"""S0 — Baseline (equal weight across all active pools)."""
from __future__ import annotations

from .base import active_pools, apply_risk_policy, tier_map


class BaselineStrategy:
    """Naive 1/N allocation across every active pool, then the risk guard.

    The neutral reference point every other strategy is judged against.
    """

    name = "s0_baseline"
    label = "Baseline (Equal Weight)"
    risk_level = "low"

    def target_weights(self, snapshot: dict, state: dict) -> dict[str, float]:
        pools = active_pools(snapshot)
        if not pools:
            return {}
        w = 1.0 / len(pools)
        weights = {p["pool_id"]: w for p in pools}
        return apply_risk_policy(weights, tier_map(snapshot))

    def run_day(self, apy_map: dict = None) -> float:
        """Thin adapter for cycle_runner compatibility.
        Returns equal-weighted average APY across all pools in apy_map."""
        _FALLBACK_APY = 4.0  # typical average of whitelisted pools
        if not apy_map:
            return _FALLBACK_APY
        values = [
            float(v) for v in apy_map.values()
            if isinstance(v, (int, float)) and float(v) > 0
        ]
        if values:
            return float(sum(values) / len(values))
        return _FALLBACK_APY
