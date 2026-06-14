"""
MP-817: ProtocolTVLCompositionAnalyzer
Breaks down a protocol's TVL by asset type and chain to assess collateral
diversity and concentration risk. Pure stdlib, advisory/read-only, atomic writes.

CLI:
    python3 -m spa_core.analytics.protocol_tvl_composition_analyzer --check
    python3 -m spa_core.analytics.protocol_tvl_composition_analyzer --run
    python3 -m spa_core.analytics.protocol_tvl_composition_analyzer --run --data-dir <dir>
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/tvl_composition_log.json")
MAX_ENTRIES = 100
TOP_ASSETS_N = 5

DEFAULT_CONCENTRATION_THRESHOLD_PCT = 40.0

# Risk flag thresholds
STABLECOIN_HIGH_PCT = 80.0
BLUE_CHIP_LOW_PCT = 10.0
STABLECOIN_MIN_FOR_BLUE_CHIP_SKIP = 50.0
CHAIN_CONCENTRATION_PCT = 80.0

# Scoring weights
TYPE_DIVERSITY_PER_TYPE = 10
TYPE_DIVERSITY_CAP = 40
CHAIN_DIVERSITY_PER_CHAIN = 10
CHAIN_DIVERSITY_CAP = 30
CONCENTRATION_BONUS_MAX = 30
CONCENTRATION_PENALTY_PER_ASSET = 10


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(
    protocol: str,
    assets: List[Dict],
    config: Optional[Dict] = None,
) -> Dict:
    """
    Analyse TVL composition of a protocol by asset type and chain.

    Parameters
    ----------
    protocol : str
        Name of the protocol (e.g. "Aave V3").
    assets : list[dict]
        Each element: {name, type, chain, tvl_usd}.
    config : dict, optional
        {concentration_threshold_pct: float}  default 40.0

    Returns
    -------
    dict  — see module docstring for full schema.
    """
    cfg = config or {}
    threshold = float(cfg.get("concentration_threshold_pct", DEFAULT_CONCENTRATION_THRESHOLD_PCT))

    # ---- totals -----------------------------------------------------------
    total_tvl = sum(float(a.get("tvl_usd", 0.0)) for a in assets)

    # ---- by_type ----------------------------------------------------------
    by_type: Dict[str, Dict] = {}
    for a in assets:
        t = str(a.get("type", "unknown"))
        tvl = float(a.get("tvl_usd", 0.0))
        name = str(a.get("name", ""))
        if t not in by_type:
            by_type[t] = {"tvl_usd": 0.0, "pct": 0.0, "assets": []}
        by_type[t]["tvl_usd"] += tvl
        if name and name not in by_type[t]["assets"]:
            by_type[t]["assets"].append(name)

    if total_tvl > 0:
        for t in by_type:
            by_type[t]["pct"] = round(by_type[t]["tvl_usd"] / total_tvl * 100.0, 4)

    # ---- by_chain ---------------------------------------------------------
    by_chain: Dict[str, Dict] = {}
    for a in assets:
        chain = str(a.get("chain", "unknown"))
        tvl = float(a.get("tvl_usd", 0.0))
        name = str(a.get("name", ""))
        if chain not in by_chain:
            by_chain[chain] = {"tvl_usd": 0.0, "pct": 0.0, "asset_count": 0, "_names": set()}
        by_chain[chain]["tvl_usd"] += tvl
        if name:
            by_chain[chain]["_names"].add(name)

    if total_tvl > 0:
        for chain in by_chain:
            by_chain[chain]["pct"] = round(by_chain[chain]["tvl_usd"] / total_tvl * 100.0, 4)

    for chain in by_chain:
        by_chain[chain]["asset_count"] = len(by_chain[chain]["_names"])
        del by_chain[chain]["_names"]

    # ---- top_assets -------------------------------------------------------
    sorted_assets = sorted(
        assets,
        key=lambda a: float(a.get("tvl_usd", 0.0)),
        reverse=True,
    )
    top_assets = []
    for a in sorted_assets[:TOP_ASSETS_N]:
        tvl = float(a.get("tvl_usd", 0.0))
        pct = (tvl / total_tvl * 100.0) if total_tvl > 0 else 0.0
        top_assets.append({
            "name": str(a.get("name", "")),
            "type": str(a.get("type", "")),
            "chain": str(a.get("chain", "")),
            "tvl_usd": tvl,
            "pct": round(pct, 4),
        })

    # ---- dominant type / chain --------------------------------------------
    dominant_type = ""
    if by_type:
        dominant_type = max(by_type, key=lambda t: by_type[t]["tvl_usd"])

    dominant_chain = ""
    if by_chain:
        dominant_chain = max(by_chain, key=lambda c: by_chain[c]["tvl_usd"])

    # ---- risk_flags -------------------------------------------------------
    risk_flags: List[str] = []
    concentrated_count = 0

    # Only emit flags when there is actual TVL data
    if total_tvl > 0:
        # Per-asset concentration
        for a in assets:
            tvl = float(a.get("tvl_usd", 0.0))
            pct = tvl / total_tvl * 100.0
            if pct > threshold:
                risk_flags.append(
                    f"Single asset >{threshold:.0f}% TVL: {a.get('name','')} ({pct:.1f}%)"
                )
                concentrated_count += 1

        # Stablecoin concentration
        stablecoin_tvl = by_type.get("stablecoin", {}).get("tvl_usd", 0.0)
        stablecoin_pct = stablecoin_tvl / total_tvl * 100.0
        if stablecoin_pct > STABLECOIN_HIGH_PCT:
            risk_flags.append("High stablecoin concentration (>80%)")

        # Low blue-chip collateral
        blue_chip_tvl = by_type.get("blue_chip", {}).get("tvl_usd", 0.0)
        blue_chip_pct = blue_chip_tvl / total_tvl * 100.0
        if blue_chip_pct < BLUE_CHIP_LOW_PCT and stablecoin_pct < STABLECOIN_MIN_FOR_BLUE_CHIP_SKIP:
            risk_flags.append("Low blue-chip collateral")

        # Single chain concentration
        for chain, info in by_chain.items():
            if info["pct"] > CHAIN_CONCENTRATION_PCT:
                risk_flags.append(f"Chain concentration >80%: {chain}")

    # ---- composition_score ------------------------------------------------
    # Spec: empty assets → score=0
    if not assets or total_tvl <= 0:
        score = 0
    else:
        num_types = len(by_type)
        num_chains = len(by_chain)
        type_diversity = min(num_types * TYPE_DIVERSITY_PER_TYPE, TYPE_DIVERSITY_CAP)
        chain_diversity = min(num_chains * CHAIN_DIVERSITY_PER_CHAIN, CHAIN_DIVERSITY_CAP)
        concentration_bonus = max(
            0,
            CONCENTRATION_BONUS_MAX - CONCENTRATION_PENALTY_PER_ASSET * concentrated_count,
        )
        score = int(max(0, min(100, type_diversity + chain_diversity + concentration_bonus)))

    return {
        "protocol": protocol,
        "total_tvl_usd": total_tvl,
        "by_type": by_type,
        "by_chain": by_chain,
        "top_assets": top_assets,
        "composition_score": score,
        "risk_flags": risk_flags,
        "dominant_type": dominant_type,
        "dominant_chain": dominant_chain,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Log / persistence
# ---------------------------------------------------------------------------

def log_result(result: Dict, data_file: Path = DATA_FILE) -> None:
    """Append result to ring-buffer JSON log (max 100 entries), atomic write."""
    data_file = Path(data_file)
    data_file.parent.mkdir(parents=True, exist_ok=True)

    existing: List[Dict] = []
    if data_file.exists():
        try:
            with open(data_file, "r") as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    combined = (existing + [result])[-MAX_ENTRIES:]
    tmp = data_file.with_suffix(".tmp")
    with open(tmp, "w") as fh:
        json.dump(combined, fh, indent=2)
    os.replace(tmp, data_file)


def load_log(data_file: Path = DATA_FILE) -> List[Dict]:
    """Load history from ring-buffer log. Returns [] on missing/corrupt."""
    data_file = Path(data_file)
    if not data_file.exists():
        return []
    try:
        with open(data_file, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_DEMO_PROTOCOL = "Aave V3 Ethereum"
_DEMO_ASSETS = [
    {"name": "USDC", "type": "stablecoin", "chain": "ethereum", "tvl_usd": 200_000_000},
    {"name": "ETH",  "type": "blue_chip",  "chain": "ethereum", "tvl_usd": 150_000_000},
    {"name": "wBTC", "type": "blue_chip",  "chain": "ethereum", "tvl_usd": 80_000_000},
    {"name": "DAI",  "type": "stablecoin", "chain": "ethereum", "tvl_usd": 60_000_000},
    {"name": "LINK", "type": "alt",        "chain": "ethereum", "tvl_usd": 10_000_000},
    {"name": "USDC", "type": "stablecoin", "chain": "base",     "tvl_usd": 5_000_000},
]


def _print_result(result: Dict) -> None:
    print(f"\n=== ProtocolTVLCompositionAnalyzer: {result['protocol']} ===")
    print(f"Total TVL       : ${result['total_tvl_usd']:>20,.2f}")
    print(f"Composition Score: {result['composition_score']}/100")
    print(f"Dominant type   : {result['dominant_type']}")
    print(f"Dominant chain  : {result['dominant_chain']}")
    print("\nBy type:")
    for t, info in result["by_type"].items():
        print(f"  {t:20s}  ${info['tvl_usd']:>15,.2f}  ({info['pct']:.2f}%)  [{', '.join(info['assets'])}]")
    print("\nBy chain:")
    for chain, info in result["by_chain"].items():
        print(f"  {chain:15s}  ${info['tvl_usd']:>15,.2f}  ({info['pct']:.2f}%)  assets: {info['asset_count']}")
    print("\nTop assets:")
    for a in result["top_assets"]:
        print(f"  {a['name']:8s} ({a['type']:12s} / {a['chain']:12s})  ${a['tvl_usd']:>12,.2f}  ({a['pct']:.2f}%)")
    if result["risk_flags"]:
        print("\nRisk flags:")
        for flag in result["risk_flags"]:
            print(f"  ⚠  {flag}")
    else:
        print("\nNo risk flags.")


def main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    run = "--run" in args
    data_dir_idx = args.index("--data-dir") + 1 if "--data-dir" in args else None
    data_file = DATA_FILE
    if data_dir_idx is not None and data_dir_idx < len(args):
        data_file = Path(args[data_dir_idx]) / "tvl_composition_log.json"

    result = analyze(_DEMO_PROTOCOL, _DEMO_ASSETS)
    _print_result(result)

    if run:
        log_result(result, data_file)
        print(f"\n✓ Result appended to {data_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
