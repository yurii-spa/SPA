"""Q1-10: agent_health escalates a stale/failed resilience DR posture to WARNING.

A rotting DR proof-chain (com.spa.resilience not running, or a drill/offsite
failing) must page via agent_health rather than sit silent in resilience_status.json.
Advisory WARNING only — DR is not the money-path; the track/kill checks own CRITICAL.
"""
import json
from datetime import datetime, timedelta, timezone

from spa_core.monitoring.agent_health_monitor import (
    OK,
    WARNING,
    RESILIENCE_STALE_H,
    check_system,
)

NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
_NONE_LOG = "/nonexistent/autopush.log"  # → file_age_minutes None → skipped


def _write(tmp_path, hours_old, overall):
    ts = (NOW - timedelta(hours=hours_old)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "resilience_status.json").write_text(
        json.dumps({"generated_at": ts, "overall": overall}), encoding="utf-8"
    )


def test_fresh_ok_posture_is_not_flagged(tmp_path):
    _write(tmp_path, 1.0, "OK")
    checks, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == OK
    assert checks["resilience_posture"] == "OK"
    assert not any("resilience" in i for i in issues)


def test_stale_posture_warns(tmp_path):
    _write(tmp_path, RESILIENCE_STALE_H + 5.0, "OK")
    checks, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == WARNING
    assert any("resilience posture stale" in i for i in issues)
    assert checks["resilience_age_h"] is not None


def test_nonok_posture_warns(tmp_path):
    _write(tmp_path, 1.0, "WARNING")
    checks, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == WARNING
    assert checks["resilience_posture"] == "WARNING"
    assert any("resilience posture WARNING" in i for i in issues)


def test_missing_posture_file_is_not_falsely_flagged(tmp_path):
    # Consistent with the other system checks (all `if <loaded>:`) so sandbox/CI
    # fixtures without the file don't newly WARN; a truly-missing prod posture is
    # caught by the per-agent freshness check for com.spa.resilience.
    checks, status, issues = check_system(tmp_path, NOW, autopush_log=_NONE_LOG)
    assert status == OK
    assert checks["resilience_posture"] is None
    assert not any("resilience" in i for i in issues)
