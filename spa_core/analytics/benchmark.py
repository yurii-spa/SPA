"""SPA vs fixed-rate deposit benchmark (MP-104).

Stdlib only. Pure function — no IO.
"""
from __future__ import annotations

from datetime import date


def compare_to_benchmark(
    equity_curve: list[float],
    dates: list[str],
    benchmark_apy: float = 0.05,
) -> dict:
    """Compare the SPA track to a simple deposit at ``benchmark_apy``.

    The benchmark is the same initial amount accruing simple (non-compounded)
    interest over the same calendar span: ``apy * days / 365``. All returns
    are reported in PERCENT. ``alpha = spa - benchmark``.

    Fewer than 2 points, a non-positive starting equity or unparseable dates
    → the all-zero result (``outperforming: False``).
    """
    zero = {
        "spa_total_return": 0.0,
        "benchmark_total_return": 0.0,
        "alpha": 0.0,
        "outperforming": False,
    }
    if len(equity_curve) < 2 or len(dates) != len(equity_curve):
        return zero
    start = float(equity_curve[0])
    end = float(equity_curve[-1])
    if start <= 0:
        return zero
    try:
        days = (date.fromisoformat(str(dates[-1])) - date.fromisoformat(str(dates[0]))).days
    except ValueError:
        return zero
    if days <= 0:
        days = len(equity_curve) - 1  # fall back to one bar == one day

    spa_total_return = (end / start - 1.0) * 100.0
    benchmark_total_return = float(benchmark_apy) * days / 365.0 * 100.0
    alpha = spa_total_return - benchmark_total_return
    return {
        "spa_total_return": round(spa_total_return, 6),
        "benchmark_total_return": round(benchmark_total_return, 6),
        "alpha": round(alpha, 6),
        "outperforming": alpha > 0,
    }
