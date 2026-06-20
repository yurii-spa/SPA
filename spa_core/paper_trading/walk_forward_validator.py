# DEPRECATED — orphaned module. Canonical: spa_core.backtesting.walk_forward_validator
# No active imports point here. TODO: remove in next cleanup.
# This file is kept for git history only.
raise ImportError(
    "DEPRECATED: use spa_core.backtesting.walk_forward_validator instead"
)

#!/usr/bin/env python3
"""Walk-Forward Validation Harness (SPA-V428 / MP-128) — read-only / advisory.

Tests whether a strategy's in-sample optimal parameters generalise to
out-of-sample data.  The harness slides a ``train_days``-long in-sample window
followed by a ``test_days``-long out-of-sample window, advancing by
``test_days`` each iteration (non-overlapping OOS windows).

For each window and each parameter configuration, performance is measured with
the requested metric.  The parameter that ranked first in-sample is located in
the OOS ranking; if it consistently achieves a high rank OOS the strategy is
*robust*; if it consistently falls to the bottom the strategy may be
curve-fitted (overfit) to historical data.

Metric definitions (simplified, annualised where applicable)
=============================================================
* ``total_return`` – ``(last_equity − first_equity) / first_equity``
* ``sharpe``       – ``mean(Δ) / std(Δ) × √252``  (0 when std = 0)
* ``sortino``      – ``mean(Δ) / down_std(Δ) × √252``  (0 when no Δ < 0)
* ``calmar``       – ``total_return / max_drawdown``  (0 when max_drawdown = 0)

where Δ are the day-over-day simple returns from the equity series, and
``down_std`` is the sample standard deviation of the negative-only returns
(or the absolute value of the single negative return when only one exists).

Parameter equity synthesis
===========================
Because the harness accepts a single base equity curve, different parameter
configurations are represented by scaling the base daily returns by
``param_value``::

    equity_t = equity_{t-1} × (1 + base_return_t × param_value)

This models different leverage / allocation magnitudes applied to the same
underlying return source.  ``param_value=1.0`` reproduces the base equity
exactly; values > 1 amplify returns (and risk); values < 1 attenuate them.

CLI (offline, exit 0 always)::

    python3 -m spa_core.paper_trading.walk_forward_validator --check
    python3 -m spa_core.paper_trading.walk_forward_validator --check --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only.
Pure stdlib (json / os / math / argparse / logging / pathlib / sys) —
no requests / web3 / LLM SDK / sockets / network. Never touches
risk / execution / allocator / cycle_runner.
"""
# from __future__ import annotations  # MP-1233: neutralized — unreachable below DEPRECATED raise, broke py_compile

import argparse
import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("spa.paper_trading.walk_forward_validator")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION = 1
SOURCE_NAME = "walk_forward_validator"
EQUITY_CURVE_FILENAME = "equity_curve_daily.json"


# ── internal helpers ──────────────────────────────────────────────────────────

def _get_equity(record: Dict) -> Optional[float]:
    """Return a valid positive equity float from a bar record, or None."""
    e = record.get("equity", record.get("close_equity"))
    if isinstance(e, (int, float)) and math.isfinite(e) and e > 0:
        return float(e)
    return None


def _extract_equities(equity_slice: List[Dict]) -> List[float]:
    """Return only the valid positive equity values from a slice."""
    result: List[float] = []
    for r in equity_slice:
        e = _get_equity(r)
        if e is not None:
            result.append(e)
    return result


def _daily_returns(equities: List[float]) -> List[float]:
    """Compute simple day-over-day returns from a level series."""
    if len(equities) < 2:
        return []
    rets: List[float] = []
    for i in range(1, len(equities)):
        prev = equities[i - 1]
        if prev != 0.0:
            rets.append((equities[i] - prev) / prev)
    return rets


def _mean(xs: List[float]) -> float:
    if not xs:
        return 0.0
    return sum(xs) / len(xs)


def _sample_std(xs: List[float]) -> float:
    """Sample standard deviation (n-1 denominator). Returns 0.0 for < 2 values."""
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var) if var > 0 else 0.0


def _max_drawdown(equities: List[float]) -> float:
    """Max drawdown as a positive fraction in [0, 1]. Returns 0.0 if none."""
    if len(equities) < 2:
        return 0.0
    peak = equities[0]
    max_dd = 0.0
    for e in equities:
        if e > peak:
            peak = e
        dd = 1.0 - e / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _make_param_equity(base_slice: List[Dict], param_value: float) -> List[Dict]:
    """Synthesise a scaled equity path by multiplying each daily return by *param_value*.

    Starting equity is identical to the base slice.  This allows different
    ``param_value`` settings to represent different leverage / allocation
    magnitudes on the same underlying return series.  Equity is kept ≥ 1e-10
    to prevent non-positive values that would confuse :func:`compute_metric`.
    """
    equities = _extract_equities(base_slice)
    if not equities:
        return []

    dates = [r.get("date", "") for r in base_slice]

    path: List[float] = [equities[0]]
    for i in range(1, len(equities)):
        prev = equities[i - 1]
        base_ret = (equities[i] - prev) / prev if prev != 0.0 else 0.0
        scaled_ret = base_ret * param_value
        new_eq = max(1e-10, path[-1] * (1.0 + scaled_ret))
        path.append(new_eq)

    result: List[Dict] = []
    for i, eq in enumerate(path):
        d = dates[i] if i < len(dates) else ""
        result.append({"date": d, "equity": eq})
    return result


# ── public API ────────────────────────────────────────────────────────────────

def compute_metric(equity_slice: List[Dict], metric: str) -> float:
    """Compute a performance metric from an equity slice.

    Parameters
    ----------
    equity_slice:
        List of bar dicts containing an ``equity`` (or ``close_equity``) key.
    metric:
        One of ``'sharpe'``, ``'sortino'``, ``'calmar'``, ``'total_return'``.

    Returns
    -------
    float
        0.0 for edge cases: empty slice, single point, flat equity (std = 0),
        no negative returns (sortino), no drawdown (calmar), or unknown metric.
    """
    if not equity_slice:
        return 0.0

    equities = _extract_equities(equity_slice)
    if len(equities) < 2:
        return 0.0

    first, last = equities[0], equities[-1]

    if metric == "total_return":
        return (last - first) / first

    rets = _daily_returns(equities)
    if not rets:
        return 0.0

    mean_r = _mean(rets)

    if metric == "sharpe":
        std_r = _sample_std(rets)
        if std_r == 0.0:
            return 0.0
        return mean_r / std_r * math.sqrt(252)

    if metric == "sortino":
        neg_rets = [r for r in rets if r < 0]
        if not neg_rets:
            return 0.0
        # For a single negative return use its absolute value as the downside deviation.
        if len(neg_rets) == 1:
            down_std = abs(neg_rets[0])
        else:
            down_std = _sample_std(neg_rets)
        if down_std == 0.0:
            return 0.0
        return mean_r / down_std * math.sqrt(252)

    if metric == "calmar":
        total_ret = (last - first) / first
        max_dd = _max_drawdown(equities)
        if max_dd == 0.0:
            return 0.0
        return total_ret / max_dd

    log.warning("Unknown metric %r; returning 0.0", metric)
    return 0.0


def run_walk_forward(
    equity_curve: List[Dict],
    strategy_params: List[Dict],
    train_days: int = 90,
    test_days: int = 30,
    metric: str = "sharpe",
) -> Dict:
    """Run walk-forward validation across sliding train/test windows.

    Parameters
    ----------
    equity_curve:
        Daily bars ``[{date, equity, ...}, ...]`` sorted oldest-first.
    strategy_params:
        Parameter configurations ``[{name, param_key, param_value, ...}, ...]``.
        Each config's equity is synthesised via :func:`_make_param_equity`
        (base daily returns × ``param_value``).
    train_days:
        In-sample window length (default 90).
    test_days:
        Out-of-sample window length (default 30). Windows advance by
        ``test_days`` each step, keeping OOS windows non-overlapping.
    metric:
        Performance metric for ranking (``'sharpe'`` | ``'sortino'`` |
        ``'calmar'`` | ``'total_return'``).

    Returns
    -------
    dict with keys:

    * ``windows`` – list of window result dicts (see below).
    * ``avg_oos_rank_pct`` – average OOS rank percentile (0 = always best,
      1 = always worst); computed as ``(rank − 1) / (n_params − 1)``.
    * ``robustness_score`` – ``1 − avg_oos_rank_pct`` (higher = better).
    * ``is_robust`` – ``robustness_score > 0.5``.
    * ``windows_count`` – number of completed windows.

    Each window dict contains:
    ``train_start``, ``train_end``, ``test_start``, ``test_end``,
    ``best_param_in_sample``, ``best_value_in_sample``,
    ``out_of_sample_value``, ``out_of_sample_rank``, ``n_params``.
    """
    _empty: Dict = {
        "windows": [],
        "avg_oos_rank_pct": 0.0,
        "robustness_score": 1.0,
        "is_robust": True,
        "windows_count": 0,
    }

    if not equity_curve or len(equity_curve) < train_days + test_days:
        return _empty
    if not strategy_params:
        return _empty

    n_params = len(strategy_params)
    window_size = train_days + test_days
    windows: List[Dict] = []
    start = 0

    while start + window_size <= len(equity_curve):
        train_slice = equity_curve[start: start + train_days]
        test_slice = equity_curve[start + train_days: start + window_size]

        train_start = train_slice[0].get("date", "") if train_slice else ""
        train_end = train_slice[-1].get("date", "") if train_slice else ""
        test_start = test_slice[0].get("date", "") if test_slice else ""
        test_end = test_slice[-1].get("date", "") if test_slice else ""

        # ── in-sample scores ──────────────────────────────────────────────────
        is_scores: List[Tuple[str, float]] = []
        for p in strategy_params:
            name = p.get("name", "")
            pv = float(p.get("param_value", 1.0))
            param_eq = _make_param_equity(train_slice, pv)
            score = compute_metric(param_eq, metric)
            is_scores.append((name, score))

        best_is_name, best_is_value = max(is_scores, key=lambda x: x[1])

        # ── out-of-sample scores & rank ───────────────────────────────────────
        oos_scores: List[Tuple[str, float]] = []
        for p in strategy_params:
            name = p.get("name", "")
            pv = float(p.get("param_value", 1.0))
            param_eq = _make_param_equity(test_slice, pv)
            score = compute_metric(param_eq, metric)
            oos_scores.append((name, score))

        # rank 1 = highest score (best performer)
        sorted_oos = sorted(oos_scores, key=lambda x: x[1], reverse=True)
        oos_rank_map = {nm: rank + 1 for rank, (nm, _) in enumerate(sorted_oos)}

        best_oos_rank = oos_rank_map.get(best_is_name, n_params)
        best_oos_value = next(
            (s for nm, s in oos_scores if nm == best_is_name), 0.0
        )

        windows.append(
            {
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
                "best_param_in_sample": best_is_name,
                "best_value_in_sample": best_is_value,
                "out_of_sample_value": best_oos_value,
                "out_of_sample_rank": best_oos_rank,
                "n_params": n_params,
            }
        )

        start += test_days

    if not windows:
        return _empty

    # ── aggregate statistics ──────────────────────────────────────────────────
    rank_pcts: List[float] = []
    for w in windows:
        np_ = w["n_params"]
        if np_ <= 1:
            rank_pcts.append(0.0)
        else:
            rank_pcts.append((w["out_of_sample_rank"] - 1) / (np_ - 1))

    avg_rank_pct = _mean(rank_pcts)
    robustness = 1.0 - avg_rank_pct

    return {
        "windows": windows,
        "avg_oos_rank_pct": round(avg_rank_pct, 6),
        "robustness_score": round(robustness, 6),
        "is_robust": robustness > 0.5,
        "windows_count": len(windows),
    }


def detect_overfitting(walk_forward_result: Dict) -> Dict:
    """Analyse a walk-forward result for overfitting signals.

    A window is flagged as *overfit* when the in-sample best parameter ranked
    **above** the 50th percentile OOS (i.e., rank_pct > 0.5, meaning below
    median among all parameters).

    Parameters
    ----------
    walk_forward_result:
        Return value of :func:`run_walk_forward`.

    Returns
    -------
    dict with keys:

    * ``overfit_windows`` – count of flagged windows.
    * ``overfit_rate``    – ``overfit_windows / total_windows`` (0.0 if none).
    * ``verdict``         – ``'ROBUST'`` (rate ≤ 1/3) | ``'MODERATE'``
      (1/3 < rate ≤ 2/3) | ``'OVERFIT'`` (rate > 2/3).
    * ``explanation``     – human-readable summary.
    """
    windows = walk_forward_result.get("windows", [])

    if not windows:
        return {
            "overfit_windows": 0,
            "overfit_rate": 0.0,
            "verdict": "ROBUST",
            "explanation": "No windows available; defaulting to ROBUST.",
        }

    overfit_count = 0
    for w in windows:
        n = w.get("n_params", 1)
        rank = w.get("out_of_sample_rank", 1)
        rank_pct = (rank - 1) / (n - 1) if n > 1 else 0.0
        if rank_pct > 0.5:
            overfit_count += 1

    total = len(windows)
    overfit_rate = overfit_count / total

    if overfit_rate <= 1 / 3:
        verdict = "ROBUST"
        explanation = (
            f"In-sample best generalised well OOS: only {overfit_count}/{total} "
            f"windows ({overfit_rate:.1%}) showed below-median OOS rank."
        )
    elif overfit_rate <= 2 / 3:
        verdict = "MODERATE"
        explanation = (
            f"Mixed generalisation: {overfit_count}/{total} windows "
            f"({overfit_rate:.1%}) had below-median OOS rank for the IS-best param."
        )
    else:
        verdict = "OVERFIT"
        explanation = (
            f"Poor generalisation: {overfit_count}/{total} windows "
            f"({overfit_rate:.1%}) had below-median OOS rank. "
            f"Strategy may be curve-fitted to training data."
        )

    return {
        "overfit_windows": overfit_count,
        "overfit_rate": round(overfit_rate, 6),
        "verdict": verdict,
        "explanation": explanation,
    }


def summarize_best_params(walk_forward_result: Dict) -> Dict:
    """Tally how often each parameter won in-sample and out-of-sample.

    Parameters
    ----------
    walk_forward_result:
        Return value of :func:`run_walk_forward`.

    Returns
    -------
    dict keyed by parameter name::

        {
            param_name: {
                in_sample_wins: int,
                oos_wins: int,
                consistency_rate: float  # oos_wins / in_sample_wins
            }
        }

    A parameter appears only if it won at least one in-sample window.
    ``consistency_rate`` is 0.0 when ``in_sample_wins == 0``.
    """
    windows = walk_forward_result.get("windows", [])
    if not windows:
        return {}

    stats: Dict[str, Dict] = {}

    for w in windows:
        is_name = w.get("best_param_in_sample", "")
        oos_rank = w.get("out_of_sample_rank", 1)
        oos_won = oos_rank == 1

        if is_name not in stats:
            stats[is_name] = {"in_sample_wins": 0, "oos_wins": 0}
        stats[is_name]["in_sample_wins"] += 1
        if oos_won:
            stats[is_name]["oos_wins"] += 1

    result: Dict = {}
    for name, s in stats.items():
        is_w = s["in_sample_wins"]
        oos_w = s["oos_wins"]
        result[name] = {
            "in_sample_wins": is_w,
            "oos_wins": oos_w,
            "consistency_rate": round(oos_w / is_w, 6) if is_w > 0 else 0.0,
        }
    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def _load_equity_curve(data_dir: Path) -> List[Dict]:
    path = data_dir / EQUITY_CURVE_FILENAME
    if not path.exists():
        log.warning("Equity curve file not found: %s", path)
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("equity_curve", data.get("entries", []))
        return []
    except Exception as exc:  # pragma: no cover
        log.error("Failed to load equity curve: %s", exc)
        return []


def _cli_check(data_dir: Path) -> None:
    equity_curve = _load_equity_curve(data_dir)
    if len(equity_curve) < 5:
        print(
            json.dumps(
                {"error": "insufficient_data", "n_bars": len(equity_curve)},
                indent=2,
            )
        )
        return

    strategy_params = [
        {"name": "conservative", "param_key": "scale", "param_value": 0.5},
        {"name": "base", "param_key": "scale", "param_value": 1.0},
        {"name": "aggressive", "param_key": "scale", "param_value": 1.5},
    ]

    result = run_walk_forward(equity_curve, strategy_params)
    overfit = detect_overfitting(result)
    summary = summarize_best_params(result)

    print(
        json.dumps(
            {
                "walk_forward": result,
                "overfitting": overfit,
                "param_summary": summary,
            },
            indent=2,
        )
    )


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Walk-Forward Validation Harness (SPA-V428 / MP-128)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print results without writing (default)",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        help="Path to the data directory",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    _cli_check(Path(args.data_dir))


if __name__ == "__main__":
    main()
