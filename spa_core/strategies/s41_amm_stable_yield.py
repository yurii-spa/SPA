"""
spa_core/strategies/s41_amm_stable_yield.py — S41 Base+Op AMM Stable Yield

S41: Base + Optimism AMM Stable Yield
=====================================
A T1-anchored portfolio that adds two L2 stablecoin-AMM LP sleeves on top of
mainnet lending anchors. The AMM legs (Aerodrome on Base, Velodrome on
Optimism) earn trading fees + protocol emissions (AERO / VELO) on USDC-USDT
correlated pairs where impermanent loss is minimal while both legs hold peg.

Allocation (fractions, sum 1.0):
  aerodrome_base      0.15  T2  USDC-USDT stable LP on Base    (fees + AERO)
  velodrome_optimism  0.10  T2  USDC-USDT stable LP on Optimism (fees + VELO)
  aave_v3             0.40  T1  mainnet lending anchor
  compound_v3         0.30  T1  mainnet lending anchor
  cash                0.05  --  dry powder buffer

Risk posture: 70% T1 anchor, 25% T2 AMM, 5% cash. T2 sleeve ≤ 50% portfolio
(ADR-019) and each protocol ≤ 20% (T2 per-protocol cap) — compliant.

Expected APY (fallback feeds):
  0.15*4.5 + 0.10*4.0 + 0.40*3.1 + 0.30*3.3 ≈ 3.3% (conservative AMM estimate).
  Upside: AERO/VELO emissions can push the AMM legs to 6-8%+ when token price
  is strong (Aerodrome USDC-USDT printed ~8% mid-2026), lifting blended APY.

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy is never overridden
  - AMM LP carries IL/depeg + emission-token volatility → T2 risk_tier

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Set

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S41"
STRATEGY_NAME = "Base+Op AMM Stable Yield"
TIER          = "T2"
DESCRIPTION   = (
    "Base+Op AMM Stable Yield: T1-anchored (70% Aave/Compound mainnet) with two "
    "L2 stablecoin-AMM LP sleeves — 15% Aerodrome USDC-USDT (Base) + 10% "
    "Velodrome USDC-USDT (Optimism), 5% cash. AMM legs earn fees + AERO/VELO "
    "emissions on correlated pairs (minimal IL). ~3.3% base APY, 6-8% upside if "
    "emissions strong. Advisory only."
)

CASH_KEY = "cash"

# ─── Protocol tiers ───────────────────────────────────────────────────────────

PROTOCOL_TIERS: Dict[str, str] = {
    "aerodrome_base":     "T2",
    "velodrome_optimism": "T2",
    "aave_v3":            "T1",
    "compound_v3":        "T1",
    CASH_KEY:            "CASH",
}

# ─── Static target allocation (fractions, sum 1.0) ────────────────────────────

WEIGHTS: Dict[str, float] = {
    "aerodrome_base":     0.15,
    "velodrome_optimism": 0.10,
    "aave_v3":            0.40,
    "compound_v3":        0.30,
    CASH_KEY:            0.05,
}

# ─── Fallback APYs (%) — conservative; AERO/VELO upside not assumed ───────────

FALLBACK_APY: Dict[str, float] = {
    "aerodrome_base":     4.5,
    "velodrome_optimism": 4.0,
    "aave_v3":            3.1,
    "compound_v3":        3.3,
    CASH_KEY:            0.0,
}

TARGET_APY_MIN:   float = 3.0
TARGET_APY_MAX:   float = 8.0   # AERO/VELO emission upside
RISK_SCORE:       float = 0.30
MAX_DRAWDOWN_PCT: float = 3.0


def _drop_suspended_and_renorm(
    weights: Dict[str, float],
    suspended: Optional[Set[str]],
) -> Dict[str, float]:
    """Drop suspended protocols (cash is never suspendable) and renorm to 1.0."""
    suspended = suspended or set()
    kept = {k: v for k, v in weights.items()
            if k == CASH_KEY or k not in suspended}
    total = sum(kept.values())
    if total <= 0.0:
        return {}
    return {k: round(v / total, 8) for k, v in kept.items()}


class S41AmmStableYield:
    """S41 — Base+Op AMM Stable Yield (static T1-anchored AMM-tilt allocation)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def get_allocation(
        self,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """Static target weights (sum 1.0). Suspended protocols renormalized out."""
        return _drop_suspended_and_renorm(WEIGHTS, suspended)

    def get_expected_apy(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> float:
        apy_map = apy_map or {}
        alloc = self.get_allocation(suspended)
        if not alloc:
            return 0.0
        weighted = 0.0
        for p, w in alloc.items():
            apy = apy_map.get(p, FALLBACK_APY.get(p, 0.0))
            weighted += w * apy
        return round(weighted, 4)

    def get_risk_summary(
        self,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        alloc = self.get_allocation(suspended)
        t1 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T2")
        cash = alloc.get(CASH_KEY, 0.0)
        return {
            "strategy_id":      STRATEGY_ID,
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "cash_weight_pct":  round(cash * 100.0, 2),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        apy_map: Optional[Dict[str, float]] = None,
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
        apy = self.get_expected_apy(apy_map, suspended)
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
            "protocol_tiers":   dict(PROTOCOL_TIERS),
            "weights":          dict(WEIGHTS),
            "fallback_apy":     dict(FALLBACK_APY),
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
            type="lp",
            risk_tier=TIER,
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s41_amm_stable_yield",
            handler_class="S41AmmStableYield",
            tags=["amm", "lp", "aerodrome", "velodrome", "base", "optimism",
                  "stablecoin", "l2", "t1_anchored", "s41"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S41AmmStableYield auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S41AmmStableYield()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
    print(json.dumps(strat.get_risk_summary(), indent=2))
