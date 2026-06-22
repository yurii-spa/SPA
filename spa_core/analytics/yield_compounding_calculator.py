"""
MP-753: YieldCompoundingCalculator
Advisory/read-only analytics module. Pure stdlib. Atomic JSON writes.

Calculates the effect of different compounding frequencies on final yield.
Shows how often to reinvest for maximum return, computes effective APY from
nominal rates, and finds optimal compounding frequency for given gas costs.
"""

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import List, Dict, Any

# ---------------------------------------------------------------------------
# Data directory
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
_DATA_DIR = os.path.join(_REPO_ROOT, "data")
_LOG_FILE = os.path.join(_DATA_DIR, "yield_compounding_log.json")
_RING_CAP = 100

# Supported compounding frequencies
_FREQUENCIES = {
    "ANNUAL": 1,
    "QUARTERLY": 4,
    "MONTHLY": 12,
    "WEEKLY": 52,
    "DAILY": 365,
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CompoundingScenario:
    protocol: str
    nominal_apy_pct: float
    gas_cost_per_compound_usd: float
    position_size_usd: float

    # Effective APY by frequency
    annual_apy: float
    quarterly_apy: float
    monthly_apy: float
    weekly_apy: float
    daily_apy: float

    # Gas drag by frequency
    annual_gas_drag_pct: float
    quarterly_gas_drag_pct: float
    monthly_gas_drag_pct: float
    weekly_gas_drag_pct: float
    daily_gas_drag_pct: float

    # Net APY (effective - gas_drag, clamped at 0)
    net_annual_apy_pct: float
    net_quarterly_apy_pct: float
    net_monthly_apy_pct: float
    net_weekly_apy_pct: float
    net_daily_apy_pct: float

    # Optimal frequency and gain
    optimal_frequency: str      # ANNUAL | QUARTERLY | MONTHLY | WEEKLY | DAILY
    optimal_net_apy_pct: float
    compounding_gain_pct: float # optimal_net_apy - net_annual_apy (can be negative)

    recommendation: str


@dataclass
class CompoundingResult:
    scenarios: List[CompoundingScenario]
    best_protocol_for_compounding: str
    avg_optimal_net_apy_pct: float
    avg_compounding_gain_pct: float
    recommendation_summary: str
    saved_to: str


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def effective_apy(nominal_pct: float, n_times_per_year: int) -> float:
    """((1 + nominal_pct/100/n)^n - 1) * 100."""
    if n_times_per_year <= 0:
        return 0.0
    nominal_rate = nominal_pct / 100.0
    return ((1.0 + nominal_rate / n_times_per_year) ** n_times_per_year - 1.0) * 100.0


def gas_drag_pct(gas_cost_usd: float,
                  n_times_per_year: int,
                  position_size_usd: float) -> float:
    """gas_cost_usd * n / position_size * 100, or 0 if position_size <= 0."""
    if position_size_usd <= 0:
        return 0.0
    return gas_cost_usd * n_times_per_year / position_size_usd * 100.0


def net_apy(eff_apy: float, gas_drag: float) -> float:
    """max(0.0, effective_apy - gas_drag)."""
    return max(0.0, eff_apy - gas_drag)


def optimal_frequency(net_apys_dict: Dict[str, float]) -> str:
    """Return the frequency label with the highest net APY."""
    return max(net_apys_dict, key=lambda k: net_apys_dict[k])


# ---------------------------------------------------------------------------
# Scenario builder
# ---------------------------------------------------------------------------

def compute_scenario(
    protocol: str,
    nominal_apy_pct: float,
    gas_cost_per_compound_usd: float,
    position_size_usd: float,
) -> CompoundingScenario:
    """Compute full CompoundingScenario for one protocol."""

    # Effective APY per frequency
    ann_apy = effective_apy(nominal_apy_pct, 1)
    qtr_apy = effective_apy(nominal_apy_pct, 4)
    mon_apy = effective_apy(nominal_apy_pct, 12)
    wkl_apy = effective_apy(nominal_apy_pct, 52)
    dly_apy = effective_apy(nominal_apy_pct, 365)

    # Gas drag per frequency
    ann_gas = gas_drag_pct(gas_cost_per_compound_usd, 1, position_size_usd)
    qtr_gas = gas_drag_pct(gas_cost_per_compound_usd, 4, position_size_usd)
    mon_gas = gas_drag_pct(gas_cost_per_compound_usd, 12, position_size_usd)
    wkl_gas = gas_drag_pct(gas_cost_per_compound_usd, 52, position_size_usd)
    dly_gas = gas_drag_pct(gas_cost_per_compound_usd, 365, position_size_usd)

    # Net APY
    net_ann = net_apy(ann_apy, ann_gas)
    net_qtr = net_apy(qtr_apy, qtr_gas)
    net_mon = net_apy(mon_apy, mon_gas)
    net_wkl = net_apy(wkl_apy, wkl_gas)
    net_dly = net_apy(dly_apy, dly_gas)

    net_dict = {
        "ANNUAL": net_ann,
        "QUARTERLY": net_qtr,
        "MONTHLY": net_mon,
        "WEEKLY": net_wkl,
        "DAILY": net_dly,
    }

    opt_freq = optimal_frequency(net_dict)
    opt_net = net_dict[opt_freq]
    gain = opt_net - net_ann  # can be negative

    # Recommendation
    if gain > 1.0:
        rec = f"Frequent compounding adds significant yield. Aim for {opt_freq} schedule."
    elif gain > 0.0:
        rec = f"Compounding beneficial. {opt_freq} frequency recommended."
    else:
        rec = "Gas costs negate compounding benefit. Minimize recompounding frequency."

    return CompoundingScenario(
        protocol=protocol,
        nominal_apy_pct=nominal_apy_pct,
        gas_cost_per_compound_usd=gas_cost_per_compound_usd,
        position_size_usd=position_size_usd,
        annual_apy=ann_apy,
        quarterly_apy=qtr_apy,
        monthly_apy=mon_apy,
        weekly_apy=wkl_apy,
        daily_apy=dly_apy,
        annual_gas_drag_pct=ann_gas,
        quarterly_gas_drag_pct=qtr_gas,
        monthly_gas_drag_pct=mon_gas,
        weekly_gas_drag_pct=wkl_gas,
        daily_gas_drag_pct=dly_gas,
        net_annual_apy_pct=net_ann,
        net_quarterly_apy_pct=net_qtr,
        net_monthly_apy_pct=net_mon,
        net_weekly_apy_pct=net_wkl,
        net_daily_apy_pct=net_dly,
        optimal_frequency=opt_freq,
        optimal_net_apy_pct=opt_net,
        compounding_gain_pct=gain,
        recommendation=rec,
    )


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

def compute_all(scenarios_data: List[Dict[str, Any]]) -> CompoundingResult:
    """
    Compute compounding scenarios for a list of protocols.

    Each entry should have: protocol, nominal_apy_pct,
    gas_cost_per_compound_usd, position_size_usd
    """
    scenarios: List[CompoundingScenario] = []
    for sd in scenarios_data:
        s = compute_scenario(
            protocol=sd["protocol"],
            nominal_apy_pct=float(sd["nominal_apy_pct"]),
            gas_cost_per_compound_usd=float(sd["gas_cost_per_compound_usd"]),
            position_size_usd=float(sd["position_size_usd"]),
        )
        scenarios.append(s)

    if not scenarios:
        return CompoundingResult(
            scenarios=[],
            best_protocol_for_compounding="N/A",
            avg_optimal_net_apy_pct=0.0,
            avg_compounding_gain_pct=0.0,
            recommendation_summary="No scenarios to evaluate.",
            saved_to="",
        )

    best = max(scenarios, key=lambda s: s.optimal_net_apy_pct)
    avg_opt = sum(s.optimal_net_apy_pct for s in scenarios) / len(scenarios)
    avg_gain = sum(s.compounding_gain_pct for s in scenarios) / len(scenarios)

    summary = (
        f"Best protocol: {best.protocol} ({best.optimal_net_apy_pct:.2f}% net APY, "
        f"{best.optimal_frequency} compounding). "
        f"Avg optimal net APY: {avg_opt:.2f}%. Avg compounding gain: {avg_gain:.2f}%."
    )

    return CompoundingResult(
        scenarios=scenarios,
        best_protocol_for_compounding=best.protocol,
        avg_optimal_net_apy_pct=avg_opt,
        avg_compounding_gain_pct=avg_gain,
        recommendation_summary=summary,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence (ring-buffer 100)
# ---------------------------------------------------------------------------

def load_history() -> List[Dict[str, Any]]:
    """Load compounding log from disk."""
    if not os.path.exists(_LOG_FILE):
        return []
    try:
        with open(_LOG_FILE, "r") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _result_to_dict(result: CompoundingResult) -> Dict[str, Any]:
    d = asdict(result)
    d["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return d


def save_results(result: CompoundingResult) -> str:
    """Append result to ring-buffer log (cap 100). Returns path written."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    history = load_history()
    entry = _result_to_dict(result)
    history.append(entry)
    if len(history) > _RING_CAP:
        history = history[-_RING_CAP:]
    tmp = _LOG_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(history, fh, indent=2)
    os.replace(tmp, _LOG_FILE)
    return _LOG_FILE


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_scenarios() -> List[Dict[str, Any]]:
    return [
        {
            "protocol": "Aave V3",
            "nominal_apy_pct": 3.5,
            "gas_cost_per_compound_usd": 5.0,
            "position_size_usd": 10000.0,
        },
        {
            "protocol": "Compound V3",
            "nominal_apy_pct": 4.8,
            "gas_cost_per_compound_usd": 5.0,
            "position_size_usd": 10000.0,
        },
        {
            "protocol": "Morpho Steakhouse",
            "nominal_apy_pct": 6.5,
            "gas_cost_per_compound_usd": 8.0,
            "position_size_usd": 25000.0,
        },
    ]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MP-753 YieldCompoundingCalculator")
    parser.add_argument("--check", action="store_true", help="Compute and print (no write)")
    parser.add_argument("--run", action="store_true", help="Compute + write to data/")
    args = parser.parse_args()

    data = _default_scenarios()
    result = compute_all(data)

    print(f"YieldCompoundingCalculator — {len(result.scenarios)} protocols")
    print(f"  Best: {result.best_protocol_for_compounding}  |  Avg net APY: {result.avg_optimal_net_apy_pct:.2f}%")
    print(f"  Avg compounding gain: {result.avg_compounding_gain_pct:.2f}%")
    for s in result.scenarios:
        print(
            f"  {s.protocol}: optimal={s.optimal_frequency} "
            f"net={s.optimal_net_apy_pct:.2f}% gain={s.compounding_gain_pct:.4f}%"
        )
        print(f"    {s.recommendation}")

    if args.run:
        path = save_results(result)
        print(f"\nSaved → {path}")
    else:
        print("\n(dry-run — use --run to persist)")


if __name__ == "__main__":
    main()
