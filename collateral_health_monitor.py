"""
MP-797: CollateralHealthMonitor
Monitors collateral health ratios across lending positions, tracks buffer to
liquidation, and alerts on deteriorating positions.

Advisory / read-only — never modifies allocator, risk, or execution.
Pure stdlib. Atomic ring-buffer write (100 entries) → data/collateral_health_log.json
"""
from __future__ import annotations

import json
import math
import os
import time
import tempfile
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_WARNING_BUFFER_PCT = 10.0  # warn if within 10 % of liquidation
DEFAULT_DANGER_BUFFER_PCT = 5.0    # danger if within 5 % of liquidation
LOG_FILE = "data/collateral_health_log.json"
LOG_MAX = 100

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_config(config: dict | None) -> dict:
    cfg = config or {}
    return {
        "warning_buffer_pct": float(cfg.get("warning_buffer_pct", DEFAULT_WARNING_BUFFER_PCT)),
        "danger_buffer_pct": float(cfg.get("danger_buffer_pct", DEFAULT_DANGER_BUFFER_PCT)),
    }


def _analyze_position(pos: dict, warning_pct: float, danger_pct: float) -> dict:
    """Compute per-position health metrics."""
    protocol = str(pos.get("protocol", "unknown"))
    collateral_usd = float(pos.get("collateral_usd", 0.0))
    debt_usd = float(pos.get("debt_usd", 0.0))
    liq_threshold = float(pos.get("liquidation_threshold", 0.80))
    collateral_token = str(pos.get("collateral_token", ""))
    price_change_24h = float(pos.get("collateral_price_change_24h", 0.0))

    # Edge: zero collateral → immediate liquidation
    if collateral_usd <= 0.0:
        return {
            "protocol": protocol,
            "current_ltv": float("inf"),
            "liquidation_ltv": liq_threshold,
            "buffer_pct": 0.0,
            "status": "LIQUIDATING",
            "max_additional_debt_usd": 0.0,
            "price_drop_to_liquidation_pct": 0.0,
            "collateral_token": collateral_token,
            "price_change_24h": price_change_24h,
        }

    # Edge: zero debt → fully healthy
    if debt_usd <= 0.0:
        return {
            "protocol": protocol,
            "current_ltv": 0.0,
            "liquidation_ltv": liq_threshold,
            "buffer_pct": 100.0,
            "status": "SAFE",
            "max_additional_debt_usd": round(collateral_usd * liq_threshold, 4),
            "price_drop_to_liquidation_pct": 100.0,
            "collateral_token": collateral_token,
            "price_change_24h": price_change_24h,
        }

    current_ltv = debt_usd / collateral_usd

    # buffer_pct: headroom as % of the liquidation threshold
    if liq_threshold <= 0.0:
        buffer_pct = 0.0
    else:
        buffer_pct = (liq_threshold - current_ltv) / liq_threshold * 100.0

    # Determine status
    if current_ltv >= liq_threshold:
        status = "LIQUIDATING"
    elif buffer_pct < danger_pct:
        status = "DANGER"
    elif buffer_pct < warning_pct:
        status = "WARNING"
    else:
        status = "SAFE"

    # Max additional debt before hitting liquidation
    max_borrow = max(0.0, collateral_usd * liq_threshold - debt_usd)

    # Price drop % to trigger liquidation
    # liquidation when: collateral_usd*(1-drop/100) * liq_threshold = debt_usd
    # → drop = (1 - debt_usd/(collateral_usd*liq_threshold)) * 100
    if liq_threshold <= 0.0:
        price_drop_pct = 0.0
    else:
        ratio = debt_usd / (collateral_usd * liq_threshold)
        if ratio >= 1.0:
            price_drop_pct = 0.0  # already at or past liquidation
        else:
            price_drop_pct = (1.0 - ratio) * 100.0

    return {
        "protocol": protocol,
        "current_ltv": round(current_ltv, 6),
        "liquidation_ltv": liq_threshold,
        "buffer_pct": round(buffer_pct, 4),
        "status": status,
        "max_additional_debt_usd": round(max_borrow, 4),
        "price_drop_to_liquidation_pct": round(price_drop_pct, 4),
        "collateral_token": collateral_token,
        "price_change_24h": price_change_24h,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(positions: list, config: dict | None = None) -> dict:
    """
    Analyze collateral health across a portfolio of lending positions.

    Parameters
    ----------
    positions : list of dict, each with:
        protocol, collateral_usd, debt_usd, liquidation_threshold,
        collateral_token, collateral_price_change_24h
    config : optional dict
        warning_buffer_pct (default 10.0) — warn if buffer < this %
        danger_buffer_pct  (default  5.0) — danger if buffer < this %

    Returns
    -------
    dict
        positions         : list of per-position results
        portfolio_summary : aggregate stats
        alerts            : list of human-readable warning strings
        timestamp         : float (unix time)
    """
    cfg = _resolve_config(config)
    warn_pct = cfg["warning_buffer_pct"]
    danger_pct = cfg["danger_buffer_pct"]

    pos_list = positions or []
    analyzed = [_analyze_position(p, warn_pct, danger_pct) for p in pos_list]

    # Portfolio summary
    total_collateral = sum(float(p.get("collateral_usd", 0.0)) for p in pos_list)
    total_debt = sum(float(p.get("debt_usd", 0.0)) for p in pos_list)
    portfolio_ltv = (total_debt / total_collateral) if total_collateral > 0 else 0.0

    at_risk_count = sum(
        1 for a in analyzed if a["status"] in ("WARNING", "DANGER", "LIQUIDATING")
    )

    healthiest_protocol = ""
    riskiest_protocol = ""
    if analyzed:
        def sort_key(a: dict) -> float:
            ltv = a["current_ltv"]
            return -float("inf") if math.isinf(ltv) else a["buffer_pct"]

        sorted_pos = sorted(analyzed, key=sort_key, reverse=True)
        healthiest_protocol = sorted_pos[0]["protocol"]
        riskiest_protocol = sorted_pos[-1]["protocol"]

    portfolio_summary = {
        "total_collateral_usd": round(total_collateral, 4),
        "total_debt_usd": round(total_debt, 4),
        "portfolio_ltv": round(portfolio_ltv, 6),
        "at_risk_count": at_risk_count,
        "healthiest_protocol": healthiest_protocol,
        "riskiest_protocol": riskiest_protocol,
    }

    # Alerts
    alerts: list[str] = []
    for a in analyzed:
        proto = a["protocol"]
        st = a["status"]
        if st == "LIQUIDATING":
            ltv_str = "inf" if math.isinf(a["current_ltv"]) else f"{a['current_ltv']:.2%}"
            alerts.append(
                f"CRITICAL: {proto} is LIQUIDATING — current LTV {ltv_str} "
                f">= threshold {a['liquidation_ltv']:.2%}"
            )
        elif st == "DANGER":
            alerts.append(
                f"DANGER: {proto} buffer {a['buffer_pct']:.2f}% < {danger_pct}% danger threshold. "
                f"Price drop of {a['price_drop_to_liquidation_pct']:.2f}% triggers liquidation."
            )
        elif st == "WARNING":
            alerts.append(
                f"WARNING: {proto} buffer {a['buffer_pct']:.2f}% < {warn_pct}% warning threshold. "
                f"Max additional borrow: ${a['max_additional_debt_usd']:,.2f}"
            )

    return {
        "positions": analyzed,
        "portfolio_summary": portfolio_summary,
        "alerts": alerts,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Ring-buffer log (atomic write)
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp-file + os.replace."""
    dir_name = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_name, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def append_log(result: dict, log_path: str = LOG_FILE) -> None:
    """Append an analysis result to the ring-buffer log (capped at LOG_MAX)."""
    try:
        with open(log_path, "r") as fh:
            log = json.load(fh)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(result)
    if len(log) > LOG_MAX:
        log = log[-LOG_MAX:]

    _atomic_write(log_path, log)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _sample_positions() -> list:
    return [
        {
            "protocol": "Aave V3",
            "collateral_usd": 100_000.0,
            "debt_usd": 65_000.0,
            "liquidation_threshold": 0.80,
            "collateral_token": "ETH",
            "collateral_price_change_24h": -2.5,
        },
        {
            "protocol": "Compound V3",
            "collateral_usd": 50_000.0,
            "debt_usd": 39_500.0,
            "liquidation_threshold": 0.80,
            "collateral_token": "WBTC",
            "collateral_price_change_24h": 0.8,
        },
        {
            "protocol": "Morpho Blue",
            "collateral_usd": 25_000.0,
            "debt_usd": 2_000.0,
            "liquidation_threshold": 0.75,
            "collateral_token": "USDC",
            "collateral_price_change_24h": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-797 CollateralHealthMonitor")
    parser.add_argument("--run", action="store_true", help="Compute and write to log")
    parser.add_argument("--check", action="store_true", help="Compute and print (default)")
    parser.add_argument("--log", default=LOG_FILE, help="Path to log file")
    args = parser.parse_args()

    result = analyze(_sample_positions())
    for pos in result["positions"]:
        ltv = pos["current_ltv"]
        ltv_s = "inf" if math.isinf(ltv) else f"{ltv:.2%}"
        print(
            f"  {pos['protocol']:20s} LTV={ltv_s} "
            f"buf={pos['buffer_pct']:.2f}% status={pos['status']}"
        )
    print(f"\nPortfolio LTV : {result['portfolio_summary']['portfolio_ltv']:.2%}")
    print(f"At-risk count : {result['portfolio_summary']['at_risk_count']}")
    for alert in result["alerts"]:
        print(f"  ⚠  {alert}")

    if args.run:
        append_log(result, args.log)
        print(f"\n✅ Written to {args.log}")
