"""
spa_core/strategies/s48_utilization_aware.py — S48 Utilization-Aware

S48 Utilization-Aware
=====================
Adapts the allocation to the Aave USDC lending **utilization regime**,
using the live Aave APY as a stdlib proxy for utilization (high APY ⇒ high
utilization ⇒ borrowers paying up ⇒ worth concentrating; low APY ⇒ slack
demand ⇒ rotate to the higher-yield Morpho Blue T2 venue).

Regimes (proxy = current Aave V3 USDC APY, percent):
  HIGH   (util >85%, Aave APY > 7%):  concentrate 50% Aave
                                      → Aave 50 / Compound 30 / Sky 20
  MEDIUM (util 70–85%, Aave 4–7%):    balanced T1
                                      → Aave 33⅓ / Compound 33⅓ / Sky 33⅓
  LOW    (util <70%, Aave APY < 4%):  shift 30% into Morpho Blue (T2)
                                      → Morpho 30 / Aave 25 / Compound 25 / Sky 20

Expected APY: 4.2–4.8% adaptive. At fallback levels (Aave 3.6% → LOW regime)
the book yields:
  0.30*6.0 + 0.25*3.6 + 0.25*3.9 + 0.20*4.0 = 1.8 + 0.9 + 0.975 + 0.8 = 4.475% ≈ 4.5%

Compliance: only the LOW regime touches T2 (Morpho Blue 30%) — above the 20%
T2 per-protocol cap, so the LOW allocation is RESEARCH/advisory and the live
allocator/RiskPolicy gate will trim Morpho to ≤20% before any rebalance. HIGH
and MEDIUM regimes are 100% T1 and fully policy-compliant.

Rules:
  - stdlib only, read-only / advisory, LLM FORBIDDEN
  - approved=False from RiskPolicy cannot be overridden
  - atomic data/ writes only — this module writes nothing

Date: 2026-06-21 (S46–S50 income batch)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from spa_core.strategies._income_common import (
    AdapterAPYMixin,
    PROTOCOL_TIER,
    PROTOCOL_RISK_SCORE,
    MIN_APY_ELIGIBLE,
    MAX_APY_ELIGIBLE,
    T2_PER_PROTOCOL_CAP,
)

# ─── Strategy identity ────────────────────────────────────────────────────────

STRATEGY_ID   = "S48"
STRATEGY_NAME = "Utilization-Aware"
TIER          = "T2"   # LOW regime can hold Morpho Blue (T2)
DESCRIPTION   = (
    "Regime-adaptive: uses live Aave USDC APY as a utilization proxy. "
    "HIGH util (>7%) → 50% Aave; MEDIUM (4–7%) → balanced 33/33/33 T1; "
    "LOW (<4%) → shift 30% to Morpho Blue. Adaptive APY 4.2–4.8%."
)

# ─── Regime thresholds (Aave APY %, utilization proxy) ────────────────────────

HIGH_UTIL_APY: float = 7.0    # Aave APY above → high utilization (>85%)
LOW_UTIL_APY:  float = 4.0    # Aave APY below → low utilization (<70%)

# ─── Per-regime weight tables (each sums to 1.0) ──────────────────────────────

WEIGHTS_HIGH: Dict[str, float] = {
    "aave_v3":     0.50,
    "compound_v3": 0.30,
    "sky_susds":   0.20,
}
WEIGHTS_MEDIUM: Dict[str, float] = {
    "aave_v3":     1.0 / 3.0,
    "compound_v3": 1.0 / 3.0,
    "sky_susds":   1.0 / 3.0,
}
WEIGHTS_LOW: Dict[str, float] = {
    "morpho_blue": 0.30,
    "aave_v3":     0.25,
    "compound_v3": 0.25,
    "sky_susds":   0.20,
}

# All slots this strategy may ever touch (for adapter loading).
_ALL_KEYS: List[str] = ["aave_v3", "compound_v3", "sky_susds", "morpho_blue"]

# ─── Target metrics ───────────────────────────────────────────────────────────

TARGET_APY_PCT: float = 4.5
TARGET_APY_MIN: float = 3.5
TARGET_APY_MAX: float = 5.5
RISK_SCORE:     float = 0.30
MAX_DRAWDOWN_PCT: float = 5.0


class UtilizationAwareStrategy(AdapterAPYMixin):
    """S48 — Utilization-Aware: Aave-APY-proxied regime allocation.

    Stdlib only, advisory/read-only. RiskPolicy approved=False is final.
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TIER           = TIER
    TARGET_APY_PCT = TARGET_APY_PCT
    RISK_SCORE     = RISK_SCORE
    HIGH_UTIL_APY  = HIGH_UTIL_APY
    LOW_UTIL_APY   = LOW_UTIL_APY
    T2_PER_PROTOCOL_CAP = T2_PER_PROTOCOL_CAP

    def __init__(self) -> None:
        self._simulate_history: List[Dict] = []
        self._load_adapters()

    def _adapter_keys(self) -> List[str]:
        return list(_ALL_KEYS)

    # ── Regime detection ──────────────────────────────────────────────────────

    def get_regime(self, aave_apy: Optional[float] = None) -> str:
        """Return 'high' | 'medium' | 'low' from the Aave-APY utilization proxy."""
        apy = aave_apy if aave_apy is not None else self._get_adapter_apy("aave_v3")
        if apy > HIGH_UTIL_APY:
            return "high"
        if apy < LOW_UTIL_APY:
            return "low"
        return "medium"

    def get_weights(self, aave_apy: Optional[float] = None) -> Dict[str, float]:
        """Active weight table for the current (or supplied-proxy) regime."""
        regime = self.get_regime(aave_apy)
        if regime == "high":
            return dict(WEIGHTS_HIGH)
        if regime == "low":
            return dict(WEIGHTS_LOW)
        return dict(WEIGHTS_MEDIUM)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_allocation(self, capital_usd: float, aave_apy: Optional[float] = None) -> Dict[str, float]:
        weights = self.get_weights(aave_apy)
        if capital_usd <= 0.0:
            return {k: 0.0 for k in weights}
        out: Dict[str, float] = {}
        for key, w in weights.items():
            if self._is_eligible(key):
                out[key] = round(capital_usd * w, 6)
        return out

    def get_expected_apy(self, aave_apy: Optional[float] = None) -> float:
        weights = self.get_weights(aave_apy)
        weighted = 0.0
        for key, w in weights.items():
            if self._is_eligible(key):
                weighted += w * self._get_adapter_apy(key)
        return round(weighted, 4)

    def get_risk_summary(self, aave_apy: Optional[float] = None) -> Dict:
        weights = self.get_weights(aave_apy)
        regime = self.get_regime(aave_apy)
        t1 = sum(w for k, w in weights.items() if PROTOCOL_TIER.get(k) == "T1")
        t2 = sum(w for k, w in weights.items() if PROTOCOL_TIER.get(k) == "T2")
        t2_per_protocol_ok = all(
            w <= T2_PER_PROTOCOL_CAP + 1e-9
            for k, w in weights.items() if PROTOCOL_TIER.get(k) == "T2"
        )
        return {
            "risk_score":         RISK_SCORE,
            "regime":             regime,
            "t1_weight_pct":      round(t1 * 100.0, 2),
            "t2_weight_pct":      round(t2 * 100.0, 2),
            "t2_per_protocol_ok": t2_per_protocol_ok,
            # LOW regime intentionally exceeds the 20% T2 cap → advisory only
            "adr_compliant":      t2_per_protocol_ok,
            "research_only":      not t2_per_protocol_ok,
            "risk_note": (
                f"S48 Utilization-Aware [{regime}]: T1={t1*100:.0f}% T2={t2*100:.0f}%. "
                + ("Morpho 30% > 20% T2 cap → LOW regime is advisory; allocator trims."
                   if not t2_per_protocol_ok else "Fully policy-compliant.")
            ),
        }

    def get_health(self, aave_apy: Optional[float] = None) -> Dict:
        weights = self.get_weights(aave_apy)
        slots_info: Dict[str, Dict] = {}
        eligible_count = 0
        for key, w in weights.items():
            eligible = self._is_eligible(key)
            if eligible:
                eligible_count += 1
            slots_info[key] = {
                "weight":   round(w, 6),
                "tier":     PROTOCOL_TIER.get(key, "?"),
                "eligible": eligible,
                "apy":      self._get_adapter_apy(key),
                "loaded":   key in getattr(self, "_adapters", {}),
            }
        if eligible_count == len(weights):
            status = "ok"
        elif eligible_count == 0:
            status = "critical"
        else:
            status = "degraded"
        return {
            "strategy_id":    STRATEGY_ID,
            "name":           STRATEGY_NAME,
            "regime":         self.get_regime(aave_apy),
            "eligible_slots": eligible_count,
            "total_slots":    len(weights),
            "slots":          slots_info,
            "expected_apy":   self.get_expected_apy(aave_apy),
            "target_apy":     TARGET_APY_PCT,
            "risk_score":     RISK_SCORE,
            "overall_status": status,
        }

    def simulate(self, capital_usd: float, aave_apy: Optional[float] = None) -> Dict:
        allocation = self.get_allocation(capital_usd, aave_apy)
        regime = self.get_regime(aave_apy)
        if not allocation or capital_usd <= 0.0:
            return {
                "total_capital":             capital_usd,
                "regime":                    regime,
                "allocation":                {},
                "deployed_usd":              0.0,
                "cash_usd":                  max(capital_usd, 0.0),
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "slot_results":              {},
                "risk_summary":              self.get_risk_summary(aave_apy),
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
            "regime":                    regime,
            "allocation":                allocation,
            "deployed_usd":              round(deployed, 4),
            "cash_usd":                  round(capital_usd - deployed, 4),
            "expected_annual_yield_usd": round(total_yield, 4),
            "expected_apy_pct":          round(self.get_expected_apy(aave_apy), 4),
            "status":                    "ok",
            "slot_results":              slot_results,
            "risk_summary":              self.get_risk_summary(aave_apy),
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
            "regime":           self.get_regime(),
            "weights_high":     dict(WEIGHTS_HIGH),
            "weights_medium":   {k: round(v, 6) for k, v in WEIGHTS_MEDIUM.items()},
            "weights_low":      dict(WEIGHTS_LOW),
            "high_util_apy":    HIGH_UTIL_APY,
            "low_util_apy":     LOW_UTIL_APY,
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
            module="spa_core.strategies.s48_utilization_aware",
            handler_class="UtilizationAwareStrategy",
            tags=[
                "s48", "utilization_aware", "regime", "adaptive", "income",
                "aave_v3", "compound_v3", "sky_susds", "morpho_blue",
            ],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "UtilizationAwareStrategy auto-registration failed: %s", exc
        )


_register()
