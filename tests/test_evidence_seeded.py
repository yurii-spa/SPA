import pytest
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
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.golive_readiness_report import GoLiveReadinessReport
from spa_core.paper_trading.track_evidence import PAPER_REAL_START

_DATA_DIR = Path(_REPO) / "data"
_HIST_FILE = _DATA_DIR / "paper_evidence_history.json"
_PE_FILE = _DATA_DIR / "paper_evidence.json"

# Real track started 2026-06-10; at least this many honest days exist.
_MIN_REAL_DAYS = 13


def _hermetic_evidence_report(n_evidenced_days: int) -> GoLiveReadinessReport:
    """Build a GoLiveReadinessReport whose evidence data is a controlled tmp
    fixture with exactly ``n_evidenced_days`` honest, evidenced paper days.

    Why hermetic: assess_evidence() scores the INTERSECTION of paper_evidence.json
    with dates that are also evidenced on equity_curve_daily.json (the go-live
    gate's own rule). The two LIVE files legitimately drift apart (e.g. the track
    was re-anchored to 2026-06-22, and paper_evidence.json can gap while the equity
    curve is written continuously), so the live intersection is a moving target and
    unsafe to assert exact tier bonuses against. We instead exercise the tier logic
    against a fixture we control, while keeping the real repo base_dir so the
    infrastructure (+10) points resolve against the real source files.

    Bars carry no negative honesty label and are dated >= PAPER_REAL_START, so
    is_evidenced_bar() counts them; the same dates populate paper_evidence.json, so
    the intersection == n_evidenced_days.
    """
    report = GoLiveReadinessReport(base_dir=_REPO)  # real base_dir -> infra +10 pts
    tmp = Path(tempfile.mkdtemp(prefix="spa_evidence_"))
    report.data_dir = tmp  # redirect all evidence-data reads to the fixture

    start = PAPER_REAL_START
    dates = [(start + timedelta(days=i)).isoformat() for i in range(n_evidenced_days)]

    with open(tmp / "paper_evidence.json", "w", encoding="utf-8") as f:
        json.dump({"days": [{"date": d} for d in dates]}, f)

    with open(tmp / "equity_curve_daily.json", "w", encoding="utf-8") as f:
        json.dump({"daily": [{"date": d, "equity": 100_000.0} for d in dates]}, f)

    with open(tmp / "paper_evidence_history.json", "w", encoding="utf-8") as f:
        json.dump({"schema_version": 1, "days": [{"date": d} for d in dates]}, f)

    return report


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

    @pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true", reason="data/state-dependent (needs real evidenced track / gates data); runs locally, skipped in data-less CI)")

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

        The evidence score counts only days that are both in paper_evidence.json
        AND evidenced on the equity curve (the same rule the go-live gate uses). A
        backfill / reconstructed placeholder must NOT earn cycle credit. Asserted
        against a hermetic fixture (5 evidenced days) so the tier bonuses are
        deterministic and independent of live-track drift.
        """
        cat = _hermetic_evidence_report(5).assess_evidence()
        # >=15: infra (10) + the lower cycle tiers (5) at 5 evidenced days.
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
        # Hermetic: 5 evidenced days => the ≥1/≥3/≥5 cycle tiers are all achieved.
        # (Live intersection of paper_evidence.json ∩ equity curve drifts and is
        # not a safe basis for asserting exact tier attainment.)
        cat = _hermetic_evidence_report(5).assess_evidence()
        done_text = " ".join(cat.items_done)
        for tier in ("≥1 real cycle", "≥3 real cycles", "≥5 real cycles"):
            self.assertIn(tier, done_text, f"{tier} should be achieved with 5 evidenced days")

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
        # Hermetic (5 evidenced days): evidence = infra(10) + ≥1/≥3/≥5 tiers(5).
        # Uses a controlled fixture rather than the live intersection, which drifts.
        cats = _hermetic_evidence_report(5)._get_categories()
        ev = next(c for c in cats if c.name == "evidence")
        self.assertGreaterEqual(ev.score, 15.0,
                                "Evidence must be >=15 with infra + real cycle tiers")


if __name__ == "__main__":
    unittest.main(verbosity=2)
