#!/usr/bin/env python3
"""Ulcer Index & Martin Ratio Analyzer (SPA-V461 / MP-146) — read-only /
advisory.

The drawdown cluster (drawdown_analytics MP-115, conditional_drawdown,
drawdown_attribution MP-127) decomposes the realised equity track into
*episodes*, the *underwater curve*, conditional drawdown-at-risk (CDaR) and
per-source attribution -- but NONE of them computes the **Ulcer Index** or the
**Martin Ratio**. That is the gap MP-146 closes.

Why the Ulcer Index matters
===========================
Max drawdown is a single worst-case *point* -- it says nothing about how often
or how long the strategy sat underwater. The Sharpe ratio penalises *upside*
volatility just as hard as downside, which mis-states the lived experience of
holding a strategy. The **Ulcer Index** (Peter Martin, 1987) is the
root-mean-square of the underwater % series::

    UI = sqrt( mean( d_k**2 ) )      with each d_k <= 0  (drawdown % from peak)

Because every underwater observation is squared and averaged, the UI uniquely
penalises BOTH the *depth* AND the *duration* of drawdowns: a deep-but-brief
dip and a shallow-but-endless slog can score the same UI, exactly mirroring
"investor pain". The companion **Martin Ratio** (a.k.a. Ulcer Performance
Index) is the pain-adjusted return::

    Martin = annualized_return_pct / UI

-- the natural Sharpe analogue when the relevant risk is drawdown pain rather
than two-sided volatility.

Reuse (single source of truth)
==============================
The equity series and the underwater curve are **reused by import** from
:mod:`spa_core.paper_trading.drawdown_analytics`
(``extract_equity_series`` / ``underwater_curve``) -- we do NOT recompute
drawdowns. :func:`content_fingerprint` is **reused by import** from
:mod:`spa_core.reporting.tear_sheet` (project convention MP-501) so idempotency
is byte-for-byte identical to the rest of the suite.

What this is NOT
================
* NOT an episode decomposer (that is drawdown_analytics MP-115).
* NOT conditional drawdown-at-risk (that is conditional_drawdown).
* NOT money-moving -- STRICTLY READ-ONLY / advisory. It only READS the equity
  track (``data/equity_curve_daily.json``) and writes its OWN derived status
  artifact. It never touches risk / execution / allocator / cycle_runner /
  golive_checker.

Advisory verdict
================
* **fail** -- ``ulcer_index >= UI_FAIL`` (deep, sustained pain), OR the Martin
  ratio is below :data:`MARTIN_FAIL` (return does not justify the pain), OR the
  annualized return is negative while drawdowns exist (pain with nothing to
  show for it).
* **warn** -- ``ulcer_index >= UI_WARN`` OR ``martin_ratio < MARTIN_WARN``.
* **ok** -- otherwise. A perfectly monotonic track has ``ulcer_index == 0`` and
  an undefined (None) Martin ratio -> ``ok`` with a "no drawdowns" note.
``verdict_reason`` is always present. Insufficient data
(``n < MIN_OBS``) -> ``available:false``, ``verdict:"ok"`` -- the schema stays
stable.

Output / persistence
====================
:func:`build_ulcer_index` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (``tempfile.mkstemp`` + ``os.replace``) writes
``data/ulcer_index.json`` with an in-file ``history`` (rotation <=
:data:`HISTORY_MAX`). Idempotency via :func:`content_fingerprint` (REUSED BY
IMPORT from :mod:`spa_core.reporting.tear_sheet`, MP-501) over the doc EXCLUDING
the volatile ``meta.generated_at`` / ``history``.

CLI::

    python3 -m spa_core.paper_trading.ulcer_index --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.ulcer_index --run     # + atomic write
    python3 -m spa_core.paper_trading.ulcer_index --run --data-dir <dir>

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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# -- Equity series + underwater curve REUSED BY IMPORT (single source of truth,
# drawdown_analytics MP-115). We do NOT recompute drawdowns here. ------------
from spa_core.paper_trading.drawdown_analytics import (
    extract_equity_series,
    underwater_curve,
)

# -- content_fingerprint REUSED BY IMPORT (project convention, MP-501) --------
from spa_core.reporting.tear_sheet import content_fingerprint
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.ulcer_index")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "ulcer_index"
STATUS_FILENAME: str = "ulcer_index.json"
EQUITY_FILENAME: str = "equity_curve_daily.json"
HISTORY_MAX: int = 500

# Require a comfortable number of equity points for a meaningful Ulcer Index.
MIN_OBS: int = 10

# Advisory thresholds (documented). The Ulcer Index is in percentage units
# (RMS of underwater %). UI_WARN/UI_FAIL flank "uncomfortable" / "painful"
# drawdown regimes; the Martin thresholds flank pain-adjusted return that is
# marginal (< 1.0) / poor (< 0.5).
UI_WARN: float = 7.5
UI_FAIL: float = 15.0
MARTIN_WARN: float = 1.0
MARTIN_FAIL: float = 0.5

ANNUALIZATION_DAYS: float = 365.0

__all__ = [
    "ulcer_index",
    "pain_index",
    "max_drawdown_pct",
    "annualized_return_pct",
    "martin_ratio",
    "build_ulcer_index",
    "write_status",
    "main",
    "content_fingerprint",
    "extract_equity_series",
    "underwater_curve",
    "MIN_OBS",
    "HISTORY_MAX",
    "SOURCE_NAME",
    "STATUS_FILENAME",
    "UI_WARN",
    "UI_FAIL",
    "MARTIN_WARN",
    "MARTIN_FAIL",
]


# ------------------------------------------------------------------------------
# Pure hand-verifiable math (no I/O)
# ------------------------------------------------------------------------------

def ulcer_index(underwater_pcts: List[float]) -> Optional[float]:
    """Ulcer Index = root-mean-square of the underwater % series.

        UI = sqrt( mean( d_k**2 ) )

    Each ``d_k`` is a drawdown % from the running peak (<= 0); squaring removes
    the sign, so a monotonically-rising track (all zeros) yields exactly 0.0.
    Empty input -> ``None``. Pure / never raises.

    Hand example: ``[0, -10, -20]`` -> mean(0, 100, 400) = 166.6667,
    sqrt = 12.909944.
    """
    if not underwater_pcts:
        return None
    total = 0.0
    for d in underwater_pcts:
        total += float(d) * float(d)
    return math.sqrt(total / len(underwater_pcts))


def pain_index(underwater_pcts: List[float]) -> Optional[float]:
    """Pain Index = mean of ``abs(d_k)`` (average underwater depth, >= 0).

    Empty input -> ``None``. Pure / never raises. Unlike the Ulcer Index this
    is a simple arithmetic mean of depths, so deep drawdowns are not given the
    extra quadratic weight the UI assigns them.
    """
    if not underwater_pcts:
        return None
    total = 0.0
    for d in underwater_pcts:
        total += abs(float(d))
    return total / len(underwater_pcts)


def max_drawdown_pct(underwater_pcts: List[float]) -> Optional[float]:
    """Most-negative underwater value (returned as a negative number).

    Bonus context metric: the single worst point of the underwater curve.
    Empty input -> ``None``. Pure / never raises.
    """
    if not underwater_pcts:
        return None
    worst = float(underwater_pcts[0])
    for d in underwater_pcts[1:]:
        dv = float(d)
        if dv < worst:
            worst = dv
    return worst


def annualized_return_pct(series: List[Tuple[str, float]]) -> Optional[float]:
    """Annualized return % from the first/last equity levels and date span.

        total = E_last / E_first
        ann   = (total ** (365 / span_days) - 1) * 100

    ``span_days`` is the calendar-day span between the first and last ISO date.
    Returns ``None`` if there are fewer than 2 points, ``span_days <= 0``,
    ``E_first <= 0``, ``total <= 0`` (cannot take a fractional power of a
    non-positive number), or a date is unparseable. Pure / never raises.
    """
    if not series or len(series) < 2:
        return None
    try:
        first_date, first_eq = series[0]
        last_date, last_eq = series[-1]
        first_eq = float(first_eq)
        last_eq = float(last_eq)
        if first_eq <= 0:
            return None
        try:
            d0 = date.fromisoformat(str(first_date)[:10])
            d1 = date.fromisoformat(str(last_date)[:10])
        except ValueError:
            return None
        span_days = (d1 - d0).days
        if span_days <= 0:
            return None
        total = last_eq / first_eq
        if total <= 0:
            return None
        ann = (total ** (ANNUALIZATION_DAYS / span_days) - 1.0) * 100.0
        if not math.isfinite(ann):
            return None
        return ann
    except (ValueError, OverflowError, ZeroDivisionError):
        return None


def martin_ratio(
    ann_return_pct: Optional[float], ui: Optional[float]
) -> Optional[float]:
    """Martin Ratio (Ulcer Performance Index) = ``ann_return_pct / ui``.

    Returns ``None`` if either argument is ``None`` or if ``ui == 0`` (no
    drawdowns -> the pain-adjusted return is undefined / infinite). Pure /
    never raises.
    """
    if ann_return_pct is None or ui is None:
        return None
    if ui == 0:
        return None
    try:
        out = ann_return_pct / ui
        if not math.isfinite(out):
            return None
        return out
    except (ZeroDivisionError, ValueError, OverflowError):
        return None


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
        "ulcer_index": None,
        "pain_index": None,
        "max_drawdown_pct": None,
        "annualized_return_pct": None,
        "martin_ratio": None,
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


def build_ulcer_index(
    data_dir: str | os.PathLike = _DEFAULT_DATA_DIR,
) -> Dict[str, Any]:
    """Compute the Ulcer Index / Martin Ratio over the equity track. Never
    raises.

    Loads ``equity_curve_daily.json``, extracts the equity series (REUSED from
    drawdown_analytics), derives the underwater curve, and computes the Ulcer
    Index, Pain Index, max drawdown, annualized return and Martin ratio.
    Returns a stable-schema dict.
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

        underwater = [dd for (_d, dd) in underwater_curve(series)]

        ui = ulcer_index(underwater)
        pain = pain_index(underwater)
        mdd = max_drawdown_pct(underwater)
        ann_ret = annualized_return_pct(series)
        martin = martin_ratio(ann_ret, ui)

        start_date = series[0][0]
        end_date = series[-1][0]

        # -- Advisory verdict --------------------------------------------------
        # fail: deep sustained pain, OR return doesn't justify the pain, OR a
        # negative return alongside real drawdowns.
        fail = False
        if ui is not None and ui >= UI_FAIL:
            fail = True
        elif martin is not None and martin < MARTIN_FAIL:
            fail = True
        elif (
            martin is None
            and ann_ret is not None
            and ann_ret < 0
            and ui not in (None, 0)
        ):
            fail = True

        warn = False
        if not fail:
            if ui is not None and ui >= UI_WARN:
                warn = True
            elif martin is not None and martin < MARTIN_WARN:
                warn = True

        if fail:
            verdict = "fail"
        elif warn:
            verdict = "warn"
        else:
            verdict = "ok"

        # verdict_reason (always present, descriptive).
        if ui == 0:
            notes.append(
                "no drawdowns over track (Ulcer Index = 0); "
                "Martin ratio undefined"
            )
        if verdict == "fail":
            if ui is not None and ui >= UI_FAIL:
                verdict_reason = (
                    f"Ulcer Index {ui:.4f} >= {UI_FAIL} -- deep / sustained "
                    f"drawdown pain over the track (max drawdown "
                    f"{mdd if mdd is None else round(mdd, 4)}%)"
                )
            elif martin is not None and martin < MARTIN_FAIL:
                verdict_reason = (
                    f"Martin ratio {martin:.4f} < {MARTIN_FAIL} -- the "
                    f"annualized return "
                    f"({ann_ret if ann_ret is None else round(ann_ret, 4)}%) "
                    f"does not justify the drawdown pain (UI {ui:.4f})"
                )
            else:
                verdict_reason = (
                    f"annualized return "
                    f"({ann_ret if ann_ret is None else round(ann_ret, 4)}%) "
                    f"is negative while the track sits in drawdown "
                    f"(UI {ui:.4f}) -- pain with nothing to show for it"
                )
        elif verdict == "warn":
            if ui is not None and ui >= UI_WARN:
                verdict_reason = (
                    f"Ulcer Index {ui:.4f} >= {UI_WARN} -- elevated drawdown "
                    f"pain (Martin ratio "
                    f"{martin if martin is None else round(martin, 4)})"
                )
            else:
                verdict_reason = (
                    f"Martin ratio {martin:.4f} < {MARTIN_WARN} -- marginal "
                    f"pain-adjusted return (UI {ui:.4f}, annualized return "
                    f"{ann_ret if ann_ret is None else round(ann_ret, 4)}%)"
                )
        else:  # ok
            if ui == 0:
                verdict_reason = (
                    "no drawdowns over the track (Ulcer Index = 0); the "
                    "strategy never sat underwater -- Martin ratio undefined"
                )
            else:
                verdict_reason = (
                    f"Ulcer Index {ui:.4f} < {UI_WARN} and Martin ratio "
                    f"{martin if martin is None else round(martin, 4)} "
                    f"acceptable -- drawdown pain within comfortable bounds"
                )

        def _rnd(x: Optional[float], places: int = 6) -> Optional[float]:
            return None if x is None else round(x, places)

        result: Dict[str, Any] = {
            "available": True,
            "is_demo": is_demo,
            "ulcer_index": _rnd(ui),
            "pain_index": _rnd(pain),
            "max_drawdown_pct": _rnd(mdd),
            "annualized_return_pct": _rnd(ann_ret),
            "martin_ratio": _rnd(martin),
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
        log.exception("unexpected error in build_ulcer_index")
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
    """Atomically write ulcer_index.json.

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
            f"[ulcer_index] available=false reason={result.get('reason', '?')}"
        )
        print(f"  verdict       : {result.get('verdict')} -- {result.get('verdict_reason')}")
        for n in result.get("notes", []):
            print(f"  note: {n}")
        return

    print("[ulcer_index] available=true")
    print(f"  verdict       : {result['verdict']} -- {result['verdict_reason']}")
    print(f"  ulcer_index   : {result['ulcer_index']}")
    print(f"  pain_index    : {result['pain_index']}")
    print(f"  max_drawdown  : {result['max_drawdown_pct']}%")
    print(f"  ann_return    : {result['annualized_return_pct']}%")
    print(f"  martin_ratio  : {result['martin_ratio']}")
    print(f"  n_obs         : {result['n_observations']}")
    print(f"  start / end   : {result['start_date']} / {result['end_date']}")
    if result.get("is_demo") is not None:
        print(f"  is_demo       : {result['is_demo']}")
    for n in result.get("notes", []):
        print(f"  note: {n}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ulcer Index & Martin Ratio Analyzer (MP-146) -- "
                    "read-only / advisory",
        add_help=True,
    )
    parser.add_argument(
        "--check", action="store_true",
        help="compute and print, no write (default)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="compute, print, and atomically write to data/ulcer_index.json",
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

    result = build_ulcer_index(data_dir)
    _print_result(result)

    if args.run:
        status = write_status(result, data_dir)
        print(f"[ulcer_index] write_status={status}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
