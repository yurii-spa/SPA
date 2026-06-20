"""
MP-756: LiquidationPriceCalculator
Advisory / read-only analytics module.
Computes exact liquidation prices for leveraged DeFi positions,
along with distance-to-liquidation metrics and alert levels.

Pure stdlib. No external dependencies. Atomic JSON writes via tmp+os.replace.
Ring-buffer cap: 100 entries.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
LOG_FILE = os.path.join(DATA_DIR, "liquidation_price_log.json")
RING_BUFFER_CAP = 100
DEFAULT_MAINTENANCE_MARGIN = 0.05


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LiquidationScenario:
    protocol: str
    asset: str
    direction: str                      # "LONG" | "SHORT"

    entry_price_usd: float
    current_price_usd: float
    leverage: float
    collateral_usd: float

    # Position sizing
    position_size_usd: float            # collateral * leverage
    borrowed_usd: float                 # position_size - collateral

    # Liquidation params
    maintenance_margin_ratio: float
    liquidation_price_usd: float

    # Current state
    current_pnl_usd: float
    current_equity_usd: float

    # Distance metrics
    price_distance_to_liquidation_usd: float
    price_distance_pct: float

    is_liquidated: bool
    alert_level: str
    recommendation: str


@dataclass
class LiquidationResult:
    scenarios: List[LiquidationScenario]

    liquidated_positions: List[str]
    at_risk_positions: List[str]

    safest_position: str
    most_at_risk: str

    system_alert_level: str

    recommendation_summary: str
    saved_to: str


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------

def compute_position_size(collateral: float, leverage: float) -> float:
    """collateral * leverage"""
    return collateral * leverage


def compute_borrowed(collateral: float, leverage: float) -> float:
    """collateral * (leverage - 1)"""
    return collateral * (leverage - 1)


def compute_liquidation_price_long(
    entry: float,
    leverage: float,
    maintenance_margin: float = DEFAULT_MAINTENANCE_MARGIN,
) -> float:
    """
    LONG liquidation price:
      entry * (1 - 1/leverage + maintenance_margin/leverage)
    Returns 0 when leverage <= 0 (guard).
    """
    if leverage <= 0:
        return 0.0
    return entry * (1.0 - 1.0 / leverage + maintenance_margin / leverage)


def compute_liquidation_price_short(
    entry: float,
    leverage: float,
    maintenance_margin: float = DEFAULT_MAINTENANCE_MARGIN,
) -> float:
    """
    SHORT liquidation price:
      entry * (1 + 1/leverage - maintenance_margin/leverage)
    Returns 0 when leverage <= 0 (guard).
    """
    if leverage <= 0:
        return 0.0
    return entry * (1.0 + 1.0 / leverage - maintenance_margin / leverage)


def compute_pnl_long(entry: float, current: float, position_size: float) -> float:
    """(current - entry) / entry * position_size"""
    if entry == 0:
        return 0.0
    return (current - entry) / entry * position_size


def compute_pnl_short(entry: float, current: float, position_size: float) -> float:
    """(entry - current) / entry * position_size"""
    if entry == 0:
        return 0.0
    return (entry - current) / entry * position_size


def price_distance_pct(current: float, liquidation: float) -> float:
    """abs(current - liquidation) / current * 100; returns 0 if current <= 0"""
    if current <= 0:
        return 0.0
    return abs(current - liquidation) / current * 100.0


def alert_level(dist_pct: float) -> str:
    """SAFE (>20%) | CAUTION (10-20%) | WARNING (5-10%) | DANGER (<5%)"""
    if dist_pct > 20.0:
        return "SAFE"
    elif dist_pct >= 10.0:
        return "CAUTION"
    elif dist_pct >= 5.0:
        return "WARNING"
    else:
        return "DANGER"


def is_liquidated(direction: str, current: float, liquidation: float) -> bool:
    """
    LONG: liquidated when current <= liquidation_price
    SHORT: liquidated when current >= liquidation_price
    """
    if direction == "LONG":
        return current <= liquidation
    else:  # SHORT
        return current >= liquidation


def _recommendation(level: str, liquidated: bool) -> str:
    if liquidated or level == "DANGER":
        return "DANGER: Approaching liquidation. Reduce leverage or add collateral immediately."
    elif level == "WARNING":
        return "WARNING: Close to liquidation threshold. Monitor closely."
    elif level == "CAUTION":
        return "CAUTION: Position at risk. Consider reducing leverage."
    else:
        return "Position safe at current price."


# ---------------------------------------------------------------------------
# High-level analysis
# ---------------------------------------------------------------------------

def analyze_scenario(
    protocol: str,
    asset: str,
    direction: str,
    entry_price: float,
    current_price: float,
    leverage: float,
    collateral: float,
    maintenance_margin: float = DEFAULT_MAINTENANCE_MARGIN,
) -> LiquidationScenario:
    """Build a full LiquidationScenario for one position."""
    pos_size = compute_position_size(collateral, leverage)
    borrowed = compute_borrowed(collateral, leverage)

    if direction == "LONG":
        liq_price = compute_liquidation_price_long(entry_price, leverage, maintenance_margin)
        pnl = compute_pnl_long(entry_price, current_price, pos_size)
    else:
        liq_price = compute_liquidation_price_short(entry_price, leverage, maintenance_margin)
        pnl = compute_pnl_short(entry_price, current_price, pos_size)

    equity = collateral + pnl
    dist_usd = abs(current_price - liq_price)
    dist_pct = price_distance_pct(current_price, liq_price)
    liquidated = is_liquidated(direction, current_price, liq_price)
    level = alert_level(dist_pct)
    rec = _recommendation(level, liquidated)

    return LiquidationScenario(
        protocol=protocol,
        asset=asset,
        direction=direction,
        entry_price_usd=entry_price,
        current_price_usd=current_price,
        leverage=leverage,
        collateral_usd=collateral,
        position_size_usd=pos_size,
        borrowed_usd=borrowed,
        maintenance_margin_ratio=maintenance_margin,
        liquidation_price_usd=liq_price,
        current_pnl_usd=pnl,
        current_equity_usd=equity,
        price_distance_to_liquidation_usd=dist_usd,
        price_distance_pct=dist_pct,
        is_liquidated=liquidated,
        alert_level=level,
        recommendation=rec,
    )


# Alert level severity ordering
_ALERT_ORDER = {"SAFE": 0, "CAUTION": 1, "WARNING": 2, "DANGER": 3}


def _worst_alert(*levels: str) -> str:
    return max(levels, key=lambda l: _ALERT_ORDER.get(l, 0))


def analyze_portfolio(scenarios_data: List[dict]) -> LiquidationResult:
    """
    scenarios_data: list of dicts with keys matching analyze_scenario signature.
    Returns a LiquidationResult (not saved to disk).
    """
    scenarios: List[LiquidationScenario] = []
    for sd in scenarios_data:
        s = analyze_scenario(
            protocol=sd["protocol"],
            asset=sd["asset"],
            direction=sd["direction"],
            entry_price=sd["entry_price"],
            current_price=sd["current_price"],
            leverage=sd["leverage"],
            collateral=sd["collateral"],
            maintenance_margin=sd.get("maintenance_margin", DEFAULT_MAINTENANCE_MARGIN),
        )
        scenarios.append(s)

    liquidated_positions = [
        f"{s.protocol}:{s.asset}" for s in scenarios if s.is_liquidated
    ]
    at_risk_positions = [
        f"{s.protocol}:{s.asset}"
        for s in scenarios
        if s.alert_level in ("WARNING", "DANGER")
    ]

    if scenarios:
        safest = max(scenarios, key=lambda s: s.price_distance_pct)
        safest_label = f"{safest.protocol}:{safest.asset}"
        most_at_risk_s = min(scenarios, key=lambda s: s.price_distance_pct)
        most_at_risk_label = f"{most_at_risk_s.protocol}:{most_at_risk_s.asset}"
        sys_level = _worst_alert(*[s.alert_level for s in scenarios])
    else:
        safest_label = ""
        most_at_risk_label = ""
        sys_level = "SAFE"

    if liquidated_positions:
        summary = f"CRITICAL: {len(liquidated_positions)} position(s) liquidated. Immediate action required."
    elif at_risk_positions:
        summary = f"WARNING: {len(at_risk_positions)} position(s) at risk. Monitor and reduce exposure."
    else:
        summary = "All positions are within safe distance from liquidation."

    return LiquidationResult(
        scenarios=scenarios,
        liquidated_positions=liquidated_positions,
        at_risk_positions=at_risk_positions,
        safest_position=safest_label,
        most_at_risk=most_at_risk_label,
        system_alert_level=sys_level,
        recommendation_summary=summary,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence (ring-buffer)
# ---------------------------------------------------------------------------

def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _scenario_to_dict(s: LiquidationScenario) -> dict:
    return asdict(s)


def _result_to_dict(result: LiquidationResult) -> dict:
    return {
        "scenarios": [_scenario_to_dict(s) for s in result.scenarios],
        "liquidated_positions": result.liquidated_positions,
        "at_risk_positions": result.at_risk_positions,
        "safest_position": result.safest_position,
        "most_at_risk": result.most_at_risk,
        "system_alert_level": result.system_alert_level,
        "recommendation_summary": result.recommendation_summary,
        "saved_to": result.saved_to,
    }


def load_history(filepath: str = LOG_FILE) -> List[dict]:
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def save_results(result: LiquidationResult, filepath: str = LOG_FILE) -> LiquidationResult:
    """Append result to ring-buffer log (cap=100). Updates result.saved_to."""
    _ensure_data_dir()
    history = load_history(filepath)
    entry = _result_to_dict(result)
    history.append(entry)
    if len(history) > RING_BUFFER_CAP:
        history = history[-RING_BUFFER_CAP:]

    dir_name = os.path.dirname(os.path.abspath(filepath))
    atomic_save(history, str(filepath))
    result.saved_to = filepath
    return result
