"""
MP-1141  DeFiProtocolYieldAfterTaxDragAnalyzer
----------------------------------------------
Estimate the *after-tax realisable APR* and the *tax drag* of a yield position,
accounting for the holder's marginal tax rate, the harvest frequency (each
harvest is a taxable event) and the holding period (which decides whether the
income is treated at the short-term or long-term rate).

Headline APR is a pre-tax number. What actually lands in the holder's pocket
depends on how the yield is taxed: a 12% headline APR for a holder on a 37%
marginal rate who harvests frequently (so all income is short-term ordinary
income) realises only ~7.6% after tax. If, instead, a large share of the income
qualifies for the long-term rate, the blended effective tax rate falls and the
after-tax APR rises. This module makes that decomposition explicit.

For a single position the module computes:
- the blended effective tax rate (short-term vs long-term, weighted by the
  share of income that qualifies for long-term treatment given the holding
  period),
- the after-tax realisable APR,
- the tax drag (the share of the headline yield eaten by tax),
- a 0-100 *after-tax efficiency score* (higher = less yield is lost to tax),
- a classification band, an A-F grade, advisory flags and recommendations.

Genuine gap: existing modules score gas breakeven, lockup discounts,
excess-basis spreads, compounding cadence and net carry, but none model the
*tax drag on yield* — the after-tax APR and effective tax rate of a position
given marginal rate, harvest cadence and holding period. The existing
``defi_tax_lot_tracker.py`` tracks individual tax *lots* (cost basis / lot
accounting) and does NOT compute a tax drag on yield, so this is a distinct
angle; a grep for "after_tax" and "tax_drag" across the analytics package
confirms no existing module covers this.

The module returns:
- name / headline_apr_pct / marginal_tax_rate_pct (input echoes)
- long_term_rate_pct               - the preferential long-term rate (echo)
- long_term_income_share           - share of income qualifying long-term (echo)
- effective_tax_rate_pct           - blended ST/LT effective rate
- after_tax_apr_pct                - headline APR net of the blended tax
- tax_drag_pct                     - share of the headline yield eaten by tax
- after_tax_efficiency_score       - 0-100, higher = less drag
- classification                   - MINIMAL_DRAG .. SEVERE
- grade                            - A-F letter grade
- flags / recommendations          - advisory verdicts

DISCLAIMER: this is a deliberately simplified, advisory-only model. It is NOT
tax advice. Real tax treatment of DeFi yield varies by jurisdiction, income
character, wash-sale and constructive-receipt rules, and individual
circumstances. Consult a qualified tax professional before acting.

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
    "yield_after_tax_drag_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Defaults.
_DEFAULT_MARGINAL_TAX_RATE_PCT = 37.0
_DEFAULT_LONG_TERM_RATE_PCT = 20.0
_DEFAULT_HOLDING_DAYS = 30.0
_DEFAULT_HARVESTS_PER_YEAR = 12.0
_LONG_TERM_THRESHOLD_DAYS = 365.0   # holds >= 1y qualify for long-term rate
_DAYS_PER_YEAR = 365.0

# A holding period at/above the long-term threshold AND infrequent harvesting
# means most income is realised long-term. We model the long-term income share
# as a function of holding period unless explicitly supplied.

# Classification bands
CLASS_MINIMAL_DRAG = "MINIMAL_DRAG"
CLASS_LIGHT = "LIGHT"
CLASS_MODERATE = "MODERATE"
CLASS_HEAVY = "HEAVY"
CLASS_SEVERE = "SEVERE"

ALL_CLASSIFICATIONS = (
    CLASS_MINIMAL_DRAG,
    CLASS_LIGHT,
    CLASS_MODERATE,
    CLASS_HEAVY,
    CLASS_SEVERE,
)

# Flags
FLAG_HIGH_MARGINAL_RATE = "HIGH_MARGINAL_RATE"
FLAG_FREQUENT_TAXABLE_EVENTS = "FREQUENT_TAXABLE_EVENTS"
FLAG_QUALIFIES_LONG_TERM = "QUALIFIES_LONG_TERM"
FLAG_SEVERE_TAX_DRAG = "SEVERE_TAX_DRAG"
FLAG_NEGATIVE_AFTER_TAX = "NEGATIVE_AFTER_TAX"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_HIGH_MARGINAL_RATE,
    FLAG_FREQUENT_TAXABLE_EVENTS,
    FLAG_QUALIFIES_LONG_TERM,
    FLAG_SEVERE_TAX_DRAG,
    FLAG_NEGATIVE_AFTER_TAX,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds (module constants)
# tax_drag_pct bands -> classification
_DRAG_MINIMAL = 15.0    # < 15% of yield lost to tax -> minimal
_DRAG_LIGHT = 25.0      # < 25% -> light
_DRAG_MODERATE = 35.0   # < 35% -> moderate
_DRAG_HEAVY = 45.0      # < 45% -> heavy; >= 45% -> severe

# Flag thresholds.
_HIGH_MARGINAL_RATE_PCT = 32.0       # marginal rate at/above this is high
_FREQUENT_HARVEST_PER_YEAR = 12.0    # harvests at/above this is frequent
_SEVERE_TAX_DRAG_PCT = 45.0          # tax drag at/above this is severe
_LONG_TERM_QUALIFY_SHARE = 0.5       # long-term share at/above => qualifies


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

def _long_term_income_share(
    holding_days: float,
    harvests_per_year: float,
    explicit_share: float | None,
) -> float:
    """
    Share of income (0..1) that qualifies for the long-term tax rate.

    If an explicit share is supplied (not None) it is used, clamped to [0,1].

    Otherwise modelled: income only qualifies for long-term treatment when the
    position is held at least the long-term threshold (1 year) AND harvesting is
    infrequent (frequent harvests realise income short-term each harvest). The
    modelled share is:

        if holding_days < threshold:        0.0
        else: 1 - (harvests_per_year / threshold-implied cadence), floored at 0

    We approximate the cadence penalty as harvests_per_year / 12 capped at 1,
    so 12+ harvests/year drives the long-term share to 0 even on a long hold.
    """
    if explicit_share is not None:
        return _clamp(explicit_share, 0.0, 1.0)

    days = max(0.0, holding_days)
    if days < _LONG_TERM_THRESHOLD_DAYS:
        return 0.0

    harvests = max(0.0, harvests_per_year)
    # Frequent harvesting realises income short-term; 12+/yr -> 0 long-term.
    cadence_penalty = _clamp(harvests / 12.0, 0.0, 1.0)
    return _clamp(1.0 - cadence_penalty, 0.0, 1.0)


def _effective_tax_rate_pct(
    marginal_tax_rate_pct: float,
    long_term_rate_pct: float,
    long_term_income_share: float,
) -> float:
    """
    Blended effective tax rate (pct): weight the long-term rate by the share of
    income qualifying long-term, and the marginal (short-term/ordinary) rate by
    the remainder.

        effective = lt_share * lt_rate + (1 - lt_share) * marginal_rate

    Rates are floored at 0; the share is clamped to [0,1].
    """
    st_rate = max(0.0, marginal_tax_rate_pct)
    lt_rate = max(0.0, long_term_rate_pct)
    share = _clamp(long_term_income_share, 0.0, 1.0)
    return share * lt_rate + (1.0 - share) * st_rate


def _after_tax_apr_pct(
    headline_apr_pct: float,
    effective_tax_rate_pct: float,
) -> float:
    """
    After-tax realisable APR (pct).

        after_tax = headline_apr * (1 - effective_tax_rate/100)

    The effective tax rate is clamped to [0,100] for this calculation so a
    >100% rate cannot flip a positive headline into a fabricated gain.
    """
    eff = _clamp(effective_tax_rate_pct, 0.0, 100.0)
    return headline_apr_pct * (1.0 - eff / 100.0)


def _tax_drag_pct(
    headline_apr_pct: float,
    after_tax_apr_pct: float,
) -> float:
    """
    Share of the headline yield eaten by tax, in pct.

        drag = (headline - after_tax) / headline * 100

    Defensive: when the headline APR is ~0 (or negative) the drag is undefined;
    we return 0.0 (no positive yield to be eaten).
    """
    if headline_apr_pct <= _EPS:
        return 0.0
    drag = (headline_apr_pct - after_tax_apr_pct) / headline_apr_pct * 100.0
    return drag


def _after_tax_efficiency_score(
    tax_drag_pct: float,
    after_tax_apr_pct: float,
    long_term_income_share: float,
    has_data: bool,
) -> float:
    """
    0-100: higher = less of the yield is lost to tax.

    Blends three drivers:
    - inverse drag (0-60): one minus tax_drag/100, so a small drag contributes
      the full 60; a 100% drag contributes 0.
    - positive-after-tax (0-25): full 25 when the after-tax APR is positive, 0
      when it is non-positive.
    - long-term qualification (0-15): scaled by the long-term income share, so
      a fully long-term position earns the full 15.

    Returns 0.0 when there is no usable data.
    """
    if not has_data:
        return 0.0

    drag_share = _clamp(tax_drag_pct / 100.0, 0.0, 1.0)
    drag_component = (1.0 - drag_share) * 60.0

    after_component = 25.0 if after_tax_apr_pct > _EPS else 0.0

    lt_share = _clamp(long_term_income_share, 0.0, 1.0)
    lt_component = lt_share * 15.0

    return _clamp(drag_component + after_component + lt_component)


def _classify(tax_drag_pct: float, has_data: bool) -> str:
    """
    Assign an advisory classification band on tax drag share of headline yield.

      < 15   -> MINIMAL_DRAG
      < 25   -> LIGHT
      < 35   -> MODERATE
      < 45   -> HEAVY
      >= 45  -> SEVERE

    No data falls back to SEVERE (cannot demonstrate the tax drag is small).
    """
    if not has_data:
        return CLASS_SEVERE

    drag = tax_drag_pct
    if drag < _DRAG_MINIMAL:
        return CLASS_MINIMAL_DRAG
    if drag < _DRAG_LIGHT:
        return CLASS_LIGHT
    if drag < _DRAG_MODERATE:
        return CLASS_MODERATE
    if drag < _DRAG_HEAVY:
        return CLASS_HEAVY
    return CLASS_SEVERE


def _grade(after_tax_efficiency_score: float) -> str:
    """Map after_tax_efficiency_score (higher = better) to an A-F grade."""
    s = after_tax_efficiency_score
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
    marginal_tax_rate_pct: float,
    harvests_per_year: float,
    long_term_income_share: float,
    tax_drag_pct: float,
    after_tax_apr_pct: float,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if marginal_tax_rate_pct >= _HIGH_MARGINAL_RATE_PCT:
        flags.append(FLAG_HIGH_MARGINAL_RATE)

    if harvests_per_year >= _FREQUENT_HARVEST_PER_YEAR:
        flags.append(FLAG_FREQUENT_TAXABLE_EVENTS)

    if long_term_income_share >= _LONG_TERM_QUALIFY_SHARE:
        flags.append(FLAG_QUALIFIES_LONG_TERM)

    if tax_drag_pct >= _SEVERE_TAX_DRAG_PCT:
        flags.append(FLAG_SEVERE_TAX_DRAG)

    if after_tax_apr_pct < 0.0:
        flags.append(FLAG_NEGATIVE_AFTER_TAX)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    headline_apr_pct: float,
    effective_tax_rate_pct: float,
    after_tax_apr_pct: float,
    tax_drag_pct: float,
    harvests_per_year: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: no headline-APR signal or data marked "
            "unreliable. Cannot assess the tax drag for this position. (Advisory "
            "only - not tax advice.)"
        )
        return recs

    if classification == CLASS_SEVERE:
        recs.append(
            f"Severe tax drag: ~{tax_drag_pct:.1f}% of the headline "
            f"{headline_apr_pct:.2f}% APR is lost to tax (effective rate ~"
            f"{effective_tax_rate_pct:.1f}%), leaving ~{after_tax_apr_pct:.2f}% "
            "after tax. (Advisory only - not tax advice.)"
        )
    elif classification == CLASS_HEAVY:
        recs.append(
            f"Heavy tax drag: ~{tax_drag_pct:.1f}% of the yield goes to tax; "
            f"after-tax APR is ~{after_tax_apr_pct:.2f}%. Consider longer holds "
            "or fewer harvests to reduce the drag. (Not tax advice.)"
        )
    elif classification == CLASS_MODERATE:
        recs.append(
            f"Moderate tax drag: after-tax APR ~{after_tax_apr_pct:.2f}% "
            f"(effective rate ~{effective_tax_rate_pct:.1f}%). Material but "
            "manageable. (Not tax advice.)"
        )
    elif classification == CLASS_LIGHT:
        recs.append(
            f"Light tax drag: after-tax APR ~{after_tax_apr_pct:.2f}% retains "
            "most of the headline yield. (Not tax advice.)"
        )
    else:  # MINIMAL_DRAG
        recs.append(
            f"Minimal tax drag: after-tax APR ~{after_tax_apr_pct:.2f}% is close "
            "to the headline; tax barely dents the yield. (Not tax advice.)"
        )

    if FLAG_HIGH_MARGINAL_RATE in flags:
        recs.append(
            "High marginal rate: most income is taxed at the top ordinary rate. "
            "Holding to qualify for the long-term rate would cut the effective "
            "rate substantially. (Not tax advice.)"
        )

    if FLAG_FREQUENT_TAXABLE_EVENTS in flags:
        recs.append(
            f"Frequent taxable events: ~{harvests_per_year:.0f} harvests/year "
            "each realise income short-term, blocking long-term treatment. "
            "Harvest less often or auto-compound without realising. (Not tax "
            "advice.)"
        )

    if FLAG_QUALIFIES_LONG_TERM in flags:
        recs.append(
            "Qualifies long-term: a meaningful share of income is taxed at the "
            "preferential long-term rate, lowering the blended effective rate. "
            "(Not tax advice.)"
        )

    if FLAG_NEGATIVE_AFTER_TAX in flags:
        recs.append(
            "Negative after-tax APR: the modelled tax exceeds the headline "
            "yield. Re-check inputs; do not rely on this without a tax "
            "professional. (Not tax advice.)"
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    token: dict | None = None,
    config: dict | None = None,
    *,
    headline_apr_pct: float | None = None,
    marginal_tax_rate_pct: float | None = None,
    long_term_rate_pct: float | None = None,
    holding_days: float | None = None,
    harvests_per_year: float | None = None,
    long_term_income_share: float | None = None,
    data_quality: Any = None,
    name: str | None = None,
) -> dict:
    """
    Analyse the after-tax drag of a single yield position.

    Inputs may be supplied as a ``token`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    Recognised keys / keywords (all with safe defaults):
    - name                    : str
    - headline_apr_pct        : float (pre-tax advertised APR)
    - marginal_tax_rate_pct   : float (short-term/ordinary rate, default 37)
    - long_term_rate_pct      : float (preferential long-term rate, default 20)
    - holding_days            : float (intended holding horizon, default 30)
    - harvests_per_year       : float (taxable harvest events/year, default 12)
    - long_term_income_share  : float (0..1; if supplied, overrides the modelled
                                share of income qualifying for long-term rate)
    - data_quality            : truthy/"ok" => trusted; falsy/"poor" => not

    config : dict, optional
        - log_path : str  (override default log path)

    Returns
    -------
    dict
        Full analysis result. Never raises to the caller.

    NOTE: simplified advisory model only. NOT tax advice.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    t = token if isinstance(token, dict) else {}

    def _pick(kw: Any, key: str, default: float) -> float:
        if kw is not None:
            return _safe_float(kw, default)
        return _safe_float(t.get(key, default), default)

    name_val = name if name is not None else str(t.get("name", "UNKNOWN"))

    headline = _pick(headline_apr_pct, "headline_apr_pct", 0.0)
    marginal = max(0.0, _pick(marginal_tax_rate_pct, "marginal_tax_rate_pct",
                              _DEFAULT_MARGINAL_TAX_RATE_PCT))
    lt_rate = max(0.0, _pick(long_term_rate_pct, "long_term_rate_pct",
                             _DEFAULT_LONG_TERM_RATE_PCT))
    days = max(0.0, _pick(holding_days, "holding_days", _DEFAULT_HOLDING_DAYS))
    harvests = max(0.0, _pick(harvests_per_year, "harvests_per_year",
                              _DEFAULT_HARVESTS_PER_YEAR))

    # long_term_income_share: explicit if supplied (kw or dict key present).
    explicit_share: float | None
    if long_term_income_share is not None:
        explicit_share = _safe_float(long_term_income_share, 0.0)
    elif "long_term_income_share" in t:
        explicit_share = _safe_float(t.get("long_term_income_share"), 0.0)
    else:
        explicit_share = None

    dq_raw = data_quality if data_quality is not None else t.get("data_quality", "ok")
    if isinstance(dq_raw, str):
        data_quality_ok = dq_raw.strip().lower() not in ("poor", "bad", "low", "")
    else:
        data_quality_ok = bool(dq_raw)

    # Data sufficiency: need a headline APR signal (non-zero) and the data
    # quality flag must not mark the inputs as unreliable.
    has_signal = abs(headline) > _EPS
    has_data = has_signal and data_quality_ok

    lt_share = _long_term_income_share(days, harvests, explicit_share)
    effective = _effective_tax_rate_pct(marginal, lt_rate, lt_share)
    after_tax = _after_tax_apr_pct(headline, effective)
    drag = _tax_drag_pct(headline, after_tax)
    classification = _classify(drag, has_data)
    score = _after_tax_efficiency_score(drag, after_tax, lt_share, has_data)
    grade = _grade(score)
    flags = _flags(
        marginal,
        harvests,
        lt_share,
        drag,
        after_tax,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        headline,
        effective,
        after_tax,
        drag,
        harvests,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "headline_apr_pct": headline,
        "marginal_tax_rate_pct": marginal,
        "long_term_rate_pct": lt_rate,
        "holding_days": days,
        "harvests_per_year": harvests,
        "long_term_income_share": lt_share,
        "data_quality_ok": data_quality_ok,
        "effective_tax_rate_pct": effective,
        "after_tax_apr_pct": after_tax,
        "tax_drag_pct": drag,
        "after_tax_efficiency_score": score,
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
    Analyse after-tax drag across a batch of positions and summarise.

    Returns
    -------
    dict
        - total_positions             : int
        - results                     : list[dict]  (per-position analysis)
        - most_tax_efficient_position : str | None  (highest efficiency score)
        - least_tax_efficient_position: str | None  (lowest efficiency score)
        - avg_after_tax_efficiency_score : float
        - severe_drag_count           : int
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
            "most_tax_efficient_position": None,
            "least_tax_efficient_position": None,
            "avg_after_tax_efficiency_score": 0.0,
            "severe_drag_count": 0,
            "timestamp": time.time(),
        }

    most = max(results, key=lambda r: r["after_tax_efficiency_score"])
    least = min(results, key=lambda r: r["after_tax_efficiency_score"])
    avg = sum(r["after_tax_efficiency_score"] for r in results) / total
    severe = sum(1 for r in results if r["classification"] == CLASS_SEVERE)

    return {
        "total_positions": total,
        "results": results,
        "most_tax_efficient_position": most["name"],
        "least_tax_efficient_position": least["name"],
        "avg_after_tax_efficiency_score": avg,
        "severe_drag_count": severe,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolYieldAfterTaxDragAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = DeFiProtocolYieldAfterTaxDragAnalyzer()
    >>> r = a.analyze({"name": "USDC-farm", "headline_apr_pct": 12.0,
    ...                "marginal_tax_rate_pct": 37.0,
    ...                "harvests_per_year": 52.0})

    NOTE: simplified advisory model only. NOT tax advice.
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
            "name": "USDC-farm (frequent harvest, top rate)",
            "headline_apr_pct": 12.0,
            "marginal_tax_rate_pct": 37.0,
            "long_term_rate_pct": 20.0,
            "holding_days": 30.0,
            "harvests_per_year": 52.0,
        },
        {
            "name": "stETH (long hold, no harvests)",
            "headline_apr_pct": 4.0,
            "marginal_tax_rate_pct": 24.0,
            "long_term_rate_pct": 15.0,
            "holding_days": 730.0,
            "harvests_per_year": 0.0,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_positions[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_positions)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
