"""
spa_core/strategies/s35_gmx_carry.py — S35 GMX Stablecoin Carry

S35: GMX Stablecoin Carry
=========================
GMX GLP (Arbitrum) is an index LP token that earns perpetual trading fees. Its
stablecoin component (USDC/USDT/DAI in the basket) produces a stablecoin-like
carry, but GLP also holds ETH/BTC — it is NOT a pure stablecoin position and
carries market exposure.

This strategy only allocates to GLP when the *estimated stablecoin-attributable
APY* of GLP clears a high bar (> 8%) — i.e. the trading-fee carry is rich enough
to justify the market exposure. Otherwise the book sits entirely in mainnet T1
lending (no GLP).

Active (GLP stablecoin APY > 8%):
  - gmx_glp_arbitrum 20%  (T2, trading-fee carry, ~7%+ APY)
  - aave_v3          50%  (T1 mainnet, ~3.5% APY)
  - compound_v3      25%  (T1 mainnet, ~4.8% APY)
  - cash              5%

Inactive (GLP carry too thin → 100% mainnet T1):
  - aave_v3          65%  (T1 mainnet)
  - compound_v3      30%  (T1 mainnet)
  - cash              5%

Note: the GLP gate compares an *estimated stablecoin APY*, not the headline GLP
APR. GLP's headline APR mixes fee income with basket price moves; only the
stablecoin-fee portion is comparable to lending carry. Callers pass
``glp_stable_apy`` (the estimated stablecoin-attributable yield).

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy is never overridden
  - GLP carries market exposure (basket) — RiskPolicy/allocator enforce T2 cap

ADR: ADR-019 (T2 total cap ≤ 50%), ADR-025 (Arbitrum Phase 2 expansion)

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Set

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S35"
STRATEGY_NAME = "GMX Stablecoin Carry"
TIER          = "T2"
DESCRIPTION   = (
    "GMX Stablecoin Carry: allocates 20% to GMX GLP Arbitrum only when its "
    "estimated stablecoin-attributable APY exceeds 8% (else 100% mainnet T1). "
    "Active book: 20% GLP, 50% Aave mainnet, 25% Compound, 5% cash."
)

CASH_KEY = "cash"

# Threshold on the GLP stablecoin-attributable APY for activation.
GLP_ACTIVATION_THRESHOLD_PCT: float = 8.0

PROTOCOL_TIERS: Dict[str, str] = {
    "gmx_glp_arbitrum": "T2",   # GLP — market-exposed LP, trading-fee carry
    "aave_v3":          "T1",   # Aave V3 mainnet
    "compound_v3":      "T1",   # Compound V3 mainnet
    CASH_KEY:           "T1",
}

# Allocation when GLP carry is rich enough (> threshold).
ACTIVE_ALLOCATION: Dict[str, float] = {
    "gmx_glp_arbitrum": 0.20,
    "aave_v3":          0.50,
    "compound_v3":      0.25,
    CASH_KEY:           0.05,
}

# Allocation when GLP carry is too thin → 100% mainnet T1.
INACTIVE_ALLOCATION: Dict[str, float] = {
    "aave_v3":     0.65,
    "compound_v3": 0.30,
    CASH_KEY:      0.05,
}

FALLBACK_APY: Dict[str, float] = {
    "gmx_glp_arbitrum": 7.0,
    "aave_v3":          3.5,
    "compound_v3":      4.8,
    CASH_KEY:           0.0,
}

TARGET_APY_MIN:   float = 3.5
TARGET_APY_MAX:   float = 9.0
RISK_SCORE:       float = 0.40
MAX_DRAWDOWN_PCT: float = 5.0


class S35GMXCarry:
    """S35 — GMX Stablecoin Carry with an 8% GLP activation gate."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def is_glp_active(self, glp_stable_apy: float) -> bool:
        """True when GLP's estimated stablecoin APY clears the activation bar."""
        return float(glp_stable_apy) > GLP_ACTIVATION_THRESHOLD_PCT

    def get_allocation(
        self,
        glp_stable_apy: float = 0.0,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """Target weights (sum 1.0).

        Uses the active (GLP-on) book when ``glp_stable_apy`` > 8% and GLP is
        not suspended, otherwise the inactive (100% mainnet T1) book. Any
        suspended protocol's weight is redistributed to the cash buffer so the
        weights still sum to 1.0.
        """
        suspended = suspended or set()
        active = self.is_glp_active(glp_stable_apy) and (
            "gmx_glp_arbitrum" not in suspended
        )
        base = ACTIVE_ALLOCATION if active else INACTIVE_ALLOCATION
        alloc: Dict[str, float] = {}
        spilled = 0.0
        for proto, w in base.items():
            if proto != CASH_KEY and proto in suspended:
                spilled += w
                continue
            alloc[proto] = alloc.get(proto, 0.0) + w
        if spilled > 0.0:
            alloc[CASH_KEY] = alloc.get(CASH_KEY, 0.0) + spilled
        return alloc

    def get_glp_weight(self, glp_stable_apy: float = 0.0) -> float:
        """GLP target weight under the current gate state (0.0 when inactive)."""
        return self.get_allocation(glp_stable_apy).get("gmx_glp_arbitrum", 0.0)

    def get_expected_apy(
        self,
        rates: Optional[Dict[str, float]] = None,
        glp_stable_apy: float = 0.0,
        suspended: Optional[Set[str]] = None,
    ) -> float:
        """Weighted APY (%) of the current allocation.

        When GLP is active, its contribution uses the live ``glp_stable_apy``
        (the gate value) rather than the static fallback, since that is the
        carry actually being captured.
        """
        rates = rates or {}
        alloc = self.get_allocation(glp_stable_apy, suspended)
        apy = 0.0
        for proto, w in alloc.items():
            if proto == "gmx_glp_arbitrum":
                rate = float(rates.get(proto, glp_stable_apy))
            else:
                rate = float(rates.get(proto, FALLBACK_APY.get(proto, 0.0)))
            apy += w * rate
        return round(apy, 4)

    def get_risk_summary(self, glp_stable_apy: float = 0.0) -> Dict:
        alloc = self.get_allocation(glp_stable_apy)
        t1 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T2")
        return {
            "strategy_id":       STRATEGY_ID,
            "risk_score":        RISK_SCORE,
            "glp_active":        self.is_glp_active(glp_stable_apy),
            "glp_weight_pct":    round(self.get_glp_weight(glp_stable_apy) * 100.0, 2),
            "t1_weight_pct":     round(t1 * 100.0, 2),
            "t2_weight_pct":     round(t2 * 100.0, 2),
            "activation_threshold_pct": GLP_ACTIVATION_THRESHOLD_PCT,
            "max_drawdown_pct":  MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        rates: Optional[Dict[str, float]] = None,
        glp_stable_apy: float = 0.0,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "allocation":                {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        alloc = self.get_allocation(glp_stable_apy, suspended)
        apy = self.get_expected_apy(rates, glp_stable_apy, suspended)
        positions = {p: round(capital_usd * w, 6) for p, w in alloc.items()}
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "allocation":                positions,
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "glp_active":                self.is_glp_active(glp_stable_apy),
            "status":                    "ok",
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> Dict:
        return {
            "strategy_id":         STRATEGY_ID,
            "strategy_name":       STRATEGY_NAME,
            "tier":                TIER,
            "description":         DESCRIPTION,
            "active_allocation":   dict(ACTIVE_ALLOCATION),
            "inactive_allocation": dict(INACTIVE_ALLOCATION),
            "protocol_tiers":      dict(PROTOCOL_TIERS),
            "fallback_apy":        dict(FALLBACK_APY),
            "activation_threshold_pct": GLP_ACTIVATION_THRESHOLD_PCT,
            "target_apy_min":      TARGET_APY_MIN,
            "target_apy_max":      TARGET_APY_MAX,
            "risk_score":          RISK_SCORE,
            "max_drawdown_pct":    MAX_DRAWDOWN_PCT,
            "timestamp":           datetime.now(timezone.utc).isoformat(),
        }


def _register() -> None:
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lp",
            risk_tier=TIER,
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s35_gmx_carry",
            handler_class="S35GMXCarry",
            tags=["arbitrum", "gmx", "glp", "carry", "trading_fees", "l2",
                  "conditional", "t1", "t2", "s35"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S35GMXCarry auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S35GMXCarry()
    print(json.dumps(strat.simulate(100_000.0, glp_stable_apy=10.0), indent=2))
    print(json.dumps(strat.simulate(100_000.0, glp_stable_apy=6.0), indent=2))
