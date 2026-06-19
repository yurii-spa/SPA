"""
tests/test_kanban_lint.py

20 unit tests for scripts/lint_kanban_usage.py

Run:
    python3 -m unittest tests/test_kanban_lint.py -v
"""
import os
import sys
import tempfile
import unittest

# Allow importing from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import lint_kanban_usage as lk


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _write_tmp(content: str, suffix: str = ".py") -> str:
    """Write content to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
    f.write(content)
    f.close()
    return f.name


class _TmpFile:
    """Context manager: creates a named temp file, removes it on exit."""
    def __init__(self, content: str, suffix: str = ".py"):
        self.content = content
        self.suffix = suffix
        self.path = None

    def __enter__(self):
        self.path = _write_tmp(self.content, self.suffix)
        return self.path

    def __exit__(self, *_):
        try:
            os.unlink(self.path)
        except OSError:
            pass


# ─────────────────────────────────────────────
# _references_kanban()
# ─────────────────────────────────────────────

class TestReferencesKanban(unittest.TestCase):
    def test_file_with_kanban_json_string(self):
        self.assertTrue(lk._references_kanban("path = 'KANBAN.json'"))

    def test_file_without_kanban_reference(self):
        self.assertFalse(lk._references_kanban("import os\nprint('hello')"))

    def test_file_with_uppercase_kanban(self):
        self.assertTrue(lk._references_kanban("# reads KANBAN"))


# ─────────────────────────────────────────────
# _uses_safe_helper()
# ─────────────────────────────────────────────

class TestUsesSafeHelper(unittest.TestCase):
    def test_increment_done_import_is_safe(self):
        content = "from spa_core.utils.kanban import increment_done\nincrement_done()"
        self.assertTrue(lk._uses_safe_helper(content))

    def test_kanban_health_import_is_safe(self):
        content = "import kanban_health\nkanban_health.save_kanban(k)"
        self.assertTrue(lk._uses_safe_helper(content))

    def test_save_kanban_atomic_call_is_safe(self):
        content = "save_kanban_atomic(k, path)"
        self.assertTrue(lk._uses_safe_helper(content))

    def test_no_safe_helper_returns_false(self):
        content = "import json\njson.dump(k, open('KANBAN.json', 'w'))"
        self.assertFalse(lk._uses_safe_helper(content))


# ─────────────────────────────────────────────
# _has_violation()
# ─────────────────────────────────────────────

class TestHasViolation(unittest.TestCase):
    def test_open_kanban_write_is_violation(self):
        content = "with open('KANBAN.json', 'w') as f:\n    json.dump(k, f)"
        hits = lk._has_violation(content)
        self.assertTrue(len(hits) > 0)

    def test_json_dump_kanban_on_same_line_is_violation(self):
        content = "json.dump(k, open('KANBAN.json', 'w'))"
        hits = lk._has_violation(content)
        self.assertTrue(len(hits) > 0)

    def test_direct_done_count_assign_is_violation(self):
        content = 'k["done_count"] = 42'
        hits = lk._has_violation(content)
        self.assertTrue(len(hits) > 0)

    def test_safe_read_only_access_is_not_violation(self):
        content = "with open('KANBAN.json', 'r') as f:\n    k = json.load(f)"
        hits = lk._has_violation(content)
        self.assertEqual(hits, [])

    def test_clean_python_file_has_no_violation(self):
        content = "import os\nprint('hello world')\n"
        hits = lk._has_violation(content)
        self.assertEqual(hits, [])


# ─────────────────────────────────────────────
# scan_file()
# ─────────────────────────────────────────────

class TestScanFile(unittest.TestCase):
    def test_violation_file_returns_report(self):
        content = (
            "import json\n"
            "with open('KANBAN.json', 'r') as f:\n"
            "    k = json.load(f)\n"
            "with open('KANBAN.json', 'w') as fw:\n"
            "    json.dump(k, fw)\n"
        )
        with _TmpFile(content) as path:
            result = lk.scan_file(path)
        self.assertIsNotNone(result)
        self.assertEqual(result["severity"], "error")

    def test_file_with_safe_helper_is_not_error(self):
        content = (
            "from spa_core.utils.kanban import increment_done\n"
            "# touches KANBAN.json\n"
            "increment_done(n=1)\n"
        )
        with _TmpFile(content) as path:
            result = lk.scan_file(path)
        # No direct write pattern → no violation
        self.assertIsNone(result)

    def test_non_kanban_file_returns_none(self):
        content = "import os\nprint('no kanban here')\n"
        with _TmpFile(content) as path:
            result = lk.scan_file(path)
        self.assertIsNone(result)

    def test_violation_report_contains_path(self):
        content = "with open('KANBAN.json', 'w') as f:\n    pass\n"
        with _TmpFile(content) as path:
            result = lk.scan_file(path)
        self.assertIsNotNone(result)
        self.assertIn("path", result)

    def test_violation_report_contains_line_numbers(self):
        content = "with open('KANBAN.json', 'w') as f:\n    pass\n"
        with _TmpFile(content) as path:
            result = lk.scan_file(path)
        self.assertIsNotNone(result)
        self.assertTrue(len(result["violations"]) > 0)
        lineno, _ = result["violations"][0]
        self.assertIsInstance(lineno, int)


# ─────────────────────────────────────────────
# scan_directory()
# ─────────────────────────────────────────────

class TestScanDirectory(unittest.TestCase):
    def test_empty_directory_returns_no_violations(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            results = lk.scan_directory(tmp_dir)
        self.assertEqual(results, [])

    def test_directory_with_violation_returns_result(self):
        content = (
            "import json\n"
            "with open('KANBAN.json', 'w') as fw:\n"
            "    json.dump({}, fw)\n"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            bad_file = os.path.join(tmp_dir, "bad_agent.py")
            with open(bad_file, "w") as f:
                f.write(content)
            results = lk.scan_directory(tmp_dir)
        self.assertEqual(len(results), 1)

    def test_directory_with_safe_file_returns_no_violations(self):
        content = (
            "from spa_core.utils.kanban import increment_done\n"
            "# KANBAN.json\n"
            "increment_done(n=1)\n"
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            good_file = os.path.join(tmp_dir, "good_agent.py")
            with open(good_file, "w") as f:
                f.write(content)
            results = lk.scan_directory(tmp_dir)
        self.assertEqual(results, [])

    def test_skip_paths_are_excluded(self):
        """Files inside __pycache__ should be skipped."""
        content = "with open('KANBAN.json', 'w') as f:\n    pass\n"
        with tempfile.TemporaryDirectory() as tmp_dir:
            pycache = os.path.join(tmp_dir, "__pycache__")
            os.makedirs(pycache)
            bad_file = os.path.join(pycache, "cached.py")
            with open(bad_file, "w") as f:
                f.write(content)
            results = lk.scan_directory(tmp_dir)
        self.assertEqual(results, [])

    def test_non_python_sh_files_are_scanned(self):
        """Shell scripts writing to KANBAN.json should be caught."""
        content = "echo '{}' > KANBAN.json\n"
        with tempfile.TemporaryDirectory() as tmp_dir:
            sh_file = os.path.join(tmp_dir, "bad_script.sh")
            with open(sh_file, "w") as f:
                f.write(content)
            results = lk.scan_directory(tmp_dir)
        self.assertEqual(len(results), 1)

    def test_txt_files_are_not_scanned(self):
        """Only .py / .sh / .command are in scope."""
        content = "open('KANBAN.json', 'w')\n"
        with tempfile.TemporaryDirectory() as tmp_dir:
            txt_file = os.path.join(tmp_dir, "notes.txt")
            with open(txt_file, "w") as f:
                f.write(content)
            results = lk.scan_directory(tmp_dir)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
