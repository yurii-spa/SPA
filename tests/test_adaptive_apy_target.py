"""
tests/test_adaptive_apy_target.py

40 unit tests for spa_core/analytics/adaptive_apy_target.py

Coverage:
  TestInstantiation       (4 tests)  — valid/invalid construction
  TestCurrentTarget       (8 tests)  — per-regime target values
  TestRecommendedAction   (6 tests)  — action strings per regime
  TestIsSuspended         (4 tests)  — suspension logic
  TestTargetRange         (4 tests)  — full bear/neutral/bull range dict
  TestForRegime           (6 tests)  — class method for all strategies
  TestRegimeChangeImpact  (6 tests)  — delta, required_action, suspended flag
  TestEdgeCases           (2 tests)  — non-empty action, unknown regime guard

Sprint v9.44 — MP-1328
Date: 2026-06-19
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.analytics.adaptive_apy_target import (
    AdaptiveAPYTarget,
    STRATEGIES_APY_CONFIG,
    VALID_REGIMES,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TestInstantiation (4 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestInstantiation(unittest.TestCase):

    def test_can_instantiate_s20_neutral(self):
        t = AdaptiveAPYTarget("S20_RS001", "neutral")
        self.assertEqual(t.strategy_id, "S20_RS001")
        self.assertEqual(t.current_regime, "neutral")

    def test_can_instantiate_s21_bear(self):
        t = AdaptiveAPYTarget("S21_RS002", "bear")
        self.assertEqual(t.strategy_id, "S21_RS002")
        self.assertEqual(t.current_regime, "bear")

    def test_can_instantiate_s20_bull(self):
        t = AdaptiveAPYTarget("S20_RS001", "bull")
        self.assertIsNotNone(t)

    def test_unknown_strategy_raises_value_error(self):
        with self.assertRaises(ValueError):
            AdaptiveAPYTarget("S99_UNKNOWN", "neutral")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TestCurrentTarget (8 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCurrentTarget(unittest.TestCase):

    def test_s20_bear_target_is_8(self):
        t = AdaptiveAPYTarget("S20_RS001", "bear")
        self.assertAlmostEqual(t.current_target(), 8.0, places=4)

    def test_s20_neutral_target_is_18_2(self):
        t = AdaptiveAPYTarget("S20_RS001", "neutral")
        self.assertAlmostEqual(t.current_target(), 18.2, places=4)

    def test_s20_bull_target_is_22(self):
        t = AdaptiveAPYTarget("S20_RS001", "bull")
        self.assertAlmostEqual(t.current_target(), 22.0, places=4)

    def test_s21_bear_target_is_0(self):
        t = AdaptiveAPYTarget("S21_RS002", "bear")
        self.assertAlmostEqual(t.current_target(), 0.0, places=4)

    def test_s21_neutral_target_is_15(self):
        t = AdaptiveAPYTarget("S21_RS002", "neutral")
        self.assertAlmostEqual(t.current_target(), 15.0, places=4)

    def test_s21_bull_target_is_20(self):
        t = AdaptiveAPYTarget("S21_RS002", "bull")
        self.assertAlmostEqual(t.current_target(), 20.0, places=4)

    def test_rs001_bear_target_less_than_neutral(self):
        bear = AdaptiveAPYTarget("S20_RS001", "bear").current_target()
        neutral = AdaptiveAPYTarget("S20_RS001", "neutral").current_target()
        self.assertLess(bear, neutral)

    def test_rs001_bull_target_greater_than_neutral(self):
        bull = AdaptiveAPYTarget("S20_RS001", "bull").current_target()
        neutral = AdaptiveAPYTarget("S20_RS001", "neutral").current_target()
        self.assertGreater(bull, neutral)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TestRecommendedAction (6 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecommendedAction(unittest.TestCase):

    def test_s20_bear_action(self):
        t = AdaptiveAPYTarget("S20_RS001", "bear")
        self.assertEqual(t.recommended_action(), "REDUCE_CRYPTO_EXPOSURE")

    def test_s20_neutral_action(self):
        t = AdaptiveAPYTarget("S20_RS001", "neutral")
        self.assertEqual(t.recommended_action(), "FULL_ALLOCATION")

    def test_s20_bull_action(self):
        t = AdaptiveAPYTarget("S20_RS001", "bull")
        self.assertEqual(t.recommended_action(), "INCREASE_GMX_WEIGHT")

    def test_s21_bear_action_is_suspend(self):
        t = AdaptiveAPYTarget("S21_RS002", "bear")
        self.assertEqual(t.recommended_action(), "SUSPEND")

    def test_s21_neutral_action(self):
        t = AdaptiveAPYTarget("S21_RS002", "neutral")
        self.assertEqual(t.recommended_action(), "CONSERVATIVE_RANGES")

    def test_s21_bull_action(self):
        t = AdaptiveAPYTarget("S21_RS002", "bull")
        self.assertEqual(t.recommended_action(), "WIDER_RANGES")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TestIsSuspended (4 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsSuspended(unittest.TestCase):

    def test_s21_bear_is_suspended_true(self):
        t = AdaptiveAPYTarget("S21_RS002", "bear")
        self.assertTrue(t.is_suspended())

    def test_s21_neutral_is_not_suspended(self):
        t = AdaptiveAPYTarget("S21_RS002", "neutral")
        self.assertFalse(t.is_suspended())

    def test_s21_bull_is_not_suspended(self):
        t = AdaptiveAPYTarget("S21_RS002", "bull")
        self.assertFalse(t.is_suspended())

    def test_s20_neutral_is_not_suspended(self):
        t = AdaptiveAPYTarget("S20_RS001", "neutral")
        self.assertFalse(t.is_suspended())


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TestTargetRange (4 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestTargetRange(unittest.TestCase):

    def test_target_range_returns_dict(self):
        t = AdaptiveAPYTarget("S20_RS001", "neutral")
        r = t.target_range()
        self.assertIsInstance(r, dict)

    def test_target_range_has_all_regimes(self):
        t = AdaptiveAPYTarget("S20_RS001", "neutral")
        r = t.target_range()
        for regime in VALID_REGIMES:
            self.assertIn(regime, r)

    def test_s20_target_range_bear_less_than_neutral(self):
        t = AdaptiveAPYTarget("S20_RS001", "neutral")
        r = t.target_range()
        self.assertLess(r["bear"], r["neutral"])

    def test_s21_target_range_neutral_less_than_bull(self):
        t = AdaptiveAPYTarget("S21_RS002", "neutral")
        r = t.target_range()
        self.assertLess(r["neutral"], r["bull"])


# ═══════════════════════════════════════════════════════════════════════════════
# 6. TestForRegime (6 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestForRegime(unittest.TestCase):

    def test_for_regime_bear_returns_dict(self):
        result = AdaptiveAPYTarget.for_regime("bear")
        self.assertIsInstance(result, dict)

    def test_for_regime_neutral_contains_all_strategies(self):
        result = AdaptiveAPYTarget.for_regime("neutral")
        for sid in STRATEGIES_APY_CONFIG:
            self.assertIn(sid, result)

    def test_for_regime_bull_contains_all_strategies(self):
        result = AdaptiveAPYTarget.for_regime("bull")
        for sid in STRATEGIES_APY_CONFIG:
            self.assertIn(sid, result)

    def test_for_regime_bear_s20_target(self):
        result = AdaptiveAPYTarget.for_regime("bear")
        self.assertAlmostEqual(result["S20_RS001"]["target"], 8.0, places=4)

    def test_for_regime_neutral_s21_target(self):
        result = AdaptiveAPYTarget.for_regime("neutral")
        self.assertAlmostEqual(result["S21_RS002"]["target"], 15.0, places=4)

    def test_for_regime_bull_s20_target(self):
        result = AdaptiveAPYTarget.for_regime("bull")
        self.assertAlmostEqual(result["S20_RS001"]["target"], 22.0, places=4)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. TestRegimeChangeImpact (6 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegimeChangeImpact(unittest.TestCase):

    def test_impact_returns_dict_with_required_keys(self):
        t = AdaptiveAPYTarget("S20_RS001", "neutral")
        impact = t.regime_change_impact("neutral", "bear")
        required = {"strategy_id", "from_regime", "to_regime",
                    "from_target", "to_target", "delta", "required_action",
                    "suspended_in_to"}
        self.assertTrue(required.issubset(impact.keys()))

    def test_s20_neutral_to_bear_delta_negative(self):
        t = AdaptiveAPYTarget("S20_RS001", "neutral")
        impact = t.regime_change_impact("neutral", "bear")
        self.assertLess(impact["delta"], 0.0)

    def test_s20_neutral_to_bull_delta_positive(self):
        t = AdaptiveAPYTarget("S20_RS001", "neutral")
        impact = t.regime_change_impact("neutral", "bull")
        self.assertGreater(impact["delta"], 0.0)

    def test_s21_bear_to_neutral_not_suspended(self):
        t = AdaptiveAPYTarget("S21_RS002", "bear")
        impact = t.regime_change_impact("bear", "neutral")
        self.assertFalse(impact["suspended_in_to"])

    def test_delta_equals_to_minus_from(self):
        t = AdaptiveAPYTarget("S20_RS001", "neutral")
        impact = t.regime_change_impact("neutral", "bull")
        expected_delta = impact["to_target"] - impact["from_target"]
        self.assertAlmostEqual(impact["delta"], expected_delta, places=4)

    def test_s21_neutral_to_bear_is_suspended_in_to(self):
        t = AdaptiveAPYTarget("S21_RS002", "neutral")
        impact = t.regime_change_impact("neutral", "bear")
        self.assertTrue(impact["suspended_in_to"])


# ═══════════════════════════════════════════════════════════════════════════════
# 8. TestEdgeCases (2 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases(unittest.TestCase):

    def test_recommended_action_always_non_empty(self):
        for sid in STRATEGIES_APY_CONFIG:
            for regime in VALID_REGIMES:
                t = AdaptiveAPYTarget(sid, regime)
                action = t.recommended_action()
                self.assertTrue(
                    len(action) > 0,
                    msg=f"{sid}/{regime}: action should not be empty"
                )

    def test_unknown_regime_raises_value_error(self):
        with self.assertRaises(ValueError):
            AdaptiveAPYTarget("S20_RS001", "sideways")


if __name__ == "__main__":
    unittest.main(verbosity=2)
