"""
spa_core/strategies/s40_pendle_pt_fixed.py — S40 Pendle PT Fixed Rate

S40: Pendle PT Fixed Rate (dual-PT + T1 anchors)
================================================
A fixed-rate-tilted portfolio built on Pendle **Principal Tokens (PT)** — the
safe leg of Pendle (buy-at-discount, redeem-at-par, fixed YTM) — anchored by two
T1 lending blue-chips. This is distinct from S23 (single PT + Sky/Aave) and from
the YT strategies (S7) which trade the *speculative* amplified-yield leg.

Allocation:
  pendle_pt_susde (T2, 20%): Pendle PT-sUSDe, ~10% fixed YTM
  pendle_pt_usdc  (T2, 15%): Pendle PT-USDC / PT-crvUSD, ~8% fixed YTM
  aave_v3         (T1, 35%): Aave V3 USDC mainnet — primary anchor, ~3.1% APY
  compound_v3     (T1, 25%): Compound V3 (Comet USDC) — second anchor, ~3.3% APY
  cash            (—,  5%):  idle USDC buffer (RiskPolicy min cash buffer)

Weighted Target APY (defaults):
  0.20*10 + 0.15*8 + 0.35*3.1 + 0.25*3.3 + 0.05*0
  = 2.00 + 1.20 + 1.085 + 0.825 + 0 = 5.11% → band 4.5–6.0%.

T2 exposure = 35% (both PT legs) — within the ADR-019 T2 ≤ 50% portfolio cap.

Kill switch (maturity rotation):
  If *either* PT leg is within 30 days of maturity (or its sub-Morpho kill
  switch trips), that leg's weight is rotated into Aave V3 (the T1 anchor) for
  the cycle. The cash buffer is preserved. This keeps capital out of an
  unwinding PT whose effective yield has gone to 0%.

Risk note:
  PTs carry maturity/liquidity risk (early exit is at AMM market price, not par)
  and the underlying protocol's solvency. T2 classification. Advisory/read-only:
  the deterministic RiskPolicy gate retains final authority; approved=False is
  never overridden.

Rules: stdlib only · read-only/advisory · LLM FORBIDDEN · no execution imports.

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S40"
STRATEGY_NAME = "Pendle PT Fixed Rate"
TIER          = "T2"
DESCRIPTION   = (
    "Pendle PT Fixed Rate (dual-PT): PT-sUSDe 20% T2 (~10% fixed) + "
    "PT-USDC 15% T2 (~8% fixed) + Aave V3 35% T1 (~3.1%) + Compound V3 25% T1 "
    "(~3.3%) + 5% cash. Target APY ~5.1%. Maturity kill switch: a PT within "
    "30d of maturity rotates to Aave V3."
)

# ─── Slots ────────────────────────────────────────────────────────────────────

SLOTS: Dict[str, Dict] = {
    "pendle_pt_susde": {
        "adapter":      "pendle_pt_susde",
        "weight":       0.20,
        "role":         "fixed_rate_engine",
        "tier":         "T2",
        "fallback_apy": 10.0,
        "description":  "Pendle PT-sUSDe — fixed YTM, ~10% locked",
    },
    "pendle_pt_usdc": {
        "adapter":      "pendle_pt_usdc",
        "weight":       0.15,
        "role":         "fixed_rate_engine",
        "tier":         "T2",
        "fallback_apy": 8.0,
        "description":  "Pendle PT-USDC/crvUSD — fixed YTM, ~8% locked",
    },
    "aave": {
        "adapter":      "aave_v3",
        "weight":       0.35,
        "role":         "t1_anchor",
        "tier":         "T1",
        "fallback_apy": 3.1,
        "description":  "Aave V3 USDC mainnet — primary T1 anchor, ~3.1% APY",
    },
    "compound": {
        "adapter":      "compound_v3",
        "weight":       0.25,
        "role":         "t1_anchor",
        "tier":         "T1",
        "fallback_apy": 3.3,
        "description":  "Compound V3 (Comet USDC) — second T1 anchor, ~3.3% APY",
    },
    "cash": {
        "adapter":      "cash",
        "weight":       0.05,
        "role":         "buffer",
        "tier":         "T0",
        "fallback_apy": 0.0,
        "description":  "Idle USDC buffer (RiskPolicy min cash buffer)",
    },
}

FALLBACK_APY: Dict[str, float] = {
    "pendle_pt_susde": 10.0,
    "pendle_pt_usdc":  8.0,
    "aave_v3":         3.1,
    "compound_v3":     3.3,
    "cash":            0.0,
}

RISK_SCORES: Dict[str, float] = {
    "pendle_pt_susde": 0.42,
    "pendle_pt_usdc":  0.38,
    "aave_v3":         0.15,
    "compound_v3":     0.15,
    "cash":            0.0,
}

# The T1 anchor that absorbs a PT leg when it is rotated out near maturity.
ROTATION_TARGET = "aave_v3"

MIN_APY_ELIGIBLE: float = 1.0
MAX_APY_ELIGIBLE: float = 30.0

TARGET_APY_PCT:   float = 5.1
TARGET_APY_MIN:   float = 4.5
TARGET_APY_MAX:   float = 6.0
RISK_SCORE:       float = 0.28
MAX_DRAWDOWN_PCT: float = 5.0
_HISTORY_MAX:     int   = 365


def _norm_apy_pct(value: object, fallback: float) -> float:
    """Normalize an adapter get_apy() return to percent.

    Adapters may return APY as a decimal (0.10) or a percent (10.0); both are
    accepted. Non-numeric / non-positive / non-finite values fall back. A PT
    leg reporting exactly 0.0 (unwinding) returns 0.0 — *not* the fallback —
    so the maturity signal is preserved.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):
        return fallback
    if v == 0.0:
        return 0.0
    if v < 0.0:
        return fallback
    return v * 100.0 if v < 1.0 else v


class PendlePTFixedRateStrategy:
    """S40 — Pendle PT Fixed Rate (dual PT + dual T1 anchor + cash).

    Locks fixed yields-to-maturity via two Pendle PT legs, anchored by Aave V3
    and Compound V3. A maturity kill switch rotates any PT within 30 days of
    maturity into the Aave V3 anchor. Stdlib only, advisory/read-only.
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
        try:
            from spa_core.adapters.pendle_pt_susde_adapter import PendlePTSusdeAdapter
            self._adapters["pendle_pt_susde"] = PendlePTSusdeAdapter()
        except Exception:   # noqa: BLE001
            pass
        try:
            from spa_core.adapters.pendle_pt_usdc_adapter import PendlePTUsdcAdapter
            self._adapters["pendle_pt_usdc"] = PendlePTUsdcAdapter()
        except Exception:   # noqa: BLE001
            pass
        try:
            from spa_core.adapters.aave_v3 import AaveV3Adapter
            self._adapters["aave_v3"] = AaveV3Adapter()
        except Exception:   # noqa: BLE001
            pass
        try:
            from spa_core.adapters.compound_v3_adapter import CompoundV3Adapter
            self._adapters["compound_v3"] = CompoundV3Adapter()
        except Exception:   # noqa: BLE001
            pass

    # ── PT maturity / rotation ────────────────────────────────────────────

    def _pt_should_rotate(self, adapter_key: str) -> bool:
        """True when a PT leg is near maturity or its kill switch tripped.

        Defaults to False when the adapter is unavailable or lacks the hook —
        rotation is a safety override, not a fail-open behaviour.
        """
        adapter = self._adapters.get(adapter_key)
        if adapter is None:
            return False
        try:
            return bool(adapter.should_rotate())  # type: ignore[attr-defined]
        except Exception:   # noqa: BLE001
            return False

    def pending_rotations(self) -> List[str]:
        """List of PT adapter keys currently flagged for rotation to Aave."""
        return [
            cfg["adapter"]
            for cfg in SLOTS.values()
            if cfg["role"] == "fixed_rate_engine"
            and self._pt_should_rotate(cfg["adapter"])
        ]

    # ── utilities ──────────────────────────────────────────────────────────

    def _get_adapter_apy(self, adapter_key: str) -> float:
        if adapter_key == "cash":
            return 0.0
        adapter = self._adapters.get(adapter_key)
        fallback = FALLBACK_APY.get(adapter_key, 0.0)
        if adapter is not None:
            try:
                return _norm_apy_pct(adapter.get_apy(), fallback)  # type: ignore[attr-defined]
            except Exception:   # noqa: BLE001
                pass
        return fallback

    def _is_eligible(self, adapter_key: str) -> bool:
        if adapter_key == "cash":
            return True
        adapter = self._adapters.get(adapter_key)
        if adapter is None:
            return True
        try:
            return bool(adapter.is_eligible())  # type: ignore[attr-defined]
        except Exception:   # noqa: BLE001
            return True

    # ── public API ─────────────────────────────────────────────────────────

    def get_allocation(self, capital_usd: float) -> Dict[str, float]:
        """Target USD allocation per adapter, after maturity rotation.

        Any PT leg flagged by :meth:`pending_rotations` has its weight folded
        into the Aave V3 anchor (ROTATION_TARGET); the cash buffer is preserved.
        """
        if capital_usd <= 0.0:
            return {}
        rotate = set(self.pending_rotations())
        allocation: Dict[str, float] = {}
        for slot_cfg in SLOTS.values():
            key = slot_cfg["adapter"]
            target_key = ROTATION_TARGET if key in rotate else key
            allocation[target_key] = (
                allocation.get(target_key, 0.0) + capital_usd * slot_cfg["weight"]
            )
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
        cash = sum(s["weight"] for s in SLOTS.values() if s["tier"] == "T0")
        rotations = self.pending_rotations()
        return {
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "cash_weight_pct":  round(cash * 100.0, 2),
            "fixed_rate":       True,
            "pending_rotations": rotations,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "risk_note": (
                f"S40 Pendle PT Fixed Rate: dual-PT T2={t2*100:.0f}% (fixed YTM) "
                f"+ T1={t1*100:.0f}% anchors + {cash*100:.0f}% cash. "
                f"Maturity kill switch active ({len(rotations)} leg(s) rotating)."
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
            "strategy_id":       STRATEGY_ID,
            "name":              STRATEGY_NAME,
            "eligible_slots":    eligible_count,
            "total_slots":       len(SLOTS),
            "slots":             slots_info,
            "expected_apy":      self.get_expected_apy(),
            "target_apy":        TARGET_APY_PCT,
            "pending_rotations": self.pending_rotations(),
            "overall_status":    status,
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
            "pending_rotations":         self.pending_rotations(),
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
            "rotation_target":      ROTATION_TARGET,
            "target_apy_pct":       TARGET_APY_PCT,
            "target_apy_min":       TARGET_APY_MIN,
            "target_apy_max":       TARGET_APY_MAX,
            "risk_score":           RISK_SCORE,
            "max_drawdown_pct":     MAX_DRAWDOWN_PCT,
            "expected_apy":         self.get_expected_apy(),
            "pending_rotations":    self.pending_rotations(),
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
            module="spa_core.strategies.s40_pendle_pt_fixed",
            handler_class="PendlePTFixedRateStrategy",
            tags=["pendle", "pendle_pt", "fixed_rate", "principal_token",
                  "pendle_pt_susde", "pendle_pt_usdc", "aave_v3", "compound_v3",
                  "t2", "dual_pt", "maturity_rotation", "s40"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "PendlePTFixedRateStrategy auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = PendlePTFixedRateStrategy()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
