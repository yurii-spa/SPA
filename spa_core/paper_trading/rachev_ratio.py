#!/usr/bin/env python3
"""Rachev Ratio — Tail-Reward / Tail-Risk Analyzer (SPA-V463 / MP-148) —
read-only / advisory.

The performance suite already covers the headline risk-adjusted battery
(``risk_metrics`` — Sharpe/Sortino/Calmar/profit-factor), the second-tier
tearsheet ratios (``advanced_ratios`` — omega/gain-to-pain/tail-ratio/ulcer/
martin/pain), the deflated significance of the Sharpe (``deflated_sharpe``),
the *historical* VaR/CVaR battery (``tail_risk``), the *parametric* Cornish-
Fisher tail risk (``distribution_normality``) and the smoothness signature
(``bias_ratio``). But NONE of those modules answers one specific
post-modern due-diligence question an allocator asks of a fat-tailed track:

    "When the book has a great day vs a terrible day, how does the AVERAGE
     extreme GAIN compare to the AVERAGE extreme LOSS? Is the right tail paying
     me enough to compensate for the left tail?"

That is the gap MP-148 closes with the **Rachev Ratio** (Biglova, Ortobelli,
Rachev & Stoyanov, 2004).

Why the Rachev Ratio matters
============================
Sharpe penalises ALL volatility (including upside); Sortino penalises only
downside *dispersion*; the ``tail_ratio`` in ``advanced_ratios`` compares the
95th vs 5th return *percentiles* (single points). The Rachev Ratio instead
compares the **Expected Tail Gain (ETG)** — the mean of the best ``alpha``
fraction of returns — against the **Expected Tail Loss (ETL)** — the mean
(magnitude) of the worst ``beta`` fraction of returns. It is the ratio of two
*conditional tail expectations*, i.e. it is built from CVaR-style averages of
WHOLE tails, not single quantiles::

    ETG = mean( best  alpha-fraction of returns )          (a reward, signed +)
    ETL = -mean( worst beta-fraction of returns )          (a loss magnitude, +)

    Rachev Ratio = ETG / ETL

Interpretation:
  * ``RR > 1``  — the average extreme gain exceeds the average extreme loss;
    the right tail rewards more than the left tail punishes (favourable
    asymmetry).
  * ``RR ~= 1`` — roughly symmetric tails.
  * ``RR < 1``  — the average extreme loss dominates the average extreme gain;
    crash risk outweighs upside (an unfavourable, left-tail-heavy profile).

For a DeFi yield optimizer the left tail is depeg / exploit / liquidity-cliff
days and the right tail is reward-spike days; a Rachev Ratio well below 1 warns
that the strategy's worst days bite harder than its best days reward — exactly
the asymmetry a yield book should avoid.

Reuse (single source of truth)
==============================
The equity series is **reused by import** from
:mod:`spa_core.paper_trading.drawdown_analytics` (``extract_equity_series``);
period returns are then derived by a small pure, hand-verifiable helper
(:func:`period_returns`) — we do NOT re-implement equity parsing. The tail
expectations are computed by small pure functions in THIS module (mirroring the
``ceil(n * frac)`` whole-tail convention of ``tail_risk.compute_cvar``) so the
math is self-contained and hand-verifiable for BOTH tails (``tail_risk`` only
exposes the left tail). :func:`content_fingerprint` is **reused by import** from
:mod:`spa_core.reporting.tear_sheet` (project convention MP-501) so idempotency
is byte-for-byte identical to the rest of the suite.

What this is NOT
================
* NOT a historical VaR/CVaR report (that is ``tail_risk``).
* NOT a percentile tail-ratio (that is ``advanced_ratios.tail_ratio``).
* NOT money-moving — STRICTLY READ-ONLY / advisory. It only READS the equity
  track (``data/equity_curve_daily.json``) and writes its OWN derived status
  artifact. It never touches risk / execution / allocator / cycle_runner /
  golive_checker.

Advisory verdict
================
* **fail** — ``rachev_ratio < RACHEV_FAIL`` (extreme losses strongly dominate
  extreme gains; left-tail-heavy profile).
* **warn** — ``rachev_ratio < RACHEV_WARN`` (mildly unfavourable tail
  asymmetry).
* **ok**  — otherwise, including the degenerate ``ETL == 0`` (no losing tail ->
  Rachev Ratio undefined / infinitely favourable) which is reported with a note,
  never a failure.
A **low-sample guard** caps the verdict at ``warn`` when either tail rests on
fewer than :data:`MIN_TAIL_OBS` observations — thin tail evidence should not
raise a hard red flag. ``verdict_reason`` is always present. Insufficient data
(``n < MIN_OBS``) -> ``available:false``, ``verdict:"ok"`` — the schema stays
stable.

Output / persistence
====================
:func:`build_rachev_ratio` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (``tempfile.mkstemp`` + ``os.replace``) writes
``data/rachev_ratio.json`` with an in-file ``history`` (rotation <=
:data:`HISTORY_MAX`). Idempotency via :func:`content_fingerprint` (REUSED BY
IMPORT from :mod:`spa_core.reporting.tear_sheet`, MP-501) over the doc EXCLUDING
the volatile ``meta.generated_at`` / ``history``.

CLI::

    python3 -m spa_core.paper_trading.rachev_ratio --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.rachev_ratio --run     # + atomic write
    python3 -m spa_core.paper_trading.rachev_ratio --run --data-dir <dir>

Scope / safety: pure stdlib
(json/math/datetime/pathlib/logging/argparse/os/sys/tempfile) — no
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
# MP-115). We do NOT re-implement equity parsing here. -----------------------
from spa_core.paper_trading.drawdown_analytics import extract_equity_series

# -- content_fingerprint REUSED BY IMPORT (project convention, MP-501) --------
from spa_core.reporting.tear_sheet import content_fingerprint

log = logging.getLogger("spa.paper_trading.rachev_ratio")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "rachev_ratio"
STATUS_FILENAME: str = "rachev_ratio.json"
EQUITY_FILENAME: str = "equity_curve_daily.json"
HISTORY_MAX: int = 500

# Tail fractions (both tails). 0.05 = the best/worst 5% of return days. With the
# ceil(n*frac) whole-tail convention this is at least 1 observation per tail.
ALPHA: float = 0.05  # right tail (gains)
BETA: float = 0.05   # left tail (losses)

# Require a comfortable number of *returns* so each 5% tail holds a couple of
# observations. n returns require n+1 equity points.
MIN_OBS: int = 20

# Advisory thresholds (documented heuristics). RR ~= 1 for symmetric tails.
# RACHEV_WARN/RACHEV_FAIL flank "mildly unfavourable" / "left-tail dominates".
# These are deliberately conservative; the ratio is advisory context for a
# human, never a gate.
RACHEV_WARN: float = 0.90
RACHEV_FAIL: float = 0.60

# Low-sample guard: if either tail holds fewer than this many observations the
# ratio rests on too little evidence to justify a hard "fail"; cap at "warn".
MIN_TAIL_OBS: int = 2

__all__ = [
    "period_returns",
    "tail_cutoff",
    "expected_tail_gain",
    "expected_tail_loss",
    "rachev_ratio",
    "build_rachev_ratio",
    "write_status",
    "main",
    "content_fingerprint",
    "extract_equity_series",
    "ALPHA",
    "BETA",
    "MIN_OBS",
    "MIN_TAIL_OBS",
    "HISTORY_MAX",
    "SOURCE_NAME",
    "STATUS_FILENAME",
    "RACHEV_WARN",
    "RACHEV_FAIL",
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


def tail_cutoff(n: int, frac: float) -> int:
    """Number of observations in a ``frac`` tail of ``n`` items.

        cutoff = max(1, ceil(n * frac))    for n >= 1

    Mirrors the whole-tail convention of ``tail_risk.compute_cvar`` (at least
    one observation). ``n <= 0`` -> 0. ``frac`` is clamped to ``[0, 1]``. Pure /
    never raises.

    Hand example: ``n=10, frac=0.2`` -> ceil(2.0) = 2; ``n=10, frac=0.05`` ->
    max(1, ceil(0.5)) = 1.
    """
    if n <= 0:
        return 0
    if frac <= 0.0:
        return 1
    if frac > 1.0:
        frac = 1.0
    return max(1, math.ceil(n * frac))


def expected_tail_gain(returns: List[float], alpha: float = ALPHA) -> Optional[float]:
    """Expected Tail Gain — mean of the best ``alpha`` fraction of returns.

    Sorts ascending and averages the top ``cutoff = max(1, ceil(n*alpha))``
    returns. This is a signed reward (positive if the best days are positive,
    but it can be negative for an all-losing series). Returns ``None`` for empty
    input. Pure / never raises.

    Hand example: ``returns=[-3,-2,-1,0,1,2,3,4,5,6], alpha=0.2`` -> cutoff 2 ->
    mean(best two = 5,6) = 5.5.
    """
    n = len(returns)
    if n == 0:
        return None
    cut = tail_cutoff(n, alpha)
    ordered = sorted(returns)
    top = ordered[n - cut:]  # ascending sort -> best (largest) at the end
    return sum(top) / len(top)


def expected_tail_loss(returns: List[float], beta: float = BETA) -> Optional[float]:
    """Expected Tail Loss — magnitude of the mean of the worst ``beta`` fraction.

    Sorts ascending and averages the bottom ``cutoff = max(1, ceil(n*beta))``
    returns, then returns the **negated** mean so a genuine losing tail yields a
    POSITIVE loss magnitude (consistent with the ``ETG / ETL`` ratio
    convention). If the worst tail is itself positive (an all-winning series)
    the returned value is negative — handled explicitly by the caller. Returns
    ``None`` for empty input. Pure / never raises.

    Hand example: ``returns=[-3,-2,-1,0,1,2,3,4,5,6], beta=0.2`` -> cutoff 2 ->
    mean(worst two = -3,-2) = -2.5 -> ETL = 2.5.
    """
    n = len(returns)
    if n == 0:
        return None
    cut = tail_cutoff(n, beta)
    ordered = sorted(returns)
    bottom = ordered[:cut]  # ascending sort -> worst (most negative) first
    return -(sum(bottom) / len(bottom))


def rachev_ratio(etg: Optional[float], etl: Optional[float]) -> Optional[float]:
    """Rachev Ratio = ``ETG / ETL``.

    Returns ``None`` when either input is ``None`` or ``ETL <= 0`` (no losing
    tail -> the ratio is undefined / unbounded; the caller reports this as an
    "ok + note" degenerate case rather than dividing). Pure / never raises.

    Hand example: ``ETG=5.5, ETL=2.5`` -> 2.2.
    """
    if etg is None or etl is None:
        return None
    if etl <= 0.0:
        return None
    return etg / etl


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
        "rachev_ratio": None,
        "expected_tail_gain": None,
        "expected_tail_loss": None,
        "alpha": ALPHA,
        "beta": BETA,
        "tail_obs_gain": None,
        "tail_obs_loss": None,
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


def build_rachev_ratio(
    data_dir: str | os.PathLike = _DEFAULT_DATA_DIR,
) -> Dict[str, Any]:
    """Compute the Rachev Ratio over the equity track. Never raises.

    Loads ``equity_curve_daily.json``, extracts the equity series (REUSED from
    drawdown_analytics), derives period returns, the Expected Tail Gain / Loss
    and their ratio. Returns a stable-schema dict.
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

        mean_ret = sum(returns) / n
        start_date = series[0][0]
        end_date = series[-1][0]

        etg = expected_tail_gain(returns, ALPHA)
        etl = expected_tail_loss(returns, BETA)
        tail_obs_gain = tail_cutoff(n, ALPHA)
        tail_obs_loss = tail_cutoff(n, BETA)

        # -- Degenerate: no losing tail -> ratio undefined ---------------------
        # ETL <= 0 means even the worst beta-fraction is non-negative (an
        # all-winning tail). The ratio is unbounded/undefined; report ok + note.
        if etl is None or etl <= 0.0:
            notes.append(
                "no losing tail (worst-tail mean is non-negative); Rachev "
                "Ratio undefined / unbounded -- extreme losses do not dominate"
            )
            result_zero: Dict[str, Any] = {
                "available": True,
                "is_demo": is_demo,
                "rachev_ratio": None,
                "expected_tail_gain": round(etg, 8) if etg is not None else None,
                "expected_tail_loss": round(etl, 8) if etl is not None else None,
                "alpha": ALPHA,
                "beta": BETA,
                "tail_obs_gain": tail_obs_gain,
                "tail_obs_loss": tail_obs_loss,
                "count_returns": n,
                "mean_return": round(mean_ret, 8),
                "n_observations": n,
                "start_date": start_date,
                "end_date": end_date,
                "verdict": "ok",
                "verdict_reason": (
                    "no losing tail (worst-tail mean >= 0) -- the Rachev Ratio "
                    "is undefined; the left tail does not dominate the right"
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

        rr = rachev_ratio(etg, etl)
        # rr is not None here (etl > 0 guaranteed above), but guard defensively.
        if rr is None:
            return _unavailable(
                "rachev ratio undefined (degenerate tails)",
                generated_at, notes, n, is_demo,
            )

        # -- Advisory verdict --------------------------------------------------
        if rr < RACHEV_FAIL:
            verdict = "fail"
        elif rr < RACHEV_WARN:
            verdict = "warn"
        else:
            verdict = "ok"

        # Low-sample guard: thin tail evidence must not raise a hard fail.
        capped = False
        min_tail = min(tail_obs_gain, tail_obs_loss)
        if verdict == "fail" and min_tail < MIN_TAIL_OBS:
            verdict = "warn"
            capped = True
            notes.append(
                f"low-sample guard: smallest tail has only {min_tail} "
                f"observation(s) (< {MIN_TAIL_OBS}); verdict capped at 'warn'"
            )

        # verdict_reason (always present, descriptive).
        if verdict == "fail":
            verdict_reason = (
                f"Rachev Ratio {rr:.4f} < {RACHEV_FAIL} -- extreme losses "
                f"dominate extreme gains (ETG {etg:.6f} vs ETL {etl:.6f} over "
                f"the {int(ALPHA * 100)}% tails); left-tail-heavy profile"
            )
        elif verdict == "warn":
            if capped:
                verdict_reason = (
                    f"Rachev Ratio {rr:.4f} < {RACHEV_FAIL} but capped to "
                    f"'warn' by the low-sample guard (smallest tail "
                    f"{min_tail} obs < {MIN_TAIL_OBS}); treat as weak evidence"
                )
            else:
                verdict_reason = (
                    f"Rachev Ratio {rr:.4f} < {RACHEV_WARN} -- mildly "
                    f"unfavourable tail asymmetry (ETG {etg:.6f} vs ETL "
                    f"{etl:.6f}); the left tail bites a little harder"
                )
        else:  # ok
            verdict_reason = (
                f"Rachev Ratio {rr:.4f} >= {RACHEV_WARN} -- the average extreme "
                f"gain (ETG {etg:.6f}) holds up against the average extreme "
                f"loss (ETL {etl:.6f}); tail reward/risk is acceptable"
            )

        result: Dict[str, Any] = {
            "available": True,
            "is_demo": is_demo,
            "rachev_ratio": round(rr, 6),
            "expected_tail_gain": round(etg, 8),
            "expected_tail_loss": round(etl, 8),
            "alpha": ALPHA,
            "beta": BETA,
            "tail_obs_gain": tail_obs_gain,
            "tail_obs_loss": tail_obs_loss,
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
        log.exception("unexpected error in build_rachev_ratio")
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
    """Atomically write rachev_ratio.json.

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

    fd, tmp_path = tempfile.mkstemp(dir=data_dir, prefix=".tmp_rachev_ratio_")
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
            f"[rachev_ratio] available=false reason={result.get('reason', '?')}"
        )
        print(f"  verdict       : {result.get('verdict')} -- {result.get('verdict_reason')}")
        for n in result.get("notes", []):
            print(f"  note: {n}")
        return

    print("[rachev_ratio] available=true")
    print(f"  verdict       : {result['verdict']} -- {result['verdict_reason']}")
    print(f"  rachev_ratio  : {result['rachev_ratio']}")
    print(f"  ETG / ETL     : {result['expected_tail_gain']} / {result['expected_tail_loss']}")
    print(f"  alpha / beta  : {result['alpha']} / {result['beta']}")
    print(f"  tail obs +/-  : {result['tail_obs_gain']} / {result['tail_obs_loss']}")
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
        description="Rachev Ratio -- Tail-Reward / Tail-Risk Analyzer "
                    "(MP-148) -- read-only / advisory",
        add_help=True,
    )
    parser.add_argument(
        "--check", action="store_true",
        help="compute and print, no write (default)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="compute, print, and atomically write to data/rachev_ratio.json",
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

    result = build_rachev_ratio(data_dir)
    _print_result(result)

    if args.run:
        status = write_status(result, data_dir)
        print(f"[rachev_ratio] write_status={status}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
