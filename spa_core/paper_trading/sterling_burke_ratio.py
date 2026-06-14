#!/usr/bin/env python3
"""Sterling Ratio & Burke Ratio Analyzer (SPA-V469 / MP-371) — read-only /
advisory.

The drawdown cluster (drawdown_analytics MP-115, drawdown_attribution MP-127,
ulcer_index / Martin MP-146) decomposes the realised equity track into
*episodes*, the *underwater curve*, per-source attribution and the RMS-of-
underwater Ulcer/Martin pain metrics. Calmar (elsewhere) divides return by the
single *max* drawdown; Martin divides by the *RMS of the whole underwater
curve*. NONE of them computes the **Sterling Ratio** or the **Burke Ratio** --
two classic *episode-level* drawdown-adjusted return measures. That is the gap
MP-371 closes.

Why Sterling and Burke (and how they differ from Calmar / Martin)
=================================================================
Both ratios are return-per-unit-of-drawdown, but each summarises the *set of
drawdown episode depths* differently:

* **Calmar** uses only the single worst (maximum) drawdown -- one number.
* **Martin / Ulcer** uses the RMS of the *entire underwater %* time series --
  every bar, penalising duration.
* **Sterling Ratio** (Deane Sterling Jones) uses the *arithmetic mean* of the
  major drawdown episode depths, plus a fixed 10% adjustment so a single tiny
  drawdown cannot inflate the ratio to infinity::

      Sterling = annualized_return_pct / ( mean(|episode_depth_i|) + 10 )

  Hand example: annualized return 30%, episode depths [-10%, -20%, -30%] ->
  mean(10, 20, 30) = 20, +10 adjustment = 30, Sterling = 30 / 30 = 1.0.

* **Burke Ratio** (Gibbons Burke, 1994) uses an RMS-style penalty over *all*
  episode depths -- the square-root of the sum of squared episode depths --
  so a few deep episodes dominate (unlike Sterling's mean and Calmar's single
  max)::

      Burke = annualized_return_pct / sqrt( sum( episode_depth_i ** 2 ) )

  Hand example: annualized return 30%, episode depths [-10%, -20%, -30%] ->
  sqrt(100 + 400 + 900) = sqrt(1400) = 37.416574, Burke = 30 / 37.416574 =
  0.801784.

So Sterling = mean-of-episodes (+10), Burke = RMS-of-episodes, Calmar =
max-episode, Martin = RMS-of-underwater-curve. Four genuinely distinct lenses.

Reuse (single source of truth)
==============================
The equity series is **reused by import** from
:mod:`spa_core.paper_trading.drawdown_analytics` (``extract_equity_series``);
the drawdown *episodes* are **reused by import** from
:mod:`spa_core.paper_trading.drawdown_attribution`
(``identify_drawdown_episodes`` -> each episode carries a negative
``drawdown_pct``). :func:`content_fingerprint` is **reused by import** from
:mod:`spa_core.reporting.tear_sheet` (project convention MP-501) so idempotency
is byte-for-byte identical to the rest of the suite. We do NOT recompute the
drawdown math; ``annualized_return_pct`` is a small pure helper (same logic as
ulcer_index.py).

What this is NOT
================
* NOT an episode decomposer (that is drawdown_analytics / drawdown_attribution).
* NOT the Ulcer / Martin RMS-underwater metric (that is ulcer_index MP-146).
* NOT money-moving -- STRICTLY READ-ONLY / advisory. It only READS the equity
  track (``data/equity_curve_daily.json``) and writes its OWN derived status
  artifact. It never touches risk / execution / allocator / cycle_runner /
  golive_checker / adapters.

Advisory verdict
================
* **fail** -- ``sterling_ratio < STERLING_FAIL`` OR ``burke_ratio < BURKE_FAIL``
  (return does not justify the episode drawdowns), OR the annualized return is
  negative while drawdowns exist (pain with nothing to show for it).
* **warn** -- ``sterling_ratio < STERLING_WARN`` OR ``burke_ratio < BURKE_WARN``.
* **ok** -- otherwise. A track with NO drawdown episodes has empty magnitudes ->
  both ratios are ``None`` -> ``ok`` with a "no drawdowns over track" note.
``verdict_reason`` is always present. Insufficient data (``n < MIN_OBS``) ->
``available:false``, ``verdict:"ok"`` -- the schema stays stable.

Output / persistence
====================
:func:`build_sterling_burke` returns a stable-schema dict and NEVER raises.
:func:`write_status` atomically (``tempfile.mkstemp`` + ``os.replace``) writes
``data/sterling_burke_ratio.json`` with an in-file ``history`` (rotation <=
:data:`HISTORY_MAX`). Idempotency via :func:`content_fingerprint` (REUSED BY
IMPORT from :mod:`spa_core.reporting.tear_sheet`, MP-501) over the doc EXCLUDING
the volatile ``meta.generated_at`` / ``history``.

CLI::

    python3 -m spa_core.paper_trading.sterling_burke_ratio --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.sterling_burke_ratio --run     # + atomic write
    python3 -m spa_core.paper_trading.sterling_burke_ratio --run --data-dir <dir>

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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# -- Equity series REUSED BY IMPORT (single source of truth, drawdown_analytics
# MP-115). We do NOT recompute the equity extraction here. -------------------
from spa_core.paper_trading.drawdown_analytics import extract_equity_series

# -- Drawdown EPISODES REUSED BY IMPORT (drawdown_attribution MP-127). Each
# episode carries a negative ``drawdown_pct``; we do NOT recompute episodes. --
from spa_core.paper_trading.drawdown_attribution import identify_drawdown_episodes

# -- content_fingerprint REUSED BY IMPORT (project convention, MP-501) --------
from spa_core.reporting.tear_sheet import content_fingerprint

log = logging.getLogger("spa.paper_trading.sterling_burke_ratio")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "sterling_burke_ratio"
STATUS_FILENAME: str = "sterling_burke_ratio.json"
EQUITY_FILENAME: str = "equity_curve_daily.json"
HISTORY_MAX: int = 500

# Require a comfortable number of equity points for meaningful ratios.
MIN_OBS: int = 10

ANNUALIZATION_DAYS: float = 365.0

# The classic Deane Sterling Jones adjustment added to the mean drawdown so a
# single tiny drawdown cannot drive the denominator to ~0 / the ratio to inf.
STERLING_ADJUSTMENT: float = 10.0

# Advisory thresholds (documented). Both ratios are return-per-unit-of-drawdown:
# a ratio >= 1 means the annualized return at least matches the (adjusted /
# RMS) drawdown magnitude. WARN flanks "marginal" (< 1.0), FAIL flanks "poor"
# (< 0.5) drawdown-adjusted return.
STERLING_WARN: float = 1.0
STERLING_FAIL: float = 0.5
BURKE_WARN: float = 1.0
BURKE_FAIL: float = 0.5

__all__ = [
    "drawdown_magnitudes",
    "sterling_ratio",
    "burke_ratio",
    "avg_drawdown_pct",
    "max_drawdown_pct",
    "num_drawdown_episodes",
    "annualized_return_pct",
    "build_sterling_burke",
    "write_status",
    "main",
    "content_fingerprint",
    "extract_equity_series",
    "identify_drawdown_episodes",
    "MIN_OBS",
    "HISTORY_MAX",
    "SOURCE_NAME",
    "STATUS_FILENAME",
    "STERLING_ADJUSTMENT",
    "STERLING_WARN",
    "STERLING_FAIL",
    "BURKE_WARN",
    "BURKE_FAIL",
]


# ------------------------------------------------------------------------------
# Pure hand-verifiable math (no I/O)
# ------------------------------------------------------------------------------

def drawdown_magnitudes(episodes: List[Dict[str, Any]]) -> List[float]:
    """Absolute depth (positive %) of each drawdown episode.

    Each episode dict (from :func:`identify_drawdown_episodes`) carries a
    negative ``drawdown_pct``; this returns ``abs(drawdown_pct)`` for every
    episode that has a finite numeric depth. Empty / non-list input -> ``[]``.
    Bars without a usable ``drawdown_pct`` are skipped. Pure / never raises.

    Hand example: episodes with drawdown_pct [-10, -20, -30] -> [10, 20, 30].
    """
    if not episodes or not isinstance(episodes, list):
        return []
    out: List[float] = []
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        dd = ep.get("drawdown_pct")
        if isinstance(dd, bool) or not isinstance(dd, (int, float)):
            continue
        ddf = float(dd)
        if not math.isfinite(ddf):
            continue
        out.append(abs(ddf))
    return out


def sterling_ratio(
    ann_return_pct: Optional[float],
    magnitudes: List[float],
    adjustment: float = STERLING_ADJUSTMENT,
) -> Optional[float]:
    """Sterling Ratio = ``ann_return_pct / (mean(magnitudes) + adjustment)``.

    Classic Deane Sterling Jones formula: the average *major* drawdown depth
    plus a fixed 10% adjustment in the denominator. ``magnitudes`` are positive
    episode depths (from :func:`drawdown_magnitudes`).

    Returns ``None`` if ``ann_return_pct`` is ``None``, if ``magnitudes`` is
    empty (no drawdowns -> ratio undefined), or if the denominator
    ``mean(magnitudes) + adjustment <= 0``. Pure / never raises.

    Hand example: ann_return 30%, magnitudes [10, 20, 30] ->
    mean = 20, +10 = 30, Sterling = 30 / 30 = 1.0.
    """
    if ann_return_pct is None or not magnitudes:
        return None
    try:
        mean_dd = sum(float(m) for m in magnitudes) / len(magnitudes)
        denom = mean_dd + float(adjustment)
        if denom <= 0:
            return None
        out = float(ann_return_pct) / denom
        if not math.isfinite(out):
            return None
        return out
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def burke_ratio(
    ann_return_pct: Optional[float],
    magnitudes: List[float],
) -> Optional[float]:
    """Burke Ratio = ``ann_return_pct / sqrt(sum(m_i ** 2))``.

    Gibbons Burke (1994): an RMS-style penalty over ALL drawdown episode depths
    -- the square-root of the sum of squared episode magnitudes. Unlike
    Sterling's *mean* of episodes and Calmar's single *max*, deep episodes
    dominate the denominator quadratically.

    Returns ``None`` if ``ann_return_pct`` is ``None``, if ``magnitudes`` is
    empty, or if the denominator ``sqrt(sum(m_i**2)) <= 0``. Pure / never
    raises.

    Hand example: ann_return 30%, magnitudes [10, 20, 30] ->
    sqrt(100 + 400 + 900) = sqrt(1400) = 37.416574, Burke = 30 / 37.416574 =
    0.801784.
    """
    if ann_return_pct is None or not magnitudes:
        return None
    try:
        ssq = 0.0
        for m in magnitudes:
            mf = float(m)
            ssq += mf * mf
        denom = math.sqrt(ssq)
        if denom <= 0:
            return None
        out = float(ann_return_pct) / denom
        if not math.isfinite(out):
            return None
        return out
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def avg_drawdown_pct(magnitudes: List[float]) -> Optional[float]:
    """Mean of the (positive) episode drawdown magnitudes, or ``None`` if empty.

    Context metric: the average episode depth. Pure / never raises.
    """
    if not magnitudes:
        return None
    return sum(float(m) for m in magnitudes) / len(magnitudes)


def max_drawdown_pct(magnitudes: List[float]) -> Optional[float]:
    """Largest (deepest) episode drawdown magnitude (positive %), or ``None``.

    Context metric: the single worst episode depth (the value Calmar would use).
    Pure / never raises.
    """
    if not magnitudes:
        return None
    worst = float(magnitudes[0])
    for m in magnitudes[1:]:
        mf = float(m)
        if mf > worst:
            worst = mf
    return worst


def num_drawdown_episodes(episodes: List[Dict[str, Any]]) -> int:
    """Number of drawdown episodes (length of the episode list). Never raises."""
    if not episodes or not isinstance(episodes, list):
        return 0
    return sum(1 for ep in episodes if isinstance(ep, dict))


def annualized_return_pct(series: List[Tuple[str, float]]) -> Optional[float]:
    """Annualized return % from the first/last equity levels and date span.

        total = E_last / E_first
        ann   = (total ** (365 / span_days) - 1) * 100

    ``span_days`` is the calendar-day span between the first and last ISO date.
    Returns ``None`` if there are fewer than 2 points, ``span_days <= 0``,
    ``E_first <= 0``, ``total <= 0`` (cannot take a fractional power of a
    non-positive number), or a date is unparseable. Pure / never raises.
    (Same logic as ulcer_index.py -- kept as a small local helper.)
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
        "sterling_ratio": None,
        "burke_ratio": None,
        "avg_drawdown_pct": None,
        "max_drawdown_pct": None,
        "n_drawdown_episodes": None,
        "annualized_return_pct": None,
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


def build_sterling_burke(
    data_dir: str | os.PathLike = _DEFAULT_DATA_DIR,
) -> Dict[str, Any]:
    """Compute the Sterling Ratio / Burke Ratio over the equity track. Never
    raises.

    Loads ``equity_curve_daily.json``, extracts the equity series (REUSED from
    drawdown_analytics), identifies drawdown episodes (REUSED from
    drawdown_attribution), and computes the Sterling and Burke ratios plus the
    avg / max episode depth, episode count and annualized return. Returns a
    stable-schema dict.
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

        # -- Drawdown episodes (REUSED from drawdown_attribution) --------------
        # identify_drawdown_episodes takes the raw [{date, equity}] bar form.
        bars = [{"date": d, "equity": eq} for (d, eq) in series]
        episodes = identify_drawdown_episodes(bars)

        magnitudes = drawdown_magnitudes(episodes)
        n_episodes = num_drawdown_episodes(episodes)
        ann_ret = annualized_return_pct(series)
        sterling = sterling_ratio(ann_ret, magnitudes)
        burke = burke_ratio(ann_ret, magnitudes)
        avg_dd = avg_drawdown_pct(magnitudes)
        max_dd = max_drawdown_pct(magnitudes)

        start_date = series[0][0]
        end_date = series[-1][0]

        no_drawdowns = not magnitudes

        # -- Advisory verdict --------------------------------------------------
        # fail: return doesn't justify the episode drawdowns (either ratio below
        # its FAIL band), OR a negative return alongside real drawdowns.
        fail = False
        if sterling is not None and sterling < STERLING_FAIL:
            fail = True
        elif burke is not None and burke < BURKE_FAIL:
            fail = True
        elif (
            not no_drawdowns
            and ann_ret is not None
            and ann_ret < 0
        ):
            fail = True

        warn = False
        if not fail:
            if sterling is not None and sterling < STERLING_WARN:
                warn = True
            elif burke is not None and burke < BURKE_WARN:
                warn = True

        if fail:
            verdict = "fail"
        elif warn:
            verdict = "warn"
        else:
            verdict = "ok"

        # verdict_reason (always present, descriptive).
        if no_drawdowns:
            notes.append(
                "no drawdowns over track; Sterling / Burke ratios undefined"
            )

        if verdict == "fail":
            if sterling is not None and sterling < STERLING_FAIL:
                verdict_reason = (
                    f"Sterling ratio {sterling:.4f} < {STERLING_FAIL} -- the "
                    f"annualized return "
                    f"({ann_ret if ann_ret is None else round(ann_ret, 4)}%) "
                    f"does not justify the average drawdown "
                    f"({avg_dd if avg_dd is None else round(avg_dd, 4)}% over "
                    f"{n_episodes} episodes, +{STERLING_ADJUSTMENT} adj)"
                )
            elif burke is not None and burke < BURKE_FAIL:
                verdict_reason = (
                    f"Burke ratio {burke:.4f} < {BURKE_FAIL} -- the annualized "
                    f"return "
                    f"({ann_ret if ann_ret is None else round(ann_ret, 4)}%) "
                    f"does not justify the RMS of {n_episodes} drawdown "
                    f"episodes (max depth "
                    f"{max_dd if max_dd is None else round(max_dd, 4)}%)"
                )
            else:
                verdict_reason = (
                    f"annualized return "
                    f"({ann_ret if ann_ret is None else round(ann_ret, 4)}%) "
                    f"is negative while the track has {n_episodes} drawdown "
                    f"episodes -- pain with nothing to show for it"
                )
        elif verdict == "warn":
            if sterling is not None and sterling < STERLING_WARN:
                verdict_reason = (
                    f"Sterling ratio {sterling:.4f} < {STERLING_WARN} -- "
                    f"marginal drawdown-adjusted return (Burke "
                    f"{burke if burke is None else round(burke, 4)}, avg "
                    f"drawdown "
                    f"{avg_dd if avg_dd is None else round(avg_dd, 4)}%)"
                )
            else:
                verdict_reason = (
                    f"Burke ratio {burke:.4f} < {BURKE_WARN} -- marginal "
                    f"drawdown-adjusted return (Sterling "
                    f"{sterling if sterling is None else round(sterling, 4)}, "
                    f"max drawdown "
                    f"{max_dd if max_dd is None else round(max_dd, 4)}%)"
                )
        else:  # ok
            if no_drawdowns:
                verdict_reason = (
                    "no drawdown episodes over the track; the strategy never "
                    "sat underwater -- Sterling / Burke ratios undefined"
                )
            else:
                verdict_reason = (
                    f"Sterling ratio "
                    f"{sterling if sterling is None else round(sterling, 4)} "
                    f">= {STERLING_WARN} and Burke ratio "
                    f"{burke if burke is None else round(burke, 4)} >= "
                    f"{BURKE_WARN} -- drawdown-adjusted return within "
                    f"comfortable bounds ({n_episodes} episodes)"
                )

        def _rnd(x: Optional[float], places: int = 6) -> Optional[float]:
            return None if x is None else round(x, places)

        result: Dict[str, Any] = {
            "available": True,
            "is_demo": is_demo,
            "sterling_ratio": _rnd(sterling),
            "burke_ratio": _rnd(burke),
            "avg_drawdown_pct": _rnd(avg_dd),
            "max_drawdown_pct": _rnd(max_dd),
            "n_drawdown_episodes": n_episodes,
            "annualized_return_pct": _rnd(ann_ret),
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
        log.exception("unexpected error in build_sterling_burke")
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
    """Atomically write sterling_burke_ratio.json.

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

    fd, tmp_path = tempfile.mkstemp(dir=data_dir, prefix=".tmp_sterling_burke_")
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
            f"[sterling_burke_ratio] available=false "
            f"reason={result.get('reason', '?')}"
        )
        print(
            f"  verdict       : {result.get('verdict')} -- "
            f"{result.get('verdict_reason')}"
        )
        for n in result.get("notes", []):
            print(f"  note: {n}")
        return

    print("[sterling_burke_ratio] available=true")
    print(f"  verdict       : {result['verdict']} -- {result['verdict_reason']}")
    print(f"  sterling_ratio: {result['sterling_ratio']}")
    print(f"  burke_ratio   : {result['burke_ratio']}")
    print(f"  avg_drawdown  : {result['avg_drawdown_pct']}%")
    print(f"  max_drawdown  : {result['max_drawdown_pct']}%")
    print(f"  n_episodes    : {result['n_drawdown_episodes']}")
    print(f"  ann_return    : {result['annualized_return_pct']}%")
    print(f"  n_obs         : {result['n_observations']}")
    print(f"  start / end   : {result['start_date']} / {result['end_date']}")
    if result.get("is_demo") is not None:
        print(f"  is_demo       : {result['is_demo']}")
    for n in result.get("notes", []):
        print(f"  note: {n}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sterling Ratio & Burke Ratio Analyzer (MP-371) -- "
                    "read-only / advisory",
        add_help=True,
    )
    parser.add_argument(
        "--check", action="store_true",
        help="compute and print, no write (default)",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="compute, print, and atomically write to "
             "data/sterling_burke_ratio.json",
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
        print(
            "ERROR: --check and --run are mutually exclusive", file=sys.stderr
        )
        return 0

    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR

    result = build_sterling_burke(data_dir)
    _print_result(result)

    if args.run:
        status = write_status(result, data_dir)
        print(f"[sterling_burke_ratio] write_status={status}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
