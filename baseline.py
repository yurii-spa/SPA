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
