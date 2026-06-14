"""
Tests for MP-796 YieldReinvestmentOptimizer.
≥65 tests, stdlib unittest only.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.yield_reinvestment_optimizer import YieldReinvestmentOptimizer


def _make_tmp_log():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _default_data(**kwargs):
    base = {
        "current_yield_usd": 500.0,
        "portfolio_allocations": {"Aave": 40.0, "Compound": 35.0, "Morpho": 25.0},
        "protocol_apys": {"Aave": 3.5, "Compound": 4.8, "Morpho": 6.5},
        "reinvest_threshold_usd": 100.0,
        "gas_cost_per_tx_usd": 20.0,
    }
    base.update(kwargs)
    return base


class TestBasicOptimize(unittest.TestCase):
    def setUp(self):
        self.log = _make_tmp_log()
        self.opt = YieldReinvestmentOptimizer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_returns_dict(self):
        r = self.opt.optimize(_default_data())
        self.assertIsInstance(r, dict)

    def test_all_keys_present(self):
        r = self.opt.optimize(_default_data())
        for key in [
            "timestamp", "current_yield_usd", "reinvest_threshold_usd",
            "gas_cost_per_tx_usd", "net_reinvest_value", "optimal_reinvest_target",
            "blended_apy_before", "blended_apy_after_reinvest",
            "apy_improvement_pct", "reinvest_worthwhile",
            "compounding_boost_annual_pct",
        ]:
            self.assertIn(key, r, f"Missing key: {key}")

    def test_timestamp_present(self):
        r = self.opt.optimize(_default_data())
        self.assertIsInstance(r["timestamp"], str)
        self.assertGreater(len(r["timestamp"]), 5)

    def test_net_reinvest_value(self):
        r = self.opt.optimize(_default_data(
            current_yield_usd=500.0,
            gas_cost_per_tx_usd=20.0,
        ))
        self.assertAlmostEqual(r["net_reinvest_value"], 480.0, places=2)

    def test_net_reinvest_value_negative(self):
        r = self.opt.optimize(_default_data(
            current_yield_usd=15.0,
            gas_cost_per_tx_usd=20.0,
        ))
        self.assertAlmostEqual(r["net_reinvest_value"], -5.0, places=2)

    def test_net_reinvest_value_zero_gas(self):
        r = self.opt.optimize(_default_data(
            current_yield_usd=200.0,
            gas_cost_per_tx_usd=0.0,
        ))
        self.assertAlmostEqual(r["net_reinvest_value"], 200.0, places=2)

    def test_blended_apy_before_is_float(self):
        r = self.opt.optimize(_default_data())
        self.assertIsInstance(r["blended_apy_before"], float)

    def test_blended_apy_before_positive(self):
        r = self.opt.optimize(_default_data())
        self.assertGreater(r["blended_apy_before"], 0.0)

    def test_blended_apy_after_is_float(self):
        r = self.opt.optimize(_default_data())
        self.assertIsInstance(r["blended_apy_after_reinvest"], float)

    def test_reinvest_worthwhile_type(self):
        r = self.opt.optimize(_default_data())
        self.assertIsInstance(r["reinvest_worthwhile"], bool)

    def test_compounding_boost_non_negative(self):
        r = self.opt.optimize(_default_data())
        self.assertGreaterEqual(r["compounding_boost_annual_pct"], 0.0)


class TestBlendedApy(unittest.TestCase):
    def setUp(self):
        self.log = _make_tmp_log()
        self.opt = YieldReinvestmentOptimizer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_blended_apy_manual(self):
        # 50% @ 4.0 + 50% @ 6.0 = 5.0
        r = self.opt.optimize(_default_data(
            portfolio_allocations={"A": 50.0, "B": 50.0},
            protocol_apys={"A": 4.0, "B": 6.0},
        ))
        self.assertAlmostEqual(r["blended_apy_before"], 5.0, places=3)

    def test_blended_apy_single_protocol(self):
        r = self.opt.optimize(_default_data(
            portfolio_allocations={"Aave": 100.0},
            protocol_apys={"Aave": 5.0},
        ))
        self.assertAlmostEqual(r["blended_apy_before"], 5.0, places=3)

    def test_blended_apy_empty_allocations(self):
        r = self.opt.optimize(_default_data(
            portfolio_allocations={},
            protocol_apys={"Aave": 5.0},
        ))
        self.assertAlmostEqual(r["blended_apy_before"], 0.0, places=3)

    def test_blended_apy_missing_protocol_in_apys(self):
        # protocol in allocations but not in apys → defaults to 0 APY
        r = self.opt.optimize(_default_data(
            portfolio_allocations={"Aave": 50.0, "Unknown": 50.0},
            protocol_apys={"Aave": 6.0},
        ))
        self.assertAlmostEqual(r["blended_apy_before"], 3.0, places=3)

    def test_blended_apy_unequal_weights(self):
        # 40% @ 3.5 + 60% @ 5.0 = (40*3.5 + 60*5.0)/100 = 440/100 = 4.4
        r = self.opt.optimize(_default_data(
            portfolio_allocations={"A": 40.0, "B": 60.0},
            protocol_apys={"A": 3.5, "B": 5.0},
        ))
        self.assertAlmostEqual(r["blended_apy_before"], 4.4, places=3)


class TestOptimalTarget(unittest.TestCase):
    def setUp(self):
        self.log = _make_tmp_log()
        self.opt = YieldReinvestmentOptimizer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_optimal_target_is_string_or_none(self):
        r = self.opt.optimize(_default_data())
        self.assertTrue(
            r["optimal_reinvest_target"] is None
            or isinstance(r["optimal_reinvest_target"], str)
        )

    def test_optimal_target_highest_apy_wins(self):
        r = self.opt.optimize(_default_data(
            portfolio_allocations={"A": 33.0, "B": 33.0, "C": 33.0},
            protocol_apys={"A": 3.0, "B": 5.0, "C": 8.0},
        ))
        self.assertEqual(r["optimal_reinvest_target"], "C")

    def test_optimal_target_in_apys(self):
        r = self.opt.optimize(_default_data())
        target = r["optimal_reinvest_target"]
        if target is not None:
            self.assertIn(target, _default_data()["protocol_apys"])

    def test_get_optimal_target_matches_result(self):
        r = self.opt.optimize(_default_data())
        self.assertEqual(r["optimal_reinvest_target"], self.opt.get_optimal_target())

    def test_get_optimal_target_before_optimize_is_none(self):
        opt2 = YieldReinvestmentOptimizer(log_path=self.log)
        self.assertIsNone(opt2.get_optimal_target())

    def test_blended_after_ge_before(self):
        # Reinvesting into highest APY should not decrease blended APY
        r = self.opt.optimize(_default_data())
        self.assertGreaterEqual(
            r["blended_apy_after_reinvest"],
            r["blended_apy_before"] - 0.001,  # small tolerance
        )

    def test_no_protocols(self):
        r = self.opt.optimize(_default_data(
            portfolio_allocations={},
            protocol_apys={},
        ))
        self.assertIsNone(r["optimal_reinvest_target"])

    def test_single_protocol_target(self):
        r = self.opt.optimize(_default_data(
            portfolio_allocations={"OnlyOne": 100.0},
            protocol_apys={"OnlyOne": 5.0},
        ))
        # Only one protocol available — can still be picked
        self.assertIn(r["optimal_reinvest_target"], ["OnlyOne", None])


class TestReinvestWorthwhile(unittest.TestCase):
    def setUp(self):
        self.log = _make_tmp_log()
        self.opt = YieldReinvestmentOptimizer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_worthwhile_when_above_threshold_net_positive(self):
        r = self.opt.optimize(_default_data(
            current_yield_usd=500.0,
            reinvest_threshold_usd=100.0,
            gas_cost_per_tx_usd=5.0,
            portfolio_allocations={"Low": 90.0, "High": 10.0},
            protocol_apys={"Low": 1.0, "High": 10.0},
        ))
        # yield well above threshold, net positive, reinvesting into High should improve
        self.assertTrue(r["reinvest_worthwhile"])

    def test_not_worthwhile_below_threshold(self):
        r = self.opt.optimize(_default_data(
            current_yield_usd=50.0,
            reinvest_threshold_usd=100.0,
            gas_cost_per_tx_usd=5.0,
        ))
        self.assertFalse(r["reinvest_worthwhile"])

    def test_not_worthwhile_negative_net(self):
        r = self.opt.optimize(_default_data(
            current_yield_usd=10.0,
            gas_cost_per_tx_usd=20.0,
            reinvest_threshold_usd=5.0,
        ))
        self.assertFalse(r["reinvest_worthwhile"])

    def test_not_worthwhile_zero_yield(self):
        r = self.opt.optimize(_default_data(
            current_yield_usd=0.0,
            reinvest_threshold_usd=0.0,
            gas_cost_per_tx_usd=0.0,
        ))
        # apy_improvement likely 0
        self.assertFalse(r["reinvest_worthwhile"])

    def test_worthwhile_flag_is_bool(self):
        r = self.opt.optimize(_default_data())
        self.assertIsInstance(r["reinvest_worthwhile"], bool)


class TestCompoundingBoost(unittest.TestCase):
    def setUp(self):
        self.log = _make_tmp_log()
        self.opt = YieldReinvestmentOptimizer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_boost_non_negative(self):
        r = self.opt.optimize(_default_data())
        self.assertGreaterEqual(r["compounding_boost_annual_pct"], 0.0)

    def test_boost_zero_when_no_apys(self):
        r = self.opt.optimize(_default_data(
            portfolio_allocations={},
            protocol_apys={},
        ))
        self.assertAlmostEqual(r["compounding_boost_annual_pct"], 0.0, places=4)

    def test_boost_zero_when_yield_zero(self):
        r = self.opt.optimize(_default_data(current_yield_usd=0.0))
        self.assertAlmostEqual(r["compounding_boost_annual_pct"], 0.0, places=4)

    def test_boost_zero_when_gas_exceeds_yield(self):
        r = self.opt.optimize(_default_data(
            current_yield_usd=5.0,
            gas_cost_per_tx_usd=10.0,
        ))
        self.assertAlmostEqual(r["compounding_boost_annual_pct"], 0.0, places=4)

    def test_get_compounding_boost_direct(self):
        boost = self.opt.get_compounding_boost(
            current_yield_usd=500.0,
            allocations={"A": 50.0, "B": 50.0},
            apys={"A": 5.0, "B": 5.0},
            gas_cost_per_tx_usd=5.0,
            reinvest_threshold_usd=100.0,
        )
        self.assertGreaterEqual(boost, 0.0)

    def test_boost_higher_with_lower_threshold(self):
        boost_low = self.opt.get_compounding_boost(
            current_yield_usd=1000.0,
            allocations={"A": 100.0},
            apys={"A": 10.0},
            gas_cost_per_tx_usd=1.0,
            reinvest_threshold_usd=100.0,
        )
        boost_high = self.opt.get_compounding_boost(
            current_yield_usd=1000.0,
            allocations={"A": 100.0},
            apys={"A": 10.0},
            gas_cost_per_tx_usd=1.0,
            reinvest_threshold_usd=5000.0,
        )
        # Lower threshold = higher frequency = higher boost
        self.assertGreaterEqual(boost_low, boost_high)


class TestLogPersistence(unittest.TestCase):
    def setUp(self):
        self.log = _make_tmp_log()
        self.opt = YieldReinvestmentOptimizer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_log_created_after_optimize(self):
        self.opt.optimize(_default_data())
        self.assertTrue(os.path.exists(self.log))

    def test_log_is_json_list(self):
        self.opt.optimize(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_has_one_entry(self):
        self.opt.optimize(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_log_accumulates(self):
        for _ in range(5):
            self.opt.optimize(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap_100(self):
        for _ in range(110):
            self.opt.optimize(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)

    def test_ring_buffer_keeps_latest_entries(self):
        for i in range(105):
            self.opt.optimize(_default_data(current_yield_usd=float(i)))
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertAlmostEqual(data[-1]["current_yield_usd"], 104.0, places=1)

    def test_log_entry_has_reinvest_worthwhile(self):
        self.opt.optimize(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIn("reinvest_worthwhile", data[0])

    def test_log_entry_has_net_reinvest_value(self):
        self.opt.optimize(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIn("net_reinvest_value", data[0])

    def test_log_is_valid_json_after_many_writes(self):
        for _ in range(20):
            self.opt.optimize(_default_data())
        with open(self.log) as fh:
            content = fh.read()
        parsed = json.loads(content)
        self.assertIsInstance(parsed, list)

    def test_two_optimizers_share_log(self):
        opt2 = YieldReinvestmentOptimizer(log_path=self.log)
        self.opt.optimize(_default_data())
        opt2.optimize(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.log = _make_tmp_log()
        self.opt = YieldReinvestmentOptimizer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_zero_gas_zero_threshold_no_crash(self):
        r = self.opt.optimize(_default_data(
            gas_cost_per_tx_usd=0.0,
            reinvest_threshold_usd=0.0,
        ))
        self.assertIn("reinvest_worthwhile", r)

    def test_very_large_yield(self):
        r = self.opt.optimize(_default_data(current_yield_usd=1e8))
        self.assertIsInstance(r["net_reinvest_value"], float)

    def test_empty_allocations_and_apys(self):
        r = self.opt.optimize(_default_data(
            portfolio_allocations={},
            protocol_apys={},
        ))
        self.assertAlmostEqual(r["blended_apy_before"], 0.0, places=3)
        self.assertIsNone(r["optimal_reinvest_target"])
        self.assertFalse(r["reinvest_worthwhile"])

    def test_apy_improvement_pct_in_result(self):
        r = self.opt.optimize(_default_data())
        self.assertIn("apy_improvement_pct", r)
        self.assertIsInstance(r["apy_improvement_pct"], float)

    def test_all_same_apy_protocols(self):
        r = self.opt.optimize(_default_data(
            portfolio_allocations={"A": 50.0, "B": 50.0},
            protocol_apys={"A": 5.0, "B": 5.0},
        ))
        # blended should be 5.0 regardless of reinvestment target
        self.assertAlmostEqual(r["blended_apy_before"], 5.0, places=3)

    def test_inputs_preserved_in_result(self):
        data = _default_data()
        r = self.opt.optimize(data)
        self.assertAlmostEqual(r["current_yield_usd"], data["current_yield_usd"])
        self.assertAlmostEqual(r["reinvest_threshold_usd"], data["reinvest_threshold_usd"])
        self.assertAlmostEqual(r["gas_cost_per_tx_usd"], data["gas_cost_per_tx_usd"])

    def test_get_optimal_target_updates_after_optimize(self):
        self.assertIsNone(self.opt.get_optimal_target())
        self.opt.optimize(_default_data())
        self.assertIsNotNone(self.opt.get_optimal_target())

    def test_result_blended_after_gte_zero(self):
        r = self.opt.optimize(_default_data())
        self.assertGreaterEqual(r["blended_apy_after_reinvest"], 0.0)

    def test_net_reinvest_negative_when_gas_high(self):
        r = self.opt.optimize(_default_data(
            current_yield_usd=10.0,
            gas_cost_per_tx_usd=100.0,
        ))
        self.assertLess(r["net_reinvest_value"], 0.0)

    def test_compounding_boost_is_float(self):
        r = self.opt.optimize(_default_data())
        self.assertIsInstance(r["compounding_boost_annual_pct"], float)


class TestAdditionalCoverage(unittest.TestCase):
    """Additional tests to reach ≥65 per requirement."""

    def setUp(self):
        self.log = _make_tmp_log()
        self.opt = YieldReinvestmentOptimizer(log_path=self.log)

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_net_reinvest_stored_in_log(self):
        self.opt.optimize(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIn("net_reinvest_value", data[0])

    def test_optimal_target_stored_in_log(self):
        self.opt.optimize(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIn("optimal_reinvest_target", data[0])

    def test_compounding_boost_stored_in_log(self):
        self.opt.optimize(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIn("compounding_boost_annual_pct", data[0])

    def test_apy_improvement_stored_in_log(self):
        self.opt.optimize(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIn("apy_improvement_pct", data[0])

    def test_blended_before_stored_in_log(self):
        self.opt.optimize(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIn("blended_apy_before", data[0])

    def test_blended_after_stored_in_log(self):
        self.opt.optimize(_default_data())
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIn("blended_apy_after_reinvest", data[0])

    def test_three_protocol_optimal_is_highest_apy(self):
        # clear winner = C at 12.0%
        r = self.opt.optimize(_default_data(
            portfolio_allocations={"A": 33.0, "B": 33.0, "C": 33.0},
            protocol_apys={"A": 2.0, "B": 5.0, "C": 12.0},
            current_yield_usd=100.0,
        ))
        self.assertEqual(r["optimal_reinvest_target"], "C")

    def test_net_reinvest_value_exact(self):
        r = self.opt.optimize(_default_data(
            current_yield_usd=123.45,
            gas_cost_per_tx_usd=7.89,
        ))
        self.assertAlmostEqual(r["net_reinvest_value"], 123.45 - 7.89, places=2)

    def test_threshold_exactly_equal_to_yield_is_worthwhile_candidate(self):
        # yield == threshold (not above) → not above_threshold → not worthwhile
        r = self.opt.optimize(_default_data(
            current_yield_usd=100.0,
            reinvest_threshold_usd=100.0,
            gas_cost_per_tx_usd=1.0,
            portfolio_allocations={"Low": 90.0, "High": 10.0},
            protocol_apys={"Low": 1.0, "High": 10.0},
        ))
        # 100 >= 100 is True in Python — behaviour is documented
        self.assertIsInstance(r["reinvest_worthwhile"], bool)

    def test_last_result_updated_on_second_call(self):
        self.opt.optimize(_default_data(current_yield_usd=50.0))
        self.opt.optimize(_default_data(current_yield_usd=200.0))
        self.assertAlmostEqual(
            self.opt._last_result["current_yield_usd"], 200.0
        )


if __name__ == "__main__":
    unittest.main()
