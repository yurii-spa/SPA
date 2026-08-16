"""
spa_core/tests/test_s73_leverage_loop.py

Tests for S73LeverageLoop (spa_core/strategies/s73_leverage_loop.py).

AUD-18 — coverage for previously untested tournament strategies.

Run:
    python3 -m unittest spa_core.tests.test_s73_leverage_loop -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.s73_leverage_loop import (
    ALLOCATION,
    BORROW_RATE_DEFAULT,
    LEVERAGE_RATIO,
    LIQUIDATION_THRESHOLD,
    RISK_TIER,
    S73LeverageLoop,
    STAKING_APY_DEFAULT,
    STRATEGY_ID,
    TARGET_APY_MAX,
    TARGET_APY_MIN,
)


class TestModuleConstants(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(STRATEGY_ID, "S73")
        self.assertEqual(RISK_TIER, "T3")

    def test_apy_targets_ordered(self):
        self.assertLess(TARGET_APY_MIN, TARGET_APY_MAX)

    def test_allocation_sums_to_one(self):
        self.assertAlmostEqual(sum(ALLOCATION.values()), 1.0, places=9)

    def test_cash_buffer_at_least_15pct(self):
        # 15% cash covers liquidation margin per module docstring.
        self.assertGreaterEqual(ALLOCATION["cash"], 0.15)

    def test_leverage_parameters_sane(self):
        self.assertGreater(LEVERAGE_RATIO, 1.0)
        self.assertLessEqual(LEVERAGE_RATIO, 3.0)
        self.assertGreater(LIQUIDATION_THRESHOLD, 0.0)
        self.assertLess(LIQUIDATION_THRESHOLD, 1.0)


class TestAllocate(unittest.TestCase):
    def setUp(self):
        self.strat = S73LeverageLoop()

    def test_static_allocation(self):
        self.assertEqual(self.strat.allocate({}), ALLOCATION)
        # apy_data is ignored — same result for any snapshot.
        self.assertEqual(
            self.strat.allocate({"aave_v3_wsteth": 99.0}), ALLOCATION
        )

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(self.strat.allocate({}).values()), 1.0, places=9)

    def test_returns_copy(self):
        weights = self.strat.allocate({})
        weights["cash"] = 0.99
        self.assertEqual(ALLOCATION["cash"], 0.15)

    def test_deterministic(self):
        self.assertEqual(self.strat.allocate({}), self.strat.allocate({}))


class TestEffectiveApy(unittest.TestCase):
    """effective_apy = staking * L - borrow * (L - 1), L = 2.0."""

    def setUp(self):
        self.strat = S73LeverageLoop()

    def test_docstring_example(self):
        # 3.5 * 2.0 - 1.5 * 1.0 = 5.5
        self.assertAlmostEqual(self.strat.effective_apy(3.5, 1.5), 5.5, places=9)

    def test_zero_borrow_doubles_staking(self):
        self.assertAlmostEqual(self.strat.effective_apy(4.0, 0.0), 8.0, places=9)

    def test_high_borrow_rate_goes_negative(self):
        # 2.0 * 2.0 - 10.0 * 1.0 = -6.0 — loop is value-destructive.
        self.assertAlmostEqual(self.strat.effective_apy(2.0, 10.0), -6.0, places=9)

    def test_breakeven_borrow_rate(self):
        # staking * L == borrow * (L - 1)  →  borrow = staking * L / (L - 1)
        staking = 3.0
        breakeven = staking * LEVERAGE_RATIO / (LEVERAGE_RATIO - 1.0)
        self.assertAlmostEqual(
            self.strat.effective_apy(staking, breakeven), 0.0, places=9
        )

    def test_default_constants_within_target_band(self):
        eff = self.strat.effective_apy(STAKING_APY_DEFAULT, BORROW_RATE_DEFAULT)
        self.assertGreaterEqual(eff, TARGET_APY_MIN)
        self.assertLessEqual(eff, TARGET_APY_MAX)


class TestComputeWeightedApy(unittest.TestCase):
    def setUp(self):
        self.strat = S73LeverageLoop()

    def test_default_uses_effective_apy_with_cash_drag(self):
        eff = self.strat.effective_apy(STAKING_APY_DEFAULT, BORROW_RATE_DEFAULT)
        expected = ALLOCATION["aave_v3_wsteth"] * eff  # cash contributes 0
        self.assertAlmostEqual(self.strat.compute_weighted_apy(), expected, places=9)

    def test_override_via_apy_data(self):
        apy = self.strat.compute_weighted_apy({"aave_v3_wsteth": 10.0})
        self.assertAlmostEqual(apy, ALLOCATION["aave_v3_wsteth"] * 10.0, places=9)

    def test_none_equals_empty_dict(self):
        self.assertAlmostEqual(
            self.strat.compute_weighted_apy(None),
            self.strat.compute_weighted_apy({}),
            places=9,
        )


class TestEligibility(unittest.TestCase):
    def setUp(self):
        self.strat = S73LeverageLoop()

    def test_default_100k_eligible(self):
        self.assertTrue(self.strat.is_eligible())

    def test_below_min_capital_not_eligible(self):
        self.assertFalse(self.strat.is_eligible(capital_usd=40_000.0))

    def test_boundary_exactly_min_is_eligible(self):
        self.assertTrue(
            self.strat.is_eligible(min_capital_usd=50_000.0, capital_usd=50_000.0)
        )


class TestAdvisoryContract(unittest.TestCase):
    def setUp(self):
        self.strat = S73LeverageLoop()

    def test_is_advisory_true(self):
        self.assertTrue(S73LeverageLoop.IS_ADVISORY)

    def test_no_execution_import(self):
        import spa_core.strategies.s73_leverage_loop as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("spa_core.execution", source)

    def test_get_info_keys(self):
        info = self.strat.get_info()
        for key in (
            "strategy_id", "strategy_name", "risk_tier", "expected_apy_pct",
            "is_advisory", "caveat", "leverage_ratio", "liquidation_threshold",
            "effective_apy_default", "allocation", "generated_at",
        ):
            self.assertIn(key, info)
        self.assertEqual(info["strategy_id"], "S73")
        self.assertEqual(info["risk_tier"], "T3")
        self.assertAlmostEqual(info["effective_apy_default"], 5.5, places=9)


class TestRegistryIntegration(unittest.TestCase):
    def test_registered_in_tournament_registry(self):
        from spa_core.strategies.strategy_registry import REGISTRY
        meta = REGISTRY.get("S73")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.risk_tier, "T3")
        self.assertEqual(meta.type, "yield_loop")
        self.assertEqual(meta.handler_class, "S73LeverageLoop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
