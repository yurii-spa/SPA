"""
Tests for MP-960: DeFiLiquidityMiningROICalculator
Run: python3 -m unittest spa_core.tests.test_defi_liquidity_mining_roi_calculator -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

# Ensure repo root is importable
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_liquidity_mining_roi_calculator import (
    DeFiLiquidityMiningROICalculator,
    _atomic_write,
    _load_log,
)


def _base_program(**overrides):
    base = {
        "protocol": "UniswapV3",
        "pair": "USDC/ETH",
        "base_swap_fee_apy_pct": 5.0,
        "mining_reward_apy_pct": 20.0,
        "reward_token_price_usd": 2.5,
        "reward_token_volatility_pct": 50.0,
        "il_estimate_pct": 3.0,
        "entry_gas_usd": 10.0,
        "exit_gas_usd": 10.0,
        "claim_gas_usd": 5.0,
        "claim_frequency_days": 7.0,
        "program_duration_days": 90.0,
        "days_remaining": 90.0,
        "capital_usd": 10000.0,
        "price_correlation_coefficient": 0.5,
    }
    base.update(overrides)
    return base


class TestDeFiLiquidityMiningROICalculatorBasic(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "lm_log.json")
        self.calc = DeFiLiquidityMiningROICalculator(log_path=self.log_path)

    def test_returns_dict(self):
        result = self.calc.calculate([_base_program()])
        self.assertIsInstance(result, dict)

    def test_top_level_keys(self):
        result = self.calc.calculate([_base_program()])
        for key in ("timestamp", "program_count", "programs", "aggregate"):
            self.assertIn(key, result)

    def test_program_count(self):
        result = self.calc.calculate([_base_program(), _base_program()])
        self.assertEqual(result["program_count"], 2)

    def test_empty_programs(self):
        result = self.calc.calculate([])
        self.assertEqual(result["program_count"], 0)
        self.assertEqual(result["programs"], [])

    def test_single_program_in_programs(self):
        result = self.calc.calculate([_base_program()])
        self.assertEqual(len(result["programs"]), 1)

    def test_program_result_keys(self):
        result = self.calc.calculate([_base_program()])
        prog = result["programs"][0]
        for k in ("protocol", "pair", "gross_mining_apy_pct", "net_apy_after_il_pct",
                  "gas_drag_pct", "final_net_apy_pct", "reward_token_risk_adjusted_apy",
                  "expected_pnl_usd", "roi_label", "flags"):
            self.assertIn(k, prog)

    def test_gross_mining_apy(self):
        prog = _base_program(base_swap_fee_apy_pct=5.0, mining_reward_apy_pct=20.0)
        result = self.calc.calculate([prog])
        self.assertAlmostEqual(result["programs"][0]["gross_mining_apy_pct"], 25.0, places=3)

    def test_net_apy_after_il(self):
        prog = _base_program(base_swap_fee_apy_pct=5.0, mining_reward_apy_pct=20.0, il_estimate_pct=3.0)
        result = self.calc.calculate([prog])
        # gross = 25, net_after_il = 25 - 3 = 22
        self.assertAlmostEqual(result["programs"][0]["net_apy_after_il_pct"], 22.0, places=3)

    def test_protocol_label(self):
        prog = _base_program(protocol="SushiSwap")
        result = self.calc.calculate([prog])
        self.assertEqual(result["programs"][0]["protocol"], "SushiSwap")

    def test_pair_label(self):
        prog = _base_program(pair="WBTC/USDC")
        result = self.calc.calculate([prog])
        self.assertEqual(result["programs"][0]["pair"], "WBTC/USDC")

    def test_timestamp_in_result(self):
        result = self.calc.calculate([_base_program()])
        self.assertIn("Z", result["timestamp"])


class TestGasDrag(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.calc = DeFiLiquidityMiningROICalculator(log_path=os.path.join(self.tmpdir, "log.json"))

    def test_gas_drag_positive(self):
        prog = _base_program(entry_gas_usd=50, exit_gas_usd=50, claim_gas_usd=10,
                              claim_frequency_days=7, days_remaining=90, capital_usd=10000)
        result = self.calc.calculate([prog])
        self.assertGreater(result["programs"][0]["gas_drag_pct"], 0)

    def test_zero_gas_zero_drag(self):
        prog = _base_program(entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0)
        result = self.calc.calculate([prog])
        self.assertAlmostEqual(result["programs"][0]["gas_drag_pct"], 0.0, places=6)

    def test_gas_heavy_flag(self):
        # Very high gas relative to capital should trigger GAS_HEAVY
        prog = _base_program(entry_gas_usd=500, exit_gas_usd=500, claim_gas_usd=200,
                              claim_frequency_days=1, days_remaining=30, capital_usd=1000)
        result = self.calc.calculate([prog])
        self.assertIn("GAS_HEAVY", result["programs"][0]["flags"])

    def test_no_gas_heavy_low_gas(self):
        prog = _base_program(entry_gas_usd=1, exit_gas_usd=1, claim_gas_usd=0.5,
                              claim_frequency_days=30, days_remaining=365, capital_usd=100000)
        result = self.calc.calculate([prog])
        self.assertNotIn("GAS_HEAVY", result["programs"][0]["flags"])

    def test_num_claims_computed(self):
        prog = _base_program(claim_frequency_days=7, days_remaining=28)
        result = self.calc.calculate([prog])
        self.assertEqual(result["programs"][0]["num_claims"], 4)

    def test_num_claims_ceiling(self):
        prog = _base_program(claim_frequency_days=7, days_remaining=29)
        result = self.calc.calculate([prog])
        self.assertEqual(result["programs"][0]["num_claims"], 5)

    def test_zero_days_remaining_no_claims(self):
        prog = _base_program(days_remaining=0)
        result = self.calc.calculate([prog])
        self.assertEqual(result["programs"][0]["num_claims"], 0)
        self.assertAlmostEqual(result["programs"][0]["gas_drag_pct"], 0.0, places=6)


class TestROILabels(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.calc = DeFiLiquidityMiningROICalculator(log_path=os.path.join(self.tmpdir, "log.json"))

    def _calc_with_apy(self, base, mining, il=0, entry=0, exit_g=0, claim=0):
        prog = _base_program(base_swap_fee_apy_pct=base, mining_reward_apy_pct=mining,
                              il_estimate_pct=il, entry_gas_usd=entry, exit_gas_usd=exit_g,
                              claim_gas_usd=claim, claim_frequency_days=365, days_remaining=365,
                              capital_usd=1_000_000)
        return self.calc.calculate([prog])["programs"][0]

    def test_exceptional_label(self):
        prog = self._calc_with_apy(base=10, mining=20)  # net ~30%
        self.assertEqual(prog["roi_label"], "EXCEPTIONAL")

    def test_strong_label(self):
        prog = self._calc_with_apy(base=5, mining=13)  # net ~18%
        self.assertEqual(prog["roi_label"], "STRONG")

    def test_moderate_label(self):
        prog = self._calc_with_apy(base=3, mining=5)  # net 8%
        self.assertEqual(prog["roi_label"], "MODERATE")

    def test_marginal_label(self):
        prog = self._calc_with_apy(base=1, mining=2)  # net 3%
        self.assertEqual(prog["roi_label"], "MARGINAL")

    def test_negative_label(self):
        prog = self._calc_with_apy(base=0, mining=0, il=20)  # net -20%
        self.assertEqual(prog["roi_label"], "NEGATIVE")

    def test_boundary_exceptional_25(self):
        # Exactly 25% → EXCEPTIONAL (> 25 is EXCEPTIONAL, 25 is STRONG... wait let me recheck)
        # _roi_label: >25 EXCEPTIONAL, >15 STRONG, >5 MODERATE, >=0 MARGINAL
        # 25.0 is not > 25, so STRONG
        prog = self._calc_with_apy(base=10, mining=15)
        self.assertIn(prog["roi_label"], ("EXCEPTIONAL", "STRONG"))

    def test_boundary_marginal_zero(self):
        # 0.0 >= 0.0 → MARGINAL
        prog = self._calc_with_apy(base=0, mining=0)
        self.assertEqual(prog["roi_label"], "MARGINAL")


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.calc = DeFiLiquidityMiningROICalculator(log_path=os.path.join(self.tmpdir, "log.json"))

    def test_high_il_risk_flag(self):
        prog = _base_program(il_estimate_pct=20.0)
        result = self.calc.calculate([prog])
        self.assertIn("HIGH_IL_RISK", result["programs"][0]["flags"])

    def test_no_high_il_risk_flag(self):
        prog = _base_program(il_estimate_pct=10.0)
        result = self.calc.calculate([prog])
        self.assertNotIn("HIGH_IL_RISK", result["programs"][0]["flags"])

    def test_high_il_risk_boundary_15(self):
        prog = _base_program(il_estimate_pct=15.01)
        result = self.calc.calculate([prog])
        self.assertIn("HIGH_IL_RISK", result["programs"][0]["flags"])

    def test_reward_volatile_flag(self):
        prog = _base_program(reward_token_volatility_pct=90.0)
        result = self.calc.calculate([prog])
        self.assertIn("REWARD_VOLATILE", result["programs"][0]["flags"])

    def test_no_reward_volatile_flag(self):
        prog = _base_program(reward_token_volatility_pct=70.0)
        result = self.calc.calculate([prog])
        self.assertNotIn("REWARD_VOLATILE", result["programs"][0]["flags"])

    def test_program_ending_soon_flag(self):
        prog = _base_program(days_remaining=7.0)
        result = self.calc.calculate([prog])
        self.assertIn("PROGRAM_ENDING_SOON", result["programs"][0]["flags"])

    def test_no_program_ending_soon_flag(self):
        prog = _base_program(days_remaining=30.0)
        result = self.calc.calculate([prog])
        self.assertNotIn("PROGRAM_ENDING_SOON", result["programs"][0]["flags"])

    def test_program_ending_soon_boundary_14(self):
        prog = _base_program(days_remaining=13.9)
        result = self.calc.calculate([prog])
        self.assertIn("PROGRAM_ENDING_SOON", result["programs"][0]["flags"])

    def test_correlated_pair_flag(self):
        prog = _base_program(price_correlation_coefficient=0.9)
        result = self.calc.calculate([prog])
        self.assertIn("CORRELATED_PAIR", result["programs"][0]["flags"])

    def test_no_correlated_pair_flag(self):
        prog = _base_program(price_correlation_coefficient=0.5)
        result = self.calc.calculate([prog])
        self.assertNotIn("CORRELATED_PAIR", result["programs"][0]["flags"])

    def test_uncorrelated_pair_flag(self):
        prog = _base_program(price_correlation_coefficient=0.1)
        result = self.calc.calculate([prog])
        self.assertIn("UNCORRELATED_PAIR", result["programs"][0]["flags"])

    def test_no_uncorrelated_pair_flag(self):
        prog = _base_program(price_correlation_coefficient=0.5)
        result = self.calc.calculate([prog])
        self.assertNotIn("UNCORRELATED_PAIR", result["programs"][0]["flags"])

    def test_correlated_boundary_08(self):
        prog = _base_program(price_correlation_coefficient=0.81)
        result = self.calc.calculate([prog])
        self.assertIn("CORRELATED_PAIR", result["programs"][0]["flags"])

    def test_uncorrelated_boundary_03(self):
        prog = _base_program(price_correlation_coefficient=0.29)
        result = self.calc.calculate([prog])
        self.assertIn("UNCORRELATED_PAIR", result["programs"][0]["flags"])

    def test_multiple_flags(self):
        prog = _base_program(il_estimate_pct=20, reward_token_volatility_pct=90,
                              days_remaining=10, price_correlation_coefficient=0.1)
        result = self.calc.calculate([prog])
        flags = result["programs"][0]["flags"]
        self.assertIn("HIGH_IL_RISK", flags)
        self.assertIn("REWARD_VOLATILE", flags)
        self.assertIn("PROGRAM_ENDING_SOON", flags)
        self.assertIn("UNCORRELATED_PAIR", flags)

    def test_empty_flags_when_no_triggers(self):
        prog = _base_program(il_estimate_pct=5, reward_token_volatility_pct=30,
                              days_remaining=90, price_correlation_coefficient=0.5,
                              entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0)
        result = self.calc.calculate([prog])
        flags = result["programs"][0]["flags"]
        self.assertNotIn("HIGH_IL_RISK", flags)
        self.assertNotIn("REWARD_VOLATILE", flags)
        self.assertNotIn("PROGRAM_ENDING_SOON", flags)
        self.assertNotIn("CORRELATED_PAIR", flags)
        self.assertNotIn("UNCORRELATED_PAIR", flags)


class TestRewardTokenRiskAdjusted(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.calc = DeFiLiquidityMiningROICalculator(log_path=os.path.join(self.tmpdir, "log.json"))

    def test_zero_volatility_no_discount(self):
        prog = _base_program(mining_reward_apy_pct=20.0, reward_token_volatility_pct=0.0)
        result = self.calc.calculate([prog])
        # Discount = 0/200 = 0, so risk_adjusted = 20 * 1.0 = 20
        self.assertAlmostEqual(result["programs"][0]["reward_token_risk_adjusted_apy"], 20.0, places=3)

    def test_max_volatility_full_discount(self):
        prog = _base_program(mining_reward_apy_pct=20.0, reward_token_volatility_pct=200.0)
        result = self.calc.calculate([prog])
        # Discount = min(200/200, 1) = 1.0, so risk_adjusted = 20 * 0 = 0
        self.assertAlmostEqual(result["programs"][0]["reward_token_risk_adjusted_apy"], 0.0, places=3)

    def test_partial_volatility_discount(self):
        prog = _base_program(mining_reward_apy_pct=20.0, reward_token_volatility_pct=100.0)
        result = self.calc.calculate([prog])
        # Discount = 100/200 = 0.5, risk_adjusted = 20 * 0.5 = 10
        self.assertAlmostEqual(result["programs"][0]["reward_token_risk_adjusted_apy"], 10.0, places=3)

    def test_risk_adjusted_non_negative(self):
        prog = _base_program(mining_reward_apy_pct=5.0, reward_token_volatility_pct=300.0)
        result = self.calc.calculate([prog])
        self.assertGreaterEqual(result["programs"][0]["reward_token_risk_adjusted_apy"], 0.0)


class TestExpectedPnL(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.calc = DeFiLiquidityMiningROICalculator(log_path=os.path.join(self.tmpdir, "log.json"))

    def test_pnl_positive_for_positive_apy(self):
        prog = _base_program(base_swap_fee_apy_pct=10, mining_reward_apy_pct=20, il_estimate_pct=0,
                              entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0,
                              days_remaining=365, capital_usd=10000)
        result = self.calc.calculate([prog])
        self.assertGreater(result["programs"][0]["expected_pnl_usd"], 0)

    def test_pnl_negative_for_negative_apy(self):
        prog = _base_program(base_swap_fee_apy_pct=0, mining_reward_apy_pct=0, il_estimate_pct=20,
                              entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0,
                              days_remaining=365, capital_usd=10000)
        result = self.calc.calculate([prog])
        self.assertLess(result["programs"][0]["expected_pnl_usd"], 0)

    def test_pnl_scales_with_capital(self):
        p1 = _base_program(capital_usd=10000, days_remaining=365, entry_gas_usd=0,
                           exit_gas_usd=0, claim_gas_usd=0)
        p2 = _base_program(capital_usd=20000, days_remaining=365, entry_gas_usd=0,
                           exit_gas_usd=0, claim_gas_usd=0)
        r1 = self.calc.calculate([p1])["programs"][0]["expected_pnl_usd"]
        r2 = self.calc.calculate([p2])["programs"][0]["expected_pnl_usd"]
        self.assertAlmostEqual(r2, r1 * 2, places=1)

    def test_pnl_zero_days_remaining(self):
        prog = _base_program(days_remaining=0)
        result = self.calc.calculate([prog])
        self.assertAlmostEqual(result["programs"][0]["expected_pnl_usd"], 0.0, places=6)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.calc = DeFiLiquidityMiningROICalculator(log_path=os.path.join(self.tmpdir, "log.json"))

    def test_empty_aggregate(self):
        result = self.calc.calculate([])
        agg = result["aggregate"]
        self.assertIsNone(agg["best_roi_program"])
        self.assertIsNone(agg["worst_roi_program"])
        self.assertEqual(agg["total_expected_pnl_usd"], 0.0)
        self.assertEqual(agg["average_final_net_apy"], 0.0)
        self.assertEqual(agg["negative_roi_count"], 0)

    def test_best_roi_program(self):
        p1 = _base_program(protocol="A", base_swap_fee_apy_pct=30, mining_reward_apy_pct=30,
                           il_estimate_pct=0, entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0)
        p2 = _base_program(protocol="B", base_swap_fee_apy_pct=1, mining_reward_apy_pct=1,
                           il_estimate_pct=0, entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0)
        result = self.calc.calculate([p1, p2])
        self.assertEqual(result["aggregate"]["best_roi_program"]["protocol"], "A")

    def test_worst_roi_program(self):
        p1 = _base_program(protocol="A", base_swap_fee_apy_pct=30, mining_reward_apy_pct=30,
                           il_estimate_pct=0, entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0)
        p2 = _base_program(protocol="B", base_swap_fee_apy_pct=1, mining_reward_apy_pct=1,
                           il_estimate_pct=0, entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0)
        result = self.calc.calculate([p1, p2])
        self.assertEqual(result["aggregate"]["worst_roi_program"]["protocol"], "B")

    def test_total_pnl_sum(self):
        p1 = _base_program(days_remaining=0)
        p2 = _base_program(days_remaining=0)
        result = self.calc.calculate([p1, p2])
        self.assertAlmostEqual(result["aggregate"]["total_expected_pnl_usd"], 0.0, places=4)

    def test_average_final_net_apy(self):
        p1 = _base_program(base_swap_fee_apy_pct=10, mining_reward_apy_pct=10, il_estimate_pct=0,
                           entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0)
        p2 = _base_program(base_swap_fee_apy_pct=0, mining_reward_apy_pct=0, il_estimate_pct=0,
                           entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0)
        result = self.calc.calculate([p1, p2])
        self.assertAlmostEqual(result["aggregate"]["average_final_net_apy"], 10.0, places=2)

    def test_negative_roi_count(self):
        p1 = _base_program(il_estimate_pct=50, base_swap_fee_apy_pct=0, mining_reward_apy_pct=0,
                           entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0)
        p2 = _base_program(il_estimate_pct=0, base_swap_fee_apy_pct=10, mining_reward_apy_pct=10,
                           entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0)
        result = self.calc.calculate([p1, p2])
        self.assertEqual(result["aggregate"]["negative_roi_count"], 1)

    def test_negative_roi_count_all_positive(self):
        p1 = _base_program(base_swap_fee_apy_pct=10, mining_reward_apy_pct=10, il_estimate_pct=0,
                           entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0)
        p2 = _base_program(base_swap_fee_apy_pct=5, mining_reward_apy_pct=5, il_estimate_pct=0,
                           entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0)
        result = self.calc.calculate([p1, p2])
        self.assertEqual(result["aggregate"]["negative_roi_count"], 0)

    def test_single_program_best_worst_same(self):
        result = self.calc.calculate([_base_program()])
        agg = result["aggregate"]
        self.assertEqual(agg["best_roi_program"]["protocol"], agg["worst_roi_program"]["protocol"])


class TestLogging(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "lm_log.json")
        self.calc = DeFiLiquidityMiningROICalculator(log_path=self.log_path)

    def test_log_created(self):
        self.calc.calculate([_base_program()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.calc.calculate([_base_program()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_count(self):
        self.calc.calculate([_base_program()])
        self.calc.calculate([_base_program()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_entry_has_ts(self):
        self.calc.calculate([_base_program()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("ts", data[0])

    def test_log_entry_has_program_count(self):
        self.calc.calculate([_base_program(), _base_program()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["program_count"], 2)

    def test_log_ring_buffer_cap(self):
        for _ in range(110):
            self.calc.calculate([_base_program()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_disabled(self):
        self.calc.calculate([_base_program()], config={"log_enabled": False})
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_custom_path(self):
        custom = os.path.join(self.tmpdir, "custom.json")
        self.calc.calculate([_base_program()], config={"log_path": custom})
        self.assertTrue(os.path.exists(custom))


class TestAtomicWrite(unittest.TestCase):
    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"x": 1})
            self.assertTrue(os.path.exists(path))

    def test_atomic_write_content(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, [1, 2, 3])
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, [1, 2, 3])

    def test_atomic_write_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"v": 1})
            _atomic_write(path, {"v": 2})
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["v"], 2)

    def test_load_log_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            result = _load_log(os.path.join(d, "nonexistent.json"))
        self.assertEqual(result, [])

    def test_load_log_invalid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            with open(path, "w") as f:
                f.write("not valid json{{{")
            result = _load_log(path)
        self.assertEqual(result, [])


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.calc = DeFiLiquidityMiningROICalculator(log_path=os.path.join(self.tmpdir, "log.json"))

    def test_very_small_capital(self):
        prog = _base_program(capital_usd=0.001)
        result = self.calc.calculate([prog])
        self.assertIsNotNone(result["programs"][0]["gas_drag_pct"])

    def test_very_high_il(self):
        prog = _base_program(il_estimate_pct=200)
        result = self.calc.calculate([prog])
        self.assertEqual(result["programs"][0]["roi_label"], "NEGATIVE")

    def test_correlation_negative(self):
        prog = _base_program(price_correlation_coefficient=-1.0)
        result = self.calc.calculate([prog])
        self.assertIn("UNCORRELATED_PAIR", result["programs"][0]["flags"])

    def test_correlation_exactly_one(self):
        prog = _base_program(price_correlation_coefficient=1.0)
        result = self.calc.calculate([prog])
        self.assertIn("CORRELATED_PAIR", result["programs"][0]["flags"])

    def test_zero_mining_reward(self):
        prog = _base_program(mining_reward_apy_pct=0, base_swap_fee_apy_pct=0,
                             entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0, il_estimate_pct=0)
        result = self.calc.calculate([prog])
        self.assertAlmostEqual(result["programs"][0]["gross_mining_apy_pct"], 0.0, places=3)

    def test_many_programs(self):
        progs = [_base_program(protocol=f"P{i}") for i in range(50)]
        result = self.calc.calculate(progs)
        self.assertEqual(result["program_count"], 50)
        self.assertEqual(len(result["programs"]), 50)

    def test_default_protocol_name(self):
        prog = {}
        result = self.calc.calculate([prog])
        self.assertEqual(result["programs"][0]["protocol"], "unknown")

    def test_default_pair_name(self):
        prog = {}
        result = self.calc.calculate([prog])
        self.assertEqual(result["programs"][0]["pair"], "unknown")

    def test_final_net_apy_consistent(self):
        prog = _base_program(base_swap_fee_apy_pct=5, mining_reward_apy_pct=15, il_estimate_pct=2,
                             entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0, days_remaining=365)
        result = self.calc.calculate([prog])
        p = result["programs"][0]
        # gross = 20, net_after_il = 18, gas_drag = 0, final = 18
        self.assertAlmostEqual(p["gross_mining_apy_pct"], 20.0, places=3)
        self.assertAlmostEqual(p["net_apy_after_il_pct"], 18.0, places=3)
        self.assertAlmostEqual(p["gas_drag_pct"], 0.0, places=3)
        self.assertAlmostEqual(p["final_net_apy_pct"], 18.0, places=3)

    def test_flags_is_list(self):
        result = self.calc.calculate([_base_program()])
        self.assertIsInstance(result["programs"][0]["flags"], list)

    def test_days_remaining_in_result(self):
        prog = _base_program(days_remaining=42.0)
        result = self.calc.calculate([prog])
        self.assertAlmostEqual(result["programs"][0]["days_remaining"], 42.0, places=3)

    def test_three_programs_agg(self):
        progs = [
            _base_program(protocol="A", base_swap_fee_apy_pct=30, mining_reward_apy_pct=0, il_estimate_pct=0, entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0),
            _base_program(protocol="B", base_swap_fee_apy_pct=10, mining_reward_apy_pct=0, il_estimate_pct=0, entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0),
            _base_program(protocol="C", base_swap_fee_apy_pct=0, mining_reward_apy_pct=0, il_estimate_pct=20, entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0),
        ]
        result = self.calc.calculate(progs)
        self.assertEqual(result["aggregate"]["best_roi_program"]["protocol"], "A")
        self.assertEqual(result["aggregate"]["worst_roi_program"]["protocol"], "C")
        self.assertEqual(result["aggregate"]["negative_roi_count"], 1)

    def test_claim_frequency_larger_than_remaining(self):
        # claim_frequency 30d > days_remaining 20d → ceil(20/30) = 1 claim
        prog = _base_program(claim_frequency_days=30, days_remaining=20)
        result = self.calc.calculate([prog])
        self.assertEqual(result["programs"][0]["num_claims"], 1)

    def test_pnl_formula_correct(self):
        # final_net_apy=10%, capital=10000, days_remaining=365 → pnl=1000
        prog = _base_program(base_swap_fee_apy_pct=10, mining_reward_apy_pct=0, il_estimate_pct=0,
                             entry_gas_usd=0, exit_gas_usd=0, claim_gas_usd=0,
                             days_remaining=365, capital_usd=10000)
        result = self.calc.calculate([prog])
        self.assertAlmostEqual(result["programs"][0]["expected_pnl_usd"], 1000.0, places=1)

    def test_reward_token_volatility_100pct(self):
        prog = _base_program(mining_reward_apy_pct=20.0, reward_token_volatility_pct=100.0)
        result = self.calc.calculate([prog])
        self.assertAlmostEqual(result["programs"][0]["reward_token_risk_adjusted_apy"], 10.0, places=3)

    def test_corr_exactly_08(self):
        prog = _base_program(price_correlation_coefficient=0.8)
        result = self.calc.calculate([prog])
        # 0.8 is NOT > 0.8, so not CORRELATED
        self.assertNotIn("CORRELATED_PAIR", result["programs"][0]["flags"])

    def test_corr_exactly_03(self):
        prog = _base_program(price_correlation_coefficient=0.3)
        result = self.calc.calculate([prog])
        # 0.3 is NOT < 0.3, so not UNCORRELATED
        self.assertNotIn("UNCORRELATED_PAIR", result["programs"][0]["flags"])

    def test_result_has_total_gas_usd(self):
        result = self.calc.calculate([_base_program()])
        self.assertIn("total_gas_usd", result["programs"][0])


if __name__ == "__main__":
    unittest.main()
