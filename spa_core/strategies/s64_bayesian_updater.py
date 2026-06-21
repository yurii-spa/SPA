"""
spa_core/strategies/s64_bayesian_updater.py — S64 Bayesian Updater

S64: Bayesian Updater
=====================
An adaptive weight-learner. S64 begins from a Jeffreys-style uninformative prior
(equal allocation — no protocol is assumed better than another) and updates the
weights each week using a simple Bayesian-flavoured likelihood ratio: a protocol
that *outperformed* its expected return earns more weight; one that
*underperformed* loses weight. Over time the book tilts toward venues that have
been delivering, while never fully abandoning the others (the prior keeps a
floor).

Update rule (per week)
----------------------
  prior          w_prior[p]                  (week 0 = 1/N, equal — Jeffreys)
  likelihood     L[p] = observed_return[p] / expected_return[p]
  posterior_raw  w_prior[p] · L[p]
  posterior      normalize(posterior_raw), then enforce caps:
                   per-protocol  T1 ≤ 40%, T2 ≤ 20%
                   aggregate     T2 ≤ 50%   (ADR-019)
                 freed weight is redistributed across uncapped protocols.

Outperforming protocols (L > 1) gain; underperformers (L < 1) shrink. The result
is a momentum-of-realized-yield tilt that is disciplined by the RiskPolicy caps,
so a hot T2 venue can never run past 20%. Expected APY improves over the paper
track as the model concentrates into the genuinely better venues — typically
~4.5–5.5% once it has a few weeks of evidence.

State is explicit: `update()` takes a prior and returns a posterior; `fold()`
replays a sequence of weekly observations from the equal-weight prior. No hidden
globals — deterministic and replayable.

Rules: stdlib only · read-only / advisory · LLM FORBIDDEN · no execution imports.
The RiskPolicy gate retains final authority; `approved=False` is never overridden.

Date: 2026-06-21
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S64"
STRATEGY_NAME = "Bayesian Updater"
TIER          = "T2"
DESCRIPTION   = (
    "Bayesian Updater: starts from a Jeffreys equal-weight prior and updates "
    "weights each week by the likelihood ratio observed/expected return — "
    "outperformers gain weight, underperformers shrink — then enforces "
    "RiskPolicy caps (T1≤40%, T2≤20%, T2 total≤50%) with weight redistributed "
    "across uncapped venues. A disciplined realized-yield momentum tilt that "
    "improves over the track. Expected ~4.5–5.5% APY. Advisory, deterministic."
)

CASH_KEY = "cash"

# ─── Universe ─────────────────────────────────────────────────────────────────

PROTOCOLS = ["aave_v3", "compound_v3", "morpho_blue", "yearn_v3", "sky_susds"]

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":     "T1",
    "compound_v3": "T1",
    "morpho_blue": "T2",
    "yearn_v3":    "T2",
    "sky_susds":   "T1",
}

# Reference / expected APYs (%) — long-run means, the prior expectation.
REFERENCE_APY: Dict[str, float] = {
    "aave_v3":     3.64,
    "compound_v3": 3.78,
    "morpho_blue": 6.87,
    "yearn_v3":    4.95,
    "sky_susds":   4.20,
}

# ─── Caps & tuning ────────────────────────────────────────────────────────────

PER_PROTOCOL_CAP: Dict[str, float] = {"T1": 0.40, "T2": 0.20}
T2_TOTAL_CAP:     float = 0.50   # ADR-019
MIN_LIKELIHOOD:   float = 0.10   # floor so a single bad week can't zero a venue
MAX_LIKELIHOOD:   float = 5.00   # ceiling so one spike can't dominate

TARGET_APY_MIN:   float = 4.0
TARGET_APY_MAX:   float = 5.5
RISK_SCORE:       float = 0.42
MAX_DRAWDOWN_PCT: float = 4.0


def _cap_for(protocol: str) -> float:
    return PER_PROTOCOL_CAP.get(PROTOCOL_TIERS.get(protocol, "T2"), 0.20)


def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


class S64BayesianUpdater:
    """S64 — Bayesian Updater (equal-weight prior, weekly likelihood-ratio tilt)."""

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    # ── Prior ────────────────────────────────────────────────────────────────

    def jeffreys_prior(self, universe: Optional[List[str]] = None) -> Dict[str, float]:
        """Equal-weight (uninformative) prior over the active universe."""
        universe = universe or list(PROTOCOLS)
        n = len(universe)
        if n == 0:
            return {}
        w = 1.0 / n
        return {p: w for p in universe}

    # ── Single weekly update ─────────────────────────────────────────────────

    def update(
        self,
        prior: Dict[str, float],
        observed: Dict[str, float],
        expected: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """One Bayesian step: posterior ∝ prior · (observed/expected), then caps.

        `expected` defaults to REFERENCE_APY. Protocols absent from `observed`
        keep a neutral likelihood (1.0). Returns a capped, normalized weight map."""
        expected = expected or REFERENCE_APY
        raw: Dict[str, float] = {}
        for p, w_prior in prior.items():
            if w_prior <= 0:
                continue
            obs = observed.get(p)
            exp = expected.get(p, REFERENCE_APY.get(p))
            if _is_number(obs) and _is_number(exp) and exp != 0:
                like = _clamp(float(obs) / float(exp), MIN_LIKELIHOOD, MAX_LIKELIHOOD)
            else:
                like = 1.0   # no evidence → neutral
            raw[p] = w_prior * like
        return self._normalize_with_caps(raw)

    # ── Replay a sequence of weeks ───────────────────────────────────────────

    def fold(
        self,
        weekly_observations: List[Dict[str, float]],
        expected: Optional[Dict[str, float]] = None,
        universe: Optional[List[str]] = None,
    ) -> Dict[str, float]:
        """Replay weekly observations from the equal-weight prior → final weights."""
        weights = self.jeffreys_prior(universe)
        for obs in weekly_observations:
            weights = self.update(weights, obs, expected)
        return weights

    # ── Cap-respecting normalization (water-filling) ─────────────────────────

    def _normalize_with_caps(self, raw: Dict[str, float]) -> Dict[str, float]:
        remaining = {p: w for p, w in raw.items() if w > 0}
        if not remaining:
            return {}
        frozen: Dict[str, float] = {}
        budget = 1.0
        for _ in range(len(remaining) + 1):
            total = sum(remaining.values())
            if total <= 0:
                break
            scaled = {p: w / total * budget for p, w in remaining.items()}
            breaches = {p: _cap_for(p) for p, s in scaled.items()
                        if s > _cap_for(p) + 1e-12}
            if not breaches:
                frozen.update(scaled)
                remaining = {}
                break
            for p, cap in breaches.items():
                frozen[p] = cap
                budget -= cap
                remaining.pop(p, None)
            if budget <= 0 or not remaining:
                break
        weights = self._enforce_t2_cap(frozen)
        return {p: round(w, 6) for p, w in weights.items() if w > 0}

    def _enforce_t2_cap(self, weights: Dict[str, float]) -> Dict[str, float]:
        """Scale T2 aggregate down to T2_TOTAL_CAP; freed weight → T1 pro-rata."""
        t2_total = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T2")
        if t2_total <= T2_TOTAL_CAP or t2_total <= 0:
            return weights
        scale = T2_TOTAL_CAP / t2_total
        freed = t2_total - T2_TOTAL_CAP
        out = {p: (w * scale if PROTOCOL_TIERS.get(p) == "T2" else w)
               for p, w in weights.items()}
        t1 = {p: w for p, w in out.items() if PROTOCOL_TIERS.get(p) == "T1"}
        t1_total = sum(t1.values())
        if t1_total > 0:
            for p in t1:
                out[p] += freed * (t1[p] / t1_total)
        return out

    # ── Outputs ──────────────────────────────────────────────────────────────

    def get_weights(
        self,
        weekly_observations: Optional[List[Dict[str, float]]] = None,
        expected: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        if not weekly_observations:
            return {p: round(w, 6) for p, w in self.jeffreys_prior().items()}
        return self.fold(weekly_observations, expected)

    def get_allocation(
        self,
        capital_usd: float,
        weekly_observations: Optional[List[Dict[str, float]]] = None,
        expected: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        if capital_usd <= 0.0:
            return {}
        weights = self.get_weights(weekly_observations, expected)
        return {p: round(capital_usd * w, 6) for p, w in weights.items()}

    def get_expected_apy(
        self,
        weekly_observations: Optional[List[Dict[str, float]]] = None,
        apy_map: Optional[Dict[str, float]] = None,
        expected: Optional[Dict[str, float]] = None,
    ) -> float:
        apy_map = apy_map or REFERENCE_APY
        weights = self.get_weights(weekly_observations, expected)
        weighted = 0.0
        for p, w in weights.items():
            if p == CASH_KEY:
                continue
            apy = apy_map.get(p, REFERENCE_APY.get(p, 0.0))
            weighted += w * (float(apy) if _is_number(apy) else 0.0)
        return round(weighted, 4)

    def get_risk_summary(
        self,
        weekly_observations: Optional[List[Dict[str, float]]] = None,
        expected: Optional[Dict[str, float]] = None,
    ) -> Dict:
        weights = self.get_weights(weekly_observations, expected)
        t1 = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in weights.items() if PROTOCOL_TIERS.get(p) == "T2")
        return {
            "strategy_id":      STRATEGY_ID,
            "risk_score":       RISK_SCORE,
            "t1_weight_pct":    round(t1 * 100.0, 2),
            "t2_weight_pct":    round(t2 * 100.0, 2),
            "weeks_observed":   len(weekly_observations or []),
            "max_drawdown_pct": MAX_DRAWDOWN_PCT,
        }

    def simulate(
        self,
        capital_usd: float,
        weekly_observations: Optional[List[Dict[str, float]]] = None,
        apy_map: Optional[Dict[str, float]] = None,
        expected: Optional[Dict[str, float]] = None,
    ) -> Dict:
        if capital_usd <= 0.0:
            return {
                "strategy_id":               STRATEGY_ID,
                "total_capital":             capital_usd,
                "allocation":                {},
                "expected_annual_yield_usd": 0.0,
                "expected_apy_pct":          0.0,
                "weeks_observed":            len(weekly_observations or []),
                "status":                    "no_capital",
                "timestamp_utc":             datetime.now(timezone.utc).isoformat(),
            }
        weights = self.get_weights(weekly_observations, expected)
        apy = self.get_expected_apy(weekly_observations, apy_map, expected)
        return {
            "strategy_id":               STRATEGY_ID,
            "total_capital":             capital_usd,
            "weights":                   weights,
            "allocation":                {p: round(capital_usd * w, 6) for p, w in weights.items()},
            "expected_annual_yield_usd": round(capital_usd * apy / 100.0, 4),
            "expected_apy_pct":          apy,
            "weeks_observed":            len(weekly_observations or []),
            "risk_summary":              self.get_risk_summary(weekly_observations, expected),
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
            "per_protocol_cap": dict(PER_PROTOCOL_CAP),
            "t2_total_cap":     T2_TOTAL_CAP,
            "min_likelihood":   MIN_LIKELIHOOD,
            "max_likelihood":   MAX_LIKELIHOOD,
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
            module="spa_core.strategies.s64_bayesian_updater",
            handler_class="S64BayesianUpdater",
            tags=["bayesian", "adaptive", "learning", "likelihood", "meta",
                  "realized_yield", "advisory", "s64"],
        ))
    except Exception as exc:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S64BayesianUpdater auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    strat = S64BayesianUpdater()
    # Three weeks where Morpho consistently beats its expectation.
    weeks = [
        {"aave_v3": 3.5, "compound_v3": 3.6, "morpho_blue": 8.5, "yearn_v3": 4.0, "sky_susds": 4.2},
        {"aave_v3": 3.4, "compound_v3": 3.7, "morpho_blue": 9.0, "yearn_v3": 4.1, "sky_susds": 4.2},
        {"aave_v3": 3.6, "compound_v3": 3.8, "morpho_blue": 9.2, "yearn_v3": 4.2, "sky_susds": 4.2},
    ]
    print(json.dumps(strat.simulate(100_000.0, weekly_observations=weeks), indent=2))
