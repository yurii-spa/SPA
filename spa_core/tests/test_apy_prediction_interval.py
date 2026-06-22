"""
Tests for MP-691: APYPredictionInterval  (≥60 tests)
Pure stdlib unittest — no pytest dependency.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.apy_prediction_interval import (
    APYHistoricalData,
    predict,
    predict_batch,
    compare_protocols,
    save_results,
    load_history,
    Z_80,
    Z_95,
    MAX_ENTRIES,
)

EPS = 1e-9


def _data(protocol, series, horizon=7):
    return APYHistoricalData(protocol=protocol, apy_series=list(series), forecast_horizon=horizon)


# ===========================================================================
# 1. mean_apy
# ===========================================================================

class TestMeanApy(unittest.TestCase):

    def test_mean_empty(self):
        result = predict(_data("P", []))
        self.assertAlmostEqual(result.mean_apy, 0.0, places=9)

    def test_mean_single(self):
        result = predict(_data("P", [5.0]))
        self.assertAlmostEqual(result.mean_apy, 5.0, places=9)

    def test_mean_two_values(self):
        result = predict(_data("P", [4.0, 6.0]))
        self.assertAlmostEqual(result.mean_apy, 5.0, places=9)

    def test_mean_multiple_values(self):
        result = predict(_data("P", [1.0, 2.0, 3.0, 4.0, 5.0]))
        self.assertAlmostEqual(result.mean_apy, 3.0, places=9)

    def test_mean_identical_values(self):
        result = predict(_data("P", [7.0] * 10))
        self.assertAlmostEqual(result.mean_apy, 7.0, places=9)


# ===========================================================================
# 2. std_apy
# ===========================================================================

class TestStdApy(unittest.TestCase):

    def test_std_empty(self):
        result = predict(_data("P", []))
        self.assertAlmostEqual(result.std_apy, 0.0, places=9)

    def test_std_single(self):
        result = predict(_data("P", [5.0]))
        self.assertAlmostEqual(result.std_apy, 0.0, places=9)

    def test_std_two_identical(self):
        result = predict(_data("P", [5.0, 5.0]))
        self.assertAlmostEqual(result.std_apy, 0.0, places=9)

    def test_std_two_values(self):
        result = predict(_data("P", [2.0, 4.0]))
        self.assertAlmostEqual(result.std_apy, 1.0, places=9)

    def test_std_known(self):
        # [2,4,4,4,5,5,7,9] pop std=2.0
        vals = [2, 4, 4, 4, 5, 5, 7, 9]
        result = predict(_data("P", vals))
        self.assertAlmostEqual(result.std_apy, 2.0, places=9)


# ===========================================================================
# 3. forecast_mean == mean_apy (naive model)
# ===========================================================================

class TestForecastMean(unittest.TestCase):

    def test_forecast_equals_mean(self):
        series = [3.0, 5.0, 7.0, 9.0]
        result = predict(_data("P", series))
        self.assertAlmostEqual(result.forecast_mean, result.mean_apy, places=9)

    def test_forecast_equals_mean_single(self):
        result = predict(_data("P", [4.5]))
        self.assertAlmostEqual(result.forecast_mean, 4.5, places=9)

    def test_forecast_equals_mean_empty(self):
        result = predict(_data("P", []))
        self.assertAlmostEqual(result.forecast_mean, 0.0, places=9)


# ===========================================================================
# 4. lower_80 / upper_80
# ===========================================================================

class TestInterval80(unittest.TestCase):

    def test_lower_80_formula(self):
        # [2, 4] → mean=3, std=1 → lower_80 = 3 - 1.282*1 = 1.718
        result = predict(_data("P", [2.0, 4.0]))
        expected = 3.0 - Z_80 * 1.0
        self.assertAlmostEqual(result.lower_80, expected, places=6)

    def test_upper_80_formula(self):
        result = predict(_data("P", [2.0, 4.0]))
        expected = 3.0 + Z_80 * 1.0
        self.assertAlmostEqual(result.upper_80, expected, places=6)

    def test_lower_80_clamped_to_zero(self):
        # very high std → lower bound would go negative
        result = predict(_data("P", [0.1, 100.0]))
        self.assertGreaterEqual(result.lower_80, 0.0)

    def test_lower_80_zero_std(self):
        result = predict(_data("P", [5.0, 5.0]))
        self.assertAlmostEqual(result.lower_80, 5.0, places=9)

    def test_upper_80_zero_std(self):
        result = predict(_data("P", [5.0, 5.0]))
        self.assertAlmostEqual(result.upper_80, 5.0, places=9)


# ===========================================================================
# 5. lower_95 / upper_95
# ===========================================================================

class TestInterval95(unittest.TestCase):

    def test_lower_95_formula(self):
        result = predict(_data("P", [2.0, 4.0]))
        expected = max(0.0, 3.0 - Z_95 * 1.0)
        self.assertAlmostEqual(result.lower_95, expected, places=6)

    def test_upper_95_formula(self):
        result = predict(_data("P", [2.0, 4.0]))
        expected = 3.0 + Z_95 * 1.0
        self.assertAlmostEqual(result.upper_95, expected, places=6)

    def test_lower_95_clamped_to_zero(self):
        result = predict(_data("P", [0.1, 100.0]))
        self.assertGreaterEqual(result.lower_95, 0.0)

    def test_lower_95_zero_std(self):
        result = predict(_data("P", [5.0, 5.0]))
        self.assertAlmostEqual(result.lower_95, 5.0, places=9)

    def test_upper_95_zero_std(self):
        result = predict(_data("P", [5.0, 5.0]))
        self.assertAlmostEqual(result.upper_95, 5.0, places=9)


# ===========================================================================
# 6. 95% wider than 80%
# ===========================================================================

class TestIntervalWidth(unittest.TestCase):

    def test_95_wider_than_80_upper(self):
        result = predict(_data("P", [2.0, 4.0, 6.0, 8.0]))
        self.assertGreater(result.upper_95, result.upper_80)

    def test_95_wider_than_80_lower_when_positive(self):
        # With mean=5, std=0.5 → lower bounds well above 0
        result = predict(_data("P", [4.5, 5.0, 5.0, 5.5]))
        self.assertLessEqual(result.lower_95, result.lower_80)

    def test_95_upper_minus_lower_wider(self):
        result = predict(_data("P", [2.0, 4.0, 6.0, 8.0]))
        width_80 = result.upper_80 - result.lower_80
        width_95 = result.upper_95 - result.lower_95
        self.assertGreater(width_95, width_80)

    def test_zero_std_same_width(self):
        result = predict(_data("P", [5.0, 5.0, 5.0]))
        self.assertAlmostEqual(result.upper_80 - result.lower_80, 0.0, places=9)
        self.assertAlmostEqual(result.upper_95 - result.lower_95, 0.0, places=9)


# ===========================================================================
# 7. trend
# ===========================================================================

class TestTrend(unittest.TestCase):

    def test_flat_less_than_14(self):
        result = predict(_data("P", [5.0] * 13))
        self.assertEqual(result.trend, "FLAT")

    def test_flat_exactly_13(self):
        series = list(range(1, 14))  # 13 values
        result = predict(_data("P", series))
        self.assertEqual(result.trend, "FLAT")

    def test_rising(self):
        # prior7 = [1..7], last7 = [100..106] → last7 >> prior7 * 1.05
        series = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0,
                  100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
        result = predict(_data("P", series))
        self.assertEqual(result.trend, "RISING")

    def test_falling(self):
        # prior7 = [100..106], last7 = [1..7] → last7 << prior7 * 0.95
        series = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0,
                  1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        result = predict(_data("P", series))
        self.assertEqual(result.trend, "FALLING")

    def test_flat_when_equal(self):
        # Same values → last7/prior7 ratio = 1.0 → FLAT
        series = [5.0] * 14
        result = predict(_data("P", series))
        self.assertEqual(result.trend, "FLAT")

    def test_rising_boundary(self):
        # last7_mean = prior7_mean * 1.051 → RISING
        prior = [10.0] * 7
        last = [10.51] * 7  # 5.1% higher
        result = predict(_data("P", prior + last))
        self.assertEqual(result.trend, "RISING")

    def test_falling_boundary(self):
        # last7_mean = prior7_mean * 0.949 → FALLING
        prior = [10.0] * 7
        last = [9.49] * 7   # 5.1% lower
        result = predict(_data("P", prior + last))
        self.assertEqual(result.trend, "FALLING")


# ===========================================================================
# 8. confidence
# ===========================================================================

class TestConfidence(unittest.TestCase):

    def test_low_empty(self):
        result = predict(_data("P", []))
        self.assertEqual(result.confidence, "LOW")

    def test_low_less_than_7(self):
        result = predict(_data("P", [5.0] * 6))
        self.assertEqual(result.confidence, "LOW")

    def test_medium_exactly_7(self):
        result = predict(_data("P", [5.0] * 7))
        self.assertEqual(result.confidence, "MEDIUM")

    def test_medium_between_7_and_30(self):
        result = predict(_data("P", [5.0] * 20))
        self.assertEqual(result.confidence, "MEDIUM")

    def test_high_exactly_30(self):
        result = predict(_data("P", [5.0] * 30))
        self.assertEqual(result.confidence, "HIGH")

    def test_high_more_than_30(self):
        result = predict(_data("P", [5.0] * 50))
        self.assertEqual(result.confidence, "HIGH")


# ===========================================================================
# 9. interpretation
# ===========================================================================

class TestInterpretation(unittest.TestCase):

    def test_contains_protocol_name(self):
        result = predict(_data("MyProtocol", [5.0] * 10))
        self.assertIn("MyProtocol", result.interpretation)

    def test_contains_forecast_value(self):
        result = predict(_data("P", [5.0] * 10))
        self.assertIn("5.00", result.interpretation)

    def test_contains_trend(self):
        result = predict(_data("P", [5.0] * 14))
        self.assertIn("FLAT", result.interpretation)

    def test_contains_confidence(self):
        result = predict(_data("P", [5.0] * 10))
        self.assertIn("MEDIUM", result.interpretation)

    def test_contains_80ci(self):
        result = predict(_data("P", [5.0, 5.0]))
        self.assertIn("80%CI", result.interpretation)

    def test_empty_series_interpretation(self):
        result = predict(_data("TestProto", []))
        self.assertIn("TestProto", result.interpretation)
        self.assertIn("0.00", result.interpretation)


# ===========================================================================
# 10. predict edge cases
# ===========================================================================

class TestPredictEdgeCases(unittest.TestCase):

    def test_single_value_std_zero(self):
        result = predict(_data("P", [7.0]))
        self.assertAlmostEqual(result.std_apy, 0.0, places=9)

    def test_single_value_intervals_equal_to_mean(self):
        result = predict(_data("P", [7.0]))
        self.assertAlmostEqual(result.lower_80, 7.0, places=9)
        self.assertAlmostEqual(result.upper_80, 7.0, places=9)
        self.assertAlmostEqual(result.lower_95, 7.0, places=9)
        self.assertAlmostEqual(result.upper_95, 7.0, places=9)

    def test_empty_series_graceful(self):
        result = predict(_data("P", []))
        self.assertAlmostEqual(result.mean_apy, 0.0, places=9)
        self.assertAlmostEqual(result.std_apy, 0.0, places=9)
        self.assertAlmostEqual(result.forecast_mean, 0.0, places=9)
        self.assertEqual(result.trend, "FLAT")
        self.assertEqual(result.confidence, "LOW")

    def test_current_apy_is_last_value(self):
        series = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = predict(_data("P", series))
        self.assertAlmostEqual(result.current_apy, 5.0, places=9)

    def test_protocol_stored(self):
        result = predict(_data("Aave-V3", [5.0]))
        self.assertEqual(result.protocol, "Aave-V3")


# ===========================================================================
# 11. predict_batch
# ===========================================================================

class TestPredictBatch(unittest.TestCase):

    def test_batch_empty(self):
        result = predict_batch([])
        self.assertEqual(result, [])

    def test_batch_single(self):
        result = predict_batch([_data("P", [5.0] * 10)])
        self.assertEqual(len(result), 1)

    def test_batch_multiple(self):
        result = predict_batch([
            _data("A", [3.0] * 10),
            _data("B", [5.0] * 10),
            _data("C", [7.0] * 10),
        ])
        self.assertEqual(len(result), 3)

    def test_batch_protocols_preserved(self):
        result = predict_batch([
            _data("Alpha", [3.0] * 10),
            _data("Beta", [5.0] * 10),
        ])
        names = [r.protocol for r in result]
        self.assertIn("Alpha", names)
        self.assertIn("Beta", names)


# ===========================================================================
# 12. compare_protocols
# ===========================================================================

class TestCompareProtocols(unittest.TestCase):

    def test_sorted_descending(self):
        preds = [
            predict(_data("Low", [2.0] * 10)),
            predict(_data("High", [8.0] * 10)),
            predict(_data("Mid", [5.0] * 10)),
        ]
        sorted_preds = compare_protocols(preds)
        forecasts = [p.forecast_mean for p in sorted_preds]
        self.assertEqual(forecasts, sorted(forecasts, reverse=True))

    def test_first_has_highest_forecast(self):
        preds = predict_batch([
            _data("A", [1.0] * 10),
            _data("B", [10.0] * 10),
            _data("C", [5.0] * 10),
        ])
        sorted_preds = compare_protocols(preds)
        self.assertEqual(sorted_preds[0].protocol, "B")

    def test_empty_compare(self):
        result = compare_protocols([])
        self.assertEqual(result, [])

    def test_single_compare(self):
        preds = [predict(_data("P", [5.0] * 10))]
        result = compare_protocols(preds)
        self.assertEqual(len(result), 1)


# ===========================================================================
# 13. save_results / load_history
# ===========================================================================

class TestPersistence(unittest.TestCase):

    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        self.data_file = Path(path)

    def tearDown(self):
        if self.data_file.exists():
            self.data_file.unlink()
        tmp = self.data_file.with_suffix(".tmp")
        if tmp.exists():
            tmp.unlink()

    def test_load_missing_returns_empty(self):
        result = load_history(self.data_file)
        self.assertEqual(result, [])

    def test_save_and_load_single(self):
        pred = predict(_data("P", [5.0] * 10))
        save_results([pred], self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["protocol"], "P")

    def test_ring_buffer_max_entries(self):
        for i in range(MAX_ENTRIES + 5):
            pred = predict(_data(f"P{i}", [float(i)] * 10))
            save_results([pred], self.data_file)
        history = load_history(self.data_file)
        self.assertLessEqual(len(history), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        for i in range(MAX_ENTRIES + 3):
            pred = predict(_data(f"proto-{i}", [float(i)] * 10))
            save_results([pred], self.data_file)
        history = load_history(self.data_file)
        last_proto = history[-1]["protocol"]
        self.assertEqual(last_proto, f"proto-{MAX_ENTRIES + 2}")

    def test_atomic_no_tmp_left(self):
        pred = predict(_data("P", [5.0]))
        save_results([pred], self.data_file)
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_file_is_valid_json(self):
        pred = predict(_data("P", [5.0]))
        save_results([pred], self.data_file)
        raw = self.data_file.read_text()
        parsed = json.loads(raw)
        self.assertIsInstance(parsed, list)

    def test_load_corrupt_returns_empty(self):
        self.data_file.write_text("not valid json {{{")
        result = load_history(self.data_file)
        self.assertEqual(result, [])

    def test_multiple_saves_accumulate(self):
        for i in range(5):
            pred = predict(_data(f"P{i}", [float(i) + 1] * 10))
            save_results([pred], self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), 5)

    def test_save_batch_multiple_predictions(self):
        preds = predict_batch([
            _data("A", [3.0] * 10),
            _data("B", [5.0] * 10),
        ])
        save_results(preds, self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), 2)


if __name__ == "__main__":
    unittest.main()
