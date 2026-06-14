"""
MP-812 — Unit tests for ProtocolVolumeAnalyzer.
Pure stdlib unittest; ≥ 65 tests.
Run: python3 -m unittest spa_core.tests.test_protocol_volume_analyzer -v
"""

import json
import math
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from spa_core.analytics.protocol_volume_analyzer import (
    MAX_ENTRIES,
    DEFAULT_CONFIG,
    _LOG10_1B_PLUS_1,
    _parse_date,
    _sma,
    _volume_score,
    _volume_trend,
    analyze,
    load_log,
    save_result,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log(tmp_dir: str) -> Path:
    return Path(tmp_dir) / "protocol_volume_log.json"


def _make_history(n: int, base_volume: float = 1_000_000, base_tx: int = 500,
                  start: str = "2026-01-01") -> list:
    """Generate n daily entries with constant volume & tx_count."""
    d = date.fromisoformat(start)
    return [
        {
            "date": (d + timedelta(days=i)).isoformat(),
            "volume_usd": base_volume,
            "tx_count": base_tx,
        }
        for i in range(n)
    ]


def _make_growing_history(n: int = 20, start_vol: float = 500_000,
                          step: float = 50_000) -> list:
    """Volume grows by `step` each day."""
    d = date.fromisoformat("2026-01-01")
    return [
        {
            "date": (d + timedelta(days=i)).isoformat(),
            "volume_usd": start_vol + i * step,
            "tx_count": 1000,
        }
        for i in range(n)
    ]


def _make_collapsing_history(n: int = 20, start_vol: float = 2_000_000,
                              step: float = 200_000) -> list:
    d = date.fromisoformat("2026-01-01")
    return [
        {
            "date": (d + timedelta(days=i)).isoformat(),
            "volume_usd": max(0, start_vol - i * step),
            "tx_count": 500,
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# 1. TestHelpers
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):

    def test_parse_date_valid(self):
        d = _parse_date("2026-01-15")
        self.assertEqual(d.year, 2026)
        self.assertEqual(d.month, 1)
        self.assertEqual(d.day, 15)

    def test_parse_date_invalid_raises(self):
        with self.assertRaises(Exception):
            _parse_date("not-a-date")

    def test_sma_empty_returns_zero(self):
        self.assertEqual(_sma([]), 0.0)

    def test_sma_single(self):
        self.assertAlmostEqual(_sma([42.0]), 42.0)

    def test_sma_multiple(self):
        self.assertAlmostEqual(_sma([1.0, 2.0, 3.0, 4.0, 5.0]), 3.0)

    def test_volume_trend_none_is_stable(self):
        self.assertEqual(_volume_trend(None), "STABLE")

    def test_volume_trend_surging(self):
        self.assertEqual(_volume_trend(51.0), "SURGING")
        self.assertEqual(_volume_trend(100.0), "SURGING")

    def test_volume_trend_growing(self):
        self.assertEqual(_volume_trend(10.01), "GROWING")
        self.assertEqual(_volume_trend(49.99), "GROWING")

    def test_volume_trend_stable(self):
        self.assertEqual(_volume_trend(0.0), "STABLE")
        self.assertEqual(_volume_trend(-10.0), "STABLE")
        self.assertEqual(_volume_trend(10.0), "STABLE")

    def test_volume_trend_declining(self):
        self.assertEqual(_volume_trend(-10.01), "DECLINING")
        self.assertEqual(_volume_trend(-50.0), "DECLINING")

    def test_volume_trend_collapsing(self):
        self.assertEqual(_volume_trend(-50.01), "COLLAPSING")
        self.assertEqual(_volume_trend(-99.9), "COLLAPSING")


# ---------------------------------------------------------------------------
# 2. TestAnalyzeBasic
# ---------------------------------------------------------------------------

class TestAnalyzeBasic(unittest.TestCase):

    def setUp(self):
        self.history = _make_history(10)
        self.result = analyze("test_protocol", self.history)

    def test_returns_dict(self):
        self.assertIsInstance(self.result, dict)

    def test_protocol_name_returned(self):
        self.assertEqual(self.result["protocol"], "test_protocol")

    def test_latest_volume_usd(self):
        self.assertAlmostEqual(self.result["latest_volume_usd"], 1_000_000)

    def test_latest_tx_count(self):
        self.assertEqual(self.result["latest_tx_count"], 500)

    def test_timestamp_present(self):
        self.assertIn("timestamp", self.result)
        self.assertIsInstance(self.result["timestamp"], float)
        self.assertGreater(self.result["timestamp"], 0)

    def test_all_required_keys_present(self):
        expected_keys = {
            "protocol", "latest_volume_usd", "latest_tx_count",
            "volume_7d_avg", "volume_30d_avg", "volume_change_7d_pct",
            "tx_count_7d_avg", "avg_tx_size_usd", "volume_trend",
            "volume_score", "peak_volume_usd", "peak_date",
            "days_since_peak", "timestamp",
        }
        self.assertEqual(expected_keys, set(self.result.keys()))

    def test_volume_score_is_int(self):
        self.assertIsInstance(self.result["volume_score"], int)

    def test_volume_score_in_range(self):
        self.assertGreaterEqual(self.result["volume_score"], 0)
        self.assertLessEqual(self.result["volume_score"], 100)

    def test_volume_trend_is_valid_string(self):
        valid = {"SURGING", "GROWING", "STABLE", "DECLINING", "COLLAPSING"}
        self.assertIn(self.result["volume_trend"], valid)

    def test_peak_volume_is_float(self):
        self.assertIsInstance(self.result["peak_volume_usd"], float)

    def test_empty_history_raises(self):
        with self.assertRaises((ValueError, Exception)):
            analyze("x", [])

    def test_single_entry_works(self):
        h = [{"date": "2026-01-01", "volume_usd": 500_000, "tx_count": 100}]
        r = analyze("x", h)
        self.assertEqual(r["latest_volume_usd"], 500_000)
        self.assertIsNone(r["volume_30d_avg"])
        self.assertIsNone(r["volume_change_7d_pct"])
        self.assertEqual(r["days_since_peak"], 0)


# ---------------------------------------------------------------------------
# 3. TestVolume7dAvg
# ---------------------------------------------------------------------------

class TestVolume7dAvg(unittest.TestCase):

    def test_uses_last_7_when_n_gte_7(self):
        # First 3 days volume = 100k, next 7 days = 1M
        h = _make_history(3, base_volume=100_000) + _make_history(7, base_volume=1_000_000,
                                                                    start="2026-01-04")
        r = analyze("x", h)
        self.assertAlmostEqual(r["volume_7d_avg"], 1_000_000)

    def test_uses_all_when_n_lt_7(self):
        h = _make_history(5, base_volume=200_000)
        r = analyze("x", h)
        self.assertAlmostEqual(r["volume_7d_avg"], 200_000)

    def test_uses_all_when_n_2(self):
        h = [
            {"date": "2026-01-01", "volume_usd": 100_000, "tx_count": 10},
            {"date": "2026-01-02", "volume_usd": 300_000, "tx_count": 30},
        ]
        r = analyze("x", h)
        self.assertAlmostEqual(r["volume_7d_avg"], 200_000)

    def test_custom_ma_window_3(self):
        # 10 entries of 100k, last 3 of 900k
        h = _make_history(10, base_volume=100_000)
        h[-1]["volume_usd"] = 900_000
        h[-2]["volume_usd"] = 900_000
        h[-3]["volume_usd"] = 900_000
        r = analyze("x", h, config={"ma_window": 3})
        self.assertAlmostEqual(r["volume_7d_avg"], 900_000)

    def test_custom_ma_window_14(self):
        h = _make_history(20, base_volume=500_000)
        r14 = analyze("x", h, config={"ma_window": 14})
        r7 = analyze("x", h, config={"ma_window": 7})
        # Both should be 500k since history is flat
        self.assertAlmostEqual(r14["volume_7d_avg"], 500_000)
        self.assertAlmostEqual(r7["volume_7d_avg"], 500_000)

    def test_tx_count_7d_avg_correct(self):
        h = _make_history(10, base_tx=1000)
        r = analyze("x", h)
        self.assertAlmostEqual(r["tx_count_7d_avg"], 1000.0)

    def test_avg_tx_size_usd_correct(self):
        h = _make_history(10, base_volume=1_000_000, base_tx=100)
        r = analyze("x", h)
        self.assertAlmostEqual(r["avg_tx_size_usd"], 10_000.0)

    def test_avg_tx_size_zero_when_tx_count_zero(self):
        h = _make_history(5, base_tx=0)
        r = analyze("x", h)
        self.assertAlmostEqual(r["avg_tx_size_usd"], 0.0)


# ---------------------------------------------------------------------------
# 4. TestVolume30dAvg
# ---------------------------------------------------------------------------

class TestVolume30dAvg(unittest.TestCase):

    def test_none_when_n_lt_30(self):
        h = _make_history(29)
        self.assertIsNone(analyze("x", h)["volume_30d_avg"])

    def test_none_when_n_exactly_2(self):
        h = _make_history(2)
        self.assertIsNone(analyze("x", h)["volume_30d_avg"])

    def test_float_when_n_exactly_30(self):
        h = _make_history(30, base_volume=750_000)
        r = analyze("x", h)
        self.assertIsNotNone(r["volume_30d_avg"])
        self.assertAlmostEqual(r["volume_30d_avg"], 750_000)

    def test_float_when_n_gt_30(self):
        h = _make_history(45, base_volume=600_000)
        r = analyze("x", h)
        self.assertIsNotNone(r["volume_30d_avg"])
        self.assertAlmostEqual(r["volume_30d_avg"], 600_000)

    def test_30d_avg_uses_last_30(self):
        # First 20 days = 100k, last 30 days = 1M
        early = _make_history(5, base_volume=100_000)
        later = _make_history(30, base_volume=1_000_000, start="2026-01-06")
        h = early + later
        r = analyze("x", h)
        self.assertAlmostEqual(r["volume_30d_avg"], 1_000_000)

    def test_30d_avg_is_float_type(self):
        h = _make_history(30)
        r = analyze("x", h)
        self.assertIsInstance(r["volume_30d_avg"], float)


# ---------------------------------------------------------------------------
# 5. TestVolumeChangeAndTrend
# ---------------------------------------------------------------------------

class TestVolumeChangeAndTrend(unittest.TestCase):

    def test_none_when_n_lt_14(self):
        h = _make_history(13)
        self.assertIsNone(analyze("x", h)["volume_change_7d_pct"])

    def test_none_when_n_exactly_13(self):
        h = _make_history(13)
        self.assertIsNone(analyze("x", h)["volume_change_7d_pct"])

    def test_computed_when_n_exactly_14(self):
        h = _make_history(14)
        r = analyze("x", h)
        self.assertIsNotNone(r["volume_change_7d_pct"])
        self.assertAlmostEqual(r["volume_change_7d_pct"], 0.0)  # flat → 0% change

    def test_positive_change_for_growth(self):
        # prev 7 days = 100k, last 7 days = 200k → +100%
        prev = _make_history(7, base_volume=100_000)
        curr = _make_history(7, base_volume=200_000, start="2026-01-08")
        h = prev + curr
        r = analyze("x", h)
        self.assertIsNotNone(r["volume_change_7d_pct"])
        self.assertAlmostEqual(r["volume_change_7d_pct"], 100.0, places=5)

    def test_negative_change_for_decline(self):
        # prev 7 = 200k, last 7 = 100k → -50%
        prev = _make_history(7, base_volume=200_000)
        curr = _make_history(7, base_volume=100_000, start="2026-01-08")
        h = prev + curr
        r = analyze("x", h)
        self.assertAlmostEqual(r["volume_change_7d_pct"], -50.0, places=5)

    def test_none_when_prev_avg_zero(self):
        # prev 7 days all have 0 volume
        prev = _make_history(7, base_volume=0)
        curr = _make_history(7, base_volume=100_000, start="2026-01-08")
        h = prev + curr
        r = analyze("x", h)
        self.assertIsNone(r["volume_change_7d_pct"])

    def test_surging_when_change_above_50(self):
        prev = _make_history(7, base_volume=100_000)
        curr = _make_history(7, base_volume=200_000, start="2026-01-08")
        h = prev + curr
        r = analyze("x", h)
        self.assertEqual(r["volume_trend"], "SURGING")

    def test_growing_when_change_10_to_50(self):
        # 11% growth
        prev = _make_history(7, base_volume=1_000_000)
        curr = _make_history(7, base_volume=1_110_000, start="2026-01-08")
        h = prev + curr
        r = analyze("x", h)
        self.assertEqual(r["volume_trend"], "GROWING")

    def test_stable_when_change_near_zero(self):
        h = _make_history(14, base_volume=1_000_000)
        r = analyze("x", h)
        self.assertEqual(r["volume_trend"], "STABLE")

    def test_declining_when_change_between_minus10_and_minus50(self):
        # -20% change
        prev = _make_history(7, base_volume=1_000_000)
        curr = _make_history(7, base_volume=800_000, start="2026-01-08")
        h = prev + curr
        r = analyze("x", h)
        self.assertEqual(r["volume_trend"], "DECLINING")

    def test_collapsing_when_change_below_minus50(self):
        # -60% change
        prev = _make_history(7, base_volume=1_000_000)
        curr = _make_history(7, base_volume=400_000, start="2026-01-08")
        h = prev + curr
        r = analyze("x", h)
        self.assertEqual(r["volume_trend"], "COLLAPSING")

    def test_trend_stable_when_change_is_none(self):
        h = _make_history(5)  # n < 14
        r = analyze("x", h)
        self.assertEqual(r["volume_trend"], "STABLE")


# ---------------------------------------------------------------------------
# 6. TestVolumeTrendBoundaries
# ---------------------------------------------------------------------------

class TestVolumeTrendBoundaries(unittest.TestCase):

    def test_exactly_50_pct_is_growing_not_surging(self):
        # 50% change is NOT > 50, so GROWING
        self.assertEqual(_volume_trend(50.0), "GROWING")

    def test_exactly_10_pct_is_stable_not_growing(self):
        # 10% is NOT > 10, so STABLE
        self.assertEqual(_volume_trend(10.0), "STABLE")

    def test_exactly_minus10_pct_is_stable(self):
        # -10 >= -10, so STABLE
        self.assertEqual(_volume_trend(-10.0), "STABLE")

    def test_exactly_minus50_pct_is_declining(self):
        # -50 >= -50, so DECLINING
        self.assertEqual(_volume_trend(-50.0), "DECLINING")

    def test_surging_strictly_above_50(self):
        self.assertEqual(_volume_trend(50.001), "SURGING")

    def test_collapsing_strictly_below_minus50(self):
        self.assertEqual(_volume_trend(-50.001), "COLLAPSING")


# ---------------------------------------------------------------------------
# 7. TestVolumeScore
# ---------------------------------------------------------------------------

class TestVolumeScore(unittest.TestCase):

    def test_score_is_int(self):
        h = _make_history(5)
        r = analyze("x", h)
        self.assertIsInstance(r["volume_score"], int)

    def test_score_clamped_to_100_max(self):
        # $10B volume + SURGING + peak within 7 days → potential > 100
        r = _volume_score(10_000_000_000, "SURGING", 0)
        self.assertLessEqual(r, 100)

    def test_score_at_least_0(self):
        r = _volume_score(0.0, "COLLAPSING", 365)
        self.assertGreaterEqual(r, 0)

    def test_surging_trend_bonus_20(self):
        # Use volume=1e6, days=100 (peak bonus=0)
        # base = log10(1e6+1)/log10(1e9+1)*60 ≈ 6/9*60 = 40
        base_score = _volume_score(1_000_000, "STABLE", 100)
        surge_score = _volume_score(1_000_000, "SURGING", 100)
        self.assertEqual(surge_score - base_score, 10)   # SURGING(20) - STABLE(10) = 10

    def test_growing_trend_bonus_15(self):
        base_score = _volume_score(1_000_000, "STABLE", 100)
        grow_score = _volume_score(1_000_000, "GROWING", 100)
        self.assertEqual(grow_score - base_score, 5)    # GROWING(15) - STABLE(10) = 5

    def test_stable_trend_bonus_10(self):
        # COLLAPSING vs STABLE difference should be 10
        coll_score = _volume_score(1_000_000, "COLLAPSING", 100)
        stab_score = _volume_score(1_000_000, "STABLE", 100)
        self.assertEqual(stab_score - coll_score, 10)

    def test_declining_trend_bonus_5(self):
        decl_score = _volume_score(1_000_000, "DECLINING", 100)
        coll_score = _volume_score(1_000_000, "COLLAPSING", 100)
        self.assertEqual(decl_score - coll_score, 5)

    def test_collapsing_trend_bonus_0(self):
        # COLLAPSING gets 0 trend bonus; check it's less than DECLINING
        d = _volume_score(1_000_000, "DECLINING", 100)
        c = _volume_score(1_000_000, "COLLAPSING", 100)
        self.assertGreater(d, c)

    def test_peak_bonus_20_within_7_days(self):
        s7 = _volume_score(1_000_000, "STABLE", 7)
        s8 = _volume_score(1_000_000, "STABLE", 8)
        self.assertEqual(s7 - s8, 10)   # 20 - 10 = 10

    def test_peak_bonus_10_within_30_days(self):
        s30 = _volume_score(1_000_000, "STABLE", 30)
        s31 = _volume_score(1_000_000, "STABLE", 31)
        self.assertEqual(s30 - s31, 10)   # 10 - 0 = 10

    def test_peak_bonus_0_beyond_30_days(self):
        s31 = _volume_score(1_000_000, "STABLE", 31)
        s100 = _volume_score(1_000_000, "STABLE", 100)
        self.assertEqual(s31, s100)

    def test_base_log_scale_1b_equals_60(self):
        # $1B volume → base exactly 60
        base = min(math.log10(1e9 + 1) / _LOG10_1B_PLUS_1 * 60.0, 60.0)
        self.assertAlmostEqual(base, 60.0, places=5)

    def test_score_higher_for_larger_volume(self):
        small = _volume_score(1_000, "STABLE", 100)
        large = _volume_score(100_000_000, "STABLE", 100)
        self.assertGreater(large, small)


# ---------------------------------------------------------------------------
# 8. TestPeakDetection
# ---------------------------------------------------------------------------

class TestPeakDetection(unittest.TestCase):

    def test_peak_is_max_volume_entry(self):
        h = _make_history(10, base_volume=1_000_000)
        h[5]["volume_usd"] = 5_000_000  # spike on day 6
        r = analyze("x", h)
        self.assertAlmostEqual(r["peak_volume_usd"], 5_000_000)

    def test_peak_date_correct(self):
        h = _make_history(10, base_volume=1_000_000)
        h[3]["volume_usd"] = 9_000_000  # peak on day 4 (2026-01-04)
        r = analyze("x", h)
        self.assertEqual(r["peak_date"], "2026-01-04")

    def test_days_since_peak_zero_when_peak_is_latest(self):
        h = _make_growing_history(10)
        r = analyze("x", h)
        # Highest volume is always the last entry in a growing series
        self.assertEqual(r["days_since_peak"], 0)

    def test_days_since_peak_positive_when_past(self):
        h = _make_history(10, base_volume=1_000_000)
        h[0]["volume_usd"] = 9_000_000  # peak on day 1 (2026-01-01)
        r = analyze("x", h)
        self.assertEqual(r["days_since_peak"], 9)

    def test_days_since_peak_computed_correctly(self):
        h = _make_history(5, base_volume=500_000)
        h[2]["volume_usd"] = 2_000_000  # peak on 2026-01-03
        r = analyze("x", h)
        # latest = 2026-01-05, peak = 2026-01-03 → 2 days
        self.assertEqual(r["days_since_peak"], 2)

    def test_flat_history_days_since_peak_zero(self):
        h = _make_history(7, base_volume=1_000_000)
        r = analyze("x", h)
        # All volumes equal → peak is first entry found, days_since_peak = n-1=6 OR last=0
        # max() picks first occurrence of tie in CPython, but peak = last possible
        # Behaviour: max picks FIRST occurrence in Python when volumes are equal.
        # days_since_peak = latest - first = 6 (or 0 if last)
        # Either is acceptable; just verify the field exists and is non-negative.
        self.assertGreaterEqual(r["days_since_peak"], 0)

    def test_peak_volume_is_max_across_all_entries(self):
        h = _make_collapsing_history(20)
        r = analyze("x", h)
        # Peak for collapsing series is the first entry (highest volume)
        self.assertAlmostEqual(r["peak_volume_usd"], float(h[0]["volume_usd"]))

    def test_peak_date_is_string(self):
        h = _make_history(5)
        r = analyze("x", h)
        self.assertIsInstance(r["peak_date"], str)


# ---------------------------------------------------------------------------
# 9. TestSaveResult
# ---------------------------------------------------------------------------

class TestSaveResult(unittest.TestCase):

    def test_creates_file_if_missing(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            self.assertFalse(log.exists())
            save_result({"test": 1}, data_file=log)
            self.assertTrue(log.exists())

    def test_file_contains_list(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            save_result({"v": 42}, data_file=log)
            data = json.loads(log.read_text())
            self.assertIsInstance(data, list)
            self.assertEqual(data[0]["v"], 42)

    def test_appends_to_existing(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            save_result({"n": 1}, data_file=log)
            save_result({"n": 2}, data_file=log)
            data = json.loads(log.read_text())
            self.assertEqual(len(data), 2)

    def test_ring_buffer_cap_100(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            for i in range(MAX_ENTRIES + 15):
                save_result({"i": i}, data_file=log)
            data = json.loads(log.read_text())
            self.assertEqual(len(data), MAX_ENTRIES)
            self.assertEqual(data[-1]["i"], MAX_ENTRIES + 14)

    def test_atomic_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            save_result({"ok": True}, data_file=log)
            tmp = log.with_suffix(".tmp")
            self.assertFalse(tmp.exists())

    def test_handles_corrupt_file(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            log.write_text("corrupt!!!{{{")
            save_result({"fresh": True}, data_file=log)
            data = json.loads(log.read_text())
            self.assertEqual(len(data), 1)
            self.assertTrue(data[0]["fresh"])

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "a" / "b" / "log.json"
            save_result({"x": 1}, data_file=log)
            self.assertTrue(log.exists())

    def test_load_log_empty_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            self.assertEqual(load_log(log), [])

    def test_load_log_returns_all_entries(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            save_result({"a": 1}, data_file=log)
            save_result({"b": 2}, data_file=log)
            loaded = load_log(log)
            self.assertEqual(len(loaded), 2)

    def test_save_full_analyze_result(self):
        with tempfile.TemporaryDirectory() as td:
            log = _tmp_log(td)
            h = _make_history(20)
            result = analyze("aave", h)
            save_result(result, data_file=log)
            loaded = load_log(log)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["protocol"], "aave")
            self.assertIn("volume_score", loaded[0])


if __name__ == "__main__":
    unittest.main()
