"""
spa_core/strategies/s61_hybrid_income_shield.py — S61 Hybrid Income Shield

S61: Hybrid Income Shield
=========================
An income-first, low-volatility book. The anchor is Sky sUSDS — a near-constant
peg instrument (365-day range 3.60–4.75%, mean 4.20%) that supplies steady
income with almost no rate volatility — wrapped in a thin "shield" of T1 lenders
(Aave, Compound) for safety and a single T2 booster (Morpho Blue) for yield.

The design goal is portfolio volatility < 1%: a heavy peg-anchored core means the
book barely moves even when individual venue rates swing. It trades a little
absolute yield for a smooth, dependable income stream — the profile a
capital-preservation / family-income mandate wants.

Target weights (the strategy's proposal)
-----------------------------------------
  sky_susds    50%   T1   income anchor, low vol
  morpho_blue  20%   T2   yield boost
  aave_v3      20%   T1   safety / liquidity
  compound_v3   5%   T1   diversifier
  cash          5%        dry powder (RiskPolicy min buffer)

Expected APY = 0.50·4.20 + 0.20·6.87 + 0.20·3.64 + 0.05·3.78 ≈ 4.39%

NOTE ON CAPS: the 50% Sky anchor exceeds the RiskPolicy per-protocol T1 cap
(40%). S61 is advisory — it emits a *target* weight map; the deterministic
RiskPolicy gate retains final authority and will trim Sky to its 40% ceiling
before any real allocation. `get_policy_capped_weights()` exposes that trimmed
view for callers that want the post-gate profile. `approved=False` from
RiskPolicy is never overridden.

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.

Date: 2026-06-21
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S61"
STRATEGY_NAME = "Hybrid Income Shield"
TIER          = "T1"
DESCRIPTION   = (
    "Hybrid Income Shield: income-first, low-volatility book anchored 50% in Sky "
    "sUSDS (near-constant peg, mean 4.20%) shielded by Aave 20% + Compound 5% (T1 "
    "safety) and boosted by Morpho Blue 20% (T2), 5% cash. Targets <1% portfolio "
    "volatility for a capital-preservation / family-income mandate. Expected ~4.39% "
    "APY. Advisory-only; RiskPolicy gate trims the 50% Sky anchor to its 40% cap."
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

# Reference APYs (%) — DeFiLlama 365-day means (2025-06→2026-06).
REFERENCE_APY: Dict[str, float] = {
    "sky_susds":   4.20,
    "morpho_blue": 6.87,
    "aave_v3":     3.64,
    "compound_v3": 3.78,
}

# The strategy's target weight proposal (sums to 1.0 incl. cash).
TARGET_WEIGHTS: Dict[str, float] = {
    "sky_susds":   0.50,
    "morpho_blue": 0.20,
    "aave_v3":     0.20,
    "compound_v3": 0.05,
    CASH_KEY:      0.05,
}

# ─── RiskPolicy caps (advisory view) ──────────────────────────────────────────

PER_PROTOCOL_CAP: Dict[str, float] = {"T1": 0.40, "T2": 0.20}
T2_TOTAL_CAP:     float = 0.50   # ADR-019
CASH_BUFFER:      float = 0.05

# ─── Targets / risk ───────────────────────────────────────────────────────────

TARGET_APY_MIN:   float = 4.0
TARGET_APY_MAX:   float = 5.0
RISK_SCORE:       float = 0.22   # low — peg-anchored income book
MAX_DRAWDOWN_PCT: float = 2.0


def _cap_for(protocol: str) -> float:
    return PER_PROTOCOL_CAP.get(PROTOCOL_TIERS.get(protocol, "T2"), 0.20)


class S61HybridIncomeShield:
    """S61 — Hybrid Income Shield (peg-anchored, income-first, low vol)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def _apy_of(self, p: str, apy_map: Dict[str, float]) -> float:
        v = apy_map.get(p)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
            return float(v)
        return REFERENCE_APY.get(p, 0.0)

    def get_weights(self) -> Dict[str, float]:
        """The strategy's target weight proposal (sums to 1.0)."""
        return {p: round(w, 6) for p, w in TARGET_WEIGHTS.items()}

    def get_policy_capped_weights(self) -> Dict[str, float]:
        """Target weights with per-protocol caps applied; freed weight → cash.

        Shows the post-RiskPolicy-gate profile (Sky 50% → 40%). T2 total cap is
        also enforced. The trimmed mass is held as cash (conservative)."""
        weights: Dict[str, float] = {}
        for p, w in TARGET_WEIGHTS.items():
            if p == CASH_KEY:
                continue
            weights[p] = min(w, _cap_for(p))
        # enforce T2 aggregate cap
        t2_total = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T2")
        if t2_total > T2_TOTAL_CAP and t2_total > 0:
            scale = T2_TOTAL_CAP / t2_total
            weights = {p: (w * scale if PROTOCOL_TIERS.get(p) == "T2" else w)
                       for p, w in weights.items()}
        deployed = sum(weights.values())
        weights[CASH_KEY] = round(max(CASH_BUFFER, 1.0 - deployed), 6)
        return {p: round(w, 6) for p, w in weights.items()}

    def get_allocation(self, capital_usd: float) -> Dict[str, float]:
        """Target USD allocation per venue (uses the proposal weights)."""
        if capital_usd <= 0.0:
            return {}
        return {p: round(capital_usd * w, 6) for p, w in self.get_weights().items()}

    def get_expected_apy(self, apy_map: Optional[Dict[str, float]] = None) -> float:
        """Weighted expected APY (%) of the proposed book (cash earns 0)."""
        apy_map = apy_map or {}
        weighted = 0.0
        for p, w in self.get_weights().items():
            if p == CASH_KEY:
                continue
            weighted += w * self._apy_of(p, apy_map)
        return round(weighted, 4)

    def get_risk_summary(self) -> Dict:
        w = self.get_weights()
        t1 = sum(v for p, v in w.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(v for p, v in w.items() if PROTOCOL_TIERS.get(p) == "T2")
        return {
            "strategy_id":      STRATEGY_ID,
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "cash_weight_pct":  round(w.get(CASH_KEY, 0.0) * 100.0, 2),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        apy_map: Optional[Dict[str, float]] = None,
    ) -> Dict:
        apy_map = apy_map or {}
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
        weights = self.get_weights()
        apy = self.get_expected_apy(apy_map)
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "weights":                   weights,
            "allocation":                {p: round(capital_usd * w, 6) for p, w in weights.items()},
            "policy_capped_weights":     self.get_policy_capped_weights(),
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "risk_summary":              self.get_risk_summary(),
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
            "protocol_tiers":   {p: PROTOCOL_TIERS[p] for p in PROTOCOLS},
            "reference_apy":    dict(REFERENCE_APY),
            "target_weights":   dict(TARGET_WEIGHTS),
            "per_protocol_cap": dict(PER_PROTOCOL_CAP),
            "t2_total_cap":     T2_TOTAL_CAP,
            "cash_buffer":      CASH_BUFFER,
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
            module="spa_core.strategies.s61_hybrid_income_shield",
            handler_class="S61HybridIncomeShield",
            tags=["hybrid", "income", "low_vol", "sky", "shield", "capital_preservation",
                  "advisory", "s61"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S61HybridIncomeShield auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    strat = S61HybridIncomeShield()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
