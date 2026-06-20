"""
MP-852 YieldCurveSteepnessAnalyzer
Advisory-only analytics module.
Analyses the term structure of yields across lock-up tenors (flexible / 30 /
90 / 180 / 365 days). Answers: is it worth locking capital for longer to earn
the term premium, and which tenor offers the best marginal trade-off?

Computes absolute spread, slope (bps/day), annualised term premium, the curve
shape (INVERTED / FLAT / NORMAL / STEEP), a recommended tenor, an A-F
attractiveness grade and term-structure risk flags.

Data log: data/yield_curve_steepness_log.json (ring-buffer 100 entries).
Pure stdlib, read-only advisory, atomic writes.
"""

import json
import os
import time
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_RING_SIZE = 100

# Flatness band in bps/day: |slope| <= this is treated as FLAT.
_DEFAULT_FLAT_EPS_BPS_PER_DAY = 0.05

# Minimum marginal bps/day a longer tenor must add to be "worth locking".
_DEFAULT_MIN_MARGINAL_BPS_PER_DAY = 0.05

# Slope band (bps/day) separating NORMAL from STEEP on the upside.
_STEEP_BPS_PER_DAY = 0.30

# Guard threshold for divisions by ~0 day spans.
_ZERO_EPS = 1e-12

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _normalize_points(points) -> list:
    """
    Accept either a list of {"tenor_days": int, "apy": float} dicts OR a plain
    {tenor: apy} mapping, and return a list of (tenor_days, apy) float tuples
    sorted ascending by tenor. Malformed / unparseable entries are skipped.
    Guards None / empty input -> [].
    """
    if not points:
        return []

    pairs = []
    if isinstance(points, dict):
        items = points.items()
        for tenor, apy in items:
            try:
                pairs.append((float(tenor), float(apy)))
            except (TypeError, ValueError):
                continue
    else:
        for entry in points:
            if isinstance(entry, dict):
                if "tenor_days" not in entry or "apy" not in entry:
                    continue
                try:
                    pairs.append((float(entry["tenor_days"]), float(entry["apy"])))
                except (TypeError, ValueError):
                    continue
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                try:
                    pairs.append((float(entry[0]), float(entry[1])))
                except (TypeError, ValueError):
                    continue
    pairs.sort(key=lambda p: p[0])
    return pairs


def _slope_bps_per_day(spread: float, day_span: float):
    """
    Slope of the curve in basis points per day:
      spread / day_span * 10000.
    Returns None when day_span ~ 0 (guard against div-by-zero).
    """
    if day_span is None or abs(float(day_span)) <= _ZERO_EPS:
        return None
    return float(spread) / float(day_span) * 10000.0


def _term_premium_per_year(spread: float, day_span: float):
    """
    Annualised term premium: spread divided by the tenor gap expressed in
    years (day_span / 365). Returns None when day_span ~ 0 (guard).
    """
    if day_span is None or abs(float(day_span)) <= _ZERO_EPS:
        return None
    years = float(day_span) / 365.0
    if abs(years) <= _ZERO_EPS:
        return None
    return float(spread) / years


def _is_monotonic_increasing(pairs: list) -> bool:
    """True when APY never decreases as tenor increases. Empty/single -> True."""
    if not pairs or len(pairs) < 2:
        return True
    for i in range(len(pairs) - 1):
        if pairs[i + 1][1] < pairs[i][1]:
            return False
    return True


# ---------------------------------------------------------------------------
# Shape / recommendation helpers
# ---------------------------------------------------------------------------


def _curve_shape(slope_bps_per_day, flat_eps: float) -> str:
    """
    Classify curve shape from slope (bps/day):
      INVERTED  slope < -flat_eps,
      FLAT      |slope| <= flat_eps,
      NORMAL    flat_eps < slope <= _STEEP_BPS_PER_DAY,
      STEEP     slope > _STEEP_BPS_PER_DAY.
    None slope (degenerate span) -> FLAT.
    """
    if slope_bps_per_day is None:
        return "FLAT"
    s = float(slope_bps_per_day)
    eps = abs(float(flat_eps))
    if s < -eps:
        return "INVERTED"
    if abs(s) <= eps:
        return "FLAT"
    if s <= _STEEP_BPS_PER_DAY:
        return "NORMAL"
    return "STEEP"


def _recommended_tenor(pairs: list, min_marginal_bps_per_day: float):
    """
    Walk the sorted curve and pick the longest tenor whose *marginal* APY gain
    per extra day (vs the previous tenor) is >= min_marginal_bps_per_day. If no
    step clears the bar, fall back to the shortest tenor (don't lock for free).
    Returns None for empty input.
    """
    if not pairs:
        return None
    if len(pairs) == 1:
        return pairs[0][0]

    rec = pairs[0][0]
    for i in range(1, len(pairs)):
        prev_tenor, prev_apy = pairs[i - 1]
        cur_tenor, cur_apy = pairs[i]
        day_span = cur_tenor - prev_tenor
        if abs(day_span) <= _ZERO_EPS:
            continue
        marginal = (cur_apy - prev_apy) / day_span * 10000.0
        if marginal >= float(min_marginal_bps_per_day):
            rec = cur_tenor
        # if a step fails the bar we stop extending — don't lock past a
        # tenor that no longer pays its marginal way.
        else:
            break
    return rec


def _grade(slope_bps_per_day, term_premium_per_year, shape: str) -> str:
    """
    Grade the term-premium attractiveness:
      A  STEEP & meaningful positive premium,
      B  NORMAL upward slope with decent premium,
      C  mild positive / FLAT-ish,
      D  flat with negligible premium,
      F  INVERTED (locking longer is penalised).
    Uses slope tiers; None slope -> D.
    """
    if shape == "INVERTED":
        return "F"
    if slope_bps_per_day is None:
        return "D"
    s = float(slope_bps_per_day)
    if s > _STEEP_BPS_PER_DAY:
        return "A"
    if s > 0.15:
        return "B"
    if s > _DEFAULT_FLAT_EPS_BPS_PER_DAY:
        return "C"
    if s >= 0.0:
        return "D"
    return "F"


def _risk_flags(n_points, shape, is_monotonic, any_negative_yield) -> list:
    """
    Build term-structure risk flags:
      INSUFFICIENT_POINTS   n_points < 2
      INVERTED_CURVE        shape == INVERTED
      NON_MONOTONIC         APY not monotonically increasing in tenor
      NEGATIVE_YIELD        any APY < 0
      FLAT_NO_PREMIUM       shape == FLAT
    """
    flags = []
    if n_points is None or n_points < 2:
        flags.append("INSUFFICIENT_POINTS")
    if shape == "INVERTED":
        flags.append("INVERTED_CURVE")
    if not is_monotonic:
        flags.append("NON_MONOTONIC")
    if any_negative_yield:
        flags.append("NEGATIVE_YIELD")
    if shape == "FLAT":
        flags.append("FLAT_NO_PREMIUM")
    return flags


def _recommendations(grade: str, flags: list, recommended_tenor) -> list:
    """Human-readable advisory strings driven by grade and flags."""
    flags = flags or []
    recs = []
    if grade == "A":
        recs.append("Steep curve — locking capital longer earns a strong term premium")
    elif grade == "B":
        recs.append("Upward curve — extending tenor is rewarded with a solid premium")
    elif grade == "C":
        recs.append("Mildly upward curve — modest premium for locking longer")
    elif grade == "D":
        recs.append("Flat curve — little reward for locking; favour flexibility")
    else:  # F
        recs.append("Inverted curve — longer tenors pay less; stay short / flexible")
    if recommended_tenor is not None:
        recs.append(f"Recommended tenor: {int(recommended_tenor)} days")
    if "INSUFFICIENT_POINTS" in flags:
        recs.append("Insufficient points — need at least two tenors to assess the curve")
    if "INVERTED_CURVE" in flags:
        recs.append("Curve is inverted — short-dated yields exceed long-dated")
    if "NON_MONOTONIC" in flags:
        recs.append("Non-monotonic curve — APY does not rise consistently with tenor")
    if "NEGATIVE_YIELD" in flags:
        recs.append("Negative yield present — at least one tenor quotes a sub-zero APY")
    if "FLAT_NO_PREMIUM" in flags:
        recs.append("Flat curve offers no meaningful term premium")
    return recs


# ---------------------------------------------------------------------------
# Core analyze function
# ---------------------------------------------------------------------------


def analyze(points, config: dict = None) -> dict:
    """
    Analyse the yield-curve steepness across lock-up tenors.

    Parameters
    ----------
    points : list[dict] | dict
        Either a list of {"tenor_days": int, "apy": float} dicts, or a plain
        {tenor_days: apy} mapping. Normalised and sorted internally.
    config : dict | None
        flat_eps_bps_per_day        (default ~0.05),
        min_marginal_bps_per_day    (default ~0.05).

    Returns
    -------
    dict with n_points, short_tenor, short_apy, long_tenor, long_apy,
    absolute_spread, slope_bps_per_day, term_premium_per_year,
    is_monotonic_increasing, curve_shape, recommended_tenor, grade,
    classification, risk_flags, recommendations, timestamp.
    """
    cfg = config or {}
    flat_eps = float(cfg.get("flat_eps_bps_per_day", _DEFAULT_FLAT_EPS_BPS_PER_DAY))
    min_marginal = float(cfg.get("min_marginal_bps_per_day", _DEFAULT_MIN_MARGINAL_BPS_PER_DAY))

    pairs = _normalize_points(points)
    n_points = len(pairs)
    any_negative = any(apy < 0 for _, apy in pairs)

    # Insufficient points: fewer than two distinct curve points.
    if n_points < 2:
        short_tenor = pairs[0][0] if n_points == 1 else None
        short_apy = pairs[0][1] if n_points == 1 else None
        is_monotonic = _is_monotonic_increasing(pairs)
        flags = _risk_flags(n_points, "FLAT", is_monotonic, any_negative)
        return {
            "n_points": n_points,
            "short_tenor": short_tenor,
            "short_apy": short_apy,
            "long_tenor": short_tenor,
            "long_apy": short_apy,
            "absolute_spread": None,
            "slope_bps_per_day": None,
            "term_premium_per_year": None,
            "is_monotonic_increasing": is_monotonic,
            "curve_shape": "FLAT",
            "recommended_tenor": short_tenor,
            "grade": "F",
            "classification": "FLAT",
            "risk_flags": flags,
            "recommendations": [
                "Insufficient points — need at least two tenors to assess the curve"
            ],
            "timestamp": time.time(),
        }

    short_tenor, short_apy = pairs[0]
    long_tenor, long_apy = pairs[-1]
    day_span = long_tenor - short_tenor

    absolute_spread = long_apy - short_apy
    slope = _slope_bps_per_day(absolute_spread, day_span)
    term_premium = _term_premium_per_year(absolute_spread, day_span)
    is_monotonic = _is_monotonic_increasing(pairs)

    shape = _curve_shape(slope, flat_eps)
    recommended = _recommended_tenor(pairs, min_marginal)
    grade = _grade(slope, term_premium, shape)
    flags = _risk_flags(n_points, shape, is_monotonic, any_negative)
    recs = _recommendations(grade, flags, recommended)

    return {
        "n_points": n_points,
        "short_tenor": short_tenor,
        "short_apy": short_apy,
        "long_tenor": long_tenor,
        "long_apy": long_apy,
        "absolute_spread": absolute_spread,
        "slope_bps_per_day": slope,
        "term_premium_per_year": term_premium,
        "is_monotonic_increasing": is_monotonic,
        "curve_shape": shape,
        "recommended_tenor": recommended,
        "grade": grade,
        "classification": shape,
        "risk_flags": flags,
        "recommendations": recs,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer 100)
# ---------------------------------------------------------------------------


def log_result(result: dict, data_dir: str = "data") -> None:
    """Atomically append result snapshot to ring-buffer log (max 100 entries)."""
    log_path = os.path.join(data_dir, "yield_curve_steepness_log.json")

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log = json.load(fh)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    snapshot = {
        "timestamp": result["timestamp"],
        "n_points": result["n_points"],
        "absolute_spread": result["absolute_spread"],
        "slope_bps_per_day": result["slope_bps_per_day"],
        "term_premium_per_year": result["term_premium_per_year"],
        "curve_shape": result["curve_shape"],
        "recommended_tenor": result["recommended_tenor"],
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

_SAMPLE_POINTS = [
    {"tenor_days": 0, "apy": 4.0},
    {"tenor_days": 30, "apy": 4.8},
    {"tenor_days": 90, "apy": 5.6},
    {"tenor_days": 180, "apy": 6.3},
    {"tenor_days": 365, "apy": 7.1},
]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-852 YieldCurveSteepnessAnalyzer")
    parser.add_argument("--check", action="store_true",
                        help="Compute and print, no write (default)")
    parser.add_argument("--run", action="store_true",
                        help="Compute, print, and write log")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    args = parser.parse_args()

    result = analyze(_SAMPLE_POINTS)

    def _fmt(v):
        return "None" if v is None else f"{v:.4f}"

    print(f"Curve points      : {result['n_points']}")
    print(f"Short tenor/apy   : {_fmt(result['short_tenor'])}d / {_fmt(result['short_apy'])}")
    print(f"Long tenor/apy    : {_fmt(result['long_tenor'])}d / {_fmt(result['long_apy'])}")
    print(f"Absolute spread   : {_fmt(result['absolute_spread'])}")
    print(f"Slope (bps/day)   : {_fmt(result['slope_bps_per_day'])}")
    print(f"Term premium/yr   : {_fmt(result['term_premium_per_year'])}")
    print(f"Monotonic         : {result['is_monotonic_increasing']}")
    print(f"Curve shape       : {result['curve_shape']}")
    print(f"Recommended tenor : {_fmt(result['recommended_tenor'])}")
    print(f"Grade             : {result['grade']}")
    print(f"Classification    : {result['classification']}")
    print(f"Risk flags        : {result['risk_flags']}")
    for r in result["recommendations"]:
        print(f"  - {r}")

    if args.run:
        log_result(result, data_dir=args.data_dir)
        print(f"Log written to    : {args.data_dir}/yield_curve_steepness_log.json")
