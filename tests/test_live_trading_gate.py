"""
tests/test_live_trading_gate.py

40 tests for spa_core/safety/live_trading_gate.py

Coverage:
  - LiveTradingGate() default LOCKED state
  - is_active() False at start
  - require_live_gate() → LiveTradingForbiddenError when LOCKED
  - get_prerequisites() → all_met=False at start
  - activate() without prerequisites → returns False, stays LOCKED
  - activate() with all prerequisites → returns True, gate ACTIVE
  - deactivate() → gate LOCKED again
  - status_report() contains "BLOCKED"/"ACTIVE"
  - Module-level require_live_gate() wrapper
  - Atomic save/load round-trip
  - Gate state persists between instances (file-based)

MP-1401 (v10.17) — stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest

from spa_core.safety.live_trading_gate import LiveTradingGate, _is_valid_sha256
from spa_core.utils.errors import LiveTradingForbiddenError


def _valid_sha256() -> str:
    """Return a syntactically valid 64-char SHA256 hex string."""
    return hashlib.sha256(b"owner-acceptance-doc-content").hexdigest()


def _make_gate(tmp_dir: str, **prereq_overrides) -> LiveTradingGate:
    """Create a LiveTradingGate rooted at *tmp_dir* with optional prereq overrides."""
    gate = LiveTradingGate(base_dir=tmp_dir)
    if prereq_overrides:
        # Poke state file directly to set prerequisites
        state = gate._load()
        state.update(prereq_overrides)
        gate._state = state
        gate._save()
        gate._state = None  # force reload
    return gate


def _make_gate_all_prereqs(tmp_dir: str) -> LiveTradingGate:
    """Gate with all three prerequisites set to True."""
    return _make_gate(
        tmp_dir,
        owner_acceptance=True,
        paper_trading_complete=True,
        pre_launch_validation=True,
    )


class TestLiveTradingGateDefaults(unittest.TestCase):
    """Gate starts in LOCKED state with all prerequisites False."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    # 1
    def test_gate_default_locked(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        self.assertFalse(gate.is_active())

    # 2
    def test_is_active_false_initially(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        result = gate.is_active()
        self.assertIs(result, False)

    # 3
    def test_require_live_gate_raises_when_locked(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        with self.assertRaises(LiveTradingForbiddenError):
            gate.require_live_gate()

    # 4
    def test_require_live_gate_error_code(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        try:
            gate.require_live_gate()
            self.fail("Expected LiveTradingForbiddenError")
        except LiveTradingForbiddenError as exc:
            self.assertEqual(exc.code, "LIVE_TRADING_FORBIDDEN")

    # 5
    def test_get_prerequisites_all_false_initially(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        prereqs = gate.get_prerequisites()
        self.assertFalse(prereqs["all_met"])

    # 6
    def test_get_prerequisites_owner_acceptance_false(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        self.assertFalse(gate.get_prerequisites()["owner_acceptance"])

    # 7
    def test_get_prerequisites_paper_trading_false(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        self.assertFalse(gate.get_prerequisites()["paper_trading_complete"])

    # 8
    def test_get_prerequisites_pre_launch_false(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        self.assertFalse(gate.get_prerequisites()["pre_launch_validation"])

    # 9
    def test_get_prerequisites_manually_activated_false(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        self.assertFalse(gate.get_prerequisites()["manually_activated"])

    # 10
    def test_get_prerequisites_returns_dict(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        result = gate.get_prerequisites()
        self.assertIsInstance(result, dict)

    # 11
    def test_get_prerequisites_all_keys_present(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        keys = gate.get_prerequisites().keys()
        expected = {"owner_acceptance", "paper_trading_complete",
                    "pre_launch_validation", "manually_activated", "all_met"}
        self.assertEqual(set(keys), expected)


class TestActivateWithoutPrerequisites(unittest.TestCase):
    """activate() must fail (return False) when prerequisites are not met."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    # 12
    def test_activate_without_prerequisites_returns_false(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        result = gate.activate(_valid_sha256(), "test")
        self.assertFalse(result)

    # 13
    def test_activate_without_prerequisites_stays_locked(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        gate.activate(_valid_sha256(), "test")
        self.assertFalse(gate.is_active())

    # 14
    def test_activate_invalid_key_returns_false(self):
        gate = _make_gate_all_prereqs(self.tmp)
        self.assertFalse(gate.activate("not-a-sha256", "test"))

    # 15
    def test_activate_short_key_returns_false(self):
        gate = _make_gate_all_prereqs(self.tmp)
        self.assertFalse(gate.activate("abc123", "test"))

    # 16
    def test_activate_returns_false_missing_owner_acceptance(self):
        gate = _make_gate(
            self.tmp,
            paper_trading_complete=True,
            pre_launch_validation=True,
        )
        self.assertFalse(gate.activate(_valid_sha256(), "test"))

    # 17
    def test_activate_returns_false_missing_paper_trading(self):
        gate = _make_gate(
            self.tmp,
            owner_acceptance=True,
            pre_launch_validation=True,
        )
        self.assertFalse(gate.activate(_valid_sha256(), "test"))

    # 18
    def test_activate_returns_false_missing_pre_launch(self):
        gate = _make_gate(
            self.tmp,
            owner_acceptance=True,
            paper_trading_complete=True,
        )
        self.assertFalse(gate.activate(_valid_sha256(), "test"))


class TestActivateWithPrerequisites(unittest.TestCase):
    """activate() succeeds when all prerequisites are met."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    # 19
    def test_activate_with_prerequisites_met_returns_true(self):
        gate = _make_gate_all_prereqs(self.tmp)
        result = gate.activate(_valid_sha256(), "Go-live test")
        self.assertTrue(result)

    # 20
    def test_activate_sets_is_active_true(self):
        gate = _make_gate_all_prereqs(self.tmp)
        gate.activate(_valid_sha256(), "Go-live test")
        self.assertTrue(gate.is_active())

    # 21
    def test_activate_persists_state(self):
        gate = _make_gate_all_prereqs(self.tmp)
        gate.activate(_valid_sha256(), "Go-live test")
        # Create fresh instance — should load from file
        gate2 = LiveTradingGate(base_dir=self.tmp)
        self.assertTrue(gate2.is_active())

    # 22
    def test_require_live_gate_no_raise_when_active(self):
        gate = _make_gate_all_prereqs(self.tmp)
        gate.activate(_valid_sha256(), "Go-live test")
        # Should NOT raise
        gate.require_live_gate()

    # 23
    def test_activate_logs_reason(self):
        gate = _make_gate_all_prereqs(self.tmp)
        gate.activate(_valid_sha256(), "My activation reason")
        state = gate._load()
        self.assertEqual(state["activated_reason"], "My activation reason")

    # 24
    def test_activate_get_prerequisites_all_met(self):
        gate = _make_gate_all_prereqs(self.tmp)
        gate.activate(_valid_sha256(), "test")
        prereqs = gate.get_prerequisites()
        self.assertTrue(prereqs["all_met"])
        self.assertTrue(prereqs["manually_activated"])


class TestDeactivate(unittest.TestCase):
    """deactivate() locks the gate, persisting reason."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    # 25
    def test_deactivate_locks_gate(self):
        gate = _make_gate_all_prereqs(self.tmp)
        gate.activate(_valid_sha256(), "test")
        gate.deactivate("emergency stop")
        self.assertFalse(gate.is_active())

    # 26
    def test_deactivate_after_activate_raises_on_require(self):
        gate = _make_gate_all_prereqs(self.tmp)
        gate.activate(_valid_sha256(), "test")
        gate.deactivate("emergency stop")
        with self.assertRaises(LiveTradingForbiddenError):
            gate.require_live_gate()

    # 27
    def test_deactivate_already_locked_no_error(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        # Must not raise
        gate.deactivate("precautionary")
        self.assertFalse(gate.is_active())

    # 28
    def test_deactivate_logs_reason(self):
        gate = _make_gate_all_prereqs(self.tmp)
        gate.activate(_valid_sha256(), "test")
        gate.deactivate("risk limit breached")
        state = gate._load()
        self.assertEqual(state["deactivated_reason"], "risk limit breached")

    # 29
    def test_deactivate_state_file_updated(self):
        gate = _make_gate_all_prereqs(self.tmp)
        gate.activate(_valid_sha256(), "test")
        gate.deactivate("test deactivation")
        gate_path = os.path.join(self.tmp, "data", "live_trading_gate.json")
        with open(gate_path) as fh:
            data = json.load(fh)
        self.assertFalse(data["active"])
        self.assertEqual(data["deactivated_reason"], "test deactivation")


class TestStatusReport(unittest.TestCase):
    """status_report() returns a human-readable string."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    # 30
    def test_status_report_is_string(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        self.assertIsInstance(gate.status_report(), str)

    # 31
    def test_status_report_contains_blocked_when_locked(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        report = gate.status_report()
        self.assertIn("BLOCKED", report)

    # 32
    def test_status_report_contains_active_when_active(self):
        gate = _make_gate_all_prereqs(self.tmp)
        gate.activate(_valid_sha256(), "test")
        report = gate.status_report()
        self.assertIn("ACTIVE", report)

    # 33
    def test_status_report_not_blocked_when_active(self):
        gate = _make_gate_all_prereqs(self.tmp)
        gate.activate(_valid_sha256(), "test")
        report = gate.status_report()
        self.assertNotIn("BLOCKED", report)


class TestPersistenceAndAtomicity(unittest.TestCase):
    """State file is created, round-trips correctly, and persists across instances."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    # 34
    def test_gate_file_created_on_load(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        gate._load()
        gate_path = os.path.join(self.tmp, "data", "live_trading_gate.json")
        self.assertTrue(os.path.exists(gate_path))

    # 35
    def test_atomic_save_load_round_trip(self):
        gate = _make_gate_all_prereqs(self.tmp)
        gate.activate(_valid_sha256(), "round-trip test")
        # New instance loads the file
        gate2 = LiveTradingGate(base_dir=self.tmp)
        self.assertTrue(gate2.is_active())
        state = gate2._load()
        self.assertEqual(state["activated_reason"], "round-trip test")

    # 36
    def test_gate_state_persists_between_instances(self):
        gate = _make_gate_all_prereqs(self.tmp)
        gate.activate(_valid_sha256(), "persist test")
        # Destroy instance, create new one
        del gate
        gate2 = LiveTradingGate(base_dir=self.tmp)
        self.assertTrue(gate2.is_active())

    # 37
    def test_gate_missing_file_defaults_locked(self):
        gate = LiveTradingGate(base_dir=self.tmp)
        # File doesn't exist yet — should still be LOCKED
        self.assertFalse(gate.is_active())

    # 38
    def test_gate_corrupt_file_defaults_locked(self):
        gate_path = os.path.join(self.tmp, "data", "live_trading_gate.json")
        os.makedirs(os.path.dirname(gate_path), exist_ok=True)
        with open(gate_path, "w") as fh:
            fh.write("{{not valid JSON}}")
        gate = LiveTradingGate(base_dir=self.tmp)
        self.assertFalse(gate.is_active())

    # 39
    def test_gate_with_custom_base_dir(self):
        custom_dir = os.path.join(self.tmp, "custom")
        os.makedirs(custom_dir, exist_ok=True)
        gate = LiveTradingGate(base_dir=custom_dir)
        self.assertFalse(gate.is_active())
        gate_path = os.path.join(custom_dir, "data", "live_trading_gate.json")
        # After loading, file should exist
        gate._load()
        self.assertTrue(os.path.exists(gate_path))


class TestModuleLevelWrapper(unittest.TestCase):
    """Module-level require_live_gate() convenience function."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    # 40
    def test_module_level_require_live_gate_raises(self):
        """The module-level wrapper must raise LiveTradingForbiddenError."""
        import spa_core.safety.live_trading_gate as mod
        # Reset singleton for isolation
        original_gate = mod._gate
        mod._gate = LiveTradingGate(base_dir=self.tmp)
        try:
            with self.assertRaises(LiveTradingForbiddenError):
                mod.require_live_gate(base_dir=self.tmp)
        finally:
            mod._gate = original_gate


class TestIsValidSha256(unittest.TestCase):
    """Internal helper _is_valid_sha256."""

    def test_valid_sha256(self):
        self.assertTrue(_is_valid_sha256(_valid_sha256()))

    def test_short_string_invalid(self):
        self.assertFalse(_is_valid_sha256("abc"))

    def test_non_hex_invalid(self):
        self.assertFalse(_is_valid_sha256("x" * 64))

    def test_none_invalid(self):
        self.assertFalse(_is_valid_sha256(None))  # type: ignore

    def test_64_zeros_valid(self):
        self.assertTrue(_is_valid_sha256("0" * 64))


if __name__ == "__main__":
    unittest.main(verbosity=2)
