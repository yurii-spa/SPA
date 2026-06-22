#!/usr/bin/env python3
"""Withdrawal planner for SPA portfolio (MP-577).

Computes optimal withdrawal sequences from DeFi adapters with minimal
portfolio impact.  Three withdrawal strategies are supported:

* **min_impact** — liquidates the most liquid T1 adapters first,
  minimising price impact and slippage.
* **max_yield** — preserves high-yield positions; withdraws from the
  lowest-APY adapters first to maintain portfolio performance.
* **pro_rata** — withdraws proportionally from every position,
  maintaining existing portfolio weights.

Design rules (project-wide)
============================
* **Stdlib only** — no external deps (no requests, web3, LLM SDK).
* **Atomic writes** — tmp file + os.replace on every JSON update.
* **LLM-FORBIDDEN** — no AI/LLM calls here; pure deterministic arithmetic.
* **Read-only wrt capital** — does NOT import execution/, does NOT touch
  trades.json, current_positions.json, or any other capital-state file.
  Only writes its own history artifact via atomic tmp+os.replace.

Typical usage from cycle_runner
=================================
::

    from spa_core.paper_trading.withdrawal_planner import WithdrawalPlanner

    planner = WithdrawalPlanner()
    portfolio = {"aave_v3": 40000.0, "compound_v3": 35000.0, "morpho": 20000.0}
    adapters = {
        "aave_v3":     {"apy": 3.5, "tvl": 9e9, "tier": "T1"},
        "compound_v3": {"apy": 4.8, "tvl": 2e9, "tier": "T1"},
        "morpho":      {"apy": 6.5, "tvl": 8e8, "tier": "T1"},
    }
    steps = planner.plan_withdrawal(15000.0, portfolio, adapters)
    plan  = planner.get_withdrawal_sequence(15000.0, portfolio, adapters, strategy="min_impact")
    planner.record_withdrawal(plan, {"aave_v3": 10000.0, "compound_v3": 5000.0})

CLI (offline, exit 0 always)::

    python3 -m spa_core.paper_trading.withdrawal_planner --check
    python3 -m spa_core.paper_trading.withdrawal_planner --run
    python3 -m spa_core.paper_trading.withdrawal_planner --run --data-dir data
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.withdrawal_planner")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = str(_REPO_ROOT / "data")

HISTORY_FILENAME = "withdrawal_history.json"
HISTORY_MAX = 365  # ring-buffer cap (one year)

# ─── Tier liquidity factors ───────────────────────────────────────────────────
# Effective tradeable depth = TVL * factor.
# Higher factor → deeper effective depth → lower slippage per dollar withdrawn.
# T1 protocols (Aave, Compound) have large, liquid markets: 20% of TVL depth.
# T3 protocols are thin: only ~1% of TVL depth.
_TIER_LIQUIDITY_FACTOR: Dict[str, float] = {
    "T1": 0.20,   # T1: ~20% of TVL is effective tradeable depth (most liquid)
    "T2": 0.05,   # T2: ~5% — moderately liquid
    "T3": 0.01,   # T3: ~1% — thin, illiquid pools
}
_DEFAULT_LIQUIDITY_FACTOR: float = 0.10  # conservative fallback for unknown tiers

# Strategy name constants
STRATEGY_MIN_IMPACT = "min_impact"
STRATEGY_MAX_YIELD  = "max_yield"
STRATEGY_PRO_RATA   = "pro_rata"

_VALID_STRATEGIES = frozenset([STRATEGY_MIN_IMPACT, STRATEGY_MAX_YIELD, STRATEGY_PRO_RATA])


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class WithdrawalStep:
    """A single adapter withdrawal directive.

    Attributes
    ----------
    adapter_id:
        Unique protocol/adapter identifier (e.g. ``"aave_v3"``).
    amount_usd:
        Dollar amount to withdraw from this adapter.
    pct_of_position:
        Fraction of the current position being withdrawn (0..1).
        1.0 means the entire position is being liquidated.
    order:
        Execution order index (1 = first to execute).
    estimated_slippage:
        Estimated price impact as a fraction (0..1).
        Populated by :meth:`WithdrawalPlanner.estimate_slippage`;
        defaults to ``0.0`` until set.
    """

    adapter_id:         str
    amount_usd:         float
    pct_of_position:    float
    order:              int
    estimated_slippage: float = field(default=0.0)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)


# ─── WithdrawalPlanner ───────────────────────────────────────────────────────

class WithdrawalPlanner:
    """Deterministic withdrawal planning engine.

    All monetary comparisons use a small tolerance (1e-9) to avoid
    IEEE-754 precision noise in boundary conditions.

    Parameters
    ----------
    min_position_residual_usd:
        Minimum remaining position size after a partial withdrawal.
        If the residual would fall below this threshold the position is
        swept entirely (avoiding tiny dust positions).  Default: 100 USD.
    slippage_cap:
        Warning threshold for per-step slippage (0..1).  Steps whose
        estimated slippage exceeds this value are flagged in the plan's
        ``warnings`` list but are *not* excluded.  Default: 0.05 (5 %).
    """

    MIN_POSITION_RESIDUAL_USD: float = 100.0
    SLIPPAGE_CAP:              float = 0.05

    def __init__(
        self,
        min_position_residual_usd: float = MIN_POSITION_RESIDUAL_USD,
        slippage_cap:               float = SLIPPAGE_CAP,
    ) -> None:
        self.min_position_residual_usd = float(min_position_residual_usd)
        self.slippage_cap              = float(slippage_cap)

    # ──────────────────────────────────────────────────────────────────────────
    # Core public API
    # ──────────────────────────────────────────────────────────────────────────

    def plan_withdrawal(
        self,
        amount_usd: float,
        portfolio:  Dict[str, float],
        adapters:   Dict[str, Dict[str, Any]],
        strategy:   str = STRATEGY_MIN_IMPACT,
    ) -> List[WithdrawalStep]:
        """Compute an ordered list of withdrawal steps.

        The planner tries to source the full ``amount_usd`` from available
        positions.  If total portfolio capital is insufficient, the plan is
        capped to what is available.

        Parameters
        ----------
        amount_usd:
            Total USD to withdraw (must be positive; non-positive returns ``[]``).
        portfolio:
            ``{adapter_id: position_usd}`` — current positions in USD.
        adapters:
            ``{adapter_id: {apy, tvl, tier, …}}`` — live adapter metadata.
            Adapters absent from *portfolio* are ignored.
        strategy:
            Withdrawal strategy name.  One of:

            * ``"min_impact"`` *(default)* — most liquid T1 adapters first.
            * ``"max_yield"``  — lowest-APY positions first.
            * ``"pro_rata"``   — proportional to current position weights.

        Returns
        -------
        List[WithdrawalStep]
            Ordered steps (``order`` = 1 is first to execute), each with
            ``estimated_slippage`` already populated.

        Raises
        ------
        ValueError
            If *strategy* is not recognised.
        """
        if strategy not in _VALID_STRATEGIES:
            raise ValueError(
                f"Unknown strategy {strategy!r}. "
                f"Valid strategies: {sorted(_VALID_STRATEGIES)}"
            )

        amount_usd = float(amount_usd)
        if amount_usd <= 0.0:
            return []

        # Only consider adapters with a positive position
        active: Dict[str, float] = {
            aid: float(pos)
            for aid, pos in portfolio.items()
            if float(pos) > 0.0
        }
        if not active:
            return []

        # Cap to total available capital
        total_available = sum(active.values())
        amount_usd = min(amount_usd, total_available)

        # Strategy-specific ordering / allocation
        if strategy == STRATEGY_MIN_IMPACT:
            ordered_ids = self._sort_min_impact(active, adapters)
            steps = self._plan_sequential(amount_usd, active, adapters, ordered_ids)
        elif strategy == STRATEGY_MAX_YIELD:
            ordered_ids = self._sort_max_yield(active, adapters)
            steps = self._plan_sequential(amount_usd, active, adapters, ordered_ids)
        else:  # STRATEGY_PRO_RATA
            ordered_ids = sorted(active.keys())  # deterministic order
            steps = self._plan_pro_rata(amount_usd, active, adapters, ordered_ids)

        # Attach slippage estimates to every step
        for step in steps:
            liquidity_data = adapters.get(step.adapter_id, {})
            step.estimated_slippage = self.estimate_slippage(step, liquidity_data)

        return steps

    def estimate_slippage(
        self,
        step:           WithdrawalStep,
        liquidity_data: Dict[str, Any],
    ) -> float:
        """Estimate price impact (slippage) for a single withdrawal step.

        Uses a linear price-impact model::

            slippage = amount_usd / (tvl * liquidity_factor)

        clamped to ``[0.0, 1.0]``.  When TVL is zero or negative, a
        conservative baseline of 1 000 000 USD is assumed.

        Parameters
        ----------
        step:
            The withdrawal step to estimate slippage for.
        liquidity_data:
            Adapter metadata dict.  Recognised keys:

            * ``tvl``               — total value locked in USD.
            * ``tier``              — ``"T1"`` / ``"T2"`` / ``"T3"``.
            * ``liquidity_factor``  — explicit override (overrides tier factor).

        Returns
        -------
        float
            Estimated slippage fraction in ``[0.0, 1.0]``.
        """
        tvl    = float(liquidity_data.get("tvl",  0.0))
        tier   = str(liquidity_data.get("tier", "T2"))
        factor = float(
            liquidity_data.get(
                "liquidity_factor",
                _TIER_LIQUIDITY_FACTOR.get(tier, _DEFAULT_LIQUIDITY_FACTOR),
            )
        )

        # Guard against missing / invalid TVL
        if tvl <= 0.0:
            tvl = 1_000_000.0  # conservative $1M baseline

        effective_depth = tvl * factor
        if effective_depth <= 0.0:
            return 1.0

        slippage = step.amount_usd / effective_depth
        return max(0.0, min(1.0, slippage))

    def get_withdrawal_sequence(
        self,
        amount_usd: float,
        portfolio:  Dict[str, float],
        adapters:   Dict[str, Dict[str, Any]],
        strategy:   str = STRATEGY_MIN_IMPACT,
    ) -> Dict[str, Any]:
        """Produce a comprehensive withdrawal plan dictionary.

        Calls :meth:`plan_withdrawal` and enriches the result with
        summary statistics, warnings, and ISO-8601 metadata.

        Parameters
        ----------
        amount_usd:
            Total USD to withdraw.
        portfolio:
            ``{adapter_id: position_usd}`` — current positions.
        adapters:
            ``{adapter_id: {apy, tvl, tier, …}}`` — adapter metadata.
        strategy:
            Withdrawal strategy name.  Default: ``"min_impact"``.

        Returns
        -------
        dict with keys:
            ``generated_at``, ``strategy``, ``requested_usd``,
            ``planned_usd``, ``coverage_pct``, ``step_count``,
            ``total_slippage_cost_usd``, ``weighted_slippage``,
            ``steps`` *(list of step dicts)*, ``warnings``.
        """
        steps = self.plan_withdrawal(amount_usd, portfolio, adapters, strategy)

        planned_usd         = sum(s.amount_usd for s in steps)
        total_slippage_cost = sum(s.amount_usd * s.estimated_slippage for s in steps)
        weighted_slippage   = (
            total_slippage_cost / planned_usd if planned_usd > 0.0 else 0.0
        )

        amount_usd_f = float(amount_usd)
        coverage_pct = min(1.0, planned_usd / amount_usd_f) if amount_usd_f > 0.0 else 1.0

        warnings: List[str] = []
        if planned_usd < amount_usd_f - 1e-6:
            warnings.append(
                f"Insufficient portfolio capital: planned ${planned_usd:,.2f} "
                f"of requested ${amount_usd_f:,.2f}."
            )
        for step in steps:
            if step.estimated_slippage > self.slippage_cap:
                warnings.append(
                    f"Step {step.order} ({step.adapter_id}): estimated slippage "
                    f"{step.estimated_slippage:.4%} exceeds cap "
                    f"{self.slippage_cap:.4%}."
                )

        return {
            "generated_at":         datetime.now(timezone.utc).isoformat(),
            "strategy":             strategy,
            "requested_usd":        round(amount_usd_f, 6),
            "planned_usd":          round(planned_usd,  6),
            "coverage_pct":         round(coverage_pct, 8),
            "step_count":           len(steps),
            "total_slippage_cost_usd": round(total_slippage_cost, 6),
            "weighted_slippage":    round(weighted_slippage, 8),
            "steps":                [s.to_dict() for s in steps],
            "warnings":             warnings,
        }

    def record_withdrawal(
        self,
        plan:           Dict[str, Any],
        actual_amounts: Dict[str, float],
        data_dir:       str = _DEFAULT_DATA_DIR,
    ) -> None:
        """Append a completed withdrawal to ``data/withdrawal_history.json``.

        The file is created if it does not exist.  Entries are kept in a
        ring-buffer of :data:`HISTORY_MAX` records (oldest evicted first).
        All writes are **atomic**: written to a temporary file then
        ``os.replace``'d into place.

        Parameters
        ----------
        plan:
            Plan dict produced by :meth:`get_withdrawal_sequence`.
        actual_amounts:
            ``{adapter_id: actual_usd_withdrawn}`` — real execution amounts
            (may differ from planned due to liquidity or rounding).
        data_dir:
            Directory for the history file.  Defaults to repo ``data/``.

        Schema of each history entry::

            {
              "recorded_at":       "2026-06-13T08:00:00+00:00",
              "strategy":          "min_impact",
              "requested_usd":     15000.0,
              "planned_usd":       15000.0,
              "actual_usd":        14850.0,
              "execution_gap_usd": 150.0,
              "coverage_pct":      1.0,
              "step_count":        2,
              "weighted_slippage": 0.000012,
              "steps":             [...],
              "actual_amounts":    {"aave_v3": 10000.0, "compound_v3": 4850.0},
              "warnings":          []
            }
        """
        data_path = Path(data_dir)
        data_path.mkdir(parents=True, exist_ok=True)
        history_file = data_path / HISTORY_FILENAME

        # Load existing history (tolerant of missing / corrupt file)
        history: List[Dict[str, Any]] = []
        if history_file.exists():
            try:
                raw = json.loads(history_file.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    history = raw
            except (json.JSONDecodeError, OSError) as exc:
                log.warning(
                    "withdrawal_history.json unreadable — starting fresh: %s", exc
                )

        actual_total  = sum(float(v) for v in actual_amounts.values())
        planned_usd   = float(plan.get("planned_usd", 0.0))
        execution_gap = round(abs(planned_usd - actual_total), 6)

        entry: Dict[str, Any] = {
            "recorded_at":       datetime.now(timezone.utc).isoformat(),
            "strategy":          plan.get("strategy", "unknown"),
            "requested_usd":     plan.get("requested_usd", 0.0),
            "planned_usd":       planned_usd,
            "actual_usd":        round(actual_total, 6),
            "execution_gap_usd": execution_gap,
            "coverage_pct":      plan.get("coverage_pct",    0.0),
            "step_count":        plan.get("step_count",      0),
            "weighted_slippage": plan.get("weighted_slippage", 0.0),
            "steps":             plan.get("steps", []),
            "actual_amounts":    {k: round(float(v), 6) for k, v in actual_amounts.items()},
            "warnings":          plan.get("warnings", []),
        }

        # Append + ring-buffer eviction
        history.append(entry)
        if len(history) > HISTORY_MAX:
            history = history[-HISTORY_MAX:]

        # Atomic write: tmp file + os.replace
        atomic_save(history, str(history_file))
    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _sort_min_impact(
        self,
        positions: Dict[str, float],
        adapters:  Dict[str, Dict[str, Any]],
    ) -> List[str]:
        """Sort adapter IDs for minimum-impact withdrawal.

        Priority (ascending sort key):
        1. Tier rank: T1 first (rank 1), T2 (rank 2), T3 (rank 3), unknown (rank 9).
        2. Within same tier: highest TVL first (most liquid → least impact).
        3. Alphabetical adapter ID for determinism.
        """
        def _key(aid: str) -> tuple:
            meta  = adapters.get(aid, {})
            tier  = str(meta.get("tier", "T9"))
            trank = {"T1": 1, "T2": 2, "T3": 3}.get(tier, 9)
            tvl   = -float(meta.get("tvl", 0.0))   # negate → highest first
            return (trank, tvl, aid)

        return sorted(positions.keys(), key=_key)

    def _sort_max_yield(
        self,
        positions: Dict[str, float],
        adapters:  Dict[str, Dict[str, Any]],
    ) -> List[str]:
        """Sort adapter IDs for max-yield withdrawal.

        Withdraw from lowest-APY adapters first so that high-yield
        positions survive as long as possible.  Tie-break: alphabetical.
        """
        def _key(aid: str) -> tuple:
            meta = adapters.get(aid, {})
            apy  = float(meta.get("apy", 0.0))
            return (apy, aid)

        return sorted(positions.keys(), key=_key)

    def _plan_sequential(
        self,
        amount_usd:  float,
        positions:   Dict[str, float],
        adapters:    Dict[str, Dict[str, Any]],
        ordered_ids: List[str],
    ) -> List[WithdrawalStep]:
        """Fill the requested amount sequentially from the ordered adapter list.

        Sweeps each adapter in turn until ``amount_usd`` is fully sourced.
        Avoids leaving dust residuals smaller than
        :attr:`min_position_residual_usd`.
        """
        steps: List[WithdrawalStep] = []
        remaining = amount_usd
        order     = 1

        for aid in ordered_ids:
            if remaining <= 1e-9:
                break
            position = positions.get(aid, 0.0)
            if position <= 0.0:
                continue

            take = min(remaining, position)

            # Sweep if the residual would be a tiny dust amount.
            # After the sweep, take may exceed remaining — that is intentional
            # (we accept slightly over-withdrawing to avoid dust positions).
            residual = position - take
            if 0.0 < residual < self.min_position_residual_usd:
                take = position  # take the whole position (may exceed remaining)

            # Hard cap: never exceed the position itself
            take = min(take, position)

            if take <= 1e-9:
                continue

            pct = min(take / position, 1.0) if position > 0.0 else 0.0

            steps.append(
                WithdrawalStep(
                    adapter_id=aid,
                    amount_usd=round(take, 6),
                    pct_of_position=round(pct, 8),
                    order=order,
                )
            )
            remaining = max(0.0, remaining - take)   # guard against tiny negatives
            order     += 1

        return steps

    def _plan_pro_rata(
        self,
        amount_usd:  float,
        positions:   Dict[str, float],
        adapters:    Dict[str, Dict[str, Any]],
        ordered_ids: List[str],
    ) -> List[WithdrawalStep]:
        """Withdraw proportionally from all positions (pro-rata strategy).

        Each adapter contributes ``weight = position / total_portfolio``
        of the requested amount.  Tiny residuals are swept for cleanliness.
        """
        total_portfolio = sum(positions.values())
        if total_portfolio <= 0.0:
            return []

        steps: List[WithdrawalStep] = []

        for order, aid in enumerate(ordered_ids, start=1):
            position = positions.get(aid, 0.0)
            if position <= 0.0:
                continue

            weight = position / total_portfolio
            take   = amount_usd * weight

            # Sweep dust residual
            residual = position - take
            if 0.0 < residual < self.min_position_residual_usd:
                take = position

            if take <= 1e-9:
                continue

            pct = min(take / position, 1.0) if position > 0.0 else 0.0

            steps.append(
                WithdrawalStep(
                    adapter_id=aid,
                    amount_usd=round(take, 6),
                    pct_of_position=round(pct, 8),
                    order=order,
                )
            )

        return steps


# ─── CLI entry-point ──────────────────────────────────────────────────────────

def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="SPA WithdrawalPlanner — compute and optionally record a withdrawal plan."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Compute and print results without writing to disk (default).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute and atomically write to data/withdrawal_history.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=_DEFAULT_DATA_DIR,
        help="Data directory for withdrawal_history.json.",
    )
    args = parser.parse_args(argv)

    if not args.run:
        args.check = True

    planner = WithdrawalPlanner()

    # Illustrative portfolio / adapters for self-test
    portfolio: Dict[str, float] = {
        "aave_v3":           40_000.0,
        "compound_v3":       30_000.0,
        "morpho_steakhouse": 15_000.0,
        "yearn_v3":          10_000.0,
    }
    adapters: Dict[str, Dict[str, Any]] = {
        "aave_v3":           {"apy": 3.5, "tvl": 9_000_000_000.0, "tier": "T1"},
        "compound_v3":       {"apy": 4.8, "tvl": 2_000_000_000.0, "tier": "T1"},
        "morpho_steakhouse": {"apy": 6.5, "tvl":   800_000_000.0, "tier": "T1"},
        "yearn_v3":          {"apy": 5.2, "tvl":   300_000_000.0, "tier": "T2"},
    }
    amount = 20_000.0

    for strategy in (STRATEGY_MIN_IMPACT, STRATEGY_MAX_YIELD, STRATEGY_PRO_RATA):
        plan = planner.get_withdrawal_sequence(amount, portfolio, adapters, strategy=strategy)
        print(f"\n=== Strategy: {strategy} ===")
        print(
            f"Requested: ${plan['requested_usd']:>12,.2f}  "
            f"Planned: ${plan['planned_usd']:>12,.2f}  "
            f"Coverage: {plan['coverage_pct']:.2%}"
        )
        print(f"Weighted slippage: {plan['weighted_slippage']:.6%}")
        for step in plan["steps"]:
            print(
                f"  [{step['order']}] {step['adapter_id']:25s}  "
                f"${step['amount_usd']:>12,.2f}  "
                f"({step['pct_of_position']:.2%} of pos)  "
                f"slip={step['estimated_slippage']:.6%}"
            )
        if plan["warnings"]:
            for w in plan["warnings"]:
                print(f"  ⚠  {w}")

    if args.run:
        plan = planner.get_withdrawal_sequence(
            amount, portfolio, adapters, strategy=STRATEGY_MIN_IMPACT
        )
        actual = {
            s["adapter_id"]: round(s["amount_usd"] * 0.999, 6)   # 0.1% execution shortfall
            for s in plan["steps"]
        }
        planner.record_withdrawal(plan, actual, data_dir=args.data_dir)
        print(f"\nRecorded → {args.data_dir}/{HISTORY_FILENAME}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(_main())
