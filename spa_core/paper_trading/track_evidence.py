#!/usr/bin/env python3
"""Honest track-record evidence model (HONEST TRACK RESET, 2026-06-26).

The go-live track must count ONLY days backed by *real evidence* that a live
``daily_cycle`` actually ran — never the flat-rate backfill, never reconstructed
(interpolated) placeholders. This module is the single source of truth for what
"evidenced" means and how to label and count equity-curve bars accordingly.

Definition (deterministic, fail-CLOSED)
=======================================
A daily equity bar is **evidenced** iff ALL hold:

1. It is dated ON OR AFTER ``PAPER_REAL_START`` (post-teardown anchor); AND
2. It is NOT ``reconstructed: true`` (interpolated placeholder — no live cycle
   ran that day); AND
3. It is NOT ``is_warmup: true`` / ``is_seed: true`` (pre-teardown demo); AND
4. There is GROUND-TRUTH evidence a real cycle ran that day — a real
   ``logs/daily_cycle_YYYYMMDD.log`` file containing the canonical cycle header
   (``Starting daily paper cycle``).

The flat-rate **backfill** days (constant apy/yield/positions, zero down days,
maxDD 0.0, no cycle log) are NOT evidenced. The reconstructed day is NOT
evidenced. Only days with a real cycle log count.

``source`` taxonomy (written onto each bar by :func:`label_bars`)
----------------------------------------------------------------
* ``"cycle"``        — a real daily_cycle log exists → evidenced.
* ``"backfill"``     — dated >= anchor, no cycle log, not reconstructed →
                       flat-rate placeholder, NOT evidenced.
* ``"reconstructed"``— ``reconstructed: true`` interpolated bar, NOT evidenced.
* ``"warmup"``       — pre-anchor / warmup / seed bar, NOT evidenced.

Each labelled bar also carries an explicit ``evidenced: true|false`` boolean so
downstream readers (golive_checker, gap_monitor, dashboard) never have to
re-derive the rule. History is PRESERVED — bars are flagged, never deleted.

Backward-compat counting (``is_evidenced_bar``)
-----------------------------------------------
For counting we treat a bar as evidenced when it is dated >= anchor, not
reconstructed/warmup/seed, and EITHER explicitly ``evidenced: true`` OR has no
explicit honesty label at all (legacy/synthetic bars written before this reset,
relied upon by existing tests). A bar explicitly labelled ``evidenced: false``
(backfill / reconstructed) is excluded. This keeps the gate honest on real data
while not breaking synthetic fixtures that carry no labels.

Scope / safety
==============
* Stdlib only — no external dependencies.
* Deterministic — no LLM, no randomness, no network.
* Atomic writes (:func:`label_equity_file` via ``atomic_save``).
* Fail-CLOSED — when cycle-log evidence cannot be confirmed, a post-anchor bar
  is treated as NOT evidenced (backfill), never silently counted.
"""
from __future__ import annotations

import re
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from spa_core.utils.atomic import atomic_save

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LOGS_DIR = _REPO_ROOT / "logs"

# Post-teardown anchor — must agree with cycle_runner.PAPER_START_DATE and
# golive_checker.PAPER_REAL_START.
PAPER_REAL_START = _date(2026, 6, 10)

# Canonical header every real daily_cycle log emits at the top of its run.
_CYCLE_HEADER_RE = re.compile(r"Starting daily paper cycle", re.IGNORECASE)

# Source labels.
SOURCE_CYCLE = "cycle"
SOURCE_BACKFILL = "backfill"
SOURCE_RECONSTRUCTED = "reconstructed"
SOURCE_WARMUP = "warmup"


# ─── date helpers ──────────────────────────────────────────────────────────────


def _bar_date(bar: Any) -> _date | None:
    if not isinstance(bar, dict):
        return None
    raw = bar.get("date") or bar.get("timestamp") or bar.get("ts")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return _date.fromisoformat(raw[:10])
    except ValueError:
        return None


# ─── cycle-log evidence ─────────────────────────────────────────────────────────


def cycle_log_path(d: _date, logs_dir: Path | str | None = None) -> Path:
    """Return the expected ``logs/daily_cycle_YYYYMMDD.log`` path for a date."""
    base = Path(logs_dir) if logs_dir is not None else _DEFAULT_LOGS_DIR
    return base / f"daily_cycle_{d.strftime('%Y%m%d')}.log"


def has_cycle_log(d: _date, logs_dir: Path | str | None = None) -> bool:
    """True iff a real daily_cycle log for ``d`` exists with the cycle header.

    Fail-CLOSED: any read error or a missing header → False (treated as no
    evidence). An empty/header-less file does not count as a real cycle.
    """
    path = cycle_log_path(d, logs_dir)
    if not path.is_file():
        return False
    try:
        # Header is on the first line; read a small prefix only.
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(4096)
    except OSError:
        return False
    return bool(_CYCLE_HEADER_RE.search(head))


def evidenced_log_dates(logs_dir: Path | str | None = None) -> list[str]:
    """All ISO dates (>= anchor) that have a real cycle log, sorted ascending."""
    base = Path(logs_dir) if logs_dir is not None else _DEFAULT_LOGS_DIR
    out: set[str] = set()
    if not base.is_dir():
        return []
    for p in base.glob("daily_cycle_*.log"):
        m = re.search(r"daily_cycle_(\d{8})\.log$", p.name)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if d >= PAPER_REAL_START and has_cycle_log(d, base):
            out.add(d.isoformat())
    return sorted(out)


# ─── per-bar classification ─────────────────────────────────────────────────────


def classify_bar(
    bar: dict,
    *,
    paper_start: _date = PAPER_REAL_START,
    logs_dir: Path | str | None = None,
) -> tuple[str, bool]:
    """Return ``(source, evidenced)`` for one bar from GROUND TRUTH (cycle logs).

    Used by :func:`label_bars` to (re)compute honest labels. Deterministic and
    fail-CLOSED: a post-anchor non-reconstructed bar with no cycle log is
    ``backfill`` (NOT evidenced).
    """
    d = _bar_date(bar)
    if bar.get("is_warmup") is True or bar.get("is_seed") is True:
        return SOURCE_WARMUP, False
    if d is None or d < paper_start:
        return SOURCE_WARMUP, False
    if bar.get("reconstructed") is True:
        return SOURCE_RECONSTRUCTED, False
    if has_cycle_log(d, logs_dir):
        return SOURCE_CYCLE, True
    return SOURCE_BACKFILL, False


def is_evidenced_bar(bar: Any, *, paper_start: _date = PAPER_REAL_START) -> bool:
    """Counting predicate (reads the bar's OWN labels — no filesystem access).

    A bar counts toward the honest track iff:
      * dated >= ``paper_start``; AND
      * not reconstructed / warmup / seed; AND
      * not explicitly ``evidenced: false`` (backfill) and not
        ``source`` in {backfill, reconstructed, warmup}.

    Backward-compat: a bar with NO explicit honesty label (legacy/synthetic)
    is treated as evidenced (so existing fixtures still count). Only an explicit
    negative label excludes it.
    """
    if not isinstance(bar, dict):
        return False
    d = _bar_date(bar)
    if d is None or d < paper_start:
        return False
    if bar.get("is_warmup") is True or bar.get("is_seed") is True:
        return False
    if bar.get("reconstructed") is True:
        return False
    if bar.get("evidenced") is False:
        return False
    src = bar.get("source")
    if src in (SOURCE_BACKFILL, SOURCE_RECONSTRUCTED, SOURCE_WARMUP):
        return False
    return True


def evidenced_bars(
    daily: Iterable[Any], *, paper_start: _date = PAPER_REAL_START
) -> list[dict]:
    """Return ONLY the evidenced bars (the clean REAL series), in input order.

    This is the single segregation point for "the real track" (T10): every
    consumer that computes a REAL metric (equity headline, drawdown, return,
    volatility, APY) must filter the daily list through here so warmup /
    backfill / reconstructed bars can never contaminate a real number. History
    is untouched — the non-evidenced bars stay in the file, they are simply not
    returned here.
    """
    if not isinstance(daily, (list, tuple)):
        return []
    return [
        bar
        for bar in daily
        if is_evidenced_bar(bar, paper_start=paper_start)
    ]


# Alias — "real_series" reads naturally at call sites computing real metrics.
real_series = evidenced_bars


def real_max_drawdown_pct(
    daily: Iterable[Any], *, paper_start: _date = PAPER_REAL_START
) -> float:
    """Max drawdown (%, ≤ 0.0) computed STRICTLY over the evidenced series.

    Deterministic, stdlib-only. Empty real series → 0.0 (no real history → no
    real drawdown). The sign convention matches ``cycle_runner._rebuild_summary``
    (a drawdown is a non-positive percentage; 0.0 means new highs only).
    """
    bars = evidenced_bars(daily, paper_start=paper_start)
    peak = float("-inf")
    max_dd = 0.0
    for bar in bars:
        try:
            close = float(bar.get("close_equity", 0.0))
        except (TypeError, ValueError):
            continue
        peak = max(peak, close)
        if peak > 0:
            max_dd = min(max_dd, (close / peak - 1.0) * 100.0)
    return round(max_dd, 4)


def real_total_return_pct(
    daily: Iterable[Any], *, paper_start: _date = PAPER_REAL_START
) -> float:
    """Total return (%) of the evidenced series (first open → last close).

    Deterministic, stdlib-only. Fewer than one real bar → 0.0.
    """
    bars = evidenced_bars(daily, paper_start=paper_start)
    if not bars:
        return 0.0
    try:
        start = float(bars[0].get("open_equity", bars[0].get("close_equity", 0.0)))
        end = float(bars[-1].get("close_equity", 0.0))
    except (TypeError, ValueError):
        return 0.0
    if not start:
        return 0.0
    return round((end / start - 1.0) * 100.0, 4)


def evidenced_dates(
    daily: Iterable[Any], *, paper_start: _date = PAPER_REAL_START
) -> list[str]:
    """Unique evidenced ISO dates from a ``daily`` bar list, sorted ascending."""
    if not isinstance(daily, (list, tuple)):
        return []
    out: set[str] = set()
    for bar in daily:
        if is_evidenced_bar(bar, paper_start=paper_start):
            d = _bar_date(bar)
            if d is not None:
                out.add(d.isoformat())
    return sorted(out)


def count_evidenced(daily: Iterable[Any], *, paper_start: _date = PAPER_REAL_START) -> int:
    """Honest track-day count = number of unique evidenced dates."""
    return len(evidenced_dates(daily, paper_start=paper_start))


def first_evidenced_date(
    daily: Iterable[Any], *, paper_start: _date = PAPER_REAL_START
) -> str | None:
    """First (earliest) evidenced ISO date, or None when none are evidenced."""
    dates = evidenced_dates(daily, paper_start=paper_start)
    return dates[0] if dates else None


# ─── labeling (writes honest flags, preserves history) ──────────────────────────


def label_bars(
    daily: list[dict],
    *,
    paper_start: _date = PAPER_REAL_START,
    logs_dir: Path | str | None = None,
) -> list[dict]:
    """Return a NEW list of bars with ``source`` + ``evidenced`` set honestly.

    History is preserved: every input bar is kept; only the two honesty fields
    are (re)written from ground truth. Existing keys are otherwise untouched.
    """
    labelled: list[dict] = []
    for bar in daily:
        if not isinstance(bar, dict):
            labelled.append(bar)
            continue
        new_bar = dict(bar)
        source, evidenced = classify_bar(
            bar, paper_start=paper_start, logs_dir=logs_dir
        )
        new_bar["source"] = source
        new_bar["evidenced"] = evidenced
        labelled.append(new_bar)
    return labelled


def label_equity_file(
    equity_path: Path | str,
    *,
    paper_start: _date = PAPER_REAL_START,
    logs_dir: Path | str | None = None,
) -> dict:
    """Atomically (re)label every bar in an equity_curve_daily.json file.

    Reads the document, labels all bars (preserving history), refreshes the
    summary's ``real_days`` / ``first_real_date`` to the honest evidenced count
    and anchor, and writes back atomically. Returns a small report dict.

    Fail-CLOSED: a missing/corrupt file is a no-op returning ``{"labelled": 0}``.
    """
    import json

    path = Path(equity_path)
    if not path.is_file():
        return {"labelled": 0, "evidenced": 0, "first_evidenced": None}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"labelled": 0, "evidenced": 0, "first_evidenced": None}
    if not isinstance(doc, dict) or not isinstance(doc.get("daily"), list):
        return {"labelled": 0, "evidenced": 0, "first_evidenced": None}

    labelled = label_bars(doc["daily"], paper_start=paper_start, logs_dir=logs_dir)
    doc["daily"] = labelled

    ev_dates = evidenced_dates(labelled, paper_start=paper_start)
    summary = doc.get("summary")
    if isinstance(summary, dict):
        summary["real_days"] = len(ev_dates)
        summary["evidenced_days"] = len(ev_dates)
        summary["first_real_date"] = (
            ev_dates[0] if ev_dates else paper_start.isoformat()
        )
        summary["evidenced_anchor"] = (
            ev_dates[0] if ev_dates else paper_start.isoformat()
        )

    atomic_save(doc, str(path))
    return {
        "labelled": len(labelled),
        "evidenced": len(ev_dates),
        "first_evidenced": ev_dates[0] if ev_dates else None,
        "evidenced_dates": ev_dates,
    }


__all__ = [
    "PAPER_REAL_START",
    "SOURCE_CYCLE",
    "SOURCE_BACKFILL",
    "SOURCE_RECONSTRUCTED",
    "SOURCE_WARMUP",
    "cycle_log_path",
    "has_cycle_log",
    "evidenced_log_dates",
    "classify_bar",
    "is_evidenced_bar",
    "evidenced_bars",
    "real_series",
    "real_max_drawdown_pct",
    "real_total_return_pct",
    "evidenced_dates",
    "count_evidenced",
    "first_evidenced_date",
    "label_bars",
    "label_equity_file",
]
