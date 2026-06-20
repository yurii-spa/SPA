#!/usr/bin/env python3
"""Hedge-fund-style tear sheet (MP-1236) → ``data/tear_sheet.json``.

A compact, machine-readable institutional tear sheet over the SPA paper track.
Distinct from the existing public monthly :mod:`spa_core.reporting.tear_sheet`
(which produces ``tear_sheet_latest.json`` + per-month markdown and is imported
elsewhere): this module is the enhanced metrics block requested in MP-1236 and
writes a *different* file, so both coexist.

Risk-adjusted core metrics are reused by import from
``risk_metrics.compute_risk_metrics`` (risk-free 4.5% annual). This module adds:
average drawdown duration, 30-day rolling Sharpe, a monthly return table, and an
explicit best/worst-day block.

Pure stdlib, offline, READ-ONLY, exit 0 always (no tracebacks). LLM FORBIDDEN.

CLI::

    python3 -m spa_core.reporting.tear_sheet_hf --check   # default, no write
    python3 -m spa_core.reporting.tear_sheet_hf --run     # atomic write
    python3 -m spa_core.reporting.tear_sheet_hf --run --data-dir DIR
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.reporting._perf_common import (
    ANNUALIZATION_DAYS,
    DISCLAIMER,
    RISK_FREE_ANNUAL_PCT,
    annualize_return_pct,
    atomic_write_json,
    compound_return_pct,
    compute_risk_metrics,
    content_fingerprint,
    daily_returns_pct,
    load_equity_curve,
    now_iso,
    read_json,
    real_track_bars,
    rebuild_curve,
    rnd,
)

ROLLING_WINDOW = 30  # 30-day rolling Sharpe window


def _rolling_sharpe(returns: List[float], window: int = ROLLING_WINDOW) -> Dict[str, Any]:
    """30-day rolling annualised Sharpe (risk-free 4.5%). Honest about short tracks."""
    rf_daily = RISK_FREE_ANNUAL_PCT / ANNUALIZATION_DAYS  # % per day
    series: List[dict] = []
    n = len(returns)
    if n >= window:
        for end in range(window, n + 1):
            w = returns[end - window:end]
            mean = statistics.fmean(w)
            vol = statistics.pstdev(w)
            sharpe = None if vol == 0 else (mean - rf_daily) / vol * math.sqrt(ANNUALIZATION_DAYS)
            series.append({"window_end_index": end - 1, "sharpe": rnd(sharpe)})
    note = (
        f"{len(series)} rolling windows of {window} days."
        if series else
        f"Track has {n} return days (< {window}); rolling-Sharpe series empty. "
        f"See risk_metrics.sharpe_ratio for the full-period figure."
    )
    return {"window_days": window, "series": series, "note": note}


def _drawdown_episodes(curve: List[dict]) -> Dict[str, Any]:
    """Underwater episodes from the rebuilt curve's ``drawdown_pct``.

    An episode is a maximal run of consecutive bars with ``drawdown_pct < 0``.
    Average duration is the mean run length in days. A monotonically rising track
    has zero episodes → duration 0.0.
    """
    episodes: List[int] = []
    run = 0
    for bar in curve:
        if float(bar.get("drawdown_pct", 0.0)) < 0:
            run += 1
        elif run:
            episodes.append(run)
            run = 0
    if run:
        episodes.append(run)
    avg = statistics.fmean(episodes) if episodes else 0.0
    return {
        "num_episodes": len(episodes),
        "avg_drawdown_duration_days": rnd(avg, 4),
        "max_drawdown_duration_days": max(episodes) if episodes else 0,
    }


def _monthly_table(curve: List[dict]) -> List[dict]:
    """Compounded return per calendar month (YYYY-MM). Shows whatever exists."""
    buckets: "OrderedDict[str, List[float]]" = OrderedDict()
    for bar in curve[1:]:  # skip seed bar
        date = str(bar.get("date", ""))
        if len(date) < 7:
            continue
        buckets.setdefault(date[:7], []).append(float(bar["daily_return_pct"]))
    return [
        {"month": m, "return_pct": rnd(compound_return_pct(rs), 6), "days": len(rs)}
        for m, rs in buckets.items()
    ]


def build_tear_sheet(data_dir: str | Path = "data") -> Dict[str, Any]:
    """Assemble the hedge-fund tear sheet. Never raises on bad/empty inputs."""
    daily = load_equity_curve(data_dir)
    real_bars = real_track_bars(daily)
    curve = rebuild_curve(real_bars)
    returns = daily_returns_pct(curve)
    notes: List[str] = []
    if not daily:
        notes.append("equity_curve_daily.json missing/empty — metrics are null/zero.")

    metrics = compute_risk_metrics(curve, risk_free_annual_pct=RISK_FREE_ANNUAL_PCT)

    # Dollar max drawdown from the rebuilt curve's running peak.
    peak = 0.0
    max_dd_usd = 0.0
    for bar in curve:
        eq = float(bar.get("close_equity", 0.0))
        peak = max(peak, eq)
        max_dd_usd = min(max_dd_usd, eq - peak)

    return {
        "meta": {
            "generated_at": now_iso(),
            "module": "tear_sheet_hf",
            "mp": "MP-1236",
            "advisory_only": True,
            "is_demo": False,
            "risk_free_annual_pct": RISK_FREE_ANNUAL_PCT,
            "annualization_days": ANNUALIZATION_DAYS,
            "track_days": len(curve),
            "return_days": len(returns),
            "track_start": curve[0]["date"] if curve else None,
            "track_end": curve[-1]["date"] if curve else None,
            "source_files": ["equity_curve_daily.json"],
            "disclaimer": DISCLAIMER,
        },
        "ratios": {
            "sharpe_ratio": metrics["sharpe_ratio"],
            "sortino_ratio": metrics["sortino_ratio"],
            "calmar_ratio": metrics["calmar_ratio"],
            "annualized_return_pct": metrics["annualized_return_pct"],
            "annualized_vol_pct": metrics["annualized_vol_pct"],
        },
        "drawdown": {
            "max_drawdown_pct": metrics["max_drawdown_pct"],
            "max_drawdown_usd": rnd(max_dd_usd, 2),
            **_drawdown_episodes(curve),
        },
        "returns": {
            "total_return_pct_compounded": rnd(compound_return_pct(returns), 6),
            "annualized_return_pct": metrics["annualized_return_pct"],
            "win_rate_pct": metrics["win_rate_pct"],
            "best_day": metrics["best_day"],
            "worst_day": metrics["worst_day"],
            "mean_daily_return_pct": metrics["mean_daily_return_pct"],
            "daily_volatility_pct": metrics["daily_volatility_pct"],
        },
        "rolling_sharpe_30d": _rolling_sharpe(returns),
        "monthly_returns": _monthly_table(curve),
        "notes": notes,
    }


def write_tear_sheet(doc: dict, data_dir: str | Path = "data") -> Dict[str, Any]:
    """Idempotent atomic write to ``data/tear_sheet.json``."""
    path = Path(data_dir) / "tear_sheet.json"
    existing = read_json(path, default=None)
    if isinstance(existing, dict) and content_fingerprint(existing) == content_fingerprint(doc):
        return {"changed": False, "path": str(path)}
    atomic_write_json(path, doc)
    return {"changed": True, "path": str(path)}


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SPA hedge-fund tear sheet (read-only).")
    p.add_argument("--run", action="store_true", help="write data/tear_sheet.json")
    p.add_argument("--check", action="store_true", help="compute + print, no write (default)")
    p.add_argument("--data-dir", default="data", help="directory of data/*.json (default: data)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print("ERROR: invalid arguments — use --check | --run [--data-dir DIR]",
                  file=sys.stderr)
        return 0
    try:
        doc = build_tear_sheet(data_dir=args.data_dir)
        if args.run:
            outcome = write_tear_sheet(doc, data_dir=args.data_dir)
            r = doc["ratios"]
            print(f"tear_sheet_hf: sharpe={r['sharpe_ratio']} calmar={r['calmar_ratio']} "
                  f"ann_return={r['annualized_return_pct']}% — "
                  f"{'written' if outcome['changed'] else 'unchanged (idempotent)'} "
                  f"{outcome['path']}")
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: never traceback, exit 0
        print(f"tear_sheet_hf: ERROR — {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
