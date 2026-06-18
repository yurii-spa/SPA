"""
MP-1160: DeFiProtocolVaultStrategyMigrationRiskAnalyzer
=======================================================
Advisory/read-only analytics module.

A vault can swap the underlying yield STRATEGY contract behind the same vault
share token ("strategy migration"). Right after a migration there is elevated
risk: the new strategy contract may be freshly deployed (short track record /
unaudited), the migration may have moved a large % of TVL, it may or may not be
gated by a governance timelock, and the share price may show a discontinuity.
Frequent migrations (churn) are also a warning. This module scores how safe it
is to enter or stay in a vault given a recent/announced strategy migration.

This isolates the *migration-event* risk window — the freshness/track-record of
the new strategy, the share of TVL moved, governance gating, share-price
continuity across the migration, the settle time elapsed, and migration churn.

Distinct from:
  * vault_share_inflation_attack_exposure → first-depositor donation attack.
  * admin_key_control_risk                → standing admin privileges.
  * vault_strategy_diversification_scorer → number/spread of strategies.
This module answers only the *migration-event* risk question.

HIGHER score = SAFER.

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
    "data", "vault_strategy_migration_risk_log.json"
)
LOG_CAP = 100

SETTLE_DAYS = 14.0            # days after migration to consider it "settled"
MATURE_DAYS = 90.0           # new strategy age for full maturity credit
MIN_TIMELOCK_HOURS = 24.0    # minimum timelock to count as governance-protected
UNPROVEN_DAYS = 30.0        # new strategy younger than this is "unproven"
LARGE_TVL_PCT = 50.0        # migrated TVL share considered "large"
FREQUENT_MIGRATIONS = 3.0   # migrations in 90d at/above this is "frequent"
CONTINUITY_DROP_FLAG_PCT = 0.5  # share-price drop above this flags discontinuity


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

class DeFiProtocolVaultStrategyMigrationRiskAnalyzer:
    """
    Scores the risk window opened by a vault swapping its underlying yield
    STRATEGY contract behind the same share token (a "strategy migration").

    HIGHER score = SAFER (mature/audited/governance-gated migration that has
    settled, with continuity of share price and low churn).

    Per-position input dict fields:
        vault / token              : str
        days_since_migration       : float (default -1; <0 = no migration)
        new_strategy_age_days      : float (default 0)
        migrated_tvl_pct           : float (default 0; clamp 0..100)
        has_timelock               : bool  (default False)
        timelock_hours             : float (default 0)
        is_audited                 : bool  (default False)
        share_price_continuity_pct : float (default 100; clamp 0..100)
        migration_count_90d        : float (default 0)
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
        days_since_migration = _f(p.get("days_since_migration"), -1.0)
        new_strategy_age_days = max(0.0, _f(p.get("new_strategy_age_days")))
        migrated_tvl_pct = _clamp(_f(p.get("migrated_tvl_pct")), 0.0, 100.0)
        has_timelock = bool(p.get("has_timelock", False))
        timelock_hours = max(0.0, _f(p.get("timelock_hours")))
        is_audited = bool(p.get("is_audited", False))
        share_price_continuity_pct = _clamp(
            _f(p.get("share_price_continuity_pct"), 100.0), 0.0, 100.0)
        migration_count_90d = max(0.0, _f(p.get("migration_count_90d")))

        # Insufficient data: nothing to analyze if there's no migration event.
        if days_since_migration < 0 and migration_count_90d <= 0:
            return self._insufficient(token)

        share_price_drop_pct = max(0.0, 100.0 - share_price_continuity_pct)
        governance_protected = has_timelock and timelock_hours >= MIN_TIMELOCK_HOURS
        is_fresh = 0 <= days_since_migration < SETTLE_DAYS
        migration_churn = migration_count_90d

        score = self._score(
            new_strategy_age_days, migrated_tvl_pct, days_since_migration,
            is_audited, governance_protected, share_price_continuity_pct,
        )
        classification = self._classify(score)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, is_fresh)
        flags = self._flags(
            is_fresh, days_since_migration, new_strategy_age_days,
            migrated_tvl_pct, is_audited, governance_protected,
            share_price_drop_pct, migration_count_90d,
        )

        return {
            "token": token,
            "days_since_migration": round(days_since_migration, 4),
            "new_strategy_age_days": round(new_strategy_age_days, 4),
            "migrated_tvl_pct": round(migrated_tvl_pct, 4),
            "has_timelock": has_timelock,
            "timelock_hours": round(timelock_hours, 4),
            "is_audited": is_audited,
            "share_price_continuity_pct": round(share_price_continuity_pct, 4),
            "share_price_drop_pct": round(share_price_drop_pct, 4),
            "governance_protected": governance_protected,
            "is_fresh": is_fresh,
            "migration_churn": round(migration_churn, 4),
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        new_strategy_age_days: float,
        migrated_tvl_pct: float,
        days_since_migration: float,
        is_audited: bool,
        governance_protected: bool,
        share_price_continuity_pct: float,
    ) -> float:
        """
        0–100, HIGHER = SAFER. Weighted components:
          maturity (30)   — new strategy track record toward MATURE_DAYS.
          exposure (20)   — inverse of TVL share moved.
          settled (15)    — settle time elapsed since migration.
          audit (15)      — new strategy audited.
          governance (10) — timelock-gated migration.
          continuity (10) — share price retained across the migration.
        """
        maturity_comp = 30.0 * _clamp(
            new_strategy_age_days / MATURE_DAYS, 0.0, 1.0)
        exposure_comp = 20.0 * _clamp(1.0 - migrated_tvl_pct / 100.0, 0.0, 1.0)
        if days_since_migration < 0:
            settled_comp = 15.0
        else:
            settled_comp = 15.0 * _clamp(
                days_since_migration / SETTLE_DAYS, 0.0, 1.0)
        audit_comp = 15.0 if is_audited else 0.0
        governance_comp = 10.0 if governance_protected else 0.0
        continuity_comp = 10.0 * _clamp(
            share_price_continuity_pct / 100.0, 0.0, 1.0)
        total = (maturity_comp + exposure_comp + settled_comp + audit_comp
                 + governance_comp + continuity_comp)
        return _clamp(total, 0.0, 100.0)

    def _classify(self, score: float) -> str:
        if score >= 80:
            return "LOW_MIGRATION_RISK"
        if score >= 60:
            return "MODERATE_MIGRATION_RISK"
        if score >= 40:
            return "ELEVATED_MIGRATION_RISK"
        return "HIGH_MIGRATION_RISK"

    def _recommend(self, classification: str, is_fresh: bool) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID"
        if classification == "LOW_MIGRATION_RISK":
            return "DEPLOY"
        if classification == "MODERATE_MIGRATION_RISK":
            return "DEPLOY_CAUTIOUSLY"
        if classification == "ELEVATED_MIGRATION_RISK":
            return "WAIT_FOR_SETTLE" if is_fresh else "DEPLOY_CAUTIOUSLY"
        # HIGH_MIGRATION_RISK
        return "AVOID"

    def _flags(
        self,
        is_fresh: bool,
        days_since_migration: float,
        new_strategy_age_days: float,
        migrated_tvl_pct: float,
        is_audited: bool,
        governance_protected: bool,
        share_price_drop_pct: float,
        migration_count_90d: float,
    ) -> List[str]:
        flags: List[str] = []

        if is_fresh:
            flags.append("FRESH_MIGRATION")
        if days_since_migration >= SETTLE_DAYS:
            flags.append("SETTLED_MIGRATION")
        if new_strategy_age_days < UNPROVEN_DAYS:
            flags.append("UNPROVEN_STRATEGY")
        if new_strategy_age_days >= MATURE_DAYS:
            flags.append("MATURE_STRATEGY")
        if migrated_tvl_pct >= LARGE_TVL_PCT:
            flags.append("LARGE_TVL_MIGRATION")
        if not is_audited:
            flags.append("UNAUDITED_STRATEGY")
        else:
            flags.append("AUDITED_STRATEGY")
        if governance_protected:
            flags.append("GOVERNANCE_TIMELOCK")
        else:
            flags.append("NO_TIMELOCK")
        if share_price_drop_pct > CONTINUITY_DROP_FLAG_PCT:
            flags.append("SHARE_PRICE_DISCONTINUITY")
        if migration_count_90d >= FREQUENT_MIGRATIONS:
            flags.append("FREQUENT_MIGRATIONS")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "days_since_migration": -1.0,
            "new_strategy_age_days": 0.0,
            "migrated_tvl_pct": 0.0,
            "has_timelock": False,
            "timelock_hours": 0.0,
            "is_audited": False,
            "share_price_continuity_pct": 100.0,
            "share_price_drop_pct": 0.0,
            "governance_protected": False,
            "is_fresh": False,
            "migration_churn": 0.0,
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
                "most_risky_vault": None,
                "least_risky_vault": None,
                "avg_score": 0.0,
                "high_risk_count": 0,
                "position_count": len(results),
            }
        # Higher score = safer → lowest score is most risky.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        high_risk = sum(
            1 for r in results
            if r["classification"] == "HIGH_MIGRATION_RISK")
        return {
            "most_risky_vault": by_score[0]["token"],
            "least_risky_vault": by_score[-1]["token"],
            "avg_score": round(avg, 2),
            "high_risk_count": high_risk,
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
            "vault": "USDC-Vault-MatureMigration",
            "days_since_migration": 45.0,
            "new_strategy_age_days": 120.0,
            "migrated_tvl_pct": 20.0,
            "has_timelock": True,
            "timelock_hours": 48.0,
            "is_audited": True,
            "share_price_continuity_pct": 100.0,
            "migration_count_90d": 1.0,
        },
        {
            "vault": "ETH-Vault-FreshRisky",
            "days_since_migration": 2.0,
            "new_strategy_age_days": 5.0,
            "migrated_tvl_pct": 80.0,
            "has_timelock": False,
            "timelock_hours": 0.0,
            "is_audited": False,
            "share_price_continuity_pct": 97.0,
            "migration_count_90d": 4.0,
        },
        {
            "vault": "DAI-Vault-NoMigration",
            "days_since_migration": -1.0,
            "new_strategy_age_days": 0.0,
            "migrated_tvl_pct": 0.0,
            "has_timelock": False,
            "timelock_hours": 0.0,
            "is_audited": False,
            "share_price_continuity_pct": 100.0,
            "migration_count_90d": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1160 Vault Strategy Migration Risk Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultStrategyMigrationRiskAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
