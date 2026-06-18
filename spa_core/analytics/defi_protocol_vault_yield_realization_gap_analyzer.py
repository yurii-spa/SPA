"""
MP-1169: DeFiProtocolVaultYieldRealizationGapAnalyzer
=====================================================
Advisory/read-only analytics module.

The gap between a vault's HEADLINE (advertised) APR and the REALIZED APR
implied by the ACTUAL growth of its share price over a trailing window. A
persistent gap means the headline overstates the real yield a holder captures
(fee drag, idle cash, missed compounds, decaying emissions, etc.). This module
does NOT model any single cause — it AGGREGATELY measures realized-vs-promised
as a trust/quality signal.

Angle: "headline says 18% APR but the share price only grew 9% annualized over
the trailing window → a severe realization gap; discount or verify."

HIGHER score = realized yield is closer to / above the headline.

Distinct from:
  * modules that model a SPECIFIC cause of the gap (gas/idle_cash/fees/emission
    decay). Those isolate one mechanism. This module makes NO claim about WHY —
    it only measures the realized-vs-promised gap as an aggregate honesty score.

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
    "data", "vault_yield_realization_gap_log.json"
)
LOG_CAP = 100

# Tolerance: a gap above this (pp) marks the headline as overstated.
GAP_TOLERANCE_PCT = 1.0
# Scoring reference: positive gap normalised against this ceiling for the
# small-gap component (gap at/above this contributes nothing).
GAP_SCORE_CEILING_PCT = 10.0

# Classification thresholds (gap in percentage points, headline - realized).
OUTPERFORM_GAP_PCT = 1.0    # realized > headline + this → outperforms
MEETS_GAP_PCT = 1.0         # |gap| at/below this → meets headline
MINOR_GAP_PCT = 3.0         # gap at/below this → minor
MODERATE_GAP_PCT = 8.0      # gap at/below this → moderate; above → severe

# meets_headline: realized within this fraction of headline.
MEETS_HEADLINE_FRACTION = 0.9


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

class DeFiProtocolVaultYieldRealizationGapAnalyzer:
    """
    Measures the gap between a vault's HEADLINE APR and the REALIZED APR derived
    from actual share-price growth over a trailing window. A realized APR can be
    supplied directly (override) or annualized from start/end share prices. The
    gap is the headline minus realized; a positive gap means the headline
    overstates real yield. The module reports this aggregately as a trust signal.

    HIGHER score = realized yield is closer to / above the headline.

    Per-position input dict fields:
        vault / token          : str
        headline_apr_pct       : float (default 0)
        share_price_start_usd  : float (default 0)
        share_price_end_usd    : float (default 0)
        window_days            : float (default 30; max(0,..))
        realized_apr_pct       : Optional[float] (default None; direct override)
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
        start = max(0.0, _f(p.get("share_price_start_usd")))
        end = max(0.0, _f(p.get("share_price_end_usd")))
        window_days = max(0.0, _f(p.get("window_days"), 30.0))

        # Realized APR: prefer a finite override; else annualize from prices.
        override_raw = p.get("realized_apr_pct")
        period_return_pct: Optional[float] = None
        realized: Optional[float] = None
        if override_raw is not None:
            ov = _f(override_raw)
            if math.isfinite(ov):
                realized = ov
        if realized is None and start > 0 and end > 0 and window_days > 0:
            period_return = end / start - 1.0
            ann = period_return * (365.0 / window_days) * 100.0
            if math.isfinite(ann):
                realized = ann
                period_return_pct = period_return * 100.0

        # Insufficient data: headline non-positive AND realized cannot be
        # derived. Also if realized stays None, classification is INSUFFICIENT.
        if (headline <= 0 and realized is None) or realized is None:
            return self._insufficient(token)
        if headline <= 0:
            # Defensive: a non-INSUFFICIENT result requires headline > 0.
            return self._insufficient(token)

        gap_pct = headline - realized

        realization_ratio = _safe_div(realized, headline, None)
        if realization_ratio is not None and not math.isfinite(
                realization_ratio):
            realization_ratio = None
        if realization_ratio is None:
            realization_pct = None
        else:
            realization_pct = _clamp(realization_ratio * 100.0, 0.0, 1e9)

        overstated = bool(gap_pct > GAP_TOLERANCE_PCT)
        meets_headline = bool(realized >= headline * MEETS_HEADLINE_FRACTION)

        score = self._score(headline, realized, gap_pct)
        classification = self._classify(gap_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(classification, overstated, realized)

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "realized_apr_pct": round(realized, 4),
            "share_price_start_usd": round(start, 4),
            "share_price_end_usd": round(end, 4),
            "window_days": round(window_days, 4),
            "period_return_pct": (
                None if period_return_pct is None
                else round(period_return_pct, 4)),
            "gap_pct": round(gap_pct, 4),
            "realization_ratio": (
                None if realization_ratio is None
                else round(realization_ratio, 4)),
            "realization_pct": (
                None if realization_pct is None
                else round(realization_pct, 4)),
            "overstated": overstated,
            "meets_headline": meets_headline,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        headline: float,
        realized: float,
        gap_pct: float,
    ) -> float:
        """
        0–100, HIGHER = realized closer to / above headline. Components:
          realization (70) — realized/headline clamped 0..1, × 70.
          small gap (30) — positive gap normalised against the ceiling.
        Outperformers (realized > headline) get full realization (70, ratio
        clamps at 1) and full small-gap (30, gap <= 0) → high.
        """
        if headline > 0:
            realization_comp = 70.0 * _clamp(
                _safe_div(realized, headline, 0.0), 0.0, 1.0)
        else:
            realization_comp = 0.0
        small_gap_comp = 30.0 * _clamp(
            1.0 - max(0.0, gap_pct) / GAP_SCORE_CEILING_PCT, 0.0, 1.0)
        total = realization_comp + small_gap_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, gap_pct: float) -> str:
        if gap_pct < -OUTPERFORM_GAP_PCT:
            return "OUTPERFORMS"
        if abs(gap_pct) <= MEETS_GAP_PCT:
            return "MEETS_HEADLINE"
        if gap_pct <= MINOR_GAP_PCT:
            return "MINOR_GAP"
        if gap_pct <= MODERATE_GAP_PCT:
            return "MODERATE_GAP"
        return "SEVERE_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification in ("OUTPERFORMS", "MEETS_HEADLINE"):
            return "TRUST_HEADLINE"
        if classification == "MINOR_GAP":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "MODERATE_GAP":
            return "DISCOUNT_HEADLINE"
        # SEVERE_GAP
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        overstated: bool,
        realized: float,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "MEETS_HEADLINE":
            flags.append("MEETS_HEADLINE")
        if classification == "OUTPERFORMS":
            flags.append("OUTPERFORMS")
        if classification == "MINOR_GAP":
            flags.append("MINOR_GAP")
        if classification == "MODERATE_GAP":
            flags.append("MODERATE_GAP")
        if classification == "SEVERE_GAP":
            flags.append("SEVERE_GAP")
        if overstated:
            flags.append("HEADLINE_OVERSTATED")
        if realized < 0:
            flags.append("NEGATIVE_REALIZED")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "realized_apr_pct": None,
            "share_price_start_usd": 0.0,
            "share_price_end_usd": 0.0,
            "window_days": 0.0,
            "period_return_pct": None,
            "gap_pct": 0.0,
            "realization_ratio": None,
            "realization_pct": None,
            "overstated": False,
            "meets_headline": False,
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
                "most_honest_vault": None,
                "least_honest_vault": None,
                "avg_score": 0.0,
                "severe_gap_count": 0,
                "position_count": len(results),
            }
        # Higher score = realized closer to headline → highest score is honest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        severe = sum(
            1 for r in results if r["classification"] == "SEVERE_GAP")
        return {
            "most_honest_vault": by_score[-1]["token"],
            "least_honest_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "severe_gap_count": severe,
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
            "vault": "USDC-Vault-Honest",
            "headline_apr_pct": 10.0,
            "share_price_start_usd": 1.0,
            "share_price_end_usd": 1.0082,
            "window_days": 30.0,
        },
        {
            "vault": "GMX-Vault-SevereGap",
            "headline_apr_pct": 18.0,
            "share_price_start_usd": 1.0,
            "share_price_end_usd": 1.0074,
            "window_days": 30.0,
        },
        {
            "vault": "DAI-Vault-NoData",
            "headline_apr_pct": 0.0,
            "share_price_start_usd": 0.0,
            "share_price_end_usd": 0.0,
            "window_days": 30.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1169 Vault Yield Realization Gap Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultYieldRealizationGapAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
