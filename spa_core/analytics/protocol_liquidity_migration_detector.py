"""
MP-848: ProtocolLiquidityMigrationDetector
Detects when liquidity is migrating from one protocol to another by analyzing
correlated TVL changes across competing protocols in the same category.

Advisory / read-only analytics. Pure stdlib. Atomic writes (tmp + os.replace).
"""

import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/liquidity_migration_log.json")
MAX_ENTRIES = 100

_DEFAULT_CONFIG = {
    "migration_threshold_pct": 10.0,  # TVL drop > this % = losing
    "min_history": 4,                 # require at least N history points
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _merge_config(config: dict | None) -> dict:
    cfg = dict(_DEFAULT_CONFIG)
    if config:
        cfg.update(config)
    return cfg


def _safe_mean(values: list) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _migration_score(losing: list, gaining: list, total_in_category: int) -> float:
    """
    Compute migration score 0-100.
    - No losing and no gaining: 0.0
    - Losing but no gaining: 30.0
    - Gaining but no losing: 20.0
    - Both: min(100, (len(losing) + len(gaining)) / max(1, total_in_category) * 100 + 30)
    """
    if not losing and not gaining:
        return 0.0
    if losing and not gaining:
        return 30.0
    if gaining and not losing:
        return 20.0
    score = (len(losing) + len(gaining)) / max(1, total_in_category) * 100 + 30
    return min(100.0, score)


def _likely_trigger(
    gaining_protocols: list,
    losing_protocols: list,
) -> str:
    """
    Determine the likely trigger for a migration event.

    Precedence:
    1. If avg apy_current of gaining > avg apy_current of losing + 1.0 → yield differential
    2. If all losers' APY dropped (apy_current < apy_7d_ago) → APY deterioration
    3. Else → protocol-specific risk factors
    """
    if not losing_protocols and not gaining_protocols:
        return "Unknown trigger — monitor APY and governance changes"

    avg_gaining_apy = _safe_mean([p.get("apy_current", 0.0) for p in gaining_protocols])
    avg_losing_apy = _safe_mean([p.get("apy_current", 0.0) for p in losing_protocols])

    if gaining_protocols and avg_gaining_apy > avg_losing_apy + 1.0:
        return "Yield differential driving migration"

    # Check if all losers have declining APY
    if losing_protocols and all(
        p.get("apy_current", 0.0) < p.get("apy_7d_ago", 0.0)
        for p in losing_protocols
    ):
        return "APY deterioration causing exits"

    return "Protocol-specific risk factors driving capital rotation"


def _process_category(
    category: str,
    protocols_in_cat: list,
    migration_threshold_pct: float,
    min_history: int,
) -> tuple:
    """
    Process all protocols in a single category.

    Returns (flow_dict | None, skipped_names: list[str])
    - Returns None if category should be skipped (< 2 protocols meet min_history).
    """
    skipped = []
    eligible = []

    for p in protocols_in_cat:
        history = p.get("tvl_history", []) or []
        if len(history) < min_history:
            skipped.append(p.get("name", "unknown"))
        else:
            eligible.append(p)

    if len(eligible) < 2:
        # Only history-insufficient protocols are "skipped"; eligible-but-alone ones
        # are simply not included in any flow (no skipped entry for them).
        return None, skipped

    losing = []
    gaining = []

    for p in eligible:
        history = p.get("tvl_history", [])
        first = float(history[0])
        last = float(history[-1])
        if first > 0:
            tvl_change_pct = (last - first) / first * 100
        else:
            tvl_change_pct = None

        if tvl_change_pct is None:
            continue

        estimated_flow = abs(last - first)

        if tvl_change_pct <= -migration_threshold_pct:
            losing.append({
                "name": p.get("name", "unknown"),
                "tvl_change_pct": tvl_change_pct,
                "estimated_outflow_usd": estimated_flow,
                # Keep raw protocol data for trigger heuristics
                "_apy_current": p.get("apy_current", 0.0),
                "_apy_7d_ago": p.get("apy_7d_ago", 0.0),
            })
        elif tvl_change_pct >= migration_threshold_pct:
            gaining.append({
                "name": p.get("name", "unknown"),
                "tvl_change_pct": tvl_change_pct,
                "estimated_inflow_usd": estimated_flow,
                "_apy_current": p.get("apy_current", 0.0),
                "_apy_7d_ago": p.get("apy_7d_ago", 0.0),
            })

    score = _migration_score(losing, gaining, len(eligible))
    detected = score >= 40

    # Build trigger data from raw protocol dicts
    trigger = _likely_trigger(
        [{
            "apy_current": e.get("_apy_current", 0.0),
            "apy_7d_ago": e.get("_apy_7d_ago", 0.0),
        } for e in gaining],
        [{
            "apy_current": e.get("_apy_current", 0.0),
            "apy_7d_ago": e.get("_apy_7d_ago", 0.0),
        } for e in losing],
    )

    # Clean output: strip internal _keys from losing/gaining
    clean_losing = [
        {k: v for k, v in l.items() if not k.startswith("_")}
        for l in losing
    ]
    clean_gaining = [
        {k: v for k, v in g.items() if not k.startswith("_")}
        for g in gaining
    ]

    flow = {
        "category": category,
        "losing_protocols": clean_losing,
        "gaining_protocols": clean_gaining,
        "migration_score": score,
        "migration_detected": detected,
        "likely_trigger": trigger,
    }

    return flow, skipped


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Detect liquidity migrations across DeFi protocol categories.

    protocols: list of {
        "name": str,
        "category": str,
        "tvl_history": list[float],  # oldest first, weekly
        "apy_current": float,
        "apy_7d_ago": float
    }
    config: {
        "migration_threshold_pct": float,  # default 10.0
        "min_history": int                 # default 4
    }

    Returns migration analysis dict.
    """
    cfg = _merge_config(config)
    migration_threshold_pct = float(cfg.get("migration_threshold_pct", 10.0))
    min_history = int(cfg.get("min_history", 4))

    if not protocols:
        result = {
            "flows": [],
            "active_migrations": 0,
            "total_capital_moving_usd": 0.0,
            "skipped_protocols": [],
            "timestamp": time.time(),
        }
        _append_log(result)
        return result

    # Group by category
    categories: dict = {}
    for p in protocols:
        cat = p.get("category", "unknown")
        categories.setdefault(cat, []).append(p)

    flows = []
    all_skipped = []

    for category, cat_protocols in categories.items():
        flow, skipped = _process_category(
            category, cat_protocols, migration_threshold_pct, min_history
        )
        all_skipped.extend(skipped)
        if flow is not None:
            flows.append(flow)

    active_migrations = sum(1 for f in flows if f["migration_detected"])
    total_capital_moving_usd = sum(
        l["estimated_outflow_usd"]
        for f in flows
        for l in f["losing_protocols"]
    )

    result = {
        "flows": flows,
        "active_migrations": active_migrations,
        "total_capital_moving_usd": total_capital_moving_usd,
        "skipped_protocols": all_skipped,
        "timestamp": time.time(),
    }

    _append_log(result)
    return result


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer, atomic)
# ---------------------------------------------------------------------------

def _append_log(entry: dict) -> None:
    """Append entry to DATA_FILE, capped at MAX_ENTRIES. Atomic write."""
    data_path = DATA_FILE
    try:
        if data_path.exists():
            with open(data_path, "r") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        else:
            data_path.parent.mkdir(parents=True, exist_ok=True)
            log = []
    except Exception:
        log = []

    log.append(entry)
    if len(log) > MAX_ENTRIES:
        log = log[-MAX_ENTRIES:]

    tmp = str(data_path) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(log, f, indent=2)
    os.replace(tmp, data_path)


def init_log() -> None:
    """Initialize data/liquidity_migration_log.json as [] if absent."""
    if not DATA_FILE.exists():
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(DATA_FILE) + ".tmp"
        with open(tmp, "w") as f:
            json.dump([], f)
        os.replace(tmp, DATA_FILE)
