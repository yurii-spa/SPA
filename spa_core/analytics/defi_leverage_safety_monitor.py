"""
MP-883: DeFiLeverageSafetyMonitor
Monitors leveraged DeFi positions for liquidation risk, funding cost drag,
and net profitability.

Advisory / read-only — never modifies allocator, risk, or execution.
Pure stdlib. Atomic ring-buffer write (100 entries) → data/leverage_safety_log.json
"""
from __future__ import annotations

import json
import math
import os
import time
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_SAFETY_BUFFER_PCT = 10.0   # flag if LTV within 10% of liquidation threshold
LOG_FILE = "data/leverage_safety_log.json"
LOG_MAX = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_config(config: dict | None) -> dict:
    cfg = config or {}
    return {
        "safety_buffer_pct": float(cfg.get("safety_buffer_pct", DEFAULT_SAFETY_BUFFER_PCT)),
    }


def _health_factor_label(health_factor: float) -> str:
    """Classify position health factor into a label."""
    if math.isnan(health_factor) or health_factor <= 1.0:
        return "LIQUIDATABLE"
    if health_factor <= 1.2:
        return "CRITICAL"
    if health_factor <= 1.5:
        return "ADEQUATE"
    return "HEALTHY"


def _safety_status(
    liquidation_distance_pct: float,
    health_factor: float,
    safety_buffer_pct: float,
) -> str:
    """Determine safety status of a position."""
    if math.isnan(health_factor) or health_factor <= 1.0 or liquidation_distance_pct <= 0:
        return "LIQUIDATABLE"
    if liquidation_distance_pct <= safety_buffer_pct:
        return "DANGER"
    if liquidation_distance_pct <= safety_buffer_pct * 2:
        return "WARNING"
    return "SAFE"


def _build_flags(
    liquidation_distance_pct: float,
    net_apy_pct: float,
    leverage_multiplier: float,
    safety_buffer_pct: float,
) -> list[str]:
    flags: list[str] = []
    if liquidation_distance_pct <= safety_buffer_pct:
        flags.append("NEAR_LIQUIDATION")
    if net_apy_pct < 0:
        flags.append("NEGATIVE_CARRY")
    if leverage_multiplier > 5.0:
        flags.append("OVER_LEVERAGED")
    return flags


def _recommendation(
    status: str,
    liquidation_distance_pct: float,
    net_apy_pct: float,
    leverage_efficiency: float,
) -> str:
    if status == "LIQUIDATABLE":
        return (
            "URGENT: Position at liquidation risk. "
            "Add collateral or repay debt immediately."
        )
    if status == "DANGER":
        return (
            f"High risk. Only {liquidation_distance_pct:.1f}% buffer to liquidation. "
            "Reduce leverage."
        )
    if status == "WARNING":
        return f"Caution. {liquidation_distance_pct:.1f}% buffer. Monitor closely."
    # SAFE
    if net_apy_pct >= 0:
        return (
            f"Healthy position. Net APY: {net_apy_pct:.1f}%. "
            f"Leverage efficiency: {leverage_efficiency:.2f}x."
        )
    return (
        f"Safe LTV but negative carry ({net_apy_pct:.1f}%). "
        "Consider reducing leverage."
    )


def _analyze_position(pos: dict, safety_buffer_pct: float) -> dict:
    """Compute per-position leverage safety metrics."""
    protocol = str(pos.get("protocol", "unknown"))
    collateral_usd = float(pos.get("collateral_usd", 0.0))
    debt_usd = float(pos.get("debt_usd", 0.0))
    liquidation_threshold_pct = float(pos.get("liquidation_threshold_pct", 0.0))
    current_ltv_pct = float(pos.get("current_ltv_pct", 0.0))
    collateral_apy_pct = float(pos.get("collateral_apy_pct", 0.0))
    borrow_cost_pct = float(pos.get("borrow_cost_pct", 0.0))
    leverage_multiplier = float(pos.get("leverage_multiplier", 1.0))
    health_factor = float(pos.get("position_health_factor", float("nan")))

    # Core calculations
    funding_drag_pct = borrow_cost_pct * (leverage_multiplier - 1)
    net_apy_pct = collateral_apy_pct * leverage_multiplier - borrow_cost_pct * (leverage_multiplier - 1)
    liquidation_distance_pct = liquidation_threshold_pct - current_ltv_pct

    # Leverage efficiency
    if collateral_apy_pct > 0:
        leverage_efficiency = net_apy_pct / collateral_apy_pct
    else:
        leverage_efficiency = 0.0

    # Classify
    status = _safety_status(liquidation_distance_pct, health_factor, safety_buffer_pct)
    hf_label = _health_factor_label(health_factor)
    flags = _build_flags(liquidation_distance_pct, net_apy_pct, leverage_multiplier, safety_buffer_pct)
    rec = _recommendation(status, liquidation_distance_pct, net_apy_pct, leverage_efficiency)

    return {
        "protocol": protocol,
        "current_ltv_pct": round(current_ltv_pct, 4),
        "liquidation_distance_pct": round(liquidation_distance_pct, 4),
        "net_apy_pct": round(net_apy_pct, 4),
        "funding_drag_pct": round(funding_drag_pct, 4),
        "safety_status": status,
        "health_factor_label": hf_label,
        "leverage_efficiency": round(leverage_efficiency, 4),
        "recommendation": rec,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(positions: list[dict], config: dict | None = None) -> dict:
    """
    Analyze leveraged DeFi positions for liquidation risk and net profitability.

    Parameters
    ----------
    positions : list of position dicts (see module docstring)
    config    : optional override dict; keys: safety_buffer_pct

    Returns
    -------
    dict with aggregated + per-position results
    """
    cfg = _resolve_config(config)
    safety_buffer_pct = cfg["safety_buffer_pct"]

    analyzed: list[dict] = []
    for pos in positions:
        analyzed.append(_analyze_position(pos, safety_buffer_pct))

    at_risk_count = sum(
        1 for p in analyzed if p["safety_status"] in ("DANGER", "LIQUIDATABLE")
    )

    if analyzed:
        average_net_apy_pct = round(
            sum(p["net_apy_pct"] for p in analyzed) / len(analyzed), 4
        )
        highest_risk_position = min(
            analyzed, key=lambda p: p["liquidation_distance_pct"]
        )["protocol"]
    else:
        average_net_apy_pct = 0.0
        highest_risk_position = None

    return {
        "positions": analyzed,
        "at_risk_count": at_risk_count,
        "average_net_apy_pct": average_net_apy_pct,
        "highest_risk_position": highest_risk_position,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Log persistence
# ---------------------------------------------------------------------------

def log_result(result: dict, data_dir: str = ".") -> None:
    """Append result snapshot to the ring-buffer JSON log (max 100 entries)."""
    log_path = os.path.join(data_dir, LOG_FILE)
    os.makedirs(os.path.dirname(log_path) if os.path.dirname(log_path) else ".", exist_ok=True)

    try:
        with open(log_path) as f:
            entries: list[dict] = json.load(f)
        if not isinstance(entries, list):
            entries = []
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []

    entries.append(result)
    entries = entries[-LOG_MAX:]

    atomic_save(entries, str(log_path))
# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo() -> None:
    """Quick demo with sample positions."""
    sample_positions = [
        {
            "protocol": "Aave-V3-USDC",
            "collateral_usd": 100_000,
            "debt_usd": 50_000,
            "liquidation_threshold_pct": 80.0,
            "current_ltv_pct": 50.0,
            "collateral_apy_pct": 5.0,
            "borrow_cost_pct": 3.0,
            "leverage_multiplier": 2.0,
            "position_health_factor": 1.6,
        },
        {
            "protocol": "Compound-V3-WETH",
            "collateral_usd": 50_000,
            "debt_usd": 40_000,
            "liquidation_threshold_pct": 82.5,
            "current_ltv_pct": 80.0,
            "collateral_apy_pct": 4.0,
            "borrow_cost_pct": 4.5,
            "leverage_multiplier": 3.0,
            "position_health_factor": 1.03,
        },
    ]
    result = analyze(sample_positions)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if "--run" in args:
        data_dir = "."
        if "--data-dir" in args:
            idx = args.index("--data-dir")
            data_dir = args[idx + 1]
        result = analyze([])  # real usage: load from positions file
        log_result(result, data_dir)
        print(json.dumps(result, indent=2))
    else:
        _demo()
