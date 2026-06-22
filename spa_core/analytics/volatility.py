"""Return volatility — daily, annualized and trailing-30d (MP-104).

Stdlib only. Pure function — no IO.
"""
from __future__ import annotations

import math

_TRADING_DAYS = 365.0  # DeFi yield accrues every calendar day


def _sample_std(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    # A constant series has exactly zero std. Compute this directly to avoid
    # the ~1e-19 float residue that (v - mean)**2 leaves when all values are
    # equal (which would otherwise fail strict == 0.0). Any real variation makes
    # max != min and takes the normal path, so this never masks volatility.
    if max(values) == min(values):
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance)


def calculate_volatility(daily_returns: list[float]) -> dict:
    """Volatility of daily *fractional* returns.

    ``daily_vol`` — sample std of all returns; ``annualized_vol`` —
    daily_vol * sqrt(365); ``vol_30d`` — annualized vol over the trailing
    30 returns. Fewer than 2 points in a window → 0.0 for that field.
    """
    rets = [float(r) for r in daily_returns]
    daily_vol = _sample_std(rets)
    vol_30d = _sample_std(rets[-30:]) * math.sqrt(_TRADING_DAYS)
    return {
        "daily_vol": daily_vol,
        "annualized_vol": daily_vol * math.sqrt(_TRADING_DAYS),
        "vol_30d": vol_30d,
    }
