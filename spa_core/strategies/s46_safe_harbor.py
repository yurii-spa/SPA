"""
spa_core/strategies/s46_safe_harbor.py — S46 Stable-Only Safe Harbor

S46 Stable-Only Safe Harbor
===========================
The ultra-conservative mode of the SPA tournament: **100% T1 protocols,
never any T2**. Designed as a capital-preservation floor — the place to
park virtual capital when the operator wants the lowest possible risk and
is content with the blended T1 yield.

Target weights (sum = 100%, fully deployed into liquid T1 venues):
  Aave V3 mainnet  (T1, 40%) — deepest-liquidity blue-chip lending
  Compound V3      (T1, 35%) — Comet USDC mono-market
  Sky sUSDS        (T1, 25%) — Sky Savings Rate, most predictable APY

No cash slot: all three venues are instant-withdrawal liquid T1, so the
strategy runs fully deployed. The live cycle's RiskPolicy gate + allocator
remain authoritative and enforce the system-wide ≥5% cash buffer when the
book is actually rebalanced — S46 only expresses the protocol split.

Expected blended APY (fallback levels Aave 3.6 / Compound 3.9 / Sky 4.0):
  0.40*3.6 + 0.35*3.9 + 0.25*4.0 = 1.44 + 1.365 + 1.0 = 3.805% ≈ 3.8%

Risk: the lowest of all tournament strategies (100% T1, no leverage,
no T2, no exotic exposure).

Rules:
  - stdlib only, no external runtime dependencies
  - read-only / advisory — does NOT call execution/ or risk-agents
  - LLM FORBIDDEN in this module
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

STRATEGY_ID   = "S46"
STRATEGY_NAME = "Stable-Only Safe Harbor"
TIER          = "T1"
DESCRIPTION   = (
    "Ultra-conservative capital-preservation mode: 100% T1, never T2. "
    "Aave V3 40% + Compound V3 35% + Sky sUSDS 25%. Blended APY ~3.8%. "
    "Lowest risk of all tournament strategies."
)

# ─── Weights (sum = 1.0, all T1) ──────────────────────────────────────────────

WEIGHTS: Dict[str, float] = {
    "aave_v3":     0.40,
    "compound_v3": 0.35,
    "sky_susds":   0.25,
}

# ─── Target metrics ───────────────────────────────────────────────────────────

TARGET_APY_PCT: float = 3.8
TARGET_APY_MIN: float = 3.0
TARGET_APY_MAX: float = 4.5
RISK_SCORE:     float = 0.22          # lowest in the universe
MAX_DRAWDOWN_PCT: float = 5.0


class SafeHarborStrategy(AdapterAPYMixin):
    """S46 — Stable-Only Safe Harbor: 100% T1, never T2.

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
        """Target USD allocation per protocol. Ineligible slots roll to cash."""
        if capital_usd <= 0.0:
            return {k: 0.0 for k in WEIGHTS}
        out: Dict[str, float] = {}
        for key, w in WEIGHTS.items():
            if self._is_eligible(key):
                out[key] = round(capital_usd * w, 6)
        return out

    def get_expected_apy(self) -> float:
        """Blended APY (%) across eligible slots; ineligible slots → 0 (cash)."""
        weighted = 0.0
        for key, w in WEIGHTS.items():
            if self._is_eligible(key):
                weighted += w * self._get_adapter_apy(key)
        return round(weighted, 4)

    def get_risk_summary(self) -> Dict:
        """All-T1 verdict: no T2 exposure, every slot ≤ 40% T1 cap."""
        t1 = sum(w for k, w in WEIGHTS.items())
        t1_per_protocol_ok = all(w <= T1_PER_PROTOCOL_CAP + 1e-9 for w in WEIGHTS.values())
        return {
            "risk_score":         RISK_SCORE,
            "t1_weight_pct":      round(t1 * 100.0, 2),
            "t2_weight_pct":      0.0,
            "t1_per_protocol_ok": t1_per_protocol_ok,
            "no_t2_exposure":     True,
            "adr_compliant":      t1_per_protocol_ok,
            "risk_note": (
                f"S46 Safe Harbor: 100% T1 ({t1*100:.0f}%), zero T2. "
                f"Aave 40% / Compound 35% / Sky 25%, all ≤ 40% T1 cap. "
                f"Lowest-risk tournament strategy."
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
                "tier":     "T1",
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
            "risk_score":     RISK_SCORE,
            "overall_status": status,
        }

    def simulate(self, capital_usd: float) -> Dict:
        """One-day simulation: allocation, per-slot annual yield, blended APY."""
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
                "tier":             "T1",
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
            risk_tier="T1",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s46_safe_harbor",
            handler_class="SafeHarborStrategy",
            tags=[
                "s46", "safe_harbor", "t1", "conservative", "capital_preservation",
                "no_t2", "aave_v3", "compound_v3", "sky_susds", "income",
            ],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "SafeHarborStrategy auto-registration failed: %s", exc
        )


_register()
