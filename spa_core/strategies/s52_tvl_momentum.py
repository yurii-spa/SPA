"""
spa_core/strategies/s52_tvl_momentum.py — S52 TVL Momentum

S52: TVL Momentum
=================
TVL (total value locked) is a flow signal: capital chases working protocols and
flees broken ones. Rising TVL usually precedes durable yield and signals operator
confidence; falling TVL is an early warning of depeg, exploit fear or a better
opportunity elsewhere. S52 overweights protocols whose current TVL sits above
their 6-month average and underweights those whose TVL is shrinking.

Algorithm:
  1. Equal-weight base over the active universe.
  2. For each protocol compute the TVL ratio = current_tvl / avg_6m_tvl.
       ratio > 1 + DEADBAND  → "momentum up"   → tilt += TILT_STEP
       ratio < 1 − DEADBAND  → "momentum down" → tilt −= TILT_STEP
       otherwise             → flat (within deadband)
  3. w_i = base_i + tilt_i, floored at MIN_WEIGHT, renormalized to 1.0.

The default TILT_STEP is +5% / −5% of the base weight (spec: "+5% / -5% weight").
TVL is read from a supplied tvl_now / tvl_avg_6m map (DeFiLlama-sourced in the
live cycle); with no TVL data the strategy degrades gracefully to equal weight.

Expected APY ~4.4% — a mild momentum tilt over a T1+T2 lending base.

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy is never overridden

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Set

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S52"
STRATEGY_NAME = "TVL Momentum"
TIER          = "T2"
DESCRIPTION   = (
    "TVL Momentum: overweights protocols whose current TVL exceeds their 6-month "
    "average (+5% tilt) and underweights those with declining TVL (-5% tilt). "
    "TVL flow as a leading signal of durable yield and operator confidence. "
    "Reads TVL from DeFiLlama, falls back to equal weight. ~4.4% APY. Advisory only."
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

# ─── Momentum tuning ──────────────────────────────────────────────────────────

DEADBAND:    float = 0.02   # ±2% around the 6-month average = "flat"
TILT_STEP:   float = 0.05   # ±5% of base weight per momentum direction
MIN_WEIGHT:  float = 0.0    # floor before renormalization

MOMENTUM_UP   = "up"
MOMENTUM_DOWN = "down"
MOMENTUM_FLAT = "flat"

TARGET_APY_MIN:   float = 4.0
TARGET_APY_MAX:   float = 5.5
RISK_SCORE:       float = 0.35
MAX_DRAWDOWN_PCT: float = 5.0


def tvl_momentum_signal(
    tvl_now: Optional[float],
    tvl_avg_6m: Optional[float],
) -> str:
    """Classify TVL momentum: up / down / flat (within deadband or missing data)."""
    if not tvl_now or not tvl_avg_6m or tvl_avg_6m <= 0.0:
        return MOMENTUM_FLAT
    ratio = float(tvl_now) / float(tvl_avg_6m)
    if ratio > 1.0 + DEADBAND:
        return MOMENTUM_UP
    if ratio < 1.0 - DEADBAND:
        return MOMENTUM_DOWN
    return MOMENTUM_FLAT


class S52TvlMomentum:
    """S52 — TVL Momentum (±5% tilt vs 6-month average TVL)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def get_momentum_signals(
        self,
        tvl_now: Optional[Dict[str, float]] = None,
        tvl_avg_6m: Optional[Dict[str, float]] = None,
    ) -> Dict[str, str]:
        tvl_now = tvl_now or {}
        tvl_avg_6m = tvl_avg_6m or {}
        return {
            p: tvl_momentum_signal(tvl_now.get(p), tvl_avg_6m.get(p))
            for p in PROTOCOLS
        }

    def get_allocation(
        self,
        tvl_now: Optional[Dict[str, float]] = None,
        tvl_avg_6m: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """TVL-momentum-tilted weights (sum 1.0). No TVL data → equal weight."""
        suspended = suspended or set()
        active = [p for p in PROTOCOLS if p not in suspended]
        if not active:
            return {}
        base = 1.0 / len(active)
        signals = self.get_momentum_signals(tvl_now, tvl_avg_6m)

        raw: Dict[str, float] = {}
        for p in active:
            sig = signals.get(p, MOMENTUM_FLAT)
            tilt = base * TILT_STEP
            if sig == MOMENTUM_UP:
                w = base + tilt
            elif sig == MOMENTUM_DOWN:
                w = base - tilt
            else:
                w = base
            raw[p] = max(MIN_WEIGHT, w)

        total = sum(raw.values())
        if total <= 0.0:
            return {p: round(base, 8) for p in active}
        return {p: round(w / total, 8) for p, w in raw.items()}

    def get_expected_apy(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        tvl_now: Optional[Dict[str, float]] = None,
        tvl_avg_6m: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> float:
        apy_map = apy_map or {}
        alloc = self.get_allocation(tvl_now, tvl_avg_6m, suspended)
        if not alloc:
            return 0.0
        weighted = 0.0
        for p, w in alloc.items():
            apy = apy_map.get(p, FALLBACK_APY.get(p, 0.0))
            weighted += w * apy
        return round(weighted, 4)

    def get_risk_summary(
        self,
        tvl_now: Optional[Dict[str, float]] = None,
        tvl_avg_6m: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        alloc = self.get_allocation(tvl_now, tvl_avg_6m, suspended)
        t1 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T2")
        return {
            "strategy_id":      STRATEGY_ID,
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "tilt_step_pct":    round(TILT_STEP * 100.0, 2),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        apy_map: Optional[Dict[str, float]] = None,
        tvl_now: Optional[Dict[str, float]] = None,
        tvl_avg_6m: Optional[Dict[str, float]] = None,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "allocation":                {},
                "momentum_signals":          self.get_momentum_signals(tvl_now, tvl_avg_6m),
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        alloc = self.get_allocation(tvl_now, tvl_avg_6m, suspended)
        apy = self.get_expected_apy(apy_map, tvl_now, tvl_avg_6m, suspended)
        positions = {p: round(capital_usd * w, 6) for p, w in alloc.items()}
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "allocation":                positions,
            "momentum_signals":          self.get_momentum_signals(tvl_now, tvl_avg_6m),
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
            "deadband":         DEADBAND,
            "tilt_step":        TILT_STEP,
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
            module="spa_core.strategies.s52_tvl_momentum",
            handler_class="S52TvlMomentum",
            tags=["tvl", "momentum", "flow", "tilt", "defillama", "aave",
                  "compound", "morpho", "t2", "s52"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S52TvlMomentum auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S52TvlMomentum()
    now = {"aave_v3": 1.2e9, "compound_v3": 0.7e9, "morpho_blue": 1.0e9}
    avg = {"aave_v3": 1.0e9, "compound_v3": 1.0e9, "morpho_blue": 1.0e9}
    print(json.dumps(strat.simulate(100_000.0, tvl_now=now, tvl_avg_6m=avg), indent=2))
