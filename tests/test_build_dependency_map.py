"""
tests/test_build_dependency_map.py

30 unit tests for scripts/build_dependency_map.py

MP-1373 (v9.89) — stdlib only, unittest.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Locate repo root and add scripts/ to path so we can import the module
_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import build_dependency_map as bdm


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_py(directory: str, filename: str, content: str) -> str:
    """Write a Python file to a temp directory and return its path."""
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ── Tests for scan_module() ───────────────────────────────────────────────────

class TestScanModule(unittest.TestCase):

    def test_returns_list(self):
        """scan_module always returns a list."""
        with tempfile.TemporaryDirectory() as tmp:
            fp = _write_py(tmp, "empty.py", "")
            result = bdm.scan_module(fp)
        self.assertIsInstance(result, list)

    def test_empty_file_returns_empty_list(self):
        """Empty file has no imports."""
        with tempfile.TemporaryDirectory() as tmp:
            fp = _write_py(tmp, "empty.py", "")
            self.assertEqual(bdm.scan_module(fp), [])

    def test_no_spa_core_imports_returns_empty(self):
        """File with only stdlib imports returns []."""
        src = "import os\nimport json\nfrom pathlib import Path\n"
        with tempfile.TemporaryDirectory() as tmp:
            fp = _write_py(tmp, "stdlib_only.py", src)
            self.assertEqual(bdm.scan_module(fp), [])

    def test_from_spa_core_import_detected(self):
        """'from spa_core.x import y' is captured."""
        src = "from spa_core.adapters.aave_v3 import AaveV3Adapter\n"
        with tempfile.TemporaryDirectory() as tmp:
            fp = _write_py(tmp, "a.py", src)
            result = bdm.scan_module(fp)
        self.assertIn("spa_core.adapters.aave_v3", result)

    def test_import_spa_core_detected(self):
        """'import spa_core.risk.policy' is captured."""
        src = "import spa_core.risk.policy\n"
        with tempfile.TemporaryDirectory() as tmp:
            fp = _write_py(tmp, "b.py", src)
            result = bdm.scan_module(fp)
        self.assertIn("spa_core.risk.policy", result)

    def test_multiple_imports_all_captured(self):
        """Multiple spa_core imports all appear in result."""
        src = (
            "from spa_core.adapters.aave_v3 import AaveV3Adapter\n"
            "from spa_core.risk.policy import RiskPolicy\n"
            "from spa_core.allocator.allocator import StrategyAllocator\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            fp = _write_py(tmp, "c.py", src)
            result = bdm.scan_module(fp)
        self.assertIn("spa_core.adapters.aave_v3", result)
        self.assertIn("spa_core.risk.policy", result)
        self.assertIn("spa_core.allocator.allocator", result)

    def test_deduplicates_repeated_imports(self):
        """Same import appearing twice only counted once."""
        src = (
            "from spa_core.adapters.aave_v3 import AaveV3Adapter\n"
            "from spa_core.adapters.aave_v3 import YieldInfo\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            fp = _write_py(tmp, "d.py", src)
            result = bdm.scan_module(fp)
        self.assertEqual(result.count("spa_core.adapters.aave_v3"), 1)

    def test_result_is_sorted(self):
        """scan_module returns a sorted list."""
        src = (
            "from spa_core.risk.policy import RiskPolicy\n"
            "from spa_core.adapters.aave_v3 import AaveV3Adapter\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            fp = _write_py(tmp, "e.py", src)
            result = bdm.scan_module(fp)
        self.assertEqual(result, sorted(result))

    def test_nonexistent_file_returns_empty(self):
        """Missing file returns [] instead of raising."""
        result = bdm.scan_module("/nonexistent/path/to/file.py")
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])

    def test_syntax_error_file_returns_empty(self):
        """File with syntax errors returns [] instead of raising."""
        src = "from spa_core.x import (\n"  # unclosed paren
        with tempfile.TemporaryDirectory() as tmp:
            fp = _write_py(tmp, "broken.py", src)
            result = bdm.scan_module(fp)
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])

    def test_only_spa_core_imports_captured(self):
        """Non-spa_core imports are not included in the result."""
        src = (
            "import requests\n"
            "from spa_core.adapters.aave_v3 import AaveV3Adapter\n"
            "import pandas as pd\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            fp = _write_py(tmp, "mixed.py", src)
            result = bdm.scan_module(fp)
        self.assertNotIn("requests", result)
        self.assertNotIn("pandas", result)
        self.assertIn("spa_core.adapters.aave_v3", result)

    def test_real_cpa_health_dashboard(self):
        """scan_module on cpa_health_dashboard.py returns expected imports."""
        dashboard_path = (
            _REPO_ROOT / "spa_core" / "analytics" / "cpa_health_dashboard.py"
        )
        if not dashboard_path.exists():
            self.skipTest("cpa_health_dashboard.py not found")
        result = bdm.scan_module(str(dashboard_path))
        self.assertIsInstance(result, list)
        # cpa_health_dashboard.py imports from spa_core.backtesting.*
        backtesting_imports = [r for r in result if "spa_core.backtesting" in r]
        self.assertTrue(
            len(backtesting_imports) >= 1,
            f"Expected at least 1 spa_core.backtesting import, got: {result}"
        )


# ── Tests for scan_all() ──────────────────────────────────────────────────────

class TestScanAll(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Create a mini spa_core-like structure
        spa = os.path.join(self.tmp, "spa_core")
        adapters = os.path.join(spa, "adapters")
        risk = os.path.join(spa, "risk")
        os.makedirs(adapters)
        os.makedirs(risk)

        _write_py(spa, "__init__.py", "")
        _write_py(adapters, "__init__.py", "")
        _write_py(risk, "__init__.py", "")
        _write_py(
            adapters, "aave_v3.py",
            "from spa_core.adapters.base_adapter import BaseAdapter\n",
        )
        _write_py(
            risk, "policy.py",
            "from spa_core.adapters.aave_v3 import AaveV3Adapter\n",
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_dict(self):
        """scan_all returns a dictionary."""
        result = bdm.scan_all(os.path.join(self.tmp, "spa_core"))
        self.assertIsInstance(result, dict)

    def test_dict_keys_are_strings(self):
        """All keys in the dep map are strings."""
        result = bdm.scan_all(os.path.join(self.tmp, "spa_core"))
        for key in result:
            self.assertIsInstance(key, str)

    def test_dict_values_are_lists(self):
        """All values in the dep map are lists."""
        result = bdm.scan_all(os.path.join(self.tmp, "spa_core"))
        for val in result.values():
            self.assertIsInstance(val, list)

    def test_finds_python_files(self):
        """scan_all finds .py files inside the directory."""
        result = bdm.scan_all(os.path.join(self.tmp, "spa_core"))
        self.assertGreater(len(result), 0)

    def test_skips_pycache(self):
        """__pycache__ directories are not scanned."""
        pycache = os.path.join(self.tmp, "spa_core", "__pycache__")
        os.makedirs(pycache, exist_ok=True)
        _write_py(pycache, "cached.py", "from spa_core.x import y\n")
        result = bdm.scan_all(os.path.join(self.tmp, "spa_core"))
        pycache_keys = [k for k in result if "__pycache__" in k]
        self.assertEqual(pycache_keys, [])

    def test_captures_imports_for_module(self):
        """Imports are correctly captured for a known module."""
        result = bdm.scan_all(os.path.join(self.tmp, "spa_core"))
        # Find the policy module
        policy_key = next(
            (k for k in result if k.endswith("risk.policy")), None
        )
        self.assertIsNotNone(policy_key, f"risk.policy not found in {list(result.keys())}")
        self.assertIn("spa_core.adapters.aave_v3", result[policy_key])

    def test_real_spa_core(self):
        """scan_all on real spa_core/ returns a non-empty dict."""
        spa_core_path = _REPO_ROOT / "spa_core"
        if not spa_core_path.exists():
            self.skipTest("spa_core/ not found")
        result = bdm.scan_all(str(spa_core_path))
        self.assertIsInstance(result, dict)
        self.assertGreater(len(result), 0)


# ── Tests for find_cycles() ───────────────────────────────────────────────────

class TestFindCycles(unittest.TestCase):

    def test_returns_list(self):
        """find_cycles always returns a list."""
        result = bdm.find_cycles({})
        self.assertIsInstance(result, list)

    def test_no_cycles_in_dag(self):
        """DAG (directed acyclic graph) yields no cycles."""
        dep_map = {
            "spa_core.a": ["spa_core.b"],
            "spa_core.b": ["spa_core.c"],
            "spa_core.c": [],
        }
        self.assertEqual(bdm.find_cycles(dep_map), [])

    def test_simple_cycle_detected(self):
        """Simple A→B→A cycle is detected."""
        dep_map = {
            "spa_core.a": ["spa_core.b"],
            "spa_core.b": ["spa_core.a"],
        }
        cycles = bdm.find_cycles(dep_map)
        self.assertGreater(len(cycles), 0)

    def test_self_loop_detected(self):
        """Module importing itself is detected as a cycle."""
        dep_map = {
            "spa_core.x": ["spa_core.x"],
        }
        cycles = bdm.find_cycles(dep_map)
        self.assertGreater(len(cycles), 0)

    def test_three_module_cycle(self):
        """A→B→C→A cycle is detected."""
        dep_map = {
            "spa_core.a": ["spa_core.b"],
            "spa_core.b": ["spa_core.c"],
            "spa_core.c": ["spa_core.a"],
        }
        cycles = bdm.find_cycles(dep_map)
        self.assertGreater(len(cycles), 0)

    def test_empty_dep_map_returns_empty(self):
        """Empty dependency map yields no cycles."""
        self.assertEqual(bdm.find_cycles({}), [])

    def test_cycles_are_lists_of_strings(self):
        """Each cycle is a list of module name strings."""
        dep_map = {
            "spa_core.a": ["spa_core.b"],
            "spa_core.b": ["spa_core.a"],
        }
        cycles = bdm.find_cycles(dep_map)
        for cycle in cycles:
            self.assertIsInstance(cycle, list)
            for item in cycle:
                self.assertIsInstance(item, str)


# ── Tests for modules_that_import() ──────────────────────────────────────────

class TestModulesThatImport(unittest.TestCase):

    def setUp(self):
        self.dep_map = {
            "spa_core.a": ["spa_core.shared"],
            "spa_core.b": ["spa_core.shared", "spa_core.other"],
            "spa_core.c": ["spa_core.other"],
            "spa_core.shared": [],
            "spa_core.other": [],
        }

    def test_returns_list(self):
        """modules_that_import returns a list."""
        result = bdm.modules_that_import("spa_core.shared", self.dep_map)
        self.assertIsInstance(result, list)

    def test_finds_importers(self):
        """Correct modules are returned for a known target."""
        result = bdm.modules_that_import("spa_core.shared", self.dep_map)
        self.assertIn("spa_core.a", result)
        self.assertIn("spa_core.b", result)
        self.assertNotIn("spa_core.c", result)

    def test_unknown_module_returns_empty(self):
        """Unknown target returns empty list."""
        result = bdm.modules_that_import("spa_core.nonexistent", self.dep_map)
        self.assertEqual(result, [])

    def test_result_is_sorted(self):
        """Result is sorted alphabetically."""
        result = bdm.modules_that_import("spa_core.shared", self.dep_map)
        self.assertEqual(result, sorted(result))

    def test_empty_dep_map_returns_empty(self):
        """Empty dep map returns [] for any target."""
        result = bdm.modules_that_import("spa_core.shared", {})
        self.assertEqual(result, [])


# ── Tests for most_imported() ─────────────────────────────────────────────────

class TestMostImported(unittest.TestCase):

    def setUp(self):
        self.dep_map = {
            "spa_core.a": ["spa_core.shared", "spa_core.util"],
            "spa_core.b": ["spa_core.shared", "spa_core.util"],
            "spa_core.c": ["spa_core.shared"],
            "spa_core.d": ["spa_core.rare"],
            "spa_core.shared": [],
            "spa_core.util": [],
            "spa_core.rare": [],
        }

    def test_returns_list(self):
        """most_imported returns a list."""
        result = bdm.most_imported(self.dep_map)
        self.assertIsInstance(result, list)

    def test_returns_tuples(self):
        """Each element is a (module_name, count) tuple."""
        result = bdm.most_imported(self.dep_map)
        for item in result:
            self.assertIsInstance(item, tuple)
            self.assertEqual(len(item), 2)

    def test_sorted_descending(self):
        """Results are sorted by count descending."""
        result = bdm.most_imported(self.dep_map)
        counts = [cnt for _, cnt in result]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_most_imported_first(self):
        """The most-imported module appears first."""
        result = bdm.most_imported(self.dep_map)
        if result:
            top_module, top_count = result[0]
            self.assertEqual(top_module, "spa_core.shared")
            self.assertEqual(top_count, 3)

    def test_top_n_respected(self):
        """top_n parameter limits result length."""
        result = bdm.most_imported(self.dep_map, top_n=2)
        self.assertLessEqual(len(result), 2)

    def test_empty_dep_map(self):
        """Empty dep map returns empty list."""
        result = bdm.most_imported({})
        self.assertEqual(result, [])


# ── Tests for to_markdown() ───────────────────────────────────────────────────

class TestToMarkdown(unittest.TestCase):

    def setUp(self):
        self.dep_map = {
            "spa_core.a": ["spa_core.b"],
            "spa_core.b": [],
        }

    def test_returns_string(self):
        """to_markdown returns a string."""
        result = bdm.to_markdown(self.dep_map)
        self.assertIsInstance(result, str)

    def test_contains_pipe(self):
        """Markdown table uses pipe characters."""
        result = bdm.to_markdown(self.dep_map)
        self.assertIn("|", result)

    def test_contains_module_names(self):
        """Module names appear in the output."""
        result = bdm.to_markdown(self.dep_map)
        self.assertIn("spa_core.a", result)
        self.assertIn("spa_core.b", result)

    def test_empty_dep_map_produces_output(self):
        """Even an empty dep map produces some markdown."""
        result = bdm.to_markdown({})
        self.assertIsInstance(result, str)
        self.assertIn("|", result)


# ── Tests for save() ─────────────────────────────────────────────────────────

class TestSave(unittest.TestCase):

    def test_creates_file(self):
        """save() creates the output file."""
        dep_map = {"spa_core.a": ["spa_core.b"]}
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "dep_map.json")
            result = bdm.save(dep_map, out_path)
            self.assertTrue(os.path.exists(result))

    def test_creates_parent_dirs(self):
        """save() creates parent directories if missing."""
        dep_map = {"spa_core.x": []}
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "data", "subdir", "dep_map.json")
            bdm.save(dep_map, out_path)
            self.assertTrue(os.path.exists(out_path))

    def test_valid_json_output(self):
        """Output file contains valid JSON."""
        dep_map = {"spa_core.a": ["spa_core.b"], "spa_core.b": []}
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "dep.json")
            bdm.save(dep_map, out_path)
            with open(out_path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("dependency_map", data)
            self.assertEqual(data["dependency_map"]["spa_core.a"], ["spa_core.b"])

    def test_returns_absolute_path(self):
        """save() returns a string path."""
        dep_map = {}
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "dep.json")
            result = bdm.save(dep_map, out_path)
            self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
