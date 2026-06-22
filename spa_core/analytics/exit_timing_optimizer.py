"""
ExitTimingOptimizer (SPA-V597 / MP-720) — advisory / read-only.

Determines the optimal time to exit a DeFi position by modeling future yield
decay, lock period expiry, and opportunity cost versus staying.

Design constraints
------------------
* Pure stdlib only — no numpy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace.
* Ring-buffer cap: 100 entries (data/exit_timing_log.json).
* LLM_FORBIDDEN_AGENTS not applicable (analytics domain).

CLI
---
  python3 -m spa_core.analytics.exit_timing_optimizer --check
  python3 -m spa_core.analytics.exit_timing_optimizer --run
  python3 -m spa_core.analytics.exit_timing_optimizer --run --data-dir PATH
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_LOG_FILENAME = "exit_timing_log.json"
_RING_BUFFER_MAX = 100

# Days at which exit scenarios are modeled (fixed grid)
_SCENARIO_DAYS: List[int] = [0, 7, 14, 30, 60, 90, 180]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ExitScenario:
    exit_day: int
    cumulative_yield_pct: float    # trapezoidal yield accumulated by exit_day
    cumulative_gas_pct: float      # est gas cost (0.05% per rebalance event)
    opportunity_cost_pct: float    # alt_yield - current_yield (can be negative)
    net_gain_pct: float            # yield - gas - max(0, opportunity_cost)
    is_locked: bool                # still within lock period


@dataclass
class ExitTimingReport:
    protocol: str
    pool: str
    current_apy: float
    daily_decay_rate: float        # % of current_apy lost per day
    lock_period_days: int
    days_already_held: int
    alternative_apy: float         # best available alternative

    # Scenarios modeled at days [0, 7, 14, 30, 60, 90, 180]
    scenarios: List[ExitScenario] = field(default_factory=list)

    # Optimal exit (among non-locked scenarios)
    optimal_exit_day: int = 0
    optimal_exit_net_gain_pct: float = 0.0

    # Current state
    remaining_lock_days: int = 0
    should_exit_now: bool = False
    exit_recommendation: str = ""  # EXIT_NOW | EXIT_AFTER_LOCK | HOLD_N_MORE_DAYS | HOLD_LONG_TERM
    recommended_exit_day: int = 0

    warnings: List[str] = field(default_factory=list)
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def model_scenario(
    exit_day: int,
    current_apy: float,
    daily_decay_rate: float,
    lock_period_days: int,
    days_already_held: int,
    alternative_apy: float,
) -> ExitScenario:
    """Model a single exit scenario at *exit_day* days from now.

    Parameters
    ----------
    exit_day : int
        Number of days from now until exit.
    current_apy : float
        Current annualised percentage yield (%).
    daily_decay_rate : float
        Daily APY decay rate expressed as % of current_apy per day.
        E.g. 2.0 means APY falls by 2% of its current value each day.
    lock_period_days : int
        Total lock period of the protocol (days).
    days_already_held : int
        Days the position has already been held.
    alternative_apy : float
        Best available APY in an alternative protocol (%).

    Returns
    -------
    ExitScenario
    """
    # --- APY at exit after compounding decay ---
    effective_apy_at_exit = max(
        0.0,
        current_apy * (1.0 - daily_decay_rate / 100.0) ** exit_day,
    )

    # --- Cumulative yield (trapezoidal approximation) ---
    # Average of start and end APY divided by 365, multiplied by days
    cumulative_yield_pct = (
        (current_apy + effective_apy_at_exit) / 2.0
    ) / 365.0 * exit_day

    # --- Gas cost ---
    # One rebalance event at entry (day 0) plus one per additional 30-day period.
    # gas_events = exit_day // 30 + 1  (always at least 1)
    gas_events = exit_day // 30 + 1
    cumulative_gas_pct = 0.05 * gas_events

    # --- Opportunity cost ---
    # The yield we would have earned in the alternative minus what we earned here.
    # Negative means current position is already better.
    opportunity_cost_pct = (
        alternative_apy / 365.0 * exit_day
    ) - cumulative_yield_pct

    # --- Net gain ---
    # We only penalise for positive opportunity cost (we missed out on something).
    net_gain_pct = (
        cumulative_yield_pct
        - cumulative_gas_pct
        - max(0.0, opportunity_cost_pct)
    )

    # --- Lock check ---
    remaining_lock = max(0, lock_period_days - days_already_held)
    is_locked = exit_day < remaining_lock

    return ExitScenario(
        exit_day=exit_day,
        cumulative_yield_pct=round(cumulative_yield_pct, 8),
        cumulative_gas_pct=round(cumulative_gas_pct, 8),
        opportunity_cost_pct=round(opportunity_cost_pct, 8),
        net_gain_pct=round(net_gain_pct, 8),
        is_locked=is_locked,
    )


def analyze(
    protocol: str,
    pool: str,
    current_apy: float,
    daily_decay_rate: float,
    lock_period_days: int,
    days_already_held: int,
    alternative_apy: float,
) -> ExitTimingReport:
    """Analyze optimal exit timing for a DeFi position.

    Scenarios are modeled at days: [0, 7, 14, 30, 60, 90, 180].
    The optimal exit is chosen from non-locked scenarios (or all if all locked).
    """
    # Build scenarios
    scenarios: List[ExitScenario] = [
        model_scenario(
            d,
            current_apy,
            daily_decay_rate,
            lock_period_days,
            days_already_held,
            alternative_apy,
        )
        for d in _SCENARIO_DAYS
    ]

    remaining_lock_days = max(0, lock_period_days - days_already_held)

    # --- Optimal exit: max net_gain among non-locked scenarios ---
    unlocked = [s for s in scenarios if not s.is_locked]
    if unlocked:
        best = max(unlocked, key=lambda s: s.net_gain_pct)
    else:
        # All scenarios still locked → pick the least-bad option
        best = max(scenarios, key=lambda s: s.net_gain_pct)

    optimal_exit_day = best.exit_day
    optimal_exit_net_gain_pct = best.net_gain_pct

    # --- should_exit_now ---
    scenario_0 = scenarios[0]  # exit_day == 0
    within_5_pct = scenario_0.net_gain_pct >= optimal_exit_net_gain_pct * 0.95
    should_exit_now = remaining_lock_days == 0 and (
        within_5_pct or current_apy < alternative_apy
    )

    # --- exit_recommendation & recommended_exit_day ---
    if should_exit_now:
        exit_recommendation = "EXIT_NOW"
        recommended_exit_day = 0
    elif remaining_lock_days > 0:
        exit_recommendation = "EXIT_AFTER_LOCK"
        recommended_exit_day = remaining_lock_days
    elif optimal_exit_day <= 14:
        exit_recommendation = "HOLD_N_MORE_DAYS"
        recommended_exit_day = optimal_exit_day
    else:
        exit_recommendation = "HOLD_LONG_TERM"
        recommended_exit_day = optimal_exit_day

    # --- warnings ---
    warnings: List[str] = []
    if daily_decay_rate > 3.0:
        warnings.append("rapid APY decay")
    if current_apy > 0 and alternative_apy > current_apy * 1.5:
        warnings.append("much better alternative exists")
    if remaining_lock_days > 60:
        warnings.append("long lock period")

    return ExitTimingReport(
        protocol=protocol,
        pool=pool,
        current_apy=current_apy,
        daily_decay_rate=daily_decay_rate,
        lock_period_days=lock_period_days,
        days_already_held=days_already_held,
        alternative_apy=alternative_apy,
        scenarios=scenarios,
        optimal_exit_day=optimal_exit_day,
        optimal_exit_net_gain_pct=optimal_exit_net_gain_pct,
        remaining_lock_days=remaining_lock_days,
        should_exit_now=should_exit_now,
        exit_recommendation=exit_recommendation,
        recommended_exit_day=recommended_exit_day,
        warnings=warnings,
        saved_to="",
    )


def compare_positions(reports: List[ExitTimingReport]) -> List[ExitTimingReport]:
    """Sort *reports* by optimal_exit_net_gain_pct descending (best first)."""
    return sorted(reports, key=lambda r: r.optimal_exit_net_gain_pct, reverse=True)


# ---------------------------------------------------------------------------
# Persistence (ring-buffer JSON, max 100 entries, atomic write)
# ---------------------------------------------------------------------------

def _scenario_to_dict(s: ExitScenario) -> dict:
    return {
        "exit_day": s.exit_day,
        "cumulative_yield_pct": s.cumulative_yield_pct,
        "cumulative_gas_pct": s.cumulative_gas_pct,
        "opportunity_cost_pct": s.opportunity_cost_pct,
        "net_gain_pct": s.net_gain_pct,
        "is_locked": s.is_locked,
    }


def _report_to_dict(report: ExitTimingReport) -> dict:
    return {
        "protocol": report.protocol,
        "pool": report.pool,
        "current_apy": report.current_apy,
        "daily_decay_rate": report.daily_decay_rate,
        "lock_period_days": report.lock_period_days,
        "days_already_held": report.days_already_held,
        "alternative_apy": report.alternative_apy,
        "scenarios": [_scenario_to_dict(s) for s in report.scenarios],
        "optimal_exit_day": report.optimal_exit_day,
        "optimal_exit_net_gain_pct": report.optimal_exit_net_gain_pct,
        "remaining_lock_days": report.remaining_lock_days,
        "should_exit_now": report.should_exit_now,
        "exit_recommendation": report.exit_recommendation,
        "recommended_exit_day": report.recommended_exit_day,
        "warnings": report.warnings,
        "saved_to": report.saved_to,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def save_results(
    report: ExitTimingReport,
    data_dir: Optional[Path] = None,
) -> str:
    """Persist *report* to the ring-buffer JSON log.  Returns file path."""
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    log_path = data_dir / _LOG_FILENAME

    # Load existing entries
    if log_path.exists():
        try:
            existing: list = json.loads(log_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = []
    else:
        existing = []

    # Append new entry
    existing.append(_report_to_dict(report))

    # Trim to ring-buffer cap
    if len(existing) > _RING_BUFFER_MAX:
        existing = existing[-_RING_BUFFER_MAX:]

    # Atomic write: tmp → os.replace
    atomic_save(existing, str(log_path))
    report.saved_to = str(log_path)
    return str(log_path)


def load_history(data_dir: Optional[Path] = None) -> list:
    """Return all saved exit timing reports from the ring-buffer JSON."""
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    log_path = Path(data_dir) / _LOG_FILENAME
    if not log_path.exists():
        return []
    try:
        return json.loads(log_path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo_report() -> ExitTimingReport:
    """Generate a demo report with illustrative parameters."""
    return analyze(
        protocol="Morpho Steakhouse",
        pool="USDC",
        current_apy=6.5,
        daily_decay_rate=0.5,
        lock_period_days=30,
        days_already_held=10,
        alternative_apy=4.8,
    )


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    run = "--run" in argv
    data_dir_arg: Optional[Path] = None
    if "--data-dir" in argv:
        idx = argv.index("--data-dir")
        if idx + 1 < len(argv):
            data_dir_arg = Path(argv[idx + 1])

    report = _demo_report()

    print(f"ExitTimingOptimizer — {report.protocol} / {report.pool}")
    print(f"  current_apy         : {report.current_apy}%")
    print(f"  daily_decay_rate    : {report.daily_decay_rate}%")
    print(f"  remaining_lock_days : {report.remaining_lock_days}")
    print(f"  optimal_exit_day    : {report.optimal_exit_day}")
    print(f"  optimal_net_gain    : {report.optimal_exit_net_gain_pct:.4f}%")
    print(f"  should_exit_now     : {report.should_exit_now}")
    print(f"  exit_recommendation : {report.exit_recommendation}")
    print(f"  recommended_exit_day: {report.recommended_exit_day}")
    if report.warnings:
        print(f"  warnings            : {', '.join(report.warnings)}")
    print()
    print("  Scenarios:")
    for s in report.scenarios:
        lock_str = " [LOCKED]" if s.is_locked else ""
        print(
            f"    day {s.exit_day:3d}{lock_str}: "
            f"yield={s.cumulative_yield_pct:.4f}% "
            f"gas={s.cumulative_gas_pct:.4f}% "
            f"net={s.net_gain_pct:.4f}%"
        )

    if run:
        path = save_results(report, data_dir=data_dir_arg)
        print(f"\n  Saved to: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
