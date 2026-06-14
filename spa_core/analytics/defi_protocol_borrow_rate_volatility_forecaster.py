"""
MP-1109  DeFiProtocolBorrowRateVolatilityForecaster
---------------------------------------------------
Forecast the forward VOLATILITY (dispersion) of a lending market's borrow APR
over a horizon, driven by utilization volatility amplified through the kinked
rate-model slope, so a leveraged / looping yield farmer can judge how stable
their borrow cost - and thus net carry (farm/supply APR minus borrow APR) -
will be.

A looping / leveraged farmer borrows against supplied collateral to recycle
into more yield. Their edge is the *carry*: the gross farm APR they earn minus
the borrow APR they pay. That carry is only as stable as the borrow rate, and
the borrow rate moves with utilization through the rate model. Near or past the
kink the *second slope* makes the borrow rate extremely sensitive to small
utilization moves, so the same utilization volatility produces a far larger
borrow-rate dispersion.

This module converts a market's utilization volatility into a forward borrow-
rate volatility using the local rate-model sensitivity, then derives a carry
"wipeout" probability (the chance the borrow rate climbs above the farm APR,
erasing the carry). This is *forward-looking dispersion*, distinct from
MP-1108's point-in-time distance to the kink.

This module computes, for a single market:
- the local rate sensitivity (d borrow-APR / d utilization),
- the forecast 1-sigma annualized borrow-APR volatility,
- p95 / p05 borrow-APR cones,
- net carry now and at the p95 borrow rate,
- a carry-wipeout probability (normal tail), and
- a 0-100 *rate-stability score* (higher = more stable / safer).

Genuine gap: existing modules forecast APY and utilization, but none translate
utilization volatility through the kinked slope into a forward borrow-rate
dispersion and a carry-wipeout probability for looped positions.

The module returns:
- current_borrow_apr_pct
- rate_sensitivity_factor
- forecast_borrow_apr_vol_pct      - 1-sigma annualized APR dispersion
- borrow_apr_p95_pct / borrow_apr_p05_pct
- net_carry_now_pct
- net_carry_at_p95_borrow_pct
- carry_wipeout_probability_pct
- rate_stability_score             - 0-100, higher = more stable / safer
- classification                   - VERY_STABLE .. HIGHLY_VOLATILE
- grade                            - A-F letter grade
- flags / recommendations          - advisory verdicts

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (100 entries).
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
    "borrow_rate_volatility_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# 90% two-sided z (one-tailed 95%) for the p95/p05 cone.
_Z_95 = 1.645

# Default rate-model / input parameters.
_DEFAULT_UTILIZATION_VOLATILITY_PCT = 10.0
_DEFAULT_KINK_UTILIZATION_PCT = 80.0
_DEFAULT_SLOPE1_PCT = 4.0
_DEFAULT_SLOPE2_PCT = 60.0
_DEFAULT_HORIZON_DAYS = 30.0

# Classification bands
CLASS_VERY_STABLE = "VERY_STABLE"
CLASS_STABLE = "STABLE"
CLASS_MODERATE = "MODERATE"
CLASS_VOLATILE = "VOLATILE"
CLASS_HIGHLY_VOLATILE = "HIGHLY_VOLATILE"

ALL_CLASSIFICATIONS = (
    CLASS_VERY_STABLE,
    CLASS_STABLE,
    CLASS_MODERATE,
    CLASS_VOLATILE,
    CLASS_HIGHLY_VOLATILE,
)

# Flags
FLAG_HIGH_RATE_VOLATILITY = "HIGH_RATE_VOLATILITY"
FLAG_CARRY_WIPEOUT_RISK = "CARRY_WIPEOUT_RISK"
FLAG_HIGH_UTILIZATION_SENSITIVITY = "HIGH_UTILIZATION_SENSITIVITY"
FLAG_NEGATIVE_CARRY_AT_P95 = "NEGATIVE_CARRY_AT_P95"
FLAG_THIN_CARRY_MARGIN = "THIN_CARRY_MARGIN"
FLAG_STABLE_BORROW_COST = "STABLE_BORROW_COST"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_HIGH_RATE_VOLATILITY,
    FLAG_CARRY_WIPEOUT_RISK,
    FLAG_HIGH_UTILIZATION_SENSITIVITY,
    FLAG_NEGATIVE_CARRY_AT_P95,
    FLAG_THIN_CARRY_MARGIN,
    FLAG_STABLE_BORROW_COST,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Classification band thresholds (on forecast_borrow_apr_vol_pct).
_VOL_VERY_STABLE_PCT = 1.0
_VOL_STABLE_PCT = 3.0
_VOL_MODERATE_PCT = 6.0
_VOL_VOLATILE_PCT = 12.0

# Flag / forcing thresholds (module constants).
_HIGH_RATE_VOLATILITY_PCT = 6.0          # forecast vol >= 6 pts is high
_CARRY_WIPEOUT_PROB_PCT = 25.0           # wipeout prob >= 25% is risky
_HIGH_SENSITIVITY_FACTOR = 1.0           # >= 1 APR-pt per util-pt is high
_THIN_CARRY_MARGIN_PCT = 1.0             # net carry now < 1 pt is thin
_STABLE_BORROW_COST_VOL_PCT = 1.0        # forecast vol < 1 pt is stable


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


def _norm_sf(z: float) -> float:
    """
    Upper-tail (survival function) of the standard normal at *z*.

    Uses the complementary error function::

        sf(z) = 0.5 * erfc(z / sqrt(2))

    Returns a probability in [0, 1]. Defensive against non-finite inputs.
    """
    try:
        return 0.5 * math.erfc(z / math.sqrt(2.0))
    except (ValueError, OverflowError):
        # math.erfc saturates cleanly; this guards only pathological inputs.
        return 0.0 if z > 0 else 1.0


# ---------------------------------------------------------------------------
# Sub-calculators (defensive division everywhere)
# ---------------------------------------------------------------------------

def _rate_sensitivity_factor(
    util: float,
    kink: float,
    slope1: float,
    slope2: float,
) -> float:
    """
    Local rate sensitivity d(borrowAPR)/d(utilization), APR-pts per util-pt.

    The kinked rate model has two local slopes::

        if util <= kink:
            sensitivity = slope1 / kink
        else:
            sensitivity = slope2 / (100 - kink)

    Above the kink the second slope makes the borrow rate far more sensitive to
    the same utilization move. Defensive: a non-positive kink routes to the
    second regime; both denominators are guarded with _EPS.
    """
    k = kink
    if k <= 0.0:
        return slope2 / max(100.0 - k, _EPS)
    if util <= k:
        return slope1 / max(k, _EPS)
    return slope2 / max(100.0 - k, _EPS)


def _forecast_borrow_apr_vol_pct(
    rate_sensitivity_factor: float,
    utilization_volatility_pct: float,
) -> float:
    """
    1-sigma annualized borrow-APR dispersion, in pct.

        vol = rate_sensitivity_factor * utilization_volatility_pct

    Floored at 0 (volatility cannot be negative).
    """
    return max(0.0, rate_sensitivity_factor * max(0.0, utilization_volatility_pct))


def _borrow_apr_p95_pct(
    current_borrow_apr_pct: float,
    forecast_vol_pct: float,
) -> float:
    """Upper p95 borrow-APR cone: current + 1.645 * forecast_vol."""
    return current_borrow_apr_pct + _Z_95 * forecast_vol_pct


def _borrow_apr_p05_pct(
    current_borrow_apr_pct: float,
    forecast_vol_pct: float,
) -> float:
    """Lower p05 borrow-APR cone: max(0, current - 1.645 * forecast_vol)."""
    return max(0.0, current_borrow_apr_pct - _Z_95 * forecast_vol_pct)


def _net_carry_now_pct(
    farm_apr_pct: float,
    current_borrow_apr_pct: float,
) -> float:
    """Net carry today: farm APR minus current borrow APR."""
    return farm_apr_pct - current_borrow_apr_pct


def _net_carry_at_p95_borrow_pct(
    farm_apr_pct: float,
    borrow_apr_p95_pct: float,
) -> float:
    """Net carry under the p95 (stress) borrow rate: farm APR minus p95."""
    return farm_apr_pct - borrow_apr_p95_pct


def _carry_wipeout_probability_pct(
    farm_apr_pct: float,
    current_borrow_apr_pct: float,
    forecast_vol_pct: float,
) -> float:
    """
    Approximate P(borrow_apr >= farm_apr) as a normal upper tail, in pct.

    The borrow rate is modelled as ~Normal(current_borrow_apr, forecast_vol).
    The carry is wiped out when the borrow rate reaches the farm APR. Let::

        z = (farm_apr - current_borrow_apr) / forecast_vol
        prob = _norm_sf(z)   # P(borrow >= farm)

    Defensive: when the forecast volatility is ~0 there is no dispersion, so the
    probability is 0% if the carry is currently positive (or break-even) and
    100% if the carry is already negative.

    Returns a probability clamped to [0, 100].
    """
    carry = farm_apr_pct - current_borrow_apr_pct
    if forecast_vol_pct <= _EPS:
        return 0.0 if carry >= 0.0 else 100.0
    z = carry / forecast_vol_pct
    prob = _norm_sf(z) * 100.0
    return _clamp(prob, 0.0, 100.0)


def _rate_stability_score(
    forecast_vol_pct: float,
    net_carry_now_pct: float,
    carry_wipeout_probability_pct: float,
    has_data: bool,
) -> float:
    """
    0-100: higher = MORE stable / safer borrow cost for a looped position.

    Blends three drivers:
    - low-volatility (0-45): one minus the forecast borrow-APR volatility
      scaled against a reference (the VOLATILE band, 12 pts). Lower vol is
      safer.
    - carry-margin (0-30): the net carry now scaled against a healthy
      reference (10 pts). A fat positive carry is safer; a negative carry
      contributes 0.
    - low-wipeout (0-25): one minus the carry-wipeout probability. A low
      chance of the carry being erased is safer.

    Returns 0.0 when there is no usable data.
    """
    if not has_data:
        return 0.0

    # Low-volatility component (0..1): scaled against the VOLATILE band.
    vol_exposure = _clamp(
        forecast_vol_pct / max(_VOL_VOLATILE_PCT, _EPS), 0.0, 1.0)
    vol_component = (1.0 - vol_exposure) * 45.0

    # Carry-margin component (0..1): scaled against a 10-pt healthy carry.
    carry_share = _clamp(net_carry_now_pct / 10.0, 0.0, 1.0)
    carry_component = carry_share * 30.0

    # Low-wipeout component (0..1).
    wipeout_share = _clamp(carry_wipeout_probability_pct / 100.0, 0.0, 1.0)
    wipeout_component = (1.0 - wipeout_share) * 25.0

    score = vol_component + carry_component + wipeout_component
    return _clamp(score)


def _classify(
    forecast_vol_pct: float,
    carry_wipeout_probability_pct: float,
    has_data: bool,
) -> str:
    """
    Assign an advisory classification band, driven by forecast borrow-APR vol.

    Bands (on forecast_borrow_apr_vol_pct):
      < 1   -> VERY_STABLE
      < 3   -> STABLE
      < 6   -> MODERATE
      < 12  -> VOLATILE
      >= 12 -> HIGHLY_VOLATILE

    A high carry-wipeout probability (>= 25%) forces at least MODERATE: even a
    low headline vol is not "stable" if the carry is one move from erasure.

    No data falls back to VERY_STABLE (no dispersion can be demonstrated).
    """
    if not has_data:
        return CLASS_VERY_STABLE

    if forecast_vol_pct < _VOL_VERY_STABLE_PCT:
        base = CLASS_VERY_STABLE
    elif forecast_vol_pct < _VOL_STABLE_PCT:
        base = CLASS_STABLE
    elif forecast_vol_pct < _VOL_MODERATE_PCT:
        base = CLASS_MODERATE
    elif forecast_vol_pct < _VOL_VOLATILE_PCT:
        base = CLASS_VOLATILE
    else:
        base = CLASS_HIGHLY_VOLATILE

    order = list(ALL_CLASSIFICATIONS)
    idx = order.index(base)

    # A high wipeout probability forces at least MODERATE.
    if carry_wipeout_probability_pct >= _CARRY_WIPEOUT_PROB_PCT:
        idx = max(idx, order.index(CLASS_MODERATE))

    return order[idx]


def _grade(rate_stability_score: float) -> str:
    """Map rate_stability_score (higher = stabler) to an A-F letter grade."""
    s = rate_stability_score
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
    forecast_vol_pct: float,
    carry_wipeout_probability_pct: float,
    rate_sensitivity_factor: float,
    net_carry_now_pct: float,
    net_carry_at_p95_borrow_pct: float,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if forecast_vol_pct >= _HIGH_RATE_VOLATILITY_PCT:
        flags.append(FLAG_HIGH_RATE_VOLATILITY)

    if carry_wipeout_probability_pct >= _CARRY_WIPEOUT_PROB_PCT:
        flags.append(FLAG_CARRY_WIPEOUT_RISK)

    if rate_sensitivity_factor >= _HIGH_SENSITIVITY_FACTOR:
        flags.append(FLAG_HIGH_UTILIZATION_SENSITIVITY)

    if net_carry_at_p95_borrow_pct < 0.0:
        flags.append(FLAG_NEGATIVE_CARRY_AT_P95)

    if net_carry_now_pct < _THIN_CARRY_MARGIN_PCT:
        flags.append(FLAG_THIN_CARRY_MARGIN)

    if forecast_vol_pct < _STABLE_BORROW_COST_VOL_PCT:
        flags.append(FLAG_STABLE_BORROW_COST)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    forecast_vol_pct: float,
    current_borrow_apr_pct: float,
    borrow_apr_p95_pct: float,
    net_carry_now_pct: float,
    net_carry_at_p95_borrow_pct: float,
    carry_wipeout_probability_pct: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: no borrow-rate / utilization signal and/or "
            "data marked unreliable. Cannot forecast borrow-rate volatility "
            "for this market."
        )
        return recs

    if classification == CLASS_HIGHLY_VOLATILE:
        recs.append(
            f"Highly volatile borrow cost: forecast 1-sigma dispersion is "
            f"~{forecast_vol_pct:.2f} points of APR. Borrow APR could spike "
            f"to ~{borrow_apr_p95_pct:.2f}% (p95) from ~{current_borrow_apr_pct:.2f}% "
            "today; size leverage conservatively."
        )
    elif classification == CLASS_VOLATILE:
        recs.append(
            f"Volatile borrow cost: forecast ~{forecast_vol_pct:.2f} points of "
            f"APR dispersion; p95 borrow rate ~{borrow_apr_p95_pct:.2f}%. Net "
            f"carry could fall to ~{net_carry_at_p95_borrow_pct:.2f}% under stress."
        )
    elif classification == CLASS_MODERATE:
        recs.append(
            f"Moderate borrow-cost volatility: ~{forecast_vol_pct:.2f} points "
            f"of forecast APR dispersion. Net carry today ~{net_carry_now_pct:.2f}%; "
            f"~{net_carry_at_p95_borrow_pct:.2f}% at the p95 borrow rate."
        )
    elif classification == CLASS_STABLE:
        recs.append(
            f"Stable borrow cost: forecast dispersion is a modest "
            f"~{forecast_vol_pct:.2f} points of APR. Carry of "
            f"~{net_carry_now_pct:.2f}% is reasonably defensible."
        )
    else:  # VERY_STABLE
        recs.append(
            f"Very stable borrow cost: forecast dispersion is only "
            f"~{forecast_vol_pct:.2f} points of APR. Borrow cost is highly "
            f"predictable; carry ~{net_carry_now_pct:.2f}%."
        )

    if FLAG_CARRY_WIPEOUT_RISK in flags:
        recs.append(
            f"Carry-wipeout risk: ~{carry_wipeout_probability_pct:.1f}% modelled "
            "probability the borrow rate climbs above the farm APR and erases "
            "the carry over the horizon. Keep a deleveraging trigger ready."
        )

    if FLAG_NEGATIVE_CARRY_AT_P95 in flags:
        recs.append(
            f"Negative carry at p95: under a stress borrow rate of "
            f"~{borrow_apr_p95_pct:.2f}% the position bleeds "
            f"~{abs(net_carry_at_p95_borrow_pct):.2f} points per year. The loop "
            "is not robust to a rate spike."
        )

    if FLAG_HIGH_UTILIZATION_SENSITIVITY in flags:
        recs.append(
            "High utilization sensitivity: the market is near/past the kink, "
            "so the steep second slope amplifies small utilization moves into "
            "large borrow-rate swings."
        )

    if FLAG_THIN_CARRY_MARGIN in flags:
        recs.append(
            f"Thin carry margin: net carry today is only "
            f"~{net_carry_now_pct:.2f} points, leaving little cushion before a "
            "rate move turns the loop unprofitable."
        )

    if FLAG_STABLE_BORROW_COST in flags and FLAG_CARRY_WIPEOUT_RISK not in flags:
        recs.append(
            "Stable borrow cost: forecast dispersion is minimal, so the carry "
            "is unlikely to be disrupted by rate moves over the horizon."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    token: dict | None = None,
    config: dict | None = None,
    *,
    current_borrow_apr_pct: float | None = None,
    current_utilization_pct: float | None = None,
    utilization_volatility_pct: float | None = None,
    kink_utilization_pct: float | None = None,
    slope1_pct: float | None = None,
    slope2_pct: float | None = None,
    farm_apr_pct: float | None = None,
    horizon_days: float | None = None,
    data_quality: Any = None,
    name: str | None = None,
) -> dict:
    """
    Forecast borrow-rate volatility for a single kinked lending market.

    Inputs may be supplied as a ``token`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    Recognised keys / keywords (all with safe defaults):
    - name                       : str
    - current_borrow_apr_pct     : float (borrow APR today)
    - current_utilization_pct    : float (0-100, current utilization)
    - utilization_volatility_pct : float (annualized stdev of util, default 10)
    - kink_utilization_pct       : float (default 80.0)
    - slope1_pct                 : float (default 4.0)
    - slope2_pct                 : float (default 60.0)
    - farm_apr_pct               : float (gross yield earned, default 0.0)
    - horizon_days               : float (default 30.0)
    - data_quality               : truthy/"ok" => trusted; falsy/"poor" => not

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

    borrow_apr = _pick(current_borrow_apr_pct, "current_borrow_apr_pct", 0.0)
    util = _clamp(
        _pick(current_utilization_pct, "current_utilization_pct", 0.0),
        0.0, 100.0,
    )
    util_vol = max(0.0, _pick(
        utilization_volatility_pct, "utilization_volatility_pct",
        _DEFAULT_UTILIZATION_VOLATILITY_PCT))
    kink = _clamp(
        _pick(kink_utilization_pct, "kink_utilization_pct",
              _DEFAULT_KINK_UTILIZATION_PCT),
        0.0, 100.0,
    )
    slope1 = _pick(slope1_pct, "slope1_pct", _DEFAULT_SLOPE1_PCT)
    slope2 = _pick(slope2_pct, "slope2_pct", _DEFAULT_SLOPE2_PCT)
    farm_apr = _pick(farm_apr_pct, "farm_apr_pct", 0.0)
    horizon = max(0.0, _pick(horizon_days, "horizon_days", _DEFAULT_HORIZON_DAYS))

    dq_raw = data_quality if data_quality is not None else t.get("data_quality", "ok")
    if isinstance(dq_raw, str):
        data_quality_ok = dq_raw.strip().lower() not in ("poor", "bad", "low", "")
    else:
        data_quality_ok = bool(dq_raw)

    # Data sufficiency: need a borrow-rate / utilization / farm signal, and the
    # data-quality flag must not mark the inputs as unreliable.
    has_signal = (
        abs(borrow_apr) > _EPS
        or abs(util) > _EPS
        or abs(farm_apr) > _EPS
    )
    has_data = has_signal and data_quality_ok

    sensitivity = _rate_sensitivity_factor(util, kink, slope1, slope2)
    forecast_vol = _forecast_borrow_apr_vol_pct(sensitivity, util_vol)
    p95 = _borrow_apr_p95_pct(borrow_apr, forecast_vol)
    p05 = _borrow_apr_p05_pct(borrow_apr, forecast_vol)
    carry_now = _net_carry_now_pct(farm_apr, borrow_apr)
    carry_p95 = _net_carry_at_p95_borrow_pct(farm_apr, p95)
    wipeout_prob = _carry_wipeout_probability_pct(farm_apr, borrow_apr, forecast_vol)
    stability = _rate_stability_score(
        forecast_vol, carry_now, wipeout_prob, has_data
    )
    classification = _classify(forecast_vol, wipeout_prob, has_data)
    grade = _grade(stability)
    flags = _flags(
        forecast_vol,
        wipeout_prob,
        sensitivity,
        carry_now,
        carry_p95,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        forecast_vol,
        borrow_apr,
        p95,
        carry_now,
        carry_p95,
        wipeout_prob,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "current_borrow_apr_pct": borrow_apr,
        "current_utilization_pct": util,
        "utilization_volatility_pct": util_vol,
        "kink_utilization_pct": kink,
        "slope1_pct": slope1,
        "slope2_pct": slope2,
        "farm_apr_pct": farm_apr,
        "horizon_days": horizon,
        "data_quality_ok": data_quality_ok,
        "rate_sensitivity_factor": sensitivity,
        "forecast_borrow_apr_vol_pct": forecast_vol,
        "borrow_apr_p95_pct": p95,
        "borrow_apr_p05_pct": p05,
        "net_carry_now_pct": carry_now,
        "net_carry_at_p95_borrow_pct": carry_p95,
        "carry_wipeout_probability_pct": wipeout_prob,
        "rate_stability_score": stability,
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
    Forecast borrow-rate volatility across a batch of markets and summarise.

    Returns
    -------
    dict
        - total_positions          : int
        - results                  : list[dict]  (per-market analysis)
        - most_stable_market       : str | None  (highest stability score)
        - most_volatile_market     : str | None  (lowest stability score)
        - avg_rate_stability_score : float
        - wipeout_risk_count       : int  (high wipeout prob or neg carry @p95)
        - timestamp                : float
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
            "most_stable_market": None,
            "most_volatile_market": None,
            "avg_rate_stability_score": 0.0,
            "wipeout_risk_count": 0,
            "timestamp": time.time(),
        }

    most_stable = max(results, key=lambda r: r["rate_stability_score"])
    most_volatile = min(results, key=lambda r: r["rate_stability_score"])
    avg = sum(r["rate_stability_score"] for r in results) / total
    wipeout_risk = sum(
        1 for r in results
        if r["carry_wipeout_probability_pct"] >= _CARRY_WIPEOUT_PROB_PCT
        or FLAG_NEGATIVE_CARRY_AT_P95 in r["flags"]
    )

    return {
        "total_positions": total,
        "results": results,
        "most_stable_market": most_stable["name"],
        "most_volatile_market": most_volatile["name"],
        "avg_rate_stability_score": avg,
        "wipeout_risk_count": wipeout_risk,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolBorrowRateVolatilityForecaster:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> f = DeFiProtocolBorrowRateVolatilityForecaster()
    >>> r = f.analyze({"name": "USDC", "current_borrow_apr_pct": 8.0})
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

    _demo_markets = [
        {
            "name": "USDC loop (past kink, volatile)",
            "current_borrow_apr_pct": 46.0,
            "current_utilization_pct": 94.0,
            "utilization_volatility_pct": 8.0,
            "kink_utilization_pct": 80.0,
            "slope1_pct": 4.0,
            "slope2_pct": 60.0,
            "farm_apr_pct": 50.0,
            "horizon_days": 30.0,
        },
        {
            "name": "ETH loop (below kink, stable)",
            "current_borrow_apr_pct": 1.8,
            "current_utilization_pct": 35.0,
            "utilization_volatility_pct": 10.0,
            "kink_utilization_pct": 80.0,
            "slope1_pct": 4.0,
            "slope2_pct": 60.0,
            "farm_apr_pct": 6.0,
            "horizon_days": 30.0,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_markets[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_markets)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
