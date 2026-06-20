"""
spa_core/strategies/s24_base_chain_max.py — S24 Base Chain Maximizer

S24: Base Chain Maximizer
=========================
Cross-chain (Coinbase Base L2) USDC yield maximizer. All legs are read-only
Base adapters already in the registry — no signing, no bridging executed.

Allocation:
  morpho_blue_base (T2, 40%): Morpho Blue Base — primary, ~6.5% APY
  aave_v3_base     (T2, 30%): Aave V3 Base — anchor, ~4.8% APY
  moonwell_base    (T2, 30%): Moonwell Base — third leg, ~6.0% APY

  Aerodrome USDC-USDT stable LP was scoped for the third leg but needs a new
  live-API adapter (api.aerodrome.finance) — out of scope for a read-only,
  stdlib, offline-safe build. Moonwell Base (existing adapter) is used as the
  third leg instead; Aerodrome remains a documented future substitute.

Weighted Target APY (defaults):
  0.40*6.5 + 0.30*4.8 + 0.30*6.0 = 2.60 + 1.44 + 1.80 = 5.84% → target 4–9%.

Phase gate:
  Base chain capital allocation is governed by ADR-025 Phase 2 (go-live
  ~2026-08-01). Before that, this strategy is advisory-only (paper). The
  per-adapter APY feeds are read-only and always available regardless of phase.

Risk note:
  Base is an L2 — bridge risk + L2 sequencer risk on top of protocol risk.
  Moonwell RISK_SCORE was raised to 0.75 after the Nov-2025 incident (ADR-026).
  T3-classified strategy (needs 30d paper before promotion). Advisory/read-only;
  RiskPolicy gate retains final authority; approved=False never overridden.

Rules: stdlib only · read-only/advisory · LLM FORBIDDEN · no execution imports.

Date: 2026-06-21
"""
from __future__ import annotations

import datetime as _dt
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S24"
STRATEGY_NAME = "Base Chain Maximizer"
TIER          = "T3"   # L2 strategy — 30d paper before promotion (ADR-023)
DESCRIPTION   = (
    "Base Chain Maximizer: Morpho Blue Base 40% (~6.5%) + Aave V3 Base 30% "
    "(~4.8%) + Moonwell Base 30% (~6.0%). Target APY 4-9%, all read-only Base "
    "L2 adapters. Aerodrome stable LP = documented future substitute. "
    "ADR-025 Phase 2 gated (Base capital ~2026-08-01)."
)

# ADR-025 Phase 2 go-live for Base capital allocation.
BASE_PHASE_2_DATE = "2026-08-01"

# ─── Slots ────────────────────────────────────────────────────────────────────

SLOTS: Dict[str, Dict] = {
    "morpho_base": {
        "adapter":      "morpho_blue_base",
        "weight":       0.40,
        "role":         "base_primary",
        "tier":         "T2",
        "fallback_apy": 6.5,
        "description":  "Morpho Blue Base — primary Base yield, ~6.5% APY",
    },
    "aave_base": {
        "adapter":      "aave_v3_base",
        "weight":       0.30,
        "role":         "base_anchor",
        "tier":         "T2",
        "fallback_apy": 4.8,
        "description":  "Aave V3 Base — Base lending anchor, ~4.8% APY",
    },
    "moonwell_base": {
        "adapter":      "moonwell_base",
        "weight":       0.30,
        "role":         "base_third_leg",
        "tier":         "T2",
        "fallback_apy": 6.0,
        "description":  "Moonwell Base — third leg (Aerodrome substitute), ~6.0% APY",
    },
}

FALLBACK_APY: Dict[str, float] = {
    "morpho_blue_base": 6.5,
    "aave_v3_base":     4.8,
    "moonwell_base":    6.0,
}

RISK_SCORES: Dict[str, float] = {
    "morpho_blue_base": 0.38,
    "aave_v3_base":     0.35,
    "moonwell_base":    0.75,   # raised Nov-2025 incident (ADR-026)
}

MIN_APY_ELIGIBLE: float = 1.0
MAX_APY_ELIGIBLE: float = 30.0

TARGET_APY_PCT:   float = 5.8
TARGET_APY_MIN:   float = 4.0
TARGET_APY_MAX:   float = 9.0
RISK_SCORE:       float = 0.45
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


def _is_phase2_active() -> bool:
    """True once Base capital allocation is permitted (ADR-025 Phase 2)."""
    return _dt.date.today().isoformat() >= BASE_PHASE_2_DATE


class BaseChainMaxStrategy:
    """S24 — Base Chain Maximizer (Morpho/Aave/Moonwell on Base L2).

    Cross-chain read-only USDC yield aggregator on Coinbase Base. Phase-gated
    by ADR-025 for capital; APY feeds are always read-only. Stdlib only.
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TIER           = TIER
    TARGET_APY_PCT = TARGET_APY_PCT
    RISK_SCORE     = RISK_SCORE

    def __init__(self) -> None:
        self._adapters: Dict[str, object] = {}
        self._simulate_history: List[Dict] = []
        self.phase2_active = _is_phase2_active()
        self._load_adapters()

    def _load_adapters(self) -> None:
        try:
            from spa_core.adapters.morpho_blue_base_adapter import MorphoBlueBaseAdapter
            self._adapters["morpho_blue_base"] = MorphoBlueBaseAdapter()
        except Exception:   # noqa: BLE001
            pass
        try:
            from spa_core.adapters.aave_v3_base_adapter import AaveV3BaseAdapter
            self._adapters["aave_v3_base"] = AaveV3BaseAdapter()
        except Exception:   # noqa: BLE001
            pass
        try:
            from spa_core.adapters.moonwell_base_adapter import MoonwellBaseAdapter
            self._adapters["moonwell_base"] = MoonwellBaseAdapter()
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

    def get_mode(self) -> str:
        """phase2_base (capital allowed) or phase1_advisory (paper only)."""
        return "phase2_base" if _is_phase2_active() else "phase1_advisory"

    # ── public API ─────────────────────────────────────────────────────────

    def get_allocation(self, capital_usd: float) -> Dict[str, float]:
        if capital_usd <= 0.0:
            return {SLOTS[s]["adapter"]: 0.0 for s in SLOTS}
        allocation: Dict[str, float] = {}
        for slot_cfg in SLOTS.values():
            key = slot_cfg["adapter"]
            allocation[key] = allocation.get(key, 0.0) + capital_usd * slot_cfg["weight"]
        return {k: round(v, 6) for k, v in allocation.items()}

    def get_expected_apy(self) -> float:
        allocation = self.get_allocation(1.0)
        total = sum(allocation.values())
        if total <= 0.0:
            return TARGET_APY_PCT
        weighted = sum(self._get_adapter_apy(k) * w for k, w in allocation.items())
        return round(weighted / total, 4)

    def get_risk_summary(self) -> Dict:
        t2 = sum(s["weight"] for s in SLOTS.values() if s["tier"] == "T2")
        return {
            "risk_score":       RISK_SCORE,
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "chain":            "base",
            "phase2_active":    _is_phase2_active(),
            "mode":             self.get_mode(),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "risk_note": (
                f"S24 Base Chain Maximizer: T2={t2*100:.0f}% on Base L2 "
                f"(bridge + sequencer risk). Moonwell risk 0.75 (ADR-026). "
                f"Mode={self.get_mode()}."
            ),
        }

    def get_health(self) -> Dict:
        slots_info: Dict[str, Dict] = {}
        eligible_count = 0
        for slot_name, slot_cfg in SLOTS.items():
            key = slot_cfg["adapter"]
            eligible = self._is_eligible(key)
            if eligible:
                eligible_count += 1
            slots_info[slot_name] = {
                "adapter":  key,
                "weight":   slot_cfg["weight"],
                "tier":     slot_cfg["tier"],
                "role":     slot_cfg["role"],
                "eligible": eligible,
                "apy":      self._get_adapter_apy(key),
                "loaded":   key in self._adapters,
            }
        if eligible_count == len(SLOTS):
            status = "ok"
        elif eligible_count == 0:
            status = "critical"
        else:
            status = "degraded"
        return {
            "strategy_id":    STRATEGY_ID,
            "name":           STRATEGY_NAME,
            "eligible_slots": eligible_count,
            "total_slots":    len(SLOTS),
            "slots":          slots_info,
            "expected_apy":   self.get_expected_apy(),
            "target_apy":     TARGET_APY_PCT,
            "mode":           self.get_mode(),
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
        result = {
            "total_capital":             capital_usd,
            "allocation":                allocation,
            "positions":                 positions,
            "expected_annual_yield_usd": round(total_yield, 4),
            "expected_apy_pct":          self.get_expected_apy(),
            "mode":                      self.get_mode(),
            "status":                    "ok",
            "risk_summary":              self.get_risk_summary(),
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }
        self._simulate_history.append(result)
        if len(self._simulate_history) > _HISTORY_MAX:
            self._simulate_history = self._simulate_history[-_HISTORY_MAX:]
        return result

    def to_dict(self) -> Dict:
        return {
            "strategy_id":          STRATEGY_ID,
            "strategy_name":        STRATEGY_NAME,
            "tier":                 TIER,
            "description":          DESCRIPTION,
            "chain":                "base",
            "phase2_date":          BASE_PHASE_2_DATE,
            "mode":                 self.get_mode(),
            "slots":                {k: dict(v) for k, v in SLOTS.items()},
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
            risk_tier="T3",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s24_base_chain_max",
            handler_class="BaseChainMaxStrategy",
            tags=["base_chain", "l2", "morpho_blue_base", "aave_v3_base",
                  "moonwell_base", "cross_chain", "t3", "phase_gated", "s24"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "BaseChainMaxStrategy auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = BaseChainMaxStrategy()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
