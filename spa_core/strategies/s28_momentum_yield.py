"""
spa_core/strategies/s28_momentum_yield.py — S28 Momentum Yield

S28: Momentum Yield
===================
APY-momentum strategy. Rising APY usually signals growing borrowing demand /
inflows that persist for a while; falling APY signals the reverse. S28 tilts an
equal-weight base toward protocols with positive 7-day APY momentum and away
from those whose yields are collapsing — riding peaks and stepping off declines.

Logic:
  - For each protocol, compute 7-day momentum = APY_now - APY_7d_ago (%/week).
  - Tilt weight: w_i = base_i * (1 + TILT_K * clamp(momentum_i, ±CLAMP)).
  - Floor at zero, renormalize to sum 1.0.
  - Protocols with momentum > +0.5%/week get overweighted; < -0.5%/week
    underweighted.

Target: capture APY peaks, avoid collapses.

Protocols / tiers:
  aave_v3 T1, compound_v3 T1, morpho_steakhouse T1, morpho_blue T2, yearn_v3 T2

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy is never overridden

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S28"
STRATEGY_NAME = "Momentum Yield"
TIER          = "T2"
DESCRIPTION   = (
    "Momentum Yield: tilts an equal-weight base toward protocols with positive "
    "7-day APY momentum (> +0.5%/week) and away from declining ones. Rides yield "
    "peaks, avoids collapses. T1+T2 lending universe. Advisory only."
)

# ─── Universe ─────────────────────────────────────────────────────────────────

PROTOCOLS = ["aave_v3", "compound_v3", "morpho_steakhouse", "morpho_blue", "yearn_v3"]

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":           "T1",
    "compound_v3":       "T1",
    "morpho_steakhouse": "T1",
    "morpho_blue":       "T2",
    "yearn_v3":          "T2",
}

FALLBACK_APY: Dict[str, float] = {
    "aave_v3":           4.0,
    "compound_v3":       4.8,
    "morpho_steakhouse": 6.5,
    "morpho_blue":       7.0,
    "yearn_v3":          6.0,
}

# ─── Momentum tuning ──────────────────────────────────────────────────────────

MOMENTUM_THRESHOLD_PCT: float = 0.5   # +0.5%/week = meaningful momentum
TILT_K:                 float = 0.5   # tilt sensitivity per %/week
CLAMP_PCT:              float = 3.0   # cap |momentum| influence at ±3%/week
WINDOW_DAYS:            int   = 7

TARGET_APY_MIN:   float = 5.0
TARGET_APY_MAX:   float = 9.0
RISK_SCORE:       float = 0.40
MAX_DRAWDOWN_PCT: float = 6.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute_momentum(history: Optional[List[float]]) -> float:
    """7-day APY momentum (%/week) from a series of daily APY readings.

    momentum = last - value WINDOW_DAYS entries ago. Falls back to (last - first)
    for short series, 0.0 for empty / single-point series.
    """
    if not history or len(history) < 2:
        return 0.0
    last = float(history[-1])
    if len(history) > WINDOW_DAYS:
        past = float(history[-1 - WINDOW_DAYS])
    else:
        past = float(history[0])
    return round(last - past, 6)


class S28MomentumYield:
    """S28 — Momentum Yield (7-day APY-momentum tilt over equal weight)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def get_momentum_scores(
        self,
        apy_history: Optional[Dict[str, List[float]]] = None,
    ) -> Dict[str, float]:
        """Per-protocol 7-day momentum (%/week)."""
        apy_history = apy_history or {}
        return {p: compute_momentum(apy_history.get(p)) for p in PROTOCOLS}

    def get_allocation(
        self,
        apy_history: Optional[Dict[str, List[float]]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """Momentum-tilted weights (sum 1.0) over the non-suspended universe."""
        suspended = suspended or set()
        active = [p for p in PROTOCOLS if p not in suspended]
        if not active:
            return {}
        base = 1.0 / len(active)
        scores = self.get_momentum_scores(apy_history)

        raw: Dict[str, float] = {}
        for p in active:
            m = _clamp(scores.get(p, 0.0), -CLAMP_PCT, CLAMP_PCT)
            w = base * (1.0 + TILT_K * m)
            raw[p] = max(0.0, w)

        total = sum(raw.values())
        if total <= 0.0:
            # All tilted to zero (extreme negative momentum) → fall back to equal.
            return {p: round(base, 8) for p in active}
        return {p: round(w / total, 8) for p, w in raw.items()}

    def get_expected_apy(
        self,
        apy_history: Optional[Dict[str, List[float]]] = None,
        apy_map: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> float:
        """Weighted expected APY (%). Uses latest history point, then apy_map,
        then fallback, for each protocol's current APY."""
        apy_history = apy_history or {}
        apy_map = apy_map or {}
        alloc = self.get_allocation(apy_history, suspended)
        if not alloc:
            return 0.0
        weighted = 0.0
        for p, w in alloc.items():
            hist = apy_history.get(p)
            if hist:
                apy = float(hist[-1])
            else:
                apy = apy_map.get(p, FALLBACK_APY.get(p, 0.0))
            weighted += w * apy
        return round(weighted, 4)

    def get_risk_summary(
        self,
        apy_history: Optional[Dict[str, List[float]]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        alloc = self.get_allocation(apy_history, suspended)
        t1 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T2")
        return {
            "strategy_id":     STRATEGY_ID,
            "risk_score":      RISK_SCORE,
            "t1_weight_pct":   round(t1 * 100.0, 2),
            "t2_weight_pct":   round(t2 * 100.0, 2),
            "momentum_threshold_pct": MOMENTUM_THRESHOLD_PCT,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        apy_history: Optional[Dict[str, List[float]]] = None,
        apy_map: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "allocation":                {},
                "momentum_scores":           self.get_momentum_scores(apy_history),
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        alloc = self.get_allocation(apy_history, suspended)
        apy = self.get_expected_apy(apy_history, apy_map, suspended)
        positions = {p: round(capital_usd * w, 6) for p, w in alloc.items()}
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "allocation":                positions,
            "momentum_scores":           self.get_momentum_scores(apy_history),
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
            "protocols":        list(PROTOCOLS),
            "protocol_tiers":   dict(PROTOCOL_TIERS),
            "fallback_apy":     dict(FALLBACK_APY),
            "momentum_threshold_pct": MOMENTUM_THRESHOLD_PCT,
            "tilt_k":           TILT_K,
            "window_days":      WINDOW_DAYS,
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
            module="spa_core.strategies.s28_momentum_yield",
            handler_class="S28MomentumYield",
            tags=["exotic", "momentum", "apy_trend", "tilt", "aave", "compound",
                  "morpho", "yearn", "t2", "s28"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S28MomentumYield auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S28MomentumYield()
    hist = {
        "aave_v3":     [3.5, 3.6, 3.8, 4.0, 4.2, 4.5, 4.8, 5.2],   # rising
        "compound_v3": [5.0, 4.8, 4.6, 4.4, 4.2, 4.0, 3.8, 3.6],   # falling
    }
    print(json.dumps(strat.simulate(100_000.0, hist), indent=2))
