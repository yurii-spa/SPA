"""
MP-835 SortinoRatioCalculator — unit tests (>=60)
Run: python3 -m unittest spa_core.tests.test_sortino_ratio_calculator -v
"""

import json
import math
import os
import tempfile
import unittest

from spa_core.analytics.sortino_ratio_calculator import (
    analyze,
    log_result,
    _mean,
    _stdev,
    _downside_deviation,
    _sortino,
    _sharpe,
    _annualize,
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
        self.assertEqual(_mean([0.5]), 0.5)

    def test_basic(self):
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0]), 2.0)

    def test_negatives(self):
        self.assertAlmostEqual(_mean([-1.0, 1.0]), 0.0)

    def test_fractional(self):
        self.assertAlmostEqual(_mean([0.001, 0.003]), 0.002)

    def test_all_zero(self):
        self.assertEqual(_mean([0.0, 0.0, 0.0]), 0.0)


# ---------------------------------------------------------------------------
# _stdev
# ---------------------------------------------------------------------------

class TestStdev(unittest.TestCase):
    def test_empty_zero(self):
        self.assertEqual(_stdev([]), 0.0)

    def test_single_zero(self):
        self.assertEqual(_stdev([0.5]), 0.0)

    def test_constant_zero(self):
        self.assertEqual(_stdev([2.0, 2.0, 2.0]), 0.0)

    def test_known_value(self):
        # sample stdev of [1,2,3,4,5] = sqrt(2.5)
        self.assertAlmostEqual(_stdev([1, 2, 3, 4, 5]), math.sqrt(2.5))

    def test_two_points(self):
        # sample stdev of [0,2] = sqrt(((0-1)^2+(2-1)^2)/1)= sqrt(2)
        self.assertAlmostEqual(_stdev([0.0, 2.0]), math.sqrt(2.0))

    def test_positive(self):
        self.assertGreater(_stdev([0.01, -0.02, 0.03]), 0.0)


# ---------------------------------------------------------------------------
# _downside_deviation
# ---------------------------------------------------------------------------

class TestDownsideDeviation(unittest.TestCase):
    def test_empty_zero(self):
        self.assertEqual(_downside_deviation([], 0.0), 0.0)

    def test_no_downside_returns_zero(self):
        # all above target
        self.assertEqual(_downside_deviation([0.01, 0.02, 0.03], 0.0), 0.0)

    def test_all_below_target(self):
        # [-0.02,-0.02] target 0 -> sqrt(mean(0.0004,0.0004))=0.02
        self.assertAlmostEqual(_downside_deviation([-0.02, -0.02], 0.0), 0.02)

    def test_mixed_uses_all_n(self):
        # [-0.02, 0.02] target 0 -> only neg counts: sqrt((0.0004+0)/2)
        expected = math.sqrt(0.0004 / 2)
        self.assertAlmostEqual(_downside_deviation([-0.02, 0.02], 0.0), expected)

    def test_target_shifts_downside(self):
        # target 0.01: 0.005 is below -> diff -0.005
        dd = _downside_deviation([0.005, 0.02], 0.01)
        expected = math.sqrt((0.005 ** 2 + 0) / 2)
        self.assertAlmostEqual(dd, expected)

    def test_exactly_at_target_not_downside(self):
        # r == target -> diff 0, not counted
        self.assertEqual(_downside_deviation([0.0, 0.0], 0.0), 0.0)

    def test_constant_above_zero(self):
        self.assertEqual(_downside_deviation([0.05, 0.05, 0.05], 0.0), 0.0)


# ---------------------------------------------------------------------------
# _sortino
# ---------------------------------------------------------------------------

class TestSortino(unittest.TestCase):
    def test_none_dd(self):
        self.assertIsNone(_sortino(0.01, 0.0, None))

    def test_zero_dd(self):
        self.assertIsNone(_sortino(0.01, 0.0, 0.0))

    def test_basic(self):
        # (0.02 - 0.0)/0.01 = 2.0
        self.assertAlmostEqual(_sortino(0.02, 0.0, 0.01), 2.0)

    def test_with_target(self):
        # (0.02 - 0.01)/0.01 = 1.0
        self.assertAlmostEqual(_sortino(0.02, 0.01, 0.01), 1.0)

    def test_negative_excess(self):
        self.assertAlmostEqual(_sortino(-0.01, 0.0, 0.01), -1.0)

    def test_tiny_dd_treated_zero(self):
        self.assertIsNone(_sortino(0.01, 0.0, 1e-15))


# ---------------------------------------------------------------------------
# _sharpe
# ---------------------------------------------------------------------------

class TestSharpe(unittest.TestCase):
    def test_none_stdev(self):
        self.assertIsNone(_sharpe(0.01, 0.0, None))

    def test_zero_stdev(self):
        self.assertIsNone(_sharpe(0.01, 0.0, 0.0))

    def test_basic(self):
        self.assertAlmostEqual(_sharpe(0.02, 0.0, 0.01), 2.0)

    def test_with_risk_free(self):
        self.assertAlmostEqual(_sharpe(0.02, 0.01, 0.01), 1.0)

    def test_negative(self):
        self.assertAlmostEqual(_sharpe(-0.01, 0.0, 0.02), -0.5)


# ---------------------------------------------------------------------------
# _annualize
# ---------------------------------------------------------------------------

class TestAnnualize(unittest.TestCase):
    def test_none_value(self):
        self.assertIsNone(_annualize(None, 365))

    def test_zero_periods(self):
        self.assertIsNone(_annualize(1.0, 0))

    def test_negative_periods(self):
        self.assertIsNone(_annualize(1.0, -5))

    def test_basic_365(self):
        self.assertAlmostEqual(_annualize(1.0, 365), math.sqrt(365))

    def test_basic_one(self):
        self.assertAlmostEqual(_annualize(2.0, 1), 2.0)

    def test_negative_value(self):
        self.assertAlmostEqual(_annualize(-1.0, 4), -2.0)

    def test_monthly(self):
        self.assertAlmostEqual(_annualize(1.0, 12), math.sqrt(12))


# ---------------------------------------------------------------------------
# _grade
# ---------------------------------------------------------------------------

class TestGrade(unittest.TestCase):
    def test_a_at_3(self):
        self.assertEqual(_grade(3.0, []), "A")

    def test_a_above_3(self):
        self.assertEqual(_grade(5.0, []), "A")

    def test_b_at_2(self):
        self.assertEqual(_grade(2.0, []), "B")

    def test_b_just_below_3(self):
        self.assertEqual(_grade(2.99, []), "B")

    def test_c_at_1(self):
        self.assertEqual(_grade(1.0, []), "C")

    def test_d_at_0(self):
        self.assertEqual(_grade(0.0, []), "D")

    def test_d_just_below_1(self):
        self.assertEqual(_grade(0.99, []), "D")

    def test_f_negative(self):
        self.assertEqual(_grade(-0.5, []), "F")

    def test_none_default_f(self):
        self.assertEqual(_grade(None, []), "F")

    def test_none_no_downside_positive_a(self):
        self.assertEqual(_grade(None, ["NO_DOWNSIDE"]), "A")

    def test_none_no_downside_negative_f(self):
        self.assertEqual(_grade(None, ["NO_DOWNSIDE", "NEGATIVE_RETURN"]), "F")


# ---------------------------------------------------------------------------
# _classification
# ---------------------------------------------------------------------------

class TestClassification(unittest.TestCase):
    def test_excellent_at_2(self):
        self.assertEqual(_classification(2.0, 0.01), "EXCELLENT")

    def test_good_at_1(self):
        self.assertEqual(_classification(1.0, 0.01), "GOOD")

    def test_adequate_at_0(self):
        self.assertEqual(_classification(0.0, 0.01), "ADEQUATE")

    def test_poor_negative_sortino_pos_mean(self):
        self.assertEqual(_classification(-0.5, 0.01), "POOR")

    def test_negative_negative_mean(self):
        self.assertEqual(_classification(-0.5, -0.01), "NEGATIVE")

    def test_none_sortino_pos_mean_excellent(self):
        self.assertEqual(_classification(None, 0.01), "EXCELLENT")

    def test_none_sortino_neg_mean_negative(self):
        self.assertEqual(_classification(None, -0.01), "NEGATIVE")

    def test_none_sortino_zero_mean_excellent(self):
        self.assertEqual(_classification(None, 0.0), "EXCELLENT")


# ---------------------------------------------------------------------------
# _risk_flags
# ---------------------------------------------------------------------------

class TestRiskFlags(unittest.TestCase):
    def test_negative_return_flagged(self):
        flags = _risk_flags(-0.01, 0.02, 0.10)
        self.assertIn("NEGATIVE_RETURN", flags)

    def test_no_negative_when_positive(self):
        flags = _risk_flags(0.01, 0.02, 0.10)
        self.assertNotIn("NEGATIVE_RETURN", flags)

    def test_no_downside_when_zero_dd(self):
        flags = _risk_flags(0.01, 0.0, 0.0)
        self.assertIn("NO_DOWNSIDE", flags)

    def test_no_downside_when_none_dd(self):
        flags = _risk_flags(0.01, None, None)
        self.assertIn("NO_DOWNSIDE", flags)

    def test_no_downside_absent_when_dd_present(self):
        flags = _risk_flags(0.01, 0.02, 0.10)
        self.assertNotIn("NO_DOWNSIDE", flags)

    def test_high_downside_vol_flagged(self):
        flags = _risk_flags(0.01, 0.05, 0.25)
        self.assertIn("HIGH_DOWNSIDE_VOL", flags)

    def test_high_downside_vol_boundary(self):
        # exactly 0.20 does not trigger (> 0.20)
        flags = _risk_flags(0.01, 0.05, 0.20)
        self.assertNotIn("HIGH_DOWNSIDE_VOL", flags)

    def test_high_downside_vol_just_above(self):
        flags = _risk_flags(0.01, 0.05, 0.2001)
        self.assertIn("HIGH_DOWNSIDE_VOL", flags)

    def test_clean_no_flags(self):
        flags = _risk_flags(0.01, 0.05, 0.10)
        self.assertEqual(flags, [])


# ---------------------------------------------------------------------------
# _recommendations
# ---------------------------------------------------------------------------

class TestRecommendations(unittest.TestCase):
    def test_grade_a_strong(self):
        recs = _recommendations("A", [], 3.0)
        self.assertTrue(any("Strong" in r for r in recs))

    def test_grade_b_strong(self):
        recs = _recommendations("B", [], 2.0)
        self.assertTrue(any("Strong" in r for r in recs))

    def test_grade_c_adequate(self):
        recs = _recommendations("C", [], 1.0)
        self.assertTrue(any("Adequate" in r for r in recs))

    def test_grade_d_marginal(self):
        recs = _recommendations("D", [], 0.5)
        self.assertTrue(any("Marginal" in r for r in recs))

    def test_grade_f_weak(self):
        recs = _recommendations("F", [], -1.0)
        self.assertTrue(any("Weak" in r for r in recs))

    def test_negative_return_rec(self):
        recs = _recommendations("F", ["NEGATIVE_RETURN"], -1.0)
        self.assertTrue(any("losing capital" in r for r in recs))

    def test_high_downside_rec(self):
        recs = _recommendations("D", ["HIGH_DOWNSIDE_VOL"], 0.5)
        self.assertTrue(any("downside volatility" in r for r in recs))

    def test_no_downside_rec(self):
        recs = _recommendations("A", ["NO_DOWNSIDE"], None)
        self.assertTrue(any("No returns fell below target" in r for r in recs))

    def test_returns_list(self):
        self.assertIsInstance(_recommendations("A", [], 3.0), list)


# ---------------------------------------------------------------------------
# analyze() — insufficient data
# ---------------------------------------------------------------------------

class TestAnalyzeInsufficient(unittest.TestCase):
    def test_empty_grade_f(self):
        r = analyze([])
        self.assertEqual(r["grade"], "F")

    def test_empty_classification(self):
        r = analyze([])
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_empty_dd_none(self):
        r = analyze([])
        self.assertIsNone(r["downside_deviation"])

    def test_empty_sortino_none(self):
        r = analyze([])
        self.assertIsNone(r["sortino_ratio"])

    def test_empty_n_zero(self):
        self.assertEqual(analyze([])["n"], 0)

    def test_single_n_one(self):
        self.assertEqual(analyze([0.01])["n"], 1)

    def test_single_insufficient(self):
        r = analyze([0.01])
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIsNone(r["sortino_ratio"])

    def test_single_mean_preserved(self):
        r = analyze([0.05])
        self.assertAlmostEqual(r["mean_return"], 0.05)

    def test_timestamp_present(self):
        self.assertIsInstance(analyze([])["timestamp"], float)


# ---------------------------------------------------------------------------
# analyze() — normal multi-return series
# ---------------------------------------------------------------------------

class TestAnalyzeNormal(unittest.TestCase):
    def setUp(self):
        self.returns = [0.002, -0.001, 0.003, 0.001, -0.0005, 0.0025]
        self.result = analyze(self.returns)

    def test_n_correct(self):
        self.assertEqual(self.result["n"], 6)

    def test_mean_correct(self):
        self.assertAlmostEqual(self.result["mean_return"], _mean(self.returns))

    def test_dd_positive(self):
        self.assertGreater(self.result["downside_deviation"], 0.0)

    def test_sortino_present(self):
        self.assertIsNotNone(self.result["sortino_ratio"])

    def test_annualized_present(self):
        self.assertIsNotNone(self.result["annualized_sortino"])

    def test_sharpe_present(self):
        self.assertIsNotNone(self.result["sharpe_ratio"])

    def test_grade_valid(self):
        self.assertIn(self.result["grade"], ("A", "B", "C", "D", "F"))

    def test_classification_valid(self):
        self.assertIn(self.result["classification"],
                      ("EXCELLENT", "GOOD", "ADEQUATE", "POOR", "NEGATIVE"))

    def test_flags_is_list(self):
        self.assertIsInstance(self.result["risk_flags"], list)

    def test_recommendations_is_list(self):
        self.assertIsInstance(self.result["recommendations"], list)

    def test_top_level_keys(self):
        expected = {
            "mean_return", "target_return", "downside_deviation",
            "sortino_ratio", "annualized_sortino", "stdev", "sharpe_ratio",
            "annualized_sharpe", "n", "grade", "classification",
            "risk_flags", "recommendations", "timestamp",
        }
        self.assertEqual(set(self.result.keys()), expected)

    def test_annualized_larger_magnitude(self):
        # sqrt(365) >> 1, so annualized magnitude exceeds periodic
        self.assertGreater(abs(self.result["annualized_sortino"]),
                           abs(self.result["sortino_ratio"]))


# ---------------------------------------------------------------------------
# analyze() — NO_DOWNSIDE case
# ---------------------------------------------------------------------------

class TestAnalyzeNoDownside(unittest.TestCase):
    def setUp(self):
        # all returns above target 0 -> no downside
        self.result = analyze([0.01, 0.02, 0.015, 0.03])

    def test_dd_zero(self):
        self.assertEqual(self.result["downside_deviation"], 0.0)

    def test_sortino_none(self):
        self.assertIsNone(self.result["sortino_ratio"])

    def test_no_downside_flag(self):
        self.assertIn("NO_DOWNSIDE", self.result["risk_flags"])

    def test_grade_a(self):
        self.assertEqual(self.result["grade"], "A")

    def test_classification_excellent(self):
        self.assertEqual(self.result["classification"], "EXCELLENT")

    def test_no_negative_flag(self):
        self.assertNotIn("NEGATIVE_RETURN", self.result["risk_flags"])


# ---------------------------------------------------------------------------
# analyze() — negative mean series
# ---------------------------------------------------------------------------

class TestAnalyzeNegative(unittest.TestCase):
    def setUp(self):
        self.result = analyze([-0.01, -0.02, -0.005, -0.015])

    def test_negative_return_flag(self):
        self.assertIn("NEGATIVE_RETURN", self.result["risk_flags"])

    def test_classification_negative(self):
        self.assertEqual(self.result["classification"], "NEGATIVE")

    def test_grade_f(self):
        self.assertEqual(self.result["grade"], "F")

    def test_sortino_negative(self):
        self.assertLess(self.result["sortino_ratio"], 0.0)


# ---------------------------------------------------------------------------
# analyze() — config handling
# ---------------------------------------------------------------------------

class TestAnalyzeConfig(unittest.TestCase):
    def test_no_annualize(self):
        r = analyze([0.002, -0.001, 0.003, 0.001], {"annualize": False})
        self.assertEqual(r["annualized_sortino"], r["sortino_ratio"])

    def test_target_return_passthrough(self):
        r = analyze([0.002, 0.001], {"target_return": 0.005})
        self.assertAlmostEqual(r["target_return"], 0.005)

    def test_periods_per_year_affects_annualization(self):
        rets = [0.002, -0.001, 0.003, 0.001]
        r12 = analyze(rets, {"periods_per_year": 12})
        r365 = analyze(rets, {"periods_per_year": 365})
        self.assertNotAlmostEqual(r12["annualized_sortino"], r365["annualized_sortino"])

    def test_risk_free_affects_sharpe(self):
        rets = [0.002, -0.001, 0.003, 0.001]
        r0 = analyze(rets, {"risk_free": 0.0})
        r1 = analyze(rets, {"risk_free": 0.001})
        self.assertGreater(r0["sharpe_ratio"], r1["sharpe_ratio"])

    def test_high_target_creates_downside(self):
        # raising target above all returns makes all of them downside
        r = analyze([0.001, 0.002], {"target_return": 0.01})
        self.assertGreater(r["downside_deviation"], 0.0)


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
        return analyze([0.002, -0.001, 0.003, 0.001])

    def test_creates_log_file(self):
        log_path = os.path.join(self.tmp_dir, "sortino_ratio_log.json")
        self.assertFalse(os.path.exists(log_path))
        log_result(self._make_result(), data_dir=self.tmp_dir)
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_list(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "sortino_ratio_log.json")) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_snapshot_fields(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "sortino_ratio_log.json")) as f:
            data = json.load(f)
        entry = data[0]
        for key in ("timestamp", "n", "mean_return", "downside_deviation",
                    "sortino_ratio", "annualized_sortino", "grade"):
            self.assertIn(key, entry)

    def test_multiple_appends(self):
        for _ in range(5):
            log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "sortino_ratio_log.json")) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_capped_at_100(self):
        for _ in range(110):
            log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "sortino_ratio_log.json")) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            r = self._make_result()
            r["n"] = i
            log_result(r, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "sortino_ratio_log.json")) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["n"], 104)

    def test_no_tmp_files_left(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        leftovers = [f for f in os.listdir(self.tmp_dir)
                     if f.startswith(".sortino_ratio_log_") and f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_corrupted_log_recovered(self):
        log_path = os.path.join(self.tmp_dir, "sortino_ratio_log.json")
        with open(log_path, "w") as f:
            f.write("not valid json{{")
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_roundtrip_persists_grade(self):
        r = self._make_result()
        log_result(r, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "sortino_ratio_log.json")) as f:
            data = json.load(f)
        self.assertEqual(data[0]["grade"], r["grade"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
