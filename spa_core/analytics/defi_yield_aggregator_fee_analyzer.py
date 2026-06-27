"""
MP-952: DeFiYieldAggregatorFeeAnalyzer
Analyzes fee structures and impact of DeFi yield aggregators.
Pure stdlib, read-only analytics, atomic writes.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any
from spa_core.utils.atomic import atomic_save
from spa_core.utils import clock

__version__ = "1.0.0"
__mp__ = "MP-952"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "aggregator_fee_log.json"
)
LOG_CAP = 100

FEE_LABELS = {
    "LOW_FEES": "LOW_FEES",
    "MODERATE": "MODERATE",
    "HIGH": "HIGH",
    "VERY_HIGH": "VERY_HIGH",
    "EXTRACTIVE": "EXTRACTIVE",
}

# Fee drag thresholds (as % of gross APY)
_DRAG_THRESHOLDS = [
    (10.0, "LOW_FEES"),
    (25.0, "MODERATE"),
    (40.0, "HIGH"),
    (50.0, "VERY_HIGH"),
    (math.inf, "EXTRACTIVE"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp + os.replace."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    atomic_save(data, str(path))
def _load_log(path: str) -> list:
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _append_log(path: str, entry: dict, cap: int) -> None:
    log = _load_log(path)
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]
    _atomic_write(path, log)


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def _compute_fee_drag(agg: dict) -> dict:
    """
    Compute total fee drag (% APY) for one aggregator.

    Components:
      - performance_fee contribution: performance_fee_pct * gross_apy_pct / 100
      - management_fee_pct: directly reduces APY (management fee on AUM ≈ annual %)
      - withdrawal_fee_pct: amortised over default 365-day holding
      - deposit_fee_pct:    amortised over default 365-day holding
    """
    gross = float(agg.get("gross_apy_pct", 0.0))
    perf_fee_pct = float(agg.get("performance_fee_pct", 0.0))   # % of profit
    mgmt_fee_pct = float(agg.get("management_fee_pct", 0.0))    # % AUM/year
    withdrawal_fee = float(agg.get("withdrawal_fee_pct", 0.0))  # one-time %
    deposit_fee = float(agg.get("deposit_fee_pct", 0.0))        # one-time %
    underlying_fee = float(agg.get("underlying_protocol_fee_pct", 0.0))

    # Performance fee drag on APY
    perf_drag = gross * perf_fee_pct / 100.0

    # Management fee is already in APY %
    mgmt_drag = mgmt_fee_pct

    # One-time fees amortised over 365 days
    withdrawal_drag = withdrawal_fee * 365.0 / 365.0  # = withdrawal_fee (annualised)
    deposit_drag = deposit_fee * 365.0 / 365.0

    # Underlying protocol fee drag on APY (like an additional management fee)
    underlying_drag = underlying_fee

    total_drag = perf_drag + mgmt_drag + withdrawal_drag + deposit_drag + underlying_drag
    return {
        "perf_drag": perf_drag,
        "mgmt_drag": mgmt_drag,
        "withdrawal_drag": withdrawal_drag,
        "deposit_drag": deposit_drag,
        "underlying_drag": underlying_drag,
        "total_fee_drag_pct": total_drag,
    }


def _fee_label(drag_pct_of_gross: float) -> str:
    """Return fee label based on drag as % of gross APY."""
    for threshold, label in _DRAG_THRESHOLDS:
        if drag_pct_of_gross < threshold:
            return label
    return "EXTRACTIVE"


def _break_even_days(
    gross_apy: float,
    total_drag: float,
    deposit_fee: float,
    withdrawal_fee: float,
) -> float:
    """
    Days until cumulative net yield covers upfront fees (deposit + withdrawal).
    Net daily rate = (gross_apy - total_drag) / 365.
    Break-even = upfront_fee_cost / net_daily_rate.
    Returns inf if net APY <= 0 or no upfront costs.
    """
    upfront = deposit_fee + withdrawal_fee
    if upfront <= 0:
        return 0.0
    net_apy = gross_apy - total_drag
    if net_apy <= 0:
        return float("inf")
    net_daily = net_apy / 365.0
    return upfront / net_daily


def _build_aggregator_result(agg: dict) -> dict:
    gross = float(agg.get("gross_apy_pct", 0.0))
    underlying_apy = float(agg.get("underlying_protocol_fee_pct", 0.0))
    # Note: underlying_protocol_fee_pct in spec is fee the underlying charges,
    # NOT the underlying's APY. We approximate underlying_apy as gross minus drag
    # from aggregator's own fees only (ex underlying).
    perf_fee_pct = float(agg.get("performance_fee_pct", 0.0))
    mgmt_fee_pct = float(agg.get("management_fee_pct", 0.0))
    withdrawal_fee = float(agg.get("withdrawal_fee_pct", 0.0))
    deposit_fee = float(agg.get("deposit_fee_pct", 0.0))
    harvest_days = float(agg.get("harvest_frequency_days", 1.0))

    drag_info = _compute_fee_drag(agg)
    total_drag = drag_info["total_fee_drag_pct"]

    net_apy = gross - total_drag
    fee_efficiency = (net_apy / gross) if gross > 0 else 0.0
    fee_efficiency = max(0.0, fee_efficiency)

    drag_pct_of_gross = (total_drag / gross * 100.0) if gross > 0 else 0.0

    label = _fee_label(drag_pct_of_gross)

    be_days = _break_even_days(gross, total_drag, deposit_fee, withdrawal_fee)

    # value_add_vs_direct: compare aggregator net_apy to direct underlying_apy
    # We approximate direct_apy = gross * (1 - underlying_protocol_fee_pct/100)
    # but spec says underlying_protocol_fee_pct IS a fee %, so direct_apy ~ gross before aggregator adds value
    # Use gross_apy as proxy for "underlying direct" since aggregator takes gross from protocol
    # and then applies its own fees on top.
    # A simpler interpretation: underlying direct APY = gross (before aggregator fees).
    direct_apy = gross  # what you'd earn going direct (before aggregator fees)
    value_add = net_apy - direct_apy  # negative means aggregator adds cost vs going direct

    # Flags
    flags = []
    if perf_fee_pct > 20.0:
        flags.append("PERFORMANCE_FEE_HEAVY")
    if mgmt_fee_pct > 2.0:
        flags.append("MANAGEMENT_FEE_HIGH")
    if net_apy > direct_apy:
        flags.append("ADDS_VALUE")
    if total_drag > gross * 0.5 and gross > 0:
        flags.append("EXTRACTIVE_FEES")
    if harvest_days < 7:
        flags.append("FREQUENT_HARVEST")

    return {
        "name": agg.get("name", ""),
        "strategy_name": agg.get("strategy_name", ""),
        "gross_apy_pct": gross,
        "total_fee_drag_pct": round(total_drag, 6),
        "net_apy_pct": round(net_apy, 6),
        "fee_efficiency_ratio": round(fee_efficiency, 6),
        "break_even_holding_days": round(be_days, 2) if be_days != float("inf") else None,
        "value_add_vs_direct": round(value_add, 6),
        "fee_label": label,
        "flags": flags,
        "fee_breakdown": {
            "perf_drag_pct": round(drag_info["perf_drag"], 6),
            "mgmt_drag_pct": round(drag_info["mgmt_drag"], 6),
            "withdrawal_drag_pct": round(drag_info["withdrawal_drag"], 6),
            "deposit_drag_pct": round(drag_info["deposit_drag"], 6),
            "underlying_drag_pct": round(drag_info["underlying_drag"], 6),
        },
    }


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiYieldAggregatorFeeAnalyzer:
    """
    Analyzes fee structures of DeFi yield aggregators.

    analyze() accepts a list of aggregator dicts and a config dict,
    returns detailed fee analysis per aggregator plus aggregated stats.
    """

    def __init__(self, log_path: str | None = None, log_cap: int = LOG_CAP):
        self._log_path = log_path or LOG_PATH
        self._log_cap = log_cap

    # ------------------------------------------------------------------
    def analyze(self, aggregators: list[dict], config: dict | None = None) -> dict:
        """
        Analyze fee structures and yield impact for each aggregator.

        Parameters
        ----------
        aggregators : list[dict]
            Each dict must include the fields described in the module docstring.
        config : dict, optional
            Currently unused; reserved for future thresholds/overrides.

        Returns
        -------
        dict
            {
              "aggregators": [...],      # per-aggregator results
              "aggregates": {...},       # cross-aggregator stats
              "analysis_timestamp": str,
            }
        """
        if config is None:
            config = {}

        results = []
        for agg in aggregators:
            results.append(_build_aggregator_result(agg))

        aggregates = self._compute_aggregates(results)

        output = {
            "aggregators": results,
            "aggregates": aggregates,
            "analysis_timestamp": clock.utcnow().isoformat() + "Z",
            "module": __mp__,
            "version": __version__,
        }

        # Append to ring-buffer log
        log_entry = {
            "ts": output["analysis_timestamp"],
            "count": len(results),
            "average_net_apy": aggregates.get("average_net_apy"),
            "average_fee_drag": aggregates.get("average_fee_drag"),
        }
        try:
            _append_log(self._log_path, log_entry, self._log_cap)
        except Exception:
            pass  # never crash analysis due to log I/O

        return output

    # ------------------------------------------------------------------
    @staticmethod
    def _compute_aggregates(results: list[dict]) -> dict:
        if not results:
            return {
                "lowest_fee_aggregator": None,
                "highest_fee_aggregator": None,
                "average_net_apy": None,
                "average_fee_drag": None,
                "adds_value_count": 0,
                "total_count": 0,
            }

        sorted_by_drag = sorted(results, key=lambda r: r["total_fee_drag_pct"])
        lowest = sorted_by_drag[0]["name"]
        highest = sorted_by_drag[-1]["name"]

        net_apys = [r["net_apy_pct"] for r in results]
        drags = [r["total_fee_drag_pct"] for r in results]
        avg_net = sum(net_apys) / len(net_apys)
        avg_drag = sum(drags) / len(drags)

        adds_value = sum(1 for r in results if "ADDS_VALUE" in r["flags"])

        return {
            "lowest_fee_aggregator": lowest,
            "highest_fee_aggregator": highest,
            "average_net_apy": round(avg_net, 6),
            "average_fee_drag": round(avg_drag, 6),
            "adds_value_count": adds_value,
            "total_count": len(results),
        }
