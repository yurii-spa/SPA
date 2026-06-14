"""
MP-1055: ProtocolDeFiStableYieldConsistencyScorer
--------------------------------------------------
Scores how consistent / predictable a DeFi protocol's yield is over time.
Read-only / advisory — never modifies allocator, risk, or execution.
Pure stdlib. Atomic ring-buffer JSON log (cap 100).

Input dict keys:
  protocol_name       : str
  apy_history         : list[float]  (most recent last; at least 7 entries)
  current_apy_pct     : float
  yield_source        : str  ("lending_interest" / "trading_fees" /
                               "emissions" / "real_yield")
  has_rate_lock       : bool
  lock_duration_days  : float  (0 if no lock)
  min_deposit_usd     : float
  withdrawal_delay_days : float

Output dict keys:
  protocol_name          : str    (echo)
  apy_mean_pct           : float
  apy_std_pct            : float
  coefficient_of_variation : float  (std / mean; 0 when mean == 0)
  consistency_score      : float  (0-100, higher = more consistent)
  predictability_label   : str    one of:
                                   ROCK_SOLID / VERY_CONSISTENT /
                                   MODERATELY_CONSISTENT / VOLATILE_YIELD /
                                   UNPREDICTABLE
  analyzed_at            : str    (ISO-8601 UTC)
"""

from __future__ import annotations

import json
import math
import os
import statistics
import tempfile
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_PATH_DEFAULT = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "stable_yield_consistency_log.json"
)
_LOG_CAP = 100

# CV-based component: max 70 pts; at cv == CV_ZERO_THRESHOLD the score hits 0
_CV_MAX_COMPONENT = 70.0
_CV_ZERO_THRESHOLD = 0.5        # cv >= 0.5 → cv_component = 0

# Yield-source bonuses (sum with other components up to 20 pts)
_YIELD_SOURCE_SCORES: dict[str, float] = {
    "real_yield": 20.0,
    "lending_interest": 15.0,
    "trading_fees": 8.0,
    "emissions": 0.0,
}
_YIELD_SOURCE_DEFAULT = 5.0     # for unrecognised yield_source strings

# Rate-lock components
_RATE_LOCK_BASE = 5.0           # pts for having any lock
_LOCK_DURATION_MAX_BONUS = 3.0  # extra pts for long-duration lock
_LOCK_DURATION_SATURATION = 90.0  # days to reach full bonus

# Withdrawal-delay component (stability signal): max 2 pts
_WITHDRAWAL_MAX_BONUS = 2.0
_WITHDRAWAL_SATURATION_DAYS = 10.0   # 10 days → full bonus

# Predictability label bands [upper_bound_exclusive, label]
_LABEL_BANDS = [
    (20.0,  "UNPREDICTABLE"),
    (40.0,  "VOLATILE_YIELD"),
    (60.0,  "MODERATELY_CONSISTENT"),
    (80.0,  "VERY_CONSISTENT"),
    (101.0, "ROCK_SOLID"),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))


def _safe_mean(values: list[float]) -> float:
    """Arithmetic mean; 0.0 for empty lists."""
    if not values:
        return 0.0
    return statistics.mean(values)


def _safe_stdev(values: list[float]) -> float:
    """Sample standard deviation (N-1); 0.0 for fewer than 2 values."""
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


def _coefficient_of_variation(std: float, mean: float) -> float:
    """CV = std / mean; returns 0.0 when mean == 0."""
    if mean == 0.0:
        return 0.0
    return std / mean


def _cv_component(cv: float) -> float:
    """
    Maps CV to a 0-70 consistency component.

    Linear decay:
      cv = 0.0 → 70.0
      cv = 0.5 → 0.0 (CV_ZERO_THRESHOLD)
      cv > 0.5 → 0.0
    """
    if cv >= _CV_ZERO_THRESHOLD:
        return 0.0
    fraction = 1.0 - cv / _CV_ZERO_THRESHOLD
    return round(_clamp(fraction * _CV_MAX_COMPONENT, 0.0, _CV_MAX_COMPONENT), 4)


def _yield_source_component(yield_source: str) -> float:
    """Return bonus points for the yield source type (0-20)."""
    return _YIELD_SOURCE_SCORES.get(yield_source, _YIELD_SOURCE_DEFAULT)


def _rate_lock_component(has_rate_lock: bool, lock_duration_days: float) -> float:
    """
    Base bonus for any lock (5 pts) + up to 3 pts for long-duration lock.
    Returns 0 if no lock.
    """
    if not has_rate_lock:
        return 0.0
    duration_bonus = min(_LOCK_DURATION_MAX_BONUS,
                         lock_duration_days / _LOCK_DURATION_SATURATION
                         * _LOCK_DURATION_MAX_BONUS)
    return round(_RATE_LOCK_BASE + duration_bonus, 4)


def _withdrawal_component(withdrawal_delay_days: float) -> float:
    """
    Small bonus (0-2 pts) for having a non-trivial withdrawal delay.
    Longer lockup signals more predictable yield dynamics.
    """
    raw = min(_WITHDRAWAL_MAX_BONUS,
              withdrawal_delay_days / _WITHDRAWAL_SATURATION_DAYS
              * _WITHDRAWAL_MAX_BONUS)
    return round(_clamp(raw, 0.0, _WITHDRAWAL_MAX_BONUS), 4)


def _compute_consistency_score(
    cv: float,
    yield_source: str,
    has_rate_lock: bool,
    lock_duration_days: float,
    withdrawal_delay_days: float,
) -> float:
    """
    Consistency score (0-100):
      cv_component     (0-70)   — lower CV → higher score
      source_component (0-20)   — yield-source reliability
      lock_component   (0-8)    — rate lock (base 5 + duration bonus 0-3)
      withdrawal_component (0-2) — withdrawal delay signal

    Maximum = 70 + 20 + 8 + 2 = 100.
    """
    cv_c = _cv_component(cv)
    src_c = _yield_source_component(yield_source)
    lock_c = _rate_lock_component(has_rate_lock, lock_duration_days)
    wd_c = _withdrawal_component(withdrawal_delay_days)
    raw = cv_c + src_c + lock_c + wd_c
    return round(_clamp(raw, 0.0, 100.0), 4)


def _compute_label(consistency_score: float) -> str:
    """Map consistency score to predictability label."""
    for upper, label in _LABEL_BANDS:
        if consistency_score < upper:
            return label
    return "ROCK_SOLID"


def _atomic_append_log(log_path: str, entry: dict, cap: int = _LOG_CAP) -> None:
    """Append *entry* to ring-buffer JSON array; atomic write via tmp+replace."""
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
    if len(data) > cap:
        data = data[-cap:]

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(abs_path), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class ProtocolDeFiStableYieldConsistencyScorer:
    """
    Score the yield consistency of a DeFi protocol.

    Usage:
        scorer = ProtocolDeFiStableYieldConsistencyScorer()
        result = scorer.score({
            "protocol_name": "Aave V3",
            "apy_history": [3.5, 3.6, 3.4, 3.5, 3.7, 3.6, 3.5],
            "current_apy_pct": 3.5,
            "yield_source": "lending_interest",
            "has_rate_lock": False,
            "lock_duration_days": 0,
            "min_deposit_usd": 0,
            "withdrawal_delay_days": 0,
        })
    """

    def __init__(self, log_path: str | None = None) -> None:
        self._log_path = log_path or _LOG_PATH_DEFAULT

    # ------------------------------------------------------------------
    # Core scoring helpers (exposed for unit testing)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_mean(apy_history: list[float]) -> float:
        """Arithmetic mean of apy_history."""
        return round(_safe_mean(apy_history), 4)

    @staticmethod
    def compute_std(apy_history: list[float]) -> float:
        """Sample standard deviation of apy_history."""
        return round(_safe_stdev(apy_history), 4)

    @staticmethod
    def compute_cv(std: float, mean: float) -> float:
        """Coefficient of variation = std / mean (0 when mean == 0)."""
        return round(_coefficient_of_variation(std, mean), 6)

    @staticmethod
    def cv_component(cv: float) -> float:
        """CV-based consistency component (0-70)."""
        return _cv_component(cv)

    @staticmethod
    def yield_source_component(yield_source: str) -> float:
        """Yield-source reliability bonus (0-20)."""
        return _yield_source_component(yield_source)

    @staticmethod
    def rate_lock_component(has_rate_lock: bool, lock_duration_days: float) -> float:
        """Rate-lock consistency bonus (0-8)."""
        return _rate_lock_component(has_rate_lock, lock_duration_days)

    @staticmethod
    def withdrawal_component(withdrawal_delay_days: float) -> float:
        """Withdrawal-delay stability signal (0-2)."""
        return _withdrawal_component(withdrawal_delay_days)

    @staticmethod
    def consistency_score(
        cv: float,
        yield_source: str,
        has_rate_lock: bool,
        lock_duration_days: float,
        withdrawal_delay_days: float,
    ) -> float:
        """Compute consistency score (0-100)."""
        return _compute_consistency_score(
            cv, yield_source, has_rate_lock, lock_duration_days, withdrawal_delay_days
        )

    @staticmethod
    def label_for(consistency_score: float) -> str:
        """Return the predictability label for a given consistency score."""
        return _compute_label(consistency_score)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def score(self, data: dict[str, Any], *, write_log: bool = True) -> dict[str, Any]:
        """
        Score the yield consistency of a DeFi protocol.

        Parameters
        ----------
        data : dict
            Input dictionary with the keys documented at module level.
        write_log : bool
            If True (default) append result to the ring-buffer log file.

        Returns
        -------
        dict
            Output dictionary with consistency metrics.
        """
        protocol_name = str(data.get("protocol_name", "unknown"))
        apy_history = [float(v) for v in data.get("apy_history", [])]
        yield_source = str(data.get("yield_source", "unknown"))
        has_rate_lock = bool(data.get("has_rate_lock", False))
        lock_duration_days = float(data.get("lock_duration_days", 0.0))
        withdrawal_delay_days = float(data.get("withdrawal_delay_days", 0.0))

        mean_apy = _safe_mean(apy_history)
        std_apy = _safe_stdev(apy_history)
        cv = _coefficient_of_variation(std_apy, mean_apy)

        score = _compute_consistency_score(
            cv, yield_source, has_rate_lock, lock_duration_days, withdrawal_delay_days
        )
        label = _compute_label(score)

        result: dict[str, Any] = {
            "protocol_name": protocol_name,
            "apy_mean_pct": round(mean_apy, 4),
            "apy_std_pct": round(std_apy, 4),
            "coefficient_of_variation": round(cv, 6),
            "consistency_score": score,
            "predictability_label": label,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        if write_log:
            _atomic_append_log(self._log_path, result)

        return result
