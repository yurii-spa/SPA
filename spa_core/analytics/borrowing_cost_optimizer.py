"""
MP-808: BorrowingCostOptimizer
Finds the cheapest borrowing option across protocols for a given collateral
and loan amount, accounting for origination fees and collateralisation
requirements.

Advisory / read-only analytics module.
Pure stdlib only. Atomic JSON writes. Ring-buffer 100 entries.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ── Paths ────────────────────────────────────────────────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
_DATA_DIR = os.path.join(_REPO_ROOT, "data")
_LOG_FILE = os.path.join(_DATA_DIR, "borrowing_cost_log.json")

_RING_BUFFER_CAP = 100
_DEFAULT_LOAN_DURATION_DAYS = 30


# ── Public API ───────────────────────────────────────────────────────────────

def analyze(
    borrow_request: Dict,
    lending_markets: List[Dict],
    config: Optional[Dict] = None,
) -> Dict:
    """
    Find the cheapest borrowing option across *lending_markets* for the given
    *borrow_request*, accounting for origination fees and collateralisation
    requirements.

    borrow_request keys:
        asset             str    e.g. "USDC"
        amount_usd        float  desired borrow amount
        collateral_usd    float  available collateral
        max_rate          float  max acceptable borrow rate %

    lending_markets items:
        protocol              str
        asset                 str
        borrow_rate_apy       float  annual %
        min_collateral_ratio  float  e.g. 1.5 = 150% collateral required
        origination_fee_pct   float  one-time fee on borrow amount
        max_borrow_usd        float | None  None = unlimited

    config keys (optional):
        loan_duration_days  int  default 30

    Returns a result dict (see module docstring for full schema).
    """
    if config is None:
        config = {}

    duration_days: int = int(config.get("loan_duration_days", _DEFAULT_LOAN_DURATION_DAYS))
    ts: float = time.time()

    asset: str = str(borrow_request.get("asset", ""))
    amount_usd: float = float(borrow_request.get("amount_usd", 0.0))
    collateral_usd: float = float(borrow_request.get("collateral_usd", 0.0))
    max_rate: float = float(borrow_request.get("max_rate", math.inf))

    viable_markets: List[Dict] = []
    filtered_out: List[str] = []

    for market in lending_markets:
        protocol: str = str(market.get("protocol", ""))
        m_asset: str = str(market.get("asset", ""))
        borrow_rate_apy: float = float(market.get("borrow_rate_apy", 0.0))
        min_col_ratio: float = float(market.get("min_collateral_ratio", 1.0))
        orig_fee_pct: float = float(market.get("origination_fee_pct", 0.0))
        max_borrow: Optional[float] = (
            float(market["max_borrow_usd"])
            if market.get("max_borrow_usd") is not None
            else None
        )

        # ── Filter: asset mismatch ────────────────────────────────────────
        if m_asset != asset:
            filtered_out.append(protocol)
            continue

        # ── max_borrowable = collateral / min_collateral_ratio ────────────
        if min_col_ratio <= 0.0:
            max_borrowable = math.inf
        else:
            max_borrowable = collateral_usd / min_col_ratio

        # ── Filter: insufficient collateral ──────────────────────────────
        if max_borrowable < amount_usd:
            filtered_out.append(protocol)
            continue

        # ── Filter: rate too high ─────────────────────────────────────────
        if borrow_rate_apy > max_rate:
            filtered_out.append(protocol)
            continue

        # ── Filter: pool limit ────────────────────────────────────────────
        if max_borrow is not None and max_borrow < amount_usd:
            filtered_out.append(protocol)
            continue

        # ── Costs ─────────────────────────────────────────────────────────
        origination_fee_usd: float = amount_usd * orig_fee_pct / 100.0
        interest_usd: float = amount_usd * borrow_rate_apy / 100.0 / 365.0 * duration_days
        total_cost_usd: float = origination_fee_usd + interest_usd

        # effective APY = total_cost / amount * 365/duration * 100
        if amount_usd > 0 and duration_days > 0:
            effective_apy: float = total_cost_usd / amount_usd * 365.0 / duration_days * 100.0
        else:
            effective_apy = 0.0

        # collateral utilisation = amount / max_borrowable * 100
        if math.isinf(max_borrowable) or max_borrowable <= 0:
            col_utilisation_pct: float = 0.0
        else:
            col_utilisation_pct = amount_usd / max_borrowable * 100.0

        # max_borrowable_usd in result: None when unlimited (inf)
        max_borrowable_result: Optional[float] = (
            None if math.isinf(max_borrowable) else max_borrowable
        )

        viable_markets.append({
            "protocol": protocol,
            "borrow_rate_apy": borrow_rate_apy,
            "origination_fee_usd": origination_fee_usd,
            "interest_30d_usd": interest_usd,
            "total_cost_usd": total_cost_usd,
            "effective_apy": effective_apy,
            "max_borrowable_usd": max_borrowable_result,
            "collateral_utilization_pct": col_utilisation_pct,
            "rank": 0,  # filled after sorting
        })

    # ── Sort by total_cost_usd, assign ranks ─────────────────────────────────
    viable_markets.sort(key=lambda m: m["total_cost_usd"])
    for i, m in enumerate(viable_markets, start=1):
        m["rank"] = i

    # ── Summary fields ────────────────────────────────────────────────────────
    best_market: Optional[str] = viable_markets[0]["protocol"] if viable_markets else None
    cheapest_rate: Optional[str] = (
        min(viable_markets, key=lambda m: m["borrow_rate_apy"])["protocol"]
        if viable_markets
        else None
    )
    most_flexible: Optional[str] = (
        _most_flexible_protocol(viable_markets) if viable_markets else None
    )

    result = {
        "asset": asset,
        "amount_requested_usd": amount_usd,
        "collateral_usd": collateral_usd,
        "viable_markets": viable_markets,
        "best_market": best_market,
        "cheapest_rate": cheapest_rate,
        "most_flexible": most_flexible,
        "filtered_out": filtered_out,
        "timestamp": ts,
    }

    _append_log(result)
    return result


# ── Helpers ──────────────────────────────────────────────────────────────────

def _most_flexible_protocol(viable_markets: List[Dict]) -> str:
    """Protocol with highest max_borrowable_usd (None = unlimited → treat as inf)."""
    def _key(m: Dict) -> float:
        v = m.get("max_borrowable_usd")
        return math.inf if v is None else float(v)

    return max(viable_markets, key=_key)["protocol"]


# ── Log persistence (ring-buffer, atomic) ────────────────────────────────────

def _load_log() -> list:
    if not os.path.exists(_LOG_FILE):
        return []
    try:
        with open(_LOG_FILE, "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _append_log(entry: Dict) -> None:
    """Append *entry* to the ring-buffer log, capped at _RING_BUFFER_CAP."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    log = _load_log()
    # Keep a compact copy (skip large viable_markets list for log)
    compact = {k: v for k, v in entry.items() if k != "viable_markets"}
    compact["viable_markets_count"] = len(entry.get("viable_markets", []))
    log.append(compact)
    if len(log) > _RING_BUFFER_CAP:
        log = log[-_RING_BUFFER_CAP:]
    _atomic_write(_LOG_FILE, log)


def _atomic_write(path: str, obj) -> None:
    atomic_save(obj, str(path))
