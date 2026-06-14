"""
MP-1140  DeFiProtocolStablecoinYieldBasisSpreadAnalyzer
-------------------------------------------------------
Decompose the headline yield of a stablecoin position relative to a risk-free
benchmark (e.g. T-bill / base rate) and judge whether the *excess basis* — the
spread actually paid over the risk-free rate — adequately compensates the
protocol and depeg risk of holding the stablecoin instead of the risk-free
asset.

A stablecoin yield only matters in *excess* of what a risk-free instrument
already pays. An 8% APY when the risk-free rate is 5% is not an "8% return for
the risk" — it is only a *3% excess basis* being paid in exchange for the full
protocol/smart-contract/depeg risk of the stablecoin venue. If that 3% is then
eroded by the expected cost of a depeg, the real compensation for taking on the
risk can be razor-thin (or negative). This module makes that decomposition
explicit.

For a single position the module computes:
- the excess basis (headline APY minus the risk-free rate),
- a basis-to-risk ratio (excess basis divided by a protocol-risk proxy),
- the real excess after a depeg haircut (excess minus the expected cost of a
  depeg over the holding horizon),
- a 0-100 *risk-compensation score* (higher = the spread generously pays for
  the risk taken),
- a classification band, an A-F grade, advisory flags and recommendations.

Genuine gap: existing modules score gas breakeven, lockup discounts, compounding
cadence and net carry, but none isolate the stablecoin yield *over the risk-free
benchmark* to produce an excess-basis decomposition, a basis-to-risk ratio, a
depeg-adjusted real excess and a single risk-compensation score. A grep for
"basis_spread", "benchmark_spread" and "excess_basis" across the analytics
package confirms no existing module covers this angle.

The module returns:
- name / headline_apy_pct / risk_free_rate_pct (input echoes)
- excess_basis_pct                 - headline_apy minus risk_free_rate
- protocol_risk_proxy_pct          - the risk proxy used (input echo)
- basis_to_risk_ratio              - excess_basis / protocol_risk_proxy
- depeg_expected_cost_pct          - expected annualised cost of a depeg
- real_excess_after_depeg_haircut_pct - excess minus the depeg cost
- risk_compensation_score          - 0-100, higher = spread pays for the risk
- classification                   - NEGATIVE_CARRY .. EXCEPTIONAL
- grade                            - A-F letter grade
- flags / recommendations          - advisory verdicts

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
    "stablecoin_yield_basis_spread_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Sentinel for "ratio is effectively infinite" (so JSON stays finite, no
# inf/NaN). Used when the risk proxy is ~0 but the excess basis is positive.
RATIO_SENTINEL_INF = 1e9

# Defaults.
_DEFAULT_RISK_FREE_RATE_PCT = 5.0
_DEFAULT_PROTOCOL_RISK_PROXY_PCT = 3.0
_DEFAULT_DEPEG_PROBABILITY = 0.02       # 2% annualised probability of a depeg
_DEFAULT_DEPEG_SEVERITY_PCT = 20.0      # expected 20% loss given a depeg event
_DEFAULT_HOLDING_DAYS = 365.0
_DAYS_PER_YEAR = 365.0

# Classification bands
CLASS_NEGATIVE_CARRY = "NEGATIVE_CARRY"
CLASS_THIN_SPREAD = "THIN_SPREAD"
CLASS_FAIR = "FAIR"
CLASS_GENEROUS = "GENEROUS"
CLASS_EXCEPTIONAL = "EXCEPTIONAL"

ALL_CLASSIFICATIONS = (
    CLASS_NEGATIVE_CARRY,
    CLASS_THIN_SPREAD,
    CLASS_FAIR,
    CLASS_GENEROUS,
    CLASS_EXCEPTIONAL,
)

# Flags
FLAG_NEGATIVE_EXCESS_BASIS = "NEGATIVE_EXCESS_BASIS"
FLAG_THIN_COMPENSATION = "THIN_COMPENSATION"
FLAG_GENEROUS_CARRY = "GENEROUS_CARRY"
FLAG_HIGH_DEPEG_DRAG = "HIGH_DEPEG_DRAG"
FLAG_BELOW_RISK_FREE = "BELOW_RISK_FREE"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_NEGATIVE_EXCESS_BASIS,
    FLAG_THIN_COMPENSATION,
    FLAG_GENEROUS_CARRY,
    FLAG_HIGH_DEPEG_DRAG,
    FLAG_BELOW_RISK_FREE,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds (module constants)
# basis_to_risk_ratio bands -> classification
_RATIO_THIN = 0.5      # ratio < 0.5 (and positive excess) -> thin spread
_RATIO_FAIR = 1.0      # 0.5..1.0 -> fair
_RATIO_GENEROUS = 2.0  # 1.0..2.0 -> generous; >= 2.0 -> exceptional

# Flag thresholds.
_THIN_COMPENSATION_RATIO = 0.5    # ratio below this is thin
_GENEROUS_CARRY_RATIO = 2.0       # ratio at/above this is generous carry
# depeg drag eats >= 50% of the gross excess basis.
_HIGH_DEPEG_DRAG_SHARE = 0.50


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

def _excess_basis_pct(headline_apy_pct: float, risk_free_rate_pct: float) -> float:
    """
    Excess basis (pct): the spread the position pays over the risk-free rate.

        excess_basis = headline_apy - risk_free_rate

    Can be negative (the position pays less than risk-free).
    """
    return headline_apy_pct - risk_free_rate_pct


def _basis_to_risk_ratio(
    excess_basis_pct: float,
    protocol_risk_proxy_pct: float,
) -> float:
    """
    Excess basis divided by the protocol-risk proxy (a dimensionless ratio).

        ratio = excess_basis / protocol_risk_proxy

    Defensive: when the risk proxy is ~0 the ratio is undefined; we return 0.0
    when the excess basis is also ~0, and a large finite sentinel
    (RATIO_SENTINEL_INF) when the excess basis is positive (spread with no
    measurable risk). A negative excess with a ~0 proxy returns the negative
    sentinel so the sign is preserved.
    """
    proxy = max(0.0, protocol_risk_proxy_pct)
    if proxy <= _EPS:
        if excess_basis_pct > _EPS:
            return RATIO_SENTINEL_INF
        if excess_basis_pct < -_EPS:
            return -RATIO_SENTINEL_INF
        return 0.0
    return excess_basis_pct / proxy


def _depeg_expected_cost_pct(
    depeg_probability: float,
    depeg_severity_pct: float,
    holding_days: float,
) -> float:
    """
    Expected annualised cost of a depeg over the holding horizon, in pct.

        annual_expected = depeg_probability * depeg_severity_pct
        horizon_scaled  = annual_expected * (holding_days / 365)

    The probability is treated as an annualised probability and scaled to the
    holding horizon. Probability is clamped to [0,1]; severity is floored at 0.
    """
    p = _clamp(depeg_probability, 0.0, 1.0)
    sev = max(0.0, depeg_severity_pct)
    days = max(0.0, holding_days)
    annual = p * sev
    return annual * (days / _DAYS_PER_YEAR)


def _real_excess_after_depeg_haircut_pct(
    excess_basis_pct: float,
    depeg_expected_cost_pct: float,
) -> float:
    """Excess basis after subtracting the expected depeg cost (can be <0)."""
    return excess_basis_pct - depeg_expected_cost_pct


def _risk_compensation_score(
    basis_to_risk_ratio: float,
    excess_basis_pct: float,
    real_excess_after_depeg_haircut_pct: float,
    has_data: bool,
) -> float:
    """
    0-100: higher = the spread generously compensates the risk taken.

    Blends three drivers:
    - basis-to-risk ratio (0-55): a ratio of 0 contributes 0, a ratio of 2.0+
      contributes the full 55; linear in between. Negative ratios contribute 0.
    - positive-excess (0-25): full 25 when the gross excess basis is positive,
      0 when it is negative.
    - depeg-survives (0-20): full 20 when the real excess after the depeg
      haircut is still positive, 0 when the haircut pushes it negative.

    Returns 0.0 when there is no usable data.
    """
    if not has_data:
        return 0.0

    # Ratio component (0..55), capped at ratio 2.0.
    ratio_capped = _clamp(basis_to_risk_ratio, 0.0, _GENEROUS_CARRY_RATIO)
    ratio_component = (ratio_capped / _GENEROUS_CARRY_RATIO) * 55.0

    excess_component = 25.0 if excess_basis_pct > _EPS else 0.0

    depeg_component = 20.0 if real_excess_after_depeg_haircut_pct > _EPS else 0.0

    return _clamp(ratio_component + excess_component + depeg_component)


def _classify(
    basis_to_risk_ratio: float,
    excess_basis_pct: float,
    has_data: bool,
) -> str:
    """
    Assign an advisory classification band.

      excess_basis <= 0          -> NEGATIVE_CARRY
      ratio < 0.5                 -> THIN_SPREAD
      ratio < 1.0                 -> FAIR
      ratio < 2.0                 -> GENEROUS
      ratio >= 2.0                -> EXCEPTIONAL

    No data falls back to NEGATIVE_CARRY (cannot demonstrate any spread).
    """
    if not has_data:
        return CLASS_NEGATIVE_CARRY

    if excess_basis_pct <= _EPS:
        return CLASS_NEGATIVE_CARRY

    ratio = basis_to_risk_ratio
    if ratio < _RATIO_THIN:
        return CLASS_THIN_SPREAD
    if ratio < _RATIO_FAIR:
        return CLASS_FAIR
    if ratio < _RATIO_GENEROUS:
        return CLASS_GENEROUS
    return CLASS_EXCEPTIONAL


def _grade(risk_compensation_score: float) -> str:
    """Map risk_compensation_score (higher = better) to an A-F letter grade."""
    s = risk_compensation_score
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
    excess_basis_pct: float,
    headline_apy_pct: float,
    risk_free_rate_pct: float,
    basis_to_risk_ratio: float,
    excess_basis_gross_pct: float,
    depeg_expected_cost_pct: float,
    classification: str,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if excess_basis_pct < 0.0:
        flags.append(FLAG_NEGATIVE_EXCESS_BASIS)

    if headline_apy_pct < risk_free_rate_pct:
        flags.append(FLAG_BELOW_RISK_FREE)

    # Thin compensation: a positive but small ratio.
    if 0.0 < basis_to_risk_ratio < _THIN_COMPENSATION_RATIO:
        flags.append(FLAG_THIN_COMPENSATION)

    if basis_to_risk_ratio >= _GENEROUS_CARRY_RATIO:
        flags.append(FLAG_GENEROUS_CARRY)

    # High depeg drag: the depeg cost eats a big share of the gross excess.
    if (excess_basis_gross_pct > _EPS
            and depeg_expected_cost_pct / excess_basis_gross_pct
            >= _HIGH_DEPEG_DRAG_SHARE):
        flags.append(FLAG_HIGH_DEPEG_DRAG)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    headline_apy_pct: float,
    risk_free_rate_pct: float,
    excess_basis_pct: float,
    basis_to_risk_ratio: float,
    real_excess_after_depeg_haircut_pct: float,
    depeg_expected_cost_pct: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: no headline-APY/risk-free signal or data marked "
            "unreliable. Cannot assess the excess-basis compensation for this "
            "position."
        )
        return recs

    if classification == CLASS_NEGATIVE_CARRY:
        recs.append(
            f"Negative carry: a headline {headline_apy_pct:.2f}% APY pays no "
            f"premium over the {risk_free_rate_pct:.2f}% risk-free rate (excess "
            f"basis ~{excess_basis_pct:.2f}%). The risk-free asset dominates; do "
            "not take on protocol/depeg risk for this."
        )
    elif classification == CLASS_THIN_SPREAD:
        recs.append(
            f"Thin spread: only ~{excess_basis_pct:.2f}% of excess basis is paid "
            "for the full protocol/depeg risk (basis-to-risk ratio "
            f"~{basis_to_risk_ratio:.2f}). The compensation is slim relative to "
            "the risk taken."
        )
    elif classification == CLASS_FAIR:
        recs.append(
            f"Fair spread: ~{excess_basis_pct:.2f}% excess basis roughly matches "
            f"the protocol-risk proxy (ratio ~{basis_to_risk_ratio:.2f}). "
            "Reasonable but not generous compensation."
        )
    elif classification == CLASS_GENEROUS:
        recs.append(
            f"Generous carry: ~{excess_basis_pct:.2f}% excess basis comfortably "
            f"exceeds the protocol-risk proxy (ratio ~{basis_to_risk_ratio:.2f}). "
            "The spread pays well for the risk."
        )
    else:  # EXCEPTIONAL
        recs.append(
            f"Exceptional carry: ~{excess_basis_pct:.2f}% excess basis is a large "
            f"multiple of the protocol-risk proxy (ratio ~{basis_to_risk_ratio:.2f}"
            "). Verify the yield source is sustainable before sizing up."
        )

    if FLAG_BELOW_RISK_FREE in flags:
        recs.append(
            f"Below risk-free: the headline {headline_apy_pct:.2f}% APY is under "
            f"the {risk_free_rate_pct:.2f}% risk-free rate. A T-bill / base-rate "
            "instrument pays more with less risk."
        )

    if FLAG_HIGH_DEPEG_DRAG in flags:
        recs.append(
            f"High depeg drag: the expected depeg cost (~"
            f"{depeg_expected_cost_pct:.2f}%) erodes most of the gross excess "
            f"basis, leaving only ~{real_excess_after_depeg_haircut_pct:.2f}% "
            "real excess. The peg risk is doing the damage, not the headline "
            "rate."
        )

    if FLAG_THIN_COMPENSATION in flags:
        recs.append(
            "Thin compensation: consider a venue with a larger spread or a lower "
            "protocol-risk profile to improve the basis-to-risk ratio."
        )

    if FLAG_GENEROUS_CARRY in flags:
        recs.append(
            "Generous carry: the spread is large relative to the risk proxy — "
            "confirm the risk proxy is not understated before treating this as "
            "free money."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    token: dict | None = None,
    config: dict | None = None,
    *,
    headline_apy_pct: float | None = None,
    risk_free_rate_pct: float | None = None,
    protocol_risk_proxy_pct: float | None = None,
    depeg_probability: float | None = None,
    depeg_severity_pct: float | None = None,
    holding_days: float | None = None,
    data_quality: Any = None,
    name: str | None = None,
) -> dict:
    """
    Analyse the excess-basis compensation of a single stablecoin position.

    Inputs may be supplied as a ``token`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    Recognised keys / keywords (all with safe defaults):
    - name                    : str
    - headline_apy_pct        : float (the advertised stablecoin yield)
    - risk_free_rate_pct      : float (T-bill / base rate benchmark, default 5)
    - protocol_risk_proxy_pct : float (a proxy for protocol/smart-contract risk
                                priced in pct, default 3)
    - depeg_probability       : float (annualised probability of a depeg, 0..1)
    - depeg_severity_pct      : float (expected loss given a depeg event, pct)
    - holding_days            : float (intended holding horizon, default 365)
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

    headline = _pick(headline_apy_pct, "headline_apy_pct", 0.0)
    risk_free = _pick(risk_free_rate_pct, "risk_free_rate_pct",
                      _DEFAULT_RISK_FREE_RATE_PCT)
    risk_proxy = max(0.0, _pick(protocol_risk_proxy_pct,
                                "protocol_risk_proxy_pct",
                                _DEFAULT_PROTOCOL_RISK_PROXY_PCT))
    depeg_prob = _clamp(_pick(depeg_probability, "depeg_probability",
                              _DEFAULT_DEPEG_PROBABILITY), 0.0, 1.0)
    depeg_sev = max(0.0, _pick(depeg_severity_pct, "depeg_severity_pct",
                               _DEFAULT_DEPEG_SEVERITY_PCT))
    days = max(0.0, _pick(holding_days, "holding_days", _DEFAULT_HOLDING_DAYS))

    dq_raw = data_quality if data_quality is not None else t.get("data_quality", "ok")
    if isinstance(dq_raw, str):
        data_quality_ok = dq_raw.strip().lower() not in ("poor", "bad", "low", "")
    else:
        data_quality_ok = bool(dq_raw)

    # Data sufficiency: need a headline yield signal (non-zero) and the data
    # quality flag must not mark the inputs as unreliable.
    has_signal = abs(headline) > _EPS
    has_data = has_signal and data_quality_ok

    excess = _excess_basis_pct(headline, risk_free)
    ratio = _basis_to_risk_ratio(excess, risk_proxy)
    depeg_cost = _depeg_expected_cost_pct(depeg_prob, depeg_sev, days)
    real_excess = _real_excess_after_depeg_haircut_pct(excess, depeg_cost)
    classification = _classify(ratio, excess, has_data)
    score = _risk_compensation_score(ratio, excess, real_excess, has_data)
    grade = _grade(score)
    flags = _flags(
        excess,
        headline,
        risk_free,
        ratio,
        excess,
        depeg_cost,
        classification,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        headline,
        risk_free,
        excess,
        ratio,
        real_excess,
        depeg_cost,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "headline_apy_pct": headline,
        "risk_free_rate_pct": risk_free,
        "protocol_risk_proxy_pct": risk_proxy,
        "depeg_probability": depeg_prob,
        "depeg_severity_pct": depeg_sev,
        "holding_days": days,
        "data_quality_ok": data_quality_ok,
        "excess_basis_pct": excess,
        "basis_to_risk_ratio": ratio,
        "depeg_expected_cost_pct": depeg_cost,
        "real_excess_after_depeg_haircut_pct": real_excess,
        "risk_compensation_score": score,
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
    Analyse excess-basis compensation across a batch of positions and summarise.

    Returns
    -------
    dict
        - total_positions             : int
        - results                     : list[dict]  (per-position analysis)
        - best_compensated_position   : str | None  (highest compensation score)
        - worst_compensated_position  : str | None  (lowest compensation score)
        - avg_risk_compensation_score : float
        - negative_excess_basis_count : int
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
            "best_compensated_position": None,
            "worst_compensated_position": None,
            "avg_risk_compensation_score": 0.0,
            "negative_excess_basis_count": 0,
            "timestamp": time.time(),
        }

    best = max(results, key=lambda r: r["risk_compensation_score"])
    worst = min(results, key=lambda r: r["risk_compensation_score"])
    avg = sum(r["risk_compensation_score"] for r in results) / total
    neg = sum(1 for r in results if r["excess_basis_pct"] < 0.0)

    return {
        "total_positions": total,
        "results": results,
        "best_compensated_position": best["name"],
        "worst_compensated_position": worst["name"],
        "avg_risk_compensation_score": avg,
        "negative_excess_basis_count": neg,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolStablecoinYieldBasisSpreadAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = DeFiProtocolStablecoinYieldBasisSpreadAnalyzer()
    >>> r = a.analyze({"name": "USDC-vault", "headline_apy_pct": 8.0,
    ...                "risk_free_rate_pct": 5.0,
    ...                "protocol_risk_proxy_pct": 3.0})
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
            "name": "USDC-vault (thin spread)",
            "headline_apy_pct": 6.0,
            "risk_free_rate_pct": 5.0,
            "protocol_risk_proxy_pct": 4.0,
            "depeg_probability": 0.02,
            "depeg_severity_pct": 20.0,
            "holding_days": 365.0,
        },
        {
            "name": "Algo-stable farm (generous)",
            "headline_apy_pct": 18.0,
            "risk_free_rate_pct": 5.0,
            "protocol_risk_proxy_pct": 5.0,
            "depeg_probability": 0.05,
            "depeg_severity_pct": 30.0,
            "holding_days": 365.0,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_positions[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_positions)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
