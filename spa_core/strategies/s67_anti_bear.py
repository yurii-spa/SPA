"""
spa_core/strategies/s67_anti_bear.py — S67 Anti-Bear

S67: Anti-Bear (inverse bear-market hedge)
==========================================
S67 is the structural MIRROR of S31 Bear Market Hedge. It consumes the SAME
regime signal S31 uses (`BearMarketHedgeStrategy.detect_regime`) and then
INVERTS the posture:

    underlying regime = BEAR   →  S67 goes BULL   (growth, ~50% T2 book)
    underlying regime = BULL   →  S67 goes BEAR   (ultra-safe, ~95% T1 book)

Why
---
Run ALONGSIDE S31 for self-hedging portfolio diversification. When S31 retreats
to capital-preservation (bear), S67 leans into growth; when S31 reaches for
yield (bull), S67 de-risks. The two books are negatively correlated by
construction, so the *combined* sleeve has lower realized variance than either
alone — a built-in pair hedge rather than a directional bet.

The "50% T2 in a (detected) BULL-for-S67 environment" is deliberately COUNTER
to a standard bear hedge: a normal hedge cuts T2 when the regime signal trips
bear; S67 does the opposite, deploying its growth book exactly then. The T2
sleeve is held at the ADR-019 aggregate cap (50%) via three T2 venues each at
their 20% per-protocol ceiling or below.

Anti-bull (ultra-safe) book is an all-T1 ballast: Aave + Compound + Sky.

Expected APY: a mirror of S31 (S31 bear 3.5–4.5%, bull 6–8%) — so S67 spans the
same 3.5–8% band, just phased opposite.

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
The deterministic RiskPolicy gate retains final authority; `approved=False` is
never overridden. S67 emits a target weight map + an (inverted) regime verdict;
it never opens positions itself. Sky deployment stays subject to the watch-list
rule (FORBIDDEN #7); the gate governs actual capital.

Date: 2026-06-21
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S67"
STRATEGY_NAME = "Anti-Bear"
TIER          = "T2"   # the BULL book carries a 50% T2 sleeve → classified T2
DESCRIPTION   = (
    "Anti-Bear: structural inverse of S31. Consumes S31's regime signal and "
    "flips it — underlying BEAR → S67 goes BULL (~50% T2 growth book), "
    "underlying BULL → S67 goes BEAR (~95% T1 ultra-safe). Run alongside S31 "
    "for self-hedging negative correlation. Expected APY mirrors S31 (3.5–8%). "
    "Advisory-only, deterministic, stdlib."
)

CASH_KEY = "cash"

# ─── Protocol universe ────────────────────────────────────────────────────────

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":     "T1",
    "compound_v3": "T1",
    "sky_susds":   "T1",
    "morpho_blue": "T2",
    "yearn_v3":    "T2",
    "fluid":       "T2",
    CASH_KEY:      "CASH",
}

# S67 BULL book (taken when the underlying regime is BEAR): growth, 50% T2.
#   T2 = morpho 20 + yearn 20 + fluid 10 = 50% (ADR-019 aggregate cap, each ≤ 20%)
#   T1 = aave 25 + compound 20 = 45% ; cash 5%
ANTI_BULL_WEIGHTS: Dict[str, float] = {
    "aave_v3":     0.25,
    "compound_v3": 0.20,
    "morpho_blue": 0.20,
    "yearn_v3":    0.20,
    "fluid":       0.10,
    CASH_KEY:      0.05,
}

# S67 BEAR book (taken when the underlying regime is BULL): ultra-safe, all-T1.
ANTI_BEAR_WEIGHTS: Dict[str, float] = {
    "aave_v3":     0.40,
    "compound_v3": 0.35,
    "sky_susds":   0.20,
    CASH_KEY:      0.05,
}

# Default APY (%) per protocol — DeFiLlama 2026-06 means / current.
APY_DEFAULTS: Dict[str, float] = {
    "aave_v3":     3.64,
    "compound_v3": 3.78,
    "sky_susds":   4.20,
    "morpho_blue": 6.87,
    "yearn_v3":    4.95,
    "fluid":       6.22,
}

# ─── Targets / risk ───────────────────────────────────────────────────────────
# Mirror of S31's full span (bear 3.5–4.5, bull 6–8).
TARGET_APY_MIN:   float = 3.5
TARGET_APY_MAX:   float = 8.0
RISK_SCORE:       float = 0.55
MAX_DRAWDOWN_PCT: float = 4.5


def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def _invert(regime: str) -> str:
    return "bear" if str(regime).lower() == "bull" else "bull"


class S67AntiBear:
    """S67 — Anti-Bear (inverted S31 regime, self-hedging companion book)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    def __init__(self, default_underlying: str = "bear"):
        # Default underlying = bear → S67 default posture = bull growth book.
        self.default_underlying = str(default_underlying).lower()

    # ── Regime ──────────────────────────────────────────────────────────────────

    def underlying_regime(self, signals: Optional[Dict] = None) -> str:
        """Delegate to S31's detector for the underlying market regime.

        Falls back to `default_underlying` if S31 is unavailable (import-safe).
        """
        try:
            from spa_core.strategies.s31_bear_market_hedge import BearMarketHedgeStrategy
            return BearMarketHedgeStrategy().detect_regime(signals)
        except Exception:   # noqa: BLE001 — advisory, never raise
            return self.default_underlying

    def detect_regime(self, signals: Optional[Dict] = None) -> str:
        """S67's own posture = the INVERSE of the underlying S31 regime."""
        return _invert(self.underlying_regime(signals))

    def regime_weights(self, regime: str) -> Dict[str, float]:
        """Weight map for an S67 posture ('bull' → growth book, else safe book)."""
        book = ANTI_BULL_WEIGHTS if str(regime).lower() == "bull" else ANTI_BEAR_WEIGHTS
        return {p: round(w, 6) for p, w in book.items()}

    # ── Allocation ──────────────────────────────────────────────────────────────

    def compute_weights(self, signals: Optional[Dict] = None,
                        regime: Optional[str] = None) -> Dict[str, float]:
        """Target weight map for the current (inverted) posture.

        `regime`, if given, is treated as S67's own posture directly (skips the
        S31 delegation) — useful for tests and explicit overrides.
        """
        posture = str(regime).lower() if regime else self.detect_regime(signals)
        return self.regime_weights(posture)

    def get_weights(self, signals: Optional[Dict] = None,
                    regime: Optional[str] = None) -> Dict[str, float]:
        return self.compute_weights(signals, regime)

    def get_allocation(self, capital_usd: float, signals: Optional[Dict] = None,
                       regime: Optional[str] = None) -> Dict[str, float]:
        if capital_usd <= 0.0:
            return {}
        weights = self.compute_weights(signals, regime)
        return {p: round(capital_usd * w, 6) for p, w in weights.items()}

    # ── Expected return ──────────────────────────────────────────────────────────

    def get_expected_apy(self, signals: Optional[Dict] = None,
                         regime: Optional[str] = None,
                         current_apys: Optional[Dict[str, float]] = None) -> float:
        apys = current_apys or dict(APY_DEFAULTS)
        weights = self.compute_weights(signals, regime)
        weighted = 0.0
        for p, w in weights.items():
            if p == CASH_KEY:
                continue
            apy = apys.get(p, APY_DEFAULTS.get(p, 0.0))
            weighted += w * (float(apy) if _is_number(apy) else APY_DEFAULTS.get(p, 0.0))
        return round(weighted, 4)

    # ── Summaries ────────────────────────────────────────────────────────────────

    def get_risk_summary(self, weights: Optional[Dict[str, float]] = None) -> Dict:
        weights = weights or self.compute_weights(regime="bull")
        t1 = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T2")
        cash = weights.get(CASH_KEY, 0.0)
        return {
            "strategy_id":      STRATEGY_ID,
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "cash_weight_pct":  round(cash * 100.0, 2),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(self, capital_usd: float, signals: Optional[Dict] = None,
                 regime: Optional[str] = None,
                 current_apys: Optional[Dict[str, float]] = None) -> Dict:
        underlying = self.underlying_regime(signals) if regime is None else _invert(regime)
        posture = str(regime).lower() if regime else _invert(underlying)
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "allocation":                {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "underlying_regime":         underlying,
                "anti_bear_posture":         posture,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        weights = self.compute_weights(signals, regime)
        apy = self.get_expected_apy(signals, regime, current_apys)
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "underlying_regime":         underlying,
            "anti_bear_posture":         posture,
            "weights":                   weights,
            "allocation":                {p: round(capital_usd * w, 6) for p, w in weights.items()},
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "risk_summary":              self.get_risk_summary(weights),
            "status":                    "ok",
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> Dict:
        return {
            "strategy_id":       STRATEGY_ID,
            "strategy_name":     STRATEGY_NAME,
            "tier":              TIER,
            "description":       DESCRIPTION,
            "anti_bull_weights": dict(ANTI_BULL_WEIGHTS),
            "anti_bear_weights": dict(ANTI_BEAR_WEIGHTS),
            "protocol_tiers":    {p: PROTOCOL_TIERS[p] for p in APY_DEFAULTS},
            "apy_defaults":      dict(APY_DEFAULTS),
            "target_apy_min":    TARGET_APY_MIN,
            "target_apy_max":    TARGET_APY_MAX,
            "risk_score":        RISK_SCORE,
            "max_drawdown_pct":  MAX_DRAWDOWN_PCT,
            "timestamp":         datetime.now(timezone.utc).isoformat(),
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
            module="spa_core.strategies.s67_anti_bear",
            handler_class="S67AntiBear",
            tags=["anti_bear", "inverse", "regime_aware", "self_hedge", "diversification",
                  "advisory", "s67"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S67AntiBear auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    strat = S67AntiBear()
    # Underlying bear (default) → S67 bull growth book:
    print(json.dumps(strat.simulate(100_000.0, regime="bull"), indent=2))
    # Underlying bull → S67 bear ultra-safe book:
    print(json.dumps(strat.simulate(100_000.0, regime="bear"), indent=2))
