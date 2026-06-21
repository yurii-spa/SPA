"""
spa_core/strategies/s70_session_best.py — S70 Session Best

S70: Session Best
=================
The hand-curated "best of session" book — the allocation the night's research
converged on as the most defensible risk/return compromise across everything
studied (optimizer output, volatility ranking, tier caps, and the new Fluid
high-yield find). It is the human-judgment counterpart to S66 Real Data Optimal:
S66 maximizes blended mean APY under the caps; S70 trades a sliver of that yield
for a smoother, more reliable book by leaning on Sky's low-vol peg and spreading
the T2 sleeve across two venues.

Curated allocation
------------------
    Sky sUSDS    30%   T1   lowest realized vol, peg-anchored (mean 4.20%)
    Morpho Blue  20%   T2   highest historical APY (mean 6.87%), at T2 cap
    Aave V3      20%   T1   battle-tested T1 anchor (mean 3.64%)
    Compound V3  15%   T1   T1 diversifier (mean 3.78%)
    Fluid USDC   10%   T2   new high-yield find (current ~6.22%)
    cash          5%        RiskPolicy min buffer
    ──────────────────────────────────────────────────────────
    blended expected APY ≈ 4.55%

    0.30·4.20 + 0.20·6.87 + 0.20·3.64 + 0.15·3.78 + 0.10·6.22
  = 1.260    + 1.374     + 0.728     + 0.567     + 0.622     = 4.551%

Policy check: T2 sleeve = Morpho 20% + Fluid 10% = 30% ≤ 50% (ADR-019); each
venue ≤ its per-protocol cap (T1 40%, T2 20%); 5% cash satisfies the min buffer.

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
The deterministic RiskPolicy gate retains final authority; `approved=False` is
never overridden. S70 emits a static target weight map only — it never opens
positions itself. Sky/Fluid deployment stays subject to the watch-list /
TVL-floor rules; the gate governs actual capital.

Date: 2026-06-21
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S70"
STRATEGY_NAME = "Session Best"
TIER          = "T2"   # carries a 30% T2 sleeve (Morpho + Fluid) → classified T2
DESCRIPTION   = (
    "Session Best: hand-curated best-of-session book — Sky 30% + Morpho 20% + "
    "Aave 20% + Compound 15% + Fluid 10% + 5% cash = ~4.55% blended APY. Trades "
    "a little yield vs S66 for a smoother, low-vol book (Sky ballast, two-venue "
    "T2 sleeve). Policy-compliant (T2 30%≤50%, caps, 5% cash). Advisory-only, "
    "deterministic, stdlib."
)

CASH_KEY = "cash"

# ─── Curated target weights ────────────────────────────────────────────────────

PROTOCOL_TIERS: Dict[str, str] = {
    "sky_susds":   "T1",
    "morpho_blue": "T2",
    "aave_v3":     "T1",
    "compound_v3": "T1",
    "fluid":       "T2",
    CASH_KEY:      "CASH",
}

TARGET_WEIGHTS: Dict[str, float] = {
    "sky_susds":   0.30,
    "morpho_blue": 0.20,
    "aave_v3":     0.20,
    "compound_v3": 0.15,
    "fluid":       0.10,
    CASH_KEY:      0.05,
}

# Reference APY (%) — DeFiLlama 2026-06 means / current (Fluid = current).
APY_DEFAULTS: Dict[str, float] = {
    "sky_susds":   4.20,
    "morpho_blue": 6.87,
    "aave_v3":     3.64,
    "compound_v3": 3.78,
    "fluid":       6.22,
}

# Per-protocol caps by tier and T2 aggregate cap (RiskPolicy / ADR-019).
PER_PROTOCOL_CAP: Dict[str, float] = {"T1": 0.40, "T2": 0.20}
T2_TOTAL_CAP:     float = 0.50

# ─── Targets / risk ───────────────────────────────────────────────────────────

TARGET_APY_MIN:   float = 4.3
TARGET_APY_MAX:   float = 4.9
RISK_SCORE:       float = 0.40
MAX_DRAWDOWN_PCT: float = 2.8


def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


class S70SessionBest:
    """S70 — Session Best (hand-curated static best-of-session book)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def __init__(self) -> None:
        pass

    # ── Allocation ──────────────────────────────────────────────────────────────

    def compute_weights(self, current_apys: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """Return the curated static target weight map (fractions, sum = 1.0)."""
        return {p: round(w, 6) for p, w in TARGET_WEIGHTS.items()}

    def get_weights(self, current_apys: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        return self.compute_weights(current_apys)

    def get_allocation(self, capital_usd: float,
                       current_apys: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        if capital_usd <= 0.0:
            return {}
        return {p: round(capital_usd * w, 6) for p, w in self.compute_weights().items()}

    # ── Expected return ──────────────────────────────────────────────────────────

    def get_expected_apy(self, current_apys: Optional[Dict[str, float]] = None) -> float:
        apys = current_apys or dict(APY_DEFAULTS)
        weighted = 0.0
        for p, w in TARGET_WEIGHTS.items():
            if p == CASH_KEY:
                continue
            apy = apys.get(p, APY_DEFAULTS.get(p, 0.0))
            weighted += w * (float(apy) if _is_number(apy) else APY_DEFAULTS.get(p, 0.0))
        return round(weighted, 4)

    # ── Compliance check ─────────────────────────────────────────────────────────

    def policy_check(self) -> Dict:
        """Verify the curated book respects the RiskPolicy caps (self-audit)."""
        weights = self.compute_weights()
        t2_total = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T2")
        cash = weights.get(CASH_KEY, 0.0)
        per_protocol_ok = all(
            w <= PER_PROTOCOL_CAP.get(PROTOCOL_TIERS.get(p, "T2"), 0.20) + 1e-9
            for p, w in weights.items() if p != CASH_KEY
        )
        return {
            "strategy_id":       STRATEGY_ID,
            "t2_total":          round(t2_total, 6),
            "t2_cap_ok":         t2_total <= T2_TOTAL_CAP + 1e-9,
            "per_protocol_ok":   per_protocol_ok,
            "cash_buffer_ok":    cash >= 0.05 - 1e-9,
            "sums_to_one":       abs(sum(weights.values()) - 1.0) < 1e-9,
        }

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
            "weights":                   weights,
            "allocation":                {p: round(capital_usd * w, 6) for p, w in weights.items()},
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "policy_check":              self.policy_check(),
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
            "target_weights":   dict(TARGET_WEIGHTS),
            "protocol_tiers":   {p: PROTOCOL_TIERS[p] for p in TARGET_WEIGHTS},
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
            module="spa_core.strategies.s70_session_best",
            handler_class="S70SessionBest",
            tags=["session_best", "curated", "low_vol", "fluid", "balanced",
                  "advisory", "s70"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S70SessionBest auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    strat = S70SessionBest()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
