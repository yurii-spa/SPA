"""
spa_core/strategies/s21_cashflow_research.py — RS-002 Cashflow (RESEARCH ONLY)

Research Strategy RS-002: Cashflow / Concentrated LP
Target APY: 29.24% (GROSS — before impermanent loss and execution costs)
Net APY estimate: 12-18% in sideways market, 0-negative in trending
Status: RESEARCH-ONLY

WARNING: The 29.24% target is GROSS of impermanent loss.
In trending BTC markets, concentrated LP positions can suffer
significant IL. Net realized returns depend heavily on:
- BTC price volatility regime
- Range policy (narrow/wide)
- Rebalancing frequency and cost
- Venue fees and utilization

Allocation:
  btc_usd_conc_liq    60%  40% APY gross (IL not modeled — placeholder)
  rwa_conc_liq        10%  18% APY (RWA venue unspecified — placeholder)
  trader_losses_vault 14%  20% APY (GMX/Hyperliquid-style — placeholder)
  stablecoin_deposit  16%   4% APY (T1 lending — live data eligible)

Research exclusion reasons:
  - btc_usd_conc_liq: no point-in-time IL-adjusted historical series
  - rwa_conc_liq: venue and product identity not specified
  - trader_losses_vault: depends on market regime, no clean historical PnL
  - Only stablecoin_deposit (16%) is strict-eligible in live system

Caveat details:
  - BTC/USD concentrated liquidity 40% = GROSS without impermanent loss
  - IL at BTC ±20% move can eat 10-15% of real return
  - "Trader losses" = GMX GLP / Hyperliquid vault — depends on market directionality
  - Real net APY is closer to 12-18% in neutral market, 0% or negative in trending

LLM FORBIDDEN in this module.
Stdlib only. No external dependencies.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Module-level constants ───────────────────────────────────────────────────

RESEARCH_ONLY = True
STRATEGY_ID = "S21"
STRATEGY_NAME = "RS-002 Cashflow (Research)"
TARGET_APY_GROSS = 29.24        # % gross blended, before IL and costs
NET_APY_ESTIMATE_RANGE = (12.0, 18.0)   # sideways market net estimate
CAPITAL_TARGET = 50_000.0       # research model capital
RISK_TIER = "RESEARCH"

# ─── Allocation weights (must sum to 1.0) ────────────────────────────────────

ALLOCATION: Dict[str, float] = {
    "btc_usd_conc_liq":    0.60,   # Concentrated liquidity BTC/USD
    "rwa_conc_liq":        0.10,   # Concentrated liquidity RWA
    "trader_losses_vault": 0.14,   # GMX/Hyperliquid vault (trader losses)
    "stablecoin_deposit":  0.16,   # T1 stablecoin deposit (strict eligible)
}

# ─── Gross APY assumptions per leg (placeholder — not live data) ─────────────

GROSS_APY_ASSUMPTIONS: Dict[str, float] = {
    "btc_usd_conc_liq":    40.0,   # GROSS, IL not modeled — placeholder only
    "rwa_conc_liq":        18.0,   # venue/product unspecified — placeholder
    "trader_losses_vault": 20.0,   # market-regime dependent — placeholder
    "stablecoin_deposit":   4.0,   # T1 lending — live data eligible
}

# ─── Data source eligibility ──────────────────────────────────────────────────

# Which legs can use live/strict data (True) vs research placeholder (False)
STRICT_ELIGIBLE: Dict[str, bool] = {
    "btc_usd_conc_liq":    False,  # no IL-adjusted historical series
    "rwa_conc_liq":        False,  # venue unspecified
    "trader_losses_vault": False,  # no clean historical PnL
    "stablecoin_deposit":  True,   # T1 lending adapter available
}

# ─── Net APY estimates by volatility regime ───────────────────────────────────

NET_APY_BY_REGIME: Dict[str, float] = {
    "sideways": 15.0,    # midpoint of 12-18% estimate
    "trending": 3.0,     # IL drags heavily; near breakeven
    "crash":    -5.0,    # severe IL + vault losses
    "bull":     18.0,    # upper bound of sideways estimate (BTC up, tight range)
}

# ─── IL drag model coefficients ──────────────────────────────────────────────
# Simplified quadratic IL approximation for concentrated LP positions.
# Actual IL = 2*sqrt(price_ratio)/(1+price_ratio) - 1 for full-range.
# Concentrated LP amplifies this by a factor depending on range width.
# We use a simplified quadratic: IL_pct ≈ 0.5 * (btc_move_pct / 100)^2 * amplifier
# with amplifier = 2.0 to reflect narrow-range concentration.

_IL_AMPLIFIER = 2.0   # concentration factor vs full-range Uniswap v2


# ══════════════════════════════════════════════════════════════════════════════
# CashflowResearchStrategy
# ══════════════════════════════════════════════════════════════════════════════

class CashflowResearchStrategy:
    """
    RS-002 Cashflow Research Strategy.

    RESEARCH-ONLY: This strategy contains placeholder APY assumptions for
    components where no clean historical data exists. It MUST NOT be used
    as input to live allocation, strict backtests, or risk decisions.

    Only the stablecoin_deposit leg (16%) is strict-eligible for live data.
    All other legs use modeled/estimated figures.

    Parameters
    ----------
    capital : float
        Notional capital for sizing calculations. Default: $50,000.
    """

    def __init__(self, capital: float = CAPITAL_TARGET) -> None:
        if capital <= 0:
            raise ValueError(f"capital must be > 0, got {capital}")
        self._capital = float(capital)
        self._created_at = datetime.now(timezone.utc).isoformat()

    # ──────────────────────────────────────────────────────────────────────────
    # Core allocation
    # ──────────────────────────────────────────────────────────────────────────

    def allocate(self, capital: float, live_apy: Optional[Dict[str, float]] = None) -> Dict:
        """
        Return allocation dict with dollar sizes and APY per leg.

        For strict-eligible legs (stablecoin_deposit), live_apy is used if
        provided. All other legs always use GROSS_APY_ASSUMPTIONS (placeholder).

        Parameters
        ----------
        capital : float
            Capital to allocate (USD).
        live_apy : dict, optional
            Map of source_id → live APY%. Only applied to strict-eligible legs.

        Returns
        -------
        dict
            {
              "strategy_id": ...,
              "research_only": True,
              "total_capital": ...,
              "legs": {
                  leg_id: {
                      "weight": float,
                      "usd": float,
                      "apy_pct": float,
                      "apy_source": "live" | "placeholder",
                      "strict_eligible": bool,
                  }
              },
              "blended_gross_apy": float,
              "weights_sum": float,
              "timestamp": str,
            }
        """
        if capital <= 0:
            raise ValueError(f"capital must be > 0, got {capital}")

        live_apy = live_apy or {}
        legs: Dict[str, dict] = {}
        weights_sum = 0.0
        blended = 0.0

        for leg, weight in ALLOCATION.items():
            weights_sum += weight
            usd = capital * weight
            eligible = STRICT_ELIGIBLE[leg]

            if eligible and leg in live_apy:
                apy = float(live_apy[leg])
                source = "live"
            else:
                apy = GROSS_APY_ASSUMPTIONS[leg]
                source = "placeholder"

            legs[leg] = {
                "weight": weight,
                "usd": round(usd, 4),
                "apy_pct": apy,
                "apy_source": source,
                "strict_eligible": eligible,
            }
            blended += weight * apy

        return {
            "strategy_id": STRATEGY_ID,
            "strategy_name": STRATEGY_NAME,
            "research_only": RESEARCH_ONLY,
            "total_capital": capital,
            "legs": legs,
            "blended_gross_apy": round(blended, 4),
            "weights_sum": round(weights_sum, 10),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # APY estimates
    # ──────────────────────────────────────────────────────────────────────────

    def gross_blended_apy(self) -> float:
        """
        Return the gross blended APY (%) from the placeholder assumptions.

        Calculation:
          0.60 * 40.0 + 0.10 * 18.0 + 0.14 * 20.0 + 0.16 * 4.0
          = 24.0 + 1.8 + 2.8 + 0.64
          = 29.24%

        Returns
        -------
        float
            Gross blended APY in percent.
        """
        total = sum(ALLOCATION[leg] * GROSS_APY_ASSUMPTIONS[leg] for leg in ALLOCATION)
        return round(total, 4)

    def net_apy_estimate(self, volatility_regime: str = "sideways") -> float:
        """
        Return a net APY estimate (%) for the given volatility regime.

        Net estimates account for approximate IL drag, execution costs,
        and vault return sensitivity. They are RESEARCH estimates only.

        Parameters
        ----------
        volatility_regime : str
            One of: "sideways", "trending", "crash", "bull".
            Unknown regimes map to the "trending" (pessimistic) estimate.

        Returns
        -------
        float
            Net APY estimate in percent.
        """
        return NET_APY_BY_REGIME.get(volatility_regime, NET_APY_BY_REGIME["trending"])

    def il_drag_estimate(self, btc_move_pct: float) -> float:
        """
        Estimate the impermanent loss drag (%) on the BTC/USD concentrated LP leg.

        Uses a simplified quadratic approximation with a concentration amplifier.
        The IL is expressed as a percentage of the full portfolio return that
        is lost due to IL on the btc_usd_conc_liq leg.

        IL_drag (portfolio %) = weight_btc * IL_on_leg (%)
        IL_on_leg (%) ≈ 0.5 * (|btc_move_pct| / 100)^2 * amplifier * 100

        At btc_move_pct = 0: returns 0.0 (no IL when price unchanged).
        At btc_move_pct = 20: meaningful IL drag.

        Parameters
        ----------
        btc_move_pct : float
            BTC price move in percent (e.g., 20 for +20% or -20%).

        Returns
        -------
        float
            IL drag as percentage points on portfolio return (≥ 0).
        """
        if btc_move_pct == 0.0:
            return 0.0
        move_fraction = abs(btc_move_pct) / 100.0
        il_on_leg_pct = 0.5 * (move_fraction ** 2) * _IL_AMPLIFIER * 100.0
        btc_weight = ALLOCATION["btc_usd_conc_liq"]
        return round(btc_weight * il_on_leg_pct, 4)

    # ──────────────────────────────────────────────────────────────────────────
    # Classification helpers
    # ──────────────────────────────────────────────────────────────────────────

    def strict_eligible_fraction(self) -> float:
        """
        Return the fraction of capital that is eligible for strict live data.

        Only stablecoin_deposit (16%) is strict-eligible. All other legs
        are research/placeholder only.

        Returns
        -------
        float
            Fraction in [0, 1]. Currently 0.16.
        """
        return sum(w for leg, w in ALLOCATION.items() if STRICT_ELIGIBLE[leg])

    def risk_classification(self) -> str:
        """
        Return the risk classification string.

        RS-002 is classified as AGGRESSIVE due to:
        - 60% concentrated LP with significant IL risk
        - 14% GMX/Hyperliquid vault (market-regime dependent)
        - High gross APY target (29.24%) with wide net outcome range

        Returns
        -------
        str
            Always "AGGRESSIVE" for RS-002.
        """
        return "AGGRESSIVE"

    # ──────────────────────────────────────────────────────────────────────────
    # Introspection / reporting
    # ──────────────────────────────────────────────────────────────────────────

    def summary(self) -> Dict:
        """Return a summary dict for logging/reporting."""
        return {
            "strategy_id": STRATEGY_ID,
            "strategy_name": STRATEGY_NAME,
            "research_only": RESEARCH_ONLY,
            "risk_classification": self.risk_classification(),
            "capital": self._capital,
            "gross_blended_apy": self.gross_blended_apy(),
            "net_apy_sideways_range": list(NET_APY_ESTIMATE_RANGE),
            "net_apy_by_regime": dict(NET_APY_BY_REGIME),
            "strict_eligible_fraction": self.strict_eligible_fraction(),
            "allocation": dict(ALLOCATION),
            "gross_apy_assumptions": dict(GROSS_APY_ASSUMPTIONS),
            "created_at": self._created_at,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"CashflowResearchStrategy("
            f"capital={self._capital:,.0f}, "
            f"gross_apy={self.gross_blended_apy():.2f}%, "
            f"research_only={RESEARCH_ONLY})"
        )
