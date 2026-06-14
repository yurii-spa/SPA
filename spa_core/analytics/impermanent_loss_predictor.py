# spa_core/analytics/impermanent_loss_predictor.py
# MP-845 — ImpermanentLossPredictor (pure stdlib, advisory/read-only)
#
# Predicts impermanent loss for AMM liquidity positions under various price
# change scenarios, comparing IL against fee income to determine profitability.
#
# IL formula (constant product AMM):
#   k   = price_ratio_current / price_ratio_entry
#   IL% = (2 * sqrt(k) / (1 + k) - 1) * 100   (always <= 0)
#
# This module is ADVISORY ONLY — never modifies allocator/risk/execution.
# Atomic writes: tmp-file + os.replace.

import json
import math
import os
import time
from pathlib import Path
from typing import Optional

DATA_FILE = Path("data/impermanent_loss_log.json")
MAX_ENTRIES = 100

DEFAULT_SCENARIOS = [0.5, 0.75, 1.25, 2.0]


# ---------------------------------------------------------------------------
# Core IL math
# ---------------------------------------------------------------------------

def _il_pct_from_k(k: float) -> float:
    """
    Compute IL percentage given price ratio k = new_price / entry_price.
    Returns a value <= 0 (negative means loss).
    k == 1 → 0% IL.
    """
    if k <= 0:
        return 0.0
    return (2.0 * math.sqrt(k) / (1.0 + k) - 1.0) * 100.0


def _scenario_analysis(
    position_value_usd: float,
    fee_apy: float,
    scenarios: list,
) -> list:
    """
    Compute IL and fee recoup days for each scenario price multiplier.
    k_scenario == price_multiplier (ratio relative to entry).
    """
    results = []
    daily_fee_usd = fee_apy / 100.0 / 365.0 * position_value_usd

    for multiplier in scenarios:
        k_s = float(multiplier)
        il_pct_s = _il_pct_from_k(k_s)         # <= 0
        il_usd_s = abs(il_pct_s) / 100.0 * position_value_usd

        if daily_fee_usd > 0 and il_usd_s > 0:
            fee_recoup_days: Optional[float] = il_usd_s / daily_fee_usd
        elif il_usd_s == 0:
            fee_recoup_days = 0.0
        else:
            fee_recoup_days = None  # fee=0, can never recoup

        results.append(
            {
                "price_multiplier": k_s,
                "il_pct": round(il_pct_s, 6),
                "il_usd": round(il_usd_s, 6),
                "fee_recoup_days": round(fee_recoup_days, 2) if fee_recoup_days is not None else None,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Main analyse function
# ---------------------------------------------------------------------------

def analyze(positions: list, config: dict = None) -> dict:
    """
    Analyse IL for each LP position, compute scenarios, aggregate totals,
    append to ring-buffer log, and return the result dict.

    Parameters
    ----------
    positions : list[dict]  — each dict with keys defined in the module docstring.
    config    : dict        — optional {"scenarios": list[float]}

    Returns
    -------
    dict  — full analysis result (see module docstring for schema).
    """
    if config is None:
        config = {}

    scenarios: list = config.get("scenarios", DEFAULT_SCENARIOS)

    errors: list = []
    analysed: list = []

    for pos in positions:
        protocol = pos.get("protocol", "unknown")
        pair     = pos.get("pair", "unknown")

        price_entry   = pos.get("price_ratio_entry", 0.0)
        price_current = pos.get("price_ratio_current", 0.0)
        value_usd     = pos.get("position_value_usd", 0.0)
        fee_apy       = pos.get("fee_apy", 0.0)
        days          = pos.get("days_in_position", 0)
        pool_type     = pos.get("pool_type", "VOLATILE")

        # Edge: entry price == 0 → skip, cannot compute ratio
        if price_entry == 0:
            errors.append(f"{protocol}/{pair}: price_ratio_entry=0, skipped")
            continue

        # k = price ratio (current vs entry)
        k = price_current / price_entry

        # IL at current price
        il_pct = _il_pct_from_k(k)                         # <= 0
        il_usd = abs(il_pct) / 100.0 * value_usd           # positive dollar loss

        # Fee income
        fee_income_usd = fee_apy / 100.0 / 365.0 * days * value_usd

        # Net P&L
        net_pnl_usd = fee_income_usd - il_usd

        # Price change %
        price_change_pct = (k - 1.0) * 100.0

        # Break-even days
        daily_fee_usd = fee_apy / 100.0 / 365.0 * value_usd
        if daily_fee_usd > 0:
            if il_usd <= fee_income_usd:
                break_even_days: Optional[float] = 0.0
            else:
                # Additional days needed on top of days already spent
                remaining_il = il_usd - fee_income_usd
                break_even_days = remaining_il / daily_fee_usd + days
        else:
            break_even_days = None  # fee=0, cannot recoup

        # Verdict
        if net_pnl_usd > 0:
            verdict = "PROFITABLE"
        elif abs(net_pnl_usd) < 1:
            verdict = "BREAKEVEN"
        elif il_pct <= -10.0 and net_pnl_usd < 0:
            verdict = "SEVERE_LOSS"
        else:
            verdict = "LOSS"

        # Scenario analysis
        pos_scenarios = _scenario_analysis(value_usd, fee_apy, scenarios)

        analysed.append(
            {
                "protocol":         protocol,
                "pair":             pair,
                "pool_type":        pool_type,
                "price_change_pct": round(price_change_pct, 4),
                "il_pct":           round(il_pct, 6),
                "il_usd":           round(il_usd, 6),
                "fee_income_usd":   round(fee_income_usd, 6),
                "net_pnl_usd":      round(net_pnl_usd, 6),
                "break_even_days":  round(break_even_days, 2) if break_even_days is not None else None,
                "verdict":          verdict,
                "scenarios":        pos_scenarios,
            }
        )

    # Aggregate totals
    total_il_usd = sum(p["il_usd"] for p in analysed)
    total_fee_usd = sum(p["fee_income_usd"] for p in analysed)
    total_net_pnl = sum(p["net_pnl_usd"] for p in analysed)

    # Worst (highest IL%)
    worst_position: Optional[str] = None
    if analysed:
        worst = min(analysed, key=lambda p: p["il_pct"])
        worst_position = f"{worst['protocol']}/{worst['pair']}"

    # Best (highest net PnL)
    best_position: Optional[str] = None
    if analysed:
        best = max(analysed, key=lambda p: p["net_pnl_usd"])
        best_position = f"{best['protocol']}/{best['pair']}"

    ts = time.time()
    result = {
        "positions":          analysed,
        "worst_position":     worst_position,
        "best_position":      best_position,
        "total_il_usd":       round(total_il_usd, 6),
        "total_fee_income_usd": round(total_fee_usd, 6),
        "total_net_pnl_usd":  round(total_net_pnl, 6),
        "errors":             errors,
        "timestamp":          ts,
    }

    _append_log(result)
    return result


# ---------------------------------------------------------------------------
# Ring-buffer log (atomic write)
# ---------------------------------------------------------------------------

def _append_log(result: dict) -> None:
    """Append result to ring-buffer log file; cap at MAX_ENTRIES."""
    log_path = DATA_FILE

    # Read existing
    existing: list = []
    try:
        with open(log_path, "r") as fh:
            existing = json.load(fh)
        if not isinstance(existing, list):
            existing = []
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    # Build slim log entry (store aggregate + timestamp only to keep log small)
    entry = {
        "timestamp":            result["timestamp"],
        "total_il_usd":         result["total_il_usd"],
        "total_fee_income_usd": result["total_fee_income_usd"],
        "total_net_pnl_usd":    result["total_net_pnl_usd"],
        "position_count":       len(result["positions"]),
        "worst_position":       result["worst_position"],
        "best_position":        result["best_position"],
    }

    existing.append(entry)

    # Ring-buffer cap
    if len(existing) > MAX_ENTRIES:
        existing = existing[-MAX_ENTRIES:]

    # Atomic write
    log_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = log_path.with_suffix(".tmp")
    with open(tmp_path, "w") as fh:
        json.dump(existing, fh, indent=2)
    os.replace(tmp_path, log_path)


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

def _demo() -> None:
    """Quick demo with a handful of positions."""
    positions = [
        {
            "protocol": "Uniswap V2",
            "pair": "ETH/USDC",
            "token_a": "ETH",
            "token_b": "USDC",
            "price_ratio_entry": 2000.0,
            "price_ratio_current": 3000.0,
            "position_value_usd": 50000.0,
            "fee_apy": 15.0,
            "days_in_position": 30,
            "pool_type": "VOLATILE",
        },
        {
            "protocol": "Curve",
            "pair": "USDC/USDT",
            "token_a": "USDC",
            "token_b": "USDT",
            "price_ratio_entry": 1.0,
            "price_ratio_current": 1.002,
            "position_value_usd": 20000.0,
            "fee_apy": 3.5,
            "days_in_position": 60,
            "pool_type": "STABLE",
        },
    ]
    result = analyze(positions)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _demo()
