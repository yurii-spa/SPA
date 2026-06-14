"""
Tests for MP-1104: DeFiProtocolTotalValueAtRiskAggregator

Run: python3 -m unittest spa_core.tests.test_defi_protocol_total_value_at_risk_aggregator
"""

import json
import math
import os
import tempfile
import unittest

from spa_core.analytics.defi_protocol_total_value_at_risk_aggregator import (
    DeFiProtocolTotalValueAtRiskAggregator,
    CORR_INDEPENDENT,
    CORR_MODERATE,
    CORR_HIGH,
    CORRELATION_MAP,
    Z_SCORE_95,
    Z_SCORE_99,
    LABEL_LOW_RISK,
    LABEL_MODERATE_RISK,
    LABEL_ELEVATED_RISK,
    LABEL_HIGH_RISK,
    LABEL_EXTREME_RISK,
    RING_BUFFER_CAP,
    get_z_score,
    get_correlation,
    compute_individual_var,
    compute_portfolio_var,
    get_risk_label,
    compute_risk_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(asset="USDC", value_usd=10_000.0, daily_volatility_pct=1.0):
    return {"asset": asset, "value_usd": value_usd, "daily_volatility_pct": daily_volatility_pct}


def _make_aggregator(tmp_dir=None):
    if tmp_dir is None:
        tmp_dir = tempfile.mkdtemp()
    log_file = os.path.join(tmp_dir, "test_var_log.json")
    return DeFiProtocolTotalValueAtRiskAggregator(data_file=log_file), log_file


# ---------------------------------------------------------------------------
# 1. Initialization tests
# ---------------------------------------------------------------------------

class TestInit(unittest.TestCase):

    def test_default_data_file_set(self):
        agg = DeFiProtocolTotalValueAtRiskAggregator()
        self.assertIn("total_value_at_risk_log.json", agg._data_file)

    def test_custom_data_file(self):
        agg = DeFiProtocolTotalValueAtRiskAggregator(data_file="/tmp/test_var.json")
        self.assertEqual(agg._data_file, "/tmp/test_var.json")

    def test_data_file_none_uses_default(self):
        agg = DeFiProtocolTotalValueAtRiskAggregator(data_file=None)
        self.assertTrue(agg._data_file.endswith("total_value_at_risk_log.json"))

    def test_instance_type(self):
        agg = DeFiProtocolTotalValueAtRiskAggregator()
        self.assertIsInstance(agg, DeFiProtocolTotalValueAtRiskAggregator)

    def test_ring_buffer_cap_constant(self):
        self.assertEqual(RING_BUFFER_CAP, 100)


# ---------------------------------------------------------------------------
# 2. Z-score helper tests
# ---------------------------------------------------------------------------

class TestZScore(unittest.TestCase):

    def test_95_returns_1645(self):
        self.assertAlmostEqual(get_z_score(95.0), 1.645)

    def test_99_returns_2326(self):
        self.assertAlmostEqual(get_z_score(99.0), 2.326)

    def test_below_99_returns_95_z(self):
        self.assertAlmostEqual(get_z_score(97.0), 1.645)

    def test_exactly_99_returns_99_z(self):
        self.assertAlmostEqual(get_z_score(99.0), Z_SCORE_99)

    def test_90_returns_95_z(self):
        self.assertAlmostEqual(get_z_score(90.0), Z_SCORE_95)

    def test_z_score_95_constant_value(self):
        self.assertEqual(Z_SCORE_95, 1.645)

    def test_z_score_99_constant_value(self):
        self.assertEqual(Z_SCORE_99, 2.326)

    def test_z_99_greater_than_z_95(self):
        self.assertGreater(Z_SCORE_99, Z_SCORE_95)


# ---------------------------------------------------------------------------
# 3. Correlation helper tests
# ---------------------------------------------------------------------------

class TestCorrelation(unittest.TestCase):

    def test_independent_zero(self):
        self.assertAlmostEqual(get_correlation("independent"), 0.0)

    def test_moderate_point_three(self):
        self.assertAlmostEqual(get_correlation("moderate"), 0.3)

    def test_high_point_seven(self):
        self.assertAlmostEqual(get_correlation("high"), 0.7)

    def test_case_insensitive_independent(self):
        self.assertAlmostEqual(get_correlation("INDEPENDENT"), 0.0)

    def test_case_insensitive_moderate(self):
        self.assertAlmostEqual(get_correlation("MODERATE"), 0.3)

    def test_case_insensitive_high(self):
        self.assertAlmostEqual(get_correlation("HIGH"), 0.7)

    def test_unknown_falls_back_to_moderate(self):
        self.assertAlmostEqual(get_correlation("unknown_corr"), 0.3)

    def test_correlation_map_has_three_keys(self):
        self.assertEqual(len(CORRELATION_MAP), 3)

    def test_corr_independent_constant(self):
        self.assertEqual(CORR_INDEPENDENT, 0.0)

    def test_corr_moderate_constant(self):
        self.assertEqual(CORR_MODERATE, 0.3)

    def test_corr_high_constant(self):
        self.assertEqual(CORR_HIGH, 0.7)


# ---------------------------------------------------------------------------
# 4. Individual VaR computation tests
# ---------------------------------------------------------------------------

class TestIndividualVar(unittest.TestCase):

    def test_basic_formula_1day(self):
        # value=100000, vol=1%, z=1.645, days=1
        expected = 100_000.0 * 0.01 * 1.645 * 1.0
        self.assertAlmostEqual(compute_individual_var(100_000.0, 1.0, 1.645, 1), expected)

    def test_zero_value_returns_zero(self):
        self.assertAlmostEqual(compute_individual_var(0.0, 1.0, 1.645, 1), 0.0)

    def test_zero_volatility_returns_zero(self):
        self.assertAlmostEqual(compute_individual_var(10_000.0, 0.0, 1.645, 1), 0.0)

    def test_multi_day_scaling(self):
        var_1d = compute_individual_var(10_000.0, 2.0, 1.645, 1)
        var_4d = compute_individual_var(10_000.0, 2.0, 1.645, 4)
        self.assertAlmostEqual(var_4d, var_1d * 2.0, places=6)

    def test_ten_day_scaling(self):
        var_1d = compute_individual_var(10_000.0, 1.0, 1.645, 1)
        var_10d = compute_individual_var(10_000.0, 1.0, 1.645, 10)
        self.assertAlmostEqual(var_10d, var_1d * math.sqrt(10), places=6)

    def test_higher_z_gives_higher_var(self):
        v95 = compute_individual_var(10_000.0, 1.0, Z_SCORE_95, 1)
        v99 = compute_individual_var(10_000.0, 1.0, Z_SCORE_99, 1)
        self.assertGreater(v99, v95)

    def test_higher_volatility_gives_higher_var(self):
        v_low = compute_individual_var(10_000.0, 1.0, 1.645, 1)
        v_high = compute_individual_var(10_000.0, 3.0, 1.645, 1)
        self.assertGreater(v_high, v_low)

    def test_proportional_to_value(self):
        v1 = compute_individual_var(10_000.0, 2.0, 1.645, 1)
        v2 = compute_individual_var(20_000.0, 2.0, 1.645, 1)
        self.assertAlmostEqual(v2, v1 * 2.0, places=6)

    def test_days_minimum_1(self):
        var_0 = compute_individual_var(10_000.0, 1.0, 1.645, 0)
        var_1 = compute_individual_var(10_000.0, 1.0, 1.645, 1)
        self.assertAlmostEqual(var_0, var_1, places=6)

    def test_large_position(self):
        result = compute_individual_var(1_000_000.0, 5.0, 1.645, 1)
        self.assertGreater(result, 0.0)


# ---------------------------------------------------------------------------
# 5. Portfolio VaR computation tests
# ---------------------------------------------------------------------------

class TestPortfolioVar(unittest.TestCase):

    def test_single_asset_equals_individual(self):
        v = [500.0]
        self.assertAlmostEqual(compute_portfolio_var(v, 0.0), 500.0, places=6)

    def test_empty_list_returns_zero(self):
        self.assertAlmostEqual(compute_portfolio_var([], 0.0), 0.0)

    def test_independent_is_quadrature(self):
        vars_ = [300.0, 400.0]
        expected = math.sqrt(300.0**2 + 400.0**2)
        self.assertAlmostEqual(compute_portfolio_var(vars_, 0.0), expected, places=6)

    def test_perfect_corr_equals_sum(self):
        vars_ = [100.0, 200.0, 300.0]
        # corr=1 -> port_var = sum
        result = compute_portfolio_var(vars_, 1.0)
        self.assertAlmostEqual(result, 600.0, places=4)

    def test_moderate_between_quad_and_sum(self):
        vars_ = [100.0, 200.0]
        quad = math.sqrt(100.0**2 + 200.0**2)
        total = 300.0
        port = compute_portfolio_var(vars_, 0.3)
        self.assertGreater(port, quad)
        self.assertLess(port, total)

    def test_high_corr_between_quad_and_sum(self):
        vars_ = [100.0, 200.0]
        quad = math.sqrt(100.0**2 + 200.0**2)
        total = 300.0
        port = compute_portfolio_var(vars_, 0.7)
        self.assertGreater(port, quad)
        self.assertLess(port, total)

    def test_three_equal_positions_independent(self):
        vars_ = [100.0, 100.0, 100.0]
        expected = math.sqrt(3) * 100.0
        self.assertAlmostEqual(compute_portfolio_var(vars_, 0.0), expected, places=6)

    def test_higher_corr_gives_higher_portfolio_var(self):
        vars_ = [200.0, 300.0]
        p_ind = compute_portfolio_var(vars_, 0.0)
        p_mod = compute_portfolio_var(vars_, 0.3)
        p_high = compute_portfolio_var(vars_, 0.7)
        self.assertLess(p_ind, p_mod)
        self.assertLess(p_mod, p_high)

    def test_two_identical_independent(self):
        v = [100.0, 100.0]
        expected = math.sqrt(2) * 100.0
        self.assertAlmostEqual(compute_portfolio_var(v, 0.0), expected, places=6)

    def test_result_non_negative(self):
        self.assertGreaterEqual(compute_portfolio_var([50.0, 80.0], 0.3), 0.0)


# ---------------------------------------------------------------------------
# 6. Risk label tests
# ---------------------------------------------------------------------------

class TestRiskLabel(unittest.TestCase):

    def test_zero_pct_is_low(self):
        self.assertEqual(get_risk_label(0.0), LABEL_LOW_RISK)

    def test_point5_pct_is_low(self):
        self.assertEqual(get_risk_label(0.5), LABEL_LOW_RISK)

    def test_just_below_1_is_low(self):
        self.assertEqual(get_risk_label(0.999), LABEL_LOW_RISK)

    def test_exactly_1_is_moderate(self):
        self.assertEqual(get_risk_label(1.0), LABEL_MODERATE_RISK)

    def test_2_pct_is_moderate(self):
        self.assertEqual(get_risk_label(2.0), LABEL_MODERATE_RISK)

    def test_just_below_3_is_moderate(self):
        self.assertEqual(get_risk_label(2.999), LABEL_MODERATE_RISK)

    def test_exactly_3_is_elevated(self):
        self.assertEqual(get_risk_label(3.0), LABEL_ELEVATED_RISK)

    def test_4_pct_is_elevated(self):
        self.assertEqual(get_risk_label(4.0), LABEL_ELEVATED_RISK)

    def test_just_below_5_is_elevated(self):
        self.assertEqual(get_risk_label(4.999), LABEL_ELEVATED_RISK)

    def test_exactly_5_is_high(self):
        self.assertEqual(get_risk_label(5.0), LABEL_HIGH_RISK)

    def test_7_pct_is_high(self):
        self.assertEqual(get_risk_label(7.0), LABEL_HIGH_RISK)

    def test_just_below_10_is_high(self):
        self.assertEqual(get_risk_label(9.999), LABEL_HIGH_RISK)

    def test_exactly_10_is_extreme(self):
        self.assertEqual(get_risk_label(10.0), LABEL_EXTREME_RISK)

    def test_20_pct_is_extreme(self):
        self.assertEqual(get_risk_label(20.0), LABEL_EXTREME_RISK)

    def test_100_pct_is_extreme(self):
        self.assertEqual(get_risk_label(100.0), LABEL_EXTREME_RISK)


# ---------------------------------------------------------------------------
# 7. Risk score tests
# ---------------------------------------------------------------------------

class TestRiskScore(unittest.TestCase):

    def test_zero_pct_returns_0(self):
        self.assertEqual(compute_risk_score(0.0), 0)

    def test_score_in_range(self):
        for pct in [0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 15.0, 20.0]:
            score = compute_risk_score(pct)
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_increasing_pct_increasing_score(self):
        scores = [compute_risk_score(p) for p in [0.0, 1.0, 3.0, 5.0, 10.0, 20.0]]
        for i in range(len(scores) - 1):
            self.assertLessEqual(scores[i], scores[i + 1])

    def test_low_risk_band_under_20(self):
        # var_pct in [0, 1) -> score in [0, 20)
        score = compute_risk_score(0.5)
        self.assertGreaterEqual(score, 0)
        self.assertLess(score, 20)

    def test_moderate_band_20_to_40(self):
        score = compute_risk_score(2.0)  # midpoint of [1,3)
        self.assertGreaterEqual(score, 20)
        self.assertLess(score, 40)

    def test_elevated_band_40_to_60(self):
        score = compute_risk_score(4.0)
        self.assertGreaterEqual(score, 40)
        self.assertLess(score, 60)

    def test_high_band_60_to_80(self):
        score = compute_risk_score(7.5)
        self.assertGreaterEqual(score, 60)
        self.assertLess(score, 80)

    def test_extreme_band_80_plus(self):
        score = compute_risk_score(12.0)
        self.assertGreaterEqual(score, 80)
        self.assertLessEqual(score, 100)

    def test_negative_pct_returns_0(self):
        self.assertEqual(compute_risk_score(-1.0), 0)

    def test_very_large_pct_capped_100(self):
        self.assertEqual(compute_risk_score(1000.0), 100)


# ---------------------------------------------------------------------------
# 8. Output keys tests
# ---------------------------------------------------------------------------

class TestOutputKeys(unittest.TestCase):

    def setUp(self):
        self.agg, _ = _make_aggregator()
        self.result = self.agg.aggregate([_pos()])

    def test_protocol_name_present(self):
        self.assertIn("protocol_name", self.result)

    def test_total_portfolio_usd_present(self):
        self.assertIn("total_portfolio_usd", self.result)

    def test_individual_var_usd_present(self):
        self.assertIn("individual_var_usd", self.result)

    def test_portfolio_var_usd_present(self):
        self.assertIn("portfolio_var_usd", self.result)

    def test_diversification_benefit_usd_present(self):
        self.assertIn("diversification_benefit_usd", self.result)

    def test_var_pct_of_portfolio_present(self):
        self.assertIn("var_pct_of_portfolio", self.result)

    def test_largest_risk_contributor_present(self):
        self.assertIn("largest_risk_contributor", self.result)

    def test_risk_level_score_present(self):
        self.assertIn("risk_level_score", self.result)

    def test_risk_label_present(self):
        self.assertIn("risk_label", self.result)

    def test_confidence_level_pct_present(self):
        self.assertIn("confidence_level_pct", self.result)

    def test_holding_days_present(self):
        self.assertIn("holding_days", self.result)

    def test_correlation_assumption_present(self):
        self.assertIn("correlation_assumption", self.result)

    def test_correlation_value_present(self):
        self.assertIn("correlation_value", self.result)

    def test_z_score_present(self):
        self.assertIn("z_score", self.result)

    def test_position_count_present(self):
        self.assertIn("position_count", self.result)

    def test_run_ts_present(self):
        self.assertIn("run_ts", self.result)


# ---------------------------------------------------------------------------
# 9. Aggregate method value tests
# ---------------------------------------------------------------------------

class TestAggregateValues(unittest.TestCase):

    def setUp(self):
        self.agg, _ = _make_aggregator()

    def test_total_portfolio_correct(self):
        positions = [_pos(value_usd=30_000.0), _pos(value_usd=70_000.0)]
        r = self.agg.aggregate(positions)
        self.assertAlmostEqual(r["total_portfolio_usd"], 100_000.0, places=4)

    def test_position_count_correct(self):
        r = self.agg.aggregate([_pos(), _pos(), _pos()])
        self.assertEqual(r["position_count"], 3)

    def test_empty_positions(self):
        r = self.agg.aggregate([])
        self.assertEqual(r["position_count"], 0)
        self.assertAlmostEqual(r["total_portfolio_usd"], 0.0)
        self.assertAlmostEqual(r["portfolio_var_usd"], 0.0)
        self.assertAlmostEqual(r["var_pct_of_portfolio"], 0.0)

    def test_single_position_no_diversification(self):
        r = self.agg.aggregate([_pos(value_usd=10_000.0, daily_volatility_pct=2.0)],
                                confidence_level_pct=95.0, holding_days=1,
                                correlation_assumption="moderate")
        expected_ivar = 10_000.0 * 0.02 * Z_SCORE_95 * 1.0
        self.assertAlmostEqual(r["individual_var_usd"], expected_ivar, places=4)
        self.assertAlmostEqual(r["portfolio_var_usd"], expected_ivar, places=4)
        self.assertAlmostEqual(r["diversification_benefit_usd"], 0.0, places=4)

    def test_independent_diversification_benefit_positive(self):
        positions = [_pos("A", 50_000.0, 2.0), _pos("B", 50_000.0, 2.0)]
        r = self.agg.aggregate(positions, correlation_assumption="independent")
        self.assertGreater(r["diversification_benefit_usd"], 0.0)

    def test_high_corr_less_diversification_than_moderate(self):
        positions = [_pos("A", 50_000.0, 2.0), _pos("B", 50_000.0, 2.0)]
        r_mod = self.agg.aggregate(positions, correlation_assumption="moderate")
        r_high = self.agg.aggregate(positions, correlation_assumption="high")
        self.assertGreater(r_high["portfolio_var_usd"], r_mod["portfolio_var_usd"])

    def test_99_confidence_gives_higher_var(self):
        positions = [_pos(value_usd=50_000.0, daily_volatility_pct=2.0)]
        r95 = self.agg.aggregate(positions, confidence_level_pct=95.0)
        r99 = self.agg.aggregate(positions, confidence_level_pct=99.0)
        self.assertGreater(r99["portfolio_var_usd"], r95["portfolio_var_usd"])

    def test_10_day_var_greater_than_1_day(self):
        positions = [_pos(value_usd=50_000.0, daily_volatility_pct=2.0)]
        r1 = self.agg.aggregate(positions, holding_days=1)
        r10 = self.agg.aggregate(positions, holding_days=10)
        self.assertGreater(r10["portfolio_var_usd"], r1["portfolio_var_usd"])

    def test_largest_risk_contributor_is_highest_vol_asset(self):
        positions = [
            _pos("LOW_VOL", 50_000.0, 0.5),
            _pos("HIGH_VOL", 50_000.0, 5.0),
        ]
        r = self.agg.aggregate(positions)
        self.assertEqual(r["largest_risk_contributor"], "HIGH_VOL")

    def test_var_pct_correct_calculation(self):
        positions = [_pos(value_usd=100_000.0, daily_volatility_pct=2.0)]
        r = self.agg.aggregate(positions, confidence_level_pct=95.0, holding_days=1,
                                correlation_assumption="independent")
        expected_var = 100_000.0 * 0.02 * Z_SCORE_95
        expected_pct = expected_var / 100_000.0 * 100.0
        self.assertAlmostEqual(r["var_pct_of_portfolio"], expected_pct, places=4)

    def test_risk_score_int_type(self):
        r = self.agg.aggregate([_pos()])
        self.assertIsInstance(r["risk_level_score"], int)

    def test_risk_score_in_bounds(self):
        r = self.agg.aggregate([_pos()])
        self.assertGreaterEqual(r["risk_level_score"], 0)
        self.assertLessEqual(r["risk_level_score"], 100)

    def test_protocol_name_stored(self):
        r = self.agg.aggregate([_pos()], protocol_name="AaveV3")
        self.assertEqual(r["protocol_name"], "AaveV3")

    def test_z_score_stored_correctly_95(self):
        r = self.agg.aggregate([_pos()], confidence_level_pct=95.0)
        self.assertAlmostEqual(r["z_score"], Z_SCORE_95)

    def test_z_score_stored_correctly_99(self):
        r = self.agg.aggregate([_pos()], confidence_level_pct=99.0)
        self.assertAlmostEqual(r["z_score"], Z_SCORE_99)

    def test_correlation_value_stored(self):
        r = self.agg.aggregate([_pos()], correlation_assumption="high")
        self.assertAlmostEqual(r["correlation_value"], 0.7)

    def test_run_ts_is_string(self):
        r = self.agg.aggregate([_pos()])
        self.assertIsInstance(r["run_ts"], str)

    def test_diversification_benefit_non_negative(self):
        positions = [_pos("A", 40_000.0, 2.0), _pos("B", 60_000.0, 3.0)]
        r = self.agg.aggregate(positions, correlation_assumption="moderate")
        self.assertGreaterEqual(r["diversification_benefit_usd"], 0.0)

    def test_holding_days_stored(self):
        r = self.agg.aggregate([_pos()], holding_days=5)
        self.assertEqual(r["holding_days"], 5)

    def test_minimum_holding_days_1(self):
        r = self.agg.aggregate([_pos()], holding_days=0)
        self.assertEqual(r["holding_days"], 1)

    def test_three_positions_aggregated(self):
        positions = [
            _pos("A", 30_000.0, 1.5),
            _pos("B", 40_000.0, 2.0),
            _pos("C", 30_000.0, 1.0),
        ]
        r = self.agg.aggregate(positions, correlation_assumption="independent")
        self.assertEqual(r["position_count"], 3)
        self.assertAlmostEqual(r["total_portfolio_usd"], 100_000.0, places=4)

    def test_risk_label_low_for_small_var(self):
        # Very small volatility → low var_pct → LOW_RISK
        r = self.agg.aggregate([_pos(value_usd=100_000.0, daily_volatility_pct=0.01)])
        self.assertEqual(r["risk_label"], LABEL_LOW_RISK)

    def test_risk_label_extreme_for_large_vol(self):
        # Very high volatility → high var_pct → EXTREME_RISK
        r = self.agg.aggregate([_pos(value_usd=100_000.0, daily_volatility_pct=20.0)])
        self.assertEqual(r["risk_label"], LABEL_EXTREME_RISK)

    def test_empty_largest_contributor_for_empty_positions(self):
        r = self.agg.aggregate([])
        self.assertEqual(r["largest_risk_contributor"], "")


# ---------------------------------------------------------------------------
# 10. Log file / ring-buffer tests
# ---------------------------------------------------------------------------

class TestLogFile(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "var_log.json")
        self.agg = DeFiProtocolTotalValueAtRiskAggregator(data_file=self.log_file)

    def test_save_creates_file(self):
        result = self.agg.aggregate([_pos()])
        self.agg.save_result(result)
        self.assertTrue(os.path.exists(self.log_file))

    def test_saved_file_is_valid_json(self):
        result = self.agg.aggregate([_pos()])
        self.agg.save_result(result)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_save_appends_entries(self):
        for _ in range(3):
            self.agg.save_result(self.agg.aggregate([_pos()]))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_caps_at_100(self):
        for _ in range(RING_BUFFER_CAP + 10):
            self.agg.save_result(self.agg.aggregate([_pos()]))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), RING_BUFFER_CAP)

    def test_ring_buffer_keeps_most_recent(self):
        for i in range(RING_BUFFER_CAP + 5):
            r = self.agg.aggregate([_pos()], protocol_name=f"p{i}")
            self.agg.save_result(r)
        with open(self.log_file) as f:
            data = json.load(f)
        # Last entry should be the most recent
        self.assertEqual(data[-1]["protocol_name"], f"p{RING_BUFFER_CAP + 4}")

    def test_save_on_missing_dir_creates_dir(self):
        sub_dir = os.path.join(self.tmp_dir, "subdir")
        agg2 = DeFiProtocolTotalValueAtRiskAggregator(
            data_file=os.path.join(sub_dir, "var_log.json")
        )
        result = agg2.aggregate([_pos()])
        agg2.save_result(result)
        self.assertTrue(os.path.exists(os.path.join(sub_dir, "var_log.json")))

    def test_saved_entry_has_protocol_name(self):
        result = self.agg.aggregate([_pos()], protocol_name="TestProtocol")
        self.agg.save_result(result)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(data[0]["protocol_name"], "TestProtocol")

    def test_corrupted_log_is_reset(self):
        with open(self.log_file, "w") as f:
            f.write("not valid json {{{")
        result = self.agg.aggregate([_pos()])
        self.agg.save_result(result)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_non_list_log_is_reset(self):
        with open(self.log_file, "w") as f:
            json.dump({"bad": "format"}, f)
        result = self.agg.aggregate([_pos()])
        self.agg.save_result(result)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_atomic_write_no_partial_file(self):
        result = self.agg.aggregate([_pos()])
        self.agg.save_result(result)
        # No .tmp files should remain
        tmp_files = [f for f in os.listdir(self.tmp_dir) if f.endswith(".tmp")]
        self.assertEqual(len(tmp_files), 0)


# ---------------------------------------------------------------------------
# 11. Edge-case / boundary tests
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.agg, _ = _make_aggregator()

    def test_all_zero_values(self):
        r = self.agg.aggregate([_pos(value_usd=0.0, daily_volatility_pct=0.0)])
        self.assertAlmostEqual(r["total_portfolio_usd"], 0.0)
        self.assertAlmostEqual(r["portfolio_var_usd"], 0.0)

    def test_very_large_position(self):
        r = self.agg.aggregate([_pos(value_usd=1e12, daily_volatility_pct=1.0)])
        self.assertGreater(r["portfolio_var_usd"], 0.0)

    def test_many_small_positions(self):
        positions = [_pos(f"A{i}", 1_000.0, 1.0) for i in range(50)]
        r = self.agg.aggregate(positions, correlation_assumption="independent")
        self.assertEqual(r["position_count"], 50)
        self.assertAlmostEqual(r["total_portfolio_usd"], 50_000.0, places=4)

    def test_mixed_volatilities(self):
        positions = [
            _pos("STABLE", 50_000.0, 0.01),
            _pos("VOLATILE", 50_000.0, 10.0),
        ]
        r = self.agg.aggregate(positions)
        self.assertEqual(r["largest_risk_contributor"], "VOLATILE")

    def test_holding_days_100(self):
        r = self.agg.aggregate([_pos()], holding_days=100)
        self.assertEqual(r["holding_days"], 100)
        self.assertGreater(r["portfolio_var_usd"], 0.0)

    def test_high_corr_single_position_no_extra_var(self):
        # With one position, correlation has no effect
        r_ind = self.agg.aggregate([_pos()], correlation_assumption="independent")
        r_high = self.agg.aggregate([_pos()], correlation_assumption="high")
        self.assertAlmostEqual(r_ind["portfolio_var_usd"], r_high["portfolio_var_usd"], places=6)

    def test_result_is_dict(self):
        r = self.agg.aggregate([_pos()])
        self.assertIsInstance(r, dict)

    def test_var_pct_zero_when_no_positions(self):
        r = self.agg.aggregate([])
        self.assertAlmostEqual(r["var_pct_of_portfolio"], 0.0)

    def test_diversification_benefit_zero_single_position(self):
        r = self.agg.aggregate([_pos()])
        self.assertAlmostEqual(r["diversification_benefit_usd"], 0.0, places=6)

    def test_two_identical_positions_independent(self):
        positions = [_pos("A", 10_000.0, 2.0), _pos("A2", 10_000.0, 2.0)]
        r = self.agg.aggregate(positions, correlation_assumption="independent")
        ivar_single = compute_individual_var(10_000.0, 2.0, Z_SCORE_95, 1)
        expected_port = math.sqrt(2) * ivar_single
        self.assertAlmostEqual(r["portfolio_var_usd"], expected_port, places=4)

    def test_asset_name_preserved(self):
        r = self.agg.aggregate([_pos(asset="ETH_USDC")])
        self.assertEqual(r["largest_risk_contributor"], "ETH_USDC")

    def test_confidence_level_stored(self):
        r = self.agg.aggregate([_pos()], confidence_level_pct=99.0)
        self.assertAlmostEqual(r["confidence_level_pct"], 99.0)

    def test_negative_volatility_treated_as_given(self):
        # Negative vol is a data quality issue; module uses as-is
        r = self.agg.aggregate([_pos(daily_volatility_pct=-1.0)])
        # portfolio_var_usd will be negative or zero in raw calc
        self.assertIsInstance(r, dict)


if __name__ == "__main__":
    unittest.main()
