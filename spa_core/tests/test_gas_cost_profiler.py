"""
Tests for MP-749: GasCostProfiler
Uses unittest only (no pytest).
Run: python3 -m unittest spa_core.tests.test_gas_cost_profiler -v
"""

import math
import os
import tempfile
import unittest

from spa_core.analytics.gas_cost_profiler import (
    GasEstimate,
    PositionGasProfile,
    GasCostResult,
    CHAIN_DISCOUNT,
    RING_BUFFER_CAP,
    compute_gas_cost_usd,
    build_estimate,
    gas_efficiency_label,
    compute_breakeven,
    profile_position,
    profile_market,
    save_results,
    load_history,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _profile(
    protocol="TestProto",
    position_size_usd=100_000.0,
    annual_apy_pct=5.0,
    deposit_gas_units=150_000,
    withdraw_gas_units=120_000,
    rebalance_gas_units=200_000,
    rebalance_count=12,
    gas_price_gwei=30.0,
    eth_price_usd=3_500.0,
    chain="MAINNET",
):
    return profile_position(
        protocol=protocol,
        position_size_usd=position_size_usd,
        annual_apy_pct=annual_apy_pct,
        deposit_gas_units=deposit_gas_units,
        withdraw_gas_units=withdraw_gas_units,
        rebalance_gas_units=rebalance_gas_units,
        rebalance_count=rebalance_count,
        gas_price_gwei=gas_price_gwei,
        eth_price_usd=eth_price_usd,
        chain=chain,
    )


def _pos_dict(**kwargs):
    defaults = {
        "protocol": "TestProto",
        "position_size_usd": 100_000.0,
        "annual_apy_pct": 5.0,
        "deposit_gas_units": 150_000,
        "withdraw_gas_units": 120_000,
        "rebalance_gas_units": 200_000,
        "rebalance_count": 12,
        "gas_price_gwei": 30.0,
        "eth_price_usd": 3_500.0,
        "chain": "MAINNET",
    }
    defaults.update(kwargs)
    return defaults


def _gas_usd(gas_units, gas_price_gwei, eth_price_usd, chain):
    discount = CHAIN_DISCOUNT.get(chain, 1.0)
    eff_gwei = gas_price_gwei * discount
    eth = gas_units * eff_gwei / 1e9
    return eth * eth_price_usd


# ===========================================================================
# 1. compute_gas_cost_usd
# ===========================================================================

class TestComputeGasCostUsd(unittest.TestCase):

    def test_mainnet_no_discount(self):
        # MAINNET discount = 1.0
        # 150000 * 30 / 1e9 * 3500 = 0.0045 * 3500 = 15.75
        cost = compute_gas_cost_usd(150_000, 30.0, 3_500.0, "MAINNET")
        self.assertAlmostEqual(cost, 15.75, places=4)

    def test_arbitrum_discount(self):
        # ARBITRUM discount = 0.05
        # 150000 * 30 * 0.05 / 1e9 * 3500 = 150000 * 1.5 / 1e9 * 3500 = 0.225e-3 * 3500 = 0.7875
        cost = compute_gas_cost_usd(150_000, 30.0, 3_500.0, "ARBITRUM")
        expected = 150_000 * 30.0 * 0.05 / 1e9 * 3_500.0
        self.assertAlmostEqual(cost, expected, places=6)

    def test_base_discount(self):
        cost = compute_gas_cost_usd(150_000, 30.0, 3_500.0, "BASE")
        expected = 150_000 * 30.0 * 0.03 / 1e9 * 3_500.0
        self.assertAlmostEqual(cost, expected, places=6)

    def test_optimism_discount(self):
        cost = compute_gas_cost_usd(150_000, 30.0, 3_500.0, "OPTIMISM")
        expected = 150_000 * 30.0 * 0.04 / 1e9 * 3_500.0
        self.assertAlmostEqual(cost, expected, places=6)

    def test_unknown_chain_defaults_to_1(self):
        cost_unknown = compute_gas_cost_usd(100_000, 20.0, 2_000.0, "SOLANA")
        cost_mainnet = compute_gas_cost_usd(100_000, 20.0, 2_000.0, "MAINNET")
        self.assertAlmostEqual(cost_unknown, cost_mainnet, places=6)

    def test_zero_gas_units(self):
        cost = compute_gas_cost_usd(0, 30.0, 3_500.0, "MAINNET")
        self.assertAlmostEqual(cost, 0.0)

    def test_high_eth_price(self):
        cost = compute_gas_cost_usd(100_000, 50.0, 10_000.0, "MAINNET")
        expected = 100_000 * 50.0 / 1e9 * 10_000.0
        self.assertAlmostEqual(cost, expected, places=4)


# ===========================================================================
# 2. build_estimate
# ===========================================================================

class TestBuildEstimate(unittest.TestCase):

    def setUp(self):
        self.est = build_estimate("DEPOSIT", 150_000, 30.0, 3_500.0, "MAINNET")

    def test_operation_field(self):
        self.assertEqual(self.est.operation, "DEPOSIT")

    def test_gas_units_field(self):
        self.assertEqual(self.est.gas_units, 150_000)

    def test_gas_price_gwei_field(self):
        self.assertAlmostEqual(self.est.gas_price_gwei, 30.0)

    def test_eth_price_usd_field(self):
        self.assertAlmostEqual(self.est.eth_price_usd, 3_500.0)

    def test_chain_field(self):
        self.assertEqual(self.est.chain, "MAINNET")

    def test_chain_discount_factor_mainnet(self):
        self.assertAlmostEqual(self.est.chain_discount_factor, 1.0)

    def test_chain_discount_factor_arbitrum(self):
        est = build_estimate("DEPOSIT", 150_000, 30.0, 3_500.0, "ARBITRUM")
        self.assertAlmostEqual(est.chain_discount_factor, 0.05)

    def test_effective_gas_price_mainnet(self):
        # MAINNET: effective = 30.0 * 1.0 = 30.0
        self.assertAlmostEqual(self.est.effective_gas_price_gwei, 30.0)

    def test_effective_gas_price_arbitrum(self):
        est = build_estimate("DEPOSIT", 150_000, 30.0, 3_500.0, "ARBITRUM")
        self.assertAlmostEqual(est.effective_gas_price_gwei, 30.0 * 0.05)

    def test_gas_cost_eth_formula(self):
        # 150000 * 30 / 1e9 = 0.0045
        self.assertAlmostEqual(self.est.gas_cost_eth, 0.0045, places=6)

    def test_gas_cost_usd_formula(self):
        # 0.0045 * 3500 = 15.75
        self.assertAlmostEqual(self.est.gas_cost_usd, 15.75, places=4)

    def test_returns_gas_estimate_type(self):
        self.assertIsInstance(self.est, GasEstimate)

    def test_withdraw_operation(self):
        est = build_estimate("WITHDRAW", 120_000, 25.0, 3_000.0, "BASE")
        self.assertEqual(est.operation, "WITHDRAW")
        self.assertEqual(est.chain, "BASE")
        self.assertAlmostEqual(est.chain_discount_factor, 0.03)


# ===========================================================================
# 3. gas_efficiency_label
# ===========================================================================

class TestGasEfficiencyLabel(unittest.TestCase):

    def test_efficient(self):
        self.assertEqual(gas_efficiency_label(0.0), "EFFICIENT")
        self.assertEqual(gas_efficiency_label(0.99), "EFFICIENT")

    def test_marginal_boundary(self):
        self.assertEqual(gas_efficiency_label(1.0), "MARGINAL")
        self.assertEqual(gas_efficiency_label(3.0), "MARGINAL")

    def test_expensive(self):
        self.assertEqual(gas_efficiency_label(3.01), "EXPENSIVE")
        self.assertEqual(gas_efficiency_label(10.0), "EXPENSIVE")


# ===========================================================================
# 4. compute_breakeven
# ===========================================================================

class TestComputeBreakeven(unittest.TestCase):

    def test_formula(self):
        # total_gas=100, apy=5% → 100 / 0.05 = 2000
        be = compute_breakeven(100.0, 5.0)
        self.assertAlmostEqual(be, 2000.0)

    def test_apy_zero_returns_inf(self):
        be = compute_breakeven(100.0, 0.0)
        self.assertTrue(math.isinf(be))

    def test_apy_negative_returns_inf(self):
        be = compute_breakeven(100.0, -1.0)
        self.assertTrue(math.isinf(be))

    def test_small_gas(self):
        be = compute_breakeven(1.0, 10.0)
        self.assertAlmostEqual(be, 10.0)

    def test_large_gas(self):
        be = compute_breakeven(1000.0, 2.0)
        self.assertAlmostEqual(be, 50_000.0)


# ===========================================================================
# 5. profile_position — computed fields
# ===========================================================================

class TestProfilePosition(unittest.TestCase):

    def test_total_gas_usd_formula(self):
        p = _profile(
            deposit_gas_units=150_000,
            withdraw_gas_units=120_000,
            rebalance_gas_units=200_000,
            rebalance_count=10,
            gas_price_gwei=30.0,
            eth_price_usd=3_500.0,
            chain="MAINNET",
        )
        dep = _gas_usd(150_000, 30.0, 3_500.0, "MAINNET")
        wit = _gas_usd(120_000, 30.0, 3_500.0, "MAINNET")
        reb = _gas_usd(200_000, 30.0, 3_500.0, "MAINNET")
        expected = dep + wit + reb * 10
        self.assertAlmostEqual(p.total_gas_usd, expected, places=4)

    def test_annual_gas_drag_pct_formula(self):
        p = _profile(position_size_usd=100_000.0)
        expected_drag = p.total_gas_usd / 100_000.0 * 100.0
        self.assertAlmostEqual(p.annual_gas_drag_pct, expected_drag, places=6)

    def test_net_apy_after_gas(self):
        p = _profile(annual_apy_pct=5.0)
        expected_net = 5.0 - p.annual_gas_drag_pct
        self.assertAlmostEqual(p.net_apy_after_gas_pct, expected_net, places=6)

    def test_breakeven_position_usd_formula(self):
        p = _profile(annual_apy_pct=5.0)
        expected = compute_breakeven(p.total_gas_usd, 5.0)
        self.assertAlmostEqual(p.breakeven_position_usd, expected, places=4)

    def test_is_gas_efficient_true(self):
        # Large position → tiny gas drag
        p = _profile(position_size_usd=10_000_000.0, annual_apy_pct=5.0)
        self.assertTrue(p.is_gas_efficient)

    def test_is_gas_efficient_false_high_drag(self):
        # Tiny position → huge gas drag
        p = _profile(position_size_usd=100.0, annual_apy_pct=5.0)
        self.assertFalse(p.is_gas_efficient)

    def test_is_gas_efficient_false_negative_net_apy(self):
        # gas drag > apy → net_apy negative → not efficient
        p = _profile(
            position_size_usd=1_000.0,
            annual_apy_pct=0.1,
            chain="MAINNET",
        )
        if p.net_apy_after_gas_pct <= 0:
            self.assertFalse(p.is_gas_efficient)

    def test_zero_rebalances_only_deposit_withdraw(self):
        p = _profile(rebalance_count=0)
        dep = _gas_usd(150_000, 30.0, 3_500.0, "MAINNET")
        wit = _gas_usd(120_000, 30.0, 3_500.0, "MAINNET")
        self.assertAlmostEqual(p.total_gas_usd, dep + wit, places=4)

    def test_protocol_field(self):
        p = _profile(protocol="Aave V3")
        self.assertEqual(p.protocol, "Aave V3")

    def test_gas_efficiency_label_on_profile(self):
        p = _profile()
        self.assertIn(p.gas_efficiency_label, ["EFFICIENT", "MARGINAL", "EXPENSIVE"])

    def test_recommendation_present(self):
        p = _profile()
        self.assertIsInstance(p.recommendation, str)
        self.assertGreater(len(p.recommendation), 0)

    def test_large_position_drag_near_zero(self):
        p = _profile(position_size_usd=1_000_000_000.0, annual_apy_pct=5.0)
        self.assertLess(p.annual_gas_drag_pct, 0.001)

    def test_chain_discount_applied_in_profile(self):
        p_main = _profile(chain="MAINNET")
        p_arb = _profile(chain="ARBITRUM")
        # Arbitrum should be significantly cheaper
        self.assertLess(p_arb.total_gas_usd, p_main.total_gas_usd)

    def test_deposit_gas_estimate_type(self):
        p = _profile()
        self.assertIsInstance(p.deposit_gas, GasEstimate)

    def test_withdraw_gas_estimate_type(self):
        p = _profile()
        self.assertIsInstance(p.withdraw_gas, GasEstimate)

    def test_rebalance_gas_estimate_type(self):
        p = _profile()
        self.assertIsInstance(p.rebalance_gas, GasEstimate)


# ===========================================================================
# 6. Recommendations
# ===========================================================================

class TestRecommendations(unittest.TestCase):

    def test_expensive_recommendation(self):
        p = _profile(position_size_usd=500.0, annual_apy_pct=5.0)
        if p.gas_efficiency_label == "EXPENSIVE":
            self.assertIn("exceed 3%", p.recommendation)
            self.assertIn("Increase position size", p.recommendation)

    def test_marginal_recommendation(self):
        # Need drag in 1-3% range
        # Try position_size = 10000, mainnet
        p = _profile(position_size_usd=5_000.0, annual_apy_pct=5.0, rebalance_count=1)
        if p.gas_efficiency_label == "MARGINAL":
            self.assertIn("Marginal", p.recommendation)
            self.assertIn("L2", p.recommendation)

    def test_efficient_recommendation(self):
        p = _profile(position_size_usd=10_000_000.0, annual_apy_pct=5.0)
        if p.gas_efficiency_label == "EFFICIENT":
            self.assertIn("Gas efficient", p.recommendation)


# ===========================================================================
# 7. profile_market — result fields
# ===========================================================================

class TestProfileMarket(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmp_dir, "gas_cost_log.json")

    def _two_positions(self):
        return [
            _pos_dict(protocol="Cheap", chain="BASE", position_size_usd=1_000_000.0),
            _pos_dict(protocol="Expensive", chain="MAINNET", position_size_usd=1_000.0),
        ]

    def test_most_gas_efficient_min_drag(self):
        result = profile_market(self._two_positions())
        # BASE is much cheaper + bigger position → lower drag
        profiles = result.profiles
        min_proto = min(profiles, key=lambda p: p.annual_gas_drag_pct).protocol
        self.assertEqual(result.most_gas_efficient_protocol, min_proto)

    def test_least_gas_efficient_max_drag(self):
        result = profile_market(self._two_positions())
        profiles = result.profiles
        max_proto = max(profiles, key=lambda p: p.annual_gas_drag_pct).protocol
        self.assertEqual(result.least_gas_efficient_protocol, max_proto)

    def test_avg_gas_drag_formula(self):
        data = [
            _pos_dict(protocol="A", position_size_usd=100_000.0),
            _pos_dict(protocol="B", position_size_usd=100_000.0),
        ]
        result = profile_market(data)
        expected_avg = sum(p.annual_gas_drag_pct for p in result.profiles) / 2
        self.assertAlmostEqual(result.avg_gas_drag_pct, expected_avg, places=6)

    def test_avg_breakeven_usd(self):
        data = [
            _pos_dict(protocol="A"),
            _pos_dict(protocol="B"),
        ]
        result = profile_market(data)
        finite = [p.breakeven_position_usd for p in result.profiles
                  if p.breakeven_position_usd != float("inf")]
        if finite:
            expected = sum(finite) / len(finite)
            self.assertAlmostEqual(result.avg_breakeven_usd, expected, places=2)

    def test_efficient_count(self):
        data = [
            _pos_dict(protocol="Big", position_size_usd=10_000_000.0),
            _pos_dict(protocol="Small", position_size_usd=100.0),
        ]
        result = profile_market(data)
        self.assertEqual(
            result.efficient_count,
            sum(1 for p in result.profiles if p.is_gas_efficient)
        )

    def test_market_gas_label_gas_friendly(self):
        # Very large positions → tiny drag → GAS_FRIENDLY
        data = [_pos_dict(protocol="BigPos", position_size_usd=100_000_000.0, chain="BASE")]
        result = profile_market(data)
        self.assertEqual(result.market_gas_label, "GAS_FRIENDLY")

    def test_market_gas_label_gas_heavy(self):
        # Tiny positions, mainnet → large drag
        data = [_pos_dict(protocol="TinyPos", position_size_usd=100.0, chain="MAINNET")]
        result = profile_market(data)
        self.assertEqual(result.market_gas_label, "GAS_HEAVY")

    def test_market_gas_label_moderate(self):
        # Moderate position
        data = [_pos_dict(protocol="ModPos", position_size_usd=5_000.0,
                          chain="MAINNET", rebalance_count=2)]
        result = profile_market(data)
        self.assertIn(result.market_gas_label, ["MODERATE_GAS", "GAS_HEAVY", "GAS_FRIENDLY"])

    def test_empty_positions(self):
        result = profile_market([])
        self.assertEqual(result.profiles, [])
        self.assertEqual(result.efficient_count, 0)

    def test_result_type(self):
        result = profile_market([_pos_dict()])
        self.assertIsInstance(result, GasCostResult)

    def test_profiles_count(self):
        data = [_pos_dict(protocol=f"P{i}") for i in range(4)]
        result = profile_market(data)
        self.assertEqual(len(result.profiles), 4)

    def test_recommendation_summary_present(self):
        result = profile_market([_pos_dict()])
        self.assertIsInstance(result.recommendation_summary, str)
        self.assertGreater(len(result.recommendation_summary), 0)


# ===========================================================================
# 8. save / load / ring-buffer
# ===========================================================================

class TestSaveLoadRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmp_dir, "gas_cost_log.json")

    def _result(self, protocol="P"):
        data = [_pos_dict(protocol=protocol)]
        return profile_market(data, data_file=self.data_file)

    def test_save_and_load_round_trip(self):
        result = self._result()
        save_results(result, self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), 1)
        self.assertIn("profiles", history[0])

    def test_load_empty_when_no_file(self):
        history = load_history(os.path.join(self.tmp_dir, "nonexistent.json"))
        self.assertEqual(history, [])

    def test_ring_buffer_cap(self):
        for i in range(RING_BUFFER_CAP + 5):
            result = self._result(protocol=f"P{i}")
            save_results(result, self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), RING_BUFFER_CAP)

    def test_saved_to_field_updated(self):
        result = self._result()
        save_results(result, self.data_file)
        self.assertEqual(result.saved_to, self.data_file)

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            result = self._result()
            save_results(result, self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), 5)

    def test_invalid_json_returns_empty(self):
        with open(self.data_file, "w") as f:
            f.write("NOT JSON")
        history = load_history(self.data_file)
        self.assertEqual(history, [])

    def test_atomic_write_creates_file(self):
        result = self._result()
        save_results(result, self.data_file)
        self.assertTrue(os.path.exists(self.data_file))


# ===========================================================================
# 9. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_zero_rebalances_no_rebalance_cost(self):
        p = _profile(rebalance_count=0)
        # total = deposit + withdraw only
        dep = p.deposit_gas.gas_cost_usd
        wit = p.withdraw_gas.gas_cost_usd
        self.assertAlmostEqual(p.total_gas_usd, dep + wit, places=6)

    def test_very_large_position_drag_near_zero(self):
        p = _profile(position_size_usd=1_000_000_000.0, annual_apy_pct=5.0, chain="BASE")
        self.assertLess(p.annual_gas_drag_pct, 0.001)
        self.assertTrue(p.is_gas_efficient)

    def test_arbitrum_cheaper_than_mainnet(self):
        p_main = _profile(chain="MAINNET", position_size_usd=100_000.0)
        p_arb = _profile(chain="ARBITRUM", position_size_usd=100_000.0)
        self.assertLess(p_arb.total_gas_usd, p_main.total_gas_usd)

    def test_base_cheaper_than_arbitrum(self):
        p_arb = _profile(chain="ARBITRUM")
        p_base = _profile(chain="BASE")
        self.assertLess(p_base.total_gas_usd, p_arb.total_gas_usd)

    def test_optimism_cheaper_than_mainnet(self):
        p_main = _profile(chain="MAINNET")
        p_opt = _profile(chain="OPTIMISM")
        self.assertLess(p_opt.total_gas_usd, p_main.total_gas_usd)

    def test_breakeven_large_apy(self):
        # High APY → lower breakeven
        p_low = _profile(annual_apy_pct=1.0)
        p_high = _profile(annual_apy_pct=20.0)
        self.assertGreater(p_low.breakeven_position_usd, p_high.breakeven_position_usd)

    def test_chain_discount_constants(self):
        self.assertAlmostEqual(CHAIN_DISCOUNT["MAINNET"], 1.0)
        self.assertAlmostEqual(CHAIN_DISCOUNT["ARBITRUM"], 0.05)
        self.assertAlmostEqual(CHAIN_DISCOUNT["BASE"], 0.03)
        self.assertAlmostEqual(CHAIN_DISCOUNT["OPTIMISM"], 0.04)

    def test_profile_returns_position_gas_profile_type(self):
        p = _profile()
        self.assertIsInstance(p, PositionGasProfile)

    def test_rebalance_count_field(self):
        p = _profile(rebalance_count=7)
        self.assertEqual(p.rebalance_count, 7)

    def test_position_size_field(self):
        p = _profile(position_size_usd=75_000.0)
        self.assertAlmostEqual(p.position_size_usd, 75_000.0)

    def test_annual_apy_field(self):
        p = _profile(annual_apy_pct=8.5)
        self.assertAlmostEqual(p.annual_apy_pct, 8.5)


if __name__ == "__main__":
    unittest.main()
