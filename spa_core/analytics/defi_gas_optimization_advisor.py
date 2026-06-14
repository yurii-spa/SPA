"""
MP-945 DeFiGasOptimizationAdvisor
===================================
Advisory-only analytics module. Pure stdlib. No external dependencies.

Advises on gas cost optimization for DeFi transactions — computing transaction
costs, recommending optimal gas prices for flexible transactions, estimating
batch savings, and flagging expensive or suboptimal transaction patterns.

Data log: data/gas_optimization_log.json (ring-buffer 100 entries, atomic write)

Usage:
    from spa_core.analytics.defi_gas_optimization_advisor import DeFiGasOptimizationAdvisor
    result = DeFiGasOptimizationAdvisor().advise(transactions, config)
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_PATH_DEFAULT = "data/gas_optimization_log.json"
LOG_CAP = 100

DEFAULT_ETH_PRICE_USD = 3000.0
BASE_TX_GAS_OVERHEAD = 21000  # Gas overhead saved per batched transaction

# Optimization label thresholds (cost as % of tx value)
OPTIMAL_PCT = 0.5
ACCEPTABLE_PCT = 1.0
EXPENSIVE_PCT = 2.0
VERY_EXPENSIVE_PCT = 5.0
# >= VERY_EXPENSIVE_PCT → PROHIBITIVE

# Flag thresholds
BATCH_COST_THRESHOLD_USD = 10.0     # BATCH_RECOMMENDED if cost > $10
WAIT_SAVINGS_THRESHOLD_USD = 5.0    # WAIT_RECOMMENDED if savings > $5
HIGH_PRIORITY_FEE_MULTIPLIER = 2.0  # HIGH_PRIORITY_FEE if priority > 2x base
SMALL_TX_VALUE_USD = 100.0          # SMALL_TX_GAS_HEAVY if value < $100
SMALL_TX_COST_USD = 5.0             # SMALL_TX_GAS_HEAVY if cost > $5
L2_COST_THRESHOLD_USD = 50.0        # L2_RECOMMENDED if cost > $50 on ethereum


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tx_cost_usd(gas_used: float, gas_price_gwei: float, eth_price_usd: float) -> float:
    """Compute transaction cost in USD: gas_used * gas_price_gwei * eth_price / 1e9."""
    return gas_used * gas_price_gwei * eth_price_usd / 1e9


def _optimal_gas_price_gwei(tx: dict) -> float:
    """
    Recommend optimal gas price for the transaction.
    - urgent: keep current_gas_price (no waiting).
    - flexible / very_flexible: target base_fee * 1.1 + 1 gwei tip,
      but never exceed current (pointless to suggest higher price).
    """
    current = float(tx.get("current_gas_price_gwei", 0))
    base_fee = float(tx.get("base_fee_gwei", 0))
    sensitivity = tx.get("time_sensitivity", "flexible")

    if sensitivity == "urgent":
        return current

    # Flexible: suggest waiting for slightly above base fee
    target = base_fee * 1.1 + 1.0
    # Never suggest waiting for something above current (no benefit)
    return min(current, max(target, base_fee + 0.5))


def _estimated_savings_usd(tx: dict, optimal_gas: float, eth_price_usd: float) -> float:
    """Savings if tx waits for optimal_gas_price instead of current_gas_price."""
    sensitivity = tx.get("time_sensitivity", "flexible")
    if sensitivity == "urgent":
        return 0.0
    current = float(tx.get("current_gas_price_gwei", 0))
    if optimal_gas >= current:
        return 0.0
    gas_used = float(tx.get("gas_used", 0))
    savings = (current - optimal_gas) * gas_used * eth_price_usd / 1e9
    return max(0.0, savings)


def _batch_savings_usd(tx: dict, eth_price_usd: float) -> float:
    """Estimate gas saved by batching this tx (one fewer base overhead of 21000 gas)."""
    if not tx.get("batch_possible", False):
        return 0.0
    gas_price = float(tx.get("current_gas_price_gwei", 0))
    return BASE_TX_GAS_OVERHEAD * gas_price * eth_price_usd / 1e9


def _optimization_label(cost_as_pct: float) -> str:
    """
    OPTIMAL        < 0.5%
    ACCEPTABLE     < 1.0%
    EXPENSIVE      < 2.0%
    VERY_EXPENSIVE < 5.0%
    PROHIBITIVE    >= 5.0%
    """
    if cost_as_pct < OPTIMAL_PCT:
        return "OPTIMAL"
    elif cost_as_pct < ACCEPTABLE_PCT:
        return "ACCEPTABLE"
    elif cost_as_pct < EXPENSIVE_PCT:
        return "EXPENSIVE"
    elif cost_as_pct < VERY_EXPENSIVE_PCT:
        return "VERY_EXPENSIVE"
    else:
        return "PROHIBITIVE"


def _compute_flags(tx: dict, cost_usd: float, savings_usd: float, batch_save: float) -> List[str]:
    """Compute advisory flag list for a transaction."""
    flags: List[str] = []

    base_fee = float(tx.get("base_fee_gwei", 0))
    priority_fee = float(tx.get("priority_fee_gwei", 0))
    tx_value_usd = float(tx.get("tx_value_usd", 0))
    sensitivity = str(tx.get("time_sensitivity", "flexible"))
    chain = str(tx.get("chain", "")).lower()
    batch_possible = bool(tx.get("batch_possible", False))

    # BATCH_RECOMMENDED: batch possible AND cost > $10
    if batch_possible and cost_usd > BATCH_COST_THRESHOLD_USD:
        flags.append("BATCH_RECOMMENDED")

    # WAIT_RECOMMENDED: flexible AND savings > $5
    if sensitivity in ("flexible", "very_flexible") and savings_usd > WAIT_SAVINGS_THRESHOLD_USD:
        flags.append("WAIT_RECOMMENDED")

    # HIGH_PRIORITY_FEE: priority_fee > 2x base_fee
    if base_fee > 0 and priority_fee > HIGH_PRIORITY_FEE_MULTIPLIER * base_fee:
        flags.append("HIGH_PRIORITY_FEE")

    # SMALL_TX_GAS_HEAVY: value < $100 AND cost > $5
    if tx_value_usd < SMALL_TX_VALUE_USD and cost_usd > SMALL_TX_COST_USD:
        flags.append("SMALL_TX_GAS_HEAVY")

    # L2_RECOMMENDED: cost > $50 AND chain is ethereum
    if cost_usd > L2_COST_THRESHOLD_USD and chain == "ethereum":
        flags.append("L2_RECOMMENDED")

    return flags


def _advise_single(tx: dict, eth_price_usd: float) -> dict:
    """Compute all advisory fields for one transaction dict."""
    protocol = str(tx.get("protocol", "unknown"))
    tx_type = str(tx.get("tx_type", "unknown"))
    gas_used = float(tx.get("gas_used", 0))
    current_gas_price_gwei = float(tx.get("current_gas_price_gwei", 0))
    base_fee_gwei = float(tx.get("base_fee_gwei", 0))
    priority_fee_gwei = float(tx.get("priority_fee_gwei", 0))
    tx_value_usd = float(tx.get("tx_value_usd", 0))
    time_sensitivity = str(tx.get("time_sensitivity", "flexible"))
    chain = str(tx.get("chain", "ethereum"))
    batch_possible = bool(tx.get("batch_possible", False))

    cost_usd = _tx_cost_usd(gas_used, current_gas_price_gwei, eth_price_usd)
    cost_pct = (cost_usd / tx_value_usd * 100.0) if tx_value_usd > 0 else 0.0
    optimal_gas = _optimal_gas_price_gwei(tx)
    savings = _estimated_savings_usd(tx, optimal_gas, eth_price_usd)
    batch_save = _batch_savings_usd(tx, eth_price_usd)
    label = _optimization_label(cost_pct)
    flags = _compute_flags(tx, cost_usd, savings, batch_save)

    return {
        "protocol": protocol,
        "tx_type": tx_type,
        "gas_used": gas_used,
        "current_gas_price_gwei": current_gas_price_gwei,
        "base_fee_gwei": base_fee_gwei,
        "priority_fee_gwei": priority_fee_gwei,
        "tx_value_usd": tx_value_usd,
        "time_sensitivity": time_sensitivity,
        "chain": chain,
        "batch_possible": batch_possible,
        "tx_cost_usd": round(cost_usd, 6),
        "cost_as_pct_of_value": round(cost_pct, 4),
        "optimal_gas_price_gwei": round(optimal_gas, 4),
        "estimated_savings_usd": round(savings, 6),
        "batch_savings_usd": round(batch_save, 6),
        "optimization_label": label,
        "flags": flags,
    }


def _atomic_write(path: str, data: dict) -> None:
    """Write JSON atomically via tmp-file + os.replace."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def _append_log(result: dict, log_path: str) -> None:
    """Append a summary entry to the ring-buffer log (cap=100). Non-fatal."""
    try:
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as fh:
                log = json.load(fh)
        else:
            log = {"entries": []}

        entry = {
            "timestamp": result["timestamp"],
            "transaction_count": result["transaction_count"],
            "total_gas_cost_usd": result["aggregates"]["total_gas_cost_usd"],
            "total_potential_savings_usd": result["aggregates"]["total_potential_savings_usd"],
            "prohibitive_count": result["aggregates"]["prohibitive_count"],
        }
        entries = log.get("entries", [])
        entries.append(entry)
        if len(entries) > LOG_CAP:
            entries = entries[-LOG_CAP:]
        log["entries"] = entries
        log["last_updated"] = result["timestamp"]

        _atomic_write(log_path, log)
    except Exception:
        pass  # Logging failures are non-fatal


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DeFiGasOptimizationAdvisor:
    """
    Advises on gas cost optimization for DeFi transactions.

    Args:
        data_dir: Optional directory for log files (overrides default).
    """

    def __init__(self, data_dir: Optional[str] = None):
        self._data_dir = data_dir

    def _log_path(self) -> str:
        if self._data_dir:
            return os.path.join(self._data_dir, "gas_optimization_log.json")
        return LOG_PATH_DEFAULT

    def advise(self, transactions: List[Dict[str, Any]], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Advise on gas optimization for a list of DeFi transactions.

        Each transaction dict may contain:
            protocol, tx_type, gas_used, current_gas_price_gwei,
            base_fee_gwei, priority_fee_gwei, tx_value_usd,
            time_sensitivity (urgent/flexible/very_flexible),
            chain, batch_possible (bool)

        Config keys:
            eth_price_usd (default 3000.0)

        Returns:
            dict with keys:
                timestamp, transaction_count, transactions (list of enriched dicts),
                aggregates (most_expensive_tx, cheapest_tx, total_gas_cost_usd,
                            total_potential_savings_usd, prohibitive_count)
        """
        if config is None:
            config = {}

        eth_price_usd = float(config.get("eth_price_usd", DEFAULT_ETH_PRICE_USD))
        timestamp = datetime.now(timezone.utc).isoformat()

        if not transactions:
            result = {
                "timestamp": timestamp,
                "transaction_count": 0,
                "transactions": [],
                "aggregates": {
                    "most_expensive_tx": None,
                    "cheapest_tx": None,
                    "total_gas_cost_usd": 0.0,
                    "total_potential_savings_usd": 0.0,
                    "prohibitive_count": 0,
                },
            }
            _append_log(result, self._log_path())
            return result

        advised = [_advise_single(tx, eth_price_usd) for tx in transactions]

        most_expensive = max(advised, key=lambda x: x["tx_cost_usd"])
        cheapest = min(advised, key=lambda x: x["tx_cost_usd"])
        total_cost = sum(a["tx_cost_usd"] for a in advised)
        total_savings = sum(a["estimated_savings_usd"] + a["batch_savings_usd"] for a in advised)
        prohibitive_count = sum(1 for a in advised if a["optimization_label"] == "PROHIBITIVE")

        result = {
            "timestamp": timestamp,
            "transaction_count": len(advised),
            "transactions": advised,
            "aggregates": {
                "most_expensive_tx": most_expensive["protocol"],
                "cheapest_tx": cheapest["protocol"],
                "total_gas_cost_usd": round(total_cost, 6),
                "total_potential_savings_usd": round(total_savings, 6),
                "prohibitive_count": prohibitive_count,
            },
        }

        _append_log(result, self._log_path())
        return result
