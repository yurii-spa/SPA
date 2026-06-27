"""
spa_core/tests/test_drill_restore.py — tests for the INERT restore drill.

Proves the drill harness (scripts/drill_restore.py):
  * builds a synthetic backup tar (valid + corrupted) and validates the GOOD one
    (all_ok) and FAILS-CLOSED on a corrupted critical file,
  * NEVER writes anywhere under the real live data/ tree (sandbox guard),
  * newest-archive selection picks the latest by mtime,
  * fail-closed when no archives exist,
  * rejects unsafe (absolute / traversal) tar member paths.

All deterministic, stdlib-only. The drill is pointed at synthetic tmp archives and a
tmp status path so the real data/ is never touched.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import tarfile
import time
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "drill_restore.py"
_REAL_DATA = (Path(__file__).resolve().parents[2] / "data").resolve()


def _load_drill():
    spec = importlib.util.spec_from_file_location("drill_restore", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


drill = _load_drill()


# --------------------------------------------------------------------------- #
# synthetic backup builders
# --------------------------------------------------------------------------- #
def _good_payloads() -> dict:
    return {
        "golive_status.json": {"passed": 26, "total": 29, "real_track_days": 6},
        "equity_curve_daily.json": {
            "summary": {"last_date": "2026-01-01"},
            "daily": [{"date": "2025-12-31", "equity": 100000.0},
                      {"date": "2026-01-01", "equity": 100010.0}],
        },
        "paper_evidence_history.json": {"schema_version": 1, "days": [{"d": 1}], "history": []},
        "current_positions.json": {"aave_v3": 23250.0},
    }


def _make_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE evidence_records (id INTEGER PRIMARY KEY, v TEXT)")
    con.execute("INSERT INTO evidence_records (v) VALUES ('x'), ('y')")
    con.commit()
    con.close()


def _make_archive(path: Path, payloads: dict) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, obj in payloads.items():
            data = json.dumps(obj).encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            import io
            tar.addfile(info, io.BytesIO(data))


@pytest.fixture
def sandbox_env(tmp_path, monkeypatch):
    """Point the drill's backups + status + db glob at a tmp tree."""
    backups = tmp_path / "backups"
    backups.mkdir()
    status = tmp_path / "restore_drill_status.json"
    monkeypatch.setattr(drill, "_BACKUPS", str(backups))
    monkeypatch.setattr(drill, "_STATUS_PATH", str(status))
    monkeypatch.setattr(drill, "ARCHIVE_GLOB", str(backups / "spa_state_*.tar.gz"))
    monkeypatch.setattr(drill, "DB_GLOB", str(backups / "spa_*.db"))
    return {"backups": backups, "status": status}


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #
def test_drill_validates_good_backup(sandbox_env):
    backups = sandbox_env["backups"]
    _make_archive(backups / "spa_state_2026-01-01.tar.gz", _good_payloads())
    _make_db(backups / "spa_2026-01-01.db")

    report = drill.run_drill(quiet=True)
    assert report["all_ok"] is True, report
    files = {e["file"]: e for e in report["files_validated"]}
    for name in drill.CRITICAL_JSON:
        assert files[name]["ok"] is True, files[name]
    assert files["track.db"]["ok"] is True, files["track.db"]
    # status JSON written atomically to the tmp path
    written = json.loads(Path(sandbox_env["status"]).read_text())
    assert written["all_ok"] is True
    assert "last_drill_ts" in written


def test_drill_fails_closed_on_corrupted_json(sandbox_env):
    backups = sandbox_env["backups"]
    payloads = _good_payloads()
    report = _good_payloads  # silence linters; not used
    # corrupt a critical file: golive missing required key
    bad = dict(payloads)
    bad["golive_status.json"] = {"foo": "bar"}  # no passed/total
    _make_archive(backups / "spa_state_2026-01-02.tar.gz", bad)
    _make_db(backups / "spa_2026-01-02.db")

    rep = drill.run_drill(quiet=True)
    assert rep["all_ok"] is False, rep
    files = {e["file"]: e for e in rep["files_validated"]}
    assert files["golive_status.json"]["ok"] is False


def test_drill_fails_closed_on_unparseable_json(sandbox_env):
    backups = sandbox_env["backups"]
    arch = backups / "spa_state_2026-01-03.tar.gz"
    # write a tar where equity_curve_daily.json is not valid JSON
    with tarfile.open(arch, "w:gz") as tar:
        import io
        for name, obj in _good_payloads().items():
            if name == "equity_curve_daily.json":
                data = b"{ this is not json"
            else:
                data = json.dumps(obj).encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    _make_db(backups / "spa_2026-01-03.db")

    rep = drill.run_drill(quiet=True)
    assert rep["all_ok"] is False
    files = {e["file"]: e for e in rep["files_validated"]}
    assert files["equity_curve_daily.json"]["ok"] is False


def test_drill_fails_closed_on_corrupted_db(sandbox_env):
    backups = sandbox_env["backups"]
    _make_archive(backups / "spa_state_2026-01-04.tar.gz", _good_payloads())
    # a non-sqlite blob masquerading as a .db
    (backups / "spa_2026-01-04.db").write_bytes(b"not a sqlite database at all" * 10)

    rep = drill.run_drill(quiet=True)
    files = {e["file"]: e for e in rep["files_validated"]}
    assert files["track.db"]["ok"] is False, files["track.db"]
    assert rep["all_ok"] is False


def test_drill_fails_closed_when_db_missing(sandbox_env):
    backups = sandbox_env["backups"]
    _make_archive(backups / "spa_state_2026-01-05.tar.gz", _good_payloads())
    # no .db snapshot at all
    rep = drill.run_drill(quiet=True)
    files = {e["file"]: e for e in rep["files_validated"]}
    assert files["track.db"]["ok"] is False
    assert rep["all_ok"] is False


def test_drill_future_equity_date_fails(sandbox_env):
    backups = sandbox_env["backups"]
    payloads = _good_payloads()
    payloads["equity_curve_daily.json"] = {
        "daily": [{"date": "2999-12-31", "equity": 1.0}]
    }
    _make_archive(backups / "spa_state_2026-01-06.tar.gz", payloads)
    _make_db(backups / "spa_2026-01-06.db")
    rep = drill.run_drill(quiet=True)
    files = {e["file"]: e for e in rep["files_validated"]}
    assert files["equity_curve_daily.json"]["ok"] is False


def test_newest_archive_selection_by_mtime(sandbox_env):
    backups = sandbox_env["backups"]
    older = backups / "spa_state_2026-01-01.tar.gz"
    newer = backups / "spa_state_2026-01-02.tar.gz"
    _make_archive(older, _good_payloads())
    _make_archive(newer, _good_payloads())
    # force mtimes: older < newer
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))
    assert drill.find_newest_archive() == str(newer)


def test_fail_closed_when_no_archives(sandbox_env):
    with pytest.raises(FileNotFoundError):
        drill.find_newest_archive()


def test_unsafe_tar_member_rejected(sandbox_env, tmp_path):
    backups = sandbox_env["backups"]
    arch = backups / "spa_state_2026-01-07.tar.gz"
    with tarfile.open(arch, "w:gz") as tar:
        import io
        data = b"x"
        info = tarfile.TarInfo(name="../escape.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    sb = tmp_path / "sb"
    sb.mkdir()
    with pytest.raises(RuntimeError):
        drill.safe_extract(str(arch), str(sb))


def test_sandbox_guard_refuses_under_live_data(sandbox_env):
    """The hard guard must refuse any sandbox path inside the REAL live data/ tree."""
    with pytest.raises(RuntimeError):
        drill._assert_sandbox_outside_data(str(_REAL_DATA))
    with pytest.raises(RuntimeError):
        drill._assert_sandbox_outside_data(str(_REAL_DATA / "subdir"))


def test_drill_never_writes_under_live_data(sandbox_env, monkeypatch):
    """
    Sabotage tempfile.mkdtemp to point INSIDE the real data/ → the guard must abort
    BEFORE any extraction, proving the drill never writes into live data/.
    """
    backups = sandbox_env["backups"]
    _make_archive(backups / "spa_state_2026-01-08.tar.gz", _good_payloads())
    _make_db(backups / "spa_2026-01-08.db")

    poisoned = _REAL_DATA / "DRILL_SHOULD_NEVER_CREATE_THIS"
    real_mkdtemp = drill.tempfile.mkdtemp

    def _evil_mkdtemp(*a, **k):
        os.makedirs(poisoned, exist_ok=True)
        return str(poisoned)

    monkeypatch.setattr(drill.tempfile, "mkdtemp", _evil_mkdtemp)
    try:
        with pytest.raises(RuntimeError):
            drill.run_drill(quiet=True)
        # the guard fired BEFORE extracting: no critical backup files were written here
        assert not (poisoned / "golive_status.json").exists()
    finally:
        # cleanup the empty poisoned dir we created (not a critical-file write)
        try:
            import shutil
            shutil.rmtree(poisoned, ignore_errors=True)
        except Exception:
            pass
        monkeypatch.setattr(drill.tempfile, "mkdtemp", real_mkdtemp)


def test_real_data_dir_untouched_signature(sandbox_env):
    """
    End-to-end on a synthetic archive: snapshot the real data/ dir listing before/after
    a full drill run and assert the set of entries is unchanged (no stray files created).
    """
    backups = sandbox_env["backups"]
    _make_archive(backups / "spa_state_2026-01-09.tar.gz", _good_payloads())
    _make_db(backups / "spa_2026-01-09.db")

    before = set(os.listdir(_REAL_DATA))
    drill.run_drill(quiet=True)
    after = set(os.listdir(_REAL_DATA))
    assert before == after, f"live data/ changed: {before ^ after}"
