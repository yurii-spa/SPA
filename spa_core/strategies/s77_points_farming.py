"""
spa_core/strategies/s77_points_farming.py — S77 Points + Yield Farming

S77: Points + Yield Farming
=============================
Deposit into protocols actively distributing points or tokens alongside base
yield. Points value is speculative but can multiply effective APY 3–5x during
active campaigns.

Currently active point/reward programs (as of 2026-06):
  Morpho Steakhouse  — MORPHO token rewards (live)
  Pendle YT sUSDe    — PENDLE governance tokens + Ethena season points
  Spark sUSDS        — stable base, no points but T1 anchor

Target allocation (static — concentrate where point campaigns are active):
  morpho_steakhouse   40%   T2   MORPHO token rewards + base yield 6.5%
  pendle_yt_susde     25%   T3   PENDLE rewards + Ethena points + YT yield
  spark_susds         20%   T1   stable base, liquid
  cash                15%        buffer (points farming can be illiquid)

Blended base APY (no points): 0.40*6.5 + 0.25*14.0 + 0.20*4.2 + 0.15*0.0
  = 2.60 + 3.50 + 0.84 = 6.94%
Points-adjusted APY estimate: base 6.94% + points premium ~11% = ~18%

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
Points value is HIGHLY UNCERTAIN and may be 0. This is advisory/simulation only.
Approved=False from RiskPolicy is never overridden. IS_ADVISORY = True.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Module-level identity ────────────────────────────────────────────────────

STRATEGY_ID   = "S77"
STRATEGY_NAME = "Points + Yield Farming"
RISK_TIER     = "T3"

TARGET_APY_MIN: float  = 5.0   # base APY without any points
TARGET_APY_MAX: float  = 40.0  # peak if point programs very active
MAX_DRAWDOWN_PCT: float = 25.0

# Points APY premium — ADVISORY estimate only, may be 0
POINTS_APY_PREMIUM_PCT: float = 11.0

# ─── Protocol allocation ──────────────────────────────────────────────────────

ALLOCATION: Dict[str, float] = {
    "morpho_steakhouse": 0.40,
    "pendle_yt_susde":   0.25,
    "spark_susds":       0.20,
    "cash":              0.15,
}

FALLBACK_APY: Dict[str, float] = {
    "morpho_steakhouse": 6.5,   # Morpho Steakhouse base APY
    "pendle_yt_susde":  14.0,   # Pendle YT base yield (excl. points)
    "spark_susds":       4.2,   # Spark DSR
    "cash":              0.0,
}

PROTOCOL_TIERS: Dict[str, str] = {
    "morpho_steakhouse": "T2",
    "pendle_yt_susde":   "T3",
    "spark_susds":       "T1",
    "cash":              "CASH",
}

# Protocol → active reward campaign (informational — not machine-enforced)
REWARD_CAMPAIGNS: Dict[str, str] = {
    "morpho_steakhouse": "MORPHO token (live — check morpho.xyz/rewards)",
    "pendle_yt_susde":   "PENDLE + Ethena ENA season points",
    "spark_susds":       "none (stable base only)",
}


# ─── Strategy class ───────────────────────────────────────────────────────────

class S77PointsFarming:
    """S77 — Points + Yield Farming.

    Concentrates capital in protocols running active token/points campaigns.
    Base APY ~6.94%; with points premium ~18% (ADVISORY estimate — may be 0).

    IS_ADVISORY = True. Stdlib only, LLM FORBIDDEN.
    """

    # Class attributes required by the strategy contract
    RISK_TIER: str          = RISK_TIER
    EXPECTED_APY_PCT: float = 18.0   # base ~7% + points premium ~11%
    IS_ADVISORY: bool        = True
    CAVEAT: str = (
        "Points value is HIGHLY UNCERTAIN and may be 0; token price risk on MORPHO "
        "and PENDLE; point programs end abruptly; YT component carries yield-collapse "
        "risk (ADR-021); strategy should be reviewed weekly as campaigns change."
    )

    def __init__(self) -> None:
        self.strategy_id   = STRATEGY_ID
        self.strategy_name = STRATEGY_NAME

    # ── Core API ──────────────────────────────────────────────────────────────

    def allocate(self, apy_data: dict) -> Dict[str, float]:
        """Return fixed target weights {protocol_id: weight}. Sum = 1.0.

        Static allocation — concentrate where campaigns are hottest.
        Points value not in weights; captured separately via compute_points_apy().

        Args:
            apy_data: live APY snapshot (not used — static allocation).

        Returns:
            {protocol_id: weight} summing to 1.0.
        """
        return dict(ALLOCATION)

    def compute_weighted_apy(self, apy_data: Optional[dict] = None) -> float:
        """Blended BASE APY (no points premium) in percent.

        Args:
            apy_data: {protocol_id: apy_pct}; missing keys use FALLBACK_APY.

        Returns:
            Base blended APY in percent (does NOT include points premium).
        """
        if apy_data is None:
            apy_data = {}
        total = 0.0
        for protocol, weight in ALLOCATION.items():
            apy = float(apy_data.get(protocol, FALLBACK_APY.get(protocol, 0.0)))
            total += weight * apy
        return total

    def compute_points_adjusted_apy(
        self,
        apy_data: Optional[dict] = None,
        points_premium_pct: Optional[float] = None,
    ) -> float:
        """Advisory estimate of points-adjusted APY.

        IMPORTANT: points premium is speculative; this is for advisory
        simulation only. Actual points value may be 0.

        Args:
            apy_data: {protocol_id: apy_pct}.
            points_premium_pct: override premium (%). Defaults to
                                POINTS_APY_PREMIUM_PCT.

        Returns:
            base_apy + points_premium (in percent). Advisory only.
        """
        base = self.compute_weighted_apy(apy_data)
        premium = (
            points_premium_pct
            if points_premium_pct is not None
            else POINTS_APY_PREMIUM_PCT
        )
        return base + premium

    def active_campaigns(self) -> Dict[str, str]:
        """Return the reward campaign descriptions per protocol."""
        return dict(REWARD_CAMPAIGNS)

    def get_info(self) -> Dict:
        """Return strategy metadata dict."""
        return {
            "strategy_id":       STRATEGY_ID,
            "strategy_name":     STRATEGY_NAME,
            "risk_tier":         RISK_TIER,
            "expected_apy_pct":  self.EXPECTED_APY_PCT,
            "is_advisory":       self.IS_ADVISORY,
            "caveat":            self.CAVEAT,
            "allocation":        dict(ALLOCATION),
            "fallback_apy":      dict(FALLBACK_APY),
            "protocol_tiers":    dict(PROTOCOL_TIERS),
            "reward_campaigns":  dict(REWARD_CAMPAIGNS),
            "points_apy_premium_pct": POINTS_APY_PREMIUM_PCT,
            "generated_at":      datetime.now(timezone.utc).isoformat(),
        }


# ─── Auto-registration ────────────────────────────────────────────────────────

def _register() -> None:
    """Register S77 in the global strategy REGISTRY on import."""
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
                "Points + Yield Farming: 40% Morpho (MORPHO rewards) + 25% Pendle "
                "YT (PENDLE+Ethena points) + 20% Spark + 15% cash. Base ~6.94% APY "
                "+ ~11% points premium advisory = ~18%. IS_ADVISORY=True. "
                "Points value may be 0. LLM FORBIDDEN."
            ),
            module="spa_core.strategies.s77_points_farming",
            handler_class="S77PointsFarming",
            tags=["points", "farming", "morpho", "pendle", "t3", "advisory", "s77"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S77PointsFarming auto-registration failed: %s", exc
        )


_register()
