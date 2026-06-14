"""
MP-706: CrossChainYieldArbitrage
Advisory/read-only module. Pure stdlib. Atomic JSON writes via tmp+os.replace.

Identifies yield arbitrage opportunities across chains by comparing net APYs
after bridge costs, gas drag, and risk premiums.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional

# ---------------------------------------------------------------------------
# Data path
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
DATA_FILE = os.path.join(_REPO_ROOT, "data", "cross_chain_arbitrage_log.json")

RING_BUFFER_CAP = 100

# ---------------------------------------------------------------------------
# Supported chains
# ---------------------------------------------------------------------------
SUPPORTED_CHAINS = {"ethereum", "arbitrum", "base", "optimism", "polygon"}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class ChainYield:
    chain: str
    protocol: str
    pool: str
    gross_apy: float
    gas_drag_pct: float
    bridge_cost_pct: float
    risk_premium_pct: float
    net_apy: float = 0.0

    def __post_init__(self):
        if self.net_apy == 0.0:
            self.net_apy = calculate_net_apy(
                self.gross_apy,
                self.gas_drag_pct,
                self.bridge_cost_pct,
                self.risk_premium_pct,
            )


@dataclass
class ArbitrageOpportunity:
    source: ChainYield
    target: ChainYield
    gross_spread_pct: float
    net_spread_pct: float
    breakeven_days: float
    position_usd: float
    estimated_annual_gain_usd: float
    viable: bool
    confidence: str
    warnings: List[str] = field(default_factory=list)
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def calculate_net_apy(
    gross_apy: float,
    gas_drag_pct: float,
    bridge_cost_pct: float,
    risk_premium_pct: float,
) -> float:
    """net = gross - gas_drag - bridge_cost*2 (round-trip) - risk_premium, clamped ≥ 0."""
    net = gross_apy - gas_drag_pct - bridge_cost_pct * 2.0 - risk_premium_pct
    return max(0.0, net)


def default_gas_drag(chain: str) -> float:
    """Estimated annual gas cost as % of position for each chain."""
    _map = {
        "ethereum": 0.8,
        "arbitrum": 0.05,
        "base": 0.04,
        "optimism": 0.05,
        "polygon": 0.1,
    }
    return _map.get(chain, 0.5)


def default_bridge_cost(chain: str) -> float:
    """One-way bridge cost as % of position. Ethereum is home chain → 0."""
    _map = {
        "ethereum": 0.0,
        "arbitrum": 0.15,
        "base": 0.12,
        "optimism": 0.15,
        "polygon": 0.08,
    }
    return _map.get(chain, 0.2)


def default_risk_premium(chain: str) -> float:
    """Extra yield required for this chain's risk above Ethereum baseline."""
    _map = {
        "ethereum": 0.0,
        "arbitrum": 0.3,
        "base": 0.2,
        "optimism": 0.3,
        "polygon": 0.5,
    }
    return _map.get(chain, 0.5)


def find_opportunity(
    source: ChainYield,
    target: ChainYield,
    position_usd: float,
) -> ArbitrageOpportunity:
    """Compute a single source→target arbitrage opportunity."""
    gross_spread = target.gross_apy - source.gross_apy
    net_spread = target.net_apy - source.net_apy

    # One-time entry cost: round-trip bridge on target + target gas drag
    total_move_cost_pct = target.bridge_cost_pct * 2.0 + target.gas_drag_pct

    if net_spread > 0:
        breakeven_days = (total_move_cost_pct / net_spread) * 365.0
    else:
        breakeven_days = 9999.0

    estimated_annual_gain_usd = position_usd * net_spread / 100.0

    viable = net_spread > 0 and breakeven_days < 90

    # Confidence based on breakeven days
    if breakeven_days < 30:
        confidence = "HIGH"
    elif breakeven_days < 60:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    warnings: List[str] = []
    if gross_spread < 0:
        warnings.append("negative gross spread")
    if breakeven_days > 180:
        warnings.append("long breakeven")
    if abs(target.risk_premium_pct - source.risk_premium_pct) > 1.0:
        warnings.append("risk premium mismatch >1%")

    return ArbitrageOpportunity(
        source=source,
        target=target,
        gross_spread_pct=gross_spread,
        net_spread_pct=net_spread,
        breakeven_days=breakeven_days,
        position_usd=position_usd,
        estimated_annual_gain_usd=estimated_annual_gain_usd,
        viable=viable,
        confidence=confidence,
        warnings=warnings,
    )


def scan_opportunities(
    chain_yields: List[ChainYield],
    position_usd: float,
) -> List[ArbitrageOpportunity]:
    """Return all N*(N-1) source→target pairs sorted by net_spread desc."""
    results: List[ArbitrageOpportunity] = []
    for i, source in enumerate(chain_yields):
        for j, target in enumerate(chain_yields):
            if i == j:
                continue
            opp = find_opportunity(source, target, position_usd)
            results.append(opp)
    results.sort(key=lambda o: o.net_spread_pct, reverse=True)
    return results


def best_opportunity(
    opportunities: List[ArbitrageOpportunity],
) -> Optional[ArbitrageOpportunity]:
    """Return the highest net_spread viable opportunity, or None."""
    viable = [o for o in opportunities if o.viable]
    if not viable:
        return None
    return max(viable, key=lambda o: o.net_spread_pct)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _chain_yield_to_dict(cy: ChainYield) -> dict:
    return {
        "chain": cy.chain,
        "protocol": cy.protocol,
        "pool": cy.pool,
        "gross_apy": cy.gross_apy,
        "gas_drag_pct": cy.gas_drag_pct,
        "bridge_cost_pct": cy.bridge_cost_pct,
        "risk_premium_pct": cy.risk_premium_pct,
        "net_apy": cy.net_apy,
    }


def _opportunity_to_dict(opp: ArbitrageOpportunity) -> dict:
    return {
        "ts": time.time(),
        "source": _chain_yield_to_dict(opp.source),
        "target": _chain_yield_to_dict(opp.target),
        "gross_spread_pct": opp.gross_spread_pct,
        "net_spread_pct": opp.net_spread_pct,
        "breakeven_days": opp.breakeven_days,
        "position_usd": opp.position_usd,
        "estimated_annual_gain_usd": opp.estimated_annual_gain_usd,
        "viable": opp.viable,
        "confidence": opp.confidence,
        "warnings": opp.warnings,
        "saved_to": opp.saved_to,
    }


def load_history(data_file: str = DATA_FILE) -> list:
    """Load the persisted ring-buffer log."""
    if not os.path.exists(data_file):
        return []
    try:
        with open(data_file, "r") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []


def save_results(
    opp: ArbitrageOpportunity,
    data_file: str = DATA_FILE,
) -> ArbitrageOpportunity:
    """Append to ring-buffer (cap 100), atomic write. Mutates opp.saved_to."""
    history = load_history(data_file)
    entry = _opportunity_to_dict(opp)
    history.append(entry)
    # Ring-buffer: keep last RING_BUFFER_CAP entries
    if len(history) > RING_BUFFER_CAP:
        history = history[-RING_BUFFER_CAP:]

    os.makedirs(os.path.dirname(data_file), exist_ok=True)
    dir_name = os.path.dirname(data_file)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=dir_name, delete=False, suffix=".tmp"
    ) as tmp:
        json.dump(history, tmp, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, data_file)

    opp.saved_to = data_file
    return opp


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    # Demo: scan a sample set of chain yields
    samples = [
        ChainYield(
            chain="ethereum",
            protocol="Aave V3",
            pool="USDC",
            gross_apy=3.5,
            gas_drag_pct=default_gas_drag("ethereum"),
            bridge_cost_pct=default_bridge_cost("ethereum"),
            risk_premium_pct=default_risk_premium("ethereum"),
        ),
        ChainYield(
            chain="arbitrum",
            protocol="Aave V3 Arb",
            pool="USDC",
            gross_apy=4.6,
            gas_drag_pct=default_gas_drag("arbitrum"),
            bridge_cost_pct=default_bridge_cost("arbitrum"),
            risk_premium_pct=default_risk_premium("arbitrum"),
        ),
        ChainYield(
            chain="base",
            protocol="Morpho Base",
            pool="USDC",
            gross_apy=5.2,
            gas_drag_pct=default_gas_drag("base"),
            bridge_cost_pct=default_bridge_cost("base"),
            risk_premium_pct=default_risk_premium("base"),
        ),
    ]

    opps = scan_opportunities(samples, position_usd=10_000)
    best = best_opportunity(opps)

    print(f"Scanned {len(opps)} pairs.")
    if best:
        print(
            f"Best opportunity: {best.source.chain}/{best.source.protocol} → "
            f"{best.target.chain}/{best.target.protocol} | "
            f"net_spread={best.net_spread_pct:.3f}% | "
            f"breakeven={best.breakeven_days:.1f}d | "
            f"viable={best.viable} | confidence={best.confidence}"
        )
        save_results(best)
        print(f"Saved to: {best.saved_to}")
    else:
        print("No viable opportunities found.")

    sys.exit(0)
