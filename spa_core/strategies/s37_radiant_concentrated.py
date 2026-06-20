"""
spa_core/strategies/s37_radiant_concentrated.py — S37 Radiant Concentrated

S37: Radiant Concentrated
=========================
Radiant Capital (Arbitrum) has historically offered the highest sustained
stablecoin yield among Arbitrum money markets. S37 concentrates in Radiant USDC
while retaining a majority mainnet T1 safety sleeve (Aave + Compound) so the
single-protocol Arbitrum exposure stays bounded.

Allocation:
  - radiant_arbitrum 50%  (T2, Radiant USDC Arbitrum, ~5.0% APY)
  - aave_v3          30%  (T1, Aave V3 mainnet, ~3.5% APY — safety)
  - compound_v3      15%  (T1, Compound V3 mainnet, ~4.8% APY — diversifier)
  - cash              5%

Weighted APY (defaults):
  0.50*5.0 + 0.30*3.5 + 0.15*4.8 + 0.05*0.0
  = 2.50 + 1.05 + 0.72 + 0.0 = 4.27%

The 50% Radiant weight is the single largest T2 position among the S34–S37 Arb
strategies; the 45% mainnet T1 sleeve (Aave + Compound) is the counterweight.

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy is never overridden
  - 50% single-T2-protocol weight exceeds the 20% per-protocol T2 cap; the
    deterministic RiskPolicy / allocator will clip it on the live path — this
    strategy expresses *intent*, the guard enforces the cap.

ADR: ADR-019 (T2 total cap ≤ 50%), ADR-025 (Arbitrum Phase 2 expansion)

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Set

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S37"
STRATEGY_NAME = "Radiant Concentrated"
TIER          = "T2"
DESCRIPTION   = (
    "Radiant Concentrated: 50% Radiant USDC Arbitrum (T2), 30% Aave V3 mainnet "
    "(T1 safety), 15% Compound V3 mainnet (T1 diversifier), 5% cash. "
    "Weighted APY ≈ 4.27%."
)

CASH_KEY = "cash"

PROTOCOL_TIERS: Dict[str, str] = {
    "radiant_arbitrum": "T2",
    "aave_v3":          "T1",
    "compound_v3":      "T1",
    CASH_KEY:           "T1",
}

# Target weights (sum 1.0).
BASE_ALLOCATION: Dict[str, float] = {
    "radiant_arbitrum": 0.50,
    "aave_v3":          0.30,
    "compound_v3":      0.15,
    CASH_KEY:           0.05,
}

FALLBACK_APY: Dict[str, float] = {
    "radiant_arbitrum": 5.0,
    "aave_v3":          3.5,
    "compound_v3":      4.8,
    CASH_KEY:           0.0,
}

# Mainnet T1 sleeve that absorbs Radiant if it is suspended.
MAINNET_FALLBACK = "aave_v3"

TARGET_APY_MIN:   float = 3.5
TARGET_APY_MAX:   float = 6.0
RISK_SCORE:       float = 0.38
MAX_DRAWDOWN_PCT: float = 4.5


class S37RadiantConcentrated:
    """S37 — Radiant-concentrated book with a mainnet T1 safety sleeve."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def get_allocation(
        self,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """Target weights (sum 1.0).

        If Radiant (or any non-cash venue) is suspended, its weight is rotated
        to the mainnet T1 fallback (``aave_v3``); cash is preserved.
        """
        suspended = suspended or set()
        alloc: Dict[str, float] = {}
        rotated = 0.0
        for proto, w in BASE_ALLOCATION.items():
            if proto != CASH_KEY and proto in suspended:
                rotated += w
                continue
            alloc[proto] = alloc.get(proto, 0.0) + w
        if rotated > 0.0:
            alloc[MAINNET_FALLBACK] = alloc.get(MAINNET_FALLBACK, 0.0) + rotated
        return alloc

    def get_radiant_weight(self, suspended: Optional[Set[str]] = None) -> float:
        """Radiant target weight under the current state."""
        return self.get_allocation(suspended).get("radiant_arbitrum", 0.0)

    def get_expected_apy(
        self,
        rates: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> float:
        """Weighted APY (%) of the current allocation."""
        rates = rates or {}
        alloc = self.get_allocation(suspended)
        apy = 0.0
        for proto, w in alloc.items():
            apy += w * float(rates.get(proto, FALLBACK_APY.get(proto, 0.0)))
        return round(apy, 4)

    def get_risk_summary(self, suspended: Optional[Set[str]] = None) -> Dict:
        alloc = self.get_allocation(suspended)
        t1 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T2")
        return {
            "strategy_id":       STRATEGY_ID,
            "risk_score":        RISK_SCORE,
            "radiant_weight_pct": round(self.get_radiant_weight(suspended) * 100.0, 2),
            "t1_weight_pct":     round(t1 * 100.0, 2),
            "t2_weight_pct":     round(t2 * 100.0, 2),
            "max_drawdown_pct":  MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        rates: Optional[Dict[str, float]] = None,
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
        alloc = self.get_allocation(suspended)
        apy = self.get_expected_apy(rates, suspended)
        positions = {p: round(capital_usd * w, 6) for p, w in alloc.items()}
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "allocation":                positions,
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
            "base_allocation":  dict(BASE_ALLOCATION),
            "protocol_tiers":   dict(PROTOCOL_TIERS),
            "fallback_apy":     dict(FALLBACK_APY),
            "mainnet_fallback": MAINNET_FALLBACK,
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
            module="spa_core.strategies.s37_radiant_concentrated",
            handler_class="S37RadiantConcentrated",
            tags=["arbitrum", "radiant", "concentrated", "l2", "aave",
                  "compound", "t1", "t2", "s37"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S37RadiantConcentrated auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S37RadiantConcentrated()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
