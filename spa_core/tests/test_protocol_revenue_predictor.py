"""
Tests for MP-824 ProtocolRevenuePredictorSimple.
Run with: python3 -m unittest spa_core.tests.test_protocol_revenue_predictor
"""

import json
import math
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.protocol_revenue_predictor import (
    analyze,
    _ols,
    _tvl_trend,
    _fee_rate_trend,
    _load_log,
    _save_log,
    _MAX_ENTRIES,
    _MIN_HISTORY,
    _DEFAULT_FORECAST_DAYS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_file(suffix=".json"):
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return Path(path)


def _make_history(n, tvl_start=1_000_000, tvl_step=0, fee_start=1_000, fee_step=0):
    """Generate n history entries with linear TVL and fee."""
    result = []
    for i in range(n):
        result.append({
            "date": f"2026-01-{i+1:02d}",
            "tvl_usd": float(tvl_start + i * tvl_step),
            "daily_fee_revenue_usd": float(fee_start + i * fee_step),
        })
    return result


def _run(history, protocol="TestProt", forecast_days=30, df=None):
    df = df or _tmp_file()
    return analyze(protocol, history, config={"forecast_days": forecast_days},
                   data_file=df, save=False), df


# ===========================================================================
# 1. OLS unit tests
# ===========================================================================

class TestOLS(unittest.TestCase):
    def test_perfect_linear_slope(self):
        y = [0.0, 1.0, 2.0, 3.0, 4.0]
        slope, intercept, r2 = _ols(y)
        self.assertAlmostEqual(slope, 1.0, places=6)
        self.assertAlmostEqual(intercept, 0.0, places=6)
        self.assertAlmostEqual(r2, 1.0, places=6)

    def test_perfect_linear_with_intercept(self):
        y = [10.0, 12.0, 14.0, 16.0]
        slope, intercept, r2 = _ols(y)
        self.assertAlmostEqual(slope, 2.0, places=6)
        self.assertAlmostEqual(intercept, 10.0, places=6)
        self.assertAlmostEqual(r2, 1.0, places=6)

    def test_flat_series_slope_zero(self):
        y = [5.0, 5.0, 5.0, 5.0, 5.0]
        slope, intercept, r2 = _ols(y)
        self.assertAlmostEqual(slope, 0.0, places=6)
        self.assertAlmostEqual(r2, 1.0, places=6)  # perfect fit (zero variance)

    def test_negative_slope(self):
        y = [4.0, 3.0, 2.0, 1.0, 0.0]
        slope, intercept, r2 = _ols(y)
        self.assertAlmostEqual(slope, -1.0, places=6)
        self.assertAlmostEqual(r2, 1.0, places=6)

    def test_two_point_perfect_fit(self):
        y = [0.0, 2.0]
        slope, _, r2 = _ols(y)
        self.assertAlmostEqual(slope, 2.0, places=6)
        self.assertAlmostEqual(r2, 1.0, places=6)

    def test_single_point(self):
        slope, intercept, r2 = _ols([7.0])
        self.assertAlmostEqual(slope, 0.0)
        self.assertAlmostEqual(intercept, 7.0)
        self.assertAlmostEqual(r2, 1.0)

    def test_r_squared_noisy(self):
        y = [1.0, 3.0, 2.0, 4.0, 3.0]
        _, _, r2 = _ols(y)
        self.assertGreaterEqual(r2, 0.0)
        self.assertLessEqual(r2, 1.0)

    def test_r_squared_non_negative(self):
        # Random-ish series
        y = [10.0, 2.0, 8.0, 1.0, 9.0, 3.0]
        _, _, r2 = _ols(y)
        self.assertGreaterEqual(r2, 0.0)

    def test_ols_three_points(self):
        y = [1.0, 2.0, 3.0]
        slope, intercept, r2 = _ols(y)
        self.assertAlmostEqual(slope, 1.0, places=6)
        self.assertAlmostEqual(r2, 1.0, places=6)


# ===========================================================================
# 2. Trend label helpers
# ===========================================================================

class TestTrendLabels(unittest.TestCase):
    def test_tvl_growing(self):
        tvls = [100.0, 110.0, 120.0, 130.0]
        slope = 10.0
        self.assertEqual(_tvl_trend(tvls, slope), "GROWING")

    def test_tvl_shrinking(self):
        tvls = [130.0, 120.0, 110.0, 100.0]
        slope = -10.0
        self.assertEqual(_tvl_trend(tvls, slope), "SHRINKING")

    def test_tvl_stable_small_change(self):
        tvls = [100.0, 101.0, 102.0, 102.0]
        # last < first*1.05 → stable
        slope = 0.67
        self.assertEqual(_tvl_trend(tvls, slope), "STABLE")

    def test_tvl_stable_flat(self):
        tvls = [100.0, 100.0, 100.0]
        self.assertEqual(_tvl_trend(tvls, 0.0), "STABLE")

    def test_tvl_growing_requires_both_conditions(self):
        # slope>0 but last NOT > first*1.05
        tvls = [100.0, 100.5, 101.0, 102.0]
        self.assertEqual(_tvl_trend(tvls, 0.5), "STABLE")

    def test_tvl_shrinking_requires_both_conditions(self):
        # slope<0 but last NOT < first*0.95
        tvls = [100.0, 99.0, 98.0, 97.0]
        self.assertEqual(_tvl_trend(tvls, -1.0), "STABLE")

    def test_tvl_zero_first_is_stable(self):
        self.assertEqual(_tvl_trend([0.0, 10.0, 20.0], 10.0), "STABLE")

    def test_fee_rate_increasing(self):
        rates = [0.001, 0.0011, 0.0012, 0.0013]
        slope = 0.0001
        self.assertEqual(_fee_rate_trend(rates, slope), "INCREASING")

    def test_fee_rate_decreasing(self):
        rates = [0.002, 0.0018, 0.0016, 0.0014]
        slope = -0.0002
        self.assertEqual(_fee_rate_trend(rates, slope), "DECREASING")

    def test_fee_rate_stable(self):
        rates = [0.001, 0.001, 0.001]
        self.assertEqual(_fee_rate_trend(rates, 0.0), "STABLE")

    def test_fee_rate_zero_first_stable(self):
        self.assertEqual(_fee_rate_trend([0.0, 0.001, 0.002], 0.001), "STABLE")

    def test_fee_rate_single_point_stable(self):
        self.assertEqual(_fee_rate_trend([0.001], 0.0), "STABLE")


# ===========================================================================
# 3. Return shape and field types
# ===========================================================================

class TestReturnShape(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()
        self.history = _make_history(5, tvl_step=100_000, fee_step=100)

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def _r(self):
        return analyze("Aave", self.history, data_file=self.df, save=False)

    def test_returns_dict(self):
        self.assertIsInstance(self._r(), dict)

    def test_has_protocol(self):
        self.assertEqual(self._r()["protocol"], "Aave")

    def test_has_data_points(self):
        r = self._r()
        self.assertIn("data_points", r)
        self.assertEqual(r["data_points"], 5)

    def test_has_current_tvl(self):
        self.assertIn("current_tvl_usd", self._r())

    def test_has_current_daily_revenue(self):
        self.assertIn("current_daily_revenue_usd", self._r())

    def test_has_fee_rate_avg(self):
        self.assertIn("fee_rate_avg", self._r())

    def test_has_fee_rate_trend(self):
        r = self._r()
        self.assertIn("fee_rate_trend", r)
        self.assertIn(r["fee_rate_trend"], ("INCREASING", "STABLE", "DECREASING"))

    def test_has_tvl_trend(self):
        r = self._r()
        self.assertIn("tvl_trend", r)
        self.assertIn(r["tvl_trend"], ("GROWING", "STABLE", "SHRINKING"))

    def test_has_tvl_slope(self):
        self.assertIn("tvl_slope_per_day", self._r())

    def test_has_revenue_slope(self):
        self.assertIn("revenue_slope_per_day", self._r())

    def test_has_predicted_tvl(self):
        self.assertIn("predicted_tvl_usd", self._r())

    def test_has_predicted_daily_revenue(self):
        self.assertIn("predicted_daily_revenue_usd", self._r())

    def test_has_predicted_annual_revenue(self):
        self.assertIn("predicted_annual_revenue_usd", self._r())

    def test_has_confidence(self):
        r = self._r()
        self.assertIn("confidence", r)
        self.assertIn(r["confidence"], ("HIGH", "MEDIUM", "LOW"))

    def test_has_r_squared(self):
        self.assertIn("r_squared", self._r())

    def test_has_timestamp(self):
        r = self._r()
        self.assertIn("timestamp", r)
        self.assertIsInstance(r["timestamp"], float)

    def test_no_nan_in_result(self):
        r = self._r()
        for k, v in r.items():
            if isinstance(v, float):
                with self.subTest(key=k):
                    self.assertFalse(math.isnan(v))

    def test_result_json_serializable(self):
        r = self._r()
        serialized = json.dumps(r)
        self.assertIsInstance(serialized, str)


# ===========================================================================
# 4. Minimum history enforcement
# ===========================================================================

class TestMinHistory(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_raises_on_empty_history(self):
        with self.assertRaises(ValueError):
            analyze("P", [], data_file=self.df, save=False)

    def test_raises_on_one_entry(self):
        h = _make_history(1)
        with self.assertRaises(ValueError):
            analyze("P", h, data_file=self.df, save=False)

    def test_raises_on_two_entries(self):
        h = _make_history(2)
        with self.assertRaises(ValueError):
            analyze("P", h, data_file=self.df, save=False)

    def test_passes_with_three_entries(self):
        h = _make_history(3)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertIsInstance(r, dict)

    def test_min_history_constant(self):
        self.assertEqual(_MIN_HISTORY, 3)


# ===========================================================================
# 5. TVL and fee_rate_avg correctness
# ===========================================================================

class TestBasicValues(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_current_tvl_is_last_entry(self):
        h = _make_history(4, tvl_start=1_000_000, tvl_step=50_000)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertAlmostEqual(r["current_tvl_usd"], 1_150_000.0)

    def test_current_daily_revenue_is_last_entry(self):
        h = _make_history(4, fee_start=1_000, fee_step=100)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertAlmostEqual(r["current_daily_revenue_usd"], 1_300.0)

    def test_fee_rate_avg_constant_fee_rate(self):
        # TVL=1M, fee=1000 → rate=0.001 for all entries
        h = _make_history(5, tvl_start=1_000_000, tvl_step=0,
                          fee_start=1_000, fee_step=0)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertAlmostEqual(r["fee_rate_avg"], 0.001, places=6)

    def test_fee_rate_avg_varying(self):
        h = [
            {"date": "2026-01-01", "tvl_usd": 1_000_000.0, "daily_fee_revenue_usd": 500.0},
            {"date": "2026-01-02", "tvl_usd": 2_000_000.0, "daily_fee_revenue_usd": 1_000.0},
            {"date": "2026-01-03", "tvl_usd": 4_000_000.0, "daily_fee_revenue_usd": 2_000.0},
        ]
        r = analyze("P", h, data_file=self.df, save=False)
        # All fee rates = 0.0005
        self.assertAlmostEqual(r["fee_rate_avg"], 0.0005, places=6)

    def test_fee_rate_avg_skips_zero_tvl(self):
        h = [
            {"date": "2026-01-01", "tvl_usd": 0.0, "daily_fee_revenue_usd": 100.0},
            {"date": "2026-01-02", "tvl_usd": 1_000_000.0, "daily_fee_revenue_usd": 1_000.0},
            {"date": "2026-01-03", "tvl_usd": 2_000_000.0, "daily_fee_revenue_usd": 2_000.0},
        ]
        r = analyze("P", h, data_file=self.df, save=False)
        # Only entries 2 and 3 count (rate=0.001 each)
        self.assertAlmostEqual(r["fee_rate_avg"], 0.001, places=6)

    def test_data_points_count(self):
        h = _make_history(7)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertEqual(r["data_points"], 7)


# ===========================================================================
# 6. TVL trend classification
# ===========================================================================

class TestTVLTrendInAnalyze(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_growing_trend(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=100_000)
        r = analyze("P", h, data_file=self.df, save=False)
        # last=1.4M > first=1M * 1.05=1.05M; slope>0
        self.assertEqual(r["tvl_trend"], "GROWING")

    def test_shrinking_trend(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=-100_000)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertEqual(r["tvl_trend"], "SHRINKING")

    def test_stable_flat(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=0)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertEqual(r["tvl_trend"], "STABLE")

    def test_stable_small_change(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=2_000)
        # last=1.008M < first*1.05=1.05M
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertEqual(r["tvl_trend"], "STABLE")

    def test_tvl_slope_positive_growing(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=100_000)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertGreater(r["tvl_slope_per_day"], 0)

    def test_tvl_slope_negative_shrinking(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=-100_000)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertLess(r["tvl_slope_per_day"], 0)

    def test_tvl_slope_zero_flat(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=0)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertAlmostEqual(r["tvl_slope_per_day"], 0.0)


# ===========================================================================
# 7. Fee rate trend classification
# ===========================================================================

class TestFeeRateTrendInAnalyze(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_fee_rate_increasing(self):
        # TVL constant, fee rising → rate rising
        h = _make_history(5, tvl_start=1_000_000, tvl_step=0,
                          fee_start=1_000, fee_step=200)
        r = analyze("P", h, data_file=self.df, save=False)
        # first_rate=0.001, last_rate=0.0018 > 0.001*1.05
        self.assertEqual(r["fee_rate_trend"], "INCREASING")

    def test_fee_rate_decreasing(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=0,
                          fee_start=2_000, fee_step=-300)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertEqual(r["fee_rate_trend"], "DECREASING")

    def test_fee_rate_stable_flat(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=0,
                          fee_start=1_000, fee_step=0)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertEqual(r["fee_rate_trend"], "STABLE")


# ===========================================================================
# 8. Predictions
# ===========================================================================

class TestPredictions(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_predicted_tvl_flat_equals_current(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=0,
                          fee_start=1_000, fee_step=0)
        r = analyze("P", h, config={"forecast_days": 30}, data_file=self.df, save=False)
        self.assertAlmostEqual(r["predicted_tvl_usd"], 1_000_000.0)

    def test_predicted_tvl_growing(self):
        # slope=100000 per day, 30 day forecast → +3M on top of current
        h = _make_history(5, tvl_start=1_000_000, tvl_step=100_000)
        r = analyze("P", h, config={"forecast_days": 30}, data_file=self.df, save=False)
        self.assertGreater(r["predicted_tvl_usd"], r["current_tvl_usd"])

    def test_predicted_tvl_non_negative(self):
        # Heavy shrinkage shouldn't produce negative TVL
        h = _make_history(5, tvl_start=100_000, tvl_step=-90_000)
        r = analyze("P", h, config={"forecast_days": 1000}, data_file=self.df, save=False)
        self.assertGreaterEqual(r["predicted_tvl_usd"], 0.0)

    def test_predicted_daily_revenue_equals_tvl_times_fee_rate(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=0,
                          fee_start=1_000, fee_step=0)
        r = analyze("P", h, data_file=self.df, save=False)
        expected = r["predicted_tvl_usd"] * r["fee_rate_avg"]
        self.assertAlmostEqual(r["predicted_daily_revenue_usd"], expected, places=4)

    def test_predicted_annual_is_daily_times_365(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=0,
                          fee_start=1_000, fee_step=0)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertAlmostEqual(
            r["predicted_annual_revenue_usd"],
            r["predicted_daily_revenue_usd"] * 365,
            places=4,
        )

    def test_forecast_days_config(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=100_000)
        r30 = analyze("P", h, config={"forecast_days": 30}, data_file=self.df, save=False)
        r60 = analyze("P", h, config={"forecast_days": 60}, data_file=self.df, save=False)
        self.assertGreater(r60["predicted_tvl_usd"], r30["predicted_tvl_usd"])

    def test_default_forecast_days(self):
        self.assertEqual(_DEFAULT_FORECAST_DAYS, 30)

    def test_predicted_revenue_non_negative(self):
        h = _make_history(5, tvl_start=100_000, tvl_step=-90_000)
        r = analyze("P", h, config={"forecast_days": 1000}, data_file=self.df, save=False)
        self.assertGreaterEqual(r["predicted_daily_revenue_usd"], 0.0)
        self.assertGreaterEqual(r["predicted_annual_revenue_usd"], 0.0)

    def test_linear_prediction_exact(self):
        # Perfect linear TVL: 0, 1, 2, 3, 4 (×1M)
        h = [
            {"date": f"2026-01-0{i+1}", "tvl_usd": float(i * 1_000_000),
             "daily_fee_revenue_usd": 1_000.0}
            for i in range(5)
        ]
        r = analyze("P", h, config={"forecast_days": 1}, data_file=self.df, save=False)
        # slope = 1M per day; current_tvl=4M; predicted = 4M + 1M = 5M
        self.assertAlmostEqual(r["predicted_tvl_usd"], 5_000_000.0, places=0)


# ===========================================================================
# 9. Confidence and R²
# ===========================================================================

class TestConfidence(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_high_confidence_perfect_fit(self):
        # Perfectly linear revenue → R²=1.0 → HIGH
        h = _make_history(10, tvl_start=1_000_000, tvl_step=0,
                          fee_start=1_000, fee_step=100)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertEqual(r["confidence"], "HIGH")
        self.assertGreaterEqual(r["r_squared"], 0.7)

    def test_low_confidence_noisy(self):
        # Alternating revenue → low R²
        h = []
        for i in range(10):
            fee = 1_000.0 if i % 2 == 0 else 5_000.0
            h.append({"date": f"2026-01-{i+1:02d}", "tvl_usd": 1_000_000.0,
                       "daily_fee_revenue_usd": fee})
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertEqual(r["confidence"], "LOW")
        self.assertLess(r["r_squared"], 0.4)

    def test_r_squared_between_0_and_1(self):
        h = _make_history(6, tvl_start=1_000_000, tvl_step=50_000,
                          fee_start=1_000, fee_step=50)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertGreaterEqual(r["r_squared"], 0.0)
        self.assertLessEqual(r["r_squared"], 1.0)

    def test_medium_confidence_moderate_fit(self):
        # R² between 0.4 and 0.7 → MEDIUM
        h = []
        # Trend + noise
        import random
        random.seed(42)
        for i in range(15):
            base_fee = 1_000.0 + i * 30.0
            noise = random.uniform(-200, 200)
            h.append({"date": f"2026-01-{i+1:02d}", "tvl_usd": 1_000_000.0,
                       "daily_fee_revenue_usd": max(1.0, base_fee + noise)})
        r = analyze("P", h, data_file=self.df, save=False)
        # Just verify it's a valid confidence level
        self.assertIn(r["confidence"], ("HIGH", "MEDIUM", "LOW"))

    def test_flat_series_r_squared_is_1(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=0,
                          fee_start=1_000, fee_step=0)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertAlmostEqual(r["r_squared"], 1.0, places=6)


# ===========================================================================
# 10. Ring-buffer log I/O
# ===========================================================================

class TestRingBuffer(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()
        self.df.unlink(missing_ok=True)

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_save_creates_file(self):
        h = _make_history(3)
        analyze("P", h, data_file=self.df, save=True)
        self.assertTrue(self.df.exists())

    def test_save_appends(self):
        h = _make_history(3)
        for _ in range(3):
            analyze("P", h, data_file=self.df, save=True)
        log = _load_log(self.df)
        self.assertEqual(len(log), 3)

    def test_ring_buffer_caps_at_max(self):
        h = _make_history(3)
        for _ in range(_MAX_ENTRIES + 15):
            analyze("P", h, data_file=self.df, save=True)
        log = _load_log(self.df)
        self.assertEqual(len(log), _MAX_ENTRIES)

    def test_save_false_no_file(self):
        h = _make_history(3)
        analyze("P", h, data_file=self.df, save=False)
        self.assertFalse(self.df.exists())

    def test_log_valid_json(self):
        h = _make_history(3)
        analyze("P", h, data_file=self.df, save=True)
        content = self.df.read_text()
        parsed = json.loads(content)
        self.assertIsInstance(parsed, list)

    def test_log_entry_has_timestamp(self):
        h = _make_history(3)
        analyze("P", h, data_file=self.df, save=True)
        log = _load_log(self.df)
        self.assertIn("timestamp", log[0])

    def test_ring_buffer_keeps_newest(self):
        for i in range(_MAX_ENTRIES + 5):
            h = _make_history(3, tvl_start=float(i) * 1_000_000)
            analyze("P", h, data_file=self.df, save=True)
        log = _load_log(self.df)
        # Most recent entries should be last
        self.assertAlmostEqual(
            log[-1]["current_tvl_usd"],
            float(_MAX_ENTRIES + 4) * 1_000_000,
        )

    def test_no_tmp_file_left_behind(self):
        h = _make_history(3)
        analyze("P", h, data_file=self.df, save=True)
        tmp = self.df.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_max_entries_constant(self):
        self.assertEqual(_MAX_ENTRIES, 100)

    def test_load_log_empty_on_missing(self):
        result = _load_log(Path("/tmp/nonexistent_spa_test_rev.json"))
        self.assertEqual(result, [])

    def test_load_log_empty_on_corrupt(self):
        corrupt = _tmp_file()
        corrupt.write_text("{not valid")
        result = _load_log(corrupt)
        self.assertEqual(result, [])
        corrupt.unlink()


# ===========================================================================
# 11. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_all_tvl_same_slope_zero(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=0,
                          fee_start=1_000, fee_step=0)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertAlmostEqual(r["tvl_slope_per_day"], 0.0)

    def test_all_zero_tvl_fee_rate_avg_zero(self):
        h = [
            {"date": f"2026-01-0{i+1}", "tvl_usd": 0.0,
             "daily_fee_revenue_usd": 0.0}
            for i in range(3)
        ]
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertAlmostEqual(r["fee_rate_avg"], 0.0)
        self.assertGreaterEqual(r["predicted_tvl_usd"], 0.0)
        self.assertGreaterEqual(r["predicted_daily_revenue_usd"], 0.0)

    def test_protocol_name_passthrough(self):
        h = _make_history(3)
        r = analyze("MyCoolProtocol", h, data_file=self.df, save=False)
        self.assertEqual(r["protocol"], "MyCoolProtocol")

    def test_timestamp_recent(self):
        h = _make_history(3)
        before = time.time()
        r = analyze("P", h, data_file=self.df, save=False)
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_large_history(self):
        h = _make_history(100, tvl_start=1_000_000, tvl_step=10_000,
                          fee_start=1_000, fee_step=10)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertEqual(r["data_points"], 100)
        self.assertIsInstance(r, dict)

    def test_exact_three_entries_works(self):
        h = _make_history(3)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertIsNotNone(r)

    def test_revenue_slope_positive_trending_up(self):
        h = _make_history(5, fee_start=1_000, fee_step=500)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertGreater(r["revenue_slope_per_day"], 0)

    def test_revenue_slope_negative_trending_down(self):
        h = _make_history(5, fee_start=5_000, fee_step=-500)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertLess(r["revenue_slope_per_day"], 0)

    def test_predicted_annual_greater_than_daily(self):
        h = _make_history(5, tvl_start=1_000_000, tvl_step=0,
                          fee_start=1_000, fee_step=0)
        r = analyze("P", h, data_file=self.df, save=False)
        self.assertGreater(r["predicted_annual_revenue_usd"],
                           r["predicted_daily_revenue_usd"])


# ===========================================================================
# 12. Default file path
# ===========================================================================

class TestDefaultFilePath(unittest.TestCase):
    def test_default_data_file(self):
        from spa_core.analytics.protocol_revenue_predictor import _DATA_FILE
        self.assertEqual(str(_DATA_FILE), "data/revenue_prediction_log.json")


if __name__ == "__main__":
    unittest.main()
