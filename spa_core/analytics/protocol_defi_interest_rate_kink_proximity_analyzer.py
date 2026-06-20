"""
MP-1108  ProtocolDeFiInterestRateKinkProximityAnalyzer
------------------------------------------------------
Quantify, for a supplier earning yield in a kinked (two-slope) lending market,
how close current utilization sits to the optimal/"kink" utilization, the
borrow-rate shock if utilization crosses it, and the liquidity headroom buffer
before the kink.

Aave / Compound-style lending markets price the borrow rate off a kinked,
two-slope interest-rate model. Below the optimal ("kink") utilization the
borrow APR rises along a gentle *first slope*; above the kink it rises along a
much steeper *second slope* that is engineered to push utilization back down
toward the optimum. For a *supplier* earning yield this geometry matters in two
ways:

  (a) Utilization near or past the kink means the market is one withdrawal away
      from a sharp borrow-rate spike, which cascades into supply APR and can
      strand liquidity (suppliers cannot withdraw when utilization is ~100%).
  (b) The distance to the kink is a leading indicator of how much *headroom* a
      market has before it tips into the steep regime.

This module computes, for a single market:
- the kinked borrow APR at the current utilization, at the kink, and at 100%,
- the headroom (in utilization points) before the kink,
- the rate "shock" embedded in the steep second slope above the kink,
- the supplier-side APR net of the reserve factor,
- a liquidity buffer (available liquidity as a share of supply), and
- a 0-100 *kink-proximity score* (higher = safer / more headroom).

Genuine gap: existing modules score utilization and borrow-cost optimisation,
but none quantify the supplier-side *distance to the kink*, the second-slope
rate shock, and the liquidity headroom buffer as a single proximity score.

The module returns:
- utilization_pct / kink_utilization_pct
- utilization_headroom_pct        - kink minus current utilization
- projected_borrow_apr_now_pct    - kinked borrow APR at current utilization
- projected_borrow_apr_at_kink_pct
- projected_borrow_apr_at_full_pct
- rate_shock_if_crossed_pct       - steep second-slope shock above the kink
- supply_apr_now_pct              - supplier APR net of reserve factor
- liquidity_buffer_pct            - available liquidity / supply
- kink_proximity_score            - 0-100, higher = safer / more headroom
- classification                  - AMPLE_HEADROOM .. PAST_KINK
- grade                           - A-F letter grade
- flags / recommendations         - advisory verdicts

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "interest_rate_kink_proximity_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Default rate-model parameters (Aave/Compound-style).
_DEFAULT_KINK_UTILIZATION_PCT = 80.0
_DEFAULT_BASE_RATE_PCT = 0.0
_DEFAULT_SLOPE1_PCT = 4.0
_DEFAULT_SLOPE2_PCT = 60.0
_DEFAULT_RESERVE_FACTOR_PCT = 10.0

# Classification bands
CLASS_AMPLE_HEADROOM = "AMPLE_HEADROOM"
CLASS_COMFORTABLE = "COMFORTABLE"
CLASS_APPROACHING_KINK = "APPROACHING_KINK"
CLASS_AT_KINK = "AT_KINK"
CLASS_PAST_KINK = "PAST_KINK"

ALL_CLASSIFICATIONS = (
    CLASS_AMPLE_HEADROOM,
    CLASS_COMFORTABLE,
    CLASS_APPROACHING_KINK,
    CLASS_AT_KINK,
    CLASS_PAST_KINK,
)

# Flags
FLAG_PAST_KINK = "PAST_KINK"
FLAG_AT_KINK = "AT_KINK"
FLAG_THIN_LIQUIDITY_BUFFER = "THIN_LIQUIDITY_BUFFER"
FLAG_STEEP_SECOND_SLOPE = "STEEP_SECOND_SLOPE"
FLAG_LARGE_RATE_SHOCK = "LARGE_RATE_SHOCK"
FLAG_AMPLE_HEADROOM = "AMPLE_HEADROOM"
FLAG_LOW_UTILIZATION_IDLE = "LOW_UTILIZATION_IDLE"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_PAST_KINK,
    FLAG_AT_KINK,
    FLAG_THIN_LIQUIDITY_BUFFER,
    FLAG_STEEP_SECOND_SLOPE,
    FLAG_LARGE_RATE_SHOCK,
    FLAG_AMPLE_HEADROOM,
    FLAG_LOW_UTILIZATION_IDLE,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds (module constants)
_THIN_LIQUIDITY_BUFFER_PCT = 10.0   # < 10% available-vs-supply is thin
_STEEP_SECOND_SLOPE_PCT = 40.0      # slope2 >= 40% borrow APR is steep
_LARGE_RATE_SHOCK_PCT = 30.0        # rate shock >= 30 pts above kink is large
_AMPLE_HEADROOM_PCT = 25.0          # >= 25 util-points of headroom is ample
_LOW_UTILIZATION_IDLE_PCT = 20.0    # < 20% utilization => idle capital drag
_AT_KINK_PROXIMITY = 0.98           # within 2% of kink (as a ratio) is "at"


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

def _borrow_apr_at_util(
    util: float,
    kink: float,
    base: float,
    slope1: float,
    slope2: float,
) -> float:
    """
    Kinked two-slope borrow APR (pct) at a given utilization.

    Below the kink the borrow rate rises along the gentle first slope; above
    the kink it rises along the steep second slope::

        if util <= kink:
            apr = base + slope1 * (util / kink)
        else:
            apr = base + slope1 + slope2 * ((util - kink) / (100 - kink))

    Defensive:
    - utilization is clamped to [0, 100],
    - a non-positive kink (kink <= 0) is guarded with _EPS so the first-slope
      ratio cannot divide by zero (everything is then in the second regime),
    - a non-positive (100 - kink) is guarded with _EPS so the second-slope
      ratio cannot divide by zero.
    """
    u = _clamp(util, 0.0, 100.0)
    k = kink

    if k <= 0.0:
        # Degenerate: the kink is at (or below) 0% utilization, so the whole
        # curve is the steep second slope from 0 -> 100.
        denom = max(100.0 - k, _EPS)
        return base + slope1 + slope2 * (max(0.0, u - k) / denom)

    if u <= k:
        return base + slope1 * (u / max(k, _EPS))

    denom = max(100.0 - k, _EPS)
    return base + slope1 + slope2 * ((u - k) / denom)


def _utilization_headroom_pct(utilization_pct: float, kink_utilization_pct: float) -> float:
    """
    Headroom in utilization points before the kink (can be negative past it).

    headroom = kink_utilization - current_utilization
    """
    return kink_utilization_pct - utilization_pct


def _rate_shock_if_crossed_pct(
    apr_at_kink_pct: float,
    apr_at_full_pct: float,
) -> float:
    """
    The steep second-slope borrow-rate shock above the kink, in pct (floor 0).

    This is the additional borrow APR a supplier's market would impose between
    the kink and 100% utilization::

        shock = max(0, apr_at_full - apr_at_kink)
    """
    return max(0.0, apr_at_full_pct - apr_at_kink_pct)


def _supply_apr_now_pct(
    borrow_apr_now_pct: float,
    utilization_pct: float,
    reserve_factor_pct: float,
) -> float:
    """
    Supplier-side APR net of the reserve factor, in pct.

    Suppliers earn the borrow interest only on the utilised fraction of their
    deposits, less the protocol reserve cut::

        supply_apr = borrow_apr * (utilization/100) * (1 - reserve_factor/100)

    Defensive: utilization and reserve factor are clamped to sane ranges so the
    multipliers stay in [0, 1].
    """
    util_frac = _clamp(utilization_pct, 0.0, 100.0) / 100.0
    reserve_frac = _clamp(reserve_factor_pct, 0.0, 100.0) / 100.0
    return borrow_apr_now_pct * util_frac * (1.0 - reserve_frac)


def _liquidity_buffer_pct(
    available_liquidity_usd: float,
    total_supplied_usd: float,
    utilization_pct: float,
) -> float:
    """
    Available liquidity as a share of total supply, in pct.

        buffer = available_liquidity / total_supplied * 100

    Defensive: when both USD figures are ~0 (no balance-sheet data supplied) we
    fall back to (100 - utilization_pct) as a proxy for the un-utilised share,
    which is economically the headroom a supplier could withdraw against.
    """
    avail = max(0.0, available_liquidity_usd)
    supplied = max(0.0, total_supplied_usd)
    if avail <= _EPS and supplied <= _EPS:
        return _clamp(100.0 - utilization_pct, 0.0, 100.0)
    if supplied <= _EPS:
        return 100.0
    return _clamp(avail / supplied * 100.0, 0.0, 100.0)


def _kink_proximity_score(
    utilization_pct: float,
    kink_utilization_pct: float,
    utilization_headroom_pct: float,
    liquidity_buffer_pct: float,
    rate_shock_if_crossed_pct: float,
    has_data: bool,
) -> float:
    """
    0-100: higher = SAFER / more headroom before the steep regime.

    Blends three drivers:
    - headroom-share (0-50): how much of the runway to the kink is still
      unused, expressed as headroom / kink. A position past the kink scores 0
      on this component.
    - liquidity-buffer (0-30): the available-vs-supply buffer (bigger is
      safer); a supplier with a thick buffer can still exit.
    - inverse rate-shock-exposure (0-20): one minus the fraction of the
      embedded second-slope shock the market is exposed to, scaled against a
      reference shock. A small / absent shock contributes the full 20.

    A position **past the kink** is forced low: the headroom component is 0 and
    an extra penalty caps the score so it cannot read as "safe".

    Returns 0.0 when there is no usable data.
    """
    if not has_data:
        return 0.0

    kink = max(kink_utilization_pct, _EPS)

    # Headroom share (0..1): unused runway to the kink.
    headroom_share = _clamp(utilization_headroom_pct / kink, 0.0, 1.0)
    headroom_component = headroom_share * 50.0

    # Liquidity buffer (0..1).
    buffer_share = _clamp(liquidity_buffer_pct / 100.0, 0.0, 1.0)
    buffer_component = buffer_share * 30.0

    # Inverse rate-shock exposure: scale the embedded shock against a reference
    # (the LARGE_RATE_SHOCK threshold). A bigger shock => smaller component.
    shock_exposure = _clamp(
        rate_shock_if_crossed_pct / max(_LARGE_RATE_SHOCK_PCT, _EPS), 0.0, 1.0)
    shock_component = (1.0 - shock_exposure) * 20.0

    score = headroom_component + buffer_component + shock_component

    # Past the kink is never "safe": cap hard.
    if utilization_pct > kink_utilization_pct:
        score = min(score, 25.0)

    return _clamp(score)


def _classify(
    utilization_pct: float,
    kink_utilization_pct: float,
    has_data: bool,
) -> str:
    """
    Assign an advisory classification band, driven by utilization vs kink.

    Bands (on headroom_ratio = utilization / kink):
      < 0.60  -> AMPLE_HEADROOM
      < 0.85  -> COMFORTABLE
      < 0.98  -> APPROACHING_KINK
      <= 1.00 -> AT_KINK
      > 1.00  -> PAST_KINK

    No data falls back to AMPLE_HEADROOM (no proximity can be demonstrated).
    A non-positive kink is treated as PAST_KINK whenever utilization is above
    it (degenerate steep-from-zero curve).
    """
    if not has_data:
        return CLASS_AMPLE_HEADROOM

    if kink_utilization_pct <= 0.0:
        return CLASS_PAST_KINK if utilization_pct > 0.0 else CLASS_AT_KINK

    ratio = utilization_pct / kink_utilization_pct

    if ratio > 1.0:
        return CLASS_PAST_KINK
    if ratio >= _AT_KINK_PROXIMITY:
        return CLASS_AT_KINK
    if ratio < 0.60:
        return CLASS_AMPLE_HEADROOM
    if ratio < 0.85:
        return CLASS_COMFORTABLE
    return CLASS_APPROACHING_KINK


def _grade(kink_proximity_score: float) -> str:
    """Map kink_proximity_score (higher = safer) to an A-F letter grade."""
    s = kink_proximity_score
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
    utilization_pct: float,
    kink_utilization_pct: float,
    utilization_headroom_pct: float,
    liquidity_buffer_pct: float,
    slope2_pct: float,
    rate_shock_if_crossed_pct: float,
    classification: str,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if classification == CLASS_PAST_KINK:
        flags.append(FLAG_PAST_KINK)

    if classification == CLASS_AT_KINK:
        flags.append(FLAG_AT_KINK)

    if liquidity_buffer_pct < _THIN_LIQUIDITY_BUFFER_PCT:
        flags.append(FLAG_THIN_LIQUIDITY_BUFFER)

    if slope2_pct >= _STEEP_SECOND_SLOPE_PCT:
        flags.append(FLAG_STEEP_SECOND_SLOPE)

    if rate_shock_if_crossed_pct >= _LARGE_RATE_SHOCK_PCT:
        flags.append(FLAG_LARGE_RATE_SHOCK)

    if utilization_headroom_pct >= _AMPLE_HEADROOM_PCT:
        flags.append(FLAG_AMPLE_HEADROOM)

    if utilization_pct < _LOW_UTILIZATION_IDLE_PCT:
        flags.append(FLAG_LOW_UTILIZATION_IDLE)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    utilization_pct: float,
    kink_utilization_pct: float,
    utilization_headroom_pct: float,
    rate_shock_if_crossed_pct: float,
    supply_apr_now_pct: float,
    liquidity_buffer_pct: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: no utilization signal and/or data marked "
            "unreliable. Cannot assess kink proximity for this market."
        )
        return recs

    if classification == CLASS_PAST_KINK:
        recs.append(
            f"Past the kink: utilization {utilization_pct:.2f}% exceeds the "
            f"{kink_utilization_pct:.2f}% optimum. The market is in the steep "
            "second-slope regime; borrow costs are elevated and supplier "
            "withdrawals may be constrained until utilization falls."
        )
    elif classification == CLASS_AT_KINK:
        recs.append(
            f"At the kink: utilization {utilization_pct:.2f}% is essentially "
            f"at the {kink_utilization_pct:.2f}% optimum. One more borrow "
            "tips the market into the steep regime; monitor closely."
        )
    elif classification == CLASS_APPROACHING_KINK:
        recs.append(
            f"Approaching the kink: utilization {utilization_pct:.2f}% is "
            f"closing on the {kink_utilization_pct:.2f}% optimum with only "
            f"~{utilization_headroom_pct:.2f} points of headroom left."
        )
    elif classification == CLASS_COMFORTABLE:
        recs.append(
            f"Comfortable: utilization {utilization_pct:.2f}% sits a healthy "
            f"~{utilization_headroom_pct:.2f} points below the "
            f"{kink_utilization_pct:.2f}% kink."
        )
    else:  # AMPLE_HEADROOM
        recs.append(
            f"Ample headroom: utilization {utilization_pct:.2f}% leaves "
            f"~{utilization_headroom_pct:.2f} points before the "
            f"{kink_utilization_pct:.2f}% kink. Borrow-rate stability is high."
        )

    if FLAG_LARGE_RATE_SHOCK in flags:
        recs.append(
            f"Large embedded rate shock: crossing the kink would add "
            f"~{rate_shock_if_crossed_pct:.2f} points of borrow APR up to "
            "100% utilization. Carry can deteriorate quickly if utilization "
            "rises."
        )

    if FLAG_STEEP_SECOND_SLOPE in flags:
        recs.append(
            "Steep second slope: this market's rate model punishes "
            "over-utilization aggressively; suppliers benefit from spikes but "
            "borrowers (and looped positions) are exposed."
        )

    if FLAG_THIN_LIQUIDITY_BUFFER in flags:
        recs.append(
            f"Thin liquidity buffer: only ~{liquidity_buffer_pct:.2f}% of "
            "supply is currently withdrawable. Exiting size may be difficult "
            "without moving the rate."
        )

    if FLAG_LOW_UTILIZATION_IDLE in flags:
        recs.append(
            f"Low utilization: at {utilization_pct:.2f}% a large share of "
            "deposits is idle, dragging the supply APR down to "
            f"~{supply_apr_now_pct:.2f}%. Capital is under-deployed here."
        )

    if FLAG_AMPLE_HEADROOM in flags and classification in (
        CLASS_AMPLE_HEADROOM, CLASS_COMFORTABLE
    ):
        recs.append(
            "Ample headroom remains before the kink: borrow-rate stability is "
            "favourable for both suppliers and looped borrowers."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    token: dict | None = None,
    config: dict | None = None,
    *,
    utilization_pct: float | None = None,
    kink_utilization_pct: float | None = None,
    base_rate_pct: float | None = None,
    slope1_pct: float | None = None,
    slope2_pct: float | None = None,
    reserve_factor_pct: float | None = None,
    available_liquidity_usd: float | None = None,
    total_supplied_usd: float | None = None,
    data_quality: Any = None,
    name: str | None = None,
) -> dict:
    """
    Analyse the kink proximity of a single kinked lending market.

    Inputs may be supplied as a ``token`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    Recognised keys / keywords (all with safe defaults):
    - name                    : str
    - utilization_pct         : float (0-100, current utilization)
    - kink_utilization_pct    : float (optimal utilization, default 80.0)
    - base_rate_pct           : float (borrow APR at 0% util, default 0.0)
    - slope1_pct              : float (borrow APR added 0 -> kink, default 4.0)
    - slope2_pct              : float (extra APR kink -> 100%, default 60.0)
    - reserve_factor_pct      : float (default 10.0)
    - available_liquidity_usd : float
    - total_supplied_usd      : float
    - data_quality            : truthy/"ok" => trusted; falsy/"poor" => not

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

    util = _clamp(_pick(utilization_pct, "utilization_pct", 0.0), 0.0, 100.0)
    kink = _clamp(
        _pick(kink_utilization_pct, "kink_utilization_pct",
              _DEFAULT_KINK_UTILIZATION_PCT),
        0.0, 100.0,
    )
    base = _pick(base_rate_pct, "base_rate_pct", _DEFAULT_BASE_RATE_PCT)
    slope1 = _pick(slope1_pct, "slope1_pct", _DEFAULT_SLOPE1_PCT)
    slope2 = _pick(slope2_pct, "slope2_pct", _DEFAULT_SLOPE2_PCT)
    reserve = _clamp(
        _pick(reserve_factor_pct, "reserve_factor_pct",
              _DEFAULT_RESERVE_FACTOR_PCT),
        0.0, 100.0,
    )
    avail = max(0.0, _pick(available_liquidity_usd, "available_liquidity_usd", 0.0))
    supplied = max(0.0, _pick(total_supplied_usd, "total_supplied_usd", 0.0))

    dq_raw = data_quality if data_quality is not None else t.get("data_quality", "ok")
    if isinstance(dq_raw, str):
        data_quality_ok = dq_raw.strip().lower() not in ("poor", "bad", "low", "")
    else:
        data_quality_ok = bool(dq_raw)

    # Data sufficiency: need a utilization or liquidity signal, and the
    # data-quality flag must not mark the inputs as unreliable.
    has_signal = (
        abs(util) > _EPS
        or avail > _EPS
        or supplied > _EPS
    )
    has_data = has_signal and data_quality_ok

    headroom = _utilization_headroom_pct(util, kink)
    apr_now = _borrow_apr_at_util(util, kink, base, slope1, slope2)
    apr_at_kink = _borrow_apr_at_util(kink, kink, base, slope1, slope2)
    apr_at_full = _borrow_apr_at_util(100.0, kink, base, slope1, slope2)
    rate_shock = _rate_shock_if_crossed_pct(apr_at_kink, apr_at_full)
    supply_apr = _supply_apr_now_pct(apr_now, util, reserve)
    liq_buffer = _liquidity_buffer_pct(avail, supplied, util)
    classification = _classify(util, kink, has_data)
    proximity = _kink_proximity_score(
        util, kink, headroom, liq_buffer, rate_shock, has_data
    )
    grade = _grade(proximity)
    flags = _flags(
        util,
        kink,
        headroom,
        liq_buffer,
        slope2,
        rate_shock,
        classification,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        util,
        kink,
        headroom,
        rate_shock,
        supply_apr,
        liq_buffer,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "utilization_pct": util,
        "kink_utilization_pct": kink,
        "base_rate_pct": base,
        "slope1_pct": slope1,
        "slope2_pct": slope2,
        "reserve_factor_pct": reserve,
        "available_liquidity_usd": avail,
        "total_supplied_usd": supplied,
        "data_quality_ok": data_quality_ok,
        "utilization_headroom_pct": headroom,
        "projected_borrow_apr_now_pct": apr_now,
        "projected_borrow_apr_at_kink_pct": apr_at_kink,
        "projected_borrow_apr_at_full_pct": apr_at_full,
        "rate_shock_if_crossed_pct": rate_shock,
        "supply_apr_now_pct": supply_apr,
        "liquidity_buffer_pct": liq_buffer,
        "kink_proximity_score": proximity,
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
    Analyse kink proximity across a batch of markets and summarise.

    Returns
    -------
    dict
        - total_positions          : int
        - results                  : list[dict]  (per-market analysis)
        - safest_market            : str | None  (highest proximity score)
        - riskiest_market          : str | None  (lowest proximity score)
        - avg_kink_proximity_score : float
        - past_kink_count          : int
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
            "safest_market": None,
            "riskiest_market": None,
            "avg_kink_proximity_score": 0.0,
            "past_kink_count": 0,
            "timestamp": time.time(),
        }

    safest = max(results, key=lambda r: r["kink_proximity_score"])
    riskiest = min(results, key=lambda r: r["kink_proximity_score"])
    avg = sum(r["kink_proximity_score"] for r in results) / total
    past_kink = sum(
        1 for r in results if r["classification"] == CLASS_PAST_KINK
    )

    return {
        "total_positions": total,
        "results": results,
        "safest_market": safest["name"],
        "riskiest_market": riskiest["name"],
        "avg_kink_proximity_score": avg,
        "past_kink_count": past_kink,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class ProtocolDeFiInterestRateKinkProximityAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = ProtocolDeFiInterestRateKinkProximityAnalyzer()
    >>> r = a.analyze({"name": "USDC", "utilization_pct": 92.0})
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
            "name": "USDC (past kink)",
            "utilization_pct": 94.0,
            "kink_utilization_pct": 80.0,
            "base_rate_pct": 0.0,
            "slope1_pct": 4.0,
            "slope2_pct": 60.0,
            "reserve_factor_pct": 10.0,
            "available_liquidity_usd": 6000000.0,
            "total_supplied_usd": 100000000.0,
        },
        {
            "name": "ETH (ample headroom)",
            "utilization_pct": 35.0,
            "kink_utilization_pct": 80.0,
            "base_rate_pct": 0.0,
            "slope1_pct": 4.0,
            "slope2_pct": 60.0,
            "reserve_factor_pct": 15.0,
            "available_liquidity_usd": 65000000.0,
            "total_supplied_usd": 100000000.0,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_markets[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_markets)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
