"""
Tests for MP-661 GasCostOptimizer (spa_core/analytics/gas_cost_optimizer.py)
Pure stdlib unittest — do NOT use pytest or any external deps.
Run: python3 -m unittest spa_core.tests.test_gas_cost_optimizer -v
"""

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap – works whether run as "python3 -m unittest" from repo root
# or directly.
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.analytics.gas_cost_optimizer import (
    GAS_ESTIMATES,
    GasCostOptimizer,
    GasEstimate,
    MAX_ENTRIES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_optimizer(tmp_dir: str) -> GasCostOptimizer:
    """Return an optimizer wired to a temp data file."""
    return GasCostOptimizer(data_file=Path(tmp_dir) / "gas_cost_log.json")


def _simple_estimate(opt: GasCostOptimizer, **kwargs) -> GasEstimate:
    defaults = dict(
        operation="AAVE_DEPOSIT",
        gas_price_gwei=30.0,
        eth_price_usd=2000.0,
        capital_usd=10_000.0,
        expected_apy=0.05,
    )
    defaults.update(kwargs)
    return opt.estimate(**defaults)


# ===========================================================================
# 1. _gas_cost_eth
# ===========================================================================

class TestGasCostEth(unittest.TestCase):

    def setUp(self):
        self.opt = GasCostOptimizer()

    def test_standard_values(self):
        # 200_000 * 30 * 1e-9 = 0.006
        result = self.opt._gas_cost_eth(200_000, 30)
        self.assertAlmostEqual(result, 0.006, places=9)

    def test_zero_gas_units(self):
        result = self.opt._gas_cost_eth(0, 50.0)
        self.assertEqual(result, 0.0)

    def test_zero_gas_price(self):
        result = self.opt._gas_cost_eth(200_000, 0.0)
        self.assertEqual(result, 0.0)

    def test_both_zero(self):
        self.assertEqual(self.opt._gas_cost_eth(0, 0.0), 0.0)

    def test_small_gas_units(self):
        # 65_000 * 10 * 1e-9 = 6.5e-4
        result = self.opt._gas_cost_eth(65_000, 10)
        self.assertAlmostEqual(result, 65_000 * 10 * 1e-9, places=12)

    def test_high_gas_price(self):
        result = self.opt._gas_cost_eth(350_000, 200)
        self.assertAlmostEqual(result, 350_000 * 200 * 1e-9, places=12)

    def test_fractional_gas_price(self):
        result = self.opt._gas_cost_eth(200_000, 1.5)
        self.assertAlmostEqual(result, 200_000 * 1.5 * 1e-9, places=12)

    def test_returns_float(self):
        self.assertIsInstance(self.opt._gas_cost_eth(100_000, 5), float)


# ===========================================================================
# 2. _verdict
# ===========================================================================

class TestVerdict(unittest.TestCase):

    def setUp(self):
        self.opt = GasCostOptimizer()

    def test_efficient_below_5(self):
        self.assertEqual(self.opt._verdict(4.99), "EFFICIENT")

    def test_efficient_zero(self):
        self.assertEqual(self.opt._verdict(0.0), "EFFICIENT")

    def test_marginal_at_5(self):
        self.assertEqual(self.opt._verdict(5.0), "MARGINAL")

    def test_marginal_middle(self):
        self.assertEqual(self.opt._verdict(12.0), "MARGINAL")

    def test_marginal_just_below_20(self):
        self.assertEqual(self.opt._verdict(19.99), "MARGINAL")

    def test_expensive_at_20(self):
        self.assertEqual(self.opt._verdict(20.0), "EXPENSIVE")

    def test_expensive_middle(self):
        self.assertEqual(self.opt._verdict(35.0), "EXPENSIVE")

    def test_expensive_just_below_50(self):
        self.assertEqual(self.opt._verdict(49.99), "EXPENSIVE")

    def test_prohibitive_at_50(self):
        self.assertEqual(self.opt._verdict(50.0), "PROHIBITIVE")

    def test_prohibitive_100(self):
        self.assertEqual(self.opt._verdict(100.0), "PROHIBITIVE")

    def test_prohibitive_999(self):
        self.assertEqual(self.opt._verdict(999.0), "PROHIBITIVE")

    def test_return_type_is_str(self):
        self.assertIsInstance(self.opt._verdict(10.0), str)


# ===========================================================================
# 3. _break_even_days
# ===========================================================================

class TestBreakEvenDays(unittest.TestCase):

    def setUp(self):
        self.opt = GasCostOptimizer()

    def test_zero_yield_returns_inf(self):
        result = self.opt._break_even_days(100.0, 0.0)
        self.assertEqual(result, float("inf"))

    def test_negative_yield_returns_inf(self):
        result = self.opt._break_even_days(10.0, -5.0)
        self.assertEqual(result, float("inf"))

    def test_positive_yield_correct(self):
        # gas=$10, annual_yield=$500 → daily=$500/365 → be=10/(500/365)
        expected = round(10.0 / (500.0 / 365), 2)
        result = self.opt._break_even_days(10.0, 500.0)
        self.assertAlmostEqual(result, expected, places=4)

    def test_zero_gas_cost(self):
        result = self.opt._break_even_days(0.0, 500.0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_result_rounded_to_2dp(self):
        result = self.opt._break_even_days(1.0, 100.0)
        self.assertEqual(result, round(1.0 / (100.0 / 365), 2))

    def test_large_gas_small_yield(self):
        result = self.opt._break_even_days(1000.0, 10.0)
        self.assertGreater(result, 365 * 10)

    def test_gas_equals_yield_one_year(self):
        # gas = annual_yield → be = 365 days
        result = self.opt._break_even_days(500.0, 500.0)
        self.assertAlmostEqual(result, 365.0, places=2)


# ===========================================================================
# 4. estimate — known operation gas units
# ===========================================================================

class TestEstimateKnownOps(unittest.TestCase):

    def setUp(self):
        self.opt = GasCostOptimizer()

    def test_aave_deposit_uses_200000(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 2000, 10000, 0.05)
        self.assertEqual(e.gas_units, 200_000)

    def test_aave_withdraw_uses_220000(self):
        e = self.opt.estimate("AAVE_WITHDRAW", 30, 2000, 10000, 0.05)
        self.assertEqual(e.gas_units, 220_000)

    def test_erc20_transfer_uses_65000(self):
        e = self.opt.estimate("ERC20_TRANSFER", 30, 2000, 10000, 0.05)
        self.assertEqual(e.gas_units, 65_000)

    def test_compound_supply_uses_150000(self):
        e = self.opt.estimate("COMPOUND_SUPPLY", 30, 2000, 10000, 0.05)
        self.assertEqual(e.gas_units, 150_000)

    def test_pendle_swap_uses_350000(self):
        e = self.opt.estimate("PENDLE_SWAP", 30, 2000, 10000, 0.05)
        self.assertEqual(e.gas_units, 350_000)

    def test_morpho_supply_uses_280000(self):
        e = self.opt.estimate("MORPHO_SUPPLY", 30, 2000, 10000, 0.05)
        self.assertEqual(e.gas_units, 280_000)

    def test_generic_approve_uses_46000(self):
        e = self.opt.estimate("GENERIC_APPROVE", 30, 2000, 10000, 0.05)
        self.assertEqual(e.gas_units, 46_000)

    def test_uniswap_v3_swap_uses_180000(self):
        e = self.opt.estimate("UNISWAP_V3_SWAP", 30, 2000, 10000, 0.05)
        self.assertEqual(e.gas_units, 180_000)

    def test_curve_swap_uses_250000(self):
        e = self.opt.estimate("CURVE_SWAP", 30, 2000, 10000, 0.05)
        self.assertEqual(e.gas_units, 250_000)


# ===========================================================================
# 5. estimate — unknown operation defaults
# ===========================================================================

class TestEstimateUnknownOp(unittest.TestCase):

    def setUp(self):
        self.opt = GasCostOptimizer()

    def test_unknown_op_defaults_200000(self):
        e = self.opt.estimate("UNKNOWN_OP_XYZ", 30, 2000, 10000, 0.05)
        self.assertEqual(e.gas_units, 200_000)

    def test_empty_string_op_defaults_200000(self):
        e = self.opt.estimate("", 30, 2000, 10000, 0.05)
        self.assertEqual(e.gas_units, 200_000)

    def test_unknown_op_operation_field_preserved(self):
        e = self.opt.estimate("MY_CUSTOM_OP", 30, 2000, 10000, 0.05)
        self.assertEqual(e.operation, "MY_CUSTOM_OP")


# ===========================================================================
# 6. estimate — field correctness
# ===========================================================================

class TestEstimateFieldCorrectness(unittest.TestCase):

    def setUp(self):
        self.opt = GasCostOptimizer()

    def test_gas_cost_usd_equals_eth_times_price(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 2000, 10000, 0.05)
        expected_eth = 200_000 * 30 * 1e-9
        expected_usd = round(expected_eth * 2000, 4)
        self.assertAlmostEqual(e.gas_cost_usd, expected_usd, places=6)

    def test_gas_cost_eth_value(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 2000, 10000, 0.05)
        expected = round(200_000 * 30 * 1e-9, 8)
        self.assertAlmostEqual(e.gas_cost_eth, expected, places=8)

    def test_expected_yield_usd(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 2000, 10000, 0.05)
        self.assertAlmostEqual(e.expected_yield_usd, round(10000 * 0.05, 4), places=4)

    def test_gas_as_pct_of_capital_formula(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 2000, 10000, 0.05)
        expected = round(e.gas_cost_usd / 10000 * 100, 4)
        self.assertAlmostEqual(e.gas_as_pct_of_capital, expected, places=4)

    def test_gas_as_pct_of_yield_formula(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 2000, 10000, 0.05)
        expected_yield = 10000 * 0.05
        expected_pct = round(e.gas_cost_usd / expected_yield * 100, 4)
        self.assertAlmostEqual(e.gas_as_pct_of_yield, expected_pct, places=4)

    def test_break_even_days_formula(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 2000, 10000, 0.05)
        daily_yield = (10000 * 0.05) / 365
        expected_be = round(e.gas_cost_usd / daily_yield, 2)
        self.assertAlmostEqual(e.break_even_days, expected_be, places=2)

    def test_operation_field_stored(self):
        e = self.opt.estimate("CURVE_SWAP", 30, 2000, 10000, 0.05)
        self.assertEqual(e.operation, "CURVE_SWAP")

    def test_gas_price_gwei_rounded(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30.123456, 2000, 10000, 0.05)
        self.assertEqual(e.gas_price_gwei, round(30.123456, 2))

    def test_eth_price_usd_rounded(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 2000.789, 10000, 0.05)
        self.assertEqual(e.eth_price_usd, round(2000.789, 2))

    def test_capital_usd_rounded(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 2000, 10000.999, 0.05)
        self.assertEqual(e.capital_usd, round(10000.999, 2))

    def test_returns_gas_estimate_instance(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 2000, 10000, 0.05)
        self.assertIsInstance(e, GasEstimate)


# ===========================================================================
# 7. estimate — edge-case inputs
# ===========================================================================

class TestEstimateEdgeCases(unittest.TestCase):

    def setUp(self):
        self.opt = GasCostOptimizer()

    def test_capital_zero_pct_capital_is_zero(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 2000, 0, 0.05)
        self.assertEqual(e.gas_as_pct_of_capital, 0.0)

    def test_apy_zero_pct_yield_is_999(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 2000, 10000, 0.0)
        self.assertEqual(e.gas_as_pct_of_yield, 999.0)

    def test_apy_zero_verdict_prohibitive(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 2000, 10000, 0.0)
        self.assertEqual(e.verdict, "PROHIBITIVE")

    def test_apy_zero_break_even_inf(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 2000, 10000, 0.0)
        self.assertEqual(e.break_even_days, float("inf"))

    def test_high_capital_low_gas_efficient(self):
        # 10M capital, 5% APY → $500k yield; gas with 5 gwei ≈ tiny
        e = self.opt.estimate("AAVE_DEPOSIT", 5, 2000, 10_000_000, 0.05)
        self.assertEqual(e.verdict, "EFFICIENT")

    def test_low_capital_high_gas_prohibitive(self):
        # $100 capital, 1% APY → $1 yield; high gas price wipes it
        e = self.opt.estimate("AAVE_DEPOSIT", 500, 5000, 100, 0.01)
        self.assertEqual(e.verdict, "PROHIBITIVE")

    def test_gas_price_zero_gas_cost_zero(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 0.0, 2000, 10000, 0.05)
        self.assertEqual(e.gas_cost_usd, 0.0)
        self.assertEqual(e.gas_cost_eth, 0.0)

    def test_eth_price_zero_gas_cost_usd_zero(self):
        e = self.opt.estimate("AAVE_DEPOSIT", 30, 0.0, 10000, 0.05)
        self.assertEqual(e.gas_cost_usd, 0.0)

    def test_marginal_verdict_boundary(self):
        # Force gas_pct_yield = 10 → MARGINAL
        opt = self.opt
        # apy=1.0 (100%), capital=10000 → yield=10000; gas_usd=10 → 0.1% → EFFICIENT
        # We need ~10% → gas_usd = 1000 on yield of 10000
        # gas_usd = gas_eth * eth_price; gas_eth = 200000 * gwei * 1e-9
        # 200000 * gwei * 1e-9 * 2000 = 1000 → gwei = 1000 / (200000 * 1e-9 * 2000) = 2500
        e = opt.estimate("AAVE_DEPOSIT", 2500, 2000, 10000, 1.0)
        self.assertIn(e.verdict, ("MARGINAL",))


# ===========================================================================
# 8. estimate_batch
# ===========================================================================

class TestEstimateBatch(unittest.TestCase):

    def setUp(self):
        self.opt = GasCostOptimizer()

    def test_empty_batch_returns_empty_list(self):
        result = self.opt.estimate_batch([])
        self.assertEqual(result, [])

    def test_single_item_batch(self):
        req = dict(operation="AAVE_DEPOSIT", gas_price_gwei=30,
                   eth_price_usd=2000, capital_usd=10000, expected_apy=0.05)
        result = self.opt.estimate_batch([req])
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], GasEstimate)

    def test_multiple_items_batch_length(self):
        reqs = [
            dict(operation="AAVE_DEPOSIT", gas_price_gwei=30,
                 eth_price_usd=2000, capital_usd=10000, expected_apy=0.05),
            dict(operation="COMPOUND_SUPPLY", gas_price_gwei=20,
                 eth_price_usd=2000, capital_usd=5000, expected_apy=0.04),
            dict(operation="ERC20_TRANSFER", gas_price_gwei=15,
                 eth_price_usd=2000, capital_usd=1000, expected_apy=0.03),
        ]
        result = self.opt.estimate_batch(reqs)
        self.assertEqual(len(result), 3)

    def test_batch_operations_are_independent(self):
        reqs = [
            dict(operation="AAVE_DEPOSIT", gas_price_gwei=30,
                 eth_price_usd=2000, capital_usd=10000, expected_apy=0.05),
            dict(operation="PENDLE_SWAP", gas_price_gwei=30,
                 eth_price_usd=2000, capital_usd=10000, expected_apy=0.05),
        ]
        result = self.opt.estimate_batch(reqs)
        self.assertEqual(result[0].gas_units, 200_000)
        self.assertEqual(result[1].gas_units, 350_000)

    def test_batch_unknown_op_defaults(self):
        req = dict(operation="MYSTERY", gas_price_gwei=30,
                   eth_price_usd=2000, capital_usd=10000, expected_apy=0.05)
        result = self.opt.estimate_batch([req])
        self.assertEqual(result[0].gas_units, 200_000)

    def test_batch_returns_list_of_gas_estimate(self):
        reqs = [
            dict(operation="AAVE_DEPOSIT", gas_price_gwei=30,
                 eth_price_usd=2000, capital_usd=10000, expected_apy=0.05),
        ]
        result = self.opt.estimate_batch(reqs)
        for item in result:
            self.assertIsInstance(item, GasEstimate)


# ===========================================================================
# 9. optimal_gas_price
# ===========================================================================

class TestOptimalGasPrice(unittest.TestCase):

    def setUp(self):
        self.opt = GasCostOptimizer()

    def test_zero_yield_returns_zero(self):
        result = self.opt.optimal_gas_price(
            max_gas_pct_of_yield=5,
            operation="AAVE_DEPOSIT",
            eth_price_usd=2000,
            capital_usd=10000,
            expected_apy=0.0,
        )
        self.assertEqual(result, 0.0)

    def test_zero_eth_price_returns_zero(self):
        result = self.opt.optimal_gas_price(
            max_gas_pct_of_yield=5,
            operation="AAVE_DEPOSIT",
            eth_price_usd=0.0,
            capital_usd=10000,
            expected_apy=0.05,
        )
        self.assertEqual(result, 0.0)

    def test_correct_formula(self):
        # max 5% of yield: yield=10000*0.05=500 → max_gas_usd=25
        # max_gas_eth = 25/2000 = 0.0125
        # max_gwei = 0.0125 / (200000 * 1e-9) = 62.5
        result = self.opt.optimal_gas_price(
            max_gas_pct_of_yield=5,
            operation="AAVE_DEPOSIT",
            eth_price_usd=2000,
            capital_usd=10000,
            expected_apy=0.05,
        )
        expected = round(0.0125 / (200_000 * 1e-9), 2)
        self.assertAlmostEqual(result, expected, places=2)

    def test_higher_threshold_higher_max_gwei(self):
        r1 = self.opt.optimal_gas_price(5, "AAVE_DEPOSIT", 2000, 10000, 0.05)
        r2 = self.opt.optimal_gas_price(20, "AAVE_DEPOSIT", 2000, 10000, 0.05)
        self.assertGreater(r2, r1)

    def test_lower_eth_price_lower_max_gwei(self):
        # Higher ETH price means each gwei costs more USD, so max allowed gwei is LOWER
        # eth=4000 → max_gwei = 31.25; eth=2000 → max_gwei = 62.5
        r1 = self.opt.optimal_gas_price(5, "AAVE_DEPOSIT", 4000, 10000, 0.05)
        r2 = self.opt.optimal_gas_price(5, "AAVE_DEPOSIT", 2000, 10000, 0.05)
        self.assertLess(r1, r2)  # higher ETH price → lower max gwei (each gwei is worth more)

    def test_negative_apy_returns_zero(self):
        result = self.opt.optimal_gas_price(5, "AAVE_DEPOSIT", 2000, 10000, -0.01)
        self.assertEqual(result, 0.0)

    def test_unknown_op_uses_default_200000(self):
        r_known = self.opt.optimal_gas_price(5, "AAVE_DEPOSIT", 2000, 10000, 0.05)
        r_unknown = self.opt.optimal_gas_price(5, "MYSTERY_OP", 2000, 10000, 0.05)
        self.assertAlmostEqual(r_known, r_unknown, places=4)

    def test_larger_capital_higher_max_gwei(self):
        r1 = self.opt.optimal_gas_price(5, "AAVE_DEPOSIT", 2000, 10000, 0.05)
        r2 = self.opt.optimal_gas_price(5, "AAVE_DEPOSIT", 2000, 100000, 0.05)
        self.assertGreater(r2, r1)


# ===========================================================================
# 10. save_estimates + load_history
# ===========================================================================

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = _make_optimizer(self.tmp)

    def _make_estimate(self, **kwargs) -> GasEstimate:
        return _simple_estimate(self.opt, **kwargs)

    def test_save_creates_file(self):
        e = self._make_estimate()
        self.opt.save_estimates([e])
        self.assertTrue(self.opt.data_file.exists())

    def test_load_history_missing_file_returns_empty(self):
        result = self.opt.load_history()
        self.assertEqual(result, [])

    def test_saved_entry_has_required_keys(self):
        e = self._make_estimate()
        self.opt.save_estimates([e])
        history = self.opt.load_history()
        self.assertEqual(len(history), 1)
        entry = history[0]
        for key in ("timestamp", "operation", "gas_cost_usd", "verdict", "break_even_days"):
            self.assertIn(key, entry)

    def test_inf_break_even_stored_as_minus_one(self):
        e = self._make_estimate(expected_apy=0.0)  # yield=0 → inf
        self.opt.save_estimates([e])
        history = self.opt.load_history()
        self.assertEqual(history[0]["break_even_days"], -1)

    def test_finite_break_even_stored_as_number(self):
        e = self._make_estimate()
        self.opt.save_estimates([e])
        history = self.opt.load_history()
        be = history[0]["break_even_days"]
        self.assertIsInstance(be, (int, float))
        self.assertNotEqual(be, -1)

    def test_verdict_stored_correctly(self):
        e = self._make_estimate()
        self.opt.save_estimates([e])
        history = self.opt.load_history()
        self.assertIn(history[0]["verdict"],
                      ("EFFICIENT", "MARGINAL", "EXPENSIVE", "PROHIBITIVE"))

    def test_ring_buffer_caps_at_max_entries(self):
        # Fill slightly above MAX_ENTRIES
        for _ in range(MAX_ENTRIES + 10):
            e = self._make_estimate()
            self.opt.save_estimates([e])
        history = self.opt.load_history()
        self.assertLessEqual(len(history), MAX_ENTRIES)

    def test_ring_buffer_exactly_max(self):
        for i in range(MAX_ENTRIES):
            e = self._make_estimate()
            self.opt.save_estimates([e])
        history = self.opt.load_history()
        self.assertEqual(len(history), MAX_ENTRIES)

    def test_atomic_write_no_tmp_left_behind(self):
        e = self._make_estimate()
        self.opt.save_estimates([e])
        tmp_path = self.opt.data_file.with_suffix(".tmp")
        self.assertFalse(tmp_path.exists())

    def test_multiple_saves_append(self):
        for _ in range(3):
            e = self._make_estimate()
            self.opt.save_estimates([e])
        history = self.opt.load_history()
        self.assertEqual(len(history), 3)

    def test_save_batch_of_estimates(self):
        estimates = [self._make_estimate() for _ in range(5)]
        self.opt.save_estimates(estimates)
        history = self.opt.load_history()
        self.assertEqual(len(history), 5)

    def test_file_is_valid_json(self):
        e = self._make_estimate()
        self.opt.save_estimates([e])
        content = self.opt.data_file.read_text()
        parsed = json.loads(content)
        self.assertIsInstance(parsed, list)

    def test_load_corrupt_file_returns_empty(self):
        self.opt.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.opt.data_file.write_text("NOT JSON {{{{")
        result = self.opt.load_history()
        self.assertEqual(result, [])

    def test_operation_field_in_history(self):
        e = self._make_estimate(operation="PENDLE_SWAP")
        self.opt.save_estimates([e])
        history = self.opt.load_history()
        self.assertEqual(history[0]["operation"], "PENDLE_SWAP")

    def test_timestamp_is_numeric(self):
        e = self._make_estimate()
        self.opt.save_estimates([e])
        history = self.opt.load_history()
        self.assertIsInstance(history[0]["timestamp"], (int, float))

    def test_gas_cost_usd_in_history(self):
        e = self._make_estimate()
        self.opt.save_estimates([e])
        history = self.opt.load_history()
        self.assertAlmostEqual(history[0]["gas_cost_usd"], e.gas_cost_usd, places=4)


# ===========================================================================
# 11. GAS_ESTIMATES registry sanity
# ===========================================================================

class TestGasEstimatesRegistry(unittest.TestCase):

    def test_all_expected_ops_present(self):
        expected = {
            "ERC20_TRANSFER", "AAVE_DEPOSIT", "AAVE_WITHDRAW",
            "COMPOUND_SUPPLY", "CURVE_SWAP", "UNISWAP_V3_SWAP",
            "MORPHO_SUPPLY", "PENDLE_SWAP", "GENERIC_APPROVE",
        }
        self.assertTrue(expected.issubset(set(GAS_ESTIMATES.keys())))

    def test_all_values_positive_ints(self):
        for op, units in GAS_ESTIMATES.items():
            self.assertIsInstance(units, int, msg=f"{op} should be int")
            self.assertGreater(units, 0, msg=f"{op} should be >0")

    def test_max_entries_is_100(self):
        self.assertEqual(MAX_ENTRIES, 100)


if __name__ == "__main__":
    unittest.main()
