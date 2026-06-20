"""
Tests for APY Forecast Engine v2 (MP-637).

spa_core/tests/test_apy_forecast_v2.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import unittest
import tempfile
from pathlib import Path

# Ensure spa_core package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.apy_forecast_v2 import (
    ALPHA,
    HORIZONS,
    APYForecastV2,
    ForecastModel,
    ForecastPoint,
    _atomic_write,
    _now_iso,
)


# ---------------------------------------------------------------------------
# ForecastModel enum
# ---------------------------------------------------------------------------

class TestForecastModel(unittest.TestCase):

    def test_linear_value(self):
        self.assertEqual(ForecastModel.LINEAR.value, "LINEAR")

    def test_exp_smoothing_value(self):
        self.assertEqual(ForecastModel.EXPONENTIAL_SMOOTHING.value, "EXPONENTIAL_SMOOTHING")

    def test_moving_average_value(self):
        self.assertEqual(ForecastModel.MOVING_AVERAGE.value, "MOVING_AVERAGE")

    def test_is_str_subclass(self):
        self.assertIsInstance(ForecastModel.LINEAR, str)

    def test_round_trip_from_value(self):
        for m in ForecastModel:
            self.assertEqual(ForecastModel(m.value), m)


# ---------------------------------------------------------------------------
# ForecastPoint dataclass
# ---------------------------------------------------------------------------

class TestForecastPoint(unittest.TestCase):

    def _make(self, **kw):
        defaults = dict(
            horizon_days=7,
            predicted_apy=0.05,
            lower_bound=0.04,
            upper_bound=0.06,
            confidence="HIGH",
            model_used=ForecastModel.LINEAR,
        )
        defaults.update(kw)
        return ForecastPoint(**defaults)

    def test_to_dict_keys(self):
        fp = self._make()
        d = fp.to_dict()
        self.assertIn("horizon_days", d)
        self.assertIn("predicted_apy", d)
        self.assertIn("lower_bound", d)
        self.assertIn("upper_bound", d)
        self.assertIn("confidence", d)
        self.assertIn("model_used", d)

    def test_to_dict_model_is_string(self):
        fp = self._make(model_used=ForecastModel.EXPONENTIAL_SMOOTHING)
        self.assertIsInstance(fp.to_dict()["model_used"], str)

    def test_from_dict_round_trip(self):
        fp = self._make(horizon_days=30, predicted_apy=0.06, confidence="MEDIUM")
        d = fp.to_dict()
        fp2 = ForecastPoint.from_dict(d)
        self.assertEqual(fp.horizon_days, fp2.horizon_days)
        self.assertAlmostEqual(fp.predicted_apy, fp2.predicted_apy, places=5)
        self.assertEqual(fp.confidence, fp2.confidence)

    def test_rounding_in_to_dict(self):
        fp = self._make(predicted_apy=0.1234567890)
        d = fp.to_dict()
        # Should be rounded to 6 decimal places
        self.assertEqual(d["predicted_apy"], round(0.1234567890, 6))

    def test_confidence_values(self):
        for conf in ("HIGH", "MEDIUM", "LOW"):
            fp = self._make(confidence=conf)
            self.assertEqual(fp.to_dict()["confidence"], conf)


# ---------------------------------------------------------------------------
# Linear forecast
# ---------------------------------------------------------------------------

class TestLinearForecast(unittest.TestCase):

    def setUp(self):
        self.engine = APYForecastV2()

    def test_empty_history_returns_zero(self):
        result = self.engine._linear_forecast([], 1)
        self.assertEqual(result, 0.0)

    def test_single_value_returns_clamped(self):
        result = self.engine._linear_forecast([0.05], 7)
        self.assertAlmostEqual(result, 0.05)

    def test_flat_series_returns_mean(self):
        h = [0.04, 0.04, 0.04, 0.04, 0.04]
        result = self.engine._linear_forecast(h, 1)
        self.assertAlmostEqual(result, 0.04, places=5)

    def test_rising_series_projects_up(self):
        # Perfectly linear increasing series
        h = [0.01, 0.02, 0.03, 0.04, 0.05]
        result = self.engine._linear_forecast(h, 1)
        self.assertGreater(result, 0.05)

    def test_falling_series_projects_down(self):
        h = [0.05, 0.04, 0.03, 0.02, 0.01]
        result = self.engine._linear_forecast(h, 1)
        self.assertLess(result, 0.01 + 1e-9)  # clamp floor = 0

    def test_result_clamped_at_zero(self):
        h = [0.001, 0.0005, 0.0001]
        result = self.engine._linear_forecast(h, 100)
        self.assertGreaterEqual(result, 0.0)

    def test_result_clamped_at_max(self):
        h = [0.40, 0.45, 0.49]
        result = self.engine._linear_forecast(h, 100)
        self.assertLessEqual(result, 0.50)

    def test_longer_horizon_deviates_more(self):
        h = [0.03, 0.04, 0.05, 0.06, 0.07]
        r1 = self.engine._linear_forecast(h, 1)
        r7 = self.engine._linear_forecast(h, 7)
        self.assertGreater(r7, r1)


# ---------------------------------------------------------------------------
# Exponential smoothing
# ---------------------------------------------------------------------------

class TestExponentialSmoothing(unittest.TestCase):

    def setUp(self):
        self.engine = APYForecastV2()

    def test_empty_history_returns_zero(self):
        self.assertEqual(self.engine._exponential_smoothing([], 7), 0.0)

    def test_single_value_returns_it(self):
        result = self.engine._exponential_smoothing([0.05], 1)
        self.assertAlmostEqual(result, 0.05)

    def test_stable_series_stays_stable(self):
        h = [0.05] * 10
        result = self.engine._exponential_smoothing(h, 7)
        self.assertAlmostEqual(result, 0.05, places=4)

    def test_rising_series_projects_up(self):
        h = [0.03, 0.04, 0.05, 0.06, 0.07]
        result = self.engine._exponential_smoothing(h, 1)
        # Smoothed last value should be close to 0.07 and trending up
        self.assertGreater(result, 0.05)

    def test_alpha_constant(self):
        self.assertEqual(APYForecastV2.ALPHA, 0.3)

    def test_result_within_bounds(self):
        h = [0.01, 0.02, 0.03]
        for horizon in [1, 7, 30]:
            r = self.engine._exponential_smoothing(h, horizon)
            self.assertGreaterEqual(r, 0.0)
            self.assertLessEqual(r, 0.50)


# ---------------------------------------------------------------------------
# Moving average
# ---------------------------------------------------------------------------

class TestMovingAverage(unittest.TestCase):

    def setUp(self):
        self.engine = APYForecastV2()

    def test_empty_history_returns_zero(self):
        self.assertEqual(self.engine._moving_average([]), 0.0)

    def test_single_value(self):
        self.assertAlmostEqual(self.engine._moving_average([0.05]), 0.05)

    def test_window_of_7_default(self):
        h = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08]
        result = self.engine._moving_average(h)
        expected = sum(h[-7:]) / 7
        self.assertAlmostEqual(result, expected, places=6)

    def test_history_shorter_than_window(self):
        h = [0.04, 0.05]
        result = self.engine._moving_average(h, window=7)
        self.assertAlmostEqual(result, 0.045, places=6)

    def test_custom_window(self):
        h = [0.01, 0.02, 0.03, 0.04, 0.05]
        result = self.engine._moving_average(h, window=3)
        self.assertAlmostEqual(result, (0.03 + 0.04 + 0.05) / 3, places=6)

    def test_result_within_bounds(self):
        h = [0.02, 0.03, 0.04]
        r = self.engine._moving_average(h)
        self.assertGreaterEqual(r, 0.0)
        self.assertLessEqual(r, 0.50)


# ---------------------------------------------------------------------------
# forecast_adapter
# ---------------------------------------------------------------------------

class TestForecastAdapter(unittest.TestCase):

    def setUp(self):
        self.engine = APYForecastV2()

    def test_returns_four_horizons(self):
        h = [0.04, 0.045, 0.05, 0.055, 0.06]
        points = self.engine.forecast_adapter("test", h)
        self.assertEqual(len(points), 4)
        horizons = [p.horizon_days for p in points]
        self.assertEqual(horizons, HORIZONS)

    def test_short_history_low_confidence(self):
        # len < 3 → LOW
        for l in (0, 1, 2):
            h = [0.05] * l
            points = self.engine.forecast_adapter("x", h)
            for p in points:
                self.assertEqual(p.confidence, "LOW", f"len={l}")

    def test_high_confidence_flat_series(self):
        # All models agree → stdev ≈ 0 → HIGH
        h = [0.05] * 10
        points = self.engine.forecast_adapter("x", h)
        # At least some should be HIGH (flat series → all models predict ~0.05)
        confidences = {p.confidence for p in points}
        self.assertIn("HIGH", confidences)

    def test_bounds_ordered(self):
        h = [0.03, 0.04, 0.05, 0.06, 0.07]
        points = self.engine.forecast_adapter("test", h)
        for p in points:
            self.assertLessEqual(p.lower_bound, p.predicted_apy + 1e-9)
            self.assertGreaterEqual(p.upper_bound, p.predicted_apy - 1e-9)

    def test_bounds_clamped_to_valid_range(self):
        h = [0.48, 0.49, 0.49, 0.50, 0.50]
        points = self.engine.forecast_adapter("high_apy", h)
        for p in points:
            self.assertGreaterEqual(p.lower_bound, 0.0)
            self.assertLessEqual(p.upper_bound, 0.50)

    def test_all_points_are_ForecastPoint(self):
        h = [0.04, 0.05, 0.06, 0.07, 0.08]
        points = self.engine.forecast_adapter("test", h)
        for p in points:
            self.assertIsInstance(p, ForecastPoint)

    def test_empty_history_handled_gracefully(self):
        points = self.engine.forecast_adapter("test", [])
        self.assertEqual(len(points), 4)
        for p in points:
            self.assertEqual(p.confidence, "LOW")


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------

class TestGenerateReport(unittest.TestCase):

    def setUp(self):
        self.engine = APYForecastV2()
        self.apy_map = {"aave": 0.035, "compound": 0.048}
        self.hist_map = {
            "aave": [0.03, 0.032, 0.034, 0.035, 0.036],
            "compound": [0.045, 0.046, 0.047, 0.048, 0.049],
        }

    def test_report_has_forecasts_key(self):
        r = self.engine.generate_report(self.apy_map, self.hist_map)
        self.assertIn("forecasts", r)

    def test_report_has_advisory(self):
        r = self.engine.generate_report(self.apy_map, self.hist_map)
        self.assertIn("advisory", r)
        self.assertIn("statistical estimates", r["advisory"])

    def test_report_has_generated_at(self):
        r = self.engine.generate_report(self.apy_map, self.hist_map)
        self.assertIn("generated_at", r)

    def test_each_adapter_has_forecasts(self):
        r = self.engine.generate_report(self.apy_map, self.hist_map)
        for adapter_id in self.apy_map:
            self.assertIn(adapter_id, r["forecasts"])

    def test_each_forecast_has_four_horizons(self):
        r = self.engine.generate_report(self.apy_map, self.hist_map)
        for adapter_id, points in r["forecasts"].items():
            self.assertEqual(len(points), 4, f"adapter={adapter_id}")

    def test_missing_history_defaults_to_current_apy(self):
        # history_map missing an adapter → fallback [current_apy]
        r = self.engine.generate_report({"x": 0.05}, {})
        self.assertIn("x", r["forecasts"])
        self.assertEqual(len(r["forecasts"]["x"]), 4)

    def test_empty_apy_map(self):
        r = self.engine.generate_report({}, {})
        self.assertEqual(r["forecasts"], {})


# ---------------------------------------------------------------------------
# save_report / ring-buffer
# ---------------------------------------------------------------------------

class TestSaveReport(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmpdir.name)
        self.engine = APYForecastV2(data_dir=self.data_dir)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _dummy_report(self, tag: str = "x") -> dict:
        return {"forecasts": {tag: []}, "advisory": "test", "generated_at": _now_iso()}

    def test_file_created_after_save(self):
        r = self._dummy_report()
        self.engine.save_report(r)
        self.assertTrue((self.data_dir / "apy_forecast_v2.json").exists())

    def test_ring_buffer_accumulates(self):
        for i in range(5):
            self.engine.save_report(self._dummy_report(str(i)))
        data = json.loads((self.data_dir / "apy_forecast_v2.json").read_text())
        self.assertEqual(len(data), 5)

    def test_ring_buffer_trims_at_30(self):
        for i in range(35):
            self.engine.save_report(self._dummy_report(str(i)))
        data = json.loads((self.data_dir / "apy_forecast_v2.json").read_text())
        self.assertEqual(len(data), 30)

    def test_atomic_write_no_tmp_files_remain(self):
        self.engine.save_report(self._dummy_report())
        tmp_files = list(self.data_dir.glob(".tmp_apy_forecast_v2_*"))
        self.assertEqual(len(tmp_files), 0)

    def test_valid_json_output(self):
        self.engine.save_report(self._dummy_report())
        text = (self.data_dir / "apy_forecast_v2.json").read_text()
        parsed = json.loads(text)
        self.assertIsInstance(parsed, list)

    def test_corrupted_existing_file_handled(self):
        out = self.data_dir / "apy_forecast_v2.json"
        out.write_text("NOT JSON")
        # Should not raise
        self.engine.save_report(self._dummy_report())
        data = json.loads(out.read_text())
        self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):

    def test_now_iso_is_string(self):
        result = _now_iso()
        self.assertIsInstance(result, str)

    def test_now_iso_contains_T(self):
        result = _now_iso()
        self.assertIn("T", result)

    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.json"
            _atomic_write(p, {"key": "value"})
            self.assertTrue(p.exists())

    def test_atomic_write_correct_content(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.json"
            _atomic_write(p, [1, 2, 3])
            self.assertEqual(json.loads(p.read_text()), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
