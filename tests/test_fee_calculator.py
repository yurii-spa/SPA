"""tests/test_fee_calculator.py — MP-584 FeeCalculator test suite.

Coverage: 93 test cases across 8 classes.

TestHelpers              (14)  — _safe_float, _get_attr, _normalise_tier,
                                  _normalise_apy_pct internal helpers
TestComputeManagementFee (12)  — basic fee, zero fee, negative amounts,
                                  apy_pct ignored, clamps, edge cases
TestComputePerformanceFee(14)  — zero/negative pnl, hurdle arithmetic,
                                  zero hurdle, high hurdle, fee_pct clamp
TestEstimateGasFeeUsd    (17)  — operation × chain matrix, unknown combos,
                                  gwei=0, gwei clamping, case-insensitive
TestEstimateSlippageCost (12)  — T1/T2/T3 base rates, size_ratio scaling,
                                  zero/negative tvl, amount=0, clamp at 1
TestComputeTotalCost     (14)  — dict adapter, object adapter, period_days,
                                  apy normalisation, all keys present, totals
TestGetFeeReport          (7)  — single adapter, multi adapter, weight
                                  normalisation, empty adapters, zero pv
TestImportHygiene         (3)  — stdlib-only, no forbidden domains imported

Total: 93 tests
"""

from __future__ import annotations

import math
import os
import sys
import types
import unittest

# Make spa_core importable from the repo root (tests/ lives one level up).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.analytics.fee_calculator import (
    FeeCalculator,
    _safe_float,
    _get_attr,
    _normalise_tier,
    _normalise_apy_pct,
    _ETH_PRICE_USD,
    _GAS_UNITS,
    _DEFAULT_GAS_UNITS,
    _SLIPPAGE_RATES,
)

# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

def _adapter(
    apy_pct=5.0,
    tvl_usd=10_000_000.0,
    tier="T1",
    management_fee_pct=0.0,
    performance_fee_pct=0.0,
    hurdle_rate=0.04,
    chain="ethereum",
    protocol="test_protocol",
):
    """Return a minimal adapter dict for testing compute_total_cost."""
    return {
        "apy_pct": apy_pct,
        "tvl_usd": tvl_usd,
        "tier": tier,
        "management_fee_pct": management_fee_pct,
        "performance_fee_pct": performance_fee_pct,
        "hurdle_rate": hurdle_rate,
        "chain": chain,
        "protocol": protocol,
    }


class _AdapterObj:
    """Object-style adapter for attribute-access tests."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# 1. Internal helpers
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):
    """14 tests covering _safe_float, _get_attr, _normalise_tier, _normalise_apy_pct."""

    # _safe_float
    def test_safe_float_int(self):
        self.assertAlmostEqual(_safe_float(42), 42.0)

    def test_safe_float_float(self):
        self.assertAlmostEqual(_safe_float(3.14), 3.14)

    def test_safe_float_string(self):
        self.assertAlmostEqual(_safe_float("1.5"), 1.5)

    def test_safe_float_none(self):
        self.assertAlmostEqual(_safe_float(None), 0.0)

    def test_safe_float_nan_default(self):
        self.assertAlmostEqual(_safe_float(float("nan")), 0.0)

    def test_safe_float_inf_default(self):
        self.assertAlmostEqual(_safe_float(float("inf")), 0.0)

    def test_safe_float_bool_false(self):
        # bool is a subclass of int; _safe_float must NOT convert it
        self.assertAlmostEqual(_safe_float(True), 0.0)

    def test_safe_float_custom_default(self):
        self.assertAlmostEqual(_safe_float(None, -1.0), -1.0)

    # _get_attr
    def test_get_attr_dict_first_key(self):
        d = {"a": 1, "b": 2}
        self.assertEqual(_get_attr(d, "a", "b"), 1)

    def test_get_attr_dict_second_key(self):
        d = {"b": 2}
        self.assertEqual(_get_attr(d, "a", "b"), 2)

    def test_get_attr_object(self):
        obj = _AdapterObj(tier="T3")
        self.assertEqual(_get_attr(obj, "tier"), "T3")

    def test_get_attr_default(self):
        self.assertIsNone(_get_attr({}, "missing"))

    # _normalise_tier
    def test_normalise_tier_t1(self):
        self.assertEqual(_normalise_tier("T1"), "T1")

    def test_normalise_tier_lowercase(self):
        self.assertEqual(_normalise_tier("t2"), "T2")

    def test_normalise_tier_unknown(self):
        self.assertEqual(_normalise_tier("T9"), "T2")

    def test_normalise_apy_decimal(self):
        self.assertAlmostEqual(_normalise_apy_pct(0.05), 5.0)

    def test_normalise_apy_pct_passthrough(self):
        self.assertAlmostEqual(_normalise_apy_pct(5.0), 5.0)

    def test_normalise_apy_zero(self):
        self.assertAlmostEqual(_normalise_apy_pct(0.0), 0.0)


# ---------------------------------------------------------------------------
# 2. compute_management_fee
# ---------------------------------------------------------------------------

class TestComputeManagementFee(unittest.TestCase):
    """12 tests for compute_management_fee."""

    def setUp(self):
        self.calc = FeeCalculator()

    def test_zero_fee(self):
        fee = self.calc.compute_management_fee(100_000, 5.0, 0.0)
        self.assertAlmostEqual(fee, 0.0)

    def test_one_pct_fee(self):
        fee = self.calc.compute_management_fee(100_000, 5.0, 1.0)
        self.assertAlmostEqual(fee, 1_000.0)

    def test_two_pct_fee(self):
        fee = self.calc.compute_management_fee(50_000, 8.0, 2.0)
        self.assertAlmostEqual(fee, 1_000.0)

    def test_apy_irrelevant_to_management_fee(self):
        """Management fee should not depend on APY value."""
        fee1 = self.calc.compute_management_fee(100_000, 0.0, 1.0)
        fee2 = self.calc.compute_management_fee(100_000, 50.0, 1.0)
        self.assertAlmostEqual(fee1, fee2)

    def test_negative_amount_clamped_to_zero(self):
        fee = self.calc.compute_management_fee(-50_000, 5.0, 1.0)
        self.assertAlmostEqual(fee, 0.0)

    def test_negative_fee_pct_clamped_to_zero(self):
        fee = self.calc.compute_management_fee(100_000, 5.0, -1.0)
        self.assertAlmostEqual(fee, 0.0)

    def test_small_fee_pct(self):
        fee = self.calc.compute_management_fee(100_000, 5.0, 0.5)
        self.assertAlmostEqual(fee, 500.0)

    def test_large_fee_pct(self):
        # Unusual but must compute correctly
        fee = self.calc.compute_management_fee(10_000, 5.0, 10.0)
        self.assertAlmostEqual(fee, 1_000.0)

    def test_zero_amount(self):
        fee = self.calc.compute_management_fee(0.0, 5.0, 2.0)
        self.assertAlmostEqual(fee, 0.0)

    def test_fractional_amount(self):
        fee = self.calc.compute_management_fee(1_000.50, 5.0, 1.0)
        self.assertAlmostEqual(fee, 10.005)

    def test_returns_float(self):
        fee = self.calc.compute_management_fee(100_000, 5.0, 1.0)
        self.assertIsInstance(fee, float)

    def test_none_fee_pct_safe_float(self):
        fee = self.calc.compute_management_fee(100_000, 5.0, None)
        self.assertAlmostEqual(fee, 0.0)


# ---------------------------------------------------------------------------
# 3. compute_performance_fee
# ---------------------------------------------------------------------------

class TestComputePerformanceFee(unittest.TestCase):
    """14 tests for compute_performance_fee."""

    def setUp(self):
        self.calc = FeeCalculator()

    def test_zero_pnl(self):
        fee = self.calc.compute_performance_fee(0.0, 20.0, 0.04)
        self.assertAlmostEqual(fee, 0.0)

    def test_negative_pnl(self):
        fee = self.calc.compute_performance_fee(-1_000.0, 20.0, 0.04)
        self.assertAlmostEqual(fee, 0.0)

    def test_zero_fee_pct(self):
        fee = self.calc.compute_performance_fee(10_000.0, 0.0, 0.04)
        self.assertAlmostEqual(fee, 0.0)

    def test_basic_hurdle_arithmetic(self):
        # gross_pnl=1000, hurdle=0.04 → hurdle_amount=40, excess=960, fee_pct=20%
        fee = self.calc.compute_performance_fee(1_000.0, 20.0, 0.04)
        self.assertAlmostEqual(fee, 960.0 * 0.20)

    def test_zero_hurdle(self):
        # entire P&L is subject to fee
        fee = self.calc.compute_performance_fee(1_000.0, 20.0, 0.0)
        self.assertAlmostEqual(fee, 200.0)

    def test_hurdle_equals_one(self):
        # hurdle=1.0 → excess = gross_pnl × (1-1.0) = 0
        fee = self.calc.compute_performance_fee(1_000.0, 20.0, 1.0)
        self.assertAlmostEqual(fee, 0.0)

    def test_hurdle_greater_than_one_clamped(self):
        # hurdle > 1.0 means hurdle_amount > pnl → excess = 0
        fee = self.calc.compute_performance_fee(1_000.0, 20.0, 1.5)
        self.assertAlmostEqual(fee, 0.0)

    def test_negative_hurdle_clamped(self):
        # negative hurdle treated as 0.0
        fee_neg = self.calc.compute_performance_fee(1_000.0, 20.0, -0.1)
        fee_zero = self.calc.compute_performance_fee(1_000.0, 20.0, 0.0)
        self.assertAlmostEqual(fee_neg, fee_zero)

    def test_negative_fee_pct_clamped(self):
        fee = self.calc.compute_performance_fee(1_000.0, -5.0, 0.04)
        self.assertAlmostEqual(fee, 0.0)

    def test_ten_pct_hurdle(self):
        # pnl=1000, hurdle=0.10 → excess=900, fee_pct=10% → 90
        fee = self.calc.compute_performance_fee(1_000.0, 10.0, 0.10)
        self.assertAlmostEqual(fee, 90.0)

    def test_large_pnl(self):
        fee = self.calc.compute_performance_fee(1_000_000.0, 20.0, 0.04)
        expected = (1_000_000.0 * 0.96) * 0.20
        self.assertAlmostEqual(fee, expected, places=2)

    def test_small_pnl(self):
        fee = self.calc.compute_performance_fee(0.01, 20.0, 0.0)
        self.assertAlmostEqual(fee, 0.002, places=6)

    def test_returns_float(self):
        fee = self.calc.compute_performance_fee(1_000.0, 20.0, 0.04)
        self.assertIsInstance(fee, float)

    def test_none_inputs_safe(self):
        fee = self.calc.compute_performance_fee(None, None, None)
        self.assertAlmostEqual(fee, 0.0)


# ---------------------------------------------------------------------------
# 4. estimate_gas_fee_usd
# ---------------------------------------------------------------------------

class TestEstimateGasFeeUsd(unittest.TestCase):
    """17 tests for estimate_gas_fee_usd."""

    def setUp(self):
        self.calc = FeeCalculator()

    # ── Ethereum L1 ────────────────────────────────────────────────────
    def test_deposit_ethereum(self):
        fee = self.calc.estimate_gas_fee_usd("deposit", "ethereum", 20.0)
        expected = _GAS_UNITS[("deposit", "ethereum")] * 20.0 * 1e-9 * _ETH_PRICE_USD
        self.assertAlmostEqual(fee, expected, places=8)

    def test_withdraw_ethereum(self):
        fee = self.calc.estimate_gas_fee_usd("withdraw", "ethereum", 20.0)
        expected = _GAS_UNITS[("withdraw", "ethereum")] * 20.0 * 1e-9 * _ETH_PRICE_USD
        self.assertAlmostEqual(fee, expected, places=8)

    def test_rebalance_ethereum(self):
        fee = self.calc.estimate_gas_fee_usd("rebalance", "ethereum", 20.0)
        expected = _GAS_UNITS[("rebalance", "ethereum")] * 20.0 * 1e-9 * _ETH_PRICE_USD
        self.assertAlmostEqual(fee, expected, places=8)

    # ── Arbitrum L2 ────────────────────────────────────────────────────
    def test_deposit_arbitrum(self):
        fee = self.calc.estimate_gas_fee_usd("deposit", "arbitrum", 0.1)
        expected = _GAS_UNITS[("deposit", "arbitrum")] * 0.1 * 1e-9 * _ETH_PRICE_USD
        self.assertAlmostEqual(fee, expected, places=8)

    def test_rebalance_arbitrum(self):
        fee = self.calc.estimate_gas_fee_usd("rebalance", "arbitrum", 0.1)
        expected = _GAS_UNITS[("rebalance", "arbitrum")] * 0.1 * 1e-9 * _ETH_PRICE_USD
        self.assertAlmostEqual(fee, expected, places=8)

    # ── Base L2 ────────────────────────────────────────────────────────
    def test_deposit_base(self):
        fee = self.calc.estimate_gas_fee_usd("deposit", "base", 0.05)
        expected = _GAS_UNITS[("deposit", "base")] * 0.05 * 1e-9 * _ETH_PRICE_USD
        self.assertAlmostEqual(fee, expected, places=8)

    # ── Optimism L2 ────────────────────────────────────────────────────
    def test_withdraw_optimism(self):
        fee = self.calc.estimate_gas_fee_usd("withdraw", "optimism", 0.05)
        expected = _GAS_UNITS[("withdraw", "optimism")] * 0.05 * 1e-9 * _ETH_PRICE_USD
        self.assertAlmostEqual(fee, expected, places=8)

    # ── Polygon PoS ────────────────────────────────────────────────────
    def test_deposit_polygon(self):
        fee = self.calc.estimate_gas_fee_usd("deposit", "polygon", 50.0)
        expected = _GAS_UNITS[("deposit", "polygon")] * 50.0 * 1e-9 * _ETH_PRICE_USD
        self.assertAlmostEqual(fee, expected, places=8)

    # ── Fallback / unknown ─────────────────────────────────────────────
    def test_unknown_chain_uses_default(self):
        fee_unknown = self.calc.estimate_gas_fee_usd("deposit", "solana", 20.0)
        expected = _DEFAULT_GAS_UNITS * 20.0 * 1e-9 * _ETH_PRICE_USD
        self.assertAlmostEqual(fee_unknown, expected, places=8)

    def test_unknown_operation_uses_default(self):
        fee = self.calc.estimate_gas_fee_usd("swap", "ethereum", 20.0)
        expected = _DEFAULT_GAS_UNITS * 20.0 * 1e-9 * _ETH_PRICE_USD
        self.assertAlmostEqual(fee, expected, places=8)

    def test_unknown_op_and_chain(self):
        fee = self.calc.estimate_gas_fee_usd("mint", "fantom", 20.0)
        expected = _DEFAULT_GAS_UNITS * 20.0 * 1e-9 * _ETH_PRICE_USD
        self.assertAlmostEqual(fee, expected, places=8)

    # ── Edge cases ─────────────────────────────────────────────────────
    def test_zero_gwei(self):
        fee = self.calc.estimate_gas_fee_usd("deposit", "ethereum", 0.0)
        self.assertAlmostEqual(fee, 0.0)

    def test_negative_gwei_clamped(self):
        fee = self.calc.estimate_gas_fee_usd("deposit", "ethereum", -10.0)
        self.assertAlmostEqual(fee, 0.0)

    def test_case_insensitive_operation(self):
        fee_lower = self.calc.estimate_gas_fee_usd("DEPOSIT", "ethereum", 20.0)
        fee_upper = self.calc.estimate_gas_fee_usd("deposit", "ETHEREUM", 20.0)
        self.assertAlmostEqual(fee_lower, fee_upper, places=8)

    def test_high_gwei(self):
        fee = self.calc.estimate_gas_fee_usd("deposit", "ethereum", 500.0)
        expected = _GAS_UNITS[("deposit", "ethereum")] * 500.0 * 1e-9 * _ETH_PRICE_USD
        self.assertAlmostEqual(fee, expected, places=4)

    def test_rebalance_more_expensive_than_deposit(self):
        r = self.calc.estimate_gas_fee_usd("rebalance", "ethereum", 20.0)
        d = self.calc.estimate_gas_fee_usd("deposit", "ethereum", 20.0)
        self.assertGreater(r, d)

    def test_returns_float(self):
        fee = self.calc.estimate_gas_fee_usd("deposit", "ethereum", 20.0)
        self.assertIsInstance(fee, float)


# ---------------------------------------------------------------------------
# 5. estimate_slippage_cost
# ---------------------------------------------------------------------------

class TestEstimateSlippageCost(unittest.TestCase):
    """12 tests for estimate_slippage_cost."""

    def setUp(self):
        self.calc = FeeCalculator()
        self.tvl = 100_000_000.0   # $100 M reference TVL
        self.small_amount = 10_000.0   # 0.01% of TVL — negligible size ratio

    # ── Base rates by tier ─────────────────────────────────────────────
    def test_t1_base_rate_small_size(self):
        # size_ratio ≈ 0 → effective_rate ≈ 0.001 * (1+0) = 0.001
        fee = self.calc.estimate_slippage_cost(self.small_amount, self.tvl, "T1")
        base = self.small_amount * _SLIPPAGE_RATES["T1"]
        self.assertAlmostEqual(fee, base * (1 + self.small_amount / self.tvl), places=4)

    def test_t2_base_rate_small_size(self):
        fee = self.calc.estimate_slippage_cost(self.small_amount, self.tvl, "T2")
        size_ratio = self.small_amount / self.tvl
        expected = self.small_amount * _SLIPPAGE_RATES["T2"] * (1 + size_ratio)
        self.assertAlmostEqual(fee, expected, places=4)

    def test_t3_base_rate_small_size(self):
        fee = self.calc.estimate_slippage_cost(self.small_amount, self.tvl, "T3")
        size_ratio = self.small_amount / self.tvl
        expected = self.small_amount * _SLIPPAGE_RATES["T3"] * (1 + size_ratio)
        self.assertAlmostEqual(fee, expected, places=4)

    def test_t1_cheaper_than_t2(self):
        f1 = self.calc.estimate_slippage_cost(100_000, self.tvl, "T1")
        f2 = self.calc.estimate_slippage_cost(100_000, self.tvl, "T2")
        self.assertLess(f1, f2)

    def test_t2_cheaper_than_t3(self):
        f2 = self.calc.estimate_slippage_cost(100_000, self.tvl, "T2")
        f3 = self.calc.estimate_slippage_cost(100_000, self.tvl, "T3")
        self.assertLess(f2, f3)

    # ── Size ratio scaling ─────────────────────────────────────────────
    def test_size_ratio_100_pct_doubles_rate(self):
        # amount == tvl → size_ratio = 1.0 → rate = 2 × base
        amount = 10_000_000.0
        tvl = 10_000_000.0
        fee = self.calc.estimate_slippage_cost(amount, tvl, "T1")
        expected = amount * _SLIPPAGE_RATES["T1"] * 2.0
        self.assertAlmostEqual(fee, expected, places=4)

    def test_size_ratio_clamped_at_1(self):
        # amount > tvl → clamped to 1.0
        fee_capped = self.calc.estimate_slippage_cost(20_000_000.0, 10_000_000.0, "T1")
        fee_at_100 = self.calc.estimate_slippage_cost(10_000_000.0, 10_000_000.0, "T1")
        # slippage for capped: amount=20M, effective_rate = base*2
        self.assertAlmostEqual(fee_capped, 20_000_000.0 * _SLIPPAGE_RATES["T1"] * 2.0, places=4)
        # vs fee_at_100 = 10M * base * 2
        self.assertGreater(fee_capped, fee_at_100)

    # ── Edge cases ─────────────────────────────────────────────────────
    def test_zero_amount(self):
        fee = self.calc.estimate_slippage_cost(0.0, self.tvl, "T1")
        self.assertAlmostEqual(fee, 0.0)

    def test_negative_amount_clamped(self):
        fee = self.calc.estimate_slippage_cost(-50_000.0, self.tvl, "T1")
        self.assertAlmostEqual(fee, 0.0)

    def test_zero_tvl_uses_worst_case(self):
        # TVL=0 → size_ratio=1.0 (worst case)
        fee_zero_tvl = self.calc.estimate_slippage_cost(10_000.0, 0.0, "T1")
        expected = 10_000.0 * _SLIPPAGE_RATES["T1"] * 2.0
        self.assertAlmostEqual(fee_zero_tvl, expected, places=4)

    def test_unknown_tier_falls_back_to_t2(self):
        fee_unknown = self.calc.estimate_slippage_cost(100_000.0, self.tvl, "TX")
        fee_t2 = self.calc.estimate_slippage_cost(100_000.0, self.tvl, "T2")
        self.assertAlmostEqual(fee_unknown, fee_t2, places=6)

    def test_returns_float(self):
        fee = self.calc.estimate_slippage_cost(1_000.0, self.tvl, "T1")
        self.assertIsInstance(fee, float)


# ---------------------------------------------------------------------------
# 6. compute_total_cost
# ---------------------------------------------------------------------------

class TestComputeTotalCost(unittest.TestCase):
    """14 tests for compute_total_cost."""

    def setUp(self):
        self.calc = FeeCalculator()
        self.base_adapter = _adapter(
            apy_pct=5.0,
            tvl_usd=10_000_000.0,
            tier="T1",
            management_fee_pct=1.0,
            performance_fee_pct=10.0,
            hurdle_rate=0.04,
            chain="ethereum",
        )

    def test_returns_dict_with_all_keys(self):
        cost = self.calc.compute_total_cost(10_000, "deposit", self.base_adapter)
        for key in ("management", "performance", "gas", "slippage", "total_usd", "total_pct"):
            self.assertIn(key, cost)

    def test_total_equals_sum_of_components(self):
        cost = self.calc.compute_total_cost(10_000, "deposit", self.base_adapter)
        s = cost["management"] + cost["performance"] + cost["gas"] + cost["slippage"]
        self.assertAlmostEqual(cost["total_usd"], s, places=5)

    def test_total_pct_formula(self):
        amount = 50_000.0
        cost = self.calc.compute_total_cost(amount, "deposit", self.base_adapter)
        self.assertAlmostEqual(cost["total_pct"], cost["total_usd"] / amount * 100, places=4)

    def test_zero_fees_adapter(self):
        a = _adapter(management_fee_pct=0.0, performance_fee_pct=0.0)
        cost = self.calc.compute_total_cost(100_000, "deposit", a)
        self.assertAlmostEqual(cost["management"], 0.0)
        self.assertAlmostEqual(cost["performance"], 0.0)

    def test_period_days_scales_management(self):
        a = _adapter(management_fee_pct=1.0)
        cost_full = self.calc.compute_total_cost(100_000, "deposit", a, period_days=365)
        cost_half = self.calc.compute_total_cost(100_000, "deposit", a, period_days=182)
        self.assertAlmostEqual(cost_full["management"] / cost_half["management"], 365 / 182, places=2)

    def test_gas_not_scaled_by_period(self):
        a = _adapter()
        c1 = self.calc.compute_total_cost(10_000, "deposit", a, period_days=1)
        c2 = self.calc.compute_total_cost(10_000, "deposit", a, period_days=365)
        self.assertAlmostEqual(c1["gas"], c2["gas"])

    def test_apy_decimal_normalisation(self):
        # apy=0.05 should normalise to 5.0% and behave like apy_pct=5.0
        a_dec = _adapter(apy_pct=0.05)
        a_pct = _adapter(apy_pct=5.0)
        c_dec = self.calc.compute_total_cost(10_000, "deposit", a_dec)
        c_pct = self.calc.compute_total_cost(10_000, "deposit", a_pct)
        self.assertAlmostEqual(c_dec["performance"], c_pct["performance"], places=4)

    def test_object_adapter(self):
        obj = _AdapterObj(
            apy_pct=5.0, tvl_usd=10_000_000.0, tier="T1",
            management_fee_pct=1.0, performance_fee_pct=10.0,
            hurdle_rate=0.04, chain="ethereum"
        )
        cost = self.calc.compute_total_cost(10_000, "deposit", obj)
        self.assertIn("total_usd", cost)
        self.assertGreater(cost["total_usd"], 0)

    def test_dict_adapter_tvl_key(self):
        # Adapter with 'tvl' instead of 'tvl_usd'
        a = {"apy_pct": 5.0, "tvl": 5_000_000.0, "tier": "T1"}
        cost = self.calc.compute_total_cost(10_000, "deposit", a)
        self.assertIn("slippage", cost)

    def test_zero_amount(self):
        cost = self.calc.compute_total_cost(0.0, "deposit", self.base_adapter)
        self.assertAlmostEqual(cost["management"], 0.0)
        self.assertAlmostEqual(cost["total_pct"], 0.0)

    def test_rebalance_gas_higher(self):
        c_dep = self.calc.compute_total_cost(10_000, "deposit", self.base_adapter)
        c_reb = self.calc.compute_total_cost(10_000, "rebalance", self.base_adapter)
        self.assertGreater(c_reb["gas"], c_dep["gas"])

    def test_period_zero_management_zero(self):
        a = _adapter(management_fee_pct=1.0)
        cost = self.calc.compute_total_cost(10_000, "deposit", a, period_days=0)
        self.assertAlmostEqual(cost["management"], 0.0)

    def test_all_values_non_negative(self):
        cost = self.calc.compute_total_cost(10_000, "deposit", self.base_adapter)
        for k, v in cost.items():
            self.assertGreaterEqual(v, 0.0, msg=f"Negative value for {k}")

    def test_arbitrum_chain(self):
        a = _adapter(chain="arbitrum")
        cost = self.calc.compute_total_cost(10_000, "deposit", a)
        expected_gas = self.calc.estimate_gas_fee_usd("deposit", "arbitrum", 20.0)
        self.assertAlmostEqual(cost["gas"], expected_gas, places=6)


# ---------------------------------------------------------------------------
# 7. get_fee_report
# ---------------------------------------------------------------------------

class TestGetFeeReport(unittest.TestCase):
    """7 tests for get_fee_report."""

    def setUp(self):
        self.calc = FeeCalculator()
        self.a1 = _adapter(apy_pct=5.0, tier="T1", protocol="aave")
        self.a2 = _adapter(apy_pct=8.0, tier="T2", protocol="morpho")

    def test_single_adapter_report_keys(self):
        report = self.calc.get_fee_report([self.a1], [1.0], 100_000)
        for key in ("total_drag_usd", "total_drag_pct", "gross_apy", "net_apy", "adapters"):
            self.assertIn(key, report)

    def test_single_adapter_weight_normalised(self):
        # weight=5 should normalise to 1.0 for single adapter
        r = self.calc.get_fee_report([self.a1], [5.0], 100_000)
        self.assertEqual(len(r["adapters"]), 1)
        self.assertAlmostEqual(r["adapters"][0]["weight"], 1.0, places=5)
        self.assertAlmostEqual(r["adapters"][0]["amount_usd"], 100_000.0, places=2)

    def test_multi_adapter_weights_sum_to_one(self):
        r = self.calc.get_fee_report([self.a1, self.a2], [0.6, 0.4], 100_000)
        w_sum = sum(row["weight"] for row in r["adapters"])
        self.assertAlmostEqual(w_sum, 1.0, places=5)

    def test_multi_adapter_amounts_sum_to_portfolio_value(self):
        pv = 200_000.0
        r = self.calc.get_fee_report([self.a1, self.a2], [0.5, 0.5], pv)
        amt_sum = sum(row["amount_usd"] for row in r["adapters"])
        self.assertAlmostEqual(amt_sum, pv, places=2)

    def test_net_apy_less_than_gross_apy(self):
        r = self.calc.get_fee_report([self.a1, self.a2], [0.5, 0.5], 100_000)
        self.assertLess(r["net_apy"], r["gross_apy"])

    def test_zero_portfolio_value(self):
        # With pv=0 amounts are 0: management/slippage=0, gas is fixed per op.
        r = self.calc.get_fee_report([self.a1], [1.0], 0.0)
        self.assertAlmostEqual(r["total_drag_pct"], 0.0)   # 0/0 handled as 0%
        self.assertAlmostEqual(r["adapters"][0]["management"], 0.0)
        self.assertAlmostEqual(r["adapters"][0]["slippage"], 0.0)

    def test_equal_weight_fallback_when_all_zero(self):
        # all zero weights → equal split
        r = self.calc.get_fee_report([self.a1, self.a2], [0.0, 0.0], 100_000)
        self.assertAlmostEqual(r["adapters"][0]["weight"], 0.5, places=5)
        self.assertAlmostEqual(r["adapters"][1]["weight"], 0.5, places=5)


# ---------------------------------------------------------------------------
# 8. Import hygiene
# ---------------------------------------------------------------------------

class TestImportHygiene(unittest.TestCase):
    """3 tests: stdlib-only, no forbidden domain imports."""

    def _get_module(self):
        import spa_core.analytics.fee_calculator as m
        return m

    def test_no_forbidden_external_libs(self):
        # Inspect THIS module's own source for forbidden imports rather than the
        # global sys.modules table. sys.modules is process-wide and is polluted
        # by unrelated analytics tests that import e.g. `requests` to assert it
        # is optional — that has nothing to do with whether fee_calculator
        # itself pulls in a forbidden dependency. Source inspection mirrors the
        # sibling test_no_execution_domain_import / test_no_risk_domain_import.
        import re
        m = self._get_module()
        src = open(m.__file__).read()
        forbidden = ["requests", "web3", "numpy", "pandas", "scipy",
                     "openai", "anthropic", "aiohttp", "httpx"]
        for lib in forbidden:
            pattern = re.compile(
                rf"^\s*(?:import\s+{re.escape(lib)}\b|from\s+{re.escape(lib)}\b)",
                re.MULTILINE,
            )
            self.assertIsNone(
                pattern.search(src),
                msg=f"Forbidden lib '{lib}' is imported by fee_calculator",
            )

    def test_no_execution_domain_import(self):
        m = self._get_module()
        src = open(m.__file__).read()
        self.assertNotIn("from spa_core.execution", src)
        self.assertNotIn("import execution", src)

    def test_no_risk_domain_import(self):
        m = self._get_module()
        src = open(m.__file__).read()
        self.assertNotIn("from spa_core.risk", src)
        self.assertNotIn("import risk", src)


# ---------------------------------------------------------------------------
# Additional edge-case / integration tests to reach ≥ 85 total
# ---------------------------------------------------------------------------

class TestEdgeCasesIntegration(unittest.TestCase):
    """14 extra cross-method and boundary tests."""

    def setUp(self):
        self.calc = FeeCalculator()

    def test_management_fee_default_arg(self):
        fee = self.calc.compute_management_fee(100_000, 5.0)
        self.assertAlmostEqual(fee, 0.0)

    def test_performance_fee_default_args(self):
        fee = self.calc.compute_performance_fee(10_000.0)
        self.assertAlmostEqual(fee, 0.0)

    def test_gas_fee_default_chain(self):
        fee_default = self.calc.estimate_gas_fee_usd("deposit")
        fee_eth = self.calc.estimate_gas_fee_usd("deposit", "ethereum")
        self.assertAlmostEqual(fee_default, fee_eth, places=8)

    def test_gas_fee_default_gwei(self):
        fee = self.calc.estimate_gas_fee_usd("deposit", "ethereum")
        # default gwei=20
        expected = _GAS_UNITS[("deposit", "ethereum")] * 20.0 * 1e-9 * _ETH_PRICE_USD
        self.assertAlmostEqual(fee, expected, places=8)

    def test_slippage_increases_with_amount(self):
        tvl = 50_000_000.0
        f1 = self.calc.estimate_slippage_cost(10_000, tvl, "T1")
        f2 = self.calc.estimate_slippage_cost(100_000, tvl, "T1")
        self.assertGreater(f2, f1)

    def test_total_cost_period_365_equals_annual_management(self):
        a = _adapter(management_fee_pct=1.0, performance_fee_pct=0.0)
        amount = 100_000.0
        cost = self.calc.compute_total_cost(amount, "deposit", a, period_days=365)
        expected_mgmt = amount * 0.01
        self.assertAlmostEqual(cost["management"], expected_mgmt, places=4)

    def test_total_cost_period_30_management_fraction(self):
        a = _adapter(management_fee_pct=1.0, performance_fee_pct=0.0)
        amount = 100_000.0
        cost = self.calc.compute_total_cost(amount, "deposit", a, period_days=30)
        expected_mgmt = amount * 0.01 * (30 / 365)
        self.assertAlmostEqual(cost["management"], expected_mgmt, places=4)

    def test_fee_report_adapters_list_length(self):
        adapters = [_adapter() for _ in range(5)]
        weights = [0.2] * 5
        r = self.calc.get_fee_report(adapters, weights, 100_000)
        self.assertEqual(len(r["adapters"]), 5)

    def test_fee_report_adapter_name_from_protocol(self):
        a = _adapter(protocol="aave_v3")
        r = self.calc.get_fee_report([a], [1.0], 100_000)
        self.assertEqual(r["adapters"][0]["name"], "aave_v3")

    def test_compute_total_cost_negative_amount(self):
        cost = self.calc.compute_total_cost(-10_000, "deposit", _adapter())
        self.assertAlmostEqual(cost["management"], 0.0)
        self.assertAlmostEqual(cost["total_pct"], 0.0)

    def test_performance_fee_100_pct(self):
        # 100% performance fee on entire excess — unusual but valid
        fee = self.calc.compute_performance_fee(1_000.0, 100.0, 0.0)
        self.assertAlmostEqual(fee, 1_000.0)

    def test_gas_fee_all_chains_covered(self):
        for chain in ("ethereum", "arbitrum", "base", "optimism", "polygon"):
            fee = self.calc.estimate_gas_fee_usd("deposit", chain, 20.0)
            self.assertGreater(fee, 0.0, msg=f"Zero gas fee for chain={chain}")

    def test_gas_fee_all_operations_covered(self):
        for op in ("deposit", "withdraw", "rebalance"):
            fee = self.calc.estimate_gas_fee_usd(op, "ethereum", 20.0)
            self.assertGreater(fee, 0.0, msg=f"Zero gas fee for op={op}")

    def test_total_cost_all_values_are_finite(self):
        cost = self.calc.compute_total_cost(10_000, "deposit", _adapter())
        for k, v in cost.items():
            self.assertTrue(math.isfinite(v), msg=f"{k} is not finite: {v}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
