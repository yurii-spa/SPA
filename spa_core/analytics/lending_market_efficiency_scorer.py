"""
MP-818: LendingMarketEfficiencyScorer
Scores lending market efficiency: how well a market matches borrowers to lenders
with minimal spread and high utilization. Pure stdlib, advisory/read-only, atomic writes.

CLI:
    python3 -m spa_core.analytics.lending_market_efficiency_scorer --check
    python3 -m spa_core.analytics.lending_market_efficiency_scorer --run
    python3 -m spa_core.analytics.lending_market_efficiency_scorer --run --data-dir <dir>
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/lending_efficiency_log.json")
MAX_ENTRIES = 100

DEFAULT_OPTIMAL_UTILIZATION = 0.80

# Score component weights (must sum ≤ 100)
SPREAD_WEIGHT = 40.0          # 0% spread → 40 pts; 20%+ → 0
UTILIZATION_WEIGHT = 40.0     # at optimal → 40 pts; ±50% off → 0
SIZE_WEIGHT = 20.0            # $1B supply → 20 pts
BORROW_RATE_FLOOR = 0.01      # Guard for borrow_rate=0

# Grade thresholds (score ≥ X)
GRADE_A = 80
GRADE_B = 65
GRADE_C = 50
GRADE_D = 35
# below GRADE_D → F


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grade(score: int) -> str:
    if score >= GRADE_A:
        return "A"
    if score >= GRADE_B:
        return "B"
    if score >= GRADE_C:
        return "C"
    if score >= GRADE_D:
        return "D"
    return "F"


def _size_score(total_supply_usd: float) -> float:
    """log10-based size score, capped at SIZE_WEIGHT (20).  $1B → 20 pts."""
    if total_supply_usd <= 0:
        return 0.0
    log_max = math.log10(1e9 + 1)
    log_supply = math.log10(total_supply_usd + 1)
    return min(log_supply / log_max * SIZE_WEIGHT, SIZE_WEIGHT)


def _score_market(market: Dict, optimal_utilization: float) -> Dict:
    """Compute per-market efficiency metrics and score."""
    protocol = str(market.get("protocol", ""))
    asset = str(market.get("asset", ""))
    supply_rate = float(market.get("supply_rate", 0.0))
    borrow_rate = float(market.get("borrow_rate", 0.0))
    utilization_rate = float(market.get("utilization_rate", 0.0))
    total_supply_usd = float(market.get("total_supply_usd", 0.0))
    total_borrow_usd = float(market.get("total_borrow_usd", 0.0))

    # Derived metrics
    spread_pct = borrow_rate - supply_rate
    utilization_gap = abs(utilization_rate - optimal_utilization)
    effective_borrow = max(borrow_rate, BORROW_RATE_FLOOR)
    capital_efficiency = utilization_rate * (supply_rate / effective_borrow)

    # Score components
    spread_score = SPREAD_WEIGHT * max(0.0, 1.0 - spread_pct / 20.0)
    utilization_score = UTILIZATION_WEIGHT * max(0.0, 1.0 - utilization_gap / 0.5)
    size_sc = _size_score(total_supply_usd)

    raw_score = spread_score + utilization_score + size_sc
    efficiency_score = int(max(0, min(100, raw_score)))

    return {
        "protocol": protocol,
        "asset": asset,
        "supply_rate": supply_rate,
        "borrow_rate": borrow_rate,
        "spread_pct": spread_pct,
        "utilization_rate": utilization_rate,
        "utilization_gap": utilization_gap,
        "capital_efficiency": capital_efficiency,
        "efficiency_score": efficiency_score,
        "grade": _grade(efficiency_score),
    }


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(
    markets: List[Dict],
    config: Optional[Dict] = None,
) -> Dict:
    """
    Score lending market efficiency across a list of markets.

    Parameters
    ----------
    markets : list[dict]
        Each element: {protocol, asset, supply_rate, borrow_rate,
                       utilization_rate, total_supply_usd, total_borrow_usd}
    config : dict, optional
        {optimal_utilization: float}  default 0.80

    Returns
    -------
    dict  — see module docstring for full schema.
    """
    cfg = config or {}
    optimal_utilization = float(cfg.get("optimal_utilization", DEFAULT_OPTIMAL_UTILIZATION))

    scored: List[Dict] = []
    for m in markets:
        scored.append(_score_market(m, optimal_utilization))

    # ---- rankings ---------------------------------------------------------
    rankings: Dict[str, str] = {
        "tightest_spread": "",
        "highest_utilization": "",
        "most_efficient": "",
    }
    if scored:
        key_for = lambda m: f"{m['protocol']}:{m['asset']}"

        tightest = min(scored, key=lambda m: m["spread_pct"])
        rankings["tightest_spread"] = key_for(tightest)

        highest_util = max(scored, key=lambda m: m["utilization_rate"])
        rankings["highest_utilization"] = key_for(highest_util)

        most_eff = max(scored, key=lambda m: m["efficiency_score"])
        rankings["most_efficient"] = key_for(most_eff)

    # ---- market_summary ---------------------------------------------------
    if scored:
        n = len(scored)
        avg_spread = sum(m["spread_pct"] for m in scored) / n
        avg_util = sum(m["utilization_rate"] for m in scored) / n
        avg_eff = sum(m["efficiency_score"] for m in scored) / n
        total_supply = sum(float(m.get("total_supply_usd", 0.0)) for m in markets)
        total_borrow = sum(float(m.get("total_borrow_usd", 0.0)) for m in markets)
    else:
        avg_spread = 0.0
        avg_util = 0.0
        avg_eff = 0.0
        total_supply = 0.0
        total_borrow = 0.0

    market_summary = {
        "avg_spread_pct": avg_spread,
        "avg_utilization_rate": avg_util,
        "avg_efficiency_score": avg_eff,
        "total_supply_usd": total_supply,
        "total_borrow_usd": total_borrow,
    }

    return {
        "markets": scored,
        "rankings": rankings,
        "market_summary": market_summary,
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

_DEMO_MARKETS = [
    {
        "protocol": "Aave V3",
        "asset": "USDC",
        "supply_rate": 3.5,
        "borrow_rate": 5.2,
        "utilization_rate": 0.82,
        "total_supply_usd": 500_000_000,
        "total_borrow_usd": 410_000_000,
    },
    {
        "protocol": "Compound V3",
        "asset": "USDC",
        "supply_rate": 4.0,
        "borrow_rate": 6.5,
        "utilization_rate": 0.75,
        "total_supply_usd": 200_000_000,
        "total_borrow_usd": 150_000_000,
    },
    {
        "protocol": "Morpho Blue",
        "asset": "WETH",
        "supply_rate": 2.8,
        "borrow_rate": 3.9,
        "utilization_rate": 0.91,
        "total_supply_usd": 800_000_000,
        "total_borrow_usd": 728_000_000,
    },
]


def _print_result(result: Dict) -> None:
    print("\n=== LendingMarketEfficiencyScorer ===")
    for m in result["markets"]:
        print(
            f"  {m['protocol']:15s} {m['asset']:6s}  "
            f"supply={m['supply_rate']:.2f}%  borrow={m['borrow_rate']:.2f}%  "
            f"spread={m['spread_pct']:.2f}%  util={m['utilization_rate']:.2%}  "
            f"score={m['efficiency_score']:3d}  grade={m['grade']}"
        )
    s = result["market_summary"]
    print(
        f"\nSummary: avg_spread={s['avg_spread_pct']:.2f}%  "
        f"avg_util={s['avg_utilization_rate']:.2%}  "
        f"avg_score={s['avg_efficiency_score']:.1f}  "
        f"total_supply=${s['total_supply_usd']:,.0f}"
    )
    r = result["rankings"]
    print(f"Tightest spread : {r['tightest_spread']}")
    print(f"Highest util    : {r['highest_utilization']}")
    print(f"Most efficient  : {r['most_efficient']}")


def main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    run = "--run" in args
    data_dir_idx = args.index("--data-dir") + 1 if "--data-dir" in args else None
    data_file = DATA_FILE
    if data_dir_idx is not None and data_dir_idx < len(args):
        data_file = Path(args[data_dir_idx]) / "lending_efficiency_log.json"

    result = analyze(_DEMO_MARKETS)
    _print_result(result)

    if run:
        log_result(result, data_file)
        print(f"\n✓ Result appended to {data_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
