"""
MP-844 ProtocolFeeTierAnalyzer
================================
Advisory-only analytics module. Analyzes fee tier distribution and liquidity
concentration across Uniswap-style AMM pools to identify the optimal fee tier
for providing liquidity and predict fee revenue.

Output: data/fee_tier_log.json  (ring-buffer, cap 100, atomic write)
CLI:
    python3 -m spa_core.analytics.protocol_fee_tier_analyzer --check
    python3 -m spa_core.analytics.protocol_fee_tier_analyzer --run [--data-dir DIR]
"""

from __future__ import annotations

import json
import os
import sys
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_LOG_CAP = 100
_DEFAULT_MIN_TVL_USD = 100_000.0
_DEFAULT_MIN_VOLUME_USD = 10_000.0

# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------

def _fee_tier_label(fee_tier_bps: int) -> str:
    """Convert basis points to label, e.g. 30 → '0.30%'."""
    return f"{fee_tier_bps / 100:.2f}%"


def _volume_to_tvl_ratio(volume_24h_usd: float, tvl_usd: float) -> float:
    if tvl_usd <= 0.0:
        return 0.0
    return volume_24h_usd / tvl_usd


def _annualized_fee_yield_pct(
    volume_24h_usd: float,
    fee_tier_bps: int,
    tvl_usd: float,
) -> float:
    """Annual fee yield as percent: (vol * fee%) / tvl * 365 * 100."""
    if tvl_usd <= 0.0:
        return 0.0
    return (volume_24h_usd * fee_tier_bps / 10_000.0) / tvl_usd * 365.0 * 100.0


def _effective_yield_pct(annualized_fee_yield: float, in_range_pct: float) -> float:
    return annualized_fee_yield * in_range_pct / 100.0


def _capital_efficiency(liquidity_concentration: float, in_range_pct: float) -> str:
    if liquidity_concentration >= 0.7 and in_range_pct >= 80.0:
        return "HIGH"
    if liquidity_concentration >= 0.4 or in_range_pct >= 60.0:
        return "MEDIUM"
    return "LOW"


def _range_risk(in_range_pct: float) -> str:
    if in_range_pct >= 85.0:
        return "LOW"
    if in_range_pct >= 60.0:
        return "MEDIUM"
    return "HIGH"


def _lp_recommendation(
    effective_yield_pct: float,
    range_risk_val: str,
    in_range_pct: float,
    filtered: bool,
) -> str:
    if filtered:
        return "SKIP"
    if effective_yield_pct >= 10.0 and range_risk_val in ("LOW", "MEDIUM"):
        return "PREFERRED"
    if range_risk_val == "HIGH" and in_range_pct < 40.0:
        return "SKIP"
    return "VIABLE"


def _is_filtered(
    tvl_usd: float,
    volume_24h_usd: float,
    min_tvl_usd: float,
    min_volume_usd: float,
) -> bool:
    return tvl_usd < min_tvl_usd or volume_24h_usd < min_volume_usd


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(pools: list[dict], config: dict | None = None) -> dict:
    """
    Analyze AMM fee tiers and return LP recommendations.

    Parameters
    ----------
    pools  : list of pool dicts.
    config : optional overrides for min_tvl_usd, min_volume_usd.

    Returns
    -------
    dict with keys: pools, best_pool, pair_summary, total_tvl_analyzed_usd, timestamp.
    """
    cfg = config or {}
    min_tvl_usd: float = float(cfg.get("min_tvl_usd", _DEFAULT_MIN_TVL_USD))
    min_volume_usd: float = float(cfg.get("min_volume_usd", _DEFAULT_MIN_VOLUME_USD))

    processed: list[dict] = []
    pair_data: dict[str, list[dict]] = {}

    for pool in pools:
        protocol: str = pool.get("protocol", "")
        pair: str = pool.get("pair", "")
        fee_tier_bps: int = int(pool.get("fee_tier_bps", 0))
        tvl_usd: float = float(pool.get("tvl_usd", 0.0))
        volume_24h_usd: float = float(pool.get("volume_24h_usd", 0.0))
        liquidity_concentration: float = float(pool.get("liquidity_concentration", 0.0))
        in_range_pct: float = float(pool.get("in_range_pct", 0.0))

        filtered = _is_filtered(tvl_usd, volume_24h_usd, min_tvl_usd, min_volume_usd)

        label = _fee_tier_label(fee_tier_bps)
        vol_tvl = _volume_to_tvl_ratio(volume_24h_usd, tvl_usd)
        ann_yield = _annualized_fee_yield_pct(volume_24h_usd, fee_tier_bps, tvl_usd)
        eff_yield = _effective_yield_pct(ann_yield, in_range_pct)
        cap_eff = _capital_efficiency(liquidity_concentration, in_range_pct)
        rr = _range_risk(in_range_pct)
        lp_rec = _lp_recommendation(eff_yield, rr, in_range_pct, filtered)

        entry = {
            "protocol": protocol,
            "pair": pair,
            "fee_tier_bps": fee_tier_bps,
            "fee_tier_label": label,
            "volume_to_tvl_ratio": vol_tvl,
            "annualized_fee_yield_pct": ann_yield,
            "effective_yield_pct": eff_yield,
            "capital_efficiency": cap_eff,
            "range_risk": rr,
            "lp_recommendation": lp_rec,
            "filtered": filtered,
        }
        processed.append(entry)

        # Collect non-filtered for pair_summary
        if not filtered:
            if pair not in pair_data:
                pair_data[pair] = []
            pair_data[pair].append(entry)

    # best_pool: non-filtered, recommendation != SKIP, highest effective_yield_pct
    viable = [p for p in processed if not p["filtered"] and p["lp_recommendation"] != "SKIP"]
    best_pool: dict | None = None
    if viable:
        best_pool = max(viable, key=lambda p: p["effective_yield_pct"])

    # pair_summary
    pair_summary: dict[str, dict] = {}
    for pair, entries in pair_data.items():
        best = max(entries, key=lambda e: e["effective_yield_pct"])
        pair_summary[pair] = {
            "pool_count": len(entries),
            "best_fee_tier_bps": best["fee_tier_bps"],
            "best_effective_yield": best["effective_yield_pct"],
        }

    # total_tvl_analyzed: sum of non-filtered pools
    total_tvl = sum(
        float(pools[i].get("tvl_usd", 0.0))
        for i, p in enumerate(processed)
        if not p["filtered"]
    )

    return {
        "pools": processed,
        "best_pool": best_pool,
        "pair_summary": pair_summary,
        "total_tvl_analyzed_usd": total_tvl,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Ring-buffer log
# ---------------------------------------------------------------------------

def _log_result(result: dict, data_dir: str) -> None:
    """Append result to the ring-buffer log (atomic write)."""
    log_path = os.path.join(data_dir, "fee_tier_log.json")
    tmp_path = log_path + ".tmp"

    entries: list = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                entries = json.load(fh)
        except (json.JSONDecodeError, OSError):
            entries = []

    entries.append(result)
    if len(entries) > _LOG_CAP:
        entries = entries[-_LOG_CAP:]

    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2)
    os.replace(tmp_path, log_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_demo_pools() -> list[dict]:
    return [
        {
            "protocol": "Uniswap V3",
            "pair": "USDC/ETH",
            "fee_tier_bps": 5,
            "tvl_usd": 50_000_000.0,
            "volume_24h_usd": 5_000_000.0,
            "liquidity_concentration": 0.8,
            "in_range_pct": 90.0,
        },
        {
            "protocol": "Uniswap V3",
            "pair": "USDC/ETH",
            "fee_tier_bps": 30,
            "tvl_usd": 10_000_000.0,
            "volume_24h_usd": 2_000_000.0,
            "liquidity_concentration": 0.6,
            "in_range_pct": 75.0,
        },
        {
            "protocol": "Uniswap V3",
            "pair": "WBTC/ETH",
            "fee_tier_bps": 30,
            "tvl_usd": 20_000_000.0,
            "volume_24h_usd": 1_000_000.0,
            "liquidity_concentration": 0.5,
            "in_range_pct": 65.0,
        },
        {
            "protocol": "Uniswap V3",
            "pair": "ETH/USDT",
            "fee_tier_bps": 100,
            "tvl_usd": 500.0,   # filtered: below min TVL
            "volume_24h_usd": 200.0,
            "liquidity_concentration": 0.3,
            "in_range_pct": 40.0,
        },
    ]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MP-844 ProtocolFeeTierAnalyzer")
    parser.add_argument("--run", action="store_true", help="Compute and write log")
    parser.add_argument("--check", action="store_true", help="Compute and print (no write)")
    parser.add_argument("--data-dir", default=None, help="Override data directory")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
    data_dir = args.data_dir or os.path.join(repo_root, "data")

    pools = _default_demo_pools()
    result = analyze(pools)

    print(json.dumps(result, indent=2))

    if args.run:
        _log_result(result, data_dir)
        print(f"\n[MP-844] Log written → {os.path.join(data_dir, 'fee_tier_log.json')}")


if __name__ == "__main__":
    main()
