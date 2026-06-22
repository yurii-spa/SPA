"""
tests/test_evidence_scoring_audit.py

MP-1352 (v9.68) — 35 tests for EvidenceScoringAudit.

Categories:
  1. Initialisation & input validation         (tests  1-5)
  2. daily_score() — values & multipliers      (tests  6-14)
  3. days_to_live() — basic behaviour          (tests 15-18)
  4. days_to_live_at() — boundary conditions   (tests 19-24)
  5. roadmap() — structure & ordering          (tests 25-29)
  6. source_impact() — keys & math             (tests 30-33)
  7. to_markdown() — output string             (tests 34-35)

Run:
    python3 -m unittest tests.test_evidence_scoring_audit -v

stdlib only. No external dependencies.
"""

from __future__ import annotations

import math
import sys
import os
import unittest

# ── repo root import ──────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.backtesting.evidence_scoring_audit import (
    EvidenceScoringAudit,
    SCORE_CLEAN,
    SCORE_RESEARCH,
    MULTIPLIER_EXTREME,
    MULTIPLIER_HIGH_DRIFT,
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Initialisation & input validation (tests 1-5)
# ══════════════════════════════════════════════════════════════════════════════

class TestInit(unittest.TestCase):

    def test_01_default_init(self):
        """EvidenceScoringAudit initialises with default clean_pct=0.17."""
        a = EvidenceScoringAudit()
        self.assertIsInstance(a, EvidenceScoringAudit)

    def test_02_custom_clean_pct(self):
        """Accepts any valid clean_pct in [0, 1]."""
        a = EvidenceScoringAudit(clean_pct=0.5)
        self.assertIsInstance(a, EvidenceScoringAudit)

    def test_03_zero_clean_pct(self):
        """Accepts clean_pct=0.0."""
        a = EvidenceScoringAudit(clean_pct=0.0)
        self.assertIsInstance(a, EvidenceScoringAudit)

    def test_04_full_clean_pct(self):
        """Accepts clean_pct=1.0."""
        a = EvidenceScoringAudit(clean_pct=1.0)
        self.assertIsInstance(a, EvidenceScoringAudit)

    def test_05_invalid_clean_pct_raises(self):
        """clean_pct > 1 or < 0 must raise ValueError."""
        with self.assertRaises(ValueError):
            EvidenceScoringAudit(clean_pct=1.1)
        with self.assertRaises(ValueError):
            EvidenceScoringAudit(clean_pct=-0.1)


# ══════════════════════════════════════════════════════════════════════════════
# 2. daily_score() (tests 6-14)
# ══════════════════════════════════════════════════════════════════════════════

class TestDailyScore(unittest.TestCase):

    def test_06_positive_at_zero_clean(self):
        """daily_score() > 0 even when clean_pct=0 (research sources earn 0.3)."""
        a = EvidenceScoringAudit(clean_pct=0.0)
        self.assertGreater(a.daily_score(), 0.0)

    def test_07_equals_research_score_at_zero_clean(self):
        """At clean_pct=0 normal day → exactly SCORE_RESEARCH."""
        a = EvidenceScoringAudit(clean_pct=0.0)
        self.assertAlmostEqual(a.daily_score(), SCORE_RESEARCH, places=9)

    def test_08_equals_clean_score_at_full_clean(self):
        """At clean_pct=1.0 normal day → exactly SCORE_CLEAN."""
        a = EvidenceScoringAudit(clean_pct=1.0)
        self.assertAlmostEqual(a.daily_score(), SCORE_CLEAN, places=9)

    def test_09_extreme_multiplier_at_full_clean(self):
        """daily_score(is_extreme=True) at clean_pct=1.0 → 1.5 pts."""
        a = EvidenceScoringAudit(clean_pct=1.0)
        self.assertAlmostEqual(
            a.daily_score(is_extreme=True),
            SCORE_CLEAN * MULTIPLIER_EXTREME,
            places=9,
        )

    def test_10_extreme_score_is_1_5_at_full_clean(self):
        """Concrete: daily_score(is_extreme=True) == 1.5 at clean_pct=1.0."""
        a = EvidenceScoringAudit(clean_pct=1.0)
        self.assertAlmostEqual(a.daily_score(is_extreme=True), 1.5, places=9)

    def test_11_high_drift_penalty(self):
        """High drift cuts score by ×0.5."""
        a = EvidenceScoringAudit(clean_pct=1.0)
        normal   = a.daily_score()
        drifted  = a.daily_score(is_high_drift=True)
        self.assertAlmostEqual(drifted, normal * MULTIPLIER_HIGH_DRIFT, places=9)

    def test_12_extreme_takes_precedence_over_drift(self):
        """If both extreme and high_drift, extreme multiplier wins."""
        a = EvidenceScoringAudit(clean_pct=0.5)
        extreme_only   = a.daily_score(is_extreme=True)
        extreme_drift  = a.daily_score(is_extreme=True, is_high_drift=True)
        self.assertAlmostEqual(extreme_only, extreme_drift, places=9)

    def test_13_score_increases_with_clean_pct(self):
        """Higher clean_pct → higher daily score (normal day)."""
        a_low  = EvidenceScoringAudit(clean_pct=0.1)
        a_high = EvidenceScoringAudit(clean_pct=0.9)
        self.assertLess(a_low.daily_score(), a_high.daily_score())

    def test_14_score_is_float(self):
        """daily_score() always returns a float."""
        a = EvidenceScoringAudit(clean_pct=0.17)
        self.assertIsInstance(a.daily_score(), float)


# ══════════════════════════════════════════════════════════════════════════════
# 3. days_to_live() — basic behaviour (tests 15-18)
# ══════════════════════════════════════════════════════════════════════════════

class TestDaysToLive(unittest.TestCase):

    def test_15_positive(self):
        """days_to_live() > 0 for any valid clean_pct."""
        for pct in [0.0, 0.17, 0.5, 1.0]:
            a = EvidenceScoringAudit(clean_pct=pct)
            self.assertGreater(a.days_to_live(), 0)

    def test_16_is_integer(self):
        """days_to_live() returns int (ceiling of raw division)."""
        a = EvidenceScoringAudit(clean_pct=0.17)
        self.assertIsInstance(a.days_to_live(), int)

    def test_17_default_clean_pct_more_than_30(self):
        """Current mix (17% CLEAN) requires more than 30 days."""
        a = EvidenceScoringAudit(clean_pct=0.17)
        self.assertGreater(a.days_to_live(), 30)

    def test_18_lower_pct_needs_more_days(self):
        """More CLEAN sources → fewer days to live."""
        a_low  = EvidenceScoringAudit(clean_pct=0.0)
        a_high = EvidenceScoringAudit(clean_pct=1.0)
        self.assertGreater(a_low.days_to_live(), a_high.days_to_live())


# ══════════════════════════════════════════════════════════════════════════════
# 4. days_to_live_at() — boundary conditions (tests 19-24)
# ══════════════════════════════════════════════════════════════════════════════

class TestDaysToLiveAt(unittest.TestCase):

    def test_19_full_clean_equals_30(self):
        """days_to_live_at(1.0) == 30 (100% CLEAN → exactly 30 days)."""
        a = EvidenceScoringAudit()
        self.assertEqual(a.days_to_live_at(1.0), 30)

    def test_20_zero_clean_more_than_30(self):
        """days_to_live_at(0.0) > 30 (all research → slower accumulation)."""
        a = EvidenceScoringAudit()
        self.assertGreater(a.days_to_live_at(0.0), 30)

    def test_21_zero_clean_exact_ceiling(self):
        """days_to_live_at(0.0) == ceil(30 / 0.3) == 100."""
        a = EvidenceScoringAudit()
        expected = math.ceil(30.0 / 0.3)  # = 100
        self.assertEqual(a.days_to_live_at(0.0), expected)

    def test_22_monotone_decreasing_in_clean_pct(self):
        """days_to_live_at decreases (or stays) as clean_pct increases."""
        a = EvidenceScoringAudit()
        prev = a.days_to_live_at(0.0)
        for pct in [0.1, 0.25, 0.5, 0.75, 1.0]:
            curr = a.days_to_live_at(pct)
            self.assertLessEqual(curr, prev)
            prev = curr

    def test_23_returns_int(self):
        """days_to_live_at always returns int."""
        a = EvidenceScoringAudit()
        self.assertIsInstance(a.days_to_live_at(0.5), int)

    def test_24_zero_pct_gt_full_pct(self):
        """0% CLEAN needs more days than 100% CLEAN."""
        a = EvidenceScoringAudit()
        self.assertGreater(a.days_to_live_at(0.0), a.days_to_live_at(1.0))


# ══════════════════════════════════════════════════════════════════════════════
# 5. roadmap() — structure & ordering (tests 25-29)
# ══════════════════════════════════════════════════════════════════════════════

class TestRoadmap(unittest.TestCase):

    def setUp(self):
        self.a = EvidenceScoringAudit()
        self.road = self.a.roadmap()

    def test_25_returns_list(self):
        self.assertIsInstance(self.road, list)

    def test_26_not_empty(self):
        self.assertGreater(len(self.road), 0)

    def test_27_each_item_is_dict(self):
        for row in self.road:
            self.assertIsInstance(row, dict)

    def test_28_each_item_has_required_keys(self):
        for row in self.road:
            self.assertIn("clean_pct",  row)
            self.assertIn("days",       row)
            self.assertIn("milestone",  row)
            self.assertIn("daily_score", row)

    def test_29_days_decrease_as_clean_pct_increases(self):
        """Later milestones (higher CLEAN%) must have <= days."""
        days_list = [row["days"] for row in self.road]
        for i in range(1, len(days_list)):
            self.assertLessEqual(days_list[i], days_list[i - 1])


# ══════════════════════════════════════════════════════════════════════════════
# 6. source_impact() (tests 30-33)
# ══════════════════════════════════════════════════════════════════════════════

class TestSourceImpact(unittest.TestCase):

    def setUp(self):
        self.a = EvidenceScoringAudit(clean_pct=0.17)

    def test_30_returns_dict(self):
        result = self.a.source_impact("aave_v3_usdc")
        self.assertIsInstance(result, dict)

    def test_31_has_days_saved_key(self):
        result = self.a.source_impact("compound_v3_usdc")
        self.assertIn("days_saved", result)

    def test_32_days_saved_non_negative(self):
        """Making a source CLEAN can only help or be neutral."""
        result = self.a.source_impact("morpho_blue")
        self.assertGreaterEqual(result["days_saved"], 0)

    def test_33_all_required_keys_present(self):
        result = self.a.source_impact("sky_susds")
        for key in ("source_id", "weight", "before_days", "after_days", "days_saved", "daily_gain"):
            self.assertIn(key, result)


# ══════════════════════════════════════════════════════════════════════════════
# 7. to_markdown() (tests 34-35)
# ══════════════════════════════════════════════════════════════════════════════

class TestToMarkdown(unittest.TestCase):

    def setUp(self):
        self.a = EvidenceScoringAudit()
        self.md = self.a.to_markdown()

    def test_34_returns_string(self):
        self.assertIsInstance(self.md, str)

    def test_35_contains_30_pts_threshold(self):
        """Must reference the 30-pt threshold in one of the expected formats."""
        has_30 = (
            "30.0" in self.md or
            "30 pt" in self.md or
            "30pt" in self.md or
            "30 pts" in self.md or
            "30.0 pts" in self.md
        )
        self.assertTrue(
            has_30,
            msg=f"Markdown did not contain '30.0' or '30 pt':\n{self.md[:500]}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
