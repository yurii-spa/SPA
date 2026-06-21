"""
spa_core/strategies/s54_daily_yield_maximizer.py — S54 Daily Yield Maximizer

S54: Daily Yield Maximizer
==========================
An aggressive daily-momentum rotation. Each day it re-allocates based purely on
*yesterday's* realized APY (a lagged, leak-free signal): 80% of capital chases
the top-3 yesterday performers, 20% stays in an equal-weight baseline for ballast
and to keep some breadth.

Algorithm:
  1. Rank protocols by yesterday's APY (descending).
  2. CHASE_WEIGHT (80%) split equally across the top-N (3) performers.
  3. BASE_WEIGHT (20%) split equally across the whole active universe.
  4. Sum the two layers per protocol, renormalize to 1.0.

Kill switch — T1 floor protection:
  If all of the top-3 are T2 protocols, an unconstrained 80% chase would blow the
  T1 floor and the T2 cap. In that case the chase layer is capped at
  CHASE_WEIGHT_CAPPED (60%) and the freed 20% reverts to the baseline, pulling
  T1 anchors back up. (data note: the allocator/RiskPolicy gate is still the hard
  backstop; this is the strategy self-limiting before it gets there.)

Lagged signal = uses yesterday's rates, so there is no look-ahead; the realized
fill always trails the signal by a day. Aggressive ⇒ higher expected APY ~4.8%.

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy is never overridden

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S54"
STRATEGY_NAME = "Daily Yield Maximizer"
TIER          = "T2"
DESCRIPTION   = (
    "Daily Yield Maximizer: aggressive daily rotation on YESTERDAY's APY (lagged, "
    "leak-free). 80% chases the top-3 yesterday performers, 20% equal-weight "
    "baseline. Kill switch: if all top-3 are T2, chase is capped at 60% to "
    "preserve the T1 floor. ~4.8% APY. Advisory only."
)

# ─── Universe & tiers ─────────────────────────────────────────────────────────

PROTOCOLS = ["aave_v3", "compound_v3", "morpho_steakhouse", "morpho_blue", "yearn_v3"]

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":           "T1",
    "compound_v3":       "T1",
    "morpho_steakhouse": "T1",
    "morpho_blue":       "T2",
    "yearn_v3":          "T2",
}

FALLBACK_APY: Dict[str, float] = {
    "aave_v3":           3.5,
    "compound_v3":       4.8,
    "morpho_steakhouse": 6.5,
    "morpho_blue":       7.0,
    "yearn_v3":          6.0,
}

# ─── Tuning ───────────────────────────────────────────────────────────────────

TOP_N:               int   = 3
CHASE_WEIGHT:        float = 0.80   # normal: 80% to the top-3
BASE_WEIGHT:         float = 0.20   # normal: 20% equal-weight baseline
CHASE_WEIGHT_CAPPED: float = 0.60   # kill switch: 60% chase when top-3 all T2

TARGET_APY_MIN:   float = 4.0
TARGET_APY_MAX:   float = 6.0
RISK_SCORE:       float = 0.45
MAX_DRAWDOWN_PCT: float = 6.0


def rank_by_yesterday(
    yesterday_apy: Dict[str, float],
    active: List[str],
) -> List[str]:
    """Active protocols ranked by yesterday's APY desc; ties broken by name for
    determinism. Protocols missing from yesterday_apy sort last (treated as 0)."""
    return sorted(
        active,
        key=lambda p: (-float(yesterday_apy.get(p, 0.0)), p),
    )


class S54DailyYieldMaximizer:
    """S54 — Daily Yield Maximizer (80/20 chase of yesterday's top-3)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def get_top_performers(
        self,
        yesterday_apy: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> List[str]:
        yesterday_apy = yesterday_apy or {}
        suspended = suspended or set()
        active = [p for p in PROTOCOLS if p not in suspended]
        ranked = rank_by_yesterday(yesterday_apy, active)
        return ranked[:TOP_N]

    def kill_switch_active(
        self,
        yesterday_apy: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> bool:
        """True when every top-3 performer is T2 → chase must be capped at 60%."""
        top = self.get_top_performers(yesterday_apy, suspended)
        if not top:
            return False
        return all(PROTOCOL_TIERS.get(p) == "T2" for p in top)

    def get_allocation(
        self,
        yesterday_apy: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """80/20 chase weights (sum 1.0); chase capped to 60% under kill switch."""
        yesterday_apy = yesterday_apy or {}
        suspended = suspended or set()
        active = [p for p in PROTOCOLS if p not in suspended]
        if not active:
            return {}

        top = self.get_top_performers(yesterday_apy, suspended)
        if not top:
            base = 1.0 / len(active)
            return {p: round(base, 8) for p in active}

        chase = CHASE_WEIGHT
        if self.kill_switch_active(yesterday_apy, suspended):
            chase = CHASE_WEIGHT_CAPPED
        base_layer = 1.0 - chase

        weights: Dict[str, float] = {p: 0.0 for p in active}
        # Chase layer: equal split across the top performers.
        per_top = chase / len(top)
        for p in top:
            weights[p] += per_top
        # Baseline layer: equal split across the whole active universe.
        per_base = base_layer / len(active)
        for p in active:
            weights[p] += per_base

        total = sum(weights.values())
        if total <= 0.0:
            base = 1.0 / len(active)
            return {p: round(base, 8) for p in active}
        return {p: round(w / total, 8) for p, w in weights.items()}

    def get_expected_apy(
        self,
        yesterday_apy: Optional[Dict[str, float]] = None,
        apy_map: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> float:
        """Expected APY uses today's apy_map (or fallback) under yesterday-driven
        weights — the fill earns today's rate on a yesterday-chosen allocation."""
        apy_map = apy_map or {}
        alloc = self.get_allocation(yesterday_apy, suspended)
        if not alloc:
            return 0.0
        weighted = 0.0
        for p, w in alloc.items():
            apy = apy_map.get(p, FALLBACK_APY.get(p, 0.0))
            weighted += w * apy
        return round(weighted, 4)

    def get_risk_summary(
        self,
        yesterday_apy: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        alloc = self.get_allocation(yesterday_apy, suspended)
        t1 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T2")
        return {
            "strategy_id":        STRATEGY_ID,
            "risk_score":         RISK_SCORE,
            "t1_weight_pct":      round(t1 * 100.0, 2),
            "t2_weight_pct":      round(t2 * 100.0, 2),
            "top_performers":     self.get_top_performers(yesterday_apy, suspended),
            "kill_switch_active": self.kill_switch_active(yesterday_apy, suspended),
            "max_drawdown_pct":   MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        yesterday_apy: Optional[Dict[str, float]] = None,
        apy_map: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "allocation":                {},
                "top_performers":            self.get_top_performers(yesterday_apy, suspended),
                "kill_switch_active":        self.kill_switch_active(yesterday_apy, suspended),
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        alloc = self.get_allocation(yesterday_apy, suspended)
        apy = self.get_expected_apy(yesterday_apy, apy_map, suspended)
        positions = {p: round(capital_usd * w, 6) for p, w in alloc.items()}
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "allocation":                positions,
            "top_performers":            self.get_top_performers(yesterday_apy, suspended),
            "kill_switch_active":        self.kill_switch_active(yesterday_apy, suspended),
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "status":                    "ok",
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> Dict:
        return {
            "strategy_id":         STRATEGY_ID,
            "strategy_name":       STRATEGY_NAME,
            "tier":                TIER,
            "description":         DESCRIPTION,
            "protocols":           list(PROTOCOLS),
            "protocol_tiers":      dict(PROTOCOL_TIERS),
            "fallback_apy":        dict(FALLBACK_APY),
            "top_n":               TOP_N,
            "chase_weight":        CHASE_WEIGHT,
            "base_weight":         BASE_WEIGHT,
            "chase_weight_capped": CHASE_WEIGHT_CAPPED,
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
            type="lending",
            risk_tier=TIER,
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s54_daily_yield_maximizer",
            handler_class="S54DailyYieldMaximizer",
            tags=["momentum", "daily", "rotation", "lagged", "aggressive",
                  "top3", "kill_switch", "t2", "s54"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S54DailyYieldMaximizer auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S54DailyYieldMaximizer()
    yday = {"morpho_blue": 7.2, "yearn_v3": 6.5, "morpho_steakhouse": 6.4,
            "compound_v3": 4.8, "aave_v3": 3.5}
    print(json.dumps(strat.simulate(100_000.0, yesterday_apy=yday), indent=2))
