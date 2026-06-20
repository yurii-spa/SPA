"""
MP-1090  DeFiProtocolRebaseTokenYieldNormalizer
--------------------------------------------------
Normalize a rebasing token's advertised (balance-growth) APY into a true
economic, purchasing-power yield, and flag dilutive / cosmetic rebases.

Rebasing tokens (stETH-style positive rebase, aTokens, OHM-style elastic
supply) advertise an APY through balance growth: the holder's token balance
ticks up every rebase. But balance growth is NOT the same as economic yield.
Some rebases are dilutive or purely cosmetic — supply inflates faster than the
underlying backing value (NAV) per token, so the holder's real purchasing
power grows by less than the headline number suggests. This module:

  (a) compounds the advertised periodic rebase into an effective annual APY,
  (b) strips out dilution to recover the real economic yield,
  (c) measures how much of the headline is purely supply inflation
      (cosmetic) versus genuine backing growth, and
  (d) adjusts for market price drift vs peg/NAV to get a purchasing-power
      yield, then scores how "real" the headline rebase actually is.

Genuine gap: existing yield modules score APY sustainability and incentive
decay, but none normalise rebasing balance-growth into a dilution-adjusted,
purchasing-power yield or quantify cosmetic-rebase share.

The module returns:
- effective_compounding_apy_pct   – advertised rebase compounded annually
- real_economic_yield_pct         – yield net of supply dilution
- dilution_drag_pct               – headline minus real economic yield
- cosmetic_rebase_ratio           – share of headline that is pure inflation
- purchasing_power_yield_pct      – real yield adjusted by price drift
- normalization_gap_pct           – headline minus purchasing-power yield
- rebase_quality_score            – 0-100, higher = more real / less cosmetic
- classification                  – REAL_YIELD .. FULLY_DILUTIVE
- grade                           – A-F letter grade
- flags / recommendations         – advisory verdicts

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
    "rebase_token_yield_normalizer_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Days per year used to annualise a periodic rebase rate.
_DAYS_PER_YEAR = 365.0

# Classification bands
CLASS_REAL_YIELD = "REAL_YIELD"
CLASS_MOSTLY_REAL = "MOSTLY_REAL"
CLASS_MIXED = "MIXED"
CLASS_MOSTLY_COSMETIC = "MOSTLY_COSMETIC"
CLASS_FULLY_DILUTIVE = "FULLY_DILUTIVE"

ALL_CLASSIFICATIONS = (
    CLASS_REAL_YIELD,
    CLASS_MOSTLY_REAL,
    CLASS_MIXED,
    CLASS_MOSTLY_COSMETIC,
    CLASS_FULLY_DILUTIVE,
)

# Flags
FLAG_HIGH_DILUTION_DRAG = "HIGH_DILUTION_DRAG"
FLAG_COSMETIC_REBASE = "COSMETIC_REBASE"
FLAG_NEGATIVE_REAL_YIELD = "NEGATIVE_REAL_YIELD"
FLAG_PRICE_BELOW_NAV = "PRICE_BELOW_NAV"
FLAG_HEADLINE_OVERSTATES_YIELD = "HEADLINE_OVERSTATES_YIELD"
FLAG_STRONG_REAL_YIELD = "STRONG_REAL_YIELD"
FLAG_BACKING_OUTPACES_SUPPLY = "BACKING_OUTPACES_SUPPLY"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_HIGH_DILUTION_DRAG,
    FLAG_COSMETIC_REBASE,
    FLAG_NEGATIVE_REAL_YIELD,
    FLAG_PRICE_BELOW_NAV,
    FLAG_HEADLINE_OVERSTATES_YIELD,
    FLAG_STRONG_REAL_YIELD,
    FLAG_BACKING_OUTPACES_SUPPLY,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds
_HIGH_DILUTION_DRAG_PCT = 5.0       # headline overstates by >= 5% is high drag
_COSMETIC_RATIO = 0.5               # >= 50% of headline is inflation is cosmetic
_STRONG_REAL_YIELD_PCT = 4.0        # real yield >= 4% is "strong" standalone
_HEADLINE_OVERSTATES_PCT = 3.0      # normalization gap >= 3% overstates
_PRICE_BELOW_NAV_PCT = -2.0         # price drift <= -2% is meaningfully below NAV


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

def _effective_compounding_apy_pct(
    advertised_apy_pct: float,
    rebase_frequency_per_day: float,
) -> float:
    """
    Compound the advertised periodic rebase into an effective annual APY (pct).

    The advertised APY is treated as the simple (nominal) annual rate that is
    actually paid out across discrete rebases. The effective compounded figure
    is::

        n = rebase_frequency_per_day * 365
        eff = ((1 + advertised/100 / n) ** n - 1) * 100

    Returns the advertised APY unchanged when the rebase frequency is <= 0
    (no compounding information; avoids div-by-zero). Defensive against
    overflow on pathological inputs.
    """
    if rebase_frequency_per_day <= 0.0:
        return advertised_apy_pct

    n = rebase_frequency_per_day * _DAYS_PER_YEAR
    if n <= 0.0:
        return advertised_apy_pct

    periodic = advertised_apy_pct / 100.0 / n
    # 1 + periodic must stay positive to avoid complex/oscillating results.
    base = 1.0 + periodic
    if base <= 0.0:
        return advertised_apy_pct
    try:
        eff = (base ** n - 1.0) * 100.0
    except OverflowError:
        return advertised_apy_pct
    return eff


def _real_economic_yield_pct(
    advertised_apy_pct: float,
    backing_value_growth_pct: float,
    supply_growth_pct: float,
) -> float:
    """
    Real economic (dilution-adjusted) yield, in pct.

    A rebase token's headline APY is delivered through supply growth. The
    holder's real economic yield is the growth of *backing value per token* —
    i.e. backing growth net of the dilution caused by supply inflation::

        real = backing_value_growth - supply_growth

    When explicit backing/supply growth are not supplied (both ~0), we fall
    back to the advertised APY (no dilution information to deduct). The result
    is capped at the advertised APY (real yield cannot exceed what is paid).
    """
    if abs(backing_value_growth_pct) <= _EPS and abs(supply_growth_pct) <= _EPS:
        return advertised_apy_pct

    real = backing_value_growth_pct - supply_growth_pct
    # Real economic yield cannot exceed the advertised headline payout.
    return min(real, advertised_apy_pct)


def _dilution_drag_pct(
    advertised_apy_pct: float,
    real_economic_yield_pct: float,
) -> float:
    """
    Headline APY lost to supply dilution, in pct (floored at 0).

    dilution_drag = max(0, advertised_apy - real_economic_yield)
    """
    return max(0.0, advertised_apy_pct - real_economic_yield_pct)


def _cosmetic_rebase_ratio(
    supply_growth_pct: float,
    backing_value_growth_pct: float,
) -> float:
    """
    Share of headline growth that is purely supply inflation, 0..1.

    The headline balance growth is driven by both supply inflation (cosmetic)
    and backing growth (real). The cosmetic share is::

        ratio = supply_growth / (supply_growth + max(0, backing_growth))

    Returns 0.0 when the denominator is ~0 (no growth at all → nothing
    cosmetic; avoids div-by-zero) and clamps the result to [0, 1]. Negative
    supply growth (a contraction) is treated as 0 cosmetic share.
    """
    sup = max(0.0, supply_growth_pct)
    back = max(0.0, backing_value_growth_pct)
    denom = sup + back
    if denom <= _EPS:
        return 0.0
    ratio = sup / denom
    return max(0.0, min(1.0, ratio))


def _purchasing_power_yield_pct(
    real_economic_yield_pct: float,
    token_price_change_pct: float,
) -> float:
    """
    Real economic yield adjusted for market price drift vs peg/NAV, in pct.

    A token trading below NAV (negative price change) erodes the holder's
    realisable purchasing power; trading above NAV adds to it::

        purchasing_power = real_economic_yield + token_price_change
    """
    return real_economic_yield_pct + token_price_change_pct


def _normalization_gap_pct(
    advertised_apy_pct: float,
    purchasing_power_yield_pct: float,
) -> float:
    """
    Gap between the headline APY and the true purchasing-power yield, in pct.

    A large positive gap means the advertised number meaningfully overstates
    the yield a holder actually realises.
    """
    return advertised_apy_pct - purchasing_power_yield_pct


def _rebase_quality_score(
    advertised_apy_pct: float,
    real_economic_yield_pct: float,
    cosmetic_rebase_ratio: float,
    purchasing_power_yield_pct: float,
    has_data: bool,
) -> float:
    """
    0-100: higher = more of the headline is real yield (less cosmetic).

    Blends three drivers:
    - real-share (0-55): real economic yield as a fraction of the headline,
    - non-cosmetic (0-25): one minus the cosmetic-rebase ratio,
    - purchasing-power realisation (0-20): purchasing-power yield as a
      fraction of the headline (penalises price-below-NAV erosion).

    Returns 0.0 when there is no usable data. A negative real or
    purchasing-power yield contributes 0 to its component.
    """
    if not has_data:
        return 0.0

    headline = advertised_apy_pct
    if headline <= _EPS:
        # No headline to overstate; quality is driven purely by the
        # non-cosmetic share (a flat token is "honest" by default).
        non_cosmetic = (1.0 - cosmetic_rebase_ratio)
        return _clamp(non_cosmetic * 100.0)

    real_frac = _clamp(real_economic_yield_pct / headline, 0.0, 1.0)
    pp_frac = _clamp(purchasing_power_yield_pct / headline, 0.0, 1.0)
    non_cosmetic = _clamp(1.0 - cosmetic_rebase_ratio, 0.0, 1.0)

    score = real_frac * 55.0 + non_cosmetic * 25.0 + pp_frac * 20.0
    return _clamp(score)


def _classify(
    cosmetic_rebase_ratio: float,
    real_economic_yield_pct: float,
    rebase_quality_score: float,
    has_data: bool,
) -> str:
    """
    Assign an advisory classification band, driven by the cosmetic ratio.

    Bands (on cosmetic_rebase_ratio):
      < 0.20  → REAL_YIELD
      < 0.40  → MOSTLY_REAL
      < 0.60  → MIXED
      < 0.80  → MOSTLY_COSMETIC
      >= 0.80 → FULLY_DILUTIVE
    A negative real economic yield forces at least MOSTLY_COSMETIC (the
    headline is not backed by real growth).

    No data falls back to REAL_YIELD (no dilution can be demonstrated).
    """
    if not has_data:
        return CLASS_REAL_YIELD

    if cosmetic_rebase_ratio < 0.20:
        base = CLASS_REAL_YIELD
    elif cosmetic_rebase_ratio < 0.40:
        base = CLASS_MOSTLY_REAL
    elif cosmetic_rebase_ratio < 0.60:
        base = CLASS_MIXED
    elif cosmetic_rebase_ratio < 0.80:
        base = CLASS_MOSTLY_COSMETIC
    else:
        base = CLASS_FULLY_DILUTIVE

    order = list(ALL_CLASSIFICATIONS)
    idx = order.index(base)

    # A negative real yield is at least MOSTLY_COSMETIC.
    if real_economic_yield_pct < 0.0:
        idx = max(idx, order.index(CLASS_MOSTLY_COSMETIC))

    return order[idx]


def _grade(rebase_quality_score: float) -> str:
    """Map rebase_quality_score (higher = better) to an A-F letter grade."""
    s = rebase_quality_score
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
    dilution_drag_pct: float,
    cosmetic_rebase_ratio: float,
    real_economic_yield_pct: float,
    token_price_change_pct: float,
    normalization_gap_pct: float,
    backing_value_growth_pct: float,
    supply_growth_pct: float,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if dilution_drag_pct >= _HIGH_DILUTION_DRAG_PCT:
        flags.append(FLAG_HIGH_DILUTION_DRAG)

    if cosmetic_rebase_ratio >= _COSMETIC_RATIO:
        flags.append(FLAG_COSMETIC_REBASE)

    if real_economic_yield_pct < 0.0:
        flags.append(FLAG_NEGATIVE_REAL_YIELD)

    if token_price_change_pct <= _PRICE_BELOW_NAV_PCT:
        flags.append(FLAG_PRICE_BELOW_NAV)

    if normalization_gap_pct >= _HEADLINE_OVERSTATES_PCT:
        flags.append(FLAG_HEADLINE_OVERSTATES_YIELD)

    if real_economic_yield_pct >= _STRONG_REAL_YIELD_PCT:
        flags.append(FLAG_STRONG_REAL_YIELD)

    if backing_value_growth_pct > supply_growth_pct:
        flags.append(FLAG_BACKING_OUTPACES_SUPPLY)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    advertised_apy_pct: float,
    real_economic_yield_pct: float,
    purchasing_power_yield_pct: float,
    cosmetic_rebase_ratio: float,
    normalization_gap_pct: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: no advertised_apy_pct and no backing/supply "
            "growth supplied. Cannot normalise rebase yield for this token."
        )
        return recs

    if classification == CLASS_FULLY_DILUTIVE:
        recs.append(
            f"Fully dilutive: ~{cosmetic_rebase_ratio * 100.0:.0f}% of the "
            f"{advertised_apy_pct:.2f}% headline is pure supply inflation. The "
            f"real economic yield is only ~{real_economic_yield_pct:.2f}%; "
            "treat the advertised APY as cosmetic."
        )
    elif classification == CLASS_MOSTLY_COSMETIC:
        recs.append(
            f"Mostly cosmetic: a majority (~{cosmetic_rebase_ratio * 100.0:.0f}%) "
            f"of the {advertised_apy_pct:.2f}% headline is supply inflation. "
            f"Real economic yield ~{real_economic_yield_pct:.2f}%."
        )
    elif classification == CLASS_MIXED:
        recs.append(
            f"Mixed rebase: ~{cosmetic_rebase_ratio * 100.0:.0f}% of the "
            f"headline is inflation and the rest is backing growth. Use the "
            f"~{real_economic_yield_pct:.2f}% real economic yield for sizing."
        )
    elif classification == CLASS_MOSTLY_REAL:
        recs.append(
            f"Mostly real: most of the {advertised_apy_pct:.2f}% headline is "
            f"backed by genuine growth; real economic yield "
            f"~{real_economic_yield_pct:.2f}%."
        )
    else:  # REAL_YIELD
        recs.append(
            f"Real yield: the {advertised_apy_pct:.2f}% headline is backed by "
            f"genuine backing growth (real economic yield "
            f"~{real_economic_yield_pct:.2f}%). Minimal dilution."
        )

    if FLAG_HIGH_DILUTION_DRAG in flags:
        recs.append(
            "High dilution drag: a large slice of the headline APY is lost to "
            "supply inflation and does not reach the holder's real yield."
        )

    if FLAG_NEGATIVE_REAL_YIELD in flags:
        recs.append(
            "Negative real economic yield: supply is inflating faster than "
            "backing value grows, so holders lose purchasing power despite a "
            "rising token balance."
        )

    if FLAG_PRICE_BELOW_NAV in flags:
        recs.append(
            "Token trades below peg/NAV: realising the position would crystallise "
            "a discount that further erodes the purchasing-power yield."
        )

    if FLAG_HEADLINE_OVERSTATES_YIELD in flags:
        recs.append(
            f"Headline overstates yield: the advertised APY exceeds the "
            f"purchasing-power yield by ~{normalization_gap_pct:.2f} points. "
            f"Underwrite against ~{purchasing_power_yield_pct:.2f}% instead."
        )

    if FLAG_STRONG_REAL_YIELD in flags:
        recs.append(
            "Strong real yield: even after stripping out dilution the economic "
            "yield is healthy on its own."
        )

    if FLAG_BACKING_OUTPACES_SUPPLY in flags and FLAG_COSMETIC_REBASE not in flags:
        recs.append(
            "Backing value grows faster than supply: the rebase is accretive "
            "rather than dilutive for holders."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    token: dict | None = None,
    config: dict | None = None,
    *,
    advertised_apy_pct: float | None = None,
    rebase_frequency_per_day: float | None = None,
    backing_value_growth_pct: float | None = None,
    supply_growth_pct: float | None = None,
    token_price_change_pct: float | None = None,
    holder_share_pct: float | None = None,
    data_quality: Any = None,
    name: str | None = None,
) -> dict:
    """
    Normalise the rebase yield of a single rebasing token.

    Inputs may be supplied as a ``token`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    Recognised keys / keywords (all with safe defaults):
    - name                       : str
    - advertised_apy_pct         : float (headline balance-growth APY)
    - rebase_frequency_per_day   : float (rebases per day, for compounding)
    - backing_value_growth_pct   : float (annualised backing/NAV per token)
    - supply_growth_pct          : float (annualised supply inflation)
    - token_price_change_pct     : float (market price drift vs peg/NAV)
    - holder_share_pct           : float (optional, informational)
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

    advertised = _pick(advertised_apy_pct, "advertised_apy_pct", 0.0)
    rebase_freq = max(0.0, _pick(
        rebase_frequency_per_day, "rebase_frequency_per_day", 0.0))
    backing_growth = _pick(
        backing_value_growth_pct, "backing_value_growth_pct", 0.0)
    supply_growth = _pick(supply_growth_pct, "supply_growth_pct", 0.0)
    price_change = _pick(token_price_change_pct, "token_price_change_pct", 0.0)
    holder_share = _clamp(_pick(holder_share_pct, "holder_share_pct", 100.0),
                          0.0, 100.0)

    dq_raw = data_quality if data_quality is not None else t.get("data_quality", "ok")
    if isinstance(dq_raw, str):
        data_quality_ok = dq_raw.strip().lower() not in ("poor", "bad", "low", "")
    else:
        data_quality_ok = bool(dq_raw)

    # Data sufficiency: need a headline APY or some backing/supply signal, and
    # the data-quality flag must not mark the inputs as unreliable.
    has_signal = (
        abs(advertised) > _EPS
        or abs(backing_growth) > _EPS
        or abs(supply_growth) > _EPS
    )
    has_data = has_signal and data_quality_ok

    effective_apy = _effective_compounding_apy_pct(advertised, rebase_freq)
    real_yield = _real_economic_yield_pct(
        advertised, backing_growth, supply_growth
    )
    dilution_drag = _dilution_drag_pct(advertised, real_yield)
    cosmetic_ratio = _cosmetic_rebase_ratio(supply_growth, backing_growth)
    purchasing_power = _purchasing_power_yield_pct(real_yield, price_change)
    norm_gap = _normalization_gap_pct(advertised, purchasing_power)
    quality = _rebase_quality_score(
        advertised, real_yield, cosmetic_ratio, purchasing_power, has_data
    )
    classification = _classify(
        cosmetic_ratio, real_yield, quality, has_data
    )
    grade = _grade(quality)
    flags = _flags(
        dilution_drag,
        cosmetic_ratio,
        real_yield,
        price_change,
        norm_gap,
        backing_growth,
        supply_growth,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        advertised,
        real_yield,
        purchasing_power,
        cosmetic_ratio,
        norm_gap,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "advertised_apy_pct": advertised,
        "rebase_frequency_per_day": rebase_freq,
        "backing_value_growth_pct": backing_growth,
        "supply_growth_pct": supply_growth,
        "token_price_change_pct": price_change,
        "holder_share_pct": holder_share,
        "data_quality_ok": data_quality_ok,
        "effective_compounding_apy_pct": effective_apy,
        "real_economic_yield_pct": real_yield,
        "dilution_drag_pct": dilution_drag,
        "cosmetic_rebase_ratio": cosmetic_ratio,
        "purchasing_power_yield_pct": purchasing_power,
        "normalization_gap_pct": norm_gap,
        "rebase_quality_score": quality,
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
    Normalise rebase yield across a batch of tokens and summarise.

    Returns
    -------
    dict
        - total_positions            : int
        - results                    : list[dict]  (per-token analysis)
        - best_token                 : str | None  (highest rebase quality)
        - worst_token                : str | None  (lowest rebase quality)
        - avg_rebase_quality_score   : float
        - cosmetic_count             : int  (MOSTLY_COSMETIC or FULLY_DILUTIVE)
        - fully_dilutive_count       : int
        - timestamp                  : float
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
            "best_token": None,
            "worst_token": None,
            "avg_rebase_quality_score": 0.0,
            "cosmetic_count": 0,
            "fully_dilutive_count": 0,
            "timestamp": time.time(),
        }

    best = max(results, key=lambda r: r["rebase_quality_score"])
    worst = min(results, key=lambda r: r["rebase_quality_score"])
    avg = sum(r["rebase_quality_score"] for r in results) / total
    cosmetic = sum(
        1 for r in results
        if r["classification"] in (CLASS_MOSTLY_COSMETIC, CLASS_FULLY_DILUTIVE)
    )
    fully_dilutive = sum(
        1 for r in results if r["classification"] == CLASS_FULLY_DILUTIVE
    )

    return {
        "total_positions": total,
        "results": results,
        "best_token": best["name"],
        "worst_token": worst["name"],
        "avg_rebase_quality_score": avg,
        "cosmetic_count": cosmetic,
        "fully_dilutive_count": fully_dilutive,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolRebaseTokenYieldNormalizer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> n = DeFiProtocolRebaseTokenYieldNormalizer()
    >>> r = n.analyze({"name": "OHM", "advertised_apy_pct": 1000.0, ...})
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

    _demo_tokens = [
        {
            "name": "OHM-style (cosmetic)",
            "advertised_apy_pct": 1000.0,
            "rebase_frequency_per_day": 3.0,
            "backing_value_growth_pct": 50.0,
            "supply_growth_pct": 900.0,
            "token_price_change_pct": -40.0,
        },
        {
            "name": "stETH-style (real)",
            "advertised_apy_pct": 4.0,
            "rebase_frequency_per_day": 1.0,
            "backing_value_growth_pct": 4.0,
            "supply_growth_pct": 0.2,
            "token_price_change_pct": 0.1,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_tokens[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_tokens)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
