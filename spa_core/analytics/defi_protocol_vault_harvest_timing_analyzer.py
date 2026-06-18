"""
MP-1167: DeFiProtocolVaultHarvestTimingAnalyzer
===============================================
Advisory/read-only analytics module.

A vault accrues UNHARVESTED (pending) rewards that are only reinvested when a
harvest/compound is triggered. Each harvest costs a FIXED gas amount
(harvest_gas_usd). Harvest too often and gas eats the reward; harvest too rarely
and you forgo compounding. This module evaluates, for a given vault, whether to
harvest NOW or wait, the optimal harvest size/interval, and the current gas-drag
on pending rewards.

Angle: "pending is $40, harvest gas is $25, accruing $6/day → it is too early to
harvest; the optimum is roughly every X days."

HIGHER score = closer to optimal harvest timing / lower gas-drag.

Distinct from:
  * vault_gas_breakeven → round-trip deposit/withdrawal gas vs position size and
    holding period (whether to enter the vault at all).
This module isolates the *timing of fixed-gas harvesting* against reward
accrual — when to claim, not whether to deposit.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_harvest_timing_log.json"
)
LOG_CAP = 100

# Min-harvest-ratio bounds (target pending/gas ratio that justifies harvesting).
MIN_HARVEST_RATIO_MIN = 1.0
MIN_HARVEST_RATIO_MAX = 50.0

# Classification thresholds (pending as a fraction of optimal pending).
APPROACHING_OPTIMAL_FRACTION = 0.5  # pending at/above → approaching optimal
# Overdue when pending exceeds optimal by this multiple.
OVERDUE_OPTIMAL_MULTIPLE = 1.5

# Scoring reference: gas drag normalised against this ceiling for the low-drag
# component (drag at/above this contributes nothing).
GAS_DRAG_SCORE_CEILING_PCT = 100.0

# Flag thresholds.
HIGH_GAS_DRAG_PCT = 33.0  # gas drag at/above this is high


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

class DeFiProtocolVaultHarvestTimingAnalyzer:
    """
    Models the TIMING of fixed-gas harvesting against reward accrual. Pending
    rewards grow at a daily accrual rate but are only compounded when harvested,
    and each harvest costs a fixed gas amount. Harvesting too early wastes gas;
    too late forgoes compounding. For a given vault the module computes the
    gas-to-reward ratio, whether harvesting now is worthwhile, the optimal
    pending size / harvest interval and the current gas-drag.

    HIGHER score = closer to optimal harvest timing / lower gas-drag.

    Per-position input dict fields:
        vault / token              : str
        pending_rewards_usd        : float (default 0; max(0,..))
        harvest_gas_usd            : float (default 0; max(0,..))
        reward_accrual_usd_per_day : float (default 0; max(0,..))
        days_since_last_harvest    : float (default 0; max(0,..))
        min_harvest_ratio          : float (default 3.0; clamp 1.0..50.0)
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
        token = p.get("vault", p.get("token", "UNKNOWN"))
        pending_usd = max(0.0, _f(p.get("pending_rewards_usd")))
        harvest_gas_usd = max(0.0, _f(p.get("harvest_gas_usd")))
        accrual_per_day = max(0.0, _f(p.get("reward_accrual_usd_per_day")))
        days_since_last = max(0.0, _f(p.get("days_since_last_harvest")))
        min_harvest_ratio = _clamp(
            _f(p.get("min_harvest_ratio"), 3.0),
            MIN_HARVEST_RATIO_MIN, MIN_HARVEST_RATIO_MAX)

        # Insufficient data: nothing pending and no accrual → nothing to model.
        if pending_usd <= 0 and accrual_per_day <= 0:
            return self._insufficient(token)

        # Gas-to-reward ratio: None if no pending reward to measure against.
        gas_to_reward_ratio = (
            None if pending_usd <= 0 else round(harvest_gas_usd / pending_usd, 4))

        # Reward-to-gas ratio: None if gas is free (harvest always worthwhile).
        reward_to_gas_ratio = (
            None if harvest_gas_usd <= 0 else pending_usd / harvest_gas_usd)
        if reward_to_gas_ratio is not None and not math.isfinite(
                reward_to_gas_ratio):
            reward_to_gas_ratio = None

        # Worthwhile now: there is pending and either gas is free or pending
        # clears the target ratio against gas.
        harvest_worthwhile_now = bool(
            pending_usd > 0
            and (harvest_gas_usd <= 0
                 or pending_usd >= harvest_gas_usd * min_harvest_ratio))

        # Target pending size at which a harvest is justified.
        optimal_harvest_pending_usd = harvest_gas_usd * min_harvest_ratio

        # Days until pending reaches optimal; None if no accrual.
        if accrual_per_day > 0:
            days_to_optimal = max(
                0.0,
                (optimal_harvest_pending_usd - pending_usd) / accrual_per_day)
            if not math.isfinite(days_to_optimal):
                days_to_optimal = None
            else:
                days_to_optimal = round(days_to_optimal, 4)
        else:
            days_to_optimal = None

        # Optimal harvest interval from zero pending; None if no accrual.
        if accrual_per_day > 0:
            optimal_interval_days = (
                optimal_harvest_pending_usd / accrual_per_day)
            if not math.isfinite(optimal_interval_days):
                optimal_interval_days = None
            else:
                optimal_interval_days = round(optimal_interval_days, 4)
        else:
            optimal_interval_days = None

        net_if_harvest_now_usd = pending_usd - harvest_gas_usd

        # Gas drag: harvest gas as a % of pending reward.
        gas_drag_pct = max(
            0.0, _safe_div(harvest_gas_usd, pending_usd, 0.0) * 100.0)

        overdue = bool(
            pending_usd >= optimal_harvest_pending_usd * OVERDUE_OPTIMAL_MULTIPLE
            and optimal_harvest_pending_usd > 0)

        score = self._score(
            gas_drag_pct, harvest_worthwhile_now, reward_to_gas_ratio,
            min_harvest_ratio)
        classification = self._classify(
            pending_usd, harvest_gas_usd, optimal_harvest_pending_usd,
            harvest_worthwhile_now, net_if_harvest_now_usd)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification, overdue, harvest_gas_usd, gas_drag_pct,
            accrual_per_day, net_if_harvest_now_usd, pending_usd)

        return {
            "token": token,
            "pending_rewards_usd": round(pending_usd, 4),
            "harvest_gas_usd": round(harvest_gas_usd, 4),
            "reward_accrual_usd_per_day": round(accrual_per_day, 4),
            "days_since_last_harvest": round(days_since_last, 4),
            "min_harvest_ratio": round(min_harvest_ratio, 4),
            "gas_to_reward_ratio": gas_to_reward_ratio,
            "reward_to_gas_ratio": (
                None if reward_to_gas_ratio is None
                else round(reward_to_gas_ratio, 4)),
            "harvest_worthwhile_now": harvest_worthwhile_now,
            "optimal_harvest_pending_usd": round(
                optimal_harvest_pending_usd, 4),
            "days_to_optimal": days_to_optimal,
            "optimal_interval_days": optimal_interval_days,
            "net_if_harvest_now_usd": round(net_if_harvest_now_usd, 4),
            "gas_drag_pct": round(gas_drag_pct, 4),
            "overdue": overdue,
            "current_accrual_per_day": round(accrual_per_day, 4),
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        gas_drag_pct: float,
        harvest_worthwhile_now: bool,
        reward_to_gas_ratio: Optional[float],
        min_harvest_ratio: float,
    ) -> float:
        """
        0–100, HIGHER = closer to optimal timing / lower gas-drag. Components:
          low gas drag (50) — drag normalised against the scoring ceiling.
          worthwhile now (30) — full credit when harvesting now is justified.
          healthy ratio (20) — reward/gas normalised against 2× min ratio.
        """
        low_drag_comp = 50.0 * _clamp(
            1.0 - gas_drag_pct / GAS_DRAG_SCORE_CEILING_PCT, 0.0, 1.0)
        worthwhile_comp = 30.0 if harvest_worthwhile_now else 0.0
        # Free harvest (reward_to_gas None) → full healthy-ratio credit.
        if reward_to_gas_ratio is None:
            healthy_ratio_comp = 20.0
        else:
            denom = min_harvest_ratio * 2.0
            healthy_ratio_comp = 20.0 * _clamp(
                _safe_div(reward_to_gas_ratio, denom, 0.0), 0.0, 1.0)
        total = low_drag_comp + worthwhile_comp + healthy_ratio_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(
        self,
        pending_usd: float,
        harvest_gas_usd: float,
        optimal_harvest_pending_usd: float,
        harvest_worthwhile_now: bool,
        net_if_harvest_now_usd: float,
    ) -> str:
        if net_if_harvest_now_usd <= 0 and pending_usd > 0:
            return "GAS_EXCEEDS_REWARD"
        if harvest_worthwhile_now and net_if_harvest_now_usd > 0:
            return "HARVEST_NOW"
        if pending_usd >= optimal_harvest_pending_usd * APPROACHING_OPTIMAL_FRACTION:
            return "APPROACHING_OPTIMAL"
        return "TOO_EARLY"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "DO_NOT_HARVEST_YET"
        if classification == "HARVEST_NOW":
            return "HARVEST_NOW"
        if classification == "APPROACHING_OPTIMAL":
            return "WAIT_SHORT"
        if classification == "TOO_EARLY":
            return "WAIT"
        # GAS_EXCEEDS_REWARD
        return "DO_NOT_HARVEST_YET"

    def _flags(
        self,
        classification: str,
        overdue: bool,
        harvest_gas_usd: float,
        gas_drag_pct: float,
        accrual_per_day: float,
        net_if_harvest_now_usd: float,
        pending_usd: float,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "HARVEST_NOW":
            flags.append("HARVEST_NOW")
        if overdue:
            flags.append("OVERDUE")
        if classification == "TOO_EARLY":
            flags.append("TOO_EARLY")
        if net_if_harvest_now_usd <= 0 and pending_usd > 0:
            flags.append("GAS_EXCEEDS_REWARD")
        if harvest_gas_usd <= 0:
            flags.append("FREE_HARVEST")
        if gas_drag_pct >= HIGH_GAS_DRAG_PCT:
            flags.append("HIGH_GAS_DRAG")
        if accrual_per_day <= 0:
            flags.append("NO_ACCRUAL")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "pending_rewards_usd": 0.0,
            "harvest_gas_usd": 0.0,
            "reward_accrual_usd_per_day": 0.0,
            "days_since_last_harvest": 0.0,
            "min_harvest_ratio": 0.0,
            "gas_to_reward_ratio": None,
            "reward_to_gas_ratio": None,
            "harvest_worthwhile_now": False,
            "optimal_harvest_pending_usd": 0.0,
            "days_to_optimal": None,
            "optimal_interval_days": None,
            "net_if_harvest_now_usd": 0.0,
            "gas_drag_pct": 0.0,
            "overdue": False,
            "current_accrual_per_day": 0.0,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "DO_NOT_HARVEST_YET",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_ready_vault": None,
                "least_ready_vault": None,
                "avg_score": 0.0,
                "harvest_now_count": 0,
                "position_count": len(results),
            }
        # Higher score = closer to optimal → highest score is most ready.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        harvest_now = sum(
            1 for r in results if r["classification"] == "HARVEST_NOW")
        return {
            "most_ready_vault": by_score[-1]["token"],
            "least_ready_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "harvest_now_count": harvest_now,
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
                    "score": r["score"],
                    "recommendation": r["recommendation"],
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
            "vault": "USDC-Vault-HarvestNow",
            "pending_rewards_usd": 200.0,
            "harvest_gas_usd": 25.0,
            "reward_accrual_usd_per_day": 6.0,
            "days_since_last_harvest": 35.0,
            "min_harvest_ratio": 3.0,
        },
        {
            "vault": "GMX-Vault-TooEarly",
            "pending_rewards_usd": 12.0,
            "harvest_gas_usd": 25.0,
            "reward_accrual_usd_per_day": 6.0,
            "days_since_last_harvest": 2.0,
            "min_harvest_ratio": 3.0,
        },
        {
            "vault": "DAI-Vault-NoData",
            "pending_rewards_usd": 0.0,
            "harvest_gas_usd": 0.0,
            "reward_accrual_usd_per_day": 0.0,
            "days_since_last_harvest": 0.0,
            "min_harvest_ratio": 3.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1167 Vault Harvest Timing Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultHarvestTimingAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
