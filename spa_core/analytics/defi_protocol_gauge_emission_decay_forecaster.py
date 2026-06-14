"""
MP-1074  DeFiProtocolGaugeEmissionDecayForecaster
--------------------------------------------------
Forecast how a gauge's incentive emissions decay over time and the resulting
incentive-APY cliff for an LP who depends on those emissions.

Many ve(3,3) / gauge-style protocols emit reward tokens on a schedule that
decays week over week. An LP whose yield leans heavily on those emissions
faces a falling incentive APR — and, eventually, an "incentive-APY cliff" when
emissions drop below the gauge's emission floor or below the pool's own base
(non-incentive) yield. This module quantifies:

  (a) the current and horizon-projected incentive APR,
  (b) the incentive-APR half-life (weeks until incentive APR halves),
  (c) how dependent total yield is on emissions today, and
  (d) the severity of the resulting APR cliff.

Genuine gap: existing gauge / bribe modules cover bribe efficiency and
vote markets, but none forecast gauge emission decay or incentive-APY cliffs.

The module returns:
- current_incentive_apr_pct           – incentive APR today
- projected_incentive_apr_at_horizon_pct – incentive APR at the horizon
- incentive_apr_half_life_weeks       – weeks until incentive APR halves
- total_apr_now_pct                   – base + incentive APR today
- total_apr_at_horizon_pct            – base + incentive APR at horizon
- incentive_dependence_pct            – incentive / total APR today
- weeks_until_incentive_below_base    – weeks until incentive APR < base yield
- apr_cliff_severity_score            – 0-100, higher = sharper cliff
- classification                      – STABLE .. EMISSION_CLIFF
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
    "gauge_emission_decay_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Sentinel: weeks-based metrics that never trigger within a reasonable horizon.
_NEVER_WEEKS = 9999.0

# Weeks per year used to annualise weekly emission value into an APR.
_WEEKS_PER_YEAR = 52.0

# Classification bands
CLASS_STABLE = "STABLE"
CLASS_GENTLE_DECAY = "GENTLE_DECAY"
CLASS_MODERATE_DECAY = "MODERATE_DECAY"
CLASS_STEEP_DECAY = "STEEP_DECAY"
CLASS_EMISSION_CLIFF = "EMISSION_CLIFF"

ALL_CLASSIFICATIONS = (
    CLASS_STABLE,
    CLASS_GENTLE_DECAY,
    CLASS_MODERATE_DECAY,
    CLASS_STEEP_DECAY,
    CLASS_EMISSION_CLIFF,
)

# Flags
FLAG_HIGH_INCENTIVE_DEPENDENCE = "HIGH_INCENTIVE_DEPENDENCE"
FLAG_STEEP_DECAY = "STEEP_DECAY"
FLAG_FAST_HALF_LIFE = "FAST_HALF_LIFE"
FLAG_INCENTIVE_BELOW_BASE_SOON = "INCENTIVE_BELOW_BASE_SOON"
FLAG_EMISSION_FLOOR_SUPPORT = "EMISSION_FLOOR_SUPPORT"
FLAG_LOW_REWARD_TOKEN_PRICE_RISK = "LOW_REWARD_TOKEN_PRICE_RISK"
FLAG_STABLE_EMISSIONS = "STABLE_EMISSIONS"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_HIGH_INCENTIVE_DEPENDENCE,
    FLAG_STEEP_DECAY,
    FLAG_FAST_HALF_LIFE,
    FLAG_INCENTIVE_BELOW_BASE_SOON,
    FLAG_EMISSION_FLOOR_SUPPORT,
    FLAG_LOW_REWARD_TOKEN_PRICE_RISK,
    FLAG_STABLE_EMISSIONS,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds
_HIGH_DEPENDENCE_PCT = 60.0        # incentive >= 60% of total APR is high
_STEEP_DECAY_PCT_PER_WEEK = 3.0    # > 3 %/wk decay is steep
_MODERATE_DECAY_PCT_PER_WEEK = 1.0  # > 1 %/wk decay is moderate
_GENTLE_DECAY_PCT_PER_WEEK = 0.05  # > 0.05 %/wk counts as (gentle) decay
_FAST_HALF_LIFE_WEEKS = 26.0       # half-life under 26 wks is fast
_INCENTIVE_BELOW_BASE_SOON_WEEKS = 26.0  # crosses base within 26 wks is soon
_LOW_REWARD_PRICE_USD = 0.01       # reward token < $0.01 is price-fragile


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

def _incentive_apr_pct(
    emission_tokens_per_week: float,
    reward_token_price_usd: float,
    gauge_share_pct: float,
    lp_tvl_usd: float,
) -> float:
    """
    Incentive APR (in pct) earned by an LP from gauge emissions.

    apr = (weekly_emission * price * share% * 52) / lp_tvl * 100

    Returns 0.0 when lp_tvl_usd <= 0 (avoids div-by-zero).
    """
    if lp_tvl_usd <= 0:
        return 0.0
    annual_reward_usd = (
        max(0.0, emission_tokens_per_week)
        * max(0.0, reward_token_price_usd)
        * gauge_share_pct / 100.0
        * _WEEKS_PER_YEAR
    )
    return annual_reward_usd / lp_tvl_usd * 100.0


def _project_emission_tokens(
    current_emission_tokens_per_week: float,
    emission_decay_pct_per_week: float,
    weeks: float,
    emission_floor_tokens_per_week: float,
) -> float:
    """
    Project the weekly emission *weeks* into the future under geometric decay,
    never falling below the emission floor.

    emission(t) = current * (1 - decay%)^t, floored at the emission floor.
    A negative "decay" (growth) is permitted and simply compounds upward.
    """
    factor = 1.0 - emission_decay_pct_per_week / 100.0
    # Guard against a pathological factor that would explode/oscillate.
    if factor <= 0.0:
        projected = max(0.0, emission_floor_tokens_per_week)
        return projected
    projected = max(0.0, current_emission_tokens_per_week) * (factor ** max(0.0, weeks))
    return max(projected, max(0.0, emission_floor_tokens_per_week))


def _incentive_apr_half_life_weeks(
    emission_decay_pct_per_week: float,
    current_emission_tokens_per_week: float,
    emission_floor_tokens_per_week: float,
) -> float:
    """
    Weeks until the incentive APR halves under geometric emission decay.

    Because incentive APR is linear in the weekly emission (price, share and
    TVL held constant), the APR half-life equals the emission half-life:

        half_life = ln(0.5) / ln(1 - decay%)

    Returns the _NEVER_WEEKS sentinel when emissions do not decay (decay <= 0)
    or when the emission floor already sits at/above half the current emission
    (the APR can never halve). Defensive against log-domain errors.
    """
    if emission_decay_pct_per_week <= 0.0:
        return _NEVER_WEEKS

    half_target = current_emission_tokens_per_week / 2.0
    # If the floor holds emissions at or above half, APR can never halve.
    if emission_floor_tokens_per_week >= half_target:
        return _NEVER_WEEKS

    factor = 1.0 - emission_decay_pct_per_week / 100.0
    if factor <= 0.0:
        # One step collapses to (at least) the floor → effectively immediate.
        return 1.0

    import math
    try:
        weeks = math.log(0.5) / math.log(factor)
    except (ValueError, ZeroDivisionError):
        return _NEVER_WEEKS
    if weeks <= 0.0:
        return _NEVER_WEEKS
    return min(weeks, _NEVER_WEEKS)


def _weeks_until_incentive_below_base(
    current_incentive_apr_pct: float,
    base_yield_apr_pct: float,
    emission_decay_pct_per_week: float,
    current_emission_tokens_per_week: float,
    emission_floor_tokens_per_week: float,
) -> float:
    """
    Weeks until the (decaying) incentive APR drops below the base yield APR.

    Incentive APR scales with the weekly emission, so the crossing happens when

        emission(t) / current_emission == base_apr / current_incentive_apr

    Returns 0.0 if incentive APR is already below base, and the _NEVER_WEEKS
    sentinel if it never crosses (no decay, or the floor holds it above base).
    Defensive against zero/negative inputs and log-domain errors.
    """
    if current_incentive_apr_pct <= base_yield_apr_pct:
        return 0.0
    if emission_decay_pct_per_week <= 0.0:
        return _NEVER_WEEKS
    if current_incentive_apr_pct <= _EPS:
        return _NEVER_WEEKS

    # The emission fraction at which incentive APR equals base yield.
    target_fraction = base_yield_apr_pct / current_incentive_apr_pct
    target_fraction = _clamp(target_fraction, 0.0, 1.0)

    # If the emission floor keeps emissions above the crossing fraction, never.
    if current_emission_tokens_per_week > 0.0:
        floor_fraction = (
            emission_floor_tokens_per_week / current_emission_tokens_per_week
        )
        if floor_fraction >= target_fraction:
            return _NEVER_WEEKS

    factor = 1.0 - emission_decay_pct_per_week / 100.0
    if factor <= 0.0:
        return 1.0
    if target_fraction <= _EPS:
        return _NEVER_WEEKS

    import math
    try:
        weeks = math.log(target_fraction) / math.log(factor)
    except (ValueError, ZeroDivisionError):
        return _NEVER_WEEKS
    if weeks <= 0.0:
        return 0.0
    return min(weeks, _NEVER_WEEKS)


def _incentive_dependence_pct(
    current_incentive_apr_pct: float,
    base_yield_apr_pct: float,
) -> float:
    """
    Share of total APR today that comes from incentives, in pct.

    Returns 0.0 when total APR is ~0 (avoids div-by-zero).
    """
    total = current_incentive_apr_pct + base_yield_apr_pct
    if total <= _EPS:
        return 0.0
    return _clamp(current_incentive_apr_pct / total * 100.0)


def _apr_cliff_severity_score(
    incentive_dependence_pct: float,
    emission_decay_pct_per_week: float,
    incentive_apr_drop_pct: float,
    has_data: bool,
) -> float:
    """
    0-100: higher = sharper incentive-APR cliff.

    Blends three drivers:
    - dependence (0-40): how much total yield leans on incentives today,
    - decay speed (0-35): saturating at the steep-decay threshold,
    - realised drop (0-25): fraction of incentive APR lost by the horizon.

    Returns 0.0 when there is no usable data.
    """
    if not has_data:
        return 0.0

    dependence_component = _clamp(incentive_dependence_pct / 100.0, 0.0, 1.0) * 40.0

    decay_frac = _clamp(
        max(0.0, emission_decay_pct_per_week) / _STEEP_DECAY_PCT_PER_WEEK,
        0.0, 1.0,
    )
    decay_component = decay_frac * 35.0

    drop_component = _clamp(incentive_apr_drop_pct / 100.0, 0.0, 1.0) * 25.0

    return _clamp(dependence_component + decay_component + drop_component)


def _classify(
    emission_decay_pct_per_week: float,
    apr_cliff_severity_score: float,
    weeks_until_incentive_below_base: float,
    has_data: bool,
) -> str:
    """
    Assign an advisory decay classification band.

    Priority (highest to lowest):
    1. EMISSION_CLIFF  – steep decay AND a high cliff-severity score, or the
                         incentive crosses below base very soon.
    2. STEEP_DECAY     – decay above the steep threshold.
    3. MODERATE_DECAY  – decay above the moderate threshold.
    4. GENTLE_DECAY    – any meaningful decay below moderate.
    5. STABLE          – emissions effectively flat (or growing).

    No data falls back to STABLE (no decay can be demonstrated).
    """
    if not has_data:
        return CLASS_STABLE

    soon_cross = (
        0.0 < weeks_until_incentive_below_base <= 8.0
    )

    if (
        emission_decay_pct_per_week >= _STEEP_DECAY_PCT_PER_WEEK
        and apr_cliff_severity_score >= 70.0
    ) or soon_cross:
        return CLASS_EMISSION_CLIFF

    if emission_decay_pct_per_week >= _STEEP_DECAY_PCT_PER_WEEK:
        return CLASS_STEEP_DECAY

    if emission_decay_pct_per_week >= _MODERATE_DECAY_PCT_PER_WEEK:
        return CLASS_MODERATE_DECAY

    if emission_decay_pct_per_week >= _GENTLE_DECAY_PCT_PER_WEEK:
        return CLASS_GENTLE_DECAY

    return CLASS_STABLE


def _grade(apr_cliff_severity_score: float) -> str:
    """Map cliff-severity (higher = worse) to an A-F letter grade."""
    s = apr_cliff_severity_score
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
    incentive_dependence_pct: float,
    emission_decay_pct_per_week: float,
    incentive_apr_half_life_weeks: float,
    weeks_until_incentive_below_base: float,
    emission_floor_tokens_per_week: float,
    projected_emission_at_horizon: float,
    reward_token_price_usd: float,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if incentive_dependence_pct >= _HIGH_DEPENDENCE_PCT:
        flags.append(FLAG_HIGH_INCENTIVE_DEPENDENCE)

    if emission_decay_pct_per_week >= _STEEP_DECAY_PCT_PER_WEEK:
        flags.append(FLAG_STEEP_DECAY)

    if 0.0 < incentive_apr_half_life_weeks <= _FAST_HALF_LIFE_WEEKS:
        flags.append(FLAG_FAST_HALF_LIFE)

    if 0.0 < weeks_until_incentive_below_base <= _INCENTIVE_BELOW_BASE_SOON_WEEKS:
        flags.append(FLAG_INCENTIVE_BELOW_BASE_SOON)

    # Floor is supporting emissions if the projected emission has bottomed out
    # at the (positive) floor.
    if (
        emission_floor_tokens_per_week > 0.0
        and projected_emission_at_horizon <= emission_floor_tokens_per_week + _EPS
    ):
        flags.append(FLAG_EMISSION_FLOOR_SUPPORT)

    if 0.0 < reward_token_price_usd < _LOW_REWARD_PRICE_USD:
        flags.append(FLAG_LOW_REWARD_TOKEN_PRICE_RISK)

    if emission_decay_pct_per_week < _GENTLE_DECAY_PCT_PER_WEEK:
        flags.append(FLAG_STABLE_EMISSIONS)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    current_incentive_apr_pct: float,
    projected_incentive_apr_at_horizon_pct: float,
    incentive_dependence_pct: float,
    incentive_apr_half_life_weeks: float,
    weeks_until_incentive_below_base: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: lp_tvl_usd <= 0 or no emissions supplied. "
            "Cannot forecast gauge emission decay for this position."
        )
        return recs

    if classification == CLASS_EMISSION_CLIFF:
        recs.append(
            f"EMISSION CLIFF: incentive APR falls from "
            f"{current_incentive_apr_pct:.2f}% toward "
            f"{projected_incentive_apr_at_horizon_pct:.2f}% over the horizon. "
            "Plan an exit or rotation before the cliff materialises."
        )
    elif classification == CLASS_STEEP_DECAY:
        recs.append(
            f"Steep emission decay: incentive APR drops from "
            f"{current_incentive_apr_pct:.2f}% to "
            f"{projected_incentive_apr_at_horizon_pct:.2f}% by the horizon. "
            "Treat the current APR as transient."
        )
    elif classification == CLASS_MODERATE_DECAY:
        recs.append(
            f"Moderate emission decay: incentive APR declines from "
            f"{current_incentive_apr_pct:.2f}% to "
            f"{projected_incentive_apr_at_horizon_pct:.2f}% over the horizon. "
            "Monitor emissions and re-underwrite periodically."
        )
    elif classification == CLASS_GENTLE_DECAY:
        recs.append(
            f"Gentle emission decay: incentive APR eases from "
            f"{current_incentive_apr_pct:.2f}% to "
            f"{projected_incentive_apr_at_horizon_pct:.2f}% over the horizon. "
            "Decay is mild and unlikely to drive an abrupt cliff."
        )
    else:  # STABLE
        recs.append(
            f"Emissions are effectively stable; incentive APR stays near "
            f"{current_incentive_apr_pct:.2f}% over the horizon. "
            "No emission-driven APR cliff is forecast."
        )

    if FLAG_HIGH_INCENTIVE_DEPENDENCE in flags:
        recs.append(
            f"High incentive dependence ({incentive_dependence_pct:.0f}% of total "
            "APR): yield relies on emissions and is exposed to their decay."
        )

    if FLAG_FAST_HALF_LIFE in flags:
        recs.append(
            f"Fast incentive half-life (~{incentive_apr_half_life_weeks:.0f} weeks): "
            "incentive APR halves quickly under the current decay rate."
        )

    if FLAG_INCENTIVE_BELOW_BASE_SOON in flags:
        recs.append(
            f"Incentive APR drops below base yield in ~"
            f"{weeks_until_incentive_below_base:.0f} weeks; after that, base "
            "yield is the dominant return driver."
        )

    if FLAG_EMISSION_FLOOR_SUPPORT in flags:
        recs.append(
            "Emissions reach the configured floor within the horizon, which "
            "caps further incentive-APR decay at the floor level."
        )

    if FLAG_LOW_REWARD_TOKEN_PRICE_RISK in flags:
        recs.append(
            "Reward token price is very low; incentive APR is fragile to "
            "further reward-token price declines on top of emission decay."
        )

    if FLAG_STABLE_EMISSIONS in flags and classification == CLASS_STABLE:
        recs.append(
            "Stable emissions: the gauge is not on a meaningful decay schedule "
            "at the supplied rate."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    gauge: dict | None = None,
    config: dict | None = None,
    *,
    current_emission_tokens_per_week: float | None = None,
    emission_decay_pct_per_week: float | None = None,
    reward_token_price_usd: float | None = None,
    lp_tvl_usd: float | None = None,
    base_yield_apr_pct: float | None = None,
    weeks_horizon: float | None = None,
    gauge_share_pct: float | None = None,
    emission_floor_tokens_per_week: float | None = None,
    name: str | None = None,
) -> dict:
    """
    Forecast gauge emission decay and the incentive-APY cliff for one position.

    Inputs may be supplied as a ``gauge`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    Recognised keys / keywords (all with safe defaults):
    - name                              : str
    - current_emission_tokens_per_week  : float (>= 0)
    - emission_decay_pct_per_week       : float (e.g. 1.5 means -1.5%/wk)
    - reward_token_price_usd            : float (>= 0)
    - lp_tvl_usd                        : float (>= 0)
    - base_yield_apr_pct                : float (>= 0, non-incentive yield)
    - weeks_horizon                     : float (default 52)
    - gauge_share_pct                   : float (LP's share, default 100)
    - emission_floor_tokens_per_week    : float (>= 0, default 0)

    config : dict, optional
        - log_path : str  (override default log path)

    Returns
    -------
    dict
        Full forecast result. Never raises to the caller.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    g = gauge if isinstance(gauge, dict) else {}

    def _pick(kw: Any, key: str, default: float) -> float:
        if kw is not None:
            return _safe_float(kw, default)
        return _safe_float(g.get(key, default), default)

    name_val = name if name is not None else str(g.get("name", "UNKNOWN"))

    cur_emission = max(0.0, _pick(
        current_emission_tokens_per_week, "current_emission_tokens_per_week", 0.0))
    decay_pct = _pick(emission_decay_pct_per_week, "emission_decay_pct_per_week", 0.0)
    reward_price = max(0.0, _pick(
        reward_token_price_usd, "reward_token_price_usd", 0.0))
    tvl = max(0.0, _pick(lp_tvl_usd, "lp_tvl_usd", 0.0))
    base_apr = max(0.0, _pick(base_yield_apr_pct, "base_yield_apr_pct", 0.0))
    horizon = max(0.0, _pick(weeks_horizon, "weeks_horizon", 52.0))
    share_pct = _clamp(_pick(gauge_share_pct, "gauge_share_pct", 100.0), 0.0, 100.0)
    floor_emission = max(0.0, _pick(
        emission_floor_tokens_per_week, "emission_floor_tokens_per_week", 0.0))

    # Data sufficiency: need positive TVL and some positive emission value.
    has_data = tvl > 0 and cur_emission > 0 and reward_price > 0

    current_incentive_apr = _incentive_apr_pct(
        cur_emission, reward_price, share_pct, tvl
    )

    projected_emission = _project_emission_tokens(
        cur_emission, decay_pct, horizon, floor_emission
    )
    projected_incentive_apr = _incentive_apr_pct(
        projected_emission, reward_price, share_pct, tvl
    )

    half_life = _incentive_apr_half_life_weeks(
        decay_pct, cur_emission, floor_emission
    )
    weeks_below_base = _weeks_until_incentive_below_base(
        current_incentive_apr, base_apr, decay_pct, cur_emission, floor_emission
    )

    total_apr_now = current_incentive_apr + base_apr
    total_apr_horizon = projected_incentive_apr + base_apr
    dependence = _incentive_dependence_pct(current_incentive_apr, base_apr)

    # Realised fractional drop in incentive APR by the horizon (0-100).
    if current_incentive_apr > _EPS:
        drop_pct = _clamp(
            (current_incentive_apr - projected_incentive_apr)
            / current_incentive_apr * 100.0,
            0.0, 100.0,
        )
    else:
        drop_pct = 0.0

    severity = _apr_cliff_severity_score(
        dependence, decay_pct, drop_pct, has_data
    )
    classification = _classify(
        decay_pct, severity, weeks_below_base, has_data
    )
    grade = _grade(severity)
    flags = _flags(
        dependence,
        decay_pct,
        half_life,
        weeks_below_base,
        floor_emission,
        projected_emission,
        reward_price,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        current_incentive_apr,
        projected_incentive_apr,
        dependence,
        half_life,
        weeks_below_base,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "current_emission_tokens_per_week": cur_emission,
        "emission_decay_pct_per_week": decay_pct,
        "reward_token_price_usd": reward_price,
        "lp_tvl_usd": tvl,
        "base_yield_apr_pct": base_apr,
        "weeks_horizon": horizon,
        "gauge_share_pct": share_pct,
        "emission_floor_tokens_per_week": floor_emission,
        "projected_emission_tokens_at_horizon": projected_emission,
        "current_incentive_apr_pct": current_incentive_apr,
        "projected_incentive_apr_at_horizon_pct": projected_incentive_apr,
        "incentive_apr_half_life_weeks": half_life,
        "total_apr_now_pct": total_apr_now,
        "total_apr_at_horizon_pct": total_apr_horizon,
        "incentive_dependence_pct": dependence,
        "weeks_until_incentive_below_base": weeks_below_base,
        "incentive_apr_drop_pct": drop_pct,
        "apr_cliff_severity_score": severity,
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

def analyze_portfolio(gauges: list, config: dict | None = None) -> dict:
    """
    Forecast emission decay across a batch of gauges and summarise.

    Returns
    -------
    dict
        - total_gauges                : int
        - results                     : list[dict]  (per-gauge forecast)
        - most_at_risk_gauge          : str | None  (highest cliff severity)
        - least_at_risk_gauge         : str | None  (lowest cliff severity)
        - avg_apr_cliff_severity_score: float
        - steep_decay_count           : int
        - timestamp                   : float
    """
    if not isinstance(gauges, list):
        gauges = []

    results = [
        analyze(g if isinstance(g, dict) else {}, config=config)
        for g in gauges
    ]
    total = len(results)

    if total == 0:
        return {
            "total_gauges": 0,
            "results": [],
            "most_at_risk_gauge": None,
            "least_at_risk_gauge": None,
            "avg_apr_cliff_severity_score": 0.0,
            "steep_decay_count": 0,
            "timestamp": time.time(),
        }

    most = max(results, key=lambda r: r["apr_cliff_severity_score"])
    least = min(results, key=lambda r: r["apr_cliff_severity_score"])
    avg = sum(r["apr_cliff_severity_score"] for r in results) / total
    steep = sum(
        1 for r in results
        if r["classification"] in (CLASS_STEEP_DECAY, CLASS_EMISSION_CLIFF)
    )

    return {
        "total_gauges": total,
        "results": results,
        "most_at_risk_gauge": most["name"],
        "least_at_risk_gauge": least["name"],
        "avg_apr_cliff_severity_score": avg,
        "steep_decay_count": steep,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolGaugeEmissionDecayForecaster:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> f = DeFiProtocolGaugeEmissionDecayForecaster()
    >>> r = f.analyze({"name": "vAMM-USDC/ETH", "current_emission_tokens_per_week": 50_000, ...})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, gauge: dict | None = None, **kwargs: Any) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(gauge, config=self._config, **kwargs)

    def analyze_portfolio(self, gauges: list) -> dict:
        """Delegate to module-level ``analyze_portfolio``."""
        return analyze_portfolio(gauges, config=self._config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo_gauges = [
        {
            "name": "vAMM-USDC/ETH (steep)",
            "current_emission_tokens_per_week": 100_000.0,
            "emission_decay_pct_per_week": 4.0,
            "reward_token_price_usd": 0.50,
            "lp_tvl_usd": 2_000_000.0,
            "base_yield_apr_pct": 3.0,
            "weeks_horizon": 52,
            "gauge_share_pct": 100.0,
            "emission_floor_tokens_per_week": 0.0,
        },
        {
            "name": "Stable gauge",
            "current_emission_tokens_per_week": 20_000.0,
            "emission_decay_pct_per_week": 0.0,
            "reward_token_price_usd": 1.0,
            "lp_tvl_usd": 5_000_000.0,
            "base_yield_apr_pct": 4.0,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_gauges[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_gauges)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
