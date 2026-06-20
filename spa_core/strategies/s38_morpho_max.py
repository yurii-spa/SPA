"""
spa_core/strategies/s38_morpho_max.py — S38 Morpho Max-Allocation

S38 Morpho Max-Allocation Strategy
==================================
Captures Morpho Blue USDC — the highest-APY venue in the SPA universe
(historical 365-day mean ≈ 6.87%, conservative target 6.0%) — by pushing
its weight to the **maximum allowed T2 single-protocol cap (20%)** while
keeping the whole book inside RiskPolicy v1.0 limits.

Motivation
----------
The live paper portfolio holds Morpho Blue (mainnet) at only ~1.9% of
capital — far below the 20% T2 per-protocol cap — while parking large
weights in lower-yield T1 venues (Aave ≈ 3.65%, Compound ≈ 3.79%).
S38 re-captures that spread without breaching any cap.

Target weights (sum = 100%):
  Morpho Blue   (T2, 20%) — max T2 single-protocol cap, ~6.0% APY
  Euler V2      (T2, 20%) — second T2 venue (ERC-4626), ~5.0% APY
  Aave V3       (T1, 35%) — T1 anchor, ~3.1% APY
  Compound V3   (T1, 20%) — T1 anchor, ~3.3% APY
  Cash          (    5%)  — min cash buffer (RiskPolicy ≥ 5%)

Compliance (RiskPolicy v1.0):
  T2 total          = 40%  ≤ 50%  cap (ADR-019)            → OK
  T2 per-protocol   = 20%  ≤ 20%  cap                      → OK (at cap)
  T1 per-protocol   = 35% / 20% ≤ 40% cap                  → OK
  Cash buffer       =  5%  ≥ 5%   min                      → OK
  adr_compliant     = True

Expected blended APY:
  Conservative (nominal):
    0.20*6.0 + 0.20*5.0 + 0.35*3.1 + 0.20*3.3 + 0.05*0.0
    = 1.20 + 1.00 + 1.085 + 0.66 = 3.945%  ≈ 3.95%
  Using 365-day historical means (Morpho 6.87 / Aave 3.65 / Compound 3.79):
    0.20*6.87 + 0.20*5.0 + 0.35*3.65 + 0.20*3.79
    = 1.374 + 1.00 + 1.2775 + 0.758 ≈ 4.41%

A marginal but real improvement over the diffuse current book, achieved
entirely within policy. The bigger upside (S39) needs an ADR to raise the
T2 single-protocol cap above 20% — until then S39 is advisory-only.

Rules:
  - stdlib only, no external runtime dependencies
  - read-only / advisory — does NOT call execution/ or risk-agents
  - LLM FORBIDDEN in this module
  - approved=False from RiskPolicy cannot be overridden
  - atomic data/ writes only (tmp + os.replace) — this module writes nothing

Date: 2026-06-21 (MP-1247)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Strategy identity ────────────────────────────────────────────────────────

STRATEGY_ID   = "S38"
STRATEGY_NAME = "Morpho Max-Allocation"
TIER          = "T2"   # T2-leaning (40% T2), but T1-anchored (55% T1)
DESCRIPTION   = (
    "Morpho Max: pushes Morpho Blue USDC to the 20% T2 single-protocol cap "
    "(~6.0% APY, highest in universe) + Euler V2 20% T2 (~5.0%) + "
    "Aave V3 35% T1 (~3.1%) + Compound V3 20% T1 (~3.3%) + 5% cash. "
    "Blended APY ~3.95% nominal / ~4.4% on historical means. "
    "Fully RiskPolicy v1.0 compliant: T2 total 40% ≤ 50%, per-protocol 20% ≤ 20%."
)

# ─── Slots (one adapter per slot, fixed weights) ──────────────────────────────
# Each slot maps to a single adapter key matching data/current_positions.json.

SLOTS: Dict[str, Dict] = {
    "morpho_blue": {
        "weight":       0.20,
        "tier":         "T2",
        "role":         "t2_yield_max",
        "fallback_apy": 6.0,
        "description":  "Morpho Blue USDC — max T2 cap, highest APY (~6.0%)",
    },
    "euler_v2": {
        "weight":       0.20,
        "tier":         "T2",
        "role":         "t2_secondary",
        "fallback_apy": 5.0,
        "description":  "Euler V2 (ERC-4626) — second T2 venue (~5.0%)",
    },
    "aave_v3": {
        "weight":       0.35,
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

# ─── Adapter import map: slot key → (module, class) ────────────────────────────

_ADAPTER_IMPORTS: Dict[str, tuple] = {
    "morpho_blue": ("spa_core.adapters.morpho_blue", "MorphoBlueAdapter"),
    "euler_v2":    ("spa_core.adapters.euler_v2", "EulerV2Adapter"),
    "aave_v3":     ("spa_core.adapters.aave_v3", "AaveV3Adapter"),
    "compound_v3": ("spa_core.adapters.compound_v3", "CompoundV3Adapter"),
}

# ─── Risk scores (per adapter) ────────────────────────────────────────────────

RISK_SCORES: Dict[str, float] = {
    "morpho_blue": 0.42,   # T2, isolated-market lending risk
    "euler_v2":    0.45,   # T2, ERC-4626 vault risk
    "aave_v3":     0.22,   # T1, blue-chip lending
    "compound_v3": 0.24,   # T1, Comet mono-market
}

# ─── Eligible APY bounds (RiskPolicy new-position window) ──────────────────────

MIN_APY_ELIGIBLE: float = 1.0
MAX_APY_ELIGIBLE: float = 30.0

# ─── Target metrics ───────────────────────────────────────────────────────────

TARGET_APY_PCT: float = 3.95          # conservative nominal blended APY
TARGET_APY_MIN: float = 3.0
TARGET_APY_MAX: float = 5.0
RISK_SCORE:     float = 0.31          # T1-anchored, moderate
MAX_DRAWDOWN_PCT: float = 5.0

# RiskPolicy v1.0 caps this strategy respects
T2_TOTAL_CAP:        float = 0.50     # ADR-019
T2_PER_PROTOCOL_CAP: float = 0.20
T1_PER_PROTOCOL_CAP: float = 0.40
MIN_CASH_BUFFER:     float = 0.05

# Flat allocation weights for cycle_runner (advisory)
ALLOCATION_WEIGHTS: Dict[str, float] = {
    "morpho_blue": 0.20,
    "euler_v2":    0.20,
    "aave_v3":     0.35,
    "compound_v3": 0.20,
}

_HISTORY_MAX: int = 365


# ─── MorphoMaxStrategy ────────────────────────────────────────────────────────

class MorphoMaxStrategy:
    """S38 — Morpho Max-Allocation: Morpho Blue at the 20% T2 cap.

    Pushes the highest-yield venue (Morpho Blue, ~6% APY) to its maximum
    allowed weight while staying fully inside RiskPolicy v1.0. T1-anchored
    (Aave 35% + Compound 20% = 55% T1) for drawdown protection.

    Stdlib only, advisory/read-only. RiskPolicy approved=False is final.
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TIER           = TIER
    TARGET_APY_PCT = TARGET_APY_PCT
    RISK_SCORE     = RISK_SCORE

    # Caps as instance-visible constants for callers/tests
    T2_TOTAL_CAP        = T2_TOTAL_CAP
    T2_PER_PROTOCOL_CAP = T2_PER_PROTOCOL_CAP
    T1_PER_PROTOCOL_CAP = T1_PER_PROTOCOL_CAP
    MIN_CASH_BUFFER     = MIN_CASH_BUFFER

    def __init__(self) -> None:
        self._adapters: Dict[str, object] = {}
        self._simulate_history: List[Dict] = []
        self._load_adapters()

    # ── Adapter loading ─────────────────────────────────────────────────────

    def _load_adapters(self) -> None:
        """Best-effort load of each adapter; missing → fallback APY at runtime."""
        import importlib
        for key, (module_path, class_name) in _ADAPTER_IMPORTS.items():
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                self._adapters[key] = cls()
            except Exception:   # noqa: BLE001 — degrade to fallback APY
                pass

    # ── Utilities ────────────────────────────────────────────────────────────

    def _get_adapter_apy(self, key: str) -> float:
        """adapter.get_apy() → SLOTS fallback_apy → 0.0."""
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
        """Eligible if adapter missing (use fallback) or adapter.is_eligible() truthy."""
        adapter = self._adapters.get(key)
        if adapter is None:
            return True
        try:
            return bool(adapter.is_eligible())  # type: ignore[attr-defined]
        except Exception:   # noqa: BLE001
            return True

    # ── Public API ─────────────────────────────────────────────────────────

    def get_allocation(self, capital_usd: float) -> Dict[str, float]:
        """Target USD allocation per adapter key (excludes the cash slot).

        Cash is held implicitly: deployed = capital * (1 - cash_weight).
        If a yield slot's adapter is ineligible, its bucket rolls to cash
        (conservative — never force-deploys into a blocked venue).
        """
        if capital_usd <= 0.0:
            return {k: 0.0 for k in ALLOCATION_WEIGHTS}

        allocation: Dict[str, float] = {}
        for key, slot in SLOTS.items():
            if key == "__cash__":
                continue
            bucket = capital_usd * slot["weight"]
            if self._is_eligible(key):
                allocation[key] = round(allocation.get(key, 0.0) + bucket, 6)
            # ineligible → bucket stays as cash (not added to allocation)
        return allocation

    def get_expected_apy(self) -> float:
        """Blended APY (%) over the full book INCLUDING the 5% cash drag."""
        weighted = 0.0
        for key, slot in SLOTS.items():
            if key == "__cash__":
                continue
            if self._is_eligible(key):
                weighted += slot["weight"] * self._get_adapter_apy(key)
            # ineligible slot → 0% (sits in cash)
        return round(weighted, 4)

    def get_risk_summary(self) -> Dict:
        """Tier weights + RiskPolicy v1.0 compliance verdict."""
        t1 = sum(s["weight"] for s in SLOTS.values() if s["tier"] == "T1")
        t2 = sum(s["weight"] for s in SLOTS.values() if s["tier"] == "T2")
        cash = sum(s["weight"] for s in SLOTS.values() if s["tier"] == "CASH")

        t2_per_protocol_ok = all(
            s["weight"] <= T2_PER_PROTOCOL_CAP + 1e-9
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
            "risk_note": (
                f"S38 Morpho Max: T2={t2*100:.0f}% (≤ {T2_TOTAL_CAP*100:.0f}% cap), "
                f"Morpho Blue at {SLOTS['morpho_blue']['weight']*100:.0f}% = T2 per-protocol cap. "
                f"T1 anchor {t1*100:.0f}%. Cash {cash*100:.0f}%. "
                f"Fully RiskPolicy v1.0 compliant."
            ),
        }

    def get_health(self) -> Dict:
        """Per-slot eligibility/APY snapshot + overall status."""
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
            "overall_status": status,
        }

    def simulate(self, capital_usd: float) -> Dict:
        """One-day simulation: allocation, per-adapter annual yield, blended APY."""
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
            "slot_results":              slot_results,
            "risk_summary":              self.get_risk_summary(),
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

        self._simulate_history.append(result)
        if len(self._simulate_history) > _HISTORY_MAX:
            self._simulate_history = self._simulate_history[-_HISTORY_MAX:]
        return result

    def to_dict(self) -> Dict:
        """JSON-serializable snapshot of the strategy."""
        return {
            "strategy_id":        STRATEGY_ID,
            "strategy_name":      STRATEGY_NAME,
            "tier":               TIER,
            "description":        DESCRIPTION,
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
            "expected_apy":       self.get_expected_apy(),
            "health":             self.get_health(),
            "risk_summary":       self.get_risk_summary(),
            "adapters_loaded":    list(self._adapters.keys()),
            "timestamp":          datetime.now(timezone.utc).isoformat(),
        }


# ─── Auto-registration ────────────────────────────────────────────────────────

def _register() -> None:
    """Register S38 in the global REGISTRY (import-time side effect)."""
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
            module="spa_core.strategies.s38_morpho_max",
            handler_class="MorphoMaxStrategy",
            tags=[
                "morpho", "morpho_blue", "t2", "max_allocation", "yield_max",
                "euler_v2", "aave_v3", "compound_v3", "adr_019_compliant",
                "s38", "policy_compliant",
            ],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "MorphoMaxStrategy auto-registration failed: %s", exc
        )


_register()
