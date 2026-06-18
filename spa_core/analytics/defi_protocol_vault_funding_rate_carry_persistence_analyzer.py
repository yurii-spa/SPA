"""
MP-1196: DeFiProtocolVaultFundingRateCarryPersistenceAnalyzer
=============================================================
Advisory/read-only analytics module.

Delta-neutral / basis-trade vaults (e.g. long spot + short perp, Ethena-style)
earn yield from PERPETUAL FUNDING RATES. The HEADLINE APR advertised by such a
vault is typically the CURRENT (spot) funding rate annualised. But funding is a
SIGNED carry that mean-reverts and FLIPS NEGATIVE in bearish / crowded regimes,
where the vault PAYS funding rather than receiving it. The honest realized carry
over a trailing window is the BLENDED (mean) of the signed funding samples, which
can be far below the headline — or outright negative.

This module measures how RELIABLE / PERSISTENT the positive-funding regime is and
how OVERSTATED the headline is versus the blended realized carry. The core risk is
the FREQUENCY of negative-funding samples and the number of SIGN FLIPS, not a
spike-vs-average question — because here the carry is SIGNED and can be a COST.

Angle: "headline 25% (current funding annualised), but trailing funding flipped
negative 50% of the time (−15%, −20%, −10%, −12% interleaved with +25%, +30%, +28%)
→ blended realized carry ≈ 3.9% and the regime is unreliable; avoid/verify."

HIGHER score = funding reliably positive (few/no negative samples) AND realized
blended carry close to the headline → the headline is honest.

Distinct from:
  * defi_protocol_vault_headline_spot_snapshot_vs_twap_analyzer — spike /
    representativeness of a generally-POSITIVE rate versus its TWAP; there the
    rate is assumed positive and the question is spike-vs-average. HERE the carry
    is SIGNED and can be a COST: the core risk is NEGATIVE-funding regime
    frequency and sign flips, not spike vs average.
  * defi_protocol_vault_utilization_peak_headline_revert_analyzer — lending
    UTILIZATION mean-reversion of an always-positive borrow APR; here the
    quantity (funding) is signed and the headline can be reversed in sign.
  * Tier-C funding_rate_arbitrage_* / defi_perpetual_funding_rate_analyzer —
    cross-venue ARBITRAGE opportunity detection (find a tradable funding spread),
    not a vault HEADLINE-HONESTY / carry-persistence signal.

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
    "data", "vault_funding_rate_carry_persistence_log.json"
)
LOG_CAP = 100

# Minimum trailing funding samples required to judge persistence.
MIN_SAMPLES = 2

# Classification thresholds on the negative-funding fraction (len(neg)/n).
PERSISTENT_NEG_FRAC = 0.05   # at/below → persistently positive
MOSTLY_NEG_FRAC = 0.20       # at/below → mostly positive
MIXED_NEG_FRAC = 0.45        # at/below → regime mixed; above → unreliable

# A single funding sample at/below this annualised % is a deep-negative regime.
DEEP_NEGATIVE_APR = -10.0
# Headline at/above this multiple of the realized blended carry is spike-sourced.
SPIKE_RATIO = 1.25


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

class DeFiProtocolVaultFundingRateCarryPersistenceAnalyzer:
    """
    Measures how reliable / persistent the positive perpetual-funding regime of a
    delta-neutral / basis-trade vault is, and how OVERSTATED its HEADLINE APR
    (current funding annualised) is versus the honest BLENDED realized carry (mean
    of the signed trailing funding samples). Funding is a SIGNED carry that flips
    negative in crowded / bearish regimes, where the vault PAYS funding; the
    realized blended carry can therefore be far below the headline or negative.

    HIGHER score = funding reliably positive (few/no negative samples) AND the
    realized blended carry close to the headline → honest headline.

    Per-position input dict fields:
        vault / token         : str
        headline_apr_pct      : float — advertised APR (= current funding
                                annualised); must be finite and > 0
        funding_rate_samples  : list[float] — trailing annualised funding rates
                                in %, SIGNED (negative = vault pays funding)
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
        samples_raw = p.get("funding_rate_samples") or []

        # Collect numeric, finite samples; skip anything non-numeric/non-finite.
        valid: List[float] = []
        for s in samples_raw:
            try:
                fs = float(s)
            except (TypeError, ValueError):
                continue
            if math.isfinite(fs):
                valid.append(fs)

        # Insufficient: headline non-finite or non-positive, or too few samples.
        if (not math.isfinite(headline) or headline <= 0
                or len(valid) < MIN_SAMPLES):
            return self._insufficient(token)

        n = len(valid)
        neg = [s for s in valid if s < 0]
        pos = [s for s in valid if s > 0]

        realized_blended_apr = _mean(valid)   # signed honest carry
        negative_funding_fraction = _clamp(len(neg) / n, 0.0, 1.0)
        positive_funding_fraction = _clamp(len(pos) / n, 0.0, 1.0)
        avg_negative_funding_apr = _mean(neg) if neg else 0.0
        avg_positive_funding_apr = _mean(pos) if pos else 0.0
        min_funding_apr = min(valid)
        max_funding_apr = max(valid)

        overstatement_pct = headline - realized_blended_apr

        realization_ratio = _safe_div(realized_blended_apr, headline, None)
        if realization_ratio is not None and not math.isfinite(
                realization_ratio):
            realization_ratio = None

        # Sign flips across adjacent samples (0 treated as non-negative).
        sign_flips = 0
        for a, b in zip(valid, valid[1:]):
            if (a < 0) != (b < 0):
                sign_flips += 1

        funding_flips_negative = bool(len(neg) > 0)
        deep_negative = bool(min_funding_apr <= DEEP_NEGATIVE_APR)
        headline_from_spike = bool(
            realized_blended_apr > 0
            and headline >= SPIKE_RATIO * realized_blended_apr)
        realized_negative_carry = bool(realized_blended_apr < 0)
        stable_carry = bool(sign_flips == 0 and len(neg) == 0)

        score = self._score(
            negative_funding_fraction, realized_blended_apr, headline)
        classification = self._classify(negative_funding_fraction)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification, funding_flips_negative, deep_negative,
            headline_from_spike, realized_negative_carry, stable_carry)

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "realized_blended_apr_pct": round(realized_blended_apr, 4),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": (
                None if realization_ratio is None
                else round(realization_ratio, 4)),
            "negative_funding_fraction": round(negative_funding_fraction, 4),
            "positive_funding_fraction": round(positive_funding_fraction, 4),
            "avg_negative_funding_apr": round(avg_negative_funding_apr, 4),
            "avg_positive_funding_apr": round(avg_positive_funding_apr, 4),
            "min_funding_apr": round(min_funding_apr, 4),
            "max_funding_apr": round(max_funding_apr, 4),
            "sample_count": n,
            "sign_flips": sign_flips,
            "funding_flips_negative": funding_flips_negative,
            "deep_negative": deep_negative,
            "headline_from_spike": headline_from_spike,
            "realized_negative_carry": realized_negative_carry,
            "stable_carry": stable_carry,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        neg_frac: float,
        realized: float,
        headline: float,
    ) -> float:
        """
        0–100, HIGHER = funding reliably positive AND realized blended carry close
        to the headline. Two components:
          * reliability = 1 − negative_funding_fraction (fewer negative samples is
            better; a regime that never pays funding scores full reliability),
          * honesty = clamp(realized / headline, 0, 1) (realized blended carry as
            a share of the headline; a negative realized carry → 0).
        Weighted 60/40 toward reliability (the persistence of the positive regime
        is the dominant risk for a funding-carry vault).
        """
        reliability = _clamp(1.0 - neg_frac, 0.0, 1.0)
        honesty = _clamp(_safe_div(realized, headline, 0.0), 0.0, 1.0)
        return _clamp(60.0 * reliability + 40.0 * honesty, 0.0, 100.0)

    def _classify(self, neg_frac: float) -> str:
        if neg_frac <= PERSISTENT_NEG_FRAC:
            return "PERSISTENT_POSITIVE"
        if neg_frac <= MOSTLY_NEG_FRAC:
            return "MOSTLY_POSITIVE"
        if neg_frac <= MIXED_NEG_FRAC:
            return "REGIME_MIXED"
        return "FUNDING_UNRELIABLE"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification == "PERSISTENT_POSITIVE":
            return "TRUST_HEADLINE"
        if classification == "MOSTLY_POSITIVE":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "REGIME_MIXED":
            return "DISCOUNT_HEADLINE"
        # FUNDING_UNRELIABLE
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        funding_flips_negative: bool,
        deep_negative: bool,
        headline_from_spike: bool,
        realized_negative_carry: bool,
        stable_carry: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "PERSISTENT_POSITIVE":
            flags.append("PERSISTENT_POSITIVE")
        if classification == "MOSTLY_POSITIVE":
            flags.append("MOSTLY_POSITIVE")
        if classification == "REGIME_MIXED":
            flags.append("REGIME_MIXED")
        if classification == "FUNDING_UNRELIABLE":
            flags.append("FUNDING_UNRELIABLE")
        if funding_flips_negative:
            flags.append("FUNDING_FLIPS_NEGATIVE")
        if deep_negative:
            flags.append("DEEP_NEGATIVE_REGIME")
        if headline_from_spike:
            flags.append("HEADLINE_FROM_SPIKE")
        if realized_negative_carry:
            flags.append("REALIZED_NEGATIVE_CARRY")
        if stable_carry:
            flags.append("STABLE_CARRY")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "realized_blended_apr_pct": None,
            "overstatement_pct": 0.0,
            "realization_ratio": None,
            "negative_funding_fraction": None,
            "positive_funding_fraction": None,
            "avg_negative_funding_apr": None,
            "avg_positive_funding_apr": None,
            "min_funding_apr": None,
            "max_funding_apr": None,
            "sample_count": 0,
            "sign_flips": None,
            "funding_flips_negative": False,
            "deep_negative": False,
            "headline_from_spike": False,
            "realized_negative_carry": False,
            "stable_carry": False,
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
                "most_honest_vault": None,
                "least_honest_vault": None,
                "avg_score": 0.0,
                "unreliable_count": 0,
                "position_count": len(results),
            }
        # Higher score = headline more honest → highest score is best.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        unreliable = sum(
            1 for r in results
            if r["classification"] == "FUNDING_UNRELIABLE")
        return {
            "most_honest_vault": by_score[-1]["token"],
            "least_honest_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "unreliable_count": unreliable,
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
            # PERSISTENT_POSITIVE: funding reliably positive around the headline.
            "vault": "ETH-Basis-Stable",
            "headline_apr_pct": 12.0,
            "funding_rate_samples": [11.0, 12.0, 13.0, 12.0, 11.5],
        },
        {
            # FUNDING_UNRELIABLE: funding flips negative half the time.
            "vault": "SOL-Basis-Volatile",
            "headline_apr_pct": 25.0,
            "funding_rate_samples": [
                25.0, -15.0, 30.0, -20.0, 5.0, -10.0, 28.0, -12.0],
        },
        {
            # MOSTLY_POSITIVE: one negative sample out of six (~0.167).
            "vault": "BTC-Basis-Minor",
            "headline_apr_pct": 10.0,
            "funding_rate_samples": [10.0, 9.0, 11.0, -2.0, 10.0, 10.0],
        },
        {
            # INSUFFICIENT_DATA: non-positive headline, no samples.
            "vault": "ARB-Basis-NoData",
            "headline_apr_pct": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1196 Vault Funding Rate Carry Persistence Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultFundingRateCarryPersistenceAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
