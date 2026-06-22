"""
MP-1185: DeFiProtocolVaultAPRAnnualizationBasisRiskAnalyzer
===========================================================
Advisory/read-only analytics module.

A vault's headline APR is usually ANNUALIZED by extrapolating a short
measurement window ×(365/window). The shorter the measurement window, the more a
single anomalous period inflates the annualized figure → the less the headline
can be trusted. High intra-period volatility makes this worse: a noisy short
window extrapolated ×365 is a wild guess.

Angle: "20% APR annualized from a 1-day window (factor 365×) with high period
volatility → very low confidence; the same 20% from a 90-day window → high
confidence."

HIGHER score = longer / more trustworthy annualization basis.

Distinct from:
  * defi_protocol_vault_apr_quote_staleness_analyzer — the AGE of the quote (how
    long ago it was last refreshed).
  * defi_protocol_vault_apr_source_dispersion_analyzer — the CROSS-SOURCE
    disagreement between APR sources.
  THIS module isolates the ANNUALIZATION BASIS LENGTH / extrapolation risk of
  the headline quote itself: how short the measurement window is relative to the
  expected basis, scaled by the intra-period volatility.

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
    "data", "vault_apr_annualization_basis_risk_log.json"
)
LOG_CAP = 100

# Default expected basis length (days) when none / non-positive supplied.
DEFAULT_EXPECTED_BASIS_DAYS = 30.0

# basis_ratio (measurement_window / expected_basis) classification thresholds.
ROBUST_RATIO = 1.0     # ratio at/above this → robust basis
ADEQUATE_RATIO = 0.5   # ratio at/above this → adequate basis
SHORT_RATIO = 0.2      # ratio at/above this → short basis; below → very short.

# Scoring / flag references.
PERIOD_VOLATILITY_CEILING = 20.0    # period_volatility_pct at/above this
#                                     saturates the volatility penalty.
HIGH_PERIOD_VOLATILITY_PCT = 10.0   # high period volatility flag + override.
HIGH_ANNUALIZATION_FACTOR = 52.0    # annualization_factor at/above this → a
#                                     weekly-or-shorter basis is being scaled up.


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

class DeFiProtocolVaultAPRAnnualizationBasisRiskAnalyzer:
    """
    Measures the ANNUALIZATION BASIS RISK of a vault's headline APR: how short
    the measurement window is relative to the expected basis (basis_ratio =
    measurement_window / expected_basis), scaled by the intra-period volatility.
    A short measurement window extrapolated ×(365/window) lets a single
    anomalous period dominate the annualized figure; high period volatility
    makes the extrapolation riskier still. The result discounts the confidence
    in the headline; it does not change the headline itself.

    HIGHER score = longer / more trustworthy annualization basis.

    Per-position input dict fields:
        vault / token            : str
        headline_apr_pct         : float (max(0,..)); <=0 → INSUFFICIENT_DATA.
        measurement_window_days  : float (max(0,..)); <=0 or non-finite →
                                   INSUFFICIENT_DATA (this is the key input).
        expected_basis_days      : float (max(0,..); default 30.0) — the basis
                                   length we expect for a trustworthy quote;
                                   <=0 → falls back to default.
        period_volatility_pct    : float (default 0; max(0,..)) — the intra-
                                   period dispersion; a higher value makes the
                                   extrapolation riskier.
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
        # judge.
        if headline <= 0:
            return self._insufficient(token)

        measurement_window = max(0.0, _f(p.get("measurement_window_days")))
        # A non-positive or non-finite measurement window is the key missing
        # input — there is no basis to judge.
        if measurement_window <= 0 or not math.isfinite(measurement_window):
            return self._insufficient(token)

        expected_basis = max(
            0.0, _f(p.get("expected_basis_days"),
                    DEFAULT_EXPECTED_BASIS_DAYS))
        if expected_basis <= 0 or not math.isfinite(expected_basis):
            expected_basis = DEFAULT_EXPECTED_BASIS_DAYS

        period_vol = max(0.0, _f(p.get("period_volatility_pct")))
        if not math.isfinite(period_vol):
            period_vol = 0.0

        ratio = _safe_div(measurement_window, expected_basis, 0.0)
        if ratio is None or not math.isfinite(ratio):
            ratio = 0.0
        basis_ratio = _clamp(ratio, 0.0, 100.0)

        factor = _safe_div(365.0, measurement_window, 0.0)
        if factor is None or not math.isfinite(factor):
            factor = 0.0
        annualization_factor = _clamp(factor, 0.0, 100000.0)

        is_sufficient_basis = bool(basis_ratio >= ROBUST_RATIO)
        short_basis_frac = _clamp(1.0 - basis_ratio, 0.0, 1.0)

        vol_factor = _clamp(period_vol / PERIOD_VOLATILITY_CEILING, 0.0, 1.0)
        volatility_adjusted_basis_risk = _clamp(
            short_basis_frac * (1.0 + vol_factor), 0.0, 2.0)

        high_annualization_factor = bool(
            annualization_factor >= HIGH_ANNUALIZATION_FACTOR)
        high_period_volatility = bool(period_vol >= HIGH_PERIOD_VOLATILITY_PCT)

        score = self._score(
            basis_ratio, period_vol, short_basis_frac, is_sufficient_basis)
        # confidence_pct mirrors the score (0–100, higher = longer / more
        # trustworthy basis) but is exposed as a dedicated confidence metric.
        confidence_pct = round(score, 4)

        classification = self._classify(basis_ratio)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, high_period_volatility)
        flags = self._flags(
            classification,
            high_annualization_factor,
            high_period_volatility,
        )

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "measurement_window_days": round(measurement_window, 4),
            "expected_basis_days": round(expected_basis, 4),
            "period_volatility_pct": round(period_vol, 4),
            "basis_ratio": round(basis_ratio, 4),
            "annualization_factor": round(annualization_factor, 4),
            "is_sufficient_basis": is_sufficient_basis,
            "short_basis_frac": round(short_basis_frac, 4),
            "volatility_adjusted_basis_risk": round(
                volatility_adjusted_basis_risk, 4),
            "confidence_pct": confidence_pct,
            "high_annualization_factor": high_annualization_factor,
            "high_period_volatility": high_period_volatility,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        basis_ratio: float,
        period_vol: float,
        short_basis_frac: float,
        is_sufficient_basis: bool,
    ) -> float:
        """
        0–100, HIGHER = longer / more trustworthy basis. Components:
          basis (70) — 70 × clamp(basis_ratio); a basis at/above the expected
            length earns the full basis credit.
          volatility (30) — 30 × (1 - clamp(period_vol/CEILING) ×
            short_basis_frac); a noisy SHORT basis is penalised, while a robust
            basis keeps its full volatility credit even when volatile.
        A robust basis (ratio>=1) with zero period volatility → 100.
        """
        if is_sufficient_basis and period_vol == 0:
            return 100.0

        basis_comp = 70.0 * _clamp(basis_ratio, 0.0, 1.0)

        vol_frac = _clamp(period_vol / PERIOD_VOLATILITY_CEILING, 0.0, 1.0)
        vol_comp = 30.0 * (1.0 - vol_frac * short_basis_frac)

        total = basis_comp + vol_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, basis_ratio: float) -> str:
        # Classify on the rounded ratio so exact thresholds land cleanly.
        r = round(basis_ratio, 4)
        if r >= ROBUST_RATIO:
            return "ROBUST_BASIS"
        if r >= ADEQUATE_RATIO:
            return "ADEQUATE_BASIS"
        if r >= SHORT_RATIO:
            return "SHORT_BASIS"
        return "VERY_SHORT_BASIS"

    def _recommend(
        self,
        classification: str,
        high_period_volatility: bool,
    ) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        # High period volatility on a (very) short basis overrides to
        # AVOID_OR_VERIFY regardless of the milder base verb.
        if high_period_volatility and classification in (
                "SHORT_BASIS", "VERY_SHORT_BASIS"):
            return "AVOID_OR_VERIFY"
        if classification == "ROBUST_BASIS":
            return "TRUST_HEADLINE"
        if classification == "ADEQUATE_BASIS":
            return "MINOR_CONFIDENCE_DISCOUNT"
        if classification == "SHORT_BASIS":
            return "DISCOUNT_FOR_BASIS_RISK"
        # VERY_SHORT_BASIS
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        high_annualization_factor: bool,
        high_period_volatility: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "ROBUST_BASIS":
            flags.append("ROBUST_BASIS")
        if classification == "ADEQUATE_BASIS":
            flags.append("ADEQUATE_BASIS")
        if classification == "VERY_SHORT_BASIS":
            flags.append("VERY_SHORT_BASIS")
        if classification in ("SHORT_BASIS", "VERY_SHORT_BASIS"):
            flags.append("SHORT_BASIS")
        if high_annualization_factor:
            flags.append("HIGH_ANNUALIZATION_FACTOR")
        if high_period_volatility:
            flags.append("HIGH_PERIOD_VOLATILITY")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "measurement_window_days": 0.0,
            "expected_basis_days": round(DEFAULT_EXPECTED_BASIS_DAYS, 4),
            "period_volatility_pct": 0.0,
            "basis_ratio": None,
            "annualization_factor": None,
            "is_sufficient_basis": False,
            "short_basis_frac": None,
            "volatility_adjusted_basis_risk": None,
            "confidence_pct": None,
            "high_annualization_factor": False,
            "high_period_volatility": False,
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
                "most_robust_vault": None,
                "least_robust_vault": None,
                "avg_score": 0.0,
                "very_short_basis_count": 0,
                "position_count": len(results),
            }
        # Higher score = more robust → highest score is the most robust.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        very_short = sum(
            1 for r in results
            if r["classification"] == "VERY_SHORT_BASIS")
        return {
            "most_robust_vault": by_score[-1]["token"],
            "least_robust_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "very_short_basis_count": very_short,
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
            # ROBUST_BASIS: 30/30 = 1.0, no vol → score 100.
            "vault": "USDC-Vault-RobustBasis",
            "headline_apr_pct": 8.0,
            "measurement_window_days": 30.0,
            "expected_basis_days": 30.0,
            "period_volatility_pct": 0.0,
        },
        {
            # ADEQUATE_BASIS: 18/30 = 0.6.
            "vault": "ETH-Vault-AdequateBasis",
            "headline_apr_pct": 12.0,
            "measurement_window_days": 18.0,
            "expected_basis_days": 30.0,
            "period_volatility_pct": 2.0,
        },
        {
            # SHORT_BASIS: 9/30 = 0.3, low vol.
            "vault": "ARB-Vault-ShortBasis",
            "headline_apr_pct": 14.0,
            "measurement_window_days": 9.0,
            "expected_basis_days": 30.0,
            "period_volatility_pct": 3.0,
        },
        {
            # VERY_SHORT_BASIS: 1/30 ≈ 0.033 (factor 365×), high vol →
            # AVOID_OR_VERIFY override.
            "vault": "CVX-Vault-VeryShort-HighVol",
            "headline_apr_pct": 20.0,
            "measurement_window_days": 1.0,
            "expected_basis_days": 30.0,
            "period_volatility_pct": 18.0,
        },
        {
            # VERY_SHORT_BASIS, low vol → AVOID_OR_VERIFY (base verb).
            "vault": "CRV-Vault-VeryShort-LowVol",
            "headline_apr_pct": 16.0,
            "measurement_window_days": 4.0,
            "expected_basis_days": 30.0,
            "period_volatility_pct": 1.0,
        },
        {
            # INSUFFICIENT_DATA: measurement window 0 (key missing input).
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": 15.0,
            "measurement_window_days": 0.0,
            "expected_basis_days": 30.0,
            "period_volatility_pct": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1185 Vault APR Annualization Basis Risk Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultAPRAnnualizationBasisRiskAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
