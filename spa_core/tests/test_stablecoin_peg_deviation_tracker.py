"""
Tests for MP-744: StablecoinPegDeviationTracker
>=60 test cases using unittest only (no pytest, no numpy, no pandas).
Tempfile-based persistence — production data/ is never touched.
"""

import json
import math
import os
import sys
import unittest
import tempfile
from pathlib import Path

# Make spa_core importable when run directly from spa_core/tests.
_SPA_ROOT = Path(__file__).resolve().parents[2]
if str(_SPA_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPA_ROOT))

from spa_core.analytics.stablecoin_peg_deviation_tracker import (  # noqa: E402
    MAX_ENTRIES,
    SEVERITY_MINOR_BPS,
    SEVERITY_MODERATE_BPS,
    SEVERITY_SEVERE_BPS,
    SEVERITY_STABLE_BPS,
    PegDeviationReport,
    StablecoinPegDeviationTracker,
)


class TestMean(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_empty(self):
        self.assertEqual(self.m._mean([]), 0.0)

    def test_single(self):
        self.assertEqual(self.m._mean([1.0]), 1.0)

    def test_average(self):
        self.assertAlmostEqual(self.m._mean([0.9, 1.0, 1.1]), 1.0)

    def test_off_peg(self):
        self.assertAlmostEqual(self.m._mean([0.98, 0.96]), 0.97)


class TestStdev(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_fewer_than_two(self):
        self.assertEqual(self.m._sample_stdev([1.0], 1.0), 0.0)

    def test_empty(self):
        self.assertEqual(self.m._sample_stdev([], 0.0), 0.0)

    def test_zero_variance(self):
        self.assertEqual(self.m._sample_stdev([1.0, 1.0, 1.0], 1.0), 0.0)

    def test_two_points(self):
        # values 0 and 2, mean 1, sample var = 2, stdev sqrt2
        self.assertAlmostEqual(self.m._sample_stdev([0.0, 2.0], 1.0), math.sqrt(2.0))

    def test_known_value(self):
        xs = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        mean = sum(xs) / len(xs)
        self.assertAlmostEqual(
            self.m._sample_stdev(xs, mean), math.sqrt(32 / 7), places=6
        )


class TestDeviation(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_pct_above_peg(self):
        self.assertAlmostEqual(self.m._deviation_pct(1.01, 1.0), 1.0)

    def test_pct_below_peg(self):
        self.assertAlmostEqual(self.m._deviation_pct(0.99, 1.0), -1.0)

    def test_pct_at_peg(self):
        self.assertEqual(self.m._deviation_pct(1.0, 1.0), 0.0)

    def test_pct_zero_peg_guard(self):
        self.assertEqual(self.m._deviation_pct(1.0, 0.0), 0.0)

    def test_pct_nonunit_peg(self):
        # peg 0.5, price 0.55 -> +10%
        self.assertAlmostEqual(self.m._deviation_pct(0.55, 0.5), 10.0)

    def test_bps_above(self):
        # 1% == 100 bps
        self.assertAlmostEqual(self.m._deviation_bps(1.01, 1.0), 100.0)

    def test_bps_below_is_abs(self):
        self.assertAlmostEqual(self.m._deviation_bps(0.99, 1.0), 100.0)

    def test_bps_small(self):
        # 0.1% == 10 bps
        self.assertAlmostEqual(self.m._deviation_bps(1.001, 1.0), 10.0)


class TestLongestRun(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_empty(self):
        self.assertEqual(self.m._longest_run([]), 0)

    def test_no_true(self):
        self.assertEqual(self.m._longest_run([False, False, False]), 0)

    def test_all_true(self):
        self.assertEqual(self.m._longest_run([True, True, True]), 3)

    def test_single_true(self):
        self.assertEqual(self.m._longest_run([False, True, False]), 1)

    def test_two_runs(self):
        self.assertEqual(self.m._longest_run([True, True, False, True]), 2)

    def test_run_at_end(self):
        self.assertEqual(self.m._longest_run([True, False, True, True, True]), 3)

    def test_interrupted(self):
        self.assertEqual(
            self.m._longest_run([True, True, False, True, True, True, False]), 3
        )


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_stable_zero(self):
        self.assertEqual(self.m._classify(0.0), "STABLE")

    def test_stable_just_below_25(self):
        self.assertEqual(self.m._classify(24.999), "STABLE")

    def test_minor_at_25(self):
        self.assertEqual(self.m._classify(SEVERITY_STABLE_BPS), "MINOR")

    def test_minor_mid(self):
        self.assertEqual(self.m._classify(40.0), "MINOR")

    def test_minor_just_below_50(self):
        self.assertEqual(self.m._classify(49.999), "MINOR")

    def test_moderate_at_50(self):
        self.assertEqual(self.m._classify(SEVERITY_MINOR_BPS), "MODERATE")

    def test_moderate_mid(self):
        self.assertEqual(self.m._classify(120.0), "MODERATE")

    def test_moderate_just_below_200(self):
        self.assertEqual(self.m._classify(199.999), "MODERATE")

    def test_severe_at_200(self):
        self.assertEqual(self.m._classify(SEVERITY_MODERATE_BPS), "SEVERE")

    def test_severe_mid(self):
        self.assertEqual(self.m._classify(350.0), "SEVERE")

    def test_severe_just_below_500(self):
        self.assertEqual(self.m._classify(499.999), "SEVERE")

    def test_critical_at_500(self):
        self.assertEqual(self.m._classify(SEVERITY_SEVERE_BPS), "CRITICAL")

    def test_critical_high(self):
        self.assertEqual(self.m._classify(2000.0), "CRITICAL")


class TestAnalyzeGuards(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_empty_samples_zero(self):
        r = self.m.analyze([])
        self.assertEqual(r.samples, 0)

    def test_empty_tier_unknown(self):
        r = self.m.analyze([])
        self.assertEqual(r.severity_tier, "UNKNOWN")

    def test_empty_current_price_none(self):
        r = self.m.analyze([])
        self.assertIsNone(r.current_price)

    def test_empty_min_max_none(self):
        r = self.m.analyze([])
        self.assertIsNone(r.min_price)
        self.assertIsNone(r.max_price)

    def test_empty_numeric_zero(self):
        r = self.m.analyze([])
        self.assertEqual(r.current_deviation_pct, 0.0)
        self.assertEqual(r.current_deviation_bps, 0.0)
        self.assertEqual(r.mean_price, 0.0)
        self.assertEqual(r.stdev_price, 0.0)
        self.assertEqual(r.longest_depeg_run, 0)

    def test_empty_advisory_present(self):
        r = self.m.analyze([])
        self.assertTrue(len(r.advisory) > 0)

    def test_returns_report_type(self):
        self.assertIsInstance(self.m.analyze([1.0]), PegDeviationReport)

    def test_single_sample_ok(self):
        r = self.m.analyze([1.0])
        self.assertEqual(r.samples, 1)
        self.assertEqual(r.stdev_price, 0.0)

    def test_single_sample_tier(self):
        r = self.m.analyze([1.0])
        self.assertEqual(r.severity_tier, "STABLE")

    def test_single_sample_current(self):
        r = self.m.analyze([0.997])
        self.assertEqual(r.current_price, 0.997)


class TestAnalyzePerfectPeg(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_all_at_peg(self):
        r = self.m.analyze([1.0, 1.0, 1.0, 1.0])
        self.assertEqual(r.current_deviation_pct, 0.0)
        self.assertEqual(r.current_deviation_bps, 0.0)
        self.assertEqual(r.severity_tier, "STABLE")

    def test_perfect_peg_no_depeg(self):
        r = self.m.analyze([1.0, 1.0, 1.0])
        self.assertEqual(r.samples_below_threshold, 0)
        self.assertEqual(r.pct_time_depegged, 0.0)
        self.assertEqual(r.longest_depeg_run, 0)

    def test_perfect_peg_zero_stdev(self):
        r = self.m.analyze([1.0, 1.0, 1.0])
        self.assertEqual(r.stdev_price, 0.0)

    def test_mean_at_peg(self):
        r = self.m.analyze([1.0, 1.0])
        self.assertEqual(r.mean_price, 1.0)


class TestAnalyzeMildDepeg(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_mild_current_deviation(self):
        # current 0.998 -> -0.2% -> 20 bps -> STABLE
        r = self.m.analyze([1.0, 0.999, 0.998])
        self.assertAlmostEqual(r.current_deviation_bps, 20.0, places=4)
        self.assertEqual(r.severity_tier, "STABLE")

    def test_minor_tier(self):
        # current 0.9965 -> -0.35% -> 35 bps -> MINOR
        r = self.m.analyze([1.0, 0.9965])
        self.assertEqual(r.severity_tier, "MINOR")

    def test_signed_current_deviation_negative(self):
        r = self.m.analyze([1.0, 0.995])
        self.assertLess(r.current_deviation_pct, 0.0)

    def test_signed_current_deviation_positive(self):
        r = self.m.analyze([1.0, 1.005])
        self.assertGreater(r.current_deviation_pct, 0.0)

    def test_min_max_price(self):
        r = self.m.analyze([1.0, 0.99, 1.02, 0.97])
        self.assertEqual(r.min_price, 0.97)
        self.assertEqual(r.max_price, 1.02)


class TestAnalyzeSevereDepeg(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_severe_tier(self):
        # current 0.97 -> -3% -> 300 bps -> SEVERE
        r = self.m.analyze([1.0, 0.99, 0.97])
        self.assertEqual(r.severity_tier, "SEVERE")

    def test_critical_tier(self):
        # current 0.90 -> -10% -> 1000 bps -> CRITICAL
        r = self.m.analyze([1.0, 0.95, 0.90])
        self.assertEqual(r.severity_tier, "CRITICAL")

    def test_critical_advisory(self):
        r = self.m.analyze([1.0, 0.5])
        self.assertIn("CRITICAL", r.advisory)

    def test_moderate_tier(self):
        # current 0.99 -> -1% -> 100 bps -> MODERATE
        r = self.m.analyze([1.0, 0.99])
        self.assertEqual(r.severity_tier, "MODERATE")


class TestMaxDeviation(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_max_deviation_signed_negative(self):
        # largest |dev| at 0.90 -> -10%
        r = self.m.analyze([1.0, 0.90, 1.0])
        self.assertAlmostEqual(r.max_deviation_pct, -10.0, places=4)

    def test_max_deviation_signed_positive(self):
        # largest |dev| at 1.08 -> +8%
        r = self.m.analyze([1.0, 1.08, 1.0])
        self.assertAlmostEqual(r.max_deviation_pct, 8.0, places=4)

    def test_max_deviation_picks_largest_abs(self):
        # -5% vs +3%: picks -5%
        r = self.m.analyze([1.0, 0.95, 1.03])
        self.assertAlmostEqual(r.max_deviation_pct, -5.0, places=4)

    def test_max_deviation_at_peg(self):
        r = self.m.analyze([1.0, 1.0, 1.0])
        self.assertEqual(r.max_deviation_pct, 0.0)


class TestThresholdCounting(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_count_beyond_default_threshold(self):
        # threshold 50 bps == 0.5%. 0.99 (100bps) and 0.985 (150bps) breach;
        # 1.0 and 0.998 (20bps) do not.
        r = self.m.analyze([1.0, 0.998, 0.99, 0.985])
        self.assertEqual(r.samples_below_threshold, 2)

    def test_pct_time_depegged(self):
        r = self.m.analyze([1.0, 0.998, 0.99, 0.985])
        self.assertAlmostEqual(r.pct_time_depegged, 0.5, places=6)

    def test_threshold_exclusive(self):
        # 40 bps (0.996) is below the 50 bps threshold -> does NOT count (strict >)
        r = self.m.analyze([0.996, 0.996])
        self.assertEqual(r.samples_below_threshold, 0)

    def test_custom_threshold(self):
        # threshold 200 bps; 0.99 (100bps) does not breach, 0.97 (300bps) does
        r = self.m.analyze([0.99, 0.97], depeg_threshold_bps=200.0)
        self.assertEqual(r.samples_below_threshold, 1)

    def test_threshold_recorded(self):
        r = self.m.analyze([1.0, 1.0], depeg_threshold_bps=75.0)
        self.assertEqual(r.depeg_threshold_bps, 75.0)

    def test_all_depegged(self):
        r = self.m.analyze([0.90, 0.91, 0.89])
        self.assertEqual(r.samples_below_threshold, 3)
        self.assertEqual(r.pct_time_depegged, 1.0)


class TestLongestDepegRunIntegration(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_run_consecutive(self):
        # breaches at indices 1,2,3 (0.99 each) -> run 3
        r = self.m.analyze([1.0, 0.99, 0.99, 0.99, 1.0])
        self.assertEqual(r.longest_depeg_run, 3)

    def test_run_interrupted(self):
        # breach, recover, breach breach -> longest 2
        r = self.m.analyze([0.99, 1.0, 0.99, 0.99])
        self.assertEqual(r.longest_depeg_run, 2)

    def test_no_run(self):
        r = self.m.analyze([1.0, 0.999, 1.0])
        self.assertEqual(r.longest_depeg_run, 0)


class TestRounding(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_all_floats_6dp(self):
        r = self.m.analyze([1.0001234567, 0.9987654321, 0.9991111111])
        for v in (
            r.current_price,
            r.current_deviation_pct,
            r.current_deviation_bps,
            r.max_deviation_pct,
            r.min_price,
            r.max_price,
            r.mean_price,
            r.stdev_price,
            r.pct_time_depegged,
        ):
            self.assertEqual(v, round(v, 6))

    def test_generated_at_set(self):
        r = self.m.analyze([1.0, 1.0])
        self.assertTrue(r.generated_at.endswith("Z"))

    def test_peg_recorded(self):
        r = self.m.analyze([1.0, 1.0], peg=1.0)
        self.assertEqual(r.peg, 1.0)

    def test_symbol_recorded(self):
        r = self.m.analyze([1.0, 1.0], symbol="DAI")
        self.assertEqual(r.symbol, "DAI")


class TestNonUnitPeg(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_euro_peg(self):
        # peg 1.08 (EUR-ish); price exactly at peg -> stable
        r = self.m.analyze([1.08, 1.08], peg=1.08, symbol="EURS")
        self.assertEqual(r.severity_tier, "STABLE")
        self.assertEqual(r.current_deviation_pct, 0.0)

    def test_euro_peg_deviation(self):
        # peg 1.08, price 1.0908 -> +1% -> 100 bps -> MODERATE
        r = self.m.analyze([1.08, 1.0908], peg=1.08)
        self.assertAlmostEqual(r.current_deviation_bps, 100.0, places=3)


class TestAdvisory(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_stable_advisory(self):
        r = self.m.analyze([1.0, 1.0])
        self.assertIn("holding peg", r.advisory)

    def test_minor_advisory(self):
        r = self.m.analyze([1.0, 0.9965])
        self.assertIn("minor", r.advisory.lower())

    def test_severe_advisory(self):
        r = self.m.analyze([1.0, 0.97])
        self.assertIn("severe", r.advisory.lower())


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "depeg.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_empty(self):
        self.assertEqual(self.m.load_history(self.path), [])

    def test_save_then_load(self):
        self.m.save_report(self.m.analyze([1.0, 0.999]), self.path)
        self.assertEqual(len(self.m.load_history(self.path)), 1)

    def test_saved_fields(self):
        self.m.save_report(self.m.analyze([1.0, 0.999]), self.path)
        e = self.m.load_history(self.path)[0]
        self.assertIn("severity_tier", e)
        self.assertIn("current_deviation_bps", e)
        self.assertIn("longest_depeg_run", e)
        self.assertIn("advisory", e)

    def test_append_multiple(self):
        for _ in range(4):
            self.m.save_report(self.m.analyze([1.0, 0.999]), self.path)
        self.assertEqual(len(self.m.load_history(self.path)), 4)

    def test_ring_buffer_cap(self):
        for _ in range(MAX_ENTRIES + 7):
            self.m.save_report(self.m.analyze([1.0, 0.999]), self.path)
        self.assertEqual(len(self.m.load_history(self.path)), MAX_ENTRIES)

    def test_corrupt_returns_empty(self):
        self.path.write_text("garbage{{")
        self.assertEqual(self.m.load_history(self.path), [])

    def test_no_tmp_left(self):
        self.m.save_report(self.m.analyze([1.0, 0.999]), self.path)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_no_tmp_left_after_many(self):
        for _ in range(5):
            self.m.save_report(self.m.analyze([1.0, 0.999]), self.path)
        leftovers = list(Path(self.tmp.name).glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_valid_json(self):
        self.m.save_report(self.m.analyze([1.0, 0.999]), self.path)
        json.loads(self.path.read_text())

    def test_creates_parent_dir(self):
        nested = Path(self.tmp.name) / "a" / "b" / "depeg.json"
        self.m.save_report(self.m.analyze([1.0, 0.999]), nested)
        self.assertTrue(nested.exists())

    def test_ring_buffer_keeps_latest(self):
        for i in range(MAX_ENTRIES + 3):
            r = self.m.analyze([1.0, 1.0], symbol=f"S{i}")
            self.m.save_report(r, self.path)
        hist = self.m.load_history(self.path)
        self.assertEqual(hist[-1]["symbol"], f"S{MAX_ENTRIES + 2}")


class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.m = StablecoinPegDeviationTracker()

    def test_slightly_depegging_series(self):
        prices = [1.0001, 0.9998, 0.9995, 0.9990, 0.9982, 0.9975, 0.9988, 0.9993]
        r = self.m.analyze(prices, peg=1.0, symbol="USDC")
        self.assertEqual(r.samples, 8)
        self.assertIn(
            r.severity_tier,
            {"STABLE", "MINOR", "MODERATE", "SEVERE", "CRITICAL"},
        )
        self.assertTrue(len(r.advisory) > 0)

    def test_tier_in_known_set(self):
        r = self.m.analyze([1.0, 0.99, 0.98])
        self.assertIn(
            r.severity_tier,
            {"STABLE", "MINOR", "MODERATE", "SEVERE", "CRITICAL", "UNKNOWN"},
        )

    def test_recovery_series_current_stable(self):
        # depegs hard then recovers to peg; current is at peg -> STABLE
        r = self.m.analyze([1.0, 0.92, 0.95, 0.99, 1.0])
        self.assertEqual(r.severity_tier, "STABLE")
        # but it did spend time depegged
        self.assertGreater(r.samples_below_threshold, 0)

    def test_demo_series_consistency(self):
        prices = [1.0, 0.99, 0.99, 0.99, 1.0]
        r = self.m.analyze(prices)
        self.assertEqual(r.longest_depeg_run, 3)
        self.assertEqual(r.samples_below_threshold, 3)


if __name__ == "__main__":
    unittest.main()
