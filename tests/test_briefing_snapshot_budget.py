"""test_briefing_snapshot_budget.py — a consumer must not invent a freshness
budget for someone else's artifact.

Cycle #242, card `inbox-brifing-schitaet-snimok-flota-protuhshim`. Three numbers
described ONE artifact and the wrong one decided:

| who                          | number  | where                                     |
|------------------------------|--------:|-------------------------------------------|
| writer `com.spa.agent_health`| 60 min  | plist StartInterval=3600 / `cadence_minutes` |
| the artifact itself          | 90 min  | `agent_health.json: stale_after_minutes`  |
| consumer (the briefing)      | 35 min  | `update_system_briefing.AGENT_SNAPSHOT_STALE_MIN` |

35 < 60 means the threshold sat BELOW the writer's own cadence, so a fully healthy
fleet flew "⚠️ SNAPSHOT STALE" for roughly 25 minutes of every hour — by
construction, not by fault. Measured 2026-08-15 08:45Z: the briefing published
"SNAPSHOT STALE (60m > 35m) ... the writer may be lagging" over 78 OK / 0 WARN /
0 CRIT, and the writer was on time.

Same class as #235 (one artifact, two budgets, decided by the side that does not
produce it) with the sign flipped: there the budget could never fire, here it fired
almost always. The cost is identical — the guard teaches its readers to ignore it,
and the real writer lag it exists to catch is ignored with it.

Both directions are pinned here, and every "must stay quiet" test has a positive
control next to it that makes the SAME surface speak: a check that has never seen a
real lag is decoration (`.claude/rules/deployment.md`).

Time is an INPUT (rule "время — вход"): every timestamp below is built relative to
a pinned `now`, so no calendar drift can turn these red.
"""
from datetime import datetime, timedelta, timezone

import update_system_briefing as usb


NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)


def _ts(minutes_ago: float) -> str:
    """An ISO timestamp `minutes_ago` before the REAL clock.

    `_age_minutes` reads the wall clock (it is not injectable), so the fixture is
    anchored relative to it — the offsets are what the tests pin, never a literal
    date.
    """
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _snapshot(minutes_ago: float, declared_budget=None, ok=78, warn=0, crit=0,
              total=78, overall="OK") -> dict:
    snap = {
        "timestamp": _ts(minutes_ago),
        "overall_status": overall,
        "healthy_count": ok,
        "warning_count": warn,
        "critical_count": crit,
        "total_agents": total,
        "agents": [],
    }
    if declared_budget is not None:
        snap["cadence_minutes"] = 60.0
        snap["stale_after_minutes"] = declared_budget
    return snap


def _patch(monkeypatch, agent_snap):
    def fake_read_json(name):
        return agent_snap if name == "agent_health.json" else {}
    monkeypatch.setattr(usb, "read_json", fake_read_json)


# ---------------------------------------------------------------------------
# 1. The budget comes from the PRODUCER
# ---------------------------------------------------------------------------
def test_declared_budget_wins_over_the_consumer_literal():
    budget, source = usb.snapshot_budget_min(_snapshot(10, declared_budget=90.0),
                                             usb.AGENT_SNAPSHOT_STALE_MIN)
    assert (budget, source) == (90.0, "declared")


def test_missing_declaration_falls_back_and_says_so():
    budget, source = usb.snapshot_budget_min(_snapshot(10), usb.AGENT_SNAPSHOT_STALE_MIN)
    assert (budget, source) == (float(usb.AGENT_SNAPSHOT_STALE_MIN), "fallback")
    # A silent fallback reads exactly like a producer-declared budget. Naming it
    # is the whole point of the `source` field.
    assert "fallback" in usb.budget_txt(budget, source).lower()
    assert "запасной" in usb.budget_txt(budget, source, lang="ru")


def test_declared_budget_is_named_as_the_writers_own():
    txt = usb.budget_txt(90.0, "declared")
    assert "declared" in txt and "fallback" not in txt


def test_garbage_declaration_is_not_trusted():
    # A budget must be a positive number. Strings, None, booleans and <= 0 are
    # not a declaration — fail back to the literal rather than crash or trust it.
    for bad in ("90", None, True, 0, -5, [90]):
        budget, source = usb.snapshot_budget_min(
            _snapshot(10, declared_budget=bad), usb.AGENT_SNAPSHOT_STALE_MIN)
        assert source == "fallback", f"garbage budget {bad!r} was trusted"
        assert budget == float(usb.AGENT_SNAPSHOT_STALE_MIN)


# ---------------------------------------------------------------------------
# 2. The classifier: quiet inside the declared budget, loud outside it
# ---------------------------------------------------------------------------
def test_snapshot_within_declared_budget_is_fresh():
    # THE BUG: 45 min is a normal age for a 60-min writer, and the artifact allows
    # 90. Before #242 this returned "stale" and the briefing called the writer late.
    state, age = usb.agent_snapshot_state(_snapshot(45, declared_budget=90.0))
    assert state == "fresh", f"a 45-min-old snapshot of a 60-min writer is not stale (age={age})"


def test_snapshot_past_declared_budget_is_stale():
    # POSITIVE CONTROL: a writer that really has missed runs must still be caught.
    state, age = usb.agent_snapshot_state(_snapshot(95, declared_budget=90.0))
    assert state == "stale"
    assert age is not None and age > 90.0


def test_declared_budget_can_be_tighter_than_the_literal():
    # The producer decides in BOTH directions — a 20-min budget makes a 25-min-old
    # snapshot stale even though the consumer's own literal (35) would allow it.
    state, _ = usb.agent_snapshot_state(_snapshot(25, declared_budget=20.0))
    assert state == "stale"


def test_undeclared_snapshot_still_judged_by_the_literal():
    # No declaration → the fallback still guards; removing the literal would leave
    # an undeclared snapshot unjudged, which is worse than a wrong budget.
    assert usb.agent_snapshot_state(_snapshot(5))[0] == "fresh"
    assert usb.agent_snapshot_state(
        _snapshot(usb.AGENT_SNAPSHOT_STALE_MIN + 10))[0] == "stale"


# ---------------------------------------------------------------------------
# 3. The two rendered surfaces (section + header cell) say the same thing
# ---------------------------------------------------------------------------
def test_healthy_fleet_produces_no_stale_line(monkeypatch):
    # The acceptance criterion from the card: on a healthy system the words
    # "SNAPSHOT STALE" do not appear at all.
    _patch(monkeypatch, _snapshot(45, declared_budget=90.0))
    section = usb.build_agents_section()
    assert "SNAPSHOT STALE" not in section.upper(), section
    assert "78 OK / 0 WARN / 0 CRIT" in section


def test_real_lag_still_produces_the_stale_line(monkeypatch):
    # POSITIVE CONTROL for the test above: the same surface, an artificially aged
    # snapshot, and the warning is back — with the writer's own budget quoted.
    _patch(monkeypatch, _snapshot(200, declared_budget=90.0))
    section = usb.build_agents_section()
    assert "SNAPSHOT STALE" in section.upper(), section
    assert "90 min declared by the writer" in section, section
    assert "last-known" in section.lower()


def test_stale_line_names_a_fallback_budget_as_a_fallback(monkeypatch):
    _patch(monkeypatch, _snapshot(usb.AGENT_SNAPSHOT_STALE_MIN + 20))
    section = usb.build_agents_section()
    assert "SNAPSHOT STALE" in section.upper()
    assert "briefing fallback" in section, (
        "a budget the producer never declared was presented as if it had:\n" + section
    )


# ---------------------------------------------------------------------------
# 4. Track integrity: the neighbouring threshold — MEASURED, not assumed
# ---------------------------------------------------------------------------
def _cycle_health(minutes_ago: float, declared_budget=None, divergent=3) -> dict:
    d = {
        "checked_at": _ts(minutes_ago),
        "checks": {"evidence_vs_curve": {
            "status": "OK", "divergent_days": divergent, "compared_days": 57,
            "max_delta_usd": 215.99, "latest_divergent": "2026-08-15", "detail": "",
        }},
    }
    if declared_budget is not None:
        d["stale_after_minutes"] = declared_budget
    return d


def test_track_budget_is_not_red_by_construction():
    # com.spa.cycle_health runs every 300 s (MEASURED: plist StartInterval=300) and
    # the literal is 30 min = 6 cadences, so unlike the agent budget this one does
    # NOT fire on a healthy system. Card item 3: measure, don't assume.
    assert usb.TRACK_SNAPSHOT_STALE_MIN > 5 * 2
    st = usb.track_integrity_state(_cycle_health(6), now=NOW)
    assert st["state"] == "fresh"
    assert st["budget_source"] == "fallback"


def test_track_snapshot_past_budget_is_stale_and_names_the_budget():
    # POSITIVE CONTROL: a 5-minute producer silent for 40 minutes has missed ~8 runs.
    st = usb.track_integrity_state(_cycle_health(40), now=NOW)
    assert st["state"] == "stale"
    cell = usb.track_integrity_cell(st)
    assert "СНИМОК ПРОТУХ" in cell
    assert "запасной бюджет" in cell, cell


def test_track_declared_budget_is_preferred_and_named():
    # cycle_health.json declares nothing today; if it ever starts, the producer wins.
    st = usb.track_integrity_state(_cycle_health(40, declared_budget=120.0), now=NOW)
    assert st["state"] == "fresh"
    st_stale = usb.track_integrity_state(_cycle_health(200, declared_budget=120.0), now=NOW)
    assert st_stale["state"] == "stale"
    assert "объявленных писателем" in usb.track_integrity_cell(st_stale)


# ---------------------------------------------------------------------------
# 5. The writer's contract, end to end — the fix is not theoretical
# ---------------------------------------------------------------------------
# Pinned against the PRODUCER MODULE, not against data/agent_health.json: a
# git-tracked snapshot is whatever was last committed (in a clean CI checkout it
# predates the contract entirely), so a data-shaped assertion would measure the
# fixture, not the code.
def test_writer_declares_a_budget_at_least_its_own_cadence():
    from spa_core.monitoring import agent_health_monitor as ahm

    assert ahm.SNAPSHOT_STALE_MIN >= ahm.SNAPSHOT_CADENCE_MIN, (
        "the writer would declare a budget below its own tick — the #242 defect "
        "moved into the producer, where every consumer inherits it"
    )


def test_a_snapshot_from_the_real_writer_is_fresh_at_one_full_cadence():
    """The end-to-end shape: writer's own contract → consumer's verdict.

    A snapshot exactly one cadence old is the NORMAL state of an on-time hourly
    writer as seen by a 30-minute reader. Before #242 the briefing called that
    state "the writer may be lagging".
    """
    from spa_core.monitoring import agent_health_monitor as ahm

    snap = _snapshot(ahm.SNAPSHOT_CADENCE_MIN, declared_budget=ahm.SNAPSHOT_STALE_MIN)
    assert usb.agent_snapshot_state(snap)[0] == "fresh"
    # POSITIVE CONTROL: past the writer's OWN budget it is stale again.
    late = _snapshot(ahm.SNAPSHOT_STALE_MIN + 1, declared_budget=ahm.SNAPSHOT_STALE_MIN)
    assert usb.agent_snapshot_state(late)[0] == "stale"
