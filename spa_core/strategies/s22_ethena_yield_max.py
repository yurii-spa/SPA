"""
spa_core/strategies/s22_ethena_yield_max.py — S22 Ethena Yield Maximizer

S22: Ethena Yield Maximizer
===========================
Aggressive synthetic-dollar yield strategy anchored on Ethena sUSDe (T3),
with a T1 safety base of Sky sUSDS + Aave V3.

Allocation:
  ethena_susde (T3, 40%): Ethena sUSDe staking vault — funding + staking, ~12% APY
  sky_susds    (T1, 30%): Sky / Spark sUSDS DSR yield — T1 anchor, ~6.5% APY
  aave         (T1, 30%): Aave V3 USDC lending — T1 anchor, ~4.2% APY

Weighted Target APY (defaults):
  0.40*12.0 + 0.30*6.5 + 0.30*4.2 = 4.80 + 1.95 + 1.26 = 8.01% → target 8–12%.

Kill switch — ethena_depeg:
  If the live USDe peg is unhealthy (SusdeAdapter.is_peg_healthy() == False),
  the 40% Ethena bucket is reallocated to the T1 safe harbor (Sky + Aave),
  split 50/50. This protects capital from a synthetic-dollar depeg event.

Risk note:
  Ethena sUSDe is T3 (RISK_SCORE 0.62, 7-day unstake cooldown). The deterministic
  RiskPolicy gate (T3_CAP 10%) and `apply_risk_policy` retain final authority and
  may clip the 40% target — this module is advisory/read-only and never overrides
  approved=False. The 40% target is the strategy's *raw* preference.

Rules:
  - stdlib only, no external deps in runtime code
  - read-only / advisory — never imports execution/ or risk agents
  - LLM FORBIDDEN in this module
  - approved=False from RiskPolicy is never overridden
  - atomic data/ writes (tmp + os.replace) — not used here (in-memory only)

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S22"
STRATEGY_NAME = "Ethena Yield Maximizer"
TIER          = "T3"   # T3-dominant: 40% Ethena sUSDe synthetic-dollar exposure
DESCRIPTION   = (
    "Ethena Yield Maximizer: sUSDe 40% T3 (funding+staking, ~12% APY) + "
    "Sky sUSDS 30% T1 (~6.5% APY) + Aave V3 30% T1 (~4.2% APY). "
    "Target APY 8-12%. Kill switch: ethena_depeg → T1 safe harbor. "
    "T3 sUSDe exceeds RiskPolicy T3_CAP 10% — advisory; gate has final say."
)

# ─── Slots ────────────────────────────────────────────────────────────────────

SLOTS: Dict[str, Dict] = {
    "ethena": {
        "adapter":      "susde",
        "weight":       0.40,
        "role":         "t3_yield_engine",
        "tier":         "T3",
        "fallback_apy": 12.0,
        "description":  "Ethena sUSDe — funding+staking yield engine, ~12% APY",
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
        "weight":       0.30,
        "role":         "t1_anchor",
        "tier":         "T1",
        "fallback_apy": 4.2,
        "description":  "Aave V3 USDC — T1 lending anchor, ~4.2% APY",
    },
}

# T1 safe-harbor slots that absorb the Ethena bucket on depeg kill-switch.
_SAFE_HARBOR_SLOTS: List[str] = ["sky", "aave"]
_KILL_SLOT: str = "ethena"

FALLBACK_APY: Dict[str, float] = {
    "susde":       12.0,
    "spark_susds": 6.5,
    "aave_v3":     4.2,
}

RISK_SCORES: Dict[str, float] = {
    "susde":       0.62,   # T3 synthetic dollar + funding-rate risk
    "spark_susds": 0.20,   # T1 MakerDAO-backed
    "aave_v3":     0.15,   # T1 blue-chip lending
}

MIN_APY_ELIGIBLE: float = 1.0
MAX_APY_ELIGIBLE: float = 30.0

TARGET_APY_PCT:    float = 8.0
TARGET_APY_MIN:    float = 6.0
TARGET_APY_MAX:    float = 14.0
RISK_SCORE:        float = 0.45
MAX_DRAWDOWN_PCT:  float = 5.0
_HISTORY_MAX:      int   = 365


def _norm_apy_pct(value: object, fallback: float) -> float:
    """Normalize an adapter's get_apy() return to *percent*.

    SPA adapters are inconsistent: newer ones (susde, spark_susds, Base) return
    percent (e.g. 6.5), older ones (aave_v3, yearn_v3) return a decimal (0.065).
    Realistic stablecoin APYs are 1–30%, so a positive value < 1.0 is a decimal
    and is scaled ×100; a value ≥ 1.0 is already percent. None/0/invalid →
    fallback.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf guard
        return fallback
    if v <= 0.0:
        return fallback
    return v * 100.0 if v < 1.0 else v


class EthenaYieldMaxStrategy:
    """S22 — Ethena Yield Maximizer (40% sUSDe T3 + 60% T1 anchor).

    Aggressive synthetic-dollar yield with a T1 base and an ethena_depeg kill
    switch that rotates the sUSDe bucket into Sky+Aave when USDe loses its peg.
    Stdlib only, advisory/read-only.
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

    # ── adapter loading ────────────────────────────────────────────────────

    def _load_adapters(self) -> None:
        try:
            from spa_core.adapters.susde_adapter import SusdeAdapter
            self._adapters["susde"] = SusdeAdapter()
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

    def ethena_depeg_active(self) -> bool:
        """True if the Ethena USDe peg is unhealthy → kill switch should fire.

        Uses SusdeAdapter.is_peg_healthy() (default-safe to healthy on missing
        data). If the adapter is unavailable, returns False (no false kill).
        """
        adapter = self._adapters.get("susde")
        if adapter is None:
            return False
        try:
            return not bool(adapter.is_peg_healthy())  # type: ignore[attr-defined]
        except Exception:   # noqa: BLE001
            return False

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
        """Target USD allocation per adapter.

        On ethena_depeg the 40% sUSDe bucket is redistributed 50/50 into the T1
        safe harbor (Sky + Aave).
        """
        if capital_usd <= 0.0:
            return {SLOTS[s]["adapter"]: 0.0 for s in SLOTS}

        depeg = self.ethena_depeg_active()
        allocation: Dict[str, float] = {}

        for slot_name, slot_cfg in SLOTS.items():
            adapter_key = slot_cfg["adapter"]
            weight = slot_cfg["weight"]

            if slot_name == _KILL_SLOT and depeg:
                # Redistribute Ethena bucket to T1 safe harbor (50/50).
                bucket = capital_usd * weight
                share = bucket / len(_SAFE_HARBOR_SLOTS)
                for hs in _SAFE_HARBOR_SLOTS:
                    hk = SLOTS[hs]["adapter"]
                    allocation[hk] = allocation.get(hk, 0.0) + share
                continue

            allocation[adapter_key] = allocation.get(adapter_key, 0.0) + capital_usd * weight

        return {k: round(v, 6) for k, v in allocation.items()}

    def get_expected_apy(self) -> float:
        allocation = self.get_allocation(1.0)
        total = sum(allocation.values())
        if total <= 0.0:
            return TARGET_APY_PCT
        weighted = sum(self._get_adapter_apy(k) * w for k, w in allocation.items())
        return round(weighted / total, 4)

    def get_risk_summary(self) -> Dict:
        depeg = self.ethena_depeg_active()
        t1 = sum(s["weight"] for s in SLOTS.values() if s["tier"] == "T1")
        t3 = sum(s["weight"] for s in SLOTS.values() if s["tier"] == "T3")
        if depeg:
            # All capital sits in T1 when the kill switch fires.
            t1, t3 = 1.0, 0.0
        return {
            "risk_score":        RISK_SCORE,
            "t1_weight_pct":     round(t1 * 100.0, 2),
            "t3_weight_pct":     round(t3 * 100.0, 2),
            "ethena_depeg":      depeg,
            "kill_switch":       "ethena_depeg",
            "t3_cap_note":       "sUSDe target 40% > RiskPolicy T3_CAP 10% — gate clips; advisory only.",
            "max_drawdown_pct":  MAX_DRAWDOWN_PCT,
            "risk_note": (
                f"S22 Ethena Yield Maximizer: sUSDe T3={t3*100:.0f}% + T1={t1*100:.0f}%. "
                f"ethena_depeg kill switch {'ACTIVE → T1 safe harbor' if depeg else 'armed'}."
            ),
        }

    def get_health(self) -> Dict:
        slots_info: Dict[str, Dict] = {}
        eligible_count = 0
        for slot_name, slot_cfg in SLOTS.items():
            adapter_key = slot_cfg["adapter"]
            eligible = self._is_eligible(adapter_key)
            if eligible:
                eligible_count += 1
            slots_info[slot_name] = {
                "adapter":  adapter_key,
                "weight":   slot_cfg["weight"],
                "tier":     slot_cfg["tier"],
                "role":     slot_cfg["role"],
                "eligible": eligible,
                "apy":      self._get_adapter_apy(adapter_key),
                "loaded":   adapter_key in self._adapters,
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
            "ethena_depeg":   self.ethena_depeg_active(),
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
            module="spa_core.strategies.s22_ethena_yield_max",
            handler_class="EthenaYieldMaxStrategy",
            tags=["ethena", "susde", "sky_susds", "aave_v3", "high_yield",
                  "t3", "synthetic_dollar", "depeg_kill_switch", "s22"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "EthenaYieldMaxStrategy auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = EthenaYieldMaxStrategy()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
