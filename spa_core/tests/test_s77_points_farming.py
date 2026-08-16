"""
spa_core/tests/test_s77_points_farming.py

Tests for S77PointsFarming (spa_core/strategies/s77_points_farming.py).

AUD-18 — coverage for previously untested tournament strategies.

Run:
    python3 -m unittest spa_core.tests.test_s77_points_farming -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.s77_points_farming import (
    ALLOCATION,
    FALLBACK_APY,
    POINTS_APY_PREMIUM_PCT,
    PROTOCOL_TIERS,
    REWARD_CAMPAIGNS,
    RISK_TIER,
    S77PointsFarming,
    STRATEGY_ID,
    TARGET_APY_MAX,
    TARGET_APY_MIN,
)


class TestModuleConstants(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(STRATEGY_ID, "S77")
        self.assertEqual(RISK_TIER, "T3")

    def test_apy_targets_ordered(self):
        self.assertLess(TARGET_APY_MIN, TARGET_APY_MAX)

    def test_allocation_sums_to_one(self):
        self.assertAlmostEqual(sum(ALLOCATION.values()), 1.0, places=9)

    def test_cash_buffer_at_least_15pct(self):
        # Points farming can be illiquid — 15% buffer per module docstring.
        self.assertGreaterEqual(ALLOCATION["cash"], 0.15)

    def test_every_alloc_key_has_tier(self):
        for key in ALLOCATION:
            self.assertIn(key, PROTOCOL_TIERS)

    def test_non_cash_protocols_have_campaign_entries(self):
        for key in ALLOCATION:
            if key == "cash":
                continue
            self.assertIn(key, REWARD_CAMPAIGNS)


class TestAllocate(unittest.TestCase):
    def setUp(self):
        self.strat = S77PointsFarming()

    def test_static_allocation(self):
        self.assertEqual(self.strat.allocate({}), ALLOCATION)
        self.assertEqual(self.strat.allocate({"morpho_steakhouse": 99.0}), ALLOCATION)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(self.strat.allocate({}).values()), 1.0, places=9)

    def test_returns_copy(self):
        weights = self.strat.allocate({})
        weights["cash"] = 0.99
        self.assertEqual(ALLOCATION["cash"], 0.15)

    def test_deterministic(self):
        self.assertEqual(self.strat.allocate({}), self.strat.allocate({}))


class TestComputeWeightedApy(unittest.TestCase):
    def setUp(self):
        self.strat = S77PointsFarming()

    def test_default_matches_docstring_blend(self):
        # 0.40*6.5 + 0.25*14.0 + 0.20*4.2 + 0.15*0.0 = 6.94
        self.assertAlmostEqual(self.strat.compute_weighted_apy(), 6.94, places=6)

    def test_base_apy_excludes_points_premium(self):
        base = self.strat.compute_weighted_apy()
        self.assertLess(base, base + POINTS_APY_PREMIUM_PCT)

    def test_live_apy_overrides_fallback(self):
        apy = self.strat.compute_weighted_apy({"morpho_steakhouse": 10.0})
        expected = (
            0.40 * 10.0
            + 0.25 * FALLBACK_APY["pendle_yt_susde"]
            + 0.20 * FALLBACK_APY["spark_susds"]
        )
        self.assertAlmostEqual(apy, expected, places=6)

    def test_base_within_target_band(self):
        base = self.strat.compute_weighted_apy()
        self.assertGreaterEqual(base, TARGET_APY_MIN)
        self.assertLessEqual(base, TARGET_APY_MAX)


class TestPointsAdjustedApy(unittest.TestCase):
    def setUp(self):
        self.strat = S77PointsFarming()

    def test_default_premium_added(self):
        base = self.strat.compute_weighted_apy()
        adjusted = self.strat.compute_points_adjusted_apy()
        self.assertAlmostEqual(adjusted, base + POINTS_APY_PREMIUM_PCT, places=9)

    def test_zero_premium_collapses_to_base(self):
        # Points value may be 0 — advisory estimate must degrade gracefully.
        base = self.strat.compute_weighted_apy()
        self.assertAlmostEqual(
            self.strat.compute_points_adjusted_apy(points_premium_pct=0.0),
            base,
            places=9,
        )

    def test_custom_premium_override(self):
        base = self.strat.compute_weighted_apy()
        self.assertAlmostEqual(
            self.strat.compute_points_adjusted_apy(points_premium_pct=5.0),
            base + 5.0,
            places=9,
        )

    def test_peak_stays_within_target_max(self):
        adjusted = self.strat.compute_points_adjusted_apy()
        self.assertLessEqual(adjusted, TARGET_APY_MAX)


class TestActiveCampaigns(unittest.TestCase):
    def test_returns_copy(self):
        strat = S77PointsFarming()
        campaigns = strat.active_campaigns()
        self.assertEqual(campaigns, REWARD_CAMPAIGNS)
        campaigns["morpho_steakhouse"] = "mutated"
        self.assertNotEqual(
            REWARD_CAMPAIGNS["morpho_steakhouse"], "mutated"
        )


class TestAdvisoryContract(unittest.TestCase):
    def setUp(self):
        self.strat = S77PointsFarming()

    def test_is_advisory_true(self):
        self.assertTrue(S77PointsFarming.IS_ADVISORY)

    def test_no_execution_import(self):
        import spa_core.strategies.s77_points_farming as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("spa_core.execution", source)

    def test_get_info_keys(self):
        info = self.strat.get_info()
        for key in (
            "strategy_id", "strategy_name", "risk_tier", "expected_apy_pct",
            "is_advisory", "caveat", "allocation", "fallback_apy",
            "protocol_tiers", "reward_campaigns", "points_apy_premium_pct",
            "generated_at",
        ):
            self.assertIn(key, info)
        self.assertEqual(info["strategy_id"], "S77")
        self.assertEqual(info["risk_tier"], "T3")
        self.assertTrue(info["is_advisory"])


class TestRegistryIntegration(unittest.TestCase):
    def test_registered_in_tournament_registry(self):
        from spa_core.strategies.strategy_registry import REGISTRY
        meta = REGISTRY.get("S77")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.risk_tier, "T3")
        self.assertEqual(meta.handler_class, "S77PointsFarming")


if __name__ == "__main__":
    unittest.main(verbosity=2)
