#!/usr/bin/env python3
"""
scripts/find_defillama_sources.py

Searches DeFiLlama yields API for SPA target protocols.

Usage:
  python3 scripts/find_defillama_sources.py
  python3 scripts/find_defillama_sources.py --protocol gmx_v2_btc
  python3 scripts/find_defillama_sources.py --save  # saves results to data/source_discovery.json
  python3 scripts/find_defillama_sources.py --all   # search all TARGET_PROTOCOLS

OUTPUT example:
  === DeFiLlama Source Discovery ===
  Searching for: gmx v2 btc

  Found 3 pools:
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Pool ID: abc123-def456                                                  │
  │ Project: gmx-v2                                                         │
  │ Symbol:  BTC-USD-GLP                                                    │
  │ Chain:   Arbitrum                                                        │
  │ APY:     18.2%                                                           │
  │ TVL:     $45.2M                                                          │
  └─────────────────────────────────────────────────────────────────────────┘

  Recommendation: Use pool ID 'abc123-def456' in gmx_research.py
"""

import json
import os
import sys
import argparse
import tempfile
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFILLAMA_POOLS_URL = "https://yields.llama.fi/pools"
MIN_TVL = 1_000_000  # $1M minimum

TARGET_PROTOCOLS = [
    {"name": "gmx_v2_btc",      "search_project": "gmx-v2",     "search_symbol": "BTC",    "chain": "Arbitrum"},
    {"name": "gmx_v2_eth",      "search_project": "gmx-v2",     "search_symbol": "ETH",    "chain": "Arbitrum"},
    {"name": "btc_stablepool",  "search_project": None,          "search_symbol": "BTC-USDC","chain": "Arbitrum"},
    {"name": "aave_usdc_arb",   "search_project": "aave-v3",    "search_symbol": "USDC",   "chain": "Arbitrum"},
    {"name": "morpho_usdc",     "search_project": "morpho",     "search_symbol": "USDC",   "chain": "Ethereum"},
    {"name": "sky_susds",       "search_project": "sky",        "search_symbol": "sUSDS",  "chain": "Ethereum"},
    {"name": "spark_susds",     "search_project": "spark",      "search_symbol": "sUSDS",  "chain": "Ethereum"},
    {"name": "pendle_pt",       "search_project": "pendle",     "search_symbol": "PT",     "chain": "Ethereum"},
    {"name": "gold_proxy_paxg", "search_project": "uniswap-v3", "search_symbol": "PAXG",   "chain": "Ethereum"},
    {"name": "ondo_ousg",       "search_project": "ondo",       "search_symbol": "OUSG",   "chain": "Ethereum"},
]


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def fetch_pools(timeout: int = 10) -> list:
    """Fetches all pools from DeFiLlama yields API.

    Returns list of pool dicts on success, empty list on any error.
    Never raises.
    """
    try:
        req = urllib.request.Request(
            DEFILLAMA_POOLS_URL,
            headers={"User-Agent": "SPA-discovery/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        # API returns {"status": "ok", "data": [...]}
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def search_pools(
    pools: list,
    project: str = None,
    symbol_kw: str = None,
    chain: str = None,
    min_tvl: float = MIN_TVL,
) -> list:
    """Filters pools by criteria.

    Args:
        pools:      Full list of pool dicts from DeFiLlama.
        project:    Exact project name match (case-insensitive).
        symbol_kw:  Keyword that must appear in pool symbol (case-insensitive).
        chain:      Chain name must match (case-insensitive).
        min_tvl:    Minimum TVL in USD (default MIN_TVL).

    Returns list of matching pool dicts (may be empty).
    """
    if not pools:
        return []

    results = []
    for pool in pools:
        # TVL filter
        tvl = pool.get("tvlUsd") or pool.get("tvl") or 0
        try:
            tvl = float(tvl)
        except (TypeError, ValueError):
            tvl = 0.0
        if tvl < min_tvl:
            continue

        # project filter
        if project is not None:
            pool_project = (pool.get("project") or "").lower()
            if pool_project != project.lower():
                continue

        # symbol keyword filter (case-insensitive substring)
        if symbol_kw is not None:
            pool_symbol = (pool.get("symbol") or "").lower()
            if symbol_kw.lower() not in pool_symbol:
                continue

        # chain filter
        if chain is not None:
            pool_chain = (pool.get("chain") or "").lower()
            if pool_chain != chain.lower():
                continue

        results.append(pool)

    return results


def _fmt_tvl(tvl: float) -> str:
    """Human-readable TVL string."""
    if tvl >= 1_000_000_000:
        return f"${tvl / 1_000_000_000:.1f}B"
    if tvl >= 1_000_000:
        return f"${tvl / 1_000_000:.1f}M"
    if tvl >= 1_000:
        return f"${tvl / 1_000:.1f}K"
    return f"${tvl:.0f}"


def format_pool(pool: dict) -> str:
    """Human-readable box display of a single pool."""
    pool_id  = pool.get("pool") or pool.get("id") or "N/A"
    project  = pool.get("project") or "N/A"
    symbol   = pool.get("symbol") or "N/A"
    chain    = pool.get("chain") or "N/A"
    apy      = pool.get("apy") or pool.get("apyBase") or 0.0
    tvl      = pool.get("tvlUsd") or pool.get("tvl") or 0.0

    try:
        apy = float(apy)
    except (TypeError, ValueError):
        apy = 0.0
    try:
        tvl = float(tvl)
    except (TypeError, ValueError):
        tvl = 0.0

    width = 73
    border = "─" * width
    lines = [
        f"┌{border}┐",
        f"│ Pool ID: {pool_id:<{width - 10}}│",
        f"│ Project: {project:<{width - 10}}│",
        f"│ Symbol:  {symbol:<{width - 10}}│",
        f"│ Chain:   {chain:<{width - 10}}│",
        f"│ APY:     {apy:.1f}%{'':<{width - 13}}│",
        f"│ TVL:     {_fmt_tvl(tvl):<{width - 10}}│",
        f"└{border}┘",
    ]
    return "\n".join(lines)


def discover_all(pools: list) -> dict:
    """Runs search for all TARGET_PROTOCOLS.

    Returns {name: [pool_dict, ...]} — may have empty lists for no-match entries.
    """
    results = {}
    for proto in TARGET_PROTOCOLS:
        name = proto["name"]
        found = search_pools(
            pools,
            project=proto.get("search_project"),
            symbol_kw=proto.get("search_symbol"),
            chain=proto.get("chain"),
            min_tvl=MIN_TVL,
        )
        results[name] = found
    return results


def save_discovery(results: dict, path: str = "data/source_discovery.json") -> str:
    """Saves discovery results atomically (tmp + os.replace).

    Returns the absolute path to the written file.
    """
    # Ensure directory exists
    dir_path = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_path, exist_ok=True)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "min_tvl": MIN_TVL,
        "total_protocols_searched": len(results),
        "results": {
            name: pools
            for name, pools in results.items()
        },
        "summary": {
            name: {
                "found": len(pools),
                "top_pool_id": pools[0].get("pool") or pools[0].get("id") if pools else None,
            }
            for name, pools in results.items()
        },
    }

    abs_path = os.path.abspath(path)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(abs_path),
        prefix=".tmp_source_discovery_",
        suffix=".json",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return abs_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_results_for_name(name: str, pools: list, verbose: bool = True) -> None:
    proto = next((p for p in TARGET_PROTOCOLS if p["name"] == name), None)
    label = f"{proto['search_project'] or ''} {proto['search_symbol'] or ''} {proto['chain'] or ''}".strip() if proto else name

    print(f"\nSearching for: {label}")
    if not pools:
        print("  (no pools found above TVL threshold)")
        return
    print(f"\nFound {len(pools)} pool(s):")
    for pool in pools:
        print(format_pool(pool))
        print()
    # Recommendation
    best = pools[0]
    best_id = best.get("pool") or best.get("id")
    print(f"Recommendation: Use pool ID '{best_id}' as primary source for '{name}'")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="DeFiLlama Source Discovery — find pool IDs for SPA target protocols",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--protocol",
        metavar="NAME",
        help="Search single protocol by name (e.g. gmx_v2_btc). "
             "Use --all for all protocols.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Search all TARGET_PROTOCOLS",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save results to data/source_discovery.json (atomic write)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        metavar="SECS",
        help="HTTP timeout in seconds (default: 15)",
    )
    args = parser.parse_args(argv)

    print("=== DeFiLlama Source Discovery ===")
    print(f"Fetching pools from {DEFILLAMA_POOLS_URL} …", flush=True)

    pools = fetch_pools(timeout=args.timeout)
    if not pools:
        print("ERROR: Could not fetch pools (network error or empty response).", file=sys.stderr)
        print("       Check connectivity and try again.", file=sys.stderr)
        return 1

    print(f"Loaded {len(pools):,} total pools from DeFiLlama.\n")

    if args.protocol:
        # single protocol
        target = next((p for p in TARGET_PROTOCOLS if p["name"] == args.protocol), None)
        if target is None:
            print(f"ERROR: Unknown protocol name '{args.protocol}'.", file=sys.stderr)
            print("Available names:", ", ".join(p["name"] for p in TARGET_PROTOCOLS), file=sys.stderr)
            return 1
        found = search_pools(
            pools,
            project=target.get("search_project"),
            symbol_kw=target.get("search_symbol"),
            chain=target.get("chain"),
            min_tvl=MIN_TVL,
        )
        _print_results_for_name(args.protocol, found)
        if args.save:
            path = save_discovery({args.protocol: found})
            print(f"\nSaved to: {path}")
    else:
        # all (default if no --protocol)
        results = discover_all(pools)
        for name, found in results.items():
            _print_results_for_name(name, found)
        if args.save:
            path = save_discovery(results)
            print(f"\n\nSaved full discovery to: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
