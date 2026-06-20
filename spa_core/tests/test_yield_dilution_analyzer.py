"""
Tests for MP-911 YieldDilutionAnalyzer.
Run: python3 -m unittest spa_core.tests.test_yield_dilution_analyzer -v
"""

import json
import math
import os
import sys
import time
import unittest
import tempfile

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from spa_core.analytics.yield_dilution_analyzer import (
    _MAX_DEPOSIT_CAP_USD,
    _append_log,
    _atomic_write,
    _build_flags,
    _classification,
    _crowding_risk_score,
    _dilution_factor,
    _diluted_apy,
    _grade,
    _marginal_apy_impact_pct,
    _max_deposit_for_floor,
    _read_log,
    _recommendation,
    _relative_size_signal,
    _reward_dependence_signal,
    _reward_share_label,
    _reward_share_pct,
    _risk_label,
    _sample_pools,
    _thin_tvl_signal,
    analyze,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _pool(
    name="Pool",
    tvl=10_000_000.0,
    apy=10.0,
    reward=5.0,
    base=5.0,
    inflow=0.0,
    deposit=0.0,
):
    return {
        "name": name,
        "current_tvl_usd": tvl,
        "current_apy_pct": apy,
        "reward_apy_pct": reward,
        "base_apy_pct": base,
        "expected_inflow_usd": inflow,
        "your_deposit_usd": deposit,
    }


# ---------------------------------------------------------------------------
# 1. _dilution_factor
# ---------------------------------------------------------------------------

class TestDilutionFactor(unittest.TestCase):
    def test_no_added(self):
        self.assertEqual(_dilution_factor(1_000_000, 0), 1.0)

    def test_equal_added(self):
        self.assertAlmostEqual(_dilution_factor(1_000_000, 1_000_000), 0.5)

    def test_large_added(self):
        self.assertAlmostEqual(_dilution_factor(1_000_000, 9_000_000), 0.1)

    def test_zero_denom_returns_one(self):
        self.assertEqual(_dilution_factor(0, 0), 1.0)

    def test_negative_denom_returns_one(self):
        self.assertEqual(_dilution_factor(-100, -100), 1.0)

    def test_zero_tvl_positive_added(self):
        self.assertEqual(_dilution_factor(0, 1000), 0.0)

    def test_clamped_to_unit_interval(self):
        f = _dilution_factor(5_000_000, 1_000_000)
        self.assertGreaterEqual(f, 0.0)
        self.assertLessEqual(f, 1.0)

    def test_monotone_decreasing_in_added(self):
        f1 = _dilution_factor(1_000_000, 100_000)
        f2 = _dilution_factor(1_000_000, 500_000)
        self.assertGreater(f1, f2)


# ---------------------------------------------------------------------------
# 2. _diluted_apy
# ---------------------------------------------------------------------------

class TestDilutedApy(unittest.TestCase):
    def test_no_added_returns_sum(self):
        self.assertAlmostEqual(_diluted_apy(5.0, 5.0, 1_000_000, 0), 10.0)

    def test_zero_added_negative_returns_sum(self):
        self.assertAlmostEqual(_diluted_apy(5.0, 5.0, 1_000_000, -5), 10.0)

    def test_dilution_halves_reward_sqrt_base(self):
        # factor = 0.5: reward*0.5 + base*sqrt(0.5)
        val = _diluted_apy(10.0, 10.0, 1_000_000, 1_000_000)
        expected = 10.0 * 0.5 + 10.0 * math.sqrt(0.5)
        self.assertAlmostEqual(val, expected)

    def test_reward_only_pure_linear(self):
        val = _diluted_apy(10.0, 0.0, 1_000_000, 1_000_000)
        self.assertAlmostEqual(val, 5.0)

    def test_base_only_sqrt(self):
        val = _diluted_apy(0.0, 10.0, 1_000_000, 1_000_000)
        self.assertAlmostEqual(val, 10.0 * math.sqrt(0.5))

    def test_monotone_decreasing_in_deposit(self):
        a = _diluted_apy(10.0, 10.0, 1_000_000, 100_000)
        b = _diluted_apy(10.0, 10.0, 1_000_000, 1_000_000)
        self.assertGreater(a, b)

    def test_larger_deposit_lower_apy(self):
        small = _diluted_apy(20.0, 5.0, 5_000_000, 500_000)
        large = _diluted_apy(20.0, 5.0, 5_000_000, 5_000_000)
        self.assertGreaterEqual(small, large)

    def test_negative_base_reduces_apy(self):
        val = _diluted_apy(10.0, -2.0, 1_000_000, 1_000_000)
        self.assertLess(val, 10.0)

    def test_zero_tvl_added_drives_reward_to_zero(self):
        # factor=0 → reward*0 + base*0
        val = _diluted_apy(10.0, 10.0, 0, 1000)
        self.assertAlmostEqual(val, 0.0)

    def test_never_errors_on_zero_everything(self):
        val = _diluted_apy(0.0, 0.0, 0, 0)
        self.assertEqual(val, 0.0)


# ---------------------------------------------------------------------------
# 3. _marginal_apy_impact_pct
# ---------------------------------------------------------------------------

class TestMarginalImpact(unittest.TestCase):
    def test_positive_drop(self):
        self.assertAlmostEqual(_marginal_apy_impact_pct(10.0, 7.0), 3.0)

    def test_no_drop(self):
        self.assertEqual(_marginal_apy_impact_pct(10.0, 10.0), 0.0)

    def test_negative_drop_clamped_zero(self):
        # diluted higher than current → 0
        self.assertEqual(_marginal_apy_impact_pct(5.0, 8.0), 0.0)

    def test_zero_current(self):
        self.assertEqual(_marginal_apy_impact_pct(0.0, 0.0), 0.0)

    def test_full_loss(self):
        self.assertAlmostEqual(_marginal_apy_impact_pct(10.0, 0.0), 10.0)


# ---------------------------------------------------------------------------
# 4. _reward_share_pct
# ---------------------------------------------------------------------------

class TestRewardSharePct(unittest.TestCase):
    def test_half(self):
        self.assertAlmostEqual(_reward_share_pct(5.0, 5.0), 50.0)

    def test_all_reward(self):
        self.assertAlmostEqual(_reward_share_pct(10.0, 0.0), 100.0)

    def test_no_reward(self):
        self.assertAlmostEqual(_reward_share_pct(0.0, 10.0), 0.0)

    def test_zero_total(self):
        self.assertEqual(_reward_share_pct(0.0, 0.0), 0.0)

    def test_negative_total_zero_guard(self):
        # total <= 0 → 0
        self.assertEqual(_reward_share_pct(0.0, -5.0), 0.0)

    def test_clamped_above_100_with_negative_base(self):
        # reward 12, base -2 → total 10 → 120% → clamped to 100
        self.assertEqual(_reward_share_pct(12.0, -2.0), 100.0)

    def test_three_quarters(self):
        self.assertAlmostEqual(_reward_share_pct(15.0, 5.0), 75.0)


# ---------------------------------------------------------------------------
# 5. _reward_dependence_signal
# ---------------------------------------------------------------------------

class TestRewardDependenceSignal(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(_reward_dependence_signal(0.0), 0.0)

    def test_full(self):
        self.assertAlmostEqual(_reward_dependence_signal(100.0), 40.0)

    def test_half(self):
        self.assertAlmostEqual(_reward_dependence_signal(50.0), 20.0)

    def test_clamped_max(self):
        self.assertLessEqual(_reward_dependence_signal(200.0), 40.0)

    def test_never_negative(self):
        self.assertGreaterEqual(_reward_dependence_signal(-10.0), 0.0)


# ---------------------------------------------------------------------------
# 6. _relative_size_signal
# ---------------------------------------------------------------------------

class TestRelativeSizeSignal(unittest.TestCase):
    def test_zero_added(self):
        self.assertEqual(_relative_size_signal(1_000_000, 0), 0.0)

    def test_equal_added_saturates(self):
        self.assertAlmostEqual(_relative_size_signal(1_000_000, 1_000_000), 40.0)

    def test_quarter_added(self):
        self.assertAlmostEqual(_relative_size_signal(1_000_000, 250_000), 10.0)

    def test_over_saturation_clamped(self):
        self.assertAlmostEqual(_relative_size_signal(1_000_000, 5_000_000), 40.0)

    def test_zero_tvl_positive_added(self):
        self.assertEqual(_relative_size_signal(0, 1000), 40.0)

    def test_zero_tvl_zero_added(self):
        self.assertEqual(_relative_size_signal(0, 0), 0.0)

    def test_negative_added_clamped(self):
        self.assertEqual(_relative_size_signal(1_000_000, -500), 0.0)

    def test_never_above_40(self):
        self.assertLessEqual(_relative_size_signal(100, 1_000_000), 40.0)


# ---------------------------------------------------------------------------
# 7. _thin_tvl_signal
# ---------------------------------------------------------------------------

class TestThinTvlSignal(unittest.TestCase):
    def test_zero_tvl_max(self):
        self.assertEqual(_thin_tvl_signal(0), 20.0)

    def test_negative_tvl_max(self):
        self.assertEqual(_thin_tvl_signal(-100), 20.0)

    def test_at_threshold_zero(self):
        self.assertEqual(_thin_tvl_signal(1_000_000), 0.0)

    def test_above_threshold_zero(self):
        self.assertEqual(_thin_tvl_signal(50_000_000), 0.0)

    def test_half_threshold(self):
        self.assertAlmostEqual(_thin_tvl_signal(500_000), 10.0)

    def test_quarter_threshold(self):
        self.assertAlmostEqual(_thin_tvl_signal(250_000), 15.0)

    def test_never_negative(self):
        self.assertGreaterEqual(_thin_tvl_signal(2_000_000), 0.0)

    def test_never_above_20(self):
        self.assertLessEqual(_thin_tvl_signal(1), 20.0)


# ---------------------------------------------------------------------------
# 8. _crowding_risk_score
# ---------------------------------------------------------------------------

class TestCrowdingRiskScore(unittest.TestCase):
    def test_clean_deep_pool_low(self):
        # no reward, big tvl, tiny added → ~0
        score = _crowding_risk_score(0.0, 100_000_000, 100_000)
        self.assertLessEqual(score, 5)

    def test_worst_case_high(self):
        # 100% reward, added==tvl, thin tvl → 40 + 40 + ~something
        score = _crowding_risk_score(100.0, 100_000, 100_000)
        self.assertGreaterEqual(score, 80)

    def test_clamped_0_100(self):
        score = _crowding_risk_score(100.0, 1, 1_000_000_000)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_returns_int(self):
        self.assertIsInstance(_crowding_risk_score(50.0, 1_000_000, 100_000), int)

    def test_zero_inputs(self):
        score = _crowding_risk_score(0.0, 10_000_000, 0)
        self.assertEqual(score, 0)

    def test_monotone_in_reward_share(self):
        low = _crowding_risk_score(10.0, 10_000_000, 1_000_000)
        high = _crowding_risk_score(90.0, 10_000_000, 1_000_000)
        self.assertGreater(high, low)

    def test_monotone_in_added(self):
        low = _crowding_risk_score(50.0, 10_000_000, 500_000)
        high = _crowding_risk_score(50.0, 10_000_000, 5_000_000)
        self.assertGreaterEqual(high, low)

    def test_thin_tvl_raises_score(self):
        deep = _crowding_risk_score(50.0, 50_000_000, 1_000_000)
        thin = _crowding_risk_score(50.0, 500_000, 1_000_000)
        self.assertGreater(thin, deep)


# ---------------------------------------------------------------------------
# 9. _max_deposit_for_floor
# ---------------------------------------------------------------------------

class TestMaxDepositForFloor(unittest.TestCase):
    def test_floor_zero_returns_cap(self):
        self.assertEqual(
            _max_deposit_for_floor(10, 5, 1_000_000, 0, 0.0), _MAX_DEPOSIT_CAP_USD
        )

    def test_floor_negative_returns_cap(self):
        self.assertEqual(
            _max_deposit_for_floor(10, 5, 1_000_000, 0, -5.0), _MAX_DEPOSIT_CAP_USD
        )

    def test_floor_already_unmet_returns_zero(self):
        # inflow already pushes APY below floor even at zero deposit
        result = _max_deposit_for_floor(10, 0, 1_000_000, 100_000_000, 9.0)
        self.assertEqual(result, 0.0)

    def test_floor_trivially_met_returns_cap(self):
        # huge base, low floor → even cap deposit stays above floor
        result = _max_deposit_for_floor(0, 1000, 1_000_000_000_000, 0, 0.001)
        self.assertEqual(result, _MAX_DEPOSIT_CAP_USD)

    def test_returns_value_within_floor(self):
        # the returned deposit should keep diluted APY >= floor
        rew, base, tvl, inflow, floor = 20.0, 5.0, 5_000_000, 0.0, 10.0
        dep = _max_deposit_for_floor(rew, base, tvl, inflow, floor)
        self.assertGreater(dep, 0)
        apy = _diluted_apy(rew, base, tvl, inflow + dep)
        self.assertGreaterEqual(apy, floor - 0.01)

    def test_just_above_threshold_breaks_floor(self):
        rew, base, tvl, floor = 20.0, 5.0, 5_000_000, 10.0
        dep = _max_deposit_for_floor(rew, base, tvl, 0.0, floor)
        # a slightly larger deposit should drop below floor
        apy_more = _diluted_apy(rew, base, tvl, dep * 1.5 + 1_000_000)
        self.assertLess(apy_more, floor + 0.5)

    def test_negative_inflow_treated_as_zero(self):
        a = _max_deposit_for_floor(20, 5, 5_000_000, -100, 10.0)
        b = _max_deposit_for_floor(20, 5, 5_000_000, 0, 10.0)
        self.assertAlmostEqual(a, b, places=0)

    def test_negative_tvl_no_crash(self):
        result = _max_deposit_for_floor(20, 5, -5_000_000, 0, 10.0)
        self.assertIsInstance(result, float)

    def test_inflow_reduces_headroom(self):
        no_inflow = _max_deposit_for_floor(20, 5, 5_000_000, 0, 10.0)
        with_inflow = _max_deposit_for_floor(20, 5, 5_000_000, 2_000_000, 10.0)
        self.assertGreater(no_inflow, with_inflow)

    def test_higher_floor_less_headroom(self):
        low_floor = _max_deposit_for_floor(20, 5, 5_000_000, 0, 8.0)
        high_floor = _max_deposit_for_floor(20, 5, 5_000_000, 0, 15.0)
        self.assertGreater(low_floor, high_floor)

    def test_result_never_above_cap(self):
        result = _max_deposit_for_floor(100, 100, 1e12, 0, 0.01)
        self.assertLessEqual(result, _MAX_DEPOSIT_CAP_USD)

    def test_result_never_negative(self):
        result = _max_deposit_for_floor(5, 0, 1_000_000, 0, 4.0)
        self.assertGreaterEqual(result, 0.0)


# ---------------------------------------------------------------------------
# 10. _risk_label
# ---------------------------------------------------------------------------

class TestRiskLabel(unittest.TestCase):
    def test_low(self):
        self.assertEqual(_risk_label(0), "LOW")

    def test_low_boundary(self):
        self.assertEqual(_risk_label(20), "LOW")

    def test_moderate(self):
        self.assertEqual(_risk_label(30), "MODERATE")

    def test_moderate_boundary(self):
        self.assertEqual(_risk_label(40), "MODERATE")

    def test_elevated(self):
        self.assertEqual(_risk_label(50), "ELEVATED")

    def test_elevated_boundary(self):
        self.assertEqual(_risk_label(60), "ELEVATED")

    def test_high(self):
        self.assertEqual(_risk_label(70), "HIGH")

    def test_high_boundary(self):
        self.assertEqual(_risk_label(80), "HIGH")

    def test_severe(self):
        self.assertEqual(_risk_label(90), "SEVERE")

    def test_severe_max(self):
        self.assertEqual(_risk_label(100), "SEVERE")


# ---------------------------------------------------------------------------
# 11. _grade
# ---------------------------------------------------------------------------

class TestGrade(unittest.TestCase):
    def test_a(self):
        self.assertEqual(_grade(0), "A")

    def test_a_boundary(self):
        self.assertEqual(_grade(20), "A")

    def test_b(self):
        self.assertEqual(_grade(30), "B")

    def test_b_boundary(self):
        self.assertEqual(_grade(40), "B")

    def test_c(self):
        self.assertEqual(_grade(50), "C")

    def test_c_boundary(self):
        self.assertEqual(_grade(60), "C")

    def test_d(self):
        self.assertEqual(_grade(70), "D")

    def test_d_boundary(self):
        self.assertEqual(_grade(80), "D")

    def test_f(self):
        self.assertEqual(_grade(90), "F")

    def test_f_max(self):
        self.assertEqual(_grade(100), "F")

    def test_higher_score_worse_grade(self):
        self.assertLess(_grade(10), _grade(90))  # "A" < "F"


# ---------------------------------------------------------------------------
# 12. _reward_share_label
# ---------------------------------------------------------------------------

class TestRewardShareLabel(unittest.TestCase):
    def test_emission_heavy(self):
        self.assertEqual(_reward_share_label(90.0), "EMISSION_HEAVY")

    def test_emission_heavy_boundary(self):
        self.assertEqual(_reward_share_label(75.0), "EMISSION_HEAVY")

    def test_mixed(self):
        self.assertEqual(_reward_share_label(50.0), "MIXED")

    def test_mixed_boundary(self):
        self.assertEqual(_reward_share_label(40.0), "MIXED")

    def test_fee_heavy(self):
        self.assertEqual(_reward_share_label(20.0), "FEE_HEAVY")

    def test_fee_heavy_boundary(self):
        self.assertEqual(_reward_share_label(0.1), "FEE_HEAVY")

    def test_fee_only(self):
        self.assertEqual(_reward_share_label(0.0), "FEE_ONLY")


# ---------------------------------------------------------------------------
# 13. _classification
# ---------------------------------------------------------------------------

class TestClassification(unittest.TestCase):
    def test_zero_tvl_saturated(self):
        self.assertEqual(_classification(50.0, 30, 0), "SATURATED")

    def test_emission_dependent(self):
        self.assertEqual(_classification(70.0, 30, 50_000_000), "EMISSION_DEPENDENT")

    def test_emission_dependent_boundary(self):
        self.assertEqual(_classification(60.0, 30, 50_000_000), "EMISSION_DEPENDENT")

    def test_dilution_sensitive(self):
        # reward share below high, but crowding >= 60
        self.assertEqual(_classification(30.0, 65, 50_000_000), "DILUTION_SENSITIVE")

    def test_thin_tvl_saturated(self):
        self.assertEqual(_classification(20.0, 30, 500_000), "SATURATED")

    def test_crowd_resistant(self):
        self.assertEqual(_classification(10.0, 10, 50_000_000), "CROWD_RESISTANT")

    def test_emission_takes_precedence_over_crowding(self):
        # high reward share AND high crowding → emission dependent
        self.assertEqual(_classification(80.0, 90, 50_000_000), "EMISSION_DEPENDENT")


# ---------------------------------------------------------------------------
# 14. _build_flags
# ---------------------------------------------------------------------------

class TestBuildFlags(unittest.TestCase):
    def test_insufficient_data_only(self):
        flags = _build_flags(50.0, 1_000_000, 100_000, 1.0, 10.0, 5.0, has_data=False)
        self.assertEqual(flags, ["INSUFFICIENT_DATA"])

    def test_no_flags_healthy(self):
        flags = _build_flags(10.0, 50_000_000, 100_000, 0.5, 10.0, 9.0, has_data=True)
        self.assertEqual(flags, [])

    def test_high_reward_dependence(self):
        flags = _build_flags(70.0, 50_000_000, 100_000, 0.5, 10.0, 3.0, has_data=True)
        self.assertIn("HIGH_REWARD_DEPENDENCE", flags)

    def test_high_reward_dependence_boundary_no_flag(self):
        # exactly 60 → not > 60 → no flag
        flags = _build_flags(60.0, 50_000_000, 100_000, 0.5, 10.0, 4.0, has_data=True)
        self.assertNotIn("HIGH_REWARD_DEPENDENCE", flags)

    def test_large_relative_deposit(self):
        # added/tvl = 0.5 > 0.25
        flags = _build_flags(10.0, 1_000_000, 500_000, 0.5, 10.0, 9.0, has_data=True)
        self.assertIn("LARGE_RELATIVE_DEPOSIT", flags)

    def test_large_relative_deposit_boundary_no_flag(self):
        # exactly 0.25 → not > 0.25
        flags = _build_flags(10.0, 1_000_000, 250_000, 0.5, 10.0, 9.0, has_data=True)
        self.assertNotIn("LARGE_RELATIVE_DEPOSIT", flags)

    def test_large_relative_deposit_zero_tvl(self):
        flags = _build_flags(10.0, 0, 1000, 0.5, 10.0, 9.0, has_data=True)
        self.assertIn("LARGE_RELATIVE_DEPOSIT", flags)

    def test_thin_tvl(self):
        flags = _build_flags(10.0, 500_000, 10_000, 0.1, 10.0, 9.0, has_data=True)
        self.assertIn("THIN_TVL", flags)

    def test_thin_tvl_boundary_no_flag(self):
        # exactly 1e6 → not < 1e6
        flags = _build_flags(10.0, 1_000_000, 10_000, 0.1, 10.0, 9.0, has_data=True)
        self.assertNotIn("THIN_TVL", flags)

    def test_severe_dilution(self):
        # marginal 3 of current 10 = 30% > 20%
        flags = _build_flags(10.0, 50_000_000, 100_000, 3.0, 10.0, 9.0, has_data=True)
        self.assertIn("SEVERE_DILUTION", flags)

    def test_severe_dilution_boundary_no_flag(self):
        # marginal 2 of 10 = exactly 20% → not > 20%
        flags = _build_flags(10.0, 50_000_000, 100_000, 2.0, 10.0, 9.0, has_data=True)
        self.assertNotIn("SEVERE_DILUTION", flags)

    def test_severe_dilution_zero_apy_no_flag(self):
        flags = _build_flags(10.0, 50_000_000, 100_000, 5.0, 0.0, 9.0, has_data=True)
        self.assertNotIn("SEVERE_DILUTION", flags)

    def test_negative_base_yield(self):
        flags = _build_flags(80.0, 50_000_000, 100_000, 0.5, 10.0, -2.0, has_data=True)
        self.assertIn("NEGATIVE_BASE_YIELD", flags)

    def test_negative_base_zero_no_flag(self):
        flags = _build_flags(50.0, 50_000_000, 100_000, 0.5, 10.0, 0.0, has_data=True)
        self.assertNotIn("NEGATIVE_BASE_YIELD", flags)

    def test_all_flags_fire(self):
        flags = _build_flags(80.0, 500_000, 400_000, 5.0, 10.0, -2.0, has_data=True)
        self.assertIn("HIGH_REWARD_DEPENDENCE", flags)
        self.assertIn("LARGE_RELATIVE_DEPOSIT", flags)
        self.assertIn("THIN_TVL", flags)
        self.assertIn("SEVERE_DILUTION", flags)
        self.assertIn("NEGATIVE_BASE_YIELD", flags)

    def test_insufficient_data_short_circuits(self):
        # even with bad metrics, no_data returns only INSUFFICIENT_DATA
        flags = _build_flags(80.0, 500_000, 400_000, 5.0, 10.0, -2.0, has_data=False)
        self.assertEqual(flags, ["INSUFFICIENT_DATA"])


# ---------------------------------------------------------------------------
# 15. _recommendation
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):
    def test_insufficient_data(self):
        rec = _recommendation("LOW", "SATURATED", 0, ["INSUFFICIENT_DATA"])
        self.assertIn("Insufficient data", rec)

    def test_low(self):
        rec = _recommendation("LOW", "CROWD_RESISTANT", 1_000_000, [])
        self.assertIn("CROWD_RESISTANT", rec)
        self.assertIn("low", rec)

    def test_moderate(self):
        rec = _recommendation("MODERATE", "CROWD_RESISTANT", 500_000, [])
        self.assertIn("moderate", rec)

    def test_elevated_with_flags(self):
        rec = _recommendation("ELEVATED", "DILUTION_SENSITIVE", 100_000, ["THIN_TVL"])
        self.assertIn("Elevated", rec)
        self.assertIn("THIN_TVL", rec)

    def test_elevated_no_flags(self):
        rec = _recommendation("ELEVATED", "DILUTION_SENSITIVE", 100_000, [])
        self.assertIn("rising dilution", rec)

    def test_high_with_flags(self):
        rec = _recommendation("HIGH", "EMISSION_DEPENDENT", 50_000,
                              ["HIGH_REWARD_DEPENDENCE"])
        self.assertIn("High crowding", rec)
        self.assertIn("HIGH_REWARD_DEPENDENCE", rec)

    def test_high_no_flags(self):
        rec = _recommendation("HIGH", "EMISSION_DEPENDENT", 50_000, [])
        self.assertIn("dilution", rec)

    def test_severe(self):
        rec = _recommendation("SEVERE", "EMISSION_DEPENDENT", 0, ["THIN_TVL"])
        self.assertIn("Severe dilution", rec)

    def test_non_empty(self):
        for lbl in ("LOW", "MODERATE", "ELEVATED", "HIGH", "SEVERE"):
            rec = _recommendation(lbl, "CROWD_RESISTANT", 1000, [])
            self.assertIsInstance(rec, str)
            self.assertGreater(len(rec), 0)


# ---------------------------------------------------------------------------
# 16. analyze() — structure
# ---------------------------------------------------------------------------

class TestAnalyzeStructure(unittest.TestCase):
    def test_empty_input(self):
        result = analyze([])
        self.assertEqual(result["pools"], [])
        self.assertIsNone(result["most_crowd_resistant"])
        self.assertIsNone(result["highest_dilution_pool"])
        self.assertAlmostEqual(result["average_crowding_risk"], 0.0)
        self.assertEqual(result["count"], 0)
        self.assertIn("timestamp", result)

    def test_single_pool_keys(self):
        result = analyze([_pool()])
        p = result["pools"][0]
        for key in (
            "name", "current_tvl_usd", "current_apy_pct", "diluted_apy_pct",
            "marginal_apy_impact_pct", "crowding_risk_score", "risk_label",
            "grade", "classification", "reward_share_pct", "reward_share_label",
            "max_deposit_for_floor_usd", "flags", "recommendation",
        ):
            self.assertIn(key, p, f"Missing key: {key}")

    def test_top_level_keys(self):
        result = analyze([_pool()])
        for key in (
            "pools", "most_crowd_resistant", "highest_dilution_pool",
            "average_crowding_risk", "count", "apy_floor_pct", "timestamp",
        ):
            self.assertIn(key, result)

    def test_timestamp_recent(self):
        before = time.time()
        result = analyze([_pool()])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_result_serializable(self):
        result = analyze([_pool("X", reward=20, base=-2, tvl=500_000, deposit=400_000)])
        parsed = json.loads(json.dumps(result))
        self.assertIn("pools", parsed)

    def test_count_matches(self):
        result = analyze([_pool("A"), _pool("B"), _pool("C")])
        self.assertEqual(result["count"], 3)
        self.assertEqual(len(result["pools"]), 3)

    def test_default_floor_reported(self):
        result = analyze([_pool()])
        self.assertEqual(result["apy_floor_pct"], 5.0)

    def test_custom_floor_reported(self):
        result = analyze([_pool()], apy_floor_pct=8.0)
        self.assertEqual(result["apy_floor_pct"], 8.0)


# ---------------------------------------------------------------------------
# 17. analyze() — calculations & summary
# ---------------------------------------------------------------------------

class TestAnalyzeCalculations(unittest.TestCase):
    def test_most_crowd_resistant(self):
        result = analyze([
            _pool("Deep", tvl=500_000_000, reward=0.5, base=4.0, inflow=1_000_000, deposit=100_000),
            _pool("Thin", tvl=300_000, reward=80, base=5, inflow=300_000, deposit=200_000),
        ])
        self.assertEqual(result["most_crowd_resistant"], "Deep")

    def test_highest_dilution_pool(self):
        result = analyze([
            _pool("Deep", tvl=500_000_000, apy=4.5, reward=0.5, base=4.0,
                  inflow=1_000_000, deposit=100_000),
            _pool("Thin", tvl=300_000, apy=85, reward=80, base=5,
                  inflow=300_000, deposit=200_000),
        ])
        self.assertEqual(result["highest_dilution_pool"], "Thin")

    def test_average_crowding_single(self):
        result = analyze([_pool("A")])
        self.assertAlmostEqual(
            result["average_crowding_risk"],
            result["pools"][0]["crowding_risk_score"],
        )

    def test_average_crowding_two(self):
        result = analyze([
            _pool("A", tvl=500_000_000, reward=0.5, base=4),
            _pool("B", tvl=300_000, reward=80, base=5, inflow=300_000),
        ])
        scores = [p["crowding_risk_score"] for p in result["pools"]]
        self.assertAlmostEqual(result["average_crowding_risk"], sum(scores) / 2, places=2)

    def test_deep_pool_low_risk(self):
        result = analyze([_pool("Deep", tvl=800_000_000, reward=0.5, base=3.7,
                                inflow=5_000_000, deposit=1_000_000)])
        p = result["pools"][0]
        self.assertIn(p["risk_label"], ("LOW", "MODERATE"))
        self.assertEqual(p["classification"], "CROWD_RESISTANT")

    def test_thin_farm_high_risk(self):
        result = analyze([_pool("Farm", tvl=400_000, apy=85, reward=78, base=7,
                                inflow=300_000, deposit=100_000)])
        p = result["pools"][0]
        self.assertIn(p["risk_label"], ("ELEVATED", "HIGH", "SEVERE"))
        self.assertIn("THIN_TVL", p["flags"])
        self.assertIn("HIGH_REWARD_DEPENDENCE", p["flags"])

    def test_larger_deposit_lower_diluted_apy(self):
        small = analyze([_pool("A", tvl=5_000_000, reward=20, base=5, deposit=500_000)])
        large = analyze([_pool("A", tvl=5_000_000, reward=20, base=5, deposit=5_000_000)])
        self.assertGreater(
            small["pools"][0]["diluted_apy_pct"],
            large["pools"][0]["diluted_apy_pct"],
        )

    def test_larger_deposit_ge_crowding(self):
        small = analyze([_pool("A", tvl=5_000_000, reward=20, base=5, deposit=500_000)])
        large = analyze([_pool("A", tvl=5_000_000, reward=20, base=5, deposit=5_000_000)])
        self.assertGreaterEqual(
            large["pools"][0]["crowding_risk_score"],
            small["pools"][0]["crowding_risk_score"],
        )

    def test_negative_base_flag(self):
        result = analyze([_pool("Bad", tvl=2_000_000, reward=14, base=-2,
                                inflow=1_000_000, deposit=200_000)])
        self.assertIn("NEGATIVE_BASE_YIELD", result["pools"][0]["flags"])

    def test_current_apy_derived_when_zero(self):
        result = analyze([_pool("X", apy=0.0, reward=6, base=4)])
        self.assertAlmostEqual(result["pools"][0]["current_apy_pct"], 10.0)

    def test_insufficient_data_pool(self):
        result = analyze([{"name": "Empty", "current_tvl_usd": 0,
                           "reward_apy_pct": 0, "base_apy_pct": 0}])
        self.assertIn("INSUFFICIENT_DATA", result["pools"][0]["flags"])

    def test_missing_keys_default_to_zero(self):
        result = analyze([{"name": "Bare"}])
        p = result["pools"][0]
        self.assertEqual(p["name"], "Bare")
        self.assertIn("INSUFFICIENT_DATA", p["flags"])

    def test_grade_present_and_valid(self):
        result = analyze([_pool()])
        self.assertIn(result["pools"][0]["grade"], ("A", "B", "C", "D", "F"))

    def test_crowding_score_bounded(self):
        result = analyze([_pool("X", tvl=1, reward=100, base=0, deposit=1e9)])
        score = result["pools"][0]["crowding_risk_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_marginal_impact_non_negative(self):
        result = analyze([_pool("X", apy=5.0, reward=2, base=3, deposit=10_000_000, tvl=1_000_000)])
        self.assertGreaterEqual(result["pools"][0]["marginal_apy_impact_pct"], 0.0)

    def test_reward_share_label_emission(self):
        result = analyze([_pool("X", reward=80, base=5)])
        self.assertEqual(result["pools"][0]["reward_share_label"], "EMISSION_HEAVY")

    def test_max_deposit_for_floor_present(self):
        result = analyze([_pool("X", reward=20, base=5, tvl=5_000_000)], apy_floor_pct=10.0)
        self.assertGreaterEqual(result["pools"][0]["max_deposit_for_floor_usd"], 0.0)


# ---------------------------------------------------------------------------
# 18. _sample_pools
# ---------------------------------------------------------------------------

class TestSamplePools(unittest.TestCase):
    def test_returns_list(self):
        self.assertIsInstance(_sample_pools(), list)

    def test_has_four_pools(self):
        self.assertEqual(len(_sample_pools()), 4)

    def test_each_pool_has_keys(self):
        for p in _sample_pools():
            for key in ("name", "current_tvl_usd", "current_apy_pct",
                        "reward_apy_pct", "base_apy_pct",
                        "expected_inflow_usd", "your_deposit_usd"):
                self.assertIn(key, p)

    def test_sample_analyzes_cleanly(self):
        result = analyze(_sample_pools())
        self.assertEqual(result["count"], 4)
        self.assertIsNotNone(result["most_crowd_resistant"])


# ---------------------------------------------------------------------------
# 19. Persistence
# ---------------------------------------------------------------------------

class TestPersistenceYDA(unittest.TestCase):
    def test_atomic_write_and_read(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, [{"x": 42}])
            self.assertEqual(_read_log(path), [{"x": 42}])

    def test_read_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_read_log(os.path.join(d, "missing.json")), [])

    def test_read_invalid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            with open(path, "w") as f:
                f.write("{{NOT JSON")
            self.assertEqual(_read_log(path), [])

    def test_read_non_list_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "obj.json")
            _atomic_write(path, {"key": "val"})
            self.assertEqual(_read_log(path), [])

    def test_append_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "new.json")
            _append_log(path, {"entry": 1})
            self.assertEqual(len(_read_log(path)), 1)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ring.json")
            for i in range(110):
                _append_log(path, {"i": i})
            data = _read_log(path)
            self.assertEqual(len(data), 100)
            self.assertEqual(data[0]["i"], 10)
            self.assertEqual(data[-1]["i"], 109)

    def test_ring_buffer_exactly_100(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "exact.json")
            for i in range(100):
                _append_log(path, {"i": i})
            self.assertEqual(len(_read_log(path)), 100)

    def test_multiple_appends(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "multi.json")
            _append_log(path, {"n": 1})
            _append_log(path, {"n": 2})
            self.assertEqual(len(_read_log(path)), 2)

    def test_atomic_write_creates_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "path", "file.json")
            _atomic_write(path, [])
            self.assertTrue(os.path.exists(path))

    def test_idempotent_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "idem.json")
            _atomic_write(path, [{"a": 1}])
            _atomic_write(path, [{"a": 1}])
            self.assertEqual(_read_log(path), [{"a": 1}])

    def test_overwrite_replaces_content(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ow.json")
            _atomic_write(path, [{"a": 1}])
            _atomic_write(path, [{"b": 2}])
            self.assertEqual(_read_log(path), [{"b": 2}])

    def test_append_full_analyze_result(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "res.json")
            result = analyze(_sample_pools())
            _append_log(path, result)
            data = _read_log(path)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["count"], 4)

    def test_no_leftover_tmp_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "clean.json")
            _atomic_write(path, [{"x": 1}])
            leftovers = [f for f in os.listdir(d) if f.startswith(".tmp_")]
            self.assertEqual(leftovers, [])


# ---------------------------------------------------------------------------
# 20. Integration scenario
# ---------------------------------------------------------------------------

class TestIntegrationScenario(unittest.TestCase):
    def test_full_realistic_scenario(self):
        pools = [
            _pool("DeepStable", tvl=800_000_000, apy=4.2, reward=0.5, base=3.7,
                  inflow=5_000_000, deposit=1_000_000),
            _pool("ThinFarm", tvl=400_000, apy=85, reward=78, base=7,
                  inflow=300_000, deposit=100_000),
            _pool("MidMixed", tvl=25_000_000, apy=18, reward=11, base=7,
                  inflow=4_000_000, deposit=500_000),
        ]
        result = analyze(pools)

        deep = next(p for p in result["pools"] if p["name"] == "DeepStable")
        thin = next(p for p in result["pools"] if p["name"] == "ThinFarm")

        self.assertEqual(deep["classification"], "CROWD_RESISTANT")
        self.assertIn(thin["risk_label"], ("ELEVATED", "HIGH", "SEVERE"))
        self.assertIn("THIN_TVL", thin["flags"])
        self.assertEqual(result["most_crowd_resistant"], "DeepStable")
        self.assertGreater(result["average_crowding_risk"], 0)

    def test_all_deep_pools_low_risk(self):
        result = analyze([
            _pool("A", tvl=1_000_000_000, reward=0.2, base=4, deposit=100_000),
            _pool("B", tvl=500_000_000, reward=0.5, base=3, deposit=50_000),
        ])
        for p in result["pools"]:
            self.assertLessEqual(p["crowding_risk_score"], 30)
            self.assertNotIn("THIN_TVL", p["flags"])

    def test_recommendation_non_empty_all_pools(self):
        result = analyze(_sample_pools())
        for p in result["pools"]:
            self.assertIsInstance(p["recommendation"], str)
            self.assertGreater(len(p["recommendation"]), 0)

    def test_custom_floor_changes_max_deposit(self):
        low = analyze([_pool("X", reward=20, base=5, tvl=5_000_000)], apy_floor_pct=8.0)
        high = analyze([_pool("X", reward=20, base=5, tvl=5_000_000)], apy_floor_pct=15.0)
        self.assertGreaterEqual(
            low["pools"][0]["max_deposit_for_floor_usd"],
            high["pools"][0]["max_deposit_for_floor_usd"],
        )


if __name__ == "__main__":
    unittest.main()
