"""
Paper-trading Conditional Drawdown-at-Risk (CDaR) analytics (SPA-V401).

Read-only analytics layer that sits *on top of* the daily equity curve from
``equity_curve.py`` (SPA-V379). It adds the one drawdown view the V380–V400
suite does not yet provide: a **tail-quantile description of the drawdown
distribution itself**.

How this differs from the existing siblings (no overlap):
  * ``return_distribution`` (V383) reports VaR / CVaR on the *daily-return*
    distribution — the tail of period-to-period P&L, not of the drawdown path.
  * ``drawdown_analysis`` enumerates discrete peak→trough→recovery *episodes*
    (when, how deep, how long underwater) — an event list, not a risk quantile.
  * ``advanced_ratios`` (V397) reduces the underwater curve to two scalars,
    the Ulcer Index (RMS of drawdown) and the pain index (mean drawdown).

This module instead treats the daily *underwater series* (drawdown depth at
each day) as a distribution and measures its tail, exactly analogous to how
return_distribution treats the return series:

    DaR(alpha)   Drawdown-at-Risk — the alpha-quantile of daily drawdown depth.
                 "On all but (1-alpha) of days the portfolio sat no deeper than
                 this below its running peak."
    CDaR(alpha)  Conditional Drawdown-at-Risk — the mean drawdown depth on the
                 worst (1-alpha) tail of days (depths >= DaR(alpha)). A coherent,
                 conservative cousin of max drawdown: it averages the deep days
                 rather than reporting the single worst point (Chekhlov, Uryasev
                 & Zabarankin, 2005).
    RoCDaR       annualized_return / CDaR(alpha) — a risk-adjusted ratio in the
                 Calmar family, but penalising the *typical deep drawdown* rather
                 than the lone worst trough.

All depths are reported as **non-negative magnitudes** (percent below peak), so
larger numbers mean a worse drawdown. ``max_drawdown_pct`` is the worst single
day; ``average_drawdown_pct`` is the mean over every day.

Method:
    The underwater series is reconstructed *self-containedly* from
    ``close_equity`` levels (running peak → depth), so the module does not depend
    on an upstream ``drawdown_pct`` field being populated — mirroring the
    robustness convention in advanced_ratios._underwater_curve.

Design notes / safety:
  * Pure stdlib (json, math, os, statistics, datetime, pathlib, logging,
    argparse) — mirrors regime_segmentation.py / advanced_ratios.py. No web3, no
    numpy/pandas/scipy, no network.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    risk policy, wallets, monitoring, or any money-moving code. It only reads
    pnl_history.json (via equity_curve.build_daily_equity_curve) and writes a
    derived report JSON.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen feed-health
    domain. Pure portfolio-performance analytics.
  * Defensive: degenerate inputs (0/1 day, flat/zero-variance series, a series
    that never draws down) never raise. Statistics that are undefined return
    ``None`` and the schema stays stable. The compute function NEVER raises on
    bad data — callers always get a dict.

CLI::

    python -m spa_core.analytics_lab.conditional_drawdown
    python -m spa_core.analytics_lab.conditional_drawdown --history data/pnl_history.json \\
        --out data/conditional_drawdown.json --confidences 0.90 0.95 0.99
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

log = logging.getLogger("spa.analytics_lab.conditional_drawdown")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "conditional_drawdown.json"

# Annualization convention shared with advanced_ratios (365 — DeFi runs 24/7).
ANNUALIZATION_DAYS = 365

# Confidence levels at which DaR / CDaR / RoCDaR are reported.
DEFAULT_CONFIDENCES = (0.90, 0.95, 0.99)

# Quantiles (percentiles) of the drawdown-depth distribution reported for context.
_QUANTILE_PCTS = (50.0, 90.0, 95.0, 99.0)

# Depths below this magnitude (%) are treated as "not underwater" (float noise).
_UNDERWATER_EPS = 1e-9


def _daily_returns(curve: list[dict]) -> list[float]:
    """Realised daily returns (%) — every bar after the seed day 1.

    Day 1's ``daily_return_pct`` is a 0.0 seed (no prior close), so it is
    excluded to avoid biasing the annualized-return figure toward zero. Mirrors
    the sibling modules.
    """
    return [bar["daily_return_pct"] for bar in curve[1:]]


def _underwater_magnitudes(curve: list[dict]) -> list[float]:
    """Drawdown depth (%, >= 0) per day, reconstructed from ``close_equity``.

    Walks the close-equity levels tracking the running peak and reports
    ``(peak - close) / peak * 100`` (a non-negative magnitude) at each day.
    Self-contained so the tail metrics do not depend on an upstream
    ``drawdown_pct`` field. A non-positive peak yields a 0.0 depth (guard).
    """
    depths: list[float] = []
    peak: float | None = None
    for bar in curve:
        close = float(bar["close_equity"])
        if peak is None or close > peak:
            peak = close
        if peak is None or peak <= 0.0:
            depths.append(0.0)
        else:
            depths.append(max(0.0, (peak - close) / peak * 100.0))
    return depths


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


def _clean_confidences(confidences) -> list[float]:
    """Validate, dedupe and sort confidence levels into (0, 1).

    Invalid / out-of-range entries are dropped. Falls back to the defaults when
    nothing valid remains, so the schema (one ``levels`` entry per confidence)
    stays predictable. Never raises.
    """
    out: list[float] = []
    seen: set[float] = set()
    try:
        iterable = list(confidences)
    except TypeError:
        iterable = []
    for c in iterable:
        try:
            cf = float(c)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(cf) or cf <= 0.0 or cf >= 1.0:
            continue
        key = round(cf, 6)
        if key in seen:
            continue
        seen.add(key)
        out.append(cf)
    if not out:
        out = list(DEFAULT_CONFIDENCES)
    return sorted(out)


def _cdar_level(
    sorted_depths: list[float],
    confidence: float,
    annualized_return_pct: float | None,
) -> dict:
    """DaR / CDaR / RoCDaR for one confidence level.

    ``sorted_depths`` must be the underwater magnitudes sorted ascending. DaR is
    the ``confidence``-quantile; CDaR is the mean of all depths at or above DaR
    (the conditional mean of the worst (1-confidence) tail). RoCDaR divides the
    annualized return by CDaR when CDaR is strictly positive.
    """
    n = len(sorted_depths)
    if n == 0:
        return {
            "confidence": round(confidence, 6),
            "dar_pct":    None,
            "cdar_pct":   None,
            "tail_days":  0,
            "rocdar":     None,
        }

    dar = _percentile(sorted_depths, confidence * 100.0)
    if dar is None:
        dar = 0.0
    tail = [d for d in sorted_depths if d >= dar - _UNDERWATER_EPS]
    if not tail:  # numeric edge — fall back to the single worst depth
        tail = [sorted_depths[-1]]
    cdar = statistics.fmean(tail)
    rocdar = (
        _safe_div(annualized_return_pct, cdar)
        if (annualized_return_pct is not None and cdar > _UNDERWATER_EPS)
        else None
    )
    return {
        "confidence": round(confidence, 6),
        "dar_pct":    round(dar, 6),
        "cdar_pct":   round(cdar, 6),
        "tail_days":  len(tail),
        "rocdar":     round(rocdar, 6) if rocdar is not None else None,
    }


def compute_conditional_drawdown(
    curve: list[dict],
    confidences=DEFAULT_CONFIDENCES,
) -> dict:
    """Compute Drawdown-at-Risk / Conditional Drawdown-at-Risk from a curve.

    Args:
        curve: list of daily bars as produced by
            ``equity_curve.build_daily_equity_curve``.
        confidences: iterable of confidence levels in the open interval (0, 1).
            Invalid entries are dropped; an empty result falls back to
            ``DEFAULT_CONFIDENCES``.

    Returns:
        A stable-schema dict. Undefined statistics are ``None``. Never raises.
    """
    levels_in = _clean_confidences(confidences)
    depths = _underwater_magnitudes(curve)
    n = len(depths)

    base = {
        "execution_mode":       "read_only_simulation",
        "annualization_days":   ANNUALIZATION_DAYS,
        "num_days":             n,
        "first_date":           curve[0]["date"] if n else None,
        "last_date":            curve[-1]["date"] if n else None,
        "max_drawdown_pct":     0.0,
        "average_drawdown_pct": 0.0,
        "pct_time_underwater":  0.0,
        "annualized_return_pct": None,
        "drawdown_quantiles":   {f"p{int(p)}": None for p in _QUANTILE_PCTS},
        "confidences":          [round(c, 6) for c in levels_in],
        "levels":               [
            _cdar_level([], c, None) for c in levels_in
        ],
    }
    if n == 0:
        return base

    sorted_depths = sorted(depths)
    annualized = _annualized_return_pct(_daily_returns(curve))
    underwater_days = sum(1 for d in depths if d > _UNDERWATER_EPS)

    base["max_drawdown_pct"] = round(max(depths), 6)
    base["average_drawdown_pct"] = round(statistics.fmean(depths), 6)
    base["pct_time_underwater"] = round(underwater_days / n * 100.0, 6)
    base["annualized_return_pct"] = (
        round(annualized, 6) if annualized is not None else None
    )
    base["drawdown_quantiles"] = {
        f"p{int(p)}": round(_percentile(sorted_depths, p), 6)
        for p in _QUANTILE_PCTS
    }
    base["levels"] = [
        _cdar_level(sorted_depths, c, annualized) for c in levels_in
    ]
    return base


def generate_conditional_drawdown_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    confidences=DEFAULT_CONFIDENCES,
) -> dict:
    """Build the full CDaR report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        output_path: where to write the report JSON. Pass ``None`` to skip
            writing (compute-only).
        confidences: confidence levels for DaR / CDaR / RoCDaR.

    Returns:
        ``{"generated_at", "source", "conditional_drawdown"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "conditional_drawdown": compute_conditional_drawdown(curve, confidences),
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            # Atomic write via the canonical atomic_save (P3-9). Byte-identical
            # (indent=2; atomic_save adds default=str for serializable payloads).
            atomic_save(report, str(out))
            cd = report["conditional_drawdown"]
            log.info(
                "conditional drawdown report written: %s (%d days, max_dd=%s, levels=%d)",
                out, cd["num_days"], cd["max_drawdown_pct"], len(cd["levels"]),
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning(
                "could not write conditional drawdown report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compute Drawdown-at-Risk (DaR) and Conditional "
                    "Drawdown-at-Risk (CDaR) tail metrics from the paper-trading "
                    "daily equity curve. Read-only drawdown-distribution analytics.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/conditional_drawdown.json)",
    )
    p.add_argument(
        "--confidences", type=float, nargs="+", default=list(DEFAULT_CONFIDENCES),
        metavar="ALPHA",
        help="confidence levels in (0,1) for DaR/CDaR "
             f"(default: {' '.join(str(c) for c in DEFAULT_CONFIDENCES)})",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_conditional_drawdown_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
        confidences=args.confidences,
    )
    print(json.dumps(report["conditional_drawdown"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
