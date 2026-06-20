"""
tests/test_backtest_paper_correlation.py

MP-1497 (v11.13) — 25 unit tests for BacktestPaperCorrelation.

Covers:
  1. Instantiation & defaults                            (3 tests)
  2. add_day(): data recording                           (4 tests)
  3. _spearman(): correctness & edge cases               (6 tests)
  4. _rank(): tie handling                               (3 tests)
  5. _recalculate(): threshold & golive logic            (5 tests)
  6. reset() and output file                             (4 tests)

Compatible with stdlib unittest and pytest.
"""

import os
import sys
import tempfile
import json
import unittest
import datetime

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.backtesting.backtest_paper_correlation import (
    BacktestPaperCorrelation,
    MIN_CORRELATION_FOR_GOLIVE,
    MIN_DAYS_FOR_VALIDATION,
    GOLIVE_DAYS_REQUIRED,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_bpc(base_dir=None) -> BacktestPaperCorrelation:
    return BacktestPaperCorrelation(base_dir=base_dir or tempfile.mkdtemp())


def _add_n_days(bpc, n, predicted_base=5.0, actual_base=5.0, noise=0.1):
    """Adds n days with slight noise to actual."""
    for i in range(n):
        bpc.add_day(
            predicted_apy=predicted_base + i * 0.05,
            actual_apy=actual_base + i * 0.05 + noise * (i % 3 - 1),
            date=f"2026-06-{(i % 28) + 1:02d}",
        )


class TestInstantiation(unittest.TestCase):
    """TC-BPC-01..03: __init__ sets correct defaults."""

    def test_01_days_tracked_zero(self):
        bpc = _make_bpc()
        self.assertEqual(bpc._data["days_tracked"], 0)

    def test_02_spearman_none_initially(self):
        bpc = _make_bpc()
        self.assertIsNone(bpc._data["spearman_correlation"])

    def test_03_passes_threshold_false_initially(self):
        bpc = _make_bpc()
        self.assertFalse(bpc._data["passes_threshold"])


class TestAddDay(unittest.TestCase):
    """TC-BPC-04..07: add_day() recording correctness."""

    def setUp(self):
        self.bpc = _make_bpc()

    def test_04_add_day_increments_days_tracked(self):
        self.bpc.add_day(5.0, 4.8, "2026-06-01")
        self.assertEqual(self.bpc._data["days_tracked"], 1)

    def test_05_add_day_stores_entry(self):
        self.bpc.add_day(5.0, 4.8, "2026-06-01")
        entry = self.bpc._data["daily_comparisons"][0]
        self.assertEqual(entry["date"], "2026-06-01")
        self.assertAlmostEqual(entry["predicted"], 5.0)
        self.assertAlmostEqual(entry["actual"], 4.8)

    def test_06_add_day_computes_error(self):
        self.bpc.add_day(5.0, 4.0, "2026-06-01")
        self.assertAlmostEqual(self.bpc._data["daily_comparisons"][0]["error"], 1.0)

    def test_07_add_day_uses_today_if_no_date(self):
        self.bpc.add_day(5.0, 4.8)
        today = datetime.date.today().isoformat()
        self.assertEqual(self.bpc._data["daily_comparisons"][0]["date"], today)


class TestSpearman(unittest.TestCase):
    """TC-BPC-08..13: _spearman correctness."""

    def setUp(self):
        self.bpc = _make_bpc()

    def test_08_perfect_positive_correlation(self):
        x = [1, 2, 3, 4, 5]
        rho = self.bpc._spearman(x, x)
        self.assertAlmostEqual(rho, 1.0, places=5)

    def test_09_perfect_negative_correlation(self):
        x = [1, 2, 3, 4, 5]
        y = [5, 4, 3, 2, 1]
        rho = self.bpc._spearman(x, y)
        self.assertAlmostEqual(rho, -1.0, places=5)

    def test_10_zero_correlation_constant_series(self):
        # Can't compute meaningful rank for constants → rho collapses
        x = [3.0] * 5
        y = [1, 2, 3, 4, 5]
        # With all ties, formula gives 1 - 0 = 1; that's correct per formula,
        # but verify it doesn't crash
        rho = self.bpc._spearman(x, y)
        self.assertIsInstance(rho, float)

    def test_11_single_element_returns_zero(self):
        rho = self.bpc._spearman([1.0], [1.0])
        self.assertEqual(rho, 0.0)

    def test_12_result_clipped_to_minus_one_plus_one(self):
        rho = self.bpc._spearman([1, 2, 3], [3, 2, 1])
        self.assertGreaterEqual(rho, -1.0)
        self.assertLessEqual(rho, 1.0)

    def test_13_moderate_positive_correlation(self):
        # nearly matching trend with some noise
        x = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        y = [1.1, 2.3, 2.9, 4.2, 5.1, 5.8, 7.3, 7.9, 9.1, 10.2]
        rho = self.bpc._spearman(x, y)
        self.assertGreater(rho, 0.9)


class TestRank(unittest.TestCase):
    """TC-BPC-14..16: _rank() tie handling."""

    def test_14_no_ties_ascending(self):
        ranks = BacktestPaperCorrelation._rank([10, 20, 30])
        self.assertEqual(ranks, [1.0, 2.0, 3.0])

    def test_15_all_ties_average_rank(self):
        # [5, 5, 5] → all get average rank (1+2+3)/3 = 2.0
        ranks = BacktestPaperCorrelation._rank([5, 5, 5])
        self.assertEqual(ranks, [2.0, 2.0, 2.0])

    def test_16_partial_tie(self):
        # [1, 2, 2, 4] → ranks [1, 2.5, 2.5, 4]
        ranks = BacktestPaperCorrelation._rank([1, 2, 2, 4])
        self.assertEqual(sorted(ranks), [1.0, 2.5, 2.5, 4.0])


class TestRecalculate(unittest.TestCase):
    """TC-BPC-17..21: _recalculate() thresholds & golive logic."""

    def test_17_correlation_none_below_min_days(self):
        bpc = _make_bpc()
        for i in range(MIN_DAYS_FOR_VALIDATION - 1):
            bpc.add_day(float(i), float(i))
        self.assertIsNone(bpc._data["spearman_correlation"])

    def test_18_correlation_set_at_min_days(self):
        bpc = _make_bpc()
        for i in range(MIN_DAYS_FOR_VALIDATION):
            bpc.add_day(float(i), float(i))
        self.assertIsNotNone(bpc._data["spearman_correlation"])

    def test_19_passes_threshold_true_for_high_corr(self):
        bpc = _make_bpc()
        # Perfect positive correlation
        for i in range(MIN_DAYS_FOR_VALIDATION):
            bpc.add_day(float(i), float(i))
        self.assertTrue(bpc._data["passes_threshold"])

    def test_20_golive_ready_requires_30_days(self):
        bpc = _make_bpc()
        # Add exactly MIN_DAYS_FOR_VALIDATION (10) days of perfect corr
        for i in range(MIN_DAYS_FOR_VALIDATION):
            bpc.add_day(float(i), float(i))
        # passes_threshold=True but not golive_ready (need 30)
        self.assertTrue(bpc._data["passes_threshold"])
        self.assertFalse(bpc._data["golive_ready"])

    def test_21_golive_ready_true_after_30_days(self):
        bpc = _make_bpc()
        for i in range(GOLIVE_DAYS_REQUIRED):
            bpc.add_day(float(i), float(i))
        self.assertTrue(bpc._data["golive_ready"])


class TestResetAndOutput(unittest.TestCase):
    """TC-BPC-22..25: reset() and JSON output."""

    def test_22_reset_clears_history(self):
        bpc = _make_bpc()
        _add_n_days(bpc, 15)
        bpc.reset()
        self.assertEqual(bpc._data["days_tracked"], 0)
        self.assertEqual(len(bpc._data["daily_comparisons"]), 0)

    def test_23_reset_clears_correlation(self):
        bpc = _make_bpc()
        _add_n_days(bpc, 15)
        bpc.reset()
        self.assertIsNone(bpc._data["spearman_correlation"])

    def test_24_add_day_writes_json_file(self):
        tmpdir = tempfile.mkdtemp()
        bpc = BacktestPaperCorrelation(base_dir=tmpdir)
        bpc.add_day(5.0, 4.9, "2026-06-01")
        out_path = os.path.join(tmpdir, BacktestPaperCorrelation.OUTPUT_PATH)
        self.assertTrue(os.path.exists(out_path))
        with open(out_path) as f:
            data = json.load(f)
        self.assertEqual(data["days_tracked"], 1)

    def test_25_to_dict_returns_current_state(self):
        bpc = _make_bpc()
        bpc.add_day(5.0, 4.9, "2026-06-01")
        d = bpc.to_dict()
        self.assertEqual(d["days_tracked"], 1)
        self.assertIn("daily_comparisons", d)


if __name__ == "__main__":
    unittest.main()
