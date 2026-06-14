"""Annualized Sharpe ratio (MP-104).

Stdlib only. Pure function — no IO.
"""
from __future__ import annotations

import math


def calculate_sharpe(
    daily_returns: list[float], risk_free_rate: float = 0.05
) -> float:
    """Annualized Sharpe over daily *fractional* returns (0.001 == 0.1%).

    Sharpe = mean(r - rf/365) / std(r - rf/365) * sqrt(365)

    Uses the sample standard deviation (n-1). Fewer than 2 points or a
    zero/degenerate std → 0.0 (metric undefined).
    """
    n = len(daily_returns)
    if n < 2:
        return 0.0
    rf_daily = risk_free_rate / 365.0
    excess = [float(r) - rf_daily for r in daily_returns]
    mean = sum(excess) / n
    variance = sum((x - mean) ** 2 for x in excess) / (n - 1)
    std = math.sqrt(variance)
    # Epsilon guard: identical returns leave a ~1e-20 float residual, not an
    # exact 0 — treat any degenerate dispersion as "Sharpe undefined".
    if std <= 1e-12 or not math.isfinite(std):
        return 0.0
    return mean / std * math.sqrt(365.0)
