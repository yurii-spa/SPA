"""test_briefing_agent_health_reasons.py — the briefing must NEVER publish a
reassurance that contradicts its own verdict.

Found live (cycle #75), verbatim from docs/SYSTEM_BRIEFING.md 2026-08-01 17:13 UTC::

    ## 🤖 Agent Health
    ⚠️ **WARNING** — 70 OK / 0 WARN / 0 CRIT  (of 70)  ·  snapshot 31m ago
    _All agents nominal_

A WARNING verdict, and directly underneath it "All agents nominal" — with the
reason for the WARNING printed nowhere. The reason existed all along, in the very
snapshot the section reads (``data/agent_health.json``)::

    "system_issues": [
      "fleet parity stale 507.9h (>26h) — drift guard not re-run",
      "capital-efficiency LAZY: 15% deployable capital idle at 0% ..."
    ]

Mechanism: ``agent_health_monitor.build_report`` computes
``overall = _worst(system_status, *[per-agent statuses])`` where ``system_status``
is raised to WARNING precisely BY ``system_issues``. The verdict is therefore
fully explainable — ``build_agents_section`` simply never read the key, deriving
its text from ``d["agents"]`` alone and falling through to the ``else`` branch.

This is the fail-OPEN class of cycles #29/#31/#35–#38/#40 (publishing "fine"
about something never checked), in its more harmful form: not silence, but
active reassurance contradicting the verdict on the line above it.

Cost is measured, not assumed: "fleet parity stale 507.9h" is ~21 days. The
fleet-drift guard had not re-run since ~2026-07-11 and no cycle noticed, because
in the one file CLAUDE.md obliges every session to read, the reason was invisible.

These tests pin the contract:
  1. Non-empty ``system_issues`` are rendered VERBATIM.
  2. "All agents nominal" is unreachable when ``overall != OK`` (fail-CLOSED:
     a non-OK verdict with no reason in the snapshot says so, it does not soothe).
  3. Positive controls: the OK/no-issues rendering is unchanged byte-for-byte,
     per-agent problems still render, counts still echo the snapshot ±0.
"""
from datetime import datetime, timedelta, timezone

import update_system_briefing as usb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fresh_ts(minutes_ago: float = 5.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _snap(overall="WARNING", ok=70, warn=0, crit=0, total=70,
          agents=None, system_issues=None, ts=None):
    """A snapshot shaped exactly like data/agent_health.json."""
    if agents is None:
        agents = [{"label": f"com.spa.a{i}", "status": "OK", "issue": ""}
                  for i in range(3)]
    snap = {
        "timestamp": ts or _fresh_ts(5.0),
        "overall_status": overall,
        "healthy_count": ok,
        "warning_count": warn,
        "critical_count": crit,
        "total_agents": total,
        "agents": agents,
    }
    if system_issues is not None:
        snap["system_issues"] = system_issues
    return snap


def _patch(monkeypatch, snap):
    def fake_read_json(name):
        return snap if name == "agent_health.json" else {}
    monkeypatch.setattr(usb, "read_json", fake_read_json)


# The two live issues, verbatim from the production snapshot that exposed this.
LIVE_ISSUES = [
    "fleet parity stale 507.9h (>26h) — drift guard not re-run",
    "capital-efficiency LAZY: 15% deployable capital idle at 0% — "
    "~127bps/yr forgone (allocator left safe headroom unused)",
]


# ---------------------------------------------------------------------------
# 1. The live defect, reproduced verbatim
# ---------------------------------------------------------------------------
def test_live_warning_snapshot_does_not_claim_all_agents_nominal(monkeypatch):
    """The exact production snapshot of 2026-08-01 must not soothe."""
    _patch(monkeypatch, _snap(overall="WARNING", system_issues=LIVE_ISSUES))
    section = usb.build_agents_section()

    assert "All agents nominal" not in section, (
        "briefing published 'All agents nominal' under a WARNING verdict "
        f"whose reasons were sitting in the snapshot:\n{section}"
    )


def test_system_issues_are_rendered_verbatim(monkeypatch):
    """Reasons are QUOTED, not summarised — a paraphrase loses the number that
    makes the issue actionable (507.9h is the whole point)."""
    _patch(monkeypatch, _snap(overall="WARNING", system_issues=LIVE_ISSUES))
    section = usb.build_agents_section()

    for issue in LIVE_ISSUES:
        assert issue in section, (
            f"system issue not rendered verbatim: {issue!r}\n{section}"
        )


def test_fleet_parity_staleness_is_visible(monkeypatch):
    """The 21-day-invisible finding must be readable in the briefing itself."""
    _patch(monkeypatch, _snap(overall="WARNING", system_issues=LIVE_ISSUES))
    section = usb.build_agents_section()
    assert "fleet parity" in section and "507.9h" in section, section


# ---------------------------------------------------------------------------
# 2. fail-CLOSED: a non-OK verdict with NO stated reason must say so
# ---------------------------------------------------------------------------
def test_non_ok_verdict_without_reasons_is_not_soothed(monkeypatch):
    """WARNING, every agent OK, and the snapshot carries no system_issues at all.

    There is nothing to quote — so the section must NOT claim everything is
    nominal. Saying "the verdict has no stated reason" is honest; saying "all
    agents nominal" is the very class of defect this file exists to stop.
    """
    _patch(monkeypatch, _snap(overall="WARNING", system_issues=None))
    section = usb.build_agents_section()

    assert "All agents nominal" not in section, (
        "non-OK verdict with no reasons still rendered the nominal reassurance:\n"
        f"{section}"
    )


def test_critical_verdict_without_reasons_is_not_soothed(monkeypatch):
    _patch(monkeypatch, _snap(overall="CRITICAL", system_issues=[]))
    section = usb.build_agents_section()
    assert "All agents nominal" not in section, section


def test_unknown_verdict_is_not_soothed(monkeypatch):
    """UNKNOWN is not OK. An unmeasured fleet must never read as a healthy one."""
    _patch(monkeypatch, _snap(overall="UNKNOWN", system_issues=[]))
    section = usb.build_agents_section()
    assert "All agents nominal" not in section, section


# ---------------------------------------------------------------------------
# 3. Positive controls — the healthy path is UNCHANGED
# ---------------------------------------------------------------------------
def test_ok_verdict_with_no_issues_still_reads_nominal(monkeypatch):
    """Control: the fix must not turn a genuinely healthy fleet into noise."""
    _patch(monkeypatch, _snap(overall="OK", warn=0, crit=0, system_issues=[]))
    section = usb.build_agents_section()
    assert "All agents nominal" in section, section


def test_ok_verdict_without_the_key_at_all_still_reads_nominal(monkeypatch):
    """Control: snapshots predating system_issues must render exactly as before."""
    _patch(monkeypatch, _snap(overall="OK", system_issues=None))
    section = usb.build_agents_section()
    assert "All agents nominal" in section, section


def test_per_agent_problems_still_render(monkeypatch):
    """Control: the pre-existing per-agent problem list is untouched."""
    agents = [
        {"label": "com.spa.daily_cycle", "status": "WARNING",
         "issue": "log missing (never ran?)"},
        {"label": "com.spa.apiserver", "status": "CRITICAL", "issue": "exit 78"},
        {"label": "com.spa.self_heal", "status": "OK", "issue": ""},
    ]
    _patch(monkeypatch, _snap(overall="CRITICAL", ok=1, warn=1, crit=1, total=3,
                              agents=agents, system_issues=[]))
    section = usb.build_agents_section()

    assert "com.spa.daily_cycle" in section and "log missing (never ran?)" in section
    assert "com.spa.apiserver" in section and "exit 78" in section
    assert "All agents nominal" not in section


def test_agent_problems_and_system_issues_render_together(monkeypatch):
    """Both kinds of reason are shown; neither branch swallows the other."""
    agents = [{"label": "com.spa.daily_cycle", "status": "WARNING",
               "issue": "log missing (never ran?)"}]
    _patch(monkeypatch, _snap(overall="WARNING", ok=0, warn=1, crit=0, total=1,
                              agents=agents, system_issues=LIVE_ISSUES))
    section = usb.build_agents_section()

    assert "com.spa.daily_cycle" in section, section
    for issue in LIVE_ISSUES:
        assert issue in section, section


def test_counts_still_echo_the_snapshot(monkeypatch):
    """Control: the fix touches the REASONS, never the numbers."""
    import re
    _patch(monkeypatch, _snap(overall="WARNING", ok=70, warn=0, crit=0, total=70,
                              system_issues=LIVE_ISSUES))
    section = usb.build_agents_section()
    m = re.search(r"(\d+)\s*OK\s*/\s*(\d+)\s*WARN\s*/\s*(\d+)\s*CRIT\s*\(of\s*(\d+)\)",
                  section)
    assert m is not None, section
    assert tuple(int(g) for g in m.groups()) == (70, 0, 0, 70), section


def test_blank_system_issues_are_not_rendered_as_reasons(monkeypatch):
    """Whitespace-only entries are not reasons; they must not manufacture a
    'reason' block, but they also must not restore the nominal reassurance
    under a non-OK verdict."""
    _patch(monkeypatch, _snap(overall="WARNING", system_issues=["", "   "]))
    section = usb.build_agents_section()
    assert "All agents nominal" not in section, section


def test_malformed_system_issues_do_not_crash(monkeypatch):
    """A non-list value must not take the whole briefing down (fail-honest)."""
    _patch(monkeypatch, _snap(overall="WARNING", system_issues="not-a-list"))
    section = usb.build_agents_section()
    assert "Agent Health" in section
    assert "All agents nominal" not in section, section
