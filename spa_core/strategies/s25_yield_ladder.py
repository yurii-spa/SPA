"""
spa_core/strategies/s25_yield_ladder.py — S25 Yield Ladder (Barbell)

S25: Yield Ladder
=================
Barbell / ladder strategy: a heavy ultra-safe T1 base paired with a single,
dynamically-selected highest-APY T2 sleeve. Each cycle the T2 sleeve rotates to
whichever candidate currently offers the best yield.

Allocation:
  sky_susds (T1, 30%): Sky/Spark sUSDS — ultra-safe DSR anchor, ~6.5% APY
  aave      (T1, 30%): Aave V3 USDC — ultra-safe lending anchor, ~4.2% APY
  best_t2   (T2, 40%): dynamic — highest-APY eligible from
                       {susde (Ethena), yearn_v3, euler_v2, maple}

  Barbell logic: 60% can-not-lose T1 + 40% reach-for-yield T2. The T2 leg is
  re-selected every `get_allocation` call (i.e. each cycle), so the ladder
  always points at the best available T2 rate.

Weighted Target APY (defaults, best_t2 ≈ 10%):
  0.30*6.5 + 0.30*4.2 + 0.40*10.0 = 1.95 + 1.26 + 4.00 = 7.21% → target 5–12%.

Risk note:
  The dynamic T2 candidate set spans T2 (yearn/euler/maple) and T3 (susde). When
  susde wins the sleeve, effective T3 exposure is 40% — above RiskPolicy T3_CAP
  10%. Advisory/read-only: the deterministic RiskPolicy gate and
  `apply_risk_policy` clip per-tier caps and retain final authority;
  approved=False is never overridden.

Rules: stdlib only · read-only/advisory · LLM FORBIDDEN · no execution imports.

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S25"
STRATEGY_NAME = "Yield Ladder"
TIER          = "T2"
DESCRIPTION   = (
    "Yield Ladder (barbell): 60% ultra-safe T1 (Sky sUSDS 30% + Aave 30%) + "
    "40% dynamic best T2 from {Ethena sUSDe, Yearn, Euler, Maple}. "
    "T2 sleeve rotates to the highest-APY candidate each cycle. Target APY 5-12%."
)

# ─── Fixed T1 base slots ──────────────────────────────────────────────────────

T1_SLOTS: Dict[str, Dict] = {
    "sky": {
        "adapter":      "spark_susds",
        "weight":       0.30,
        "tier":         "T1",
        "fallback_apy": 6.5,
        "description":  "Sky/Spark sUSDS — ultra-safe DSR anchor, ~6.5% APY",
    },
    "aave": {
        "adapter":      "aave_v3",
        "weight":       0.30,
        "tier":         "T1",
        "fallback_apy": 4.2,
        "description":  "Aave V3 USDC — ultra-safe lending anchor, ~4.2% APY",
    },
}

# ─── Dynamic T2 sleeve ────────────────────────────────────────────────────────

T2_SLEEVE_WEIGHT: float = 0.40
# Candidate adapter keys for the dynamic best-T2 sleeve (rotated each cycle).
T2_CANDIDATES: List[str] = ["susde", "yearn_v3", "euler_v2", "maple"]

FALLBACK_APY: Dict[str, float] = {
    "spark_susds": 6.5,
    "aave_v3":     4.2,
    "susde":       12.0,
    "yearn_v3":    8.5,
    "euler_v2":    7.5,
    "maple":       9.0,
}

RISK_SCORES: Dict[str, float] = {
    "spark_susds": 0.20,
    "aave_v3":     0.15,
    "susde":       0.62,
    "yearn_v3":    0.40,
    "euler_v2":    0.43,
    "maple":       0.48,
}

# Tier of each dynamic candidate (susde is T3, the rest T2).
CANDIDATE_TIER: Dict[str, str] = {
    "susde":    "T3",
    "yearn_v3": "T2",
    "euler_v2": "T2",
    "maple":    "T2",
}

MIN_APY_ELIGIBLE: float = 1.0
MAX_APY_ELIGIBLE: float = 30.0

TARGET_APY_PCT:   float = 7.0
TARGET_APY_MIN:   float = 5.0
TARGET_APY_MAX:   float = 12.0
RISK_SCORE:       float = 0.40
MAX_DRAWDOWN_PCT: float = 5.0
_HISTORY_MAX:     int   = 365


def _norm_apy_pct(value: object, fallback: float) -> float:
    """Normalize an adapter get_apy() return to percent (see S22 for rationale)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):
        return fallback
    if v <= 0.0:
        return fallback
    return v * 100.0 if v < 1.0 else v


class YieldLadderStrategy:
    """S25 — Yield Ladder (barbell): 60% T1 base + 40% dynamic best T2.

    The T2 sleeve is re-selected each cycle to the highest-APY eligible
    candidate among {susde, yearn_v3, euler_v2, maple}. Stdlib only,
    advisory/read-only.
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TIER           = TIER
    TARGET_APY_PCT = TARGET_APY_PCT
    RISK_SCORE     = RISK_SCORE

    def __init__(self) -> None:
        self._adapters: Dict[str, object] = {}
        self._simulate_history: List[Dict] = []
        self._load_adapters()

    def _load_adapters(self) -> None:
        loaders = {
            "spark_susds": ("spa_core.adapters.spark_susds_adapter", "SparkSusdsAdapter"),
            "aave_v3":     ("spa_core.adapters.aave_v3", "AaveV3Adapter"),
            "susde":       ("spa_core.adapters.susde_adapter", "SusdeAdapter"),
            "yearn_v3":    ("spa_core.adapters.yearn_v3", "YearnV3Adapter"),
            "euler_v2":    ("spa_core.adapters.euler_v2", "EulerV2Adapter"),
            "maple":       ("spa_core.adapters.maple", "MapleAdapter"),
        }
        for key, (module_path, cls_name) in loaders.items():
            try:
                import importlib
                mod = importlib.import_module(module_path)
                self._adapters[key] = getattr(mod, cls_name)()
            except Exception:   # noqa: BLE001
                pass

    # ── utilities ──────────────────────────────────────────────────────────

    def _get_adapter_apy(self, adapter_key: str) -> float:
        adapter = self._adapters.get(adapter_key)
        fallback = FALLBACK_APY.get(adapter_key, 0.0)
        if adapter is not None:
            try:
                return _norm_apy_pct(adapter.get_apy(), fallback)  # type: ignore[attr-defined]
            except Exception:   # noqa: BLE001
                pass
        return fallback

    def _is_eligible(self, adapter_key: str) -> bool:
        adapter = self._adapters.get(adapter_key)
        if adapter is None:
            return True
        try:
            return bool(adapter.is_eligible())  # type: ignore[attr-defined]
        except Exception:   # noqa: BLE001
            return True

    def select_best_t2(self) -> Tuple[str, float]:
        """Pick the highest-APY *eligible* T2 candidate for the sleeve.

        Returns (adapter_key, apy_pct). Falls back to the first candidate if
        none is eligible (so the ladder always has a T2 leg in paper mode).
        """
        best_key: Optional[str] = None
        best_apy: float = -1.0
        for key in T2_CANDIDATES:
            if not self._is_eligible(key):
                continue
            apy = self._get_adapter_apy(key)
            if apy > best_apy:
                best_apy = apy
                best_key = key
        if best_key is None:
            fallback_key = T2_CANDIDATES[0]
            return fallback_key, self._get_adapter_apy(fallback_key)
        return best_key, best_apy

    # ── public API ─────────────────────────────────────────────────────────

    def get_allocation(self, capital_usd: float) -> Dict[str, float]:
        if capital_usd <= 0.0:
            keys = [s["adapter"] for s in T1_SLOTS.values()] + [T2_CANDIDATES[0]]
            return {k: 0.0 for k in keys}
        allocation: Dict[str, float] = {}
        for slot_cfg in T1_SLOTS.values():
            key = slot_cfg["adapter"]
            allocation[key] = allocation.get(key, 0.0) + capital_usd * slot_cfg["weight"]
        best_key, _ = self.select_best_t2()
        allocation[best_key] = allocation.get(best_key, 0.0) + capital_usd * T2_SLEEVE_WEIGHT
        return {k: round(v, 6) for k, v in allocation.items()}

    def get_expected_apy(self) -> float:
        allocation = self.get_allocation(1.0)
        total = sum(allocation.values())
        if total <= 0.0:
            return TARGET_APY_PCT
        weighted = sum(self._get_adapter_apy(k) * w for k, w in allocation.items())
        return round(weighted / total, 4)

    def get_risk_summary(self) -> Dict:
        best_key, best_apy = self.select_best_t2()
        sleeve_tier = CANDIDATE_TIER.get(best_key, "T2")
        t1 = sum(s["weight"] for s in T1_SLOTS.values())
        t2_or_t3 = T2_SLEEVE_WEIGHT
        return {
            "risk_score":        RISK_SCORE,
            "t1_weight_pct":     round(t1 * 100.0, 2),
            "sleeve_weight_pct": round(t2_or_t3 * 100.0, 2),
            "sleeve_selected":   best_key,
            "sleeve_tier":       sleeve_tier,
            "sleeve_apy":        best_apy,
            "barbell":           True,
            "t3_cap_note": (
                "Sleeve=susde → 40% T3 > RiskPolicy T3_CAP 10%; gate clips. Advisory."
                if sleeve_tier == "T3" else "Sleeve within T2 caps."
            ),
            "max_drawdown_pct":  MAX_DRAWDOWN_PCT,
            "risk_note": (
                f"S25 Yield Ladder barbell: T1={t1*100:.0f}% safe base + "
                f"{t2_or_t3*100:.0f}% {sleeve_tier} sleeve → {best_key} ({best_apy:.2f}%)."
            ),
        }

    def get_health(self) -> Dict:
        slots_info: Dict[str, Dict] = {}
        eligible_count = 0
        # T1 base slots.
        for slot_name, slot_cfg in T1_SLOTS.items():
            key = slot_cfg["adapter"]
            eligible = self._is_eligible(key)
            if eligible:
                eligible_count += 1
            slots_info[slot_name] = {
                "adapter":  key,
                "weight":   slot_cfg["weight"],
                "tier":     slot_cfg["tier"],
                "eligible": eligible,
                "apy":      self._get_adapter_apy(key),
                "loaded":   key in self._adapters,
            }
        # Dynamic sleeve.
        best_key, best_apy = self.select_best_t2()
        sleeve_eligible = self._is_eligible(best_key)
        if sleeve_eligible:
            eligible_count += 1
        slots_info["best_t2"] = {
            "adapter":    best_key,
            "weight":     T2_SLEEVE_WEIGHT,
            "tier":       CANDIDATE_TIER.get(best_key, "T2"),
            "eligible":   sleeve_eligible,
            "apy":        best_apy,
            "candidates": list(T2_CANDIDATES),
            "loaded":     best_key in self._adapters,
        }
        total_slots = len(T1_SLOTS) + 1
        if eligible_count == total_slots:
            status = "ok"
        elif eligible_count == 0:
            status = "critical"
        else:
            status = "degraded"
        return {
            "strategy_id":    STRATEGY_ID,
            "name":           STRATEGY_NAME,
            "eligible_slots": eligible_count,
            "total_slots":    total_slots,
            "slots":          slots_info,
            "expected_apy":   self.get_expected_apy(),
            "target_apy":     TARGET_APY_PCT,
            "sleeve_selected": best_key,
            "overall_status": status,
        }

    def simulate(self, capital_usd: float) -> Dict:
        allocation = self.get_allocation(capital_usd)
        if not allocation or capital_usd <= 0.0:
            return {
                "total_capital":             capital_usd,
                "allocation":                {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "risk_summary":              self.get_risk_summary(),
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        total_yield = 0.0
        positions: Dict[str, Dict] = {}
        for key, amount in allocation.items():
            apy = self._get_adapter_apy(key)
            annual = amount * (apy / 100.0)
            total_yield += annual
            positions[key] = {
                "amount_usd":       round(amount, 6),
                "apy_pct":          apy,
                "annual_yield_usd": round(annual, 4),
                "risk_score":       RISK_SCORES.get(key, 0.0),
            }
        best_key, _ = self.select_best_t2()
        result = {
            "total_capital":             capital_usd,
            "allocation":                allocation,
            "positions":                 positions,
            "sleeve_selected":           best_key,
            "expected_annual_yield_usd": round(total_yield, 4),
            "expected_apy_pct":          self.get_expected_apy(),
            "status":                    "ok",
            "risk_summary":              self.get_risk_summary(),
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }
        self._simulate_history.append(result)
        if len(self._simulate_history) > _HISTORY_MAX:
            self._simulate_history = self._simulate_history[-_HISTORY_MAX:]
        return result

    def to_dict(self) -> Dict:
        best_key, best_apy = self.select_best_t2()
        return {
            "strategy_id":          STRATEGY_ID,
            "strategy_name":        STRATEGY_NAME,
            "tier":                 TIER,
            "description":          DESCRIPTION,
            "t1_slots":             {k: dict(v) for k, v in T1_SLOTS.items()},
            "t2_sleeve_weight":     T2_SLEEVE_WEIGHT,
            "t2_candidates":        list(T2_CANDIDATES),
            "candidate_tier":       dict(CANDIDATE_TIER),
            "sleeve_selected":      best_key,
            "sleeve_apy":           best_apy,
            "fallback_apy":         dict(FALLBACK_APY),
            "risk_scores":          dict(RISK_SCORES),
            "target_apy_pct":       TARGET_APY_PCT,
            "target_apy_min":       TARGET_APY_MIN,
            "target_apy_max":       TARGET_APY_MAX,
            "risk_score":           RISK_SCORE,
            "max_drawdown_pct":     MAX_DRAWDOWN_PCT,
            "expected_apy":         self.get_expected_apy(),
            "health":               self.get_health(),
            "risk_summary":         self.get_risk_summary(),
            "adapters_loaded":      list(self._adapters.keys()),
            "simulate_history_len": len(self._simulate_history),
            "timestamp":            datetime.now(timezone.utc).isoformat(),
        }


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
            module="spa_core.strategies.s25_yield_ladder",
            handler_class="YieldLadderStrategy",
            tags=["barbell", "ladder", "dynamic", "sky_susds", "aave_v3",
                  "susde", "yearn_v3", "euler_v2", "maple", "t2", "s25"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "YieldLadderStrategy auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = YieldLadderStrategy()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
