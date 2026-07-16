"""
Paper-trading return-normality & parametric-tail diagnostics (SPA-V403).

Read-only analytics layer that sits *on top of* the daily equity curve from
``equity_curve.py`` (SPA-V379), operating on the realised daily-return series.

How this differs from ``return_distribution.py`` (SPA-V383):
    V383 *describes the empirical distribution* — it reports the realised
    moments (skew/excess-kurtosis), percentiles, a histogram and **historical
    (non-parametric)** VaR/CVaR taken straight from the sorted sample. It never
    asks whether that distribution is *statistically* normal, and it never fits
    a parametric model to the tail.

    This module asks the complementary question a quant risk desk asks next:
    **is the return distribution actually normal, and — assuming a (moment-
    adjusted) parametric model — how bad is the tail?** Concretely it runs a
    formal normality hypothesis test and computes *parametric* tail risk:

        jarque_bera        formal Jarque-Bera normality test (statistic, closed-
                           form chi-square p-value, accept/reject at alpha 0.05).
        gaussian VaR/CVaR  parametric (normal-model) Value-at-Risk / Expected
                           Shortfall from the fitted mean & stdev.
        cornish_fisher     Cornish-Fisher modified VaR/CVaR — the same Gaussian
                           quantile *expanded* with the realised skew & excess
                           kurtosis, so fat / skewed tails inflate the estimate.
        tail_inflation     modified_var - gaussian_var: how much fatter-than-
                           normal tails push the parametric VaR.
        normality_grade    A/B/C/D heuristic and a short verdict label.

    V383 and V403 deliberately share the moment definitions (same population
    Fisher-Pearson skew & excess kurtosis) so the two reports reconcile, but the
    *outputs* never overlap: V383 = empirical description, V403 = hypothesis
    test + parametric tail.

Design notes / safety:
  * Pure stdlib (json, math, os, statistics, datetime, pathlib, logging,
    argparse) — mirrors the no-external-dependency style of
    linearity_analytics.py / return_distribution.py. **No numpy / scipy /
    pandas / web3 / requests, no network.** The inverse-normal-CDF (probit) and
    the standard-normal PDF are implemented from scratch (Acklam's rational
    approximation), and the chi-square(df=2) survival used for the JB p-value is
    its exact closed form ``exp(-JB/2)``.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    risk policy, wallets, or any money-moving code. It only reads
    pnl_history.json (via equity_curve.build_daily_equity_curve) and writes a
    derived report JSON.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen
    feed-health domain. Pure portfolio-performance analytics.
  * Returns series is ``curve[1:]`` (the seed day's 0.0 return is excluded),
    matching return_distribution.py exactly.
  * Defensive: degenerate inputs (0/1 day, flat / zero-variance series) never
    raise — undefined statistics return ``None`` and the schema stays stable.

VaR / CVaR sign convention (matches return_distribution.py): both are reported
    as the daily return at the lower tail, i.e. a *loss* is a negative percent.
    For confidence ``c`` the model places probability mass ``1 - c`` in the
    lower tail, so the quantile multiplier ``z = invCDF(1 - c)`` is negative and
    a typical VaR/CVaR comes out negative ("the loss you don't expect to exceed
    at confidence c"). These are NOT clamped to <= 0 — a strongly positive-mean
    series can legitimately produce a positive (non-loss) parametric quantile,
    and clamping would hide that.

CLI::

    python -m spa_core.analytics_lab.distribution_normality
    python -m spa_core.analytics_lab.distribution_normality --history data/pnl_history.json \\
        --out data/distribution_normality.json --confidences 0.95 0.99
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

from spa_core.paper_trading.equity_curve import (
    DEFAULT_HISTORY_PATH,
    build_daily_equity_curve,
    load_pnl_history,
)
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.analytics_lab.distribution_normality")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "distribution_normality.json"

# Default tail confidence levels (as fractions in (0,1)).
DEFAULT_CONFIDENCES = (0.95, 0.99)

# Jarque-Bera significance level for the is_normal decision.
JB_ALPHA = 0.05

# Inverse-square-root-of-two-pi, used by the standard-normal PDF.
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)


# ─── Daily-return series (identical convention to return_distribution.py) ─────

def _daily_returns(curve: list[dict]) -> list[float]:
    """Realised daily returns (%) — every bar after the seed day 1.

    Day 1's ``daily_return_pct`` is a 0.0 seed (no prior close), so it is
    excluded to avoid biasing the distribution toward zero — matching
    return_distribution.py exactly.
    """
    return [bar["daily_return_pct"] for bar in curve[1:]]


# ─── Stdlib normal-distribution helpers (implemented from scratch) ────────────

def _norm_pdf(z: float) -> float:
    """Standard-normal probability density function φ(z)."""
    return _INV_SQRT_2PI * math.exp(-0.5 * z * z)


# Acklam's rational approximation to the inverse normal CDF (probit). Absolute
# error < ~1.15e-9 across the open interval (0, 1); refined here with a single
# Halley step for extra accuracy. References: P.J. Acklam (2003).
_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
      3.754408661907416e+00)
# Break-points between the central and tail rational branches.
_P_LOW = 0.02425
_P_HIGH = 1.0 - _P_LOW


def _inv_norm_cdf(p: float) -> float:
    """Inverse standard-normal CDF (probit / quantile function).

    ``p`` must be in the open interval (0, 1). Returns the ``z`` such that
    Φ(z) == p, using Acklam's rational approximation refined by one Halley
    iteration. ``_inv_norm_cdf(0.5) == 0.0`` exactly; the function is strictly
    monotone increasing.
    """
    if not (0.0 < p < 1.0):
        raise ValueError(f"_inv_norm_cdf domain is (0,1), got {p}")
    if p == 0.5:
        return 0.0

    if p < _P_LOW:
        q = math.sqrt(-2.0 * math.log(p))
        z = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
            ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
    elif p <= _P_HIGH:
        q = p - 0.5
        r = q * q
        z = (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / \
            (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        z = -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
            ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)

    # One Halley refinement step using the exact CDF (erf) and PDF.
    e = 0.5 * math.erfc(-z / math.sqrt(2.0)) - p  # Φ(z) - p
    u = e / _norm_pdf(z)
    z = z - u / (1.0 + 0.5 * z * u)
    return z


# ─── Moments (shared definitions with return_distribution.py) ─────────────────

def _skewness(values: list[float], mean: float, stdev: float) -> float | None:
    """Population (Fisher-Pearson) skewness. None if undefined (n<2 or flat)."""
    n = len(values)
    if n < 2 or stdev == 0:
        return None
    m3 = sum((v - mean) ** 3 for v in values) / n
    return m3 / (stdev ** 3)


def _excess_kurtosis(values: list[float], mean: float, stdev: float) -> float | None:
    """Population excess kurtosis (kurtosis - 3). None if undefined."""
    n = len(values)
    if n < 2 or stdev == 0:
        return None
    m4 = sum((v - mean) ** 4 for v in values) / n
    return m4 / (stdev ** 4) - 3.0


# ─── Jarque-Bera normality test ───────────────────────────────────────────────

def _jarque_bera(n: int, skew: float | None, exkurt: float | None) -> dict:
    """Jarque-Bera normality test from the sample size + moments.

    statistic = n/6 * (S^2 + K^2/4), with S=skewness, K=excess kurtosis. Under
    H0 (normality) the statistic is asymptotically chi-square with df=2, whose
    survival function (the p-value) has the exact closed form ``exp(-JB/2)``.
    H0 (the data is normal) is *retained* when p_value >= alpha.

    Degenerate-safe: if the moments are undefined (too few points / flat series)
    every field is ``None`` except ``alpha``.
    """
    base = {"statistic": None, "p_value": None, "is_normal": None, "alpha": JB_ALPHA}
    if skew is None or exkurt is None or n < 1:
        return base
    jb = (n / 6.0) * (skew * skew + (exkurt * exkurt) / 4.0)
    # chi-square(df=2) survival == exp(-x/2), exact closed form.
    p_value = math.exp(-0.5 * jb)
    return {
        "statistic": round(jb, 6),
        "p_value": round(p_value, 6),
        "is_normal": bool(p_value >= JB_ALPHA),
        "alpha": JB_ALPHA,
    }


# ─── Parametric (Gaussian + Cornish-Fisher) tail risk ─────────────────────────

def _gaussian_var_cvar(mean: float, stdev: float, z: float, c: float) -> tuple[float, float]:
    """Parametric Gaussian VaR and CVaR (Expected Shortfall) at confidence c.

    ``z = invCDF(1 - c)`` is the (negative) lower-tail quantile multiplier.
        VaR_g  = mean + z * stdev
        CVaR_g = mean - stdev * φ(z) / (1 - c)
    Both in the same return units as the input; a loss is negative.
    """
    var_g = mean + z * stdev
    cvar_g = mean - stdev * _norm_pdf(z) / (1.0 - c)
    return var_g, cvar_g


def _cornish_fisher(z: float, skew: float, exkurt: float) -> float:
    """Cornish-Fisher expansion of a standard-normal quantile.

    z_cf = z + (z^2 - 1)/6 * S
             + (z^3 - 3z)/24 * K
             - (2z^3 - 5z)/36 * S^2
    where S = skewness, K = excess kurtosis. Reduces to ``z`` for a normal
    series (S=K=0); fat / skewed tails push it further into the tail.
    """
    z2 = z * z
    z3 = z2 * z
    return (
        z
        + (z2 - 1.0) / 6.0 * skew
        + (z3 - 3.0 * z) / 24.0 * exkurt
        - (2.0 * z3 - 5.0 * z) / 36.0 * (skew * skew)
    )


# ─── Confidence-level validation ──────────────────────────────────────────────

def _normalize_confidences(
    confidences: tuple[float, ...] | list[float],
) -> list[float]:
    """Validate, dedup and sort the confidence fractions.

    Keeps only values strictly inside (0, 1); dedups and sorts ascending. If
    *every* supplied value is invalid, falls back to the module default so the
    report is always populated.
    """
    valid = sorted({float(c) for c in confidences if 0.0 < float(c) < 1.0})
    if not valid:
        return sorted(set(DEFAULT_CONFIDENCES))
    return valid


# ─── Grade & verdict heuristics ───────────────────────────────────────────────

def _normality_grade(
    skew: float | None, exkurt: float | None, jb_p: float | None
) -> str | None:
    """A/B/C/D normality grade from |skew|, |excess kurtosis| and the JB p-value.

    Thresholds (all conditions must hold for a grade; degrade to the next on the
    first that fails):
        A : p >= 0.10 and |skew| < 0.5 and |excess kurtosis| < 1.0
        B : p >= 0.05 and |skew| < 1.0 and |excess kurtosis| < 2.0
        C : p >= 0.01 and |skew| < 2.0 and |excess kurtosis| < 5.0
        D : otherwise (strong departure from normality)
    Returns ``None`` if the moments are undefined (too little / flat data).
    """
    if skew is None or exkurt is None or jb_p is None:
        return None
    a_s, a_k = abs(skew), abs(exkurt)
    if jb_p >= 0.10 and a_s < 0.5 and a_k < 1.0:
        return "A"
    if jb_p >= 0.05 and a_s < 1.0 and a_k < 2.0:
        return "B"
    if jb_p >= 0.01 and a_s < 2.0 and a_k < 5.0:
        return "C"
    return "D"


def _verdict(
    n: int, skew: float | None, exkurt: float | None, jb: dict
) -> str:
    """Short human label summarising the normality diagnosis.

    "insufficient_data"      → moments undefined.
    "approximately_normal"   → JB retains H0 and both moments are mild.
    "fat_tailed"             → JB rejects mainly via excess kurtosis.
    "skewed"                 → JB rejects mainly via skew.
    "non_normal"             → JB rejects with both moments elevated / generic.
    """
    if skew is None or exkurt is None or jb["is_normal"] is None:
        return "insufficient_data"
    a_s, a_k = abs(skew), abs(exkurt)
    if jb["is_normal"] and a_s < 0.5 and a_k < 1.0:
        return "approximately_normal"
    # Rejected (or borderline with elevated moments) — classify the driver.
    if a_k >= 1.0 and a_k >= 2.0 * a_s:
        return "fat_tailed"
    if a_s >= 0.5 and a_s > a_k:
        return "skewed"
    return "non_normal"


# ─── Top-level compute ────────────────────────────────────────────────────────

def compute_normality(
    curve: list[dict],
    confidences: tuple[float, ...] | list[float] = DEFAULT_CONFIDENCES,
) -> dict:
    """Compute normality test + parametric tail risk from a daily equity curve.

    Args:
        curve: list of daily bars as produced by
            ``equity_curve.build_daily_equity_curve``.
        confidences: tail confidence fractions in (0, 1) (e.g. (0.95, 0.99)).

    Returns:
        A stable-schema metrics dict. Statistics that are undefined for the
        given data (too few days, zero variance) are ``None``.
    """
    levels_conf = _normalize_confidences(confidences)

    base = {
        "count":            0,
        "num_days":         0,
        "first_date":       None,
        "last_date":        None,
        "mean_pct":         None,
        "stdev_pct":        None,
        "skewness":         None,
        "excess_kurtosis":  None,
        "jarque_bera":      {"statistic": None, "p_value": None,
                             "is_normal": None, "alpha": JB_ALPHA},
        "levels":           [],
        "normality_grade":  None,
        "verdict":          "insufficient_data",
        "confidences":      levels_conf,
        "execution_mode":   "read_only_simulation",
    }

    returns = _daily_returns(curve)
    n = len(returns)
    if n == 0:
        return base

    # Date span comes from the underlying curve bars (seed day included for the
    # span markers; returns themselves still exclude the seed).
    dates = [bar.get("date") for bar in curve if bar.get("date") is not None]
    first_date = dates[0] if dates else None
    last_date = dates[-1] if dates else None

    mean = statistics.fmean(returns)
    stdev = statistics.pstdev(returns) if n >= 1 else 0.0
    skew = _skewness(returns, mean, stdev)
    exkurt = _excess_kurtosis(returns, mean, stdev)

    jb = _jarque_bera(n, skew, exkurt)

    # Parametric tail levels. Only computable when the variance is non-zero and
    # the moments exist; otherwise every level field is None (schema stable).
    levels: list[dict] = []
    moments_ok = skew is not None and exkurt is not None and stdev > 0
    for c in levels_conf:
        z = _inv_norm_cdf(1.0 - c)  # negative lower-tail multiplier
        if moments_ok:
            gaussian_var, gaussian_cvar = _gaussian_var_cvar(mean, stdev, z, c)
            cf_z = _cornish_fisher(z, skew, exkurt)
            modified_var = mean + cf_z * stdev
            # Modified CVaR: same ES formula evaluated at the CF-adjusted
            # quantile. This is an APPROXIMATION (the CF expansion targets the
            # quantile, not the tail expectation) but gives a fat-tail-aware ES.
            modified_cvar = mean - stdev * _norm_pdf(cf_z) / (1.0 - c)
            tail_inflation = modified_var - gaussian_var
            levels.append({
                "confidence":         round(c, 6),
                "z":                  round(z, 6),
                "gaussian_var_pct":   round(gaussian_var, 6),
                "gaussian_cvar_pct":  round(gaussian_cvar, 6),
                "cf_z":               round(cf_z, 6),
                "modified_var_pct":   round(modified_var, 6),
                "modified_cvar_pct":  round(modified_cvar, 6),
                "tail_inflation_pct": round(tail_inflation, 6),
            })
        else:
            levels.append({
                "confidence":         round(c, 6),
                "z":                  round(z, 6),
                "gaussian_var_pct":   None,
                "gaussian_cvar_pct":  None,
                "cf_z":               None,
                "modified_var_pct":   None,
                "modified_cvar_pct":  None,
                "tail_inflation_pct": None,
            })

    def _rnd(x: float | None, places: int = 6) -> float | None:
        return None if x is None else round(x, places)

    return {
        "count":            n,
        "num_days":         len(curve),
        "first_date":       first_date,
        "last_date":        last_date,
        "mean_pct":         round(mean, 6),
        "stdev_pct":        round(stdev, 6),
        "skewness":         _rnd(skew),
        "excess_kurtosis":  _rnd(exkurt),
        "jarque_bera":      jb,
        "levels":           levels,
        "normality_grade":  _normality_grade(skew, exkurt, jb["p_value"]),
        "verdict":          _verdict(n, skew, exkurt, jb),
        "confidences":      levels_conf,
        "execution_mode":   "read_only_simulation",
    }


def generate_normality_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    confidences: tuple[float, ...] | list[float] = DEFAULT_CONFIDENCES,
) -> dict:
    """Build the full normality report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        output_path: where to write the report JSON. Pass ``None`` to skip
            writing (compute-only).
        confidences: tail confidence fractions in (0, 1).

    Returns:
        ``{"generated_at", "source", "metrics"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "metrics":      compute_normality(curve, confidences),
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            # Atomic write via the canonical atomic_save (P3-9). Byte-identical
            # (indent=2; atomic_save adds default=str for serializable payloads).
            atomic_save(report, str(out))
            log.info(
                "normality report written: %s (%d days, verdict=%s, grade=%s)",
                out, report["metrics"]["count"],
                report["metrics"]["verdict"],
                report["metrics"]["normality_grade"],
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning("could not write normality report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compute return-normality (Jarque-Bera) + parametric "
                    "(Gaussian / Cornish-Fisher) tail risk from paper-trading "
                    "P&L history.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/distribution_normality.json)",
    )
    p.add_argument(
        "--confidences", type=float, nargs="+", default=list(DEFAULT_CONFIDENCES),
        help="tail confidence fractions in (0,1) (default: 0.95 0.99)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_normality_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
        confidences=args.confidences,
    )
    print(json.dumps(report["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
