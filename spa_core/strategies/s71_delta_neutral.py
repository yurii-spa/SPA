"""
spa_core/strategies/s71_delta_neutral.py — S71 Delta-Neutral Yield

S71: Delta-Neutral Yield (Ethena)
==================================
Hold sUSDe (Ethena synthetic dollar) which internally earns stETH staking yield
plus the ETH perpetual short funding rate. No actual derivatives are executed in
this codebase — the strategy models delta-neutral exposure as a high-yield
stablecoin position.

Target allocation (static):
  ethena_susde   60%   T3   synthetic dollar; staking + funding yield (~8–20% APY)
  spark_susds    25%   T1   sUSDS liquid reserve; safer DSR-backed base
  cash           15%        RiskPolicy buffer

Blended expected APY: 0.60*12.0 + 0.25*4.2 + 0.15*0.0 = 8.25%

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
Approved=False from RiskPolicy is never overridden. IS_ADVISORY = True.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Module-level identity ────────────────────────────────────────────────────

STRATEGY_ID   = "S71"
STRATEGY_NAME = "Delta-Neutral Yield (Ethena)"
RISK_TIER     = "T2"

TARGET_APY_MIN: float = 6.0
TARGET_APY_MAX: float = 22.0
MAX_DRAWDOWN_PCT: float = 10.0

# ─── Protocol allocation ──────────────────────────────────────────────────────

ALLOCATION: Dict[str, float] = {
    "ethena_susde": 0.60,
    "spark_susds":  0.25,
    "cash":         0.15,
}

FALLBACK_APY: Dict[str, float] = {
    "ethena_susde": 12.0,
    "spark_susds":  4.2,
    "cash":         0.0,
}

PROTOCOL_TIERS: Dict[str, str] = {
    "ethena_susde": "T3",
    "spark_susds":  "T1",
    "cash":         "CASH",
}


# ─── Strategy class ───────────────────────────────────────────────────────────

class S71DeltaNeutral:
    """S71 — Delta-Neutral Yield via Ethena sUSDe.

    Long sUSDe (Ethena synthetic dollar) which internally earns stETH staking
    yield + short ETH perp funding. No actual derivatives in this codebase —
    modelled as a high-yield stablecoin position.

    60% ethena_susde · 25% spark_susds · 15% cash.
    Blended APY ≈ 8.25% at defaults. IS_ADVISORY = True.

    Stdlib only, LLM FORBIDDEN, read-only/advisory.
    """

    # Class attributes required by the strategy contract
    RISK_TIER: str         = RISK_TIER
    EXPECTED_APY_PCT: float = 8.25
    IS_ADVISORY: bool       = True
    CAVEAT: str = (
        "Funding rate can go negative; sUSDe depeg risk on ETH spot/futures "
        "divergence; Ethena smart contract risk; not capital-guaranteed."
    )

    def __init__(self) -> None:
        self.strategy_id   = STRATEGY_ID
        self.strategy_name = STRATEGY_NAME

    # ── Core API ──────────────────────────────────────────────────────────────

    def allocate(self, apy_data: dict) -> Dict[str, float]:
        """Return fixed target weights {protocol_id: weight}.

        Weights are static for S71 (no regime switching). Sum = 1.0.

        Args:
            apy_data: live APY snapshot (not used in static allocation, kept
                      for interface consistency with other strategies).

        Returns:
            {protocol_id: weight} with weights summing to 1.0.
        """
        return dict(ALLOCATION)

    def compute_weighted_apy(self, apy_data: Optional[dict] = None) -> float:
        """Compute blended APY using provided or fallback APYs (%).

        Args:
            apy_data: {protocol_id: apy_pct} override; missing keys use FALLBACK_APY.

        Returns:
            Blended APY in percent.
        """
        if apy_data is None:
            apy_data = {}
        total = 0.0
        for protocol, weight in ALLOCATION.items():
            apy = float(apy_data.get(protocol, FALLBACK_APY.get(protocol, 0.0)))
            total += weight * apy
        return total

    def get_info(self) -> Dict:
        """Return strategy metadata dict."""
        return {
            "strategy_id":     STRATEGY_ID,
            "strategy_name":   STRATEGY_NAME,
            "risk_tier":       RISK_TIER,
            "expected_apy_pct": self.EXPECTED_APY_PCT,
            "is_advisory":     self.IS_ADVISORY,
            "caveat":          self.CAVEAT,
            "allocation":      dict(ALLOCATION),
            "fallback_apy":    dict(FALLBACK_APY),
            "protocol_tiers":  dict(PROTOCOL_TIERS),
            "generated_at":    datetime.now(timezone.utc).isoformat(),
        }


# ─── Auto-registration ────────────────────────────────────────────────────────

def _register() -> None:
    """Register S71 in the global strategy REGISTRY on import."""
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
                "Delta-Neutral Yield via Ethena sUSDe. 60% sUSDe (staking + "
                "funding, ~12% APY) + 25% spark sUSDS (DSR, ~4.2%) + 15% cash. "
                "Blended ~8.25% APY. IS_ADVISORY=True. Funding risk mitigated by "
                "spark sUSDS buffer. LLM FORBIDDEN."
            ),
            module="spa_core.strategies.s71_delta_neutral",
            handler_class="S71DeltaNeutral",
            tags=["ethena", "delta_neutral", "susde", "t2", "advisory", "s71"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S71DeltaNeutral auto-registration failed: %s", exc
        )


_register()
