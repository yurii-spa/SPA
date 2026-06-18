"""
MP-1193: DeFiProtocolVaultHeadlineSpotSnapshotVsTWAPAnalyzer
============================================================
Advisory/read-only analytics module.

A vault's HEADLINE APR is often a SPOT snapshot of the instantaneous yield
rate at the measurement instant. The yield a holder actually captures over the
window is the TIME-WEIGHTED AVERAGE (TWAP) of that rate. When the headline is
snapshotted during a transient rate SPIKE, spot >> twap and realized yield
falls short. This module measures how REPRESENTATIVE the spot snapshot is of
the time-weighted average — a headline-honesty/quality signal.

Angle: "headline says 18% APR (a spot snapshot taken at a rate spike) but the
time-weighted average of the rate series over the window was only 9% → the
headline is not representative; discount or verify."

HIGHER score = spot is representative of (or below) the TWAP → trustworthy
headline.

Distinct from:
  * yield_realization_gap — headline vs realized-from-share-price growth. That
    measures promised-vs-captured aggregately. This isolates the SPOT-snapshot-
    vs-TWAP of the rate series within a single window.
  * apr_lookback_window_selection_bias — choosing a favorable WINDOW LENGTH.
    This holds the window fixed and looks at spot vs the TWAP within it.
  * apr_source_dispersion — disagreement ACROSS data sources. This uses a
    single rate series.
  * utilization_peak_headline_revert — utilization-specific mean reversion.
    This is rate-series agnostic about the spike's cause.

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
    "data", "vault_headline_spot_snapshot_vs_twap_log.json"
)
LOG_CAP = 100

# Tolerance: a premium above this (pp) marks the spot snapshot as overstating.
REP_TOLERANCE_PCT = 1.0
# Scoring reference: positive premium normalised against this ceiling for the
# small-premium component (premium at/above this contributes nothing).
PREMIUM_SCORE_CEILING_PCT = 10.0

# Classification thresholds (premium in pp, spot - twap).
MINOR_PREMIUM_PCT = 3.0      # premium at/below this → minor
MODERATE_PREMIUM_PCT = 8.0   # premium at/below this → moderate; above → severe

# spot_at_peak: spot within this fraction of the sample peak.
SPOT_AT_PEAK_FRACTION = 0.98

# Minimum finite samples required to derive a TWAP from the sample series.
MIN_SAMPLES = 2


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

class DeFiProtocolVaultHeadlineSpotSnapshotVsTWAPAnalyzer:
    """
    Measures how representative a vault's HEADLINE (spot snapshot) APR is of the
    TIME-WEIGHTED AVERAGE of the intra-window rate series. The TWAP can be
    supplied directly (override) or derived as the mean of the time-ordered
    rate samples (equal spacing assumed). The premium is spot minus twap; a
    positive premium means the spot snapshot overstates the time-weighted
    average. The module reports this aggregately as a headline-honesty signal.

    HIGHER score = spot is representative of (or below) the TWAP.

    Per-position input dict fields:
        vault / token       : str
        headline_apr_pct    : float (default 0)          — quoted SPOT APR
        rate_samples_pct    : Optional[List[float]]       — time-ordered
                              intra-window APR samples (equal spacing assumed)
        twap_apr_pct        : Optional[float]             — direct TWAP override
                              (finite → wins over samples)
        window_days         : float (default 30; max(0,..)) — informational
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
        spot = _f(p.get("headline_apr_pct"))
        window_days = max(0.0, _f(p.get("window_days"), 30.0))

        # Collect finite samples from the rate series.
        raw_samples = p.get("rate_samples_pct")
        finite_samples: List[float] = []
        if isinstance(raw_samples, (list, tuple)):
            for s in raw_samples:
                sv = _f(s)
                if math.isfinite(sv):
                    finite_samples.append(sv)

        # Determine the TWAP: a finite override wins over the sample mean.
        override_raw = p.get("twap_apr_pct")
        override_present = False
        twap_used: Optional[float] = None
        twap_source = "none"
        if override_raw is not None:
            ov = _f(override_raw)
            if math.isfinite(ov):
                twap_used = ov
                twap_source = "override"
                override_present = True
        if twap_used is None and len(finite_samples) >= MIN_SAMPLES:
            twap_used = _mean(finite_samples)
            twap_source = "samples"

        # Insufficient data: non-finite/non-positive spot or no derivable TWAP.
        if not math.isfinite(spot) or spot <= 0 or twap_used is None:
            return self._insufficient(token)

        premium_pct = spot - twap_used

        premium_ratio = _safe_div(spot, twap_used, None)
        if premium_ratio is not None and not math.isfinite(premium_ratio):
            premium_ratio = None

        representativeness_ratio = _safe_div(twap_used, spot, None)
        if (representativeness_ratio is not None
                and not math.isfinite(representativeness_ratio)):
            representativeness_ratio = None
        if representativeness_ratio is None:
            representativeness_pct = None
        else:
            representativeness_ratio = _clamp(
                representativeness_ratio, 0.0, 1e9)
            representativeness_pct = representativeness_ratio * 100.0

        # Peak / trough / range of the sample series, if present.
        if finite_samples:
            peak = max(finite_samples)
            trough = min(finite_samples)
            sample_range_pct = peak - trough
            spot_at_peak = bool(
                peak > 0 and spot >= peak * SPOT_AT_PEAK_FRACTION)
        else:
            peak = None
            trough = None
            sample_range_pct = None
            spot_at_peak = False

        overstated = bool(premium_pct > REP_TOLERANCE_PCT)

        score = self._score(spot, twap_used, premium_pct)
        classification = self._classify(premium_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification, overstated, spot_at_peak, twap_used,
            len(finite_samples), override_present)

        return {
            "token": token,
            "headline_apr_pct": round(spot, 4),
            "twap_apr_pct": round(twap_used, 4),
            "twap_source": twap_source,
            "window_days": round(window_days, 4),
            "premium_pct": round(premium_pct, 4),
            "premium_ratio": (
                None if premium_ratio is None else round(premium_ratio, 4)),
            "representativeness_ratio": (
                None if representativeness_ratio is None
                else round(representativeness_ratio, 4)),
            "representativeness_pct": (
                None if representativeness_pct is None
                else round(representativeness_pct, 4)),
            "peak_sample_pct": (None if peak is None else round(peak, 4)),
            "trough_sample_pct": (
                None if trough is None else round(trough, 4)),
            "sample_range_pct": (
                None if sample_range_pct is None
                else round(sample_range_pct, 4)),
            "sample_count": len(finite_samples),
            "spot_at_peak": spot_at_peak,
            "overstated": overstated,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        spot: float,
        twap: float,
        premium_pct: float,
    ) -> float:
        """
        0–100, HIGHER = spot more representative of / below the TWAP. Components:
          representativeness (70) — twap/spot clamped 0..1, × 70.
          small premium (30) — positive premium normalised against the ceiling.
        A spot at/below the TWAP gets full representativeness (70, ratio clamps
        at 1) and full small-premium (30, premium <= 0) → high.
        """
        if spot > 0:
            representativeness_comp = 70.0 * _clamp(
                _safe_div(twap, spot, 0.0), 0.0, 1.0)
        else:
            representativeness_comp = 0.0
        small_premium_comp = 30.0 * _clamp(
            1.0 - max(0.0, premium_pct) / PREMIUM_SCORE_CEILING_PCT, 0.0, 1.0)
        total = representativeness_comp + small_premium_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, premium_pct: float) -> str:
        if premium_pct < -REP_TOLERANCE_PCT:
            return "UNDERSTATED"
        if abs(premium_pct) <= REP_TOLERANCE_PCT:
            return "REPRESENTATIVE"
        if premium_pct <= MINOR_PREMIUM_PCT:
            return "MINOR_PREMIUM"
        if premium_pct <= MODERATE_PREMIUM_PCT:
            return "MODERATE_PREMIUM"
        return "SEVERE_PREMIUM"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification in ("UNDERSTATED", "REPRESENTATIVE"):
            return "TRUST_HEADLINE"
        if classification == "MINOR_PREMIUM":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "MODERATE_PREMIUM":
            return "DISCOUNT_HEADLINE"
        # SEVERE_PREMIUM
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        overstated: bool,
        spot_at_peak: bool,
        twap: float,
        sample_count: int,
        override_present: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "UNDERSTATED":
            flags.append("UNDERSTATED")
        if classification == "REPRESENTATIVE":
            flags.append("REPRESENTATIVE")
        if classification == "MINOR_PREMIUM":
            flags.append("MINOR_PREMIUM")
        if classification == "MODERATE_PREMIUM":
            flags.append("MODERATE_PREMIUM")
        if classification == "SEVERE_PREMIUM":
            flags.append("SEVERE_PREMIUM")
        if overstated:
            flags.append("SPOT_OVERSTATES_TWAP")
        if spot_at_peak and overstated:
            flags.append("SPOT_SNAPSHOT_AT_PEAK")
        if twap < 0:
            flags.append("NEGATIVE_TWAP")
        if (not override_present) and 0 < sample_count < 3:
            flags.append("SPARSE_SAMPLES")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "twap_apr_pct": None,
            "twap_source": "none",
            "window_days": 0.0,
            "premium_pct": 0.0,
            "premium_ratio": None,
            "representativeness_ratio": None,
            "representativeness_pct": None,
            "peak_sample_pct": None,
            "trough_sample_pct": None,
            "sample_range_pct": None,
            "sample_count": 0,
            "spot_at_peak": False,
            "overstated": False,
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
                "most_representative_vault": None,
                "least_representative_vault": None,
                "avg_score": 0.0,
                "severe_premium_count": 0,
                "position_count": len(results),
            }
        # Higher score = spot more representative → highest score is best.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        severe = sum(
            1 for r in results if r["classification"] == "SEVERE_PREMIUM")
        return {
            "most_representative_vault": by_score[-1]["token"],
            "least_representative_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "severe_premium_count": severe,
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
            "vault": "USDC-Vault-Representative",
            "headline_apr_pct": 10.0,
            "rate_samples_pct": [9.8, 10.1, 9.9, 10.2, 10.0],
            "window_days": 30.0,
        },
        {
            "vault": "GMX-Vault-SeverePremium",
            "headline_apr_pct": 20.0,
            "rate_samples_pct": [8.0, 9.0, 10.0, 11.0, 20.4],
            "window_days": 30.0,
        },
        {
            "vault": "DAI-Vault-NoData",
            "headline_apr_pct": 0.0,
            "window_days": 30.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1193 Vault Headline Spot Snapshot vs TWAP Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultHeadlineSpotSnapshotVsTWAPAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
