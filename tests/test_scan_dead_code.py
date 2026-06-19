"""
tests/test_scan_dead_code.py

25 unit tests for scripts/scan_dead_code.py
Run: python3 -m unittest tests/test_scan_dead_code.py -v
"""

import json
import os
import sys
import tempfile
import textwrap
import unittest

# Allow importing from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import scan_dead_code as sdc


def _write(path: str, content: str = ""):
    """Helper: create file with content, making parent dirs."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(content))


def _make_spa(base: str):
    """Build a tiny spa_core tree under base/ for testing."""
    # spa_core/__init__.py
    _write(os.path.join(base, "spa_core", "__init__.py"), "")
    # spa_core/alpha.py — 10 meaningful lines (stub)
    _write(os.path.join(base, "spa_core", "alpha.py"),
           "\n".join([f"x_{i} = {i}" for i in range(10)]) + "\n")
    # spa_core/beta.py — 60 meaningful lines (non-stub)
    _write(os.path.join(base, "spa_core", "beta.py"),
           "\n".join([f"y_{i} = {i}" for i in range(60)]) + "\n")
    # spa_core/gamma.py — imports alpha
    _write(os.path.join(base, "spa_core", "gamma.py"),
           "from spa_core import alpha\nimport beta\nx = 1\n")
    return os.path.join(base, "spa_core")


def _make_tests(base: str):
    """Build a tiny tests dir — only test_beta.py exists."""
    tests_dir = os.path.join(base, "tests")
    os.makedirs(tests_dir, exist_ok=True)
    _write(os.path.join(tests_dir, "test_beta.py"),
           "import unittest\nclass T(unittest.TestCase): pass\n")
    return tests_dir


class TestFindModules(unittest.TestCase):
    # 1
    def test_returns_list(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            result = sdc.find_modules(spa)
            self.assertIsInstance(result, list)

    # 2
    def test_nonexistent_dir_returns_empty(self):
        result = sdc.find_modules("/tmp/_no_such_spa_dir_999")
        self.assertEqual(result, [])

    # 3
    def test_finds_py_files(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            result = sdc.find_modules(spa)
            basenames = [os.path.basename(p) for p in result]
            self.assertIn("alpha.py", basenames)
            self.assertIn("beta.py", basenames)

    # 4
    def test_sorted_output(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            result = sdc.find_modules(spa)
            self.assertEqual(result, sorted(result))

    # 5
    def test_excludes_pycache(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            pycache = os.path.join(spa, "__pycache__")
            os.makedirs(pycache, exist_ok=True)
            _write(os.path.join(pycache, "alpha.cpython-311.pyc"), "")
            result = sdc.find_modules(spa)
            self.assertFalse(any("__pycache__" in p for p in result))


class TestFindTests(unittest.TestCase):
    # 6
    def test_returns_set(self):
        with tempfile.TemporaryDirectory() as base:
            td = _make_tests(base)
            result = sdc.find_tests(td)
            self.assertIsInstance(result, set)

    # 7
    def test_discovers_tested_module(self):
        with tempfile.TemporaryDirectory() as base:
            td = _make_tests(base)
            result = sdc.find_tests(td)
            self.assertIn("beta", result)

    # 8
    def test_nonexistent_dir_returns_empty_set(self):
        result = sdc.find_tests("/tmp/_no_tests_999")
        self.assertEqual(result, set())

    # 9
    def test_does_not_include_non_test_files(self):
        with tempfile.TemporaryDirectory() as d:
            _write(os.path.join(d, "helper.py"), "x=1\n")
            result = sdc.find_tests(d)
            self.assertNotIn("helper", result)


class TestModulesWithoutTests(unittest.TestCase):
    # 10
    def test_returns_list(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            td = _make_tests(base)
            mods = sdc.find_modules(spa)
            tests_set = sdc.find_tests(td)
            result = sdc.modules_without_tests(mods, tests_set)
            self.assertIsInstance(result, list)

    # 11
    def test_untested_module_in_list(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            td = _make_tests(base)
            mods = sdc.find_modules(spa)
            tests_set = sdc.find_tests(td)
            result = sdc.modules_without_tests(mods, tests_set)
            basenames = [os.path.basename(p) for p in result]
            self.assertIn("alpha.py", basenames)

    # 12
    def test_tested_module_not_in_list(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            td = _make_tests(base)
            mods = sdc.find_modules(spa)
            tests_set = sdc.find_tests(td)
            result = sdc.modules_without_tests(mods, tests_set)
            basenames = [os.path.basename(p) for p in result]
            self.assertNotIn("beta.py", basenames)

    # 13
    def test_init_excluded(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            td = _make_tests(base)
            mods = sdc.find_modules(spa)
            tests_set = sdc.find_tests(td)
            result = sdc.modules_without_tests(mods, tests_set)
            basenames = [os.path.basename(p) for p in result]
            self.assertNotIn("__init__.py", basenames)


class TestFindAllImports(unittest.TestCase):
    # 14
    def test_returns_dict(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            result = sdc.find_all_imports(spa)
            self.assertIsInstance(result, dict)

    # 15
    def test_values_are_lists(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            result = sdc.find_all_imports(spa)
            for v in result.values():
                self.assertIsInstance(v, list)

    # 16
    def test_imported_module_in_map(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            # gamma.py imports alpha and beta
            result = sdc.find_all_imports(spa)
            self.assertIn("alpha", result)


class TestOrphanModules(unittest.TestCase):
    # 17
    def test_returns_list(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            mods = sdc.find_modules(spa)
            imp_map = sdc.find_all_imports(spa)
            result = sdc.orphan_modules(mods, imp_map)
            self.assertIsInstance(result, list)

    # 18
    def test_init_not_in_orphans(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            mods = sdc.find_modules(spa)
            imp_map = sdc.find_all_imports(spa)
            result = sdc.orphan_modules(mods, imp_map)
            basenames = [os.path.basename(p) for p in result]
            self.assertNotIn("__init__.py", basenames)

    # 19
    def test_imported_module_not_orphan(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            mods = sdc.find_modules(spa)
            imp_map = sdc.find_all_imports(spa)
            result = sdc.orphan_modules(mods, imp_map)
            basenames = [os.path.basename(p) for p in result]
            # alpha is imported by gamma.py, so should not be orphan
            self.assertNotIn("alpha.py", basenames)

    # 20
    def test_truly_orphan_detected(self):
        with tempfile.TemporaryDirectory() as base:
            spa_dir = os.path.join(base, "spa_core")
            os.makedirs(spa_dir, exist_ok=True)
            _write(os.path.join(spa_dir, "__init__.py"), "")
            # isolated.py is never imported by anything
            _write(os.path.join(spa_dir, "isolated.py"), "x = 1\n")
            # importer.py imports nothing from isolated
            _write(os.path.join(spa_dir, "importer.py"), "import os\n")
            mods = sdc.find_modules(spa_dir)
            imp_map = sdc.find_all_imports(spa_dir)
            result = sdc.orphan_modules(mods, imp_map)
            basenames = [os.path.basename(p) for p in result]
            self.assertIn("isolated.py", basenames)


class TestStubModules(unittest.TestCase):
    # 21
    def test_returns_list(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            mods = sdc.find_modules(spa)
            result = sdc.stub_modules(mods)
            self.assertIsInstance(result, list)

    # 22
    def test_small_file_is_stub(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            mods = sdc.find_modules(spa)
            result = sdc.stub_modules(mods, min_lines=50)
            basenames = [os.path.basename(p) for p in result]
            # alpha.py has 10 lines → stub
            self.assertIn("alpha.py", basenames)

    # 23
    def test_large_file_not_stub(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            mods = sdc.find_modules(spa)
            result = sdc.stub_modules(mods, min_lines=50)
            basenames = [os.path.basename(p) for p in result]
            # beta.py has 60 lines → not a stub
            self.assertNotIn("beta.py", basenames)

    # 24
    def test_zero_threshold_includes_empty(self):
        with tempfile.TemporaryDirectory() as base:
            spa_dir = os.path.join(base, "spa_core")
            os.makedirs(spa_dir, exist_ok=True)
            _write(os.path.join(spa_dir, "empty.py"), "")
            mods = sdc.find_modules(spa_dir)
            result = sdc.stub_modules(mods, min_lines=1)
            basenames = [os.path.basename(p) for p in result]
            self.assertIn("empty.py", basenames)


class TestReport(unittest.TestCase):
    # 25 — report has all required keys
    def test_report_required_keys(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            td = _make_tests(base)
            result = sdc.report(spa, td)
            for key in ("no_tests", "orphans", "stubs", "summary"):
                self.assertIn(key, result)

    def test_report_summary_has_counts(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            td = _make_tests(base)
            result = sdc.report(spa, td)
            s = result["summary"]
            for key in ("total_modules", "no_tests_count", "orphans_count", "stubs_count"):
                self.assertIn(key, s)

    def test_report_no_tests_is_list(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            td = _make_tests(base)
            result = sdc.report(spa, td)
            self.assertIsInstance(result["no_tests"], list)

    def test_report_orphans_is_list(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            td = _make_tests(base)
            result = sdc.report(spa, td)
            self.assertIsInstance(result["orphans"], list)

    def test_report_stubs_is_list(self):
        with tempfile.TemporaryDirectory() as base:
            spa = _make_spa(base)
            td = _make_tests(base)
            result = sdc.report(spa, td)
            self.assertIsInstance(result["stubs"], list)


class TestSave(unittest.TestCase):
    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as base:
            path = os.path.join(base, "data", "report.json")
            data = {"no_tests": [], "orphans": [], "stubs": [], "summary": {}}
            result_path = sdc.save(data, path)
            self.assertTrue(os.path.exists(result_path))

    def test_save_returns_path(self):
        with tempfile.TemporaryDirectory() as base:
            path = os.path.join(base, "data", "report.json")
            data = {"no_tests": [], "orphans": [], "stubs": [], "summary": {}}
            result = sdc.save(data, path)
            self.assertEqual(result, path)

    def test_save_valid_json(self):
        with tempfile.TemporaryDirectory() as base:
            path = os.path.join(base, "data", "report.json")
            data = {"no_tests": ["a"], "orphans": [], "stubs": [], "summary": {"x": 1}}
            sdc.save(data, path)
            with open(path, "r") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["no_tests"], ["a"])

    def test_save_no_tmp_file_remains(self):
        with tempfile.TemporaryDirectory() as base:
            path = os.path.join(base, "data", "report.json")
            data = {"no_tests": [], "orphans": [], "stubs": [], "summary": {}}
            sdc.save(data, path)
            self.assertFalse(os.path.exists(path + ".tmp"))


if __name__ == "__main__":
    unittest.main()
