"""
MP-1109: DeFiProtocolYieldHarvestingFrequencyOptimizer
Computes the optimal compounding (harvest) frequency for DeFi yield positions
given gas costs, current APY, position size, and reward-emission decay.
Pure stdlib, read-only/advisory, atomic ring-buffer log.
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "harvest_frequency_log.json"
)
LOG_CAP = 100

DAYS_PER_YEAR  = 365.25
MIN_HARVEST_INTERVAL_DAYS = 0.5      # never harvest more than twice per day
MAX_HARVEST_INTERVAL_DAYS = 365.0    # never wait more than a year

# Frequency label thresholds (interval in days)
_FREQ_LABELS: List[Tuple[float, str]] = [
    (1.0,   "DAILY"),
    (7.0,   "WEEKLY"),
    (30.0,  "MONTHLY"),
    (90.0,  "QUARTERLY"),
    (365.0, "ANNUALLY"),
    (float("inf"), "NEVER_PROFITABLE"),
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _daily_rate(apy_pct: float) -> float:
    """Convert APY% to daily compounding rate."""
    if apy_pct <= 0:
        return 0.0
    return (1.0 + apy_pct / 100.0) ** (1.0 / DAYS_PER_YEAR) - 1.0


def _apy_from_daily(daily_rate: float) -> float:
    """Convert daily rate back to APY%."""
    return ((1.0 + daily_rate) ** DAYS_PER_YEAR - 1.0) * 100.0


def _compound_gain(position_usd: float, daily_rate: float, days: float) -> float:
    """Gain from compounding at daily_rate for `days` days."""
    return position_usd * ((1.0 + daily_rate) ** days - 1.0)


def _frequency_label(interval_days: float) -> str:
    for threshold, label in _FREQ_LABELS:
        if interval_days <= threshold:
            return label
    return "NEVER_PROFITABLE"


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


def optimal_harvest_interval_days(
    position_usd: float,
    apy_pct: float,
    gas_cost_usd: float,
    reward_decay_pct_per_day: float = 0.0,
) -> float:
    """
    Analytically approximate the optimal harvest interval in days.

    Derivation: gain from compounding G(t) ≈ position * r * t  (linear approx)
    Net gain = G(t) - gas_cost.  Optimal t* maximises net gain per day:
        d/dt[(G(t) - gas) / t] = 0
    For continuous compounding:
        t* = sqrt(2 * gas / (position * r))
    where r = annual yield rate.

    With decay factor d (fraction/day), yield rate at time t ≈ r * exp(-d*t),
    so effective annual yield is modulated; we iterate numerically for decay > 0.
    """
    if position_usd <= 0 or apy_pct <= 0 or gas_cost_usd < 0:
        return MAX_HARVEST_INTERVAL_DAYS

    daily_r = _daily_rate(apy_pct)
    if daily_r <= 0:
        return MAX_HARVEST_INTERVAL_DAYS

    if reward_decay_pct_per_day <= 0:
        # Closed-form
        t_star = math.sqrt(2.0 * gas_cost_usd / (position_usd * daily_r))
    else:
        # Numerical search: maximise net_gain_per_day over interval grid
        decay = reward_decay_pct_per_day / 100.0
        best_t   = MAX_HARVEST_INTERVAL_DAYS
        best_val = -1e18
        # Grid search: 0.5 to 365 days in 0.5-day steps
        t = MIN_HARVEST_INTERVAL_DAYS
        while t <= MAX_HARVEST_INTERVAL_DAYS:
            effective_daily = daily_r * math.exp(-decay * t)
            gain = position_usd * effective_daily * t - gas_cost_usd
            if gain > 0:
                score = gain / t
                if score > best_val:
                    best_val = score
                    best_t   = t
            t += 0.5
        t_star = best_t

    return _clamp(t_star, MIN_HARVEST_INTERVAL_DAYS, MAX_HARVEST_INTERVAL_DAYS)


def effective_apy_with_compounding(
    apy_pct: float,
    position_usd: float,
    gas_cost_usd: float,
    harvest_interval_days: float,
) -> float:
    """
    Net effective APY after accounting for gas costs at the given harvest interval.
    """
    if position_usd <= 0 or harvest_interval_days <= 0:
        return 0.0

    daily_r = _daily_rate(apy_pct)
    harvests_per_year = DAYS_PER_YEAR / harvest_interval_days
    annual_gas = gas_cost_usd * harvests_per_year

    # Gross gains for one interval, compounded across the year
    interval_gain = _compound_gain(position_usd, daily_r, harvest_interval_days)
    annual_gross  = interval_gain * (DAYS_PER_YEAR / harvest_interval_days)
    net_annual    = max(0.0, annual_gross - annual_gas)
    return net_annual / position_usd * 100.0


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolYieldHarvestingFrequencyOptimizer:
    """
    Computes optimal harvest frequency per position/protocol.

    Input position dict keys:
        name                    : str
        protocol                : str
        position_usd            : float  (current USD value in pool)
        gross_apy_pct           : float  (raw APY before gas drag)
        gas_cost_per_harvest_usd: float  (estimated USD gas for one harvest tx)
        reward_decay_pct_per_day: float  (optional; emission decay %/day, default 0)
        current_harvest_interval_days: float  (user's current practice; for comparison)
    """

    def optimize(
        self,
        positions: List[dict],
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        results = [self._optimize_position(p) for p in positions]
        agg = self._aggregate(results)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"positions": results, "aggregate": agg}

    # ── per-position ──────────────────────────────────────────────────────────

    def _optimize_position(self, p: dict) -> dict:
        name     = p.get("name", "unknown")
        protocol = p.get("protocol", "unknown")
        pos_usd  = float(p.get("position_usd", 0.0))
        apy      = float(p.get("gross_apy_pct", 0.0))
        gas      = float(p.get("gas_cost_per_harvest_usd", 0.0))
        decay    = float(p.get("reward_decay_pct_per_day", 0.0))
        current_interval = float(p.get("current_harvest_interval_days", 7.0))

        # Optimal interval
        opt_interval = optimal_harvest_interval_days(pos_usd, apy, gas, decay)
        opt_label    = _frequency_label(opt_interval)

        # Effective APYs
        eff_apy_optimal  = effective_apy_with_compounding(apy, pos_usd, gas, opt_interval)
        eff_apy_current  = effective_apy_with_compounding(apy, pos_usd, gas, current_interval)
        apy_improvement  = max(0.0, eff_apy_optimal - eff_apy_current)

        # Annual savings / additional yield from switching to optimal
        additional_annual_yield = pos_usd * apy_improvement / 100.0

        # Min position size at which harvesting becomes profitable
        min_position = self._min_profitable_position(apy, gas)

        flags = self._flags(
            opt_interval, current_interval, eff_apy_optimal, apy,
            pos_usd, min_position, gas, decay
        )

        return {
            "name":                       name,
            "protocol":                   protocol,
            "position_usd":               round(pos_usd, 2),
            "gross_apy_pct":              round(apy, 4),
            "gas_cost_per_harvest_usd":   round(gas, 4),
            "reward_decay_pct_per_day":   round(decay, 4),
            "optimal_interval_days":      round(opt_interval, 2),
            "optimal_frequency_label":    opt_label,
            "current_interval_days":      round(current_interval, 2),
            "effective_apy_at_optimal":   round(eff_apy_optimal, 4),
            "effective_apy_at_current":   round(eff_apy_current, 4),
            "apy_improvement_pct":        round(apy_improvement, 4),
            "additional_annual_yield_usd": round(additional_annual_yield, 2),
            "min_profitable_position_usd": round(min_position, 2),
            "flags":                      flags,
        }

    # ── helpers ───────────────────────────────────────────────────────────────

    def _min_profitable_position(self, apy_pct: float, gas_usd: float) -> float:
        """
        Minimum position size (USD) for harvesting to be net-positive at all
        (assuming annual harvest; break-even: pos * APY ≥ gas * 365/interval).
        For annual harvest: min_pos = gas / (apy/100).
        """
        if apy_pct <= 0:
            return float("inf")
        return gas_usd / (apy_pct / 100.0)

    # ── flags ─────────────────────────────────────────────────────────────────

    def _flags(
        self,
        opt_interval: float,
        current_interval: float,
        eff_apy_opt: float,
        gross_apy: float,
        pos_usd: float,
        min_pos: float,
        gas: float,
        decay: float,
    ) -> List[str]:
        flags: List[str] = []

        # Position too small to harvest profitably
        if pos_usd < min_pos and min_pos < float("inf"):
            flags.append("POSITION_TOO_SMALL_TO_HARVEST")

        # Gas exceeds 10% of annual yield
        if gross_apy > 0:
            annual_yield = pos_usd * gross_apy / 100.0
            harvests_per_year = DAYS_PER_YEAR / max(opt_interval, 1.0)
            if gas * harvests_per_year > annual_yield * 0.10:
                flags.append("HIGH_GAS_DRAG")

        # Current frequency is >2× too frequent vs optimal
        if current_interval < opt_interval / 2.0:
            flags.append("OVER_HARVESTING")

        # Current frequency is <½ of optimal (under-compounding)
        if current_interval > opt_interval * 2.0:
            flags.append("UNDER_HARVESTING")

        # Effective APY degraded ≥5pp by gas
        if gross_apy > 0 and (gross_apy - eff_apy_opt) >= 5.0:
            flags.append("GAS_ERODES_SIGNIFICANT_YIELD")

        # High decay
        if decay >= 1.0:
            flags.append("HIGH_REWARD_DECAY")

        return flags

    # ── aggregates ────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        if not results:
            return {
                "total_additional_annual_yield_usd": 0.0,
                "avg_apy_improvement_pct": 0.0,
                "over_harvesting_count": 0,
                "under_harvesting_count": 0,
                "most_suboptimal_position": None,
            }

        total_additional = sum(r["additional_annual_yield_usd"] for r in results)
        avg_improvement  = sum(r["apy_improvement_pct"] for r in results) / len(results)
        over_harvesting  = sum(1 for r in results if "OVER_HARVESTING" in r["flags"])
        under_harvesting = sum(1 for r in results if "UNDER_HARVESTING" in r["flags"])

        by_suboptimality = sorted(
            results, key=lambda r: abs(r["optimal_interval_days"] - r["current_interval_days"]), reverse=True
        )

        return {
            "total_additional_annual_yield_usd": round(total_additional, 2),
            "avg_apy_improvement_pct": round(avg_improvement, 4),
            "over_harvesting_count":  over_harvesting,
            "under_harvesting_count": under_harvesting,
            "most_suboptimal_position": by_suboptimality[0]["name"] if by_suboptimality else None,
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap      = cfg["log_cap"]
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts":             datetime.now(timezone.utc).isoformat(),
            "position_count": len(results),
            "aggregates":     agg,
            "snapshots": [
                {
                    "name":                  r["name"],
                    "optimal_interval_days": r["optimal_interval_days"],
                    "frequency_label":       r["optimal_frequency_label"],
                    "apy_improvement_pct":   r["apy_improvement_pct"],
                    "additional_yield_usd":  r["additional_annual_yield_usd"],
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

def _demo_positions() -> List[dict]:
    return [
        {
            "name": "Aave USDC (large)",
            "protocol": "Aave V3",
            "position_usd": 500_000.0,
            "gross_apy_pct": 4.5,
            "gas_cost_per_harvest_usd": 15.0,
            "reward_decay_pct_per_day": 0.0,
            "current_harvest_interval_days": 1.0,
        },
        {
            "name": "Small farm (high gas)",
            "protocol": "SomeYieldFarm",
            "position_usd": 5_000.0,
            "gross_apy_pct": 20.0,
            "gas_cost_per_harvest_usd": 50.0,
            "reward_decay_pct_per_day": 0.5,
            "current_harvest_interval_days": 7.0,
        },
    ]


if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="MP-1109 Yield Harvesting Frequency Optimizer")
    parser.add_argument("--run",   action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    optimizer = DeFiProtocolYieldHarvestingFrequencyOptimizer()
    result = optimizer.optimize(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
