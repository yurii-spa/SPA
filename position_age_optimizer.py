"""
MP-709 PositionAgeOptimizer
Determines the optimal holding duration for DeFi positions by balancing
entry/exit costs against accumulated yield, identifying diminishing returns.

Advisory / read-only. Pure stdlib. Atomic JSON writes via tmp + os.replace.
Ring-buffer cap: 100 entries.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

DATA_FILE = Path(__file__).parent.parent.parent / "data" / "position_age_log.json"
RING_BUFFER_CAP = 100


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class AgeAnalysis:
    protocol: str
    pool: str
    entry_cost_pct: float       # gas + slippage entering position (% of value)
    exit_cost_pct: float        # gas + slippage exiting (% of value)
    current_apy: float          # current gross APY (%)
    position_age_days: int

    # Breakeven
    breakeven_days: float       # total_cost / (apy/365)  [0 if apy=0]
    days_past_breakeven: int    # max(0, age - breakeven)
    net_return_pct: float       # (apy/365 * age) - entry_cost - exit_cost

    # Optimal hold
    optimal_hold_days: float    # breakeven_days * 3
    hold_efficiency: float      # net_return / max(0.001, breakeven*daily_apy)

    # Recommendation
    maturity_label: str     # TOO_EARLY | MATURING | OPTIMAL | DIMINISHING
    action: str             # HOLD_TO_BREAKEVEN | CONTINUE_HOLD | CONSIDER_REBALANCE | REBALANCE_NOW
    next_review_days: int   # days until next review

    opportunity_cost_pct: float  # opportunity cost vs best alternative in review window
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def analyze(
    protocol: str,
    pool: str,
    entry_cost_pct: float,
    exit_cost_pct: float,
    current_apy: float,
    position_age_days: int,
    best_alternative_apy: float = 0.0,
) -> AgeAnalysis:
    """Compute position-age optimality analysis.

    All cost/APY arguments are in percentage units (e.g. 1.0 for 1 %).
    """
    total_cost_pct = entry_cost_pct + exit_cost_pct
    daily_apy = current_apy / 365.0  # % per day

    # Breakeven: days needed so gross yield covers round-trip costs
    if daily_apy == 0:
        breakeven_days = 0.0
    else:
        breakeven_days = total_cost_pct / daily_apy

    # Net return: cumulative gross yield minus round-trip costs
    net_return_pct = (daily_apy * position_age_days) - total_cost_pct

    days_past_breakeven = max(0, int(position_age_days - breakeven_days))

    optimal_hold_days = breakeven_days * 3.0

    # Efficiency: net_return relative to the theoretical single-breakeven earnings
    denominator = max(0.001, breakeven_days * daily_apy)
    hold_efficiency = net_return_pct / denominator

    # Maturity label — how far past breakeven are we?
    if position_age_days < breakeven_days:
        maturity_label = "TOO_EARLY"
    elif position_age_days < 2 * breakeven_days:
        maturity_label = "MATURING"
    elif position_age_days < 4 * breakeven_days:
        maturity_label = "OPTIMAL"
    else:
        maturity_label = "DIMINISHING"

    # Action
    _action_map = {
        "TOO_EARLY":   "HOLD_TO_BREAKEVEN",
        "MATURING":    "CONTINUE_HOLD",
        "OPTIMAL":     "CONSIDER_REBALANCE",
        "DIMINISHING": "REBALANCE_NOW",
    }
    action = _action_map[maturity_label]

    # Next review
    if maturity_label == "TOO_EARLY":
        next_review_days = math.ceil(breakeven_days - position_age_days)
    elif maturity_label == "MATURING":
        next_review_days = 30
    else:
        next_review_days = 7

    # Opportunity cost over the next review window
    if best_alternative_apy <= current_apy:
        opportunity_cost_pct = 0.0
    else:
        opportunity_cost_pct = (
            (best_alternative_apy - current_apy) / 365.0 * next_review_days
        )

    return AgeAnalysis(
        protocol=protocol,
        pool=pool,
        entry_cost_pct=entry_cost_pct,
        exit_cost_pct=exit_cost_pct,
        current_apy=current_apy,
        position_age_days=position_age_days,
        breakeven_days=breakeven_days,
        days_past_breakeven=days_past_breakeven,
        net_return_pct=net_return_pct,
        optimal_hold_days=optimal_hold_days,
        hold_efficiency=hold_efficiency,
        maturity_label=maturity_label,
        action=action,
        next_review_days=next_review_days,
        opportunity_cost_pct=opportunity_cost_pct,
        saved_to="",
    )


def batch_analyze(positions_data: List[dict]) -> List[AgeAnalysis]:
    """Analyze a list of position dicts and return sorted by net_return_pct desc.

    Each dict should have keys: protocol, pool, entry_cost_pct, exit_cost_pct,
    current_apy, position_age_days, best_alternative_apy (optional, default 0).
    """
    results: List[AgeAnalysis] = []
    for p in positions_data:
        result = analyze(
            protocol=p["protocol"],
            pool=p["pool"],
            entry_cost_pct=p["entry_cost_pct"],
            exit_cost_pct=p["exit_cost_pct"],
            current_apy=p["current_apy"],
            position_age_days=p["position_age_days"],
            best_alternative_apy=p.get("best_alternative_apy", 0.0),
        )
        results.append(result)
    return sorted(results, key=lambda r: r.net_return_pct, reverse=True)


def find_rebalance_candidates(analyses: List[AgeAnalysis]) -> List[AgeAnalysis]:
    """Return analyses where action is CONSIDER_REBALANCE or REBALANCE_NOW."""
    return [
        a for a in analyses
        if a.action in ("CONSIDER_REBALANCE", "REBALANCE_NOW")
    ]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_results(
    analysis: AgeAnalysis,
    data_file: Path = DATA_FILE,
) -> AgeAnalysis:
    """Append analysis to the ring-buffer JSON file (cap 100).

    Uses atomic tmp + os.replace write.  Updates analysis.saved_to in place.
    """
    history = load_history(data_file)

    record: dict = {
        "protocol": analysis.protocol,
        "pool": analysis.pool,
        "entry_cost_pct": analysis.entry_cost_pct,
        "exit_cost_pct": analysis.exit_cost_pct,
        "current_apy": analysis.current_apy,
        "position_age_days": analysis.position_age_days,
        "breakeven_days": analysis.breakeven_days,
        "days_past_breakeven": analysis.days_past_breakeven,
        "net_return_pct": analysis.net_return_pct,
        "optimal_hold_days": analysis.optimal_hold_days,
        "hold_efficiency": analysis.hold_efficiency,
        "maturity_label": analysis.maturity_label,
        "action": analysis.action,
        "next_review_days": analysis.next_review_days,
        "opportunity_cost_pct": analysis.opportunity_cost_pct,
        "saved_at": datetime.utcnow().isoformat(),
    }

    history.append(record)
    if len(history) > RING_BUFFER_CAP:
        history = history[-RING_BUFFER_CAP:]

    data_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = data_file.with_suffix(".age_tmp")
    tmp_path.write_text(json.dumps(history, indent=2))
    os.replace(str(tmp_path), str(data_file))

    analysis.saved_to = str(data_file)
    return analysis


def load_history(data_file: Path = DATA_FILE) -> list:
    """Load persisted history; returns [] on missing file or parse error."""
    if not data_file.exists():
        return []
    try:
        return json.loads(data_file.read_text())
    except (json.JSONDecodeError, OSError):
        return []
