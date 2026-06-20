"""
MP-715: YieldAggregationEngine
Advisory/read-only module. Pure stdlib. Atomic JSON writes via tmp+os.replace.
Ring-buffer cap: 100 entries.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_DATA_DIR = os.path.join(_REPO_ROOT, "data")
_LOG_FILE = os.path.join(_DATA_DIR, "yield_aggregation_log.json")

_RING_BUFFER_CAP = 100
_TOP_N = 10


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class YieldEntry:
    source: str            # adapter name / data source
    protocol: str
    pool: str
    chain: str
    apy: float
    tvl_usd: float
    risk_score: float      # 0–100
    liquidity_usd: float   # exit liquidity
    last_updated_iso: str  # ISO datetime of last data refresh


@dataclass
class AggregatedView:
    total_entries: int
    unique_protocols: int
    unique_chains: int

    # Rankings
    top_by_apy: List[YieldEntry]
    top_by_risk_adjusted: List[YieldEntry]
    top_by_tvl: List[YieldEntry]

    # Statistics
    avg_apy: float
    median_apy: float
    max_apy: float
    min_apy: float
    avg_risk_score: float

    # Chain breakdown
    by_chain: Dict[str, dict]  # {chain: {"count": int, "avg_apy": float, "total_tvl": float}}

    # Filters applied
    filters_applied: dict  # {"min_tvl": float, "max_risk": float, "chains": list}

    saved_to: str = ""


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def risk_adjusted_apy(entry: YieldEntry) -> float:
    """Risk-adjusted APY: apy / (1 + risk_score / 100)."""
    return entry.apy / (1 + entry.risk_score / 100)


def compute_median(values: List[float]) -> float:
    """Return the median of a numeric list. Returns 0.0 for empty list."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate(
    entries: List[YieldEntry],
    min_tvl_usd: float = 0.0,
    max_risk_score: float = 100.0,
    allowed_chains: Optional[List[str]] = None,
) -> AggregatedView:
    """
    Filter entries and compute aggregated statistics + rankings.

    Parameters
    ----------
    entries         : full list of YieldEntry objects
    min_tvl_usd     : minimum TVL filter (inclusive)
    max_risk_score  : maximum risk score filter (inclusive)
    allowed_chains  : if non-empty list, only include those chains; None/[] = all
    """
    # Normalise allowed_chains
    chain_filter: Optional[set] = None
    if allowed_chains:
        chain_filter = {c.lower() for c in allowed_chains}

    filtered: List[YieldEntry] = []
    for e in entries:
        if e.tvl_usd < min_tvl_usd:
            continue
        if e.risk_score > max_risk_score:
            continue
        if chain_filter is not None and e.chain.lower() not in chain_filter:
            continue
        filtered.append(e)

    # Rankings
    top_by_apy = sorted(filtered, key=lambda x: x.apy, reverse=True)[:_TOP_N]
    top_by_risk_adjusted = sorted(
        filtered, key=lambda x: risk_adjusted_apy(x), reverse=True
    )[:_TOP_N]
    top_by_tvl = sorted(filtered, key=lambda x: x.tvl_usd, reverse=True)[:_TOP_N]

    # Statistics
    apys = [e.apy for e in filtered]
    risk_scores = [e.risk_score for e in filtered]

    if apys:
        avg_apy = sum(apys) / len(apys)
        median_apy = compute_median(apys)
        max_apy = max(apys)
        min_apy = min(apys)
        avg_risk_score = sum(risk_scores) / len(risk_scores)
    else:
        avg_apy = median_apy = max_apy = min_apy = avg_risk_score = 0.0

    # Unique counts
    unique_protocols = len({e.protocol for e in filtered})
    unique_chains = len({e.chain for e in filtered})

    # Chain breakdown
    by_chain: Dict[str, dict] = {}
    for e in filtered:
        ch = e.chain
        if ch not in by_chain:
            by_chain[ch] = {"count": 0, "total_apy": 0.0, "total_tvl": 0.0}
        by_chain[ch]["count"] += 1
        by_chain[ch]["total_apy"] += e.apy
        by_chain[ch]["total_tvl"] += e.tvl_usd

    chain_summary: Dict[str, dict] = {}
    for ch, v in by_chain.items():
        chain_summary[ch] = {
            "count": v["count"],
            "avg_apy": v["total_apy"] / v["count"],
            "total_tvl": v["total_tvl"],
        }

    filters_applied = {
        "min_tvl": min_tvl_usd,
        "max_risk": max_risk_score,
        "chains": allowed_chains if allowed_chains else [],
    }

    return AggregatedView(
        total_entries=len(filtered),
        unique_protocols=unique_protocols,
        unique_chains=unique_chains,
        top_by_apy=top_by_apy,
        top_by_risk_adjusted=top_by_risk_adjusted,
        top_by_tvl=top_by_tvl,
        avg_apy=avg_apy,
        median_apy=median_apy,
        max_apy=max_apy,
        min_apy=min_apy,
        avg_risk_score=avg_risk_score,
        by_chain=chain_summary,
        filters_applied=filters_applied,
    )


# ---------------------------------------------------------------------------
# Arbitrage detection
# ---------------------------------------------------------------------------

def find_arbitrage(
    view: AggregatedView,
    min_spread_pct: float = 0.5,
) -> List[Tuple[YieldEntry, YieldEntry, float]]:
    """
    Find pairs with the same pool name on different chains where APY spread
    exceeds min_spread_pct. Returns list of (entry_a, entry_b, spread) sorted
    by spread desc.

    Matching is case-insensitive on pool name; chains must differ.
    """
    # Combine all entries from the three ranking lists (de-duplicate by object id)
    seen_ids: set = set()
    all_entries: List[YieldEntry] = []
    for lst in (view.top_by_apy, view.top_by_risk_adjusted, view.top_by_tvl):
        for e in lst:
            if id(e) not in seen_ids:
                seen_ids.add(id(e))
                all_entries.append(e)

    # Group by pool name (lower)
    pool_groups: Dict[str, List[YieldEntry]] = {}
    for e in all_entries:
        key = e.pool.lower()
        pool_groups.setdefault(key, []).append(e)

    results: List[Tuple[YieldEntry, YieldEntry, float]] = []
    for pool_name, group in pool_groups.items():
        # Only interested if multiple chains present
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if a.chain.lower() == b.chain.lower():
                    continue  # same chain, skip
                spread = abs(a.apy - b.apy)
                if spread > min_spread_pct:
                    results.append((a, b, spread))

    results.sort(key=lambda x: x[2], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _entry_to_dict(e: YieldEntry) -> dict:
    return {
        "source": e.source,
        "protocol": e.protocol,
        "pool": e.pool,
        "chain": e.chain,
        "apy": e.apy,
        "tvl_usd": e.tvl_usd,
        "risk_score": e.risk_score,
        "liquidity_usd": e.liquidity_usd,
        "last_updated_iso": e.last_updated_iso,
    }


def _view_to_dict(view: AggregatedView, timestamp: str) -> dict:
    return {
        "timestamp": timestamp,
        "total_entries": view.total_entries,
        "unique_protocols": view.unique_protocols,
        "unique_chains": view.unique_chains,
        "top_by_apy": [_entry_to_dict(e) for e in view.top_by_apy],
        "top_by_risk_adjusted": [_entry_to_dict(e) for e in view.top_by_risk_adjusted],
        "top_by_tvl": [_entry_to_dict(e) for e in view.top_by_tvl],
        "avg_apy": view.avg_apy,
        "median_apy": view.median_apy,
        "max_apy": view.max_apy,
        "min_apy": view.min_apy,
        "avg_risk_score": view.avg_risk_score,
        "by_chain": view.by_chain,
        "filters_applied": view.filters_applied,
        "saved_to": view.saved_to,
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_history() -> list:
    """Load the ring-buffer log from disk. Returns empty list on error."""
    if not os.path.exists(_LOG_FILE):
        return []
    try:
        with open(_LOG_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def save_results(view: AggregatedView) -> str:
    """Append aggregated view to ring-buffer log (cap 100). Returns path written to."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    history = load_history()
    timestamp = datetime.now(timezone.utc).isoformat()
    entry = _view_to_dict(view, timestamp)
    history.append(entry)
    # Ring-buffer: keep last 100
    if len(history) > _RING_BUFFER_CAP:
        history = history[-_RING_BUFFER_CAP:]
    # Atomic write
    dir_path = os.path.dirname(_LOG_FILE)
    os.makedirs(dir_path, exist_ok=True)
    atomic_save(history, str(_LOG_FILE))
    view.saved_to = _LOG_FILE
    return _LOG_FILE


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo() -> None:
    now = datetime.now(timezone.utc).isoformat()
    entries = [
        YieldEntry("aave_v3", "Aave V3", "USDC", "ethereum", 3.5, 50_000_000, 10, 40_000_000, now),
        YieldEntry("compound_v3", "Compound V3", "USDC", "ethereum", 4.8, 30_000_000, 15, 25_000_000, now),
        YieldEntry("morpho", "Morpho Steakhouse", "USDC", "ethereum", 6.5, 20_000_000, 20, 15_000_000, now),
        YieldEntry("aave_arb", "Aave V3", "USDC", "arbitrum", 4.6, 10_000_000, 18, 8_000_000, now),
    ]
    view = aggregate(entries, min_tvl_usd=5_000_000, max_risk_score=50)
    print(f"Total entries: {view.total_entries}")
    print(f"Top by APY: {[e.protocol for e in view.top_by_apy]}")
    print(f"By chain: {view.by_chain}")
    arb = find_arbitrage(view, min_spread_pct=0.5)
    print(f"Arbitrage opportunities: {len(arb)}")
    save_results(view)
    print(f"Saved to: {view.saved_to}")


if __name__ == "__main__":
    _demo()
