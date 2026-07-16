"""
Paper-trading advanced risk-adjusted ratios (SPA-V397).

Read-only analytics layer that sits *on top of* the daily equity curve from
``equity_curve.py`` (SPA-V379). Where ``risk_metrics.py`` (SPA-V380) covers the
headline Sharpe / Sortino / Calmar / profit-factor battery, this module adds the
second tier of professional tearsheet ratios that those three do not cover —
the ones an investor digest reaches for when the path is volatile or fat-tailed:

    omega_ratio            E[max(r-MAR,0)] / E[max(MAR-r,0)]  (whole-distribution
                           upside/downside ratio about a threshold MAR)
    gain_to_pain_ratio     sum(returns) / abs(sum(negative returns))  (Schwager)
    tail_ratio             abs(p95) / abs(p5) of the daily-return distribution
    common_sense_ratio     tail_ratio * profit_factor  (right-tail-aware PF)
    ulcer_index            sqrt(mean(drawdown_pct^2))  — depth *and* duration of
                           drawdowns (RMS of the underwater curve)
    martin_ratio           annualized_return / ulcer_index  (Ulcer Performance
                           Index / UPI)
    pain_index             mean(abs(drawdown_pct))  — average underwater depth
    pain_ratio             annualized_return / pain_index

Design notes / safety:
  * Pure stdlib (json, math, statistics, datetime, pathlib, logging, argparse) —
    mirrors the no-external-dependency style of risk_metrics.py / equity_curve.py.
    No web3, no numpy/pandas/scipy, no network.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    risk policy, wallets, or any money-moving code. It only reads
    pnl_history.json (via equity_curve.build_daily_equity_curve) and writes a
    derived report JSON.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen
    feed-health domain. Pure portfolio-performance analytics.
  * The underwater curve used for Ulcer / pain metrics is reconstructed
    *internally* from the realised daily-return series (start 1.0, running peak),
    so the module does not depend on the ``drawdown_pct`` field being populated
    upstream and is self-consistent for any return series.
  * Defensive: degenerate inputs (0 or 1 day, no losses, flat series) never
    raise — ratios that are mathematically undefined return ``None`` and the
    schema stays stable.

Annualization assumes ``ANNUALIZATION_DAYS`` return periods per year (365 — DeFi
positions accrue every calendar day, unlike the 252-day equities convention).

CLI::

    python -m spa_core.analytics_lab.advanced_ratios
    python -m spa_core.analytics_lab.advanced_ratios --history data/pnl_history.json \\
        --out data/advanced_ratios.json --mar 4.0
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
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.analytics_lab.advanced_ratios")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "advanced_ratios.json"

# DeFi positions accrue every calendar day → 365, not the 252 trading-day
# convention used for equities.
ANNUALIZATION_DAYS = 365

# Percentiles used for the tail ratio (right tail / left tail).
TAIL_UPPER_PCT = 95.0
TAIL_LOWER_PCT = 5.0


def _daily_returns(curve: list[dict]) -> list[float]:
    """Realised daily returns (%) — every bar after the seed day 1.

    Day 1's ``daily_return_pct`` is a 0.0 seed (no prior close), so it is
    excluded to avoid biasing the metrics toward zero.
    """
    return [bar["daily_return_pct"] for bar in curve[1:]]


def _safe_div(numerator: float, denominator: float) -> float | None:
    """Divide, returning None when the ratio is mathematically undefined."""
    if denominator == 0:
        return None
    return numerator / denominator


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    """Linear-interpolation percentile (same convention as return_distribution).

    ``sorted_values`` must be sorted ascending. ``pct`` in [0, 100].
    """
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_values[int(rank)]
    frac = rank - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _annualized_return_pct(returns: list[float]) -> float | None:
    """Geometric annualized return from a realised daily-return series (%)."""
    n = len(returns)
    if n == 0:
        return None
    growth = 1.0
    for r in returns:
        growth *= (1.0 + r / 100.0)
    if growth <= 0:
        return -100.0
    return (growth ** (ANNUALIZATION_DAYS / n) - 1.0) * 100.0


def _underwater_curve(returns: list[float]) -> list[float]:
    """Reconstruct the drawdown series (%, <= 0) from a daily-return series.

    Starts equity at 1.0, compounds each daily return, tracks the running peak
    and reports ``(equity / peak - 1) * 100`` at each step. Self-contained so
    Ulcer / pain metrics do not depend on an upstream ``drawdown_pct`` field.
    """
    equity = 1.0
    peak = 1.0
    underwater: list[float] = []
    for r in returns:
        equity *= (1.0 + r / 100.0)
        if equity > peak:
            peak = equity
        underwater.append((equity / peak - 1.0) * 100.0 if peak > 0 else 0.0)
    return underwater


def compute_advanced_ratios(
    curve: list[dict],
    mar_annual_pct: float = 0.0,
) -> dict:
    """Compute advanced risk-adjusted ratios from a daily equity curve.

    Args:
        curve: list of daily bars as produced by
            ``equity_curve.build_daily_equity_curve``.
        mar_annual_pct: Minimum Acceptable Return (annual %, default 0). Used as
            the Omega-ratio threshold; converted to a daily MAR via the same
            365-day compounding convention used elsewhere.

    Returns:
        A stable-schema metrics dict. Ratios that are undefined for the given
        data (too few days, no losses, zero tail, …) are ``None``.
    """
    # Daily MAR consistent with the annualization convention.
    mar_daily_pct = ((1.0 + mar_annual_pct / 100.0) ** (1.0 / ANNUALIZATION_DAYS) - 1.0) * 100.0

    base = {
        "num_return_days":     0,
        "mar_annual_pct":      round(float(mar_annual_pct), 4),
        "mar_daily_pct":       round(mar_daily_pct, 6),
        "omega_ratio":         None,
        "gain_to_pain_ratio":  None,
        "tail_ratio":          None,
        "common_sense_ratio":  None,
        "profit_factor":       None,
        "ulcer_index":         None,
        "martin_ratio":        None,
        "pain_index":          None,
        "pain_ratio":          None,
        "max_drawdown_pct":    0.0,
        "annualized_return_pct": None,
        "tail_upper_pct":      TAIL_UPPER_PCT,
        "tail_lower_pct":      TAIL_LOWER_PCT,
        "annualization_days":  ANNUALIZATION_DAYS,
    }

    returns = _daily_returns(curve)
    n = len(returns)
    if n == 0:
        return base

    # ── Omega ratio about the daily MAR ────────────────────────────────────
    # Omega(θ) = sum(max(r-θ, 0)) / sum(max(θ-r, 0)).
    upside = sum(max(r - mar_daily_pct, 0.0) for r in returns)
    downside = sum(max(mar_daily_pct - r, 0.0) for r in returns)
    omega = _safe_div(upside, downside)

    # ── Gain-to-pain (Schwager): sum(returns) / abs(sum(losses)) ───────────
    losses = [r for r in returns if r < 0]
    gains = [r for r in returns if r > 0]
    sum_returns = sum(returns)
    sum_losses = sum(losses)  # <= 0
    sum_gains = sum(gains)
    gain_to_pain = _safe_div(sum_returns, abs(sum_losses))
    profit_factor = _safe_div(sum_gains, abs(sum_losses))

    # ── Tail ratio: |p95| / |p5| ───────────────────────────────────────────
    ordered = sorted(returns)
    p_hi = _percentile(ordered, TAIL_UPPER_PCT)
    p_lo = _percentile(ordered, TAIL_LOWER_PCT)
    tail_ratio = (
        _safe_div(abs(p_hi), abs(p_lo))
        if (p_hi is not None and p_lo is not None)
        else None
    )

    # ── Common-sense ratio: tail_ratio * profit_factor ─────────────────────
    common_sense = (
        tail_ratio * profit_factor
        if (tail_ratio is not None and profit_factor is not None)
        else None
    )

    # ── Ulcer / pain from the reconstructed underwater curve ───────────────
    underwater = _underwater_curve(returns)
    ulcer_index = math.sqrt(statistics.fmean([d * d for d in underwater])) if underwater else 0.0
    pain_index = statistics.fmean([abs(d) for d in underwater]) if underwater else 0.0
    max_dd = min(underwater) if underwater else 0.0

    annualized_return_pct = _annualized_return_pct(returns)
    martin = (
        _safe_div(annualized_return_pct, ulcer_index)
        if annualized_return_pct is not None
        else None
    )
    pain_ratio = (
        _safe_div(annualized_return_pct, pain_index)
        if annualized_return_pct is not None
        else None
    )

    def _rnd(x: float | None, places: int = 4) -> float | None:
        return None if x is None else round(x, places)

    return {
        "num_return_days":       n,
        "mar_annual_pct":        round(float(mar_annual_pct), 4),
        "mar_daily_pct":         round(mar_daily_pct, 6),
        "omega_ratio":           _rnd(omega),
        "gain_to_pain_ratio":    _rnd(gain_to_pain),
        "tail_ratio":            _rnd(tail_ratio),
        "common_sense_ratio":    _rnd(common_sense),
        "profit_factor":         _rnd(profit_factor),
        "ulcer_index":           round(ulcer_index, 4),
        "martin_ratio":          _rnd(martin),
        "pain_index":            round(pain_index, 4),
        "pain_ratio":            _rnd(pain_ratio),
        "max_drawdown_pct":      round(max_dd, 4),
        "annualized_return_pct": _rnd(annualized_return_pct),
        "tail_upper_pct":        TAIL_UPPER_PCT,
        "tail_lower_pct":        TAIL_LOWER_PCT,
        "annualization_days":    ANNUALIZATION_DAYS,
    }


def generate_advanced_ratios_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    mar_annual_pct: float = 0.0,
) -> dict:
    """Build the full advanced-ratios report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        output_path: where to write the report JSON. Pass ``None`` to skip
            writing (compute-only).
        mar_annual_pct: Minimum Acceptable Return (annual %) for the Omega ratio.

    Returns:
        ``{"generated_at", "source", "metrics"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "metrics":      compute_advanced_ratios(curve, mar_annual_pct),
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            # Atomic write via the canonical atomic_save (P3-9). Byte-identical
            # (indent=2; atomic_save adds default=str for serializable payloads).
            atomic_save(report, str(out))
            log.info(
                "advanced ratios report written: %s (omega=%s, ulcer=%s, %d days)",
                out, report["metrics"]["omega_ratio"],
                report["metrics"]["ulcer_index"],
                report["metrics"]["num_return_days"],
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning("could not write advanced ratios report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compute advanced risk-adjusted ratios from paper-trading P&L history.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/advanced_ratios.json)",
    )
    p.add_argument(
        "--mar", type=float, default=0.0,
        help="Minimum Acceptable Return, annual %% — Omega threshold (default: 0.0)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_advanced_ratios_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
        mar_annual_pct=args.mar,
    )
    print(json.dumps(report["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
