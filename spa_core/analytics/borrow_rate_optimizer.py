"""
MP-746: BorrowRateOptimizer
Analyzes borrow rates across DeFi lending protocols to find optimal
borrowing opportunities. Compares supply APY vs borrow cost, utilization
ratios, and computes effective net APY after borrowing costs for leveraged
yield strategies.
Advisory/read-only. Pure stdlib. Atomic JSON writes.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List

# ── Data directory (repo-relative) ──────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_DATA_DIR = os.path.join(_REPO_ROOT, "data")
_LOG_FILE = os.path.join(_DATA_DIR, "borrow_rate_log.json")

_RING_BUFFER_CAP = 100


# ── Core dataclasses ─────────────────────────────────────────────────────────

@dataclass
class BorrowOpportunity:
    protocol: str
    asset: str

    supply_apy_pct: float          # yield from supplying
    borrow_rate_pct: float         # cost to borrow (variable)
    utilization_rate_pct: float    # how full the pool is (0-100%)

    # Computed
    net_spread_pct: float          # supply_apy - borrow_rate (positive = supply beats borrow)

    # Leverage analysis
    leverage_2x_apy_pct: float     # 2*supply_apy - borrow_rate
    leverage_3x_apy_pct: float     # 3*supply_apy - 2*borrow_rate

    # Risk metrics
    liquidation_buffer_pct: float  # max(0, 80 - utilization_rate)
    utilization_risk: str          # "LOW" | "MODERATE" | "HIGH"

    # Recommendation
    is_attractive: bool            # net_spread > 1.0 and utilization_rate < 80
    attractiveness_score: float    # net_spread * (1 - util/100) * 100, clamped 0-100

    rate_label: str                # "CHEAP" | "MODERATE" | "EXPENSIVE"
    recommendation: str


@dataclass
class BorrowRateResult:
    opportunities: List[BorrowOpportunity]

    # Rankings
    best_spread_protocol: str      # highest net_spread_pct
    lowest_rate_protocol: str      # lowest borrow_rate_pct
    riskiest_protocol: str         # highest utilization_rate_pct

    avg_borrow_rate_pct: float
    avg_net_spread_pct: float

    attractive_count: int          # count where is_attractive=True

    market_rate_label: str         # "CHEAP_CREDIT" | "MODERATE_CREDIT" | "EXPENSIVE_CREDIT"

    recommendation_summary: str
    saved_to: str


# ── Pure calculation functions ────────────────────────────────────────────────

def compute_net_spread(supply_apy: float, borrow_rate: float) -> float:
    """supply_apy - borrow_rate; positive means supply beats borrow cost."""
    return supply_apy - borrow_rate


def compute_leverage_2x(supply_apy: float, borrow_rate: float) -> float:
    """2*supply_apy - borrow_rate (borrow 1x, redeploy at supply_apy)."""
    return 2.0 * supply_apy - borrow_rate


def compute_leverage_3x(supply_apy: float, borrow_rate: float) -> float:
    """3*supply_apy - 2*borrow_rate (borrow 2x, redeploy 3x total)."""
    return 3.0 * supply_apy - 2.0 * borrow_rate


def utilization_risk(util_pct: float) -> str:
    """Classify pool utilization risk."""
    if util_pct < 50.0:
        return "LOW"
    if util_pct <= 80.0:
        return "MODERATE"
    return "HIGH"


def liquidation_buffer(util_pct: float) -> float:
    """Proxy buffer before liquidity crunch: max(0, 80 - util_pct)."""
    return max(0.0, 80.0 - util_pct)


def attractiveness_score(net_spread: float, util_pct: float) -> float:
    """net_spread * (1 - util/100) * 100, clamped to [0, 100]."""
    raw = net_spread * (1.0 - util_pct / 100.0) * 100.0
    return min(100.0, max(0.0, raw))


def rate_label(borrow_rate: float) -> str:
    """Classify borrow rate cost level."""
    if borrow_rate < 3.0:
        return "CHEAP"
    if borrow_rate <= 6.0:
        return "MODERATE"
    return "EXPENSIVE"


def is_attractive(net_spread: float, util_pct: float) -> bool:
    """True when net_spread > 1.0 and utilization < 80%."""
    return net_spread > 1.0 and util_pct < 80.0


def _build_recommendation(net_spread: float, util_pct: float, attractive: bool) -> str:
    if util_pct > 80.0:
        return "High utilization risk. Rates may spike."
    if net_spread < 0.0:
        return "Borrow cost exceeds supply yield. Avoid."
    if attractive:
        return "Attractive spread with healthy liquidity."
    return "Marginal spread. Monitor closely."


def analyze_opportunity(
    protocol: str,
    asset: str,
    supply_apy: float,
    borrow_rate: float,
    utilization: float,
) -> BorrowOpportunity:
    """Analyze a single borrowing opportunity."""
    spread = compute_net_spread(supply_apy, borrow_rate)
    lev2 = compute_leverage_2x(supply_apy, borrow_rate)
    lev3 = compute_leverage_3x(supply_apy, borrow_rate)
    u_risk = utilization_risk(utilization)
    buf = liquidation_buffer(utilization)
    score = attractiveness_score(spread, utilization)
    attractive = is_attractive(spread, utilization)
    label = rate_label(borrow_rate)
    rec = _build_recommendation(spread, utilization, attractive)

    return BorrowOpportunity(
        protocol=protocol,
        asset=asset,
        supply_apy_pct=supply_apy,
        borrow_rate_pct=borrow_rate,
        utilization_rate_pct=utilization,
        net_spread_pct=spread,
        leverage_2x_apy_pct=lev2,
        leverage_3x_apy_pct=lev3,
        liquidation_buffer_pct=buf,
        utilization_risk=u_risk,
        is_attractive=attractive,
        attractiveness_score=score,
        rate_label=label,
        recommendation=rec,
    )


def analyze_market(opportunities_data: List[dict]) -> BorrowRateResult:
    """
    Analyze multiple borrowing opportunities.

    Each dict must have: protocol, asset, supply_apy_pct,
    borrow_rate_pct, utilization_rate_pct.
    """
    if not opportunities_data:
        raise ValueError("opportunities_data must not be empty")

    opps = [
        analyze_opportunity(
            protocol=d["protocol"],
            asset=d["asset"],
            supply_apy=d["supply_apy_pct"],
            borrow_rate=d["borrow_rate_pct"],
            utilization=d["utilization_rate_pct"],
        )
        for d in opportunities_data
    ]

    best_spread_opp = max(opps, key=lambda o: o.net_spread_pct)
    lowest_rate_opp = min(opps, key=lambda o: o.borrow_rate_pct)
    riskiest_opp = max(opps, key=lambda o: o.utilization_rate_pct)

    avg_borrow = sum(o.borrow_rate_pct for o in opps) / len(opps)
    avg_spread = sum(o.net_spread_pct for o in opps) / len(opps)
    attr_count = sum(1 for o in opps if o.is_attractive)

    if avg_borrow < 3.0:
        mkt_label = "CHEAP_CREDIT"
    elif avg_borrow <= 6.0:
        mkt_label = "MODERATE_CREDIT"
    else:
        mkt_label = "EXPENSIVE_CREDIT"

    if attr_count == 0:
        summary = "No attractive opportunities found. Monitor for rate improvements."
    elif attr_count == 1:
        summary = (
            f"1 attractive opportunity: {best_spread_opp.protocol} "
            f"with {best_spread_opp.net_spread_pct:.2f}% net spread."
        )
    else:
        summary = (
            f"{attr_count} attractive opportunities. "
            f"Best spread at {best_spread_opp.protocol} "
            f"({best_spread_opp.net_spread_pct:.2f}%). "
            f"Lowest rate at {lowest_rate_opp.protocol} "
            f"({lowest_rate_opp.borrow_rate_pct:.2f}%)."
        )

    return BorrowRateResult(
        opportunities=opps,
        best_spread_protocol=best_spread_opp.protocol,
        lowest_rate_protocol=lowest_rate_opp.protocol,
        riskiest_protocol=riskiest_opp.protocol,
        avg_borrow_rate_pct=avg_borrow,
        avg_net_spread_pct=avg_spread,
        attractive_count=attr_count,
        market_rate_label=mkt_label,
        recommendation_summary=summary,
        saved_to="",
    )


# ── Persistence ───────────────────────────────────────────────────────────────

def _result_to_dict(result: BorrowRateResult) -> dict:
    d = asdict(result)
    d["timestamp"] = datetime.now(timezone.utc).isoformat()
    return d


def load_history(log_file: str = _LOG_FILE) -> list:
    """Load historical borrow rate analysis log."""
    if not os.path.exists(log_file):
        return []
    with open(log_file, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_results(result: BorrowRateResult, log_file: str = _LOG_FILE) -> str:
    """
    Append result to ring-buffer log (cap=100). Atomic write via tmp+replace.
    Returns the log file path.
    """
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    history = load_history(log_file)
    history.append(_result_to_dict(result))
    if len(history) > _RING_BUFFER_CAP:
        history = history[-_RING_BUFFER_CAP:]

    dir_ = os.path.dirname(log_file)
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(history, fh, indent=2)
        os.replace(tmp_path, log_file)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return log_file


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_run() -> None:  # pragma: no cover
    """Quick smoke-test with hard-coded sample data."""
    sample = [
        {"protocol": "Aave V3",    "asset": "USDC", "supply_apy_pct": 4.5, "borrow_rate_pct": 2.8, "utilization_rate_pct": 60.0},
        {"protocol": "Compound V3","asset": "USDC", "supply_apy_pct": 3.8, "borrow_rate_pct": 3.2, "utilization_rate_pct": 72.0},
        {"protocol": "Morpho Blue","asset": "USDC", "supply_apy_pct": 6.2, "borrow_rate_pct": 7.1, "utilization_rate_pct": 88.0},
    ]
    result = analyze_market(sample)
    print("=== BorrowRateOptimizer Demo ===")
    print(f"Market label  : {result.market_rate_label}")
    print(f"Best spread   : {result.best_spread_protocol}  ({result.avg_net_spread_pct:.2f}% avg)")
    print(f"Attractive    : {result.attractive_count}/{len(result.opportunities)}")
    print(f"Summary       : {result.recommendation_summary}")
    for opp in result.opportunities:
        print(f"  {opp.protocol:15s} spread={opp.net_spread_pct:+.2f}% util={opp.utilization_rate_pct:.0f}%"
              f" risk={opp.utilization_risk:8s} score={opp.attractiveness_score:.1f}")


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv or len(sys.argv) == 1:
        _demo_run()
