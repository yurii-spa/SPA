"""
MP-711: ProtocolDominanceAnalyzer
Analyzes which protocols dominate a given DeFi category, tracking market share,
moat strength, and competitive dynamics. Advisory/read-only, pure stdlib, atomic JSON.
"""

from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional
import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/protocol_dominance_log.json")
MAX_ENTRIES = 100

# Tuple type for raw protocol input
ProtocolRaw = Tuple[str, float, float, int, float]
# (protocol, tvl_usd, tvl_30d_growth_pct, user_count, revenue_30d_usd)


@dataclass
class ProtocolMarketShare:
    protocol: str
    category: str           # "lending" | "dex" | "yield_aggregator" | "liquid_staking" | "cdp"
    tvl_usd: float
    market_share_pct: float     # this protocol's TVL / total category TVL * 100
    tvl_30d_growth_pct: float   # TVL growth over 30d
    user_count: int             # approximate (0 if unknown)
    revenue_30d_usd: float      # 30-day protocol revenue (0 if unknown)


@dataclass
class DominanceReport:
    category: str
    total_tvl_usd: float
    protocols: List[ProtocolMarketShare]    # sorted by tvl desc

    # Market structure
    hhi: float              # Herfindahl-Hirschman Index of TVL concentration
    top1_share_pct: float   # #1 protocol's share
    top3_share_pct: float   # top 3 combined
    cr4: float              # concentration ratio: top 4 combined share

    # Classification
    market_structure: str   # MONOPOLY | DUOPOLY | OLIGOPOLY | COMPETITIVE
    moat_score: float       # top protocol's moat (0–100)

    # Dynamics
    fastest_grower: str     # protocol with highest tvl_30d_growth_pct
    market_leader: str      # protocol with highest TVL
    challenger: str         # protocol with 2nd highest TVL (or "none" if only 1)

    category_health: str    # HEALTHY | CONCENTRATED | DOMINATED
    warnings: List[str]
    saved_to: str


# ---------------------------------------------------------------------------
# Pure math helpers
# ---------------------------------------------------------------------------

def compute_shares(
    protocols_raw: List[ProtocolRaw],
    category: str,
) -> List[ProtocolMarketShare]:
    """Compute market share for each protocol from raw input tuples."""
    total_tvl = sum(p[1] for p in protocols_raw)
    result: List[ProtocolMarketShare] = []
    for proto, tvl, growth, users, revenue in protocols_raw:
        share = (tvl / total_tvl * 100.0) if total_tvl > 0 else 0.0
        result.append(ProtocolMarketShare(
            protocol=proto,
            category=category,
            tvl_usd=tvl,
            market_share_pct=share,
            tvl_30d_growth_pct=growth,
            user_count=users,
            revenue_30d_usd=revenue,
        ))
    return result


def compute_hhi(shares_list: List[float]) -> float:
    """Herfindahl-Hirschman Index: sum((share_pct/100)^2)."""
    return sum((s / 100.0) ** 2 for s in shares_list)


# ---------------------------------------------------------------------------
# Signal derivation helpers
# ---------------------------------------------------------------------------

def _market_structure(top1: float, top2: float, cr4: float) -> str:
    """Classify market structure based on concentration."""
    if top1 > 70:
        return "MONOPOLY"
    if top1 + top2 > 80:
        return "DUOPOLY"
    if cr4 > 70:
        return "OLIGOPOLY"
    return "COMPETITIVE"


def _moat_score(leader: ProtocolMarketShare, hhi: float) -> float:
    """Compute moat score for the market leader (0–100).
    moat = leader.market_share_pct * 0.4 + (1 - hhi) * 30 + revenue_score * 0.3
    revenue_score = min(100, revenue_30d_usd / 1_000_000)
    """
    revenue_score = min(100.0, leader.revenue_30d_usd / 1_000_000.0)
    moat = leader.market_share_pct * 0.4 + (1.0 - hhi) * 30.0 + revenue_score * 0.3
    return min(100.0, moat)


def _category_health(hhi: float) -> str:
    if hhi < 0.25:
        return "HEALTHY"
    if hhi < 0.50:
        return "CONCENTRATED"
    return "DOMINATED"


def _build_warnings(
    top1_share: float,
    protocols: List[ProtocolMarketShare],
) -> List[str]:
    warnings: List[str] = []
    if top1_share > 60:
        warnings.append("single protocol dominance")
    if any(p.tvl_30d_growth_pct > 50 for p in protocols):
        warnings.append("rapid challenger growth")
    if any(p.tvl_30d_growth_pct < -20 for p in protocols):
        warnings.append("major TVL outflow detected")
    return warnings


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(
    category: str,
    protocols_raw: List[ProtocolRaw],
    data_file: Path = DATA_FILE,
) -> DominanceReport:
    """Compute a full DominanceReport from raw protocol data."""
    if not protocols_raw:
        raise ValueError("protocols_raw must not be empty")

    protocols = compute_shares(protocols_raw, category)
    # Sort by TVL descending
    protocols.sort(key=lambda p: p.tvl_usd, reverse=True)

    total_tvl = sum(p.tvl_usd for p in protocols)
    shares = [p.market_share_pct for p in protocols]

    hhi = compute_hhi(shares)

    top1 = shares[0] if len(shares) >= 1 else 0.0
    top3 = sum(shares[:3])
    cr4 = sum(shares[:4])

    top2 = shares[1] if len(shares) >= 2 else 0.0

    mkt_structure = _market_structure(top1, top2, cr4)
    moat = _moat_score(protocols[0], hhi)

    fastest_grower = max(protocols, key=lambda p: p.tvl_30d_growth_pct).protocol
    market_leader = protocols[0].protocol
    challenger = protocols[1].protocol if len(protocols) >= 2 else "none"

    health = _category_health(hhi)
    warnings = _build_warnings(top1, protocols)

    return DominanceReport(
        category=category,
        total_tvl_usd=total_tvl,
        protocols=protocols,
        hhi=hhi,
        top1_share_pct=top1,
        top3_share_pct=top3,
        cr4=cr4,
        market_structure=mkt_structure,
        moat_score=moat,
        fastest_grower=fastest_grower,
        market_leader=market_leader,
        challenger=challenger,
        category_health=health,
        warnings=warnings,
        saved_to=str(data_file),
    )


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare_categories(reports: List[DominanceReport]) -> List[DominanceReport]:
    """Return reports sorted by HHI descending (most concentrated first)."""
    return sorted(reports, key=lambda r: r.hhi, reverse=True)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _protocol_to_dict(p: ProtocolMarketShare) -> Dict[str, Any]:
    return {
        "protocol": p.protocol,
        "category": p.category,
        "tvl_usd": p.tvl_usd,
        "market_share_pct": p.market_share_pct,
        "tvl_30d_growth_pct": p.tvl_30d_growth_pct,
        "user_count": p.user_count,
        "revenue_30d_usd": p.revenue_30d_usd,
    }


def _report_to_dict(report: DominanceReport) -> Dict[str, Any]:
    return {
        "category": report.category,
        "total_tvl_usd": report.total_tvl_usd,
        "protocols": [_protocol_to_dict(p) for p in report.protocols],
        "hhi": report.hhi,
        "top1_share_pct": report.top1_share_pct,
        "top3_share_pct": report.top3_share_pct,
        "cr4": report.cr4,
        "market_structure": report.market_structure,
        "moat_score": report.moat_score,
        "fastest_grower": report.fastest_grower,
        "market_leader": report.market_leader,
        "challenger": report.challenger,
        "category_health": report.category_health,
        "warnings": report.warnings,
        "saved_to": report.saved_to,
        "_saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def save_results(report: DominanceReport, data_file: Path = DATA_FILE) -> None:
    """Append report to ring-buffer JSON file (max MAX_ENTRIES entries). Atomic write."""
    data_file = Path(data_file)
    data_file.parent.mkdir(parents=True, exist_ok=True)

    existing: List[Dict[str, Any]] = []
    if data_file.exists():
        try:
            with open(data_file) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(_report_to_dict(report))
    if len(existing) > MAX_ENTRIES:
        existing = existing[-MAX_ENTRIES:]

    tmp = data_file.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(existing, f, indent=2)
    os.replace(tmp, data_file)


def load_history(data_file: Path = DATA_FILE) -> List[Dict[str, Any]]:
    """Load saved report history from JSON file."""
    data_file = Path(data_file)
    if not data_file.exists():
        return []
    try:
        with open(data_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Demo: lending category with 4 protocols
    protocols_raw: List[ProtocolRaw] = [
        ("Aave V3",     5_000_000_000, 10.0,  50000, 2_000_000),
        ("Compound V3", 1_500_000_000,  5.0,  15000,   500_000),
        ("Morpho",        800_000_000, 35.0,   8000,   200_000),
        ("Euler V2",      300_000_000, -5.0,   3000,    50_000),
    ]

    report = analyze("lending", protocols_raw)
    print(f"Category       : {report.category}")
    print(f"Total TVL      : ${report.total_tvl_usd:,.0f}")
    print(f"HHI            : {report.hhi:.4f}")
    print(f"Market structure: {report.market_structure}")
    print(f"Category health : {report.category_health}")
    print(f"Market leader  : {report.market_leader} ({report.top1_share_pct:.1f}%)")
    print(f"Challenger     : {report.challenger}")
    print(f"Fastest grower : {report.fastest_grower}")
    print(f"Moat score     : {report.moat_score:.1f}")
    print(f"Warnings       : {report.warnings}")
