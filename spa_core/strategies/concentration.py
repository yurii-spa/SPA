"""S1 — Concentration (back the highest-APY pools heavily)."""
from __future__ import annotations

from .base import active_pools


class ConcentrationStrategy:
    """Concentrate into the top APY pools.

    top-1 -> 50%, top-2 -> 30%, the remaining pools split 20% equally. With a
    single active pool: 60% in it, 40% cash. Returns *raw* weights; the runner's
    risk guard then clips per-tier caps (so this can read above-cap before the
    guard, which is the whole point of measuring it).
    """

    name = "s1_concentration"
    label = "Concentration"
    risk_level = "high"

    def target_weights(self, snapshot: dict, state: dict) -> dict[str, float]:
        pools = active_pools(snapshot)
        if not pools:
            return {}
        ranked = sorted(pools, key=lambda p: p["apy_pct"], reverse=True)
        if len(ranked) == 1:
            return {ranked[0]["pool_id"]: 0.60}

        weights: dict[str, float] = {ranked[0]["pool_id"]: 0.50, ranked[1]["pool_id"]: 0.30}
        rest = ranked[2:]
        if rest:
            share = 0.20 / len(rest)
            for p in rest:
                weights[p["pool_id"]] = share
        return weights
