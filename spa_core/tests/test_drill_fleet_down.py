"""
spa_core/tests/test_drill_fleet_down.py — tests for the INERT fleet-down drill.

Proves the drill harness (scripts/drill_fleet_down.py):
  * runs deterministically and PASSES on its built-in scenarios,
  * NEVER calls launchctl / subprocess (inert),
  * a fixture with a RETIRED agent loaded → "would bootout, never revive",
  * a fixture with a resident agent missing → "would revive",
  * an idle-calendar fixture (RunAtLoad:False, not loaded) → "skip" (not revived),
  * the retired-never-revived assertion holds across ALL scenarios,
  * the decision logic is sourced from the REAL monitoring module (not a copy).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from spa_core.monitoring.agent_health_monitor import RETIRED_LABELS

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "drill_fleet_down.py"


def _load_drill():
    """Import the drill script as a module (it lives under scripts/, not a package)."""
    spec = importlib.util.spec_from_file_location("drill_fleet_down", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def drill():
    return _load_drill()


# --------------------------------------------------------------------------- #
# Determinism + overall PASS
# --------------------------------------------------------------------------- #
def test_drill_runs_deterministically_and_passes(drill):
    r1 = drill.run_drill()
    r2 = drill.run_drill()
    assert r1["passed"] is True
    assert r2["passed"] is True
    # identical except for the timestamp
    r1.pop("generated_at")
    r2.pop("generated_at")
    assert r1 == r2, "drill must be deterministic across runs"
    assert not r1["assertion_failures"]


def test_drill_is_inert_metadata(drill):
    r = drill.run_drill()
    assert r["is_drill"] is True
    assert r["calls_launchctl"] is False
    assert r["boots_anything"] is False
    assert r["llm_forbidden"] is True


def test_decision_logic_sourced_from_real_module(drill):
    """The drill must import the REAL functions, not a divergent copy."""
    from spa_core.monitoring import agent_health_monitor as ahm
    assert drill.requires_residency is ahm.requires_residency
    assert drill.classify_agent is ahm.classify_agent
    assert drill.RETIRED_LABELS is ahm.RETIRED_LABELS


def test_drill_never_calls_subprocess(monkeypatch, drill):
    """Hard inertness proof: a poisoned subprocess.run must NEVER be reached."""
    import subprocess

    def _boom(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("drill called subprocess — NOT inert")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    r = drill.run_drill()  # must complete with zero subprocess calls
    assert r["passed"] is True


# --------------------------------------------------------------------------- #
# Per-scenario behaviour
# --------------------------------------------------------------------------- #
def test_retired_loaded_fixture_would_bootout_never_revive(drill):
    sc = [s for s in drill.run_drill()["scenarios"]
          if s["scenario"] == "retired_still_loaded"][0]
    rec = sc["recovery"]
    # A retired agent lingering loaded is flagged for bootout ...
    assert rec["retired_lingering_loaded_would_bootout"], \
        "retired_still_loaded fixture must have a retired agent flagged for bootout"
    # ... and is NEVER in the revive set.
    assert not (set(rec["retired_lingering_loaded_would_bootout"])
                & set(rec["would_revive"]))
    assert not (set(rec["would_revive"]) & set(RETIRED_LABELS))


def test_missing_resident_fixture_would_revive(drill):
    sc = [s for s in drill.run_drill()["scenarios"]
          if s["scenario"] == "all_down"][0]
    rec = sc["recovery"]
    # all_down → every resident-required agent is genuinely missing → all revived.
    assert rec["would_revive"], "missing residents must be in the revive set"
    # KeepAlive + StartInterval residents present in the revive set.
    assert "com.spa.apiserver" in rec["would_revive"]      # KeepAlive daemon
    assert "com.spa.rules_watchdog" in rec["would_revive"]  # StartInterval guardian


def test_idle_calendar_fixture_skipped_not_revived(drill):
    sc = [s for s in drill.run_drill()["scenarios"]
          if s["scenario"] == "idle_calendar_not_loaded"][0]
    rec = sc["recovery"]
    # Residents all up → nothing to revive; calendar agents idle → skipped.
    assert rec["would_revive"] == []
    assert rec["would_skip_idle_calendar"], "idle calendar agents must be in the skip set"
    assert "com.spa.daily_cycle" in rec["would_skip_idle_calendar"]
    # An idle calendar agent must NEVER be in the revive set.
    assert not (set(rec["would_skip_idle_calendar"]) & set(rec["would_revive"]))


def test_half_down_revives_only_missing_residents(drill):
    sc = [s for s in drill.run_drill()["scenarios"]
          if s["scenario"] == "half_down"][0]
    rec = sc["recovery"]
    # Only the residents NOT in the loaded set get revived; loaded ones are left.
    for lbl in rec["loaded"]:
        assert lbl not in rec["would_revive"], "a loaded agent must not be revived"
    # Idle calendar still skipped, retired still never revived.
    assert not (set(rec["would_revive"]) & set(RETIRED_LABELS))


# --------------------------------------------------------------------------- #
# The headline invariant: retired NEVER revived, across EVERY scenario.
# --------------------------------------------------------------------------- #
def test_no_retired_ever_revived_across_all_scenarios(drill):
    report = drill.run_drill()
    for sc in report["scenarios"]:
        revived = set(sc["recovery"]["would_revive"])
        assert not (revived & set(RETIRED_LABELS)), (
            f"scenario {sc['scenario']} would revive a RETIRED label: "
            f"{sorted(revived & set(RETIRED_LABELS))}"
        )
    # And the report-level aggregate agrees.
    assert report["passed"] is True


def test_every_scenario_has_all_four_invariant_checks(drill):
    report = drill.run_drill()
    expected_checks = {
        "no_retired_ever_revived",
        "idle_calendar_not_revived",
        "missing_residents_all_revived",
        "retired_lingering_booted_not_revived",
    }
    assert report["scenarios"], "drill must define at least one scenario"
    for sc in report["scenarios"]:
        names = {c["name"] for c in sc["checks"]}
        assert expected_checks <= names, f"{sc['scenario']} missing checks: {expected_checks - names}"
        assert all(c["ok"] for c in sc["checks"]), f"{sc['scenario']} has a failing check"


def test_retired_skip_set_covers_all_installed_retired(drill):
    """Every RETIRED label installed in the fixture appears in would_skip_retired."""
    report = drill.run_drill()
    for sc in report["scenarios"]:
        skip = set(sc["recovery"]["would_skip_retired"])
        # Base fleet installs every RETIRED_LABELS entry.
        assert set(RETIRED_LABELS) <= skip
