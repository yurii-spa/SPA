"""
tests/test_backup_restore.py — 20 unit tests for backup_spa_data.py and restore_spa_data.py
MP-1525 (v11.41)
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "scripts"))

# Load modules under test
def _load_module(name: str) -> object:
    path = os.path.join(_REPO_ROOT, "scripts", f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

backup_mod = _load_module("backup_spa_data")
restore_mod = _load_module("restore_spa_data")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _silent(fn, *args, **kwargs):
    """Call fn suppressing stdout."""
    buf = StringIO()
    with patch("sys.stdout", buf):
        return fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# 1. BACKUP_FILES constant
# ---------------------------------------------------------------------------

class TestBackupFilesConstant(unittest.TestCase):
    def test_backup_files_non_empty(self):
        self.assertGreater(len(backup_mod.BACKUP_FILES), 0)

    def test_backup_files_contains_kanban(self):
        self.assertIn("KANBAN.json", backup_mod.BACKUP_FILES)

    def test_backup_files_contains_gate_status(self):
        self.assertIn("data/gate_status.json", backup_mod.BACKUP_FILES)

    def test_backup_files_contains_golive(self):
        self.assertIn("data/golive_status.json", backup_mod.BACKUP_FILES)


# ---------------------------------------------------------------------------
# 2. _atomic_write_json
# ---------------------------------------------------------------------------

class TestAtomicWriteJson(unittest.TestCase):
    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _silent(backup_mod._atomic_write_json, {"key": "val"}, path)
            self.assertTrue(os.path.exists(path))

    def test_atomic_write_content_correct(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _silent(backup_mod._atomic_write_json, {"answer": 42}, path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["answer"], 42)

    def test_atomic_write_no_tmp_leftover(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _silent(backup_mod._atomic_write_json, {}, path)
            leftovers = [f for f in os.listdir(d) if f.endswith(".tmp")]
            self.assertEqual(leftovers, [])


# ---------------------------------------------------------------------------
# 3. backup() — core behaviour
# ---------------------------------------------------------------------------

class TestBackupFunction(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_backup_creates_timestamped_dir(self):
        bdir = _silent(backup_mod.backup, base_dir=_REPO_ROOT, backup_root=self.tmpdir)
        self.assertTrue(os.path.isdir(bdir))
        self.assertIn("backup_", os.path.basename(bdir))

    def test_backup_creates_manifest_json(self):
        bdir = _silent(backup_mod.backup, base_dir=_REPO_ROOT, backup_root=self.tmpdir)
        manifest = os.path.join(bdir, "manifest.json")
        self.assertTrue(os.path.exists(manifest))

    def test_backup_manifest_has_schema_version(self):
        bdir = _silent(backup_mod.backup, base_dir=_REPO_ROOT, backup_root=self.tmpdir)
        with open(os.path.join(bdir, "manifest.json")) as f:
            m = json.load(f)
        self.assertIn("schema_version", m)

    def test_backup_manifest_lists_files_copied(self):
        bdir = _silent(backup_mod.backup, base_dir=_REPO_ROOT, backup_root=self.tmpdir)
        with open(os.path.join(bdir, "manifest.json")) as f:
            m = json.load(f)
        self.assertIn("files_copied", m)
        self.assertIsInstance(m["files_copied"], list)

    def test_backup_dry_run_no_dir_created(self):
        _silent(backup_mod.backup, base_dir=_REPO_ROOT, backup_root=self.tmpdir, dry_run=True)
        entries = os.listdir(self.tmpdir) if os.path.exists(self.tmpdir) else []
        # No actual backup dir should be created
        self.assertEqual(len([e for e in entries if e.startswith("backup_")]), 0)

    def test_backup_copies_kanban(self):
        bdir = _silent(backup_mod.backup, base_dir=_REPO_ROOT, backup_root=self.tmpdir)
        self.assertTrue(os.path.exists(os.path.join(bdir, "KANBAN.json")))

    def test_backup_returns_path_string(self):
        result = _silent(backup_mod.backup, base_dir=_REPO_ROOT, backup_root=self.tmpdir)
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# 4. list_backups()
# ---------------------------------------------------------------------------

class TestListBackups(unittest.TestCase):
    def test_list_backups_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            result = backup_mod.list_backups(d)
            self.assertEqual(result, [])

    def test_list_backups_returns_list(self):
        with tempfile.TemporaryDirectory() as d:
            result = backup_mod.list_backups(d)
            self.assertIsInstance(result, list)

    def test_list_backups_finds_backup(self):
        with tempfile.TemporaryDirectory() as d:
            _silent(backup_mod.backup, base_dir=_REPO_ROOT, backup_root=d)
            result = backup_mod.list_backups(d)
            self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# 5. restore() — core behaviour
# ---------------------------------------------------------------------------

class TestRestoreFunction(unittest.TestCase):
    def setUp(self):
        # Create a real backup to restore from
        self.src_dir = tempfile.mkdtemp()
        self.bkp_root = tempfile.mkdtemp()
        self.tgt_dir = tempfile.mkdtemp()
        # Write a dummy file in src
        os.makedirs(os.path.join(self.src_dir, "data"), exist_ok=True)
        self.dummy = {"test": True}
        with open(os.path.join(self.src_dir, "KANBAN.json"), "w") as f:
            json.dump(self.dummy, f)
        with open(os.path.join(self.src_dir, "data", "gate_status.json"), "w") as f:
            json.dump({"gate": "PASS"}, f)
        # Back up with only these files registered temporarily
        import shutil
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.bkp_dir = os.path.join(self.bkp_root, f"backup_{ts}")
        os.makedirs(self.bkp_dir, exist_ok=True)
        shutil.copy2(os.path.join(self.src_dir, "KANBAN.json"), os.path.join(self.bkp_dir, "KANBAN.json"))
        os.makedirs(os.path.join(self.bkp_dir, "data"), exist_ok=True)
        shutil.copy2(
            os.path.join(self.src_dir, "data", "gate_status.json"),
            os.path.join(self.bkp_dir, "data", "gate_status.json"),
        )
        backup_mod._atomic_write_json(
            {"schema_version": "1.0", "timestamp": ts, "files_copied": ["KANBAN.json", "data/gate_status.json"]},
            os.path.join(self.bkp_dir, "manifest.json"),
        )

    def tearDown(self):
        import shutil
        for d in (self.src_dir, self.bkp_root, self.tgt_dir):
            shutil.rmtree(d, ignore_errors=True)

    def test_restore_returns_dict(self):
        result = _silent(restore_mod.restore, backup_dir=self.bkp_dir, target_dir=self.tgt_dir)
        self.assertIsInstance(result, dict)

    def test_restore_kanban_file_created(self):
        _silent(restore_mod.restore, backup_dir=self.bkp_dir, target_dir=self.tgt_dir)
        self.assertTrue(os.path.exists(os.path.join(self.tgt_dir, "KANBAN.json")))

    def test_restore_content_matches(self):
        _silent(restore_mod.restore, backup_dir=self.bkp_dir, target_dir=self.tgt_dir)
        with open(os.path.join(self.tgt_dir, "KANBAN.json")) as f:
            data = json.load(f)
        self.assertEqual(data["test"], True)

    def test_restore_dry_run_no_files_written(self):
        _silent(restore_mod.restore, backup_dir=self.bkp_dir, target_dir=self.tgt_dir, dry_run=True)
        self.assertFalse(os.path.exists(os.path.join(self.tgt_dir, "KANBAN.json")))

    def test_restore_specific_files_only(self):
        _silent(restore_mod.restore, backup_dir=self.bkp_dir, target_dir=self.tgt_dir, files=["KANBAN.json"])
        self.assertTrue(os.path.exists(os.path.join(self.tgt_dir, "KANBAN.json")))
        self.assertFalse(os.path.exists(os.path.join(self.tgt_dir, "data", "gate_status.json")))

    def test_restore_result_has_restored_key(self):
        result = _silent(restore_mod.restore, backup_dir=self.bkp_dir, target_dir=self.tgt_dir)
        self.assertIn("restored", result)
        self.assertIn("KANBAN.json", result["restored"])

    def test_restore_no_errors_on_valid_backup(self):
        result = _silent(restore_mod.restore, backup_dir=self.bkp_dir, target_dir=self.tgt_dir)
        self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
