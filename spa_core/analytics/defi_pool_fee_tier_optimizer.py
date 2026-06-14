"""
MP-889: DeFiPoolFeeTierOptimizer
Selects the optimal fee tier for LP positions based on volume, volatility,
and capital efficiency using IL-adjusted net-score.

Advisory / read-only. Pure stdlib. Atomic JSON writes.
"""

import json
import os
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "fee_tier_optimization_log.json"
)
_LOG_CAP = 100

_DEFAULT_CONFIG: dict = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fee_per_day(capital_usd: float, tier_bps: int,
                 daily_volume_usd: float, tvl_usd: float) -> float:
    """Fee revenue per day for this LP position.

    fee_per_day = capital * (tier_bps / 10000) * (daily_volume / tvl)
    if tvl > 0 else 0.
    """
    if tvl_usd <= 0:
        return 0.0
    return capital_usd * (tier_bps / 10_000) * (daily_volume_usd / tvl_usd)


def _il_risk_score(volatility_30d_pct: float, tier_bps: int) -> int:
    """IL risk score 0–100.

    il_risk_score = min(100, int(volatility_30d_pct / (tier_bps * 0.1 + 1)))
    """
    return min(100, int(volatility_30d_pct / (tier_bps * 0.1 + 1)))


def _net_score(fpd: float, il_score: int) -> float:
    """Net score: fee_per_day * (1 - il_risk_score / 200)."""
    return fpd * (1 - il_score / 200.0)


def _build_tier_analysis(pool: dict) -> list:
    """Build per-tier analysis list for a pool."""
    capital = pool.get("capital_usd", 0.0)
    daily_vol = pool.get("daily_volume_usd", 0.0)
    tvl = pool.get("tvl_usd", 0.0)
    vol30 = pool.get("volatility_30d_pct", 0.0)
    tiers = pool.get("available_tiers_bps", [])

    result = []
    for t in tiers:
        fpd = _fee_per_day(capital, t, daily_vol, tvl)
        il = _il_risk_score(vol30, t)
        ndp = (fpd / capital * 100.0) if capital > 0 else 0.0
        ann = ndp * 365.0
        result.append({
            "tier_bps": t,
            "fee_per_day_usd": fpd,
            "il_risk_score": il,
            "net_daily_yield_pct": ndp,
            "annualized_yield_pct": ann,
        })
    return result


def _select_optimal_tier(tier_analysis: list, current_tier_bps: int) -> int:
    """Choose optimal tier: highest net_score; tie → highest tier_bps.

    Falls back to current_tier_bps if tier_analysis is empty.
    """
    if not tier_analysis:
        return current_tier_bps

    best = None
    best_score = None
    for ta in tier_analysis:
        fpd = ta["fee_per_day_usd"]
        il = ta["il_risk_score"]
        score = _net_score(fpd, il)
        if best_score is None or score > best_score or (
            score == best_score and ta["tier_bps"] > best["tier_bps"]
        ):
            best_score = score
            best = ta
    return best["tier_bps"]  # type: ignore[index]


def _build_rationale(pool: dict, optimal_tier: int) -> str:
    """Produce a human-readable rationale string."""
    current = pool.get("current_tier_bps", 0)
    vol = pool.get("volatility_30d_pct", 0.0)
    tvl = pool.get("tvl_usd", 0.0)
    daily_vol = pool.get("daily_volume_usd", 0.0)

    vol_tvl_ratio = (daily_vol / tvl) if tvl > 0 else 0.0

    if vol > 50 and optimal_tier >= 30:
        return "High volatility pair. Higher fee tier compensates IL risk."
    if vol_tvl_ratio > 0.5:
        return "High volume/TVL ratio. Any tier generates strong yield."
    if optimal_tier < current:
        return "Reducing fee tier: lower volatility suggests tighter spread is competitive."
    if optimal_tier > current:
        return "Increasing fee tier: volatility risk warrants higher fee protection."
    return "Current tier optimal. No change needed."


def _analyze_pool(pool: dict) -> dict:
    """Analyze a single pool and return its result dict."""
    pair = pool.get("pair", "")
    current_tier = pool.get("current_tier_bps", 0)
    capital = pool.get("capital_usd", 0.0)
    position_days = pool.get("position_days", 0)

    tier_analysis = _build_tier_analysis(pool)
    optimal_tier = _select_optimal_tier(tier_analysis, current_tier)

    # projected_earnings: optimal tier's fee_per_day * position_days
    opt_ta = next((t for t in tier_analysis if t["tier_bps"] == optimal_tier), None)
    projected_earnings = 0.0
    if opt_ta is not None:
        projected_earnings = opt_ta["fee_per_day_usd"] * position_days

    tier_change = optimal_tier != current_tier
    rationale = _build_rationale(pool, optimal_tier)

    return {
        "pair": pair,
        "current_tier_bps": current_tier,
        "optimal_tier_bps": optimal_tier,
        "tier_analysis": tier_analysis,
        "projected_earnings_usd": projected_earnings,
        "tier_change_recommended": tier_change,
        "rationale": rationale,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(pools: list, config: dict = None) -> dict:
    """Analyze LP pools and select optimal fee tiers.

    Parameters
    ----------
    pools : list of pool dicts (see module docstring)
    config : optional config dict (unused in v1, reserved)

    Returns
    -------
    dict with keys: pools, summary, timestamp
    """
    _ = config  # reserved

    if not pools:
        return {
            "pools": [],
            "summary": {
                "pools_needing_rebalance": 0,
                "average_optimal_yield_pct": 0.0,
                "total_projected_earnings_usd": 0.0,
            },
            "timestamp": time.time(),
        }

    pool_results = [_analyze_pool(p) for p in pools]

    pools_needing_rebalance = sum(
        1 for pr in pool_results if pr["tier_change_recommended"]
    )

    # average_optimal_yield_pct: mean of annualized_yield_pct at optimal tier
    opt_yields = []
    for pr in pool_results:
        opt_tier = pr["optimal_tier_bps"]
        ta = next((t for t in pr["tier_analysis"] if t["tier_bps"] == opt_tier), None)
        if ta is not None:
            opt_yields.append(ta["annualized_yield_pct"])

    avg_yield = (sum(opt_yields) / len(opt_yields)) if opt_yields else 0.0
    total_earnings = sum(pr["projected_earnings_usd"] for pr in pool_results)

    return {
        "pools": pool_results,
        "summary": {
            "pools_needing_rebalance": pools_needing_rebalance,
            "average_optimal_yield_pct": avg_yield,
            "total_projected_earnings_usd": total_earnings,
        },
        "timestamp": time.time(),
    }


def run_and_log(pools: list, config: dict = None,
                data_file: str = _DATA_FILE) -> dict:
    """Run analyze() and append result to ring-buffer JSON log.

    Atomic write via tmp+os.replace. Ring-buffer capped at _LOG_CAP entries.
    """
    result = analyze(pools, config)

    data_dir = os.path.dirname(data_file)
    os.makedirs(data_dir, exist_ok=True)

    # Load existing log
    try:
        with open(data_file) as f:
            log: list = json.load(f)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(result)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]

    tmp = data_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(log, f, indent=2)
    os.replace(tmp, data_file)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    mode = "--check"
    data_dir = None
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a in ("--check", "--run"):
            mode = a
        if a == "--data-dir" and i + 1 < len(args):
            data_dir = args[i + 1]

    # Demo pools for smoke-test
    demo_pools = [
        {
            "pair": "ETH/USDC",
            "available_tiers_bps": [1, 5, 30, 100],
            "daily_volume_usd": 50_000_000,
            "tvl_usd": 100_000_000,
            "volatility_30d_pct": 45.0,
            "current_tier_bps": 5,
            "capital_usd": 100_000,
            "position_days": 30,
        },
        {
            "pair": "USDC/USDT",
            "available_tiers_bps": [1, 5],
            "daily_volume_usd": 200_000_000,
            "tvl_usd": 500_000_000,
            "volatility_30d_pct": 0.5,
            "current_tier_bps": 1,
            "capital_usd": 200_000,
            "position_days": 60,
        },
    ]

    if mode == "--run":
        df = os.path.join(data_dir or "data", "fee_tier_optimization_log.json")
        r = run_and_log(demo_pools, data_file=df)
    else:
        r = analyze(demo_pools)

    print(json.dumps(r, indent=2))
