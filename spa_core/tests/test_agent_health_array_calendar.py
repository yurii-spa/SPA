"""
test_agent_health_array_calendar.py — an ARRAY ``StartCalendarInterval`` must be judged by
its TIGHTEST entry, never by a fixed "array ⇒ weekly" rule.

RM-TRUTH-01 / ADR-580, A4 reliability finding #2 (REVIEW_1 confirmed the defect and
REFUTED the naive fix): ``classify_agent`` (agent_health_monitor.py) handled only a
``dict`` ``StartCalendarInterval``. launchd also accepts an ARRAY of dicts (fires at the
union of every entry), and that shape fell through to the final ``return CAT_DAILY`` with
no regard for what the entries actually say.

Two real plists on this host are the positive controls, read as fixtures (not re-typed by
hand, so the test notices if either schedule is ever edited):

  * ``com.spa.novel_edge_rnd``  — array of two Weekday dicts (Tue=2, Fri=5, both 04:00).
    Pre-fix: falls through to CAT_DAILY (26h/52h window) ⇒ permanent false CRITICAL every
    Fri→Tue gap (≈2.2–4 days, A4 measured 3.2d CRIT, last_exit 0).
  * ``com.spa.aggressive_lab`` — array of four same-day Hour/Minute dicts (00/06/12/18h,
    no Weekday). The NAIVE "array ⇒ weekly" fix (A4's own Phase-2 proposal) would
    misclassify this as CAT_WEEKLY — a 6-hourly agent silently tolerated for up to two
    weeks before any alarm. REVIEW_1 #2 refuted exactly this fix. This test pins the
    opposite: a same-day array stays CAT_DAILY (or tighter).

A second, narrower defect lives inside the weekly case itself: Tue+Fri's REAL worst-case
gap is 4 days (Fri→Tue), not the flat 7-day single-weekday window. Judging it by the flat
window would only catch TWO consecutive missed runs, not one — so the threshold itself must
come from the measured gap between entries, not a fixed category constant.

Every test fails on the pre-fix classifier / threshold. stdlib only, hermetic, no data/, no
network.
"""
from __future__ import annotations

import plistlib
from pathlib import Path

from spa_core.monitoring.agent_health_monitor import (
    CAT_DAILY,
    CAT_MONTHLY,
    CAT_ONE_TIME,
    CAT_WEEKLY,
    _FRESHNESS_THRESHOLD_MIN,
    _weekly_entries_max_gap_minutes,
    classify_agent,
    weekly_freshness_threshold_min,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NOVEL_EDGE_PLIST = _REPO_ROOT / "launchd" / "com.spa.novel_edge_rnd.plist"
_AGGRESSIVE_LAB_PLIST = _REPO_ROOT / "scripts" / "com.spa.aggressive_lab.plist"

# FROZEN-DATE-OK: these are the historical incident's own schedules, read fresh from the
# repo's plists below — not hand-typed, so the test tracks the real file, not a copy of it.


def _load_calendar(path: Path) -> list:
    assert path.is_file(), f"missing {path} — the incident's own plist is not in the repo"
    plist = plistlib.loads(path.read_bytes())
    cal = plist.get("StartCalendarInterval")
    assert isinstance(cal, list), (
        f"{path.name} StartCalendarInterval is no longer an array ({cal!r}) — this test's "
        f"subject (the array shape) changed; re-derive it rather than deleting the test"
    )
    return cal


def test_novel_edge_rnd_real_plist_is_weekly_not_daily():
    """The accident itself: Tue+Fri array must not fall through to CAT_DAILY."""
    cal = _load_calendar(_NOVEL_EDGE_PLIST)
    cat = classify_agent({"StartCalendarInterval": cal})
    assert cat == CAT_WEEKLY, (
        f"novel_edge_rnd's Tue+Fri array classified {cat!r} — as {CAT_DAILY!r} the 26h/52h "
        f"window makes every Fri→Tue gap (≈2.2–4 days) a permanent false CRITICAL"
    )


def test_novel_edge_rnd_real_max_gap_is_not_crit_at_measured_silence():
    """A4 measured a 3.2-day silence flagged CRITICAL. The real worst-case gap
    (Fri 04:00 → Tue 04:00 = 4 days) must clear BOTH the WARNING and CRITICAL bars."""
    cal = _load_calendar(_NOVEL_EDGE_PLIST)
    threshold = weekly_freshness_threshold_min({"StartCalendarInterval": cal})
    measured_silence_min = 3.2 * 24 * 60
    assert measured_silence_min < threshold, (
        f"the A4-measured 3.2-day silence ({measured_silence_min} min) still trips the "
        f"weekly WARNING window ({threshold} min) — the false alarm is not fixed"
    )
    assert measured_silence_min < 2 * threshold, "…and must not reach CRITICAL (2x) either"


def test_novel_edge_rnd_still_flags_a_genuinely_missed_run():
    """Fail-CLOSED check: going stale PAST the real 4-day max gap must still alarm.
    A flat 7-day single-weekday window would silently tolerate one entirely missed
    Tue-or-Fri run — this pins that it does not."""
    cal = _load_calendar(_NOVEL_EDGE_PLIST)
    threshold = weekly_freshness_threshold_min({"StartCalendarInterval": cal})
    real_max_gap_min = 4 * 24 * 60  # Fri 04:00 -> Tue 04:00
    assert threshold == real_max_gap_min, (
        f"weekly threshold {threshold} min does not equal the measured worst-case gap "
        f"{real_max_gap_min} min — Tue+Fri's real cadence is tighter than the flat 7-day window"
    )
    past_the_gap_min = real_max_gap_min + 60
    assert past_the_gap_min > threshold, "a genuinely missed run must exceed the WARNING bar"


def test_aggressive_lab_real_plist_stays_daily_not_weekly():
    """REVIEW_1 #2's refutation, pinned: a same-day 4x/day array must NOT become weekly.
    Classifying it weekly would fail-OPEN — up to two weeks of silence before any alarm."""
    cal = _load_calendar(_AGGRESSIVE_LAB_PLIST)
    cat = classify_agent({"StartCalendarInterval": cal})
    assert cat == CAT_DAILY, (
        f"aggressive_lab's 4x/day array (00/06/12/18h, no Weekday) classified {cat!r} — a "
        f"6-hourly agent must stay daily-or-tighter, never weekly (REVIEW_1 #2 fail-OPEN)"
    )
    # And it must not silently inherit the weekly threshold either.
    threshold = _FRESHNESS_THRESHOLD_MIN[cat]
    assert threshold == _FRESHNESS_THRESHOLD_MIN[CAT_DAILY]


def test_single_weekday_array_keeps_the_flat_seven_day_window():
    """A single-entry array (one Weekday) is not "multiple weekdays" — it must keep the
    existing flat 7-day/14-day window unchanged (anti-weakening pin)."""
    cal = [{"Weekday": 0, "Hour": 10, "Minute": 0}]
    assert classify_agent({"StartCalendarInterval": cal}) == CAT_WEEKLY
    assert weekly_freshness_threshold_min({"StartCalendarInterval": cal}) == (
        _FRESHNESS_THRESHOLD_MIN[CAT_WEEKLY]
    )


def test_tightest_entry_wins_across_mixed_shapes():
    """A one-time entry riding alongside a weekly entry in the same array must not loosen
    the agent to CAT_ONE_TIME (no alarm at all) — the recurring weekly entry still fires."""
    mixed = [{"Weekday": 1, "Hour": 9}, {"Month": 12, "Day": 25, "Hour": 0}]
    assert classify_agent({"StartCalendarInterval": mixed}) == CAT_WEEKLY
    # A monthly-only entry next to an Hour/Minute-only (effectively daily) entry: the daily
    # entry fires every day, so the union is daily, not monthly.
    mixed2 = [{"Day": 1, "Hour": 8}, {"Hour": 7, "Minute": 30}]
    assert classify_agent({"StartCalendarInterval": mixed2}) == CAT_DAILY


def test_malformed_or_empty_array_fails_closed_to_daily():
    """An array with no usable dict entries must not silently relax to the loosest
    category — fail-CLOSED means the SHORTEST grace window, not the longest."""
    assert classify_agent({"StartCalendarInterval": []}) == CAT_DAILY
    assert classify_agent({"StartCalendarInterval": ["not-a-dict"]}) == CAT_DAILY


def test_weekly_gap_helper_handles_duplicate_and_unordered_times():
    """Direct unit coverage of the gap arithmetic, independent of any plist on disk."""
    # Tue 04:00, Fri 04:00 (unordered input) -> gaps 3d and 4d -> max 4d.
    entries = [
        {"Weekday": 5, "Hour": 4, "Minute": 0},
        {"Weekday": 2, "Hour": 4, "Minute": 0},
    ]
    assert _weekly_entries_max_gap_minutes(entries) == 4 * 24 * 60
    # Apple's Weekday 7 == 0 (both Sunday) must collapse to the same slot.
    entries_dup = [
        {"Weekday": 0, "Hour": 0, "Minute": 0},
        {"Weekday": 7, "Hour": 0, "Minute": 0},
    ]
    assert _weekly_entries_max_gap_minutes(entries_dup) == 7 * 24 * 60
    assert _weekly_entries_max_gap_minutes([]) is None


def test_fix_does_not_reclassify_the_existing_dict_cases():
    """Anti-weakening pin against the monthly-cadence fix (test_agent_health_monthly_cadence.py):
    the single-dict path must be byte-for-byte the same classifications as before."""
    assert classify_agent({"StartCalendarInterval": {"Hour": 8, "Minute": 10}}) == CAT_DAILY
    assert classify_agent({"StartCalendarInterval": {"Weekday": 0, "Hour": 10}}) == CAT_WEEKLY
    assert classify_agent({"StartCalendarInterval": {"Month": 9, "Day": 1}}) == CAT_ONE_TIME
    assert classify_agent({"StartCalendarInterval": {"Day": 1, "Hour": 8}}) == CAT_MONTHLY
    assert classify_agent(None) is not None
