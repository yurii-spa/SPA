"""
MP-1194: DeFiProtocolVaultMarginalDepositAPRDilutionAnalyzer
============================================================
Advisory/read-only analytics module.

A vault's HEADLINE blended APR is the AVERAGE across sub-strategy "sleeves"
weighted by CURRENT allocation. A NEW marginal deposit cannot earn that average
because the highest-yielding sleeves are often capacity-constrained: new capital
is routed greedily (descending APR) only into sleeves with remaining capacity,
so the MARGINAL APR earned by new dollars is typically LOWER than the headline
average. This module measures how diluted a NEW depositor's marginal APR is
versus the headline — a headline-honesty/quality signal for new capital.

Angle: "headline 14% is the blended average, but the 20% sleeve is near capacity
and only a small share of TVL; marginal new deposits flow into the 8% sleeves →
marginal APR for a NEW depositor is below the headline; discount or verify."

HIGHER score = marginal deposit APR is close to / above the headline (top sleeves
have ample capacity) → headline honest for new capital.

Distinct from:
  * defi_protocol_vault_capacity_dilution_analyzer — overall TVL growth diluting
    a fixed reward pool (aggregate dilution), not per-sleeve routing of marginal
    capital across yield tiers.
  * defi_protocol_yield_source_diversification_scorer — diversification QUALITY
    across sources, not the marginal-vs-average routing of new dollars.
  * protocol_defi_apy_decomposition_analyzer — decomposes yield SOURCES of the
    headline, not marginal-vs-average for new capital.
  * defi_protocol_vault_boost_tier_headline_realization_analyzer — boost
    multiplier TIERS, not sleeve capacity routing of marginal deposits.

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
    "data", "vault_marginal_deposit_apr_dilution_log.json"
)
LOG_CAP = 100

# Default new deposit size (USD) used when not supplied.
DEFAULT_NEW_DEPOSIT_USD = 100000.0

# Tolerance: |dilution| at/below this (pp) marks marginal as ALIGNED to headline.
ALIGN_TOLERANCE_PCT = 0.5
# Scoring reference: positive dilution normalised against this ceiling for the
# small-dilution component (dilution at/above this contributes nothing).
DILUTION_SCORE_CEILING_PCT = 10.0

# Classification thresholds (dilution in pp, headline - marginal).
MINOR_DILUTION_PCT = 3.0      # dilution at/below this → minor
MODERATE_DILUTION_PCT = 8.0   # dilution at/below this → moderate; above → severe

# Minimum valid sleeves required to derive a marginal APR.
MIN_SLEEVES = 1


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

class DeFiProtocolVaultMarginalDepositAPRDilutionAnalyzer:
    """
    Measures how diluted a NEW depositor's MARGINAL APR is versus the vault's
    HEADLINE blended (allocation-weighted average) APR. A new deposit is routed
    greedily into sleeves in descending APR order, but only up to each sleeve's
    remaining capacity; capital that cannot be placed in any sleeve sits idle at
    0%. The marginal APR earned by the new dollars is therefore typically below
    the headline average when top sleeves are capacity-constrained. The module
    reports this aggregately as a headline-honesty signal for new capital.

    HIGHER score = marginal deposit APR is close to / above the headline.

    Per-position input dict fields:
        vault / token            : str
        headline_apr_pct         : float (default 0) — advertised blended APR
        sleeves                  : Optional[List[dict]] each
                                   {"apr_pct", "allocation_usd",
                                    "capacity_remaining_usd"}
        new_deposit_usd          : float (default DEFAULT_NEW_DEPOSIT_USD;
                                   max(0, ..))
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
        headline = _f(p.get("headline_apr_pct"))
        new_deposit = max(0.0, _f(p.get("new_deposit_usd"),
                                  DEFAULT_NEW_DEPOSIT_USD))

        # Collect valid sleeves: keep only sleeves with a finite apr_pct.
        raw_sleeves = p.get("sleeves")
        valid_sleeves: List[Dict[str, float]] = []
        if isinstance(raw_sleeves, (list, tuple)):
            for s in raw_sleeves:
                if not isinstance(s, dict):
                    continue
                apr_raw = s.get("apr_pct")
                apr = _f(apr_raw)
                if not math.isfinite(apr):
                    continue
                # Discard a candidate only if apr_pct is non-finite.
                if apr_raw is not None and not math.isfinite(_f(apr_raw,
                                                                float("nan"))):
                    continue
                alloc = max(0.0, _f(s.get("allocation_usd")))
                cap_rem = max(0.0, _f(s.get("capacity_remaining_usd")))
                valid_sleeves.append(
                    {"apr": apr, "alloc": alloc, "cap_rem": cap_rem})

        # Insufficient data: no valid sleeves, non-positive headline, or no
        # deposit to route.
        if (not valid_sleeves
                or not math.isfinite(headline) or headline <= 0
                or new_deposit <= 0):
            return self._insufficient(token)

        # Allocation-weighted headline-equivalent average APR (current).
        total_alloc = sum(s["alloc"] for s in valid_sleeves)
        if total_alloc > 0:
            weighted_avg_apr = (
                sum(s["apr"] * s["alloc"] for s in valid_sleeves)
                / total_alloc)
        else:
            weighted_avg_apr = _mean([s["apr"] for s in valid_sleeves])

        # Marginal routing: greedily fill new deposit into sleeves in DESC APR.
        sorted_sleeves = sorted(
            valid_sleeves, key=lambda s: s["apr"], reverse=True)
        total_remaining_capacity_usd = sum(
            s["cap_rem"] for s in valid_sleeves)
        deployable = min(new_deposit, total_remaining_capacity_usd)
        undeployed = new_deposit - deployable

        remaining = new_deposit
        weighted_filled = 0.0
        for s in sorted_sleeves:
            if remaining <= 0:
                break
            fill = min(remaining, s["cap_rem"])
            if fill <= 0:
                continue
            weighted_filled += fill * s["apr"]
            remaining -= fill
        # Undeployed capital earns 0%.
        marginal_apr = (weighted_filled + undeployed * 0.0) / new_deposit

        dilution_pct = headline - marginal_apr

        dilution_ratio = _safe_div(marginal_apr, headline, None)
        if dilution_ratio is not None and not math.isfinite(dilution_ratio):
            dilution_ratio = None

        # Top (highest-apr) sleeve characteristics.
        top_sleeve = sorted_sleeves[0]
        top_sleeve_apr_pct = top_sleeve["apr"]
        top_sleeve_capacity_remaining_usd = top_sleeve["cap_rem"]

        fully_absorbed = bool(undeployed <= 1e-9)
        top_sleeve_constrained = bool(
            top_sleeve_capacity_remaining_usd < new_deposit)

        score = self._score(marginal_apr, headline, dilution_pct)
        classification = self._classify(dilution_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification, top_sleeve_constrained, fully_absorbed,
            headline, weighted_avg_apr, len(valid_sleeves))

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "marginal_apr_pct": round(marginal_apr, 4),
            "weighted_avg_apr_pct": round(weighted_avg_apr, 4),
            "dilution_pct": round(dilution_pct, 4),
            "dilution_ratio": (
                None if dilution_ratio is None else round(dilution_ratio, 4)),
            "top_sleeve_apr_pct": round(top_sleeve_apr_pct, 4),
            "top_sleeve_capacity_remaining_usd": round(
                top_sleeve_capacity_remaining_usd, 4),
            "total_remaining_capacity_usd": round(
                total_remaining_capacity_usd, 4),
            "new_deposit_usd": round(new_deposit, 4),
            "deployable_usd": round(deployable, 4),
            "undeployed_usd": round(undeployed, 4),
            "sleeve_count": len(valid_sleeves),
            "fully_absorbed": fully_absorbed,
            "top_sleeve_constrained": top_sleeve_constrained,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        marginal_apr: float,
        headline: float,
        dilution_pct: float,
    ) -> float:
        """
        0–100, HIGHER = marginal APR closer to / above the headline. Components:
          alignment (70) — marginal/headline clamped 0..1, × 70.
          small dilution (30) — positive dilution normalised against the ceiling.
        A marginal at/above the headline gets full alignment (70, ratio clamps
        at 1) and full small-dilution (30, dilution <= 0) → high.
        """
        if headline > 0:
            alignment_comp = 70.0 * _clamp(
                _safe_div(marginal_apr, headline, 0.0), 0.0, 1.0)
        else:
            alignment_comp = 0.0
        small_dilution_comp = 30.0 * _clamp(
            1.0 - max(0.0, dilution_pct) / DILUTION_SCORE_CEILING_PCT,
            0.0, 1.0)
        total = alignment_comp + small_dilution_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, dilution_pct: float) -> str:
        if dilution_pct < -ALIGN_TOLERANCE_PCT:
            return "MARGINAL_ABOVE_HEADLINE"
        if abs(dilution_pct) <= ALIGN_TOLERANCE_PCT:
            return "ALIGNED"
        if dilution_pct <= MINOR_DILUTION_PCT:
            return "MINOR_DILUTION"
        if dilution_pct <= MODERATE_DILUTION_PCT:
            return "MODERATE_DILUTION"
        return "SEVERE_DILUTION"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification in ("MARGINAL_ABOVE_HEADLINE", "ALIGNED"):
            return "TRUST_HEADLINE"
        if classification == "MINOR_DILUTION":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "MODERATE_DILUTION":
            return "DISCOUNT_HEADLINE"
        # SEVERE_DILUTION
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        top_sleeve_constrained: bool,
        fully_absorbed: bool,
        headline: float,
        weighted_avg_apr: float,
        sleeve_count: int,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "ALIGNED":
            flags.append("ALIGNED")
        if classification == "MINOR_DILUTION":
            flags.append("MINOR_DILUTION")
        if classification == "MODERATE_DILUTION":
            flags.append("MODERATE_DILUTION")
        if classification == "SEVERE_DILUTION":
            flags.append("SEVERE_DILUTION")
        if classification == "MARGINAL_ABOVE_HEADLINE":
            flags.append("MARGINAL_ABOVE_HEADLINE")
        if top_sleeve_constrained:
            flags.append("TOP_SLEEVE_CAPACITY_CONSTRAINED")
        if not fully_absorbed:
            flags.append("DEPOSIT_NOT_FULLY_ABSORBED")
        if headline > weighted_avg_apr + ALIGN_TOLERANCE_PCT:
            flags.append("HEADLINE_ABOVE_CURRENT_AVERAGE")
        if 0 < sleeve_count < 2:
            flags.append("SPARSE_SLEEVES")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "marginal_apr_pct": None,
            "weighted_avg_apr_pct": None,
            "dilution_pct": 0.0,
            "dilution_ratio": None,
            "top_sleeve_apr_pct": None,
            "top_sleeve_capacity_remaining_usd": None,
            "total_remaining_capacity_usd": None,
            "new_deposit_usd": 0.0,
            "deployable_usd": None,
            "undeployed_usd": None,
            "sleeve_count": 0,
            "fully_absorbed": False,
            "top_sleeve_constrained": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_OR_VERIFY",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [
            r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_aligned_vault": None,
                "least_aligned_vault": None,
                "avg_score": 0.0,
                "severe_dilution_count": 0,
                "position_count": len(results),
            }
        # Higher score = marginal more aligned → highest score is best.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        severe = sum(
            1 for r in results if r["classification"] == "SEVERE_DILUTION")
        return {
            "most_aligned_vault": by_score[-1]["token"],
            "least_aligned_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "severe_dilution_count": severe,
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
            # ALIGNED: top sleeve has ample capacity for the new deposit.
            "vault": "USDC-Vault-Aligned",
            "headline_apr_pct": 12.0,
            "sleeves": [
                {"apr_pct": 12.0, "allocation_usd": 1_000_000.0,
                 "capacity_remaining_usd": 5_000_000.0},
                {"apr_pct": 8.0, "allocation_usd": 500_000.0,
                 "capacity_remaining_usd": 2_000_000.0},
            ],
            "new_deposit_usd": 100000.0,
        },
        {
            # SEVERE_DILUTION: tiny capacity on the 20% sleeve forces the new
            # deposit into the low (8%) sleeves.
            "vault": "GMX-Vault-SevereDilution",
            "headline_apr_pct": 14.0,
            "sleeves": [
                {"apr_pct": 20.0, "allocation_usd": 1_000_000.0,
                 "capacity_remaining_usd": 1_000.0},
                {"apr_pct": 5.0, "allocation_usd": 1_000_000.0,
                 "capacity_remaining_usd": 5_000_000.0},
            ],
            "new_deposit_usd": 100000.0,
        },
        {
            # INSUFFICIENT_DATA: no sleeves and headline 0.
            "vault": "DAI-Vault-NoData",
            "headline_apr_pct": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1194 Vault Marginal Deposit APR Dilution Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultMarginalDepositAPRDilutionAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
