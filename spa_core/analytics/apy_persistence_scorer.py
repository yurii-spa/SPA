"""
MP-851 APYPersistenceScorer
Advisory-only analytics module.
Scores how "sticky"/durable a quoted APY has been over a historical series.
Distinct from volatility trackers: this measures *temporal persistence and
reliability* (does the rate hold up over time?) rather than raw dispersion.

Combines four temporal signals — time spent above a reference threshold,
lag-1 autocorrelation (level inertia), coefficient of variation, and drawdown
from the historical peak — into a 0-100 persistence score with an A-F grade.

Data log: data/apy_persistence_log.json (ring-buffer 100 entries).
Pure stdlib, read-only advisory, atomic writes.
"""

import json
import os
import time
import math
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_RING_SIZE = 100
_DEFAULT_MIN_PERIODS = 3

# Threshold below which a stdev is treated as exactly zero
# (guards against floating-point dust on constant series).
_ZERO_EPS = 1e-12

# Trend band: half-series means must differ by more than this fraction of the
# overall mean to count as IMPROVING / DECAYING (else STABLE).
_TREND_BAND = 0.05

# Risk-flag thresholds.
_HIGH_CV = 0.5
_SHARP_DECAY_PCT = 30.0
_BELOW_THRESHOLD_PCT = 50.0

# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------


def _mean(series: list) -> float:
    """Arithmetic mean of a list. Guards empty input -> 0.0."""
    if not series:
        return 0.0
    n = len(series)
    if n <= 0:
        return 0.0
    return sum(float(x) for x in series) / n


def _stdev(series: list) -> float:
    """Population standard deviation. Returns 0.0 for <2 points."""
    n = len(series) if series else 0
    if n < 2:
        return 0.0
    m = _mean(series)
    var = sum((float(x) - m) ** 2 for x in series) / n
    if var <= 0:
        return 0.0
    return math.sqrt(var)


def _peak(series: list) -> float:
    """Maximum value of the series. Guards empty input -> 0.0."""
    if not series:
        return 0.0
    return max(float(x) for x in series)


def _time_above_threshold_pct(series: list, threshold: float) -> float:
    """
    Percentage (0-100) of observations >= threshold.
    Guards empty input -> 0.0.
    """
    if not series:
        return 0.0
    n = len(series)
    if n <= 0:
        return 0.0
    above = sum(1 for x in series if float(x) >= float(threshold))
    return above / n * 100.0


def _lag1_autocorrelation(series):
    """
    Lag-1 autocorrelation of the series. Returns None when there are fewer
    than 2 points or the variance is ~0 (guard against div-by-zero).
    Result is clamped to [-1.0, 1.0] to absorb floating-point overshoot.
    """
    n = len(series) if series else 0
    if n < 2:
        return None
    m = _mean(series)
    denom = sum((float(x) - m) ** 2 for x in series)
    if denom <= _ZERO_EPS:
        return None
    num = 0.0
    for i in range(n - 1):
        num += (float(series[i]) - m) * (float(series[i + 1]) - m)
    ac = num / denom
    if ac > 1.0:
        return 1.0
    if ac < -1.0:
        return -1.0
    return ac


def _coefficient_of_variation(mean: float, stdev: float):
    """
    Coefficient of variation = stdev / |mean|. Returns None when |mean| ~ 0
    (guard against div-by-zero).
    """
    if mean is None or stdev is None:
        return None
    am = abs(float(mean))
    if am <= _ZERO_EPS:
        return None
    return float(stdev) / am


def _drawdown_from_peak_pct(peak: float, current: float):
    """
    Drawdown of current value from the historical peak, as a percentage:
      (peak - current) / peak * 100.
    Returns None when peak ~ 0 (guard against div-by-zero). Negative values
    (current above peak — only possible via float dust) are clamped to 0.
    """
    if peak is None or current is None:
        return None
    p = float(peak)
    if abs(p) <= _ZERO_EPS:
        return None
    dd = (p - float(current)) / p * 100.0
    if dd < 0.0:
        return 0.0
    return dd


def _trend(series: list, mean: float) -> str:
    """
    Compare the mean of the first half vs the second half of the series.
    IMPROVING when 2nd half exceeds 1st half by more than _TREND_BAND * mean,
    DECAYING when it falls short by the same band, else STABLE. Guards short
    series and ~0 mean (falls back to absolute comparison).
    """
    n = len(series) if series else 0
    if n < 2:
        return "STABLE"
    half = n // 2
    first = series[:half]
    second = series[half:]
    if not first or not second:
        return "STABLE"
    m1 = _mean(first)
    m2 = _mean(second)
    diff = m2 - m1
    band = _TREND_BAND * abs(float(mean)) if mean else 0.0
    if band <= _ZERO_EPS:
        # mean ~ 0: use a tiny absolute band on the diff itself
        if diff > _ZERO_EPS:
            return "IMPROVING"
        if diff < -_ZERO_EPS:
            return "DECAYING"
        return "STABLE"
    if diff > band:
        return "IMPROVING"
    if diff < -band:
        return "DECAYING"
    return "STABLE"


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _persistence_score(time_above_pct, autocorr, cv, drawdown_pct) -> float:
    """
    Weighted 0-100 composition of four temporal-persistence signals:
      * time_above_threshold component (weight 0.35) — high is sticky.
      * autocorrelation component      (weight 0.25) — positive inertia is good.
      * coefficient-of-variation comp. (weight 0.20) — low CV is good.
      * drawdown-from-peak component   (weight 0.20) — small drawdown is good.
    Each sub-component is normalised to 0-100; None inputs degrade gracefully
    to a neutral mid value so the score never raises.
    """
    # time above threshold: already 0-100.
    ta = time_above_pct if time_above_pct is not None else 50.0
    ta = max(0.0, min(100.0, ta))

    # autocorrelation in [-1,1] -> 0-100 (1 -> 100, 0 -> 50, -1 -> 0).
    if autocorr is None:
        ac_comp = 50.0
    else:
        ac_comp = (max(-1.0, min(1.0, autocorr)) + 1.0) / 2.0 * 100.0

    # CV: 0 -> 100, 1.0 -> 0 (clamp). None -> neutral 50.
    if cv is None:
        cv_comp = 50.0
    else:
        cv_comp = max(0.0, 100.0 - max(0.0, cv) * 100.0)

    # drawdown pct: 0 -> 100, 100 -> 0. None -> neutral 50.
    if drawdown_pct is None:
        dd_comp = 50.0
    else:
        dd_comp = max(0.0, 100.0 - max(0.0, min(100.0, drawdown_pct)))

    score = 0.35 * ta + 0.25 * ac_comp + 0.20 * cv_comp + 0.20 * dd_comp
    return max(0.0, min(100.0, score))


def _grade(score) -> str:
    """Grade by persistence score: >=80 A, >=65 B, >=50 C, >=35 D, else F."""
    if score is None:
        return "F"
    if score >= 80.0:
        return "A"
    if score >= 65.0:
        return "B"
    if score >= 50.0:
        return "C"
    if score >= 35.0:
        return "D"
    return "F"


def _classification(score) -> str:
    """
    Classify by persistence score:
      STICKY (>=80), DURABLE (>=65), MODERATE (>=50),
      VOLATILE (>=35), EPHEMERAL (<35).
    """
    if score is None:
        return "EPHEMERAL"
    if score >= 80.0:
        return "STICKY"
    if score >= 65.0:
        return "DURABLE"
    if score >= 50.0:
        return "MODERATE"
    if score >= 35.0:
        return "VOLATILE"
    return "EPHEMERAL"


def _risk_flags(n, min_periods, cv, drawdown_pct, time_above_pct, trend) -> list:
    """
    Build risk flags:
      INSUFFICIENT_DATA          n < min_periods
      HIGH_VOLATILITY            CV > 0.5
      SHARP_DECAY                drawdown_from_peak > 30%
      BELOW_THRESHOLD_MAJORITY   time_above_threshold < 50%
      NEGATIVE_TREND             trend == DECAYING
    """
    flags = []
    if n is not None and min_periods is not None and n < min_periods:
        flags.append("INSUFFICIENT_DATA")
    if cv is not None and cv > _HIGH_CV:
        flags.append("HIGH_VOLATILITY")
    if drawdown_pct is not None and drawdown_pct > _SHARP_DECAY_PCT:
        flags.append("SHARP_DECAY")
    if time_above_pct is not None and time_above_pct < _BELOW_THRESHOLD_PCT:
        flags.append("BELOW_THRESHOLD_MAJORITY")
    if trend == "DECAYING":
        flags.append("NEGATIVE_TREND")
    return flags


def _recommendations(grade: str, flags: list) -> list:
    """Human-readable advisory strings driven by grade and flags."""
    flags = flags or []
    recs = []
    if grade in ("A", "B"):
        recs.append("APY has been durable over time — suitable as a core yield source")
    elif grade == "C":
        recs.append("APY persistence is moderate — acceptable with periodic review")
    elif grade == "D":
        recs.append("APY persistence is weak — keep allocation modest and monitor closely")
    else:  # F
        recs.append("APY has been ephemeral — treat quoted rate with caution")
    if "INSUFFICIENT_DATA" in flags:
        recs.append("Insufficient history to judge persistence — gather more observations")
    if "HIGH_VOLATILITY" in flags:
        recs.append("High coefficient of variation — quoted APY swings widely")
    if "SHARP_DECAY" in flags:
        recs.append("Sharp decay from peak — current rate well below historical high")
    if "BELOW_THRESHOLD_MAJORITY" in flags:
        recs.append("APY spent most of its history below the reference threshold")
    if "NEGATIVE_TREND" in flags:
        recs.append("Downward trend detected — second-half mean below first-half mean")
    return recs


# ---------------------------------------------------------------------------
# Core analyze function
# ---------------------------------------------------------------------------


def analyze(apy_series: list, config: dict = None) -> dict:
    """
    Score the temporal persistence / stickiness of a quoted-APY series.

    Parameters
    ----------
    apy_series : list[float]
        Historical APY observations in chronological order.
    config : dict | None
        threshold    (reference level; default = mean of the series),
        min_periods  (int, default 3).

    Returns
    -------
    dict with n, mean_apy, current_apy, peak_apy, threshold,
    time_above_threshold_pct, lag1_autocorrelation, coefficient_of_variation,
    drawdown_from_peak_pct, trend, persistence_score, grade, classification,
    risk_flags, recommendations, timestamp.
    """
    cfg = config or {}
    min_periods = int(cfg.get("min_periods", _DEFAULT_MIN_PERIODS))

    series = [float(x) for x in apy_series] if apy_series else []
    n = len(series)

    mean_apy = _mean(series) if n else 0.0
    # threshold defaults to the series mean.
    threshold = float(cfg["threshold"]) if cfg.get("threshold") is not None else mean_apy

    # Insufficient data: fewer than min_periods observations.
    if n < min_periods:
        return {
            "n": n,
            "mean_apy": mean_apy,
            "current_apy": series[-1] if n else None,
            "peak_apy": _peak(series) if n else None,
            "threshold": threshold,
            "time_above_threshold_pct": None,
            "lag1_autocorrelation": None,
            "coefficient_of_variation": None,
            "drawdown_from_peak_pct": None,
            "trend": "STABLE",
            "persistence_score": None,
            "grade": "F",
            "classification": "INSUFFICIENT_DATA",
            "risk_flags": ["INSUFFICIENT_DATA"],
            "recommendations": [
                "Insufficient data — need at least "
                f"{min_periods} APY observations"
            ],
            "timestamp": time.time(),
        }

    current_apy = series[-1]
    peak_apy = _peak(series)
    stdev = _stdev(series)

    time_above = _time_above_threshold_pct(series, threshold)
    autocorr = _lag1_autocorrelation(series)
    cv = _coefficient_of_variation(mean_apy, stdev)
    drawdown = _drawdown_from_peak_pct(peak_apy, current_apy)
    trend = _trend(series, mean_apy)

    score = _persistence_score(time_above, autocorr, cv, drawdown)
    flags = _risk_flags(n, min_periods, cv, drawdown, time_above, trend)
    grade = _grade(score)
    classification = _classification(score)
    recs = _recommendations(grade, flags)

    return {
        "n": n,
        "mean_apy": mean_apy,
        "current_apy": current_apy,
        "peak_apy": peak_apy,
        "threshold": threshold,
        "time_above_threshold_pct": time_above,
        "lag1_autocorrelation": autocorr,
        "coefficient_of_variation": cv,
        "drawdown_from_peak_pct": drawdown,
        "trend": trend,
        "persistence_score": score,
        "grade": grade,
        "classification": classification,
        "risk_flags": flags,
        "recommendations": recs,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer 100)
# ---------------------------------------------------------------------------


def log_result(result: dict, data_dir: str = "data") -> None:
    """Atomically append result snapshot to ring-buffer log (max 100 entries)."""
    log_path = os.path.join(data_dir, "apy_persistence_log.json")

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log = json.load(fh)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    snapshot = {
        "timestamp": result["timestamp"],
        "n": result["n"],
        "mean_apy": result["mean_apy"],
        "current_apy": result["current_apy"],
        "persistence_score": result["persistence_score"],
        "drawdown_from_peak_pct": result["drawdown_from_peak_pct"],
        "grade": result["grade"],
        "classification": result["classification"],
    }
    log.append(snapshot)

    if len(log) > _LOG_RING_SIZE:
        log = log[-_LOG_RING_SIZE:]

    os.makedirs(data_dir, exist_ok=True)
    atomic_save(log, str(log_path))
# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_SAMPLE_SERIES = [
    8.2, 8.1, 8.3, 8.0, 7.9, 8.1, 8.2, 8.0, 7.8, 8.1,
    8.0, 7.9, 8.2, 8.1, 8.0, 7.7, 8.0, 8.1, 7.9, 8.0,
]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-851 APYPersistenceScorer")
    parser.add_argument("--check", action="store_true",
                        help="Compute and print, no write (default)")
    parser.add_argument("--run", action="store_true",
                        help="Compute, print, and write log")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    args = parser.parse_args()

    result = analyze(_SAMPLE_SERIES)

    def _fmt(v):
        return "None" if v is None else f"{v:.4f}"

    print(f"Observations      : {result['n']}")
    print(f"Mean APY          : {_fmt(result['mean_apy'])}")
    print(f"Current APY       : {_fmt(result['current_apy'])}")
    print(f"Peak APY          : {_fmt(result['peak_apy'])}")
    print(f"Time above thresh : {_fmt(result['time_above_threshold_pct'])}%")
    print(f"Lag-1 autocorr    : {_fmt(result['lag1_autocorrelation'])}")
    print(f"Coeff of variation: {_fmt(result['coefficient_of_variation'])}")
    print(f"Drawdown from peak: {_fmt(result['drawdown_from_peak_pct'])}%")
    print(f"Trend             : {result['trend']}")
    print(f"Persistence score : {_fmt(result['persistence_score'])}")
    print(f"Grade             : {result['grade']}")
    print(f"Classification    : {result['classification']}")
    print(f"Risk flags        : {result['risk_flags']}")
    for r in result["recommendations"]:
        print(f"  - {r}")

    if args.run:
        log_result(result, data_dir=args.data_dir)
        print(f"Log written to    : {args.data_dir}/apy_persistence_log.json")
