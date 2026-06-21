"""
spa_core/strategies/s62_yield_ladder_v2.py — S62 Yield Ladder v2

S62: Yield Ladder v2 (gradual deployment)
=========================================
The enemy of new-capital deployment is FOMO: dumping a fresh tranche into the
highest-APY venue at a single moment exposes the whole book to that venue's
worst entry point. S62 ramps deployment over three weeks while never sitting
idle — capital earns Sky sUSDS income from day one and is gradually laddered
into the optimal diversified book.

Deployment schedule (by day index since first deploy)
-----------------------------------------------------
  Week 1   (day  0– 6)   100% Sky sUSDS              guaranteed income while waiting
  Week 2   (day  7–13)    50% Morpho / 50% Sky       half-step into yield
  Week 3+  (day 14+)      Aave 30 / Sky 30 /          optimal diversified book
                          Compound 20 / Morpho 20

By week 3 the book is fully diversified across T1 anchors and a T2 booster;
weeks 1–2 keep every dollar earning peg income so there is no cash drag and no
single-moment entry risk. This is the v2 of the original laddering idea: it
spreads *entry timing* rather than holding cash, and it anchors the wait in the
lowest-volatility income instrument (Sky).

Expected APY ramps ~4.20% (week 1) → ~4.5% (week 3 optimal book).

NOTE ON CAPS: Sky weights in weeks 1–2 exceed the RiskPolicy per-protocol T1 cap
(40%). S62 is advisory — it emits a target weight map per day; the deterministic
RiskPolicy gate trims to caps before any real allocation. `approved=False` is
never overridden.

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.

Date: 2026-06-21
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S62"
STRATEGY_NAME = "Yield Ladder v2"
TIER          = "T1"
DESCRIPTION   = (
    "Yield Ladder v2: gradual 3-week deployment for fresh capital with no FOMO "
    "entry and no cash drag. Week 1 = 100% Sky sUSDS (guaranteed income while "
    "waiting), week 2 = 50% Morpho / 50% Sky, week 3+ = optimal Aave30/Sky30/"
    "Compound20/Morpho20. Spreads entry timing while every dollar earns peg "
    "income from day one. Expected ~4.2%→~4.5% APY. Advisory-only, deterministic."
)

CASH_KEY = "cash"

# ─── Protocol universe ────────────────────────────────────────────────────────

PROTOCOLS = ["sky_susds", "morpho_blue", "aave_v3", "compound_v3"]

PROTOCOL_TIERS: Dict[str, str] = {
    "sky_susds":   "T1",
    "morpho_blue": "T2",
    "aave_v3":     "T1",
    "compound_v3": "T1",
    CASH_KEY:      "CASH",
}

REFERENCE_APY: Dict[str, float] = {
    "sky_susds":   4.20,
    "morpho_blue": 6.87,
    "aave_v3":     3.64,
    "compound_v3": 3.78,
}

# ─── Ladder phases ────────────────────────────────────────────────────────────

WEEK1_END_DAY = 7    # days 0..6   → phase "week1"
WEEK2_END_DAY = 14   # days 7..13  → phase "week2"; day 14+ → "week3"

PHASE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "week1": {"sky_susds": 1.00},
    "week2": {"morpho_blue": 0.50, "sky_susds": 0.50},
    "week3": {"aave_v3": 0.30, "sky_susds": 0.30, "compound_v3": 0.20, "morpho_blue": 0.20},
}

# ─── Targets / risk ───────────────────────────────────────────────────────────

TARGET_APY_MIN:   float = 4.0
TARGET_APY_MAX:   float = 5.0
RISK_SCORE:       float = 0.25
MAX_DRAWDOWN_PCT: float = 2.5


class S62YieldLadderV2:
    """S62 — Yield Ladder v2 (3-week FOMO-free deployment, Sky-anchored wait)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def _apy_of(self, p: str, apy_map: Dict[str, float]) -> float:
        v = apy_map.get(p)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
            return float(v)
        return REFERENCE_APY.get(p, 0.0)

    def phase_for_day(self, day_index: int) -> str:
        """Map a day index (≥0) to its ladder phase."""
        d = max(0, int(day_index))
        if d < WEEK1_END_DAY:
            return "week1"
        if d < WEEK2_END_DAY:
            return "week2"
        return "week3"

    def get_weights(self, day_index: int = 0) -> Dict[str, float]:
        """Target weight map for the given deployment day (sums to 1.0)."""
        phase = self.phase_for_day(day_index)
        return {p: round(w, 6) for p, w in PHASE_WEIGHTS[phase].items()}

    def get_allocation(self, capital_usd: float, day_index: int = 0) -> Dict[str, float]:
        if capital_usd <= 0.0:
            return {}
        return {p: round(capital_usd * w, 6)
                for p, w in self.get_weights(day_index).items()}

    def get_expected_apy(
        self, day_index: int = 0, apy_map: Optional[Dict[str, float]] = None
    ) -> float:
        apy_map = apy_map or {}
        weighted = 0.0
        for p, w in self.get_weights(day_index).items():
            if p == CASH_KEY:
                continue
            weighted += w * self._apy_of(p, apy_map)
        return round(weighted, 4)

    def get_risk_summary(self, day_index: int = 0) -> Dict:
        w = self.get_weights(day_index)
        t1 = sum(v for p, v in w.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(v for p, v in w.items() if PROTOCOL_TIERS.get(p) == "T2")
        return {
            "strategy_id":      STRATEGY_ID,
            "phase":            self.phase_for_day(day_index),
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        day_index: int = 0,
        apy_map: Optional[Dict[str, float]] = None,
    ) -> Dict:
        apy_map = apy_map or {}
        phase = self.phase_for_day(day_index)
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "day_index":                 max(0, int(day_index)),
                "phase":                     phase,
                "allocation":                {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        weights = self.get_weights(day_index)
        apy = self.get_expected_apy(day_index, apy_map)
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "day_index":                 max(0, int(day_index)),
            "phase":                     phase,
            "weights":                   weights,
            "allocation":                {p: round(capital_usd * w, 6) for p, w in weights.items()},
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "risk_summary":              self.get_risk_summary(day_index),
            "status":                    "ok",
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> Dict:
        return {
            "strategy_id":     STRATEGY_ID,
            "strategy_name":   STRATEGY_NAME,
            "tier":            TIER,
            "description":     DESCRIPTION,
            "protocols":       list(PROTOCOLS),
            "protocol_tiers":  {p: PROTOCOL_TIERS[p] for p in PROTOCOLS},
            "reference_apy":   dict(REFERENCE_APY),
            "phase_weights":   {k: dict(v) for k, v in PHASE_WEIGHTS.items()},
            "week1_end_day":   WEEK1_END_DAY,
            "week2_end_day":   WEEK2_END_DAY,
            "target_apy_min":  TARGET_APY_MIN,
            "target_apy_max":  TARGET_APY_MAX,
            "risk_score":      RISK_SCORE,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "timestamp":       datetime.now(timezone.utc).isoformat(),
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
            module="spa_core.strategies.s62_yield_ladder_v2",
            handler_class="S62YieldLadderV2",
            tags=["ladder", "deployment", "dca", "no_fomo", "sky", "ramp",
                  "advisory", "s62"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S62YieldLadderV2 auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    strat = S62YieldLadderV2()
    for d in (0, 7, 14):
        print(json.dumps(strat.simulate(100_000.0, day_index=d), indent=2))
