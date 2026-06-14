"""
Tests for MP-1025: ProtocolDeFiYieldCurvePositionAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_yield_curve_position_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_yield_curve_position_analyzer import (
    ProtocolDeFiYieldCurvePositionAnalyzer,
    LOG_CAP,
    _DEFAULT_BENCHMARK_RATE_PCT,
    _DURATION_IMMUNE_DAYS,
    _DURATION_SHORT_DAYS,
    _DURATION_MEDIUM_DAYS,
    _POSITIVE_CARRY_THRESHOLD,
    _BENCHMARK_LAGGING_THRESHOLD,
    _ALL_LABELS,
    _ALL_FLAGS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_position(**overrides) -> dict:
    """Return a minimal valid position dict with optional overrides."""
    base = {
        "name": "TestPosition",
        "protocol": "Aave V3",
        "position_type": "variable_rate_lending",
        "effective_duration_days": 1.0,
        "rate_sensitivity_pct": 1.0,
        "current_rate_pct": 6.5,
        "benchmark_rate_pct": 5.25,
        "rate_environment": "stable",
        "notional_value_usd": 100_000.0,
        "collateral_posted_usd": 0.0,
        "refinancing_risk": False,
    }
    base.update(overrides)
    return base


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiYieldCurvePositionAnalyzer(data_dir=self.tmp)


# ===========================================================================
# 1. Duration Risk Score
# ===========================================================================

class TestDurationRiskScore(BaseTest):

    def test_zero_duration_zero_sensitivity_near_zero_score(self):
        score = self.analyzer._compute_duration_risk_score(0.0, 0.0)
        self.assertAlmostEqual(score, 0.0)

    def test_max_duration_max_sensitivity_gives_100(self):
        score = self.analyzer._compute_duration_risk_score(365.0, 10.0)
        self.assertAlmostEqual(score, 100.0, delta=1.0)

    def test_score_bounded_0_100(self):
        s_low = self.analyzer._compute_duration_risk_score(0.0, 0.0)
        s_high = self.analyzer._compute_duration_risk_score(1000.0, 100.0)
        self.assertGreaterEqual(s_low, 0.0)
        self.assertLessEqual(s_high, 100.0)

    def test_high_duration_with_low_sensitivity(self):
        score = self.analyzer._compute_duration_risk_score(365.0, 0.0)
        self.assertGreater(score, 40.0)  # duration contributes 55%

    def test_low_duration_with_high_sensitivity(self):
        score = self.analyzer._compute_duration_risk_score(1.0, 10.0)
        self.assertGreater(score, 30.0)  # sensitivity contributes 45%

    def test_medium_duration_medium_sensitivity(self):
        score = self.analyzer._compute_duration_risk_score(90.0, 3.0)
        self.assertTrue(0.0 < score < 100.0)

    def test_negative_sensitivity_uses_abs_value(self):
        s1 = self.analyzer._compute_duration_risk_score(90.0, 5.0)
        s2 = self.analyzer._compute_duration_risk_score(90.0, -5.0)
        self.assertAlmostEqual(s1, s2, delta=0.01)


# ===========================================================================
# 2. Carry Score
# ===========================================================================

class TestCarryScore(BaseTest):

    def test_lending_positive_carry_high_score(self):
        # current_rate 10% >> benchmark 5.25% → big premium
        score = self.analyzer._compute_carry_score(4.75, "fixed_rate_lending")
        self.assertGreater(score, 50.0)

    def test_lending_negative_carry_low_score(self):
        # current_rate < benchmark
        score = self.analyzer._compute_carry_score(-3.0, "variable_rate_lending")
        self.assertLess(score, 50.0)

    def test_borrowing_negative_premium_good_carry(self):
        # Borrowing at below-benchmark rate → good carry
        score = self.analyzer._compute_carry_score(-3.0, "fixed_rate_borrowing")
        self.assertGreater(score, 50.0)

    def test_carry_score_bounded_0_100(self):
        s1 = self.analyzer._compute_carry_score(100.0, "fixed_rate_lending")
        s2 = self.analyzer._compute_carry_score(-100.0, "fixed_rate_lending")
        self.assertLessEqual(s1, 100.0)
        self.assertGreaterEqual(s2, 0.0)

    def test_lp_stable_treated_symmetrically(self):
        score = self.analyzer._compute_carry_score(0.0, "lp_stable")
        self.assertTrue(0.0 <= score <= 100.0)

    def test_staking_position_carry(self):
        score = self.analyzer._compute_carry_score(2.0, "staking")
        self.assertTrue(0.0 <= score <= 100.0)


# ===========================================================================
# 3. Interest Rate Variance (IRV)
# ===========================================================================

class TestIRV(BaseTest):

    def test_irv_basic_computation(self):
        # 100_000 × 5.0 × 1.0 / 100 = 5000
        irv = self.analyzer._compute_irv_usd(100_000.0, 5.0, 1.0)
        self.assertAlmostEqual(irv, 5000.0)

    def test_irv_zero_notional(self):
        irv = self.analyzer._compute_irv_usd(0.0, 5.0, 1.0)
        self.assertEqual(irv, 0.0)

    def test_irv_zero_sensitivity(self):
        irv = self.analyzer._compute_irv_usd(1_000_000.0, 0.0, 1.0)
        self.assertEqual(irv, 0.0)

    def test_irv_is_positive(self):
        irv = self.analyzer._compute_irv_usd(50_000.0, -3.0, 1.0)
        self.assertGreaterEqual(irv, 0.0)

    def test_irv_scales_with_notional(self):
        irv1 = self.analyzer._compute_irv_usd(100_000.0, 5.0, 1.0)
        irv2 = self.analyzer._compute_irv_usd(200_000.0, 5.0, 1.0)
        self.assertAlmostEqual(irv2, 2 * irv1, delta=0.01)

    def test_irv_scales_with_rate_shock(self):
        irv1 = self.analyzer._compute_irv_usd(100_000.0, 5.0, 1.0)
        irv2 = self.analyzer._compute_irv_usd(100_000.0, 5.0, 2.0)
        self.assertAlmostEqual(irv2, 2 * irv1, delta=0.01)


# ===========================================================================
# 4. Label Determination
# ===========================================================================

class TestLabelDetermination(BaseTest):

    def test_duration_immune_variable_short(self):
        label = self.analyzer._determine_label(1.0, 0.5, "variable_rate_lending", "stable")
        self.assertEqual(label, "DURATION_IMMUNE")

    def test_duration_immune_variable_at_boundary(self):
        # exactly 7 is NOT < 7
        label = self.analyzer._determine_label(7.0, 0.5, "variable_rate_lending", "stable")
        self.assertNotEqual(label, "DURATION_IMMUNE")

    def test_rate_trapped_fixed_rising(self):
        label = self.analyzer._determine_label(90.0, 3.0, "fixed_rate_lending", "rising")
        self.assertEqual(label, "RATE_TRAPPED")

    def test_rate_trapped_fixed_borrow_rising(self):
        label = self.analyzer._determine_label(90.0, 3.0, "fixed_rate_borrowing", "rising")
        self.assertEqual(label, "RATE_TRAPPED")

    def test_no_rate_trapped_stable_env(self):
        label = self.analyzer._determine_label(90.0, 3.0, "fixed_rate_lending", "stable")
        self.assertNotEqual(label, "RATE_TRAPPED")

    def test_long_duration_risk(self):
        label = self.analyzer._determine_label(200.0, 5.0, "variable_rate_lending", "stable")
        self.assertEqual(label, "LONG_DURATION_RISK")

    def test_no_long_duration_risk_low_sensitivity(self):
        label = self.analyzer._determine_label(200.0, 1.0, "variable_rate_lending", "stable")
        self.assertNotEqual(label, "LONG_DURATION_RISK")

    def test_short_duration_label(self):
        label = self.analyzer._determine_label(20.0, 1.0, "fixed_rate_lending", "stable")
        self.assertEqual(label, "SHORT_DURATION")

    def test_medium_duration_label(self):
        label = self.analyzer._determine_label(90.0, 1.0, "lp_stable", "stable")
        self.assertEqual(label, "MEDIUM_DURATION")

    def test_all_labels_are_valid(self):
        test_cases = [
            (1.0, 0.5, "variable_rate_lending", "stable"),
            (200.0, 5.0, "variable_rate_lending", "stable"),
            (90.0, 3.0, "fixed_rate_lending", "rising"),
            (20.0, 1.0, "lp_stable", "stable"),
            (90.0, 1.0, "lp_volatile", "stable"),
        ]
        for args in test_cases:
            label = self.analyzer._determine_label(*args)
            self.assertIn(label, _ALL_LABELS)


# ===========================================================================
# 5. Flags
# ===========================================================================

class TestFlags(BaseTest):

    def test_refinancing_imminent_flag(self):
        flags = self.analyzer._compute_flags(
            True, "variable_rate_lending", "stable", 1.0, 30.0, 6.5, 5.25
        )
        self.assertIn("REFINANCING_IMMINENT", flags)

    def test_no_refinancing_flag_when_false(self):
        flags = self.analyzer._compute_flags(
            False, "variable_rate_lending", "stable", 1.0, 30.0, 6.5, 5.25
        )
        self.assertNotIn("REFINANCING_IMMINENT", flags)

    def test_rate_env_mismatch_fixed_borrow_falling(self):
        flags = self.analyzer._compute_flags(
            False, "fixed_rate_borrowing", "falling", 1.0, 30.0, 6.5, 5.25
        )
        self.assertIn("RATE_ENVIRONMENT_MISMATCH", flags)

    def test_rate_env_mismatch_fixed_lend_rising(self):
        flags = self.analyzer._compute_flags(
            False, "fixed_rate_lending", "rising", 1.0, 30.0, 4.0, 5.25
        )
        self.assertIn("RATE_ENVIRONMENT_MISMATCH", flags)

    def test_no_mismatch_variable_rate(self):
        flags = self.analyzer._compute_flags(
            False, "variable_rate_lending", "rising", 1.0, 30.0, 6.5, 5.25
        )
        self.assertNotIn("RATE_ENVIRONMENT_MISMATCH", flags)

    def test_positive_carry_flag(self):
        flags = self.analyzer._compute_flags(
            False, "variable_rate_lending", "stable", 3.0, 30.0, 8.25, 5.25
        )
        self.assertIn("POSITIVE_CARRY", flags)

    def test_no_positive_carry_below_threshold(self):
        flags = self.analyzer._compute_flags(
            False, "variable_rate_lending", "stable", 1.9, 30.0, 7.15, 5.25
        )
        self.assertNotIn("POSITIVE_CARRY", flags)

    def test_duration_mismatch_flag_long_lending(self):
        # lending with duration > 180 * 3 = 540 days
        flags = self.analyzer._compute_flags(
            False, "fixed_rate_lending", "stable", 1.0, 600.0, 6.5, 5.25
        )
        self.assertIn("DURATION_MISMATCH", flags)

    def test_no_duration_mismatch_short_lending(self):
        flags = self.analyzer._compute_flags(
            False, "fixed_rate_lending", "stable", 1.0, 90.0, 6.5, 5.25
        )
        self.assertNotIn("DURATION_MISMATCH", flags)

    def test_benchmark_lagging_flag(self):
        # current_rate = 2.0, benchmark = 5.25 → 2.0 < 5.25 - 2.0 = 3.25
        flags = self.analyzer._compute_flags(
            False, "variable_rate_lending", "stable", -3.25, 30.0, 2.0, 5.25
        )
        self.assertIn("BENCHMARK_LAGGING", flags)

    def test_no_benchmark_lagging_above_threshold(self):
        flags = self.analyzer._compute_flags(
            False, "variable_rate_lending", "stable", 1.0, 30.0, 6.0, 5.25
        )
        self.assertNotIn("BENCHMARK_LAGGING", flags)

    def test_all_flags_simultaneously(self):
        flags = self.analyzer._compute_flags(
            True, "fixed_rate_borrowing", "falling", 3.0, 600.0, 1.0, 5.25
        )
        self.assertIn("REFINANCING_IMMINENT", flags)
        self.assertIn("RATE_ENVIRONMENT_MISMATCH", flags)
        # POSITIVE_CARRY: rate_premium > 2 → 3.0 > 2.0 → yes
        self.assertIn("POSITIVE_CARRY", flags)
        # BENCHMARK_LAGGING: 1.0 < 5.25 - 2.0 = 3.25 → yes
        self.assertIn("BENCHMARK_LAGGING", flags)

    def test_flags_are_valid_values(self):
        flags = self.analyzer._compute_flags(
            True, "fixed_rate_lending", "rising", 3.0, 600.0, 2.0, 5.25
        )
        for flag in flags:
            self.assertIn(flag, _ALL_FLAGS)

    def test_no_duration_mismatch_for_borrowing(self):
        # DURATION_MISMATCH only applies to lending types
        flags = self.analyzer._compute_flags(
            False, "variable_rate_borrowing", "stable", 1.0, 600.0, 6.5, 5.25
        )
        self.assertNotIn("DURATION_MISMATCH", flags)


# ===========================================================================
# 6. Analyze Position (single)
# ===========================================================================

class TestAnalyzePosition(BaseTest):

    def test_returns_required_keys(self):
        p = make_position()
        result = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        for key in [
            "name", "protocol", "position_type", "effective_duration_days",
            "rate_sensitivity_pct", "current_rate_pct", "benchmark_rate_pct",
            "rate_environment", "notional_value_usd", "collateral_posted_usd",
            "refinancing_risk", "duration_risk_score", "rate_premium_pct",
            "carry_score", "interest_rate_var_usd", "label", "flags",
        ]:
            self.assertIn(key, result)

    def test_default_values_on_empty_dict(self):
        result = self.analyzer._analyze_position({}, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        self.assertEqual(result["name"], "unknown")
        self.assertEqual(result["notional_value_usd"], 0.0)

    def test_rate_premium_computed_correctly(self):
        p = make_position(current_rate_pct=7.25, benchmark_rate_pct=5.25)
        result = self.analyzer._analyze_position(p, 5.25, 1.0)
        self.assertAlmostEqual(result["rate_premium_pct"], 2.0, delta=0.001)

    def test_label_is_valid(self):
        p = make_position()
        result = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        self.assertIn(result["label"], _ALL_LABELS)

    def test_flags_is_list(self):
        p = make_position()
        result = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        self.assertIsInstance(result["flags"], list)

    def test_duration_immune_variable_short(self):
        p = make_position(effective_duration_days=1.0, rate_sensitivity_pct=0.5,
                          position_type="variable_rate_lending")
        result = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        self.assertEqual(result["label"], "DURATION_IMMUNE")

    def test_rate_trapped_fixed_rising(self):
        p = make_position(effective_duration_days=120.0, rate_sensitivity_pct=5.0,
                          position_type="fixed_rate_lending", rate_environment="rising")
        result = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        self.assertEqual(result["label"], "RATE_TRAPPED")

    def test_irv_correct_for_position(self):
        p = make_position(notional_value_usd=100_000.0, rate_sensitivity_pct=5.0)
        result = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        self.assertAlmostEqual(result["interest_rate_var_usd"], 5000.0, delta=1.0)

    def test_collateral_stored_in_result(self):
        p = make_position(collateral_posted_usd=50_000.0)
        result = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        self.assertEqual(result["collateral_posted_usd"], 50_000.0)

    def test_refinancing_risk_triggers_flag(self):
        p = make_position(refinancing_risk=True)
        result = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        self.assertIn("REFINANCING_IMMINENT", result["flags"])

    def test_duration_risk_score_in_range(self):
        p = make_position()
        result = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        self.assertGreaterEqual(result["duration_risk_score"], 0.0)
        self.assertLessEqual(result["duration_risk_score"], 100.0)


# ===========================================================================
# 7. Analyze (full method)
# ===========================================================================

class TestAnalyzeMethod(BaseTest):

    def test_analyze_empty_list(self):
        result = self.analyzer.analyze([], {"log_enabled": False})
        self.assertEqual(result["position_count"], 0)
        self.assertEqual(result["positions"], [])

    def test_analyze_single_position(self):
        result = self.analyzer.analyze([make_position()], {"log_enabled": False})
        self.assertEqual(result["position_count"], 1)
        self.assertEqual(len(result["positions"]), 1)

    def test_analyze_multiple_positions(self):
        positions = [make_position(name=f"Pos{i}") for i in range(5)]
        result = self.analyzer.analyze(positions, {"log_enabled": False})
        self.assertEqual(result["position_count"], 5)

    def test_raises_on_non_list_positions(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze("not_a_list", {})

    def test_raises_on_non_dict_config(self):
        with self.assertRaises(TypeError):
            self.analyzer.analyze([], "not_a_dict")

    def test_output_has_timestamp(self):
        result = self.analyzer.analyze([], {"log_enabled": False})
        self.assertIn("timestamp", result)

    def test_output_module_name(self):
        result = self.analyzer.analyze([], {"log_enabled": False})
        self.assertEqual(result["module"], "ProtocolDeFiYieldCurvePositionAnalyzer")

    def test_output_mp_number(self):
        result = self.analyzer.analyze([], {"log_enabled": False})
        self.assertEqual(result["mp"], "MP-1025")

    def test_aggregates_in_output(self):
        result = self.analyzer.analyze([], {"log_enabled": False})
        self.assertIn("aggregates", result)

    def test_config_benchmark_override(self):
        p = make_position(current_rate_pct=4.0, benchmark_rate_pct=4.0)
        result = self.analyzer.analyze([p], {"log_enabled": False, "benchmark_rate": 4.0})
        self.assertEqual(result["benchmark_rate_pct"], 4.0)

    def test_config_rate_shock_override(self):
        result = self.analyzer.analyze([], {"log_enabled": False, "rate_shock_pct": 2.0})
        self.assertEqual(result["rate_shock_pct"], 2.0)

    def test_config_data_dir_override_creates_log(self):
        tmp2 = tempfile.mkdtemp()
        positions = [make_position()]
        self.analyzer.analyze(positions, {"log_enabled": True, "data_dir": tmp2})
        log_path = os.path.join(tmp2, "yield_curve_position_log.json")
        self.assertTrue(os.path.exists(log_path))


# ===========================================================================
# 8. Aggregates
# ===========================================================================

class TestComputeAggregates(BaseTest):

    def test_empty_list_returns_defaults(self):
        agg = self.analyzer._compute_aggregates([])
        self.assertIsNone(agg["highest_duration_risk"])
        self.assertIsNone(agg["lowest_risk"])
        self.assertEqual(agg["total_irv_usd"], 0.0)
        self.assertEqual(agg["portfolio_duration_days"], 0.0)
        self.assertEqual(agg["rate_trapped_count"], 0)
        self.assertEqual(agg["duration_immune_count"], 0)

    def test_single_item_both_extremes(self):
        p = make_position(name="Solo")
        r = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        agg = self.analyzer._compute_aggregates([r])
        self.assertEqual(agg["highest_duration_risk"], "Solo")
        self.assertEqual(agg["lowest_risk"], "Solo")

    def test_total_irv_sums_correctly(self):
        p1 = make_position(name="A", notional_value_usd=100_000.0, rate_sensitivity_pct=5.0)
        p2 = make_position(name="B", notional_value_usd=200_000.0, rate_sensitivity_pct=5.0)
        r1 = self.analyzer._analyze_position(p1, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        r2 = self.analyzer._analyze_position(p2, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        agg = self.analyzer._compute_aggregates([r1, r2])
        self.assertAlmostEqual(agg["total_irv_usd"], 15000.0, delta=1.0)

    def test_portfolio_duration_weighted_avg(self):
        p1 = make_position(name="A", effective_duration_days=10.0, notional_value_usd=100_000.0)
        p2 = make_position(name="B", effective_duration_days=30.0, notional_value_usd=300_000.0)
        r1 = self.analyzer._analyze_position(p1, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        r2 = self.analyzer._analyze_position(p2, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        agg = self.analyzer._compute_aggregates([r1, r2])
        # weighted: (10*100k + 30*300k) / 400k = (1M + 9M) / 400k = 25
        self.assertAlmostEqual(agg["portfolio_duration_days"], 25.0, delta=0.5)

    def test_rate_trapped_count(self):
        p_trapped = make_position(name="Trapped", effective_duration_days=120.0,
                                  rate_sensitivity_pct=5.0, position_type="fixed_rate_lending",
                                  rate_environment="rising")
        r_trapped = self.analyzer._analyze_position(p_trapped, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        r_normal = self.analyzer._analyze_position(make_position(name="Normal"), _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        agg = self.analyzer._compute_aggregates([r_trapped, r_normal])
        self.assertGreaterEqual(agg["rate_trapped_count"], 1)

    def test_duration_immune_count(self):
        p_immune = make_position(name="Immune", effective_duration_days=1.0,
                                 position_type="variable_rate_lending")
        r_immune = self.analyzer._analyze_position(p_immune, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        self.assertEqual(r_immune["label"], "DURATION_IMMUNE")
        agg = self.analyzer._compute_aggregates([r_immune])
        self.assertEqual(agg["duration_immune_count"], 1)

    def test_highest_and_lowest_risk_different(self):
        p_low = make_position(name="Low", effective_duration_days=1.0, rate_sensitivity_pct=0.1)
        p_high = make_position(name="High", effective_duration_days=365.0, rate_sensitivity_pct=10.0)
        r_low = self.analyzer._analyze_position(p_low, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        r_high = self.analyzer._analyze_position(p_high, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        agg = self.analyzer._compute_aggregates([r_low, r_high])
        self.assertEqual(agg["highest_duration_risk"], "High")
        self.assertEqual(agg["lowest_risk"], "Low")

    def test_zero_notional_portfolio_duration(self):
        p = make_position(name="Zero", notional_value_usd=0.0)
        r = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        agg = self.analyzer._compute_aggregates([r])
        self.assertEqual(agg["portfolio_duration_days"], 0.0)


# ===========================================================================
# 9. Ring-buffer log
# ===========================================================================

class TestRingBufferLog(BaseTest):

    def test_log_created_on_first_write(self):
        self.analyzer.analyze([make_position()], {})
        self.assertTrue(os.path.exists(self.analyzer.log_path))

    def test_log_is_valid_json_list(self):
        self.analyzer.analyze([make_position()], {})
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_accumulates_entries(self):
        for _ in range(3):
            self.analyzer.analyze([make_position()], {})
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_capped_at_100(self):
        for _ in range(LOG_CAP + 5):
            self.analyzer.analyze([make_position()], {})
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), LOG_CAP)

    def test_log_disabled_creates_no_file(self):
        self.analyzer.analyze([make_position()], {"log_enabled": False})
        self.assertFalse(os.path.exists(self.analyzer.log_path))

    def test_log_entry_has_timestamp(self):
        self.analyzer.analyze([make_position()], {})
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[-1])

    def test_log_entry_has_position_count(self):
        self.analyzer.analyze([make_position(), make_position(name="B")], {})
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["position_count"], 2)

    def test_atomic_write_no_tmp_file(self):
        self.analyzer.analyze([make_position()], {})
        tmp_file = self.analyzer.log_path + ".tmp"
        self.assertFalse(os.path.exists(tmp_file))

    def test_corrupted_log_recovered(self):
        os.makedirs(self.tmp, exist_ok=True)
        with open(self.analyzer.log_path, "w") as f:
            f.write("{INVALID JSON")
        self.analyzer.analyze([make_position()], {})
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_newest_at_end_when_capped(self):
        for i in range(LOG_CAP + 3):
            self.analyzer.analyze([make_position(name=f"P{i}")], {})
        with open(self.analyzer.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), LOG_CAP)
        self.assertIn("positions", data[-1])


# ===========================================================================
# 10. Edge cases and integration
# ===========================================================================

class TestEdgeCases(BaseTest):

    def test_all_position_types_produce_labels(self):
        types = [
            "fixed_rate_lending", "variable_rate_lending",
            "fixed_rate_borrowing", "variable_rate_borrowing",
            "lp_stable", "lp_volatile", "staking",
        ]
        for pt in types:
            p = make_position(position_type=pt, effective_duration_days=30.0,
                              rate_sensitivity_pct=2.0)
            result = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
            self.assertIn(result["label"], _ALL_LABELS, msg=f"Failed for type: {pt}")

    def test_rate_environment_rising_falling_stable(self):
        for env in ["rising", "falling", "stable"]:
            p = make_position(rate_environment=env)
            result = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
            self.assertIn("label", result)

    def test_missing_fields_use_defaults(self):
        result = self.analyzer._analyze_position({}, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        self.assertEqual(result["notional_value_usd"], 0.0)
        self.assertEqual(result["refinancing_risk"], False)

    def test_large_portfolio_aggregates(self):
        positions = [make_position(name=f"P{i}", notional_value_usd=float(i * 10_000))
                     for i in range(20)]
        result = self.analyzer.analyze(positions, {"log_enabled": False})
        self.assertEqual(result["position_count"], 20)
        self.assertIn("aggregates", result)

    def test_benchmark_lagging_with_low_rate(self):
        p = make_position(current_rate_pct=2.0, benchmark_rate_pct=5.25)
        result = self.analyzer._analyze_position(p, 5.25, 1.0)
        self.assertIn("BENCHMARK_LAGGING", result["flags"])

    def test_positive_carry_flag_in_result(self):
        p = make_position(current_rate_pct=8.5, benchmark_rate_pct=5.25)
        result = self.analyzer._analyze_position(p, 5.25, 1.0)
        self.assertIn("POSITIVE_CARRY", result["flags"])

    def test_long_duration_risk_label_high_sensitivity(self):
        p = make_position(
            effective_duration_days=200.0,
            rate_sensitivity_pct=8.0,
            position_type="lp_stable",
            rate_environment="stable",
        )
        result = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        self.assertEqual(result["label"], "LONG_DURATION_RISK")

    def test_carry_score_in_range(self):
        p = make_position()
        result = self.analyzer._analyze_position(p, _DEFAULT_BENCHMARK_RATE_PCT, 1.0)
        self.assertGreaterEqual(result["carry_score"], 0.0)
        self.assertLessEqual(result["carry_score"], 100.0)

    def test_analyze_returns_dict(self):
        result = self.analyzer.analyze([make_position()], {"log_enabled": False})
        self.assertIsInstance(result, dict)

    def test_analyze_result_is_serializable(self):
        result = self.analyzer.analyze([make_position()], {"log_enabled": False})
        # Should not raise
        json.dumps(result)

    def test_rate_shock_affects_irv(self):
        p = make_position(notional_value_usd=100_000.0, rate_sensitivity_pct=5.0)
        r1 = self.analyzer.analyze([p], {"log_enabled": False, "rate_shock_pct": 1.0})
        r2 = self.analyzer.analyze([p], {"log_enabled": False, "rate_shock_pct": 2.0})
        irv1 = r1["positions"][0]["interest_rate_var_usd"]
        irv2 = r2["positions"][0]["interest_rate_var_usd"]
        self.assertAlmostEqual(irv2, 2 * irv1, delta=1.0)


if __name__ == "__main__":
    unittest.main()
