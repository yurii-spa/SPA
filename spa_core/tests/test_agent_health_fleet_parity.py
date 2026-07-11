"""Q3-2: agent_health surfaces fleet-parity DRIFT as a WARNING.

A retired-but-installed label (revival / Telegram-409 flood hazard), an orphan plist,
a declared-no-plist install, or a declared-not-running agent must page via agent_health
rather than sit silent in fleet_parity.json. Advisory WARNING only — fleet hygiene is
not the money-path; the track/kill checks own CRITICAL.
"""
import json
from datetime import datetime, timedelta, timezone

from spa_core.monitoring.agent_health_monitor import (
    OK,
    WARNING,
    FLEET_PARITY_STALE_H,
    check_system,
)

NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
_NONE_LOG = "/nonexistent/autopush.log"


def _write(tmp_path, hours_old, payload):
    ts = (NOW - timedelta(hours=hours_old)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "fleet_parity.json").write_text(
        json.dumps({"generated_at": ts, **payload}), encoding="utf-8"
    )


def test_fresh_ok_parity_is_not_flagged(tmp_path):
    _write(tmp_path, 1.0, {"status": "OK"})
    checks, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == OK
    assert checks["fleet_parity_status"] == "OK"
    assert not any("fleet parity" in i for i in issues)


def test_drift_warns_and_summarizes_classes(tmp_path):
    _write(tmp_path, 1.0, {
        "status": "DRIFT",
        "retired_but_installed": ["com.spa.digest_weekly", "com.spa.tier1_digest"],
        "orphan_plist_not_declared": ["com.spa.foo"],
        "live": {"declared_not_running": ["com.spa.redteam_rotation"]},
    })
    checks, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == WARNING
    drift = [i for i in issues if "fleet parity DRIFT" in i]
    assert drift, "DRIFT must page a WARNING"
    assert "2 retired-still-installed" in drift[0]
    assert "declared-not-running" in drift[0]


def test_stale_parity_warns(tmp_path):
    _write(tmp_path, FLEET_PARITY_STALE_H + 3.0, {"status": "OK"})
    checks, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == WARNING
    assert any("fleet parity stale" in i for i in issues)
    assert checks["fleet_parity_age_h"] is not None


def test_missing_parity_file_is_not_falsely_flagged(tmp_path):
    checks, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == OK
    assert checks.get("fleet_parity_status") is None
    assert not any("fleet parity" in i for i in issues)
