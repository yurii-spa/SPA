"""
MP-1138  DeFiProtocolGasCostBreakevenAnalyzer
---------------------------------------------
Quantify, for a yield-farming position, whether the *gas cost* of entering and
exiting (and periodically compounding) the position is small enough relative to
the net yield earned for the position to actually be worth opening.

A DeFi yield position is only profitable after it has earned back the gas it
cost to deploy. For small positions, on expensive chains, or in strategies that
require frequent harvest/compound transactions, the round-trip gas (approve +
deposit + harvest*N + withdraw) can swallow most or all of the yield. A 6% APR
position that costs $80 of gas to enter and exit needs to be large enough — and
held long enough — that 6% on the principal clears that $80 plus the running
harvest cost. This module makes that explicit.

For a single position the module computes:
- the total round-trip gas cost (entry + exit + harvest_count * harvest gas),
- the gross and net yield over the intended holding horizon (gross yield minus
  gas drag), in both USD and annualised-pct terms,
- the *breakeven holding days*: how long the position must be held for net
  yield to cover the round-trip gas,
- the *breakeven position size*: the minimum principal at which the position
  clears its gas over the intended horizon,
- the gas drag as a share of gross yield, and the net APR after gas,
- a 0-100 *gas-efficiency score* (higher = gas is a small drag / position is
  comfortably worth opening).

Genuine gap: existing modules score yield compounding cadence, APY, and net
carry, but none isolate the *entry/exit/harvest gas* round-trip against the
intended holding horizon to produce a breakeven holding period, a breakeven
position size, and a single gas-efficiency score.

The module returns:
- principal_usd / net_apr_pct (input echoes)
- total_gas_cost_usd            - entry + exit + harvest_count * harvest gas
- gross_yield_usd               - APR * principal over holding horizon
- net_yield_usd                 - gross yield minus total gas
- net_yield_after_gas_apr_pct   - annualised net APR after the gas drag
- gas_drag_pct_of_gross         - gas / gross yield (share eaten by gas)
- breakeven_holding_days        - days to clear the round-trip gas
- breakeven_position_size_usd   - min principal to clear gas over the horizon
- gas_efficiency_score          - 0-100, higher = gas is a small drag
- classification                - GAS_NEGLIGIBLE .. GAS_PROHIBITIVE
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
    "gas_cost_breakeven_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Sentinel for "never breaks even" (so JSON stays finite, no inf/NaN).
BREAKEVEN_SENTINEL_NEVER = 1e9

# Defaults.
_DEFAULT_HOLDING_DAYS = 30.0
_DEFAULT_ENTRY_GAS_USD = 0.0
_DEFAULT_EXIT_GAS_USD = 0.0
_DEFAULT_HARVEST_GAS_USD = 0.0
_DEFAULT_HARVEST_COUNT = 0.0
_DAYS_PER_YEAR = 365.0

# Classification bands
CLASS_GAS_NEGLIGIBLE = "GAS_NEGLIGIBLE"
CLASS_GAS_MINOR = "GAS_MINOR"
CLASS_GAS_MODERATE = "GAS_MODERATE"
CLASS_GAS_HEAVY = "GAS_HEAVY"
CLASS_GAS_PROHIBITIVE = "GAS_PROHIBITIVE"

ALL_CLASSIFICATIONS = (
    CLASS_GAS_NEGLIGIBLE,
    CLASS_GAS_MINOR,
    CLASS_GAS_MODERATE,
    CLASS_GAS_HEAVY,
    CLASS_GAS_PROHIBITIVE,
)

# Flags
FLAG_GAS_EXCEEDS_YIELD = "GAS_EXCEEDS_YIELD"
FLAG_NEVER_BREAKS_EVEN = "NEVER_BREAKS_EVEN"
FLAG_BREAKEVEN_AFTER_HORIZON = "BREAKEVEN_AFTER_HORIZON"
FLAG_POSITION_TOO_SMALL = "POSITION_TOO_SMALL"
FLAG_HIGH_HARVEST_DRAG = "HIGH_HARVEST_DRAG"
FLAG_GAS_NEGLIGIBLE = "GAS_NEGLIGIBLE"
FLAG_NEGATIVE_NET_YIELD = "NEGATIVE_NET_YIELD"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_GAS_EXCEEDS_YIELD,
    FLAG_NEVER_BREAKS_EVEN,
    FLAG_BREAKEVEN_AFTER_HORIZON,
    FLAG_POSITION_TOO_SMALL,
    FLAG_HIGH_HARVEST_DRAG,
    FLAG_GAS_NEGLIGIBLE,
    FLAG_NEGATIVE_NET_YIELD,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds (module constants)
_GAS_NEGLIGIBLE_DRAG_PCT = 5.0     # gas < 5% of gross yield is negligible
_GAS_MINOR_DRAG_PCT = 20.0         # < 20% is minor
_GAS_MODERATE_DRAG_PCT = 50.0      # < 50% is moderate
_GAS_HEAVY_DRAG_PCT = 90.0         # < 90% is heavy; >= 90% prohibitive
_HIGH_HARVEST_DRAG_SHARE = 0.50    # harvest gas >= 50% of total gas is high
_BREAKEVEN_HORIZON_MARGIN = 1.0    # breakeven beyond horizon => flag


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

def _total_gas_cost_usd(
    entry_gas_usd: float,
    exit_gas_usd: float,
    harvest_gas_usd: float,
    harvest_count: float,
) -> float:
    """
    Total round-trip gas cost (USD): entry + exit + harvest_count * harvest gas.

    All components are floored at 0 (gas cannot be negative); harvest_count is
    floored at 0.
    """
    entry = max(0.0, entry_gas_usd)
    exit_ = max(0.0, exit_gas_usd)
    harvest = max(0.0, harvest_gas_usd)
    count = max(0.0, harvest_count)
    return entry + exit_ + harvest * count


def _gross_yield_usd(
    principal_usd: float,
    net_apr_pct: float,
    holding_days: float,
) -> float:
    """
    Gross yield (USD) earned over the holding horizon (simple, not compounded).

        gross = principal * (apr/100) * (holding_days / 365)

    Defensive: principal and holding_days are floored at 0.
    """
    p = max(0.0, principal_usd)
    days = max(0.0, holding_days)
    return p * (net_apr_pct / 100.0) * (days / _DAYS_PER_YEAR)


def _net_yield_usd(gross_yield_usd: float, total_gas_cost_usd: float) -> float:
    """Net yield after gas: gross yield minus total round-trip gas (can be <0)."""
    return gross_yield_usd - total_gas_cost_usd


def _net_yield_after_gas_apr_pct(
    net_yield_usd: float,
    principal_usd: float,
    holding_days: float,
) -> float:
    """
    Annualised net APR after gas drag, in pct.

        net_apr = (net_yield / principal) * (365 / holding_days) * 100

    Defensive: a non-positive principal or holding_days yields 0.0 (no
    meaningful annualisation possible).
    """
    p = max(0.0, principal_usd)
    days = max(0.0, holding_days)
    if p <= _EPS or days <= _EPS:
        return 0.0
    return (net_yield_usd / p) * (_DAYS_PER_YEAR / days) * 100.0


def _gas_drag_pct_of_gross(
    total_gas_cost_usd: float,
    gross_yield_usd: float,
) -> float:
    """
    Gas as a share of gross yield, in pct (0..>100; capped reporting at 999.0).

        drag = total_gas / gross_yield * 100

    Defensive: when gross yield is ~0 but gas is positive, the drag is
    effectively infinite — we report a large sentinel (999.0). When both are ~0
    the drag is 0.0.
    """
    gas = max(0.0, total_gas_cost_usd)
    gross = gross_yield_usd
    if gross <= _EPS:
        return 0.0 if gas <= _EPS else 999.0
    return gas / gross * 100.0


def _breakeven_holding_days(
    principal_usd: float,
    net_apr_pct: float,
    total_gas_cost_usd: float,
) -> float:
    """
    Days the position must be held for yield to cover the round-trip gas.

        daily_yield = principal * (apr/100) / 365
        breakeven_days = total_gas / daily_yield

    Defensive: when the daily yield is <= 0 (no/negative APR or no principal)
    the position never breaks even — return BREAKEVEN_SENTINEL_NEVER. When gas
    is ~0 the breakeven is immediate (0.0 days).
    """
    gas = max(0.0, total_gas_cost_usd)
    if gas <= _EPS:
        return 0.0
    p = max(0.0, principal_usd)
    daily_yield = p * (net_apr_pct / 100.0) / _DAYS_PER_YEAR
    if daily_yield <= _EPS:
        return BREAKEVEN_SENTINEL_NEVER
    return gas / daily_yield


def _breakeven_position_size_usd(
    net_apr_pct: float,
    holding_days: float,
    total_gas_cost_usd: float,
) -> float:
    """
    Minimum principal at which the position clears its gas over the horizon.

    Solving gross_yield(principal) = total_gas for principal::

        principal * (apr/100) * (days/365) = total_gas
        principal = total_gas / [(apr/100) * (days/365)]

    Defensive: when the yield-per-dollar over the horizon is <= 0 (no/negative
    APR or zero horizon) no finite principal clears gas — return
    BREAKEVEN_SENTINEL_NEVER. When gas is ~0 any size works (0.0).
    """
    gas = max(0.0, total_gas_cost_usd)
    if gas <= _EPS:
        return 0.0
    days = max(0.0, holding_days)
    yield_per_dollar = (net_apr_pct / 100.0) * (days / _DAYS_PER_YEAR)
    if yield_per_dollar <= _EPS:
        return BREAKEVEN_SENTINEL_NEVER
    return gas / yield_per_dollar


def _gas_efficiency_score(
    gas_drag_pct_of_gross: float,
    net_yield_usd: float,
    breakeven_holding_days: float,
    holding_days: float,
    has_data: bool,
) -> float:
    """
    0-100: higher = gas is a small drag / the position is worth opening.

    Blends three drivers:
    - inverse drag-share (0-55): one minus gas/gross-yield, so a small gas drag
      contributes the full 55; a drag at/above 100% contributes 0.
    - net-yield-positive (0-25): full 25 when net yield is positive, scaled down
      to 0 as net yield goes negative (relative to gross-yield magnitude).
    - breakeven-within-horizon (0-20): full 20 when the position breaks even
      comfortably within the intended holding horizon; 0 when it never does.

    Returns 0.0 when there is no usable data.
    """
    if not has_data:
        return 0.0

    # Inverse drag share (0..1): clamp drag to [0,100]% then invert.
    drag_share = _clamp(gas_drag_pct_of_gross / 100.0, 0.0, 1.0)
    drag_component = (1.0 - drag_share) * 55.0

    # Net-yield component: positive => full; negative => decays to 0.
    if net_yield_usd >= 0.0:
        net_component = 25.0
    else:
        net_component = 0.0

    # Breakeven-within-horizon component.
    days = max(0.0, holding_days)
    if breakeven_holding_days >= BREAKEVEN_SENTINEL_NEVER:
        be_component = 0.0
    elif days <= _EPS:
        be_component = 0.0
    else:
        be_ratio = _clamp(breakeven_holding_days / days, 0.0, 1.0)
        be_component = (1.0 - be_ratio) * 20.0

    return _clamp(drag_component + net_component + be_component)


def _classify(gas_drag_pct_of_gross: float, has_data: bool) -> str:
    """
    Assign an advisory classification band on gas drag share of gross yield.

      < 5    -> GAS_NEGLIGIBLE
      < 20   -> GAS_MINOR
      < 50   -> GAS_MODERATE
      < 90   -> GAS_HEAVY
      >= 90  -> GAS_PROHIBITIVE

    No data falls back to GAS_PROHIBITIVE (cannot demonstrate the gas is small).
    """
    if not has_data:
        return CLASS_GAS_PROHIBITIVE

    drag = gas_drag_pct_of_gross
    if drag < _GAS_NEGLIGIBLE_DRAG_PCT:
        return CLASS_GAS_NEGLIGIBLE
    if drag < _GAS_MINOR_DRAG_PCT:
        return CLASS_GAS_MINOR
    if drag < _GAS_MODERATE_DRAG_PCT:
        return CLASS_GAS_MODERATE
    if drag < _GAS_HEAVY_DRAG_PCT:
        return CLASS_GAS_HEAVY
    return CLASS_GAS_PROHIBITIVE


def _grade(gas_efficiency_score: float) -> str:
    """Map gas_efficiency_score (higher = better) to an A-F letter grade."""
    s = gas_efficiency_score
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
    gas_drag_pct_of_gross: float,
    net_yield_usd: float,
    breakeven_holding_days: float,
    breakeven_position_size_usd: float,
    principal_usd: float,
    holding_days: float,
    total_gas_cost_usd: float,
    harvest_gas_total_usd: float,
    classification: str,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if gas_drag_pct_of_gross >= 100.0:
        flags.append(FLAG_GAS_EXCEEDS_YIELD)

    if net_yield_usd < 0.0:
        flags.append(FLAG_NEGATIVE_NET_YIELD)

    if breakeven_holding_days >= BREAKEVEN_SENTINEL_NEVER:
        flags.append(FLAG_NEVER_BREAKS_EVEN)
    elif breakeven_holding_days > holding_days * _BREAKEVEN_HORIZON_MARGIN:
        flags.append(FLAG_BREAKEVEN_AFTER_HORIZON)

    # Position too small: the breakeven principal exceeds the actual principal.
    if (breakeven_position_size_usd < BREAKEVEN_SENTINEL_NEVER
            and principal_usd > _EPS
            and breakeven_position_size_usd > principal_usd):
        flags.append(FLAG_POSITION_TOO_SMALL)

    # High harvest drag: harvest gas is a big share of total gas.
    if (total_gas_cost_usd > _EPS
            and harvest_gas_total_usd / total_gas_cost_usd >= _HIGH_HARVEST_DRAG_SHARE):
        flags.append(FLAG_HIGH_HARVEST_DRAG)

    if classification == CLASS_GAS_NEGLIGIBLE:
        flags.append(FLAG_GAS_NEGLIGIBLE)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    total_gas_cost_usd: float,
    gross_yield_usd: float,
    net_yield_usd: float,
    breakeven_holding_days: float,
    breakeven_position_size_usd: float,
    net_apr_after_gas_pct: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: no principal/APR/gas signal or data marked "
            "unreliable. Cannot assess gas-cost breakeven for this position."
        )
        return recs

    if classification == CLASS_GAS_PROHIBITIVE:
        recs.append(
            f"Gas prohibitive: ~${total_gas_cost_usd:,.2f} of round-trip gas "
            f"swallows nearly all (or more than) the ~${gross_yield_usd:,.2f} "
            "gross yield. This position is likely not worth opening at this "
            "size/horizon."
        )
    elif classification == CLASS_GAS_HEAVY:
        recs.append(
            f"Gas heavy: round-trip gas of ~${total_gas_cost_usd:,.2f} eats a "
            "large share of gross yield. Consider a larger position, a longer "
            "hold, or a cheaper chain."
        )
    elif classification == CLASS_GAS_MODERATE:
        recs.append(
            f"Gas moderate: net yield after gas is ~${net_yield_usd:,.2f} "
            f"(~{net_apr_after_gas_pct:.2f}% APR). Worth opening but the gas "
            "drag is material."
        )
    elif classification == CLASS_GAS_MINOR:
        recs.append(
            f"Gas minor: net yield after gas ~${net_yield_usd:,.2f} "
            f"(~{net_apr_after_gas_pct:.2f}% APR); gas is a small drag."
        )
    else:  # GAS_NEGLIGIBLE
        recs.append(
            f"Gas negligible: round-trip gas barely dents the yield; net APR "
            f"after gas ~{net_apr_after_gas_pct:.2f}%. Comfortably worth "
            "opening."
        )

    if FLAG_NEVER_BREAKS_EVEN in flags:
        recs.append(
            "Never breaks even: at the current APR and principal the position "
            "earns no (or negative) yield, so gas is never recovered."
        )
    elif FLAG_BREAKEVEN_AFTER_HORIZON in flags:
        recs.append(
            f"Breaks even only after the intended horizon: ~"
            f"{breakeven_holding_days:.1f} days are needed to clear gas. Plan "
            "to hold at least that long or skip the trade."
        )

    if FLAG_POSITION_TOO_SMALL in flags:
        recs.append(
            f"Position too small: a principal of at least ~"
            f"${breakeven_position_size_usd:,.2f} is needed to clear the gas "
            "over this horizon. Size up or batch with other positions."
        )

    if FLAG_HIGH_HARVEST_DRAG in flags:
        recs.append(
            "High harvest drag: most of the gas is recurring harvest/compound "
            "cost. Harvest less frequently or use an auto-compounder to cut "
            "the running gas."
        )

    if FLAG_NEGATIVE_NET_YIELD in flags:
        recs.append(
            f"Negative net yield: after gas the position loses ~"
            f"${-net_yield_usd:,.2f} over the horizon. Do not open as "
            "configured."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    token: dict | None = None,
    config: dict | None = None,
    *,
    principal_usd: float | None = None,
    net_apr_pct: float | None = None,
    holding_days: float | None = None,
    entry_gas_usd: float | None = None,
    exit_gas_usd: float | None = None,
    harvest_gas_usd: float | None = None,
    harvest_count: float | None = None,
    data_quality: Any = None,
    name: str | None = None,
) -> dict:
    """
    Analyse the gas-cost breakeven of a single yield position.

    Inputs may be supplied as a ``token`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    Recognised keys / keywords (all with safe defaults):
    - name              : str
    - principal_usd     : float (position size)
    - net_apr_pct       : float (net yield APR before gas)
    - holding_days      : float (intended holding horizon, default 30)
    - entry_gas_usd     : float (one-off entry gas: approve + deposit)
    - exit_gas_usd      : float (one-off exit gas: withdraw)
    - harvest_gas_usd   : float (per-harvest gas)
    - harvest_count     : float (number of harvest/compound txns over horizon)
    - data_quality      : truthy/"ok" => trusted; falsy/"poor" => not

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

    principal = max(0.0, _pick(principal_usd, "principal_usd", 0.0))
    apr = _pick(net_apr_pct, "net_apr_pct", 0.0)
    days = max(0.0, _pick(holding_days, "holding_days", _DEFAULT_HOLDING_DAYS))
    entry_gas = max(0.0, _pick(entry_gas_usd, "entry_gas_usd", _DEFAULT_ENTRY_GAS_USD))
    exit_gas = max(0.0, _pick(exit_gas_usd, "exit_gas_usd", _DEFAULT_EXIT_GAS_USD))
    harvest_gas = max(0.0, _pick(harvest_gas_usd, "harvest_gas_usd", _DEFAULT_HARVEST_GAS_USD))
    harvest_n = max(0.0, _pick(harvest_count, "harvest_count", _DEFAULT_HARVEST_COUNT))

    dq_raw = data_quality if data_quality is not None else t.get("data_quality", "ok")
    if isinstance(dq_raw, str):
        data_quality_ok = dq_raw.strip().lower() not in ("poor", "bad", "low", "")
    else:
        data_quality_ok = bool(dq_raw)

    # Data sufficiency: need a principal signal and some gas or APR signal, and
    # the data-quality flag must not mark the inputs as unreliable.
    total_gas = _total_gas_cost_usd(entry_gas, exit_gas, harvest_gas, harvest_n)
    harvest_gas_total = max(0.0, harvest_gas) * max(0.0, harvest_n)
    has_signal = (
        principal > _EPS
        and (total_gas > _EPS or abs(apr) > _EPS)
    )
    has_data = has_signal and data_quality_ok

    gross = _gross_yield_usd(principal, apr, days)
    net = _net_yield_usd(gross, total_gas)
    net_apr_after_gas = _net_yield_after_gas_apr_pct(net, principal, days)
    drag = _gas_drag_pct_of_gross(total_gas, gross)
    be_days = _breakeven_holding_days(principal, apr, total_gas)
    be_size = _breakeven_position_size_usd(apr, days, total_gas)
    classification = _classify(drag, has_data)
    score = _gas_efficiency_score(drag, net, be_days, days, has_data)
    grade = _grade(score)
    flags = _flags(
        drag,
        net,
        be_days,
        be_size,
        principal,
        days,
        total_gas,
        harvest_gas_total,
        classification,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        total_gas,
        gross,
        net,
        be_days,
        be_size,
        net_apr_after_gas,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "principal_usd": principal,
        "net_apr_pct": apr,
        "holding_days": days,
        "entry_gas_usd": entry_gas,
        "exit_gas_usd": exit_gas,
        "harvest_gas_usd": harvest_gas,
        "harvest_count": harvest_n,
        "data_quality_ok": data_quality_ok,
        "total_gas_cost_usd": total_gas,
        "harvest_gas_total_usd": harvest_gas_total,
        "gross_yield_usd": gross,
        "net_yield_usd": net,
        "net_yield_after_gas_apr_pct": net_apr_after_gas,
        "gas_drag_pct_of_gross": drag,
        "breakeven_holding_days": be_days,
        "breakeven_position_size_usd": be_size,
        "gas_efficiency_score": score,
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
    Analyse gas-cost breakeven across a batch of positions and summarise.

    Returns
    -------
    dict
        - total_positions             : int
        - results                     : list[dict]  (per-position analysis)
        - most_gas_efficient_position : str | None  (highest efficiency score)
        - least_gas_efficient_position: str | None  (lowest efficiency score)
        - avg_gas_efficiency_score    : float
        - negative_net_yield_count    : int
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
            "most_gas_efficient_position": None,
            "least_gas_efficient_position": None,
            "avg_gas_efficiency_score": 0.0,
            "negative_net_yield_count": 0,
            "timestamp": time.time(),
        }

    most = max(results, key=lambda r: r["gas_efficiency_score"])
    least = min(results, key=lambda r: r["gas_efficiency_score"])
    avg = sum(r["gas_efficiency_score"] for r in results) / total
    neg = sum(1 for r in results if r["net_yield_usd"] < 0.0)

    return {
        "total_positions": total,
        "results": results,
        "most_gas_efficient_position": most["name"],
        "least_gas_efficient_position": least["name"],
        "avg_gas_efficiency_score": avg,
        "negative_net_yield_count": neg,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolGasCostBreakevenAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = DeFiProtocolGasCostBreakevenAnalyzer()
    >>> r = a.analyze({"name": "USDC-LP", "principal_usd": 500.0,
    ...                "net_apr_pct": 6.0, "entry_gas_usd": 40.0,
    ...                "exit_gas_usd": 40.0})
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
            "name": "USDC-LP (small, expensive)",
            "principal_usd": 500.0,
            "net_apr_pct": 6.0,
            "holding_days": 30.0,
            "entry_gas_usd": 40.0,
            "exit_gas_usd": 40.0,
            "harvest_gas_usd": 15.0,
            "harvest_count": 4.0,
        },
        {
            "name": "stETH (large, cheap)",
            "principal_usd": 250000.0,
            "net_apr_pct": 4.0,
            "holding_days": 180.0,
            "entry_gas_usd": 12.0,
            "exit_gas_usd": 12.0,
            "harvest_gas_usd": 0.0,
            "harvest_count": 0.0,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_positions[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_positions)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
