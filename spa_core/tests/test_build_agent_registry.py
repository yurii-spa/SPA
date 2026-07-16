"""Regression coverage for ``scripts/build_agent_registry.py`` — the deterministic SSOT
that maps the whole launchd fleet for both memory and the ``/admin/agents`` dashboard.

The module is a script (``scripts/`` has no ``__init__.py``), so — exactly like
``spa_core/api/routers/agents.py`` does at runtime — we load it by file path via
``importlib.util.spec_from_file_location``.

These tests pin the *judgement* logic that a broken build would silently corrupt:
  * schedule formatting (StartInterval / StartCalendarInterval / KeepAlive / WatchPaths);
  * the three problem-flag classes (retired-but-loaded / loaded-not-reboot-safe / drift);
  * last_exit tolerance (0 and SIGTERM -15 are clean, anything else is flagged);
  * per-role rollup excludes retired agents; problem_count matches the flags.

The build queries the live host (``launchctl`` + ``~/Library/LaunchAgents``); we inject
fakes for ``_launchctl`` / ``_retired`` and repoint ``_LAUNCH_DIR`` at a tmp dir so the
suite stays hermetic and offline (no dependency on the machine actually running SPA).
"""
from __future__ import annotations

import importlib.util
import plistlib
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BUILDER = _REPO / "scripts" / "build_agent_registry.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_agent_registry", _BUILDER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mod():
    return _load_module()


# --------------------------------------------------------------------------- _schedule

def test_schedule_start_interval_hours(mod):
    assert mod._schedule({"StartInterval": 10800}) == "каждые 3ч"


def test_schedule_start_interval_minutes(mod):
    assert mod._schedule({"StartInterval": 1800}) == "каждые 30м"


def test_schedule_start_interval_odd_seconds(mod):
    # not a whole minute -> raw seconds
    assert mod._schedule({"StartInterval": 90}) == "90с"


def test_schedule_calendar_single(mod):
    s = mod._schedule({"StartCalendarInterval": {"Hour": 8, "Minute": 5}})
    assert s.startswith("расписание")
    assert "08:05" in s


def test_schedule_calendar_list_with_weekday(mod):
    # Tue 09:00 + Fri 09:00 (novel_edge style)
    s = mod._schedule({"StartCalendarInterval": [
        {"Weekday": 2, "Hour": 9, "Minute": 0},
        {"Weekday": 5, "Hour": 9, "Minute": 0},
    ]})
    assert "Вт 09:00" in s and "Пт 09:00" in s


def test_schedule_keepalive(mod):
    assert mod._schedule({"KeepAlive": True}) == "KeepAlive (демон)"


def test_schedule_watchpaths(mod):
    assert mod._schedule({"WatchPaths": ["/some/path"]}) == "по событию (WatchPaths)"


def test_schedule_empty(mod):
    assert mod._schedule({}) == "—"


# --------------------------------------------------------------------------- build()

def _write_plist(dirpath: Path, short: str, body: dict) -> None:
    (dirpath / f"com.spa.{short}.plist").write_bytes(plistlib.dumps(body))


def _wire(mod, monkeypatch, tmp_path, *, loaded, retired):
    """Point the builder at a hermetic fleet: fake launchctl + tmp LaunchAgents dir."""
    monkeypatch.setattr(mod, "_launchctl", lambda: loaded)
    monkeypatch.setattr(mod, "_retired", lambda: set(retired))
    monkeypatch.setattr(mod, "_LAUNCH_DIR", tmp_path)


def _by_label(reg: dict) -> dict:
    return {a["label"]: a for a in reg["agents"]}


def test_build_clean_agent_no_problems(mod, monkeypatch, tmp_path):
    _write_plist(tmp_path, "daily_cycle", {"StartCalendarInterval": {"Hour": 8, "Minute": 0}})
    _wire(mod, monkeypatch, tmp_path,
          loaded={"com.spa.daily_cycle": {"pid": 123, "last_exit": 0}}, retired=set())
    reg = mod.build()
    a = _by_label(reg)["com.spa.daily_cycle"]
    assert a["loaded"] is True and a["reboot_safe"] is True
    assert a["retired"] is False and a["problems"] == []
    assert a["role"] == "allocation"  # from _ROLE map
    assert reg["problem_count"] == 0
    assert reg["total_loaded"] == 1


def test_build_retired_but_loaded_is_flagged(mod, monkeypatch, tmp_path):
    _wire(mod, monkeypatch, tmp_path,
          loaded={"com.spa.zombie": {"pid": 9, "last_exit": 0}},
          retired={"com.spa.zombie"})
    reg = mod.build()
    a = _by_label(reg)["com.spa.zombie"]
    assert a["retired"] is True and a["loaded"] is True
    assert any("RETIRED" in p for p in a["problems"])
    assert reg["problem_count"] == 1


def test_build_retired_and_not_loaded_is_clean(mod, monkeypatch, tmp_path):
    # correct end-state for a retired agent: gone from launchctl -> no problem, not in rollup
    _wire(mod, monkeypatch, tmp_path, loaded={}, retired={"com.spa.old"})
    reg = mod.build()
    a = _by_label(reg)["com.spa.old"]
    assert a["retired"] is True and a["loaded"] is False
    assert a["problems"] == []
    assert reg["problem_count"] == 0
    assert "other" not in reg["by_role"]  # retired excluded from role rollup


def test_build_loaded_but_not_reboot_safe(mod, monkeypatch, tmp_path):
    # loaded, but no plist resident in ~/Library -> won't survive reboot
    _wire(mod, monkeypatch, tmp_path,
          loaded={"com.spa.ephemeral": {"pid": 5, "last_exit": 0}}, retired=set())
    reg = mod.build()
    a = _by_label(reg)["com.spa.ephemeral"]
    assert a["reboot_safe"] is False
    assert any("reboot" in p for p in a["problems"])
    assert reg["problem_count"] == 1


def test_build_installed_but_not_loaded_is_drift(mod, monkeypatch, tmp_path):
    _write_plist(tmp_path, "sleeping", {"StartInterval": 3600})
    _wire(mod, monkeypatch, tmp_path, loaded={}, retired=set())
    reg = mod.build()
    a = _by_label(reg)["com.spa.sleeping"]
    assert a["loaded"] is False and a["reboot_safe"] is True
    assert any("drift" in p for p in a["problems"])
    assert reg["problem_count"] == 1


def test_build_last_exit_sigterm_and_zero_are_clean(mod, monkeypatch, tmp_path):
    _write_plist(tmp_path, "sigterm_job", {"KeepAlive": True})
    _write_plist(tmp_path, "zero_job", {"KeepAlive": True})
    _wire(mod, monkeypatch, tmp_path, loaded={
        "com.spa.sigterm_job": {"pid": 1, "last_exit": -15},  # SIGTERM = normal stop
        "com.spa.zero_job": {"pid": 2, "last_exit": 0},
    }, retired=set())
    reg = mod.build()
    by = _by_label(reg)
    assert by["com.spa.sigterm_job"]["problems"] == []
    assert by["com.spa.zero_job"]["problems"] == []
    assert reg["problem_count"] == 0


def test_build_last_exit_nonzero_is_flagged(mod, monkeypatch, tmp_path):
    _write_plist(tmp_path, "crasher", {"KeepAlive": True})
    _wire(mod, monkeypatch, tmp_path,
          loaded={"com.spa.crasher": {"pid": 7, "last_exit": 78}}, retired=set())
    reg = mod.build()
    a = _by_label(reg)["com.spa.crasher"]
    assert any("78" in p for p in a["problems"])
    assert reg["problem_count"] == 1


def test_build_unknown_short_falls_back_to_other_role(mod, monkeypatch, tmp_path):
    _write_plist(tmp_path, "mystery_widget", {"StartInterval": 3600})
    _wire(mod, monkeypatch, tmp_path,
          loaded={"com.spa.mystery_widget": {"pid": 3, "last_exit": 0}}, retired=set())
    reg = mod.build()
    assert _by_label(reg)["com.spa.mystery_widget"]["role"] == "other"


def test_build_role_rollup_and_shape(mod, monkeypatch, tmp_path):
    _write_plist(tmp_path, "daily_cycle", {"StartInterval": 3600})   # allocation
    _write_plist(tmp_path, "self_heal", {"KeepAlive": True})          # monitoring
    _wire(mod, monkeypatch, tmp_path, loaded={
        "com.spa.daily_cycle": {"pid": 1, "last_exit": 0},
        "com.spa.self_heal": {"pid": 2, "last_exit": 0},
    }, retired=set())
    reg = mod.build()
    assert reg["model"] == "agent_registry"
    assert reg["total_known"] == 2 and reg["total_loaded"] == 2
    assert reg["by_role"]["allocation"] == 1
    assert reg["by_role"]["monitoring"] == 1
    assert set(reg["roles"]) == {"infra", "allocation", "monitoring", "reporting", "research", "other"}
    assert "generated_at" in reg
