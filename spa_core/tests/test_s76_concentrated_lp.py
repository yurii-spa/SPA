"""
spa_core/tests/test_s76_concentrated_lp.py

Tests for S76ConcentratedLP (spa_core/strategies/s76_concentrated_lp.py).

AUD-18 — coverage for previously untested tournament strategies.

Run:
    python3 -m unittest spa_core.tests.test_s76_concentrated_lp -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.s76_concentrated_lp import (
    ALLOC_LP_ACTIVE,
    ALLOC_LP_OFF,
    FALLBACK_APY,
    LP_ATTRACTIVE_THRESHOLD,
    PROTOCOL_TIERS,
    RISK_TIER,
    S76ConcentratedLP,
    STRATEGY_ID,
    STRATEGY_NAME,
    TARGET_APY_MAX,
    TARGET_APY_MIN,
)


class TestModuleConstants(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(STRATEGY_ID, "S76")
        self.assertEqual(RISK_TIER, "T2")
        self.assertTrue(STRATEGY_NAME)

    def test_apy_targets_ordered(self):
        self.assertLess(TARGET_APY_MIN, TARGET_APY_MAX)

    def test_threshold_is_decimal_fraction(self):
        self.assertEqual(LP_ATTRACTIVE_THRESHOLD, 0.06)

    def test_regime_allocations_sum_to_one(self):
        self.assertAlmostEqual(sum(ALLOC_LP_ACTIVE.values()), 1.0, places=9)
        self.assertAlmostEqual(sum(ALLOC_LP_OFF.values()), 1.0, places=9)

    def test_cash_buffer_at_least_15pct_in_both_regimes(self):
        self.assertGreaterEqual(ALLOC_LP_ACTIVE["cash"], 0.15)
        self.assertGreaterEqual(ALLOC_LP_OFF["cash"], 0.15)

    def test_every_alloc_key_has_tier(self):
        for key in {**ALLOC_LP_ACTIVE, **ALLOC_LP_OFF}:
            self.assertIn(key, PROTOCOL_TIERS)


class TestAllocateRegimes(unittest.TestCase):
    def setUp(self):
        self.strat = S76ConcentratedLP()

    def test_lp_active_above_threshold(self):
        weights = self.strat.allocate({"aerodrome_usdc_lp": 0.085})
        self.assertEqual(weights, ALLOC_LP_ACTIVE)

    def test_lp_off_below_threshold(self):
        weights = self.strat.allocate({"aerodrome_usdc_lp": 0.04})
        self.assertEqual(weights, ALLOC_LP_OFF)

    def test_exactly_at_threshold_is_lp_off(self):
        # Strictly `>` comparison: 0.06 is NOT attractive.
        weights = self.strat.allocate({"aerodrome_usdc_lp": LP_ATTRACTIVE_THRESHOLD})
        self.assertEqual(weights, ALLOC_LP_OFF)
        self.assertEqual(
            self.strat.current_regime({"aerodrome_usdc_lp": LP_ATTRACTIVE_THRESHOLD}),
            "lp_off",
        )

    def test_missing_key_uses_fallback_and_activates_lp(self):
        # Fallback 0.085 > 0.06 → lp_active.
        self.assertEqual(self.strat.allocate({}), ALLOC_LP_ACTIVE)
        self.assertEqual(self.strat.current_regime({}), "lp_active")

    def test_weights_sum_to_one_in_both_regimes(self):
        for apy in (0.085, 0.04):
            weights = self.strat.allocate({"aerodrome_usdc_lp": apy})
            self.assertAlmostEqual(sum(weights.values()), 1.0, places=9)

    def test_allocate_returns_copy_not_module_dict(self):
        weights = self.strat.allocate({"aerodrome_usdc_lp": 0.085})
        weights["cash"] = 0.99
        self.assertEqual(ALLOC_LP_ACTIVE["cash"], 0.15)

    def test_deterministic(self):
        snap = {"aerodrome_usdc_lp": 0.07}
        self.assertEqual(self.strat.allocate(snap), self.strat.allocate(snap))


class TestCurrentRegime(unittest.TestCase):
    def setUp(self):
        self.strat = S76ConcentratedLP()

    def test_labels(self):
        self.assertEqual(
            self.strat.current_regime({"aerodrome_usdc_lp": 0.10}), "lp_active"
        )
        self.assertEqual(
            self.strat.current_regime({"aerodrome_usdc_lp": 0.01}), "lp_off"
        )


class TestComputeWeightedApy(unittest.TestCase):
    def setUp(self):
        self.strat = S76ConcentratedLP()

    def test_default_matches_docstring_lp_active(self):
        # Fallback: aerodrome 0.085 decimal → 8.5%;
        # 0.60*8.5 + 0.25*3.5 + 0.15*0.0 = 5.975
        self.assertAlmostEqual(self.strat.compute_weighted_apy(), 5.975, places=6)

    def test_lp_off_blend_matches_docstring(self):
        # lp_apy 0.04 → lp_off regime; aerodrome not in weights.
        # 0.50*3.5 + 0.35*4.8 + 0.15*0.0 = 3.43
        apy = self.strat.compute_weighted_apy({"aerodrome_usdc_lp": 0.04})
        self.assertAlmostEqual(apy, 3.43, places=6)

    def test_decimal_lp_apy_scaled_to_percent(self):
        # aerodrome supplied as decimal 0.10 (<1.0) → blended as 10%.
        apy = self.strat.compute_weighted_apy({"aerodrome_usdc_lp": 0.10})
        expected = 0.60 * 10.0 + 0.25 * FALLBACK_APY["aave_v3"]
        self.assertAlmostEqual(apy, expected, places=6)

    def test_percent_lp_apy_not_double_scaled(self):
        # aerodrome supplied in percent (8.5 ≥ 1.0) → used as-is.
        apy = self.strat.compute_weighted_apy({"aerodrome_usdc_lp": 8.5})
        expected = 0.60 * 8.5 + 0.25 * FALLBACK_APY["aave_v3"]
        self.assertAlmostEqual(apy, expected, places=6)

    def test_result_within_target_band(self):
        apy = self.strat.compute_weighted_apy()
        self.assertGreaterEqual(apy, TARGET_APY_MIN)
        self.assertLessEqual(apy, TARGET_APY_MAX)


class TestAdvisoryContract(unittest.TestCase):
    def setUp(self):
        self.strat = S76ConcentratedLP()

    def test_is_advisory_true(self):
        self.assertTrue(S76ConcentratedLP.IS_ADVISORY)
        self.assertTrue(self.strat.IS_ADVISORY)

    def test_no_execution_import(self):
        import spa_core.strategies.s76_concentrated_lp as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("spa_core.execution", source)

    def test_get_info_keys(self):
        info = self.strat.get_info()
        for key in (
            "strategy_id", "strategy_name", "risk_tier", "expected_apy_pct",
            "is_advisory", "caveat", "lp_attractive_threshold",
            "alloc_lp_active", "alloc_lp_off", "fallback_apy",
            "protocol_tiers", "generated_at",
        ):
            self.assertIn(key, info)
        self.assertEqual(info["strategy_id"], "S76")
        self.assertEqual(info["risk_tier"], "T2")
        self.assertTrue(info["is_advisory"])

    def test_get_info_returns_copies(self):
        info = self.strat.get_info()
        info["alloc_lp_active"]["cash"] = 0.99
        self.assertEqual(ALLOC_LP_ACTIVE["cash"], 0.15)


class TestRegistryIntegration(unittest.TestCase):
    def test_registered_in_tournament_registry(self):
        from spa_core.strategies.strategy_registry import REGISTRY
        meta = REGISTRY.get("S76")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.risk_tier, "T2")
        self.assertEqual(meta.type, "lp")
        self.assertEqual(meta.handler_class, "S76ConcentratedLP")


if __name__ == "__main__":
    unittest.main(verbosity=2)
