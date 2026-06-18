"""
MP-1173: DeFiProtocolVaultHarvestCycleEntryTimingAnalyzer
=========================================================
Advisory/read-only analytics module.

For a holder about to DEPOSIT, advises WHERE in the vault's harvest /
distribution cycle they are entering. Entering just after a harvest gives the
cleanest cost basis: the share price has just been reset and no large
accrued-but-unharvested yield is baked in. Entering late in the cycle means
buying into a large pending yield stake that other (earlier) depositors will
share. A `snapshot_gated` distribution flips the optimal timing: there you want
to be IN before the snapshot, so depositing near/at the end of the cycle is
correct.

Angle: "you are 88% through a 24h cycle with 1.6% pending yield accrued → you'd
be buying into a fat pending stake; wait ~3h for the harvest to reset the basis."

HIGHER score = cleaner / better-timed entry.

Distinct from:
  * defi_protocol_vault_pending_harvest_premium_analyzer — values the premium
    already baked into the share price; THIS module gives an actionable
    WAIT vs DEPOSIT_NOW entry-timing call from the cycle position.
  * protocol_defi_yield_farming_exit_timing_advisor — exit timing, not entry.

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
    "data", "vault_harvest_cycle_entry_timing_log.json"
)
LOG_CAP = 100

# Cycle-position classification thresholds (% through the cycle).
EARLY_PCT = 15.0    # at/below this → just harvested / optimal entry
MID_PCT = 50.0      # at/below this → still a good entry
LATE_PCT = 85.0     # at/below this → late cycle; above → pre-harvest

# Pending-yield references.
PENDING_CEILING_PCT = 2.0   # pending yield at/above this → full pending weight
PENDING_HIGH_PCT = 1.0      # pending yield at/above this → high-pending flag

# A cycle is "near harvest" when within this fraction of its end.
NEAR_HARVEST_FRACTION = 0.10


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

class DeFiProtocolVaultHarvestCycleEntryTimingAnalyzer:
    """
    Advises a prospective depositor where in the vault's harvest / distribution
    cycle they are entering. Combines the cycle position (how far through the
    interval) with the pending accrued-but-unharvested yield to score entry
    cleanliness. A snapshot-gated distribution flips the optimal timing — there
    the holder wants to be in before the snapshot — which is reflected in the
    recommendation and flags (but not the score).

    HIGHER score = cleaner / better-timed entry.

    Per-position input dict fields:
        vault / token            : str
        harvest_interval_hours   : float (max(0,..)); <=0 → INSUFFICIENT.
        hours_since_last_harvest : float (default 0; max(0,..)).
        pending_yield_pct        : float (default 0; max(0,..)) — accrued-but-
                                   unharvested yield as % of NAV.
        snapshot_gated           : bool (default False).
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
        harvest_interval = max(0.0, _f(p.get("harvest_interval_hours")))

        # Insufficient data fast-path: no cycle length gives no basis for a
        # cycle-position judgement.
        if harvest_interval <= 0:
            return self._insufficient(token)

        hours_since = max(0.0, _f(p.get("hours_since_last_harvest")))
        pending_yield_pct = max(0.0, _f(p.get("pending_yield_pct")))
        snapshot_gated = bool(p.get("snapshot_gated", False))

        cycle_position_pct = _clamp(
            _safe_div(hours_since, harvest_interval, 0.0), 0.0, 1.0) * 100.0
        hours_to_next_harvest = max(0.0, harvest_interval - hours_since)
        is_overdue = hours_since >= harvest_interval
        near_harvest = (
            hours_to_next_harvest <= harvest_interval * NEAR_HARVEST_FRACTION)
        just_harvested = cycle_position_pct <= EARLY_PCT

        score = self._score(cycle_position_pct, pending_yield_pct)
        classification = self._classify(cycle_position_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(
            classification, snapshot_gated, near_harvest)
        flags = self._flags(
            classification,
            just_harvested,
            near_harvest,
            is_overdue,
            snapshot_gated,
            pending_yield_pct,
        )

        return {
            "token": token,
            "harvest_interval_hours": round(harvest_interval, 4),
            "hours_since_last_harvest": round(hours_since, 4),
            "pending_yield_pct": round(pending_yield_pct, 4),
            "cycle_position_pct": round(cycle_position_pct, 4),
            "hours_to_next_harvest": round(hours_to_next_harvest, 4),
            "is_overdue": is_overdue,
            "near_harvest": near_harvest,
            "just_harvested": just_harvested,
            "snapshot_gated": snapshot_gated,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        cycle_position_pct: float,
        pending_yield_pct: float,
    ) -> float:
        """
        0–100, HIGHER = better entry timing. Single axis = entry cleanliness:
          cycle (60) — earlier in the cycle is cleaner; full credit at the
            start, zero at the end.
          pending (40) — a large pending stake only hurts when you enter late,
            so the penalty scales by BOTH the pending size and the cycle
            position. (snapshot_gated does NOT change the score.)
        """
        cyc = _clamp(cycle_position_pct / 100.0, 0.0, 1.0)
        cycle_comp = 60.0 * (1.0 - cyc)
        pend = _clamp(pending_yield_pct / PENDING_CEILING_PCT, 0.0, 1.0)
        pending_comp = 40.0 * (1.0 - pend * cyc)
        total = cycle_comp + pending_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, cycle_position_pct: float) -> str:
        if cycle_position_pct <= EARLY_PCT:
            return "OPTIMAL_ENTRY"
        if cycle_position_pct <= MID_PCT:
            return "GOOD_ENTRY"
        if cycle_position_pct <= LATE_PCT:
            return "LATE_CYCLE"
        return "PRE_HARVEST"

    def _recommend(
        self,
        classification: str,
        snapshot_gated: bool,
        near_harvest: bool,
    ) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if snapshot_gated and (
                classification == "PRE_HARVEST" or near_harvest):
            return "DEPOSIT_NOW_FOR_SNAPSHOT"
        if classification == "OPTIMAL_ENTRY":
            return "DEPOSIT_NOW"
        if classification == "GOOD_ENTRY":
            return "DEPOSIT_NOW"
        if classification == "LATE_CYCLE":
            return "CONSIDER_WAIT"
        # PRE_HARVEST
        return "WAIT_FOR_HARVEST"

    def _flags(
        self,
        classification: str,
        just_harvested: bool,
        near_harvest: bool,
        is_overdue: bool,
        snapshot_gated: bool,
        pending_yield_pct: float,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "OPTIMAL_ENTRY":
            flags.append("OPTIMAL_ENTRY")
        if classification == "GOOD_ENTRY":
            flags.append("GOOD_ENTRY")
        if classification == "LATE_CYCLE":
            flags.append("LATE_CYCLE")
        if classification == "PRE_HARVEST":
            flags.append("PRE_HARVEST")
        if just_harvested:
            flags.append("JUST_HARVESTED")
        if near_harvest:
            flags.append("NEAR_HARVEST")
        if is_overdue:
            flags.append("HARVEST_OVERDUE")
        if snapshot_gated:
            flags.append("SNAPSHOT_GATED")
        if pending_yield_pct >= PENDING_HIGH_PCT:
            flags.append("HIGH_PENDING_STAKE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "harvest_interval_hours": 0.0,
            "hours_since_last_harvest": 0.0,
            "pending_yield_pct": 0.0,
            "cycle_position_pct": 0.0,
            "hours_to_next_harvest": 0.0,
            "is_overdue": False,
            "near_harvest": False,
            "just_harvested": False,
            "snapshot_gated": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "best_entry_vault": None,
                "worst_entry_vault": None,
                "avg_score": 0.0,
                "pre_harvest_count": 0,
                "position_count": len(results),
            }
        # Higher score = better entry → highest score is best entry.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        pre_harvest = sum(
            1 for r in results if r["classification"] == "PRE_HARVEST")
        return {
            "best_entry_vault": by_score[-1]["token"],
            "worst_entry_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "pre_harvest_count": pre_harvest,
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
            "vault": "USDC-Vault-JustHarvested",
            "harvest_interval_hours": 24.0,
            "hours_since_last_harvest": 2.0,
            "pending_yield_pct": 0.1,
            "snapshot_gated": False,
        },
        {
            "vault": "ETH-Vault-GoodEntry",
            "harvest_interval_hours": 24.0,
            "hours_since_last_harvest": 9.0,
            "pending_yield_pct": 0.4,
            "snapshot_gated": False,
        },
        {
            "vault": "ARB-Vault-LateCycle",
            "harvest_interval_hours": 24.0,
            "hours_since_last_harvest": 16.0,
            "pending_yield_pct": 1.2,
            "snapshot_gated": False,
        },
        {
            "vault": "OP-Vault-PreHarvest",
            "harvest_interval_hours": 24.0,
            "hours_since_last_harvest": 23.0,
            "pending_yield_pct": 1.8,
            "snapshot_gated": False,
        },
        {
            "vault": "GMX-Vault-SnapshotGated",
            "harvest_interval_hours": 168.0,
            "hours_since_last_harvest": 160.0,
            "pending_yield_pct": 1.5,
            "snapshot_gated": True,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "harvest_interval_hours": 0.0,
            "hours_since_last_harvest": 0.0,
            "pending_yield_pct": 0.0,
            "snapshot_gated": False,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1173 Vault Harvest Cycle Entry Timing Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultHarvestCycleEntryTimingAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
