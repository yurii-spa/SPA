"""
SPA Backtesting — Standalone Metrics Functions
==============================================

All functions are pure (no side-effects) and operate on plain Python lists.
These are used by BacktestEngine but can also be imported independently.
"""

from __future__ import annotations

import math
import statistics


def sharpe_ratio(
    returns: list[float],
    risk_free_rate: float = 0.04,
) -> float:
    """
    Compute annualised Sharpe ratio from a list of daily returns (as fractions, not %).

    Args:
        returns: Daily portfolio returns, e.g. [0.0003, -0.0001, 0.0005, ...]
        risk_free_rate: Annual risk-free rate as a fraction (default 4% = 0.04).

    Returns:
        Annualised Sharpe ratio (float). Returns 0.0 if fewer than 2 data points.
    """
    if len(returns) < 2:
        return 0.0

    daily_rf = risk_free_rate / 365.0
    excess = [r - daily_rf for r in returns]
    mean_excess = statistics.mean(excess)

    try:
        std = statistics.stdev(excess)
    except statistics.StatisticsError:
        return 0.0

    if std == 0.0:
        return 0.0

    return round((mean_excess / std) * math.sqrt(365), 4)


def max_drawdown(equity_curve: list[float]) -> float:
    """
    Compute maximum drawdown from an equity curve (list of portfolio values).

    Args:
        equity_curve: List of portfolio values over time (e.g. [100000, 100300, 99800, ...]).

    Returns:
        Maximum drawdown as a positive fraction, e.g. 0.0312 means 3.12% drawdown.
        Returns 0.0 if fewer than 2 data points.
    """
    if len(equity_curve) < 2:
        return 0.0

    peak = equity_curve[0]
    max_dd = 0.0

    for value in equity_curve:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak > 0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown

    return round(max_dd, 6)


def win_rate(trades: list[dict]) -> float:
    """
    Compute the fraction of trades with positive PnL.

    Args:
        trades: List of trade dicts, each must have a "pnl" key (float).
                Trades with pnl == 0.0 are counted as losses (conservative).

    Returns:
        Win rate as a fraction in [0, 1]. Returns 0.0 if trades list is empty.
    """
    if not trades:
        return 0.0

    wins = sum(1 for t in trades if t.get("pnl", 0.0) > 0.0)
    return round(wins / len(trades), 4)


def total_return_pct(initial_capital: float, final_capital: float) -> float:
    """
    Compute total return as a percentage.

    Returns:
        e.g. 3.45 means +3.45% total return. Can be negative.
    """
    if initial_capital == 0:
        return 0.0
    return round((final_capital - initial_capital) / initial_capital * 100, 4)


def annualised_return_pct(total_return_fraction: float, days: int) -> float:
    """
    Annualise a total return given the number of days elapsed.

    Args:
        total_return_fraction: e.g. 0.05 for +5%
        days: Number of calendar days in the backtest period.

    Returns:
        Annualised return as a percentage, e.g. 12.3 means +12.3% annualised.
    """
    if days <= 0 or total_return_fraction <= -1.0:
        return 0.0
    factor = (1 + total_return_fraction) ** (365.0 / days)
    return round((factor - 1) * 100, 4)
