"""
Tests for MP-788: YieldTimingOptimizer
≥65 unittest tests — pure stdlib, no external deps.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# resolve project root so we can import spa_core
_HERE = os.path.dirname(__file__)
_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.yield_timing_optimizer import YieldTimingOptimizer, RING_BUFFER_CAP
from spa_core.utils.errors import SPAError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_history(apys):
    """Convert list of APY floats to [(ts, apy)] with ascending timestamps."""
    base = 1_700_000_000
    return [(base + i * 86400, a) for i, a in enumerate(apys)]


def _make_data(apys, current_apy, protocol="TestProto", hold=30):
    return {
        "protocol": protocol,
        "apy_history": _make_history(apys),
        "current_apy": current_apy,
        "hold_period_days": hold,
    }


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestYieldTimingOptimizerInit(unittest.TestCase):
    """Instantiation and attribute tests."""

    def test_init_default_log_path(self):
        opt = YieldTimingOptimizer()
        self.assertIn("yield_timing_log.json", opt.log_path)

    def test_init_custom_log_path(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            opt = YieldTimingOptimizer(log_path=path)
            self.assertEqual(opt.log_path, path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_result_none_before_optimize(self):
        opt = YieldTimingOptimizer()
        self.assertIsNone(opt._result)

    def test_get_last_result_none_before_optimize(self):
        opt = YieldTimingOptimizer()
        self.assertIsNone(opt.get_last_result())

    def test_get_entry_signal_raises_before_optimize(self):
        opt = YieldTimingOptimizer()
        with self.assertRaises(SPAError):
            opt.get_entry_signal()

    def test_get_timing_score_raises_before_optimize(self):
        opt = YieldTimingOptimizer()
        with self.assertRaises(SPAError):
            opt.get_timing_score()


class TestOptimizeReturnStructure(unittest.TestCase):
    """Shape and type of the optimize() return dict."""

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")
        self.opt = YieldTimingOptimizer(log_path=self.tmp)
        self.data = _make_data([3.0, 4.0, 5.0, 6.0, 7.0], current_apy=6.5)

    def tearDown(self):
        for p in [self.tmp, self.tmp + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def _result(self):
        return self.opt.optimize(self.data)

    def test_returns_dict(self):
        self.assertIsInstance(self._result(), dict)

    def test_protocol_key_present(self):
        self.assertIn("protocol", self._result())

    def test_current_apy_key_present(self):
        self.assertIn("current_apy", self._result())

    def test_hold_period_days_key_present(self):
        self.assertIn("hold_period_days", self._result())

    def test_apy_percentile_key_present(self):
        self.assertIn("apy_percentile", self._result())

    def test_timing_score_key_present(self):
        self.assertIn("timing_score", self._result())

    def test_expected_apy_next_30d_key_present(self):
        self.assertIn("expected_apy_next_30d", self._result())

    def test_entry_signal_key_present(self):
        self.assertIn("entry_signal", self._result())

    def test_historical_avg_key_present(self):
        self.assertIn("historical_avg", self._result())

    def test_historical_std_key_present(self):
        self.assertIn("historical_std", self._result())

    def test_historical_min_key_present(self):
        self.assertIn("historical_min", self._result())

    def test_historical_max_key_present(self):
        self.assertIn("historical_max", self._result())

    def test_history_count_key_present(self):
        self.assertIn("history_count", self._result())

    def test_timestamp_key_present(self):
        self.assertIn("timestamp", self._result())

    def test_protocol_value_correct(self):
        self.assertEqual(self._result()["protocol"], "TestProto")

    def test_current_apy_value_correct(self):
        self.assertAlmostEqual(self._result()["current_apy"], 6.5)

    def test_hold_period_days_default_30(self):
        d = _make_data([1, 2, 3], current_apy=2.5)
        del d["hold_period_days"]
        r = self.opt.optimize(d)
        self.assertEqual(r["hold_period_days"], 30)

    def test_hold_period_days_custom(self):
        d = _make_data([1, 2, 3], current_apy=2.5, hold=90)
        self.assertEqual(self.opt.optimize(d)["hold_period_days"], 90)

    def test_history_count_matches(self):
        r = self._result()
        self.assertEqual(r["history_count"], 5)

    def test_timestamp_positive(self):
        self.assertGreater(self._result()["timestamp"], 0)


class TestPercentileAndScore(unittest.TestCase):
    """Percentile computation and timing_score bounds."""

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")
        self.opt = YieldTimingOptimizer(log_path=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def test_percentile_zero_when_below_all(self):
        r = self.opt.optimize(_make_data([5, 6, 7, 8, 9], current_apy=1.0))
        self.assertAlmostEqual(r["apy_percentile"], 0.0)

    def test_percentile_100_when_above_all(self):
        r = self.opt.optimize(_make_data([1, 2, 3, 4, 5], current_apy=99.0))
        self.assertAlmostEqual(r["apy_percentile"], 100.0)

    def test_percentile_50_for_median(self):
        # 10 values; current = 5.5 → 5 values below → 50%
        apys = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        r = self.opt.optimize(_make_data(apys, current_apy=5.5))
        self.assertAlmostEqual(r["apy_percentile"], 50.0)

    def test_percentile_range_low(self):
        r = self.opt.optimize(_make_data([1, 2, 3], current_apy=0.0))
        self.assertGreaterEqual(r["apy_percentile"], 0.0)
        self.assertLessEqual(r["apy_percentile"], 100.0)

    def test_timing_score_equals_percentile_when_inbounds(self):
        r = self.opt.optimize(_make_data([3, 4, 5, 6, 7], current_apy=6.5))
        self.assertAlmostEqual(r["timing_score"], r["apy_percentile"])

    def test_timing_score_not_exceed_100(self):
        r = self.opt.optimize(_make_data([1, 2, 3], current_apy=999.0))
        self.assertLessEqual(r["timing_score"], 100.0)

    def test_timing_score_not_below_0(self):
        r = self.opt.optimize(_make_data([5, 6, 7], current_apy=-99.0))
        self.assertGreaterEqual(r["timing_score"], 0.0)

    def test_percentile_type_float(self):
        r = self.opt.optimize(_make_data([3, 5], current_apy=4.0))
        self.assertIsInstance(r["apy_percentile"], float)

    def test_timing_score_type_float(self):
        r = self.opt.optimize(_make_data([3, 5], current_apy=4.0))
        self.assertIsInstance(r["timing_score"], float)


class TestHistoricalStats(unittest.TestCase):
    """historical_avg, std, min, max correctness."""

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")
        self.opt = YieldTimingOptimizer(log_path=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def test_avg_correct(self):
        apys = [2.0, 4.0, 6.0]
        r = self.opt.optimize(_make_data(apys, current_apy=5.0))
        self.assertAlmostEqual(r["historical_avg"], 4.0, places=4)

    def test_min_correct(self):
        apys = [2.0, 4.0, 6.0]
        r = self.opt.optimize(_make_data(apys, current_apy=5.0))
        self.assertAlmostEqual(r["historical_min"], 2.0, places=4)

    def test_max_correct(self):
        apys = [2.0, 4.0, 6.0]
        r = self.opt.optimize(_make_data(apys, current_apy=5.0))
        self.assertAlmostEqual(r["historical_max"], 6.0, places=4)

    def test_std_zero_for_single_element(self):
        r = self.opt.optimize(_make_data([5.0], current_apy=5.0))
        self.assertAlmostEqual(r["historical_std"], 0.0)

    def test_std_positive_for_multiple_different(self):
        r = self.opt.optimize(_make_data([1.0, 5.0, 9.0], current_apy=5.0))
        self.assertGreater(r["historical_std"], 0.0)

    def test_std_zero_for_identical_values(self):
        r = self.opt.optimize(_make_data([4.0, 4.0, 4.0], current_apy=4.0))
        self.assertAlmostEqual(r["historical_std"], 0.0, places=6)

    def test_expected_apy_positive_for_positive_inputs(self):
        r = self.opt.optimize(_make_data([3.0, 4.0, 5.0], current_apy=4.5))
        self.assertGreater(r["expected_apy_next_30d"], 0.0)

    def test_expected_apy_type_float(self):
        r = self.opt.optimize(_make_data([3.0, 4.0], current_apy=3.5))
        self.assertIsInstance(r["expected_apy_next_30d"], float)


class TestEntrySignals(unittest.TestCase):
    """Entry signal thresholds."""

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")
        self.opt = YieldTimingOptimizer(log_path=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def _run(self, apys, current):
        return self.opt.optimize(_make_data(apys, current))["entry_signal"]

    def test_strong_buy_top_decile(self):
        # 100 values, current above 80th percentile
        apys = list(range(1, 101))
        sig = self._run(apys, current=90.5)
        self.assertEqual(sig, "STRONG_BUY")

    def test_buy_between_60_and_80(self):
        # 100 values, current at ~70th pct
        apys = list(range(1, 101))
        sig = self._run(apys, current=70.5)
        self.assertEqual(sig, "BUY")

    def test_hold_between_40_and_60(self):
        apys = list(range(1, 101))
        sig = self._run(apys, current=50.5)
        self.assertEqual(sig, "HOLD")

    def test_wait_below_40th(self):
        apys = list(range(1, 101))
        sig = self._run(apys, current=30.5)
        self.assertEqual(sig, "WAIT")

    def test_wait_for_lowest_apy(self):
        sig = self._run([5, 6, 7, 8, 9], current=1.0)
        self.assertEqual(sig, "WAIT")

    def test_strong_buy_above_all(self):
        sig = self._run([1, 2, 3, 4, 5], current=99.0)
        self.assertEqual(sig, "STRONG_BUY")

    def test_valid_signals_only(self):
        valid = {"STRONG_BUY", "BUY", "HOLD", "WAIT"}
        for current in [0.5, 3.5, 5.5, 7.5, 9.5]:
            sig = self._run([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], current)
            self.assertIn(sig, valid)

    def test_compute_signal_static_strong_buy(self):
        self.assertEqual(YieldTimingOptimizer._compute_signal(81.0), "STRONG_BUY")

    def test_compute_signal_static_buy(self):
        self.assertEqual(YieldTimingOptimizer._compute_signal(61.0), "BUY")

    def test_compute_signal_static_hold(self):
        self.assertEqual(YieldTimingOptimizer._compute_signal(41.0), "HOLD")

    def test_compute_signal_static_wait_at_40(self):
        self.assertEqual(YieldTimingOptimizer._compute_signal(40.0), "WAIT")

    def test_compute_signal_static_wait_zero(self):
        self.assertEqual(YieldTimingOptimizer._compute_signal(0.0), "WAIT")

    def test_get_entry_signal_after_optimize(self):
        self.opt.optimize(_make_data([1, 2, 3, 4, 5], current_apy=99.0))
        self.assertIsInstance(self.opt.get_entry_signal(), str)

    def test_get_timing_score_after_optimize(self):
        self.opt.optimize(_make_data([1, 2, 3], current_apy=2.0))
        self.assertIsInstance(self.opt.get_timing_score(), float)

    def test_get_last_result_not_none_after_optimize(self):
        self.opt.optimize(_make_data([1, 2, 3], current_apy=2.0))
        self.assertIsNotNone(self.opt.get_last_result())

    def test_consecutive_optimize_updates_result(self):
        self.opt.optimize(_make_data([1, 2, 3], current_apy=2.0))
        first_ts = self.opt._result["timestamp"]
        time.sleep(0.01)
        self.opt.optimize(_make_data([1, 2, 3, 4, 5], current_apy=4.0))
        self.assertNotEqual(self.opt._result["history_count"], 3)


class TestEdgeCases(unittest.TestCase):
    """Edge cases: single history, negative APY, empty."""

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")
        self.opt = YieldTimingOptimizer(log_path=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def test_empty_history_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.opt.optimize({"protocol": "X", "apy_history": [], "current_apy": 5.0})

    def test_missing_protocol_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.opt.optimize({"apy_history": [(0, 1.0)], "current_apy": 1.0})

    def test_missing_current_apy_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.opt.optimize({"protocol": "X", "apy_history": [(0, 1.0)]})

    def test_missing_apy_history_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.opt.optimize({"protocol": "X", "current_apy": 1.0})

    def test_single_element_history(self):
        r = self.opt.optimize(_make_data([5.0], current_apy=5.0))
        self.assertEqual(r["history_count"], 1)
        self.assertAlmostEqual(r["historical_std"], 0.0)

    def test_negative_apy_values(self):
        r = self.opt.optimize(_make_data([-2.0, -1.0, 0.0, 1.0], current_apy=-0.5))
        self.assertGreaterEqual(r["apy_percentile"], 0.0)
        self.assertLessEqual(r["apy_percentile"], 100.0)

    def test_two_element_history(self):
        r = self.opt.optimize(_make_data([3.0, 7.0], current_apy=5.0))
        self.assertEqual(r["history_count"], 2)
        self.assertAlmostEqual(r["historical_avg"], 5.0)

    def test_hold_period_days_1(self):
        r = self.opt.optimize(_make_data([3, 4, 5], current_apy=4.0, hold=1))
        self.assertIsNotNone(r["expected_apy_next_30d"])

    def test_hold_period_days_365(self):
        r = self.opt.optimize(_make_data([3, 4, 5], current_apy=4.0, hold=365))
        self.assertIsNotNone(r["expected_apy_next_30d"])

    def test_very_large_apy_clamped(self):
        r = self.opt.optimize(_make_data([1, 2, 3], current_apy=10_000.0))
        self.assertLessEqual(r["timing_score"], 100.0)

    def test_large_history_100_points(self):
        apys = [float(i) for i in range(1, 101)]
        r = self.opt.optimize(_make_data(apys, current_apy=85.0))
        self.assertEqual(r["history_count"], 100)


class TestRingBuffer(unittest.TestCase):
    """Log file ring-buffer and atomic write."""

    def setUp(self):
        fd, self.tmp = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.tmp)  # start fresh (file doesn't exist yet)
        self.opt = YieldTimingOptimizer(log_path=self.tmp)

    def tearDown(self):
        for p in [self.tmp, self.tmp + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def test_log_file_created(self):
        self.opt.optimize(_make_data([1, 2, 3], current_apy=2.0))
        self.assertTrue(os.path.exists(self.tmp))

    def test_log_file_valid_json(self):
        self.opt.optimize(_make_data([1, 2, 3], current_apy=2.0))
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_timestamp(self):
        self.opt.optimize(_make_data([1, 2, 3], current_apy=2.0))
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_entry_signal(self):
        self.opt.optimize(_make_data([1, 2, 3], current_apy=2.0))
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertIn("entry_signal", data[0])

    def test_ring_buffer_cap(self):
        for i in range(RING_BUFFER_CAP + 10):
            self.opt.optimize(_make_data([float(i), float(i + 1)], current_apy=float(i)))
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), RING_BUFFER_CAP)

    def test_tmp_file_cleaned_up(self):
        self.opt.optimize(_make_data([1, 2, 3], current_apy=2.0))
        self.assertFalse(os.path.exists(self.tmp + ".tmp"))

    def test_second_entry_appended(self):
        self.opt.optimize(_make_data([1, 2, 3], current_apy=2.0))
        self.opt.optimize(_make_data([4, 5, 6], current_apy=5.0))
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_corrupted_log_resets_gracefully(self):
        with open(self.tmp, "w") as f:
            f.write("NOT VALID JSON!!!!")
        # Should not raise; resets to empty list
        self.opt.optimize(_make_data([1, 2], current_apy=1.5))
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


if __name__ == "__main__":
    unittest.main()
