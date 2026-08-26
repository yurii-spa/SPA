"""
test_agent_health_monthly_cadence.py — a MONTHLY agent must be judged by a monthly window.

Positive controls for the failure measured on 2026-08-24 (cycle #374). The fleet's single
🔴 CRITICAL was `com.spa.monthly_statement`:

    {"label": "com.spa.monthly_statement", "status": "CRITICAL", "last_exit": 0,
     "log_age_min": 3749.8, "category": "daily", "issue": "log stale 2.6d (>2.2d)"}

Its plist says ``StartCalendarInterval = {Day: 1, Hour: 8, Minute: 30}`` — launchd's
day-of-MONTH, i.e. it fires on the 1st and then legitimately says nothing for ~30 days.
``classify_agent`` knew only ``Month``+``Day`` (one-time) and ``Weekday`` (weekly), so a bare
``Day`` fell through to ``CAT_DAILY`` with a 26h/52h window. A monthly producer asked a daily
question is CRITICAL ~28 days out of every 30 BY CONSTRUCTION: the alarm carried no information
about the agent at all, and `last_exit: 0` proves the agent itself was fine.

Same class as #242/#256 ("срок годности спрашивали не у того") — the freshness budget has to be
taken from the PRODUCER's cadence, never from a sibling's literal.

Every test below fails on the pre-fix classifier. stdlib only, hermetic, no data/, no network.
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
    _RESIDENCY_REQUIRED_CATS,
    classify_agent,
    requires_residency,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The exact schedule read off launchd/com.spa.monthly_statement.plist on 2026-08-24.
# FROZEN-DATE-OK: this is the historical incident's own schedule, and the schedule IS
# the subject of the test — not a freshness fixture that ages.
_MONTHLY_CAL = {"Day": 1, "Hour": 8, "Minute": 30}


def test_day_of_month_schedule_is_monthly_not_daily():
    """The accident itself: `Day` without `Month` is a MONTHLY cadence."""
    cat = classify_agent({"StartCalendarInterval": dict(_MONTHLY_CAL)})
    assert cat == CAT_MONTHLY, (
        f"day-of-month schedule {_MONTHLY_CAL} classified {cat!r} — as {CAT_DAILY!r} it gets a "
        f"26h window and is CRITICAL ~28 days of every 30 no matter how healthy it is"
    )


def test_monthly_window_outlives_the_longest_real_gap():
    """A monthly job's quiet stretch is up to 31 days; the WARNING window must exceed it,
    and the observed 2.6-day silence must be nowhere near either threshold."""
    warn = _FRESHNESS_THRESHOLD_MIN[CAT_MONTHLY]
    assert warn > 31 * 24 * 60, (
        f"monthly window {warn} min does not even cover a 31-day month — still red by construction"
    )
    observed_silence_min = 3749.8      # the log age that produced the false CRITICAL
    assert observed_silence_min < warn, (
        f"the 2026-08-24 silence ({observed_silence_min} min) still trips the monthly WARNING "
        f"window ({warn} min) — the false alarm is not fixed"
    )
    assert observed_silence_min < 2 * warn, "…and it must not reach CRITICAL (2x) either"


def test_monthly_agent_is_not_required_to_be_resident():
    """A calendar job correctly EXITS between runs. Demanding residency of it is the other
    half of the chronic false-CRITICAL bug, so `monthly` must stay out of that set."""
    assert CAT_MONTHLY not in _RESIDENCY_REQUIRED_CATS
    assert not requires_residency(CAT_MONTHLY, {"StartCalendarInterval": dict(_MONTHLY_CAL)})


def test_fix_does_not_reclassify_the_neighbouring_cadences():
    """Anti-weakening pin: only `Day`-without-`Month` moves. Every other calendar shape keeps
    the category (and therefore the window) it had before."""
    assert classify_agent({"StartCalendarInterval": {"Hour": 8, "Minute": 10}}) == CAT_DAILY
    assert classify_agent({"StartCalendarInterval": {"Weekday": 0, "Hour": 10}}) == CAT_WEEKLY
    assert classify_agent({"StartCalendarInterval": {"Month": 9, "Day": 1}}) == CAT_ONE_TIME
    # Weekday wins over a co-present Day — a weekly job is not a monthly one.
    assert classify_agent({"StartCalendarInterval": {"Weekday": 0, "Day": 1}}) == CAT_WEEKLY
    assert classify_agent({"StartInterval": 300}) != CAT_MONTHLY
    assert classify_agent(None) != CAT_MONTHLY


def test_the_real_plist_on_disk_is_judged_monthly():
    """Judge the SUBJECT, not a copy of it: read the deployed plist itself, so the guard
    notices if the agent is ever rescheduled onto a different cadence."""
    p = _REPO_ROOT / "launchd" / "com.spa.monthly_statement.plist"
    assert p.is_file(), f"missing {p} — the incident's own agent is not in the repo"
    cal = plistlib.loads(p.read_bytes()).get("StartCalendarInterval")
    assert isinstance(cal, dict) and "Day" in cal and "Month" not in cal, (
        f"com.spa.monthly_statement is no longer a day-of-month job ({cal!r}) — this test's "
        f"subject changed; re-derive its window from the new schedule rather than deleting it"
    )
    assert classify_agent({"StartCalendarInterval": cal}) == CAT_MONTHLY
