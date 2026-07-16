#!/usr/bin/env python3
"""Bias Ratio — Return-Smoothing / Mark-Manipulation Detector (SPA-V462 /
MP-147) — read-only / advisory.

The performance suite already measures the *magnitude* and *shape* of risk
(drawdown_analytics, ulcer_index, tail_risk), the *normality* of the return
distribution (distribution_normality) and *serial structure* (serial_dependence
-- autocorrelation, runs, variance-ratio, Hurst). But NONE of those modules
answers a distinct due-diligence question that every allocator asks of an
illiquid / mark-to-model strategy:

    "Do these returns look TOO SMOOTH to be true -- are small losses being
     suppressed or marks being managed?"

That is the gap MP-147 closes with the **Bias Ratio** (Adil Abdulali, 2006).

Why the Bias Ratio matters
==========================
A manager who marks illiquid positions to model -- or who simply smooths
reported returns -- tends to *avoid printing small negative numbers*: a tiny
loss is rounded up to a tiny gain, or deferred. Over many periods this leaves a
tell-tale asymmetry in the cluster of returns *near zero*: an over-supply of
small positive returns and a deficit of small negative ones. The Bias Ratio
quantifies exactly that asymmetry. Let ``s`` be the sample standard deviation
of the return series. Define::

    L = #{ returns r with   0 <= r <= +s }      (small NON-NEGATIVE)
    m = #{ returns r with  -s <= r <  0  }       (small NEGATIVE)

    Bias Ratio = L / (1 + m)

For an honestly-priced, liquid strategy small gains and small losses occur in
roughly equal numbers, so ``BR ~= 1``. For smoothed / mark-managed returns the
small losses vanish (``m`` shrinks) while small gains pile up just above zero
(``L`` grows), driving ``BR`` well above 1. Empirically liquid equity indices
score ~1; illiquid credit / real-estate vehicles score 2-3; the Madoff track
scored ~6-7. A high Bias Ratio is therefore a classic red flag that the track's
returns are not arm's-length-priced.

For a DeFi yield optimizer the analogue is direct: positions in thin pools, or
APY marks taken from a model rather than realisable exit prices, can produce an
unnaturally smooth equity track. The Bias Ratio flags when the paper track
looks "too good to be honestly marked".

Reuse (single source of truth)
==============================
The equity series is **reused by import** from
:mod:`spa_core.paper_trading.drawdown_analytics` (``extract_equity_series``);
period returns are then derived by a small pure, hand-verifiable helper
(:func:`period_returns`) -- we do NOT re-implement equity parsing.
:func:`content_fingerprint` is **reused by import** from
:mod:`spa_core.reporting.tear_sheet` (project convention MP-501) so idempotency
is byte-for-byte identical to the rest of the suite.

What this is NOT
================
* NOT a normality test (that is distribution_normality).
* NOT an autocorrelation / serial-structure test (that is serial_dependence).
* NOT money-moving -- STRICTLY READ-ONLY / advisory. It only READS the equity
  track (``data/equity_curve_daily.json``) and writes its OWN derived status
  artifact. It never touches risk / execution / allocator / cycle_runner /
  golive_checker.

Advisory verdict
================
* **fail** -- ``bias_ratio > BIAS_FAIL`` (strong smoothing signature; small
  losses are conspicuously absent relative to small gains).
* **warn** -- ``bias_ratio > BIAS_WARN`` (mild asymmetry near zero).
* **ok** -- otherwise, including the degenerate ``s == 0`` (no dispersion ->
  Bias Ratio undefined) which is reported with a note, never a failure.
A **low-sample guard** caps the verdict at ``warn`` when too few returns fall in
the small-band ``[-s, +s]`` for the ratio to be trustworthy -- thin evidence
should not raise a hard red flag. ``verdict_reason`` is always present.
Insufficient data (``n < MIN_OBS``) -> ``available:false``, ``verdict:"ok"`` --
the schema stays stable.

Output / persistence
====================
:func:`build_bias_ratio` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (``tempfile.mkstemp`` + ``os.replace``) writes
``data/bias_ratio.json`` with an in-file ``history`` (rotation <=
:data:`HISTORY_MAX`). Idempotency via :func:`content_fingerprint` (REUSED BY
IMPORT from :mod:`spa_core.reporting.tear_sheet`, MP-501) over the doc EXCLUDING
the volatile ``meta.generated_at`` / ``history``.

CLI::

    python3 -m spa_core.analytics_lab.bias_ratio --check   # compute+print, no write (default)
    python3 -m spa_core.analytics_lab.bias_ratio --run     # + atomic write
    python3 -m spa_core.analytics_lab.bias_ratio --run --data-dir <dir>

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# -- Equity series REUSED BY IMPORT (single source of truth, drawdown_analytics
# MP-115). We do NOT re-implement equity parsing here. -----------------------
from spa_core.paper_trading.drawdown_analytics import extract_equity_series

# -- content_fingerprint REUSED BY IMPORT (project convention, MP-501) --------
from spa_core.reporting.tear_sheet import content_fingerprint
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.analytics_lab.bias_ratio")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "bias_ratio"
STATUS_FILENAME: str = "bias_ratio.json"
EQUITY_FILENAME: str = "equity_curve_daily.json"
HISTORY_MAX: int = 500

# Require a comfortable number of *returns* for a meaningful standard deviation
# and near-zero band count. n returns require n+1 equity points.
MIN_OBS: int = 12

# Advisory thresholds (documented heuristics). For an honestly-priced liquid
# strategy the Bias Ratio is ~1. BIAS_WARN/BIAS_FAIL flank "mild near-zero
# asymmetry" / "strong smoothing signature". These are deliberately
# conservative; the ratio is advisory context for a human, never a gate.
BIAS_WARN: float = 2.0
BIAS_FAIL: float = 3.0

# Low-sample guard: if fewer than this many returns land in the small band
# [-s, +s], the ratio rests on too little evidence to justify a hard "fail";
# the verdict is capped at "warn".
MIN_BAND_OBS: int = 6

__all__ = [
    "period_returns",
    "sample_std",
    "band_counts",
    "bias_ratio",
    "build_bias_ratio",
    "write_status",
    "main",
    "content_fingerprint",
    "extract_equity_series",
    "MIN_OBS",
    "MIN_BAND_OBS",
    "HISTORY_MAX",
    "SOURCE_NAME",
    "STATUS_FILENAME",
    "BIAS_WARN",
    "BIAS_FAIL",
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

    Hand example: ``[("d0",100),("d1",110),("d2",99)]`` ->
    ``[0.10, -0.10]``.
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


def sample_std(values: List[float]) -> Optional[float]:
    """Sample standard deviation (n-1 denominator, Bessel-corrected).

    Returns ``None`` for fewer than 2 values. A series of identical values
    yields exactly ``0.0``. Pure / never raises.

    Hand example: ``[1, 2, 3, 4, 5]`` -> variance 2.5 -> std ~= 1.5811388.
    """
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    ss = 0.0
    for v in values:
        d = v - mean
        ss += d * d
    var = ss / (n - 1)
    if var < 0:  # numerical guard; cannot normally happen
        var = 0.0
    return math.sqrt(var)


def band_counts(returns: List[float], s: float) -> Tuple[int, int]:
    """Count returns in the two small near-zero half-bands.

    Returns ``(small_positive, small_negative)`` where::

        small_positive = #{ r :  0 <= r <= +s }
        small_negative = #{ r : -s <= r <  0  }

    Zero is counted as a (non-negative) small positive, matching Abdulali's
    convention. ``s`` is assumed ``>= 0``; if ``s == 0`` only exact zeros fall
    in the positive band. Pure / never raises.
    """
    pos = 0
    neg = 0
    for r in returns:
        if 0.0 <= r <= s:
            pos += 1
        elif -s <= r < 0.0:
            neg += 1
    return pos, neg


def bias_ratio(small_positive: int, small_negative: int) -> float:
    """Bias Ratio = ``small_positive / (1 + small_negative)``.

    The ``1 +`` in the denominator keeps the ratio finite when there are no
    small negative returns (the very case smoothing produces). With equal small
    gains and losses the ratio approaches 1. Pure / never raises.

    Hand example: ``L=8, m=1`` -> 8 / 2 = 4.0.
    """
    return float(small_positive) / (1.0 + float(small_negative))


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
        "bias_ratio": None,
        "std_returns": None,
        "count_small_positive": None,
        "count_small_negative": None,
        "count_returns": None,
        "mean_return": None,
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


def build_bias_ratio(
    data_dir: str | os.PathLike = _DEFAULT_DATA_DIR,
) -> Dict[str, Any]:
    """Compute the Bias Ratio over the equity track. Never raises.

    Loads ``equity_curve_daily.json``, extracts the equity series (REUSED from
    drawdown_analytics), derives period returns, the sample standard deviation,
    the near-zero band counts and the Bias Ratio. Returns a stable-schema dict.
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
        returns = period_returns(series)
        n = len(returns)
        if n < MIN_OBS:
            return _unavailable(
                f"only {n} daily returns (< {MIN_OBS} required)",
                generated_at, notes, n, is_demo,
            )

        s = sample_std(returns)
        mean_ret = sum(returns) / n
        start_date = series[0][0]
        end_date = series[-1][0]

        # -- Degenerate: zero dispersion -> Bias Ratio undefined ---------------
        if s is None or s == 0:
            notes.append(
                "zero return dispersion (std = 0); Bias Ratio undefined -- "
                "every period return is identical"
            )
            result_zero: Dict[str, Any] = {
                "available": True,
                "is_demo": is_demo,
                "bias_ratio": None,
                "std_returns": 0.0 if s == 0 else None,
                "count_small_positive": None,
                "count_small_negative": None,
                "count_returns": n,
                "mean_return": round(mean_ret, 8),
                "n_observations": n,
                "start_date": start_date,
                "end_date": end_date,
                "verdict": "ok",
                "verdict_reason": (
                    "zero return dispersion (std = 0) -- the Bias Ratio is "
                    "undefined; no near-zero asymmetry can be measured"
                ),
                "notes": notes,
                "meta": {
                    "generated_at": generated_at,
                    "schema_version": SCHEMA_VERSION,
                    "source": SOURCE_NAME,
                    "min_obs_required": MIN_OBS,
                },
            }
            return result_zero

        pos, neg = band_counts(returns, s)
        br = bias_ratio(pos, neg)
        band_total = pos + neg

        # -- Advisory verdict --------------------------------------------------
        if br > BIAS_FAIL:
            verdict = "fail"
        elif br > BIAS_WARN:
            verdict = "warn"
        else:
            verdict = "ok"

        # Low-sample guard: thin near-zero evidence must not raise a hard fail.
        capped = False
        if verdict == "fail" and band_total < MIN_BAND_OBS:
            verdict = "warn"
            capped = True
            notes.append(
                f"low-sample guard: only {band_total} returns in the small "
                f"band [-s, +s] (< {MIN_BAND_OBS}); verdict capped at 'warn'"
            )

        # verdict_reason (always present, descriptive).
        if verdict == "fail":
            verdict_reason = (
                f"Bias Ratio {br:.4f} > {BIAS_FAIL} -- strong return-smoothing "
                f"signature: {pos} small gains vs {neg} small losses in "
                f"[-{s:.6f}, +{s:.6f}]; small losses are conspicuously absent"
            )
        elif verdict == "warn":
            if capped:
                verdict_reason = (
                    f"Bias Ratio {br:.4f} > {BIAS_FAIL} but capped to 'warn' "
                    f"by the low-sample guard ({band_total} near-zero "
                    f"returns < {MIN_BAND_OBS}); treat as weak evidence"
                )
            else:
                verdict_reason = (
                    f"Bias Ratio {br:.4f} > {BIAS_WARN} -- mild near-zero "
                    f"asymmetry ({pos} small gains vs {neg} small losses); "
                    f"some smoothing possible"
                )
        else:  # ok
            verdict_reason = (
                f"Bias Ratio {br:.4f} <= {BIAS_WARN} -- small gains ({pos}) "
                f"and small losses ({neg}) are roughly balanced near zero; no "
                f"smoothing signature"
            )

        result: Dict[str, Any] = {
            "available": True,
            "is_demo": is_demo,
            "bias_ratio": round(br, 6),
            "std_returns": round(s, 8),
            "count_small_positive": pos,
            "count_small_negative": neg,
            "count_returns": n,
            "mean_return": round(mean_ret, 8),
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
        log.exception("unexpected error in build_bias_ratio")
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
    """Atomically write bias_ratio.json.

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
            f"[bias_ratio] available=false reason={result.get('reason', '?')}"
        )
        print(f"  verdict       : {result.get('verdict')} -- {result.get('verdict_reason')}")
        for n in result.get("notes", []):
            print(f"  note: {n}")
        return

    print("[bias_ratio] available=true")
    print(f"  verdict       : {result['verdict']} -- {result['verdict_reason']}")
    print(f"  bias_ratio    : {result['bias_ratio']}")
    print(f"  std_returns   : {result['std_returns']}")
    print(f"  small +/-     : {result['count_small_positive']} / {result['count_small_negative']}")
    print(f"  count_returns : {result['count_returns']}")
    print(f"  mean_return   : {result['mean_return']}")
    print(f"  n_obs         : {result['n_observations']}")
    print(f"  start / end   : {result['start_date']} / {result['end_date']}")
    if result.get("is_demo") is not None:
        print(f"  is_demo       : {result['is_demo']}")
    for n in result.get("notes", []):
        print(f"  note: {n}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bias Ratio -- Return-Smoothing / Mark-Manipulation "
                    "Detector (MP-147) -- read-only / advisory",
        add_help=True,
    )
    parser.add_argument(
        "--check", action="store_true",
        help="compute and print, no write (default)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="compute, print, and atomically write to data/bias_ratio.json",
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

    result = build_bias_ratio(data_dir)
    _print_result(result)

    if args.run:
        status = write_status(result, data_dir)
        print(f"[bias_ratio] write_status={status}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
