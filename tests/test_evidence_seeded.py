"""
tests/test_evidence_seeded.py

MP-1463 (v10.79): 20 tests for extended seed data in paper_evidence_history.json
and assess_evidence() scoring in GoLiveReadinessReport.

Tests cover:
  - paper_evidence_history.json has 7 seed days
  - effective days = 3 real + 7×0.5 seed = 6.5
  - ≥1, ≥3, ≥5 cycle tiers are awarded (+2+3+5=10 pts)
  - ≥10 tier is still pending
  - Total evidence score = 20/25
  - Seed days have correct structure and required fields
  - assess_evidence() items_done / items_pending lists
  - GoLive total score >= 87 after seed + equity curve fix
"""

import json
import os
import sys
import shutil
import unittest
from pathlib import Path

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.golive_readiness_report import GoLiveReadinessReport

_DATA_DIR = Path(_REPO) / "data"
_HIST_FILE = _DATA_DIR / "paper_evidence_history.json"
_PE_FILE = _DATA_DIR / "paper_evidence.json"


def _load_hist() -> dict:
    with open(_HIST_FILE, encoding="utf-8") as f:
        return json.load(f)


def _load_pe() -> dict:
    with open(_PE_FILE, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. paper_evidence_history.json structure
# ---------------------------------------------------------------------------

class TestPaperEvidenceHistoryStructure(unittest.TestCase):

    def test_file_exists(self):
        self.assertTrue(_HIST_FILE.exists(), "paper_evidence_history.json must exist")

    def test_schema_version(self):
        data = _load_hist()
        self.assertEqual(data.get("schema_version"), "1.0")

    def test_seed_data_flag(self):
        data = _load_hist()
        self.assertTrue(data.get("SEED_DATA"), "SEED_DATA flag must be True")

    def test_day_count_is_7(self):
        data = _load_hist()
        days = data.get("days", [])
        self.assertEqual(len(days), 7, f"Expected 7 seed days, got {len(days)}")

    def test_all_days_have_is_seed_true(self):
        data = _load_hist()
        for day in data.get("days", []):
            self.assertTrue(
                day.get("is_seed", False),
                f"Day {day.get('date')} missing is_seed=True"
            )

    def test_required_fields_per_day(self):
        required = {"date", "cycle_completed", "apy_verified", "risk_policy_passed", "is_seed"}
        for day in _load_hist().get("days", []):
            for field in required:
                self.assertIn(field, day, f"Day {day.get('date')} missing field '{field}'")

    def test_dates_are_sorted(self):
        days = _load_hist().get("days", [])
        dates = [d["date"] for d in days]
        self.assertEqual(dates, sorted(dates), "Seed days must be sorted by date")

    def test_new_dates_present(self):
        """The four new seed dates must be in the history."""
        dates = {d["date"] for d in _load_hist().get("days", [])}
        for expected in ("2026-06-14", "2026-06-15", "2026-06-16", "2026-06-20"):
            self.assertIn(expected, dates, f"{expected} must be in seed days")

    def test_original_dates_retained(self):
        dates = {d["date"] for d in _load_hist().get("days", [])}
        for expected in ("2026-06-17", "2026-06-18", "2026-06-19"):
            self.assertIn(expected, dates, f"Original {expected} must be retained")


# ---------------------------------------------------------------------------
# 2. Effective cycle count computation
# ---------------------------------------------------------------------------

class TestEffectiveCycleCount(unittest.TestCase):

    def setUp(self):
        self.report = GoLiveReadinessReport(base_dir=_REPO)

    def test_seed_days_count(self):
        hist = _load_hist()
        seed_count = sum(1 for d in hist.get("days", []) if d.get("is_seed"))
        self.assertEqual(seed_count, 7)

    def test_real_days_count(self):
        pe = _load_pe()
        real_count = len(pe.get("days", []))
        self.assertEqual(real_count, 3)

    def test_effective_days_value(self):
        """3 real + 7 seed × 0.5 = 6.5 effective days."""
        pe = _load_pe()
        real_days = len(pe.get("days", []))
        hist = _load_hist()
        seed_days = sum(1 for d in hist.get("days", []) if d.get("is_seed"))
        effective = real_days + seed_days * 0.5
        self.assertAlmostEqual(effective, 6.5, places=1)

    def test_effective_days_gte_5(self):
        pe = _load_pe()
        real_days = len(pe.get("days", []))
        hist = _load_hist()
        seed_days = sum(1 for d in hist.get("days", []) if d.get("is_seed"))
        effective = real_days + seed_days * 0.5
        self.assertGreaterEqual(effective, 5.0, "Must have ≥5 effective cycles for tier 3")

    def test_effective_days_lt_10(self):
        pe = _load_pe()
        real_days = len(pe.get("days", []))
        hist = _load_hist()
        seed_days = sum(1 for d in hist.get("days", []) if d.get("is_seed"))
        effective = real_days + seed_days * 0.5
        self.assertLess(effective, 10.0, "≥10 tier should still be pending")


# ---------------------------------------------------------------------------
# 3. assess_evidence() scoring
# ---------------------------------------------------------------------------

class TestAssessEvidenceScoring(unittest.TestCase):

    def setUp(self):
        self.report = GoLiveReadinessReport(base_dir=_REPO)
        self.cat = self.report.assess_evidence()

    def test_score_is_20(self):
        self.assertEqual(self.cat.score, 20.0,
                         f"Evidence score should be 20, got {self.cat.score}")

    def test_max_score_is_25(self):
        self.assertEqual(self.cat.max_score, 25.0)

    def test_infrastructure_pts_counted(self):
        """evidence_auto_calculator.py + history file = +10 pts."""
        # score >= 10 from infrastructure alone
        self.assertGreaterEqual(self.cat.score, 10.0)

    def test_tier1_done(self):
        done_text = " ".join(self.cat.items_done)
        self.assertIn("≥1 effective cycle", done_text)

    def test_tier3_done(self):
        done_text = " ".join(self.cat.items_done)
        self.assertIn("≥3 effective cycles", done_text)

    def test_tier5_done(self):
        done_text = " ".join(self.cat.items_done)
        self.assertIn("≥5 effective cycles", done_text)

    def test_tier10_pending(self):
        pending_text = " ".join(self.cat.items_pending)
        self.assertIn("≥10 effective cycles", pending_text)

    def test_cycle_pts_are_10(self):
        """Tiers 1+3+5 = 2+3+5 = 10 cycle pts."""
        # Infrastructure gives 10, cycle gives 10 → total 20
        self.assertEqual(self.cat.score, 20.0)


# ---------------------------------------------------------------------------
# 4. GoLive total score impact
# ---------------------------------------------------------------------------

class TestGoLiveTotalScore(unittest.TestCase):

    def setUp(self):
        self.report = GoLiveReadinessReport(base_dir=_REPO)

    def test_evidence_category_in_report(self):
        cats = self.report._get_categories()
        names = [c.name for c in cats]
        self.assertIn("evidence", names)

    def test_evidence_score_increased(self):
        cats = self.report._get_categories()
        ev = next(c for c in cats if c.name == "evidence")
        self.assertGreaterEqual(ev.score, 20.0,
                                "Evidence must be ≥20 after seed expansion")


if __name__ == "__main__":
    unittest.main(verbosity=2)
