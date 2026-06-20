"""
MP-852 ProtocolTokenEmissionAnalyzer
======================================
Analyzes DeFi protocol token emission schedules to assess inflation pressure,
supply dilution impact on token price, and whether protocol revenue can absorb
emission costs.

Advisory / read-only module. Pure stdlib only.
Output log: data/token_emission_log.json (ring-buffer, max 100 entries).
Atomic writes: tmp + os.replace.
"""

import json
import math
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_INFLATION_ALERT_PCT = 5.0
LOG_MAX_ENTRIES = 100

# Revenue-coverage thresholds
REVENUE_BACKED_THRESHOLD = 1.0
PARTIALLY_BACKED_THRESHOLD = 0.5

# Inflation pressure thresholds (annualized %)
HYPERINFLATIONARY_THRESHOLD = 100.0
HIGH_THRESHOLD = 20.0


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
        return os.path.join(data_dir, "token_emission_log.json")
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        candidate = os.path.join(here, "data", "token_emission_log.json")
        if os.path.isdir(os.path.join(here, "data")) or os.path.exists(
            os.path.join(here, "data")
        ):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    return os.path.join("data", "token_emission_log.json")


# ---------------------------------------------------------------------------
# Core analysis per protocol
# ---------------------------------------------------------------------------

def _analyze_protocol(proto: dict, inflation_alert_pct: float) -> dict:
    name = proto.get("name", "unknown")
    token_symbol = proto.get("token_symbol", "???")
    current_supply = float(proto.get("current_supply", 0.0))
    max_supply = float(proto.get("max_supply", 0.0))
    emissions_per_day = float(proto.get("emissions_per_day", 0.0))
    token_price_usd = float(proto.get("token_price_usd", 0.0))
    revenue_daily_usd = float(proto.get("protocol_revenue_daily_usd", 0.0))
    unlock_schedule = proto.get("emission_unlock_schedule", [])

    # Treat negative emissions as 0
    if emissions_per_day < 0:
        emissions_per_day = 0.0

    # --- Inflation metrics ---
    if current_supply > 0:
        daily_inflation_pct = emissions_per_day / current_supply * 100.0
    else:
        daily_inflation_pct = 0.0

    annualized_inflation_pct = daily_inflation_pct * 365.0

    # --- Emission value ---
    emission_value_usd_daily = emissions_per_day * token_price_usd

    # --- Revenue coverage ratio ---
    if emission_value_usd_daily == 0:
        revenue_coverage_ratio = 999.0  # no emissions → infinite coverage, store as 999
    else:
        revenue_coverage_ratio = revenue_daily_usd / emission_value_usd_daily

    # --- Supply remaining ---
    if max_supply > 0:
        remaining = max_supply - current_supply
        supply_remaining_pct = remaining / max_supply * 100.0
        if supply_remaining_pct < 0:
            supply_remaining_pct = 0.0
    else:
        supply_remaining_pct = None  # unlimited

    # --- Days to fully diluted ---
    if max_supply == 0 or emissions_per_day == 0:
        days_to_fully_diluted = None
    elif max_supply <= current_supply:
        days_to_fully_diluted = 0.0
    else:
        days_to_fully_diluted = (max_supply - current_supply) / emissions_per_day

    # --- Next major unlock ---
    next_major_unlock = None
    min_days = None
    for unlock in unlock_schedule:
        d = int(unlock.get("days_until", 0))
        if d > 0:
            if min_days is None or d < min_days:
                min_days = d
                next_major_unlock = unlock

    # --- Inflation pressure ---
    if annualized_inflation_pct >= HYPERINFLATIONARY_THRESHOLD:
        inflation_pressure = "HYPERINFLATIONARY"
    elif annualized_inflation_pct >= HIGH_THRESHOLD:
        inflation_pressure = "HIGH"
    elif annualized_inflation_pct >= inflation_alert_pct:
        inflation_pressure = "MODERATE"
    else:
        inflation_pressure = "LOW"

    # --- Sustainability ---
    if emissions_per_day == 0:
        sustainability = "DEFLATIONARY"
    elif revenue_coverage_ratio >= REVENUE_BACKED_THRESHOLD:
        sustainability = "REVENUE_BACKED"
    elif revenue_coverage_ratio >= PARTIALLY_BACKED_THRESHOLD:
        sustainability = "PARTIALLY_BACKED"
    else:
        sustainability = "UNSUSTAINABLE"

    # --- Flags ---
    flags = []

    if annualized_inflation_pct >= inflation_alert_pct:
        flags.append(
            f"Annual inflation {annualized_inflation_pct:.1f}% — high dilution"
        )

    if emissions_per_day > 0 and revenue_coverage_ratio < 1.0:
        flags.append("Revenue does not cover emissions")

    if next_major_unlock is not None and int(next_major_unlock.get("days_until", 999)) <= 30:
        flags.append("Major unlock event approaching")

    if max_supply == 0 and emissions_per_day > 0:
        flags.append("Unlimited supply — no hard cap")

    if supply_remaining_pct is not None and supply_remaining_pct < 10.0:
        flags.append("Near fully diluted")

    if revenue_daily_usd == 0 and emissions_per_day > 0:
        flags.append("No protocol revenue")

    return {
        "name": name,
        "token_symbol": token_symbol,
        "daily_inflation_pct": round(daily_inflation_pct, 6),
        "annualized_inflation_pct": round(annualized_inflation_pct, 4),
        "emission_value_usd_daily": round(emission_value_usd_daily, 6),
        "revenue_coverage_ratio": round(revenue_coverage_ratio, 6),
        "supply_remaining_pct": round(supply_remaining_pct, 4) if supply_remaining_pct is not None else None,
        "days_to_fully_diluted": round(days_to_fully_diluted, 4) if days_to_fully_diluted is not None else None,
        "next_major_unlock": next_major_unlock,
        "inflation_pressure": inflation_pressure,
        "sustainability": sustainability,
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------

def analyze(
    protocols: list,
    config: dict = None,
    data_dir: Optional[str] = None,
    save_log: bool = True,
) -> dict:
    """
    Analyze token emission schedules for a list of DeFi protocols.

    Parameters
    ----------
    protocols : list of dict
        Each protocol must have:
        - name: str
        - token_symbol: str
        - current_supply: float
        - max_supply: float (0 = unlimited)
        - emissions_per_day: float
        - token_price_usd: float
        - protocol_revenue_daily_usd: float
        - emission_unlock_schedule: list of {days_until: int, tokens_unlocking: float}

    config : dict, optional
        - inflation_alert_pct: float (default 5.0)

    data_dir : str, optional
        Override directory for token_emission_log.json

    save_log : bool
        Whether to append result to ring-buffer log (default True)

    Returns
    -------
    dict with keys:
        protocols, most_inflationary, most_sustainable, average_inflation_pct, timestamp
    """
    if config is None:
        config = {}

    inflation_alert_pct = float(config.get("inflation_alert_pct", DEFAULT_INFLATION_ALERT_PCT))

    analyzed = []
    for proto in protocols:
        analyzed.append(_analyze_protocol(proto, inflation_alert_pct))

    # --- most_inflationary ---
    most_inflationary = None
    if analyzed:
        highest_inflation = max(analyzed, key=lambda p: p["annualized_inflation_pct"])
        most_inflationary = highest_inflation["name"]

    # --- most_sustainable ---
    # Highest revenue_coverage_ratio; prefer REVENUE_BACKED
    most_sustainable = None
    if analyzed:
        revenue_backed = [p for p in analyzed if p["sustainability"] == "REVENUE_BACKED"]
        if revenue_backed:
            best = max(revenue_backed, key=lambda p: p["revenue_coverage_ratio"])
        else:
            best = max(analyzed, key=lambda p: p["revenue_coverage_ratio"])
        most_sustainable = best["name"]

    # --- average_inflation_pct ---
    if analyzed:
        average_inflation_pct = sum(p["annualized_inflation_pct"] for p in analyzed) / len(analyzed)
    else:
        average_inflation_pct = 0.0

    result = {
        "protocols": analyzed,
        "most_inflationary": most_inflationary,
        "most_sustainable": most_sustainable,
        "average_inflation_pct": round(average_inflation_pct, 4),
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

    _demo_protocols = [
        {
            "name": "Aave",
            "token_symbol": "AAVE",
            "current_supply": 16_000_000.0,
            "max_supply": 16_000_000.0,
            "emissions_per_day": 0.0,
            "token_price_usd": 90.0,
            "protocol_revenue_daily_usd": 200_000.0,
            "emission_unlock_schedule": [],
        },
        {
            "name": "Compound",
            "token_symbol": "COMP",
            "current_supply": 7_000_000.0,
            "max_supply": 10_000_000.0,
            "emissions_per_day": 2000.0,
            "token_price_usd": 55.0,
            "protocol_revenue_daily_usd": 50_000.0,
            "emission_unlock_schedule": [
                {"days_until": 20, "tokens_unlocking": 500_000},
            ],
        },
        {
            "name": "NewProtocol",
            "token_symbol": "NEW",
            "current_supply": 100_000.0,
            "max_supply": 0.0,  # unlimited
            "emissions_per_day": 10_000.0,
            "token_price_usd": 0.10,
            "protocol_revenue_daily_usd": 0.0,
            "emission_unlock_schedule": [],
        },
    ]

    result = analyze(_demo_protocols, save_log=("--run" in sys.argv))
    print(json.dumps(result, indent=2))
