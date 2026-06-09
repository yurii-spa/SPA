"""S2 — APY Momentum (chase pools whose APY is rising)."""
from __future__ import annotations

from .base import active_pools, normalize, pool_apy_history


class APYMomentumStrategy:
    """Weight pools by positive APY momentum.

    For each pool ``delta = current_apy - mean(last 5 historical APYs)``; weights
    are proportional to ``max(delta, 0)`` (only positive momentum is rewarded).
    When fewer than 3 historical runs (with per-adapter APY) are available, falls
    back to equal weight.

    History is read from ``state["history"]`` (the runner injects the
    ``orchestrator_runs.json`` ``runs`` list); tests may pass it directly.
    """

    name = "s2_momentum"
    label = "APY Momentum"
    risk_level = "high"

    MOMENTUM_LOOKBACK = 5
    MIN_RUNS = 3

    def target_weights(self, snapshot: dict, state: dict) -> dict[str, float]:
        pools = active_pools(snapshot)
        if not pools:
            return {}

        history = (state or {}).get("history") or []
        series = pool_apy_history(history)
        usable = [s for s in series.values() if len(s) >= 1]
        if len(history) < self.MIN_RUNS or len(usable) == 0:
            return self._equal_weight(pools)

        deltas: dict[str, float] = {}
        for p in pools:
            past = series.get(p["pool_id"], [])
            if not past:
                continue
            window = past[-self.MOMENTUM_LOOKBACK:]
            baseline = sum(window) / len(window)
            delta = p["apy_pct"] - baseline
            if delta > 0:
                deltas[p["pool_id"]] = delta

        if not deltas:
            # No pool has positive momentum -> hold equal weight rather than cash.
            return self._equal_weight(pools)
        return normalize(deltas)

    @staticmethod
    def _equal_weight(pools: list[dict]) -> dict[str, float]:
        w = 1.0 / len(pools)
        return {p["pool_id"]: w for p in pools}
