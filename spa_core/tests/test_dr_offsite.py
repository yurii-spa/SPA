"""
test_dr_offsite.py — DR offsite copy + sha256 verify + status surface (R6).

Drives spa_core/dr/offsite_copy.run() against tmp source/dest dirs and asserts the
status JSON: a good copy → verified:true + sha matches + is_real_remote:false for the
stand-in; a missing/corrupted source → verified:false + non-zero exit (fail-CLOSED).
"""
import gzip
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from spa_core.dr import offsite_copy


def _make_archive(backup_dir: Path, name: str, payload: bytes = b"state-data") -> Path:
    """Write a real tiny .tar.gz so sha256 over real bytes is meaningful."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / name
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("state.json")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    with gzip.open(path, "wb") as gz:
        gz.write(buf.getvalue())
    return path


def _run(tmp_path, dest=None, keep=14, backup_dir=None):
    backup_dir = backup_dir or (tmp_path / "backups")
    dest = dest if dest is not None else (tmp_path / "offsite")
    status = tmp_path / "dr_offsite_status.json"
    code = offsite_copy.run(
        backup_dir=Path(backup_dir),
        dest_dir=Path(dest),
        status_path=status,
        keep=keep,
    )
    data = json.loads(status.read_text()) if status.exists() else None
    return code, data


def test_successful_copy_verified_and_sha_matches(tmp_path):
    backup_dir = tmp_path / "backups"
    src = _make_archive(backup_dir, "spa_state_2026-06-27.tar.gz")
    dest = tmp_path / "offsite"

    code, status = _run(tmp_path, dest=dest, backup_dir=backup_dir)

    assert code == 0
    assert status["verified"] is True
    assert status["archive_name"] == "spa_state_2026-06-27.tar.gz"
    # sha in status == sha of the real source file == sha of the copied dest file.
    src_sha = offsite_copy.sha256_file(src)
    dst_sha = offsite_copy.sha256_file(dest / src.name)
    assert status["sha256"] == src_sha == dst_sha
    assert status["n_offsite_kept"] == 1


def test_newest_archive_selected(tmp_path):
    backup_dir = tmp_path / "backups"
    _make_archive(backup_dir, "spa_state_2026-06-25.tar.gz", b"old")
    _make_archive(backup_dir, "spa_state_2026-06-27.tar.gz", b"newest")

    code, status = _run(tmp_path, backup_dir=backup_dir)
    assert code == 0
    assert status["archive_name"] == "spa_state_2026-06-27.tar.gz"


def test_missing_source_fails_closed(tmp_path):
    # empty backup dir → no archive
    (tmp_path / "backups").mkdir()
    code, status = _run(tmp_path)
    assert code != 0
    assert status["verified"] is False
    assert status["error"] == "no_source_archive"


def test_corrupted_dest_after_copy_fails_closed(tmp_path, monkeypatch):
    """Simulate a transfer that lands different bytes → sha mismatch → verified:false."""
    backup_dir = tmp_path / "backups"
    _make_archive(backup_dir, "spa_state_2026-06-27.tar.gz", b"good")
    dest = tmp_path / "offsite"

    # Corrupt the copy by patching the atomic copier to write tampered bytes.
    real_copy = offsite_copy._atomic_copy

    def tampered(s, d):
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_bytes(b"CORRUPTED-DOES-NOT-MATCH")

    monkeypatch.setattr(offsite_copy, "_atomic_copy", tampered)
    code, status = _run(tmp_path, dest=dest, backup_dir=backup_dir)

    assert code != 0
    assert status["verified"] is False
    assert status["error"] == "sha256_mismatch"
    # corrupt dest must be removed (never a silent bad backup left behind)
    assert not (dest / "spa_state_2026-06-27.tar.gz").exists()
    monkeypatch.setattr(offsite_copy, "_atomic_copy", real_copy)


def test_is_real_remote_false_for_standin(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    _make_archive(backup_dir, "spa_state_2026-06-27.tar.gz")
    # Point the module stand-in at our tmp dest and resolve dest to the same dir.
    standin = tmp_path / "standin"
    monkeypatch.setattr(offsite_copy, "STANDIN_DEST", standin)
    code, status = _run(tmp_path, dest=standin, backup_dir=backup_dir)
    assert code == 0
    assert status["is_real_remote"] is False


def test_is_real_remote_true_for_other_dest(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    _make_archive(backup_dir, "spa_state_2026-06-27.tar.gz")
    standin = tmp_path / "standin"
    monkeypatch.setattr(offsite_copy, "STANDIN_DEST", standin)
    other = tmp_path / "some_real_remote_mount"
    code, status = _run(tmp_path, dest=other, backup_dir=backup_dir)
    assert code == 0
    assert status["is_real_remote"] is True


def test_prune_keeps_last_n(tmp_path):
    backup_dir = tmp_path / "backups"
    dest = tmp_path / "offsite"
    dest.mkdir()
    # Pre-seed dest with 5 old offsite copies.
    for d in ("20", "21", "22", "23", "24"):
        (dest / f"spa_state_2026-06-{d}.tar.gz").write_bytes(b"x")
    _make_archive(backup_dir, "spa_state_2026-06-27.tar.gz")

    code, status = _run(tmp_path, dest=dest, keep=3, backup_dir=backup_dir)
    assert code == 0
    assert status["verified"] is True
    kept = sorted(p.name for p in dest.glob("spa_state_*.tar.gz"))
    assert status["n_offsite_kept"] == 3 == len(kept)
    # newest copy is always retained
    assert "spa_state_2026-06-27.tar.gz" in kept


def test_env_var_dest_honored(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    _make_archive(backup_dir, "spa_state_2026-06-27.tar.gz")
    env_dest = tmp_path / "via_env"
    monkeypatch.setenv("SPA_OFFSITE_DEST", str(env_dest))
    status = tmp_path / "dr_offsite_status.json"
    # dest_dir=None → run() reads SPA_OFFSITE_DEST
    code = offsite_copy.run(backup_dir=backup_dir, dest_dir=None, status_path=status)
    assert code == 0
    data = json.loads(status.read_text())
    assert os.path.basename(data["dest"]) == "via_env"
    assert (env_dest / "spa_state_2026-06-27.tar.gz").exists()
