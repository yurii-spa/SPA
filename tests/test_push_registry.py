"""
tests/test_push_registry.py

30 unit tests for scripts/push_registry.py
Run: python3 -m unittest tests/test_push_registry.py -v
"""

import json
import os
import sys
import unittest

# Allow importing from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import push_registry as pr
import tempfile


def _make_registry(**kwargs):
    """Build a minimal registry dict for testing."""
    scripts = {
        "push_v921.sh": {"status": "DONE",    "date": "2026-06-01", "commit": "abc"},
        "push_v941.sh": {"status": "PENDING", "date": None,         "commit": None},
        "push_v942.sh": {"status": "PENDING", "date": None,         "commit": None},
        "push_audit001.sh": {"status": "PENDING", "date": None,     "commit": None},
    }
    scripts.update(kwargs)
    return {"last_updated": "2026-06-19", "scripts": scripts}


class TestScanScripts(unittest.TestCase):
    # 1
    def test_scan_returns_list(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "push_v921.sh"), "w").close()
            result = pr.scan_scripts(d)
            self.assertIsInstance(result, list)

    # 2
    def test_scan_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            result = pr.scan_scripts(d)
            self.assertEqual(result, [])

    # 3
    def test_scan_nonexistent_dir(self):
        result = pr.scan_scripts("/tmp/_no_such_dir_spa_999")
        self.assertEqual(result, [])

    # 4
    def test_scan_finds_push_v_scripts(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ["push_v921.sh", "push_v922.sh", "other.sh", "README.md"]:
                open(os.path.join(d, name), "w").close()
            result = pr.scan_scripts(d)
            self.assertIn("push_v921.sh", result)
            self.assertIn("push_v922.sh", result)
            self.assertNotIn("other.sh", result)
            self.assertNotIn("README.md", result)

    # 5
    def test_scan_finds_push_audit_scripts(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "push_audit001.sh"), "w").close()
            open(os.path.join(d, "push_audit_v3.sh"), "w").close()
            result = pr.scan_scripts(d)
            self.assertIn("push_audit001.sh", result)

    # 6
    def test_scan_returns_sorted(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ["push_v930.sh", "push_v910.sh", "push_v920.sh"]:
                open(os.path.join(d, name), "w").close()
            result = pr.scan_scripts(d)
            self.assertEqual(result, sorted(result))


class TestLoadRegistry(unittest.TestCase):
    # 7
    def test_load_returns_dict(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "reg.json")
            data = {"last_updated": "2026-06-19", "scripts": {}}
            with open(path, "w") as f:
                json.dump(data, f)
            result = pr.load_registry(path)
            self.assertIsInstance(result, dict)

    # 8
    def test_load_has_scripts_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "reg.json")
            data = {"last_updated": "2026-06-19", "scripts": {}}
            with open(path, "w") as f:
                json.dump(data, f)
            result = pr.load_registry(path)
            self.assertIn("scripts", result)

    # 9
    def test_load_has_last_updated_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "reg.json")
            data = {"last_updated": "2026-06-19", "scripts": {}}
            with open(path, "w") as f:
                json.dump(data, f)
            result = pr.load_registry(path)
            self.assertIn("last_updated", result)

    # 10
    def test_load_missing_file_returns_empty_registry(self):
        result = pr.load_registry("/tmp/_no_such_registry_spa.json")
        self.assertIsInstance(result, dict)
        self.assertIn("scripts", result)
        self.assertEqual(result["scripts"], {})


class TestSaveRegistry(unittest.TestCase):
    # 11
    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "reg.json")
            registry = {"last_updated": "2026-06-19", "scripts": {}}
            pr.save_registry(registry, path)
            self.assertTrue(os.path.exists(path))

    # 12
    def test_save_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "reg.json")
            registry = _make_registry()
            pr.save_registry(registry, path)
            with open(path, "r") as f:
                loaded = json.load(f)
            self.assertIn("scripts", loaded)

    # 13
    def test_save_no_tmp_file_remains(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "reg.json")
            registry = _make_registry()
            pr.save_registry(registry, path)
            self.assertFalse(os.path.exists(path + ".tmp"))

    # 14
    def test_save_updates_last_updated(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "reg.json")
            registry = {"last_updated": "2000-01-01", "scripts": {}}
            pr.save_registry(registry, path)
            with open(path, "r") as f:
                loaded = json.load(f)
            self.assertNotEqual(loaded["last_updated"], "2000-01-01")


class TestPendingScripts(unittest.TestCase):
    # 15
    def test_pending_returns_list(self):
        registry = _make_registry()
        result = pr.pending_scripts(registry)
        self.assertIsInstance(result, list)

    # 16
    def test_pending_excludes_done(self):
        registry = _make_registry()
        result = pr.pending_scripts(registry)
        self.assertNotIn("push_v921.sh", result)

    # 17
    def test_pending_includes_pending(self):
        registry = _make_registry()
        result = pr.pending_scripts(registry)
        self.assertIn("push_v941.sh", result)

    # 18
    def test_pending_empty_when_all_done(self):
        registry = {"last_updated": "2026-06-19", "scripts": {
            "push_v921.sh": {"status": "DONE", "date": "2026-06-19", "commit": ""}
        }}
        result = pr.pending_scripts(registry)
        self.assertEqual(result, [])


class TestMarkDone(unittest.TestCase):
    # 19
    def test_mark_done_returns_count(self):
        registry = _make_registry()
        count = pr.mark_done(["push_v941.sh"], registry)
        self.assertEqual(count, 1)

    # 20
    def test_mark_done_changes_status(self):
        registry = _make_registry()
        pr.mark_done(["push_v941.sh"], registry)
        self.assertEqual(registry["scripts"]["push_v941.sh"]["status"], "DONE")

    # 21
    def test_mark_done_unknown_script_returns_zero(self):
        registry = _make_registry()
        count = pr.mark_done(["push_v999_unknown.sh"], registry)
        self.assertEqual(count, 0)

    # 22
    def test_mark_done_sets_date(self):
        registry = _make_registry()
        pr.mark_done(["push_v941.sh"], registry)
        self.assertIsNotNone(registry["scripts"]["push_v941.sh"]["date"])

    # 23
    def test_mark_done_multiple(self):
        registry = _make_registry()
        count = pr.mark_done(["push_v941.sh", "push_v942.sh"], registry)
        self.assertEqual(count, 2)

    # 24
    def test_mark_done_records_commit(self):
        registry = _make_registry()
        pr.mark_done(["push_v941.sh"], registry, commit="deadbeef")
        self.assertEqual(registry["scripts"]["push_v941.sh"]["commit"], "deadbeef")


class TestSyncScan(unittest.TestCase):
    # 25
    def test_sync_scan_adds_new_scripts(self):
        registry = {"last_updated": "2026-06-19", "scripts": {}}
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "push_v921.sh"), "w").close()
            added = pr.sync_scan(registry, d)
            self.assertEqual(added, 1)
            self.assertIn("push_v921.sh", registry["scripts"])

    # 26
    def test_sync_scan_returns_count(self):
        registry = {"last_updated": "2026-06-19", "scripts": {}}
        with tempfile.TemporaryDirectory() as d:
            for n in range(921, 924):
                open(os.path.join(d, f"push_v{n}.sh"), "w").close()
            added = pr.sync_scan(registry, d)
            self.assertEqual(added, 3)

    # 27
    def test_sync_scan_does_not_overwrite_existing(self):
        registry = _make_registry()
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "push_v921.sh"), "w").close()
            open(os.path.join(d, "push_v999.sh"), "w").close()
            pr.sync_scan(registry, d)
            # push_v921.sh was already DONE — must stay DONE
            self.assertEqual(registry["scripts"]["push_v921.sh"]["status"], "DONE")

    # 28
    def test_sync_scan_new_entries_are_pending(self):
        registry = {"last_updated": "2026-06-19", "scripts": {}}
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "push_v999.sh"), "w").close()
            pr.sync_scan(registry, d)
            self.assertEqual(registry["scripts"]["push_v999.sh"]["status"], "PENDING")


class TestSummary(unittest.TestCase):
    # 29
    def test_summary_returns_dict(self):
        registry = _make_registry()
        result = pr.summary(registry)
        self.assertIsInstance(result, dict)

    # 30
    def test_summary_has_required_keys(self):
        registry = _make_registry()
        result = pr.summary(registry)
        for key in ("total", "done", "pending", "pct_done"):
            self.assertIn(key, result)

    def test_summary_pct_done_range(self):
        registry = _make_registry()
        result = pr.summary(registry)
        self.assertGreaterEqual(result["pct_done"], 0)
        self.assertLessEqual(result["pct_done"], 100)

    def test_summary_counts_correct(self):
        registry = _make_registry()
        s = pr.summary(registry)
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["done"], 1)
        self.assertEqual(s["pending"], 3)

    def test_summary_empty_registry(self):
        registry = {"last_updated": "2026-06-19", "scripts": {}}
        result = pr.summary(registry)
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["pct_done"], 0.0)


class TestRenderTable(unittest.TestCase):
    def test_render_table_returns_string(self):
        registry = _make_registry()
        result = pr.render_table(registry)
        self.assertIsInstance(result, str)

    def test_render_table_contains_status_word(self):
        registry = _make_registry()
        result = pr.render_table(registry)
        self.assertTrue("DONE" in result or "PENDING" in result)

    def test_render_table_empty_registry(self):
        registry = {"last_updated": "2026-06-19", "scripts": {}}
        result = pr.render_table(registry)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)


if __name__ == "__main__":
    unittest.main()
