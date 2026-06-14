"""
MP-877: DeFiVaultStrategyComparator
Compares vault strategies head-to-head — single-asset vs LP vs leveraged vs
delta-neutral — normalizing for risk and capital requirements to find the best
risk-adjusted strategy per capital tier.

Advisory / read-only. Pure stdlib. Atomic writes (tmp + os.replace).
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

DATA_FILE = Path("data/vault_strategy_log.json")
MAX_ENTRIES = 100

# ---------------------------------------------------------------------------
# Internal scoring helpers
# ---------------------------------------------------------------------------

VALID_STRATEGY_TYPES = {
    "SINGLE_ASSET", "LP_PROVISION", "LEVERAGED", "DELTA_NEUTRAL", "RESTAKING"
}


def _yield_score(net_net_apy: float) -> int:
    """0-40 score based on net_net_apy."""
    if net_net_apy >= 30:
        return 40
    if net_net_apy >= 20:
        return 35
    if net_net_apy >= 15:
        return 30
    if net_net_apy >= 10:
        return 25
    if net_net_apy >= 5:
        return 18
    if net_net_apy >= 2:
        return 10
    if net_net_apy >= 0:
        return 5
    return 0


def _risk_bonus(risk_multiplier: float) -> int:
    """0-30 score; higher risk_multiplier → lower bonus."""
    if risk_multiplier <= 1.0:
        return 30
    if risk_multiplier <= 1.5:
        return 25
    if risk_multiplier <= 2.0:
        return 18
    if risk_multiplier <= 2.5:
        return 12
    if risk_multiplier <= 3.0:
        return 6
    return 0


def _rebalance_score(rebalance_frequency_days: int) -> int:
    """0-30 score; more frequent rebalancing → lower score."""
    if rebalance_frequency_days >= 30:
        return 30
    if rebalance_frequency_days >= 14:
        return 22
    if rebalance_frequency_days >= 7:
        return 15
    if rebalance_frequency_days >= 3:
        return 8
    return 0


def _strategy_score(net_net_apy: float, risk_multiplier: float,
                    rebalance_frequency_days: int) -> int:
    """Composite 0-100 strategy score."""
    score = (
        _yield_score(net_net_apy)
        + _risk_bonus(risk_multiplier)
        + _rebalance_score(rebalance_frequency_days)
    )
    return min(100, score)


def _strategy_grade(score: int) -> str:
    """Grade from composite score."""
    if score >= 90:
        return "S"
    if score >= 75:
        return "A"
    if score >= 60:
        return "B"
    if score >= 45:
        return "C"
    if score >= 30:
        return "D"
    return "F"


def _rebalance_burden(rebalance_frequency_days: int) -> str:
    """Burden label based on rebalance frequency."""
    if rebalance_frequency_days < 7:
        return "HIGH"
    if rebalance_frequency_days <= 14:
        return "MEDIUM"
    return "LOW"


def _check_suitability(strategy: dict, config: dict) -> tuple:
    """Return (is_suitable, suitability_reason)."""
    user_capital = config.get("user_capital_usd", 10_000)
    max_risk = config.get("max_acceptable_risk", 3.0)
    mgmt_pref = config.get("management_preference", "ANY")

    min_cap = strategy.get("min_capital_usd", 0.0)
    max_cap = strategy.get("max_capital_usd", 0.0)
    risk_mult = strategy.get("risk_multiplier", 1.0)
    requires_active = strategy.get("requires_active_management", False)

    # Capital lower bound
    if user_capital < min_cap:
        return False, (
            f"Requires minimum {min_cap:.0f} USD "
            f"(you have {user_capital:.0f})"
        )

    # Capital upper bound (0 = unlimited)
    if max_cap > 0 and user_capital > max_cap:
        return False, f"Maximum capital {max_cap:.0f} USD exceeded"

    # Risk filter
    if risk_mult > max_risk:
        return False, (
            f"Risk multiplier {risk_mult:.1f}x exceeds "
            f"maximum {max_risk:.1f}x"
        )

    # Management preference
    if mgmt_pref == "PASSIVE" and requires_active:
        return False, "Requires active management"
    if mgmt_pref == "ACTIVE" and not requires_active:
        return False, "Requires passive management"

    return True, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(strategies: list, config: dict = None) -> dict:
    """
    Compare vault strategies and return risk-adjusted rankings.

    strategies: list of strategy dicts (see module docstring)
    config: optional dict with user_capital_usd, max_acceptable_risk,
            management_preference

    Returns analysis dict.
    """
    if config is None:
        config = {}

    user_capital = float(config.get("user_capital_usd", 10_000))
    # Keep max_acceptable_risk as-is (could be float or int)
    config.setdefault("user_capital_usd", user_capital)
    config.setdefault("max_acceptable_risk", 3.0)
    config.setdefault("management_preference", "ANY")

    if not strategies:
        return {
            "strategies": [],
            "best_strategy": None,
            "best_by_type": {},
            "suitable_count": 0,
            "comparison_summary": "",
            "timestamp": time.time(),
        }

    results = []
    best_by_type: dict = {}

    for s in strategies:
        name = s.get("name", "")
        stype = s.get("strategy_type", "SINGLE_ASSET")
        net_apy = float(s.get("net_apy_pct", 0.0))
        risk_mult = float(s.get("risk_multiplier", 1.0))
        gas_monthly = float(s.get("gas_cost_per_month_usd", 0.0))
        rebalance_days = int(s.get("rebalance_frequency_days", 30))

        # Derived metrics
        if user_capital > 0:
            annualized_gas_drag = gas_monthly * 12 / user_capital * 100
            monthly_gas_drag = gas_monthly / user_capital * 100
        else:
            annualized_gas_drag = 0.0
            monthly_gas_drag = 0.0

        risk_adjusted_apy = net_apy / risk_mult if risk_mult > 0 else 0.0
        net_net_apy = risk_adjusted_apy - annualized_gas_drag

        score = _strategy_score(net_net_apy, risk_mult, rebalance_days)
        grade = _strategy_grade(score)
        burden = _rebalance_burden(rebalance_days)

        is_suitable, reason = _check_suitability(s, config)

        entry = {
            "name": name,
            "strategy_type": stype,
            "net_apy_pct": net_apy,
            "risk_adjusted_apy_pct": round(risk_adjusted_apy, 6),
            "monthly_gas_drag_pct": round(monthly_gas_drag, 6),
            "net_net_apy_pct": round(net_net_apy, 6),
            "annualized_gas_drag_pct": round(annualized_gas_drag, 6),
            "strategy_score": score,
            "strategy_grade": grade,
            "is_suitable": is_suitable,
            "suitability_reason": reason,
            "rebalance_burden": burden,
        }
        results.append(entry)

        # best_by_type: track highest score for each type (suitable or not)
        if stype not in best_by_type or score > best_by_type[stype]["_score"]:
            best_by_type[stype] = {"name": name, "_score": score}

    # Clean best_by_type — remove internal _score key
    best_by_type_clean = {k: v["name"] for k, v in best_by_type.items()}

    suitable = [r for r in results if r["is_suitable"]]
    suitable_count = len(suitable)

    best_strategy = None
    best_net_net = 0.0
    if suitable:
        best_entry = max(suitable, key=lambda r: r["strategy_score"])
        best_strategy = best_entry["name"]
        best_net_net = best_entry["net_net_apy_pct"]

    comparison_summary = (
        f"Analyzed {len(strategies)} strategies, {suitable_count} suitable. "
        f"Best: {best_strategy or 'none'} ({best_net_net:.2f} net-net APY%)"
    )

    output = {
        "strategies": results,
        "best_strategy": best_strategy,
        "best_by_type": best_by_type_clean,
        "suitable_count": suitable_count,
        "comparison_summary": comparison_summary,
        "timestamp": time.time(),
    }

    _log_result(output)
    return output


# ---------------------------------------------------------------------------
# Ring-buffer log
# ---------------------------------------------------------------------------

def _log_result(result: dict) -> None:
    """Append result to ring-buffer JSON log (max MAX_ENTRIES). Atomic write."""
    data_path = Path(DATA_FILE)
    data_path.parent.mkdir(parents=True, exist_ok=True)

    entries = []
    if data_path.exists():
        try:
            with open(data_path) as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                entries = []
        except (json.JSONDecodeError, OSError):
            entries = []

    entries.append(result)
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]

    tmp = str(data_path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(entries, f, indent=2)
    os.replace(tmp, str(data_path))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _init_data_file() -> None:
    """Ensure data file exists as empty list."""
    p = Path(DATA_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        tmp = str(p) + ".tmp"
        with open(tmp, "w") as f:
            json.dump([], f)
        os.replace(tmp, str(p))


if __name__ == "__main__":
    import argparse
    import sys

    _init_data_file()

    parser = argparse.ArgumentParser(
        description="MP-877 DeFiVaultStrategyComparator"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run demo analysis and print results without logging",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run demo analysis and log results",
    )
    args = parser.parse_args()

    demo_strategies = [
        {
            "name": "Aave USDC Single Asset",
            "strategy_type": "SINGLE_ASSET",
            "net_apy_pct": 4.5,
            "risk_multiplier": 1.0,
            "min_capital_usd": 100,
            "max_capital_usd": 0,
            "rebalance_frequency_days": 90,
            "gas_cost_per_month_usd": 5.0,
            "requires_active_management": False,
        },
        {
            "name": "Uniswap ETH/USDC LP",
            "strategy_type": "LP_PROVISION",
            "net_apy_pct": 18.0,
            "risk_multiplier": 2.0,
            "min_capital_usd": 1000,
            "max_capital_usd": 0,
            "rebalance_frequency_days": 7,
            "gas_cost_per_month_usd": 40.0,
            "requires_active_management": True,
        },
        {
            "name": "Delta Neutral sUSDe",
            "strategy_type": "DELTA_NEUTRAL",
            "net_apy_pct": 22.0,
            "risk_multiplier": 1.5,
            "min_capital_usd": 5000,
            "max_capital_usd": 500000,
            "rebalance_frequency_days": 14,
            "gas_cost_per_month_usd": 25.0,
            "requires_active_management": True,
        },
    ]

    demo_config = {
        "user_capital_usd": 10000,
        "max_acceptable_risk": 3.0,
        "management_preference": "ANY",
    }

    result = analyze(demo_strategies, demo_config)
    print(json.dumps(result, indent=2))
    sys.exit(0)
