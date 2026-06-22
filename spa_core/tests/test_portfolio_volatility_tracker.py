"""
Tests for MP-639: PortfolioVolatilityTracker
Target: ≥55 tests
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Ensure spa_core package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.portfolio_volatility_tracker import (
    MAX_ENTRIES,
    RING_BUFFER_SIZE,
    PortfolioVolatilityTracker,
    VolatilitySnapshot,
)


def make_tracker(tmp_dir: str) -> PortfolioVolatilityTracker:
    return PortfolioVolatilityTracker(data_file=Path(tmp_dir) / "vol.json")


def tracker_with_readings(tmp_dir: str, readings: list) -> PortfolioVolatilityTracker:
    t = make_tracker(tmp_dir)
    for r in readings:
        t.add_reading(r)
    return t


# ===========================================================================
# 1. _stdev edge cases
# ===========================================================================

class TestStdev(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.t = make_tracker(self.tmp)

    def test_empty_list_returns_zero(self):
        self.assertEqual(self.t._stdev([]), 0.0)

    def test_single_value_returns_zero(self):
        self.assertEqual(self.t._stdev([0.05]), 0.0)

    def test_two_equal_values_returns_zero(self):
        self.assertEqual(self.t._stdev([0.05, 0.05]), 0.0)

    def test_two_values_known_result(self):
        # sample stdev([1,3]) = sqrt(2)
        result = self.t._stdev([1.0, 3.0])
        self.assertAlmostEqual(result, math.sqrt(2), places=10)

    def test_three_values_known_result(self):
        # [2,4,6]: mean=4, var=(4+0+4)/2=4, stdev=2
        self.assertAlmostEqual(self.t._stdev([2.0, 4.0, 6.0]), 2.0, places=10)

    def test_uniform_large_list_returns_zero(self):
        # floating-point cancellation may leave a tiny epsilon; treat as zero
        self.assertAlmostEqual(self.t._stdev([0.1] * 30), 0.0, places=12)

    def test_stdev_positive_for_varying_values(self):
        self.assertGreater(self.t._stdev([0.03, 0.07, 0.05, 0.09]), 0.0)

    def test_stdev_non_negative(self):
        self.assertGreaterEqual(self.t._stdev([0.01, 0.02, 0.03]), 0.0)

    def test_stdev_order_independent(self):
        vals = [0.01, 0.05, 0.03, 0.07, 0.02]
        self.assertAlmostEqual(
            self.t._stdev(vals),
            self.t._stdev(list(reversed(vals))),
            places=12,
        )


# ===========================================================================
# 2. _classify_regime
# ===========================================================================

class TestClassifyRegime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.t = make_tracker(self.tmp)

    def test_zero_vol_is_stable(self):
        self.assertEqual(self.t._classify_regime(0.0), "STABLE")

    def test_just_below_005_is_stable(self):
        self.assertEqual(self.t._classify_regime(0.004999), "STABLE")

    def test_exactly_005_is_moderate(self):
        self.assertEqual(self.t._classify_regime(0.005), "MODERATE")

    def test_010_is_moderate(self):
        self.assertEqual(self.t._classify_regime(0.010), "MODERATE")

    def test_just_below_015_is_moderate(self):
        self.assertEqual(self.t._classify_regime(0.01499), "MODERATE")

    def test_exactly_015_is_high(self):
        self.assertEqual(self.t._classify_regime(0.015), "HIGH")

    def test_025_is_high(self):
        self.assertEqual(self.t._classify_regime(0.025), "HIGH")

    def test_just_below_030_is_high(self):
        self.assertEqual(self.t._classify_regime(0.02999), "HIGH")

    def test_exactly_030_is_extreme(self):
        self.assertEqual(self.t._classify_regime(0.030), "EXTREME")

    def test_high_vol_is_extreme(self):
        self.assertEqual(self.t._classify_regime(0.1), "EXTREME")

    def test_regime_returns_string(self):
        self.assertIsInstance(self.t._classify_regime(0.01), str)


# ===========================================================================
# 3. _classify_trend
# ===========================================================================

class TestClassifyTrend(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.t = make_tracker(self.tmp)

    def test_zero_vol30_returns_stable(self):
        self.assertEqual(self.t._classify_trend(0.01, 0.0), "STABLE")

    def test_ratio_below_08_is_improving(self):
        # 7d=0.004, 30d=0.01 → ratio=0.4 < 0.8
        self.assertEqual(self.t._classify_trend(0.004, 0.01), "IMPROVING")

    def test_ratio_exactly_08_is_stable(self):
        # 7d=0.008, 30d=0.01 → ratio=0.8 → STABLE (not < 0.8)
        self.assertEqual(self.t._classify_trend(0.008, 0.01), "STABLE")

    def test_ratio_between_08_and_125_is_stable(self):
        self.assertEqual(self.t._classify_trend(0.01, 0.01), "STABLE")

    def test_ratio_above_125_is_worsening(self):
        # 7d=0.02, 30d=0.01 → ratio=2.0 > 1.25
        self.assertEqual(self.t._classify_trend(0.02, 0.01), "WORSENING")

    def test_equal_vols_is_stable(self):
        self.assertEqual(self.t._classify_trend(0.005, 0.005), "STABLE")

    def test_trend_returns_string(self):
        self.assertIsInstance(self.t._classify_trend(0.01, 0.02), str)


# ===========================================================================
# 4. add_reading and ring-buffer capping
# ===========================================================================

class TestAddReading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_add_single_reading(self):
        t = make_tracker(self.tmp)
        t.add_reading(0.05)
        self.assertEqual(t.history_length(), 1)

    def test_add_multiple_readings(self):
        t = make_tracker(self.tmp)
        for _ in range(10):
            t.add_reading(0.05)
        self.assertEqual(t.history_length(), 10)

    def test_ring_buffer_caps_at_size(self):
        t = make_tracker(self.tmp)
        for i in range(RING_BUFFER_SIZE + 20):
            t.add_reading(float(i) * 0.001)
        self.assertEqual(t.history_length(), RING_BUFFER_SIZE)

    def test_ring_buffer_keeps_last_readings(self):
        t = make_tracker(self.tmp)
        for i in range(RING_BUFFER_SIZE + 5):
            t.add_reading(float(i))
        self.assertEqual(t._history[-1], float(RING_BUFFER_SIZE + 4))

    def test_ring_buffer_drops_oldest(self):
        t = make_tracker(self.tmp)
        for i in range(RING_BUFFER_SIZE + 10):
            t.add_reading(float(i))
        self.assertEqual(t._history[0], 10.0)

    def test_clear_history(self):
        t = make_tracker(self.tmp)
        t.add_reading(0.05)
        t.clear_history()
        self.assertEqual(t.history_length(), 0)


# ===========================================================================
# 5. compute_snapshot
# ===========================================================================

class TestComputeSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_empty_history_gives_zero_vols(self):
        t = make_tracker(self.tmp)
        snap = t.compute_snapshot()
        self.assertEqual(snap.vol_7d, 0.0)
        self.assertEqual(snap.vol_30d, 0.0)
        self.assertEqual(snap.vol_90d, 0.0)

    def test_single_reading_gives_zero_vols(self):
        t = tracker_with_readings(self.tmp, [0.05])
        snap = t.compute_snapshot()
        self.assertEqual(snap.vol_7d, 0.0)
        self.assertEqual(snap.vol_30d, 0.0)

    def test_two_readings_gives_nonzero_vol(self):
        t = tracker_with_readings(self.tmp, [0.04, 0.06])
        snap = t.compute_snapshot()
        self.assertGreater(snap.vol_7d, 0.0)

    def test_snapshot_timestamp_recent(self):
        t = make_tracker(self.tmp)
        snap = t.compute_snapshot()
        self.assertAlmostEqual(snap.timestamp, time.time(), delta=5)

    def test_snapshot_apy_values_matches_history(self):
        readings = [0.03, 0.04, 0.05, 0.06, 0.07]
        t = tracker_with_readings(self.tmp, readings)
        snap = t.compute_snapshot()
        self.assertEqual(snap.apy_values, readings)

    def test_vol_7d_uses_only_last_7(self):
        """vol_7d should be computed from the last 7 readings only."""
        t = make_tracker(self.tmp)
        stable = [0.05] * 83
        volatile = [0.03, 0.07, 0.02, 0.09, 0.04, 0.08, 0.01]
        for r in stable + volatile:
            t.add_reading(r)
        snap = t.compute_snapshot()
        expected_7d = round(t._stdev(volatile), 6)
        self.assertAlmostEqual(snap.vol_7d, expected_7d, places=6)

    def test_vol_30d_uses_last_30(self):
        readings = [float(i) * 0.001 for i in range(50)]
        t = tracker_with_readings(self.tmp, readings)
        snap = t.compute_snapshot()
        expected = round(t._stdev(readings[-30:]), 6)
        self.assertAlmostEqual(snap.vol_30d, expected, places=6)

    def test_vol_90d_uses_all_readings(self):
        readings = [float(i) * 0.001 for i in range(40)]
        t = tracker_with_readings(self.tmp, readings)
        snap = t.compute_snapshot()
        expected = round(t._stdev(readings), 6)
        self.assertAlmostEqual(snap.vol_90d, expected, places=6)

    def test_mean_apy_correct(self):
        t = tracker_with_readings(self.tmp, [0.04, 0.06, 0.05])
        snap = t.compute_snapshot()
        self.assertAlmostEqual(snap.mean_apy, round(0.05, 6), places=6)

    def test_cv_zero_when_mean_too_small(self):
        t = tracker_with_readings(self.tmp, [0.0001, 0.0002])
        snap = t.compute_snapshot()
        self.assertEqual(snap.cv, 0.0)

    def test_cv_non_negative_for_normal_apy(self):
        t = tracker_with_readings(self.tmp, [0.04, 0.06, 0.05, 0.07])
        snap = t.compute_snapshot()
        self.assertGreaterEqual(snap.cv, 0.0)

    def test_regime_field_valid(self):
        t = tracker_with_readings(self.tmp, [0.05] * 10)
        snap = t.compute_snapshot()
        self.assertIn(snap.regime, ("STABLE", "MODERATE", "HIGH", "EXTREME"))

    def test_trend_field_valid(self):
        t = tracker_with_readings(self.tmp, [0.05] * 10)
        snap = t.compute_snapshot()
        self.assertIn(snap.trend, ("IMPROVING", "STABLE", "WORSENING"))

    def test_get_current_regime_returns_string(self):
        t = tracker_with_readings(self.tmp, [0.05] * 5)
        self.assertIsInstance(t.get_current_regime(), str)


# ===========================================================================
# 6. save_snapshot and persistence
# ===========================================================================

class TestSaveSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _make_snap(self, **kwargs) -> VolatilitySnapshot:
        defaults = dict(
            timestamp=time.time(),
            apy_values=[0.05],
            vol_7d=0.001,
            vol_30d=0.002,
            vol_90d=0.003,
            regime="STABLE",
            trend="STABLE",
            mean_apy=0.05,
            cv=0.02,
        )
        defaults.update(kwargs)
        return VolatilitySnapshot(**defaults)

    def test_save_creates_file(self):
        t = make_tracker(self.tmp)
        t.save_snapshot(self._make_snap())
        self.assertTrue((Path(self.tmp) / "vol.json").exists())

    def test_save_writes_valid_json(self):
        t = make_tracker(self.tmp)
        t.save_snapshot(self._make_snap())
        data = json.loads((Path(self.tmp) / "vol.json").read_text())
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_save_appends_second_entry(self):
        t = make_tracker(self.tmp)
        t.save_snapshot(self._make_snap())
        t.save_snapshot(self._make_snap())
        data = json.loads((Path(self.tmp) / "vol.json").read_text())
        self.assertEqual(len(data), 2)

    def test_ring_buffer_caps_at_max_entries(self):
        t = make_tracker(self.tmp)
        for _ in range(MAX_ENTRIES + 5):
            t.save_snapshot(self._make_snap())
        data = json.loads((Path(self.tmp) / "vol.json").read_text())
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_drops_oldest_entries(self):
        t = make_tracker(self.tmp)
        for i in range(MAX_ENTRIES + 3):
            t.save_snapshot(self._make_snap(vol_7d=float(i) * 0.001))
        data = json.loads((Path(self.tmp) / "vol.json").read_text())
        self.assertAlmostEqual(data[0]["vol_7d"], round(3 * 0.001, 6), places=9)

    def test_atomic_write_no_tmp_left(self):
        t = make_tracker(self.tmp)
        t.save_snapshot(self._make_snap())
        self.assertFalse((Path(self.tmp) / "vol.tmp").exists())

    def test_save_stores_correct_fields(self):
        t = make_tracker(self.tmp)
        snap = self._make_snap(regime="HIGH", trend="WORSENING", mean_apy=0.08, cv=0.1)
        t.save_snapshot(snap)
        entry = json.loads((Path(self.tmp) / "vol.json").read_text())[0]
        self.assertEqual(entry["regime"], "HIGH")
        self.assertEqual(entry["trend"], "WORSENING")
        self.assertAlmostEqual(entry["mean_apy"], 0.08, places=9)
        self.assertAlmostEqual(entry["cv"], 0.1, places=9)

    def test_save_stores_apy_values_count_not_list(self):
        t = make_tracker(self.tmp)
        snap = self._make_snap(apy_values=[0.04, 0.05, 0.06])
        t.save_snapshot(snap)
        entry = json.loads((Path(self.tmp) / "vol.json").read_text())[0]
        self.assertEqual(entry["apy_values_count"], 3)
        self.assertNotIn("apy_values", entry)


# ===========================================================================
# 7. load_history
# ===========================================================================

class TestLoadHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_load_missing_file_returns_empty_list(self):
        t = make_tracker(self.tmp)
        self.assertEqual(t.load_history(), [])

    def test_load_corrupt_file_returns_empty_list(self):
        f = Path(self.tmp) / "vol.json"
        f.write_text("not valid json!!!")
        t = PortfolioVolatilityTracker(data_file=f)
        self.assertEqual(t.load_history(), [])

    def test_load_returns_saved_entries(self):
        t = make_tracker(self.tmp)
        snap = VolatilitySnapshot(
            timestamp=1.0, apy_values=[0.05], vol_7d=0.001, vol_30d=0.002,
            vol_90d=0.003, regime="STABLE", trend="STABLE", mean_apy=0.05, cv=0.02
        )
        t.save_snapshot(snap)
        history = t.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["regime"], "STABLE")


# ===========================================================================
# 8. Full scenario
# ===========================================================================

class TestFullScenario(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_40_readings_regime_and_mean(self):
        """40 readings with small noise → STABLE or MODERATE regime."""
        import random
        random.seed(42)
        t = make_tracker(self.tmp)
        for _ in range(40):
            t.add_reading(0.05 + random.uniform(-0.008, 0.008))
        snap = t.compute_snapshot()
        self.assertIn(snap.regime, ("STABLE", "MODERATE"))
        self.assertGreater(snap.mean_apy, 0.04)
        self.assertLess(snap.mean_apy, 0.06)

    def test_40_readings_save_and_load(self):
        t = make_tracker(self.tmp)
        for i in range(40):
            t.add_reading(0.04 + (i % 5) * 0.01)
        snap = t.compute_snapshot()
        t.save_snapshot(snap)
        history = t.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["apy_values_count"], 40)

    def test_worsening_trend_detected(self):
        t = make_tracker(self.tmp)
        for _ in range(23):
            t.add_reading(0.05)
        for v in [0.02, 0.09, 0.01, 0.10, 0.03, 0.11, 0.005]:
            t.add_reading(v)
        snap = t.compute_snapshot()
        self.assertEqual(snap.trend, "WORSENING")

    def test_improving_trend_detected(self):
        t = make_tracker(self.tmp)
        for i in range(23):
            t.add_reading(0.03 + (i % 2) * 0.04)
        for _ in range(7):
            t.add_reading(0.05)
        snap = t.compute_snapshot()
        self.assertEqual(snap.trend, "IMPROVING")

    def test_regime_extreme_with_high_variance(self):
        t = make_tracker(self.tmp)
        for r in [0.01, 0.10, 0.01, 0.10, 0.01, 0.10, 0.01]:
            t.add_reading(r)
        snap = t.compute_snapshot()
        self.assertEqual(snap.regime, "EXTREME")

    def test_vol_7d_from_last_7_not_all(self):
        t = make_tracker(self.tmp)
        for _ in range(83):
            t.add_reading(0.05)
        volatile_7 = [0.02, 0.08, 0.03, 0.09, 0.01, 0.10, 0.04]
        for v in volatile_7:
            t.add_reading(v)
        snap = t.compute_snapshot()
        expected_7d = round(t._stdev(volatile_7), 6)
        self.assertAlmostEqual(snap.vol_7d, expected_7d, places=6)


if __name__ == "__main__":
    unittest.main()
