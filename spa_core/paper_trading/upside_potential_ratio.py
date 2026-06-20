#!/usr/bin/env python3
"""Upside Potential Ratio (UPR) — Reward-vs-Downside-Risk Analyzer
(SPA-V464 / MP-149) — read-only / advisory.

The performance suite already covers the headline risk-adjusted battery
(``risk_metrics`` — Sharpe/Sortino/Calmar/profit-factor), the second-tier
tearsheet ratios (``advanced_ratios`` — omega/gain-to-pain/tail-ratio/ulcer/
martin/pain), the deflated significance of the Sharpe (``deflated_sharpe``),
the *historical* VaR/CVaR battery (``tail_risk``), the *parametric* Cornish-
Fisher tail risk (``distribution_normality``), the smoothness signature
(``bias_ratio``) and the tail-reward/tail-risk asymmetry (``rachev_ratio``).
But NONE of those modules answers the specific post-modern due-diligence
question that gave rise to the Sortino family of statistics:

    "Relative to a minimum acceptable return, how much UPSIDE POTENTIAL does
     the book generate per unit of DOWNSIDE RISK it takes on? Is the average
     amount by which it BEATS the target large compared to the dispersion of
     the amounts by which it MISSES the target?"

That is the gap MP-149 closes with the **Upside Potential Ratio** (Sortino,
van der Meer & Plantinga, 1999; Sortino & Satchell).

Why the Upside Potential Ratio matters
=======================================
The Sortino ratio in ``risk_metrics`` divides the EXCESS MEAN return by the
downside deviation — its numerator rewards the *average* return (good and bad
days alike, netted) and can be dragged negative by a bad mean. The Upside
Potential Ratio keeps the SAME downside-risk denominator but replaces the
numerator with the **first upper partial moment** — the mean of ONLY the
amounts by which returns *exceed* the minimum acceptable return (MAR). Misses
contribute nothing to the numerator (they are floored at zero), only to the
denominator. The statistic therefore isolates "how much good, per unit of
bad", which is exactly what a post-modern-portfolio-theory allocator wants::

    UP  = mean( max(r - MAR, 0) )           (first UPPER partial moment, order 1)
    DD  = sqrt( mean( min(r - MAR, 0)^2 ) )  (sqrt of 2nd LOWER partial moment)

    Upside Potential Ratio = UP / DD

Both UP and DD are expressed in the SAME return units, so the natural reference
point is **1.0**:
  * ``UPR > 1``  — the average outperformance above the target EXCEEDS the
    magnitude of downside-risk dispersion (favourable reward/risk).
  * ``UPR ~= 1`` — upside potential and downside risk are comparable.
  * ``UPR < 1``  — downside-risk dispersion dominates the upside potential
    (an unfavourable, risk-heavy profile).

For a DeFi yield optimizer, MAR = 0 daily means "any losing day is downside";
a UPR well below 1 warns that the dispersion of the strategy's losing days
outweighs the average size of its winning days — exactly the asymmetry a yield
book that markets itself as "steady carry" should not exhibit.

Reuse (single source of truth)
==============================
The equity series is **reused by import** from
:mod:`spa_core.paper_trading.drawdown_analytics` (``extract_equity_series``);
period returns are then derived by a small pure, hand-verifiable helper
(:func:`period_returns`) — we do NOT re-implement equity parsing. The partial
moments are computed by small pure functions in THIS module so the math is
self-contained and hand-verifiable. :func:`content_fingerprint` is **reused by
import** from :mod:`spa_core.reporting.tear_sheet` (project convention MP-501)
so idempotency is byte-for-byte identical to the rest of the suite.

What this is NOT
================
* NOT the Sortino ratio (that is ``risk_metrics`` — different numerator).
* NOT the Omega ratio (that is ``advanced_ratios.omega`` — a ratio of partial
  moments of the SAME order; UPR mixes order-1 upside with order-2 downside).
* NOT money-moving — STRICTLY READ-ONLY / advisory. It only READS the equity
  track (``data/equity_curve_daily.json``) and writes its OWN derived status
  artifact. It never touches risk / execution / allocator / cycle_runner /
  golive_checker.

Advisory verdict
================
* **fail** — ``upside_potential_ratio < UPR_FAIL`` (downside-risk dispersion
  strongly dominates upside potential).
* **warn** — ``upside_potential_ratio < UPR_WARN`` (upside potential below the
  natural 1.0 reference; mildly unfavourable).
* **ok**  — otherwise, including the degenerate ``DD == 0`` (no downside at all
  -> ratio undefined / infinitely favourable) which is reported with a note,
  never a failure.
A **low-sample guard** caps the verdict at ``warn`` when fewer than
:data:`MIN_SIDE_OBS` returns actually fell on the DOWNSIDE — thin downside
evidence should not raise a hard red flag. ``verdict_reason`` is always present.
Insufficient data (``n < MIN_OBS``) -> ``available:false``, ``verdict:"ok"`` —
the schema stays stable.

Output / persistence
====================
:func:`build_upside_potential_ratio` returns a stable-schema dict and NEVER
raises. :func:`write_status` atomically (``tempfile.mkstemp`` + ``os.replace``)
writes ``data/upside_potential_ratio.json`` with an in-file ``history``
(rotation <= :data:`HISTORY_MAX`). Idempotency via :func:`content_fingerprint`
(REUSED BY IMPORT from :mod:`spa_core.reporting.tear_sheet`, MP-501) over the
doc EXCLUDING the volatile ``meta.generated_at`` / ``history``.

CLI::

    python3 -m spa_core.paper_trading.upside_potential_ratio --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.upside_potential_ratio --run     # + atomic write
    python3 -m spa_core.paper_trading.upside_potential_ratio --run --data-dir <dir>

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

log = logging.getLogger("spa.paper_trading.upside_potential_ratio")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "upside_potential_ratio"
STATUS_FILENAME: str = "upside_potential_ratio.json"
EQUITY_FILENAME: str = "equity_curve_daily.json"
HISTORY_MAX: int = 500

# Minimum Acceptable Return (daily). MAR = 0 means any losing day is downside
# and any winning day is upside — the natural reference for a daily carry book.
MAR: float = 0.0

# Require a comfortable number of *returns*. n returns require n+1 equity points.
MIN_OBS: int = 20

# Advisory thresholds (documented heuristics). UP and DD share the same return
# units, so 1.0 is the natural reference: UPR > 1 means the average
# outperformance exceeds the downside-risk magnitude. UPR_WARN/UPR_FAIL flank
# "below the natural reference" / "downside dispersion strongly dominates".
# These are deliberately conservative; the ratio is advisory context for a
# human, never a gate.
UPR_WARN: float = 1.0
UPR_FAIL: float = 0.5

# Low-sample guard: if fewer than this many returns actually fell on the
# downside, the denominator rests on too little evidence to justify a hard
# "fail"; cap at "warn".
MIN_SIDE_OBS: int = 3

__all__ = [
    "period_returns",
    "upside_potential",
    "downside_deviation",
    "upside_potential_ratio",
    "build_upside_potential_ratio",
    "write_status",
    "main",
    "content_fingerprint",
    "extract_equity_series",
    "MAR",
    "MIN_OBS",
    "MIN_SIDE_OBS",
    "HISTORY_MAX",
    "SOURCE_NAME",
    "STATUS_FILENAME",
    "UPR_WARN",
    "UPR_FAIL",
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


def upside_potential(returns: List[float], mar: float = MAR) -> float:
    """Upside Potential — first UPPER partial moment (order 1) about ``mar``.

        UP = mean( max(r - mar, 0) )    over ALL returns

    The amount by which each return exceeds the minimum acceptable return,
    floored at zero (misses contribute nothing), averaged over EVERY return
    (not only the winning ones). Returns ``0.0`` if there is no upside or the
    input is empty. Pure / never raises.

    Hand example: ``returns=[0.02,-0.01,0.04,-0.03], mar=0`` ->
    max-terms ``[0.02,0,0.04,0]`` -> mean = 0.06 / 4 = 0.015.
    """
    n = len(returns)
    if n == 0:
        return 0.0
    total = 0.0
    for r in returns:
        diff = r - mar
        if diff > 0.0:
            total += diff
    return total / n


def downside_deviation(returns: List[float], mar: float = MAR) -> float:
    """Downside Deviation — sqrt of the 2nd LOWER partial moment about ``mar``.

        DD = sqrt( mean( min(r - mar, 0)^2 ) )    over ALL returns

    The root-mean-square of the amounts by which returns fall *short* of the
    minimum acceptable return, with outperformance floored at zero, averaged
    over EVERY return. Returns ``0.0`` if there is no downside or the input is
    empty. Pure / never raises.

    Hand example: ``returns=[0.02,-0.01,0.04,-0.03], mar=0`` ->
    min-terms ``[0,-0.01,0,-0.03]`` -> squares ``[0,0.0001,0,0.0009]`` ->
    mean = 0.001 / 4 = 0.00025 -> sqrt = 0.0158113883...
    """
    n = len(returns)
    if n == 0:
        return 0.0
    total = 0.0
    for r in returns:
        diff = r - mar
        if diff < 0.0:
            total += diff * diff
    return math.sqrt(total / n)


def upside_potential_ratio(up: Optional[float], dd: Optional[float]) -> Optional[float]:
    """Upside Potential Ratio = ``UP / DD``.

    Returns ``None`` when either input is ``None`` or ``DD <= 0`` (no downside
    risk -> the ratio is undefined / unbounded; the caller reports this as an
    "ok + note" degenerate case rather than dividing). Pure / never raises.

    Hand example: ``UP=0.015, DD=0.0158113883`` -> ~0.9486833.
    """
    if up is None or dd is None:
        return None
    if dd <= 0.0:
        return None
    return up / dd


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
        "upside_potential_ratio": None,
        "upside_potential": None,
        "downside_deviation": None,
        "mar": MAR,
        "count_upside": None,
        "count_downside": None,
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


def build_upside_potential_ratio(
    data_dir: str | os.PathLike = _DEFAULT_DATA_DIR,
) -> Dict[str, Any]:
    """Compute the Upside Potential Ratio over the equity track. Never raises.

    Loads ``equity_curve_daily.json``, extracts the equity series (REUSED from
    drawdown_analytics), derives period returns, the upside potential / downside
    deviation about MAR and their ratio. Returns a stable-schema dict.
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

        mean_ret = statistics.fmean(returns)
        start_date = series[0][0]
        end_date = series[-1][0]

        up = upside_potential(returns, MAR)
        dd = downside_deviation(returns, MAR)
        count_upside = sum(1 for r in returns if (r - MAR) > 0.0)
        count_downside = sum(1 for r in returns if (r - MAR) < 0.0)

        # -- Degenerate: no downside at all -> ratio undefined -----------------
        # DD <= 0 means no return fell below MAR (a track with no losing days
        # relative to the target). The ratio is unbounded/undefined; report
        # ok + note rather than dividing.
        if dd <= 0.0:
            notes.append(
                "Upside Potential Ratio undefined (no downside observations)"
            )
            result_zero: Dict[str, Any] = {
                "available": True,
                "is_demo": is_demo,
                "upside_potential_ratio": None,
                "upside_potential": round(up, 8),
                "downside_deviation": round(dd, 8),
                "mar": MAR,
                "count_upside": count_upside,
                "count_downside": count_downside,
                "count_returns": n,
                "mean_return": round(mean_ret, 8),
                "n_observations": n,
                "start_date": start_date,
                "end_date": end_date,
                "verdict": "ok",
                "verdict_reason": (
                    "no downside observations (no return fell below MAR "
                    f"{MAR}) -- the Upside Potential Ratio is undefined; "
                    "there is no downside risk to compare against"
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

        upr = upside_potential_ratio(up, dd)
        # upr is not None here (dd > 0 guaranteed above), but guard defensively.
        if upr is None:
            return _unavailable(
                "upside potential ratio undefined (degenerate downside)",
                generated_at, notes, n, is_demo,
            )

        # -- Advisory verdict --------------------------------------------------
        if upr < UPR_FAIL:
            verdict = "fail"
        elif upr < UPR_WARN:
            verdict = "warn"
        else:
            verdict = "ok"

        # Low-sample guard: thin downside evidence must not raise a hard fail.
        capped = False
        if verdict == "fail" and count_downside < MIN_SIDE_OBS:
            verdict = "warn"
            capped = True
            notes.append(
                f"low-sample guard: only {count_downside} downside "
                f"observation(s) (< {MIN_SIDE_OBS}); verdict capped at 'warn'"
            )

        # verdict_reason (always present, descriptive).
        if verdict == "fail":
            verdict_reason = (
                f"Upside Potential Ratio {upr:.4f} < {UPR_FAIL} -- downside-risk "
                f"dispersion dominates upside potential (UP {up:.6f} vs DD "
                f"{dd:.6f} about MAR {MAR}); risk-heavy profile"
            )
        elif verdict == "warn":
            if capped:
                verdict_reason = (
                    f"Upside Potential Ratio {upr:.4f} < {UPR_FAIL} but capped "
                    f"to 'warn' by the low-sample guard ({count_downside} "
                    f"downside obs < {MIN_SIDE_OBS}); treat as weak evidence"
                )
            else:
                verdict_reason = (
                    f"Upside Potential Ratio {upr:.4f} < {UPR_WARN} -- upside "
                    f"potential below the natural 1.0 reference (UP {up:.6f} vs "
                    f"DD {dd:.6f}); downside dispersion bites a little harder"
                )
        else:  # ok
            verdict_reason = (
                f"Upside Potential Ratio {upr:.4f} >= {UPR_WARN} -- the average "
                f"outperformance above MAR (UP {up:.6f}) holds up against the "
                f"downside-risk dispersion (DD {dd:.6f}); reward/risk is "
                f"acceptable"
            )

        result: Dict[str, Any] = {
            "available": True,
            "is_demo": is_demo,
            "upside_potential_ratio": round(upr, 6),
            "upside_potential": round(up, 8),
            "downside_deviation": round(dd, 8),
            "mar": MAR,
            "count_upside": count_upside,
            "count_downside": count_downside,
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
        log.exception("unexpected error in build_upside_potential_ratio")
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
    """Atomically write upside_potential_ratio.json.

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
            f"[upside_potential_ratio] available=false reason={result.get('reason', '?')}"
        )
        print(f"  verdict       : {result.get('verdict')} -- {result.get('verdict_reason')}")
        for n in result.get("notes", []):
            print(f"  note: {n}")
        return

    print("[upside_potential_ratio] available=true")
    print(f"  verdict       : {result['verdict']} -- {result['verdict_reason']}")
    print(f"  upr           : {result['upside_potential_ratio']}")
    print(f"  UP / DD       : {result['upside_potential']} / {result['downside_deviation']}")
    print(f"  mar           : {result['mar']}")
    print(f"  count +/-     : {result['count_upside']} / {result['count_downside']}")
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
        description="Upside Potential Ratio -- Reward-vs-Downside-Risk "
                    "Analyzer (MP-149) -- read-only / advisory",
        add_help=True,
    )
    parser.add_argument(
        "--check", action="store_true",
        help="compute and print, no write (default)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="compute, print, and atomically write to "
             "data/upside_potential_ratio.json",
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

    result = build_upside_potential_ratio(data_dir)
    _print_result(result)

    if args.run:
        status = write_status(result, data_dir)
        print(f"[upside_potential_ratio] write_status={status}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
