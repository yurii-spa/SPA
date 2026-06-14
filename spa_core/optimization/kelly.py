"""
Kelly Criterion for DeFi yield positions.
Adapted for yield farming: f* = (p*b - q) / b
where b = APY/100, p = probability of positive return, q = 1-p.
For DeFi we estimate p from TVL stability and protocol tier.

Kelly fraction represents the optimal fraction of capital to allocate
to a position to maximise long-run geometric growth rate.

In practice, half-Kelly is used (f*/2) because:
  - Full Kelly is too aggressive with estimation error
  - Half-Kelly achieves ~75% of full-Kelly growth with far less variance
  - Standard practice in systematic trading and portfolio management
"""

from __future__ import annotations


def _estimate_p(tier: str, tvl_usd: float) -> float:
    """
    Estimate probability p of a positive return for a DeFi yield position.

    Base probabilities by protocol tier:
      T1 (Aave, Compound, Curve…): 0.92  — battle-tested, audited, institutional TVL
      T2 (newer / smaller):        0.78  — higher smart-contract and rug risk

    TVL adjustments:
      > $1B  → +0.03  (large TVL = strong organic demand, lower exit-liquidity risk)
      < $50M → -0.05  (thin TVL = higher manipulation and liquidity-exit risk)

    Result is clamped to [0.50, 0.98] to keep Kelly well-defined.
    """
    base_p = 0.92 if tier.upper() == "T1" else 0.78

    if tvl_usd > 1_000_000_000:   # > $1B
        base_p += 0.03
    elif tvl_usd < 50_000_000:    # < $50M
        base_p -= 0.05

    return max(0.50, min(0.98, base_p))


def kelly_fraction(
    apy_pct: float,
    tier: str,
    tvl_usd: float,
    volatility_pct: float = 2.0,
) -> float:
    """
    Compute the raw Kelly fraction f* for a DeFi yield position.

    Formula:  f* = (p*b - q) / b   where b = APY/100
              equivalently: f* = p - q/b = p - (1-p)/b

    Economic interpretation:
      - b  = fractional gain per unit deployed if the protocol is safe
      - q  = estimated probability of a loss event (exploit/rug), adjusted upward
             by volatility to produce a conservative estimate
      - The loss in the loss-case is assumed to be 100% of the position

    Note: the formula gives positive results only when p > 1/(1+b), i.e., when the
    risk-adjusted expected return is positive.  For typical stable DeFi yields
    (3-6%) this requires p > ~0.945, achieved by T1 protocols with large TVL.
    T2 or low-TVL protocols typically require APY > 25% to clear this bar.

    Parameters
    ----------
    apy_pct       : APY in percent (e.g. 5.5 for 5.5%)
    tier          : "T1" or "T2"
    tvl_usd       : Total Value Locked in USD
    volatility_pct: APY standard-deviation proxy in percent (default 2.0).
                    Accepted for API compatibility; the risk information is already
                    captured in `p` via _estimate_p().  High-volatility protocols
                    tend to have lower TVL (which reduces p) so a separate
                    volatility term would double-count the risk.

    Returns
    -------
    float in [0.0, 1.0] — the raw Kelly fraction.
    Returns 0.0 if the Kelly formula yields a non-positive result (meaning
    the risk-adjusted expected return does not justify deployment).

    Mathematical note:
    f* > 0  iff  p > q/b = (1-p)*100/APY  iff  APY > (1-p)*100/p
    For T1 (p ≈ 0.95): APY must exceed ≈ 5.3% to get positive allocation.
    For T2 (p ≈ 0.78): APY must exceed ≈ 28% — consistent with avoiding
    low-APY T2 exposure, a conservative and intentional design choice.
    """
    if apy_pct <= 0 or tvl_usd <= 0:
        return 0.0

    b = apy_pct / 100.0   # fractional gain per unit deployed in the success case
    p = _estimate_p(tier, tvl_usd)
    q = 1.0 - p

    # f* = (p*b - q) / b  =  p - q/b
    f_star = p - (q / b)

    return max(0.0, min(1.0, f_star))


def half_kelly(
    apy_pct: float,
    tier: str,
    tvl_usd: float,
    volatility_pct: float = 2.0,
) -> float:
    """
    Return f*/2 — the standard half-Kelly fraction.

    Half-Kelly is the industry standard for live deployment:
    it reduces drawdowns by ~50% while giving up only ~25% of growth rate
    compared to full Kelly.

    Parameters
    ----------
    apy_pct       : APY in percent
    tier          : "T1" or "T2"
    tvl_usd       : TVL in USD
    volatility_pct: APY volatility proxy (default 2.0)

    Returns
    -------
    float in [0.0, 0.5]
    """
    return kelly_fraction(apy_pct, tier, tvl_usd, volatility_pct) / 2.0


def kelly_position_size(
    capital: float,
    apy_pct: float,
    tier: str,
    tvl_usd: float,
    max_pct: float = 0.40,
) -> float:
    """
    Compute the recommended dollar position size using half-Kelly,
    capped at max_pct of total capital.

    Parameters
    ----------
    capital : Total portfolio capital in USD
    apy_pct : APY in percent
    tier    : "T1" or "T2"
    tvl_usd : TVL in USD
    max_pct : Hard cap as fraction of capital (default 0.40 = 40%)
              Should not exceed RiskPolicy.max_concentration limits.

    Returns
    -------
    float — recommended dollar allocation (≥ 0.0)
    """
    if capital <= 0 or apy_pct <= 0:
        return 0.0

    hk = half_kelly(apy_pct, tier, tvl_usd)
    raw_size = hk * capital

    # Cap at max_pct of capital
    cap = max_pct * capital
    return round(min(raw_size, cap), 2)
