"""An agent the owner switched off with ``launchctl disable`` is PAUSED, not DOWN.

Replays the 2026-09-30 post-reboot finding: ``com.spa.mission_tick`` was paused
(``bootout`` + ``disable``). agent_health rated the whole fleet CRITICAL for it,
self_heal tried to ``bootstrap`` it every 5 minutes and reboot_verify tried again
at login — only launchd's own refusal kept the paused workload from coming back.

Each test pins one side: the pause is recognised; a genuinely dead resident agent
is still CRITICAL; an unreadable override list hides nothing (fail-CLOSED).
Hermetic: every launchctl answer is injected, the host is never asked.
"""
from __future__ import annotations

import plistlib
from pathlib import Path

from spa_core.monitoring import agent_health_monitor as ahm
from spa_core.monitoring import self_heal

PAUSED = "com.spa.mission_tick"
DEAD = "com.spa.rtmr_sense"

MODERN = f'''disabled services = {{
\t\t"com.ollama.ollama" => enabled
\t\t"{PAUSED}" => disabled
\t}}
'''
LEGACY = f'''disabled services = {{
\t\t"{PAUSED}" => true
\t\t"com.spa.other" => false
\t}}
'''


def _resident_plist(la: Path, label: str) -> None:
    with open(la / f"{label}.plist", "wb") as f:
        plistlib.dump({"Label": label, "ProgramArguments": ["/bin/true"],
                       "StartInterval": 900}, f)


def _agents(tmp_path: Path, disabled_output):
    la = tmp_path / "LaunchAgents"
    la.mkdir()
    for lbl in (PAUSED, DEAD):
        _resident_plist(la, lbl)
    data = tmp_path / "data"
    data.mkdir()
    mon = ahm.AgentHealthMonitor(data_dir=data, launch_agents_dir=la,
                                 launchctl_output="",  # nothing loaded
                                 launchctl_disabled_output=disabled_output)
    return {a["label"]: a for a in mon.collect()["agents"]}


def test_parse_both_launchctl_formats():
    assert ahm.parse_launchctl_disabled(MODERN) == {"com.ollama.ollama": False, PAUSED: True}
    assert ahm.parse_launchctl_disabled(LEGACY) == {PAUSED: True, "com.spa.other": False}
    assert ahm.launchd_disabled_labels(MODERN) == frozenset({PAUSED})


def test_paused_agent_is_not_critical_but_dead_one_still_is(tmp_path):
    agents = _agents(tmp_path, MODERN)
    assert agents[PAUSED]["status"] == ahm.OK
    assert "intentionally disabled" in agents[PAUSED]["note"]
    assert agents[DEAD]["status"] == ahm.CRITICAL  # the pause hides nothing else


def test_positive_control_without_override_list_the_pause_reads_as_outage(tmp_path):
    # Injected `launchctl list` but no override list ⇒ the host is NOT consulted
    # and the pause is unknown — exactly the pre-fix behaviour, so it is CRITICAL.
    agents = _agents(tmp_path, None)
    assert agents[PAUSED]["status"] == ahm.CRITICAL


def test_unreadable_override_list_is_not_measured_not_empty(monkeypatch):
    monkeypatch.setattr(ahm, "_run_launchctl_disabled", lambda: None)
    assert ahm.launchd_disabled_labels() is None
    monkeypatch.setattr(self_heal, "launchd_disabled_labels", lambda: None)
    assert self_heal._disabled_labels() == frozenset()


def test_self_heal_never_expects_a_paused_agent(tmp_path, monkeypatch):
    for lbl in (PAUSED, DEAD):
        _resident_plist(tmp_path, lbl)
    monkeypatch.setattr(self_heal, "_LA", tmp_path)
    monkeypatch.setattr(self_heal, "_disabled_labels", lambda: frozenset({PAUSED}))
    assert self_heal._expected_labels() == [DEAD]
    # control: with no pause recorded, both are expected (and would be revived)
    monkeypatch.setattr(self_heal, "_disabled_labels", lambda: frozenset())
    assert self_heal._expected_labels() == sorted([PAUSED, DEAD])
