"""
MP-893 DeFiLendingRateSpreadAnalyzer
Advisory/read-only. Pure stdlib. Atomic writes.

Analyzes lending rate spreads between borrow and supply rates across DeFi
protocols to find optimal lending/borrowing opportunities.
"""

import json
import os
import time
import tempfile
from typing import Optional

# ─── constants ────────────────────────────────────────────────────────────────

_DEFAULT_CONFIG = {
    "min_supply_apy_pct": 2.0,
    "max_borrow_apy_pct": 15.0,
}

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "lending_rate_spread_log.json"
)
_LOG_CAP = 100


# ─── helpers ──────────────────────────────────────────────────────────────────

def _utilization_label(util: float) -> str:
    if util < 20:
        return "IDLE"
    if util < 50:
        return "LOW"
    if util < 80:
        return "OPTIMAL"
    if util < 90:
        return "HIGH"
    return "CRITICAL"


def _util_score(label: str) -> int:
    return {
        "OPTIMAL": 100,
        "HIGH": 70,
        "LOW": 60,
        "CRITICAL": 30,
        "IDLE": 20,
    }.get(label, 20)


def _lender_rate_quality(supply: float) -> str:
    if supply >= 5.0:
        return "EXCELLENT"
    if supply >= 3.0:
        return "GOOD"
    if supply >= 2.0:
        return "FAIR"
    return "POOR"


def _borrower_cost_label(borrow: float) -> str:
    if borrow < 5.0:
        return "CHEAP"
    if borrow < 10.0:
        return "MODERATE"
    if borrow < 15.0:
        return "EXPENSIVE"
    return "VERY_EXPENSIVE"


def _market_score(supply_apy: float, spread_efficiency: float, util_label: str) -> int:
    supply_norm = min(100, int(supply_apy * 10))
    efficiency_norm = min(100, int(spread_efficiency))
    u_score = _util_score(util_label)
    raw = supply_norm * 0.4 + efficiency_norm * 0.3 + u_score * 0.3
    return min(100, int(raw))


def _flags(
    supply_apy: float,
    borrow_apy: float,
    util: float,
    reserve_factor: float,
    cfg: dict,
) -> list:
    f = []
    if supply_apy < cfg["min_supply_apy_pct"]:
        f.append("LOW_SUPPLY_APY")
    if borrow_apy > cfg["max_borrow_apy_pct"]:
        f.append("HIGH_BORROW_APY")
    if util > 85:
        f.append("NEAR_MAX_UTILIZATION")
    if reserve_factor > 20:
        f.append("HIGH_RESERVE_CAPTURE")
    return f


# ─── log ──────────────────────────────────────────────────────────────────────

def _append_log(entry: dict, log_path: str = _LOG_PATH) -> None:
    """Append one entry to ring-buffer JSON log (cap=100). Atomic write."""
    try:
        abs_path = os.path.abspath(log_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        try:
            with open(abs_path) as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except (FileNotFoundError, json.JSONDecodeError):
            existing = []
        existing.append(entry)
        existing = existing[-_LOG_CAP:]
        dir_ = os.path.dirname(abs_path)
        with tempfile.NamedTemporaryFile(
            "w", dir=dir_, suffix=".tmp", delete=False
        ) as tf:
            json.dump(existing, tf, indent=2)
            tmp_name = tf.name
        os.replace(tmp_name, abs_path)
    except Exception:
        pass  # advisory — never raise


# ─── core ─────────────────────────────────────────────────────────────────────

def analyze(markets: list, config: dict = None) -> dict:
    """
    Analyze lending rate spreads across DeFi protocol markets.

    Parameters
    ----------
    markets : list[dict]
        Each dict has: protocol, asset, supply_apy_pct, borrow_apy_pct,
        utilization_rate_pct, total_supplied_usd, total_borrowed_usd,
        reserve_factor_pct.
    config : dict, optional
        min_supply_apy_pct (default 2.0), max_borrow_apy_pct (default 15.0).

    Returns
    -------
    dict with enriched markets list and aggregate statistics.
    """
    cfg = dict(_DEFAULT_CONFIG)
    if config:
        cfg.update({k: v for k, v in config.items() if k in _DEFAULT_CONFIG})

    ts = time.time()

    if not markets:
        result = {
            "markets": [],
            "by_asset": {},
            "best_supply_market": None,
            "cheapest_borrow_market": None,
            "average_spread_pct": 0.0,
            "timestamp": ts,
        }
        _append_log(result)
        return result

    enriched = []
    for m in markets:
        protocol = str(m.get("protocol", ""))
        asset = str(m.get("asset", ""))
        supply = float(m.get("supply_apy_pct", 0.0))
        borrow = float(m.get("borrow_apy_pct", 0.0))
        util = float(m.get("utilization_rate_pct", 0.0))
        reserve = float(m.get("reserve_factor_pct", 0.0))

        spread = borrow - supply
        efficiency = (supply / borrow * 100.0) if borrow > 0 else 100.0
        u_label = _utilization_label(util)
        score = _market_score(supply, efficiency, u_label)
        flist = _flags(supply, borrow, util, reserve, cfg)

        enriched.append({
            "protocol": protocol,
            "asset": asset,
            "supply_apy_pct": supply,
            "borrow_apy_pct": borrow,
            "spread_pct": spread,
            "spread_efficiency": efficiency,
            "utilization_rate_pct": util,
            "utilization_label": u_label,
            "reserve_capture_pct": reserve,
            "lender_rate_quality": _lender_rate_quality(supply),
            "borrower_cost_label": _borrower_cost_label(borrow),
            "market_score": score,
            "flags": flist,
        })

    # by_asset aggregation
    by_asset: dict = {}
    for e in enriched:
        a = e["asset"]
        if a not in by_asset:
            by_asset[a] = {
                "best_supply_apy": e["supply_apy_pct"],
                "lowest_borrow_apy": e["borrow_apy_pct"] if e["borrow_apy_pct"] > 0 else None,
                "market_count": 1,
            }
        else:
            rec = by_asset[a]
            rec["best_supply_apy"] = max(rec["best_supply_apy"], e["supply_apy_pct"])
            if e["borrow_apy_pct"] > 0:
                if rec["lowest_borrow_apy"] is None:
                    rec["lowest_borrow_apy"] = e["borrow_apy_pct"]
                else:
                    rec["lowest_borrow_apy"] = min(rec["lowest_borrow_apy"], e["borrow_apy_pct"])
            rec["market_count"] += 1

    # resolve None → 0.0 for lowest_borrow_apy
    for a in by_asset:
        if by_asset[a]["lowest_borrow_apy"] is None:
            by_asset[a]["lowest_borrow_apy"] = 0.0

    # best_supply_market
    best_supply = max(enriched, key=lambda x: x["supply_apy_pct"])
    best_supply_market = f"{best_supply['protocol']}:{best_supply['asset']}"

    # cheapest_borrow_market (borrow > 0)
    borrow_candidates = [e for e in enriched if e["borrow_apy_pct"] > 0]
    if borrow_candidates:
        cheapest = min(borrow_candidates, key=lambda x: x["borrow_apy_pct"])
        cheapest_borrow_market: Optional[str] = f"{cheapest['protocol']}:{cheapest['asset']}"
    else:
        cheapest_borrow_market = None

    # average spread
    avg_spread = sum(e["spread_pct"] for e in enriched) / len(enriched)

    result = {
        "markets": enriched,
        "by_asset": by_asset,
        "best_supply_market": best_supply_market,
        "cheapest_borrow_market": cheapest_borrow_market,
        "average_spread_pct": avg_spread,
        "timestamp": ts,
    }
    _append_log(result)
    return result


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="MP-893 DeFiLendingRateSpreadAnalyzer")
    parser.add_argument("--run", action="store_true", help="Compute and write log entry")
    parser.add_argument("--check", action="store_true", help="Compute only, no write (default)")
    args = parser.parse_args()

    _sample_markets = [
        {
            "protocol": "Aave V3",
            "asset": "USDC",
            "supply_apy_pct": 3.5,
            "borrow_apy_pct": 5.2,
            "utilization_rate_pct": 67.0,
            "total_supplied_usd": 500_000_000,
            "total_borrowed_usd": 335_000_000,
            "reserve_factor_pct": 10.0,
        },
        {
            "protocol": "Compound V3",
            "asset": "USDC",
            "supply_apy_pct": 4.8,
            "borrow_apy_pct": 6.1,
            "utilization_rate_pct": 79.0,
            "total_supplied_usd": 300_000_000,
            "total_borrowed_usd": 237_000_000,
            "reserve_factor_pct": 5.0,
        },
    ]

    result = analyze(_sample_markets)
    print(json.dumps(result, indent=2))
