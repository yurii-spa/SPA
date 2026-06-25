"""
spa_core/strategy_lab/liquidator/ — Cross-Domain / Balance-Sheet Liquidator de-risk (RESEARCH).

The CHEAP, read-only, no-capital, no-custody test of thesis #3: "be the delta-neutral liquidator
for long-tail / nested collateral on isolated lending (Morpho Blue / Euler V2) — when atomic-MEV
bots fail (illiquid collateral in crashes), clear the bad debt with a balance sheet, hedge the
price risk via perps, and unwind the nested collateral over hours/days."

This package measures the OPPORTUNITY SIZE read-only. The CEX-execution + custody + balance-sheet
legs are explicitly OUT OF SCOPE (deferred), exactly as the rates-desk brief defers the CEX hedge
leg — here we only quantify the addressable long-tail liquidation / penalty / OEV-recapture pool.

Two modules:
  market_monitor.py       — read-only index of isolated lending markets (Morpho Blue + Euler V2)
                            via the keyless DeFiLlama /pools surface, classifying each market's
                            collateral kind (vanilla / LRT / PT / LP / BTC / synth) so the LONG
                            TAIL (esoteric collateral where atomic-MEV liquidation breaks) is
                            isolated.
  opportunity_estimator.py — per market, estimate the addressable liquidation opportunity: the
                            statutory penalty $ on the borrowed-against base, scaled by an honest
                            annual liquidation turnover, and GATED by the EXIT GAP — does the
                            collateral have enough on-chain DEX depth for an ATOMIC liquidation
                            (reusing the liquidation_nav slippage model)? If NOT, that illiquid
                            share is the "MEV-bots-can't, balance-sheet-can" addressable edge.

stdlib only, deterministic, fail-CLOSED, LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from spa_core.strategy_lab.liquidator.market_monitor import (
    CollateralKind,
    IsolatedMarket,
    MarketMonitor,
    classify_collateral,
)
from spa_core.strategy_lab.liquidator.opportunity_estimator import (
    MarketOpportunity,
    OpportunityEstimator,
    UniverseOpportunity,
)

__all__ = [
    "CollateralKind",
    "IsolatedMarket",
    "MarketMonitor",
    "classify_collateral",
    "MarketOpportunity",
    "OpportunityEstimator",
    "UniverseOpportunity",
]
