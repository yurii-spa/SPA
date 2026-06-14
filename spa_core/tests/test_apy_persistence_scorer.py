"""
MP-851 APYPersistenceScorer — unit tests (>=60)
Run: python3 -m unittest spa_core.tests.test_apy_persistence_scorer -v
"""

import json
import math
import os
import tempfile
import unittest

from spa_core.analytics.apy_persistence_scorer import (
    analyze,
    log_result,
    _mean,
    _stdev,
    _peak,
    _time_above_threshold_pct,
    _lag1_autocorrelation,
    _coefficient_of_variation,
    _drawdown_from_peak_pct,
    _trend,
    _persistence_score,
    _grade,
    _classification,
    _risk_flags,
    _recommendations,
)


# ---------------------------------------------------------------------------
# _mean
# ---------------------------------------------------------------------------

class TestMean(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_single(self):
        self.assertEqual(_mean([7.5]), 7.5)

    def test_basic(self):
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0]), 2.0)

    def test_negatives(self):
        self.assertAlmostEqual(_mean([-2.0, 2.0]), 0.0)

    def test_constant(self):
        self.assertEqual(_mean([5.0, 5.0, 5.0]), 5.0)


# ---------------------------------------------------------------------------
# _stdev
# ---------------------------------------------------------------------------

class TestStdev(unittest.TestCase):
    def test_empty_zero(self):
        self.assertEqual(_stdev([]), 0.0)

    def test_single_zero(self):
        self.assertEqual(_stdev([4.0]), 0.0)

    def test_constant_zero(self):
        self.assertEqual(_stdev([3.0, 3.0, 3.0]), 0.0)

    def test_population_known(self):
        # population stdev of [2,4] = 1.0
        self.assertAlmostEqual(_stdev([2.0, 4.0]), 1.0)

    def test_positive(self):
        self.assertGreater(_stdev([1.0, 2.0, 3.0]), 0.0)


# ---------------------------------------------------------------------------
# _peak
# ---------------------------------------------------------------------------

class TestPeak(unittest.TestCase):
    def test_empty_zero(self):
        self.assertEqual(_peak([]), 0.0)

    def test_single(self):
        self.assertEqual(_peak([6.0]), 6.0)

    def test_basic(self):
        self.assertEqual(_peak([1.0, 9.0, 4.0]), 9.0)

    def test_negatives(self):
        self.assertEqual(_peak([-3.0, -1.0, -5.0]), -1.0)


# ---------------------------------------------------------------------------
# _time_above_threshold_pct
# ---------------------------------------------------------------------------

class TestTimeAboveThreshold(unittest.TestCase):
    def test_empty_zero(self):
        self.assertEqual(_time_above_threshold_pct([], 5.0), 0.0)

    def test_all_above(self):
        self.assertEqual(_time_above_threshold_pct([6.0, 7.0, 8.0], 5.0), 100.0)

    def test_none_above(self):
        self.assertEqual(_time_above_threshold_pct([1.0, 2.0], 5.0), 0.0)

    def test_half_above(self):
        self.assertEqual(_time_above_threshold_pct([4.0, 6.0], 5.0), 50.0)

    def test_equal_counts_as_above(self):
        self.assertEqual(_time_above_threshold_pct([5.0, 5.0], 5.0), 100.0)


# ---------------------------------------------------------------------------
# _lag1_autocorrelation
# ---------------------------------------------------------------------------

class TestLag1Autocorrelation(unittest.TestCase):
    def test_single_none(self):
        self.assertIsNone(_lag1_autocorrelation([5.0]))

    def test_empty_none(self):
        self.assertIsNone(_lag1_autocorrelation([]))

    def test_constant_none(self):
        # zero variance -> None
        self.assertIsNone(_lag1_autocorrelation([4.0, 4.0, 4.0]))

    def test_perfectly_alternating_negative(self):
        ac = _lag1_autocorrelation([1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
        self.assertLess(ac, 0.0)

    def test_smooth_positive(self):
        ac = _lag1_autocorrelation([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertGreater(ac, 0.0)

    def test_clamped_range(self):
        ac = _lag1_autocorrelation([8.0, 8.1, 8.0, 8.1, 8.0])
        self.assertGreaterEqual(ac, -1.0)
        self.assertLessEqual(ac, 1.0)


# ---------------------------------------------------------------------------
# _coefficient_of_variation
# ---------------------------------------------------------------------------

class TestCoefficientOfVariation(unittest.TestCase):
    def test_zero_mean_none(self):
        self.assertIsNone(_coefficient_of_variation(0.0, 1.0))

    def test_none_inputs(self):
        self.assertIsNone(_coefficient_of_variation(None, 1.0))
        self.assertIsNone(_coefficient_of_variation(1.0, None))

    def test_basic(self):
        self.assertAlmostEqual(_coefficient_of_variation(10.0, 2.0), 0.2)

    def test_negative_mean_uses_abs(self):
        self.assertAlmostEqual(_coefficient_of_variation(-10.0, 2.0), 0.2)

    def test_zero_stdev(self):
        self.assertEqual(_coefficient_of_variation(5.0, 0.0), 0.0)


# ---------------------------------------------------------------------------
# _drawdown_from_peak_pct
# ---------------------------------------------------------------------------

class TestDrawdownFromPeak(unittest.TestCase):
    def test_zero_peak_none(self):
        self.assertIsNone(_drawdown_from_peak_pct(0.0, 0.0))

    def test_none_inputs(self):
        self.assertIsNone(_drawdown_from_peak_pct(None, 1.0))
        self.assertIsNone(_drawdown_from_peak_pct(1.0, None))

    def test_basic(self):
        # peak 10, current 8 -> 20%
        self.assertAlmostEqual(_drawdown_from_peak_pct(10.0, 8.0), 20.0)

    def test_at_peak_zero(self):
        self.assertAlmostEqual(_drawdown_from_peak_pct(10.0, 10.0), 0.0)

    def test_above_peak_clamped_zero(self):
        self.assertEqual(_drawdown_from_peak_pct(10.0, 11.0), 0.0)

    def test_full_drawdown(self):
        self.assertAlmostEqual(_drawdown_from_peak_pct(10.0, 0.0), 100.0)


# ---------------------------------------------------------------------------
# _trend
# ---------------------------------------------------------------------------

class TestTrend(unittest.TestCase):
    def test_short_stable(self):
        self.assertEqual(_trend([5.0], 5.0), "STABLE")

    def test_empty_stable(self):
        self.assertEqual(_trend([], 0.0), "STABLE")

    def test_improving(self):
        series = [5.0, 5.0, 8.0, 8.0]
        self.assertEqual(_trend(series, _mean(series)), "IMPROVING")

    def test_decaying(self):
        series = [8.0, 8.0, 5.0, 5.0]
        self.assertEqual(_trend(series, _mean(series)), "DECAYING")

    def test_stable_within_band(self):
        series = [8.0, 8.0, 8.0, 8.0]
        self.assertEqual(_trend(series, _mean(series)), "STABLE")

    def test_small_change_stays_stable(self):
        # change well under 5% of mean
        series = [8.0, 8.0, 8.05, 8.05]
        self.assertEqual(_trend(series, _mean(series)), "STABLE")

    def test_zero_mean_improving(self):
        series = [-1.0, -1.0, 1.0, 1.0]
        self.assertEqual(_trend(series, 0.0), "IMPROVING")

    def test_zero_mean_decaying(self):
        series = [1.0, 1.0, -1.0, -1.0]
        self.assertEqual(_trend(series, 0.0), "DECAYING")


# ---------------------------------------------------------------------------
# _persistence_score
# ---------------------------------------------------------------------------

class TestPersistenceScore(unittest.TestCase):
    def test_perfect_inputs_high(self):
        score = _persistence_score(100.0, 1.0, 0.0, 0.0)
        self.assertAlmostEqual(score, 100.0)

    def test_worst_inputs_low(self):
        score = _persistence_score(0.0, -1.0, 1.0, 100.0)
        self.assertAlmostEqual(score, 0.0)

    def test_none_inputs_neutral(self):
        score = _persistence_score(None, None, None, None)
        self.assertTrue(0.0 <= score <= 100.0)

    def test_range_clamped(self):
        score = _persistence_score(200.0, 5.0, -1.0, -50.0)
        self.assertLessEqual(score, 100.0)
        self.assertGreaterEqual(score, 0.0)

    def test_high_time_above_helps(self):
        low = _persistence_score(0.0, 0.0, 0.2, 5.0)
        high = _persistence_score(100.0, 0.0, 0.2, 5.0)
        self.assertGreater(high, low)

    def test_high_cv_hurts(self):
        good = _persistence_score(80.0, 0.5, 0.0, 5.0)
        bad = _persistence_score(80.0, 0.5, 1.0, 5.0)
        self.assertGreater(good, bad)

    def test_high_drawdown_hurts(self):
        good = _persistence_score(80.0, 0.5, 0.1, 0.0)
        bad = _persistence_score(80.0, 0.5, 0.1, 80.0)
        self.assertGreater(good, bad)


# ---------------------------------------------------------------------------
# _grade
# ---------------------------------------------------------------------------

class TestGrade(unittest.TestCase):
    def test_a_at_80(self):
        self.assertEqual(_grade(80.0), "A")

    def test_a_above(self):
        self.assertEqual(_grade(95.0), "A")

    def test_b_at_65(self):
        self.assertEqual(_grade(65.0), "B")

    def test_b_just_below_80(self):
        self.assertEqual(_grade(79.9), "B")

    def test_c_at_50(self):
        self.assertEqual(_grade(50.0), "C")

    def test_d_at_35(self):
        self.assertEqual(_grade(35.0), "D")

    def test_f_below_35(self):
        self.assertEqual(_grade(34.9), "F")

    def test_none_f(self):
        self.assertEqual(_grade(None), "F")


# ---------------------------------------------------------------------------
# _classification
# ---------------------------------------------------------------------------

class TestClassification(unittest.TestCase):
    def test_sticky_at_80(self):
        self.assertEqual(_classification(80.0), "STICKY")

    def test_durable_at_65(self):
        self.assertEqual(_classification(65.0), "DURABLE")

    def test_moderate_at_50(self):
        self.assertEqual(_classification(50.0), "MODERATE")

    def test_volatile_at_35(self):
        self.assertEqual(_classification(35.0), "VOLATILE")

    def test_ephemeral_below_35(self):
        self.assertEqual(_classification(10.0), "EPHEMERAL")

    def test_none_ephemeral(self):
        self.assertEqual(_classification(None), "EPHEMERAL")


# ---------------------------------------------------------------------------
# _risk_flags
# ---------------------------------------------------------------------------

class TestRiskFlags(unittest.TestCase):
    def test_insufficient_data(self):
        flags = _risk_flags(2, 3, 0.1, 5.0, 80.0, "STABLE")
        self.assertIn("INSUFFICIENT_DATA", flags)

    def test_no_insufficient_when_enough(self):
        flags = _risk_flags(5, 3, 0.1, 5.0, 80.0, "STABLE")
        self.assertNotIn("INSUFFICIENT_DATA", flags)

    def test_high_volatility(self):
        flags = _risk_flags(5, 3, 0.6, 5.0, 80.0, "STABLE")
        self.assertIn("HIGH_VOLATILITY", flags)

    def test_high_volatility_boundary(self):
        # exactly 0.5 does not trigger (> 0.5)
        flags = _risk_flags(5, 3, 0.5, 5.0, 80.0, "STABLE")
        self.assertNotIn("HIGH_VOLATILITY", flags)

    def test_sharp_decay(self):
        flags = _risk_flags(5, 3, 0.1, 31.0, 80.0, "STABLE")
        self.assertIn("SHARP_DECAY", flags)

    def test_sharp_decay_boundary(self):
        flags = _risk_flags(5, 3, 0.1, 30.0, 80.0, "STABLE")
        self.assertNotIn("SHARP_DECAY", flags)

    def test_below_threshold_majority(self):
        flags = _risk_flags(5, 3, 0.1, 5.0, 40.0, "STABLE")
        self.assertIn("BELOW_THRESHOLD_MAJORITY", flags)

    def test_below_threshold_boundary(self):
        # exactly 50 does not trigger (< 50)
        flags = _risk_flags(5, 3, 0.1, 5.0, 50.0, "STABLE")
        self.assertNotIn("BELOW_THRESHOLD_MAJORITY", flags)

    def test_negative_trend(self):
        flags = _risk_flags(5, 3, 0.1, 5.0, 80.0, "DECAYING")
        self.assertIn("NEGATIVE_TREND", flags)

    def test_clean_no_flags(self):
        flags = _risk_flags(5, 3, 0.1, 5.0, 80.0, "IMPROVING")
        self.assertEqual(flags, [])

    def test_none_cv_no_high_vol(self):
        flags = _risk_flags(5, 3, None, 5.0, 80.0, "STABLE")
        self.assertNotIn("HIGH_VOLATILITY", flags)


# ---------------------------------------------------------------------------
# _recommendations
# ---------------------------------------------------------------------------

class TestRecommendations(unittest.TestCase):
    def test_grade_a_durable(self):
        recs = _recommendations("A", [])
        self.assertTrue(any("durable" in r for r in recs))

    def test_grade_b_durable(self):
        recs = _recommendations("B", [])
        self.assertTrue(any("durable" in r for r in recs))

    def test_grade_c_moderate(self):
        recs = _recommendations("C", [])
        self.assertTrue(any("moderate" in r for r in recs))

    def test_grade_d_weak(self):
        recs = _recommendations("D", [])
        self.assertTrue(any("weak" in r for r in recs))

    def test_grade_f_ephemeral(self):
        recs = _recommendations("F", [])
        self.assertTrue(any("ephemeral" in r for r in recs))

    def test_insufficient_rec(self):
        recs = _recommendations("F", ["INSUFFICIENT_DATA"])
        self.assertTrue(any("Insufficient history" in r for r in recs))

    def test_high_vol_rec(self):
        recs = _recommendations("C", ["HIGH_VOLATILITY"])
        self.assertTrue(any("coefficient of variation" in r for r in recs))

    def test_sharp_decay_rec(self):
        recs = _recommendations("D", ["SHARP_DECAY"])
        self.assertTrue(any("Sharp decay" in r for r in recs))

    def test_below_threshold_rec(self):
        recs = _recommendations("C", ["BELOW_THRESHOLD_MAJORITY"])
        self.assertTrue(any("below the reference threshold" in r for r in recs))

    def test_negative_trend_rec(self):
        recs = _recommendations("D", ["NEGATIVE_TREND"])
        self.assertTrue(any("Downward trend" in r for r in recs))

    def test_returns_list(self):
        self.assertIsInstance(_recommendations("A", []), list)


# ---------------------------------------------------------------------------
# analyze() — insufficient data
# ---------------------------------------------------------------------------

class TestAnalyzeInsufficient(unittest.TestCase):
    def test_empty_classification(self):
        r = analyze([])
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_empty_grade_f(self):
        self.assertEqual(analyze([])["grade"], "F")

    def test_empty_flag(self):
        self.assertEqual(analyze([])["risk_flags"], ["INSUFFICIENT_DATA"])

    def test_empty_n_zero(self):
        self.assertEqual(analyze([])["n"], 0)

    def test_empty_score_none(self):
        self.assertIsNone(analyze([])["persistence_score"])

    def test_two_points_insufficient(self):
        r = analyze([8.0, 8.1])
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_custom_min_periods(self):
        r = analyze([8.0, 8.1, 8.2], {"min_periods": 5})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_current_apy_preserved(self):
        r = analyze([8.0, 9.0])
        self.assertEqual(r["current_apy"], 9.0)

    def test_timestamp_present(self):
        self.assertIsInstance(analyze([])["timestamp"], float)


# ---------------------------------------------------------------------------
# analyze() — normal series
# ---------------------------------------------------------------------------

class TestAnalyzeNormal(unittest.TestCase):
    def setUp(self):
        self.series = [8.0, 8.1, 8.0, 7.9, 8.1, 8.2, 8.0, 7.9, 8.1, 8.0]
        self.result = analyze(self.series)

    def test_n_correct(self):
        self.assertEqual(self.result["n"], 10)

    def test_mean_correct(self):
        self.assertAlmostEqual(self.result["mean_apy"], _mean(self.series))

    def test_current_apy(self):
        self.assertEqual(self.result["current_apy"], 8.0)

    def test_peak_apy(self):
        self.assertEqual(self.result["peak_apy"], 8.2)

    def test_score_in_range(self):
        self.assertTrue(0.0 <= self.result["persistence_score"] <= 100.0)

    def test_grade_valid(self):
        self.assertIn(self.result["grade"], ("A", "B", "C", "D", "F"))

    def test_classification_valid(self):
        self.assertIn(self.result["classification"],
                      ("STICKY", "DURABLE", "MODERATE", "VOLATILE", "EPHEMERAL"))

    def test_flags_is_list(self):
        self.assertIsInstance(self.result["risk_flags"], list)

    def test_recommendations_is_list(self):
        self.assertIsInstance(self.result["recommendations"], list)

    def test_time_above_in_range(self):
        self.assertTrue(0.0 <= self.result["time_above_threshold_pct"] <= 100.0)

    def test_trend_valid(self):
        self.assertIn(self.result["trend"], ("IMPROVING", "STABLE", "DECAYING"))

    def test_top_level_keys(self):
        expected = {
            "n", "mean_apy", "current_apy", "peak_apy", "threshold",
            "time_above_threshold_pct", "lag1_autocorrelation",
            "coefficient_of_variation", "drawdown_from_peak_pct", "trend",
            "persistence_score", "grade", "classification", "risk_flags",
            "recommendations", "timestamp",
        }
        self.assertEqual(set(self.result.keys()), expected)

    def test_default_threshold_is_mean(self):
        self.assertAlmostEqual(self.result["threshold"], _mean(self.series))


# ---------------------------------------------------------------------------
# analyze() — sticky high-persistence series
# ---------------------------------------------------------------------------

class TestAnalyzeSticky(unittest.TestCase):
    def setUp(self):
        # nearly constant high APY above its own mean often / low CV
        self.result = analyze([8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0])

    def test_low_cv(self):
        self.assertEqual(self.result["coefficient_of_variation"], 0.0)

    def test_zero_drawdown(self):
        self.assertAlmostEqual(self.result["drawdown_from_peak_pct"], 0.0)

    def test_high_score(self):
        self.assertGreaterEqual(self.result["persistence_score"], 50.0)

    def test_stable_trend(self):
        self.assertEqual(self.result["trend"], "STABLE")


# ---------------------------------------------------------------------------
# analyze() — decaying / ephemeral series
# ---------------------------------------------------------------------------

class TestAnalyzeDecaying(unittest.TestCase):
    def setUp(self):
        # sharp decay from a high peak to a low current value
        self.result = analyze([20.0, 18.0, 15.0, 10.0, 6.0, 3.0, 2.0, 1.0])

    def test_negative_trend(self):
        self.assertEqual(self.result["trend"], "DECAYING")

    def test_negative_trend_flag(self):
        self.assertIn("NEGATIVE_TREND", self.result["risk_flags"])

    def test_sharp_decay_flag(self):
        self.assertIn("SHARP_DECAY", self.result["risk_flags"])

    def test_drawdown_large(self):
        self.assertGreater(self.result["drawdown_from_peak_pct"], 30.0)

    def test_lower_score(self):
        self.assertLess(self.result["persistence_score"], 80.0)


# ---------------------------------------------------------------------------
# analyze() — config handling
# ---------------------------------------------------------------------------

class TestAnalyzeConfig(unittest.TestCase):
    def test_custom_threshold(self):
        r = analyze([8.0, 8.1, 8.2, 8.3], {"threshold": 8.15})
        self.assertEqual(r["threshold"], 8.15)

    def test_threshold_affects_time_above(self):
        series = [5.0, 6.0, 7.0, 8.0]
        low = analyze(series, {"threshold": 4.0})
        high = analyze(series, {"threshold": 7.5})
        self.assertGreater(low["time_above_threshold_pct"],
                           high["time_above_threshold_pct"])

    def test_min_periods_default_three(self):
        # exactly 3 points is enough by default
        r = analyze([8.0, 8.1, 8.2])
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ---------------------------------------------------------------------------
# log_result() — ring-buffer and atomic write
# ---------------------------------------------------------------------------

class TestLogResult(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _make_result(self):
        return analyze([8.0, 8.1, 8.0, 7.9, 8.1, 8.0])

    def test_creates_log_file(self):
        log_path = os.path.join(self.tmp_dir, "apy_persistence_log.json")
        self.assertFalse(os.path.exists(log_path))
        log_result(self._make_result(), data_dir=self.tmp_dir)
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_list(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "apy_persistence_log.json")) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_snapshot_fields(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "apy_persistence_log.json")) as f:
            data = json.load(f)
        entry = data[0]
        for key in ("timestamp", "n", "mean_apy", "current_apy",
                    "persistence_score", "drawdown_from_peak_pct",
                    "grade", "classification"):
            self.assertIn(key, entry)

    def test_multiple_appends(self):
        for _ in range(5):
            log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "apy_persistence_log.json")) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_capped(self):
        for _ in range(110):
            log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "apy_persistence_log.json")) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            r = self._make_result()
            r["n"] = i
            log_result(r, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "apy_persistence_log.json")) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["n"], 104)

    def test_no_tmp_files_left(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        leftovers = [f for f in os.listdir(self.tmp_dir)
                     if f.startswith(".apy_persistence_log_") and f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_corrupted_log_recovered(self):
        log_path = os.path.join(self.tmp_dir, "apy_persistence_log.json")
        with open(log_path, "w") as f:
            f.write("not valid json{{")
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_atomic_repeated_writes(self):
        for _ in range(3):
            log_result(self._make_result(), data_dir=self.tmp_dir)
        log_path = os.path.join(self.tmp_dir, "apy_persistence_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_roundtrip_persists_grade(self):
        r = self._make_result()
        log_result(r, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "apy_persistence_log.json")) as f:
            data = json.load(f)
        self.assertEqual(data[0]["grade"], r["grade"])

    def test_insufficient_result_loggable(self):
        r = analyze([8.0])
        log_result(r, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "apy_persistence_log.json")) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
