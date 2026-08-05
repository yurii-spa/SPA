#!/usr/bin/env python3
"""Observability for the OFF-SITE backup of the live paper-trading track.

Why this module exists
======================
``cycle_runner._default_track_persister`` runs the off-site backup
(``spa_core/persistence/backup.py`` — a dated folder on iCloud Drive /
``$SPA_BACKUP_DIR``) and records its outcome into
``data/track_persist_status.json`` as ``backup_status`` / ``backup_errors``.

Measured 2026-08-05 (grep over the whole tree, ``attic/`` and
``scripts/archive/`` excluded): those two keys had **two writers and zero
readers**. The refusal was recorded honestly (invariant #2) and looked at by
nobody — the mirror image of the fail-OPEN monitor class: not "OK about a check
that never ran", but "a real failure nobody ever reads". The subject is the
last line of recovery for the live track, and it can go missing for weeks with
the only trace being a field in a JSON file.

The neighbouring flag ``track_persist_ok`` IS read (``system_health_monitor``),
but it is **deliberately decoupled** from the backup: the local SQLite mirror is
the machine's crash-recovery copy and must succeed independently of the off-site
copy (docstring, ``cycle_runner.py`` ``_default_track_persister``). That
decoupling is correct and is NOT touched here — this module adds a signal
*beside* ``mirror_ok``, it never overrides it.

Design
======
* Pure and deterministic. ``now`` is an argument, never ambient state — a
  freshness judgement whose clock cannot be injected is untestable by
  construction (``.claude/rules/deployment.md``).
* Fail-CLOSED (invariant #2). "Not measured" is a distinct outcome from "ok":
  a missing / unreadable / key-less / undateable / stale snapshot yields
  ``UNCHECKED``, never a silent green. An unrecognised ``backup_status`` value
  is quoted VERBATIM rather than bucketed into a guess.
* Verbatim reasons. Whatever ``backup_errors`` holds is carried through
  unchanged; this module never rewrites a producer's words into "something went
  wrong".
* No escalation. The verdict is a monitoring severity and nothing else. It does
  not reach the kill-switch: ``threat_reactor`` reads ``peg_report.json`` /
  ``red_flags.json`` / ``emergency_status.json`` and never
  ``system_health.json`` (verified 2026-08-05). A missing off-site copy is an
  operations failure, not a market event.
* stdlib only; nothing here touches the backup root itself — enumerating it is
  exactly the call that stalls (see ``backup.py``, probe rationale), and a
  monitor that hangs is worse than no monitor.

Day history
===========
``track_persist_status.json`` is a SNAPSHOT: every cycle overwrites it. One
snapshot cannot answer "has this been failing for a week?", and the acceptance
criteria require a series signal. The day map is therefore accumulated by the
caller and stored inside the report the monitor ALREADY writes
(``data/system_health.json`` → ``offsite_backup_days``) — the monitor's
documented contract is that ``system_health.json`` is the only file it writes,
and adding a second state file would break it.

Days are keyed by the snapshot's own ``ts`` (the cycle the snapshot describes),
NOT by the monitor's run day: the monitor runs twice a day and may skip runs,
and attributing an observation to the wrong day would invent history.

A day nobody observed is a HOLE, not a pass and not a failure: the streak walk
stops at it and names it. That is the difference between "failed 3 days in a
row" and "failed on two days I happened to look at".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# Severity vocabulary — the plain strings ``system_health_monitor`` uses. They
# are restated (not imported) because the monitor imports THIS module; importing
# back would be circular. A test pins the two against each other.
CRITICAL = "CRITICAL"
WARNING = "WARNING"
OK = "OK"

STATUS_FILENAME = "track_persist_status.json"

# Observation states.
STATE_OK = "ok"
STATE_FAILED = "failed"
STATE_UNCHECKED = "unchecked"

# Freshness window for the snapshot, in hours. The producer is the daily cycle
# (one run per day), so the same 26h window the monitor already uses for
# ``paper_trading_status`` (STATUS_FRESH_H) — one cadence plus slack. Beyond it
# the snapshot describes a day that is over: an "ok" from it is not evidence
# about today, and publishing it as today's green would be precisely the
# fail-OPEN this module exists to close.
SNAPSHOT_FRESH_H = 26.0

# CRITICAL threshold for consecutive OBSERVED failing days.
#
# Chosen from a measurement, not for roundness. The backup is a FULL copy (not
# incremental) and rotation keeps 14 dated folders, so a single missed day loses
# nothing permanently — the next day's run restores the off-site copy in full.
# What matters is a PERSISTENT condition. The stall that motivates this signal
# is intermittent and was observed on two consecutive days (2026-08-04 and
# 2026-08-05) at the same root — and on the second day it parked on a different
# syscall family than on the first (``backup.py`` probe rationale). Two
# consecutive failures therefore sit INSIDE the measured intermittency envelope;
# three is the first count that does not, i.e. the smallest number that means
# "this is a condition, not a hiccup".
FAIL_STREAK_CRITICAL_DAYS = 3

# Retained days in the day map. Matches the monitor's own ``_HISTORY_MAX`` and
# comfortably exceeds both the 14-folder rotation and the streak threshold.
HISTORY_MAX_DAYS = 30

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_day(value: Any) -> bool:
    """A day key must be well-formed AND a real calendar date.

    The shape alone is not enough: ``"9999-99-99"`` matches the pattern and then
    explodes in ``date.fromisoformat`` deep inside the streak walk — a crash in
    a health check triggered by nothing but a corrupt carry-over.
    """
    if not (isinstance(value, str) and _DAY_RE.match(value)):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


# How many verbatim error strings are inlined into the one-line title. The FULL
# list always survives in ``evidence``; this only bounds the headline.
_TITLE_ERRORS = 2


# ---------------------------------------------------------------------------
# Data carriers
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Observation:
    """What a single ``track_persist_status.json`` snapshot tells us."""

    state: str                                   # STATE_OK / STATE_FAILED / STATE_UNCHECKED
    day: Optional[str] = None                    # ISO date the snapshot describes
    errors: tuple = ()                           # verbatim ``backup_errors``
    reason: str = ""                             # verbatim why (esp. for UNCHECKED)
    age_hours: Optional[float] = None
    raw_status: Any = None                       # verbatim ``backup_status``
    # What this snapshot says about ITS OWN day, which is not always what it
    # says about TODAY. A stale snapshot is UNCHECKED as a statement about now,
    # yet it remains a genuine observation of the day it describes — that day
    # belongs in the series. ``None`` means the day was not measured at all.
    day_state: Optional[str] = None


@dataclass(frozen=True)
class Streak:
    """Consecutive OBSERVED failing days, walking back from the newest day."""

    days: int = 0
    stopped_by: str = "no observations"
    last_day: Optional[str] = None


@dataclass(frozen=True)
class Verdict:
    severity: str = OK
    title: str = ""
    unchecked: bool = False
    evidence: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Reading the snapshot
# ---------------------------------------------------------------------------
def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except Exception:                              # noqa: BLE001 — parsing must never raise
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _unchecked(reason: str, **kw) -> Observation:
    return Observation(state=STATE_UNCHECKED, reason=reason, **kw)


def read_observation(data_dir: str | Path, *, now: Optional[datetime] = None) -> Observation:
    """Read the off-site backup outcome from ``track_persist_status.json``.

    Never raises. Every path that cannot produce a trustworthy verdict returns
    ``STATE_UNCHECKED`` carrying the verbatim reason — a silent green is not
    among the outcomes.
    """
    now = now or datetime.now(timezone.utc)
    path = Path(data_dir) / STATUS_FILENAME

    try:
        if not path.exists():
            return _unchecked(f"{STATUS_FILENAME} missing")
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:                       # noqa: BLE001 — a monitor never dies on input
        return _unchecked(f"{STATUS_FILENAME} unreadable: {type(exc).__name__}: {exc}")

    if not isinstance(doc, dict):
        return _unchecked(
            f"{STATUS_FILENAME} is not a JSON object (got {type(doc).__name__})")

    if "backup_status" not in doc:
        keys = ", ".join(sorted(str(k) for k in doc)) or "<none>"
        return _unchecked(
            f"{STATUS_FILENAME} has no 'backup_status' key (keys present: {keys})")

    raw = doc.get("backup_status")
    raw_errors = doc.get("backup_errors")
    errors = tuple(str(e) for e in raw_errors) if isinstance(raw_errors, list) else ()

    stamp = _parse_ts(doc.get("ts"))
    day = stamp.astimezone(timezone.utc).date().isoformat() if stamp else None
    age_h = round((now - stamp).total_seconds() / 3600.0, 2) if stamp else None

    # Unrecognised value: quote it verbatim rather than guess which bucket it
    # belongs to. "ok" and "error" are what the producer writes today; anything
    # else means the contract moved and we have NOT measured the backup.
    if not isinstance(raw, str) or raw.strip().lower() not in (STATE_OK, "error"):
        return _unchecked(
            f"{STATUS_FILENAME} backup_status is not a recognised value: {raw!r}",
            day=day, errors=errors, age_hours=age_h, raw_status=raw)

    failed = raw.strip().lower() == "error"

    if stamp is None:
        # Undateable snapshot. A recorded FAILURE is still a measured failure —
        # it just cannot join the day series, and that limit is stated instead
        # of hidden. A recorded SUCCESS, however, cannot be trusted as today's:
        # an "ok" of unknown age is exactly the stale green this module closes.
        reason = f"{STATUS_FILENAME} carries no usable 'ts': {doc.get('ts')!r}"
        if failed:
            return Observation(state=STATE_FAILED, day=None, errors=errors,
                               reason=reason + " — day unknown, cannot join the series",
                               raw_status=raw)
        return _unchecked(reason, errors=errors, raw_status=raw)

    day_state = STATE_FAILED if failed else STATE_OK

    if age_h is not None and age_h > SNAPSHOT_FRESH_H:
        # Stale: the day it describes is over. The observation still joins the
        # day map (it IS a real observation of THAT day, via ``day_state``), but
        # today's verdict is "not measured" — not "ok", and not an escalation
        # either: a dead cycle is a different alarm, owned by other checks.
        return _unchecked(
            f"{STATUS_FILENAME} is {age_h:.1f}h old (> {SNAPSHOT_FRESH_H}h) — "
            f"describes {day}, backup_status={raw!r}",
            day=day, errors=errors, age_hours=age_h, raw_status=raw,
            day_state=day_state)

    return Observation(state=day_state, day=day, errors=errors, reason=raw,
                       age_hours=age_h, raw_status=raw, day_state=day_state)


# ---------------------------------------------------------------------------
# Day history
# ---------------------------------------------------------------------------
def sanitize_history(history: Any) -> dict:
    """Keep only well-formed ``YYYY-MM-DD -> {state: ok|failed}`` entries.

    A malformed carry-over must not be able to invent a streak, and must not
    crash the monitor either.
    """
    out: dict = {}
    if not isinstance(history, dict):
        return out
    for k, v in history.items():
        if not _is_day(k):
            continue
        if not isinstance(v, dict):
            continue
        state = v.get("state")
        if state not in (STATE_OK, STATE_FAILED):
            continue
        entry: dict = {"state": state}
        errs = v.get("errors")
        if isinstance(errs, list) and errs:
            entry["errors"] = [str(e) for e in errs]
        out[k] = entry
    return dict(sorted(out.items())[-HISTORY_MAX_DAYS:])


def merge_day(history: Any, obs: Observation) -> dict:
    """Fold one observation into the day map.

    Only a DATED observation that actually measured its day is recorded — see
    ``Observation.day_state``. A day we could not measure stays a HOLE, because
    otherwise the streak would silently bridge across days nobody looked at.
    """
    out = sanitize_history(history)
    if _is_day(obs.day) and obs.day_state in (STATE_OK, STATE_FAILED):
        entry: dict = {"state": obs.day_state}
        if obs.errors:
            entry["errors"] = list(obs.errors)
        out[obs.day] = entry
    return dict(sorted(out.items())[-HISTORY_MAX_DAYS:])


def failure_streak(history: Any) -> Streak:
    """Consecutive FAILED days walking back from the newest observed day.

    Stops — and says why — at the first day that is ``ok``, unobserved, or
    before the retained window. The stop reason is part of the answer: "2 days,
    stopped by an unobserved day" is a different claim from "2 days, stopped by
    a good day", and collapsing them would overstate what was measured.
    """
    hist = sanitize_history(history)
    if not hist:
        return Streak(0, "no observations", None)

    days = sorted(hist)
    newest = days[-1]
    if hist[newest]["state"] != STATE_FAILED:
        return Streak(0, "newest observed day is ok", newest)

    oldest = days[0]
    cur = datetime.fromisoformat(newest).date()
    floor = datetime.fromisoformat(oldest).date()
    n = 0
    while True:
        key = cur.isoformat()
        entry = hist.get(key)
        if entry is None:
            return Streak(n, f"unobserved day {key}", newest)
        if entry["state"] != STATE_FAILED:
            return Streak(n, f"ok day {key}", newest)
        n += 1
        if cur <= floor:
            return Streak(n, "start of retained history", newest)
        cur = cur - timedelta(days=1)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------
def _verbatim(errors) -> str:
    if not errors:
        return "no reason recorded in backup_errors"
    head = list(errors)[:_TITLE_ERRORS]
    text = "; ".join(head)
    if len(errors) > len(head):
        text += f" (+{len(errors) - len(head)} more)"
    return text


def evaluate(obs: Observation, history: Any) -> Verdict:
    """Turn one observation plus the day map into a monitoring verdict.

    ``history`` is expected to ALREADY include ``obs`` (call ``merge_day``
    first) so the streak counts today.
    """
    streak = failure_streak(history)
    evidence = {
        "day": obs.day,
        "snapshot_age_hours": obs.age_hours,
        "backup_status": obs.raw_status,
        "backup_errors": list(obs.errors),
        "streak_days": streak.days,
        "streak_stopped_by": streak.stopped_by,
        "streak_threshold_days": FAIL_STREAK_CRITICAL_DAYS,
        "observed_days": len(sanitize_history(history)),
    }

    if obs.state == STATE_UNCHECKED:
        return Verdict(WARNING, f"off-site track backup UNCHECKED — {obs.reason}",
                       unchecked=True, evidence=evidence)

    if obs.state == STATE_FAILED:
        why = _verbatim(obs.errors)
        if streak.days >= FAIL_STREAK_CRITICAL_DAYS:
            return Verdict(
                CRITICAL,
                f"off-site track backup FAILED {streak.days} observed days in a row "
                f"(>= {FAIL_STREAK_CRITICAL_DAYS}) — the newest off-site copy of the "
                f"live track is at least {streak.days}d old: {why}",
                evidence=evidence)
        tail = f" ({streak.days} observed days in a row)" if streak.days > 1 else ""
        day = f" on {obs.day}" if obs.day else " (day unknown)"
        return Verdict(WARNING,
                       f"off-site track backup FAILED{day}{tail}: {why}",
                       evidence=evidence)

    return Verdict(OK, f"off-site track backup ok ({obs.day})", evidence=evidence)


def assess(data_dir: str | Path, prev_history: Any,
           *, now: Optional[datetime] = None) -> tuple[Verdict, dict]:
    """One-shot: read → merge → evaluate. Returns ``(verdict, new_history)``."""
    obs = read_observation(data_dir, now=now)
    history = merge_day(prev_history, obs)
    return evaluate(obs, history), history
