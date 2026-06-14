"""
MP-750: YieldRunwayEstimator
Estimates how long a yield strategy can sustain a target withdrawal rate.
Advisory/read-only. Pure stdlib. Atomic JSON writes via tmp+os.replace.
Ring-buffer cap 100 entries.
"""

import json
import math
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional

# ---------------------------------------------------------------------------
# Default data file
# ---------------------------------------------------------------------------
_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_runway_log.json"
)
_DEFAULT_DATA_FILE = os.path.normpath(_DEFAULT_DATA_FILE)

_RING_BUFFER_CAP = 100


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RunwayEstimate:
    strategy_name: str
    initial_capital_usd: float
    annual_yield_pct: float
    monthly_withdrawal_usd: float

    # Computed
    monthly_yield_pct: float = 0.0        # annual_yield_pct / 12
    monthly_yield_usd: float = 0.0        # initial_capital * monthly_yield_pct / 100
    net_monthly_change_usd: float = 0.0   # monthly_yield_usd - monthly_withdrawal_usd

    # Runway
    runway_months: float = 0.0            # float("inf") if sustainable
    runway_years: float = 0.0

    is_sustainable: bool = False

    # Sustainability ratio
    coverage_ratio: float = 0.0           # monthly_yield / monthly_withdrawal (inf if withdrawal=0)

    # Capital at milestones
    capital_at_6m_usd: float = 0.0
    capital_at_12m_usd: float = 0.0
    capital_at_24m_usd: float = 0.0

    # Withdrawal rate
    withdrawal_rate_pct: float = 0.0      # monthly_withdrawal / initial_capital * 100

    # Alert
    alert_level: str = "SUSTAINABLE"
    recommendation: str = ""


@dataclass
class RunwayResult:
    estimates: List[RunwayEstimate] = field(default_factory=list)

    sustainable_strategies: List[str] = field(default_factory=list)
    critical_strategies: List[str] = field(default_factory=list)

    longest_runway_strategy: str = ""
    shortest_runway_strategy: str = ""

    avg_coverage_ratio: float = 0.0

    recommendation_summary: str = ""
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core computation helpers
# ---------------------------------------------------------------------------

def compute_runway(initial_capital: float, annual_yield_pct: float,
                   monthly_withdrawal: float) -> float:
    """Return months until capital is depleted (float('inf') if sustainable)."""
    if monthly_withdrawal <= 0:
        return float("inf")

    monthly_yield_rate = annual_yield_pct / 100.0 / 12.0
    cap = initial_capital
    months = 0
    while cap > 0 and months < 1200:
        cap = cap * (1.0 + monthly_yield_rate) - monthly_withdrawal
        months += 1

    if months >= 1200 and cap > 0:
        return float("inf")
    return float(months)


def simulate_capital(initial: float, annual_yield_pct: float,
                     monthly_withdrawal: float, n_months: int) -> float:
    """Simulate n_months of compounding + withdrawals. Returns capital (≥0)."""
    if n_months <= 0:
        return initial
    monthly_yield_rate = annual_yield_pct / 100.0 / 12.0
    cap = initial
    for _ in range(n_months):
        cap = cap * (1.0 + monthly_yield_rate) - monthly_withdrawal
        if cap < 0:
            cap = 0.0
            break
    return cap


def _alert_level(runway_months: float, is_sustainable: bool) -> str:
    if is_sustainable or runway_months >= 36:
        return "SUSTAINABLE"
    if runway_months >= 12:
        return "CAUTION"
    if runway_months >= 6:
        return "CRITICAL"
    return "DEPLETING"


def _recommendation(alert: str) -> str:
    if alert == "SUSTAINABLE":
        return "Yield covers withdrawals. Strategy is self-sustaining."
    if alert == "CAUTION":
        return "Runway between 12-36 months. Consider increasing yield or reducing withdrawals."
    if alert == "CRITICAL":
        return "Runway 6-12 months. Urgent action required to avoid capital depletion."
    return "Runway under 6 months. Capital depleting rapidly. Stop or drastically reduce withdrawals immediately."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def estimate_runway(strategy_name: str, initial_capital: float,
                    annual_yield_pct: float, monthly_withdrawal: float) -> RunwayEstimate:
    """Compute a full RunwayEstimate for a single strategy."""
    monthly_yield_pct = annual_yield_pct / 12.0
    monthly_yield_usd = initial_capital * monthly_yield_pct / 100.0
    net_monthly_change_usd = monthly_yield_usd - monthly_withdrawal

    is_sustainable = monthly_yield_usd >= monthly_withdrawal

    runway_months = compute_runway(initial_capital, annual_yield_pct, monthly_withdrawal)
    runway_years = (runway_months / 12.0) if runway_months != float("inf") else float("inf")

    if monthly_withdrawal > 0:
        coverage_ratio = monthly_yield_usd / monthly_withdrawal
    else:
        coverage_ratio = float("inf")

    capital_at_6m = simulate_capital(initial_capital, annual_yield_pct, monthly_withdrawal, 6)
    capital_at_12m = simulate_capital(initial_capital, annual_yield_pct, monthly_withdrawal, 12)
    capital_at_24m = simulate_capital(initial_capital, annual_yield_pct, monthly_withdrawal, 24)

    withdrawal_rate_pct = (monthly_withdrawal / initial_capital * 100.0) if initial_capital > 0 else 0.0

    alert = _alert_level(runway_months, is_sustainable)
    rec = _recommendation(alert)

    return RunwayEstimate(
        strategy_name=strategy_name,
        initial_capital_usd=initial_capital,
        annual_yield_pct=annual_yield_pct,
        monthly_withdrawal_usd=monthly_withdrawal,
        monthly_yield_pct=monthly_yield_pct,
        monthly_yield_usd=monthly_yield_usd,
        net_monthly_change_usd=net_monthly_change_usd,
        runway_months=runway_months,
        runway_years=runway_years,
        is_sustainable=is_sustainable,
        coverage_ratio=coverage_ratio,
        capital_at_6m_usd=capital_at_6m,
        capital_at_12m_usd=capital_at_12m,
        capital_at_24m_usd=capital_at_24m,
        withdrawal_rate_pct=withdrawal_rate_pct,
        alert_level=alert,
        recommendation=rec,
    )


def estimate_portfolio(strategies_data: List[dict]) -> RunwayResult:
    """
    Compute RunwayEstimate for each strategy dict and aggregate into RunwayResult.
    Each dict: {strategy_name, initial_capital_usd, annual_yield_pct, monthly_withdrawal_usd}
    """
    estimates = []
    for s in strategies_data:
        est = estimate_runway(
            strategy_name=s["strategy_name"],
            initial_capital=s["initial_capital_usd"],
            annual_yield_pct=s["annual_yield_pct"],
            monthly_withdrawal=s["monthly_withdrawal_usd"],
        )
        estimates.append(est)

    sustainable = [e.strategy_name for e in estimates if e.is_sustainable]
    critical = [e.strategy_name for e in estimates
                if e.alert_level in ("CRITICAL", "DEPLETING")]

    # Longest/shortest runway (inf counts as largest)
    if estimates:
        longest = max(estimates, key=lambda e: e.runway_months if e.runway_months != float("inf") else 1e18)
        shortest = min(estimates, key=lambda e: e.runway_months if e.runway_months != float("inf") else 1e18)
        longest_name = longest.strategy_name
        shortest_name = shortest.strategy_name
    else:
        longest_name = ""
        shortest_name = ""

    # avg coverage ratio — cap inf at 999
    if estimates:
        ratios = [min(e.coverage_ratio, 999.0) if e.coverage_ratio != float("inf") else 999.0
                  for e in estimates]
        avg_cov = sum(ratios) / len(ratios)
    else:
        avg_cov = 0.0

    # Summary recommendation
    if not estimates:
        summary = "No strategies provided."
    elif len(sustainable) == len(estimates):
        summary = "All strategies are sustainable. Yield covers all withdrawals."
    elif critical:
        summary = f"{len(critical)} strategy(s) critically close to depletion. Immediate review required."
    else:
        summary = f"{len(sustainable)}/{len(estimates)} strategies sustainable. Monitor non-sustainable strategies."

    return RunwayResult(
        estimates=estimates,
        sustainable_strategies=sustainable,
        critical_strategies=critical,
        longest_runway_strategy=longest_name,
        shortest_runway_strategy=shortest_name,
        avg_coverage_ratio=avg_cov,
        recommendation_summary=summary,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence (ring-buffer 100)
# ---------------------------------------------------------------------------

def _serialize_estimate(e: RunwayEstimate) -> dict:
    d = asdict(e)
    # Convert inf to a sentinel for JSON serialisation
    for k, v in d.items():
        if isinstance(v, float) and math.isinf(v):
            d[k] = None  # JSON null represents inf
    return d


def _serialize_result(result: RunwayResult) -> dict:
    out = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "estimates": [_serialize_estimate(e) for e in result.estimates],
        "sustainable_strategies": result.sustainable_strategies,
        "critical_strategies": result.critical_strategies,
        "longest_runway_strategy": result.longest_runway_strategy,
        "shortest_runway_strategy": result.shortest_runway_strategy,
        "avg_coverage_ratio": result.avg_coverage_ratio,
        "recommendation_summary": result.recommendation_summary,
        "saved_to": result.saved_to,
    }
    return out


def load_history(data_file: Optional[str] = None) -> list:
    path = data_file or _DEFAULT_DATA_FILE
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return []


def save_results(result: RunwayResult, data_file: Optional[str] = None) -> str:
    """Append result to ring-buffer log (cap 100). Returns file path."""
    path = data_file or _DEFAULT_DATA_FILE
    history = load_history(path)

    entry = _serialize_result(result)
    history.append(entry)

    # Ring-buffer cap
    if len(history) > _RING_BUFFER_CAP:
        history = history[-_RING_BUFFER_CAP:]

    os.makedirs(os.path.dirname(path), exist_ok=True)

    # Atomic write
    dir_name = os.path.dirname(path)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=dir_name, delete=False, suffix=".tmp"
    ) as tf:
        json.dump(history, tf, indent=2)
        tmp_path = tf.name

    os.replace(tmp_path, path)
    return path


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _demo() -> None:
    strategies = [
        {
            "strategy_name": "Aave-Conservative",
            "initial_capital_usd": 100_000,
            "annual_yield_pct": 4.0,
            "monthly_withdrawal_usd": 200,
        },
        {
            "strategy_name": "Morpho-Aggressive",
            "initial_capital_usd": 50_000,
            "annual_yield_pct": 6.5,
            "monthly_withdrawal_usd": 1_000,
        },
        {
            "strategy_name": "Overdrawn",
            "initial_capital_usd": 10_000,
            "annual_yield_pct": 2.0,
            "monthly_withdrawal_usd": 500,
        },
    ]
    result = estimate_portfolio(strategies)
    saved = save_results(result)
    result.saved_to = saved
    print("=== YieldRunwayEstimator Demo ===")
    for e in result.estimates:
        rm = f"{e.runway_months:.1f}" if e.runway_months != float("inf") else "∞"
        print(f"  {e.strategy_name}: {e.alert_level}  runway={rm}m  coverage={e.coverage_ratio:.2f}x")
    print(f"Saved to: {saved}")


if __name__ == "__main__":
    _demo()
