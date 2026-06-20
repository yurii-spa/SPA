"""
MP-992 Tests: DeFiGasCostYieldDragAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_gas_cost_yield_drag_analyzer -v
"""

import json
import os
import unittest
import tempfile

from spa_core.analytics.defi_gas_cost_yield_drag_analyzer import (
    DeFiGasCostYieldDragAnalyzer,
)


def make_pos(**kwargs):
    defaults = {
        "name": "stETH-vault",
        "protocol": "Lido",
        "chain": "arbitrum",
        "gross_apy_pct": 10.0,
        "position_size_usd": 100_000.0,
        "entry_gas_usd": 5.0,
        "exit_gas_usd": 5.0,
        "harvest_gas_usd": 2.0,
        "harvests_per_year": 12.0,
        "holding_days": 365.0,
    }
    defaults.update(kwargs)
    return defaults


class TestBasicShape(unittest.TestCase):
    def setUp(self):
        self.az = DeFiGasCostYieldDragAnalyzer()

    def test_returns_expected_keys(self):
        r = self.az.analyze([make_pos()])
        self.assertEqual(r["position_count"], 1)
        p = r["positions"][0]
        for k in (
            "gross_apy_pct", "position_size_usd", "total_annual_gas_usd",
            "gas_drag_pct", "net_apy_pct", "breakeven_position_usd",
            "gross_profit_usd", "net_profit_usd", "drag_ratio", "drag_score",
            "grade", "classification", "flags",
        ):
            self.assertIn(k, p)

    def test_empty_input(self):
        r = self.az.analyze([])
        self.assertEqual(r["position_count"], 0)
        self.assertIsNone(r["aggregates"]["average_gas_drag_pct"])

    def test_timestamp_present(self):
        r = self.az.analyze([make_pos()])
        self.assertIn("timestamp", r)


class TestGasMath(unittest.TestCase):
    def setUp(self):
        self.az = DeFiGasCostYieldDragAnalyzer()

    def test_net_apy_is_gross_minus_drag(self):
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertAlmostEqual(
            p["net_apy_pct"], p["gross_apy_pct"] - p["gas_drag_pct"], places=4
        )

    def test_total_annual_gas(self):
        # entry+exit = 10 amortised over 1 yr = 10; harvest 2*12 = 24; total 34
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertAlmostEqual(p["total_annual_gas_usd"], 34.0, places=2)

    def test_drag_pct(self):
        # 34 / 100000 * 100 = 0.034 %
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertAlmostEqual(p["gas_drag_pct"], 0.034, places=4)

    def test_one_time_gas_amortised_over_half_year(self):
        # holding 182.5 days = 0.5 yr -> one-time 10 annualises to 20
        p = self.az.analyze([make_pos(holding_days=182.5, harvests_per_year=0,
                                      harvest_gas_usd=0)])["positions"][0]
        self.assertAlmostEqual(p["total_annual_gas_usd"], 20.0, places=2)

    def test_breakeven_position(self):
        # total_annual_gas 34 / (10/100) = 340
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertAlmostEqual(p["breakeven_position_usd"], 340.0, places=2)

    def test_tiny_position_below_breakeven_is_unprofitable(self):
        p = self.az.analyze([make_pos(position_size_usd=100.0)])["positions"][0]
        self.assertIn("BELOW_BREAKEVEN", p["flags"])
        self.assertLess(p["net_apy_pct"], 0.0)
        self.assertEqual(p["classification"], "UNPROFITABLE")

    def test_net_profit_over_holding(self):
        # gross 100000*0.10*1 = 10000; gas over holding = 10 + 24 = 34; net 9966
        p = self.az.analyze([make_pos()])["positions"][0]
        self.assertAlmostEqual(p["gross_profit_usd"], 10000.0, places=2)
        self.assertAlmostEqual(p["net_profit_usd"], 9966.0, places=2)


class TestGuards(unittest.TestCase):
    def setUp(self):
        self.az = DeFiGasCostYieldDragAnalyzer()

    def test_zero_size_no_crash(self):
        p = self.az.analyze([make_pos(position_size_usd=0.0)])["positions"][0]
        self.assertEqual(p["gas_drag_pct"], 0.0)
        self.assertIn("INSUFFICIENT_DATA", p["flags"])

    def test_zero_gross_apy_no_breakeven(self):
        p = self.az.analyze([make_pos(gross_apy_pct=0.0)])["positions"][0]
        self.assertIsNone(p["breakeven_position_usd"])
        self.assertEqual(p["classification"], "UNPROFITABLE")

    def test_zero_holding_days_no_crash(self):
        p = self.az.analyze([make_pos(holding_days=0.0)])["positions"][0]
        self.assertIsInstance(p["total_annual_gas_usd"], float)

    def test_negative_inputs_clamped(self):
        p = self.az.analyze([make_pos(entry_gas_usd=-50.0)])["positions"][0]
        self.assertGreaterEqual(p["total_annual_gas_usd"], 0.0)


class TestClassificationAndScore(unittest.TestCase):
    def setUp(self):
        self.az = DeFiGasCostYieldDragAnalyzer()

    def test_negligible_drag_big_position(self):
        p = self.az.analyze([make_pos(position_size_usd=10_000_000.0)])["positions"][0]
        self.assertEqual(p["classification"], "NEGLIGIBLE_DRAG")
        self.assertEqual(p["grade"], "A")

    def test_score_bounds(self):
        for size in (50.0, 5000.0, 1_000_000.0):
            p = self.az.analyze([make_pos(position_size_usd=size)])["positions"][0]
            self.assertGreaterEqual(p["drag_score"], 0.0)
            self.assertLessEqual(p["drag_score"], 100.0)

    def test_excessive_harvesting_flag(self):
        p = self.az.analyze([make_pos(harvests_per_year=365.0)])["positions"][0]
        self.assertIn("EXCESSIVE_HARVESTING", p["flags"])

    def test_l1_expensive_flag(self):
        p = self.az.analyze([make_pos(chain="ethereum", entry_gas_usd=60.0,
                                      exit_gas_usd=60.0)])["positions"][0]
        self.assertIn("L1_EXPENSIVE", p["flags"])

    def test_tiny_position_flag(self):
        p = self.az.analyze([make_pos(position_size_usd=500.0)])["positions"][0]
        self.assertIn("TINY_POSITION", p["flags"])


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.az = DeFiGasCostYieldDragAnalyzer()

    def test_best_worst_and_counts(self):
        r = self.az.analyze([
            make_pos(name="big", position_size_usd=5_000_000.0),
            make_pos(name="small", position_size_usd=100.0),
        ])
        agg = r["aggregates"]
        self.assertEqual(agg["best_net_yield"]["name"], "big")
        self.assertEqual(agg["worst_net_yield"]["name"], "small")
        self.assertGreaterEqual(agg["below_breakeven_count"], 1)
        self.assertGreaterEqual(agg["unprofitable_count"], 1)

    def test_average_drag(self):
        r = self.az.analyze([make_pos(), make_pos()])
        self.assertIsInstance(r["aggregates"]["average_gas_drag_pct"], float)


class TestLogging(unittest.TestCase):
    def setUp(self):
        self.az = DeFiGasCostYieldDragAnalyzer()

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.az.analyze([make_pos()], config={"write_log": True, "data_dir": d})
            path = os.path.join(d, "gas_cost_yield_drag_log.json")
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)

    def test_ring_buffer_caps_at_100(self):
        with tempfile.TemporaryDirectory() as d:
            for _ in range(105):
                self.az.analyze([make_pos()], config={"write_log": True, "data_dir": d})
            with open(os.path.join(d, "gas_cost_yield_drag_log.json")) as f:
                log = json.load(f)
            self.assertEqual(len(log), 100)

    def test_corrupt_log_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gas_cost_yield_drag_log.json")
            with open(path, "w") as f:
                f.write("{ not json")
            self.az.analyze([make_pos()], config={"write_log": True, "data_dir": d})
            with open(path) as f:
                log = json.load(f)
            self.assertEqual(len(log), 1)


if __name__ == "__main__":
    unittest.main()
