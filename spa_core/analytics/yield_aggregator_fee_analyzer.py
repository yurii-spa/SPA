"""
MP-858: YieldAggregatorFeeAnalyzer
Advisory/read-only analytics module.

Analyzes the true net yield after all aggregator fees (management, performance,
withdrawal) and compares fee competitiveness vs market average.

CLI:
    python3 -m spa_core.analytics.yield_aggregator_fee_analyzer --check
    python3 -m spa_core.analytics.yield_aggregator_fee_analyzer --run
    python3 -m spa_core.analytics.yield_aggregator_fee_analyzer --run --data-dir /path
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
DEFAULT_DATA_FILE = os.path.join(_REPO_ROOT, "data", "yield_aggregator_fee_log.json")
_LOG_CAP = 100

_DEFAULT_CONFIG = {
    "market_avg_management_fee": 1.5,
    "market_avg_performance_fee": 20.0,
    "benchmark_apy_pct": 5.0,
}


# ---------------------------------------------------------------------------
# Per-aggregator calculations
# ---------------------------------------------------------------------------

def _management_drag(management_fee_pct: float) -> float:
    """Direct annual management fee drag (same as input %)."""
    return management_fee_pct


def _performance_drag(performance_fee_pct: float, gross_apy_pct: float) -> float:
    """Performance fee expressed as % of gross APY (annualised drag)."""
    return performance_fee_pct / 100.0 * gross_apy_pct


def _withdrawal_drag(withdrawal_fee_pct: float, holding_period_days: int) -> float:
    """Annualised withdrawal fee drag; 0 if holding_period_days == 0."""
    if holding_period_days <= 0:
        return 0.0
    return withdrawal_fee_pct / holding_period_days * 365.0


def _fee_competitiveness(fee_drag: float, gross_apy_pct: float) -> str:
    """
    EXCELLENT | GOOD | FAIR | EXPENSIVE | AVOID based on fee drag
    relative to gross APY.
    """
    if gross_apy_pct == 0:
        if fee_drag > 0:
            return "AVOID"
        return "EXCELLENT"

    if fee_drag <= 0.5:
        return "EXCELLENT"

    ratio = fee_drag / gross_apy_pct * 100.0
    if ratio <= 15.0:
        return "GOOD"
    if ratio <= 30.0:
        return "FAIR"
    if ratio <= 50.0:
        return "EXPENSIVE"
    return "AVOID"


def _fee_efficiency_score(net_apy_pct: float, gross_apy_pct: float, fee_drag: float) -> int:
    """
    0-100 based on net/gross retention.
    gross=0, fee_drag=0 -> 100
    gross=0, fee_drag>0 -> 0
    gross>0 -> min(100, max(0, net/gross*100))
    """
    if gross_apy_pct == 0:
        return 100 if fee_drag == 0 else 0
    retention = max(0.0, net_apy_pct / gross_apy_pct * 100.0)
    return min(100, int(retention))


def _autocompound_label(autocompound: bool) -> str:
    if autocompound:
        return "Auto-compounds (higher effective yield)"
    return "Manual compounding required"


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------

def analyze(aggregators: list, config: dict = None) -> dict:
    """
    Analyze net yield and fee competitiveness for each aggregator.

    Parameters
    ----------
    aggregators : list[dict]
        Each entry: name, gross_apy_pct, management_fee_pct,
        performance_fee_pct, withdrawal_fee_pct, holding_period_days,
        autocompound.
    config : dict | None
        Optional overrides: market_avg_management_fee,
        market_avg_performance_fee, benchmark_apy_pct.

    Returns
    -------
    dict with keys: aggregators, best_net_yield, most_fee_efficient,
    market_summary, timestamp.
    """
    cfg = dict(_DEFAULT_CONFIG)
    if config:
        cfg.update(config)

    benchmark_apy = float(cfg.get("benchmark_apy_pct", 5.0))

    results = []

    for agg in aggregators:
        name = agg["name"]
        gross = float(agg["gross_apy_pct"])
        mgmt_fee = float(agg["management_fee_pct"])
        perf_fee = float(agg["performance_fee_pct"])
        wd_fee = float(agg["withdrawal_fee_pct"])
        holding = int(agg["holding_period_days"])
        autocompound = bool(agg["autocompound"])

        mgmt_drag = _management_drag(mgmt_fee)
        perf_drag = _performance_drag(perf_fee, gross)
        wd_drag = _withdrawal_drag(wd_fee, holding)
        fee_drag = mgmt_drag + perf_drag + wd_drag
        net_apy = gross - fee_drag
        vs_benchmark = net_apy - benchmark_apy

        competitiveness = _fee_competitiveness(fee_drag, gross)
        efficiency = _fee_efficiency_score(net_apy, gross, fee_drag)
        label = _autocompound_label(autocompound)

        results.append(
            {
                "name": name,
                "gross_apy_pct": gross,
                "net_apy_pct": net_apy,
                "fee_drag_pct": fee_drag,
                "management_drag_pct": mgmt_drag,
                "performance_drag_pct": perf_drag,
                "withdrawal_drag_pct": wd_drag,
                "fee_competitiveness": competitiveness,
                "vs_benchmark_pct": vs_benchmark,
                "fee_efficiency_score": efficiency,
                "autocompound_label": label,
            }
        )

    # Aggregates
    if results:
        best_net = max(results, key=lambda r: r["net_apy_pct"])["name"]
        most_efficient = max(results, key=lambda r: r["fee_efficiency_score"])["name"]
        avg_gross = sum(r["gross_apy_pct"] for r in results) / len(results)
        avg_net = sum(r["net_apy_pct"] for r in results) / len(results)
        avg_drag = sum(r["fee_drag_pct"] for r in results) / len(results)
        avg_drag_of_gross = (avg_drag / avg_gross * 100.0) if avg_gross > 0 else 0.0
    else:
        best_net = None
        most_efficient = None
        avg_gross = 0.0
        avg_net = 0.0
        avg_drag = 0.0
        avg_drag_of_gross = 0.0

    return {
        "aggregators": results,
        "best_net_yield": best_net,
        "most_fee_efficient": most_efficient,
        "market_summary": {
            "avg_gross_apy_pct": avg_gross,
            "avg_net_apy_pct": avg_net,
            "avg_fee_drag_pct": avg_drag,
            "avg_fee_drag_of_gross_pct": avg_drag_of_gross,
        },
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Atomic log writer
# ---------------------------------------------------------------------------

def _append_log(result: dict, data_file: str) -> None:
    """Append result to ring-buffer log (max _LOG_CAP entries), atomic write."""
    try:
        with open(data_file, "r") as f:
            log = json.load(f)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(result)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]

    data_dir = os.path.dirname(data_file)
    os.makedirs(data_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=data_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp, data_file)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_DEMO_AGGREGATORS = [
    {
        "name": "Yearn USDC v3",
        "gross_apy_pct": 8.0,
        "management_fee_pct": 2.0,
        "performance_fee_pct": 20.0,
        "withdrawal_fee_pct": 0.0,
        "holding_period_days": 180,
        "autocompound": True,
    },
    {
        "name": "Beefy USDC",
        "gross_apy_pct": 6.5,
        "management_fee_pct": 0.0,
        "performance_fee_pct": 4.5,
        "withdrawal_fee_pct": 0.1,
        "holding_period_days": 90,
        "autocompound": True,
    },
    {
        "name": "Manual Vault",
        "gross_apy_pct": 10.0,
        "management_fee_pct": 1.0,
        "performance_fee_pct": 15.0,
        "withdrawal_fee_pct": 0.5,
        "holding_period_days": 365,
        "autocompound": False,
    },
]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MP-858 YieldAggregatorFeeAnalyzer")
    parser.add_argument("--check", action="store_true", help="Compute and print without writing")
    parser.add_argument("--run", action="store_true", help="Compute and write to log")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    data_file = DEFAULT_DATA_FILE
    if args.data_dir:
        data_file = os.path.join(args.data_dir, "yield_aggregator_fee_log.json")

    result = analyze(_DEMO_AGGREGATORS)
    print(json.dumps(result, indent=2))

    if args.run:
        _append_log(result, data_file)
        print(f"\n[MP-858] Log written -> {data_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
