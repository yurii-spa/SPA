"""
MP-1091  ProtocolDeFiValidatorSlashingExposureAnalyzer
--------------------------------------------------
Quantify the expected and worst-case slashing loss for a staked / liquid-
staking-token (LST) / restaking position.

A staking position carries slashing risk: validators can lose a fraction of
their stake for downtime (small, common) or — much worse — for correlated /
double-sign faults (large, rare, and tail-correlated across an operator's
validators). Restaking (EigenLayer-style AVS obligations) compounds the
slashing surface by exposing the same stake to additional slashing conditions.
Existing modules cover validator-set decentralization and restaking risk in
general terms, but none translate those risks into a holder's expected
slashing loss and worst-case haircut for a specific position. This module:

  (a) probability-weights downtime and correlated penalties into an expected
      annual slashing loss (pct and USD),
  (b) scales the correlated penalty by operator/validator concentration into a
      worst-case haircut,
  (c) measures how much of the expected loss comes from the correlated tail,
  (d) amplifies the slashing surface for restaking layers, and
  (e) offsets exposure by any insurance coverage, then scores the risk.

The module returns:
- expected_annual_slashing_loss_pct   – probability-weighted annual loss
- expected_annual_slashing_loss_usd   – the same in USD
- worst_case_haircut_pct              – concentration-scaled correlated penalty
- correlated_loss_contribution_pct    – share of expected loss from the tail
- restaking_amplification_factor      – >= 1.0, slashing-surface multiplier
- effective_exposure_after_insurance_pct – exposure net of insurance
- slashing_risk_score                 – 0-100, higher = riskier
- classification                      – MINIMAL .. SEVERE
- grade                               – A-F letter grade
- flags / recommendations             – advisory verdicts

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
    "validator_slashing_exposure_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Each restaking layer adds this fraction of slashing surface (compounding).
_RESTAKING_LAYER_AMPLIFICATION = 0.35

# Classification bands
CLASS_MINIMAL = "MINIMAL"
CLASS_LOW = "LOW"
CLASS_MODERATE = "MODERATE"
CLASS_HIGH = "HIGH"
CLASS_SEVERE = "SEVERE"

ALL_CLASSIFICATIONS = (
    CLASS_MINIMAL,
    CLASS_LOW,
    CLASS_MODERATE,
    CLASS_HIGH,
    CLASS_SEVERE,
)

# Flags
FLAG_HIGH_OPERATOR_CONCENTRATION = "HIGH_OPERATOR_CONCENTRATION"
FLAG_SINGLE_VALIDATOR = "SINGLE_VALIDATOR"
FLAG_HIGH_CORRELATED_RISK = "HIGH_CORRELATED_RISK"
FLAG_RESTAKING_AMPLIFIED = "RESTAKING_AMPLIFIED"
FLAG_UNINSURED = "UNINSURED"
FLAG_LARGE_WORST_CASE_HAIRCUT = "LARGE_WORST_CASE_HAIRCUT"
FLAG_WELL_DIVERSIFIED = "WELL_DIVERSIFIED"
FLAG_LOW_SLASHING_HISTORY = "LOW_SLASHING_HISTORY"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_HIGH_OPERATOR_CONCENTRATION,
    FLAG_SINGLE_VALIDATOR,
    FLAG_HIGH_CORRELATED_RISK,
    FLAG_RESTAKING_AMPLIFIED,
    FLAG_UNINSURED,
    FLAG_LARGE_WORST_CASE_HAIRCUT,
    FLAG_WELL_DIVERSIFIED,
    FLAG_LOW_SLASHING_HISTORY,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds
_HIGH_OPERATOR_CONCENTRATION_PCT = 50.0   # largest operator >= 50% is high
_WELL_DIVERSIFIED_VALIDATORS = 20.0       # >= 20 validators is well diversified
_WELL_DIVERSIFIED_OPERATOR_PCT = 20.0     # operator share <= 20% is diversified
_HIGH_CORRELATED_PROB = 0.01              # >= 1%/yr correlated prob is high
_LARGE_WORST_CASE_PCT = 30.0              # worst-case haircut >= 30% is large
_LOW_SLASHING_HISTORY_PROB = 0.001        # combined slash prob < 0.1% is low
_UNINSURED_PCT = 1.0                      # < 1% insurance is effectively none


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

def _restaking_amplification_factor(restaking_layers: float) -> float:
    """
    Slashing-surface multiplier from restaking layers, >= 1.0.

    Each restaking layer exposes the same stake to an additional set of
    slashing conditions::

        factor = 1 + layers * _RESTAKING_LAYER_AMPLIFICATION

    Negative layer counts are treated as 0 (factor 1.0).
    """
    layers = max(0.0, restaking_layers)
    return 1.0 + layers * _RESTAKING_LAYER_AMPLIFICATION


def _expected_annual_slashing_loss_pct(
    annual_downtime_slash_prob: float,
    downtime_penalty_pct: float,
    annual_correlated_slash_prob: float,
    correlated_penalty_pct: float,
    restaking_amplification_factor: float,
) -> float:
    """
    Probability-weighted expected annual slashing loss, in pct of position.

    expected = (p_downtime * downtime_penalty + p_correlated * correlated_penalty)
               * restaking_amplification_factor

    Probabilities are clamped to [0, 1] and penalties floored at 0. The result
    is clamped to [0, 100] (cannot lose more than the whole position).
    """
    p_down = _clamp(annual_downtime_slash_prob, 0.0, 1.0)
    p_corr = _clamp(annual_correlated_slash_prob, 0.0, 1.0)
    down_pen = max(0.0, downtime_penalty_pct)
    corr_pen = max(0.0, correlated_penalty_pct)

    base = p_down * down_pen + p_corr * corr_pen
    return _clamp(base * max(1.0, restaking_amplification_factor))


def _expected_annual_slashing_loss_usd(
    expected_annual_slashing_loss_pct: float,
    position_value_usd: float,
) -> float:
    """
    Expected annual slashing loss in USD.

    Returns 0.0 when the position value is <= 0 (avoids negative loss).
    """
    if position_value_usd <= 0:
        return 0.0
    return expected_annual_slashing_loss_pct / 100.0 * position_value_usd


def _worst_case_haircut_pct(
    correlated_penalty_pct: float,
    operator_concentration_pct: float,
    num_validators: float,
    restaking_amplification_factor: float,
) -> float:
    """
    Worst-case slashing haircut, in pct of position.

    A correlated fault hits an operator's validators together. The more
    concentrated the stake (high operator share, few validators), the closer
    the haircut is to the full correlated penalty; well-spread stake limits the
    haircut to the affected slice::

        concentration_frac = max(operator_share, 1/num_validators)
        haircut = correlated_penalty * concentration_frac * amplification

    Clamped to [0, 100].
    """
    corr_pen = max(0.0, correlated_penalty_pct)

    op_frac = _clamp(operator_concentration_pct, 0.0, 100.0) / 100.0

    if num_validators >= 1.0:
        validator_frac = 1.0 / num_validators
    else:
        # Unknown / zero validators → assume fully concentrated.
        validator_frac = 1.0

    concentration_frac = max(op_frac, validator_frac)
    concentration_frac = max(0.0, min(1.0, concentration_frac))

    haircut = corr_pen * concentration_frac * max(1.0, restaking_amplification_factor)
    return _clamp(haircut)


def _correlated_loss_contribution_pct(
    annual_correlated_slash_prob: float,
    correlated_penalty_pct: float,
    annual_downtime_slash_prob: float,
    downtime_penalty_pct: float,
) -> float:
    """
    Share of expected loss attributable to correlated (tail) events, in pct.

    correlated_component = p_correlated * correlated_penalty
    downtime_component   = p_downtime * downtime_penalty
    contribution = correlated_component / (correlated + downtime) * 100

    Returns 0.0 when total expected loss is ~0 (avoids div-by-zero).
    """
    p_corr = _clamp(annual_correlated_slash_prob, 0.0, 1.0)
    p_down = _clamp(annual_downtime_slash_prob, 0.0, 1.0)
    corr_component = p_corr * max(0.0, correlated_penalty_pct)
    down_component = p_down * max(0.0, downtime_penalty_pct)
    total = corr_component + down_component
    if total <= _EPS:
        return 0.0
    return _clamp(corr_component / total * 100.0)


def _effective_exposure_after_insurance_pct(
    expected_annual_slashing_loss_pct: float,
    insurance_coverage_pct: float,
) -> float:
    """
    Expected slashing loss net of insurance coverage, in pct.

    effective = expected_loss * (1 - insurance_coverage/100)

    Insurance coverage is clamped to [0, 100]; result floored at 0.
    """
    coverage = _clamp(insurance_coverage_pct, 0.0, 100.0) / 100.0
    return max(0.0, expected_annual_slashing_loss_pct * (1.0 - coverage))


def _slashing_risk_score(
    expected_annual_slashing_loss_pct: float,
    worst_case_haircut_pct: float,
    operator_concentration_pct: float,
    correlated_loss_contribution_pct: float,
    effective_exposure_after_insurance_pct: float,
    has_data: bool,
) -> float:
    """
    0-100: higher = riskier.

    Blends:
    - effective expected loss (0-35): scaled so 5%+ expected loss saturates,
    - worst-case haircut (0-30): scaled so a full correlated penalty saturates,
    - operator concentration (0-20): the structural driver of correlation,
    - correlated-tail share (0-15): fat tails are riskier than steady downtime.

    Returns 0.0 when there is no usable data.
    """
    if not has_data:
        return 0.0

    # Effective expected loss: 5% annual expected loss is treated as "full".
    loss_frac = _clamp(effective_exposure_after_insurance_pct / 5.0, 0.0, 1.0)
    loss_component = loss_frac * 35.0

    haircut_frac = _clamp(worst_case_haircut_pct / 100.0, 0.0, 1.0)
    haircut_component = haircut_frac * 30.0

    concentration_frac = _clamp(operator_concentration_pct / 100.0, 0.0, 1.0)
    concentration_component = concentration_frac * 20.0

    tail_frac = _clamp(correlated_loss_contribution_pct / 100.0, 0.0, 1.0)
    tail_component = tail_frac * 15.0

    return _clamp(
        loss_component
        + haircut_component
        + concentration_component
        + tail_component
    )


def _classify(
    slashing_risk_score: float,
    has_data: bool,
) -> str:
    """
    Assign an advisory classification band, driven by the risk score.

    Bands (on slashing_risk_score):
      < 15  → MINIMAL
      < 35  → LOW
      < 55  → MODERATE
      < 75  → HIGH
      >= 75 → SEVERE

    No data falls back to MINIMAL (no slashing exposure can be demonstrated).
    """
    if not has_data:
        return CLASS_MINIMAL

    s = slashing_risk_score
    if s < 15.0:
        return CLASS_MINIMAL
    if s < 35.0:
        return CLASS_LOW
    if s < 55.0:
        return CLASS_MODERATE
    if s < 75.0:
        return CLASS_HIGH
    return CLASS_SEVERE


def _grade(slashing_risk_score: float) -> str:
    """Map slashing_risk_score (higher = riskier) to an A-F letter grade."""
    s = slashing_risk_score
    if s < 10.0:
        return "A"
    if s < 30.0:
        return "B"
    if s < 50.0:
        return "C"
    if s < 70.0:
        return "D"
    return "F"


def _flags(
    operator_concentration_pct: float,
    num_validators: float,
    annual_correlated_slash_prob: float,
    restaking_amplification_factor: float,
    insurance_coverage_pct: float,
    worst_case_haircut_pct: float,
    annual_downtime_slash_prob: float,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if operator_concentration_pct >= _HIGH_OPERATOR_CONCENTRATION_PCT:
        flags.append(FLAG_HIGH_OPERATOR_CONCENTRATION)

    if 0.0 < num_validators <= 1.0:
        flags.append(FLAG_SINGLE_VALIDATOR)

    if annual_correlated_slash_prob >= _HIGH_CORRELATED_PROB:
        flags.append(FLAG_HIGH_CORRELATED_RISK)

    if restaking_amplification_factor > 1.0 + _EPS:
        flags.append(FLAG_RESTAKING_AMPLIFIED)

    if insurance_coverage_pct < _UNINSURED_PCT:
        flags.append(FLAG_UNINSURED)

    if worst_case_haircut_pct >= _LARGE_WORST_CASE_PCT:
        flags.append(FLAG_LARGE_WORST_CASE_HAIRCUT)

    if (
        num_validators >= _WELL_DIVERSIFIED_VALIDATORS
        and 0.0 < operator_concentration_pct <= _WELL_DIVERSIFIED_OPERATOR_PCT
    ):
        flags.append(FLAG_WELL_DIVERSIFIED)

    combined_prob = (
        _clamp(annual_downtime_slash_prob, 0.0, 1.0)
        + _clamp(annual_correlated_slash_prob, 0.0, 1.0)
    )
    if combined_prob < _LOW_SLASHING_HISTORY_PROB:
        flags.append(FLAG_LOW_SLASHING_HISTORY)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    expected_annual_slashing_loss_pct: float,
    worst_case_haircut_pct: float,
    correlated_loss_contribution_pct: float,
    effective_exposure_after_insurance_pct: float,
    restaking_amplification_factor: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: position_value_usd <= 0 or no slashing "
            "probabilities supplied. Cannot assess slashing exposure."
        )
        return recs

    if classification == CLASS_SEVERE:
        recs.append(
            f"SEVERE slashing exposure: expected annual loss "
            f"~{expected_annual_slashing_loss_pct:.2f}% with a worst-case "
            f"haircut of ~{worst_case_haircut_pct:.0f}%. Reduce or diversify "
            "this position."
        )
    elif classification == CLASS_HIGH:
        recs.append(
            f"High slashing exposure: expected annual loss "
            f"~{expected_annual_slashing_loss_pct:.2f}%, worst-case haircut "
            f"~{worst_case_haircut_pct:.0f}%. Size the position for a tail "
            "event."
        )
    elif classification == CLASS_MODERATE:
        recs.append(
            f"Moderate slashing exposure: expected annual loss "
            f"~{expected_annual_slashing_loss_pct:.2f}%. Monitor operator "
            "concentration and restaking obligations."
        )
    elif classification == CLASS_LOW:
        recs.append(
            f"Low slashing exposure: expected annual loss "
            f"~{expected_annual_slashing_loss_pct:.2f}%. Risk is contained but "
            "not zero."
        )
    else:  # MINIMAL
        recs.append(
            f"Minimal slashing exposure: expected annual loss "
            f"~{expected_annual_slashing_loss_pct:.2f}%. The position is well "
            "spread with little correlated risk."
        )

    if FLAG_HIGH_OPERATOR_CONCENTRATION in flags:
        recs.append(
            "High operator concentration: a single operator controls a large "
            "share of the stake, so a correlated fault could slash most of the "
            "position at once."
        )

    if FLAG_SINGLE_VALIDATOR in flags:
        recs.append(
            "Single validator: the entire stake sits behind one validator with "
            "no diversification against a slashing event."
        )

    if FLAG_HIGH_CORRELATED_RISK in flags:
        recs.append(
            f"Elevated correlated-fault probability: the tail dominates "
            f"(~{correlated_loss_contribution_pct:.0f}% of expected loss). "
            "Double-sign / correlated penalties are large and hard to recover."
        )

    if FLAG_RESTAKING_AMPLIFIED in flags:
        recs.append(
            f"Restaking amplifies the slashing surface "
            f"(x{restaking_amplification_factor:.2f}): the same stake is exposed "
            "to multiple AVS slashing conditions simultaneously."
        )

    if FLAG_UNINSURED in flags:
        recs.append(
            f"Effectively uninsured: ~{effective_exposure_after_insurance_pct:.2f}% "
            "expected loss is borne directly with no coverage offset."
        )

    if FLAG_LARGE_WORST_CASE_HAIRCUT in flags:
        recs.append(
            f"Large worst-case haircut (~{worst_case_haircut_pct:.0f}%): a single "
            "correlated event could remove a substantial fraction of the "
            "position."
        )

    if FLAG_WELL_DIVERSIFIED in flags:
        recs.append(
            "Well diversified across validators and operators, which limits the "
            "correlated-slashing haircut to a small slice of the position."
        )

    if FLAG_LOW_SLASHING_HISTORY in flags:
        recs.append(
            "Low historical slashing probability: the supplied fault rates are "
            "small, keeping expected loss low under current assumptions."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    position: dict | None = None,
    config: dict | None = None,
    *,
    position_value_usd: float | None = None,
    num_validators: float | None = None,
    operator_concentration_pct: float | None = None,
    annual_downtime_slash_prob: float | None = None,
    annual_correlated_slash_prob: float | None = None,
    downtime_penalty_pct: float | None = None,
    correlated_penalty_pct: float | None = None,
    restaking_layers: float | None = None,
    insurance_coverage_pct: float | None = None,
    data_quality: Any = None,
    name: str | None = None,
) -> dict:
    """
    Analyse the slashing exposure of a single staking / LST / restaking position.

    Inputs may be supplied as a ``position`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    Recognised keys / keywords (all with safe defaults):
    - name                          : str
    - position_value_usd            : float (>= 0)
    - num_validators                : float (>= 0, stake spread)
    - operator_concentration_pct    : float (largest operator's share, 0-100)
    - annual_downtime_slash_prob    : float (0-1)
    - annual_correlated_slash_prob  : float (0-1)
    - downtime_penalty_pct          : float (penalty per downtime event)
    - correlated_penalty_pct        : float (penalty per correlated event)
    - restaking_layers              : float (>= 0, extra AVS obligations)
    - insurance_coverage_pct        : float (0-100, optional offset)
    - data_quality                  : truthy/"ok" => trusted; falsy/"poor" => not

    config : dict, optional
        - log_path : str  (override default log path)

    Returns
    -------
    dict
        Full analysis result. Never raises to the caller.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    p = position if isinstance(position, dict) else {}

    def _pick(kw: Any, key: str, default: float) -> float:
        if kw is not None:
            return _safe_float(kw, default)
        return _safe_float(p.get(key, default), default)

    name_val = name if name is not None else str(p.get("name", "UNKNOWN"))

    position_value = max(0.0, _pick(position_value_usd, "position_value_usd", 0.0))
    num_vals = max(0.0, _pick(num_validators, "num_validators", 1.0))
    operator_conc = _clamp(_pick(
        operator_concentration_pct, "operator_concentration_pct", 0.0), 0.0, 100.0)
    p_downtime = _clamp(_pick(
        annual_downtime_slash_prob, "annual_downtime_slash_prob", 0.0), 0.0, 1.0)
    p_correlated = _clamp(_pick(
        annual_correlated_slash_prob, "annual_correlated_slash_prob", 0.0), 0.0, 1.0)
    downtime_penalty = max(0.0, _pick(
        downtime_penalty_pct, "downtime_penalty_pct", 0.0))
    correlated_penalty = max(0.0, _pick(
        correlated_penalty_pct, "correlated_penalty_pct", 0.0))
    layers = max(0.0, _pick(restaking_layers, "restaking_layers", 0.0))
    insurance = _clamp(_pick(
        insurance_coverage_pct, "insurance_coverage_pct", 0.0), 0.0, 100.0)

    dq_raw = data_quality if data_quality is not None else p.get("data_quality", "ok")
    if isinstance(dq_raw, str):
        data_quality_ok = dq_raw.strip().lower() not in ("poor", "bad", "low", "")
    else:
        data_quality_ok = bool(dq_raw)

    # Data sufficiency: need a positive position value and some slashing signal
    # (a non-zero probability or penalty), and trustworthy data.
    has_signal = position_value > 0 and (
        p_downtime > 0.0
        or p_correlated > 0.0
        or downtime_penalty > 0.0
        or correlated_penalty > 0.0
    )
    has_data = has_signal and data_quality_ok

    amplification = _restaking_amplification_factor(layers)
    expected_pct = _expected_annual_slashing_loss_pct(
        p_downtime, downtime_penalty, p_correlated, correlated_penalty,
        amplification,
    )
    expected_usd = _expected_annual_slashing_loss_usd(expected_pct, position_value)
    worst_case = _worst_case_haircut_pct(
        correlated_penalty, operator_conc, num_vals, amplification
    )
    correlated_contribution = _correlated_loss_contribution_pct(
        p_correlated, correlated_penalty, p_downtime, downtime_penalty
    )
    effective_exposure = _effective_exposure_after_insurance_pct(
        expected_pct, insurance
    )
    risk = _slashing_risk_score(
        expected_pct, worst_case, operator_conc, correlated_contribution,
        effective_exposure, has_data,
    )
    classification = _classify(risk, has_data)
    grade = _grade(risk)
    flags = _flags(
        operator_conc,
        num_vals,
        p_correlated,
        amplification,
        insurance,
        worst_case,
        p_downtime,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        expected_pct,
        worst_case,
        correlated_contribution,
        effective_exposure,
        amplification,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "position_value_usd": position_value,
        "num_validators": num_vals,
        "operator_concentration_pct": operator_conc,
        "annual_downtime_slash_prob": p_downtime,
        "annual_correlated_slash_prob": p_correlated,
        "downtime_penalty_pct": downtime_penalty,
        "correlated_penalty_pct": correlated_penalty,
        "restaking_layers": layers,
        "insurance_coverage_pct": insurance,
        "data_quality_ok": data_quality_ok,
        "restaking_amplification_factor": amplification,
        "expected_annual_slashing_loss_pct": expected_pct,
        "expected_annual_slashing_loss_usd": expected_usd,
        "worst_case_haircut_pct": worst_case,
        "correlated_loss_contribution_pct": correlated_contribution,
        "effective_exposure_after_insurance_pct": effective_exposure,
        "slashing_risk_score": risk,
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
    Analyse slashing exposure across a batch of positions and summarise.

    Returns
    -------
    dict
        - total_positions             : int
        - results                     : list[dict]  (per-position analysis)
        - most_exposed_position       : str | None  (highest slashing risk)
        - least_exposed_position      : str | None  (lowest slashing risk)
        - avg_slashing_risk_score     : float
        - severe_count                : int
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
            "most_exposed_position": None,
            "least_exposed_position": None,
            "avg_slashing_risk_score": 0.0,
            "severe_count": 0,
            "timestamp": time.time(),
        }

    most = max(results, key=lambda r: r["slashing_risk_score"])
    least = min(results, key=lambda r: r["slashing_risk_score"])
    avg = sum(r["slashing_risk_score"] for r in results) / total
    severe = sum(
        1 for r in results if r["classification"] == CLASS_SEVERE
    )

    return {
        "total_positions": total,
        "results": results,
        "most_exposed_position": most["name"],
        "least_exposed_position": least["name"],
        "avg_slashing_risk_score": avg,
        "severe_count": severe,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class ProtocolDeFiValidatorSlashingExposureAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = ProtocolDeFiValidatorSlashingExposureAnalyzer()
    >>> r = a.analyze({"name": "stETH", "position_value_usd": 1_000_000, ...})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, position: dict | None = None, **kwargs: Any) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(position, config=self._config, **kwargs)

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
            "name": "Solo restaker (severe)",
            "position_value_usd": 1_000_000.0,
            "num_validators": 1.0,
            "operator_concentration_pct": 100.0,
            "annual_downtime_slash_prob": 0.05,
            "annual_correlated_slash_prob": 0.02,
            "downtime_penalty_pct": 0.5,
            "correlated_penalty_pct": 100.0,
            "restaking_layers": 4.0,
            "insurance_coverage_pct": 0.0,
        },
        {
            "name": "Diversified LST (low)",
            "position_value_usd": 1_000_000.0,
            "num_validators": 500.0,
            "operator_concentration_pct": 8.0,
            "annual_downtime_slash_prob": 0.01,
            "annual_correlated_slash_prob": 0.0005,
            "downtime_penalty_pct": 0.1,
            "correlated_penalty_pct": 50.0,
            "restaking_layers": 0.0,
            "insurance_coverage_pct": 50.0,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_positions[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_positions)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
