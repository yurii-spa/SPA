"""
MP-907: DeFiVaultRebalancingCostAnalyzer

Analyzes the cost of rebalancing DeFi vaults: calculates gas costs,
slippage costs, drift scores, urgency scores, and rebalance labels.

Advisory/read-only. Pure stdlib. Atomic writes (tmp + os.replace).
Ring-buffer capped at 100 entries in data/vault_rebalancing_log.json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/vault_rebalancing_log.json")
MAX_ENTRIES = 100

# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────

# Default gas cost per rebalance swap (in USD per token traded)
DEFAULT_GAS_USD_PER_SWAP = 5.0
# Gwei to ETH conversion
GWEI_TO_ETH = 1e-9
# Approximate gas units per swap on mainnet
GAS_UNITS_PER_SWAP = 150_000
# ETH price default (used if not in config)
DEFAULT_ETH_PRICE_USD = 3_000.0

# Slippage model coefficients
# linear: slippage_pct = (trade_size_usd / pool_depth_usd) * linear_coeff
LINEAR_COEFF = 0.5
# quadratic: slippage_pct = ((trade_size_usd / pool_depth_usd) ** 2) * quadratic_coeff
QUADRATIC_COEFF = 2.0

# Drift thresholds
DRIFT_URGENT = 15.0      # % total absolute drift
DRIFT_RECOMMENDED = 8.0
DRIFT_OPTIONAL = 3.0

# Urgency modifiers
OVERDUE_URGENCY_BONUS = 20.0
HIGH_COST_URGENCY_PENALTY = 10.0

# Cost thresholds
HIGH_COST_PCT = 1.0          # cost > 1% AUM → HIGH_COST flag
LARGE_DRIFT_THRESHOLD = 10.0  # total drift > 10% → LARGE_DRIFT flag
LOW_LIQUIDITY_RATIO = 10.0   # pool_depth < 10x trade_size → LOW_LIQUIDITY


# ─────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────

def _compute_total_drift(current_weights: dict, target_weights: dict) -> float:
    """
    Compute total absolute weight drift (sum of |current - target| for each token).
    Returns percentage (0–200 range but practically 0–100).
    """
    all_tokens = set(current_weights) | set(target_weights)
    drift = 0.0
    for token in all_tokens:
        curr = current_weights.get(token, 0.0)
        tgt = target_weights.get(token, 0.0)
        drift += abs(curr - tgt)
    return drift


def _compute_drift_score(total_drift_pct: float) -> float:
    """Convert absolute drift percentage to a 0–100 drift score."""
    # 0% drift → 0 score; 50% drift → 100 score (clamped)
    score = min(100.0, (total_drift_pct / 50.0) * 100.0)
    return round(score, 2)


def _compute_trade_sizes(
    current_weights: dict,
    target_weights: dict,
    aum_usd: float,
) -> dict:
    """
    Compute per-token trade size in USD needed to reach target weights.
    Only includes tokens that need to be traded (delta != 0).
    Returns dict of token → trade_size_usd (always positive).
    """
    all_tokens = set(current_weights) | set(target_weights)
    trades = {}
    for token in all_tokens:
        curr_pct = current_weights.get(token, 0.0)
        tgt_pct = target_weights.get(token, 0.0)
        delta = abs(tgt_pct - curr_pct)
        if delta > 0.0:
            trades[token] = (delta / 100.0) * aum_usd
    return trades


def _compute_slippage_cost(
    trade_sizes: dict,
    pool_depths: dict,
    slippage_model: str,
) -> float:
    """
    Compute total slippage cost in USD across all token trades.
    slippage_model: 'linear' or 'quadratic'
    """
    total_slippage_usd = 0.0
    for token, trade_size in trade_sizes.items():
        pool_depth = pool_depths.get(token, 1_000_000.0)
        if pool_depth <= 0:
            pool_depth = 1.0
        ratio = trade_size / pool_depth
        if slippage_model == "quadratic":
            slippage_pct = (ratio ** 2) * QUADRATIC_COEFF
        else:  # default: linear
            slippage_pct = ratio * LINEAR_COEFF
        slippage_pct = min(slippage_pct, 0.10)  # cap at 10%
        total_slippage_usd += trade_size * slippage_pct
    return total_slippage_usd


def _compute_gas_cost(
    trade_count: int,
    gas_price_gwei: float,
    eth_price_usd: float,
) -> float:
    """
    Compute total gas cost in USD for a given number of swaps.
    """
    if trade_count <= 0:
        return 0.0
    gas_eth = gas_price_gwei * GWEI_TO_ETH * GAS_UNITS_PER_SWAP * trade_count
    return gas_eth * eth_price_usd


def _compute_urgency_score(
    drift_score: float,
    last_rebalance_days_ago: float,
    rebalance_frequency_days: float,
    cost_as_pct_aum: float,
) -> float:
    """
    Compute urgency score 0–100.
    Higher drift + overdue = higher urgency.
    High cost penalizes urgency slightly.
    """
    urgency = drift_score  # base urgency from drift

    # Overdue bonus
    if rebalance_frequency_days > 0:
        overdue_ratio = last_rebalance_days_ago / rebalance_frequency_days
        if overdue_ratio >= 2.0:
            urgency += OVERDUE_URGENCY_BONUS
        elif overdue_ratio >= 1.5:
            urgency += OVERDUE_URGENCY_BONUS * 0.5
        elif overdue_ratio >= 1.0:
            urgency += OVERDUE_URGENCY_BONUS * 0.2

    # High cost penalty
    if cost_as_pct_aum > HIGH_COST_PCT:
        urgency -= HIGH_COST_URGENCY_PENALTY

    return round(max(0.0, min(100.0, urgency)), 2)


def _compute_rebalance_label(drift_score: float, urgency_score: float) -> str:
    """Determine rebalance action label."""
    # Use both drift and urgency
    if urgency_score >= 70 or drift_score >= (_compute_drift_score(DRIFT_URGENT)):
        return "URGENT"
    elif urgency_score >= 45 or drift_score >= (_compute_drift_score(DRIFT_RECOMMENDED)):
        return "RECOMMENDED"
    elif urgency_score >= 20 or drift_score >= (_compute_drift_score(DRIFT_OPTIONAL)):
        return "OPTIONAL"
    else:
        return "NOT_NEEDED"


def _compute_flags(
    cost_as_pct_aum: float,
    total_drift_pct: float,
    last_rebalance_days_ago: float,
    rebalance_frequency_days: float,
    trade_sizes: dict,
    pool_depths: dict,
) -> list:
    """Compute flags for a vault rebalancing analysis."""
    flags = []
    if cost_as_pct_aum > HIGH_COST_PCT:
        flags.append("HIGH_COST")
    if total_drift_pct > LARGE_DRIFT_THRESHOLD:
        flags.append("LARGE_DRIFT")
    if rebalance_frequency_days > 0 and last_rebalance_days_ago > 2 * rebalance_frequency_days:
        flags.append("OVERDUE")
    # LOW_LIQUIDITY: any token's pool_depth < 10x its trade size
    for token, trade_size in trade_sizes.items():
        depth = pool_depths.get(token, float("inf"))
        if depth < LOW_LIQUIDITY_RATIO * trade_size:
            flags.append("LOW_LIQUIDITY")
            break
    return flags


def _analyze_vault(vault: dict, config: dict) -> dict:
    """Analyze a single vault and return per-vault result dict."""
    name = vault.get("name", "unknown")
    protocol = vault.get("protocol", "unknown")
    current_weights = vault.get("current_weights", {})
    target_weights = vault.get("target_weights", {})
    aum_usd = float(vault.get("aum_usd", 0.0))
    gas_price_gwei = float(vault.get("gas_price_gwei", config.get("default_gas_price_gwei", 30.0)))
    slippage_model = vault.get("slippage_model", "linear").lower()
    pool_depths = vault.get("pool_depths", {})
    rebalance_frequency_days = float(vault.get("rebalance_frequency_days", 30.0))
    last_rebalance_days_ago = float(vault.get("last_rebalance_days_ago", 0.0))
    eth_price_usd = float(config.get("eth_price_usd", DEFAULT_ETH_PRICE_USD))

    # Core computations
    total_drift_pct = _compute_total_drift(current_weights, target_weights)
    drift_score = _compute_drift_score(total_drift_pct)
    trade_sizes = _compute_trade_sizes(current_weights, target_weights, aum_usd)
    trade_count = len(trade_sizes)

    slippage_cost_usd = _compute_slippage_cost(trade_sizes, pool_depths, slippage_model)
    gas_cost_usd = _compute_gas_cost(trade_count, gas_price_gwei, eth_price_usd)
    rebalance_cost_usd = slippage_cost_usd + gas_cost_usd

    cost_as_pct_aum = (rebalance_cost_usd / aum_usd * 100.0) if aum_usd > 0 else 0.0

    urgency_score = _compute_urgency_score(
        drift_score,
        last_rebalance_days_ago,
        rebalance_frequency_days,
        cost_as_pct_aum,
    )

    label = _compute_rebalance_label(drift_score, urgency_score)

    flags = _compute_flags(
        cost_as_pct_aum,
        total_drift_pct,
        last_rebalance_days_ago,
        rebalance_frequency_days,
        trade_sizes,
        pool_depths,
    )

    return {
        "name": name,
        "protocol": protocol,
        "drift_score": drift_score,
        "urgency_score": urgency_score,
        "rebalance_cost_usd": round(rebalance_cost_usd, 4),
        "cost_as_pct_aum": round(cost_as_pct_aum, 6),
        "slippage_cost_usd": round(slippage_cost_usd, 4),
        "gas_cost_usd": round(gas_cost_usd, 4),
        "total_drift_pct": round(total_drift_pct, 4),
        "rebalance_label": label,
        "flags": flags,
        "trade_count": trade_count,
    }


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

class DeFiVaultRebalancingCostAnalyzer:
    """
    Analyzes rebalancing costs for a list of DeFi vaults.

    Each vault dict must contain:
        name: str
        protocol: str
        current_weights: dict[str, float]  -- token → % allocation
        target_weights:  dict[str, float]  -- token → % allocation
        aum_usd: float
        gas_price_gwei: float
        slippage_model: 'linear' | 'quadratic'
        pool_depths: dict[str, float]      -- token → pool depth USD
        rebalance_frequency_days: float
        last_rebalance_days_ago: float

    config dict may contain:
        eth_price_usd: float
        default_gas_price_gwei: float
        data_file: str  (override default DATA_FILE path)
    """

    def analyze(self, vaults: list, config: dict | None = None) -> dict:
        """
        Analyze a list of vaults and return aggregated results.

        Returns:
            {
                "vaults": [per-vault results],
                "aggregates": {
                    "most_urgent_vault": str,
                    "lowest_cost_vault": str,
                    "total_rebalance_cost_usd": float,
                    "average_drift": float,
                    "urgent_count": int,
                },
                "timestamp": float,
                "vault_count": int,
            }
        """
        if config is None:
            config = {}

        if not vaults:
            result = {
                "vaults": [],
                "aggregates": {
                    "most_urgent_vault": None,
                    "lowest_cost_vault": None,
                    "total_rebalance_cost_usd": 0.0,
                    "average_drift": 0.0,
                    "urgent_count": 0,
                },
                "timestamp": time.time(),
                "vault_count": 0,
            }
            self._write_log(result, config)
            return result

        vault_results = [_analyze_vault(v, config) for v in vaults]

        # Aggregates
        total_cost = sum(r["rebalance_cost_usd"] for r in vault_results)
        avg_drift = sum(r["total_drift_pct"] for r in vault_results) / len(vault_results)
        urgent_count = sum(1 for r in vault_results if r["rebalance_label"] == "URGENT")

        # Most urgent: highest urgency_score
        most_urgent = max(vault_results, key=lambda r: r["urgency_score"])
        # Lowest cost: lowest rebalance_cost_usd (only among vaults with actual trades)
        tradeable = [r for r in vault_results if r["trade_count"] > 0]
        if tradeable:
            lowest_cost = min(tradeable, key=lambda r: r["rebalance_cost_usd"])
            lowest_cost_name = lowest_cost["name"]
        else:
            lowest_cost_name = vault_results[0]["name"] if vault_results else None

        result = {
            "vaults": vault_results,
            "aggregates": {
                "most_urgent_vault": most_urgent["name"],
                "lowest_cost_vault": lowest_cost_name,
                "total_rebalance_cost_usd": round(total_cost, 4),
                "average_drift": round(avg_drift, 4),
                "urgent_count": urgent_count,
            },
            "timestamp": time.time(),
            "vault_count": len(vault_results),
        }

        self._write_log(result, config)
        return result

    @staticmethod
    def _write_log(result: dict, config: dict) -> None:
        """Append result to ring-buffer log (atomic write)."""
        data_file = Path(config.get("data_file", DATA_FILE))
        # Load existing
        if data_file.exists():
            try:
                with open(data_file) as f:
                    log = json.load(f)
            except (json.JSONDecodeError, OSError):
                log = []
        else:
            log = []

        # Append new entry
        entry = {
            "ts": result["timestamp"],
            "vault_count": result["vault_count"],
            "aggregates": result["aggregates"],
        }
        log.append(entry)

        # Ring-buffer cap
        if len(log) > MAX_ENTRIES:
            log = log[-MAX_ENTRIES:]

        # Atomic write
        tmp = str(data_file) + ".tmp"
        data_file.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp, str(data_file))


# ─────────────────────────────────────────────────────────────────
# Expose internal helpers for unit testing
# ─────────────────────────────────────────────────────────────────

__all__ = [
    "DeFiVaultRebalancingCostAnalyzer",
    "_compute_total_drift",
    "_compute_drift_score",
    "_compute_trade_sizes",
    "_compute_slippage_cost",
    "_compute_gas_cost",
    "_compute_urgency_score",
    "_compute_rebalance_label",
    "_compute_flags",
    "_analyze_vault",
]
