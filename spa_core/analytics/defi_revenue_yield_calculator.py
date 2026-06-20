"""
MP-742: DeFiRevenueYieldCalculator
Advisory/read-only analytics module.
Calculates "real yield" from DeFi protocols by distinguishing genuine fee
revenue from inflationary token emissions.
Pure stdlib only. Atomic JSON writes via tmp+os.replace.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Dict, Any
from spa_core.utils.atomic import atomic_save


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ProtocolRevenue:
    protocol: str
    daily_fee_revenue_usd: float
    daily_token_emissions_usd: float
    total_value_locked_usd: float

    # Computed annualized figures
    annual_fee_revenue_usd: float = 0.0
    annual_emission_usd: float = 0.0
    revenue_yield_pct: float = 0.0
    emission_yield_pct: float = 0.0
    total_yield_pct: float = 0.0

    # Ratios / scores
    real_yield_ratio: float = 0.0       # revenue_yield / total_yield * 100
    is_real_yield_protocol: bool = False
    sustainability_score: float = 0.0   # 0-100

    revenue_label: str = ""  # REAL_YIELD | HYBRID | EMISSION_ONLY


@dataclass
class RevenueYieldResult:
    protocols: List[ProtocolRevenue] = field(default_factory=list)

    top_real_yield_protocols: List[str] = field(default_factory=list)
    most_inflationary_protocols: List[str] = field(default_factory=list)

    avg_real_yield_ratio: float = 0.0
    real_yield_protocol_count: int = 0

    market_real_yield_label: str = ""  # MATURE | MIXED | INFLATIONARY
    recommendation_summary: str = ""
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------

def compute_revenue_yield(daily_fee_usd: float, tvl_usd: float) -> float:
    """Annualised revenue yield as a percentage of TVL."""
    if tvl_usd <= 0:
        return 0.0
    return (daily_fee_usd * 365) / tvl_usd * 100


def compute_emission_yield(daily_emission_usd: float, tvl_usd: float) -> float:
    """Annualised emission yield as a percentage of TVL."""
    if tvl_usd <= 0:
        return 0.0
    return (daily_emission_usd * 365) / tvl_usd * 100


def real_yield_ratio(revenue_yield: float, total_yield: float) -> float:
    """Fraction of total yield that is 'real' (fee-backed), 0-100."""
    if total_yield <= 0:
        return 100.0
    return revenue_yield / total_yield * 100


def sustainability_score(revenue_yield: float, emission_yield: float) -> float:
    """Sustainability score 0-100: how much yield is fee-backed vs emission."""
    total = revenue_yield + emission_yield
    if total <= 0:
        return 100.0
    return revenue_yield / total * 100


def revenue_label(ratio: float) -> str:
    """Classify a real_yield_ratio into a label."""
    if ratio >= 70.0:
        return "REAL_YIELD"
    if ratio >= 30.0:
        return "HYBRID"
    return "EMISSION_ONLY"


def _market_label(avg_ratio: float) -> str:
    if avg_ratio > 60.0:
        return "MATURE"
    if avg_ratio >= 30.0:
        return "MIXED"
    return "INFLATIONARY"


# ---------------------------------------------------------------------------
# Protocol analysis
# ---------------------------------------------------------------------------

def analyze_protocol(
    protocol: str,
    daily_fee_usd: float,
    daily_emission_usd: float,
    tvl_usd: float,
) -> ProtocolRevenue:
    """Build a fully-populated ProtocolRevenue dataclass."""
    ann_fee = daily_fee_usd * 365
    ann_emission = daily_emission_usd * 365

    rev_yield = compute_revenue_yield(daily_fee_usd, tvl_usd)
    em_yield = compute_emission_yield(daily_emission_usd, tvl_usd)
    tot_yield = rev_yield + em_yield

    ryr = real_yield_ratio(rev_yield, tot_yield)
    sus = sustainability_score(rev_yield, em_yield)
    lbl = revenue_label(ryr)

    return ProtocolRevenue(
        protocol=protocol,
        daily_fee_revenue_usd=daily_fee_usd,
        daily_token_emissions_usd=daily_emission_usd,
        total_value_locked_usd=tvl_usd,
        annual_fee_revenue_usd=ann_fee,
        annual_emission_usd=ann_emission,
        revenue_yield_pct=rev_yield,
        emission_yield_pct=em_yield,
        total_yield_pct=tot_yield,
        real_yield_ratio=ryr,
        is_real_yield_protocol=(ryr >= 50.0),
        sustainability_score=sus,
        revenue_label=lbl,
    )


# ---------------------------------------------------------------------------
# Market analysis
# ---------------------------------------------------------------------------

def analyze_market(protocols_data: List[Dict[str, Any]]) -> RevenueYieldResult:
    """
    Analyse a list of protocol dicts, each with keys:
        protocol, daily_fee_revenue_usd, daily_token_emissions_usd,
        total_value_locked_usd
    Returns a populated RevenueYieldResult.
    """
    protocols: List[ProtocolRevenue] = []
    for d in protocols_data:
        pr = analyze_protocol(
            protocol=d["protocol"],
            daily_fee_usd=d["daily_fee_revenue_usd"],
            daily_emission_usd=d["daily_token_emissions_usd"],
            tvl_usd=d["total_value_locked_usd"],
        )
        protocols.append(pr)

    # Rankings
    by_rev = sorted(protocols, key=lambda p: p.revenue_yield_pct, reverse=True)
    by_em = sorted(protocols, key=lambda p: p.emission_yield_pct, reverse=True)
    top_real = [p.protocol for p in by_rev[:3]]
    most_inf = [p.protocol for p in by_em[:3]]

    # Averages
    n = len(protocols)
    avg_ratio = sum(p.real_yield_ratio for p in protocols) / n if n > 0 else 0.0
    real_count = sum(1 for p in protocols if p.is_real_yield_protocol)

    mkt_label = _market_label(avg_ratio)

    # Recommendation
    if mkt_label == "INFLATIONARY":
        rec = "Market dominated by token emissions — prioritize REAL_YIELD protocols"
    elif real_count < 2:
        rec = "Few real yield protocols available — reduce DeFi exposure"
    else:
        rec = f"Market label: {mkt_label}. {real_count} real yield protocol(s) identified."

    return RevenueYieldResult(
        protocols=protocols,
        top_real_yield_protocols=top_real,
        most_inflationary_protocols=most_inf,
        avg_real_yield_ratio=avg_ratio,
        real_yield_protocol_count=real_count,
        market_real_yield_label=mkt_label,
        recommendation_summary=rec,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_DEFAULT_LOG = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "defi_revenue_yield_log.json"
)
_DEFAULT_LOG = os.path.normpath(_DEFAULT_LOG)
_RING_SIZE = 100


def _to_dict(result: RevenueYieldResult) -> Dict[str, Any]:
    """Serialise result to a JSON-safe dict."""
    d = asdict(result)
    return d


def save_results(result: RevenueYieldResult, path: str = _DEFAULT_LOG) -> str:
    """Append result to ring-buffer JSON log (max 100 entries). Returns path."""
    history = load_history(path)
    entry = _to_dict(result)
    entry["_saved_at"] = datetime.now(timezone.utc).isoformat()
    history.append(entry)
    if len(history) > _RING_SIZE:
        history = history[-_RING_SIZE:]
    _atomic_write(path, history)
    result.saved_to = path
    return path


def load_history(path: str = _DEFAULT_LOG) -> list:
    """Load ring-buffer log, returning [] if missing or corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _atomic_write(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_save(data, str(path))
    import sys

    sample = [
        {
            "protocol": "Aave V3",
            "daily_fee_revenue_usd": 50_000,
            "daily_token_emissions_usd": 10_000,
            "total_value_locked_usd": 5_000_000_000,
        },
        {
            "protocol": "Compound V3",
            "daily_fee_revenue_usd": 20_000,
            "daily_token_emissions_usd": 30_000,
            "total_value_locked_usd": 2_000_000_000,
        },
        {
            "protocol": "New Farm",
            "daily_fee_revenue_usd": 500,
            "daily_token_emissions_usd": 80_000,
            "total_value_locked_usd": 100_000_000,
        },
    ]

    result = analyze_market(sample)

    mode = "--check"
    if len(sys.argv) > 1:
        mode = sys.argv[1]

    print(f"Market label : {result.market_real_yield_label}")
    print(f"Avg real yield ratio: {result.avg_real_yield_ratio:.1f}%")
    print(f"Real yield protocols: {result.real_yield_protocol_count}")
    print(f"Top real yield : {result.top_real_yield_protocols}")
    print(f"Most inflationary: {result.most_inflationary_protocols}")
    print(f"Recommendation: {result.recommendation_summary}")

    if mode == "--run":
        saved = save_results(result)
        print(f"Saved to: {saved}")
