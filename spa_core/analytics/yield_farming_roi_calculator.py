"""
MP-869: YieldFarmingROICalculator
Comprehensive ROI calculator for yield farming positions, accounting for
token price exposure (reward token + principal), entry/exit costs,
impermanent loss drag, and true annualized returns.

Advisory / read-only. Pure stdlib only. Atomic writes (tmp + os.replace).
Ring-buffer JSON log capped at 100 entries.

Usage:
    from spa_core.analytics.yield_farming_roi_calculator import analyze
    result = analyze(farms, config={"risk_free_rate_pct": 5.0})
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = _REPO_ROOT / "data" / "yield_farming_roi_log.json"
MAX_ENTRIES = 100

_DEFAULT_RISK_FREE_RATE = 5.0   # annual %

# ---------------------------------------------------------------------------
# Internal helpers: classification
# ---------------------------------------------------------------------------

def _reward_token_impact(price_change_pct: float) -> str:
    """Classify reward token price impact category."""
    if price_change_pct >= 20.0:
        return "BOOSTED"
    elif price_change_pct >= -10.0:
        return "NEUTRAL"
    elif price_change_pct >= -50.0:
        return "DILUTED"
    else:
        return "DESTROYED"


def _roi_label(annualized_return_pct: float) -> str:
    """Classify ROI quality label from annualized return %."""
    if annualized_return_pct >= 30.0:
        return "EXCEPTIONAL"
    elif annualized_return_pct >= 15.0:
        return "STRONG"
    elif annualized_return_pct >= 0.0:
        return "POSITIVE"
    elif annualized_return_pct >= -5.0:
        return "MARGINAL"
    else:
        return "LOSS"


def _build_recommendation(
    label: str,
    protocol: str,
    annualized_return_pct: float,
    holding_days: int,
    reward_token_impact: str,
    total_costs_usd: float,
    impermanent_loss_pct: float,
    net_profit_usd: float,
) -> str:
    """Build human-readable recommendation string."""
    if label == "EXCEPTIONAL":
        return (
            f"Outstanding farm. {annualized_return_pct:.1f}% annualized after {holding_days}d."
        )
    elif label == "STRONG":
        return (
            f"Strong returns from {protocol}. Reward token {reward_token_impact.lower()}."
        )
    elif label == "POSITIVE":
        return "Profitable. Watch reward token dilution if APY is high."
    elif label == "MARGINAL":
        return (
            f"Near break-even. Costs {total_costs_usd:.0f} USD, IL drag {impermanent_loss_pct:.1f}%."
        )
    else:  # LOSS
        return f"Position underwater {abs(net_profit_usd):.0f} USD. Exit recommended."


# ---------------------------------------------------------------------------
# Internal helpers: single-farm analysis
# ---------------------------------------------------------------------------

def _analyze_farm(farm: dict, risk_free_rate_pct: float) -> dict:
    """Compute full ROI metrics for a single farm dict."""
    protocol = str(farm.get("protocol", "unknown"))
    principal = float(farm.get("principal_usd", 0.0))
    entry_cost = float(farm.get("entry_cost_usd", 0.0))
    exit_cost = float(farm.get("exit_cost_usd", 0.0))
    holding_days = int(farm.get("holding_days", 0))
    base_apy_pct = float(farm.get("base_apy_pct", 0.0))
    reward_apy_pct = float(farm.get("reward_token_apy_pct", 0.0))
    reward_price_change = float(farm.get("reward_token_price_change_pct", 0.0))
    principal_price_change = float(farm.get("principal_price_change_pct", 0.0))
    il_pct = float(farm.get("impermanent_loss_pct", 0.0))

    # --- Base yield ---
    if holding_days > 0 and principal > 0:
        base_yield_usd = principal * base_apy_pct / 100.0 * holding_days / 365.0
    else:
        base_yield_usd = 0.0

    # --- Reward yield (adjusted for reward token price change) ---
    reward_yield_raw = principal * reward_apy_pct / 100.0 * holding_days / 365.0
    reward_yield_usd = reward_yield_raw * (1.0 + reward_price_change / 100.0)

    # --- Impermanent loss (positive = loss) ---
    il_loss_usd = principal * il_pct / 100.0

    # --- Principal gain / loss from price change ---
    principal_gain_usd = principal * principal_price_change / 100.0

    # --- Transaction costs ---
    total_costs_usd = entry_cost + exit_cost

    # --- Net profit ---
    net_profit_usd = (
        base_yield_usd
        + reward_yield_usd
        - il_loss_usd
        + principal_gain_usd
        - total_costs_usd
    )

    # --- Return metrics ---
    total_return_pct = (net_profit_usd / principal * 100.0) if principal > 0 else 0.0
    annualized_return_pct = (
        total_return_pct / holding_days * 365.0 if holding_days > 0 else 0.0
    )

    if holding_days > 0:
        excess_return_pct = annualized_return_pct - (
            risk_free_rate_pct * holding_days / 365.0
        )
    else:
        excess_return_pct = 0.0

    # --- Labels ---
    rt_impact = _reward_token_impact(reward_price_change)
    label = _roi_label(annualized_return_pct)
    recommendation = _build_recommendation(
        label,
        protocol,
        annualized_return_pct,
        holding_days,
        rt_impact,
        total_costs_usd,
        il_pct,
        net_profit_usd,
    )

    return {
        "protocol": protocol,
        "principal_usd": principal,
        "base_yield_usd": base_yield_usd,
        "reward_yield_usd": reward_yield_usd,
        "il_loss_usd": il_loss_usd,
        "principal_gain_usd": principal_gain_usd,
        "total_costs_usd": total_costs_usd,
        "net_profit_usd": net_profit_usd,
        "total_return_pct": total_return_pct,
        "annualized_return_pct": annualized_return_pct,
        "excess_return_pct": excess_return_pct,
        "roi_label": label,
        "reward_token_impact": rt_impact,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

def _append_log(result: dict, log_file: Path = None) -> None:
    """Append result snapshot to ring-buffer log (atomic write, max 100 entries)."""
    if log_file is None:
        log_file = DATA_FILE

    try:
        if log_file.exists():
            with open(log_file, "r") as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        else:
            existing = []
    except Exception:
        existing = []

    existing.append(result)
    if len(existing) > MAX_ENTRIES:
        existing = existing[-MAX_ENTRIES:]

    tmp_path = str(log_file) + ".tmp"
    try:
        os.makedirs(log_file.parent, exist_ok=True)
        with open(tmp_path, "w") as fh:
            json.dump(existing, fh, indent=2)
        os.replace(tmp_path, log_file)
    except Exception:
        pass  # Advisory: never raise on log failure


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(farms: list, config: dict = None) -> dict:
    """
    Analyze yield farming positions for comprehensive ROI.

    Parameters
    ----------
    farms : list[dict]
        Each dict contains: protocol, principal_usd, entry_cost_usd, exit_cost_usd,
        holding_days, base_apy_pct, reward_token_apy_pct,
        reward_token_price_change_pct, principal_price_change_pct, impermanent_loss_pct.
    config : dict, optional
        { "risk_free_rate_pct": float }  — default 5.0 annual %.

    Returns
    -------
    dict with per-farm analysis and portfolio_summary.
    """
    if config is None:
        config = {}
    risk_free_rate_pct = float(config.get("risk_free_rate_pct", _DEFAULT_RISK_FREE_RATE))

    # Empty input edge case
    if not farms:
        result = {
            "farms": [],
            "best_farm": None,
            "worst_farm": None,
            "profitable_farms": [],
            "portfolio_summary": {
                "total_principal_usd": 0.0,
                "total_net_profit_usd": 0.0,
                "weighted_avg_annualized_pct": 0.0,
                "total_costs_usd": 0.0,
            },
            "timestamp": time.time(),
        }
        _append_log(result)
        return result

    # Analyze each farm
    analyzed = [_analyze_farm(f, risk_free_rate_pct) for f in farms]

    # Portfolio-level aggregates
    total_principal = sum(f["principal_usd"] for f in analyzed)
    total_net_profit = sum(f["net_profit_usd"] for f in analyzed)
    total_costs = sum(f["total_costs_usd"] for f in analyzed)

    if total_principal > 0:
        weighted_avg = (
            sum(f["annualized_return_pct"] * f["principal_usd"] for f in analyzed)
            / total_principal
        )
    else:
        weighted_avg = 0.0

    # Profitable farms (net_profit > 0)
    profitable_farms = [f["protocol"] for f in analyzed if f["net_profit_usd"] > 0]

    # Best / worst by annualized return
    best = max(analyzed, key=lambda f: f["annualized_return_pct"])
    worst = min(analyzed, key=lambda f: f["annualized_return_pct"])

    result = {
        "farms": analyzed,
        "best_farm": best["protocol"],
        "worst_farm": worst["protocol"],
        "profitable_farms": profitable_farms,
        "portfolio_summary": {
            "total_principal_usd": total_principal,
            "total_net_profit_usd": total_net_profit,
            "weighted_avg_annualized_pct": weighted_avg,
            "total_costs_usd": total_costs,
        },
        "timestamp": time.time(),
    }

    _append_log(result)
    return result
