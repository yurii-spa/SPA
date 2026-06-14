"""
MP-1110: DeFiProtocolLendingUtilizationElasticityAnalyzer
Analyzes how sensitive DeFi lending protocol borrow/supply rates are to changes
in utilization ratio. Detects kink proximity, cliff risk, and models rate
trajectories under deposit/withdrawal shocks.
Pure stdlib, read-only/advisory, atomic ring-buffer log.
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "utilization_elasticity_log.json"
)
LOG_CAP = 100

# Kink proximity thresholds
KINK_PROXIMITY_WARNING  = 0.05   # within 5pp of kink → WARNING
KINK_PROXIMITY_CRITICAL = 0.02   # within 2pp of kink → CRITICAL

# Elasticity rating thresholds (dRate/dUtil; higher = more elastic / risky)
ELASTICITY_HIGH    = 5.0    # >5 pp rate change per 1pp util change
ELASTICITY_MEDIUM  = 2.0

# Utilization thresholds for labels
UTIL_CRITICAL = 0.95
UTIL_HIGH     = 0.80
UTIL_MODERATE = 0.60


# ── helpers ───────────────────────────────────────────────────────────────────

def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _borrow_rate_at_util(
    util: float,
    base_rate: float,
    slope1: float,
    slope2: float,
    kink: float,
) -> float:
    """
    Compound/Aave two-slope interest rate model.
    All rates in decimal (0–1).
    """
    util = _clamp(util, 0.0, 1.0)
    if util <= kink:
        return base_rate + util * slope1
    else:
        return base_rate + kink * slope1 + (util - kink) * slope2


def _supply_apy_from_borrow(
    util: float,
    borrow_rate: float,
    reserve_factor: float,
) -> float:
    """Supply APY = borrow_rate * util * (1 - reserve_factor)."""
    return borrow_rate * _clamp(util, 0.0, 1.0) * (1.0 - _clamp(reserve_factor, 0.0, 1.0))


def _rate_elasticity(
    util: float,
    slope1: float,
    slope2: float,
    kink: float,
    delta: float = 0.01,
) -> float:
    """
    Numerical elasticity: Δrate / Δutil at the given utilization point.
    Uses forward difference with delta=1pp.
    """
    r0 = _borrow_rate_at_util(util, 0.0, slope1, slope2, kink)
    r1 = _borrow_rate_at_util(
        _clamp(util + delta, 0.0, 1.0), 0.0, slope1, slope2, kink
    )
    return (r1 - r0) / delta


def _utilization_label(util: float) -> str:
    if util >= UTIL_CRITICAL:
        return "CRITICAL"
    if util >= UTIL_HIGH:
        return "HIGH"
    if util >= UTIL_MODERATE:
        return "MODERATE"
    return "LOW"


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolLendingUtilizationElasticityAnalyzer:
    """
    Analyzes DeFi lending protocol rate elasticity with respect to utilization.

    Input protocol dict keys:
        name                : str
        category            : str      ("lending", "cdp")
        current_utilization : float    (0–1, fraction of supplied capital borrowed)
        base_rate           : float    (min borrow rate, decimal, e.g. 0.02 = 2%)
        slope1              : float    (rate slope below kink, decimal per util unit)
        slope2              : float    (rate slope above kink — steeper)
        kink                : float    (utilization kink point, 0–1, e.g. 0.80)
        reserve_factor      : float    (fraction of borrow interest kept as reserve)
        total_supply_usd    : float    (total deposited capital)
        total_borrow_usd    : float    (total outstanding borrows)
        shock_scenarios     : list[float]  (optional utilization delta scenarios)
    """

    def analyze(
        self,
        protocols: List[dict],
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        results = [self._analyze_protocol(p) for p in protocols]
        agg = self._aggregate(results)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"protocols": results, "aggregate": agg}

    # ── per-protocol ──────────────────────────────────────────────────────────

    def _analyze_protocol(self, p: dict) -> dict:
        name     = p.get("name", "unknown")
        category = p.get("category", "lending")

        util   = _clamp(float(p.get("current_utilization", 0.0)), 0.0, 1.0)
        base   = float(p.get("base_rate", 0.02))
        s1     = float(p.get("slope1", 0.04))
        s2     = float(p.get("slope2", 3.0))
        kink   = _clamp(float(p.get("kink", 0.80)), 0.0, 1.0)
        rf     = _clamp(float(p.get("reserve_factor", 0.10)), 0.0, 1.0)
        supply = float(p.get("total_supply_usd", 0.0))
        borrow = float(p.get("total_borrow_usd", 0.0))

        # Current rates
        current_borrow_rate = _borrow_rate_at_util(util, base, s1, s2, kink)
        current_supply_apy  = _supply_apy_from_borrow(util, current_borrow_rate, rf)

        # Rate at kink
        kink_borrow_rate    = _borrow_rate_at_util(kink, base, s1, s2, kink)

        # Elasticity at current util
        elasticity = _rate_elasticity(util, s1, s2, kink)

        # Kink proximity (signed distance; negative = below kink)
        kink_distance = kink - util   # positive = below kink, negative = above

        # Shock scenarios
        default_shocks = p.get("shock_scenarios", [-0.10, -0.05, +0.05, +0.10])
        shock_results  = self._shock_scenarios(
            util, base, s1, s2, kink, rf, supply, borrow, default_shocks
        )

        # Cliff delta: borrow-rate jump if util moves from (kink−ε) to (kink+ε)
        cliff_borrow_rate_below = _borrow_rate_at_util(kink - 0.001, base, s1, s2, kink)
        cliff_borrow_rate_above = _borrow_rate_at_util(kink + 0.001, base, s1, s2, kink)
        cliff_delta_pct = (cliff_borrow_rate_above - cliff_borrow_rate_below) * 100.0

        flags = self._flags(
            util, kink, kink_distance, elasticity, current_borrow_rate, cliff_delta_pct
        )

        util_label = _utilization_label(util)

        return {
            "name":                     name,
            "category":                 category,
            "current_utilization_pct":  round(util * 100.0, 2),
            "utilization_label":        util_label,
            "kink_utilization_pct":     round(kink * 100.0, 2),
            "kink_distance_pp":         round(kink_distance * 100.0, 2),
            "current_borrow_rate_pct":  round(current_borrow_rate * 100.0, 4),
            "current_supply_apy_pct":   round(current_supply_apy * 100.0, 4),
            "kink_borrow_rate_pct":     round(kink_borrow_rate * 100.0, 4),
            "cliff_delta_pct":          round(cliff_delta_pct, 4),
            "rate_elasticity_pp_per_pp": round(elasticity * 100.0, 4),
            "shock_scenarios":          shock_results,
            "flags":                    flags,
        }

    # ── shock scenarios ───────────────────────────────────────────────────────

    def _shock_scenarios(
        self,
        util: float,
        base: float,
        s1: float,
        s2: float,
        kink: float,
        rf: float,
        supply: float,
        borrow: float,
        shocks: List[float],
    ) -> List[dict]:
        results = []
        for delta in shocks:
            new_util = _clamp(util + delta, 0.0, 1.0)
            new_borrow = _borrow_rate_at_util(new_util, base, s1, s2, kink)
            new_supply  = _supply_apy_from_borrow(new_util, new_borrow, rf)
            borrow_change = (new_borrow - _borrow_rate_at_util(util, base, s1, s2, kink)) * 100.0
            supply_change = new_supply * 100.0 - _supply_apy_from_borrow(
                util, _borrow_rate_at_util(util, base, s1, s2, kink), rf
            ) * 100.0
            results.append({
                "util_delta_pp":        round(delta * 100.0, 1),
                "new_utilization_pct":  round(new_util * 100.0, 2),
                "new_borrow_rate_pct":  round(new_borrow * 100.0, 4),
                "new_supply_apy_pct":   round(new_supply * 100.0, 4),
                "borrow_rate_change_pp": round(borrow_change, 4),
                "supply_apy_change_pp": round(supply_change, 4),
                "crosses_kink":         (util < kink) and (new_util >= kink),
            })
        return results

    # ── flags ─────────────────────────────────────────────────────────────────

    def _flags(
        self,
        util: float,
        kink: float,
        kink_distance: float,
        elasticity: float,
        borrow_rate: float,
        cliff_delta_pct: float,
    ) -> List[str]:
        flags: List[str] = []

        if util >= UTIL_CRITICAL:
            flags.append("UTILIZATION_CRITICAL")
        elif util >= UTIL_HIGH:
            flags.append("UTILIZATION_HIGH")

        # Above kink
        if util > kink:
            flags.append("ABOVE_KINK")

        # Near kink
        if 0.0 < kink_distance <= KINK_PROXIMITY_CRITICAL:
            flags.append("KINK_PROXIMITY_CRITICAL")
        elif 0.0 < kink_distance <= KINK_PROXIMITY_WARNING:
            flags.append("KINK_PROXIMITY_WARNING")

        # High elasticity → rate jumps strongly with small util changes
        if elasticity * 100.0 >= ELASTICITY_HIGH:
            flags.append("HIGH_RATE_ELASTICITY")
        elif elasticity * 100.0 >= ELASTICITY_MEDIUM:
            flags.append("MEDIUM_RATE_ELASTICITY")

        # Large cliff at kink
        if cliff_delta_pct >= 10.0:
            flags.append("LARGE_KINK_CLIFF")

        return flags

    # ── aggregates ────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        if not results:
            return {
                "highest_utilization": None,
                "lowest_utilization": None,
                "avg_utilization_pct": 0.0,
                "avg_borrow_rate_pct": 0.0,
                "above_kink_count": 0,
                "critical_utilization_count": 0,
            }

        by_util = sorted(results, key=lambda r: r["current_utilization_pct"], reverse=True)
        avg_util   = sum(r["current_utilization_pct"] for r in results) / len(results)
        avg_borrow = sum(r["current_borrow_rate_pct"] for r in results) / len(results)

        return {
            "highest_utilization":       by_util[0]["name"] if by_util else None,
            "lowest_utilization":        by_util[-1]["name"] if by_util else None,
            "avg_utilization_pct":       round(avg_util, 2),
            "avg_borrow_rate_pct":       round(avg_borrow, 4),
            "above_kink_count":          sum(1 for r in results if "ABOVE_KINK" in r["flags"]),
            "critical_utilization_count": sum(
                1 for r in results if r["utilization_label"] == "CRITICAL"
            ),
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap      = cfg["log_cap"]
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts":             datetime.now(timezone.utc).isoformat(),
            "protocol_count": len(results),
            "aggregates":     agg,
            "snapshots": [
                {
                    "name":             r["name"],
                    "utilization_pct":  r["current_utilization_pct"],
                    "util_label":       r["utilization_label"],
                    "borrow_rate_pct":  r["current_borrow_rate_pct"],
                    "kink_distance_pp": r["kink_distance_pp"],
                    "flags":            r["flags"],
                }
                for r in results
            ],
        }

        log: List[dict] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as fh:
                    log = json.load(fh)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append(entry)
        if len(log) > cap:
            log = log[-cap:]

        tmp = log_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, log_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_protocols() -> List[dict]:
    return [
        {
            "name": "Compound V3 USDC",
            "category": "lending",
            "current_utilization": 0.82,
            "base_rate": 0.02,
            "slope1": 0.10,
            "slope2": 3.00,
            "kink": 0.80,
            "reserve_factor": 0.10,
            "total_supply_usd": 2_000_000_000,
            "total_borrow_usd": 1_640_000_000,
        },
        {
            "name": "Aave V3 USDC",
            "category": "lending",
            "current_utilization": 0.65,
            "base_rate": 0.0,
            "slope1": 0.04,
            "slope2": 0.60,
            "kink": 0.90,
            "reserve_factor": 0.10,
            "total_supply_usd": 5_000_000_000,
            "total_borrow_usd": 3_250_000_000,
        },
    ]


if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="MP-1110 Lending Utilization Elasticity Analyzer")
    parser.add_argument("--run",   action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolLendingUtilizationElasticityAnalyzer()
    result = analyzer.analyze(_demo_protocols(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
