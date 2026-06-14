"""
Tests for MP-763: ApyVolatilityForecaster
≥50 test cases using unittest only (no pytest, no numpy, no pandas).
Tempfile-based persistence — production data/ is never touched.
"""

import json
import math
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.apy_volatility_forecaster import (
    CV_MODERATE,
    CV_STABLE,
    CV_VOLATILE,
    DEFAULT_BAND_K,
    DEFAULT_EWMA_LAMBDA,
    MAX_ENTRIES,
    ApyVolatilityForecaster,
    ApyVolatilityReport,
)


class TestMean(unittest.TestCase):
    def setUp(self):
        self.f = ApyVolatilityForecaster()

    def test_empty(self):
        self.assertEqual(self.f._mean([]), 0.0)

    def test_single(self):
        self.assertEqual(self.f._mean([0.05]), 0.05)

    def test_average(self):
        self.assertAlmostEqual(self.f._mean([0.1, 0.2, 0.3]), 0.2)

    def test_negative(self):
        self.assertAlmostEqual(self.f._mean([-0.1, 0.1]), 0.0)


class TestStdev(unittest.TestCase):
    def setUp(self):
        self.f = ApyVolatilityForecaster()

    def test_fewer_than_two(self):
        self.assertEqual(self.f._sample_stdev([0.1], 0.1), 0.0)

    def test_empty(self):
        self.assertEqual(self.f._sample_stdev([], 0.0), 0.0)

    def test_zero_variance(self):
        self.assertEqual(self.f._sample_stdev([0.05, 0.05, 0.05], 0.05), 0.0)

    def test_two_points(self):
        # values 0 and 2, mean 1 -> sample var ((1)+(1))/1 = 2 -> stdev sqrt2
        self.assertAlmostEqual(self.f._sample_stdev([0.0, 2.0], 1.0), math.sqrt(2.0))

    def test_known_value(self):
        xs = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        m = sum(xs) / len(xs)
        self.assertAlmostEqual(self.f._sample_stdev(xs, m), math.sqrt(32 / 7), places=6)


class TestEwmaVolatility(unittest.TestCase):
    def setUp(self):
        self.f = ApyVolatilityForecaster()

    def test_constant_series_zero(self):
        self.assertAlmostEqual(
            self.f._ewma_volatility([0.05, 0.05, 0.05], 0.05, 0.94), 0.0
        )

    def test_manual_two_points(self):
        xs = [0.0, 0.02]
        mean = 0.01
        lam = 0.94
        var = 0.0
        for x in xs:
            var = lam * var + (1 - lam) * (x - mean) ** 2
        self.assertAlmostEqual(
            self.f._ewma_volatility(xs, mean, lam), math.sqrt(var), places=9
        )

    def test_positive_for_varying(self):
        self.assertGreater(
            self.f._ewma_volatility([0.01, 0.05, 0.02], 0.02666, 0.94), 0.0
        )

    def test_lambda_affects_result(self):
        xs = [0.01, 0.05, 0.02, 0.06]
        mean = sum(xs) / len(xs)
        a = self.f._ewma_volatility(xs, mean, 0.90)
        b = self.f._ewma_volatility(xs, mean, 0.99)
        self.assertNotAlmostEqual(a, b, places=6)


class TestClampLambda(unittest.TestCase):
    def setUp(self):
        self.f = ApyVolatilityForecaster()

    def test_in_range(self):
        self.assertEqual(self.f._clamp_lambda(0.5), 0.5)

    def test_zero_defaults(self):
        self.assertEqual(self.f._clamp_lambda(0.0), DEFAULT_EWMA_LAMBDA)

    def test_one_defaults(self):
        self.assertEqual(self.f._clamp_lambda(1.0), DEFAULT_EWMA_LAMBDA)

    def test_negative_defaults(self):
        self.assertEqual(self.f._clamp_lambda(-0.3), DEFAULT_EWMA_LAMBDA)

    def test_above_one_defaults(self):
        self.assertEqual(self.f._clamp_lambda(1.5), DEFAULT_EWMA_LAMBDA)

    def test_near_one_kept(self):
        self.assertEqual(self.f._clamp_lambda(0.99), 0.99)


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.f = ApyVolatilityForecaster()

    def test_stable_low(self):
        self.assertEqual(self.f._classify(0.05), "STABLE")

    def test_stable_just_below_boundary(self):
        self.assertEqual(self.f._classify(0.0999), "STABLE")

    def test_moderate_at_boundary(self):
        self.assertEqual(self.f._classify(CV_STABLE), "MODERATE")

    def test_moderate_mid(self):
        self.assertEqual(self.f._classify(0.20), "MODERATE")

    def test_volatile_at_boundary(self):
        self.assertEqual(self.f._classify(CV_MODERATE), "VOLATILE")

    def test_volatile_mid(self):
        self.assertEqual(self.f._classify(0.40), "VOLATILE")

    def test_highly_volatile_at_boundary(self):
        self.assertEqual(self.f._classify(CV_VOLATILE), "HIGHLY_VOLATILE")

    def test_highly_volatile_high(self):
        self.assertEqual(self.f._classify(1.5), "HIGHLY_VOLATILE")

    def test_just_below_volatile(self):
        self.assertEqual(self.f._classify(0.2499), "MODERATE")

    def test_just_below_highly_volatile(self):
        self.assertEqual(self.f._classify(0.4999), "VOLATILE")


class TestAnalyzeGuards(unittest.TestCase):
    def setUp(self):
        self.f = ApyVolatilityForecaster()

    def test_empty(self):
        r = self.f.analyze([])
        self.assertEqual(r.stability_tier, "UNKNOWN")
        self.assertEqual(r.num_observations, 0)

    def test_single(self):
        r = self.f.analyze([0.05])
        self.assertEqual(r.stability_tier, "UNKNOWN")

    def test_single_advisory(self):
        r = self.f.analyze([0.05])
        self.assertTrue(any("at least 2" in a for a in r.advisory))

    def test_single_latest_recorded(self):
        r = self.f.analyze([0.05])
        self.assertEqual(r.latest, 0.05)

    def test_empty_latest_zero(self):
        r = self.f.analyze([])
        self.assertEqual(r.latest, 0.0)

    def test_guard_zero_stats(self):
        r = self.f.analyze([0.05])
        self.assertEqual(r.realized_volatility, 0.0)
        self.assertEqual(r.ewma_volatility, 0.0)
        self.assertEqual(r.forecast_low, 0.0)
        self.assertEqual(r.forecast_high, 0.0)
        self.assertEqual(r.trend, 0.0)

    def test_returns_report_type(self):
        self.assertIsInstance(self.f.analyze([0.05, 0.06]), ApyVolatilityReport)


class TestAnalyzeMath(unittest.TestCase):
    def setUp(self):
        self.f = ApyVolatilityForecaster()

    def test_num_observations(self):
        r = self.f.analyze([0.05, 0.06, 0.04, 0.07])
        self.assertEqual(r.num_observations, 4)

    def test_mean_value(self):
        r = self.f.analyze([0.04, 0.06])
        self.assertAlmostEqual(r.mean, 0.05, places=6)

    def test_realized_volatility_known(self):
        r = self.f.analyze([0.0, 0.02])
        # sample stdev of [0,0.02] = sqrt(((0-0.01)^2+(0.02-0.01)^2)/1) = 0.0141421...
        expected = math.sqrt(((0.0 - 0.01) ** 2 + (0.02 - 0.01) ** 2) / 1)
        self.assertAlmostEqual(r.realized_volatility, round(expected, 6), places=6)

    def test_latest_value(self):
        r = self.f.analyze([0.05, 0.06, 0.07])
        self.assertEqual(r.latest, 0.07)

    def test_trend_up(self):
        r = self.f.analyze([0.04, 0.05, 0.06])
        self.assertAlmostEqual(r.trend, 0.02, places=6)

    def test_trend_down(self):
        r = self.f.analyze([0.06, 0.05, 0.04])
        self.assertAlmostEqual(r.trend, -0.02, places=6)

    def test_trend_flat(self):
        r = self.f.analyze([0.05, 0.04, 0.05])
        self.assertAlmostEqual(r.trend, 0.0, places=6)

    def test_constant_series_zero_vol(self):
        r = self.f.analyze([0.05, 0.05, 0.05])
        self.assertEqual(r.realized_volatility, 0.0)
        self.assertEqual(r.ewma_volatility, 0.0)

    def test_constant_series_cv_zero(self):
        r = self.f.analyze([0.05, 0.05, 0.05])
        self.assertEqual(r.coefficient_of_variation, 0.0)

    def test_constant_series_stable(self):
        r = self.f.analyze([0.05, 0.05, 0.05])
        self.assertEqual(r.stability_tier, "STABLE")

    def test_cv_zero_when_mean_zero(self):
        r = self.f.analyze([-0.02, 0.02])  # mean 0
        self.assertEqual(r.mean, 0.0)
        self.assertEqual(r.coefficient_of_variation, 0.0)

    def test_cv_positive(self):
        r = self.f.analyze([0.04, 0.06, 0.05, 0.08, 0.03])
        self.assertGreater(r.coefficient_of_variation, 0.0)

    def test_forecast_band_symmetric(self):
        r = self.f.analyze([0.04, 0.06, 0.05, 0.08])
        mid = (r.forecast_low + r.forecast_high) / 2
        self.assertAlmostEqual(mid, r.latest, places=6)

    def test_forecast_band_width(self):
        r = self.f.analyze([0.04, 0.06, 0.05, 0.08], band_k=2.0)
        expected_width = 2 * 2.0 * r.ewma_volatility
        self.assertAlmostEqual(
            r.forecast_high - r.forecast_low, round(expected_width, 6), places=5
        )

    def test_band_k_widens(self):
        narrow = self.f.analyze([0.04, 0.06, 0.05, 0.08], band_k=1.0)
        wide = self.f.analyze([0.04, 0.06, 0.05, 0.08], band_k=3.0)
        self.assertGreater(
            wide.forecast_high - wide.forecast_low,
            narrow.forecast_high - narrow.forecast_low,
        )

    def test_default_lambda_used(self):
        # out-of-range lambda falls back to default; equal result
        a = self.f.analyze([0.04, 0.06, 0.05, 0.08], ewma_lambda=2.0)
        b = self.f.analyze([0.04, 0.06, 0.05, 0.08], ewma_lambda=DEFAULT_EWMA_LAMBDA)
        self.assertEqual(a.ewma_volatility, b.ewma_volatility)


class TestAdvisory(unittest.TestCase):
    def setUp(self):
        self.f = ApyVolatilityForecaster()

    def test_stable_advisory(self):
        r = self.f.analyze([0.0500, 0.0501, 0.0499, 0.0500])
        self.assertTrue(any("Stable APY" in a for a in r.advisory))

    def test_highly_volatile_advisory(self):
        r = self.f.analyze([0.01, 0.10, 0.02, 0.15, 0.005])
        self.assertTrue(any("Highly volatile" in a for a in r.advisory))

    def test_trend_up_advisory(self):
        r = self.f.analyze([0.04, 0.05, 0.06])
        self.assertTrue(any("upward" in a for a in r.advisory))

    def test_trend_down_advisory(self):
        r = self.f.analyze([0.06, 0.05, 0.04])
        self.assertTrue(any("downward" in a for a in r.advisory))

    def test_trend_flat_advisory(self):
        r = self.f.analyze([0.05, 0.04, 0.05])
        self.assertTrue(any("flat" in a for a in r.advisory))

    def test_ewma_relationship_advisory_present(self):
        r = self.f.analyze([0.04, 0.06, 0.05, 0.08])
        self.assertTrue(
            any("EWMA" in a or "ewma" in a.lower() for a in r.advisory)
        )

    def test_advisory_non_empty(self):
        r = self.f.analyze([0.04, 0.06, 0.05])
        self.assertTrue(len(r.advisory) >= 1)


class TestRounding(unittest.TestCase):
    def setUp(self):
        self.f = ApyVolatilityForecaster()

    def test_all_6dp(self):
        r = self.f.analyze([0.0411111, 0.0622222, 0.0533333])
        for v in (r.mean, r.realized_volatility, r.ewma_volatility, r.latest,
                  r.coefficient_of_variation, r.forecast_low, r.forecast_high,
                  r.trend):
            self.assertEqual(v, round(v, 6))

    def test_generated_at_set(self):
        r = self.f.analyze([0.05, 0.06])
        self.assertTrue(r.generated_at.endswith("Z"))

    def test_default_band_k_constant(self):
        self.assertEqual(DEFAULT_BAND_K, 2.0)

    def test_default_lambda_constant(self):
        self.assertEqual(DEFAULT_EWMA_LAMBDA, 0.94)


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.f = ApyVolatilityForecaster()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "apyvol.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_missing_empty(self):
        self.assertEqual(self.f.load_history(self.path), [])

    def test_save_then_load(self):
        self.f.save_report(self.f.analyze([0.05, 0.06, 0.04]), self.path)
        self.assertEqual(len(self.f.load_history(self.path)), 1)

    def test_saved_fields(self):
        self.f.save_report(self.f.analyze([0.05, 0.06, 0.04]), self.path)
        e = self.f.load_history(self.path)[0]
        self.assertIn("realized_volatility", e)
        self.assertIn("ewma_volatility", e)
        self.assertIn("stability_tier", e)
        self.assertIn("advisory", e)

    def test_append_multiple(self):
        for _ in range(4):
            self.f.save_report(self.f.analyze([0.05, 0.06]), self.path)
        self.assertEqual(len(self.f.load_history(self.path)), 4)

    def test_ring_buffer_cap(self):
        for _ in range(MAX_ENTRIES + 5):
            self.f.save_report(self.f.analyze([0.05, 0.06]), self.path)
        self.assertEqual(len(self.f.load_history(self.path)), MAX_ENTRIES)

    def test_corrupt_returns_empty(self):
        self.path.write_text("garbage{{")
        self.assertEqual(self.f.load_history(self.path), [])

    def test_no_tmp_left(self):
        self.f.save_report(self.f.analyze([0.05, 0.06]), self.path)
        self.assertFalse(self.path.with_suffix(".tmp").exists())

    def test_valid_json(self):
        self.f.save_report(self.f.analyze([0.05, 0.06]), self.path)
        json.loads(self.path.read_text())

    def test_creates_parent_dir(self):
        nested = Path(self.tmp.name) / "x" / "y" / "apyvol.json"
        self.f.save_report(self.f.analyze([0.05, 0.06]), nested)
        self.assertTrue(nested.exists())

    def test_round_trip_values(self):
        rep = self.f.analyze([0.04, 0.06, 0.05, 0.08])
        self.f.save_report(rep, self.path)
        e = self.f.load_history(self.path)[0]
        self.assertEqual(e["realized_volatility"], rep.realized_volatility)
        self.assertEqual(e["stability_tier"], rep.stability_tier)


class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.f = ApyVolatilityForecaster()

    def test_realistic_series(self):
        apy = [0.052, 0.048, 0.055, 0.061, 0.058, 0.050, 0.047, 0.053]
        r = self.f.analyze(apy)
        self.assertEqual(r.num_observations, 8)
        self.assertIn(r.stability_tier,
                      {"STABLE", "MODERATE", "VOLATILE", "HIGHLY_VOLATILE"})
        self.assertTrue(len(r.advisory) >= 1)

    def test_tier_in_known_set(self):
        r = self.f.analyze([0.05, 0.06, 0.04])
        self.assertIn(
            r.stability_tier,
            {"STABLE", "MODERATE", "VOLATILE", "HIGHLY_VOLATILE", "UNKNOWN"},
        )

    def test_stable_scenario(self):
        r = self.f.analyze([0.0500, 0.0502, 0.0498, 0.0501, 0.0499])
        self.assertEqual(r.stability_tier, "STABLE")

    def test_volatile_scenario(self):
        r = self.f.analyze([0.01, 0.09, 0.02, 0.12, 0.03])
        self.assertIn(r.stability_tier, {"VOLATILE", "HIGHLY_VOLATILE"})

    def test_percent_inputs_work(self):
        # treated numerically; percents instead of fractions
        r = self.f.analyze([5.2, 4.8, 5.5, 6.1, 5.8])
        self.assertGreater(r.realized_volatility, 0.0)
        self.assertEqual(r.num_observations, 5)


if __name__ == "__main__":
    unittest.main()
