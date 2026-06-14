"""
MP-1154: DeFiProtocolDepositCapHeadroomAnalyzer
===============================================
Advisory/read-only analytics module.

Given a vault's deposit-cap economics, compute how close the vault is to its
DEPOSIT CAP (the hard or soft ceiling on total deposits) and what that implies
for entering at a desired size. In other words: "can I actually deploy the size
I want into this vault, and if the cap was recently raised and fresh TVL is
rushing in, how much will that dilute the headline APY?"

This isolates the *deposit-cap headroom / capacity-to-enter* question — how much
room is left under the cap, whether the intended deposit fits, how fast the cap
is filling at the current inflow, and how much pro-rata APY dilution the fresh
inflow implies.

Distinct from:
  * tvl_growth / inflow monitors  → they track TVL trajectory generically.
  * exit_liquidity analyzers      → they model EXIT-side depth / slippage.
  * minimum_profitable_position   → it answers entry break-even vs gas.
This module answers only the deposit-cap-headroom / capacity question.

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
    "data", "deposit_cap_headroom_log.json"
)
LOG_CAP = 100

DAYS_SENTINEL_NEVER = 1e9      # zero inflow → cap is never reached
PCT_SENTINEL_MAX = 1e6        # guard for utilization / dilution overflow

# Utilization thresholds (current_tvl / cap, as %)
NEAR_CAP_PCT = 90.0           # >=90% full → near the cap
CAP_REACHED_PCT = 100.0       # >=100% full → cap reached
TIGHT_HEADROOM_PCT = 75.0     # >=75% full → headroom getting tight
AMPLE_HEADROOM_PCT = 40.0     # <40% full → ample headroom

# Fill-speed threshold
FAST_FILL_DAYS = 7.0          # cap reached within a week → fast filling

# Dilution threshold (projected APY dilution from fresh inflow, %)
DILUTION_RISK_PCT = 3.0       # >=3% pro-rata dilution → flag


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

class DeFiProtocolDepositCapHeadroomAnalyzer:
    """
    Analyzes how close a vault is to its deposit cap and whether a desired
    deposit can be deployed without bumping the ceiling (or being diluted).

    Per-position input dict fields:
        vault / token              : str
        deposit_cap_usd            : float  (the deposit ceiling)
        current_tvl_usd            : float  (deposits already in the vault)
        intended_deposit_usd       : float  (size I want to add, default 0)
        recent_inflow_usd_7d       : float  (net inflow over last 7d, default 0)
        cap_is_hard                : bool   (hard ceiling vs soft, default True)
        base_apy_pct               : float  (headline yield, default 0)
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
        cap = _f(p.get("deposit_cap_usd"))
        current_tvl = _f(p.get("current_tvl_usd"))
        intended = max(0.0, _f(p.get("intended_deposit_usd")))
        inflow_7d = max(0.0, _f(p.get("recent_inflow_usd_7d")))
        cap_is_hard = bool(p.get("cap_is_hard", True))
        base_apy = max(0.0, _f(p.get("base_apy_pct")))

        # Insufficient data: no cap to compare against, or negative TVL.
        if cap <= 0 or current_tvl < 0:
            return self._insufficient(token, cap_is_hard)

        utilization = _safe_div(current_tvl, cap, PCT_SENTINEL_MAX) * 100.0
        if utilization >= PCT_SENTINEL_MAX:
            utilization = PCT_SENTINEL_MAX
        utilization = min(utilization, PCT_SENTINEL_MAX)

        headroom = max(0.0, cap - current_tvl)

        intended_fits = intended <= headroom
        if intended <= 0:
            fillable_pct = 100.0
        else:
            fillable_pct = _clamp(
                _safe_div(min(intended, headroom), intended, 0.0) * 100.0,
                0.0, 100.0,
            )

        # Days to cap at current inflow pace (inflow_7d / 7 per day).
        daily_inflow = inflow_7d / 7.0
        if daily_inflow <= 0 or headroom <= 0:
            days_to_cap = DAYS_SENTINEL_NEVER if daily_inflow <= 0 else 0.0
        else:
            days_to_cap = _safe_div(headroom, daily_inflow, DAYS_SENTINEL_NEVER)

        # Projected dilution: fresh inflow dilutes base_apy pro-rata. The fresh
        # inflow that can still fit is bounded by headroom; dilution approximated
        # as fresh / (current_tvl + fresh) applied to base_apy.
        fresh = min(inflow_7d, headroom)
        denom = current_tvl + fresh
        dilution_frac = _safe_div(fresh, denom, 0.0)
        projected_dilution = _clamp(dilution_frac * base_apy, 0.0, PCT_SENTINEL_MAX)

        score = self._headroom_score(
            utilization, intended_fits, intended, days_to_cap, cap_is_hard,
        )
        classification = self._classify(utilization)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, intended, intended_fits, fillable_pct)
        flags = self._flags(
            utilization, intended, intended_fits, days_to_cap, daily_inflow,
            cap_is_hard, projected_dilution, classification,
        )

        return {
            "token": token,
            "deposit_cap_usd": round(cap, 2),
            "current_tvl_usd": round(current_tvl, 2),
            "cap_utilization_pct": round(utilization, 4),
            "remaining_headroom_usd": round(headroom, 2),
            "intended_deposit_usd": round(intended, 2),
            "intended_fits": intended_fits,
            "fillable_pct_of_intended": round(fillable_pct, 4),
            "days_to_cap_at_current_inflow": (
                None if days_to_cap >= DAYS_SENTINEL_NEVER else round(days_to_cap, 2)
            ),
            "projected_dilution_pct": round(projected_dilution, 4),
            "cap_is_hard": cap_is_hard,
            "headroom_score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _headroom_score(
        self,
        utilization: float,
        intended_fits: bool,
        intended: float,
        days_to_cap: float,
        cap_is_hard: bool,
    ) -> float:
        """
        0–100, higher = more headroom / safer to enter. Weighted:
          sufficient headroom (≈40) + intended fits (≈30)
          + slow fill / many days to cap (≈20) + soft-cap bonus (≈10).
        """
        # Headroom component — 0% util → full, CAP_REACHED_PCT+ → 0.
        free_frac = _clamp(1.0 - utilization / CAP_REACHED_PCT, 0.0, 1.0)
        headroom = 40.0 * free_frac

        # Intended-fits component — only meaningful if a deposit is intended.
        if intended <= 0:
            fits = 30.0
        else:
            fits = 30.0 if intended_fits else 0.0

        # Fill-speed component — break the cap well beyond a week → full.
        if days_to_cap >= DAYS_SENTINEL_NEVER:
            fill = 20.0
        else:
            # 0 days → 0, FAST_FILL_DAYS*4 (~28d) or more → full.
            fill = 20.0 * _clamp(days_to_cap / (FAST_FILL_DAYS * 4.0), 0.0, 1.0)

        # Soft-cap bonus — a soft cap can flex, so it's less binding.
        bonus = 0.0 if cap_is_hard else 10.0

        return _clamp(headroom + fits + fill + bonus, 0.0, 100.0)

    def _classify(self, utilization: float) -> str:
        if utilization >= CAP_REACHED_PCT:
            return "CAP_REACHED"
        if utilization >= TIGHT_HEADROOM_PCT:
            return "TIGHT_HEADROOM"
        if utilization >= AMPLE_HEADROOM_PCT:
            return "MODERATE_HEADROOM"
        return "AMPLE_HEADROOM"

    def _recommend(
        self,
        classification: str,
        intended: float,
        intended_fits: bool,
        fillable_pct: float,
    ) -> str:
        if classification == "CAP_REACHED":
            return "WAIT_OR_SKIP"
        if intended <= 0:
            # no specific size requested: ample/moderate → deploy, tight → wait
            return "WAIT_OR_SKIP" if classification == "TIGHT_HEADROOM" else "DEPLOY"
        if intended_fits:
            return "DEPLOY"
        if fillable_pct > 0:
            return "DEPLOY_PARTIAL"
        return "WAIT_OR_SKIP"

    def _flags(
        self,
        utilization: float,
        intended: float,
        intended_fits: bool,
        days_to_cap: float,
        daily_inflow: float,
        cap_is_hard: bool,
        projected_dilution: float,
        classification: str,
    ) -> List[str]:
        flags: List[str] = []

        if utilization >= CAP_REACHED_PCT:
            flags.append("CAP_REACHED")
        elif utilization >= NEAR_CAP_PCT:
            flags.append("NEAR_CAP")

        if classification == "AMPLE_HEADROOM":
            flags.append("AMPLE_HEADROOM")

        if intended > 0:
            if intended_fits:
                flags.append("INTENDED_FITS")
            else:
                flags.append("INTENDED_EXCEEDS_HEADROOM")

        if days_to_cap < DAYS_SENTINEL_NEVER and days_to_cap <= FAST_FILL_DAYS and daily_inflow > 0:
            flags.append("FAST_FILLING")

        if cap_is_hard:
            flags.append("HARD_CAP")
        else:
            flags.append("SOFT_CAP")

        if projected_dilution >= DILUTION_RISK_PCT:
            flags.append("DILUTION_RISK")

        return flags

    def _insufficient(self, token: str, cap_is_hard: bool) -> dict:
        return {
            "token": token,
            "deposit_cap_usd": 0.0,
            "current_tvl_usd": 0.0,
            "cap_utilization_pct": 0.0,
            "remaining_headroom_usd": 0.0,
            "intended_deposit_usd": 0.0,
            "intended_fits": False,
            "fillable_pct_of_intended": 0.0,
            "days_to_cap_at_current_inflow": None,
            "projected_dilution_pct": 0.0,
            "cap_is_hard": cap_is_hard,
            "headroom_score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "WAIT_OR_SKIP",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_headroom_vault": None,
                "least_headroom_vault": None,
                "avg_headroom_score": 0.0,
                "cap_reached_count": 0,
                "position_count": len(results),
            }
        by_score = sorted(scored, key=lambda r: r["headroom_score"])
        avg = _mean([r["headroom_score"] for r in scored])
        cap_reached = sum(1 for r in results if r["classification"] == "CAP_REACHED")
        return {
            "most_headroom_vault": by_score[-1]["token"],
            "least_headroom_vault": by_score[0]["token"],
            "avg_headroom_score": round(avg, 2),
            "cap_reached_count": cap_reached,
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
                    "headroom_score": r["headroom_score"],
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
            "vault": "USDC-Vault-Ample",
            "deposit_cap_usd": 100_000_000.0,
            "current_tvl_usd": 25_000_000.0,
            "intended_deposit_usd": 1_000_000.0,
            "recent_inflow_usd_7d": 2_000_000.0,
            "cap_is_hard": True,
            "base_apy_pct": 8.0,
        },
        {
            "vault": "ETH-Vault-NearCap",
            "deposit_cap_usd": 50_000_000.0,
            "current_tvl_usd": 48_000_000.0,
            "intended_deposit_usd": 5_000_000.0,
            "recent_inflow_usd_7d": 3_500_000.0,
            "cap_is_hard": True,
            "base_apy_pct": 12.0,
        },
        {
            "vault": "DAI-Vault-Full",
            "deposit_cap_usd": 10_000_000.0,
            "current_tvl_usd": 10_000_000.0,
            "intended_deposit_usd": 500_000.0,
            "recent_inflow_usd_7d": 0.0,
            "cap_is_hard": False,
            "base_apy_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1154 Deposit Cap Headroom Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolDepositCapHeadroomAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
