"""
Yield Strategy Backtester (MP-886)
====================================

Simple backtesting of yield strategies using historical daily APY observations.
Computes compounded returns, rebalance costs, Sharpe ratio, and labels.

Design constraints:
* Pure stdlib only — no numpy/scipy/requests/pandas.
* Atomic writes: tmp + os.replace (POSIX-safe).
* Advisory / read-only analytics — never modifies allocator/risk/execution.
* Deterministic: identical input → identical output.
* Ring-buffer JSON: MAX_ENTRIES = 100.

CLI:
    python3 -m spa_core.analytics.yield_strategy_backtester --check  (default)
    python3 -m spa_core.analytics.yield_strategy_backtester --run    (+ atomic save)
    python3 -m spa_core.analytics.yield_strategy_backtester --run --data-dir PATH
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = _PROJECT_ROOT / "data" / "backtest_results_log.json"
MAX_ENTRIES = 100  # ring-buffer size

_DEFAULT_REBALANCE_FREQUENCY_DAYS = 7
_DEFAULT_RISK_FREE_RATE_PCT = 4.0


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------

def _atomic_write_json(path: Path, payload: object) -> None:
    """Atomic JSON write: tmp-file + os.replace. Creates parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Core math helpers
# ---------------------------------------------------------------------------

def _mean(data: List[float]) -> float:
    """Arithmetic mean; 0.0 for empty list."""
    if not data:
        return 0.0
    return sum(data) / len(data)


def _population_std_dev(data: List[float]) -> float:
    """
    Population standard deviation using math.sqrt and manual calculation.
    Returns 0.0 for empty list or single element.
    """
    n = len(data)
    if n <= 1:
        return 0.0
    mu = _mean(data)
    variance = sum((x - mu) ** 2 for x in data) / n
    return math.sqrt(variance)


def _compound_final_capital(
    initial_capital: float, daily_apy_history: List[float]
) -> float:
    """
    Compound capital over the history of daily APY observations.
    daily_return_i = daily_apy_history[i] / 100 / 365
    final_capital = initial_capital * product(1 + daily_return_i)
    Empty history → initial_capital.
    """
    if not daily_apy_history:
        return initial_capital
    capital = initial_capital
    for apy in daily_apy_history:
        daily_return = apy / 100.0 / 365.0
        capital *= 1.0 + daily_return
    return capital


# ---------------------------------------------------------------------------
# Label helpers
# ---------------------------------------------------------------------------

def _performance_label(net_return_pct: float) -> str:
    """
    "EXCEPTIONAL" if net_return_pct > 50
    "STRONG"      if net_return_pct > 20
    "GOOD"        if net_return_pct > 10
    "MODERATE"    if net_return_pct > 0
    "POOR"        otherwise (<=0)
    """
    if net_return_pct > 50:
        return "EXCEPTIONAL"
    if net_return_pct > 20:
        return "STRONG"
    if net_return_pct > 10:
        return "GOOD"
    if net_return_pct > 0:
        return "MODERATE"
    return "POOR"


def _consistency_label(apy_std_dev: float) -> str:
    """
    "VERY_CONSISTENT"   if std < 2
    "CONSISTENT"        if std < 5
    "VARIABLE"          if std < 10
    "HIGHLY_VARIABLE"   if std >= 10
    """
    if apy_std_dev < 2:
        return "VERY_CONSISTENT"
    if apy_std_dev < 5:
        return "CONSISTENT"
    if apy_std_dev < 10:
        return "VARIABLE"
    return "HIGHLY_VARIABLE"


def _build_recommendation(
    performance_label: str,
    consistency_label: str,
    net_return_pct: float,
    sharpe_ratio: float,
    days_tested: int,
    average_apy_pct: float,
    rebalance_count: int,
) -> str:
    """Build recommendation string based on performance label."""
    if performance_label == "EXCEPTIONAL" and sharpe_ratio > 2:
        return (
            f"Outstanding strategy. {net_return_pct:.1f}% net return, "
            f"Sharpe {sharpe_ratio:.2f}."
        )
    if performance_label in ("EXCEPTIONAL", "STRONG"):
        return (
            f"Strong performer. {net_return_pct:.1f}% net return "
            f"over {days_tested} days."
        )
    if performance_label == "GOOD":
        return (
            f"Solid yield. Average APY {average_apy_pct:.1f}%, "
            f"{rebalance_count} rebalances."
        )
    if performance_label == "MODERATE":
        return "Positive but modest returns. Consider lower rebalance costs."
    # POOR
    return (
        f"Strategy underperformed. Net return: {net_return_pct:.1f}%. "
        f"Review APY stability."
    )


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------

def analyze(strategies: list, config: dict = None) -> dict:
    """
    Backtest yield strategies using historical daily APY data.

    strategies: list of {
        "name": str,
        "daily_apy_history": list[float],
        "initial_capital_usd": float,
        "rebalance_cost_bps": float
    }
    config: {
        "rebalance_frequency_days": int,   # default 7
        "risk_free_rate_pct": float        # default 4.0
    }

    Returns: {
        "strategies": list of per-strategy results,
        "best_strategy": str | None,
        "best_sharpe": str | None,
        "timestamp": float
    }
    """
    cfg = config or {}
    rebalance_frequency_days = int(
        cfg.get("rebalance_frequency_days", _DEFAULT_REBALANCE_FREQUENCY_DAYS)
    )
    risk_free_rate_pct = float(
        cfg.get("risk_free_rate_pct", _DEFAULT_RISK_FREE_RATE_PCT)
    )

    if not strategies:
        return {
            "strategies": [],
            "best_strategy": None,
            "best_sharpe": None,
            "timestamp": time.time(),
        }

    results = []
    for strat in strategies:
        name = strat.get("name", "")
        daily_apy_history = list(strat.get("daily_apy_history", []))
        initial_capital_usd = float(strat.get("initial_capital_usd", 0.0))
        rebalance_cost_bps = float(strat.get("rebalance_cost_bps", 0.0))

        days_tested = len(daily_apy_history)

        # APY statistics
        average_apy_pct = _mean(daily_apy_history)
        min_apy_pct = min(daily_apy_history) if daily_apy_history else 0.0
        max_apy_pct = max(daily_apy_history) if daily_apy_history else 0.0
        apy_std_dev = _population_std_dev(daily_apy_history)

        # Compounding
        final_capital_usd = _compound_final_capital(
            initial_capital_usd, daily_apy_history
        )

        # Returns
        if initial_capital_usd > 0:
            total_return_pct = (
                (final_capital_usd - initial_capital_usd) / initial_capital_usd * 100.0
            )
        else:
            total_return_pct = 0.0

        # Rebalance cost
        rebalance_count = (
            days_tested // rebalance_frequency_days
            if rebalance_frequency_days > 0
            else 0
        )
        total_rebalance_cost_usd = (
            rebalance_count * (rebalance_cost_bps / 10000.0) * initial_capital_usd
        )

        # Net return
        if initial_capital_usd > 0:
            cost_pct = total_rebalance_cost_usd / initial_capital_usd * 100.0
            net_return_pct = total_return_pct - cost_pct
        else:
            net_return_pct = 0.0

        # Sharpe ratio
        if apy_std_dev > 0:
            sharpe_ratio = (average_apy_pct - risk_free_rate_pct) / apy_std_dev
        else:
            sharpe_ratio = 0.0

        # Labels
        perf_label = _performance_label(net_return_pct)
        cons_label = _consistency_label(apy_std_dev)

        # Recommendation
        recommendation = _build_recommendation(
            perf_label,
            cons_label,
            net_return_pct,
            sharpe_ratio,
            days_tested,
            average_apy_pct,
            rebalance_count,
        )

        results.append(
            {
                "name": name,
                "days_tested": days_tested,
                "average_apy_pct": average_apy_pct,
                "min_apy_pct": min_apy_pct,
                "max_apy_pct": max_apy_pct,
                "apy_std_dev": apy_std_dev,
                "final_capital_usd": final_capital_usd,
                "total_return_pct": total_return_pct,
                "rebalance_count": rebalance_count,
                "total_rebalance_cost_usd": total_rebalance_cost_usd,
                "net_return_pct": net_return_pct,
                "sharpe_ratio": sharpe_ratio,
                "performance_label": perf_label,
                "consistency_label": cons_label,
                "recommendation": recommendation,
            }
        )

    # Best by net_return_pct
    best_strategy: Optional[str] = None
    if results:
        best = max(results, key=lambda r: r["net_return_pct"])
        best_strategy = best["name"]

    # Best by sharpe_ratio (ties broken by first occurrence)
    best_sharpe: Optional[str] = None
    if results:
        best_s = max(results, key=lambda r: r["sharpe_ratio"])
        best_sharpe = best_s["name"]

    return {
        "strategies": results,
        "best_strategy": best_strategy,
        "best_sharpe": best_sharpe,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load_log(path: Path) -> list:
    """Load existing ring-buffer log or return empty list."""
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_result(result: dict, path: Path = DATA_FILE) -> None:
    """Append result to ring-buffer log (max MAX_ENTRIES) and atomic-write."""
    log = _load_log(path)
    log.append(result)
    if len(log) > MAX_ENTRIES:
        log = log[-MAX_ENTRIES:]
    _atomic_write_json(path, log)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _sample_strategies() -> list:
    """Return sample strategy data for CLI demo."""
    apy_a = [8.5] * 180
    apy_b = [5.0, 10.0, 3.0, 15.0, 4.0, 8.0] * 30
    apy_c = [3.5] * 180

    return [
        {
            "name": "HighSteadyYield",
            "daily_apy_history": apy_a,
            "initial_capital_usd": 100_000.0,
            "rebalance_cost_bps": 5.0,
        },
        {
            "name": "VariableYield",
            "daily_apy_history": apy_b,
            "initial_capital_usd": 100_000.0,
            "rebalance_cost_bps": 10.0,
        },
        {
            "name": "LowStableYield",
            "daily_apy_history": apy_c,
            "initial_capital_usd": 100_000.0,
            "rebalance_cost_bps": 2.0,
        },
    ]


def main(argv: list = None) -> None:
    """CLI entry point."""
    if argv is None:
        argv = sys.argv[1:]

    run_mode = "--run" in argv
    data_dir: Optional[Path] = None

    if "--data-dir" in argv:
        idx = argv.index("--data-dir")
        if idx + 1 < len(argv):
            data_dir = Path(argv[idx + 1])

    out_path = (data_dir / "backtest_results_log.json") if data_dir else DATA_FILE

    strategies = _sample_strategies()
    result = analyze(strategies)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if run_mode:
        save_result(result, out_path)
        print(f"\n✅ Saved to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
