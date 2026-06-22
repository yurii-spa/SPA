"""
Tests for MP-945 DeFiGasOptimizationAdvisor
≥85 unittest tests covering all branches, edge-cases, and data shapes.
Run: python3 -m unittest spa_core.tests.test_defi_gas_optimization_advisor -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.defi_gas_optimization_advisor import (
    BASE_TX_GAS_OVERHEAD,
    DEFAULT_ETH_PRICE_USD,
    DeFiGasOptimizationAdvisor,
    _batch_savings_usd,
    _compute_flags,
    _estimated_savings_usd,
    _optimization_label,
    _optimal_gas_price_gwei,
    _tx_cost_usd,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_tx(**kwargs):
    """Build a transaction dict with sensible defaults."""
    defaults = {
        "protocol": "Aave",
        "tx_type": "stake",
        "gas_used": 100_000,
        "current_gas_price_gwei": 20.0,
        "base_fee_gwei": 15.0,
        "priority_fee_gwei": 2.0,
        "tx_value_usd": 10_000.0,
        "time_sensitivity": "flexible",
        "chain": "ethereum",
        "batch_possible": False,
    }
    defaults.update(kwargs)
    return defaults


def _cheap_tx(**kwargs):
    """A tx cheap enough to be OPTIMAL."""
    return _make_tx(gas_used=50_000, current_gas_price_gwei=5.0, tx_value_usd=100_000.0, **kwargs)


def _expensive_tx(**kwargs):
    """A tx expensive relative to value → PROHIBITIVE."""
    return _make_tx(gas_used=300_000, current_gas_price_gwei=100.0, tx_value_usd=100.0, **kwargs)


def _make_advisor_with_tmpdir():
    td = tempfile.mkdtemp()
    return DeFiGasOptimizationAdvisor(data_dir=td), td


ETH_PRICE = DEFAULT_ETH_PRICE_USD


# ---------------------------------------------------------------------------
# 1. _tx_cost_usd
# ---------------------------------------------------------------------------

class TestTxCostUsd(unittest.TestCase):

    def test_basic_calculation(self):
        # 100000 gas * 20 gwei * 3000 / 1e9 = 6.0 USD
        result = _tx_cost_usd(100_000, 20.0, 3000.0)
        self.assertAlmostEqual(result, 6.0)

    def test_zero_gas_used(self):
        self.assertAlmostEqual(_tx_cost_usd(0, 20.0, 3000.0), 0.0)

    def test_zero_gas_price(self):
        self.assertAlmostEqual(_tx_cost_usd(100_000, 0.0, 3000.0), 0.0)

    def test_zero_eth_price(self):
        self.assertAlmostEqual(_tx_cost_usd(100_000, 20.0, 0.0), 0.0)

    def test_scales_with_gas_used(self):
        c1 = _tx_cost_usd(100_000, 20.0, 3000.0)
        c2 = _tx_cost_usd(200_000, 20.0, 3000.0)
        self.assertAlmostEqual(c2, 2 * c1)

    def test_scales_with_gas_price(self):
        c1 = _tx_cost_usd(100_000, 10.0, 3000.0)
        c2 = _tx_cost_usd(100_000, 20.0, 3000.0)
        self.assertAlmostEqual(c2, 2 * c1)

    def test_scales_with_eth_price(self):
        c1 = _tx_cost_usd(100_000, 20.0, 1500.0)
        c2 = _tx_cost_usd(100_000, 20.0, 3000.0)
        self.assertAlmostEqual(c2, 2 * c1)

    def test_high_gas_scenario(self):
        # 500k gas * 200 gwei * 4000 USD / 1e9 = 400 USD
        result = _tx_cost_usd(500_000, 200.0, 4000.0)
        self.assertAlmostEqual(result, 400.0)

    def test_low_gas_scenario(self):
        # 21000 gas * 1 gwei * 3000 / 1e9 = 0.063 USD
        result = _tx_cost_usd(21_000, 1.0, 3000.0)
        self.assertAlmostEqual(result, 0.063)


# ---------------------------------------------------------------------------
# 2. _optimal_gas_price_gwei
# ---------------------------------------------------------------------------

class TestOptimalGasPrice(unittest.TestCase):

    def test_urgent_returns_current(self):
        tx = _make_tx(time_sensitivity="urgent", current_gas_price_gwei=50.0, base_fee_gwei=30.0)
        self.assertAlmostEqual(_optimal_gas_price_gwei(tx), 50.0)

    def test_flexible_returns_lower_than_current(self):
        tx = _make_tx(time_sensitivity="flexible", current_gas_price_gwei=50.0, base_fee_gwei=30.0)
        optimal = _optimal_gas_price_gwei(tx)
        self.assertLess(optimal, 50.0)

    def test_very_flexible_returns_lower_than_current(self):
        tx = _make_tx(time_sensitivity="very_flexible", current_gas_price_gwei=50.0, base_fee_gwei=30.0)
        optimal = _optimal_gas_price_gwei(tx)
        self.assertLess(optimal, 50.0)

    def test_optimal_never_exceeds_current(self):
        tx = _make_tx(time_sensitivity="flexible", current_gas_price_gwei=10.0, base_fee_gwei=8.0)
        optimal = _optimal_gas_price_gwei(tx)
        self.assertLessEqual(optimal, 10.0)

    def test_optimal_at_least_base_fee_plus_min(self):
        tx = _make_tx(time_sensitivity="flexible", current_gas_price_gwei=100.0, base_fee_gwei=20.0)
        optimal = _optimal_gas_price_gwei(tx)
        self.assertGreaterEqual(optimal, 20.5)  # base_fee + 0.5 minimum

    def test_flexible_with_zero_base_fee(self):
        tx = _make_tx(time_sensitivity="flexible", current_gas_price_gwei=10.0, base_fee_gwei=0.0)
        optimal = _optimal_gas_price_gwei(tx)
        self.assertGreaterEqual(optimal, 0.5)

    def test_very_flexible_same_as_flexible(self):
        tx_flex = _make_tx(time_sensitivity="flexible", current_gas_price_gwei=50.0, base_fee_gwei=30.0)
        tx_vflex = _make_tx(time_sensitivity="very_flexible", current_gas_price_gwei=50.0, base_fee_gwei=30.0)
        self.assertAlmostEqual(_optimal_gas_price_gwei(tx_flex), _optimal_gas_price_gwei(tx_vflex))


# ---------------------------------------------------------------------------
# 3. _estimated_savings_usd
# ---------------------------------------------------------------------------

class TestEstimatedSavings(unittest.TestCase):

    def test_urgent_saves_nothing(self):
        tx = _make_tx(time_sensitivity="urgent", gas_used=200_000,
                      current_gas_price_gwei=50.0, base_fee_gwei=30.0)
        self.assertAlmostEqual(_estimated_savings_usd(tx, 30.0, ETH_PRICE), 0.0)

    def test_flexible_saves_when_optimal_lower(self):
        tx = _make_tx(time_sensitivity="flexible", gas_used=200_000,
                      current_gas_price_gwei=50.0, base_fee_gwei=30.0)
        savings = _estimated_savings_usd(tx, 34.0, ETH_PRICE)
        expected = (50.0 - 34.0) * 200_000 * ETH_PRICE / 1e9
        self.assertAlmostEqual(savings, expected, places=4)

    def test_no_savings_if_optimal_equals_current(self):
        tx = _make_tx(time_sensitivity="flexible", gas_used=100_000,
                      current_gas_price_gwei=20.0, base_fee_gwei=15.0)
        self.assertAlmostEqual(_estimated_savings_usd(tx, 20.0, ETH_PRICE), 0.0)

    def test_no_savings_if_optimal_above_current(self):
        tx = _make_tx(time_sensitivity="flexible", gas_used=100_000,
                      current_gas_price_gwei=10.0, base_fee_gwei=5.0)
        self.assertAlmostEqual(_estimated_savings_usd(tx, 15.0, ETH_PRICE), 0.0)

    def test_savings_never_negative(self):
        tx = _make_tx(time_sensitivity="flexible", gas_used=0,
                      current_gas_price_gwei=50.0, base_fee_gwei=30.0)
        self.assertGreaterEqual(_estimated_savings_usd(tx, 20.0, ETH_PRICE), 0.0)

    def test_very_flexible_also_computes_savings(self):
        tx = _make_tx(time_sensitivity="very_flexible", gas_used=200_000,
                      current_gas_price_gwei=60.0, base_fee_gwei=40.0)
        savings = _estimated_savings_usd(tx, 45.0, ETH_PRICE)
        self.assertGreater(savings, 0.0)


# ---------------------------------------------------------------------------
# 4. _batch_savings_usd
# ---------------------------------------------------------------------------

class TestBatchSavings(unittest.TestCase):

    def test_no_batch_possible_zero_savings(self):
        tx = _make_tx(batch_possible=False, current_gas_price_gwei=20.0)
        self.assertAlmostEqual(_batch_savings_usd(tx, ETH_PRICE), 0.0)

    def test_batch_possible_nonzero_savings(self):
        tx = _make_tx(batch_possible=True, current_gas_price_gwei=20.0)
        savings = _batch_savings_usd(tx, ETH_PRICE)
        expected = BASE_TX_GAS_OVERHEAD * 20.0 * ETH_PRICE / 1e9
        self.assertAlmostEqual(savings, expected)

    def test_batch_savings_zero_if_zero_gas_price(self):
        tx = _make_tx(batch_possible=True, current_gas_price_gwei=0.0)
        self.assertAlmostEqual(_batch_savings_usd(tx, ETH_PRICE), 0.0)

    def test_batch_savings_scales_with_gas_price(self):
        tx1 = _make_tx(batch_possible=True, current_gas_price_gwei=10.0)
        tx2 = _make_tx(batch_possible=True, current_gas_price_gwei=20.0)
        self.assertAlmostEqual(_batch_savings_usd(tx2, ETH_PRICE), 2 * _batch_savings_usd(tx1, ETH_PRICE))

    def test_batch_savings_uses_base_overhead(self):
        tx = _make_tx(batch_possible=True, current_gas_price_gwei=1.0)
        savings = _batch_savings_usd(tx, 1e9)
        # 21000 * 1 * 1e9 / 1e9 = 21000 USD
        self.assertAlmostEqual(savings, 21000.0)


# ---------------------------------------------------------------------------
# 5. _optimization_label
# ---------------------------------------------------------------------------

class TestOptimizationLabel(unittest.TestCase):

    def test_optimal(self):
        self.assertEqual(_optimization_label(0.1), "OPTIMAL")

    def test_optimal_at_zero(self):
        self.assertEqual(_optimization_label(0.0), "OPTIMAL")

    def test_optimal_just_below_threshold(self):
        self.assertEqual(_optimization_label(0.49), "OPTIMAL")

    def test_acceptable(self):
        self.assertEqual(_optimization_label(0.7), "ACCEPTABLE")

    def test_acceptable_at_lower_bound(self):
        self.assertEqual(_optimization_label(0.5), "ACCEPTABLE")

    def test_acceptable_just_below_upper(self):
        self.assertEqual(_optimization_label(0.99), "ACCEPTABLE")

    def test_expensive(self):
        self.assertEqual(_optimization_label(1.5), "EXPENSIVE")

    def test_expensive_at_lower_bound(self):
        self.assertEqual(_optimization_label(1.0), "EXPENSIVE")

    def test_very_expensive(self):
        self.assertEqual(_optimization_label(3.0), "VERY_EXPENSIVE")

    def test_very_expensive_at_lower_bound(self):
        self.assertEqual(_optimization_label(2.0), "VERY_EXPENSIVE")

    def test_prohibitive(self):
        self.assertEqual(_optimization_label(10.0), "PROHIBITIVE")

    def test_prohibitive_at_threshold(self):
        self.assertEqual(_optimization_label(5.0), "PROHIBITIVE")

    def test_very_high_pct(self):
        self.assertEqual(_optimization_label(100.0), "PROHIBITIVE")


# ---------------------------------------------------------------------------
# 6. _compute_flags
# ---------------------------------------------------------------------------

class TestComputeFlags(unittest.TestCase):

    def test_no_flags_neutral(self):
        tx = _make_tx(batch_possible=False, tx_value_usd=10_000, time_sensitivity="urgent",
                      priority_fee_gwei=1.0, base_fee_gwei=10.0, chain="arbitrum")
        flags = _compute_flags(tx, cost_usd=1.0, savings_usd=0.0, batch_save=0.0)
        self.assertEqual(flags, [])

    def test_batch_recommended(self):
        tx = _make_tx(batch_possible=True)
        flags = _compute_flags(tx, cost_usd=15.0, savings_usd=0.0, batch_save=1.0)
        self.assertIn("BATCH_RECOMMENDED", flags)

    def test_no_batch_if_cost_below_threshold(self):
        tx = _make_tx(batch_possible=True)
        flags = _compute_flags(tx, cost_usd=5.0, savings_usd=0.0, batch_save=0.5)
        self.assertNotIn("BATCH_RECOMMENDED", flags)

    def test_no_batch_if_not_possible(self):
        tx = _make_tx(batch_possible=False)
        flags = _compute_flags(tx, cost_usd=50.0, savings_usd=0.0, batch_save=0.0)
        self.assertNotIn("BATCH_RECOMMENDED", flags)

    def test_wait_recommended_flexible(self):
        tx = _make_tx(time_sensitivity="flexible")
        flags = _compute_flags(tx, cost_usd=10.0, savings_usd=10.0, batch_save=0.0)
        self.assertIn("WAIT_RECOMMENDED", flags)

    def test_wait_recommended_very_flexible(self):
        tx = _make_tx(time_sensitivity="very_flexible")
        flags = _compute_flags(tx, cost_usd=10.0, savings_usd=10.0, batch_save=0.0)
        self.assertIn("WAIT_RECOMMENDED", flags)

    def test_no_wait_if_urgent(self):
        tx = _make_tx(time_sensitivity="urgent")
        flags = _compute_flags(tx, cost_usd=10.0, savings_usd=20.0, batch_save=0.0)
        self.assertNotIn("WAIT_RECOMMENDED", flags)

    def test_no_wait_if_savings_below_threshold(self):
        tx = _make_tx(time_sensitivity="flexible")
        flags = _compute_flags(tx, cost_usd=10.0, savings_usd=3.0, batch_save=0.0)
        self.assertNotIn("WAIT_RECOMMENDED", flags)

    def test_high_priority_fee(self):
        tx = _make_tx(base_fee_gwei=10.0, priority_fee_gwei=25.0)
        flags = _compute_flags(tx, cost_usd=5.0, savings_usd=0.0, batch_save=0.0)
        self.assertIn("HIGH_PRIORITY_FEE", flags)

    def test_no_high_priority_fee_normal(self):
        tx = _make_tx(base_fee_gwei=10.0, priority_fee_gwei=15.0)
        flags = _compute_flags(tx, cost_usd=5.0, savings_usd=0.0, batch_save=0.0)
        self.assertNotIn("HIGH_PRIORITY_FEE", flags)

    def test_high_priority_fee_zero_base_fee_no_flag(self):
        tx = _make_tx(base_fee_gwei=0.0, priority_fee_gwei=10.0)
        flags = _compute_flags(tx, cost_usd=5.0, savings_usd=0.0, batch_save=0.0)
        self.assertNotIn("HIGH_PRIORITY_FEE", flags)

    def test_small_tx_gas_heavy(self):
        tx = _make_tx(tx_value_usd=50.0)
        flags = _compute_flags(tx, cost_usd=8.0, savings_usd=0.0, batch_save=0.0)
        self.assertIn("SMALL_TX_GAS_HEAVY", flags)

    def test_no_small_tx_large_value(self):
        tx = _make_tx(tx_value_usd=1000.0)
        flags = _compute_flags(tx, cost_usd=8.0, savings_usd=0.0, batch_save=0.0)
        self.assertNotIn("SMALL_TX_GAS_HEAVY", flags)

    def test_no_small_tx_low_cost(self):
        tx = _make_tx(tx_value_usd=50.0)
        flags = _compute_flags(tx, cost_usd=2.0, savings_usd=0.0, batch_save=0.0)
        self.assertNotIn("SMALL_TX_GAS_HEAVY", flags)

    def test_l2_recommended(self):
        tx = _make_tx(chain="ethereum")
        flags = _compute_flags(tx, cost_usd=60.0, savings_usd=0.0, batch_save=0.0)
        self.assertIn("L2_RECOMMENDED", flags)

    def test_no_l2_not_ethereum(self):
        tx = _make_tx(chain="arbitrum")
        flags = _compute_flags(tx, cost_usd=100.0, savings_usd=0.0, batch_save=0.0)
        self.assertNotIn("L2_RECOMMENDED", flags)

    def test_no_l2_below_cost_threshold(self):
        tx = _make_tx(chain="ethereum")
        flags = _compute_flags(tx, cost_usd=20.0, savings_usd=0.0, batch_save=0.0)
        self.assertNotIn("L2_RECOMMENDED", flags)

    def test_chain_case_insensitive(self):
        tx = _make_tx(chain="Ethereum")
        flags = _compute_flags(tx, cost_usd=100.0, savings_usd=0.0, batch_save=0.0)
        self.assertIn("L2_RECOMMENDED", flags)


# ---------------------------------------------------------------------------
# 7. DeFiGasOptimizationAdvisor.advise() — basic
# ---------------------------------------------------------------------------

class TestAdviseBasic(unittest.TestCase):

    def setUp(self):
        self.advisor, self.tmpdir = _make_advisor_with_tmpdir()

    def test_empty_transactions(self):
        result = self.advisor.advise([])
        self.assertEqual(result["transaction_count"], 0)
        self.assertEqual(result["transactions"], [])

    def test_empty_aggregates(self):
        result = self.advisor.advise([])
        agg = result["aggregates"]
        self.assertIsNone(agg["most_expensive_tx"])
        self.assertIsNone(agg["cheapest_tx"])
        self.assertEqual(agg["total_gas_cost_usd"], 0.0)
        self.assertEqual(agg["total_potential_savings_usd"], 0.0)
        self.assertEqual(agg["prohibitive_count"], 0)

    def test_single_transaction(self):
        result = self.advisor.advise([_make_tx()])
        self.assertEqual(result["transaction_count"], 1)
        self.assertEqual(len(result["transactions"]), 1)

    def test_result_has_timestamp(self):
        result = self.advisor.advise([_make_tx()])
        self.assertIn("timestamp", result)

    def test_result_required_keys(self):
        result = self.advisor.advise([_make_tx()])
        for k in ("timestamp", "transaction_count", "transactions", "aggregates"):
            self.assertIn(k, result)

    def test_tx_fields_present(self):
        result = self.advisor.advise([_make_tx()])
        tx = result["transactions"][0]
        for k in ("protocol", "tx_type", "gas_used", "tx_cost_usd",
                  "cost_as_pct_of_value", "optimal_gas_price_gwei",
                  "estimated_savings_usd", "batch_savings_usd",
                  "optimization_label", "flags"):
            self.assertIn(k, tx)

    def test_none_config_defaults(self):
        result = self.advisor.advise([_make_tx()], config=None)
        self.assertIsNotNone(result)

    def test_custom_eth_price(self):
        tx = _make_tx(gas_used=100_000, current_gas_price_gwei=20.0, tx_value_usd=100_000.0)
        r1 = self.advisor.advise([tx], config={"eth_price_usd": 3000.0})
        r2 = self.advisor.advise([tx], config={"eth_price_usd": 6000.0})
        cost1 = r1["transactions"][0]["tx_cost_usd"]
        cost2 = r2["transactions"][0]["tx_cost_usd"]
        self.assertAlmostEqual(cost2, 2 * cost1, places=4)


# ---------------------------------------------------------------------------
# 8. tx_cost_usd and cost_as_pct
# ---------------------------------------------------------------------------

class TestTxCostInResult(unittest.TestCase):

    def setUp(self):
        self.advisor, self.tmpdir = _make_advisor_with_tmpdir()

    def test_tx_cost_computed_correctly(self):
        tx = _make_tx(gas_used=100_000, current_gas_price_gwei=20.0, tx_value_usd=10_000.0)
        result = self.advisor.advise([tx], config={"eth_price_usd": 3000.0})
        # 100000 * 20 * 3000 / 1e9 = 6.0
        self.assertAlmostEqual(result["transactions"][0]["tx_cost_usd"], 6.0, places=4)

    def test_cost_as_pct_computed(self):
        tx = _make_tx(gas_used=100_000, current_gas_price_gwei=20.0, tx_value_usd=600.0)
        result = self.advisor.advise([tx], config={"eth_price_usd": 3000.0})
        # cost = 6.0, pct = 6/600*100 = 1.0%
        self.assertAlmostEqual(result["transactions"][0]["cost_as_pct_of_value"], 1.0, places=3)

    def test_cost_pct_zero_value(self):
        tx = _make_tx(gas_used=100_000, current_gas_price_gwei=20.0, tx_value_usd=0.0)
        result = self.advisor.advise([tx])
        self.assertAlmostEqual(result["transactions"][0]["cost_as_pct_of_value"], 0.0)

    def test_labels_match_cost_pct(self):
        # cheap tx → OPTIMAL
        tx = _cheap_tx()
        result = self.advisor.advise([tx], config={"eth_price_usd": 3000.0})
        label = result["transactions"][0]["optimization_label"]
        self.assertEqual(label, "OPTIMAL")

    def test_expensive_tx_prohibitive(self):
        tx = _expensive_tx()
        result = self.advisor.advise([tx], config={"eth_price_usd": 3000.0})
        label = result["transactions"][0]["optimization_label"]
        self.assertEqual(label, "PROHIBITIVE")


# ---------------------------------------------------------------------------
# 9. Aggregates
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):

    def setUp(self):
        self.advisor, self.tmpdir = _make_advisor_with_tmpdir()

    def _two_txs(self):
        cheap = _make_tx(protocol="CheapProtocol", gas_used=10_000, current_gas_price_gwei=5.0,
                         tx_value_usd=10_000, time_sensitivity="urgent")
        expensive = _make_tx(protocol="ExpProtocol", gas_used=500_000, current_gas_price_gwei=100.0,
                             tx_value_usd=10_000, time_sensitivity="urgent")
        return cheap, expensive

    def test_most_expensive_tx(self):
        cheap, expensive = self._two_txs()
        result = self.advisor.advise([cheap, expensive])
        self.assertEqual(result["aggregates"]["most_expensive_tx"], "ExpProtocol")

    def test_cheapest_tx(self):
        cheap, expensive = self._two_txs()
        result = self.advisor.advise([cheap, expensive])
        self.assertEqual(result["aggregates"]["cheapest_tx"], "CheapProtocol")

    def test_total_gas_cost_usd(self):
        tx1 = _make_tx(protocol="A", gas_used=100_000, current_gas_price_gwei=20.0, tx_value_usd=1000)
        tx2 = _make_tx(protocol="B", gas_used=200_000, current_gas_price_gwei=20.0, tx_value_usd=1000)
        result = self.advisor.advise([tx1, tx2], config={"eth_price_usd": 3000.0})
        # tx1: 6.0, tx2: 12.0, total: 18.0
        self.assertAlmostEqual(result["aggregates"]["total_gas_cost_usd"], 18.0, places=3)

    def test_prohibitive_count(self):
        cheap = _cheap_tx()
        prohibitive = _expensive_tx()
        result = self.advisor.advise([cheap, prohibitive], config={"eth_price_usd": 3000.0})
        self.assertEqual(result["aggregates"]["prohibitive_count"], 1)

    def test_prohibitive_count_zero_all_cheap(self):
        result = self.advisor.advise([_cheap_tx(), _cheap_tx()], config={"eth_price_usd": 3000.0})
        self.assertEqual(result["aggregates"]["prohibitive_count"], 0)

    def test_total_potential_savings_includes_batch(self):
        tx = _make_tx(batch_possible=True, current_gas_price_gwei=100.0,
                      base_fee_gwei=10.0, time_sensitivity="flexible",
                      gas_used=200_000, tx_value_usd=10_000)
        result = self.advisor.advise([tx], config={"eth_price_usd": 3000.0})
        self.assertGreater(result["aggregates"]["total_potential_savings_usd"], 0.0)

    def test_single_tx_most_equals_cheapest(self):
        result = self.advisor.advise([_make_tx()])
        self.assertEqual(result["aggregates"]["most_expensive_tx"],
                         result["aggregates"]["cheapest_tx"])


# ---------------------------------------------------------------------------
# 10. Ring-buffer log
# ---------------------------------------------------------------------------

class TestLog(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.advisor = DeFiGasOptimizationAdvisor(data_dir=self.tmpdir)
        self.log_path = os.path.join(self.tmpdir, "gas_optimization_log.json")

    def test_log_created(self):
        self.advisor.advise([_make_tx()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_valid_json(self):
        self.advisor.advise([_make_tx()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)

    def test_log_has_entries(self):
        self.advisor.advise([_make_tx()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("entries", data)
        self.assertEqual(len(data["entries"]), 1)

    def test_log_appends(self):
        self.advisor.advise([_make_tx()])
        self.advisor.advise([_make_tx()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data["entries"]), 2)

    def test_log_ring_buffer_cap(self):
        for _ in range(110):
            self.advisor.advise([_make_tx()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data["entries"]), 100)

    def test_log_entry_keys(self):
        self.advisor.advise([_make_tx()])
        with open(self.log_path) as f:
            data = json.load(f)
        entry = data["entries"][0]
        for k in ("timestamp", "transaction_count", "total_gas_cost_usd",
                  "total_potential_savings_usd", "prohibitive_count"):
            self.assertIn(k, entry)

    def test_log_has_last_updated(self):
        self.advisor.advise([_make_tx()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("last_updated", data)

    def test_no_tmp_file_after_write(self):
        self.advisor.advise([_make_tx()])
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_empty_advise_also_logs(self):
        self.advisor.advise([])
        self.assertTrue(os.path.exists(self.log_path))


# ---------------------------------------------------------------------------
# 11. Edge cases and passthrough
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.advisor, self.tmpdir = _make_advisor_with_tmpdir()

    def test_protocol_passthrough(self):
        result = self.advisor.advise([_make_tx(protocol="Compound")])
        self.assertEqual(result["transactions"][0]["protocol"], "Compound")

    def test_tx_type_passthrough(self):
        result = self.advisor.advise([_make_tx(tx_type="swap")])
        self.assertEqual(result["transactions"][0]["tx_type"], "swap")

    def test_chain_passthrough(self):
        result = self.advisor.advise([_make_tx(chain="polygon")])
        self.assertEqual(result["transactions"][0]["chain"], "polygon")

    def test_flags_is_list(self):
        result = self.advisor.advise([_make_tx()])
        self.assertIsInstance(result["transactions"][0]["flags"], list)

    def test_missing_fields_default(self):
        result = self.advisor.advise([{"protocol": "Bare"}])
        self.assertEqual(result["transactions"][0]["tx_cost_usd"], 0.0)

    def test_batch_possible_false_no_batch_savings(self):
        result = self.advisor.advise([_make_tx(batch_possible=False)])
        self.assertAlmostEqual(result["transactions"][0]["batch_savings_usd"], 0.0)

    def test_batch_possible_true_has_batch_savings(self):
        result = self.advisor.advise([_make_tx(batch_possible=True, current_gas_price_gwei=30.0)])
        self.assertGreater(result["transactions"][0]["batch_savings_usd"], 0.0)

    def test_default_log_path_when_no_data_dir(self):
        a = DeFiGasOptimizationAdvisor()
        self.assertIn("gas_optimization_log", a._log_path())

    def test_custom_data_dir_in_log_path(self):
        td = tempfile.mkdtemp()
        a = DeFiGasOptimizationAdvisor(data_dir=td)
        self.assertTrue(a._log_path().startswith(td))

    def test_multiple_txs_all_in_result(self):
        txs = [_make_tx(protocol=f"P{i}") for i in range(10)]
        result = self.advisor.advise(txs)
        self.assertEqual(result["transaction_count"], 10)
        self.assertEqual(len(result["transactions"]), 10)


if __name__ == "__main__":
    unittest.main()
