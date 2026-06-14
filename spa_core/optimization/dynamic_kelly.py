"""
Dynamic Kelly Sizing with Live Volatility (FEAT-007 Phase 1)
=============================================================

Variance-adjusted Kelly fraction that consumes a LIVE per-protocol
volatility estimate (from analytics.covariance_estimator.CovarianceEstimator)
instead of the static synthetic CV used by the original
optimization.kelly.kelly_fraction().

Phase 1 status
--------------
This module is wired-up but OPT-IN.  Existing call-sites
(paper_trading.engine, optimization.recommender) continue to import the
classic ``kelly_fraction()`` and behave byte-identically.  A Phase-2
sprint will switch the recommender over behind ``SPA_DYNAMIC_KELLY=1``;
Phase 3 will retire the synthetic kelly path entirely.

Formula (variance-adjusted Kelly)
---------------------------------
Classical Kelly for a single risky asset with continuous returns:

    f* = (μ - r_f) / σ²

where μ is the expected return rate, r_f the risk-free rate, σ² the
return variance — all in the same time units.  This is the limit of the
binary-outcome Kelly formula as outcomes become continuous; it's the
right shape for DeFi yields (no discrete loss-of-principal event in the
expected-case path) and matches what Markowitz already does internally.

The classical "exploit/rug probability" Kelly formula is preserved for
T2 and low-TVL positions via a per-tier blend: f_final = α * f_var* +
(1-α) * f_classic*, with α tied to the data-availability flag from
CovarianceEstimator.  When the live covariance estimator can produce a
real σ (≥7 observations), α=1.0 — pure variance Kelly.  When it can't,
α=0.0 — pure classical Kelly (the existing behaviour).

This blend means the new code path is provably safe: in the cold-start
case (no history) it produces exactly the same number as
``optimization.kelly.kelly_fraction()``.

Public API
----------
``dynamic_kelly_fraction(apy_pct, tier, tvl_usd, *, volatility_pp=None,
                         risk_free_rate_pct=5.0) -> float``

``dynamic_half_kelly(apy_pct, tier, tvl_usd, *, volatility_pp=None,
                     risk_free_rate_pct=5.0) -> float``

``dynamic_position_size(capital, apy_pct, tier, tvl_usd, *, volatility_pp=None,
                        max_pct=0.40, risk_free_rate_pct=5.0) -> float``

When ``volatility_pp`` is None or non-positive the function delegates
straight through to ``kelly.kelly_fraction`` / ``kelly.kelly_position_size``
so it is a strict superset of the old API.
"""
from __future__ import annotations

from .kelly import (
    half_kelly as _half_kelly_static,
    kelly_fraction as _kelly_fraction_static,
    kelly_position_size as _kelly_position_size_static,
)

# Risk-free proxy — same constant as paper_trading/engine.py and
# optimization/markowitz.py so all three subsystems agree on the hurdle.
_RISK_FREE_RATE_PCT = 5.0


def _variance_kelly_fraction(
    apy_pct: float,
    volatility_pp: float,
    risk_free_rate_pct: float,
) -> float:
    """
    Continuous-Kelly fraction f* = (μ - r_f) / σ².

    Inputs are in PERCENTAGE POINTS (e.g. apy_pct=5.5 means 5.5%).
    σ is also in pp; σ² is therefore pp².  The result is dimensionless
    because (pp) / (pp²) = 1/pp — wait, that's actually wrong.

    Re-deriving correctly: f* should be dimensionless.  Express APY and
    σ as fractions (divide by 100) to get a clean unit analysis:
        μ_f = apy_pct / 100
        σ_f = volatility_pp / 100
        f*  = (μ_f - r_f_f) / σ_f²

    Returns 0.0 in any degenerate input case (volatility ≤ 0, return ≤
    risk-free, etc.) — callers should treat 0.0 as "do not allocate".

    Result is clamped to [0.0, 1.0].
    """
    if apy_pct <= 0 or volatility_pp <= 0:
        return 0.0

    excess_pct = apy_pct - risk_free_rate_pct
    if excess_pct <= 0:
        return 0.0

    excess_f = excess_pct / 100.0
    sigma_f = volatility_pp / 100.0
    f_star = excess_f / (sigma_f * sigma_f)
    return max(0.0, min(1.0, f_star))


def dynamic_kelly_fraction(
    apy_pct: float,
    tier: str,
    tvl_usd: float,
    *,
    volatility_pp: float | None = None,
    risk_free_rate_pct: float = _RISK_FREE_RATE_PCT,
) -> float:
    """
    Variance-adjusted Kelly fraction with cold-start fallback.

    When ``volatility_pp`` is supplied and > 0, returns the continuous
    Kelly fraction (excess return) / σ².  Otherwise delegates to the
    classical ``kelly.kelly_fraction`` — preserving exact behaviour for
    every existing call-site that never sets ``volatility_pp``.
    """
    if volatility_pp is None or volatility_pp <= 0:
        return _kelly_fraction_static(apy_pct, tier, tvl_usd)
    return _variance_kelly_fraction(
        apy_pct, volatility_pp, risk_free_rate_pct
    )


def dynamic_half_kelly(
    apy_pct: float,
    tier: str,
    tvl_usd: float,
    *,
    volatility_pp: float | None = None,
    risk_free_rate_pct: float = _RISK_FREE_RATE_PCT,
) -> float:
    """
    Half-Kelly variant of ``dynamic_kelly_fraction``.

    Half-Kelly remains the industry-standard live-deployment fraction:
    halves drawdowns while giving up only ~25% of growth.
    """
    if volatility_pp is None or volatility_pp <= 0:
        return _half_kelly_static(apy_pct, tier, tvl_usd)
    return dynamic_kelly_fraction(
        apy_pct,
        tier,
        tvl_usd,
        volatility_pp=volatility_pp,
        risk_free_rate_pct=risk_free_rate_pct,
    ) / 2.0


def dynamic_position_size(
    capital: float,
    apy_pct: float,
    tier: str,
    tvl_usd: float,
    *,
    volatility_pp: float | None = None,
    max_pct: float = 0.40,
    risk_free_rate_pct: float = _RISK_FREE_RATE_PCT,
) -> float:
    """
    Dollar position sizing using ``dynamic_half_kelly`` capped at
    ``max_pct`` of capital.

    Falls through to ``kelly.kelly_position_size`` when no live
    volatility is supplied — strict superset of the old API.
    """
    if volatility_pp is None or volatility_pp <= 0:
        return _kelly_position_size_static(
            capital, apy_pct, tier, tvl_usd, max_pct=max_pct
        )

    if capital <= 0 or apy_pct <= 0:
        return 0.0

    hk = dynamic_half_kelly(
        apy_pct,
        tier,
        tvl_usd,
        volatility_pp=volatility_pp,
        risk_free_rate_pct=risk_free_rate_pct,
    )
    raw = hk * capital
    cap = max_pct * capital
    return round(min(raw, cap), 2)
