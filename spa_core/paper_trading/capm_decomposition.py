#!/usr/bin/env python3
"""CAPM Risk-Decomposition Analyzer (SPA-V465 / MP-150) — read-only / advisory.

The benchmark-relative suite already measures the portfolio *against a
baseline*: ``benchmark_comparison`` reports excess return, tracking error, the
information ratio, beta, correlation and capture ratios. But it deliberately
stops short of the **CAPM risk-adjusted battery** — the regression-of-excess-
returns view that an institutional due-diligence layer expects:

    "Once we regress the book's EXCESS return on the BENCHMARK's excess return,
     how much return did the manager add that is NOT explained by simply taking
     market beta (Jensen's alpha)? What is the reward per unit of *systematic*
     risk (Treynor)? Where does this strategy plot on the capital-market line
     once we lever/de-lever it to the benchmark's volatility (Modigliani M²)?
     Is the alpha large relative to the *specific* risk taken to earn it
     (appraisal ratio)? And how much of the variance is market-driven vs
     idiosyncratic (systematic / specific decomposition)?"

That is the gap MP-150 closes with the **CAPM Risk-Decomposition Analyzer**
(Jensen 1968; Treynor 1965; Modigliani & Modigliani 1997; Treynor & Black
1973).

The CAPM regression
===================
Let ``Rp`` be the portfolio daily returns, ``Rm`` the benchmark daily returns
and ``Rf`` the (constant) daily risk-free return derived from a flat annual
rate. We regress the portfolio EXCESS return on the benchmark EXCESS return::

    (Rp - Rf) = alpha + beta * (Rm - Rf) + residual

Because ``Rf`` is constant it cancels out of the slope, so the population OLS
slope is simply ``beta = cov(Rp, Rm) / var(Rm)`` and the intercept is the
daily Jensen's alpha. Every downstream statistic is hand-derivable from
``beta``, ``alpha`` and the residual series.

Output fields (every metric is ``None`` when undefined for the data)
====================================================================
    available                  True once n >= MIN_OBS returns are present
    beta                       cov(Rp, Rm) / var(Rm) — systematic exposure
    correlation                Pearson correlation of Rp vs Rm in [-1, 1]
    jensen_alpha_daily         CAPM intercept: mean(Rp) - [Rf + beta*(mean(Rm)-Rf)]
    jensen_alpha_annualized_pct  ((1+alpha_daily)**365 - 1) * 100 (geometric)
    treynor_ratio              (ann. portfolio return - ann. Rf) / beta (None if beta<=0)
    modigliani_m2_pct          RAP: Rf_ann + sharpe_p * sigma_benchmark_annual (%)
    m2_alpha_pct               M² minus the annualized benchmark return (%)
    appraisal_ratio            alpha_daily / pstdev(residuals), annualized * sqrt(365)
    systematic_variance        beta**2 * var(Rm) — market-driven variance
    specific_variance          pvariance(residuals) — idiosyncratic variance
    capm_r_squared             systematic / (systematic + specific) in [0, 1]
    pct_systematic_risk        capm_r_squared * 100
    sharpe_portfolio_daily     (mean(Rp) - Rf) / pstdev(Rp) (daily)
    portfolio_annualized_pct   geometric annualized portfolio return (%)
    benchmark_annualized_pct   geometric annualized benchmark return (%)
    risk_free_annual_pct       the flat annual Rf used (%)
    risk_free_daily            the per-day Rf (constant)
    benchmark_kind             "explicit" | "flat_risk_free"
    count_returns / n_observations  number of daily returns used
    start_date / end_date      span of the equity track
    verdict / verdict_reason   advisory band (see below)

Benchmark convention (mirrors ``benchmark_comparison``)
======================================================
By default the benchmark is a **flat risk-free baseline** — a constant annual
rate (default 4.0%) converted to a per-day return via
``(1 + apy/100) ** (1/365) - 1``. A flat benchmark has ZERO variance, so the
entire CAPM decomposition (beta, alpha, Treynor, M², appraisal, variance split)
is mathematically undefined and reported as ``None`` with an honest note — this
is the same degeneracy handling ``benchmark_comparison`` uses for its
variance-dependent metrics. Callers that DO have a varying benchmark (an index
return series) pass ``benchmark_returns`` directly and then every metric
populates.

Annualization convention
========================
Returns/alpha are compounded geometrically at 365 periods/year (the calendar-
day cadence of the daily equity curve, matching ``benchmark_comparison``'s
``DEFAULT_PERIODS_PER_YEAR``). Volatilities annualize by ``* sqrt(365)``.
Jensen's alpha is annualized geometrically (``(1+alpha_daily)**365 - 1``); a
linear ``* 365`` alternative is intentionally NOT used (it overstates a daily
intercept). The appraisal ratio annualizes by ``* sqrt(365)`` (it is a
Sharpe-like ratio of a daily mean to a daily std).

Reuse (single source of truth)
==============================
The equity series is **reused by import** from
:mod:`spa_core.paper_trading.drawdown_analytics` (``extract_equity_series``);
period returns are derived by a small pure helper (:func:`period_returns`).
:func:`content_fingerprint` is **reused by import** from
:mod:`spa_core.reporting.tear_sheet` (project convention MP-501) so idempotency
is byte-for-byte identical to the rest of the suite. The OLS / covariance /
variance math is implemented from scratch in pure stdlib in THIS module so it
is self-contained and hand-verifiable.

What this is NOT
================
* NOT ``benchmark_comparison`` (that is the excess-return / active-risk view;
  this is the CAPM-regression risk-adjusted view it left out).
* NOT money-moving — STRICTLY READ-ONLY / advisory. It only READS the equity
  track (``data/equity_curve_daily.json``) and writes its OWN derived status
  artifact. It never touches risk / execution / allocator / wallets and does
  NOT touch the frozen feed-health domain (SPA-BL-011).

Advisory verdict (never a gate; verdict in {"ok","warn"})
=========================================================
Based on Jensen's annualized alpha when it is defined:
* annualized alpha clearly positive or near zero -> ``ok``
  (note "positive risk-adjusted excess return" when clearly positive).
* annualized alpha strongly negative (< :data:`ALPHA_WARN_PCT`) -> ``warn``.
A **low-sample guard** keeps the verdict at ``warn`` (never harsher — analytics
never "fail") when ``n < MIN_SAMPLE_GUARD`` regardless; thin evidence is noted.
With the flat default benchmark the decomposition is undefined: ``available``
stays True, ``verdict`` is ``ok`` and a note explains a varying benchmark is
required. ``verdict_reason`` is always present. Insufficient data
(``n < MIN_OBS``) -> ``available:false``, ``verdict:"ok"`` — schema stays stable.

Output / persistence
====================
:func:`build_capm_decomposition` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (``tempfile.mkstemp`` + ``os.replace``) writes
``data/capm_decomposition.json`` with an in-file ``history`` (rotation <=
:data:`HISTORY_MAX`). Idempotency via :func:`content_fingerprint` (REUSED BY
IMPORT from :mod:`spa_core.reporting.tear_sheet`, MP-501) over the doc EXCLUDING
the volatile ``meta.generated_at`` / ``history``.

CLI::

    python3 -m spa_core.paper_trading.capm_decomposition --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.capm_decomposition --run     # + atomic write
    python3 -m spa_core.paper_trading.capm_decomposition --run --data-dir <dir>

Scope / safety: pure stdlib
(json/math/statistics/datetime/pathlib/logging/argparse/os/sys/tempfile) — no
requests/web3/numpy/pandas/scipy/LLM SDK/sockets/network/subprocess/eval/exec.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# -- Equity series REUSED BY IMPORT (single source of truth, drawdown_analytics
# MP-115). We do NOT re-implement equity parsing here. -----------------------
from spa_core.paper_trading.drawdown_analytics import extract_equity_series

# -- content_fingerprint REUSED BY IMPORT (project convention, MP-501) --------
from spa_core.reporting.tear_sheet import content_fingerprint
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.capm_decomposition")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "capm_decomposition"
STATUS_FILENAME: str = "capm_decomposition.json"
EQUITY_FILENAME: str = "equity_curve_daily.json"
HISTORY_MAX: int = 500

# Require a comfortable number of *returns*. n returns require n+1 equity points.
MIN_OBS: int = 20

# Flat-benchmark annual rate (%). 4.0% ~ a conservative stablecoin / risk-free
# lending baseline; mirrors benchmark_comparison.DEFAULT_BENCHMARK_APY. The
# decomposition is then read as a regression on the risk-free baseline (which,
# being flat, has zero variance -> the decomposition is undefined; callers pass
# a varying benchmark_returns to populate every metric).
DEFAULT_RISK_FREE_APY: float = 4.0

# Periods per year for annualisation and the flat-rate per-day conversion. 365
# matches the calendar-day cadence of the daily equity curve (and
# benchmark_comparison.DEFAULT_PERIODS_PER_YEAR).
PERIODS_PER_YEAR: int = 365

# Advisory thresholds (documented heuristics, advisory only — never a gate).
# Jensen's annualized alpha at/above ALPHA_OK_PCT is flagged as a clearly
# positive risk-adjusted excess return; at/below ALPHA_WARN_PCT it is a (soft)
# "warn". The band between them is a neutral "ok". Conservative on purpose.
ALPHA_OK_PCT: float = 2.0
ALPHA_WARN_PCT: float = -2.0

# Low-sample guard: with fewer than this many returns the verdict is held at
# "warn" at worst (analytics never "fail") and the thin-evidence note is added.
MIN_SAMPLE_GUARD: int = 40

__all__ = [
    "period_returns",
    "flat_daily_return",
    "covariance",
    "ols_capm",
    "build_capm_decomposition",
    "write_status",
    "main",
    "content_fingerprint",
    "extract_equity_series",
    "MIN_OBS",
    "HISTORY_MAX",
    "SOURCE_NAME",
    "STATUS_FILENAME",
    "DEFAULT_RISK_FREE_APY",
    "PERIODS_PER_YEAR",
    "ALPHA_OK_PCT",
    "ALPHA_WARN_PCT",
    "MIN_SAMPLE_GUARD",
]


# ------------------------------------------------------------------------------
# Pure hand-verifiable math (no I/O)
# ------------------------------------------------------------------------------

def period_returns(series: List[Tuple[str, float]]) -> List[float]:
    """Simple period returns from an equity series.

        r_k = E_k / E_{k-1} - 1

    Consumes a list of ``(date, equity_level)`` pairs (as produced by
    :func:`extract_equity_series`) and returns ``len(series) - 1`` returns.
    A non-positive or non-finite prior equity level is skipped (its step
    produces no return) so the function NEVER raises and never emits ``inf`` /
    ``nan``. Fewer than 2 points -> ``[]``.

    Hand example: ``[("d0",100),("d1",110),("d2",99)]`` -> ``[0.10, -0.10]``.
    """
    out: List[float] = []
    if not series or len(series) < 2:
        return out
    prev: Optional[float] = None
    for _date, eq in series:
        try:
            cur = float(eq)
        except (TypeError, ValueError):
            cur = float("nan")
        if prev is not None and math.isfinite(prev) and prev > 0 and math.isfinite(cur):
            out.append(cur / prev - 1.0)
        prev = cur
    return out


def flat_daily_return(annual_pct: float, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    """Per-period return of a flat annual rate, compounded (as a fraction).

        (1 + annual/100) ** (1/periods) - 1

    Returns ``0.0`` for a non-positive ``periods_per_year``. Pure / never
    raises. Note: returns a *fraction* (e.g. 0.000107...) NOT a percentage,
    matching the units of :func:`period_returns`.

    Hand example: ``annual_pct=4.0`` -> ``(1.04) ** (1/365) - 1`` ~= 1.0746e-4.
    """
    if periods_per_year <= 0:
        return 0.0
    return (1.0 + annual_pct / 100.0) ** (1.0 / periods_per_year) - 1.0


def covariance(xs: List[float], ys: List[float], mean_x: float, mean_y: float) -> float:
    """Population covariance of two equal-length series.

        cov = mean( (x - mean_x) * (y - mean_y) )

    Returns ``0.0`` for an empty input. Pure / never raises.
    """
    n = len(xs)
    if n == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / n


def ols_capm(
    rp: List[float],
    rm: List[float],
    rf_daily: float,
) -> Optional[Dict[str, Any]]:
    """Population OLS of the portfolio EXCESS return on the benchmark EXCESS
    return: ``(Rp - Rf) = alpha + beta*(Rm - Rf) + residual``.

    Because ``Rf`` is a constant it cancels out of the slope, so
    ``beta = cov(Rp, Rm) / var(Rm)`` (population cov/var) and the intercept is
    the daily Jensen's alpha ``alpha = mean(Rp) - [Rf + beta*(mean(Rm)-Rf)]``.

    Returns ``None`` when the series are misaligned/empty or the benchmark has
    ZERO population variance (a flat benchmark -> beta undefined). Otherwise a
    dict with ``beta``, ``alpha_daily``, ``mean_p``, ``mean_m``, ``var_m``,
    ``var_p``, ``correlation``, ``residuals`` (the daily residual series). Pure
    / never raises.

    Hand example: ``rp=[0.02,-0.01,0.03], rm=[0.01,-0.02,0.02], rf=0`` ->
    var_m and cov computed on a population basis; beta = cov/var_m.
    """
    n = len(rp)
    if n == 0 or n != len(rm):
        return None
    mean_p = statistics.fmean(rp)
    mean_m = statistics.fmean(rm)
    var_m = statistics.pvariance(rm) if n >= 1 else 0.0
    if var_m <= 0.0:
        return None
    var_p = statistics.pvariance(rp) if n >= 1 else 0.0
    cov_pm = covariance(rp, rm, mean_p, mean_m)
    beta = cov_pm / var_m
    # CAPM intercept (daily Jensen's alpha).
    alpha_daily = mean_p - (rf_daily + beta * (mean_m - rf_daily))
    # Pearson correlation (guard tiny floating-point overshoot beyond [-1, 1]).
    if var_p > 0.0:
        correlation = cov_pm / math.sqrt(var_p * var_m)
        correlation = max(-1.0, min(1.0, correlation))
    else:
        correlation = 0.0
    # Residual series: e_t = (Rp_t - Rf) - (alpha + beta*(Rm_t - Rf)).
    residuals = [
        (p - rf_daily) - (alpha_daily + beta * (m - rf_daily))
        for p, m in zip(rp, rm)
    ]
    return {
        "beta": beta,
        "alpha_daily": alpha_daily,
        "mean_p": mean_p,
        "mean_m": mean_m,
        "var_m": var_m,
        "var_p": var_p,
        "correlation": correlation,
        "residuals": residuals,
    }


def _compound(returns: List[float]) -> float:
    """Cumulative compounded return (fraction) of per-period returns (fractions)."""
    factor = 1.0
    for r in returns:
        factor *= (1.0 + r)
    return factor - 1.0


def _annualize_total(total: float, n: int, periods_per_year: int) -> float:
    """Geometric annualization (fraction) of a realised compounded return."""
    if n <= 0:
        return 0.0
    factor = 1.0 + total
    if factor <= 0.0:
        return -1.0
    return factor ** (periods_per_year / n) - 1.0


# ------------------------------------------------------------------------------
# is_demo (honest, from the equity source artifact) — never raises
# ------------------------------------------------------------------------------

def _detect_is_demo(data_dir: Path) -> Optional[bool]:
    """Honest demo flag from ``equity_curve_daily.json`` (the equity source),
    else ``None``. Looks for a top-level / ``meta`` ``is_demo`` boolean. Never
    raises.
    """
    p = data_dir / EQUITY_FILENAME
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    if isinstance(d.get("is_demo"), bool):
        return d["is_demo"]
    meta = d.get("meta")
    if isinstance(meta, dict) and isinstance(meta.get("is_demo"), bool):
        return meta["is_demo"]
    return None


# ------------------------------------------------------------------------------
# Main builder
# ------------------------------------------------------------------------------

def _unavailable(
    reason: str,
    generated_at: str,
    notes: List[str],
    n_observations: Optional[int] = None,
    is_demo: Optional[bool] = None,
) -> Dict[str, Any]:
    """Stable-schema unavailable result. verdict='ok' (advisory no-op)."""
    return {
        "available": False,
        "reason": reason,
        "is_demo": is_demo,
        "beta": None,
        "correlation": None,
        "jensen_alpha_daily": None,
        "jensen_alpha_annualized_pct": None,
        "treynor_ratio": None,
        "modigliani_m2_pct": None,
        "m2_alpha_pct": None,
        "appraisal_ratio": None,
        "systematic_variance": None,
        "specific_variance": None,
        "capm_r_squared": None,
        "pct_systematic_risk": None,
        "sharpe_portfolio_daily": None,
        "portfolio_annualized_pct": None,
        "benchmark_annualized_pct": None,
        "risk_free_annual_pct": round(float(DEFAULT_RISK_FREE_APY), 8),
        "risk_free_daily": None,
        "benchmark_kind": None,
        "count_returns": None,
        "n_observations": n_observations,
        "start_date": None,
        "end_date": None,
        "verdict": "ok",
        "verdict_reason": f"insufficient data: {reason}",
        "notes": notes,
        "meta": {
            "generated_at": generated_at,
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "min_obs_required": MIN_OBS,
            "periods_per_year": PERIODS_PER_YEAR,
        },
    }


def build_capm_decomposition(
    data_dir: str | os.PathLike = _DEFAULT_DATA_DIR,
    benchmark_returns: Optional[List[float]] = None,
    risk_free_annual_pct: float = DEFAULT_RISK_FREE_APY,
    periods_per_year: int = PERIODS_PER_YEAR,
) -> Dict[str, Any]:
    """Compute the CAPM risk-decomposition over the equity track. Never raises.

    Loads ``equity_curve_daily.json``, extracts the equity series (REUSED from
    drawdown_analytics), derives the portfolio daily returns, builds the
    benchmark series (explicit ``benchmark_returns`` aligned by truncation, else
    a flat risk-free baseline), runs the population OLS of EXCESS returns and
    derives Jensen's alpha, the Treynor ratio, Modigliani M², the appraisal
    ratio and the systematic/specific variance decomposition. Returns a
    stable-schema dict.

    With the flat default benchmark (``benchmark_returns is None``) the benchmark
    variance is zero, so the entire decomposition is undefined (``None``);
    ``available`` stays True with an honest note. Pass a varying
    ``benchmark_returns`` to populate every metric.
    """
    data_dir = Path(data_dir)
    notes: List[str] = []
    generated_at = datetime.now(timezone.utc).isoformat()
    is_demo: Optional[bool] = None
    benchmark_kind = "explicit" if benchmark_returns is not None else "flat_risk_free"

    try:
        is_demo = _detect_is_demo(data_dir)

        # -- Load equity track ourselves (filename constant) -------------------
        try:
            equity_doc = json.loads(
                (data_dir / EQUITY_FILENAME).read_text(encoding="utf-8")
            )
        except Exception as exc:
            return _unavailable(
                f"could not load {EQUITY_FILENAME}: {exc}",
                generated_at, notes, None, is_demo,
            )

        series = extract_equity_series(equity_doc)
        rp = period_returns(series)
        n = len(rp)
        if n < MIN_OBS:
            return _unavailable(
                f"only {n} daily returns (< {MIN_OBS} required)",
                generated_at, notes, n, is_demo,
            )

        start_date = series[0][0]
        end_date = series[-1][0]

        # -- Daily risk-free + benchmark series --------------------------------
        rf_daily = flat_daily_return(risk_free_annual_pct, periods_per_year)
        if benchmark_returns is None:
            rm = [rf_daily] * n
        else:
            m = min(n, len(benchmark_returns))
            rp = rp[:m]
            rm = [float(x) for x in benchmark_returns[:m]]
            n = m
            # re-derive the date span over the aligned window (n returns span
            # the first n+1 equity points: series[0] .. series[n]).
            end_date = series[n][0] if n < len(series) else series[-1][0]
        if n < MIN_OBS:
            return _unavailable(
                f"only {n} aligned returns (< {MIN_OBS} required)",
                generated_at, notes, n, is_demo,
            )

        # Portfolio-only stats (defined regardless of the benchmark variance).
        mean_p = statistics.fmean(rp)
        std_p = statistics.pstdev(rp) if n >= 1 else 0.0
        sharpe_p_daily = (mean_p - rf_daily) / std_p if std_p > 0.0 else None
        port_ann = _annualize_total(_compound(rp), n, periods_per_year)
        bench_ann = _annualize_total(_compound(rm), n, periods_per_year)
        rf_annual_eff = (1.0 + rf_daily) ** periods_per_year - 1.0

        # -- CAPM OLS of EXCESS returns ----------------------------------------
        fit = ols_capm(rp, rm, rf_daily)

        if fit is None:
            # Degenerate: benchmark has zero variance (the flat default) -> the
            # entire decomposition is undefined. Honest, advisory ok + note.
            notes.append(
                "flat risk-free benchmark has zero variance -- CAPM "
                "decomposition requires a varying benchmark series (pass "
                "benchmark_returns)"
            )
            verdict_reason = (
                "CAPM decomposition undefined: the benchmark has zero variance "
                f"(benchmark_kind={benchmark_kind}); beta, Jensen's alpha, "
                "Treynor, M2, appraisal and the variance split all require a "
                "varying benchmark. Pass benchmark_returns to populate them."
            )
            return {
                "available": True,
                "is_demo": is_demo,
                "beta": None,
                "correlation": None,
                "jensen_alpha_daily": None,
                "jensen_alpha_annualized_pct": None,
                "treynor_ratio": None,
                "modigliani_m2_pct": None,
                "m2_alpha_pct": None,
                "appraisal_ratio": None,
                "systematic_variance": None,
                "specific_variance": None,
                "capm_r_squared": None,
                "pct_systematic_risk": None,
                "sharpe_portfolio_daily": (
                    round(sharpe_p_daily, 8) if sharpe_p_daily is not None else None
                ),
                "portfolio_annualized_pct": round(port_ann * 100.0, 8),
                "benchmark_annualized_pct": round(bench_ann * 100.0, 8),
                "risk_free_annual_pct": round(float(risk_free_annual_pct), 8),
                "risk_free_daily": round(rf_daily, 8),
                "benchmark_kind": benchmark_kind,
                "count_returns": n,
                "n_observations": n,
                "start_date": start_date,
                "end_date": end_date,
                "verdict": "ok",
                "verdict_reason": verdict_reason,
                "notes": notes,
                "meta": {
                    "generated_at": generated_at,
                    "schema_version": SCHEMA_VERSION,
                    "source": SOURCE_NAME,
                    "min_obs_required": MIN_OBS,
                    "periods_per_year": periods_per_year,
                },
            }

        beta = fit["beta"]
        alpha_daily = fit["alpha_daily"]
        var_m = fit["var_m"]
        correlation = fit["correlation"]
        residuals = fit["residuals"]

        # -- Jensen's alpha annualized (geometric) -----------------------------
        # Geometric: ((1 + alpha_daily) ** periods) - 1. A linear * periods
        # convention is intentionally NOT used (it overstates a daily intercept).
        alpha_factor = 1.0 + alpha_daily
        if alpha_factor <= 0.0:
            alpha_ann_pct = -100.0
        else:
            alpha_ann_pct = (alpha_factor ** periods_per_year - 1.0) * 100.0

        # -- Treynor ratio: excess annual return per unit of systematic risk ---
        # (ann. portfolio return - ann. Rf) / beta. None if beta <= 0 (a non-
        # positive beta makes the per-unit-of-market-risk reading meaningless).
        if beta > 0.0:
            treynor = (port_ann - rf_annual_eff) / beta
        else:
            treynor = None
            notes.append(
                f"Treynor ratio undefined: beta {beta:.6f} <= 0 (reward per "
                "unit of systematic risk is meaningless for a non-positive beta)"
            )

        # -- Modigliani M2 (RAP), annualized % ---------------------------------
        # M2 = Rf_ann + sharpe_p * sigma_benchmark_annual, levering the book to
        # the benchmark's volatility. sigma_benchmark_annual in % units.
        sigma_bench_annual_pct = math.sqrt(var_m) * math.sqrt(periods_per_year) * 100.0
        if sharpe_p_daily is not None:
            m2_pct = rf_annual_eff * 100.0 + sharpe_p_daily * sigma_bench_annual_pct
            m2_alpha_pct = m2_pct - bench_ann * 100.0
        else:
            m2_pct = None
            m2_alpha_pct = None
            notes.append(
                "Modigliani M2 undefined: portfolio Sharpe undefined "
                "(zero portfolio volatility)"
            )

        # -- Appraisal ratio: alpha per unit of SPECIFIC risk ------------------
        # alpha_daily / pstdev(residuals), annualized * sqrt(periods).
        resid_std = statistics.pstdev(residuals) if len(residuals) >= 1 else 0.0
        if resid_std > 0.0:
            appraisal = (alpha_daily / resid_std) * math.sqrt(periods_per_year)
        else:
            appraisal = None
            notes.append(
                "appraisal ratio undefined: zero residual (specific) risk"
            )

        # -- Systematic / specific variance decomposition ----------------------
        systematic_variance = beta * beta * var_m
        specific_variance = statistics.pvariance(residuals) if len(residuals) >= 1 else 0.0
        total_var = systematic_variance + specific_variance
        if total_var > 0.0:
            capm_r_squared = systematic_variance / total_var
            capm_r_squared = max(0.0, min(1.0, capm_r_squared))
            pct_systematic_risk = capm_r_squared * 100.0
        else:
            capm_r_squared = None
            pct_systematic_risk = None

        # -- Advisory verdict (on Jensen's annualized alpha) -------------------
        # analytics never "fail": verdict in {"ok","warn"} only.
        if alpha_ann_pct <= ALPHA_WARN_PCT:
            verdict = "warn"
            verdict_reason = (
                f"Jensen's annualized alpha {alpha_ann_pct:.4f}% <= "
                f"{ALPHA_WARN_PCT}% -- negative risk-adjusted excess return "
                f"(beta {beta:.4f}); the book earned less than CAPM expects for "
                "the market risk it took"
            )
        elif alpha_ann_pct >= ALPHA_OK_PCT:
            verdict = "ok"
            verdict_reason = (
                f"Jensen's annualized alpha {alpha_ann_pct:.4f}% >= "
                f"{ALPHA_OK_PCT}% -- positive risk-adjusted excess return "
                f"(beta {beta:.4f}); the book added return beyond its market "
                "exposure"
            )
        else:
            verdict = "ok"
            verdict_reason = (
                f"Jensen's annualized alpha {alpha_ann_pct:.4f}% is near zero "
                f"(within [{ALPHA_WARN_PCT}%, {ALPHA_OK_PCT}%]; beta "
                f"{beta:.4f}) -- risk-adjusted return roughly in line with CAPM"
            )

        # Low-sample guard: thin evidence is held at "warn" at worst and noted.
        if n < MIN_SAMPLE_GUARD:
            notes.append(
                f"low-sample guard: only {n} returns (< {MIN_SAMPLE_GUARD}); "
                "CAPM estimates rest on thin evidence -- treat as weak"
            )
            if verdict not in ("ok", "warn"):
                verdict = "warn"

        def _rnd(x: Optional[float], places: int = 8) -> Optional[float]:
            return None if x is None else round(x, places)

        result: Dict[str, Any] = {
            "available": True,
            "is_demo": is_demo,
            "beta": _rnd(beta),
            "correlation": _rnd(correlation),
            "jensen_alpha_daily": _rnd(alpha_daily),
            "jensen_alpha_annualized_pct": _rnd(alpha_ann_pct),
            "treynor_ratio": _rnd(treynor),
            "modigliani_m2_pct": _rnd(m2_pct),
            "m2_alpha_pct": _rnd(m2_alpha_pct),
            "appraisal_ratio": _rnd(appraisal),
            "systematic_variance": _rnd(systematic_variance),
            "specific_variance": _rnd(specific_variance),
            "capm_r_squared": _rnd(capm_r_squared),
            "pct_systematic_risk": _rnd(pct_systematic_risk),
            "sharpe_portfolio_daily": _rnd(sharpe_p_daily),
            "portfolio_annualized_pct": _rnd(port_ann * 100.0),
            "benchmark_annualized_pct": _rnd(bench_ann * 100.0),
            "risk_free_annual_pct": round(float(risk_free_annual_pct), 8),
            "risk_free_daily": _rnd(rf_daily),
            "benchmark_kind": benchmark_kind,
            "count_returns": n,
            "n_observations": n,
            "start_date": start_date,
            "end_date": end_date,
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "notes": notes,
            "meta": {
                "generated_at": generated_at,
                "schema_version": SCHEMA_VERSION,
                "source": SOURCE_NAME,
                "min_obs_required": MIN_OBS,
                "periods_per_year": periods_per_year,
            },
        }
        return result

    except Exception as exc:  # last-resort: NEVER raise
        log.exception("unexpected error in build_capm_decomposition")
        return _unavailable(
            f"unexpected error: {exc}", generated_at, notes, None, is_demo
        )


# ------------------------------------------------------------------------------
# Atomic persistence (content_fingerprint reused by import — see top of module)
# ------------------------------------------------------------------------------

def write_status(
    result: Dict[str, Any],
    data_dir: str | os.PathLike = _DEFAULT_DATA_DIR,
) -> str:
    """Atomically write capm_decomposition.json.

    Returns ``"DATA_WRITTEN"`` | ``"DATA_UNCHANGED"``. Idempotent by
    :func:`content_fingerprint` (ignores ``meta.generated_at`` / ``history``).
    Rotates ``history`` to <= :data:`HISTORY_MAX`. Tolerant of a broken /
    absent previous status file.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / STATUS_FILENAME

    current_fp = content_fingerprint(result)

    existing: Dict[str, Any] = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except Exception:
            existing = {}

    if existing.get("_fingerprint") == current_fp:
        return "DATA_UNCHANGED"

    history: List[Dict[str, Any]] = existing.get("history", [])
    if not isinstance(history, list):
        history = []
    if existing and "_fingerprint" in existing:
        prev_entry = {k: v for k, v in existing.items() if k != "history"}
        history = [prev_entry] + history
        history = history[:HISTORY_MAX]

    doc = dict(result)
    doc["_fingerprint"] = current_fp
    doc["history"] = history

    atomic_save(doc, str(out_path))
    return "DATA_WRITTEN"


# ------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------

def _print_result(result: Dict[str, Any]) -> None:
    if not result.get("available"):
        print(
            f"[capm_decomposition] available=false reason={result.get('reason', '?')}"
        )
        print(f"  verdict       : {result.get('verdict')} -- {result.get('verdict_reason')}")
        for n in result.get("notes", []):
            print(f"  note: {n}")
        return

    print("[capm_decomposition] available=true")
    print(f"  verdict       : {result['verdict']} -- {result['verdict_reason']}")
    print(f"  benchmark     : {result['benchmark_kind']}")
    print(f"  beta          : {result['beta']}")
    print(f"  correlation   : {result['correlation']}")
    print(f"  jensen_alpha  : {result['jensen_alpha_daily']} (daily) / "
          f"{result['jensen_alpha_annualized_pct']}% (ann)")
    print(f"  treynor       : {result['treynor_ratio']}")
    print(f"  M2 / M2_alpha : {result['modigliani_m2_pct']}% / {result['m2_alpha_pct']}%")
    print(f"  appraisal     : {result['appraisal_ratio']}")
    print(f"  var systematic: {result['systematic_variance']}")
    print(f"  var specific  : {result['specific_variance']}")
    print(f"  pct_systematic: {result['pct_systematic_risk']}")
    print(f"  port/bench ann: {result['portfolio_annualized_pct']}% / "
          f"{result['benchmark_annualized_pct']}%")
    print(f"  rf annual/day : {result['risk_free_annual_pct']}% / {result['risk_free_daily']}")
    print(f"  count_returns : {result['count_returns']}")
    print(f"  n_obs         : {result['n_observations']}")
    print(f"  start / end   : {result['start_date']} / {result['end_date']}")
    if result.get("is_demo") is not None:
        print(f"  is_demo       : {result['is_demo']}")
    for n in result.get("notes", []):
        print(f"  note: {n}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="CAPM Risk-Decomposition Analyzer (MP-150) -- read-only / "
                    "advisory (Jensen's alpha, Treynor, Modigliani M2, "
                    "appraisal ratio, systematic/specific variance split)",
        add_help=True,
    )
    parser.add_argument(
        "--check", action="store_true",
        help="compute and print, no write (default)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="compute, print, and atomically write to "
             "data/capm_decomposition.json",
    )
    parser.add_argument(
        "--data-dir", default=None,
        help="override data directory (default: <repo_root>/data)",
    )

    try:
        args, unknown = parser.parse_known_args(argv)
    except SystemExit:
        # argparse may try to exit on a hard parse error; swallow -> exit 0.
        print("ERROR: invalid arguments", file=sys.stderr)
        return 0

    if unknown:
        print(f"ERROR: invalid arguments: {unknown}", file=sys.stderr)
        return 0

    # --check / --run mutually exclusive; conflict -> ERROR to stderr, exit 0.
    if args.check and args.run:
        print("ERROR: --check and --run are mutually exclusive", file=sys.stderr)
        return 0

    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR

    result = build_capm_decomposition(data_dir)
    _print_result(result)

    if args.run:
        status = write_status(result, data_dir)
        print(f"[capm_decomposition] write_status={status}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
