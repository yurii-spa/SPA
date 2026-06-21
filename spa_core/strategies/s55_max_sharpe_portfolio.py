"""
spa_core/strategies/s55_max_sharpe_portfolio.py — S55 Maximum Sharpe Portfolio

S55: Maximum Sharpe Portfolio
=============================
The "trust the optimizer" strategy. S55 adopts the grid-search portfolio
optimizer's **best-Sharpe** allocation verbatim as fixed target weights and
rebalances weekly to hold them. It does no signal processing of its own — it is
the operationalised recommendation of `data/optimizer_results.json`
(`best_by_sharpe`), so the tournament can score the optimizer's pick head-to-head
against the heuristic strategies.

Optimizer best-Sharpe weights (run 2026-06-20, Sharpe_daily 5.76, APY 4.484%):
  aave 30% · compound 20% · sky 30% · morpho 20%   (T2 total 20%)

⚠️ Sky/sUSDS gate (FORBIDDEN rule #7 + ADR Sky watch-list):
  Sky/sUSDS MUST hold 0% allocation until the on-chain GSM Pause Delay ≥ 48h is
  confirmed. So by default S55 GATES the 30% sky sleeve into a cash buffer and
  deploys only aave/compound/morpho. Pass sky_gsm_confirmed=True (only once the
  gate is genuinely satisfied) to restore the full optimizer weights and the
  4.484% target APY. The raw optimizer weights are preserved in
  RAW_OPTIMIZER_WEIGHTS for transparency; gating never silently rewrites them.

Rebalance cadence: weekly (REBALANCE_PERIOD_DAYS = 7) — should_rebalance() tells
the cycle when the held weights have aged past a week.

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy is never overridden
  - Sky stays 0% until GSM Pause Delay ≥ 48h (rule #7) — gated by default

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional, Set

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S55"
STRATEGY_NAME = "Maximum Sharpe Portfolio"
TIER          = "T1"
DESCRIPTION   = (
    "Maximum Sharpe Portfolio: adopts the optimizer's best-Sharpe allocation "
    "(aave 30% / compound 20% / sky 30% / morpho 20%, Sharpe 5.76, APY 4.484%) as "
    "fixed weights, rebalanced weekly. Sky 30% is gated to cash by default per "
    "FORBIDDEN rule #7 (GSM Pause Delay ≥ 48h) until confirmed. Advisory only."
)

# ─── Keys ─────────────────────────────────────────────────────────────────────

SKY_KEY  = "sky_susds"
CASH_KEY = "cash"

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":     "T1",
    "compound_v3": "T1",
    SKY_KEY:       "T1",   # Sky/sUSDS is a T1 anchor, but gated to 0% (rule #7)
    "morpho_blue": "T2",
    CASH_KEY:      "CASH",
}

# ─── Raw optimizer best-Sharpe weights (from data/optimizer_results.json) ──────
# Source of truth — NEVER mutated; gating produces a separate gated map.
RAW_OPTIMIZER_WEIGHTS: Dict[str, float] = {
    "aave_v3":     0.30,
    "compound_v3": 0.20,
    SKY_KEY:       0.30,
    "morpho_blue": 0.20,
}

# Fallback APYs (%) tuned so the *confirmed* allocation reproduces the optimizer's
# reported 4.484% expected APY: 0.3*3.5 + 0.2*4.8 + 0.3*3.58 + 0.2*7.0 = 4.484.
FALLBACK_APY: Dict[str, float] = {
    "aave_v3":     3.5,
    "compound_v3": 4.8,
    SKY_KEY:       3.58,
    "morpho_blue": 7.0,
    CASH_KEY:      0.0,
}

OPTIMIZER_SHARPE_APY:  float = 4.484   # optimizer-reported best-Sharpe expected APY
OPTIMIZER_SHARPE_DAILY: float = 5.7645

REBALANCE_PERIOD_DAYS: int = 7         # weekly rebalance

TARGET_APY_MIN:   float = 3.3   # gated (sky→cash) floor
TARGET_APY_MAX:   float = 4.5   # confirmed (full optimizer weights)
RISK_SCORE:       float = 0.22
MAX_DRAWDOWN_PCT: float = 3.0


def gated_weights(sky_gsm_confirmed: bool) -> Dict[str, float]:
    """Apply the Sky gate.

    confirmed=True  → raw optimizer weights (sky deployed).
    confirmed=False → sky weight parked in CASH (rule #7), others unchanged.
    """
    if sky_gsm_confirmed:
        return dict(RAW_OPTIMIZER_WEIGHTS)
    w = {k: v for k, v in RAW_OPTIMIZER_WEIGHTS.items() if k != SKY_KEY}
    w[CASH_KEY] = RAW_OPTIMIZER_WEIGHTS.get(SKY_KEY, 0.0)
    return w


def should_rebalance(days_since_last: Optional[int]) -> bool:
    """Weekly cadence: rebalance when ≥ REBALANCE_PERIOD_DAYS have elapsed.
    None (never rebalanced) → True."""
    if days_since_last is None:
        return True
    return int(days_since_last) >= REBALANCE_PERIOD_DAYS


class S55MaxSharpePortfolio:
    """S55 — Maximum Sharpe Portfolio (optimizer best-Sharpe fixed weights, weekly)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def get_allocation(
        self,
        sky_gsm_confirmed: bool = False,
        suspended: Optional[Set[str]] = None,
    ) -> Dict[str, float]:
        """Fixed optimizer weights (sky gated to cash unless confirmed).

        Suspended protocols (cash never suspendable) are dropped and the remainder
        renormalized to 1.0."""
        suspended = suspended or set()
        base = gated_weights(sky_gsm_confirmed)
        kept = {k: v for k, v in base.items()
                if k == CASH_KEY or k not in suspended}
        total = sum(kept.values())
        if total <= 0.0:
            return {}
        return {k: round(v / total, 8) for k, v in kept.items()}

    def get_expected_apy(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        sky_gsm_confirmed: bool = False,
        suspended: Optional[Set[str]] = None,
    ) -> float:
        apy_map = apy_map or {}
        alloc = self.get_allocation(sky_gsm_confirmed, suspended)
        if not alloc:
            return 0.0
        weighted = 0.0
        for p, w in alloc.items():
            apy = apy_map.get(p, FALLBACK_APY.get(p, 0.0))
            weighted += w * apy
        return round(weighted, 4)

    def get_risk_summary(
        self,
        sky_gsm_confirmed: bool = False,
        suspended: Optional[Set[str]] = None,
    ) -> Dict:
        alloc = self.get_allocation(sky_gsm_confirmed, suspended)
        t1 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in alloc.items() if PROTOCOL_TIERS.get(p) == "T2")
        cash = alloc.get(CASH_KEY, 0.0)
        return {
            "strategy_id":          STRATEGY_ID,
            "risk_score":           RISK_SCORE,
            "t1_weight_pct":        round(t1 * 100.0, 2),
            "t2_weight_pct":        round(t2 * 100.0, 2),
            "cash_weight_pct":      round(cash * 100.0, 2),
            "sky_gsm_confirmed":    sky_gsm_confirmed,
            "rebalance_period_days": REBALANCE_PERIOD_DAYS,
            "optimizer_sharpe_apy": OPTIMIZER_SHARPE_APY,
            "max_drawdown_pct":     MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        apy_map: Optional[Dict[str, float]] = None,
        sky_gsm_confirmed: bool = False,
        suspended: Optional[Set[str]] = None,
        days_since_last_rebalance: Optional[int] = None,
    ) -> Dict:
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "allocation":                {},
                "sky_gsm_confirmed":         sky_gsm_confirmed,
                "should_rebalance":          should_rebalance(days_since_last_rebalance),
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        alloc = self.get_allocation(sky_gsm_confirmed, suspended)
        apy = self.get_expected_apy(apy_map, sky_gsm_confirmed, suspended)
        positions = {p: round(capital_usd * w, 6) for p, w in alloc.items()}
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "allocation":                positions,
            "sky_gsm_confirmed":         sky_gsm_confirmed,
            "should_rebalance":          should_rebalance(days_since_last_rebalance),
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "status":                    "ok",
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> Dict:
        return {
            "strategy_id":           STRATEGY_ID,
            "strategy_name":         STRATEGY_NAME,
            "tier":                  TIER,
            "description":           DESCRIPTION,
            "protocol_tiers":        dict(PROTOCOL_TIERS),
            "raw_optimizer_weights": dict(RAW_OPTIMIZER_WEIGHTS),
            "fallback_apy":          dict(FALLBACK_APY),
            "optimizer_sharpe_apy":  OPTIMIZER_SHARPE_APY,
            "optimizer_sharpe_daily": OPTIMIZER_SHARPE_DAILY,
            "rebalance_period_days": REBALANCE_PERIOD_DAYS,
            "target_apy_min":        TARGET_APY_MIN,
            "target_apy_max":        TARGET_APY_MAX,
            "risk_score":            RISK_SCORE,
            "max_drawdown_pct":      MAX_DRAWDOWN_PCT,
            "timestamp":             datetime.now(timezone.utc).isoformat(),
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
            module="spa_core.strategies.s55_max_sharpe_portfolio",
            handler_class="S55MaxSharpePortfolio",
            tags=["optimizer", "max_sharpe", "fixed_weights", "weekly_rebalance",
                  "sky_gated", "aave", "compound", "morpho", "t1", "s55"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S55MaxSharpePortfolio auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S55MaxSharpePortfolio()
    print("=== gated (default, sky→cash) ===")
    print(json.dumps(strat.simulate(100_000.0), indent=2))
    print("=== confirmed (full optimizer weights) ===")
    print(json.dumps(strat.simulate(100_000.0, sky_gsm_confirmed=True), indent=2))
