#!/usr/bin/env python3
"""
tests/test_backup.py — MP-1451 (Sprint v10.67)

Test suite for spa_core/persistence/backup.py (daily off-site backup).

Tests:
  A. default_backup_dir (A1–A2)
  B. _atomic_write_json — delegation to atomic_save after migration (B1–B3)
  C. _atomic_copy (C1–C3)
  D. run_backup — manifest & files (D1–D5)
  E. _rotate — keep_last pruning (E1–E4)

Pure stdlib. No network. Offline.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO))

from spa_core.persistence.backup import (
    _atomic_copy,
    _atomic_write_json,
    _rotate,
    _sha256,
    default_backup_dir,
    run_backup,
    KEEP_LAST,
    MANIFEST_FILENAME,
)


def _make_dummy_file(path: pathlib.Path, content: str = "test") -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ═══════════════════════════════════════════════════════════════════════════════
# Group A — default_backup_dir
# ═══════════════════════════════════════════════════════════════════════════════

class TestDefaultBackupDir(unittest.TestCase):

    def test_A1_returns_path_instance(self):
        """default_backup_dir() returns a pathlib.Path."""
        result = default_backup_dir()
        self.assertIsInstance(result, pathlib.Path)

    def test_A2_env_override_respected(self):
        """SPA_BACKUP_DIR env var overrides default."""
        with tempfile.TemporaryDirectory() as d:
            os.environ["SPA_BACKUP_DIR"] = d
            try:
                result = default_backup_dir()
                self.assertEqual(str(result), d)
            finally:
                del os.environ["SPA_BACKUP_DIR"]


# ═══════════════════════════════════════════════════════════════════════════════
# Group B — _atomic_write_json (migration target)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAtomicWriteJson(unittest.TestCase):

    def test_B1_writes_valid_json(self):
        """_atomic_write_json writes parseable JSON."""
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "out.json"
            _atomic_write_json(p, {"key": "value", "n": 42})
            self.assertTrue(p.exists())
            data = json.loads(p.read_text())
            self.assertEqual(data["key"], "value")
            self.assertEqual(data["n"], 42)

    def test_B2_no_tmp_files_left(self):
        """_atomic_write_json leaves no .tmp files after success."""
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "out.json"
            _atomic_write_json(p, {"x": 1})
            tmp_files = list(pathlib.Path(d).glob("*.tmp"))
            self.assertEqual(len(tmp_files), 0)

    def test_B3_overwrites_existing_file(self):
        """_atomic_write_json atomically replaces an existing file."""
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "out.json"
            _atomic_write_json(p, {"v": 1})
            _atomic_write_json(p, {"v": 2})
            data = json.loads(p.read_text())
            self.assertEqual(data["v"], 2)


# ═══════════════════════════════════════════════════════════════════════════════
# Group C — _atomic_copy
# ═══════════════════════════════════════════════════════════════════════════════

class TestAtomicCopy(unittest.TestCase):

    def test_C1_file_copied_correctly(self):
        """_atomic_copy produces a byte-identical copy."""
        with tempfile.TemporaryDirectory() as d:
            src = pathlib.Path(d) / "source.txt"
            dst = pathlib.Path(d) / "dest.txt"
            src.write_bytes(b"hello world test data 12345")
            _atomic_copy(src, dst)
            self.assertEqual(src.read_bytes(), dst.read_bytes())

    def test_C2_no_tmp_files_left_after_copy(self):
        """_atomic_copy leaves no temp artifacts."""
        with tempfile.TemporaryDirectory() as d:
            src = pathlib.Path(d) / "src.bin"
            dst = pathlib.Path(d) / "dst.bin"
            src.write_bytes(b"\x00\xff" * 64)
            _atomic_copy(src, dst)
            tmp_files = list(pathlib.Path(d).glob("*.tmp"))
            self.assertEqual(len(tmp_files), 0)

    def test_C3_sha256_matches_after_copy(self):
        """sha256 of copied file matches original."""
        with tempfile.TemporaryDirectory() as d:
            src = pathlib.Path(d) / "data.bin"
            dst = pathlib.Path(d) / "data_copy.bin"
            content = b"SPA backup integrity test " * 100
            src.write_bytes(content)
            _atomic_copy(src, dst)
            self.assertEqual(_sha256(src), _sha256(dst))


# ═══════════════════════════════════════════════════════════════════════════════
# Group D — run_backup
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunBackup(unittest.TestCase):

    def _setup(self):
        """Create a temp data_dir and backup_dir with some track files."""
        tmp = tempfile.mkdtemp()
        data_dir = pathlib.Path(tmp) / "data"
        data_dir.mkdir()
        backup_dir = pathlib.Path(tmp) / "backups"
        backup_dir.mkdir()
        _make_dummy_file(data_dir / "trades.json", '{"trades":[]}')
        _make_dummy_file(data_dir / "equity_curve_daily.json", '{"curve":[]}')
        return data_dir, backup_dir

    def test_D1_run_backup_returns_ok(self):
        """run_backup returns status=='ok' when files present."""
        data_dir, backup_dir = self._setup()
        result = run_backup(data_dir=data_dir, backup_dir=backup_dir)
        self.assertEqual(result.get("status"), "ok")

    def test_D2_dated_folder_created(self):
        """run_backup creates a YYYY-MM-DD dated subdirectory."""
        data_dir, backup_dir = self._setup()
        run_backup(data_dir=data_dir, backup_dir=backup_dir)
        dated_dirs = [d for d in backup_dir.iterdir() if d.is_dir()]
        self.assertEqual(len(dated_dirs), 1)
        self.assertRegex(dated_dirs[0].name, r"^\d{4}-\d{2}-\d{2}$")

    def test_D3_manifest_json_written(self):
        """run_backup writes manifest.json in the dated folder with files + ts keys."""
        data_dir, backup_dir = self._setup()
        run_backup(data_dir=data_dir, backup_dir=backup_dir)
        dated = next(backup_dir.iterdir())
        manifest_path = dated / MANIFEST_FILENAME
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text())
        self.assertIn("files", manifest)
        # backup.py uses 'ts' key (ISO timestamp)
        self.assertTrue("ts" in manifest or "timestamp" in manifest,
                        f"Expected 'ts' or 'timestamp' in manifest, got keys: {list(manifest.keys())}")

    def test_D4_trades_file_copied(self):
        """run_backup copies trades.json to dated folder."""
        data_dir, backup_dir = self._setup()
        run_backup(data_dir=data_dir, backup_dir=backup_dir)
        dated = next(backup_dir.iterdir())
        self.assertTrue((dated / "trades.json").exists())

    def test_D5_missing_data_dir_returns_error_not_exception(self):
        """run_backup with non-existent data_dir returns error dict, not exception."""
        with tempfile.TemporaryDirectory() as d:
            backup_dir = pathlib.Path(d) / "backups"
            backup_dir.mkdir()
            result = run_backup(
                data_dir=pathlib.Path(d) / "no_such_data",
                backup_dir=backup_dir,
            )
            # Should not raise; status may be ok (no files) or error
            self.assertIn("status", result)


# ═══════════════════════════════════════════════════════════════════════════════
# Group E — _rotate
# ═══════════════════════════════════════════════════════════════════════════════

class TestRotate(unittest.TestCase):

    def _make_dated_dirs(self, backup_dir: pathlib.Path, dates: list[str]) -> None:
        for d in dates:
            (backup_dir / d).mkdir(parents=True)

    def test_E1_no_rotation_when_below_limit(self):
        """_rotate does nothing when folder count <= keep_last."""
        with tempfile.TemporaryDirectory() as d:
            backup_dir = pathlib.Path(d)
            self._make_dated_dirs(backup_dir, ["2026-06-10", "2026-06-11"])
            removed = _rotate(backup_dir, keep_last=14)
            self.assertEqual(len(removed), 0)
            self.assertTrue((backup_dir / "2026-06-10").exists())

    def test_E2_oldest_removed_when_over_limit(self):
        """_rotate removes oldest folder(s) when over keep_last."""
        with tempfile.TemporaryDirectory() as d:
            backup_dir = pathlib.Path(d)
            dates = [f"2026-06-{i:02d}" for i in range(1, 17)]  # 16 dated dirs
            self._make_dated_dirs(backup_dir, dates)
            removed = _rotate(backup_dir, keep_last=14)
            self.assertEqual(len(removed), 2)
            # Oldest two should be gone
            self.assertFalse((backup_dir / "2026-06-01").exists())
            self.assertFalse((backup_dir / "2026-06-02").exists())

    def test_E3_non_date_dirs_not_removed(self):
        """_rotate only removes folders matching YYYY-MM-DD pattern."""
        with tempfile.TemporaryDirectory() as d:
            backup_dir = pathlib.Path(d)
            # More than keep_last folders, but some are non-date
            dates = [f"2026-06-{i:02d}" for i in range(1, 16)]
            self._make_dated_dirs(backup_dir, dates)
            (backup_dir / "misc_folder").mkdir()
            _rotate(backup_dir, keep_last=14)
            # misc_folder must still exist
            self.assertTrue((backup_dir / "misc_folder").exists())

    def test_E4_keep_last_constant_is_14(self):
        """KEEP_LAST constant is 14 as per spec."""
        self.assertEqual(KEEP_LAST, 14)


if __name__ == "__main__":
    unittest.main(verbosity=2)
