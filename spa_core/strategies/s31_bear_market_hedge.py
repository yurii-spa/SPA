"""
spa_core/strategies/s31_bear_market_hedge.py — S31 Bear Market Hedge

S31: Bear Market Hedge
======================
A regime-aware defensive strategy. Its job is to *protect the portfolio in down
markets* — the exact failure mode revealed by the S7 Pendle-YT backtest, where
the speculative YT leg posted −14.28% APY with a 3.73% max drawdown in the bear
scenario.

Whereas S7 holds a fixed 40% YT sleeve regardless of conditions, S31 detects the
market regime each day and rotates between two target allocations:

  BEAR (capital preservation, target 3.5–4.5% APY, max DD < 0.5%):
    aave_v3       40%  (T1 ultra-safe lending)
    compound_v3   40%  (T1 ultra-safe lending)
    sky_susds     15%  (T1 sUSDS — very stable DSR anchor)
    cash           5%
    → ZERO T2, ZERO Pendle/YT exposure.

  BULL (growth, target 6–8% APY):
    aave_v3       25%  (T1)
    compound_v3   25%  (T1)
    fluid       17.5%  (T2)
    ethena      17.5%  (T2)
    pendle_pt     10%  (Pendle PT — fixed-rate, far safer than YT)
    cash           5%

Regime detection signals (any one trips BEAR by default — a hedge errs toward
safety):
  1. Aave USDC utilization < 50%  → low borrowing demand = bear
  2. Average T2 APY < 4%          → yields compressing = bear
  3. Any protocol APY declining > 1%/week → momentum rolling over = bear

Transition (anti-whipsaw):
  The book does not snap between allocations. On a regime change it rotates
  gradually over TRANSITION_DAYS = 7 days, ~14.29% (= 1/7) of the portfolio per
  day, so a one-day false signal cannot fully de-risk and re-risk the book.

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
The deterministic RiskPolicy gate retains final authority; `approved=False` is
never overridden. Pendle PT is advisory only (ADR-021 governs the YT family;
S31 deliberately avoids YT entirely).

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S31"
STRATEGY_NAME = "Bear Market Hedge"
TIER          = "T1"   # net-defensive; bull mode adds a capped T2/PT growth sleeve
DESCRIPTION   = (
    "Bear Market Hedge: regime-aware defensive rotation. BEAR = 80% T1 "
    "(Aave+Compound) + 15% Sky sUSDS + 5% cash, zero T2/YT (target 3.5-4.5% APY, "
    "DD<0.5%). BULL = 50% T1 + 35% T2 (Fluid/Ethena) + 10% Pendle PT + 5% cash "
    "(target 6-8% APY). Gradual 7-day / ~14%/day transition to avoid whipsaws. "
    "Protects the book when speculative strategies (e.g. S7 YT) fail."
)

# ─── Protocol universe (unified across regimes; weight 0 where absent) ─────────

PROTOCOLS: List[str] = [
    "aave_v3",      # T1 lending
    "compound_v3",  # T1 lending
    "sky_susds",    # T1 sUSDS DSR anchor
    "fluid",        # T2
    "ethena",       # T2
    "pendle_pt",    # Pendle PT — fixed-rate (NOT YT)
    "cash",         # idle reserve, 0% APY
]

TIER_OF: Dict[str, str] = {
    "aave_v3":     "T1",
    "compound_v3": "T1",
    "sky_susds":   "T1",
    "fluid":       "T2",
    "ethena":      "T2",
    "pendle_pt":   "T3",   # Pendle PT — fixed-rate; conservatively bucketed T3
    "cash":        "T1",
}

# Target weights per regime (each column sums to 1.0).
BEAR_WEIGHTS: Dict[str, float] = {
    "aave_v3":     0.40,
    "compound_v3": 0.40,
    "sky_susds":   0.15,
    "fluid":       0.0,
    "ethena":      0.0,
    "pendle_pt":   0.0,
    "cash":        0.05,
}

BULL_WEIGHTS: Dict[str, float] = {
    "aave_v3":     0.25,
    "compound_v3": 0.25,
    "sky_susds":   0.0,
    "fluid":       0.175,
    "ethena":      0.175,
    "pendle_pt":   0.10,
    "cash":        0.05,
}

# Conservative default annual APYs (%) — fallbacks when live feed is unavailable.
APY_DEFAULTS: Dict[str, float] = {
    "aave_v3":     4.0,
    "compound_v3": 4.5,
    "sky_susds":   6.0,
    "fluid":       8.0,
    "ethena":     10.0,
    "pendle_pt":   8.5,
    "cash":        0.0,
}

# ─── Regime detection thresholds ──────────────────────────────────────────────

AAVE_UTIL_BEAR_THRESHOLD: float = 0.50   # utilization (0..1) below this → bear
T2_APY_BEAR_THRESHOLD:    float = 4.0    # avg T2 APY (%) below this → bear
APY_DECLINE_BEAR_THRESHOLD: float = 1.0  # any protocol declining > this %/week → bear

# A hedge errs toward safety: any single bear signal trips BEAR.
BEAR_TRIGGER: int = 1

# ─── Transition (anti-whipsaw) ────────────────────────────────────────────────

TRANSITION_DAYS: int = 7
DAILY_ROTATION_FRACTION: float = 1.0 / TRANSITION_DAYS   # ≈ 0.142857
DAILY_ROTATION_PCT: float = round(100.0 / TRANSITION_DAYS, 4)  # ≈ 14.2857

# ─── Targets / risk ───────────────────────────────────────────────────────────

BEAR_TARGET_APY_MIN: float = 3.5
BEAR_TARGET_APY_MAX: float = 4.5
BULL_TARGET_APY_MIN: float = 6.0
BULL_TARGET_APY_MAX: float = 8.0

TARGET_APY_MIN:   float = BEAR_TARGET_APY_MIN
TARGET_APY_MAX:   float = BULL_TARGET_APY_MAX
RISK_SCORE:       float = 0.22   # net-defensive
MAX_DRAWDOWN_PCT: float = 2.0    # bull sleeve cap; bear regime targets < 0.5%
_HISTORY_MAX:     int   = 365


def _regime_weights(regime: str) -> Dict[str, float]:
    """Return the target weight map for a regime ('bear' default-safe)."""
    return dict(BULL_WEIGHTS) if str(regime).lower() == "bull" else dict(BEAR_WEIGHTS)


class BearMarketHedgeStrategy:
    """S31 — Bear Market Hedge.

    Detects the market regime from live-ish signals and rotates gradually
    (7-day, ~14%/day) between a capital-preservation BEAR book and a growth
    BULL book. Stdlib only, advisory/read-only — never mutates allocator/risk/
    execution state.
    """

    STRATEGY_ID    = STRATEGY_ID
    STRATEGY_NAME  = STRATEGY_NAME
    TIER           = TIER
    RISK_SCORE     = RISK_SCORE

    def __init__(self, initial_regime: str = "bear") -> None:
        # Start defensively unless told otherwise.
        self._active_regime: str = "bull" if str(initial_regime).lower() == "bull" else "bear"
        self._current_weights: Dict[str, float] = _regime_weights(self._active_regime)
        self._start_weights: Dict[str, float] = dict(self._current_weights)
        self._transition_day: int = TRANSITION_DAYS   # already settled at target
        self._simulate_history: List[Dict] = []

    # ── Regime detection ────────────────────────────────────────────────────

    @staticmethod
    def _norm_util(util: object) -> Optional[float]:
        """Normalize utilization to a 0..1 fraction (accepts 0.45 or 45.0)."""
        if isinstance(util, bool) or not isinstance(util, (int, float)):
            return None
        v = float(util)
        if v != v:  # NaN
            return None
        return v / 100.0 if v > 1.0 else v

    def bear_signals(self, signals: Optional[Dict]) -> Dict[str, bool]:
        """Evaluate the three bear-detection signals.

        Args:
            signals: {
                "aave_utilization":       float (0..1 or 0..100),
                "avg_t2_apy":             float (percent),
                "max_weekly_apy_decline": float (percent/week, magnitude > 0),
            }  — any key may be omitted (→ that signal is False).

        Returns:
            {signal_name: bool} for the three signals.
        """
        signals = signals or {}
        util = self._norm_util(signals.get("aave_utilization"))
        avg_t2 = signals.get("avg_t2_apy")
        decline = signals.get("max_weekly_apy_decline")

        return {
            "low_utilization": util is not None and util < AAVE_UTIL_BEAR_THRESHOLD,
            "low_t2_apy": isinstance(avg_t2, (int, float)) and not isinstance(avg_t2, bool)
                          and float(avg_t2) < T2_APY_BEAR_THRESHOLD,
            "apy_declining": isinstance(decline, (int, float)) and not isinstance(decline, bool)
                             and float(decline) > APY_DECLINE_BEAR_THRESHOLD,
        }

    def detect_regime(self, signals: Optional[Dict]) -> str:
        """Return 'bear' or 'bull' from the signal set (any signal → bear)."""
        fired = sum(1 for v in self.bear_signals(signals).values() if v)
        return "bear" if fired >= BEAR_TRIGGER else "bull"

    # ── Allocation ──────────────────────────────────────────────────────────

    def regime_weights(self, regime: str) -> Dict[str, float]:
        """Public accessor for a regime's target weight map."""
        return _regime_weights(regime)

    def get_allocation(self, capital_usd: float, regime: Optional[str] = None) -> Dict[str, float]:
        """Target USD allocation for a regime (instant, ignores transition state).

        Args:
            capital_usd: portfolio size in USD.
            regime: 'bear' | 'bull'. Defaults to the currently active regime.
        """
        regime = regime if regime is not None else self._active_regime
        weights = _regime_weights(regime)
        if capital_usd <= 0.0:
            return {p: 0.0 for p in PROTOCOLS}
        return {p: round(capital_usd * weights.get(p, 0.0), 6) for p in PROTOCOLS}

    def get_current_weights(self) -> Dict[str, float]:
        """Current (possibly mid-transition) weight map."""
        return dict(self._current_weights)

    def get_current_allocation(self, capital_usd: float) -> Dict[str, float]:
        """USD allocation at the *current* (mid-transition) weights."""
        if capital_usd <= 0.0:
            return {p: 0.0 for p in PROTOCOLS}
        return {p: round(capital_usd * self._current_weights.get(p, 0.0), 6) for p in PROTOCOLS}

    # ── Transition state machine ────────────────────────────────────────────

    @property
    def active_regime(self) -> str:
        return self._active_regime

    @property
    def transition_progress(self) -> float:
        """0.0 → 1.0 progress of the in-flight rotation."""
        return min(1.0, self._transition_day / float(TRANSITION_DAYS))

    def is_transitioning(self) -> bool:
        return self.transition_progress < 1.0

    def step_day(self, regime: str) -> Dict[str, float]:
        """Advance one day toward `regime`'s target, rotating ≤ ~14% of book.

        On a regime change the current weights are snapshotted as the start of a
        fresh 7-day rotation. Each subsequent call moves DAILY_ROTATION_FRACTION
        (1/7) of the way from start → target. Returns the new current weights.
        """
        regime = "bull" if str(regime).lower() == "bull" else "bear"
        target = _regime_weights(regime)

        if regime != self._active_regime:
            # New regime: begin a fresh gradual rotation from where we are now.
            self._active_regime = regime
            self._start_weights = dict(self._current_weights)
            self._transition_day = 0

        if self._current_weights != target:
            self._transition_day += 1
            progress = self.transition_progress
            if progress >= 1.0:
                self._current_weights = dict(target)
            else:
                self._current_weights = {
                    p: self._start_weights.get(p, 0.0)
                       + (target.get(p, 0.0) - self._start_weights.get(p, 0.0)) * progress
                    for p in PROTOCOLS
                }
        return dict(self._current_weights)

    # ── APY / expectations ──────────────────────────────────────────────────

    def _apy(self, protocol: str, apy_map: Optional[Dict[str, float]]) -> float:
        if apy_map and protocol in apy_map:
            v = apy_map[protocol]
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
        return APY_DEFAULTS.get(protocol, 0.0)

    def get_expected_apy(self, regime: Optional[str] = None,
                         apy_map: Optional[Dict[str, float]] = None) -> float:
        """Weighted annual APY (%) for a regime's target book."""
        regime = regime if regime is not None else self._active_regime
        weights = _regime_weights(regime)
        return round(sum(w * self._apy(p, apy_map) for p, w in weights.items()), 4)

    def current_expected_apy(self, apy_map: Optional[Dict[str, float]] = None) -> float:
        """Weighted APY (%) at the current (mid-transition) weights."""
        return round(sum(w * self._apy(p, apy_map)
                         for p, w in self._current_weights.items()), 4)

    # ── Risk / health summaries ─────────────────────────────────────────────

    def get_risk_summary(self, regime: Optional[str] = None) -> Dict:
        regime = regime if regime is not None else self._active_regime
        weights = _regime_weights(regime)
        t1 = sum(w for p, w in weights.items() if TIER_OF.get(p) == "T1")
        t2 = sum(w for p, w in weights.items() if TIER_OF.get(p) == "T2")
        t3 = sum(w for p, w in weights.items() if TIER_OF.get(p) == "T3")
        return {
            "regime":           regime,
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "t3_weight_pct":    round(t3 * 100.0, 2),
            "yt_exposure_pct":  0.0,   # S31 never holds Pendle YT
            "cash_pct":         round(weights.get("cash", 0.0) * 100.0, 2),
            "max_drawdown_pct": 0.5 if regime == "bear" else MAX_DRAWDOWN_PCT,
            "risk_note": (
                f"S31 {regime.upper()}: T1={t1*100:.0f}% T2={t2*100:.0f}% "
                f"PT={t3*100:.0f}% — zero YT. "
                + ("Capital preservation." if regime == "bear" else "Capped growth sleeve.")
            ),
        }

    def get_health(self, signals: Optional[Dict] = None) -> Dict:
        sig = self.bear_signals(signals)
        regime = self.detect_regime(signals)
        return {
            "strategy_id":     STRATEGY_ID,
            "name":            STRATEGY_NAME,
            "detected_regime": regime,
            "active_regime":   self._active_regime,
            "transitioning":   self.is_transitioning(),
            "transition_progress": round(self.transition_progress, 4),
            "bear_signals":    sig,
            "bear_signals_fired": sum(1 for v in sig.values() if v),
            "expected_apy":    self.get_expected_apy(regime, None),
            "overall_status":  "ok",
        }

    # ── Simulation ──────────────────────────────────────────────────────────

    def simulate(self, capital_usd: float, signals: Optional[Dict] = None,
                 apy_map: Optional[Dict[str, float]] = None,
                 advance: bool = True) -> Dict:
        """Simulate one day: detect regime, rotate ≤14%, accrue daily yield.

        Args:
            capital_usd: portfolio size (USD).
            signals: regime-detection inputs (see bear_signals()).
            apy_map: optional {protocol: apy_pct} live overrides.
            advance: when True, advances the 7-day transition one step.
        """
        detected = self.detect_regime(signals)
        if advance:
            self.step_day(detected)
        weights = self._current_weights

        if capital_usd <= 0.0:
            return {
                "total_capital":             capital_usd,
                "detected_regime":           detected,
                "allocation":                {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "risk_summary":              self.get_risk_summary(detected),
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }

        positions: Dict[str, Dict] = {}
        total_yield = 0.0
        allocation: Dict[str, float] = {}
        for p in PROTOCOLS:
            amount = round(capital_usd * weights.get(p, 0.0), 6)
            allocation[p] = amount
            apy = self._apy(p, apy_map)
            annual = amount * (apy / 100.0)
            total_yield += annual
            positions[p] = {
                "amount_usd":       amount,
                "apy_pct":          apy,
                "tier":             TIER_OF.get(p, "T1"),
                "annual_yield_usd": round(annual, 4),
            }

        apy_pct = round(total_yield / capital_usd * 100.0, 4) if capital_usd > 0 else 0.0
        result = {
            "total_capital":             capital_usd,
            "detected_regime":           detected,
            "active_regime":             self._active_regime,
            "transition_progress":       round(self.transition_progress, 4),
            "allocation":                allocation,
            "positions":                 positions,
            "expected_annual_yield_usd": round(total_yield, 4),
            "expected_apy_pct":          apy_pct,
            "daily_yield_usd":           round(total_yield / 365.0, 6),
            "status":                    "ok",
            "risk_summary":              self.get_risk_summary(detected),
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
            "protocols":          list(PROTOCOLS),
            "tier_of":            dict(TIER_OF),
            "bear_weights":       dict(BEAR_WEIGHTS),
            "bull_weights":       dict(BULL_WEIGHTS),
            "apy_defaults":       dict(APY_DEFAULTS),
            "thresholds": {
                "aave_util_bear":   AAVE_UTIL_BEAR_THRESHOLD,
                "t2_apy_bear":      T2_APY_BEAR_THRESHOLD,
                "apy_decline_bear": APY_DECLINE_BEAR_THRESHOLD,
                "bear_trigger":     BEAR_TRIGGER,
            },
            "transition_days":      TRANSITION_DAYS,
            "daily_rotation_pct":   DAILY_ROTATION_PCT,
            "bear_target_apy":      [BEAR_TARGET_APY_MIN, BEAR_TARGET_APY_MAX],
            "bull_target_apy":      [BULL_TARGET_APY_MIN, BULL_TARGET_APY_MAX],
            "risk_score":           RISK_SCORE,
            "max_drawdown_pct":     MAX_DRAWDOWN_PCT,
            "bear_expected_apy":    self.get_expected_apy("bear", None),
            "bull_expected_apy":    self.get_expected_apy("bull", None),
            "active_regime":        self._active_regime,
            "transition_progress":  round(self.transition_progress, 4),
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
            risk_tier="T1",
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s31_bear_market_hedge",
            handler_class="BearMarketHedgeStrategy",
            tags=["bear_hedge", "defensive", "regime", "capital_preservation",
                  "aave_v3", "compound_v3", "sky_susds", "pendle_pt", "t1", "s31"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "BearMarketHedgeStrategy auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    s = BearMarketHedgeStrategy()
    print(json.dumps(s.simulate(100_000.0, {"aave_utilization": 0.40}), indent=2))
