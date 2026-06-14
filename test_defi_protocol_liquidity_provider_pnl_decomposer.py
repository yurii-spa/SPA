"""
Tests for MP-1084: DeFiProtocolLiquidityProviderPnlDecomposer
Run with: python3 -m unittest spa_core.tests.test_defi_protocol_liquidity_provider_pnl_decomposer
"""

import json
import math
import os
import sys
import tempfile
import unittest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_liquidity_provider_pnl_decomposer import (
    DeFiProtocolLiquidityProviderPnlDecomposer,
    VALID_POOL_TYPES,
    STABLE_SWAP_IL_MULTIPLIER,
    LOG_CAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_pos(**overrides):
    """Return a minimal valid position dict."""
    pos = {
        "pool_name":            "TEST/USDC",
        "entry_price_a":        1.0,
        "entry_price_b":        1.0,
        "current_price_a":      1.0,
        "current_price_b":      1.0,
        "initial_position_usd": 10_000.0,
        "fee_income_usd":       0.0,
        "days_held":            30.0,
        "pool_type":            "constant_product",
        "concentration_factor": 1.0,
    }
    pos.update(overrides)
    return pos


def _make_decomposer(tmp_dir):
    log_file = os.path.join(tmp_dir, "lp_pnl_test.json")
    return DeFiProtocolLiquidityProviderPnlDecomposer(log_file=log_file), log_file


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestResultStructure(unittest.TestCase):
    """Verify that analyze() returns a dict with all expected keys."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d, _ = _make_decomposer(self.tmp)

    def test_all_keys_present(self):
        r = self.d.analyze(_base_pos())
        expected_keys = {
            "pool_name", "pool_type", "days_held",
            "hodl_value_usd", "lp_value_usd",
            "impermanent_loss_usd", "impermanent_loss_pct",
            "fee_income_usd", "fee_income_pct",
            "net_lp_value_usd", "net_vs_hodl_pct",
            "pnl_label", "analyzed_at",
        }
        self.assertEqual(expected_keys, set(r.keys()))

    def test_pool_name_preserved(self):
        r = self.d.analyze(_base_pos(pool_name="ETH/USDC"))
        self.assertEqual(r["pool_name"], "ETH/USDC")

    def test_pool_type_preserved(self):
        r = self.d.analyze(_base_pos(pool_type="stable_swap"))
        self.assertEqual(r["pool_type"], "stable_swap")

    def test_days_held_preserved(self):
        r = self.d.analyze(_base_pos(days_held=90.0))
        self.assertEqual(r["days_held"], 90.0)

    def test_analyzed_at_is_string(self):
        r = self.d.analyze(_base_pos())
        self.assertIsInstance(r["analyzed_at"], str)
        self.assertIn("T", r["analyzed_at"])

    def test_pnl_label_is_valid(self):
        valid_labels = {
            "LP_CRUSHING_HODL", "LP_BEATING_HODL",
            "NEUTRAL", "LP_LAGGING_HODL", "SEVERE_LP_UNDERPERFORMANCE",
        }
        r = self.d.analyze(_base_pos())
        self.assertIn(r["pnl_label"], valid_labels)


class TestNoChangeScenario(unittest.TestCase):
    """When prices don't change, IL = 0 and LP value = HODL value."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d, _ = _make_decomposer(self.tmp)

    def test_hodl_equals_initial_no_change(self):
        r = self.d.analyze(_base_pos())
        self.assertAlmostEqual(r["hodl_value_usd"], 10_000.0, places=4)

    def test_lp_equals_hodl_no_change(self):
        r = self.d.analyze(_base_pos())
        self.assertAlmostEqual(r["lp_value_usd"], r["hodl_value_usd"], places=4)

    def test_il_usd_zero_no_change(self):
        r = self.d.analyze(_base_pos())
        self.assertAlmostEqual(r["impermanent_loss_usd"], 0.0, places=4)

    def test_il_pct_zero_no_change(self):
        r = self.d.analyze(_base_pos())
        self.assertAlmostEqual(r["impermanent_loss_pct"], 0.0, places=4)

    def test_net_vs_hodl_zero_no_fees(self):
        r = self.d.analyze(_base_pos())
        self.assertAlmostEqual(r["net_vs_hodl_pct"], 0.0, places=4)

    def test_neutral_label_no_change_no_fees(self):
        r = self.d.analyze(_base_pos())
        self.assertIn(r["pnl_label"], {"NEUTRAL", "LP_BEATING_HODL"})

    def test_equal_price_rise_both_tokens(self):
        # Both tokens double in price → HODL = 2× initial, LP = 2× initial, IL = 0
        r = self.d.analyze(_base_pos(current_price_a=2.0, current_price_b=2.0))
        self.assertAlmostEqual(r["hodl_value_usd"], 20_000.0, places=4)
        self.assertAlmostEqual(r["lp_value_usd"], 20_000.0, places=4)
        self.assertAlmostEqual(r["impermanent_loss_pct"], 0.0, places=4)

    def test_equal_price_drop_both_tokens(self):
        # Both halve → HODL = 5000, LP = 5000, IL = 0
        r = self.d.analyze(_base_pos(current_price_a=0.5, current_price_b=0.5))
        self.assertAlmostEqual(r["hodl_value_usd"], 5_000.0, places=4)
        self.assertAlmostEqual(r["lp_value_usd"], 5_000.0, places=4)
        self.assertAlmostEqual(r["impermanent_loss_pct"], 0.0, places=4)


class TestConstantProductIL(unittest.TestCase):
    """Impermanent loss formula verification for constant_product pools."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d, _ = _make_decomposer(self.tmp)

    def _il_formula(self, r_a, r_b=1.0):
        r = r_a / r_b
        return (2 * math.sqrt(r) / (1 + r) - 1) * 100

    def test_il_formula_2x_move(self):
        # Token A doubles, B unchanged → r=2, IL ≈ -5.72%
        r = self.d.analyze(_base_pos(current_price_a=2.0))
        expected = self._il_formula(2.0)
        self.assertAlmostEqual(r["impermanent_loss_pct"], expected, places=4)

    def test_il_formula_4x_move(self):
        # Token A = 4×, IL ≈ -20%
        r = self.d.analyze(_base_pos(current_price_a=4.0))
        expected = self._il_formula(4.0)
        self.assertAlmostEqual(r["impermanent_loss_pct"], expected, places=4)

    def test_il_formula_half_move(self):
        # Token A = 0.5×, IL same as 2× (symmetric)
        r = self.d.analyze(_base_pos(current_price_a=0.5))
        expected = self._il_formula(0.5)
        self.assertAlmostEqual(r["impermanent_loss_pct"], expected, places=4)

    def test_il_is_symmetric(self):
        r2x   = self.d.analyze(_base_pos(current_price_a=2.0))
        r_half = self.d.analyze(_base_pos(current_price_a=0.5))
        self.assertAlmostEqual(
            r2x["impermanent_loss_pct"], r_half["impermanent_loss_pct"], places=4
        )

    def test_il_negative_when_price_diverges(self):
        r = self.d.analyze(_base_pos(current_price_a=3.0))
        self.assertLess(r["impermanent_loss_pct"], 0.0)

    def test_il_zero_when_ratio_unchanged(self):
        # Both prices double → r_a/r_b = 1 → IL = 0
        r = self.d.analyze(_base_pos(current_price_a=3.0, current_price_b=3.0))
        self.assertAlmostEqual(r["impermanent_loss_pct"], 0.0, places=4)

    def test_hodl_value_both_rise(self):
        # r_a=3, r_b=2, initial=10k: HODL = 5000*(3+2) = 25000
        r = self.d.analyze(_base_pos(
            entry_price_a=100.0, entry_price_b=1.0,
            current_price_a=300.0, current_price_b=2.0,
        ))
        self.assertAlmostEqual(r["hodl_value_usd"], 25_000.0, places=4)

    def test_lp_value_less_than_hodl_on_diverge(self):
        r = self.d.analyze(_base_pos(current_price_a=5.0))
        self.assertLess(r["lp_value_usd"], r["hodl_value_usd"])

    def test_il_grows_with_divergence(self):
        r2 = self.d.analyze(_base_pos(current_price_a=2.0))
        r4 = self.d.analyze(_base_pos(current_price_a=4.0))
        r9 = self.d.analyze(_base_pos(current_price_a=9.0))
        self.assertLess(r4["impermanent_loss_pct"], r2["impermanent_loss_pct"])
        self.assertLess(r9["impermanent_loss_pct"], r4["impermanent_loss_pct"])

    def test_il_bounded_above_zero(self):
        r = self.d.analyze(_base_pos(current_price_a=1000.0))
        self.assertLessEqual(r["impermanent_loss_pct"], 0.0)

    def test_il_bounded_below_minus_100(self):
        r = self.d.analyze(_base_pos(current_price_a=1_000_000.0))
        self.assertGreaterEqual(r["impermanent_loss_pct"], -100.0)

    def test_lp_value_nonnegative(self):
        r = self.d.analyze(_base_pos(current_price_a=999_999.0))
        self.assertGreaterEqual(r["lp_value_usd"], 0.0)

    def test_fee_income_pct_calculation(self):
        r = self.d.analyze(_base_pos(fee_income_usd=500.0))
        self.assertAlmostEqual(r["fee_income_pct"], 5.0, places=4)

    def test_net_lp_value_includes_fees(self):
        r = self.d.analyze(_base_pos(fee_income_usd=1_000.0))
        self.assertAlmostEqual(r["net_lp_value_usd"], r["lp_value_usd"] + 1_000.0, places=4)

    def test_fees_can_offset_il(self):
        # Large fees should make net_vs_hodl positive despite IL
        r = self.d.analyze(_base_pos(current_price_a=2.0, fee_income_usd=5_000.0))
        # IL alone: ~-5.72%, but fees add 50% of initial → net should be positive
        self.assertGreater(r["net_vs_hodl_pct"], 0.0)


class TestStableSwapPool(unittest.TestCase):
    """Stable-swap IL is 10% of constant-product IL."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d, _ = _make_decomposer(self.tmp)

    def test_stable_swap_il_smaller_than_cp(self):
        cp   = self.d.analyze(_base_pos(current_price_a=2.0, pool_type="constant_product"))
        ss   = self.d.analyze(_base_pos(current_price_a=2.0, pool_type="stable_swap"))
        self.assertGreater(ss["impermanent_loss_pct"], cp["impermanent_loss_pct"])

    def test_stable_swap_il_multiplier(self):
        cp  = self.d.analyze(_base_pos(current_price_a=2.0, pool_type="constant_product"))
        ss  = self.d.analyze(_base_pos(current_price_a=2.0, pool_type="stable_swap"))
        self.assertAlmostEqual(
            ss["impermanent_loss_pct"],
            cp["impermanent_loss_pct"] * STABLE_SWAP_IL_MULTIPLIER,
            places=4,
        )

    def test_stable_swap_zero_il_no_change(self):
        r = self.d.analyze(_base_pos(pool_type="stable_swap"))
        self.assertAlmostEqual(r["impermanent_loss_pct"], 0.0, places=4)

    def test_stable_swap_il_negative_on_diverge(self):
        r = self.d.analyze(_base_pos(current_price_a=3.0, pool_type="stable_swap"))
        self.assertLess(r["impermanent_loss_pct"], 0.0)

    def test_stable_swap_better_than_cp_same_prices(self):
        cp = self.d.analyze(_base_pos(current_price_a=4.0, pool_type="constant_product"))
        ss = self.d.analyze(_base_pos(current_price_a=4.0, pool_type="stable_swap"))
        self.assertGreater(ss["lp_value_usd"], cp["lp_value_usd"])

    def test_stable_swap_lp_value_nonnegative(self):
        r = self.d.analyze(_base_pos(current_price_a=1_000.0, pool_type="stable_swap"))
        self.assertGreaterEqual(r["lp_value_usd"], 0.0)

    def test_stable_swap_fee_pct_correct(self):
        r = self.d.analyze(_base_pos(pool_type="stable_swap", fee_income_usd=200.0))
        self.assertAlmostEqual(r["fee_income_pct"], 2.0, places=4)


class TestConcentratedLiquidityPool(unittest.TestCase):
    """Concentrated liquidity amplifies IL by concentration_factor."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d, _ = _make_decomposer(self.tmp)

    def test_conc_il_larger_than_cp(self):
        cp   = self.d.analyze(_base_pos(current_price_a=2.0, pool_type="constant_product"))
        conc = self.d.analyze(_base_pos(
            current_price_a=2.0, pool_type="concentrated", concentration_factor=3.0
        ))
        self.assertLess(conc["impermanent_loss_pct"], cp["impermanent_loss_pct"])

    def test_conc_il_proportional_to_factor(self):
        cp    = self.d.analyze(_base_pos(current_price_a=2.0, pool_type="constant_product"))
        conc2 = self.d.analyze(_base_pos(
            current_price_a=2.0, pool_type="concentrated", concentration_factor=2.0
        ))
        self.assertAlmostEqual(
            conc2["impermanent_loss_pct"],
            cp["impermanent_loss_pct"] * 2.0,
            places=4,
        )

    def test_conc_il_bounded_minus100(self):
        r = self.d.analyze(_base_pos(
            current_price_a=1_000.0, pool_type="concentrated", concentration_factor=100.0
        ))
        self.assertGreaterEqual(r["impermanent_loss_pct"], -100.0)

    def test_conc_lp_value_nonnegative(self):
        r = self.d.analyze(_base_pos(
            current_price_a=100.0, pool_type="concentrated", concentration_factor=50.0
        ))
        self.assertGreaterEqual(r["lp_value_usd"], 0.0)

    def test_conc_factor_1_equals_cp(self):
        cp   = self.d.analyze(_base_pos(current_price_a=3.0, pool_type="constant_product"))
        conc = self.d.analyze(_base_pos(
            current_price_a=3.0, pool_type="concentrated", concentration_factor=1.0
        ))
        self.assertAlmostEqual(
            conc["impermanent_loss_pct"], cp["impermanent_loss_pct"], places=4
        )

    def test_conc_zero_il_no_change(self):
        r = self.d.analyze(_base_pos(pool_type="concentrated", concentration_factor=5.0))
        self.assertAlmostEqual(r["impermanent_loss_pct"], 0.0, places=4)

    def test_conc_factor_10(self):
        cp   = self.d.analyze(_base_pos(current_price_a=2.0, pool_type="constant_product"))
        conc = self.d.analyze(_base_pos(
            current_price_a=2.0, pool_type="concentrated", concentration_factor=10.0
        ))
        self.assertAlmostEqual(
            conc["impermanent_loss_pct"],
            max(-100.0, cp["impermanent_loss_pct"] * 10.0),
            places=4,
        )


class TestPnlLabels(unittest.TestCase):
    """Test all five pnl_label categories using price divergence and fees."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d, _ = _make_decomposer(self.tmp)

    # -- LP_CRUSHING_HODL: net_vs_hodl > 5% ----------------------------------

    def test_lp_crushing_hodl_label_big_fees(self):
        # No IL, fees = 10% of capital → net = +10%
        r = self.d.analyze(_base_pos(fee_income_usd=1_000.0))
        self.assertEqual(r["pnl_label"], "LP_CRUSHING_HODL")

    def test_lp_crushing_hodl_boundary_plus(self):
        # No IL, fees = 5.5% → net ≈ +5.5%
        r = self.d.analyze(_base_pos(fee_income_usd=550.0))
        self.assertEqual(r["pnl_label"], "LP_CRUSHING_HODL")

    def test_lp_crushing_hodl_high_fee(self):
        r = self.d.analyze(_base_pos(fee_income_usd=10_000.0))
        self.assertEqual(r["pnl_label"], "LP_CRUSHING_HODL")

    # -- LP_BEATING_HODL: 0 < net_vs_hodl <= 5% ------------------------------

    def test_lp_beating_hodl_label(self):
        # No IL, fees = 3% → net = +3%
        r = self.d.analyze(_base_pos(fee_income_usd=300.0))
        self.assertEqual(r["pnl_label"], "LP_BEATING_HODL")

    def test_lp_beating_hodl_boundary_just_above_zero(self):
        # No IL, fees = 0.1% → net = +0.1%
        r = self.d.analyze(_base_pos(fee_income_usd=10.0))
        self.assertEqual(r["pnl_label"], "LP_BEATING_HODL")

    def test_lp_beating_hodl_small_il_offset_by_fees(self):
        # stable_swap + 2× → IL ≈ -0.572%; fees = 3% → net ≈ +2.4%
        r = self.d.analyze(_base_pos(
            current_price_a=2.0, pool_type="stable_swap", fee_income_usd=300.0
        ))
        self.assertEqual(r["pnl_label"], "LP_BEATING_HODL")

    # -- NEUTRAL: -1% < net_vs_hodl <= 0% ------------------------------------

    def test_neutral_label_stable_swap(self):
        # stable_swap + 2× divergence → IL ≈ -0.572%, no fees → NEUTRAL
        r = self.d.analyze(_base_pos(
            current_price_a=2.0, pool_type="stable_swap"
        ))
        self.assertEqual(r["pnl_label"], "NEUTRAL")

    def test_neutral_label_tiny_stable_il(self):
        # stable_swap very small divergence
        r = self.d.analyze(_base_pos(
            current_price_a=1.5, pool_type="stable_swap"
        ))
        self.assertEqual(r["pnl_label"], "NEUTRAL")

    def test_neutral_label_no_change_no_fees(self):
        # IL = 0, fees = 0 → net = 0 → NEUTRAL or LP_BEATING_HODL
        r = self.d.analyze(_base_pos())
        self.assertIn(r["pnl_label"], {"NEUTRAL", "LP_BEATING_HODL"})

    def test_neutral_label_boundary_minus_1(self):
        # net just at -1.0% → LP_LAGGING_HODL (not > -1.0)
        # stable_swap, divergence ≈ 4.7× gives IL ≈ -0.572*ln(4.7/1)/ln(2/1) ≈ ...
        # Use constant_product + just enough fees to land at ≈ -1.0%
        # CP at r≈1.02: IL ≈ tiny, add fees≈0 → get tiny negative
        # Easier: CP at some divergence gives IL slightly < -1% → LP_LAGGING_HODL
        r = self.d.analyze(_base_pos(current_price_a=1.5))
        # IL for CP at r=1.5 → 2*sqrt(1.5)/(2.5) - 1 ≈ -1.92% → LP_LAGGING
        self.assertEqual(r["pnl_label"], "LP_LAGGING_HODL")

    # -- LP_LAGGING_HODL: -10% < net_vs_hodl <= -1% --------------------------

    def test_lp_lagging_hodl_label(self):
        # CP, 2× divergence → IL ≈ -5.72%
        r = self.d.analyze(_base_pos(current_price_a=2.0, pool_type="constant_product"))
        self.assertEqual(r["pnl_label"], "LP_LAGGING_HODL")

    def test_lp_lagging_hodl_boundary_just_above_minus10(self):
        # CP + fees bring net just above -10%
        # CP at 2×: IL ≈ -5.72%, add small fees to stay in -10 < net < -1
        r = self.d.analyze(_base_pos(current_price_a=2.0, pool_type="constant_product"))
        self.assertIn(r["pnl_label"], {"LP_LAGGING_HODL"})

    def test_lp_lagging_hodl_half_price_move(self):
        # CP at 0.5× (equivalent to 2× by symmetry)
        r = self.d.analyze(_base_pos(current_price_a=0.5, pool_type="constant_product"))
        self.assertEqual(r["pnl_label"], "LP_LAGGING_HODL")

    # -- SEVERE_LP_UNDERPERFORMANCE: net_vs_hodl <= -10% ---------------------

    def test_severe_underperformance_label(self):
        # CP, 4× divergence → IL ≈ -20%
        r = self.d.analyze(_base_pos(current_price_a=4.0, pool_type="constant_product"))
        self.assertEqual(r["pnl_label"], "SEVERE_LP_UNDERPERFORMANCE")

    def test_severe_underperformance_at_large_il(self):
        r = self.d.analyze(_base_pos(
            current_price_a=100.0, pool_type="constant_product"
        ))
        self.assertEqual(r["pnl_label"], "SEVERE_LP_UNDERPERFORMANCE")

    def test_severe_underperformance_concentrated_big_factor(self):
        # concentrated + large divergence + big factor → huge IL
        r = self.d.analyze(_base_pos(
            current_price_a=2.0, pool_type="concentrated",
            concentration_factor=5.0,
        ))
        self.assertEqual(r["pnl_label"], "SEVERE_LP_UNDERPERFORMANCE")


class TestFeeIncome(unittest.TestCase):
    """Fee income calculations."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d, _ = _make_decomposer(self.tmp)

    def test_zero_fees(self):
        r = self.d.analyze(_base_pos(fee_income_usd=0.0))
        self.assertAlmostEqual(r["fee_income_pct"], 0.0, places=6)

    def test_fee_pct_10_percent(self):
        r = self.d.analyze(_base_pos(initial_position_usd=10_000.0, fee_income_usd=1_000.0))
        self.assertAlmostEqual(r["fee_income_pct"], 10.0, places=4)

    def test_fee_pct_half_percent(self):
        r = self.d.analyze(_base_pos(initial_position_usd=20_000.0, fee_income_usd=100.0))
        self.assertAlmostEqual(r["fee_income_pct"], 0.5, places=4)

    def test_fee_income_preserved_in_result(self):
        r = self.d.analyze(_base_pos(fee_income_usd=123.45))
        self.assertAlmostEqual(r["fee_income_usd"], 123.45, places=4)

    def test_net_lp_value_no_il_no_change(self):
        r = self.d.analyze(_base_pos(fee_income_usd=500.0))
        self.assertAlmostEqual(r["net_lp_value_usd"], 10_500.0, places=4)

    def test_fees_fully_offset_il(self):
        # Get IL amount, then set fees = |IL| → net_vs_hodl ≈ 0
        r0 = self.d.analyze(_base_pos(current_price_a=2.0))
        il_abs = abs(r0["impermanent_loss_usd"])
        r1 = self.d.analyze(_base_pos(current_price_a=2.0, fee_income_usd=il_abs))
        self.assertAlmostEqual(r1["net_vs_hodl_pct"], 0.0, places=3)


class TestHODLValueCalculation(unittest.TestCase):
    """Verify HODL value arithmetic across scenarios."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d, _ = _make_decomposer(self.tmp)

    def test_hodl_value_basic(self):
        # r_a=2, r_b=1, initial=10k → hodl = 5000*2 + 5000*1 = 15000
        r = self.d.analyze(_base_pos(current_price_a=2.0, current_price_b=1.0))
        self.assertAlmostEqual(r["hodl_value_usd"], 15_000.0, places=4)

    def test_hodl_value_both_rise(self):
        # r_a=3, r_b=3, initial=10k → hodl = 30000
        r = self.d.analyze(_base_pos(current_price_a=3.0, current_price_b=3.0))
        self.assertAlmostEqual(r["hodl_value_usd"], 30_000.0, places=4)

    def test_hodl_value_b_rises(self):
        # r_a=1, r_b=4, initial=10k → hodl = 5000*1 + 5000*4 = 25000
        r = self.d.analyze(_base_pos(current_price_a=1.0, current_price_b=4.0))
        self.assertAlmostEqual(r["hodl_value_usd"], 25_000.0, places=4)

    def test_hodl_value_both_drop(self):
        # r_a=0.5, r_b=0.5, initial=10k → hodl = 5000
        r = self.d.analyze(_base_pos(current_price_a=0.5, current_price_b=0.5))
        self.assertAlmostEqual(r["hodl_value_usd"], 5_000.0, places=4)

    def test_hodl_different_entry_prices(self):
        # entry_a=1000, entry_b=1, cur_a=2000, cur_b=2
        # r_a=2, r_b=2 → hodl = 10k/2*(2+2) = 20k
        r = self.d.analyze(_base_pos(
            entry_price_a=1000.0, entry_price_b=1.0,
            current_price_a=2000.0, current_price_b=2.0,
        ))
        self.assertAlmostEqual(r["hodl_value_usd"], 20_000.0, places=4)

    def test_hodl_different_initial_capital(self):
        r = self.d.analyze(_base_pos(initial_position_usd=50_000.0))
        self.assertAlmostEqual(r["hodl_value_usd"], 50_000.0, places=4)

    def test_hodl_nonnegative(self):
        r = self.d.analyze(_base_pos(current_price_a=0.001, current_price_b=0.001))
        self.assertGreaterEqual(r["hodl_value_usd"], 0.0)


class TestValidation(unittest.TestCase):
    """Validation must raise ValueError for bad inputs."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d, _ = _make_decomposer(self.tmp)

    def test_missing_pool_name(self):
        pos = _base_pos()
        del pos["pool_name"]
        with self.assertRaises(ValueError):
            self.d.analyze(pos)

    def test_missing_entry_price_a(self):
        pos = _base_pos()
        del pos["entry_price_a"]
        with self.assertRaises(ValueError):
            self.d.analyze(pos)

    def test_missing_entry_price_b(self):
        pos = _base_pos()
        del pos["entry_price_b"]
        with self.assertRaises(ValueError):
            self.d.analyze(pos)

    def test_missing_current_price_a(self):
        pos = _base_pos()
        del pos["current_price_a"]
        with self.assertRaises(ValueError):
            self.d.analyze(pos)

    def test_missing_current_price_b(self):
        pos = _base_pos()
        del pos["current_price_b"]
        with self.assertRaises(ValueError):
            self.d.analyze(pos)

    def test_missing_initial_position_usd(self):
        pos = _base_pos()
        del pos["initial_position_usd"]
        with self.assertRaises(ValueError):
            self.d.analyze(pos)

    def test_missing_fee_income_usd(self):
        pos = _base_pos()
        del pos["fee_income_usd"]
        with self.assertRaises(ValueError):
            self.d.analyze(pos)

    def test_missing_days_held(self):
        pos = _base_pos()
        del pos["days_held"]
        with self.assertRaises(ValueError):
            self.d.analyze(pos)

    def test_missing_pool_type(self):
        pos = _base_pos()
        del pos["pool_type"]
        with self.assertRaises(ValueError):
            self.d.analyze(pos)

    def test_zero_entry_price_a(self):
        with self.assertRaises(ValueError):
            self.d.analyze(_base_pos(entry_price_a=0.0))

    def test_negative_entry_price_a(self):
        with self.assertRaises(ValueError):
            self.d.analyze(_base_pos(entry_price_a=-1.0))

    def test_zero_current_price_a(self):
        with self.assertRaises(ValueError):
            self.d.analyze(_base_pos(current_price_a=0.0))

    def test_zero_initial_position(self):
        with self.assertRaises(ValueError):
            self.d.analyze(_base_pos(initial_position_usd=0.0))

    def test_negative_initial_position(self):
        with self.assertRaises(ValueError):
            self.d.analyze(_base_pos(initial_position_usd=-100.0))

    def test_negative_fee_income(self):
        with self.assertRaises(ValueError):
            self.d.analyze(_base_pos(fee_income_usd=-1.0))

    def test_negative_days_held(self):
        with self.assertRaises(ValueError):
            self.d.analyze(_base_pos(days_held=-1.0))

    def test_invalid_pool_type(self):
        with self.assertRaises(ValueError):
            self.d.analyze(_base_pos(pool_type="uniswap_v4"))

    def test_invalid_pool_type_empty(self):
        with self.assertRaises(ValueError):
            self.d.analyze(_base_pos(pool_type=""))

    def test_concentration_factor_below_1(self):
        with self.assertRaises(ValueError):
            self.d.analyze(_base_pos(
                pool_type="concentrated", concentration_factor=0.5
            ))

    def test_zero_concentration_factor(self):
        with self.assertRaises(ValueError):
            self.d.analyze(_base_pos(
                pool_type="concentrated", concentration_factor=0.0
            ))


class TestLogFile(unittest.TestCase):
    """Ring-buffer JSON log functionality."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d, self.log_file = _make_decomposer(self.tmp)

    def test_log_created_on_first_analyze(self):
        self.d.analyze(_base_pos())
        self.assertTrue(os.path.exists(self.log_file))

    def test_log_is_valid_json(self):
        self.d.analyze(_base_pos())
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_has_one_entry_after_one_analyze(self):
        self.d.analyze(_base_pos())
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_accumulates_entries(self):
        for _ in range(5):
            self.d.analyze(_base_pos())
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_ring_buffer_caps_at_100(self):
        for i in range(110):
            self.d.analyze(_base_pos(pool_name=f"POOL_{i}"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), LOG_CAP)

    def test_log_ring_buffer_keeps_newest(self):
        for i in range(110):
            self.d.analyze(_base_pos(pool_name=f"POOL_{i}"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["pool_name"], "POOL_109")

    def test_log_entry_has_pnl_label(self):
        self.d.analyze(_base_pos())
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIn("pnl_label", data[0])

    def test_log_recovers_from_corrupt_file(self):
        with open(self.log_file, "w") as f:
            f.write("NOT_JSON{{{{")
        # Should not raise; should reset log
        self.d.analyze(_base_pos())
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d, _ = _make_decomposer(self.tmp)

    def test_very_small_price_change(self):
        r = self.d.analyze(_base_pos(current_price_a=1.0001))
        self.assertAlmostEqual(r["impermanent_loss_pct"], 0.0, delta=0.01)

    def test_large_initial_position(self):
        r = self.d.analyze(_base_pos(initial_position_usd=100_000_000.0))
        self.assertGreater(r["hodl_value_usd"], 0.0)

    def test_small_initial_position(self):
        r = self.d.analyze(_base_pos(initial_position_usd=0.01))
        self.assertGreater(r["hodl_value_usd"], 0.0)

    def test_zero_days_held_allowed(self):
        r = self.d.analyze(_base_pos(days_held=0.0))
        self.assertIsNotNone(r)

    def test_very_large_days_held(self):
        r = self.d.analyze(_base_pos(days_held=3650.0))
        self.assertIsNotNone(r)

    def test_concentration_factor_1000(self):
        # Should be clamped to -100%
        r = self.d.analyze(_base_pos(
            current_price_a=2.0, pool_type="concentrated",
            concentration_factor=1000.0,
        ))
        self.assertGreaterEqual(r["impermanent_loss_pct"], -100.0)
        self.assertGreaterEqual(r["lp_value_usd"], 0.0)

    def test_all_three_pool_types_accepted(self):
        for pt in ("constant_product", "stable_swap", "concentrated"):
            r = self.d.analyze(_base_pos(pool_type=pt))
            self.assertIn("pnl_label", r)

    def test_valid_pool_types_constant(self):
        self.assertIn("constant_product", VALID_POOL_TYPES)
        self.assertIn("stable_swap", VALID_POOL_TYPES)
        self.assertIn("concentrated", VALID_POOL_TYPES)

    def test_float_conversion_from_int(self):
        r = self.d.analyze(_base_pos(
            entry_price_a=1, current_price_a=2,
            initial_position_usd=10000,
        ))
        self.assertIsInstance(r["hodl_value_usd"], float)

    def test_net_vs_hodl_equals_fee_pct_when_il_zero(self):
        # No price change → IL=0, net_vs_hodl = fee_income_pct
        r = self.d.analyze(_base_pos(fee_income_usd=1_000.0))
        self.assertAlmostEqual(r["net_vs_hodl_pct"], r["fee_income_pct"], places=4)


class TestRealWorldScenarios(unittest.TestCase):
    """Representative DeFi scenarios."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d, _ = _make_decomposer(self.tmp)

    def test_eth_usdc_2x_bull_run(self):
        # ETH doubles vs USDC; IL ≈ -5.72%
        r = self.d.analyze(_base_pos(
            pool_name="ETH/USDC", entry_price_a=2_000.0, entry_price_b=1.0,
            current_price_a=4_000.0, current_price_b=1.0,
            initial_position_usd=100_000.0, fee_income_usd=2_000.0,
            pool_type="constant_product",
        ))
        self.assertLess(r["impermanent_loss_pct"], 0.0)
        self.assertGreater(r["impermanent_loss_pct"], -10.0)

    def test_usdc_dai_stable_pool(self):
        # Stablecoins barely move — IL negligible on stable_swap
        r = self.d.analyze(_base_pos(
            pool_name="USDC/DAI",
            entry_price_a=1.0, entry_price_b=1.0,
            current_price_a=1.001, current_price_b=0.999,
            initial_position_usd=50_000.0, fee_income_usd=150.0,
            pool_type="stable_swap",
        ))
        self.assertGreater(r["impermanent_loss_pct"], -0.1)

    def test_uniswap_v3_concentrated_range(self):
        r = self.d.analyze(_base_pos(
            pool_name="WBTC/USDC", entry_price_a=30_000.0, entry_price_b=1.0,
            current_price_a=60_000.0, current_price_b=1.0,
            initial_position_usd=200_000.0, fee_income_usd=15_000.0,
            pool_type="concentrated", concentration_factor=4.0,
        ))
        self.assertGreater(r["fee_income_pct"], 0.0)
        self.assertIn("pnl_label", r)

    def test_crashed_token_scenario(self):
        # Token A crashes 90%
        r = self.d.analyze(_base_pos(
            pool_name="TOKEN/USDC", entry_price_a=10.0, entry_price_b=1.0,
            current_price_a=1.0, current_price_b=1.0,
            initial_position_usd=10_000.0, fee_income_usd=100.0,
            pool_type="constant_product",
        ))
        self.assertLess(r["impermanent_loss_pct"], -5.0)

    def test_depeg_stablecoin_stable_pool(self):
        # stablecoin depeg: USDC stays at $1, USDT drops to $0.9
        r = self.d.analyze(_base_pos(
            pool_name="USDC/USDT",
            entry_price_a=1.0, entry_price_b=1.0,
            current_price_a=1.0, current_price_b=0.9,
            initial_position_usd=1_000_000.0, fee_income_usd=5_000.0,
            pool_type="stable_swap",
        ))
        self.assertLess(r["impermanent_loss_pct"], 0.0)
        # Stable swap should limit the damage
        cp_r = self.d.analyze(_base_pos(
            entry_price_a=1.0, entry_price_b=1.0,
            current_price_a=1.0, current_price_b=0.9,
            pool_type="constant_product",
        ))
        self.assertGreater(r["impermanent_loss_pct"], cp_r["impermanent_loss_pct"])


if __name__ == "__main__":
    unittest.main()
