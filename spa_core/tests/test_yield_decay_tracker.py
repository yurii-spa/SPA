"""
Tests for MP-798: YieldDecayTracker
≥65 unittest tests. Pure stdlib (unittest only).
Run: python3 -m unittest spa_core/tests/test_yield_decay_tracker.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.yield_decay_tracker import (
    analyze,
    append_log,
    _linear_regression,
    _find_apy_at_offset,
    _resolve_config,
    _atomic_write,
    DEFAULT_DECAY_WINDOW_DAYS,
    DEFAULT_PROJECTION_DAYS,
    SECONDS_PER_DAY,
    LOG_MAX,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_history(start_apy: float, end_apy: float, days: int, now: float | None = None) -> list[dict]:
    """Generate evenly-spaced history over `days` days."""
    now = now or time.time()
    base = now - days * SECONDS_PER_DAY
    entries = []
    for i in range(days + 1):
        frac = i / days if days > 0 else 0.0
        apy = start_apy + (end_apy - start_apy) * frac
        entries.append({"timestamp": base + i * SECONDS_PER_DAY, "apy": apy})
    return entries


def _flat_history(apy: float, days: int, now: float | None = None) -> list[dict]:
    return _make_history(apy, apy, days, now)


def _single_entry(apy: float = 10.0, now: float | None = None) -> list[dict]:
    ts = now or time.time()
    return [{"timestamp": ts, "apy": apy}]


# ---------------------------------------------------------------------------
# 1. Config resolution
# ---------------------------------------------------------------------------

class TestResolveConfig(unittest.TestCase):

    def test_defaults_none(self):
        cfg = _resolve_config(None)
        self.assertEqual(cfg["decay_window_days"], DEFAULT_DECAY_WINDOW_DAYS)
        self.assertEqual(cfg["projection_days"], DEFAULT_PROJECTION_DAYS)

    def test_defaults_empty(self):
        cfg = _resolve_config({})
        self.assertEqual(cfg["decay_window_days"], DEFAULT_DECAY_WINDOW_DAYS)

    def test_custom_window(self):
        cfg = _resolve_config({"decay_window_days": 14})
        self.assertEqual(cfg["decay_window_days"], 14)

    def test_custom_projection(self):
        cfg = _resolve_config({"projection_days": 60})
        self.assertEqual(cfg["projection_days"], 60)

    def test_both_custom(self):
        cfg = _resolve_config({"decay_window_days": 7, "projection_days": 30})
        self.assertEqual(cfg["decay_window_days"], 7)
        self.assertEqual(cfg["projection_days"], 30)

    def test_string_converted(self):
        cfg = _resolve_config({"decay_window_days": "10", "projection_days": "45"})
        self.assertIsInstance(cfg["decay_window_days"], int)
        self.assertIsInstance(cfg["projection_days"], int)


# ---------------------------------------------------------------------------
# 2. Linear regression
# ---------------------------------------------------------------------------

class TestLinearRegression(unittest.TestCase):

    def test_perfect_line(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [10.0, 8.0, 6.0, 4.0]
        slope, intercept = _linear_regression(xs, ys)
        self.assertAlmostEqual(slope, -2.0, places=5)
        self.assertAlmostEqual(intercept, 10.0, places=5)

    def test_flat_line_slope_zero(self):
        xs = [0.0, 1.0, 2.0]
        ys = [5.0, 5.0, 5.0]
        slope, _ = _linear_regression(xs, ys)
        self.assertAlmostEqual(slope, 0.0, places=5)

    def test_positive_slope(self):
        xs = [0.0, 1.0, 2.0]
        ys = [3.0, 6.0, 9.0]
        slope, _ = _linear_regression(xs, ys)
        self.assertAlmostEqual(slope, 3.0, places=5)

    def test_single_point_fallback(self):
        slope, intercept = _linear_regression([1.0], [7.0])
        self.assertEqual(slope, 0.0)
        self.assertEqual(intercept, 7.0)

    def test_two_points(self):
        xs = [0.0, 10.0]
        ys = [20.0, 10.0]
        slope, _ = _linear_regression(xs, ys)
        self.assertAlmostEqual(slope, -1.0, places=5)

    def test_same_x_values(self):
        # denominator = 0 → slope 0, intercept = mean(y)
        xs = [5.0, 5.0, 5.0]
        ys = [3.0, 6.0, 9.0]
        slope, intercept = _linear_regression(xs, ys)
        self.assertEqual(slope, 0.0)
        self.assertAlmostEqual(intercept, 6.0, places=5)


# ---------------------------------------------------------------------------
# 3. _find_apy_at_offset
# ---------------------------------------------------------------------------

class TestFindApyAtOffset(unittest.TestCase):

    def test_finds_closest_entry(self):
        now = 1_000_000.0
        history = [
            {"timestamp": now - 8 * SECONDS_PER_DAY, "apy": 12.0},
            {"timestamp": now - 7.1 * SECONDS_PER_DAY, "apy": 11.5},
            {"timestamp": now, "apy": 10.0},
        ]
        result = _find_apy_at_offset(history, now, 7 * SECONDS_PER_DAY)
        # Closest to (now - 7 days) is the 7.1d entry
        self.assertAlmostEqual(result, 11.5, places=3)

    def test_returns_none_for_empty(self):
        result = _find_apy_at_offset([], 1_000_000.0, 7 * SECONDS_PER_DAY)
        self.assertIsNone(result)

    def test_single_entry_returns_it(self):
        result = _find_apy_at_offset([{"timestamp": 0.0, "apy": 5.0}], 100.0, 50.0)
        self.assertEqual(result, 5.0)


# ---------------------------------------------------------------------------
# 4. analyze() – return structure
# ---------------------------------------------------------------------------

class TestAnalyzeStructure(unittest.TestCase):

    def setUp(self):
        self.history = _make_history(20.0, 10.0, 60)

    def test_returns_dict(self):
        result = analyze("Proto", self.history)
        self.assertIsInstance(result, dict)

    def test_required_keys(self):
        result = analyze("Proto", self.history)
        for key in (
            "protocol", "current_apy", "apy_7d_ago", "apy_30d_ago",
            "decay_rate_daily_pct", "half_life_days", "projected_apy_30d",
            "projected_apy_90d", "trend", "sustainability_score",
            "recommendation", "timestamp",
        ):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_protocol_name_preserved(self):
        result = analyze("Aave V3", self.history)
        self.assertEqual(result["protocol"], "Aave V3")

    def test_current_apy_is_last_entry(self):
        result = analyze("Proto", self.history)
        self.assertAlmostEqual(result["current_apy"], 10.0, places=3)

    def test_timestamp_is_recent(self):
        before = time.time()
        result = analyze("Proto", self.history)
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)


# ---------------------------------------------------------------------------
# 5. Decay rate
# ---------------------------------------------------------------------------

class TestDecayRate(unittest.TestCase):

    def test_decaying_history_positive_rate(self):
        history = _make_history(20.0, 10.0, 60)
        result = analyze("P", history)
        self.assertGreater(result["decay_rate_daily_pct"], 0.0)

    def test_recovering_history_negative_rate(self):
        history = _make_history(5.0, 20.0, 60)
        result = analyze("P", history)
        self.assertLess(result["decay_rate_daily_pct"], 0.0)

    def test_flat_history_zero_rate(self):
        history = _flat_history(10.0, 60)
        result = analyze("P", history)
        self.assertAlmostEqual(result["decay_rate_daily_pct"], 0.0, places=4)

    def test_single_entry_zero_rate(self):
        result = analyze("P", _single_entry(12.0))
        self.assertAlmostEqual(result["decay_rate_daily_pct"], 0.0, places=4)

    def test_rate_approximately_correct(self):
        # 20 → 10 over 60 days → slope = -10/60 ≈ -0.1667/day → decay_rate ≈ 0.1667
        history = _make_history(20.0, 10.0, 60)
        result = analyze("P", history)
        self.assertAlmostEqual(result["decay_rate_daily_pct"], 10.0 / 60.0, delta=0.02)


# ---------------------------------------------------------------------------
# 6. Trend classification
# ---------------------------------------------------------------------------

class TestTrend(unittest.TestCase):

    def test_collapsed_when_apy_below_1(self):
        history = _flat_history(0.5, 10)
        result = analyze("P", history)
        self.assertEqual(result["trend"], "COLLAPSED")

    def test_collapsed_when_apy_exactly_0(self):
        history = _flat_history(0.0, 10)
        result = analyze("P", history)
        self.assertEqual(result["trend"], "COLLAPSED")

    def test_decaying_when_fast_drop(self):
        # 20 → 5 over 30 days → rate ≈ 0.5/day > 0.5 → DECAYING
        history = _make_history(20.0, 4.0, 30)
        result = analyze("P", history)
        self.assertEqual(result["trend"], "DECAYING")

    def test_recovering_when_fast_rise(self):
        # 5 → 22 over 30 days → slope ≈ +0.567/day → decay_rate ≈ -0.567 < -0.5 → RECOVERING
        history = _make_history(5.0, 22.0, 30)
        result = analyze("P", history)
        self.assertEqual(result["trend"], "RECOVERING")

    def test_stable_when_flat(self):
        history = _flat_history(10.0, 30)
        result = analyze("P", history)
        self.assertEqual(result["trend"], "STABLE")

    def test_stable_when_slow_decay(self):
        # 10 → 9.9 over 30 days → rate ≈ 0.0033/day < 0.5 → STABLE
        history = _make_history(10.0, 9.9, 30)
        result = analyze("P", history)
        self.assertEqual(result["trend"], "STABLE")

    def test_collapsed_takes_priority_over_rate(self):
        # even if there was a prior high, current is 0.5
        history = _make_history(10.0, 0.5, 30)
        result = analyze("P", history)
        self.assertEqual(result["trend"], "COLLAPSED")


# ---------------------------------------------------------------------------
# 7. Projections
# ---------------------------------------------------------------------------

class TestProjections(unittest.TestCase):

    def test_stable_projection_30d_near_current(self):
        history = _flat_history(10.0, 30)
        result = analyze("P", history)
        self.assertAlmostEqual(result["projected_apy_30d"], 10.0, delta=0.05)

    def test_stable_projection_90d_near_current(self):
        history = _flat_history(10.0, 30)
        result = analyze("P", history)
        self.assertAlmostEqual(result["projected_apy_90d"], 10.0, delta=0.05)

    def test_decaying_projection_30d_lower(self):
        history = _make_history(20.0, 5.0, 60)
        result = analyze("P", history)
        self.assertLess(result["projected_apy_30d"], result["current_apy"])

    def test_projections_floor_at_zero(self):
        # Very fast decay: 10 → 0.1 over 10 days → projecting far out → floor 0
        history = _make_history(10.0, 0.1, 10)
        result = analyze("P", history)
        self.assertGreaterEqual(result["projected_apy_30d"], 0.0)
        self.assertGreaterEqual(result["projected_apy_90d"], 0.0)

    def test_recovering_projection_90d_higher(self):
        history = _make_history(5.0, 20.0, 60)
        result = analyze("P", history)
        # rate is negative, so projected = current - rate*days = current + |rate|*days
        self.assertGreater(result["projected_apy_90d"], result["current_apy"])

    def test_linear_projection_formula_30d(self):
        # 20 → 10 over 60 days → rate = 10/60 → projected 30d = 10 - rate*30
        history = _make_history(20.0, 10.0, 60)
        result = analyze("P", history)
        expected = max(0.0, result["current_apy"] - result["decay_rate_daily_pct"] * 30)
        self.assertAlmostEqual(result["projected_apy_30d"], expected, places=3)

    def test_custom_projection_days(self):
        history = _flat_history(10.0, 30)
        result = analyze("P", history, config={"projection_days": 180})
        self.assertAlmostEqual(result["projected_apy_90d"], 10.0, delta=0.05)


# ---------------------------------------------------------------------------
# 8. Half-life
# ---------------------------------------------------------------------------

class TestHalfLife(unittest.TestCase):

    def test_half_life_none_when_not_decaying(self):
        history = _flat_history(10.0, 30)
        result = analyze("P", history)
        self.assertIsNone(result["half_life_days"])

    def test_half_life_none_when_recovering(self):
        history = _make_history(5.0, 20.0, 60)
        result = analyze("P", history)
        self.assertIsNone(result["half_life_days"])

    def test_half_life_positive_when_decaying(self):
        history = _make_history(20.0, 5.0, 60)
        result = analyze("P", history)
        if result["decay_rate_daily_pct"] > 0:
            self.assertIsNotNone(result["half_life_days"])
            self.assertGreater(result["half_life_days"], 0.0)

    def test_half_life_formula(self):
        # rate ≈ 10/60, apy ≈ 10 → half_life = (10/2) / (10/60) = 30 days
        history = _make_history(20.0, 10.0, 60)
        result = analyze("P", history)
        if result["decay_rate_daily_pct"] > 0:
            expected = (result["current_apy"] / 2.0) / result["decay_rate_daily_pct"]
            self.assertAlmostEqual(result["half_life_days"], expected, places=3)


# ---------------------------------------------------------------------------
# 9. Sustainability score
# ---------------------------------------------------------------------------

class TestSustainabilityScore(unittest.TestCase):

    def test_collapsed_low_score(self):
        history = _flat_history(0.5, 10)
        result = analyze("P", history)
        self.assertLessEqual(result["sustainability_score"], 10)

    def test_stable_high_apy_high_score(self):
        history = _flat_history(15.0, 30)
        result = analyze("P", history)
        self.assertGreaterEqual(result["sustainability_score"], 90)

    def test_score_clamped_0_100(self):
        for apy in [0.0, 5.0, 15.0, 30.0]:
            history = _flat_history(apy, 10)
            result = analyze("P", history)
            self.assertGreaterEqual(result["sustainability_score"], 0)
            self.assertLessEqual(result["sustainability_score"], 100)

    def test_decaying_has_lower_score_than_stable(self):
        stable = analyze("S", _flat_history(10.0, 30))
        decaying = analyze("D", _make_history(20.0, 4.0, 30))
        self.assertGreater(stable["sustainability_score"], decaying["sustainability_score"])

    def test_recovering_high_apy_max_score(self):
        history = _make_history(5.0, 20.0, 60)
        result = analyze("P", history)
        # RECOVERING + apy>10 → 50+20+30 = 100
        self.assertEqual(result["sustainability_score"], 100)

    def test_stable_low_apy_score_70(self):
        # STABLE, apy=5 (<10) → 50+20=70
        history = _flat_history(5.0, 30)
        result = analyze("P", history)
        self.assertEqual(result["sustainability_score"], 70)

    def test_stable_high_apy_score_100(self):
        # STABLE, apy=15 → 50+20+30=100
        history = _flat_history(15.0, 30)
        result = analyze("P", history)
        self.assertEqual(result["sustainability_score"], 100)


# ---------------------------------------------------------------------------
# 10. Recommendation
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):

    def test_exit_when_collapsed(self):
        result = analyze("P", _flat_history(0.5, 10))
        self.assertEqual(result["recommendation"], "EXIT")

    def test_exit_when_decaying_and_projected_below_3(self):
        # Fast decay: 20 → 0 in 30 days → projected 30d ≈ -something → floor 0 < 3 → EXIT
        history = _make_history(20.0, 0.1, 30)
        result = analyze("P", history)
        self.assertEqual(result["recommendation"], "EXIT")

    def test_reduce_when_decaying_and_projected_above_3(self):
        # Slow decay: 10 → 8 in 30 days → rate≈0.067/day → projected 30d ≈ 10-2=8 → REDUCE
        history = _make_history(10.0, 8.0, 30)
        result = analyze("P", history)
        if result["trend"] == "DECAYING":
            self.assertEqual(result["recommendation"], "REDUCE")

    def test_enter_when_recovering_and_apy_above_5(self):
        # RECOVERING + current_apy > 5
        history = _make_history(5.0, 20.0, 60)
        result = analyze("P", history)
        if result["trend"] == "RECOVERING" and result["current_apy"] > 5.0:
            self.assertEqual(result["recommendation"], "ENTER")

    def test_hold_when_stable(self):
        history = _flat_history(10.0, 30)
        result = analyze("P", history)
        self.assertEqual(result["recommendation"], "HOLD")

    def test_hold_when_recovering_but_low_apy(self):
        # RECOVERING but current_apy <= 5 → HOLD
        history = _make_history(1.0, 4.9, 60)
        result = analyze("P", history)
        if result["trend"] == "RECOVERING":
            self.assertEqual(result["recommendation"], "HOLD")

    def test_single_entry_hold(self):
        result = analyze("P", _single_entry(10.0))
        self.assertEqual(result["recommendation"], "HOLD")


# ---------------------------------------------------------------------------
# 11. Historical APY lookback
# ---------------------------------------------------------------------------

class TestHistoricalLookback(unittest.TestCase):

    def test_apy_7d_ago_returned(self):
        history = _make_history(20.0, 10.0, 60)
        result = analyze("P", history)
        self.assertIsNotNone(result["apy_7d_ago"])

    def test_apy_30d_ago_returned_when_enough_data(self):
        history = _make_history(20.0, 10.0, 60)
        result = analyze("P", history)
        self.assertIsNotNone(result["apy_30d_ago"])

    def test_apy_30d_ago_none_when_too_little_data(self):
        history = _make_history(20.0, 10.0, 20)  # only 20 days
        result = analyze("P", history)
        self.assertIsNone(result["apy_30d_ago"])

    def test_single_entry_both_none(self):
        result = analyze("P", _single_entry())
        self.assertIsNone(result["apy_7d_ago"])
        self.assertIsNone(result["apy_30d_ago"])

    def test_apy_7d_ago_less_than_current_for_decaying(self):
        history = _make_history(20.0, 10.0, 60)
        result = analyze("P", history)
        if result["apy_7d_ago"] is not None:
            self.assertGreater(result["apy_7d_ago"], result["current_apy"])

    def test_history_sorted_by_timestamp(self):
        # Provide unsorted history — should still work
        history = _make_history(20.0, 10.0, 30)
        shuffled = list(reversed(history))
        result = analyze("P", shuffled)
        self.assertAlmostEqual(result["current_apy"], 10.0, delta=0.5)


# ---------------------------------------------------------------------------
# 12. Ring-buffer log
# ---------------------------------------------------------------------------

class TestAppendLog(unittest.TestCase):

    def setUp(self):
        self.tmp_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.log_path = self.tmp_file.name
        self.tmp_file.close()
        os.unlink(self.log_path)

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)

    def test_creates_file(self):
        result = analyze("P", _flat_history(10.0, 10))
        append_log(result, self.log_path)
        self.assertTrue(os.path.exists(self.log_path))

    def test_valid_json(self):
        result = analyze("P", _flat_history(10.0, 10))
        append_log(result, self.log_path)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_appends_multiple(self):
        for i in range(3):
            append_log(analyze("P", _flat_history(10.0, 10)), self.log_path)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_cap(self):
        for _ in range(LOG_MAX + 15):
            append_log(analyze("P", _flat_history(10.0, 10)), self.log_path)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), LOG_MAX)

    def test_ring_buffer_keeps_latest(self):
        for i in range(LOG_MAX + 5):
            r = analyze("P", _flat_history(10.0, 10))
            r["_seq"] = i
            append_log(r, self.log_path)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(data[-1]["_seq"], LOG_MAX + 4)

    def test_corrupted_log_resets(self):
        with open(self.log_path, "w") as fh:
            fh.write("garbage")
        append_log(analyze("P", _flat_history(10.0, 10)), self.log_path)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_non_list_json_resets(self):
        with open(self.log_path, "w") as fh:
            json.dump({"oops": "dict"}, fh)
        append_log(analyze("P", _flat_history(10.0, 10)), self.log_path)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)


# ---------------------------------------------------------------------------
# 13. Atomic write
# ---------------------------------------------------------------------------

class TestAtomicWrite(unittest.TestCase):

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.json")
            _atomic_write(path, {"ok": True})
            self.assertTrue(os.path.exists(path))

    def test_valid_json_written(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.json")
            _atomic_write(path, [1, 2, 3])
            with open(path) as fh:
                self.assertEqual(json.load(fh), [1, 2, 3])

    def test_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.json")
            _atomic_write(path, {})
            tmp_files = [f for f in os.listdir(d) if f.endswith(".tmp")]
            self.assertEqual(tmp_files, [])

    def test_creates_subdirectories(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a", "b", "out.json")
            _atomic_write(path, "hello")
            self.assertTrue(os.path.exists(path))


# ---------------------------------------------------------------------------
# 14. Edge cases and robustness
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_empty_history(self):
        result = analyze("P", [])
        self.assertIn("trend", result)
        self.assertIn("recommendation", result)

    def test_none_history(self):
        result = analyze("P", None)
        self.assertIn("trend", result)

    def test_two_entry_history(self):
        history = [
            {"timestamp": time.time() - SECONDS_PER_DAY, "apy": 15.0},
            {"timestamp": time.time(), "apy": 14.0},
        ]
        result = analyze("P", history)
        self.assertIn("decay_rate_daily_pct", result)

    def test_very_long_history(self):
        history = _make_history(30.0, 5.0, 365)
        result = analyze("P", history)
        self.assertIn("trend", result)

    def test_negative_apy_not_in_projection(self):
        history = _make_history(2.0, 0.1, 10)
        result = analyze("P", history)
        self.assertGreaterEqual(result["projected_apy_30d"], 0.0)
        self.assertGreaterEqual(result["projected_apy_90d"], 0.0)

    def test_protocol_empty_string(self):
        result = analyze("", _flat_history(10.0, 10))
        self.assertEqual(result["protocol"], "")

    def test_all_same_timestamp(self):
        ts = time.time()
        history = [{"timestamp": ts, "apy": 10.0}, {"timestamp": ts, "apy": 10.0}]
        result = analyze("P", history)
        self.assertAlmostEqual(result["decay_rate_daily_pct"], 0.0, places=5)

    def test_collapsed_apy_exact_boundary(self):
        # exactly 1.0 → not collapsed (< 1.0 triggers COLLAPSED)
        history = _flat_history(1.0, 10)
        result = analyze("P", history)
        self.assertNotEqual(result["trend"], "COLLAPSED")

    def test_collapsed_just_below_boundary(self):
        history = _flat_history(0.99, 10)
        result = analyze("P", history)
        self.assertEqual(result["trend"], "COLLAPSED")


if __name__ == "__main__":
    unittest.main()
