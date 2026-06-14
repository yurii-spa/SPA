"""
MP-730: FundingRateArbitrageAnalyzer
Advisory/read-only module. Pure stdlib. No external deps.

Analyzes funding rate differentials between perpetual futures markets and
compares against spot yield rates to identify funding rate arbitrage opportunities.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from typing import List, Optional

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_DATA_DIR = os.path.join(_REPO_ROOT, "data")
_LOG_FILE = os.path.join(_DATA_DIR, "funding_rate_arb_log.json")

_RING_BUFFER_CAP = 100

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FundingRateSnapshot:
    symbol: str                 # e.g. "ETH", "BTC", "SOL"
    exchange: str               # e.g. "dYdX", "GMX", "Gains"
    funding_rate_8h: float      # raw 8h rate (decimal, e.g. 0.001 = 0.1%)
    spot_apy: float             # current spot/lending yield (%, e.g. 3.5)
    timestamp_iso: str


@dataclass
class FundingArbOpportunity:
    symbol: str
    long_venue: str             # where to hold spot (e.g. "Aave ETH")
    short_venue: str            # where to short perp (e.g. "dYdX")

    spot_apy: float
    funding_rate_annual: float  # annualised funding rate (%)

    # Combined yield
    gross_yield: float          # spot_apy + funding_rate_annual
    estimated_cost_pct: float   # execution cost estimate (default 0.5% per side)
    net_yield: float            # gross_yield - 2 * estimated_cost_pct

    # Risk
    liquidation_risk: str       # "LOW" | "MEDIUM" | "HIGH"
    basis_risk: str             # "LOW" | "MEDIUM" | "HIGH"

    # Verdict
    is_attractive: bool         # net_yield > 5.0 %
    confidence: str             # "HIGH" | "MEDIUM" | "LOW"
    recommendation: str


@dataclass
class FundingRateAnalysisResult:
    snapshots: List[FundingRateSnapshot]
    opportunities: List[FundingArbOpportunity]  # sorted by net_yield desc

    # Summary
    best_opportunity: Optional[FundingArbOpportunity]
    avg_funding_rate: float
    max_funding_rate: float
    min_funding_rate: float

    # Market regime
    funding_regime: str   # "EXTREME_BULL" | "BULL" | "NEUTRAL" | "BEAR" | "EXTREME_BEAR"

    total_opportunities: int
    attractive_opportunities: int
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core logic functions
# ---------------------------------------------------------------------------

# Top-10 alts by typical market cap (for basis_risk assessment)
_TOP10_ALTS = {"BNB", "SOL", "XRP", "ADA", "AVAX", "DOT", "MATIC", "LINK", "UNI", "LTC"}
_LOW_BASIS_RISK = {"BTC", "ETH"}


def annualize_funding(rate_8h: float) -> float:
    """Convert 8-hour funding rate (decimal) to annual percentage.

    Formula: rate_8h * 3 periods/day * 365 days * 100 → percentage
    Wait — let's check: if rate_8h=0.001 then annual=0.001*3*365=1.095 (109.5%)
    The spec says: rate_8h * 3 * 365 (giving a decimal, then *100 for %)
    But the spec test says: 0.001 → 0.001*3*365 = 1.095 (109.5% annual)
    So the result is already in percentage terms (1.095 means 109.5%).
    Let's keep it as the decimal * 3 * 365 = the fractional annual rate,
    and express as percent: rate_8h * 3 * 365 * 100.

    Actually re-reading: "annualize_funding: 0.001 → 0.001*3*365 = 1.095 (109.5% annual)"
    This means rate_8h=0.001 → result=1.095 (which equals 109.5% when expressed as pct).
    So result = rate_8h * 3 * 365 (fractional, not percentage).
    But then gross_yield = spot_apy + funding_rate_annual
    If spot_apy is in % (e.g. 3.5) and funding_rate_annual is fractional (1.095),
    they don't match. Let's think again...

    The spec says funding_rate_annual is "annualized funding rate (%)" and
    the test says "0.001 → 0.001*3*365 = 1.095 (109.5% annual)".
    So 1.095 represents 109.5% → stored as 109.5 (in percentage points).
    So: annualize_funding(0.001) = 0.001 * 3 * 365 * 100 = 109.5

    But wait: "0.001*3*365 = 1.095" — this is just 109.5% expressed as 1.095
    The spec literally says the result is 1.095 for input 0.001.
    So the function returns the decimal * 3 * 365 = 1.095 (NOT *100).

    Then spot_apy must also be in the same units (decimal, not percent).
    But the dataclass says spot_apy has values like 3.5 (percentage).

    Let me re-read: "annualize_funding(rate_8h) → rate_8h * 3 * 365"
    "annualize_funding: 0.001 → 0.001*3*365 = 1.095 (109.5% annual)"

    So the function returns rate_8h * 3 * 365 = 1.095 for input 0.001.
    The (109.5% annual) is the interpretation: 1.095 = 109.5%.

    But spot_apy in FundingRateSnapshot is described as "current spot/lending yield for same asset"
    and in the example context of DeFi, it would be like 3.5% → stored as 3.5.

    If we add spot_apy=3.5 + funding_rate_annual=1.095, we get 4.595.
    That doesn't make sense for gross_yield to be meaningful.

    Perhaps spot_apy is also stored as decimal (0.035) and funding_rate_annual=1.095 means
    the rate is 1.095 (decimal) = 109.5%.

    Or maybe the convention is:
    - spot_apy is in percentage (3.5 = 3.5%)
    - funding_rate_annual is also in percentage (1.095 = 1.095%? but 0.001*3*365=1.095...
      if 0.001 is 0.1% per 8h, then 0.001*3*365*100 = 109.5%/year, not 1.095%/year)

    Hmm, I think there's ambiguity. Let me just go with the literal spec:
    annualize_funding returns rate_8h * 3 * 365 (no *100).

    And for the FundingRateSnapshot, spot_apy is in the same unit (fractional, not percent).
    The example APY for Morpho Steakhouse is "~6.5%" but as a fraction that's 0.065.

    Actually I think the simplest interpretation that makes the tests work:
    - annualize_funding(0.001) = 1.095 (result is fractional, 1.095 means 109.5%)
    - spot_apy in snapshot: 0.035 means 3.5%
    - funding_rate_annual in opportunity: 1.095 (fractional)
    - gross_yield = spot_apy + funding_rate_annual (both fractional)
    - net_yield = gross_yield - 1.0 → no, "2 * estimated_cost_pct" where estimated_cost_pct=0.5%...
      if 0.5% is 0.005 fractional, then 2*0.005 = 0.01 fractional

    This is getting complicated. Let me take a different approach and look at:
    "net_yield = gross_yield - 2 * estimated_cost_pct"
    "estimated_cost_pct: execution cost estimate (default 0.5% per side)"
    "net_yield = gross_yield - 1.0 (fixed 1% cost)" — from test cases

    So net_yield = gross_yield - 1.0. This means gross_yield is in PERCENTAGE POINTS (%).
    And the cost is 1.0 percentage point (1%).

    If gross_yield is in %, then spot_apy is in % (e.g., 3.5%) and funding_rate_annual is in %.

    But then annualize_funding(0.001) = 1.095 and that's 1.095%?
    No — 0.001 per 8h * 3 * 365 = 1.095 per year = 109.5%/year. That would be 109.5% in percentage terms.

    OK I think I need to choose a consistent interpretation:
    Option A: Everything in % (percentage points)
    - spot_apy = 3.5 (means 3.5%)
    - funding_rate_annual = annualize_funding(0.001) = 109.5 (means 109.5%)
    - gross_yield = 3.5 + 109.5 = 113.0 (%)
    - net_yield = 113.0 - 1.0 = 112.0 (%) [1% total costs]
    - is_attractive: net_yield > 5.0 → True
    - estimated_cost_pct = 0.5 (meaning 0.5% per side, so 0.5*2=1.0%)

    This makes sense! annualize_funding(0.001) should return 109.5 (as percentage).
    But the spec says "0.001 → 0.001*3*365 = 1.095" — that's 1.095, not 109.5.

    WAIT — maybe rate_8h is already stored as a percentage?
    If rate_8h = 0.001 means 0.001% (one thousandth of a percent), then
    annualized = 0.001% * 3 * 365 = 1.095%. That makes more sense for the unit test!

    Actually in crypto, 8h funding rates are typically quoted as percentages like 0.01% or 0.001%.
    If funding_rate_8h = 0.001 means 0.001% per 8 hours:
    annual = 0.001 * 3 * 365 = 1.095 % per year (1.095 percentage points)

    But for "EXTREME_BULL" DeFi scenarios the funding can be much higher, like 0.1% per 8h:
    annual = 0.1 * 3 * 365 = 109.5 %/year — which is aggressive but not unheard of in bull markets.

    OK let me just go with: rate_8h is stored as percentage (e.g., 0.001 means 0.001%),
    and annualize_funding returns it in percentage (0.001 * 3 * 365 = 1.095%).

    Everything in percentage units (%), not decimal fractions.
    spot_apy = 3.5 means 3.5%
    funding_rate_annual = 1.095 means 1.095%
    gross_yield = spot_apy + funding_rate_annual (both in %)
    net_yield = gross_yield - 2 * estimated_cost_pct (estimated_cost_pct = 0.5%)
    net_yield = gross_yield - 1.0 ← matches test "net_yield = gross_yield - 1.0 (fixed 1% cost)"
    is_attractive: net_yield > 5.0 (5.0%)

    assess_liquidation_risk(funding_rate_annual): "HIGH if abs > 100%, MEDIUM if abs > 50%, else LOW"
    This refers to funding_rate_annual in %.
    annualize_funding(0.001) = 1.095 → LOW (< 50%)
    annualize_funding(1.0) = 1095 → HIGH (> 100% annual, since 1% per 8h * 3 * 365 = 1095%)

    Hmm but then the "HIGH if abs > 100%" threshold seems very easy to hit.
    If funding_rate_8h = 0.1 (0.1% per 8h), annual = 0.1*3*365 = 109.5% → MEDIUM (50 < 109.5 < 100? No, > 100).

    Let me re-read: "HIGH if abs > 100%, MEDIUM if abs > 50%, else LOW"
    With rate stored as percentage points:
    - Rate of 0.01% per 8h → 10.95% annual → LOW
    - Rate of 0.05% per 8h → 54.75% annual → MEDIUM
    - Rate of 0.1% per 8h → 109.5% annual → HIGH

    This actually makes sense for extreme bull markets! OK, I'll go with this interpretation.

    Now for funding_regime: "EXTREME_BULL" (>50%) | "BULL" (>20%) | "NEUTRAL" (0-20%) | "BEAR" (<0%) | "EXTREME_BEAR" (<-20%)
    This is based on avg_funding_rate, which is in the same percentage units.
    avg_funding_rate > 50% → EXTREME_BULL → very aggressive
    avg_funding_rate > 20% → BULL
    avg_funding_rate 0-20% → NEUTRAL
    avg_funding_rate < 0% → BEAR
    avg_funding_rate < -20% → EXTREME_BEAR

    OK let me just implement it this way and make sure the tests match.
    """
    return rate_8h * 3 * 365


def assess_liquidation_risk(funding_rate_annual: float) -> str:
    """Assess liquidation risk based on absolute annualised funding rate (%).

    HIGH if abs > 100%, MEDIUM if abs > 50%, else LOW.
    """
    abs_rate = abs(funding_rate_annual)
    if abs_rate > 100.0:
        return "HIGH"
    elif abs_rate > 50.0:
        return "MEDIUM"
    return "LOW"


def assess_basis_risk(symbol: str) -> str:
    """Assess basis risk (spot vs perp divergence) by asset.

    LOW for BTC/ETH, MEDIUM for top-10 alts, HIGH for others.
    """
    upper = symbol.upper()
    if upper in _LOW_BASIS_RISK:
        return "LOW"
    elif upper in _TOP10_ALTS:
        return "MEDIUM"
    return "HIGH"


def _build_long_venue(symbol: str, exchange: str) -> str:
    """Build descriptive long-venue label."""
    return f"Aave {symbol}"


def compute_opportunity(
    snapshot: FundingRateSnapshot,
    estimated_cost_pct: float = 0.5,
) -> FundingArbOpportunity:
    """Compute a FundingArbOpportunity from a single snapshot.

    Only meaningful when funding is positive (long spot + short perp earns both).
    """
    funding_rate_annual = annualize_funding(snapshot.funding_rate_8h)

    gross_yield = snapshot.spot_apy + funding_rate_annual
    net_yield = gross_yield - 2.0 * estimated_cost_pct

    liq_risk = assess_liquidation_risk(funding_rate_annual)
    b_risk = assess_basis_risk(snapshot.symbol)

    is_attractive = net_yield > 5.0

    # Confidence
    if net_yield > 15.0 and liq_risk == "LOW":
        confidence = "HIGH"
    elif net_yield > 8.0:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    long_venue = _build_long_venue(snapshot.symbol, snapshot.exchange)
    short_venue = snapshot.exchange

    if is_attractive:
        recommendation = (
            f"Long {snapshot.symbol} spot @ {long_venue}, short perp @ {short_venue}. "
            f"Net {net_yield:.1f}%/yr. {confidence} confidence."
        )
    else:
        recommendation = f"Insufficient yield after costs ({net_yield:.1f}%/yr)"

    return FundingArbOpportunity(
        symbol=snapshot.symbol,
        long_venue=long_venue,
        short_venue=short_venue,
        spot_apy=snapshot.spot_apy,
        funding_rate_annual=funding_rate_annual,
        gross_yield=gross_yield,
        estimated_cost_pct=estimated_cost_pct,
        net_yield=net_yield,
        liquidation_risk=liq_risk,
        basis_risk=b_risk,
        is_attractive=is_attractive,
        confidence=confidence,
        recommendation=recommendation,
    )


def analyze_market(
    snapshots: List[FundingRateSnapshot],
    total_capital_usd: float = 100_000.0,
) -> FundingRateAnalysisResult:
    """Analyze a list of FundingRateSnapshots and produce a FundingRateAnalysisResult."""
    if not snapshots:
        return FundingRateAnalysisResult(
            snapshots=[],
            opportunities=[],
            best_opportunity=None,
            avg_funding_rate=0.0,
            max_funding_rate=0.0,
            min_funding_rate=0.0,
            funding_regime="NEUTRAL",
            total_opportunities=0,
            attractive_opportunities=0,
            saved_to="",
        )

    # Compute annualised rates for all snapshots
    annual_rates = [annualize_funding(s.funding_rate_8h) for s in snapshots]

    avg_funding = sum(annual_rates) / len(annual_rates)
    max_funding = max(annual_rates)
    min_funding = min(annual_rates)

    # Opportunities only for positive-funding snapshots
    opportunities: List[FundingArbOpportunity] = []
    for snapshot in snapshots:
        if snapshot.funding_rate_8h > 0:
            opp = compute_opportunity(snapshot)
            opportunities.append(opp)

    # Sort descending by net_yield
    opportunities.sort(key=lambda o: o.net_yield, reverse=True)

    best_opportunity = opportunities[0] if opportunities else None
    attractive_count = sum(1 for o in opportunities if o.is_attractive)

    # Funding regime based on avg
    if avg_funding > 50.0:
        regime = "EXTREME_BULL"
    elif avg_funding > 20.0:
        regime = "BULL"
    elif avg_funding < -20.0:
        regime = "EXTREME_BEAR"
    elif avg_funding < 0.0:
        regime = "BEAR"
    else:
        regime = "NEUTRAL"

    return FundingRateAnalysisResult(
        snapshots=snapshots,
        opportunities=opportunities,
        best_opportunity=best_opportunity,
        avg_funding_rate=avg_funding,
        max_funding_rate=max_funding,
        min_funding_rate=min_funding,
        funding_regime=regime,
        total_opportunities=len(opportunities),
        attractive_opportunities=attractive_count,
        saved_to="",
    )


def top_n(result: FundingRateAnalysisResult, n: int) -> List[FundingArbOpportunity]:
    """Return top n opportunities sorted by net_yield descending."""
    return result.opportunities[:n]


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _result_to_dict(result: FundingRateAnalysisResult) -> dict:
    """Serialise result to a JSON-safe dict."""
    def snap_to_dict(s: FundingRateSnapshot) -> dict:
        return {
            "symbol": s.symbol,
            "exchange": s.exchange,
            "funding_rate_8h": s.funding_rate_8h,
            "spot_apy": s.spot_apy,
            "timestamp_iso": s.timestamp_iso,
        }

    def opp_to_dict(o: FundingArbOpportunity) -> dict:
        return {
            "symbol": o.symbol,
            "long_venue": o.long_venue,
            "short_venue": o.short_venue,
            "spot_apy": o.spot_apy,
            "funding_rate_annual": o.funding_rate_annual,
            "gross_yield": o.gross_yield,
            "estimated_cost_pct": o.estimated_cost_pct,
            "net_yield": o.net_yield,
            "liquidation_risk": o.liquidation_risk,
            "basis_risk": o.basis_risk,
            "is_attractive": o.is_attractive,
            "confidence": o.confidence,
            "recommendation": o.recommendation,
        }

    return {
        "snapshots": [snap_to_dict(s) for s in result.snapshots],
        "opportunities": [opp_to_dict(o) for o in result.opportunities],
        "best_opportunity": opp_to_dict(result.best_opportunity) if result.best_opportunity else None,
        "avg_funding_rate": result.avg_funding_rate,
        "max_funding_rate": result.max_funding_rate,
        "min_funding_rate": result.min_funding_rate,
        "funding_regime": result.funding_regime,
        "total_opportunities": result.total_opportunities,
        "attractive_opportunities": result.attractive_opportunities,
        "saved_to": result.saved_to,
    }


def save_results(result: FundingRateAnalysisResult, data_dir: str = _DATA_DIR) -> str:
    """Append result to ring-buffer log (cap 100). Returns saved path. Atomic write."""
    os.makedirs(data_dir, exist_ok=True)
    log_file = os.path.join(data_dir, "funding_rate_arb_log.json")

    # Load existing
    if os.path.exists(log_file):
        try:
            with open(log_file) as f:
                history: list = json.load(f)
        except (json.JSONDecodeError, OSError):
            history = []
    else:
        history = []

    # Append new entry
    entry = _result_to_dict(result)
    entry["_saved_at"] = _now_iso()
    history.append(entry)

    # Ring-buffer cap
    if len(history) > _RING_BUFFER_CAP:
        history = history[-_RING_BUFFER_CAP:]

    # Atomic write
    tmp_file = log_file + ".tmp"
    with open(tmp_file, "w") as f:
        json.dump(history, f, indent=2)
    os.replace(tmp_file, log_file)

    return log_file


def load_history(data_dir: str = _DATA_DIR) -> list:
    """Load all saved results from log."""
    log_file = os.path.join(data_dir, "funding_rate_arb_log.json")
    if not os.path.exists(log_file):
        return []
    try:
        with open(log_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _now_iso() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_sample_snapshots() -> List[FundingRateSnapshot]:
    """Build sample snapshots for demo/testing."""
    ts = _now_iso()
    return [
        FundingRateSnapshot("ETH", "dYdX", 0.01, 3.5, ts),
        FundingRateSnapshot("BTC", "dYdX", 0.008, 2.8, ts),
        FundingRateSnapshot("SOL", "GMX", 0.05, 4.2, ts),
        FundingRateSnapshot("ETH", "Gains", -0.002, 3.5, ts),
    ]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-730 FundingRateArbitrageAnalyzer")
    parser.add_argument("--run", action="store_true", help="Compute and save results")
    parser.add_argument("--check", action="store_true", default=True, help="Compute and print (default)")
    parser.add_argument("--data-dir", default=_DATA_DIR)
    args = parser.parse_args()

    snapshots = _build_sample_snapshots()
    result = analyze_market(snapshots)

    print(f"Funding Regime: {result.funding_regime}")
    print(f"Avg funding rate (annual): {result.avg_funding_rate:.2f}%")
    print(f"Total opps: {result.total_opportunities}, Attractive: {result.attractive_opportunities}")
    if result.best_opportunity:
        print(f"Best: {result.best_opportunity.recommendation}")

    if args.run:
        path = save_results(result, data_dir=args.data_dir)
        print(f"Saved to: {path}")
