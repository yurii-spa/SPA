"""The off-site backup of the LIVE TRACK must be visible when it fails.

Card: ``agent-offsite-backup-refusal-is-recorded-and-unread`` (cycle #123).

What was measured on 2026-08-05 (grep over the whole tree, ``attic/`` and
``scripts/archive/`` excluded): ``backup_status`` / ``backup_errors`` had two
writers (``cycle_runner``) and ZERO readers. The refusal was recorded honestly
— invariant #2 held — and nobody ever looked at it. The subject is the last
line of recovery for the live track.

Every test below is a POSITIVE CONTROL in the sense the deployment rule asks
for: the monitor tests fail on the pre-fix tree (no ``d1.track_backup.offsite``
check exists there at all), and each module test reproduces one concrete way
the signal could lie — stale green, unknown value, invented streak, silent
carry-over loss.

Times are derived from an INJECTED ``now`` (``_BASE``) on BOTH sides — the pure
module and the monitor — so the calendar can never turn these red
(``.claude/rules/deployment.md``, "Время в тестах"). ``_BASE`` is CONSTRUCTED
rather than quoted, so no fixture here holds a literal date string.

The monitor side used to read the real clock (``_freshness.ts``) instead, and
that was not merely stylistic: two tests below asked "is the snapshot's day
TODAY?", which is false for one hour after UTC midnight, and they duly went red
at 00:28 UTC on 2026-08-09 (card
``inbox-ryad-dnei-offsite-bekapa-klyuchuetsya-lo``). Measured on the unpatched
tree by replaying that instant: the series held ``2026-08-08`` while the
assertion asked for ``2026-08-09``. **The monitor was right and the tests were
wrong** — days are keyed by the snapshot's OWN day on purpose (module docstring,
"Day history"), because the monitor runs twice a day and may skip runs. The
fix therefore pins the assertions to the fixture's own day and adds the midnight
crossing as a positive control, rather than moving the production key.

The one exception is ``test_a_domain_that_never_ran_cannot_erase_a_running_streak``,
whose subject is carry-over of an opaque day key and not freshness at all: any
well-formed day works, and pinning one keeps the assertion readable. It carries
``# FROZEN-DATE-OK`` — note the ratchet honours that marker FILE-wide, which is
why every other fixture below is derived rather than written out.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import offsite_backup_observability as ob
from spa_core.monitoring import system_health_monitor as shm

# Injected clock for the pure-module tests. Constructed, never quoted, so the
# fixtures below carry no literal date string at all.
_BASE = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)
_D0 = _BASE.date()

# The night window that broke the two monitor tests: 28 minutes past UTC
# midnight, derived from ``_BASE`` so it stays a construction and not a quoted
# date. At this instant a snapshot one hour old belongs to the PREVIOUS
# calendar day — the whole subject of the midnight controls below.
_MIDNIGHT = _BASE + timedelta(hours=12, minutes=28)

CHECK_ID = "d1.track_backup.offsite"


def day(offset: int = 0) -> str:
    return (_D0 + timedelta(days=offset)).isoformat()


def stamp(hours_ago: float = 4.0) -> str:
    return (_BASE - timedelta(hours=hours_ago)).isoformat()


def day_of(hours_ago: float) -> str:
    """The calendar day a snapshot of this age describes — derived, never
    guessed, so the assertion cannot drift from the fixture."""
    return (_BASE - timedelta(hours=hours_ago)).date().isoformat()


def write_status(ddir: Path, doc) -> Path:
    p = Path(ddir) / ob.STATUS_FILENAME
    p.write_text(json.dumps(doc) if not isinstance(doc, str) else doc,
                 encoding="utf-8")
    return p


def snapshot(status="ok", errors=None, hours_ago=4.0):
    return {
        "track_persist_ok": True,
        "mirror_ok": True,
        "reason": "ok",
        "ts": stamp(hours_ago),
        "backup_status": status,
        "backup_errors": errors or [],
    }


# ===========================================================================
# 1. A healthy day reads as healthy — and nothing more
# ===========================================================================
def test_ok_snapshot_is_ok_and_records_the_day(tmp_path):
    write_status(tmp_path, snapshot("ok"))
    verdict, history = ob.assess(tmp_path, {}, now=_BASE)
    assert verdict.severity == ob.OK
    assert verdict.unchecked is False
    assert history == {day(0): {"state": "ok"}}


# ===========================================================================
# 2. A recorded failure becomes visible — with the producer's OWN words
# ===========================================================================
def test_single_failed_day_is_a_warning_with_the_verbatim_reason(tmp_path):
    reason = "backup root unresponsive after 10.0s (Path.iterdir did not return)"
    write_status(tmp_path, snapshot("error", [reason]))
    verdict, history = ob.assess(tmp_path, {}, now=_BASE)
    assert verdict.severity == ob.WARNING
    # VERBATIM — not "something went wrong with the backup".
    assert reason in verdict.title
    assert verdict.evidence["backup_errors"] == [reason]
    assert history == {day(0): {"state": "failed", "errors": [reason]}}


def test_several_errors_are_all_kept_and_the_headline_says_how_many_more(tmp_path):
    errs = ["first failure", "second failure", "third failure"]
    write_status(tmp_path, snapshot("error", errs))
    verdict, _ = ob.assess(tmp_path, {}, now=_BASE)
    assert verdict.evidence["backup_errors"] == errs          # nothing dropped
    assert "first failure" in verdict.title
    assert "+1 more" in verdict.title                         # and nothing hidden


def test_a_failure_with_no_recorded_reason_says_so_instead_of_inventing_one(tmp_path):
    write_status(tmp_path, snapshot("error", []))
    verdict, _ = ob.assess(tmp_path, {}, now=_BASE)
    assert verdict.severity == ob.WARNING
    assert "no reason recorded in backup_errors" in verdict.title


# ===========================================================================
# 3. The SERIES signal — one bad day is not an emergency, a run of them is
# ===========================================================================
def test_two_failed_days_stay_a_warning(tmp_path):
    """Pins the threshold from below: 2 is inside the measured intermittency."""
    write_status(tmp_path, snapshot("error", ["stalled"]))
    prev = {day(-1): {"state": "failed"}}
    verdict, _ = ob.assess(tmp_path, prev, now=_BASE)
    assert verdict.severity == ob.WARNING
    assert verdict.evidence["streak_days"] == 2


def test_three_failed_days_in_a_row_are_critical(tmp_path):
    """Pins the threshold from above — and is the whole point of the card."""
    write_status(tmp_path, snapshot("error", ["stalled"]))
    prev = {day(-2): {"state": "failed"}, day(-1): {"state": "failed"}}
    verdict, _ = ob.assess(tmp_path, prev, now=_BASE)
    assert verdict.severity == ob.CRITICAL
    assert verdict.evidence["streak_days"] == ob.FAIL_STREAK_CRITICAL_DAYS == 3
    assert "3" in verdict.title


def test_a_good_day_breaks_the_streak(tmp_path):
    write_status(tmp_path, snapshot("error", ["stalled"]))
    prev = {day(-3): {"state": "failed"}, day(-2): {"state": "failed"},
            day(-1): {"state": "ok"}}
    verdict, _ = ob.assess(tmp_path, prev, now=_BASE)
    assert verdict.severity == ob.WARNING
    assert verdict.evidence["streak_days"] == 1
    assert verdict.evidence["streak_stopped_by"] == f"ok day {day(-1)}"


def test_an_unobserved_day_breaks_the_streak_and_is_named(tmp_path):
    """The difference between "failed 3 days running" and "failed on the two
    days I happened to look at". Bridging the hole would overstate the claim."""
    write_status(tmp_path, snapshot("error", ["stalled"]))
    prev = {day(-3): {"state": "failed"}, day(-2): {"state": "failed"}}   # day(-1) missing
    verdict, _ = ob.assess(tmp_path, prev, now=_BASE)
    assert verdict.severity == ob.WARNING                      # NOT critical
    assert verdict.evidence["streak_days"] == 1
    assert verdict.evidence["streak_stopped_by"] == f"unobserved day {day(-1)}"


def test_streak_is_zero_when_the_newest_observed_day_is_ok(tmp_path):
    write_status(tmp_path, snapshot("ok"))
    prev = {day(-2): {"state": "failed"}, day(-1): {"state": "failed"}}
    verdict, _ = ob.assess(tmp_path, prev, now=_BASE)
    assert verdict.severity == ob.OK
    assert verdict.evidence["streak_days"] == 0


# ===========================================================================
# 4. "Not measured" is never "ok" (class #29/#31/#35–#38, fail-CLOSED)
# ===========================================================================
def test_missing_status_file_is_unchecked_not_ok(tmp_path):
    verdict, history = ob.assess(tmp_path, {}, now=_BASE)
    assert verdict.severity == ob.WARNING and verdict.unchecked is True
    assert ob.STATUS_FILENAME in verdict.title and "missing" in verdict.title
    assert history == {}


def test_unreadable_status_file_is_unchecked_and_names_the_failure(tmp_path):
    write_status(tmp_path, "{not json at all")
    verdict, _ = ob.assess(tmp_path, {}, now=_BASE)
    assert verdict.unchecked is True
    assert "unreadable" in verdict.title
    assert "JSONDecodeError" in verdict.title                  # verbatim, not "bad file"


def test_status_file_that_is_not_an_object_is_unchecked(tmp_path):
    write_status(tmp_path, [1, 2, 3])
    verdict, _ = ob.assess(tmp_path, {}, now=_BASE)
    assert verdict.unchecked is True
    assert "not a JSON object" in verdict.title


def test_missing_backup_status_key_is_unchecked_and_lists_the_keys_present(tmp_path):
    """The exact shape of the pre-fix world: the file exists, the neighbouring
    flag is green, and the backup key simply is not there."""
    write_status(tmp_path, {"track_persist_ok": True, "ts": stamp()})
    verdict, _ = ob.assess(tmp_path, {}, now=_BASE)
    assert verdict.unchecked is True
    assert "no 'backup_status' key" in verdict.title
    assert "track_persist_ok" in verdict.title


def test_unrecognised_backup_status_is_quoted_verbatim_and_records_no_day(tmp_path):
    write_status(tmp_path, snapshot("partially-ok"))
    verdict, history = ob.assess(tmp_path, {}, now=_BASE)
    assert verdict.unchecked is True
    assert "'partially-ok'" in verdict.title
    assert history == {}      # an unmeasured day must stay a hole


def test_stale_green_is_refused_but_its_day_still_joins_the_series(tmp_path):
    """A snapshot older than the freshness window is not evidence about today.
    Publishing its "ok" as today's green is exactly the fail-OPEN this closes —
    yet the day it describes was genuinely observed and belongs in the series."""
    old = ob.SNAPSHOT_FRESH_H + 10
    write_status(tmp_path, snapshot("ok", hours_ago=old))
    verdict, history = ob.assess(tmp_path, {}, now=_BASE)
    assert verdict.severity == ob.WARNING and verdict.unchecked is True
    assert verdict.severity != ob.OK
    assert history == {day_of(old): {"state": "ok"}}


def test_stale_failure_is_unchecked_for_today_not_escalated(tmp_path):
    old = ob.SNAPSHOT_FRESH_H + 10
    write_status(tmp_path, snapshot("error", ["stalled"], hours_ago=old))
    verdict, history = ob.assess(tmp_path, {}, now=_BASE)
    assert verdict.unchecked is True
    assert verdict.severity == ob.WARNING          # a dead cycle is another check's alarm
    assert history == {day_of(old): {"state": "failed", "errors": ["stalled"]}}


def test_undateable_snapshot_with_a_failure_is_reported_but_cannot_join_the_series(tmp_path):
    doc = snapshot("error", ["stalled"])
    doc["ts"] = "not-a-date"
    write_status(tmp_path, doc)
    verdict, history = ob.assess(tmp_path, {}, now=_BASE)
    assert verdict.severity == ob.WARNING
    assert "stalled" in verdict.title              # the measured failure survives
    assert history == {}                           # the limit is stated, not hidden


def test_undateable_snapshot_claiming_ok_is_unchecked(tmp_path):
    doc = snapshot("ok")
    doc.pop("ts")
    write_status(tmp_path, doc)
    verdict, _ = ob.assess(tmp_path, {}, now=_BASE)
    assert verdict.unchecked is True               # an "ok" of unknown age proves nothing


# ===========================================================================
# 5. A corrupt carry-over cannot invent history
# ===========================================================================
@pytest.mark.parametrize("junk", [
    None, [], "history", 42,
    {"not-a-day": {"state": "failed"}},
    {"9999-99-99": {"state": "failed"}},
])
def test_malformed_history_is_discarded_rather_than_trusted(tmp_path, junk):
    write_status(tmp_path, snapshot("error", ["stalled"]))
    verdict, history = ob.assess(tmp_path, junk, now=_BASE)
    assert verdict.severity == ob.WARNING          # never escalates on garbage
    assert history == {day(0): {"state": "failed", "errors": ["stalled"]}}


def test_history_entries_with_a_bogus_state_are_dropped(tmp_path):
    write_status(tmp_path, snapshot("error", ["stalled"]))
    prev = {day(-2): {"state": "CATASTROPHE"}, day(-1): {"state": "failed"}}
    verdict, history = ob.assess(tmp_path, prev, now=_BASE)
    assert verdict.evidence["streak_days"] == 2    # not 3 — the bogus day is a hole
    assert day(-2) not in history


def test_history_is_bounded(tmp_path):
    write_status(tmp_path, snapshot("ok"))
    prev = {day(-i): {"state": "ok"} for i in range(1, ob.HISTORY_MAX_DAYS + 20)}
    _, history = ob.assess(tmp_path, prev, now=_BASE)
    assert len(history) == ob.HISTORY_MAX_DAYS
    assert day(0) in history                       # the newest day is never the one dropped


# ===========================================================================
# 6. The monitor actually reads it — positive controls against the pre-fix tree
# ===========================================================================
def _monitor(tmp_path, now: datetime = _BASE) -> shm.SystemHealthMonitor:
    """The monitor with its clock INJECTED — never the ambient one.

    ``now`` reaches only the off-site check (``SystemHealthMonitor.__init__``);
    everything else in d1 keeps the real clock, which is fine because nothing
    below asserts on it.
    """
    return shm.SystemHealthMonitor(data_dir=tmp_path, project_root=tmp_path,
                                   now=now)


def _d1(mon):
    mon._prev_cache = mon._load_previous()
    mon._prelude()
    return {c.id: c for c in mon.check_d1_data_pipeline()}


def live_snapshot(status="ok", errors=None, hours_ago=1.0, now: datetime = _BASE):
    """A snapshot ``hours_ago`` before the instant the monitor will be given.

    Both sides come from the same ``now``, so the age is pinned and so is the
    day the snapshot describes (``snapshot_day`` below reads it back).
    """
    return {"track_persist_ok": True, "mirror_ok": True, "reason": "ok",
            "ts": (now - timedelta(hours=hours_ago)).isoformat(),
            "backup_status": status, "backup_errors": errors or []}


def snapshot_day(hours_ago: float = 1.0, now: datetime = _BASE) -> str:
    """The day ``live_snapshot`` just wrote — DERIVED from the same instant.

    Asking instead for "today" is the defect this file was red on: for one hour
    after UTC midnight the snapshot's day and the run day are different days.
    """
    return (now - timedelta(hours=hours_ago)).date().isoformat()


def test_monitor_publishes_a_failed_offsite_backup(tmp_path):
    """POSITIVE CONTROL. On the pre-fix tree no check with this id exists at
    all — a recorded backup failure produced no signal whatsoever."""
    reason = "backup root unresponsive after 10.0s"
    write_status(tmp_path, live_snapshot("error", [reason]))
    checks = _d1(_monitor(tmp_path))
    assert CHECK_ID in checks, "the off-site backup outcome is read by nobody"
    assert checks[CHECK_ID].status == shm.WARNING
    assert reason in checks[CHECK_ID].title


def _seed_two_failed_days_before(tmp_path, day_key: str) -> None:
    """Carry-over of the two days preceding ``day_key`` — anchored to the
    SNAPSHOT's day, not to "today". Anchoring to the run day is what made this
    test unsatisfiable in the hour after UTC midnight: the seeded days sat one
    day away from the day the snapshot actually lands on, so the walk stopped
    at a hole and the streak never reached three."""
    d = datetime.fromisoformat(day_key).date()
    (tmp_path / "system_health.json").write_text(json.dumps({
        "offsite_backup_days": {
            (d - timedelta(days=2)).isoformat(): {"state": "failed"},
            (d - timedelta(days=1)).isoformat(): {"state": "failed"},
        }}), encoding="utf-8")


def test_monitor_escalates_a_three_day_streak_to_critical(tmp_path):
    """POSITIVE CONTROL for the series criterion, through the real report
    carry-over (previous system_health.json), not a hand-fed dict."""
    _seed_two_failed_days_before(tmp_path, snapshot_day())
    write_status(tmp_path, live_snapshot("error", ["stalled"]))
    checks = _d1(_monitor(tmp_path))
    assert checks[CHECK_ID].status == shm.CRITICAL


def test_monitor_reports_unchecked_when_the_key_is_absent(tmp_path):
    write_status(tmp_path, {"track_persist_ok": True,
                            "ts": (_BASE - timedelta(hours=1)).isoformat()})
    checks = _d1(_monitor(tmp_path))
    assert checks[CHECK_ID].status == shm.WARNING
    assert "UNCHECKED" in checks[CHECK_ID].title


def test_offsite_failure_does_not_poison_the_mirror_check(tmp_path):
    """The decoupling of ``mirror_ok`` from the off-site backup is deliberate
    (``cycle_runner._default_track_persister``): the local crash-recovery copy
    must not be reported unhealthy because iCloud stalled. The new signal lives
    BESIDE it — this pins that it never swallowed the old one."""
    write_status(tmp_path, live_snapshot("error", ["stalled"]))
    (tmp_path / "track.db").write_bytes(b"x" * 4096)
    checks = _d1(_monitor(tmp_path))
    assert checks[CHECK_ID].status == shm.WARNING
    assert checks["d1.track_db.mirror"].status == shm.OK


def test_the_day_series_is_published_in_the_report(tmp_path, monkeypatch):
    """Durability across runs: without this key in the report there is no
    series at all, and every run would restart the streak at 1.

    The two network-reaching domains are stubbed out — the subject here is
    report assembly, and letting them run only adds live-feed refusals to the
    suite's ledger (``spa_core/tests/conftest.py``).
    """
    for dom in ("check_d2_connectivity", "check_d4_external"):
        monkeypatch.setattr(shm.SystemHealthMonitor, dom, lambda self: [])
    write_status(tmp_path, live_snapshot("error", ["stalled"]))
    report = _monitor(tmp_path).collect()
    published = report["offsite_backup_days"]
    assert published.get(snapshot_day(), {}).get("state") == "failed"


def test_a_domain_that_never_ran_cannot_erase_a_running_streak(tmp_path):
    """The streak must not be resettable by a d1 timeout — that is precisely
    the run on which the system is already unwell."""
    prev_days = {"offsite_backup_days": {"2026-01-01": {"state": "failed"}}}  # FROZEN-DATE-OK: any well-formed day; the subject is carry-over, not freshness
    (tmp_path / "system_health.json").write_text(json.dumps(prev_days),
                                                 encoding="utf-8")
    mon = _monitor(tmp_path)
    mon._prev_cache = mon._load_previous()
    # _check_offsite_backup never ran → _offsite_backup_days stays None
    assert mon._offsite_backup_days is None
    assert mon._offsite_backup_days_for_report() == {"2026-01-01": {"state": "failed"}}  # FROZEN-DATE-OK: see above


def test_the_check_never_raises_and_carries_history_forward(tmp_path, monkeypatch):
    mon = _monitor(tmp_path)
    mon._prev_cache = {"offsite_backup_days": {day(-1): {"state": "failed"}}}

    def boom(*a, **kw):
        raise RuntimeError("exploded")

    monkeypatch.setattr(ob, "assess", boom)
    res = mon._check_offsite_backup("d1_data_pipeline")
    assert res.status == shm.WARNING and "UNCHECKED" in res.title
    assert "exploded" in (res.error or "")
    assert mon._offsite_backup_days_for_report() == {day(-1): {"state": "failed"}}


# ===========================================================================
# 6b. UTC midnight — the hour the card was measured in
#
# The card feared the day series itself tore every night, making "three days in
# a row" unreachable forever: an alarm that cannot fire while the console stays
# green. Measurement said otherwise — the tear was in the ASSERTIONS, and the
# two controls below pin both halves of that answer so neither can regress.
# ===========================================================================
def test_the_series_keys_the_snapshots_day_not_the_run_day_after_midnight(tmp_path):
    """POSITIVE CONTROL replaying 00:28 UTC 2026-08-09 exactly.

    The snapshot is an hour old, so it belongs to YESTERDAY while the monitor
    runs today. Keying by the run day would file the observation under a day
    nobody measured — inventing history in one direction and leaving a hole in
    the other. Re-keying by ``now`` turns this red.
    """
    write_status(tmp_path, live_snapshot("error", ["stalled"], now=_MIDNIGHT))
    mon = _monitor(tmp_path, now=_MIDNIGHT)
    checks = _d1(mon)

    yesterday = snapshot_day(now=_MIDNIGHT)
    assert yesterday != _MIDNIGHT.date().isoformat(), "fixture must straddle midnight"
    series = mon._offsite_backup_days_for_report()
    assert series.get(yesterday, {}).get("state") == "failed"
    assert _MIDNIGHT.date().isoformat() not in series      # no day was invented
    # An hour-old snapshot is still fresh — the calendar turning is not staleness.
    assert checks[CHECK_ID].status == shm.WARNING
    assert "UNCHECKED" not in checks[CHECK_ID].title


def test_a_three_day_streak_still_escalates_across_midnight(tmp_path):
    """POSITIVE CONTROL for the card's actual fear: CRITICAL must remain
    REACHABLE in the night window, not only in daylight hours."""
    _seed_two_failed_days_before(tmp_path, snapshot_day(now=_MIDNIGHT))
    write_status(tmp_path, live_snapshot("error", ["stalled"], now=_MIDNIGHT))
    checks = _d1(_monitor(tmp_path, now=_MIDNIGHT))
    assert checks[CHECK_ID].status == shm.CRITICAL
    assert checks[CHECK_ID].evidence["streak_days"] == ob.FAIL_STREAK_CRITICAL_DAYS


def test_three_consecutive_daily_cycles_reach_critical(tmp_path, monkeypatch):
    """The claim "three in a row NEVER happens" — measured end to end instead
    of argued.

    Three consecutive daily cycles at 06:00 UTC, each failing, with the monitor
    running TWICE a day (its real cadence) and carrying its own report forward
    exactly as production does. The second run of a day must re-file the same
    day rather than open a new one, or the streak would count runs instead of
    days and reach three a day and a half early.
    """
    for dom in ("check_d2_connectivity", "check_d4_external"):
        monkeypatch.setattr(shm.SystemHealthMonitor, dom, lambda self: [])

    cycle_hour = _BASE.replace(hour=6, minute=0)          # daily_cycle, 06:00 UTC
    statuses = []
    for d in range(3):
        cycle_at = cycle_hour + timedelta(days=d)
        write_status(tmp_path, {
            "track_persist_ok": True, "mirror_ok": True, "reason": "ok",
            "ts": cycle_at.isoformat(),
            "backup_status": "error", "backup_errors": ["stalled"]})
        for run_offset in (2, 10):                        # 08:00 and 16:00 UTC
            mon = _monitor(tmp_path, now=cycle_at + timedelta(hours=run_offset))
            report = mon.collect()
            (tmp_path / "system_health.json").write_text(
                json.dumps(report), encoding="utf-8")     # the real carry-over
            statuses.append(
                {c["id"]: c for c in report["checks"]}[CHECK_ID]["status"])

    assert len(mon._offsite_backup_days_for_report()) == 3   # days, not runs
    assert statuses[-1] == shm.CRITICAL
    # ...and not one run sooner: the fourth run is still day 2 of the streak.
    assert statuses[:4] == [shm.WARNING] * 4


# ===========================================================================
# 7. Boundaries the card drew explicitly
# ===========================================================================
def test_severity_vocabulary_matches_the_monitor():
    """The module restates the monitor's severity strings (importing back would
    be circular). Pin them against drift."""
    assert (ob.CRITICAL, ob.WARNING, ob.OK) == (shm.CRITICAL, shm.WARNING, shm.OK)


def test_this_signal_cannot_reach_the_kill_switch():
    """The card forbids escalation: a missing off-site copy is an operations
    failure, not a market event, and monitors that feed the kill-switch are
    owner-gated. ``threat_reactor`` must keep reading only its three sources."""
    src = (Path(shm.__file__).resolve().parents[1]
           / "monitoring" / "threat_reactor.py").read_text(encoding="utf-8")
    assert "system_health" not in src
    assert "offsite_backup" not in src and "backup_status" not in src


def test_the_module_never_touches_the_backup_root():
    """Enumerating the backup root is the call that stalls (backup.py probe).
    A monitor that hangs is worse than no monitor, so this module must not
    import or reach the backup layer at all."""
    src = Path(ob.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "persistence.backup" not in code
    assert "default_backup_dir" not in code
    assert "iterdir" not in code and "listdir" not in code
