"""
tests/test_kanban_health.py

25 unit tests for scripts/kanban_health.py

Run:
    python3 -m unittest tests/test_kanban_health.py -v
"""
import json
import os
import sys
import unittest

# Allow importing from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import kanban_health as kh
import tempfile


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _make_valid_kanban(**overrides) -> dict:
    """Return a minimal valid KANBAN dict."""
    base = {
        "done_count": 5,
        "done": [
            {"id": f"MP-{i}", "title": f"Task {i}"} for i in range(1, 6)
        ],
        "sprint_completed": "v10.0",
        "sprint_current": "v10.3",
        "current_sprint": "v10.3",
        "version": "10.0.0",
        "last_updated": "2026-06-19",
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────
# check_kanban() — valid data returns no issues
# ─────────────────────────────────────────────

class TestCheckKanbanValid(unittest.TestCase):
    def test_valid_kanban_returns_empty_issues(self):
        k = _make_valid_kanban()
        self.assertEqual(kh.check_kanban(k), [])

    def test_valid_with_large_done_count(self):
        k = _make_valid_kanban(done_count=1109)
        self.assertEqual(kh.check_kanban(k), [])

    def test_valid_no_done_items(self):
        k = _make_valid_kanban(done=[], done_count=0)
        self.assertEqual(kh.check_kanban(k), [])

    def test_valid_sprint_current_equals_completed(self):
        """sprint_current == sprint_completed is allowed (borderline OK)."""
        k = _make_valid_kanban(sprint_current="v10.0", current_sprint="v10.0")
        self.assertEqual(kh.check_kanban(k), [])


# ─────────────────────────────────────────────
# check_kanban() — done_count issues
# ─────────────────────────────────────────────

class TestCheckDoneCount(unittest.TestCase):
    def test_done_count_less_than_done_len_is_issue(self):
        k = _make_valid_kanban(done_count=3)
        issues = kh.check_kanban(k)
        self.assertTrue(any("done_count" in i and "done[]" in i for i in issues))

    def test_done_count_zero_with_tasks_is_issue(self):
        k = _make_valid_kanban(done_count=0)
        issues = kh.check_kanban(k)
        self.assertTrue(any("done_count" in i for i in issues))

    def test_done_count_exact_match_is_ok(self):
        k = _make_valid_kanban(done_count=5)
        issues = kh.check_kanban(k)
        self.assertFalse(any("done_count" in i for i in issues))


# ─────────────────────────────────────────────
# check_kanban() — sprint regression (CRIT-001)
# ─────────────────────────────────────────────

class TestCheckSprintRegression(unittest.TestCase):
    def test_sprint_current_behind_completed_is_issue(self):
        """v9.94 < v10.0 must be detected as regression."""
        k = _make_valid_kanban(sprint_current="v9.94", current_sprint="v9.94")
        issues = kh.check_kanban(k)
        self.assertTrue(
            any("sprint_current" in i and "sprint_completed" in i for i in issues)
        )

    def test_sprint_current_far_behind_is_issue(self):
        k = _make_valid_kanban(sprint_current="v9.04", current_sprint="v9.04")
        issues = kh.check_kanban(k)
        self.assertTrue(any("regression" in i for i in issues))

    def test_sprint_current_missing_is_issue(self):
        k = _make_valid_kanban(sprint_current="", current_sprint="")
        issues = kh.check_kanban(k)
        self.assertTrue(any("sprint_current" in i for i in issues))

    def test_sprint_completed_missing_is_issue(self):
        k = _make_valid_kanban(sprint_completed="")
        issues = kh.check_kanban(k)
        self.assertTrue(any("sprint_completed" in i for i in issues))

    def test_sprint_current_ahead_is_ok(self):
        k = _make_valid_kanban(sprint_current="v10.4", current_sprint="v10.4")
        self.assertEqual(kh.check_kanban(k), [])


# ─────────────────────────────────────────────
# check_kanban() — version
# ─────────────────────────────────────────────

class TestCheckVersion(unittest.TestCase):
    def test_wrong_version_is_issue(self):
        k = _make_valid_kanban(version="9.94.0")
        issues = kh.check_kanban(k)
        self.assertTrue(any("version" in i for i in issues))

    def test_missing_version_is_issue(self):
        k = _make_valid_kanban()
        del k["version"]
        issues = kh.check_kanban(k)
        self.assertTrue(any("version" in i for i in issues))

    def test_correct_version_is_ok(self):
        k = _make_valid_kanban(version="10.0.0")
        self.assertEqual(kh.check_kanban(k), [])


# ─────────────────────────────────────────────
# check_kanban() — duplicate IDs
# ─────────────────────────────────────────────

class TestCheckDuplicates(unittest.TestCase):
    def test_duplicate_ids_in_done_is_issue(self):
        done = [{"id": "MP-1"}, {"id": "MP-1"}, {"id": "MP-2"}]
        k = _make_valid_kanban(done=done, done_count=10)
        issues = kh.check_kanban(k)
        self.assertTrue(any("Duplicate" in i for i in issues))

    def test_unique_ids_is_ok(self):
        done = [{"id": f"MP-{i}"} for i in range(5)]
        k = _make_valid_kanban(done=done, done_count=10)
        self.assertEqual(kh.check_kanban(k), [])


# ─────────────────────────────────────────────
# check_kanban() — last_updated
# ─────────────────────────────────────────────

class TestCheckLastUpdated(unittest.TestCase):
    def test_missing_last_updated_is_issue(self):
        k = _make_valid_kanban()
        del k["last_updated"]
        issues = kh.check_kanban(k)
        self.assertTrue(any("last_updated" in i for i in issues))

    def test_present_last_updated_is_ok(self):
        k = _make_valid_kanban(last_updated="2026-06-19")
        self.assertEqual(kh.check_kanban(k), [])


# ─────────────────────────────────────────────
# fix_kanban()
# ─────────────────────────────────────────────

class TestFixKanban(unittest.TestCase):
    def test_fix_bumps_done_count(self):
        k = _make_valid_kanban(done_count=1)
        k = kh.fix_kanban(k)
        self.assertGreaterEqual(k["done_count"], 5)  # 5 items in done[]

    def test_fix_sets_version(self):
        k = _make_valid_kanban(version="9.0.0")
        k = kh.fix_kanban(k)
        self.assertEqual(k["version"], "10.0.0")

    def test_fix_sprint_current_when_behind(self):
        k = _make_valid_kanban(sprint_current="v9.94", current_sprint="v9.94")
        k = kh.fix_kanban(k)
        self.assertTrue(
            kh._sprint_gte(k["sprint_current"], k["sprint_completed"])
        )

    def test_fix_aligns_current_sprint(self):
        k = _make_valid_kanban(sprint_current="v9.94", current_sprint="v9.04")
        k = kh.fix_kanban(k)
        self.assertEqual(k["current_sprint"], k["sprint_current"])

    def test_fix_sets_last_updated_when_missing(self):
        k = _make_valid_kanban()
        del k["last_updated"]
        k = kh.fix_kanban(k)
        self.assertTrue(k.get("last_updated"))

    def test_fix_sets_sprint_completed_default(self):
        k = _make_valid_kanban(sprint_completed="")
        k = kh.fix_kanban(k)
        self.assertEqual(k["sprint_completed"], "v10.0")

    def test_fix_preserves_high_done_count(self):
        k = _make_valid_kanban(done_count=1109)
        k = kh.fix_kanban(k)
        self.assertEqual(k["done_count"], 1109)

    def test_fix_stamps_last_checked(self):
        k = _make_valid_kanban()
        k = kh.fix_kanban(k)
        self.assertTrue(k.get("last_checked"))

    def test_fix_accepts_sprint_current_override(self):
        k = _make_valid_kanban(sprint_current="v9.94", current_sprint="v9.94")
        k = kh.fix_kanban(k, sprint_current="v10.4")
        self.assertEqual(k["sprint_current"], "v10.4")

    def test_fixed_kanban_has_no_issues(self):
        k = _make_valid_kanban(
            done_count=0,
            version="9.0.0",
            sprint_current="v9.94",
            current_sprint="v9.04",
        )
        k = kh.fix_kanban(k)
        remaining = kh.check_kanban(k)
        self.assertEqual(remaining, [])


# ─────────────────────────────────────────────
# save_kanban() / load_kanban()
# ─────────────────────────────────────────────

class TestSaveLoad(unittest.TestCase):
    def test_save_kanban_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "KANBAN.json")
            kh.save_kanban(_make_valid_kanban(), path)
            self.assertTrue(os.path.exists(path))

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "KANBAN.json")
            kh.save_kanban(_make_valid_kanban(done_count=42), path)
            loaded = kh.load_kanban(path)
            self.assertEqual(loaded["done_count"], 42)

    def test_save_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "KANBAN.json")
            kh.save_kanban(_make_valid_kanban(), path)
            with open(path) as f:
                data = json.load(f)
            self.assertIn("done_count", data)


if __name__ == "__main__":
    unittest.main()
