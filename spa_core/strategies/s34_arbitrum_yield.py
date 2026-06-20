"""
spa_core/strategies/s34_arbitrum_yield.py — S34 Arbitrum Yield

S34: Arbitrum Yield (T2 Arb-focused)
====================================
Arbitrum-dominant stablecoin yield strategy. The book is concentrated on
Arbitrum L2 money markets (Aave V3 Arbitrum + Radiant) with a mainnet T1 anchor
for bridge-risk mitigation, plus a small cash buffer.

Target allocation:
  - aave_arbitrum    40%  (Aave V3 Arbitrum USDC, T1, ~4.5% APY)
  - radiant_arbitrum 30%  (Radiant USDC Arbitrum,  T2, ~5.0% APY)
  - aave_v3          25%  (Aave V3 mainnet USDC,    T1 anchor, ~3.5% APY)
  - cash              5%  (idle buffer, 0% APY)

Bridge-risk trigger (sequencer rotation):
  If the Arbitrum sequencer is reported down, the strategy rotates the entire
  Arbitrum allocation (aave_arbitrum + radiant_arbitrum) to the mainnet anchor
  (aave_v3). The cash buffer is preserved. This is the core safety mechanism of
  an Arb-focused book: an L2 sequencer outage freezes withdrawals, so capital is
  parked on mainnet until the sequencer recovers.

Weighted APY (defaults, sequencer up):
  0.40*4.5 + 0.30*5.0 + 0.25*3.5 + 0.05*0.0
  = 1.80 + 1.50 + 0.875 + 0.0 = 4.175%

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy is never overridden
  - Atomic writes (tmp + os.replace) where persistence is needed

ADR: ADR-019 (T2 total cap ≤ 50%), ADR-025 (Arbitrum Phase 2 expansion)

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Set

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S34"
STRATEGY_NAME = "Arbitrum Yield"
TIER          = "T2"
DESCRIPTION   = (
    "Arbitrum Yield: Arb-focused stablecoin book — 40% Aave V3 Arbitrum, "
    "30% Radiant Arbitrum, 25% Aave V3 mainnet anchor, 5% cash. Rotates the "
    "Arbitrum allocation to mainnet when the L2 sequencer is down (bridge-risk "
    "trigger). Weighted APY ≈ 4.18%."
)

CASH_KEY = "cash"

# Protocols and their tier classification
PROTOCOL_TIERS: Dict[str, str] = {
    "aave_arbitrum":    "T1",   # Aave V3 Arbitrum (L2 anchor, blue-chip)
    "radiant_arbitrum": "T2",   # Radiant Capital Arbitrum (Arb-native money market)
    "aave_v3":          "T1",   # Aave V3 mainnet (bridge-risk anchor)
    CASH_KEY:           "T1",   # idle cash
}

# Pools that live on Arbitrum L2 (rotated out on sequencer-down).
ARBITRUM_POOLS = ("aave_arbitrum", "radiant_arbitrum")

# Mainnet anchor that absorbs rotated capital.
MAINNET_ANCHOR = "aave_v3"

# Target weights (sum 1.0) when the sequencer is healthy.
BASE_ALLOCATION: Dict[str, float] = {
    "aave_arbitrum":    0.40,
    "radiant_arbitrum": 0.30,
    "aave_v3":          0.25,
    CASH_KEY:           0.05,
}

# Fallback APY (%) — used when a live rate is absent. Per task spec.
FALLBACK_APY: Dict[str, float] = {
    "aave_arbitrum":    4.5,
    "radiant_arbitrum": 5.0,
    "aave_v3":          3.5,
    CASH_KEY:           0.0,
}

TARGET_APY_MIN:   float = 3.5
TARGET_APY_MAX:   float = 6.0
RISK_SCORE:       float = 0.34
MAX_DRAWDOWN_PCT: float = 4.0


class S34ArbitrumYield:
    """S34 — Arbitrum Yield with sequencer-down rotation to mainnet."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def get_allocation(
        self,
        sequencer_up: bool = True,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """Target weights (sum 1.0).

        When ``sequencer_up`` is False, the Arbitrum allocation is rotated into
        the mainnet anchor (``aave_v3``); the cash buffer is preserved. Suspended
        protocols are also rotated to the anchor (cash kept).
        """
        suspended = suspended or set()
        alloc: Dict[str, float] = {}
        rotated = 0.0
        for proto, w in BASE_ALLOCATION.items():
            if proto == CASH_KEY:
                alloc[CASH_KEY] = alloc.get(CASH_KEY, 0.0) + w
                continue
            down = (not sequencer_up and proto in ARBITRUM_POOLS)
            if down or proto in suspended:
                rotated += w
                continue
            alloc[proto] = alloc.get(proto, 0.0) + w
        if rotated > 0.0:
            alloc[MAINNET_ANCHOR] = alloc.get(MAINNET_ANCHOR, 0.0) + rotated
        # Drop zero weights for cleanliness, keep cash even if 0? Keep cash.
        return {p: w for p, w in alloc.items() if w > 0.0 or p == CASH_KEY}

    def is_bridge_risk_triggered(self, sequencer_up: bool) -> bool:
        """True when the sequencer-down rotation is active."""
        return not sequencer_up

    def get_arbitrum_exposure_pct(self, sequencer_up: bool = True) -> float:
        """Percent of the book held on Arbitrum L2 under the current state."""
        alloc = self.get_allocation(sequencer_up=sequencer_up)
        arb = sum(alloc.get(p, 0.0) for p in ARBITRUM_POOLS)
        return round(arb * 100.0, 4)

    def get_expected_apy(
        self,
        rates: Optional[Dict[str, float]] = None,
        sequencer_up: bool = True,
        suspended: Optional[Set[str]] = None,
    ) -> float:
        """Weighted APY (%) of the current allocation."""
        rates = rates or {}
        alloc = self.get_allocation(sequencer_up=sequencer_up, suspended=suspended)
        apy = 0.0
        for proto, w in alloc.items():
            apy += w * float(rates.get(proto, FALLBACK_APY.get(proto, 0.0)))
        return round(apy, 4)

    def get_risk_summary(self, sequencer_up: bool = True) -> Dict:
        alloc = self.get_allocation(sequencer_up=sequencer_up)
        t1 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T2")
        return {
            "strategy_id":          STRATEGY_ID,
            "risk_score":           RISK_SCORE,
            "t1_weight_pct":        round(t1 * 100.0, 2),
            "t2_weight_pct":        round(t2 * 100.0, 2),
            "arbitrum_exposure_pct": self.get_arbitrum_exposure_pct(sequencer_up),
            "bridge_risk_triggered": self.is_bridge_risk_triggered(sequencer_up),
            "max_drawdown_pct":     MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        rates: Optional[Dict[str, float]] = None,
        sequencer_up: bool = True,
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
        alloc = self.get_allocation(sequencer_up=sequencer_up, suspended=suspended)
        apy = self.get_expected_apy(rates, sequencer_up, suspended)
        positions = {p: round(capital_usd * w, 6) for p, w in alloc.items()}
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "allocation":                positions,
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "sequencer_up":              sequencer_up,
            "bridge_risk_triggered":     self.is_bridge_risk_triggered(sequencer_up),
            "status":                    "ok",
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> Dict:
        return {
            "strategy_id":      STRATEGY_ID,
            "strategy_name":    STRATEGY_NAME,
            "tier":             TIER,
            "description":      DESCRIPTION,
            "base_allocation":  dict(BASE_ALLOCATION),
            "protocol_tiers":   dict(PROTOCOL_TIERS),
            "fallback_apy":     dict(FALLBACK_APY),
            "arbitrum_pools":   list(ARBITRUM_POOLS),
            "mainnet_anchor":   MAINNET_ANCHOR,
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
            module="spa_core.strategies.s34_arbitrum_yield",
            handler_class="S34ArbitrumYield",
            tags=["arbitrum", "radiant", "aave", "l2", "bridge_risk",
                  "sequencer", "t1", "t2", "s34"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S34ArbitrumYield auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S34ArbitrumYield()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
    print(json.dumps(strat.simulate(100_000.0, sequencer_up=False), indent=2))
