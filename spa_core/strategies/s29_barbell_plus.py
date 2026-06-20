"""
spa_core/strategies/s29_barbell_plus.py — S29 Barbell Plus

S29: Barbell Plus
=================
A barbell: 70% ultra-conservative T1 (only the largest, most battle-tested
protocols, TVL > $500M) paired with a 30% high-octane T2 sleeve that rotates
monthly into whatever T2 venue offers the best risk-adjusted APY. The heavy safe
anchor caps drawdown; the small aggressive sleeve lifts blended yield.

Logic:
  - SAFE LEG (70%): split equally across eligible T1 protocols with TVL > $500M.
  - RISK LEG (30%): 100% of the sleeve to the single T2 candidate with the best
    risk-adjusted APY (apy / risk_score), rotated monthly.
  - Degenerate cases: no eligible T1 → safe leg falls to cash; no eligible T2 →
    risk leg folds back into the safe leg.

Target: very low max drawdown with a competitive blended APY.

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy is never overridden

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Set

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S29"
STRATEGY_NAME = "Barbell Plus"
TIER          = "T2"
DESCRIPTION   = (
    "Barbell Plus: 70% ultra-conservative T1 (only TVL > $500M protocols) + "
    "30% best risk-adjusted T2 sleeve rotated monthly. Very low max drawdown "
    "with competitive blended APY. Advisory only."
)

# ─── Barbell legs ─────────────────────────────────────────────────────────────

SAFE_WEIGHT: float = 0.70
RISK_WEIGHT: float = 0.30
MIN_T1_TVL_USD: float = 500_000_000.0   # $500M floor for the safe leg

CASH_KEY = "cash"

# Defaults used when no live data is supplied (TVL in USD, APY in %).
DEFAULT_T1_POOLS: Dict[str, float] = {        # protocol → TVL
    "aave_v3":           8_000_000_000.0,
    "compound_v3":       2_000_000_000.0,
    "morpho_steakhouse": 600_000_000.0,
}
DEFAULT_T2_CANDIDATES: Dict[str, float] = {   # protocol → APY %
    "morpho_blue": 7.5,
    "yearn_v3":    6.5,
    "euler_v2":    8.0,
    "maple":       9.5,
}

# Per-candidate risk scores for the risk-adjusted ranking of the T2 sleeve.
T2_RISK_SCORES: Dict[str, float] = {
    "morpho_blue": 0.40,
    "yearn_v3":    0.42,
    "euler_v2":    0.48,
    "maple":       0.60,
}

FALLBACK_T1_APY: Dict[str, float] = {
    "aave_v3":           4.0,
    "compound_v3":       4.8,
    "morpho_steakhouse": 6.5,
}

TARGET_APY_MIN:   float = 5.0
TARGET_APY_MAX:   float = 8.0
RISK_SCORE:       float = 0.30
MAX_DRAWDOWN_PCT: float = 3.0


class S29BarbellPlus:
    """S29 — Barbell Plus (70% T1 anchor + 30% rotating T2 sleeve)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def eligible_t1(
        self,
        t1_pools: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """T1 protocols with TVL > $500M, excluding suspended ones."""
        suspended = suspended or set()
        pools = t1_pools if t1_pools is not None else DEFAULT_T1_POOLS
        return {
            p: tvl for p, tvl in pools.items()
            if p not in suspended and tvl > MIN_T1_TVL_USD
        }

    def best_t2(
        self,
        t2_candidates: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Optional[str]:
        """Highest risk-adjusted-APY (apy / risk_score) eligible T2 candidate."""
        suspended = suspended or set()
        cands = t2_candidates if t2_candidates is not None else DEFAULT_T2_CANDIDATES
        eligible = {p: apy for p, apy in cands.items() if p not in suspended}
        if not eligible:
            return None

        def risk_adj(p: str) -> float:
            rs = T2_RISK_SCORES.get(p, 0.5)
            return eligible[p] / rs if rs > 0 else eligible[p]

        return max(eligible.keys(), key=risk_adj)

    def get_allocation(
        self,
        t1_pools: Optional[Dict[str, float]] = None,
        t2_candidates: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """Barbell weights (sum 1.0): 70% T1 anchor + 30% best T2 sleeve."""
        t1 = self.eligible_t1(t1_pools, suspended)
        t2_pick = self.best_t2(t2_candidates, suspended)

        alloc: Dict[str, float] = {}

        # Determine effective leg weights, folding a missing leg into the other.
        safe_w, risk_w = SAFE_WEIGHT, RISK_WEIGHT
        if not t1 and t2_pick is None:
            return {CASH_KEY: 1.0}
        if not t1:
            # No safe anchor → everything into the T2 sleeve.
            risk_w = SAFE_WEIGHT + RISK_WEIGHT
            safe_w = 0.0
        if t2_pick is None:
            # No risk sleeve → fold into the safe anchor.
            safe_w = SAFE_WEIGHT + RISK_WEIGHT
            risk_w = 0.0

        if safe_w > 0.0 and t1:
            per = safe_w / len(t1)
            for p in t1:
                alloc[p] = alloc.get(p, 0.0) + per
        if risk_w > 0.0 and t2_pick is not None:
            alloc[t2_pick] = alloc.get(t2_pick, 0.0) + risk_w

        return {p: round(w, 8) for p, w in alloc.items()}

    def get_expected_apy(
        self,
        t1_pools: Optional[Dict[str, float]] = None,
        t2_candidates: Optional[Dict[str, float]] = None,
        t1_apy: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> float:
        """Weighted blended APY (%)."""
        alloc = self.get_allocation(t1_pools, t2_candidates, suspended)
        if not alloc:
            return 0.0
        t1_apy = t1_apy or {}
        cands = t2_candidates if t2_candidates is not None else DEFAULT_T2_CANDIDATES
        weighted = 0.0
        for p, w in alloc.items():
            if p == CASH_KEY:
                apy = 0.0
            elif p in cands:
                apy = cands[p]
            else:
                apy = t1_apy.get(p, FALLBACK_T1_APY.get(p, 4.0))
            weighted += w * apy
        return round(weighted, 4)

    def get_risk_summary(
        self,
        t1_pools: Optional[Dict[str, float]] = None,
        t2_candidates: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        alloc = self.get_allocation(t1_pools, t2_candidates, suspended)
        cands = t2_candidates if t2_candidates is not None else DEFAULT_T2_CANDIDATES
        t1_w = sum(w for p, w in alloc.items()
                   if p != CASH_KEY and p not in cands)
        t2_w = sum(w for p, w in alloc.items() if p in cands)
        cash_w = alloc.get(CASH_KEY, 0.0)
        return {
            "strategy_id":      STRATEGY_ID,
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1_w * 100.0, 2),
            "t2_weight_pct":    round(t2_w * 100.0, 2),
            "cash_weight_pct":  round(cash_w * 100.0, 2),
            "min_t1_tvl_usd":   MIN_T1_TVL_USD,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        t1_pools: Optional[Dict[str, float]] = None,
        t2_candidates: Optional[Dict[str, float]] = None,
        t1_apy: Optional[Dict[str, float]] = None,
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
        alloc = self.get_allocation(t1_pools, t2_candidates, suspended)
        apy = self.get_expected_apy(t1_pools, t2_candidates, t1_apy, suspended)
        positions = {p: round(capital_usd * w, 6) for p, w in alloc.items()}
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "allocation":                positions,
            "t2_sleeve":                 self.best_t2(t2_candidates, suspended),
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "status":                    "ok",
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> Dict:
        return {
            "strategy_id":      STRATEGY_ID,
            "strategy_name":    STRATEGY_NAME,
            "tier":             TIER,
            "description":      DESCRIPTION,
            "safe_weight":      SAFE_WEIGHT,
            "risk_weight":      RISK_WEIGHT,
            "min_t1_tvl_usd":   MIN_T1_TVL_USD,
            "default_t1_pools": dict(DEFAULT_T1_POOLS),
            "default_t2_candidates": dict(DEFAULT_T2_CANDIDATES),
            "t2_risk_scores":   dict(T2_RISK_SCORES),
            "target_apy_min":   TARGET_APY_MIN,
            "target_apy_max":   TARGET_APY_MAX,
            "risk_score":       RISK_SCORE,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "timestamp":        datetime.now(timezone.utc).isoformat(),
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
            module="spa_core.strategies.s29_barbell_plus",
            handler_class="S29BarbellPlus",
            tags=["exotic", "barbell", "t1_anchor", "t2_sleeve", "risk_adjusted",
                  "low_drawdown", "t2", "s29"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S29BarbellPlus auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S29BarbellPlus()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
