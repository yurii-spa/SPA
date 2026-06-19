"""
tests/test_paper_trading_kickoff.py

MP-1355 (v9.71) — 40 unit tests for PaperTradingKickoff.

Compatible with stdlib unittest:
    python3 -m unittest tests/test_paper_trading_kickoff.py -v

Also compatible with pytest.

Test sections:
  1.  Instantiation                                      (3 tests)
  2.  check_prerequisites() — return type & structure    (5 tests)
  3.  can_kickoff()                                      (5 tests)
  4.  kickoff(dry_run=True)                              (6 tests)
  5.  kickoff(dry_run=False) — file creation             (6 tests)
  6.  KickoffResult fields                               (5 tests)
  7.  waive_acceptance behaviour                         (5 tests)
  8.  status()                                           (5 tests)

Total: 40 tests
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# ── repo root import ──────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.backtesting.paper_trading_kickoff import (
    PaperTradingKickoff,
    PrerequisiteCheck,
    KickoffResult,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

_PRE_PAPER_PASS = {
    "schema_version": "0.1",
    "generated_at": "2026-06-19",
    "status": "PASS",
    "paper_test_can_be_designed": True,
    "paper_trading_allowed": False,
    "strict_blockers": [],
}

_PAPER_READY_PASS = {
    "schema_version": "0.1",
    "status": "READY",
    "paper_trading_allowed": True,
    "generated_at": "2026-06-19",
    "blockers": [],
}

_PAPER_READY_BLOCKED = {
    "schema_version": "0.1",
    "status": "NOT_READY",
    "paper_trading_allowed": False,
    "generated_at": "2026-06-19",
    "blockers": ["Hardening audit not PASS.", "Owner acceptance not signed."],
}

_OWNER_ACCEPTED = {
    "accepted": True,
    "owner": "yurii",
    "accepted_at": "2026-06-19T12:00:00Z",
}

_OWNER_NOT_SIGNED = {
    "accepted": False,
    "owner": None,
    "accepted_at": None,
}

_KILL_SWITCH_OFF = {
    "generated_at": "2026-06-19T06:00:00Z",
    "triggered": False,
    "reason": "all triggers clear",
}

_KILL_SWITCH_ON = {
    "generated_at": "2026-06-19T06:00:00Z",
    "triggered": True,
    "reason": "portfolio drawdown >= 5%",
}


def _make_env(
    tmp: Path,
    *,
    pre_paper: dict | None = _PRE_PAPER_PASS,
    paper_ready: dict | None = _PAPER_READY_PASS,
    owner: dict | None = _OWNER_ACCEPTED,
    kill: dict | None = _KILL_SWITCH_OFF,
    cpa_doc: bool = True,
    waive_acceptance: bool = False,
) -> PaperTradingKickoff:
    """Build a temp-dir environment and return a configured PaperTradingKickoff."""
    (tmp / "data" / "backtest").mkdir(parents=True, exist_ok=True)
    (tmp / "data" / "paper").mkdir(parents=True, exist_ok=True)
    (tmp / "docs").mkdir(parents=True, exist_ok=True)

    def _write(rel: str, obj: dict) -> None:
        (tmp / rel).write_text(json.dumps(obj), encoding="utf-8")

    if pre_paper is not None:
        _write("data/backtest/pre_paper_backtest_gate.json", pre_paper)
    if paper_ready is not None:
        _write("data/backtest/paper_ready_gate.json", paper_ready)
    if owner is not None:
        _write("data/backtest/owner_paper_acceptance.json", owner)
    if kill is not None:
        _write("data/kill_switch_status.json", kill)
    if cpa_doc:
        (tmp / "docs" / "CPA_INTEGRATION_STATUS.md").write_text("# CPA", encoding="utf-8")

    return PaperTradingKickoff(base_dir=str(tmp), waive_acceptance=waive_acceptance)


# ── Test Cases ────────────────────────────────────────────────────────────────

class TestInstantiation(unittest.TestCase):
    """Section 1 — Instantiation (3 tests)"""

    def test_default_instantiation(self):
        """PaperTradingKickoff() can be created with no arguments."""
        k = PaperTradingKickoff()
        self.assertIsInstance(k, PaperTradingKickoff)

    def test_base_dir_stored(self):
        """base_dir is stored on the instance."""
        k = PaperTradingKickoff(base_dir="/tmp")
        self.assertEqual(str(k.base_dir), "/tmp")

    def test_waive_acceptance_flag(self):
        """waive_acceptance flag is stored correctly."""
        k = PaperTradingKickoff(waive_acceptance=True)
        self.assertTrue(k.waive_acceptance)
        k2 = PaperTradingKickoff(waive_acceptance=False)
        self.assertFalse(k2.waive_acceptance)


class TestCheckPrerequisites(unittest.TestCase):
    """Section 2 — check_prerequisites() return type & structure (5 tests)"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.base = Path(self.tmp)

    def test_returns_list(self):
        """check_prerequisites() returns a list."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            result = k.check_prerequisites()
            self.assertIsInstance(result, list)

    def test_returns_prerequisitecheck_objects(self):
        """Each item in the list is a PrerequisiteCheck."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            for item in k.check_prerequisites():
                self.assertIsInstance(item, PrerequisiteCheck)

    def test_exactly_five_checks(self):
        """There are exactly 5 prerequisite checks."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            self.assertEqual(len(k.check_prerequisites()), 5)

    def test_check_names_unique(self):
        """All check names are unique."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            names = [c.name for c in k.check_prerequisites()]
            self.assertEqual(len(names), len(set(names)))

    def test_all_pass_in_happy_path(self):
        """All required checks pass when every file is present and valid."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            checks = k.check_prerequisites()
            required_failed = [c for c in checks if c.required and not c.passed]
            self.assertEqual(required_failed, [])


class TestCanKickoff(unittest.TestCase):
    """Section 3 — can_kickoff() (5 tests)"""

    def test_true_when_all_pass(self):
        """can_kickoff() returns True when all required prerequisites pass."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            self.assertTrue(k.can_kickoff())

    def test_false_when_backtest_gate_missing(self):
        """can_kickoff() returns False when backtest gate file is missing."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp), pre_paper=None)
            self.assertFalse(k.can_kickoff())

    def test_false_when_paper_ready_blocked(self):
        """can_kickoff() returns False when paper_ready_gate is NOT_READY."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp), paper_ready=_PAPER_READY_BLOCKED)
            self.assertFalse(k.can_kickoff())

    def test_false_when_cpa_doc_missing(self):
        """can_kickoff() returns False when CPA doc is absent."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp), cpa_doc=False)
            self.assertFalse(k.can_kickoff())

    def test_returns_bool(self):
        """can_kickoff() always returns a bool."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            result = k.can_kickoff()
            self.assertIsInstance(result, bool)


class TestKickoffDryRun(unittest.TestCase):
    """Section 4 — kickoff(dry_run=True) (6 tests)"""

    def test_dry_run_returns_kickoff_result(self):
        """kickoff(dry_run=True) returns KickoffResult."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            result = k.kickoff(dry_run=True)
            self.assertIsInstance(result, KickoffResult)

    def test_dry_run_success_true_when_valid(self):
        """dry_run result.success is True when all prerequisites pass."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            result = k.kickoff(dry_run=True)
            self.assertTrue(result.success)

    def test_dry_run_does_not_create_paper_state(self):
        """dry_run=True must NOT create data/paper/paper_state.json."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            k.kickoff(dry_run=True)
            state_file = Path(tmp) / "data" / "paper" / "paper_state.json"
            self.assertFalse(state_file.exists())

    def test_dry_run_does_not_create_receipt(self):
        """dry_run=True must NOT create kickoff_receipt.json."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            k.kickoff(dry_run=True)
            receipt_file = Path(tmp) / "data" / "paper" / "kickoff_receipt.json"
            self.assertFalse(receipt_file.exists())

    def test_dry_run_receipt_path_is_none(self):
        """dry_run result.receipt_path is None."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            result = k.kickoff(dry_run=True)
            self.assertIsNone(result.receipt_path)

    def test_dry_run_blocked_when_prerequisites_fail(self):
        """dry_run result.success is False when prerequisites fail."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp), pre_paper=None)
            result = k.kickoff(dry_run=True)
            self.assertFalse(result.success)


class TestKickoffReal(unittest.TestCase):
    """Section 5 — kickoff(dry_run=False) file creation (6 tests)"""

    def test_creates_paper_state(self):
        """kickoff() creates data/paper/paper_state.json."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            k.kickoff(dry_run=False)
            state_file = Path(tmp) / "data" / "paper" / "paper_state.json"
            self.assertTrue(state_file.exists())

    def test_paper_state_valid_json(self):
        """data/paper/paper_state.json is valid JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            k.kickoff(dry_run=False)
            state_file = Path(tmp) / "data" / "paper" / "paper_state.json"
            data = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertIn("start_date", data)
            self.assertIn("day", data)

    def test_paper_state_day_is_zero(self):
        """paper_state.json day field starts at 0."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            k.kickoff(dry_run=False)
            state_file = Path(tmp) / "data" / "paper" / "paper_state.json"
            data = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(data["day"], 0)

    def test_creates_receipt(self):
        """kickoff() creates data/paper/kickoff_receipt.json."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            k.kickoff(dry_run=False)
            receipt_file = Path(tmp) / "data" / "paper" / "kickoff_receipt.json"
            self.assertTrue(receipt_file.exists())

    def test_receipt_path_in_result(self):
        """result.receipt_path points to existing file after kickoff."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            result = k.kickoff(dry_run=False)
            self.assertIsNotNone(result.receipt_path)
            self.assertTrue(Path(result.receipt_path).exists())

    def test_no_files_when_prerequisites_fail(self):
        """kickoff() creates NO files when prerequisites fail."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp), pre_paper=None)
            k.kickoff(dry_run=False)
            state_file = Path(tmp) / "data" / "paper" / "paper_state.json"
            receipt_file = Path(tmp) / "data" / "paper" / "kickoff_receipt.json"
            self.assertFalse(state_file.exists())
            self.assertFalse(receipt_file.exists())


class TestKickoffResult(unittest.TestCase):
    """Section 6 — KickoffResult fields (5 tests)"""

    def test_success_true_all_required_pass(self):
        """KickoffResult.success=True when all required checks pass."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            result = k.kickoff(dry_run=True)
            self.assertTrue(result.success)

    def test_success_false_when_blocked(self):
        """KickoffResult.success=False when a required check fails."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp), paper_ready=_PAPER_READY_BLOCKED)
            result = k.kickoff(dry_run=True)
            self.assertFalse(result.success)

    def test_blocking_issues_empty_when_all_pass(self):
        """blocking_issues is empty when all required prerequisites pass."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            result = k.kickoff(dry_run=True)
            self.assertEqual(result.blocking_issues, [])

    def test_blocking_issues_populated_when_fail(self):
        """blocking_issues contains entries for failed required checks."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp), cpa_doc=False)
            result = k.kickoff(dry_run=True)
            self.assertGreater(len(result.blocking_issues), 0)

    def test_prerequisites_list_in_result(self):
        """KickoffResult.prerequisites contains PrerequisiteCheck objects."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            result = k.kickoff(dry_run=True)
            self.assertIsInstance(result.prerequisites, list)
            self.assertGreater(len(result.prerequisites), 0)
            self.assertIsInstance(result.prerequisites[0], PrerequisiteCheck)


class TestWaiveAcceptance(unittest.TestCase):
    """Section 7 — waive_acceptance behaviour (5 tests)"""

    def test_waive_true_allows_kickoff_without_acceptance(self):
        """waive_acceptance=True: kickoff succeeds even without owner acceptance file."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp), owner=None, waive_acceptance=True)
            # Need also kill switch and CPA doc to be present; acceptance is missing
            # but waived → should succeed
            result = k.kickoff(dry_run=True)
            self.assertTrue(result.success)

    def test_waive_false_blocks_when_acceptance_missing(self):
        """waive_acceptance=False: kickoff blocked when owner_paper_acceptance.json is absent."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp), owner=None, waive_acceptance=False)
            result = k.kickoff(dry_run=True)
            self.assertFalse(result.success)

    def test_waive_false_blocks_when_not_signed(self):
        """waive_acceptance=False: kickoff blocked when acceptance file says accepted=False."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp), owner=_OWNER_NOT_SIGNED, waive_acceptance=False)
            result = k.kickoff(dry_run=True)
            self.assertFalse(result.success)

    def test_waive_true_acceptance_is_non_required(self):
        """With waive_acceptance=True, owner_acceptance check has required=False."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp), owner=None)
            k.waive_acceptance = True
            checks = k.check_prerequisites()
            owner_check = next(c for c in checks if c.name == "owner_acceptance")
            self.assertFalse(owner_check.required)

    def test_waive_false_acceptance_is_required(self):
        """With waive_acceptance=False, owner_acceptance check has required=True."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            k.waive_acceptance = False
            checks = k.check_prerequisites()
            owner_check = next(c for c in checks if c.name == "owner_acceptance")
            self.assertTrue(owner_check.required)


class TestStatus(unittest.TestCase):
    """Section 8 — status() (5 tests)"""

    def test_not_started_when_no_state_file(self):
        """status() returns 'not_started' when paper_state.json does not exist."""
        with tempfile.TemporaryDirectory() as tmp:
            k = PaperTradingKickoff(base_dir=str(tmp))
            result = k.status()
            self.assertEqual(result["status"], "not_started")

    def test_running_after_kickoff(self):
        """status() returns 'running' after a successful kickoff."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            k.kickoff(dry_run=False)
            result = k.status()
            self.assertEqual(result["status"], "running")

    def test_status_contains_start_date(self):
        """status() dict contains start_date after kickoff."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp))
            k.kickoff(dry_run=False)
            result = k.status()
            self.assertIn("start_date", result)
            self.assertIsNotNone(result["start_date"])

    def test_status_completed_when_state_says_completed(self):
        """status() returns 'completed' when paper_state.json status=completed."""
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "data" / "paper"
            state_dir.mkdir(parents=True, exist_ok=True)
            state_file = state_dir / "paper_state.json"
            state_file.write_text(
                json.dumps({"status": "completed", "start_date": "2026-06-19", "day": 30}),
                encoding="utf-8",
            )
            k = PaperTradingKickoff(base_dir=str(tmp))
            result = k.status()
            self.assertEqual(result["status"], "completed")

    def test_status_is_dict(self):
        """status() always returns a dict."""
        with tempfile.TemporaryDirectory() as tmp:
            k = PaperTradingKickoff(base_dir=str(tmp))
            result = k.status()
            self.assertIsInstance(result, dict)


# ── Kill-switch extra ─────────────────────────────────────────────────────────

class TestKillSwitch(unittest.TestCase):
    """Kill switch integration (bonus — ensures section coverage is complete)"""

    def test_kill_switch_triggered_blocks_kickoff(self):
        """Kickoff is blocked when kill_switch_status.json triggered=True."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp), kill=_KILL_SWITCH_ON)
            result = k.kickoff(dry_run=True)
            self.assertFalse(result.success)

    def test_kill_switch_missing_does_not_block(self):
        """Missing kill_switch_status.json does NOT block kickoff (non-required)."""
        with tempfile.TemporaryDirectory() as tmp:
            k = _make_env(Path(tmp), kill=None)
            result = k.kickoff(dry_run=True)
            self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
