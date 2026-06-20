"""
MP-855 DeFiCollateralHealthMonitor
====================================
Advisory-only, read-only analytics module.
Monitors health factors of collateral positions in lending protocols.
Calculates health factor, liquidation proximity, buffer remaining,
and recommends risk-reduction actions.

Output file: data/collateral_health_log.json (ring-buffer, cap 100)
Pure Python stdlib only. Atomic writes (tmp + os.replace).
"""

import json
import math
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save


# ---------------------------------------------------------------------------
# Core calculations
# ---------------------------------------------------------------------------

def _health_factor(collateral_usd: float, liquidation_threshold: float, debt_usd: float) -> float:
    """health_factor = (collateral * liq_threshold) / debt; inf if debt=0"""
    if debt_usd <= 0:
        return float('inf')
    return (collateral_usd * liquidation_threshold) / debt_usd


def _ltv_current(debt_usd: float, collateral_usd: float) -> float:
    """debt / collateral if collateral>0 else 0.0"""
    if collateral_usd <= 0:
        return 0.0
    return debt_usd / collateral_usd


def _buffer_to_liquidation_usd(
    collateral_usd: float, debt_usd: float, liquidation_threshold: float
) -> float:
    """
    How much collateral value can drop before liquidation.
    inf if debt=0; can be negative if already underwater.
    """
    if debt_usd <= 0:
        return float('inf')
    return collateral_usd - (debt_usd / liquidation_threshold)


def _liquidation_price_drop_pct(
    collateral_usd: float, debt_usd: float, liquidation_threshold: float
) -> float:
    """
    % price drop that triggers liquidation.
    100.0 if debt=0; 0.0 if collateral=0.
    """
    if debt_usd <= 0:
        return 100.0
    if collateral_usd <= 0:
        return 0.0
    raw = (1.0 - (debt_usd / (collateral_usd * liquidation_threshold))) * 100.0
    return max(0.0, raw)


# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------

_DEFAULT_SAFE_HF = 1.5


def _health_status(
    health_factor: float, debt_usd: float, safe_health_factor: float = _DEFAULT_SAFE_HF
) -> str:
    if debt_usd <= 0:
        return "SAFE"
    if math.isinf(health_factor):
        return "SAFE"
    if health_factor <= 1.0:
        return "LIQUIDATABLE"
    if health_factor <= 1.1:
        return "CRITICAL"
    if health_factor <= 1.25:
        return "DANGER"
    if health_factor <= safe_health_factor:
        return "WARNING"
    return "SAFE"


def _recommendation(
    status: str,
    health_factor: float,
    buffer_to_liquidation_usd: float,
    liquidation_price_drop_pct: float,
) -> str:
    if math.isinf(health_factor):
        return "No debt. Position fully safe."
    if status == "LIQUIDATABLE":
        return (
            f"URGENT: Position may be liquidated. Immediately repay debt or add "
            f"{abs(buffer_to_liquidation_usd):.0f} USD collateral."
        )
    if status == "CRITICAL":
        return (
            f"Add collateral or repay debt immediately. Only "
            f"{liquidation_price_drop_pct:.1f}% price drop to liquidation."
        )
    if status == "DANGER":
        return (
            f"Reduce risk. {liquidation_price_drop_pct:.1f}% price drop triggers "
            f"liquidation. Consider partial repayment."
        )
    if status == "WARNING":
        return (
            f"Monitor closely. Health factor {health_factor:.2f}. "
            f"Consider reducing exposure."
        )
    # SAFE with debt
    return (
        f"Position healthy. Health factor {health_factor:.2f}. "
        f"Buffer: {buffer_to_liquidation_usd:.0f} USD."
    )


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------

def analyze(positions: list, config: dict = None) -> dict:
    """
    Analyze collateral health across lending protocol positions.

    Parameters
    ----------
    positions : list of dict with keys:
        protocol, collateral_usd, debt_usd, liquidation_threshold,
        collateral_factor, collateral_asset, borrow_asset
    config : optional dict with:
        safe_health_factor (default 1.5)

    Returns
    -------
    dict with keys: positions, portfolio_summary, timestamp
    """
    cfg = config or {}
    safe_hf = float(cfg.get("safe_health_factor", _DEFAULT_SAFE_HF))

    analyzed = []
    for pos in positions:
        protocol = str(pos.get("protocol", "unknown"))
        collateral_usd = float(pos.get("collateral_usd", 0.0))
        debt_usd = float(pos.get("debt_usd", 0.0))
        liq_threshold = float(pos.get("liquidation_threshold", 0.0))
        collateral_factor = float(pos.get("collateral_factor", 0.0))
        collateral_asset = str(pos.get("collateral_asset", ""))
        borrow_asset = str(pos.get("borrow_asset", ""))

        hf = _health_factor(collateral_usd, liq_threshold, debt_usd)
        ltv_cur = _ltv_current(debt_usd, collateral_usd)
        buf = _buffer_to_liquidation_usd(collateral_usd, debt_usd, liq_threshold)
        drop_pct = _liquidation_price_drop_pct(collateral_usd, debt_usd, liq_threshold)
        status = _health_status(hf, debt_usd, safe_hf)
        rec = _recommendation(status, hf, buf, drop_pct)

        analyzed.append({
            "protocol": protocol,
            "collateral_usd": collateral_usd,
            "debt_usd": debt_usd,
            "health_factor": hf,
            "ltv_current": ltv_cur,
            "ltv_max": collateral_factor,
            "ltv_liquidation": liq_threshold,
            "buffer_to_liquidation_usd": buf,
            "liquidation_price_drop_pct": drop_pct,
            "health_status": status,
            "recommendation": rec,
            "collateral_asset": collateral_asset,
            "borrow_asset": borrow_asset,
        })

    # -----------------------------------------------------------------------
    # Portfolio summary
    # -----------------------------------------------------------------------
    total_collateral = sum(p["collateral_usd"] for p in analyzed)
    total_debt = sum(p["debt_usd"] for p in analyzed)
    positions_safe = sum(1 for p in analyzed if p["health_status"] == "SAFE")
    positions_at_risk = sum(
        1 for p in analyzed if p["health_status"] != "SAFE"
    )

    finite_hfs = [
        (p["protocol"], p["health_factor"])
        for p in analyzed
        if not math.isinf(p["health_factor"])
    ]

    if finite_hfs:
        most_at_risk_proto = min(finite_hfs, key=lambda x: x[1])[0]
        avg_hf = sum(x[1] for x in finite_hfs) / len(finite_hfs)
    else:
        most_at_risk_proto = None
        avg_hf = None

    portfolio_summary = {
        "total_positions": len(analyzed),
        "total_collateral_usd": total_collateral,
        "total_debt_usd": total_debt,
        "positions_safe": positions_safe,
        "positions_at_risk": positions_at_risk,
        "most_at_risk": most_at_risk_proto,
        "average_health_factor": avg_hf,
    }

    return {
        "positions": analyzed,
        "portfolio_summary": portfolio_summary,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

_DEFAULT_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "collateral_health_log.json"
)
_RING_CAP = 100


def _resolve_log_path(data_dir: Optional[str] = None) -> str:
    if data_dir:
        return os.path.join(data_dir, "collateral_health_log.json")
    return os.path.normpath(_DEFAULT_LOG)


def _atomic_write(path: str, obj) -> None:
    """Write JSON atomically via tmp + os.replace."""
    dirpath = os.path.dirname(path) or "."
    os.makedirs(dirpath, exist_ok=True)
    atomic_save(obj, str(path))
def _json_serial(obj):
    if obj == float('inf'):
        return "Infinity"
    if obj == float('-inf'):
        return "-Infinity"
    raise TypeError(f"Not serializable: {obj!r}")


def _load_log(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, list):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


def append_log(result: dict, data_dir: Optional[str] = None) -> None:
    """Append analyze() result to ring-buffer log (max 100 entries)."""
    path = _resolve_log_path(data_dir)
    log = _load_log(path)
    log.append(result)
    if len(log) > _RING_CAP:
        log = log[-_RING_CAP:]
    _atomic_write(path, log)


def run(positions: list, config: dict = None, data_dir: Optional[str] = None) -> dict:
    """
    Run analyze() and persist result to ring-buffer log.
    Advisory only — no trades, no state mutations.
    """
    result = analyze(positions, config)
    append_log(result, data_dir)
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="DeFiCollateralHealthMonitor (MP-855)")
    parser.add_argument("--check", action="store_true", help="Run analysis, print, no write (default)")
    parser.add_argument("--run", action="store_true", help="Run analysis + persist log")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    # Demo positions
    demo_positions = [
        {
            "protocol": "Aave V3",
            "collateral_usd": 10000.0,
            "debt_usd": 6000.0,
            "liquidation_threshold": 0.85,
            "collateral_factor": 0.75,
            "collateral_asset": "ETH",
            "borrow_asset": "USDC",
        },
        {
            "protocol": "Compound V3",
            "collateral_usd": 5000.0,
            "debt_usd": 0.0,
            "liquidation_threshold": 0.80,
            "collateral_factor": 0.70,
            "collateral_asset": "WBTC",
            "borrow_asset": "USDC",
        },
    ]

    if args.run:
        result = run(demo_positions, data_dir=args.data_dir)
        print(json.dumps(result, indent=2, default=_json_serial))
    else:
        result = analyze(demo_positions)
        print(json.dumps(result, indent=2, default=_json_serial))
