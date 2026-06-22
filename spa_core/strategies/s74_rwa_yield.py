"""
spa_core/strategies/s74_rwa_yield.py — S74 RWA Yield

S74: RWA Yield
===============
Real-World Asset backed yield:
  Maple Finance USDC pools  — institutional lending (~8–9% APY)
  Ondo Finance USDY          — tokenised US Treasury (~5.35% APY)
  Spark sUSDS                — liquid DeFi reserve (~4.2% APY)

Allocation switches on `apy_data.get("maple", 6.5)`:
  maple_apy > 7.0 (attractive rate):
    maple     45%   T2   institutional lending
    ondo_usdy 30%   T2   T-bill backed stablecoin
    spark_susds 25% T1   liquid reserve

  maple_apy ≤ 7.0 (ordinary rate):
    maple     30%   T2   reduced exposure
    ondo_usdy 40%   T2   increased T-bill allocation
    spark_susds 30% T1   larger liquid buffer

Blended expected APY:
  High-maple:  0.45*8.5 + 0.30*5.35 + 0.25*4.2 = 3.83 + 1.61 + 1.05 = 6.48%
  Normal-maple: 0.30*8.5 + 0.40*5.35 + 0.30*4.2 = 2.55 + 2.14 + 1.26 = 5.95%

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
Approved=False from RiskPolicy is never overridden. IS_ADVISORY = True.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Module-level identity ────────────────────────────────────────────────────

STRATEGY_ID   = "S74"
STRATEGY_NAME = "RWA Yield"
RISK_TIER     = "T2"

TARGET_APY_MIN: float  = 4.0
TARGET_APY_MAX: float  = 11.0
MAX_DRAWDOWN_PCT: float = 5.0

MAPLE_HIGH_THRESHOLD: float = 7.0   # switch to high-maple allocation above this

# ─── Regime allocations ───────────────────────────────────────────────────────

ALLOC_HIGH_MAPLE: Dict[str, float] = {
    "maple":       0.45,
    "ondo_usdy":   0.30,
    "spark_susds": 0.25,
}

ALLOC_NORMAL_MAPLE: Dict[str, float] = {
    "maple":       0.30,
    "ondo_usdy":   0.40,
    "spark_susds": 0.30,
}

FALLBACK_APY: Dict[str, float] = {
    "maple":       6.5,    # Maple Finance historical midpoint
    "ondo_usdy":   5.35,   # Ondo USDY US T-bill backed
    "spark_susds": 4.2,    # Spark DSR
    "cash":        0.0,
}

PROTOCOL_TIERS: Dict[str, str] = {
    "maple":       "T2",
    "ondo_usdy":   "T2",
    "spark_susds": "T1",
    "cash":        "CASH",
}


# ─── Strategy class ───────────────────────────────────────────────────────────

class S74RWAYield:
    """S74 — RWA Yield (Maple + Ondo USDY + Spark sUSDS).

    Real-World Asset backed yield strategy. Tilts toward Maple (institutional
    lending) when rates are attractive (>7%), otherwise increases T-bill
    allocation for stability.

    IS_ADVISORY = True. Stdlib only, LLM FORBIDDEN.
    """

    # Class attributes required by the strategy contract
    RISK_TIER: str          = RISK_TIER
    EXPECTED_APY_PCT: float = 6.8
    IS_ADVISORY: bool        = True
    CAVEAT: str = (
        "Smart contract + custodian risk on RWA protocols; less liquid than DeFi "
        "native; US-person restrictions on some RWA tokens (Ondo USDY, Maple); "
        "credit risk on institutional borrowers in Maple pools."
    )

    def __init__(self) -> None:
        self.strategy_id   = STRATEGY_ID
        self.strategy_name = STRATEGY_NAME

    # ── Core API ──────────────────────────────────────────────────────────────

    def allocate(self, apy_data: dict) -> Dict[str, float]:
        """Return RWA target weights, regime-aware on Maple rate.

        Reads `apy_data.get("maple", FALLBACK_APY["maple"])` to switch
        between high-maple (≥7%) and normal-maple allocations.

        Args:
            apy_data: live APY snapshot; 'maple' key drives regime.

        Returns:
            {protocol_id: weight} summing to 1.0.
        """
        maple_apy = float(apy_data.get("maple", FALLBACK_APY["maple"]))
        if maple_apy > MAPLE_HIGH_THRESHOLD:
            return dict(ALLOC_HIGH_MAPLE)
        return dict(ALLOC_NORMAL_MAPLE)

    def compute_weighted_apy(self, apy_data: Optional[dict] = None) -> float:
        """Blended APY for the current maple regime (%).

        Args:
            apy_data: {protocol_id: apy_pct}; missing keys use FALLBACK_APY.

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

    def current_regime(self, apy_data: dict) -> str:
        """Return 'high_maple' or 'normal_maple' for the given APY snapshot."""
        maple_apy = float(apy_data.get("maple", FALLBACK_APY["maple"]))
        return "high_maple" if maple_apy > MAPLE_HIGH_THRESHOLD else "normal_maple"

    def get_info(self) -> Dict:
        """Return strategy metadata dict."""
        return {
            "strategy_id":       STRATEGY_ID,
            "strategy_name":     STRATEGY_NAME,
            "risk_tier":         RISK_TIER,
            "expected_apy_pct":  self.EXPECTED_APY_PCT,
            "is_advisory":       self.IS_ADVISORY,
            "caveat":            self.CAVEAT,
            "maple_high_threshold": MAPLE_HIGH_THRESHOLD,
            "alloc_high_maple":  dict(ALLOC_HIGH_MAPLE),
            "alloc_normal_maple": dict(ALLOC_NORMAL_MAPLE),
            "fallback_apy":      dict(FALLBACK_APY),
            "protocol_tiers":    dict(PROTOCOL_TIERS),
            "generated_at":      datetime.now(timezone.utc).isoformat(),
        }


# ─── Auto-registration ────────────────────────────────────────────────────────

def _register() -> None:
    """Register S74 in the global strategy REGISTRY on import."""
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier="T2",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=(
                "RWA Yield: Maple Finance institutional pools + Ondo USDY "
                "tokenised T-bills + Spark sUSDS. maple>7%: 45/30/25%; else "
                "30/40/30%. ~6.8% blended APY. IS_ADVISORY=True. LLM FORBIDDEN."
            ),
            module="spa_core.strategies.s74_rwa_yield",
            handler_class="S74RWAYield",
            tags=["rwa", "maple", "ondo", "t2", "advisory", "s74"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S74RWAYield auto-registration failed: %s", exc
        )


_register()
