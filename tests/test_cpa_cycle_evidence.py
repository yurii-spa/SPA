"""
tests/test_cpa_cycle_evidence.py

MP-1410 (v10.26): 30 unit tests for CPACycleWithEvidence.

Coverage:
  - Construction and delegation (4 tests)
  - _update_evidence_after_cycle() with status OK → records entry (4 tests)
  - _update_evidence_after_cycle() with status FAIL → cycle_completed=False (3 tests)
  - Evidence file created atomically after run (3 tests)
  - Two invocations → two history entries (3 tests)
  - Score increases with each successful cycle (3 tests)
  - apy_ok extraction from sections (4 tests)
  - risk_ok from risk_policy_blocks.json (4 tests)
  - logs() captures evidence output (2 tests)
  - _risk_policy_passed_today() edge cases (2 tests)

Run:
    python3 -m unittest tests/test_cpa_cycle_evidence.py -v
"""

import json
import os
import sys
import tempfile
import datetime
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.backtesting.cpa_cycle_with_evidence import CPACycleWithEvidence
from spa_core.analytics.evidence_auto_calculator import EvidenceAutoCalculator


# ─── Stub cycle class ─────────────────────────────────────────────────────────

def _make_stub_cycle(sections: dict = None, date: str = "2026-06-01"):
    """Return a stub CPADailyCycle-compatible class."""

    class _StubCycle:
        def __init__(self, base_dir=".", date=None):
            self._base_dir = Path(base_dir)
            self._date = date or "2026-06-01"

        def run(self) -> dict:
            secs = sections or {}
            return {"date": self._date, "sections": secs}

        def save(self, result):
            return "/tmp/fake.json"

        def to_telegram_message(self, result):
            return "stub"

        def send_telegram(self, result):
            return False

    return _StubCycle


def _ok_sections(apy: float = 4.5, paper_active: bool = True) -> dict:
    """Return sections dict that looks like a healthy run."""
    return {
        "gate_check": {"backtest": "PASS", "pre_paper": "PASS", "paper": "READY"},
        "source_status": {"total": 3, "clean_included": 3},
        "evidence_update": {
            "paper_active": paper_active,
            "days_running": 2,
            "apy_today_pct": apy,
            "is_demo": False,
        },
        "regime_check": {"regime": "neutral"},
        "research_gates": {},
        "governance_log": {},
        "telegram": {"sent": False},
    }


def _fail_sections() -> dict:
    """Return sections dict with a section error."""
    return {
        "gate_check": {"error": "file not found"},
        "evidence_update": {"paper_active": False, "days_running": 0},
    }


def _wrap(tmp_dir: str, sections=None, date: str = "2026-06-01") -> CPACycleWithEvidence:
    """Construct a CPACycleWithEvidence with stub inner cycle."""
    stub_cls = _make_stub_cycle(sections=sections, date=date)
    return CPACycleWithEvidence(
        base_dir=tmp_dir,
        date=date,
        _cycle_cls=stub_cls,
    )


# ─── Group 1: Construction and delegation (4 tests) ──────────────────────────

class TestConstruction(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_instantiates(self):
        w = _wrap(self.tmp)
        self.assertIsNotNone(w)

    def test_base_dir_stored(self):
        w = _wrap(self.tmp)
        self.assertEqual(str(w._base_dir), self.tmp)

    def test_date_stored(self):
        w = _wrap(self.tmp, date="2026-07-01")
        self.assertEqual(w._date, "2026-07-01")

    def test_logs_empty_initially(self):
        w = _wrap(self.tmp)
        self.assertEqual(w.logs(), [])


# ─── Group 2: _update_evidence_after_cycle() status OK records entry (4 tests) ─

class TestUpdateEvidenceOK(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "data"), exist_ok=True)

    def test_returns_evidence_score(self):
        w = _wrap(self.tmp, sections=_ok_sections())
        result = {"status": "OK", "sections": _ok_sections(), "date": "2026-06-01"}
        score = w._update_evidence_after_cycle(result)
        self.assertIsNotNone(score)

    def test_ok_result_sets_cycle_completed_true(self):
        w = _wrap(self.tmp, date="2026-06-01")
        result = {"status": "OK", "sections": _ok_sections(), "date": "2026-06-01"}
        w._update_evidence_after_cycle(result)
        calc = EvidenceAutoCalculator(base_dir=self.tmp)
        calc.load()
        self.assertEqual(len(calc._history), 1)
        self.assertTrue(calc._history[0].cycle_completed)

    def test_ok_result_with_apy_sets_apy_verified_true(self):
        w = _wrap(self.tmp, date="2026-06-01")
        result = {"status": "OK", "sections": _ok_sections(apy=5.0, paper_active=True)}
        w._update_evidence_after_cycle(result)
        calc = EvidenceAutoCalculator(base_dir=self.tmp)
        calc.load()
        self.assertTrue(calc._history[0].apy_verified)

    def test_evidence_file_written_after_update(self):
        w = _wrap(self.tmp, date="2026-06-01")
        result = {"status": "OK", "sections": _ok_sections()}
        w._update_evidence_after_cycle(result)
        evidence_file = Path(self.tmp) / "data" / "paper_evidence_history.json"
        self.assertTrue(evidence_file.exists())


# ─── Group 3: _update_evidence_after_cycle() FAIL → cycle_completed=False (3 tests) ─

class TestUpdateEvidenceFail(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "data"), exist_ok=True)

    def test_fail_result_sets_cycle_completed_false(self):
        w = _wrap(self.tmp, date="2026-06-02")
        result = {"status": "FAIL", "sections": _fail_sections(), "date": "2026-06-02"}
        w._update_evidence_after_cycle(result)
        calc = EvidenceAutoCalculator(base_dir=self.tmp)
        calc.load()
        self.assertFalse(calc._history[0].cycle_completed)

    def test_fail_result_apy_not_verified(self):
        w = _wrap(self.tmp, date="2026-06-02")
        result = {"status": "FAIL", "sections": _fail_sections()}
        w._update_evidence_after_cycle(result)
        calc = EvidenceAutoCalculator(base_dir=self.tmp)
        calc.load()
        self.assertFalse(calc._history[0].apy_verified)

    def test_evidence_file_still_created_on_fail(self):
        w = _wrap(self.tmp, date="2026-06-02")
        result = {"status": "FAIL", "sections": _fail_sections()}
        w._update_evidence_after_cycle(result)
        evidence_file = Path(self.tmp) / "data" / "paper_evidence_history.json"
        self.assertTrue(evidence_file.exists())


# ─── Group 4: Evidence file created atomically after run() (3 tests) ─────────

class TestRunCreatesFile(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "data"), exist_ok=True)

    def test_run_creates_evidence_file(self):
        w = _wrap(self.tmp, sections=_ok_sections(), date="2026-06-01")
        w.run()
        evidence_file = Path(self.tmp) / "data" / "paper_evidence_history.json"
        self.assertTrue(evidence_file.exists())

    def test_evidence_file_is_valid_json(self):
        w = _wrap(self.tmp, sections=_ok_sections(), date="2026-06-01")
        w.run()
        evidence_file = Path(self.tmp) / "data" / "paper_evidence_history.json"
        with open(evidence_file, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("history", data)

    def test_run_returns_status_key(self):
        w = _wrap(self.tmp, sections=_ok_sections(), date="2026-06-01")
        result = w.run()
        self.assertIn("status", result)


# ─── Group 5: Two calls → two history entries (3 tests) ──────────────────────

class TestTwoInvocations(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "data"), exist_ok=True)

    def test_two_different_dates_two_entries(self):
        w1 = _wrap(self.tmp, sections=_ok_sections(), date="2026-06-01")
        w1.run()
        w2 = _wrap(self.tmp, sections=_ok_sections(), date="2026-06-02")
        w2.run()

        calc = EvidenceAutoCalculator(base_dir=self.tmp)
        calc.load()
        self.assertEqual(len(calc._history), 2)

    def test_two_entries_correct_dates(self):
        for day in ("2026-06-01", "2026-06-02"):
            w = _wrap(self.tmp, sections=_ok_sections(), date=day)
            w.run()

        calc = EvidenceAutoCalculator(base_dir=self.tmp)
        calc.load()
        dates = [d.date for d in calc._history]
        self.assertIn("2026-06-01", dates)
        self.assertIn("2026-06-02", dates)

    def test_same_date_twice_no_duplicate(self):
        for _ in range(2):
            w = _wrap(self.tmp, sections=_ok_sections(), date="2026-06-01")
            w.run()

        calc = EvidenceAutoCalculator(base_dir=self.tmp)
        calc.load()
        self.assertEqual(len(calc._history), 1)


# ─── Group 6: Score increases with each successful cycle (3 tests) ────────────

class TestScoreGrowth(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "data"), exist_ok=True)

    def _score(self) -> int:
        calc = EvidenceAutoCalculator(base_dir=self.tmp)
        calc.load()
        return calc.calculate_score().total

    def test_score_zero_before_any_run(self):
        self.assertEqual(self._score(), 0)

    def test_score_positive_after_one_run(self):
        w = _wrap(self.tmp, sections=_ok_sections(), date="2026-06-01")
        w.run()
        self.assertGreater(self._score(), 0)

    def test_score_increases_after_second_run(self):
        w1 = _wrap(self.tmp, sections=_ok_sections(), date="2026-06-01")
        w1.run()
        score1 = self._score()

        w2 = _wrap(self.tmp, sections=_ok_sections(), date="2026-06-02")
        w2.run()
        score2 = self._score()

        self.assertGreater(score2, score1)


# ─── Group 7: apy_ok extraction (4 tests) ────────────────────────────────────

class TestApyExtraction(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "data"), exist_ok=True)

    def test_apy_ok_true_when_apy_positive(self):
        w = _wrap(self.tmp, date="2026-06-01")
        result = {"status": "OK", "sections": _ok_sections(apy=5.0, paper_active=True)}
        w._update_evidence_after_cycle(result)
        calc = EvidenceAutoCalculator(base_dir=self.tmp)
        calc.load()
        self.assertTrue(calc._history[0].apy_verified)

    def test_apy_ok_false_when_paper_inactive(self):
        w = _wrap(self.tmp, date="2026-06-01")
        result = {"status": "OK", "sections": _ok_sections(apy=5.0, paper_active=False)}
        w._update_evidence_after_cycle(result)
        calc = EvidenceAutoCalculator(base_dir=self.tmp)
        calc.load()
        self.assertFalse(calc._history[0].apy_verified)

    def test_apy_ok_false_when_apy_none(self):
        secs = _ok_sections(paper_active=True)
        secs["evidence_update"]["apy_today_pct"] = None
        w = _wrap(self.tmp, date="2026-06-01")
        result = {"status": "OK", "sections": secs}
        w._update_evidence_after_cycle(result)
        calc = EvidenceAutoCalculator(base_dir=self.tmp)
        calc.load()
        self.assertFalse(calc._history[0].apy_verified)

    def test_apy_ok_false_when_apy_zero(self):
        w = _wrap(self.tmp, date="2026-06-01")
        result = {"status": "OK", "sections": _ok_sections(apy=0.0, paper_active=True)}
        w._update_evidence_after_cycle(result)
        calc = EvidenceAutoCalculator(base_dir=self.tmp)
        calc.load()
        self.assertFalse(calc._history[0].apy_verified)


# ─── Group 8: risk_ok from risk_policy_blocks.json (4 tests) ─────────────────

class TestRiskExtraction(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "data"), exist_ok=True)

    def _write_blocks(self, blocks: list) -> None:
        path = Path(self.tmp) / "data" / "risk_policy_blocks.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(blocks, fh)

    def test_risk_ok_true_when_no_blocks_file(self):
        w = _wrap(self.tmp, date="2026-06-01")
        result = w._risk_policy_passed_today({})
        self.assertTrue(result)

    def test_risk_ok_true_when_blocks_empty(self):
        self._write_blocks([])
        w = _wrap(self.tmp, date="2026-06-01")
        self.assertTrue(w._risk_policy_passed_today({}))

    def test_risk_ok_false_when_block_today(self):
        self._write_blocks([{"date": "2026-06-01T08:00:00", "reason": "drawdown"}])
        w = _wrap(self.tmp, date="2026-06-01")
        self.assertFalse(w._risk_policy_passed_today({}))

    def test_risk_ok_true_when_block_different_date(self):
        self._write_blocks([{"date": "2026-05-31", "reason": "drawdown"}])
        w = _wrap(self.tmp, date="2026-06-01")
        self.assertTrue(w._risk_policy_passed_today({}))


# ─── Group 9: logs() captures evidence output (2 tests) ──────────────────────

class TestLogs(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "data"), exist_ok=True)

    def test_logs_populated_after_run(self):
        w = _wrap(self.tmp, sections=_ok_sections(), date="2026-06-01")
        w.run()
        self.assertTrue(len(w.logs()) > 0)

    def test_logs_contain_score_info(self):
        w = _wrap(self.tmp, sections=_ok_sections(), date="2026-06-01")
        w.run()
        combined = " ".join(w.logs())
        # Should mention score or pts
        self.assertTrue("score" in combined.lower() or "pts" in combined.lower())


# ─── Group 10: _risk_policy_passed_today() edge cases (2 tests) ───────────────

class TestRiskEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "data"), exist_ok=True)

    def test_risk_ok_true_when_file_is_not_a_list(self):
        path = Path(self.tmp) / "data" / "risk_policy_blocks.json"
        with open(path, "w") as fh:
            json.dump({"not": "a list"}, fh)
        w = _wrap(self.tmp, date="2026-06-01")
        self.assertTrue(w._risk_policy_passed_today({}))

    def test_risk_ok_true_on_corrupt_file(self):
        path = Path(self.tmp) / "data" / "risk_policy_blocks.json"
        path.write_text("{ corrupt json }", encoding="utf-8")
        w = _wrap(self.tmp, date="2026-06-01")
        self.assertTrue(w._risk_policy_passed_today({}))


if __name__ == "__main__":
    unittest.main()
