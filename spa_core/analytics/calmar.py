"""Calmar ratio (MP-104).

Stdlib only. Pure function — no IO.
"""
from __future__ import annotations

import math


def calculate_calmar(
    total_return_annualized: float, max_drawdown_pct: float
) -> float:
    """Calmar = annualized return / |max drawdown|.

    Both inputs must be on the same scale (e.g. both in percent).
    A zero or non-finite drawdown → 0.0 (metric undefined).
    """
    dd = abs(float(max_drawdown_pct))
    if dd == 0.0 or not math.isfinite(dd):
        return 0.0
    return float(total_return_annualized) / dd
