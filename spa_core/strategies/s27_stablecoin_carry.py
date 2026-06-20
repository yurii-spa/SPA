"""
spa_core/strategies/s27_stablecoin_carry.py — S27 Stablecoin Carry

S27: Stablecoin Carry
=====================
Cross-stablecoin / cross-protocol carry strategy. Stablecoin lending rates for
USDC, USDT and DAI drift apart across Aave and Compound. S27 always parks the
full book in the single highest-yielding T1 venue, and only *switches* venues
when the rate spread clears a hysteresis band — avoiding churn (and rebalance
cost) when the edge is too thin to be worth moving.

Logic:
  - Rank all eligible T1 stablecoin venues by live supply APY.
  - Allocate 100% to the top venue.
  - Switch away from the current venue only when
        best_apy - current_apy > SWITCH_THRESHOLD_PCT (0.5%).
    Otherwise stay put (rebalance weekly cadence in the live cycle).

Target: always capture the top stablecoin rate (net of switch friction).

Venues (all T1 blue-chip stablecoin lending):
  aave_usdc, compound_usdc, aave_usdt, compound_usdt, sky_dai

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy is never overridden
  - all venues are T1 single-asset lending (no IL, no leverage)

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Set

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S27"
STRATEGY_NAME = "Stablecoin Carry"
TIER          = "T1"
DESCRIPTION   = (
    "Stablecoin Carry: parks 100% in the top-yielding T1 stablecoin venue "
    "(USDC/USDT/DAI on Aave/Compound/Sky), switching only when the rate spread "
    "exceeds 0.5% (hysteresis avoids churn). Captures the best stablecoin rate."
)

# ─── Venues (all T1) ──────────────────────────────────────────────────────────

VENUES = ["aave_usdc", "compound_usdc", "aave_usdt", "compound_usdt", "sky_dai"]

PROTOCOL_TIERS: Dict[str, str] = {v: "T1" for v in VENUES}

FALLBACK_APY: Dict[str, float] = {
    "aave_usdc":     4.2,
    "compound_usdc": 4.8,
    "aave_usdt":     4.5,
    "compound_usdt": 4.6,
    "sky_dai":       5.0,
}

# ─── Switch hysteresis ────────────────────────────────────────────────────────

SWITCH_THRESHOLD_PCT: float = 0.5   # only switch venues if edge > 0.5%

TARGET_APY_MIN:   float = 4.0
TARGET_APY_MAX:   float = 7.0
RISK_SCORE:       float = 0.12
MAX_DRAWDOWN_PCT: float = 2.0


class S27StablecoinCarry:
    """S27 — Stablecoin Carry (top-rate T1 venue with switch hysteresis)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def _eligible_rates(
        self,
        rates: Optional[Dict[str, float]],
        suspended: Optional[Set[str]],
    ) -> Dict[str, float]:
        """Resolve live rates over non-suspended venues, filling defaults."""
        suspended = suspended or set()
        rates = rates or {}
        out: Dict[str, float] = {}
        for v in VENUES:
            if v in suspended:
                continue
            out[v] = float(rates.get(v, FALLBACK_APY.get(v, 0.0)))
        return out

    def best_venue(
        self,
        rates: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Optional[str]:
        """Return the highest-APY eligible venue (None if none eligible)."""
        eligible = self._eligible_rates(rates, suspended)
        if not eligible:
            return None
        return max(eligible.items(), key=lambda kv: kv[1])[0]

    def should_switch(
        self,
        current_venue: Optional[str],
        rates: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> bool:
        """True if we should rotate out of `current_venue`.

        Always switch if the current venue is unset, suspended, or no longer
        eligible. Otherwise switch only when the best venue beats current by
        more than SWITCH_THRESHOLD_PCT.
        """
        eligible = self._eligible_rates(rates, suspended)
        if not eligible:
            return False
        if current_venue is None or current_venue not in eligible:
            return True
        best = self.best_venue(rates, suspended)
        if best is None or best == current_venue:
            return False
        return (eligible[best] - eligible[current_venue]) > SWITCH_THRESHOLD_PCT

    def get_allocation(
        self,
        rates: Optional[Dict[str, float]] = None,
        current_venue: Optional[str] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """Target weights (sum 1.0): 100% to the chosen venue.

        Holds `current_venue` if switching is not yet justified; otherwise
        rotates to the best eligible venue.
        """
        eligible = self._eligible_rates(rates, suspended)
        if not eligible:
            return {}
        if current_venue in eligible and not self.should_switch(
            current_venue, rates, suspended
        ):
            chosen = current_venue
        else:
            chosen = self.best_venue(rates, suspended)
        return {chosen: 1.0}

    def get_expected_apy(
        self,
        rates: Optional[Dict[str, float]] = None,
        current_venue: Optional[str] = None,
        suspended: Optional[Set[str]] = None,
    ) -> float:
        """APY (%) of the chosen venue."""
        eligible = self._eligible_rates(rates, suspended)
        alloc = self.get_allocation(rates, current_venue, suspended)
        if not alloc:
            return 0.0
        venue = next(iter(alloc))
        return round(eligible.get(venue, 0.0), 4)

    def get_risk_summary(
        self,
        rates: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        alloc = self.get_allocation(rates, None, suspended)
        t1 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T1")
        return {
            "strategy_id":     STRATEGY_ID,
            "risk_score":      RISK_SCORE,
            "t1_weight_pct":   round(t1 * 100.0, 2),
            "switch_threshold_pct": SWITCH_THRESHOLD_PCT,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        rates: Optional[Dict[str, float]] = None,
        current_venue: Optional[str] = None,
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
        alloc = self.get_allocation(rates, current_venue, suspended)
        apy = self.get_expected_apy(rates, current_venue, suspended)
        positions = {p: round(capital_usd * w, 6) for p, w in alloc.items()}
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "allocation":                positions,
            "chosen_venue":              next(iter(alloc)) if alloc else None,
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "status":                    "ok" if alloc else "no_venue",
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> Dict:
        return {
            "strategy_id":          STRATEGY_ID,
            "strategy_name":        STRATEGY_NAME,
            "tier":                 TIER,
            "description":          DESCRIPTION,
            "venues":               list(VENUES),
            "protocol_tiers":       dict(PROTOCOL_TIERS),
            "fallback_apy":         dict(FALLBACK_APY),
            "switch_threshold_pct": SWITCH_THRESHOLD_PCT,
            "target_apy_min":       TARGET_APY_MIN,
            "target_apy_max":       TARGET_APY_MAX,
            "risk_score":           RISK_SCORE,
            "max_drawdown_pct":     MAX_DRAWDOWN_PCT,
            "timestamp":            datetime.now(timezone.utc).isoformat(),
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
            module="spa_core.strategies.s27_stablecoin_carry",
            handler_class="S27StablecoinCarry",
            tags=["exotic", "carry", "stablecoin", "rate_arbitrage", "aave",
                  "compound", "sky", "t1", "s27"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S27StablecoinCarry auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S27StablecoinCarry()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
