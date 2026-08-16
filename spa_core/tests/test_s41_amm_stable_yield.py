"""
spa_core/tests/test_s41_amm_stable_yield.py

Tests for S41AmmStableYield and _drop_suspended_and_renorm
(spa_core/strategies/s41_amm_stable_yield.py).

AUD-18 — coverage for previously untested tournament strategies.

Run:
    python3 -m unittest spa_core.tests.test_s41_amm_stable_yield -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.s41_amm_stable_yield import (
    AERODROME_FULL_WEIGHT,
    AERODROME_KEY,
    AERODROME_LP_TVL_FLOOR_USD,
    AERODROME_THIN_POOL_WEIGHT,
    CASH_KEY,
    FALLBACK_APY,
    PROTOCOL_TIERS,
    S41AmmStableYield,
    STRATEGY_ID,
    TIER,
    WEIGHTS,
    _drop_suspended_and_renorm,
)


class TestModuleConstants(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(STRATEGY_ID, "S41")
        self.assertEqual(TIER, "T2")

    def test_static_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0, places=9)

    def test_t1_anchor_dominates(self):
        t1 = sum(w for p, w in WEIGHTS.items() if PROTOCOL_TIERS.get(p) == "T1")
        t2 = sum(w for p, w in WEIGHTS.items() if PROTOCOL_TIERS.get(p) == "T2")
        self.assertAlmostEqual(t1, 0.70, places=9)
        self.assertAlmostEqual(t2, 0.25, places=9)
        # ADR-019: T2 sleeve ≤ 50% and each T2 protocol ≤ 20%.
        self.assertLessEqual(t2, 0.50)
        for p, w in WEIGHTS.items():
            if PROTOCOL_TIERS.get(p) == "T2":
                self.assertLessEqual(w, 0.20)


class TestDropSuspendedAndRenorm(unittest.TestCase):
    def test_no_suspension_is_identity_renorm(self):
        out = _drop_suspended_and_renorm(dict(WEIGHTS), None)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)
        for key, weight in WEIGHTS.items():
            self.assertAlmostEqual(out[key], weight, places=6)

    def test_suspended_protocol_removed_and_renormed(self):
        out = _drop_suspended_and_renorm(dict(WEIGHTS), {AERODROME_KEY})
        self.assertNotIn(AERODROME_KEY, out)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)
        # Remaining weights scale by 1 / 0.85.
        self.assertAlmostEqual(out["aave_v3"], 0.40 / 0.85, places=6)

    def test_cash_never_suspendable(self):
        out = _drop_suspended_and_renorm(dict(WEIGHTS), {CASH_KEY})
        self.assertIn(CASH_KEY, out)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=6)

    def test_all_non_cash_suspended_leaves_pure_cash(self):
        suspended = {k for k in WEIGHTS if k != CASH_KEY}
        out = _drop_suspended_and_renorm(dict(WEIGHTS), suspended)
        self.assertEqual(set(out), {CASH_KEY})
        self.assertAlmostEqual(out[CASH_KEY], 1.0, places=6)

    def test_zero_total_returns_empty(self):
        out = _drop_suspended_and_renorm({"a": 0.0, "b": 0.0}, None)
        self.assertEqual(out, {})


class TestGetAllocation(unittest.TestCase):
    def setUp(self):
        self.strat = S41AmmStableYield()

    def test_default_matches_static_weights(self):
        alloc = self.strat.get_allocation()
        self.assertAlmostEqual(sum(alloc.values()), 1.0, places=6)
        self.assertAlmostEqual(alloc[AERODROME_KEY], AERODROME_FULL_WEIGHT, places=6)

    def test_thin_pool_flag_cuts_aerodrome_sleeve(self):
        # ADR-050: TVL below $20M floor → 15% → 5%, then renorm (total 0.90).
        alloc = self.strat.get_allocation(aerodrome_tvl_usd=2_000_000.0)
        self.assertAlmostEqual(sum(alloc.values()), 1.0, places=6)
        self.assertAlmostEqual(
            alloc[AERODROME_KEY], AERODROME_THIN_POOL_WEIGHT / 0.90, places=6
        )
        self.assertLess(alloc[AERODROME_KEY], AERODROME_FULL_WEIGHT)

    def test_tvl_at_floor_keeps_full_weight(self):
        alloc = self.strat.get_allocation(
            aerodrome_tvl_usd=AERODROME_LP_TVL_FLOOR_USD
        )
        self.assertAlmostEqual(alloc[AERODROME_KEY], AERODROME_FULL_WEIGHT, places=6)

    def test_no_tvl_supplied_is_backcompat_static(self):
        self.assertEqual(self.strat.get_allocation(), self.strat.get_allocation(None))

    def test_suspension_composes_with_thin_pool(self):
        alloc = self.strat.get_allocation(
            suspended={"velodrome_optimism"},
            aerodrome_tvl_usd=1_000_000.0,
        )
        self.assertNotIn("velodrome_optimism", alloc)
        self.assertAlmostEqual(sum(alloc.values()), 1.0, places=6)

    def test_deterministic(self):
        self.assertEqual(self.strat.get_allocation(), self.strat.get_allocation())


class TestGetExpectedApy(unittest.TestCase):
    def setUp(self):
        self.strat = S41AmmStableYield()

    def test_fallback_blend_matches_docstring(self):
        # 0.15*4.5 + 0.10*4.0 + 0.40*3.1 + 0.30*3.3 + 0.05*0 = 3.305
        self.assertAlmostEqual(self.strat.get_expected_apy(), 3.305, places=3)

    def test_live_apy_overrides_fallback(self):
        apy = self.strat.get_expected_apy({"aerodrome_base": 8.19})
        expected = (
            0.15 * 8.19 + 0.10 * FALLBACK_APY["velodrome_optimism"]
            + 0.40 * FALLBACK_APY["aave_v3"] + 0.30 * FALLBACK_APY["compound_v3"]
        )
        self.assertAlmostEqual(apy, expected, places=3)

    def test_all_suspended_returns_cash_only_zero_apy(self):
        suspended = {k for k in WEIGHTS if k != CASH_KEY}
        self.assertAlmostEqual(self.strat.get_expected_apy(None, suspended), 0.0)


class TestRiskSummary(unittest.TestCase):
    def test_tier_split_and_keys(self):
        summary = S41AmmStableYield().get_risk_summary()
        for key in ("strategy_id", "risk_score", "t1_weight_pct",
                    "t2_weight_pct", "cash_weight_pct", "max_drawdown_pct"):
            self.assertIn(key, summary)
        self.assertAlmostEqual(summary["t1_weight_pct"], 70.0, places=2)
        self.assertAlmostEqual(summary["t2_weight_pct"], 25.0, places=2)
        self.assertAlmostEqual(summary["cash_weight_pct"], 5.0, places=2)


class TestSimulate(unittest.TestCase):
    def setUp(self):
        self.strat = S41AmmStableYield()

    def test_positions_sum_to_capital(self):
        result = self.strat.simulate(100_000.0)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(
            sum(result["allocation"].values()), 100_000.0, places=2
        )

    def test_annual_yield_consistent_with_apy(self):
        result = self.strat.simulate(100_000.0)
        expected = round(100_000.0 * result["expected_apy_pct"] / 100.0, 4)
        self.assertAlmostEqual(
            result["expected_annual_yield_usd"], expected, places=4
        )

    def test_zero_capital_is_no_capital(self):
        result = self.strat.simulate(0.0)
        self.assertEqual(result["status"], "no_capital")
        self.assertEqual(result["allocation"], {})
        self.assertEqual(result["expected_annual_yield_usd"], 0.0)

    def test_negative_capital_is_no_capital(self):
        self.assertEqual(self.strat.simulate(-5.0)["status"], "no_capital")


class TestToDictAndContract(unittest.TestCase):
    def test_to_dict_keys(self):
        d = S41AmmStableYield().to_dict()
        for key in ("strategy_id", "strategy_name", "tier", "description",
                    "protocol_tiers", "weights", "fallback_apy",
                    "target_apy_min", "target_apy_max", "risk_score",
                    "max_drawdown_pct", "timestamp"):
            self.assertIn(key, d)
        self.assertEqual(d["strategy_id"], "S41")
        self.assertEqual(d["tier"], "T2")

    def test_no_execution_import(self):
        import spa_core.strategies.s41_amm_stable_yield as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("spa_core.execution", source)


class TestRegistryIntegration(unittest.TestCase):
    def test_registered_in_tournament_registry(self):
        from spa_core.strategies.strategy_registry import REGISTRY
        meta = REGISTRY.get("S41")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.risk_tier, "T2")
        self.assertEqual(meta.type, "lp")
        self.assertEqual(meta.handler_class, "S41AmmStableYield")


if __name__ == "__main__":
    unittest.main(verbosity=2)
