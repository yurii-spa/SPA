"""
Paper-trading risk-adjusted performance metrics (SPA-V380).

Read-only analytics layer that sits *on top of* the daily equity curve from
``equity_curve.py`` (SPA-V379). Where ``equity_curve`` answers "what did the
equity do day-to-day", this module answers "how good was that path on a
risk-adjusted basis" — the headline ratios a reporting layer / investor
digest wants next to the equity sparkline.

Design notes / safety:
  * Pure stdlib (json, math, statistics, datetime, pathlib, logging) — mirrors
    the no-external-dependency style of equity_curve.py and the execution
    adapters. No web3, no numpy/pandas.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    risk policy, wallets, or any money-moving code. It only reads
    pnl_history.json (via equity_curve.build_daily_equity_curve) and writes a
    derived report JSON.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen
    feed-health domain. It is pure portfolio-performance analytics.
  * Defensive: degenerate inputs (0 or 1 day, zero volatility, no losing days)
    never raise — ratios that are mathematically undefined return ``None`` and
    the schema stays stable.

Metrics (all derived from the daily-return series, one return per calendar
day after day 1):

    num_return_days        count of daily returns used (= num_days - 1)
    mean_daily_return_pct  arithmetic mean of daily returns
    daily_volatility_pct   population stdev of daily returns
    downside_deviation_pct population stdev of negative daily returns only
    annualized_return_pct  geometric, compounded over ANNUALIZATION_DAYS
    annualized_vol_pct     daily_vol * sqrt(ANNUALIZATION_DAYS)
    sharpe_ratio           annualized excess return / annualized vol
    sortino_ratio          annualized excess return / annualized downside dev
    calmar_ratio           annualized_return / abs(max_drawdown)
    win_rate_pct           positive_days / num_return_days * 100
    profit_factor          sum(gains) / abs(sum(losses))
    avg_win_pct            mean of positive daily returns
    avg_loss_pct           mean of negative daily returns (<= 0)
    win_loss_ratio         avg_win / abs(avg_loss)
    best_day / worst_day   {date, daily_return_pct}
    max_drawdown_pct       worst close-to-peak drawdown (<= 0)

Risk-free rate is configurable (annual %, default 0). Annualization assumes
``ANNUALIZATION_DAYS`` return periods per year (365 — DeFi positions accrue
every calendar day, unlike a 252-day equities convention).

CLI::

    python -m spa_core.paper_trading.risk_metrics
    python -m spa_core.paper_trading.risk_metrics --history data/pnl_history.json \\
        --out data/risk_metrics.json --risk-free 2.0
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

log = logging.getLogger("spa.paper_trading.risk_metrics")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "risk_metrics.json"

# DeFi positions accrue every calendar day → 365, not the 252 trading-day
# convention used for equities.
ANNUALIZATION_DAYS = 365


def _daily_returns(curve: list[dict]) -> list[float]:
    """Realised daily returns (%) — i.e. every bar after the seed day 1.

    Day 1's ``daily_return_pct`` is a 0.0 seed (no prior close), so it is
    excluded to avoid biasing the mean/vol toward zero.
    """
    return [bar["daily_return_pct"] for bar in curve[1:]]


def _safe_div(numerator: float, denominator: float) -> float | None:
    """Divide, returning None when the ratio is mathematically undefined."""
    if denominator == 0:
        return None
    return numerator / denominator


def compute_risk_metrics(
    curve: list[dict],
    risk_free_annual_pct: float = 0.0,
) -> dict:
    """Compute risk-adjusted performance metrics from a daily equity curve.

    Args:
        curve: list of daily bars as produced by
            ``equity_curve.build_daily_equity_curve``.
        risk_free_annual_pct: annual risk-free rate in percent (default 0).

    Returns:
        A stable-schema metrics dict. Ratios that are undefined for the given
        data (too few days, zero volatility, no losses, …) are ``None``.
    """
    base = {
        "num_return_days":        0,
        "mean_daily_return_pct":  0.0,
        "daily_volatility_pct":   0.0,
        "downside_deviation_pct": 0.0,
        "annualized_return_pct":  None,
        "annualized_vol_pct":     None,
        "sharpe_ratio":           None,
        "sortino_ratio":          None,
        "calmar_ratio":           None,
        "win_rate_pct":           None,
        "profit_factor":          None,
        "avg_win_pct":            None,
        "avg_loss_pct":           None,
        "win_loss_ratio":         None,
        "best_day":               None,
        "worst_day":              None,
        "max_drawdown_pct":       0.0,
        "risk_free_annual_pct":   round(float(risk_free_annual_pct), 4),
        "annualization_days":     ANNUALIZATION_DAYS,
    }

    returns = _daily_returns(curve)
    n = len(returns)
    if n == 0:
        return base

    mean_daily = statistics.fmean(returns)
    daily_vol = statistics.pstdev(returns) if n >= 1 else 0.0

    gains = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    # Downside deviation: stdev of negative returns about zero (not their mean),
    # the standard Sortino convention. Zero if there are no losing days.
    downside_dev = (
        math.sqrt(statistics.fmean([r * r for r in losses])) if losses else 0.0
    )

    # Geometric annualized return: compound the realised daily returns and
    # scale to a full year. Guard against a <= -100% cumulative (capital wipe).
    growth = 1.0
    for r in returns:
        growth *= (1.0 + r / 100.0)
    if growth <= 0:
        annualized_return_pct = -100.0
    else:
        annualized_return_pct = (growth ** (ANNUALIZATION_DAYS / n) - 1.0) * 100.0

    annualized_vol_pct = daily_vol * math.sqrt(ANNUALIZATION_DAYS)
    excess_annual = annualized_return_pct - float(risk_free_annual_pct)
    annualized_downside_pct = downside_dev * math.sqrt(ANNUALIZATION_DAYS)

    sharpe = _safe_div(excess_annual, annualized_vol_pct)
    sortino = _safe_div(excess_annual, annualized_downside_pct)

    max_dd = min((bar["drawdown_pct"] for bar in curve), default=0.0)
    calmar = _safe_div(annualized_return_pct, abs(max_dd))

    win_rate_pct = len(gains) / n * 100.0
    sum_gains = sum(gains)
    sum_losses = sum(losses)  # <= 0
    profit_factor = _safe_div(sum_gains, abs(sum_losses))
    avg_win = statistics.fmean(gains) if gains else None
    avg_loss = statistics.fmean(losses) if losses else None
    win_loss_ratio = (
        _safe_div(avg_win, abs(avg_loss))
        if (avg_win is not None and avg_loss is not None)
        else None
    )

    best = max(curve[1:], key=lambda b: b["daily_return_pct"], default=None)
    worst = min(curve[1:], key=lambda b: b["daily_return_pct"], default=None)

    def _rnd(x: float | None, places: int = 4) -> float | None:
        return None if x is None else round(x, places)

    return {
        "num_return_days":        n,
        "mean_daily_return_pct":  round(mean_daily, 4),
        "daily_volatility_pct":   round(daily_vol, 4),
        "downside_deviation_pct": round(downside_dev, 4),
        "annualized_return_pct":  round(annualized_return_pct, 4),
        "annualized_vol_pct":     round(annualized_vol_pct, 4),
        "sharpe_ratio":           _rnd(sharpe),
        "sortino_ratio":          _rnd(sortino),
        "calmar_ratio":           _rnd(calmar),
        "win_rate_pct":           round(win_rate_pct, 4),
        "profit_factor":          _rnd(profit_factor),
        "avg_win_pct":            _rnd(avg_win),
        "avg_loss_pct":           _rnd(avg_loss),
        "win_loss_ratio":         _rnd(win_loss_ratio),
        "best_day":               None if best is None else {
            "date": best["date"], "daily_return_pct": best["daily_return_pct"]},
        "worst_day":              None if worst is None else {
            "date": worst["date"], "daily_return_pct": worst["daily_return_pct"]},
        "max_drawdown_pct":       round(max_dd, 4),
        "risk_free_annual_pct":   round(float(risk_free_annual_pct), 4),
        "annualization_days":     ANNUALIZATION_DAYS,
    }


def generate_risk_metrics_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    risk_free_annual_pct: float = 0.0,
) -> dict:
    """Build the full risk-metrics report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        output_path: where to write the report JSON. Pass ``None`` to skip
            writing (compute-only).
        risk_free_annual_pct: annual risk-free rate in percent.

    Returns:
        ``{"generated_at", "source", "metrics"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "metrics":      compute_risk_metrics(curve, risk_free_annual_pct),
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2), encoding="utf-8")
            log.info(
                "risk metrics report written: %s (sharpe=%s, %d days)",
                out, report["metrics"]["sharpe_ratio"],
                report["metrics"]["num_return_days"],
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning("could not write risk metrics report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compute risk-adjusted metrics from paper-trading P&L history.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/risk_metrics.json)",
    )
    p.add_argument(
        "--risk-free", type=float, default=0.0,
        help="annual risk-free rate in percent (default: 0.0)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_risk_metrics_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
        risk_free_annual_pct=args.risk_free,
    )
    print(json.dumps(report["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
