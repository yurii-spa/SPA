"""
MP-1183: DeFiProtocolVaultUnclaimedRewardForfeitureAnalyzer
===========================================================
Advisory/read-only analytics module.

Accrued-but-unclaimed rewards can be subject to a claim window / deadline; if
not claimed before the window closes they are (partially or fully) FORFEITED.
This measures the FORFEITURE RISK of sitting on unclaimed rewards given the time
remaining until the deadline versus how often you actually claim.

Angle: "$500 of unclaimed rewards, the claim window closes in 24h but you only
claim every 168h → you will almost certainly miss the deadline and forfeit them
→ claim now."

HIGHER score = safer (low forfeiture risk).

Distinct from:
  * defi_protocol_reward_claim_timing_optimizer (MP-1144) — weighs claim GAS
    cost against holding volatility / opportunity cost; there is NO hard
    deadline, it optimises WHEN to claim for net value.
  THIS module models a HARD expiry deadline + forfeiture — the risk that an
  unclaimed reward is lost entirely because the claim window closes before you
  get to it.

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
    "data", "vault_unclaimed_reward_forfeiture_log.json"
)
LOG_CAP = 100

# Default claim cadence (hours) when none / non-positive supplied.
DEFAULT_CLAIM_CADENCE_HOURS = 168.0

# urgency_ratio classification thresholds.
SAFE_RATIO = 0.5      # ratio at/below this → safe
WATCH_RATIO = 1.0     # ratio at/below this → watch
ATRISK_RATIO = 2.0    # ratio at/below this → at risk; above → critical

# Large-forfeit-at-risk flag threshold (expected_forfeit_usd).
LARGE_FORFEIT_USD = 100.0

# Cap on urgency_ratio to keep it finite.
URGENCY_RATIO_CAP = 100.0

# Scoring reference: expected_forfeit_pct ceiling for the size component.
FORFEIT_PCT_CEILING = 100.0

# Score floor for an already-expired position with no realistic recovery.
EXPIRED_SCORE = 1.0


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


def _safe_div(num: float, den: float, sentinel):
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

class DeFiProtocolVaultUnclaimedRewardForfeitureAnalyzer:
    """
    Measures the FORFEITURE RISK of unclaimed rewards under a hard claim
    deadline. The urgency_ratio = claim_cadence_hours / hours_to_deadline; when
    the cadence is longer than the time remaining (ratio > 1) you are likely to
    miss the window. A monotonic miss_probability maps the urgency to a
    0..1 chance of missing; the expected forfeiture is the unclaimed amount ×
    forfeit_fraction × miss_probability. The result quantifies the risk; it does
    not claim on your behalf.

    HIGHER score = safer (low forfeiture risk).

    Per-position input dict fields:
        vault / token         : str
        unclaimed_reward_usd  : float; <=0 → INSUFFICIENT_DATA.
        hours_to_deadline     : float (max(0,..)) — time until the claim window
                                closes; 0 → already at/over the deadline (max
                                risk). Non-finite treated as 0.
        claim_cadence_hours   : float (max(0,..); default 168.0) — how often
                                rewards are actually claimed; <=0 → default.
        forfeit_fraction      : float (default 1.0; clamp [0,1]) — fraction of
                                the unclaimed amount lost if the deadline missed.
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
        unclaimed = _f(p.get("unclaimed_reward_usd"))

        # Insufficient data fast-path: a non-positive unclaimed amount gives no
        # forfeiture to judge.
        if unclaimed <= 0 or not math.isfinite(unclaimed):
            return self._insufficient(token)

        hours_to_deadline = max(0.0, _f(p.get("hours_to_deadline")))
        if not math.isfinite(hours_to_deadline):
            hours_to_deadline = 0.0

        cadence = max(
            0.0, _f(p.get("claim_cadence_hours"),
                    DEFAULT_CLAIM_CADENCE_HOURS))
        if cadence <= 0 or not math.isfinite(cadence):
            cadence = DEFAULT_CLAIM_CADENCE_HOURS

        forfeit_fraction = _clamp(_f(p.get("forfeit_fraction"), 1.0), 0.0, 1.0)
        if not math.isfinite(forfeit_fraction):
            forfeit_fraction = 1.0

        expired = bool(hours_to_deadline <= 0)

        # urgency_ratio = cadence / hours_to_deadline; expired → cap (max risk).
        if expired:
            urgency_ratio = URGENCY_RATIO_CAP
        else:
            urgency_ratio = _safe_div(cadence, hours_to_deadline, None)
            if urgency_ratio is None or not math.isfinite(urgency_ratio):
                urgency_ratio = URGENCY_RATIO_CAP
        urgency_ratio = _clamp(urgency_ratio, 0.0, URGENCY_RATIO_CAP)

        # miss_probability (0..1): monotonic in urgency_ratio.
        # For ratio in [0,1] it rises linearly as min(1, ratio); above 1 it is
        # already at the maximum 1.0 (cadence longer than remaining time).
        miss_probability = _clamp(urgency_ratio, 0.0, 1.0)

        expected_forfeit_usd = unclaimed * forfeit_fraction * miss_probability
        if not math.isfinite(expected_forfeit_usd):
            expected_forfeit_usd = 0.0

        expected_forfeit_pct = _safe_div(
            expected_forfeit_usd, unclaimed, 0.0) * 100.0
        if not math.isfinite(expected_forfeit_pct):
            expected_forfeit_pct = 0.0
        expected_forfeit_pct = _clamp(expected_forfeit_pct, 0.0, 100.0)

        high_miss = bool(miss_probability >= 0.5)
        large_forfeit = bool(expected_forfeit_usd >= LARGE_FORFEIT_USD)

        score = self._score(
            miss_probability, expected_forfeit_pct, expired)
        classification = self._classify(urgency_ratio, expired)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification, expired, high_miss, large_forfeit)

        return {
            "token": token,
            "unclaimed_reward_usd": round(unclaimed, 4),
            "hours_to_deadline": round(hours_to_deadline, 4),
            "claim_cadence_hours": round(cadence, 4),
            "forfeit_fraction": round(forfeit_fraction, 4),
            "urgency_ratio": round(urgency_ratio, 4),
            "is_expired": expired,
            "miss_probability": round(miss_probability, 4),
            "expected_forfeit_usd": round(expected_forfeit_usd, 4),
            "expected_forfeit_pct": round(expected_forfeit_pct, 4),
            "high_miss_probability": high_miss,
            "large_forfeit": large_forfeit,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        miss_probability: float,
        expected_forfeit_pct: float,
        expired: bool,
    ) -> float:
        """
        0–100, HIGHER = safer (low forfeiture risk). Components:
          safety (70) — 70 × (1 - miss_probability); full 70 when there is no
            chance of missing the deadline.
          size (30) — 30 × (1 - clamp(expected_forfeit_pct/FORFEIT_PCT_CEILING,
            0, 1)); full 30 when the expected forfeiture is negligible.
        An already-expired position with no realistic recovery → EXPIRED_SCORE
        (a very low floor) regardless of the components.
        """
        if expired:
            return EXPIRED_SCORE

        safety_comp = 70.0 * (1.0 - _clamp(miss_probability, 0.0, 1.0))
        size_frac = _clamp(
            expected_forfeit_pct / FORFEIT_PCT_CEILING, 0.0, 1.0)
        size_comp = 30.0 * (1.0 - size_frac)

        total = safety_comp + size_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, urgency_ratio: float, expired: bool) -> str:
        if expired:
            return "EXPIRED"
        if urgency_ratio <= SAFE_RATIO:
            return "SAFE"
        if urgency_ratio <= WATCH_RATIO:
            return "WATCH"
        if urgency_ratio <= ATRISK_RATIO:
            return "AT_RISK"
        return "CRITICAL"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if classification == "SAFE":
            return "NO_ACTION"
        if classification == "WATCH":
            return "SCHEDULE_CLAIM"
        if classification == "AT_RISK":
            return "CLAIM_SOON"
        if classification == "CRITICAL":
            return "CLAIM_NOW"
        # EXPIRED
        return "DEADLINE_PASSED_VERIFY"

    def _flags(
        self,
        classification: str,
        expired: bool,
        high_miss: bool,
        large_forfeit: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "SAFE":
            flags.append("SAFE")
        if classification == "WATCH":
            flags.append("WATCH")
        if classification == "AT_RISK":
            flags.append("AT_RISK")
        if classification == "CRITICAL":
            flags.append("CRITICAL")
        if classification == "EXPIRED":
            flags.append("EXPIRED")
        elif expired:
            flags.append("EXPIRED")
        if high_miss:
            flags.append("HIGH_MISS_PROBABILITY")
        if large_forfeit:
            flags.append("LARGE_FORFEIT_AT_RISK")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "unclaimed_reward_usd": 0.0,
            "hours_to_deadline": 0.0,
            "claim_cadence_hours": round(DEFAULT_CLAIM_CADENCE_HOURS, 4),
            "forfeit_fraction": 1.0,
            "urgency_ratio": None,
            "is_expired": False,
            "miss_probability": None,
            "expected_forfeit_usd": None,
            "expected_forfeit_pct": None,
            "high_miss_probability": False,
            "large_forfeit": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results
                  if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "safest_vault": None,
                "most_at_risk_vault": None,
                "avg_score": 0.0,
                "critical_count": 0,
                "total_expected_forfeit_usd": 0.0,
                "position_count": len(results),
            }
        # Higher score = safer → highest score is the safest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        critical = sum(
            1 for r in results
            if r["classification"] == "CRITICAL")
        total_forfeit = sum(
            r["expected_forfeit_usd"] for r in scored
            if isinstance(r["expected_forfeit_usd"], (int, float)))
        return {
            "safest_vault": by_score[-1]["token"],
            "most_at_risk_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "critical_count": critical,
            "total_expected_forfeit_usd": round(total_forfeit, 4),
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
            "vault": "USDC-Vault-Safe",
            "unclaimed_reward_usd": 50.0,
            "hours_to_deadline": 720.0,
            "claim_cadence_hours": 168.0,
            "forfeit_fraction": 1.0,
        },
        {
            "vault": "ETH-Vault-Watch",
            "unclaimed_reward_usd": 80.0,
            "hours_to_deadline": 200.0,
            "claim_cadence_hours": 168.0,
            "forfeit_fraction": 1.0,
        },
        {
            "vault": "ARB-Vault-AtRisk",
            "unclaimed_reward_usd": 120.0,
            "hours_to_deadline": 120.0,
            "claim_cadence_hours": 168.0,
            "forfeit_fraction": 1.0,
        },
        {
            "vault": "CRV-Vault-Critical",
            "unclaimed_reward_usd": 300.0,
            "hours_to_deadline": 24.0,
            "claim_cadence_hours": 168.0,
            "forfeit_fraction": 1.0,
        },
        {
            "vault": "CVX-Vault-Expired",
            "unclaimed_reward_usd": 200.0,
            "hours_to_deadline": 0.0,
            "claim_cadence_hours": 168.0,
            "forfeit_fraction": 1.0,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "unclaimed_reward_usd": 0.0,
            "hours_to_deadline": 100.0,
            "claim_cadence_hours": 168.0,
            "forfeit_fraction": 1.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1183 Vault Unclaimed Reward Forfeiture Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultUnclaimedRewardForfeitureAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
