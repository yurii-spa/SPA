"""
tests/test_monitor_severity_and_flood_hardening.py
===================================================
Architect N8+N9 hardening tests for the SPA monitoring/alerting layer.

N8 — severity-vocab unification + portfolio_health field unification:
  * A red-flag writer emitting a DIFFERENT critical spelling ("WARNING" stays a
    warning; "CRITICAL"/"CRIT"/"FATAL" all count as critical) is still matched by
    BOTH consumers via the shared SET — a rename can never silently disable
    critical detection.
  * Both health monitors read the ACTUAL portfolio_health.json key the writer
    emits ("health_score") via the one shared helper.

N9 — alert-flood:
  * A single-tick agent skip (file fresh within widened window) does NOT flip
    all_ok to DOWN.
  * An agent with no judgeable verdict (running=None) does NOT flip all_ok.
  * The pre-dawn self-healing dip (same / shrinking critical set) does NOT
    re-page; a genuinely-new critical DOES page.

stdlib-only / deterministic — no network, no real launchctl.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.alerts import severity as sev
from spa_core.monitoring import system_health_monitor as shm
from spa_core.monitoring.system_health_monitor import (
    SystemHealthMonitor, CRITICAL, OK, WARNING,
)
from spa_core.monitoring import agent_health_monitor as ahm
from spa_core.monitoring import uptime_monitor as um


# ===========================================================================
# N8 — shared severity vocabulary
# ===========================================================================
def test_severity_set_matches_synonyms_not_single_literal():
    # canonical
    assert sev.is_critical("CRITICAL")
    # synonyms a future writer might rename to — all still critical
    assert sev.is_critical("CRIT")
    assert sev.is_critical("FATAL")
    assert sev.is_critical("emergency")  # case-insensitive
    # warnings are NOT critical
    assert not sev.is_critical("WARN")
    assert not sev.is_critical("WARNING")
    assert not sev.is_critical(None)
    assert not sev.is_critical(123)


def test_warning_vocab_widened_warn_and_warning():
    # The motivating false-negative: a writer changes "WARN" -> "WARNING".
    assert sev.is_warning("WARN")
    assert sev.is_warning("WARNING")
    assert not sev.is_warning("CRITICAL")


def test_red_flag_monitor_emits_shared_vocab():
    from spa_core.alerts import red_flag_monitor as rfm
    # The writer's SEVERITIES must BE the shared vocabulary (single source).
    assert rfm.SEVERITIES == sev.SEVERITIES
    assert rfm.SEV_CRITICAL in sev.CRITICAL_SEVERITIES
    assert sev.is_warning(rfm.SEV_WARN)


# --- a "WARNING"-spelling writer is still caught by BOTH consumers as critical
#     when the level is a critical synonym; and a renamed critical is caught ----
def _shm_red_flag_check(tmp_path: Path, flags: list, positions: dict | None = None):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "red_flags.json").write_text(
        json.dumps({"red_flags": flags, "fallback_used": False}), encoding="utf-8")
    if positions is not None:
        (data / "current_positions.json").write_text(
            json.dumps({"positions": positions}), encoding="utf-8")
    mon = SystemHealthMonitor(data_dir=str(data), project_root=str(tmp_path))
    mon._prelude()
    return mon._check_red_flags("d6_risk_gates")


def test_shm_consumer_catches_renamed_critical_on_held(tmp_path):
    # Writer emits "CRIT" (a renamed critical) on a HELD protocol -> must be CRITICAL.
    res = _shm_red_flag_check(
        tmp_path,
        flags=[{"protocol": "aave_v3", "severity": "CRIT", "message": "boom"}],
        positions={"aave_v3": 50_000.0},
    )
    assert res.status == CRITICAL


def test_shm_consumer_catches_fatal_severity(tmp_path):
    # A future "FATAL" spelling on a held protocol must still page.
    res = _shm_red_flag_check(
        tmp_path,
        flags=[{"protocol": "euler_v2", "severity": "FATAL", "message": "x"}],
        positions={"euler_v2": 30_000.0},
    )
    assert res.status == CRITICAL


def test_shm_consumer_warning_spelling_not_critical(tmp_path):
    # "WARNING" must NOT be treated as critical (no false-positive page).
    res = _shm_red_flag_check(
        tmp_path,
        flags=[{"protocol": "aave_v3", "severity": "WARNING", "message": "minor"}],
        positions={"aave_v3": 50_000.0},
    )
    assert res.status == OK  # no CRITICAL flags at all


def test_agent_health_consumer_catches_renamed_critical(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "red_flags.json").write_text(
        json.dumps({"red_flags": [
            {"protocol": "aave_v3", "severity": "CRIT", "message": "x"}],
            "fallback_used": False}), encoding="utf-8")
    (data / "current_positions.json").write_text(
        json.dumps({"positions": {"aave_v3": 40_000.0}}), encoding="utf-8")
    now = datetime.now(timezone.utc)
    checks, status, issues = ahm.check_system(data, now)
    assert status == ahm.CRITICAL
    assert checks.get("critical_flags") == 1


# ===========================================================================
# N8 — portfolio_health field unification
# ===========================================================================
def test_read_portfolio_health_score_prefers_written_key():
    # Writer emits "health_score"; helper must read it.
    assert sev.read_portfolio_health_score({"health_score": 82.5}) == 82.5
    # legacy alias still works
    assert sev.read_portfolio_health_score({"score": 71.0}) == 71.0
    # booleans rejected, missing -> None
    assert sev.read_portfolio_health_score({"health_score": True}) is None
    assert sev.read_portfolio_health_score({}) is None
    assert sev.read_portfolio_health_score("nope") is None


def test_shm_portfolio_health_reads_health_score_key(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    # writer's real shape: {"health_score": ...} (NOT "score")
    (data / "portfolio_health.json").write_text(
        json.dumps({"health_score": 50.0, "summary_level": "CRITICAL"}),
        encoding="utf-8")
    mon = SystemHealthMonitor(data_dir=str(data), project_root=str(tmp_path))
    mon._prelude()
    res = mon._check_portfolio_health("d6_risk_gates")
    # 50 < floor(70) -> CRITICAL, and the score was actually READ (value set).
    assert res.value == 50.0
    assert res.status == CRITICAL


def test_agent_health_portfolio_reads_health_score_key(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "portfolio_health.json").write_text(
        json.dumps({"health_score": 88.0}), encoding="utf-8")
    now = datetime.now(timezone.utc)
    checks, _status, _issues = ahm.check_system(data, now)
    assert checks.get("portfolio_health_score") == 88.0


# ===========================================================================
# N9(a) — uptime: single-tick skip / no-verdict does NOT flip all_ok
# ===========================================================================
def _fresh(data_dir: Path, rel: str, age_s: float = 0.0):
    p = data_dir.parent / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}", encoding="utf-8")
    t = time.time() - age_s
    import os
    os.utime(p, (t, t))


def test_single_tick_skip_within_window_stays_alive(tmp_path):
    # An hourly agent (analytics_tier_b) that skipped one tick: file ~70 min old,
    # window is now 3h (10800s) -> still ALIVE (running True), NOT a DOWN flip.
    chk = um.check_agent_by_output(
        "com.spa.analytics_tier_b",
        base_dir=tmp_path,
    )
    # No file yet -> missing. Now create one ~70 min old and re-check.
    (tmp_path / "data").mkdir(exist_ok=True)
    f = tmp_path / "data" / "analytics_signals_advisory.json"
    f.write_text("{}", encoding="utf-8")
    import os
    t = time.time() - 70 * 60
    os.utime(f, (t, t))
    chk = um.check_agent_by_output("com.spa.analytics_tier_b", base_dir=tmp_path)
    assert chk["running"] is True, chk
    assert chk["max_age"] >= 3 * 3600


def test_daily_cycle_window_spans_full_day(tmp_path):
    # daily_cycle runs once at 08:00 UTC; a status file written ~20h ago must NOT
    # read as DOWN (the old 90-min window was the dominant false-DOWN source).
    (tmp_path / "data").mkdir(exist_ok=True)
    f = tmp_path / "data" / "paper_trading_status.json"
    f.write_text("{}", encoding="utf-8")
    import os
    t = time.time() - 20 * 3600
    os.utime(f, (t, t))
    chk = um.check_agent_by_output("com.spa.daily_cycle", base_dir=tmp_path)
    assert chk["running"] is True, chk
    assert chk["max_age"] >= 24 * 3600


def test_all_ok_ignores_none_verdict():
    # An agent with running=None (no judgeable signal) must NOT flip all_ok.
    checks = {
        "launchd_a": {"running": True},
        "launchd_b": {"running": None},   # no verdict -> excluded
        "http_server": {"ok": True},
        "cycle_freshness": {"ok": True},
        "git_push": {"ok": True},
    }
    ok_flags = []
    for key, chk in checks.items():
        if key.startswith("launchd_"):
            running = chk.get("running", False)
            if running is None:
                continue
            ok_flags.append(bool(running))
        else:
            ok_flags.append(bool(chk.get("ok", False)))
    assert all(ok_flags) is True


def test_run_all_checks_none_verdict_not_down(tmp_path, monkeypatch):
    # End-to-end: stub check_agent so one agent returns running=None; all_ok must
    # remain True (no false DOWN), and a genuinely-running set stays OK.
    data = tmp_path / "data"
    data.mkdir()
    repo = tmp_path

    def fake_check_agent(label, base_dir=None):
        if label == "com.spa.daily-paper-report":
            return {"running": None, "method": "no_output_file"}
        return {"running": True, "method": "launchctl_pid"}

    monkeypatch.setattr(um, "check_agent", fake_check_agent)
    monkeypatch.setattr(um, "check_http_server", lambda port=8765: {"ok": True})
    monkeypatch.setattr(um, "check_cycle_freshness", lambda d: {"ok": True})
    monkeypatch.setattr(um, "check_git_push", lambda d: {"ok": True})
    # silence alerting + prev-state side effects
    monkeypatch.setattr(um, "_process_agent_alerts", lambda *a, **k: {})

    result = um.run_all_checks(data_dir=data, repo_dir=repo)
    assert result["all_ok"] is True


def test_daily_paper_report_no_longer_file_judged():
    # de-dup: daily-paper-report must NOT share paper_trading_status.json as its
    # liveness file (that file backs daily_cycle only).
    mapping = um.AGENT_OUTPUT_FILES["com.spa.daily-paper-report"]
    assert mapping[0] is None
    # And exactly one label is backed by paper_trading_status.json.
    backers = [lbl for lbl, (f, _a) in um.AGENT_OUTPUT_FILES.items()
               if f == "data/paper_trading_status.json"]
    assert backers == ["com.spa.daily_cycle"], backers


# ===========================================================================
# N9(b) — system_health: pre-dawn dip does NOT re-page; new critical DOES
# ===========================================================================
def _mon(tmp_path):
    (tmp_path / "data").mkdir(exist_ok=True)
    return SystemHealthMonitor(data_dir=str(tmp_path / "data"),
                               project_root=str(tmp_path))


def test_predawn_dip_same_critical_set_does_not_repage(tmp_path):
    mon = _mon(tmp_path)
    # Same single critical present in both runs -> no NEW critical -> no page.
    report = {"checks": [{"id": "d1.golive.count", "status": CRITICAL}]}
    prev = {"checks": [{"id": "d1.golive.count", "status": CRITICAL}]}
    assert mon._new_critical(report, prev) is False


def test_critical_clearing_does_not_page(tmp_path):
    mon = _mon(tmp_path)
    # Critical set SHRINKS (recovery) -> not a page.
    report = {"checks": [{"id": "x", "status": CRITICAL}]}
    prev = {"checks": [{"id": "x", "status": CRITICAL},
                       {"id": "y", "status": CRITICAL}]}
    assert mon._new_critical(report, prev) is False


def test_genuinely_new_critical_pages(tmp_path):
    mon = _mon(tmp_path)
    report = {"checks": [{"id": "x", "status": CRITICAL},
                         {"id": "z", "status": CRITICAL}]}
    prev = {"checks": [{"id": "x", "status": CRITICAL}]}
    assert mon._new_critical(report, prev) is True


def test_first_critical_with_no_prev_pages(tmp_path):
    mon = _mon(tmp_path)
    report = {"checks": [{"id": "x", "status": CRITICAL}]}
    assert mon._new_critical(report, None) is True
