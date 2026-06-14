"""
MP-740: YieldAttributionAnalyzer
Decomposes total portfolio yield into constituent sources:
base rates, incentive tokens, fees, and leverage —
attributing what fraction of yield comes from each source
and assessing sustainability.

Advisory/read-only. Pure stdlib. Atomic JSON writes.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUSTAINABILITY_MAP = {
    "BASE_RATE": True,
    "REAL_YIELD": True,
    "TRADING_FEES": True,
    "INCENTIVE_TOKENS": False,
    "LEVERAGE": False,
}

SUSTAINABILITY_NOTES = {
    "BASE_RATE": "Organic lending demand",
    "REAL_YIELD": "Protocol revenue-backed",
    "TRADING_FEES": "DEX volume-backed",
    "INCENTIVE_TOKENS": "Token emission-dependent — may not persist",
    "LEVERAGE": "Funding-rate dependent — can reverse",
}

RING_BUFFER_CAP = 100
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
LOG_FILE = "yield_attribution_log.json"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class YieldComponent:
    name: str                  # "BASE_RATE" | "INCENTIVE_TOKENS" | "TRADING_FEES" | "LEVERAGE" | "REAL_YIELD"
    apy_contribution: float    # this component's APY contribution
    pct_of_total: float        # contribution / total_apy * 100
    is_sustainable: bool       # BASE_RATE and TRADING_FEES are sustainable; INCENTIVE_TOKENS and LEVERAGE are not
    sustainability_note: str


@dataclass
class PositionAttribution:
    position_name: str
    protocol: str
    total_apy: float
    allocation_pct: float        # % of portfolio

    components: List[YieldComponent] = field(default_factory=list)

    sustainable_apy: float = 0.0
    unsustainable_apy: float = 0.0
    sustainability_ratio: float = 0.0   # sustainable / total * 100

    sustainability_label: str = ""  # "SUSTAINABLE" (>70%) | "MIXED" (40-70%) | "FRAGILE" (<40%)
    weighted_contribution: float = 0.0  # total_apy * allocation_pct / 100


@dataclass
class YieldAttributionResult:
    positions: List[PositionAttribution] = field(default_factory=list)

    # Portfolio-level attribution
    portfolio_total_apy: float = 0.0
    portfolio_sustainable_apy: float = 0.0
    portfolio_unsustainable_apy: float = 0.0
    portfolio_sustainability_ratio: float = 0.0  # portfolio_sustainable / portfolio_total * 100

    # By source breakdown
    source_breakdown: dict = field(default_factory=dict)  # {component_name: total_weighted_contribution}

    # Risk
    fragile_positions: List[str] = field(default_factory=list)

    portfolio_sustainability_label: str = ""  # SUSTAINABLE / MIXED / FRAGILE
    recommendations: List[str] = field(default_factory=list)
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def build_component(name: str, apy_contribution: float, total_apy: float) -> YieldComponent:
    """Build a YieldComponent, computing pct_of_total, sustainability."""
    pct_of_total = (apy_contribution / total_apy * 100) if total_apy > 0 else 0.0
    is_sustainable = SUSTAINABILITY_MAP.get(name, False)
    sustainability_note = SUSTAINABILITY_NOTES.get(name, "Unknown source")
    return YieldComponent(
        name=name,
        apy_contribution=apy_contribution,
        pct_of_total=pct_of_total,
        is_sustainable=is_sustainable,
        sustainability_note=sustainability_note,
    )


def compute_sustainability_label(ratio: float) -> str:
    """
    SUSTAINABLE  >70%
    MIXED        40-70%
    FRAGILE      <40%
    """
    if ratio > 70.0:
        return "SUSTAINABLE"
    elif ratio >= 40.0:
        return "MIXED"
    else:
        return "FRAGILE"


def attribute_position(
    position_name: str,
    protocol: str,
    total_apy: float,
    allocation_pct: float,
    components_data: List[dict],
) -> PositionAttribution:
    """
    Build a PositionAttribution from raw component data.

    components_data: List[dict] with keys {name, apy_contribution}
    """
    components = [
        build_component(c["name"], c["apy_contribution"], total_apy)
        for c in components_data
    ]

    sustainable_apy = sum(c.apy_contribution for c in components if c.is_sustainable)
    unsustainable_apy = sum(c.apy_contribution for c in components if not c.is_sustainable)

    if total_apy > 0:
        sustainability_ratio = sustainable_apy / total_apy * 100
    else:
        sustainability_ratio = 100.0  # no yield → treat as fully sustainable

    sustainability_label = compute_sustainability_label(sustainability_ratio)
    weighted_contribution = total_apy * allocation_pct / 100

    return PositionAttribution(
        position_name=position_name,
        protocol=protocol,
        total_apy=total_apy,
        allocation_pct=allocation_pct,
        components=components,
        sustainable_apy=sustainable_apy,
        unsustainable_apy=unsustainable_apy,
        sustainability_ratio=sustainability_ratio,
        sustainability_label=sustainability_label,
        weighted_contribution=weighted_contribution,
    )


def analyze_portfolio(positions_data: List[dict]) -> YieldAttributionResult:
    """
    Analyze a full portfolio.

    positions_data: List[dict] with keys:
        {position_name, protocol, total_apy, allocation_pct, components: List}
    """
    positions = [
        attribute_position(
            p["position_name"],
            p["protocol"],
            p["total_apy"],
            p["allocation_pct"],
            p.get("components", []),
        )
        for p in positions_data
    ]

    portfolio_total_apy = sum(p.weighted_contribution for p in positions)
    portfolio_sustainable_apy = sum(
        p.sustainable_apy * p.allocation_pct / 100 for p in positions
    )
    portfolio_unsustainable_apy = sum(
        p.unsustainable_apy * p.allocation_pct / 100 for p in positions
    )

    if portfolio_total_apy > 0:
        portfolio_sustainability_ratio = portfolio_sustainable_apy / portfolio_total_apy * 100
    else:
        portfolio_sustainability_ratio = 100.0

    # Per-source breakdown: sum of each component's weighted contribution
    source_breakdown: dict = {}
    for pos in positions:
        weight = pos.allocation_pct / 100
        for comp in pos.components:
            key = comp.name
            source_breakdown[key] = source_breakdown.get(key, 0.0) + (comp.apy_contribution * weight)

    fragile_positions = [p.position_name for p in positions if p.sustainability_ratio < 40.0]

    # Total allocation in fragile positions
    fragile_alloc = sum(p.allocation_pct for p in positions if p.sustainability_ratio < 40.0)

    portfolio_sustainability_label = compute_sustainability_label(portfolio_sustainability_ratio)

    recommendations: List[str] = []
    if fragile_alloc > 30.0:
        recommendations.append(
            "High fragile position weight — incentive yields may collapse"
        )
    if portfolio_sustainability_ratio < 40.0:
        recommendations.append(
            "Portfolio heavily dependent on unsustainable yield — review token emission risks"
        )

    return YieldAttributionResult(
        positions=positions,
        portfolio_total_apy=portfolio_total_apy,
        portfolio_sustainable_apy=portfolio_sustainable_apy,
        portfolio_unsustainable_apy=portfolio_unsustainable_apy,
        portfolio_sustainability_ratio=portfolio_sustainability_ratio,
        source_breakdown=source_breakdown,
        fragile_positions=fragile_positions,
        portfolio_sustainability_label=portfolio_sustainability_label,
        recommendations=recommendations,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _log_path(data_dir: Optional[str] = None) -> str:
    base = data_dir or DEFAULT_DATA_DIR
    return os.path.join(base, LOG_FILE)


def _result_to_dict(result: YieldAttributionResult) -> dict:
    """Serialize YieldAttributionResult to a JSON-safe dict."""

    def component_to_dict(c: YieldComponent) -> dict:
        return {
            "name": c.name,
            "apy_contribution": c.apy_contribution,
            "pct_of_total": c.pct_of_total,
            "is_sustainable": c.is_sustainable,
            "sustainability_note": c.sustainability_note,
        }

    def position_to_dict(p: PositionAttribution) -> dict:
        return {
            "position_name": p.position_name,
            "protocol": p.protocol,
            "total_apy": p.total_apy,
            "allocation_pct": p.allocation_pct,
            "components": [component_to_dict(c) for c in p.components],
            "sustainable_apy": p.sustainable_apy,
            "unsustainable_apy": p.unsustainable_apy,
            "sustainability_ratio": p.sustainability_ratio,
            "sustainability_label": p.sustainability_label,
            "weighted_contribution": p.weighted_contribution,
        }

    return {
        "timestamp": time.time(),
        "positions": [position_to_dict(p) for p in result.positions],
        "portfolio_total_apy": result.portfolio_total_apy,
        "portfolio_sustainable_apy": result.portfolio_sustainable_apy,
        "portfolio_unsustainable_apy": result.portfolio_unsustainable_apy,
        "portfolio_sustainability_ratio": result.portfolio_sustainability_ratio,
        "source_breakdown": result.source_breakdown,
        "fragile_positions": result.fragile_positions,
        "portfolio_sustainability_label": result.portfolio_sustainability_label,
        "recommendations": result.recommendations,
        "saved_to": result.saved_to,
    }


def save_results(result: YieldAttributionResult, data_dir: Optional[str] = None) -> str:
    """Append result to ring-buffer log (cap=100). Returns path written."""
    path = _log_path(data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    history = load_history(data_dir)
    history.append(_result_to_dict(result))
    if len(history) > RING_BUFFER_CAP:
        history = history[-RING_BUFFER_CAP:]

    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(history, fh, indent=2)
    os.replace(tmp, path)

    result.saved_to = path
    return path


def load_history(data_dir: Optional[str] = None) -> list:
    """Load attribution log. Returns empty list if file missing/corrupt."""
    path = _log_path(data_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, IOError):
        return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _demo_run() -> None:
    """Quick smoke-test with demo data."""
    positions_data = [
        {
            "position_name": "Aave USDC",
            "protocol": "Aave V3",
            "total_apy": 5.0,
            "allocation_pct": 40.0,
            "components": [
                {"name": "BASE_RATE", "apy_contribution": 4.5},
                {"name": "INCENTIVE_TOKENS", "apy_contribution": 0.5},
            ],
        },
        {
            "position_name": "Curve 3Pool",
            "protocol": "Curve",
            "total_apy": 8.0,
            "allocation_pct": 35.0,
            "components": [
                {"name": "TRADING_FEES", "apy_contribution": 2.0},
                {"name": "INCENTIVE_TOKENS", "apy_contribution": 6.0},
            ],
        },
        {
            "position_name": "Delta Neutral sUSDe",
            "protocol": "Ethena",
            "total_apy": 27.0,
            "allocation_pct": 25.0,
            "components": [
                {"name": "BASE_RATE", "apy_contribution": 5.0},
                {"name": "LEVERAGE", "apy_contribution": 22.0},
            ],
        },
    ]

    result = analyze_portfolio(positions_data)
    print(f"Portfolio Total APY : {result.portfolio_total_apy:.2f}%")
    print(f"Sustainable APY     : {result.portfolio_sustainable_apy:.2f}%")
    print(f"Sustainability Ratio: {result.portfolio_sustainability_ratio:.1f}%")
    print(f"Portfolio Label     : {result.portfolio_sustainability_label}")
    print(f"Fragile Positions   : {result.fragile_positions}")
    print(f"Source Breakdown    : {result.source_breakdown}")
    print(f"Recommendations     : {result.recommendations}")


if __name__ == "__main__":
    import sys

    if "--run" in sys.argv:
        data_dir = None
        if "--data-dir" in sys.argv:
            idx = sys.argv.index("--data-dir")
            data_dir = sys.argv[idx + 1]
        # For standalone run, use demo data
        positions_data = []
        result = analyze_portfolio(positions_data)
        save_results(result, data_dir)
        print(f"Saved to {result.saved_to}")
    else:
        _demo_run()
