"""
Tests for spa_core/analytics/apy_forecaster.py — MP-580

Groups:
    TestApyForecasterInit               (5  tests)
    TestLoadHistory                     (12 tests)
    TestComputeEma                      (14 tests)
    TestComputeTrend                    (14 tests)
    TestConfidenceHelper                (6  tests)
    TestForecastFallback                (8  tests)
    TestForecastWithData                (14 tests)
    TestForecastAll                     (10 tests)
    TestSaveForecast                    (10 tests)
    TestImportHygiene                   (4  tests)
    TestEdgeCases                       (8  tests)

Total: 105 tests
"""
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — ensure spa_core is importable from tests/
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.analytics.apy_forecaster import (
    ApyForecaster,
    _CONFIDENCE_HIGH,
    _CONFIDENCE_MEDIUM,
    _FORECAST_MAX_APY,
    _FORECAST_MIN_APY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_forecaster(tmp_path: Path) -> ApyForecaster:
    """Return a forecaster backed by a fresh temp directory."""
    return ApyForecaster(data_dir=str(tmp_path))


def write_history(tmp_path: Path, data: dict) -> None:
    """Write apy_history.json into tmp_path."""
    f = tmp_path / "apy_history.json"
    f.write_text(json.dumps(data))


def history_with_apys(adapter_id: str, apys: list[float]) -> dict:
    """Build a minimal apy_history.json payload for one adapter."""
    entries = [{"ts": f"2026-0{i+1:02d}-01T00:00:00+00:00", "apy": v, "tvl": 1e8}
               for i, v in enumerate(apys)]
    return {"protocol_history": {adapter_id: entries}}


# ===========================================================================
# 1. Init tests (5)
# ===========================================================================

class TestApyForecasterInit(unittest.TestCase):

    def test_default_data_dir(self):
        fc = ApyForecaster()
        self.assertEqual(str(fc.data_dir), "data")

    def test_custom_data_dir(self):
        fc = ApyForecaster(data_dir="/tmp/spa_test")
        self.assertEqual(str(fc.data_dir), "/tmp/spa_test")

    def test_data_dir_is_path_object(self):
        fc = ApyForecaster(data_dir="/tmp/spa_test")
        self.assertIsInstance(fc.data_dir, Path)

    def test_history_file_path(self):
        with tempfile.TemporaryDirectory() as td:
            fc = ApyForecaster(data_dir=td)
            self.assertTrue(str(fc._history_file).endswith("apy_history.json"))

    def test_forecasts_file_path(self):
        with tempfile.TemporaryDirectory() as td:
            fc = ApyForecaster(data_dir=td)
            self.assertTrue(str(fc._forecasts_file).endswith("apy_forecasts.json"))


# ===========================================================================
# 2. LoadHistory tests (12)
# ===========================================================================

class TestLoadHistory(unittest.TestCase):

    def test_missing_file_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            fc = make_forecaster(Path(td))
            self.assertEqual(fc.load_history("aave-v3-usdc"), [])

    def test_empty_json_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            write_history(td, {})
            fc = make_forecaster(td)
            self.assertEqual(fc.load_history("aave"), [])

    def test_unknown_adapter_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            write_history(td, history_with_apys("other", [5.0]))
            fc = make_forecaster(td)
            self.assertEqual(fc.load_history("aave"), [])

    def test_known_adapter_returns_list(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            write_history(td, history_with_apys("aave", [5.0, 6.0]))
            fc = make_forecaster(td)
            result = fc.load_history("aave")
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 2)

    def test_entries_have_apy_field(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            write_history(td, history_with_apys("aave", [3.5, 4.0]))
            fc = make_forecaster(td)
            for entry in fc.load_history("aave"):
                self.assertIn("apy", entry)

    def test_apy_values_match(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            write_history(td, history_with_apys("aave", [3.5, 4.0, 4.5]))
            fc = make_forecaster(td)
            apys = [e["apy"] for e in fc.load_history("aave")]
            self.assertEqual(apys, [3.5, 4.0, 4.5])

    def test_malformed_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            (td / "apy_history.json").write_text("NOT_JSON{{{")
            fc = make_forecaster(td)
            self.assertEqual(fc.load_history("any"), [])

    def test_entries_without_apy_are_filtered(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            data = {"protocol_history": {
                "aave": [
                    {"ts": "2026-01-01T00:00:00+00:00", "tvl": 1e8},  # no apy
                    {"ts": "2026-01-02T00:00:00+00:00", "apy": 5.0, "tvl": 1e8},
                ]
            }}
            write_history(td, data)
            fc = make_forecaster(td)
            result = fc.load_history("aave")
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["apy"], 5.0)

    def test_nan_apy_entries_are_filtered(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            data = {"protocol_history": {
                "aave": [{"ts": "t", "apy": float("nan")}, {"ts": "t2", "apy": 5.0}]
            }}
            write_history(td, data)
            fc = make_forecaster(td)
            result = fc.load_history("aave")
            self.assertEqual(len(result), 1)

    def test_fallback_schema_without_protocol_history_wrapper(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            data = {"aave": [{"apy": 4.0}, {"apy": 5.0}]}
            write_history(td, data)
            fc = make_forecaster(td)
            result = fc.load_history("aave")
            self.assertEqual(len(result), 2)

    def test_large_history_length_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            apys = [float(i) for i in range(90)]
            write_history(td, history_with_apys("big", apys))
            fc = make_forecaster(td)
            self.assertEqual(len(fc.load_history("big")), 90)

    def test_multiple_adapters_independent(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            data = {
                "protocol_history": {
                    "aave": [{"apy": 3.0}],
                    "compound": [{"apy": 5.0}, {"apy": 6.0}],
                }
            }
            write_history(td, data)
            fc = make_forecaster(td)
            self.assertEqual(len(fc.load_history("aave")), 1)
            self.assertEqual(len(fc.load_history("compound")), 2)


# ===========================================================================
# 3. ComputeEma tests (14)
# ===========================================================================

class TestComputeEma(unittest.TestCase):

    def test_empty_list_returns_zero(self):
        fc = ApyForecaster()
        self.assertEqual(fc.compute_ema([]), 0.0)

    def test_single_value_returns_that_value(self):
        fc = ApyForecaster()
        self.assertAlmostEqual(fc.compute_ema([5.0]), 5.0)

    def test_two_values_correct(self):
        fc = ApyForecaster()
        # ema = 0.3*6 + 0.7*5 = 1.8 + 3.5 = 5.3
        self.assertAlmostEqual(fc.compute_ema([5.0, 6.0], alpha=0.3), 5.3, places=10)

    def test_alpha_one_returns_last_value(self):
        fc = ApyForecaster()
        self.assertAlmostEqual(fc.compute_ema([1.0, 2.0, 3.0, 99.0], alpha=1.0), 99.0)

    def test_default_alpha_0_3(self):
        fc = ApyForecaster()
        vals = [5.0, 5.0, 5.0]
        # Constant series: EMA = 5.0
        self.assertAlmostEqual(fc.compute_ema(vals), 5.0, places=6)

    def test_increasing_series_ema_lags_behind_last(self):
        fc = ApyForecaster()
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        ema = fc.compute_ema(vals, alpha=0.3)
        # EMA should be < last value for increasing series
        self.assertLess(ema, 5.0)
        self.assertGreater(ema, 1.0)

    def test_decreasing_series_ema_above_last(self):
        fc = ApyForecaster()
        vals = [10.0, 8.0, 6.0, 4.0, 2.0]
        ema = fc.compute_ema(vals, alpha=0.3)
        self.assertGreater(ema, 2.0)

    def test_constant_series_ema_equals_value(self):
        fc = ApyForecaster()
        vals = [7.5] * 20
        self.assertAlmostEqual(fc.compute_ema(vals), 7.5, places=8)

    def test_custom_alpha_0_5(self):
        fc = ApyForecaster()
        vals = [4.0, 6.0]
        # ema = 0.5*6 + 0.5*4 = 5.0
        self.assertAlmostEqual(fc.compute_ema(vals, alpha=0.5), 5.0)

    def test_custom_alpha_0_1_heavy_smoothing(self):
        fc = ApyForecaster()
        vals = [10.0, 1.0]
        # ema = 0.1*1 + 0.9*10 = 0.1+9 = 9.1
        self.assertAlmostEqual(fc.compute_ema(vals, alpha=0.1), 9.1)

    def test_invalid_alpha_zero_raises(self):
        fc = ApyForecaster()
        with self.assertRaises(ValueError):
            fc.compute_ema([1.0, 2.0], alpha=0.0)

    def test_invalid_alpha_negative_raises(self):
        fc = ApyForecaster()
        with self.assertRaises(ValueError):
            fc.compute_ema([1.0, 2.0], alpha=-0.1)

    def test_invalid_alpha_gt_one_raises(self):
        fc = ApyForecaster()
        with self.assertRaises(ValueError):
            fc.compute_ema([1.0, 2.0], alpha=1.1)

    def test_long_series_result_is_float(self):
        fc = ApyForecaster()
        vals = [float(i % 10 + 1) for i in range(100)]
        result = fc.compute_ema(vals)
        self.assertIsInstance(result, float)


# ===========================================================================
# 4. ComputeTrend tests (14)
# ===========================================================================

class TestComputeTrend(unittest.TestCase):

    def test_empty_returns_zero(self):
        fc = ApyForecaster()
        self.assertEqual(fc.compute_trend([]), 0.0)

    def test_single_value_returns_zero(self):
        fc = ApyForecaster()
        self.assertEqual(fc.compute_trend([5.0]), 0.0)

    def test_constant_series_slope_zero(self):
        fc = ApyForecaster()
        self.assertAlmostEqual(fc.compute_trend([5.0, 5.0, 5.0, 5.0, 5.0]), 0.0, places=10)

    def test_linear_increasing_correct_slope(self):
        fc = ApyForecaster()
        # y = x → slope = 1.0
        vals = [0.0, 1.0, 2.0, 3.0, 4.0]
        self.assertAlmostEqual(fc.compute_trend(vals), 1.0, places=8)

    def test_linear_decreasing_correct_slope(self):
        fc = ApyForecaster()
        vals = [4.0, 3.0, 2.0, 1.0, 0.0]
        self.assertAlmostEqual(fc.compute_trend(vals), -1.0, places=8)

    def test_slope_0_5_correct(self):
        fc = ApyForecaster()
        # y = 0 + 0.5*x
        vals = [0.0, 0.5, 1.0, 1.5, 2.0]
        self.assertAlmostEqual(fc.compute_trend(vals), 0.5, places=8)

    def test_window_larger_than_series_uses_all(self):
        fc = ApyForecaster()
        vals = [1.0, 2.0, 3.0]
        # slope = 1.0
        self.assertAlmostEqual(fc.compute_trend(vals, window=10), 1.0, places=8)

    def test_window_limits_to_last_n_values(self):
        fc = ApyForecaster()
        # First part flat, then rising — window=3 should catch the rise
        vals = [5.0, 5.0, 5.0, 5.0, 6.0, 7.0, 8.0]
        slope_full = fc.compute_trend(vals, window=7)
        slope_window = fc.compute_trend(vals, window=3)
        self.assertGreater(slope_window, slope_full)

    def test_two_values_correct(self):
        fc = ApyForecaster()
        # y = [3, 5] → slope = (5-3)/1 = 2
        self.assertAlmostEqual(fc.compute_trend([3.0, 5.0]), 2.0, places=8)

    def test_result_is_float(self):
        fc = ApyForecaster()
        result = fc.compute_trend([1.0, 2.0, 3.0])
        self.assertIsInstance(result, float)

    def test_noisy_series_returns_finite(self):
        fc = ApyForecaster()
        import random
        random.seed(42)
        vals = [5.0 + random.uniform(-1, 1) for _ in range(20)]
        slope = fc.compute_trend(vals)
        self.assertTrue(math.isfinite(slope))

    def test_default_window_is_seven(self):
        fc = ApyForecaster()
        # Two-point series → same regardless of window if ≥ 2
        vals = [0.0, 1.0]
        self.assertAlmostEqual(fc.compute_trend(vals), 1.0, places=8)

    def test_y_equals_2x_plus_1(self):
        fc = ApyForecaster()
        vals = [1.0, 3.0, 5.0, 7.0, 9.0]
        self.assertAlmostEqual(fc.compute_trend(vals), 2.0, places=8)

    def test_negative_then_flat_mixed_signal(self):
        fc = ApyForecaster()
        vals = [10.0, 8.0, 6.0, 6.0, 6.0]
        slope = fc.compute_trend(vals)
        # Expect negative slope overall
        self.assertLess(slope, 0.0)


# ===========================================================================
# 5. Confidence helper tests (6)
# ===========================================================================

class TestConfidenceHelper(unittest.TestCase):

    def test_zero_points_none(self):
        fc = ApyForecaster()
        self.assertEqual(fc._confidence(0), "none")

    def test_one_point_low(self):
        fc = ApyForecaster()
        self.assertEqual(fc._confidence(1), "low")

    def test_six_points_low(self):
        fc = ApyForecaster()
        self.assertEqual(fc._confidence(_CONFIDENCE_MEDIUM - 1), "low")

    def test_seven_points_medium(self):
        fc = ApyForecaster()
        self.assertEqual(fc._confidence(_CONFIDENCE_MEDIUM), "medium")

    def test_thirteen_points_medium(self):
        fc = ApyForecaster()
        self.assertEqual(fc._confidence(_CONFIDENCE_HIGH - 1), "medium")

    def test_fourteen_points_high(self):
        fc = ApyForecaster()
        self.assertEqual(fc._confidence(_CONFIDENCE_HIGH), "high")


# ===========================================================================
# 6. Forecast — fallback (no history) tests (8)
# ===========================================================================

class TestForecastFallback(unittest.TestCase):

    def _fc_empty(self) -> ApyForecaster:
        td = tempfile.mkdtemp()
        return ApyForecaster(data_dir=td)

    def test_returns_dict(self):
        fc = self._fc_empty()
        result = fc.forecast("missing")
        self.assertIsInstance(result, dict)

    def test_confidence_none(self):
        fc = self._fc_empty()
        self.assertEqual(fc.forecast("missing")["confidence"], "none")

    def test_method_fallback(self):
        fc = self._fc_empty()
        self.assertEqual(fc.forecast("missing")["method"], "fallback")

    def test_forecast_apy_equals_default(self):
        fc = self._fc_empty()
        self.assertAlmostEqual(fc.forecast("missing", default_apy=6.5)["forecast_apy"], 6.5)

    def test_current_apy_equals_default(self):
        fc = self._fc_empty()
        self.assertAlmostEqual(fc.forecast("x", default_apy=3.0)["current_apy"], 3.0)

    def test_ema_apy_equals_default(self):
        fc = self._fc_empty()
        self.assertAlmostEqual(fc.forecast("x", default_apy=4.2)["ema_apy"], 4.2)

    def test_trend_per_day_zero(self):
        fc = self._fc_empty()
        self.assertEqual(fc.forecast("x")["trend_per_day"], 0.0)

    def test_adapter_id_in_result(self):
        fc = self._fc_empty()
        result = fc.forecast("my-adapter")
        self.assertEqual(result["adapter_id"], "my-adapter")


# ===========================================================================
# 7. Forecast — with historical data tests (14)
# ===========================================================================

class TestForecastWithData(unittest.TestCase):

    def _fc_with_apys(self, apys: list[float], adapter_id: str = "aave") -> ApyForecaster:
        td = Path(tempfile.mkdtemp())
        write_history(td, history_with_apys(adapter_id, apys))
        return ApyForecaster(data_dir=str(td))

    def test_returns_dict_with_required_keys(self):
        fc = self._fc_with_apys([5.0] * 20)
        result = fc.forecast("aave")
        for key in ("adapter_id", "current_apy", "ema_apy", "trend_per_day",
                    "forecast_apy", "confidence", "method"):
            self.assertIn(key, result)

    def test_method_ema_trend(self):
        fc = self._fc_with_apys([5.0] * 20)
        self.assertEqual(fc.forecast("aave")["method"], "ema_trend")

    def test_confidence_high_for_14_plus(self):
        fc = self._fc_with_apys([5.0] * 20)
        self.assertEqual(fc.forecast("aave")["confidence"], "high")

    def test_confidence_medium_for_7_to_13(self):
        fc = self._fc_with_apys([5.0] * 10)
        self.assertEqual(fc.forecast("aave")["confidence"], "medium")

    def test_confidence_low_for_under_7(self):
        fc = self._fc_with_apys([5.0] * 3)
        self.assertEqual(fc.forecast("aave")["confidence"], "low")

    def test_current_apy_is_last_value(self):
        fc = self._fc_with_apys([3.0, 4.0, 5.0, 6.0])
        self.assertAlmostEqual(fc.forecast("aave")["current_apy"], 6.0, places=5)

    def test_forecast_constant_series_same_as_current(self):
        # Constant APY → trend=0, ema=current → forecast=current
        fc = self._fc_with_apys([5.0] * 20)
        result = fc.forecast("aave", days_ahead=7)
        self.assertAlmostEqual(result["forecast_apy"], result["ema_apy"], places=4)

    def test_forecast_rising_series_above_current_ema(self):
        fc = self._fc_with_apys([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0,
                                   9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        result = fc.forecast("aave", days_ahead=7)
        self.assertGreater(result["forecast_apy"], result["ema_apy"])

    def test_forecast_clamp_floor(self):
        # Strongly decreasing → without clamp would go negative
        fc = self._fc_with_apys([20.0, 15.0, 10.0, 5.0, 2.0, 1.0,
                                   0.5, 0.1, 0.05, 0.01, 0.005, 0.001,
                                   0.0005, 0.0001])
        result = fc.forecast("aave", days_ahead=365)
        self.assertGreaterEqual(result["forecast_apy"], _FORECAST_MIN_APY)

    def test_forecast_clamp_ceiling(self):
        # Strongly increasing → without clamp would go >> 200
        fc = self._fc_with_apys([1.0] * 7 + [100.0, 200.0, 300.0, 400.0,
                                               500.0, 600.0, 700.0])
        result = fc.forecast("aave", days_ahead=365)
        self.assertLessEqual(result["forecast_apy"], _FORECAST_MAX_APY)

    def test_trend_per_day_positive_for_rising(self):
        fc = self._fc_with_apys(list(range(1, 20)))
        self.assertGreater(fc.forecast("aave")["trend_per_day"], 0.0)

    def test_trend_per_day_negative_for_falling(self):
        fc = self._fc_with_apys(list(range(20, 0, -1)))
        self.assertLess(fc.forecast("aave")["trend_per_day"], 0.0)

    def test_forecast_days_ahead_affects_result(self):
        fc = self._fc_with_apys(list(range(1, 20)))
        r7 = fc.forecast("aave", days_ahead=7)
        r14 = fc.forecast("aave", days_ahead=14)
        # More days ahead with positive trend → higher forecast
        self.assertGreater(r14["forecast_apy"], r7["forecast_apy"])

    def test_adapter_id_preserved(self):
        td = Path(tempfile.mkdtemp())
        write_history(td, history_with_apys("compound-v3-eth", [4.0] * 10))
        fc = ApyForecaster(data_dir=str(td))
        result = fc.forecast("compound-v3-eth")
        self.assertEqual(result["adapter_id"], "compound-v3-eth")


# ===========================================================================
# 8. ForecastAll tests (10)
# ===========================================================================

class TestForecastAll(unittest.TestCase):

    def _fc_two_adapters(self) -> ApyForecaster:
        td = Path(tempfile.mkdtemp())
        data = {
            "protocol_history": {
                "aave": [{"apy": 5.0}] * 20,
                "compound": [{"apy": 4.0}] * 15,
            }
        }
        write_history(td, data)
        return ApyForecaster(data_dir=str(td))

    def test_returns_dict(self):
        fc = self._fc_two_adapters()
        result = fc.forecast_all(["aave", "compound"])
        self.assertIsInstance(result, dict)

    def test_keys_match_input_ids(self):
        fc = self._fc_two_adapters()
        result = fc.forecast_all(["aave", "compound"])
        self.assertIn("aave", result)
        self.assertIn("compound", result)

    def test_count_matches_input(self):
        fc = self._fc_two_adapters()
        result = fc.forecast_all(["aave", "compound"])
        self.assertEqual(len(result), 2)

    def test_accepts_string_list(self):
        fc = self._fc_two_adapters()
        result = fc.forecast_all(["aave"])
        self.assertIn("aave", result)

    def test_accepts_dict_list(self):
        fc = self._fc_two_adapters()
        result = fc.forecast_all([{"id": "aave", "default_apy": 4.0}])
        self.assertIn("aave", result)

    def test_accepts_tuple_list(self):
        fc = self._fc_two_adapters()
        result = fc.forecast_all([("aave", 4.0)])
        self.assertIn("aave", result)

    def test_empty_input_returns_empty_dict(self):
        fc = self._fc_two_adapters()
        self.assertEqual(fc.forecast_all([]), {})

    def test_unknown_adapter_fallback(self):
        fc = self._fc_two_adapters()
        result = fc.forecast_all(["unknown-xyz"])
        self.assertEqual(result["unknown-xyz"]["confidence"], "none")

    def test_each_value_is_forecast_dict(self):
        fc = self._fc_two_adapters()
        for v in fc.forecast_all(["aave", "compound"]).values():
            self.assertIn("forecast_apy", v)
            self.assertIn("confidence", v)

    def test_default_apy_used_from_dict(self):
        td = Path(tempfile.mkdtemp())  # empty data dir
        fc = ApyForecaster(data_dir=str(td))
        result = fc.forecast_all([{"id": "missing", "default_apy": 9.9}])
        self.assertAlmostEqual(result["missing"]["forecast_apy"], 9.9)


# ===========================================================================
# 9. SaveForecast tests (10)
# ===========================================================================

class TestSaveForecast(unittest.TestCase):

    def _minimal_forecasts(self) -> dict:
        return {
            "aave": {
                "adapter_id": "aave",
                "current_apy": 5.0,
                "ema_apy": 5.0,
                "trend_per_day": 0.0,
                "forecast_apy": 5.0,
                "confidence": "high",
                "method": "ema_trend",
            }
        }

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            fc = ApyForecaster(data_dir=td)
            fc.save_forecast(self._minimal_forecasts())
            self.assertTrue((Path(td) / "apy_forecasts.json").exists())

    def test_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            fc = ApyForecaster(data_dir=td)
            fc.save_forecast(self._minimal_forecasts())
            data = json.loads((Path(td) / "apy_forecasts.json").read_text())
            self.assertIsInstance(data, dict)

    def test_file_has_generated_at(self):
        with tempfile.TemporaryDirectory() as td:
            fc = ApyForecaster(data_dir=td)
            fc.save_forecast(self._minimal_forecasts())
            data = json.loads((Path(td) / "apy_forecasts.json").read_text())
            self.assertIn("generated_at", data)

    def test_file_has_adapter_count(self):
        with tempfile.TemporaryDirectory() as td:
            fc = ApyForecaster(data_dir=td)
            fc.save_forecast(self._minimal_forecasts())
            data = json.loads((Path(td) / "apy_forecasts.json").read_text())
            self.assertEqual(data["adapter_count"], 1)

    def test_file_has_forecasts_key(self):
        with tempfile.TemporaryDirectory() as td:
            fc = ApyForecaster(data_dir=td)
            fc.save_forecast(self._minimal_forecasts())
            data = json.loads((Path(td) / "apy_forecasts.json").read_text())
            self.assertIn("forecasts", data)

    def test_forecasts_content_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            fc = ApyForecaster(data_dir=td)
            fc.save_forecast(self._minimal_forecasts())
            data = json.loads((Path(td) / "apy_forecasts.json").read_text())
            self.assertIn("aave", data["forecasts"])
            self.assertAlmostEqual(data["forecasts"]["aave"]["current_apy"], 5.0)

    def test_no_tmp_files_left(self):
        with tempfile.TemporaryDirectory() as td:
            fc = ApyForecaster(data_dir=td)
            fc.save_forecast(self._minimal_forecasts())
            tmp_files = list(Path(td).glob(".apy_forecasts_*.tmp"))
            self.assertEqual(len(tmp_files), 0)

    def test_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as td:
            fc = ApyForecaster(data_dir=td)
            fc.save_forecast({"a": {"forecast_apy": 1.0}})
            fc.save_forecast({"b": {"forecast_apy": 2.0}})
            data = json.loads((Path(td) / "apy_forecasts.json").read_text())
            self.assertIn("b", data["forecasts"])
            self.assertNotIn("a", data["forecasts"])

    def test_empty_forecasts_dict(self):
        with tempfile.TemporaryDirectory() as td:
            fc = ApyForecaster(data_dir=td)
            fc.save_forecast({})
            data = json.loads((Path(td) / "apy_forecasts.json").read_text())
            self.assertEqual(data["adapter_count"], 0)

    def test_creates_data_dir_if_missing(self):
        with tempfile.TemporaryDirectory() as td:
            new_dir = os.path.join(td, "nested", "data")
            fc = ApyForecaster(data_dir=new_dir)
            fc.save_forecast(self._minimal_forecasts())
            self.assertTrue((Path(new_dir) / "apy_forecasts.json").exists())


# ===========================================================================
# 10. Import hygiene tests (4)
# ===========================================================================

class TestImportHygiene(unittest.TestCase):

    def test_no_numpy(self):
        import spa_core.analytics.apy_forecaster as m
        src = Path(m.__file__).read_text()
        self.assertNotIn("import numpy", src)
        self.assertNotIn("import np", src)

    def test_no_requests(self):
        import spa_core.analytics.apy_forecaster as m
        src = Path(m.__file__).read_text()
        self.assertNotIn("import requests", src)

    def test_no_subprocess(self):
        import spa_core.analytics.apy_forecaster as m
        src = Path(m.__file__).read_text()
        self.assertNotIn("import subprocess", src)

    def test_no_execution_import(self):
        import spa_core.analytics.apy_forecaster as m
        src = Path(m.__file__).read_text()
        self.assertNotIn("from spa_core.execution", src)
        self.assertNotIn("import spa_core.execution", src)


# ===========================================================================
# 11. Edge cases (8)
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_forecast_days_ahead_zero(self):
        td = Path(tempfile.mkdtemp())
        write_history(td, history_with_apys("aave", [5.0] * 14))
        fc = ApyForecaster(data_dir=str(td))
        result = fc.forecast("aave", days_ahead=0)
        # forecast = ema + trend * 0 = ema
        self.assertAlmostEqual(result["forecast_apy"], result["ema_apy"], places=4)

    def test_very_large_days_ahead_clamped(self):
        td = Path(tempfile.mkdtemp())
        write_history(td, history_with_apys("aave", list(range(1, 21))))
        fc = ApyForecaster(data_dir=str(td))
        result = fc.forecast("aave", days_ahead=100000)
        self.assertLessEqual(result["forecast_apy"], _FORECAST_MAX_APY)
        self.assertGreaterEqual(result["forecast_apy"], _FORECAST_MIN_APY)

    def test_ema_single_element_list(self):
        fc = ApyForecaster()
        self.assertAlmostEqual(fc.compute_ema([42.0]), 42.0)

    def test_trend_two_identical_values(self):
        fc = ApyForecaster()
        self.assertAlmostEqual(fc.compute_trend([5.0, 5.0]), 0.0, places=8)

    def test_forecast_all_with_duplicate_ids(self):
        td = Path(tempfile.mkdtemp())
        write_history(td, history_with_apys("aave", [5.0] * 14))
        fc = ApyForecaster(data_dir=str(td))
        # Duplicate id: last write wins
        result = fc.forecast_all(["aave", "aave"])
        # Python dict: aave key appears once (last assignment)
        self.assertIn("aave", result)

    def test_load_history_string_not_list_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            data = {"protocol_history": {"aave": "not-a-list"}}
            write_history(td, data)
            fc = ApyForecaster(data_dir=str(td))
            self.assertEqual(fc.load_history("aave"), [])

    def test_ema_with_integer_values(self):
        fc = ApyForecaster()
        # Integers should be handled transparently
        result = fc.compute_ema([5, 6, 7], alpha=0.3)
        self.assertIsInstance(result, float)

    def test_forecast_result_all_finite(self):
        td = Path(tempfile.mkdtemp())
        write_history(td, history_with_apys("aave", [3.5, 4.0, 4.5, 5.0,
                                                       5.5, 6.0, 6.5, 7.0,
                                                       7.5, 8.0, 8.5, 9.0,
                                                       9.5, 10.0]))
        fc = ApyForecaster(data_dir=str(td))
        result = fc.forecast("aave")
        for key in ("current_apy", "ema_apy", "trend_per_day", "forecast_apy"):
            self.assertTrue(math.isfinite(result[key]),
                            f"Expected finite for {key}, got {result[key]}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
