"""
Tests for MP-790: GasPriceForecaster
≥65 unittest cases covering forecasting, regime classification, optimal window,
tx cost, EMA, percentile, rolling averages, log persistence, edge cases.
"""

import json
import math
import os
import tempfile
import time
import unittest

from spa_core.analytics.gas_price_forecaster import (
    GasPriceForecaster,
    GasForecastResult,
    GasRegime,
    TxUrgency,
    EMA_ALPHA,
    EMA_LOOKBACK,
    GAS_LIMIT_SIMPLE_TRANSFER,
    LOG_CAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_history(n: int, base_gwei: float = 30.0, spread: float = 10.0,
                  now: float = None) -> list:
    """Return n (timestamp, gwei) pairs over last 24h."""
    now = now or time.time()
    result = []
    for i in range(n):
        ts = now - 86400 + (i / max(n - 1, 1)) * 86400
        gwei = base_gwei + (spread * (i % 2) - spread / 2)
        result.append((ts, round(gwei, 2)))
    return result


def _make_gas_data(urgency="FLEXIBLE", current_gwei=25.0, n_history=50,
                   base_gwei=30.0) -> dict:
    now = time.time()
    return {
        "gas_history": _make_history(n_history, base_gwei=base_gwei, now=now),
        "current_gwei": current_gwei,
        "tx_urgency": urgency,
    }


class TestGasPriceForecasterBasic(unittest.TestCase):

    def setUp(self):
        self.forecaster = GasPriceForecaster()

    # --- Test 1-5: result fields exist and have correct types ---

    def test_01_result_is_gas_forecast_result(self):
        r = self.forecaster.forecast(_make_gas_data())
        self.assertIsInstance(r, GasForecastResult)

    def test_02_timestamp_is_recent(self):
        r = self.forecaster.forecast(_make_gas_data())
        self.assertAlmostEqual(r.timestamp, time.time(), delta=5)

    def test_03_current_gwei_preserved(self):
        r = self.forecaster.forecast(_make_gas_data(current_gwei=42.5))
        self.assertAlmostEqual(r.current_gwei, 42.5)

    def test_04_eth_price_preserved(self):
        r = self.forecaster.forecast(_make_gas_data(), eth_price_usd=2500.0)
        self.assertEqual(r.eth_price_usd, 2500.0)

    def test_05_urgency_preserved(self):
        r = self.forecaster.forecast(_make_gas_data(urgency="IMMEDIATE"))
        self.assertEqual(r.urgency, "IMMEDIATE")

    # --- Test 6-10: urgency parsing ---

    def test_06_urgency_immediate(self):
        r = self.forecaster.forecast(_make_gas_data(urgency="IMMEDIATE"))
        self.assertEqual(r.urgency, TxUrgency.IMMEDIATE.value)

    def test_07_urgency_flexible(self):
        r = self.forecaster.forecast(_make_gas_data(urgency="FLEXIBLE"))
        self.assertEqual(r.urgency, TxUrgency.FLEXIBLE.value)

    def test_08_urgency_patient(self):
        r = self.forecaster.forecast(_make_gas_data(urgency="PATIENT"))
        self.assertEqual(r.urgency, TxUrgency.PATIENT.value)

    def test_09_urgency_unknown_defaults_flexible(self):
        data = _make_gas_data()
        data["tx_urgency"] = "UNKNOWN_VALUE"
        r = self.forecaster.forecast(data)
        self.assertEqual(r.urgency, TxUrgency.FLEXIBLE.value)

    def test_10_urgency_lowercase_accepted(self):
        data = _make_gas_data()
        data["tx_urgency"] = "immediate"
        r = self.forecaster.forecast(data)
        self.assertEqual(r.urgency, "IMMEDIATE")

    # --- Test 11-15: optimal_window ---

    def test_11_optimal_window_immediate_is_now(self):
        r = self.forecaster.forecast(_make_gas_data(urgency="IMMEDIATE"))
        self.assertEqual(r.optimal_window, "now")

    def test_12_optimal_window_flexible_nonempty(self):
        r = self.forecaster.forecast(_make_gas_data(urgency="FLEXIBLE"))
        self.assertIsInstance(r.optimal_window, str)
        self.assertTrue(len(r.optimal_window) > 0)

    def test_13_optimal_window_patient_nonempty(self):
        r = self.forecaster.forecast(_make_gas_data(urgency="PATIENT"))
        self.assertIsInstance(r.optimal_window, str)
        self.assertTrue(len(r.optimal_window) > 0)

    def test_14_optimal_window_flexible_empty_history(self):
        data = {"gas_history": [], "current_gwei": 20.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertEqual(r.optimal_window, "next 4h")

    def test_15_optimal_window_patient_empty_history(self):
        data = {"gas_history": [], "current_gwei": 20.0, "tx_urgency": "PATIENT"}
        r = self.forecaster.forecast(data)
        self.assertEqual(r.optimal_window, "next 24h")

    # --- Test 16-20: gas_regime values ---

    def test_16_regime_cheap_when_very_low_percentile(self):
        # current_gwei far below all history → percentile ~0 → CHEAP
        data = _make_gas_data(current_gwei=1.0, base_gwei=50.0)
        r = self.forecaster.forecast(data)
        self.assertEqual(r.gas_regime, GasRegime.CHEAP.value)

    def test_17_regime_very_expensive_when_very_high(self):
        data = _make_gas_data(current_gwei=200.0, base_gwei=20.0)
        r = self.forecaster.forecast(data)
        self.assertEqual(r.gas_regime, GasRegime.VERY_EXPENSIVE.value)

    def test_18_regime_normal_at_median(self):
        # Build monotonically increasing history so current at 50th pct
        now = time.time()
        hist = [(now - 86400 + i * 300, float(i)) for i in range(100)]
        data = {"gas_history": hist, "current_gwei": 50.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertIn(r.gas_regime, [GasRegime.NORMAL.value, GasRegime.CHEAP.value,
                                      GasRegime.EXPENSIVE.value])

    def test_19_regime_expensive_75th_pct(self):
        # current at 75th percentile
        now = time.time()
        hist = [(now - 86400 + i * 300, float(i)) for i in range(100)]
        data = {"gas_history": hist, "current_gwei": 74.5, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertEqual(r.gas_regime, GasRegime.EXPENSIVE.value)

    def test_20_regime_enum_values_valid(self):
        valid = {e.value for e in GasRegime}
        for urgency in ("IMMEDIATE", "FLEXIBLE", "PATIENT"):
            for gwei in (5.0, 25.0, 60.0, 150.0):
                data = _make_gas_data(urgency=urgency, current_gwei=gwei)
                r = self.forecaster.forecast(data)
                self.assertIn(r.gas_regime, valid)

    # --- Test 21-25: rolling averages ---

    def test_21_rolling_avg_24h_approximately_correct(self):
        now = time.time()
        hist = [(now - i * 300, 30.0) for i in range(288)]  # all 30 gwei
        data = {"gas_history": hist, "current_gwei": 30.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertAlmostEqual(r.rolling_avg_24h, 30.0, places=1)

    def test_22_rolling_avg_1h_uses_only_recent(self):
        now = time.time()
        # Older points: all > 1h ago (anchored at now-7200 to now-4500 — safely outside window)
        hist = [(now - 7200 + i * 300, 50.0) for i in range(4)]   # now-7200..now-6300
        # Recent points: within last hour
        hist += [(now - 1800 + i * 60, 10.0) for i in range(10)]
        data = {"gas_history": hist, "current_gwei": 10.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertLess(r.rolling_avg_1h, 15.0)

    def test_23_rolling_avg_none_when_no_recent_data(self):
        # History is all >24h old
        now = time.time()
        hist = [(now - 90000, 30.0)]
        data = {"gas_history": hist, "current_gwei": 30.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertIsNone(r.rolling_avg_24h)

    def test_24_rolling_avg_1h_none_when_no_1h_data(self):
        now = time.time()
        hist = [(now - 7200, 30.0)]  # 2h old only
        data = {"gas_history": hist, "current_gwei": 30.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertIsNone(r.rolling_avg_1h)

    def test_25_rolling_avg_both_present_with_fresh_data(self):
        data = _make_gas_data(n_history=100)
        r = self.forecaster.forecast(data)
        self.assertIsNotNone(r.rolling_avg_1h)
        self.assertIsNotNone(r.rolling_avg_24h)

    # --- Test 26-30: EMA forecast ---

    def test_26_forecast_1h_is_float(self):
        r = self.forecaster.forecast(_make_gas_data())
        self.assertIsInstance(r.forecast_1h, float)

    def test_27_forecast_1h_equals_current_when_no_history(self):
        data = {"gas_history": [], "current_gwei": 33.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertAlmostEqual(r.forecast_1h, 33.0)

    def test_28_forecast_1h_ema_formula_single_point(self):
        now = time.time()
        hist = [(now - 300, 40.0)]
        data = {"gas_history": hist, "current_gwei": 30.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        expected = EMA_ALPHA * 30.0 + (1 - EMA_ALPHA) * 40.0
        self.assertAlmostEqual(r.forecast_1h, expected, places=2)

    def test_29_forecast_1h_moves_toward_current(self):
        now = time.time()
        hist = [(now - i * 300, 50.0) for i in range(10)]
        data_low = {"gas_history": hist, "current_gwei": 10.0, "tx_urgency": "FLEXIBLE"}
        data_high = {"gas_history": hist, "current_gwei": 100.0, "tx_urgency": "FLEXIBLE"}
        r_low = self.forecaster.forecast(data_low)
        r_high = self.forecaster.forecast(data_high)
        self.assertLess(r_low.forecast_1h, r_high.forecast_1h)

    def test_30_forecast_1h_stable_constant_series(self):
        now = time.time()
        hist = [(now - i * 300, 25.0) for i in range(20)]
        data = {"gas_history": hist, "current_gwei": 25.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertAlmostEqual(r.forecast_1h, 25.0, places=2)

    # --- Test 31-35: percentile ---

    def test_31_percentile_zero_when_lowest(self):
        now = time.time()
        hist = [(now - i * 300, float(i + 1)) for i in range(100)]
        data = {"gas_history": hist, "current_gwei": 0.5, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertAlmostEqual(r.percentile_current, 0.0)

    def test_32_percentile_100_when_highest(self):
        now = time.time()
        hist = [(now - i * 300, float(i + 1)) for i in range(100)]
        data = {"gas_history": hist, "current_gwei": 200.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertAlmostEqual(r.percentile_current, 100.0)

    def test_33_percentile_50_at_median(self):
        now = time.time()
        hist = [(now - i * 300, float(i)) for i in range(100)]
        data = {"gas_history": hist, "current_gwei": 49.5, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertGreater(r.percentile_current, 40.0)
        self.assertLess(r.percentile_current, 60.0)

    def test_34_percentile_defaults_50_no_history(self):
        data = {"gas_history": [], "current_gwei": 20.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertAlmostEqual(r.percentile_current, 50.0)

    def test_35_percentile_in_range(self):
        data = _make_gas_data(current_gwei=25.0)
        r = self.forecaster.forecast(data)
        self.assertGreaterEqual(r.percentile_current, 0.0)
        self.assertLessEqual(r.percentile_current, 100.0)

    # --- Test 36-40: tx cost calculation ---

    def test_36_tx_cost_usd_formula(self):
        gwei = 30.0
        eth_price = 3000.0
        expected = gwei * GAS_LIMIT_SIMPLE_TRANSFER / 1e9 * eth_price
        data = _make_gas_data(current_gwei=gwei)
        r = self.forecaster.forecast(data, eth_price_usd=eth_price)
        self.assertAlmostEqual(r.estimated_tx_cost_usd, expected, places=4)

    def test_37_tx_cost_scales_with_gwei(self):
        data_low = _make_gas_data(current_gwei=10.0)
        data_high = _make_gas_data(current_gwei=100.0)
        r_low = self.forecaster.forecast(data_low, eth_price_usd=3000.0)
        r_high = self.forecaster.forecast(data_high, eth_price_usd=3000.0)
        self.assertAlmostEqual(r_high.estimated_tx_cost_usd / r_low.estimated_tx_cost_usd, 10.0, places=1)

    def test_38_tx_cost_scales_with_eth_price(self):
        data = _make_gas_data(current_gwei=30.0)
        r1 = self.forecaster.forecast(data, eth_price_usd=1500.0)
        r2 = self.forecaster.forecast(data, eth_price_usd=3000.0)
        self.assertAlmostEqual(r2.estimated_tx_cost_usd / r1.estimated_tx_cost_usd, 2.0, places=1)

    def test_39_tx_cost_zero_gwei(self):
        data = {"gas_history": [], "current_gwei": 0.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data, eth_price_usd=3000.0)
        self.assertAlmostEqual(r.estimated_tx_cost_usd, 0.0)

    def test_40_tx_cost_positive(self):
        data = _make_gas_data(current_gwei=25.0)
        r = self.forecaster.forecast(data, eth_price_usd=3000.0)
        self.assertGreater(r.estimated_tx_cost_usd, 0.0)

    # --- Test 41-45: data_points_used ---

    def test_41_data_points_count_correct(self):
        data = _make_gas_data(n_history=77)
        r = self.forecaster.forecast(data)
        self.assertEqual(r.data_points_used, 77)

    def test_42_data_points_zero_no_history(self):
        data = {"gas_history": [], "current_gwei": 20.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertEqual(r.data_points_used, 0)

    def test_43_data_points_matches_list_length(self):
        n = 33
        data = _make_gas_data(n_history=n)
        r = self.forecaster.forecast(data)
        self.assertEqual(r.data_points_used, n)

    # --- Test 44-48: to_dict ---

    def test_44_to_dict_returns_dict(self):
        r = self.forecaster.forecast(_make_gas_data())
        self.assertIsInstance(r.to_dict(), dict)

    def test_45_to_dict_has_required_keys(self):
        r = self.forecaster.forecast(_make_gas_data())
        d = r.to_dict()
        for key in ("timestamp", "current_gwei", "gas_regime", "forecast_1h",
                    "optimal_window", "estimated_tx_cost_usd", "urgency"):
            self.assertIn(key, d)

    def test_46_to_dict_json_serialisable(self):
        r = self.forecaster.forecast(_make_gas_data())
        s = json.dumps(r.to_dict())
        self.assertIsInstance(s, str)

    # --- Test 47-52: get_gas_regime / get_optimal_tx_window ---

    def test_47_get_gas_regime_none_before_forecast(self):
        f = GasPriceForecaster()
        self.assertIsNone(f.get_gas_regime())

    def test_48_get_gas_regime_after_forecast(self):
        self.forecaster.forecast(_make_gas_data())
        self.assertIsNotNone(self.forecaster.get_gas_regime())

    def test_49_get_optimal_window_none_before_forecast(self):
        f = GasPriceForecaster()
        self.assertIsNone(f.get_optimal_tx_window())

    def test_50_get_optimal_window_after_forecast(self):
        self.forecaster.forecast(_make_gas_data())
        self.assertIsNotNone(self.forecaster.get_optimal_tx_window())

    def test_51_get_gas_regime_matches_result(self):
        r = self.forecaster.forecast(_make_gas_data())
        self.assertEqual(self.forecaster.get_gas_regime(), r.gas_regime)

    def test_52_get_optimal_window_matches_result(self):
        r = self.forecaster.forecast(_make_gas_data())
        self.assertEqual(self.forecaster.get_optimal_tx_window(), r.optimal_window)

    # --- Test 53-60: log persistence ---

    def test_53_append_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gas_log.json")
            f = GasPriceForecaster(log_path=path)
            r = f.forecast(_make_gas_data())
            f.append_log(r)
            self.assertTrue(os.path.exists(path))

    def test_54_append_log_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gas_log.json")
            f = GasPriceForecaster(log_path=path)
            r = f.forecast(_make_gas_data())
            f.append_log(r)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)

    def test_55_append_log_single_entry(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gas_log.json")
            f = GasPriceForecaster(log_path=path)
            r = f.forecast(_make_gas_data())
            f.append_log(r)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_56_append_log_accumulates(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gas_log.json")
            f = GasPriceForecaster(log_path=path)
            for _ in range(5):
                r = f.forecast(_make_gas_data())
                f.append_log(r)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 5)

    def test_57_log_capped_at_100(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gas_log.json")
            f = GasPriceForecaster(log_path=path)
            for _ in range(LOG_CAP + 10):
                r = f.forecast(_make_gas_data())
                f.append_log(r)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), LOG_CAP)

    def test_58_log_entry_has_gas_regime(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gas_log.json")
            f = GasPriceForecaster(log_path=path)
            r = f.forecast(_make_gas_data())
            f.append_log(r)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIn("gas_regime", data[0])

    def test_59_log_missing_dir_created(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "deep", "gas_log.json")
            f = GasPriceForecaster(log_path=path)
            r = f.forecast(_make_gas_data())
            f.append_log(r)
            self.assertTrue(os.path.exists(path))

    def test_60_log_overwrites_corrupt_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gas_log.json")
            with open(path, "w") as fh:
                fh.write("CORRUPT{{")
            f = GasPriceForecaster(log_path=path)
            r = f.forecast(_make_gas_data())
            f.append_log(r)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    # --- Test 61-65: edge cases ---

    def test_61_no_history_full_run(self):
        data = {"gas_history": [], "current_gwei": 15.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data, eth_price_usd=2000.0)
        self.assertIsInstance(r, GasForecastResult)
        self.assertEqual(r.current_gwei, 15.0)

    def test_62_single_history_point(self):
        now = time.time()
        data = {
            "gas_history": [(now - 1800, 30.0)],
            "current_gwei": 25.0,
            "tx_urgency": "FLEXIBLE",
        }
        r = self.forecaster.forecast(data)
        self.assertIsInstance(r, GasForecastResult)

    def test_63_very_large_gwei(self):
        data = _make_gas_data(current_gwei=10000.0)
        r = self.forecaster.forecast(data, eth_price_usd=5000.0)
        self.assertGreater(r.estimated_tx_cost_usd, 0)
        self.assertEqual(r.gas_regime, GasRegime.VERY_EXPENSIVE.value)

    def test_64_forecast_result_roundtrip_json(self):
        r = self.forecaster.forecast(_make_gas_data())
        d = r.to_dict()
        s = json.dumps(d)
        d2 = json.loads(s)
        self.assertEqual(d["gas_regime"], d2["gas_regime"])
        self.assertEqual(d["urgency"], d2["urgency"])

    def test_65_multiple_forecasts_independent(self):
        f = GasPriceForecaster()
        r1 = f.forecast(_make_gas_data(current_gwei=10.0))
        r2 = f.forecast(_make_gas_data(current_gwei=100.0))
        self.assertNotEqual(r1.current_gwei, r2.current_gwei)
        self.assertEqual(f.get_gas_regime(), r2.gas_regime)

    # --- Bonus test 66-68 ---

    def test_66_gas_regime_boundary_20th(self):
        # At exactly 20th percentile boundary → NORMAL
        now = time.time()
        hist = [(now - i * 300, float(i)) for i in range(100)]
        data = {"gas_history": hist, "current_gwei": 20.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertIn(r.gas_regime, [GasRegime.CHEAP.value, GasRegime.NORMAL.value])

    def test_67_gas_regime_boundary_70th(self):
        now = time.time()
        hist = [(now - i * 300, float(i)) for i in range(100)]
        data = {"gas_history": hist, "current_gwei": 70.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertIn(r.gas_regime, [GasRegime.EXPENSIVE.value, GasRegime.NORMAL.value])

    def test_68_gas_regime_boundary_90th(self):
        now = time.time()
        hist = [(now - i * 300, float(i)) for i in range(100)]
        data = {"gas_history": hist, "current_gwei": 91.0, "tx_urgency": "FLEXIBLE"}
        r = self.forecaster.forecast(data)
        self.assertEqual(r.gas_regime, GasRegime.VERY_EXPENSIVE.value)


if __name__ == "__main__":
    unittest.main()
