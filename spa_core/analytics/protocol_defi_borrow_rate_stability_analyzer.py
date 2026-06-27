"""
MP-1089: ProtocolDeFiBorrowRateStabilityAnalyzer
Analyzes historical borrow rate stability for variable-rate lending positions.
High volatility = unpredictable cost of capital.

Pure stdlib, read-only analytics, atomic writes, ring-buffer log capped at 100.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any
from spa_core.utils.atomic import atomic_save
from spa_core.utils import clock

__version__ = "1.0.0"
__mp__ = "MP-1089"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "borrow_rate_stability_log.json"
)
LOG_CAP = 100

# Stability label constants
ULTRA_STABLE = "ULTRA_STABLE"
STABLE = "STABLE"
MODERATE_VARIANCE = "MODERATE_VARIANCE"
HIGH_VARIANCE = "HIGH_VARIANCE"
VOLATILE_RATE = "VOLATILE_RATE"

# Coefficient-of-variation thresholds for stability labels
_CV_THRESHOLDS = [
    (0.05, ULTRA_STABLE),
    (0.15, STABLE),
    (0.30, MODERATE_VARIANCE),
    (0.50, HIGH_VARIANCE),
]  # > 0.50 → VOLATILE_RATE


# ---------------------------------------------------------------------------
# Atomic I/O helpers
# ---------------------------------------------------------------------------


def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    atomic_save(data, str(abs_path))
def _load_log(path: str) -> list:
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _append_log(path: str, entry: dict, cap: int) -> None:
    log = _load_log(path)
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]
    _atomic_write(path, log)


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------


def _compute_mean(rates: list) -> float:
    """Population mean of rate series."""
    if not rates:
        return 0.0
    return sum(rates) / len(rates)


def _compute_std(rates: list, mean: float) -> float:
    """
    Population standard deviation of rate series.
    Returns 0.0 for lists with fewer than 2 elements.
    """
    n = len(rates)
    if n < 2:
        return 0.0
    variance = sum((r - mean) ** 2 for r in rates) / n
    return math.sqrt(variance)


def _compute_rate_cv(std: float, mean: float) -> float:
    """
    Coefficient of variation = std / mean.
    Returns 0.0 when mean is zero and std is zero (no movement).
    Returns a large value (e.g. std itself) when mean ≈ 0 but std > 0,
    indicating extreme instability.
    Uses abs(mean) to handle theoretical negative rates.
    """
    abs_mean = abs(mean)
    if abs_mean < 1e-12:
        # No mean → if no std either, perfectly stable; else extremely volatile
        return 0.0 if std < 1e-12 else float("inf")
    return std / abs_mean


def _compute_stability_label(rate_cv: float) -> str:
    """
    Map coefficient of variation to stability label.

    cv < 0.05          → ULTRA_STABLE
    cv 0.05 – 0.15     → STABLE
    cv 0.15 – 0.30     → MODERATE_VARIANCE
    cv 0.30 – 0.50     → HIGH_VARIANCE
    cv > 0.50          → VOLATILE_RATE
    """
    if not math.isfinite(rate_cv):
        return VOLATILE_RATE
    for threshold, label in _CV_THRESHOLDS:
        if rate_cv < threshold:
            return label
    return VOLATILE_RATE


def _compute_stability_score(rate_cv: float) -> int:
    """
    Integer stability score 0-100.
    100 = perfectly stable (cv = 0).
    0   = cv ≥ 1.0 (or non-finite).

    Linear: score = round(100 * max(0, 1 - cv))
    At cv = 0   → 100
    At cv = 0.5 → 50
    At cv = 1.0 → 0
    """
    if not math.isfinite(rate_cv):
        return 0
    clamped = min(1.0, max(0.0, rate_cv))
    return round(100 * (1.0 - clamped))


def _compute_above_optimal_flag(
    utilization_rate_pct: float,
    optimal_utilization_pct: float,
) -> bool:
    """True when current utilization exceeds the kink / optimal point."""
    return utilization_rate_pct > optimal_utilization_pct


# ---------------------------------------------------------------------------
# Main analyser class
# ---------------------------------------------------------------------------


class ProtocolDeFiBorrowRateStabilityAnalyzer:
    """
    Analyzes historical borrow rate stability for variable-rate DeFi lending positions.

    Call ``analyze()`` with a historical rate series and current pool parameters
    to get a complete stability assessment.  Results are also appended to a
    ring-buffer JSON log (capped at 100 entries).
    """

    def __init__(
        self,
        log_path: str | None = None,
        log_cap: int = LOG_CAP,
    ) -> None:
        self._log_path = log_path or LOG_PATH
        self._log_cap = log_cap

    # ------------------------------------------------------------------
    def analyze(
        self,
        borrow_rates_pct: list,
        current_rate_pct: float,
        utilization_rate_pct: float,
        optimal_utilization_pct: float,
        base_rate_pct: float,
        protocol_name: str,
    ) -> dict:
        """
        Analyze borrow rate stability from a historical observation series.

        Parameters
        ----------
        borrow_rates_pct : list of float
            Historical variable borrow rates (e.g. last 30 observations).
            Must contain at least one element.
        current_rate_pct : float
            Most recent (current) borrow rate.
        utilization_rate_pct : float
            Current pool utilization in percent (0–100).
        optimal_utilization_pct : float
            Kink-point utilization in percent (e.g. 80.0).
        base_rate_pct : float
            Minimum / floor borrow rate.
        protocol_name : str
            Protocol or market identifier.

        Returns
        -------
        dict
            Keys: mean_rate_pct, rate_std_pct, rate_cv, max_rate_pct,
                  min_rate_pct, above_optimal_flag, stability_score,
                  stability_label, current_rate_pct, utilization_rate_pct,
                  optimal_utilization_pct, base_rate_pct, observations,
                  protocol_name, analysis_timestamp, module, version.
        """
        # Coerce inputs
        rates: list[float] = [float(r) for r in borrow_rates_pct]
        current = float(current_rate_pct)
        utilization = float(utilization_rate_pct)
        optimal = float(optimal_utilization_pct)
        base = float(base_rate_pct)

        # Core statistics
        if rates:
            mean_rate = _compute_mean(rates)
            rate_std = _compute_std(rates, mean_rate)
            max_rate = max(rates)
            min_rate = min(rates)
        else:
            # Empty series: stable with zeros
            mean_rate = 0.0
            rate_std = 0.0
            max_rate = 0.0
            min_rate = 0.0

        rate_cv = _compute_rate_cv(rate_std, mean_rate)
        stability_label = _compute_stability_label(rate_cv)
        stability_score = _compute_stability_score(rate_cv)
        above_optimal = _compute_above_optimal_flag(utilization, optimal)

        # Represent infinite cv as a large sentinel for JSON serialisation
        rate_cv_serialisable = rate_cv if math.isfinite(rate_cv) else 9999.0

        result: dict = {
            "protocol_name": str(protocol_name),
            "mean_rate_pct": round(mean_rate, 6),
            "rate_std_pct": round(rate_std, 6),
            "rate_cv": round(rate_cv_serialisable, 6),
            "max_rate_pct": round(max_rate, 6),
            "min_rate_pct": round(min_rate, 6),
            "above_optimal_flag": above_optimal,
            "stability_score": stability_score,
            "stability_label": stability_label,
            "current_rate_pct": round(current, 6),
            "utilization_rate_pct": round(utilization, 6),
            "optimal_utilization_pct": round(optimal, 6),
            "base_rate_pct": round(base, 6),
            "observations": len(rates),
            "analysis_timestamp": clock.utcnow().isoformat() + "Z",
            "module": __mp__,
            "version": __version__,
        }

        # Append to ring-buffer log (best-effort; never crash analysis)
        log_entry = {
            "ts": result["analysis_timestamp"],
            "protocol_name": str(protocol_name),
            "mean_rate_pct": round(mean_rate, 4),
            "rate_std_pct": round(rate_std, 4),
            "rate_cv": round(rate_cv_serialisable, 4),
            "stability_label": stability_label,
            "stability_score": stability_score,
            "above_optimal_flag": above_optimal,
        }
        try:
            _append_log(self._log_path, log_entry, self._log_cap)
        except Exception:
            pass

        return result
