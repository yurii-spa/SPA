"""S5 — Yield Spread (allocate only to pools beating the market median)."""
from __future__ import annotations

from .base import active_pools, apply_risk_policy, normalize, tier_map


class YieldSpreadStrategy:
    """Bet on outperformance relative to the cross-sectional median APY.

    ``spread = apy - median(all active APYs)``. Pools with positive spread get
    weight proportional to their spread; non-positive spread -> weight 0. The
    result is normalised and run through the risk guard.

    Rationale: "back protocols that are beating the market, rather than any fixed
    APY threshold" — the spread re-centres automatically as the whole market
    moves.
    """

    name = "s5_yield_spread"
    label = "Yield Spread"
    risk_level = "medium"

    def target_weights(self, snapshot: dict, state: dict) -> dict[str, float]:
        pools = active_pools(snapshot)
        if not pools:
            return {}

        apys = sorted(p["apy_pct"] for p in pools)
        median = _median(apys)

        spreads: dict[str, float] = {}
        for p in pools:
            spread = p["apy_pct"] - median
            if spread > 0:
                spreads[p["pool_id"]] = spread

        if not spreads:
            # Everything is at/below the median (e.g. a flat or two-pool market):
            # nothing strictly outperforms -> stay in cash.
            return {}

        weights = normalize(spreads)
        return apply_risk_policy(weights, tier_map(snapshot))


def _median(sorted_values: list[float]) -> float:
    n = len(sorted_values)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0
