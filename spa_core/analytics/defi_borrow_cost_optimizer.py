"""
MP-863 DeFiBorrowCostOptimizer
Advisory/read-only. Pure stdlib. No external dependencies.

Compares borrowing costs across lending protocols and identifies the optimal
borrow source for a given collateral type, considering interest rates,
utilization, and stability of rates.

Data log: data/borrow_cost_log.json (ring-buffer 100, atomic write)
"""

import json
import math
import os
import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "borrow_cost_log.json")
_LOG_CAP = 100

_DEFAULT_MIN_LIQUIDITY = 100_000.0
_DEFAULT_TARGET_BORROW = 10_000.0


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _effective_cost_score(borrow_apy_pct: float) -> int:
    """Higher score = lower APY (better for borrower)."""
    if borrow_apy_pct <= 1:
        return 100
    if borrow_apy_pct <= 3:
        return 85
    if borrow_apy_pct <= 5:
        return 70
    if borrow_apy_pct <= 8:
        return 55
    if borrow_apy_pct <= 12:
        return 35
    if borrow_apy_pct <= 20:
        return 20
    return 5


def _rate_stability_score(rate_30d_std_pct: float) -> int:
    """Higher score = lower volatility (more stable)."""
    if rate_30d_std_pct <= 0.1:
        return 100
    if rate_30d_std_pct <= 0.5:
        return 80
    if rate_30d_std_pct <= 1.0:
        return 60
    if rate_30d_std_pct <= 2.0:
        return 40
    if rate_30d_std_pct <= 5.0:
        return 20
    return 5


def _liquidity_score(available_liquidity_usd: float) -> int:
    """Higher score = more liquidity."""
    if available_liquidity_usd >= 100_000_000:
        return 100
    if available_liquidity_usd >= 10_000_000:
        return 80
    if available_liquidity_usd >= 1_000_000:
        return 60
    if available_liquidity_usd >= 500_000:
        return 40
    if available_liquidity_usd >= 100_000:
        return 20
    return 5


def _utilization_risk_score(utilization_pct: float) -> int:
    """Higher score = lower utilization risk (lower util)."""
    if utilization_pct <= 50:
        return 100
    if utilization_pct <= 70:
        return 80
    if utilization_pct <= 80:
        return 60
    if utilization_pct <= 90:
        return 30
    if utilization_pct <= 95:
        return 10
    return 5


def _composite_score(ecs: int, rss: int, ls: int, urs: int) -> int:
    raw = ecs * 0.4 + rss * 0.3 + ls * 0.2 + urs * 0.1
    return min(100, int(raw))


def _borrow_label(composite: int) -> str:
    if composite >= 80:
        return "OPTIMAL"
    if composite >= 60:
        return "GOOD"
    if composite >= 40:
        return "ACCEPTABLE"
    if composite >= 20:
        return "RISKY"
    return "AVOID"


def _is_near_kink(rate_model: str, utilization_pct: float, kink_utilization_pct: float) -> bool:
    if rate_model != "KINKED":
        return False
    if kink_utilization_pct <= 0:
        return False
    return abs(utilization_pct - kink_utilization_pct) <= 5.0


def _rate_trend(borrow_apy_pct: float, rate_30d_avg_pct: float) -> str:
    if rate_30d_avg_pct == 0:
        return "STABLE"
    if borrow_apy_pct < rate_30d_avg_pct * 0.95:
        return "FALLING"
    if borrow_apy_pct > rate_30d_avg_pct * 1.05:
        return "RISING"
    return "STABLE"


def _recommendation(label: str, protocol: str, borrow_asset: str,
                    borrow_apy_pct: float, rate_30d_std_pct: float,
                    utilization_pct: float) -> str:
    if label == "OPTIMAL":
        return (
            f"Borrow {borrow_asset} on {protocol} at {borrow_apy_pct:.2f}%. "
            f"Best available rate."
        )
    if label == "GOOD":
        return (
            f"Good option on {protocol}. Rate {borrow_apy_pct:.2f}%, "
            f"stable ({rate_30d_std_pct:.2f}% std)."
        )
    if label == "ACCEPTABLE":
        return (
            f"Acceptable on {protocol} but consider rate volatility risk."
        )
    if label == "RISKY":
        return (
            f"High utilization ({utilization_pct:.0f}%) on {protocol}. "
            f"Rate may spike."
        )
    # AVOID
    return f"Avoid {protocol} for borrowing. Poor composite score."


# ---------------------------------------------------------------------------
# Asset summary helper
# ---------------------------------------------------------------------------

def _build_asset_summary(scored_markets: list) -> dict:
    summary: dict[str, dict] = {}
    for m in scored_markets:
        asset = m["borrow_asset"]
        cs = m["composite_score"]
        apy = m["borrow_apy_pct"]
        protocol = m["protocol"]
        if asset not in summary:
            summary[asset] = {
                "count": 0,
                "best_protocol": protocol,
                "best_composite": cs,
                "min_apy": apy,
            }
        summary[asset]["count"] += 1
        if cs > summary[asset]["best_composite"]:
            summary[asset]["best_composite"] = cs
            summary[asset]["best_protocol"] = protocol
        if apy < summary[asset]["min_apy"]:
            summary[asset]["min_apy"] = apy

    # Strip internal tracking field
    result = {}
    for asset, v in summary.items():
        result[asset] = {
            "count": v["count"],
            "best_protocol": v["best_protocol"],
            "min_apy": v["min_apy"],
        }
    return result


# ---------------------------------------------------------------------------
# Log helper
# ---------------------------------------------------------------------------

def _log_result(result: dict) -> None:
    """Append result to ring-buffer log (cap 100), atomic write."""
    log_path = os.path.normpath(_LOG_PATH)
    try:
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                entries = []
        else:
            entries = []
    except Exception:
        entries = []

    entries.append(result)
    if len(entries) > _LOG_CAP:
        entries = entries[-_LOG_CAP:]

    tmp_path = log_path + ".tmp"
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(tmp_path, "w") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp_path, log_path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze(borrow_markets: list, config: dict = None) -> dict:
    """
    Analyze borrow markets and score them by composite cost/risk metric.

    Parameters
    ----------
    borrow_markets : list of dicts with keys:
        protocol, borrow_asset, borrow_apy_pct, utilization_pct, rate_model,
        kink_utilization_pct, rate_30d_avg_pct, rate_30d_std_pct,
        available_liquidity_usd
    config : optional dict with min_liquidity_usd and target_borrow_usd

    Returns
    -------
    dict with borrow_markets, best_borrow_market, asset_summary,
    filtered_out_count, average_composite_score, timestamp
    """
    if config is None:
        config = {}

    min_liquidity = float(config.get("min_liquidity_usd", _DEFAULT_MIN_LIQUIDITY))
    _target_borrow = float(config.get("target_borrow_usd", _DEFAULT_TARGET_BORROW))  # noqa: F841

    filtered_out_count = 0
    scored_markets = []

    for m in borrow_markets:
        protocol = str(m.get("protocol", ""))
        borrow_asset = str(m.get("borrow_asset", ""))
        borrow_apy_pct = float(m.get("borrow_apy_pct", 0.0))
        utilization_pct = float(m.get("utilization_pct", 0.0))
        rate_model = str(m.get("rate_model", "VARIABLE"))
        kink_utilization_pct = float(m.get("kink_utilization_pct", 0.0))
        rate_30d_avg_pct = float(m.get("rate_30d_avg_pct", borrow_apy_pct))
        rate_30d_std_pct = float(m.get("rate_30d_std_pct", 0.0))
        available_liquidity_usd = float(m.get("available_liquidity_usd", 0.0))

        if available_liquidity_usd < min_liquidity:
            filtered_out_count += 1
            continue

        ecs = _effective_cost_score(borrow_apy_pct)
        rss = _rate_stability_score(rate_30d_std_pct)
        ls = _liquidity_score(available_liquidity_usd)
        urs = _utilization_risk_score(utilization_pct)
        comp = _composite_score(ecs, rss, ls, urs)
        label = _borrow_label(comp)
        near_kink = _is_near_kink(rate_model, utilization_pct, kink_utilization_pct)
        trend = _rate_trend(borrow_apy_pct, rate_30d_avg_pct)
        rec = _recommendation(label, protocol, borrow_asset, borrow_apy_pct,
                               rate_30d_std_pct, utilization_pct)

        scored_markets.append({
            "protocol": protocol,
            "borrow_asset": borrow_asset,
            "borrow_apy_pct": borrow_apy_pct,
            "effective_cost_score": ecs,
            "rate_stability_score": rss,
            "liquidity_score": ls,
            "utilization_risk_score": urs,
            "composite_score": comp,
            "borrow_label": label,
            "is_near_kink": near_kink,
            "rate_trend": trend,
            "recommendation": rec,
        })

    # Best market: highest composite_score
    best_borrow_market = None
    if scored_markets:
        best = max(scored_markets, key=lambda x: x["composite_score"])
        best_borrow_market = f"{best['protocol']} ({best['borrow_asset']})"

    asset_summary = _build_asset_summary(scored_markets)

    avg_composite = 0.0
    if scored_markets:
        avg_composite = round(
            sum(m["composite_score"] for m in scored_markets) / len(scored_markets), 2
        )

    result = {
        "borrow_markets": scored_markets,
        "best_borrow_market": best_borrow_market,
        "asset_summary": asset_summary,
        "filtered_out_count": filtered_out_count,
        "average_composite_score": avg_composite,
        "timestamp": time.time(),
    }

    _log_result(result)
    return result
