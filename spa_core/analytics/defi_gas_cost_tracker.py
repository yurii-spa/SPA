"""
MP-887 DeFiGasCostTracker
Advisory/read-only analytics module.
Tracks gas costs across chains and protocols, computes break-even position
sizes and annual gas drag on yield.

Data log: data/gas_cost_log.json (ring-buffer, max 100 entries)
Pure stdlib. No external dependencies.
"""

import json
import math
import os
import time


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INF_SENTINEL = 99999.0   # JSON-serialisable stand-in for math.inf

_EFFICIENCY_LABELS = [
    (7.0,   "EFFICIENT"),
    (30.0,  "ACCEPTABLE"),
    (90.0,  "EXPENSIVE"),
]   # anything > 90 (including sentinel) → "PROHIBITIVE"

_DEFAULT_CONFIG = {
    "min_breakeven_days": 30,
}

_LOG_CAP = 100


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _gas_cost_eth(gas_used: int, gas_price_gwei: float) -> float:
    """gas_used * gas_price_gwei / 1e9  →  ETH spent"""
    return gas_used * gas_price_gwei / 1_000_000_000.0


def _efficiency_label(breakeven_days: float) -> str:
    for threshold, label in _EFFICIENCY_LABELS:
        if breakeven_days <= threshold:
            return label
    return "PROHIBITIVE"


def _safe_mean(values: list) -> float:
    """Return mean of non-empty list; 0.0 for empty."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _finite_breakeven(raw: float) -> bool:
    """True when the value represents a real (finite) break-even."""
    return raw < INF_SENTINEL


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(transactions: list, config: dict = None) -> dict:
    """
    Analyze gas costs across DeFi transactions.

    Parameters
    ----------
    transactions : list of dict
        Each entry must have: protocol, chain, tx_type, gas_used,
        gas_price_gwei, eth_price_usd, position_size_usd, yield_apy_pct.
    config : dict, optional
        Supported keys:
          - min_breakeven_days (int, default 30)

    Returns
    -------
    dict
        Full analysis result (see module docstring for schema).
    """
    cfg = {**_DEFAULT_CONFIG, **(config or {})}
    min_breakeven = float(cfg.get("min_breakeven_days", 30))

    enriched = []

    for tx in transactions:
        protocol        = str(tx.get("protocol", ""))
        chain           = str(tx.get("chain", ""))
        tx_type         = str(tx.get("tx_type", ""))
        gas_used        = int(tx.get("gas_used", 0))
        gas_price_gwei  = float(tx.get("gas_price_gwei", 0.0))
        eth_price_usd   = float(tx.get("eth_price_usd", 0.0))
        position_size   = float(tx.get("position_size_usd", 0.0))
        yield_apy_pct   = float(tx.get("yield_apy_pct", 0.0))

        gc_eth = _gas_cost_eth(gas_used, gas_price_gwei)
        gc_usd = gc_eth * eth_price_usd

        if position_size > 0:
            gas_pct = gc_usd / position_size * 100.0
        else:
            gas_pct = 0.0

        # annual_gas_drag_pct = same as gas_pct_of_position
        annual_gas_drag_pct = gas_pct

        # break-even days
        denom = position_size * yield_apy_pct / 100.0 / 365.0
        if denom > 0:
            bd_raw = gc_usd / denom
        else:
            bd_raw = INF_SENTINEL

        # Cap to sentinel for JSON safety
        bd_out = min(bd_raw, INF_SENTINEL)

        eff_label = _efficiency_label(bd_out)
        flag = "HIGH_GAS" if bd_out > min_breakeven else None

        enriched.append({
            "protocol":             protocol,
            "chain":                chain,
            "tx_type":              tx_type,
            "gas_cost_eth":         gc_eth,
            "gas_cost_usd":         gc_usd,
            "gas_pct_of_position":  gas_pct,
            "breakeven_days":       bd_out,
            "annual_gas_drag_pct":  annual_gas_drag_pct,
            "efficiency_label":     eff_label,
            "flag":                 flag,
        })

    # ------------------------------------------------------------------
    # Aggregations
    # ------------------------------------------------------------------

    by_chain: dict = {}
    by_protocol: dict = {}
    by_tx_type: dict = {}

    for e in enriched:
        chain    = e["chain"]
        protocol = e["protocol"]
        tx_type  = e["tx_type"]

        # by_chain
        if chain not in by_chain:
            by_chain[chain] = {"_gas_usd_list": [], "_bd_finite": []}
        by_chain[chain]["_gas_usd_list"].append(e["gas_cost_usd"])
        if _finite_breakeven(e["breakeven_days"]):
            by_chain[chain]["_bd_finite"].append(e["breakeven_days"])

        # by_protocol
        if protocol not in by_protocol:
            by_protocol[protocol] = {"_gas_usd_list": []}
        by_protocol[protocol]["_gas_usd_list"].append(e["gas_cost_usd"])

        # by_tx_type
        if tx_type not in by_tx_type:
            by_tx_type[tx_type] = {"_gas_usd_list": []}
        by_tx_type[tx_type]["_gas_usd_list"].append(e["gas_cost_usd"])

    # Materialise aggregation dicts
    by_chain_out = {}
    for chain, data in by_chain.items():
        gas_list = data["_gas_usd_list"]
        bd_list  = data["_bd_finite"]
        by_chain_out[chain] = {
            "avg_gas_usd":          _safe_mean(gas_list),
            "tx_count":             len(gas_list),
            "avg_breakeven_days":   _safe_mean(bd_list),
        }

    by_protocol_out = {}
    for protocol, data in by_protocol.items():
        gas_list = data["_gas_usd_list"]
        by_protocol_out[protocol] = {
            "avg_gas_usd":   _safe_mean(gas_list),
            "total_gas_usd": sum(gas_list),
            "tx_count":      len(gas_list),
        }

    by_tx_type_out = {}
    for tx_type, data in by_tx_type.items():
        gas_list = data["_gas_usd_list"]
        by_tx_type_out[tx_type] = {
            "avg_gas_usd": _safe_mean(gas_list),
            "tx_count":    len(gas_list),
        }

    total_gas_spent_usd = sum(e["gas_cost_usd"] for e in enriched)

    # Global average break-even (finite only)
    finite_bds = [e["breakeven_days"] for e in enriched if _finite_breakeven(e["breakeven_days"])]
    avg_breakeven_days = _safe_mean(finite_bds)

    # cheapest / most expensive chain
    cheapest_chain       = None
    most_expensive_chain = None
    if by_chain_out:
        cheapest_chain       = min(by_chain_out, key=lambda c: by_chain_out[c]["avg_gas_usd"])
        most_expensive_chain = max(by_chain_out, key=lambda c: by_chain_out[c]["avg_gas_usd"])

    return {
        "transactions":          enriched,
        "by_chain":              by_chain_out,
        "by_protocol":           by_protocol_out,
        "by_tx_type":            by_tx_type_out,
        "total_gas_spent_usd":   total_gas_spent_usd,
        "average_breakeven_days": avg_breakeven_days,
        "cheapest_chain":        cheapest_chain,
        "most_expensive_chain":  most_expensive_chain,
        "timestamp":             time.time(),
    }


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer, 100 entries)
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data) -> None:
    """Write JSON atomically via tmp file + os.replace."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def log_result(result: dict, log_path: str = "data/gas_cost_log.json") -> None:
    """Append result snapshot to ring-buffer log (max 100 entries)."""
    os.makedirs(os.path.dirname(log_path) if os.path.dirname(log_path) else ".", exist_ok=True)
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            entries = json.load(f)
        if not isinstance(entries, list):
            entries = []
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []

    entry = {
        "timestamp":             result.get("timestamp", time.time()),
        "total_gas_spent_usd":   result.get("total_gas_spent_usd", 0.0),
        "average_breakeven_days": result.get("average_breakeven_days", 0.0),
        "tx_count":              len(result.get("transactions", [])),
        "cheapest_chain":        result.get("cheapest_chain"),
        "most_expensive_chain":  result.get("most_expensive_chain"),
    }

    entries.append(entry)
    if len(entries) > _LOG_CAP:
        entries = entries[-_LOG_CAP:]

    _atomic_write(log_path, entries)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _cli():
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="MP-887 DeFiGasCostTracker")
    parser.add_argument("--check", action="store_true", help="Compute and print, no write (default)")
    parser.add_argument("--run",   action="store_true", help="Compute + write to log")
    parser.add_argument("--data-dir", default="data", help="Directory for JSON state files")
    args = parser.parse_args()

    # Demo data when run standalone
    demo_txs = [
        {
            "protocol": "Aave V3",
            "chain": "ethereum",
            "tx_type": "deposit",
            "gas_used": 200_000,
            "gas_price_gwei": 20.0,
            "eth_price_usd": 3_500.0,
            "position_size_usd": 50_000.0,
            "yield_apy_pct": 4.0,
        },
        {
            "protocol": "Compound V3",
            "chain": "arbitrum",
            "tx_type": "rebalance",
            "gas_used": 150_000,
            "gas_price_gwei": 0.1,
            "eth_price_usd": 3_500.0,
            "position_size_usd": 30_000.0,
            "yield_apy_pct": 5.0,
        },
    ]

    result = analyze(demo_txs)

    print(json.dumps({
        "total_gas_spent_usd":   result["total_gas_spent_usd"],
        "average_breakeven_days": result["average_breakeven_days"],
        "cheapest_chain":        result["cheapest_chain"],
        "most_expensive_chain":  result["most_expensive_chain"],
        "by_chain":              result["by_chain"],
    }, indent=2))

    if args.run:
        log_path = os.path.join(args.data_dir, "gas_cost_log.json")
        log_result(result, log_path)
        print(f"[MP-887] Result logged to {log_path}")


if __name__ == "__main__":
    _cli()
