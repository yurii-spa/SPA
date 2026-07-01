#!/usr/bin/env python3
"""Track-continuity self-heal (RISKWIRE WS1.1, 2026-07-01).

The go-live thesis rests on ONE artifact: a continuous 30-day *evidenced* track in
``data/equity_curve_daily.json``. That file is (owner-gated) git-tracked, so a
``git reset --hard origin/main`` / branch-checkout / merge can clobber the live
local curve with a STALE committed copy — silently dropping days whose real
``daily_cycle`` already ran (the 2026-06-27/28/29 incident: three genuinely
evidenced bars were lost when the working tree was reset to ``origin/main``). The
daily append path (:func:`equity._upsert_equity_point`) only ever appends *today*
onto the last bar — it never re-scans for a gap — so a lost day becomes a
PERMANENT hole that freezes ``real_track_days`` and slips day-30 indefinitely.

This module closes that hole. Each cycle (and via the gap/cycle monitor) it:

  1. DETECTS any day that has GROUND-TRUTH evidence a real cycle ran — a
     ``logs/daily_cycle_YYYYMMDD.log`` with the canonical cycle header AND a
     recorded ``MP-416 evidence recorded: … equity=…`` line — but has NO
     evidenced bar in the equity curve; then
  2. RECOVERS that day's bar from the log's recorded equity value, chained
     continuously off the prior bar's close (``open = prev_close``), labelled
     ``source="cycle"``, ``evidenced=true``, ``recovered_from="self_heal"`` so the
     provenance is explicit and auditable.

Fail-CLOSED, by construction:
  * A day with NO real cycle log is NEVER recovered — it stays absent (honest).
  * A day with a log but NO parseable ``MP-416 … equity=`` value is NOT recovered
    (no fabricated equity — we refuse rather than invent a number).
  * Recovery never DROPS or mutates a pre-existing evidenced bar; it only inserts
    the missing ones and re-sorts by date.
  * A future-dated log (date > ``today``) is never recovered.

Stdlib only. Deterministic (no LLM, no randomness, no network). Atomic writes.
The recovered equity value comes verbatim from the real cycle log — it is not
computed, interpolated, or invented; the log IS the evidence.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spa_core.paper_trading._cycle_io import (
    CAPITAL_USD,
    EQUITY_FILENAME,
    MAX_EQUITY_POINTS,
)
from spa_core.paper_trading.equity import _rebuild_summary
from spa_core.paper_trading.track_evidence import (
    PAPER_REAL_START,
    cycle_log_path,
    evidenced_dates,
    has_cycle_log,
)
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.track_self_heal")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_DEFAULT_LOGS_DIR = _REPO_ROOT / "logs"

# Canonical evidence line every real cycle emits (cycle_reporting.py MP-416):
#   "INFO spa.cycle_runner: MP-416 evidence recorded: date=2026-06-27 apy=4.1656% equity=100201.66"
_EVIDENCE_RE = re.compile(
    r"MP-416 evidence recorded:\s*date=(?P<date>\d{4}-\d{2}-\d{2})\s+"
    r"apy=(?P<apy>-?\d+(?:\.\d+)?)%\s+equity=(?P<equity>-?\d+(?:\.\d+)?)"
)


# ── log parsing (the evidence source) ───────────────────────────────────────────


def parse_cycle_log_equity(
    d: _date, logs_dir: Path | str | None = None
) -> tuple[float, float] | None:
    """Return ``(equity, apy_pct)`` recorded for date ``d`` in its cycle log.

    Reads the day's ``logs/daily_cycle_YYYYMMDD.log`` and extracts the recorded
    ``MP-416 evidence recorded: … equity=…`` value FOR THAT DATE. A cycle log may
    contain several runs (the file can accumulate multiple same-day runs, and a
    log named for day *N* may also carry a late day *N-1* run); we therefore match
    ONLY lines whose embedded ``date=`` equals ``d`` and take the LAST such line —
    the final recorded state for that day.

    Fail-CLOSED: returns ``None`` when the log is missing, unreadable, or contains
    no matching evidence line for ``d`` (never invents a value).
    """
    if not has_cycle_log(d, logs_dir):
        return None
    path = cycle_log_path(d, logs_dir)
    iso = d.isoformat()
    equity: float | None = None
    apy: float = 0.0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "MP-416 evidence recorded" not in line:
                    continue
                m = _EVIDENCE_RE.search(line)
                if not m or m.group("date") != iso:
                    continue
                try:
                    equity = float(m.group("equity"))
                    apy = float(m.group("apy"))
                except ValueError:
                    continue
    except OSError:
        return None
    if equity is None:
        return None
    return equity, apy


# ── detection ───────────────────────────────────────────────────────────────────


def _load_equity_doc(equity_path: Path) -> dict | None:
    if not equity_path.is_file():
        return None
    try:
        doc = json.loads(equity_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("daily"), list):
        return None
    return doc


def _bar_dates(daily: list) -> set[str]:
    out: set[str] = set()
    for b in daily:
        if isinstance(b, dict):
            v = b.get("date")
            if isinstance(v, str) and v:
                out.add(v[:10])
    return out


def detect_missing_evidenced_days(
    equity_doc: dict,
    *,
    paper_start: _date = PAPER_REAL_START,
    logs_dir: Path | str | None = None,
    today: _date | None = None,
) -> list[str]:
    """ISO dates that have real cycle-log evidence but NO bar in the curve.

    A day is "missing-but-evidenced" iff it is >= ``paper_start``, <= ``today``,
    it has a real cycle log with a parseable ``MP-416 … equity=`` line, and there
    is NO equity bar for that date at all. These are the days the self-heal will
    recover. Ordered ascending so recovery chains continuously.

    Fail-CLOSED: a log-less day, or a log with no parseable equity, is not
    returned (never recovered).
    """
    if today is None:
        today = datetime.now(timezone.utc).date()
    daily = equity_doc.get("daily") if isinstance(equity_doc, dict) else None
    if not isinstance(daily, list):
        daily = []
    present = _bar_dates(daily)

    base = Path(logs_dir) if logs_dir is not None else _DEFAULT_LOGS_DIR
    missing: list[str] = []
    if not base.is_dir():
        return missing
    for p in base.glob("daily_cycle_*.log"):
        m = re.search(r"daily_cycle_(\d{8})\.log$", p.name)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if d < paper_start or d > today:
            continue
        if d.isoformat() in present:
            continue  # a bar already exists for this day (evidenced or not)
        # No bar for this day — recover ONLY if the log carries real evidence.
        if parse_cycle_log_equity(d, base) is not None:
            missing.append(d.isoformat())
    return sorted(set(missing))


# ── recovery ────────────────────────────────────────────────────────────────────


def _make_recovered_bar(
    d_iso: str,
    equity: float,
    apy_pct: float,
    prev_close: float,
    first_open: float,
    prior_peak: float,
    positions: dict[str, float],
) -> dict:
    """Build one evidenced daily bar for a recovered day, chained off prev_close.

    The CLOSE equity is the log-recorded value (the evidence). The daily yield is
    the honest close-minus-prev delta so the curve stays internally consistent.
    """
    close_equity = round(float(equity), 2)
    open_equity = round(float(prev_close), 2)
    daily_yield = round(close_equity - open_equity, 4)
    daily_return_pct = (
        round((close_equity / prev_close - 1.0) * 100.0, 6) if prev_close else 0.0
    )
    cumulative_return_pct = (
        round((close_equity / first_open - 1.0) * 100.0, 6) if first_open else 0.0
    )
    peak = max(prior_peak, close_equity)
    drawdown_pct = round((close_equity / peak - 1.0) * 100.0, 6) if peak else 0.0
    return {
        "date": d_iso,
        "open_equity": open_equity,
        "close_equity": close_equity,
        "high_equity": round(max(open_equity, close_equity), 2),
        "low_equity": round(min(open_equity, close_equity), 2),
        "snapshots": 1,
        "daily_return_pct": daily_return_pct,
        "cumulative_return_pct": cumulative_return_pct,
        "drawdown_pct": drawdown_pct,
        "equity": close_equity,
        "apy_today": round(float(apy_pct), 4),
        "daily_yield_usd": daily_yield,
        "positions": {p: round(float(v), 2) for p, v in positions.items()},
        # Provenance: this bar was recovered from the real cycle log (the log is
        # the evidence a live cycle ran that day). Labelled evidenced so the
        # go-live track counts it honestly, and stamped so the recovery is
        # explicit and auditable (mirrors the prior honest recovery pattern).
        "source": "cycle",
        "evidenced": True,
        "recovered_from": "self_heal",
        "note": (
            "real equity recovered from logs/daily_cycle_{}.log "
            "(MP-416 evidence equity={:.2f})".format(
                d_iso.replace("-", ""), close_equity
            )
        ),
    }


# Base-drift tolerance: an ``open_equity`` that differs from the prior evidenced
# close by more than this (USD) is treated as an incident-caused base break to
# repair. A cent-level rounding difference is NOT a break.
_BASE_DRIFT_TOLERANCE_USD = 0.02


def _repair_continuity(
    by_date: dict[str, dict],
    *,
    paper_start: _date = PAPER_REAL_START,
    today: _date | None = None,
    only_after: str | None = None,
) -> list[str]:
    """Re-chain evidenced bars whose ``open_equity`` drifted off the prior close.

    Fixes the incident pattern where a real cycle accrued its (real) daily yield
    off a CLOBBERED prior close (e.g. the 06-30 bar accrued its real ~$9 yield off
    the stale 06-26 base after a git reset dropped 06-27/28/29). We preserve each
    affected bar's real ``daily_yield_usd`` (the evidence) and only correct its
    base: ``open`` becomes the true prior evidenced close, ``close = open +
    real_yield``, and the derived fields are recomputed. Mutates ``by_date`` in
    place; returns the sorted list of repaired dates.

    SCOPE GUARD (``only_after``): a repair is ONLY ever applied to a bar dated
    STRICTLY AFTER ``only_after`` — i.e. it is a downstream consequence of a day
    we just RECOVERED, never a standalone rewrite of an otherwise-untouched track.
    This is the safety invariant: absent a recovery this pass touches nothing, so
    an existing real bar can never be silently re-chained (a discontinuity with no
    recovery is left for the cycle's own continuity guard to HALT on, honestly).
    When ``only_after`` is None, no repair is performed.

    Fail-CLOSED: touches ONLY evidenced, non-future bars strictly after
    ``only_after``; a bar with no numeric ``daily_yield_usd`` is left untouched (we
    never invent yield); a bar already continuous within tolerance is untouched.
    """
    from spa_core.paper_trading.track_evidence import is_evidenced_bar

    repaired: list[str] = []
    if only_after is None:
        return repaired
    ordered = sorted(by_date)
    prev_close: float | None = None
    first_open: float | None = None
    peak = float("-inf")
    for d_iso in ordered:
        bar = by_date[d_iso]
        try:
            d = _date.fromisoformat(d_iso)
        except ValueError:
            continue
        is_ev = is_evidenced_bar(bar, paper_start=paper_start, today=today)
        if first_open is None:
            first_open = float(bar.get("open_equity", bar.get("close_equity", 0.0)))

        # Only repair bars STRICTLY AFTER a recovered day (scope guard) — never
        # rewrite a bar on an otherwise-untouched track.
        if is_ev and prev_close is not None and d_iso > only_after:
            open_eq = float(bar.get("open_equity", 0.0))
            if abs(open_eq - prev_close) > _BASE_DRIFT_TOLERANCE_USD:
                y = bar.get("daily_yield_usd")
                if isinstance(y, (int, float)) and not isinstance(y, bool):
                    new_open = round(prev_close, 2)
                    new_close = round(prev_close + float(y), 2)
                    fo = first_open if first_open else new_open
                    new_peak = max(peak if peak != float("-inf") else new_close, new_close)
                    bar["open_equity"] = new_open
                    bar["close_equity"] = new_close
                    bar["equity"] = new_close
                    bar["high_equity"] = round(max(new_open, new_close), 2)
                    bar["low_equity"] = round(min(new_open, new_close), 2)
                    bar["daily_return_pct"] = (
                        round((new_close / new_open - 1.0) * 100.0, 6) if new_open else 0.0
                    )
                    bar["cumulative_return_pct"] = (
                        round((new_close / fo - 1.0) * 100.0, 6) if fo else 0.0
                    )
                    bar["drawdown_pct"] = (
                        round((new_close / new_peak - 1.0) * 100.0, 6) if new_peak else 0.0
                    )
                    prior_note = bar.get("note") or ""
                    bar["continuity_repaired"] = True
                    bar["note"] = (
                        (prior_note + " | " if prior_note else "")
                        + "base re-chained off true prior evidenced close "
                        "(stale-restore incident); real daily_yield preserved"
                    )
                    repaired.append(d_iso)

        close = float(bar.get("close_equity", bar.get("equity", 0.0)))
        if is_ev:
            prev_close = close
            peak = max(peak, close)
    return sorted(set(repaired))


def heal_track(
    equity_path: Path | str | None = None,
    *,
    paper_start: _date = PAPER_REAL_START,
    logs_dir: Path | str | None = None,
    today: _date | None = None,
    apply: bool = True,
) -> dict:
    """Detect + recover missing-but-evidenced days in the equity curve.

    Returns a report dict::

        {
          "healed": ["2026-06-27", ...],   # dates inserted
          "refused": ["2026-07-02", ...],  # days with NO log/evidence (untouched)
          "evidenced_before": int,
          "evidenced_after": int,
          "applied": bool,                 # whether the file was written
        }

    Fail-CLOSED throughout:
      * only days returned by :func:`detect_missing_evidenced_days` (real log +
        parseable equity) are recovered;
      * a missing/corrupt equity file is a no-op (nothing to heal safely);
      * ``apply=False`` computes the plan without writing (used by red-team /
        monitors that want a dry-run).

    The recovered bars carry forward the LAST known ``positions`` map (informational
    only — the evidence is the equity value), and the summary is recomputed by the
    canonical :func:`equity._rebuild_summary` so ``real_days`` / evidenced count /
    drawdown all agree with the go-live gate.
    """
    epath = Path(equity_path) if equity_path is not None else (
        _DEFAULT_DATA_DIR / EQUITY_FILENAME
    )
    if today is None:
        today = datetime.now(timezone.utc).date()

    doc = _load_equity_doc(epath)
    if doc is None:
        return {
            "healed": [], "refused": [], "evidenced_before": 0,
            "evidenced_after": 0, "applied": False,
            "note": "equity file missing/corrupt — no-op (fail-closed)",
        }

    daily: list[dict] = [b for b in doc["daily"] if isinstance(b, dict)]
    ev_before = len(evidenced_dates(daily, paper_start=paper_start, today=today))

    missing = detect_missing_evidenced_days(
        doc, paper_start=paper_start, logs_dir=logs_dir, today=today
    )

    # Work on a date-sorted copy so we can chain each recovered bar off the
    # correct prior close and re-insert deterministically.
    by_date: dict[str, dict] = {}
    for b in daily:
        v = b.get("date")
        if isinstance(v, str) and v:
            by_date[v[:10]] = b

    last_positions: dict[str, float] = {}
    for b in sorted(daily, key=lambda x: str(x.get("date", ""))):
        pos = b.get("positions")
        if isinstance(pos, dict) and pos:
            last_positions = {k: float(v) for k, v in pos.items()
                              if isinstance(v, (int, float)) and not isinstance(v, bool)}

    healed: list[str] = []
    base = Path(logs_dir) if logs_dir is not None else _DEFAULT_LOGS_DIR
    for d_iso in missing:
        d = _date.fromisoformat(d_iso)
        parsed = parse_cycle_log_equity(d, base)
        if parsed is None:  # defensive — detect already filtered, stay fail-closed
            continue
        equity_val, apy_val = parsed

        # Chain off the most recent bar STRICTLY BEFORE this date.
        prior = [by_date[k] for k in by_date if k < d_iso]
        prior.sort(key=lambda x: str(x.get("date", "")))
        prev_close = (
            float(prior[-1].get("close_equity", prior[-1].get("equity", CAPITAL_USD)))
            if prior else CAPITAL_USD
        )
        first_open = (
            float(min((by_date[k] for k in by_date), key=lambda x: str(x.get("date")))
                  .get("open_equity", CAPITAL_USD))
            if by_date else prev_close
        )
        prior_peak = max(
            [float(b.get("close_equity", 0.0)) for b in prior] or [prev_close]
        )
        pos = last_positions
        bprior = prior[-1].get("positions") if prior else None
        if isinstance(bprior, dict) and bprior:
            pos = {k: float(v) for k, v in bprior.items()
                   if isinstance(v, (int, float)) and not isinstance(v, bool)}

        bar = _make_recovered_bar(
            d_iso, equity_val, apy_val, prev_close, first_open, prior_peak, pos
        )
        by_date[d_iso] = bar
        healed.append(d_iso)

    # ── continuity repair (base-drift from a stale-restore incident) ─────────────
    # After inserting recovered days, an EXISTING evidenced bar can still carry a
    # stale ``open_equity`` — the incident-day cycle accrued its real daily yield
    # off a CLOBBERED prior close (e.g. 2026-06-30 accrued ~$9 off the reset
    # 06-26 base 100190.22 instead of the true 06-29 close 100224.36). The daily
    # YIELD is real (the log recorded it); only the BASE is wrong. We re-chain such
    # bars forward, PRESERVING their real ``daily_yield_usd`` so the evidenced
    # daily return is untouched — we never invent yield, we only correct the base.
    # Repair is a downstream consequence of a recovery ONLY — scoped to bars
    # strictly after the earliest day we just recovered. No recovery → no repair
    # (an untouched track is never silently re-chained; a bare discontinuity is
    # left for the cycle's own continuity guard to HALT on, honestly).
    repaired = _repair_continuity(
        by_date,
        paper_start=paper_start,
        today=today,
        only_after=min(healed) if healed else None,
    )

    # Rebuild the ordered daily list and recompute the canonical summary.
    new_daily = [by_date[k] for k in sorted(by_date)]
    new_daily = new_daily[-MAX_EQUITY_POINTS:]
    ev_after = len(evidenced_dates(new_daily, paper_start=paper_start, today=today))

    report = {
        "healed": healed,
        "repaired": repaired,
        "refused": [],  # populated by callers doing an explicit no-log probe
        "evidenced_before": ev_before,
        "evidenced_after": ev_after,
        "applied": False,
    }
    if not healed and not repaired:
        report["note"] = "no missing evidenced days, no base-drift — track continuous"
        return report

    if apply:
        doc["daily"] = new_daily
        doc["summary"] = _rebuild_summary(new_daily)
        doc["generated_at"] = datetime.now(timezone.utc).isoformat()
        atomic_save(doc, str(epath))
        report["applied"] = True
        log.info(
            "track_self_heal: recovered %d day(s) %s + repaired %d base-drift %s "
            "(evidenced %d → %d) from real cycle logs",
            len(healed), healed, len(repaired), repaired, ev_before, ev_after,
        )
    return report


__all__ = [
    "parse_cycle_log_equity",
    "detect_missing_evidenced_days",
    "heal_track",
]


if __name__ == "__main__":  # pragma: no cover - manual CLI
    import argparse

    ap = argparse.ArgumentParser(description="Track-continuity self-heal (WS1.1).")
    ap.add_argument("--equity", default=None, help="equity_curve_daily.json path")
    ap.add_argument("--logs", default=None, help="logs dir (default repo logs/)")
    ap.add_argument("--dry-run", action="store_true", help="detect only, do not write")
    args = ap.parse_args()
    rep = heal_track(
        equity_path=args.equity, logs_dir=args.logs, apply=not args.dry_run
    )
    print(json.dumps(rep, indent=2))
