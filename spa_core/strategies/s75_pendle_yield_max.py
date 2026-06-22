"""
spa_core/strategies/s75_pendle_yield_max.py — S75 Pendle Yield Tokenisation Max

S75: Yield Tokenisation Max (Pendle)
======================================
Use Pendle Finance to buy YT (Yield Tokens) for leveraged yield exposure, or
PT (Principal Tokens) for fixed-rate safety.

If current yield (proxied by aave_v3 APY) > HIGH_RATE_THRESHOLD (6%):
  high-rate regime — buy YT (leveraged yield, rates expected to stay elevated):
    pendle_yt_susde  40%   T3   YT on sUSDe (~5–10x leveraged yield exposure)
    pendle_pt_susde  20%   T2   PT on sUSDe (fixed-rate anchor, maturity-aware)
    spark_susds      25%   T1   liquid stable reserve
    cash             15%        buffer

Else (normal-rate regime, APY ≤ 6%):
  PT for fixed-rate safety — rates expected to be stable or falling:
    pendle_pt_susde  50%   T2   PT on sUSDe (fixed rate lock-in)
    spark_susds      35%   T1   liquid stable reserve
    cash             15%        buffer

Blended expected APY:
  High-rate:  0.40*14.0 + 0.20*8.0 + 0.25*4.2 + 0.15*0.0 = 5.6+1.6+1.05 = 8.25%
  Normal:     0.50* 8.0 + 0.35*4.2 + 0.15*0.0             = 4.0+1.47     = 5.47%

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
ADR-021 governs Pendle YT (T3-SPEC — advisory only, positions not auto-opened).
Approved=False from RiskPolicy is never overridden. IS_ADVISORY = True.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Module-level identity ────────────────────────────────────────────────────

STRATEGY_ID   = "S75"
STRATEGY_NAME = "Pendle Yield Tokenisation Max"
RISK_TIER     = "T2"

TARGET_APY_MIN: float  = 3.0
TARGET_APY_MAX: float  = 25.0
MAX_DRAWDOWN_PCT: float = 30.0    # YT can lose all value in a rate collapse

HIGH_RATE_THRESHOLD: float = 0.06   # 6% — proxy via aave_v3 APY (decimal fraction)

# ─── Regime allocations ───────────────────────────────────────────────────────

ALLOC_HIGH_RATE: Dict[str, float] = {
    "pendle_yt_susde": 0.40,
    "pendle_pt_susde": 0.20,
    "spark_susds":     0.25,
    "cash":            0.15,
}

ALLOC_NORMAL_RATE: Dict[str, float] = {
    "pendle_pt_susde": 0.50,
    "spark_susds":     0.35,
    "cash":            0.15,
}

FALLBACK_APY: Dict[str, float] = {
    "pendle_yt_susde": 14.0,   # YT leveraged yield at default rates
    "pendle_pt_susde":  8.0,   # PT fixed rate on sUSDe
    "spark_susds":      4.2,   # Spark DSR
    "cash":             0.0,
    "aave_v3":          0.035, # proxy for rate regime detection
}

PROTOCOL_TIERS: Dict[str, str] = {
    "pendle_yt_susde": "T3",
    "pendle_pt_susde": "T2",
    "spark_susds":     "T1",
    "cash":            "CASH",
}


# ─── Strategy class ───────────────────────────────────────────────────────────

class S75PendleYieldMax:
    """S75 — Pendle Yield Tokenisation Max (YT/PT on sUSDe).

    Buys Pendle YT when DeFi rates are elevated (>6%), switching to PT-only
    for fixed-rate safety when rates are normal. YT gives leveraged yield
    exposure but can lose ALL value if underlying yield collapses.

    Governs by ADR-021. IS_ADVISORY = True. Stdlib only, LLM FORBIDDEN.
    """

    # Class attributes required by the strategy contract
    RISK_TIER: str          = RISK_TIER
    EXPECTED_APY_PCT: float = 14.0   # YT can 5–10x yield in high-rate regime
    IS_ADVISORY: bool        = True
    CAVEAT: str = (
        "YT can lose all value if underlying yield collapses below PT implied "
        "rate; time-decay erodes YT value continuously; complex pricing — use "
        "advisory/simulation mode only (ADR-021). PT is safer but still carries "
        "maturity/liquidity risk."
    )

    def __init__(self) -> None:
        self.strategy_id   = STRATEGY_ID
        self.strategy_name = STRATEGY_NAME

    # ── Core API ──────────────────────────────────────────────────────────────

    def allocate(self, apy_data: dict) -> Dict[str, float]:
        """Return Pendle regime-aware target weights {protocol_id: weight}.

        Uses `apy_data.get("aave_v3", FALLBACK_APY["aave_v3"])` as a proxy
        for the current DeFi rate regime (decimal — e.g. 0.035 = 3.5%).

        Args:
            apy_data: live APY snapshot; 'aave_v3' key drives regime.

        Returns:
            {protocol_id: weight} summing to 1.0.
        """
        current_apy = float(apy_data.get("aave_v3", FALLBACK_APY["aave_v3"]))
        if current_apy > HIGH_RATE_THRESHOLD:
            return dict(ALLOC_HIGH_RATE)
        return dict(ALLOC_NORMAL_RATE)

    def current_regime(self, apy_data: dict) -> str:
        """Return 'high_rate' or 'normal_rate' for the given APY snapshot."""
        current_apy = float(apy_data.get("aave_v3", FALLBACK_APY["aave_v3"]))
        return "high_rate" if current_apy > HIGH_RATE_THRESHOLD else "normal_rate"

    def compute_weighted_apy(self, apy_data: Optional[dict] = None) -> float:
        """Blended APY for the current rate regime (%).

        Args:
            apy_data: {protocol_id: apy_pct}; missing keys use FALLBACK_APY.
                      Note: 'aave_v3' here is used as regime signal only.

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
            "strategy_id":        STRATEGY_ID,
            "strategy_name":      STRATEGY_NAME,
            "risk_tier":          RISK_TIER,
            "expected_apy_pct":   self.EXPECTED_APY_PCT,
            "is_advisory":        self.IS_ADVISORY,
            "caveat":             self.CAVEAT,
            "high_rate_threshold": HIGH_RATE_THRESHOLD,
            "alloc_high_rate":    dict(ALLOC_HIGH_RATE),
            "alloc_normal_rate":  dict(ALLOC_NORMAL_RATE),
            "fallback_apy":       dict(FALLBACK_APY),
            "protocol_tiers":     dict(PROTOCOL_TIERS),
            "adr":                "ADR-021 (Pendle YT T3-SPEC advisory only)",
            "generated_at":       datetime.now(timezone.utc).isoformat(),
        }


# ─── Auto-registration ────────────────────────────────────────────────────────

def _register() -> None:
    """Register S75 in the global strategy REGISTRY on import."""
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
                "Pendle Yield Max: YT on sUSDe when aave>6% (40% YT+20% PT+25% "
                "spark+15% cash ~8.25% APY); PT-only below (50% PT+35% spark+15% "
                "cash ~5.47% APY). ADR-021 advisory. IS_ADVISORY=True."
            ),
            module="spa_core.strategies.s75_pendle_yield_max",
            handler_class="S75PendleYieldMax",
            tags=["pendle", "yt", "pt", "yield_token", "t2", "advisory", "s75", "adr021"],
        ))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "S75PendleYieldMax auto-registration failed: %s", exc
        )


_register()
