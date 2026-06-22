"""
spa_core/strategies/s73_leverage_loop.py — S73 Leverage Loop / Recursive Lending

S73: Leverage Loop / Recursive Lending
========================================
Supply wstETH to Aave, borrow ETH, swap to wstETH, repeat.
NET yield = staking_yield * leverage - borrow_rate * (leverage - 1).

At conservative 2x leverage with 3.5% staking yield and 1.5% borrow cost:
  effective_apy = 3.5 * 2.0 - 1.5 * (2.0 - 1) = 7.0 - 1.5 = 5.5%

The leverage is MODELLED in the APY projection. The allocate() method
returns weights for the capital deployment (85% wstETH Aave, 15% cash)
— the recursive loop is advisory only, not executed automatically.

Target allocation (static):
  aave_v3_wsteth   85%   T2   wstETH lending on Aave V3 (leverage modelled)
  cash             15%        mandatory buffer — covers liquidation margin

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
Approved=False from RiskPolicy is never overridden. IS_ADVISORY = True.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Module-level identity ────────────────────────────────────────────────────

STRATEGY_ID   = "S73"
STRATEGY_NAME = "Leverage Loop / Recursive Lending"
RISK_TIER     = "T3"

TARGET_APY_MIN: float  = 4.0
TARGET_APY_MAX: float  = 12.0
MAX_DRAWDOWN_PCT: float = 20.0

# Conservative 2x leverage, max safe ~3x
LEVERAGE_RATIO: float          = 2.0
LIQUIDATION_THRESHOLD: float   = 0.825   # Aave wstETH LTV limit
STAKING_APY_DEFAULT: float     = 3.5     # stETH staking yield (%)
BORROW_RATE_DEFAULT: float     = 1.5     # Aave ETH borrow rate (%)

# ─── Protocol allocation ──────────────────────────────────────────────────────

ALLOCATION: Dict[str, float] = {
    "aave_v3_wsteth": 0.85,
    "cash":           0.15,
}

FALLBACK_APY: Dict[str, float] = {
    "aave_v3_wsteth": 7.5,   # effective 2x leverage yield
    "cash":           0.0,
}

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3_wsteth": "T2",
    "cash":           "CASH",
}


# ─── Strategy class ───────────────────────────────────────────────────────────

class S73LeverageLoop:
    """S73 — Leverage Loop / Recursive Lending.

    Models 2x ETH/wstETH leverage loop on Aave V3.
    effective_apy = staking_apy * leverage - borrow_rate * (leverage - 1).

    The allocation is advisory-only: 85% aave_v3_wsteth + 15% cash.
    The recursion is NOT executed automatically. IS_ADVISORY = True.

    Stdlib only, LLM FORBIDDEN.
    """

    # Class attributes required by the strategy contract
    RISK_TIER: str          = RISK_TIER
    EXPECTED_APY_PCT: float = 5.5   # 3.5*2 - 1.5*1 = 5.5% conservative
    IS_ADVISORY: bool        = True
    CAVEAT: str = (
        "Liquidation risk if ETH/stETH depeg or price drop breaches Aave LTV; "
        "gas-cost intensive to set up and unwind; not suitable for <$50K capital; "
        "borrow rate volatile in high-utilisation environments."
    )

    LEVERAGE_RATIO: float        = LEVERAGE_RATIO
    LIQUIDATION_THRESHOLD: float = LIQUIDATION_THRESHOLD

    def __init__(self) -> None:
        self.strategy_id   = STRATEGY_ID
        self.strategy_name = STRATEGY_NAME

    # ── Core API ──────────────────────────────────────────────────────────────

    def allocate(self, apy_data: dict) -> Dict[str, float]:
        """Return fixed target weights {protocol_id: weight}. Sum = 1.0.

        The leverage is modelled in the APY, not the weights. Weights
        represent where the initial capital is deployed.

        Args:
            apy_data: live APY snapshot (not used — static allocation).

        Returns:
            {protocol_id: weight} summing to 1.0.
        """
        return dict(ALLOCATION)

    def effective_apy(
        self,
        staking_apy: float,
        borrow_rate: float,
    ) -> float:
        """Compute net APY of the leverage loop (%).

        Formula: staking_apy * leverage - borrow_rate * (leverage - 1)

        Args:
            staking_apy: stETH/wstETH staking yield in percent (e.g. 3.5).
            borrow_rate: Aave ETH borrow rate in percent (e.g. 1.5).

        Returns:
            Net APY in percent (can be negative if borrow_rate is very high).
        """
        return (
            staking_apy * self.LEVERAGE_RATIO
            - borrow_rate * (self.LEVERAGE_RATIO - 1.0)
        )

    def compute_weighted_apy(self, apy_data: Optional[dict] = None) -> float:
        """Blended portfolio APY including cash drag.

        Args:
            apy_data: {protocol_id: apy_pct}; 'aave_v3_wsteth' overrides
                      the effective leverage-loop APY if supplied; otherwise
                      calls effective_apy(STAKING_APY_DEFAULT, BORROW_RATE_DEFAULT).

        Returns:
            Blended APY in percent.
        """
        if apy_data is None:
            apy_data = {}

        if "aave_v3_wsteth" in apy_data:
            wsteth_apy = float(apy_data["aave_v3_wsteth"])
        else:
            wsteth_apy = self.effective_apy(STAKING_APY_DEFAULT, BORROW_RATE_DEFAULT)

        cash_apy = 0.0
        return (
            ALLOCATION["aave_v3_wsteth"] * wsteth_apy
            + ALLOCATION["cash"] * cash_apy
        )

    def is_eligible(
        self,
        min_capital_usd: float = 50_000.0,
        capital_usd: float = 100_000.0,
    ) -> bool:
        """Check capital threshold eligibility (not suitable <$50K).

        Args:
            min_capital_usd: minimum required capital (default $50K).
            capital_usd: current portfolio capital.

        Returns:
            True if capital_usd >= min_capital_usd.
        """
        return capital_usd >= min_capital_usd

    def get_info(self) -> Dict:
        """Return strategy metadata dict."""
        eff = self.effective_apy(STAKING_APY_DEFAULT, BORROW_RATE_DEFAULT)
        return {
            "strategy_id":         STRATEGY_ID,
            "strategy_name":       STRATEGY_NAME,
            "risk_tier":           RISK_TIER,
            "expected_apy_pct":    self.EXPECTED_APY_PCT,
            "is_advisory":         self.IS_ADVISORY,
            "caveat":              self.CAVEAT,
            "leverage_ratio":      LEVERAGE_RATIO,
            "liquidation_threshold": LIQUIDATION_THRESHOLD,
            "effective_apy_default": eff,
            "staking_apy_default": STAKING_APY_DEFAULT,
            "borrow_rate_default": BORROW_RATE_DEFAULT,
            "allocation":          dict(ALLOCATION),
            "fallback_apy":        dict(FALLBACK_APY),
            "protocol_tiers":      dict(PROTOCOL_TIERS),
            "generated_at":        datetime.now(timezone.utc).isoformat(),
        }


# ─── Auto-registration ────────────────────────────────────────────────────────

def _register() -> None:
    """Register S73 in the global strategy REGISTRY on import."""
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="yield_loop",
            risk_tier="T3",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=(
                "Leverage Loop: 2x wstETH/ETH recursive loop on Aave V3. "
                "effective_apy = 3.5%*2 - 1.5%*1 = 5.5% conservative. "
                "Allocation: 85% aave_v3_wsteth + 15% cash. Advisory-only. "
                "IS_ADVISORY=True. Min capital $50K. LLM FORBIDDEN."
            ),
            module="spa_core.strategies.s73_leverage_loop",
            handler_class="S73LeverageLoop",
            tags=["leverage", "loop", "wsteth", "aave", "t3", "advisory", "s73"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S73LeverageLoop auto-registration failed: %s", exc
        )


_register()
