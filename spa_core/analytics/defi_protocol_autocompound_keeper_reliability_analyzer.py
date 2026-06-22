"""
MP-1151: DeFiProtocolAutoCompoundKeeperReliabilityAnalyzer
==========================================================
Advisory/read-only analytics module.

For an auto-compounding vault, assess how RELIABLY the keeper / harvest
mechanism actually compounds rewards, and the resulting drag of REALIZED vs
THEORETICAL compounding APY. A vault may advertise an auto-compound APY, but if
the keeper stalls, misses harvests, or the harvest cadence is far slower than
the target, the realized APY drifts well below the theoretical figure.

This audits keeper EXECUTION reliability: harvest freshness/staleness, harvest
completion rate over a window, APY realization, and keeper centralization.

Distinct from:
  * yield_harvesting_frequency_optimizer → it computes the OPTIMAL cadence.
  * reward_claim_timing_optimizer        → it picks WHEN to claim rewards.
This module audits whether the keeper actually EXECUTES, and the staleness drag.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import os
from datetime import datetime, timezone
from typing import List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "autocompound_keeper_reliability_log.json"
)
LOG_CAP = 100

RATIO_SENTINEL_INF = 1e9       # interval ~ 0 → staleness undefined
PCT_SENTINEL_CAP = 1e9         # completion / realization undefined

# Staleness thresholds (hours_since_last / expected_interval)
STALE_RATIO = 1.5              # > this → stale
SEVERELY_STALE_RATIO = 3.0     # > this → severely stale
STALLED_RATIO = 5.0            # > this → effectively stalled

# Completion-rate thresholds (observed / expected harvests, %)
HIGH_COMPLETION_PCT = 90.0     # >= this → keeper keeping up
MISSED_HARVEST_PCT = 20.0      # missed-rate >= this → missing harvests

# APY-drag thresholds (theoretical − realized, absolute pct points)
SIGNIFICANT_APY_DRAG_PCT = 1.0

# Keeper-centralization mapping (higher = worse / more centralized)
KEEPER_CENTRALIZATION = {
    "PERMISSIONLESS": 5.0,
    "INCENTIVIZED_BOT": 20.0,
    "MULTI_KEEPER": 35.0,
    "SINGLE_KEEPER": 80.0,
    "MANUAL": 95.0,
}
DEFAULT_CENTRALIZATION = 80.0  # unknown keeper type → treat as single-keeper risk

DECENTRALIZED_KEEPERS = {"PERMISSIONLESS", "MULTI_KEEPER"}
CENTRALIZED_KEEPERS = {"SINGLE_KEEPER", "MANUAL"}

# Reliability classification thresholds (on reliability_score)
SCORE_HIGHLY_RELIABLE = 85.0
SCORE_RELIABLE = 70.0
SCORE_DEGRADED = 50.0
SCORE_UNRELIABLE = 30.0


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

class DeFiProtocolAutoCompoundKeeperReliabilityAnalyzer:
    """
    Analyzes auto-compound keeper execution reliability and staleness drag.

    Per-position input dict fields:
        token / vault                 : str
        expected_harvest_interval_hours: float  (target cadence)
        hours_since_last_harvest       : float
        observed_harvests_last_30d     : float
        expected_harvests_last_30d     : float
        keeper_type                    : str    (PERMISSIONLESS / INCENTIVIZED_BOT
                                                 / MULTI_KEEPER / SINGLE_KEEPER / MANUAL)
        theoretical_apy_pct            : float
        realized_apy_pct               : float
        harvest_incentive_pct          : float  (bounty paid to keeper, default 0)
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
        token = p.get("token", p.get("vault", "UNKNOWN"))
        interval = _f(p.get("expected_harvest_interval_hours"))
        hours_since = max(0.0, _f(p.get("hours_since_last_harvest")))
        observed = max(0.0, _f(p.get("observed_harvests_last_30d")))
        expected = max(0.0, _f(p.get("expected_harvests_last_30d")))
        keeper_type = str(p.get("keeper_type", "")).upper()
        theoretical_apy = _f(p.get("theoretical_apy_pct"))
        realized_apy = _f(p.get("realized_apy_pct"))
        incentive = max(0.0, _f(p.get("harvest_incentive_pct")))

        # Insufficient data: cannot assess cadence nor APY drag.
        if interval <= 0 and theoretical_apy <= 0:
            return self._insufficient(token)

        # ── staleness ───────────────────────────────────────────────────────────
        staleness_ratio = _safe_div(hours_since, interval, RATIO_SENTINEL_INF)
        if staleness_ratio >= RATIO_SENTINEL_INF:
            is_stale = False  # undefined cadence → don't assert stale
        else:
            is_stale = staleness_ratio > STALE_RATIO

        # ── completion rate ───────────────────────────────────────────────────────
        completion_raw = _safe_div(observed, expected, PCT_SENTINEL_CAP) * 100.0
        if completion_raw >= PCT_SENTINEL_CAP:
            completion_true = None        # unknown expected harvests
            completion_for_score = 100.0  # don't penalise when unknown
        else:
            completion_true = completion_raw
            completion_for_score = _clamp(completion_raw, 0.0, 100.0)

        if completion_true is None:
            missed_rate = 0.0
        else:
            missed_rate = max(0.0, 100.0 - completion_true)

        # ── apy drag / realization ────────────────────────────────────────────────
        apy_drag = theoretical_apy - realized_apy
        realization_raw = _safe_div(realized_apy, theoretical_apy, PCT_SENTINEL_CAP) * 100.0
        if realization_raw >= PCT_SENTINEL_CAP:
            apy_realization = None         # unknown theoretical
            realization_for_score = 100.0
        else:
            apy_realization = realization_raw
            realization_for_score = _clamp(realization_raw, 0.0, 100.0)

        centralization = KEEPER_CENTRALIZATION.get(keeper_type, DEFAULT_CENTRALIZATION)

        score = self._reliability_score(
            completion_for_score, staleness_ratio, realization_for_score, centralization,
        )
        classification = self._classify(score, staleness_ratio)
        grade = _grade_from_score(score)
        flags = self._flags(
            staleness_ratio, is_stale, completion_true, missed_rate, apy_drag,
            keeper_type, incentive, classification,
        )

        return {
            "token": token,
            "harvest_staleness_ratio": (
                None if staleness_ratio >= RATIO_SENTINEL_INF else round(staleness_ratio, 4)
            ),
            "is_stale": bool(is_stale),
            "harvest_completion_rate_pct": (
                None if completion_true is None else round(completion_true, 2)
            ),
            "missed_harvest_rate_pct": round(missed_rate, 2),
            "apy_drag_pct": round(apy_drag, 4),
            "apy_realization_pct": (
                None if apy_realization is None else round(apy_realization, 2)
            ),
            "keeper_centralization_pct": round(centralization, 2),
            "reliability_score": round(score, 2),
            "classification": classification,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _reliability_score(
        self,
        completion_for_score: float,
        staleness_ratio: float,
        realization_for_score: float,
        centralization: float,
    ) -> float:
        """
        0–100, higher = better. Weighted:
          completion rate (≈35) + freshness i.e. low staleness (≈25)
          + apy realization (≈25) + keeper decentralization (≈15).
        """
        # Completion component.
        completion = 35.0 * _clamp(completion_for_score / 100.0, 0.0, 1.0)

        # Freshness component — ratio at/below 1.0 → full; STALLED_RATIO+ → 0.
        if staleness_ratio >= RATIO_SENTINEL_INF:
            freshness = 25.0  # undefined cadence → neutral-positive
        elif staleness_ratio <= 1.0:
            freshness = 25.0
        else:
            decay = (staleness_ratio - 1.0) / (STALLED_RATIO - 1.0)
            freshness = 25.0 * _clamp(1.0 - decay, 0.0, 1.0)

        # APY realization component.
        realization = 25.0 * _clamp(realization_for_score / 100.0, 0.0, 1.0)

        # Decentralization component — invert centralization (0 best → 15).
        decentralization = 15.0 * _clamp(1.0 - centralization / 100.0, 0.0, 1.0)

        return _clamp(completion + freshness + realization + decentralization, 0.0, 100.0)

    def _classify(self, score: float, staleness_ratio: float) -> str:
        if staleness_ratio < RATIO_SENTINEL_INF and staleness_ratio > STALLED_RATIO:
            return "STALLED"
        if score >= SCORE_HIGHLY_RELIABLE:
            return "HIGHLY_RELIABLE"
        if score >= SCORE_RELIABLE:
            return "RELIABLE"
        if score >= SCORE_DEGRADED:
            return "DEGRADED"
        if score >= SCORE_UNRELIABLE:
            return "UNRELIABLE"
        return "STALLED"

    def _flags(
        self,
        staleness_ratio: float,
        is_stale: bool,
        completion_true: Optional[float],
        missed_rate: float,
        apy_drag: float,
        keeper_type: str,
        incentive: float,
        classification: str,
    ) -> List[str]:
        flags: List[str] = []

        if staleness_ratio < RATIO_SENTINEL_INF:
            if staleness_ratio > SEVERELY_STALE_RATIO:
                flags.append("SEVERELY_STALE")
            if is_stale:
                flags.append("STALE_HARVEST")
            else:
                flags.append("FRESH_HARVEST")

        if completion_true is not None and completion_true >= HIGH_COMPLETION_PCT:
            flags.append("HIGH_COMPLETION")
        if missed_rate >= MISSED_HARVEST_PCT:
            flags.append("MISSED_HARVESTS")

        if apy_drag >= SIGNIFICANT_APY_DRAG_PCT:
            flags.append("SIGNIFICANT_APY_DRAG")

        if keeper_type in CENTRALIZED_KEEPERS:
            flags.append("CENTRALIZED_KEEPER")
        if keeper_type in DECENTRALIZED_KEEPERS:
            flags.append("DECENTRALIZED_KEEPER")

        if incentive <= 0 and keeper_type != "PERMISSIONLESS":
            flags.append("NO_HARVEST_INCENTIVE")

        if classification == "STALLED":
            flags.append("STALLED")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "harvest_staleness_ratio": None,
            "is_stale": False,
            "harvest_completion_rate_pct": None,
            "missed_harvest_rate_pct": 0.0,
            "apy_drag_pct": 0.0,
            "apy_realization_pct": None,
            "keeper_centralization_pct": 0.0,
            "reliability_score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_reliable_vault": None,
                "least_reliable_vault": None,
                "avg_reliability_score": 0.0,
                "stalled_count": 0,
                "position_count": len(results),
            }
        by_score = sorted(scored, key=lambda r: r["reliability_score"])
        avg = _mean([r["reliability_score"] for r in scored])
        stalled = sum(1 for r in results if r["classification"] == "STALLED")
        return {
            "most_reliable_vault": by_score[-1]["token"],
            "least_reliable_vault": by_score[0]["token"],
            "avg_reliability_score": round(avg, 2),
            "stalled_count": stalled,
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
                    "reliability_score": r["reliability_score"],
                    "is_stale": r["is_stale"],
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
            "token": "yvUSDC",
            "expected_harvest_interval_hours": 24.0,
            "hours_since_last_harvest": 6.0,
            "observed_harvests_last_30d": 30.0,
            "expected_harvests_last_30d": 30.0,
            "keeper_type": "PERMISSIONLESS",
            "theoretical_apy_pct": 9.0,
            "realized_apy_pct": 8.8,
            "harvest_incentive_pct": 0.0,
        },
        {
            "token": "StalledVault",
            "expected_harvest_interval_hours": 24.0,
            "hours_since_last_harvest": 200.0,
            "observed_harvests_last_30d": 6.0,
            "expected_harvests_last_30d": 30.0,
            "keeper_type": "SINGLE_KEEPER",
            "theoretical_apy_pct": 12.0,
            "realized_apy_pct": 4.0,
            "harvest_incentive_pct": 0.0,
        },
        {
            "token": "ManualVault",
            "expected_harvest_interval_hours": 48.0,
            "hours_since_last_harvest": 80.0,
            "observed_harvests_last_30d": 12.0,
            "expected_harvests_last_30d": 15.0,
            "keeper_type": "MANUAL",
            "theoretical_apy_pct": 7.0,
            "realized_apy_pct": 5.5,
            "harvest_incentive_pct": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1151 Auto-Compound Keeper Reliability Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolAutoCompoundKeeperReliabilityAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
