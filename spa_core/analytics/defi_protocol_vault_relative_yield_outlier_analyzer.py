"""
MP-1171: DeFiProtocolVaultRelativeYieldOutlierAnalyzer
======================================================
Advisory/read-only analytics module.

Compares a vault's APR against a COHORT of comparable peer vaults and flags
statistical outliers. An APR sitting far ABOVE the peer median is "too good to
be true" — it usually hides extra risk or unsustainable emissions. An APR far
BELOW the peers means better alternatives exist for the same risk profile. The
detector is a per-vault z-score against the supplied peer cohort.

Angle: "this vault pays 38% while its peers cluster at 9% (z = +4.1) → extreme
high outlier, verify the source of yield before sizing in."

HIGHER score = closer to the peer median / NOT an outlier (more trustworthy).

Distinct from:
  * generic apr_comparator / yield_ranker → those merely sort or compare APRs.
    This module is a per-vault statistical z-score OUTLIER detector against a
    passed peer cohort, using pure stdlib statistics.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
import statistics
from datetime import datetime, timezone
from typing import List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_relative_yield_outlier_log.json"
)
LOG_CAP = 100

# Scoring reference: |z| normalised against this ceiling for the in-line band.
Z_SCORE_CEILING = 3.0

# Classification thresholds (z-score).
EXTREME_HIGH_Z = 3.0    # z at/above this → extreme high outlier.
HIGH_Z = 2.0            # z at/above this → high outlier.
LOW_Z = -2.0            # z at/below this → low outlier.

# Flag thresholds.
THIN_COHORT_MAX = 5     # 0 < peer_count < this → thin cohort.
MIN_PEERS = 2           # below this → insufficient data.


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

class DeFiProtocolVaultRelativeYieldOutlierAnalyzer:
    """
    Detects statistical APR outliers of a vault against a supplied peer cohort.
    Computes the z-score of the vault's APR vs the peer mean/stdev, the excess
    over the peer median, and the percentile rank within the cohort. Strongly
    above the cohort = "too good to be true" (hidden risk); strongly below =
    better alternatives exist.

    HIGHER score = closer to the peer median / NOT an outlier (more trustworthy).

    Per-position input dict fields:
        vault / token     : str
        apr_pct           : float (default 0)
        peer_aprs_pct     : List[float] (default []; APR of comparable vaults)
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
        apr = _f(p.get("apr_pct"))

        # Sanitise the peer cohort to finite numbers only.
        raw_peers = p.get("peer_aprs_pct", [])
        peers: List[float] = []
        if isinstance(raw_peers, (list, tuple)):
            for x in raw_peers:
                v = _f(x, default=float("nan"))
                if math.isfinite(v):
                    peers.append(v)
        peer_count = len(peers)

        # Fast-path: cohort too thin to compute statistics.
        if peer_count < MIN_PEERS:
            return self._insufficient(token, apr, peer_count)

        peer_median = statistics.median(peers)
        peer_mean = statistics.mean(peers)
        peer_stdev = statistics.pstdev(peers) if peer_count >= 2 else 0.0

        # Guard against non-finite statistics.
        if not math.isfinite(peer_median):
            peer_median = 0.0
        if not math.isfinite(peer_mean):
            peer_mean = 0.0
        if not math.isfinite(peer_stdev) or peer_stdev < 0:
            peer_stdev = 0.0

        excess_apr_pct = apr - peer_median
        excess_vs_mean_pct = apr - peer_mean

        # z-score: None when there is no dispersion (all peers equal).
        if peer_stdev > 0:
            z_raw = (apr - peer_mean) / peer_stdev
            z_score = z_raw if math.isfinite(z_raw) else None
        else:
            z_score = None

        # Percentage above the peer median.
        if peer_median > 0:
            pam = excess_apr_pct / peer_median * 100.0
            pct_above_median = pam if math.isfinite(pam) else None
        else:
            pct_above_median = None

        # Percentile rank: share of peers strictly below this APR.
        below = sum(1 for x in peers if x < apr)
        percentile_rank = _clamp(below / peer_count * 100.0, 0.0, 100.0) \
            if peer_count > 0 else 0.0

        is_high_outlier = bool(z_score is not None and z_score >= HIGH_Z)
        is_low_outlier = bool(z_score is not None and z_score <= LOW_Z)

        score = self._score(peer_stdev, z_score, is_high_outlier)
        classification = self._classify(peer_count, z_score)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(classification, excess_apr_pct, peer_count)

        return {
            "token": token,
            "apr_pct": round(apr, 4),
            "peer_count": peer_count,
            "peer_median": round(peer_median, 4),
            "peer_mean": round(peer_mean, 4),
            "peer_stdev": round(peer_stdev, 4),
            "excess_apr_pct": round(excess_apr_pct, 4),
            "excess_vs_mean_pct": round(excess_vs_mean_pct, 4),
            "z_score": round(z_score, 4) if z_score is not None else None,
            "pct_above_median": (round(pct_above_median, 4)
                                 if pct_above_median is not None else None),
            "percentile_rank": round(percentile_rank, 4),
            "is_high_outlier": is_high_outlier,
            "is_low_outlier": is_low_outlier,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        peer_stdev: float,
        z_score: Optional[float],
        is_high_outlier: bool,
    ) -> float:
        """
        0–100, HIGHER = closer to median / NOT an outlier. Components:
          in-line (70) — when dispersion exists, |z| normalised vs the ceiling;
                         when there is no dispersion, a neutral 35.
          not high outlier (30) — full unless the vault is a high outlier.
        """
        if peer_stdev > 0 and z_score is not None:
            inline_comp = 70.0 * _clamp(
                1.0 - abs(z_score) / Z_SCORE_CEILING, 0.0, 1.0)
        else:
            inline_comp = 35.0
        not_high_comp = 0.0 if is_high_outlier else 30.0
        total = inline_comp + not_high_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, peer_count: int, z_score: Optional[float]) -> str:
        if peer_count < MIN_PEERS:
            return "INSUFFICIENT_DATA"
        if z_score is None:
            return "INSUFFICIENT_DATA"
        if z_score >= EXTREME_HIGH_Z:
            return "EXTREME_HIGH_OUTLIER"
        if z_score >= HIGH_Z:
            return "HIGH_OUTLIER"
        if z_score <= LOW_Z:
            return "LOW_OUTLIER"
        return "IN_LINE"

    def _recommend(self, classification: str) -> str:
        return {
            "INSUFFICIENT_DATA": "HOLD",
            "EXTREME_HIGH_OUTLIER": "VERIFY_OR_AVOID",
            "HIGH_OUTLIER": "INVESTIGATE_BEFORE_SIZING",
            "LOW_OUTLIER": "CONSIDER_PEER_ALTERNATIVE",
            "IN_LINE": "DEPLOY_OK",
        }.get(classification, "HOLD")

    def _flags(
        self,
        classification: str,
        excess_apr_pct: float,
        peer_count: int,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "EXTREME_HIGH_OUTLIER":
            flags.append("EXTREME_HIGH_OUTLIER")
        if classification == "HIGH_OUTLIER":
            flags.append("HIGH_OUTLIER")
        if classification == "LOW_OUTLIER":
            flags.append("LOW_OUTLIER")
        if classification == "IN_LINE":
            flags.append("IN_LINE")
        if excess_apr_pct > 0:
            flags.append("ABOVE_MEDIAN")
        if excess_apr_pct < 0:
            flags.append("BELOW_MEDIAN")
        if 0 < peer_count < THIN_COHORT_MAX:
            flags.append("THIN_COHORT")

        return flags

    def _insufficient(self, token: str, apr: float, peer_count: int) -> dict:
        return {
            "token": token,
            "apr_pct": round(apr, 4),
            "peer_count": peer_count,
            "peer_median": 0.0,
            "peer_mean": 0.0,
            "peer_stdev": 0.0,
            "excess_apr_pct": 0.0,
            "excess_vs_mean_pct": 0.0,
            "z_score": None,
            "pct_above_median": None,
            "percentile_rank": 0.0,
            "is_high_outlier": False,
            "is_low_outlier": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "HOLD",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results
                  if r["classification"] != "INSUFFICIENT_DATA"]
        high_outlier_count = sum(1 for r in results if r.get("is_high_outlier"))
        if not scored:
            return {
                "most_trustworthy_vault": None,
                "least_trustworthy_vault": None,
                "avg_score": 0.0,
                "high_outlier_count": high_outlier_count,
                "position_count": len(results),
            }
        # Higher score = more trustworthy (closer to median, not an outlier).
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        return {
            "most_trustworthy_vault": by_score[-1]["token"],
            "least_trustworthy_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "high_outlier_count": high_outlier_count,
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
            "vault": "USDC-Vault-InLine",
            "apr_pct": 9.5,
            "peer_aprs_pct": [9.0, 9.2, 9.8, 10.1, 8.9],
        },
        {
            "vault": "ETH-Vault-ExtremeHigh",
            "apr_pct": 42.0,
            "peer_aprs_pct": [8.0, 9.0, 10.0, 9.5, 8.5],
        },
        {
            "vault": "DAI-Vault-Low",
            "apr_pct": 2.0,
            "peer_aprs_pct": [9.0, 9.5, 10.0, 9.8, 9.2],
        },
        {
            "vault": "GMX-Vault-NoPeers",
            "apr_pct": 15.0,
            "peer_aprs_pct": [],
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1171 Vault Relative Yield Outlier Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultRelativeYieldOutlierAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
