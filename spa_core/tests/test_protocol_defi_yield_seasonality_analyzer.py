"""
Tests for MP-1129: ProtocolDeFiYieldSeasonalityAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_yield_seasonality_analyzer
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)

from spa_core.analytics.protocol_defi_yield_seasonality_analyzer import (
    ProtocolDeFiYieldSeasonalityAnalyzer,
    _clamp,
    _safe_ratio,
    _compute_apy_vs_30d_ratio,
    _compute_apy_vs_90d_ratio,
    _compute_apy_vs_180d_ratio,
    _compute_is_above_all_averages,
    _compute_expected_normalized_apy_pct,
    _compute_ratio_component,
    _compute_yield_type_base,
    _compute_market_condition_adj,
    _compute_quarter_end_adj,
    _compute_reversion_probability_pct,
    _compute_seasonality_label,
    _atomic_append_log,
    _LOG_CAP,
    _W_30D,
    _W_90D,
    _W_180D,
    _RATIO_EXCESS_SATURATION,
    _RATIO_MAX_CONTRIBUTION,
    _YIELD_TYPE_BASE,
    _MARKET_CONDITION_ADJ,
    _QUARTER_END_HIGH_THRESHOLD,
    _QUARTER_END_HIGH_ADJ,
    _QUARTER_END_MID_THRESHOLD,
    _QUARTER_END_MID_ADJ,
)


# ---------------------------------------------------------------------------
# Fixture factory
# ---------------------------------------------------------------------------

def make_data(**overrides):
    """Return a baseline valid input dict."""
    base = {
        "protocol_name": "Uniswap V3",
        "current_apy_pct": 12.5,
        "apy_30d_avg_pct": 8.0,
        "apy_90d_avg_pct": 7.0,
        "apy_180d_avg_pct": 6.5,
        "yield_type": "trading_fees",
        "market_condition": "bull",
        "days_into_quarter": 30,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. _clamp
# ---------------------------------------------------------------------------

class TestClamp(unittest.TestCase):
    def test_below_lo_default(self):
        self.assertEqual(_clamp(-5.0), 0.0)

    def test_above_hi_default(self):
        self.assertEqual(_clamp(105.0), 100.0)

    def test_at_lo(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_at_hi(self):
        self.assertEqual(_clamp(100.0), 100.0)

    def test_inside_range(self):
        self.assertAlmostEqual(_clamp(42.0), 42.0)

    def test_custom_bounds_inside(self):
        self.assertAlmostEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_custom_bounds_below(self):
        self.assertEqual(_clamp(-2.0, 0.0, 10.0), 0.0)

    def test_custom_bounds_above(self):
        self.assertEqual(_clamp(12.0, 0.0, 10.0), 10.0)


# ---------------------------------------------------------------------------
# 2. _safe_ratio
# ---------------------------------------------------------------------------

class TestSafeRatio(unittest.TestCase):
    def test_normal_ratio(self):
        self.assertAlmostEqual(_safe_ratio(10.0, 5.0), 2.0, places=6)

    def test_equal_values(self):
        self.assertAlmostEqual(_safe_ratio(7.0, 7.0), 1.0, places=6)

    def test_current_less_than_avg(self):
        self.assertAlmostEqual(_safe_ratio(3.0, 6.0), 0.5, places=6)

    def test_zero_avg_returns_one(self):
        self.assertAlmostEqual(_safe_ratio(10.0, 0.0), 1.0)

    def test_negative_avg_returns_one(self):
        self.assertAlmostEqual(_safe_ratio(10.0, -1.0), 1.0)

    def test_zero_current(self):
        self.assertAlmostEqual(_safe_ratio(0.0, 5.0), 0.0, places=6)

    def test_returns_float(self):
        self.assertIsInstance(_safe_ratio(10.0, 5.0), float)

    def test_rounded_to_6_places(self):
        result = _safe_ratio(1.0, 3.0)
        self.assertEqual(result, round(result, 6))


# ---------------------------------------------------------------------------
# 3. _compute_apy_vs_30d_ratio
# ---------------------------------------------------------------------------

class TestApyVs30dRatio(unittest.TestCase):
    def test_above_avg(self):
        self.assertAlmostEqual(_compute_apy_vs_30d_ratio(12.0, 8.0), 1.5, places=5)

    def test_equal_to_avg(self):
        self.assertAlmostEqual(_compute_apy_vs_30d_ratio(8.0, 8.0), 1.0, places=5)

    def test_below_avg(self):
        self.assertAlmostEqual(_compute_apy_vs_30d_ratio(4.0, 8.0), 0.5, places=5)

    def test_zero_avg_fallback(self):
        self.assertAlmostEqual(_compute_apy_vs_30d_ratio(10.0, 0.0), 1.0)

    def test_negative_avg_fallback(self):
        self.assertAlmostEqual(_compute_apy_vs_30d_ratio(5.0, -2.0), 1.0)

    def test_large_spike(self):
        result = _compute_apy_vs_30d_ratio(50.0, 5.0)
        self.assertAlmostEqual(result, 10.0, places=4)


# ---------------------------------------------------------------------------
# 4. _compute_apy_vs_90d_ratio
# ---------------------------------------------------------------------------

class TestApyVs90dRatio(unittest.TestCase):
    def test_above_avg(self):
        self.assertAlmostEqual(_compute_apy_vs_90d_ratio(14.0, 7.0), 2.0, places=5)

    def test_equal_to_avg(self):
        self.assertAlmostEqual(_compute_apy_vs_90d_ratio(7.0, 7.0), 1.0, places=5)

    def test_below_avg(self):
        self.assertAlmostEqual(_compute_apy_vs_90d_ratio(3.5, 7.0), 0.5, places=5)

    def test_zero_avg_fallback(self):
        self.assertAlmostEqual(_compute_apy_vs_90d_ratio(5.0, 0.0), 1.0)

    def test_negative_avg_fallback(self):
        self.assertAlmostEqual(_compute_apy_vs_90d_ratio(5.0, -5.0), 1.0)

    def test_triple_the_avg(self):
        result = _compute_apy_vs_90d_ratio(21.0, 7.0)
        self.assertAlmostEqual(result, 3.0, places=5)


# ---------------------------------------------------------------------------
# 5. _compute_apy_vs_180d_ratio
# ---------------------------------------------------------------------------

class TestApyVs180dRatio(unittest.TestCase):
    def test_above_avg(self):
        self.assertAlmostEqual(_compute_apy_vs_180d_ratio(13.0, 6.5), 2.0, places=5)

    def test_equal_to_avg(self):
        self.assertAlmostEqual(_compute_apy_vs_180d_ratio(6.5, 6.5), 1.0, places=5)

    def test_below_avg(self):
        self.assertAlmostEqual(_compute_apy_vs_180d_ratio(3.0, 6.0), 0.5, places=5)

    def test_zero_avg_fallback(self):
        self.assertAlmostEqual(_compute_apy_vs_180d_ratio(8.0, 0.0), 1.0)

    def test_negative_avg_fallback(self):
        self.assertAlmostEqual(_compute_apy_vs_180d_ratio(8.0, -3.0), 1.0)

    def test_fractional_result(self):
        result = _compute_apy_vs_180d_ratio(5.0, 6.0)
        self.assertAlmostEqual(result, round(5.0 / 6.0, 6), places=6)


# ---------------------------------------------------------------------------
# 6. _compute_is_above_all_averages
# ---------------------------------------------------------------------------

class TestIsAboveAllAverages(unittest.TestCase):
    def test_above_all(self):
        self.assertTrue(
            _compute_is_above_all_averages(15.0, 8.0, 7.0, 6.5)
        )

    def test_equal_to_30d_not_above(self):
        self.assertFalse(
            _compute_is_above_all_averages(8.0, 8.0, 7.0, 6.5)
        )

    def test_equal_to_90d_not_above(self):
        self.assertFalse(
            _compute_is_above_all_averages(10.0, 8.0, 10.0, 6.5)
        )

    def test_equal_to_180d_not_above(self):
        self.assertFalse(
            _compute_is_above_all_averages(10.0, 8.0, 7.0, 10.0)
        )

    def test_below_all(self):
        self.assertFalse(
            _compute_is_above_all_averages(3.0, 8.0, 7.0, 6.5)
        )

    def test_returns_bool(self):
        result = _compute_is_above_all_averages(10.0, 5.0, 5.0, 5.0)
        self.assertIsInstance(result, bool)

    def test_above_only_30d(self):
        self.assertFalse(
            _compute_is_above_all_averages(9.0, 8.0, 10.0, 11.0)
        )

    def test_zero_all_averages_positive_current(self):
        # 5.0 > 0.0 for all → True
        self.assertTrue(
            _compute_is_above_all_averages(5.0, 0.0, 0.0, 0.0)
        )


# ---------------------------------------------------------------------------
# 7. _compute_expected_normalized_apy_pct
# ---------------------------------------------------------------------------

class TestExpectedNormalizedApy(unittest.TestCase):
    def test_equal_averages(self):
        # All avgs equal → result = same
        result = _compute_expected_normalized_apy_pct(10.0, 10.0, 10.0)
        self.assertAlmostEqual(result, 10.0, places=5)

    def test_weight_sum_is_one(self):
        self.assertAlmostEqual(_W_30D + _W_90D + _W_180D, 1.0, places=6)

    def test_baseline_weights(self):
        # 0.2*8 + 0.4*7 + 0.4*6.5 = 1.6 + 2.8 + 2.6 = 7.0
        result = _compute_expected_normalized_apy_pct(8.0, 7.0, 6.5)
        self.assertAlmostEqual(result, 7.0, places=4)

    def test_zero_all_averages(self):
        result = _compute_expected_normalized_apy_pct(0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.0, places=5)

    def test_30d_weighted_less(self):
        # 30d is less weighted → closer to 90d+180d average
        result = _compute_expected_normalized_apy_pct(100.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 20.0, places=4)

    def test_90d_and_180d_equal_weight(self):
        # 90d=180d=5, 30d=0 → result = 0.4*5 + 0.4*5 = 4.0
        result = _compute_expected_normalized_apy_pct(0.0, 5.0, 5.0)
        self.assertAlmostEqual(result, 4.0, places=4)

    def test_returns_float(self):
        self.assertIsInstance(
            _compute_expected_normalized_apy_pct(5.0, 6.0, 7.0), float
        )

    def test_rounded_to_6_places(self):
        result = _compute_expected_normalized_apy_pct(8.0, 7.0, 6.5)
        self.assertEqual(result, round(result, 6))


# ---------------------------------------------------------------------------
# 8. _compute_ratio_component
# ---------------------------------------------------------------------------

class TestRatioComponent(unittest.TestCase):
    def test_ratio_1_gives_zero(self):
        self.assertAlmostEqual(_compute_ratio_component(1.0), 0.0)

    def test_ratio_below_1_gives_zero(self):
        self.assertAlmostEqual(_compute_ratio_component(0.5), 0.0)

    def test_ratio_at_saturation(self):
        # ratio=1.0+SATURATION=3.0 → full contribution = 60
        result = _compute_ratio_component(1.0 + _RATIO_EXCESS_SATURATION)
        self.assertAlmostEqual(result, _RATIO_MAX_CONTRIBUTION)

    def test_ratio_above_saturation_capped(self):
        result = _compute_ratio_component(10.0)
        self.assertAlmostEqual(result, _RATIO_MAX_CONTRIBUTION)

    def test_ratio_at_mid(self):
        # excess=1.0, saturation=2.0 → frac=0.5 → 30 pts
        result = _compute_ratio_component(2.0)
        self.assertAlmostEqual(result, 30.0, places=3)

    def test_ratio_1_5(self):
        # excess=0.5, saturation=2.0 → frac=0.25 → 15 pts
        result = _compute_ratio_component(1.5)
        self.assertAlmostEqual(result, 15.0, places=3)

    def test_returns_float(self):
        self.assertIsInstance(_compute_ratio_component(1.5), float)

    def test_monotone_increases(self):
        ratios = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
        components = [_compute_ratio_component(r) for r in ratios]
        for i in range(len(components) - 1):
            self.assertLessEqual(components[i], components[i + 1])


# ---------------------------------------------------------------------------
# 9. _compute_yield_type_base
# ---------------------------------------------------------------------------

class TestYieldTypeBase(unittest.TestCase):
    def test_points_highest(self):
        self.assertEqual(
            _compute_yield_type_base("points"), _YIELD_TYPE_BASE["points"]
        )

    def test_emissions(self):
        self.assertEqual(
            _compute_yield_type_base("emissions"), _YIELD_TYPE_BASE["emissions"]
        )

    def test_trading_fees(self):
        self.assertEqual(
            _compute_yield_type_base("trading_fees"), _YIELD_TYPE_BASE["trading_fees"]
        )

    def test_staking_rewards(self):
        self.assertEqual(
            _compute_yield_type_base("staking_rewards"),
            _YIELD_TYPE_BASE["staking_rewards"],
        )

    def test_lending_interest(self):
        self.assertEqual(
            _compute_yield_type_base("lending_interest"),
            _YIELD_TYPE_BASE["lending_interest"],
        )

    def test_unknown_type_returns_default(self):
        result = _compute_yield_type_base("unknown_yield")
        self.assertGreater(result, 0)  # should return a positive default

    def test_points_higher_than_lending(self):
        self.assertGreater(
            _compute_yield_type_base("points"),
            _compute_yield_type_base("lending_interest"),
        )


# ---------------------------------------------------------------------------
# 10. _compute_market_condition_adj
# ---------------------------------------------------------------------------

class TestMarketConditionAdj(unittest.TestCase):
    def test_bull(self):
        self.assertEqual(
            _compute_market_condition_adj("bull"), _MARKET_CONDITION_ADJ["bull"]
        )

    def test_high_volatility(self):
        self.assertEqual(
            _compute_market_condition_adj("high_volatility"),
            _MARKET_CONDITION_ADJ["high_volatility"],
        )

    def test_sideways(self):
        self.assertEqual(
            _compute_market_condition_adj("sideways"),
            _MARKET_CONDITION_ADJ["sideways"],
        )

    def test_bear(self):
        self.assertEqual(
            _compute_market_condition_adj("bear"), _MARKET_CONDITION_ADJ["bear"]
        )

    def test_unknown_returns_default(self):
        result = _compute_market_condition_adj("unknown")
        self.assertGreaterEqual(result, 0)

    def test_high_volatility_highest(self):
        self.assertGreaterEqual(
            _compute_market_condition_adj("high_volatility"),
            _compute_market_condition_adj("bull"),
        )


# ---------------------------------------------------------------------------
# 11. _compute_quarter_end_adj
# ---------------------------------------------------------------------------

class TestQuarterEndAdj(unittest.TestCase):
    def test_early_quarter_zero(self):
        self.assertAlmostEqual(_compute_quarter_end_adj(0), 0.0)

    def test_day_30_zero(self):
        self.assertAlmostEqual(_compute_quarter_end_adj(30), 0.0)

    def test_day_59_zero(self):
        self.assertAlmostEqual(_compute_quarter_end_adj(59), 0.0)

    def test_at_mid_threshold(self):
        self.assertAlmostEqual(
            _compute_quarter_end_adj(_QUARTER_END_MID_THRESHOLD),
            _QUARTER_END_MID_ADJ,
        )

    def test_between_thresholds(self):
        self.assertAlmostEqual(_compute_quarter_end_adj(70), _QUARTER_END_MID_ADJ)

    def test_at_high_threshold(self):
        self.assertAlmostEqual(
            _compute_quarter_end_adj(_QUARTER_END_HIGH_THRESHOLD),
            _QUARTER_END_HIGH_ADJ,
        )

    def test_at_end_of_quarter(self):
        self.assertAlmostEqual(_compute_quarter_end_adj(90), _QUARTER_END_HIGH_ADJ)

    def test_high_adj_greater_than_mid_adj(self):
        self.assertGreater(_QUARTER_END_HIGH_ADJ, _QUARTER_END_MID_ADJ)


# ---------------------------------------------------------------------------
# 12. _compute_reversion_probability_pct
# ---------------------------------------------------------------------------

class TestReversionProbability(unittest.TestCase):
    def test_ratio_1_low_base(self):
        # ratio=1.0 → ratio_comp=0; base from yield+market+quarter
        result = _compute_reversion_probability_pct(
            1.0, "lending_interest", "sideways", 0
        )
        expected = 0.0 + 5.0 + 5.0 + 0.0  # 10
        self.assertAlmostEqual(result, expected, places=2)

    def test_high_ratio_increases_probability(self):
        low = _compute_reversion_probability_pct(1.1, "trading_fees", "sideways", 0)
        high = _compute_reversion_probability_pct(2.0, "trading_fees", "sideways", 0)
        self.assertGreater(high, low)

    def test_points_type_increases_probability(self):
        p1 = _compute_reversion_probability_pct(1.5, "staking_rewards", "sideways", 0)
        p2 = _compute_reversion_probability_pct(1.5, "points", "sideways", 0)
        self.assertGreater(p2, p1)

    def test_bull_increases_probability(self):
        p_bear = _compute_reversion_probability_pct(1.5, "trading_fees", "bear", 0)
        p_bull = _compute_reversion_probability_pct(1.5, "trading_fees", "bull", 0)
        self.assertGreaterEqual(p_bull, p_bear)

    def test_quarter_end_increases_probability(self):
        p_early = _compute_reversion_probability_pct(
            1.5, "trading_fees", "sideways", 10
        )
        p_late = _compute_reversion_probability_pct(
            1.5, "trading_fees", "sideways", 80
        )
        self.assertGreater(p_late, p_early)

    def test_max_capped_at_99(self):
        result = _compute_reversion_probability_pct(
            10.0, "points", "high_volatility", 90
        )
        self.assertLessEqual(result, 99.0)

    def test_min_is_nonnegative(self):
        result = _compute_reversion_probability_pct(
            0.0, "lending_interest", "bear", 0
        )
        self.assertGreaterEqual(result, 0.0)

    def test_returns_float(self):
        result = _compute_reversion_probability_pct(
            1.5, "trading_fees", "bull", 30
        )
        self.assertIsInstance(result, float)

    def test_full_saturation_scenario(self):
        # ratio=3.0 → ratio_comp=60; points=20; high_vol=12; q_end=5 → 97
        result = _compute_reversion_probability_pct(
            3.0, "points", "high_volatility", 80
        )
        self.assertAlmostEqual(result, 97.0, places=2)

    def test_moderate_scenario(self):
        # ratio=2.0 → excess=1.0 → frac=0.5 → 30; trading_fees=10; bull=10; day30=0 → 50
        result = _compute_reversion_probability_pct(
            2.0, "trading_fees", "bull", 30
        )
        self.assertAlmostEqual(result, 50.0, places=2)


# ---------------------------------------------------------------------------
# 13. _compute_seasonality_label
# ---------------------------------------------------------------------------

class TestSeasonalityLabel(unittest.TestCase):
    def test_ratio_1_stable(self):
        self.assertEqual(_compute_seasonality_label(1.0), "STABLE_YIELD")

    def test_ratio_1_1_stable_boundary(self):
        self.assertEqual(_compute_seasonality_label(1.1), "STABLE_YIELD")

    def test_ratio_1_11_slightly_elevated(self):
        self.assertEqual(_compute_seasonality_label(1.11), "SLIGHTLY_ELEVATED")

    def test_ratio_1_3_slightly_elevated_boundary(self):
        self.assertEqual(_compute_seasonality_label(1.3), "SLIGHTLY_ELEVATED")

    def test_ratio_1_31_elevated(self):
        self.assertEqual(_compute_seasonality_label(1.31), "ELEVATED_LIKELY_REVERTING")

    def test_ratio_1_7_elevated_boundary(self):
        self.assertEqual(_compute_seasonality_label(1.7), "ELEVATED_LIKELY_REVERTING")

    def test_ratio_1_71_spike(self):
        self.assertEqual(_compute_seasonality_label(1.71), "SPIKE_EXPECT_REVERSION")

    def test_ratio_2_5_spike_boundary(self):
        self.assertEqual(_compute_seasonality_label(2.5), "SPIKE_EXPECT_REVERSION")

    def test_ratio_2_51_unsustainable(self):
        self.assertEqual(_compute_seasonality_label(2.51), "UNSUSTAINABLE_SPIKE")

    def test_ratio_10_unsustainable(self):
        self.assertEqual(_compute_seasonality_label(10.0), "UNSUSTAINABLE_SPIKE")

    def test_all_valid_labels(self):
        valid = {
            "STABLE_YIELD",
            "SLIGHTLY_ELEVATED",
            "ELEVATED_LIKELY_REVERTING",
            "SPIKE_EXPECT_REVERSION",
            "UNSUSTAINABLE_SPIKE",
        }
        for ratio in [0.5, 1.0, 1.1, 1.2, 1.5, 1.7, 2.0, 2.5, 3.0]:
            self.assertIn(_compute_seasonality_label(ratio), valid)

    def test_ratio_below_1_stable(self):
        # Below 1.0 means current below 90d avg → definitely stable
        self.assertEqual(_compute_seasonality_label(0.8), "STABLE_YIELD")


# ---------------------------------------------------------------------------
# 14. Analyzer.analyze — output structure and values
# ---------------------------------------------------------------------------

class TestAnalyzerAnalyze(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_log.json")
        self.analyzer = ProtocolDeFiYieldSeasonalityAnalyzer(
            log_path=self.log_path
        )

    def test_returns_dict(self):
        result = self.analyzer.analyze(make_data(), write_log=False)
        self.assertIsInstance(result, dict)

    def test_all_expected_keys_present(self):
        result = self.analyzer.analyze(make_data(), write_log=False)
        expected_keys = {
            "protocol_name",
            "yield_type",
            "market_condition",
            "apy_vs_30d_ratio",
            "apy_vs_90d_ratio",
            "apy_vs_180d_ratio",
            "is_above_all_averages",
            "reversion_probability_pct",
            "expected_normalized_apy_pct",
            "seasonality_label",
            "analyzed_at",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_protocol_name_echoed(self):
        result = self.analyzer.analyze(
            make_data(protocol_name="CurveFinance"), write_log=False
        )
        self.assertEqual(result["protocol_name"], "CurveFinance")

    def test_yield_type_echoed(self):
        result = self.analyzer.analyze(
            make_data(yield_type="emissions"), write_log=False
        )
        self.assertEqual(result["yield_type"], "emissions")

    def test_market_condition_echoed(self):
        result = self.analyzer.analyze(
            make_data(market_condition="bear"), write_log=False
        )
        self.assertEqual(result["market_condition"], "bear")

    def test_30d_ratio_correct(self):
        result = self.analyzer.analyze(
            make_data(current_apy_pct=12.5, apy_30d_avg_pct=8.0), write_log=False
        )
        self.assertAlmostEqual(result["apy_vs_30d_ratio"], 12.5 / 8.0, places=5)

    def test_90d_ratio_correct(self):
        result = self.analyzer.analyze(
            make_data(current_apy_pct=12.5, apy_90d_avg_pct=7.0), write_log=False
        )
        self.assertAlmostEqual(result["apy_vs_90d_ratio"], 12.5 / 7.0, places=5)

    def test_180d_ratio_correct(self):
        result = self.analyzer.analyze(
            make_data(current_apy_pct=12.5, apy_180d_avg_pct=6.5), write_log=False
        )
        self.assertAlmostEqual(result["apy_vs_180d_ratio"], 12.5 / 6.5, places=5)

    def test_is_above_all_true(self):
        result = self.analyzer.analyze(
            make_data(
                current_apy_pct=15.0,
                apy_30d_avg_pct=8.0,
                apy_90d_avg_pct=7.0,
                apy_180d_avg_pct=6.5,
            ),
            write_log=False,
        )
        self.assertTrue(result["is_above_all_averages"])

    def test_is_above_all_false(self):
        result = self.analyzer.analyze(
            make_data(
                current_apy_pct=5.0,
                apy_30d_avg_pct=8.0,
                apy_90d_avg_pct=7.0,
                apy_180d_avg_pct=6.5,
            ),
            write_log=False,
        )
        self.assertFalse(result["is_above_all_averages"])

    def test_normalized_apy_correct(self):
        result = self.analyzer.analyze(
            make_data(apy_30d_avg_pct=8.0, apy_90d_avg_pct=7.0, apy_180d_avg_pct=6.5),
            write_log=False,
        )
        expected = _compute_expected_normalized_apy_pct(8.0, 7.0, 6.5)
        self.assertAlmostEqual(result["expected_normalized_apy_pct"], expected, places=5)

    def test_seasonality_label_valid(self):
        valid_labels = {
            "STABLE_YIELD",
            "SLIGHTLY_ELEVATED",
            "ELEVATED_LIKELY_REVERTING",
            "SPIKE_EXPECT_REVERSION",
            "UNSUSTAINABLE_SPIKE",
        }
        result = self.analyzer.analyze(make_data(), write_log=False)
        self.assertIn(result["seasonality_label"], valid_labels)

    def test_analyzed_at_is_iso(self):
        result = self.analyzer.analyze(make_data(), write_log=False)
        from datetime import datetime
        datetime.fromisoformat(result["analyzed_at"].replace("Z", "+00:00"))

    def test_write_log_true_creates_file(self):
        self.analyzer.analyze(make_data())
        self.assertTrue(os.path.exists(self.log_path))

    def test_write_log_false_no_file(self):
        self.analyzer.analyze(make_data(), write_log=False)
        self.assertFalse(os.path.exists(self.log_path))

    def test_missing_keys_defaults(self):
        result = self.analyzer.analyze({}, write_log=False)
        self.assertEqual(result["protocol_name"], "unknown")
        self.assertIn("seasonality_label", result)

    def test_zero_avg_ratio_fallback(self):
        result = self.analyzer.analyze(
            make_data(
                current_apy_pct=10.0,
                apy_30d_avg_pct=0.0,
                apy_90d_avg_pct=0.0,
                apy_180d_avg_pct=0.0,
            ),
            write_log=False,
        )
        self.assertAlmostEqual(result["apy_vs_90d_ratio"], 1.0)

    def test_stable_scenario_label(self):
        # current = 90d avg → ratio = 1.0 → STABLE_YIELD
        result = self.analyzer.analyze(
            make_data(
                current_apy_pct=7.0,
                apy_30d_avg_pct=7.0,
                apy_90d_avg_pct=7.0,
                apy_180d_avg_pct=7.0,
            ),
            write_log=False,
        )
        self.assertEqual(result["seasonality_label"], "STABLE_YIELD")

    def test_unsustainable_spike_scenario(self):
        # current = 3x the 90d avg
        result = self.analyzer.analyze(
            make_data(
                current_apy_pct=21.0,
                apy_90d_avg_pct=7.0,
            ),
            write_log=False,
        )
        self.assertEqual(result["seasonality_label"], "UNSUSTAINABLE_SPIKE")

    def test_reversion_probability_is_float(self):
        result = self.analyzer.analyze(make_data(), write_log=False)
        self.assertIsInstance(result["reversion_probability_pct"], float)


# ---------------------------------------------------------------------------
# 15. _atomic_append_log
# ---------------------------------------------------------------------------

class TestAtomicAppendLog(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_log.json")

    def test_creates_file_on_first_write(self):
        _atomic_append_log(self.log_path, {"k": "v"})
        self.assertTrue(os.path.exists(self.log_path))

    def test_file_is_valid_json(self):
        _atomic_append_log(self.log_path, {"k": "v"})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_appends_multiple_entries(self):
        for i in range(3):
            _atomic_append_log(self.log_path, {"i": i})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_entry_content_preserved(self):
        entry = {"protocol": "aave", "ratio": 1.5}
        _atomic_append_log(self.log_path, entry)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["protocol"], "aave")
        self.assertAlmostEqual(data[0]["ratio"], 1.5)

    def test_handles_corrupted_file(self):
        with open(self.log_path, "w") as f:
            f.write("{corrupted{{")
        _atomic_append_log(self.log_path, {"k": "v"})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_handles_missing_file(self):
        _atomic_append_log(self.log_path, {"k": "v"})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_creates_parent_dirs(self):
        deep_path = os.path.join(self.tmp_dir, "a", "b", "c", "log.json")
        _atomic_append_log(deep_path, {"k": "v"})
        self.assertTrue(os.path.exists(deep_path))

    def test_preserves_order(self):
        for i in range(6):
            _atomic_append_log(self.log_path, {"idx": i})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual([d["idx"] for d in data], list(range(6)))

    def test_cap_enforced(self):
        for i in range(15):
            _atomic_append_log(self.log_path, {"i": i}, cap=10)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 10)

    def test_non_list_json_replaced(self):
        with open(self.log_path, "w") as f:
            json.dump({"not": "a list"}, f)
        _atomic_append_log(self.log_path, {"k": "v"})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


# ---------------------------------------------------------------------------
# 16. Ring-buffer cap
# ---------------------------------------------------------------------------

class TestLogCap(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "cap_test.json")
        self.analyzer = ProtocolDeFiYieldSeasonalityAnalyzer(
            log_path=self.log_path
        )

    def test_cap_is_100(self):
        self.assertEqual(_LOG_CAP, 100)

    def test_log_never_exceeds_cap(self):
        for i in range(115):
            self.analyzer.analyze(make_data(protocol_name=f"P{i}"))
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), _LOG_CAP)

    def test_oldest_entries_dropped(self):
        for i in range(105):
            _atomic_append_log(self.log_path, {"idx": i})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["idx"], 5)

    def test_exactly_cap_entries_preserved(self):
        for i in range(_LOG_CAP):
            _atomic_append_log(self.log_path, {"idx": i})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_CAP)


if __name__ == "__main__":
    unittest.main()
