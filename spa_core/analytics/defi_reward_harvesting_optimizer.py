"""
MP-851 DeFiRewardHarvestingOptimizer
=====================================
Determines optimal harvesting frequency for yield farming rewards by comparing
gas costs against the compounding benefit, accounting for reward token volatility.

Advisory / read-only module. Pure stdlib only.
Output log: data/reward_harvesting_log.json (ring-buffer, max 100 entries).
Atomic writes: tmp + os.replace.
"""

import json
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_TARGET_HARVEST_ROI_PCT = 10.0   # harvest when gas < this % of reward
DEFAULT_COMPOUND_PERIODS_PER_YEAR = 52  # weekly compounding
LOG_MAX_ENTRIES = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_log(log_path: str) -> list:
    """Load existing log or return empty list."""
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _save_log(log_path: str, entries: list) -> None:
    """Atomically write log (ring-buffer capped at LOG_MAX_ENTRIES)."""
    entries = entries[-LOG_MAX_ENTRIES:]
    dir_name = os.path.dirname(log_path) or "."
    os.makedirs(dir_name, exist_ok=True)
    atomic_save(entries, str(log_path))
def _get_log_path(data_dir: Optional[str]) -> str:
    if data_dir:
        return os.path.join(data_dir, "reward_harvesting_log.json")
    # Walk up from this file to find project root containing data/
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        candidate = os.path.join(here, "data", "reward_harvesting_log.json")
        if os.path.isdir(os.path.join(here, "data")) or os.path.exists(
            os.path.join(here, "data")
        ):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    # Fallback: cwd/data
    return os.path.join("data", "reward_harvesting_log.json")


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def _analyze_position(pos: dict, target_roi_pct: float) -> dict:
    """Analyze a single position and return per-position result dict."""
    protocol = pos.get("protocol", "unknown")
    position_value = float(pos.get("position_value_usd", 0.0))
    reward_apy = float(pos.get("reward_apy", 0.0))
    gas_cost = float(pos.get("gas_cost_per_harvest_usd", 0.0))
    volatility = pos.get("reward_token_volatility", "LOW")
    days_since = int(pos.get("days_since_last_harvest", 0))
    reinvestment_apy = float(pos.get("reinvestment_apy", 0.0))

    # --- Accrued rewards ---
    # accrued = reward_apy/100/365 * days * position_value
    if position_value <= 0 or days_since <= 0:
        accrued_rewards_usd = 0.0
    else:
        accrued_rewards_usd = (reward_apy / 100.0 / 365.0) * days_since * position_value

    # --- Gas as % of rewards ---
    if accrued_rewards_usd <= 0:
        gas_as_pct_of_rewards = 999.0
    else:
        gas_as_pct_of_rewards = gas_cost / accrued_rewards_usd * 100.0

    # --- Optimal harvest days ---
    # Solve: gas / (reward_apy/100/365 * days * value) * 100 = target_roi_pct
    # => days = gas / (reward_apy/100/365 * value) / (target_roi_pct/100)
    if reward_apy <= 0 or position_value <= 0:
        optimal_harvest_days = None
    else:
        daily_rate = reward_apy / 100.0 / 365.0
        optimal_harvest_days = gas_cost / (daily_rate * position_value) / (target_roi_pct / 100.0)

    # --- Compound benefit ---
    # Additional yield from reinvesting NOW over next 30 days
    compound_benefit_usd = accrued_rewards_usd * reinvestment_apy / 100.0 / 365.0 * 30.0

    # --- Days to optimal ---
    if optimal_harvest_days is None:
        days_to_optimal = None
    elif days_since >= optimal_harvest_days:
        days_to_optimal = None  # already past optimal
    else:
        days_to_optimal = optimal_harvest_days - days_since

    # --- Recommendation ---
    # HARVEST_URGENT: HIGH volatility + already profitable, OR overdue by 2x
    is_profitable = gas_as_pct_of_rewards <= target_roi_pct
    is_overdue = (
        optimal_harvest_days is not None
        and days_since > optimal_harvest_days * 2
    )

    if (is_profitable and volatility == "HIGH") or is_overdue:
        recommendation = "HARVEST_URGENT"
    elif is_profitable:
        recommendation = "HARVEST_NOW"
    else:
        recommendation = "WAIT"

    # --- Urgency reason ---
    if recommendation == "HARVEST_URGENT":
        if volatility == "HIGH" and is_profitable:
            urgency_reason = "Reward token volatile — harvest before price drops further"
        else:
            # overdue
            days_overdue = int(days_since - optimal_harvest_days) if optimal_harvest_days is not None else 0
            urgency_reason = f"Harvest overdue by {days_overdue} days"
    elif recommendation == "HARVEST_NOW":
        urgency_reason = f"Gas only {gas_as_pct_of_rewards:.1f}% of rewards — favorable to harvest"
    else:  # WAIT
        if days_to_optimal is not None:
            urgency_reason = f"Wait {days_to_optimal:.0f} more days for optimal harvest timing"
        else:
            urgency_reason = "Insufficient rewards accumulated to justify gas cost"

    return {
        "protocol": protocol,
        "accrued_rewards_usd": round(accrued_rewards_usd, 6),
        "gas_as_pct_of_rewards": round(gas_as_pct_of_rewards, 4),
        "optimal_harvest_days": round(optimal_harvest_days, 4) if optimal_harvest_days is not None else None,
        "compound_benefit_usd": round(compound_benefit_usd, 6),
        "harvest_recommendation": recommendation,
        "days_to_optimal": round(days_to_optimal, 4) if days_to_optimal is not None else None,
        "urgency_reason": urgency_reason,
    }


def analyze(
    positions: list,
    config: dict = None,
    data_dir: Optional[str] = None,
    save_log: bool = True,
) -> dict:
    """
    Analyze harvesting timing for a list of yield farming positions.

    Parameters
    ----------
    positions : list of dict
        Each position must have:
        - protocol: str
        - position_value_usd: float
        - reward_apy: float
        - gas_cost_per_harvest_usd: float
        - reward_token_volatility: "LOW" | "MEDIUM" | "HIGH"
        - days_since_last_harvest: int
        - reinvestment_apy: float

    config : dict, optional
        - target_harvest_roi_pct: float  (default 10.0)
        - compound_periods_per_year: int (default 52, informational)

    data_dir : str, optional
        Override directory for reward_harvesting_log.json

    save_log : bool
        Whether to append result to the ring-buffer log (default True)

    Returns
    -------
    dict with keys:
        positions, harvest_now_count, total_accrued_usd,
        total_gas_if_all_harvested_usd, highest_priority, timestamp
    """
    if config is None:
        config = {}

    target_roi_pct = float(config.get("target_harvest_roi_pct", DEFAULT_TARGET_HARVEST_ROI_PCT))
    # compound_periods is accepted but only informational in current model
    # compound_periods = int(config.get("compound_periods_per_year", DEFAULT_COMPOUND_PERIODS_PER_YEAR))

    analyzed = []
    for pos in positions:
        analyzed.append(_analyze_position(pos, target_roi_pct))

    harvest_now_count = sum(
        1 for p in analyzed
        if p["harvest_recommendation"] in ("HARVEST_NOW", "HARVEST_URGENT")
    )

    total_accrued_usd = sum(p["accrued_rewards_usd"] for p in analyzed)
    total_gas_if_all_harvested_usd = sum(
        float(pos.get("gas_cost_per_harvest_usd", 0.0)) for pos in positions
    )

    # highest_priority: first HARVEST_URGENT protocol
    highest_priority = None
    for p in analyzed:
        if p["harvest_recommendation"] == "HARVEST_URGENT":
            highest_priority = p["protocol"]
            break

    result = {
        "positions": analyzed,
        "harvest_now_count": harvest_now_count,
        "total_accrued_usd": round(total_accrued_usd, 6),
        "total_gas_if_all_harvested_usd": round(total_gas_if_all_harvested_usd, 6),
        "highest_priority": highest_priority,
        "timestamp": time.time(),
    }

    if save_log:
        log_path = _get_log_path(data_dir)
        entries = _load_log(log_path)
        entries.append(result)
        _save_log(log_path, entries)

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo_positions = [
        {
            "protocol": "Aave-V3",
            "position_value_usd": 50000.0,
            "reward_apy": 5.0,
            "gas_cost_per_harvest_usd": 8.0,
            "reward_token_volatility": "LOW",
            "days_since_last_harvest": 14,
            "reinvestment_apy": 3.5,
        },
        {
            "protocol": "Compound-V3",
            "position_value_usd": 30000.0,
            "reward_apy": 6.0,
            "gas_cost_per_harvest_usd": 12.0,
            "reward_token_volatility": "HIGH",
            "days_since_last_harvest": 7,
            "reinvestment_apy": 4.8,
        },
        {
            "protocol": "Morpho",
            "position_value_usd": 20000.0,
            "reward_apy": 8.0,
            "gas_cost_per_harvest_usd": 5.0,
            "reward_token_volatility": "MEDIUM",
            "days_since_last_harvest": 30,
            "reinvestment_apy": 6.5,
        },
    ]

    result = analyze(_demo_positions, save_log=("--run" in sys.argv))
    print(json.dumps(result, indent=2))
