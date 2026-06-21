"""
spa_core/strategies/s65_session_champion.py — S65 Session Champion

S65: Session Champion
=====================
The hand-curated "best of session" book — the single allocation that the night's
research converged on as the strongest risk-adjusted income profile across the
whitelisted universe. It blends a peg-anchored income core (Sky) with two
high-mean T2 boosters (Morpho Blue, Fluid USDC) and a T1 safety sleeve
(Aave, Compound), capped to stay inside policy.

Target weights (the curated champion)
-------------------------------------
  sky_susds    25%   T1   4.20%   lowest-vol income anchor
  morpho_blue  20%   T2   6.87%   curated-vault yield booster
  fluid        20%   T2   6.22%   live high-yield USDC venue
  aave_v3      20%   T1   3.64%   T1 baseline / liquidity
  compound_v3  10%   T1   3.78%   T1 diversifier
  cash          5%                dry powder

Expected APY = 0.25·4.20 + 0.20·6.87 + 0.20·6.22 + 0.20·3.64 + 0.10·3.78 ≈ 4.77%
— the highest expected-yield book in the session while staying policy-compliant.

Policy compliance: T2 total = Morpho 20% + Fluid 20% = 40% ≤ 50% cap (ADR-019);
every venue is at or under its per-protocol cap (T1 ≤ 40%, T2 ≤ 20%); cash 5%
meets the minimum buffer. Unlike S61–S63 this book is constructed to satisfy the
RiskPolicy caps as-is, so the gate passes it through unmodified.

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
The RiskPolicy gate retains final authority; `approved=False` is never overridden.

Date: 2026-06-21
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S65"
STRATEGY_NAME = "Session Champion"
TIER          = "T2"
DESCRIPTION   = (
    "Session Champion: the hand-curated best-of-session book — Sky 25% (income "
    "anchor) + Morpho Blue 20% + Fluid 20% (T2 yield boosters) + Aave 20% + "
    "Compound 10% (T1 sleeve) + 5% cash. Highest expected-yield book of the "
    "session (~4.77% APY) while fully policy-compliant: T2 total 40% ≤ 50% cap, "
    "all venues within per-protocol caps. Advisory-only, deterministic, stdlib."
)

CASH_KEY = "cash"

# ─── Universe ─────────────────────────────────────────────────────────────────

PROTOCOLS = ["sky_susds", "morpho_blue", "fluid", "aave_v3", "compound_v3"]

PROTOCOL_TIERS: Dict[str, str] = {
    "sky_susds":   "T1",
    "morpho_blue": "T2",
    "fluid":       "T2",
    "aave_v3":     "T1",
    "compound_v3": "T1",
    CASH_KEY:      "CASH",
}

# Reference APYs (%) — Sky/Morpho/Aave/Compound 365-day means; Fluid current live.
REFERENCE_APY: Dict[str, float] = {
    "sky_susds":   4.20,
    "morpho_blue": 6.87,
    "fluid":       6.22,
    "aave_v3":     3.64,
    "compound_v3": 3.78,
}

# The curated champion weights (sums to 1.0 incl. cash; policy-compliant as-is).
TARGET_WEIGHTS: Dict[str, float] = {
    "sky_susds":   0.25,
    "morpho_blue": 0.20,
    "fluid":       0.20,
    "aave_v3":     0.20,
    "compound_v3": 0.10,
    CASH_KEY:      0.05,
}

# ─── RiskPolicy caps (for compliance assertions) ──────────────────────────────

PER_PROTOCOL_CAP: Dict[str, float] = {"T1": 0.40, "T2": 0.20}
T2_TOTAL_CAP:     float = 0.50   # ADR-019
CASH_BUFFER:      float = 0.05

# ─── Targets / risk ───────────────────────────────────────────────────────────

TARGET_APY_MIN:   float = 4.5
TARGET_APY_MAX:   float = 5.2
RISK_SCORE:       float = 0.38
MAX_DRAWDOWN_PCT: float = 3.5


def _cap_for(protocol: str) -> float:
    return PER_PROTOCOL_CAP.get(PROTOCOL_TIERS.get(protocol, "T2"), 0.20)


def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


class S65SessionChampion:
    """S65 — Session Champion (curated best-of-session, policy-compliant book)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def _apy_of(self, p: str, apy_map: Dict[str, float]) -> float:
        v = apy_map.get(p)
        return float(v) if _is_number(v) else REFERENCE_APY.get(p, 0.0)

    def get_weights(self) -> Dict[str, float]:
        return {p: round(w, 6) for p, w in TARGET_WEIGHTS.items()}

    def is_policy_compliant(self) -> bool:
        """True iff the curated book satisfies all RiskPolicy caps as-is."""
        w = TARGET_WEIGHTS
        for p, v in w.items():
            if p == CASH_KEY:
                continue
            if v > _cap_for(p) + 1e-9:
                return False
        t2_total = sum(v for p, v in w.items() if PROTOCOL_TIERS.get(p) == "T2")
        if t2_total > T2_TOTAL_CAP + 1e-9:
            return False
        if w.get(CASH_KEY, 0.0) < CASH_BUFFER - 1e-9:
            return False
        return abs(sum(w.values()) - 1.0) < 1e-6

    def get_allocation(self, capital_usd: float) -> Dict[str, float]:
        if capital_usd <= 0.0:
            return {}
        return {p: round(capital_usd * w, 6) for p, w in self.get_weights().items()}

    def get_expected_apy(self, apy_map: Optional[Dict[str, float]] = None) -> float:
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
            "strategy_id":         STRATEGY_ID,
            "risk_score":          RISK_SCORE,
            "t1_weight_pct":       round(t1 * 100.0, 2),
            "t2_weight_pct":       round(t2 * 100.0, 2),
            "cash_weight_pct":     round(w.get(CASH_KEY, 0.0) * 100.0, 2),
            "policy_compliant":    self.is_policy_compliant(),
            "max_drawdown_pct":    MAX_DRAWDOWN_PCT,
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
                "policy_compliant":          self.is_policy_compliant(),
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
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "policy_compliant":          self.is_policy_compliant(),
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
            module="spa_core.strategies.s65_session_champion",
            handler_class="S65SessionChampion",
            tags=["champion", "curated", "best_of_session", "fluid", "morpho",
                  "sky", "policy_compliant", "advisory", "s65"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S65SessionChampion auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    strat = S65SessionChampion()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
