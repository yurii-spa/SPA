"""
MP-1166: DeFiProtocolVaultCapacityDilutionAnalyzer
==================================================
Advisory/read-only analytics module.

A vault/strategy has a FINITE alpha capacity (optimal_capacity_tvl). While the
deployed TVL stays below that capacity the headline APR holds; once TVL grows
ABOVE capacity, the marginal capital can no longer be put to work at the same
APR, so yield-per-share is DILUTED. Your own deposit additionally pushes TVL
toward (and possibly past) the threshold. This module answers, for a given
vault, whether the advertised APR is realistic for new capital: it computes the
post-deposit TVL, the over-capacity overhang, the effective (diluted) APR on
new capital, the dilution and remaining headroom.

Angle: "the vault shows 15% APR at a $50M capacity, but TVL is already $120M →
the effective APR on new capital is far lower; should I still deploy?"

HIGHER score = more headroom / less dilution.

Distinct from:
  * vault_gas_breakeven → fixed dollar gas cost vs position size / holding days.
  * vault_round_trip_cost → percentage deposit/withdrawal fees + slippage.
This module isolates *alpha-capacity dilution*: how much the headline APR shrinks
once TVL (including your deposit) exceeds the strategy's optimal capacity.

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
    "data", "vault_capacity_dilution_log.json"
)
LOG_CAP = 100

# Capacity decay exponent bounds (how sharply APR falls past capacity).
DECAY_EXPONENT_MIN = 0.25
DECAY_EXPONENT_MAX = 3.0

# Utilisation classification thresholds (post-deposit TVL as a % of capacity).
AMPLE_UTILIZATION_PCT = 70.0        # util at/below → ample headroom
APPROACHING_UTILIZATION_PCT = 100.0  # util at/below → approaching capacity
OVER_UTILIZATION_PCT = 150.0        # util at/below → over capacity; above → severe

# At-capacity tolerance band around 100% utilisation.
AT_CAPACITY_TOLERANCE_PCT = 1.0

# Scoring reference: dilution normalised against this ceiling for the low-dilution
# component (dilution at/above this contributes nothing).
DILUTION_SCORE_CEILING_PCT = 50.0
# Headroom normalised against this ceiling for the has-headroom component.
HEADROOM_SCORE_CEILING_PCT = 50.0

# Flag thresholds.
SEVERE_DILUTION_PCT = 33.0     # dilution at/above this is severe
NEGLIGIBLE_DILUTION_PCT = 2.0  # dilution below this is negligible


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

class DeFiProtocolVaultCapacityDilutionAnalyzer:
    """
    Models the FINITE alpha capacity of a vault/strategy and how much the
    headline APR is diluted once deployed TVL (including your own deposit) grows
    past that capacity. While post-deposit TVL stays at/below capacity the
    headline APR holds; above capacity the marginal capital cannot be deployed
    at the same APR, so the effective APR on new capital decays.

    HIGHER score = more headroom / less dilution.

    Per-position input dict fields:
        vault / token            : str
        headline_apr_pct         : float (default 0; max(0,..))
        current_tvl_usd          : float (default 0; max(0,..))
        optimal_capacity_tvl_usd : float (default 0; max(0,..))
        your_deposit_usd         : float (default 0; max(0,..))
        capacity_decay_exponent  : float (default 1.0; clamp 0.25..3.0)
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
        headline_apr_pct = max(0.0, _f(p.get("headline_apr_pct")))
        current_tvl_usd = max(0.0, _f(p.get("current_tvl_usd")))
        capacity_usd = max(0.0, _f(p.get("optimal_capacity_tvl_usd")))
        your_deposit_usd = max(0.0, _f(p.get("your_deposit_usd")))
        decay_exponent = _clamp(
            _f(p.get("capacity_decay_exponent"), 1.0),
            DECAY_EXPONENT_MIN, DECAY_EXPONENT_MAX)

        # Insufficient data: no headline APR or no capacity → nothing to model.
        if headline_apr_pct <= 0 or capacity_usd <= 0:
            return self._insufficient(token)

        post_deposit_tvl_usd = current_tvl_usd + your_deposit_usd
        over_capacity_usd = max(0.0, post_deposit_tvl_usd - capacity_usd)

        # Utilisation of capacity by post-deposit TVL (%).
        utilization_pct = _safe_div(
            post_deposit_tvl_usd, capacity_usd, 0.0) * 100.0

        # Effective (diluted) APR on new capital. At/below capacity the headline
        # APR holds; above, it decays by (capacity / post_deposit_tvl)^exponent.
        if post_deposit_tvl_usd <= capacity_usd:
            effective_apr_pct = headline_apr_pct
        else:
            ratio = _safe_div(capacity_usd, post_deposit_tvl_usd, 0.0)
            decay = ratio ** decay_exponent if ratio > 0 else 0.0
            effective_apr_pct = headline_apr_pct * decay
        if not math.isfinite(effective_apr_pct):
            effective_apr_pct = 0.0
        effective_apr_pct = max(0.0, effective_apr_pct)

        # Dilution: how much headline APR is lost, as a % of headline.
        dilution_pct = _clamp(
            _safe_div(
                headline_apr_pct - effective_apr_pct, headline_apr_pct, 0.0
            ) * 100.0, 0.0, 100.0)
        apr_lost_pct = max(0.0, headline_apr_pct - effective_apr_pct)

        # Headroom: how much can still be added BEFORE your deposit.
        headroom_usd = max(0.0, capacity_usd - current_tvl_usd)
        headroom_pct = _safe_div(headroom_usd, capacity_usd, 0.0) * 100.0

        over_capacity = bool(post_deposit_tvl_usd > capacity_usd)
        at_capacity = bool(
            abs(utilization_pct - 100.0) <= AT_CAPACITY_TOLERANCE_PCT)
        your_deposit_tips_over = bool(
            current_tvl_usd <= capacity_usd
            and post_deposit_tvl_usd > capacity_usd)

        score = self._score(dilution_pct, headroom_pct, over_capacity)
        classification = self._classify(utilization_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification, dilution_pct, your_deposit_tips_over, headroom_usd)

        return {
            "token": token,
            "headline_apr_pct": round(headline_apr_pct, 4),
            "current_tvl_usd": round(current_tvl_usd, 4),
            "optimal_capacity_tvl_usd": round(capacity_usd, 4),
            "your_deposit_usd": round(your_deposit_usd, 4),
            "capacity_decay_exponent": round(decay_exponent, 4),
            "post_deposit_tvl_usd": round(post_deposit_tvl_usd, 4),
            "over_capacity_usd": round(over_capacity_usd, 4),
            "utilization_pct": round(utilization_pct, 4),
            "effective_apr_pct": round(effective_apr_pct, 4),
            "dilution_pct": round(dilution_pct, 4),
            "apr_lost_pct": round(apr_lost_pct, 4),
            "headroom_usd": round(headroom_usd, 4),
            "headroom_pct": round(headroom_pct, 4),
            "over_capacity": over_capacity,
            "at_capacity": at_capacity,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        dilution_pct: float,
        headroom_pct: float,
        over_capacity: bool,
    ) -> float:
        """
        0–100, HIGHER = more headroom / less dilution. Components:
          low dilution (55) — dilution normalised against the scoring ceiling.
          has headroom (30) — remaining headroom normalised against its ceiling.
          not over capacity (15) — full credit when post-deposit TVL fits.
        """
        low_dilution_comp = 55.0 * _clamp(
            1.0 - dilution_pct / DILUTION_SCORE_CEILING_PCT, 0.0, 1.0)
        headroom_comp = 30.0 * _clamp(
            headroom_pct / HEADROOM_SCORE_CEILING_PCT, 0.0, 1.0)
        not_over_comp = 0.0 if over_capacity else 15.0
        total = low_dilution_comp + headroom_comp + not_over_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, utilization_pct: float) -> str:
        if utilization_pct <= AMPLE_UTILIZATION_PCT:
            return "AMPLE_HEADROOM"
        if utilization_pct <= APPROACHING_UTILIZATION_PCT:
            return "APPROACHING_CAPACITY"
        if utilization_pct <= OVER_UTILIZATION_PCT:
            return "OVER_CAPACITY"
        return "SEVERELY_DILUTED"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID"
        if classification == "AMPLE_HEADROOM":
            return "DEPLOY"
        if classification == "APPROACHING_CAPACITY":
            return "DEPLOY_SOON"
        if classification == "OVER_CAPACITY":
            return "DEPLOY_REDUCED_SIZE"
        # SEVERELY_DILUTED
        return "AVOID"

    def _flags(
        self,
        classification: str,
        dilution_pct: float,
        your_deposit_tips_over: bool,
        headroom_usd: float,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "AMPLE_HEADROOM":
            flags.append("AMPLE_HEADROOM")
        if classification == "APPROACHING_CAPACITY":
            flags.append("APPROACHING_CAPACITY")
        if classification == "OVER_CAPACITY":
            flags.append("OVER_CAPACITY")
        if dilution_pct >= SEVERE_DILUTION_PCT:
            flags.append("SEVERELY_DILUTED")
        if your_deposit_tips_over:
            flags.append("YOUR_DEPOSIT_TIPS_OVER")
        if headroom_usd <= 0:
            flags.append("NO_HEADROOM")
        if dilution_pct < NEGLIGIBLE_DILUTION_PCT:
            flags.append("NEGLIGIBLE_DILUTION")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "current_tvl_usd": 0.0,
            "optimal_capacity_tvl_usd": 0.0,
            "your_deposit_usd": 0.0,
            "capacity_decay_exponent": 0.0,
            "post_deposit_tvl_usd": 0.0,
            "over_capacity_usd": 0.0,
            "utilization_pct": 0.0,
            "effective_apr_pct": 0.0,
            "dilution_pct": 0.0,
            "apr_lost_pct": 0.0,
            "headroom_usd": 0.0,
            "headroom_pct": 0.0,
            "over_capacity": False,
            "at_capacity": False,
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
                "least_diluted_vault": None,
                "most_diluted_vault": None,
                "avg_score": 0.0,
                "over_capacity_count": 0,
                "position_count": len(results),
            }
        # Higher score = more headroom / less dilution → highest is least diluted.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        over_capacity = sum(1 for r in results if r.get("over_capacity"))
        return {
            "least_diluted_vault": by_score[-1]["token"],
            "most_diluted_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "over_capacity_count": over_capacity,
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
            "vault": "USDC-Vault-AmpleHeadroom",
            "headline_apr_pct": 8.0,
            "current_tvl_usd": 10_000_000.0,
            "optimal_capacity_tvl_usd": 50_000_000.0,
            "your_deposit_usd": 100_000.0,
            "capacity_decay_exponent": 1.0,
        },
        {
            "vault": "GMX-Vault-SeverelyDiluted",
            "headline_apr_pct": 15.0,
            "current_tvl_usd": 120_000_000.0,
            "optimal_capacity_tvl_usd": 50_000_000.0,
            "your_deposit_usd": 500_000.0,
            "capacity_decay_exponent": 1.5,
        },
        {
            "vault": "DAI-Vault-NoData",
            "headline_apr_pct": 0.0,
            "current_tvl_usd": 0.0,
            "optimal_capacity_tvl_usd": 0.0,
            "your_deposit_usd": 0.0,
            "capacity_decay_exponent": 1.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1166 Vault Capacity Dilution Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultCapacityDilutionAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
