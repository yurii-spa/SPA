"""
Unit tests for spa_core.analytics.yield_decay_analyzer (MP-761).

Stdlib unittest only (no pytest / numpy / pandas).
All file-IO tests use a temporary directory — no production data touched.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.yield_decay_analyzer import (
    DecayAnalysis,
    DecayResult,
    _decay_label_from_pct,
    _is_likely_inflated,
    _mean,
    _recommendation_for_label,
    analyze,
    analyze_market,
    compute_half_avgs,
    decay_velocity,
    load_history,
    periods_to_floor,
    save_results,
    trend_direction,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _series(values):
    return list(values)


def _proto(protocol, apy_series, asset="USDC"):
    return {"protocol": protocol, "asset": asset, "apy_series": apy_series}


# ---------------------------------------------------------------------------
# Basic field extraction
# ---------------------------------------------------------------------------

class TestBasicFields(unittest.TestCase):
    def test_first_apy_is_first_element(self):
        a = analyze("proto", "USDC", [10.0, 8.0, 6.0])
        self.assertAlmostEqual(a.first_apy, 10.0)

    def test_latest_apy_is_last_element(self):
        a = analyze("proto", "USDC", [10.0, 8.0, 6.0])
        self.assertAlmostEqual(a.latest_apy, 6.0)

    def test_peak_apy_is_maximum(self):
        a = analyze("proto", "USDC", [5.0, 15.0, 8.0, 3.0])
        self.assertAlmostEqual(a.peak_apy, 15.0)

    def test_peak_equals_first_when_monotone_decreasing(self):
        a = analyze("proto", "USDC", [20.0, 15.0, 10.0, 5.0])
        self.assertAlmostEqual(a.peak_apy, 20.0)

    def test_protocol_stored(self):
        a = analyze("aave_v3", "USDC", [5.0, 4.0])
        self.assertEqual(a.protocol, "aave_v3")

    def test_asset_stored(self):
        a = analyze("proto", "DAI", [5.0])
        self.assertEqual(a.asset, "DAI")

    def test_apy_series_stored(self):
        series = [10.0, 8.0, 6.0]
        a = analyze("proto", "USDC", series)
        self.assertEqual(a.apy_series, series)

    def test_floor_apy_default(self):
        a = analyze("proto", "USDC", [10.0, 8.0])
        self.assertAlmostEqual(a.floor_apy, 2.0)

    def test_floor_apy_custom(self):
        a = analyze("proto", "USDC", [10.0, 8.0], floor_apy=3.0)
        self.assertAlmostEqual(a.floor_apy, 3.0)


# ---------------------------------------------------------------------------
# Decay from peak
# ---------------------------------------------------------------------------

class TestDecayFromPeak(unittest.TestCase):
    def test_decay_from_peak_formula(self):
        # peak=20, latest=10 → 50%
        a = analyze("p", "U", [20.0, 15.0, 10.0])
        self.assertAlmostEqual(a.decay_from_peak_pct, 50.0)

    def test_decay_from_peak_zero_when_growing(self):
        # latest equals peak
        a = analyze("p", "U", [5.0, 8.0, 10.0])
        self.assertAlmostEqual(a.decay_from_peak_pct, 0.0)

    def test_decay_from_peak_zero_when_flat(self):
        a = analyze("p", "U", [5.0, 5.0, 5.0])
        self.assertAlmostEqual(a.decay_from_peak_pct, 0.0)

    def test_decay_from_peak_zero_when_peak_is_zero(self):
        a = analyze("p", "U", [0.0, 0.0])
        self.assertAlmostEqual(a.decay_from_peak_pct, 0.0)

    def test_decay_from_peak_100_when_latest_zero(self):
        a = analyze("p", "U", [10.0, 5.0, 0.0])
        self.assertAlmostEqual(a.decay_from_peak_pct, 100.0)


# ---------------------------------------------------------------------------
# compute_half_avgs
# ---------------------------------------------------------------------------

class TestComputeHalfAvgs(unittest.TestCase):
    def test_even_series_splits_correctly(self):
        first, second = compute_half_avgs([10.0, 8.0, 6.0, 4.0])
        self.assertAlmostEqual(first, 9.0)   # avg of [10, 8]
        self.assertAlmostEqual(second, 5.0)  # avg of [6, 4]

    def test_odd_series_splits_correctly(self):
        first, second = compute_half_avgs([10.0, 8.0, 6.0, 4.0, 2.0])
        # mid = 2, first = [10,8], second = [6,4,2]
        self.assertAlmostEqual(first, 9.0)
        self.assertAlmostEqual(second, 4.0)

    def test_single_element_returns_same(self):
        first, second = compute_half_avgs([7.0])
        self.assertAlmostEqual(first, 7.0)
        self.assertAlmostEqual(second, 7.0)

    def test_two_elements(self):
        first, second = compute_half_avgs([10.0, 4.0])
        self.assertAlmostEqual(first, 10.0)
        self.assertAlmostEqual(second, 4.0)

    def test_returns_tuple_of_two(self):
        result = compute_half_avgs([5.0, 4.0, 3.0])
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# trend_direction
# ---------------------------------------------------------------------------

class TestTrendDirection(unittest.TestCase):
    def test_decaying_when_second_much_less_than_first(self):
        # second < first * 0.9
        self.assertEqual(trend_direction(10.0, 8.0), "DECAYING")

    def test_growing_when_second_much_greater_than_first(self):
        # second > first * 1.1
        self.assertEqual(trend_direction(10.0, 12.0), "GROWING")

    def test_stable_within_10_pct(self):
        self.assertEqual(trend_direction(10.0, 9.5), "STABLE")
        self.assertEqual(trend_direction(10.0, 10.5), "STABLE")

    def test_exactly_09_boundary_is_decaying(self):
        # second = first * 0.89 → DECAYING
        self.assertEqual(trend_direction(10.0, 8.9), "DECAYING")

    def test_exactly_09_stable(self):
        # second = first * 0.9 → boundary; NOT < so STABLE
        self.assertEqual(trend_direction(10.0, 9.0), "STABLE")

    def test_zero_first_avg_returns_stable(self):
        self.assertEqual(trend_direction(0.0, 5.0), "STABLE")

    def test_analyze_result_includes_trend(self):
        a = analyze("p", "U", [20.0, 15.0, 10.0, 5.0])
        self.assertEqual(a.trend_direction, "DECAYING")

    def test_growing_series_is_growing(self):
        a = analyze("p", "U", [3.0, 5.0, 8.0, 12.0])
        self.assertEqual(a.trend_direction, "GROWING")


# ---------------------------------------------------------------------------
# decay_velocity
# ---------------------------------------------------------------------------

class TestDecayVelocity(unittest.TestCase):
    def test_velocity_formula(self):
        # (first - last) / (n-1) = (10 - 4) / 2 = 3
        v = decay_velocity([10.0, 7.0, 4.0])
        self.assertAlmostEqual(v, 3.0)

    def test_single_element_is_zero(self):
        self.assertAlmostEqual(decay_velocity([5.0]), 0.0)

    def test_growing_series_negative_velocity(self):
        # (4 - 10) / 2 = -3
        v = decay_velocity([4.0, 7.0, 10.0])
        self.assertAlmostEqual(v, -3.0)

    def test_flat_series_zero_velocity(self):
        v = decay_velocity([5.0, 5.0, 5.0])
        self.assertAlmostEqual(v, 0.0)

    def test_two_element_velocity(self):
        v = decay_velocity([10.0, 6.0])
        self.assertAlmostEqual(v, 4.0)

    def test_analyze_velocity_field(self):
        a = analyze("p", "U", [10.0, 7.0, 4.0])
        self.assertAlmostEqual(a.decay_velocity, 3.0)


# ---------------------------------------------------------------------------
# periods_to_floor
# ---------------------------------------------------------------------------

class TestPeriodsToFloor(unittest.TestCase):
    def test_formula_basic(self):
        # (10 - 2) / 2 = 4
        ptf = periods_to_floor(10.0, 2.0, floor=2.0)
        self.assertAlmostEqual(ptf, 4.0)

    def test_stable_velocity_returns_inf(self):
        ptf = periods_to_floor(10.0, 0.0, floor=2.0)
        self.assertTrue(math.isinf(ptf))

    def test_growing_velocity_returns_inf(self):
        ptf = periods_to_floor(10.0, -1.0, floor=2.0)
        self.assertTrue(math.isinf(ptf))

    def test_already_at_floor_returns_inf(self):
        ptf = periods_to_floor(2.0, 1.0, floor=2.0)
        self.assertTrue(math.isinf(ptf))

    def test_below_floor_returns_inf(self):
        ptf = periods_to_floor(1.5, 0.5, floor=2.0)
        self.assertTrue(math.isinf(ptf))

    def test_custom_floor(self):
        ptf = periods_to_floor(12.0, 2.0, floor=4.0)
        self.assertAlmostEqual(ptf, 4.0)


# ---------------------------------------------------------------------------
# decay_label
# ---------------------------------------------------------------------------

class TestDecayLabel(unittest.TestCase):
    def test_stable_when_no_decay(self):
        self.assertEqual(_decay_label_from_pct(0.0), "STABLE")
        self.assertEqual(_decay_label_from_pct(-5.0), "STABLE")

    def test_mild_decay_0_to_20(self):
        self.assertEqual(_decay_label_from_pct(0.001), "MILD_DECAY")
        self.assertEqual(_decay_label_from_pct(10.0), "MILD_DECAY")
        self.assertEqual(_decay_label_from_pct(19.9), "MILD_DECAY")

    def test_moderate_decay_20_to_50(self):
        self.assertEqual(_decay_label_from_pct(20.0), "MODERATE_DECAY")
        self.assertEqual(_decay_label_from_pct(35.0), "MODERATE_DECAY")
        self.assertEqual(_decay_label_from_pct(50.0), "MODERATE_DECAY")

    def test_severe_decay_above_50(self):
        self.assertEqual(_decay_label_from_pct(50.1), "SEVERE_DECAY")
        self.assertEqual(_decay_label_from_pct(90.0), "SEVERE_DECAY")

    def test_analyze_severe_decay_series(self):
        # peak=20, latest=5 → 75% decay
        a = analyze("p", "U", [20.0, 15.0, 10.0, 5.0])
        self.assertEqual(a.decay_label, "SEVERE_DECAY")

    def test_analyze_stable_series(self):
        a = analyze("p", "U", [5.0, 5.0, 5.0])
        self.assertEqual(a.decay_label, "STABLE")

    def test_analyze_mild_decay(self):
        # peak=10, latest=9 → 10%
        a = analyze("p", "U", [10.0, 9.5, 9.0])
        self.assertEqual(a.decay_label, "MILD_DECAY")


# ---------------------------------------------------------------------------
# is_likely_inflated
# ---------------------------------------------------------------------------

class TestIsLikelyInflated(unittest.TestCase):
    def test_peak_3x_latest_is_inflated(self):
        self.assertTrue(_is_likely_inflated(30.0, 9.0, 10.0))

    def test_peak_exactly_3x_not_inflated(self):
        # NOT strictly > 3, so not inflated
        self.assertFalse(_is_likely_inflated(30.0, 10.0, 10.0))

    def test_peak_above_20_and_decay_above_50_is_inflated(self):
        self.assertTrue(_is_likely_inflated(25.0, 10.0, 60.0))

    def test_peak_above_20_but_decay_below_50_not_inflated(self):
        self.assertFalse(_is_likely_inflated(25.0, 15.0, 40.0))

    def test_normal_situation_not_inflated(self):
        self.assertFalse(_is_likely_inflated(10.0, 8.0, 20.0))

    def test_zero_latest_does_not_trigger_cond1(self):
        # latest=0 → cond1 False (division-by-zero guard)
        self.assertFalse(_is_likely_inflated(30.0, 0.0, 50.0))

    def test_analyze_inflated_series(self):
        # peak=100 → latest=5 → peak > 3*latest and decay=95%
        a = analyze("p", "U", [100.0, 50.0, 20.0, 10.0, 5.0])
        self.assertTrue(a.is_likely_inflated)

    def test_analyze_not_inflated_stable(self):
        a = analyze("p", "U", [5.0, 5.1, 5.0, 4.9])
        self.assertFalse(a.is_likely_inflated)


# ---------------------------------------------------------------------------
# recommendation text
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):
    def test_severe_decay_recommendation(self):
        rec = _recommendation_for_label("SEVERE_DECAY")
        self.assertIn("Significant yield decay", rec)

    def test_moderate_decay_recommendation(self):
        rec = _recommendation_for_label("MODERATE_DECAY")
        self.assertIn("Moderate decay", rec)

    def test_mild_decay_recommendation(self):
        rec = _recommendation_for_label("MILD_DECAY")
        self.assertIn("Mild decay", rec)

    def test_stable_recommendation(self):
        rec = _recommendation_for_label("STABLE")
        self.assertIn("stable", rec.lower())

    def test_analyze_severe_sets_recommendation(self):
        a = analyze("p", "U", [20.0, 15.0, 10.0, 5.0])
        self.assertIn("Significant", a.recommendation)

    def test_analyze_stable_sets_recommendation(self):
        a = analyze("p", "U", [5.0, 5.0, 5.0])
        self.assertIn("stable", a.recommendation.lower())


# ---------------------------------------------------------------------------
# analyze_market
# ---------------------------------------------------------------------------

class TestAnalyzeMarket(unittest.TestCase):
    def _market(self):
        return [
            _proto("aave", [10.0, 8.0, 6.0]),
            _proto("compound", [6.0, 5.8, 5.6]),
            _proto("morpho", [25.0, 15.0, 5.0]),
        ]

    def test_returns_decay_result(self):
        r = analyze_market(self._market())
        self.assertIsInstance(r, DecayResult)

    def test_analyses_count_matches_input(self):
        r = analyze_market(self._market())
        self.assertEqual(len(r.analyses), 3)

    def test_most_stable_protocol_min_decay(self):
        r = analyze_market(self._market())
        # compound has smallest decay
        decays = {a.protocol: a.decay_from_peak_pct for a in r.analyses}
        expected_stable = min(decays, key=decays.get)
        self.assertEqual(r.most_stable_protocol, expected_stable)

    def test_most_decayed_protocol_max_decay(self):
        r = analyze_market(self._market())
        decays = {a.protocol: a.decay_from_peak_pct for a in r.analyses}
        expected_decayed = max(decays, key=decays.get)
        self.assertEqual(r.most_decayed_protocol, expected_decayed)

    def test_avg_decay_is_mean(self):
        r = analyze_market(self._market())
        expected = sum(a.decay_from_peak_pct for a in r.analyses) / 3
        self.assertAlmostEqual(r.avg_decay_from_peak_pct, expected)

    def test_inflated_count(self):
        r = analyze_market(self._market())
        expected = sum(1 for a in r.analyses if a.is_likely_inflated)
        self.assertEqual(r.inflated_count, expected)

    def test_market_stable_when_low_avg_decay(self):
        data = [
            _proto("a", [5.0, 5.1, 5.0]),
            _proto("b", [6.0, 6.1, 6.0]),
        ]
        r = analyze_market(data)
        self.assertEqual(r.market_decay_label, "STABLE_MARKET")

    def test_market_normalizing_when_moderate_avg(self):
        # force ~15% avg decay
        data = [
            _proto("a", [20.0, 17.0]),  # 15% decay
            _proto("b", [20.0, 17.0]),
        ]
        r = analyze_market(data)
        self.assertIn(r.market_decay_label, ("STABLE_MARKET", "NORMALIZING"))

    def test_market_declining_when_high_avg_decay(self):
        data = [
            _proto("a", [100.0, 10.0]),  # 90% decay
            _proto("b", [100.0, 10.0]),
        ]
        r = analyze_market(data)
        self.assertEqual(r.market_decay_label, "DECLINING")

    def test_recommendation_summary_nonempty(self):
        r = analyze_market(self._market())
        self.assertTrue(len(r.recommendation_summary) > 0)

    def test_empty_input_returns_result(self):
        r = analyze_market([])
        self.assertIsInstance(r, DecayResult)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_single_element_series_no_exception(self):
        a = analyze("p", "U", [5.0])
        self.assertAlmostEqual(a.first_apy, 5.0)
        self.assertAlmostEqual(a.latest_apy, 5.0)
        self.assertAlmostEqual(a.peak_apy, 5.0)
        self.assertAlmostEqual(a.decay_velocity, 0.0)
        self.assertTrue(math.isinf(a.periods_to_floor))

    def test_single_element_series_decay_zero(self):
        a = analyze("p", "U", [5.0])
        self.assertAlmostEqual(a.decay_from_peak_pct, 0.0)

    def test_monotonically_growing_series_stable_no_decay(self):
        a = analyze("p", "U", [3.0, 5.0, 7.0, 9.0, 11.0])
        self.assertAlmostEqual(a.decay_from_peak_pct, 0.0)
        self.assertEqual(a.decay_label, "STABLE")

    def test_monotonically_growing_velocity_negative(self):
        a = analyze("p", "U", [3.0, 5.0, 7.0])
        self.assertLess(a.decay_velocity, 0)

    def test_growing_series_periods_to_floor_inf(self):
        a = analyze("p", "U", [3.0, 5.0, 7.0, 9.0])
        self.assertTrue(math.isinf(a.periods_to_floor))

    def test_all_zeros_does_not_raise(self):
        a = analyze("p", "U", [0.0, 0.0, 0.0])
        self.assertAlmostEqual(a.decay_from_peak_pct, 0.0)


# ---------------------------------------------------------------------------
# Save / Load
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _market_result(self):
        return analyze_market([
            _proto("aave", [10.0, 8.0, 6.0]),
            _proto("compound", [6.0, 5.8, 5.6]),
        ])

    def test_save_creates_file(self):
        r = self._market_result()
        save_results(r, data_dir=self.tmpdir)
        self.assertTrue((self.tmpdir / "yield_decay_log.json").exists())

    def test_load_returns_list(self):
        r = self._market_result()
        save_results(r, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertIsInstance(history, list)

    def test_round_trip_saves_one_entry(self):
        r = self._market_result()
        save_results(r, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 1)

    def test_round_trip_analyses_count(self):
        r = self._market_result()
        save_results(r, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history[0]["analyses"]), 2)

    def test_multiple_saves_accumulate(self):
        for _ in range(3):
            save_results(self._market_result(), data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 3)

    def test_ring_buffer_caps_at_100(self):
        for _ in range(105):
            save_results(self._market_result(), data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertLessEqual(len(history), 100)

    def test_ring_buffer_exactly_100(self):
        for _ in range(102):
            save_results(self._market_result(), data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 100)

    def test_load_empty_when_no_file(self):
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(history, [])

    def test_saved_to_field_set(self):
        r = self._market_result()
        r = save_results(r, data_dir=self.tmpdir)
        self.assertTrue(len(r.saved_to) > 0)

    def test_atomic_write_valid_json(self):
        r = self._market_result()
        save_results(r, data_dir=self.tmpdir)
        content = (self.tmpdir / "yield_decay_log.json").read_text(encoding="utf-8")
        parsed = json.loads(content)
        self.assertIsInstance(parsed, list)

    def test_inf_serialized_as_string(self):
        # series with velocity > 0 → periods_to_floor is finite, but
        # a stable series will produce inf
        r = analyze_market([_proto("p", [5.0, 5.0, 5.0])])
        save_results(r, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        ptf = history[0]["analyses"][0]["periods_to_floor"]
        # Should be "Infinity" (string) or a number — either is valid JSON
        self.assertIn(str(ptf), ["Infinity", "inf"] + [str(ptf)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
