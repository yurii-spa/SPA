"""
MP-1147  DeFiProtocolFixedVsFloatingYieldDecisionAnalyzer
--------------------------------------------------------
Should you LOCK a fixed yield now (e.g. a Pendle PT, a fixed-rate vault) or STAY
FLOATING (a variable APR)?

A fixed rate trades certainty for the chance that floating averages higher over
the horizon; staying floating keeps the upside but bears rate risk. The right
call depends on the spread between the lockable fixed rate and the floating rate
today, your forward expectation for the average floating rate, and how volatile
that floating rate is.

Given the lockable fixed APR, the current floating APR, a forward expectation for
the floating APR over the horizon, the floating APR's annualised volatility, and
a horizon in days, this module quantifies the fixed-vs-floating spread, the
breakeven average floating rate that makes you indifferent, the expected total
return of each leg over the horizon, the advantage of locking fixed, the
probability that floating beats fixed (modelling the average floating rate as a
Normal), and a single 0-100 decision score where higher means a stronger case to
LOCK FIXED.

Genuine gap: an existing module optimizes borrow-rate MODE (stable vs variable
on the DEBT side) and another values PT/YT tokenization mechanics, but none make
the EARN-side lock-fixed-vs-stay-floating decision with a breakeven average
floating rate and a probability-floating-beats-fixed estimate.

The module returns:
- name / fixed_apr_pct / current_floating_apr_pct (input echoes)
- expected_floating_apr_pct / floating_apr_volatility_pct / horizon_days
- fixed_minus_current_floating_spread_pct - fixed vs floating today
- fixed_vs_expected_spread_pct            - fixed vs expected floating
- breakeven_avg_floating_apr_pct          - indifference average floating rate
- fixed_total_return_pct                  - fixed leg return over horizon
- expected_floating_total_return_pct      - expected floating return over horizon
- advantage_of_fixed_pct                  - fixed minus expected floating return
- probability_floating_beats_fixed_pct    - P(floating avg > fixed), 0..100
- decision_score                          - 0-100, higher = lock fixed
- classification                          - STRONG_LOCK .. STRONG_FLOAT
- recommendation                          - LOCK_FIXED / STAY_FLOATING / NEUTRAL
- grade                                   - A-F letter grade
- flags / recommendations                 - advisory verdicts

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "fixed_vs_floating_yield_decision_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Defaults.
_DEFAULT_FLOATING_VOLATILITY_PCT = 0.0
_DEFAULT_HORIZON_DAYS = 365.0
_DAYS_PER_YEAR = 365.0

# Classification bands on decision_score
CLASS_STRONG_LOCK = "STRONG_LOCK"
CLASS_LEAN_LOCK = "LEAN_LOCK"
CLASS_NEUTRAL = "NEUTRAL"
CLASS_LEAN_FLOAT = "LEAN_FLOAT"
CLASS_STRONG_FLOAT = "STRONG_FLOAT"

ALL_CLASSIFICATIONS = (
    CLASS_STRONG_LOCK,
    CLASS_LEAN_LOCK,
    CLASS_NEUTRAL,
    CLASS_LEAN_FLOAT,
    CLASS_STRONG_FLOAT,
)

# Recommendation values
REC_LOCK_FIXED = "LOCK_FIXED"
REC_STAY_FLOATING = "STAY_FLOATING"
REC_NEUTRAL = "NEUTRAL"

ALL_RECOMMENDATIONS = (
    REC_LOCK_FIXED,
    REC_STAY_FLOATING,
    REC_NEUTRAL,
)

# Flags
FLAG_LOCK_FIXED = "LOCK_FIXED"
FLAG_STAY_FLOATING = "STAY_FLOATING"
FLAG_FIXED_BELOW_CURRENT_FLOATING = "FIXED_BELOW_CURRENT_FLOATING"
FLAG_HIGH_FLOATING_VOLATILITY = "HIGH_FLOATING_VOLATILITY"
FLAG_FLOATING_LIKELY_WINS = "FLOATING_LIKELY_WINS"
FLAG_FIXED_LIKELY_WINS = "FIXED_LIKELY_WINS"
FLAG_NEAR_INDIFFERENT = "NEAR_INDIFFERENT"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_LOCK_FIXED,
    FLAG_STAY_FLOATING,
    FLAG_FIXED_BELOW_CURRENT_FLOATING,
    FLAG_HIGH_FLOATING_VOLATILITY,
    FLAG_FLOATING_LIKELY_WINS,
    FLAG_FIXED_LIKELY_WINS,
    FLAG_NEAR_INDIFFERENT,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds (module constants)
_STRONG_LOCK_SCORE = 75.0
_LEAN_LOCK_SCORE = 58.0
_NEUTRAL_SCORE = 42.0
_LEAN_FLOAT_SCORE = 25.0
_HIGH_FLOATING_VOLATILITY_PCT = 5.0   # >= 5pp annualised stdev is high vol
_FLOATING_LIKELY_WINS_PCT = 60.0      # P(floating>fixed) >= 60 -> floating wins
_FIXED_LIKELY_WINS_PCT = 40.0         # P(floating>fixed) <= 40 -> fixed wins
_NEAR_INDIFFERENT_PCT = 0.25          # |advantage_of_fixed| < 0.25pp ~ indiff
_ADVANTAGE_SATURATION_PCT = 4.0       # advantage saturating point for score


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
    atomic_save(data, str(abs_path))
def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* to the inclusive range [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Sub-calculators (defensive division everywhere)
# ---------------------------------------------------------------------------

def _fixed_minus_current_floating_spread_pct(
    fixed_apr_pct: float,
    current_floating_apr_pct: float,
) -> float:
    """Fixed rate minus the floating rate today (can be < 0)."""
    return fixed_apr_pct - current_floating_apr_pct


def _fixed_vs_expected_spread_pct(
    fixed_apr_pct: float,
    expected_floating_apr_pct: float,
) -> float:
    """Fixed rate minus the expected average floating rate (can be < 0)."""
    return fixed_apr_pct - expected_floating_apr_pct


def _breakeven_avg_floating_apr_pct(fixed_apr_pct: float) -> float:
    """
    The average floating rate over the horizon that makes you indifferent.

    Indifference is when the floating leg's average APR equals the fixed APR, so
    the breakeven average floating rate is simply the fixed APR itself.
    """
    return fixed_apr_pct


def _total_return_pct(apr_pct: float, horizon_days: float) -> float:
    """
    Simple (non-compounded) total return over the horizon, in pct.

        total = apr * (horizon_days / 365)

    Defensive: horizon_days is floored at 0.
    """
    days = max(0.0, horizon_days)
    return apr_pct * (days / _DAYS_PER_YEAR)


def _advantage_of_fixed_pct(
    fixed_total_return_pct: float,
    expected_floating_total_return_pct: float,
) -> float:
    """Fixed total return minus expected floating total return (can be < 0)."""
    return fixed_total_return_pct - expected_floating_total_return_pct


def _phi(x: float) -> float:
    """Standard-normal CDF via the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _probability_floating_beats_fixed_pct(
    fixed_apr_pct: float,
    expected_floating_apr_pct: float,
    floating_apr_volatility_pct: float,
) -> float:
    """
    P(average floating over horizon > fixed APR), in pct (0..100).

    Models the average floating rate as Normal(mean=expected_floating_apr_pct,
    sd=floating_apr_volatility_pct):

        P(floating_avg > fixed) = 1 - Phi((fixed - expected) / sd)

    Defensive: when the volatility is ~0 the outcome is deterministic — 100.0 if
    expected > fixed, 0.0 if expected < fixed, 50.0 if equal.
    """
    sd = max(0.0, floating_apr_volatility_pct)
    if sd <= _EPS:
        if expected_floating_apr_pct > fixed_apr_pct + _EPS:
            return 100.0
        if expected_floating_apr_pct < fixed_apr_pct - _EPS:
            return 0.0
        return 50.0
    z = (fixed_apr_pct - expected_floating_apr_pct) / sd
    return _clamp((1.0 - _phi(z)) * 100.0, 0.0, 100.0)


def _decision_score(
    advantage_of_fixed_pct: float,
    probability_floating_beats_fixed_pct: float,
    fixed_minus_current_floating_spread_pct: float,
    has_data: bool,
) -> float:
    """
    0-100: HIGHER = a stronger case to LOCK FIXED; lower = stay floating.

    Blends three drivers:
    - advantage-of-fixed (0-50): the fixed leg's expected total-return edge,
      mapped through a saturating curve centred at neutral (advantage 0 -> 25,
      saturating at +/- _ADVANTAGE_SATURATION_PCT to 50/0).
    - low probability floating wins (0-35): (100 - P(floating beats fixed)) so a
      high chance floating wins drags the score down.
    - positive fixed-minus-current spread (0-15): a small bonus when the fixed
      rate is at or above the floating rate today.

    Returns 0.0 when there is no usable data.
    """
    if not has_data:
        return 0.0

    # Advantage component: centred at 25, saturating at +/- saturation point.
    adv_ratio = _clamp(
        advantage_of_fixed_pct / _ADVANTAGE_SATURATION_PCT, -1.0, 1.0)
    adv_component = 25.0 + adv_ratio * 25.0  # 0..50

    # Low-probability-floating-wins component (0..35).
    prob_component = (100.0 - _clamp(
        probability_floating_beats_fixed_pct, 0.0, 100.0)) / 100.0 * 35.0

    # Positive-spread-today bonus (0..15), saturating at +2pp spread.
    if fixed_minus_current_floating_spread_pct <= 0.0:
        spread_component = 0.0
    else:
        spread_ratio = _clamp(
            fixed_minus_current_floating_spread_pct / 2.0, 0.0, 1.0)
        spread_component = spread_ratio * 15.0

    return _clamp(adv_component + prob_component + spread_component)


def _classify(decision_score: float, has_data: bool) -> str:
    """
    Assign an advisory classification band on the decision score.

      >= 75  -> STRONG_LOCK
      >= 58  -> LEAN_LOCK
      >= 42  -> NEUTRAL
      >= 25  -> LEAN_FLOAT
      < 25   -> STRONG_FLOAT

    No data falls back to NEUTRAL (no basis to prefer either leg).
    """
    if not has_data:
        return CLASS_NEUTRAL

    s = decision_score
    if s >= _STRONG_LOCK_SCORE:
        return CLASS_STRONG_LOCK
    if s >= _LEAN_LOCK_SCORE:
        return CLASS_LEAN_LOCK
    if s >= _NEUTRAL_SCORE:
        return CLASS_NEUTRAL
    if s >= _LEAN_FLOAT_SCORE:
        return CLASS_LEAN_FLOAT
    return CLASS_STRONG_FLOAT


def _recommendation(decision_score: float, has_data: bool) -> str:
    """
    Discrete lock-vs-float verdict string.

      score >= 58 -> LOCK_FIXED
      score <= 42 -> STAY_FLOATING
      otherwise   -> NEUTRAL

    No data -> NEUTRAL.
    """
    if not has_data:
        return REC_NEUTRAL
    if decision_score >= _LEAN_LOCK_SCORE:
        return REC_LOCK_FIXED
    if decision_score <= _NEUTRAL_SCORE:
        return REC_STAY_FLOATING
    return REC_NEUTRAL


def _grade(decision_score: float) -> str:
    """
    Map decision_score to an A-F letter grade by *decisiveness* — distance from
    the neutral midpoint (50). A clear lock-or-float call grades high; a
    near-coin-flip grades low.
    """
    decisiveness = abs(decision_score - 50.0) * 2.0  # 0..100
    s = decisiveness
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
    recommendation: str,
    fixed_minus_current_floating_spread_pct: float,
    floating_apr_volatility_pct: float,
    probability_floating_beats_fixed_pct: float,
    advantage_of_fixed_pct: float,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if recommendation == REC_LOCK_FIXED:
        flags.append(FLAG_LOCK_FIXED)
    elif recommendation == REC_STAY_FLOATING:
        flags.append(FLAG_STAY_FLOATING)

    if fixed_minus_current_floating_spread_pct < 0.0:
        flags.append(FLAG_FIXED_BELOW_CURRENT_FLOATING)

    if floating_apr_volatility_pct >= _HIGH_FLOATING_VOLATILITY_PCT:
        flags.append(FLAG_HIGH_FLOATING_VOLATILITY)

    if probability_floating_beats_fixed_pct >= _FLOATING_LIKELY_WINS_PCT:
        flags.append(FLAG_FLOATING_LIKELY_WINS)

    if probability_floating_beats_fixed_pct <= _FIXED_LIKELY_WINS_PCT:
        flags.append(FLAG_FIXED_LIKELY_WINS)

    if abs(advantage_of_fixed_pct) < _NEAR_INDIFFERENT_PCT:
        flags.append(FLAG_NEAR_INDIFFERENT)

    return flags


def _recommendations(
    classification: str,
    recommendation: str,
    flags: list,
    fixed_apr_pct: float,
    expected_floating_apr_pct: float,
    advantage_of_fixed_pct: float,
    probability_floating_beats_fixed_pct: float,
    breakeven_avg_floating_apr_pct: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: no fixed or floating APR signal, or data marked "
            "unreliable. Cannot make a lock-vs-float recommendation."
        )
        return recs

    if recommendation == REC_LOCK_FIXED:
        recs.append(
            f"Lock fixed: at ~{fixed_apr_pct:.2f}% the fixed leg has a "
            f"~{advantage_of_fixed_pct:.2f}pp expected total-return edge over "
            f"floating, and floating only wins with ~"
            f"{probability_floating_beats_fixed_pct:.0f}% probability. Locking "
            "removes rate risk at a favourable level."
        )
    elif recommendation == REC_STAY_FLOATING:
        recs.append(
            f"Stay floating: the expected average floating rate is above the "
            f"~{fixed_apr_pct:.2f}% fixed rate (floating wins with ~"
            f"{probability_floating_beats_fixed_pct:.0f}% probability). Keep the "
            "upside rather than lock in below your forward expectation."
        )
    else:
        recs.append(
            f"Neutral: fixed (~{fixed_apr_pct:.2f}%) and the expected average "
            f"floating (~{expected_floating_apr_pct:.2f}%) are close; the "
            f"breakeven average floating rate is ~{breakeven_avg_floating_apr_pct:.2f}%. "
            "Decide on your own rate view and risk tolerance."
        )

    if FLAG_FIXED_BELOW_CURRENT_FLOATING in flags:
        recs.append(
            "Fixed below current floating: locking now crystallises a rate "
            "below what floating pays today. Only lock if you expect floating "
            "to fall meaningfully over the horizon."
        )

    if FLAG_HIGH_FLOATING_VOLATILITY in flags:
        recs.append(
            "High floating volatility: the floating rate is uncertain, so the "
            "probability estimate is wide. Locking fixed has extra value as "
            "insurance against that volatility."
        )

    if FLAG_FLOATING_LIKELY_WINS in flags:
        recs.append(
            f"Floating likely wins: ~{probability_floating_beats_fixed_pct:.0f}% "
            "chance the average floating rate exceeds the fixed rate over the "
            "horizon."
        )
    elif FLAG_FIXED_LIKELY_WINS in flags:
        recs.append(
            f"Fixed likely wins: only ~{probability_floating_beats_fixed_pct:.0f}% "
            "chance floating beats fixed; the fixed rate is the safer expected "
            "outcome."
        )

    if FLAG_NEAR_INDIFFERENT in flags:
        recs.append(
            "Near-indifferent: the fixed and expected-floating returns are "
            "within a fraction of a point. Either leg is defensible; prefer "
            "fixed if you value certainty."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    token: dict | None = None,
    config: dict | None = None,
    *,
    fixed_apr_pct: float | None = None,
    current_floating_apr_pct: float | None = None,
    expected_floating_apr_pct: float | None = None,
    floating_apr_volatility_pct: float | None = None,
    horizon_days: float | None = None,
    data_quality: Any = None,
    name: str | None = None,
) -> dict:
    """
    Analyse the lock-fixed-vs-stay-floating decision for a single position.

    Inputs may be supplied as a ``token`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    Recognised keys / keywords (all with safe defaults):
    - name                        : str
    - fixed_apr_pct               : float (the fixed rate you can lock now)
    - current_floating_apr_pct    : float (floating APR today)
    - expected_floating_apr_pct   : float (forward avg floating expectation;
                                    defaults to the resolved current floating)
    - floating_apr_volatility_pct : float (annualised stdev, default 0)
    - horizon_days                : float (default 365)
    - data_quality                : truthy/"ok" => trusted; falsy/"poor" => not

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

    def _pick(kw: Any, key: str, default: float) -> float:
        if kw is not None:
            return _safe_float(kw, default)
        return _safe_float(t.get(key, default), default)

    name_val = name if name is not None else str(t.get("name", "UNKNOWN"))

    fixed = _pick(fixed_apr_pct, "fixed_apr_pct", 0.0)
    current_floating = _pick(current_floating_apr_pct, "current_floating_apr_pct", 0.0)

    # Expected floating falls back to the resolved current floating when neither
    # the kwarg nor the token key provides it.
    if expected_floating_apr_pct is not None:
        expected_floating = _safe_float(expected_floating_apr_pct, current_floating)
    elif "expected_floating_apr_pct" in t:
        expected_floating = _safe_float(
            t.get("expected_floating_apr_pct"), current_floating)
    else:
        expected_floating = current_floating

    volatility = max(0.0, _pick(
        floating_apr_volatility_pct, "floating_apr_volatility_pct",
        _DEFAULT_FLOATING_VOLATILITY_PCT))
    horizon = max(0.0, _pick(horizon_days, "horizon_days", _DEFAULT_HORIZON_DAYS))

    dq_raw = data_quality if data_quality is not None else t.get("data_quality", "ok")
    if isinstance(dq_raw, str):
        data_quality_ok = dq_raw.strip().lower() not in ("poor", "bad", "low", "")
    else:
        data_quality_ok = bool(dq_raw)

    # Data sufficiency: need a fixed or current-floating APR signal and the
    # data-quality flag must not mark the inputs as unreliable.
    has_signal = (abs(fixed) > _EPS or abs(current_floating) > _EPS)
    has_data = has_signal and data_quality_ok

    spread_current = _fixed_minus_current_floating_spread_pct(fixed, current_floating)
    spread_expected = _fixed_vs_expected_spread_pct(fixed, expected_floating)
    breakeven = _breakeven_avg_floating_apr_pct(fixed)
    fixed_total = _total_return_pct(fixed, horizon)
    floating_total = _total_return_pct(expected_floating, horizon)
    advantage = _advantage_of_fixed_pct(fixed_total, floating_total)
    prob_floating = _probability_floating_beats_fixed_pct(
        fixed, expected_floating, volatility)
    score = _decision_score(advantage, prob_floating, spread_current, has_data)
    classification = _classify(score, has_data)
    recommendation = _recommendation(score, has_data)
    grade = _grade(score)
    flags = _flags(
        recommendation,
        spread_current,
        volatility,
        prob_floating,
        advantage,
        has_data,
    )
    recs = _recommendations(
        classification,
        recommendation,
        flags,
        fixed,
        expected_floating,
        advantage,
        prob_floating,
        breakeven,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "fixed_apr_pct": fixed,
        "current_floating_apr_pct": current_floating,
        "expected_floating_apr_pct": expected_floating,
        "floating_apr_volatility_pct": volatility,
        "horizon_days": horizon,
        "data_quality_ok": data_quality_ok,
        "fixed_minus_current_floating_spread_pct": spread_current,
        "fixed_vs_expected_spread_pct": spread_expected,
        "breakeven_avg_floating_apr_pct": breakeven,
        "fixed_total_return_pct": fixed_total,
        "expected_floating_total_return_pct": floating_total,
        "advantage_of_fixed_pct": advantage,
        "probability_floating_beats_fixed_pct": prob_floating,
        "decision_score": score,
        "classification": classification,
        "recommendation": recommendation,
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

def analyze_portfolio(positions: list, config: dict | None = None) -> dict:
    """
    Analyse the lock-vs-float decision across a batch of positions.

    Returns
    -------
    dict
        - total_positions             : int
        - results                     : list[dict]  (per-position analysis)
        - most_lock_worthy_position   : str | None  (highest decision score)
        - most_float_worthy_position  : str | None  (lowest decision score)
        - avg_decision_score          : float
        - lock_fixed_count            : int  (recommendation == LOCK_FIXED)
        - timestamp                   : float
    """
    if not isinstance(positions, list):
        positions = []

    results = [
        analyze(p if isinstance(p, dict) else {}, config=config)
        for p in positions
    ]
    total = len(results)

    if total == 0:
        return {
            "total_positions": 0,
            "results": [],
            "most_lock_worthy_position": None,
            "most_float_worthy_position": None,
            "avg_decision_score": 0.0,
            "lock_fixed_count": 0,
            "timestamp": time.time(),
        }

    most_lock = max(results, key=lambda r: r["decision_score"])
    most_float = min(results, key=lambda r: r["decision_score"])
    avg = sum(r["decision_score"] for r in results) / total
    lock_count = sum(1 for r in results if r["recommendation"] == REC_LOCK_FIXED)

    return {
        "total_positions": total,
        "results": results,
        "most_lock_worthy_position": most_lock["name"],
        "most_float_worthy_position": most_float["name"],
        "avg_decision_score": avg,
        "lock_fixed_count": lock_count,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolFixedVsFloatingYieldDecisionAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = DeFiProtocolFixedVsFloatingYieldDecisionAnalyzer()
    >>> r = a.analyze({"name": "PT-stETH", "fixed_apr_pct": 6.0,
    ...                "current_floating_apr_pct": 4.5,
    ...                "expected_floating_apr_pct": 4.0,
    ...                "floating_apr_volatility_pct": 2.0})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, token: dict | None = None, **kwargs: Any) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(token, config=self._config, **kwargs)

    def analyze_portfolio(self, positions: list) -> dict:
        """Delegate to module-level ``analyze_portfolio``."""
        return analyze_portfolio(positions, config=self._config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo_positions = [
        {
            "name": "PT-stETH (lock-worthy)",
            "fixed_apr_pct": 6.0,
            "current_floating_apr_pct": 4.5,
            "expected_floating_apr_pct": 4.0,
            "floating_apr_volatility_pct": 2.0,
            "horizon_days": 180.0,
        },
        {
            "name": "Variable vault (float-worthy)",
            "fixed_apr_pct": 4.0,
            "current_floating_apr_pct": 6.0,
            "expected_floating_apr_pct": 7.0,
            "floating_apr_volatility_pct": 3.0,
            "horizon_days": 365.0,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_positions[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_positions)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
