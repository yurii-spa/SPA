"""
spa_core/strategies/s63_anti_correlation.py — S63 Anti-Correlation

S63: Anti-Correlation
=====================
Aave and Compound are both blue-chip USDC money markets whose utilization-driven
rates tend to move together — in calm regimes their APY correlation can sit near
1.0. When two positions are that correlated they are effectively *one* exposure
carrying two protocols' worth of smart-contract risk. S63 watches the
Aave↔Compound correlation and, when it gets dangerously high, swaps the
lower-yield of the pair out for Sky sUSDS (a peg instrument that is structurally
decorrelated from money-market utilization). When correlation normalizes it
restores the standard balanced-T1 book.

Hysteresis (avoids whipsaw around the threshold)
------------------------------------------------
  corr(Aave, Compound) > 0.95   → DECORRELATED: drop the lower-yield of the pair,
                                   route its weight to Sky sUSDS
  corr(Aave, Compound) < 0.80   → NORMAL: restore standard T1 allocation
  0.80 ≤ corr ≤ 0.95            → HOLD previous state (no flip-flop in the band)

Standard book (NORMAL):   Aave 30 / Compound 30 / Morpho 20 / Sky 15 / cash 5
Decorrelated book:        keep higher-yield of {Aave, Compound} at 30, move the
                          loser's 30 into Sky (→ Sky 45), Morpho 20, cash 5

Expected APY ≈ 4.2% (NORMAL) … ~4.4% (DECORRELATED) — the small Sky drag is
offset by the concentration-risk reduction.

State is passed in explicitly (`prior_state`) so the strategy stays deterministic
and stateless — no hidden globals. If no correlation data is available it returns
the standard book.

NOTE ON CAPS: the decorrelated book's Sky 45% exceeds the RiskPolicy per-protocol
T1 cap (40%); S63 is advisory and the deterministic RiskPolicy gate trims to caps
before any real allocation. `approved=False` is never overridden.

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.

Date: 2026-06-21
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S63"
STRATEGY_NAME = "Anti-Correlation"
TIER          = "T1"
DESCRIPTION   = (
    "Anti-Correlation: monitors Aave↔Compound APY correlation; when it exceeds "
    "0.95 the lower-yield twin is swapped out for decorrelated Sky sUSDS, and when "
    "it drops below 0.80 the standard balanced-T1 book is restored (hysteresis "
    "band 0.80–0.95 holds state to avoid whipsaw). Cuts redundant money-market "
    "concentration risk. Expected ~4.2–4.4% APY. Advisory-only, deterministic."
)

CASH_KEY = "cash"

# ─── Universe ─────────────────────────────────────────────────────────────────

PROTOCOLS = ["aave_v3", "compound_v3", "morpho_blue", "sky_susds"]

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":     "T1",
    "compound_v3": "T1",
    "morpho_blue": "T2",
    "sky_susds":   "T1",
    CASH_KEY:      "CASH",
}

REFERENCE_APY: Dict[str, float] = {
    "aave_v3":     3.64,
    "compound_v3": 3.78,
    "morpho_blue": 6.87,
    "sky_susds":   4.20,
}

# The correlated pair under watch.
PAIR = ("aave_v3", "compound_v3")

# ─── Hysteresis thresholds ────────────────────────────────────────────────────

CORR_HIGH: float = 0.95   # above → decorrelate
CORR_LOW:  float = 0.80   # below → restore standard

STATE_NORMAL       = "normal"
STATE_DECORRELATED = "decorrelated"

# Standard balanced-T1 book (NORMAL regime).
STANDARD_WEIGHTS: Dict[str, float] = {
    "aave_v3":     0.30,
    "compound_v3": 0.30,
    "morpho_blue": 0.20,
    "sky_susds":   0.15,
    CASH_KEY:      0.05,
}

DEFAULT_CORR_PATH = os.path.join("data", "correlation_matrix.json")

# ─── Targets / risk ───────────────────────────────────────────────────────────

TARGET_APY_MIN:   float = 4.0
TARGET_APY_MAX:   float = 4.6
RISK_SCORE:       float = 0.28
MAX_DRAWDOWN_PCT: float = 3.0


def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def load_pair_correlation(path: Optional[str] = None) -> Optional[float]:
    """Read corr(Aave, Compound) from correlation_matrix.json; None if absent.

    Accepts {"protocol_correlations": {"matrix": {p: {q: r}}}} or a bare
    {p: {q: r}} dict. Never raises — read-only, offline-safe."""
    path = path or DEFAULT_CORR_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    matrix = None
    if isinstance(data, dict):
        pc = data.get("protocol_correlations")
        if isinstance(pc, dict) and isinstance(pc.get("matrix"), dict):
            matrix = pc["matrix"]
        elif all(isinstance(v, dict) for v in data.values()):
            matrix = data
    if not isinstance(matrix, dict):
        return None
    a, b = PAIR
    for x, y in ((a, b), (b, a)):
        row = matrix.get(x)
        if isinstance(row, dict) and _is_number(row.get(y)):
            return float(row[y])
    return None


class S63AntiCorrelation:
    """S63 — Anti-Correlation (decorrelate Aave/Compound into Sky on high corr)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def _apy_of(self, p: str, apy_map: Dict[str, float]) -> float:
        v = apy_map.get(p)
        return float(v) if _is_number(v) else REFERENCE_APY.get(p, 0.0)

    def resolve_state(
        self, correlation: Optional[float], prior_state: str = STATE_NORMAL
    ) -> str:
        """Apply the hysteresis band to pick the active regime."""
        if correlation is None:
            return STATE_NORMAL
        if correlation > CORR_HIGH:
            return STATE_DECORRELATED
        if correlation < CORR_LOW:
            return STATE_NORMAL
        # inside the band → keep prior state (no whipsaw)
        return prior_state if prior_state in (STATE_NORMAL, STATE_DECORRELATED) else STATE_NORMAL

    def _decorrelated_weights(self, apy_map: Dict[str, float]) -> Dict[str, float]:
        """Keep the higher-yield of the pair; route the loser's weight into Sky."""
        a, b = PAIR
        ya, yb = self._apy_of(a, apy_map), self._apy_of(b, apy_map)
        keeper, loser = (a, b) if ya >= yb else (b, a)
        w = dict(STANDARD_WEIGHTS)
        moved = w.pop(loser, 0.0)
        w["sky_susds"] = round(w.get("sky_susds", 0.0) + moved, 6)
        # keeper retains its standard weight
        return {p: round(v, 6) for p, v in w.items()}

    def get_weights(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        correlation: Optional[float] = None,
        prior_state: str = STATE_NORMAL,
    ) -> Dict[str, float]:
        apy_map = apy_map or {}
        if correlation is None:
            correlation = load_pair_correlation()
        state = self.resolve_state(correlation, prior_state)
        if state == STATE_DECORRELATED:
            return self._decorrelated_weights(apy_map)
        return {p: round(w, 6) for p, w in STANDARD_WEIGHTS.items()}

    def get_allocation(
        self,
        capital_usd: float,
        apy_map: Optional[Dict[str, float]] = None,
        correlation: Optional[float] = None,
        prior_state: str = STATE_NORMAL,
    ) -> Dict[str, float]:
        if capital_usd <= 0.0:
            return {}
        weights = self.get_weights(apy_map, correlation, prior_state)
        return {p: round(capital_usd * w, 6) for p, w in weights.items()}

    def get_expected_apy(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        correlation: Optional[float] = None,
        prior_state: str = STATE_NORMAL,
    ) -> float:
        apy_map = apy_map or {}
        weights = self.get_weights(apy_map, correlation, prior_state)
        weighted = 0.0
        for p, w in weights.items():
            if p == CASH_KEY:
                continue
            weighted += w * self._apy_of(p, apy_map)
        return round(weighted, 4)

    def get_risk_summary(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        correlation: Optional[float] = None,
        prior_state: str = STATE_NORMAL,
    ) -> Dict:
        state = self.resolve_state(
            correlation if correlation is not None else load_pair_correlation(),
            prior_state,
        )
        weights = self.get_weights(apy_map, correlation, prior_state)
        t1 = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T2")
        return {
            "strategy_id":      STRATEGY_ID,
            "state":            state,
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "cash_weight_pct":  round(weights.get(CASH_KEY, 0.0) * 100.0, 2),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        apy_map: Optional[Dict[str, float]] = None,
        correlation: Optional[float] = None,
        prior_state: str = STATE_NORMAL,
    ) -> Dict:
        apy_map = apy_map or {}
        if correlation is None:
            correlation = load_pair_correlation()
        state = self.resolve_state(correlation, prior_state)
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "state":                     state,
                "pair_correlation":          correlation,
                "allocation":                {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        weights = self.get_weights(apy_map, correlation, prior_state)
        apy = self.get_expected_apy(apy_map, correlation, prior_state)
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "state":                     state,
            "pair_correlation":          correlation,
            "weights":                   weights,
            "allocation":                {p: round(capital_usd * w, 6) for p, w in weights.items()},
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "risk_summary":              self.get_risk_summary(apy_map, correlation, prior_state),
            "status":                    "ok",
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> Dict:
        return {
            "strategy_id":      STRATEGY_ID,
            "strategy_name":    STRATEGY_NAME,
            "tier":             TIER,
            "description":      DESCRIPTION,
            "protocols":        list(PROTOCOLS),
            "protocol_tiers":   {p: PROTOCOL_TIERS[p] for p in PROTOCOLS},
            "reference_apy":    dict(REFERENCE_APY),
            "pair":             list(PAIR),
            "corr_high":        CORR_HIGH,
            "corr_low":         CORR_LOW,
            "standard_weights": dict(STANDARD_WEIGHTS),
            "target_apy_min":   TARGET_APY_MIN,
            "target_apy_max":   TARGET_APY_MAX,
            "risk_score":       RISK_SCORE,
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
            "timestamp":        datetime.now(timezone.utc).isoformat(),
        }


def _register() -> None:
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier=TIER,
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s63_anti_correlation",
            handler_class="S63AntiCorrelation",
            tags=["correlation", "decorrelation", "hysteresis", "concentration",
                  "sky", "risk_reduction", "advisory", "s63"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S63AntiCorrelation auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    strat = S63AntiCorrelation()
    print(json.dumps(strat.simulate(100_000.0, correlation=0.97), indent=2))
    print(json.dumps(strat.simulate(100_000.0, correlation=0.50), indent=2))
