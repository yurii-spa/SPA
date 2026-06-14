"""
MP-852 YieldCurveSteepnessAnalyzer — unit tests (>=60)
Run: python3 -m unittest spa_core.tests.test_yield_curve_steepness_analyzer -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.yield_curve_steepness_analyzer import (
    analyze,
    log_result,
    _normalize_points,
    _slope_bps_per_day,
    _term_premium_per_year,
    _is_monotonic_increasing,
    _curve_shape,
    _recommended_tenor,
    _grade,
    _risk_flags,
    _recommendations,
)


# ---------------------------------------------------------------------------
# _normalize_points
# ---------------------------------------------------------------------------

class TestNormalizePoints(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(_normalize_points([]), [])

    def test_none(self):
        self.assertEqual(_normalize_points(None), [])

    def test_list_of_dicts(self):
        pts = [{"tenor_days": 30, "apy": 5.0}, {"tenor_days": 90, "apy": 6.0}]
        self.assertEqual(_normalize_points(pts), [(30.0, 5.0), (90.0, 6.0)])

    def test_dict_mapping(self):
        out = _normalize_points({30: 5.0, 90: 6.0})
        self.assertEqual(out, [(30.0, 5.0), (90.0, 6.0)])

    def test_sorts_ascending(self):
        pts = [{"tenor_days": 90, "apy": 6.0}, {"tenor_days": 30, "apy": 5.0}]
        self.assertEqual(_normalize_points(pts), [(30.0, 5.0), (90.0, 6.0)])

    def test_skips_malformed_dict(self):
        pts = [{"tenor_days": 30, "apy": 5.0}, {"foo": 1}]
        self.assertEqual(_normalize_points(pts), [(30.0, 5.0)])

    def test_skips_unparseable_values(self):
        pts = [{"tenor_days": "x", "apy": 5.0}, {"tenor_days": 30, "apy": 6.0}]
        self.assertEqual(_normalize_points(pts), [(30.0, 6.0)])

    def test_tuple_pairs(self):
        out = _normalize_points([(30, 5.0), (90, 6.0)])
        self.assertEqual(out, [(30.0, 5.0), (90.0, 6.0)])

    def test_floats_preserved(self):
        out = _normalize_points([{"tenor_days": 30, "apy": 5.55}])
        self.assertEqual(out, [(30.0, 5.55)])


# ---------------------------------------------------------------------------
# _slope_bps_per_day
# ---------------------------------------------------------------------------

class TestSlopeBpsPerDay(unittest.TestCase):
    def test_zero_span_none(self):
        self.assertIsNone(_slope_bps_per_day(1.0, 0.0))

    def test_none_span(self):
        self.assertIsNone(_slope_bps_per_day(1.0, None))

    def test_basic(self):
        # spread 1.0 over 100 days -> 1/100*10000 = 100 bps/day
        self.assertAlmostEqual(_slope_bps_per_day(1.0, 100.0), 100.0)

    def test_negative_spread(self):
        self.assertAlmostEqual(_slope_bps_per_day(-1.0, 100.0), -100.0)

    def test_zero_spread(self):
        self.assertEqual(_slope_bps_per_day(0.0, 100.0), 0.0)


# ---------------------------------------------------------------------------
# _term_premium_per_year
# ---------------------------------------------------------------------------

class TestTermPremiumPerYear(unittest.TestCase):
    def test_zero_span_none(self):
        self.assertIsNone(_term_premium_per_year(1.0, 0.0))

    def test_none_span(self):
        self.assertIsNone(_term_premium_per_year(1.0, None))

    def test_one_year_span(self):
        # 365 day span -> divide spread by 1.0
        self.assertAlmostEqual(_term_premium_per_year(3.0, 365.0), 3.0)

    def test_half_year_span(self):
        # 182.5 day span -> spread / 0.5
        self.assertAlmostEqual(_term_premium_per_year(1.0, 182.5), 2.0)

    def test_negative_spread(self):
        self.assertAlmostEqual(_term_premium_per_year(-3.0, 365.0), -3.0)


# ---------------------------------------------------------------------------
# _is_monotonic_increasing
# ---------------------------------------------------------------------------

class TestIsMonotonic(unittest.TestCase):
    def test_empty_true(self):
        self.assertTrue(_is_monotonic_increasing([]))

    def test_single_true(self):
        self.assertTrue(_is_monotonic_increasing([(30.0, 5.0)]))

    def test_increasing(self):
        self.assertTrue(_is_monotonic_increasing([(30.0, 5.0), (90.0, 6.0)]))

    def test_flat_is_monotonic(self):
        self.assertTrue(_is_monotonic_increasing([(30.0, 5.0), (90.0, 5.0)]))

    def test_decreasing_false(self):
        self.assertFalse(_is_monotonic_increasing([(30.0, 6.0), (90.0, 5.0)]))

    def test_dip_false(self):
        pts = [(30.0, 5.0), (90.0, 6.0), (180.0, 5.5)]
        self.assertFalse(_is_monotonic_increasing(pts))


# ---------------------------------------------------------------------------
# _curve_shape
# ---------------------------------------------------------------------------

class TestCurveShape(unittest.TestCase):
    def test_none_flat(self):
        self.assertEqual(_curve_shape(None, 0.05), "FLAT")

    def test_inverted(self):
        self.assertEqual(_curve_shape(-1.0, 0.05), "INVERTED")

    def test_flat_within_eps(self):
        self.assertEqual(_curve_shape(0.02, 0.05), "FLAT")

    def test_flat_negative_within_eps(self):
        self.assertEqual(_curve_shape(-0.02, 0.05), "FLAT")

    def test_normal(self):
        self.assertEqual(_curve_shape(0.10, 0.05), "NORMAL")

    def test_steep(self):
        self.assertEqual(_curve_shape(0.50, 0.05), "STEEP")

    def test_boundary_flat_eps(self):
        # exactly eps -> FLAT (|s| <= eps)
        self.assertEqual(_curve_shape(0.05, 0.05), "FLAT")

    def test_boundary_steep(self):
        # exactly _STEEP threshold 0.30 -> NORMAL (<=)
        self.assertEqual(_curve_shape(0.30, 0.05), "NORMAL")


# ---------------------------------------------------------------------------
# _recommended_tenor
# ---------------------------------------------------------------------------

class TestRecommendedTenor(unittest.TestCase):
    def test_empty_none(self):
        self.assertIsNone(_recommended_tenor([], 0.05))

    def test_single(self):
        self.assertEqual(_recommended_tenor([(30.0, 5.0)], 0.05), 30.0)

    def test_picks_longest_when_premium_pays(self):
        pts = [(0.0, 4.0), (30.0, 4.8), (90.0, 5.6), (180.0, 6.3), (365.0, 7.1)]
        self.assertEqual(_recommended_tenor(pts, 0.05), 365.0)

    def test_falls_back_short_when_flat(self):
        pts = [(0.0, 5.0), (30.0, 5.0), (90.0, 5.0)]
        self.assertEqual(_recommended_tenor(pts, 0.05), 0.0)

    def test_stops_at_failing_step(self):
        # first step pays (4->6 over 30d), second barely moves over a long
        # span (6.0->6.001 over 275d = ~0.036 bps/day < 0.05) -> stop at 30
        pts = [(0.0, 4.0), (30.0, 6.0), (305.0, 6.001)]
        self.assertEqual(_recommended_tenor(pts, 0.05), 30.0)

    def test_inverted_recommends_short(self):
        pts = [(0.0, 7.0), (30.0, 6.0), (90.0, 5.0)]
        self.assertEqual(_recommended_tenor(pts, 0.05), 0.0)


# ---------------------------------------------------------------------------
# _grade
# ---------------------------------------------------------------------------

class TestGrade(unittest.TestCase):
    def test_inverted_f(self):
        self.assertEqual(_grade(-1.0, -1.0, "INVERTED"), "F")

    def test_none_slope_d(self):
        self.assertEqual(_grade(None, None, "FLAT"), "D")

    def test_steep_a(self):
        self.assertEqual(_grade(0.5, 2.0, "STEEP"), "A")

    def test_strong_normal_b(self):
        self.assertEqual(_grade(0.20, 1.0, "NORMAL"), "B")

    def test_mild_normal_c(self):
        self.assertEqual(_grade(0.10, 0.5, "NORMAL"), "C")

    def test_flat_d(self):
        self.assertEqual(_grade(0.02, 0.1, "FLAT"), "D")

    def test_negative_slope_f(self):
        self.assertEqual(_grade(-0.1, -0.5, "NORMAL"), "F")

    def test_zero_slope_d(self):
        self.assertEqual(_grade(0.0, 0.0, "FLAT"), "D")


# ---------------------------------------------------------------------------
# _risk_flags
# ---------------------------------------------------------------------------

class TestRiskFlags(unittest.TestCase):
    def test_insufficient_points(self):
        flags = _risk_flags(1, "FLAT", True, False)
        self.assertIn("INSUFFICIENT_POINTS", flags)

    def test_no_insufficient_when_enough(self):
        flags = _risk_flags(3, "NORMAL", True, False)
        self.assertNotIn("INSUFFICIENT_POINTS", flags)

    def test_inverted_curve(self):
        flags = _risk_flags(3, "INVERTED", True, False)
        self.assertIn("INVERTED_CURVE", flags)

    def test_non_monotonic(self):
        flags = _risk_flags(3, "NORMAL", False, False)
        self.assertIn("NON_MONOTONIC", flags)

    def test_negative_yield(self):
        flags = _risk_flags(3, "NORMAL", True, True)
        self.assertIn("NEGATIVE_YIELD", flags)

    def test_flat_no_premium(self):
        flags = _risk_flags(3, "FLAT", True, False)
        self.assertIn("FLAT_NO_PREMIUM", flags)

    def test_normal_clean(self):
        flags = _risk_flags(3, "NORMAL", True, False)
        self.assertEqual(flags, [])

    def test_steep_clean(self):
        flags = _risk_flags(5, "STEEP", True, False)
        self.assertEqual(flags, [])


# ---------------------------------------------------------------------------
# _recommendations
# ---------------------------------------------------------------------------

class TestRecommendations(unittest.TestCase):
    def test_grade_a_steep(self):
        recs = _recommendations("A", [], 365)
        self.assertTrue(any("Steep curve" in r for r in recs))

    def test_grade_b_upward(self):
        recs = _recommendations("B", [], 180)
        self.assertTrue(any("Upward curve" in r for r in recs))

    def test_grade_c_mild(self):
        recs = _recommendations("C", [], 90)
        self.assertTrue(any("Mildly upward" in r for r in recs))

    def test_grade_d_flat(self):
        recs = _recommendations("D", [], 0)
        self.assertTrue(any("Flat curve" in r for r in recs))

    def test_grade_f_inverted(self):
        recs = _recommendations("F", [], 0)
        self.assertTrue(any("Inverted curve" in r for r in recs))

    def test_recommended_tenor_included(self):
        recs = _recommendations("A", [], 365)
        self.assertTrue(any("Recommended tenor: 365" in r for r in recs))

    def test_recommended_tenor_none_omitted(self):
        recs = _recommendations("F", ["INSUFFICIENT_POINTS"], None)
        self.assertFalse(any("Recommended tenor" in r for r in recs))

    def test_insufficient_rec(self):
        recs = _recommendations("F", ["INSUFFICIENT_POINTS"], None)
        self.assertTrue(any("Insufficient points" in r for r in recs))

    def test_inverted_rec(self):
        recs = _recommendations("F", ["INVERTED_CURVE"], 0)
        self.assertTrue(any("inverted" in r for r in recs))

    def test_non_monotonic_rec(self):
        recs = _recommendations("C", ["NON_MONOTONIC"], 90)
        self.assertTrue(any("Non-monotonic" in r for r in recs))

    def test_negative_yield_rec(self):
        recs = _recommendations("C", ["NEGATIVE_YIELD"], 90)
        self.assertTrue(any("Negative yield" in r for r in recs))

    def test_flat_no_premium_rec(self):
        recs = _recommendations("D", ["FLAT_NO_PREMIUM"], 0)
        self.assertTrue(any("no meaningful term premium" in r for r in recs))

    def test_returns_list(self):
        self.assertIsInstance(_recommendations("A", [], 365), list)


# ---------------------------------------------------------------------------
# analyze() — insufficient points
# ---------------------------------------------------------------------------

class TestAnalyzeInsufficient(unittest.TestCase):
    def test_empty_flag(self):
        r = analyze([])
        self.assertIn("INSUFFICIENT_POINTS", r["risk_flags"])

    def test_empty_n_zero(self):
        self.assertEqual(analyze([])["n_points"], 0)

    def test_empty_spread_none(self):
        self.assertIsNone(analyze([])["absolute_spread"])

    def test_empty_slope_none(self):
        self.assertIsNone(analyze([])["slope_bps_per_day"])

    def test_single_point_flag(self):
        r = analyze([{"tenor_days": 30, "apy": 5.0}])
        self.assertIn("INSUFFICIENT_POINTS", r["risk_flags"])

    def test_single_point_n(self):
        r = analyze([{"tenor_days": 30, "apy": 5.0}])
        self.assertEqual(r["n_points"], 1)

    def test_single_recommended_tenor(self):
        r = analyze([{"tenor_days": 30, "apy": 5.0}])
        self.assertEqual(r["recommended_tenor"], 30.0)

    def test_single_short_apy(self):
        r = analyze([{"tenor_days": 30, "apy": 5.0}])
        self.assertEqual(r["short_apy"], 5.0)

    def test_timestamp_present(self):
        self.assertIsInstance(analyze([])["timestamp"], float)


# ---------------------------------------------------------------------------
# analyze() — normal upward curve
# ---------------------------------------------------------------------------

class TestAnalyzeNormalCurve(unittest.TestCase):
    def setUp(self):
        self.points = [
            {"tenor_days": 0, "apy": 4.0},
            {"tenor_days": 30, "apy": 4.8},
            {"tenor_days": 90, "apy": 5.6},
            {"tenor_days": 180, "apy": 6.3},
            {"tenor_days": 365, "apy": 7.1},
        ]
        self.result = analyze(self.points)

    def test_n_points(self):
        self.assertEqual(self.result["n_points"], 5)

    def test_short_tenor(self):
        self.assertEqual(self.result["short_tenor"], 0.0)

    def test_long_tenor(self):
        self.assertEqual(self.result["long_tenor"], 365.0)

    def test_spread_positive(self):
        self.assertAlmostEqual(self.result["absolute_spread"], 3.1)

    def test_slope_positive(self):
        self.assertGreater(self.result["slope_bps_per_day"], 0.0)

    def test_term_premium_positive(self):
        self.assertGreater(self.result["term_premium_per_year"], 0.0)

    def test_monotonic(self):
        self.assertTrue(self.result["is_monotonic_increasing"])

    def test_shape_valid(self):
        self.assertIn(self.result["curve_shape"],
                      ("INVERTED", "FLAT", "NORMAL", "STEEP"))

    def test_classification_matches_shape(self):
        self.assertEqual(self.result["classification"], self.result["curve_shape"])

    def test_recommended_longest(self):
        self.assertEqual(self.result["recommended_tenor"], 365.0)

    def test_grade_valid(self):
        self.assertIn(self.result["grade"], ("A", "B", "C", "D", "F"))

    def test_flags_is_list(self):
        self.assertIsInstance(self.result["risk_flags"], list)

    def test_recommendations_is_list(self):
        self.assertIsInstance(self.result["recommendations"], list)

    def test_top_level_keys(self):
        expected = {
            "n_points", "short_tenor", "short_apy", "long_tenor", "long_apy",
            "absolute_spread", "slope_bps_per_day", "term_premium_per_year",
            "is_monotonic_increasing", "curve_shape", "recommended_tenor",
            "grade", "classification", "risk_flags", "recommendations",
            "timestamp",
        }
        self.assertEqual(set(self.result.keys()), expected)


# ---------------------------------------------------------------------------
# analyze() — inverted curve
# ---------------------------------------------------------------------------

class TestAnalyzeInverted(unittest.TestCase):
    def setUp(self):
        self.points = [
            {"tenor_days": 0, "apy": 8.0},
            {"tenor_days": 90, "apy": 6.0},
            {"tenor_days": 365, "apy": 4.0},
        ]
        self.result = analyze(self.points)

    def test_shape_inverted(self):
        self.assertEqual(self.result["curve_shape"], "INVERTED")

    def test_inverted_flag(self):
        self.assertIn("INVERTED_CURVE", self.result["risk_flags"])

    def test_negative_spread(self):
        self.assertLess(self.result["absolute_spread"], 0.0)

    def test_grade_f(self):
        self.assertEqual(self.result["grade"], "F")

    def test_recommended_short(self):
        self.assertEqual(self.result["recommended_tenor"], 0.0)

    def test_negative_slope(self):
        self.assertLess(self.result["slope_bps_per_day"], 0.0)


# ---------------------------------------------------------------------------
# analyze() — flat curve
# ---------------------------------------------------------------------------

class TestAnalyzeFlat(unittest.TestCase):
    def setUp(self):
        self.points = [
            {"tenor_days": 0, "apy": 5.0},
            {"tenor_days": 90, "apy": 5.0},
            {"tenor_days": 365, "apy": 5.0},
        ]
        self.result = analyze(self.points)

    def test_shape_flat(self):
        self.assertEqual(self.result["curve_shape"], "FLAT")

    def test_flat_no_premium_flag(self):
        self.assertIn("FLAT_NO_PREMIUM", self.result["risk_flags"])

    def test_zero_spread(self):
        self.assertAlmostEqual(self.result["absolute_spread"], 0.0)

    def test_recommended_short(self):
        self.assertEqual(self.result["recommended_tenor"], 0.0)


# ---------------------------------------------------------------------------
# analyze() — non-monotonic and negative yield
# ---------------------------------------------------------------------------

class TestAnalyzeEdgeShapes(unittest.TestCase):
    def test_non_monotonic_flag(self):
        points = [
            {"tenor_days": 0, "apy": 4.0},
            {"tenor_days": 90, "apy": 7.0},
            {"tenor_days": 365, "apy": 5.0},
        ]
        r = analyze(points)
        self.assertIn("NON_MONOTONIC", r["risk_flags"])

    def test_negative_yield_flag(self):
        points = [
            {"tenor_days": 0, "apy": -1.0},
            {"tenor_days": 365, "apy": 3.0},
        ]
        r = analyze(points)
        self.assertIn("NEGATIVE_YIELD", r["risk_flags"])

    def test_dict_input_supported(self):
        r = analyze({0: 4.0, 365: 7.0})
        self.assertEqual(r["n_points"], 2)
        self.assertAlmostEqual(r["absolute_spread"], 3.0)

    def test_steep_curve(self):
        points = [{"tenor_days": 0, "apy": 4.0}, {"tenor_days": 30, "apy": 8.0}]
        r = analyze(points)
        self.assertEqual(r["curve_shape"], "STEEP")


# ---------------------------------------------------------------------------
# analyze() — config handling
# ---------------------------------------------------------------------------

class TestAnalyzeConfig(unittest.TestCase):
    def test_custom_flat_eps_makes_flat(self):
        points = [{"tenor_days": 0, "apy": 5.0}, {"tenor_days": 100, "apy": 5.5}]
        # slope = 0.5/100*10000 = 50 bps/day; huge eps -> FLAT
        r = analyze(points, {"flat_eps_bps_per_day": 1000.0})
        self.assertEqual(r["curve_shape"], "FLAT")

    def test_custom_min_marginal_high_falls_back(self):
        points = [
            {"tenor_days": 0, "apy": 4.0},
            {"tenor_days": 30, "apy": 4.8},
            {"tenor_days": 90, "apy": 5.6},
        ]
        # require an absurdly high marginal -> fall back to shortest
        r = analyze(points, {"min_marginal_bps_per_day": 9999.0})
        self.assertEqual(r["recommended_tenor"], 0.0)


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
        return analyze([
            {"tenor_days": 0, "apy": 4.0},
            {"tenor_days": 90, "apy": 5.6},
            {"tenor_days": 365, "apy": 7.1},
        ])

    def test_creates_log_file(self):
        log_path = os.path.join(self.tmp_dir, "yield_curve_steepness_log.json")
        self.assertFalse(os.path.exists(log_path))
        log_result(self._make_result(), data_dir=self.tmp_dir)
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_list(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "yield_curve_steepness_log.json")) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_snapshot_fields(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "yield_curve_steepness_log.json")) as f:
            data = json.load(f)
        entry = data[0]
        for key in ("timestamp", "n_points", "absolute_spread",
                    "slope_bps_per_day", "term_premium_per_year",
                    "curve_shape", "recommended_tenor", "grade"):
            self.assertIn(key, entry)

    def test_multiple_appends(self):
        for _ in range(5):
            log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "yield_curve_steepness_log.json")) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_capped(self):
        for _ in range(110):
            log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "yield_curve_steepness_log.json")) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            r = self._make_result()
            r["n_points"] = i
            log_result(r, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "yield_curve_steepness_log.json")) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["n_points"], 104)

    def test_no_tmp_files_left(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        leftovers = [f for f in os.listdir(self.tmp_dir)
                     if f.startswith(".yield_curve_steepness_log_") and f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_corrupted_log_recovered(self):
        log_path = os.path.join(self.tmp_dir, "yield_curve_steepness_log.json")
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
        log_path = os.path.join(self.tmp_dir, "yield_curve_steepness_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_roundtrip_persists_shape(self):
        r = self._make_result()
        log_result(r, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "yield_curve_steepness_log.json")) as f:
            data = json.load(f)
        self.assertEqual(data[0]["curve_shape"], r["curve_shape"])

    def test_insufficient_result_loggable(self):
        r = analyze([])
        log_result(r, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "yield_curve_steepness_log.json")) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
