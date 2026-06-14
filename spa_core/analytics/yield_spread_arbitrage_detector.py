"""
YieldSpreadArbitrageDetector (MP-841)
======================================
Detects yield spread arbitrage opportunities between protocols offering the
same or equivalent assets at different rates, accounting for gas costs and
execution risk.

Advisory / read-only module — never moves capital, never modifies risk/,
execution/, monitoring/, or allocator/. Pure stdlib, atomic writes.

analyze(markets, config) -> dict

Output ring-buffer (100 entries): data/yield_spread_arb_log.json

Design constraints
------------------
* Pure stdlib — no numpy / scipy / requests / web3 / pandas.
* Advisory only — read-only, never touches execution domain.
* Atomic writes: tmp + os.replace.
* Never raises on the happy path; malformed input degrades gracefully.

CLI
---
``python3 -m spa_core.analytics.yield_spread_arbitrage_detector --check``
``python3 -m spa_core.analytics.yield_spread_arbitrage_detector --run``
``python3 -m spa_core.analytics.yield_spread_arbitrage_detector --data-dir PATH``

MP-841.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RING_BUFFER_MAX: int = 100
_DEFAULT_DATA_FILE: str = "yield_spread_arb_log.json"
_DEFAULT_MIN_SPREAD_PCT: float = 0.5
_DEFAULT_MIN_NET_PROFIT_USD: float = 10.0

# Viability thresholds on net_spread_pct
_VIABILITY_EXCELLENT_THRESHOLD: float = 2.0
_VIABILITY_GOOD_THRESHOLD: float = 1.0
_VIABILITY_MARGINAL_THRESHOLD: float = 0.0

# ---------------------------------------------------------------------------
# Core logic helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Coerce a value to float, returning default on failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _viability(net_spread_pct: float, net_annual_profit_usd: float,
               min_net_profit_usd: float) -> str:
    """Return viability tier for an opportunity."""
    if net_annual_profit_usd < min_net_profit_usd:
        return "UNVIABLE"
    if net_spread_pct >= _VIABILITY_EXCELLENT_THRESHOLD:
        return "EXCELLENT"
    if net_spread_pct >= _VIABILITY_GOOD_THRESHOLD:
        return "GOOD"
    return "MARGINAL"


def _risk_note(viability: str, asset: str, gross_spread_pct: float) -> str:
    """Return a human-readable risk note for an opportunity."""
    if viability == "EXCELLENT":
        return f"Strong arbitrage — {gross_spread_pct:.2f}% gross spread on {asset}"
    if viability == "GOOD":
        return f"Good spread on {asset} — monitor gas costs"
    if viability == "MARGINAL":
        return f"Thin margin on {asset} — gas-sensitive"
    return f"Gas costs eat spread on {asset}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze(markets: List[Dict], config: Optional[Dict] = None) -> Dict:
    """
    Detect yield spread arbitrage opportunities.

    markets: list of {
        "protocol": str,
        "asset": str,
        "side": "LEND" | "BORROW",
        "apy": float,
        "available_liquidity_usd": float,
        "min_position_usd": float,
        "gas_cost_usd": float
    }
    config: {
        "min_spread_pct": float,      # default 0.5
        "min_net_profit_usd": float   # default 10.0
    }

    Returns analysis dict with opportunities list and summary fields.
    """
    cfg = config or {}
    min_spread_pct = _safe_float(cfg.get("min_spread_pct"), _DEFAULT_MIN_SPREAD_PCT)
    min_net_profit = _safe_float(cfg.get("min_net_profit_usd"), _DEFAULT_MIN_NET_PROFIT_USD)

    opportunities: List[Dict] = []
    assets_seen: set = set()

    # Group by asset
    lend_map: Dict[str, List[Dict]] = {}
    borrow_map: Dict[str, List[Dict]] = {}

    for mkt in (markets or []):
        asset = str(mkt.get("asset", "")).strip()
        if not asset:
            continue
        side = str(mkt.get("side", "")).upper()
        assets_seen.add(asset)
        entry = {
            "protocol": str(mkt.get("protocol", "")),
            "asset": asset,
            "apy": _safe_float(mkt.get("apy"), 0.0),
            "available_liquidity_usd": _safe_float(mkt.get("available_liquidity_usd"), 0.0),
            "min_position_usd": _safe_float(mkt.get("min_position_usd"), 0.0),
            "gas_cost_usd": _safe_float(mkt.get("gas_cost_usd"), 0.0),
        }
        if side == "LEND":
            lend_map.setdefault(asset, []).append(entry)
        elif side == "BORROW":
            borrow_map.setdefault(asset, []).append(entry)

    # For each asset, enumerate (lend, borrow) pairs
    for asset in sorted(assets_seen):
        lenders = lend_map.get(asset, [])
        borrowers = borrow_map.get(asset, [])
        for lend in lenders:
            for borrow in borrowers:
                # Must be different protocols
                if lend["protocol"] == borrow["protocol"]:
                    continue
                # lend APY must exceed borrow APY
                lend_apy = lend["apy"]
                borrow_apy = borrow["apy"]
                if lend_apy <= borrow_apy:
                    continue
                gross_spread = lend_apy - borrow_apy
                # Filter on gross spread threshold
                if gross_spread < min_spread_pct:
                    continue
                # Compute position size
                max_position = min(
                    lend["available_liquidity_usd"],
                    borrow["available_liquidity_usd"],
                )
                # Must meet both minimums
                required_min = max(lend["min_position_usd"], borrow["min_position_usd"])
                if max_position < required_min:
                    continue
                # Gas
                gas_total = lend["gas_cost_usd"] + borrow["gas_cost_usd"]
                # Gas drag as % of position per year
                if max_position > 0:
                    gas_drag_pct = (gas_total / max_position) * 100.0
                else:
                    gas_drag_pct = 999.0
                net_spread_pct = gross_spread - gas_drag_pct
                estimated_annual_profit = (net_spread_pct / 100.0) * max_position
                net_annual_profit = estimated_annual_profit - gas_total
                viab = _viability(net_spread_pct, net_annual_profit, min_net_profit)
                note = _risk_note(viab, asset, gross_spread)
                opportunities.append({
                    "asset": asset,
                    "lend_protocol": lend["protocol"],
                    "borrow_protocol": borrow["protocol"],
                    "lend_apy": lend_apy,
                    "borrow_apy": borrow_apy,
                    "gross_spread_pct": gross_spread,
                    "net_spread_pct": net_spread_pct,
                    "max_position_usd": max_position,
                    "estimated_annual_profit_usd": estimated_annual_profit,
                    "gas_total_usd": gas_total,
                    "net_annual_profit_usd": net_annual_profit,
                    "viability": viab,
                    "risk_note": note,
                })

    # Sort by net_annual_profit_usd descending
    opportunities.sort(key=lambda o: o["net_annual_profit_usd"], reverse=True)

    # best_opportunity: first viable one
    best: Optional[Dict] = None
    for opp in opportunities:
        if opp["viability"] != "UNVIABLE":
            best = opp
            break

    viable_count = sum(1 for o in opportunities if o["viability"] != "UNVIABLE")

    return {
        "opportunities": opportunities,
        "best_opportunity": best,
        "total_opportunities": len(opportunities),
        "viable_count": viable_count,
        "assets_analyzed": sorted(assets_seen),
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _default_data_dir() -> Path:
    here = Path(__file__).resolve()
    # spa_core/analytics/ -> go up 2 to project root
    return here.parents[2] / "data"


def _load_log(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _save_log(path: Path, log: List[Dict]) -> None:
    """Atomic write with ring-buffer cap."""
    if len(log) > _RING_BUFFER_MAX:
        log = log[-_RING_BUFFER_MAX:]
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


def run(markets: List[Dict], config: Optional[Dict] = None,
        data_dir: Optional[str] = None) -> Dict:
    """analyze() + append result to ring-buffer log file."""
    result = analyze(markets, config)
    dd = Path(data_dir) if data_dir else _default_data_dir()
    dd.mkdir(parents=True, exist_ok=True)
    log_path = dd / _DEFAULT_DATA_FILE
    log = _load_log(log_path)
    log.append(result)
    _save_log(log_path, log)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _demo_markets() -> List[Dict]:
    """Return a small demo market set for --check / --run CLI."""
    return [
        {"protocol": "Aave V3", "asset": "USDC", "side": "LEND",
         "apy": 4.5, "available_liquidity_usd": 1_000_000,
         "min_position_usd": 1_000, "gas_cost_usd": 15.0},
        {"protocol": "Compound V3", "asset": "USDC", "side": "LEND",
         "apy": 5.2, "available_liquidity_usd": 800_000,
         "min_position_usd": 500, "gas_cost_usd": 12.0},
        {"protocol": "Morpho Steakhouse", "asset": "USDC", "side": "LEND",
         "apy": 6.1, "available_liquidity_usd": 500_000,
         "min_position_usd": 2_000, "gas_cost_usd": 20.0},
        {"protocol": "Aave V3", "asset": "USDC", "side": "BORROW",
         "apy": 3.5, "available_liquidity_usd": 600_000,
         "min_position_usd": 1_000, "gas_cost_usd": 15.0},
        {"protocol": "Compound V3", "asset": "USDC", "side": "BORROW",
         "apy": 4.0, "available_liquidity_usd": 400_000,
         "min_position_usd": 500, "gas_cost_usd": 12.0},
        {"protocol": "Aave V3", "asset": "ETH", "side": "LEND",
         "apy": 2.0, "available_liquidity_usd": 2_000_000,
         "min_position_usd": 5_000, "gas_cost_usd": 25.0},
        {"protocol": "Compound V3", "asset": "ETH", "side": "BORROW",
         "apy": 1.2, "available_liquidity_usd": 1_500_000,
         "min_position_usd": 5_000, "gas_cost_usd": 22.0},
    ]


def _cli_main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="MP-841 YieldSpreadArbitrageDetector"
    )
    parser.add_argument("--check", action="store_true",
                        help="Compute and print (no write)")
    parser.add_argument("--run", action="store_true",
                        help="Compute, print, and persist to data/")
    parser.add_argument("--data-dir", default=None,
                        help="Override data directory")
    args = parser.parse_args()

    markets = _demo_markets()
    if args.run:
        result = run(markets, data_dir=args.data_dir)
        print("[MP-841] Result written to data/yield_spread_arb_log.json")
    else:
        result = analyze(markets)
        print("[MP-841] --check mode (no write)")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _cli_main()
