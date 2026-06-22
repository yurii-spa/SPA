"""
MP-1148: DeFiProtocolStablecoinParRedemptionCapacityAnalyzer
============================================================
Advisory/read-only analytics module.

Quantifies a holder's ability to EXIT a stablecoin position AT PAR ($1) at
scale — i.e. the *throughput* of redemption, not the price deviation itself.
A stablecoin can trade at $1.00 on screen yet be effectively *trapped* if the
issuer's primary par-redemption is gated by daily caps, a redemption queue /
cooldown, or insufficient liquid reserves, and the secondary market is too thin
to absorb the position without slippage.

This is the "I hold $X — how many days, at what haircut, and via which route
(primary redeem vs secondary market) can I get back to $X of hard dollars?"
question.

Distinct from:
  * depeg / peg-deviation monitors  → they score the PRICE gap from $1.
  * reserve_quality_scorer          → it scores reserve COMPOSITION quality.
  * withdrawal_queue_risk           → generic vault exit queue, not stablecoin
                                      par-redemption throughput + backing.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "stablecoin_par_redemption_capacity_log.json"
)
LOG_CAP = 100

DAYS_SENTINEL_NEVER = 1e9      # cannot exit via primary (no cap / no backing)
RATIO_SENTINEL_INF = 1e9       # backing >> position with position ~0

# Capacity-utilisation thresholds (position as % of daily redemption cap)
UTIL_HIGH_PCT = 80.0           # position consumes >80% of one day's cap
UTIL_MULTI_DAY_PCT = 100.0     # position exceeds a single day's cap

# Days-to-exit classification thresholds (calendar days incl. queue)
DAYS_AMPLE = 1.0               # ≤1 day → effectively immediate
DAYS_ADEQUATE = 3.0
DAYS_CONSTRAINED = 7.0
DAYS_TIGHT = 21.0             # beyond this → effectively trapped at par

# Backing coverage thresholds (liquid backing / position)
BACKING_FULL = 1.0
BACKING_THIN = 0.5

# Fee / slippage thresholds (pct)
HIGH_REDEMPTION_FEE_PCT = 0.5
SECONDARY_TIGHT_SLIPPAGE_PCT = 0.3   # secondary cheaper than waiting if ≤ this


# ── helpers ───────────────────────────────────────────────────────────────────

def _f(val, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_div(num: float, den: float, sentinel: float) -> float:
    if den <= 0:
        return sentinel
    return num / den


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


def _grade_from_score(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolStablecoinParRedemptionCapacityAnalyzer:
    """
    Analyzes par-redemption (exit-at-$1) capacity for stablecoin positions.

    Per-position input dict fields:
        token                      : str
        position_usd               : float  (size to exit at par)
        daily_redemption_cap_usd   : float  (issuer primary par-redeem cap/day;
                                             0 → no/unknown primary redemption)
        liquid_backing_usd         : float  (immediately-redeemable reserves)
        total_supply_usd           : float  (optional, context)
        redemption_fee_pct         : float  (fee on primary par redeem)
        redemption_delay_days      : float  (queue / cooldown before settlement)
        secondary_depth_usd        : float  (DEX/CEX depth to exit near par)
        secondary_slippage_pct     : float  (est slippage dumping position on 2ndary)
    """

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        position: dict,
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        result = self._analyze_one(position)
        if write_log:
            self._write_log([result], self._aggregate([result]), cfg)
        return result

    def analyze_portfolio(
        self,
        positions: List[dict],
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        results = [self._analyze_one(p) for p in positions]
        agg = self._aggregate(results)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"positions": results, "aggregate": agg}

    # ── per-position ───────────────────────────────────────────────────────────

    def _analyze_one(self, p: dict) -> dict:
        token = p.get("token", "UNKNOWN")
        position = _f(p.get("position_usd"))
        daily_cap = _f(p.get("daily_redemption_cap_usd"))
        liquid_backing = _f(p.get("liquid_backing_usd"))
        total_supply = _f(p.get("total_supply_usd"))
        fee_pct = max(0.0, _f(p.get("redemption_fee_pct")))
        delay_days = max(0.0, _f(p.get("redemption_delay_days")))
        sec_depth = _f(p.get("secondary_depth_usd"))
        sec_slip = max(0.0, _f(p.get("secondary_slippage_pct")))

        # Insufficient data: no position, or neither primary nor secondary path known
        if position <= 0 or (daily_cap <= 0 and sec_depth <= 0 and liquid_backing <= 0):
            return self._insufficient(token, position)

        # ── primary redemption throughput ──────────────────────────────────────
        # Days of capped redemption to clear the position, plus settlement delay.
        cap_days = _safe_div(position, daily_cap, DAYS_SENTINEL_NEVER)
        if cap_days >= DAYS_SENTINEL_NEVER:
            days_to_par_exit = DAYS_SENTINEL_NEVER
        else:
            days_to_par_exit = math.ceil(cap_days) + delay_days

        util_pct = _safe_div(position, daily_cap, RATIO_SENTINEL_INF) * 100.0
        if util_pct >= RATIO_SENTINEL_INF:
            util_pct = RATIO_SENTINEL_INF  # no primary cap → undefined utilisation

        backing_coverage = _safe_div(liquid_backing, position, RATIO_SENTINEL_INF)

        net_par_proceeds_pct = max(0.0, 100.0 - fee_pct)

        # Position as a share of total supply (systemic exit pressure)
        supply_share_pct = _safe_div(position, total_supply, RATIO_SENTINEL_INF) * 100.0
        if supply_share_pct >= RATIO_SENTINEL_INF:
            supply_share_pct = 0.0  # unknown supply → don't penalise

        # ── route recommendation ────────────────────────────────────────────────
        primary_ok = daily_cap > 0 and liquid_backing >= position
        secondary_ok = sec_depth >= position and sec_slip <= SECONDARY_TIGHT_SLIPPAGE_PCT

        # Effective haircut of each route (lower = better)
        primary_haircut = fee_pct if daily_cap > 0 else DAYS_SENTINEL_NEVER
        secondary_haircut = sec_slip if sec_depth > 0 else DAYS_SENTINEL_NEVER

        route = self._route(
            primary_ok, secondary_ok, primary_haircut, secondary_haircut,
            days_to_par_exit, sec_depth, position,
        )

        par_exit_feasible = (
            (daily_cap > 0 and days_to_par_exit <= DAYS_TIGHT and backing_coverage >= BACKING_THIN)
            or secondary_ok
        )

        score = self._capacity_score(
            days_to_par_exit, backing_coverage, util_pct, fee_pct,
            sec_depth, position, sec_slip,
        )
        classification = self._classify(days_to_par_exit, backing_coverage, par_exit_feasible)
        grade = _grade_from_score(score)
        flags = self._flags(
            daily_cap, days_to_par_exit, backing_coverage, util_pct,
            fee_pct, route, par_exit_feasible, classification,
        )

        return {
            "token": token,
            "position_usd": round(position, 2),
            "days_to_par_exit": (
                None if days_to_par_exit >= DAYS_SENTINEL_NEVER else round(days_to_par_exit, 2)
            ),
            "redemption_capacity_utilization_pct": (
                None if util_pct >= RATIO_SENTINEL_INF else round(util_pct, 2)
            ),
            "backing_coverage_ratio": (
                None if backing_coverage >= RATIO_SENTINEL_INF else round(backing_coverage, 4)
            ),
            "net_par_proceeds_pct": round(net_par_proceeds_pct, 4),
            "supply_share_pct": round(supply_share_pct, 4),
            "recommended_exit_route": route,
            "par_exit_feasible": bool(par_exit_feasible),
            "redemption_capacity_score": round(score, 2),
            "classification": classification,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _capacity_score(
        self,
        days_to_par_exit: float,
        backing_coverage: float,
        util_pct: float,
        fee_pct: float,
        sec_depth: float,
        position: float,
        sec_slip: float,
    ) -> float:
        """
        0–100, higher = easier to exit at par. Weighted:
          speed (≈45) + backing (≈30) + cost (≈15) + secondary fallback (≈10).
        """
        # Speed component — fast saturating decay with days
        if days_to_par_exit >= DAYS_SENTINEL_NEVER:
            speed = 0.0
        else:
            # 1 day → ~45, 7 days → ~22, 30 days → ~8
            speed = 45.0 / (1.0 + days_to_par_exit / 4.0)

        # Backing component
        if backing_coverage >= RATIO_SENTINEL_INF:
            backing = 30.0  # unknown/huge backing relative to position
        else:
            backing = 30.0 * _clamp(backing_coverage / BACKING_FULL, 0.0, 1.0)

        # Cost component — full fee of 1% → 0
        cost = 15.0 * _clamp(1.0 - fee_pct / 1.0, 0.0, 1.0)

        # Secondary fallback component
        if position > 0 and sec_depth >= position and sec_slip <= SECONDARY_TIGHT_SLIPPAGE_PCT:
            secondary = 10.0
        elif sec_depth > 0 and position > 0:
            depth_ratio = _clamp(sec_depth / position, 0.0, 1.0)
            slip_factor = _clamp(1.0 - sec_slip / 1.0, 0.0, 1.0)
            secondary = 10.0 * depth_ratio * slip_factor
        else:
            secondary = 0.0

        return _clamp(speed + backing + cost + secondary, 0.0, 100.0)

    def _route(
        self,
        primary_ok: bool,
        secondary_ok: bool,
        primary_haircut: float,
        secondary_haircut: float,
        days_to_par_exit: float,
        sec_depth: float,
        position: float,
    ) -> str:
        has_primary = primary_haircut < DAYS_SENTINEL_NEVER
        has_secondary = secondary_haircut < DAYS_SENTINEL_NEVER

        if not has_primary and not has_secondary:
            return "TRAPPED"
        if primary_ok and secondary_ok:
            # both viable → prefer cheaper haircut; tie → primary (true par)
            return "SECONDARY_MARKET" if secondary_haircut < primary_haircut else "PRIMARY_REDEEM"
        if secondary_ok and not primary_ok:
            return "SECONDARY_MARKET"
        if primary_ok and not secondary_ok:
            return "PRIMARY_REDEEM"
        # Neither fully clears the position alone → split across routes if both exist
        if has_primary and has_secondary and sec_depth > 0:
            return "SPLIT_PRIMARY_AND_SECONDARY"
        if has_primary:
            return "PRIMARY_REDEEM"
        return "SECONDARY_MARKET"

    def _classify(
        self,
        days_to_par_exit: float,
        backing_coverage: float,
        par_exit_feasible: bool,
    ) -> str:
        if not par_exit_feasible and days_to_par_exit >= DAYS_SENTINEL_NEVER:
            return "TRAPPED"
        if days_to_par_exit >= DAYS_SENTINEL_NEVER:
            # no primary path but secondary feasible
            return "CONSTRAINED" if par_exit_feasible else "TRAPPED"
        if days_to_par_exit <= DAYS_AMPLE and backing_coverage >= BACKING_FULL:
            return "AMPLE_CAPACITY"
        if days_to_par_exit <= DAYS_ADEQUATE and backing_coverage >= BACKING_THIN:
            return "ADEQUATE"
        if days_to_par_exit <= DAYS_CONSTRAINED:
            return "CONSTRAINED"
        if days_to_par_exit <= DAYS_TIGHT:
            return "TIGHT"
        return "TRAPPED"

    def _flags(
        self,
        daily_cap: float,
        days_to_par_exit: float,
        backing_coverage: float,
        util_pct: float,
        fee_pct: float,
        route: str,
        par_exit_feasible: bool,
        classification: str,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "AMPLE_CAPACITY":
            flags.append("AMPLE_CAPACITY")
        if daily_cap <= 0:
            flags.append("NO_PRIMARY_REDEMPTION")
        if backing_coverage < BACKING_FULL and backing_coverage < RATIO_SENTINEL_INF:
            flags.append("BACKING_SHORTFALL")
        if util_pct >= UTIL_MULTI_DAY_PCT and util_pct < RATIO_SENTINEL_INF:
            flags.append("EXCEEDS_DAILY_CAP")
        elif util_pct >= UTIL_HIGH_PCT and util_pct < RATIO_SENTINEL_INF:
            flags.append("HIGH_CAPACITY_UTILIZATION")
        if days_to_par_exit > DAYS_CONSTRAINED and days_to_par_exit < DAYS_SENTINEL_NEVER:
            flags.append("SLOW_REDEMPTION_QUEUE")
        if fee_pct >= HIGH_REDEMPTION_FEE_PCT:
            flags.append("HIGH_REDEMPTION_FEE")
        if route in ("SECONDARY_MARKET", "SPLIT_PRIMARY_AND_SECONDARY"):
            flags.append("SECONDARY_PREFERRED")
        if not par_exit_feasible:
            flags.append("TRAPPED_AT_PAR")

        return flags

    def _insufficient(self, token: str, position: float) -> dict:
        return {
            "token": token,
            "position_usd": round(max(0.0, position), 2),
            "days_to_par_exit": None,
            "redemption_capacity_utilization_pct": None,
            "backing_coverage_ratio": None,
            "net_par_proceeds_pct": 0.0,
            "supply_share_pct": 0.0,
            "recommended_exit_route": "TRAPPED",
            "par_exit_feasible": False,
            "redemption_capacity_score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_constrained_position": None,
                "least_constrained_position": None,
                "avg_redemption_capacity_score": 0.0,
                "trapped_count": 0,
                "position_count": len(results),
            }
        by_score = sorted(scored, key=lambda r: r["redemption_capacity_score"])
        avg = _mean([r["redemption_capacity_score"] for r in scored])
        trapped = sum(1 for r in results if r["classification"] == "TRAPPED")
        return {
            "most_constrained_position": by_score[0]["token"],
            "least_constrained_position": by_score[-1]["token"],
            "avg_redemption_capacity_score": round(avg, 2),
            "trapped_count": trapped,
            "position_count": len(results),
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap = cfg["log_cap"]
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "position_count": len(results),
            "aggregate": agg,
            "snapshots": [
                {
                    "token": r["token"],
                    "classification": r["classification"],
                    "redemption_capacity_score": r["redemption_capacity_score"],
                    "recommended_exit_route": r["recommended_exit_route"],
                    "flags": r["flags"],
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
            "token": "USDC",
            "position_usd": 500_000.0,
            "daily_redemption_cap_usd": 50_000_000.0,
            "liquid_backing_usd": 30_000_000_000.0,
            "total_supply_usd": 32_000_000_000.0,
            "redemption_fee_pct": 0.0,
            "redemption_delay_days": 0.0,
            "secondary_depth_usd": 20_000_000.0,
            "secondary_slippage_pct": 0.02,
        },
        {
            "token": "SmallStable",
            "position_usd": 2_000_000.0,
            "daily_redemption_cap_usd": 250_000.0,
            "liquid_backing_usd": 1_000_000.0,
            "total_supply_usd": 40_000_000.0,
            "redemption_fee_pct": 0.75,
            "redemption_delay_days": 3.0,
            "secondary_depth_usd": 300_000.0,
            "secondary_slippage_pct": 1.2,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1148 Stablecoin Par-Redemption Capacity Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolStablecoinParRedemptionCapacityAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
