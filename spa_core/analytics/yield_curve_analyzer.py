"""
MP-805 YieldCurveAnalyzer
=========================
Analyzes the yield curve across different durations (short/medium/long) for
DeFi lending markets, detects inversions, and identifies optimal duration for
deployment.

Data file: data/yield_curve_log.json  (ring-buffer, max 100 entries)
Advisory / read-only — never touches allocator, risk, or execution domains.
Pure stdlib only.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_SHORT_MAX_DAYS: int = 30
DEFAULT_MEDIUM_MAX_DAYS: int = 180
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "yield_curve_log.json"
)
_LOG_CAP = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _classify_curve_shape(rates: list[dict]) -> str:
    """
    Classify the curve shape for a single protocol.

    Expects `rates` sorted by duration_days ascending, each entry having
    "supply_rate" and "duration_days" keys.

    Rules:
    - < 2 points → FLAT
    - range of supply_rate < 0.5 → FLAT
    - If mid-point supply rate is the highest (humped) → HUMPED
    - last > first + 0.5 → NORMAL
    - first > last + 0.5 → INVERTED
    - Otherwise → FLAT
    """
    if len(rates) < 2:
        return "FLAT"

    supply_rates = [r["supply_rate"] for r in rates]
    first = supply_rates[0]
    last = supply_rates[-1]
    rate_range = max(supply_rates) - min(supply_rates)

    if rate_range < 0.5:
        return "FLAT"

    # Check humped: middle point is the maximum
    if len(supply_rates) >= 3:
        max_val = max(supply_rates)
        max_idx = supply_rates.index(max_val)
        if 0 < max_idx < len(supply_rates) - 1:
            return "HUMPED"

    if last > first + 0.5:
        return "NORMAL"
    if first > last + 0.5:
        return "INVERTED"
    return "FLAT"


def _market_shape(shapes: list[str]) -> str:
    """Majority vote across protocol shapes; tie → MIXED."""
    if not shapes:
        return "FLAT"
    counts = Counter(shapes)
    top_count = max(counts.values())
    winners = [s for s, c in counts.items() if c == top_count]
    if len(winners) == 1:
        return winners[0]
    return "MIXED"


def _safe_avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(rate_data: list[dict], config: dict | None = None) -> dict:
    """
    Analyze the DeFi yield curve across protocols and durations.

    Parameters
    ----------
    rate_data : list[dict]
        Each element: {
            "duration_days": int,
            "protocol": str,
            "borrow_rate": float,   # annual %
            "supply_rate": float    # annual %
        }
    config : dict, optional
        {
            "short_max_days": int,   # default 30
            "medium_max_days": int   # default 180
        }

    Returns
    -------
    dict
        Full analysis result (see module docstring for schema).
    """
    cfg = config or {}
    short_max = int(cfg.get("short_max_days", DEFAULT_SHORT_MAX_DAYS))
    medium_max = int(cfg.get("medium_max_days", DEFAULT_MEDIUM_MAX_DAYS))

    # Group by protocol
    proto_map: dict[str, list[dict]] = {}
    for row in rate_data:
        proto = row["protocol"]
        proto_map.setdefault(proto, []).append(row)

    protocols_out: dict[str, dict] = {}
    protocol_shapes: list[str] = []

    for proto, rows in proto_map.items():
        # Sort by duration ascending
        sorted_rows = sorted(rows, key=lambda r: r["duration_days"])

        rates_list = []
        for r in sorted_rows:
            spread = r["borrow_rate"] - r["supply_rate"]
            rates_list.append({
                "duration_days": r["duration_days"],
                "borrow_rate": r["borrow_rate"],
                "supply_rate": r["supply_rate"],
                "spread": round(spread, 6),
            })

        shape = _classify_curve_shape(rates_list)
        protocol_shapes.append(shape)

        supply_vals = [r["supply_rate"] for r in rates_list]
        max_supply = max(supply_vals) if supply_vals else 0.0
        optimal_dur = sorted_rows[supply_vals.index(max_supply)]["duration_days"] if supply_vals else 0

        short_supplies = [
            r["supply_rate"] for r in rates_list if r["duration_days"] <= short_max
        ]
        long_supplies = [
            r["supply_rate"] for r in rates_list if r["duration_days"] > medium_max
        ]

        protocols_out[proto] = {
            "rates": rates_list,
            "curve_shape": shape,
            "max_supply_rate": round(max_supply, 6),
            "optimal_duration_days": optimal_dur,
            "short_term_avg_supply": round(_safe_avg(short_supplies), 6),
            "long_term_avg_supply": round(_safe_avg(long_supplies), 6),
        }

    # Cross-protocol aggregations
    best_short: dict[str, Any] = {"protocol": "", "rate": -1.0, "duration_days": 0}
    best_long: dict[str, Any] = {"protocol": "", "rate": -1.0, "duration_days": 0}
    highest_spread: dict[str, Any] = {"protocol": "", "spread": -1.0, "duration_days": 0}

    for proto, rows in proto_map.items():
        for r in rows:
            supply = r["supply_rate"]
            dur = r["duration_days"]
            spread = r["borrow_rate"] - r["supply_rate"]

            if dur <= short_max and supply > best_short["rate"]:
                best_short = {"protocol": proto, "rate": round(supply, 6), "duration_days": dur}

            if dur > medium_max and supply > best_long["rate"]:
                best_long = {"protocol": proto, "rate": round(supply, 6), "duration_days": dur}

            if spread > highest_spread["spread"]:
                highest_spread = {"protocol": proto, "spread": round(spread, 6), "duration_days": dur}

    # Fallback: if no short/long entries found, find globally
    if best_short["protocol"] == "" and rate_data:
        short_candidates = sorted(rate_data, key=lambda r: (r["supply_rate"],), reverse=True)
        if short_candidates:
            r = short_candidates[0]
            best_short = {
                "protocol": r["protocol"],
                "rate": round(r["supply_rate"], 6),
                "duration_days": r["duration_days"],
            }
    if best_long["protocol"] == "" and rate_data:
        long_candidates = sorted(rate_data, key=lambda r: (r["supply_rate"],), reverse=True)
        if long_candidates:
            r = long_candidates[0]
            best_long = {
                "protocol": r["protocol"],
                "rate": round(r["supply_rate"], 6),
                "duration_days": r["duration_days"],
            }

    result = {
        "protocols": protocols_out,
        "cross_protocol": {
            "best_short_term": best_short,
            "best_long_term": best_long,
            "highest_spread_opportunity": highest_spread,
        },
        "market_shape": _market_shape(protocol_shapes),
        "timestamp": time.time(),
    }

    _append_log(result)
    return result


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _append_log(entry: dict) -> None:
    """Append result to ring-buffer log (max _LOG_CAP entries). Atomic write."""
    log_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "yield_curve_log.json")
    )
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log: list = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    log.append(entry)
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]

    tmp = log_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2)
    os.replace(tmp, log_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _demo() -> None:  # pragma: no cover
    sample = [
        {"duration_days": 1,   "protocol": "Aave",     "borrow_rate": 5.0,  "supply_rate": 3.2},
        {"duration_days": 7,   "protocol": "Aave",     "borrow_rate": 5.5,  "supply_rate": 3.5},
        {"duration_days": 30,  "protocol": "Aave",     "borrow_rate": 6.0,  "supply_rate": 4.0},
        {"duration_days": 90,  "protocol": "Aave",     "borrow_rate": 6.2,  "supply_rate": 4.5},
        {"duration_days": 180, "protocol": "Aave",     "borrow_rate": 6.5,  "supply_rate": 4.8},
        {"duration_days": 365, "protocol": "Aave",     "borrow_rate": 7.0,  "supply_rate": 5.2},
        {"duration_days": 1,   "protocol": "Compound", "borrow_rate": 4.8,  "supply_rate": 4.5},
        {"duration_days": 30,  "protocol": "Compound", "borrow_rate": 4.5,  "supply_rate": 4.2},
        {"duration_days": 365, "protocol": "Compound", "borrow_rate": 4.0,  "supply_rate": 3.8},
    ]
    import json as _json
    print(_json.dumps(analyze(sample), indent=2))


if __name__ == "__main__":  # pragma: no cover
    _demo()
