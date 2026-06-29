"""
tests/test_evidence_seeded.py

Evidence scoring is HONEST real-only (seed days retired 2026-06-23): the GoLive
evidence category counts only real paper-trading days from paper_evidence.json.
Synthetic 0.5-weight "seed" bootstrap days were removed because counting them
inflated the track, contradicting the project's honest-track-record principle.

Tests are robust to track growth — they assert relationships and lower bounds,
not frozen day counts (the track grows by one real day each cycle).
"""

import json
import os
import sys
import unittest
from pathlib import Path

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.golive_readiness_report import GoLiveReadinessReport

_DATA_DIR = Path(_REPO) / "data"
_HIST_FILE = _DATA_DIR / "paper_evidence_history.json"
_PE_FILE = _DATA_DIR / "paper_evidence.json"

# Real track started 2026-06-10; at least this many honest days exist.
_MIN_REAL_DAYS = 13


def _load_hist() -> dict:
    with open(_HIST_FILE, encoding="utf-8") as f:
        return json.load(f)


def _load_pe() -> dict:
    with open(_PE_FILE, encoding="utf-8") as f:
        return json.load(f)


def _hist_days(hist: dict) -> list:
    """History day list under the canonical 'days' key (legacy: 'history')."""
    return hist.get("days") or hist.get("history") or []


# ---------------------------------------------------------------------------
# 1. paper_evidence_history.json structure (when populated)
# ---------------------------------------------------------------------------

class TestPaperEvidenceHistoryStructure(unittest.TestCase):

    def test_file_exists(self):
        self.assertTrue(_HIST_FILE.exists(), "paper_evidence_history.json must exist")

    def test_days_sorted(self):
        days = _hist_days(_load_hist())
        dates = [d["date"] for d in days if isinstance(d, dict) and "date" in d]
        self.assertEqual(dates, sorted(dates), "history days must be sorted by date")

    def test_required_fields_per_day(self):
        required = {"date", "cycle_completed", "apy_verified", "risk_policy_passed"}
        for day in _hist_days(_load_hist()):
            if not isinstance(day, dict):
                continue
            for field in required:
                self.assertIn(field, day, f"Day {day.get('date')} missing '{field}'")

    def test_no_duplicate_dates(self):
        days = _hist_days(_load_hist())
        dates = [d["date"] for d in days if isinstance(d, dict) and "date" in d]
        self.assertEqual(len(dates), len(set(dates)), "history must have no duplicate dates")


# ---------------------------------------------------------------------------
# 2. Real cycle count (honest, real-only)
# ---------------------------------------------------------------------------

class TestRealCycleCount(unittest.TestCase):

    def test_real_days_present(self):
        pe = _load_pe()
        real_count = len(pe.get("days", []))
        self.assertGreaterEqual(
            real_count, _MIN_REAL_DAYS,
            f"track started 2026-06-10; expected >= {_MIN_REAL_DAYS} real days",
        )

    def test_real_days_distinct_and_sorted(self):
        pe = _load_pe()
        dates = [d.get("date") for d in pe.get("days", []) if isinstance(d, dict)]
        self.assertEqual(dates, sorted(dates), "real days must be sorted")
        self.assertEqual(len(dates), len(set(dates)), "real days must be distinct")

    def test_effective_equals_real(self):
        """Honest model: cycle credit is driven by EVIDENCED days, not the raw
        paper_evidence.json length (#6).

        The evidence score counts only days with a real daily_cycle log on the
        equity curve (the same rule the go-live gate uses). A backfill /
        reconstructed placeholder in paper_evidence.json must NOT earn cycle
        credit. We assert the floor that always holds — infrastructure (+10) plus
        at least the ≥1/≥3/≥5 cycle tiers (+5) once ≥5 evidenced days exist —
        without enshrining the OLD over-reported count.
        """
        report = GoLiveReadinessReport(base_dir=_REPO)
        cat = report.assess_evidence()
        # >=15: infra (10) + the lower cycle tiers (5) for the evidenced track.
        self.assertGreaterEqual(cat.score, 15.0)
        # Honest cap: never over-credit beyond the max.
        self.assertLessEqual(cat.score, cat.max_score)


# ---------------------------------------------------------------------------
# 3. assess_evidence() scoring (real-only)
# ---------------------------------------------------------------------------

class TestAssessEvidenceScoring(unittest.TestCase):

    def setUp(self):
        self.cat = GoLiveReadinessReport(base_dir=_REPO).assess_evidence()

    def test_max_score_is_25(self):
        self.assertEqual(self.cat.max_score, 25.0)

    def test_infrastructure_pts_counted(self):
        # evidence_auto_calculator.py + history file initialized = +10 pts.
        self.assertGreaterEqual(self.cat.score, 10.0)

    def test_score_within_bounds(self):
        self.assertGreaterEqual(self.cat.score, 0.0)
        self.assertLessEqual(self.cat.score, self.cat.max_score)

    def test_lower_tiers_done(self):
        done_text = " ".join(self.cat.items_done)
        for tier in ("≥1 real cycle", "≥3 real cycles", "≥5 real cycles"):
            self.assertIn(tier, done_text, f"{tier} should be achieved with >=13 real days")

    def test_no_seed_inflation_in_notes(self):
        # Honest model must not advertise seed days in the evidence notes.
        self.assertNotIn("seed", (self.cat.notes or "").lower())


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

    def test_evidence_score_reasonable(self):
        cats = self.report._get_categories()
        ev = next(c for c in cats if c.name == "evidence")
        self.assertGreaterEqual(ev.score, 15.0,
                                "Evidence must be >=15 with infra + real cycle tiers")


if __name__ == "__main__":
    unittest.main(verbosity=2)
