"""
MP-828 CrossProtocolYieldOptimizer
Advisory-only analytics. Pure stdlib, no external deps.
Greedy risk-adjusted ranking with capacity/position caps.
Logs to data/yield_optimization_log.json (ring-buffer 100, atomic writes).
"""

import json
import os
import time
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.normpath(os.path.join(_MODULE_DIR, "..", ".."))

LOG_PATH = os.path.join(_PROJECT_ROOT, "data", "yield_optimization_log.json")
LOG_RING_SIZE = 100

_DEFAULT_CONSTRAINTS = {
    "max_positions": 5,
    "min_allocation_usd": 500.0,
    "max_risk_score": 70,
    "min_apy": 0.0,
    "max_single_position_pct": 40.0,
}


# ---------------------------------------------------------------------------
# Atomic I/O helpers
# ---------------------------------------------------------------------------

def _atomic_write(path, obj):
    """Write JSON atomically via tmp + os.replace."""
    dir_ = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_, exist_ok=True)
    atomic_save(obj, str(path))
def _load_log(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _append_log(path, entry):
    log = _load_log(path)
    log.append(entry)
    if len(log) > LOG_RING_SIZE:
        log = log[-LOG_RING_SIZE:]
    _atomic_write(path, log)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(capital_usd, opportunities, constraints=None):
    """
    Find optimal capital allocation across protocols to maximise
    risk-adjusted yield within constraints.

    Parameters
    ----------
    capital_usd : float
    opportunities : list of dict
        Each: {protocol, apy, risk_score, min_deposit_usd, max_capacity_usd}
        max_capacity_usd may be None (= unlimited)
    constraints : dict, optional
        {max_positions, min_allocation_usd, max_risk_score,
         min_apy, max_single_position_pct}

    Returns
    -------
    dict
        {capital_usd, total_opportunities, filtered_opportunities,
         allocation, unallocated_usd, expected_total_annual_yield_usd,
         blended_apy, blended_risk_adjusted_apy, portfolio_risk_score,
         optimization_method, timestamp}
    """
    capital = float(capital_usd)
    total_opps = len(opportunities) if opportunities else 0

    cfg = dict(_DEFAULT_CONSTRAINTS)
    if constraints:
        cfg.update(constraints)

    max_positions = max(1, int(cfg.get("max_positions", 5)))
    min_alloc = float(cfg.get("min_allocation_usd", 500.0))
    max_risk = int(cfg.get("max_risk_score", 70))
    min_apy = float(cfg.get("min_apy", 0.0))
    max_single_pct = float(cfg.get("max_single_position_pct", 40.0))

    # ---- Zero-capital edge case ----
    if capital <= 0 or not opportunities:
        result = _zero_result(capital, total_opps, 0)
        _append_log(LOG_PATH, result)
        return result

    # ---- Step 1: Filter ----
    # min_deposit <= capital / max_positions
    deposit_threshold = capital / max_positions

    filtered = []
    for opp in opportunities:
        risk = int(opp.get("risk_score", 0))
        apy = float(opp.get("apy", 0.0))
        min_dep = float(opp.get("min_deposit_usd", 0.0))

        if risk > max_risk:
            continue
        if apy < min_apy:
            continue
        if min_dep > deposit_threshold:
            continue
        filtered.append(dict(opp))  # shallow copy so we can annotate

    filtered_count = len(filtered)

    if not filtered:
        result = _zero_result(capital, total_opps, 0)
        result["filtered_opportunities"] = 0
        _append_log(LOG_PATH, result)
        return result

    # ---- Step 2: Compute risk_adjusted_apy and sort descending ----
    for opp in filtered:
        risk = int(opp.get("risk_score", 0))
        apy = float(opp.get("apy", 0.0))
        opp["_ra_apy"] = apy * (1.0 - risk / 100.0)

    filtered.sort(key=lambda x: x["_ra_apy"], reverse=True)

    # ---- Step 3: Take top max_positions ----
    selected = filtered[:max_positions]
    n = len(selected)

    # ---- Step 4: Initial allocation with caps ----
    base = capital / n
    max_pct_cap = capital * max_single_pct / 100.0

    allocs = []
    excess = 0.0
    uncapped_indices = []

    for i, opp in enumerate(selected):
        cap_cap = opp.get("max_capacity_usd")
        eff_cap = min(
            float(cap_cap) if cap_cap is not None else float("inf"),
            max_pct_cap,
        )
        alloc = min(base, eff_cap)
        if alloc < base - 1e-9:          # was capped
            excess += base - alloc
        else:
            uncapped_indices.append(i)
        allocs.append(alloc)

    # ---- Step 5: One-pass redistribution of excess to uncapped ----
    if uncapped_indices and excess > 1e-9:
        extra = excess / len(uncapped_indices)
        for i in uncapped_indices:
            opp = selected[i]
            cap_cap = opp.get("max_capacity_usd")
            eff_cap = min(
                float(cap_cap) if cap_cap is not None else float("inf"),
                max_pct_cap,
            )
            allocs[i] = min(allocs[i] + extra, eff_cap)

    # ---- Step 6: Build allocation list, skip if below min_alloc ----
    allocation = []
    total_allocated = 0.0

    for i, opp in enumerate(selected):
        alloc = allocs[i]
        if alloc < min_alloc:
            continue

        apy = float(opp.get("apy", 0.0))
        risk = int(opp.get("risk_score", 0))
        ra_apy = apy * (1.0 - risk / 100.0)
        exp_yield = alloc * apy / 100.0

        allocation.append({
            "protocol": str(opp.get("protocol", "")),
            "allocated_usd": round(alloc, 6),
            "allocation_pct": 0.0,   # filled below
            "apy": apy,
            "risk_score": risk,
            "expected_annual_yield_usd": round(exp_yield, 6),
            "risk_adjusted_apy": round(ra_apy, 6),
        })
        total_allocated += alloc

    # Fill allocation_pct
    for item in allocation:
        item["allocation_pct"] = (
            round(item["allocated_usd"] / capital * 100.0, 4)
            if capital > 0
            else 0.0
        )

    unallocated = capital - total_allocated

    # ---- Blended metrics ----
    if total_allocated > 0 and allocation:
        exp_total_yield = sum(
            item["expected_annual_yield_usd"] for item in allocation
        )
        blended_apy = exp_total_yield / capital * 100.0
        blended_ra_apy = sum(
            item["allocated_usd"] / capital * item["risk_adjusted_apy"]
            for item in allocation
        )
        port_risk = sum(
            item["allocated_usd"] / total_allocated * item["risk_score"]
            for item in allocation
        )
    else:
        exp_total_yield = 0.0
        blended_apy = 0.0
        blended_ra_apy = 0.0
        port_risk = 0.0

    result = {
        "capital_usd": capital,
        "total_opportunities": total_opps,
        "filtered_opportunities": filtered_count,
        "allocation": allocation,
        "unallocated_usd": round(unallocated, 6),
        "expected_total_annual_yield_usd": round(exp_total_yield, 6),
        "blended_apy": round(blended_apy, 6),
        "blended_risk_adjusted_apy": round(blended_ra_apy, 6),
        "portfolio_risk_score": round(port_risk, 4),
        "optimization_method": "risk_adjusted_ranking",
        "timestamp": time.time(),
    }

    _append_log(LOG_PATH, result)
    return result


def _zero_result(capital, total_opps, filtered_count):
    return {
        "capital_usd": capital,
        "total_opportunities": total_opps,
        "filtered_opportunities": filtered_count,
        "allocation": [],
        "unallocated_usd": round(capital, 6),
        "expected_total_annual_yield_usd": 0.0,
        "blended_apy": 0.0,
        "blended_risk_adjusted_apy": 0.0,
        "portfolio_risk_score": 0.0,
        "optimization_method": "risk_adjusted_ranking",
        "timestamp": time.time(),
    }
