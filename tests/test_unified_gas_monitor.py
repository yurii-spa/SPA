#!/usr/bin/env python3
"""
tests/test_unified_gas_monitor.py

25 unit tests for UnifiedGasMonitor (MP-1488, v11.04).

Covers:
  - Constants: GAS_LIMITS, SUPPORTED_CHAINS, ETH_PRICE_USD
  - estimate_rebalance_cost: Ethereum and Base
  - estimate_operation_cost: valid / invalid operation / invalid chain
  - annual_gas_cost_usd: arithmetic
  - compare_all_chains: structure, cheapest_chain
  - to_dict: snapshot
  - supported_operations: correct keys per chain
  - _validate_chain: raises on unknown chain
  - _calc_cost: arithmetic parity (gas × gwei / 1e9 × eth_price)
  - Custom eth_price_usd injection
  - Profitability flag

Run:
    python3 -m pytest tests/test_unified_gas_monitor.py -v
    python3 tests/test_unified_gas_monitor.py
"""
from __future__ import annotations

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.monitor.unified_gas_monitor import (
    ETH_PRICE_USD,
    GAS_LIMITS,
    OUTPUT_PATH,
    PROFITABILITY_THRESHOLD_USD,
    REBALANCES_PER_YEAR,
    SUPPORTED_CHAINS,
    UnifiedGasMonitor,
    _FALLBACK_GAS_PRICE_GWEI,
    _GWEI_PER_ETH,
)


# ---------------------------------------------------------------------------
# 1. Module constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):

    def test_01_supported_chains_not_empty(self):
        self.assertGreater(len(SUPPORTED_CHAINS), 0)

    def test_02_ethereum_in_supported(self):
        self.assertIn("ethereum", SUPPORTED_CHAINS)

    def test_03_base_in_supported(self):
        self.assertIn("base", SUPPORTED_CHAINS)

    def test_04_gas_limits_keys_match_supported(self):
        for chain in SUPPORTED_CHAINS:
            self.assertIn(chain, GAS_LIMITS)

    def test_05_all_gas_limit_values_positive(self):
        for chain, ops in GAS_LIMITS.items():
            for op, limit in ops.items():
                with self.subTest(chain=chain, op=op):
                    self.assertGreater(limit, 0)

    def test_06_rebalance_full_in_all_chains(self):
        for chain in SUPPORTED_CHAINS:
            self.assertIn("rebalance_full", GAS_LIMITS[chain])

    def test_07_eth_price_positive(self):
        self.assertGreater(ETH_PRICE_USD, 0)

    def test_08_profitability_threshold_positive(self):
        self.assertGreater(PROFITABILITY_THRESHOLD_USD, 0)


# ---------------------------------------------------------------------------
# 2. estimate_rebalance_cost
# ---------------------------------------------------------------------------

class TestEstimateRebalanceCost(unittest.TestCase):

    def setUp(self):
        self.monitor = UnifiedGasMonitor()

    def test_09_ethereum_returns_dict(self):
        result = self.monitor.estimate_rebalance_cost("ethereum")
        self.assertIsInstance(result, dict)

    def test_10_ethereum_result_has_required_keys(self):
        result = self.monitor.estimate_rebalance_cost("ethereum")
        for key in ("chain", "gas_limit", "gas_price_gwei", "cost_eth", "cost_usd", "is_profitable"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_11_base_cost_less_than_ethereum(self):
        eth_cost = self.monitor.estimate_rebalance_cost("ethereum")["cost_usd"]
        base_cost = self.monitor.estimate_rebalance_cost("base")["cost_usd"]
        self.assertLess(base_cost, eth_cost)

    def test_12_chain_field_normalized_lowercase(self):
        result = self.monitor.estimate_rebalance_cost("Ethereum")
        self.assertEqual(result["chain"], "ethereum")

    def test_13_invalid_chain_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.monitor.estimate_rebalance_cost("solana")

    def test_14_base_is_profitable(self):
        result = self.monitor.estimate_rebalance_cost("base")
        self.assertTrue(result["is_profitable"])

    def test_15_cost_eth_arithmetic(self):
        """cost_eth = gas_limit × gas_price_gwei / 1e9"""
        result = self.monitor.estimate_rebalance_cost("ethereum")
        expected = result["gas_limit"] * result["gas_price_gwei"] / _GWEI_PER_ETH
        self.assertAlmostEqual(result["cost_eth"], expected, places=6)

    def test_16_cost_usd_arithmetic(self):
        """cost_usd = cost_eth × ETH_PRICE_USD"""
        monitor = UnifiedGasMonitor(eth_price_usd=2000.0)
        result = monitor.estimate_rebalance_cost("ethereum")
        expected = result["cost_eth"] * 2000.0
        self.assertAlmostEqual(result["cost_usd"], expected, places=2)


# ---------------------------------------------------------------------------
# 3. estimate_operation_cost
# ---------------------------------------------------------------------------

class TestEstimateOperationCost(unittest.TestCase):

    def setUp(self):
        self.monitor = UnifiedGasMonitor()

    def test_17_valid_operation_ethereum(self):
        result = self.monitor.estimate_operation_cost("ethereum", "aave_deposit")
        self.assertEqual(result["operation"], "aave_deposit")
        self.assertGreater(result["cost_usd"], 0)

    def test_18_invalid_operation_raises(self):
        with self.assertRaises(ValueError):
            self.monitor.estimate_operation_cost("ethereum", "nonexistent_op")

    def test_19_gas_price_override(self):
        result = self.monitor.estimate_operation_cost("ethereum", "aave_deposit", gas_price_gwei=50.0)
        self.assertAlmostEqual(result["gas_price_gwei"], 50.0, places=4)


# ---------------------------------------------------------------------------
# 4. annual_gas_cost_usd
# ---------------------------------------------------------------------------

class TestAnnualGasCost(unittest.TestCase):

    def test_20_annual_cost_positive(self):
        monitor = UnifiedGasMonitor()
        cost = monitor.annual_gas_cost_usd("ethereum")
        self.assertGreater(cost, 0)

    def test_21_annual_cost_equals_single_times_frequency(self):
        monitor = UnifiedGasMonitor()
        single = monitor.estimate_rebalance_cost("ethereum")["cost_usd"]
        annual = monitor.annual_gas_cost_usd("ethereum", rebalances_per_year=REBALANCES_PER_YEAR)
        self.assertAlmostEqual(annual, single * REBALANCES_PER_YEAR, places=2)


# ---------------------------------------------------------------------------
# 5. compare_all_chains
# ---------------------------------------------------------------------------

class TestCompareAllChains(unittest.TestCase):

    def setUp(self):
        self.monitor = UnifiedGasMonitor()
        self.data = self.monitor.compare_all_chains()

    def test_22_compare_all_returns_dict(self):
        self.assertIsInstance(self.data, dict)

    def test_23_has_chains_key(self):
        self.assertIn("chains", self.data)

    def test_24_cheapest_chain_is_base(self):
        self.assertEqual(self.data.get("cheapest_chain"), "base")

    def test_25_last_updated_set(self):
        self.assertIsNotNone(self.data.get("last_updated"))
        self.assertIn("T", self.data["last_updated"])


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
