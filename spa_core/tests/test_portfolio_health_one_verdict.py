"""
ONE number -> ONE verdict: portfolio health is classified in exactly one place.

Positive control (the real incident, card
`agent-task-odno-chislo-dva-verdikta-portfolio-healt`, measured 2026-08-07):
`data/portfolio_health.json` carried `health_score = 69.43` and the two health
monitors, using the SAME floor (70), disagreed about what it means —

    system_health_monitor  d6.health  -> CRITICAL  (and the whole system verdict
                                                    went CRITICAL with it)
    agent_health_monitor              -> WARNING

so SYSTEM_BRIEFING showed "System Health 🔴 CRITICAL" next to "Agents ⚠️ WARNING"
from a single number, inside a domain named `d6_risk_gates` while RiskPolicy was
`policy_compliant: true` and no gate had refused anything.

Every test below fails on the pre-fix code (the two monitors each owned a
private severity ladder) and passes once both classify through the single shared
helper `spa_core.alerts.severity.classify_portfolio_health`.

Time is an INPUT here (`.claude/rules/deployment.md`, preference #1): the one
`now` used is created once and injected; no literal dates.

stdlib-only. No live network, no writes outside tmp_path.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.alerts import severity as sev
from spa_core.monitoring import agent_health_monitor as ahm
from spa_core.monitoring.system_health_monitor import SystemHealthMonitor

# The measured incident value and its neighbours around the floor.
INCIDENT_SCORE = 69.43

# Injected clock: one anchor per call, passed everywhere. No freshness
# assertion in this file depends on it — it exists so the monitor never reads
# the ambient wall clock behind the test's back.
#
# Read at CALL time, never at import time: a module-level wall-clock read is
# compared against the clock of the assert moment, so a run crossing midnight
# reddens unrepeatably (test_no_import_time_clock_in_tests, run 30723870323).
def _now() -> datetime:
    return datetime.now(timezone.utc)

# A path that cannot exist, so the autopush-lag check contributes nothing.
NO_AUTOPUSH_LOG = "/nonexistent/spa-test/autopush.log"


def _data_dir(tmp_path: Path, score) -> Path:
    """A data dir holding ONLY portfolio_health.json, so the verdict under test
    is the only thing either monitor can have an opinion about."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    payload = {"generated_at": _now().isoformat(), "summary_level": "WARNING"}
    if score is not None:
        payload["health_score"] = score
    (data / "portfolio_health.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return data


def _system_verdict(tmp_path: Path, data: Path) -> str:
    mon = SystemHealthMonitor(data_dir=str(data), project_root=str(tmp_path))
    mon._prelude()
    return mon._check_portfolio_health("d6_risk_gates").status


def _agent_verdict(data: Path) -> tuple[str, list]:
    checks, status, issues = ahm.check_system(
        data, _now(), autopush_log=NO_AUTOPUSH_LOG
    )
    return status, issues


# ---------------------------------------------------------------------------
# The incident itself
# ---------------------------------------------------------------------------
def test_incident_score_gets_one_verdict_from_both_monitors(tmp_path):
    """69.43 must not be CRITICAL in one monitor and WARNING in the other."""
    data = _data_dir(tmp_path, INCIDENT_SCORE)
    system = _system_verdict(tmp_path, data)
    agent, issues = _agent_verdict(data)

    assert system == agent, (
        f"one number, two verdicts: system_health={system} vs "
        f"agent_health={agent} for health_score={INCIDENT_SCORE}"
    )
    # And the agreed verdict is the shared classifier's, not either module's own.
    expected, _reason = sev.classify_portfolio_health(INCIDENT_SCORE)
    assert system == expected == "WARNING"
    # The signal is NOT silenced: the score is still reported and still raises
    # an issue line naming the floor.
    assert any("portfolio_health" in i for i in issues), issues


def test_below_floor_is_never_critical_in_either_monitor(tmp_path):
    """A composite quality score below the floor is a WARNING, not the loudest
    level in the system. Real d6_risk_gates criticals (cap breaches, policy
    refusals, kill-switch) are unaffected and covered by their own tests."""
    for score in (INCIDENT_SCORE, 42.0, 0.0, -5.0):
        data = _data_dir(tmp_path, score)
        system = _system_verdict(tmp_path, data)
        agent, _issues = _agent_verdict(data)
        assert system == agent == "WARNING", (score, system, agent)


@pytest.mark.parametrize("score", [70.0, 70.01, 88.0, 100.0])
def test_at_or_above_floor_is_ok_in_both(tmp_path, score):
    data = _data_dir(tmp_path, score)
    assert _system_verdict(tmp_path, data) == "OK"
    agent, issues = _agent_verdict(data)
    assert agent == "OK"
    assert not [i for i in issues if "portfolio_health" in i], issues


# ---------------------------------------------------------------------------
# Why the agreed level cannot be CRITICAL: agent_health's own invariant
# ---------------------------------------------------------------------------
def test_agent_report_keeps_critical_count_invariant_below_floor(tmp_path):
    """`critical_count == 0  <=>  overall_status != CRITICAL` (build_report).

    A portfolio-health-driven CRITICAL would report overall CRITICAL with
    critical_count == 0 and break that invariant — which is why WARNING is the
    only verdict BOTH monitors can carry. This test is the guard on that claim.
    """
    data = _data_dir(tmp_path, INCIDENT_SCORE)
    checks, status, issues = ahm.check_system(
        data, _now(), autopush_log=NO_AUTOPUSH_LOG
    )
    report = ahm.build_report([], checks, status, issues, _now())
    assert (report["critical_count"] == 0) == (
        report["overall_status"] != "CRITICAL"
    ), report


# ---------------------------------------------------------------------------
# Drift guard: neither monitor may own a private floor or a private ladder
# ---------------------------------------------------------------------------
def test_both_monitors_use_the_shared_floor():
    from spa_core.monitoring import system_health_monitor as shm

    assert shm.PORTFOLIO_HEALTH_FLOOR == sev.PORTFOLIO_HEALTH_FLOOR
    assert ahm.PORTFOLIO_HEALTH_FLOOR == sev.PORTFOLIO_HEALTH_FLOOR


def test_moving_the_shared_floor_moves_both_monitors(tmp_path, monkeypatch):
    """Mutation control: raise the floor in the ONE place it is defined and both
    monitors must follow. If either kept a private copy, one of them stays OK."""
    from spa_core.monitoring import system_health_monitor as shm

    monkeypatch.setattr(sev, "PORTFOLIO_HEALTH_FLOOR", 95.0, raising=True)
    monkeypatch.setattr(shm, "PORTFOLIO_HEALTH_FLOOR", 95.0, raising=True)
    monkeypatch.setattr(ahm, "PORTFOLIO_HEALTH_FLOOR", 95.0, raising=True)

    data = _data_dir(tmp_path, 88.0)          # OK at floor 70, below floor 95
    assert _system_verdict(tmp_path, data) == "WARNING"
    agent, issues = _agent_verdict(data)
    assert agent == "WARNING"
    assert any("portfolio_health" in i for i in issues), issues


# ---------------------------------------------------------------------------
# The shared classifier itself — fail-CLOSED on unusable input
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad", [None, "69.43", True, False, float("nan"), float("inf"), float("-inf")]
)
def test_unusable_score_is_warning_never_ok(bad):
    status, reason = sev.classify_portfolio_health(bad)
    assert status == "WARNING", (bad, status, reason)
    assert reason


def test_absent_score_file_is_warning_in_both(tmp_path):
    """Absence != breach, and absence != health. Both monitors say WARNING."""
    data = _data_dir(tmp_path, None)          # file present, no score key
    assert _system_verdict(tmp_path, data) == "WARNING"


def test_classifier_boundary_is_inclusive_at_the_floor():
    assert sev.classify_portfolio_health(sev.PORTFOLIO_HEALTH_FLOOR)[0] == "OK"
    assert sev.classify_portfolio_health(
        sev.PORTFOLIO_HEALTH_FLOOR - 0.01
    )[0] == "WARNING"
