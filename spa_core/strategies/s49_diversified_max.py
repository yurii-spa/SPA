"""
spa_core/strategies/s49_diversified_max.py — S49 Diversified Maximum

S49 Diversified Maximum
=======================
Maximum protocol diversification to minimise concentration risk: spread
capital across **seven** venues with **no single protocol above 20%**.
Deliberately sacrifices a little APY (~0.3pp vs the optimal concentrated
book) in exchange for the lowest single-protocol blast radius in the
tournament.

Target weights (sum = 100%, max 20% any single protocol):
  Aave V3     (T1, 20%)
  Compound V3 (T1, 20%)
  Sky sUSDS   (T1, 15%)
  Morpho Blue (T2, 15%)
  Fluid       (T2, 10%)
  Yearn V3    (T2, 10%)
  Euler V2    (T2, 10%)

Tier split: T1 = 55%, T2 = 45% (≤ 50% ADR-019 cap). Every T2 slot ≤ 20%
per-protocol cap; every T1 slot ≤ 40% cap. Fully RiskPolicy v1.0 compliant.

Expected blended APY (fallback levels):
  0.20*3.6 + 0.20*3.9 + 0.15*4.0 + 0.15*6.0 + 0.10*4.5 + 0.10*4.8 + 0.10*5.0
  = 0.72 + 0.78 + 0.60 + 0.90 + 0.45 + 0.48 + 0.50 = 4.43% ≈ 4.4%
(~0.3pp below a Morpho-concentrated book — the diversification premium.)

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
    PROTOCOL_TIER,
    PROTOCOL_RISK_SCORE,
    MIN_APY_ELIGIBLE,
    MAX_APY_ELIGIBLE,
    T2_TOTAL_CAP,
    T2_PER_PROTOCOL_CAP,
    T1_PER_PROTOCOL_CAP,
)

# ─── Strategy identity ────────────────────────────────────────────────────────

STRATEGY_ID   = "S49"
STRATEGY_NAME = "Diversified Maximum"
TIER          = "T2"
DESCRIPTION   = (
    "Maximum diversification across 7 venues, no single protocol >20%: "
    "Aave 20 / Compound 20 / Sky 15 / Morpho 15 / Fluid 10 / Yearn 10 / Euler 10. "
    "T1 55% / T2 45%. Blended APY ~4.4% (sacrifices ~0.3pp for low concentration)."
)

# ─── Weights (sum = 1.0, max 20% any single protocol) ─────────────────────────

WEIGHTS: Dict[str, float] = {
    "aave_v3":     0.20,
    "compound_v3": 0.20,
    "sky_susds":   0.15,
    "morpho_blue": 0.15,
    "fluid":       0.10,
    "yearn_v3":    0.10,
    "euler_v2":    0.10,
}

MAX_SINGLE_PROTOCOL: float = 0.20

# ─── Target metrics ───────────────────────────────────────────────────────────

TARGET_APY_PCT: float = 4.4
TARGET_APY_MIN: float = 3.5
TARGET_APY_MAX: float = 5.0
RISK_SCORE:     float = 0.33
MAX_DRAWDOWN_PCT: float = 5.0


class DiversifiedMaxStrategy(AdapterAPYMixin):
    """S49 — Diversified Maximum: 7 venues, no single protocol >20%.

    Stdlib only, advisory/read-only. RiskPolicy approved=False is final.
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TIER           = TIER
    TARGET_APY_PCT = TARGET_APY_PCT
    RISK_SCORE     = RISK_SCORE
    MAX_SINGLE_PROTOCOL = MAX_SINGLE_PROTOCOL
    T2_TOTAL_CAP        = T2_TOTAL_CAP
    T2_PER_PROTOCOL_CAP = T2_PER_PROTOCOL_CAP
    T1_PER_PROTOCOL_CAP = T1_PER_PROTOCOL_CAP

    def __init__(self) -> None:
        self._simulate_history: List[Dict] = []
        self._load_adapters()

    def _adapter_keys(self) -> List[str]:
        return list(WEIGHTS.keys())

    # ── Diversification metrics ───────────────────────────────────────────────

    def get_hhi(self) -> float:
        """Herfindahl–Hirschman Index of the weight vector (0..1, lower=diverse)."""
        return round(sum(w * w for w in WEIGHTS.values()), 6)

    def effective_positions(self) -> float:
        """Inverse HHI — effective number of equally-weighted positions."""
        hhi = self.get_hhi()
        return round(1.0 / hhi, 4) if hhi > 0 else 0.0

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

    def get_risk_summary(self) -> Dict:
        t1 = sum(w for k, w in WEIGHTS.items() if PROTOCOL_TIER.get(k) == "T1")
        t2 = sum(w for k, w in WEIGHTS.items() if PROTOCOL_TIER.get(k) == "T2")
        max_weight = max(WEIGHTS.values())
        t2_per_protocol_ok = all(
            w <= T2_PER_PROTOCOL_CAP + 1e-9
            for k, w in WEIGHTS.items() if PROTOCOL_TIER.get(k) == "T2"
        )
        t1_per_protocol_ok = all(
            w <= T1_PER_PROTOCOL_CAP + 1e-9
            for k, w in WEIGHTS.items() if PROTOCOL_TIER.get(k) == "T1"
        )
        no_concentration = max_weight <= MAX_SINGLE_PROTOCOL + 1e-9
        adr_compliant = (
            t2 <= T2_TOTAL_CAP + 1e-9
            and t2_per_protocol_ok
            and t1_per_protocol_ok
            and no_concentration
        )
        return {
            "risk_score":          RISK_SCORE,
            "t1_weight_pct":       round(t1 * 100.0, 2),
            "t2_weight_pct":       round(t2 * 100.0, 2),
            "max_single_pct":      round(max_weight * 100.0, 2),
            "no_concentration":    no_concentration,
            "hhi":                 self.get_hhi(),
            "effective_positions": self.effective_positions(),
            "t2_per_protocol_ok":  t2_per_protocol_ok,
            "t1_per_protocol_ok":  t1_per_protocol_ok,
            "adr_compliant":       adr_compliant,
            "risk_note": (
                f"S49 Diversified Max: 7 venues, max single {max_weight*100:.0f}% ≤ 20%. "
                f"T1={t1*100:.0f}% T2={t2*100:.0f}% (≤ 50% cap). "
                f"HHI={self.get_hhi():.3f}, {self.effective_positions():.1f} effective positions. "
                f"Fully RiskPolicy v1.0 compliant."
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
                "weight":   w,
                "tier":     PROTOCOL_TIER.get(key, "?"),
                "eligible": eligible,
                "apy":      self._get_adapter_apy(key),
                "loaded":   key in getattr(self, "_adapters", {}),
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
            "hhi":            self.get_hhi(),
            "effective_positions": self.effective_positions(),
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
                "tier":             PROTOCOL_TIER.get(key, "?"),
                "risk_score":       PROTOCOL_RISK_SCORE.get(key, 0.0),
            }
        result = {
            "total_capital":             capital_usd,
            "allocation":                allocation,
            "deployed_usd":              round(deployed, 4),
            "cash_usd":                  round(capital_usd - deployed, 4),
            "expected_annual_yield_usd": round(total_yield, 4),
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
            "max_single_protocol": MAX_SINGLE_PROTOCOL,
            "hhi":              self.get_hhi(),
            "effective_positions": self.effective_positions(),
            "target_apy_pct":   TARGET_APY_PCT,
            "target_apy_min":   TARGET_APY_MIN,
            "target_apy_max":   TARGET_APY_MAX,
            "risk_score":       RISK_SCORE,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "min_apy_eligible": MIN_APY_ELIGIBLE,
            "max_apy_eligible": MAX_APY_ELIGIBLE,
            "expected_apy":     self.get_expected_apy(),
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
            risk_tier="T2",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s49_diversified_max",
            handler_class="DiversifiedMaxStrategy",
            tags=[
                "s49", "diversified", "max_diversification", "low_concentration",
                "income", "aave_v3", "compound_v3", "sky_susds", "morpho_blue",
                "fluid", "yearn_v3", "euler_v2", "adr_019_compliant",
            ],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "DiversifiedMaxStrategy auto-registration failed: %s", exc
        )


_register()
