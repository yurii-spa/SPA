#!/usr/bin/env python3
"""Drawdown Episode & Underwater Analyzer (SPA-V433 / MP-115) — read-only / advisory.

Decomposes the realised equity track (``data/equity_curve_daily.json``) into its
**drawdown episodes** and the **underwater curve**, answering the institutional
DD question *"how deep and how long are your drawdowns, and are you underwater
right now?"*. The tear-sheet (MP-501) reports a single headline max-drawdown
number; this module reports the *episode-level* anatomy behind it: every
peak→trough→recovery cycle with its depth, decline duration, recovery duration,
total time underwater, and whether it has recovered yet.

Reuse (single source of truth)
==============================
The compounded-path drawdown math is **reused by import** from
:mod:`spa_core.reporting.tear_sheet` (``max_drawdown_from_returns`` /
``compound_return_pct``) — we do NOT reimplement the drawdown formula. The
episode walk operates on the close-equity *level* series; the deepest episode
depth equals ``max_drawdown_from_returns`` applied to the close-to-close return
series (proven by an equality test), because compounding consecutive
close-to-close returns reconstructs exactly the same level path.

Conventions
===========
The equity series is taken from each bar's ``close_equity`` (fallback
``equity``), sorted by ``date``. The first valid bar is the initial peak
baseline (its drawdown is 0). The underwater value at bar *t* is
``(equity_t / running_peak_t − 1) · 100`` (≤ 0). A position is "underwater"
while that value is strictly negative. Durations are computed in calendar days
from the ISO ``date`` strings (tolerant: unparseable dates → ``None`` days).

Output / persistence
====================
:func:`build_drawdown_analytics` returns a stable-schema dict and NEVER raises
(missing / broken / empty file → honest nulls + notes). :func:`write_status`
atomically (tmp + ``os.replace``) writes ``data/drawdown_analytics.json`` with
an in-file ``history`` of runs (rotation ≤ :data:`HISTORY_MAX`). Idempotency: a
:func:`content_fingerprint` over the whole doc EXCLUDING the volatile
``meta.generated_at`` / ``history`` means a repeated ``--run`` on unchanged
inputs is byte-identical and does not grow history.

CLI (offline, exit 0 always, no tracebacks; junk args → clear ERROR on stderr)::

    python3 -m spa_core.paper_trading.drawdown_analytics --check   # compute+print, no write (default)
    python3 -m spa_core.paper_trading.drawdown_analytics --run     # + atomic write
    python3 -m spa_core.paper_trading.drawdown_analytics --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory only. Pure stdlib
(json/os/math/datetime/argparse/tempfile/logging/pathlib) — no
requests/web3/LLM SDK/sockets/network. It only READS ``equity_curve_daily.json``
and writes its OWN status artifact; it never moves capital and never touches
risk/execution/allocator/cycle_runner.
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

# REUSE BY IMPORT — single source of truth for the compounded-path drawdown
# math (MP-501). We do NOT reimplement the drawdown / compounding formula here.
from spa_core.reporting.tear_sheet import (
    max_drawdown_from_returns,
    compound_return_pct,
)
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.paper_trading.drawdown_analytics")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION = 1
SOURCE_NAME = "drawdown_analytics"
STATUS_FILENAME = "drawdown_analytics.json"
EQUITY_FILENAME = "equity_curve_daily.json"
HISTORY_MAX = 500  # run-history rotation (pattern: tear_sheet / exit_liquidity)
RECENT_UNDERWATER_MAX = 90  # bounded tail of the underwater curve in the doc

# Real (honest) track start — convention shared with index.html / portal_data.
REAL_TRACK_START = "2026-06-10"
DISCLAIMER = "NOT investment advice"


# ─── Tolerant IO / coercion helpers (pattern: tear_sheet / exit_liquidity) ────


def _read_json(path: Path) -> Any:
    """Read JSON tolerantly: missing/broken file → None, never raises."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Shim — delegates to spa_core.utils.atomic.atomic_save."""
    atomic_save(obj, path)
def _valid_date(value: Any) -> bool:
    """True iff ``value`` is an ISO ``YYYY-MM-DD`` (prefix) date string."""
    if not isinstance(value, str) or len(value) < 10:
        return False
    try:
        date.fromisoformat(value[:10])
        return True
    except ValueError:
        return False


def _days_between(start: Any, end: Any) -> Optional[int]:
    """Calendar days between two ISO date strings (end − start), or None."""
    if not _valid_date(start) or not _valid_date(end):
        return None
    try:
        d0 = date.fromisoformat(str(start)[:10])
        d1 = date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    return (d1 - d0).days


def _round(value: Optional[float], ndigits: int = 6) -> Optional[float]:
    return None if value is None else round(value, ndigits)


# ─── Equity series extraction ────────────────────────────────────────────────


def extract_equity_series(equity_doc: Any) -> List[Tuple[str, float]]:
    """Sorted ``[(date, close_equity), ...]`` from equity_curve_daily.json.

    Accepts either the canonical ``{"daily": [...]}`` wrapper or a bare list of
    bars. Each bar must have a valid ``date`` and a finite ``close_equity``
    (fallback ``equity``); other bars are silently skipped. Non-positive equity
    is dropped (a 0/negative level is not usable for ratio drawdowns). Never
    raises; bad input → ``[]``.
    """
    if isinstance(equity_doc, dict):
        daily = equity_doc.get("daily")
    else:
        daily = equity_doc
    if not isinstance(daily, list):
        return []
    out: List[Tuple[str, float]] = []
    for bar in daily:
        if not isinstance(bar, dict) or not _valid_date(bar.get("date")):
            continue
        eq = _num(bar.get("close_equity"))
        if eq is None:
            eq = _num(bar.get("equity"))
        if eq is None or eq <= 0:
            continue
        out.append((str(bar.get("date"))[:10], eq))
    out.sort(key=lambda kv: kv[0])
    return out


def _returns_from_levels(series: List[Tuple[str, float]]) -> List[float]:
    """Close-to-close daily returns (%) from a level series (len-1 values)."""
    returns: List[float] = []
    for i in range(1, len(series)):
        prev = series[i - 1][1]
        cur = series[i][1]
        if prev > 0:
            returns.append((cur / prev - 1.0) * 100.0)
    return returns


def underwater_curve(series: List[Tuple[str, float]]) -> List[Tuple[str, float]]:
    """Underwater curve ``[(date, drawdown_pct ≤ 0), ...]`` over running peak."""
    curve: List[Tuple[str, float]] = []
    peak = None
    for d, eq in series:
        peak = eq if peak is None else max(peak, eq)
        dd = (eq / peak - 1.0) * 100.0 if peak > 0 else 0.0
        curve.append((d, dd))
    return curve


# ─── Episode detection (peak → trough → recovery) ────────────────────────────


def detect_drawdown_episodes(series: List[Tuple[str, float]]) -> List[Dict[str, Any]]:
    """Decompose the level series into drawdown episodes.

    An episode opens when equity drops below the last confirmed peak and closes
    when equity recovers back to (≥) that peak. If the series ends while still
    below the peak the episode is ``recovered=False`` (ongoing). Each episode:
    start/peak date+value, trough date+value, depth_pct (≤0), decline_days
    (peak→trough), recovery_date, recovery_days (trough→recovery),
    underwater_days (peak→recovery, or peak→last bar if ongoing), recovered.
    Pure function — never raises.
    """
    episodes: List[Dict[str, Any]] = []
    if len(series) < 2:
        return episodes
    last_date = series[-1][0]
    peak_date, peak_val = series[0]
    in_dd = False
    ep: Optional[Dict[str, Any]] = None

    def _finalize(ep: Dict[str, Any], recovery_date: Optional[str]) -> Dict[str, Any]:
        recovered = recovery_date is not None
        end_for_underwater = recovery_date if recovered else last_date
        depth = (ep["trough_value"] / ep["peak_value"] - 1.0) * 100.0
        return {
            "start_date": ep["peak_date"],
            "peak_date": ep["peak_date"],
            "peak_value": _round(ep["peak_value"], 2),
            "trough_date": ep["trough_date"],
            "trough_value": _round(ep["trough_value"], 2),
            "depth_pct": _round(depth),
            "decline_days": _days_between(ep["peak_date"], ep["trough_date"]),
            "recovery_date": recovery_date,
            "recovery_days": _days_between(ep["trough_date"], recovery_date),
            "underwater_days": _days_between(ep["peak_date"], end_for_underwater),
            "recovered": recovered,
        }

    for d, eq in series[1:]:
        if not in_dd:
            if eq < peak_val:
                in_dd = True
                ep = {
                    "peak_date": peak_date,
                    "peak_value": peak_val,
                    "trough_date": d,
                    "trough_value": eq,
                }
            else:
                peak_date, peak_val = d, eq  # new (higher-or-equal) peak
        else:
            assert ep is not None
            if eq < ep["trough_value"]:
                ep["trough_value"] = eq
                ep["trough_date"] = d
            if eq >= peak_val:  # recovered to the pre-drawdown peak
                episodes.append(_finalize(ep, d))
                in_dd = False
                ep = None
                peak_date, peak_val = d, eq
    if in_dd and ep is not None:  # ongoing, unrecovered at end of track
        episodes.append(_finalize(ep, None))
    return episodes


# ─── Aggregate build ─────────────────────────────────────────────────────────


def _is_demo(equity_doc: Any) -> Optional[bool]:
    if isinstance(equity_doc, dict) and isinstance(equity_doc.get("is_demo"), bool):
        return equity_doc.get("is_demo")
    return None


def build_drawdown_analytics(
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build the drawdown-analytics document. Stable schema, never raises."""
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    now = now or datetime.now(timezone.utc)
    notes: List[str] = []

    equity_doc = _read_json(ddir / EQUITY_FILENAME)
    if equity_doc is None:
        notes.append(f"{EQUITY_FILENAME} missing or unreadable — no analytics")
    series = extract_equity_series(equity_doc)
    is_demo = _is_demo(equity_doc)

    meta = {
        "source": SOURCE_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "advisory_only": True,
        "disclaimer": DISCLAIMER,
        "source_file": EQUITY_FILENAME,
        "real_track_start": REAL_TRACK_START,
        "is_demo": is_demo,
    }

    if len(series) < 2:
        if equity_doc is not None and len(series) < 2:
            notes.append("equity series has < 2 valid bars — no drawdown analytics")
        meta["notes"] = notes
        return {
            "meta": meta,
            "available": False,
            "track": {
                "first_date": series[0][0] if series else None,
                "last_date": series[-1][0] if series else None,
                "num_bars": len(series),
            },
            "headline": {
                "max_drawdown_pct": None,
                "current_drawdown_pct": None,
                "currently_underwater": None,
                "longest_underwater_days": None,
                "time_in_drawdown_pct": None,
                "num_episodes": 0,
                "num_recovered": 0,
                "num_ongoing": 0,
                "avg_depth_pct": None,
                "avg_recovery_days": None,
                "worst_episode": None,
            },
            "episodes": [],
            "recent_underwater": [],
        }

    returns = _returns_from_levels(series)
    curve = underwater_curve(series)
    episodes = detect_drawdown_episodes(series)

    # Headline max drawdown — REUSED from tear_sheet (single source of truth).
    max_dd = max_drawdown_from_returns(returns) if returns else None

    underwater_bars = sum(1 for _, dd in curve if dd < 0)
    time_in_dd = (underwater_bars / len(curve) * 100.0) if curve else None
    current_dd = curve[-1][1] if curve else None
    currently_underwater = bool(current_dd is not None and current_dd < 0)

    recovered = [e for e in episodes if e["recovered"]]
    ongoing = [e for e in episodes if not e["recovered"]]
    depths = [e["depth_pct"] for e in episodes if e["depth_pct"] is not None]
    rec_days = [e["recovery_days"] for e in recovered if e["recovery_days"] is not None]
    uw_days = [e["underwater_days"] for e in episodes if e["underwater_days"] is not None]
    worst = min(episodes, key=lambda e: (e["depth_pct"] if e["depth_pct"] is not None else 0.0)) \
        if episodes else None

    headline = {
        "max_drawdown_pct": _round(max_dd),
        "current_drawdown_pct": _round(current_dd),
        "currently_underwater": currently_underwater,
        "longest_underwater_days": max(uw_days) if uw_days else None,
        "time_in_drawdown_pct": _round(time_in_dd),
        "num_episodes": len(episodes),
        "num_recovered": len(recovered),
        "num_ongoing": len(ongoing),
        "avg_depth_pct": _round(sum(depths) / len(depths)) if depths else None,
        "avg_recovery_days": _round(sum(rec_days) / len(rec_days), 2) if rec_days else None,
        "worst_episode": worst,
    }

    meta["notes"] = notes
    return {
        "meta": meta,
        "available": True,
        "track": {
            "first_date": series[0][0],
            "last_date": series[-1][0],
            "num_bars": len(series),
            "total_return_pct": _round(compound_return_pct(returns)),
        },
        "headline": headline,
        "episodes": episodes,
        "recent_underwater": [
            {"date": d, "drawdown_pct": _round(dd)}
            for d, dd in curve[-RECENT_UNDERWATER_MAX:]
        ],
    }


# ─── Persist (idempotent, pattern: tear_sheet MP-501 / exit_liquidity) ───────


def content_fingerprint(doc: Any) -> str:
    """Canonical fingerprint of the status CONTENT. Pure function.

    Volatile fields excluded: top-level ``history`` and ``meta.generated_at``
    (documented idempotency choice — ``generated_at`` only changes when content
    changes). Non-dict input → a fingerprint that never matches a valid doc.
    """
    if not isinstance(doc, dict):
        return "<invalid>"
    core = {k: v for k, v in doc.items() if k != "history"}
    meta = core.get("meta")
    if isinstance(meta, dict):
        core["meta"] = {k: v for k, v in meta.items() if k != "generated_at"}
    return json.dumps(core, sort_keys=True, ensure_ascii=False)


def _history_entry(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Short run-history record for drawdown_analytics.json."""
    meta = doc.get("meta") or {}
    head = doc.get("headline") or {}
    return {
        "generated_at": meta.get("generated_at"),
        "max_drawdown_pct": head.get("max_drawdown_pct"),
        "current_drawdown_pct": head.get("current_drawdown_pct"),
        "currently_underwater": head.get("currently_underwater"),
        "num_episodes": head.get("num_episodes"),
    }


def write_status(
    doc: Dict[str, Any], data_dir: Optional[str | os.PathLike] = None
) -> Dict[str, Any]:
    """Atomically write data/drawdown_analytics.json (tmp + os.replace).

    Idempotency: if :func:`content_fingerprint` is unchanged relative to the
    persisted status, the file is NOT rewritten (a repeated ``--run`` is
    byte-identical and history does not grow). On a content change a short
    record is appended to ``history`` (rotation ≤ :data:`HISTORY_MAX`). A
    broken/absent existing status file is tolerated as fresh.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    path = ddir / STATUS_FILENAME
    prev = _read_json(path)
    if isinstance(prev, dict) and content_fingerprint(prev) == content_fingerprint(doc):
        log.info("drawdown analytics unchanged: %s", path)
        return {"path": str(path), "changed": False}

    history: List[Dict[str, Any]] = []
    if isinstance(prev, dict) and isinstance(prev.get("history"), list):
        history = [h for h in prev["history"] if isinstance(h, dict)]
    history.append(_history_entry(doc))
    out = dict(doc)
    out["history"] = history[-HISTORY_MAX:]
    _atomic_write_json(path, out)
    log.info("drawdown analytics written: %s", path)
    return {"path": str(path), "changed": True}


# ─── CLI (offline, advisory, exit 0, no tracebacks) ──────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m spa_core.paper_trading.drawdown_analytics",
        description=(
            "Drawdown Episode & Underwater Analyzer (SPA-V433 / MP-115): "
            "read-only / advisory decomposition of the equity track into "
            "drawdown episodes + the underwater curve. Offline."
        ),
        add_help=True,
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--check", action="store_true",
        help="compute and print the JSON analytics WITHOUT writing (default)",
    )
    group.add_argument(
        "--run", action="store_true",
        help="compute and atomically write data/drawdown_analytics.json",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    # Custom error handling: argparse normally prints to stderr and exits 2 on a
    # junk arg; this advisory CLI must always exit 0 with a clear ERROR and no
    # traceback (pattern: exit_liquidity.py / data_integrity.py).
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(
                "ERROR: invalid arguments — use --check | --run [--data-dir DIR]",
                file=sys.stderr,
            )
        return 0

    try:
        doc = build_drawdown_analytics(data_dir=args.data_dir)
        if args.run:
            outcome = write_status(doc, data_dir=args.data_dir)
            head = doc.get("headline") or {}
            print(
                f"drawdown_analytics: max_dd={head.get('max_drawdown_pct')}% "
                f"current={head.get('current_drawdown_pct')}% "
                f"episodes={head.get('num_episodes')} — "
                f"{'written' if outcome['changed'] else 'unchanged (idempotent)'} "
                f"{outcome['path']}"
            )
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception as exc:  # advisory: no tracebacks, exit 0
        print(
            f"drawdown_analytics: ERROR — {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
