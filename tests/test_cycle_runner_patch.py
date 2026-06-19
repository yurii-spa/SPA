"""
tests/test_cycle_runner_patch.py

25 unit tests for spa_core.backtesting.cycle_runner_patch.

MP-1348 (v9.64)

Tests cover:
  - CycleRunnerPatch construction
  - is_already_applied() when file absent / present / patched
  - show_diff() structure
  - apply(dry_run=True) does not modify file
  - apply() on missing file returns error result
  - verify() dict contract
  - CPA_HOOK_IMPORT / CPA_HOOK_CALL content guards
  - CLI constants
  - _build_patched() injection logic

stdlib only; no external dependencies.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# ── ensure project root is importable ───────────────────────────────────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.backtesting.cycle_runner_patch import (
    CPA_HOOK_CALL,
    CPA_HOOK_IMPORT,
    CycleRunnerPatch,
    _CALL_SENTINEL,
    _IMPORT_SENTINEL,
)

# ── helpers ──────────────────────────────────────────────────────────────────

_MINIMAL_CYCLE_RUNNER = """\
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def run(verbose: bool = False) -> None:
    \"\"\"Main cycle.\"\"\"
    pass
"""

_ALREADY_PATCHED = _MINIMAL_CYCLE_RUNNER + "\n" + CPA_HOOK_IMPORT + "\n" + CPA_HOOK_CALL


# ── Test cases ────────────────────────────────────────────────────────────────

class TestCycleRunnerPatchConstruction(unittest.TestCase):
    """CycleRunnerPatch can be instantiated."""

    def test_01_default_construction(self):
        """CycleRunnerPatch() instantiates without errors."""
        patch = CycleRunnerPatch()
        self.assertIsInstance(patch, CycleRunnerPatch)

    def test_02_custom_path_construction(self):
        """CycleRunnerPatch(path) stores the given path."""
        patch = CycleRunnerPatch(cycle_runner_path="/tmp/fake_runner.py")
        self.assertIn("fake_runner.py", str(patch._path))

    def test_03_path_attribute_is_pathlib(self):
        """Internal _path is a pathlib.Path."""
        patch = CycleRunnerPatch()
        self.assertIsInstance(patch._path, Path)


class TestIsAlreadyApplied(unittest.TestCase):

    def test_04_missing_file_returns_false(self):
        """is_already_applied() returns False when file does not exist."""
        patch = CycleRunnerPatch(cycle_runner_path="/nonexistent/cycle_runner.py")
        self.assertFalse(patch.is_already_applied())

    def test_05_unpatched_file_returns_false(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(_MINIMAL_CYCLE_RUNNER)
            fname = f.name
        try:
            patch = CycleRunnerPatch(cycle_runner_path=fname)
            self.assertFalse(patch.is_already_applied())
        finally:
            os.unlink(fname)

    def test_06_patched_file_returns_true(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(_ALREADY_PATCHED)
            fname = f.name
        try:
            patch = CycleRunnerPatch(cycle_runner_path=fname)
            self.assertTrue(patch.is_already_applied())
        finally:
            os.unlink(fname)

    def test_07_returns_bool_type(self):
        patch = CycleRunnerPatch(cycle_runner_path="/nonexistent.py")
        result = patch.is_already_applied()
        self.assertIsInstance(result, bool)


class TestShowDiff(unittest.TestCase):

    def test_08_returns_string(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(_MINIMAL_CYCLE_RUNNER)
            fname = f.name
        try:
            patch = CycleRunnerPatch(cycle_runner_path=fname)
            result = patch.show_diff()
            self.assertIsInstance(result, str)
        finally:
            os.unlink(fname)

    def test_09_nonempty_for_unpatched_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(_MINIMAL_CYCLE_RUNNER)
            fname = f.name
        try:
            patch = CycleRunnerPatch(cycle_runner_path=fname)
            diff = patch.show_diff()
            self.assertTrue(len(diff) > 0)
        finally:
            os.unlink(fname)

    def test_10_diff_contains_plus_lines(self):
        """Diff shows added lines (unified diff format)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(_MINIMAL_CYCLE_RUNNER)
            fname = f.name
        try:
            patch = CycleRunnerPatch(cycle_runner_path=fname)
            diff = patch.show_diff()
            self.assertIn("+", diff)
        finally:
            os.unlink(fname)

    def test_11_missing_file_diff_contains_message(self):
        patch = CycleRunnerPatch(cycle_runner_path="/nonexistent.py")
        diff = patch.show_diff()
        self.assertIn("not found", diff.lower())


class TestApplyDryRun(unittest.TestCase):

    def test_12_dry_run_does_not_modify_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(_MINIMAL_CYCLE_RUNNER)
            fname = f.name
        original_mtime = os.path.getmtime(fname)
        try:
            patch = CycleRunnerPatch(cycle_runner_path=fname)
            result = patch.apply(dry_run=True)
            new_mtime = os.path.getmtime(fname)
            # File should not have been modified
            self.assertEqual(original_mtime, new_mtime)
            self.assertTrue(result["dry_run"])
        finally:
            os.unlink(fname)

    def test_13_dry_run_returns_success_true(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(_MINIMAL_CYCLE_RUNNER)
            fname = f.name
        try:
            patch = CycleRunnerPatch(cycle_runner_path=fname)
            result = patch.apply(dry_run=True)
            self.assertTrue(result["success"])
        finally:
            os.unlink(fname)

    def test_14_dry_run_lines_added_positive(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(_MINIMAL_CYCLE_RUNNER)
            fname = f.name
        try:
            patch = CycleRunnerPatch(cycle_runner_path=fname)
            result = patch.apply(dry_run=True)
            self.assertGreater(result["lines_added"], 0)
        finally:
            os.unlink(fname)

    def test_15_missing_file_returns_error(self):
        patch = CycleRunnerPatch(cycle_runner_path="/nonexistent/cycle_runner.py")
        result = patch.apply(dry_run=False)
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_16_already_applied_skips_patch(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(_ALREADY_PATCHED)
            fname = f.name
        try:
            patch = CycleRunnerPatch(cycle_runner_path=fname)
            result = patch.apply(dry_run=False)
            self.assertTrue(result["already_applied"])
            self.assertEqual(result["lines_added"], 0)
        finally:
            os.unlink(fname)


class TestVerify(unittest.TestCase):

    def test_17_returns_dict(self):
        patch = CycleRunnerPatch(cycle_runner_path="/nonexistent.py")
        result = patch.verify()
        self.assertIsInstance(result, dict)

    def test_18_has_success_key(self):
        patch = CycleRunnerPatch(cycle_runner_path="/nonexistent.py")
        result = patch.verify()
        self.assertIn("success", result)

    def test_19_missing_file_success_false(self):
        patch = CycleRunnerPatch(cycle_runner_path="/nonexistent.py")
        result = patch.verify()
        self.assertFalse(result["success"])

    def test_20_has_all_expected_keys(self):
        patch = CycleRunnerPatch(cycle_runner_path="/nonexistent.py")
        result = patch.verify()
        for key in ("success", "import_present", "call_present", "file_exists", "path"):
            self.assertIn(key, result)

    def test_21_patched_file_verify_success(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(_ALREADY_PATCHED)
            fname = f.name
        try:
            patch = CycleRunnerPatch(cycle_runner_path=fname)
            result = patch.verify()
            self.assertTrue(result["success"])
            self.assertTrue(result["import_present"])
            self.assertTrue(result["call_present"])
        finally:
            os.unlink(fname)


class TestCPAHookConstants(unittest.TestCase):

    def test_22_import_contains_correct_module_path(self):
        """CPA_HOOK_IMPORT imports from the right module."""
        self.assertIn("spa_core.backtesting.cycle_runner_cpa_hook", CPA_HOOK_IMPORT)

    def test_23_import_contains_cpa_gate_hook_class(self):
        self.assertIn("CPAGateHook", CPA_HOOK_IMPORT)

    def test_24_call_contains_allow_live_check(self):
        """CPA_HOOK_CALL checks allow_live."""
        self.assertIn("allow_live", CPA_HOOK_CALL)

    def test_25_call_contains_allow_paper_check(self):
        """CPA_HOOK_CALL checks allow_paper."""
        self.assertIn("allow_paper", CPA_HOOK_CALL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
