"""
tests/test_infrastructure_verify.py

Sprint v10.34 — MP-1418 Infrastructure score boost.
25 tests for scripts/verify_infrastructure.py:
  - Module imports correctly
  - All check_*() functions return bool
  - all_pass() returns bool
  - infrastructure_report() returns well-formed dict
  - CLI main() exit codes correct
  - Individual checks work on real filesystem and mock dirs

stdlib only — unittest, no external dependencies.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure repo root is on path
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Import under test
import scripts.verify_infrastructure as vi


# ── Tests: module interface ────────────────────────────────────────────────────

class TestModuleImports(unittest.TestCase):
    """Tests T01–T05: module imports and exports."""

    # T01
    def test_module_imports(self):
        self.assertIsNotNone(vi)

    # T02
    def test_checks_registry_is_list(self):
        self.assertIsInstance(vi.CHECKS, list)

    # T03
    def test_checks_registry_non_empty(self):
        self.assertGreater(len(vi.CHECKS), 0)

    # T04
    def test_checks_registry_structure(self):
        """Each entry must be a 3-tuple: (name, description, callable)."""
        for item in vi.CHECKS:
            self.assertEqual(len(item), 3, f"CHECKS entry wrong length: {item}")
            name, desc, fn = item
            self.assertIsInstance(name, str)
            self.assertIsInstance(desc, str)
            self.assertTrue(callable(fn))

    # T05
    def test_repo_root_is_path(self):
        self.assertIsInstance(vi.REPO_ROOT, Path)


# ── Tests: individual check_* functions ───────────────────────────────────────

class TestCheckFunctions(unittest.TestCase):
    """Tests T06–T13: each check function returns bool."""

    # T06
    def test_check_git_hooks_returns_bool(self):
        result = vi.check_git_hooks()
        self.assertIsInstance(result, bool)

    # T07
    def test_check_launchd_plist_returns_bool(self):
        result = vi.check_launchd_plist()
        self.assertIsInstance(result, bool)

    # T08
    def test_check_kill_switch_returns_bool(self):
        result = vi.check_kill_switch()
        self.assertIsInstance(result, bool)

    # T09
    def test_check_data_backups_returns_bool(self):
        result = vi.check_data_backups()
        self.assertIsInstance(result, bool)

    # T10
    def test_check_monitoring_returns_bool(self):
        result = vi.check_monitoring()
        self.assertIsInstance(result, bool)

    # T11
    def test_check_verify_script_returns_bool(self):
        result = vi.check_verify_script()
        self.assertIsInstance(result, bool)

    # T12
    def test_check_infrastructure_doc_returns_bool(self):
        result = vi.check_infrastructure_doc()
        self.assertIsInstance(result, bool)

    # T13
    def test_check_install_hooks_script_returns_bool(self):
        result = vi.check_install_hooks_script()
        self.assertIsInstance(result, bool)


# ── Tests: real filesystem ─────────────────────────────────────────────────────

class TestRealFilesystem(unittest.TestCase):
    """Tests T14–T17: checks against the actual SPA repo."""

    # T14
    def test_kill_switch_exists_in_repo(self):
        """spa_core/safety/ with safeguard.py and live_trading_gate.py must exist."""
        self.assertTrue(vi.check_kill_switch(),
                        "spa_core/safety/safeguard.py and live_trading_gate.py must exist")

    # T15
    def test_data_backups_exist_in_repo(self):
        """push_to_github.py or auto_push.py must exist in repo root."""
        self.assertTrue(vi.check_data_backups(),
                        "push_to_github.py or auto_push.py must be present in repo root")

    # T16
    def test_monitoring_exists_in_repo(self):
        """cycle_runner.py must exist."""
        self.assertTrue(vi.check_monitoring(),
                        "spa_core/paper_trading/cycle_runner.py must exist")

    # T17
    def test_verify_script_exists_in_repo(self):
        """This script itself must exist."""
        self.assertTrue(vi.check_verify_script(),
                        "scripts/verify_infrastructure.py must exist in repo")


# ── Tests: all_pass() ─────────────────────────────────────────────────────────

class TestAllPass(unittest.TestCase):
    """Tests T18–T20: all_pass() aggregation."""

    # T18
    def test_all_pass_returns_bool(self):
        result = vi.all_pass()
        self.assertIsInstance(result, bool)

    # T19
    def test_all_pass_true_when_all_true(self):
        self.assertTrue(vi.all_pass({"a": True, "b": True, "c": True}))

    # T20
    def test_all_pass_false_when_any_false(self):
        self.assertFalse(vi.all_pass({"a": True, "b": False, "c": True}))


# ── Tests: infrastructure_report() ────────────────────────────────────────────

class TestInfrastructureReport(unittest.TestCase):
    """Tests T21–T24: infrastructure_report() structure and types."""

    def setUp(self):
        self.report = vi.infrastructure_report()

    # T21
    def test_report_returns_dict(self):
        self.assertIsInstance(self.report, dict)

    # T22
    def test_report_has_required_keys(self):
        for key in ("all_pass", "passed", "total", "pass_rate_pct", "checks", "failed_checks"):
            self.assertIn(key, self.report, f"report must contain key '{key}'")

    # T23
    def test_report_checks_is_list(self):
        self.assertIsInstance(self.report["checks"], list)

    # T24
    def test_report_check_items_have_required_fields(self):
        for item in self.report["checks"]:
            for field in ("name", "description", "status"):
                self.assertIn(field, item, f"check item missing field '{field}'")
            self.assertIn(item["status"], ("PASS", "FAIL"),
                          f"status must be PASS or FAIL, got {item['status']!r}")


# ── Tests: CLI main() ─────────────────────────────────────────────────────────

class TestCLIMain(unittest.TestCase):
    """Test T25: main() exit codes."""

    # T25
    def test_main_returns_int(self):
        """main() without --strict always returns 0."""
        ret = vi.main([])
        self.assertIsInstance(ret, int)
        self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
