"""
spa_core/strategies/s68_temporal_diversification.py — S68 Temporal Diversification

S68: Temporal Diversification
=============================
Most strategies diversify across *protocols*. S68 also diversifies across
*time horizons* — it runs four independent sub-sleeves simultaneously, each
with a different rebalance cadence / lock structure, so the book is never fully
exposed to a single timing decision:

    Sub-A  25%  30-day-lock equivalent   → Sky sUSDS (near-constant peg ballast)
    Sub-B  25%  7-day rebalance          → T1 equal weight (Aave/Compound/Sky)
    Sub-C  25%  1-day rebalance          → best CURRENT-APY venue (chase spot)
    Sub-D  25%  rate-lock                → Pendle PT (fixed forward rate)

Rationale: laddering rebalance frequency is the yield analogue of bond maturity
laddering. The slow sleeves (A, D) lock in stability and forward rate; the fast
sleeves (B, C) capture spot opportunities. Their timing errors are uncorrelated,
so the blended book has a smoother realized path than any single cadence.

Aggregation
-----------
The four 25% sleeves are summed into one target weight map. Because fast sleeves
can concentrate (Sub-C → one venue), the aggregate is then run through the
RiskPolicy caps — per-protocol (T1 40% / T2 20%) and T2 aggregate ≤ 50%
(ADR-019) — by water-filling; any weight that cannot be placed under the caps
falls to cash. Expected APY ≈ 4.5% (average across the four sleeves).

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
The deterministic RiskPolicy gate retains final authority; `approved=False` is
never overridden. S68 emits target weights + the per-sleeve breakdown; it never
opens positions itself. Sky/Pendle deployment stays subject to the watch-list /
T3-SPEC rules; the gate governs actual capital.

Date: 2026-06-21
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S68"
STRATEGY_NAME = "Temporal Diversification"
TIER          = "T2"   # carries Pendle PT + spot sleeves → classified T2
DESCRIPTION   = (
    "Temporal Diversification: four 25% sleeves laddered by rebalance horizon — "
    "30-day lock (Sky sUSDS), 7-day T1 equal weight, 1-day best-current-APY, and "
    "Pendle PT rate-lock. Diversifies timing risk, not just protocol risk. "
    "Aggregate is cap-enforced (T1 40%/T2 20%, T2≤50%). Expected ~4.5% APY. "
    "Advisory-only, deterministic, stdlib."
)

CASH_KEY = "cash"

# ─── Protocol universe ────────────────────────────────────────────────────────

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":     "T1",
    "compound_v3": "T1",
    "sky_susds":   "T1",
    "morpho_blue": "T2",
    "yearn_v3":    "T2",
    "fluid":       "T2",
    "pendle_pt":   "T2",
    CASH_KEY:      "CASH",
}

# T1 venues used by Sub-B (equal weight) and the spot universe for Sub-C.
T1_VENUES:   List[str] = ["aave_v3", "compound_v3", "sky_susds"]
SPOT_VENUES: List[str] = ["aave_v3", "compound_v3", "sky_susds",
                          "morpho_blue", "yearn_v3", "fluid"]
LOCK_VENUE:  str       = "sky_susds"   # Sub-A 30-day-lock equivalent
PT_VENUE:    str       = "pendle_pt"   # Sub-D fixed-rate lock

SUB_WEIGHT:  float = 0.25   # each sleeve holds 25% of capital

# Default APY (%) per protocol — DeFiLlama 2026-06 means / current.
APY_DEFAULTS: Dict[str, float] = {
    "aave_v3":     3.64,
    "compound_v3": 3.78,
    "sky_susds":   4.20,
    "morpho_blue": 6.87,
    "yearn_v3":    4.95,
    "fluid":       6.22,
    "pendle_pt":   6.00,   # Pendle PT fixed forward rate (conservative default)
}

# Per-protocol caps by tier and T2 aggregate cap (RiskPolicy / ADR-019).
PER_PROTOCOL_CAP: Dict[str, float] = {"T1": 0.40, "T2": 0.20}
T2_TOTAL_CAP:     float = 0.50

# ─── Targets / risk ───────────────────────────────────────────────────────────

TARGET_APY_MIN:   float = 4.2
TARGET_APY_MAX:   float = 5.0
RISK_SCORE:       float = 0.45
MAX_DRAWDOWN_PCT: float = 3.0


def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def _cap_for(protocol: str) -> float:
    return PER_PROTOCOL_CAP.get(PROTOCOL_TIERS.get(protocol, "T2"), 0.20)


class S68TemporalDiversification:
    """S68 — Temporal Diversification (four horizon-laddered sleeves)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def __init__(self) -> None:
        pass

    # ── Sub-sleeves ───────────────────────────────────────────────────────────────

    def _best_current_venue(self, current_apys: Dict[str, float]) -> str:
        """Highest live-APY venue among SPOT_VENUES (deterministic tie-break by
        SPOT_VENUES order). Falls back to the default-APY ranking when no live
        snapshot is supplied."""
        best, best_apy = None, float("-inf")
        for p in SPOT_VENUES:
            apy = current_apys.get(p, APY_DEFAULTS.get(p))
            if not _is_number(apy):
                continue
            if float(apy) > best_apy:
                best, best_apy = p, float(apy)
        return best or SPOT_VENUES[0]

    def sub_allocations(self, current_apys: Optional[Dict[str, float]] = None) -> Dict[str, Dict[str, float]]:
        """Return the four sleeves as separate weight maps (each summing to 0.25)."""
        cur = current_apys or dict(APY_DEFAULTS)
        sub_a = {LOCK_VENUE: SUB_WEIGHT}
        sub_b = {p: SUB_WEIGHT / len(T1_VENUES) for p in T1_VENUES}
        sub_c = {self._best_current_venue(cur): SUB_WEIGHT}
        sub_d = {PT_VENUE: SUB_WEIGHT}
        return {"sub_a_lock30": sub_a, "sub_b_t1_7d": sub_b,
                "sub_c_spot_1d": sub_c, "sub_d_pendle_pt": sub_d}

    # ── Aggregation + caps ────────────────────────────────────────────────────────

    def _aggregate(self, sleeves: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        agg: Dict[str, float] = {}
        for sleeve in sleeves.values():
            for p, w in sleeve.items():
                agg[p] = agg.get(p, 0.0) + w
        return agg

    def _enforce_caps(self, agg: Dict[str, float]) -> Dict[str, float]:
        """Clamp per-protocol caps, then the T2 aggregate cap; freed weight → cash."""
        capped = {p: min(w, _cap_for(p)) for p, w in agg.items()}
        # T2 aggregate cap.
        t2_total = sum(w for p, w in capped.items() if PROTOCOL_TIERS.get(p) == "T2")
        if t2_total > T2_TOTAL_CAP and t2_total > 0:
            scale = T2_TOTAL_CAP / t2_total
            capped = {p: (w * scale if PROTOCOL_TIERS.get(p) == "T2" else w)
                      for p, w in capped.items()}
        deployed = sum(capped.values())
        cash = max(0.0, 1.0 - deployed)
        out = {p: round(w, 6) for p, w in capped.items() if w > 0}
        if cash > 1e-9:
            out[CASH_KEY] = round(cash, 6)
        return out

    def compute_weights(self, current_apys: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """Aggregate the four sleeves and enforce RiskPolicy caps."""
        sleeves = self.sub_allocations(current_apys)
        return self._enforce_caps(self._aggregate(sleeves))

    def get_weights(self, current_apys: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        return self.compute_weights(current_apys)

    def get_allocation(self, capital_usd: float,
                       current_apys: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        if capital_usd <= 0.0:
            return {}
        return {p: round(capital_usd * w, 6) for p, w in self.compute_weights(current_apys).items()}

    # ── Expected return ──────────────────────────────────────────────────────────

    def get_expected_apy(self, current_apys: Optional[Dict[str, float]] = None) -> float:
        apys = current_apys or dict(APY_DEFAULTS)
        weights = self.compute_weights(current_apys)
        weighted = 0.0
        for p, w in weights.items():
            if p == CASH_KEY:
                continue
            apy = apys.get(p, APY_DEFAULTS.get(p, 0.0))
            weighted += w * (float(apy) if _is_number(apy) else APY_DEFAULTS.get(p, 0.0))
        return round(weighted, 4)

    # ── Summaries ────────────────────────────────────────────────────────────────

    def get_risk_summary(self, weights: Optional[Dict[str, float]] = None) -> Dict:
        weights = weights or self.compute_weights()
        t1 = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T2")
        cash = weights.get(CASH_KEY, 0.0)
        return {
            "strategy_id":      STRATEGY_ID,
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "cash_weight_pct":  round(cash * 100.0, 2),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(self, capital_usd: float,
                 current_apys: Optional[Dict[str, float]] = None) -> Dict:
        cur = current_apys or dict(APY_DEFAULTS)
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
        weights = self.compute_weights(cur)
        apy = self.get_expected_apy(cur)
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "sub_allocations":           self.sub_allocations(cur),
            "weights":                   weights,
            "allocation":                {p: round(capital_usd * w, 6) for p, w in weights.items()},
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "risk_summary":              self.get_risk_summary(weights),
            "status":                    "ok",
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> Dict:
        return {
            "strategy_id":      STRATEGY_ID,
            "strategy_name":    STRATEGY_NAME,
            "tier":             TIER,
            "description":      DESCRIPTION,
            "sub_weight":       SUB_WEIGHT,
            "t1_venues":        list(T1_VENUES),
            "spot_venues":      list(SPOT_VENUES),
            "lock_venue":       LOCK_VENUE,
            "pt_venue":         PT_VENUE,
            "protocol_tiers":   {p: PROTOCOL_TIERS[p] for p in APY_DEFAULTS},
            "apy_defaults":     dict(APY_DEFAULTS),
            "per_protocol_cap": dict(PER_PROTOCOL_CAP),
            "t2_total_cap":     T2_TOTAL_CAP,
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
            module="spa_core.strategies.s68_temporal_diversification",
            handler_class="S68TemporalDiversification",
            tags=["temporal", "horizon_ladder", "multi_cadence", "pendle_pt",
                  "diversification", "advisory", "s68"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S68TemporalDiversification auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    strat = S68TemporalDiversification()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
