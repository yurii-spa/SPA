"""
MP-988: DeFiYieldAggregationEfficiencyAnalyzer
Analyzes the efficiency of yield-aggregating vaults (Yearn, Beefy, Convex style).
Pure stdlib — no external dependencies.
"""

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

LOG_CAP = 100
DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "yield_aggregation_efficiency_log.json",
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically using tmp + os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_ = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _compute_compound_boost(
    gross_apy_pct: float,
    harvest_interval_hours: float,
    auto_compound: bool,
) -> float:
    """Annualised gain from auto-compounding vs manual (once-a-year) baseline.

    Formula: effective_apy = (1 + r/n)^n − 1  where n = 8760 / interval_h
    compound_boost_pct = (effective_apy − simple_apy) × 100
    Returns 0 when auto_compound=False or interval ≤ 0.
    """
    if not auto_compound or harvest_interval_hours <= 0:
        return 0.0
    r = gross_apy_pct / 100.0
    n = 8760.0 / harvest_interval_hours
    effective_apy = (1.0 + r / n) ** n - 1.0
    boost = (effective_apy - r) * 100.0
    return max(0.0, boost)


def _compute_gas_cost_annual_pct(
    gas_per_harvest_usd: float,
    harvest_interval_hours: float,
    total_assets_usd: float,
) -> float:
    """Annual gas cost as % of AUM (0.0 if undefined)."""
    if total_assets_usd <= 0 or harvest_interval_hours <= 0:
        return 0.0
    harvests_per_year = 8760.0 / harvest_interval_hours
    annual_gas_usd = gas_per_harvest_usd * harvests_per_year
    return (annual_gas_usd / total_assets_usd) * 100.0


def _compute_capital_utilization_score(
    strategy_utilization_pct: float,
    strategy_count: int,
) -> float:
    """0–100 composite: 70 % from utilisation + 30 % from strategy-count factor."""
    util_score = min(max(strategy_utilization_pct, 0.0), 100.0) * 0.70
    # log-scale: 1 strategy → 0 pts; 10 strategies → 30 pts (max)
    strategy_factor = min(
        math.log1p(max(strategy_count, 0)) / math.log1p(10) * 30.0,
        30.0,
    )
    return round(min(util_score + strategy_factor, 100.0), 4)


def _fee_pct_of_gross(total_fees_pct: float, gross_apy_pct: float) -> float:
    """What fraction of gross APY is consumed by fees, expressed in %."""
    if gross_apy_pct <= 0:
        return 0.0
    return (total_fees_pct / gross_apy_pct) * 100.0


def _compute_efficiency_label(
    value_add_pct: float,
    gross_apy_pct: float,
    total_fees_pct: float,
    net_apy_pct: float,
    underlying_base_apy_pct: float,
) -> str:
    """Classify vault by efficiency tier."""
    if net_apy_pct < underlying_base_apy_pct:
        return "VALUE_DESTROYING"
    fee_drag = _fee_pct_of_gross(total_fees_pct, gross_apy_pct)
    if value_add_pct > 3.0 and fee_drag < 30.0:
        return "HIGHLY_EFFICIENT"
    if value_add_pct > 1.5 and fee_drag < 40.0:
        return "EFFICIENT"
    if value_add_pct >= 0.0 and fee_drag < 50.0:
        return "NEUTRAL"
    return "INEFFICIENT"


def _compute_flags(
    net_apy_pct: float,
    underlying_base_apy_pct: float,
    total_fees_pct: float,
    gross_apy_pct: float,
    compound_boost_pct: float,
    harvest_cost_ratio: float,
    strategy_utilization_pct: float,
) -> list:
    """Return advisory flag strings for a vault."""
    flags = []
    if net_apy_pct < underlying_base_apy_pct:
        flags.append("VALUE_DESTROYING")
    if _fee_pct_of_gross(total_fees_pct, gross_apy_pct) > 40.0:
        flags.append("HIGH_FEE_DRAG")
    if compound_boost_pct > 2.0:
        flags.append("COMPOUND_HEAVY")
    if harvest_cost_ratio > 5.0:
        flags.append("GAS_INTENSIVE")
    if strategy_utilization_pct < 70.0:
        flags.append("UNDER_UTILIZED")
    return flags


# ── main class ─────────────────────────────────────────────────────────────────

class DeFiYieldAggregationEfficiencyAnalyzer:
    """MP-988 — analyses efficiency of yield-aggregating vaults.

    Usage::

        analyzer = DeFiYieldAggregationEfficiencyAnalyzer()
        result = analyzer.analyze(vaults, config)

    ``config`` keys:
      - ``persist`` (bool, default False): append result to ring-buffer log.
    """

    def __init__(self, log_path: str = DEFAULT_LOG_PATH) -> None:
        self.log_path = log_path

    # ── public ─────────────────────────────────────────────────────────────

    def analyze(self, vaults: list, config: dict) -> dict:
        """Analyse each vault and return aggregated efficiency report.

        Required vault keys:
          name, protocol, strategy_count, gross_apy_pct, net_apy_pct,
          management_fee_pct, performance_fee_pct, total_assets_usd,
          harvest_interval_hours, auto_compound, underlying_base_apy_pct,
          gas_per_harvest_usd, slippage_per_harvest_pct,
          strategy_utilization_pct
        """
        persist = bool(config.get("persist", False))
        results = []

        for vault in vaults:
            name = vault.get("name", "unknown")
            protocol = vault.get("protocol", "unknown")
            strategy_count = int(vault.get("strategy_count", 1))
            gross_apy = float(vault.get("gross_apy_pct", 0.0))
            net_apy = float(vault.get("net_apy_pct", 0.0))
            mgmt_fee = float(vault.get("management_fee_pct", 0.0))
            perf_fee = float(vault.get("performance_fee_pct", 0.0))
            total_assets = float(vault.get("total_assets_usd", 0.0))
            harvest_interval = float(vault.get("harvest_interval_hours", 24.0))
            auto_compound = bool(vault.get("auto_compound", False))
            underlying_base_apy = float(vault.get("underlying_base_apy_pct", 0.0))
            gas_per_harvest = float(vault.get("gas_per_harvest_usd", 0.0))
            slippage_per_harvest = float(vault.get("slippage_per_harvest_pct", 0.0))
            strategy_utilization = float(vault.get("strategy_utilization_pct", 100.0))

            total_fees_pct = mgmt_fee + perf_fee
            value_add_pct = net_apy - underlying_base_apy

            fee_efficiency_ratio: Any = None
            if total_fees_pct > 0:
                fee_efficiency_ratio = round(value_add_pct / total_fees_pct, 6)

            compound_boost = _compute_compound_boost(gross_apy, harvest_interval, auto_compound)
            gas_cost_annual_pct = _compute_gas_cost_annual_pct(
                gas_per_harvest, harvest_interval, total_assets
            )
            # harvest_cost_ratio = gas cost as % of gross APY
            harvest_cost_ratio = (
                (gas_cost_annual_pct / gross_apy) * 100.0 if gross_apy > 0 else 0.0
            )
            capital_util_score = _compute_capital_utilization_score(
                strategy_utilization, strategy_count
            )
            efficiency_label = _compute_efficiency_label(
                value_add_pct, gross_apy, total_fees_pct, net_apy, underlying_base_apy
            )
            flags = _compute_flags(
                net_apy, underlying_base_apy, total_fees_pct, gross_apy,
                compound_boost, harvest_cost_ratio, strategy_utilization,
            )

            results.append({
                "name": name,
                "protocol": protocol,
                "strategy_count": strategy_count,
                "gross_apy_pct": gross_apy,
                "net_apy_pct": net_apy,
                "underlying_base_apy_pct": underlying_base_apy,
                "total_fees_pct": round(total_fees_pct, 6),
                "value_add_pct": round(value_add_pct, 6),
                "fee_efficiency_ratio": fee_efficiency_ratio,
                "compound_boost_pct": round(compound_boost, 6),
                "harvest_cost_ratio": round(harvest_cost_ratio, 6),
                "capital_utilization_score": capital_util_score,
                "gas_cost_annual_pct": round(gas_cost_annual_pct, 6),
                "slippage_per_harvest_pct": slippage_per_harvest,
                "efficiency_label": efficiency_label,
                "flags": flags,
            })

        # ── aggregates ─────────────────────────────────────────────────────
        if results:
            sorted_by_va = sorted(results, key=lambda r: r["value_add_pct"], reverse=True)
            most_efficient = sorted_by_va[0]["name"]
            least_efficient = sorted_by_va[-1]["name"]
            avg_value_add = sum(r["value_add_pct"] for r in results) / len(results)
            vd_count = sum(1 for r in results if "VALUE_DESTROYING" in r["flags"])
            valid_fee_eff = [
                r["fee_efficiency_ratio"] for r in results
                if r["fee_efficiency_ratio"] is not None
            ]
            avg_fee_efficiency: Any = (
                sum(valid_fee_eff) / len(valid_fee_eff) if valid_fee_eff else None
            )
        else:
            most_efficient = None
            least_efficient = None
            avg_value_add = 0.0
            vd_count = 0
            avg_fee_efficiency = None

        output = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "vault_count": len(vaults),
            "vaults": results,
            "aggregates": {
                "most_efficient": most_efficient,
                "least_efficient": least_efficient,
                "average_value_add": round(avg_value_add, 6),
                "value_destroying_count": vd_count,
                "average_fee_efficiency": (
                    round(avg_fee_efficiency, 6)
                    if avg_fee_efficiency is not None
                    else None
                ),
            },
        }

        if persist:
            self._append_log(output)

        return output

    # ── private ────────────────────────────────────────────────────────────

    def _append_log(self, entry: dict) -> None:
        """Append entry to ring-buffer log (cap = LOG_CAP), atomic write."""
        try:
            with open(self.log_path, "r", encoding="utf-8") as fh:
                log = json.load(fh)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []
        log.append(entry)
        if len(log) > LOG_CAP:
            log = log[-LOG_CAP:]
        _atomic_write(self.log_path, log)
