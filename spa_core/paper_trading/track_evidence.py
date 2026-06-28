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

import math
import re
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from spa_core.utils.atomic import atomic_save

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LOGS_DIR = _REPO_ROOT / "logs"

# Minimum evidenced daily *returns* (one fewer than bars) required before a
# risk-adjusted metric (Sharpe/Sortino) is considered statistically meaningful.
# Below this the metric is THIN/UNKNOWN (returns None) — a 5-bar Sharpe on a
# near-zero-vol stablecoin book degenerates to a huge/meaningless number, so we
# refuse to report it rather than fabricate a degenerate value (fail-CLOSED).
MIN_EVIDENCED_RETURNS_FOR_SHARPE = 20

# Trading-day annualization factor for a daily-cadence yield book (matches
# analytics.sharpe.calculate_sharpe, which uses sqrt(365)).
_ANNUALIZATION_DAYS = 365.0

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


def is_evidenced_bar(
    bar: Any,
    *,
    paper_start: _date = PAPER_REAL_START,
    today: _date | None = None,
) -> bool:
    """Counting predicate (reads the bar's OWN labels — no filesystem access).

    A bar counts toward the honest track iff:
      * dated >= ``paper_start``; AND
      * dated <= ``today`` when ``today`` is given (FUTURE-DATED bars never
        count — a bar dated after the current UTC day cannot evidence a cycle
        that has not run yet; this keeps the day-count monotone and prevents a
        stray future date from over-counting the track); AND
      * not reconstructed / warmup / seed; AND
      * not explicitly ``evidenced: false`` (backfill) and not
        ``source`` in {backfill, reconstructed, warmup}.

    Backward-compat: ``today`` defaults to None (no future guard), so existing
    callers/fixtures are unaffected; a bar with NO explicit honesty label
    (legacy/synthetic) is still treated as evidenced. Only an explicit negative
    label (or a future date when guarded) excludes it.
    """
    if not isinstance(bar, dict):
        return False
    d = _bar_date(bar)
    if d is None or d < paper_start:
        return False
    if today is not None and d > today:
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


def _evidenced_closes(
    daily: Iterable[Any], *, paper_start: _date = PAPER_REAL_START
) -> list[float]:
    """Finite, positive close-equity series over the EVIDENCED bars, in order.

    Non-finite / non-positive closes are dropped as no-data (never fabricate a
    return). Used by the risk-adjusted metrics below.
    """
    closes: list[float] = []
    for bar in evidenced_bars(daily, paper_start=paper_start):
        try:
            c = float(bar.get("close_equity", bar.get("equity", 0.0)))
        except (TypeError, ValueError):
            continue
        if math.isfinite(c) and c > 0:
            closes.append(c)
    return closes


def evidenced_daily_returns(
    daily: Iterable[Any], *, paper_start: _date = PAPER_REAL_START
) -> list[float]:
    """Fractional day-over-day returns over the EVIDENCED series.

    Deterministic, stdlib-only. Pairs with a non-positive base are skipped.
    Warmup / backfill / reconstructed bars never enter the series, so the
    returns can never be contaminated by the pre-anchor discontinuity.
    """
    closes = _evidenced_closes(daily, paper_start=paper_start)
    out: list[float] = []
    for prev, cur in zip(closes, closes[1:]):
        if prev > 0:
            out.append(cur / prev - 1.0)
    return out


def real_sharpe_ratio(
    daily: Iterable[Any],
    *,
    paper_start: _date = PAPER_REAL_START,
    risk_free_rate: float = 0.0,
    min_returns: int = MIN_EVIDENCED_RETURNS_FOR_SHARPE,
) -> float | None:
    """Annualized Sharpe over the EVIDENCED daily returns, or ``None`` (THIN).

    HONEST / fail-CLOSED: returns ``None`` when there are fewer than
    ``min_returns`` evidenced daily returns (the metric stays THIN/UNKNOWN
    rather than reporting a degenerate small-sample Sharpe), or when the return
    dispersion is degenerate (std ≈ 0 → undefined). Mirrors the formula of
    :func:`spa_core.analytics.sharpe.calculate_sharpe` but is segregated to the
    evidenced series so warmup/backfill bars can never inflate it.
    """
    returns = evidenced_daily_returns(daily, paper_start=paper_start)
    n = len(returns)
    if n < max(2, int(min_returns)):
        return None
    rf_daily = risk_free_rate / _ANNUALIZATION_DAYS
    excess = [r - rf_daily for r in returns]
    mean = sum(excess) / n
    variance = sum((x - mean) ** 2 for x in excess) / (n - 1)
    std = math.sqrt(variance)
    if std <= 1e-12 or not math.isfinite(std):
        return None
    sharpe = mean / std * math.sqrt(_ANNUALIZATION_DAYS)
    return round(sharpe, 4) if math.isfinite(sharpe) else None


def real_sortino_ratio(
    daily: Iterable[Any],
    *,
    paper_start: _date = PAPER_REAL_START,
    risk_free_rate: float = 0.0,
    min_returns: int = MIN_EVIDENCED_RETURNS_FOR_SHARPE,
) -> float | None:
    """Annualized Sortino over the EVIDENCED daily returns, or ``None`` (THIN).

    Like :func:`real_sharpe_ratio` but the denominator is downside deviation
    (only sub-target returns penalized). Fail-CLOSED: ``None`` below
    ``min_returns`` evidenced returns or when there is no downside dispersion
    (a strictly non-decreasing book has undefined Sortino → ``None`` rather than
    a fabricated +inf).
    """
    returns = evidenced_daily_returns(daily, paper_start=paper_start)
    n = len(returns)
    if n < max(2, int(min_returns)):
        return None
    rf_daily = risk_free_rate / _ANNUALIZATION_DAYS
    excess = [r - rf_daily for r in returns]
    mean = sum(excess) / n
    downside = [min(0.0, x) for x in excess]
    dd_var = sum(x * x for x in downside) / (n - 1)
    dd = math.sqrt(dd_var)
    if dd <= 1e-12 or not math.isfinite(dd):
        return None
    sortino = mean / dd * math.sqrt(_ANNUALIZATION_DAYS)
    return round(sortino, 4) if math.isfinite(sortino) else None


def evidenced_risk_metrics(
    daily: Iterable[Any],
    *,
    paper_start: _date = PAPER_REAL_START,
    risk_free_rate: float = 0.0,
    min_returns: int = MIN_EVIDENCED_RETURNS_FOR_SHARPE,
) -> dict[str, Any]:
    """Bundle of evidenced risk-adjusted metrics for persistence on the track.

    Returns a JSON-serialisable dict with ``sharpe`` / ``sortino`` (float or
    ``None`` when THIN), the evidenced ``n_returns`` actually used, the
    ``min_returns`` gate, and a ``status`` of ``"OK"`` (enough evidenced points)
    or ``"THIN"`` (not yet enough — metrics are ``None``, honest UNKNOWN).
    """
    returns = evidenced_daily_returns(daily, paper_start=paper_start)
    n = len(returns)
    thin = n < max(2, int(min_returns))
    return {
        "sharpe": None if thin else real_sharpe_ratio(
            daily, paper_start=paper_start, risk_free_rate=risk_free_rate,
            min_returns=min_returns,
        ),
        "sortino": None if thin else real_sortino_ratio(
            daily, paper_start=paper_start, risk_free_rate=risk_free_rate,
            min_returns=min_returns,
        ),
        "n_returns": n,
        "min_returns": int(min_returns),
        "risk_free_rate": float(risk_free_rate),
        "status": "THIN" if thin else "OK",
    }


def evidenced_dates(
    daily: Iterable[Any],
    *,
    paper_start: _date = PAPER_REAL_START,
    today: _date | None = None,
) -> list[str]:
    """Unique evidenced ISO dates from a ``daily`` bar list, sorted ascending.

    ``sorted(set(...))`` makes the count MONOTONE and order-independent: duplicate
    dates collapse to one and out-of-order input yields the same set. When
    ``today`` is given, future-dated bars are excluded (see :func:`is_evidenced_bar`)
    so a stray future date can never over-count the track.
    """
    if not isinstance(daily, (list, tuple)):
        return []
    out: set[str] = set()
    for bar in daily:
        if is_evidenced_bar(bar, paper_start=paper_start, today=today):
            d = _bar_date(bar)
            if d is not None:
                out.add(d.isoformat())
    return sorted(out)


def count_evidenced(
    daily: Iterable[Any],
    *,
    paper_start: _date = PAPER_REAL_START,
    today: _date | None = None,
) -> int:
    """Honest track-day count = number of unique evidenced dates."""
    return len(evidenced_dates(daily, paper_start=paper_start, today=today))


def first_evidenced_date(
    daily: Iterable[Any],
    *,
    paper_start: _date = PAPER_REAL_START,
    today: _date | None = None,
) -> str | None:
    """First (earliest) evidenced ISO date, or None when none are evidenced."""
    dates = evidenced_dates(daily, paper_start=paper_start, today=today)
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
    # Evidenced risk-adjusted metrics (Sharpe/Sortino) on the REAL series.
    # Persisted so every consumer reads the ONE honest value; THIN (None) until
    # MIN_EVIDENCED_RETURNS_FOR_SHARPE evidenced returns accrue (fail-CLOSED).
    risk = evidenced_risk_metrics(labelled, paper_start=paper_start)
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
        summary["evidenced_sharpe"] = risk["sharpe"]
        summary["evidenced_sortino"] = risk["sortino"]
        summary["evidenced_risk_status"] = risk["status"]
        summary["evidenced_risk_n_returns"] = risk["n_returns"]

    atomic_save(doc, str(path))
    return {
        "labelled": len(labelled),
        "evidenced": len(ev_dates),
        "first_evidenced": ev_dates[0] if ev_dates else None,
        "evidenced_dates": ev_dates,
        "evidenced_sharpe": risk["sharpe"],
        "evidenced_sortino": risk["sortino"],
        "evidenced_risk_status": risk["status"],
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
    "evidenced_daily_returns",
    "real_sharpe_ratio",
    "real_sortino_ratio",
    "evidenced_risk_metrics",
    "MIN_EVIDENCED_RETURNS_FOR_SHARPE",
    "evidenced_dates",
    "count_evidenced",
    "first_evidenced_date",
    "label_bars",
    "label_equity_file",
]
