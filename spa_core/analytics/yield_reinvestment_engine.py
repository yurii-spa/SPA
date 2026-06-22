"""
MP-735: YieldReinvestmentEngine
Calculates optimal yield reinvestment schedules — how frequently to harvest
and reinvest yield to maximize compound growth — accounting for gas costs
and minimum harvest thresholds.
Advisory/read-only. Pure stdlib. Atomic JSON writes.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, List

# ── Data directory ────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_DATA_DIR = os.path.join(_REPO_ROOT, "data")
_LOG_FILE = os.path.join(_DATA_DIR, "reinvestment_log.json")

_RING_BUFFER_CAP = 100

# Harvest frequencies
FREQUENCIES: Dict[str, int] = {
    "DAILY": 365,
    "WEEKLY": 52,
    "MONTHLY": 12,
    "QUARTERLY": 4,
}

_GAS_EFFICIENCY_THRESHOLD = 0.05  # gas < 5% of gross yield


# ── Core dataclasses ──────────────────────────────────────────────────────────

@dataclass
class ReinvestmentSchedule:
    position_name: str
    principal_usd: float
    apy: float

    frequency_label: str
    periods_per_year: int

    gas_cost_per_harvest_usd: float
    annual_gas_cost_usd: float

    effective_apy: float
    compounded_value_1y: float
    net_compounded_value_1y: float
    net_gain_usd: float

    simple_interest_gain: float
    compounding_benefit_usd: float

    is_gas_efficient: bool

    recommendation: str


@dataclass
class ReinvestmentOptimizationResult:
    position_name: str
    principal_usd: float
    apy: float

    schedules: List[ReinvestmentSchedule]
    optimal_schedule: ReinvestmentSchedule

    min_principal_for_daily: float

    summary: str
    saved_to: str


# ── Core logic ────────────────────────────────────────────────────────────────

def compound_value(principal: float, apy_pct: float, periods_per_year: int) -> float:
    """
    Compute compounded value after 1 year.
    principal * (1 + apy_pct/100/periods_per_year) ** periods_per_year
    """
    if periods_per_year <= 0:
        raise ValueError(f"periods_per_year must be > 0, got {periods_per_year}")
    rate_per_period = apy_pct / 100.0 / periods_per_year
    return principal * (1.0 + rate_per_period) ** periods_per_year


def compute_schedule(
    position_name: str,
    principal: float,
    apy: float,
    frequency_label: str,
    gas_cost_usd: float,
) -> ReinvestmentSchedule:
    """Compute a reinvestment schedule for a given frequency."""
    if frequency_label not in FREQUENCIES:
        raise ValueError(
            f"Unknown frequency '{frequency_label}'. "
            f"Valid: {list(FREQUENCIES.keys())}"
        )

    periods = FREQUENCIES[frequency_label]
    annual_gas = gas_cost_usd * periods

    compounded = compound_value(principal, apy, periods)
    net_compounded = compounded - annual_gas
    net_gain = net_compounded - principal

    simple_interest_gain = principal * apy / 100.0
    compounding_benefit = net_gain - simple_interest_gain

    gross_yield = compounded - principal
    is_gas_efficient = annual_gas < _GAS_EFFICIENCY_THRESHOLD * gross_yield if gross_yield > 0 else False

    effective_apy = (net_compounded / principal - 1.0) * 100.0 if principal > 0 else 0.0

    if is_gas_efficient:
        recommendation = (
            f"Harvest {frequency_label}: effective APY {effective_apy:.2f}%. "
            f"Compounding adds ${compounding_benefit:.2f}/yr over simple interest."
        )
    else:
        recommendation = (
            "Gas costs outweigh compounding benefit at this frequency. "
            "Harvest less often."
        )

    return ReinvestmentSchedule(
        position_name=position_name,
        principal_usd=principal,
        apy=apy,
        frequency_label=frequency_label,
        periods_per_year=periods,
        gas_cost_per_harvest_usd=gas_cost_usd,
        annual_gas_cost_usd=annual_gas,
        effective_apy=effective_apy,
        compounded_value_1y=compounded,
        net_compounded_value_1y=net_compounded,
        net_gain_usd=net_gain,
        simple_interest_gain=simple_interest_gain,
        compounding_benefit_usd=compounding_benefit,
        is_gas_efficient=is_gas_efficient,
        recommendation=recommendation,
    )


def optimize(
    position_name: str,
    principal: float,
    apy: float,
    gas_cost_usd: float,
) -> ReinvestmentOptimizationResult:
    """
    Compute reinvestment schedules for all 4 frequencies and select the optimal one.
    """
    schedules = [
        compute_schedule(position_name, principal, apy, label, gas_cost_usd)
        for label in FREQUENCIES
    ]

    optimal = max(schedules, key=lambda s: s.net_gain_usd)

    # min_principal for daily to be gas-efficient:
    # annual_gas < 5% * gross_yield  =>  gas*365 < 0.05 * principal*(apy/100)
    # principal > gas*365 / (0.05 * apy/100)  = gas*365*100*20 / apy
    if apy > 0:
        min_principal_for_daily = (gas_cost_usd * 365) / (apy / 100) * 20
    else:
        min_principal_for_daily = float("inf")

    summary = (
        f"Optimal: {optimal.frequency_label} harvesting. "
        f"Net gain: ${optimal.net_gain_usd:.2f}/yr. "
        f"vs Simple interest gain: ${optimal.simple_interest_gain:.2f}/yr."
    )

    return ReinvestmentOptimizationResult(
        position_name=position_name,
        principal_usd=principal,
        apy=apy,
        schedules=schedules,
        optimal_schedule=optimal,
        min_principal_for_daily=min_principal_for_daily,
        summary=summary,
        saved_to="",
    )


def compare_positions(
    positions_data: List[dict],
    gas_cost_usd: float,
) -> Dict[str, ReinvestmentSchedule]:
    """
    Compare multiple positions and return optimal schedule per position.
    positions_data: List[dict] with keys: name, principal, apy
    Returns: {position_name: optimal_schedule}
    """
    result: Dict[str, ReinvestmentSchedule] = {}
    for pos in positions_data:
        opt_result = optimize(
            position_name=pos["name"],
            principal=pos["principal"],
            apy=pos["apy"],
            gas_cost_usd=gas_cost_usd,
        )
        result[pos["name"]] = opt_result.optimal_schedule
    return result


# ── Persistence ───────────────────────────────────────────────────────────────

def _result_to_dict(result: ReinvestmentOptimizationResult) -> dict:
    """Convert result to a JSON-serialisable dict with timestamp."""
    d = asdict(result)
    d["timestamp"] = datetime.now(timezone.utc).isoformat()
    return d


def save_results(
    result: ReinvestmentOptimizationResult,
    log_file: str = _LOG_FILE,
) -> str:
    """Append result to ring-buffer JSON log (max 100 entries). Returns path."""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    history = load_history(log_file)
    entry = _result_to_dict(result)
    history.append(entry)

    if len(history) > _RING_BUFFER_CAP:
        history = history[-_RING_BUFFER_CAP:]

    dir_name = os.path.dirname(log_file)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=dir_name, delete=False, suffix=".tmp"
    ) as tmp:
        json.dump(history, tmp, indent=2, default=str)
        tmp_path = tmp.name

    os.replace(tmp_path, log_file)
    result.saved_to = log_file
    return log_file


def load_history(log_file: str = _LOG_FILE) -> list:
    """Load existing history from log file."""
    if not os.path.exists(log_file):
        return []
    try:
        with open(log_file, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_run() -> None:
    """Quick demo with sample data."""
    result = optimize(
        position_name="Aave USDC",
        principal=100_000,
        apy=5.0,
        gas_cost_usd=10.0,
    )
    print(result.summary)
    print(f"Optimal: {result.optimal_schedule.frequency_label}")
    print(f"Min principal for daily: ${result.min_principal_for_daily:,.0f}")
    for s in result.schedules:
        print(
            f"  {s.frequency_label:10s} net_gain=${s.net_gain_usd:,.2f} "
            f"gas_eff={s.is_gas_efficient}"
        )


if __name__ == "__main__":
    import sys

    if "--run" in sys.argv:
        _demo_run()
    elif "--check" in sys.argv:
        _demo_run()
    else:
        _demo_run()
