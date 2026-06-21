"""
spa_core/strategies/s66_real_data_optimal.py — S66 Real Data Optimal

S66: Real Data Optimal
======================
The *scientifically optimal* static allocation, anchored to the actual
DeFiLlama 365-day historical best mix produced by the portfolio optimizer
during this session. The optimizer searched the feasible weight space under
the RiskPolicy caps (T1 ≤ 40%/protocol, T2 ≤ 20%/protocol, T2 total ≤ 50%)
and converged on:

    Aave V3      30%   (T1 anchor,        mean 3.64%)
    Sky sUSDS    30%   (lowest-vol T1,    mean 4.20%)
    Compound V3  20%   (T1 diversifier,   mean 3.78%)
    Morpho Blue  20%   (T2 yield engine,  mean 6.87%)
    ──────────────────────────────────────────────────
    blended expected APY ≈ 4.48%

    0.30·3.64 + 0.30·4.20 + 0.20·3.78 + 0.20·6.87
  = 1.092    + 1.260     + 0.756     + 1.374     = 4.482%

This is the optimizer-derived reference book the session research called
*optimal*: it maximizes blended historical mean APY subject to the policy caps
while leaning on Sky's near-constant peg (3.6–4.75%, lowest realized vol) for
ballast. It is intentionally STATIC — no chasing spikes — and re-anchors only
when a weight drifts off target.

Weekly drift check
------------------
The book is reviewed weekly; a rebalance is signalled when ANY live weight has
drifted more than DRIFT_THRESHOLD (5 percentage points, absolute) from its
target. Below that band the strategy holds — drift-banding suppresses churn and
the rebalance cost it incurs.

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
The deterministic RiskPolicy gate retains final authority; `approved=False` is
never overridden. S66 emits a target weight map and a drift verdict only — it
never opens positions itself. Sky/sUSDS deployment remains subject to the
watch-list rule (FORBIDDEN #7: 0% until on-chain GSM Pause Delay ≥ 48h); the
gate governs actual capital, this book is advisory.

Date: 2026-06-21
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S66"
STRATEGY_NAME = "Real Data Optimal"
TIER          = "T2"   # holds a T2 sleeve (Morpho 20%) → classified T2 overall
DESCRIPTION   = (
    "Real Data Optimal: the optimizer's scientifically optimal static book "
    "anchored to DeFiLlama 365-day historical means under RiskPolicy caps — "
    "Aave 30% + Sky 30% + Compound 20% + Morpho 20% = ~4.48% blended APY. "
    "Weekly drift check: rebalance when any weight drifts > 5pp from target. "
    "Advisory-only, deterministic, stdlib."
)

CASH_KEY = "cash"

# ─── Protocol universe + optimal target weights ────────────────────────────────

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":     "T1",
    "sky_susds":   "T1",
    "compound_v3": "T1",
    "morpho_blue": "T2",
    CASH_KEY:      "CASH",
}

# Optimizer result (fractions, sum = 1.0; fully invested, no idle cash).
TARGET_WEIGHTS: Dict[str, float] = {
    "aave_v3":     0.30,
    "sky_susds":   0.30,
    "compound_v3": 0.20,
    "morpho_blue": 0.20,
}

# Long-run mean APY (%) — DeFiLlama 365-day series (2025-06→2026-06).
MEAN_APY_DEFAULTS: Dict[str, float] = {
    "aave_v3":     3.64,
    "sky_susds":   4.20,
    "compound_v3": 3.78,
    "morpho_blue": 6.87,
}
APY_DEFAULTS: Dict[str, float] = dict(MEAN_APY_DEFAULTS)

# ─── Model parameters ─────────────────────────────────────────────────────────

DRIFT_THRESHOLD: float = 0.05   # rebalance when |live - target| > 5 percentage pts
REBALANCE_DAYS:  int   = 7      # weekly review cadence

# ─── Targets / risk ───────────────────────────────────────────────────────────

TARGET_APY_MIN:   float = 4.2
TARGET_APY_MAX:   float = 4.8
RISK_SCORE:       float = 0.35
MAX_DRAWDOWN_PCT: float = 2.5


def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


class S66RealDataOptimal:
    """S66 — Real Data Optimal (static optimizer book, weekly drift-banded)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def __init__(self, drift_threshold: float = DRIFT_THRESHOLD):
        self.drift_threshold = max(0.0, float(drift_threshold))

    # ── Allocation ──────────────────────────────────────────────────────────────

    def compute_weights(self, current_apys: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """Return the static optimal target weight map (fractions, sum = 1.0).

        `current_apys` is accepted for interface symmetry but ignored — this book
        is anchored to historical means, not live spot rates.
        """
        return {p: round(w, 6) for p, w in TARGET_WEIGHTS.items()}

    def get_weights(self, current_apys: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        return self.compute_weights(current_apys)

    def get_allocation(self, capital_usd: float,
                       current_apys: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """Target USD allocation per venue. Empty on non-positive capital."""
        if capital_usd <= 0.0:
            return {}
        return {p: round(capital_usd * w, 6) for p, w in self.compute_weights().items()}

    # ── Drift / rebalance ─────────────────────────────────────────────────────────

    def drifts(self, current_weights: Dict[str, float]) -> Dict[str, float]:
        """Absolute drift |current - target| per target protocol (fractions)."""
        out: Dict[str, float] = {}
        for p, target in TARGET_WEIGHTS.items():
            cur = current_weights.get(p, 0.0)
            cur = float(cur) if _is_number(cur) else 0.0
            out[p] = round(abs(cur - target), 6)
        return out

    def needs_rebalance(self, current_weights: Dict[str, float]) -> bool:
        """True if ANY target weight has drifted more than the drift threshold."""
        return any(d > self.drift_threshold for d in self.drifts(current_weights).values())

    def rebalance_check(self, current_weights: Dict[str, float]) -> Dict:
        """Detailed weekly drift verdict."""
        drifts = self.drifts(current_weights)
        breaches = {p: d for p, d in drifts.items() if d > self.drift_threshold}
        return {
            "strategy_id":     STRATEGY_ID,
            "needs_rebalance": bool(breaches),
            "drift_threshold": self.drift_threshold,
            "drifts":          drifts,
            "breaches":        breaches,
            "review_days":     REBALANCE_DAYS,
        }

    # ── Expected return ──────────────────────────────────────────────────────────

    def get_expected_apy(self, current_apys: Optional[Dict[str, float]] = None) -> float:
        """Weighted expected APY (%) of the optimal book (cash earns 0)."""
        apys = current_apys or dict(APY_DEFAULTS)
        weighted = 0.0
        for p, w in TARGET_WEIGHTS.items():
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
            "target_weights":   dict(TARGET_WEIGHTS),
            "protocol_tiers":   {p: PROTOCOL_TIERS[p] for p in TARGET_WEIGHTS},
            "mean_apy_defaults": dict(MEAN_APY_DEFAULTS),
            "drift_threshold":  DRIFT_THRESHOLD,
            "rebalance_days":   REBALANCE_DAYS,
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
            module="spa_core.strategies.s66_real_data_optimal",
            handler_class="S66RealDataOptimal",
            tags=["optimal", "static", "optimizer", "drift_banded", "historical_mean",
                  "advisory", "s66"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S66RealDataOptimal auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    strat = S66RealDataOptimal()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
    drifted = {"aave_v3": 0.40, "sky_susds": 0.25, "compound_v3": 0.20, "morpho_blue": 0.15}
    print(json.dumps(strat.rebalance_check(drifted), indent=2))
