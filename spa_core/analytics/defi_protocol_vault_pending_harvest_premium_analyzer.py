"""
MP-1158: DeFiProtocolVaultPendingHarvestPremiumAnalyzer
=======================================================
Advisory/read-only analytics module.

An auto-compounding yield vault accrues rewards that are not yet harvested and
reinvested. Until the next harvest, those pending rewards are not yet reflected
in the vault's share price (pricePerShare). When the keeper harvests, the share
price steps up by the harvested amount (net of any performance fee). A depositor
who enters NOW captures that pending step at the next harvest regardless of how
briefly they were staked.

This module quantifies the PENDING-HARVEST PREMIUM and the deposit-timing edge:
how large the pending share-price step is (gross and net of fees), how far the
vault is through its current harvest cycle, when the next harvest lands, and the
"free" yield available to a just-in-time depositor.

This isolates the *pending-harvest premium / deposit-timing edge* question — the
unrealized step pending at the next harvest, harvest-cycle progress, and the
capturable net premium for an entering depositor.

Distinct from:
  * idle_cash_drag      → it models uninvested capital and APY drag.
  * round_trip_cost     → it models deposit/withdraw round-trip cost.
  * performance-fee     → fee analyzers model ongoing fee drag on returns.
This module answers only the pending-harvest-premium / timing-edge question.

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
    "data", "vault_pending_harvest_premium_log.json"
)
LOG_CAP = 100

DEFAULT_HARVEST_INTERVAL_HOURS = 24.0   # typical cadence between harvests (h)

# Net-premium classification bands (%)
CLEAN_PREMIUM_PCT = 0.10            # net premium < 0.10% → clean entry
MINOR_PREMIUM_PCT = 0.50           # net premium < 0.50% → minor premium
MODERATE_PREMIUM_PCT = 1.50        # net premium < 1.50% → moderate premium
# net premium >= 1.50% → large premium

# Just-in-time / staleness / fee-drag flag thresholds
JIT_PREMIUM_PCT = 1.50             # net premium >= 1.5% qualifies for JIT
JIT_PROGRESS_PCT = 75.0            # harvest progress >= 75% qualifies for JIT
HIGH_PERF_FEE_PCT = 20.0           # performance fee >= 20% → high fee drag


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

class DeFiProtocolVaultPendingHarvestPremiumAnalyzer:
    """
    Analyzes the pending-harvest premium of an auto-compounding vault and the
    deposit-timing edge available to an entering depositor.

    HIGHER score = BETTER timing opportunity (larger capturable net premium and
    later in the harvest cycle → sooner payout).

    Per-position input dict fields:
        vault / token            : str
        total_tvl_usd            : float  (vault TVL / current AUM)
        pending_rewards_usd      : float  (accrued-but-unharvested, default 0)
        hours_since_last_harvest : float  (default 0)
        harvest_interval_hours   : float  (cadence between harvests, default 24)
        performance_fee_pct      : float  (fee on harvested rewards, default 0)
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
        total_tvl = _f(p.get("total_tvl_usd"))
        pending = max(0.0, _f(p.get("pending_rewards_usd")))
        hours_since = max(0.0, _f(p.get("hours_since_last_harvest")))
        interval = _f(p.get("harvest_interval_hours"), DEFAULT_HARVEST_INTERVAL_HOURS)
        if interval <= 0:
            interval = DEFAULT_HARVEST_INTERVAL_HOURS
        perf_fee = _clamp(_f(p.get("performance_fee_pct")), 0.0, 100.0)

        # Insufficient data: cannot reason about a premium without TVL.
        if total_tvl <= 0:
            return self._insufficient(token)

        # Gross pending share-price step pending at next harvest.
        pending_premium_pct = _safe_div(pending, total_tvl, 0.0) * 100.0
        # Net of performance fee (the depositor only captures the after-fee step).
        net_premium_pct = pending_premium_pct * (1.0 - perf_fee / 100.0)
        net_premium_pct = max(0.0, net_premium_pct)

        # Harvest-cycle progress and time to next harvest.
        harvest_progress_pct = _clamp(
            _safe_div(hours_since, interval, 0.0) * 100.0, 0.0, 100.0)
        hours_to_next = max(0.0, interval - hours_since)

        # A just-in-time depositor captures the full pending net premium.
        timing_edge_pct = net_premium_pct

        classification = self._classify(net_premium_pct)
        score = self._timing_score(net_premium_pct, harvest_progress_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            net_premium_pct, harvest_progress_pct, hours_since, interval,
            perf_fee, classification,
        )

        return {
            "token": token,
            "total_tvl_usd": round(total_tvl, 2),
            "pending_rewards_usd": round(pending, 2),
            "pending_premium_pct": round(pending_premium_pct, 4),
            "net_premium_pct": round(net_premium_pct, 4),
            "timing_edge_pct": round(timing_edge_pct, 4),
            "performance_fee_pct": round(perf_fee, 4),
            "harvest_interval_hours": round(interval, 4),
            "hours_since_last_harvest": round(hours_since, 4),
            "harvest_progress_pct": round(harvest_progress_pct, 4),
            "hours_to_next_harvest": round(hours_to_next, 4),
            "timing_score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _timing_score(
        self,
        net_premium_pct: float,
        harvest_progress_pct: float,
    ) -> float:
        """
        0–100, HIGHER = BETTER timing opportunity. Weighted:
          premium component (≈70, saturating toward a 2% net premium)
          + harvest-progress component (≈30, full late in the cycle).
        """
        premium_comp = 70.0 * _clamp(net_premium_pct / 2.0, 0.0, 1.0)
        timing_comp = 30.0 * _clamp(harvest_progress_pct / 100.0, 0.0, 1.0)
        return _clamp(premium_comp + timing_comp, 0.0, 100.0)

    def _classify(self, net_premium_pct: float) -> str:
        if net_premium_pct < CLEAN_PREMIUM_PCT:
            return "CLEAN"
        if net_premium_pct < MINOR_PREMIUM_PCT:
            return "MINOR_PREMIUM"
        if net_premium_pct < MODERATE_PREMIUM_PCT:
            return "MODERATE_PREMIUM"
        return "LARGE_PREMIUM"

    def _recommend(self, classification: str) -> str:
        if classification in ("LARGE_PREMIUM", "MODERATE_PREMIUM"):
            return "ENTER_BEFORE_HARVEST"
        if classification == "MINOR_PREMIUM":
            return "NEUTRAL"
        if classification == "CLEAN":
            return "NO_TIMING_EDGE"
        return "AVOID"

    def _flags(
        self,
        net_premium_pct: float,
        harvest_progress_pct: float,
        hours_since: float,
        interval: float,
        perf_fee: float,
        classification: str,
    ) -> List[str]:
        flags: List[str] = []

        if net_premium_pct >= JIT_PREMIUM_PCT and \
                harvest_progress_pct >= JIT_PROGRESS_PCT:
            flags.append("JUST_IN_TIME_OPPORTUNITY")

        if hours_since > 2.0 * interval:
            flags.append("STALE_HARVEST")

        if perf_fee >= HIGH_PERF_FEE_PCT:
            flags.append("HIGH_PERF_FEE_DRAG")

        if classification == "CLEAN":
            flags.append("CLEAN_ENTRY")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "total_tvl_usd": 0.0,
            "pending_rewards_usd": 0.0,
            "pending_premium_pct": 0.0,
            "net_premium_pct": 0.0,
            "timing_edge_pct": 0.0,
            "performance_fee_pct": 0.0,
            "harvest_interval_hours": 0.0,
            "hours_since_last_harvest": 0.0,
            "harvest_progress_pct": 0.0,
            "hours_to_next_harvest": 0.0,
            "timing_score": 0.0,
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
                "best_timing_vault": None,
                "avg_score": 0.0,
                "large_premium_count": 0,
                "position_count": len(results),
            }
        # Higher score = better timing → best is the highest score.
        by_score = sorted(scored, key=lambda r: r["timing_score"])
        avg = _mean([r["timing_score"] for r in scored])
        large = sum(1 for r in results if r["classification"] == "LARGE_PREMIUM")
        return {
            "best_timing_vault": by_score[-1]["token"],
            "avg_score": round(avg, 2),
            "large_premium_count": large,
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
                    "timing_score": r["timing_score"],
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
            "vault": "USDC-Vault-Clean",
            "total_tvl_usd": 100_000_000.0,
            "pending_rewards_usd": 20_000.0,
            "hours_since_last_harvest": 1.0,
            "harvest_interval_hours": 24.0,
            "performance_fee_pct": 10.0,
        },
        {
            "vault": "ETH-Vault-Moderate",
            "total_tvl_usd": 50_000_000.0,
            "pending_rewards_usd": 350_000.0,
            "hours_since_last_harvest": 12.0,
            "harvest_interval_hours": 24.0,
            "performance_fee_pct": 10.0,
        },
        {
            "vault": "DAI-Vault-JustInTime",
            "total_tvl_usd": 20_000_000.0,
            "pending_rewards_usd": 400_000.0,
            "hours_since_last_harvest": 22.0,
            "harvest_interval_hours": 24.0,
            "performance_fee_pct": 10.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1158 Vault Pending Harvest Premium Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultPendingHarvestPremiumAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
