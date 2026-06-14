"""
Tests for MP-716: APYNormalizationEngine
≥65 tests. Pure unittest, no external deps.
"""
import json
import math
import os
import sys
import tempfile
import unittest

# Make spa_core importable regardless of working directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.apy_normalization_engine import (
    RawAPY,
    NormalizedAPY,
    NormalizationReport,
    to_ear,
    quality_score,
    normalize,
    detect_outliers,
    build_report,
    compare_sources,
    save_results,
    load_history,
    _mean,
    _std,
    _median,
)


# ─── to_ear tests ──────────────────────────────────────────────────────────

class TestToEAR(unittest.TestCase):

    def test_simple_returns_raw(self):
        self.assertAlmostEqual(to_ear(10.0, "simple"), 10.0)

    def test_simple_zero(self):
        self.assertAlmostEqual(to_ear(0.0, "simple"), 0.0)

    def test_annual_returns_raw(self):
        self.assertAlmostEqual(to_ear(5.0, "annual"), 5.0)

    def test_annual_large(self):
        self.assertAlmostEqual(to_ear(50.0, "annual"), 50.0)

    def test_monthly_12pct(self):
        # EAR = ((1 + 0.12/12)^12 - 1)*100 ≈ 12.6825%
        expected = ((1 + 0.12 / 12) ** 12 - 1) * 100
        self.assertAlmostEqual(to_ear(12.0, "monthly"), expected, places=6)

    def test_monthly_0pct(self):
        self.assertAlmostEqual(to_ear(0.0, "monthly"), 0.0, places=10)

    def test_monthly_greater_than_raw(self):
        # Compounding should give higher EAR than nominal for positive rates
        raw = 6.0
        self.assertGreater(to_ear(raw, "monthly"), raw)

    def test_weekly_formula(self):
        expected = ((1 + 0.12 / 52) ** 52 - 1) * 100
        self.assertAlmostEqual(to_ear(12.0, "weekly"), expected, places=6)

    def test_weekly_greater_than_monthly(self):
        # Weekly compounding > monthly compounding for same nominal rate
        self.assertGreater(to_ear(10.0, "weekly"), to_ear(10.0, "monthly"))

    def test_daily_formula(self):
        expected = ((1 + 0.12 / 365) ** 365 - 1) * 100
        self.assertAlmostEqual(to_ear(12.0, "daily"), expected, places=5)

    def test_daily_greater_than_weekly(self):
        self.assertGreater(to_ear(10.0, "daily"), to_ear(10.0, "weekly"))

    def test_continuous_formula(self):
        # EAR = (e^0.12 - 1)*100 ≈ 12.7497%
        expected = (math.exp(0.12) - 1) * 100
        self.assertAlmostEqual(to_ear(12.0, "continuous"), expected, places=5)

    def test_continuous_greater_than_daily(self):
        self.assertGreater(to_ear(10.0, "continuous"), to_ear(10.0, "daily"))

    def test_continuous_approx_12_75_for_12pct(self):
        result = to_ear(12.0, "continuous")
        self.assertAlmostEqual(result, 12.7497, places=3)

    def test_unknown_compounding_returns_raw(self):
        self.assertAlmostEqual(to_ear(7.5, "biennial"), 7.5)

    def test_unknown_compounding_empty_string(self):
        self.assertAlmostEqual(to_ear(5.0, ""), 5.0)

    def test_case_insensitive_monthly(self):
        expected = ((1 + 0.12 / 12) ** 12 - 1) * 100
        self.assertAlmostEqual(to_ear(12.0, "MONTHLY"), expected, places=6)

    def test_case_insensitive_continuous(self):
        expected = (math.exp(0.05) - 1) * 100
        self.assertAlmostEqual(to_ear(5.0, "Continuous"), expected, places=5)


# ─── quality_score tests ───────────────────────────────────────────────────

class TestQualityScore(unittest.TestCase):

    def test_high(self):
        self.assertEqual(quality_score("HIGH"), 90.0)

    def test_medium(self):
        self.assertEqual(quality_score("MEDIUM"), 60.0)

    def test_low(self):
        self.assertEqual(quality_score("LOW"), 30.0)

    def test_unknown_defaults_to_30(self):
        self.assertEqual(quality_score("UNKNOWN"), 30.0)

    def test_case_insensitive_high(self):
        self.assertEqual(quality_score("high"), 90.0)

    def test_case_insensitive_medium(self):
        self.assertEqual(quality_score("Medium"), 60.0)


# ─── quality_adjusted_apy tests ───────────────────────────────────────────

class TestQualityAdjusted(unittest.TestCase):

    def test_high_quality_adjustment(self):
        ear = 10.0
        qs = quality_score("HIGH")
        expected = ear * qs / 100.0
        raw = RawAPY("S", "P", "pool", 10.0, "simple", "HIGH")
        normed = normalize([raw])
        self.assertAlmostEqual(normed[0].quality_adjusted_apy, expected)

    def test_low_quality_adjustment(self):
        raw = RawAPY("S", "P", "pool", 20.0, "simple", "LOW")
        normed = normalize([raw])
        self.assertAlmostEqual(normed[0].quality_adjusted_apy, 20.0 * 30.0 / 100.0)

    def test_medium_quality_adjustment(self):
        raw = RawAPY("S", "P", "pool", 5.0, "annual", "MEDIUM")
        normed = normalize([raw])
        self.assertAlmostEqual(normed[0].quality_adjusted_apy, 5.0 * 60.0 / 100.0)


# ─── normalize tests ───────────────────────────────────────────────────────

class TestNormalize(unittest.TestCase):

    def _r(self, apy, comp, quality="HIGH"):
        return RawAPY("src", "proto", "pool", apy, comp, quality)

    def test_simple_compounding_passthrough(self):
        normed = normalize([self._r(5.0, "simple")])
        self.assertAlmostEqual(normed[0].ear, 5.0)

    def test_annual_compounding_passthrough(self):
        normed = normalize([self._r(5.0, "annual")])
        self.assertAlmostEqual(normed[0].ear, 5.0)

    def test_monthly_compounding(self):
        normed = normalize([self._r(12.0, "monthly")])
        expected = ((1 + 0.12 / 12) ** 12 - 1) * 100
        self.assertAlmostEqual(normed[0].ear, expected, places=6)

    def test_weekly_compounding(self):
        normed = normalize([self._r(12.0, "weekly")])
        expected = ((1 + 0.12 / 52) ** 52 - 1) * 100
        self.assertAlmostEqual(normed[0].ear, expected, places=6)

    def test_daily_compounding(self):
        normed = normalize([self._r(12.0, "daily")])
        expected = ((1 + 0.12 / 365) ** 365 - 1) * 100
        self.assertAlmostEqual(normed[0].ear, expected, places=5)

    def test_continuous_compounding(self):
        normed = normalize([self._r(12.0, "continuous")])
        expected = (math.exp(0.12) - 1) * 100
        self.assertAlmostEqual(normed[0].ear, expected, places=5)

    def test_apr_equals_ear(self):
        normed = normalize([self._r(10.0, "daily")])
        self.assertEqual(normed[0].apr, normed[0].ear)

    def test_is_outlier_starts_false(self):
        normed = normalize([self._r(5.0, "daily")])
        self.assertFalse(normed[0].is_outlier)

    def test_empty_list(self):
        self.assertEqual(normalize([]), [])

    def test_source_preserved(self):
        r = RawAPY("SpecialSource", "P", "pool", 5.0, "simple", "HIGH")
        normed = normalize([r])
        self.assertEqual(normed[0].source, "SpecialSource")

    def test_multiple_entries_count(self):
        raws = [self._r(float(i), "simple") for i in range(5)]
        normed = normalize(raws)
        self.assertEqual(len(normed), 5)


# ─── detect_outliers tests ─────────────────────────────────────────────────

class TestDetectOutliers(unittest.TestCase):

    def _normed(self, ear_values):
        entries = []
        for v in ear_values:
            r = RawAPY("S", "P", "pool", v, "simple", "HIGH")
        return normalize([RawAPY("S", "P", f"p{i}", v, "simple", "HIGH")
                         for i, v in enumerate(ear_values)])

    def test_no_outliers_if_less_than_3_entries_1(self):
        normed = normalize([RawAPY("S", "P", "p", 5.0, "simple", "HIGH")])
        result = detect_outliers(normed)
        self.assertFalse(result[0].is_outlier)

    def test_no_outliers_if_less_than_3_entries_2(self):
        raws = [RawAPY("S", "P", f"p{i}", float(i * 5), "simple", "HIGH") for i in range(2)]
        normed = normalize(raws)
        result = detect_outliers(normed)
        self.assertFalse(all(e.is_outlier for e in result))

    def test_outlier_detected_high(self):
        # 4, 5, 6, 5, 4 plus extreme outlier 100
        values = [4.0, 5.0, 6.0, 5.0, 4.0, 100.0]
        raws = [RawAPY("S", "P", f"p{i}", v, "simple", "HIGH") for i, v in enumerate(values)]
        normed = normalize(raws)
        result = detect_outliers(normed)
        outlier_flags = [e.is_outlier for e in result]
        # 100 should be flagged
        self.assertTrue(outlier_flags[-1])
        # small values should not be flagged
        self.assertFalse(outlier_flags[0])

    def test_no_outliers_uniform_values(self):
        raws = [RawAPY("S", "P", f"p{i}", 5.0, "simple", "HIGH") for i in range(5)]
        normed = normalize(raws)
        result = detect_outliers(normed)
        self.assertFalse(any(e.is_outlier for e in result))

    def test_outlier_count_preserved_in_report(self):
        # 5 uniform values + one extreme → 100 lies beyond mean+2*std
        # [5]*5 + [100]: mean≈20.83, std≈35.42, hi≈91.67 → 100 is outlier
        values = [5.0, 5.0, 5.0, 5.0, 5.0, 100.0]
        raws = [RawAPY("S", "P", f"p{i}", v, "simple", "HIGH") for i, v in enumerate(values)]
        report = build_report(raws)
        self.assertEqual(report.outlier_count, 1)

    def test_mean_2std_threshold_logic(self):
        # [10]*5 + [15]: mean≈10.83, std≈1.86, hi≈14.55 → 15 is outlier
        values = [10.0, 10.0, 10.0, 10.0, 10.0, 15.0]
        raws = [RawAPY("S", "P", f"p{i}", v, "simple", "HIGH") for i, v in enumerate(values)]
        normed = normalize(raws)
        result = detect_outliers(normed)
        ears = {e.ear: e.is_outlier for e in result}
        # 15 should be flagged (above mean+2*std)
        self.assertTrue(ears[15.0])


# ─── build_report stats tests ──────────────────────────────────────────────

class TestBuildReport(unittest.TestCase):

    def _raws(self, vals, comp="simple", quality="HIGH"):
        return [RawAPY("S", "P", f"p{i}", v, comp, quality) for i, v in enumerate(vals)]

    def test_mean_ear_correct(self):
        raws = self._raws([4.0, 6.0])
        report = build_report(raws)
        self.assertAlmostEqual(report.mean_ear, 5.0)

    def test_median_ear_odd(self):
        raws = self._raws([1.0, 3.0, 5.0])
        report = build_report(raws)
        self.assertAlmostEqual(report.median_ear, 3.0)

    def test_median_ear_even(self):
        raws = self._raws([2.0, 4.0, 6.0, 8.0])
        report = build_report(raws)
        self.assertAlmostEqual(report.median_ear, 5.0)

    def test_std_all_same(self):
        raws = self._raws([5.0, 5.0, 5.0, 5.0])
        report = build_report(raws)
        self.assertAlmostEqual(report.std_ear, 0.0)
        self.assertEqual(report.outlier_count, 0)

    def test_outlier_not_included_in_stats(self):
        # [5]*5 + [100]: 100 is flagged as outlier, so stats computed on [5]*5
        values = [5.0, 5.0, 5.0, 5.0, 5.0, 100.0]
        raws = self._raws(values)
        report = build_report(raws)
        # mean should be ~5.0 (from non-outlier entries)
        self.assertAlmostEqual(report.mean_ear, 5.0, places=0)
        self.assertGreater(report.outlier_count, 0)

    def test_highest_quality_adjusted_picks_max(self):
        raws = [
            RawAPY("S", "P", "p0", 5.0, "simple", "LOW"),    # qa = 5*30/100=1.5
            RawAPY("S", "P", "p1", 6.0, "simple", "HIGH"),   # qa = 6*90/100=5.4
            RawAPY("S", "P", "p2", 4.0, "simple", "MEDIUM"), # qa = 4*60/100=2.4
        ]
        report = build_report(raws)
        self.assertEqual(report.highest_quality_adjusted.pool, "p1")

    def test_highest_ear_picks_max(self):
        raws = self._raws([3.0, 7.0, 5.0])
        report = build_report(raws)
        self.assertAlmostEqual(report.highest_ear.ear, 7.0)

    def test_highest_ear_can_be_outlier(self):
        values = [5.0, 5.0, 5.0, 100.0]
        raws = self._raws(values)
        report = build_report(raws)
        self.assertAlmostEqual(report.highest_ear.ear, 100.0)

    def test_empty_input_builds_report(self):
        report = build_report([])
        self.assertEqual(len(report.entries), 0)
        self.assertEqual(report.outlier_count, 0)

    def test_threshold_high(self):
        raws = self._raws([4.0, 6.0, 5.0])
        report = build_report(raws)
        expected_hi = report.mean_ear + 2 * report.std_ear
        self.assertAlmostEqual(report.outlier_threshold_high, expected_hi)

    def test_threshold_low_non_negative(self):
        raws = self._raws([4.0, 6.0, 5.0])
        report = build_report(raws)
        self.assertGreaterEqual(report.outlier_threshold_low, 0.0)

    def test_entries_count_matches_input(self):
        raws = self._raws([1.0, 2.0, 3.0, 4.0])
        report = build_report(raws)
        self.assertEqual(len(report.entries), 4)


# ─── compare_sources tests ─────────────────────────────────────────────────

class TestCompareSources(unittest.TestCase):

    def test_two_sources_separate_correctly(self):
        raws = [
            RawAPY("Alpha", "P", "p0", 4.0, "simple", "HIGH"),
            RawAPY("Alpha", "P", "p1", 6.0, "simple", "HIGH"),
            RawAPY("Beta", "P", "p2", 10.0, "simple", "HIGH"),
        ]
        report = build_report(raws)
        sources = compare_sources(report)
        self.assertIn("Alpha", sources)
        self.assertIn("Beta", sources)
        self.assertAlmostEqual(sources["Alpha"], 5.0)
        self.assertAlmostEqual(sources["Beta"], 10.0)

    def test_single_source_avg_is_ear(self):
        raws = [RawAPY("X", "P", f"p{i}", 5.0, "simple", "HIGH") for i in range(3)]
        report = build_report(raws)
        sources = compare_sources(report)
        self.assertAlmostEqual(sources["X"], 5.0)

    def test_empty_report_returns_empty_dict(self):
        report = build_report([])
        sources = compare_sources(report)
        self.assertEqual(sources, {})


# ─── Save/Load + ring-buffer tests ────────────────────────────────────────

class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_apy_log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _raws(self, n=3):
        return [RawAPY("S", "P", f"p{i}", float(i + 1) * 2, "simple", "HIGH") for i in range(n)]

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(load_history(self.log_path), [])

    def test_save_creates_file(self):
        report = build_report(self._raws())
        save_results(report, self.log_path)
        self.assertTrue(os.path.exists(self.log_path))

    def test_load_after_save_has_one_entry(self):
        report = build_report(self._raws())
        save_results(report, self.log_path)
        history = load_history(self.log_path)
        self.assertEqual(len(history), 1)

    def test_multiple_saves_accumulate(self):
        for _ in range(3):
            report = build_report(self._raws())
            save_results(report, self.log_path)
        self.assertEqual(len(load_history(self.log_path)), 3)

    def test_ring_buffer_cap_100(self):
        for _ in range(110):
            report = build_report(self._raws(1))
            save_results(report, self.log_path)
        history = load_history(self.log_path)
        self.assertEqual(len(history), 100)

    def test_saved_to_field_set(self):
        report = build_report(self._raws())
        saved = save_results(report, self.log_path)
        self.assertIn(self.log_path, saved.saved_to)

    def test_saved_report_has_mean_ear(self):
        report = build_report(self._raws())
        save_results(report, self.log_path)
        history = load_history(self.log_path)
        self.assertIn("mean_ear", history[0])

    def test_json_valid_after_save(self):
        report = build_report(self._raws())
        save_results(report, self.log_path)
        with open(self.log_path, "r") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_malformed_file_returns_empty(self):
        with open(self.log_path, "w") as f:
            f.write("not json{{")
        self.assertEqual(load_history(self.log_path), [])


# ─── Edge case tests ───────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def test_all_same_apy_no_std(self):
        raws = [RawAPY("S", "P", f"p{i}", 5.0, "simple", "HIGH") for i in range(5)]
        report = build_report(raws)
        self.assertAlmostEqual(report.std_ear, 0.0)
        self.assertEqual(report.outlier_count, 0)

    def test_single_entry_report(self):
        raws = [RawAPY("S", "P", "p", 8.0, "simple", "HIGH")]
        report = build_report(raws)
        self.assertEqual(len(report.entries), 1)
        self.assertEqual(report.outlier_count, 0)
        self.assertFalse(report.entries[0].is_outlier)

    def test_two_entries_no_outliers(self):
        raws = [RawAPY("S", "P", f"p{i}", float(i + 3), "simple", "HIGH") for i in range(2)]
        report = build_report(raws)
        self.assertEqual(report.outlier_count, 0)

    def test_zero_apy_entries(self):
        raws = [RawAPY("S", "P", f"p{i}", 0.0, "daily", "MEDIUM") for i in range(4)]
        report = build_report(raws)
        self.assertAlmostEqual(report.mean_ear, 0.0)

    def test_mixed_compounding_types(self):
        raws = [
            RawAPY("S", "P", "p0", 12.0, "simple", "HIGH"),
            RawAPY("S", "P", "p1", 12.0, "monthly", "HIGH"),
            RawAPY("S", "P", "p2", 12.0, "daily", "HIGH"),
            RawAPY("S", "P", "p3", 12.0, "continuous", "HIGH"),
        ]
        report = build_report(raws)
        ears = [e.ear for e in report.entries]
        # continuous > daily > monthly > simple
        self.assertGreater(ears[3], ears[2])
        self.assertGreater(ears[2], ears[1])
        self.assertGreater(ears[1], ears[0])


# ─── Helper function tests ─────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_basic(self):
        self.assertAlmostEqual(_mean([2.0, 4.0, 6.0]), 4.0)

    def test_std_single(self):
        self.assertAlmostEqual(_std([5.0], 5.0), 0.0)

    def test_std_basic(self):
        vals = [2.0, 4.0, 6.0]
        mu = _mean(vals)
        s = _std(vals, mu)
        # Population std of [2,4,6] with mean 4 = sqrt(8/3)
        self.assertAlmostEqual(s, math.sqrt(8.0 / 3.0), places=5)

    def test_median_single(self):
        self.assertEqual(_median([7.0]), 7.0)

    def test_median_odd(self):
        self.assertEqual(_median([1.0, 3.0, 5.0]), 3.0)

    def test_median_even(self):
        self.assertAlmostEqual(_median([1.0, 3.0, 5.0, 7.0]), 4.0)

    def test_median_empty(self):
        self.assertEqual(_median([]), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
