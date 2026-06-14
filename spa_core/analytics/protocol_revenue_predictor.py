"""
MP-824: ProtocolRevenuePredictorSimple
Predicts future protocol revenue using historical TVL and fee rate trends
via simple Ordinary Least Squares (OLS) linear regression.

Advisory / read-only — never modifies allocator, risk, or execution.
Pure stdlib — zero external dependencies.
Atomic writes: tmp + os.replace.
Ring-buffer log capped at 100 entries (data/revenue_prediction_log.json).
"""

import json
import os
import time
from pathlib import Path

_DATA_FILE = Path("data/revenue_prediction_log.json")
_MAX_ENTRIES = 100
_DEFAULT_FORECAST_DAYS = 30
_MIN_HISTORY = 3  # minimum data points required


# ---------------------------------------------------------------------------
# OLS helpers
# ---------------------------------------------------------------------------

def _ols(y: list) -> tuple:
    """
    Fit y = slope * x + intercept via OLS where x = 0, 1, 2, ...

    Returns (slope, intercept, r_squared).
    Guards against degenerate cases (n < 2, zero variance).
    """
    n = len(y)
    if n < 2:
        return 0.0, (y[0] if y else 0.0), 1.0

    # x indices: 0, 1, ..., n-1
    sx = n * (n - 1) / 2          # sum of x
    sy = sum(y)                    # sum of y
    sxy = sum(i * v for i, v in enumerate(y))
    sxx = n * (n - 1) * (2 * n - 1) / 6  # sum of x^2

    denom = n * sxx - sx * sx
    if denom == 0.0:
        # All x values equal (degenerate — won't happen for indices)
        intercept = sy / n
        return 0.0, intercept, 1.0

    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n

    # R² computation
    mean_y = sy / n
    ss_tot = sum((v - mean_y) ** 2 for v in y)
    if ss_tot == 0.0:
        r_squared = 1.0  # perfect fit (all y identical)
    else:
        ss_res = sum((v - (slope * i + intercept)) ** 2 for i, v in enumerate(y))
        r_squared = max(0.0, 1.0 - ss_res / ss_tot)

    return slope, intercept, r_squared


# ---------------------------------------------------------------------------
# Ring-buffer helpers
# ---------------------------------------------------------------------------

def _load_log(data_file: Path) -> list:
    """Load ring-buffer log; return [] on any read / parse error."""
    try:
        return json.loads(data_file.read_text())
    except Exception:
        return []


def _save_log(entry: dict, data_file: Path) -> None:
    """Append *entry* to the ring-buffer log (max _MAX_ENTRIES). Atomic write."""
    data_file.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_log(data_file)
    existing.append(entry)
    if len(existing) > _MAX_ENTRIES:
        existing = existing[-_MAX_ENTRIES:]
    tmp = data_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2))
    os.replace(tmp, data_file)


# ---------------------------------------------------------------------------
# Trend classification helpers
# ---------------------------------------------------------------------------

def _tvl_trend(tvl_values: list, slope: float) -> str:
    """
    GROWING  — slope > 0 AND last_tvl > first_tvl * 1.05
    SHRINKING — slope < 0 AND last_tvl < first_tvl * 0.95
    STABLE    — otherwise
    """
    if len(tvl_values) < 2:
        return "STABLE"
    first = tvl_values[0]
    last = tvl_values[-1]
    if first == 0:
        return "STABLE"
    if slope > 0 and last > first * 1.05:
        return "GROWING"
    if slope < 0 and last < first * 0.95:
        return "SHRINKING"
    return "STABLE"


def _fee_rate_trend(rates: list, slope: float) -> str:
    """
    INCREASING — slope > 0 AND last_rate > first_rate * 1.05
    DECREASING — slope < 0 AND last_rate < first_rate * 0.95
    STABLE     — otherwise
    """
    if len(rates) < 2:
        return "STABLE"
    first = rates[0]
    last = rates[-1]
    if first == 0:
        return "STABLE"
    if slope > 0 and last > first * 1.05:
        return "INCREASING"
    if slope < 0 and last < first * 0.95:
        return "DECREASING"
    return "STABLE"


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(
    protocol: str,
    history: list,
    config: dict = None,
    *,
    data_file: Path = None,
    save: bool = True,
) -> dict:
    """
    Predict future protocol revenue using historical TVL / fee-rate trends.

    Parameters
    ----------
    protocol : str
        Protocol name (e.g. "Aave V3").
    history : list[dict]
        Minimum 3 entries, sorted ascending by date:
        [{"date": "YYYY-MM-DD", "tvl_usd": float, "daily_fee_revenue_usd": float}, ...]
    config : dict | None
        {"forecast_days": int}  # default 30
    data_file : Path | None
        Override default log path (useful in tests).
    save : bool
        Whether to append the result to the ring-buffer log.

    Returns
    -------
    dict
        Full prediction result.

    Raises
    ------
    ValueError
        If ``history`` has fewer than _MIN_HISTORY (3) entries.
    """
    if data_file is None:
        data_file = _DATA_FILE

    if len(history) < _MIN_HISTORY:
        raise ValueError(
            f"history must have at least {_MIN_HISTORY} entries, got {len(history)}"
        )

    cfg = config or {}
    forecast_days = int(cfg.get("forecast_days", _DEFAULT_FORECAST_DAYS))

    # --- extract series ---
    tvl_values = [float(h.get("tvl_usd", 0.0)) for h in history]
    revenue_values = [float(h.get("daily_fee_revenue_usd", 0.0)) for h in history]

    # --- current values (last entry) ---
    current_tvl = tvl_values[-1]
    current_revenue = revenue_values[-1]

    # --- fee rate per entry (daily_fee / tvl); skip where tvl == 0 ---
    fee_rates = []
    for tvl, rev in zip(tvl_values, revenue_values):
        if tvl > 0:
            fee_rates.append(rev / tvl)

    fee_rate_avg = (sum(fee_rates) / len(fee_rates)) if fee_rates else 0.0

    # --- OLS on TVL ---
    tvl_slope, _tvl_intercept, _tvl_r2 = _ols(tvl_values)

    # --- OLS on daily revenue ---
    rev_slope, _rev_intercept, rev_r2 = _ols(revenue_values)

    # --- OLS on fee rates (for trend direction) ---
    if len(fee_rates) >= 2:
        rate_slope, _, _ = _ols(fee_rates)
    else:
        rate_slope = 0.0

    # --- trend labels ---
    tvl_trend_label = _tvl_trend(tvl_values, tvl_slope)
    fee_rate_trend_label = _fee_rate_trend(fee_rates, rate_slope) if fee_rates else "STABLE"

    # --- predictions ---
    predicted_tvl = max(0.0, current_tvl + tvl_slope * forecast_days)
    predicted_daily_revenue = max(0.0, predicted_tvl * fee_rate_avg)
    predicted_annual_revenue = predicted_daily_revenue * 365.0

    # --- confidence from revenue R² ---
    if rev_r2 >= 0.7:
        confidence = "HIGH"
    elif rev_r2 >= 0.4:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    result = {
        "protocol": protocol,
        "data_points": len(history),
        "current_tvl_usd": current_tvl,
        "current_daily_revenue_usd": current_revenue,
        "fee_rate_avg": fee_rate_avg,
        "fee_rate_trend": fee_rate_trend_label,
        "tvl_trend": tvl_trend_label,
        "tvl_slope_per_day": tvl_slope,
        "revenue_slope_per_day": rev_slope,
        "predicted_tvl_usd": predicted_tvl,
        "predicted_daily_revenue_usd": predicted_daily_revenue,
        "predicted_annual_revenue_usd": predicted_annual_revenue,
        "confidence": confidence,
        "r_squared": rev_r2,
        "timestamp": time.time(),
    }

    if save:
        _save_log(result, data_file)

    return result


# ---------------------------------------------------------------------------
# CLI entry point (advisory — prints result, exit 0 always)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo_history = [
        {"date": "2026-01-01", "tvl_usd": 100_000_000.0, "daily_fee_revenue_usd": 10_000.0},
        {"date": "2026-01-02", "tvl_usd": 105_000_000.0, "daily_fee_revenue_usd": 10_500.0},
        {"date": "2026-01-03", "tvl_usd": 110_000_000.0, "daily_fee_revenue_usd": 11_000.0},
        {"date": "2026-01-04", "tvl_usd": 112_000_000.0, "daily_fee_revenue_usd": 11_200.0},
        {"date": "2026-01-05", "tvl_usd": 118_000_000.0, "daily_fee_revenue_usd": 11_800.0},
    ]

    res = analyze("Aave V3", _demo_history, config={"forecast_days": 30}, save=False)
    print(json.dumps(res, indent=2))
    sys.exit(0)
