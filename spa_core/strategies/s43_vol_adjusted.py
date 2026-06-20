"""
spa_core/strategies/s43_vol_adjusted.py — S43 Volatility-Adjusted Yield

S43: Volatility-Adjusted Yield
==============================
Allocates capital proportional to each venue's *risk-adjusted yield* — its APY
divided by its realized daily-return volatility. High yield is only rewarded if
it comes cheaply in risk: Sky sUSDS (4.20% APY / 0.022% vol ≈ 191) dominates the
score table precisely because its return is almost frictionless, while a fat but
choppy T2 APY scores far lower per unit of risk.

Score table (real 2026-06 sample):
  sky_susds           4.20% / 0.022% ≈ 191   (T1)
  morpho_steakhouse   6.86% / 0.078% ≈  88   (T2)
  compound_v3         3.78% / 0.070% ≈  54   (T1)
  aave_v3             3.64% / 0.073% ≈  50   (T1)

Allocation = score-proportional, then constrained by RiskPolicy caps via an
iterative water-filling pass:
  - per-protocol T1 cap   40%
  - per-protocol T2 cap   20%
  - T2 total cap          50%
  - min cash buffer        5%  (carved out before scoring)
Any weight that hits its cap is frozen; the excess is redistributed pro-rata to
the still-uncapped venues until nothing exceeds its cap. sUSDS lands at its 40%
T1 cap, Morpho at its 20% T2 cap, Aave/Compound split the remainder.

Expected book ≈ sUSDS 40% · Morpho 20% · Compound 18% · Aave 17% · cash 5%,
giving ≈ 4.35% expected APY at materially lower volatility than a naive
yield-chasing book.

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
The deterministic RiskPolicy gate retains final authority; `approved=False` is
never overridden.

Date: 2026-06-21
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S43"
STRATEGY_NAME = "Volatility-Adjusted Yield"
TIER          = "T2"   # holds a capped T2 sleeve (Morpho); net T1-tilted
DESCRIPTION   = (
    "Volatility-Adjusted Yield: allocates proportional to APY/daily-vol "
    "(risk-adjusted yield), constrained by T1 40% / T2 20% per-protocol and T2 "
    "50% total caps via water-filling. Sky sUSDS scores ~191 (lowest vol) and "
    "lands at its 40% cap; Morpho ~88 at its 20% cap; Aave/Compound take the "
    "remainder. Expected ~4.35% APY at low realized vol. Advisory only."
)

CASH_KEY = "cash"

# ─── Protocol universe ────────────────────────────────────────────────────────

PROTOCOL_TIERS: Dict[str, str] = {
    "sky_susds":         "T1",
    "aave_v3":           "T1",
    "compound_v3":       "T1",
    "morpho_steakhouse": "T2",
}

# Conservative default annual APYs (%) from the real track (2026-06 sample).
APY_DEFAULTS: Dict[str, float] = {
    "sky_susds":         4.20,
    "aave_v3":           3.64,
    "compound_v3":       3.78,
    "morpho_steakhouse": 6.86,
}

# Realized daily-return volatility (%) — sUSDS is the lowest in the universe.
DAILY_VOL: Dict[str, float] = {
    "sky_susds":         0.022,
    "aave_v3":           0.073,
    "compound_v3":       0.070,
    "morpho_steakhouse": 0.078,
}

# ─── RiskPolicy caps (fractions of total portfolio) ───────────────────────────

T1_PROTOCOL_CAP: float = 0.40   # per-protocol cap, T1
T2_PROTOCOL_CAP: float = 0.20   # per-protocol cap, T2
T2_TOTAL_CAP:    float = 0.50   # aggregate T2 cap (ADR-019)
MIN_CASH_BUFFER: float = 0.05   # carved out before scoring

# ─── Targets / risk ───────────────────────────────────────────────────────────

TARGET_APY_MIN:   float = 4.0
TARGET_APY_MAX:   float = 5.0
RISK_SCORE:       float = 0.18
MAX_DRAWDOWN_PCT: float = 1.0

_EPS = 1e-12


def _is_pos_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and x > 0.0


def _protocol_cap(protocol: str) -> float:
    return T1_PROTOCOL_CAP if PROTOCOL_TIERS.get(protocol) == "T1" else T2_PROTOCOL_CAP


def _waterfill(scores: Dict[str, float], budget: float) -> Dict[str, float]:
    """Distribute `budget` (a fraction) across `scores` proportionally, honoring
    per-protocol caps; redistribute capped overflow to uncapped venues until
    stable. Returns {protocol: weight_fraction}.
    """
    weights: Dict[str, float] = {p: 0.0 for p in scores}
    capped: Dict[str, bool] = {p: False for p in scores}
    remaining = budget

    # Iterate at most len(scores)+1 times — each pass freezes ≥1 venue or settles.
    for _ in range(len(scores) + 1):
        active = {p: s for p, s in scores.items() if not capped[p] and s > 0.0}
        total = sum(active.values())
        if remaining <= _EPS or total <= _EPS:
            break

        newly_capped = False
        for p, s in active.items():
            proposed = weights[p] + remaining * (s / total)
            cap = _protocol_cap(p)
            if proposed >= cap - _EPS:
                # Freeze at cap; its overflow returns to `remaining` next pass.
                remaining -= (cap - weights[p])
                weights[p] = cap
                capped[p] = True
                newly_capped = True

        if not newly_capped:
            # No new caps hit → distribute the rest proportionally and stop.
            for p, s in active.items():
                weights[p] += remaining * (s / total)
            remaining = 0.0
            break

    return weights


class S43VolAdjusted:
    """S43 — Volatility-Adjusted Yield (risk-adjusted, cap-constrained allocation)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    # ── Scoring ─────────────────────────────────────────────────────────────

    def risk_adjusted_scores(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        vol_map: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """Compute APY / daily_vol per protocol (fallbacks to defaults)."""
        apy_map = apy_map or {}
        vol_map = vol_map or {}
        scores: Dict[str, float] = {}
        for p in PROTOCOL_TIERS:
            apy = apy_map.get(p, APY_DEFAULTS.get(p, 0.0))
            vol = vol_map.get(p, DAILY_VOL.get(p, 0.0))
            if _is_pos_number(vol) and _is_pos_number(apy):
                scores[p] = round(float(apy) / float(vol), 6)
            else:
                scores[p] = 0.0
        return scores

    # ── Allocation ──────────────────────────────────────────────────────────

    def get_weights(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        vol_map: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """Target weight map (fractions, sum 1.0) including cash buffer.

        Score-proportional under T1/T2 per-protocol caps and the T2 total cap,
        with a min cash buffer carved out first.
        """
        scores = self.risk_adjusted_scores(apy_map, vol_map)
        investable = 1.0 - MIN_CASH_BUFFER

        weights = _waterfill(scores, investable)

        # Enforce the aggregate T2 cap: if the T2 sleeve exceeds T2_TOTAL_CAP,
        # scale T2 down and re-waterfill the freed budget into T1 only.
        t2_total = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T2")
        if t2_total > T2_TOTAL_CAP + _EPS:
            scale = T2_TOTAL_CAP / t2_total
            for p in weights:
                if PROTOCOL_TIERS.get(p) == "T2":
                    weights[p] *= scale
            freed = investable - sum(weights.values())
            t1_scores = {p: s for p, s in scores.items() if PROTOCOL_TIERS.get(p) == "T1"}
            # Account for weight already placed in T1 so caps stay respected.
            t1_fill = _waterfill(t1_scores, sum(weights[p] for p in t1_scores) + freed)
            for p in t1_scores:
                weights[p] = t1_fill[p]

        weights[CASH_KEY] = round(1.0 - sum(weights.values()), 8)
        return {p: round(w, 8) for p, w in weights.items()}

    def get_allocation(
        self,
        capital_usd: float,
        apy_map: Optional[Dict[str, float]] = None,
        vol_map: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """Target USD allocation per venue. Empty on non-positive capital."""
        if capital_usd <= 0.0:
            return {}
        weights = self.get_weights(apy_map, vol_map)
        return {p: round(capital_usd * w, 6) for p, w in weights.items()}

    # ── Expected return ─────────────────────────────────────────────────────

    def get_expected_apy(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        vol_map: Optional[Dict[str, float]] = None,
    ) -> float:
        """Weighted expected APY (%) of the allocated book."""
        apy_map = apy_map or {}
        weights = self.get_weights(apy_map, vol_map)
        weighted = 0.0
        for p, w in weights.items():
            if p == CASH_KEY:
                continue
            apy = apy_map.get(p, APY_DEFAULTS.get(p, 0.0))
            weighted += w * apy
        return round(weighted, 4)

    def get_expected_daily_vol(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        vol_map: Optional[Dict[str, float]] = None,
    ) -> float:
        """Weighted average daily volatility (%) of the allocated book."""
        vol_map = vol_map or {}
        weights = self.get_weights(apy_map, vol_map)
        weighted = 0.0
        for p, w in weights.items():
            vol = vol_map.get(p, DAILY_VOL.get(p, 0.0))
            weighted += w * vol
        return round(weighted, 6)

    # ── Summaries ─────────────────────────────────────────────────────────────

    def get_risk_summary(
        self,
        apy_map: Optional[Dict[str, float]] = None,
        vol_map: Optional[Dict[str, float]] = None,
    ) -> Dict:
        weights = self.get_weights(apy_map, vol_map)
        t1 = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T2")
        cash = weights.get(CASH_KEY, 0.0)
        return {
            "strategy_id":      STRATEGY_ID,
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "cash_weight_pct":  round(cash * 100.0, 2),
            "expected_daily_vol_pct": self.get_expected_daily_vol(apy_map, vol_map),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        apy_map: Optional[Dict[str, float]] = None,
        vol_map: Optional[Dict[str, float]] = None,
    ) -> Dict:
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "allocation":                {},
                "scores":                    self.risk_adjusted_scores(apy_map, vol_map),
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        apy = self.get_expected_apy(apy_map, vol_map)
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "allocation":                self.get_allocation(capital_usd, apy_map, vol_map),
            "scores":                    self.risk_adjusted_scores(apy_map, vol_map),
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "expected_daily_vol_pct":    self.get_expected_daily_vol(apy_map, vol_map),
            "status":                    "ok",
            "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
        }

    def to_dict(self) -> Dict:
        return {
            "strategy_id":      STRATEGY_ID,
            "strategy_name":    STRATEGY_NAME,
            "tier":             TIER,
            "description":      DESCRIPTION,
            "protocol_tiers":   dict(PROTOCOL_TIERS),
            "apy_defaults":     dict(APY_DEFAULTS),
            "daily_vol":        dict(DAILY_VOL),
            "t1_protocol_cap":  T1_PROTOCOL_CAP,
            "t2_protocol_cap":  T2_PROTOCOL_CAP,
            "t2_total_cap":     T2_TOTAL_CAP,
            "min_cash_buffer":  MIN_CASH_BUFFER,
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
            module="spa_core.strategies.s43_vol_adjusted",
            handler_class="S43VolAdjusted",
            tags=["risk_adjusted", "volatility", "sky_susds", "water_filling",
                  "sharpe_tilt", "low_vol", "s43"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S43VolAdjusted auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    strat = S43VolAdjusted()
    print(json.dumps(strat.simulate(100_000.0), indent=2))
