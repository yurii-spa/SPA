"""test_health_surfaces_consistent.py — the two SPA health surfaces must AGREE.

The SYSTEM_BRIEFING.md agent fleet section and data/agent_health.json used to
contradict each other (the briefing showed e.g. 19/48 healthy + 9 CRIT while
agent_health.json showed 45/47 + 0 CRIT for the SAME fleet) because the briefing
INDEPENDENTLY re-derived agent freshness from raw logs/<name>.log paths — the
"log missing (never ran?)" detector bug that false-flagged agents which had
demonstrably run (they migrated to /tmp/spa_<name>.* after the fleet migration).

These tests pin the contract:
  1. The briefing CONSUMES agent_health.json verbatim → counts equal ±0.
  2. An agent that is FRESH/OK in agent_health.json is NOT reported "never ran"
     by the briefing (the briefing does not re-derive a contradictory verdict).
  3. A STALE agent_health.json → the briefing says "STALE", not a contradictory
     number (fail-honest snapshot-age guard).
  4. A MISSING agent_health.json → the briefing says "unavailable", not a number.
"""
import re
from datetime import datetime, timedelta, timezone

import pytest

import update_system_briefing as usb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fresh_ts(minutes_ago: float = 5.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _snapshot(ts: str, ok=45, warn=2, crit=0, total=47, overall="WARNING",
              agents=None) -> dict:
    if agents is None:
        agents = [
            {"label": "com.spa.agent_health", "status": "OK", "issue": ""},
            {"label": "com.spa.daily_cycle", "status": "WARNING",
             "issue": "log missing (never ran?)"},
            {"label": "com.spa.weekly_backup", "status": "WARNING",
             "issue": "log missing (never ran?)"},
        ]
    return {
        "timestamp": ts,
        "overall_status": overall,
        "healthy_count": ok,
        "warning_count": warn,
        "critical_count": crit,
        "total_agents": total,
        "agents": agents,
    }


def _patch_snapshot(monkeypatch, snap_or_none):
    """Force update_system_briefing.read_json('agent_health.json') → snap."""
    def fake_read_json(name):
        if name == "agent_health.json":
            return snap_or_none if snap_or_none is not None else {}
        return {}
    monkeypatch.setattr(usb, "read_json", fake_read_json)


def _counts_in_text(text: str):
    """Extract (ok, warn, crit, total) from a 'X OK / Y WARN / Z CRIT (of T)'
    string, if present. Returns None when no such count line exists."""
    m = re.search(r"(\d+)\s*OK\s*/\s*(\d+)\s*WARN\s*/\s*(\d+)\s*CRIT\s*\(of\s*(\d+)\)", text)
    if not m:
        return None
    return tuple(int(g) for g in m.groups())


# ---------------------------------------------------------------------------
# 1. Fresh snapshot → counts AGREE ±0
# ---------------------------------------------------------------------------
def test_briefing_counts_match_agent_health_fresh(monkeypatch):
    snap = _snapshot(_fresh_ts(5.0), ok=45, warn=2, crit=0, total=47)
    _patch_snapshot(monkeypatch, snap)

    section = usb.build_agents_section()
    counts = _counts_in_text(section)
    assert counts is not None, f"no count line rendered:\n{section}"
    assert counts == (45, 2, 0, 47), (
        f"briefing counts {counts} != agent_health.json (45,2,0,47)"
    )


def test_briefing_counts_match_arbitrary_fresh(monkeypatch):
    # Any snapshot — the briefing must echo it ±0, never re-derive.
    snap = _snapshot(_fresh_ts(2.0), ok=40, warn=1, crit=0, total=41, overall="WARNING")
    _patch_snapshot(monkeypatch, snap)
    counts = _counts_in_text(usb.build_agents_section())
    assert counts == (40, 1, 0, 41)


# ---------------------------------------------------------------------------
# 2. A FRESH/OK agent is NOT reported "never ran" by the briefing
# ---------------------------------------------------------------------------
def test_fresh_ok_agent_not_flagged_never_ran(monkeypatch):
    agents = [
        # demonstrably ran 0.6 min ago, OK — must NOT appear as "never ran"
        {"label": "com.spa.cycle_health", "status": "OK", "issue": ""},
        {"label": "com.spa.self_heal", "status": "OK", "issue": ""},
    ]
    snap = _snapshot(_fresh_ts(5.0), ok=2, warn=0, crit=0, total=2,
                     overall="OK", agents=agents)
    _patch_snapshot(monkeypatch, snap)

    section = usb.build_agents_section()
    assert "never ran" not in section, (
        f"briefing re-derived a false 'never ran' for an OK agent:\n{section}"
    )
    assert "cycle_health" not in section.split("Problems")[-1] if "Problems" in section else True
    assert "All agents nominal" in section


def test_briefing_reflects_only_agent_health_problems(monkeypatch):
    # The ONLY 'log missing (never ran?)' lines come verbatim from the snapshot's
    # WARNING agents — never invented by the briefing for an OK agent.
    snap = _snapshot(_fresh_ts(5.0))
    _patch_snapshot(monkeypatch, snap)
    section = usb.build_agents_section()
    never_ran_labels = re.findall(r"`(com\.spa\.[\w\-]+)`[^\n]*never ran", section)
    assert set(never_ran_labels) == {"com.spa.daily_cycle", "com.spa.weekly_backup"}, (
        f"briefing flagged unexpected 'never ran' agents: {never_ran_labels}"
    )


# ---------------------------------------------------------------------------
# 3. STALE snapshot → "STALE", NOT a contradictory number
# ---------------------------------------------------------------------------
def test_stale_snapshot_marked_stale(monkeypatch):
    stale_ts = (datetime.now(timezone.utc)
                - timedelta(minutes=usb.AGENT_SNAPSHOT_STALE_MIN + 30)).isoformat()
    snap = _snapshot(stale_ts)
    _patch_snapshot(monkeypatch, snap)

    section = usb.build_agents_section()
    assert "STALE" in section.upper(), f"stale snapshot not marked:\n{section}"
    # It may still print the LAST-KNOWN counts, but must label them last-known,
    # and must NOT present a fresh "✅ WARNING — .. CRIT" headline as if live.
    assert "last-known" in section.lower() or "LAST-KNOWN" in section


def test_stale_state_classifier():
    stale_ts = (datetime.now(timezone.utc)
                - timedelta(minutes=usb.AGENT_SNAPSHOT_STALE_MIN + 1)).isoformat()
    state, age = usb.agent_snapshot_state(_snapshot(stale_ts))
    assert state == "stale"
    assert age is not None and age > usb.AGENT_SNAPSHOT_STALE_MIN


def test_fresh_state_classifier():
    state, age = usb.agent_snapshot_state(_snapshot(_fresh_ts(5.0)))
    assert state == "fresh"
    assert age is not None and age <= usb.AGENT_SNAPSHOT_STALE_MIN


def test_unparseable_timestamp_is_stale_fail_closed():
    # Present snapshot whose timestamp we cannot date → fail-CLOSED to stale.
    state, age = usb.agent_snapshot_state(_snapshot("not-a-timestamp"))
    assert state == "stale"
    assert age is None


# ---------------------------------------------------------------------------
# 4. MISSING snapshot → "unavailable", NOT a number
# ---------------------------------------------------------------------------
def test_missing_snapshot_says_unavailable(monkeypatch):
    _patch_snapshot(monkeypatch, None)
    section = usb.build_agents_section()
    assert "UNAVAILABLE" in section.upper()
    # must NOT fabricate a count line
    assert _counts_in_text(section) is None, (
        f"missing snapshot produced a contradictory count:\n{section}"
    )


def test_missing_state_classifier():
    state, age = usb.agent_snapshot_state({})
    assert state == "missing"
    assert age is None


# ---------------------------------------------------------------------------
# 5. The LIVE on-disk snapshot (if present + fresh) agrees with a rendered
#    section built from it — end-to-end guard against re-derivation drift.
# ---------------------------------------------------------------------------
def test_live_snapshot_roundtrip_if_fresh():
    live = usb.read_json("agent_health.json")
    if not live:
        pytest.skip("no live agent_health.json in this environment")
    state, _ = usb.agent_snapshot_state(live)
    if state != "fresh":
        pytest.skip(f"live snapshot is {state}; consistency guard covered elsewhere")
    section = usb.build_agents_section()
    counts = _counts_in_text(section)
    assert counts is not None
    assert counts == (
        live["healthy_count"], live["warning_count"],
        live["critical_count"], live["total_agents"],
    ), "rendered briefing counts drifted from live agent_health.json"


# ---------------------------------------------------------------------------
# 6. CRY-WOLF FIX (WS 3.1): a RETIRED agent (httpserver, morning_digest, …) must
#    NOT be reported as a fault by the briefing's launchd section. A healthy
#    fleet that has correctly NOT loaded a retired agent reads HEALTHY.
# ---------------------------------------------------------------------------
import subprocess as _subprocess

from spa_core.monitoring.agent_health_monitor import RETIRED_LABELS


def _fake_launchctl(monkeypatch, stdout: str):
    """Force update_system_briefing's subprocess.run(['launchctl','list']) output."""
    class _R:
        def __init__(self, out):
            self.stdout = out
    monkeypatch.setattr(usb.subprocess, "run",
                        lambda *a, **k: _R(stdout))


def test_retired_agent_not_flagged_missing(monkeypatch):
    # A fleet where every NON-retired expected agent is loaded, and NO retired
    # agent (httpserver / morning_digest / daily-paper-report) is present.
    expected_non_retired = [
        "com.spa.cloudflared", "com.spa.familyfund", "com.spa.uptime_monitor",
        "com.spa.cycle_health", "com.spa.cycle_gap_monitor", "com.spa.portfolio_monitor",
        "com.spa.peg_monitor", "com.spa.red_flag_monitor", "com.spa.governance_watcher",
        "com.spa.autopush", "com.spa.daily_cycle", "com.spa.base_gas_monitor",
        "com.spa.sky_monitor", "com.spa.checkpoint-7day", "com.spa.weekly_backup",
        "com.spa.analytics_tier_c", "com.spa.analytics_tier_b", "com.spa.bts-feed",
        "com.spa.bts-monitor",
    ]
    lines = "\n".join(f"123\t0\t{lbl}" for lbl in expected_non_retired)
    _fake_launchctl(monkeypatch, lines)

    section = usb.build_launchd_section()
    # No retired agent is named as Missing.
    for retired in RETIRED_LABELS:
        assert retired not in section, (
            f"briefing cried wolf: retired agent {retired} flagged in:\n{section}"
        )
    # Healthy fleet reads healthy — no "Missing (not loaded)" block at all.
    assert "Missing (not loaded)" not in section
    assert "Missing from expected list: **0**" in section


def test_retired_agent_with_nonzero_exit_not_error_flagged(monkeypatch):
    # A retired agent's .plist lingers and launchd retains a non-zero exit for it.
    # It must NOT appear in the "Non-zero exit codes" block (it's out of fleet).
    lines = "\n".join([
        "-\t1\tcom.spa.httpserver",          # retired, exit 1 — must be IGNORED
        "-\t1\tcom.spa.morning_digest",      # retired, exit 1 — must be IGNORED
        "555\t0\tcom.spa.autopush",
        "556\t0\tcom.spa.daily_cycle",
    ])
    _fake_launchctl(monkeypatch, lines)
    section = usb.build_launchd_section()
    assert "Non-zero exit" not in section, (
        f"retired agent's stale exit cried wolf:\n{section}"
    )
    assert "com.spa.httpserver" not in section
    assert "com.spa.morning_digest" not in section


def test_live_agent_nonzero_exit_still_flagged(monkeypatch):
    # Honesty must NOT over-suppress: a NON-retired agent with a real non-zero
    # exit (and no live PID) is STILL flagged. Retired-skip ≠ blanket silence.
    lines = "\n".join([
        "-\t1\tcom.spa.autopush",            # live agent, genuine failure
        "557\t0\tcom.spa.daily_cycle",
    ])
    _fake_launchctl(monkeypatch, lines)
    section = usb.build_launchd_section()
    assert "Non-zero exit" in section
    assert "com.spa.autopush" in section
