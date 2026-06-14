"""
MP-1142  DeFiProtocolYieldTermStructureAnalyzer
-----------------------------------------------
Analyse the *term structure* of yield across different tenors / lock durations
for a single market (e.g. fixed-rate Pendle PT tenors with distinct maturities,
or lock-up vaults paying different APRs for different lock lengths) and judge
whether the curve is healthy (normal, upward sloping with a real pickup for
locking longer) or distressed (inverted, with short rates above long rates).

A yield curve is a set of (tenor_days, apr_pct) points. The *shape* of that
curve carries information: a normal, upward-sloping curve pays you a term
premium for locking capital longer; a *flat* curve pays nothing extra for the
loss of liquidity; an *inverted* curve (short rates above long rates) signals
that the market expects rates to fall, or that there is stress pulling the front
end up. Locking long into a flat or inverted curve sacrifices liquidity for no
(or negative) pickup. Conversely a steep curve with a genuine pickup rewards
locking. This module makes that shape explicit and recommends the tenor with the
best annualised carry once a reinvestment-risk assumption on the short end is
priced in.

For a single curve the module computes:
- the short-end and long-end APR (extreme tenors),
- the curve slope (long minus short, normalised per year of extra tenor),
- the term spread (long minus short, in pct),
- whether the curve is inverted, and the inversion magnitude,
- a steepness classification,
- the optimal tenor: the point with the best annualised carry once the short
  end is penalised by a reinvestment-rate assumption (you cannot assume you can
  keep rolling the short tenor at today's high short rate),
- the pickup of the optimal tenor over the short end,
- a 0-100 *term-structure score* (higher = a healthy, normal, upward-sloping
  curve that pays a real premium for locking).

Genuine gap: the analytics package has several generic ``yield_curve`` helpers
(builders, trackers, spread/steepness analysers), but none is a per-tenor DeFi
*term-structure* analyser that ingests explicit (tenor_days, apr_pct) lock
points, detects curve inversion, prices a reinvestment-risk penalty on the short
end, and recommends an optimal lock tenor with a single term-structure score. A
grep for "term_structure" and "curve_inversion" across the package confirms no
existing module covers this specific (tenor, lock, inversion, optimal-tenor)
angle.

The module returns:
- name (input echo) / points (normalised curve points)
- short_tenor_days / long_tenor_days
- short_apr_pct / long_apr_pct
- term_spread_pct               - long APR minus short APR
- curve_slope_pct_per_year      - term spread normalised per year of extra tenor
- is_inverted                   - bool: short rate above long rate
- inversion_magnitude_pct       - how far inverted (0 if normal)
- steepness_classification      - STEEP_NORMAL .. DEEPLY_INVERTED
- optimal_tenor_days            - tenor with best reinvest-adjusted carry
- optimal_tenor_apr_pct         - that tenor's APR
- pickup_vs_short_pct           - optimal carry minus short carry
- term_structure_score          - 0-100, higher = healthy normal curve
- grade                         - A-F letter grade
- flags / recommendations       - advisory verdicts

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "yield_term_structure_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Sentinel for "no meaningful tenor" (so JSON stays finite, no inf/NaN).
TENOR_SENTINEL_NONE = 0.0

_DAYS_PER_YEAR = 365.0

# Default reinvestment-rate assumption (pct): the rate you assume you can roll
# the short tenor at once it matures. Used to penalise the short-end carry so a
# transiently high short rate does not always "win".
_DEFAULT_REINVESTMENT_RATE_PCT = 4.0

# Classification bands
CLASS_STEEP_NORMAL = "STEEP_NORMAL"
CLASS_NORMAL = "NORMAL"
CLASS_FLAT = "FLAT"
CLASS_SLIGHTLY_INVERTED = "SLIGHTLY_INVERTED"
CLASS_DEEPLY_INVERTED = "DEEPLY_INVERTED"

ALL_CLASSIFICATIONS = (
    CLASS_STEEP_NORMAL,
    CLASS_NORMAL,
    CLASS_FLAT,
    CLASS_SLIGHTLY_INVERTED,
    CLASS_DEEPLY_INVERTED,
)

# Flags
FLAG_INVERTED_CURVE = "INVERTED_CURVE"
FLAG_FLAT_CURVE = "FLAT_CURVE"
FLAG_STEEP_CURVE = "STEEP_CURVE"
FLAG_HIGH_TERM_PREMIUM = "HIGH_TERM_PREMIUM"
FLAG_NEGATIVE_TERM_PREMIUM = "NEGATIVE_TERM_PREMIUM"
FLAG_LONG_LOCK_NO_PICKUP = "LONG_LOCK_NO_PICKUP"
FLAG_DEEPLY_INVERTED = "DEEPLY_INVERTED"
FLAG_OPTIMAL_IS_SHORT = "OPTIMAL_IS_SHORT"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_INVERTED_CURVE,
    FLAG_FLAT_CURVE,
    FLAG_STEEP_CURVE,
    FLAG_HIGH_TERM_PREMIUM,
    FLAG_NEGATIVE_TERM_PREMIUM,
    FLAG_LONG_LOCK_NO_PICKUP,
    FLAG_DEEPLY_INVERTED,
    FLAG_OPTIMAL_IS_SHORT,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds (module constants), expressed on curve_slope_pct_per_year unless
# noted. Slope is term_spread normalised per extra year of tenor.
_SLOPE_STEEP_PCT_PER_YEAR = 2.0     # slope >= 2.0 pct/yr -> steep normal
_SLOPE_FLAT_BAND_PCT_PER_YEAR = 0.25  # |slope| < 0.25 -> flat
# Inversion magnitude (pct, long below short) bands:
_INVERSION_DEEP_PCT = 1.0          # short above long by >= 1.0 pct -> deeply inv
# Term premium flag thresholds (term_spread_pct):
_HIGH_TERM_PREMIUM_PCT = 3.0       # long pays >= 3 pct more than short
_LONG_LOCK_NO_PICKUP_PCT = 0.25    # long pays < 0.25 pct more than short


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


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* to the inclusive range [lo, hi]."""
    return max(lo, min(hi, value))


def _normalise_points(raw: Any) -> list:
    """
    Coerce a raw list of curve points into a clean, sorted list of dicts.

    Each accepted point is a dict with ``tenor_days`` and ``apr_pct`` (other
    shapes are dropped). Points with a non-positive tenor are dropped (a tenor
    must be a positive number of days). The result is sorted ascending by tenor.
    Duplicate tenors are kept (the sort is stable); callers treat the first as
    the short end and the last as the long end after sorting.
    """
    out: list = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        tenor = _safe_float(item.get("tenor_days"), -1.0)
        apr = _safe_float(item.get("apr_pct"), 0.0)
        if tenor <= _EPS:
            continue
        out.append({"tenor_days": tenor, "apr_pct": apr})
    out.sort(key=lambda p: p["tenor_days"])
    return out


# ---------------------------------------------------------------------------
# Sub-calculators (defensive division everywhere)
# ---------------------------------------------------------------------------

def _term_spread_pct(short_apr_pct: float, long_apr_pct: float) -> float:
    """Term spread (pct): long-end APR minus short-end APR (can be negative)."""
    return long_apr_pct - short_apr_pct


def _curve_slope_pct_per_year(
    short_apr_pct: float,
    long_apr_pct: float,
    short_tenor_days: float,
    long_tenor_days: float,
) -> float:
    """
    Slope of the curve, in pct of APR per *year* of additional tenor.

        slope = (long_apr - short_apr) / ((long_tenor - short_tenor) / 365)

    Defensive: when the two tenors coincide (zero horizontal distance) the slope
    is undefined; return 0.0 (a single point / degenerate curve has no slope).
    """
    span_days = long_tenor_days - short_tenor_days
    if abs(span_days) <= _EPS:
        return 0.0
    span_years = span_days / _DAYS_PER_YEAR
    if abs(span_years) <= _EPS:
        return 0.0
    return (long_apr_pct - short_apr_pct) / span_years


def _inversion_magnitude_pct(short_apr_pct: float, long_apr_pct: float) -> float:
    """
    How far the curve is inverted, in pct (short above long). 0.0 if normal.

        inversion = max(0, short_apr - long_apr)
    """
    return max(0.0, short_apr_pct - long_apr_pct)


def _reinvest_adjusted_carry_pct(
    apr_pct: float,
    tenor_days: float,
    longest_tenor_days: float,
    reinvestment_rate_pct: float,
) -> float:
    """
    Annualised carry of a tenor over the *longest* horizon, blending the tenor's
    own APR for its life with the reinvestment-rate assumption for the remaining
    time until the longest tenor matures.

    Rationale: a high short rate cannot simply be annualised to the long horizon
    — once the short tenor matures you must roll at an unknown future rate, here
    proxied by ``reinvestment_rate_pct``. Locking the long tenor avoids that roll
    risk. The blended carry is::

        own_years   = min(tenor, longest) / 365
        roll_years  = max(0, longest - tenor) / 365
        carry = (apr * own_years + reinvest * roll_years) / (own_years+roll_years)

    Defensive: a non-positive longest horizon returns the tenor's own APR.
    """
    longest = max(0.0, longest_tenor_days)
    own = min(max(0.0, tenor_days), longest)
    if longest <= _EPS:
        return apr_pct
    roll = max(0.0, longest - own)
    own_years = own / _DAYS_PER_YEAR
    roll_years = roll / _DAYS_PER_YEAR
    denom = own_years + roll_years
    if denom <= _EPS:
        return apr_pct
    return (apr_pct * own_years + reinvestment_rate_pct * roll_years) / denom


def _optimal_tenor(
    points: list,
    reinvestment_rate_pct: float,
) -> tuple:
    """
    Find the tenor with the best reinvestment-adjusted carry over the longest
    horizon on the curve.

    Returns ``(tenor_days, apr_pct, best_carry_pct)``. For an empty curve returns
    ``(TENOR_SENTINEL_NONE, 0.0, 0.0)``.
    """
    if not points:
        return (TENOR_SENTINEL_NONE, 0.0, 0.0)
    longest = points[-1]["tenor_days"]
    best = None
    best_carry = None
    for p in points:
        carry = _reinvest_adjusted_carry_pct(
            p["apr_pct"], p["tenor_days"], longest, reinvestment_rate_pct
        )
        if best_carry is None or carry > best_carry:
            best_carry = carry
            best = p
    return (best["tenor_days"], best["apr_pct"], best_carry)


def _pickup_vs_short_pct(
    optimal_carry_pct: float,
    short_carry_pct: float,
) -> float:
    """Pickup of the optimal tenor's carry over the short tenor's carry (pct)."""
    return optimal_carry_pct - short_carry_pct


def _term_structure_score(
    curve_slope_pct_per_year: float,
    term_spread_pct: float,
    is_inverted: bool,
    inversion_magnitude_pct: float,
    pickup_vs_short_pct: float,
    has_data: bool,
) -> float:
    """
    0-100: higher = a healthy, normal, upward-sloping curve that pays a real
    premium for locking.

    Blends three drivers:
    - slope component (0-50): a flat/inverted curve contributes 0, a slope at or
      above the steep threshold contributes the full 50; linear in between.
    - non-inversion component (0-30): full 30 when not inverted; decays toward 0
      as the inversion deepens (0 at/below the deep-inversion threshold).
    - pickup component (0-20): full 20 when the optimal tenor pays a healthy
      pickup over the short end; 0 when there is no pickup.

    Returns 0.0 when there is no usable data.
    """
    if not has_data:
        return 0.0

    # Slope component (0..50): clamp slope to [0, steep] then scale.
    slope_capped = _clamp(curve_slope_pct_per_year, 0.0, _SLOPE_STEEP_PCT_PER_YEAR)
    slope_component = (slope_capped / _SLOPE_STEEP_PCT_PER_YEAR) * 50.0

    # Non-inversion component (0..30).
    if not is_inverted:
        inv_component = 30.0
    else:
        inv_ratio = _clamp(inversion_magnitude_pct / _INVERSION_DEEP_PCT, 0.0, 1.0)
        inv_component = (1.0 - inv_ratio) * 30.0

    # Pickup component (0..20): scale pickup against the high-term-premium mark.
    pickup_capped = _clamp(pickup_vs_short_pct, 0.0, _HIGH_TERM_PREMIUM_PCT)
    pickup_component = (pickup_capped / _HIGH_TERM_PREMIUM_PCT) * 20.0

    return _clamp(slope_component + inv_component + pickup_component)


def _classify(
    curve_slope_pct_per_year: float,
    is_inverted: bool,
    inversion_magnitude_pct: float,
    has_data: bool,
) -> str:
    """
    Assign an advisory steepness classification band.

      inverted, magnitude >= deep      -> DEEPLY_INVERTED
      inverted, magnitude < deep        -> SLIGHTLY_INVERTED
      |slope| < flat band               -> FLAT
      slope >= steep                    -> STEEP_NORMAL
      otherwise (normal positive slope) -> NORMAL

    No data falls back to FLAT (cannot demonstrate any shape).
    """
    if not has_data:
        return CLASS_FLAT

    if is_inverted:
        if inversion_magnitude_pct >= _INVERSION_DEEP_PCT:
            return CLASS_DEEPLY_INVERTED
        return CLASS_SLIGHTLY_INVERTED

    if abs(curve_slope_pct_per_year) < _SLOPE_FLAT_BAND_PCT_PER_YEAR:
        return CLASS_FLAT
    if curve_slope_pct_per_year >= _SLOPE_STEEP_PCT_PER_YEAR:
        return CLASS_STEEP_NORMAL
    return CLASS_NORMAL


def _grade(term_structure_score: float) -> str:
    """Map term_structure_score (higher = better) to an A-F letter grade."""
    s = term_structure_score
    if s >= 90.0:
        return "A"
    if s >= 70.0:
        return "B"
    if s >= 50.0:
        return "C"
    if s >= 30.0:
        return "D"
    return "F"


def _flags(
    is_inverted: bool,
    inversion_magnitude_pct: float,
    curve_slope_pct_per_year: float,
    term_spread_pct: float,
    pickup_vs_short_pct: float,
    optimal_tenor_days: float,
    short_tenor_days: float,
    classification: str,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if is_inverted:
        flags.append(FLAG_INVERTED_CURVE)
        if inversion_magnitude_pct >= _INVERSION_DEEP_PCT:
            flags.append(FLAG_DEEPLY_INVERTED)
        flags.append(FLAG_NEGATIVE_TERM_PREMIUM)
    else:
        if abs(curve_slope_pct_per_year) < _SLOPE_FLAT_BAND_PCT_PER_YEAR:
            flags.append(FLAG_FLAT_CURVE)
        if curve_slope_pct_per_year >= _SLOPE_STEEP_PCT_PER_YEAR:
            flags.append(FLAG_STEEP_CURVE)

    if term_spread_pct >= _HIGH_TERM_PREMIUM_PCT:
        flags.append(FLAG_HIGH_TERM_PREMIUM)

    # Long lock with no pickup: the long end barely pays more than the short
    # end (but not inverted; inverted is its own, stronger signal).
    if (not is_inverted) and term_spread_pct < _LONG_LOCK_NO_PICKUP_PCT:
        flags.append(FLAG_LONG_LOCK_NO_PICKUP)

    # The reinvest-adjusted optimum is the short tenor (locking long is not
    # worth it once roll risk is priced in).
    if (optimal_tenor_days > _EPS
            and abs(optimal_tenor_days - short_tenor_days) <= _EPS
            and short_tenor_days > _EPS):
        flags.append(FLAG_OPTIMAL_IS_SHORT)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    short_apr_pct: float,
    long_apr_pct: float,
    term_spread_pct: float,
    curve_slope_pct_per_year: float,
    inversion_magnitude_pct: float,
    optimal_tenor_days: float,
    optimal_tenor_apr_pct: float,
    pickup_vs_short_pct: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: fewer than two usable curve points (each needs a "
            "positive tenor_days and an apr_pct) or data marked unreliable. "
            "Cannot assess the yield term structure for this market."
        )
        return recs

    if classification == CLASS_DEEPLY_INVERTED:
        recs.append(
            f"Deeply inverted curve: the short tenor pays ~{short_apr_pct:.2f}% "
            f"vs ~{long_apr_pct:.2f}% at the long end (inverted by "
            f"~{inversion_magnitude_pct:.2f}%). Do not lock long; stay short and "
            "roll, or wait for the curve to normalise."
        )
    elif classification == CLASS_SLIGHTLY_INVERTED:
        recs.append(
            f"Slightly inverted curve: the short end (~{short_apr_pct:.2f}%) edges "
            f"out the long end (~{long_apr_pct:.2f}%). Locking long gives up "
            "liquidity for a lower rate; favour the short tenor."
        )
    elif classification == CLASS_FLAT:
        recs.append(
            f"Flat curve: the long end pays only ~{term_spread_pct:.2f}% more than "
            "the short end. There is little term premium for sacrificing "
            "liquidity; staying short keeps optionality at almost no cost."
        )
    elif classification == CLASS_STEEP_NORMAL:
        recs.append(
            f"Steep normal curve: a slope of ~{curve_slope_pct_per_year:.2f}%/yr "
            f"and a ~{term_spread_pct:.2f}% term spread pay a real premium for "
            "locking longer. Locking the longer tenor is well compensated."
        )
    else:  # NORMAL
        recs.append(
            f"Normal curve: an upward slope of ~{curve_slope_pct_per_year:.2f}%/yr "
            f"pays a modest ~{term_spread_pct:.2f}% premium for locking longer."
        )

    if optimal_tenor_days > _EPS:
        recs.append(
            f"Reinvest-adjusted optimum: the ~{optimal_tenor_days:.0f}-day tenor "
            f"(~{optimal_tenor_apr_pct:.2f}% APR) gives the best carry once a "
            "reinvestment-rate assumption is priced onto the short end "
            f"(pickup vs short ~{pickup_vs_short_pct:.2f}%)."
        )

    if FLAG_OPTIMAL_IS_SHORT in flags:
        recs.append(
            "Optimal is the short tenor: once roll risk is priced in, locking "
            "long does not beat staying short. Keep capital liquid and roll."
        )

    if FLAG_LONG_LOCK_NO_PICKUP in flags:
        recs.append(
            "Long lock, no pickup: the long tenor barely out-yields the short "
            "tenor. Do not give up liquidity for a negligible premium."
        )

    if FLAG_HIGH_TERM_PREMIUM in flags:
        recs.append(
            f"High term premium: the curve pays ~{term_spread_pct:.2f}% extra at "
            "the long end. Confirm the long-tenor source is durable before "
            "locking into it."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    token: dict | None = None,
    config: dict | None = None,
    *,
    points: list | None = None,
    reinvestment_rate_assumption_pct: float | None = None,
    data_quality: Any = None,
    name: str | None = None,
) -> dict:
    """
    Analyse the yield term structure of a single market / curve.

    Inputs may be supplied as a ``token`` dict and/or via keyword arguments
    (keywords take precedence over dict values).

    Recognised keys / keywords:
    - name                              : str
    - points                            : list[{tenor_days, apr_pct}]
                                          (minimum 2 usable points required)
    - reinvestment_rate_assumption_pct  : float (rate assumed for rolling the
                                          short end, default 4)
    - data_quality                      : truthy/"ok" => trusted; falsy/"poor"

    config : dict, optional
        - log_path : str  (override default log path)

    Returns
    -------
    dict
        Full analysis result. Never raises to the caller.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    t = token if isinstance(token, dict) else {}

    name_val = name if name is not None else str(t.get("name", "UNKNOWN"))

    raw_points = points if points is not None else t.get("points")
    norm_points = _normalise_points(raw_points)

    reinvest = reinvestment_rate_assumption_pct
    if reinvest is None:
        reinvest = t.get("reinvestment_rate_assumption_pct",
                         _DEFAULT_REINVESTMENT_RATE_PCT)
    reinvest = _safe_float(reinvest, _DEFAULT_REINVESTMENT_RATE_PCT)

    dq_raw = data_quality if data_quality is not None else t.get("data_quality", "ok")
    if isinstance(dq_raw, str):
        data_quality_ok = dq_raw.strip().lower() not in ("poor", "bad", "low", "")
    else:
        data_quality_ok = bool(dq_raw)

    # Data sufficiency: need at least two usable curve points and the
    # data-quality flag must not mark the inputs as unreliable.
    has_signal = len(norm_points) >= 2
    has_data = has_signal and data_quality_ok

    if has_signal:
        short = norm_points[0]
        long_ = norm_points[-1]
        short_tenor = short["tenor_days"]
        long_tenor = long_["tenor_days"]
        short_apr = short["apr_pct"]
        long_apr = long_["apr_pct"]
    else:
        short_tenor = TENOR_SENTINEL_NONE
        long_tenor = TENOR_SENTINEL_NONE
        short_apr = 0.0
        long_apr = 0.0

    term_spread = _term_spread_pct(short_apr, long_apr)
    slope = _curve_slope_pct_per_year(short_apr, long_apr, short_tenor, long_tenor)
    inversion = _inversion_magnitude_pct(short_apr, long_apr)
    is_inverted = inversion > _EPS

    opt_tenor, opt_apr, opt_carry = _optimal_tenor(norm_points, reinvest)
    if has_signal:
        short_carry = _reinvest_adjusted_carry_pct(
            short_apr, short_tenor, long_tenor, reinvest
        )
    else:
        short_carry = 0.0
    pickup = _pickup_vs_short_pct(opt_carry, short_carry)

    classification = _classify(slope, is_inverted, inversion, has_data)
    score = _term_structure_score(
        slope, term_spread, is_inverted, inversion, pickup, has_data
    )
    grade = _grade(score)
    flags = _flags(
        is_inverted,
        inversion,
        slope,
        term_spread,
        pickup,
        opt_tenor,
        short_tenor,
        classification,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        short_apr,
        long_apr,
        term_spread,
        slope,
        inversion,
        opt_tenor,
        opt_apr,
        pickup,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "points": norm_points,
        "point_count": len(norm_points),
        "reinvestment_rate_assumption_pct": reinvest,
        "data_quality_ok": data_quality_ok,
        "short_tenor_days": short_tenor,
        "long_tenor_days": long_tenor,
        "short_apr_pct": short_apr,
        "long_apr_pct": long_apr,
        "term_spread_pct": term_spread,
        "curve_slope_pct_per_year": slope,
        "is_inverted": is_inverted,
        "inversion_magnitude_pct": inversion,
        "optimal_tenor_days": opt_tenor,
        "optimal_tenor_apr_pct": opt_apr,
        "optimal_tenor_carry_pct": opt_carry,
        "pickup_vs_short_pct": pickup,
        "term_structure_score": score,
        "steepness_classification": classification,
        "classification": classification,
        "grade": grade,
        "flags": flags,
        "recommendations": recs,
        "timestamp": time.time(),
    }

    try:
        _atomic_log(log_path, result)
    except Exception:
        pass  # advisory: never crash caller

    return result


# ---------------------------------------------------------------------------
# Public batch analyse function
# ---------------------------------------------------------------------------

def analyze_portfolio(curves: list, config: dict | None = None) -> dict:
    """
    Analyse the term structure across a batch of markets / curves and summarise.

    Returns
    -------
    dict
        - total_curves                 : int
        - results                      : list[dict]  (per-curve analysis)
        - most_inverted_market         : str | None  (largest inversion magnitude)
        - least_inverted_market        : str | None  (smallest inversion / steepest)
        - avg_term_structure_score     : float
        - inverted_count               : int
        - timestamp                    : float
    """
    if not isinstance(curves, list):
        curves = []

    results = [
        analyze(c if isinstance(c, dict) else {}, config=config)
        for c in curves
    ]
    total = len(results)

    if total == 0:
        return {
            "total_curves": 0,
            "results": [],
            "most_inverted_market": None,
            "least_inverted_market": None,
            "avg_term_structure_score": 0.0,
            "inverted_count": 0,
            "timestamp": time.time(),
        }

    # Most inverted = largest inversion magnitude; least inverted = smallest.
    most = max(results, key=lambda r: r["inversion_magnitude_pct"])
    least = min(results, key=lambda r: r["inversion_magnitude_pct"])
    avg = sum(r["term_structure_score"] for r in results) / total
    inverted = sum(1 for r in results if r["is_inverted"])

    return {
        "total_curves": total,
        "results": results,
        "most_inverted_market": most["name"],
        "least_inverted_market": least["name"],
        "avg_term_structure_score": avg,
        "inverted_count": inverted,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolYieldTermStructureAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = DeFiProtocolYieldTermStructureAnalyzer()
    >>> r = a.analyze({"name": "Pendle-PT", "points": [
    ...     {"tenor_days": 30, "apr_pct": 5.0},
    ...     {"tenor_days": 180, "apr_pct": 8.0},
    ...     {"tenor_days": 365, "apr_pct": 10.0}]})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, token: dict | None = None, **kwargs: Any) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(token, config=self._config, **kwargs)

    def analyze_portfolio(self, curves: list) -> dict:
        """Delegate to module-level ``analyze_portfolio``."""
        return analyze_portfolio(curves, config=self._config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo_curves = [
        {
            "name": "Pendle-PT (normal, steep)",
            "points": [
                {"tenor_days": 30, "apr_pct": 5.0},
                {"tenor_days": 180, "apr_pct": 8.0},
                {"tenor_days": 365, "apr_pct": 11.0},
            ],
            "reinvestment_rate_assumption_pct": 4.0,
        },
        {
            "name": "Lock-vault (inverted)",
            "points": [
                {"tenor_days": 30, "apr_pct": 12.0},
                {"tenor_days": 180, "apr_pct": 9.0},
                {"tenor_days": 365, "apr_pct": 7.0},
            ],
            "reinvestment_rate_assumption_pct": 4.0,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_curves[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_curves)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
