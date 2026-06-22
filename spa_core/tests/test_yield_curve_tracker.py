"""
Tests for MP-686: YieldCurveTracker
65+ tests covering all logic branches.
Uses unittest only (pure stdlib).
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.yield_curve_tracker import (
    YieldPoint,
    YieldCurveReport,
    _sort_points,
    _is_inverted,
    _term_premium_bps,
    _nearest_tradfi,
    _defi_vs_tradfi_spread_bps,
    _segment_slopes,
    _steepest_segment,
    _flattest_segment,
    _best_entry_point,
    _has_hump,
    _curve_shape,
    _interpretation,
    analyze_curve,
    save_results,
    load_history,
)


def make_pt(maturity, protocol="pendle", asset="USDC", yield_pct=5.0, tvl=500_000):
    return YieldPoint(
        maturity_days=maturity,
        protocol=protocol,
        asset=asset,
        yield_pct=yield_pct,
        tvl_usd=tvl,
    )


class TestSortPoints(unittest.TestCase):
    def test_already_sorted(self):
        pts = [make_pt(30), make_pt(90), make_pt(180)]
        result = _sort_points(pts)
        self.assertEqual([p.maturity_days for p in result], [30, 90, 180])

    def test_reverse_order(self):
        pts = [make_pt(365), make_pt(90), make_pt(30)]
        result = _sort_points(pts)
        self.assertEqual([p.maturity_days for p in result], [30, 90, 365])

    def test_single_point(self):
        pts = [make_pt(60)]
        result = _sort_points(pts)
        self.assertEqual(len(result), 1)

    def test_empty(self):
        self.assertEqual(_sort_points([]), [])


class TestIsInverted(unittest.TestCase):
    def test_inverted_short_higher(self):
        pts = [make_pt(30, yield_pct=8.0), make_pt(365, yield_pct=5.0)]
        self.assertTrue(_is_inverted(pts))

    def test_normal_curve(self):
        pts = [make_pt(30, yield_pct=5.0), make_pt(365, yield_pct=8.0)]
        self.assertFalse(_is_inverted(pts))

    def test_equal_yields(self):
        pts = [make_pt(30, yield_pct=5.0), make_pt(365, yield_pct=5.0)]
        self.assertFalse(_is_inverted(pts))

    def test_single_point(self):
        self.assertFalse(_is_inverted([make_pt(30)]))

    def test_empty(self):
        self.assertFalse(_is_inverted([]))

    def test_three_points_inverted(self):
        pts = [make_pt(30, yield_pct=9.0), make_pt(90, yield_pct=7.0), make_pt(365, yield_pct=5.0)]
        self.assertTrue(_is_inverted(pts))

    def test_three_points_normal(self):
        pts = [make_pt(30, yield_pct=4.0), make_pt(90, yield_pct=6.0), make_pt(365, yield_pct=8.0)]
        self.assertFalse(_is_inverted(pts))


class TestTermPremiumBps(unittest.TestCase):
    def test_normal_positive(self):
        pts = [make_pt(30, yield_pct=4.0), make_pt(365, yield_pct=6.0)]
        self.assertAlmostEqual(_term_premium_bps(pts), 200.0)

    def test_inverted_negative(self):
        pts = [make_pt(30, yield_pct=8.0), make_pt(365, yield_pct=5.0)]
        self.assertAlmostEqual(_term_premium_bps(pts), -300.0)

    def test_flat_zero(self):
        pts = [make_pt(30, yield_pct=5.0), make_pt(365, yield_pct=5.0)]
        self.assertAlmostEqual(_term_premium_bps(pts), 0.0)

    def test_single_point_zero(self):
        self.assertAlmostEqual(_term_premium_bps([make_pt(30)]), 0.0)

    def test_empty_zero(self):
        self.assertAlmostEqual(_term_premium_bps([]), 0.0)

    def test_uses_sorted_order(self):
        # Even if passed out of order, sorted already applied upstream
        pts = [make_pt(30, yield_pct=4.0), make_pt(180, yield_pct=5.5), make_pt(365, yield_pct=7.0)]
        self.assertAlmostEqual(_term_premium_bps(pts), 300.0)


class TestNearestTradfi(unittest.TestCase):
    def test_exact_match_30(self):
        self.assertAlmostEqual(_nearest_tradfi(30), 4.25)

    def test_exact_match_365(self):
        self.assertAlmostEqual(_nearest_tradfi(365), 4.40)

    def test_nearest_to_60(self):
        # 60 is between 30 and 90; |60-30|=30, |60-90|=30 — tie → min picks first key
        result = _nearest_tradfi(60)
        self.assertIn(result, [4.25, 4.50])

    def test_nearest_to_45(self):
        # |45-30|=15, |45-90|=45 → nearest=30
        self.assertAlmostEqual(_nearest_tradfi(45), 4.25)

    def test_nearest_to_200(self):
        # |200-180|=20, |200-365|=165 → nearest=180
        self.assertAlmostEqual(_nearest_tradfi(200), 4.55)

    def test_nearest_to_1000(self):
        # |1000-730|=270, |1000-1825|=825 → nearest=730
        self.assertAlmostEqual(_nearest_tradfi(1000), 4.20)


class TestDefiVsTradfiSpread(unittest.TestCase):
    def test_no_defi_points_zero(self):
        pts = [make_pt(30, protocol="tradfi", yield_pct=4.25)]
        self.assertAlmostEqual(_defi_vs_tradfi_spread_bps(pts), 0.0)

    def test_empty_zero(self):
        self.assertAlmostEqual(_defi_vs_tradfi_spread_bps([]), 0.0)

    def test_single_defi_at_30(self):
        # tradfi at 30 = 4.25%; defi = 6.25% → spread = 200 bps
        pts = [make_pt(30, protocol="pendle", yield_pct=6.25)]
        self.assertAlmostEqual(_defi_vs_tradfi_spread_bps(pts), 200.0)

    def test_multiple_defi_average(self):
        # pt1: maturity=30 defi=6.25 → tradfi=4.25 → spread=200 bps
        # pt2: maturity=365 defi=8.40 → tradfi=4.40 → spread=400 bps
        # avg = 300 bps
        pts = [
            make_pt(30, protocol="pendle", yield_pct=6.25),
            make_pt(365, protocol="pendle", yield_pct=8.40),
        ]
        self.assertAlmostEqual(_defi_vs_tradfi_spread_bps(pts), 300.0)

    def test_tradfi_excluded_from_spread(self):
        pts = [
            make_pt(30, protocol="tradfi", yield_pct=4.25),
            make_pt(90, protocol="pendle", yield_pct=5.50),
        ]
        # only pendle counts: 5.50 - 4.50 = 1.0% = 100 bps
        self.assertAlmostEqual(_defi_vs_tradfi_spread_bps(pts), 100.0)

    def test_negative_spread(self):
        # defi yield below tradfi
        pts = [make_pt(365, protocol="pendle", yield_pct=3.40)]
        # tradfi at 365 = 4.40; spread = (3.40 - 4.40)*100 = -100 bps
        self.assertAlmostEqual(_defi_vs_tradfi_spread_bps(pts), -100.0)


class TestSegmentSlopes(unittest.TestCase):
    def test_two_points(self):
        pts = [make_pt(30, yield_pct=4.0), make_pt(365, yield_pct=8.0)]
        slopes = _segment_slopes(pts)
        self.assertEqual(len(slopes), 1)
        a, b, slope = slopes[0]
        self.assertEqual(a, 30)
        self.assertEqual(b, 365)
        expected = (8.0 - 4.0) / (365 - 30) * 365
        self.assertAlmostEqual(slope, expected, places=5)

    def test_three_points(self):
        pts = [make_pt(30, yield_pct=4.0), make_pt(90, yield_pct=5.0), make_pt(180, yield_pct=7.0)]
        slopes = _segment_slopes(pts)
        self.assertEqual(len(slopes), 2)

    def test_single_point_empty(self):
        self.assertEqual(_segment_slopes([make_pt(30)]), [])

    def test_empty_empty(self):
        self.assertEqual(_segment_slopes([]), [])

    def test_slope_formula_annualized(self):
        # yield goes from 0.0 to 3.65 over 365 days → annualized = 3.65
        pts = [make_pt(0, yield_pct=0.0), make_pt(365, yield_pct=3.65)]
        slopes = _segment_slopes(pts)
        self.assertAlmostEqual(slopes[0][2], 3.65, places=5)

    def test_negative_slope(self):
        pts = [make_pt(30, yield_pct=8.0), make_pt(365, yield_pct=5.0)]
        slopes = _segment_slopes(pts)
        self.assertLess(slopes[0][2], 0)


class TestSteepestAndFlattest(unittest.TestCase):
    def _make_slopes(self):
        return [(30, 90, 2.0), (90, 180, 0.5), (180, 365, 5.0)]

    def test_steepest(self):
        self.assertEqual(_steepest_segment(self._make_slopes()), (180, 365))

    def test_flattest(self):
        self.assertEqual(_flattest_segment(self._make_slopes()), (90, 180))

    def test_steepest_negative_slope(self):
        slopes = [(30, 90, -6.0), (90, 180, 0.1)]
        self.assertEqual(_steepest_segment(slopes), (30, 90))

    def test_flattest_single(self):
        slopes = [(30, 90, 3.0)]
        self.assertEqual(_steepest_segment(slopes), (30, 90))
        self.assertEqual(_flattest_segment(slopes), (30, 90))

    def test_empty(self):
        self.assertEqual(_steepest_segment([]), (0, 0))
        self.assertEqual(_flattest_segment([]), (0, 0))


class TestBestEntryPoint(unittest.TestCase):
    def test_highest_yield_defi(self):
        pts = [
            make_pt(30, protocol="pendle", yield_pct=5.0, tvl=200_000),
            make_pt(90, protocol="pendle", yield_pct=9.0, tvl=200_000),
            make_pt(180, protocol="pendle", yield_pct=7.0, tvl=200_000),
        ]
        self.assertEqual(_best_entry_point(pts), 90)

    def test_tvl_filter(self):
        pts = [
            make_pt(30, protocol="pendle", yield_pct=5.0, tvl=200_000),
            make_pt(90, protocol="pendle", yield_pct=15.0, tvl=50_000),  # too small TVL
        ]
        self.assertEqual(_best_entry_point(pts), 30)

    def test_no_qualifying_returns_zero(self):
        pts = [make_pt(30, protocol="pendle", yield_pct=5.0, tvl=50_000)]
        self.assertEqual(_best_entry_point(pts), 0)

    def test_tradfi_excluded(self):
        pts = [
            make_pt(30, protocol="tradfi", yield_pct=20.0, tvl=1_000_000),
            make_pt(90, protocol="pendle", yield_pct=6.0, tvl=200_000),
        ]
        self.assertEqual(_best_entry_point(pts), 90)

    def test_empty_returns_zero(self):
        self.assertEqual(_best_entry_point([]), 0)

    def test_exact_tvl_boundary(self):
        # tvl=100_000 should NOT qualify (must be > 100_000)
        pts = [make_pt(30, protocol="pendle", yield_pct=5.0, tvl=100_000)]
        self.assertEqual(_best_entry_point(pts), 0)

    def test_tvl_just_above_boundary(self):
        pts = [make_pt(30, protocol="pendle", yield_pct=5.0, tvl=100_001)]
        self.assertEqual(_best_entry_point(pts), 30)


class TestHasHump(unittest.TestCase):
    def test_humped(self):
        pts = [
            make_pt(30, yield_pct=4.0),
            make_pt(90, yield_pct=9.0),   # peak
            make_pt(365, yield_pct=6.0),
        ]
        self.assertTrue(_has_hump(pts))

    def test_normal_no_hump(self):
        pts = [make_pt(30, yield_pct=4.0), make_pt(90, yield_pct=6.0), make_pt(365, yield_pct=8.0)]
        self.assertFalse(_has_hump(pts))

    def test_two_points_no_hump(self):
        self.assertFalse(_has_hump([make_pt(30), make_pt(90)]))

    def test_single_point_no_hump(self):
        self.assertFalse(_has_hump([make_pt(30)]))

    def test_four_points_hump_middle(self):
        pts = [
            make_pt(30, yield_pct=4.0),
            make_pt(90, yield_pct=8.0),  # hump
            make_pt(180, yield_pct=6.0),
            make_pt(365, yield_pct=5.5),
        ]
        self.assertTrue(_has_hump(pts))


class TestCurveShape(unittest.TestCase):
    def test_inverted_shape(self):
        pts = [make_pt(30, yield_pct=8.0), make_pt(365, yield_pct=5.0)]
        self.assertEqual(_curve_shape(True, -300.0, pts), "INVERTED")

    def test_flat_shape(self):
        pts = [make_pt(30, yield_pct=5.0), make_pt(365, yield_pct=5.1)]
        self.assertEqual(_curve_shape(False, 10.0, pts), "FLAT")

    def test_flat_negative_small(self):
        pts = [make_pt(30, yield_pct=5.1), make_pt(365, yield_pct=5.0)]
        self.assertEqual(_curve_shape(False, -10.0, pts), "FLAT")

    def test_humped_shape(self):
        pts = [make_pt(30, yield_pct=4.0), make_pt(90, yield_pct=9.0), make_pt(365, yield_pct=5.0)]
        self.assertEqual(_curve_shape(False, 100.0, pts), "HUMPED")

    def test_normal_shape(self):
        pts = [make_pt(30, yield_pct=4.0), make_pt(90, yield_pct=6.0), make_pt(365, yield_pct=8.0)]
        self.assertEqual(_curve_shape(False, 400.0, pts), "NORMAL")

    def test_inverted_takes_priority_over_flat(self):
        # If inverted, shape = INVERTED even if term_premium is small
        pts = [make_pt(30, yield_pct=5.05), make_pt(365, yield_pct=5.0)]
        self.assertEqual(_curve_shape(True, -5.0, pts), "INVERTED")

    def test_flat_boundary_exactly_20(self):
        # abs < 20 → FLAT; abs == 20 → not FLAT
        pts = [make_pt(30, yield_pct=5.0), make_pt(365, yield_pct=5.2)]
        self.assertEqual(_curve_shape(False, 20.0, pts), "NORMAL")

    def test_flat_boundary_just_under_20(self):
        pts = [make_pt(30, yield_pct=5.0), make_pt(365, yield_pct=5.19)]
        self.assertEqual(_curve_shape(False, 19.0, pts), "FLAT")


class TestInterpretation(unittest.TestCase):
    def test_inverted(self):
        msg = _interpretation("INVERTED")
        self.assertIn("Inverted", msg)
        self.assertIn("shorter", msg)

    def test_flat(self):
        msg = _interpretation("FLAT")
        self.assertIn("Flat", msg)

    def test_humped(self):
        msg = _interpretation("HUMPED")
        self.assertIn("Humped", msg)

    def test_normal(self):
        msg = _interpretation("NORMAL")
        self.assertIn("Normal", msg)

    def test_unknown_shape_empty(self):
        self.assertEqual(_interpretation("UNKNOWN"), "")


class TestAnalyzeCurve(unittest.TestCase):
    def _normal_points(self):
        return [
            make_pt(30,  protocol="pendle", yield_pct=4.0, tvl=500_000),
            make_pt(90,  protocol="pendle", yield_pct=5.5, tvl=400_000),
            make_pt(180, protocol="pendle", yield_pct=6.8, tvl=300_000),
            make_pt(365, protocol="pendle", yield_pct=8.0, tvl=200_000),
        ]

    def test_returns_yield_curve_report(self):
        report = analyze_curve("test-001", self._normal_points())
        self.assertIsInstance(report, YieldCurveReport)

    def test_curve_id_preserved(self):
        report = analyze_curve("my-curve", self._normal_points())
        self.assertEqual(report.curve_id, "my-curve")

    def test_points_sorted_by_maturity(self):
        pts = [make_pt(365), make_pt(30), make_pt(90)]
        report = analyze_curve("sort-test", pts)
        maturities = [p.maturity_days for p in report.points]
        self.assertEqual(maturities, sorted(maturities))

    def test_normal_curve_shape(self):
        report = analyze_curve("normal", self._normal_points())
        self.assertEqual(report.curve_shape, "NORMAL")

    def test_normal_curve_not_inverted(self):
        report = analyze_curve("normal", self._normal_points())
        self.assertFalse(report.is_inverted)

    def test_normal_curve_positive_term_premium(self):
        report = analyze_curve("normal", self._normal_points())
        self.assertGreater(report.term_premium_bps, 0)

    def test_inverted_curve(self):
        pts = [
            make_pt(30, yield_pct=9.0, tvl=500_000),
            make_pt(90, yield_pct=7.0, tvl=400_000),
            make_pt(365, yield_pct=5.0, tvl=200_000),
        ]
        report = analyze_curve("inv", pts)
        self.assertTrue(report.is_inverted)
        self.assertEqual(report.curve_shape, "INVERTED")
        self.assertIn("Inverted", report.interpretation)

    def test_single_point_term_premium_zero(self):
        report = analyze_curve("single", [make_pt(90, yield_pct=5.0)])
        self.assertAlmostEqual(report.term_premium_bps, 0.0)

    def test_single_point_no_segments(self):
        report = analyze_curve("single", [make_pt(90)])
        self.assertEqual(report.steepest_segment, (0, 0))
        self.assertEqual(report.flattest_segment, (0, 0))

    def test_humped_curve(self):
        pts = [
            make_pt(30, yield_pct=4.0, tvl=500_000),
            make_pt(90, yield_pct=10.0, tvl=500_000),
            make_pt(365, yield_pct=6.0, tvl=500_000),
        ]
        report = analyze_curve("hump", pts)
        self.assertEqual(report.curve_shape, "HUMPED")

    def test_best_entry_highest_defi_yield(self):
        report = analyze_curve("best", self._normal_points())
        self.assertEqual(report.best_entry_point, 365)

    def test_defi_tradfi_spread_computed(self):
        pts = [make_pt(30, protocol="pendle", yield_pct=6.25, tvl=500_000)]
        report = analyze_curve("spread", pts)
        self.assertAlmostEqual(report.defi_vs_tradfi_spread_bps, 200.0)

    def test_interpretation_matches_shape(self):
        report = analyze_curve("normal", self._normal_points())
        if report.curve_shape == "NORMAL":
            self.assertIn("Normal", report.interpretation)
        elif report.curve_shape == "INVERTED":
            self.assertIn("Inverted", report.interpretation)

    def test_empty_points(self):
        report = analyze_curve("empty", [])
        self.assertFalse(report.is_inverted)
        self.assertAlmostEqual(report.term_premium_bps, 0.0)


class TestSaveAndLoadHistory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = Path(self.tmpdir) / "yield_curve_log.json"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_report(self, curve_id="test-001"):
        pts = [
            make_pt(30, yield_pct=4.0),
            make_pt(365, yield_pct=7.0),
        ]
        return analyze_curve(curve_id, pts)

    def test_load_missing_returns_empty(self):
        self.assertEqual(load_history(self.data_file), [])

    def test_save_then_load(self):
        report = self._make_report()
        save_results(report, self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["curve_id"], "test-001")

    def test_save_multiple(self):
        for i in range(5):
            save_results(self._make_report(f"curve-{i}"), self.data_file)
        self.assertEqual(len(load_history(self.data_file)), 5)

    def test_ring_buffer_cap(self):
        from spa_core.analytics.yield_curve_tracker import MAX_ENTRIES
        for i in range(MAX_ENTRIES + 10):
            save_results(self._make_report(f"c{i}"), self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), MAX_ENTRIES)

    def test_ring_buffer_keeps_newest(self):
        from spa_core.analytics.yield_curve_tracker import MAX_ENTRIES
        for i in range(MAX_ENTRIES + 5):
            save_results(self._make_report(f"c{i}"), self.data_file)
        history = load_history(self.data_file)
        last_id = history[-1]["curve_id"]
        self.assertEqual(last_id, f"c{MAX_ENTRIES + 4}")

    def test_atomic_write_no_tmp_left(self):
        save_results(self._make_report(), self.data_file)
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_save_creates_parent_dir(self):
        nested = Path(self.tmpdir) / "nested" / "deep" / "yield_curve_log.json"
        save_results(self._make_report(), nested)
        self.assertTrue(nested.exists())

    def test_saved_json_valid(self):
        save_results(self._make_report(), self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)
        self.assertIsInstance(data[0], dict)

    def test_load_invalid_json_returns_empty(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_file.write_text("{invalid json")
        self.assertEqual(load_history(self.data_file), [])

    def test_report_fields_saved(self):
        pts = [make_pt(30, yield_pct=4.0, tvl=500_000), make_pt(365, yield_pct=8.0, tvl=300_000)]
        report = analyze_curve("field-check", pts)
        save_results(report, self.data_file)
        history = load_history(self.data_file)
        entry = history[0]
        self.assertIn("is_inverted", entry)
        self.assertIn("term_premium_bps", entry)
        self.assertIn("curve_shape", entry)
        self.assertIn("interpretation", entry)
        self.assertIn("defi_vs_tradfi_spread_bps", entry)
        self.assertIn("best_entry_point", entry)
        self.assertIn("steepest_segment", entry)
        self.assertIn("flattest_segment", entry)
        self.assertIn("points", entry)
        self.assertIn("timestamp", entry)


class TestEdgeCases(unittest.TestCase):
    def test_two_points_flat_curve(self):
        pts = [make_pt(30, yield_pct=5.0), make_pt(365, yield_pct=5.1)]
        report = analyze_curve("flat", pts)
        self.assertEqual(report.curve_shape, "FLAT")

    def test_all_same_maturity_not_inverted(self):
        pts = [make_pt(90, yield_pct=5.0), make_pt(90, yield_pct=6.0)]
        report = analyze_curve("dup-mat", pts)
        # same maturity: sorted[0] == sorted[-1] → not inverted since first==first
        self.assertFalse(report.is_inverted)

    def test_term_premium_bps_large_curve(self):
        pts = [make_pt(30, yield_pct=2.0), make_pt(1825, yield_pct=12.0)]
        report = analyze_curve("large", pts)
        self.assertAlmostEqual(report.term_premium_bps, 1000.0)

    def test_tradfi_only_no_spread(self):
        pts = [
            make_pt(30, protocol="tradfi", yield_pct=4.25, tvl=1_000_000),
            make_pt(365, protocol="tradfi", yield_pct=4.40, tvl=1_000_000),
        ]
        report = analyze_curve("tradfi-only", pts)
        self.assertAlmostEqual(report.defi_vs_tradfi_spread_bps, 0.0)

    def test_best_entry_point_all_low_tvl(self):
        pts = [make_pt(30, protocol="pendle", yield_pct=5.0, tvl=10_000)]
        report = analyze_curve("low-tvl", pts)
        self.assertEqual(report.best_entry_point, 0)

    def test_steepest_segment_with_two_equal_slopes(self):
        pts = [make_pt(30, yield_pct=4.0), make_pt(90, yield_pct=5.0), make_pt(150, yield_pct=6.0)]
        report = analyze_curve("equal-slopes", pts)
        # Both slopes equal; steepest returns one of them (any valid pair)
        self.assertIsInstance(report.steepest_segment, tuple)

    def test_report_interpretation_not_empty(self):
        pts = [make_pt(30, yield_pct=4.0), make_pt(365, yield_pct=8.0)]
        report = analyze_curve("normal2", pts)
        self.assertGreater(len(report.interpretation), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
