"""
Paper-trading benchmark-relative performance analytics (SPA-V394).

Read-only analytics layer that sits *on top of* the daily equity curve from
``equity_curve.py`` (SPA-V379). The existing paper-trading analytics describe the
portfolio in isolation — headline ratios (``risk_metrics.py`` / SPA-V380),
trailing windows (``rolling_performance.py`` / SPA-V381), drawdown episodes
(``drawdown_analysis.py`` / SPA-V382), the return distribution + tail risk
(``return_distribution.py`` / SPA-V383) and the calendar/streak view
(``calendar_returns.py`` / SPA-V384). What none of them answer is "how did the
portfolio do *relative to a baseline* you could have parked the same capital
in" — i.e. the excess-return / active-risk framing an investor/reporting layer
expects. This module fills that gap.

It compares the realised daily-return series against a benchmark and reports the
classic relative-performance battery:

    excess / active return     portfolio return minus the benchmark return
    tracking_error_pct         stdev of the daily active returns (active risk)
    information_ratio          mean active return / tracking error (annualised too)
    beta                       cov(portfolio, benchmark) / var(benchmark)
    correlation                Pearson correlation of the two return series
    up_capture / down_capture  how much of the benchmark's up / down moves the
                               portfolio captured (only defined for a *varying*
                               benchmark)
    days_outperformed          count of days the portfolio beat the benchmark

Benchmark convention:
    By default the benchmark is a **flat risk-free baseline** — a constant annual
    rate (default 4.0%, a stablecoin-lending proxy) converted to a per-day return
    via ``(1 + apy/100) ** (1/365) - 1``. A flat benchmark has zero variance, so
    the variance-dependent metrics (``beta``, ``correlation``, ``up_capture``,
    ``down_capture``) are mathematically undefined and reported as ``None`` — the
    variance-free metrics (excess return, tracking error, information ratio,
    days-outperformed) remain fully meaningful and are exactly the "excess return
    over the risk-free rate" view. Callers that *do* have a varying benchmark
    (e.g. an index return series) can pass ``benchmark_returns`` directly and then
    every metric — beta/correlation/capture included — is populated.

Design notes / safety:
  * Pure stdlib (json, math, statistics, datetime, pathlib, logging) — mirrors
    the no-external-dependency style of the sibling modules. No web3, no
    numpy/pandas/scipy.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    risk policy, wallets, or any money-moving code. It only reads
    pnl_history.json (via equity_curve.build_daily_equity_curve) and writes a
    derived report JSON.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen
    feed-health domain. It is pure portfolio-performance analytics.
  * Defensive: degenerate inputs (0 or 1 day, zero spread, zero-variance
    benchmark) never raise — undefined statistics return ``None`` and the schema
    stays stable.

CLI::

    python -m spa_core.paper_trading.benchmark_comparison
    python -m spa_core.paper_trading.benchmark_comparison --history data/pnl_history.json \\
        --out data/benchmark_comparison.json --benchmark-apy 4.0 --periods 365
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

log = logging.getLogger("spa.paper_trading.benchmark_comparison")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "benchmark_comparison.json"

# Default flat-benchmark annual rate (%). 4.0% ~ a conservative stablecoin /
# risk-free lending baseline; the comparison then reads as "excess over baseline".
DEFAULT_BENCHMARK_APY = 4.0
# Trading periods per year used to annualise / to convert the flat annual
# benchmark rate to a per-day return. 365 matches the calendar-day cadence of
# the daily equity curve.
DEFAULT_PERIODS_PER_YEAR = 365


def _daily_returns(curve: list[dict]) -> list[float]:
    """Realised daily returns (%) — every bar after the seed day 1.

    Day 1's ``daily_return_pct`` is a 0.0 seed (no prior close), so it is
    excluded to avoid biasing the comparison toward zero. Mirrors the
    convention used by ``return_distribution._daily_returns``.
    """
    return [bar["daily_return_pct"] for bar in curve[1:]]


def _flat_daily_return_pct(annual_pct: float, periods_per_year: int) -> float:
    """Per-period return (%) of a flat annual rate, compounded.

    ``(1 + annual/100) ** (1/periods) - 1`` expressed as a percentage.
    """
    if periods_per_year <= 0:
        return 0.0
    return ((1.0 + annual_pct / 100.0) ** (1.0 / periods_per_year) - 1.0) * 100.0


def _compound_pct(returns: list[float]) -> float:
    """Cumulative compounded return (%) of a series of per-period returns (%)."""
    factor = 1.0
    for r in returns:
        factor *= (1.0 + r / 100.0)
    return (factor - 1.0) * 100.0


def _covariance(xs: list[float], ys: list[float], mean_x: float, mean_y: float) -> float:
    """Population covariance of two equal-length series."""
    n = len(xs)
    if n == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / n


def compute_benchmark_comparison(
    curve: list[dict],
    benchmark_returns: list[float] | None = None,
    benchmark_annual_pct: float = DEFAULT_BENCHMARK_APY,
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> dict:
    """Compute benchmark-relative performance from a daily equity curve.

    Args:
        curve: list of daily bars as produced by
            ``equity_curve.build_daily_equity_curve``.
        benchmark_returns: optional explicit benchmark daily-return series (%).
            When provided it is aligned to the portfolio series by truncating
            both to the shorter length. When ``None`` a *flat* benchmark derived
            from ``benchmark_annual_pct`` is used.
        benchmark_annual_pct: annual rate (%) for the flat benchmark.
        periods_per_year: periods/year for annualisation and the flat-rate
            per-day conversion.

    Returns:
        A stable-schema comparison dict. Metrics that are undefined for the given
        data (too few days, zero-variance benchmark) are ``None``.
    """
    benchmark_kind = "explicit" if benchmark_returns is not None else "flat_risk_free"
    base = {
        "count":                    0,
        "benchmark_kind":           benchmark_kind,
        "benchmark_annual_pct":     round(float(benchmark_annual_pct), 4),
        "benchmark_daily_pct":      None,
        "periods_per_year":         int(periods_per_year),
        "portfolio_total_return_pct":   None,
        "benchmark_total_return_pct":   None,
        "excess_total_return_pct":      None,
        "portfolio_annualized_pct":     None,
        "benchmark_annualized_pct":     None,
        "mean_active_return_pct":   None,
        "tracking_error_pct":       None,
        "information_ratio":        None,
        "information_ratio_annualized": None,
        "beta":                     None,
        "correlation":              None,
        "up_capture":               None,
        "down_capture":             None,
        "days_outperformed":        0,
        "days_underperformed":      0,
        "days_matched":             0,
        "best_active_day":          None,
        "worst_active_day":         None,
    }

    port = _daily_returns(curve)
    n = len(port)
    if n == 0:
        return base

    # Build / align the benchmark series.
    if benchmark_returns is None:
        bench_daily = _flat_daily_return_pct(benchmark_annual_pct, periods_per_year)
        bench = [bench_daily] * n
    else:
        m = min(n, len(benchmark_returns))
        port = port[:m]
        bench = list(benchmark_returns[:m])
        n = m
    if n == 0:
        return base

    # Active (excess) daily returns.
    dates = [bar.get("date") for bar in curve[1:1 + n]]
    active = [p - b for p, b in zip(port, bench)]

    mean_p = statistics.fmean(port)
    mean_b = statistics.fmean(bench)
    mean_active = statistics.fmean(active)
    # Population stdev of active returns == tracking error. Undefined (None) only
    # when there is a single observation.
    tracking_error = statistics.pstdev(active) if n >= 1 else 0.0

    # Information ratio: active return per unit of active risk. Undefined when
    # tracking error is 0 (portfolio tracks the benchmark exactly).
    if tracking_error and tracking_error != 0:
        info_ratio = mean_active / tracking_error
        info_ratio_ann = info_ratio * math.sqrt(periods_per_year) if periods_per_year > 0 else None
    else:
        info_ratio = None
        info_ratio_ann = None

    # Beta / correlation require a benchmark with non-zero variance.
    var_b = statistics.pvariance(bench) if n >= 1 else 0.0
    var_p = statistics.pvariance(port) if n >= 1 else 0.0
    if var_b > 0:
        cov_pb = _covariance(port, bench, mean_p, mean_b)
        beta = cov_pb / var_b
        if var_p > 0:
            correlation = cov_pb / math.sqrt(var_p * var_b)
            # Guard against tiny floating-point overshoot beyond [-1, 1].
            correlation = max(-1.0, min(1.0, correlation))
        else:
            correlation = None
    else:
        beta = None
        correlation = None

    # Up / down capture: portfolio compounded return on benchmark-up vs
    # benchmark-down days, relative to the benchmark's compounded return on those
    # same days. Only meaningful for a *varying* benchmark — a flat benchmark
    # has zero variance (all days identical), so the up/down split is degenerate
    # and the ratios are reported as None (consistent with beta/correlation).
    def _capture(p_series: list[float], b_series: list[float]) -> float | None:
        if not b_series:
            return None
        b_cum = _compound_pct(b_series)
        if b_cum == 0:
            return None
        return _compound_pct(p_series) / b_cum

    if var_b > 0:
        up_p = [p for p, b in zip(port, bench) if b > 0]
        up_b = [b for b in bench if b > 0]
        dn_p = [p for p, b in zip(port, bench) if b < 0]
        dn_b = [b for b in bench if b < 0]
        up_capture = _capture(up_p, up_b)
        down_capture = _capture(dn_p, dn_b)
    else:
        up_capture = None
        down_capture = None

    days_out = sum(1 for a in active if a > 0)
    days_under = sum(1 for a in active if a < 0)
    days_match = n - days_out - days_under

    # Best / worst active day (by active return).
    best_idx = max(range(n), key=lambda i: active[i])
    worst_idx = min(range(n), key=lambda i: active[i])
    best_active = {"date": dates[best_idx], "active_return_pct": round(active[best_idx], 4)}
    worst_active = {"date": dates[worst_idx], "active_return_pct": round(active[worst_idx], 4)}

    port_total = _compound_pct(port)
    bench_total = _compound_pct(bench)

    def _annualize(total_pct: float) -> float:
        # Geometric annualisation from the realised compounded return.
        factor = 1.0 + total_pct / 100.0
        if factor <= 0:
            return -100.0
        return (factor ** (periods_per_year / n) - 1.0) * 100.0

    def _rnd(x: float | None, places: int = 4) -> float | None:
        return None if x is None else round(x, places)

    return {
        "count":                    n,
        "benchmark_kind":           benchmark_kind,
        "benchmark_annual_pct":     round(float(benchmark_annual_pct), 4),
        "benchmark_daily_pct":      round(mean_b, 6),
        "periods_per_year":         int(periods_per_year),
        "portfolio_total_return_pct":   round(port_total, 4),
        "benchmark_total_return_pct":   round(bench_total, 4),
        "excess_total_return_pct":      round(port_total - bench_total, 4),
        "portfolio_annualized_pct":     round(_annualize(port_total), 4),
        "benchmark_annualized_pct":     round(_annualize(bench_total), 4),
        "mean_active_return_pct":   round(mean_active, 6),
        "tracking_error_pct":       round(tracking_error, 6),
        "information_ratio":        _rnd(info_ratio),
        "information_ratio_annualized": _rnd(info_ratio_ann),
        "beta":                     _rnd(beta),
        "correlation":              _rnd(correlation),
        "up_capture":               _rnd(up_capture),
        "down_capture":             _rnd(down_capture),
        "days_outperformed":        days_out,
        "days_underperformed":      days_under,
        "days_matched":             days_match,
        "best_active_day":          best_active,
        "worst_active_day":         worst_active,
    }


def generate_benchmark_comparison_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    benchmark_annual_pct: float = DEFAULT_BENCHMARK_APY,
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> dict:
    """Build the full benchmark-comparison report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        output_path: where to write the report JSON. Pass ``None`` to skip
            writing (compute-only).
        benchmark_annual_pct: annual rate (%) for the flat benchmark.
        periods_per_year: periods/year for annualisation.

    Returns:
        ``{"generated_at", "source", "comparison"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "comparison":   compute_benchmark_comparison(
            curve,
            benchmark_returns=None,
            benchmark_annual_pct=benchmark_annual_pct,
            periods_per_year=periods_per_year,
        ),
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            # Atomic-ish write: tmp file then replace (mirrors the orchestrator /
            # alerts modules' safe-write convention).
            tmp = out.with_suffix(out.suffix + ".tmp")
            tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
            tmp.replace(out)
            log.info(
                "benchmark comparison report written: %s (%d days, excess=%s%%, IR=%s)",
                out, report["comparison"]["count"],
                report["comparison"]["excess_total_return_pct"],
                report["comparison"]["information_ratio"],
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning(
                "could not write benchmark comparison report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compute benchmark-relative performance (excess return, "
                    "tracking error, information ratio, beta/correlation, "
                    "capture ratios) from paper-trading P&L history.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/benchmark_comparison.json)",
    )
    p.add_argument(
        "--benchmark-apy", type=float, default=DEFAULT_BENCHMARK_APY,
        help=f"flat benchmark annual rate %% (default: {DEFAULT_BENCHMARK_APY})",
    )
    p.add_argument(
        "--periods", type=int, default=DEFAULT_PERIODS_PER_YEAR,
        help=f"periods per year for annualisation (default: {DEFAULT_PERIODS_PER_YEAR})",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_benchmark_comparison_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
        benchmark_annual_pct=args.benchmark_apy,
        periods_per_year=args.periods,
    )
    print(json.dumps(report["comparison"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
