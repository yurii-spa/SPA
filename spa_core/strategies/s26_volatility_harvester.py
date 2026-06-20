"""
spa_core/strategies/s26_volatility_harvester.py — S26 Volatility Harvester

S26: Volatility Harvester
=========================
Exotic regime-rotating strategy. DeFi lending rates spike when borrowing demand
surges (volatility / leverage unwinds). S26 leans into floating-rate supply when
borrow rates are high, and rotates into fixed-rate Pendle PT when rates compress —
capturing high carry in volatile regimes while locking in yield in calm ones.

Regime detection (Aave USDC borrow APY as the volatility proxy):
  HIGH_VOL  (borrow APY > 8.0%): 60% Aave supply (earn the spike) + T1/PT ballast
  LOW_VOL   (borrow APY < 5.0%): rotate to fixed-rate Pendle PT (lock the rate)
  NEUTRAL   (5.0–8.0%):          balanced floating + fixed

Target APY: 6–9% with lower variance than pure floating-rate lending.

Protocols / tiers:
  aave_v3      T1  — floating-rate USDC supply (rides the borrow-rate spike)
  compound_v3  T1  — floating-rate USDC supply (ballast / liquidity reserve)
  pendle_pt    T2  — fixed-rate PT USDC (locks yield when rates compress)

Rules:
  - stdlib only, no external deps in runtime code
  - read-only / advisory — never imports execution/ or risk agents
  - LLM FORBIDDEN in this module
  - approved=False from RiskPolicy is never overridden (60% Aave is a raw
    preference; the deterministic gate clips per-protocol caps and has final say)

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Set

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S26"
STRATEGY_NAME = "Volatility Harvester"
TIER          = "T2"
DESCRIPTION   = (
    "Volatility Harvester: rotates between floating-rate Aave supply (high-vol "
    "regime, borrow APY > 8%) and fixed-rate Pendle PT (low-vol, borrow APY < 5%). "
    "Target 6-9% APY with lower variance than pure lending. Advisory only."
)

# ─── Regime thresholds (Aave USDC borrow APY, percent) ────────────────────────

HIGH_VOL_BORROW_PCT: float = 8.0   # borrow APY above this → high-vol regime
LOW_VOL_BORROW_PCT:  float = 5.0   # borrow APY below this → low-vol regime

REGIME_HIGH    = "high_vol"
REGIME_LOW     = "low_vol"
REGIME_NEUTRAL = "neutral"

# ─── Protocol tiers ───────────────────────────────────────────────────────────

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":     "T1",
    "compound_v3": "T1",
    "pendle_pt":   "T2",
}

# ─── Regime allocations (fractions, each sums to 1.0) ─────────────────────────

REGIME_WEIGHTS: Dict[str, Dict[str, float]] = {
    REGIME_HIGH: {        # ride the borrow-rate spike on floating supply
        "aave_v3":     0.60,
        "compound_v3": 0.20,
        "pendle_pt":   0.20,
    },
    REGIME_LOW: {         # rates compressed → lock in fixed-rate PT
        "pendle_pt":   0.55,
        "aave_v3":     0.25,
        "compound_v3": 0.20,
    },
    REGIME_NEUTRAL: {     # balanced floating + fixed
        "aave_v3":     0.40,
        "pendle_pt":   0.35,
        "compound_v3": 0.25,
    },
}

# Default APY estimates (percent) used when no live feed is supplied.
FALLBACK_APY: Dict[str, float] = {
    "aave_v3":     4.0,
    "compound_v3": 4.8,
    "pendle_pt":   8.5,
}

TARGET_APY_MIN:   float = 6.0
TARGET_APY_MAX:   float = 9.0
RISK_SCORE:       float = 0.38
MAX_DRAWDOWN_PCT: float = 5.0


def _drop_suspended_and_renorm(
    weights: Dict[str, float],
    suspended: Optional[Set[str]],
) -> Dict[str, float]:
    """Drop suspended protocols and renormalize the remainder to sum 1.0."""
    suspended = suspended or set()
    kept = {k: v for k, v in weights.items() if k not in suspended}
    total = sum(kept.values())
    if total <= 0.0:
        return {}
    return {k: round(v / total, 8) for k, v in kept.items()}


class S26VolatilityHarvester:
    """S26 — Volatility Harvester (regime-rotating floating/fixed lending)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def detect_regime(self, borrow_apy_pct: float) -> str:
        """Classify the volatility regime from the Aave USDC borrow APY (%)."""
        if borrow_apy_pct > HIGH_VOL_BORROW_PCT:
            return REGIME_HIGH
        if borrow_apy_pct < LOW_VOL_BORROW_PCT:
            return REGIME_LOW
        return REGIME_NEUTRAL

    def get_allocation(
        self,
        borrow_apy_pct: float = 6.0,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """Target weight per protocol (fractions sum to 1.0) for the current regime.

        Suspended protocols are excluded and their weight redistributed
        proportionally across the remaining protocols.
        """
        regime = self.detect_regime(borrow_apy_pct)
        return _drop_suspended_and_renorm(REGIME_WEIGHTS[regime], suspended)

    def get_expected_apy(
        self,
        borrow_apy_pct: float = 6.0,
        apy_map: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> float:
        """Weighted expected APY (%) for the current regime allocation."""
        apy_map = apy_map or {}
        alloc = self.get_allocation(borrow_apy_pct, suspended)
        if not alloc:
            return 0.0
        weighted = 0.0
        for proto, weight in alloc.items():
            apy = apy_map.get(proto, FALLBACK_APY.get(proto, 0.0))
            weighted += weight * apy
        return round(weighted, 4)

    def get_risk_summary(
        self,
        borrow_apy_pct: float = 6.0,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        """Tier-weight breakdown for the current regime allocation."""
        alloc = self.get_allocation(borrow_apy_pct, suspended)
        t1 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T2")
        return {
            "strategy_id":     STRATEGY_ID,
            "regime":          self.detect_regime(borrow_apy_pct),
            "risk_score":      RISK_SCORE,
            "t1_weight_pct":   round(t1 * 100.0, 2),
            "t2_weight_pct":   round(t2 * 100.0, 2),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        borrow_apy_pct: float = 6.0,
        apy_map: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        """Simulate one allocation snapshot for the given capital and regime."""
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "regime":                    self.detect_regime(borrow_apy_pct),
                "allocation":                {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        alloc = self.get_allocation(borrow_apy_pct, suspended)
        apy = self.get_expected_apy(borrow_apy_pct, apy_map, suspended)
        positions = {p: round(capital_usd * w, 6) for p, w in alloc.items()}
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "regime":                    self.detect_regime(borrow_apy_pct),
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
            "high_vol_borrow_pct": HIGH_VOL_BORROW_PCT,
            "low_vol_borrow_pct":  LOW_VOL_BORROW_PCT,
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
            module="spa_core.strategies.s26_volatility_harvester",
            handler_class="S26VolatilityHarvester",
            tags=["exotic", "volatility", "regime_rotation", "aave", "pendle_pt",
                  "floating_fixed", "t2", "s26"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S26VolatilityHarvester auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S26VolatilityHarvester()
    for b in (3.0, 6.0, 10.0):
        print(f"borrow={b}% → {json.dumps(strat.simulate(100_000.0, b), indent=2)}")
