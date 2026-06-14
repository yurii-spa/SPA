"""
MP-754: CollateralRatioMonitor
Monitors collateral ratios in lending positions to detect under-collateralization risk.
Advisory/read-only. Pure stdlib. Atomic JSON writes.
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional

# ---------------------------------------------------------------------------
# Output path
# ---------------------------------------------------------------------------
_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "collateral_ratio_log.json"
)
_RING_BUFFER_CAP = 100
_INF_CAP = 9999.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CollateralPosition:
    protocol: str
    asset: str

    collateral_value_usd: float
    debt_value_usd: float
    liquidation_threshold_pct: float

    collateral_ratio_pct: float = 0.0
    max_safe_debt_usd: float = 0.0
    available_borrow_usd: float = 0.0
    liquidation_buffer_pct: float = 0.0
    health_factor: float = 0.0
    is_safe: bool = True
    alert_level: str = "SAFE"
    price_drop_tolerance_pct: float = 0.0
    recommendation: str = ""


@dataclass
class CollateralMonitorResult:
    positions: List[CollateralPosition] = field(default_factory=list)
    safe_positions: List[str] = field(default_factory=list)
    at_risk_positions: List[str] = field(default_factory=list)
    most_at_risk: str = ""
    avg_health_factor: float = 0.0
    system_alert_level: str = "SAFE"
    recommendation_summary: str = ""
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------

def compute_collateral_ratio(collateral: float, debt: float) -> float:
    """collateral / debt * 100 if debt > 0 else _INF_CAP."""
    if debt <= 0:
        return _INF_CAP
    return collateral / debt * 100.0


def compute_health_factor(
    collateral: float, debt: float, liquidation_threshold_pct: float
) -> float:
    """(collateral * liquidation_threshold_pct/100) / debt  if debt > 0 else _INF_CAP."""
    if debt <= 0:
        return _INF_CAP
    return (collateral * liquidation_threshold_pct / 100.0) / debt


def compute_max_safe_debt(collateral: float, liquidation_threshold_pct: float) -> float:
    """collateral * liquidation_threshold_pct / 100."""
    return collateral * liquidation_threshold_pct / 100.0


def compute_liquidation_buffer(
    collateral_ratio: float, liquidation_threshold: float
) -> float:
    """collateral_ratio - liquidation_threshold; returns _INF_CAP when collateral_ratio==_INF_CAP."""
    if collateral_ratio >= _INF_CAP:
        return _INF_CAP
    return collateral_ratio - liquidation_threshold


def price_drop_tolerance(health_factor: float) -> float:
    """
    How much collateral price can fall before liquidation.
    = max(0, (1 - 1/hf) * 100)  when 0 < hf < _INF_CAP
    hf == _INF_CAP  → 100
    hf == 0         → 0
    """
    if health_factor <= 0:
        return 0.0
    if health_factor >= _INF_CAP:
        return 100.0
    return max(0.0, (1.0 - 1.0 / health_factor) * 100.0)


def alert_level_from_hf(hf: float) -> str:
    """SAFE (>=1.5) | CAUTION (1.2-1.5) | WARNING (1.0-1.2) | DANGER (<1.0)."""
    if hf >= 1.5:
        return "SAFE"
    if hf >= 1.2:
        return "CAUTION"
    if hf >= 1.0:
        return "WARNING"
    return "DANGER"


_ALERT_ORDER = {"SAFE": 0, "CAUTION": 1, "WARNING": 2, "DANGER": 3}


def _worst_alert(*levels: str) -> str:
    return max(levels, key=lambda lvl: _ALERT_ORDER.get(lvl, 0))


# ---------------------------------------------------------------------------
# Position builder
# ---------------------------------------------------------------------------

def monitor_position(
    protocol: str,
    asset: str,
    collateral_value_usd: float,
    debt_value_usd: float,
    liquidation_threshold_pct: float,
) -> CollateralPosition:
    """Build a fully-computed CollateralPosition."""
    cr = compute_collateral_ratio(collateral_value_usd, debt_value_usd)
    hf = compute_health_factor(
        collateral_value_usd, debt_value_usd, liquidation_threshold_pct
    )
    max_safe = compute_max_safe_debt(collateral_value_usd, liquidation_threshold_pct)
    avail = max(0.0, max_safe - debt_value_usd)
    buf = compute_liquidation_buffer(cr, liquidation_threshold_pct)
    tol = price_drop_tolerance(hf)
    alert = alert_level_from_hf(hf)
    is_safe = hf >= 1.0

    if alert == "DANGER":
        rec = (
            "DANGER: Position approaching liquidation. "
            "Repay debt or add collateral immediately."
        )
    elif alert == "WARNING":
        rec = "WARNING: Low health factor. Consider reducing debt."
    elif alert == "CAUTION":
        rec = "CAUTION: Thinning margin. Monitor closely."
    else:
        rec = "Position healthy."

    return CollateralPosition(
        protocol=protocol,
        asset=asset,
        collateral_value_usd=collateral_value_usd,
        debt_value_usd=debt_value_usd,
        liquidation_threshold_pct=liquidation_threshold_pct,
        collateral_ratio_pct=cr,
        max_safe_debt_usd=max_safe,
        available_borrow_usd=avail,
        liquidation_buffer_pct=buf,
        health_factor=hf,
        is_safe=is_safe,
        alert_level=alert,
        price_drop_tolerance_pct=tol,
        recommendation=rec,
    )


# ---------------------------------------------------------------------------
# Portfolio aggregation
# ---------------------------------------------------------------------------

def monitor_portfolio(
    positions_data: List[dict],
    data_file: Optional[str] = None,
) -> CollateralMonitorResult:
    """
    positions_data: list of dicts with keys:
        protocol, asset, collateral_value_usd, debt_value_usd, liquidation_threshold_pct
    """
    positions = [monitor_position(**p) for p in positions_data]

    safe_positions = [
        f"{p.protocol}/{p.asset}" for p in positions if p.alert_level == "SAFE"
    ]
    at_risk_positions = [
        f"{p.protocol}/{p.asset}"
        for p in positions
        if p.alert_level in ("WARNING", "DANGER")
    ]

    if positions:
        most_at_risk_pos = min(positions, key=lambda p: p.health_factor)
        most_at_risk = f"{most_at_risk_pos.protocol}/{most_at_risk_pos.asset}"
        avg_hf = sum(min(p.health_factor, _INF_CAP) for p in positions) / len(positions)
        system_alert = _worst_alert(*[p.alert_level for p in positions])
    else:
        most_at_risk = ""
        avg_hf = 0.0
        system_alert = "SAFE"

    if system_alert == "DANGER":
        summary = "CRITICAL: One or more positions at liquidation risk."
    elif system_alert == "WARNING":
        summary = "WARNING: Low health factors detected. Review positions."
    elif system_alert == "CAUTION":
        summary = "CAUTION: Margins thinning. Monitor closely."
    else:
        summary = "All positions healthy."

    return CollateralMonitorResult(
        positions=positions,
        safe_positions=safe_positions,
        at_risk_positions=at_risk_positions,
        most_at_risk=most_at_risk,
        avg_health_factor=avg_hf,
        system_alert_level=system_alert,
        recommendation_summary=summary,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence (ring-buffer 100)
# ---------------------------------------------------------------------------

def _resolve_path(data_file: Optional[str]) -> str:
    return data_file or _DEFAULT_DATA_FILE


def load_history(data_file: Optional[str] = None) -> list:
    path = _resolve_path(data_file)
    if not os.path.exists(path):
        return []
    with open(path, "r") as fh:
        return json.load(fh)


def save_results(
    result: CollateralMonitorResult,
    data_file: Optional[str] = None,
) -> CollateralMonitorResult:
    """Append result snapshot to ring-buffer JSON (cap 100). Returns updated result."""
    path = _resolve_path(data_file)
    history = load_history(path)

    snapshot = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "positions": [asdict(p) for p in result.positions],
        "safe_positions": result.safe_positions,
        "at_risk_positions": result.at_risk_positions,
        "most_at_risk": result.most_at_risk,
        "avg_health_factor": result.avg_health_factor,
        "system_alert_level": result.system_alert_level,
        "recommendation_summary": result.recommendation_summary,
    }

    history.append(snapshot)
    history = history[-_RING_BUFFER_CAP:]

    tmp_path = path + ".tmp"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(tmp_path, "w") as fh:
        json.dump(history, fh, indent=2)
    os.replace(tmp_path, path)

    result.saved_to = path
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-754 CollateralRatioMonitor")
    parser.add_argument(
        "--run", action="store_true", help="Compute and save results"
    )
    parser.add_argument(
        "--check", action="store_true", help="Compute and print only (default)"
    )
    args = parser.parse_args()

    # Example positions
    sample = [
        {
            "protocol": "Aave V3",
            "asset": "USDC",
            "collateral_value_usd": 10000.0,
            "debt_value_usd": 6000.0,
            "liquidation_threshold_pct": 80.0,
        },
        {
            "protocol": "Compound V3",
            "asset": "ETH",
            "collateral_value_usd": 5000.0,
            "debt_value_usd": 0.0,
            "liquidation_threshold_pct": 75.0,
        },
    ]

    result = monitor_portfolio(sample)
    print(f"System alert level : {result.system_alert_level}")
    print(f"Avg health factor  : {result.avg_health_factor:.4f}")
    print(f"Most at risk       : {result.most_at_risk}")
    for pos in result.positions:
        print(
            f"  {pos.protocol}/{pos.asset}: HF={pos.health_factor:.4f} "
            f"alert={pos.alert_level}"
        )

    if args.run:
        save_results(result)
        print(f"Saved to: {result.saved_to}")
