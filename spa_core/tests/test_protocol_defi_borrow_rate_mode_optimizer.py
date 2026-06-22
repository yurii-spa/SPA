"""
Tests for MP-1124: DeFiProtocolBorrowRateModeOptimizer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_borrow_rate_mode_optimizer -v
Total: >= 120 test methods.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_borrow_rate_mode_optimizer import (
    DeFiProtocolBorrowRateModeOptimizer,
    BorrowRateModeReport,
    MAX_ENTRIES,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_report(
    stable_borrow_apr_pct: float = 6.0,
    variable_borrow_apr_pct: float = 4.0,
    variable_rate_drift_pct: float = 0.0,
    variable_rate_volatility_pct: float = 0.0,
    horizon_days: int = 30,
    farm_apr_pct: float = 10.0,
    borrow_amount_usd: float = 100_000.0,
    stable_rate_rebalance_risk_pct: float = 0.0,
    protocol_name: str = "TestMarket",
) -> BorrowRateModeReport:
    ana = DeFiProtocolBorrowRateModeOptimizer()
    return ana.analyze(
        stable_borrow_apr_pct=stable_borrow_apr_pct,
        variable_borrow_apr_pct=variable_borrow_apr_pct,
        variable_rate_drift_pct=variable_rate_drift_pct,
        variable_rate_volatility_pct=variable_rate_volatility_pct,
        horizon_days=horizon_days,
        farm_apr_pct=farm_apr_pct,
        borrow_amount_usd=borrow_amount_usd,
        stable_rate_rebalance_risk_pct=stable_rate_rebalance_risk_pct,
        protocol_name=protocol_name,
    )


def make_position(**kwargs) -> dict:
    base = dict(
        stable_borrow_apr_pct=6.0,
        variable_borrow_apr_pct=4.0,
        variable_rate_drift_pct=0.0,
        variable_rate_volatility_pct=0.0,
        horizon_days=30,
        farm_apr_pct=10.0,
        borrow_amount_usd=100_000.0,
        stable_rate_rebalance_risk_pct=0.0,
        protocol_name="TestMarket",
    )
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# 1. Expected variable APR computation
# ---------------------------------------------------------------------------

class TestExpectedVariableAPR(unittest.TestCase):

    def test_no_drift(self):
        r = make_report(variable_borrow_apr_pct=5.0, variable_rate_drift_pct=0.0)
        self.assertAlmostEqual(r.expected_variable_apr_pct, 5.0, places=6)

    def test_positive_drift(self):
        r = make_report(variable_borrow_apr_pct=5.0, variable_rate_drift_pct=1.5)
        self.assertAlmostEqual(r.expected_variable_apr_pct, 6.5, places=6)

    def test_negative_drift(self):
        r = make_report(variable_borrow_apr_pct=5.0, variable_rate_drift_pct=-2.0)
        self.assertAlmostEqual(r.expected_variable_apr_pct, 3.0, places=6)

    def test_large_drift(self):
        r = make_report(variable_borrow_apr_pct=4.0, variable_rate_drift_pct=10.0)
        self.assertAlmostEqual(r.expected_variable_apr_pct, 14.0, places=6)

    def test_drift_makes_expected_negative(self):
        r = make_report(variable_borrow_apr_pct=2.0, variable_rate_drift_pct=-5.0)
        self.assertAlmostEqual(r.expected_variable_apr_pct, -3.0, places=6)


# ---------------------------------------------------------------------------
# 2. P95 computation
# ---------------------------------------------------------------------------

class TestVariableP95(unittest.TestCase):

    def test_zero_vol_p95_equals_expected(self):
        r = make_report(variable_borrow_apr_pct=5.0, variable_rate_volatility_pct=0.0)
        self.assertAlmostEqual(r.variable_apr_p95_pct, r.expected_variable_apr_pct, places=6)

    def test_p95_adds_165_sigma(self):
        r = make_report(variable_borrow_apr_pct=5.0, variable_rate_volatility_pct=2.0)
        # expected = 5, p95 = 5 + 1.645*2 = 8.29
        self.assertAlmostEqual(r.variable_apr_p95_pct, 8.29, places=4)

    def test_p95_with_drift_and_vol(self):
        r = make_report(variable_borrow_apr_pct=5.0, variable_rate_drift_pct=1.0,
                        variable_rate_volatility_pct=1.0)
        # expected = 6, p95 = 6 + 1.645 = 7.645
        self.assertAlmostEqual(r.variable_apr_p95_pct, 7.645, places=4)

    def test_p95_greater_than_expected_when_vol_positive(self):
        r = make_report(variable_rate_volatility_pct=3.0)
        self.assertGreater(r.variable_apr_p95_pct, r.expected_variable_apr_pct)

    def test_negative_vol_clamped_to_zero(self):
        r = make_report(variable_borrow_apr_pct=5.0, variable_rate_volatility_pct=-3.0)
        self.assertAlmostEqual(r.variable_apr_p95_pct, 5.0, places=6)

    def test_negative_vol_stored_as_zero(self):
        r = make_report(variable_rate_volatility_pct=-1.0)
        self.assertAlmostEqual(r.variable_rate_volatility_pct, 0.0, places=6)


# ---------------------------------------------------------------------------
# 3. Cost advantage
# ---------------------------------------------------------------------------

class TestCostAdvantage(unittest.TestCase):

    def test_variable_cheaper_positive_advantage(self):
        r = make_report(stable_borrow_apr_pct=6.0, variable_borrow_apr_pct=4.0)
        self.assertAlmostEqual(r.cost_advantage_variable_pct, 2.0, places=6)

    def test_stable_cheaper_negative_advantage(self):
        r = make_report(stable_borrow_apr_pct=4.0, variable_borrow_apr_pct=6.0)
        self.assertAlmostEqual(r.cost_advantage_variable_pct, -2.0, places=6)

    def test_equal_rates_zero_advantage(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=5.0)
        self.assertAlmostEqual(r.cost_advantage_variable_pct, 0.0, places=6)

    def test_advantage_includes_drift(self):
        # stable=6, var=4, drift=1 -> expected_var=5, adv = 6-5 = 1
        r = make_report(stable_borrow_apr_pct=6.0, variable_borrow_apr_pct=4.0,
                        variable_rate_drift_pct=1.0)
        self.assertAlmostEqual(r.cost_advantage_variable_pct, 1.0, places=6)

    def test_drift_flips_advantage_sign(self):
        # stable=6, var=4, drift=3 -> expected_var=7, adv = 6-7 = -1
        r = make_report(stable_borrow_apr_pct=6.0, variable_borrow_apr_pct=4.0,
                        variable_rate_drift_pct=3.0)
        self.assertAlmostEqual(r.cost_advantage_variable_pct, -1.0, places=6)


# ---------------------------------------------------------------------------
# 4. Stable cost not inflated by rebalance risk
# ---------------------------------------------------------------------------

class TestStableCostIndependentOfRebalance(unittest.TestCase):

    def test_stable_cost_equals_stable_apr_no_risk(self):
        r = make_report(stable_borrow_apr_pct=6.0, stable_rate_rebalance_risk_pct=0.0)
        self.assertAlmostEqual(r.expected_cost_stable_pct, 6.0, places=6)

    def test_stable_cost_unchanged_by_risk(self):
        r0 = make_report(stable_borrow_apr_pct=6.0, stable_rate_rebalance_risk_pct=0.0)
        r1 = make_report(stable_borrow_apr_pct=6.0, stable_rate_rebalance_risk_pct=80.0)
        self.assertAlmostEqual(r0.expected_cost_stable_pct, r1.expected_cost_stable_pct, places=6)

    def test_stable_cost_equals_apr_high_risk(self):
        r = make_report(stable_borrow_apr_pct=7.5, stable_rate_rebalance_risk_pct=90.0)
        self.assertAlmostEqual(r.expected_cost_stable_pct, 7.5, places=6)

    def test_expected_cost_variable_equals_expected_variable(self):
        r = make_report(variable_borrow_apr_pct=4.0, variable_rate_drift_pct=1.0)
        self.assertAlmostEqual(r.expected_cost_variable_pct, r.expected_variable_apr_pct, places=6)


# ---------------------------------------------------------------------------
# 5. Stable certainty score
# ---------------------------------------------------------------------------

class TestStableCertainty(unittest.TestCase):

    def test_zero_risk_full_certainty(self):
        r = make_report(stable_rate_rebalance_risk_pct=0.0)
        self.assertAlmostEqual(r.stable_certainty_score, 100.0, places=6)

    def test_30pct_risk(self):
        r = make_report(stable_rate_rebalance_risk_pct=30.0)
        self.assertAlmostEqual(r.stable_certainty_score, 70.0, places=6)

    def test_100pct_risk_zero_certainty(self):
        r = make_report(stable_rate_rebalance_risk_pct=100.0)
        self.assertAlmostEqual(r.stable_certainty_score, 0.0, places=6)

    def test_negative_risk_clamped(self):
        r = make_report(stable_rate_rebalance_risk_pct=-20.0)
        self.assertAlmostEqual(r.stable_certainty_score, 100.0, places=6)

    def test_over_100_risk_clamped(self):
        r = make_report(stable_rate_rebalance_risk_pct=150.0)
        self.assertAlmostEqual(r.stable_certainty_score, 0.0, places=6)

    def test_certainty_in_range(self):
        for risk in (0.0, 10.0, 50.0, 90.0, 100.0):
            r = make_report(stable_rate_rebalance_risk_pct=risk)
            self.assertGreaterEqual(r.stable_certainty_score, 0.0)
            self.assertLessEqual(r.stable_certainty_score, 100.0)


# ---------------------------------------------------------------------------
# 6. Breakeven and headroom
# ---------------------------------------------------------------------------

class TestBreakeven(unittest.TestCase):

    def test_breakeven_equals_stable_apr(self):
        r = make_report(stable_borrow_apr_pct=6.5)
        self.assertAlmostEqual(r.breakeven_variable_apr_pct, 6.5, places=6)

    def test_headroom_positive_when_expected_below_stable(self):
        r = make_report(stable_borrow_apr_pct=6.0, variable_borrow_apr_pct=4.0)
        self.assertAlmostEqual(r.headroom_to_breakeven_pct, 2.0, places=6)

    def test_headroom_negative_when_expected_above_stable(self):
        r = make_report(stable_borrow_apr_pct=4.0, variable_borrow_apr_pct=6.0)
        self.assertAlmostEqual(r.headroom_to_breakeven_pct, -2.0, places=6)

    def test_headroom_equals_cost_advantage_no_drift(self):
        r = make_report(stable_borrow_apr_pct=6.0, variable_borrow_apr_pct=4.0)
        self.assertAlmostEqual(r.headroom_to_breakeven_pct, r.cost_advantage_variable_pct, places=6)

    def test_headroom_with_drift(self):
        r = make_report(stable_borrow_apr_pct=6.0, variable_borrow_apr_pct=4.0,
                        variable_rate_drift_pct=1.0)
        # breakeven=6, expected_var=5, headroom=1
        self.assertAlmostEqual(r.headroom_to_breakeven_pct, 1.0, places=6)


# ---------------------------------------------------------------------------
# 7. Net carry
# ---------------------------------------------------------------------------

class TestNetCarry(unittest.TestCase):

    def test_net_carry_stable(self):
        r = make_report(farm_apr_pct=10.0, stable_borrow_apr_pct=6.0)
        self.assertAlmostEqual(r.net_carry_stable_pct, 4.0, places=6)

    def test_net_carry_variable(self):
        r = make_report(farm_apr_pct=10.0, variable_borrow_apr_pct=4.0)
        self.assertAlmostEqual(r.net_carry_variable_pct, 6.0, places=6)

    def test_net_carry_variable_p95(self):
        r = make_report(farm_apr_pct=10.0, variable_borrow_apr_pct=4.0,
                        variable_rate_volatility_pct=2.0)
        # p95 = 4 + 1.645*2 = 7.29, carry = 10 - 7.29 = 2.71
        self.assertAlmostEqual(r.net_carry_variable_p95_pct, 2.71, places=4)

    def test_net_carry_negative_when_farm_below_cost(self):
        r = make_report(farm_apr_pct=3.0, variable_borrow_apr_pct=5.0)
        self.assertLess(r.net_carry_variable_pct, 0.0)

    def test_net_carry_stable_negative(self):
        r = make_report(farm_apr_pct=3.0, stable_borrow_apr_pct=5.0)
        self.assertLess(r.net_carry_stable_pct, 0.0)

    def test_p95_carry_lower_than_expected_carry(self):
        r = make_report(variable_rate_volatility_pct=2.0)
        self.assertLessEqual(r.net_carry_variable_p95_pct, r.net_carry_variable_pct)

    def test_net_carry_variable_with_drift(self):
        r = make_report(farm_apr_pct=10.0, variable_borrow_apr_pct=4.0,
                        variable_rate_drift_pct=2.0)
        # expected_var=6, carry=4
        self.assertAlmostEqual(r.net_carry_variable_pct, 4.0, places=6)


# ---------------------------------------------------------------------------
# 8. Cost regime classification
# ---------------------------------------------------------------------------

class TestCostRegime(unittest.TestCase):

    def test_variable_strongly_cheaper(self):
        r = make_report(stable_borrow_apr_pct=10.0, variable_borrow_apr_pct=4.0)
        # adv = 6 >= 3
        self.assertEqual(r.cost_regime, "VARIABLE_STRONGLY_CHEAPER")

    def test_variable_cheaper(self):
        r = make_report(stable_borrow_apr_pct=6.0, variable_borrow_apr_pct=4.0)
        # adv = 2
        self.assertEqual(r.cost_regime, "VARIABLE_CHEAPER")

    def test_near_parity(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=4.5)
        # adv = 0.5
        self.assertEqual(r.cost_regime, "NEAR_PARITY")

    def test_stable_cheaper(self):
        r = make_report(stable_borrow_apr_pct=4.0, variable_borrow_apr_pct=6.0)
        # adv = -2
        self.assertEqual(r.cost_regime, "STABLE_CHEAPER")

    def test_stable_strongly_cheaper(self):
        r = make_report(stable_borrow_apr_pct=4.0, variable_borrow_apr_pct=10.0)
        # adv = -6
        self.assertEqual(r.cost_regime, "STABLE_STRONGLY_CHEAPER")

    def test_regime_at_plus_3_boundary(self):
        r = make_report(stable_borrow_apr_pct=7.0, variable_borrow_apr_pct=4.0)
        # adv = 3.0 -> STRONGLY
        self.assertEqual(r.cost_regime, "VARIABLE_STRONGLY_CHEAPER")

    def test_regime_at_plus_1_boundary(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=4.0)
        # adv = 1.0 -> VARIABLE_CHEAPER
        self.assertEqual(r.cost_regime, "VARIABLE_CHEAPER")

    def test_regime_just_below_1(self):
        r = make_report(stable_borrow_apr_pct=4.9, variable_borrow_apr_pct=4.0)
        # adv = 0.9 -> NEAR_PARITY
        self.assertEqual(r.cost_regime, "NEAR_PARITY")

    def test_regime_at_minus_1_boundary(self):
        r = make_report(stable_borrow_apr_pct=4.0, variable_borrow_apr_pct=5.0)
        # adv = -1.0 -> STABLE_CHEAPER
        self.assertEqual(r.cost_regime, "STABLE_CHEAPER")

    def test_regime_at_minus_3_boundary(self):
        r = make_report(stable_borrow_apr_pct=4.0, variable_borrow_apr_pct=7.0)
        # adv = -3.0 -> STABLE_STRONGLY_CHEAPER
        self.assertEqual(r.cost_regime, "STABLE_STRONGLY_CHEAPER")

    def test_regime_exact_zero_advantage(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=5.0)
        self.assertEqual(r.cost_regime, "NEAR_PARITY")

    def test_regime_valid_set(self):
        valid = {"VARIABLE_STRONGLY_CHEAPER", "VARIABLE_CHEAPER", "NEAR_PARITY",
                 "STABLE_CHEAPER", "STABLE_STRONGLY_CHEAPER"}
        for s, v in [(10, 4), (6, 4), (5, 4.5), (4, 6), (4, 10)]:
            r = make_report(stable_borrow_apr_pct=float(s), variable_borrow_apr_pct=float(v))
            self.assertIn(r.cost_regime, valid)


# ---------------------------------------------------------------------------
# 9. Recommended mode
# ---------------------------------------------------------------------------

class TestRecommendedMode(unittest.TestCase):

    def test_indifferent_near_zero_advantage(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=5.0)
        self.assertEqual(r.recommended_mode, "INDIFFERENT")

    def test_indifferent_within_epsilon(self):
        r = make_report(stable_borrow_apr_pct=5.05, variable_borrow_apr_pct=5.0)
        # adv = 0.05 <= 0.10
        self.assertEqual(r.recommended_mode, "INDIFFERENT")

    def test_variable_when_clearly_cheaper(self):
        r = make_report(stable_borrow_apr_pct=8.0, variable_borrow_apr_pct=4.0)
        self.assertEqual(r.recommended_mode, "VARIABLE")

    def test_stable_when_clearly_cheaper(self):
        r = make_report(stable_borrow_apr_pct=4.0, variable_borrow_apr_pct=8.0)
        self.assertEqual(r.recommended_mode, "STABLE")

    def test_mode_valid_set(self):
        valid = {"STABLE", "VARIABLE", "INDIFFERENT"}
        for s, v in [(8, 4), (4, 8), (5, 5), (6, 4), (4, 6)]:
            r = make_report(stable_borrow_apr_pct=float(s), variable_borrow_apr_pct=float(v))
            self.assertIn(r.recommended_mode, valid)

    def test_just_outside_epsilon_not_indifferent(self):
        r = make_report(stable_borrow_apr_pct=5.2, variable_borrow_apr_pct=5.0)
        # adv = 0.2 > 0.10
        self.assertNotEqual(r.recommended_mode, "INDIFFERENT")

    def test_high_rebalance_risk_pushes_to_variable(self):
        # Near parity but huge rebalance risk -> variable preferred
        r = make_report(stable_borrow_apr_pct=5.3, variable_borrow_apr_pct=5.0,
                        stable_rate_rebalance_risk_pct=100.0)
        self.assertEqual(r.recommended_mode, "VARIABLE")


# ---------------------------------------------------------------------------
# 10. Recommendation score
# ---------------------------------------------------------------------------

class TestRecommendationScore(unittest.TestCase):

    def test_score_in_range(self):
        for s, v in [(8, 4), (4, 8), (5, 5), (6, 4)]:
            r = make_report(stable_borrow_apr_pct=float(s), variable_borrow_apr_pct=float(v))
            self.assertGreaterEqual(r.mode_recommendation_score, 0.0)
            self.assertLessEqual(r.mode_recommendation_score, 100.0)

    def test_parity_score_around_50(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=5.0,
                        stable_rate_rebalance_risk_pct=0.0)
        self.assertAlmostEqual(r.mode_recommendation_score, 50.0, places=4)

    def test_variable_cheaper_score_above_50(self):
        r = make_report(stable_borrow_apr_pct=8.0, variable_borrow_apr_pct=4.0,
                        variable_rate_volatility_pct=0.0)
        self.assertGreater(r.mode_recommendation_score, 50.0)

    def test_stable_cheaper_score_below_50(self):
        r = make_report(stable_borrow_apr_pct=4.0, variable_borrow_apr_pct=8.0,
                        farm_apr_pct=20.0)
        self.assertLess(r.mode_recommendation_score, 50.0)

    def test_negative_p95_carry_lowers_score(self):
        r_safe = make_report(stable_borrow_apr_pct=6.0, variable_borrow_apr_pct=5.0,
                             variable_rate_volatility_pct=0.0, farm_apr_pct=20.0)
        r_tail = make_report(stable_borrow_apr_pct=6.0, variable_borrow_apr_pct=5.0,
                             variable_rate_volatility_pct=10.0, farm_apr_pct=6.0)
        self.assertLess(r_tail.mode_recommendation_score, r_safe.mode_recommendation_score)

    def test_low_certainty_raises_score(self):
        r_certain = make_report(stable_borrow_apr_pct=6.0, variable_borrow_apr_pct=5.5,
                                stable_rate_rebalance_risk_pct=0.0)
        r_uncertain = make_report(stable_borrow_apr_pct=6.0, variable_borrow_apr_pct=5.5,
                                  stable_rate_rebalance_risk_pct=100.0)
        self.assertGreater(r_uncertain.mode_recommendation_score,
                           r_certain.mode_recommendation_score)


# ---------------------------------------------------------------------------
# 11. Grade
# ---------------------------------------------------------------------------

class TestGrade(unittest.TestCase):

    def test_grade_valid_set(self):
        valid = {"A", "B", "C", "D", "F"}
        for s, v, f in [(8, 4, 20), (4, 8, 6), (5, 5, 10), (6, 4, 3)]:
            r = make_report(stable_borrow_apr_pct=float(s),
                            variable_borrow_apr_pct=float(v), farm_apr_pct=float(f))
            self.assertIn(r.grade, valid)

    def test_unprofitable_best_carry_low_grade(self):
        r = make_report(farm_apr_pct=2.0, stable_borrow_apr_pct=6.0,
                        variable_borrow_apr_pct=5.0)
        self.assertIn(r.grade, {"D", "F"})

    def test_deeply_unprofitable_grade_f(self):
        r = make_report(farm_apr_pct=1.0, stable_borrow_apr_pct=10.0,
                        variable_borrow_apr_pct=9.0)
        self.assertEqual(r.grade, "F")

    def test_clear_profitable_decision_high_grade(self):
        r = make_report(farm_apr_pct=20.0, stable_borrow_apr_pct=10.0,
                        variable_borrow_apr_pct=3.0, variable_rate_volatility_pct=0.0)
        self.assertIn(r.grade, {"A", "B"})

    def test_grade_is_string(self):
        r = make_report()
        self.assertIsInstance(r.grade, str)


# ---------------------------------------------------------------------------
# 12. Flags - VARIABLE_CHEAPER_NOW
# ---------------------------------------------------------------------------

class TestFlagVariableCheaper(unittest.TestCase):

    def test_flag_set_when_variable_cheaper(self):
        r = make_report(stable_borrow_apr_pct=6.0, variable_borrow_apr_pct=4.0)
        self.assertIn("VARIABLE_CHEAPER_NOW", r.flags)

    def test_flag_absent_when_stable_cheaper(self):
        r = make_report(stable_borrow_apr_pct=4.0, variable_borrow_apr_pct=6.0)
        self.assertNotIn("VARIABLE_CHEAPER_NOW", r.flags)

    def test_flag_absent_near_parity(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=5.0)
        self.assertNotIn("VARIABLE_CHEAPER_NOW", r.flags)


# ---------------------------------------------------------------------------
# 13. Flags - NEGATIVE_CARRY_AT_P95 / STABLE_SAFER_TAIL
# ---------------------------------------------------------------------------

class TestFlagNegativeCarryP95(unittest.TestCase):

    def test_negative_p95_carry_flag(self):
        r = make_report(farm_apr_pct=5.0, variable_borrow_apr_pct=4.0,
                        variable_rate_volatility_pct=5.0)
        # p95 = 4 + 1.645*5 = 12.225 > 5 -> negative carry
        self.assertIn("NEGATIVE_CARRY_AT_P95", r.flags)

    def test_stable_safer_tail_accompanies(self):
        r = make_report(farm_apr_pct=5.0, variable_borrow_apr_pct=4.0,
                        variable_rate_volatility_pct=5.0)
        self.assertIn("STABLE_SAFER_TAIL", r.flags)

    def test_no_negative_p95_when_carry_positive(self):
        r = make_report(farm_apr_pct=20.0, variable_borrow_apr_pct=4.0,
                        variable_rate_volatility_pct=1.0)
        self.assertNotIn("NEGATIVE_CARRY_AT_P95", r.flags)

    def test_no_stable_safer_tail_when_safe(self):
        r = make_report(farm_apr_pct=20.0, variable_borrow_apr_pct=4.0,
                        variable_rate_volatility_pct=1.0)
        self.assertNotIn("STABLE_SAFER_TAIL", r.flags)


# ---------------------------------------------------------------------------
# 14. Flags - HIGH_RATE_VOLATILITY
# ---------------------------------------------------------------------------

class TestFlagHighVolatility(unittest.TestCase):

    def test_high_vol_flag(self):
        r = make_report(variable_rate_volatility_pct=4.0)
        self.assertIn("HIGH_RATE_VOLATILITY", r.flags)

    def test_high_vol_at_threshold(self):
        r = make_report(variable_rate_volatility_pct=3.0)
        self.assertIn("HIGH_RATE_VOLATILITY", r.flags)

    def test_low_vol_no_flag(self):
        r = make_report(variable_rate_volatility_pct=1.0)
        self.assertNotIn("HIGH_RATE_VOLATILITY", r.flags)

    def test_zero_vol_no_flag(self):
        r = make_report(variable_rate_volatility_pct=0.0)
        self.assertNotIn("HIGH_RATE_VOLATILITY", r.flags)


# ---------------------------------------------------------------------------
# 15. Flags - STABLE_REBALANCE_RISK
# ---------------------------------------------------------------------------

class TestFlagRebalanceRisk(unittest.TestCase):

    def test_high_risk_flag(self):
        r = make_report(stable_rate_rebalance_risk_pct=50.0)
        self.assertIn("STABLE_REBALANCE_RISK", r.flags)

    def test_at_threshold_flag(self):
        r = make_report(stable_rate_rebalance_risk_pct=40.0)
        self.assertIn("STABLE_REBALANCE_RISK", r.flags)

    def test_low_risk_no_flag(self):
        r = make_report(stable_rate_rebalance_risk_pct=10.0)
        self.assertNotIn("STABLE_REBALANCE_RISK", r.flags)

    def test_zero_risk_no_flag(self):
        r = make_report(stable_rate_rebalance_risk_pct=0.0)
        self.assertNotIn("STABLE_REBALANCE_RISK", r.flags)


# ---------------------------------------------------------------------------
# 16. Flags - NEAR_BREAKEVEN
# ---------------------------------------------------------------------------

class TestFlagNearBreakeven(unittest.TestCase):

    def test_near_breakeven_flag(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=4.8)
        # headroom = 0.2 <= 0.5
        self.assertIn("NEAR_BREAKEVEN", r.flags)

    def test_exactly_at_breakeven(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=5.0)
        self.assertIn("NEAR_BREAKEVEN", r.flags)

    def test_far_from_breakeven_no_flag(self):
        r = make_report(stable_borrow_apr_pct=8.0, variable_borrow_apr_pct=4.0)
        self.assertNotIn("NEAR_BREAKEVEN", r.flags)

    def test_negative_headroom_near_breakeven(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=5.3)
        # headroom = -0.3, |.| = 0.3 <= 0.5
        self.assertIn("NEAR_BREAKEVEN", r.flags)


# ---------------------------------------------------------------------------
# 17. Flags - RISING / FALLING variable rate
# ---------------------------------------------------------------------------

class TestFlagDriftDirection(unittest.TestCase):

    def test_rising_flag(self):
        r = make_report(variable_rate_drift_pct=1.0)
        self.assertIn("RISING_VARIABLE_RATE", r.flags)

    def test_falling_flag(self):
        r = make_report(variable_rate_drift_pct=-1.0)
        self.assertIn("FALLING_VARIABLE_RATE", r.flags)

    def test_no_drift_neither_flag(self):
        r = make_report(variable_rate_drift_pct=0.0)
        self.assertNotIn("RISING_VARIABLE_RATE", r.flags)
        self.assertNotIn("FALLING_VARIABLE_RATE", r.flags)

    def test_tiny_drift_no_flag(self):
        r = make_report(variable_rate_drift_pct=0.01)
        self.assertNotIn("RISING_VARIABLE_RATE", r.flags)

    def test_rising_and_falling_mutually_exclusive(self):
        r = make_report(variable_rate_drift_pct=2.0)
        self.assertNotIn("FALLING_VARIABLE_RATE", r.flags)


# ---------------------------------------------------------------------------
# 18. INSUFFICIENT_DATA path
# ---------------------------------------------------------------------------

class TestInsufficientData(unittest.TestCase):

    def test_both_rates_zero_insufficient(self):
        r = make_report(stable_borrow_apr_pct=0.0, variable_borrow_apr_pct=0.0)
        self.assertIn("INSUFFICIENT_DATA", r.flags)

    def test_insufficient_grade_f(self):
        r = make_report(stable_borrow_apr_pct=0.0, variable_borrow_apr_pct=0.0)
        self.assertEqual(r.grade, "F")

    def test_insufficient_mode_indifferent(self):
        r = make_report(stable_borrow_apr_pct=0.0, variable_borrow_apr_pct=0.0)
        self.assertEqual(r.recommended_mode, "INDIFFERENT")

    def test_nan_stable_insufficient(self):
        r = make_report(stable_borrow_apr_pct=float("nan"), variable_borrow_apr_pct=4.0)
        self.assertIn("INSUFFICIENT_DATA", r.flags)

    def test_inf_variable_insufficient(self):
        r = make_report(variable_borrow_apr_pct=float("inf"))
        self.assertIn("INSUFFICIENT_DATA", r.flags)

    def test_insufficient_advisory_mentions(self):
        r = make_report(stable_borrow_apr_pct=0.0, variable_borrow_apr_pct=0.0)
        self.assertTrue(any("insufficient" in m.lower() for m in r.advisory))

    def test_insufficient_only_one_flag(self):
        r = make_report(stable_borrow_apr_pct=0.0, variable_borrow_apr_pct=0.0)
        self.assertEqual(r.flags, ["INSUFFICIENT_DATA"])

    def test_one_rate_nonzero_not_insufficient(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=0.0)
        self.assertNotIn("INSUFFICIENT_DATA", r.flags)


# ---------------------------------------------------------------------------
# 19. Horizon clamping
# ---------------------------------------------------------------------------

class TestHorizonClamping(unittest.TestCase):

    def test_zero_horizon_clamped_to_1(self):
        r = make_report(horizon_days=0)
        self.assertEqual(r.horizon_days, 1)

    def test_negative_horizon_clamped(self):
        r = make_report(horizon_days=-10)
        self.assertEqual(r.horizon_days, 1)

    def test_normal_horizon_preserved(self):
        r = make_report(horizon_days=90)
        self.assertEqual(r.horizon_days, 90)

    def test_horizon_is_int(self):
        r = make_report(horizon_days=45)
        self.assertIsInstance(r.horizon_days, int)


# ---------------------------------------------------------------------------
# 20. Report field types
# ---------------------------------------------------------------------------

class TestReportFieldTypes(unittest.TestCase):

    def setUp(self):
        self.r = make_report(protocol_name="Aave V3")

    def test_protocol_name_stored(self):
        self.assertEqual(self.r.protocol_name, "Aave V3")

    def test_expected_variable_is_float(self):
        self.assertIsInstance(self.r.expected_variable_apr_pct, float)

    def test_cost_advantage_is_float(self):
        self.assertIsInstance(self.r.cost_advantage_variable_pct, float)

    def test_mode_recommendation_score_is_float(self):
        self.assertIsInstance(self.r.mode_recommendation_score, float)

    def test_recommended_mode_is_str(self):
        self.assertIsInstance(self.r.recommended_mode, str)

    def test_cost_regime_is_str(self):
        self.assertIsInstance(self.r.cost_regime, str)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r.flags, list)

    def test_advisory_is_list(self):
        self.assertIsInstance(self.r.advisory, list)

    def test_advisory_not_empty(self):
        self.assertGreater(len(self.r.advisory), 0)

    def test_generated_at_non_empty(self):
        self.assertIsInstance(self.r.generated_at, str)
        self.assertGreater(len(self.r.generated_at), 0)

    def test_borrow_amount_preserved(self):
        r = make_report(borrow_amount_usd=250_000.0)
        self.assertAlmostEqual(r.borrow_amount_usd, 250_000.0, places=2)


# ---------------------------------------------------------------------------
# 21. Advisory content
# ---------------------------------------------------------------------------

class TestAdvisoryMessages(unittest.TestCase):

    def test_variable_advisory_mentions_variable(self):
        r = make_report(stable_borrow_apr_pct=8.0, variable_borrow_apr_pct=4.0,
                        protocol_name="Aave")
        self.assertTrue(any("VARIABLE" in m for m in r.advisory))

    def test_stable_advisory_mentions_stable(self):
        r = make_report(stable_borrow_apr_pct=4.0, variable_borrow_apr_pct=8.0,
                        protocol_name="Aave")
        self.assertTrue(any("STABLE" in m for m in r.advisory))

    def test_indifferent_advisory(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=5.0)
        self.assertTrue(any("parity" in m.lower() or "INDIFFERENT" in m for m in r.advisory))

    def test_protocol_name_in_advisory(self):
        r = make_report(protocol_name="MyMarket")
        self.assertTrue(any("MyMarket" in m for m in r.advisory))

    def test_negative_p95_advisory(self):
        r = make_report(farm_apr_pct=5.0, variable_borrow_apr_pct=4.0,
                        variable_rate_volatility_pct=5.0)
        self.assertTrue(any("NEGATIVE" in m or "tail" in m.lower() for m in r.advisory))

    def test_rebalance_risk_advisory(self):
        r = make_report(stable_rate_rebalance_risk_pct=60.0)
        self.assertTrue(any("re-price" in m or "certainty" in m.lower() for m in r.advisory))


# ---------------------------------------------------------------------------
# 22. Persistence
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def _temp_file(self) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        os.unlink(tmp.name)
        return Path(tmp.name)

    def test_save_creates_file(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        tf = self._temp_file()
        try:
            ana.save_report(make_report(), data_file=tf)
            self.assertTrue(tf.exists())
        finally:
            tf.unlink(missing_ok=True)

    def test_save_valid_json(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        tf = self._temp_file()
        try:
            ana.save_report(make_report(), data_file=tf)
            with open(tf) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
        finally:
            tf.unlink(missing_ok=True)

    def test_save_stores_one_entry(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        tf = self._temp_file()
        try:
            ana.save_report(make_report(), data_file=tf)
            data = json.loads(tf.read_text())
            self.assertEqual(len(data), 1)
        finally:
            tf.unlink(missing_ok=True)

    def test_save_accumulates(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        tf = self._temp_file()
        try:
            for _ in range(5):
                ana.save_report(make_report(), data_file=tf)
            self.assertEqual(len(json.loads(tf.read_text())), 5)
        finally:
            tf.unlink(missing_ok=True)

    def test_ring_buffer_cap(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        tf = self._temp_file()
        try:
            for _ in range(MAX_ENTRIES + 10):
                ana.save_report(make_report(), data_file=tf)
            self.assertEqual(len(json.loads(tf.read_text())), MAX_ENTRIES)
        finally:
            tf.unlink(missing_ok=True)

    def test_ring_buffer_keeps_recent(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        tf = self._temp_file()
        try:
            for i in range(MAX_ENTRIES + 5):
                ana.save_report(make_report(protocol_name=f"M{i}"), data_file=tf)
            data = json.loads(tf.read_text())
            self.assertEqual(data[-1]["protocol_name"], f"M{MAX_ENTRIES + 4}")
        finally:
            tf.unlink(missing_ok=True)

    def test_load_missing_file(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        self.assertEqual(ana.load_history(Path("/nonexistent/x.json")), [])

    def test_load_corrupt_file(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        tf = self._temp_file()
        try:
            tf.write_text("not-json")
            self.assertEqual(ana.load_history(tf), [])
        finally:
            tf.unlink(missing_ok=True)

    def test_entry_has_keys(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        tf = self._temp_file()
        try:
            ana.save_report(make_report(), data_file=tf)
            entry = json.loads(tf.read_text())[0]
            for key in ("timestamp", "protocol_name", "recommended_mode",
                        "cost_regime", "grade", "cost_advantage_variable_pct",
                        "mode_recommendation_score"):
                self.assertIn(key, entry)
        finally:
            tf.unlink(missing_ok=True)

    def test_atomic_no_tmp_left(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        tf = self._temp_file()
        try:
            ana.save_report(make_report(), data_file=tf)
            self.assertFalse(tf.with_suffix(".tmp").exists())
        finally:
            tf.unlink(missing_ok=True)

    def test_save_creates_parent_dirs(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        with tempfile.TemporaryDirectory() as td:
            nested = Path(td) / "a" / "b" / "out.json"
            ana.save_report(make_report(), data_file=nested)
            self.assertTrue(nested.exists())

    def test_entry_flags_is_list(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        tf = self._temp_file()
        try:
            ana.save_report(make_report(), data_file=tf)
            self.assertIsInstance(json.loads(tf.read_text())[0]["flags"], list)
        finally:
            tf.unlink(missing_ok=True)

    def test_entry_mode_matches(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        r = make_report(stable_borrow_apr_pct=8.0, variable_borrow_apr_pct=4.0)
        tf = self._temp_file()
        try:
            ana.save_report(r, data_file=tf)
            self.assertEqual(json.loads(tf.read_text())[0]["recommended_mode"],
                             r.recommended_mode)
        finally:
            tf.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 23. analyze_portfolio
# ---------------------------------------------------------------------------

class TestPortfolio(unittest.TestCase):

    def setUp(self):
        self.ana = DeFiProtocolBorrowRateModeOptimizer()

    def test_empty_portfolio(self):
        s = self.ana.analyze_portfolio([])
        self.assertEqual(s["count"], 0)

    def test_empty_portfolio_none_markets(self):
        s = self.ana.analyze_portfolio([])
        self.assertIsNone(s["cheapest_variable_market"])

    def test_count(self):
        s = self.ana.analyze_portfolio([make_position(), make_position()])
        self.assertEqual(s["count"], 2)

    def test_cheapest_market(self):
        s = self.ana.analyze_portfolio([
            make_position(variable_borrow_apr_pct=3.0, protocol_name="Cheap"),
            make_position(variable_borrow_apr_pct=8.0, protocol_name="Dear"),
        ])
        self.assertEqual(s["cheapest_variable_market"], "Cheap")

    def test_dearest_market(self):
        s = self.ana.analyze_portfolio([
            make_position(variable_borrow_apr_pct=3.0, protocol_name="Cheap"),
            make_position(variable_borrow_apr_pct=8.0, protocol_name="Dear"),
        ])
        self.assertEqual(s["most_expensive_variable_market"], "Dear")

    def test_avg_score(self):
        s = self.ana.analyze_portfolio([make_position(), make_position()])
        self.assertIsInstance(s["avg_mode_recommendation_score"], float)

    def test_mode_counts_sum(self):
        positions = [
            make_position(stable_borrow_apr_pct=8.0, variable_borrow_apr_pct=4.0),
            make_position(stable_borrow_apr_pct=4.0, variable_borrow_apr_pct=8.0),
            make_position(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=5.0),
        ]
        s = self.ana.analyze_portfolio(positions)
        total = (s["recommend_stable_count"] + s["recommend_variable_count"]
                 + s["recommend_indifferent_count"])
        self.assertEqual(total, 3)

    def test_variable_count(self):
        s = self.ana.analyze_portfolio([
            make_position(stable_borrow_apr_pct=8.0, variable_borrow_apr_pct=4.0),
        ])
        self.assertEqual(s["recommend_variable_count"], 1)

    def test_stable_count(self):
        s = self.ana.analyze_portfolio([
            make_position(stable_borrow_apr_pct=4.0, variable_borrow_apr_pct=8.0),
        ])
        self.assertEqual(s["recommend_stable_count"], 1)

    def test_indifferent_count(self):
        s = self.ana.analyze_portfolio([
            make_position(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=5.0),
        ])
        self.assertEqual(s["recommend_indifferent_count"], 1)

    def test_negative_carry_count(self):
        s = self.ana.analyze_portfolio([
            make_position(farm_apr_pct=2.0, stable_borrow_apr_pct=6.0,
                          variable_borrow_apr_pct=5.0),
        ])
        self.assertEqual(s["negative_carry_count"], 1)

    def test_no_negative_carry(self):
        s = self.ana.analyze_portfolio([
            make_position(farm_apr_pct=20.0, stable_borrow_apr_pct=4.0,
                          variable_borrow_apr_pct=3.0),
        ])
        self.assertEqual(s["negative_carry_count"], 0)

    def test_portfolio_with_insufficient(self):
        s = self.ana.analyze_portfolio([
            make_position(stable_borrow_apr_pct=0.0, variable_borrow_apr_pct=0.0),
            make_position(variable_borrow_apr_pct=3.0, protocol_name="Good"),
        ])
        self.assertEqual(s["cheapest_variable_market"], "Good")

    def test_portfolio_all_insufficient_none(self):
        s = self.ana.analyze_portfolio([
            make_position(stable_borrow_apr_pct=0.0, variable_borrow_apr_pct=0.0),
        ])
        self.assertIsNone(s["cheapest_variable_market"])


# ---------------------------------------------------------------------------
# 24. Stateless analyzer
# ---------------------------------------------------------------------------

class TestStateless(unittest.TestCase):

    def test_two_calls_independent(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        r1 = ana.analyze(8.0, 4.0, 0.0, 0.0, 30, 10.0, 1000.0, 0.0, "A")
        r2 = ana.analyze(4.0, 8.0, 0.0, 0.0, 30, 10.0, 1000.0, 0.0, "B")
        self.assertEqual(r1.recommended_mode, "VARIABLE")
        self.assertEqual(r2.recommended_mode, "STABLE")

    def test_repeated_call_same_result(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        r1 = ana.analyze(6.0, 4.0, 1.0, 2.0, 30, 10.0, 1000.0, 20.0, "X")
        r2 = ana.analyze(6.0, 4.0, 1.0, 2.0, 30, 10.0, 1000.0, 20.0, "X")
        self.assertEqual(r1.recommended_mode, r2.recommended_mode)
        self.assertAlmostEqual(r1.mode_recommendation_score, r2.mode_recommendation_score, places=8)

    def test_borrow_amount_does_not_affect_mode(self):
        ana = DeFiProtocolBorrowRateModeOptimizer()
        r1 = ana.analyze(6.0, 4.0, 0.0, 0.0, 30, 10.0, 1_000.0, 0.0, "P")
        r2 = ana.analyze(6.0, 4.0, 0.0, 0.0, 30, 10.0, 1_000_000.0, 0.0, "P")
        self.assertEqual(r1.recommended_mode, r2.recommended_mode)


# ---------------------------------------------------------------------------
# 25. Known scenarios
# ---------------------------------------------------------------------------

class TestKnownScenarios(unittest.TestCase):

    def test_variable_clearly_better(self):
        r = make_report(stable_borrow_apr_pct=8.0, variable_borrow_apr_pct=3.0,
                        variable_rate_drift_pct=0.0, variable_rate_volatility_pct=0.5,
                        farm_apr_pct=12.0)
        self.assertEqual(r.recommended_mode, "VARIABLE")

    def test_stable_better_high_vol(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=5.2,
                        variable_rate_drift_pct=2.0, variable_rate_volatility_pct=6.0,
                        farm_apr_pct=8.0)
        self.assertEqual(r.recommended_mode, "STABLE")

    def test_rising_rates_favor_stable_lock(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=4.5,
                        variable_rate_drift_pct=2.0, farm_apr_pct=8.0)
        # expected_var = 6.5 > 5 stable -> stable cheaper
        self.assertEqual(r.recommended_mode, "STABLE")

    def test_falling_rates_favor_variable(self):
        r = make_report(stable_borrow_apr_pct=5.0, variable_borrow_apr_pct=5.5,
                        variable_rate_drift_pct=-2.0, farm_apr_pct=10.0)
        # expected_var = 3.5 < 5 -> variable cheaper
        self.assertEqual(r.recommended_mode, "VARIABLE")

    def test_negative_carry_both_modes(self):
        r = make_report(farm_apr_pct=3.0, stable_borrow_apr_pct=6.0,
                        variable_borrow_apr_pct=7.0)
        self.assertLess(r.net_carry_stable_pct, 0.0)
        self.assertLess(r.net_carry_variable_pct, 0.0)


# ---------------------------------------------------------------------------
# 26. Numerical edge cases
# ---------------------------------------------------------------------------

class TestNumericalEdge(unittest.TestCase):

    def test_very_high_rates(self):
        r = make_report(stable_borrow_apr_pct=200.0, variable_borrow_apr_pct=150.0)
        self.assertIsInstance(r.cost_advantage_variable_pct, float)

    def test_very_small_rates(self):
        r = make_report(stable_borrow_apr_pct=0.01, variable_borrow_apr_pct=0.02)
        self.assertIsInstance(r.recommended_mode, str)

    def test_negative_farm_apr(self):
        r = make_report(farm_apr_pct=-5.0)
        self.assertLess(r.net_carry_variable_pct, 0.0)

    def test_negative_stable_apr(self):
        # Incentivised negative borrow rate
        r = make_report(stable_borrow_apr_pct=-1.0, variable_borrow_apr_pct=2.0)
        self.assertEqual(r.recommended_mode, "STABLE")

    def test_extreme_volatility(self):
        r = make_report(variable_rate_volatility_pct=50.0)
        self.assertIn("HIGH_RATE_VOLATILITY", r.flags)

    def test_score_clamped_at_extreme_advantage(self):
        r = make_report(stable_borrow_apr_pct=100.0, variable_borrow_apr_pct=1.0)
        self.assertLessEqual(r.mode_recommendation_score, 100.0)

    def test_score_clamped_at_extreme_negative(self):
        r = make_report(stable_borrow_apr_pct=1.0, variable_borrow_apr_pct=100.0,
                        farm_apr_pct=0.0, variable_rate_volatility_pct=20.0)
        self.assertGreaterEqual(r.mode_recommendation_score, 0.0)


# ---------------------------------------------------------------------------
# 27. Rounding / determinism
# ---------------------------------------------------------------------------

class TestRounding(unittest.TestCase):

    def test_fields_rounded(self):
        r = make_report(stable_borrow_apr_pct=6.123456789,
                        variable_borrow_apr_pct=4.987654321)
        self.assertLessEqual(len(str(r.cost_advantage_variable_pct).split(".")[-1]), 8)

    def test_expected_variable_rounded(self):
        r = make_report(variable_borrow_apr_pct=4.111111111,
                        variable_rate_drift_pct=0.222222222)
        self.assertIsInstance(r.expected_variable_apr_pct, float)


if __name__ == "__main__":
    unittest.main()
