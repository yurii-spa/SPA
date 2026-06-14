"""
MP-1111  ProtocolDeFiYieldSmoothingAnalyzer
--------------------------------------------
Analyzes how well a yield source smooths returns over time versus having
spiky / batch payouts.

Protocols that compound daily are preferable to those that distribute weekly
or monthly batch rewards, because daily reinvestment captures the full power
of compound interest.

Outputs
-------
mean_yield_pct               : mean of yield_observations
yield_std_pct                : population std-dev of observations
yield_cv                     : coefficient of variation (std / mean); NaN-safe
smoothness_score             : int 0-100 (100 = perfectly smooth daily compounding)
missed_compounding_drag_pct  : APY lost due to non-daily compounding (in %)
smoothing_label              : SMOOTH_DAILY / GOOD_SMOOTHING / MODERATE_SPIKES /
                                BATCH_PAYOUT / ERRATIC_YIELD

Label logic
-----------
payout_freq==1  AND cv < 0.1  → SMOOTH_DAILY
payout_freq<=3  AND cv < 0.2  → GOOD_SMOOTHING
payout_freq<=7  AND cv < 0.4  → MODERATE_SPIKES
payout_freq>7   OR  cv 0.4–0.7 → BATCH_PAYOUT
cv > 0.7                        → ERRATIC_YIELD

Missed compounding drag formula
--------------------------------
drag = ((1 + mean_daily_rate)^365
        - (1 + mean_daily_rate * payout_freq)^(365/payout_freq)) * 100

where mean_daily_rate = mean_yield_pct / 100 / 365

Log file : data/yield_smoothing_log.json  (ring-buffer 100, atomic write)

Advisory / read-only.  Pure Python stdlib.  No external dependencies.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "yield_smoothing_log.json",
)
_LOG_CAP = 100

# Smoothing label constants
SMOOTH_DAILY    = "SMOOTH_DAILY"
GOOD_SMOOTHING  = "GOOD_SMOOTHING"
MODERATE_SPIKES = "MODERATE_SPIKES"
BATCH_PAYOUT    = "BATCH_PAYOUT"
ERRATIC_YIELD   = "ERRATIC_YIELD"

ALL_SMOOTHING_LABELS = (
    SMOOTH_DAILY,
    GOOD_SMOOTHING,
    MODERATE_SPIKES,
    BATCH_PAYOUT,
    ERRATIC_YIELD,
)

# CV thresholds
_CV_SMOOTH_THRESHOLD    = 0.1
_CV_GOOD_THRESHOLD      = 0.2
_CV_MODERATE_THRESHOLD  = 0.4
_CV_BATCH_THRESHOLD     = 0.7

# Payout-frequency thresholds
_FREQ_SMOOTH  = 1
_FREQ_GOOD    = 3
_FREQ_MODERATE = 7


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, abs_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to the inclusive range [lo, hi]."""
    return max(lo, min(hi, value))


def _safe_list_of_floats(observations: Any) -> list:
    """
    Convert *observations* to a list of valid finite floats.
    Non-numeric / non-finite values are silently dropped.
    """
    if not isinstance(observations, (list, tuple)):
        return []
    result = []
    for v in observations:
        try:
            f = float(v)
            if math.isfinite(f):
                result.append(f)
        except (TypeError, ValueError):
            pass
    return result


# ---------------------------------------------------------------------------
# Sub-calculators
# ---------------------------------------------------------------------------

def _mean_yield(observations: list) -> float:
    """Arithmetic mean of *observations*. Returns 0.0 for empty list."""
    if not observations:
        return 0.0
    return sum(observations) / len(observations)


def _yield_std(observations: list, mean: float) -> float:
    """
    Population standard deviation of *observations*.

    Returns 0.0 for empty or single-element list (no variance to compute).
    """
    n = len(observations)
    if n < 2:
        return 0.0
    variance = sum((x - mean) ** 2 for x in observations) / n
    return math.sqrt(variance)


def _yield_cv(std: float, mean: float) -> float:
    """
    Coefficient of variation = std / mean.

    Returns 0.0 when mean == 0 (avoids division by zero).
    A high CV signals erratic yields; low CV signals stability.
    """
    if mean == 0.0:
        return 0.0
    if mean < 0:
        # Negative mean makes CV sign ambiguous; use absolute value
        return abs(std / mean)
    return std / mean


def _missed_compounding_drag_pct(
    mean_yield_pct: float,
    payout_frequency_days: int,
) -> float:
    """
    APY lost due to non-daily compounding (in pct).

    Formula
    -------
    Let r = mean_yield_pct / 100 / 365  (mean daily rate, dimensionless)

    daily_apy   = (1 + r)^365
    batch_apy   = (1 + r * payout_frequency_days)^(365 / payout_frequency_days)
    drag        = (daily_apy - batch_apy) * 100

    For daily compounding (payout_frequency_days=1) the drag is exactly 0.

    Returns a non-negative value; negative result (unusual) is clamped to 0.
    """
    if mean_yield_pct <= 0 or payout_frequency_days <= 0:
        return 0.0

    r = mean_yield_pct / 100.0 / 365.0

    # Daily compounding APY
    daily_apy = (1.0 + r) ** 365

    # Batch compounding APY
    freq = max(1, int(payout_frequency_days))
    if freq == 1:
        return 0.0

    periods_per_year = 365.0 / freq
    batch_rate_per_period = r * freq
    batch_apy = (1.0 + batch_rate_per_period) ** periods_per_year

    drag = (daily_apy - batch_apy) * 100.0
    return max(0.0, drag)


def _smoothness_score(
    cv: float,
    payout_frequency_days: int,
    auto_compounds: bool,
    compounding_frequency_days: int,
    missed_drag_pct: float,
) -> int:
    """
    Composite smoothness score, 0–100.

    Components
    ----------
    - CV component (0-40):
      Lower CV → higher score (stable daily yield = max marks).
    - Payout frequency component (0-30):
      Daily payout → max marks; exponential penalty for longer intervals.
    - Auto-compounding bonus (0-20):
      Full marks for auto-compound with daily compounding.
    - Drag penalty (0-10 deducted):
      Large missed_compounding_drag reduces score.

    Score is clamped to [0, 100].
    """
    # CV component (0-40): score decreases as CV rises beyond 0
    if cv <= 0.0:
        cv_component = 40.0
    else:
        # Saturates at 0 once cv >= 1.0
        cv_component = max(0.0, 40.0 * (1.0 - _clamp(cv / 1.0, 0.0, 1.0)))

    # Payout frequency component (0-30): daily = 30, longer = lower
    freq = max(1, int(payout_frequency_days))
    if freq == 1:
        freq_component = 30.0
    else:
        # Exponential decay: score = 30 * exp(-0.1 * (freq - 1))
        freq_component = max(0.0, 30.0 * math.exp(-0.1 * (freq - 1)))

    # Auto-compounding bonus (0-20)
    if auto_compounds:
        comp_freq = max(1, int(compounding_frequency_days))
        if comp_freq == 1:
            auto_component = 20.0
        elif comp_freq <= 3:
            auto_component = 15.0
        elif comp_freq <= 7:
            auto_component = 10.0
        else:
            auto_component = 5.0
    else:
        auto_component = 0.0

    # Drag penalty (deduct up to 10 points for high drag)
    drag_penalty = _clamp(missed_drag_pct * 10.0, 0.0, 10.0)

    raw = cv_component + freq_component + auto_component - drag_penalty
    return int(_clamp(round(raw), 0, 100))


def _smoothing_label(
    cv: float,
    payout_frequency_days: int,
) -> str:
    """
    Advisory smoothing label.

    Priority order (highest specificity first):
    1. cv > 0.7                               → ERRATIC_YIELD
    2. payout_freq == 1 AND cv < 0.1          → SMOOTH_DAILY
    3. payout_freq <= 3 AND cv < 0.2          → GOOD_SMOOTHING
    4. payout_freq <= 7 AND cv < 0.4          → MODERATE_SPIKES
    5. payout_freq > 7 OR cv in [0.4, 0.7]   → BATCH_PAYOUT
    """
    freq = max(1, int(payout_frequency_days))

    # Erratic always wins
    if cv > _CV_BATCH_THRESHOLD:
        return ERRATIC_YIELD

    if freq == _FREQ_SMOOTH and cv < _CV_SMOOTH_THRESHOLD:
        return SMOOTH_DAILY

    if freq <= _FREQ_GOOD and cv < _CV_GOOD_THRESHOLD:
        return GOOD_SMOOTHING

    if freq <= _FREQ_MODERATE and cv < _CV_MODERATE_THRESHOLD:
        return MODERATE_SPIKES

    return BATCH_PAYOUT


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(source: dict, config: dict | None = None) -> dict:
    """
    Analyze yield smoothing characteristics of a DeFi yield source.

    Parameters
    ----------
    source : dict
        yield_observations          : list[float]  (daily yield rates in pct)
        payout_frequency_days       : int   (1=daily, 7=weekly, …)
        auto_compounds              : bool  (does protocol auto-compound?)
        compounding_frequency_days  : int   (how often it compounds if auto)
        position_size_usd           : float
        protocol_name               : str

    config : dict, optional
        log_path : str  (override default log path)

    Returns
    -------
    dict
        Full smoothing analysis.  Never raises to the caller.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    protocol_name = str(source.get("protocol_name", "UNKNOWN"))
    raw_obs       = source.get("yield_observations", [])
    observations  = _safe_list_of_floats(raw_obs)
    payout_freq   = max(1, int(_safe_float(source.get("payout_frequency_days", 1), 1)))
    auto_comp     = bool(source.get("auto_compounds", False))
    comp_freq     = max(1, int(_safe_float(source.get("compounding_frequency_days", 1), 1)))
    position_usd  = max(0.0, _safe_float(source.get("position_size_usd", 0.0)))

    mean_yield  = _mean_yield(observations)
    std_yield   = _yield_std(observations, mean_yield)
    cv          = _yield_cv(std_yield, mean_yield)
    drag        = _missed_compounding_drag_pct(mean_yield, payout_freq)
    score       = _smoothness_score(cv, payout_freq, auto_comp, comp_freq, drag)
    label       = _smoothing_label(cv, payout_freq)

    result: dict[str, Any] = {
        "protocol_name":                protocol_name,
        "observation_count":            len(observations),
        "payout_frequency_days":        payout_freq,
        "auto_compounds":               auto_comp,
        "compounding_frequency_days":   comp_freq,
        "position_size_usd":            position_usd,
        "mean_yield_pct":               mean_yield,
        "yield_std_pct":                std_yield,
        "yield_cv":                     cv,
        "smoothness_score":             score,
        "missed_compounding_drag_pct":  drag,
        "smoothing_label":              label,
        "timestamp":                    time.time(),
    }

    try:
        _atomic_log(log_path, result)
    except Exception:
        pass  # advisory: never crash caller

    return result


# ---------------------------------------------------------------------------
# Public batch analyse function
# ---------------------------------------------------------------------------

def analyze_portfolio(sources: list, config: dict | None = None) -> dict:
    """
    Analyze a list of yield sources and produce a summary.

    Parameters
    ----------
    sources : list[dict]
        List of source dicts (see :func:`analyze`).
    config : dict, optional
        Forwarded to :func:`analyze`.

    Returns
    -------
    dict
        Summary with keys:
        - total_sources
        - results                    – list of per-source analyses
        - smoothest_source           – name of source with highest smoothness_score
        - most_erratic_source        – name of source with lowest smoothness_score
        - avg_smoothness_score
        - erratic_count              – number of ERRATIC_YIELD sources
        - avg_missed_drag_pct
    """
    if not isinstance(sources, list):
        sources = []

    results: list[dict] = [
        analyze(s if isinstance(s, dict) else {}, config=config)
        for s in sources
    ]

    total = len(results)
    if total == 0:
        return {
            "total_sources":         0,
            "results":               [],
            "smoothest_source":      None,
            "most_erratic_source":   None,
            "avg_smoothness_score":  0.0,
            "erratic_count":         0,
            "avg_missed_drag_pct":   0.0,
        }

    smoothest  = max(results, key=lambda r: r["smoothness_score"])
    most_erratic = min(results, key=lambda r: r["smoothness_score"])
    avg_score  = sum(r["smoothness_score"] for r in results) / total
    erratic    = sum(1 for r in results if r["smoothing_label"] == ERRATIC_YIELD)
    avg_drag   = sum(r["missed_compounding_drag_pct"] for r in results) / total

    return {
        "total_sources":         total,
        "results":               results,
        "smoothest_source":      smoothest["protocol_name"],
        "most_erratic_source":   most_erratic["protocol_name"],
        "avg_smoothness_score":  avg_score,
        "erratic_count":         erratic,
        "avg_missed_drag_pct":   avg_drag,
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class ProtocolDeFiYieldSmoothingAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = ProtocolDeFiYieldSmoothingAnalyzer()
    >>> r = a.analyze({"protocol_name": "Aave V3", "yield_observations": [...], ...})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, source: dict) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(source, config=self._config)

    def analyze_portfolio(self, sources: list) -> dict:
        """Delegate to module-level ``analyze_portfolio``."""
        return analyze_portfolio(sources, config=self._config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _daily_stable = [0.01384] * 30    # perfectly stable daily yield ~5% APY

    _weekly_batch = [0.0] * 6 + [0.09688]  # 6 days of 0 then one big batch

    _noisy = [
        0.005, 0.018, 0.002, 0.025, 0.001, 0.030, 0.003, 0.022,
        0.001, 0.019, 0.004, 0.027, 0.000, 0.031, 0.002, 0.020,
        0.005, 0.015, 0.003, 0.028, 0.001, 0.023, 0.006, 0.017,
        0.002, 0.029, 0.001, 0.024, 0.004, 0.016,
    ]

    _demo = [
        {
            "protocol_name":            "Aave (daily auto-compound)",
            "yield_observations":       _daily_stable,
            "payout_frequency_days":    1,
            "auto_compounds":           True,
            "compounding_frequency_days": 1,
            "position_size_usd":        100_000.0,
        },
        {
            "protocol_name":            "Convex (weekly harvest)",
            "yield_observations":       _weekly_batch * 4,
            "payout_frequency_days":    7,
            "auto_compounds":           False,
            "compounding_frequency_days": 7,
            "position_size_usd":        50_000.0,
        },
        {
            "protocol_name":            "Noisy DeFi (erratic)",
            "yield_observations":       _noisy,
            "payout_frequency_days":    1,
            "auto_compounds":           False,
            "compounding_frequency_days": 1,
            "position_size_usd":        25_000.0,
        },
    ]

    import json as _json
    for src in _demo:
        r = analyze(src)
        print(_json.dumps(
            {k: v for k, v in r.items() if k != "timestamp"},
            indent=2, default=str
        ))
        print()

    print("---- portfolio ----")
    summary = analyze_portfolio(_demo)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
