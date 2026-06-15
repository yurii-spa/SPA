"""
MP-1162: DeFiProtocolVaultRewardLockDiscountAnalyzer
====================================================
Advisory/read-only analytics module.

A vault advertises an APR, but pays part of the yield in a LOCKED / VESTING
reward token (esTOKEN-style). The locked portion is worth less than face value:
it suffers a present-value time-discount over the lock period, and is partly
already vested/liquid. This module computes the liquid-equivalent APR after the
haircut — i.e. what the headline APR is really worth once the locked reward
token is discounted to present value.

It isolates the *present-value haircut* of the still-locked reward portion of a
vault's own APR.

Distinct from:
  * token_vesting_overhang → market unlock/sell pressure on a token.
  * reward_emission_decay  → emission tapering over time.
This module answers only the *present-value haircut of the locked reward share*
of a vault's APR.

HIGHER score = more of the yield is liquid/durable.

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
    "data", "vault_reward_lock_discount_log.json"
)
LOG_CAP = 100

HIGH_HAIRCUT_SHARE_PCT = 25.0   # haircut share at/above this is "significant"
LONG_LOCK_DAYS = 365.0          # lock at/above this is "long"
HIGH_PENALTY_PCT = 50.0         # early-unlock penalty at/above this is "high"
DAYS_PER_YEAR = 365.0

MOSTLY_LIQUID_SHARE = 10.0      # locked-share band: mostly liquid
MODERATE_LOCK_SHARE = 35.0      # locked-share band: moderate lock
HEAVY_LOCK_SHARE = 70.0         # locked-share band: heavy lock


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

class DeFiProtocolVaultRewardLockDiscountAnalyzer:
    """
    Models the PRESENT-VALUE haircut of a vault's locked reward token. The
    headline APR is split into a base (liquid) APR and a reward APR paid in a
    locked/vesting token. The locked reward is discounted to present value over
    the lock period; the already-vested portion is liquid. The result is the
    liquid-equivalent APR after the haircut.

    HIGHER score = more of the yield is liquid/durable.

    Per-position input dict fields:
        vault / token             : str
        base_apr_pct              : float (default 0; max(0,..))
        reward_apr_pct            : float (default 0; max(0,..); locked token)
        lock_days                 : float (default 0; max(0,..))
        discount_rate_pct         : float (default 30; max(0,..); annual PV cost)
        early_unlock_penalty_pct  : float (default 0; clamp 0..100)
        already_vested_pct        : float (default 0; clamp 0..100)
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
        base_apr = max(0.0, _f(p.get("base_apr_pct")))
        reward_apr = max(0.0, _f(p.get("reward_apr_pct")))
        lock_days = max(0.0, _f(p.get("lock_days")))
        discount_rate_pct = max(0.0, _f(p.get("discount_rate_pct"), 30.0))
        early_unlock_penalty_pct = _clamp(
            _f(p.get("early_unlock_penalty_pct")), 0.0, 100.0)
        already_vested_pct = _clamp(
            _f(p.get("already_vested_pct")), 0.0, 100.0)

        # Insufficient data: no yield at all → nothing to analyze.
        if base_apr <= 0 and reward_apr <= 0:
            return self._insufficient(token)

        headline_apr_pct = base_apr + reward_apr
        vested_reward_apr_pct = reward_apr * already_vested_pct / 100.0
        locked_reward_apr_pct = reward_apr * (1.0 - already_vested_pct / 100.0)

        lock_years = lock_days / DAYS_PER_YEAR
        # Present-value factor in (0, 1]; equals 1.0 when lock_days == 0.
        # Guard against overflow on extreme inputs: an unbounded discount over a
        # long lock drives the PV factor toward 0, so fall back to 0.0 (and
        # clamp to (0, 1] so float artifacts never escape the valid range).
        try:
            pv_factor = 1.0 / ((1.0 + discount_rate_pct / 100.0) ** lock_years)
        except (OverflowError, ZeroDivisionError, ValueError):
            pv_factor = 0.0
        if not math.isfinite(pv_factor):
            pv_factor = 0.0
        pv_factor = _clamp(pv_factor, 0.0, 1.0)

        discounted_reward_apr_pct = (
            vested_reward_apr_pct + locked_reward_apr_pct * pv_factor)
        liquid_equivalent_apr_pct = base_apr + discounted_reward_apr_pct
        apr_haircut_pct = max(0.0, headline_apr_pct - liquid_equivalent_apr_pct)
        haircut_share_pct = _safe_div(
            apr_haircut_pct, headline_apr_pct, 0.0) * 100.0

        liquid_yield_apr_pct = base_apr + vested_reward_apr_pct
        liquid_yield_share_pct = _clamp(
            _safe_div(liquid_yield_apr_pct, headline_apr_pct, 0.0) * 100.0,
            0.0, 100.0)
        locked_share_pct = _clamp(100.0 - liquid_yield_share_pct, 0.0, 100.0)

        penalty_cost_apr_pct = (
            locked_reward_apr_pct * early_unlock_penalty_pct / 100.0)

        score = self._score(
            liquid_equivalent_apr_pct, headline_apr_pct, lock_days,
            early_unlock_penalty_pct, already_vested_pct)
        classification = self._classify(locked_share_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            locked_share_pct, haircut_share_pct, lock_days,
            early_unlock_penalty_pct, liquid_yield_apr_pct, already_vested_pct)

        return {
            "token": token,
            "base_apr_pct": round(base_apr, 4),
            "reward_apr_pct": round(reward_apr, 4),
            "lock_days": round(lock_days, 4),
            "discount_rate_pct": round(discount_rate_pct, 4),
            "early_unlock_penalty_pct": round(early_unlock_penalty_pct, 4),
            "already_vested_pct": round(already_vested_pct, 4),
            "headline_apr_pct": round(headline_apr_pct, 4),
            "vested_reward_apr_pct": round(vested_reward_apr_pct, 4),
            "locked_reward_apr_pct": round(locked_reward_apr_pct, 4),
            "pv_factor": round(pv_factor, 6),
            "discounted_reward_apr_pct": round(discounted_reward_apr_pct, 4),
            "liquid_equivalent_apr_pct": round(liquid_equivalent_apr_pct, 4),
            "apr_haircut_pct": round(apr_haircut_pct, 4),
            "haircut_share_pct": round(haircut_share_pct, 4),
            "liquid_yield_apr_pct": round(liquid_yield_apr_pct, 4),
            "liquid_yield_share_pct": round(liquid_yield_share_pct, 4),
            "locked_share_pct": round(locked_share_pct, 4),
            "penalty_cost_apr_pct": round(penalty_cost_apr_pct, 4),
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        liquid_equivalent_apr_pct: float,
        headline_apr_pct: float,
        lock_days: float,
        early_unlock_penalty_pct: float,
        already_vested_pct: float,
    ) -> float:
        """
        0–100, HIGHER = more of the yield is liquid/durable. Components:
          liquid share (50)  — liquid-equivalent APR as a fraction of headline.
          low lock (25)      — shorter lock relative to one year.
          low penalty (15)   — lower early-unlock penalty.
          vested (10)        — more of the reward already vested.
        """
        liquid_share_comp = 50.0 * _clamp(
            _safe_div(liquid_equivalent_apr_pct, headline_apr_pct, 0.0),
            0.0, 1.0)
        low_lock_comp = 25.0 * _clamp(
            1.0 - lock_days / DAYS_PER_YEAR, 0.0, 1.0)
        low_penalty_comp = 15.0 * _clamp(
            1.0 - early_unlock_penalty_pct / 100.0, 0.0, 1.0)
        vested_comp = 10.0 * _clamp(already_vested_pct / 100.0, 0.0, 1.0)
        total = (
            liquid_share_comp + low_lock_comp + low_penalty_comp + vested_comp)
        return _clamp(total, 0.0, 100.0)

    def _classify(self, locked_share_pct: float) -> str:
        if locked_share_pct <= MOSTLY_LIQUID_SHARE:
            return "MOSTLY_LIQUID"
        if locked_share_pct <= MODERATE_LOCK_SHARE:
            return "MODERATE_LOCK"
        if locked_share_pct <= HEAVY_LOCK_SHARE:
            return "HEAVY_LOCK"
        return "FULLY_LOCKED"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID"
        if classification == "MOSTLY_LIQUID":
            return "DEPLOY"
        if classification == "MODERATE_LOCK":
            return "DEPLOY_CAUTIOUSLY"
        if classification == "HEAVY_LOCK":
            return "DISCOUNT_THE_APR"
        # FULLY_LOCKED
        return "AVOID"

    def _flags(
        self,
        locked_share_pct: float,
        haircut_share_pct: float,
        lock_days: float,
        early_unlock_penalty_pct: float,
        liquid_yield_apr_pct: float,
        already_vested_pct: float,
    ) -> List[str]:
        flags: List[str] = []

        if locked_share_pct <= MOSTLY_LIQUID_SHARE:
            flags.append("MOSTLY_LIQUID_YIELD")
        if haircut_share_pct >= HIGH_HAIRCUT_SHARE_PCT:
            flags.append("SIGNIFICANT_LOCK_HAIRCUT")
        if lock_days >= LONG_LOCK_DAYS:
            flags.append("LONG_LOCK")
        if early_unlock_penalty_pct > 0:
            flags.append("EARLY_UNLOCK_PENALTY")
        if early_unlock_penalty_pct >= HIGH_PENALTY_PCT:
            flags.append("HIGH_UNLOCK_PENALTY")
        if liquid_yield_apr_pct <= 0:
            flags.append("NO_LIQUID_YIELD")
        if 0 < already_vested_pct < 100:
            flags.append("PARTIALLY_VESTED")
        if already_vested_pct >= 100:
            flags.append("FULLY_VESTED")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "base_apr_pct": 0.0,
            "reward_apr_pct": 0.0,
            "lock_days": 0.0,
            "discount_rate_pct": 0.0,
            "early_unlock_penalty_pct": 0.0,
            "already_vested_pct": 0.0,
            "headline_apr_pct": 0.0,
            "vested_reward_apr_pct": 0.0,
            "locked_reward_apr_pct": 0.0,
            "pv_factor": 0.0,
            "discounted_reward_apr_pct": 0.0,
            "liquid_equivalent_apr_pct": 0.0,
            "apr_haircut_pct": 0.0,
            "haircut_share_pct": 0.0,
            "liquid_yield_apr_pct": 0.0,
            "liquid_yield_share_pct": 0.0,
            "locked_share_pct": 0.0,
            "penalty_cost_apr_pct": 0.0,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_liquid_vault": None,
                "least_liquid_vault": None,
                "avg_score": 0.0,
                "heavy_lock_count": 0,
                "position_count": len(results),
            }
        # Higher score = more liquid/durable → highest score is most liquid.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        heavy_lock = sum(
            1 for r in results
            if r["classification"] in ("HEAVY_LOCK", "FULLY_LOCKED"))
        return {
            "most_liquid_vault": by_score[-1]["token"],
            "least_liquid_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "heavy_lock_count": heavy_lock,
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
            "vault": "USDC-Vault-MostlyLiquid",
            "base_apr_pct": 4.0,
            "reward_apr_pct": 1.0,
            "lock_days": 0.0,
            "discount_rate_pct": 30.0,
            "early_unlock_penalty_pct": 0.0,
            "already_vested_pct": 100.0,
        },
        {
            "vault": "GMX-Vault-HeavyLock",
            "base_apr_pct": 2.0,
            "reward_apr_pct": 18.0,
            "lock_days": 365.0,
            "discount_rate_pct": 30.0,
            "early_unlock_penalty_pct": 50.0,
            "already_vested_pct": 0.0,
        },
        {
            "vault": "DAI-Vault-NoYield",
            "base_apr_pct": 0.0,
            "reward_apr_pct": 0.0,
            "lock_days": 0.0,
            "discount_rate_pct": 30.0,
            "early_unlock_penalty_pct": 0.0,
            "already_vested_pct": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1162 Vault Reward Lock Discount Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultRewardLockDiscountAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
