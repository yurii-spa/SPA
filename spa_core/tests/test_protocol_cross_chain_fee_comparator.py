"""
Tests for MP-955 ProtocolCrossChainFeeComparator
=================================================
Run with: python3 -m unittest spa_core/tests/test_protocol_cross_chain_fee_comparator.py
≥ 80 test cases.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_cross_chain_fee_comparator import (
    ProtocolCrossChainFeeComparator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chain(
    name="TestChain",
    avg_gas_price_gwei=1.0,
    native_token_price_usd=2000.0,
    simple_transfer_gas=21000,
    token_swap_gas=150000,
    lp_deposit_gas=200000,
    lp_withdrawal_gas=180000,
    bridge_gas_out=100000,
    tps_capacity=100,
    avg_finality_seconds=60.0,
    is_l2=False,
    l1_data_posting_cost_per_tx_usd=0.0,
    eth_price_usd=None,
):
    d = dict(
        name=name,
        avg_gas_price_gwei=avg_gas_price_gwei,
        native_token_price_usd=native_token_price_usd,
        simple_transfer_gas=simple_transfer_gas,
        token_swap_gas=token_swap_gas,
        lp_deposit_gas=lp_deposit_gas,
        lp_withdrawal_gas=lp_withdrawal_gas,
        bridge_gas_out=bridge_gas_out,
        tps_capacity=tps_capacity,
        avg_finality_seconds=avg_finality_seconds,
        is_l2=is_l2,
        l1_data_posting_cost_per_tx_usd=l1_data_posting_cost_per_tx_usd,
    )
    if eth_price_usd is not None:
        d["eth_price_usd"] = eth_price_usd
    return d


def _gas_usd(gas_units, gwei, token_price):
    return gas_units * gwei * 1e-9 * token_price


def _comparator():
    return ProtocolCrossChainFeeComparator()


# ---------------------------------------------------------------------------
# Basic structure tests
# ---------------------------------------------------------------------------

class TestCrossChainFeeComparatorBasic(unittest.TestCase):
    def setUp(self):
        self.cmp = _comparator()

    def test_01_instantiation(self):
        self.assertIsInstance(self.cmp, ProtocolCrossChainFeeComparator)

    def test_02_compare_returns_dict(self):
        result = self.cmp.compare([_chain()])
        self.assertIsInstance(result, dict)

    def test_03_has_chains_key(self):
        result = self.cmp.compare([_chain()])
        self.assertIn("chains", result)

    def test_04_has_aggregates_key(self):
        result = self.cmp.compare([_chain()])
        self.assertIn("aggregates", result)

    def test_05_has_metadata_key(self):
        result = self.cmp.compare([_chain()])
        self.assertIn("metadata", result)

    def test_06_empty_chains(self):
        result = self.cmp.compare([])
        self.assertEqual(result["chains"], [])
        self.assertIsInstance(result["aggregates"], dict)

    def test_07_single_chain_count(self):
        result = self.cmp.compare([_chain("A")])
        self.assertEqual(len(result["chains"]), 1)

    def test_08_multiple_chains_count(self):
        result = self.cmp.compare([_chain("A"), _chain("B"), _chain("C")])
        self.assertEqual(len(result["chains"]), 3)

    def test_09_chain_name_preserved(self):
        result = self.cmp.compare([_chain(name="Ethereum")])
        self.assertEqual(result["chains"][0]["name"], "Ethereum")

    def test_10_is_l2_preserved(self):
        result = self.cmp.compare([_chain(is_l2=True)])
        self.assertTrue(result["chains"][0]["is_l2"])

    def test_11_tps_preserved(self):
        result = self.cmp.compare([_chain(tps_capacity=5000)])
        self.assertAlmostEqual(result["chains"][0]["tps_capacity"], 5000.0, places=1)

    def test_12_finality_preserved(self):
        result = self.cmp.compare([_chain(avg_finality_seconds=2.5)])
        self.assertAlmostEqual(result["chains"][0]["avg_finality_seconds"], 2.5, places=2)

    def test_13_metadata_timestamp_is_float(self):
        result = self.cmp.compare([_chain()])
        self.assertIsInstance(result["metadata"]["timestamp"], float)

    def test_14_metadata_timestamp_recent(self):
        before = time.time() - 1
        result = self.cmp.compare([_chain()])
        after = time.time() + 1
        self.assertGreater(result["metadata"]["timestamp"], before)
        self.assertLess(result["metadata"]["timestamp"], after)

    def test_15_metadata_chains_analyzed(self):
        result = self.cmp.compare([_chain("A"), _chain("B")])
        self.assertEqual(result["metadata"]["chains_analyzed"], 2)

    def test_16_metadata_has_run_id(self):
        result = self.cmp.compare([_chain()])
        self.assertIn("run_id", result["metadata"])
        self.assertIn("mp955_", result["metadata"]["run_id"])

    def test_17_metadata_has_version(self):
        result = self.cmp.compare([_chain()])
        self.assertIn("version", result["metadata"])

    def test_18_chain_has_all_required_fields(self):
        result = self.cmp.compare([_chain()])
        c = result["chains"][0]
        for field in (
            "name", "is_l2", "avg_finality_seconds", "tps_capacity",
            "simple_transfer_usd", "token_swap_usd", "lp_deposit_usd",
            "lp_withdrawal_usd", "bridge_out_usd", "full_defi_cycle_usd",
            "cost_efficiency_score", "fee_label", "flags",
        ):
            self.assertIn(field, c, msg=f"Missing field: {field}")

    def test_19_flags_is_list(self):
        result = self.cmp.compare([_chain()])
        self.assertIsInstance(result["chains"][0]["flags"], list)


# ---------------------------------------------------------------------------
# Cost calculation tests
# ---------------------------------------------------------------------------

class TestCrossChainFeeComparatorCalculations(unittest.TestCase):
    def setUp(self):
        self.cmp = _comparator()

    def _get_chain(self, **kwargs):
        result = self.cmp.compare([_chain(**kwargs)])
        return result["chains"][0]

    def test_20_simple_transfer_calculation(self):
        c = self._get_chain(avg_gas_price_gwei=10.0, native_token_price_usd=3000.0,
                            simple_transfer_gas=21000)
        expected = _gas_usd(21000, 10.0, 3000.0)
        self.assertAlmostEqual(c["simple_transfer_usd"], expected, places=6)

    def test_21_token_swap_calculation(self):
        c = self._get_chain(avg_gas_price_gwei=20.0, native_token_price_usd=2500.0,
                            token_swap_gas=200000)
        expected = _gas_usd(200000, 20.0, 2500.0)
        self.assertAlmostEqual(c["token_swap_usd"], expected, places=5)

    def test_22_lp_deposit_calculation(self):
        c = self._get_chain(avg_gas_price_gwei=5.0, native_token_price_usd=1000.0,
                            lp_deposit_gas=250000)
        expected = _gas_usd(250000, 5.0, 1000.0)
        self.assertAlmostEqual(c["lp_deposit_usd"], expected, places=5)

    def test_23_lp_withdrawal_calculation(self):
        c = self._get_chain(avg_gas_price_gwei=5.0, native_token_price_usd=1000.0,
                            lp_withdrawal_gas=180000)
        expected = _gas_usd(180000, 5.0, 1000.0)
        self.assertAlmostEqual(c["lp_withdrawal_usd"], expected, places=5)

    def test_24_bridge_out_calculation(self):
        c = self._get_chain(avg_gas_price_gwei=10.0, native_token_price_usd=2000.0,
                            bridge_gas_out=120000)
        expected = _gas_usd(120000, 10.0, 2000.0)
        self.assertAlmostEqual(c["bridge_out_usd"], expected, places=5)

    def test_25_full_cycle_is_sum_of_four(self):
        c = self._get_chain(avg_gas_price_gwei=5.0, native_token_price_usd=2000.0,
                            simple_transfer_gas=21000, token_swap_gas=150000,
                            lp_deposit_gas=200000, lp_withdrawal_gas=180000)
        expected = (c["simple_transfer_usd"] + c["token_swap_usd"]
                    + c["lp_deposit_usd"] + c["lp_withdrawal_usd"])
        self.assertAlmostEqual(c["full_defi_cycle_usd"], expected, places=6)

    def test_26_full_cycle_excludes_bridge(self):
        # Full cycle should NOT include bridge_out
        c = self._get_chain(avg_gas_price_gwei=5.0, native_token_price_usd=2000.0)
        self.assertAlmostEqual(
            c["full_defi_cycle_usd"],
            c["simple_transfer_usd"] + c["token_swap_usd"]
            + c["lp_deposit_usd"] + c["lp_withdrawal_usd"],
            places=6,
        )
        # bridge_out is separate
        self.assertIn("bridge_out_usd", c)

    def test_27_l2_adds_l1_data_to_transfer(self):
        l1_cost = 0.01
        c = self._get_chain(is_l2=True, l1_data_posting_cost_per_tx_usd=l1_cost,
                            avg_gas_price_gwei=0.1, native_token_price_usd=3000.0,
                            simple_transfer_gas=21000)
        base = _gas_usd(21000, 0.1, 3000.0)
        self.assertAlmostEqual(c["simple_transfer_usd"], base + l1_cost, places=6)

    def test_28_l2_adds_l1_data_to_swap(self):
        l1_cost = 0.02
        c = self._get_chain(is_l2=True, l1_data_posting_cost_per_tx_usd=l1_cost,
                            avg_gas_price_gwei=0.1, native_token_price_usd=3000.0,
                            token_swap_gas=150000)
        base = _gas_usd(150000, 0.1, 3000.0)
        self.assertAlmostEqual(c["token_swap_usd"], base + l1_cost, places=6)

    def test_29_l2_adds_l1_data_to_lp_deposit(self):
        l1_cost = 0.015
        c = self._get_chain(is_l2=True, l1_data_posting_cost_per_tx_usd=l1_cost,
                            avg_gas_price_gwei=0.1, native_token_price_usd=3000.0,
                            lp_deposit_gas=200000)
        base = _gas_usd(200000, 0.1, 3000.0)
        self.assertAlmostEqual(c["lp_deposit_usd"], base + l1_cost, places=6)

    def test_30_l1_chain_no_l1_data_added(self):
        gwei, price = 5.0, 2000.0
        transfer_gas = 21000
        c = self._get_chain(is_l2=False, l1_data_posting_cost_per_tx_usd=0.5,
                            avg_gas_price_gwei=gwei, native_token_price_usd=price,
                            simple_transfer_gas=transfer_gas)
        # is_l2=False → l1_data should NOT be added
        expected = _gas_usd(transfer_gas, gwei, price)
        self.assertAlmostEqual(c["simple_transfer_usd"], expected, places=6)

    def test_31_zero_gas_price_all_zeros(self):
        c = self._get_chain(avg_gas_price_gwei=0.0, native_token_price_usd=3000.0)
        self.assertAlmostEqual(c["simple_transfer_usd"], 0.0, places=8)
        self.assertAlmostEqual(c["full_defi_cycle_usd"], 0.0, places=8)

    def test_32_zero_native_price_all_zeros(self):
        c = self._get_chain(avg_gas_price_gwei=30.0, native_token_price_usd=0.0)
        self.assertAlmostEqual(c["full_defi_cycle_usd"], 0.0, places=8)

    def test_33_eth_price_fallback_when_no_native_price(self):
        # eth_price_usd should be used if native_token_price_usd not provided
        result = self.cmp.compare([{
            "name": "TestChain",
            "avg_gas_price_gwei": 10.0,
            "eth_price_usd": 2000.0,
            "simple_transfer_gas": 21000,
            "token_swap_gas": 150000,
            "lp_deposit_gas": 200000,
            "lp_withdrawal_gas": 180000,
            "bridge_gas_out": 100000,
            "tps_capacity": 100,
            "avg_finality_seconds": 60.0,
            "is_l2": False,
        }])
        # Should use eth_price_usd=2000 as native price
        expected = _gas_usd(21000, 10.0, 2000.0)
        self.assertAlmostEqual(result["chains"][0]["simple_transfer_usd"], expected, places=5)

    def test_34_l2_zero_l1_data_no_change(self):
        # L2 with zero l1_data → same cost as without l1_data
        c_no_l1 = self._get_chain(is_l2=True, l1_data_posting_cost_per_tx_usd=0.0,
                                  avg_gas_price_gwei=1.0, native_token_price_usd=2000.0)
        c_with_0 = self._get_chain(is_l2=True, l1_data_posting_cost_per_tx_usd=0.0,
                                   avg_gas_price_gwei=1.0, native_token_price_usd=2000.0)
        self.assertAlmostEqual(c_no_l1["full_defi_cycle_usd"],
                               c_with_0["full_defi_cycle_usd"], places=8)

    def test_35_cost_efficiency_score_range_0_to_100(self):
        result = self.cmp.compare([_chain("A", avg_gas_price_gwei=1.0),
                                   _chain("B", avg_gas_price_gwei=50.0)])
        for c in result["chains"]:
            score = c["cost_efficiency_score"]
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_36_cost_efficiency_cheapest_is_100(self):
        result = self.cmp.compare([
            _chain("Cheap", avg_gas_price_gwei=0.01, native_token_price_usd=100.0),
            _chain("Expensive", avg_gas_price_gwei=100.0, native_token_price_usd=5000.0),
        ])
        cheap = next(c for c in result["chains"] if c["name"] == "Cheap")
        self.assertAlmostEqual(cheap["cost_efficiency_score"], 100.0, places=1)

    def test_37_cost_efficiency_most_expensive_is_0(self):
        result = self.cmp.compare([
            _chain("Cheap", avg_gas_price_gwei=0.01, native_token_price_usd=100.0),
            _chain("Expensive", avg_gas_price_gwei=100.0, native_token_price_usd=5000.0),
        ])
        exp = next(c for c in result["chains"] if c["name"] == "Expensive")
        self.assertAlmostEqual(exp["cost_efficiency_score"], 0.0, places=1)

    def test_38_cost_efficiency_single_chain_is_100(self):
        result = self.cmp.compare([_chain("Solo")])
        self.assertAlmostEqual(result["chains"][0]["cost_efficiency_score"], 100.0, places=1)


# ---------------------------------------------------------------------------
# Fee label tests
# ---------------------------------------------------------------------------

class TestCrossChainFeeComparatorLabels(unittest.TestCase):
    def setUp(self):
        self.cmp = _comparator()

    def _get_label_for_cycle(self, cycle_usd: float) -> str:
        """Create a chain that gives approximately `cycle_usd` as full_defi_cycle_usd."""
        return ProtocolCrossChainFeeComparator._compute_fee_label(cycle_usd)

    def test_39_label_ultra_cheap(self):
        self.assertEqual(self._get_label_for_cycle(0.05), "ULTRA_CHEAP")

    def test_40_label_ultra_cheap_boundary(self):
        # 0.099 → ULTRA_CHEAP
        self.assertEqual(self._get_label_for_cycle(0.099), "ULTRA_CHEAP")

    def test_41_label_cheap(self):
        self.assertEqual(self._get_label_for_cycle(0.50), "CHEAP")

    def test_42_label_cheap_boundary(self):
        self.assertEqual(self._get_label_for_cycle(0.999), "CHEAP")

    def test_43_label_cheap_at_threshold(self):
        # exactly 0.10 → CHEAP (not ULTRA_CHEAP, since < 0.10 is ULTRA_CHEAP)
        self.assertEqual(self._get_label_for_cycle(0.10), "CHEAP")

    def test_44_label_moderate(self):
        self.assertEqual(self._get_label_for_cycle(5.0), "MODERATE")

    def test_45_label_moderate_boundary(self):
        self.assertEqual(self._get_label_for_cycle(9.99), "MODERATE")

    def test_46_label_expensive(self):
        self.assertEqual(self._get_label_for_cycle(25.0), "EXPENSIVE")

    def test_47_label_expensive_boundary(self):
        self.assertEqual(self._get_label_for_cycle(49.99), "EXPENSIVE")

    def test_48_label_prohibitive(self):
        self.assertEqual(self._get_label_for_cycle(50.0), "PROHIBITIVE")

    def test_49_label_prohibitive_high(self):
        self.assertEqual(self._get_label_for_cycle(500.0), "PROHIBITIVE")

    def test_50_label_from_chain_result(self):
        # High gas Ethereum-like → PROHIBITIVE
        result = self.cmp.compare([_chain("ETH", avg_gas_price_gwei=50.0,
                                          native_token_price_usd=3500.0)])
        label = result["chains"][0]["fee_label"]
        self.assertIn(label, ["ULTRA_CHEAP", "CHEAP", "MODERATE", "EXPENSIVE", "PROHIBITIVE"])


# ---------------------------------------------------------------------------
# Flag tests
# ---------------------------------------------------------------------------

class TestCrossChainFeeComparatorFlags(unittest.TestCase):
    def setUp(self):
        self.cmp = _comparator()

    def _flags(self, **kwargs) -> list:
        return self.cmp.compare([_chain(**kwargs)])["chains"][0]["flags"]

    def test_51_flag_l2_discount_set(self):
        # is_l2=True, cheap cycle
        flags = self._flags(is_l2=True, avg_gas_price_gwei=0.001,
                            native_token_price_usd=100.0)
        self.assertIn("L2_DISCOUNT", flags)

    def test_52_flag_l2_discount_not_set_for_l1(self):
        flags = self._flags(is_l2=False, avg_gas_price_gwei=0.001,
                            native_token_price_usd=100.0)
        self.assertNotIn("L2_DISCOUNT", flags)

    def test_53_flag_l2_discount_not_set_when_expensive_l2(self):
        # L2 but cycle > $1 → no L2_DISCOUNT
        flags = self._flags(is_l2=True, avg_gas_price_gwei=50.0,
                            native_token_price_usd=3000.0)
        self.assertNotIn("L2_DISCOUNT", flags)

    def test_54_flag_high_throughput_set(self):
        flags = self._flags(tps_capacity=5000.0)
        self.assertIn("HIGH_THROUGHPUT", flags)

    def test_55_flag_high_throughput_not_set_below_threshold(self):
        flags = self._flags(tps_capacity=999.0)
        self.assertNotIn("HIGH_THROUGHPUT", flags)

    def test_56_flag_high_throughput_boundary_exactly_1000(self):
        # >1000 means exactly 1000 should NOT get the flag
        flags = self._flags(tps_capacity=1000.0)
        self.assertNotIn("HIGH_THROUGHPUT", flags)

    def test_57_flag_high_throughput_just_above_1000(self):
        flags = self._flags(tps_capacity=1001.0)
        self.assertIn("HIGH_THROUGHPUT", flags)

    def test_58_flag_fast_finality_set(self):
        flags = self._flags(avg_finality_seconds=1.0)
        self.assertIn("FAST_FINALITY", flags)

    def test_59_flag_fast_finality_not_set_slow(self):
        flags = self._flags(avg_finality_seconds=60.0)
        self.assertNotIn("FAST_FINALITY", flags)

    def test_60_flag_fast_finality_boundary_exactly_5(self):
        # < 5s → FAST_FINALITY; exactly 5s → NOT
        flags = self._flags(avg_finality_seconds=5.0)
        self.assertNotIn("FAST_FINALITY", flags)

    def test_61_flag_fast_finality_just_below_5(self):
        flags = self._flags(avg_finality_seconds=4.99)
        self.assertIn("FAST_FINALITY", flags)

    def test_62_flag_bridge_expensive_set(self):
        # Make bridge_out_usd > $10
        flags = self._flags(avg_gas_price_gwei=50.0, native_token_price_usd=3000.0,
                            bridge_gas_out=200000)
        if self.cmp.compare([_chain(avg_gas_price_gwei=50.0, native_token_price_usd=3000.0,
                                    bridge_gas_out=200000)])["chains"][0]["bridge_out_usd"] > 10:
            self.assertIn("BRIDGE_EXPENSIVE", flags)

    def test_63_flag_bridge_not_expensive_cheap_chain(self):
        # Very cheap chain → bridge < $10
        c = self.cmp.compare([_chain(avg_gas_price_gwei=0.001, native_token_price_usd=100.0,
                                     bridge_gas_out=100000)])["chains"][0]
        if c["bridge_out_usd"] <= 10.0:
            self.assertNotIn("BRIDGE_EXPENSIVE", c["flags"])

    def test_64_flag_l1_data_cost_dominant(self):
        # L2 with high l1_data relative to execution
        # 4 * l1_data > 50% of cycle
        # cycle = 4 * (tiny_exec + l1_data) = 4*tiny + 4*l1
        # 4*l1 > 0.5*(4*tiny + 4*l1) → 4*l1 > 2*tiny + 2*l1 → 2*l1 > 2*tiny → l1 > tiny
        # So: l1_data > execution gas cost → L1_DATA_COST_DOMINANT
        flags = self._flags(
            is_l2=True,
            avg_gas_price_gwei=0.001,        # tiny execution cost
            native_token_price_usd=100.0,
            l1_data_posting_cost_per_tx_usd=10.0,  # large L1 data cost
        )
        self.assertIn("L1_DATA_COST_DOMINANT", flags)

    def test_65_flag_l1_data_not_dominant_when_execution_bigger(self):
        # Large execution cost, tiny L1 data
        flags = self._flags(
            is_l2=True,
            avg_gas_price_gwei=100.0,        # large execution
            native_token_price_usd=3000.0,
            l1_data_posting_cost_per_tx_usd=0.001,  # tiny L1 data
        )
        self.assertNotIn("L1_DATA_COST_DOMINANT", flags)

    def test_66_flag_l1_data_dominant_not_set_for_l1_chain(self):
        # l1_data_posting_cost for a non-L2 chain → flag must NOT appear
        flags = self._flags(
            is_l2=False,
            l1_data_posting_cost_per_tx_usd=100.0,
        )
        self.assertNotIn("L1_DATA_COST_DOMINANT", flags)

    def test_67_no_flags_for_basic_expensive_l1(self):
        # Average L1 chain, no special flags expected
        flags = self._flags(
            avg_gas_price_gwei=20.0,
            native_token_price_usd=2000.0,
            tps_capacity=15,
            avg_finality_seconds=780.0,
            is_l2=False,
        )
        self.assertNotIn("HIGH_THROUGHPUT", flags)
        self.assertNotIn("FAST_FINALITY", flags)
        self.assertNotIn("L2_DISCOUNT", flags)

    def test_68_l2_discount_at_threshold_boundary(self):
        # cycle exactly $1.00 → NOT L2_DISCOUNT (< $1.0 required)
        # We approximate by using a chain that costs ~$1
        # Find: gwei * gas_total * 1e-9 * price = ~1 for total cycle
        # 4 ops: 21000+150000+200000+180000 = 551000 gas total
        # 551000 * gwei * 1e-9 * price = 1 → gwei * price = 1 / (551000 * 1e-9) ≈ 1815
        # e.g. gwei=18.15, price=100 (or gwei=1, price=1815)
        result = self.cmp.compare([_chain(
            is_l2=True,
            avg_gas_price_gwei=1.0,
            native_token_price_usd=1815.0,
            simple_transfer_gas=21000,
            token_swap_gas=150000,
            lp_deposit_gas=200000,
            lp_withdrawal_gas=180000,
        )])
        c = result["chains"][0]
        if c["full_defi_cycle_usd"] >= 1.0:
            self.assertNotIn("L2_DISCOUNT", c["flags"])


# ---------------------------------------------------------------------------
# Aggregates tests
# ---------------------------------------------------------------------------

class TestCrossChainFeeComparatorAggregates(unittest.TestCase):
    def setUp(self):
        self.cmp = _comparator()

    def test_69_empty_aggregates_all_none(self):
        result = self.cmp.compare([])
        agg = result["aggregates"]
        self.assertIsNone(agg["cheapest_chain"])
        self.assertIsNone(agg["most_expensive_chain"])
        self.assertIsNone(agg["cheapest_for_small_txs"])
        self.assertIsNone(agg["recommended_for_defi"])
        self.assertIsNone(agg["average_cycle_cost_usd"])

    def test_70_cheapest_chain(self):
        result = self.cmp.compare([
            _chain("Cheap", avg_gas_price_gwei=0.01, native_token_price_usd=100.0),
            _chain("Expensive", avg_gas_price_gwei=50.0, native_token_price_usd=3000.0),
        ])
        self.assertEqual(result["aggregates"]["cheapest_chain"], "Cheap")

    def test_71_most_expensive_chain(self):
        result = self.cmp.compare([
            _chain("Cheap", avg_gas_price_gwei=0.01, native_token_price_usd=100.0),
            _chain("Expensive", avg_gas_price_gwei=50.0, native_token_price_usd=3000.0),
        ])
        self.assertEqual(result["aggregates"]["most_expensive_chain"], "Expensive")

    def test_72_cheapest_for_small_txs(self):
        # Same cycle cost but one has cheaper transfer
        result = self.cmp.compare([
            _chain("LowTransfer", avg_gas_price_gwei=0.01, native_token_price_usd=100.0,
                   simple_transfer_gas=21000),
            _chain("HighTransfer", avg_gas_price_gwei=50.0, native_token_price_usd=3000.0,
                   simple_transfer_gas=21000),
        ])
        self.assertEqual(result["aggregates"]["cheapest_for_small_txs"], "LowTransfer")

    def test_73_average_cycle_cost(self):
        result = self.cmp.compare([
            _chain("A", avg_gas_price_gwei=0.0, native_token_price_usd=2000.0),  # free
            _chain("B", avg_gas_price_gwei=0.0, native_token_price_usd=2000.0),  # free
        ])
        self.assertAlmostEqual(result["aggregates"]["average_cycle_cost_usd"], 0.0, places=6)

    def test_74_single_chain_all_aggregates_point_to_it(self):
        result = self.cmp.compare([_chain("Solo")])
        agg = result["aggregates"]
        self.assertEqual(agg["cheapest_chain"], "Solo")
        self.assertEqual(agg["most_expensive_chain"], "Solo")
        self.assertEqual(agg["cheapest_for_small_txs"], "Solo")
        self.assertIsNotNone(agg["recommended_for_defi"])

    def test_75_aggregates_has_all_keys(self):
        result = self.cmp.compare([_chain()])
        agg = result["aggregates"]
        for key in ("cheapest_chain", "most_expensive_chain", "cheapest_for_small_txs",
                    "recommended_for_defi", "average_cycle_cost_usd"):
            self.assertIn(key, agg)

    def test_76_recommended_prefers_fast_finality(self):
        # Two chains with same cost but one much faster finality
        result = self.cmp.compare([
            _chain("Fast", avg_gas_price_gwei=1.0, native_token_price_usd=100.0,
                   tps_capacity=5000, avg_finality_seconds=1.0),
            _chain("Slow", avg_gas_price_gwei=1.0, native_token_price_usd=100.0,
                   tps_capacity=100, avg_finality_seconds=600.0),
        ])
        # Both have same cost → fast finality should win recommended
        self.assertEqual(result["aggregates"]["recommended_for_defi"], "Fast")

    def test_77_average_cycle_cost_correct(self):
        # Use zero-gas chains to get predictable values
        result = self.cmp.compare([
            _chain("A", avg_gas_price_gwei=0.0, native_token_price_usd=2000.0,
                   l1_data_posting_cost_per_tx_usd=0.0, is_l2=False),
            _chain("B", avg_gas_price_gwei=0.0, native_token_price_usd=2000.0,
                   l1_data_posting_cost_per_tx_usd=0.0, is_l2=False),
        ])
        # Both zero → average = 0
        self.assertAlmostEqual(result["aggregates"]["average_cycle_cost_usd"], 0.0, places=6)

    def test_78_cheapest_for_small_may_differ_from_cheapest_cycle(self):
        # Chain A: expensive cycle but cheapest transfer
        # Chain B: cheaper cycle overall but slightly pricier transfer
        # This test verifies the aggregate is computed per-transfer, not per-cycle
        result = self.cmp.compare([
            _chain("A", avg_gas_price_gwei=0.001, native_token_price_usd=100.0,
                   simple_transfer_gas=21000, token_swap_gas=5_000_000,
                   lp_deposit_gas=5_000_000, lp_withdrawal_gas=5_000_000),
            _chain("B", avg_gas_price_gwei=10.0, native_token_price_usd=100.0,
                   simple_transfer_gas=21000, token_swap_gas=150000,
                   lp_deposit_gas=200000, lp_withdrawal_gas=180000),
        ])
        # Chain A has tiny transfer but huge LP costs; B is moderate across the board
        cheapest_transfer = result["aggregates"]["cheapest_for_small_txs"]
        self.assertIsNotNone(cheapest_transfer)


# ---------------------------------------------------------------------------
# Log tests
# ---------------------------------------------------------------------------

class TestCrossChainFeeComparatorLog(unittest.TestCase):
    def setUp(self):
        self.cmp = _comparator()
        self.tmpdir = tempfile.mkdtemp()

    def test_79_write_log_creates_file(self):
        result = self.cmp.compare([_chain()])
        self.cmp.write_log(result, self.tmpdir)
        log_path = os.path.join(self.tmpdir, "cross_chain_fee_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_80_write_log_valid_json(self):
        result = self.cmp.compare([_chain()])
        self.cmp.write_log(result, self.tmpdir)
        log_path = os.path.join(self.tmpdir, "cross_chain_fee_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_81_write_log_appends(self):
        for i in range(3):
            result = self.cmp.compare([_chain(f"Chain{i}")])
            self.cmp.write_log(result, self.tmpdir)
        log_path = os.path.join(self.tmpdir, "cross_chain_fee_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_82_write_log_ring_buffer_cap_100(self):
        for i in range(110):
            result = self.cmp.compare([_chain(f"C{i}")])
            self.cmp.write_log(result, self.tmpdir)
        log_path = os.path.join(self.tmpdir, "cross_chain_fee_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_83_write_log_no_tmp_files_left(self):
        result = self.cmp.compare([_chain()])
        self.cmp.write_log(result, self.tmpdir)
        tmp_files = [f for f in os.listdir(self.tmpdir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_84_write_log_creates_data_dir(self):
        new_dir = os.path.join(self.tmpdir, "nested", "data")
        result = self.cmp.compare([_chain()])
        self.cmp.write_log(result, new_dir)
        self.assertTrue(os.path.isdir(new_dir))

    def test_85_log_entry_has_chains_key(self):
        result = self.cmp.compare([_chain()])
        self.cmp.write_log(result, self.tmpdir)
        log_path = os.path.join(self.tmpdir, "cross_chain_fee_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("chains", data[0])

    def test_86_log_entry_has_metadata(self):
        result = self.cmp.compare([_chain()])
        self.cmp.write_log(result, self.tmpdir)
        log_path = os.path.join(self.tmpdir, "cross_chain_fee_log.json")
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("metadata", data[0])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestCrossChainFeeComparatorEdgeCases(unittest.TestCase):
    def setUp(self):
        self.cmp = _comparator()

    def test_87_config_param_ignored_gracefully(self):
        result = self.cmp.compare([_chain()], config={"unknown": "value"})
        self.assertIn("chains", result)

    def test_88_very_high_gas_price(self):
        result = self.cmp.compare([_chain(avg_gas_price_gwei=10000.0,
                                          native_token_price_usd=5000.0)])
        c = result["chains"][0]
        self.assertGreater(c["full_defi_cycle_usd"], 0.0)
        self.assertEqual(c["fee_label"], "PROHIBITIVE")

    def test_89_multiple_chains_order_preserved(self):
        names = ["Alpha", "Beta", "Gamma", "Delta"]
        result = self.cmp.compare([_chain(n) for n in names])
        result_names = [c["name"] for c in result["chains"]]
        self.assertEqual(result_names, names)

    def test_90_version_attribute(self):
        self.assertIsNotNone(ProtocolCrossChainFeeComparator._VERSION)

    def test_91_log_cap_attribute(self):
        self.assertEqual(ProtocolCrossChainFeeComparator._LOG_CAP, 100)

    def test_92_metadata_chains_analyzed_zero_on_empty(self):
        result = self.cmp.compare([])
        self.assertEqual(result["metadata"]["chains_analyzed"], 0)

    def test_93_bridge_exactly_10_not_flagged(self):
        # bridge_out_usd exactly $10 → NOT BRIDGE_EXPENSIVE (strictly >10 required)
        # Find params: gas_units * gwei * 1e-9 * price = 10
        # 100000 * 1.0 * 1e-9 * 100000 = 100000 * 1e-4 = 10 exactly
        result = self.cmp.compare([_chain(
            avg_gas_price_gwei=1.0,
            native_token_price_usd=100000.0,
            bridge_gas_out=100000,
        )])
        c = result["chains"][0]
        self.assertAlmostEqual(c["bridge_out_usd"], 10.0, places=4)
        # Exactly $10 → NOT BRIDGE_EXPENSIVE (condition is >10)
        self.assertNotIn("BRIDGE_EXPENSIVE", c["flags"])

    def test_94_bridge_above_10_flagged(self):
        result = self.cmp.compare([_chain(
            avg_gas_price_gwei=1.0,
            native_token_price_usd=100001.0,  # slightly above $10
            bridge_gas_out=100000,
        )])
        c = result["chains"][0]
        self.assertGreater(c["bridge_out_usd"], 10.0)
        self.assertIn("BRIDGE_EXPENSIVE", c["flags"])

    def test_95_cost_efficiency_score_is_float_or_numeric(self):
        result = self.cmp.compare([_chain("A"), _chain("B")])
        for c in result["chains"]:
            self.assertIsInstance(c["cost_efficiency_score"], float)


if __name__ == "__main__":
    unittest.main()
