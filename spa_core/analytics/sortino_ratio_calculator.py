"""
MP-835 SortinoRatioCalculator
Advisory-only analytics module.
Computes the downside-risk-adjusted return (Sortino ratio) for a series of
periodic returns. Complements sharpe_ratio_calculator.py but uses ONLY the
downside deviation (target semi-deviation) rather than full volatility.

Data log: data/sortino_ratio_log.json (ring-buffer 100 entries).
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
_DEFAULT_TARGET_RETURN = 0.0
_DEFAULT_RISK_FREE = 0.0
_DEFAULT_PERIODS_PER_YEAR = 365
_DEFAULT_ANNUALIZE = True

# Threshold below which a deviation is treated as exactly zero
# (guards against floating-point dust on constant series).
_ZERO_EPS = 1e-12

# Annualized downside-vol threshold for the HIGH_DOWNSIDE_VOL flag.
_HIGH_DOWNSIDE_VOL = 0.20

# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------


def _mean(returns: list) -> float:
    """Arithmetic mean of a list of returns. Guards empty input."""
    if not returns:
        return 0.0
    n = len(returns)
    if n <= 0:
        return 0.0
    return sum(float(r) for r in returns) / n


def _stdev(returns: list) -> float:
    """Sample standard deviation (n-1). Returns 0.0 for <2 points."""
    n = len(returns) if returns else 0
    if n < 2:
        return 0.0
    m = _mean(returns)
    var = sum((float(r) - m) ** 2 for r in returns) / (n - 1)
    if var <= 0:
        return 0.0
    return math.sqrt(var)


def _downside_deviation(returns: list, target: float) -> float:
    """
    Target semi-deviation: sqrt of the mean over ALL n periods of
    (min(0, r - target))**2. Returns 0.0 when there are no observations
    below target. Guards empty input (None handled by caller).
    """
    n = len(returns) if returns else 0
    if n <= 0:
        return 0.0
    acc = 0.0
    for r in returns:
        diff = float(r) - float(target)
        if diff < 0:
            acc += diff * diff
    mean_sq = acc / n
    if mean_sq <= _ZERO_EPS:
        return 0.0
    return math.sqrt(mean_sq)


def _sortino(mean: float, target: float, dd):
    """
    Periodic Sortino ratio = (mean - target) / downside_deviation.
    Returns None when dd is None or zero (caller treats as NO_DOWNSIDE).
    """
    if dd is None:
        return None
    if dd <= _ZERO_EPS:
        return None
    return (float(mean) - float(target)) / dd


def _sharpe(mean: float, risk_free: float, stdev):
    """
    Periodic Sharpe ratio = (mean - risk_free) / stdev. Returns None when
    stdev is None or zero.
    """
    if stdev is None:
        return None
    if stdev <= _ZERO_EPS:
        return None
    return (float(mean) - float(risk_free)) / stdev


def _annualize(value, periods: int):
    """
    Annualize a periodic ratio by multiplying by sqrt(periods_per_year).
    Returns None when value is None or periods <= 0.
    """
    if value is None:
        return None
    if periods is None or periods <= 0:
        return None
    return value * math.sqrt(periods)


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def _grade(ann_sortino, flags) -> str:
    """
    Grade by annualized Sortino:
      >=3 -> A, >=2 -> B, >=1 -> C, >=0 -> D, <0 -> F.
    None grades F UNLESS the NO_DOWNSIDE positive case (no downside obs and a
    non-negative mean) which earns an A.
    """
    flags = flags or []
    if ann_sortino is None:
        if "NO_DOWNSIDE" in flags and "NEGATIVE_RETURN" not in flags:
            return "A"
        return "F"
    if ann_sortino >= 3.0:
        return "A"
    if ann_sortino >= 2.0:
        return "B"
    if ann_sortino >= 1.0:
        return "C"
    if ann_sortino >= 0.0:
        return "D"
    return "F"


def _classification(sortino, mean) -> str:
    """
    Classify by periodic (or annualized — same sign/tier mapping) Sortino:
      EXCELLENT (sortino >= 2), GOOD (>= 1), ADEQUATE (>= 0),
      POOR (< 0 but mean >= 0), NEGATIVE (mean < 0).
    When sortino is None: EXCELLENT if mean >= target-proxy (mean >= 0),
    else NEGATIVE.
    """
    m = float(mean) if mean is not None else 0.0
    if sortino is None:
        if m >= 0:
            return "EXCELLENT"
        return "NEGATIVE"
    if sortino >= 2.0:
        return "EXCELLENT"
    if sortino >= 1.0:
        return "GOOD"
    if sortino >= 0.0:
        return "ADEQUATE"
    # sortino < 0
    if m >= 0:
        return "POOR"
    return "NEGATIVE"


def _risk_flags(mean: float, downside_deviation, ann_downside_deviation) -> list:
    """
    Build risk flags:
      NEGATIVE_RETURN     mean_return < 0
      NO_DOWNSIDE         no downside observations (dd is 0 / None)
      HIGH_DOWNSIDE_VOL   annualized downside deviation > 0.20
    """
    flags = []
    if mean is not None and float(mean) < 0:
        flags.append("NEGATIVE_RETURN")
    if downside_deviation is None or downside_deviation <= _ZERO_EPS:
        flags.append("NO_DOWNSIDE")
    if ann_downside_deviation is not None and ann_downside_deviation > _HIGH_DOWNSIDE_VOL:
        flags.append("HIGH_DOWNSIDE_VOL")
    return flags


def _recommendations(grade: str, flags: list, sortino) -> list:
    """Human-readable advisory strings driven by grade and flags."""
    flags = flags or []
    recs = []
    if grade in ("A", "B"):
        recs.append("Strong downside-risk-adjusted performance — suitable core allocation")
    elif grade == "C":
        recs.append("Adequate downside-risk-adjusted return — acceptable with monitoring")
    elif grade == "D":
        recs.append("Marginal downside-risk-adjusted return — keep position sizes modest")
    else:  # F
        recs.append("Weak downside-risk-adjusted return — reconsider allocation")
    if "NEGATIVE_RETURN" in flags:
        recs.append("Mean return is negative — strategy is losing capital on average")
    if "HIGH_DOWNSIDE_VOL" in flags:
        recs.append("High downside volatility — expect large adverse swings")
    if "NO_DOWNSIDE" in flags:
        recs.append("No returns fell below target — Sortino undefined (no downside observed)")
    return recs


# ---------------------------------------------------------------------------
# Core analyze function
# ---------------------------------------------------------------------------


def analyze(returns: list, config: dict = None) -> dict:
    """
    Compute downside-risk-adjusted (Sortino) metrics for a return series.

    Parameters
    ----------
    returns : list[float]
        Periodic fractional returns (e.g. daily returns like 0.001).
    config : dict | None
        target_return (MAR, default 0.0), risk_free (default 0.0),
        periods_per_year (int, default 365), annualize (bool, default True).

    Returns
    -------
    dict with mean_return, target_return, downside_deviation, sortino_ratio,
    annualized_sortino, stdev, sharpe_ratio, annualized_sharpe, n, grade,
    classification, risk_flags, recommendations, timestamp.
    """
    cfg = config or {}
    target_return = float(cfg.get("target_return", _DEFAULT_TARGET_RETURN))
    risk_free = float(cfg.get("risk_free", _DEFAULT_RISK_FREE))
    periods_per_year = int(cfg.get("periods_per_year", _DEFAULT_PERIODS_PER_YEAR))
    annualize = bool(cfg.get("annualize", _DEFAULT_ANNUALIZE))

    returns = list(returns) if returns else []
    n = len(returns)

    # Insufficient data: empty or single point.
    if n < 2:
        mean_return = _mean(returns) if n == 1 else 0.0
        return {
            "mean_return": mean_return,
            "target_return": target_return,
            "downside_deviation": None,
            "sortino_ratio": None,
            "annualized_sortino": None,
            "stdev": None,
            "sharpe_ratio": None,
            "annualized_sharpe": None,
            "n": n,
            "grade": "F",
            "classification": "INSUFFICIENT_DATA",
            "risk_flags": [],
            "recommendations": ["Insufficient data — need at least 2 returns"],
            "timestamp": time.time(),
        }

    mean_return = _mean(returns)
    stdev = _stdev(returns)
    dd = _downside_deviation(returns, target_return)

    # downside_deviation of exactly 0 means no downside observations.
    if dd <= _ZERO_EPS:
        dd_value = 0.0
        sortino_ratio = None
        ann_dd = 0.0
    else:
        dd_value = dd
        sortino_ratio = _sortino(mean_return, target_return, dd)
        ann_dd = _annualize(dd, periods_per_year) if annualize else dd

    sharpe_ratio = _sharpe(mean_return, risk_free, stdev)

    if annualize:
        annualized_sortino = _annualize(sortino_ratio, periods_per_year)
        annualized_sharpe = _annualize(sharpe_ratio, periods_per_year)
    else:
        annualized_sortino = sortino_ratio
        annualized_sharpe = sharpe_ratio

    flags = _risk_flags(mean_return, dd_value, ann_dd)
    grade = _grade(annualized_sortino, flags)
    classification = _classification(sortino_ratio, mean_return)
    recs = _recommendations(grade, flags, sortino_ratio)

    return {
        "mean_return": mean_return,
        "target_return": target_return,
        "downside_deviation": dd_value,
        "sortino_ratio": sortino_ratio,
        "annualized_sortino": annualized_sortino,
        "stdev": stdev,
        "sharpe_ratio": sharpe_ratio,
        "annualized_sharpe": annualized_sharpe,
        "n": n,
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
    log_path = os.path.join(data_dir, "sortino_ratio_log.json")

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
        "mean_return": result["mean_return"],
        "downside_deviation": result["downside_deviation"],
        "sortino_ratio": result["sortino_ratio"],
        "annualized_sortino": result["annualized_sortino"],
        "grade": result["grade"],
    }
    log.append(snapshot)

    if len(log) > _LOG_RING_SIZE:
        log = log[-_LOG_RING_SIZE:]

    os.makedirs(data_dir, exist_ok=True)
    atomic_save(log, str(log_path))
# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_SAMPLE_RETURNS = [
    0.0012, -0.0005, 0.0021, 0.0008, -0.0011, 0.0015, 0.0003,
    -0.0007, 0.0019, 0.0006, 0.0010, -0.0002, 0.0014, 0.0009,
]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-835 SortinoRatioCalculator")
    parser.add_argument("--check", action="store_true",
                        help="Compute and print, no write (default)")
    parser.add_argument("--run", action="store_true",
                        help="Compute, print, and write log")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    args = parser.parse_args()

    result = analyze(_SAMPLE_RETURNS)

    def _fmt(v):
        return "None" if v is None else f"{v:.4f}"

    print(f"Returns count     : {result['n']}")
    print(f"Mean return       : {_fmt(result['mean_return'])}")
    print(f"Target return     : {_fmt(result['target_return'])}")
    print(f"Downside dev      : {_fmt(result['downside_deviation'])}")
    print(f"Sortino (periodic): {_fmt(result['sortino_ratio'])}")
    print(f"Sortino (annual)  : {_fmt(result['annualized_sortino'])}")
    print(f"Sharpe (periodic) : {_fmt(result['sharpe_ratio'])}")
    print(f"Sharpe (annual)   : {_fmt(result['annualized_sharpe'])}")
    print(f"Grade             : {result['grade']}")
    print(f"Classification    : {result['classification']}")
    print(f"Risk flags        : {result['risk_flags']}")
    for r in result["recommendations"]:
        print(f"  - {r}")

    if args.run:
        log_result(result, data_dir=args.data_dir)
        print(f"Log written to    : {args.data_dir}/sortino_ratio_log.json")
