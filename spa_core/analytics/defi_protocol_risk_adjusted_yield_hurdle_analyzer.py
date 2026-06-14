"""
MP-1146  DeFiProtocolRiskAdjustedYieldHurdleAnalyzer
---------------------------------------------------
Does an offered DeFi APR clear the RISK-ADJUSTED HURDLE once you price in the
protocol's tail-loss risk?

A headline yield is only meaningful net of the risk it carries. A protocol
offering 12% APR on a strategy with a meaningful annual probability of a
smart-contract exploit, a stablecoin depeg, or an insolvency event is not
truly offering 12% — the expected loss from that tail event drags the effective
return down, and to be worth holding the offered yield must clear a *hurdle*:
the risk-free baseline PLUS enough premium to compensate for the expected loss.

Given an offered yield, a risk-free baseline, an implied annual probability of a
loss event, and a loss-given-event haircut, this module computes the expected
annual loss drag, the risk-adjusted APR (yield net of expected loss), the
required hurdle APR (risk-free + expected loss), whether the offered yield clears
that hurdle, the raw risk premium earned above the risk-free rate, how many times
that premium covers the expected loss, and a single 0-100 hurdle-clearance score.

Genuine gap: existing modules rate real-yield sustainability and decompose real
vs incentive yield, but none compute a required risk-premium / hurdle APR from an
explicit annual loss probability + loss-given-event and test whether the offered
yield clears it.

The module returns:
- name / offered_apr_pct / risk_free_apr_pct (input echoes)
- annual_loss_probability_pct / loss_given_event_pct (input echoes)
- expected_annual_loss_pct       - prob * lge, expected % of principal lost/yr
- risk_adjusted_apr_pct          - offered yield minus expected loss
- required_hurdle_apr_pct        - risk-free + expected loss (min to clear)
- excess_over_hurdle_pct         - offered minus required hurdle
- risk_premium_earned_pct        - offered minus risk-free (raw premium)
- risk_premium_coverage_ratio    - premium / expected loss (x times covered)
- clears_hurdle                  - bool: excess > 0
- hurdle_clearance_score         - 0-100, higher = more comfortably clears
- classification                 - GENEROUS_PREMIUM .. NEGATIVE_PREMIUM
- grade                          - A-F letter grade
- flags / recommendations        - advisory verdicts

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
    "risk_adjusted_yield_hurdle_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Sentinel for "premium infinitely covers a ~zero expected loss" (so JSON stays
# finite, no inf/NaN).
RATIO_SENTINEL_INF = 1e9

# Defaults.
_DEFAULT_RISK_FREE_APR_PCT = 4.0
_DEFAULT_LOSS_GIVEN_EVENT_PCT = 100.0  # default: total loss if event occurs
_DEFAULT_ANNUAL_LOSS_PROBABILITY_PCT = 0.0

# Classification bands on excess_over_hurdle_pct (offered minus required hurdle)
CLASS_GENEROUS_PREMIUM = "GENEROUS_PREMIUM"
CLASS_ADEQUATE = "ADEQUATE"
CLASS_THIN = "THIN"
CLASS_INADEQUATE = "INADEQUATE"
CLASS_NEGATIVE_PREMIUM = "NEGATIVE_PREMIUM"

ALL_CLASSIFICATIONS = (
    CLASS_GENEROUS_PREMIUM,
    CLASS_ADEQUATE,
    CLASS_THIN,
    CLASS_INADEQUATE,
    CLASS_NEGATIVE_PREMIUM,
)

# Flags
FLAG_CLEARS_HURDLE = "CLEARS_HURDLE"
FLAG_BELOW_HURDLE = "BELOW_HURDLE"
FLAG_NEGATIVE_RISK_ADJUSTED_YIELD = "NEGATIVE_RISK_ADJUSTED_YIELD"
FLAG_HIGH_LOSS_PROBABILITY = "HIGH_LOSS_PROBABILITY"
FLAG_TOTAL_LOSS_GIVEN_EVENT = "TOTAL_LOSS_GIVEN_EVENT"
FLAG_THIN_PREMIUM = "THIN_PREMIUM"
FLAG_GENEROUS_PREMIUM = "GENEROUS_PREMIUM"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_CLEARS_HURDLE,
    FLAG_BELOW_HURDLE,
    FLAG_NEGATIVE_RISK_ADJUSTED_YIELD,
    FLAG_HIGH_LOSS_PROBABILITY,
    FLAG_TOTAL_LOSS_GIVEN_EVENT,
    FLAG_THIN_PREMIUM,
    FLAG_GENEROUS_PREMIUM,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds (module constants)
_GENEROUS_EXCESS_PCT = 5.0      # excess >= 5 -> generous premium
_ADEQUATE_EXCESS_PCT = 1.0      # excess >= 1 -> adequate
_THIN_EXCESS_PCT = 0.0          # excess >= 0 -> thin (just clears)
_INADEQUATE_EXCESS_PCT = -5.0   # excess >= -5 -> inadequate; < -5 negative
_HIGH_LOSS_PROBABILITY_PCT = 10.0   # >= 10%/yr is a high loss probability
_TOTAL_LOSS_GIVEN_EVENT_PCT = 95.0  # >= 95% haircut is effectively total loss


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


# ---------------------------------------------------------------------------
# Sub-calculators (defensive division everywhere)
# ---------------------------------------------------------------------------

def _expected_annual_loss_pct(
    annual_loss_probability_pct: float,
    loss_given_event_pct: float,
) -> float:
    """
    Expected % of principal lost per year.

        expected_loss = (prob/100) * (lge/100) * 100

    Both inputs are floored at 0 and capped at 100 (a probability or haircut
    cannot be negative or exceed 100%).
    """
    prob = _clamp(annual_loss_probability_pct, 0.0, 100.0)
    lge = _clamp(loss_given_event_pct, 0.0, 100.0)
    return (prob / 100.0) * (lge / 100.0) * 100.0


def _risk_adjusted_apr_pct(
    offered_apr_pct: float,
    expected_annual_loss_pct: float,
) -> float:
    """Offered yield net of the expected annual loss drag (can be < 0)."""
    return offered_apr_pct - expected_annual_loss_pct


def _required_hurdle_apr_pct(
    risk_free_apr_pct: float,
    expected_annual_loss_pct: float,
) -> float:
    """Minimum APR to clear: risk-free baseline plus expected annual loss."""
    return risk_free_apr_pct + max(0.0, expected_annual_loss_pct)


def _excess_over_hurdle_pct(
    offered_apr_pct: float,
    required_hurdle_apr_pct: float,
) -> float:
    """Offered yield minus the required hurdle APR (can be < 0)."""
    return offered_apr_pct - required_hurdle_apr_pct


def _risk_premium_earned_pct(
    offered_apr_pct: float,
    risk_free_apr_pct: float,
) -> float:
    """Raw risk premium: offered yield above the risk-free rate (can be < 0)."""
    return offered_apr_pct - risk_free_apr_pct


def _risk_premium_coverage_ratio(
    risk_premium_earned_pct: float,
    expected_annual_loss_pct: float,
) -> float:
    """
    How many times the raw risk premium covers the expected annual loss.

        coverage = risk_premium / expected_loss

    Defensive: when the expected loss is ~0 a positive premium covers it
    infinitely -> RATIO_SENTINEL_INF; a non-positive premium against ~0 loss
    -> 0.0. When both are ~0 -> 0.0.
    """
    loss = max(0.0, expected_annual_loss_pct)
    if loss <= _EPS:
        return RATIO_SENTINEL_INF if risk_premium_earned_pct > _EPS else 0.0
    return risk_premium_earned_pct / loss


def _hurdle_clearance_score(
    excess_over_hurdle_pct: float,
    risk_premium_coverage_ratio: float,
    risk_adjusted_apr_pct: float,
    has_data: bool,
) -> float:
    """
    0-100: higher = the offered yield more comfortably clears the risk hurdle.

    Blends three drivers:
    - excess-over-hurdle (0-50): mapped through a saturating curve so a small
      positive excess scores partial credit and a ~5pp excess saturates the
      full 50; a negative excess contributes 0.
    - coverage-ratio (0-30): how many times the raw premium covers expected
      loss, saturating at ~3x for the full 30.
    - positive risk-adjusted APR (0-20): full 20 when the yield net of expected
      loss is positive, scaled down to 0 as it goes negative.

    Returns 0.0 when there is no usable data.
    """
    if not has_data:
        return 0.0

    # Excess-over-hurdle component: saturating at _GENEROUS_EXCESS_PCT (5pp).
    if excess_over_hurdle_pct <= 0.0:
        excess_component = 0.0
    else:
        excess_ratio = _clamp(
            excess_over_hurdle_pct / _GENEROUS_EXCESS_PCT, 0.0, 1.0)
        excess_component = excess_ratio * 50.0

    # Coverage-ratio component: saturating at 3x coverage.
    if risk_premium_coverage_ratio >= RATIO_SENTINEL_INF:
        coverage_component = 30.0
    elif risk_premium_coverage_ratio <= 0.0:
        coverage_component = 0.0
    else:
        coverage_ratio = _clamp(risk_premium_coverage_ratio / 3.0, 0.0, 1.0)
        coverage_component = coverage_ratio * 30.0

    # Positive risk-adjusted-APR component.
    ra_component = 20.0 if risk_adjusted_apr_pct > 0.0 else 0.0

    return _clamp(excess_component + coverage_component + ra_component)


def _classify(excess_over_hurdle_pct: float, has_data: bool) -> str:
    """
    Assign an advisory classification band on excess over the required hurdle.

      >= 5   -> GENEROUS_PREMIUM
      >= 1   -> ADEQUATE
      >= 0   -> THIN
      >= -5  -> INADEQUATE
      < -5   -> NEGATIVE_PREMIUM

    No data falls back to NEGATIVE_PREMIUM (cannot demonstrate the yield clears
    the risk).
    """
    if not has_data:
        return CLASS_NEGATIVE_PREMIUM

    excess = excess_over_hurdle_pct
    if excess >= _GENEROUS_EXCESS_PCT:
        return CLASS_GENEROUS_PREMIUM
    if excess >= _ADEQUATE_EXCESS_PCT:
        return CLASS_ADEQUATE
    if excess >= _THIN_EXCESS_PCT:
        return CLASS_THIN
    if excess >= _INADEQUATE_EXCESS_PCT:
        return CLASS_INADEQUATE
    return CLASS_NEGATIVE_PREMIUM


def _grade(hurdle_clearance_score: float) -> str:
    """Map hurdle_clearance_score (higher = better) to an A-F letter grade."""
    s = hurdle_clearance_score
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
    excess_over_hurdle_pct: float,
    clears_hurdle: bool,
    risk_adjusted_apr_pct: float,
    annual_loss_probability_pct: float,
    loss_given_event_pct: float,
    classification: str,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if clears_hurdle:
        flags.append(FLAG_CLEARS_HURDLE)
    else:
        flags.append(FLAG_BELOW_HURDLE)

    if risk_adjusted_apr_pct < 0.0:
        flags.append(FLAG_NEGATIVE_RISK_ADJUSTED_YIELD)

    if annual_loss_probability_pct >= _HIGH_LOSS_PROBABILITY_PCT:
        flags.append(FLAG_HIGH_LOSS_PROBABILITY)

    if loss_given_event_pct >= _TOTAL_LOSS_GIVEN_EVENT_PCT:
        flags.append(FLAG_TOTAL_LOSS_GIVEN_EVENT)

    if _THIN_EXCESS_PCT <= excess_over_hurdle_pct < _ADEQUATE_EXCESS_PCT:
        flags.append(FLAG_THIN_PREMIUM)

    if classification == CLASS_GENEROUS_PREMIUM:
        flags.append(FLAG_GENEROUS_PREMIUM)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    offered_apr_pct: float,
    required_hurdle_apr_pct: float,
    excess_over_hurdle_pct: float,
    expected_annual_loss_pct: float,
    risk_adjusted_apr_pct: float,
    risk_premium_coverage_ratio: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: no offered-APR signal or data marked "
            "unreliable. Cannot assess whether the yield clears its "
            "risk-adjusted hurdle."
        )
        return recs

    if classification == CLASS_GENEROUS_PREMIUM:
        recs.append(
            f"Generous premium: the offered ~{offered_apr_pct:.2f}% clears the "
            f"~{required_hurdle_apr_pct:.2f}% risk-adjusted hurdle by "
            f"~{excess_over_hurdle_pct:.2f}pp. The yield is well compensated "
            "for the priced tail-loss risk."
        )
    elif classification == CLASS_ADEQUATE:
        recs.append(
            f"Adequate premium: the offered ~{offered_apr_pct:.2f}% clears the "
            f"~{required_hurdle_apr_pct:.2f}% hurdle by ~{excess_over_hurdle_pct:.2f}pp. "
            "The yield covers risk-free plus expected loss with room to spare."
        )
    elif classification == CLASS_THIN:
        recs.append(
            f"Thin premium: the offered ~{offered_apr_pct:.2f}% only just clears "
            f"the ~{required_hurdle_apr_pct:.2f}% hurdle (~{excess_over_hurdle_pct:.2f}pp). "
            "Little margin for the tail-loss risk being underestimated."
        )
    elif classification == CLASS_INADEQUATE:
        recs.append(
            f"Inadequate premium: the offered ~{offered_apr_pct:.2f}% falls "
            f"~{-excess_over_hurdle_pct:.2f}pp short of the ~{required_hurdle_apr_pct:.2f}% "
            "risk-adjusted hurdle. You are not paid enough for the priced risk."
        )
    else:  # NEGATIVE_PREMIUM
        recs.append(
            f"Negative premium: the offered ~{offered_apr_pct:.2f}% falls far "
            f"short of the ~{required_hurdle_apr_pct:.2f}% hurdle. The yield "
            "does not compensate for the tail-loss risk; consider avoiding."
        )

    if FLAG_NEGATIVE_RISK_ADJUSTED_YIELD in flags:
        recs.append(
            f"Negative risk-adjusted yield: after the expected annual loss of "
            f"~{expected_annual_loss_pct:.2f}pp the yield is ~{risk_adjusted_apr_pct:.2f}% — "
            "expected loss exceeds the offered APR."
        )

    if FLAG_HIGH_LOSS_PROBABILITY in flags:
        recs.append(
            "High loss probability: the implied annual chance of a loss event "
            "is elevated; small errors in the probability estimate move the "
            "hurdle materially. Demand extra premium or size down."
        )

    if FLAG_TOTAL_LOSS_GIVEN_EVENT in flags:
        recs.append(
            "Total loss given event: a loss event is assumed to wipe out "
            "(nearly) the full principal, so the hurdle is driven entirely by "
            "the event probability."
        )

    if FLAG_THIN_PREMIUM in flags:
        recs.append(
            f"Thin coverage: the raw risk premium covers the expected loss only "
            f"~{risk_premium_coverage_ratio:.2f}x. Prefer a wider buffer before "
            "deploying."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    token: dict | None = None,
    config: dict | None = None,
    *,
    offered_apr_pct: float | None = None,
    risk_free_apr_pct: float | None = None,
    annual_loss_probability_pct: float | None = None,
    loss_given_event_pct: float | None = None,
    data_quality: Any = None,
    name: str | None = None,
) -> dict:
    """
    Analyse whether an offered DeFi APR clears its risk-adjusted hurdle.

    Inputs may be supplied as a ``token`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    Recognised keys / keywords (all with safe defaults):
    - name                        : str
    - offered_apr_pct             : float (the yield the protocol offers)
    - risk_free_apr_pct           : float (baseline, default 4.0)
    - annual_loss_probability_pct : float (implied loss-event chance/yr, 0..100)
    - loss_given_event_pct        : float (principal haircut if event, default 100)
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

    offered = _pick(offered_apr_pct, "offered_apr_pct", 0.0)
    risk_free = _pick(
        risk_free_apr_pct, "risk_free_apr_pct", _DEFAULT_RISK_FREE_APR_PCT)
    loss_prob = _clamp(
        _pick(annual_loss_probability_pct, "annual_loss_probability_pct",
              _DEFAULT_ANNUAL_LOSS_PROBABILITY_PCT),
        0.0, 100.0)
    lge = _clamp(
        _pick(loss_given_event_pct, "loss_given_event_pct",
              _DEFAULT_LOSS_GIVEN_EVENT_PCT),
        0.0, 100.0)

    dq_raw = data_quality if data_quality is not None else t.get("data_quality", "ok")
    if isinstance(dq_raw, str):
        data_quality_ok = dq_raw.strip().lower() not in ("poor", "bad", "low", "")
    else:
        data_quality_ok = bool(dq_raw)

    # Data sufficiency: need an offered-APR signal and the data-quality flag
    # must not mark the inputs as unreliable. (Risk-free has a default; loss
    # probability may legitimately be 0.)
    has_signal = abs(offered) > _EPS
    has_data = has_signal and data_quality_ok

    exp_loss = _expected_annual_loss_pct(loss_prob, lge)
    risk_adj = _risk_adjusted_apr_pct(offered, exp_loss)
    hurdle = _required_hurdle_apr_pct(risk_free, exp_loss)
    excess = _excess_over_hurdle_pct(offered, hurdle)
    premium = _risk_premium_earned_pct(offered, risk_free)
    coverage = _risk_premium_coverage_ratio(premium, exp_loss)
    clears = excess > 0.0
    classification = _classify(excess, has_data)
    score = _hurdle_clearance_score(excess, coverage, risk_adj, has_data)
    grade = _grade(score)
    flags = _flags(
        excess,
        clears,
        risk_adj,
        loss_prob,
        lge,
        classification,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        offered,
        hurdle,
        excess,
        exp_loss,
        risk_adj,
        coverage,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "offered_apr_pct": offered,
        "risk_free_apr_pct": risk_free,
        "annual_loss_probability_pct": loss_prob,
        "loss_given_event_pct": lge,
        "data_quality_ok": data_quality_ok,
        "expected_annual_loss_pct": exp_loss,
        "risk_adjusted_apr_pct": risk_adj,
        "required_hurdle_apr_pct": hurdle,
        "excess_over_hurdle_pct": excess,
        "risk_premium_earned_pct": premium,
        "risk_premium_coverage_ratio": coverage,
        "clears_hurdle": clears,
        "hurdle_clearance_score": score,
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

def analyze_portfolio(positions: list, config: dict | None = None) -> dict:
    """
    Analyse risk-adjusted hurdle clearance across a batch of positions.

    Returns
    -------
    dict
        - total_positions                : int
        - results                        : list[dict]  (per-position analysis)
        - best_hurdle_clearance_position : str | None  (highest score)
        - worst_hurdle_clearance_position: str | None  (lowest score)
        - avg_hurdle_clearance_score     : float
        - below_hurdle_count             : int  (positions not clearing hurdle)
        - timestamp                      : float
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
            "best_hurdle_clearance_position": None,
            "worst_hurdle_clearance_position": None,
            "avg_hurdle_clearance_score": 0.0,
            "below_hurdle_count": 0,
            "timestamp": time.time(),
        }

    best = max(results, key=lambda r: r["hurdle_clearance_score"])
    worst = min(results, key=lambda r: r["hurdle_clearance_score"])
    avg = sum(r["hurdle_clearance_score"] for r in results) / total
    below = sum(1 for r in results if not r["clears_hurdle"])

    return {
        "total_positions": total,
        "results": results,
        "best_hurdle_clearance_position": best["name"],
        "worst_hurdle_clearance_position": worst["name"],
        "avg_hurdle_clearance_score": avg,
        "below_hurdle_count": below,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolRiskAdjustedYieldHurdleAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = DeFiProtocolRiskAdjustedYieldHurdleAnalyzer()
    >>> r = a.analyze({"name": "Vault-X", "offered_apr_pct": 12.0,
    ...                "annual_loss_probability_pct": 3.0,
    ...                "loss_given_event_pct": 80.0})
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
            "name": "Blue-chip stable lending (safe)",
            "offered_apr_pct": 9.0,
            "risk_free_apr_pct": 4.0,
            "annual_loss_probability_pct": 1.0,
            "loss_given_event_pct": 50.0,
        },
        {
            "name": "Exotic farm (risky)",
            "offered_apr_pct": 14.0,
            "risk_free_apr_pct": 4.0,
            "annual_loss_probability_pct": 15.0,
            "loss_given_event_pct": 100.0,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_positions[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_positions)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
