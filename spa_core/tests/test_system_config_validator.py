"""
Tests for spa_core.analytics.system_config_validator (MP-636).

Coverage: 43 unit tests across:
  - TestValidationResultDataclass   (5)
  - TestCheckFileExists             (7)
  - TestCheckJsonValid              (7)
  - TestCheckPythonSyntax           (7)
  - TestCheckAnalyticsModule        (7)
  - TestRunAllChecks                (5)
  - TestGenerateReport              (8)
  - TestNowIso                      (1)   (total = 47)

All tests use tempfile.TemporaryDirectory() so production files are
never touched.

Run:
  python3 -m pytest spa_core/tests/test_system_config_validator.py -v
  python3 -m unittest spa_core.tests.test_system_config_validator -v
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
import unittest
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from spa_core.analytics.system_config_validator import (
    SEV_CRITICAL,
    SEV_WARNING,
    SEV_INFO,
    ValidationResult,
    SystemConfigValidator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_validator(tmp_dir: str) -> SystemConfigValidator:
    """Create a validator rooted at tmp_dir."""
    return SystemConfigValidator(project_root=Path(tmp_dir))


def _write_file(directory: str, relative: str, content: str) -> Path:
    """Write content to tmp_dir/relative, creating parent dirs."""
    p = Path(directory) / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _create_required_files(tmp_dir: str) -> None:
    """Seed a tmp directory with all REQUIRED_FILES stubs."""
    for filepath in SystemConfigValidator.REQUIRED_FILES:
        if filepath.endswith(".json"):
            _write_file(tmp_dir, filepath, "{}")
        else:
            _write_file(tmp_dir, filepath, "# stub\n")


def _create_analytics_modules(tmp_dir: str) -> None:
    """Seed a tmp directory with all REQUIRED_ANALYTICS stubs."""
    for module_name in SystemConfigValidator.REQUIRED_ANALYTICS:
        relative = f"spa_core/analytics/{module_name}.py"
        _write_file(tmp_dir, relative, f"# {module_name} stub\n")


def _seed_all(tmp_dir: str) -> None:
    """Create both required files and analytics modules."""
    _create_required_files(tmp_dir)
    _create_analytics_modules(tmp_dir)


# ===========================================================================
# TestValidationResultDataclass
# ===========================================================================

class TestValidationResultDataclass(unittest.TestCase):
    """Tests for ValidationResult construction."""

    def test_create_passed(self):
        r = ValidationResult(
            check_name="test", passed=True, severity=SEV_INFO,
            message="OK", file_path=None,
        )
        self.assertTrue(r.passed)
        self.assertEqual(r.severity, SEV_INFO)

    def test_create_failed_critical(self):
        r = ValidationResult(
            check_name="test", passed=False, severity=SEV_CRITICAL,
            message="Missing", file_path="/some/path",
        )
        self.assertFalse(r.passed)
        self.assertEqual(r.severity, SEV_CRITICAL)

    def test_file_path_can_be_none(self):
        r = ValidationResult(
            check_name="x", passed=True, severity=SEV_INFO,
            message="ok", file_path=None,
        )
        self.assertIsNone(r.file_path)

    def test_all_fields_set(self):
        r = ValidationResult("c", True, SEV_WARNING, "msg", "/p")
        self.assertEqual(r.check_name, "c")
        self.assertEqual(r.message, "msg")
        self.assertEqual(r.file_path, "/p")

    def test_severity_warning(self):
        r = ValidationResult("x", False, SEV_WARNING, "w", None)
        self.assertEqual(r.severity, SEV_WARNING)


# ===========================================================================
# TestCheckFileExists
# ===========================================================================

class TestCheckFileExists(unittest.TestCase):
    """Tests for check_file_exists."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v = _make_validator(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_existing_file_passes(self):
        _write_file(self.tmp.name, "test.txt", "hello")
        result = self.v.check_file_exists("test.txt")
        self.assertTrue(result.passed)

    def test_missing_file_fails(self):
        result = self.v.check_file_exists("missing.txt")
        self.assertFalse(result.passed)

    def test_missing_file_default_severity_critical(self):
        result = self.v.check_file_exists("missing.txt")
        self.assertEqual(result.severity, SEV_CRITICAL)

    def test_missing_file_custom_severity(self):
        result = self.v.check_file_exists("missing.txt", severity=SEV_WARNING)
        self.assertEqual(result.severity, SEV_WARNING)

    def test_existing_file_severity_info(self):
        _write_file(self.tmp.name, "x.py", "pass")
        result = self.v.check_file_exists("x.py")
        self.assertEqual(result.severity, SEV_INFO)

    def test_file_path_in_result(self):
        result = self.v.check_file_exists("sub/file.py")
        self.assertIn("file.py", result.file_path)

    def test_directory_not_treated_as_file(self):
        # Create a directory with that name — should still fail
        d = Path(self.tmp.name) / "mydir"
        d.mkdir()
        result = self.v.check_file_exists("mydir")
        self.assertFalse(result.passed)


# ===========================================================================
# TestCheckJsonValid
# ===========================================================================

class TestCheckJsonValid(unittest.TestCase):
    """Tests for check_json_valid."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v = _make_validator(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_json_passes(self):
        _write_file(self.tmp.name, "data.json", '{"key": "value"}')
        result = self.v.check_json_valid("data.json")
        self.assertTrue(result.passed)

    def test_empty_object_valid(self):
        _write_file(self.tmp.name, "data.json", "{}")
        result = self.v.check_json_valid("data.json")
        self.assertTrue(result.passed)

    def test_invalid_json_fails(self):
        _write_file(self.tmp.name, "bad.json", "{not valid json}")
        result = self.v.check_json_valid("bad.json")
        self.assertFalse(result.passed)

    def test_invalid_json_severity_warning(self):
        _write_file(self.tmp.name, "bad.json", "<<<invalid>>>")
        result = self.v.check_json_valid("bad.json")
        self.assertEqual(result.severity, SEV_WARNING)

    def test_missing_file_fails(self):
        result = self.v.check_json_valid("nonexistent.json")
        self.assertFalse(result.passed)

    def test_valid_json_severity_info(self):
        _write_file(self.tmp.name, "a.json", "[]")
        result = self.v.check_json_valid("a.json")
        self.assertEqual(result.severity, SEV_INFO)

    def test_json_array_valid(self):
        _write_file(self.tmp.name, "arr.json", '[1, 2, 3]')
        result = self.v.check_json_valid("arr.json")
        self.assertTrue(result.passed)


# ===========================================================================
# TestCheckPythonSyntax
# ===========================================================================

class TestCheckPythonSyntax(unittest.TestCase):
    """Tests for check_python_syntax."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v = _make_validator(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_python_passes(self):
        _write_file(self.tmp.name, "mod.py", "x = 1\nprint(x)\n")
        result = self.v.check_python_syntax("mod.py")
        self.assertTrue(result.passed)

    def test_syntax_error_fails(self):
        _write_file(self.tmp.name, "bad.py", "def broken(\n")
        result = self.v.check_python_syntax("bad.py")
        self.assertFalse(result.passed)

    def test_syntax_error_severity_warning(self):
        _write_file(self.tmp.name, "bad.py", "def f(:\n    pass\n")
        result = self.v.check_python_syntax("bad.py")
        self.assertEqual(result.severity, SEV_WARNING)

    def test_missing_file_fails(self):
        result = self.v.check_python_syntax("missing.py")
        self.assertFalse(result.passed)

    def test_valid_syntax_severity_info(self):
        _write_file(self.tmp.name, "ok.py", "pass\n")
        result = self.v.check_python_syntax("ok.py")
        self.assertEqual(result.severity, SEV_INFO)

    def test_complex_valid_module(self):
        code = textwrap.dedent("""
            from __future__ import annotations
            import json
            from dataclasses import dataclass

            @dataclass
            class Foo:
                x: int

            def bar(y: float) -> str:
                return str(y)
        """)
        _write_file(self.tmp.name, "complex.py", code)
        result = self.v.check_python_syntax("complex.py")
        self.assertTrue(result.passed)

    def test_message_contains_filepath(self):
        _write_file(self.tmp.name, "ok.py", "pass\n")
        result = self.v.check_python_syntax("ok.py")
        self.assertIn("ok.py", result.message)


# ===========================================================================
# TestCheckAnalyticsModule
# ===========================================================================

class TestCheckAnalyticsModule(unittest.TestCase):
    """Tests for check_analytics_module."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v = _make_validator(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_existing_valid_module_passes(self):
        _write_file(
            self.tmp.name,
            "spa_core/analytics/my_module.py",
            "# valid module\nx = 1\n",
        )
        result = self.v.check_analytics_module("my_module")
        self.assertTrue(result.passed)

    def test_missing_module_fails(self):
        result = self.v.check_analytics_module("nonexistent_module")
        self.assertFalse(result.passed)

    def test_missing_module_severity_critical(self):
        result = self.v.check_analytics_module("nonexistent_module")
        self.assertEqual(result.severity, SEV_CRITICAL)

    def test_syntax_error_module_fails(self):
        _write_file(
            self.tmp.name,
            "spa_core/analytics/broken.py",
            "def bad(:\n    pass\n",
        )
        result = self.v.check_analytics_module("broken")
        self.assertFalse(result.passed)

    def test_syntax_error_module_severity_warning(self):
        _write_file(
            self.tmp.name,
            "spa_core/analytics/broken.py",
            "syntax error here @@@@\n",
        )
        result = self.v.check_analytics_module("broken")
        self.assertEqual(result.severity, SEV_WARNING)

    def test_check_name_contains_module_name(self):
        result = self.v.check_analytics_module("my_module")
        self.assertIn("my_module", result.check_name)

    def test_valid_module_severity_info(self):
        _write_file(
            self.tmp.name,
            "spa_core/analytics/good.py",
            "pass\n",
        )
        result = self.v.check_analytics_module("good")
        self.assertEqual(result.severity, SEV_INFO)


# ===========================================================================
# TestRunAllChecks
# ===========================================================================

class TestRunAllChecks(unittest.TestCase):
    """Tests for run_all_checks."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_root_produces_results(self):
        v = _make_validator(self.tmp.name)
        results = v.run_all_checks()
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

    def test_all_files_present_all_pass(self):
        _seed_all(self.tmp.name)
        v = _make_validator(self.tmp.name)
        results = v.run_all_checks()
        failed = [r for r in results if not r.passed]
        self.assertEqual(failed, [], msg=f"Unexpected failures: {[r.message for r in failed]}")

    def test_missing_required_file_produces_critical(self):
        v = _make_validator(self.tmp.name)
        results = v.run_all_checks()
        critical_fails = [r for r in results if not r.passed and r.severity == SEV_CRITICAL]
        self.assertGreater(len(critical_fails), 0)

    def test_result_count_matches_expected(self):
        """Total checks = REQUIRED_FILES (presence) + JSON files + REQUIRED_ANALYTICS."""
        v = _make_validator(self.tmp.name)
        results = v.run_all_checks()
        json_files = [f for f in SystemConfigValidator.REQUIRED_FILES if f.endswith(".json")]
        expected_min = len(SystemConfigValidator.REQUIRED_FILES) + len(json_files) + len(SystemConfigValidator.REQUIRED_ANALYTICS)
        self.assertEqual(len(results), expected_min)

    def test_all_results_are_validation_result(self):
        v = _make_validator(self.tmp.name)
        results = v.run_all_checks()
        for r in results:
            self.assertIsInstance(r, ValidationResult)


# ===========================================================================
# TestGenerateReport
# ===========================================================================

class TestGenerateReport(unittest.TestCase):
    """Tests for generate_report output structure and content."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_report_has_required_keys(self):
        v = _make_validator(self.tmp.name)
        report = v.generate_report()
        for key in ("results", "total_checks", "passed", "failed_critical",
                    "failed_warning", "health_pct", "is_healthy", "advisory",
                    "generated_at"):
            self.assertIn(key, report)

    def test_unhealthy_when_files_missing(self):
        v = _make_validator(self.tmp.name)
        report = v.generate_report()
        self.assertFalse(report["is_healthy"])

    def test_healthy_when_all_present(self):
        _seed_all(self.tmp.name)
        v = _make_validator(self.tmp.name)
        report = v.generate_report()
        self.assertTrue(report["is_healthy"])

    def test_health_pct_between_0_and_100(self):
        v = _make_validator(self.tmp.name)
        report = v.generate_report()
        self.assertGreaterEqual(report["health_pct"], 0.0)
        self.assertLessEqual(report["health_pct"], 100.0)

    def test_health_pct_100_when_all_pass(self):
        _seed_all(self.tmp.name)
        v = _make_validator(self.tmp.name)
        report = v.generate_report()
        self.assertAlmostEqual(report["health_pct"], 100.0, places=1)

    def test_advisory_unhealthy_contains_word(self):
        v = _make_validator(self.tmp.name)
        report = v.generate_report()
        self.assertIn("UNHEALTHY", report["advisory"])

    def test_advisory_healthy_contains_word(self):
        _seed_all(self.tmp.name)
        v = _make_validator(self.tmp.name)
        report = v.generate_report()
        self.assertIn("HEALTHY", report["advisory"])

    def test_report_is_json_serialisable(self):
        v = _make_validator(self.tmp.name)
        report = v.generate_report()
        serialised = json.dumps(report)
        self.assertIn("results", serialised)

    def test_generated_at_is_iso(self):
        v = _make_validator(self.tmp.name)
        report = v.generate_report()
        ts = report["generated_at"]
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_failed_critical_count_nonzero_when_missing(self):
        v = _make_validator(self.tmp.name)
        report = v.generate_report()
        self.assertGreater(report["failed_critical"], 0)


# ===========================================================================
# TestNowIso
# ===========================================================================

class TestNowIso(unittest.TestCase):
    def test_returns_iso_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            v = _make_validator(tmp)
            ts = v._now_iso()
            self.assertIsInstance(ts, str)
            self.assertIn("T", ts)


# ===========================================================================
# Integration / edge-case tests
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_custom_project_root_respected(self):
        """Validator rooted at a custom path should find files there."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "KANBAN.json", '{"hello": 1}')
            v = _make_validator(tmp)
            result = v.check_file_exists("KANBAN.json")
            self.assertTrue(result.passed)

    def test_valid_json_after_seeding(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "data/adapter_status.json", '{"status": "ok"}')
            v = _make_validator(tmp)
            result = v.check_json_valid("data/adapter_status.json")
            self.assertTrue(result.passed)

    def test_invalid_json_message_explains_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "bad.json", "{broken: json}")
            v = _make_validator(tmp)
            result = v.check_json_valid("bad.json")
            self.assertFalse(result.passed)
            self.assertIn("bad.json", result.message)

    def test_partial_seed_partial_pass(self):
        """Seed only some required files — partial pass rate expected."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "KANBAN.json", "{}")
            v = _make_validator(tmp)
            results = v.run_all_checks()
            passed = [r for r in results if r.passed]
            failed = [r for r in results if not r.passed]
            self.assertGreater(len(passed), 0)
            self.assertGreater(len(failed), 0)

    def test_analytics_module_path_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_file(tmp, "spa_core/analytics/foo.py", "x = 1\n")
            v = _make_validator(tmp)
            result = v.check_analytics_module("foo")
            self.assertIn("spa_core/analytics/foo.py", result.file_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
