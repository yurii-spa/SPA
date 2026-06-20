#!/usr/bin/env python3
"""Structural-Break / Change-Point Detector (SPA-V452 / MP-138) — read-only /
advisory.

The paper-trading analytics suite (linearity_analytics, alpha_decay,
regime_detector, regime_conditional_performance, serial_dependence,
return_predictability, deflated_sharpe, ...) describes the *distribution*,
*risk*, *time-ordering* and *significance* of the daily-return series -- but
NONE of them answers the single question a due-diligence reviewer asks about an
edge's durability: **is the track stationary, or is there a detectable
structural BREAK (change-point) where the strategy's mean daily return shifted
-- especially deteriorated?**

This module closes that gap with a classic, transparent two-step procedure on
the *daily return* series, implemented entirely from scratch on stdlib:

  1. **CUSUM diagnostic path** -- the cumulative sum of standardized deviations
     from the series mean, ``S_k = sum_{i<=k} (r_i - mean) / stdev``. A flat-ish
     ``S_k`` means a stationary mean; a large excursion flags a regime where the
     running mean drifted away from the global mean. The index of maximal
     ``|S_k|`` is the natural single change-point CANDIDATE.

  2. **Single-break binary-segmentation t-test** -- split the series at the
     candidate index (subject to a minimum-segment guard so neither side is a
     sliver), then run a two-sample **Welch t-test** (unequal variances) on the
     two segment means. A significant difference (two-sided p < alpha) is a
     detected structural break; the sign of ``mean_after - mean_before`` tells
     us whether the edge deteriorated or improved.

What this is NOT
================
* NOT a regime *classifier* (regime_detector) -- it asks the binary "is there
  ONE break in the mean?" question, not "which of K regimes are we in?".
* NOT a feed-health monitor -- it never touches the SPA-BL-011 frozen
  feed-health domain.
* NOT money-moving -- STRICTLY READ-ONLY / advisory. It only READS the equity
  track (via ``equity_curve.build_daily_equity_curve``, exactly as
  linearity_analytics.py does) and writes its OWN derived status artifact. It
  never touches risk / execution / allocator / cycle_runner / golive_checker.

p-value approximation (honest disclosure)
=========================================
:func:`two_sided_p_from_t` computes the two-sided tail of Student's t via the
regularized incomplete beta function ``I_x(a, b)`` (Lentz continued-fraction
evaluation, pure ``math``). This is the *exact* relationship
``p = I_{df/(df+t**2)}(df/2, 1/2)`` and is accurate to well within 1e-9 across
the range of t / df we encounter; it gracefully degrades (never raises) and
always returns a value clamped to ``[0, 1]``.

Advisory verdict
================
* **fail** -- break detected AND ``shift_direction == 'deterioration'`` (the
  edge structurally weakened: the mean daily return after the break is
  significantly lower -- a red flag for a decaying strategy).
* **warn** -- break detected AND ``shift_direction == 'improvement'`` (the
  process changed: the pre-break track is NOT representative of the current
  regime, so historical stats over the full track are misleading).
* **ok** -- no break detected (mean appears stationary over the track).
``verdict_reason`` is always present. Insufficient data
(``n < MIN_OBS`` / flat / zero-variance) -> ``available:false``,
``reason:"insufficient_data"``, ``verdict:"ok"`` -- schema stays stable.

Output / persistence
====================
:func:`build_structural_break` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (``tempfile.mkstemp`` + ``os.replace``) writes
``data/structural_break.json`` with an in-file ``history`` (rotation <=
:data:`HISTORY_MAX`). Idempotency via :func:`content_fingerprint` (REUSED BY
IMPORT from :mod:`spa_core.reporting.tear_sheet`, MP-501) over the doc EXCLUDING
the volatile ``meta.generated_at`` / ``history``.

CLI::

    python3 -m spa_core.paper_trading.structural_break --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.structural_break --run     # + atomic write
    python3 -m spa_core.paper_trading.structural_break --run --data-dir <dir>

Scope / safety: pure stdlib
(json/math/statistics/datetime/pathlib/logging/argparse/os/sys/tempfile) -- no
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
from typing import Any, Dict, List, Optional

# -- Equity track loaded EXACTLY as linearity_analytics.py loads it -----------
from spa_core.paper_trading.equity_curve import (
    load_pnl_history,
    build_daily_equity_curve,
)

# -- content_fingerprint REUSED BY IMPORT (project convention, MP-501) --------
from spa_core.reporting.tear_sheet import content_fingerprint
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.structural_break")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "structural_break"
STATUS_FILENAME: str = "structural_break.json"
EQUITY_FILENAME: str = "equity_curve_daily.json"
HISTORY_MAX: int = 500

# Need a comfortable margin so both sides of a candidate break can clear the
# default min_segment guard (5) and still leave a couple of bars of slack.
MIN_OBS: int = 12

DEFAULT_MIN_SEGMENT: int = 5
DEFAULT_ALPHA: float = 0.05

__all__ = [
    "cusum_path",
    "max_cusum_deviation",
    "candidate_break_index",
    "welch_t_test",
    "two_sided_p_from_t",
    "detect_structural_break",
    "build_structural_break",
    "write_status",
    "main",
    "content_fingerprint",
    "MIN_OBS",
    "HISTORY_MAX",
    "SOURCE_NAME",
    "STATUS_FILENAME",
]


# ------------------------------------------------------------------------------
# Pure CUSUM / change-point math (hand-verifiable, no I/O)
# ------------------------------------------------------------------------------

def cusum_path(returns: List[float]) -> List[float]:
    """Cumulative sum of standardized deviations from the mean.

        S_k = sum_{i <= k} (r_i - mean) / stdev      (k = 0 .. n-1)

    ``mean`` and ``stdev`` are the population mean / population standard
    deviation of the full series. This is a diagnostic CUSUM path: it starts
    near 0, wanders, and (because the deviations sum to zero) returns to 0 at
    the final index. A large excursion flags a stretch whose local mean drifted
    from the global mean -- the hallmark of a structural break.

    Degenerate inputs (``n < 2`` or ``stdev == 0``) -> a list of zeros of the
    same length. Pure / never raises.
    """
    n = len(returns)
    if n < 2:
        return [0.0] * n
    mean = statistics.fmean(returns)
    stdev = statistics.pstdev(returns)
    if stdev == 0:
        return [0.0] * n
    path: List[float] = []
    acc = 0.0
    for r in returns:
        acc += (r - mean) / stdev
        path.append(acc)
    return path


def max_cusum_deviation(returns: List[float]) -> Dict[str, Any]:
    """Index and value of the maximal-magnitude point of the CUSUM path.

    Returns ``{"index": int, "value": float}`` -- ``value`` is the *signed*
    ``S_k`` at the index of largest ``|S_k|``. Empty / degenerate (all-zero
    path) -> ``{"index": None, "value": 0.0}``. Pure / never raises.
    """
    path = cusum_path(returns)
    if not path:
        return {"index": None, "value": 0.0}
    best_i = 0
    best_abs = abs(path[0])
    for i, s in enumerate(path):
        a = abs(s)
        if a > best_abs:
            best_abs = a
            best_i = i
    if best_abs == 0.0:
        return {"index": None, "value": 0.0}
    return {"index": best_i, "value": path[best_i]}


def candidate_break_index(
    returns: List[float], min_segment: int = DEFAULT_MIN_SEGMENT
) -> Optional[int]:
    """Index of the single change-point candidate = argmax ``|S_k|``.

    The series is split into ``before = returns[:idx + 1]`` and
    ``after = returns[idx + 1:]`` (so the candidate bar belongs to the *before*
    segment). The candidate is returned only if BOTH resulting segments have at
    least ``min_segment`` observations; otherwise ``None`` (a break hugging the
    very edge of the track is not actionable). Pure / never raises.
    """
    dev = max_cusum_deviation(returns)
    idx = dev["index"]
    if idx is None:
        return None
    n = len(returns)
    len_before = idx + 1
    len_after = n - (idx + 1)
    if len_before < min_segment or len_after < min_segment:
        return None
    return idx


# ------------------------------------------------------------------------------
# Welch two-sample t-test + Student-t two-sided p-value (from scratch)
# ------------------------------------------------------------------------------

def welch_t_test(a: List[float], b: List[float]) -> Dict[str, Any]:
    """Two-sample Welch t-test for unequal variances, implemented from scratch.

        t  = (mean_a - mean_b) / sqrt(var_a / n_a + var_b / n_b)
        df = (var_a/n_a + var_b/n_b)**2
             / ( (var_a/n_a)**2/(n_a-1) + (var_b/n_b)**2/(n_b-1) )  (Welch-Satterthwaite)

    ``var_*`` are sample variances (ddof=1). Returns
    ``{t_stat, df, mean_a, mean_b, n_a, n_b}``. Degenerate cases (either group
    with < 2 observations, or a zero combined standard-error denominator) ->
    ``t_stat = None`` and ``df = None``. Pure / never raises.
    """
    n_a = len(a)
    n_b = len(b)
    base: Dict[str, Any] = {
        "t_stat": None,
        "df": None,
        "mean_a": (statistics.fmean(a) if n_a else None),
        "mean_b": (statistics.fmean(b) if n_b else None),
        "n_a": n_a,
        "n_b": n_b,
    }
    if n_a < 2 or n_b < 2:
        return base

    mean_a = base["mean_a"]
    mean_b = base["mean_b"]
    var_a = statistics.variance(a)  # ddof=1 sample variance
    var_b = statistics.variance(b)

    sa = var_a / n_a
    sb = var_b / n_b
    denom_sq = sa + sb
    if denom_sq <= 0.0:  # both groups perfectly constant -> undefined
        return base

    t_stat = (mean_a - mean_b) / math.sqrt(denom_sq)

    # Welch-Satterthwaite degrees of freedom.
    df_denom = 0.0
    if n_a > 1:
        df_denom += (sa * sa) / (n_a - 1)
    if n_b > 1:
        df_denom += (sb * sb) / (n_b - 1)
    df = (denom_sq * denom_sq) / df_denom if df_denom > 0.0 else None

    base["t_stat"] = t_stat
    base["df"] = df
    return base


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method).

    Mirrors Numerical Recipes' ``betacf``; pure ``math``. Used only inside
    :func:`_betai`. Converges for ``x < (a + 1)/(a + b + 2)``.
    """
    max_iter = 300
    eps = 3.0e-12
    fpmin = 1.0e-300

    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function ``I_x(a, b)``. Pure ``math``.

    ``I_x(a,b) = B(x; a,b) / B(a,b)``. Uses the symmetry relation plus the
    continued-fraction evaluator above. Returns a value in ``[0, 1]``.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    # Front factor: x^a (1-x)^b / [a * B(a,b)] via log-gamma for stability.
    ln_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(ln_beta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def two_sided_p_from_t(t: Optional[float], df: Optional[float]) -> Optional[float]:
    """Two-sided p-value of Student's t with ``df`` degrees of freedom.

    Exact relation (clamped to ``[0, 1]``)::

        p = I_{df/(df + t**2)}(df/2, 1/2)

    evaluated via the regularized incomplete beta function :func:`_betai`
    (continued-fraction; pure ``math``). Properties: symmetric in the sign of
    ``t``, monotonically decreasing in ``|t|``, ``p ~ 1`` at ``t = 0``. Returns
    ``None`` when ``t`` is ``None`` or ``df`` is ``None``/non-positive. Never
    raises -- any internal arithmetic failure degrades to ``None``.
    """
    if t is None or df is None or df <= 0.0:
        return None
    try:
        tt = float(t)
        x = df / (df + tt * tt)
        p = _betai(df / 2.0, 0.5, x)
        if not math.isfinite(p):
            return None
        return max(0.0, min(1.0, p))
    except (ValueError, OverflowError, ZeroDivisionError):
        return None


def detect_structural_break(
    returns: List[float],
    min_segment: int = DEFAULT_MIN_SEGMENT,
    alpha: float = DEFAULT_ALPHA,
) -> Dict[str, Any]:
    """Single-break binary-segmentation change-point test on a return series.

    Pipeline: find the CUSUM candidate index (subject to the ``min_segment``
    guard), split into before/after segments, run a Welch t-test on their means
    and convert to a two-sided p-value.

    Returns a stable-schema dict::

        {
          break_detected: bool,
          break_index: int | None,        # split point (last index of "before")
          t_stat: float | None,
          p_value: float | None,
          mean_before: float | None,
          mean_after: float | None,
          shift_direction: 'deterioration' | 'improvement' | 'none',
          segment_lengths: [len_before, len_after],
        }

    ``break_detected`` is ``True`` iff ``p_value`` is not ``None`` and
    ``p_value < alpha``. ``shift_direction`` is ``'deterioration'`` when
    ``mean_after < mean_before``, ``'improvement'`` when greater, else
    ``'none'``. Pure / never raises.
    """
    result: Dict[str, Any] = {
        "break_detected": False,
        "break_index": None,
        "t_stat": None,
        "p_value": None,
        "mean_before": None,
        "mean_after": None,
        "shift_direction": "none",
        "segment_lengths": [0, 0],
    }

    idx = candidate_break_index(returns, min_segment=min_segment)
    if idx is None:
        return result

    before = returns[: idx + 1]
    after = returns[idx + 1 :]
    result["break_index"] = idx
    result["segment_lengths"] = [len(before), len(after)]

    wt = welch_t_test(before, after)
    result["t_stat"] = wt["t_stat"]
    result["mean_before"] = wt["mean_a"]
    result["mean_after"] = wt["mean_b"]

    p = two_sided_p_from_t(wt["t_stat"], wt["df"])
    result["p_value"] = p

    mb = wt["mean_a"]
    ma = wt["mean_b"]
    if mb is not None and ma is not None:
        if ma < mb:
            result["shift_direction"] = "deterioration"
        elif ma > mb:
            result["shift_direction"] = "improvement"
        else:
            result["shift_direction"] = "none"

    result["break_detected"] = bool(p is not None and p < alpha)
    return result


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
        "break_detected": False,
        "break_index": None,
        "break_date": None,
        "n_observations": n_observations,
        "cusum_max_abs": None,
        "mean_before": None,
        "mean_after": None,
        "shift_direction": "none",
        "t_stat": None,
        "p_value": None,
        "verdict": "ok",
        "verdict_reason": f"insufficient data: {reason}",
        "min_segment": DEFAULT_MIN_SEGMENT,
        "alpha": DEFAULT_ALPHA,
        "notes": notes,
        "meta": {
            "generated_at": generated_at,
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE_NAME,
            "min_obs_required": MIN_OBS,
        },
    }


def build_structural_break(
    data_dir: str | os.PathLike = _DEFAULT_DATA_DIR,
    min_segment: int = DEFAULT_MIN_SEGMENT,
    alpha: float = DEFAULT_ALPHA,
) -> Dict[str, Any]:
    """Detect a single structural break in the mean daily return. Never raises.

    Loads the equity track EXACTLY as linearity_analytics.py does
    (``load_pnl_history`` + ``build_daily_equity_curve``), extracts the daily
    return series (excluding the seed bar), and runs the CUSUM +
    binary-segmentation Welch t-test. Returns a stable-schema dict.
    """
    data_dir = Path(data_dir)
    notes: List[str] = []
    generated_at = datetime.now(timezone.utc).isoformat()
    is_demo: Optional[bool] = None

    try:
        is_demo = _detect_is_demo(data_dir)

        # -- Load equity track (linearity_analytics.py loading style) ----------
        try:
            records = load_pnl_history(data_dir / "pnl_history.json")
            curve = build_daily_equity_curve(records)
        except Exception as exc:
            return _unavailable(f"could not load equity track: {exc}",
                                generated_at, notes, None, is_demo)

        # Daily returns: drop the synthetic seed bar (day 1), matching the rest
        # of the suite (probabilistic_sharpe / return_distribution).
        returns = [bar["daily_return_pct"] for bar in curve[1:]]
        # Dates aligned 1:1 with the returns above.
        dates = [bar.get("date") for bar in curve[1:]]

        n = len(returns)
        if n < MIN_OBS:
            return _unavailable(
                f"only {n} daily returns (< {MIN_OBS} required)",
                generated_at, notes, n, is_demo,
            )

        stdev = statistics.pstdev(returns)
        if stdev == 0:
            return _unavailable("flat / zero-variance return series",
                                generated_at, notes, n, is_demo)

        # -- CUSUM diagnostic + change-point detection -------------------------
        dev = max_cusum_deviation(returns)
        cusum_max_abs = abs(dev["value"]) if dev["value"] is not None else 0.0

        detection = detect_structural_break(
            returns, min_segment=min_segment, alpha=alpha
        )

        break_detected = detection["break_detected"]
        break_index = detection["break_index"]
        shift_direction = detection["shift_direction"]
        t_stat = detection["t_stat"]
        p_value = detection["p_value"]
        mean_before = detection["mean_before"]
        mean_after = detection["mean_after"]

        # break_date = date of the FIRST bar of the "after" segment (the bar at
        # which the new regime begins). break_index is the last "before" index.
        break_date = None
        if break_index is not None:
            after_start = break_index + 1
            if 0 <= after_start < len(dates):
                break_date = dates[after_start]

        if break_index is None:
            notes.append(
                f"no actionable change-point: candidate fails the "
                f"min_segment={min_segment} guard or series is degenerate"
            )

        # -- Advisory verdict --------------------------------------------------
        if break_detected and shift_direction == "deterioration":
            verdict = "fail"
            verdict_reason = (
                f"structural break detected at index {break_index} "
                f"(p={p_value:.4f} < {alpha}): mean daily return DETERIORATED "
                f"from {mean_before:.4f}% to {mean_after:.4f}% -- the edge "
                f"structurally weakened (red flag)"
            )
        elif break_detected and shift_direction == "improvement":
            verdict = "warn"
            verdict_reason = (
                f"structural break detected at index {break_index} "
                f"(p={p_value:.4f} < {alpha}): mean daily return IMPROVED "
                f"from {mean_before:.4f}% to {mean_after:.4f}% -- the process "
                f"changed; the pre-break track is not representative"
            )
        else:
            verdict = "ok"
            if break_index is None:
                verdict_reason = (
                    "no detectable structural break (no actionable candidate "
                    "under the min_segment guard); mean appears stationary"
                )
            elif p_value is not None:
                verdict_reason = (
                    f"no significant structural break at candidate index "
                    f"{break_index} (p={p_value:.4f} >= {alpha}); mean appears "
                    f"stationary"
                )
            else:
                verdict_reason = (
                    f"no significant structural break at candidate index "
                    f"{break_index} (p undefined); mean appears stationary"
                )

        def _rnd(x: Optional[float], places: int = 6) -> Optional[float]:
            return None if x is None else round(x, places)

        result: Dict[str, Any] = {
            "available": True,
            "is_demo": is_demo,
            "break_detected": break_detected,
            "break_index": break_index,
            "break_date": break_date,
            "n_observations": n,
            "cusum_max_abs": _rnd(cusum_max_abs),
            "mean_before": _rnd(mean_before),
            "mean_after": _rnd(mean_after),
            "shift_direction": shift_direction,
            "t_stat": _rnd(t_stat),
            "p_value": _rnd(p_value),
            "verdict": verdict,
            "verdict_reason": verdict_reason,
            "segment_lengths": detection["segment_lengths"],
            "min_segment": min_segment,
            "alpha": alpha,
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
        log.exception("unexpected error in build_structural_break")
        return _unavailable(f"unexpected error: {exc}",
                            generated_at, notes, None, is_demo)


# ------------------------------------------------------------------------------
# Atomic persistence (content_fingerprint reused by import -- see top of module)
# ------------------------------------------------------------------------------

def write_status(
    result: Dict[str, Any],
    data_dir: str | os.PathLike = _DEFAULT_DATA_DIR,
) -> str:
    """Atomically write structural_break.json.

    Returns ``"DATA_WRITTEN"`` | ``"DATA_UNCHANGED"``. Idempotent by
    :func:`content_fingerprint` (ignores ``meta.generated_at`` / ``history``).
    Rotates ``history`` to <= :data:`HISTORY_MAX`.
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
            f"[structural_break] available=false reason={result.get('reason', '?')}"
        )
        print(f"  verdict       : {result.get('verdict')} -- {result.get('verdict_reason')}")
        for n in result.get("notes", []):
            print(f"  note: {n}")
        return

    print("[structural_break] available=true")
    print(f"  verdict       : {result['verdict']} -- {result['verdict_reason']}")
    print(f"  break_detected: {result['break_detected']}")
    print(f"  break_index   : {result['break_index']}  break_date: {result['break_date']}")
    print(f"  n_obs         : {result['n_observations']}")
    print(f"  cusum_max_abs : {result['cusum_max_abs']}")
    print(f"  mean before/after: {result['mean_before']} / {result['mean_after']} "
          f"({result['shift_direction']})")
    print(f"  t_stat / p    : {result['t_stat']} / {result['p_value']}")
    print(f"  segment_lengths: {result['segment_lengths']}")
    if result.get("is_demo") is not None:
        print(f"  is_demo       : {result['is_demo']}")
    for n in result.get("notes", []):
        print(f"  note: {n}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Structural-Break / Change-Point Detector (MP-138) -- "
                    "read-only / advisory",
        add_help=True,
    )
    parser.add_argument(
        "--check", action="store_true",
        help="compute and print, no write (default)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="compute, print, and atomically write to data/structural_break.json",
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

    result = build_structural_break(data_dir)
    _print_result(result)

    if args.run:
        status = write_status(result, data_dir)
        print(f"[structural_break] write_status={status}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
