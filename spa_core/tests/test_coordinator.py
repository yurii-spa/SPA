"""
Tests for spa_core.coordinator.sprint_coordinator.

Every test is hermetically isolated in tmp_path — no real KANBAN.json or
spa_core modules are touched.  Subprocess calls (git, pytest) are either
mocked or exercised against the real repo where safe.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any
from unittest import mock


# Make sure the repo root is importable regardless of how pytest is invoked
_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.coordinator.sprint_coordinator import (
    GateResult,
    check_git_clean,
    check_imports,
    check_kanban,
    check_push_scripts,
    kanban_update,
    main,
    post_gate,
    pre_gate,
    wave_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_kanban(tmp_path: Path, **extra) -> Path:
    """Write a minimal valid KANBAN.json to *tmp_path* and return its path."""
    data: dict[str, Any] = {
        "done_count": 10,
        "sprint_current": "v11.00",
        "sprint_completed": "v10.99",
        "last_updated": "2026-01-01",
        "columns": {},
    }
    data.update(extra)
    p = tmp_path / "KANBAN.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ============================================================
# 1. GateResult NamedTuple
# ============================================================


def test_gate_result_namedtuple():
    r = GateResult(passed=True, checks={"a": True}, errors=[])
    assert r.passed is True
    assert r.checks == {"a": True}
    assert r.errors == []


def test_gate_result_failed():
    r = GateResult(passed=False, checks={"a": False}, errors=["boom"])
    assert r.passed is False
    assert "boom" in r.errors


# ============================================================
# 2. check_kanban
# ============================================================


def test_check_kanban_valid(tmp_path, monkeypatch):
    p = _minimal_kanban(tmp_path)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", p)
    ok, err = check_kanban()
    assert ok is True
    assert err == ""


def test_check_kanban_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.KANBAN_PATH",
        tmp_path / "nonexistent.json",
    )
    ok, err = check_kanban()
    assert ok is False
    assert "missing" in err.lower()


def test_check_kanban_conflict_markers(tmp_path, monkeypatch):
    p = tmp_path / "KANBAN.json"
    p.write_text('<<<<<<< HEAD\n{"done_count":1}\n=======\n{"done_count":2}\n>>>>>>> other\n')
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", p)
    ok, err = check_kanban()
    assert ok is False
    assert "conflict" in err.lower()


def test_check_kanban_invalid_json(tmp_path, monkeypatch):
    p = tmp_path / "KANBAN.json"
    p.write_text("{broken json,,}")
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", p)
    ok, err = check_kanban()
    assert ok is False
    assert "invalid json" in err.lower()


# ============================================================
# 3. check_git_clean
# ============================================================


def test_check_git_clean_no_conflicts(monkeypatch):
    """Mock git returning empty output → should be clean."""
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.subprocess.run",
        lambda *a, **kw: mock.Mock(stdout="", returncode=0),
    )
    # Also patch away index.lock
    fake_lock = mock.MagicMock()
    fake_lock.exists.return_value = False
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.REPO",
        mock.MagicMock(__truediv__=lambda s, x: fake_lock if x == ".git" else mock.MagicMock()),
    )
    # Re-test via patching the function's internals directly
    with mock.patch(
        "spa_core.coordinator.sprint_coordinator.subprocess.run",
        return_value=mock.Mock(stdout="", returncode=0),
    ):
        with mock.patch.object(Path, "exists", return_value=False):
            ok, err = check_git_clean()
    assert ok is True
    assert err == ""


def test_check_git_clean_with_conflict_files():
    """Simulate git reporting an unresolved conflict file."""
    with mock.patch(
        "spa_core.coordinator.sprint_coordinator.subprocess.run",
        return_value=mock.Mock(stdout="spa_core/foo.py\n", returncode=1),
    ):
        with mock.patch.object(Path, "exists", return_value=False):
            ok, err = check_git_clean()
    assert ok is False
    assert "spa_core/foo.py" in err


def test_check_git_clean_stale_lock(tmp_path):
    """Create a real index.lock to trigger the stale-lock detection."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    lock = git_dir / "index.lock"
    lock.write_text("")

    with mock.patch(
        "spa_core.coordinator.sprint_coordinator.subprocess.run",
        return_value=mock.Mock(stdout="", returncode=0),
    ):
        with mock.patch(
            "spa_core.coordinator.sprint_coordinator.REPO",
            tmp_path,
        ):
            ok, err = check_git_clean()
    assert ok is False
    assert "index.lock" in err


# ============================================================
# 4. check_push_scripts
# ============================================================


def test_check_push_scripts_all_present(tmp_path):
    """All referenced files exist → 0 missing."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    # Real file
    (tmp_path / "spa_core" / "foo.py").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "spa_core" / "foo.py").write_text("")

    script = scripts_dir / "push_v001.sh"
    script.write_text("#!/usr/bin/env bash\nspa_core/foo.py\n")

    with mock.patch("spa_core.coordinator.sprint_coordinator.REPO", tmp_path):
        missing_count, missing_paths = check_push_scripts(scripts_dir)

    assert missing_count == 0
    assert missing_paths == []


def test_check_push_scripts_missing_file(tmp_path):
    """A referenced file does NOT exist → shows up as missing."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    script = scripts_dir / "push_v002.sh"
    script.write_text("#!/usr/bin/env bash\nspa_core/does_not_exist.py\n")

    with mock.patch("spa_core.coordinator.sprint_coordinator.REPO", tmp_path):
        missing_count, missing_paths = check_push_scripts(scripts_dir)

    assert missing_count >= 1
    assert any("does_not_exist.py" in p for p in missing_paths)


def test_check_push_scripts_empty_dir(tmp_path):
    """No scripts → no missing files."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    missing_count, missing_paths = check_push_scripts(scripts_dir)
    assert missing_count == 0


# ============================================================
# 5. check_imports  (unit-level, using a fake minimal module tree)
# ============================================================


def test_check_imports_ok(tmp_path, monkeypatch):
    """A single importable module → ok=1, fail=0."""
    pkg = tmp_path / "spa_core" / "utils"
    pkg.mkdir(parents=True)
    (tmp_path / "spa_core" / "__init__.py").write_text("")
    (tmp_path / "spa_core" / "utils" / "__init__.py").write_text("")
    (tmp_path / "spa_core" / "utils" / "helper.py").write_text("X = 1\n")

    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.REPO", tmp_path)
    ok, fail, errors = check_imports()
    assert ok >= 1
    assert fail == 0
    assert errors == []


def test_check_imports_broken_module(tmp_path, monkeypatch):
    """A module with a syntax/import error → fail=1."""
    pkg = tmp_path / "spa_core" / "broken_pkg"
    pkg.mkdir(parents=True)
    (tmp_path / "spa_core" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("")
    (pkg / "bad_module.py").write_text("import this_does_not_exist_ever_xyz\n")

    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.REPO", tmp_path)
    ok, fail, errors = check_imports()
    assert fail >= 1
    assert any("bad_module" in e for e in errors)


def test_check_imports_skips_test_files(tmp_path, monkeypatch):
    """test_ prefixed files are skipped even if they would fail."""
    pkg = tmp_path / "spa_core" / "mymod"
    pkg.mkdir(parents=True)
    (tmp_path / "spa_core" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "test_bad.py").write_text("raise RuntimeError('MUST NOT IMPORT')\n")
    (pkg / "good.py").write_text("X = 1\n")

    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.REPO", tmp_path)
    ok, fail, errors = check_imports()
    assert fail == 0


# ============================================================
# 6. pre_gate
# ============================================================


def test_pre_gate_all_pass(tmp_path, monkeypatch):
    """pre_gate returns passed=True when all sub-checks succeed."""
    _minimal_kanban(tmp_path)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", tmp_path / "KANBAN.json")
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_git_clean",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_imports",
        lambda **kw: (5, 0, []),
    )
    r = pre_gate()
    assert r.passed is True
    assert r.checks["kanban_valid"] is True
    assert r.checks["git_clean"] is True
    assert r.checks["imports_ok"] is True


def test_pre_gate_fails_on_bad_kanban(tmp_path, monkeypatch):
    bad = tmp_path / "KANBAN.json"
    bad.write_text("{broken}")
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", bad)
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_git_clean",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_imports",
        lambda **kw: (5, 0, []),
    )
    r = pre_gate()
    assert r.passed is False
    assert r.checks["kanban_valid"] is False
    assert any("[KANBAN]" in e for e in r.errors)


def test_pre_gate_fails_on_import_errors(tmp_path, monkeypatch):
    _minimal_kanban(tmp_path)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", tmp_path / "KANBAN.json")
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_git_clean",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_imports",
        lambda **kw: (3, 2, ["mod_a: some error", "mod_b: other error"]),
    )
    r = pre_gate()
    assert r.passed is False
    assert r.checks["imports_ok"] is False
    assert r.checks["import_fail_count"] == 2


def test_pre_gate_contains_import_counts(tmp_path, monkeypatch):
    _minimal_kanban(tmp_path)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", tmp_path / "KANBAN.json")
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_git_clean",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_imports",
        lambda **kw: (42, 0, []),
    )
    r = pre_gate()
    assert r.checks["import_ok_count"] == 42
    assert r.checks["import_fail_count"] == 0


# ============================================================
# 7. post_gate
# ============================================================


def _mock_pre_passed(monkeypatch, tmp_path):
    _minimal_kanban(tmp_path)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", tmp_path / "KANBAN.json")
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_git_clean",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_imports",
        lambda **kw: (10, 0, []),
    )


def test_post_gate_pytest_passes(tmp_path, monkeypatch):
    _mock_pre_passed(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.subprocess.run",
        lambda *a, **kw: mock.Mock(returncode=0, stdout="5 passed", stderr=""),
    )
    r = post_gate()
    assert r.passed is True
    assert r.checks["tests_passed"] is True


def test_post_gate_pytest_fails(tmp_path, monkeypatch):
    _mock_pre_passed(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.subprocess.run",
        lambda *a, **kw: mock.Mock(
            returncode=1,
            stdout="FAILED test_foo.py::test_bar\n1 failed",
            stderr="",
        ),
    )
    r = post_gate()
    assert r.passed is False
    assert r.checks["tests_passed"] is False
    assert any("[PYTEST]" in e for e in r.errors)


def test_post_gate_pre_failure_still_runs_pytest(tmp_path, monkeypatch):
    """Even when pre-gate sub-checks fail, pytest still runs."""
    bad = tmp_path / "KANBAN.json"
    bad.write_text("{bad}")
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", bad)
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_git_clean",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_imports",
        lambda **kw: (5, 0, []),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.subprocess.run",
        lambda *a, **kw: mock.Mock(returncode=0, stdout="1 passed", stderr=""),
    )
    r = post_gate()
    # KANBAN failed → overall passed must be False
    assert r.passed is False
    # But tests_passed was True
    assert r.checks["tests_passed"] is True


# ============================================================
# 8. kanban_update
# ============================================================


def test_kanban_update_increments_done_count(tmp_path, monkeypatch):
    p = _minimal_kanban(tmp_path, done_count=5)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", p)
    result = kanban_update(done_delta=3)
    assert result["done_count"] == 8


def test_kanban_update_sets_sprint(tmp_path, monkeypatch):
    p = _minimal_kanban(tmp_path, sprint_current="v11.00")
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", p)
    result = kanban_update(done_delta=0, sprint="v11.01")
    assert result["sprint"] == "v11.01"
    data = json.loads(p.read_text())
    assert data["sprint_current"] == "v11.01"


def test_kanban_update_default_delta_is_1(tmp_path, monkeypatch):
    p = _minimal_kanban(tmp_path, done_count=100)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", p)
    result = kanban_update()
    assert result["done_count"] == 101


def test_kanban_update_persists_to_disk(tmp_path, monkeypatch):
    p = _minimal_kanban(tmp_path, done_count=7)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", p)
    kanban_update(done_delta=2)
    data = json.loads(p.read_text())
    assert data["done_count"] == 9


def test_kanban_update_leaves_valid_json(tmp_path, monkeypatch):
    p = _minimal_kanban(tmp_path)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", p)
    kanban_update(done_delta=1, sprint="v12.00")
    # Should still be parseable
    data = json.loads(p.read_text())
    assert "done_count" in data
    assert "sprint_current" in data


def test_kanban_update_concurrent_safety(tmp_path, monkeypatch):
    """Two threads calling kanban_update must not lose increments."""
    p = _minimal_kanban(tmp_path, done_count=0)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", p)

    errors: list[Exception] = []

    def worker():
        try:
            kanban_update(done_delta=1)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    data = json.loads(p.read_text())
    assert data["done_count"] == 10


def test_kanban_update_sets_last_updated(tmp_path, monkeypatch):
    p = _minimal_kanban(tmp_path, last_updated="2000-01-01")
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", p)
    kanban_update()
    data = json.loads(p.read_text())
    assert data["last_updated"] != "2000-01-01"


# ============================================================
# 9. wave_report
# ============================================================


def test_wave_report_structure(tmp_path, monkeypatch):
    """wave_report returns all expected top-level keys."""
    _minimal_kanban(tmp_path)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", tmp_path / "KANBAN.json")
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_imports",
        lambda **kw: (20, 1, ["bad_mod: err"]),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_git_clean",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_push_scripts",
        lambda *a, **kw: (0, []),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.subprocess.run",
        lambda *a, **kw: mock.Mock(stdout="", returncode=0),
    )
    report = wave_report(wave=5)
    assert report["wave"] == 5
    assert "imports" in report
    assert "kanban" in report
    assert "git" in report
    assert "push_scripts" in report
    assert "timestamp" in report


def test_wave_report_import_counts(tmp_path, monkeypatch):
    _minimal_kanban(tmp_path)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", tmp_path / "KANBAN.json")
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_imports",
        lambda **kw: (15, 3, ["a", "b", "c"]),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_git_clean",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_push_scripts",
        lambda *a, **kw: (0, []),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.subprocess.run",
        lambda *a, **kw: mock.Mock(stdout="", returncode=0),
    )
    report = wave_report()
    assert report["imports"]["ok"] == 15
    assert report["imports"]["fail"] == 3
    assert report["imports"]["top_errors"] == ["a", "b", "c"]


# ============================================================
# 10. CLI (main)
# ============================================================


def test_cli_pre_gate_exit_0(tmp_path, monkeypatch, capsys):
    """pre-gate with all checks passing → exit code 0."""
    _minimal_kanban(tmp_path)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", tmp_path / "KANBAN.json")
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_git_clean",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_imports",
        lambda **kw: (5, 0, []),
    )
    code = main(["pre-gate"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["passed"] is True


def test_cli_pre_gate_exit_1(tmp_path, monkeypatch):
    """pre-gate with kanban failure → exit code 1."""
    bad = tmp_path / "KANBAN.json"
    bad.write_text("{not valid}")
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", bad)
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_git_clean",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_imports",
        lambda **kw: (5, 0, []),
    )
    code = main(["pre-gate"])
    assert code == 1


def test_cli_kanban_update(tmp_path, monkeypatch, capsys):
    p = _minimal_kanban(tmp_path, done_count=10)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", p)
    code = main(["kanban-update", "--done", "4", "--sprint", "v99.01"])
    assert code == 0
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["done_count"] == 14
    assert result["sprint"] == "v99.01"


def test_cli_wave_report_output(tmp_path, monkeypatch, capsys):
    _minimal_kanban(tmp_path)
    monkeypatch.setattr("spa_core.coordinator.sprint_coordinator.KANBAN_PATH", tmp_path / "KANBAN.json")
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_imports",
        lambda **kw: (5, 0, []),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_git_clean",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.check_push_scripts",
        lambda *a, **kw: (0, []),
    )
    monkeypatch.setattr(
        "spa_core.coordinator.sprint_coordinator.subprocess.run",
        lambda *a, **kw: mock.Mock(stdout="", returncode=0),
    )
    code = main(["wave-report", "--wave", "7"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["wave"] == 7


def test_cli_no_command_prints_help(capsys):
    code = main([])
    assert code == 0
    out = capsys.readouterr().out
    # Should print something resembling a help/usage message
    assert len(out) > 0
