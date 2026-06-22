"""
MP-1181: DeFiProtocolVaultAPRSourceDispersionAnalyzer
=====================================================
Advisory/read-only analytics module.

When several independent sources / aggregators report DIFFERENT APR values for
the same vault, the quote is unreliable. High dispersion across sources (the
spread / coefficient of variation of the reported APRs) → low confidence in the
headline. A large gap between the headline and the median of the sources →
the headline source itself may be broken or stale.

Angle: "Source A says 8%, B says 8.2%, C says 22% and the headline is 22% →
the headline is an outlier; trust the ~8% consensus, not the headline."

HIGHER score = tighter consensus / more trustworthy headline.

Distinct from:
  * defi_protocol_vault_yield_realization_gap_analyzer — REALIZED vs advertised
    APR for a SINGLE source over time.
  * apy_anomaly_detector — one-off anomalies in a single series.
  THIS module isolates the CROSS-SOURCE DISAGREEMENT of APR quotes at a single
  point in time — how much independent reporters disagree right now.

dispersion_ratio is the coefficient of variation (population standard deviation
of the source APRs divided by their mean).

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_apr_source_dispersion_log.json"
)
LOG_CAP = 100

# Minimum number of valid source APRs required to assess dispersion.
MIN_SOURCES = 2

# dispersion_ratio (coefficient of variation) classification thresholds.
TIGHT_CONSENSUS_RATIO = 0.05    # CoV at/below this → tight consensus
MINOR_DISPERSION_RATIO = 0.15   # CoV at/below this → minor dispersion
MODERATE_DISPERSION_RATIO = 0.30  # CoV at/below this → moderate; above → high

# Scoring references.
DISPERSION_CEILING = MODERATE_DISPERSION_RATIO  # CoV at/above this zeroes the
#                                                 agreement component.
HEADLINE_GAP_CEILING = 30.0     # headline_vs_median_pct at/above this zeroes
#                                 the alignment component.

# headline-is-outlier threshold (headline_vs_median_pct).
HEADLINE_OUTLIER_PCT = 15.0

# Wide-spread flag threshold (apr_spread_pct = max - min).
WIDE_SPREAD_PCT = 10.0

# Cap on the dispersion_ratio to keep it finite.
DISPERSION_RATIO_CAP = 100.0


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


def _median(values: List[float]) -> float:
    """Median of a non-empty list (no statistics dependency)."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _stdev(values: List[float], mean: float) -> float:
    """Population standard deviation (no statistics dependency)."""
    if not values:
        return 0.0
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(var)


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

class DeFiProtocolVaultAPRSourceDispersionAnalyzer:
    """
    Measures the CROSS-SOURCE DISAGREEMENT of a vault's APR quotes at one moment.
    Given the headline APR and a list of APRs from independent sources, the
    coefficient of variation of the sources (dispersion_ratio) and the gap
    between the headline and the source median drive a confidence in the
    headline. High dispersion or a headline that is an outlier vs the consensus
    means the headline is unreliable. This discounts confidence; it does not
    change the headline itself.

    HIGHER score = tighter consensus / more trustworthy headline.

    Per-position input dict fields:
        vault / token     : str
        headline_apr_pct  : float (max(0,..)); <=0 → INSUFFICIENT_DATA.
        source_aprs_pct   : List[float] — APRs from independent sources;
                            None/non-numeric/negative entries are filtered out.
                            <2 valid → INSUFFICIENT_SOURCES (neutral safe
                            result, score 0.0, excluded from aggregate).
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

        # Insufficient data fast-path: a non-positive headline gives no basis.
        if headline <= 0:
            return self._insufficient(token)

        # Filter source APRs: drop None / non-numeric / negative / non-finite.
        raw = p.get("source_aprs_pct")
        sources: List[float] = []
        if isinstance(raw, (list, tuple)):
            for item in raw:
                if item is None or isinstance(item, bool):
                    continue
                if not isinstance(item, (int, float)):
                    continue
                val = float(item)
                if not math.isfinite(val) or val < 0:
                    continue
                sources.append(val)

        source_count = len(sources)

        # Insufficient sources: a neutral safe result (does not penalise
        # allocation; excluded from the aggregate like INSUFFICIENT_DATA).
        if source_count < MIN_SOURCES:
            return self._insufficient_sources(token, headline, source_count)

        median_apr = _median(sources)
        mean_apr = _mean(sources)
        apr_spread = max(sources) - min(sources)

        # dispersion_ratio = coefficient of variation (population stdev / mean).
        stdev = _stdev(sources, mean_apr)
        dispersion_ratio = _safe_div(stdev, mean_apr, None)
        if dispersion_ratio is None or not math.isfinite(dispersion_ratio):
            dispersion_ratio = 0.0
        dispersion_ratio = _clamp(dispersion_ratio, 0.0, DISPERSION_RATIO_CAP)
        # Classify on the reported (4-dp rounded) ratio so documented
        # thresholds behave exactly at the boundary despite float error.
        dispersion_ratio = round(dispersion_ratio, 4)

        # headline_vs_median_pct = abs(headline - median) / median * 100.
        headline_vs_median = _safe_div(
            abs(headline - median_apr) * 100.0, median_apr, None)
        if headline_vs_median is None or not math.isfinite(headline_vs_median):
            headline_vs_median = 0.0
        headline_vs_median = _clamp(headline_vs_median, 0.0, 1e6)

        headline_is_outlier = bool(headline_vs_median > HEADLINE_OUTLIER_PCT)
        wide_spread = bool(apr_spread >= WIDE_SPREAD_PCT)

        score = self._score(dispersion_ratio, headline_vs_median)
        classification = self._classify(dispersion_ratio)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, headline_is_outlier)
        flags = self._flags(
            classification,
            headline_is_outlier,
            wide_spread,
        )

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "source_count": source_count,
            "median_apr_pct": round(median_apr, 4),
            "mean_apr_pct": round(mean_apr, 4),
            "apr_spread_pct": round(apr_spread, 4),
            "dispersion_ratio": round(dispersion_ratio, 4),
            "headline_vs_median_pct": round(headline_vs_median, 4),
            "headline_is_outlier": headline_is_outlier,
            "wide_spread": wide_spread,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        dispersion_ratio: float,
        headline_vs_median: float,
    ) -> float:
        """
        0–100, HIGHER = tighter consensus / more trustworthy headline.
        Components:
          agreement (60) — (1 - clamp(dispersion_ratio / DISPERSION_CEILING)) ×
            60; decays with the cross-source coefficient of variation.
          alignment (40) — (1 - clamp(headline_vs_median / HEADLINE_GAP_CEILING))
            × 40; decays as the headline drifts from the source median.
        Zero dispersion with headline == median → 100.
        """
        disp_frac = _clamp(dispersion_ratio / DISPERSION_CEILING, 0.0, 1.0)
        agreement_comp = 60.0 * (1.0 - disp_frac)

        gap_frac = _clamp(headline_vs_median / HEADLINE_GAP_CEILING, 0.0, 1.0)
        alignment_comp = 40.0 * (1.0 - gap_frac)

        total = agreement_comp + alignment_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, dispersion_ratio: float) -> str:
        if dispersion_ratio <= TIGHT_CONSENSUS_RATIO:
            return "TIGHT_CONSENSUS"
        if dispersion_ratio <= MINOR_DISPERSION_RATIO:
            return "MINOR_DISPERSION"
        if dispersion_ratio <= MODERATE_DISPERSION_RATIO:
            return "MODERATE_DISPERSION"
        return "HIGH_DISPERSION"

    def _recommend(
        self,
        classification: str,
        headline_is_outlier: bool,
    ) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if classification == "INSUFFICIENT_SOURCES":
            return "VERIFY_DATA"
        # A headline outlier at moderate-or-worse dispersion overrides to
        # AVOID_OR_VERIFY regardless of the milder base recommendation.
        if headline_is_outlier and classification in (
                "MODERATE_DISPERSION", "HIGH_DISPERSION"):
            return "AVOID_OR_VERIFY"
        if classification == "TIGHT_CONSENSUS":
            return "TRUST_HEADLINE"
        if classification == "MINOR_DISPERSION":
            return "MINOR_CONFIDENCE_DISCOUNT"
        if classification == "MODERATE_DISPERSION":
            return "VERIFY_ACROSS_SOURCES"
        # HIGH_DISPERSION
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        headline_is_outlier: bool,
        wide_spread: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "TIGHT_CONSENSUS":
            flags.append("TIGHT_CONSENSUS")
        if classification == "MINOR_DISPERSION":
            flags.append("MINOR_DISPERSION")
        if classification == "MODERATE_DISPERSION":
            flags.append("MODERATE_DISPERSION")
        if classification == "HIGH_DISPERSION":
            flags.append("HIGH_DISPERSION")
        if headline_is_outlier:
            flags.append("HEADLINE_OUTLIER")
        if wide_spread:
            flags.append("WIDE_SPREAD")

        return flags

    def _insufficient_sources(
        self,
        token: str,
        headline: float,
        source_count: int,
    ) -> dict:
        # Neutral safe result: score 0.0 (like INSUFFICIENT_DATA) so the
        # aggregate excludes it; metrics that cannot be computed are None.
        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "source_count": source_count,
            "median_apr_pct": None,
            "mean_apr_pct": None,
            "apr_spread_pct": None,
            "dispersion_ratio": None,
            "headline_vs_median_pct": None,
            "headline_is_outlier": False,
            "wide_spread": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_SOURCES",
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_SOURCES"],
        }

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "source_count": 0,
            "median_apr_pct": None,
            "mean_apr_pct": None,
            "apr_spread_pct": None,
            "dispersion_ratio": None,
            "headline_vs_median_pct": None,
            "headline_is_outlier": False,
            "wide_spread": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results
                  if r["classification"] not in (
                      "INSUFFICIENT_DATA", "INSUFFICIENT_SOURCES")]
        if not scored:
            return {
                "most_consistent_vault": None,
                "most_dispersed_vault": None,
                "avg_score": 0.0,
                "high_dispersion_count": 0,
                "position_count": len(results),
            }
        # Higher score = more consistent → highest score is most consistent.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        high_dispersion = sum(
            1 for r in results
            if r["classification"] == "HIGH_DISPERSION")
        return {
            "most_consistent_vault": by_score[-1]["token"],
            "most_dispersed_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "high_dispersion_count": high_dispersion,
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
            "vault": "USDC-Vault-TightConsensus",
            "headline_apr_pct": 8.0,
            "source_aprs_pct": [8.0, 8.1, 7.95, 8.05],
        },
        {
            "vault": "ETH-Vault-MinorDispersion",
            "headline_apr_pct": 12.0,
            "source_aprs_pct": [12.0, 11.0, 13.0, 12.2],
        },
        {
            "vault": "ARB-Vault-ModerateDispersion",
            "headline_apr_pct": 14.0,
            "source_aprs_pct": [14.0, 10.0, 18.0, 12.0],
        },
        {
            "vault": "CRV-Vault-HighDispersion-Outlier",
            "headline_apr_pct": 30.0,
            "source_aprs_pct": [10.0, 9.0, 30.0, 8.0],
        },
        {
            "vault": "CVX-Vault-OneSource",
            "headline_apr_pct": 20.0,
            "source_aprs_pct": [20.0],
        },
        {
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": 0.0,
            "source_aprs_pct": [],
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1181 Vault APR Source Dispersion Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultAPRSourceDispersionAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
