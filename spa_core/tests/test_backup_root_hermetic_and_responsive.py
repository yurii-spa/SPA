"""Track backup: hermetic in tests, and never blocked forever by a dead root.

Card ``agent-track-persistence-test-writes-to-real-icloud-backup`` (found by
cycle #112, fixed by cycle #113). Two independent halves, tested separately:

A. **Hermeticity** — no test resolves the production off-site backup root.
   ``spa_core/tests/backup_dir_guard.py`` + the autouse fixture in both
   conftests pin ``$SPA_BACKUP_DIR`` into a sandbox. Redirection, not a mock:
   the real ``run_backup`` still copies, hashes, manifests and rotates.

B. **Liveness** — an unresponsive backup root makes ``run_backup`` refuse with a
   RECORDED error inside its deadline, instead of blocking forever inside
   ``os.replace`` (measured on the production Mac host 2026-08-04: a plain
   ``os.listdir`` of the iCloud ``SPA_backups`` root did not return in 20 s).

Positive controls are included on purpose: a guard that always says "fine" and a
probe that always says "stalled" would both be useless, so each half is pinned
from both sides.
"""
import os
import threading
import time
from pathlib import Path

import pytest

from spa_core.persistence import backup as bk
from spa_core.persistence.backup import (
    default_backup_dir,
    probe_timeout_s,
    run_backup,
)

import sys

backup_dir_guard = sys.modules["spa_backup_dir_guard"]


# ── A. hermeticity ────────────────────────────────────────────────────────


def test_default_backup_dir_is_sandboxed_during_tests():
    """The guard is actually in force: the default root is the sandbox."""
    assert os.environ.get("SPA_BACKUP_DIR") == str(backup_dir_guard.sandbox_root())
    assert default_backup_dir() == backup_dir_guard.sandbox_root()


def test_default_backup_dir_never_resolves_to_icloud_in_tests():
    """The exact production path that hung must be unreachable from the suite."""
    icloud = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    resolved = default_backup_dir()
    assert icloud not in resolved.parents and resolved != icloud / "SPA_backups"
    assert Path.home() / "SPA_backups" != resolved


def test_positive_control_without_the_guard_icloud_would_be_chosen(monkeypatch):
    """Control: the guard is what redirects — the old resolution is unchanged.

    With the env var removed and the iCloud parent reported present, the module
    still picks iCloud. So test A above passes because of the guard, not because
    ``default_backup_dir`` was quietly rewritten.
    """
    monkeypatch.delenv("SPA_BACKUP_DIR", raising=False)
    monkeypatch.setattr(bk, "_ICLOUD_PARENT", Path("/nonexistent-icloud-parent"))
    assert default_backup_dir() == Path.home() / "SPA_backups"

    class _AlwaysThere:
        """Minimal stand-in: the module only calls .exists() and `/`."""

        def exists(self) -> bool:
            return True

        def __truediv__(self, other) -> Path:
            return Path("/pretend/icloud") / other

    monkeypatch.setattr(bk, "_ICLOUD_PARENT", _AlwaysThere())
    assert default_backup_dir() == Path("/pretend/icloud/SPA_backups")


def test_guard_restores_a_preexisting_value(monkeypatch):
    """restore() puts back exactly what install() found (no leak either way)."""
    monkeypatch.setenv("SPA_BACKUP_DIR", "/tmp/preexisting-root")
    backup_dir_guard.install()
    assert os.environ["SPA_BACKUP_DIR"] == str(backup_dir_guard.sandbox_root())
    backup_dir_guard.restore()
    assert os.environ["SPA_BACKUP_DIR"] == "/tmp/preexisting-root"


def test_guard_restores_an_absent_value(monkeypatch):
    """restore() removes the variable again when it was unset before."""
    monkeypatch.delenv("SPA_BACKUP_DIR", raising=False)
    backup_dir_guard.install()
    assert "SPA_BACKUP_DIR" in os.environ
    backup_dir_guard.restore()
    assert "SPA_BACKUP_DIR" not in os.environ


def test_pin_is_reinstalled_after_a_test_unsets_it():
    """The per-test half of the guard: one test's `del` must not leak forward.

    Asserted in a CHILD process (``_child_backup_pin_check.py``, two tests in
    fixed order) because the property is *what the next test sees* — it cannot
    be observed from inside the test that breaks the environment, and must not
    ride on collection order in the real suite, which is shuffled.
    """
    import subprocess

    child = Path(__file__).resolve().parent / "_child_backup_pin_check.py"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(child), "-q", "-p", "no:randomly"],
        cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True,
        text=True,
        timeout=300,
        env={k: v for k, v in os.environ.items() if k != "SPA_BACKUP_DIR"},
    )
    assert proc.returncode == 0, f"child run failed:\n{proc.stdout}\n{proc.stderr}"


def test_real_backup_still_runs_against_the_sandbox(tmp_path):
    """Coverage is not reduced: the real copy/manifest path executes and works."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "trades.json").write_text("[]")
    res = run_backup(data_dir)  # no backup_dir → guard's sandbox
    assert res["status"] == "ok", res
    assert "trades.json" in res["files"]
    dest = Path(res["dest"])
    assert dest.is_relative_to(backup_dir_guard.sandbox_root())
    assert (dest / "trades.json").read_text() == "[]"
    assert (dest / "manifest.json").exists()


# ── B. liveness ───────────────────────────────────────────────────────────


@pytest.fixture
def stall_mkdir(monkeypatch):
    """Make ``Path.mkdir`` block like a dead sync filesystem does.

    The block is released at teardown so the daemon worker actually exits —
    a test that simulates a hang must not leak one.
    """
    release = threading.Event()
    monkeypatch.setattr(bk.Path, "mkdir", lambda self, **kw: release.wait(60))
    yield
    release.set()


def test_unresponsive_backup_root_does_not_hang_the_run(monkeypatch, tmp_path):
    """THE REGRESSION: a root that never answers ends in a refusal, not a hang."""
    monkeypatch.setattr(bk, "_probe_backup_root", lambda root, timeout: "simulated stall")
    started = time.monotonic()
    res = run_backup(tmp_path / "data", tmp_path / "dead_root")
    assert time.monotonic() - started < 30
    assert res["status"] == "error"
    assert any("backup_root_unavailable" in e for e in res["errors"])


def test_probe_gives_up_on_the_thread_not_on_the_syscall(stall_mkdir):
    """A blocked worker cannot be cancelled — the probe must walk away anyway."""
    started = time.monotonic()
    reason = bk._probe_backup_root(Path("/pretend/stalled"), 0.5)
    elapsed = time.monotonic() - started
    assert reason is not None and "did not respond" in reason
    assert 0.5 <= elapsed < 5.0  # returned on its deadline, not on the syscall


def test_run_backup_never_raises_on_a_stalled_root(monkeypatch, tmp_path):
    """The documented 'never raises' contract holds on the refusal path too."""
    monkeypatch.setattr(bk, "_probe_backup_root", lambda root, timeout: "stalled")
    res = run_backup(tmp_path / "data", tmp_path / "root")  # must not raise
    assert isinstance(res, dict) and res["status"] == "error"


def test_probe_reports_a_real_failure_instead_of_swallowing_it(tmp_path):
    """A root that fails fast (not a file) is reported, not silently skipped."""
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    reason = bk._probe_backup_root(blocker, 5.0)
    assert reason is not None and "did not respond" not in reason


def test_positive_control_a_healthy_root_passes_the_probe(tmp_path):
    """Control: the probe is not a blanket 'always stalled' verdict."""
    assert bk._probe_backup_root(tmp_path / "fresh_root", 5.0) is None
    assert (tmp_path / "fresh_root").is_dir()


def test_probe_leaves_no_residue_in_a_healthy_root(tmp_path):
    """The probe cleans up after itself when the root answers."""
    root = tmp_path / "clean"
    assert bk._probe_backup_root(root, 5.0) is None
    assert list(root.iterdir()) == []


def test_probe_timeout_is_configurable_and_disablable(monkeypatch):
    """Deadline: $SPA_BACKUP_PROBE_TIMEOUT_S → 10 s; <= 0 disables the probe."""
    monkeypatch.delenv(bk.PROBE_TIMEOUT_ENV, raising=False)
    assert probe_timeout_s() == bk.DEFAULT_PROBE_TIMEOUT_S
    monkeypatch.setenv(bk.PROBE_TIMEOUT_ENV, "2.5")
    assert probe_timeout_s() == 2.5
    monkeypatch.setenv(bk.PROBE_TIMEOUT_ENV, "not-a-number")
    assert probe_timeout_s() == bk.DEFAULT_PROBE_TIMEOUT_S  # bad value → default, not a crash
    # disabled: the probe returns "fine" without touching the filesystem at all
    assert bk._probe_backup_root(Path("/definitely/does/not/exist"), 0) is None


def test_healthy_root_is_unaffected_by_the_probe(tmp_path):
    """End to end: a normal backup is still ok and still writes its files."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "trades.json").write_text('[{"id": 1}]')
    res = run_backup(data_dir, tmp_path / "root")
    assert res["status"] == "ok" and res["errors"] == []
    assert (Path(res["dest"]) / "trades.json").exists()


# ── B2. the probe must cover the SCAN path too, not just the write path ───
#
# Added by cycle #122 while re-verifying the (orphaned) cycle-#113 fix before
# delivering it. Measured on this host 2026-08-05: the real iCloud SPA_backups
# root passed the entire write probe in 0.00 s while `os.listdir` of it did not
# return in 25 s — the mirror image of the 2026-08-04 measurement, where
# `os.replace` was the call that blocked. `_rotate` reaches that root through
# `Path.iterdir` on EVERY run_backup, so a write-only probe would have waved
# today's stall through and hung in rotation instead. Which syscall family a
# stalled sync filesystem parks on is not stable; the probe has to touch all of
# them the caller touches.


def test_rotate_is_why_the_scan_path_matters(tmp_path):
    """Pin the coupling: `_rotate` reaches the root through `Path.iterdir`.

    If rotation ever stops enumerating, the probe's scan leg is no longer
    justified by anything and this test says so — rather than the leg quietly
    outliving its reason.
    """
    root = tmp_path / "root"
    root.mkdir()
    seen: list[str] = []
    real_iterdir = bk.Path.iterdir

    def _spy(self):
        seen.append(str(self))
        return real_iterdir(self)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(bk.Path, "iterdir", _spy)
    try:
        bk._rotate(root, keep_last=14)
    finally:
        monkey.undo()
    assert seen == [str(root)]


def test_probe_scans_the_root_the_way_rotate_does(tmp_path):
    """The probe performs the same enumeration, not only the write round-trip."""
    root = tmp_path / "root"
    seen: list[str] = []
    real_iterdir = bk.Path.iterdir

    def _spy(self):
        seen.append(str(self))
        return real_iterdir(self)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(bk.Path, "iterdir", _spy)
    try:
        assert bk._probe_backup_root(root, 5.0) is None
    finally:
        monkey.undo()
    assert str(root) in seen, "probe never enumerated the root — _rotate would still hang"


def test_root_that_writes_fine_but_cannot_be_enumerated_is_refused(tmp_path):
    """THE 2026-08-05 SHAPE: writes answer instantly, the scan never returns.

    Positive control for the scan leg specifically: with the write path fully
    healthy, the probe must still refuse — this is exactly the state the live
    iCloud root was in when this test was written.
    """
    root = tmp_path / "root"
    root.mkdir()
    release = threading.Event()
    real_iterdir = bk.Path.iterdir

    def _stalled(self):
        if str(self) == str(root):
            release.wait(60)
        return real_iterdir(self)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(bk.Path, "iterdir", _stalled)
    try:
        started = time.monotonic()
        reason = bk._probe_backup_root(root, 0.5)
        elapsed = time.monotonic() - started
    finally:
        release.set()
        monkey.undo()
    assert reason is not None and "did not respond" in reason
    assert 0.5 <= elapsed < 5.0
    # and the write path really was healthy — the refusal came from the scan
    assert bk._probe_backup_root(root, 5.0) is None


@pytest.mark.parametrize("timeout", [0.2, 1.0])
def test_refusal_is_recorded_not_swallowed(monkeypatch, tmp_path, timeout, stall_mkdir):
    """Invariant #2: the refusal is named in errors[], for every deadline."""
    monkeypatch.setenv(bk.PROBE_TIMEOUT_ENV, str(timeout))
    res = run_backup(tmp_path / "data", tmp_path / "root")
    assert res["status"] == "error"
    assert any(e.startswith("backup_root_unavailable:") for e in res["errors"])
    assert any(f"{timeout:g}s" in e for e in res["errors"])
