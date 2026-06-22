"""
tests/test_system_health_check.py — 20 unit tests for scripts/system_health_check.py
MP-1524 (v11.40)
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from io import StringIO
from unittest.mock import patch

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# Load module under test
_SCRIPT = os.path.join(_REPO_ROOT, "scripts", "system_health_check.py")
spec = importlib.util.spec_from_file_location("system_health_check", _SCRIPT)
shc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shc)


def _run_checks_silent(**kwargs) -> dict:
    """Run run_checks() suppressing stdout; return results dict."""
    buf = StringIO()
    with patch("sys.stdout", buf):
        return shc.run_checks(**kwargs)


# ---------------------------------------------------------------------------
# 1. Module structure
# ---------------------------------------------------------------------------

class TestModuleStructure(unittest.TestCase):
    def test_checks_registry_not_empty(self):
        self.assertGreater(len(shc._CHECKS), 0)

    def test_checks_registry_has_tuples(self):
        for name, fn in shc._CHECKS:
            self.assertIsInstance(name, str)
            self.assertTrue(callable(fn))

    def test_run_checks_function_exists(self):
        self.assertTrue(callable(shc.run_checks))

    def test_main_function_exists(self):
        self.assertTrue(callable(shc.main))

    def test_at_least_six_checks(self):
        """Spec requires at least 6 diagnostic checks."""
        self.assertGreaterEqual(len(shc._CHECKS), 6)


# ---------------------------------------------------------------------------
# 2. check() decorator
# ---------------------------------------------------------------------------

class TestCheckDecorator(unittest.TestCase):
    def test_decorator_registers_function(self):
        original_len = len(shc._CHECKS)
        @shc.check("__test_decorator__")
        def _dummy():
            return "ok"
        self.assertEqual(len(shc._CHECKS), original_len + 1)
        # cleanup
        shc._CHECKS[:] = [(n, f) for n, f in shc._CHECKS if n != "__test_decorator__"]

    def test_decorator_preserves_function(self):
        @shc.check("__test_preserve__")
        def _my_fn():
            return "preserved"
        self.assertEqual(_my_fn(), "preserved")
        shc._CHECKS[:] = [(n, f) for n, f in shc._CHECKS if n != "__test_preserve__"]


# ---------------------------------------------------------------------------
# 3. run_checks() result structure
# ---------------------------------------------------------------------------

class TestRunChecksStructure(unittest.TestCase):
    def test_run_checks_returns_dict(self):
        result = _run_checks_silent()
        self.assertIsInstance(result, dict)

    def test_run_checks_has_pass_key(self):
        result = _run_checks_silent()
        self.assertIn("pass", result)

    def test_run_checks_has_fail_key(self):
        result = _run_checks_silent()
        self.assertIn("fail", result)

    def test_run_checks_has_warn_key(self):
        result = _run_checks_silent()
        self.assertIn("warn", result)

    def test_run_checks_has_details_key(self):
        result = _run_checks_silent()
        self.assertIn("details", result)

    def test_run_checks_details_is_list(self):
        result = _run_checks_silent()
        self.assertIsInstance(result["details"], list)


# ---------------------------------------------------------------------------
# 4. Individual check results (integration — against real project)
# ---------------------------------------------------------------------------

class TestRealChecks(unittest.TestCase):
    def test_kanban_check_passes(self):
        """KANBAN integrity check must pass against live KANBAN.json."""
        result = shc.kanban_ok()
        self.assertIn("done_count=", result)
        self.assertGreater(int(result.split("done_count=")[1].split(",")[0]), 0)

    def test_gates_check_passes(self):
        """Gate status check must report PASS for backtest."""
        result = shc.gates_ok()
        self.assertIn("backtest=PASS", result)

    def test_live_gate_locked(self):
        """Live gate must be LOCKED during paper period."""
        result = shc.live_gate_locked()
        self.assertIn("LOCKED", result)

    def test_errors_hierarchy(self):
        """SPAError hierarchy must be intact."""
        result = shc.errors_ok()
        self.assertIn("SPAError", result)

    def test_atomic_ok(self):
        """atomic_save / atomic_load must be importable."""
        result = shc.atomic_ok()
        self.assertIn("atomic_save", result)


# ---------------------------------------------------------------------------
# 5. Pass / Fail / Warn accounting
# ---------------------------------------------------------------------------

class TestResultAccounting(unittest.TestCase):
    def test_all_checks_pass_real_project(self):
        """No FAIL expected in a healthy project (may have WARN)."""
        result = _run_checks_silent()
        self.assertEqual(
            result["fail"], 0,
            msg="Unexpected FAILs:\n" + "\n".join(
                f"  {d['name']}: {d['detail']}"
                for d in result["details"]
                if d["status"] == "FAIL"
            )
        )

    def test_pass_plus_fail_plus_warn_equals_total(self):
        result = _run_checks_silent()
        total = result["pass"] + result["fail"] + result["warn"]
        self.assertEqual(total, len(shc._CHECKS))

    def test_details_length_equals_checks_length(self):
        result = _run_checks_silent()
        self.assertEqual(len(result["details"]), len(shc._CHECKS))

    def test_details_status_values_valid(self):
        result = _run_checks_silent()
        valid = {"PASS", "FAIL", "WARN"}
        for d in result["details"]:
            self.assertIn(d["status"], valid, f"Unknown status in {d}")


# ---------------------------------------------------------------------------
# 6. main() exit code
# ---------------------------------------------------------------------------

class TestMainExitCode(unittest.TestCase):
    def test_main_returns_zero_on_all_pass(self):
        """main() should exit 0 when no FAILs."""
        with patch("sys.argv", ["system_health_check"]):
            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = shc.main()
        self.assertEqual(rc, 0)

    def test_main_returns_one_on_fail(self):
        """If a check fails, main() should return 1."""
        def _failing_check():
            raise AssertionError("forced failure")
        original = list(shc._CHECKS)
        shc._CHECKS.clear()
        shc._CHECKS.append(("__force_fail__", _failing_check))
        try:
            with patch("sys.argv", ["system_health_check"]):
                buf = StringIO()
                with patch("sys.stdout", buf):
                    rc = shc.main()
            self.assertEqual(rc, 1)
        finally:
            shc._CHECKS.clear()
            shc._CHECKS.extend(original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
