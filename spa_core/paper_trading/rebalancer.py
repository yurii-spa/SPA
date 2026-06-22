#!/usr/bin/env python3
"""Portfolio rebalancing engine (SPA / MP-rebalancer).

Computes allocation drift between current and target weights, generates
typed RebalanceAction objects, estimates transaction costs, persists a
ring-buffered history, and provides a quick needs_rebalance predicate.

Paper mode: all actions are recorded in data/rebalance_history.json without
touching any real or on-chain capital.  The module is advisory-only and
strictly read-only with respect to positions/trades — it only writes its OWN
history artifact via atomic tmp+os.replace.

Design rules (project-wide)
============================
* **Stdlib only** — no external deps (no requests, web3, LLM SDK).
* **Atomic writes** — tmp file + os.replace on every JSON update.
* **LLM-FORBIDDEN** — no AI/LLM calls here; pure deterministic arithmetic.
* **Read-only wrt capital** — does NOT import execution/, does NOT touch
  trades.json, current_positions.json, or any other capital-state file.

Typical usage from cycle_runner
=================================
::

    from spa_core.paper_trading.rebalancer import Rebalancer

    rb = Rebalancer()
    if rb.needs_rebalance(current_weights, target_weights):
        actions = rb.compute_actions(current_weights, target_weights, equity)
        actions = rb.compute_dollar_moves(actions, equity)
        cost    = rb.estimate_rebalance_cost(actions)
        rb.record_rebalance(actions, equity, data_dir="data")

CLI (offline, exit 0 always)::

    python3 -m spa_core.paper_trading.rebalancer --check
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.rebalancer")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = str(_REPO_ROOT / "data")

HISTORY_FILENAME = "rebalance_history.json"
HISTORY_MAX = 365  # ring-buffer cap for rebalance_history.json

# ─── Action type constants ────────────────────────────────────────────────────

ACTION_INCREASE = "INCREASE"
ACTION_DECREASE = "DECREASE"
ACTION_HOLD     = "HOLD"
ACTION_EXIT     = "EXIT"
ACTION_ENTER    = "ENTER"

# Priority map: lower integer = higher priority
_PRIORITY = {
    ACTION_EXIT:     1,
    ACTION_ENTER:    2,
    ACTION_INCREASE: 3,
    ACTION_DECREASE: 4,
    ACTION_HOLD:     5,
}


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class RebalanceAction:
    """Represents a single adapter rebalance directive.

    Attributes
    ----------
    adapter_id:
        Unique protocol/adapter identifier (e.g. ``"aave_v3"``).
    current_weight:
        Current weight as a fraction in [0, 1] (e.g. 0.40 = 40 %).
    target_weight:
        Target weight as a fraction in [0, 1].
    delta_weight:
        Signed drift: ``target_weight - current_weight``.
        Positive → need to increase allocation.
    action:
        One of ``INCREASE | DECREASE | HOLD | EXIT | ENTER``.
    priority:
        Integer priority: 1 = highest (EXIT first, HOLD last).
    dollar_amount:
        Absolute USD move required.  Populated by
        :meth:`Rebalancer.compute_dollar_moves`; defaults to ``None``
        until that method is called.
    """

    adapter_id:     str
    current_weight: float
    target_weight:  float
    delta_weight:   float
    action:         str
    priority:       int
    dollar_amount:  Optional[float] = field(default=None)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict (dollar_amount omitted if None)."""
        d = asdict(self)
        if d["dollar_amount"] is None:
            del d["dollar_amount"]
        return d


# ─── Rebalancer ───────────────────────────────────────────────────────────────

class Rebalancer:
    """Deterministic portfolio rebalancing engine.

    All thresholds are expressed as **percentages** (e.g. 2.0 means 2 %).
    Internally, weights are expected as fractions in [0, 1].

    Parameters
    ----------
    rebalance_threshold_pct:
        Minimum absolute drift (in percentage points) before an adapter
        triggers a non-HOLD action.  Default: 2.0 pp.
    max_single_move_pct:
        Maximum fraction of portfolio moved for a single adapter (capped in
        :meth:`compute_dollar_moves`).  Default: 10.0 %.
    """

    REBALANCE_THRESHOLD_PCT: float = 2.0
    MAX_SINGLE_MOVE_PCT:     float = 10.0

    def __init__(
        self,
        rebalance_threshold_pct: float = REBALANCE_THRESHOLD_PCT,
        max_single_move_pct:     float = MAX_SINGLE_MOVE_PCT,
    ) -> None:
        self.rebalance_threshold_pct = float(rebalance_threshold_pct)
        self.max_single_move_pct     = float(max_single_move_pct)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_actions(
        self,
        current_weights: Dict[str, float],
        target_weights:  Dict[str, float],
        equity: float,
    ) -> List[RebalanceAction]:
        """Compute the list of rebalance actions required.

        The union of adapter IDs from both dicts is considered (missing keys
        are treated as 0.0 weight).  Adapters whose |delta| is below
        ``rebalance_threshold_pct / 100`` are classified as HOLD and
        **excluded** from the returned list.

        Action classification
        ---------------------
        * EXIT    — current > 0, target == 0 (or effectively 0)
        * ENTER   — current == 0 (or effectively 0), target > 0
        * INCREASE — target > current, |delta| ≥ threshold
        * DECREASE — target < current, |delta| ≥ threshold
        * HOLD    — |delta| < threshold (never returned; skipped silently)

        The result is sorted descending by |delta_weight| (largest moves first),
        with ties broken by action priority (EXIT > ENTER > INCREASE > DECREASE).

        Parameters
        ----------
        current_weights:
            ``{adapter_id: weight}`` — fractions in [0, 1].
        target_weights:
            ``{adapter_id: weight}`` — fractions in [0, 1].
        equity:
            Total portfolio value in USD (informational; not used in
            classification, but stored on actions for downstream callers).

        Returns
        -------
        List[RebalanceAction]
            Sorted list of non-HOLD actions.
        """
        threshold = self.rebalance_threshold_pct / 100.0
        all_ids = set(current_weights) | set(target_weights)

        actions: List[RebalanceAction] = []
        for adapter_id in all_ids:
            cur = float(current_weights.get(adapter_id, 0.0))
            tgt = float(target_weights.get(adapter_id, 0.0))
            delta = tgt - cur

            action = self._classify(cur, tgt, delta, threshold)
            if action == ACTION_HOLD:
                continue  # below threshold — skip

            actions.append(
                RebalanceAction(
                    adapter_id=adapter_id,
                    current_weight=cur,
                    target_weight=tgt,
                    delta_weight=round(delta, 8),
                    action=action,
                    priority=_PRIORITY[action],
                )
            )

        # Sort: largest absolute move first; ties by priority (lower = better)
        actions.sort(
            key=lambda a: (-abs(a.delta_weight), a.priority)
        )
        return actions

    def compute_dollar_moves(
        self,
        actions: List[RebalanceAction],
        equity: float,
    ) -> List[RebalanceAction]:
        """Populate ``dollar_amount`` on each action and apply the per-move cap.

        ``dollar_amount = min(|delta_weight| * equity, max_single_move_pct/100 * equity)``

        Modifies actions in-place and also returns the list (for chaining).

        Parameters
        ----------
        actions:
            List produced by :meth:`compute_actions`.
        equity:
            Total portfolio value in USD.

        Returns
        -------
        List[RebalanceAction]
            The same list with ``dollar_amount`` set on every element.
        """
        cap = (self.max_single_move_pct / 100.0) * equity
        for action in actions:
            raw = abs(action.delta_weight) * equity
            action.dollar_amount = round(min(raw, cap), 6)
        return actions

    def estimate_rebalance_cost(
        self,
        actions: List[RebalanceAction],
        slippage_bps: float = 10.0,
    ) -> Dict[str, Any]:
        """Estimate total transaction cost of the rebalance plan.

        ``cost_per_action = dollar_amount * (slippage_bps / 10_000)``

        Works on the ``dollar_amount`` field; if it is ``None`` the gross
        move is estimated from ``|delta_weight| * 1`` (unitless) and the cost
        will be 0 for those actions (safe degradation).

        Parameters
        ----------
        actions:
            Actions, ideally already processed by :meth:`compute_dollar_moves`.
        slippage_bps:
            Assumed slippage per leg in basis points.  Default: 10 bps.

        Returns
        -------
        dict with keys:
            ``total_moves_usd``, ``total_cost_usd``, ``cost_bps``,
            ``action_count``.
        """
        bps_factor = slippage_bps / 10_000.0
        total_moves = 0.0
        total_cost  = 0.0

        for a in actions:
            move = a.dollar_amount if a.dollar_amount is not None else 0.0
            total_moves += move
            total_cost  += move * bps_factor

        cost_bps = (total_cost / total_moves * 10_000.0) if total_moves > 0 else 0.0

        return {
            "total_moves_usd": round(total_moves, 6),
            "total_cost_usd":  round(total_cost,  6),
            "cost_bps":        round(cost_bps,    4),
            "action_count":    len(actions),
        }

    def record_rebalance(
        self,
        actions: List[RebalanceAction],
        equity: float,
        data_dir: str = _DEFAULT_DATA_DIR,
    ) -> None:
        """Append a rebalance event to ``data/rebalance_history.json``.

        The file is created if it does not exist.  Entries are kept in a
        ring-buffer of :data:`HISTORY_MAX` records (oldest evicted first).
        All writes are **atomic**: written to a temporary file, then
        ``os.replace``'d into place.

        Schema of each history entry::

            {
              "date":            "2026-06-12",
              "equity":          100017.45,
              "actions_count":   2,
              "total_moves_usd": 5000.00,
              "cost_usd":        5.00,
              "actions": [
                {
                  "adapter_id":   "aave_v3",
                  "action":       "DECREASE",
                  "delta_weight": -0.05,
                  "dollar_amount": 5000.00
                },
                ...
              ]
            }

        Parameters
        ----------
        actions:
            Actions to record (should have ``dollar_amount`` set).
        equity:
            Portfolio equity at rebalance time (USD).
        data_dir:
            Directory for the history file.  Defaults to repo ``data/``.
        """
        data_path = Path(data_dir)
        data_path.mkdir(parents=True, exist_ok=True)
        history_file = data_path / HISTORY_FILENAME

        # Load existing history (tolerant)
        history: List[Dict[str, Any]] = []
        if history_file.exists():
            try:
                raw = json.loads(history_file.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    history = raw
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("rebalance_history.json unreadable — starting fresh: %s", exc)

        # Build cost estimate
        cost_info = self.estimate_rebalance_cost(actions)

        today = date.today().isoformat()
        entry: Dict[str, Any] = {
            "date":            today,
            "equity":          round(equity, 6),
            "actions_count":   len(actions),
            "total_moves_usd": cost_info["total_moves_usd"],
            "cost_usd":        cost_info["total_cost_usd"],
            "actions": [
                {
                    "adapter_id":    a.adapter_id,
                    "action":        a.action,
                    "delta_weight":  round(a.delta_weight, 8),
                    "dollar_amount": round(a.dollar_amount, 6) if a.dollar_amount is not None else None,
                }
                for a in actions
            ],
        }

        # Append + ring-buffer eviction
        history.append(entry)
        if len(history) > HISTORY_MAX:
            history = history[-HISTORY_MAX:]

        # Atomic write
        atomic_save(history, str(history_file))
    def needs_rebalance(
        self,
        current_weights: Dict[str, float],
        target_weights:  Dict[str, float],
    ) -> bool:
        """Return True if any adapter drifted beyond the threshold.

        This is a cheap predicate (no action objects allocated) that cycle_runner
        can call before committing to the full :meth:`compute_actions` path.

        Parameters
        ----------
        current_weights:
            ``{adapter_id: weight}`` — fractions in [0, 1].
        target_weights:
            ``{adapter_id: weight}`` — fractions in [0, 1].

        Returns
        -------
        bool
        """
        threshold = self.rebalance_threshold_pct / 100.0
        _eps = 1e-9  # IEEE-754 tolerance for exact-boundary values
        all_ids = set(current_weights) | set(target_weights)
        for adapter_id in all_ids:
            cur = float(current_weights.get(adapter_id, 0.0))
            tgt = float(target_weights.get(adapter_id, 0.0))
            if abs(tgt - cur) >= threshold - _eps:
                return True
        return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(
        cur: float,
        tgt: float,
        delta: float,
        threshold: float,
    ) -> str:
        """Classify the action for a single adapter.

        Logic:
        - |delta| < threshold                 → HOLD (no action)
        - cur ≈ 0 and tgt > 0                 → ENTER
        - cur > 0 and tgt ≈ 0                 → EXIT
        - delta > 0 and |delta| ≥ threshold   → INCREASE
        - delta < 0 and |delta| ≥ threshold   → DECREASE
        """
        _ZERO = 1e-9    # effective-zero tolerance
        _EPS  = 1e-9    # floating-point tolerance for boundary comparison

        abs_delta = abs(delta)
        # Use a small epsilon for the boundary so that weights like 0.42-0.40
        # (which IEEE-754 rounds to 0.01999…) still trigger at exactly threshold.
        if abs_delta < threshold - _EPS:
            return ACTION_HOLD

        cur_zero = cur < _ZERO
        tgt_zero = tgt < _ZERO

        if tgt_zero and not cur_zero:
            return ACTION_EXIT
        if cur_zero and not tgt_zero:
            return ACTION_ENTER
        if delta > 0:
            return ACTION_INCREASE
        return ACTION_DECREASE


# ─── CLI entry-point ──────────────────────────────────────────────────────────

def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="SPA Rebalancer — compute and optionally record rebalance actions."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print results without writing (default).",
    )
    parser.add_argument(
        "--data-dir",
        default=_DEFAULT_DATA_DIR,
        help="Data directory for rebalance_history.json.",
    )
    args = parser.parse_args(argv)

    # Example self-test with illustrative weights
    rb = Rebalancer()
    current = {"aave_v3": 0.40, "compound_v3": 0.35, "morpho": 0.20, "cash": 0.05}
    target  = {"aave_v3": 0.35, "compound_v3": 0.35, "morpho": 0.25, "cash": 0.05}
    equity  = 100_000.0

    needs = rb.needs_rebalance(current, target)
    print(f"needs_rebalance: {needs}")

    actions = rb.compute_actions(current, target, equity)
    actions = rb.compute_dollar_moves(actions, equity)
    cost    = rb.estimate_rebalance_cost(actions)

    for a in actions:
        print(
            f"  {a.action:8s}  {a.adapter_id:20s}  "
            f"delta={a.delta_weight:+.4f}  "
            f"${a.dollar_amount:,.2f}"
        )
    print(f"cost estimate: {cost}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(_main())
