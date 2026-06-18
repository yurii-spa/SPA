"""
MP-1180: DeFiProtocolVaultAPRQuoteStalenessAnalyzer
===================================================
Advisory/read-only analytics module.

A vault's headline APR is a QUOTE — a number computed at some moment from a
trailing window. If that quote was last refreshed N hours ago and the refresh
is overdue relative to the expected cadence, the spot/headline APR may no longer
reflect the current yield. The staler the quote (and the more volatile the
underlying APR), the less the headline can be trusted.

Angle: "12% APR, but the quote is 96h old against a 24h expected refresh and the
APR has been swinging ±5pp → the headline is severely stale, refresh or verify
before relying on it."

HIGHER score = fresher / more trustworthy quote.

Distinct from:
  * defi_protocol_vault_share_price_staleness_analyzer — the age of the reported
    SHARE PRICE / NAV of the vault.
  * defi_protocol_oracle_price_freshness_analyzer — the age of the ORACLE PRICE
    of an asset.
  THIS module isolates the AGE / FRESHNESS of the APR (yield) QUOTE itself —
  how long ago the headline-APR number was last computed/refreshed, scaled by
  the expected refresh cadence and the APR's own volatility.

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
    "data", "vault_apr_quote_staleness_log.json"
)
LOG_CAP = 100

# Default expected refresh cadence (hours) when none / non-positive supplied.
DEFAULT_EXPECTED_REFRESH_HOURS = 24.0

# staleness_ratio (quote_age / expected_refresh) classification thresholds.
FRESH_RATIO = 1.0             # ratio at/below this → fresh
SLIGHTLY_STALE_RATIO = 2.0    # ratio at/below this → slightly stale
STALE_RATIO = 4.0             # ratio at/below this → stale; above → severely

# Scoring references.
STALENESS_CEILING = STALE_RATIO   # staleness_ratio at/above this zeroes the
#                                   freshness component.
APR_VOLATILITY_CEILING = 20.0     # apr_volatility_pct at/above this saturates
#                                   the volatility penalty / adjustment.

# High-APR-volatility flag + override threshold (apr_volatility_pct).
HIGH_APR_VOLATILITY_PCT = 10.0

# Cap on the staleness_ratio to keep it finite.
STALENESS_RATIO_CAP = 100.0


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

class DeFiProtocolVaultAPRQuoteStalenessAnalyzer:
    """
    Measures how STALE a vault's headline-APR QUOTE is. The headline APR is a
    number computed at some moment from a trailing window; if it was last
    refreshed long ago relative to the expected cadence (staleness_ratio =
    quote_age / expected_refresh) the spot APR may no longer be valid. A high
    APR volatility makes staleness more dangerous, so the staleness is adjusted
    upward by the volatility. The result discounts the confidence in the
    headline; it does not change the headline itself.

    HIGHER score = fresher / more trustworthy quote.

    Per-position input dict fields:
        vault / token          : str
        headline_apr_pct       : float (max(0,..)); <=0 → INSUFFICIENT_DATA.
        quote_age_hours        : float (max(0,..)) — how long ago the APR quote
                                 was last refreshed.
        expected_refresh_hours : float (max(0,..); default 24.0) — expected
                                 refresh cadence; <=0 → falls back to default.
        apr_volatility_pct     : float (default 0; max(0,..)) — the spread /
                                 dispersion of the APR; a higher value makes
                                 staleness riskier.
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
        # judge for staleness.
        if headline <= 0:
            return self._insufficient(token)

        quote_age = max(0.0, _f(p.get("quote_age_hours")))
        if not math.isfinite(quote_age):
            quote_age = 0.0

        expected_refresh = max(
            0.0, _f(p.get("expected_refresh_hours"),
                    DEFAULT_EXPECTED_REFRESH_HOURS))
        if expected_refresh <= 0 or not math.isfinite(expected_refresh):
            expected_refresh = DEFAULT_EXPECTED_REFRESH_HOURS

        apr_vol = max(0.0, _f(p.get("apr_volatility_pct")))
        if not math.isfinite(apr_vol):
            apr_vol = 0.0

        # staleness_ratio = quote_age / expected_refresh.
        staleness_ratio = _safe_div(quote_age, expected_refresh, None)
        if staleness_ratio is None or not math.isfinite(staleness_ratio):
            # expected_refresh is always > 0 here, so this is defensive only.
            staleness_ratio = 0.0
        staleness_ratio = _clamp(staleness_ratio, 0.0, STALENESS_RATIO_CAP)

        is_fresh = bool(staleness_ratio <= FRESH_RATIO)
        hours_overdue = max(0.0, quote_age - expected_refresh)

        # Volatility-adjusted staleness: high APR volatility inflates the
        # effective staleness (a stale quote of a volatile APR is worse).
        vol_factor = _clamp(apr_vol / APR_VOLATILITY_CEILING, 0.0, 1.0)
        volatility_adjusted_staleness = staleness_ratio * (1.0 + vol_factor)
        volatility_adjusted_staleness = _clamp(
            volatility_adjusted_staleness, 0.0,
            STALENESS_RATIO_CAP * 2.0)

        high_apr_volatility = bool(apr_vol >= HIGH_APR_VOLATILITY_PCT)

        score = self._score(staleness_ratio, apr_vol, is_fresh, quote_age)
        # confidence_pct mirrors the score (0–100, higher = fresher / more
        # trustworthy) but is exposed as a dedicated confidence metric.
        confidence_pct = round(score, 4)

        classification = self._classify(staleness_ratio)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, high_apr_volatility)
        flags = self._flags(
            classification,
            hours_overdue,
            high_apr_volatility,
        )

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "quote_age_hours": round(quote_age, 4),
            "expected_refresh_hours": round(expected_refresh, 4),
            "apr_volatility_pct": round(apr_vol, 4),
            "staleness_ratio": round(staleness_ratio, 4),
            "is_fresh": is_fresh,
            "hours_overdue": round(hours_overdue, 4),
            "volatility_adjusted_staleness": round(
                volatility_adjusted_staleness, 4),
            "confidence_pct": confidence_pct,
            "high_apr_volatility": high_apr_volatility,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        staleness_ratio: float,
        apr_vol: float,
        is_fresh: bool,
        quote_age: float,
    ) -> float:
        """
        0–100, HIGHER = fresher / more trustworthy. Components:
          freshness (70) — (1 - clamp(staleness_ratio / STALENESS_CEILING)) ×
            70; decays as the quote ages past the expected cadence.
          volatility (30) — 30 - 30 × clamp(apr_vol / APR_VOLATILITY_CEILING) ×
            clamp(staleness_ratio / STALENESS_CEILING); a stale quote of a
            volatile APR is penalised, while a fresh quote keeps its full
            volatility credit.
        A fresh quote (ratio<=1) with zero age → 100.
        """
        if is_fresh and quote_age <= 0.0:
            return 100.0

        stale_frac = _clamp(staleness_ratio / STALENESS_CEILING, 0.0, 1.0)
        freshness_comp = 70.0 * (1.0 - stale_frac)

        vol_frac = _clamp(apr_vol / APR_VOLATILITY_CEILING, 0.0, 1.0)
        vol_penalty = vol_frac * stale_frac
        volatility_comp = 30.0 - 30.0 * vol_penalty

        total = freshness_comp + volatility_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, staleness_ratio: float) -> str:
        if staleness_ratio <= FRESH_RATIO:
            return "FRESH"
        if staleness_ratio <= SLIGHTLY_STALE_RATIO:
            return "SLIGHTLY_STALE"
        if staleness_ratio <= STALE_RATIO:
            return "STALE"
        return "SEVERELY_STALE"

    def _recommend(
        self,
        classification: str,
        high_apr_volatility: bool,
    ) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        # High APR volatility combined with a (severely) stale quote overrides
        # to AVOID_OR_VERIFY regardless of the milder base recommendation.
        if high_apr_volatility and classification in (
                "STALE", "SEVERELY_STALE"):
            return "AVOID_OR_VERIFY"
        if classification == "FRESH":
            return "TRUST_QUOTE"
        if classification == "SLIGHTLY_STALE":
            return "MINOR_STALENESS_DISCOUNT"
        if classification == "STALE":
            return "REFRESH_BEFORE_USE"
        # SEVERELY_STALE
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        hours_overdue: float,
        high_apr_volatility: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "FRESH":
            flags.append("FRESH")
        if classification == "SLIGHTLY_STALE":
            flags.append("SLIGHTLY_STALE")
        if classification == "STALE":
            flags.append("STALE")
        if classification == "SEVERELY_STALE":
            flags.append("SEVERELY_STALE")
        if hours_overdue > 0:
            flags.append("OVERDUE")
        if high_apr_volatility:
            flags.append("HIGH_APR_VOLATILITY")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "quote_age_hours": 0.0,
            "expected_refresh_hours": round(DEFAULT_EXPECTED_REFRESH_HOURS, 4),
            "apr_volatility_pct": 0.0,
            "staleness_ratio": None,
            "is_fresh": False,
            "hours_overdue": None,
            "volatility_adjusted_staleness": None,
            "confidence_pct": None,
            "high_apr_volatility": False,
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
                "freshest_vault": None,
                "stalest_vault": None,
                "avg_score": 0.0,
                "severely_stale_count": 0,
                "position_count": len(results),
            }
        # Higher score = fresher → highest score is the freshest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        severely_stale = sum(
            1 for r in results
            if r["classification"] == "SEVERELY_STALE")
        return {
            "freshest_vault": by_score[-1]["token"],
            "stalest_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "severely_stale_count": severely_stale,
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
            "vault": "USDC-Vault-Fresh",
            "headline_apr_pct": 8.0,
            "quote_age_hours": 6.0,
            "expected_refresh_hours": 24.0,
            "apr_volatility_pct": 1.0,
        },
        {
            "vault": "ETH-Vault-SlightlyStale",
            "headline_apr_pct": 12.0,
            "quote_age_hours": 36.0,
            "expected_refresh_hours": 24.0,
            "apr_volatility_pct": 2.0,
        },
        {
            "vault": "ARB-Vault-Stale",
            "headline_apr_pct": 14.0,
            "quote_age_hours": 72.0,
            "expected_refresh_hours": 24.0,
            "apr_volatility_pct": 4.0,
        },
        {
            "vault": "CRV-Vault-SeverelyStale",
            "headline_apr_pct": 16.0,
            "quote_age_hours": 200.0,
            "expected_refresh_hours": 24.0,
            "apr_volatility_pct": 6.0,
        },
        {
            "vault": "CVX-Vault-Stale-HighVol",
            "headline_apr_pct": 20.0,
            "quote_age_hours": 120.0,
            "expected_refresh_hours": 24.0,
            "apr_volatility_pct": 18.0,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": 0.0,
            "quote_age_hours": 0.0,
            "expected_refresh_hours": 24.0,
            "apr_volatility_pct": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1180 Vault APR Quote Staleness Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultAPRQuoteStalenessAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
