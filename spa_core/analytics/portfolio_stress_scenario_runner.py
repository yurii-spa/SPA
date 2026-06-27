"""
MP-731: PortfolioStressScenarioRunner
Advisory/read-only module. Pure stdlib. No external deps.

Runs macro stress scenarios across the portfolio to estimate worst-case losses
and identify resilience gaps.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from spa_core.utils import clock

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_DATA_DIR = os.path.join(_REPO_ROOT, "data")
_LOG_FILE = os.path.join(_DATA_DIR, "stress_scenario_log.json")

_RING_BUFFER_CAP = 100

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class StressScenario:
    name: str
    description: str

    # Shocks applied (all in %)
    tvl_shock_pct: float        # % drop in TVL (e.g. -60.0 = TVL drops 60%)
    apy_shock_pct: float        # % change in APY (e.g. -80.0 = APY drops 80%)
    price_shock_pct: float      # % change in collateral prices (e.g. -50.0)
    liquidity_shock_pct: float  # % reduction in exit liquidity (e.g. -70.0)

    # Probability (historical estimate)
    prob_annual: float          # annual probability (e.g. 0.05 = 5% chance/year)
    severity: str               # "MILD" | "MODERATE" | "SEVERE" | "EXTREME"


@dataclass
class PositionStressResult:
    position_name: str
    protocol: str
    initial_value_usd: float
    initial_apy: float
    risk_score: float

    # Per-scenario results {scenario_name: {stressed_value, stressed_apy, loss_usd, loss_pct, can_exit}}
    scenario_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Worst case
    max_loss_usd: float = 0.0
    max_loss_pct: float = 0.0
    worst_scenario: str = ""


@dataclass
class PortfolioStressResult:
    portfolio_id: str
    total_value_usd: float
    scenarios: List[StressScenario]
    position_results: List[PositionStressResult]

    # Portfolio-level stress metrics
    portfolio_scenario_losses: Dict[str, float] = field(default_factory=dict)  # {scenario_name: total_loss_usd}
    worst_scenario_loss_usd: float = 0.0
    worst_scenario_name: str = ""
    worst_scenario_loss_pct: float = 0.0

    # Expected shortfall (CVaR-like): probability-weighted worst losses
    expected_shortfall_usd: float = 0.0

    # Resilience
    resilient_positions_count: int = 0   # positions with max_loss_pct < 20%
    vulnerable_positions_count: int = 0   # positions with max_loss_pct >= 50%

    resilience_score: float = 0.0        # 0–100
    resilience_label: str = ""           # "STRONG" | "ADEQUATE" | "WEAK"

    recommendations: List[str] = field(default_factory=list)
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Pre-built default scenarios
# ---------------------------------------------------------------------------

DEFAULT_SCENARIOS: List[StressScenario] = [
    StressScenario(
        "MARKET_CRASH",
        "40% crypto market crash",
        tvl_shock_pct=-40.0,
        apy_shock_pct=-50.0,
        price_shock_pct=-40.0,
        liquidity_shock_pct=-30.0,
        prob_annual=0.15,
        severity="SEVERE",
    ),
    StressScenario(
        "RATE_SPIKE",
        "Interest rate spike collapses DeFi APYs",
        tvl_shock_pct=-20.0,
        apy_shock_pct=-70.0,
        price_shock_pct=-10.0,
        liquidity_shock_pct=-20.0,
        prob_annual=0.20,
        severity="MODERATE",
    ),
    StressScenario(
        "LIQUIDITY_CRISIS",
        "DeFi liquidity crunch — exits costly",
        tvl_shock_pct=-50.0,
        apy_shock_pct=-30.0,
        price_shock_pct=-20.0,
        liquidity_shock_pct=-80.0,
        prob_annual=0.10,
        severity="SEVERE",
    ),
    StressScenario(
        "DEFI_CONTAGION",
        "Major protocol hack causes contagion",
        tvl_shock_pct=-70.0,
        apy_shock_pct=-90.0,
        price_shock_pct=-30.0,
        liquidity_shock_pct=-60.0,
        prob_annual=0.05,
        severity="EXTREME",
    ),
    StressScenario(
        "STABLECOIN_DEPEG",
        "Major stablecoin loses peg",
        tvl_shock_pct=-30.0,
        apy_shock_pct=-60.0,
        price_shock_pct=-5.0,
        liquidity_shock_pct=-50.0,
        prob_annual=0.08,
        severity="SEVERE",
    ),
]

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def apply_shock(initial_value: float, shock_pct: float) -> float:
    """Apply a percentage shock to an initial value.

    Formula: initial_value * (1 + shock_pct / 100)
    shock_pct is negative for losses (e.g. -40 → 60% of initial).
    """
    return initial_value * (1.0 + shock_pct / 100.0)


def stress_position(
    position: Dict[str, Any],
    scenarios: List[StressScenario],
) -> PositionStressResult:
    """Compute per-scenario stress results for a single position.

    position dict keys: name, protocol, value_usd, apy, risk_score
    """
    name = position["name"]
    protocol = position["protocol"]
    initial_value = float(position["value_usd"])
    initial_apy = float(position["apy"])
    risk_score = float(position.get("risk_score", 0.0))

    scenario_results: Dict[str, Dict[str, Any]] = {}
    max_loss_usd = 0.0
    worst_scenario = ""

    for scenario in scenarios:
        # Price shock drives value change (simplified)
        stressed_value = apply_shock(initial_value, scenario.price_shock_pct)

        # APY shock, floored at 0
        stressed_apy = max(0.0, apply_shock(initial_apy, scenario.apy_shock_pct))

        loss_usd = initial_value - stressed_value
        loss_pct = (loss_usd / initial_value * 100.0) if initial_value != 0 else 0.0

        # can_exit: >30% liquidity remains after shock
        remaining_liquidity_frac = 1.0 + scenario.liquidity_shock_pct / 100.0
        can_exit = remaining_liquidity_frac > 0.3

        scenario_results[scenario.name] = {
            "stressed_value": stressed_value,
            "stressed_apy": stressed_apy,
            "loss_usd": loss_usd,
            "loss_pct": loss_pct,
            "can_exit": can_exit,
        }

        if loss_usd > max_loss_usd:
            max_loss_usd = loss_usd
            worst_scenario = scenario.name

    max_loss_pct = (max_loss_usd / initial_value * 100.0) if initial_value != 0 else 0.0

    return PositionStressResult(
        position_name=name,
        protocol=protocol,
        initial_value_usd=initial_value,
        initial_apy=initial_apy,
        risk_score=risk_score,
        scenario_results=scenario_results,
        max_loss_usd=max_loss_usd,
        max_loss_pct=max_loss_pct,
        worst_scenario=worst_scenario,
    )


def run_stress(
    portfolio_id: str,
    positions: List[Dict[str, Any]],
    scenarios: Optional[List[StressScenario]] = None,
) -> PortfolioStressResult:
    """Run stress scenarios across all positions.

    positions: list of dicts with keys: name, protocol, value_usd, apy, risk_score
    scenarios: list of StressScenario (defaults to DEFAULT_SCENARIOS)
    """
    if scenarios is None:
        scenarios = DEFAULT_SCENARIOS

    total_value = sum(float(p["value_usd"]) for p in positions)

    # Stress each position
    position_results = [stress_position(p, scenarios) for p in positions]

    # Aggregate portfolio-level losses per scenario
    portfolio_scenario_losses: Dict[str, float] = {}
    for scenario in scenarios:
        total_loss = sum(
            pr.scenario_results[scenario.name]["loss_usd"]
            for pr in position_results
            if scenario.name in pr.scenario_results
        )
        portfolio_scenario_losses[scenario.name] = total_loss

    # Worst scenario
    worst_name = ""
    worst_loss = 0.0
    for name, loss in portfolio_scenario_losses.items():
        if loss > worst_loss:
            worst_loss = loss
            worst_name = name

    worst_loss_pct = (worst_loss / total_value * 100.0) if total_value > 0 else 0.0

    # Expected shortfall: probability-weighted average of SEVERE + EXTREME scenario losses
    severe_extreme = [s for s in scenarios if s.severity in ("SEVERE", "EXTREME")]
    if severe_extreme:
        total_prob = sum(s.prob_annual for s in severe_extreme)
        weighted_loss = sum(
            s.prob_annual * portfolio_scenario_losses.get(s.name, 0.0)
            for s in severe_extreme
        )
        expected_shortfall = weighted_loss / total_prob if total_prob > 0 else 0.0
    else:
        expected_shortfall = 0.0

    # Resilience
    total_positions = len(position_results)
    resilient = sum(1 for pr in position_results if pr.max_loss_pct < 20.0)
    vulnerable = sum(1 for pr in position_results if pr.max_loss_pct >= 50.0)

    resilience_score = (resilient / total_positions * 100.0) if total_positions > 0 else 0.0

    if resilience_score >= 70.0:
        resilience_label = "STRONG"
    elif resilience_score >= 40.0:
        resilience_label = "ADEQUATE"
    else:
        resilience_label = "WEAK"

    # Recommendations
    recommendations: List[str] = []

    if vulnerable > 0:
        # Find top vulnerable positions (highest max_loss_pct)
        vuln_positions = sorted(
            [pr for pr in position_results if pr.max_loss_pct >= 50.0],
            key=lambda pr: pr.max_loss_pct,
            reverse=True,
        )
        top_vuln_names = ", ".join(pr.position_name for pr in vuln_positions[:3])
        recommendations.append(
            f"Reduce exposure to {top_vuln_names}"
        )

    if total_value > 0 and expected_shortfall > total_value * 0.3:
        recommendations.append(
            "Portfolio expected shortfall exceeds 30% of value"
        )

    if resilience_score < 40.0:
        recommendations.append(
            "Portfolio lacks stress resilience — diversify across safer protocols"
        )

    return PortfolioStressResult(
        portfolio_id=portfolio_id,
        total_value_usd=total_value,
        scenarios=scenarios,
        position_results=position_results,
        portfolio_scenario_losses=portfolio_scenario_losses,
        worst_scenario_loss_usd=worst_loss,
        worst_scenario_name=worst_name,
        worst_scenario_loss_pct=worst_loss_pct,
        expected_shortfall_usd=expected_shortfall,
        resilient_positions_count=resilient,
        vulnerable_positions_count=vulnerable,
        resilience_score=resilience_score,
        resilience_label=resilience_label,
        recommendations=recommendations,
        saved_to="",
    )


def compare_scenarios(result: PortfolioStressResult) -> Dict[str, float]:
    """Return dict of {scenario_name: total_loss_usd} sorted by loss descending."""
    return dict(
        sorted(
            result.portfolio_scenario_losses.items(),
            key=lambda kv: kv[1],
            reverse=True,
        )
    )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _scenario_to_dict(s: StressScenario) -> dict:
    return {
        "name": s.name,
        "description": s.description,
        "tvl_shock_pct": s.tvl_shock_pct,
        "apy_shock_pct": s.apy_shock_pct,
        "price_shock_pct": s.price_shock_pct,
        "liquidity_shock_pct": s.liquidity_shock_pct,
        "prob_annual": s.prob_annual,
        "severity": s.severity,
    }


def _position_result_to_dict(pr: PositionStressResult) -> dict:
    return {
        "position_name": pr.position_name,
        "protocol": pr.protocol,
        "initial_value_usd": pr.initial_value_usd,
        "initial_apy": pr.initial_apy,
        "risk_score": pr.risk_score,
        "scenario_results": pr.scenario_results,
        "max_loss_usd": pr.max_loss_usd,
        "max_loss_pct": pr.max_loss_pct,
        "worst_scenario": pr.worst_scenario,
    }


def _result_to_dict(result: PortfolioStressResult) -> dict:
    return {
        "portfolio_id": result.portfolio_id,
        "total_value_usd": result.total_value_usd,
        "scenarios": [_scenario_to_dict(s) for s in result.scenarios],
        "position_results": [_position_result_to_dict(pr) for pr in result.position_results],
        "portfolio_scenario_losses": result.portfolio_scenario_losses,
        "worst_scenario_loss_usd": result.worst_scenario_loss_usd,
        "worst_scenario_name": result.worst_scenario_name,
        "worst_scenario_loss_pct": result.worst_scenario_loss_pct,
        "expected_shortfall_usd": result.expected_shortfall_usd,
        "resilient_positions_count": result.resilient_positions_count,
        "vulnerable_positions_count": result.vulnerable_positions_count,
        "resilience_score": result.resilience_score,
        "resilience_label": result.resilience_label,
        "recommendations": result.recommendations,
        "saved_to": result.saved_to,
    }


def save_results(result: PortfolioStressResult, data_dir: str = _DATA_DIR) -> str:
    """Append result to ring-buffer log (cap 100). Returns saved path. Atomic write."""
    os.makedirs(data_dir, exist_ok=True)
    log_file = os.path.join(data_dir, "stress_scenario_log.json")

    # Load existing
    if os.path.exists(log_file):
        try:
            with open(log_file) as f:
                history: list = json.load(f)
        except (json.JSONDecodeError, OSError):
            history = []
    else:
        history = []

    # Append new entry
    entry = _result_to_dict(result)
    entry["_saved_at"] = clock.utcnow().isoformat() + "Z"
    history.append(entry)

    # Ring-buffer cap
    if len(history) > _RING_BUFFER_CAP:
        history = history[-_RING_BUFFER_CAP:]

    # Atomic write
    tmp_file = log_file + ".tmp"
    with open(tmp_file, "w") as f:
        json.dump(history, f, indent=2)
    os.replace(tmp_file, log_file)

    return log_file


def load_history(data_dir: str = _DATA_DIR) -> list:
    """Load all saved results from log."""
    log_file = os.path.join(data_dir, "stress_scenario_log.json")
    if not os.path.exists(log_file):
        return []
    try:
        with open(log_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-731 PortfolioStressScenarioRunner")
    parser.add_argument("--run", action="store_true", help="Compute and save results")
    parser.add_argument("--check", action="store_true", default=True, help="Compute and print (default)")
    parser.add_argument("--data-dir", default=_DATA_DIR)
    args = parser.parse_args()

    # Sample portfolio
    sample_positions = [
        {"name": "Aave USDC", "protocol": "Aave", "value_usd": 40000.0, "apy": 3.5, "risk_score": 2.0},
        {"name": "Compound USDC", "protocol": "Compound", "value_usd": 30000.0, "apy": 4.8, "risk_score": 2.5},
        {"name": "Morpho Steakhouse", "protocol": "Morpho", "value_usd": 20000.0, "apy": 6.5, "risk_score": 3.5},
        {"name": "Cash", "protocol": "USDC", "value_usd": 10000.0, "apy": 0.0, "risk_score": 1.0},
    ]

    result = run_stress("sample_portfolio", sample_positions)

    print(f"Portfolio: {result.portfolio_id}, Total: ${result.total_value_usd:,.0f}")
    print(f"Worst scenario: {result.worst_scenario_name} (${result.worst_scenario_loss_usd:,.0f})")
    print(f"Resilience: {result.resilience_label} ({result.resilience_score:.0f}%)")
    print(f"Expected shortfall: ${result.expected_shortfall_usd:,.0f}")

    if args.run:
        path = save_results(result, data_dir=args.data_dir)
        print(f"Saved to: {path}")
