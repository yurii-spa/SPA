#!/usr/bin/env python3
"""Honest Metrics — Sortino/Sharpe CI + LOW_CONFIDENCE flag (SPA / MP-138)

Read-only / advisory module.  Computes honest statistical metrics with proper
small-sample handling: returns None instead of misleading numbers, adds
bootstrap confidence intervals, and labels confidence tiers based on sample size.

Functions
---------
compute_sortino(returns, target=0.0, annualize=True)
compute_sharpe(returns, risk_free_daily=0.0, annualize=True)
bootstrap_ci(metric_fn, returns, n_bootstrap=1000, ci_level=0.95, seed=42)
confidence_label(n_days)
evaluate_strategy(equity_history, initial_capital=100_000.0)
run_honest_metrics(data_dir, output_path=None)

Constraints
-----------
- Pure stdlib: math, statistics, random, json, os, pathlib, datetime, tempfile
- NO numpy, pandas, scipy — zero external imports
- Atomic writes: tmp + os.replace — no direct open(..., "w") on state files
- STRICTLY READ-ONLY: never touches risk / execution / allocator / cycle_runner
- LLM FORBIDDEN in this module (SPA security policy)

CLI (offline, exit 0 always)::

    python3 -m spa_core.paper_trading.honest_metrics --check    # compute+print, no write (default)
    python3 -m spa_core.paper_trading.honest_metrics --run      # + atomic write
    python3 -m spa_core.paper_trading.honest_metrics --run --data-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

_ANNUALIZE_FACTOR = math.sqrt(252)
_MIN_SAMPLES = 3          # minimum returns for Sharpe / Sortino
_BOOTSTRAP_MIN_VALID = 5  # minimum valid bootstrap draws to report CI

SCHEMA_VERSION = 1
SOURCE_NAME = "honest_metrics"
OUTPUT_FILENAME = "honest_metrics.json"


# ---------------------------------------------------------------------------
# Core metric functions
# ---------------------------------------------------------------------------

def compute_sortino(
    returns: List[float],
    target: float = 0.0,
    annualize: bool = True,
) -> Dict[str, Any]:
    """Compute Sortino ratio with small-sample protection.

    Downside deviation uses the full-sample denominator (N) so that infrequent
    but severe losses are not hidden by a small downside-only count.

    Parameters
    ----------
    returns:
        Daily returns as decimal fractions (e.g. 0.01 for 1 %).
    target:
        Minimum acceptable return (MAR), default 0.0.
    annualize:
        Multiply result by √252 when True.

    Returns
    -------
    dict with keys:
        ``sortino``         float | None
        ``n``               int   — total sample size
        ``downside_returns`` int  — returns strictly below *target*
    """
    n = len(returns)
    downside_deviations = [r - target for r in returns if r < target]
    n_down = len(downside_deviations)

    if n < _MIN_SAMPLES or n_down == 0:
        return {"sortino": None, "n": n, "downside_returns": n_down}

    # Downside deviation: sqrt( sum(dev^2) / N )  — full-sample denominator
    mean_sq = sum(d * d for d in downside_deviations) / n
    downside_dev = math.sqrt(mean_sq)

    if downside_dev == 0.0:
        return {"sortino": None, "n": n, "downside_returns": n_down}

    excess_return = statistics.mean(returns) - target
    sortino = excess_return / downside_dev

    if annualize:
        sortino *= _ANNUALIZE_FACTOR

    return {"sortino": sortino, "n": n, "downside_returns": n_down}


def compute_sharpe(
    returns: List[float],
    risk_free_daily: float = 0.0,
    annualize: bool = True,
) -> Dict[str, Any]:
    """Compute Sharpe ratio with small-sample protection.

    Parameters
    ----------
    returns:
        Daily returns as decimal fractions.
    risk_free_daily:
        Daily risk-free rate (default 0.0).
    annualize:
        Multiply result by √252 when True.

    Returns
    -------
    dict with keys:
        ``sharpe``  float | None
        ``n``       int
    """
    n = len(returns)

    if n < _MIN_SAMPLES:
        return {"sharpe": None, "n": n}

    try:
        std = statistics.stdev(returns)     # sample std (n-1 denominator)
    except statistics.StatisticsError:
        return {"sharpe": None, "n": n}

    if std == 0.0:
        return {"sharpe": None, "n": n}

    excess = statistics.mean(returns) - risk_free_daily
    sharpe = excess / std

    if annualize:
        sharpe *= _ANNUALIZE_FACTOR

    return {"sharpe": sharpe, "n": n}


def bootstrap_ci(
    metric_fn: Callable[[List[float]], Optional[float]],
    returns: List[float],
    n_bootstrap: int = 1000,
    ci_level: float = 0.95,
    seed: int = 42,
) -> Optional[Dict[str, Any]]:
    """Bootstrap confidence interval for any scalar metric.

    Uses random.Random(seed) — pure stdlib, fully reproducible.
    Resamples *with replacement* n_bootstrap times, calls metric_fn on each
    resample, collects the finite results, and returns the percentile CI.

    Parameters
    ----------
    metric_fn:
        callable(list[float]) → float | None.  None / inf / nan are excluded.
    returns:
        Daily returns to bootstrap from.
    n_bootstrap:
        Number of resamples.
    ci_level:
        Confidence level (e.g. 0.95 → 95 % CI).
    seed:
        RNG seed for reproducibility.

    Returns
    -------
    dict with keys ``lower``, ``upper``, ``n_valid``
    or None if fewer than 5 valid bootstrap draws.
    """
    n = len(returns)
    if n == 0:
        return None

    rng = random.Random(seed)
    samples: List[float] = []

    for _ in range(n_bootstrap):
        resample = [returns[rng.randint(0, n - 1)] for _ in range(n)]
        val = metric_fn(resample)
        if val is not None and math.isfinite(val):
            samples.append(val)

    if len(samples) < _BOOTSTRAP_MIN_VALID:
        return None

    samples.sort()
    m = len(samples)
    tail = (1.0 - ci_level) / 2.0
    lower_idx = int(math.floor(tail * m))
    upper_idx = int(math.floor((1.0 - tail) * m)) - 1
    upper_idx = max(lower_idx, min(upper_idx, m - 1))

    return {
        "lower": samples[lower_idx],
        "upper": samples[upper_idx],
        "n_valid": m,
    }


def confidence_label(n_days: int) -> str:
    """Map sample size to a confidence tier.

    Parameters
    ----------
    n_days:
        Number of daily return observations.

    Returns
    -------
    str:
        ``"INSUFFICIENT"``   n < 7
        ``"LOW_CONFIDENCE"`` 7 ≤ n < 30
        ``"MODERATE"``       30 ≤ n < 90
        ``"HIGH"``           n ≥ 90
    """
    if n_days < 7:
        return "INSUFFICIENT"
    if n_days < 30:
        return "LOW_CONFIDENCE"
    if n_days < 90:
        return "MODERATE"
    return "HIGH"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_max_drawdown(equity_values: List[float]) -> float:
    """Maximum peak-to-trough drawdown as a positive percentage."""
    if len(equity_values) < 2:
        return 0.0
    peak = equity_values[0]
    max_dd = 0.0
    for e in equity_values:
        if e > peak:
            peak = e
        if peak > 0.0:
            dd = (peak - e) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _annualized_return(
    equity_values: List[float],
    n_returns: int,
) -> Optional[float]:
    """Geometric annualised return (percent).  None if not enough data."""
    if n_returns < 30:
        return None
    e0, e1 = equity_values[0], equity_values[-1]
    if e0 <= 0.0 or e1 <= 0.0:
        return None
    ratio = e1 / e0
    return (ratio ** (252.0 / n_returns) - 1.0) * 100.0


def _calmar(
    annualized_return_pct: Optional[float],
    max_drawdown_pct: float,
) -> Optional[float]:
    """Calmar = annualised return / max drawdown.  None when denominator is 0."""
    if annualized_return_pct is None or max_drawdown_pct == 0.0:
        return None
    return annualized_return_pct / max_drawdown_pct


# ---------------------------------------------------------------------------
# Strategy scorecard
# ---------------------------------------------------------------------------

def evaluate_strategy(
    equity_history: Union[List[Dict[str, Any]], List[float]],
    initial_capital: float = 100_000.0,
) -> Dict[str, Any]:
    """Compute a full metrics scorecard for one strategy's equity history.

    Parameters
    ----------
    equity_history:
        Either:
        - list of ``{"date": "YYYY-MM-DD", "equity": float}`` dicts, or
        - a plain list of float equity values (oldest first).
    initial_capital:
        Starting capital (informational only — not used in ratio math).

    Returns
    -------
    dict::

        {
          "n_days":                int,
          "confidence":            "INSUFFICIENT"|"LOW_CONFIDENCE"|"MODERATE"|"HIGH",
          "sharpe":                float | null,
          "sortino":               float | null,
          "calmar":                float | null,
          "max_drawdown_pct":      float,
          "total_return_pct":      float,
          "annualized_return_pct": float | null,
          "sharpe_ci_95":          {"lower": float, "upper": float} | null,
          "sortino_ci_95":         {"lower": float, "upper": float} | null,
          "warning":               str | null,
        }
    """
    # ------------------------------------------------------------------
    # Normalise input
    # ------------------------------------------------------------------
    if not equity_history:
        equities: List[float] = []
    elif isinstance(equity_history[0], dict):
        equities = [float(e["equity"]) for e in equity_history]
    else:
        equities = [float(v) for v in equity_history]

    n_equity = len(equities)

    # ------------------------------------------------------------------
    # Edge-case: zero or one equity point → no returns at all
    # ------------------------------------------------------------------
    if n_equity < 2:
        return {
            "n_days": 0,
            "confidence": confidence_label(0),
            "sharpe": None,
            "sortino": None,
            "calmar": None,
            "max_drawdown_pct": 0.0,
            "total_return_pct": 0.0,
            "annualized_return_pct": None,
            "sharpe_ci_95": None,
            "sortino_ci_95": None,
            "warning": "Fewer than 30 days: metrics are directional only",
        }

    # ------------------------------------------------------------------
    # Daily returns
    # ------------------------------------------------------------------
    returns: List[float] = []
    for i in range(1, n_equity):
        prev = equities[i - 1]
        curr = equities[i]
        returns.append((curr - prev) / prev if prev != 0.0 else 0.0)

    n_returns = len(returns)
    conf = confidence_label(n_returns)
    warning: Optional[str] = (
        "Fewer than 30 days: metrics are directional only"
        if n_returns < 30
        else None
    )

    # ------------------------------------------------------------------
    # Basic statistics
    # ------------------------------------------------------------------
    total_return_pct = (
        (equities[-1] - equities[0]) / equities[0] * 100.0
        if equities[0] != 0.0
        else 0.0
    )
    max_dd_pct = _compute_max_drawdown(equities)
    ann_ret = _annualized_return(equities, n_returns)

    # ------------------------------------------------------------------
    # Ratios
    # ------------------------------------------------------------------
    sharpe_res = compute_sharpe(returns)
    sortino_res = compute_sortino(returns)
    sharpe_val = sharpe_res["sharpe"]
    sortino_val = sortino_res["sortino"]
    calmar_val = _calmar(ann_ret, max_dd_pct)

    # ------------------------------------------------------------------
    # Bootstrap CIs (only when there are enough returns)
    # ------------------------------------------------------------------
    sharpe_ci: Optional[Dict[str, Any]] = None
    sortino_ci: Optional[Dict[str, Any]] = None

    if n_returns >= _MIN_SAMPLES:
        def _sharpe_fn(r: List[float]) -> Optional[float]:
            return compute_sharpe(r)["sharpe"]

        def _sortino_fn(r: List[float]) -> Optional[float]:
            return compute_sortino(r)["sortino"]

        sharpe_ci = bootstrap_ci(_sharpe_fn, returns)
        sortino_ci = bootstrap_ci(_sortino_fn, returns)

    return {
        "n_days": n_returns,
        "confidence": conf,
        "sharpe": sharpe_val,
        "sortino": sortino_val,
        "calmar": calmar_val,
        "max_drawdown_pct": max_dd_pct,
        "total_return_pct": total_return_pct,
        "annualized_return_pct": ann_ret,
        "sharpe_ci_95": sharpe_ci,
        "sortino_ci_95": sortino_ci,
        "warning": warning,
    }


# ---------------------------------------------------------------------------
# Batch runner — reads shadow_portfolio.json
# ---------------------------------------------------------------------------

def run_honest_metrics(
    data_dir: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Compute honest metrics for all shadow strategies.

    Reads  ``<data_dir>/shadow_portfolio.json``,
    calls  :func:`evaluate_strategy` for each strategy found in ``history``,
    writes ``<data_dir>/honest_metrics.json`` atomically.

    Parameters
    ----------
    data_dir:
        Directory containing shadow_portfolio.json.
    output_path:
        Override output path. Default: ``data_dir/honest_metrics.json``.

    Returns
    -------
    dict with keys ``generated_at``, ``strategies``, etc.
    """
    data_dir = Path(data_dir)
    shadow_path = data_dir / "shadow_portfolio.json"
    out_path = Path(output_path) if output_path else data_dir / OUTPUT_FILENAME

    # ------------------------------------------------------------------
    # Load shadow portfolio
    # ------------------------------------------------------------------
    try:
        with open(shadow_path, "r", encoding="utf-8") as fh:
            shadow = json.load(fh)
    except FileNotFoundError:
        return {
            "error": f"shadow_portfolio.json not found at {shadow_path}",
            "strategies": {},
        }
    except json.JSONDecodeError as exc:
        return {
            "error": f"JSON parse error: {exc}",
            "strategies": {},
        }

    history: List[Dict[str, Any]] = shadow.get("history", [])

    # Discover strategy IDs from first history entry
    strategy_ids: List[str] = []
    if history:
        strategy_ids = [k for k in history[0].keys() if k != "date"]

    # ------------------------------------------------------------------
    # Score each strategy
    # ------------------------------------------------------------------
    results: Dict[str, Any] = {}
    for sid in strategy_ids:
        equity_series = []
        for entry in history:
            eq = entry.get(sid)
            if eq is not None:
                equity_series.append({
                    "date": entry.get("date", ""),
                    "equity": float(eq),
                })
        results[sid] = evaluate_strategy(equity_series)

    output: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_NAME,
        "schema_version": SCHEMA_VERSION,
        "advisory_only": True,
        "n_strategies": len(results),
        "strategies": results,
    }

    # ------------------------------------------------------------------
    # Atomic write
    # ------------------------------------------------------------------
    out_dir = out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=out_dir,
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        json.dump(output, tmp, indent=2)
        tmp_name = tmp.name
    os.replace(tmp_name, out_path)

    return output


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Honest Metrics — Sortino/Sharpe CI + LOW_CONFIDENCE flag (MP-138)"
    )
    parser.add_argument("--run", action="store_true", help="Compute + write output file")
    parser.add_argument("--check", action="store_true", help="Compute + print only (default)")
    parser.add_argument(
        "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        help=f"Data directory (default: {_DEFAULT_DATA_DIR})",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)

    if args.run:
        result = run_honest_metrics(data_dir)
        if "error" in result:
            print(f"ERROR: {result['error']}", file=sys.stderr)
        else:
            print(
                f"honest_metrics: {result['n_strategies']} strategies scored, "
                f"written to {data_dir / OUTPUT_FILENAME}"
            )
        print(json.dumps(result, indent=2))
    else:
        # --check or default: compute without writing
        shadow_path = data_dir / "shadow_portfolio.json"
        try:
            with open(shadow_path, "r", encoding="utf-8") as fh:
                shadow = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return

        history = shadow.get("history", [])
        strategy_ids = [k for k in (history[0].keys() if history else []) if k != "date"]
        results: Dict[str, Any] = {}
        for sid in strategy_ids:
            eq_series = [
                {"date": e.get("date", ""), "equity": float(e[sid])}
                for e in history
                if sid in e
            ]
            results[sid] = evaluate_strategy(eq_series)

        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    _cli()
