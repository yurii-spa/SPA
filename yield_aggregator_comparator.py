"""YieldAggregatorComparator — MP-825.

Compares yield aggregators (Yearn, Beefy, Convex, etc.) for the same underlying
asset to find the best net APY after fees.

Design constraints
------------------
* Pure stdlib only — no external dependencies.
* Advisory / read-only — never touches allocator / risk / execution.
* Atomic writes: tmp-file + os.replace on every save.
* Ring-buffer: data/aggregator_comparison_log.json capped at MAX_ENTRIES=100.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/aggregator_comparison_log.json")
MAX_ENTRIES = 100
DEFAULT_MIN_TVL_USD = 1_000_000.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _trust_score(audit_count: int, strategy_count: int, tvl_usd: float) -> int:
    """Compute 0-100 trust score.

    Components:
    - audit_count * 15           (unlimited contribution, capped at total 100)
    - min(strategy_count * 5, 25)
    - int(min(log10(tvl_usd / 1e6 + 1) * 20, 30))
    """
    log_comp = math.log10(tvl_usd / 1_000_000.0 + 1) * 20
    log_comp = min(log_comp, 30.0)
    raw = audit_count * 15 + min(strategy_count * 5, 25) + int(log_comp)
    return min(100, raw)


def _fee_drag(underlying_apy: float, performance_fee_pct: float,
              management_fee_pct: float) -> float:
    """Annual fee impact on gross APY.

    fee_drag_pct = (underlying_apy * performance_fee_pct / 100) + management_fee_pct
    """
    return (underlying_apy * performance_fee_pct / 100.0) + management_fee_pct


def _append_log(entry: dict) -> None:
    """Append result to ring-buffer JSON log (atomic write, capped at MAX_ENTRIES)."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(DATA_FILE) as fh:
            log: list = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(entry)
    if len(log) > MAX_ENTRIES:
        log = log[-MAX_ENTRIES:]

    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w") as fh:
        json.dump(log, fh, indent=2)
    os.replace(tmp, DATA_FILE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(asset: str, aggregators: list, config: dict = None) -> dict:
    """Compare yield aggregators for *asset*, returning ranked fee-adjusted results.

    Parameters
    ----------
    asset:
        Name of the underlying asset (e.g. "USDC", "WETH").
    aggregators:
        List of aggregator dicts with keys:
            name, underlying_apy, performance_fee_pct, management_fee_pct,
            gas_optimization_bonus, auto_compound_bonus, tvl_usd,
            strategy_count, audit_count.
    config:
        Optional dict with:
            min_tvl_usd  (default 1_000_000) — filter aggregators below this TVL.

    Returns
    -------
    dict with keys: asset, aggregators, filtered_out, winner, highest_net_apy,
    most_trusted, market_avg_net_apy, timestamp.
    """
    config = config or {}
    min_tvl = float(config.get("min_tvl_usd", DEFAULT_MIN_TVL_USD))

    passing: list[dict] = []
    filtered_out: list[str] = []

    for agg in aggregators:
        name = str(agg["name"])
        tvl = float(agg.get("tvl_usd", 0.0))

        if tvl < min_tvl:
            filtered_out.append(name)
            continue

        underlying_apy = float(agg.get("underlying_apy", 0.0))
        perf_fee_pct = float(agg.get("performance_fee_pct", 0.0))
        mgmt_fee_pct = float(agg.get("management_fee_pct", 0.0))
        gas_bonus = float(agg.get("gas_optimization_bonus", 0.0))
        compound_bonus = float(agg.get("auto_compound_bonus", 0.0))
        strategy_count = int(agg.get("strategy_count", 0))
        audit_count = int(agg.get("audit_count", 0))

        gross_apy = underlying_apy + gas_bonus + compound_bonus
        drag = _fee_drag(underlying_apy, perf_fee_pct, mgmt_fee_pct)
        net_apy = gross_apy - drag

        if gross_apy != 0.0:
            fee_efficiency = net_apy / gross_apy * 100.0
        else:
            fee_efficiency = 0.0

        ts = _trust_score(audit_count, strategy_count, tvl)
        composite = net_apy * (ts / 100.0)

        passing.append({
            "name": name,
            "gross_apy": gross_apy,
            "fee_drag_pct": drag,
            "net_apy": net_apy,
            "fee_efficiency": fee_efficiency,
            "trust_score": ts,
            "composite_score": composite,
            "rank": 0,  # assigned after sort
        })

    # Sort by composite_score descending; assign sequential ranks from 1
    passing.sort(key=lambda x: x["composite_score"], reverse=True)
    for idx, item in enumerate(passing):
        item["rank"] = idx + 1

    winner = passing[0]["name"] if passing else None
    highest_net_apy = (
        max(passing, key=lambda x: x["net_apy"])["name"] if passing else None
    )
    most_trusted = (
        max(passing, key=lambda x: x["trust_score"])["name"] if passing else None
    )
    market_avg_net_apy = (
        sum(x["net_apy"] for x in passing) / len(passing) if passing else 0.0
    )

    result: dict = {
        "asset": asset,
        "aggregators": passing,
        "filtered_out": filtered_out,
        "winner": winner,
        "highest_net_apy": highest_net_apy,
        "most_trusted": most_trusted,
        "market_avg_net_apy": market_avg_net_apy,
        "timestamp": time.time(),
    }

    _append_log(result)
    return result
