#!/usr/bin/env python3
"""K-Ratio (Kestner) Analyzer (SPA-V482 / MP-513) — read-only / advisory.

The existing performance suite has two large families: *distribution* metrics
(Sharpe / Sortino / Omega / Rachev — how good the per-period return
distribution is) and *drawdown* metrics (Calmar / Sterling / Burke /
Martin·Ulcer / Pain — how deep the track sat underwater). NEITHER family
measures the **consistency / trend quality** of the equity curve over TIME:
how *steadily* (linearly, in log space) capital compounds. Two tracks can end
at the same equity, with the same Sharpe and the same max drawdown, yet one
climbs in a smooth straight line while the other lurches up in jagged bursts.
The smooth one is more trustworthy and more capacity-robust. That is the gap
MP-513 closes with the **K-Ratio** (Lars Kestner).

Why the K-Ratio (and how it differs from everything else)
=========================================================
The K-Ratio regresses the *cumulative log-equity* curve against a *time index*
and divides the regression slope by the statistical uncertainty of that slope.
A high K-Ratio means the slope (growth rate) is large AND tightly estimated --
i.e. the curve hugs a straight upward line. A low or negative K-Ratio means the
growth is weak / erratic / downward relative to its noise.

* Sharpe / Sortino / Omega summarise the *return distribution* and are
  order-independent: shuffle the daily returns and they do not change.
* Calmar / Sterling / Burke / Martin summarise *drawdown depth*.
* The **K-Ratio is order-DEPENDENT and time-aware** -- it is the only metric
  here that rewards a steady, monotone climb and penalises a choppy path to the
  same endpoint. Shuffling the daily returns changes it.

Formula (hand-verifiable)
=========================
Given equity levels ``E_1 .. E_n`` (n points), form the cumulative log-return
curve ``y_i = ln(E_i / E_1)`` (so ``y_1 = 0``) against the time index
``x_i = i`` (``1 .. n``). Ordinary least squares of ``y`` on ``x``::

    x̄ = mean(x_i),  ȳ = mean(y_i)
    Sxx = Σ (x_i - x̄)²
    Sxy = Σ (x_i - x̄)(y_i - ȳ)
    slope     b   = Sxy / Sxx
    intercept a   = ȳ - b·x̄
    residual  e_i = y_i - (a + b·x_i)
    residual std error  s    = sqrt( Σ e_i² / (n - 2) )
    std error of slope  se_b = s / sqrt(Sxx)
    t-stat              t    = b / se_b
    K-Ratio (Kestner 2003 revised)  K = b / (se_b · n) = t / n

Hand example (pure OLS, ``ols_slope_intercept`` / ``slope_std_error`` /
``k_ratio``): ``xs = [1,2,3,4,5]``, ``ys = [1,2,3,4,6]`` ->
``x̄=3``, ``ȳ=3.2``, ``Sxx=10``, ``Sxy=12`` -> ``b=1.2``, ``a=-0.4``;
residuals ``[0.2, 0, -0.2, -0.4, 0.4]`` -> ``SSE=0.4`` ->
``s=sqrt(0.4/3)=0.365148`` -> ``se_b=0.365148/sqrt(10)=0.115470`` ->
``t=1.2/0.115470=10.392305`` -> ``K=t/5=2.078461``.

Edge cases (all guarded; never raise)
=====================================
* ``n < MIN_OBS`` (=10) -> ``available:false``, ``verdict:"ok"`` (stable schema).
* ``n < 3`` -> regression undefined (``n-2 < 1``) -> ``k_ratio = None``.
* **Perfectly linear log-equity** (constant daily compounding) -> all residuals
  ``0`` -> ``se_b = 0`` -> ``k_ratio = None`` with a note. A perfectly steady
  track is the IDEAL, not a failure -> ``verdict:"ok"``.
* Any ``E_i <= 0`` / non-finite / non-numeric -> dropped safely (the equity
  series is REUSED from drawdown_analytics, which already filters non-positive).
* Zero variance in ``x`` -> guarded (cannot happen for ``n >= 2`` distinct
  indices, but guarded anyway).

Advisory verdict (higher K-Ratio is better)
===========================================
* **fail** -- ``k_ratio < K_FAIL`` (=0.0): the time-regressed growth is
  negative / not statistically upward -- a losing or directionless track.
* **warn** -- ``k_ratio < K_WARN`` (=0.5): marginally steady upward growth.
* **ok** -- otherwise, OR ``k_ratio is None`` (perfectly linear / insufficient
  data -> advisory no-op). ``verdict_reason`` is always present.

Reuse (single source of truth)
==============================
The equity series is **reused by import** from
:mod:`spa_core.paper_trading.drawdown_analytics` (``extract_equity_series``) --
we do NOT recompute equity extraction. :func:`content_fingerprint` is **reused
by import** from :mod:`spa_core.reporting.tear_sheet` (project convention
MP-501) so idempotency is byte-for-byte identical to the rest of the suite.

What this is NOT
================
* NOT a distribution metric (Sharpe/Sortino/Omega) -- those live elsewhere.
* NOT a drawdown metric (Calmar/Sterling/Burke/Martin/Ulcer/Pain).
* NOT money-moving -- STRICTLY READ-ONLY / advisory. It only READS the equity
  track (``data/equity_curve_daily.json``) and writes its OWN derived status
  artifact. It never touches risk / execution / monitoring / allocator /
  cycle_runner / golive_checker / adapters.

Output / persistence
====================
:func:`build_k_ratio` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (``tempfile.mkstemp`` + ``os.replace``) writes
``data/k_ratio.json`` with an in-file ``history`` (rotation <=
:data:`HISTORY_MAX`). Idempotency via :func:`content_fingerprint` over the doc
EXCLUDING the volatile ``meta.generated_at`` / ``history``.

CLI::

    python3 -m spa_core.paper_trading.k_ratio --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.k_ratio --run     # + atomic write
    python3 -m spa_core.paper_trading.k_ratio --run --data-dir <dir>

Scope / safety: pure stdlib
(json/math/datetime/pathlib/logging/argparse/os/sys/tempfile) -- no
requests/web3/numpy/pandas/scipy/LLM SDK/sockets/network/subprocess/eval/exec.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# -- Equity series REUSED BY IMPORT (single source of truth, drawdown_analytics
# MP-115). We do NOT recompute the equity extraction here. -------------------
from spa_core.paper_trading.drawdown_analytics import extract_equity_series

# -- content_fingerprint REUSED BY IMPORT (project convention, MP-501) --------
from spa_core.reporting.tear_sheet import content_fingerprint

log = logging.getLogger("spa.paper_trading.k_ratio")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "k_ratio"
STATUS_FILENAME: str = "k_ratio.json"
EQUITY_FILENAME: str = "equity_curve_daily.json"
HISTORY_MAX: int = 500

# Require a comfortable number of equity points for a meaningful regression.
MIN_OBS: int = 10

# Minimum points for the regression standard error to be defined (n - 2 >= 1).
MIN_REGRESSION_OBS: int = 3

# Advisory thresholds (documented). Higher K-Ratio = steadier upward compounding.
# WARN flanks "marginal" (< 0.5), FAIL flanks "not statistically upward" (< 0.0).
K_WARN: float = 0.5
K_FAIL: float = 0.0

__all__ = [
    "cumulative_log_returns",
    "ols_slope_intercept",
    "slope_std_error",
    "k_ratio",
    "k_ratio_from_equity",
    "build_k_ratio",
    "write_status",
    "main",
    "content_fingerprint",
    "extract_equity_series",
    "MIN_OBS",
    "MIN_REGRESSION_OBS",
    "HISTORY_MAX",
    "SOURCE_NAME",
    "STATUS_FILENAME",
    "K_WARN",
    "K_FAIL",
]


# ------------------------------------------------------------------------------
# Pure hand-verifiable math (no I/O)
# ------------------------------------------------------------------------------

def _finite_float(x: Any) -> Optional[float]:
    """Coerce ``x`` to a finite float, else ``None``. Rejects bool. Never raises."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        xf = float(x)
    except (ValueError, OverflowError):
        return None
    return xf if math.isfinite(xf) else None


def cumulative_log_returns(levels: List[float]) -> List[float]:
    """Cumulative log-return curve ``y_i = ln(E_i / E_1)`` from equity levels.

    ``y_1`` is always ``0.0``. Requires the *first* level to be a finite,
    strictly-positive number; otherwise returns ``[]`` (cannot anchor the
    curve). Any later non-positive / non-finite level is dropped so the curve
    never blows up. Pure / never raises.

    Hand example: levels ``[100, 110, 121]`` -> ``[0.0, ln(1.1), ln(1.21)]`` =
    ``[0.0, 0.0953102, 0.1906204]``.
    """
    if not levels or not isinstance(levels, list):
        return []
    base = _finite_float(levels[0])
    if base is None or base <= 0:
        return []
    out: List[float] = []
    for lv in levels:
        lvf = _finite_float(lv)
        if lvf is None or lvf <= 0:
            continue
        try:
            out.append(math.log(lvf / base))
        except (ValueError, ZeroDivisionError, OverflowError):
            continue
    return out


def ols_slope_intercept(
    xs: List[float], ys: List[float]
) -> Optional[Tuple[float, float]]:
    """Ordinary-least-squares ``(slope, intercept)`` of ``ys`` on ``xs``.

        slope     = Σ(x-x̄)(y-ȳ) / Σ(x-x̄)²
        intercept = ȳ - slope·x̄

    Returns ``None`` if the lists are empty / mismatched in length, shorter than
    2, contain a non-finite value, or have zero variance in ``x``
    (``Σ(x-x̄)² == 0``). Pure / never raises.

    Hand example: ``xs=[1,2,3,4,5]``, ``ys=[1,2,3,4,6]`` -> ``(1.2, -0.4)``.
    """
    if not xs or not ys or len(xs) != len(ys) or len(xs) < 2:
        return None
    try:
        xf = [_finite_float(x) for x in xs]
        yf = [_finite_float(y) for y in ys]
        if any(v is None for v in xf) or any(v is None for v in yf):
            return None
        n = len(xf)
        xbar = sum(xf) / n  # type: ignore[arg-type]
        ybar = sum(yf) / n  # type: ignore[arg-type]
        sxx = 0.0
        sxy = 0.0
        for xi, yi in zip(xf, yf):
            dx = xi - xbar  # type: ignore[operator]
            sxx += dx * dx
            sxy += dx * (yi - ybar)  # type: ignore[operator]
        if sxx <= 0:
            return None
        slope = sxy / sxx
        intercept = ybar - slope * xbar  # type: ignore[operator]
        if not (math.isfinite(slope) and math.isfinite(intercept)):
            return None
        return (slope, intercept)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def slope_std_error(xs: List[float], ys: List[float]) -> Optional[float]:
    """Standard error of the OLS slope.

        s    = sqrt( Σ residual_i² / (n - 2) )    (residual std error)
        se_b = s / sqrt( Σ(x-x̄)² )

    Returns ``None`` if the regression is undefined (see
    :func:`ols_slope_intercept`), if ``n < 3`` (``n-2 < 1``), or if
    ``Σ(x-x̄)² <= 0``. Returns ``0.0`` when the fit is exact (all residuals
    zero -- a perfectly linear track). Pure / never raises.

    Hand example: ``xs=[1,2,3,4,5]``, ``ys=[1,2,3,4,6]`` -> ``0.115470``.
    """
    fit = ols_slope_intercept(xs, ys)
    if fit is None:
        return None
    n = len(xs)
    if n < MIN_REGRESSION_OBS:
        return None
    try:
        slope, intercept = fit
        xf = [float(x) for x in xs]
        yf = [float(y) for y in ys]
        xbar = sum(xf) / n
        sxx = sum((xi - xbar) ** 2 for xi in xf)
        if sxx <= 0:
            return None
        sse = 0.0
        for xi, yi in zip(xf, yf):
            e = yi - (intercept + slope * xi)
            sse += e * e
        resid_var = sse / (n - 2)
        if resid_var < 0:
            resid_var = 0.0
        s = math.sqrt(resid_var)
        se_b = s / math.sqrt(sxx)
        if not math.isfinite(se_b):
            return None
        return se_b
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def k_ratio(
    slope: Optional[float],
    se_slope: Optional[float],
    n: int,
) -> Optional[float]:
    """Kestner (2003 revised) K-Ratio = ``slope / (se_slope * n)`` = ``t / n``.

    Returns ``None`` if ``slope`` or ``se_slope`` is ``None``, if ``n <= 0``, or
    if ``se_slope <= 0`` (a perfectly linear fit -> the slope is estimated with
    zero error -> the ratio is undefined / "infinitely good"; we report ``None``
    and let the caller note the perfectly-linear track). Pure / never raises.

    Hand example: ``slope=1.2``, ``se_slope=0.115470``, ``n=5`` ->
    ``1.2 / (0.115470 * 5) = 2.078461``.
    """
    if slope is None or se_slope is None or n <= 0 or se_slope <= 0:
        return None
    try:
        out = float(slope) / (float(se_slope) * float(n))
        return out if math.isfinite(out) else None
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def k_ratio_from_equity(
    series: List[Tuple[str, float]]
) -> Dict[str, Optional[float]]:
    """Full K-Ratio regression bundle from an equity ``(date, level)`` series.

    Builds the cumulative log-return curve ``y_i = ln(E_i/E_1)`` against the
    time index ``x_i = 1..n`` and runs the OLS regression. Returns a dict with
    ``slope``, ``intercept``, ``slope_std_error``, ``t_stat``, ``k_ratio`` and
    ``n`` (all numeric or ``None``). ``perfectly_linear`` is ``True`` when the
    fit is exact (``slope_std_error == 0``). Pure / never raises.
    """
    empty: Dict[str, Optional[float]] = {
        "slope": None,
        "intercept": None,
        "slope_std_error": None,
        "t_stat": None,
        "k_ratio": None,
        "n": 0,
        "perfectly_linear": False,
    }
    if not series or not isinstance(series, list):
        return dict(empty)

    levels = [lvl for (_d, lvl) in series]
    ys = cumulative_log_returns(levels)
    n = len(ys)
    empty["n"] = n
    if n < 2:
        return dict(empty)

    xs = list(range(1, n + 1))
    fit = ols_slope_intercept(xs, ys)
    if fit is None:
        return dict(empty)
    slope, intercept = fit
    se_b = slope_std_error(xs, ys)

    perfectly_linear = se_b == 0.0
    t_stat: Optional[float] = None
    if se_b is not None and se_b > 0:
        try:
            t_stat = slope / se_b
            if not math.isfinite(t_stat):
                t_stat = None
        except (ValueError, ZeroDivisionError, OverflowError):
            t_stat = None

    k = k_ratio(slope, se_b, n)

    return {
        "slope": slope,
        "intercept": intercept,
        "slope_std_error": se_b,
        "t_stat": t_stat,
        "k_ratio": k,
        "n": n,
        "perfectly_linear": perfectly_linear,
    }


# ------------------------------------------------------------------------------
# is_demo (honest, from the equity source artifact) -- never raises
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
        "k_ratio": None,
        "regression_slope": None,
        "slope_std_error": None,
        "t_stat": None,
        "intercept": None,
        "perfectly_linear": None,
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
        },
    }


def build_k_ratio(
    data_dir: str | os.PathLike = _DEFAULT_DATA_DIR,
) -> Dict[str, Any]:
    """Compute the K-Ratio over the equity track. Never raises.

    Loads ``equity_curve_daily.json``, extracts the equity series (REUSED from
    drawdown_analytics), builds the cumulative log-return curve, runs the OLS
    time regression and computes the Kestner K-Ratio plus the slope, slope
    standard error and t-stat. Returns a stable-schema dict.
    """
    data_dir = Path(data_dir)
    notes: List[str] = []
    generated_at = datetime.now(timezone.utc).isoformat()
    is_demo: Optional[bool] = None

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
        n = len(series)
        if n < MIN_OBS:
            return _unavailable(
                f"only {n} equity points (< {MIN_OBS} required)",
                generated_at, notes, n, is_demo,
            )

        bundle = k_ratio_from_equity(series)
        k = bundle["k_ratio"]
        slope = bundle["slope"]
        se_b = bundle["slope_std_error"]
        t_stat = bundle["t_stat"]
        intercept = bundle["intercept"]
        perfectly_linear = bool(bundle["perfectly_linear"])

        start_date = series[0][0]
        end_date = series[-1][0]

        # -- Advisory verdict (higher K-Ratio is better) ----------------------
        if k is None:
            verdict = "ok"
        elif k < K_FAIL:
            verdict = "fail"
        elif k < K_WARN:
            verdict = "warn"
        else:
            verdict = "ok"

        if perfectly_linear:
            notes.append(
                "perfectly linear log-equity (zero residual variance); "
                "K-Ratio undefined -- the steadiest possible track"
            )

        # verdict_reason (always present, descriptive).
        if k is None:
            if perfectly_linear:
                verdict_reason = (
                    "equity compounds on a perfectly straight log-line "
                    "(zero residual variance) -- K-Ratio undefined; this is "
                    "the ideal, steadiest growth"
                )
            else:
                verdict_reason = (
                    "K-Ratio undefined (regression not estimable on the "
                    f"available {n} points)"
                )
        elif verdict == "fail":
            verdict_reason = (
                f"K-Ratio {k:.4f} < {K_FAIL} -- the time-regressed growth "
                f"slope ({slope if slope is None else round(slope, 6)}) is not "
                f"statistically upward (t-stat "
                f"{t_stat if t_stat is None else round(t_stat, 4)} over {n} "
                f"points): a losing or directionless track"
            )
        elif verdict == "warn":
            verdict_reason = (
                f"K-Ratio {k:.4f} < {K_WARN} -- marginally steady upward "
                f"growth (slope {slope if slope is None else round(slope, 6)}, "
                f"t-stat {t_stat if t_stat is None else round(t_stat, 4)}, "
                f"{n} points)"
            )
        else:  # ok
            verdict_reason = (
                f"K-Ratio {k:.4f} >= {K_WARN} -- steady, statistically upward "
                f"compounding (slope {slope if slope is None else round(slope, 6)}, "
                f"t-stat {t_stat if t_stat is None else round(t_stat, 4)}, "
                f"{n} points)"
            )

        def _rnd(x: Optional[float], places: int = 6) -> Optional[float]:
            return None if x is None else round(x, places)

        result: Dict[str, Any] = {
            "available": True,
            "is_demo": is_demo,
            "k_ratio": _rnd(k),
            "regression_slope": _rnd(slope),
            "slope_std_error": _rnd(se_b),
            "t_stat": _rnd(t_stat),
            "intercept": _rnd(intercept),
            "perfectly_linear": perfectly_linear,
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
            },
        }
        return result

    except Exception as exc:  # last-resort: NEVER raise
        log.exception("unexpected error in build_k_ratio")
        return _unavailable(
            f"unexpected error: {exc}", generated_at, notes, None, is_demo
        )


# ------------------------------------------------------------------------------
# Atomic persistence (content_fingerprint reused by import -- see top of module)
# ------------------------------------------------------------------------------

def write_status(
    result: Dict[str, Any],
    data_dir: str | os.PathLike = _DEFAULT_DATA_DIR,
) -> str:
    """Atomically write k_ratio.json.

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

    fd, tmp_path = tempfile.mkstemp(dir=data_dir, prefix=".tmp_k_ratio_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        os.replace(tmp_path, out_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return "DATA_WRITTEN"


# ------------------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------------------

def _print_result(result: Dict[str, Any]) -> None:
    if not result.get("available"):
        print(
            f"[k_ratio] available=false reason={result.get('reason', '?')}"
        )
        print(
            f"  verdict       : {result.get('verdict')} -- "
            f"{result.get('verdict_reason')}"
        )
        for n in result.get("notes", []):
            print(f"  note: {n}")
        return

    print("[k_ratio] available=true")
    print(f"  verdict       : {result['verdict']} -- {result['verdict_reason']}")
    print(f"  k_ratio       : {result['k_ratio']}")
    print(f"  slope         : {result['regression_slope']}")
    print(f"  slope_std_err : {result['slope_std_error']}")
    print(f"  t_stat        : {result['t_stat']}")
    print(f"  perfectly_lin : {result['perfectly_linear']}")
    print(f"  n_obs         : {result['n_observations']}")
    print(f"  start / end   : {result['start_date']} / {result['end_date']}")
    if result.get("is_demo") is not None:
        print(f"  is_demo       : {result['is_demo']}")
    for n in result.get("notes", []):
        print(f"  note: {n}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="K-Ratio (Kestner) Analyzer (MP-513) -- read-only / advisory",
        add_help=True,
    )
    parser.add_argument(
        "--check", action="store_true",
        help="compute and print, no write (default)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="compute, print, and atomically write to data/k_ratio.json",
    )
    parser.add_argument(
        "--data-dir", default=None,
        help="override data directory (default: <repo_root>/data)",
    )

    try:
        args, unknown = parser.parse_known_args(argv)
    except SystemExit:
        print("ERROR: invalid arguments", file=sys.stderr)
        return 0

    if unknown:
        print(f"ERROR: invalid arguments: {unknown}", file=sys.stderr)
        return 0

    if args.check and args.run:
        print(
            "ERROR: --check and --run are mutually exclusive", file=sys.stderr
        )
        return 0

    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR

    result = build_k_ratio(data_dir)
    _print_result(result)

    if args.run:
        status = write_status(result, data_dir)
        print(f"[k_ratio] write_status={status}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
