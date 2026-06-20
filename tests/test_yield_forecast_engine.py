"""
tests/test_yield_forecast_engine.py

MP-1437 — 20 tests for YieldForecastEngine (spa_core/analytics/yield_forecast_engine.py)
Sprint v10.53
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root on path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.yield_forecast_engine import (
    YieldForecastEngine,
    ForecastResult,
    LINEAR_WEIGHT,
    EMA_WEIGHT,
    TREND_UP,
    TREND_STABLE,
    TREND_DOWN,
    _linear_regression,
    _r_squared,
    _compute_ema_series,
    classify_trend,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RISING_SERIES  = [0.030, 0.032, 0.034, 0.036, 0.038, 0.040, 0.042, 0.044, 0.046, 0.048]
_FLAT_SERIES    = [0.040] * 20
_FALLING_SERIES = [0.050, 0.048, 0.046, 0.044, 0.042, 0.040, 0.038, 0.036, 0.034, 0.032]


class TestInstantiation(unittest.TestCase):
    """TC-YFE-01..02: Class instantiation."""

    def test_01_default_instantiation(self):
        """YieldForecastEngine() instantiates without error."""
        engine = YieldForecastEngine()
        self.assertIsInstance(engine, YieldForecastEngine)

    def test_02_custom_data_dir(self):
        """Custom data_dir is stored correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = YieldForecastEngine(data_dir=tmpdir)
            self.assertEqual(str(engine._data_dir), tmpdir)


class TestLinearForecast(unittest.TestCase):
    """TC-YFE-03..05: linear_forecast()."""

    def setUp(self):
        self.engine = YieldForecastEngine()

    def test_03_rising_series_projects_higher(self):
        """linear_forecast on rising series returns value above last element."""
        proj = self.engine.linear_forecast(_RISING_SERIES, forecast_days=5)
        self.assertGreater(proj, _RISING_SERIES[-1])

    def test_04_empty_series_returns_zero(self):
        """linear_forecast([]) returns 0.0."""
        self.assertEqual(self.engine.linear_forecast([], forecast_days=1), 0.0)

    def test_05_single_element_returns_that_value(self):
        """linear_forecast([v]) returns v for any forecast_days."""
        self.assertAlmostEqual(self.engine.linear_forecast([0.05], forecast_days=10), 0.05)


class TestEmaForecast(unittest.TestCase):
    """TC-YFE-06..08: ema_forecast()."""

    def setUp(self):
        self.engine = YieldForecastEngine()

    def test_06_rising_series_ema_above_mean(self):
        """EMA forecast on rising series > mean of series (recency-weighted)."""
        proj = self.engine.ema_forecast(_RISING_SERIES, forecast_days=1)
        mean = sum(_RISING_SERIES) / len(_RISING_SERIES)
        self.assertGreater(proj, mean)

    def test_07_empty_series_returns_zero(self):
        """ema_forecast([]) returns 0.0."""
        self.assertEqual(self.engine.ema_forecast([], forecast_days=1), 0.0)

    def test_08_single_element_returns_that_value(self):
        """ema_forecast([v]) returns v."""
        self.assertAlmostEqual(self.engine.ema_forecast([0.04], forecast_days=5), 0.04)


class TestEnsembleForecast(unittest.TestCase):
    """TC-YFE-09..14: ensemble_forecast()."""

    def setUp(self):
        self.engine = YieldForecastEngine()

    def test_09_returns_forecast_result_instance(self):
        """ensemble_forecast returns ForecastResult dataclass."""
        result = self.engine.ensemble_forecast(_RISING_SERIES, forecast_days=7)
        self.assertIsInstance(result, ForecastResult)

    def test_10_ensemble_is_weighted_average_of_linear_and_ema(self):
        """projected_apy == 0.4*linear + 0.6*ema (within floating-point tolerance)."""
        result = self.engine.ensemble_forecast(_RISING_SERIES, forecast_days=7)
        expected = LINEAR_WEIGHT * result.projected_apy_linear + EMA_WEIGHT * result.projected_apy_ema
        self.assertAlmostEqual(result.projected_apy, expected, places=10)

    def test_11_empty_series_returns_zero_apy(self):
        """ensemble_forecast([]) → projected_apy = 0.0."""
        result = self.engine.ensemble_forecast([], forecast_days=7)
        self.assertEqual(result.projected_apy, 0.0)

    def test_12_empty_series_trend_is_stable(self):
        """ensemble_forecast([]) → trend_direction = STABLE."""
        result = self.engine.ensemble_forecast([], forecast_days=7)
        self.assertEqual(result.trend_direction, TREND_STABLE)

    def test_13_forecast_range_min_lte_max(self):
        """forecast_range['min'] ≤ forecast_range['max'] always."""
        result = self.engine.ensemble_forecast(_RISING_SERIES, forecast_days=7)
        self.assertLessEqual(result.forecast_range["min"], result.forecast_range["max"])

    def test_14_horizon_days_stored_correctly(self):
        """result.horizon_days matches forecast_days argument."""
        result = self.engine.ensemble_forecast(_RISING_SERIES, forecast_days=14)
        self.assertEqual(result.horizon_days, 14)


class TestTrendAndConfidence(unittest.TestCase):
    """TC-YFE-15..17: trend direction and R² confidence."""

    def setUp(self):
        self.engine = YieldForecastEngine()

    def test_15_rising_series_trend_up(self):
        """Strongly rising series → trend_direction = UP."""
        result = self.engine.ensemble_forecast(_RISING_SERIES, forecast_days=1)
        self.assertEqual(result.trend_direction, TREND_UP)

    def test_16_falling_series_trend_down(self):
        """Strongly falling series → trend_direction = DOWN."""
        result = self.engine.ensemble_forecast(_FALLING_SERIES, forecast_days=1)
        self.assertEqual(result.trend_direction, TREND_DOWN)

    def test_17_flat_series_confidence_one(self):
        """Flat series (constant APY) → R² confidence = 1.0."""
        conf = self.engine.forecast_confidence(_FLAT_SERIES)
        self.assertAlmostEqual(conf, 1.0, places=6)


class TestForecastResultToDict(unittest.TestCase):
    """TC-YFE-18: ForecastResult.to_dict()."""

    def test_18_to_dict_has_all_required_keys(self):
        """ForecastResult.to_dict() contains all required keys."""
        engine = YieldForecastEngine()
        result = engine.ensemble_forecast(_RISING_SERIES, forecast_days=7)
        d = result.to_dict()
        required = {
            "computed_at", "horizon_days", "series_length",
            "projected_apy", "projected_apy_linear", "projected_apy_ema",
            "confidence", "trend_direction", "linear_slope",
            "forecast_range", "advisory",
        }
        self.assertTrue(required.issubset(d.keys()))


class TestSaveAndLoadHistory(unittest.TestCase):
    """TC-YFE-19..20: save/load round-trip."""

    def test_19_save_writes_json_ring_buffer(self):
        """save() creates a JSON file; the entry can be reloaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = YieldForecastEngine(data_dir=tmpdir)
            result = engine.ensemble_forecast(_RISING_SERIES, forecast_days=7)
            log_path = engine.save(result)

            self.assertTrue(os.path.exists(log_path))
            with open(log_path, "r") as fh:
                log = json.load(fh)

            self.assertIsInstance(log, list)
            self.assertGreater(len(log), 0)
            self.assertEqual(log[-1]["horizon_days"], 7)

    def test_20_load_history_returns_list_after_save(self):
        """load_history() returns non-empty list after save()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = YieldForecastEngine(data_dir=tmpdir)
            result = engine.ensemble_forecast(_FLAT_SERIES, forecast_days=3)
            engine.save(result)

            history = engine.load_history()
            self.assertIsInstance(history, list)
            self.assertGreater(len(history), 0)
            # last entry matches saved result
            self.assertAlmostEqual(history[-1]["projected_apy"], result.to_dict()["projected_apy"], places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
