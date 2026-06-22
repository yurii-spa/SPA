"""
spa_core/strategies/s76_concentrated_lp.py — S76 Concentrated Liquidity LP

S76: Concentrated Liquidity Stablecoin LP
==========================================
Provide liquidity to the USDC/USDT pair on Aerodrome (Base) in a tight range
(±0.1%). Near-zero impermanent loss since both legs are USD-pegged stablecoins.
Earn trading fee APY typically 6–15%.

Allocation switches on `apy_data.get("aerodrome_usdc_lp", 0.085)`:
  lp_apy > 0.06 (LP is attractive, above cost-of-capital):
    aerodrome_usdc_lp  60%   T2   tight-range USDC/USDT LP on Aerodrome (Base)
    aave_v3            25%   T1   safe T1 lending backup
    cash               15%        RiskPolicy buffer + out-of-range contingency

  lp_apy ≤ 0.06 (LP unattractive — fees collapsed or volume dried up):
    aave_v3            50%   T1   retreat to safe T1 lending
    compound_v3        35%   T1   T1 diversifier
    cash               15%        buffer

Blended expected APY:
  LP active:  0.60*8.5 + 0.25*3.5 + 0.15*0.0 = 5.10 + 0.88 = 5.97%
  LP off:     0.50*3.5 + 0.35*4.8 + 0.15*0.0 = 1.75 + 1.68 = 3.43%

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
Approved=False from RiskPolicy is never overridden. IS_ADVISORY = True.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Module-level identity ────────────────────────────────────────────────────

STRATEGY_ID   = "S76"
STRATEGY_NAME = "Concentrated Liquidity Stablecoin LP"
RISK_TIER     = "T2"

TARGET_APY_MIN: float  = 2.0
TARGET_APY_MAX: float  = 18.0
MAX_DRAWDOWN_PCT: float = 5.0

LP_ATTRACTIVE_THRESHOLD: float = 0.06  # 6% APY threshold (decimal fraction)

# ─── Regime allocations ───────────────────────────────────────────────────────

ALLOC_LP_ACTIVE: Dict[str, float] = {
    "aerodrome_usdc_lp": 0.60,
    "aave_v3":           0.25,
    "cash":              0.15,
}

ALLOC_LP_OFF: Dict[str, float] = {
    "aave_v3":    0.50,
    "compound_v3": 0.35,
    "cash":       0.15,
}

FALLBACK_APY: Dict[str, float] = {
    "aerodrome_usdc_lp": 0.085,  # 8.5% — typical Aerodrome USDC/USDT fees
    "aave_v3":           3.5,
    "compound_v3":       4.8,
    "cash":              0.0,
}

PROTOCOL_TIERS: Dict[str, str] = {
    "aerodrome_usdc_lp": "T2",
    "aave_v3":           "T1",
    "compound_v3":       "T1",
    "cash":              "CASH",
}


# ─── Strategy class ───────────────────────────────────────────────────────────

class S76ConcentratedLP:
    """S76 — Concentrated Liquidity Stablecoin LP (Aerodrome USDC/USDT).

    Provides concentrated LP in tight USDC/USDT range on Aerodrome (Base).
    Near-zero IL since both assets are USD-pegged. Falls back to T1 lending
    if LP APY drops below 6%.

    IS_ADVISORY = True. Stdlib only, LLM FORBIDDEN.
    """

    # Class attributes required by the strategy contract
    RISK_TIER: str          = RISK_TIER
    EXPECTED_APY_PCT: float = 8.5   # Aerodrome USDC/USDT typical range
    IS_ADVISORY: bool        = True
    CAVEAT: str = (
        "Smart contract risk on Aerodrome/Base; liquidity out of range means 0 "
        "fee income (manual rerange needed); USDC or USDT depeg risk (even minor "
        "depegs cause IL in tight range); Base bridge/sequencer risk."
    )

    def __init__(self) -> None:
        self.strategy_id   = STRATEGY_ID
        self.strategy_name = STRATEGY_NAME

    # ── Core API ──────────────────────────────────────────────────────────────

    def allocate(self, apy_data: dict) -> Dict[str, float]:
        """Return LP regime-aware target weights {protocol_id: weight}.

        Reads `apy_data.get("aerodrome_usdc_lp", FALLBACK_APY["aerodrome_usdc_lp"])`
        (as a decimal — e.g. 0.085 = 8.5%) to choose allocation.

        Args:
            apy_data: live APY snapshot; 'aerodrome_usdc_lp' drives regime.

        Returns:
            {protocol_id: weight} summing to 1.0.
        """
        lp_apy = float(apy_data.get(
            "aerodrome_usdc_lp", FALLBACK_APY["aerodrome_usdc_lp"]
        ))
        if lp_apy > LP_ATTRACTIVE_THRESHOLD:
            return dict(ALLOC_LP_ACTIVE)
        return dict(ALLOC_LP_OFF)

    def current_regime(self, apy_data: dict) -> str:
        """Return 'lp_active' or 'lp_off' for the given APY snapshot."""
        lp_apy = float(apy_data.get(
            "aerodrome_usdc_lp", FALLBACK_APY["aerodrome_usdc_lp"]
        ))
        return "lp_active" if lp_apy > LP_ATTRACTIVE_THRESHOLD else "lp_off"

    def compute_weighted_apy(self, apy_data: Optional[dict] = None) -> float:
        """Blended APY for the current LP regime (%).

        Note: aerodrome_usdc_lp APY in apy_data must be in DECIMAL form
        (e.g. 0.085) for regime detection; but for APY blending it is
        multiplied as a raw percentage — supply it in percent (8.5) for
        correct blending, or the fallback (0.085) is used as 0.085%.

        For consistency with strategy APY blending convention, protocol APY
        values supplied via apy_data for blending should be in percent.

        Args:
            apy_data: {protocol_id: apy_pct_or_decimal}

        Returns:
            Blended APY in percent.
        """
        if apy_data is None:
            apy_data = {}
        weights = self.allocate(apy_data)
        total = 0.0
        for protocol, weight in weights.items():
            raw = apy_data.get(protocol, FALLBACK_APY.get(protocol, 0.0))
            apy_pct = float(raw)
            # aerodrome_usdc_lp fallback is stored as decimal (0.085) not percent
            if protocol == "aerodrome_usdc_lp" and apy_pct < 1.0:
                apy_pct = apy_pct * 100.0
            total += weight * apy_pct
        return total

    def get_info(self) -> Dict:
        """Return strategy metadata dict."""
        return {
            "strategy_id":         STRATEGY_ID,
            "strategy_name":       STRATEGY_NAME,
            "risk_tier":           RISK_TIER,
            "expected_apy_pct":    self.EXPECTED_APY_PCT,
            "is_advisory":         self.IS_ADVISORY,
            "caveat":              self.CAVEAT,
            "lp_attractive_threshold": LP_ATTRACTIVE_THRESHOLD,
            "alloc_lp_active":     dict(ALLOC_LP_ACTIVE),
            "alloc_lp_off":        dict(ALLOC_LP_OFF),
            "fallback_apy":        dict(FALLBACK_APY),
            "protocol_tiers":      dict(PROTOCOL_TIERS),
            "generated_at":        datetime.now(timezone.utc).isoformat(),
        }


# ─── Auto-registration ────────────────────────────────────────────────────────

def _register() -> None:
    """Register S76 in the global strategy REGISTRY on import."""
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lp",
            risk_tier="T2",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=(
                "Concentrated LP: Aerodrome USDC/USDT tight-range (Base). "
                "LP>6%: 60% aerodrome_usdc_lp + 25% aave + 15% cash (~6% APY). "
                "LP≤6%: 50% aave + 35% compound + 15% cash (~3.4%). "
                "Near-zero IL. IS_ADVISORY=True. LLM FORBIDDEN."
            ),
            module="spa_core.strategies.s76_concentrated_lp",
            handler_class="S76ConcentratedLP",
            tags=["lp", "aerodrome", "usdc", "usdt", "base", "t2", "advisory", "s76"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S76ConcentratedLP auto-registration failed: %s", exc
        )


_register()
