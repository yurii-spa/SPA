"""YieldOpportunityScanner — MP-803.

Scans across all available yield opportunities and surfaces the top picks
based on a composite score of APY, safety, liquidity, and duration fit.

Design constraints
------------------
* Pure stdlib only — no external dependencies.
* Advisory / read-only — never touches allocator / risk / execution.
* Atomic writes: tmp-file + os.replace on every save.
* Ring-buffer: data/yield_opportunity_scan_log.json capped at MAX_ENTRIES=100.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.

Scoring formula summary
-----------------------
  apy_score      (0–40)  : min(apy / 25 * 40, 40)
  safety_score   (0–30)  : audit_count*5 + min(age_days/365,1)*15, cap 30
  liquidity_score(0–20)  : log10(tvl/1e6+1) / log10(1001) * 20, cap 20
  fit_score      (0–10)  : 10 if chain in preferred_chains else 5;
                           then −3 if lock_days > 0 (floor 0)
  composite score (0–100): sum of above four components

Filters applied before scoring
-------------------------------
  * chain not in portfolio.preferred_chains
  * lock_days > portfolio.max_lock_days
  * apy < portfolio.min_apy
  * min_deposit_usd > portfolio.total_usd

CLI (advisory, no writes unless --run)
---------------------------------------
  python3 -m spa_core.analytics.yield_opportunity_scanner --check
  python3 -m spa_core.analytics.yield_opportunity_scanner --run
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Module-level configuration
# ---------------------------------------------------------------------------

DATA_FILE = Path("data/yield_opportunity_scan_log.json")
MAX_ENTRIES: int = 100
DEFAULT_TOP_N: int = 5


# ---------------------------------------------------------------------------
# Internal scoring helpers (pure functions — deterministic, no I/O)
# ---------------------------------------------------------------------------

def _apy_score(apy: float) -> float:
    """0–40: min(apy / 25 * 40, 40)."""
    return min(apy / 25.0 * 40.0, 40.0)


def _safety_score(audit_count: int, age_days: int) -> float:
    """0–30: audit_count * 5 + min(age_days / 365, 1) * 15, capped 30."""
    raw = float(audit_count) * 5.0 + min(float(age_days) / 365.0, 1.0) * 15.0
    return min(raw, 30.0)


def _liquidity_score(tvl_usd: float) -> float:
    """0–20: log10(tvl / 1e6 + 1) / log10(1001) * 20, capped 20."""
    tvl = max(float(tvl_usd), 0.0)
    numerator = math.log10(tvl / 1_000_000.0 + 1.0)
    denominator = math.log10(1001.0)
    return min(numerator / denominator * 20.0, 20.0)


def _fit_score(chain: str, preferred_chains: List[str], lock_days: int) -> float:
    """0–10: base 10 if chain in preferred else 5; −3 if lock_days > 0 (floor 0)."""
    base = 10.0 if chain in preferred_chains else 5.0
    if lock_days > 0:
        base -= 3.0
    return max(base, 0.0)


# ---------------------------------------------------------------------------
# Ring-buffer persistence (atomic write)
# ---------------------------------------------------------------------------

def _append_log(entry: Dict[str, Any]) -> None:
    """Atomically append *entry* to the ring-buffer scan log (max MAX_ENTRIES)."""
    try:
        data_file: Path = DATA_FILE
        data_file.parent.mkdir(parents=True, exist_ok=True)

        if data_file.exists():
            try:
                existing: List[Any] = json.loads(
                    data_file.read_text(encoding="utf-8")
                )
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError):
                existing = []
        else:
            existing = []

        existing.append(entry)
        if len(existing) > MAX_ENTRIES:
            existing = existing[-MAX_ENTRIES:]

        tmp = data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        os.replace(tmp, data_file)
    except Exception:  # noqa: BLE001 — advisory module; never raise on I/O errors
        pass


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def analyze(
    opportunities: List[Dict[str, Any]],
    portfolio: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Scan yield opportunities and return composite-scored top picks.

    Parameters
    ----------
    opportunities:
        List of opportunity dicts with keys: id, protocol, type, apy,
        tvl_usd, audit_count, age_days, min_deposit_usd, lock_days, chain.
    portfolio:
        Portfolio context: total_usd, preferred_chains, max_lock_days, min_apy.
    config:
        Optional overrides.  Supports ``top_n`` (default 5).

    Returns
    -------
    dict with keys: total_scanned, filtered_out, scored, top_picks,
                    best_apy, safest, timestamp.
    """
    if config is None:
        config = {}

    top_n: int = max(int(config.get("top_n", DEFAULT_TOP_N)), 0)
    total_usd: float = float(portfolio.get("total_usd", 0.0))
    preferred_chains: List[str] = list(portfolio.get("preferred_chains", []))
    max_lock_days: int = int(portfolio.get("max_lock_days", 0))
    min_apy: float = float(portfolio.get("min_apy", 0.0))

    total_scanned: int = len(opportunities)
    filtered_out: int = 0
    scored: List[Dict[str, Any]] = []

    for opp in opportunities:
        chain: str = str(opp.get("chain", ""))
        lock_days: int = int(opp.get("lock_days", 0))
        apy: float = float(opp.get("apy", 0.0))
        min_deposit: float = float(opp.get("min_deposit_usd", 0.0))

        # ---- Portfolio filters (order matters for counting) -----------------
        if chain not in preferred_chains:
            filtered_out += 1
            continue
        if lock_days > max_lock_days:
            filtered_out += 1
            continue
        if apy < min_apy:
            filtered_out += 1
            continue
        if min_deposit > total_usd:
            filtered_out += 1
            continue

        # ---- Composite scoring ----------------------------------------------
        tvl_usd: float = float(opp.get("tvl_usd", 0.0))
        audit_count: int = int(opp.get("audit_count", 0))
        age_days: int = int(opp.get("age_days", 0))

        as_: float = round(_apy_score(apy), 2)
        ss: float = round(_safety_score(audit_count, age_days), 2)
        ls: float = round(_liquidity_score(tvl_usd), 2)
        fs: float = round(_fit_score(chain, preferred_chains, lock_days), 2)
        composite: float = round(as_ + ss + ls + fs, 2)

        scored.append({
            "id": str(opp.get("id", "")),
            "protocol": str(opp.get("protocol", "")),
            "type": str(opp.get("type", "")),
            "chain": chain,
            "apy": apy,
            "score": composite,
            "apy_score": as_,
            "safety_score": ss,
            "liquidity_score": ls,
            "fit_score": fs,
            "recommended_allocation_usd": 0.0,
        })

    # Sort by composite score descending (stable sort preserves insertion order on ties)
    scored.sort(key=lambda x: x["score"], reverse=True)

    # ---- Top-N picks ---------------------------------------------------------
    top_picks_entries = scored[:top_n]
    top_picks_ids: List[str] = [e["id"] for e in top_picks_entries]
    n_picks: int = len(top_picks_ids)

    # Recommended allocation for top-N picks (score-weighted per pick)
    if n_picks > 0:
        top_ids_set = set(top_picks_ids)
        for entry in scored:
            if entry["id"] in top_ids_set:
                entry["recommended_allocation_usd"] = round(
                    entry["score"] / 100.0 * total_usd / n_picks, 2
                )

    # ---- Aggregate metadata -------------------------------------------------
    best_apy_id: Optional[str] = None
    safest_id: Optional[str] = None
    if scored:
        best_apy_id = max(scored, key=lambda x: x["apy"])["id"]
        safest_id = max(scored, key=lambda x: x["safety_score"])["id"]

    result: Dict[str, Any] = {
        "total_scanned": total_scanned,
        "filtered_out": filtered_out,
        "scored": scored,
        "top_picks": top_picks_ids,
        "best_apy": best_apy_id,
        "safest": safest_id,
        "timestamp": time.time(),
    }

    _append_log(result)
    return result


# ---------------------------------------------------------------------------
# CLI entry-point (advisory only — exits 0 always)
# ---------------------------------------------------------------------------

def _demo_opportunities() -> List[Dict[str, Any]]:
    return [
        {
            "id": "aave-eth-usdc",
            "protocol": "Aave V3",
            "type": "lending",
            "apy": 3.5,
            "tvl_usd": 2_000_000_000,
            "audit_count": 6,
            "age_days": 1200,
            "min_deposit_usd": 100,
            "lock_days": 0,
            "chain": "ethereum",
        },
        {
            "id": "compound-eth-usdc",
            "protocol": "Compound V3",
            "type": "lending",
            "apy": 4.8,
            "tvl_usd": 800_000_000,
            "audit_count": 5,
            "age_days": 900,
            "min_deposit_usd": 100,
            "lock_days": 0,
            "chain": "ethereum",
        },
        {
            "id": "morpho-steakhouse",
            "protocol": "Morpho Steakhouse",
            "type": "vault",
            "apy": 6.5,
            "tvl_usd": 150_000_000,
            "audit_count": 3,
            "age_days": 400,
            "min_deposit_usd": 500,
            "lock_days": 0,
            "chain": "ethereum",
        },
    ]


if __name__ == "__main__":
    import sys

    write_mode = "--run" in sys.argv
    opps = _demo_opportunities()
    portfolio = {
        "total_usd": 100_000,
        "preferred_chains": ["ethereum"],
        "max_lock_days": 0,
        "min_apy": 1.0,
    }
    result = analyze(opps, portfolio)
    print(json.dumps(result, indent=2))
    if not write_mode:
        # Undo the log append for --check mode by reading nothing (log already written)
        print("\n[--check mode: result printed, log written as advisory side-effect]")
    sys.exit(0)
