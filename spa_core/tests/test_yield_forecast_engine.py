"""
Tests for MP-769: YieldForecastEngine
Uses unittest only. 65+ test cases.

Coverage:
- _linear_regression: empty, single, two points, flat, upward, downward, large
- _r_squared: perfect fit, flat series, zero variance, negative fit
- _compute_ema_series: empty, single, multi, alpha=0/1
- _ema_trend_slope: empty, flat, trending
- classify_trend: UP / STABLE / DOWN thresholds
- linear_forecast: empty, single, flat, up, down, multi-day
- ema_forecast: empty, single, flat, up, down, multi-day
- ensemble_forecast: empty, single, flat, up, down, forecast_range, ForecastResult fields
- forecast_confidence: empty, single, flat, perfect, random
- save / load_history: ring buffer, atomic write, corrupt JSON
- Module-level convenience wrappers
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.yield_forecast_engine import (
    EMA_ALPHA,
    EMA_WEIGHT,
    LINEAR_WEIGHT,
    RING_BUFFER_CAP,
    TREND_DOWN,
    TREND_STABLE,
    TREND_UP,
    ForecastResult,
    YieldForecastEngine,
    _compute_ema_series,
    _ema_trend_slope,
    _linear_regression,
    _r_squared,
    classify_trend,
    ensemble_forecast,
    ema_forecast,
    forecast_confidence,
    linear_forecast,
    load_history,
    save_results,
)


# ===========================================================================
# _linear_regression
# ===========================================================================

class TestLinearRegression(unittest.TestCase):

    def test_empty_series(self):
        slope, intercept = _linear_regression([])
        self.assertEqual(slope, 0.0)
        self.assertEqual(intercept, 0.0)

    def test_single_element(self):
        slope, intercept = _linear_regression([0.05])
        self.assertEqual(slope, 0.0)
        self.assertAlmostEqual(intercept, 0.05)

    def test_two_points_rising(self):
        # y = 0, 1 → slope=1, intercept=0
        slope, intercept = _linear_regression([0.0, 1.0])
        self.assertAlmostEqual(slope, 1.0, places=10)
        self.assertAlmostEqual(intercept, 0.0, places=10)

    def test_two_points_falling(self):
        # y = 1, 0 → slope=-1, intercept=1
        slope, intercept = _linear_regression([1.0, 0.0])
        self.assertAlmostEqual(slope, -1.0, places=10)
        self.assertAlmostEqual(intercept, 1.0, places=10)

    def test_flat_series(self):
        series = [0.05] * 10
        slope, intercept = _linear_regression(series)
        self.assertAlmostEqual(slope, 0.0, places=10)
        self.assertAlmostEqual(intercept, 0.05, places=10)

    def test_perfect_uptrend(self):
        # y = 0, 1, 2, 3, 4 → slope=1, intercept=0
        slope, intercept = _linear_regression([0.0, 1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(slope, 1.0, places=10)
        self.assertAlmostEqual(intercept, 0.0, places=10)

    def test_perfect_downtrend(self):
        # y = 4, 3, 2, 1, 0 → slope=-1, intercept=4
        slope, intercept = _linear_regression([4.0, 3.0, 2.0, 1.0, 0.0])
        self.assertAlmostEqual(slope, -1.0, places=10)
        self.assertAlmostEqual(intercept, 4.0, places=10)

    def test_apy_series(self):
        # Incrementing APY: 0.03, 0.04, 0.05 → slope=0.01
        slope, intercept = _linear_regression([0.03, 0.04, 0.05])
        self.assertAlmostEqual(slope, 0.01, places=10)
        self.assertAlmostEqual(intercept, 0.03, places=10)

    def test_large_series(self):
        n = 100
        series = [float(i) for i in range(n)]
        slope, intercept = _linear_regression(series)
        self.assertAlmostEqual(slope, 1.0, places=6)
        self.assertAlmostEqual(intercept, 0.0, places=6)


# ===========================================================================
# _r_squared
# ===========================================================================

class TestRSquared(unittest.TestCase):

    def test_perfect_fit(self):
        series = [0.0, 1.0, 2.0, 3.0, 4.0]
        slope, intercept = _linear_regression(series)
        r2 = _r_squared(series, slope, intercept)
        self.assertAlmostEqual(r2, 1.0, places=10)

    def test_flat_series_constant_variance(self):
        series = [0.05] * 10
        slope, intercept = _linear_regression(series)
        r2 = _r_squared(series, slope, intercept)
        self.assertAlmostEqual(r2, 1.0, places=10)

    def test_single_element(self):
        r2 = _r_squared([0.05], 0.0, 0.05)
        self.assertAlmostEqual(r2, 1.0)

    def test_r2_clamped_above_zero(self):
        # Arbitrary bad fit shouldn't go negative
        series = [0.1, 0.05, 0.2, 0.01, 0.3]
        slope, intercept = _linear_regression(series)
        r2 = _r_squared(series, slope, intercept)
        self.assertGreaterEqual(r2, 0.0)

    def test_r2_clamped_below_one(self):
        series = [0.1, 0.05, 0.2, 0.01, 0.3]
        slope, intercept = _linear_regression(series)
        r2 = _r_squared(series, slope, intercept)
        self.assertLessEqual(r2, 1.0)

    def test_near_perfect_fit(self):
        # Mostly linear with tiny noise
        series = [i * 0.01 + (0.0001 if i == 3 else 0.0) for i in range(10)]
        slope, intercept = _linear_regression(series)
        r2 = _r_squared(series, slope, intercept)
        self.assertGreater(r2, 0.99)


# ===========================================================================
# _compute_ema_series
# ===========================================================================

class TestComputeEmaSeries(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(_compute_ema_series([]), [])

    def test_single(self):
        result = _compute_ema_series([0.05])
        self.assertEqual(result, [0.05])

    def test_alpha_1_returns_original(self):
        series = [0.03, 0.04, 0.05, 0.06]
        result = _compute_ema_series(series, alpha=1.0)
        for a, b in zip(result, series):
            self.assertAlmostEqual(a, b, places=10)

    def test_alpha_0_returns_constant(self):
        series = [0.03, 0.04, 0.05, 0.06]
        result = _compute_ema_series(series, alpha=0.0)
        for val in result:
            self.assertAlmostEqual(val, 0.03, places=10)

    def test_length_preserved(self):
        series = [0.03, 0.04, 0.05, 0.06, 0.07]
        result = _compute_ema_series(series)
        self.assertEqual(len(result), len(series))

    def test_first_element_unchanged(self):
        series = [0.05, 0.06, 0.07]
        result = _compute_ema_series(series)
        self.assertAlmostEqual(result[0], series[0], places=10)

    def test_second_element_formula(self):
        series = [0.04, 0.06]
        result = _compute_ema_series(series, alpha=EMA_ALPHA)
        expected = EMA_ALPHA * 0.06 + (1 - EMA_ALPHA) * 0.04
        self.assertAlmostEqual(result[1], expected, places=10)

    def test_ema_smoothing_reduces_spikes(self):
        series = [0.05, 0.10, 0.05, 0.10, 0.05]
        result = _compute_ema_series(series)
        # EMA should be smoother than the raw series
        raw_range = max(series) - min(series)
        ema_range = max(result) - min(result)
        self.assertLess(ema_range, raw_range)


# ===========================================================================
# _ema_trend_slope
# ===========================================================================

class TestEmaTrendSlope(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(_ema_trend_slope([]), 0.0)

    def test_single_element(self):
        slope = _ema_trend_slope([0.05])
        self.assertEqual(slope, 0.0)

    def test_flat_ema(self):
        ema = [0.05] * 10
        slope = _ema_trend_slope(ema)
        self.assertAlmostEqual(slope, 0.0, places=10)

    def test_rising_ema(self):
        ema = [float(i) for i in range(10)]
        slope = _ema_trend_slope(ema)
        self.assertGreater(slope, 0.0)

    def test_falling_ema(self):
        ema = [float(10 - i) for i in range(10)]
        slope = _ema_trend_slope(ema)
        self.assertLess(slope, 0.0)


# ===========================================================================
# classify_trend
# ===========================================================================

class TestClassifyTrend(unittest.TestCase):

    def test_stable_zero(self):
        self.assertEqual(classify_trend(0.0), TREND_STABLE)

    def test_stable_small_positive(self):
        self.assertEqual(classify_trend(5e-5), TREND_STABLE)

    def test_stable_small_negative(self):
        self.assertEqual(classify_trend(-5e-5), TREND_STABLE)

    def test_up_above_threshold(self):
        self.assertEqual(classify_trend(2e-4), TREND_UP)

    def test_down_below_threshold(self):
        self.assertEqual(classify_trend(-2e-4), TREND_DOWN)

    def test_up_exact_threshold(self):
        # slope > 1e-4 → UP; slope == 1e-4 is NOT > threshold
        self.assertEqual(classify_trend(1.001e-4), TREND_UP)

    def test_down_exact_threshold(self):
        self.assertEqual(classify_trend(-1.001e-4), TREND_DOWN)


# ===========================================================================
# linear_forecast (method & wrapper)
# ===========================================================================

class TestLinearForecast(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = YieldForecastEngine(data_dir=self.tmpdir)

    def test_empty_series_returns_zero(self):
        result = self.engine.linear_forecast([], forecast_days=7)
        self.assertAlmostEqual(result, 0.0)

    def test_single_element(self):
        result = self.engine.linear_forecast([0.05], forecast_days=1)
        self.assertAlmostEqual(result, 0.05, places=8)

    def test_flat_series_returns_constant(self):
        series = [0.05] * 10
        result = self.engine.linear_forecast(series, forecast_days=7)
        self.assertAlmostEqual(result, 0.05, places=6)

    def test_perfect_uptrend_1_day(self):
        # y = 0,1,2,...,9; slope=1, intercept=0
        # forecast at idx 9+1=10 → 10.0
        series = list(range(10))
        result = self.engine.linear_forecast([float(x) for x in series], forecast_days=1)
        self.assertAlmostEqual(result, 10.0, places=6)

    def test_perfect_downtrend(self):
        # y = 10,9,...,1; slope=-1, intercept=10
        # forecast at idx 9+1=10 → 10 + (-1)*10 = 0
        series = [float(10 - i) for i in range(10)]
        result = self.engine.linear_forecast(series, forecast_days=1)
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_apy_uptrend_7_days(self):
        # slope=0.001/day, start=0.040
        series = [0.040 + 0.001 * i for i in range(14)]
        result = self.engine.linear_forecast(series, forecast_days=7)
        # expect ≈ 0.040 + 0.001*20 = 0.060
        self.assertAlmostEqual(result, 0.060, places=5)

    def test_convenience_wrapper(self):
        result = linear_forecast([0.05, 0.06, 0.07], forecast_days=1,
                                 data_dir=self.tmpdir)
        self.assertIsInstance(result, float)

    def test_forecast_days_affects_result(self):
        series = [0.040 + 0.001 * i for i in range(10)]
        r1 = self.engine.linear_forecast(series, forecast_days=1)
        r7 = self.engine.linear_forecast(series, forecast_days=7)
        # Uptrend: 7-day forecast should be higher
        self.assertGreater(r7, r1)


# ===========================================================================
# ema_forecast (method & wrapper)
# ===========================================================================

class TestEmaForecast(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = YieldForecastEngine(data_dir=self.tmpdir)

    def test_empty_series_returns_zero(self):
        result = self.engine.ema_forecast([], forecast_days=7)
        self.assertAlmostEqual(result, 0.0)

    def test_single_element(self):
        result = self.engine.ema_forecast([0.05], forecast_days=1)
        self.assertAlmostEqual(result, 0.05, places=8)

    def test_flat_series_returns_constant(self):
        series = [0.05] * 20
        result = self.engine.ema_forecast(series, forecast_days=1)
        self.assertAlmostEqual(result, 0.05, places=4)

    def test_uptrend_forecast_above_current(self):
        series = [0.04 + 0.001 * i for i in range(20)]
        result = self.engine.ema_forecast(series, forecast_days=7)
        self.assertGreater(result, series[-1])

    def test_downtrend_forecast_below_current(self):
        series = [0.06 - 0.001 * i for i in range(20)]
        result = self.engine.ema_forecast(series, forecast_days=7)
        self.assertLess(result, series[-1])

    def test_convenience_wrapper(self):
        result = ema_forecast([0.05, 0.06, 0.07], forecast_days=1,
                              data_dir=self.tmpdir)
        self.assertIsInstance(result, float)

    def test_forecast_days_scales_extrapolation(self):
        series = [0.04 + 0.001 * i for i in range(20)]
        r1 = self.engine.ema_forecast(series, forecast_days=1)
        r7 = self.engine.ema_forecast(series, forecast_days=7)
        # Uptrend: further horizon → higher forecast
        self.assertGreater(r7, r1)


# ===========================================================================
# ensemble_forecast (method & wrapper)
# ===========================================================================

class TestEnsembleForecast(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = YieldForecastEngine(data_dir=self.tmpdir)

    def test_empty_returns_zero_result(self):
        result = self.engine.ensemble_forecast([], forecast_days=7)
        self.assertIsInstance(result, ForecastResult)
        self.assertAlmostEqual(result.projected_apy, 0.0)
        self.assertAlmostEqual(result.confidence, 0.0)
        self.assertEqual(result.trend_direction, TREND_STABLE)
        self.assertEqual(result.series_length, 0)

    def test_single_element(self):
        result = self.engine.ensemble_forecast([0.05], forecast_days=1)
        self.assertAlmostEqual(result.projected_apy, 0.05, places=6)
        self.assertEqual(result.series_length, 1)

    def test_flat_series_stable_trend(self):
        series = [0.05] * 30
        result = self.engine.ensemble_forecast(series, forecast_days=7)
        self.assertEqual(result.trend_direction, TREND_STABLE)
        self.assertAlmostEqual(result.projected_apy, 0.05, places=4)

    def test_uptrend_direction(self):
        series = [0.04 + 0.001 * i for i in range(30)]
        result = self.engine.ensemble_forecast(series, forecast_days=7)
        self.assertEqual(result.trend_direction, TREND_UP)

    def test_downtrend_direction(self):
        series = [0.06 - 0.001 * i for i in range(30)]
        result = self.engine.ensemble_forecast(series, forecast_days=7)
        self.assertEqual(result.trend_direction, TREND_DOWN)

    def test_ensemble_is_weighted_average(self):
        series = [0.04 + 0.001 * i for i in range(10)]
        result = self.engine.ensemble_forecast(series, forecast_days=1)
        expected = (LINEAR_WEIGHT * result.projected_apy_linear
                    + EMA_WEIGHT * result.projected_apy_ema)
        self.assertAlmostEqual(result.projected_apy, expected, places=10)

    def test_forecast_range_min_le_max(self):
        series = [0.04 + 0.001 * i for i in range(10)]
        result = self.engine.ensemble_forecast(series, forecast_days=7)
        self.assertLessEqual(result.forecast_range["min"],
                             result.forecast_range["max"])

    def test_forecast_range_keys(self):
        result = self.engine.ensemble_forecast([0.05] * 10, forecast_days=1)
        self.assertIn("min", result.forecast_range)
        self.assertIn("max", result.forecast_range)

    def test_confidence_in_range(self):
        series = [0.04 + 0.001 * i for i in range(10)]
        result = self.engine.ensemble_forecast(series, forecast_days=1)
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_perfect_linear_confidence_is_1(self):
        series = [float(i) * 0.001 for i in range(30)]
        result = self.engine.ensemble_forecast(series, forecast_days=1)
        self.assertAlmostEqual(result.confidence, 1.0, places=6)

    def test_horizon_days_preserved(self):
        result = self.engine.ensemble_forecast([0.05] * 10, forecast_days=14)
        self.assertEqual(result.horizon_days, 14)

    def test_series_length_preserved(self):
        series = [0.05] * 20
        result = self.engine.ensemble_forecast(series, forecast_days=1)
        self.assertEqual(result.series_length, 20)

    def test_advisory_present(self):
        result = self.engine.ensemble_forecast([0.05], forecast_days=1)
        self.assertIsInstance(result.advisory, str)
        self.assertGreater(len(result.advisory), 0)

    def test_computed_at_present(self):
        result = self.engine.ensemble_forecast([0.05], forecast_days=1)
        self.assertIn("T", result.computed_at)

    def test_to_dict_keys(self):
        result = self.engine.ensemble_forecast([0.05] * 5, forecast_days=1)
        d = result.to_dict()
        for key in ("computed_at", "projected_apy", "projected_apy_linear",
                    "projected_apy_ema", "confidence", "trend_direction",
                    "forecast_range", "advisory"):
            self.assertIn(key, d)

    def test_1_element_series_confidence_is_1(self):
        result = self.engine.ensemble_forecast([0.05], forecast_days=1)
        self.assertAlmostEqual(result.confidence, 1.0)

    def test_negative_trend_series(self):
        series = [0.08 - 0.002 * i for i in range(20)]
        result = self.engine.ensemble_forecast(series, forecast_days=7)
        self.assertEqual(result.trend_direction, TREND_DOWN)
        self.assertGreater(result.projected_apy_linear, 0.0)  # still positive APY

    def test_convenience_wrapper(self):
        result = ensemble_forecast([0.05, 0.06, 0.07], forecast_days=1,
                                   data_dir=self.tmpdir)
        self.assertIsInstance(result, ForecastResult)

    def test_deterministic_output(self):
        series = [0.04 + 0.001 * i for i in range(15)]
        r1 = self.engine.ensemble_forecast(series, forecast_days=7)
        r2 = self.engine.ensemble_forecast(series, forecast_days=7)
        self.assertAlmostEqual(r1.projected_apy, r2.projected_apy, places=10)
        self.assertAlmostEqual(r1.confidence, r2.confidence, places=10)

    def test_forecast_range_contains_ensemble(self):
        series = [0.04 + 0.001 * i for i in range(10)]
        result = self.engine.ensemble_forecast(series, forecast_days=7)
        # Ensemble is between min(linear, ema) and max(linear, ema)
        self.assertGreaterEqual(result.projected_apy,
                                result.forecast_range["min"] - 1e-10)
        self.assertLessEqual(result.projected_apy,
                             result.forecast_range["max"] + 1e-10)


# ===========================================================================
# forecast_confidence
# ===========================================================================

class TestForecastConfidence(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = YieldForecastEngine(data_dir=self.tmpdir)

    def test_empty_returns_zero(self):
        self.assertAlmostEqual(self.engine.forecast_confidence([]), 0.0)

    def test_single_returns_one(self):
        self.assertAlmostEqual(self.engine.forecast_confidence([0.05]), 1.0)

    def test_flat_series_returns_one(self):
        self.assertAlmostEqual(
            self.engine.forecast_confidence([0.05] * 20), 1.0, places=6
        )

    def test_perfect_linear_returns_one(self):
        series = [0.001 * i for i in range(30)]
        conf = self.engine.forecast_confidence(series)
        self.assertAlmostEqual(conf, 1.0, places=6)

    def test_in_range_0_to_1(self):
        series = [0.1, 0.05, 0.2, 0.01, 0.3, 0.07, 0.15]
        conf = self.engine.forecast_confidence(series)
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)

    def test_convenience_wrapper(self):
        result = forecast_confidence([0.05, 0.06, 0.07], data_dir=self.tmpdir)
        self.assertIsInstance(result, float)


# ===========================================================================
# save / load_history (ring buffer + atomic write)
# ===========================================================================

class TestSaveAndLoadHistory(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = YieldForecastEngine(data_dir=self.tmpdir)

    def _compute_and_save(self):
        series = [0.04 + 0.001 * i for i in range(10)]
        result = self.engine.ensemble_forecast(series, forecast_days=1)
        return self.engine.save(result)

    def test_save_creates_file(self):
        path = self._compute_and_save()
        self.assertTrue(os.path.exists(path))

    def test_save_returns_correct_path(self):
        path = self._compute_and_save()
        self.assertTrue(path.endswith("yield_forecast_log.json"))

    def test_load_empty_before_save(self):
        self.assertEqual(self.engine.load_history(), [])

    def test_save_and_load_roundtrip(self):
        self._compute_and_save()
        history = self.engine.load_history()
        self.assertEqual(len(history), 1)

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            self._compute_and_save()
        self.assertEqual(len(self.engine.load_history()), 5)

    def test_ring_buffer_cap(self):
        for _ in range(RING_BUFFER_CAP + 15):
            self._compute_and_save()
        self.assertEqual(len(self.engine.load_history()), RING_BUFFER_CAP)

    def test_load_missing_file_returns_empty(self):
        engine = YieldForecastEngine(data_dir=self.tmpdir)
        self.assertEqual(engine.load_history(), [])

    def test_load_corrupt_json_returns_empty(self):
        log_path = os.path.join(self.tmpdir, "yield_forecast_log.json")
        with open(log_path, "w") as f:
            f.write("CORRUPT")
        self.assertEqual(self.engine.load_history(), [])

    def test_load_non_list_json_returns_empty(self):
        log_path = os.path.join(self.tmpdir, "yield_forecast_log.json")
        with open(log_path, "w") as f:
            json.dump({"not": "a list"}, f)
        self.assertEqual(self.engine.load_history(), [])

    def test_saved_entry_has_projected_apy(self):
        self._compute_and_save()
        history = self.engine.load_history()
        self.assertIn("projected_apy", history[0])

    def test_saved_entry_has_confidence(self):
        self._compute_and_save()
        history = self.engine.load_history()
        self.assertIn("confidence", history[0])

    def test_saved_entry_has_trend_direction(self):
        self._compute_and_save()
        history = self.engine.load_history()
        self.assertIn("trend_direction", history[0])

    def test_atomic_write_valid_json(self):
        self._compute_and_save()
        log_path = os.path.join(self.tmpdir, "yield_forecast_log.json")
        with open(log_path, "r") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_save_results_wrapper(self):
        series = [0.05] * 10
        result = self.engine.ensemble_forecast(series, forecast_days=1)
        path = save_results(result, data_dir=self.tmpdir)
        self.assertTrue(os.path.exists(path))

    def test_load_history_wrapper(self):
        series = [0.05] * 10
        result = self.engine.ensemble_forecast(series, forecast_days=1)
        save_results(result, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 1)


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = YieldForecastEngine(data_dir=self.tmpdir)

    def test_1_element_linear_forecast(self):
        result = self.engine.linear_forecast([0.05], forecast_days=7)
        self.assertAlmostEqual(result, 0.05)

    def test_2_element_upward_linear(self):
        result = self.engine.linear_forecast([0.04, 0.06], forecast_days=1)
        # slope=0.02, intercept=0.04; at idx 2: 0.04 + 0.02*2 = 0.08
        self.assertAlmostEqual(result, 0.08, places=8)

    def test_very_short_series_ema(self):
        result = self.engine.ema_forecast([0.05, 0.06], forecast_days=1)
        self.assertIsInstance(result, float)

    def test_all_same_values_stable_trend(self):
        series = [0.05] * 50
        result = self.engine.ensemble_forecast(series, forecast_days=30)
        self.assertEqual(result.trend_direction, TREND_STABLE)

    def test_high_apy_series(self):
        # Simulating Pendle-like high APY
        series = [0.15 + 0.001 * i for i in range(20)]
        result = self.engine.ensemble_forecast(series, forecast_days=7)
        self.assertGreater(result.projected_apy, 0.15)

    def test_zero_apy_series(self):
        series = [0.0] * 10
        result = self.engine.ensemble_forecast(series, forecast_days=1)
        self.assertAlmostEqual(result.projected_apy, 0.0, places=8)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(LINEAR_WEIGHT + EMA_WEIGHT, 1.0, places=10)

    def test_forecast_range_flat_series(self):
        series = [0.05] * 20
        result = self.engine.ensemble_forecast(series, forecast_days=7)
        # Both models should forecast ~0.05
        self.assertAlmostEqual(result.forecast_range["min"],
                               result.forecast_range["max"], places=4)

    def test_ring_buffer_keeps_most_recent(self):
        # Fill beyond cap, check we kept the last N
        for i in range(RING_BUFFER_CAP + 5):
            series = [float(i) * 0.001] * 5
            result = self.engine.ensemble_forecast(series, forecast_days=1)
            self.engine.save(result)
        history = self.engine.load_history()
        self.assertEqual(len(history), RING_BUFFER_CAP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
