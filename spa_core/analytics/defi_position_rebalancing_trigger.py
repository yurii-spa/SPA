"""
MP-865 DeFiPositionRebalancingTrigger
Advisory/read-only analytics module.
Monitors portfolio allocation drift and identifies when positions should be rebalanced.
Pure stdlib. Atomic writes via tmp + os.replace.
"""
import json
import os
import time

_DEFAULT_CONFIG = {
    "drift_threshold_pct": 5.0,
    "yield_degradation_threshold": 0.25,
    "max_concentration_pct": 40.0,
}

_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "rebalancing_trigger_log.json")
_LOG_CAP = 100


def _merge_config(config: dict | None) -> dict:
    cfg = dict(_DEFAULT_CONFIG)
    if config:
        for k in _DEFAULT_CONFIG:
            if k in config:
                cfg[k] = float(config[k])
    return cfg


def _compute_position(pos: dict, cfg: dict, total_portfolio_value: float) -> dict:
    protocol = pos.get("protocol", "")
    current_pct = float(pos.get("current_allocation_pct", 0.0))
    target_pct = float(pos.get("target_allocation_pct", 0.0))
    current_apy = float(pos.get("current_apy_pct", 0.0))
    initial_apy = float(pos.get("initial_apy_pct", 0.0))
    rebalance_cost = float(pos.get("rebalance_cost_usd", 0.0))

    drift_threshold = cfg["drift_threshold_pct"]
    yield_deg_threshold = cfg["yield_degradation_threshold"]
    max_conc = cfg["max_concentration_pct"]

    allocation_drift_pct = current_pct - target_pct
    drift_magnitude_pct = abs(allocation_drift_pct)

    if initial_apy > 0:
        yield_degradation_pct = (initial_apy - current_apy) / initial_apy * 100.0
    else:
        yield_degradation_pct = 0.0

    is_overweight = allocation_drift_pct > drift_threshold
    is_underweight = allocation_drift_pct < -drift_threshold
    yield_degraded = yield_degradation_pct > (yield_deg_threshold * 100.0)
    is_overconcentrated = current_pct > max_conc

    # Urgency
    if is_overconcentrated or ((is_overweight or is_underweight) and yield_degraded):
        urgency = "IMMEDIATE"
    elif (is_overweight or is_underweight) and not yield_degraded:
        urgency = "SOON"
    elif not (is_overweight or is_underweight) and yield_degraded:
        urgency = "MONITOR"
    else:
        urgency = "HOLD"

    if total_portfolio_value > 0:
        estimated_value_to_move_usd = abs(allocation_drift_pct / 100.0) * total_portfolio_value
    else:
        estimated_value_to_move_usd = 0.0

    # Recommendation
    if urgency == "IMMEDIATE":
        recommendation = (
            f"Rebalance NOW. Drift {allocation_drift_pct:+.1f}% + "
            f"yield degraded {yield_degradation_pct:.0f}%."
        )
    elif urgency == "SOON":
        recommendation = (
            f"Schedule rebalance. {protocol} drifted {allocation_drift_pct:+.1f}% from target."
        )
    elif urgency == "MONITOR":
        recommendation = (
            f"Yield degraded {yield_degradation_pct:.0f}% but allocation on target. Monitor."
        )
    else:
        recommendation = (
            f"Position within parameters. Allocation drift {allocation_drift_pct:+.1f}%."
        )

    return {
        "protocol": protocol,
        "current_allocation_pct": current_pct,
        "target_allocation_pct": target_pct,
        "allocation_drift_pct": allocation_drift_pct,
        "drift_magnitude_pct": drift_magnitude_pct,
        "yield_degradation_pct": yield_degradation_pct,
        "is_overweight": is_overweight,
        "is_underweight": is_underweight,
        "yield_degraded": yield_degraded,
        "is_overconcentrated": is_overconcentrated,
        "rebalance_urgency": urgency,
        "rebalance_cost_usd": rebalance_cost,
        "estimated_value_to_move_usd": estimated_value_to_move_usd,
        "recommendation": recommendation,
    }


def analyze(positions: list, config: dict = None) -> dict:
    """
    Analyze portfolio positions for rebalancing triggers.

    positions: list of dicts with protocol, current_allocation_pct, target_allocation_pct,
               current_apy_pct, initial_apy_pct, rebalance_cost_usd, position_value_usd
    config: optional overrides for drift_threshold_pct, yield_degradation_threshold,
            max_concentration_pct

    Returns dict with per-position analysis and portfolio summary.
    """
    cfg = _merge_config(config)

    if not positions:
        return {
            "positions": [],
            "portfolio_summary": {
                "total_portfolio_value_usd": 0.0,
                "positions_needing_rebalance": 0,
                "total_drift_magnitude_pct": 0.0,
                "highest_drift_protocol": None,
                "total_rebalance_cost_usd": 0.0,
                "rebalance_recommended": False,
            },
            "timestamp": time.time(),
        }

    total_portfolio_value = sum(float(p.get("position_value_usd", 0.0)) for p in positions)

    analyzed = [_compute_position(p, cfg, total_portfolio_value) for p in positions]

    # Portfolio summary
    positions_needing_rebalance = sum(
        1 for p in analyzed if p["rebalance_urgency"] in ("IMMEDIATE", "SOON")
    )
    total_drift_magnitude_pct = sum(p["drift_magnitude_pct"] for p in analyzed)

    highest_drift_protocol = None
    if analyzed:
        best = max(analyzed, key=lambda p: p["drift_magnitude_pct"])
        highest_drift_protocol = best["protocol"]

    total_rebalance_cost_usd = sum(
        p["rebalance_cost_usd"]
        for p in analyzed
        if p["rebalance_urgency"] in ("IMMEDIATE", "SOON")
    )

    immediate_count = sum(1 for p in analyzed if p["rebalance_urgency"] == "IMMEDIATE")
    soon_count = sum(1 for p in analyzed if p["rebalance_urgency"] == "SOON")
    rebalance_recommended = immediate_count >= 1 or soon_count >= 2

    result = {
        "positions": analyzed,
        "portfolio_summary": {
            "total_portfolio_value_usd": total_portfolio_value,
            "positions_needing_rebalance": positions_needing_rebalance,
            "total_drift_magnitude_pct": total_drift_magnitude_pct,
            "highest_drift_protocol": highest_drift_protocol,
            "total_rebalance_cost_usd": total_rebalance_cost_usd,
            "rebalance_recommended": rebalance_recommended,
        },
        "timestamp": time.time(),
    }
    return result


def log_result(result: dict, log_path: str = None) -> None:
    """Append result to ring-buffer JSON log (cap 100). Atomic write."""
    path = log_path or _LOG_PATH
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    try:
        with open(path, "r") as f:
            log = json.load(f)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(result)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]

    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(log, f, indent=2)
    os.replace(tmp, path)


if __name__ == "__main__":
    import sys

    sample_positions = [
        {
            "protocol": "Aave V3",
            "current_allocation_pct": 48.0,
            "target_allocation_pct": 40.0,
            "current_apy_pct": 2.5,
            "initial_apy_pct": 3.5,
            "rebalance_cost_usd": 45.0,
            "position_value_usd": 48000.0,
        },
        {
            "protocol": "Compound V3",
            "current_allocation_pct": 25.0,
            "target_allocation_pct": 30.0,
            "current_apy_pct": 4.8,
            "initial_apy_pct": 4.8,
            "rebalance_cost_usd": 30.0,
            "position_value_usd": 25000.0,
        },
        {
            "protocol": "Morpho Steakhouse",
            "current_allocation_pct": 22.0,
            "target_allocation_pct": 25.0,
            "current_apy_pct": 6.5,
            "initial_apy_pct": 6.5,
            "rebalance_cost_usd": 20.0,
            "position_value_usd": 22000.0,
        },
        {
            "protocol": "Cash",
            "current_allocation_pct": 5.0,
            "target_allocation_pct": 5.0,
            "current_apy_pct": 0.0,
            "initial_apy_pct": 0.0,
            "rebalance_cost_usd": 0.0,
            "position_value_usd": 5000.0,
        },
    ]

    result = analyze(sample_positions)
    print(json.dumps(result, indent=2))

    if "--run" in sys.argv:
        log_result(result)
        print("\nResult logged to", _LOG_PATH)
