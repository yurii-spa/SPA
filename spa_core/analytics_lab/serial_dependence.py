"""
Paper-trading serial-dependence / time-ordering diagnostics (SPA-V399).

Read-only analytics layer that sits *on top of* the daily equity curve from
``equity_curve.py`` (SPA-V379). Every other paper_trading analytic in the suite
treats the realised daily-return series as an *unordered bag* of numbers:
``risk_metrics`` (V380) reduces it to Sharpe/Sortino/Calmar, ``return_distribution``
(V383) describes its *shape* and tails, ``advanced_ratios`` (V397) adds Omega /
Ulcer, etc. None of them ask whether the *ordering* of the returns carries
information — i.e. whether good days tend to follow good days (momentum /
trending) or to reverse (mean-reversion), or whether the sequence is
indistinguishable from a random walk.

This module fills exactly that gap with the classic battery of serial-dependence
diagnostics an investor/quant reaches for when deciding whether an equity curve
has exploitable structure or is just noise:

    autocorrelation        sample ACF at lags 1..max_lag (Pearson serial corr)
    ljung_box              portmanteau test that *all* of lags 1..m are jointly
                           zero  (Q stat + chi-square p-value, df=m)
    runs_test              Wald-Wolfowitz runs test for randomness of the sign
                           sequence about the mean (z + two-sided p-value)
    variance_ratio         Lo-MacKinlay VR(q) = Var(q-period) / (q*Var(1-period))
                           per horizon q  (>1 trending, <1 mean-reverting, ~1 RW)
    hurst_exponent         rescaled-range (R/S) estimate  (0.5 random walk,
                           >0.5 persistent/trending, <0.5 anti-persistent)
    interpretation         coarse label: trending / mean_reverting / random_walk
                           / insufficient_data, derived from the above

Design notes / safety:
  * Pure stdlib (json, math, os, statistics, datetime, pathlib, logging,
    argparse) — mirrors the no-external-dependency style of risk_metrics.py /
    return_distribution.py / advanced_ratios.py. No web3, no numpy/pandas/scipy,
    no network. The chi-square and normal tail probabilities are computed from
    scratch (regularized incomplete gamma + erfc) so no scipy is needed.
  * STRICTLY READ-ONLY w.r.t. trading state. Never touches the execution path,
    risk policy, wallets, or any money-moving code. It only reads
    pnl_history.json (via equity_curve.build_daily_equity_curve) and writes a
    derived report JSON.
  * NOT a feed-health monitor — does not touch the SPA-BL-011 frozen
    feed-health domain. Pure portfolio-performance analytics.
  * Defensive: degenerate inputs (0, 1, few days, flat/zero-variance series)
    never raise — statistics that are mathematically undefined return ``None``
    and the schema stays stable.

CLI::

    python -m spa_core.analytics_lab.serial_dependence
    python -m spa_core.analytics_lab.serial_dependence --history data/pnl_history.json \\
        --out data/serial_dependence.json --max-lag 5 --vr-lags 2 3 5
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

log = logging.getLogger("spa.analytics_lab.serial_dependence")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = _PROJECT_ROOT / "data" / "serial_dependence.json"

# How many lags of autocorrelation / Ljung-Box to report by default.
DEFAULT_MAX_LAG = 5
# Variance-ratio horizons (q) reported by default.
DEFAULT_VR_LAGS = (2, 3, 5)

# Significance threshold used only for the coarse ``interpretation`` label.
_SIGNIFICANCE_ALPHA = 0.05
# Variance-ratio dead-band around 1.0 for the coarse label.
_VR_TREND_HI = 1.10
_VR_TREND_LO = 0.90


def _daily_returns(curve: list[dict]) -> list[float]:
    """Realised daily returns (%) — every bar after the seed day 1.

    Day 1's ``daily_return_pct`` is a 0.0 seed (no prior close), so it is
    excluded to avoid biasing the diagnostics toward zero.
    """
    return [bar["daily_return_pct"] for bar in curve[1:]]


# ─── Special functions (stdlib-only tail probabilities) ───────────────────────

def _gammap_regularized(s: float, x: float) -> float:
    """Lower regularized incomplete gamma P(s, x) = γ(s, x) / Γ(s).

    Numerical-Recipes style: series expansion for x < s+1, continued fraction
    (returning 1 - Q) otherwise. ``s > 0`` and ``x >= 0`` required; returns a
    value in [0, 1]. Used to build chi-square tail probabilities without scipy.
    """
    if x <= 0.0:
        return 0.0
    if s <= 0.0:
        return 1.0
    gln = math.lgamma(s)
    if x < s + 1.0:
        # Series representation.
        ap = s
        total = 1.0 / s
        delta = total
        for _ in range(1000):
            ap += 1.0
            delta *= x / ap
            total += delta
            if abs(delta) < abs(total) * 1e-15:
                break
        return total * math.exp(-x + s * math.log(x) - gln)
    # Continued fraction for Q(s, x); P = 1 - Q.
    tiny = 1e-300
    b = x + 1.0 - s
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - s)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    q = math.exp(-x + s * math.log(x) - gln) * h
    return 1.0 - q


def _chi2_sf(x: float, df: int) -> float | None:
    """Chi-square survival function P(X > x) for ``df`` degrees of freedom.

    Returns a p-value in [0, 1], or None if the arguments are degenerate
    (df < 1). Implemented via the upper regularized incomplete gamma.
    """
    if df < 1:
        return None
    if x <= 0.0:
        return 1.0
    p = _gammap_regularized(df / 2.0, x / 2.0)
    return max(0.0, min(1.0, 1.0 - p))


def _normal_two_sided_p(z: float) -> float:
    """Two-sided p-value for a standard-normal z-score, via ``math.erfc``."""
    return max(0.0, min(1.0, math.erfc(abs(z) / math.sqrt(2.0))))


# ─── Core statistics ──────────────────────────────────────────────────────────

def _autocorrelations(values: list[float], max_lag: int) -> list[dict]:
    """Sample autocorrelation function for lags 1..max_lag.

    Uses the standard biased estimator with the full-sample variance in the
    denominator::

        r_k = Σ_{t=1}^{n-k} (x_t - x̄)(x_{t+k} - x̄) / Σ_{t=1}^{n} (x_t - x̄)²

    Returns a list of ``{"lag": k, "acf": r_k|None}``. ``acf`` is None when the
    lag cannot be estimated (n <= k+1) or the series has zero variance.
    """
    n = len(values)
    out: list[dict] = []
    if n == 0:
        return [{"lag": k, "acf": None} for k in range(1, max_lag + 1)]
    mean = statistics.fmean(values)
    denom = sum((v - mean) ** 2 for v in values)
    for k in range(1, max_lag + 1):
        if denom == 0.0 or n <= k + 1:
            out.append({"lag": k, "acf": None})
            continue
        num = sum((values[t] - mean) * (values[t + k] - mean)
                  for t in range(n - k))
        out.append({"lag": k, "acf": round(num / denom, 6)})
    return out


def _ljung_box(acf: list[dict], n: int) -> dict:
    """Ljung-Box portmanteau statistic over the supplied (lag, acf) pairs.

    Q = n(n+2) Σ_k r_k² / (n - k), summed over the lags whose ACF is defined.
    df is the number of such lags. p_value is the chi-square survival function.
    All fields are None when no lag is usable.
    """
    usable = [(d["lag"], d["acf"]) for d in acf if d["acf"] is not None]
    if not usable or n < 3:
        return {"statistic": None, "df": 0, "p_value": None,
                "lags": [d["lag"] for d in acf]}
    q = 0.0
    df = 0
    for lag, r in usable:
        if n - lag <= 0:
            continue
        q += (r * r) / (n - lag)
        df += 1
    if df == 0:
        return {"statistic": None, "df": 0, "p_value": None,
                "lags": [lag for lag, _ in usable]}
    q *= n * (n + 2)
    return {
        "statistic": round(q, 6),
        "df": df,
        "p_value": (lambda p: None if p is None else round(p, 6))(_chi2_sf(q, df)),
        "lags": [lag for lag, _ in usable],
    }


def _runs_test(values: list[float]) -> dict:
    """Wald-Wolfowitz runs test for randomness of the sign sequence about mean.

    Values exactly equal to the mean are dropped (the standard handling). A
    "run" is a maximal block of consecutive same-side observations. Reports the
    observed run count, the expected count and variance under the
    null of randomness, the z-score and a two-sided normal p-value.

    All inferential fields are None when the test is undefined (one side empty,
    or fewer than two usable observations).
    """
    base = {"runs": None, "n_above": 0, "n_below": 0, "expected_runs": None,
            "z_score": None, "p_value": None}
    if not values:
        return base
    mean = statistics.fmean(values)
    signs = [1 if v > mean else (-1 if v < mean else 0) for v in values]
    seq = [s for s in signs if s != 0]
    n1 = sum(1 for s in seq if s == 1)
    n2 = sum(1 for s in seq if s == -1)
    base["n_above"] = n1
    base["n_below"] = n2
    if n1 == 0 or n2 == 0 or len(seq) < 2:
        # Count runs anyway for transparency, but inference is undefined.
        runs = 1 + sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1]) if seq else 0
        base["runs"] = runs
        return base
    runs = 1 + sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
    nt = n1 + n2
    expected = 2.0 * n1 * n2 / nt + 1.0
    var = (2.0 * n1 * n2 * (2.0 * n1 * n2 - nt)) / (nt * nt * (nt - 1.0))
    z = None if var <= 0.0 else (runs - expected) / math.sqrt(var)
    return {
        "runs": runs,
        "n_above": n1,
        "n_below": n2,
        "expected_runs": round(expected, 6),
        "z_score": None if z is None else round(z, 6),
        "p_value": None if z is None else round(_normal_two_sided_p(z), 6),
    }


def _variance_ratio(values: list[float], q: int) -> float | None:
    """Lo-MacKinlay variance ratio VR(q) using overlapping q-period sums.

    VR(q) = Var(q-period return) / (q * Var(1-period return)), where the
    q-period returns are overlapping rolling sums of the daily series (a valid
    additive approximation for small daily percentage returns). VR > 1 implies
    positive serial correlation (trending), VR < 1 mean reversion, VR ≈ 1 a
    random walk. None if undefined (n < q+1, q < 2, or zero 1-period variance).
    """
    n = len(values)
    if q < 2 or n < q + 1:
        return None
    var1 = statistics.pvariance(values)
    if var1 == 0.0:
        return None
    # Overlapping q-period sums.
    qsums = [sum(values[i:i + q]) for i in range(0, n - q + 1)]
    if len(qsums) < 2:
        return None
    varq = statistics.pvariance(qsums)
    return round(varq / (q * var1), 6)


def _hurst_rs(values: list[float], min_chunk: int = 4) -> float | None:
    """Rescaled-range (R/S) estimate of the Hurst exponent.

    Splits the series into non-overlapping chunks of increasing size, computes
    the average rescaled range R/S per chunk size, and regresses log(R/S) on
    log(chunk_size); the slope is the Hurst exponent. Needs at least two
    distinct chunk sizes with a positive R/S, so short series (n < 2*min_chunk)
    return None — which is the honest answer for a handful of days, not a
    fabricated 0.5.
    """
    n = len(values)
    if n < 2 * min_chunk:
        return None
    # Candidate chunk sizes: min_chunk, 2*min_chunk, ... up to n.
    sizes: list[int] = []
    size = min_chunk
    while size <= n:
        sizes.append(size)
        size *= 2
    points: list[tuple[float, float]] = []
    for m in sizes:
        n_chunks = n // m
        if n_chunks < 1:
            continue
        rs_vals: list[float] = []
        for c in range(n_chunks):
            chunk = values[c * m:(c + 1) * m]
            mean = statistics.fmean(chunk)
            dev = 0.0
            cum = []
            for v in chunk:
                dev += v - mean
                cum.append(dev)
            r = max(cum) - min(cum)
            s = statistics.pstdev(chunk)
            if s > 0.0 and r > 0.0:
                rs_vals.append(r / s)
        if rs_vals:
            avg_rs = statistics.fmean(rs_vals)
            if avg_rs > 0.0:
                points.append((math.log(m), math.log(avg_rs)))
    if len(points) < 2:
        return None
    # Ordinary least-squares slope.
    mx = statistics.fmean([p[0] for p in points])
    my = statistics.fmean([p[1] for p in points])
    num = sum((px - mx) * (py - my) for px, py in points)
    den = sum((px - mx) ** 2 for px, _ in points)
    if den == 0.0:
        return None
    return round(num / den, 6)


def _classify(acf: list[dict], ljung: dict, vr: dict, n: int) -> str:
    """Coarse label from the diagnostics. Conservative: only departs from
    ``random_walk`` when there is corroborating evidence."""
    if n < 4:
        return "insufficient_data"
    lag1 = next((d["acf"] for d in acf if d["lag"] == 1), None)
    p = ljung.get("p_value")
    significant = p is not None and p < _SIGNIFICANCE_ALPHA
    vr2 = vr.get("2")
    trend_votes = 0
    revert_votes = 0
    if lag1 is not None and significant:
        if lag1 > 0:
            trend_votes += 1
        elif lag1 < 0:
            revert_votes += 1
    if vr2 is not None:
        if vr2 > _VR_TREND_HI:
            trend_votes += 1
        elif vr2 < _VR_TREND_LO:
            revert_votes += 1
    if trend_votes > revert_votes and trend_votes > 0:
        return "trending"
    if revert_votes > trend_votes and revert_votes > 0:
        return "mean_reverting"
    return "random_walk"


def compute_serial_dependence(
    curve: list[dict],
    max_lag: int = DEFAULT_MAX_LAG,
    vr_lags: tuple[int, ...] | list[int] = DEFAULT_VR_LAGS,
) -> dict:
    """Compute serial-dependence diagnostics from a daily equity curve.

    Args:
        curve: list of daily bars as produced by
            ``equity_curve.build_daily_equity_curve``.
        max_lag: highest autocorrelation / Ljung-Box lag to report.
        vr_lags: variance-ratio horizons (q) to report.

    Returns:
        A stable-schema dict; undefined statistics are ``None``.
    """
    max_lag = max(1, int(max_lag))
    vr_lags = [int(q) for q in vr_lags]
    returns = _daily_returns(curve)
    n = len(returns)

    acf = _autocorrelations(returns, max_lag)
    ljung = _ljung_box(acf, n)
    runs = _runs_test(returns)
    vr = {str(q): _variance_ratio(returns, q) for q in vr_lags}
    hurst = _hurst_rs(returns)

    mean = round(statistics.fmean(returns), 6) if n else None
    stdev = round(statistics.pstdev(returns), 6) if n else None

    return {
        "num_return_days":   n,
        "mean_pct":          mean,
        "stdev_pct":         stdev,
        "max_lag":           max_lag,
        "autocorrelation":   acf,
        "ljung_box":         ljung,
        "runs_test":         runs,
        "variance_ratio":    vr,
        "variance_ratio_lags": vr_lags,
        "hurst_exponent":    hurst,
        "interpretation":    _classify(acf, ljung, vr, n),
    }


def generate_serial_dependence_report(
    history_path: str | Path = DEFAULT_HISTORY_PATH,
    output_path: str | Path | None = DEFAULT_OUTPUT_PATH,
    max_lag: int = DEFAULT_MAX_LAG,
    vr_lags: tuple[int, ...] | list[int] = DEFAULT_VR_LAGS,
) -> dict:
    """Build the full serial-dependence report and (optionally) persist it.

    Args:
        history_path: source pnl_history.json.
        output_path: where to write the report JSON. Pass ``None`` to skip
            writing (compute-only).
        max_lag: highest autocorrelation / Ljung-Box lag.
        vr_lags: variance-ratio horizons.

    Returns:
        ``{"generated_at", "source", "diagnostics"}``.
    """
    records = load_pnl_history(history_path)
    curve = build_daily_equity_curve(records)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source":       str(history_path),
        "diagnostics":  compute_serial_dependence(curve, max_lag, vr_lags),
    }

    if output_path is not None:
        out = Path(output_path)
        try:
            # Atomic write via the canonical atomic_save (P3-9). Byte-identical
            # (indent=2; atomic_save adds default=str for serializable payloads).
            atomic_save(report, str(out))
            log.info(
                "serial dependence report written: %s (%d days, label=%s, lb_p=%s)",
                out, report["diagnostics"]["num_return_days"],
                report["diagnostics"]["interpretation"],
                report["diagnostics"]["ljung_box"].get("p_value"),
            )
        except OSError as exc:  # never let a write failure crash the pipeline
            log.warning(
                "could not write serial dependence report to %s: %s", out, exc)

    return report


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compute serial-dependence / time-ordering diagnostics "
                    "(autocorrelation, Ljung-Box, runs test, variance ratio, "
                    "Hurst) from paper-trading P&L history.",
    )
    p.add_argument(
        "--history", default=str(DEFAULT_HISTORY_PATH),
        help="path to pnl_history.json (default: data/pnl_history.json)",
    )
    p.add_argument(
        "--out", default=str(DEFAULT_OUTPUT_PATH),
        help="output report path (default: data/serial_dependence.json)",
    )
    p.add_argument(
        "--max-lag", type=int, default=DEFAULT_MAX_LAG,
        help=f"highest ACF/Ljung-Box lag (default: {DEFAULT_MAX_LAG})",
    )
    p.add_argument(
        "--vr-lags", type=int, nargs="+", default=list(DEFAULT_VR_LAGS),
        help="variance-ratio horizons q (default: 2 3 5)",
    )
    p.add_argument(
        "--no-write", action="store_true",
        help="compute and print only; do not write the report file",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    report = generate_serial_dependence_report(
        history_path=args.history,
        output_path=None if args.no_write else args.out,
        max_lag=args.max_lag,
        vr_lags=args.vr_lags,
    )
    print(json.dumps(report["diagnostics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
