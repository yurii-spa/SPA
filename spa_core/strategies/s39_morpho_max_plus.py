"""
spa_core/strategies/s39_morpho_max_plus.py — S39 Morpho Max+ (cap-raise variant)

S39 Morpho Max+ Strategy  (ADVISORY / RESEARCH-ONLY under current policy)
=========================================================================
S39 is S38 pushed one step further: it allocates **25%** to Morpho Blue —
ABOVE the current RiskPolicy v1.0 T2 single-protocol cap of 20%.

⚠️  Under the CURRENT RiskPolicy v1.0 this allocation is NON-COMPLIANT.
    `get_risk_summary()["adr_compliant"]` returns **False** and the
    RiskPolicy gate in cycle_runner would BLOCK it (approved=False is final
    and cannot be overridden). S39 exists to quantify the upside of raising
    the T2 single-protocol cap to 25% — it is a research candidate for a
    future ADR, NOT a deployable allocation today.

Target weights (sum = 100%, contingent on cap raise to 25%):
  Morpho Blue   (T2, 25%) — requires ADR raising T2 cap 20%→25%, ~6.0% APY
  Euler V2      (T2, 20%) — second T2 venue, ~5.0% APY
  Aave V3       (T1, 30%) — T1 anchor, ~3.1% APY
  Compound V3   (T1, 20%) — T1 anchor, ~3.3% APY
  Cash          (    5%)  — min cash buffer

Compliance (RiskPolicy v1.0 AS-IS):
  T2 total          = 45%  ≤ 50%  cap (ADR-019)            → OK
  T2 per-protocol   = 25%  >  20% cap                      → VIOLATION
  adr_compliant     = False  (pending cap-raise ADR)

Expected blended APY (only realisable if/when the cap is raised):
  Conservative (nominal):
    0.25*6.0 + 0.20*5.0 + 0.30*3.1 + 0.20*3.3 + 0.05*0.0
    = 1.50 + 1.00 + 0.93 + 0.66 = 4.09%  ≈ 4.1%
  Using 365-day historical means (Morpho 6.87 / Aave 3.65 / Compound 3.79):
    0.25*6.87 + 0.20*5.0 + 0.30*3.65 + 0.20*3.79
    = 1.7175 + 1.00 + 1.095 + 0.758 ≈ 4.57%

Delta vs S38: +~0.15pp nominal (3.95% → 4.10%) for +5pp Morpho concentration.
The marginal yield gain must be weighed against higher single-protocol risk —
exactly the trade-off the cap-raise ADR would have to justify.

Rules: identical to S38 — stdlib only, read-only/advisory, LLM FORBIDDEN,
RiskPolicy approved=False is final, no disk writes.

Date: 2026-06-21 (MP-1247)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

# ─── Strategy identity ────────────────────────────────────────────────────────

STRATEGY_ID   = "S39"
STRATEGY_NAME = "Morpho Max+ (cap-raise research)"
TIER          = "T2"
DESCRIPTION   = (
    "Morpho Max+ (RESEARCH): Morpho Blue at 25% — ABOVE current 20% T2 "
    "per-protocol cap. Euler 20% T2 + Aave 30% T1 + Compound 20% T1 + 5% cash. "
    "Blended APY ~4.1% nominal / ~4.6% on historical means. "
    "NON-COMPLIANT under RiskPolicy v1.0 (T2 per-protocol 25% > 20%); "
    "advisory-only pending a cap-raise ADR. RiskPolicy gate would block it."
)

# ─── Slots ────────────────────────────────────────────────────────────────────

SLOTS: Dict[str, Dict] = {
    "morpho_blue": {
        "weight":       0.25,
        "tier":         "T2",
        "role":         "t2_yield_max",
        "fallback_apy": 6.0,
        "description":  "Morpho Blue USDC — 25% (above current 20% cap), ~6.0%",
    },
    "euler_v2": {
        "weight":       0.20,
        "tier":         "T2",
        "role":         "t2_secondary",
        "fallback_apy": 5.0,
        "description":  "Euler V2 (ERC-4626) — second T2 venue (~5.0%)",
    },
    "aave_v3": {
        "weight":       0.30,
        "tier":         "T1",
        "role":         "t1_anchor",
        "fallback_apy": 3.1,
        "description":  "Aave V3 mainnet — T1 anchor (~3.1%)",
    },
    "compound_v3": {
        "weight":       0.20,
        "tier":         "T1",
        "role":         "t1_anchor",
        "fallback_apy": 3.3,
        "description":  "Compound V3 Comet USDC — T1 anchor (~3.3%)",
    },
    "__cash__": {
        "weight":       0.05,
        "tier":         "CASH",
        "role":         "cash_buffer",
        "fallback_apy": 0.0,
        "description":  "Cash buffer — RiskPolicy min ≥ 5%",
    },
}

_ADAPTER_IMPORTS: Dict[str, tuple] = {
    "morpho_blue": ("spa_core.adapters.morpho_blue", "MorphoBlueAdapter"),
    "euler_v2":    ("spa_core.adapters.euler_v2", "EulerV2Adapter"),
    "aave_v3":     ("spa_core.adapters.aave_v3", "AaveV3Adapter"),
    "compound_v3": ("spa_core.adapters.compound_v3", "CompoundV3Adapter"),
}

RISK_SCORES: Dict[str, float] = {
    "morpho_blue": 0.42,
    "euler_v2":    0.45,
    "aave_v3":     0.22,
    "compound_v3": 0.24,
}

MIN_APY_ELIGIBLE: float = 1.0
MAX_APY_ELIGIBLE: float = 30.0

TARGET_APY_PCT: float = 4.10          # conservative nominal blended APY (if cap raised)
TARGET_APY_MIN: float = 3.5
TARGET_APY_MAX: float = 5.5
RISK_SCORE:     float = 0.34
MAX_DRAWDOWN_PCT: float = 5.0

# RiskPolicy v1.0 caps (AS-IS) — S39 deliberately exceeds the per-protocol cap
T2_TOTAL_CAP:        float = 0.50
T2_PER_PROTOCOL_CAP: float = 0.20     # current cap; S39 Morpho weight = 0.25 > this
T1_PER_PROTOCOL_CAP: float = 0.40
MIN_CASH_BUFFER:     float = 0.05

# Hypothetical raised cap this strategy is designed for (proposed ADR)
PROPOSED_T2_PER_PROTOCOL_CAP: float = 0.25

ALLOCATION_WEIGHTS: Dict[str, float] = {
    "morpho_blue": 0.25,
    "euler_v2":    0.20,
    "aave_v3":     0.30,
    "compound_v3": 0.20,
}

_HISTORY_MAX: int = 365


# ─── MorphoMaxPlusStrategy ────────────────────────────────────────────────────

class MorphoMaxPlusStrategy:
    """S39 — Morpho Max+ (cap-raise research candidate).

    Identical mechanics to S38 but Morpho Blue at 25%, exceeding the current
    20% T2 single-protocol cap. ADVISORY-ONLY: RiskPolicy would block it
    (approved=False is final). Quantifies the upside of a cap-raise ADR.
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TIER           = TIER
    TARGET_APY_PCT = TARGET_APY_PCT
    RISK_SCORE     = RISK_SCORE

    T2_TOTAL_CAP        = T2_TOTAL_CAP
    T2_PER_PROTOCOL_CAP = T2_PER_PROTOCOL_CAP
    T1_PER_PROTOCOL_CAP = T1_PER_PROTOCOL_CAP
    MIN_CASH_BUFFER     = MIN_CASH_BUFFER
    PROPOSED_T2_PER_PROTOCOL_CAP = PROPOSED_T2_PER_PROTOCOL_CAP

    # Mark clearly as not deployable under current policy
    IS_RESEARCH_ONLY = True

    def __init__(self) -> None:
        self._adapters: Dict[str, object] = {}
        self._simulate_history: List[Dict] = []
        self._load_adapters()

    def _load_adapters(self) -> None:
        import importlib
        for key, (module_path, class_name) in _ADAPTER_IMPORTS.items():
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                self._adapters[key] = cls()
            except Exception:   # noqa: BLE001
                pass

    def _get_adapter_apy(self, key: str) -> float:
        adapter = self._adapters.get(key)
        if adapter is not None:
            try:
                apy = adapter.get_apy()  # type: ignore[attr-defined]
                if isinstance(apy, (int, float)) and not isinstance(apy, bool) and apy > 0:
                    return float(apy)
            except Exception:   # noqa: BLE001
                pass
        slot = SLOTS.get(key)
        return float(slot["fallback_apy"]) if slot else 0.0

    def _is_eligible(self, key: str) -> bool:
        adapter = self._adapters.get(key)
        if adapter is None:
            return True
        try:
            return bool(adapter.is_eligible())  # type: ignore[attr-defined]
        except Exception:   # noqa: BLE001
            return True

    def get_allocation(self, capital_usd: float) -> Dict[str, float]:
        """Target USD allocation (cash held implicitly). See S38 for semantics."""
        if capital_usd <= 0.0:
            return {k: 0.0 for k in ALLOCATION_WEIGHTS}
        allocation: Dict[str, float] = {}
        for key, slot in SLOTS.items():
            if key == "__cash__":
                continue
            bucket = capital_usd * slot["weight"]
            if self._is_eligible(key):
                allocation[key] = round(allocation.get(key, 0.0) + bucket, 6)
        return allocation

    def get_expected_apy(self) -> float:
        weighted = 0.0
        for key, slot in SLOTS.items():
            if key == "__cash__":
                continue
            if self._is_eligible(key):
                weighted += slot["weight"] * self._get_adapter_apy(key)
        return round(weighted, 4)

    def get_risk_summary(self) -> Dict:
        """Tier weights + compliance verdict. adr_compliant is False AS-IS."""
        t1 = sum(s["weight"] for s in SLOTS.values() if s["tier"] == "T1")
        t2 = sum(s["weight"] for s in SLOTS.values() if s["tier"] == "T2")
        cash = sum(s["weight"] for s in SLOTS.values() if s["tier"] == "CASH")

        # AS-IS (current 20% cap) — expected to be False for S39
        t2_per_protocol_ok = all(
            s["weight"] <= T2_PER_PROTOCOL_CAP + 1e-9
            for s in SLOTS.values() if s["tier"] == "T2"
        )
        # Under the proposed 25% cap — would pass
        t2_per_protocol_ok_proposed = all(
            s["weight"] <= PROPOSED_T2_PER_PROTOCOL_CAP + 1e-9
            for s in SLOTS.values() if s["tier"] == "T2"
        )
        t1_per_protocol_ok = all(
            s["weight"] <= T1_PER_PROTOCOL_CAP + 1e-9
            for s in SLOTS.values() if s["tier"] == "T1"
        )
        adr_compliant = (
            t2 <= T2_TOTAL_CAP + 1e-9
            and t2_per_protocol_ok
            and t1_per_protocol_ok
            and cash >= MIN_CASH_BUFFER - 1e-9
        )
        adr_compliant_if_cap_raised = (
            t2 <= T2_TOTAL_CAP + 1e-9
            and t2_per_protocol_ok_proposed
            and t1_per_protocol_ok
            and cash >= MIN_CASH_BUFFER - 1e-9
        )

        return {
            "risk_score":          RISK_SCORE,
            "t1_weight_pct":       round(t1 * 100.0, 2),
            "t2_weight_pct":       round(t2 * 100.0, 2),
            "cash_weight_pct":     round(cash * 100.0, 2),
            "t2_total_cap_pct":    round(T2_TOTAL_CAP * 100.0, 2),
            "t2_per_protocol_cap_pct": round(T2_PER_PROTOCOL_CAP * 100.0, 2),
            "t2_per_protocol_ok":  t2_per_protocol_ok,
            "t1_per_protocol_ok":  t1_per_protocol_ok,
            "cash_buffer_ok":      cash >= MIN_CASH_BUFFER - 1e-9,
            "adr_compliant":       adr_compliant,
            "adr_compliant_if_cap_raised": adr_compliant_if_cap_raised,
            "proposed_t2_per_protocol_cap_pct": round(PROPOSED_T2_PER_PROTOCOL_CAP * 100.0, 2),
            "is_research_only":    True,
            "risk_note": (
                f"S39 Morpho Max+ RESEARCH: Morpho Blue {SLOTS['morpho_blue']['weight']*100:.0f}% "
                f"EXCEEDS current T2 per-protocol cap {T2_PER_PROTOCOL_CAP*100:.0f}% → "
                f"adr_compliant=False, RiskPolicy gate would BLOCK. "
                f"Would pass under a proposed {PROPOSED_T2_PER_PROTOCOL_CAP*100:.0f}% cap (needs ADR). "
                f"T2 total {t2*100:.0f}% ≤ {T2_TOTAL_CAP*100:.0f}%; T1 anchor {t1*100:.0f}%; cash {cash*100:.0f}%."
            ),
        }

    def get_health(self) -> Dict:
        slots_info: Dict[str, Dict] = {}
        eligible_count = 0
        yield_slots = [k for k in SLOTS if k != "__cash__"]
        for key in yield_slots:
            slot = SLOTS[key]
            eligible = self._is_eligible(key)
            apy = self._get_adapter_apy(key) if eligible else slot["fallback_apy"]
            if eligible:
                eligible_count += 1
            slots_info[key] = {
                "weight":   slot["weight"],
                "tier":     slot["tier"],
                "role":     slot["role"],
                "eligible": eligible,
                "apy":      apy,
                "loaded":   key in self._adapters,
            }
        if eligible_count == len(yield_slots):
            status = "ok"
        elif eligible_count == 0:
            status = "critical"
        else:
            status = "degraded"
        return {
            "strategy_id":    STRATEGY_ID,
            "name":           STRATEGY_NAME,
            "eligible_slots": eligible_count,
            "total_slots":    len(yield_slots),
            "slots":          slots_info,
            "expected_apy":   self.get_expected_apy(),
            "target_apy":     TARGET_APY_PCT,
            "risk_score":     RISK_SCORE,
            "is_research_only": True,
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
                "tier":             SLOTS[key]["tier"],
                "risk_score":       RISK_SCORES.get(key, 0.0),
            }
        result = {
            "total_capital":             capital_usd,
            "allocation":                allocation,
            "deployed_usd":              round(deployed, 4),
            "cash_usd":                  round(capital_usd - deployed, 4),
            "expected_annual_yield_usd": round(total_yield, 4),
            "expected_apy_pct":          round(self.get_expected_apy(), 4),
            "status":                    "ok",
            "is_research_only":          True,
            "slot_results":              slot_results,
            "risk_summary":              self.get_risk_summary(),
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }
        self._simulate_history.append(result)
        if len(self._simulate_history) > _HISTORY_MAX:
            self._simulate_history = self._simulate_history[-_HISTORY_MAX:]
        return result

    def to_dict(self) -> Dict:
        return {
            "strategy_id":        STRATEGY_ID,
            "strategy_name":      STRATEGY_NAME,
            "tier":               TIER,
            "description":        DESCRIPTION,
            "is_research_only":   True,
            "slots":              {k: dict(v) for k, v in SLOTS.items()},
            "allocation_weights": dict(ALLOCATION_WEIGHTS),
            "risk_scores":        dict(RISK_SCORES),
            "target_apy_pct":     TARGET_APY_PCT,
            "target_apy_min":     TARGET_APY_MIN,
            "target_apy_max":     TARGET_APY_MAX,
            "risk_score":         RISK_SCORE,
            "max_drawdown_pct":   MAX_DRAWDOWN_PCT,
            "min_apy_eligible":   MIN_APY_ELIGIBLE,
            "max_apy_eligible":   MAX_APY_ELIGIBLE,
            "proposed_t2_per_protocol_cap": PROPOSED_T2_PER_PROTOCOL_CAP,
            "expected_apy":       self.get_expected_apy(),
            "health":             self.get_health(),
            "risk_summary":       self.get_risk_summary(),
            "adapters_loaded":    list(self._adapters.keys()),
            "timestamp":          datetime.now(timezone.utc).isoformat(),
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
            module="spa_core.strategies.s39_morpho_max_plus",
            handler_class="MorphoMaxPlusStrategy",
            tags=[
                "morpho", "morpho_blue", "t2", "max_allocation", "research_only",
                "cap_raise", "non_compliant", "euler_v2", "aave_v3", "compound_v3",
                "s39", "advisory",
            ],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "MorphoMaxPlusStrategy auto-registration failed: %s", exc
        )


_register()
