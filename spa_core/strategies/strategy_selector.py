"""
spa_core.strategies.strategy_selector — SPA-V408 shadow→allocator feedback loop.

Reads the shadow-strategy leaderboard (``data/strategy_shadow_comparison.json``,
written by :mod:`spa_core.strategies.comparator`) and selects the best-performing
shadow strategy by **Sortino** (primary) with **Sharpe** as the tiebreak. The
chosen strategy's live target weights are read from its persisted virtual
portfolio (``data/strategies/{name}.json``) and normalised so the allocator can
use them as a *base* distribution — before its own tier caps and risk-grade
exclusions are applied on top.

Confidence is gated on how long a strategy has been running:

    * < 7 days       → not a candidate at all (insufficient data)
    * 7‥14 days      → ``"low"``     (eligible, but NOT selectable)
    * 15‥29 days     → ``"medium"``  (selectable)
    * ≥ 30 days      → ``"high"``    (selectable)

:meth:`StrategySelector.select_best` only ever returns a strategy whose
confidence is ``"medium"`` or ``"high"`` — a thin, statistically-cautious gate so
the real allocator never chases a few days of noise.

Strictly read-only / advisory. Stdlib only. Does NOT import ``execution``,
``feed_health`` or the deterministic risk agents — it only reads their JSON
snapshots, exactly like the rest of the shadow framework.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_COMPARISON = _PROJECT_ROOT / "data" / "strategy_shadow_comparison.json"
_DEFAULT_STRATEGIES_DIR = _PROJECT_ROOT / "data" / "strategies"

#: A strategy needs at least this many days before it is even a candidate.
MIN_DAYS_FOR_CANDIDATE = 7
#: ≥ this many days of history → "medium" confidence (the selectable floor).
MEDIUM_CONFIDENCE_DAYS = 15
#: ≥ this many days of history → "high" confidence.
HIGH_CONFIDENCE_DAYS = 30

#: Confidence levels that :meth:`select_best` will act on.
_SELECTABLE = ("medium", "high")


def _as_float(value) -> float | None:
    """Best-effort float coercion; ``None`` for unparseable / non-finite input."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf guard
        return None
    return f


def confidence_for(days_running, sortino) -> str | None:
    """Classify a strategy's confidence from its run length and Sortino.

    Returns ``None`` when the strategy is not even a candidate (Sortino missing,
    or fewer than :data:`MIN_DAYS_FOR_CANDIDATE` days). Otherwise one of
    ``"low"`` / ``"medium"`` / ``"high"``.
    """
    if _as_float(sortino) is None:
        return None
    try:
        days = int(days_running)
    except (TypeError, ValueError):
        return None
    if days < MIN_DAYS_FOR_CANDIDATE:
        return None
    if days >= HIGH_CONFIDENCE_DAYS:
        return "high"
    if days >= MEDIUM_CONFIDENCE_DAYS:
        return "medium"
    return "low"


class StrategySelector:
    """Pick the best shadow strategy and surface its target weights."""

    def __init__(
        self,
        comparison_path: str | Path = _DEFAULT_COMPARISON,
        strategies_dir: str | Path = _DEFAULT_STRATEGIES_DIR,
    ):
        self.comparison_path = Path(comparison_path)
        self.strategies_dir = Path(strategies_dir)

    # ── leaderboard loading ────────────────────────────────────────────────
    def _load_comparison(self) -> dict | None:
        """Read the shadow leaderboard JSON, or ``None`` on any failure."""
        if not self.comparison_path.exists():
            return None
        try:
            with open(self.comparison_path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            return None
        return doc if isinstance(doc, dict) else None

    def _candidates(self) -> list[dict]:
        """Eligible strategies (Sortino present, ≥ min days), ranked best-first.

        Ranking key: Sortino descending, Sharpe descending as the tiebreak.
        Each returned row is annotated with its ``confidence``.
        """
        doc = self._load_comparison()
        if not doc:
            return []
        rows = doc.get("strategies")
        if not isinstance(rows, list):
            return []

        cands: list[dict] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            name = r.get("name")
            if not name:
                continue
            sortino = _as_float(r.get("sortino"))
            days = r.get("days_running")
            conf = confidence_for(days, sortino)
            if conf is None:  # not a candidate (no Sortino or < min days)
                continue
            cands.append(
                {
                    "name": str(name),
                    "sortino": sortino,
                    "sharpe": _as_float(r.get("sharpe")),
                    "days_running": int(days),
                    "confidence": conf,
                }
            )

        # Sortino primary (desc), Sharpe tiebreak (desc). Missing Sharpe → -inf.
        cands.sort(
            key=lambda c: (
                c["sortino"],
                c["sharpe"] if c["sharpe"] is not None else float("-inf"),
            ),
            reverse=True,
        )
        return cands

    # ── public API ─────────────────────────────────────────────────────────
    def select_best(self) -> dict | None:
        """Return the best selectable shadow strategy, or ``None``.

        ``None`` is returned when:

        * the comparison file is missing / unreadable,
        * no strategy has a non-null Sortino (no real data yet),
        * no strategy reaches ``"medium"`` confidence (all run < 15 days).

        On success returns::

            {
              "strategy_id":        "s1_concentration",
              "sortino":            1.23,
              "sharpe":             0.98,          # may be None
              "confidence":         "high" | "medium",
              "days_running":       35,
              "allocation_weights": {pool_id: weight, ...},  # normalised to 1.0
              "selected_at":        "<ISO-8601 UTC>",
              "reason":             "highest Sortino (1.230) with high confidence (N=35 days)",
            }
        """
        cands = self._candidates()
        # Only "medium"/"high" are selectable; "low" stays advisory-only.
        selectable = [c for c in cands if c["confidence"] in _SELECTABLE]
        if not selectable:
            return None

        best = selectable[0]
        weights = self._weights_for(best["name"])
        return {
            "strategy_id": best["name"],
            "sortino": best["sortino"],
            "sharpe": best["sharpe"],
            "confidence": best["confidence"],
            "days_running": best["days_running"],
            "allocation_weights": weights,
            "selected_at": datetime.now(timezone.utc).isoformat(),
            "reason": (
                f"highest Sortino ({best['sortino']:.3f}) with "
                f"{best['confidence']} confidence (N={best['days_running']} days)"
            ),
        }

    def get_allocation_weights_for_best(self) -> dict[str, float] | None:
        """Normalised ``{pool_id: weight}`` for the best strategy, else ``None``.

        ``None`` when no strategy is selectable *or* the selected strategy has no
        usable persisted positions.
        """
        best = self.select_best()
        if not best:
            return None
        weights = best.get("allocation_weights") or {}
        return weights or None

    # ── weights from the persisted virtual portfolio ──────────────────────
    def _weights_for(self, name: str) -> dict[str, float]:
        """Read ``data/strategies/{name}.json`` and normalise its positions.

        The strategy's current ``positions`` (USD per pool) are normalised so the
        deployed mass sums to 1.0 — a clean probability distribution over pools
        that the allocator treats like any model's raw weights. Returns ``{}`` if
        the portfolio file is missing, unreadable, or holds no positive position.
        """
        path = self.strategies_dir / f"{name}.json"
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}

        positions = data.get("positions")
        if not isinstance(positions, dict) or not positions:
            return {}

        clean: dict[str, float] = {}
        for pool_id, usd in positions.items():
            v = _as_float(usd)
            if v is not None and v > 0:
                clean[str(pool_id)] = v

        total = sum(clean.values())
        if total <= 0:
            return {}
        return {p: v / total for p, v in clean.items()}


__all__ = ["StrategySelector", "confidence_for", "MIN_DAYS_FOR_CANDIDATE",
           "MEDIUM_CONFIDENCE_DAYS", "HIGH_CONFIDENCE_DAYS"]
