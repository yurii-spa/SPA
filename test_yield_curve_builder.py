"""
Tests for MP-645: YieldCurveBuilder  (≥60 tests)
Pure stdlib unittest — no pytest dependency.
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from spa_core.analytics.yield_curve_builder import (
    CurvePoint,
    YieldCurveBuilder,
    YieldCurveSnapshot,
    MAX_ENTRIES,
)

EPS = 1e-9  # float equality tolerance


def _pt(adapter_id, lock_days, apy, tier="T1", is_liquid=None):
    if is_liquid is None:
        is_liquid = lock_days == 0
    return CurvePoint(
        adapter_id=adapter_id,
        protocol=f"Proto-{adapter_id}",
        lock_days=lock_days,
        apy=apy,
        tier=tier,
        is_liquid=is_liquid,
    )


def _builder(data_file=None):
    if data_file is None:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        data_file = Path(path)
    return YieldCurveBuilder(data_file=data_file)


def _approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ===========================================================================
# 1. _apy_at_lock
# ===========================================================================

class TestApyAtLock(unittest.TestCase):

    def setUp(self):
        self.b = _builder()

    def test_exact_match_0(self):
        pts = [_pt("a", 0, 0.04), _pt("b", 30, 0.07)]
        self.assertAlmostEqual(self.b._apy_at_lock(pts, 0), 0.04, places=9)

    def test_exact_match_30(self):
        pts = [_pt("a", 0, 0.04), _pt("b", 30, 0.07)]
        self.assertAlmostEqual(self.b._apy_at_lock(pts, 30), 0.07, places=9)

    def test_exact_match_90(self):
        pts = [_pt("a", 90, 0.09)]
        self.assertAlmostEqual(self.b._apy_at_lock(pts, 90), 0.09, places=9)

    def test_exact_match_multiple_same_lock_returns_max(self):
        pts = [_pt("a", 30, 0.06), _pt("b", 30, 0.08)]
        self.assertAlmostEqual(self.b._apy_at_lock(pts, 30), 0.08, places=9)

    def test_nearest_fallback_below(self):
        pts = [_pt("a", 0, 0.03), _pt("b", 7, 0.05)]
        self.assertAlmostEqual(self.b._apy_at_lock(pts, 30), 0.05, places=9)

    def test_nearest_fallback_above(self):
        pts = [_pt("a", 7, 0.05), _pt("b", 90, 0.09)]
        self.assertAlmostEqual(self.b._apy_at_lock(pts, 0), 0.05, places=9)

    def test_nearest_between_two_equidistant(self):
        pts = [_pt("a", 0, 0.04), _pt("b", 30, 0.08)]
        result = self.b._apy_at_lock(pts, 15)
        self.assertIn(round(result, 9), [round(0.04, 9), round(0.08, 9)])

    def test_empty_list_returns_zero(self):
        self.assertEqual(self.b._apy_at_lock([], 30), 0.0)

    def test_single_point_any_target_0(self):
        pts = [_pt("a", 180, 0.12)]
        self.assertAlmostEqual(self.b._apy_at_lock(pts, 0), 0.12, places=9)

    def test_single_point_any_target_90(self):
        pts = [_pt("a", 180, 0.12)]
        self.assertAlmostEqual(self.b._apy_at_lock(pts, 90), 0.12, places=9)

    def test_exact_90_multiple_picks_max(self):
        pts = [_pt("a", 90, 0.07), _pt("b", 90, 0.10)]
        self.assertAlmostEqual(self.b._apy_at_lock(pts, 90), 0.10, places=9)


# ===========================================================================
# 2. _classify_shape
# ===========================================================================

class TestClassifyShape(unittest.TestCase):

    def setUp(self):
        self.b = _builder()
        self.pts = [_pt("a", 0, 0.05)]

    def test_flat_both_zero(self):
        self.assertEqual(self.b._classify_shape(0.0, 0.0, self.pts), "FLAT")

    def test_flat_both_within_threshold(self):
        self.assertEqual(self.b._classify_shape(3.0, 2.0, self.pts), "FLAT")

    def test_flat_negative_within_threshold(self):
        self.assertEqual(self.b._classify_shape(-4.0, -4.9, self.pts), "FLAT")

    def test_normal_positive_slope_0_30(self):
        self.assertEqual(self.b._classify_shape(10.0, 0.0, self.pts), "NORMAL")

    def test_normal_positive_slope_30_90(self):
        self.assertEqual(self.b._classify_shape(0.0, 10.0, self.pts), "NORMAL")

    def test_normal_both_positive(self):
        self.assertEqual(self.b._classify_shape(20.0, 15.0, self.pts), "NORMAL")

    def test_inverted_both_negative(self):
        self.assertEqual(self.b._classify_shape(-10.0, -10.0, self.pts), "INVERTED")

    def test_inverted_slope_0_30_negative_slope_30_90_flat(self):
        self.assertEqual(self.b._classify_shape(-10.0, 2.0, self.pts), "INVERTED")

    def test_humped_up_then_down(self):
        self.assertEqual(self.b._classify_shape(20.0, -15.0, self.pts), "HUMPED")

    def test_humped_large_up_large_down(self):
        self.assertEqual(self.b._classify_shape(100.0, -100.0, self.pts), "HUMPED")

    def test_boundary_exactly_5bps_not_flat(self):
        shape = self.b._classify_shape(5.0, 0.0, self.pts)
        self.assertNotEqual(shape, "FLAT")

    def test_boundary_exactly_negative_5bps_inverted(self):
        shape = self.b._classify_shape(-5.0, -5.0, self.pts)
        self.assertEqual(shape, "INVERTED")


# ===========================================================================
# 3. build_curve — general
# ===========================================================================

class TestBuildCurveGeneral(unittest.TestCase):

    def setUp(self):
        self.b = _builder()

    def test_empty_input_returns_flat(self):
        snap = self.b.build_curve([])
        self.assertEqual(snap.curve_shape, "FLAT")

    def test_empty_input_zeros(self):
        snap = self.b.build_curve([])
        self.assertEqual(snap.slope_0_30, 0.0)
        self.assertEqual(snap.slope_30_90, 0.0)
        self.assertEqual(snap.best_liquid_apy, 0.0)
        self.assertEqual(snap.best_overall_apy, 0.0)
        self.assertEqual(snap.optimal_point, "none")

    def test_empty_points_list(self):
        snap = self.b.build_curve([])
        self.assertEqual(snap.points, [])

    def test_empty_timestamp_is_recent(self):
        snap = self.b.build_curve([])
        self.assertLess(abs(snap.timestamp - time.time()), 5.0)

    def test_single_point_is_optimal(self):
        snap = self.b.build_curve([_pt("solo", 0, 0.06)])
        self.assertEqual(snap.optimal_point, "solo")

    def test_single_point_curve_flat(self):
        snap = self.b.build_curve([_pt("solo", 0, 0.06)])
        self.assertEqual(snap.curve_shape, "FLAT")

    def test_points_sorted_by_lock_days_ascending(self):
        pts = [_pt("c", 90, 0.09), _pt("a", 0, 0.04), _pt("b", 30, 0.07)]
        snap = self.b.build_curve(pts)
        locks = [p.lock_days for p in snap.points]
        self.assertEqual(locks, sorted(locks))

    def test_points_tie_break_higher_apy_first(self):
        pts = [_pt("x", 30, 0.06), _pt("y", 30, 0.09)]
        snap = self.b.build_curve(pts)
        self.assertEqual(snap.points[0].adapter_id, "y")

    def test_timestamp_is_float(self):
        snap = self.b.build_curve([_pt("a", 0, 0.05)])
        self.assertIsInstance(snap.timestamp, float)


# ===========================================================================
# 4. best_liquid_apy & best_overall_apy
# ===========================================================================

class TestBestApys(unittest.TestCase):

    def setUp(self):
        self.b = _builder()

    def test_best_liquid_only_considers_is_liquid_true(self):
        pts = [_pt("liquid1", 0, 0.04, is_liquid=True),
               _pt("locked1", 30, 0.10, is_liquid=False)]
        snap = self.b.build_curve(pts)
        self.assertAlmostEqual(snap.best_liquid_apy, 0.04, places=6)

    def test_best_liquid_zero_when_no_liquid(self):
        pts = [_pt("locked", 30, 0.08, is_liquid=False)]
        snap = self.b.build_curve(pts)
        self.assertEqual(snap.best_liquid_apy, 0.0)

    def test_best_liquid_multiple_picks_max(self):
        pts = [_pt("a", 0, 0.05, is_liquid=True),
               _pt("b", 0, 0.08, is_liquid=True),
               _pt("c", 0, 0.03, is_liquid=True)]
        snap = self.b.build_curve(pts)
        self.assertAlmostEqual(snap.best_liquid_apy, 0.08, places=6)

    def test_best_overall_picks_max_across_all(self):
        pts = [_pt("a", 0, 0.04), _pt("b", 30, 0.12), _pt("c", 90, 0.09)]
        snap = self.b.build_curve(pts)
        self.assertAlmostEqual(snap.best_overall_apy, 0.12, places=6)

    def test_best_overall_single_point(self):
        snap = self.b.build_curve([_pt("a", 0, 0.07)])
        self.assertAlmostEqual(snap.best_overall_apy, 0.07, places=6)

    def test_best_liquid_rounded_to_6_decimals(self):
        pts = [_pt("a", 0, 0.1234567890, is_liquid=True)]
        snap = self.b.build_curve(pts)
        self.assertEqual(snap.best_liquid_apy, round(0.1234567890, 6))


# ===========================================================================
# 5. optimal_point
# ===========================================================================

class TestOptimalPoint(unittest.TestCase):

    def setUp(self):
        self.b = _builder()

    def test_liquid_high_apy_beats_locked(self):
        pts = [_pt("liquid", 0, 0.10), _pt("locked", 90, 0.15)]
        # scores: liquid=0.10/1=0.10, locked=0.15/91≈0.00165 → liquid wins
        snap = self.b.build_curve(pts)
        self.assertEqual(snap.optimal_point, "liquid")

    def test_weekly_beats_liquid_when_far_higher_apy(self):
        pts = [_pt("liquid", 0, 0.01), _pt("weekly", 7, 0.50)]
        # scores: liquid=0.01/1=0.01, weekly=0.50/8=0.0625 → weekly wins
        snap = self.b.build_curve(pts)
        self.assertEqual(snap.optimal_point, "weekly")

    def test_single_point_is_optimal(self):
        snap = self.b.build_curve([_pt("only", 180, 0.12)])
        self.assertEqual(snap.optimal_point, "only")

    def test_empty_returns_none_string(self):
        snap = self.b.build_curve([])
        self.assertEqual(snap.optimal_point, "none")

    def test_score_formula_correct(self):
        # liquid=0.01/1=0.01, weekly=0.50/8=0.0625 → liquid wins (0.01 < 0.0625? No.)
        pts = [_pt("a", 0, 0.05), _pt("b", 7, 0.50)]
        snap = self.b.build_curve(pts)
        score_a = 0.05 / (0 + 1)
        score_b = 0.50 / (7 + 1)
        expected = "b" if score_b > score_a else "a"
        self.assertEqual(snap.optimal_point, expected)


# ===========================================================================
# 6. slope calculations
# ===========================================================================

class TestSlopes(unittest.TestCase):

    def setUp(self):
        self.b = _builder()

    def test_slope_0_30_positive(self):
        pts = [_pt("a", 0, 0.04), _pt("b", 30, 0.07)]
        snap = self.b.build_curve(pts)
        expected = round((0.07 - 0.04) * 10000, 2)
        self.assertAlmostEqual(snap.slope_0_30, expected, places=1)

    def test_slope_0_30_negative(self):
        pts = [_pt("a", 0, 0.09), _pt("b", 30, 0.04)]
        snap = self.b.build_curve(pts)
        expected = round((0.04 - 0.09) * 10000, 2)
        self.assertAlmostEqual(snap.slope_0_30, expected, places=1)

    def test_slope_30_90_positive(self):
        pts = [_pt("a", 0, 0.04), _pt("b", 30, 0.07), _pt("c", 90, 0.10)]
        snap = self.b.build_curve(pts)
        expected = round((0.10 - 0.07) * 10000, 2)
        self.assertAlmostEqual(snap.slope_30_90, expected, places=1)

    def test_slope_30_90_negative(self):
        pts = [_pt("a", 0, 0.04), _pt("b", 30, 0.10), _pt("c", 90, 0.06)]
        snap = self.b.build_curve(pts)
        expected = round((0.06 - 0.10) * 10000, 2)
        self.assertAlmostEqual(snap.slope_30_90, expected, places=1)

    def test_slopes_in_bps_not_decimal(self):
        pts = [_pt("a", 0, 0.05), _pt("b", 30, 0.06)]
        snap = self.b.build_curve(pts)
        self.assertGreater(abs(snap.slope_0_30), 1.0)

    def test_equal_apys_both_slopes_zero(self):
        pts = [_pt("a", 0, 0.05), _pt("b", 30, 0.05), _pt("c", 90, 0.05)]
        snap = self.b.build_curve(pts)
        self.assertAlmostEqual(snap.slope_0_30, 0.0, places=6)
        self.assertAlmostEqual(snap.slope_30_90, 0.0, places=6)
        self.assertEqual(snap.curve_shape, "FLAT")

    def test_slope_rounded_to_2_decimals(self):
        pts = [_pt("a", 0, 0.04), _pt("b", 30, 0.07123456)]
        snap = self.b.build_curve(pts)
        self.assertEqual(snap.slope_0_30, round((0.07123456 - 0.04) * 10000, 2))


# ===========================================================================
# 7. save_snapshot & load_history
# ===========================================================================

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = Path(self.tmpdir) / "yield_curve.json"
        self.b = YieldCurveBuilder(data_file=self.data_file)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_creates_file(self):
        snap = self.b.build_curve([_pt("a", 0, 0.05)])
        self.b.save_snapshot(snap)
        self.assertTrue(self.data_file.exists())

    def test_save_writes_valid_json(self):
        snap = self.b.build_curve([_pt("a", 0, 0.05)])
        self.b.save_snapshot(snap)
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_save_entry_has_all_keys(self):
        snap = self.b.build_curve([_pt("a", 0, 0.05)])
        self.b.save_snapshot(snap)
        entry = json.loads(self.data_file.read_text())[0]
        for key in ("timestamp", "point_count", "slope_0_30", "slope_30_90",
                    "curve_shape", "best_liquid_apy", "best_overall_apy", "optimal_point"):
            self.assertIn(key, entry)

    def test_save_multiple_appends(self):
        for _ in range(5):
            snap = self.b.build_curve([_pt("a", 0, 0.05)])
            self.b.save_snapshot(snap)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), 5)

    def test_ring_buffer_caps_at_max_entries(self):
        for _ in range(MAX_ENTRIES + 10):
            snap = self.b.build_curve([_pt("a", 0, 0.05)])
            self.b.save_snapshot(snap)
        data = json.loads(self.data_file.read_text())
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_save_is_atomic_no_tmp_left(self):
        snap = self.b.build_curve([_pt("a", 0, 0.05)])
        self.b.save_snapshot(snap)
        self.assertFalse(self.data_file.with_suffix(".tmp").exists())

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(self.b.load_history(), [])

    def test_load_history_returns_list(self):
        snap = self.b.build_curve([_pt("a", 0, 0.05)])
        self.b.save_snapshot(snap)
        h = self.b.load_history()
        self.assertIsInstance(h, list)
        self.assertEqual(len(h), 1)

    def test_load_history_corrupted_file_returns_empty(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_file.write_text("NOT_JSON{{{")
        self.assertEqual(self.b.load_history(), [])

    def test_save_point_count_matches(self):
        pts = [_pt("a", 0, 0.05), _pt("b", 30, 0.07)]
        snap = self.b.build_curve(pts)
        self.b.save_snapshot(snap)
        entry = json.loads(self.data_file.read_text())[0]
        self.assertEqual(entry["point_count"], 2)


# ===========================================================================
# 8. get_inversion_alert
# ===========================================================================

class TestInversionAlert(unittest.TestCase):

    def setUp(self):
        self.b = _builder()

    def test_normal_curve_returns_none(self):
        pts = [_pt("a", 0, 0.04), _pt("b", 30, 0.07), _pt("c", 90, 0.10)]
        snap = self.b.build_curve(pts)
        self.assertIsNone(self.b.get_inversion_alert(snap))

    def test_flat_curve_returns_none(self):
        pts = [_pt("a", 0, 0.05), _pt("b", 30, 0.05), _pt("c", 90, 0.05)]
        snap = self.b.build_curve(pts)
        self.assertIsNone(self.b.get_inversion_alert(snap))

    def test_humped_curve_returns_none(self):
        snap = YieldCurveSnapshot(
            timestamp=time.time(), points=[],
            slope_0_30=100.0, slope_30_90=-100.0, curve_shape="HUMPED",
            best_liquid_apy=0.05, best_overall_apy=0.08, optimal_point="x",
        )
        self.assertIsNone(self.b.get_inversion_alert(snap))

    def test_inverted_curve_returns_non_none(self):
        snap = YieldCurveSnapshot(
            timestamp=time.time(), points=[],
            slope_0_30=-50.0, slope_30_90=-30.0, curve_shape="INVERTED",
            best_liquid_apy=0.09, best_overall_apy=0.09, optimal_point="a",
        )
        alert = self.b.get_inversion_alert(snap)
        self.assertIsNotNone(alert)

    def test_inverted_alert_contains_word_inverted(self):
        snap = YieldCurveSnapshot(
            timestamp=time.time(), points=[],
            slope_0_30=-50.0, slope_30_90=-30.0, curve_shape="INVERTED",
            best_liquid_apy=0.09, best_overall_apy=0.09, optimal_point="a",
        )
        alert = self.b.get_inversion_alert(snap)
        self.assertIn("INVERTED", alert)

    def test_inverted_alert_mentions_rate(self):
        snap = YieldCurveSnapshot(
            timestamp=time.time(), points=[],
            slope_0_30=-50.0, slope_30_90=-30.0, curve_shape="INVERTED",
            best_liquid_apy=0.09, best_overall_apy=0.09, optimal_point="a",
        )
        alert = self.b.get_inversion_alert(snap)
        self.assertIn("9.0%", alert)


# ===========================================================================
# 9. Full scenario: 5 adapters (0/7/30/90/180 days)
# ===========================================================================

class TestFullScenario(unittest.TestCase):

    def setUp(self):
        self.b = _builder()
        self.pts = [
            _pt("aave",   0,   0.035, "T1", True),
            _pt("comp",   7,   0.048, "T1", False),
            _pt("morpho", 30,  0.065, "T1", False),
            _pt("euler",  90,  0.072, "T2", False),
            _pt("pendle", 180, 0.120, "T3", False),
        ]
        self.snap = self.b.build_curve(self.pts)

    def test_correct_point_count(self):
        self.assertEqual(len(self.snap.points), 5)

    def test_sorted_ascending(self):
        locks = [p.lock_days for p in self.snap.points]
        self.assertEqual(locks, [0, 7, 30, 90, 180])

    def test_slope_0_30_positive(self):
        self.assertGreater(self.snap.slope_0_30, 0)

    def test_slope_30_90_positive(self):
        self.assertGreater(self.snap.slope_30_90, 0)

    def test_curve_shape_normal(self):
        self.assertEqual(self.snap.curve_shape, "NORMAL")

    def test_best_liquid_apy(self):
        self.assertAlmostEqual(self.snap.best_liquid_apy, 0.035, places=6)

    def test_best_overall_apy(self):
        self.assertAlmostEqual(self.snap.best_overall_apy, 0.120, places=6)

    def test_optimal_point_is_aave(self):
        # Scores: aave=0.035/1=0.035 wins over all locked adapters
        self.assertEqual(self.snap.optimal_point, "aave")

    def test_no_inversion_alert(self):
        self.assertIsNone(self.b.get_inversion_alert(self.snap))

    def test_slope_0_30_approx_300bps(self):
        # apy@0=0.035, apy@30=0.065 → 300bps
        self.assertAlmostEqual(self.snap.slope_0_30, 300.0, delta=1.0)

    def test_slope_30_90_approx_70bps(self):
        # apy@30=0.065, apy@90=0.072 → 70bps
        self.assertAlmostEqual(self.snap.slope_30_90, 70.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
