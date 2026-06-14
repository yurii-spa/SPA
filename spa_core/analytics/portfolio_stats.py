"""
Advanced portfolio statistics for the Analytics tab.
All pure Python — no numpy/pandas.

All functions accept an equity_curve: list[dict] where each dict has at least:
    {"date": "YYYY-MM-DD", "total_capital": float}

Edge cases handled throughout:
  - Empty curve         → safe defaults (0.0 or empty list)
  - Single data point   → safe defaults
  - All-flat curve      → zero drawdown, zero deviation stats
"""

from __future__ import annotations

import math
from typing import Optional


# ─── Internal helpers ──────────────────────────────────────────────────────────

def _capitals(equity_curve: list[dict]) -> list[float]:
    """Extract total_capital values; handle missing/None gracefully."""
    return [float(e.get("total_capital") or 0.0) for e in equity_curve]


def _daily_returns(capitals: list[float]) -> list[float]:
    """Compute daily percentage returns from a capital series."""
    if len(capitals) < 2:
        return []
    returns = []
    for i in range(1, len(capitals)):
        prev = capitals[i - 1]
        if prev and prev != 0:
            returns.append((capitals[i] - prev) / prev)
        else:
            returns.append(0.0)
    return returns


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    variance = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _drawdown_series(capitals: list[float]) -> list[float]:
    """
    Returns a list of drawdown fractions (0 to 1) for each point.
    Drawdown[i] = (peak_up_to_i - capitals[i]) / peak_up_to_i
    """
    if not capitals:
        return []
    drawdowns = []
    peak = capitals[0]
    for c in capitals:
        if c > peak:
            peak = c
        dd = (peak - c) / peak if peak > 0 else 0.0
        drawdowns.append(dd)
    return drawdowns


def _max_drawdown_fraction(capitals: list[float]) -> float:
    """Return maximum drawdown as a fraction (0–1)."""
    if len(capitals) < 2:
        return 0.0
    dds = _drawdown_series(capitals)
    return max(dds) if dds else 0.0


def _annualised_return(total_return_fraction: float, n_days: int) -> float:
    """Annualise a total return given the number of days."""
    if n_days <= 0:
        return 0.0
    # (1 + r)^(365/n) - 1
    try:
        return (1 + total_return_fraction) ** (365.0 / n_days) - 1
    except (ZeroDivisionError, OverflowError, ValueError):
        return 0.0


# ─── Public functions ──────────────────────────────────────────────────────────

def calmar_ratio(equity_curve: list[dict], risk_free: float = 0.04) -> float:
    """
    Calmar Ratio = annualised return / max drawdown.

    Higher = better. A ratio ≥ 3 is considered excellent for institutional funds.
    Returns 0.0 if drawdown is zero (no drawdown = perfect, but ratio undefined).
    """
    caps = _capitals(equity_curve)
    if len(caps) < 2:
        return 0.0

    initial = caps[0]
    final   = caps[-1]
    n_days  = len(caps)

    total_ret = (final - initial) / initial if initial else 0.0
    ann_ret   = _annualised_return(total_ret, n_days)
    max_dd    = _max_drawdown_fraction(caps)

    if max_dd == 0.0:
        return 0.0  # no drawdown — ratio is undefined, return 0 as sentinel
    return round(ann_ret / max_dd, 4)


def sortino_ratio(
    equity_curve: list[dict],
    risk_free: float = 0.04,
    target: float = 0.0,
) -> float:
    """
    Sortino Ratio = (annualised_return - risk_free) / downside_deviation.

    Like Sharpe but only penalises negative (downside) volatility.
    target: minimum acceptable daily return (default 0.0).
    """
    caps    = _capitals(equity_curve)
    returns = _daily_returns(caps)
    if not returns:
        return 0.0

    # Daily risk-free
    daily_rf = (1 + risk_free) ** (1 / 365) - 1

    # Annualised mean return
    mean_daily = _mean(returns)
    ann_return = (1 + mean_daily) ** 365 - 1

    # Downside deviation: only days below target
    downside = [min(r - target, 0.0) for r in returns]
    downside_sq = [d ** 2 for d in downside]
    if not downside_sq:
        return 0.0

    downside_std_daily = math.sqrt(sum(downside_sq) / len(downside_sq))
    downside_std_ann   = downside_std_daily * math.sqrt(365)

    if downside_std_ann == 0.0:
        return 0.0
    return round((ann_return - risk_free) / downside_std_ann, 4)


def ulcer_index(equity_curve: list[dict]) -> float:
    """
    Ulcer Index = RMS of all drawdown percentages.

    Measures the depth and duration of drawdowns together.
    Lower is better. A value of 0.0 means no drawdown ever occurred.
    """
    caps = _capitals(equity_curve)
    if len(caps) < 2:
        return 0.0

    dds = _drawdown_series(caps)   # fractions 0–1
    dds_pct = [d * 100 for d in dds]  # convert to %

    rms = math.sqrt(sum(d ** 2 for d in dds_pct) / len(dds_pct))
    return round(rms, 4)


def recovery_factor(equity_curve: list[dict]) -> float:
    """
    Recovery Factor = total_return / max_drawdown.

    Measures how much reward was earned per unit of maximum pain.
    Higher = better (≥ 3 is considered strong).
    Returns 0.0 if drawdown is zero.
    """
    caps = _capitals(equity_curve)
    if len(caps) < 2:
        return 0.0

    initial = caps[0]
    final   = caps[-1]
    total_ret = (final - initial) / initial if initial else 0.0
    max_dd    = _max_drawdown_fraction(caps)

    if max_dd == 0.0:
        return 0.0
    return round(total_ret / max_dd, 4)


def avg_drawdown_duration(equity_curve: list[dict]) -> float:
    """
    Average number of days spent in a drawdown (i.e., below a prior peak).

    Returns 0.0 if the portfolio never enters a drawdown.
    """
    caps = _capitals(equity_curve)
    if len(caps) < 2:
        return 0.0

    # Build per-day drawdown flag (True = in drawdown)
    dds = _drawdown_series(caps)
    in_dd = [d > 0.0 for d in dds]

    # Identify contiguous drawdown runs
    durations = []
    run = 0
    for flag in in_dd:
        if flag:
            run += 1
        else:
            if run > 0:
                durations.append(run)
            run = 0
    if run > 0:
        durations.append(run)  # still in drawdown at end

    if not durations:
        return 0.0
    return round(sum(durations) / len(durations), 2)


def value_at_risk_historical(
    equity_curve: list[dict],
    confidence: float = 0.95,
) -> float:
    """
    Historical Value at Risk (VaR) at the given confidence level.

    Returns the loss (as a positive fraction) that is not exceeded with
    the given confidence. E.g. VaR 95% = 0.012 means there is a 5%
    chance of losing more than 1.2% on any given day.
    """
    caps    = _capitals(equity_curve)
    returns = _daily_returns(caps)
    if not returns:
        return 0.0

    sorted_returns = sorted(returns)  # worst to best
    idx = int((1 - confidence) * len(sorted_returns))
    idx = max(0, min(idx, len(sorted_returns) - 1))
    var = -sorted_returns[idx]  # make positive (it's a loss figure)
    return round(max(var, 0.0), 6)


def expected_shortfall(
    equity_curve: list[dict],
    confidence: float = 0.95,
) -> float:
    """
    Expected Shortfall (CVaR) = average loss beyond the VaR threshold.

    More informative than VaR: tells you the *expected* loss in the worst
    (1 - confidence) fraction of days. Higher = more tail risk.
    """
    caps    = _capitals(equity_curve)
    returns = _daily_returns(caps)
    if not returns:
        return 0.0

    sorted_returns = sorted(returns)
    cutoff_idx = int((1 - confidence) * len(sorted_returns))
    cutoff_idx = max(1, cutoff_idx)  # at least one observation

    tail = sorted_returns[:cutoff_idx]
    if not tail:
        return 0.0

    cvar = -_mean(tail)  # make positive
    return round(max(cvar, 0.0), 6)


def portfolio_summary(equity_curve: list[dict]) -> dict:
    """
    Compute all advanced metrics in a single pass — Dashboard-ready dict.

    Keys:
        calmar_ratio, sortino_ratio, ulcer_index, recovery_factor,
        avg_drawdown_duration_days, value_at_risk_95, expected_shortfall_95,
        total_return_pct, annualised_return_pct, max_drawdown_pct,
        data_points
    """
    caps = _capitals(equity_curve)
    n    = len(caps)

    if n < 2:
        return {
            "calmar_ratio":               0.0,
            "sortino_ratio":              0.0,
            "ulcer_index":                0.0,
            "recovery_factor":            0.0,
            "avg_drawdown_duration_days": 0.0,
            "value_at_risk_95":           0.0,
            "expected_shortfall_95":      0.0,
            "total_return_pct":           0.0,
            "annualised_return_pct":      0.0,
            "max_drawdown_pct":           0.0,
            "data_points":                n,
        }

    initial   = caps[0]
    final     = caps[-1]
    total_ret = (final - initial) / initial if initial else 0.0
    ann_ret   = _annualised_return(total_ret, n)
    max_dd    = _max_drawdown_fraction(caps)

    return {
        "calmar_ratio":               calmar_ratio(equity_curve),
        "sortino_ratio":              sortino_ratio(equity_curve),
        "ulcer_index":                ulcer_index(equity_curve),
        "recovery_factor":            recovery_factor(equity_curve),
        "avg_drawdown_duration_days": avg_drawdown_duration(equity_curve),
        "value_at_risk_95":           value_at_risk_historical(equity_curve, 0.95),
        "expected_shortfall_95":      expected_shortfall(equity_curve, 0.95),
        "total_return_pct":           round(total_ret * 100, 4),
        "annualised_return_pct":      round(ann_ret * 100, 4),
        "max_drawdown_pct":           round(max_dd * 100, 4),
        "data_points":                n,
    }


def rolling_metrics(
    equity_curve: list[dict],
    window: int = 30,
) -> list[dict]:
    """
    Compute rolling window metrics over the equity curve.

    For each point i ≥ window-1 in the curve, uses the slice [i-window+1 .. i]
    to compute Sharpe, Sortino, and drawdown. For points before the window,
    uses an expanding window (minimum 2 points required).

    Returns a list of dicts, one per equity_curve entry:
        {date, sharpe, sortino, drawdown, return_pct}

    - sharpe: rolling annualised Sharpe ratio (risk_free=4%)
    - sortino: rolling annualised Sortino ratio
    - drawdown: rolling max drawdown (%) within the window
    - return_pct: rolling total return (%) within the window
    """
    result = []
    n = len(equity_curve)
    if n == 0:
        return []

    for i in range(n):
        entry  = equity_curve[i]
        date   = entry.get("date", str(i))
        start  = max(0, i - window + 1)
        window_slice = equity_curve[start: i + 1]

        if len(window_slice) < 2:
            result.append({
                "date":       date,
                "sharpe":     0.0,
                "sortino":    0.0,
                "drawdown":   0.0,
                "return_pct": 0.0,
            })
            continue

        caps    = _capitals(window_slice)
        returns = _daily_returns(caps)

        # Rolling Sharpe
        daily_rf = (1.05) ** (1 / 365) - 1  # ~4% annual
        excess   = [r - daily_rf for r in returns]
        mean_e   = _mean(excess)
        std_e    = _std(excess)
        sharpe   = round((mean_e / std_e) * math.sqrt(365), 4) if std_e else 0.0

        # Rolling Sortino
        mean_r   = _mean(returns)
        ann_r    = (1 + mean_r) ** 365 - 1
        downside_sq = [min(r, 0.0) ** 2 for r in returns]
        ds_std   = math.sqrt(sum(downside_sq) / len(downside_sq)) if downside_sq else 0.0
        ds_ann   = ds_std * math.sqrt(365)
        sortino  = round((ann_r - 0.04) / ds_ann, 4) if ds_ann else 0.0

        # Rolling drawdown (%)
        max_dd   = round(_max_drawdown_fraction(caps) * 100, 4)

        # Rolling total return (%)
        ret_pct  = round((caps[-1] - caps[0]) / caps[0] * 100, 4) if caps[0] else 0.0

        result.append({
            "date":       date,
            "sharpe":     sharpe,
            "sortino":    sortino,
            "drawdown":   max_dd,
            "return_pct": ret_pct,
        })

    return result
