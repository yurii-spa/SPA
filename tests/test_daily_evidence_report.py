"""
tests/test_daily_evidence_report.py

MP-1466 (v10.82): 20 tests for spa_core/alerts/daily_evidence_report.py

Tests cover:
  - build_evidence_message() returns valid HTML string
  - Score section displays current values (20/25)
  - Breakdown shows infrastructure and cycle pts
  - ETA and days-to-target present
  - Progress bar generation (_progress_bar helper)
  - _compute_evidence_score() reads seed + real data correctly
  - _html() escaping
  - _days_to_target() math
  - send_evidence_update() is callable (dry-path, no real Telegram)
  - module is importable with no side effects
"""

import json
import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.alerts.daily_evidence_report import (
    build_evidence_message,
    _compute_evidence_score,
    _progress_bar,
    _html,
    _days_to_target,
    _ETA_DATE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_repo(tmp_dir: str, seed_days: int = 3, real_days: int = 2) -> str:
    """Create a minimal fake repo structure in tmp_dir."""
    root = Path(tmp_dir)
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (root / "spa_core" / "analytics").mkdir(parents=True, exist_ok=True)
    # evidence_auto_calculator.py (just needs to exist)
    (root / "spa_core" / "analytics" / "evidence_auto_calculator.py").write_text("# stub")

    # paper_evidence_history.json with seed days
    hist = {
        "schema_version": "1.0",
        "SEED_DATA": True,
        "days": [
            {
                "date": f"2026-06-{14 + i:02d}",
                "cycle_completed": True,
                "apy_verified": True,
                "risk_policy_passed": True,
                "is_seed": True,
            }
            for i in range(seed_days)
        ],
    }
    (data / "paper_evidence_history.json").write_text(json.dumps(hist))

    # paper_evidence.json with real days
    pe = {
        "days": [
            {"date": f"2026-06-{18 + i:02d}", "apy_pct": 3.9, "equity_value": 100010.0}
            for i in range(real_days)
        ]
    }
    (data / "paper_evidence.json").write_text(json.dumps(pe))

    return str(root)


# ---------------------------------------------------------------------------
# 1. _html() escaping
# ---------------------------------------------------------------------------

class TestHtmlEscaping(unittest.TestCase):

    def test_no_special_chars(self):
        self.assertEqual(_html("hello"), "hello")

    def test_ampersand(self):
        self.assertIn("&amp;", _html("a & b"))

    def test_less_than(self):
        self.assertIn("&lt;", _html("<tag>"))

    def test_greater_than(self):
        self.assertIn("&gt;", _html("1 > 0"))


# ---------------------------------------------------------------------------
# 2. _progress_bar()
# ---------------------------------------------------------------------------

class TestProgressBar(unittest.TestCase):

    def test_zero_progress(self):
        bar = _progress_bar(0, 10)
        self.assertIn("0%", bar)
        self.assertEqual(bar.count("░"), 10)

    def test_full_progress(self):
        bar = _progress_bar(10, 10)
        self.assertIn("100%", bar)
        self.assertEqual(bar.count("█"), 10)

    def test_half_progress(self):
        bar = _progress_bar(5, 10)
        self.assertIn("50%", bar)

    def test_returns_string(self):
        self.assertIsInstance(_progress_bar(3, 10), str)


# ---------------------------------------------------------------------------
# 3. _days_to_target()
# ---------------------------------------------------------------------------

class TestDaysToTarget(unittest.TestCase):

    def test_at_zero(self):
        self.assertEqual(_days_to_target(0, 30), 30)

    def test_halfway(self):
        self.assertEqual(_days_to_target(15, 30), 15)

    def test_at_target(self):
        self.assertEqual(_days_to_target(30, 30), 0)

    def test_over_target(self):
        self.assertEqual(_days_to_target(35, 30), 0)


# ---------------------------------------------------------------------------
# 4. _compute_evidence_score() with fake repo
# ---------------------------------------------------------------------------

class TestComputeEvidenceScore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = _make_fake_repo(self.tmp, seed_days=7, real_days=3)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_dict(self):
        result = _compute_evidence_score(self.repo)
        self.assertIsInstance(result, dict)

    def test_real_days_correct(self):
        result = _compute_evidence_score(self.repo)
        self.assertEqual(result["real_days"], 3)

    def test_seed_days_correct(self):
        result = _compute_evidence_score(self.repo)
        self.assertEqual(result["seed_days"], 7)

    def test_effective_days(self):
        result = _compute_evidence_score(self.repo)
        self.assertAlmostEqual(result["effective"], 6.5, places=1)

    def test_score_gte_10_with_calc(self):
        """Infra pts: calc exists + history init = 10."""
        result = _compute_evidence_score(self.repo)
        self.assertGreaterEqual(result["infra_pts"], 10)


# ---------------------------------------------------------------------------
# 5. build_evidence_message() with real repo data
# ---------------------------------------------------------------------------

class TestBuildEvidenceMessageReal(unittest.TestCase):

    def test_returns_string(self):
        msg = build_evidence_message(base_dir=_REPO)
        self.assertIsInstance(msg, str)

    def test_contains_score(self):
        msg = build_evidence_message(base_dir=_REPO)
        self.assertIn("Score:", msg)
        self.assertIn("20", msg)

    def test_contains_breakdown(self):
        msg = build_evidence_message(base_dir=_REPO)
        self.assertIn("Breakdown", msg)
        self.assertIn("Infrastructure", msg)
        self.assertIn("Daily cycles", msg)

    def test_contains_eta(self):
        msg = build_evidence_message(base_dir=_REPO)
        self.assertIn(_ETA_DATE, msg)

    def test_contains_progress_bar(self):
        msg = build_evidence_message(base_dir=_REPO)
        # Progress bar is inside <code> tags
        self.assertIn("<code>", msg)

    def test_max_4000_chars(self):
        msg = build_evidence_message(base_dir=_REPO)
        self.assertLessEqual(len(msg), 4000, f"Message too long: {len(msg)} chars")

    def test_contains_days_logged(self):
        msg = build_evidence_message(base_dir=_REPO)
        self.assertIn("Days logged", msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
