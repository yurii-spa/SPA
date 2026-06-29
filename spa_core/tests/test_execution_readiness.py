#!/usr/bin/env python3
"""Tests for spa_core.execution.readiness_audit (go/no-go self-audit).

Hermetic: env and the data directory are monkeypatched so the suite never
depends on the real repo state or the host environment. The module under
test is READ-ONLY against execution code — these tests confirm that contract
plus the verdict logic.
"""
from __future__ import annotations

import json

import pytest

from spa_core.execution import readiness_audit as ra


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture()
def clean_env(monkeypatch):
    """Remove all live-arming env vars so the default posture is paper-safe."""
    for name in (ra.EXECUTION_MODE_ENV, *ra.SIGNER_KEY_ENVS):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture()
def data_dir(tmp_path):
    """An empty data dir (no golive / status files → track-record fails)."""
    d = tmp_path / "data"
    d.mkdir()
    return d


def _write(d, name, obj):
    (d / name).write_text(json.dumps(obj), encoding="utf-8")


# ─── audit() shape & types ──────────────────────────────────────────────────


def test_audit_returns_expected_shape(clean_env, data_dir):
    rep = ra.audit(data_dir=data_dir)
    assert isinstance(rep, dict)
    for key in ("audited_at", "version", "checks", "posture",
                "ready_for_live", "live_blockers"):
        assert key in rep
    assert isinstance(rep["posture"], str)
    assert isinstance(rep["ready_for_live"], bool)
    assert isinstance(rep["live_blockers"], list)
    assert isinstance(rep["checks"], dict)


def test_posture_and_ready_are_bools_and_strings(clean_env, data_dir):
    rep = ra.audit(data_dir=data_dir)
    assert rep["posture"] in ("PAPER_SAFE", "POSTURE_AT_RISK")
    assert isinstance(rep["ready_for_live"], bool)


# ─── live_blockers non-empty while custody absent ───────────────────────────


def test_live_blockers_nonempty_when_custody_absent(clean_env, data_dir):
    rep = ra.audit(data_dir=data_dir)
    assert rep["ready_for_live"] is False
    assert len(rep["live_blockers"]) > 0
    assert any("custody" in b for b in rep["live_blockers"])


def test_default_posture_is_paper_safe(clean_env, data_dir):
    """No live env, dry-run default True, kill-switch readable, cap present."""
    rep = ra.audit(data_dir=data_dir)
    assert rep["posture"] == "PAPER_SAFE"


# ─── dry-run default check ──────────────────────────────────────────────────


def test_dry_run_default_check_passes(clean_env):
    c = ra.check_adapter_dry_run_default()
    assert c["ok"] is True
    assert c["blocker"] is False
    assert c["adapters_inspected"] >= 1


# ─── kill-switch tuple unpacking ────────────────────────────────────────────


def test_kill_switch_readable_unpacks_tuple(clean_env, data_dir):
    c = ra.check_kill_switch_readable(data_dir)
    assert c["ok"] is True
    assert c["blocker"] is False
    # is_kill_switch_active() returns (bool, reason); both must be captured.
    assert isinstance(c["kill_switch_active"], bool)
    assert isinstance(c["kill_switch_reason"], str)


# ─── env-live detection ─────────────────────────────────────────────────────


def test_execution_mode_not_live_default(clean_env):
    c = ra.check_execution_mode_not_live()
    assert c["ok"] is True
    assert c["live_mode"] is False


def test_execution_mode_live_detected(monkeypatch):
    monkeypatch.setenv(ra.EXECUTION_MODE_ENV, "live")
    c = ra.check_execution_mode_not_live()
    assert c["ok"] is False
    assert c["live_mode"] is True
    # Posture flag, not itself a blocker.
    assert c["blocker"] is False


def test_execution_mode_live_case_insensitive(monkeypatch):
    monkeypatch.setenv(ra.EXECUTION_MODE_ENV, "LIVE")
    c = ra.check_execution_mode_not_live()
    assert c["live_mode"] is True


def test_live_mode_removes_that_specific_blocker(monkeypatch, tmp_path):
    """When mode IS live, 'SPA_EXECUTION_MODE not enabled' must NOT appear."""
    d = tmp_path / "data"
    d.mkdir()
    for name in ra.SIGNER_KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(ra.EXECUTION_MODE_ENV, "live")
    rep = ra.audit(data_dir=d)
    assert "SPA_EXECUTION_MODE not enabled" not in rep["live_blockers"]
    # still not ready (custody/audit/track missing)
    assert rep["ready_for_live"] is False


# ─── custody detection ──────────────────────────────────────────────────────


def test_custody_absent_is_paper_safe_but_blocker(clean_env):
    c = ra.check_custody_connected()
    assert c["ok"] is True            # safe for paper
    assert c["blocker"] is True       # but blocks go-live
    assert c["custody_connected"] is False


def test_custody_present_flips_unsafe(monkeypatch):
    monkeypatch.setenv("SPA_PRIVATE_KEY", "0x" + "ab" * 32)
    c = ra.check_custody_connected()
    assert c["ok"] is False
    assert c["custody_connected"] is True
    assert "SPA_PRIVATE_KEY" in c["signer_envs_present"]


# ─── amount cap & multisig control ──────────────────────────────────────────


def test_live_amount_cap_present(clean_env):
    c = ra.check_live_amount_cap()
    assert c["ok"] is True
    assert c["max_live_amount"] > 0


def test_multisig_control_present(clean_env):
    c = ra.check_multisig_control()
    assert c["ok"] is True
    assert c["blocker"] is False


# ─── track record gate ──────────────────────────────────────────────────────


def test_track_record_blocks_when_insufficient(clean_env, data_dir):
    _write(data_dir, "paper_trading_status.json", {"days_running": 15})
    _write(data_dir, "golive_status.json",
           {"ready": False, "passed": 27, "total": 29})
    c = ra.check_track_record(data_dir)
    assert c["ok"] is False
    assert c["blocker"] is True
    assert c["days_running"] == 15


def test_track_record_ok_when_met(clean_env, data_dir):
    _write(data_dir, "paper_trading_status.json", {"days_running": 31})
    _write(data_dir, "golive_status.json",
           {"ready": True, "passed": 29, "total": 29})
    c = ra.check_track_record(data_dir)
    assert c["ok"] is True
    assert c["blocker"] is False


def test_track_record_reads_evidenced_count_not_raw_bars(clean_env, data_dir):
    """Audit finding #4: the cutover scorecard must report the EVIDENCED track count
    (golive_status.real_track_days), NOT the raw inflated days_running from
    paper_trading_status.json. With real_track_days=7 (anchored) and golive 27/29, the
    scorecard must read 7/30 · 27/29 — even though days_running says 19 raw bars."""
    _write(data_dir, "paper_trading_status.json", {"days_running": 19})  # raw, inflated
    _write(data_dir, "golive_status.json",
           {"ready": False, "passed": 27, "total": 29, "real_track_days": 7,
            "evidenced_anchor": "2026-06-22"})
    c = ra.check_track_record(data_dir)
    assert c["days_running"] == 7, "must report EVIDENCED 7, not the raw 19 bars"
    assert c["golive_passed"] == 27
    assert c["golive_total"] == 29
    assert c["ok"] is False and c["blocker"] is True
    assert "7/30" in c["detail"] and "27/29" in c["detail"]


def test_track_blocker_listed_in_live_blockers(clean_env, data_dir):
    _write(data_dir, "paper_trading_status.json", {"days_running": 15})
    _write(data_dir, "golive_status.json",
           {"ready": False, "passed": 27, "total": 29})
    rep = ra.audit(data_dir=data_dir)
    assert any("track_record" in b for b in rep["live_blockers"])


# ─── ready_for_live remains False even when track met (custody/audit gate) ──


def test_not_ready_without_custody_even_with_track(clean_env, data_dir):
    _write(data_dir, "paper_trading_status.json", {"days_running": 60})
    _write(data_dir, "golive_status.json",
           {"ready": True, "passed": 29, "total": 29})
    rep = ra.audit(data_dir=data_dir)
    assert rep["ready_for_live"] is False
    assert any("custody" in b for b in rep["live_blockers"])
    assert any("external audit" in b for b in rep["live_blockers"])


def test_ready_for_live_true_only_when_all_gates_pass(monkeypatch, tmp_path):
    """Synthetic: every live gate satisfied → ready_for_live True."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv(ra.EXECUTION_MODE_ENV, "live")
    monkeypatch.setenv("SPA_PRIVATE_KEY", "0x" + "cd" * 32)  # custody connected
    _write(d, "paper_trading_status.json", {"days_running": 45})
    _write(d, "golive_status.json", {"ready": True, "passed": 29, "total": 29})
    _write(d, "external_audit_attestation.json", {"passed": True})
    rep = ra.audit(data_dir=d)
    assert rep["live_blockers"] == []
    assert rep["ready_for_live"] is True


# ─── build_report structure + atomic write ──────────────────────────────────


def test_build_report_writes_file(clean_env, data_dir):
    rep = ra.build_report(write=True, data_dir=data_dir)
    out = data_dir / ra._REPORT_FILENAME
    assert out.exists()
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk["posture"] == rep["posture"]
    assert on_disk["ready_for_live"] == rep["ready_for_live"]
    assert "checks" in on_disk


def test_build_report_no_write(clean_env, data_dir):
    rep = ra.build_report(write=False, data_dir=data_dir)
    assert not (data_dir / ra._REPORT_FILENAME).exists()
    assert isinstance(rep, dict)


# ─── determinism ────────────────────────────────────────────────────────────


def test_determinism(clean_env, data_dir):
    a = ra.audit(data_dir=data_dir)
    b = ra.audit(data_dir=data_dir)
    # Everything except the timestamp must be identical.
    a.pop("audited_at")
    b.pop("audited_at")
    assert a == b


# ─── read-only contract: report file is the ONLY thing written ──────────────


def test_audit_writes_nothing(clean_env, data_dir):
    before = set(p.name for p in data_dir.iterdir())
    ra.audit(data_dir=data_dir)  # audit() must not write anything
    after = set(p.name for p in data_dir.iterdir())
    assert before == after
