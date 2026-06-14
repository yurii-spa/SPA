"""
Portfolio Stress Tester (MP-760)
=================================

Runs predefined stress scenarios against a DeFi portfolio to estimate losses
under adverse market conditions — rate crashes, liquidity crises, token price
collapses. Advisory only, never modifies allocator/risk/execution.

Scenarios: RATE_CRASH_50, RATE_CRASH_80, LIQUIDITY_CRISIS,
           COLLATERAL_DROP_30, COLLATERAL_DROP_50, BLACK_SWAN.

Design constraints:
* Pure stdlib only — no numpy/scipy/requests/pandas.
* Atomic writes: tmp + os.replace (POSIX-safe).
* Advisory / read-only analytics — never modifies allocator/risk/execution.
* Deterministic: identical input → identical output.
* Ring-buffer JSON: MAX_ENTRIES = 100.

CLI:
    python3 -m spa_core.analytics.portfolio_stress_tester --check  (default)
    python3 -m spa_core.analytics.portfolio_stress_tester --run    (+ atomic save)
    python3 -m spa_core.analytics.portfolio_stress_tester --run --data-dir PATH
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_ENTRIES = 100

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "portfolio_stress_log.json"

SCENARIOS: Dict[str, Dict] = {
    "RATE_CRASH_50": {
        "apy_multiplier": 0.5,
        "description": "All yields halved",
    },
    "RATE_CRASH_80": {
        "apy_multiplier": 0.2,
        "description": "Yields drop 80%",
    },
    "LIQUIDITY_CRISIS": {
        "apy_multiplier": 0.3,
        "withdrawal_penalty_pct": 5.0,
        "description": "Liquidity crunch + 5% exit penalty",
    },
    "COLLATERAL_DROP_30": {
        "collateral_multiplier": 0.7,
        "description": "Collateral values drop 30%",
    },
    "COLLATERAL_DROP_50": {
        "collateral_multiplier": 0.5,
        "description": "Collateral values drop 50%",
    },
    "BLACK_SWAN": {
        "apy_multiplier": 0.1,
        "collateral_multiplier": 0.6,
        "withdrawal_penalty_pct": 10.0,
        "description": "Extreme stress: yields near zero + collateral drop + exit penalty",
    },
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    scenario_name: str
    description: str

    # Portfolio state under stress
    base_annual_yield_usd: float        # normal yield
    stressed_annual_yield_usd: float    # yield under scenario
    yield_impact_usd: float             # base - stressed (loss)
    yield_impact_pct: float             # yield_impact / base * 100

    base_portfolio_value_usd: float
    stressed_portfolio_value_usd: float  # after collateral drop + exit penalty
    portfolio_impact_usd: float          # base - stressed
    portfolio_impact_pct: float          # portfolio_impact / base * 100

    severity: str  # MILD | MODERATE | SEVERE | CATASTROPHIC


@dataclass
class StressTestResult:
    portfolio_value_usd: float
    annual_yield_usd: float

    scenario_results: List[ScenarioResult] = field(default_factory=list)

    worst_scenario: str = ""    # highest portfolio_impact_pct
    best_scenario: str = ""     # lowest portfolio_impact_pct

    avg_portfolio_impact_pct: float = 0.0

    # How many scenarios are SEVERE or CATASTROPHIC
    severe_scenario_count: int = 0

    overall_resilience: str = ""   # RESILIENT | MODERATE | FRAGILE
    recommendation_summary: str = ""
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def _classify_severity(portfolio_impact_pct: float) -> str:
    """MILD (<5%) | MODERATE (5-15%) | SEVERE (15-30%) | CATASTROPHIC (>30%)."""
    if portfolio_impact_pct < 5.0:
        return "MILD"
    if portfolio_impact_pct < 15.0:
        return "MODERATE"
    if portfolio_impact_pct <= 30.0:
        return "SEVERE"
    return "CATASTROPHIC"


def run_scenario(
    portfolio_value_usd: float,
    annual_yield_usd: float,
    scenario_name: str,
) -> ScenarioResult:
    """Run a single named stress scenario and return results."""
    if scenario_name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_name!r}")

    params = SCENARIOS[scenario_name]
    description = params["description"]

    apy_multiplier: float = params.get("apy_multiplier", 1.0)
    collateral_multiplier: float = params.get("collateral_multiplier", 1.0)
    withdrawal_penalty_pct: float = params.get("withdrawal_penalty_pct", 0.0)

    # Yield stress
    stressed_yield = annual_yield_usd * apy_multiplier
    yield_impact = annual_yield_usd - stressed_yield
    yield_impact_pct = (yield_impact / annual_yield_usd * 100.0) if annual_yield_usd != 0 else 0.0

    # Portfolio value stress
    stressed_value = portfolio_value_usd * collateral_multiplier * (1.0 - withdrawal_penalty_pct / 100.0)
    portfolio_impact = portfolio_value_usd - stressed_value
    portfolio_impact_pct = (portfolio_impact / portfolio_value_usd * 100.0) if portfolio_value_usd != 0 else 0.0

    severity = _classify_severity(portfolio_impact_pct)

    return ScenarioResult(
        scenario_name=scenario_name,
        description=description,
        base_annual_yield_usd=annual_yield_usd,
        stressed_annual_yield_usd=stressed_yield,
        yield_impact_usd=yield_impact,
        yield_impact_pct=yield_impact_pct,
        base_portfolio_value_usd=portfolio_value_usd,
        stressed_portfolio_value_usd=stressed_value,
        portfolio_impact_usd=portfolio_impact,
        portfolio_impact_pct=portfolio_impact_pct,
        severity=severity,
    )


def run_all_scenarios(
    portfolio_value_usd: float,
    annual_yield_usd: float,
) -> StressTestResult:
    """Run all 6 predefined scenarios and summarise."""
    results: List[ScenarioResult] = []
    for name in SCENARIOS:
        results.append(run_scenario(portfolio_value_usd, annual_yield_usd, name))

    # Worst / best by portfolio_impact_pct
    worst = max(results, key=lambda r: r.portfolio_impact_pct)
    best = min(results, key=lambda r: r.portfolio_impact_pct)

    avg_impact = sum(r.portfolio_impact_pct for r in results) / len(results)

    severe_count = sum(1 for r in results if r.severity in ("SEVERE", "CATASTROPHIC"))

    # Overall resilience
    if avg_impact < 10.0:
        resilience = "RESILIENT"
        recommendation = "Portfolio resilient to stress scenarios."
    elif avg_impact < 25.0:
        resilience = "MODERATE"
        recommendation = "Moderate resilience. Consider scenario hedging."
    else:
        resilience = "FRAGILE"
        recommendation = "Portfolio is fragile. Reduce leverage and improve liquidity buffers."

    return StressTestResult(
        portfolio_value_usd=portfolio_value_usd,
        annual_yield_usd=annual_yield_usd,
        scenario_results=results,
        worst_scenario=worst.scenario_name,
        best_scenario=best.scenario_name,
        avg_portfolio_impact_pct=avg_impact,
        severe_scenario_count=severe_count,
        overall_resilience=resilience,
        recommendation_summary=recommendation,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: object) -> None:
    """Write JSON atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _result_to_dict(result: StressTestResult) -> dict:
    scenarios = []
    for sr in result.scenario_results:
        scenarios.append({
            "scenario_name": sr.scenario_name,
            "description": sr.description,
            "base_annual_yield_usd": sr.base_annual_yield_usd,
            "stressed_annual_yield_usd": sr.stressed_annual_yield_usd,
            "yield_impact_usd": sr.yield_impact_usd,
            "yield_impact_pct": sr.yield_impact_pct,
            "base_portfolio_value_usd": sr.base_portfolio_value_usd,
            "stressed_portfolio_value_usd": sr.stressed_portfolio_value_usd,
            "portfolio_impact_usd": sr.portfolio_impact_usd,
            "portfolio_impact_pct": sr.portfolio_impact_pct,
            "severity": sr.severity,
        })
    return {
        "portfolio_value_usd": result.portfolio_value_usd,
        "annual_yield_usd": result.annual_yield_usd,
        "scenario_results": scenarios,
        "worst_scenario": result.worst_scenario,
        "best_scenario": result.best_scenario,
        "avg_portfolio_impact_pct": result.avg_portfolio_impact_pct,
        "severe_scenario_count": result.severe_scenario_count,
        "overall_resilience": result.overall_resilience,
        "recommendation_summary": result.recommendation_summary,
        "saved_to": result.saved_to,
    }


def save_results(result: StressTestResult, data_dir: Optional[Path] = None) -> StressTestResult:
    """Append result to ring-buffer JSON (cap MAX_ENTRIES). Returns updated result."""
    path = (data_dir / DATA_FILE.name) if data_dir else DATA_FILE
    existing: list = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    entry = _result_to_dict(result)
    entry["saved_to"] = str(path)
    existing.append(entry)
    # Ring-buffer
    if len(existing) > MAX_ENTRIES:
        existing = existing[-MAX_ENTRIES:]

    _atomic_write(path, existing)
    result.saved_to = str(path)
    return result


def load_history(data_dir: Optional[Path] = None) -> list:
    """Load saved stress test history."""
    path = (data_dir / DATA_FILE.name) if data_dir else DATA_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _demo_portfolio() -> tuple:
    """Return (portfolio_value_usd, annual_yield_usd) for demo run."""
    return 100_000.0, 6_000.0   # $100k portfolio, ~6% APY


def _print_result(result: StressTestResult) -> None:
    print(f"\n{'='*60}")
    print("PORTFOLIO STRESS TEST — MP-760")
    print(f"{'='*60}")
    print(f"Portfolio value : ${result.portfolio_value_usd:,.2f}")
    print(f"Annual yield    : ${result.annual_yield_usd:,.2f}")
    print(f"\n{'Scenario':<22} {'Sev':<14} {'Portfolio loss':<16} {'Yield loss'}")
    print("-" * 70)
    for sr in result.scenario_results:
        print(
            f"{sr.scenario_name:<22} {sr.severity:<14} "
            f"{sr.portfolio_impact_pct:>6.1f}%          "
            f"{sr.yield_impact_pct:>6.1f}%"
        )
    print("-" * 70)
    print(f"\nWorst scenario : {result.worst_scenario}")
    print(f"Best scenario  : {result.best_scenario}")
    print(f"Avg impact     : {result.avg_portfolio_impact_pct:.1f}%")
    print(f"Severe count   : {result.severe_scenario_count}")
    print(f"Resilience     : {result.overall_resilience}")
    print(f"Recommendation : {result.recommendation_summary}")
    if result.saved_to:
        print(f"\nSaved to: {result.saved_to}")


def main(argv: Optional[list] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Portfolio Stress Tester MP-760")
    parser.add_argument("--check", action="store_true", default=False,
                        help="Compute and print without saving (default)")
    parser.add_argument("--run", action="store_true", default=False,
                        help="Compute and save to data file")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Override data directory")
    args = parser.parse_args(argv)

    portfolio_value, annual_yield = _demo_portfolio()

    # Try to load real portfolio data
    data_dir = Path(args.data_dir) if args.data_dir else None
    base_dir = data_dir or DATA_FILE.parent
    positions_file = base_dir / "current_positions.json"
    if positions_file.exists():
        try:
            positions = json.loads(positions_file.read_text(encoding="utf-8"))
            if isinstance(positions, dict):
                portfolio_value = float(positions.get("total_value_usd", portfolio_value))
                annual_yield = float(positions.get("annual_yield_usd", annual_yield))
        except (json.JSONDecodeError, OSError, ValueError, KeyError):
            pass

    result = run_all_scenarios(portfolio_value, annual_yield)
    _print_result(result)

    if args.run:
        result = save_results(result, data_dir=data_dir)
        print(f"\nSaved to: {result.saved_to}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
