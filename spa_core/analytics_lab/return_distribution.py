"""
Paper-trading daily-return distribution & historical VaR/CVaR (SPA-V383).

Read-only analytics layer that sits *on top of* the daily equity curve from
``equity_curve.py`` (SPA-V379). Where ``risk_metrics.py`` (SPA-V380) reduces the
return series to headline ratios (Sharpe/Sortino/Calmar) and
``rolling_performance.py`` (SPA-V381) gives a trailing-window view, this module
answers "what does the *shape* of the daily-return distribution look like, and
how bad is the tail" — the distribution stats, percentiles, histogram and
historical Value-at-Risk / Conditional-VaR an investor/reporting layer wants
next to the equity sparkline.

Design notes / safety:
  * Pure stdlib (json, math, statistics, datetime, pathlib, logging) — mirrors
    the no-external-dependency style of equity_curve.py / risk_metrics.py. No
    web3, no numpy/pandas/scipy.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    risk policy, wallets, or any money-moving code. It only reads
    pnl_history.json (via equity_curve.build_daily_equity_curve) and writes a
    derived report JSON.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen
    feed-health domain. It is pure portfolio-performance analytics.
  * Defensive: degenerate inputs (0, 1 or 2 days, zero spread) never raise —
    statistics that are mathematically undefined return ``None`` and the schema
    stays stable.

VaR / CVaR convention (historical, non-parametric):
    Both are reported as *losses* expressed as **negative percentages** of a
    single day's return (the same units as ``daily_return_pct``), so a more
    negative number is a worse outcome. For a confidence level ``c`` (e.g. 95),
    the (1 - c) lower-tail quantile of the realised daily returns is the VaR;
    CVaR (expected shortfall) is the mean of all realised returns at or below
    that quantile. A non-negative VaR/CVaR (i.e. no loss at that confidence)
    is clamped to 0.0 so "VaR" always reads as "the loss you don't expect to
    exceed".

Distribution stats (over realised daily returns, one per calendar day after
day 1):

    count                  number of daily returns
    mean_pct / median_pct  central tendency
    stdev_pct              population stdev
    min_pct / max_pct      extremes
    skewness               Fisher-Pearson sample skew (population moment)
    excess_kurtosis        kurtosis - 3 (0 == normal); >0 fat-tailed
    positive_days / negative_days / zero_days
    percentiles            {p5, p25, p50, p75, p95}  (linear interpolation)
    histogram              fixed-count equal-width buckets over [min, max]
    var                    {"95": pct, "99": pct, ...}  historical VaR (loss, <=0)
    cvar                   {"95": pct, "99": pct, ...}  historical CVaR (loss, <=0)

CLI::

    python -m spa_core.analytics_lab.return_distribution
    python -m spa_core.analytics_lab.return_distribution --history data/pnl_history.json \\
        --out data/return_distribution.json --bins 12 --confidence 90 95 99
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

from spa_core.paper_trading.equity_curve import (
    DEFAULT_HISTORY_PATH,
    build_daily_equity_curve,
    load_pnl_history,
)

log = logging.getLogger("spa.analytics_lab.return_distribution")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "return_distribution.json"

# Default tail confidence levels (percent) and histogram bucket count.
DEFAULT_CONFIDENCE_LEVELS = (95, 99)
DEFAULT_BINS = 10


def _daily_returns(curve: list[dict]) -> list[float]:
    """Realised daily returns (%) — i.e. every bar after the seed day 1.

    Day 1's ``daily_return_pct`` is a 0.0 seed (no prior close), so it is
    excluded to avoid biasing the distribution toward zero.
    """
    return [bar["daily_return_pct"] for bar in curve[1:]]


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (NIST/Excel ``PERCENTILE.INC`` style).

    ``sorted_values`` must be ascending and non-empty. ``pct`` in [0, 100].
    """
    if not sorted_values:
        raise ValueError("percentile of empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_values[lo]
    frac = rank - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _skewness(values: list[float], mean: float, stdev: float) -> float | None:
    """Population (Fisher-Pearson) skewness. None if undefined (n<2 or zero spread)."""
    n = len(values)
    if n < 2 or stdev == 0:
        return None
    m3 = sum((v - mean) ** 3 for v in values) / n
    return m3 / (stdev ** 3)


def _excess_kurtosis(values: list[float], mean: float, stdev: float) -> float | None:
    """Population excess kurtosis (kurtosis - 3). None if undefined."""
    n = len(values)
    if n < 2 or stdev == 0:
        return None
    m4 = sum((v - mean) ** 4 for v in values) / n
    return m4 / (stdev ** 4) - 3.0


def _histogram(sorted_values: list[float], bins: int) -> list[dict]:
    """Equal-width histogram over [min, max] with ``bins`` buckets.

    The final bucket is inclusive of the max so the largest value is counted.
    Returns a list of ``{lower, upper, count}`` dicts. Empty if no values.
    """
    if not sorted_values or bins < 1:
        return []
    lo, hi = sorted_values[0], sorted_values[-1]
    if hi == lo:
        # All identical → a single degenerate bucket holding every value.
        return [{"lower": round(lo, 6), "upper": round(hi, 6),
                 "count": len(sorted_values)}]
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in sorted_values:
        idx = int((v - lo) / width)
        if idx >= bins:  # the max value lands exactly on the top edge
            idx = bins - 1
        counts[idx] += 1
    return [
        {"lower": round(lo + i * width, 6),
         "upper": round(lo + (i + 1) * width, 6),
         "count": counts[i]}
        for i in range(bins)
    ]


def _historical_var_cvar(
    sorted_values: list[float], confidence_pct: float
) -> tuple[float | None, float | None]:
    """Historical (non-parametric) VaR and CVaR at ``confidence_pct``.

    Returns ``(var_pct, cvar_pct)`` as losses expressed as negative percentages
    (clamped to <= 0). ``(None, None)`` if there is no data.
    """
    if not sorted_values:
        return None, None
    alpha = (100.0 - confidence_pct) / 100.0  # lower-tail probability
    var_q = _percentile(sorted_values, alpha * 100.0)
    # Expected shortfall: mean of returns at or below the VaR quantile. Always
    # includes at least the worst observation so it is never empty.
    tail = [v for v in sorted_values if v <= var_q]
    if not tail:
        tail = [sorted_values[0]]
    cvar = statistics.fmean(tail)
    # Report as a loss: a non-negative quantile means "no loss at this
    # confidence" → clamp to 0.0.
    return min(var_q, 0.0), min(cvar, 0.0)


def compute_return_distribution(
    curve: list[dict],
    bins: int = DEFAULT_BINS,
    confidence_levels: tuple[int, ...] | list[int] = DEFAULT_CONFIDENCE_LEVELS,
) -> dict:
    """Compute the daily-return distribution + VaR/CVaR from a daily equity curve.

    Args:
        curve: list of daily bars as produced by
            ``equity_curve.build_daily_equity_curve``.
        bins: number of equal-width histogram buckets.
        confidence_levels: tail confidence levels in percent (e.g. (95, 99)).

    Returns:
        A stable-schema distribution dict. Statistics that are undefined for the
        given data (too few days, zero spread) are ``None``.
    """
    levels = [int(c) for c in confidence_levels]
    base = {
        "count":            0,
        "mean_pct":         None,
        "median_pct":       None,
        "stdev_pct":        None,
        "min_pct":          None,
        "max_pct":          None,
        "skewness":         None,
        "excess_kurtosis":  None,
        "positive_days":    0,
        "negative_days":    0,
        "zero_days":        0,
        "percentiles":      {"p5": None, "p25": None, "p50": None,
                             "p75": None, "p95": None},
        "histogram":        [],
        "var":              {str(c): None for c in levels},
        "cvar":             {str(c): None for c in levels},
        "bins":             int(bins),
        "confidence_levels": levels,
    }

    returns = _daily_returns(curve)
    n = len(returns)
    if n == 0:
        return base

    sorted_r = sorted(returns)
    mean = statistics.fmean(returns)
    median = statistics.median(returns)
    stdev = statistics.pstdev(returns) if n >= 1 else 0.0

    positive = sum(1 for r in returns if r > 0)
    negative = sum(1 for r in returns if r < 0)
    zero = n - positive - negative

    var_map: dict[str, float | None] = {}
    cvar_map: dict[str, float | None] = {}
    for c in levels:
        v, cv = _historical_var_cvar(sorted_r, float(c))
        var_map[str(c)] = None if v is None else round(v, 4)
        cvar_map[str(c)] = None if cv is None else round(cv, 4)

    def _rnd(x: float | None, places: int = 4) -> float | None:
        return None if x is None else round(x, places)

    return {
        "count":            n,
        "mean_pct":         round(mean, 4),
        "median_pct":       round(median, 4),
        "stdev_pct":        round(stdev, 4),
        "min_pct":          round(sorted_r[0], 4),
        "max_pct":          round(sorted_r[-1], 4),
        "skewness":         _rnd(_skewness(returns, mean, stdev)),
        "excess_kurtosis":  _rnd(_excess_kurtosis(returns, mean, stdev)),
        "positive_days":    positive,
        "negative_days":    negative,
        "zero_days":        zero,
        "percentiles": {
            "p5":  round(_percentile(sorted_r, 5), 4),
            "p25": round(_percentile(sorted_r, 25), 4),
            "p50": round(_percentile(sorted_r, 50), 4),
            "p75": round(_percentile(sorted_r, 75), 4),
            "p95": round(_percentile(sorted_r, 95), 4),
        },
        "histogram":        _histogram(sorted_r, bins),
        "var":              var_map,
        "cvar":             cvar_map,
        "bins":             int(bins),
        "confidence_levels": levels,
    }


def generate_return_distribution_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    bins: int = DEFAULT_BINS,
    confidence_levels: tuple[int, ...] | list[int] = DEFAULT_CONFIDENCE_LEVELS,
) -> dict:
    """Build the full return-distribution report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        output_path: where to write the report JSON. Pass ``None`` to skip
            writing (compute-only).
        bins: number of histogram buckets.
        confidence_levels: tail confidence levels in percent.

    Returns:
        ``{"generated_at", "source", "distribution"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "distribution": compute_return_distribution(curve, bins, confidence_levels),
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
            log.info(
                "return distribution report written: %s (%d days, var95=%s)",
                out, report["distribution"]["count"],
                report["distribution"]["var"].get("95"),
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning(
                "could not write return distribution report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compute daily-return distribution + historical VaR/CVaR "
                    "from paper-trading P&L history.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/return_distribution.json)",
    )
    p.add_argument(
        "--bins", type=int, default=DEFAULT_BINS,
        help=f"number of histogram buckets (default: {DEFAULT_BINS})",
    )
    p.add_argument(
        "--confidence", type=int, nargs="+", default=list(DEFAULT_CONFIDENCE_LEVELS),
        help="tail confidence levels in percent (default: 95 99)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_return_distribution_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
        bins=args.bins,
        confidence_levels=args.confidence,
    )
    print(json.dumps(report["distribution"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
