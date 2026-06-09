"""S3 — Risk Parity+ (inverse-volatility weighting; the defensive pole)."""
from __future__ import annotations

from math import sqrt

from .base import active_pools, normalize, pool_apy_history


class RiskParityPlusStrategy:
    """Allocate inversely to each pool's APY volatility.

    For each pool ``sigma = std(last 10 historical APYs)``; weight ``= 1/sigma``,
    normalised to sum to 1. Pools whose ``sigma`` is zero or whose history is too
    short fall back to equal weight. Minimises allocation volatility — the
    defensive counterpart to Concentration.

    History is read from ``state["history"]``.
    """

    name = "s3_risk_parity"
    label = "Risk Parity+"
    risk_level = "low"

    VOL_LOOKBACK = 10
    MIN_POINTS = 3  # need a few points before a std is meaningful

    def target_weights(self, snapshot: dict, state: dict) -> dict[str, float]:
        pools = active_pools(snapshot)
        if not pools:
            return {}

        history = (state or {}).get("history") or []
        series = pool_apy_history(history)

        inv_vol: dict[str, float] = {}
        usable = 0
        for p in pools:
            past = series.get(p["pool_id"], [])[-self.VOL_LOOKBACK:]
            if len(past) < self.MIN_POINTS:
                continue
            sigma = _std(past)
            if sigma <= 0:
                continue
            inv_vol[p["pool_id"]] = 1.0 / sigma
            usable += 1

        # Need every active pool covered for a clean risk-parity split; otherwise
        # the comparison would be biased toward whichever pools happen to have
        # history. Fall back to equal weight.
        if usable < len(pools):
            return self._equal_weight(pools)
        return normalize(inv_vol)

    @staticmethod
    def _equal_weight(pools: list[dict]) -> dict[str, float]:
        w = 1.0 / len(pools)
        return {p["pool_id"]: w for p in pools}


def _std(values: list[float]) -> float:
    """Population standard deviation."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    return sqrt(var)
