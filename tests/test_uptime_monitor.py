"""
tests/test_uptime_monitor.py
============================
Tests for spa_core/monitoring/uptime_monitor.py (P0-1 fix).

Focus:
  * Exit-code policy: default run → 0 even when DEGRADED (the bug that produced
    launchd exit 256); --strict → 1 on DEGRADED; internal failure → 1.
  * Fail-safe checks never raise (missing files, missing binaries, bad JSON).
  * BASE_DIR resolves three parents up to the repo root.
  * Atomic status-file write.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


from spa_core.monitoring import uptime_monitor as um


# ---------------------------------------------------------------------------
# BASE_DIR / path resolution
# ---------------------------------------------------------------------------

def test_base_dir_is_repo_root():
    """BASE_DIR must be three parents up from spa_core/monitoring/uptime_monitor.py."""
    expected = Path(um.__file__).resolve().parent.parent.parent
    assert um.BASE_DIR == expected
    # Sanity: the repo root should contain spa_core/
    assert (um.BASE_DIR / "spa_core").is_dir()


# ---------------------------------------------------------------------------
# check_cycle_freshness — fail-safe + correctness
# ---------------------------------------------------------------------------

def test_cycle_freshness_missing_file(tmp_path):
    res = um.check_cycle_freshness(tmp_path)
    assert res["ok"] is False
    assert res["error"] and "not found" in res["error"]


def test_cycle_freshness_bad_json(tmp_path):
    (tmp_path / "paper_trading_status.json").write_text("{ not json", encoding="utf-8")
    res = um.check_cycle_freshness(tmp_path)
    assert res["ok"] is False
    assert "JSON parse error" in res["error"]


def test_cycle_freshness_fresh_epoch(tmp_path):
    (tmp_path / "paper_trading_status.json").write_text(
        json.dumps({"last_cycle_ts": time.time()}), encoding="utf-8"
    )
    res = um.check_cycle_freshness(tmp_path)
    assert res["ok"] is True
    assert res["stale_hours"] is not None and res["stale_hours"] < 1.0


def test_cycle_freshness_stale_epoch(tmp_path):
    old = time.time() - (um.STALE_CYCLE_HOURS + 5) * 3600
    (tmp_path / "paper_trading_status.json").write_text(
        json.dumps({"last_cycle_ts": old}), encoding="utf-8"
    )
    res = um.check_cycle_freshness(tmp_path)
    assert res["ok"] is False
    assert res["stale_hours"] > um.STALE_CYCLE_HOURS


def test_cycle_freshness_iso_string(tmp_path):
    from datetime import datetime, timezone
    iso = datetime.now(timezone.utc).isoformat()
    (tmp_path / "paper_trading_status.json").write_text(
        json.dumps({"last_cycle_ts": iso}), encoding="utf-8"
    )
    res = um.check_cycle_freshness(tmp_path)
    assert res["ok"] is True


# ---------------------------------------------------------------------------
# check_agent_by_output — output-file freshness
# ---------------------------------------------------------------------------

def test_agent_by_output_missing_file(tmp_path):
    res = um.check_agent_by_output("com.spa.peg_monitor", base_dir=tmp_path)
    assert res["running"] is False
    assert res["method"] == "output_file_missing"


def test_agent_by_output_fresh_file(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "peg_report.json").write_text("{}", encoding="utf-8")
    res = um.check_agent_by_output("com.spa.peg_monitor", base_dir=tmp_path)
    assert res["running"] is True
    assert res["method"] == "output_file_age"


def test_agent_by_output_no_mapping(tmp_path):
    res = um.check_agent_by_output("com.spa.does_not_exist", base_dir=tmp_path)
    assert res["running"] is None
    assert res["method"] == "no_mapping"


def test_agent_by_output_no_output_file():
    # httpserver maps to (None, 0) → no file to judge by.
    res = um.check_agent_by_output("com.spa.httpserver")
    assert res["running"] is None
    assert res["method"] == "no_output_file"


# ---------------------------------------------------------------------------
# check_tcp_port / check_http_server — fail-safe
# ---------------------------------------------------------------------------

def test_check_tcp_port_closed_is_false():
    # An almost-certainly-closed high port should return False, never raise.
    assert um.check_tcp_port(59999, timeout=0.2) is False


def test_check_http_server_connection_refused():
    res = um.check_http_server(port=59999)
    assert res["ok"] is False
    assert res["error"] is not None


# ---------------------------------------------------------------------------
# check_launchd_service / check_git_push — never raise on missing binary
# ---------------------------------------------------------------------------

def test_check_launchd_service_never_raises():
    res = um.check_launchd_service("com.spa.definitely_not_loaded_xyz")
    assert "running" in res
    assert res["running"] in (True, False)


def test_check_git_push_invalid_repo(tmp_path):
    res = um.check_git_push(tmp_path)
    assert res["ok"] is False
    assert res["error"] is not None


# ---------------------------------------------------------------------------
# run_all_checks — atomic write + structure
# ---------------------------------------------------------------------------

def test_run_all_checks_writes_status_file(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    result = um.run_all_checks(data_dir=data_dir, repo_dir=tmp_path)
    assert "all_ok" in result and "checks" in result and "ts" in result
    out = data_dir / um.UPTIME_STATUS_FILE
    assert out.exists()
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["all_ok"] == result["all_ok"]
    # tmp file must not be left behind
    assert not (data_dir / (um.UPTIME_STATUS_FILE + ".tmp")).exists()


# ---------------------------------------------------------------------------
# EXIT-CODE POLICY — the actual P0-1 bug (exit 256)
# ---------------------------------------------------------------------------

def test_main_returns_zero_when_degraded(monkeypatch):
    """Default mode: DEGRADED must NOT produce a non-zero exit (the bug)."""
    monkeypatch.setattr(
        um, "run_all_checks",
        lambda **kw: {"all_ok": False, "ts": time.time(), "checks": {}},
    )
    assert um.main(argv=[]) == 0


def test_main_returns_zero_when_all_ok(monkeypatch):
    monkeypatch.setattr(
        um, "run_all_checks",
        lambda **kw: {"all_ok": True, "ts": time.time(), "checks": {}},
    )
    assert um.main(argv=[]) == 0


def test_main_strict_returns_one_when_degraded(monkeypatch):
    """--strict preserves legacy behaviour: DEGRADED → 1."""
    monkeypatch.setattr(
        um, "run_all_checks",
        lambda **kw: {"all_ok": False, "ts": time.time(), "checks": {}},
    )
    assert um.main(argv=["--strict"]) == 1


def test_main_strict_returns_zero_when_all_ok(monkeypatch):
    monkeypatch.setattr(
        um, "run_all_checks",
        lambda **kw: {"all_ok": True, "ts": time.time(), "checks": {}},
    )
    assert um.main(argv=["--strict"]) == 0


def test_main_returns_one_on_internal_failure(monkeypatch):
    """A genuine internal failure (checks blow up) → exit 1, not a crash."""
    def boom(**kw):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(um, "run_all_checks", boom)
    assert um.main(argv=[]) == 1


def test_main_smoke_real_run():
    """End-to-end: main() against the real repo must return 0 and not raise."""
    rc = um.main(argv=[])
    assert rc == 0
