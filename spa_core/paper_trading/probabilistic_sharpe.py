"""
Paper-trading Probabilistic Sharpe Ratio & Minimum Track Record Length (SPA-V404).

Read-only analytics layer that sits *on top of* the daily equity curve from
``equity_curve.py`` (SPA-V379), operating on the realised daily-return series.

How this differs from the rest of the suite:
    ``risk_metrics.py``        reports the *point estimate* of the Sharpe /
                               Sortino ratio. ``advanced_ratios.py`` (V397) adds
                               Omega / Ulcer. ``linearity_analytics.py`` (V402)
                               gives a t-stat on the equity *trend*.
                               ``distribution_normality.py`` (V403) tests
                               whether the return distribution is normal and
                               prices a parametric tail.

    None of them answer the single question a discretionary allocator asks of a
    *short, non-normal* track record: **how much should I trust the Sharpe at
    all?** A Sharpe of 1.5 measured over 8 noisy, skewed days is not the same
    evidence as the same Sharpe over 800 clean days.

    This module answers it with the **Probabilistic Sharpe Ratio (PSR)** and the
    **Minimum Track Record Length (MinTRL)** of Bailey & López de Prado (2012,
    *The Sharpe Ratio Efficient Frontier*, J. of Risk):

        PSR(SR*)   the probability that the *true* (population) Sharpe ratio
                   exceeds a benchmark SR*, given the observed Sharpe, the
                   track-record length, and the realised skewness & kurtosis.
                   Higher moments matter: negative skew and fat tails *lower*
                   the confidence that an observed Sharpe is real.

        MinTRL     the minimum number of observations the track record would
                   need for PSR to reach a target confidence (e.g. 0.95) — i.e.
                   "how many more days of this behaviour before the Sharpe is
                   statistically credible".

    PSR/MinTRL deliberately reuse the same population Fisher-Pearson skewness &
    excess-kurtosis definitions as ``return_distribution.py`` (V383) and
    ``distribution_normality.py`` (V403), so the three reports reconcile; but the
    *output* — a significance probability and a required sample size — does not
    overlap with any sibling.

Formulas (Bailey & López de Prado 2012), with per-period (non-annualised)
Sharpe ``SR``, skewness ``γ3``, kurtosis ``γ4`` (non-excess; 3 for a normal),
benchmark ``SR*`` and ``n`` returns::

        PSR(SR*) = Φ[ (SR − SR*) · √(n − 1)
                      / √(1 − γ3·SR + (γ4 − 1)/4 · SR²) ]

        MinTRL   = 1 + (1 − γ3·SR + (γ4 − 1)/4 · SR²) · ( Φ⁻¹(α) / (SR − SR*) )²

The bracket ``V = 1 − γ3·SR + (γ4 − 1)/4 · SR²`` is the (estimated) variance of
the Sharpe estimator; for a normal series (γ3=0, γ4=3) it reduces to
``1 + ½·SR²`` (the classic Lo 2002 result). MinTRL is only defined when the
edge is positive (``SR > SR*``) and ``V > 0``.

Design notes / safety:
  * Pure stdlib (json, math, os, statistics, datetime, pathlib, logging,
    argparse) — mirrors the no-external-dependency style of
    distribution_normality.py / linearity_analytics.py. **No numpy / scipy /
    pandas / web3 / requests, no network.** The standard-normal CDF Φ is the
    exact ``0.5·erfc(−x/√2)`` and the inverse-normal-CDF (probit) Φ⁻¹ is
    Acklam's rational approximation refined by one Halley step — both
    implemented from scratch.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    risk policy, wallets, or any money-moving code. It only reads
    pnl_history.json (via equity_curve.build_daily_equity_curve) and writes a
    derived report JSON.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen
    feed-health domain. Pure portfolio-performance analytics.
  * Returns series is ``curve[1:]`` (the seed day's 0.0 return is excluded),
    matching return_distribution.py / distribution_normality.py exactly.
  * Defensive: degenerate inputs (0/1 day, flat / zero-variance series,
    non-positive variance term) never raise — undefined statistics return
    ``None`` and the schema stays stable.

CLI::

    python -m spa_core.paper_trading.probabilistic_sharpe
    python -m spa_core.paper_trading.probabilistic_sharpe --history data/pnl_history.json \\
        --out data/probabilistic_sharpe.json --benchmark 0.0 --confidences 0.95 0.99
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

log = logging.getLogger("spa.paper_trading.probabilistic_sharpe")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "probabilistic_sharpe.json"

# Default MinTRL target confidence levels (as fractions in (0,1)).
DEFAULT_CONFIDENCES = (0.95, 0.99)

# Default benchmark Sharpe the PSR is tested against (per-period). 0.0 asks
# "is the true Sharpe greater than zero" — the basic does-it-have-an-edge test.
DEFAULT_BENCHMARK_SR = 0.0

# Calendar-day annualisation (daily snapshots) — matches the sibling modules.
ANNUALIZATION_DAYS = 365


# ─── Daily-return series (identical convention to distribution_normality.py) ──

def _daily_returns(curve: list[dict]) -> list[float]:
    """Realised daily returns (%) — every bar after the seed day 1.

    Day 1's ``daily_return_pct`` is a 0.0 seed (no prior close), so it is
    excluded to avoid biasing the series toward zero — matching
    return_distribution.py / distribution_normality.py exactly.
    """
    return [bar["daily_return_pct"] for bar in curve[1:]]


# ─── Stdlib normal-distribution helpers (implemented from scratch) ────────────

def _norm_cdf(x: float) -> float:
    """Standard-normal CDF Φ(x) via the exact complementary error function."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


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

# 1/√(2π) for the standard-normal PDF used in the Halley refinement.
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)


def _inv_norm_cdf(p: float) -> float:
    """Inverse standard-normal CDF (probit / quantile function).

    ``p`` must be in the open interval (0, 1). Returns the ``z`` such that
    Φ(z) == p, using Acklam's rational approximation refined by one Halley
    iteration. ``_inv_norm_cdf(0.5) == 0.0`` exactly; strictly monotone.
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
    e = _norm_cdf(z) - p
    u = e / (_INV_SQRT_2PI * math.exp(-0.5 * z * z))
    z = z - u / (1.0 + 0.5 * z * u)
    return z


# ─── Moments (shared definitions with distribution_normality.py) ──────────────

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


# ─── PSR / MinTRL core ────────────────────────────────────────────────────────

def _variance_term(sr: float, skew: float, exkurt: float) -> float:
    """Estimator variance bracket ``V = 1 − γ3·SR + (γ4 − 1)/4 · SR²``.

    ``γ4 = exkurt + 3`` (non-excess kurtosis), so ``(γ4 − 1)/4 == (exkurt + 2)/4``.
    For a normal series (skew=0, exkurt=0) this reduces to ``1 + ½·SR²``.
    """
    return 1.0 - skew * sr + ((exkurt + 2.0) / 4.0) * sr * sr


def _probabilistic_sharpe(
    sr: float, sr_star: float, n: int, skew: float, exkurt: float
) -> tuple[float | None, float]:
    """Probabilistic Sharpe Ratio PSR(SR*) and the variance term ``V``.

    Returns ``(psr, V)``. ``psr`` is ``None`` when it is undefined (n < 2 or the
    variance term is non-positive); ``V`` is always returned for transparency.
    """
    v = _variance_term(sr, skew, exkurt)
    if n < 2 or v <= 0.0:
        return None, v
    z = (sr - sr_star) * math.sqrt(n - 1) / math.sqrt(v)
    return _norm_cdf(z), v


def _min_track_record_length(
    sr: float, sr_star: float, skew: float, exkurt: float, alpha: float
) -> float | None:
    """Minimum Track Record Length for PSR to reach confidence ``alpha``.

    ``MinTRL = 1 + V · (Φ⁻¹(α) / (SR − SR*))²``. Defined only when the edge is
    positive (``SR > SR*``) and the variance term ``V`` is positive — otherwise
    the target confidence is unreachable and the function returns ``None``.
    """
    if sr <= sr_star:
        return None
    v = _variance_term(sr, skew, exkurt)
    if v <= 0.0:
        return None
    z_alpha = _inv_norm_cdf(alpha)
    return 1.0 + v * (z_alpha / (sr - sr_star)) ** 2


# ─── Grade & verdict heuristics ───────────────────────────────────────────────

def _psr_grade(psr: float | None) -> str | None:
    """A/B/C/D grade from the PSR (probability the true Sharpe beats SR*)."""
    if psr is None:
        return None
    if psr >= 0.99:
        return "A"
    if psr >= 0.95:
        return "B"
    if psr >= 0.90:
        return "C"
    return "D"


def _verdict(psr: float | None) -> str:
    """Short human label summarising the statistical significance of the Sharpe."""
    if psr is None:
        return "insufficient_data"
    if psr >= 0.99:
        return "highly_significant"
    if psr >= 0.95:
        return "significant"
    if psr >= 0.90:
        return "marginally_significant"
    return "not_significant"


# ─── Confidence-level validation ──────────────────────────────────────────────

def _normalize_confidences(
    confidences: tuple[float, ...] | list[float],
) -> list[float]:
    """Validate, dedup and sort the MinTRL target confidences.

    Keeps only values strictly inside (0, 1); dedups and sorts ascending. If
    *every* supplied value is invalid, falls back to the module default so the
    report is always populated.
    """
    valid = sorted({float(c) for c in confidences if 0.0 < float(c) < 1.0})
    if not valid:
        return sorted(set(DEFAULT_CONFIDENCES))
    return valid


# ─── Top-level compute ────────────────────────────────────────────────────────

def compute_probabilistic_sharpe(
    curve: list[dict],
    benchmark_sr: float = DEFAULT_BENCHMARK_SR,
    confidences: tuple[float, ...] | list[float] = DEFAULT_CONFIDENCES,
) -> dict:
    """Compute PSR + MinTRL from a daily equity curve.

    Args:
        curve: list of daily bars as produced by
            ``equity_curve.build_daily_equity_curve``.
        benchmark_sr: per-period benchmark Sharpe ``SR*`` the PSR is tested
            against (default 0.0 — "is the true Sharpe positive").
        confidences: MinTRL target confidence fractions in (0, 1).

    Returns:
        A stable-schema metrics dict. Statistics that are undefined for the
        given data (too few days, zero variance, non-positive variance term)
        are ``None``.
    """
    target_conf = _normalize_confidences(confidences)
    sr_star = float(benchmark_sr)

    base = {
        "count":                       0,
        "num_days":                    0,
        "first_date":                  None,
        "last_date":                   None,
        "mean_pct":                    None,
        "stdev_pct":                   None,
        "skewness":                    None,
        "excess_kurtosis":             None,
        "kurtosis":                    None,
        "observed_sharpe_daily":       None,
        "observed_sharpe_annualized":  None,
        "annualization_days":          ANNUALIZATION_DAYS,
        "benchmark_sharpe_daily":      round(sr_star, 6),
        "variance_term":               None,
        "psr":                         None,
        "psr_grade":                   None,
        "verdict":                     "insufficient_data",
        "targets":                     [],
        "confidences":                 target_conf,
        "execution_mode":              "read_only_simulation",
    }

    returns = _daily_returns(curve)
    n = len(returns)
    if n == 0:
        return base

    dates = [bar.get("date") for bar in curve if bar.get("date") is not None]
    first_date = dates[0] if dates else None
    last_date = dates[-1] if dates else None

    mean = statistics.fmean(returns)
    stdev = statistics.pstdev(returns) if n >= 1 else 0.0
    skew = _skewness(returns, mean, stdev)
    exkurt = _excess_kurtosis(returns, mean, stdev)

    def _rnd(x: float | None, places: int = 6) -> float | None:
        return None if x is None else round(x, places)

    # Per-period (daily) Sharpe estimate. Undefined when the series is flat or
    # too short for the moments — in which case PSR/MinTRL are all None.
    moments_ok = skew is not None and exkurt is not None and stdev > 0 and n >= 2
    if moments_ok:
        sr_daily = mean / stdev
        sr_annual = sr_daily * math.sqrt(ANNUALIZATION_DAYS)
        psr, v = _probabilistic_sharpe(sr_daily, sr_star, n, skew, exkurt)
        targets = []
        for c in target_conf:
            mintrl = _min_track_record_length(sr_daily, sr_star, skew, exkurt, c)
            add_needed = None if mintrl is None else max(0.0, mintrl - n)
            targets.append({
                "confidence":               round(c, 6),
                "z_alpha":                  round(_inv_norm_cdf(c), 6),
                "min_track_record_length":  _rnd(mintrl, 4),
                "additional_days_needed":   _rnd(add_needed, 4),
            })
        return {
            "count":                       n,
            "num_days":                    len(curve),
            "first_date":                  first_date,
            "last_date":                   last_date,
            "mean_pct":                    round(mean, 6),
            "stdev_pct":                   round(stdev, 6),
            "skewness":                    _rnd(skew),
            "excess_kurtosis":             _rnd(exkurt),
            "kurtosis":                    _rnd(exkurt + 3.0),
            "observed_sharpe_daily":       round(sr_daily, 6),
            "observed_sharpe_annualized":  round(sr_annual, 6),
            "annualization_days":          ANNUALIZATION_DAYS,
            "benchmark_sharpe_daily":      round(sr_star, 6),
            "variance_term":               round(v, 6),
            "psr":                         _rnd(psr),
            "psr_grade":                   _psr_grade(psr),
            "verdict":                     _verdict(psr),
            "targets":                     targets,
            "confidences":                 target_conf,
            "execution_mode":              "read_only_simulation",
        }

    # Degenerate: keep the span / moment fields we *can* report, everything
    # else stays None and the schema is unchanged.
    out = dict(base)
    out.update({
        "count":           n,
        "num_days":        len(curve),
        "first_date":      first_date,
        "last_date":       last_date,
        "mean_pct":        round(mean, 6),
        "stdev_pct":       round(stdev, 6),
        "skewness":        _rnd(skew),
        "excess_kurtosis": _rnd(exkurt),
        "kurtosis":        None if exkurt is None else _rnd(exkurt + 3.0),
    })
    return out


def generate_probabilistic_sharpe_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    benchmark_sr: float = DEFAULT_BENCHMARK_SR,
    confidences: tuple[float, ...] | list[float] = DEFAULT_CONFIDENCES,
) -> dict:
    """Build the full PSR/MinTRL report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        output_path: where to write the report JSON. Pass ``None`` to skip
            writing (compute-only).
        benchmark_sr: per-period benchmark Sharpe ``SR*``.
        confidences: MinTRL target confidence fractions in (0, 1).

    Returns:
        ``{"generated_at", "source", "metrics"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "metrics":      compute_probabilistic_sharpe(curve, benchmark_sr, confidences),
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            # Atomic write via the canonical atomic_save (P3-9). Byte-identical
            # (indent=2; atomic_save adds default=str for serializable payloads).
            atomic_save(report, str(out))
            log.info(
                "PSR report written: %s (%d days, psr=%s, verdict=%s)",
                out, report["metrics"]["count"],
                report["metrics"]["psr"], report["metrics"]["verdict"],
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning("could not write PSR report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compute the Probabilistic Sharpe Ratio (PSR) and Minimum "
                    "Track Record Length (MinTRL) from paper-trading P&L history.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/probabilistic_sharpe.json)",
    )
    p.add_argument(
        "--benchmark", type=float, default=DEFAULT_BENCHMARK_SR,
        help="per-period benchmark Sharpe SR* the PSR is tested against "
             "(default: 0.0)",
    )
    p.add_argument(
        "--confidences", type=float, nargs="+", default=list(DEFAULT_CONFIDENCES),
        help="MinTRL target confidence fractions in (0,1) (default: 0.95 0.99)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_probabilistic_sharpe_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
        benchmark_sr=args.benchmark,
        confidences=args.confidences,
    )
    print(json.dumps(report["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
