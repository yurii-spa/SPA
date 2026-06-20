"""
spa_core/strategies/s32_market_neutral.py — S32 Market Neutral

S32: Market Neutral
===================
A true market-neutral allocator: it holds the *same* risk posture regardless of
the detected regime — 50% T1, 45% T2, 5% cash — and simply rebalances back to
those weights once a week. Where S31 (Bear Market Hedge) actively de-risks in a
downturn, S32 takes no regime view at all; its low drawdown comes purely from
diversification and disciplined weekly rebalancing.

Fixed targets:
  T1 sleeve   50%  — equal-weight Aave + Compound + Sky sUSDS (16.667% each)
  T2 sleeve   45%  — top 3 T2 pools by current APY, equal-weight (15% each)
  cash         5%

Weighted target APY (defaults): ~5.5% (range 5–6%), drawdown target < 1%.

Rebalance cadence:
  Weekly (REBALANCE_INTERVAL_DAYS = 7). Between rebalances the book drifts with
  yield accrual; `should_rebalance(day)` is True every 7th day.

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
The deterministic RiskPolicy gate retains final authority; `approved=False` is
never overridden.

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S32"
STRATEGY_NAME = "Market Neutral"
TIER          = "T2"
DESCRIPTION   = (
    "Market Neutral: fixed 50% T1 / 45% T2 / 5% cash regardless of regime, "
    "rebalanced weekly. T1 = equal-weight Aave+Compound+Sky; T2 = top 3 pools "
    "by APY, equal-weight. Target 5-6% APY with <1% drawdown. No market timing."
)

# ─── Sleeve weights ───────────────────────────────────────────────────────────

T1_SLEEVE_WEIGHT:   float = 0.50
T2_SLEEVE_WEIGHT:   float = 0.45
CASH_WEIGHT:        float = 0.05

# T1 sleeve: exactly these three, always equal-weight.
T1_PROTOCOLS: List[str] = ["aave_v3", "compound_v3", "sky_susds"]

# T2 candidate universe — the top 3 by current APY are selected each rebalance.
T2_CANDIDATES: List[str] = [
    "fluid",
    "yearn_v3",
    "morpho_steakhouse",
    "euler_v2",
    "morpho_blue",
]

# How many T2 pools to hold (equal-weight within the T2 sleeve).
T2_PICK_COUNT: int = 3

# Conservative default annual APYs (%) — fallbacks when the live feed is down.
APY_DEFAULTS: Dict[str, float] = {
    # T1
    "aave_v3":           4.2,
    "compound_v3":       4.5,
    "sky_susds":         6.0,
    # T2 candidates
    "fluid":             7.0,
    "yearn_v3":          6.8,
    "morpho_steakhouse": 6.5,
    "euler_v2":          6.4,
    "morpho_blue":       6.2,
    "cash":              0.0,
}

TIER_OF: Dict[str, str] = {
    "aave_v3":           "T1",
    "compound_v3":       "T1",
    "sky_susds":         "T1",
    "fluid":             "T2",
    "yearn_v3":          "T2",
    "morpho_steakhouse": "T2",
    "euler_v2":          "T2",
    "morpho_blue":       "T2",
    "cash":              "T1",
}

# ─── Cadence / targets / risk ─────────────────────────────────────────────────

REBALANCE_INTERVAL_DAYS: int = 7

TARGET_APY_PCT:   float = 5.5
TARGET_APY_MIN:   float = 5.0
TARGET_APY_MAX:   float = 6.0
RISK_SCORE:       float = 0.30
MAX_DRAWDOWN_PCT: float = 1.0
_HISTORY_MAX:     int   = 365

# Tolerance for "sleeve weights sum to 1.0" sanity checks.
_EPS: float = 1e-9


def _apy_of(protocol: str, apy_map: Optional[Dict[str, float]]) -> float:
    if apy_map and protocol in apy_map:
        v = apy_map[protocol]
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return APY_DEFAULTS.get(protocol, 0.0)


class MarketNeutralStrategy:
    """S32 — Market Neutral (fixed 50/45/5, weekly rebalance).

    Regime-agnostic by construction. Stdlib only, advisory/read-only — never
    mutates allocator/risk/execution state.
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TIER           = TIER
    TARGET_APY_PCT = TARGET_APY_PCT
    RISK_SCORE     = RISK_SCORE

    def __init__(self) -> None:
        self._simulate_history: List[Dict] = []
        self._last_rebalance_day: int = 0

    # ── T2 selection ─────────────────────────────────────────────────────────

    def select_t2(self, apy_map: Optional[Dict[str, float]] = None) -> List[str]:
        """Pick the top T2_PICK_COUNT candidates by APY (ties broken by name).

        Deterministic: sorts by (−apy, name) so the result is stable when the
        live feed is unavailable and all candidates fall back to defaults.
        """
        ranked: List[Tuple[float, str]] = sorted(
            ((_apy_of(p, apy_map), p) for p in T2_CANDIDATES),
            key=lambda t: (-t[0], t[1]),
        )
        return [p for _, p in ranked[:T2_PICK_COUNT]]

    # ── Target weights ───────────────────────────────────────────────────────

    def target_weights(self, apy_map: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """Fixed 50/45/5 weight map with equal weights inside each sleeve."""
        weights: Dict[str, float] = {}

        t1_each = T1_SLEEVE_WEIGHT / len(T1_PROTOCOLS)
        for p in T1_PROTOCOLS:
            weights[p] = weights.get(p, 0.0) + t1_each

        t2 = self.select_t2(apy_map)
        if t2:
            t2_each = T2_SLEEVE_WEIGHT / len(t2)
            for p in t2:
                weights[p] = weights.get(p, 0.0) + t2_each

        weights["cash"] = weights.get("cash", 0.0) + CASH_WEIGHT
        return weights

    def get_allocation(self, capital_usd: float,
                       apy_map: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """Target USD allocation at the fixed 50/45/5 weights."""
        weights = self.target_weights(apy_map)
        if capital_usd <= 0.0:
            return {p: 0.0 for p in weights}
        return {p: round(capital_usd * w, 6) for p, w in weights.items()}

    # ── Rebalance cadence ────────────────────────────────────────────────────

    def should_rebalance(self, day: int) -> bool:
        """True on a weekly boundary (day 0, 7, 14, …)."""
        return day >= 0 and day % REBALANCE_INTERVAL_DAYS == 0

    # ── Expectations ─────────────────────────────────────────────────────────

    def get_expected_apy(self, apy_map: Optional[Dict[str, float]] = None) -> float:
        weights = self.target_weights(apy_map)
        return round(sum(w * _apy_of(p, apy_map) for p, w in weights.items()), 4)

    # ── Risk / health ────────────────────────────────────────────────────────

    def get_risk_summary(self, apy_map: Optional[Dict[str, float]] = None) -> Dict:
        weights = self.target_weights(apy_map)
        t1 = sum(w for p, w in weights.items() if TIER_OF.get(p) == "T1")
        t2 = sum(w for p, w in weights.items() if TIER_OF.get(p) == "T2")
        return {
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "cash_pct":         round(weights.get("cash", 0.0) * 100.0, 2),
            "market_neutral":   True,
            "rebalance_days":   REBALANCE_INTERVAL_DAYS,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "risk_note": (
                f"S32 Market Neutral: fixed T1={t1*100:.0f}% / T2={t2*100:.0f}% / "
                f"cash={weights.get('cash', 0.0)*100:.0f}%, weekly rebalance, no timing."
            ),
        }

    def get_health(self, apy_map: Optional[Dict[str, float]] = None) -> Dict:
        weights = self.target_weights(apy_map)
        t1 = sum(w for p, w in weights.items() if TIER_OF.get(p) == "T1")
        t2 = sum(w for p, w in weights.items() if TIER_OF.get(p) == "T2")
        cash = weights.get("cash", 0.0)
        balanced = (abs(t1 - T1_SLEEVE_WEIGHT) < 1e-6
                    and abs(t2 - T2_SLEEVE_WEIGHT) < 1e-6
                    and abs(cash - CASH_WEIGHT) < 1e-6)
        return {
            "strategy_id":     STRATEGY_ID,
            "name":            STRATEGY_NAME,
            "t1_protocols":    list(T1_PROTOCOLS),
            "t2_selected":     self.select_t2(apy_map),
            "weights_balanced": balanced,
            "expected_apy":    self.get_expected_apy(apy_map),
            "target_apy":      TARGET_APY_PCT,
            "overall_status":  "ok" if balanced else "degraded",
        }

    # ── Simulation ───────────────────────────────────────────────────────────

    def simulate(self, capital_usd: float, day: int = 0,
                 apy_map: Optional[Dict[str, float]] = None) -> Dict:
        """Simulate one day. Rebalances to target on weekly boundaries."""
        rebalanced = self.should_rebalance(day)
        if rebalanced:
            self._last_rebalance_day = day

        allocation = self.get_allocation(capital_usd, apy_map)
        if capital_usd <= 0.0:
            return {
                "total_capital":             capital_usd,
                "day":                       day,
                "allocation":                {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "rebalanced":                rebalanced,
                "status":                    "no_capital",
                "risk_summary":              self.get_risk_summary(apy_map),
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }

        positions: Dict[str, Dict] = {}
        total_yield = 0.0
        for p, amount in allocation.items():
            apy = _apy_of(p, apy_map)
            annual = amount * (apy / 100.0)
            total_yield += annual
            positions[p] = {
                "amount_usd":       amount,
                "apy_pct":          apy,
                "tier":             TIER_OF.get(p, "T2"),
                "annual_yield_usd": round(annual, 4),
            }

        result = {
            "total_capital":             capital_usd,
            "day":                       day,
            "allocation":                allocation,
            "positions":                 positions,
            "expected_annual_yield_usd": round(total_yield, 4),
            "expected_apy_pct":          self.get_expected_apy(apy_map),
            "daily_yield_usd":           round(total_yield / 365.0, 6),
            "rebalanced":                rebalanced,
            "last_rebalance_day":        self._last_rebalance_day,
            "status":                    "ok",
            "risk_summary":              self.get_risk_summary(apy_map),
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }
        self._simulate_history.append(result)
        if len(self._simulate_history) > _HISTORY_MAX:
            self._simulate_history = self._simulate_history[-_HISTORY_MAX:]
        return result

    def to_dict(self) -> Dict:
        return {
            "strategy_id":        STRATEGY_ID,
            "strategy_name":      STRATEGY_NAME,
            "tier":               TIER,
            "description":        DESCRIPTION,
            "t1_protocols":       list(T1_PROTOCOLS),
            "t2_candidates":      list(T2_CANDIDATES),
            "t2_pick_count":      T2_PICK_COUNT,
            "sleeve_weights": {
                "t1":   T1_SLEEVE_WEIGHT,
                "t2":   T2_SLEEVE_WEIGHT,
                "cash": CASH_WEIGHT,
            },
            "apy_defaults":         dict(APY_DEFAULTS),
            "tier_of":              dict(TIER_OF),
            "rebalance_interval_days": REBALANCE_INTERVAL_DAYS,
            "target_apy_pct":       TARGET_APY_PCT,
            "target_apy_min":       TARGET_APY_MIN,
            "target_apy_max":       TARGET_APY_MAX,
            "risk_score":           RISK_SCORE,
            "max_drawdown_pct":     MAX_DRAWDOWN_PCT,
            "expected_apy":         self.get_expected_apy(),
            "t2_selected":          self.select_t2(),
            "simulate_history_len": len(self._simulate_history),
            "timestamp":            datetime.now(timezone.utc).isoformat(),
        }


def _register() -> None:
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
            description=DESCRIPTION,
            module="spa_core.strategies.s32_market_neutral",
            handler_class="MarketNeutralStrategy",
            tags=["market_neutral", "diversified", "weekly_rebalance",
                  "aave_v3", "compound_v3", "sky_susds", "t1", "t2", "s32"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "MarketNeutralStrategy auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    s = MarketNeutralStrategy()
    print(json.dumps(s.simulate(100_000.0, day=0), indent=2))
