"""
Tests for MP-995: ProtocolDeFiGasCostOptimizer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_gas_cost_optimizer
"""

import json
import os
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.protocol_defi_gas_cost_optimizer import (
    ProtocolDeFiGasCostOptimizer,
)


def _make_op(
    name="TestSwap",
    op_type="swap",
    protocol="Uniswap",
    chain="ethereum",
    estimated_gas_units=100_000,
    current_gas_price_gwei=20.0,
    eth_price_usd=2_000.0,
    transaction_value_usd=10_000.0,
    frequency_per_month=4.0,
    can_batch=False,
    can_delay=False,
    typical_cheap_gas_gwei=10.0,
    congestion_factor=1.0,
):
    return {
        "name": name,
        "op_type": op_type,
        "protocol": protocol,
        "chain": chain,
        "estimated_gas_units": estimated_gas_units,
        "current_gas_price_gwei": current_gas_price_gwei,
        "eth_price_usd": eth_price_usd,
        "transaction_value_usd": transaction_value_usd,
        "frequency_per_month": frequency_per_month,
        "can_batch": can_batch,
        "can_delay": can_delay,
        "typical_cheap_gas_gwei": typical_cheap_gas_gwei,
        "congestion_factor": congestion_factor,
    }


class TestGasCostUsd(unittest.TestCase):
    def setUp(self):
        self.opt = ProtocolDeFiGasCostOptimizer()

    def test_basic_calculation(self):
        # 100000 * 20 * 2000 / 1e9 = 4.0 USD
        op = _make_op(estimated_gas_units=100_000, current_gas_price_gwei=20.0, eth_price_usd=2_000.0)
        self.assertAlmostEqual(self.opt._gas_cost_usd(op), 4.0, places=5)

    def test_zero_units(self):
        op = _make_op(estimated_gas_units=0)
        self.assertEqual(self.opt._gas_cost_usd(op), 0.0)

    def test_zero_gas_price(self):
        op = _make_op(current_gas_price_gwei=0.0)
        self.assertEqual(self.opt._gas_cost_usd(op), 0.0)

    def test_l2_cheap_gas(self):
        # 100000 * 0.1 * 2000 / 1e9 = 0.02 USD
        op = _make_op(estimated_gas_units=100_000, current_gas_price_gwei=0.1, eth_price_usd=2_000.0)
        self.assertAlmostEqual(self.opt._gas_cost_usd(op), 0.02, places=5)

    def test_high_gas_price(self):
        # 200000 * 100 * 3000 / 1e9 = 60.0 USD
        op = _make_op(estimated_gas_units=200_000, current_gas_price_gwei=100.0, eth_price_usd=3_000.0)
        self.assertAlmostEqual(self.opt._gas_cost_usd(op), 60.0, places=4)


class TestGasCostBps(unittest.TestCase):
    def setUp(self):
        self.opt = ProtocolDeFiGasCostOptimizer()

    def test_basic_bps(self):
        # $4 gas on $10000 tx = 4/10000*10000 = 4 bps
        self.assertAlmostEqual(self.opt._gas_cost_bps(4.0, 10_000.0), 4.0, places=4)

    def test_zero_tx_value(self):
        result = self.opt._gas_cost_bps(4.0, 0.0)
        self.assertGreater(result, 1000.0)  # sentinel value

    def test_100_bps(self):
        # $10 gas on $1000 tx = 100 bps
        self.assertAlmostEqual(self.opt._gas_cost_bps(10.0, 1_000.0), 100.0, places=4)

    def test_low_bps_l2(self):
        # $0.02 gas on $1000 tx = 0.2 bps
        self.assertAlmostEqual(self.opt._gas_cost_bps(0.02, 1_000.0), 0.2, places=4)


class TestMonthlyGasCost(unittest.TestCase):
    def setUp(self):
        self.opt = ProtocolDeFiGasCostOptimizer()

    def test_monthly_calculation(self):
        # $4 gas * 4 times/month = $16/month
        self.assertAlmostEqual(self.opt._monthly_gas_cost_usd(4.0, 4.0), 16.0, places=4)

    def test_zero_frequency(self):
        self.assertAlmostEqual(self.opt._monthly_gas_cost_usd(10.0, 0.0), 0.0, places=4)

    def test_once_per_month(self):
        self.assertAlmostEqual(self.opt._monthly_gas_cost_usd(25.0, 1.0), 25.0, places=4)

    def test_negative_frequency_clamped(self):
        result = self.opt._monthly_gas_cost_usd(10.0, -1.0)
        self.assertAlmostEqual(result, 0.0, places=4)


class TestBatchSavings(unittest.TestCase):
    def setUp(self):
        self.opt = ProtocolDeFiGasCostOptimizer()

    def test_can_batch_true(self):
        op = _make_op(can_batch=True, frequency_per_month=10.0)
        # $4 gas, 10/month, 40% reduction = $4 * 0.4 * 10 = $16
        savings = self.opt._potential_savings_batch_usd(op, 4.0, 10.0)
        self.assertAlmostEqual(savings, 16.0, places=4)

    def test_can_batch_false(self):
        op = _make_op(can_batch=False)
        savings = self.opt._potential_savings_batch_usd(op, 4.0, 10.0)
        self.assertEqual(savings, 0.0)

    def test_batch_zero_frequency(self):
        op = _make_op(can_batch=True)
        savings = self.opt._potential_savings_batch_usd(op, 4.0, 0.0)
        self.assertEqual(savings, 0.0)


class TestTimingSavings(unittest.TestCase):
    def setUp(self):
        self.opt = ProtocolDeFiGasCostOptimizer()

    def test_can_delay_true_savings(self):
        # current=20 gwei, cheap=10 gwei → 50% savings
        op = _make_op(can_delay=True, current_gas_price_gwei=20.0, typical_cheap_gas_gwei=10.0)
        savings = self.opt._potential_savings_timing_usd(op, 4.0, 4.0)
        # savings_ratio = (20-10)/20 = 0.5; 0.5 * 4 * 4 = 8
        self.assertAlmostEqual(savings, 8.0, places=4)

    def test_can_delay_false(self):
        op = _make_op(can_delay=False)
        savings = self.opt._potential_savings_timing_usd(op, 4.0, 4.0)
        self.assertEqual(savings, 0.0)

    def test_no_savings_when_already_cheap(self):
        # typical >= current → no savings
        op = _make_op(can_delay=True, current_gas_price_gwei=10.0, typical_cheap_gas_gwei=15.0)
        savings = self.opt._potential_savings_timing_usd(op, 4.0, 4.0)
        self.assertEqual(savings, 0.0)

    def test_timing_zero_current_gas(self):
        op = _make_op(can_delay=True, current_gas_price_gwei=0.0, typical_cheap_gas_gwei=5.0)
        savings = self.opt._potential_savings_timing_usd(op, 4.0, 4.0)
        self.assertEqual(savings, 0.0)


class TestTotalSavingsPct(unittest.TestCase):
    def setUp(self):
        self.opt = ProtocolDeFiGasCostOptimizer()

    def test_basic_savings_pct(self):
        # $8 savings on $20 monthly = 40%
        pct = self.opt._total_potential_savings_pct(5.0, 3.0, 20.0)
        self.assertAlmostEqual(pct, 40.0, places=4)

    def test_zero_monthly_gas(self):
        pct = self.opt._total_potential_savings_pct(5.0, 3.0, 0.0)
        self.assertEqual(pct, 0.0)

    def test_savings_capped_at_100(self):
        pct = self.opt._total_potential_savings_pct(1000.0, 1000.0, 10.0)
        self.assertLessEqual(pct, 100.0)


class TestCostEfficiencyScore(unittest.TestCase):
    def setUp(self):
        self.opt = ProtocolDeFiGasCostOptimizer()

    def test_zero_bps_perfect_score(self):
        self.assertAlmostEqual(self.opt._cost_efficiency_score(0.0), 100.0, places=2)

    def test_100_bps_zero_score(self):
        self.assertAlmostEqual(self.opt._cost_efficiency_score(100.0), 0.0, places=2)

    def test_50_bps_score_50(self):
        self.assertAlmostEqual(self.opt._cost_efficiency_score(50.0), 50.0, places=2)

    def test_score_clamped_to_zero(self):
        self.assertEqual(self.opt._cost_efficiency_score(200.0), 0.0)

    def test_sentinel_bps_zero_score(self):
        self.assertEqual(self.opt._cost_efficiency_score(9999.0), 0.0)

    def test_score_bounded_0_100(self):
        for bps in [0, 5, 20, 50, 100, 200, 9999]:
            s = self.opt._cost_efficiency_score(float(bps))
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)


class TestEfficiencyLabel(unittest.TestCase):
    def setUp(self):
        self.opt = ProtocolDeFiGasCostOptimizer()

    def test_ultra_efficient_l2(self):
        label = self.opt._efficiency_label(3.0, "arbitrum", 5.0)
        self.assertEqual(label, "ULTRA_EFFICIENT")

    def test_ultra_efficient_l2_base(self):
        label = self.opt._efficiency_label(2.0, "base", 2.0)
        self.assertEqual(label, "ULTRA_EFFICIENT")

    def test_not_ultra_efficient_ethereum(self):
        # bps < 5 but ethereum → not ULTRA_EFFICIENT
        label = self.opt._efficiency_label(3.0, "ethereum", 5.0)
        self.assertEqual(label, "EFFICIENT")

    def test_efficient(self):
        label = self.opt._efficiency_label(15.0, "ethereum", 10.0)
        self.assertEqual(label, "EFFICIENT")

    def test_acceptable(self):
        label = self.opt._efficiency_label(30.0, "ethereum", 50.0)
        self.assertEqual(label, "ACCEPTABLE")

    def test_expensive(self):
        label = self.opt._efficiency_label(75.0, "ethereum", 200.0)
        self.assertEqual(label, "EXPENSIVE")

    def test_cost_prohibitive_by_bps(self):
        label = self.opt._efficiency_label(100.0, "ethereum", 50.0)
        self.assertEqual(label, "COST_PROHIBITIVE")

    def test_cost_prohibitive_by_monthly_cost(self):
        label = self.opt._efficiency_label(10.0, "arbitrum", 1001.0)
        self.assertEqual(label, "COST_PROHIBITIVE")

    def test_ultra_efficient_optimism(self):
        label = self.opt._efficiency_label(4.9, "optimism", 10.0)
        self.assertEqual(label, "ULTRA_EFFICIENT")

    def test_ultra_efficient_polygon(self):
        label = self.opt._efficiency_label(1.0, "polygon", 2.0)
        self.assertEqual(label, "ULTRA_EFFICIENT")


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.opt = ProtocolDeFiGasCostOptimizer()

    def test_l2_migration_recommended(self):
        op = _make_op(chain="ethereum", can_batch=False, can_delay=False)
        # bps > 50: $10 gas on $1000 tx = 100 bps
        flags = self.opt._compute_flags(op, 100.0, 0.0, 0.0, 10.0, 50.0)
        self.assertIn("L2_MIGRATION_RECOMMENDED", flags)

    def test_no_l2_migration_on_l2(self):
        op = _make_op(chain="arbitrum")
        flags = self.opt._compute_flags(op, 100.0, 0.0, 0.0, 10.0, 50.0)
        self.assertNotIn("L2_MIGRATION_RECOMMENDED", flags)

    def test_batch_opportunity(self):
        op = _make_op(can_batch=True)
        flags = self.opt._compute_flags(op, 30.0, 60.0, 0.0, 10.0, 50.0)
        self.assertIn("BATCH_OPPORTUNITY", flags)

    def test_no_batch_when_savings_low(self):
        op = _make_op(can_batch=True)
        flags = self.opt._compute_flags(op, 30.0, 30.0, 0.0, 10.0, 50.0)
        self.assertNotIn("BATCH_OPPORTUNITY", flags)

    def test_no_batch_when_cant_batch(self):
        op = _make_op(can_batch=False)
        flags = self.opt._compute_flags(op, 30.0, 100.0, 0.0, 10.0, 50.0)
        self.assertNotIn("BATCH_OPPORTUNITY", flags)

    def test_timing_opportunity(self):
        op = _make_op(can_delay=True)
        flags = self.opt._compute_flags(op, 30.0, 0.0, 50.0, 10.0, 50.0)
        self.assertIn("TIMING_OPPORTUNITY", flags)

    def test_no_timing_when_savings_low(self):
        op = _make_op(can_delay=True)
        flags = self.opt._compute_flags(op, 30.0, 0.0, 20.0, 10.0, 50.0)
        self.assertNotIn("TIMING_OPPORTUNITY", flags)

    def test_harvest_not_worth_it(self):
        # gas_cost > 50% of tx_value: $60 gas on $100 harvest value
        op = _make_op(op_type="harvest", transaction_value_usd=100.0)
        flags = self.opt._compute_flags(op, 30.0, 0.0, 0.0, 60.0, 50.0)
        self.assertIn("HARVEST_NOT_WORTH_IT", flags)

    def test_harvest_worth_it(self):
        # gas_cost < 50% of tx_value: $10 gas on $1000 harvest
        op = _make_op(op_type="harvest", transaction_value_usd=1_000.0)
        flags = self.opt._compute_flags(op, 30.0, 0.0, 0.0, 10.0, 50.0)
        self.assertNotIn("HARVEST_NOT_WORTH_IT", flags)

    def test_harvest_not_worth_for_non_harvest(self):
        # Even if gas > 50% of tx, HARVEST_NOT_WORTH_IT only applies to harvest
        op = _make_op(op_type="swap", transaction_value_usd=100.0)
        flags = self.opt._compute_flags(op, 30.0, 0.0, 0.0, 60.0, 50.0)
        self.assertNotIn("HARVEST_NOT_WORTH_IT", flags)

    def test_high_frequency_cost(self):
        op = _make_op()
        flags = self.opt._compute_flags(op, 30.0, 0.0, 0.0, 10.0, 600.0)
        self.assertIn("HIGH_FREQUENCY_COST", flags)

    def test_no_high_frequency_low_cost(self):
        op = _make_op()
        flags = self.opt._compute_flags(op, 30.0, 0.0, 0.0, 10.0, 100.0)
        self.assertNotIn("HIGH_FREQUENCY_COST", flags)

    def test_no_flags_cheap_l2_op(self):
        op = _make_op(chain="arbitrum", can_batch=False, can_delay=False, op_type="swap")
        flags = self.opt._compute_flags(op, 3.0, 0.0, 0.0, 0.1, 2.0)
        self.assertEqual(flags, [])


class TestOptimizeReturnStructure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = Path(self.tmp.name) / "gas_optimization_log.json"
        self.opt = ProtocolDeFiGasCostOptimizer(data_file=self.data_file)

    def tearDown(self):
        self.tmp.cleanup()

    def test_return_keys(self):
        result = self.opt.optimize([_make_op()])
        self.assertIn("operations", result)
        self.assertIn("aggregates", result)
        self.assertIn("timestamp", result)
        self.assertIn("config", result)

    def test_empty_operations(self):
        result = self.opt.optimize([])
        self.assertEqual(result["operations"], [])
        self.assertEqual(result["aggregates"]["cost_prohibitive_count"], 0)

    def test_single_operation(self):
        result = self.opt.optimize([_make_op(name="Swap1")])
        self.assertEqual(len(result["operations"]), 1)
        self.assertEqual(result["operations"][0]["name"], "Swap1")

    def test_operation_result_keys(self):
        result = self.opt.optimize([_make_op()])
        op = result["operations"][0]
        required = [
            "name", "gas_cost_usd", "gas_cost_bps", "monthly_gas_cost_usd",
            "potential_savings_batch_usd", "potential_savings_timing_usd",
            "total_potential_savings_pct", "cost_efficiency_score",
            "efficiency_label", "flags",
        ]
        for key in required:
            self.assertIn(key, op)

    def test_aggregates_keys(self):
        result = self.opt.optimize([_make_op()])
        agg = result["aggregates"]
        required = [
            "most_efficient", "most_expensive", "total_monthly_gas_usd",
            "total_potential_savings_usd", "cost_prohibitive_count",
        ]
        for key in required:
            self.assertIn(key, agg)

    def test_timestamp_is_float(self):
        result = self.opt.optimize([_make_op()])
        self.assertIsInstance(result["timestamp"], float)

    def test_config_passthrough(self):
        cfg = {"mode": "analyze"}
        result = self.opt.optimize([_make_op()], config=cfg)
        self.assertEqual(result["config"]["mode"], "analyze")

    def test_no_config_default(self):
        result = self.opt.optimize([_make_op()])
        self.assertEqual(result["config"], {})


class TestOptimizeAggregates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = Path(self.tmp.name) / "gas_optimization_log.json"
        self.opt = ProtocolDeFiGasCostOptimizer(data_file=self.data_file)

    def tearDown(self):
        self.tmp.cleanup()

    def test_total_monthly_gas(self):
        # Op1: $4 * 4 = $16; Op2: $8 * 2 = $16; total = $32
        op1 = _make_op(name="A", estimated_gas_units=100_000, current_gas_price_gwei=20.0,
                       eth_price_usd=2_000.0, frequency_per_month=4.0)
        op2 = _make_op(name="B", estimated_gas_units=200_000, current_gas_price_gwei=20.0,
                       eth_price_usd=2_000.0, frequency_per_month=2.0)
        result = self.opt.optimize([op1, op2])
        self.assertAlmostEqual(result["aggregates"]["total_monthly_gas_usd"], 32.0, places=2)

    def test_most_efficient_by_score(self):
        cheap = _make_op(name="Cheap", estimated_gas_units=10, current_gas_price_gwei=1.0,
                         eth_price_usd=2000.0, transaction_value_usd=100_000.0)
        expensive = _make_op(name="Expensive", estimated_gas_units=500_000,
                             current_gas_price_gwei=100.0, eth_price_usd=3_000.0,
                             transaction_value_usd=1_000.0)
        result = self.opt.optimize([cheap, expensive])
        self.assertEqual(result["aggregates"]["most_efficient"], "Cheap")

    def test_most_expensive_by_bps(self):
        cheap = _make_op(name="Cheap", estimated_gas_units=10, current_gas_price_gwei=1.0,
                         eth_price_usd=2000.0, transaction_value_usd=100_000.0)
        expensive = _make_op(name="Expensive", estimated_gas_units=500_000,
                             current_gas_price_gwei=100.0, eth_price_usd=3_000.0,
                             transaction_value_usd=1_000.0)
        result = self.opt.optimize([cheap, expensive])
        self.assertEqual(result["aggregates"]["most_expensive"], "Expensive")

    def test_cost_prohibitive_count(self):
        prohibitive = _make_op(
            name="BigGas", estimated_gas_units=500_000, current_gas_price_gwei=100.0,
            eth_price_usd=3_000.0, transaction_value_usd=1_000.0, frequency_per_month=1.0
        )
        normal = _make_op(name="Normal")
        result = self.opt.optimize([prohibitive, normal])
        self.assertGreaterEqual(result["aggregates"]["cost_prohibitive_count"], 1)

    def test_total_savings_batching(self):
        op = _make_op(name="BatchOp", can_batch=True, frequency_per_month=10.0)
        # $4 gas, 10/mo, 40% batch savings = $16
        result = self.opt.optimize([op])
        self.assertAlmostEqual(
            result["aggregates"]["total_potential_savings_usd"], 16.0, places=2
        )


class TestEfficiencyLabelsInOptimize(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.opt = ProtocolDeFiGasCostOptimizer(
            data_file=Path(self.tmp.name) / "log.json"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_ultra_efficient_l2(self):
        op = _make_op(chain="arbitrum", estimated_gas_units=10_000,
                      current_gas_price_gwei=0.1, eth_price_usd=2_000.0,
                      transaction_value_usd=100_000.0)
        result = self.opt.optimize([op])
        self.assertEqual(result["operations"][0]["efficiency_label"], "ULTRA_EFFICIENT")

    def test_efficient_label(self):
        op = _make_op(chain="ethereum", estimated_gas_units=50_000,
                      current_gas_price_gwei=10.0, eth_price_usd=2_000.0,
                      transaction_value_usd=100_000.0)
        result = self.opt.optimize([op])
        self.assertEqual(result["operations"][0]["efficiency_label"], "EFFICIENT")

    def test_cost_prohibitive_high_bps(self):
        op = _make_op(chain="ethereum", estimated_gas_units=500_000,
                      current_gas_price_gwei=100.0, eth_price_usd=3_000.0,
                      transaction_value_usd=500.0, frequency_per_month=1.0)
        result = self.opt.optimize([op])
        self.assertEqual(result["operations"][0]["efficiency_label"], "COST_PROHIBITIVE")


class TestAtomicLogWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_file = Path(self.tmp.name) / "gas_optimization_log.json"
        self.opt = ProtocolDeFiGasCostOptimizer(data_file=self.data_file)

    def tearDown(self):
        self.tmp.cleanup()

    def test_log_file_created(self):
        self.opt.optimize([_make_op()])
        self.assertTrue(self.data_file.exists())

    def test_log_is_list(self):
        self.opt.optimize([_make_op()])
        with open(self.data_file) as fh:
            log = json.load(fh)
        self.assertIsInstance(log, list)

    def test_log_entry_count_grows(self):
        for _ in range(3):
            self.opt.optimize([_make_op()])
        with open(self.data_file) as fh:
            log = json.load(fh)
        self.assertEqual(len(log), 3)

    def test_log_entry_keys(self):
        self.opt.optimize([_make_op()])
        with open(self.data_file) as fh:
            log = json.load(fh)
        entry = log[0]
        for key in ["timestamp", "operation_count", "total_monthly_gas_usd"]:
            self.assertIn(key, entry)

    def test_ring_buffer_cap_100(self):
        for i in range(105):
            self.opt.optimize([_make_op(name=f"Op{i}")])
        with open(self.data_file) as fh:
            log = json.load(fh)
        self.assertEqual(len(log), 100)

    def test_no_tmp_file_left(self):
        self.opt.optimize([_make_op()])
        tmp_path = str(self.data_file) + ".tmp"
        self.assertFalse(os.path.exists(tmp_path))

    def test_log_summary_contains_efficiency(self):
        self.opt.optimize([_make_op(name="TestOp")])
        with open(self.data_file) as fh:
            log = json.load(fh)
        summary = log[0]["summary"]
        self.assertEqual(summary[0]["name"], "TestOp")
        self.assertIn("efficiency_label", summary[0])

    def test_corrupted_log_reset(self):
        with open(self.data_file, "w") as fh:
            fh.write("not json {{{")
        self.opt.optimize([_make_op()])
        with open(self.data_file) as fh:
            log = json.load(fh)
        self.assertEqual(len(log), 1)

    def test_non_list_json_reset(self):
        with open(self.data_file, "w") as fh:
            json.dump({"key": "value"}, fh)
        self.opt.optimize([_make_op()])
        with open(self.data_file) as fh:
            log = json.load(fh)
        self.assertIsInstance(log, list)


class TestPassthroughFields(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.opt = ProtocolDeFiGasCostOptimizer(
            data_file=Path(self.tmp.name) / "log.json"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_protocol_passthrough(self):
        op = _make_op(protocol="Compound")
        result = self.opt.optimize([op])
        self.assertEqual(result["operations"][0]["protocol"], "Compound")

    def test_chain_passthrough(self):
        op = _make_op(chain="Optimism")
        result = self.opt.optimize([op])
        self.assertEqual(result["operations"][0]["chain"], "optimism")  # lowercased

    def test_can_batch_passthrough(self):
        op = _make_op(can_batch=True)
        result = self.opt.optimize([op])
        self.assertTrue(result["operations"][0]["can_batch"])

    def test_congestion_factor_passthrough(self):
        op = _make_op(congestion_factor=2.0)
        result = self.opt.optimize([op])
        self.assertAlmostEqual(result["operations"][0]["congestion_factor"], 2.0)

    def test_typical_cheap_gas_passthrough(self):
        op = _make_op(typical_cheap_gas_gwei=5.0)
        result = self.opt.optimize([op])
        self.assertAlmostEqual(result["operations"][0]["typical_cheap_gas_gwei"], 5.0)


class TestMultipleOpTypes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.opt = ProtocolDeFiGasCostOptimizer(
            data_file=Path(self.tmp.name) / "log.json"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_op_types(self):
        op_types = ["swap", "borrow", "repay", "deposit", "withdraw", "harvest", "rebalance", "bridge"]
        ops = [_make_op(name=t, op_type=t) for t in op_types]
        result = self.opt.optimize(ops)
        self.assertEqual(len(result["operations"]), len(op_types))

    def test_harvest_flag_applies_only_to_harvest(self):
        # Only harvest type triggers HARVEST_NOT_WORTH_IT
        ops = [
            _make_op(name="Harvest", op_type="harvest", transaction_value_usd=10.0,
                     estimated_gas_units=500_000, current_gas_price_gwei=100.0, eth_price_usd=3000.0),
            _make_op(name="Swap", op_type="swap", transaction_value_usd=10.0,
                     estimated_gas_units=500_000, current_gas_price_gwei=100.0, eth_price_usd=3000.0),
        ]
        result = self.opt.optimize(ops)
        harvest_flags = result["operations"][0]["flags"]
        swap_flags = result["operations"][1]["flags"]
        self.assertIn("HARVEST_NOT_WORTH_IT", harvest_flags)
        self.assertNotIn("HARVEST_NOT_WORTH_IT", swap_flags)

    def test_bridge_on_ethereum_gets_l2_suggestion(self):
        op = _make_op(
            name="Bridge", op_type="bridge", chain="ethereum",
            estimated_gas_units=300_000, current_gas_price_gwei=50.0,
            eth_price_usd=2000.0, transaction_value_usd=500.0
        )
        result = self.opt.optimize([op])
        flags = result["operations"][0]["flags"]
        self.assertIn("L2_MIGRATION_RECOMMENDED", flags)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.opt = ProtocolDeFiGasCostOptimizer(
            data_file=Path(self.tmp.name) / "log.json"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_name_default(self):
        result = self.opt.optimize([{"estimated_gas_units": 100_000}])
        self.assertEqual(result["operations"][0]["name"], "unknown")

    def test_minimal_operation(self):
        # Should not raise
        result = self.opt.optimize([{"name": "Minimal"}])
        self.assertEqual(result["operations"][0]["gas_cost_usd"], 0.0)

    def test_cost_efficiency_range(self):
        ops = [
            _make_op(estimated_gas_units=10, current_gas_price_gwei=0.01, transaction_value_usd=1_000_000.0),
            _make_op(estimated_gas_units=1_000_000, current_gas_price_gwei=500.0, transaction_value_usd=1.0),
        ]
        result = self.opt.optimize(ops)
        for op in result["operations"]:
            self.assertGreaterEqual(op["cost_efficiency_score"], 0.0)
            self.assertLessEqual(op["cost_efficiency_score"], 100.0)

    def test_savings_pct_range(self):
        ops = [
            _make_op(can_batch=True, can_delay=True, current_gas_price_gwei=100.0,
                     typical_cheap_gas_gwei=1.0, frequency_per_month=100.0),
        ]
        result = self.opt.optimize(ops)
        pct = result["operations"][0]["total_potential_savings_pct"]
        self.assertGreaterEqual(pct, 0.0)
        self.assertLessEqual(pct, 100.0)

    def test_flags_is_list(self):
        result = self.opt.optimize([_make_op()])
        self.assertIsInstance(result["operations"][0]["flags"], list)

    def test_multiple_calls_accumulate_log(self):
        for i in range(5):
            self.opt.optimize([_make_op(name=f"Op{i}")])
        with open(self.opt.data_file) as fh:
            log = json.load(fh)
        self.assertEqual(len(log), 5)


if __name__ == "__main__":
    unittest.main()
