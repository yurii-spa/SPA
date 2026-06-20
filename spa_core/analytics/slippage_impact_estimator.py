"""
MP-758: SlippageImpactEstimator
Advisory/read-only analytics module.
Estimates transaction slippage for DeFi swaps and rebalancing operations.
Uses pool depth and trade size to compute expected slippage, effective execution
price, and determines whether a trade is cost-effective.

CLI:
    python3 -m spa_core.analytics.slippage_impact_estimator --check
    python3 -m spa_core.analytics.slippage_impact_estimator --run
    python3 -m spa_core.analytics.slippage_impact_estimator --run --data-dir /path/to/data
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict
from typing import List
from spa_core.utils.atomic import atomic_save


# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
DEFAULT_DATA_FILE = os.path.join(_REPO_ROOT, "data", "slippage_impact_log.json")
RING_BUFFER_CAP = 100


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SlippageEstimate:
    protocol: str
    token_pair: str          # e.g. "USDC/ETH"

    trade_size_usd: float
    pool_liquidity_usd: float   # total pool TVL

    # Slippage model: price_impact_pct = trade_size / (pool_liquidity * 2) * 100
    price_impact_pct: float

    mid_price: float            # reference price (no slippage)
    effective_price: float      # mid_price * (1 - price_impact_pct/100) for buys

    slippage_cost_usd: float    # trade_size * price_impact_pct / 100

    max_slippage_pct: float
    is_within_tolerance: bool   # price_impact_pct <= max_slippage_pct

    # Minimum liquidity needed for this trade at max_slippage tolerance
    min_pool_liquidity_needed_usd: float

    pool_fraction_pct: float    # trade_size / pool_liquidity * 100

    slippage_label: str         # NEGLIGIBLE | LOW | MODERATE | HIGH
    recommendation: str


@dataclass
class SlippageResult:
    estimates: List[SlippageEstimate]

    lowest_slippage_pool: str   # min price_impact_pct
    highest_slippage_pool: str  # max price_impact_pct

    tradeable_pools: List[str]  # is_within_tolerance=True

    avg_price_impact_pct: float
    total_slippage_cost_usd: float

    market_liquidity_label: str  # DEEP | ADEQUATE | THIN

    recommendation_summary: str
    saved_to: str


# ---------------------------------------------------------------------------
# Core computation functions
# ---------------------------------------------------------------------------

def compute_price_impact(trade_size_usd: float, pool_liquidity_usd: float) -> float:
    """
    price_impact_pct = trade_size / (pool_liquidity * 2) * 100
    Returns 100.0 if pool_liquidity <= 0.
    """
    if pool_liquidity_usd <= 0:
        return 100.0
    return trade_size_usd / (pool_liquidity_usd * 2) * 100


def compute_effective_price(mid_price: float, price_impact_pct: float) -> float:
    """effective_price = mid_price * (1 - price_impact_pct/100)"""
    return mid_price * (1 - price_impact_pct / 100)


def compute_slippage_cost(trade_size_usd: float, price_impact_pct: float) -> float:
    """slippage_cost_usd = trade_size * price_impact_pct / 100"""
    return trade_size_usd * price_impact_pct / 100


def compute_min_pool_liquidity(trade_size_usd: float, max_slippage_pct: float) -> float:
    """
    min_pool_liquidity = trade_size / (max_slippage_pct/100 * 2)
    Returns float('inf') if max_slippage_pct <= 0.
    """
    if max_slippage_pct <= 0:
        return float("inf")
    return trade_size_usd / (max_slippage_pct / 100 * 2)


def slippage_label(impact_pct: float) -> str:
    """NEGLIGIBLE (<0.1%) | LOW (0.1-0.5%) | MODERATE (0.5-1%) | HIGH (>1%)"""
    if impact_pct < 0.1:
        return "NEGLIGIBLE"
    elif impact_pct < 0.5:
        return "LOW"
    elif impact_pct <= 1.0:
        return "MODERATE"
    else:
        return "HIGH"


# ---------------------------------------------------------------------------
# Estimation functions
# ---------------------------------------------------------------------------

def estimate_slippage(
    protocol: str,
    token_pair: str,
    trade_size_usd: float,
    pool_liquidity_usd: float,
    mid_price: float,
    max_slippage_pct: float = 0.5,
) -> SlippageEstimate:
    """Estimate slippage for a single pool/trade pair."""
    impact = compute_price_impact(trade_size_usd, pool_liquidity_usd)
    effective = compute_effective_price(mid_price, impact)
    cost = compute_slippage_cost(trade_size_usd, impact)
    within_tolerance = impact <= max_slippage_pct
    min_liq = compute_min_pool_liquidity(trade_size_usd, max_slippage_pct)

    if pool_liquidity_usd > 0:
        pool_frac = trade_size_usd / pool_liquidity_usd * 100
    else:
        pool_frac = 100.0

    label = slippage_label(impact)

    # Recommendation
    if label == "HIGH" or not within_tolerance:
        rec = "High slippage risk. Split trade or use deeper pool."
    elif label == "MODERATE":
        rec = "Moderate slippage. Consider smaller trade size."
    elif label == "LOW":
        rec = "Acceptable slippage. Proceed with caution."
    else:  # NEGLIGIBLE
        rec = "Negligible slippage. Trade freely."

    return SlippageEstimate(
        protocol=protocol,
        token_pair=token_pair,
        trade_size_usd=trade_size_usd,
        pool_liquidity_usd=pool_liquidity_usd,
        price_impact_pct=impact,
        mid_price=mid_price,
        effective_price=effective,
        slippage_cost_usd=cost,
        max_slippage_pct=max_slippage_pct,
        is_within_tolerance=within_tolerance,
        min_pool_liquidity_needed_usd=min_liq,
        pool_fraction_pct=pool_frac,
        slippage_label=label,
        recommendation=rec,
    )


def estimate_market(estimates_data: List[dict]) -> SlippageResult:
    """
    Analyze slippage across multiple pools.

    estimates_data: List[dict] with keys:
        protocol, token_pair, trade_size_usd, pool_liquidity_usd,
        mid_price, max_slippage_pct (optional, default 0.5)
    """
    estimates: List[SlippageEstimate] = []
    for d in estimates_data:
        est = estimate_slippage(
            protocol=d["protocol"],
            token_pair=d["token_pair"],
            trade_size_usd=float(d["trade_size_usd"]),
            pool_liquidity_usd=float(d["pool_liquidity_usd"]),
            mid_price=float(d["mid_price"]),
            max_slippage_pct=float(d.get("max_slippage_pct", 0.5)),
        )
        estimates.append(est)

    if not estimates:
        return SlippageResult(
            estimates=[],
            lowest_slippage_pool="N/A",
            highest_slippage_pool="N/A",
            tradeable_pools=[],
            avg_price_impact_pct=0.0,
            total_slippage_cost_usd=0.0,
            market_liquidity_label="DEEP",
            recommendation_summary="No pools to analyze.",
            saved_to="",
        )

    lowest = min(estimates, key=lambda e: e.price_impact_pct).protocol
    highest = max(estimates, key=lambda e: e.price_impact_pct).protocol
    tradeable = [e.protocol for e in estimates if e.is_within_tolerance]
    avg_impact = sum(e.price_impact_pct for e in estimates) / len(estimates)
    total_cost = sum(e.slippage_cost_usd for e in estimates)

    if avg_impact < 0.1:
        liq_label = "DEEP"
    elif avg_impact < 0.5:
        liq_label = "ADEQUATE"
    else:
        liq_label = "THIN"

    if liq_label == "DEEP":
        rec_summary = "Market liquidity is deep. All pools have minimal slippage."
    elif liq_label == "ADEQUATE":
        rec_summary = "Market liquidity is adequate. Monitor slippage on large trades."
    else:
        rec_summary = "Market liquidity is thin. Split trades and prefer largest pools."

    return SlippageResult(
        estimates=estimates,
        lowest_slippage_pool=lowest,
        highest_slippage_pool=highest,
        tradeable_pools=tradeable,
        avg_price_impact_pct=round(avg_impact, 6),
        total_slippage_cost_usd=round(total_cost, 4),
        market_liquidity_label=liq_label,
        recommendation_summary=rec_summary,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence (ring-buffer 100)
# ---------------------------------------------------------------------------

def _estimate_to_dict(e: SlippageEstimate) -> dict:
    return asdict(e)


def _result_to_dict(result: SlippageResult) -> dict:
    return {
        "estimates": [_estimate_to_dict(e) for e in result.estimates],
        "lowest_slippage_pool": result.lowest_slippage_pool,
        "highest_slippage_pool": result.highest_slippage_pool,
        "tradeable_pools": result.tradeable_pools,
        "avg_price_impact_pct": result.avg_price_impact_pct,
        "total_slippage_cost_usd": result.total_slippage_cost_usd,
        "market_liquidity_label": result.market_liquidity_label,
        "recommendation_summary": result.recommendation_summary,
        "saved_to": result.saved_to,
    }


def load_history(data_file: str = DEFAULT_DATA_FILE) -> list:
    """Load history from JSON ring-buffer file."""
    if not os.path.exists(data_file):
        return []
    try:
        with open(data_file, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def save_results(result: SlippageResult, data_file: str = DEFAULT_DATA_FILE) -> str:
    """Atomically append result to ring-buffer JSON file (cap 100)."""
    history = load_history(data_file)
    history.append(_result_to_dict(result))
    if len(history) > RING_BUFFER_CAP:
        history = history[-RING_BUFFER_CAP:]

    os.makedirs(os.path.dirname(data_file), exist_ok=True)
    atomic_save(history, str(data_file))
    result.saved_to = data_file
    return data_file


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_SAMPLE_DATA = [
    {
        "protocol": "Aave V3",
        "token_pair": "USDC/ETH",
        "trade_size_usd": 10_000,
        "pool_liquidity_usd": 50_000_000,
        "mid_price": 1.0,
        "max_slippage_pct": 0.5,
    },
    {
        "protocol": "Uniswap V3",
        "token_pair": "USDC/ETH",
        "trade_size_usd": 500_000,
        "pool_liquidity_usd": 5_000_000,
        "mid_price": 1.0,
        "max_slippage_pct": 0.5,
    },
    {
        "protocol": "Curve 3pool",
        "token_pair": "USDC/USDT",
        "trade_size_usd": 100_000,
        "pool_liquidity_usd": 200_000_000,
        "mid_price": 1.0,
        "max_slippage_pct": 0.5,
    },
]


def main() -> None:
    mode = "--check"
    data_file = DEFAULT_DATA_FILE
    args = sys.argv[1:]
    if "--run" in args:
        mode = "--run"
    if "--data-dir" in args:
        idx = args.index("--data-dir")
        if idx + 1 < len(args):
            data_file = os.path.join(args[idx + 1], "slippage_impact_log.json")

    result = estimate_market(_SAMPLE_DATA)

    print("=== MP-758 SlippageImpactEstimator ===")
    print(f"Pools analyzed: {len(result.estimates)}")
    print(f"Market liquidity: {result.market_liquidity_label}")
    print(f"Avg price impact: {result.avg_price_impact_pct:.4f}%")
    print(f"Total slippage cost: ${result.total_slippage_cost_usd:.2f}")
    print(f"Tradeable pools: {result.tradeable_pools}")
    print(f"Summary: {result.recommendation_summary}")

    for e in result.estimates:
        print(
            f"  [{e.slippage_label}] {e.protocol} {e.token_pair} "
            f"impact={e.price_impact_pct:.4f}% "
            f"cost=${e.slippage_cost_usd:.2f} "
            f"within_tol={e.is_within_tolerance}"
        )
        print(f"    → {e.recommendation}")

    if mode == "--run":
        save_results(result, data_file)
        print(f"Saved → {result.saved_to}")


if __name__ == "__main__":
    main()
