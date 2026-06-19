"""
tests/test_launch_runbook.py

MP-1368 (v9.84) — Tests for LaunchRunbook.

Compatible with stdlib unittest:
    python3 -m unittest tests.test_launch_runbook -v
Also compatible with pytest.

Test groups:
  1.  Instantiation (tests 1–3)
  2.  STEPS constant (tests 4–8)
  3.  complete_step() (tests 9–13)
  4.  current_phase() (tests 14–18)
  5.  next_step() (tests 19–22)
  6.  can_proceed_to_launch() (tests 23–25)
  7.  progress() (tests 26–28)
  8.  save() / persistence (tests 29–30)

Total: 30 tests
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.backtesting.launch_runbook import (
    STEPS,
    VALID_PHASES,
    LaunchRunbook,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_rb(tmpdir: str) -> LaunchRunbook:
    """Create a fresh LaunchRunbook rooted in a temp directory."""
    runbook_path = str(Path(tmpdir) / "data" / "live" / "launch_runbook_state.json")
    return LaunchRunbook(runbook_path=runbook_path)


def _all_blocking_step_ids_for_phase(phase: str) -> list:
    return [s[1] for s in STEPS if s[0] == phase and s[3]]


def _complete_all_blocking(rb: LaunchRunbook, phase: str) -> None:
    """Mark all blocking steps for a given phase as completed."""
    for p, sid, _, blocking in STEPS:
        if p == phase and blocking:
            rb.complete_step(sid, notes="test helper")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 1–3: Instantiation
# ═══════════════════════════════════════════════════════════════════════════════

class TestInstantiation(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_01_instantiate_with_default_path(self):
        """LaunchRunbook instantiates without arguments."""
        rb = LaunchRunbook()
        self.assertIsNotNone(rb)

    def test_02_instantiate_with_custom_path(self):
        """LaunchRunbook accepts a custom runbook_path."""
        path = str(Path(self.tmpdir) / "state.json")
        rb = LaunchRunbook(runbook_path=path)
        self.assertIsNotNone(rb)

    def test_03_path_stored_as_path_object(self):
        """LaunchRunbook._path is a pathlib.Path."""
        rb = _make_rb(self.tmpdir)
        self.assertIsInstance(rb._path, Path)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 4–8: STEPS constant
# ═══════════════════════════════════════════════════════════════════════════════

class TestStepsConstant(unittest.TestCase):

    def test_04_steps_is_list(self):
        """STEPS is a list."""
        self.assertIsInstance(STEPS, list)

    def test_05_steps_has_10_entries(self):
        """STEPS contains exactly 10 steps."""
        self.assertEqual(len(STEPS), 10)

    def test_06_each_step_is_4_tuple(self):
        """Each entry in STEPS is a 4-tuple (phase, step_id, description, blocking)."""
        for s in STEPS:
            self.assertEqual(len(s), 4, f"Step {s!r} is not a 4-tuple")

    def test_07_steps_phases_are_valid(self):
        """Every step's phase is one of pre_launch/launch/post_launch."""
        valid = {"pre_launch", "launch", "post_launch"}
        for s in STEPS:
            self.assertIn(s[0], valid, f"Phase {s[0]!r} not in valid phases")

    def test_08_steps_blocking_is_bool(self):
        """Every step's blocking field is a bool."""
        for s in STEPS:
            self.assertIsInstance(s[3], bool, f"Step {s[1]!r} blocking is not bool")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 9–13: complete_step()
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompleteStep(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rb = _make_rb(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_09_complete_step_marks_as_done(self):
        """After complete_step('backup'), 'backup' is in completed_step_ids()."""
        self.rb.complete_step("backup")
        self.assertIn("backup", self.rb.completed_step_ids())

    def test_10_complete_step_stores_notes(self):
        """complete_step() stores the operator notes."""
        self.rb.complete_step("validate", notes="All checks passed")
        self.assertEqual(self.rb.step_notes("validate"), "All checks passed")

    def test_11_complete_step_invalid_id_raises(self):
        """complete_step() raises ValueError for an unknown step_id."""
        with self.assertRaises(ValueError):
            self.rb.complete_step("nonexistent_step")

    def test_12_complete_step_multiple_steps(self):
        """Multiple steps can be completed independently."""
        self.rb.complete_step("backup")
        self.rb.complete_step("validate")
        self.assertIn("backup", self.rb.completed_step_ids())
        self.assertIn("validate", self.rb.completed_step_ids())

    def test_13_step_notes_returns_none_for_incomplete(self):
        """step_notes() returns None for a step that hasn't been completed."""
        result = self.rb.step_notes("backup")
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 14–18: current_phase()
# ═══════════════════════════════════════════════════════════════════════════════

class TestCurrentPhase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rb = _make_rb(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_14_initial_phase_is_pre_launch(self):
        """current_phase() returns 'pre_launch' on a fresh runbook."""
        self.assertEqual(self.rb.current_phase(), "pre_launch")

    def test_15_phase_after_all_pre_launch_blocking_is_launch(self):
        """Completing all blocking pre_launch steps moves phase to 'launch'."""
        _complete_all_blocking(self.rb, "pre_launch")
        self.assertEqual(self.rb.current_phase(), "launch")

    def test_16_phase_after_all_launch_blocking_is_post_launch(self):
        """Completing all blocking launch steps moves phase to 'post_launch'."""
        _complete_all_blocking(self.rb, "pre_launch")
        _complete_all_blocking(self.rb, "launch")
        self.assertEqual(self.rb.current_phase(), "post_launch")

    def test_17_phase_completed_when_all_blocking_done(self):
        """Phase becomes 'completed' when all blocking steps in all phases are done."""
        for phase in ["pre_launch", "launch", "post_launch"]:
            _complete_all_blocking(self.rb, phase)
        self.assertEqual(self.rb.current_phase(), "completed")

    def test_18_phase_returns_string(self):
        """current_phase() always returns a string."""
        self.assertIsInstance(self.rb.current_phase(), str)


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 19–22: next_step()
# ═══════════════════════════════════════════════════════════════════════════════

class TestNextStep(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rb = _make_rb(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_19_next_step_returns_first_uncompleted(self):
        """next_step() returns a dict for the first uncompleted step."""
        nxt = self.rb.next_step()
        self.assertIsNotNone(nxt)
        self.assertIsInstance(nxt, dict)

    def test_20_next_step_has_required_keys(self):
        """next_step() dict has phase, step_id, description, blocking."""
        nxt = self.rb.next_step()
        self.assertIsNotNone(nxt)
        for key in ("phase", "step_id", "description", "blocking"):
            self.assertIn(key, nxt)

    def test_21_next_step_is_first_step_initially(self):
        """Initially, next_step() is the very first STEPS entry."""
        nxt = self.rb.next_step()
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt["step_id"], STEPS[0][1])

    def test_22_next_step_returns_none_when_all_done(self):
        """next_step() returns None when all steps are completed."""
        for _, sid, _, _ in STEPS:
            self.rb.complete_step(sid)
        self.assertIsNone(self.rb.next_step())


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 23–25: can_proceed_to_launch()
# ═══════════════════════════════════════════════════════════════════════════════

class TestCanProceedToLaunch(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rb = _make_rb(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_23_cannot_proceed_initially(self):
        """can_proceed_to_launch() is False on a fresh runbook."""
        self.assertFalse(self.rb.can_proceed_to_launch())

    def test_24_can_proceed_after_blocking_pre_launch_done(self):
        """can_proceed_to_launch() is True after all blocking pre_launch steps done."""
        _complete_all_blocking(self.rb, "pre_launch")
        self.assertTrue(self.rb.can_proceed_to_launch())

    def test_25_cannot_proceed_if_only_advisory_done(self):
        """
        can_proceed_to_launch() remains False if only non-blocking pre_launch
        steps are done (but at least one blocking step exists).
        """
        # Complete only non-blocking pre_launch steps (advisory)
        non_blocking = [
            s[1] for s in STEPS if s[0] == "pre_launch" and not s[3]
        ]
        blocking = [
            s[1] for s in STEPS if s[0] == "pre_launch" and s[3]
        ]
        if non_blocking and blocking:
            for sid in non_blocking:
                self.rb.complete_step(sid)
            # Don't complete blocking ones
            self.assertFalse(self.rb.can_proceed_to_launch())
        else:
            # All pre_launch steps are blocking — trivially skip this test
            self.skipTest("No non-blocking pre_launch steps to test with")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 26–28: progress()
# ═══════════════════════════════════════════════════════════════════════════════

class TestProgress(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rb = _make_rb(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_26_progress_has_required_keys(self):
        """progress() returns a dict with pre_launch, launch, post_launch, overall."""
        prog = self.rb.progress()
        self.assertIsInstance(prog, dict)
        for key in ("pre_launch", "launch", "post_launch", "overall"):
            self.assertIn(key, prog)

    def test_27_progress_phase_has_completed_and_total(self):
        """Each phase entry in progress() has 'completed' and 'total' keys."""
        prog = self.rb.progress()
        for phase in ("pre_launch", "launch", "post_launch", "overall"):
            self.assertIn("completed", prog[phase])
            self.assertIn("total", prog[phase])

    def test_28_progress_overall_total_equals_len_steps(self):
        """progress()['overall']['total'] == len(STEPS)."""
        prog = self.rb.progress()
        self.assertEqual(prog["overall"]["total"], len(STEPS))


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 29–30: save() / persistence
# ═══════════════════════════════════════════════════════════════════════════════

class TestSave(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_29_save_creates_file(self):
        """save() creates the runbook state JSON file."""
        rb = _make_rb(self.tmpdir)
        rb.complete_step("backup", notes="test")
        rb.save()
        self.assertTrue(rb._path.exists())

    def test_30_saved_state_is_valid_json_and_persists(self):
        """State saved by save() can be reloaded by a new LaunchRunbook instance."""
        path = str(Path(self.tmpdir) / "data" / "live" / "launch_runbook_state.json")
        rb1 = LaunchRunbook(runbook_path=path)
        rb1.complete_step("backup", notes="saved note")
        rb1.save()

        rb2 = LaunchRunbook(runbook_path=path)
        self.assertIn("backup", rb2.completed_step_ids())
        self.assertEqual(rb2.step_notes("backup"), "saved note")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
