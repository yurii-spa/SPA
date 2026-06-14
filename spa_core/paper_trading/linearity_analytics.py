"""
Paper-trading equity-curve linearity / K-ratio analytics (SPA-V402).

Read-only analytics layer that sits *on top of* the daily equity curve from
``equity_curve.py`` (SPA-V379). The whole prior suite (V380-V401) describes the
distribution, risk, drawdown and time-ordering of the *return* series — but none
of them asks the single question a discretionary allocator eyeballs first when
they look at a track record: **how straight and steady is the equity curve?**

A curve that grinds upward in a near-straight log line (high, statistically
significant drift with small wobble) is far more trustworthy than one with the
same end-point reached through a violent boom-and-bust. This module quantifies
exactly that "straightness" by regressing the **cumulative log-equity against
time** and reporting how strong, significant and clean that linear trend is:

    log_slope_per_day      OLS slope of ln(equity) vs the day index — the steady
                           per-day log drift (compounding rate) of the book.
    r_squared              goodness of the linear fit (0..1): how close the
                           log-equity path hugs a straight line.
    slope_std_err          standard error of the slope estimate.
    t_stat_slope           slope / std_err — statistical significance of the
                           trend (is the drift distinguishable from noise?).
    k_ratio                Kestner K-ratio = t_stat_slope / sqrt(num_points):
                           consistency-of-return measure combining the strength
                           of the trend with the number of observations.
    rmse_log               RMS of the regression residuals (log units) — typical
                           deviation of the path from its own trend line.
    max_abs_residual_log   worst single deviation from the trend line.
    annualized_log_drift_pct   (exp(slope * 365) - 1) * 100 — the steady drift
                           expressed as an annual %.
    linearity_grade        A/B/C/D label from r_squared.
    trend_direction        up / down / flat from the slope sign.

Design notes / safety:
  * Pure stdlib (json, math, statistics, datetime, pathlib, logging, argparse) —
    mirrors the no-external-dependency style of advanced_ratios.py /
    risk_metrics.py / equity_curve.py. No web3, numpy/pandas/scipy, no network.
    The ordinary-least-squares fit and its slope standard error are implemented
    from scratch.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    risk policy, wallets, or any money-moving code. It only reads
    pnl_history.json (via equity_curve.build_daily_equity_curve) and writes a
    derived report JSON.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen feed-health
    domain. Pure portfolio-performance analytics.
  * Regression is run on ln(close_equity) using ALL equity points (the seed day
    included — every point is a real mark of the book's value, unlike the
    return series where day 1 is a synthetic 0.0 seed).
  * Defensive: degenerate inputs (0 or 1 point, flat curve, non-positive equity,
    fewer than 3 points so the slope standard error is undefined) never raise —
    undefined statistics return ``None`` and the schema stays stable.

The K-ratio normalization follows Kestner's 2013 revision (divide the slope
t-statistic by sqrt(n)); the original 1996 formulation divided by n. We expose
the raw ``t_stat_slope`` alongside so either convention can be recovered.

CLI::

    python -m spa_core.paper_trading.linearity_analytics
    python -m spa_core.paper_trading.linearity_analytics --history data/pnl_history.json \\
        --out data/linearity_analytics.json
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from spa_core.paper_trading.equity_curve import (
    DEFAULT_HISTORY_PATH,
    build_daily_equity_curve,
    load_pnl_history,
)

log = logging.getLogger("spa.paper_trading.linearity_analytics")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "linearity_analytics.json"

# DeFi positions accrue every calendar day → 365, not the 252 trading-day
# convention used for equities.
ANNUALIZATION_DAYS = 365

# Slope magnitudes (per-day log drift) below this count as "flat" for the
# trend_direction label. 1e-6 ≈ 0.0365%/yr — well inside noise.
_FLAT_SLOPE_EPS = 1e-6

# r_squared thresholds for the linearity grade (how straight is the log path).
_GRADE_A = 0.95
_GRADE_B = 0.80
_GRADE_C = 0.50


def _equity_series(curve: list[dict]) -> list[float]:
    """Close-equity for every bar in the curve (seed day included)."""
    return [bar["close_equity"] for bar in curve]


def _ols_fit(xs: list[float], ys: list[float]) -> dict:
    """Ordinary-least-squares fit of ys ~ xs, computed from scratch.

    Returns a dict with slope, intercept, r_squared, slope_std_err, t_stat,
    residual RMS and max-abs residual. Statistics that are undefined for the
    given data (fewer than 2 points, zero variance in x, fewer than 3 points
    for the slope standard error) are ``None``. Never raises.
    """
    base = {
        "slope": None,
        "intercept": None,
        "r_squared": None,
        "slope_std_err": None,
        "t_stat": None,
        "rmse": None,
        "max_abs_residual": None,
    }
    n = len(xs)
    if n < 2 or n != len(ys):
        return base

    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    sxx = sum((x - x_mean) ** 2 for x in xs)
    syy = sum((y - y_mean) ** 2 for y in ys)
    sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))

    if sxx == 0:  # all x identical — slope undefined
        return base

    slope = sxy / sxx
    intercept = y_mean - slope * x_mean

    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    sse = sum(r * r for r in residuals)
    rmse = math.sqrt(sse / n)
    max_abs_residual = max(abs(r) for r in residuals)

    # r_squared = 1 - SSE/SST; flat target (syy == 0) → perfectly explained iff
    # the fit is also flat, which it is when syy == 0 (slope 0). Report 1.0.
    r_squared = 1.0 if syy == 0 else max(0.0, min(1.0, 1.0 - sse / syy))

    # Slope standard error needs n-2 residual degrees of freedom.
    slope_std_err = None
    t_stat = None
    if n >= 3:
        resid_var = sse / (n - 2)
        slope_std_err = math.sqrt(resid_var / sxx) if sxx > 0 else None
        if slope_std_err is not None and slope_std_err > 0:
            t_stat = slope / slope_std_err
        elif slope_std_err == 0:
            # Perfect fit (zero residual variance) → infinitely significant; we
            # report None rather than inf to keep the JSON finite-and-clean.
            t_stat = None

    return {
        "slope": slope,
        "intercept": intercept,
        "r_squared": r_squared,
        "slope_std_err": slope_std_err,
        "t_stat": t_stat,
        "rmse": rmse,
        "max_abs_residual": max_abs_residual,
    }


def _linearity_grade(r_squared: float | None) -> str | None:
    if r_squared is None:
        return None
    if r_squared >= _GRADE_A:
        return "A"
    if r_squared >= _GRADE_B:
        return "B"
    if r_squared >= _GRADE_C:
        return "C"
    return "D"


def _trend_direction(slope: float | None) -> str | None:
    if slope is None:
        return None
    if slope > _FLAT_SLOPE_EPS:
        return "up"
    if slope < -_FLAT_SLOPE_EPS:
        return "down"
    return "flat"


def compute_linearity(curve: list[dict]) -> dict:
    """Compute equity-curve linearity / K-ratio statistics from a daily curve.

    Args:
        curve: list of daily bars as produced by
            ``equity_curve.build_daily_equity_curve``.

    Returns:
        A stable-schema metrics dict. Statistics that are undefined for the
        given data (too few points, flat curve, non-positive equity) are
        ``None``.
    """
    base = {
        "num_points":               0,
        "log_slope_per_day":        None,
        "intercept_log":            None,
        "r_squared":                None,
        "slope_std_err":            None,
        "t_stat_slope":             None,
        "k_ratio":                  None,
        "rmse_log":                 None,
        "max_abs_residual_log":     None,
        "annualized_log_drift_pct": None,
        "linearity_grade":          None,
        "trend_direction":          None,
        "annualization_days":       ANNUALIZATION_DAYS,
        "execution_mode":           "read_only_simulation",
    }

    equities = _equity_series(curve)
    # Need strictly-positive equity to take logs; guard defensively.
    if len(equities) < 2 or any(e <= 0 for e in equities):
        base["num_points"] = len(equities)
        return base

    n = len(equities)
    xs = [float(i) for i in range(n)]            # day index 0..n-1
    ys = [math.log(e) for e in equities]          # cumulative log-equity

    fit = _ols_fit(xs, ys)
    slope = fit["slope"]

    k_ratio = None
    if fit["t_stat"] is not None and n > 0:
        k_ratio = fit["t_stat"] / math.sqrt(n)

    annualized_log_drift_pct = None
    if slope is not None:
        # Steady per-day log drift → annual % via continuous compounding.
        annualized_log_drift_pct = (math.exp(slope * ANNUALIZATION_DAYS) - 1.0) * 100.0

    def _rnd(x, places=8):
        return None if x is None else round(x, places)

    return {
        "num_points":               n,
        "log_slope_per_day":        _rnd(slope),
        "intercept_log":            _rnd(fit["intercept"]),
        "r_squared":                _rnd(fit["r_squared"], 6),
        "slope_std_err":            _rnd(fit["slope_std_err"]),
        "t_stat_slope":             _rnd(fit["t_stat"], 6),
        "k_ratio":                  _rnd(k_ratio, 6),
        "rmse_log":                 _rnd(fit["rmse"]),
        "max_abs_residual_log":     _rnd(fit["max_abs_residual"]),
        "annualized_log_drift_pct": _rnd(annualized_log_drift_pct, 4),
        "linearity_grade":          _linearity_grade(fit["r_squared"]),
        "trend_direction":          _trend_direction(slope),
        "annualization_days":       ANNUALIZATION_DAYS,
        "execution_mode":           "read_only_simulation",
    }


def generate_linearity_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
) -> dict:
    """Build the full linearity report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        output_path: where to write the report JSON. Pass ``None`` to skip
            writing (compute-only).

    Returns:
        ``{"generated_at", "source", "metrics"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "metrics":      compute_linearity(curve),
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write: tmp in the same dir + os.replace (mirrors siblings).
            tmp = out.with_name(f".linearity_analytics_{os.getpid()}.tmp")
            tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
            os.replace(tmp, out)
            log.info(
                "linearity report written: %s (r2=%s, k_ratio=%s, %d pts)",
                out, report["metrics"]["r_squared"],
                report["metrics"]["k_ratio"],
                report["metrics"]["num_points"],
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning("could not write linearity report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compute equity-curve linearity / K-ratio analytics from paper-trading P&L history.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/linearity_analytics.json)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_linearity_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
    )
    print(json.dumps(report["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
