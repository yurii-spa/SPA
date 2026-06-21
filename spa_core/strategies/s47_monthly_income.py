"""
spa_core/strategies/s47_monthly_income.py — S47 Monthly Income Optimizer

S47 Monthly Income Optimizer
============================
Tilts the all-T1 book toward the **most predictable** yield sources to
maximise *steady, forecastable* monthly income on the $100k virtual book —
not raw APY. Predictability beats peak yield here: Sky's Savings Rate is
the smoothest (APY 3.60–4.75% range, ~0.022% daily vol), so it gets the
largest weight; Compound is the next-smoothest; Aave is the baseline.

Target weights (sum = 100%, all T1):
  Sky sUSDS    (T1, 40%) — most predictable APY (3.60–4.75%, 0.022% vol)
  Compound V3  (T1, 35%) — second-most-predictable
  Aave V3      (T1, 25%) — baseline blue-chip lending

Expected blended APY (fallback Sky 4.0 / Compound 3.9 / Aave 3.6):
  0.40*4.0 + 0.35*3.9 + 0.25*3.6 = 1.6 + 1.365 + 0.9 = 3.865% ≈ 3.9%

Expected monthly income on $100k:
  100_000 * 0.03865 / 12 ≈ $322/month  (brief target ≈ $325/month)

Risk: very low (100% T1, predictability-weighted).

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy cannot be overridden
  - atomic data/ writes only — this module writes nothing

Date: 2026-06-21 (S46–S50 income batch)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from spa_core.strategies._income_common import (
    AdapterAPYMixin,
    PROTOCOL_RISK_SCORE,
    MIN_APY_ELIGIBLE,
    MAX_APY_ELIGIBLE,
    T1_PER_PROTOCOL_CAP,
)

# ─── Strategy identity ────────────────────────────────────────────────────────

STRATEGY_ID   = "S47"
STRATEGY_NAME = "Monthly Income Optimizer"
TIER          = "T1"
DESCRIPTION   = (
    "Predictability-weighted all-T1 income engine: Sky sUSDS 40% (smoothest) "
    "+ Compound V3 35% + Aave V3 25%. Blended APY ~3.9% → ~$322/month on $100k. "
    "Maximises steady monthly income, not peak APY. Very low risk."
)

# ─── Weights (sum = 1.0, all T1) ──────────────────────────────────────────────

WEIGHTS: Dict[str, float] = {
    "sky_susds":   0.40,
    "compound_v3": 0.35,
    "aave_v3":     0.25,
}

# Predictability rank (lower daily vol = more predictable). Advisory metadata.
PREDICTABILITY: Dict[str, float] = {
    "sky_susds":   0.022,   # %/day vol — smoothest
    "compound_v3": 0.05,
    "aave_v3":     0.08,
}

# ─── Target metrics ───────────────────────────────────────────────────────────

TARGET_APY_PCT: float = 3.9
TARGET_APY_MIN: float = 3.0
TARGET_APY_MAX: float = 4.5
RISK_SCORE:     float = 0.21
MAX_DRAWDOWN_PCT: float = 5.0


class MonthlyIncomeStrategy(AdapterAPYMixin):
    """S47 — Monthly Income Optimizer: predictability-weighted all-T1.

    Stdlib only, advisory/read-only. RiskPolicy approved=False is final.
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TIER           = TIER
    TARGET_APY_PCT = TARGET_APY_PCT
    RISK_SCORE     = RISK_SCORE
    T1_PER_PROTOCOL_CAP = T1_PER_PROTOCOL_CAP

    def __init__(self) -> None:
        self._simulate_history: List[Dict] = []
        self._load_adapters()

    def _adapter_keys(self) -> List[str]:
        return list(WEIGHTS.keys())

    # ── Public API ────────────────────────────────────────────────────────────

    def get_allocation(self, capital_usd: float) -> Dict[str, float]:
        if capital_usd <= 0.0:
            return {k: 0.0 for k in WEIGHTS}
        out: Dict[str, float] = {}
        for key, w in WEIGHTS.items():
            if self._is_eligible(key):
                out[key] = round(capital_usd * w, 6)
        return out

    def get_expected_apy(self) -> float:
        weighted = 0.0
        for key, w in WEIGHTS.items():
            if self._is_eligible(key):
                weighted += w * self._get_adapter_apy(key)
        return round(weighted, 4)

    def get_monthly_income(self, capital_usd: float) -> float:
        """Expected monthly income (USD) = capital * blended_apy / 100 / 12."""
        if capital_usd <= 0.0:
            return 0.0
        return round(capital_usd * (self.get_expected_apy() / 100.0) / 12.0, 2)

    def get_annual_income(self, capital_usd: float) -> float:
        if capital_usd <= 0.0:
            return 0.0
        return round(capital_usd * (self.get_expected_apy() / 100.0), 2)

    def get_risk_summary(self) -> Dict:
        t1 = sum(WEIGHTS.values())
        t1_per_protocol_ok = all(w <= T1_PER_PROTOCOL_CAP + 1e-9 for w in WEIGHTS.values())
        return {
            "risk_score":          RISK_SCORE,
            "t1_weight_pct":       round(t1 * 100.0, 2),
            "t2_weight_pct":       0.0,
            "t1_per_protocol_ok":  t1_per_protocol_ok,
            "no_t2_exposure":      True,
            "adr_compliant":       t1_per_protocol_ok,
            "predictability_rank": dict(PREDICTABILITY),
            "risk_note": (
                f"S47 Monthly Income: 100% T1, predictability-weighted "
                f"(Sky 40% smoothest / Compound 35% / Aave 25%). Very low risk."
            ),
        }

    def get_health(self) -> Dict:
        slots_info: Dict[str, Dict] = {}
        eligible_count = 0
        for key, w in WEIGHTS.items():
            eligible = self._is_eligible(key)
            if eligible:
                eligible_count += 1
            slots_info[key] = {
                "weight":         w,
                "tier":           "T1",
                "eligible":       eligible,
                "apy":            self._get_adapter_apy(key),
                "predictability": PREDICTABILITY.get(key),
                "loaded":         key in getattr(self, "_adapters", {}),
            }
        if eligible_count == len(WEIGHTS):
            status = "ok"
        elif eligible_count == 0:
            status = "critical"
        else:
            status = "degraded"
        return {
            "strategy_id":    STRATEGY_ID,
            "name":           STRATEGY_NAME,
            "eligible_slots": eligible_count,
            "total_slots":    len(WEIGHTS),
            "slots":          slots_info,
            "expected_apy":   self.get_expected_apy(),
            "target_apy":     TARGET_APY_PCT,
            "monthly_income_100k": self.get_monthly_income(100_000.0),
            "risk_score":     RISK_SCORE,
            "overall_status": status,
        }

    def simulate(self, capital_usd: float) -> Dict:
        allocation = self.get_allocation(capital_usd)
        if not allocation or capital_usd <= 0.0:
            return {
                "total_capital":             capital_usd,
                "allocation":                {},
                "deployed_usd":              0.0,
                "cash_usd":                  max(capital_usd, 0.0),
                "expected_annual_yield_usd": 0.0,
                "expected_monthly_income_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "slot_results":              {},
                "risk_summary":              self.get_risk_summary(),
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        total_yield = 0.0
        deployed = 0.0
        slot_results: Dict[str, Dict] = {}
        for key, amount in allocation.items():
            apy = self._get_adapter_apy(key)
            annual_yield = amount * (apy / 100.0)
            total_yield += annual_yield
            deployed += amount
            slot_results[key] = {
                "amount_usd":       round(amount, 4),
                "apy_pct":          apy,
                "annual_yield_usd": round(annual_yield, 4),
                "monthly_yield_usd": round(annual_yield / 12.0, 4),
                "tier":             "T1",
                "risk_score":       PROTOCOL_RISK_SCORE.get(key, 0.0),
            }
        result = {
            "total_capital":             capital_usd,
            "allocation":                allocation,
            "deployed_usd":              round(deployed, 4),
            "cash_usd":                  round(capital_usd - deployed, 4),
            "expected_annual_yield_usd": round(total_yield, 4),
            "expected_monthly_income_usd": round(total_yield / 12.0, 4),
            "expected_apy_pct":          round(self.get_expected_apy(), 4),
            "status":                    "ok",
            "slot_results":              slot_results,
            "risk_summary":              self.get_risk_summary(),
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }
        self._simulate_history.append(result)
        if len(self._simulate_history) > 365:
            self._simulate_history = self._simulate_history[-365:]
        return result

    def to_dict(self) -> Dict:
        return {
            "strategy_id":      STRATEGY_ID,
            "strategy_name":    STRATEGY_NAME,
            "tier":             TIER,
            "description":      DESCRIPTION,
            "weights":          dict(WEIGHTS),
            "predictability":   dict(PREDICTABILITY),
            "target_apy_pct":   TARGET_APY_PCT,
            "target_apy_min":   TARGET_APY_MIN,
            "target_apy_max":   TARGET_APY_MAX,
            "risk_score":       RISK_SCORE,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "min_apy_eligible": MIN_APY_ELIGIBLE,
            "max_apy_eligible": MAX_APY_ELIGIBLE,
            "expected_apy":     self.get_expected_apy(),
            "monthly_income_100k": self.get_monthly_income(100_000.0),
            "health":           self.get_health(),
            "risk_summary":     self.get_risk_summary(),
            "timestamp":        datetime.now(timezone.utc).isoformat(),
        }


# ─── Auto-registration ────────────────────────────────────────────────────────

def _register() -> None:
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier="T1",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s47_monthly_income",
            handler_class="MonthlyIncomeStrategy",
            tags=[
                "s47", "monthly_income", "t1", "predictable", "income",
                "sky_susds", "compound_v3", "aave_v3", "low_risk",
            ],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "MonthlyIncomeStrategy auto-registration failed: %s", exc
        )


_register()
