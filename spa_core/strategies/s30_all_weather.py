"""
spa_core/strategies/s30_all_weather.py — S30 All-Weather DeFi

S30: All-Weather DeFi
=====================
A regime-adaptive portfolio designed to earn in any market condition. It reads
market regime from Aave USDC utilization as a risk-appetite proxy (high
utilization = leverage demand = bull; low utilization = deleveraging = bear) and
shifts between an aggressive T2 tilt, a balanced mix, and a defensive T1 + cash
posture.

Regime (Aave USDC utilization, fraction 0–1; percent inputs auto-normalized):
  BULL     (util > 0.80): heavier T2 — chase higher APY while demand is strong
  BEAR     (util < 0.50): heavy T1 + cash — preserve capital as TVL falls
  SIDEWAYS (0.50–0.80):   balanced T1/T2 with a cash buffer

Target: 4–6% APY in any regime with < 2% max drawdown.

Protocols / tiers:
  aave_v3 T1, compound_v3 T1 — defensive anchors
  morpho_blue T2, yearn_v3 T2 — yield engines (bull/sideways only)
  cash — dry powder (bear/sideways buffer)

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy is never overridden

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Set

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S30"
STRATEGY_NAME = "All-Weather DeFi"
TIER          = "T2"
DESCRIPTION   = (
    "All-Weather DeFi: regime-adaptive from Aave utilization. Bull (util>80%) → "
    "heavier T2; bear (util<50%) → heavy T1+cash; sideways → balanced. Targets "
    "4-6% APY in any regime with <2% max drawdown. Advisory only."
)

# ─── Regime thresholds (Aave USDC utilization, fraction) ──────────────────────

UTIL_BULL: float = 0.80    # above → bull
UTIL_BEAR: float = 0.50    # below → bear

REGIME_BULL     = "bull"
REGIME_BEAR     = "bear"
REGIME_SIDEWAYS = "sideways"

# ─── Protocol tiers ───────────────────────────────────────────────────────────

CASH_KEY = "cash"

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":     "T1",
    "compound_v3": "T1",
    "morpho_blue": "T2",
    "yearn_v3":    "T2",
    CASH_KEY:      "CASH",
}

# ─── Regime allocations (fractions, each sums to 1.0) ─────────────────────────

REGIME_WEIGHTS: Dict[str, Dict[str, float]] = {
    REGIME_BULL: {           # T1=0.40, T2=0.50, cash=0.10
        "aave_v3":     0.25,
        "compound_v3": 0.15,
        "morpho_blue": 0.30,
        "yearn_v3":    0.20,
        CASH_KEY:      0.10,
    },
    REGIME_SIDEWAYS: {       # T1=0.55, T2=0.30, cash=0.15
        "aave_v3":     0.30,
        "compound_v3": 0.25,
        "morpho_blue": 0.20,
        "yearn_v3":    0.10,
        CASH_KEY:      0.15,
    },
    REGIME_BEAR: {           # T1=0.70, cash=0.30, T2=0
        "aave_v3":     0.40,
        "compound_v3": 0.30,
        CASH_KEY:      0.30,
    },
}

FALLBACK_APY: Dict[str, float] = {
    "aave_v3":     4.0,
    "compound_v3": 4.8,
    "morpho_blue": 7.0,
    "yearn_v3":    6.0,
    CASH_KEY:      0.0,
}

TARGET_APY_MIN:   float = 4.0
TARGET_APY_MAX:   float = 6.0
RISK_SCORE:       float = 0.28
MAX_DRAWDOWN_PCT: float = 2.0


def _normalize_util(util: float) -> float:
    """Accept utilization as fraction (0–1) or percent (0–100); return fraction."""
    u = float(util)
    if u > 1.5:   # clearly a percent value
        u = u / 100.0
    return max(0.0, min(1.0, u))


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


class S30AllWeather:
    """S30 — All-Weather DeFi (utilization-driven regime allocation)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def detect_regime(self, utilization: float) -> str:
        """Classify regime from Aave USDC utilization (fraction or percent)."""
        u = _normalize_util(utilization)
        if u > UTIL_BULL:
            return REGIME_BULL
        if u < UTIL_BEAR:
            return REGIME_BEAR
        return REGIME_SIDEWAYS

    def get_allocation(
        self,
        utilization: float = 0.65,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """Regime weights (sum 1.0). Suspended protocols are renormalized out."""
        regime = self.detect_regime(utilization)
        return _drop_suspended_and_renorm(REGIME_WEIGHTS[regime], suspended)

    def get_expected_apy(
        self,
        utilization: float = 0.65,
        apy_map: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> float:
        apy_map = apy_map or {}
        alloc = self.get_allocation(utilization, suspended)
        if not alloc:
            return 0.0
        weighted = 0.0
        for p, w in alloc.items():
            apy = apy_map.get(p, FALLBACK_APY.get(p, 0.0))
            weighted += w * apy
        return round(weighted, 4)

    def get_risk_summary(
        self,
        utilization: float = 0.65,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        alloc = self.get_allocation(utilization, suspended)
        t1 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T2")
        cash = alloc.get(CASH_KEY, 0.0)
        return {
            "strategy_id":     STRATEGY_ID,
            "regime":          self.detect_regime(utilization),
            "risk_score":      RISK_SCORE,
            "t1_weight_pct":   round(t1 * 100.0, 2),
            "t2_weight_pct":   round(t2 * 100.0, 2),
            "cash_weight_pct": round(cash * 100.0, 2),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        utilization: float = 0.65,
        apy_map: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "regime":                    self.detect_regime(utilization),
                "allocation":                {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        alloc = self.get_allocation(utilization, suspended)
        apy = self.get_expected_apy(utilization, apy_map, suspended)
        positions = {p: round(capital_usd * w, 6) for p, w in alloc.items()}
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "regime":                    self.detect_regime(utilization),
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
            "regime_weights":   {k: dict(v) for k, v in REGIME_WEIGHTS.items()},
            "fallback_apy":     dict(FALLBACK_APY),
            "util_bull":        UTIL_BULL,
            "util_bear":        UTIL_BEAR,
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
            module="spa_core.strategies.s30_all_weather",
            handler_class="S30AllWeather",
            tags=["exotic", "all_weather", "regime_adaptive", "utilization",
                  "bull_bear_sideways", "capital_preservation", "t2", "s30"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S30AllWeather auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S30AllWeather()
    for u in (0.40, 0.65, 0.90):
        print(f"util={u} → {json.dumps(strat.simulate(100_000.0, u), indent=2)}")
