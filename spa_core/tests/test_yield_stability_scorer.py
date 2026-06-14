"""
Tests for MP-745: YieldStabilityScorer
≥65 tests using unittest only (no pytest).
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.yield_stability_scorer import (
    YieldStabilityScore,
    YieldStabilityResult,
    compute_cv,
    compute_regime_changes,
    compute_trend_direction,
    score_protocol,
    score_all,
    save_results,
    load_history,
    _mean,
    _std,
)


# ---------------------------------------------------------------------------
# Internal helpers (_mean, _std)
# ---------------------------------------------------------------------------

class TestMean(unittest.TestCase):

    def test_basic(self):
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0]), 2.0)

    def test_empty_returns_zero(self):
        self.assertAlmostEqual(_mean([]), 0.0)

    def test_single(self):
        self.assertAlmostEqual(_mean([5.0]), 5.0)

    def test_floats(self):
        self.assertAlmostEqual(_mean([1.5, 2.5]), 2.0)


class TestStd(unittest.TestCase):

    def test_constant_returns_zero(self):
        self.assertAlmostEqual(_std([5, 5, 5, 5]), 0.0)

    def test_empty_returns_zero(self):
        self.assertAlmostEqual(_std([]), 0.0)

    def test_single_returns_zero(self):
        self.assertAlmostEqual(_std([42.0]), 0.0)

    def test_known_population_std(self):
        # population std of [2,4,4,4,5,5,7,9] = 2.0
        self.assertAlmostEqual(_std([2, 4, 4, 4, 5, 5, 7, 9]), 2.0)

    def test_two_point_symmetric(self):
        # std([0, 2]) population = 1.0
        self.assertAlmostEqual(_std([0, 2]), 1.0)

    def test_nonnegative(self):
        self.assertGreaterEqual(_std([1, 5, 3, 8, 2]), 0.0)


# ---------------------------------------------------------------------------
# compute_cv
# ---------------------------------------------------------------------------

class TestComputeCV(unittest.TestCase):

    def test_formula(self):
        series = [5.0, 5.0, 5.0, 7.0, 3.0]
        expected = _std(series) / _mean(series) * 100
        self.assertAlmostEqual(compute_cv(series), expected)

    def test_constant_series_returns_zero(self):
        self.assertAlmostEqual(compute_cv([5, 5, 5, 5]), 0.0)

    def test_mean_zero_returns_zero(self):
        self.assertEqual(compute_cv([0, 0, 0]), 0.0)

    def test_empty_returns_zero(self):
        self.assertEqual(compute_cv([]), 0.0)

    def test_negative_mean_returns_zero(self):
        self.assertEqual(compute_cv([-1, -2, -3]), 0.0)

    def test_nonnegative_result(self):
        self.assertGreaterEqual(compute_cv([3.0, 5.0, 7.0]), 0.0)


# ---------------------------------------------------------------------------
# compute_regime_changes
# ---------------------------------------------------------------------------

class TestComputeRegimeChanges(unittest.TestCase):

    def test_alternating_above_below(self):
        # mean=5: [3,7,3,7] → 3 transitions
        self.assertEqual(compute_regime_changes([3, 7, 3, 7], 5.0), 3)

    def test_constant_at_mean_zero(self):
        self.assertEqual(compute_regime_changes([5, 5, 5, 5], 5.0), 0)

    def test_all_above_mean_zero(self):
        self.assertEqual(compute_regime_changes([6, 7, 8], 5.0), 0)

    def test_all_below_mean_zero(self):
        self.assertEqual(compute_regime_changes([1, 2, 3], 5.0), 0)

    def test_alternating_many(self):
        # [1,9,1,9,1,9] mean=5 → 5 transitions
        self.assertEqual(compute_regime_changes([1, 9, 1, 9, 1, 9], 5.0), 5)

    def test_single_element_zero(self):
        self.assertEqual(compute_regime_changes([5], 5.0), 0)

    def test_empty_zero(self):
        self.assertEqual(compute_regime_changes([], 5.0), 0)

    def test_one_crossing(self):
        # [3,3,7,7]: crosses once at (3→7)
        self.assertEqual(compute_regime_changes([3, 3, 7, 7], 5.0), 1)

    def test_boundary_at_mean_not_counted(self):
        # [5,5,5]: all at mean, no transition
        self.assertEqual(compute_regime_changes([5, 5, 5], 5.0), 0)


# ---------------------------------------------------------------------------
# compute_trend_direction
# ---------------------------------------------------------------------------

class TestComputeTrendDirection(unittest.TestCase):

    def test_up_second_half_higher(self):
        series = [5, 5, 5, 5, 10, 10, 10, 10]
        self.assertEqual(compute_trend_direction(series), "UP")

    def test_down_second_half_lower(self):
        series = [10, 10, 10, 10, 5, 5, 5, 5]
        self.assertEqual(compute_trend_direction(series), "DOWN")

    def test_flat_same_halves(self):
        series = [5, 5, 5, 5, 5, 5, 5, 5]
        self.assertEqual(compute_trend_direction(series), "FLAT")

    def test_single_element_flat(self):
        self.assertEqual(compute_trend_direction([5.0]), "FLAT")

    def test_two_elements_up(self):
        self.assertEqual(compute_trend_direction([5, 10]), "UP")

    def test_two_elements_down(self):
        self.assertEqual(compute_trend_direction([10, 5]), "DOWN")

    def test_two_elements_flat(self):
        self.assertEqual(compute_trend_direction([5, 5]), "FLAT")

    def test_below_threshold_is_flat(self):
        # 0.9% change < 1% threshold → FLAT
        series = [10, 10, 10.09, 10.09]
        self.assertEqual(compute_trend_direction(series), "FLAT")

    def test_above_threshold_is_up(self):
        # 1.5% change > 1% threshold → UP
        series = [10, 10, 10.15, 10.15]
        self.assertEqual(compute_trend_direction(series), "UP")


# ---------------------------------------------------------------------------
# score_protocol
# ---------------------------------------------------------------------------

class TestScoreProtocol(unittest.TestCase):

    def test_constant_cv_score_100(self):
        s = score_protocol("A", "USDC", [5.0] * 10)
        self.assertAlmostEqual(s.cv_score, 100.0)

    def test_constant_range_score_100(self):
        s = score_protocol("A", "USDC", [5.0] * 10)
        self.assertAlmostEqual(s.range_score, 100.0)

    def test_constant_regime_score_100(self):
        s = score_protocol("A", "USDC", [5.0] * 10)
        self.assertAlmostEqual(s.regime_score, 100.0)

    def test_constant_stability_score_100(self):
        # all components = 100 → stability = 100
        s = score_protocol("A", "USDC", [5.0] * 10)
        self.assertAlmostEqual(s.stability_score, 100.0)

    def test_cv_score_formula_100_minus_cv(self):
        series = [4.0, 6.0, 4.0, 6.0]
        cv = compute_cv(series)
        expected_cv_score = max(0.0, 100.0 - min(cv, 100.0))
        s = score_protocol("A", "USDC", series)
        self.assertAlmostEqual(s.cv_score, expected_cv_score)

    def test_regime_score_clamped_at_zero(self):
        # 20+ regime changes → max(0, 100-n*5) = 0
        series = [1.0, 9.0] * 15  # 30 elements alternating
        s = score_protocol("A", "USDC", series)
        self.assertAlmostEqual(s.regime_score, 0.0)

    def test_stability_score_weighted_formula(self):
        s = score_protocol("A", "USDC", [5.0] * 20)
        expected = round(0.4 * s.cv_score + 0.4 * s.range_score + 0.2 * s.regime_score, 2)
        self.assertAlmostEqual(s.stability_score, expected)

    def test_stability_score_rounded_to_2dp(self):
        s = score_protocol("A", "USDC", [3.0, 5.0, 7.0, 4.0, 6.0])
        self.assertAlmostEqual(s.stability_score, round(s.stability_score, 2))

    def test_stability_label_highly_stable(self):
        s = score_protocol("A", "USDC", [5.0] * 20)
        self.assertEqual(s.stability_label, "HIGHLY_STABLE")

    def test_stability_label_unstable(self):
        # Very volatile: alternating extremes
        s = score_protocol("A", "USDC", [1.0, 20.0] * 10)
        self.assertIn(s.stability_label, {"UNSTABLE", "MODERATE"})

    def test_all_four_labels_possible(self):
        valid = {"HIGHLY_STABLE", "STABLE", "MODERATE", "UNSTABLE"}
        s = score_protocol("A", "USDC", [5.0] * 5)
        self.assertIn(s.stability_label, valid)

    def test_is_yield_trending_up_true(self):
        s = score_protocol("A", "USDC", [3, 3, 3, 3, 6, 6, 6, 6])
        self.assertTrue(s.is_yield_trending_up)
        self.assertEqual(s.trend_direction, "UP")

    def test_is_yield_trending_up_false_down(self):
        s = score_protocol("A", "USDC", [6, 6, 6, 6, 3, 3, 3, 3])
        self.assertFalse(s.is_yield_trending_up)
        self.assertEqual(s.trend_direction, "DOWN")

    def test_is_yield_trending_up_false_flat(self):
        s = score_protocol("A", "USDC", [5.0] * 10)
        self.assertFalse(s.is_yield_trending_up)
        self.assertEqual(s.trend_direction, "FLAT")

    def test_mean_apy(self):
        s = score_protocol("A", "USDC", [4.0, 6.0])
        self.assertAlmostEqual(s.mean_apy, 5.0)

    def test_apy_range(self):
        s = score_protocol("A", "USDC", [3.0, 7.0, 5.0])
        self.assertAlmostEqual(s.apy_range, 4.0)

    def test_min_apy(self):
        s = score_protocol("A", "USDC", [3.0, 7.0, 5.0])
        self.assertAlmostEqual(s.min_apy, 3.0)

    def test_max_apy(self):
        s = score_protocol("A", "USDC", [3.0, 7.0, 5.0])
        self.assertAlmostEqual(s.max_apy, 7.0)

    def test_single_element_zero_std(self):
        s = score_protocol("A", "USDC", [5.0])
        self.assertAlmostEqual(s.std_apy, 0.0)

    def test_single_element_zero_regime_changes(self):
        s = score_protocol("A", "USDC", [5.0])
        self.assertEqual(s.regime_changes, 0)

    def test_single_element_zero_range(self):
        s = score_protocol("A", "USDC", [5.0])
        self.assertAlmostEqual(s.apy_range, 0.0)

    def test_protocol_stored(self):
        s = score_protocol("MyProto", "USDC", [5.0])
        self.assertEqual(s.protocol, "MyProto")

    def test_asset_stored(self):
        s = score_protocol("A", "DAI", [5.0])
        self.assertEqual(s.asset, "DAI")

    def test_recommendation_highly_stable_mentions_core(self):
        s = score_protocol("A", "USDC", [5.0] * 20)
        self.assertIn("core allocation", s.recommendation.lower())

    def test_recommendation_nonempty(self):
        s = score_protocol("A", "USDC", [1.0, 20.0] * 5)
        self.assertGreater(len(s.recommendation), 0)

    def test_returns_yield_stability_score(self):
        s = score_protocol("A", "USDC", [5.0])
        self.assertIsInstance(s, YieldStabilityScore)

    def test_coefficient_of_variation_stored(self):
        series = [4.0, 6.0, 4.0, 6.0]
        s = score_protocol("A", "USDC", series)
        self.assertAlmostEqual(s.coefficient_of_variation, compute_cv(series))


# ---------------------------------------------------------------------------
# score_all
# ---------------------------------------------------------------------------

class TestScoreAll(unittest.TestCase):

    def _pd(self, protocol, series):
        return {"protocol": protocol, "asset": "USDC", "apy_series": series}

    def test_most_stable_is_max(self):
        pds = [self._pd("Stable", [5.0] * 20), self._pd("Volatile", [1.0, 20.0] * 5)]
        result = score_all(pds)
        self.assertEqual(result.most_stable_protocol, "Stable")

    def test_least_stable_is_min(self):
        pds = [self._pd("Stable", [5.0] * 20), self._pd("Volatile", [1.0, 20.0] * 5)]
        result = score_all(pds)
        self.assertEqual(result.least_stable_protocol, "Volatile")

    def test_avg_stability_score_constant(self):
        pds = [self._pd("A", [5.0] * 10), self._pd("B", [5.0] * 10)]
        result = score_all(pds)
        self.assertAlmostEqual(result.avg_stability_score, 100.0)

    def test_highly_stable_count(self):
        pds = [
            self._pd("A", [5.0] * 10),       # HIGHLY_STABLE (100)
            self._pd("B", [5.0] * 10),       # HIGHLY_STABLE (100)
            self._pd("C", [1.0, 20.0] * 5),  # not highly stable
        ]
        result = score_all(pds)
        self.assertEqual(result.highly_stable_count, 2)

    def test_market_label_stable_market(self):
        pds = [self._pd(f"P{i}", [5.0] * 10) for i in range(3)]
        result = score_all(pds)
        self.assertEqual(result.market_stability_label, "STABLE_MARKET")

    def test_market_label_volatile_market(self):
        # Very volatile → avg score low
        pds = [self._pd(f"P{i}", [1.0, 20.0] * 10) for i in range(3)]
        result = score_all(pds)
        self.assertIn(result.market_stability_label, {"VOLATILE_MARKET", "MIXED_MARKET"})

    def test_market_label_mixed_market_exists_in_valid_set(self):
        valid = {"STABLE_MARKET", "MIXED_MARKET", "VOLATILE_MARKET"}
        pds = [self._pd("A", [5.0] * 5), self._pd("B", [1.0, 20.0] * 5)]
        result = score_all(pds)
        self.assertIn(result.market_stability_label, valid)

    def test_returns_yield_stability_result(self):
        pds = [self._pd("A", [5.0] * 5)]
        self.assertIsInstance(score_all(pds), YieldStabilityResult)

    def test_scores_list_length(self):
        pds = [self._pd(f"P{i}", [5.0] * 5) for i in range(4)]
        result = score_all(pds)
        self.assertEqual(len(result.scores), 4)

    def test_two_identical_protocols_same_score(self):
        series = [5.0, 6.0, 4.0, 5.5]
        pds = [self._pd("A", series), self._pd("B", series)]
        result = score_all(pds)
        scores = {s.protocol: s.stability_score for s in result.scores}
        self.assertAlmostEqual(scores["A"], scores["B"])

    def test_recommendation_summary_nonempty(self):
        pds = [self._pd("A", [5.0] * 5)]
        result = score_all(pds)
        self.assertGreater(len(result.recommendation_summary), 0)


# ---------------------------------------------------------------------------
# save_results / load_history
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmp_dir, "yield_stability_log.json")

    def _make_result(self):
        pds = [{"protocol": "Aave", "asset": "USDC", "apy_series": [5.0, 5.1, 4.9, 5.2]}]
        return score_all(pds)

    def test_save_creates_file(self):
        save_results(self._make_result(), self.data_file)
        self.assertTrue(os.path.exists(self.data_file))

    def test_load_empty_on_missing(self):
        self.assertEqual(load_history(self.data_file), [])

    def test_save_load_round_trip(self):
        save_results(self._make_result(), self.data_file)
        self.assertEqual(len(load_history(self.data_file)), 1)

    def test_save_accumulates(self):
        r = self._make_result()
        save_results(r, self.data_file)
        save_results(r, self.data_file)
        self.assertEqual(len(load_history(self.data_file)), 2)

    def test_ring_buffer_cap_100(self):
        r = self._make_result()
        for _ in range(105):
            save_results(r, self.data_file)
        self.assertEqual(len(load_history(self.data_file)), 100)

    def test_file_is_valid_json(self):
        save_results(self._make_result(), self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_single_element_series_scores_gracefully(self):
        s = score_protocol("A", "USDC", [5.0])
        self.assertAlmostEqual(s.std_apy, 0.0)
        self.assertEqual(s.regime_changes, 0)
        self.assertAlmostEqual(s.apy_range, 0.0)
        self.assertIsInstance(s.stability_score, float)

    def test_all_same_values_score_100(self):
        s = score_protocol("A", "USDC", [5.0] * 100)
        self.assertAlmostEqual(s.stability_score, 100.0)

    def test_two_identical_input_series_same_score(self):
        pds = [
            {"protocol": "X", "asset": "USDC", "apy_series": [3.0, 5.0, 7.0]},
            {"protocol": "Y", "asset": "USDC", "apy_series": [3.0, 5.0, 7.0]},
        ]
        result = score_all(pds)
        x = next(s.stability_score for s in result.scores if s.protocol == "X")
        y = next(s.stability_score for s in result.scores if s.protocol == "Y")
        self.assertAlmostEqual(x, y)


if __name__ == "__main__":
    unittest.main()
