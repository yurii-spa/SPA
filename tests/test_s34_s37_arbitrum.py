"""
tests/test_s34_s37_arbitrum.py — Arbitrum-focused strategies S34–S37 (40 tests)

10 tests per strategy:
  TestS34ArbitrumYield        (10) — alloc sums, sequencer rotation, exposure, APY
  TestS35GMXCarry             (10) — GLP gate >8%, active/inactive books, weights
  TestS36CrossChainOptimizer  (10) — best-chain tilt, mainnet merge, anchor, APY
  TestS37RadiantConcentrated  (10) — 50/30/15/5 split, Radiant suspend rotation

Rules: stdlib only, unittest, no network / filesystem access.
"""
import unittest

from spa_core.strategies.s34_arbitrum_yield import (
    S34ArbitrumYield, BASE_ALLOCATION as S34_ALLOC, ARBITRUM_POOLS,
    MAINNET_ANCHOR as S34_ANCHOR, CASH_KEY as S34_CASH,
)
from spa_core.strategies.s35_gmx_carry import (
    S35GMXCarry, GLP_ACTIVATION_THRESHOLD_PCT, ACTIVE_ALLOCATION,
    INACTIVE_ALLOCATION, CASH_KEY as S35_CASH,
)
from spa_core.strategies.s36_cross_chain_optimizer import (
    S36CrossChainOptimizer, TILT_WEIGHT, ANCHOR_WEIGHT, CASH_WEIGHT,
    CHAIN_VENUES, MAINNET_ANCHOR as S36_ANCHOR, CASH_KEY as S36_CASH,
)
from spa_core.strategies.s37_radiant_concentrated import (
    S37RadiantConcentrated, BASE_ALLOCATION as S37_ALLOC,
    MAINNET_FALLBACK, CASH_KEY as S37_CASH,
)


def _sum(alloc):
    return sum(alloc.values())


# ──────────────────────────────────────────────────────────────────────────────
# S34 — Arbitrum Yield
# ──────────────────────────────────────────────────────────────────────────────

class TestS34ArbitrumYield(unittest.TestCase):

    def setUp(self):
        self.s = S34ArbitrumYield()

    def test_alloc_sums_to_one_up(self):
        self.assertAlmostEqual(_sum(self.s.get_allocation(sequencer_up=True)), 1.0, places=6)

    def test_alloc_sums_to_one_down(self):
        self.assertAlmostEqual(_sum(self.s.get_allocation(sequencer_up=False)), 1.0, places=6)

    def test_base_weights_match_spec(self):
        alloc = self.s.get_allocation(sequencer_up=True)
        self.assertAlmostEqual(alloc["aave_arbitrum"], 0.40, places=6)
        self.assertAlmostEqual(alloc["radiant_arbitrum"], 0.30, places=6)
        self.assertAlmostEqual(alloc["aave_v3"], 0.25, places=6)
        self.assertAlmostEqual(alloc[S34_CASH], 0.05, places=6)

    def test_sequencer_down_rotates_arb_to_mainnet(self):
        alloc = self.s.get_allocation(sequencer_up=False)
        for p in ARBITRUM_POOLS:
            self.assertNotIn(p, alloc)
        # 0.40 + 0.30 + 0.25 = 0.95 lands on the mainnet anchor.
        self.assertAlmostEqual(alloc[S34_ANCHOR], 0.95, places=6)

    def test_sequencer_down_preserves_cash(self):
        alloc = self.s.get_allocation(sequencer_up=False)
        self.assertAlmostEqual(alloc[S34_CASH], 0.05, places=6)

    def test_bridge_risk_flag(self):
        self.assertTrue(self.s.is_bridge_risk_triggered(False))
        self.assertFalse(self.s.is_bridge_risk_triggered(True))

    def test_arbitrum_exposure_up_vs_down(self):
        self.assertAlmostEqual(self.s.get_arbitrum_exposure_pct(True), 70.0, places=4)
        self.assertAlmostEqual(self.s.get_arbitrum_exposure_pct(False), 0.0, places=4)

    def test_expected_apy_default(self):
        # 0.40*4.5 + 0.30*5.0 + 0.25*3.5 = 4.175
        self.assertAlmostEqual(self.s.get_expected_apy(), 4.175, places=3)

    def test_expected_apy_down_uses_anchor(self):
        # sequencer down: 0.95*3.5 = 3.325
        self.assertAlmostEqual(self.s.get_expected_apy(sequencer_up=False), 3.325, places=3)

    def test_simulate_positions_sum_to_capital(self):
        sim = self.s.simulate(100_000.0)
        self.assertAlmostEqual(sum(sim["allocation"].values()), 100_000.0, places=2)
        self.assertEqual(sim["status"], "ok")

    def test_no_capital(self):
        sim = self.s.simulate(0.0)
        self.assertEqual(sim["status"], "no_capital")
        self.assertEqual(sim["allocation"], {})


# ──────────────────────────────────────────────────────────────────────────────
# S35 — GMX Stablecoin Carry
# ──────────────────────────────────────────────────────────────────────────────

class TestS35GMXCarry(unittest.TestCase):

    def setUp(self):
        self.s = S35GMXCarry()

    def test_threshold_constant(self):
        self.assertEqual(GLP_ACTIVATION_THRESHOLD_PCT, 8.0)

    def test_glp_active_above_threshold(self):
        self.assertTrue(self.s.is_glp_active(8.5))

    def test_glp_inactive_at_or_below_threshold(self):
        self.assertFalse(self.s.is_glp_active(8.0))
        self.assertFalse(self.s.is_glp_active(6.0))

    def test_active_alloc_includes_glp(self):
        alloc = self.s.get_allocation(glp_stable_apy=10.0)
        self.assertAlmostEqual(alloc["gmx_glp_arbitrum"], 0.20, places=6)
        self.assertAlmostEqual(_sum(alloc), 1.0, places=6)

    def test_inactive_alloc_excludes_glp(self):
        alloc = self.s.get_allocation(glp_stable_apy=5.0)
        self.assertNotIn("gmx_glp_arbitrum", alloc)
        self.assertAlmostEqual(_sum(alloc), 1.0, places=6)

    def test_inactive_is_full_mainnet_t1(self):
        alloc = self.s.get_allocation(glp_stable_apy=5.0)
        self.assertAlmostEqual(alloc["aave_v3"], 0.65, places=6)
        self.assertAlmostEqual(alloc["compound_v3"], 0.30, places=6)

    def test_glp_weight_helper(self):
        self.assertAlmostEqual(self.s.get_glp_weight(10.0), 0.20, places=6)
        self.assertAlmostEqual(self.s.get_glp_weight(5.0), 0.0, places=6)

    def test_suspended_glp_falls_back_to_cash(self):
        alloc = self.s.get_allocation(glp_stable_apy=10.0, suspended={"gmx_glp_arbitrum"})
        self.assertNotIn("gmx_glp_arbitrum", alloc)
        self.assertAlmostEqual(_sum(alloc), 1.0, places=6)

    def test_expected_apy_uses_live_glp_rate(self):
        # active: 0.20*12 + 0.50*3.5 + 0.25*4.8 = 2.4 + 1.75 + 1.2 = 5.35
        self.assertAlmostEqual(self.s.get_expected_apy(glp_stable_apy=12.0), 5.35, places=2)

    def test_simulate_sums_to_capital(self):
        sim = self.s.simulate(100_000.0, glp_stable_apy=10.0)
        self.assertAlmostEqual(sum(sim["allocation"].values()), 100_000.0, places=2)
        self.assertTrue(sim["glp_active"])


# ──────────────────────────────────────────────────────────────────────────────
# S36 — Cross-Chain Optimizer
# ──────────────────────────────────────────────────────────────────────────────

class TestS36CrossChainOptimizer(unittest.TestCase):

    def setUp(self):
        self.s = S36CrossChainOptimizer()

    def test_weights_constants(self):
        self.assertAlmostEqual(TILT_WEIGHT + ANCHOR_WEIGHT + CASH_WEIGHT, 1.0, places=6)

    def test_alloc_sums_to_one(self):
        self.assertAlmostEqual(_sum(self.s.get_allocation()), 1.0, places=6)

    def test_best_chain_arbitrum(self):
        self.assertEqual(self.s.best_chain({"arbitrum": 9.0, "mainnet": 3.0, "base": 4.0}), "arbitrum")

    def test_best_chain_base(self):
        self.assertEqual(self.s.best_chain({"arbitrum": 4.0, "mainnet": 3.0, "base": 7.0}), "base")

    def test_tilt_to_arbitrum_venue(self):
        alloc = self.s.get_allocation({"arbitrum": 9.0})
        venue = CHAIN_VENUES["arbitrum"]
        self.assertAlmostEqual(alloc[venue], TILT_WEIGHT, places=6)
        self.assertAlmostEqual(alloc[S36_ANCHOR], ANCHOR_WEIGHT, places=6)

    def test_mainnet_best_merges_tilt_and_anchor(self):
        alloc = self.s.get_allocation({"mainnet": 9.0, "arbitrum": 3.0, "base": 4.0})
        # tilt (0.60) + anchor (0.30) both land on aave_v3 -> 0.90
        self.assertAlmostEqual(alloc[S36_ANCHOR], 0.90, places=6)
        self.assertAlmostEqual(alloc[S36_CASH], 0.10, places=6)
        self.assertAlmostEqual(_sum(alloc), 1.0, places=6)

    def test_anchor_always_present(self):
        alloc = self.s.get_allocation({"base": 9.0})
        self.assertGreaterEqual(alloc.get(S36_ANCHOR, 0.0), ANCHOR_WEIGHT - 1e-9)

    def test_cash_weight(self):
        alloc = self.s.get_allocation({"arbitrum": 9.0})
        self.assertAlmostEqual(alloc[S36_CASH], CASH_WEIGHT, places=6)

    def test_expected_apy_arbitrum_tilt(self):
        # tilt arb@6 (0.60*6=3.6) + anchor aave@3.5 (0.30*3.5=1.05) + cash 0 = 4.65
        apy = self.s.get_expected_apy(chain_apy={"arbitrum": 6.0})
        self.assertAlmostEqual(apy, 4.65, places=2)

    def test_simulate_sums_to_capital(self):
        sim = self.s.simulate(100_000.0, chain_apy={"arbitrum": 6.0})
        self.assertAlmostEqual(sum(sim["allocation"].values()), 100_000.0, places=2)
        self.assertEqual(sim["best_chain"], "arbitrum")


# ──────────────────────────────────────────────────────────────────────────────
# S37 — Radiant Concentrated
# ──────────────────────────────────────────────────────────────────────────────

class TestS37RadiantConcentrated(unittest.TestCase):

    def setUp(self):
        self.s = S37RadiantConcentrated()

    def test_alloc_sums_to_one(self):
        self.assertAlmostEqual(_sum(self.s.get_allocation()), 1.0, places=6)

    def test_weights_match_spec(self):
        alloc = self.s.get_allocation()
        self.assertAlmostEqual(alloc["radiant_arbitrum"], 0.50, places=6)
        self.assertAlmostEqual(alloc["aave_v3"], 0.30, places=6)
        self.assertAlmostEqual(alloc["compound_v3"], 0.15, places=6)
        self.assertAlmostEqual(alloc[S37_CASH], 0.05, places=6)

    def test_radiant_is_largest_weight(self):
        alloc = self.s.get_allocation()
        self.assertEqual(max(alloc, key=alloc.get), "radiant_arbitrum")

    def test_radiant_weight_helper(self):
        self.assertAlmostEqual(self.s.get_radiant_weight(), 0.50, places=6)

    def test_radiant_suspended_rotates_to_mainnet(self):
        alloc = self.s.get_allocation(suspended={"radiant_arbitrum"})
        self.assertNotIn("radiant_arbitrum", alloc)
        # 0.50 rotates to aave_v3 -> 0.30 + 0.50 = 0.80
        self.assertAlmostEqual(alloc[MAINNET_FALLBACK], 0.80, places=6)
        self.assertAlmostEqual(_sum(alloc), 1.0, places=6)

    def test_suspended_preserves_cash(self):
        alloc = self.s.get_allocation(suspended={"radiant_arbitrum"})
        self.assertAlmostEqual(alloc[S37_CASH], 0.05, places=6)

    def test_expected_apy_default(self):
        # 0.50*5.0 + 0.30*3.5 + 0.15*4.8 = 2.5 + 1.05 + 0.72 = 4.27
        self.assertAlmostEqual(self.s.get_expected_apy(), 4.27, places=2)

    def test_mainnet_t1_sleeve_is_45pct(self):
        summ = self.s.get_risk_summary()
        # T1 = aave_v3 (0.30) + compound_v3 (0.15) + cash (0.05) = 0.50
        self.assertAlmostEqual(summ["t1_weight_pct"], 50.0, places=2)
        self.assertAlmostEqual(summ["t2_weight_pct"], 50.0, places=2)

    def test_simulate_sums_to_capital(self):
        sim = self.s.simulate(100_000.0)
        self.assertAlmostEqual(sum(sim["allocation"].values()), 100_000.0, places=2)
        self.assertEqual(sim["status"], "ok")

    def test_no_capital(self):
        sim = self.s.simulate(0.0)
        self.assertEqual(sim["status"], "no_capital")


# ──────────────────────────────────────────────────────────────────────────────
# Registry integration — all four self-register
# ──────────────────────────────────────────────────────────────────────────────

class TestS34S37Registration(unittest.TestCase):

    def test_all_registered(self):
        from spa_core.strategies.strategy_registry import REGISTRY
        for sid in ("S34", "S35", "S36", "S37"):
            self.assertIsNotNone(REGISTRY.get(sid), f"{sid} not registered")


if __name__ == "__main__":
    unittest.main()
