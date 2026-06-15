"""
MP-1171: DeFiProtocolVaultMaturityTrackRecordAnalyzer
=====================================================
Advisory/read-only analytics module.

How battle-tested / proven a vault is. A freshly-launched vault (a few days
old, few harvest/epoch cycles completed, unaudited, never stress-tested)
carries higher unknown-unknown risk than one that has survived many cycles and
a market stress event. The holder weighs maturity before committing size.

Angle: "vault is 9 days old, completed 1 epoch, unaudited, never saw a
drawdown → unproven; size down or wait."

HIGHER score = more mature / proven / battle-tested.

Distinct from:
  * adapter_health_scorecard — operational health / uptime (live ops, not
    age/track-record).
  * any TVL / peg modules — capital and price stability, not maturity.
  THIS module isolates AGE + completed cycles + audit + stress-survival as a
  single maturity score.

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
    "data", "vault_maturity_track_record_log.json"
)
LOG_CAP = 100

# Scoring references (full-credit ceilings).
AGE_FULL_DAYS = 180.0       # age at/above this → full age credit
EPOCHS_FULL = 12.0          # epochs at/above this → full cycles credit
AUDIT_COUNT_FULL = 3        # audit count at/above this → full audit-count bonus

# Days per average month (Gregorian).
DAYS_PER_MONTH = 30.4375

# Maturity classification thresholds (days / epochs).
BRAND_NEW_AGE_DAYS = 14.0   # age below this → brand new / unproven driver
UNPROVEN_EPOCHS = 2.0       # epochs below this → unproven driver
EMERGING_AGE_DAYS = 60.0    # age below this → emerging driver
EMERGING_EPOCHS = 6.0       # epochs below this → emerging driver
ESTABLISHED_AGE_DAYS = 180.0  # age below this → established driver
ESTABLISHED_EPOCHS = 12.0   # epochs below this → established driver

# seasoned: age and epochs both proven.
SEASONED_AGE_DAYS = 180.0
SEASONED_EPOCHS = 12.0


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


def _maturity_label(classification: str) -> str:
    """Short human label for a maturity classification."""
    return {
        "UNPROVEN": "unproven",
        "EMERGING": "emerging",
        "ESTABLISHED": "established",
        "BATTLE_TESTED": "battle-tested",
        "INSUFFICIENT_DATA": "unknown",
    }.get(classification, "unknown")


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolVaultMaturityTrackRecordAnalyzer:
    """
    Measures how battle-tested / proven a vault is from its AGE, the number of
    harvest/reward cycles (epochs) it has successfully completed, whether it has
    been audited (and how many times), and whether it survived a market stress
    event. A freshly-launched, unaudited, never-stressed vault is unproven; one
    that has survived many cycles and a stress event is battle-tested.

    HIGHER score = more mature / proven / battle-tested.

    Per-position input dict fields:
        vault / token          : str
        vault_age_days         : float (default 0; max(0,..))
        epochs_completed       : float (default 0; max(0,..)) — harvest/reward
                                 cycles successfully completed.
        is_audited             : bool (default False)
        audit_count            : int (default 0; max(0,..))
        survived_stress_event  : bool (default False) — held through a market
                                 crash / depeg / large-withdrawal event.
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
        age_days = max(0.0, _f(p.get("vault_age_days")))
        epochs = max(0.0, _f(p.get("epochs_completed")))
        is_audited = bool(p.get("is_audited", False))
        audit_count = int(max(0.0, _f(p.get("audit_count"))))
        survived_stress = bool(p.get("survived_stress_event", False))

        # Insufficient data fast-path: no age and no completed cycles gives no
        # basis for a maturity judgement.
        if age_days <= 0 and epochs <= 0:
            return self._insufficient(token)

        age_months = _safe_div(age_days, DAYS_PER_MONTH, 0.0)
        if not math.isfinite(age_months):
            age_months = 0.0

        is_brand_new = bool(age_days < BRAND_NEW_AGE_DAYS)
        is_seasoned = bool(
            age_days >= SEASONED_AGE_DAYS and epochs >= SEASONED_EPOCHS)

        score = self._score(age_days, epochs, is_audited, audit_count,
                             survived_stress)
        classification = self._classify(age_days, epochs, survived_stress)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification,
            is_brand_new,
            is_seasoned,
            is_audited,
            survived_stress,
        )

        return {
            "token": token,
            "vault_age_days": round(age_days, 4),
            "epochs_completed": round(epochs, 4),
            "age_months": round(age_months, 4),
            "is_audited": is_audited,
            "audit_count": audit_count,
            "survived_stress_event": survived_stress,
            "maturity_label": _maturity_label(classification),
            "is_brand_new": is_brand_new,
            "is_seasoned": is_seasoned,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        age_days: float,
        epochs: float,
        is_audited: bool,
        audit_count: int,
        survived_stress: bool,
    ) -> float:
        """
        0–100, HIGHER = more mature / proven. Components:
          age (35) — age_days/AGE_FULL_DAYS clamped 0..1, × 35.
          cycles (25) — epochs/EPOCHS_FULL clamped 0..1, × 25.
          audited (20) — 20 if audited (scaled a little by audit_count up to a
            cap); 0 if unaudited.
          stress-survived (20) — 20 if it survived a stress event, else 0.
        """
        age_comp = 35.0 * _clamp(
            _safe_div(age_days, AGE_FULL_DAYS, 0.0), 0.0, 1.0)
        cycles_comp = 25.0 * _clamp(
            _safe_div(epochs, EPOCHS_FULL, 0.0), 0.0, 1.0)
        if is_audited:
            # Base 14 for being audited, scaled up to 20 by audit_count.
            count_scale = _clamp(
                _safe_div(float(audit_count), float(AUDIT_COUNT_FULL), 0.0),
                0.0, 1.0)
            audit_comp = 14.0 + 6.0 * count_scale
        else:
            audit_comp = 0.0
        stress_comp = 20.0 if survived_stress else 0.0
        total = age_comp + cycles_comp + audit_comp + stress_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(
        self,
        age_days: float,
        epochs: float,
        survived_stress: bool,
    ) -> str:
        if age_days < BRAND_NEW_AGE_DAYS or epochs < UNPROVEN_EPOCHS:
            return "UNPROVEN"
        if age_days < EMERGING_AGE_DAYS or epochs < EMERGING_EPOCHS:
            return "EMERGING"
        if (age_days < ESTABLISHED_AGE_DAYS or epochs < ESTABLISHED_EPOCHS
                or not survived_stress):
            return "ESTABLISHED"
        return "BATTLE_TESTED"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification == "BATTLE_TESTED":
            return "DEPLOY_FULL_SIZE"
        if classification == "ESTABLISHED":
            return "DEPLOY"
        if classification == "EMERGING":
            return "DEPLOY_REDUCED_SIZE"
        # UNPROVEN
        return "WAIT_OR_TINY_SIZE"

    def _flags(
        self,
        classification: str,
        is_brand_new: bool,
        is_seasoned: bool,
        is_audited: bool,
        survived_stress: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "UNPROVEN":
            flags.append("UNPROVEN")
        if classification == "EMERGING":
            flags.append("EMERGING")
        if classification == "ESTABLISHED":
            flags.append("ESTABLISHED")
        if classification == "BATTLE_TESTED":
            flags.append("BATTLE_TESTED")
        if is_brand_new:
            flags.append("BRAND_NEW")
        if is_seasoned:
            flags.append("SEASONED")
        if is_audited:
            flags.append("AUDITED")
        else:
            flags.append("UNAUDITED")
        if survived_stress:
            flags.append("SURVIVED_STRESS_EVENT")
        else:
            flags.append("NEVER_STRESS_TESTED")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "vault_age_days": 0.0,
            "epochs_completed": 0.0,
            "age_months": None,
            "is_audited": False,
            "audit_count": 0,
            "survived_stress_event": False,
            "maturity_label": _maturity_label("INSUFFICIENT_DATA"),
            "is_brand_new": False,
            "is_seasoned": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_OR_VERIFY",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_mature_vault": None,
                "least_mature_vault": None,
                "avg_score": 0.0,
                "unproven_count": 0,
                "position_count": len(results),
            }
        # Higher score = more mature → highest score is most mature.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        unproven = sum(
            1 for r in results if r["classification"] == "UNPROVEN")
        return {
            "most_mature_vault": by_score[-1]["token"],
            "least_mature_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "unproven_count": unproven,
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
            "vault": "USDC-Vault-BattleTested",
            "vault_age_days": 400.0,
            "epochs_completed": 50.0,
            "is_audited": True,
            "audit_count": 3,
            "survived_stress_event": True,
        },
        {
            "vault": "ETH-Vault-Established",
            "vault_age_days": 220.0,
            "epochs_completed": 20.0,
            "is_audited": True,
            "audit_count": 2,
            "survived_stress_event": False,
        },
        {
            "vault": "ARB-Vault-Emerging",
            "vault_age_days": 40.0,
            "epochs_completed": 4.0,
            "is_audited": True,
            "audit_count": 1,
            "survived_stress_event": False,
        },
        {
            "vault": "New-Vault-Unproven",
            "vault_age_days": 9.0,
            "epochs_completed": 1.0,
            "is_audited": False,
            "audit_count": 0,
            "survived_stress_event": False,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "vault_age_days": 0.0,
            "epochs_completed": 0.0,
            "is_audited": False,
            "audit_count": 0,
            "survived_stress_event": False,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1171 Vault Maturity Track Record Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultMaturityTrackRecordAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
