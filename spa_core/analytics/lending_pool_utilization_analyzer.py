"""
MP-836 LendingPoolUtilizationAnalyzer
Advisory-only analytics module.
Analyzes lending-pool utilization, the kinked interest-rate model, and
withdrawal-liquidity risk (Aave/Compound-style). Identifies pools that are
over-utilized (rate-spike / illiquid) or underutilized (capital-inefficient).

Data log: data/lending_pool_utilization_log.json (ring-buffer 100 entries).
Pure stdlib, read-only advisory, atomic writes.
"""

import json
import os
import time
import math
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

_LOG_RING_SIZE = 100

_DEFAULT_OPTIMAL_UTILIZATION = 0.80
_DEFAULT_BASE_RATE = 0.0
_DEFAULT_SLOPE1 = 0.04
_DEFAULT_SLOPE2 = 0.75
_DEFAULT_RESERVE_FACTOR = 0.10
_DEFAULT_MIN_LIQUIDITY_RATIO = 0.05

# Regime / liquidity thresholds.
_UNDERUTILIZED_MAX = 0.40
_HIGH_MAX = 0.95
_TIGHT_LIQUIDITY = 0.15

# ---------------------------------------------------------------------------
# Per-pool computation helpers
# ---------------------------------------------------------------------------


def _utilization(total_supplied: float, total_borrowed: float) -> float:
    """utilization = borrowed / supplied. Guards supplied <= 0 -> 0.0."""
    supplied = float(total_supplied) if total_supplied is not None else 0.0
    borrowed = float(total_borrowed) if total_borrowed is not None else 0.0
    if supplied <= 0:
        return 0.0
    u = borrowed / supplied
    if u < 0:
        return 0.0
    return u


def _borrow_rate(u: float, base_rate: float, slope1: float, slope2: float,
                 optimal: float) -> float:
    """
    Kinked interest-rate model.
      if u <= optimal:  base + (u/optimal) * slope1
      else:             base + slope1 + ((u-optimal)/(1-optimal)) * slope2
    Guards optimal in (0, 1); falls back to a linear model otherwise.
    """
    base = float(base_rate)
    s1 = float(slope1)
    s2 = float(slope2)
    opt = float(optimal)
    u = float(u)

    if not (0.0 < opt < 1.0):
        # Degenerate kink point — treat whole curve as a single slope.
        return max(0.0, base + u * s1)

    if u <= opt:
        rate = base + (u / opt) * s1
    else:
        denom = 1.0 - opt
        if denom <= 0:
            rate = base + s1 + s2
        else:
            rate = base + s1 + ((u - opt) / denom) * s2
    return max(0.0, rate)


def _supply_rate(borrow_rate: float, u: float, reserve_factor: float) -> float:
    """supply_rate = borrow_rate * u * (1 - reserve_factor). Guards reserve."""
    rf = float(reserve_factor)
    if rf < 0:
        rf = 0.0
    if rf > 1:
        rf = 1.0
    rate = float(borrow_rate) * float(u) * (1.0 - rf)
    return max(0.0, rate)


def _regime(u: float, optimal: float) -> str:
    """
    UNDERUTILIZED (u < 0.40), OPTIMAL (0.40 <= u <= optimal),
    HIGH (optimal < u <= 0.95), CRITICAL (u > 0.95).
    """
    u = float(u)
    opt = float(optimal)
    if u < _UNDERUTILIZED_MAX:
        return "UNDERUTILIZED"
    if u <= opt:
        return "OPTIMAL"
    if u <= _HIGH_MAX:
        return "HIGH"
    return "CRITICAL"


def _liquidity_risk(liquidity_ratio: float, min_liquidity_ratio: float) -> str:
    """
    ILLIQUID (ratio < min_liquidity_ratio), TIGHT (< 0.15), HEALTHY (else).
    """
    lr = float(liquidity_ratio)
    floor = float(min_liquidity_ratio)
    if lr < floor:
        return "ILLIQUID"
    if lr < _TIGHT_LIQUIDITY:
        return "TIGHT"
    return "HEALTHY"


def _health_score(u: float, optimal: float, liquidity_ratio: float,
                  min_liquidity_ratio: float) -> float:
    """
    Health score in [0, 100]. Rewards utilization near optimal and penalizes
    distance from it plus thin liquidity.

      utilization_component (0-70): peaks when u == optimal, declines linearly
        on either side.
      liquidity_component (0-30): scales the available-liquidity ratio,
        zeroed below the minimum-liquidity floor.
    """
    u = float(u)
    opt = float(optimal)
    lr = float(liquidity_ratio)
    floor = float(min_liquidity_ratio)

    # Utilization component.
    if not (0.0 < opt < 1.0):
        util_component = 35.0
    elif u <= opt:
        # Linear ramp 0 -> 70 as u goes 0 -> optimal.
        util_component = 70.0 * (u / opt)
    else:
        # Decline from 70 toward 0 as u goes optimal -> 1.0.
        denom = 1.0 - opt
        if denom <= 0:
            util_component = 0.0
        else:
            over = (u - opt) / denom
            util_component = 70.0 * max(0.0, 1.0 - over)

    # Liquidity component.
    if lr < floor:
        liq_component = 0.0
    else:
        # Scale ratio into 0-30, saturating at a comfortable 0.30 ratio.
        liq_component = 30.0 * min(1.0, lr / 0.30)

    score = util_component + liq_component
    return max(0.0, min(100.0, score))


def _grade(health_score: float) -> str:
    """Grade A-F from a 0-100 health score (higher is healthier)."""
    s = float(health_score)
    if s >= 85:
        return "A"
    if s >= 70:
        return "B"
    if s >= 50:
        return "C"
    if s >= 30:
        return "D"
    return "F"


def _flags(u: float, optimal: float, liquidity_ratio: float,
           min_liquidity_ratio: float, supplied: float) -> list:
    """
    Build risk flags:
      ZERO_SUPPLY        supplied <= 0
      ILLIQUID           liquidity_ratio < min_liquidity_ratio
      OVER_KINK          u > optimal
      RATE_SPIKE_RISK    u > 0.95
      UNDERUTILIZED      u < 0.40
    """
    flags = []
    if supplied is None or float(supplied) <= 0:
        flags.append("ZERO_SUPPLY")
    if float(liquidity_ratio) < float(min_liquidity_ratio):
        flags.append("ILLIQUID")
    if float(u) > float(optimal):
        flags.append("OVER_KINK")
    if float(u) > _HIGH_MAX:
        flags.append("RATE_SPIKE_RISK")
    if float(u) < _UNDERUTILIZED_MAX:
        flags.append("UNDERUTILIZED")
    return flags


def _recommendations(regime: str, liquidity_risk: str, flags: list) -> list:
    """Human-readable advisory strings driven by regime / liquidity / flags."""
    flags = flags or []
    recs = []
    if regime == "OPTIMAL":
        recs.append("Good supply target — utilization near the optimal kink")
    elif regime == "UNDERUTILIZED":
        recs.append("Capital underutilized — supply yield is muted, consider redeploying")
    elif regime == "HIGH":
        recs.append("Utilization above the kink — borrow rates climbing, monitor closely")
    elif regime == "CRITICAL":
        recs.append("Utilization critical — withdrawals may be blocked, reduce exposure")

    if liquidity_risk == "ILLIQUID":
        recs.append("Withdrawal may face slippage — limited liquidity available")
    elif liquidity_risk == "TIGHT":
        recs.append("Liquidity is tight — large withdrawals could be delayed")

    if "ZERO_SUPPLY" in flags:
        recs.append("Pool has no supplied liquidity — data may be stale or pool inactive")
    if "RATE_SPIKE_RISK" in flags:
        recs.append("Borrow rate near the steep slope — interest costs can spike sharply")
    return recs


# ---------------------------------------------------------------------------
# Config resolution helper
# ---------------------------------------------------------------------------


def _resolve(pool: dict, cfg: dict, key: str, default):
    """Resolve a parameter: pool value, then global config, then default."""
    if key in pool and pool[key] is not None:
        return pool[key]
    if key in cfg and cfg[key] is not None:
        return cfg[key]
    return default


# ---------------------------------------------------------------------------
# Core analyze function
# ---------------------------------------------------------------------------


def analyze(pools: list, config: dict = None) -> dict:
    """
    Analyze lending-pool utilization, rates, and liquidity risk.

    Parameters
    ----------
    pools : list[dict]
        Each dict: name, total_supplied, total_borrowed, optimal_utilization,
        base_rate, slope1, slope2, reserve_factor.
    config : dict | None
        Global defaults for the same keys plus min_liquidity_ratio (0.05).

    Returns
    -------
    dict with pools (scored list), average_utilization,
    highest_borrow_rate_pool, most_illiquid_pool, critical_count, timestamp.
    """
    cfg = config or {}
    min_liq = float(cfg.get("min_liquidity_ratio", _DEFAULT_MIN_LIQUIDITY_RATIO))

    scored = []

    for pool in pools:
        name = str(pool.get("name", ""))
        supplied = float(pool.get("total_supplied", 0.0) or 0.0)
        borrowed = float(pool.get("total_borrowed", 0.0) or 0.0)

        optimal = float(_resolve(pool, cfg, "optimal_utilization", _DEFAULT_OPTIMAL_UTILIZATION))
        base_rate = float(_resolve(pool, cfg, "base_rate", _DEFAULT_BASE_RATE))
        slope1 = float(_resolve(pool, cfg, "slope1", _DEFAULT_SLOPE1))
        slope2 = float(_resolve(pool, cfg, "slope2", _DEFAULT_SLOPE2))
        reserve_factor = float(_resolve(pool, cfg, "reserve_factor", _DEFAULT_RESERVE_FACTOR))

        u = _utilization(supplied, borrowed)
        available_liquidity = max(0.0, supplied - borrowed)
        if supplied > 0:
            liquidity_ratio = available_liquidity / supplied
        else:
            liquidity_ratio = 0.0

        borrow_rate = _borrow_rate(u, base_rate, slope1, slope2, optimal)
        supply_rate = _supply_rate(borrow_rate, u, reserve_factor)
        regime = _regime(u, optimal)
        liq_risk = _liquidity_risk(liquidity_ratio, min_liq)
        health = _health_score(u, optimal, liquidity_ratio, min_liq)
        grade = _grade(health)
        flags = _flags(u, optimal, liquidity_ratio, min_liq, supplied)
        recs = _recommendations(regime, liq_risk, flags)

        scored.append({
            "name": name,
            "utilization": u,
            "borrow_rate": borrow_rate,
            "supply_rate": supply_rate,
            "available_liquidity": available_liquidity,
            "liquidity_ratio": liquidity_ratio,
            "regime": regime,
            "liquidity_risk": liq_risk,
            "health_score": health,
            "grade": grade,
            "flags": flags,
            "recommendations": recs,
        })

    # Summary.
    if scored:
        average_utilization = sum(p["utilization"] for p in scored) / len(scored)
        highest_borrow_rate_pool = max(scored, key=lambda p: p["borrow_rate"])["name"]
        most_illiquid_pool = min(scored, key=lambda p: p["liquidity_ratio"])["name"]
        critical_count = sum(1 for p in scored if p["regime"] == "CRITICAL")
    else:
        average_utilization = 0.0
        highest_borrow_rate_pool = None
        most_illiquid_pool = None
        critical_count = 0

    return {
        "pools": scored,
        "average_utilization": average_utilization,
        "highest_borrow_rate_pool": highest_borrow_rate_pool,
        "most_illiquid_pool": most_illiquid_pool,
        "critical_count": critical_count,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Log persistence (ring-buffer 100)
# ---------------------------------------------------------------------------


def log_result(result: dict, data_dir: str = "data") -> None:
    """Atomically append result snapshot to ring-buffer log (max 100 entries)."""
    log_path = os.path.join(data_dir, "lending_pool_utilization_log.json")

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log = json.load(fh)
        if not isinstance(log, list):
            log = []
    except (FileNotFoundError, json.JSONDecodeError):
        log = []

    snapshot = {
        "timestamp": result["timestamp"],
        "pool_count": len(result["pools"]),
        "average_utilization": result["average_utilization"],
        "critical_count": result["critical_count"],
        "highest_borrow_rate_pool": result["highest_borrow_rate_pool"],
        "most_illiquid_pool": result["most_illiquid_pool"],
    }
    log.append(snapshot)

    if len(log) > _LOG_RING_SIZE:
        log = log[-_LOG_RING_SIZE:]

    os.makedirs(data_dir, exist_ok=True)
    atomic_save(log, str(log_path))
# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

_SAMPLE_POOLS = [
    {
        "name": "Aave-USDC",
        "total_supplied": 100_000_000.0,
        "total_borrowed": 80_000_000.0,
        "optimal_utilization": 0.80,
        "base_rate": 0.0,
        "slope1": 0.04,
        "slope2": 0.75,
        "reserve_factor": 0.10,
    },
    {
        "name": "Compound-DAI",
        "total_supplied": 50_000_000.0,
        "total_borrowed": 49_000_000.0,
        "optimal_utilization": 0.80,
        "base_rate": 0.0,
        "slope1": 0.04,
        "slope2": 0.75,
        "reserve_factor": 0.15,
    },
    {
        "name": "SmallPool-USDT",
        "total_supplied": 10_000_000.0,
        "total_borrowed": 2_000_000.0,
        "optimal_utilization": 0.80,
        "base_rate": 0.01,
        "slope1": 0.04,
        "slope2": 0.75,
        "reserve_factor": 0.10,
    },
]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-836 LendingPoolUtilizationAnalyzer")
    parser.add_argument("--check", action="store_true",
                        help="Compute and print, no write (default)")
    parser.add_argument("--run", action="store_true",
                        help="Compute, print, and write log")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    args = parser.parse_args()

    result = analyze(_SAMPLE_POOLS)

    print(f"Pools analyzed    : {len(result['pools'])}")
    print(f"Avg utilization   : {result['average_utilization']:.2%}")
    print(f"Critical count    : {result['critical_count']}")
    print(f"Highest borrow rt : {result['highest_borrow_rate_pool']}")
    print(f"Most illiquid     : {result['most_illiquid_pool']}")
    for p in result["pools"]:
        print(f"  {p['name']:18s} u={p['utilization']:6.2%}  "
              f"borrow={p['borrow_rate']:6.2%}  supply={p['supply_rate']:6.2%}  "
              f"{p['regime']:13s} {p['liquidity_risk']:8s} grade={p['grade']}")

    if args.run:
        log_result(result, data_dir=args.data_dir)
        print(f"Log written to    : {args.data_dir}/lending_pool_utilization_log.json")
