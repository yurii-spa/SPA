"""Tests for the Q3-2 fleet-parity self-check (scripts/fleet_parity_check.py).

Verifies the three drift categories are detected deterministically on injected fixtures (no dependence
on the live installer / launchctl), that a fully-consistent fleet reports OK, and that the live
launchctl comparison degrades to `unavailable` rather than failing. Also runs the LIVE check to prove
it executes end-to-end without raising (its status may legitimately be DRIFT — that's its job).
"""
import importlib

import pytest

fpc = importlib.import_module("scripts.fleet_parity_check")


def _patch(monkeypatch, declared, plist, retired, live=None):
    monkeypatch.setattr(fpc, "declared_labels", lambda: set(declared))
    monkeypatch.setattr(fpc, "plist_labels", lambda: set(plist))
    monkeypatch.setattr(fpc, "retired_labels", lambda: set(retired))
    monkeypatch.setattr(fpc, "_live_labels", lambda: (set(live) if live is not None else None))


def test_consistent_fleet_is_ok(monkeypatch):
    _patch(monkeypatch,
           declared={"com.spa.a", "com.spa.b"},
           plist={"com.spa.a", "com.spa.b", "com.spa.old"},
           retired={"com.spa.old"})           # old has a plist but is retired → not an orphan
    rep = fpc.build_report(write=False)
    assert rep["status"] == "OK"
    assert rep["broken_declared_no_plist"] == []
    assert rep["orphan_plist_not_declared"] == []
    assert rep["retired_but_installed"] == []


def test_broken_declared_without_plist(monkeypatch):
    _patch(monkeypatch, declared={"com.spa.a", "com.spa.ghost"}, plist={"com.spa.a"}, retired=set())
    rep = fpc.build_report(write=False)
    assert rep["status"] == "DRIFT"
    assert rep["broken_declared_no_plist"] == ["com.spa.ghost"]


def test_orphan_plist_not_declared(monkeypatch):
    _patch(monkeypatch, declared={"com.spa.a"}, plist={"com.spa.a", "com.spa.stray"}, retired=set())
    rep = fpc.build_report(write=False)
    assert rep["status"] == "DRIFT"
    assert rep["orphan_plist_not_declared"] == ["com.spa.stray"]


def test_retired_but_still_installed(monkeypatch):
    _patch(monkeypatch, declared={"com.spa.a", "com.spa.zombie"},
           plist={"com.spa.a", "com.spa.zombie"}, retired={"com.spa.zombie"})
    rep = fpc.build_report(write=False)
    assert rep["status"] == "DRIFT"
    assert rep["retired_but_installed"] == ["com.spa.zombie"]


def test_live_unavailable_is_not_a_failure(monkeypatch):
    _patch(monkeypatch, declared={"com.spa.a"}, plist={"com.spa.a"}, retired=set(), live=None)
    rep = fpc.build_report(write=False)
    assert rep["live"]["available"] is False
    assert rep["status"] == "OK"


def test_live_comparison_when_available(monkeypatch):
    _patch(monkeypatch, declared={"com.spa.a", "com.spa.b"},
           plist={"com.spa.a", "com.spa.b"}, retired=set(),
           live={"com.spa.a"})                # b declared+plist but not running
    rep = fpc.build_report(write=False)
    assert rep["live"]["available"] is True
    assert rep["live"]["declared_not_running"] == ["com.spa.b"]


def test_live_check_runs_without_raising():
    # end-to-end against the REAL sources — status may be OK or DRIFT, but it must not raise.
    rep = fpc.build_report(write=False)
    assert rep["status"] in ("OK", "DRIFT")
    assert isinstance(rep["n_declared"], int) and rep["n_declared"] > 0


def test_commented_installer_lines_not_declared(monkeypatch, tmp_path):
    """A commented-out install_agent block must NOT count as a declared install (the httpserver
    false-positive fix)."""
    fake = tmp_path / "install.sh"
    fake.write_text(
        'install_agent \\\n'
        '    "$REPO/scripts/com.spa.live.plist" \\\n'
        '    "com.spa.live" \\\n'
        '    "1"\n'
        '#    "$REPO/scripts/com.spa.dead.plist" \\\n'
        '#    "com.spa.dead" \\\n'
    )
    monkeypatch.setattr(fpc, "_INSTALLER", fake)
    labels = fpc.declared_labels()
    assert "com.spa.live" in labels
    assert "com.spa.dead" not in labels
