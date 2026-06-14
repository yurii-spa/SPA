"""
MP-1161: DeFiProtocolVaultWithdrawalFeeDecayAnalyzer
====================================================
Advisory/read-only analytics module.

Some vaults charge a TIME-DECAYING early-withdrawal fee (a "loyalty" / exit-ramp
fee): a high withdrawal fee right after deposit that linearly decays to a floor
over a ramp period. A holder needs the effective withdrawal fee at the current
holding day, how many days until it reaches the floor, the fee saved by waiting,
and the yield earned while waiting.

This isolates the *decay schedule* over holding time — the current effective fee
given days held, the days remaining to the floor, the fee (and USD) saved by
waiting for the floor, and the yield accrued during that wait.

Distinct from:
  * vault_round_trip_cost → static deposit + withdrawal fees, break-even days.
This module answers only the *time-decaying withdrawal fee* question.

HIGHER score = cheaper to exit NOW (the fee has matured toward its floor).

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
    "data", "vault_withdrawal_fee_decay_log.json"
)
LOG_CAP = 100

HIGH_FEE_PCT = 5.0        # effective fee at/above this is "high"
MODERATE_FEE_PCT = 2.0    # effective fee at/above this is "moderate"/high-exit
LOW_FEE_PCT = 0.5        # effective fee below this is "low"
NEAR_FLOOR_DAYS = 7.0    # days to floor at/below this is "near floor"
LONG_RAMP_DAYS = 60.0    # days to floor above this is "long ramp remaining"
DAYS_PER_YEAR = 365.0
FEE_EPSILON = 1e-9       # tolerance for "at floor" comparison


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

class DeFiProtocolVaultWithdrawalFeeDecayAnalyzer:
    """
    Models a vault's TIME-DECAYING early-withdrawal fee: the effective fee at the
    current holding day, days to the floor, fee saved by waiting, and yield
    earned while waiting.

    HIGHER score = cheaper to exit NOW (fee has matured toward its floor).

    Per-position input dict fields:
        vault / token              : str
        initial_withdrawal_fee_pct : float (default 0; clamp 0..100)
        floor_withdrawal_fee_pct   : float (default 0; clamp 0..100)
        fee_decay_days             : float (default 0)
        days_held                  : float (default 0; max(0,..))
        position_usd               : float (default 0; max(0,..))
        apr_pct                    : float (default 0)
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
        initial = _clamp(_f(p.get("initial_withdrawal_fee_pct")), 0.0, 100.0)
        floor = _clamp(_f(p.get("floor_withdrawal_fee_pct")), 0.0, 100.0)
        fee_decay_days = max(0.0, _f(p.get("fee_decay_days")))
        days_held = max(0.0, _f(p.get("days_held")))
        position_usd = max(0.0, _f(p.get("position_usd")))
        apr_pct = _f(p.get("apr_pct"))

        # Insufficient data: no fee schedule at all → nothing to analyze.
        if initial <= 0 and floor <= 0 and fee_decay_days <= 0:
            return self._insufficient(token)

        # Guard against an inverted schedule (floor above initial): treat the
        # effective initial as the larger of the two so the fee decays downward.
        eff_initial = max(initial, floor)
        lo_fee = min(initial, floor)
        hi_fee = max(initial, floor)

        if fee_decay_days > 0:
            progress = _clamp(days_held / fee_decay_days, 0.0, 1.0)
        else:
            progress = 1.0

        current_fee_pct = _clamp(
            eff_initial - (eff_initial - floor) * progress, lo_fee, hi_fee)
        # Never below the floor.
        if current_fee_pct < floor:
            current_fee_pct = floor

        days_to_floor = max(0.0, fee_decay_days - days_held)
        at_floor = current_fee_pct <= floor + FEE_EPSILON or progress >= 1.0
        # Once at the floor, snap the effective fee exactly to the floor so tiny
        # float artifacts don't show up as residual savings.
        if at_floor:
            current_fee_pct = floor

        fee_now_usd = position_usd * current_fee_pct / 100.0
        fee_at_floor_usd = position_usd * floor / 100.0
        fee_savings_if_wait_pct = max(0.0, current_fee_pct - floor)
        fee_savings_if_wait_usd = max(0.0, fee_now_usd - fee_at_floor_usd)
        yield_while_waiting_pct = apr_pct * days_to_floor / DAYS_PER_YEAR
        yield_while_waiting_usd = position_usd * yield_while_waiting_pct / 100.0

        score = self._score(progress, current_fee_pct, floor)
        classification = self._classify(current_fee_pct, at_floor)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            at_floor, current_fee_pct, floor, days_to_floor,
            fee_savings_if_wait_pct,
        )

        return {
            "token": token,
            "initial_withdrawal_fee_pct": round(initial, 4),
            "floor_withdrawal_fee_pct": round(floor, 4),
            "fee_decay_days": round(fee_decay_days, 4),
            "days_held": round(days_held, 4),
            "position_usd": round(position_usd, 4),
            "apr_pct": round(apr_pct, 4),
            "progress": round(progress, 4),
            "current_fee_pct": round(current_fee_pct, 4),
            "days_to_floor": round(days_to_floor, 4),
            "at_floor": at_floor,
            "fee_now_usd": round(fee_now_usd, 4),
            "fee_at_floor_usd": round(fee_at_floor_usd, 4),
            "fee_savings_if_wait_pct": round(fee_savings_if_wait_pct, 4),
            "fee_savings_if_wait_usd": round(fee_savings_if_wait_usd, 4),
            "yield_while_waiting_pct": round(yield_while_waiting_pct, 4),
            "yield_while_waiting_usd": round(yield_while_waiting_usd, 4),
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        progress: float,
        current_fee_pct: float,
        floor: float,
    ) -> float:
        """
        0–100, HIGHER = cheaper to exit now (fee matured). Components:
          decay progress (45) — how far the fee has decayed toward the floor.
          low current fee (40) — effective fee inverse of HIGH_FEE_PCT.
          low floor (15)      — a low permanent floor.
        """
        decay_progress_comp = 45.0 * _clamp(progress, 0.0, 1.0)
        low_current_fee_comp = 40.0 * _clamp(
            1.0 - current_fee_pct / HIGH_FEE_PCT, 0.0, 1.0)
        low_floor_comp = 15.0 * _clamp(1.0 - floor / HIGH_FEE_PCT, 0.0, 1.0)
        total = decay_progress_comp + low_current_fee_comp + low_floor_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, current_fee_pct: float, at_floor: bool) -> str:
        if at_floor:
            return "MATURED"
        if current_fee_pct < LOW_FEE_PCT:
            return "LOW_EXIT_FEE"
        if current_fee_pct < MODERATE_FEE_PCT:
            return "MODERATE_EXIT_FEE"
        return "HIGH_EXIT_FEE"

    def _recommend(self, classification: str) -> str:
        # INSUFFICIENT_DATA → EXIT_OK: no fee schedule means a free exit, so
        # there is nothing to wait for.
        if classification == "INSUFFICIENT_DATA":
            return "EXIT_OK"
        if classification in ("MATURED", "LOW_EXIT_FEE"):
            return "EXIT_OK"
        if classification == "MODERATE_EXIT_FEE":
            return "WAIT_FOR_DECAY"
        # HIGH_EXIT_FEE
        return "HOLD_TO_FLOOR"

    def _flags(
        self,
        at_floor: bool,
        current_fee_pct: float,
        floor: float,
        days_to_floor: float,
        fee_savings_if_wait_pct: float,
    ) -> List[str]:
        flags: List[str] = []

        if at_floor:
            flags.append("AT_FLOOR")
        if current_fee_pct > floor + LOW_FEE_PCT:
            flags.append("EARLY_WITHDRAWAL_PENALTY")
        if current_fee_pct >= MODERATE_FEE_PCT:
            flags.append("HIGH_EXIT_FEE")
        if not at_floor and days_to_floor <= NEAR_FLOOR_DAYS:
            flags.append("NEAR_FLOOR")
        if days_to_floor > LONG_RAMP_DAYS:
            flags.append("LONG_RAMP_REMAINING")
        if floor <= 0:
            flags.append("ZERO_FLOOR_FEE")
        if fee_savings_if_wait_pct > 0:
            flags.append("WAIT_SAVES_FEE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "initial_withdrawal_fee_pct": 0.0,
            "floor_withdrawal_fee_pct": 0.0,
            "fee_decay_days": 0.0,
            "days_held": 0.0,
            "position_usd": 0.0,
            "apr_pct": 0.0,
            "progress": 0.0,
            "current_fee_pct": 0.0,
            "days_to_floor": 0.0,
            "at_floor": False,
            "fee_now_usd": 0.0,
            "fee_at_floor_usd": 0.0,
            "fee_savings_if_wait_pct": 0.0,
            "fee_savings_if_wait_usd": 0.0,
            "yield_while_waiting_pct": 0.0,
            "yield_while_waiting_usd": 0.0,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "EXIT_OK",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "cheapest_to_exit_vault": None,
                "most_expensive_to_exit_vault": None,
                "avg_score": 0.0,
                "high_fee_count": 0,
                "position_count": len(results),
            }
        # Higher score = cheaper to exit now → highest score is cheapest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        high_fee = sum(
            1 for r in results
            if r["classification"] == "HIGH_EXIT_FEE")
        return {
            "cheapest_to_exit_vault": by_score[-1]["token"],
            "most_expensive_to_exit_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "high_fee_count": high_fee,
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
            "vault": "USDC-Vault-Matured",
            "initial_withdrawal_fee_pct": 3.0,
            "floor_withdrawal_fee_pct": 0.1,
            "fee_decay_days": 30.0,
            "days_held": 45.0,
            "position_usd": 10000.0,
            "apr_pct": 8.0,
        },
        {
            "vault": "ETH-Vault-FreshHighFee",
            "initial_withdrawal_fee_pct": 5.0,
            "floor_withdrawal_fee_pct": 0.5,
            "fee_decay_days": 90.0,
            "days_held": 3.0,
            "position_usd": 25000.0,
            "apr_pct": 12.0,
        },
        {
            "vault": "DAI-Vault-NoFee",
            "initial_withdrawal_fee_pct": 0.0,
            "floor_withdrawal_fee_pct": 0.0,
            "fee_decay_days": 0.0,
            "days_held": 10.0,
            "position_usd": 5000.0,
            "apr_pct": 6.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1161 Vault Withdrawal Fee Decay Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultWithdrawalFeeDecayAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
