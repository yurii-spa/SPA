"""
spa_core/strategies/s72_basis_trade.py — S72 Basis Trade / Funding Rate Arb

S72: Basis Trade / Funding Rate Arb
=====================================
Earn the spread between spot yield and perpetual funding rate.

Two regimes determined by `apy_data.get("funding_rate_regime", "positive")`:

  POSITIVE funding (default — perpetuals trade at premium, longs pay shorts):
    aave_v3        30%   T1   safe T1 lending base
    compound_v3    20%   T1   T1 diversifier
    ethena_susde   30%   T3   captures funding premium via sUSDe
    cash           20%        large buffer for regime-flip protection

  NEUTRAL / NEGATIVE funding (perps at parity or discount):
    aave_v3        50%   T1   retreat to safety
    compound_v3    30%   T1   T1 diversifier
    spark_susds    15%   T1   stable DSR base
    cash            5%        min RiskPolicy buffer

Blended expected APY:
  Positive: 0.30*3.5 + 0.20*4.8 + 0.30*12.0 + 0.20*0.0 = 5.61%
  Negative: 0.50*3.5 + 0.30*4.8 + 0.15*4.2  + 0.05*0.0 = 4.43%

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
Approved=False from RiskPolicy is never overridden. IS_ADVISORY = True.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Module-level identity ────────────────────────────────────────────────────

STRATEGY_ID   = "S72"
STRATEGY_NAME = "Basis Trade / Funding Rate Arb"
RISK_TIER     = "T2"

TARGET_APY_MIN: float = 3.0
TARGET_APY_MAX: float = 15.0
MAX_DRAWDOWN_PCT: float = 8.0

POSITIVE_REGIME = "positive"
NEGATIVE_REGIME = "negative"

# ─── Regime allocations ───────────────────────────────────────────────────────

ALLOC_POSITIVE: Dict[str, float] = {
    "aave_v3":      0.30,
    "compound_v3":  0.20,
    "ethena_susde": 0.30,
    "cash":         0.20,
}

ALLOC_NEGATIVE: Dict[str, float] = {
    "aave_v3":     0.50,
    "compound_v3": 0.30,
    "spark_susds": 0.15,
    "cash":        0.05,
}

FALLBACK_APY: Dict[str, float] = {
    "aave_v3":      3.5,
    "compound_v3":  4.8,
    "ethena_susde": 12.0,
    "spark_susds":  4.2,
    "cash":         0.0,
}

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":      "T1",
    "compound_v3":  "T1",
    "ethena_susde": "T3",
    "spark_susds":  "T1",
    "cash":         "CASH",
}


# ─── Strategy class ───────────────────────────────────────────────────────────

class S72BasisTrade:
    """S72 — Basis Trade / Funding Rate Arb.

    Earn the spread between spot lending yield and perpetual funding rate.
    Tilts toward sUSDe (funding arb) when funding_rate_regime == 'positive';
    retreats to T1-only when neutral/negative.

    IS_ADVISORY = True. Stdlib only, LLM FORBIDDEN.
    """

    # Class attributes required by the strategy contract
    RISK_TIER: str          = RISK_TIER
    EXPECTED_APY_PCT: float = 9.5
    IS_ADVISORY: bool        = True
    CAVEAT: str = (
        "Funding rate is regime-dependent; can go near-zero or negative in bear "
        "markets or when perp open interest collapses. sUSDe depeg/smart contract "
        "risk remains. Cash buffer protects against sudden regime flips."
    )

    def __init__(self) -> None:
        self.strategy_id   = STRATEGY_ID
        self.strategy_name = STRATEGY_NAME

    # ── Core API ──────────────────────────────────────────────────────────────

    def allocate(self, apy_data: dict) -> Dict[str, float]:
        """Return regime-aware target weights {protocol_id: weight}.

        Reads `apy_data.get('funding_rate_regime', 'positive')` to choose
        allocation. Sum of weights = 1.0 in both regimes.

        Args:
            apy_data: live snapshot; must include 'funding_rate_regime' for
                      dynamic switching; defaults to 'positive'.

        Returns:
            {protocol_id: weight} summing to 1.0.
        """
        regime = apy_data.get("funding_rate_regime", POSITIVE_REGIME)
        if regime == POSITIVE_REGIME:
            return dict(ALLOC_POSITIVE)
        # neutral or negative → safety mode
        return dict(ALLOC_NEGATIVE)

    def current_regime(self, apy_data: dict) -> str:
        """Return the detected funding regime string."""
        return apy_data.get("funding_rate_regime", POSITIVE_REGIME)

    def compute_weighted_apy(self, apy_data: Optional[dict] = None) -> float:
        """Blended APY for the current regime (%).

        Args:
            apy_data: {protocol_id: apy_pct} plus optional 'funding_rate_regime'.

        Returns:
            Blended APY in percent.
        """
        if apy_data is None:
            apy_data = {}
        weights = self.allocate(apy_data)
        total = 0.0
        for protocol, weight in weights.items():
            apy = float(apy_data.get(protocol, FALLBACK_APY.get(protocol, 0.0)))
            total += weight * apy
        return total

    def get_info(self) -> Dict:
        """Return strategy metadata dict."""
        return {
            "strategy_id":      STRATEGY_ID,
            "strategy_name":    STRATEGY_NAME,
            "risk_tier":        RISK_TIER,
            "expected_apy_pct": self.EXPECTED_APY_PCT,
            "is_advisory":      self.IS_ADVISORY,
            "caveat":           self.CAVEAT,
            "alloc_positive":   dict(ALLOC_POSITIVE),
            "alloc_negative":   dict(ALLOC_NEGATIVE),
            "fallback_apy":     dict(FALLBACK_APY),
            "protocol_tiers":   dict(PROTOCOL_TIERS),
            "generated_at":     datetime.now(timezone.utc).isoformat(),
        }


# ─── Auto-registration ────────────────────────────────────────────────────────

def _register() -> None:
    """Register S72 in the global strategy REGISTRY on import."""
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="yield_loop",
            risk_tier="T2",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=(
                "Basis Trade / Funding Rate Arb. POSITIVE regime: Aave 30% + "
                "Compound 20% + sUSDe 30% + cash 20% (~5.6% blended). NEGATIVE "
                "regime: Aave 50% + Compound 30% + Spark 15% + cash 5% (~4.4%). "
                "Regime from apy_data['funding_rate_regime']. IS_ADVISORY=True."
            ),
            module="spa_core.strategies.s72_basis_trade",
            handler_class="S72BasisTrade",
            tags=["basis", "funding_rate", "ethena", "t2", "advisory", "s72"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S72BasisTrade auto-registration failed: %s", exc
        )


_register()
