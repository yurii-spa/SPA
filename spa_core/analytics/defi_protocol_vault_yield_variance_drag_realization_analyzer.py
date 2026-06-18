"""
MP-1197: DeFiProtocolVaultYieldVarianceDragRealizationAnalyzer
==============================================================
Advisory/read-only analytics module.

The HEADLINE APR a vault advertises is almost always the ARITHMETIC MEAN of its
per-period yield samples — the "average rate" — annualised. But a depositor who
actually stays in the vault realises the GEOMETRIC MEAN of the per-period returns,
which by the AM–GM inequality (Jensen) is ALWAYS at/below the arithmetic mean once
the per-period yields are VOLATILE. The gap between the two is the VARIANCE DRAG
(volatility drag): a structural, fee-free, downtime-free shortfall that grows with
the variance of the yield stream. A high-volatility yield therefore realises
materially less than its arithmetic-mean headline even when the protocol is
perfectly honest about the average.

This module compares the arithmetic-mean annualised reference against the
geometric-mean (actually-realisable) annualised return and reports the variance
drag — purely from the dispersion of the per-period samples.

Angle: "a monthly options/LP vault advertises 120% (the ARITHMETIC mean of its
per-epoch returns, ×12), but those per-epoch returns swing hard (+40%, −20%, +45%,
−25%, +50%, −30%) so the GEOMETRIC mean a holder actually compounds annualises to
only ≈ 51% — the ~69pp gap is pure variance drag. The drag FRACTION
(1 − geometric/arithmetic) is scale-free in the annualisation factor: SMOOTHER
per-period yield → smaller drag → headline more realisable; wilder swings around
the same average → larger drag → headline overstates the compounded return."

HIGHER score = low variance drag (smooth yield, geometric ≈ arithmetic) → the
arithmetic-mean headline is realisable. LOWER score = high variance drag (volatile
yield) → the headline overstates the compounded return a holder captures.

Distinct from:
  * defi_protocol_vault_trading_fee_apr_volatility_analyzer — measures the
    VOLATILITY / instability of a trading-fee APR itself (is the rate stable?).
    HERE we convert that dispersion into the SPECIFIC geometric-vs-arithmetic
    realisation gap (variance drag) a compounding holder eats.
  * apy_volatility_forecaster — FORECASTS future volatility; here we quantify the
    realised arithmetic→geometric shortfall on the observed samples.
  * defi_protocol_vault_headline_spot_snapshot_vs_twap_analyzer — spike /
    representativeness of a SPOT snapshot versus its TWAP (a level question). HERE
    the question is DISPERSION: even a perfectly representative average rate loses
    to its own volatility when compounded (a second-moment effect, not a level).
  * defi_protocol_vault_funding_rate_carry_persistence_analyzer — SIGN frequency /
    persistence of a signed carry; here the samples are a (generally positive)
    yield stream and the risk is the variance penalty, not negative-regime count.
  * defi_protocol_vault_deployment_ramp_drag_analyzer — a TIME-availability drag
    (non-earning days scale realised down linearly); here every period earns, but
    the DISPERSION of what it earns drags the geometric mean below the arithmetic.

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
    "data", "vault_yield_variance_drag_realization_log.json"
)
LOG_CAP = 100

# Minimum per-period yield samples required to judge dispersion.
MIN_SAMPLES = 2

# Default annualisation factor (periods per year); 365 = daily samples.
DEFAULT_PERIODS_PER_YEAR = 365.0

# Classification thresholds on the drag fraction (variance_drag / arithmetic_apr).
NEGLIGIBLE_DRAG_FRAC = 0.02   # at/below → negligible
MINOR_DRAG_FRAC = 0.08        # at/below → minor
MODERATE_DRAG_FRAC = 0.20     # at/below → moderate; above → severe

# Coefficient of variation at/above this is flagged high-volatility.
HIGH_CV = 1.0
# Headline at/above this multiple of the sample arithmetic mean is optimistic
# beyond the variance drag (the advertised figure exceeds even the arithmetic).
HEADLINE_OPTIMISTIC_RATIO = 1.05


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


def _pstdev(values: List[float]) -> float:
    n = len(values)
    if n < 1:
        return 0.0
    mu = _mean(values)
    var = sum((v - mu) ** 2 for v in values) / n
    return math.sqrt(var) if var > 0 else 0.0


def _safe_div(num: float, den: float, sentinel):
    if den <= 0:
        return sentinel
    return num / den


def _geometric_mean_pct(samples_pct: List[float]):
    """
    Per-period geometric mean of a yield series given in %, returned in %.
    Returns (g_pct, wipeout) where wipeout is True iff any (1 + s/100) <= 0
    (a period lost >= 100% → the compounded path is wiped out; geometric mean
    is then undefined and the realised return is total loss).
    """
    growths = [1.0 + s / 100.0 for s in samples_pct]
    if any(g <= 0.0 for g in growths):
        return None, True
    # Sum of logs is numerically safer than a running product.
    log_sum = sum(math.log(g) for g in growths)
    g = math.exp(log_sum / len(growths)) - 1.0
    return g * 100.0, False


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

class DeFiProtocolVaultYieldVarianceDragRealizationAnalyzer:
    """
    Quantifies the VARIANCE DRAG (volatility drag) between a vault's
    ARITHMETIC-mean headline APR and the GEOMETRIC-mean APR a compounding holder
    actually realises. By AM–GM the geometric mean is at/below the arithmetic mean
    whenever the per-period yields are volatile, so a noisy yield stream realises
    less than its advertised average even with zero fees and full uptime.

    HIGHER score = smooth yield (geometric ≈ arithmetic, small drag) → the
    headline is realisable. LOWER score = volatile yield (large drag) → the
    headline overstates the compounded return.

    Per-position input dict fields:
        vault / token        : str
        headline_apr_pct     : float — advertised APR (arithmetic-mean rate
                               annualised); must be finite and > 0
        period_yield_samples : list[float] — per-PERIOD realised yields in %
                               (e.g. daily or per-epoch returns), signed
        periods_per_year     : float — annualisation factor (optional; default
                               365 = daily samples)
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
        samples_raw = p.get("period_yield_samples") or []
        ppy = _f(p.get("periods_per_year"), DEFAULT_PERIODS_PER_YEAR)
        if not math.isfinite(ppy) or ppy <= 0:
            ppy = DEFAULT_PERIODS_PER_YEAR

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
        period_mean_pct = _mean(valid)                 # per-period arithmetic
        period_volatility_pct = _pstdev(valid)         # per-period stdev
        coefficient_of_variation = (
            _safe_div(period_volatility_pct, abs(period_mean_pct), None))

        geom_pp, wipeout = _geometric_mean_pct(valid)  # per-period geometric

        arithmetic_apr_pct = period_mean_pct * ppy

        if wipeout:
            # A period lost >= 100% → compounded path wiped out (total loss).
            geometric_apr_pct = -100.0
        else:
            geometric_apr_pct = geom_pp * ppy

        variance_drag_pct = arithmetic_apr_pct - geometric_apr_pct

        # Drag fraction (scale-free) on the arithmetic reference; only meaningful
        # when the arithmetic annualised APR is positive.
        if arithmetic_apr_pct > 0:
            drag_fraction = _clamp(
                variance_drag_pct / arithmetic_apr_pct, 0.0, 1.0)
            realization_ratio = _safe_div(
                geometric_apr_pct, arithmetic_apr_pct, None)
        else:
            # Non-positive arithmetic mean of samples behind a positive headline:
            # nothing realisable to drag toward — treat as fully overstated.
            drag_fraction = 1.0
            realization_ratio = 0.0

        if realization_ratio is not None and not math.isfinite(
                realization_ratio):
            realization_ratio = None

        headline_vs_arith_gap_pct = headline - arithmetic_apr_pct

        high_volatility = bool(
            coefficient_of_variation is not None
            and coefficient_of_variation >= HIGH_CV)
        headline_above_arithmetic = bool(
            arithmetic_apr_pct > 0
            and headline >= HEADLINE_OPTIMISTIC_RATIO * arithmetic_apr_pct)
        smooth_yield = bool(
            not wipeout and drag_fraction <= NEGLIGIBLE_DRAG_FRAC)

        score = self._score(drag_fraction, coefficient_of_variation)
        classification = self._classify(drag_fraction, wipeout)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification, wipeout, high_volatility,
            headline_above_arithmetic, smooth_yield)

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "arithmetic_apr_pct": round(arithmetic_apr_pct, 4),
            "geometric_apr_pct": round(geometric_apr_pct, 4),
            "variance_drag_pct": round(variance_drag_pct, 4),
            "drag_fraction": round(drag_fraction, 4),
            "realization_ratio": (
                None if realization_ratio is None
                else round(realization_ratio, 4)),
            "headline_vs_arith_gap_pct": round(headline_vs_arith_gap_pct, 4),
            "period_mean_pct": round(period_mean_pct, 6),
            "period_volatility_pct": round(period_volatility_pct, 6),
            "coefficient_of_variation": (
                None if coefficient_of_variation is None
                else round(coefficient_of_variation, 4)),
            "periods_per_year": round(ppy, 4),
            "sample_count": n,
            "capital_wipeout_period": wipeout,
            "high_volatility": high_volatility,
            "headline_above_arithmetic": headline_above_arithmetic,
            "smooth_yield": smooth_yield,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        drag_fraction: float,
        coefficient_of_variation: Optional[float],
    ) -> float:
        """
        0–100, HIGHER = smaller variance drag and a smoother yield stream. Two
        components:
          * realisation = 1 − drag_fraction (the geometric realised APR as a share
            of the arithmetic headline; a fully-drained stream → 0),
          * smoothness = clamp(1 − coefficient_of_variation, 0, 1) (a near-constant
            yield → ~1; CV ≥ 1 → 0).
        Weighted 70/30 toward realisation (the realised shortfall is the dominant
        signal; smoothness is a corroborating second-moment view). When CV is
        undefined (zero arithmetic mean) smoothness contributes 0.
        """
        realisation = _clamp(1.0 - drag_fraction, 0.0, 1.0)
        if coefficient_of_variation is None:
            smoothness = 0.0
        else:
            smoothness = _clamp(1.0 - coefficient_of_variation, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * smoothness, 0.0, 100.0)

    def _classify(self, drag_fraction: float, wipeout: bool) -> str:
        if wipeout:
            return "SEVERE_DRAG"
        if drag_fraction <= NEGLIGIBLE_DRAG_FRAC:
            return "NEGLIGIBLE_DRAG"
        if drag_fraction <= MINOR_DRAG_FRAC:
            return "MINOR_DRAG"
        if drag_fraction <= MODERATE_DRAG_FRAC:
            return "MODERATE_DRAG"
        return "SEVERE_DRAG"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification == "NEGLIGIBLE_DRAG":
            return "TRUST_HEADLINE"
        if classification == "MINOR_DRAG":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "MODERATE_DRAG":
            return "DISCOUNT_HEADLINE"
        # SEVERE_DRAG
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        wipeout: bool,
        high_volatility: bool,
        headline_above_arithmetic: bool,
        smooth_yield: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "NEGLIGIBLE_DRAG":
            flags.append("NEGLIGIBLE_DRAG")
        if classification == "MINOR_DRAG":
            flags.append("MINOR_DRAG")
        if classification == "MODERATE_DRAG":
            flags.append("MODERATE_DRAG")
        if classification == "SEVERE_DRAG":
            flags.append("SEVERE_DRAG")
        if wipeout:
            flags.append("CAPITAL_WIPEOUT_PERIOD")
        if high_volatility:
            flags.append("HIGH_VOLATILITY")
        if headline_above_arithmetic:
            flags.append("HEADLINE_ABOVE_ARITHMETIC")
        if smooth_yield:
            flags.append("SMOOTH_YIELD")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "arithmetic_apr_pct": None,
            "geometric_apr_pct": None,
            "variance_drag_pct": None,
            "drag_fraction": None,
            "realization_ratio": None,
            "headline_vs_arith_gap_pct": None,
            "period_mean_pct": None,
            "period_volatility_pct": None,
            "coefficient_of_variation": None,
            "periods_per_year": None,
            "sample_count": 0,
            "capital_wipeout_period": False,
            "high_volatility": False,
            "headline_above_arithmetic": False,
            "smooth_yield": False,
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
                "severe_count": 0,
                "position_count": len(results),
            }
        # Higher score = headline more realisable → highest score is best.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        severe = sum(
            1 for r in results
            if r["classification"] == "SEVERE_DRAG")
        return {
            "most_honest_vault": by_score[-1]["token"],
            "least_honest_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "severe_count": severe,
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
            # NEGLIGIBLE_DRAG: near-constant weekly yield → geometric ≈ arithmetic.
            "vault": "USDC-Lend-Smooth",
            "headline_apr_pct": 7.3,
            "periods_per_year": 52,
            "period_yield_samples": [0.140, 0.140, 0.141, 0.139, 0.140],
        },
        {
            # MODERATE_DRAG: moderately choppy monthly returns.
            "vault": "ETH-Epoch-Choppy",
            "headline_apr_pct": 40.0,
            "periods_per_year": 12,
            "period_yield_samples": [12.0, -6.0, 10.0, -4.0, 11.0, -3.0],
        },
        {
            # SEVERE_DRAG: wildly swinging monthly returns → big variance drag.
            "vault": "DEGEN-Options-Volatile",
            "headline_apr_pct": 120.0,
            "periods_per_year": 12,
            "period_yield_samples": [40.0, -20.0, 45.0, -25.0, 50.0, -30.0],
        },
        {
            # CAPITAL_WIPEOUT_PERIOD: a single period loses 100%+ → total loss.
            "vault": "RUG-Risk-Vault",
            "headline_apr_pct": 50.0,
            "periods_per_year": 12,
            "period_yield_samples": [30.0, 30.0, -100.0, 30.0],
        },
        {
            # INSUFFICIENT_DATA: non-positive headline, no samples.
            "vault": "ARB-Vault-NoData",
            "headline_apr_pct": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1197 Vault Yield Variance Drag Realization Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultYieldVarianceDragRealizationAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
