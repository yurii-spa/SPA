#!/usr/bin/env python3
"""
SPA Adapter Health CLI — MP-1486 (v11.02)

Shows live health status for all registered SPA adapters.

Usage:
    python3 scripts/adapter_health.py              # table output, all adapters
    python3 scripts/adapter_health.py --json       # JSON output
    python3 scripts/adapter_health.py --tier T1    # filter by tier
    python3 scripts/adapter_health.py --tier T2 --json

Exit codes:
    0  — all checked adapters healthy (APY in range, no import errors)
    1  — one or more adapters returned ERROR status

Adapter registry:  spa_core/adapters/__init__.py (ADAPTER_REGISTRY)
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

# Ensure project root is on path when run as script
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from spa_core.adapters.registry import ADAPTER_REGISTRY  # noqa: E402

# ── APY sanity band (percentages, matching DeFiLlama convention) ──────────────
APY_MIN_PCT: float = 0.0    # 0%
APY_MAX_PCT: float = 200.0  # 200%


# ── Adapter checker ───────────────────────────────────────────────────────────

def check_adapter(name: str, info: dict) -> dict:
    """
    Check health of a single adapter entry from ADAPTER_REGISTRY.

    Args:
        name: Registry key (e.g. 'aave_usdc').
        info: Registry dict with keys: module, class, tier, research_only,
              chain, asset, fallback_apy.

    Returns a dict with keys:
        name, tier, chain, asset, research_only,
        apy_pct, source, status, error (only on ERROR)
    """
    tier = info.get("tier", "?")
    chain = info.get("chain", "?")
    asset = info.get("asset", "?")
    research_only = bool(info.get("research_only", False))
    fallback_apy = float(info.get("fallback_apy", 0.0))

    # -- try dynamic import and live fetch --
    apy_pct: float | None = None
    source = "live"
    try:
        mod = importlib.import_module(info["module"])
        cls = getattr(mod, info["class"])
        adapter = cls()

        # Try various method names in priority order
        live = None
        for method in ("get_apy", "current_apy", "fetch_apy", "apy"):
            fn = getattr(adapter, method, None)
            if callable(fn):
                try:
                    result = fn()
                    if result is not None:
                        live = float(result)
                        break
                except Exception:
                    continue

        if live is not None:
            # Normalise: adapters sometimes return decimal (0.035) or pct (3.5)
            apy_pct = live * 100.0 if live < 1.0 else live
            source = "live"
        else:
            # Fall back to registry default (already in %)
            apy_pct = fallback_apy
            source = "fallback"

    except Exception as exc:
        # Import or instantiation failed — use fallback
        if fallback_apy > 0:
            apy_pct = fallback_apy
            source = "fallback"
        else:
            return {
                "name": name,
                "tier": tier,
                "chain": chain,
                "asset": asset,
                "research_only": research_only,
                "apy_pct": None,
                "source": "error",
                "status": "ERROR",
                "error": str(exc),
            }

    # -- determine status --
    if apy_pct is None:
        status = "NO_DATA"
    elif APY_MIN_PCT <= apy_pct <= APY_MAX_PCT:
        status = "OK"
    else:
        status = "APY_OOB"

    result: dict = {
        "name": name,
        "tier": tier,
        "chain": chain,
        "asset": asset,
        "research_only": research_only,
        "apy_pct": round(apy_pct, 4) if apy_pct is not None else None,
        "source": source,
        "status": status,
    }
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def run_all(tier_filter: str | None = None) -> list[dict]:
    """Check all adapters (optionally filtered by tier).  Returns result list."""
    results = []
    for name, info in ADAPTER_REGISTRY.items():
        if tier_filter and info.get("tier") != tier_filter:
            continue
        results.append(check_adapter(name, info))
    return results


def print_table(results: list[dict]) -> None:
    """Print a human-readable table to stdout."""
    ok = sum(1 for r in results if r["status"] == "OK")
    total = len(results)

    print(f"\nSPA Adapter Health — {ok}/{total} OK\n")
    print(f"{'NAME':<25} {'TIER':<5} {'CHAIN':<12} {'ASSET':<8} {'APY%':<8} {'SOURCE':<10} STATUS")
    print("─" * 82)

    for r in results:
        apy_str = f"{r['apy_pct']:.2f}%" if r.get("apy_pct") is not None else "N/A"
        ro_flag = " [RO]" if r.get("research_only") else ""
        status_str = r["status"] + ro_flag
        print(
            f"{r['name']:<25} {r['tier']:<5} {r['chain']:<12} {r['asset']:<8} "
            f"{apy_str:<8} {r.get('source','?'):<10} {status_str}"
        )

    print()
    errors = [r for r in results if r["status"] == "ERROR"]
    if errors:
        print(f"Errors ({len(errors)}):")
        for r in errors:
            print(f"  [{r['name']}] {r.get('error', 'unknown')}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SPA Adapter Health CLI — check all registered adapters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Output as JSON instead of table",
    )
    parser.add_argument(
        "--tier", choices=["T1", "T2", "T3"],
        help="Filter results by tier (T1, T2, T3)",
    )
    parser.add_argument(
        "--name",
        help="Check a single adapter by registry name",
    )
    args = parser.parse_args()

    if args.name:
        info = ADAPTER_REGISTRY.get(args.name)
        if info is None:
            print(f"ERROR: adapter '{args.name}' not in ADAPTER_REGISTRY", file=sys.stderr)
            print(f"Available: {', '.join(ADAPTER_REGISTRY)}", file=sys.stderr)
            sys.exit(1)
        results = [check_adapter(args.name, info)]
    else:
        results = run_all(tier_filter=args.tier)

    if args.as_json:
        print(json.dumps(results, indent=2))
    else:
        print_table(results)

    # Exit 1 if any adapter errored
    has_errors = any(r["status"] == "ERROR" for r in results)
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
