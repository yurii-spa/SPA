"""
MP-1184: DeFiProtocolVaultTrailingWindowBoostBackdatingAnalyzer
===============================================================
Advisory/read-only analytics module.

A vault's headline APR is typically an AVERAGE computed over a trailing window
(e.g. trailing 30 days). If a temporary incentive boost was active for only part
of that window and has already ended, the trailing figure "backdates" — it looks
backwards and keeps crediting the already-expired boost, overstating the forward
run-rate. The smaller the fraction of the window in which the boost is still
active, and the larger the boost's contribution, the worse the overstatement.

Angle: "headline 15%, base 8%, boost 7% but active only 10 of the 30 days in the
window → forward run-rate ≈ base + boost*0.33 ≈ 10.3%, discount the headline to
the run-rate before relying on it."

HIGHER score = closer to the forward run-rate / more trustworthy.

Distinct from:
  * gauge_emission_decay_forecaster — forecasts the SMOOTH future decay of
    emissions per a published schedule (a forward projection).
  * protocol_incentive_decay_monitor — monitors the ongoing decay of incentives.
  THIS module isolates the BACKDATING ARTEFACT in the trailing-APR QUOTE itself:
  an incentive boost that already (partially) ended INSIDE the lookback window
  still inflates the trailing average, so the headline overstates the forward
  run-rate. It quantifies that overstatement from the boost coverage within the
  window.

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
    "data", "vault_trailing_window_boost_backdating_log.json"
)
LOG_CAP = 100

# Default trailing window length (days) when none / non-positive supplied.
DEFAULT_WINDOW_DAYS = 30.0

# coverage_frac (boost_active_days / window_days) classification thresholds.
FULLY_CURRENT_COVERAGE = 0.95       # coverage at/above this → fully current
MOSTLY_CURRENT_COVERAGE = 0.75      # coverage at/above this → mostly current
PARTIALLY_BACKDATED_COVERAGE = 0.40  # coverage at/above this → partially
#                                      backdated; below → heavily backdated.

# High boost share flag + override threshold (boost_share_pct).
HIGH_BOOST_SHARE_PCT = 50.0

# Large overstatement flag threshold (overstatement_share_pct).
LARGE_OVERSTATEMENT_PCT = 25.0


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

class DeFiProtocolVaultTrailingWindowBoostBackdatingAnalyzer:
    """
    Measures how much a vault's trailing-window headline APR overstates the
    forward run-rate because of an incentive boost that already (partially)
    ended INSIDE the lookback window. The headline is a trailing average; if the
    boost was active for only a fraction of the window (coverage_frac =
    boost_active_days / window_days), the trailing figure "backdates" — it keeps
    crediting the expired boost. The forward run-rate is base + boost*coverage;
    the difference is the backdating overstatement. The result discounts the
    confidence in the headline; it does not change the headline itself.

    HIGHER score = closer to the forward run-rate / more trustworthy.

    Per-position input dict fields:
        vault / token       : str
        headline_apr_pct    : float (max(0,..)); <=0 → INSUFFICIENT_DATA.
        boost_apr_pct       : float (max(0,..), clamped <= headline) — the boost
                              contribution baked into the trailing headline;
                              <=0 → NO_BOOST.
        window_days         : float (max(0,..); default 30.0) — the trailing
                              window length; <=0 or non-finite → default.
        boost_active_days   : float (max(0,..), clamped <= window_days) — days
                              within the window the boost was actually active.
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
        headline = max(0.0, _f(p.get("headline_apr_pct")))

        # Insufficient data fast-path: a non-positive headline gives no quote to
        # judge for backdating.
        if headline <= 0:
            return self._insufficient(token)

        boost = max(0.0, _f(p.get("boost_apr_pct")))
        if not math.isfinite(boost):
            boost = 0.0
        # A boost cannot exceed the headline it is baked into.
        boost = min(boost, headline)

        window_days = max(0.0, _f(p.get("window_days"), DEFAULT_WINDOW_DAYS))
        if window_days <= 0 or not math.isfinite(window_days):
            window_days = DEFAULT_WINDOW_DAYS

        boost_active_days = max(0.0, _f(p.get("boost_active_days")))
        if not math.isfinite(boost_active_days):
            boost_active_days = 0.0
        boost_active_days = min(boost_active_days, window_days)

        base = max(0.0, headline - boost)

        boost_share = _safe_div(boost, headline, 0.0)
        if boost_share is None or not math.isfinite(boost_share):
            boost_share = 0.0
        boost_share_pct = _clamp(boost_share * 100.0, 0.0, 100.0)

        coverage = _safe_div(boost_active_days, window_days, 0.0)
        if coverage is None or not math.isfinite(coverage):
            coverage = 0.0
        coverage_frac = _clamp(coverage, 0.0, 1.0)
        expired_frac = _clamp(1.0 - coverage_frac, 0.0, 1.0)

        forward_run_rate = base + boost * coverage_frac
        if not math.isfinite(forward_run_rate):
            forward_run_rate = base

        apr_overstatement = max(0.0, headline - forward_run_rate)
        if not math.isfinite(apr_overstatement):
            apr_overstatement = 0.0

        ov_share = _safe_div(apr_overstatement, headline, 0.0)
        if ov_share is None or not math.isfinite(ov_share):
            ov_share = 0.0
        overstatement_share_pct = _clamp(ov_share * 100.0, 0.0, 100.0)

        boost_expired = bool(expired_frac > 0.0)
        high_boost_share = bool(boost_share_pct >= HIGH_BOOST_SHARE_PCT)

        score = self._score(boost, coverage_frac, overstatement_share_pct)

        classification = self._classify(boost, coverage_frac)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, high_boost_share)
        flags = self._flags(
            classification,
            boost,
            boost_expired,
            high_boost_share,
            overstatement_share_pct,
        )

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "boost_apr_pct": round(boost, 4),
            "base_apr_pct": round(base, 4),
            "window_days": round(window_days, 4),
            "boost_active_days": round(boost_active_days, 4),
            "boost_share_pct": round(boost_share_pct, 4),
            "coverage_frac": round(coverage_frac, 4),
            "expired_frac": round(expired_frac, 4),
            "forward_run_rate_apr_pct": round(forward_run_rate, 4),
            "apr_overstatement_pct": round(apr_overstatement, 4),
            "overstatement_share_pct": round(overstatement_share_pct, 4),
            "boost_expired": boost_expired,
            "high_boost_share": high_boost_share,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        boost: float,
        coverage_frac: float,
        overstatement_share_pct: float,
    ) -> float:
        """
        0–100, HIGHER = closer to the forward run-rate / more trustworthy.
          No boost → 100 (the headline IS the run-rate; nothing to backdate).
          persistence (60) — 60 × coverage_frac; rewards a boost that is still
            active across most of the window.
          magnitude (40) — 40 × (1 - clamp(overstatement_share/100)); penalises
            a large overstatement of the headline relative to the run-rate.
        coverage_frac == 1 → 60 + 40 = 100.
        """
        if boost <= 0:
            return 100.0

        persistence_comp = 60.0 * _clamp(coverage_frac, 0.0, 1.0)
        magnitude_comp = 40.0 * (
            1.0 - _clamp(overstatement_share_pct / 100.0, 0.0, 1.0))
        total = persistence_comp + magnitude_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, boost: float, coverage_frac: float) -> str:
        if boost <= 0:
            return "NO_BOOST"
        if coverage_frac >= FULLY_CURRENT_COVERAGE:
            return "FULLY_CURRENT"
        if coverage_frac >= MOSTLY_CURRENT_COVERAGE:
            return "MOSTLY_CURRENT"
        if coverage_frac >= PARTIALLY_BACKDATED_COVERAGE:
            return "PARTIALLY_BACKDATED"
        return "HEAVILY_BACKDATED"

    def _recommend(
        self,
        classification: str,
        high_boost_share: bool,
    ) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        # A heavily-backdated headline whose boost is a large share of the APR
        # overrides to AVOID_OR_VERIFY regardless of the milder base verb.
        if classification == "HEAVILY_BACKDATED" and high_boost_share:
            return "AVOID_OR_VERIFY"
        if classification == "NO_BOOST":
            return "TRUST_HEADLINE"
        if classification == "FULLY_CURRENT":
            return "TRUST_HEADLINE"
        if classification == "MOSTLY_CURRENT":
            return "MINOR_BOOST_DISCOUNT"
        if classification == "PARTIALLY_BACKDATED":
            return "DISCOUNT_TO_RUN_RATE"
        # HEAVILY_BACKDATED
        return "USE_FORWARD_RUN_RATE"

    def _flags(
        self,
        classification: str,
        boost: float,
        boost_expired: bool,
        high_boost_share: bool,
        overstatement_share_pct: float,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "NO_BOOST":
            flags.append("NO_BOOST")
        if classification == "FULLY_CURRENT":
            flags.append("FULLY_CURRENT")
        if classification == "MOSTLY_CURRENT":
            flags.append("MOSTLY_CURRENT")
        if classification == "PARTIALLY_BACKDATED":
            flags.append("PARTIALLY_BACKDATED")
        if classification == "HEAVILY_BACKDATED":
            flags.append("HEAVILY_BACKDATED")
        if boost_expired and boost > 0:
            flags.append("BOOST_EXPIRED")
        if high_boost_share:
            flags.append("HIGH_BOOST_SHARE")
        if overstatement_share_pct >= LARGE_OVERSTATEMENT_PCT:
            flags.append("LARGE_OVERSTATEMENT")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "boost_apr_pct": 0.0,
            "base_apr_pct": 0.0,
            "window_days": round(DEFAULT_WINDOW_DAYS, 4),
            "boost_active_days": 0.0,
            "boost_share_pct": 0.0,
            "coverage_frac": None,
            "expired_frac": None,
            "forward_run_rate_apr_pct": None,
            "apr_overstatement_pct": None,
            "overstatement_share_pct": None,
            "boost_expired": False,
            "high_boost_share": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results
                  if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_current_vault": None,
                "most_backdated_vault": None,
                "avg_score": 0.0,
                "heavily_backdated_count": 0,
                "position_count": len(results),
            }
        # Higher score = more current → highest score is the most current.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        heavily_backdated = sum(
            1 for r in results
            if r["classification"] == "HEAVILY_BACKDATED")
        return {
            "most_current_vault": by_score[-1]["token"],
            "most_backdated_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "heavily_backdated_count": heavily_backdated,
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
            # NO_BOOST → TRUST_HEADLINE, score 100.
            "vault": "USDC-Vault-NoBoost",
            "headline_apr_pct": 8.0,
            "boost_apr_pct": 0.0,
            "window_days": 30.0,
            "boost_active_days": 0.0,
        },
        {
            # FULLY_CURRENT: coverage 30/30 = 1.0.
            "vault": "ETH-Vault-FullyCurrent",
            "headline_apr_pct": 12.0,
            "boost_apr_pct": 3.0,
            "window_days": 30.0,
            "boost_active_days": 30.0,
        },
        {
            # MOSTLY_CURRENT: coverage 24/30 = 0.8.
            "vault": "ARB-Vault-MostlyCurrent",
            "headline_apr_pct": 14.0,
            "boost_apr_pct": 4.0,
            "window_days": 30.0,
            "boost_active_days": 24.0,
        },
        {
            # PARTIALLY_BACKDATED: coverage 15/30 = 0.5.
            "vault": "CRV-Vault-PartiallyBackdated",
            "headline_apr_pct": 15.0,
            "boost_apr_pct": 7.0,
            "window_days": 30.0,
            "boost_active_days": 15.0,
        },
        {
            # HEAVILY_BACKDATED + HIGH_BOOST_SHARE → AVOID_OR_VERIFY.
            # coverage 3/30 = 0.1; boost share 12/20 = 60%.
            "vault": "CVX-Vault-HeavilyBackdated-HighShare",
            "headline_apr_pct": 20.0,
            "boost_apr_pct": 12.0,
            "window_days": 30.0,
            "boost_active_days": 3.0,
        },
        {
            # INSUFFICIENT_DATA: non-positive headline.
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": 0.0,
            "boost_apr_pct": 0.0,
            "window_days": 30.0,
            "boost_active_days": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1184 Vault Trailing-Window Boost Backdating Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultTrailingWindowBoostBackdatingAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
