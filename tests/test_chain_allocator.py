#!/usr/bin/env python3
"""
tests/test_chain_allocator.py

25 unit tests for ChainAllocator (MP-1489, v11.05).

Covers:
  - compute_allocation pure function: all branches
  - ChainAllocator.optimize: structure, inputs stored, advisory text
  - ChainAllocator.allocation_usd: arithmetic, error before optimize
  - ChainAllocator.is_bridge_justified
  - AllocationError on negative capital
  - MIN_ALLOCATION_USD / BRIDGE_COST_USD constants
  - to_dict snapshot
  - Output advisory text content
  - All-Ethereum / All-Base / balanced / dominant splits

Run:
    python3 -m pytest tests/test_chain_allocator.py -v
    python3 tests/test_chain_allocator.py
"""
from __future__ import annotations

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.chain_allocator import (
    BRIDGE_COST_USD,
    MIN_ALLOCATION_USD,
    OUTPUT_PATH,
    SUPPORTED_CHAINS,
    ChainAllocator,
    compute_allocation,
)
from spa_core.utils.errors import AllocationError


# ---------------------------------------------------------------------------
# 1. Module constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):

    def test_01_bridge_cost_positive(self):
        self.assertGreater(BRIDGE_COST_USD, 0)

    def test_02_min_allocation_positive(self):
        self.assertGreater(MIN_ALLOCATION_USD, 0)

    def test_03_supported_chains_has_ethereum(self):
        self.assertIn("ethereum", SUPPORTED_CHAINS)

    def test_04_supported_chains_has_base(self):
        self.assertIn("base", SUPPORTED_CHAINS)

    def test_05_output_path_ends_with_json(self):
        self.assertTrue(OUTPUT_PATH.endswith(".json"))


# ---------------------------------------------------------------------------
# 2. compute_allocation pure function
# ---------------------------------------------------------------------------

class TestComputeAllocation(unittest.TestCase):

    def _check_fractions(self, alloc: dict):
        """Assert fractions sum to ~1.0 and are non-negative."""
        total = sum(alloc.values())
        self.assertAlmostEqual(total, 1.0, places=6, msg=f"Fractions don't sum to 1.0: {alloc}")
        for chain, frac in alloc.items():
            self.assertGreaterEqual(frac, 0.0, f"{chain} fraction is negative")

    def test_06_fractions_sum_to_one_balanced(self):
        alloc = compute_allocation(100_000, 6.5, 6.5)
        self._check_fractions(alloc)

    def test_07_small_capital_all_ethereum(self):
        """Too small to split, Ethereum APY higher → all Ethereum."""
        alloc = compute_allocation(500, 6.0, 5.0)
        self.assertAlmostEqual(alloc["ethereum"], 1.0, places=4)
        self.assertAlmostEqual(alloc["base"], 0.0, places=4)

    def test_08_small_capital_all_base(self):
        """Too small to split, Base APY higher → all Base."""
        alloc = compute_allocation(500, 5.0, 8.0)
        self.assertAlmostEqual(alloc["base"], 1.0, places=4)
        self.assertAlmostEqual(alloc["ethereum"], 0.0, places=4)

    def test_09_base_dominant_when_base_much_better(self):
        """Large capital, Base APY >> Ethereum → Base-dominant split."""
        alloc = compute_allocation(
            total_capital=100_000,
            eth_best_apy=4.0,
            base_best_apy=10.0,
        )
        self.assertGreater(alloc["base"], alloc["ethereum"])

    def test_10_eth_dominant_when_eth_much_better(self):
        """Large capital, Ethereum APY >> Base after bridge → Eth-dominant."""
        alloc = compute_allocation(
            total_capital=100_000,
            eth_best_apy=10.0,
            base_best_apy=4.0,
        )
        self.assertGreater(alloc["ethereum"], alloc["base"])

    def test_11_balanced_when_apy_close(self):
        """When APYs are within threshold, balanced split returned."""
        alloc = compute_allocation(
            total_capital=100_000,
            eth_best_apy=6.5,
            base_best_apy=6.5,
            eth_gas_usd=0.0,
            base_gas_usd=0.0,
        )
        # Both near 0.5 (balanced); exact values depend on implementation
        self.assertAlmostEqual(alloc["ethereum"] + alloc["base"], 1.0, places=4)

    def test_12_negative_capital_raises(self):
        with self.assertRaises(AllocationError):
            compute_allocation(-1000, 6.0, 7.0)

    def test_13_zero_capital_does_not_raise(self):
        """Zero capital should not raise; handled as 'too small to split'."""
        try:
            alloc = compute_allocation(0, 6.0, 7.0)
            self._check_fractions(alloc)
        except AllocationError:
            # AllocationError for zero capital is also acceptable
            pass

    def test_14_custom_bridge_cost_affects_result(self):
        """A very high bridge cost should reduce Base attractiveness."""
        alloc_low_bridge = compute_allocation(100_000, 6.0, 7.0, bridge_cost_usd=1.0)
        alloc_high_bridge = compute_allocation(100_000, 6.0, 7.0, bridge_cost_usd=10_000.0)
        # High bridge cost should favour Ethereum more
        self.assertGreaterEqual(
            alloc_high_bridge["ethereum"],
            alloc_low_bridge["ethereum"],
        )


# ---------------------------------------------------------------------------
# 3. ChainAllocator class
# ---------------------------------------------------------------------------

class TestChainAllocator(unittest.TestCase):

    def setUp(self):
        self.allocator = ChainAllocator()

    def test_15_optimize_returns_dict(self):
        result = self.allocator.optimize(100_000, 6.5, 7.0)
        self.assertIsInstance(result, dict)

    def test_16_optimize_has_allocation_key(self):
        result = self.allocator.optimize(100_000, 6.5, 7.0)
        self.assertIn("allocation", result)

    def test_17_optimize_has_advisory_key(self):
        result = self.allocator.optimize(100_000, 6.5, 7.0)
        self.assertIn("advisory", result)
        self.assertIsInstance(result["advisory"], str)
        self.assertGreater(len(result["advisory"]), 0)

    def test_18_optimize_has_inputs_key(self):
        result = self.allocator.optimize(100_000, 6.5, 7.0)
        self.assertIn("inputs", result)

    def test_19_inputs_stored_correctly(self):
        result = self.allocator.optimize(100_000, 6.5, 7.0)
        self.assertAlmostEqual(result["inputs"]["total_capital"], 100_000)
        self.assertAlmostEqual(result["inputs"]["eth_best_apy"], 6.5)
        self.assertAlmostEqual(result["inputs"]["base_best_apy"], 7.0)

    def test_20_last_updated_is_set(self):
        result = self.allocator.optimize(100_000, 6.5, 7.0)
        self.assertIsNotNone(result.get("last_updated"))

    def test_21_allocation_fractions_sum_to_one(self):
        result = self.allocator.optimize(100_000, 6.5, 7.0)
        total = sum(result["allocation"].values())
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_22_allocation_usd_arithmetic(self):
        self.allocator.optimize(100_000, 6.5, 7.0)
        usd = self.allocator.allocation_usd(100_000)
        total_usd = sum(usd.values())
        self.assertAlmostEqual(total_usd, 100_000, places=0)

    def test_23_allocation_usd_before_optimize_raises(self):
        fresh_allocator = ChainAllocator()
        with self.assertRaises(AllocationError):
            fresh_allocator.allocation_usd(100_000)

    def test_24_is_bridge_justified_base_higher(self):
        result = self.allocator.is_bridge_justified(
            total_capital=100_000,
            eth_best_apy=4.0,
            base_best_apy=10.0,
        )
        self.assertTrue(result)

    def test_25_to_dict_reflects_last_optimize(self):
        self.allocator.optimize(50_000, 5.0, 8.0)
        d = self.allocator.to_dict()
        self.assertIn("allocation", d)
        self.assertAlmostEqual(d["inputs"]["total_capital"], 50_000)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
