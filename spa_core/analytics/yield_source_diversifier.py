"""
MP-755: YieldSourceDiversifier
Analyzes diversification of yield sources across a DeFi portfolio.
Advisory/read-only. Pure stdlib. Atomic JSON writes. Ring-buffer 100.
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_source_diversifier_log.json"
)
_RING_BUFFER_CAP = 100

# Valid yield types
YIELD_TYPES = {
    "LENDING",
    "LIQUIDITY_PROVISION",
    "STAKING",
    "REAL_YIELD",
    "INCENTIVE_EMISSIONS",
    "RESTAKING",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class YieldSource:
    protocol: str
    chain: str
    yield_type: str
    allocation_usd: float
    apy_pct: float


@dataclass
class DiversificationScore:
    # Protocol-level
    protocol_hhi: float = 0.0
    protocol_concentration_label: str = "LOW"
    top_protocol: str = ""
    top_protocol_share_pct: float = 0.0

    # Chain-level
    chain_hhi: float = 0.0
    chain_concentration_label: str = "LOW"
    top_chain: str = ""
    top_chain_share_pct: float = 0.0

    # Yield-type level
    yield_type_hhi: float = 0.0
    yield_type_label: str = "LOW"
    top_yield_type: str = ""
    top_yield_type_share_pct: float = 0.0

    # Composite (0-100)
    diversification_score: float = 0.0
    diversification_label: str = "CONCENTRATED"

    # Recommendations
    warnings: List[str] = field(default_factory=list)
    recommendation: str = ""


@dataclass
class DiversificationResult:
    sources: List[YieldSource] = field(default_factory=list)
    total_allocation_usd: float = 0.0
    weighted_avg_apy_pct: float = 0.0
    score: DiversificationScore = field(default_factory=DiversificationScore)
    saved_to: str = ""


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------

def compute_hhi(allocations_dict: Dict[str, float]) -> float:
    """
    Herfindahl-Hirschman Index: sum of (share_i)^2.
    Returns 0 if empty or total == 0.
    """
    if not allocations_dict:
        return 0.0
    total = sum(allocations_dict.values())
    if total <= 0:
        return 0.0
    return sum((v / total) ** 2 for v in allocations_dict.values())


def concentration_label(hhi: float) -> str:
    """LOW (<0.15) | MODERATE (0.15-0.25) | HIGH (>0.25)."""
    if hhi < 0.15:
        return "LOW"
    if hhi <= 0.25:
        return "MODERATE"
    return "HIGH"


def compute_diversification_score(
    protocol_hhi: float,
    chain_hhi: float,
    yield_type_hhi: float,
) -> float:
    """(1-protocol_hhi)*40 + (1-chain_hhi)*30 + (1-yield_type_hhi)*30, clamped 0-100."""
    score = (
        (1.0 - protocol_hhi) * 40.0
        + (1.0 - chain_hhi) * 30.0
        + (1.0 - yield_type_hhi) * 30.0
    )
    return max(0.0, min(100.0, score))


def diversification_label(score: float) -> str:
    """WELL_DIVERSIFIED (>=70) | MODERATE (40-70) | CONCENTRATED (<40)."""
    if score >= 70.0:
        return "WELL_DIVERSIFIED"
    if score >= 40.0:
        return "MODERATE"
    return "CONCENTRATED"


def _top_item(allocations_dict: Dict[str, float]) -> tuple:
    """Returns (name, share_pct) for the highest-allocated item."""
    if not allocations_dict:
        return ("", 0.0)
    total = sum(allocations_dict.values())
    if total <= 0:
        return ("", 0.0)
    top_name = max(allocations_dict, key=lambda k: allocations_dict[k])
    share = allocations_dict[top_name] / total * 100.0
    return top_name, share


def compute_warnings(
    top_protocol: str,
    top_protocol_share: float,
    top_chain: str,
    top_chain_share: float,
    top_yield_type: str,
    top_yield_type_share: float,
) -> List[str]:
    warnings: List[str] = []
    if top_protocol_share > 50.0:
        warnings.append(f"Over 50% in single protocol: {top_protocol}")
    if top_chain_share > 80.0:
        warnings.append(f"Over 80% on single chain: {top_chain}")
    if top_yield_type_share > 60.0:
        warnings.append(f"Over 60% in single yield type: {top_yield_type}")
    return warnings


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze(
    sources_data: List[dict],
    data_file: Optional[str] = None,
) -> DiversificationResult:
    """
    sources_data: list of dicts {protocol, chain, yield_type, allocation_usd, apy_pct}
    """
    sources = [YieldSource(**s) for s in sources_data]
    total = sum(s.allocation_usd for s in sources)

    if total > 0:
        weighted_avg_apy = sum(s.allocation_usd * s.apy_pct for s in sources) / total
    else:
        weighted_avg_apy = 0.0

    # Aggregate by dimension
    protocol_allocs: Dict[str, float] = {}
    chain_allocs: Dict[str, float] = {}
    yield_type_allocs: Dict[str, float] = {}

    for s in sources:
        protocol_allocs[s.protocol] = protocol_allocs.get(s.protocol, 0.0) + s.allocation_usd
        chain_allocs[s.chain] = chain_allocs.get(s.chain, 0.0) + s.allocation_usd
        yield_type_allocs[s.yield_type] = yield_type_allocs.get(s.yield_type, 0.0) + s.allocation_usd

    p_hhi = compute_hhi(protocol_allocs)
    c_hhi = compute_hhi(chain_allocs)
    yt_hhi = compute_hhi(yield_type_allocs)

    top_proto, top_proto_share = _top_item(protocol_allocs)
    top_chain, top_chain_share = _top_item(chain_allocs)
    top_yt, top_yt_share = _top_item(yield_type_allocs)

    div_score = compute_diversification_score(p_hhi, c_hhi, yt_hhi)
    div_label = diversification_label(div_score)

    warnings = compute_warnings(
        top_proto, top_proto_share,
        top_chain, top_chain_share,
        top_yt, top_yt_share,
    )

    if div_label == "CONCENTRATED":
        recommendation = (
            "Portfolio highly concentrated. Diversify across protocols and chains."
        )
    elif div_label == "MODERATE":
        recommendation = (
            "Moderate diversification. Consider adding more protocols or chains."
        )
    else:
        recommendation = (
            "Well diversified across protocols, chains, and yield types."
        )

    score = DiversificationScore(
        protocol_hhi=p_hhi,
        protocol_concentration_label=concentration_label(p_hhi),
        top_protocol=top_proto,
        top_protocol_share_pct=top_proto_share,
        chain_hhi=c_hhi,
        chain_concentration_label=concentration_label(c_hhi),
        top_chain=top_chain,
        top_chain_share_pct=top_chain_share,
        yield_type_hhi=yt_hhi,
        yield_type_label=concentration_label(yt_hhi),
        top_yield_type=top_yt,
        top_yield_type_share_pct=top_yt_share,
        diversification_score=div_score,
        diversification_label=div_label,
        warnings=warnings,
        recommendation=recommendation,
    )

    return DiversificationResult(
        sources=sources,
        total_allocation_usd=total,
        weighted_avg_apy_pct=weighted_avg_apy,
        score=score,
        saved_to="",
    )


# ---------------------------------------------------------------------------
# Persistence (ring-buffer 100)
# ---------------------------------------------------------------------------

def _resolve_path(data_file: Optional[str]) -> str:
    return data_file or _DEFAULT_DATA_FILE


def load_history(data_file: Optional[str] = None) -> list:
    path = _resolve_path(data_file)
    if not os.path.exists(path):
        return []
    with open(path, "r") as fh:
        return json.load(fh)


def save_results(
    result: DiversificationResult,
    data_file: Optional[str] = None,
) -> DiversificationResult:
    """Append snapshot to ring-buffer JSON (cap 100). Returns updated result."""
    path = _resolve_path(data_file)
    history = load_history(path)

    snapshot = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_allocation_usd": result.total_allocation_usd,
        "weighted_avg_apy_pct": result.weighted_avg_apy_pct,
        "score": asdict(result.score),
        "sources": [asdict(s) for s in result.sources],
    }

    history.append(snapshot)
    history = history[-_RING_BUFFER_CAP:]

    tmp_path = path + ".tmp"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(tmp_path, "w") as fh:
        json.dump(history, fh, indent=2)
    os.replace(tmp_path, path)

    result.saved_to = path
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-755 YieldSourceDiversifier")
    parser.add_argument("--run", action="store_true", help="Compute and save")
    parser.add_argument("--check", action="store_true", help="Compute only (default)")
    args = parser.parse_args()

    sample = [
        {"protocol": "Aave", "chain": "Ethereum", "yield_type": "LENDING",
         "allocation_usd": 30000, "apy_pct": 3.5},
        {"protocol": "Compound", "chain": "Ethereum", "yield_type": "LENDING",
         "allocation_usd": 20000, "apy_pct": 4.8},
        {"protocol": "Morpho", "chain": "Ethereum", "yield_type": "LENDING",
         "allocation_usd": 25000, "apy_pct": 6.5},
        {"protocol": "Lido", "chain": "Ethereum", "yield_type": "STAKING",
         "allocation_usd": 15000, "apy_pct": 4.0},
        {"protocol": "Uniswap", "chain": "Arbitrum", "yield_type": "LIQUIDITY_PROVISION",
         "allocation_usd": 10000, "apy_pct": 12.0},
    ]

    result = analyze(sample)
    sc = result.score
    print(f"Total allocation   : ${result.total_allocation_usd:,.0f}")
    print(f"Weighted avg APY   : {result.weighted_avg_apy_pct:.2f}%")
    print(f"Diversification    : {sc.diversification_score:.1f} ({sc.diversification_label})")
    print(f"Protocol HHI       : {sc.protocol_hhi:.4f} ({sc.protocol_concentration_label})")
    print(f"Chain HHI          : {sc.chain_hhi:.4f} ({sc.chain_concentration_label})")
    print(f"Yield type HHI     : {sc.yield_type_hhi:.4f} ({sc.yield_type_label})")
    if sc.warnings:
        for w in sc.warnings:
            print(f"  ⚠ {w}")
    print(f"Recommendation     : {sc.recommendation}")

    if args.run:
        save_results(result)
        print(f"Saved to: {result.saved_to}")
