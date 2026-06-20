"""
spa_core/strategies/s42_crisis_refuge.py — S42 Crisis Refuge

S42: Crisis Refuge
==================
The ultra-safe portfolio for when DeFi *feels* risky. When market-wide signals
say "de-risk now", S42 parks the book in the lowest-volatility T1 venues the
universe offers, anchored by Sky sUSDS — whose realized daily-return volatility
(0.022%) is the lowest of any protocol we track (vs Aave 0.073%, Morpho 0.078%).

Target book (static, deterministic):
  sky_susds     50%  T1  — primary refuge: lowest vol (0.022%), 4.20% mean APY
  aave_v3       30%  T1  — battle-tested lending anchor (3.64%)
  compound_v3   15%  T1  — T1 diversifier (3.78%)
  cash           5%      — dry powder / min cash buffer

Expected APY ≈ 0.50·4.20 + 0.30·3.64 + 0.15·3.78 ≈ 3.76%.
Max-drawdown target < 0.1% — the lowest of any SPA strategy, by construction:
100% T1, zero T2/T3, zero leverage, dominated by the lowest-vol asset.

Activation — S42 is *advisory only* and proposes itself when ANY of these
crisis triggers fires:
  1. Market-wide T2 APY collapse: every tracked T2 protocol's APY < 3%.
  2. Kill switch raised anywhere (RiskPolicy drawdown kill, manual halt, etc.).
  3. TVL of any held position drops > 30% in 24h (venue run / depeg risk).

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
The deterministic RiskPolicy gate retains final authority; `approved=False` is
never overridden. S42 never opens positions itself — it emits a target weight
map and an activation verdict for the allocator/operator to consider.

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S42"
STRATEGY_NAME = "Crisis Refuge"
TIER          = "T1"
DESCRIPTION   = (
    "Crisis Refuge: ultra-defensive 100% T1 book anchored by Sky sUSDS (lowest "
    "vol 0.022%). 50% sUSDS + 30% Aave + 15% Compound + 5% cash. Expected ~3.76% "
    "APY, max DD < 0.1% (lowest of any strategy). Advisory-only; proposes itself "
    "on crisis triggers (T2 APY collapse, kill switch, or 30% TVL crash in 24h)."
)

CASH_KEY = "cash"

# ─── Target book (fractions, sum to 1.0) ──────────────────────────────────────

TARGET_WEIGHTS: Dict[str, float] = {
    "sky_susds":   0.50,   # primary refuge — lowest vol
    "aave_v3":     0.30,
    "compound_v3": 0.15,
    CASH_KEY:      0.05,
}

PROTOCOL_TIERS: Dict[str, str] = {
    "sky_susds":   "T1",
    "aave_v3":     "T1",
    "compound_v3": "T1",
    CASH_KEY:      "CASH",
}

# Conservative default annual APYs (%) from the real track (2026-06 sample).
APY_DEFAULTS: Dict[str, float] = {
    "sky_susds":   4.20,
    "aave_v3":     3.64,
    "compound_v3": 3.78,
    CASH_KEY:      0.0,
}

# Realized daily-return volatility (%) — sUSDS is the lowest in the universe.
DAILY_VOL: Dict[str, float] = {
    "sky_susds":   0.022,
    "aave_v3":     0.073,
    "compound_v3": 0.070,
    CASH_KEY:      0.0,
}

# ─── Activation thresholds ────────────────────────────────────────────────────

T2_APY_COLLAPSE_THRESHOLD: float = 3.0    # all T2 APYs below this (%) → crisis
TVL_CRASH_THRESHOLD_PCT:   float = -30.0  # held-position 24h TVL change ≤ this → crisis

# ─── Targets / risk ───────────────────────────────────────────────────────────

TARGET_APY_MIN:   float = 3.5
TARGET_APY_MAX:   float = 4.2
RISK_SCORE:       float = 0.10   # lowest-risk strategy in the book
MAX_DRAWDOWN_PCT: float = 0.1    # < 0.1% target, by construction


def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x  # not NaN


class S42CrisisRefuge:
    """S42 — Crisis Refuge (static ultra-defensive T1 book + crisis trigger logic)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    # ── Allocation ────────────────────────────────────────────────────────────

    def get_weights(self) -> Dict[str, float]:
        """Target weight map (fractions, sum 1.0)."""
        return dict(TARGET_WEIGHTS)

    def get_allocation(self, capital_usd: float) -> Dict[str, float]:
        """Target USD allocation per venue. Empty on non-positive capital."""
        if capital_usd <= 0.0:
            return {}
        return {p: round(capital_usd * w, 6) for p, w in TARGET_WEIGHTS.items()}

    # ── Expected return ───────────────────────────────────────────────────────

    def get_expected_apy(self, apy_map: Optional[Dict[str, float]] = None) -> float:
        """Weighted expected APY (%). Falls back to APY_DEFAULTS per venue."""
        apy_map = apy_map or {}
        weighted = 0.0
        for p, w in TARGET_WEIGHTS.items():
            apy = apy_map.get(p, APY_DEFAULTS.get(p, 0.0))
            weighted += w * apy
        return round(weighted, 4)

    def get_expected_daily_vol(self, vol_map: Optional[Dict[str, float]] = None) -> float:
        """Weighted average daily volatility (%) of the book (advisory proxy)."""
        vol_map = vol_map or {}
        weighted = 0.0
        for p, w in TARGET_WEIGHTS.items():
            vol = vol_map.get(p, DAILY_VOL.get(p, 0.0))
            weighted += w * vol
        return round(weighted, 6)

    # ── Activation logic ──────────────────────────────────────────────────────

    def should_activate(self, market_state: Optional[Dict] = None) -> Dict:
        """Evaluate the crisis triggers against a market-state snapshot.

        Args:
            market_state: {
                "t2_apys":         {protocol: apy_pct, ...}  — tracked T2 APYs,
                "kill_switch":     bool                      — any kill switch raised,
                "position_tvl_24h_change_pct": {pos: pct, ...} — 24h TVL Δ of held positions,
            }  — any key may be omitted (→ that trigger is False).

        Returns:
            {"active": bool, "triggers": [str, ...], "detail": {...}}.
        """
        market_state = market_state or {}
        triggers: List[str] = []
        detail: Dict[str, object] = {}

        # 1. Market-wide T2 APY collapse — every tracked T2 protocol below threshold.
        t2_apys = market_state.get("t2_apys") or {}
        valid_t2 = {k: float(v) for k, v in t2_apys.items() if _is_number(v)}
        if valid_t2 and all(v < T2_APY_COLLAPSE_THRESHOLD for v in valid_t2.values()):
            triggers.append("t2_apy_collapse")
            detail["t2_apy_collapse"] = {
                "threshold_pct": T2_APY_COLLAPSE_THRESHOLD,
                "t2_apys":       valid_t2,
            }

        # 2. Kill switch raised anywhere.
        if bool(market_state.get("kill_switch")):
            triggers.append("kill_switch")
            detail["kill_switch"] = True

        # 3. TVL of any held position drops > 30% in 24h.
        tvl_changes = market_state.get("position_tvl_24h_change_pct") or {}
        crashed = {k: float(v) for k, v in tvl_changes.items()
                   if _is_number(v) and float(v) <= TVL_CRASH_THRESHOLD_PCT}
        if crashed:
            triggers.append("tvl_crash")
            detail["tvl_crash"] = {
                "threshold_pct": TVL_CRASH_THRESHOLD_PCT,
                "positions":     crashed,
            }

        return {"active": len(triggers) > 0, "triggers": triggers, "detail": detail}

    # ── Summaries ─────────────────────────────────────────────────────────────

    def get_risk_summary(self) -> Dict:
        t1 = sum(w for p, w in TARGET_WEIGHTS.items() if PROTOCOL_TIERS.get(p) == "T1")
        cash = TARGET_WEIGHTS.get(CASH_KEY, 0.0)
        return {
            "strategy_id":      STRATEGY_ID,
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    0.0,
            "cash_weight_pct":  round(cash * 100.0, 2),
            "expected_daily_vol_pct": self.get_expected_daily_vol(),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        apy_map: Optional[Dict[str, float]] = None,
        market_state: Optional[Dict] = None,
    ) -> Dict:
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "allocation":                {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "activation":                self.should_activate(market_state),
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        apy = self.get_expected_apy(apy_map)
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "allocation":                self.get_allocation(capital_usd),
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "expected_daily_vol_pct":    self.get_expected_daily_vol(),
            "activation":                self.should_activate(market_state),
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
            "protocol_tiers":   dict(PROTOCOL_TIERS),
            "apy_defaults":     dict(APY_DEFAULTS),
            "daily_vol":        dict(DAILY_VOL),
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
            module="spa_core.strategies.s42_crisis_refuge",
            handler_class="S42CrisisRefuge",
            tags=["defensive", "crisis", "capital_preservation", "sky_susds",
                  "low_vol", "t1_only", "refuge", "s42"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S42CrisisRefuge auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S42CrisisRefuge()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
    crisis = {"t2_apys": {"morpho_blue": 2.5, "yearn_v3": 2.1}, "kill_switch": False}
    print(json.dumps(strat.should_activate(crisis), indent=2))
