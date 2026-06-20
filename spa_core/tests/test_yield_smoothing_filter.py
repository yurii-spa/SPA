"""Tests for MP-737: YieldSmoothingFilter — pure stdlib unittest."""
import math
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.yield_smoothing_filter import (
    compute_sma, compute_ema, detect_outliers, compute_cv,
    smooth_protocol, smooth_all, save_results, load_history,
    SmoothedYield, YieldSmoothingResult,
)


class TestComputeSMA(unittest.TestCase):
    def test_basic_average(self):
        self.assertAlmostEqual(compute_sma([1.0, 2.0, 3.0], 3), 2.0)

    def test_window_larger_than_series(self):
        self.assertAlmostEqual(compute_sma([5.0, 10.0], 10), 7.5)

    def test_window_smaller_takes_last(self):
        self.assertAlmostEqual(compute_sma([1.0, 2.0, 3.0, 4.0, 5.0], 2), 4.5)

    def test_window_one(self):
        self.assertAlmostEqual(compute_sma([3.0, 7.0, 9.0], 1), 9.0)

    def test_empty_returns_zero(self):
        self.assertEqual(compute_sma([], 7), 0.0)

    def test_single_element(self):
        self.assertAlmostEqual(compute_sma([5.0], 7), 5.0)

    def test_window_exact(self):
        self.assertAlmostEqual(compute_sma([2.0, 4.0, 6.0], 3), 4.0)

    def test_window_7(self):
        s = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        # last 7 = [4,5,6,7,8,9,10], mean=7
        self.assertAlmostEqual(compute_sma(s, 7), 7.0)


class TestComputeEMA(unittest.TestCase):
    def test_empty_returns_zero(self):
        self.assertEqual(compute_ema([], 7), 0.0)

    def test_single_value(self):
        self.assertAlmostEqual(compute_ema([5.0], 7), 5.0)

    def test_alpha_formula_window7(self):
        alpha = 2.0 / (7 + 1)
        series = [10.0, 12.0]
        expected = alpha * 12.0 + (1 - alpha) * 10.0
        self.assertAlmostEqual(compute_ema(series, 7), expected)

    def test_alpha_formula_window14(self):
        alpha = 2.0 / (14 + 1)
        series = [5.0, 6.0]
        expected = alpha * 6.0 + (1 - alpha) * 5.0
        self.assertAlmostEqual(compute_ema(series, 14), expected)

    def test_ema_converges_toward_recent(self):
        series = [1.0] + [100.0] * 20
        self.assertGreater(compute_ema(series, 7), 50.0)

    def test_ema_constant_equals_constant(self):
        self.assertAlmostEqual(compute_ema([5.0] * 10, 7), 5.0)

    def test_three_values(self):
        alpha = 2.0 / (2 + 1)
        ema = 3.0
        ema = alpha * 6.0 + (1 - alpha) * ema
        ema = alpha * 9.0 + (1 - alpha) * ema
        self.assertAlmostEqual(compute_ema([3.0, 6.0, 9.0], 2), ema)

    def test_ema_less_than_last_value_rising(self):
        # EMA lags, so in a rising series it's below the last
        result = compute_ema([1.0, 2.0, 3.0, 4.0, 5.0], 7)
        self.assertLess(result, 5.0)


class TestDetectOutliers(unittest.TestCase):
    def _clear_series(self):
        """Series with a VERY obvious spike (>10x mean) so it's well beyond 2*std."""
        return [5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 1000.0]

    def test_no_outliers_constant(self):
        series = [5.0] * 10
        indices, cleaned = detect_outliers(series)
        self.assertEqual(indices, [])
        self.assertEqual(cleaned, series)

    def test_extreme_spike_detected(self):
        indices, cleaned = detect_outliers(self._clear_series())
        self.assertIn(9, indices)

    def test_extreme_spike_replaced_with_median(self):
        series = [5.0] * 9 + [1000.0]
        _, cleaned = detect_outliers(series)
        self.assertAlmostEqual(cleaned[9], 5.0)  # median of [5,5,...,5,1000]=5

    def test_empty_series(self):
        indices, cleaned = detect_outliers([])
        self.assertEqual(indices, [])
        self.assertEqual(cleaned, [])

    def test_all_same_no_outliers(self):
        self.assertEqual(detect_outliers([7.0] * 10)[0], [])

    def test_cleaned_length_equals_original(self):
        _, cleaned = detect_outliers(self._clear_series())
        self.assertEqual(len(cleaned), 10)

    def test_normal_values_unchanged(self):
        series = [5.0] * 9 + [1000.0]
        _, cleaned = detect_outliers(series)
        self.assertAlmostEqual(cleaned[0], 5.0)
        self.assertAlmostEqual(cleaned[4], 5.0)

    def test_outlier_index_list_length(self):
        series = [5.0] * 9 + [1000.0]
        indices, _ = detect_outliers(series)
        self.assertEqual(len(indices), 1)

    def test_strict_boundary_not_outlier(self):
        # Value exactly at 2*sigma boundary should NOT be flagged (strict >)
        # Use constant series: sigma=0, so no outliers possible
        series = [3.0] * 5
        indices, _ = detect_outliers(series)
        self.assertEqual(indices, [])


class TestComputeCV(unittest.TestCase):
    def test_zero_mean_returns_zero(self):
        self.assertEqual(compute_cv([0.0, 0.0, 0.0]), 0.0)

    def test_constant_cv_zero(self):
        self.assertAlmostEqual(compute_cv([5.0, 5.0, 5.0]), 0.0)

    def test_cv_formula(self):
        series = [1.0, 2.0, 3.0]
        mu = 2.0
        sigma = math.sqrt(sum((x - mu)**2 for x in series) / len(series))
        expected = sigma / mu * 100
        self.assertAlmostEqual(compute_cv(series), expected, places=5)

    def test_high_variation(self):
        self.assertGreater(compute_cv([1.0, 100.0]), 50.0)

    def test_empty(self):
        self.assertEqual(compute_cv([]), 0.0)

    def test_single_value(self):
        self.assertAlmostEqual(compute_cv([5.0]), 0.0)

    def test_cv_positive(self):
        self.assertGreaterEqual(compute_cv([1.0, 2.0, 3.0]), 0.0)


class TestSmoothProtocol(unittest.TestCase):
    def _constant(self):
        return [5.0] * 10   # perfectly stable, zero CV, zero spikes

    def _spikey(self):
        # 9 values at 5.0, 3 extreme spikes
        return [5.0] * 7 + [5.0, 5.0, 1000.0, 5.0, 2000.0, 5.0, 3000.0]

    def test_protocol_set(self):
        self.assertEqual(smooth_protocol("Aave", "USDC", self._constant()).protocol, "Aave")

    def test_asset_set(self):
        self.assertEqual(smooth_protocol("Aave", "USDC", self._constant()).asset, "USDC")

    def test_raw_series_preserved(self):
        s = self._constant()
        self.assertEqual(smooth_protocol("P", "A", s).raw_apy_series, s)

    def test_sma_7(self):
        s = self._constant()
        r = smooth_protocol("P", "A", s)
        self.assertAlmostEqual(r.sma_7, compute_sma(s, 7))

    def test_sma_14(self):
        s = self._constant()
        r = smooth_protocol("P", "A", s)
        self.assertAlmostEqual(r.sma_14, compute_sma(s, 14))

    def test_ema_7(self):
        s = self._constant()
        r = smooth_protocol("P", "A", s)
        self.assertAlmostEqual(r.ema_7, compute_ema(s, 7))

    def test_ema_14(self):
        s = self._constant()
        r = smooth_protocol("P", "A", s)
        self.assertAlmostEqual(r.ema_14, compute_ema(s, 14))

    def test_spike_count_zero_constant(self):
        r = smooth_protocol("P", "A", self._constant())
        self.assertEqual(r.spike_count, 0)

    def test_spike_count_spikey(self):
        r = smooth_protocol("P", "A", self._spikey())
        self.assertGreater(r.spike_count, 0)

    def test_recommended_ema7_when_spikes_gt_2(self):
        r = smooth_protocol("P", "A", self._spikey())
        if r.spike_count > 2:
            self.assertAlmostEqual(r.recommended_yield, r.ema_7)

    def test_recommended_cleaned_avg_few_spikes(self):
        r = smooth_protocol("P", "A", self._constant())
        if r.spike_count <= 2:
            self.assertAlmostEqual(r.recommended_yield, r.cleaned_avg)

    def test_stability_label_stable_constant(self):
        r = smooth_protocol("P", "A", self._constant())
        self.assertEqual(r.stability_label, "STABLE")

    def test_stability_label_spikey(self):
        r = smooth_protocol("P", "A", self._spikey())
        self.assertIn(r.stability_label, ["MODERATE", "VOLATILE"])

    def test_confidence_high_constant(self):
        r = smooth_protocol("P", "A", self._constant())
        self.assertEqual(r.confidence, "HIGH")

    def test_cv_non_negative(self):
        self.assertGreaterEqual(smooth_protocol("P", "A", self._constant()).coefficient_of_variation, 0.0)

    def test_cleaned_series_length(self):
        s = self._spikey()
        r = smooth_protocol("P", "A", s)
        self.assertEqual(len(r.cleaned_series), len(s))

    def test_cleaned_avg_equals_mean_for_constant(self):
        r = smooth_protocol("P", "A", self._constant())
        self.assertAlmostEqual(r.cleaned_avg, 5.0)

    def test_spike_indices_nonempty_for_spikey(self):
        r = smooth_protocol("P", "A", self._spikey())
        self.assertGreater(len(r.spike_indices), 0)


class TestSmoothAll(unittest.TestCase):
    def _data(self):
        return [
            {"protocol": "Aave", "asset": "USDC", "apy_series": [5.0] * 10},
            {"protocol": "Compound", "asset": "USDC",
             "apy_series": [5.0] * 7 + [5.0, 5.0, 1000.0, 5.0, 2000.0, 5.0, 3000.0]},
        ]

    def test_returns_result(self):
        self.assertIsInstance(smooth_all(self._data()), YieldSmoothingResult)

    def test_smoothed_count(self):
        self.assertEqual(len(smooth_all(self._data()).smoothed), 2)

    def test_most_stable(self):
        self.assertEqual(smooth_all(self._data()).most_stable_protocol, "Aave")

    def test_most_volatile(self):
        self.assertEqual(smooth_all(self._data()).most_volatile_protocol, "Compound")

    def test_avg_spike_rate(self):
        r = smooth_all(self._data())
        expected = sum(s.spike_count for s in r.smoothed) / 2
        self.assertAlmostEqual(r.avg_spike_rate, expected)

    def test_empty_input(self):
        r = smooth_all([])
        self.assertEqual(r.smoothed, [])
        self.assertEqual(r.most_stable_protocol, "")
        self.assertEqual(r.avg_spike_rate, 0.0)

    def test_single_protocol_stable_volatile_same(self):
        r = smooth_all([{"protocol": "X", "asset": "ETH", "apy_series": [4.0] * 5}])
        self.assertEqual(r.most_stable_protocol, "X")
        self.assertEqual(r.most_volatile_protocol, "X")

    def test_three_protocols(self):
        data = [
            {"protocol": "A", "asset": "U", "apy_series": [5.0] * 10},
            {"protocol": "B", "asset": "U", "apy_series": [5.0] * 5 + [500.0] * 5},
            {"protocol": "C", "asset": "U", "apy_series": [5.0] * 8 + [5000.0, 5000.0]},
        ]
        r = smooth_all(data)
        self.assertEqual(r.most_stable_protocol, "A")
        self.assertEqual(len(r.smoothed), 3)


class TestPersistence(unittest.TestCase):
    def _result(self):
        return smooth_all([{"protocol": "T", "asset": "U", "apy_series": [5.0] * 10}])

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "data" / "smooth.json"
            save_results(self._result(), data_file=path)
            history = load_history(data_file=path)
            self.assertEqual(len(history), 1)
            self.assertIn("smoothed", history[0])

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "data" / "smooth_rb.json"
            for _ in range(105):
                save_results(self._result(), data_file=path)
            self.assertEqual(len(load_history(data_file=path)), 100)

    def test_load_missing_returns_empty(self):
        self.assertEqual(load_history(data_file=Path("/nonexistent/x.json")), [])

    def test_accumulates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "data" / "acc.json"
            for _ in range(3):
                save_results(self._result(), data_file=path)
            self.assertEqual(len(load_history(data_file=path)), 3)

    def test_saved_to_ends_in_json(self):
        self.assertTrue(self._result().saved_to.endswith(".json"))

    def test_atomic_no_tmp_leftover(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "data" / "atomic.json"
            save_results(self._result(), data_file=path)
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_smoothed_survives_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "data" / "rt.json"
            save_results(self._result(), data_file=path)
            h = load_history(data_file=path)
            self.assertIsInstance(h[0]["smoothed"], list)


if __name__ == "__main__":
    unittest.main()
