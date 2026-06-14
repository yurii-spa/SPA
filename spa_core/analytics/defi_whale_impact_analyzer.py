"""
MP-847: DeFiWhaleImpactAnalyzer
Analyzes how large whale transactions (deposits, withdrawals, swaps) impact
pool mechanics, yield dilution, and slippage for regular users in DeFi protocols.

Advisory / read-only analytics. Pure stdlib. Atomic writes (tmp + os.replace).
"""

import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/whale_impact_log.json")
MAX_ENTRIES = 100

_DEFAULT_CONFIG = {
    "whale_threshold_pct": 5.0,   # tx > this % of TVL = whale
    "max_safe_impact_pct": 2.0,   # pool impact above this = risky
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _merge_config(config: dict | None) -> dict:
    cfg = dict(_DEFAULT_CONFIG)
    if config:
        cfg.update(config)
    return cfg


def _classify_impact(
    whale_volume_pct_tvl: float,
    price_impact_pct: float,
    max_safe_impact_pct: float,
) -> str:
    if whale_volume_pct_tvl >= 20 or price_impact_pct >= 10:
        return "CRITICAL"
    if whale_volume_pct_tvl >= 10 or price_impact_pct >= 5:
        return "HIGH"
    if whale_volume_pct_tvl >= max_safe_impact_pct or price_impact_pct >= 2:
        return "MEDIUM"
    return "LOW"


def _user_impact_msg(
    impact_level: str,
    whale_volume_pct_tvl: float,
    whale_tx_count: int,
) -> str:
    if impact_level == "CRITICAL":
        return (
            f"Whale activity represents {whale_volume_pct_tvl:.1f}% of pool"
            " — expect high slippage and yield volatility"
        )
    if impact_level == "HIGH":
        return (
            f"Significant whale presence ({whale_volume_pct_tvl:.1f}% TVL)"
            " — monitor closely"
        )
    if impact_level == "MEDIUM":
        return (
            f"Moderate whale activity — {whale_tx_count} large transactions detected"
        )
    return f"Pool activity within normal parameters — {whale_tx_count} whale transactions"


def _recommended_action(impact_level: str, net_whale_flow_usd: float) -> str:
    if impact_level == "CRITICAL":
        if net_whale_flow_usd < 0:
            return (
                "Consider exiting position — large whale withdrawals may"
                " destabilize pool"
            )
        return "Wait for whale activity to settle before entering"
    if impact_level == "HIGH":
        return "Reduce position size or wait for stabilization"
    if impact_level == "MEDIUM":
        return "Monitor for next 24-48h before taking action"
    return "No action required — normal market activity"


def _analyze_pool(pool: dict, whale_threshold_pct: float, max_safe_impact_pct: float) -> dict:
    """Analyze a single pool and return its impact dict."""
    protocol = pool.get("protocol", "unknown")
    pool_id = pool.get("pool_id", "unknown")
    tvl_usd = float(pool.get("tvl_usd", 0) or 0)
    daily_volume_usd = float(pool.get("daily_volume_usd", 0) or 0)
    fee_apy = float(pool.get("fee_apy", 0) or 0)
    transactions = pool.get("whale_transactions", []) or []

    # --- identify whale txs ---
    whale_txs = []
    for tx in transactions:
        amount = float(tx.get("amount_usd", 0) or 0)
        if tvl_usd == 0:
            is_whale = True
        else:
            is_whale = (amount / tvl_usd * 100) >= whale_threshold_pct
        if is_whale:
            whale_txs.append(tx)

    whale_tx_count = len(whale_txs)
    whale_volume_usd = sum(float(t.get("amount_usd", 0) or 0) for t in whale_txs)

    if tvl_usd > 0:
        whale_volume_pct_tvl = whale_volume_usd / tvl_usd * 100
    else:
        whale_volume_pct_tvl = 0.0

    # --- net whale flow ---
    net_inflow = 0.0
    net_outflow = 0.0
    swap_whale_vol = 0.0

    for tx in whale_txs:
        amount = float(tx.get("amount_usd", 0) or 0)
        tx_type = tx.get("tx_type", "")
        direction = tx.get("direction", "IN")

        if tx_type == "SWAP":
            swap_whale_vol += amount
            # SWAP direction=IN treated as positive for net_flow
            if direction == "IN":
                net_inflow += amount
            else:
                net_outflow += amount
        elif tx_type == "DEPOSIT":
            net_inflow += amount
        elif tx_type == "WITHDRAW":
            net_outflow += amount

    net_whale_flow_usd = net_inflow - net_outflow

    # --- yield dilution ---
    if net_whale_flow_usd > 0 and fee_apy > 0 and tvl_usd > 0:
        new_yield = fee_apy * tvl_usd / (tvl_usd + net_whale_flow_usd)
        yield_dilution_pct = (fee_apy - new_yield) / fee_apy * 100
    else:
        yield_dilution_pct = 0.0

    # --- price impact ---
    if daily_volume_usd > 0:
        price_impact_pct = (swap_whale_vol / daily_volume_usd) * 0.3
    else:
        price_impact_pct = 0.0
    price_impact_pct = min(price_impact_pct, 20.0)

    # --- impact level ---
    impact_level = _classify_impact(
        whale_volume_pct_tvl, price_impact_pct, max_safe_impact_pct
    )

    user_impact = _user_impact_msg(impact_level, whale_volume_pct_tvl, whale_tx_count)
    recommended_action = _recommended_action(impact_level, net_whale_flow_usd)

    return {
        "protocol": protocol,
        "pool_id": pool_id,
        "whale_tx_count": whale_tx_count,
        "whale_volume_usd": whale_volume_usd,
        "whale_volume_pct_tvl": whale_volume_pct_tvl,
        "net_whale_flow_usd": net_whale_flow_usd,
        "yield_dilution_pct": yield_dilution_pct,
        "price_impact_pct": price_impact_pct,
        "impact_level": impact_level,
        "user_impact": user_impact,
        "recommended_action": recommended_action,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(pools: list, config: dict = None) -> dict:
    """
    Analyze whale transaction impact across a list of DeFi pools.

    pools: list of {
        "protocol": str,
        "pool_id": str,
        "tvl_usd": float,
        "whale_transactions": list of {
            "tx_type": "DEPOSIT" | "WITHDRAW" | "SWAP",
            "amount_usd": float,
            "direction": "IN" | "OUT"
        },
        "daily_volume_usd": float,
        "fee_apy": float
    }
    config: {
        "whale_threshold_pct": float,  # default 5.0
        "max_safe_impact_pct": float   # default 2.0
    }

    Returns analysis dict with per-pool results + aggregates.
    """
    cfg = _merge_config(config)
    whale_threshold_pct = float(cfg.get("whale_threshold_pct", 5.0))
    max_safe_impact_pct = float(cfg.get("max_safe_impact_pct", 2.0))

    if not pools:
        return {
            "pools": [],
            "most_impacted_pool": None,
            "safest_pool": None,
            "total_whale_volume_usd": 0.0,
            "timestamp": time.time(),
        }

    pool_results = []
    for pool in pools:
        result = _analyze_pool(pool, whale_threshold_pct, max_safe_impact_pct)
        pool_results.append(result)

    # --- aggregates ---
    total_whale_volume_usd = sum(p["whale_volume_usd"] for p in pool_results)

    # Most impacted: highest whale_volume_pct_tvl
    _IMPACT_ORDER = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}

    def _impact_key(p):
        return (_IMPACT_ORDER.get(p["impact_level"], 0), p["whale_volume_pct_tvl"])

    sorted_by_impact = sorted(pool_results, key=_impact_key, reverse=True)
    most_impacted_pool = sorted_by_impact[0]["pool_id"] if sorted_by_impact else None

    sorted_by_safe = sorted(pool_results, key=_impact_key)
    safest_pool = sorted_by_safe[0]["pool_id"] if sorted_by_safe else None

    result = {
        "pools": pool_results,
        "most_impacted_pool": most_impacted_pool,
        "safest_pool": safest_pool,
        "total_whale_volume_usd": total_whale_volume_usd,
        "timestamp": time.time(),
    }

    _append_log(result)
    return result


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer, atomic)
# ---------------------------------------------------------------------------

def _append_log(entry: dict) -> None:
    """Append entry to DATA_FILE, capped at MAX_ENTRIES. Atomic write."""
    data_path = DATA_FILE
    try:
        if data_path.exists():
            with open(data_path, "r") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        else:
            data_path.parent.mkdir(parents=True, exist_ok=True)
            log = []
    except Exception:
        log = []

    log.append(entry)
    if len(log) > MAX_ENTRIES:
        log = log[-MAX_ENTRIES:]

    tmp = str(data_path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(log, f, indent=2)
    os.replace(tmp, data_path)


def init_log() -> None:
    """Initialize data/whale_impact_log.json as [] if absent."""
    if not DATA_FILE.exists():
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(DATA_FILE) + ".tmp"
        with open(tmp, "w") as f:
            json.dump([], f)
        os.replace(tmp, DATA_FILE)
