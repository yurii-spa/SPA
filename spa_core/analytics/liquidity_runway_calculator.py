"""LiquidityRunwayCalculator — MP-826.

Calculates how long a protocol's liquidity mining program can continue at
current rates, and projects TVL changes if emissions stop.

Design constraints
------------------
* Pure stdlib only — no external dependencies.
* Advisory / read-only — never touches allocator / risk / execution.
* Atomic writes: tmp-file + os.replace on every save.
* Ring-buffer: data/liquidity_runway_log.json capped at MAX_ENTRIES=100.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/liquidity_runway_log.json")
MAX_ENTRIES = 100
DEFAULT_TVL_DROP_PCT = 60.0

# Sustainability thresholds (days)
_HEALTHY_DAYS = 365
_MODERATE_DAYS = 180
_STRESSED_DAYS = 90


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sustainability_status(is_self_sustaining: bool,
                           runway_days: float | None) -> str:
    """Map runway to SELF_SUSTAINING | HEALTHY | MODERATE | STRESSED | CRITICAL."""
    if is_self_sustaining:
        return "SELF_SUSTAINING"
    # runway_days is a finite float here
    if runway_days >= _HEALTHY_DAYS:
        return "HEALTHY"
    if runway_days >= _MODERATE_DAYS:
        return "MODERATE"
    if runway_days >= _STRESSED_DAYS:
        return "STRESSED"
    return "CRITICAL"


def _risk_assessment(is_self_sustaining: bool, runway_days: float | None,
                     revenue_coverage_pct: float) -> str:
    """Human-readable risk summary."""
    if is_self_sustaining:
        return "Protocol is self-sustaining"
    return (
        f"Protocol has {runway_days:.0f} days runway with "
        f"{revenue_coverage_pct:.0f}% revenue coverage"
    )


def _append_log(entry: dict) -> None:
    """Append result to ring-buffer JSON log (atomic write, capped at MAX_ENTRIES)."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(DATA_FILE) as fh:
            log: list = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(entry)
    if len(log) > MAX_ENTRIES:
        log = log[-MAX_ENTRIES:]

    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w") as fh:
        json.dump(log, fh, indent=2)
    os.replace(tmp, DATA_FILE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocol: str, metrics: dict, config: dict = None) -> dict:
    """Calculate liquidity runway and TVL-at-risk for *protocol*.

    Parameters
    ----------
    protocol:
        Protocol name (e.g. "Uniswap V3", "Curve").
    metrics:
        Dict with keys:
            treasury_usd            — funds available for incentives
            daily_emission_usd      — current daily incentive spend
            current_tvl_usd         — current total value locked
            organic_tvl_pct         — % of TVL that is non-incentivized (0-100)
            tvl_per_emission_usd    — TVL attracted per $1 of daily emissions
            daily_protocol_revenue_usd — revenue to replenish treasury
    config:
        Optional dict with:
            tvl_drop_at_emission_stop_pct (default 60.0) — estimated TVL drop
            if emissions stop entirely.

    Returns
    -------
    dict with full runway analysis.
    """
    config = config or {}
    tvl_drop_pct = float(config.get("tvl_drop_at_emission_stop_pct",
                                     DEFAULT_TVL_DROP_PCT))

    treasury = float(metrics.get("treasury_usd", 0.0))
    daily_emission = float(metrics.get("daily_emission_usd", 0.0))
    current_tvl = float(metrics.get("current_tvl_usd", 0.0))
    organic_tvl_pct = float(metrics.get("organic_tvl_pct", 0.0))
    tvl_per_emission = float(metrics.get("tvl_per_emission_usd", 0.0))
    daily_revenue = float(metrics.get("daily_protocol_revenue_usd", 0.0))

    # Self-sustaining: revenue covers or exceeds spend
    # Also self-sustaining if daily_emission == 0 (nothing to burn)
    is_self_sustaining = daily_revenue >= daily_emission

    # Net daily burn (positive = burning, negative = accumulating)
    net_daily_burn = daily_emission - daily_revenue

    # Runway
    if is_self_sustaining:
        runway_days: float | None = None
    else:
        # net_daily_burn > 0 here
        runway_days = treasury / net_daily_burn

    # Revenue coverage
    revenue_coverage_pct = daily_revenue / max(daily_emission, 0.01) * 100.0

    # TVL at risk (incentivized portion)
    tvl_at_risk = current_tvl * (1.0 - organic_tvl_pct / 100.0)
    incentivized_tvl = tvl_at_risk

    # Projected TVL if emissions stop
    projected_tvl_after_stop = current_tvl * (1.0 - tvl_drop_pct / 100.0)
    tvl_drop_usd = current_tvl - projected_tvl_after_stop

    status = _sustainability_status(is_self_sustaining, runway_days)
    risk_str = _risk_assessment(is_self_sustaining, runway_days, revenue_coverage_pct)

    result: dict = {
        "protocol": protocol,
        "runway_days": runway_days,
        "is_self_sustaining": is_self_sustaining,
        "net_daily_burn_usd": net_daily_burn,
        "tvl_at_risk_usd": tvl_at_risk,
        "incentivized_tvl_usd": incentivized_tvl,
        "projected_tvl_after_stop_usd": projected_tvl_after_stop,
        "tvl_drop_usd": tvl_drop_usd,
        "emission_efficiency": tvl_per_emission,
        "revenue_coverage_pct": revenue_coverage_pct,
        "sustainability_status": status,
        "risk_assessment": risk_str,
        "timestamp": time.time(),
    }

    _append_log(result)
    return result
