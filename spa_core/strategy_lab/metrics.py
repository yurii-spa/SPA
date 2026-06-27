"""
spa_core/strategy_lab/metrics.py — standard comparison metric set for the Strategy Lab.

Computes a StrategyMetrics (base.py) from an equity time-series + daily returns + an event
log. ONE metric set for every strategy (candidates + wrapped baselines) so comparison is
honest. Reuses the Tier-1 stats helpers rather than reimplementing:

  - spa_core.backtesting.tier1.deflated_sharpe : moments, sharpe_per_period, annualize_sharpe,
                                                 probabilistic_sharpe_ratio
  - spa_core.backtesting.tier1.tail_risk       : risk_adjusted_net_apy / strategy_tail_risk

Only the genuinely missing pieces are added locally: annualized net APY from an equity curve,
max drawdown, Sortino, beta-to-ETH regression, funding drag, correlation to a stable blend,
the joint ETH-down-20%/funding-flip tail scenario, and the beats-RWA-floor decision.

stdlib-only, deterministic. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

from spa_core.strategy_lab.base import StrategyMetrics
from spa_core.strategy_lab.config import rwa_floor_apy_pct
from spa_core.backtesting.tier1.deflated_sharpe import (
    moments,
    sharpe_per_period,
    annualize_sharpe,
    DAYS_PER_YEAR,
)

# moments is imported above and reused by sharpe()/volatility_pct() — single source.

# ──────────────────────────────────────────────────────────────────────────────
# Local helpers (the bits not already in tier1)
# ──────────────────────────────────────────────────────────────────────────────


def _clean(xs: Sequence[Optional[float]]) -> List[float]:
    """Drop None AND non-finite (NaN/inf) inputs — fail-CLOSED.

    A NaN/inf in an equity or return series is a corrupt point, never a real
    observation; left in, it poisons every downstream sum/ratio into a silent
    NaN/inf (which then serializes to invalid JSON ``NaN``/``Infinity`` tokens).
    Dropping it here is a no-op for a valid (all-finite) series and turns a
    degenerate series into honest "too few points" rather than a leaked NaN.
    """
    return [float(x) for x in xs if x is not None and math.isfinite(x)]


def _finite_or(value: float, fallback: float) -> float:
    """Return ``value`` if finite, else ``fallback`` — last-line fail-CLOSED guard so a
    metric NEVER returns NaN/inf even if a non-finite slips past the input clean."""
    return value if math.isfinite(value) else fallback


def net_apy_from_equity(equity_series: Sequence[float]) -> float:
    """Annualized net return (%) implied by an equity curve (compounded, daily steps)."""
    eq = _clean(equity_series)
    if len(eq) < 2 or eq[0] <= 0:
        return 0.0
    n_days = len(eq) - 1
    total_growth = eq[-1] / eq[0]
    if total_growth <= 0:
        return -100.0
    try:
        annual_growth = total_growth ** (DAYS_PER_YEAR / n_days)
    except OverflowError:
        annual_growth = float("inf")
    # fail-CLOSED: an overflow/non-finite annualization is not a real APY — report 0.0
    # rather than leak inf/NaN into the scorecard JSON.
    return round(_finite_or((annual_growth - 1.0) * 100.0, 0.0), 4)


def max_drawdown_pct(equity_series: Sequence[float]) -> float:
    """Worst peak-to-trough decline (%, reported as a positive number)."""
    eq = _clean(equity_series)
    if len(eq) < 2:
        return 0.0
    peak = eq[0]
    worst = 0.0
    for v in eq:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > worst:
                worst = dd
    return round(_finite_or(worst * 100.0, 0.0), 4)


def volatility_pct(daily_returns: Sequence[float]) -> float:
    """Annualized volatility (%) of daily returns."""
    rets = _clean(daily_returns)
    if len(rets) < 2:
        return 0.0
    std = moments(rets)["std"]
    return round(_finite_or(std * math.sqrt(DAYS_PER_YEAR) * 100.0, 0.0), 4)


def sharpe(daily_returns: Sequence[float], rf_daily: float = 0.0) -> Optional[float]:
    """Annualized Sharpe (reuses tier1 sharpe_per_period + annualize_sharpe).

    Returns ``None`` — NOT a giant finite number — for a locked-volatility book whose
    return variance is only floating-point noise (a fixed-APY accrual: std ≈ 1e-20 while
    mean ≈ 1e-7 → mean/std explodes to ~1e17). The Sharpe of a zero-variance series is
    mathematically undefined; reporting 451,467,719 as a "Sharpe" is an honesty artifact
    (it reads as a real risk-adjusted score). The guard is RELATIVE to the mean so it fires
    on a constant accrual regardless of the APY level, but a genuinely low-vol-yet-noisy
    book (real daily APY jitter) still gets a finite, honest Sharpe.
    """
    rets = _clean(daily_returns)
    if len(rets) < 2:
        return None
    m = moments(rets)
    std = m["std"]
    mean = m["mean"]
    # Undefined when there is no REAL dispersion. Absolute floor catches an exactly-flat
    # book. The relative test fires when std is smaller than ~1ppm of |mean|: a fixed-rate
    # accrual's only "variance" is float64 rounding noise (observed std/mean ≈ 1e-8 for the
    # engine_a/b/c/rwa baselines → Sharpe ≈ 4.5e8…1.2e9, a pure artifact). A genuinely
    # low-vol-yet-noisy book has daily APY jitter of basis points → std/mean ≳ 1e-3, far
    # above this floor, so it still gets an honest finite Sharpe.
    if std <= 1e-15 or (mean != 0.0 and std < abs(mean) * 1e-6):
        return None
    val = annualize_sharpe(sharpe_per_period(rets, rf_daily))
    # fail-CLOSED: a non-finite Sharpe is undefined (UNKNOWN), never a leaked NaN/inf number.
    return round(val, 4) if math.isfinite(val) else None


def sortino(daily_returns: Sequence[float], rf_daily: float = 0.0) -> Optional[float]:
    """Annualized Sortino: excess mean / downside deviation (only sub-rf returns penalized).

    Returns ``None`` — NOT 0.0 — for a book with no real downside dispersion (a fixed-APY
    accrual or a hedged/floor book whose returns never dip meaningfully below rf). This MIRRORS
    the sharpe() honesty guard: a zero/near-zero downside-deviation Sortino is mathematically
    UNDEFINED (excess / 0). Reporting it as 0.0 reads to a user as a BAD risk-adjusted score
    when the truth is the opposite — the book simply had no downside to penalize, which is
    excellent. A genuinely low-but-NONZERO downside still gets a finite, honest Sortino. The
    relative floor (downside deviation < ~1ppm of |mean|) catches a fixed-rate accrual whose
    only "downside" is float64 rounding noise, exactly as sharpe() does for total variance.
    """
    rets = _clean(daily_returns)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    downside = [(r - rf_daily) ** 2 for r in rets if r < rf_daily]
    if not downside:
        # No sub-rf return at all → downside deviation is undefined, not zero.
        return None
    dd = math.sqrt(sum(downside) / len(rets))
    # Undefined when there is no REAL downside dispersion. Absolute floor catches an exactly-flat
    # book; the relative test fires when dd is smaller than ~1ppm of |mean| (float-noise-only),
    # mirroring sharpe(). A genuinely low-vol-yet-noisy book keeps an honest finite Sortino.
    if dd <= 1e-15 or (mean != 0.0 and dd < abs(mean) * 1e-6):
        return None
    val = ((mean - rf_daily) / dd) * math.sqrt(DAYS_PER_YEAR)
    # fail-CLOSED: a non-finite Sortino is undefined (UNKNOWN), never a leaked NaN/inf number.
    return round(val, 4) if math.isfinite(val) else None


def _aligned(a: Sequence[Optional[float]], b: Sequence[Optional[float]]):
    """Align two series, dropping any pair where EITHER value is None or non-finite
    (NaN/inf) — fail-CLOSED, so beta/correlation never ingest a corrupt point that
    would silently poison the regression into NaN."""
    xs, ys = [], []
    for x, y in zip(a, b):
        if (
            x is not None and y is not None
            and math.isfinite(x) and math.isfinite(y)
        ):
            xs.append(float(x))
            ys.append(float(y))
    return xs, ys


def beta(strategy_returns: Sequence[float], market_returns: Sequence[float]) -> float:
    """OLS beta of strategy daily returns vs ETH daily returns. ~0 for neutral, ~1 for
    directional. cov(s, m) / var(m)."""
    xs, ys = _aligned(strategy_returns, market_returns)  # xs=strategy, ys=market
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    var_m = sum((y - my) ** 2 for y in ys)
    if var_m == 0:
        return 0.0
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return round(_finite_or(cov / var_m, 0.0), 4)


def correlation(a: Sequence[Optional[float]], b: Sequence[Optional[float]]) -> Optional[float]:
    """Pearson correlation of two aligned daily-return series. None when undefined."""
    xs, ys = _aligned(a, b)
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    val = cov / (sx * sy)
    # fail-CLOSED: a non-finite correlation is undefined (None), never a leaked NaN.
    return round(val, 4) if math.isfinite(val) else None


def funding_drag_pct(events: Sequence[dict], capital: float) -> float:
    """Cumulative funding cost as % of capital (for the neutral variant's perp short).

    Sums event entries of type 'funding' (field 'usd', negative = cost paid). Reported as a
    positive drag percent (cost / capital * 100). 0 when no funding events / no capital."""
    if capital <= 0:
        return 0.0
    total_cost = 0.0
    for ev in events or []:
        if ev.get("type") == "funding":
            usd = float(ev.get("usd", 0.0))
            if usd < 0:
                total_cost += -usd
    return round(total_cost / capital * 100.0, 4)


def tail_eth_down20_funding_flip_pct(
    positions: Sequence,
    capital: float,
    beta_to_eth: float,
    funding_flip_8h: float = 0.0005,
    settles_per_day: int = 3,
    horizon_days: int = 1,
) -> float:
    """P&L (% of capital) under the joint stress: ETH -20% AND perp funding flips negative.

    Two legs:
      • Directional/price exposure: beta_to_eth * (-20%) on capital — a neutral book (beta~0)
        barely moves; a directional one (beta~1) takes ~-20%.
      • Funding leg: the perp short now PAYS funding; cost = |short notional| * flip * settles.
        Short notional is read from the strategy's perp_short positions; for a hedged neutral
        book this is the dominant stress term (its price leg is hedged out).
    Returns a percent of capital (negative = loss)."""
    if capital <= 0:
        return 0.0
    eth_shock = -0.20
    price_pnl = beta_to_eth * eth_shock * capital

    short_notional = 0.0
    for p in positions or []:
        kind = getattr(p, "kind", None)
        if kind == "perp_short":
            short_notional += abs(getattr(p, "notional_usd", 0.0))
    funding_cost = short_notional * abs(funding_flip_8h) * settles_per_day * horizon_days

    pnl_usd = price_pnl - funding_cost
    return round(pnl_usd / capital * 100.0, 4)


def beats_rwa_floor(
    net_apy_pct: float,
    max_dd_pct: float,
    floor_apy_pct: Optional[float] = None,
) -> bool:
    """Risk-adjusted decision vs the RWA risk-free floor.

    A strategy 'beats the floor' only if its net APY exceeds the floor AND it does so on a
    risk-adjusted basis: excess-return-per-unit-drawdown (a Calmar-style ratio against the
    floor) must be positive and the drawdown must not erase the excess. The floor itself has
    ~0 drawdown, so any strategy taking drawdown must out-earn it to compensate."""
    floor = rwa_floor_apy_pct() if floor_apy_pct is None else float(floor_apy_pct)
    excess = net_apy_pct - floor
    if excess <= 0:
        return False
    # Risk-adjusted: the annual excess must at least cover the realized drawdown.
    return excess > max_dd_pct


# ──────────────────────────────────────────────────────────────────────────────
# Aggregate
# ──────────────────────────────────────────────────────────────────────────────


def compute_metrics(
    equity_series: Sequence[float],
    daily_returns: Sequence[float],
    eth_returns: Sequence[float],
    stable_returns: Sequence[float],
    events: Sequence[dict],
    config: dict,
    positions: Optional[Sequence] = None,
) -> StrategyMetrics:
    """Build the full StrategyMetrics from an equity/return series + event log.

    Args:
        equity_series : daily equity values (>=2 points).
        daily_returns : strategy daily fractional returns.
        eth_returns   : ETH daily fractional returns (for beta).
        stable_returns: stable-yield benchmark daily returns (for correlation).
        events        : event log dicts; funding events {'type':'funding','usd':...}.
        config        : strategy config block (uses 'capital_usd' / global initial_capital,
                        'funding_settles_per_day', 'rwa_floor_apy_pct' if present).
        positions     : optional current Position list (for the tail scenario short leg).
    """
    capital = float(
        config.get("capital_usd")
        or config.get("initial_capital")
        or (equity_series[0] if equity_series else 0.0)
    )
    settles = int(config.get("funding_settles_per_day", 3))
    floor = config.get("rwa_floor_apy_pct")

    napy = net_apy_from_equity(equity_series)
    mdd = max_drawdown_pct(equity_series)
    b_eth = beta(daily_returns, eth_returns)

    return StrategyMetrics(
        net_apy_pct=napy,
        max_drawdown_pct=mdd,
        sharpe=sharpe(daily_returns),
        sortino=sortino(daily_returns),
        volatility_pct=volatility_pct(daily_returns),
        beta_to_eth=b_eth,
        funding_drag_pct=funding_drag_pct(events, capital),
        corr_to_stable_blend=correlation(daily_returns, stable_returns),
        tail_eth_down20_funding_flip_pct=tail_eth_down20_funding_flip_pct(
            positions or [], capital, b_eth, settles_per_day=settles
        ),
        beats_rwa_floor=beats_rwa_floor(napy, mdd, floor),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Comparative table
# ──────────────────────────────────────────────────────────────────────────────


def _fmt(v, suffix="", nd=2):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "✅" if v else "❌"
    return f"{v:.{nd}f}{suffix}"


def compare_table(results: Dict[str, StrategyMetrics], floor_apy_pct: Optional[float] = None) -> str:
    """Markdown comparative table of strategies vs the RWA floor. Non-passers (beats_rwa_floor
    False) are flagged. `results` maps strategy id -> StrategyMetrics."""
    floor = rwa_floor_apy_pct() if floor_apy_pct is None else float(floor_apy_pct)
    header = (
        f"### Strategy Lab — comparison vs RWA floor ({floor:.2f}% APY)\n\n"
        "| Strategy | Net APY % | MaxDD % | Sharpe | Sortino | Vol % | β(ETH) | "
        "FundDrag % | Corr(stable) | Tail(ETH-20/flip) % | Beats Floor |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for sid, m in results.items():
        flag = "" if m.beats_rwa_floor else "  ⚠ below floor"
        rows.append(
            f"| {sid}{flag} | {_fmt(m.net_apy_pct)} | {_fmt(m.max_drawdown_pct)} | "
            f"{_fmt(m.sharpe)} | {_fmt(m.sortino)} | {_fmt(m.volatility_pct)} | "
            f"{_fmt(m.beta_to_eth)} | {_fmt(m.funding_drag_pct)} | "
            f"{_fmt(m.corr_to_stable_blend)} | {_fmt(m.tail_eth_down20_funding_flip_pct)} | "
            f"{_fmt(m.beats_rwa_floor)} |"
        )
    return header + "\n".join(rows)
