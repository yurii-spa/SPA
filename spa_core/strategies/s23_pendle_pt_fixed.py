"""
spa_core/strategies/s23_pendle_pt_fixed.py — S23 Pendle PT Fixed Rate

S23: Pendle PT Fixed Rate
=========================
Fixed-rate DeFi via Pendle Principal Tokens (PT). PTs trade at a discount and
redeem 1:1 at maturity, locking in a fixed yield-to-maturity with lower variance
than floating-rate lending. The remaining half sits in a T1 anchor.

Allocation:
  pendle_pt (T2, 50%): highest-yield USDC-settled PT pool (PT-sUSDe / PT-USDC),
                       fixed YTM, ~7% locked (range 6–9%)
  sky_susds (T1, 30%): Sky/Spark sUSDS — T1 DSR anchor, ~6.5% APY
  aave      (T1, 20%): Aave V3 USDC — T1 lending anchor, ~4.2% APY

Weighted Target APY (defaults):
  0.50*7.0 + 0.30*6.5 + 0.20*4.2 = 3.50 + 1.95 + 0.84 = 6.29% → target 6–9%.

Fixed-rate property:
  The PT leg is read from PendlePTAdapter (live Pendle markets API). If PT data
  is unavailable (offline / no eligible market), the strategy uses a mock fixed
  rate of 7.0% for paper simulation (`MOCK_PT_APY`) and flags
  `pendle_pt_live=False`. Lower variance is the point: a PT locks the rate to
  maturity, so paper P&L is smooth vs floating pools.

Risk note:
  PTs carry maturity/liquidity risk (early exit is at market price, not par) and
  the underlying protocol's solvency. T2 classification. Advisory/read-only — the
  deterministic RiskPolicy gate retains final authority; approved=False is never
  overridden.

Rules: stdlib only · read-only/advisory · LLM FORBIDDEN · no execution imports.

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S23"
STRATEGY_NAME = "Pendle PT Fixed Rate"
TIER          = "T2"
DESCRIPTION   = (
    "Pendle PT Fixed Rate: PT 50% T2 (fixed YTM ~7%, PT-sUSDe/PT-USDC) + "
    "Sky sUSDS 30% T1 (~6.5%) + Aave V3 20% T1 (~4.2%). "
    "Target APY 6-9% locked, lower variance than floating. "
    "Mock 7% PT rate when live Pendle data unavailable."
)

# ─── Slots ────────────────────────────────────────────────────────────────────

SLOTS: Dict[str, Dict] = {
    "pendle_pt": {
        "adapter":      "pendle_pt",
        "weight":       0.50,
        "role":         "fixed_rate_engine",
        "tier":         "T2",
        "fallback_apy": 7.0,
        "description":  "Pendle PT — fixed YTM, ~7% locked",
    },
    "sky": {
        "adapter":      "spark_susds",
        "weight":       0.30,
        "role":         "t1_anchor",
        "tier":         "T1",
        "fallback_apy": 6.5,
        "description":  "Sky/Spark sUSDS — T1 DSR anchor, ~6.5% APY",
    },
    "aave": {
        "adapter":      "aave_v3",
        "weight":       0.20,
        "role":         "t1_anchor",
        "tier":         "T1",
        "fallback_apy": 4.2,
        "description":  "Aave V3 USDC — T1 lending anchor, ~4.2% APY",
    },
}

FALLBACK_APY: Dict[str, float] = {
    "pendle_pt":   7.0,
    "spark_susds": 6.5,
    "aave_v3":     4.2,
}

RISK_SCORES: Dict[str, float] = {
    "pendle_pt":   0.42,   # T2 maturity/liquidity + underlying solvency risk
    "spark_susds": 0.20,
    "aave_v3":     0.15,
}

# Mock fixed rate used when the live Pendle markets API is unreachable.
MOCK_PT_APY: float = 7.0

MIN_APY_ELIGIBLE: float = 1.0
MAX_APY_ELIGIBLE: float = 30.0

TARGET_APY_PCT:   float = 6.5
TARGET_APY_MIN:   float = 5.0
TARGET_APY_MAX:   float = 9.0
RISK_SCORE:       float = 0.36
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


class PendlePTFixedStrategy:
    """S23 — Pendle PT Fixed Rate (50% PT + 50% T1 anchor).

    Locks a fixed yield-to-maturity via Pendle PTs, falling back to a 7% mock
    rate for paper simulation when live markets are unavailable. Stdlib only,
    advisory/read-only.
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TIER           = TIER
    TARGET_APY_PCT = TARGET_APY_PCT
    RISK_SCORE     = RISK_SCORE
    MOCK_PT_APY    = MOCK_PT_APY

    def __init__(self) -> None:
        self._adapters: Dict[str, object] = {}
        self._simulate_history: List[Dict] = []
        self._pt_live: bool = False
        self._load_adapters()

    def _load_adapters(self) -> None:
        try:
            from spa_core.adapters.pendle_pt_adapter import PendlePTAdapter
            self._adapters["pendle_pt"] = PendlePTAdapter()
        except Exception:   # noqa: BLE001
            pass
        try:
            from spa_core.adapters.spark_susds_adapter import SparkSusdsAdapter
            self._adapters["spark_susds"] = SparkSusdsAdapter()
        except Exception:   # noqa: BLE001
            pass
        try:
            from spa_core.adapters.aave_v3 import AaveV3Adapter
            self._adapters["aave_v3"] = AaveV3Adapter()
        except Exception:   # noqa: BLE001
            pass

    # ── PT-specific ────────────────────────────────────────────────────────

    def get_pt_apy(self) -> float:
        """Live PT YTM (percent), or MOCK_PT_APY when unavailable.

        Sets `self._pt_live` to True only when a strictly-positive live rate is
        read from the Pendle adapter.
        """
        adapter = self._adapters.get("pendle_pt")
        if adapter is not None:
            try:
                raw = adapter.get_apy()  # type: ignore[attr-defined]
                apy = _norm_apy_pct(raw, 0.0)
                if apy > 0.0:
                    self._pt_live = True
                    return apy
            except Exception:   # noqa: BLE001
                pass
        self._pt_live = False
        return MOCK_PT_APY

    def pt_is_live(self) -> bool:
        """Whether the last PT APY read came from live data (vs mock)."""
        # Refresh the flag by re-reading.
        self.get_pt_apy()
        return self._pt_live

    # ── utilities ──────────────────────────────────────────────────────────

    def _get_adapter_apy(self, adapter_key: str) -> float:
        if adapter_key == "pendle_pt":
            return self.get_pt_apy()
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
        t1 = sum(s["weight"] for s in SLOTS.values() if s["tier"] == "T1")
        t2 = sum(s["weight"] for s in SLOTS.values() if s["tier"] == "T2")
        return {
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "pendle_pt_live":   self.pt_is_live(),
            "fixed_rate":       True,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "risk_note": (
                f"S23 Pendle PT Fixed Rate: PT T2={t2*100:.0f}% (fixed YTM) + "
                f"T1={t1*100:.0f}%. Lower variance via rate lock to maturity."
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
            "pendle_pt_live": self.pt_is_live(),
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
            "pendle_pt_live":            self._pt_live,
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
            "slots":                {k: dict(v) for k, v in SLOTS.items()},
            "fallback_apy":         dict(FALLBACK_APY),
            "risk_scores":          dict(RISK_SCORES),
            "mock_pt_apy":          MOCK_PT_APY,
            "target_apy_pct":       TARGET_APY_PCT,
            "target_apy_min":       TARGET_APY_MIN,
            "target_apy_max":       TARGET_APY_MAX,
            "risk_score":           RISK_SCORE,
            "max_drawdown_pct":     MAX_DRAWDOWN_PCT,
            "expected_apy":         self.get_expected_apy(),
            "pendle_pt_live":       self.pt_is_live(),
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
            module="spa_core.strategies.s23_pendle_pt_fixed",
            handler_class="PendlePTFixedStrategy",
            tags=["pendle", "pendle_pt", "fixed_rate", "principal_token",
                  "sky_susds", "aave_v3", "t2", "low_variance", "s23"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "PendlePTFixedStrategy auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = PendlePTFixedStrategy()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
