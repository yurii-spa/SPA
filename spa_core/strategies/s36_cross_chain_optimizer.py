"""
spa_core/strategies/s36_cross_chain_optimizer.py — S36 Cross-Chain Optimizer

S36: Cross-Chain Optimizer
==========================
Weekly cross-chain rotation. Each week the strategy compares the best available
stablecoin APY on three venues — mainnet T1, Arbitrum T2, and Base T2 — and
tilts 60% of the book to the highest-yielding chain. A fixed 30% mainnet T1
anchor is always retained as a bridging-risk buffer, and 10% sits in cash.

Allocation:
  - 60%  highest-yielding chain (mainnet T1 / Arbitrum T2 / Base T2)
  - 30%  mainnet T1 anchor (aave_v3) — bridging-risk buffer, always held
  - 10%  cash

When the highest-yielding chain *is* mainnet, the 60% tilt and the 30% anchor
both land on ``aave_v3`` and are merged (90% mainnet, 10% cash).

Chain representatives (one stable venue per chain):
  - mainnet  -> aave_v3            (T1, ~3.5% APY)
  - arbitrum -> radiant_arbitrum   (T2, ~5.0% APY)
  - base     -> aave_v3_base       (T2, ~4.0% APY)

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy is never overridden
  - 30% mainnet anchor is a hard buffer against L2 bridge / sequencer risk

ADR: ADR-019 (T2 total cap ≤ 50%), ADR-025 (Arbitrum), ADR-025 (Base cap)

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Set

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S36"
STRATEGY_NAME = "Cross-Chain Optimizer"
TIER          = "T2"
DESCRIPTION   = (
    "Cross-Chain Optimizer: weekly compares best stablecoin APY across mainnet "
    "T1, Arbitrum T2 and Base T2; tilts 60% to the top chain, holds a 30% "
    "mainnet T1 anchor (bridge-risk buffer) and 10% cash."
)

CASH_KEY = "cash"

# Tilt / anchor / cash split.
TILT_WEIGHT:   float = 0.60   # to the highest-yielding chain
ANCHOR_WEIGHT: float = 0.30   # always mainnet T1
CASH_WEIGHT:   float = 0.10

# Representative stablecoin venue per chain.
CHAIN_VENUES: Dict[str, str] = {
    "mainnet":  "aave_v3",
    "arbitrum": "radiant_arbitrum",
    "base":     "aave_v3_base",
}

MAINNET_ANCHOR = "aave_v3"

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":          "T1",
    "radiant_arbitrum": "T2",
    "aave_v3_base":     "T2",
    CASH_KEY:           "T1",
}

# Fallback APY (%) per representative venue.
FALLBACK_APY: Dict[str, float] = {
    "aave_v3":          3.5,
    "radiant_arbitrum": 5.0,
    "aave_v3_base":     4.0,
    CASH_KEY:           0.0,
}

# Fallback per-chain APY (used to pick the best chain when no live data given).
FALLBACK_CHAIN_APY: Dict[str, float] = {
    "mainnet":  3.5,
    "arbitrum": 5.0,
    "base":     4.0,
}

TARGET_APY_MIN:   float = 3.5
TARGET_APY_MAX:   float = 6.5
RISK_SCORE:       float = 0.36
MAX_DRAWDOWN_PCT: float = 4.5


class S36CrossChainOptimizer:
    """S36 — weekly cross-chain tilt with a fixed mainnet anchor."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def _chain_rates(
        self,
        chain_apy: Optional[Dict[str, float]],
        suspended: Optional[Set[str]],
    ) -> Dict[str, float]:
        """Resolve per-chain APY over non-suspended chains, filling defaults."""
        suspended = suspended or set()
        chain_apy = chain_apy or {}
        out: Dict[str, float] = {}
        for chain, venue in CHAIN_VENUES.items():
            if chain in suspended or venue in suspended:
                continue
            out[chain] = float(chain_apy.get(chain, FALLBACK_CHAIN_APY.get(chain, 0.0)))
        return out

    def best_chain(
        self,
        chain_apy: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Optional[str]:
        """Return the highest-yielding eligible chain (None if none eligible)."""
        rates = self._chain_rates(chain_apy, suspended)
        # Always keep mainnet eligible for the tilt if all else suspended.
        if not rates:
            return None
        return max(rates.items(), key=lambda kv: kv[1])[0]

    def get_allocation(
        self,
        chain_apy: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """Target weights (sum 1.0): 60% best chain, 30% mainnet anchor, 10% cash.

        If the best chain is mainnet, the tilt and anchor merge onto ``aave_v3``.
        If no L2 chain is eligible, the tilt falls back to the mainnet anchor.
        """
        best = self.best_chain(chain_apy, suspended)
        alloc: Dict[str, float] = {}
        # Anchor — always mainnet T1.
        alloc[MAINNET_ANCHOR] = alloc.get(MAINNET_ANCHOR, 0.0) + ANCHOR_WEIGHT
        # Tilt — to best chain's venue (mainnet anchor if no eligible chain).
        tilt_venue = CHAIN_VENUES.get(best, MAINNET_ANCHOR) if best else MAINNET_ANCHOR
        alloc[tilt_venue] = alloc.get(tilt_venue, 0.0) + TILT_WEIGHT
        # Cash.
        alloc[CASH_KEY] = alloc.get(CASH_KEY, 0.0) + CASH_WEIGHT
        return alloc

    def get_expected_apy(
        self,
        rates: Optional[Dict[str, float]] = None,
        chain_apy: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> float:
        """Weighted APY (%) of the current allocation.

        ``rates`` maps venue->APY; when absent, per-venue fallbacks are used and
        the tilt venue's rate is taken from ``chain_apy`` if supplied.
        """
        rates = dict(rates or {})
        # Let chain_apy inform venue rates for the chosen tilt.
        chain_apy = chain_apy or {}
        for chain, venue in CHAIN_VENUES.items():
            if chain in chain_apy and venue not in rates:
                rates[venue] = float(chain_apy[chain])
        alloc = self.get_allocation(chain_apy, suspended)
        apy = 0.0
        for venue, w in alloc.items():
            apy += w * float(rates.get(venue, FALLBACK_APY.get(venue, 0.0)))
        return round(apy, 4)

    def get_risk_summary(
        self,
        chain_apy: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        alloc = self.get_allocation(chain_apy, suspended)
        t1 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T2")
        return {
            "strategy_id":      STRATEGY_ID,
            "risk_score":       RISK_SCORE,
            "best_chain":       self.best_chain(chain_apy, suspended),
            "anchor_weight_pct": round(ANCHOR_WEIGHT * 100.0, 2),
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        rates: Optional[Dict[str, float]] = None,
        chain_apy: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "allocation":                {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        alloc = self.get_allocation(chain_apy, suspended)
        apy = self.get_expected_apy(rates, chain_apy, suspended)
        positions = {p: round(capital_usd * w, 6) for p, w in alloc.items()}
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "allocation":                positions,
            "best_chain":                self.best_chain(chain_apy, suspended),
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "status":                    "ok",
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> Dict:
        return {
            "strategy_id":      STRATEGY_ID,
            "strategy_name":    STRATEGY_NAME,
            "tier":             TIER,
            "description":      DESCRIPTION,
            "tilt_weight":      TILT_WEIGHT,
            "anchor_weight":    ANCHOR_WEIGHT,
            "cash_weight":      CASH_WEIGHT,
            "chain_venues":     dict(CHAIN_VENUES),
            "protocol_tiers":   dict(PROTOCOL_TIERS),
            "fallback_apy":     dict(FALLBACK_APY),
            "fallback_chain_apy": dict(FALLBACK_CHAIN_APY),
            "target_apy_min":   TARGET_APY_MIN,
            "target_apy_max":   TARGET_APY_MAX,
            "risk_score":       RISK_SCORE,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "timestamp":        datetime.now(timezone.utc).isoformat(),
        }


def _register() -> None:
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier=TIER,
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s36_cross_chain_optimizer",
            handler_class="S36CrossChainOptimizer",
            tags=["cross_chain", "arbitrum", "base", "mainnet", "rotation",
                  "l2", "anchor", "t1", "t2", "s36"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S36CrossChainOptimizer auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S36CrossChainOptimizer()
    print(json.dumps(strat.simulate(100_000.0, chain_apy={"arbitrum": 6.0}), indent=2))
