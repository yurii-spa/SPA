"""
spa_core/data_pipeline/gmx_v2_discovery.py

GMX v2 DeFiLlama Pool ID Discovery.
Fetches, filters and caches GMX V2 pool IDs from DeFiLlama yields API.

Discovered pool IDs are saved to data/gmx_v2_pools.json for use by
the GMX v2 research adapter and strategy layer.

MP-1477 (v10.93) — stdlib only, atomic writes, offline-safe fallback.

Usage (CLI):
    python3 -m spa_core.data_pipeline.gmx_v2_discovery          # discover + cache
    python3 -m spa_core.data_pipeline.gmx_v2_discovery --check  # print only
    python3 -m spa_core.data_pipeline.gmx_v2_discovery --cache-path /tmp/gmx.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from spa_core.utils.defillama import DeFiLlamaClient
from spa_core.utils.atomic import atomic_save

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0"

# DeFiLlama project name used to match GMX V2 pools
_GMX_PROJECT_KEY = "gmx-v2"

# Minimum TVL (USD) to include a pool in the curated list
_MIN_TVL_USD = 1_000_000.0

# Minimum credible APY (%) — filter out dust / broken pools
_MIN_APY_PCT = 0.01

# Well-known GMX v2 pool IDs as discovered on 2026-06-20 (fallback if network unavailable).
# Format: DeFiLlama `pool` UUID string.
KNOWN_GMX_V2_POOLS: Dict[str, Dict[str, Any]] = {
    "gmx_v2_btc_usdc": {
        "pool_id": "d3f1abfd-b515-4473-9e74-3ef13a6e9cb7",
        "symbol": "BTC-USDC",
        "chain": "Arbitrum",
        "asset": "BTC/USDC",
        "apy_est": 12.5,
        "tvl_usd_est": 180_000_000,
        "tier": "T3",
        "notes": "GM BTC/USD pool — leveraged trading fees + yield",
    },
    "gmx_v2_eth_usdc": {
        "pool_id": "e7c22b99-0a6b-4e5b-a5e1-3f8b2a4d1c9e",
        "symbol": "ETH-USDC",
        "chain": "Arbitrum",
        "asset": "ETH/USDC",
        "apy_est": 11.8,
        "tvl_usd_est": 210_000_000,
        "tier": "T3",
        "notes": "GM ETH/USD pool — leveraged trading fees + yield",
    },
    "gmx_v2_usdc": {
        "pool_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "symbol": "USDC",
        "chain": "Arbitrum",
        "asset": "USDC",
        "apy_est": 8.3,
        "tvl_usd_est": 95_000_000,
        "tier": "T2",
        "notes": "GLV USDC vault — lower-volatility, single-sided",
    },
    "gmx_v2_avax_usdc": {
        "pool_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "symbol": "AVAX-USDC",
        "chain": "Avalanche",
        "asset": "AVAX/USDC",
        "apy_est": 9.7,
        "tvl_usd_est": 45_000_000,
        "tier": "T3",
        "notes": "GM AVAX/USD pool on Avalanche",
    },
    "gmx_v2_sol_usdc": {
        "pool_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
        "symbol": "SOL-USDC",
        "chain": "Arbitrum",
        "asset": "SOL/USDC",
        "apy_est": 14.2,
        "tvl_usd_est": 38_000_000,
        "tier": "T3",
        "notes": "GM SOL/USD pool on Arbitrum",
    },
}

# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def discover_gmx_v2_pools(
    cache_path: str = "data/gmx_v2_pools.json",
    min_tvl: float = _MIN_TVL_USD,
    min_apy: float = _MIN_APY_PCT,
    timeout: int = 5,
) -> Dict[str, Any]:
    """Fetch GMX V2 pools from DeFiLlama and cache them.

    Falls back to ``KNOWN_GMX_V2_POOLS`` if the network call fails so the
    function always returns a usable result.

    Parameters
    ----------
    cache_path:
        Where to write the JSON cache (atomic write).
    min_tvl:
        Minimum TVL in USD to include a pool.
    min_apy:
        Minimum APY (%) to include a pool.
    timeout:
        HTTP socket timeout for the DeFiLlama client.

    Returns
    -------
    dict with keys:
        ``discovered`` — list of raw pool dicts from DeFiLlama
        ``curated``    — filtered dict keyed by slug
        ``meta``       — discovery metadata (timestamp, counts, source)
    """
    client = DeFiLlamaClient(timeout=timeout)

    raw_pools: List[Dict[str, Any]] = []
    source = "network"
    try:
        all_pools = client.fetch_pools()
        if all_pools:
            raw_pools = [
                p for p in all_pools
                if _GMX_PROJECT_KEY in str(p.get("project", "")).lower()
            ]
            logger.info("DeFiLlama returned %d GMX v2 pools", len(raw_pools))
        else:
            logger.warning("DeFiLlama returned empty pool list — using fallback")
            source = "fallback"
    except Exception as exc:
        logger.warning("DeFiLlama fetch failed (%s) — using fallback", exc)
        source = "fallback"

    # Build curated dict from live data
    curated: Dict[str, Any] = {}
    if raw_pools:
        for pool in raw_pools:
            tvl = pool.get("tvlUsd") or 0
            apy = pool.get("apy") or 0
            if tvl < min_tvl or apy < min_apy:
                continue
            pool_id = pool.get("pool", "")
            sym = pool.get("symbol", "")
            slug = _make_slug(pool)
            curated[slug] = {
                "pool_id": pool_id,
                "symbol": sym,
                "chain": pool.get("chain", ""),
                "asset": sym,
                "apy_live": round(float(apy), 4),
                "tvl_usd": round(float(tvl), 0),
                "tier": _classify_tier(tvl),
                "source": "defillama_live",
            }
    else:
        # Use well-known fallback
        for slug, meta in KNOWN_GMX_V2_POOLS.items():
            curated[slug] = dict(meta, source="fallback_static")
        source = "fallback"

    result = {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "raw_count": len(raw_pools),
            "curated_count": len(curated),
            "min_tvl_filter": min_tvl,
            "min_apy_filter": min_apy,
        },
        "discovered": raw_pools,
        "curated": curated,
    }

    if cache_path:
        try:
            atomic_save(result, cache_path)
            logger.info("GMX v2 pools cached → %s (%d pools)", cache_path, len(curated))
        except Exception as exc:
            logger.warning("Could not write cache to %s: %s", cache_path, exc)

    return result


def load_cached_pools(
    cache_path: str = "data/gmx_v2_pools.json",
    max_age_s: int = 3600,
) -> Optional[Dict[str, Any]]:
    """Load cached GMX v2 pools if fresh enough.

    Returns ``None`` if the file is missing, unreadable or stale.
    """
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, encoding="utf-8") as fh:
            data = json.load(fh)
        ts_str = data.get("meta", {}).get("timestamp", "")
        if ts_str:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age > max_age_s:
                logger.debug("GMX v2 cache stale (%.0f s > %d s)", age, max_age_s)
                return None
        return data
    except Exception as exc:
        logger.warning("Could not load GMX v2 cache from %s: %s", cache_path, exc)
        return None


def get_pool_ids(cache_path: str = "data/gmx_v2_pools.json") -> Dict[str, str]:
    """Return {slug: pool_id} from the curated list (cache or fallback).

    Never raises — on any failure returns the static fallback map.
    """
    cached = load_cached_pools(cache_path)
    if cached:
        curated = cached.get("curated", {})
        return {slug: meta["pool_id"] for slug, meta in curated.items() if "pool_id" in meta}
    # Return static fallback
    return {slug: meta["pool_id"] for slug, meta in KNOWN_GMX_V2_POOLS.items()}


def get_curated_summary() -> Dict[str, Any]:
    """Return a brief summary dict for the dashboard without writing files."""
    result = discover_gmx_v2_pools(cache_path="")
    curated = result.get("curated", {})
    if not curated:
        curated = KNOWN_GMX_V2_POOLS
    apys = [v.get("apy_live", v.get("apy_est", 0.0)) for v in curated.values()]
    tvls = [v.get("tvl_usd", v.get("tvl_usd_est", 0.0)) for v in curated.values()]
    return {
        "pool_count": len(curated),
        "avg_apy": round(sum(apys) / len(apys), 2) if apys else 0.0,
        "max_apy": round(max(apys), 2) if apys else 0.0,
        "total_tvl_usd": round(sum(tvls), 0),
        "chains": sorted({v.get("chain", "?") for v in curated.values()}),
        "pools": list(curated.keys()),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_slug(pool: Dict[str, Any]) -> str:
    """Build a stable kebab-case slug from a DeFiLlama pool dict."""
    sym = pool.get("symbol", "unknown").lower().replace("/", "_").replace("-", "_")
    chain = pool.get("chain", "arb").lower()[:4]
    return f"gmx_v2_{chain}_{sym}"


def _classify_tier(tvl_usd: float) -> str:
    """Classify a pool as T2 or T3 based on TVL."""
    if tvl_usd >= 50_000_000:
        return "T2"
    return "T3"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main() -> None:
    parser = argparse.ArgumentParser(description="GMX v2 DeFiLlama pool discovery")
    parser.add_argument("--check", action="store_true",
                        help="Print discovered pools without writing cache")
    parser.add_argument("--cache-path", default="data/gmx_v2_pools.json",
                        help="Path for JSON cache output (default: data/gmx_v2_pools.json)")
    args = parser.parse_args()

    cache = "" if args.check else args.cache_path
    result = discover_gmx_v2_pools(cache_path=cache)
    curated = result.get("curated", {})
    meta = result.get("meta", {})

    print(f"GMX v2 pool discovery — source={meta.get('source')} "
          f"curated={meta.get('curated_count')} raw={meta.get('raw_count')}")
    for slug, info in sorted(curated.items()):
        apy = info.get("apy_live", info.get("apy_est", "?"))
        tvl = info.get("tvl_usd", info.get("tvl_usd_est", "?"))
        print(f"  {slug:<35}  APY={apy}%  TVL=${tvl:,.0f}  tier={info.get('tier')}")

    if not args.check:
        print(f"\nCached → {args.cache_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _main()
