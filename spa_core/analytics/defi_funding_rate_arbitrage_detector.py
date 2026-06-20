"""
MP-873: DeFiFundingRateArbitrageDetector
=========================================
Advisory-only analytics module.
Identifies funding rate arbitrage opportunities between perpetual futures
funding rates and spot/lending yields.

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/funding_rate_arb_log.json.
Atomic writes: tmp + os.replace.
"""

import json
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_MIN_ANNUALIZED_SPREAD_PCT = 5.0
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "funding_rate_arb_log.json",
)
LOG_MAX_ENTRIES = 100


# ---------------------------------------------------------------------------
# Core computation helpers
# ---------------------------------------------------------------------------

def _annualize_funding_rate(funding_rate_8h: float) -> float:
    """Convert 8h funding rate % → annualized %.  3 periods/day × 365 days."""
    return funding_rate_8h * 3 * 365


def _annualize_execution_cost(execution_cost_pct: float, holding_days: int) -> float:
    """Spread one-time execution cost over holding period, then annualize."""
    if holding_days <= 0:
        return 0.0
    return execution_cost_pct / holding_days * 365


def _gross_spread(perp_funding_annualized: float, spot_lending_apy: float) -> float:
    return perp_funding_annualized - spot_lending_apy


def _net_spread(gross: float, execution_cost_annualized: float) -> float:
    return gross - execution_cost_annualized


def _estimated_profit(
    capital_usd: float, net_spread_pct: float, holding_days: int
) -> float:
    if capital_usd <= 0 or holding_days <= 0:
        return 0.0
    return capital_usd * net_spread_pct / 100.0 * holding_days / 365.0


def _opportunity_type(
    net_spread: float,
    perp_funding_annualized: float,
    min_threshold: float,
) -> str:
    if net_spread < 0:
        return "NEGATIVE"
    if net_spread < min_threshold:
        return "NEUTRAL"
    # net_spread >= min_threshold
    if perp_funding_annualized < 0:
        return "SPOT_YIELD_DOMINANT"
    return "FUNDING_RATE_ARB"


def _risk_note(
    opp_type: str,
    net_spread: float,
    perp_funding_annualized: float,
    min_threshold: float,
    spot_protocol: str,
    perp_protocol: str,
) -> str:
    if opp_type == "NEGATIVE":
        return "Spread is negative. Not profitable at current rates."
    if opp_type == "NEUTRAL":
        return (
            f"Spread {net_spread:.1f}% below {min_threshold:.1f}% minimum threshold."
        )
    if opp_type == "SPOT_YIELD_DOMINANT":
        return (
            f"Negative funding ({perp_funding_annualized:.1f}% annual) + spot yield "
            f"creates short-bias arb."
        )
    # FUNDING_RATE_ARB
    return (
        f"Delta-neutral: long spot on {spot_protocol} + short perp on {perp_protocol}. "
        f"Net {net_spread:.1f}% annual."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(opportunities: list, config: dict = None) -> dict:
    """
    Identify funding rate arbitrage opportunities.

    Parameters
    ----------
    opportunities : list[dict]
        Each element must contain:
            asset                    : str
            perp_funding_rate_pct_8h : float  (funding rate per 8h period, may be negative)
            spot_lending_apy_pct     : float
            spot_protocol            : str
            perp_protocol            : str
            execution_cost_pct       : float  (one-time gas+fees %)
            capital_usd              : float
            holding_days             : int
    config : dict | None
        min_annualized_spread_pct : float  (default 5.0)

    Returns
    -------
    dict  (see module docstring for full schema)
    """
    cfg = config or {}
    min_spread = float(cfg.get("min_annualized_spread_pct", DEFAULT_MIN_ANNUALIZED_SPREAD_PCT))

    if not opportunities:
        result = {
            "opportunities": [],
            "best_opportunity": None,
            "total_viable_opportunities": 0,
            "average_net_spread_pct": 0.0,
            "timestamp": time.time(),
        }
        _append_log(result)
        return result

    processed = []
    for opp in opportunities:
        asset = opp.get("asset", "")
        funding_8h = float(opp.get("perp_funding_rate_pct_8h", 0.0))
        spot_apy = float(opp.get("spot_lending_apy_pct", 0.0))
        spot_protocol = opp.get("spot_protocol", "")
        perp_protocol = opp.get("perp_protocol", "")
        exec_cost = float(opp.get("execution_cost_pct", 0.0))
        capital = float(opp.get("capital_usd", 0.0))
        holding = int(opp.get("holding_days", 0))

        perp_ann = _annualize_funding_rate(funding_8h)
        exec_ann = _annualize_execution_cost(exec_cost, holding)
        gross = _gross_spread(perp_ann, spot_apy)
        net = _net_spread(gross, exec_ann)
        profit = _estimated_profit(capital, net, holding)
        opp_type = _opportunity_type(net, perp_ann, min_spread)
        is_opp = net >= min_spread
        note = _risk_note(opp_type, net, perp_ann, min_spread, spot_protocol, perp_protocol)

        processed.append(
            {
                "asset": asset,
                "perp_funding_annualized_pct": round(perp_ann, 6),
                "spot_lending_apy_pct": round(spot_apy, 6),
                "gross_spread_pct": round(gross, 6),
                "net_spread_pct": round(net, 6),
                "execution_cost_annualized_pct": round(exec_ann, 6),
                "estimated_profit_usd": round(profit, 6),
                "annualized_return_pct": round(net, 6),
                "is_opportunity": is_opp,
                "opportunity_type": opp_type,
                "risk_note": note,
            }
        )

    # Summary metrics
    viable = [p for p in processed if p["is_opportunity"]]
    total_viable = len(viable)

    # best_opportunity: asset with highest net_spread among viable
    best = None
    if viable:
        best_item = max(viable, key=lambda x: x["net_spread_pct"])
        best = best_item["asset"]

    all_nets = [p["net_spread_pct"] for p in processed]
    avg_net = sum(all_nets) / len(all_nets) if all_nets else 0.0

    result = {
        "opportunities": processed,
        "best_opportunity": best,
        "total_viable_opportunities": total_viable,
        "average_net_spread_pct": round(avg_net, 6),
        "timestamp": time.time(),
    }
    _append_log(result)
    return result


# ---------------------------------------------------------------------------
# Log management
# ---------------------------------------------------------------------------

def _append_log(entry: dict) -> None:
    """Atomically append a result entry to the ring-buffer log (max 100)."""
    log_dir = os.path.dirname(LOG_PATH)
    os.makedirs(log_dir, exist_ok=True)

    existing = []
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, "r") as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    # keep only last LOG_MAX_ENTRIES
    existing = existing[-LOG_MAX_ENTRIES:]

    # atomic write
    atomic_save(existing, str(LOG_PATH))
def init_log() -> None:
    """Initialize the log file as an empty list if it doesn't exist."""
    log_dir = os.path.dirname(LOG_PATH)
    os.makedirs(log_dir, exist_ok=True)
    if not os.path.exists(LOG_PATH):
        atomic_save([], str(LOG_PATH))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    init_log()

    # Demo run with sample data
    sample = [
        {
            "asset": "ETH",
            "perp_funding_rate_pct_8h": 0.05,
            "spot_lending_apy_pct": 3.5,
            "spot_protocol": "Aave V3",
            "perp_protocol": "dYdX",
            "execution_cost_pct": 0.3,
            "capital_usd": 100000,
            "holding_days": 30,
        },
        {
            "asset": "BTC",
            "perp_funding_rate_pct_8h": 0.01,
            "spot_lending_apy_pct": 4.8,
            "spot_protocol": "Compound V3",
            "perp_protocol": "GMX",
            "execution_cost_pct": 0.2,
            "capital_usd": 50000,
            "holding_days": 14,
        },
    ]

    result = analyze(sample)
    print(json.dumps(result, indent=2))
    sys.exit(0)
