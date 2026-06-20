"""
MP-816 EmissionScheduleForecaster
Forecasts how the emission-driven portion of a protocol's APY will decay over future
periods, so the optimizer can anticipate yield decay before it happens.

Advisory/read-only module. Pure stdlib. Atomic writes via tmp + os.replace.
Data: data/emission_schedule_forecast_log.json (ring-buffer 100)
"""

import json
import math
import os
import time
from spa_core.utils.atomic import atomic_save

_DEFAULT_CONFIG = {
    "default_periods": 12,            # projection horizon when params omits "periods"
    "stable_emission_share": 20.0,    # emission share < this (%) → STABLE
    "gradual_decline_max": 30.0,      # horizon decline < this (%) → GRADUAL_DECAY
    "fast_decline_max": 60.0,         # horizon decline < this (%) → FAST_DECAY (else CLIFF)
}

_LOG_RING_SIZE = 100
_DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "emission_schedule_forecast_log.json"
)


def _clamp_decay_rate(decay_rate: float) -> float:
    """Clamp decay rate into [0, 1). A rate of 1.0+ would zero emissions instantly."""
    if decay_rate < 0.0:
        return 0.0
    if decay_rate >= 1.0:
        return 0.999999
    return decay_rate


def _half_life_periods(decay_rate: float):
    """Periods until emission falls to <=50% of current. None when no decay."""
    if decay_rate <= 0.0 or decay_rate >= 1.0:
        return None
    # (1 - decay_rate)^t <= 0.5  →  t >= log(0.5) / log(1 - decay_rate)
    return math.log(0.5) / math.log(1.0 - decay_rate)


def _classify_sustainability(
    emission_share_pct: float,
    decay_rate: float,
    decline_pct: float,
    stable_emission_share: float,
    gradual_decline_max: float,
    fast_decline_max: float,
) -> str:
    """Return sustainability category."""
    if emission_share_pct < stable_emission_share or decay_rate <= 0.0:
        return "STABLE"
    if decline_pct < gradual_decline_max:
        return "GRADUAL_DECAY"
    if decline_pct < fast_decline_max:
        return "FAST_DECAY"
    return "CLIFF"


def _compute_risk_flags(
    emission_share_pct: float,
    decay_rate: float,
    base_apy: float,
) -> list:
    """Return list of risk flag strings."""
    flags = []

    if emission_share_pct > 70.0:
        flags.append("Yield highly emission-dependent")

    if decay_rate > 0.3:
        flags.append("Rapid emission decay expected")

    if base_apy <= 0.0:
        flags.append("No real yield floor")

    return flags


def _recommendation(sustainability: str) -> str:
    """Map sustainability to human-readable recommendation."""
    return {
        "STABLE": "Favorable — emission share is small or stable, yield is durable",
        "GRADUAL_DECAY": "Acceptable — mild emission decay, monitor over the horizon",
        "FAST_DECAY": "Caution — material emission decay expected, plan a rotation",
        "CLIFF": "Avoid — emissions collapse over the horizon, yield is transient",
    }[sustainability]


def forecast(protocol: str, params: dict, config: dict = None) -> dict:
    """
    Forecast emission-driven APY decay over future periods.

    Parameters
    ----------
    protocol : str
        Protocol name (e.g. "Radiant V2").
    params : dict
        {
            "current_emission_apy": float,   # APY currently from token emissions
            "base_apy": float,               # non-emission (real) APY, ~stable
            "decay_rate_per_period": float,  # fractional decay each period (0.10 = -10%/period)
            "periods": int,                  # future periods to project (default 12)
            "period_label": str              # optional, e.g. "month" (default "period")
        }
    config : dict, optional
        Overrides for _DEFAULT_CONFIG thresholds.

    Returns
    -------
    dict with keys:
        protocol, period_label, periods, current_emission_apy, base_apy,
        current_total_apy, decay_rate_per_period, decay_rate_clamped,
        schedule, half_life_periods, terminal_emission_apy, terminal_total_apy,
        total_apy_decline_pct, current_emission_share_pct, sustainability,
        risk_flags, recommendation, timestamp
    """
    cfg = {**_DEFAULT_CONFIG, **(config or {})}
    default_periods = int(cfg.get("default_periods", _DEFAULT_CONFIG["default_periods"]))
    stable_emission_share = float(cfg.get("stable_emission_share", _DEFAULT_CONFIG["stable_emission_share"]))
    gradual_decline_max = float(cfg.get("gradual_decline_max", _DEFAULT_CONFIG["gradual_decline_max"]))
    fast_decline_max = float(cfg.get("fast_decline_max", _DEFAULT_CONFIG["fast_decline_max"]))

    current_emission_apy = float(params.get("current_emission_apy", 0.0))
    base_apy = float(params.get("base_apy", 0.0))
    raw_decay_rate = float(params.get("decay_rate_per_period", 0.0))
    periods = int(params.get("periods", default_periods))
    period_label = str(params.get("period_label", "period"))

    if periods < 0:
        periods = 0

    decay_rate = _clamp_decay_rate(raw_decay_rate)

    current_total_apy = base_apy + current_emission_apy

    # Emission share of current total
    if current_total_apy == 0.0:
        current_emission_share_pct = 0.0
    else:
        current_emission_share_pct = (current_emission_apy / current_total_apy) * 100.0

    # Build geometric-decay schedule for t = 1..periods
    schedule = []
    for t in range(1, periods + 1):
        emission_t = current_emission_apy * ((1.0 - decay_rate) ** t)
        total_t = base_apy + emission_t
        schedule.append({
            "period": t,
            "emission_apy": emission_t,
            "total_apy": total_t,
        })

    if schedule:
        terminal_emission_apy = schedule[-1]["emission_apy"]
        terminal_total_apy = schedule[-1]["total_apy"]
    else:
        terminal_emission_apy = current_emission_apy
        terminal_total_apy = current_total_apy

    # Total APY decline over the horizon
    if current_total_apy == 0.0:
        total_apy_decline_pct = 0.0
    else:
        total_apy_decline_pct = (
            (current_total_apy - terminal_total_apy) / current_total_apy
        ) * 100.0

    half_life = _half_life_periods(decay_rate)

    sustainability = _classify_sustainability(
        current_emission_share_pct,
        decay_rate,
        total_apy_decline_pct,
        stable_emission_share,
        gradual_decline_max,
        fast_decline_max,
    )

    risk_flags = _compute_risk_flags(
        current_emission_share_pct,
        decay_rate,
        base_apy,
    )

    result = {
        "protocol": protocol,
        "period_label": period_label,
        "periods": periods,
        "current_emission_apy": current_emission_apy,
        "base_apy": base_apy,
        "current_total_apy": current_total_apy,
        "decay_rate_per_period": raw_decay_rate,
        "decay_rate_clamped": decay_rate,
        "schedule": schedule,
        "half_life_periods": half_life,
        "terminal_emission_apy": terminal_emission_apy,
        "terminal_total_apy": terminal_total_apy,
        "total_apy_decline_pct": total_apy_decline_pct,
        "current_emission_share_pct": current_emission_share_pct,
        "sustainability": sustainability,
        "risk_flags": risk_flags,
        "recommendation": _recommendation(sustainability),
        "timestamp": time.time(),
    }

    return result


def log_result(result: dict, log_path: str = None) -> None:
    """Append result to ring-buffer JSON log (max 100 entries). Atomic write."""
    if log_path is None:
        log_path = _DEFAULT_LOG_PATH

    # Load existing log
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                log = json.load(f)
        except (json.JSONDecodeError, OSError):
            log = []
    else:
        log = []

    log.append(result)

    # Ring-buffer cap
    if len(log) > _LOG_RING_SIZE:
        log = log[-_LOG_RING_SIZE:]

    # Atomic write
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    atomic_save(log, str(log_path))
def forecast_and_log(protocol: str, params: dict, config: dict = None, log_path: str = None) -> dict:
    """forecast() + log_result(). Returns the result dict."""
    result = forecast(protocol, params, config)
    log_result(result, log_path)
    return result


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    _example_params = {
        "current_emission_apy": 6.0,
        "base_apy": 3.0,
        "decay_rate_per_period": 0.10,
        "periods": 12,
        "period_label": "month",
    }

    result = forecast("Radiant V2", _example_params)
    json.dump(result, sys.stdout, indent=2)
    print()
