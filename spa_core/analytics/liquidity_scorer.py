"""Liquidity Scorer — MP-581.

Evaluates adapter and portfolio liquidity on a 0–100 scale using five
deterministic sub-scores:

    TVL score        (0–30 pts) — absolute liquidity cushion
    Tier score       (0–25 pts) — T1=25 / T2=15 / T3=5
    Redemption score (0–20 pts) — instant=20 / batched=10 / lock=0
    Age score        (0–15 pts) — protocol maturity proxy
    Audit score      (0–10 pts) — number of independent audits

Design constraints
------------------
* Stdlib only (no numpy, requests, web3, pandas, …).
* Pure advisory — never touches allocator / risk / execution.
* Strictly read-only: no writes, no side-effects.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# TVL breakpoints (USD) → max 30 pts (linear piecewise)
_TVL_TIERS: List[tuple] = [
    (1_000_000_000, 30),   # ≥ $1 B
    (500_000_000,  26),    # ≥ $500 M
    (100_000_000,  20),    # ≥ $100 M
    (50_000_000,   14),    # ≥ $50 M
    (10_000_000,    8),    # ≥ $10 M
    (5_000_000,     4),    # ≥ $5 M  (RiskPolicy TVL floor)
    (0,             0),    # < $5 M
]

_TIER_SCORES: Dict[str, float] = {
    "T1": 25.0,
    "T2": 15.0,
    "T3":  5.0,
}

_REDEMPTION_SCORES: Dict[str, float] = {
    "instant":  20.0,
    "batched":  10.0,
    "lock":      0.0,
}

# Default protocol age assumed when not provided (1 year = 365 days)
_DEFAULT_PROTOCOL_AGE_DAYS: float = 365.0

# Age breakpoints (days) → max 15 pts
_AGE_TIERS: List[tuple] = [
    (1825, 15),   # ≥ 5 years
    (1095, 12),   # ≥ 3 years
    (730,   9),   # ≥ 2 years
    (365,   6),   # ≥ 1 year
    (180,   3),   # ≥ 6 months
    (0,     0),   # < 6 months
]

# Audit count → max 10 pts
_AUDIT_TIERS: List[tuple] = [
    (4, 10),   # ≥ 4 audits
    (3,  8),
    (2,  6),
    (1,  3),
    (0,  0),
]

# Classification thresholds
_LIQUIDITY_CLASSES = [
    (80.0, "excellent"),
    (60.0, "good"),
    (40.0, "fair"),
    (0.0,  "poor"),
]

# Exit time lookup by tier (days) — (min_days, max_days)
_EXIT_TIME_BY_TIER: Dict[str, tuple] = {
    "T1": (0.0,   0.0),    # instant
    "T2": (1.0,   3.0),    # batched ~1–3 days
    "T3": (7.0,  30.0),    # lock-up 7–30 days
}

# Redemption modifier on exit time (override tier-based defaults)
_EXIT_TIME_BY_REDEMPTION: Dict[str, tuple] = {
    "instant": (0.0,  0.0),
    "batched": (1.0,  3.0),
    "lock":    (7.0, 30.0),
}

# TVL utilisation thresholds for exit-time scaling (fraction of TVL)
_EXIT_TIME_UTILISATION_LOW:  float = 0.01   # < 1% of TVL → no premium
_EXIT_TIME_UTILISATION_HIGH: float = 0.10   # > 10% of TVL → max premium

# Maximum exit-time multiplier when amount_usd/tvl_usd is very large
_EXIT_TIME_MAX_MULTIPLIER: float = 3.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tiered_score(value: float, tiers: List[tuple]) -> float:
    """Return the score for *value* by walking *tiers* (descending thresholds)."""
    for threshold, pts in tiers:
        if value >= threshold:
            return float(pts)
    return 0.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to float, returning *default* on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalise_tier(tier: Any) -> str:
    """Return a canonical tier string (T1/T2/T3); fall back to T3."""
    s = str(tier).strip().upper() if tier is not None else ""
    return s if s in _TIER_SCORES else "T3"


def _normalise_redemption(redemption_type: Any) -> str:
    """Return a canonical redemption string; fall back to 'lock'."""
    s = str(redemption_type).strip().lower() if redemption_type is not None else ""
    return s if s in _REDEMPTION_SCORES else "lock"


# ---------------------------------------------------------------------------
# LiquidityScorer
# ---------------------------------------------------------------------------

class LiquidityScorer:
    """Deterministic liquidity scoring for DeFi adapters and portfolios.

    All methods are pure functions over adapter dicts / attribute objects.
    No IO, no network, no LLM calls.

    Adapter schema (dict or object with attributes):
        tvl_usd           float   — TVL in USD (None → 0)
        tier              str     — "T1" / "T2" / "T3"
        redemption_type   str     — "instant" / "batched" / "lock"
        protocol_age_days float   — protocol age in days (None → 365 default)
        audit_count       int     — number of independent security audits
    """

    # ------------------------------------------------------------------
    # Adapter attribute access
    # ------------------------------------------------------------------

    @staticmethod
    def _get(adapter: Any, key: str, default: Any = None) -> Any:
        """Read *key* from adapter dict or object attribute."""
        if isinstance(adapter, dict):
            return adapter.get(key, default)
        return getattr(adapter, key, default)

    # ------------------------------------------------------------------
    # Sub-score components
    # ------------------------------------------------------------------

    def _tvl_score(self, adapter: Any) -> float:
        tvl = _safe_float(self._get(adapter, "tvl_usd"), 0.0)
        return _tiered_score(tvl, _TVL_TIERS)

    def _tier_score(self, adapter: Any) -> float:
        tier = _normalise_tier(self._get(adapter, "tier", "T3"))
        return _TIER_SCORES[tier]

    def _redemption_score(self, adapter: Any) -> float:
        rtype = _normalise_redemption(self._get(adapter, "redemption_type", "lock"))
        return _REDEMPTION_SCORES[rtype]

    def _age_score(self, adapter: Any) -> float:
        age = _safe_float(
            self._get(adapter, "protocol_age_days", None),
            _DEFAULT_PROTOCOL_AGE_DAYS,
        )
        return _tiered_score(age, _AGE_TIERS)

    def _audit_score(self, adapter: Any) -> float:
        audits = _safe_float(self._get(adapter, "audit_count", 0), 0.0)
        return _tiered_score(audits, _AUDIT_TIERS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score_adapter(self, adapter: Any) -> float:
        """Return a liquidity score [0–100] for a single adapter.

        Score = TVL (30) + Tier (25) + Redemption (20) + Age (15) + Audit (10).

        Parameters
        ----------
        adapter:
            A dict with keys ``tvl_usd``, ``tier``, ``redemption_type``,
            ``protocol_age_days``, ``audit_count``; or an object with
            the same attribute names.  Missing / None values use safe
            defaults (TVL→0, tier→T3, redemption→lock, age→1yr, audits→0).

        Returns
        -------
        float
            Score in [0.0, 100.0].
        """
        score = (
            self._tvl_score(adapter)
            + self._tier_score(adapter)
            + self._redemption_score(adapter)
            + self._age_score(adapter)
            + self._audit_score(adapter)
        )
        return round(min(max(score, 0.0), 100.0), 4)

    def score_portfolio(
        self,
        adapters: Sequence[Any],
        weights: Sequence[float],
    ) -> float:
        """Return a weighted-average liquidity score [0–100] for a portfolio.

        Parameters
        ----------
        adapters:
            Sequence of adapter dicts / objects (same schema as
            :meth:`score_adapter`).
        weights:
            Sequence of non-negative numeric weights (absolute USD amounts
            or fractional weights — they are normalised internally).  Must
            have the same length as *adapters*.

        Returns
        -------
        float
            Weighted-average score in [0.0, 100.0].  Returns 0.0 for an
            empty / zero-weight portfolio.

        Raises
        ------
        ValueError
            If ``len(adapters) != len(weights)``.
        """
        if len(adapters) != len(weights):
            raise ValueError(
                f"adapters ({len(adapters)}) and weights ({len(weights)}) "
                "must have equal length"
            )
        float_weights = [_safe_float(w, 0.0) for w in weights]
        total = sum(max(w, 0.0) for w in float_weights)
        if total <= 0.0:
            return 0.0
        weighted_sum = sum(
            self.score_adapter(a) * max(float_weights[i], 0.0)
            for i, a in enumerate(adapters)
        )
        return round(min(max(weighted_sum / total, 0.0), 100.0), 4)

    def get_liquidity_report(
        self,
        adapters: Sequence[Any],
        weights: Sequence[float],
    ) -> Dict[str, Any]:
        """Return a detailed liquidity report for a portfolio.

        Parameters
        ----------
        adapters:
            Sequence of adapter dicts / objects.
        weights:
            Sequence of non-negative weights corresponding to *adapters*.

        Returns
        -------
        dict with keys:
            ``portfolio_score``      float  — overall weighted score
            ``classification``       str    — excellent/good/fair/poor
            ``scores``               list[float]  — per-adapter scores
            ``breakdown``            list[dict]   — per-adapter sub-score breakdown
            ``warnings``             list[str]    — advisory warnings
            ``tier_liquidity_breakdown``  dict    — T1/T2/T3 weighted-avg scores
                                                    and weight fractions
        """
        if len(adapters) != len(weights):
            raise ValueError(
                f"adapters ({len(adapters)}) and weights ({len(weights)}) "
                "must have equal length"
            )

        float_weights = [max(_safe_float(w, 0.0), 0.0) for w in weights]
        total_weight = sum(float_weights)

        scores: List[float] = []
        breakdown: List[Dict[str, Any]] = []
        warnings: List[str] = []

        # Tier accumulators for tier_liquidity_breakdown
        tier_weight: Dict[str, float] = {"T1": 0.0, "T2": 0.0, "T3": 0.0}
        tier_score_sum: Dict[str, float] = {"T1": 0.0, "T2": 0.0, "T3": 0.0}

        for i, adapter in enumerate(adapters):
            w = float_weights[i]
            s = self.score_adapter(adapter)
            scores.append(s)

            tvl_pts       = self._tvl_score(adapter)
            tier_pts      = self._tier_score(adapter)
            redemption_pts = self._redemption_score(adapter)
            age_pts       = self._age_score(adapter)
            audit_pts     = self._audit_score(adapter)

            tier_str = _normalise_tier(self._get(adapter, "tier", "T3"))
            rtype    = _normalise_redemption(
                self._get(adapter, "redemption_type", "lock")
            )
            tvl_usd  = _safe_float(self._get(adapter, "tvl_usd"), 0.0)
            protocol = self._get(adapter, "protocol", self._get(adapter, "PROTOCOL", f"adapter_{i}"))
            age_days = _safe_float(
                self._get(adapter, "protocol_age_days", None),
                _DEFAULT_PROTOCOL_AGE_DAYS,
            )
            audits   = int(_safe_float(self._get(adapter, "audit_count", 0), 0.0))

            # Identify low-score components for warnings
            if tvl_usd < 5_000_000:
                warnings.append(
                    f"{protocol}: TVL ${tvl_usd:,.0f} below RiskPolicy floor ($5M)"
                )
            if s < 40.0:
                warnings.append(
                    f"{protocol}: poor liquidity score {s:.1f} — consider reducing allocation"
                )
            if rtype == "lock":
                warnings.append(
                    f"{protocol}: lock redemption type — exit may take weeks"
                )
            if audits == 0:
                warnings.append(f"{protocol}: zero audits — unaudited protocol")

            breakdown.append(
                {
                    "protocol":        protocol,
                    "score":           s,
                    "weight":          w,
                    "weight_fraction": round(w / total_weight, 6) if total_weight > 0 else 0.0,
                    "sub_scores": {
                        "tvl":         tvl_pts,
                        "tier":        tier_pts,
                        "redemption":  redemption_pts,
                        "age":         age_pts,
                        "audit":       audit_pts,
                    },
                    "tier":            tier_str,
                    "redemption_type": rtype,
                    "tvl_usd":         tvl_usd,
                    "protocol_age_days": age_days,
                    "audit_count":     audits,
                }
            )

            # Accumulate tier stats
            if tier_str in tier_weight:
                tier_weight[tier_str] += w
                tier_score_sum[tier_str] += s * w

        # Overall portfolio score
        portfolio_score = self.score_portfolio(adapters, weights)
        classification  = self.classify_liquidity(portfolio_score)

        # Tier breakdown
        tier_liquidity_breakdown: Dict[str, Dict[str, Any]] = {}
        for tier_key in ("T1", "T2", "T3"):
            tw = tier_weight[tier_key]
            tier_liquidity_breakdown[tier_key] = {
                "weight_fraction": round(tw / total_weight, 6) if total_weight > 0 else 0.0,
                "weighted_avg_score": round(
                    tier_score_sum[tier_key] / tw if tw > 0 else 0.0, 4
                ),
            }

        # Deduplicate warnings
        seen: set = set()
        unique_warnings: List[str] = []
        for w_str in warnings:
            if w_str not in seen:
                seen.add(w_str)
                unique_warnings.append(w_str)

        return {
            "portfolio_score":        portfolio_score,
            "classification":         classification,
            "scores":                 scores,
            "breakdown":              breakdown,
            "warnings":               unique_warnings,
            "tier_liquidity_breakdown": tier_liquidity_breakdown,
        }

    @staticmethod
    def classify_liquidity(score: float) -> str:
        """Classify a liquidity score into a human-readable category.

        Parameters
        ----------
        score:
            Numeric score (any range; clamped to [0, 100] for evaluation).

        Returns
        -------
        str
            ``"excellent"`` (≥80), ``"good"`` (60–79), ``"fair"`` (40–59),
            ``"poor"`` (<40).
        """
        s = min(max(_safe_float(score, 0.0), 0.0), 100.0)
        for threshold, label in _LIQUIDITY_CLASSES:
            if s >= threshold:
                return label
        return "poor"

    def estimate_exit_time_days(
        self,
        adapter: Any,
        amount_usd: float = 0.0,
    ) -> float:
        """Estimate the number of days to fully exit a position.

        The estimate is based on:
        1. ``redemption_type`` (preferred) or ``tier`` — determines the
           base range (min, max) in days.
        2. A utilisation premium: when ``amount_usd / tvl_usd`` exceeds
           ``_EXIT_TIME_UTILISATION_LOW``, the estimate is scaled linearly
           toward ``_EXIT_TIME_MAX_MULTIPLIER × max_days`` at the
           ``_EXIT_TIME_UTILISATION_HIGH`` threshold.

        Parameters
        ----------
        adapter:
            Adapter dict / object (schema same as :meth:`score_adapter`).
        amount_usd:
            Size of the position to exit in USD (default 0 → no utilisation
            premium applied).

        Returns
        -------
        float
            Estimated exit time in days (≥ 0).
        """
        raw_rtype = self._get(adapter, "redemption_type", None)
        tier = _normalise_tier(self._get(adapter, "tier", "T3"))

        # Prefer redemption_type when explicitly provided; fall back to tier
        if raw_rtype is not None:
            rtype = _normalise_redemption(raw_rtype)
            min_days, max_days = _EXIT_TIME_BY_REDEMPTION.get(
                rtype, _EXIT_TIME_BY_TIER.get(tier, (7.0, 30.0))
            )
        else:
            min_days, max_days = _EXIT_TIME_BY_TIER.get(tier, (7.0, 30.0))

        base_days = (min_days + max_days) / 2.0 if max_days > min_days else min_days

        # Utilisation premium
        tvl_usd = _safe_float(self._get(adapter, "tvl_usd"), 0.0)
        amount  = max(_safe_float(amount_usd, 0.0), 0.0)
        if tvl_usd > 0.0 and amount > 0.0:
            utilisation = amount / tvl_usd
            if utilisation > _EXIT_TIME_UTILISATION_LOW:
                # Linear interpolation between base and max*multiplier
                t = min(
                    (utilisation - _EXIT_TIME_UTILISATION_LOW)
                    / (_EXIT_TIME_UTILISATION_HIGH - _EXIT_TIME_UTILISATION_LOW),
                    1.0,
                )
                premium_days = max_days * _EXIT_TIME_MAX_MULTIPLIER
                base_days = base_days + t * (premium_days - base_days)

        return round(max(base_days, 0.0), 4)
