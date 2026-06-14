"""
Tests for MP-1071: ProtocolDeFiAmmImpermanentLossForecaster
≥90 unittest tests covering IL math, fee income, scenario dicts, risk labels,
output structure, edge cases, and ring-buffer log.
Run with: python3 -m unittest spa_core/tests/test_protocol_defi_amm_impermanent_loss_forecaster.py
"""

import json
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_amm_impermanent_loss_forecaster import (
    ProtocolDeFiAmmImpermanentLossForecaster,
    constant_product_il,
    stable_swap_il,
    compute_il,
    compute_fee_income,
    price_ratio_change_pct,
    compute_scenario,
    il_risk_label,
    _atomic_log_append,
    STABLE_SWAP_REDUCTION_FACTOR,
    LABEL_IL_NEGLIGIBLE,
    LABEL_LOW_IL_RISK,
    LABEL_MODERATE_IL,
    LABEL_HIGH_IL,
    LABEL_SEVERE_IL,
    POOL_TYPE_CONSTANT_PRODUCT,
    POOL_TYPE_STABLE_SWAP,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _pool(**kwargs):
    base = {
        "pool_name": "ETH/USDC 0.3%",
        "token_a_symbol": "ETH",
        "token_b_symbol": "USDC",
        "initial_price_ratio": 3000.0,
        "price_scenarios": [0.5, 0.75, 1.0, 1.5, 2.0],
        "fee_tier_bps": 30,
        "expected_volume_usd_per_day": 10_000_000,
        "position_usd": 100_000,
        "holding_period_days": 30,
        "pool_type": "constant_product",
    }
    base.update(kwargs)
    return base


# --------------------------------------------------------------------------- #
# Tests: constant_product_il
# --------------------------------------------------------------------------- #

class TestConstantProductIl(unittest.TestCase):

    def test_no_price_change_zero_il(self):
        il = constant_product_il(1.0)
        self.assertAlmostEqual(il, 0.0, places=8)

    def test_price_doubled_negative_il(self):
        # k=2: 2*sqrt(2)/3 - 1 ≈ -0.05719
        il = constant_product_il(2.0)
        self.assertAlmostEqual(il, -0.05719, places=4)

    def test_price_halved_same_magnitude_as_doubled(self):
        # IL is symmetric: k=0.5 gives same magnitude as k=2.0
        il_double = constant_product_il(2.0)
        il_half = constant_product_il(0.5)
        self.assertAlmostEqual(il_double, il_half, places=8)

    def test_price_quadrupled(self):
        # k=4: 2*sqrt(4)/5 - 1 = 4/5 - 1 = -0.2
        il = constant_product_il(4.0)
        self.assertAlmostEqual(il, -0.2, places=8)

    def test_price_quartered(self):
        # k=0.25 symmetric with k=4
        il = constant_product_il(0.25)
        self.assertAlmostEqual(il, -0.2, places=8)

    def test_zero_price_multiplier_total_loss(self):
        il = constant_product_il(0.0)
        self.assertEqual(il, -1.0)

    def test_negative_price_multiplier_total_loss(self):
        il = constant_product_il(-5.0)
        self.assertEqual(il, -1.0)

    def test_il_always_non_positive(self):
        for k in [0.1, 0.5, 1.0, 1.5, 2.0, 5.0, 10.0]:
            il = constant_product_il(k)
            self.assertLessEqual(il, 0.0)

    def test_il_magnitude_increases_further_from_1(self):
        il_moderate = constant_product_il(2.0)
        il_large = constant_product_il(10.0)
        self.assertLess(il_large, il_moderate)  # both negative, larger divergence → more loss

    def test_large_price_multiplier_approaches_minus_1(self):
        il = constant_product_il(10000.0)
        self.assertLess(il, -0.9)  # approaches -1 as k → ∞

    def test_near_1_price_change_small_il(self):
        il = constant_product_il(1.01)
        self.assertGreater(il, -0.001)  # very small loss for 1% price move

    def test_return_type_is_float(self):
        self.assertIsInstance(constant_product_il(1.5), float)


# --------------------------------------------------------------------------- #
# Tests: stable_swap_il
# --------------------------------------------------------------------------- #

class TestStableSwapIl(unittest.TestCase):

    def test_no_price_change_zero_il(self):
        il = stable_swap_il(1.0)
        self.assertAlmostEqual(il, 0.0, places=8)

    def test_stable_il_less_than_cp(self):
        cp = constant_product_il(2.0)
        ss = stable_swap_il(2.0)
        self.assertGreater(ss, cp)  # ss is closer to 0 (less loss)

    def test_stable_il_fraction_of_cp(self):
        cp = constant_product_il(4.0)
        ss = stable_swap_il(4.0)
        self.assertAlmostEqual(ss / cp, STABLE_SWAP_REDUCTION_FACTOR, places=5)

    def test_zero_price_multiplier(self):
        il = stable_swap_il(0.0)
        self.assertLessEqual(il, 0.0)

    def test_negative_price_multiplier(self):
        il = stable_swap_il(-1.0)
        self.assertLessEqual(il, 0.0)

    def test_stable_always_non_positive(self):
        for k in [0.1, 0.5, 1.0, 1.5, 2.0, 5.0]:
            self.assertLessEqual(stable_swap_il(k), 0.0)


# --------------------------------------------------------------------------- #
# Tests: compute_il dispatch
# --------------------------------------------------------------------------- #

class TestComputeIl(unittest.TestCase):

    def test_constant_product_dispatches_correctly(self):
        cp_direct = constant_product_il(2.0)
        cp_dispatched = compute_il(2.0, "constant_product")
        self.assertAlmostEqual(cp_dispatched, cp_direct, places=10)

    def test_stable_swap_dispatches_correctly(self):
        ss_direct = stable_swap_il(2.0)
        ss_dispatched = compute_il(2.0, "stable_swap")
        self.assertAlmostEqual(ss_dispatched, ss_direct, places=10)

    def test_unknown_pool_type_uses_constant_product(self):
        cp_direct = constant_product_il(3.0)
        dispatched = compute_il(3.0, "mystery_pool")
        self.assertAlmostEqual(dispatched, cp_direct, places=10)

    def test_stable_case_insensitive(self):
        ss_direct = stable_swap_il(2.0)
        dispatched_upper = compute_il(2.0, "Stable_Swap")
        self.assertAlmostEqual(dispatched_upper, ss_direct, places=8)

    def test_stable_substring_match(self):
        # "stableswap_v2" contains "stable"
        ss_direct = stable_swap_il(2.0)
        dispatched = compute_il(2.0, "stableswap_v2")
        self.assertAlmostEqual(dispatched, ss_direct, places=8)

    def test_il_is_less_for_stable_than_cp(self):
        cp = compute_il(4.0, "constant_product")
        ss = compute_il(4.0, "stable_swap")
        self.assertGreater(ss, cp)  # ss closer to zero (less loss)


# --------------------------------------------------------------------------- #
# Tests: compute_fee_income
# --------------------------------------------------------------------------- #

class TestComputeFeeIncome(unittest.TestCase):

    def test_zero_position_returns_zero(self):
        self.assertEqual(compute_fee_income(30, 1_000_000, 0, 30), 0.0)

    def test_negative_position_returns_zero(self):
        self.assertEqual(compute_fee_income(30, 1_000_000, -1000, 30), 0.0)

    def test_basic_calculation(self):
        # fee_rate = 30/10000 = 0.003; volume=1_000_000; days=30; position=100_000
        # total_fees = 0.003 * 1_000_000 * 30 = 90_000
        # fraction = 90_000 / 100_000 = 0.9
        result = compute_fee_income(30, 1_000_000, 100_000, 30)
        self.assertAlmostEqual(result, 0.9)

    def test_zero_volume_returns_zero(self):
        result = compute_fee_income(30, 0.0, 100_000, 30)
        self.assertEqual(result, 0.0)

    def test_zero_days_returns_zero(self):
        result = compute_fee_income(30, 1_000_000, 100_000, 0)
        self.assertEqual(result, 0.0)

    def test_higher_fee_tier_more_income(self):
        low = compute_fee_income(5, 1_000_000, 100_000, 30)
        high = compute_fee_income(100, 1_000_000, 100_000, 30)
        self.assertGreater(high, low)

    def test_more_volume_more_income(self):
        low_vol = compute_fee_income(30, 100_000, 100_000, 30)
        high_vol = compute_fee_income(30, 10_000_000, 100_000, 30)
        self.assertGreater(high_vol, low_vol)

    def test_longer_holding_more_income(self):
        short = compute_fee_income(30, 1_000_000, 100_000, 7)
        long_ = compute_fee_income(30, 1_000_000, 100_000, 90)
        self.assertGreater(long_, short)

    def test_proportional_to_fee_tier(self):
        a = compute_fee_income(30, 1_000_000, 100_000, 30)
        b = compute_fee_income(60, 1_000_000, 100_000, 30)
        self.assertAlmostEqual(b / a, 2.0, places=8)

    def test_result_is_float(self):
        result = compute_fee_income(30, 1_000_000, 100_000, 30)
        self.assertIsInstance(result, float)


# --------------------------------------------------------------------------- #
# Tests: price_ratio_change_pct
# --------------------------------------------------------------------------- #

class TestPriceRatioChangePct(unittest.TestCase):

    def test_no_change(self):
        self.assertAlmostEqual(price_ratio_change_pct(1.0), 0.0)

    def test_double_is_100_pct(self):
        self.assertAlmostEqual(price_ratio_change_pct(2.0), 100.0)

    def test_half_is_minus_50_pct(self):
        self.assertAlmostEqual(price_ratio_change_pct(0.5), -50.0)

    def test_triple_is_200_pct(self):
        self.assertAlmostEqual(price_ratio_change_pct(3.0), 200.0)

    def test_zero_is_minus_100_pct(self):
        self.assertAlmostEqual(price_ratio_change_pct(0.0), -100.0)


# --------------------------------------------------------------------------- #
# Tests: compute_scenario
# --------------------------------------------------------------------------- #

class TestComputeScenario(unittest.TestCase):

    def test_no_change_zero_il(self):
        s = compute_scenario(1.0, 0.0, "constant_product")
        self.assertAlmostEqual(s["il_pct"], 0.0, places=5)

    def test_no_change_zero_net_pnl_no_fees(self):
        s = compute_scenario(1.0, 0.0, "constant_product")
        self.assertAlmostEqual(s["net_pnl_pct"], 0.0, places=5)

    def test_break_even_with_zero_il_zero_fee(self):
        s = compute_scenario(1.0, 0.0, "constant_product")
        self.assertTrue(s["break_even"])

    def test_il_pct_is_negative_when_price_changes(self):
        s = compute_scenario(2.0, 0.0, "constant_product")
        self.assertLess(s["il_pct"], 0.0)

    def test_fee_income_pct_in_output(self):
        s = compute_scenario(1.0, 0.1, "constant_product")
        self.assertAlmostEqual(s["fee_income_pct"], 10.0, places=4)

    def test_net_pnl_is_il_plus_fee(self):
        s = compute_scenario(2.0, 0.05, "constant_product")
        expected = s["il_pct"] + s["fee_income_pct"]
        self.assertAlmostEqual(s["net_pnl_pct"], expected, places=4)

    def test_break_even_when_fees_cover_il(self):
        # IL at k=1.0 is 0; any fee > 0 → break_even
        s = compute_scenario(1.0, 0.01, "constant_product")
        self.assertTrue(s["break_even"])

    def test_not_break_even_when_il_exceeds_fee(self):
        # IL at k=4 is -20%; fee_income = 5% → net = -15% → not break even
        s = compute_scenario(4.0, 0.05, "constant_product")
        self.assertFalse(s["break_even"])

    def test_output_keys_present(self):
        s = compute_scenario(1.5, 0.02, "constant_product")
        for key in ("price_ratio_change_pct", "il_pct", "fee_income_pct", "net_pnl_pct", "break_even"):
            self.assertIn(key, s)

    def test_price_ratio_change_pct_correct(self):
        s = compute_scenario(1.5, 0.0, "constant_product")
        self.assertAlmostEqual(s["price_ratio_change_pct"], 50.0)

    def test_stable_swap_less_il_than_cp(self):
        cp = compute_scenario(4.0, 0.0, "constant_product")
        ss = compute_scenario(4.0, 0.0, "stable_swap")
        self.assertGreater(ss["il_pct"], cp["il_pct"])  # ss closer to 0


# --------------------------------------------------------------------------- #
# Tests: il_risk_label
# --------------------------------------------------------------------------- #

class TestIlRiskLabel(unittest.TestCase):

    def test_zero_il_negligible(self):
        self.assertEqual(il_risk_label(0.0), LABEL_IL_NEGLIGIBLE)

    def test_just_below_0_5_negligible(self):
        self.assertEqual(il_risk_label(-0.49), LABEL_IL_NEGLIGIBLE)

    def test_at_0_5_low(self):
        self.assertEqual(il_risk_label(-0.5), LABEL_LOW_IL_RISK)

    def test_just_below_2_low(self):
        self.assertEqual(il_risk_label(-1.99), LABEL_LOW_IL_RISK)

    def test_at_2_moderate(self):
        self.assertEqual(il_risk_label(-2.0), LABEL_MODERATE_IL)

    def test_just_below_5_moderate(self):
        self.assertEqual(il_risk_label(-4.99), LABEL_MODERATE_IL)

    def test_at_5_high(self):
        self.assertEqual(il_risk_label(-5.0), LABEL_HIGH_IL)

    def test_just_below_15_high(self):
        self.assertEqual(il_risk_label(-14.99), LABEL_HIGH_IL)

    def test_at_15_severe(self):
        self.assertEqual(il_risk_label(-15.0), LABEL_SEVERE_IL)

    def test_large_il_severe(self):
        self.assertEqual(il_risk_label(-50.0), LABEL_SEVERE_IL)

    def test_positive_il_uses_abs(self):
        # absolute value is used; positive 5.0 should map same as -5.0
        self.assertEqual(il_risk_label(5.0), LABEL_HIGH_IL)


# --------------------------------------------------------------------------- #
# Tests: _atomic_log_append
# --------------------------------------------------------------------------- #

class TestAtomicLogAppend(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_il_log.json")

    def test_creates_file_on_first_append(self):
        _atomic_log_append({"il": -5.0}, self.log_path, 100)
        self.assertTrue(os.path.exists(self.log_path))

    def test_file_contains_valid_json_list(self):
        _atomic_log_append({"il": -5.0}, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_multiple_appends_accumulate(self):
        for i in range(5):
            _atomic_log_append({"i": i}, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap_enforced(self):
        for i in range(12):
            _atomic_log_append({"i": i}, self.log_path, 5)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_keeps_newest(self):
        cap = 3
        for i in range(7):
            _atomic_log_append({"i": i}, self.log_path, cap)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], 6)

    def test_no_tmp_file_left(self):
        _atomic_log_append({"x": 1}, self.log_path, 100)
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_corrupt_file_recovered(self):
        with open(self.log_path, "w") as f:
            f.write("{invalid")
        _atomic_log_append({"x": 1}, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_entry_contents_preserved(self):
        entry = {"pool": "ETH/USDC", "il": -5.72, "label": "HIGH_IL"}
        _atomic_log_append(entry, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["pool"], "ETH/USDC")
        self.assertAlmostEqual(data[0]["il"], -5.72)


# --------------------------------------------------------------------------- #
# Tests: ProtocolDeFiAmmImpermanentLossForecaster — output keys
# --------------------------------------------------------------------------- #

class TestForecasterOutputKeys(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.forecaster = ProtocolDeFiAmmImpermanentLossForecaster(
            log_path=os.path.join(self.tmpdir, "log.json")
        )

    def _basic_result(self):
        return self.forecaster.forecast(_pool())

    def test_has_pool_name(self):
        self.assertIn("pool_name", self._basic_result())

    def test_has_token_a_symbol(self):
        self.assertIn("token_a_symbol", self._basic_result())

    def test_has_token_b_symbol(self):
        self.assertIn("token_b_symbol", self._basic_result())

    def test_has_scenarios(self):
        self.assertIn("scenarios", self._basic_result())

    def test_has_worst_case_il_pct(self):
        self.assertIn("worst_case_il_pct", self._basic_result())

    def test_has_best_case_net_pnl_pct(self):
        self.assertIn("best_case_net_pnl_pct", self._basic_result())

    def test_has_il_risk_label(self):
        self.assertIn("il_risk_label", self._basic_result())

    def test_has_timestamp(self):
        self.assertIn("timestamp", self._basic_result())

    def test_has_pool_type(self):
        self.assertIn("pool_type", self._basic_result())

    def test_has_fee_tier_bps(self):
        self.assertIn("fee_tier_bps", self._basic_result())

    def test_pool_name_returned_correctly(self):
        r = self.forecaster.forecast(_pool(pool_name="DAI/USDC"))
        self.assertEqual(r["pool_name"], "DAI/USDC")

    def test_timestamp_is_string(self):
        r = self._basic_result()
        self.assertIsInstance(r["timestamp"], str)


# --------------------------------------------------------------------------- #
# Tests: ProtocolDeFiAmmImpermanentLossForecaster — scenarios list
# --------------------------------------------------------------------------- #

class TestForecasterScenarios(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.forecaster = ProtocolDeFiAmmImpermanentLossForecaster(
            log_path=os.path.join(self.tmpdir, "log.json")
        )

    def test_scenario_count_matches_input(self):
        r = self.forecaster.forecast(_pool(price_scenarios=[0.5, 1.0, 2.0]))
        self.assertEqual(len(r["scenarios"]), 3)

    def test_single_scenario(self):
        r = self.forecaster.forecast(_pool(price_scenarios=[1.0]))
        self.assertEqual(len(r["scenarios"]), 1)

    def test_five_scenarios(self):
        r = self.forecaster.forecast(_pool(price_scenarios=[0.5, 0.75, 1.0, 1.5, 2.0]))
        self.assertEqual(len(r["scenarios"]), 5)

    def test_each_scenario_has_required_keys(self):
        r = self.forecaster.forecast(_pool(price_scenarios=[1.0, 2.0]))
        for s in r["scenarios"]:
            for key in ("price_ratio_change_pct", "il_pct", "fee_income_pct", "net_pnl_pct", "break_even"):
                self.assertIn(key, s)

    def test_no_price_change_zero_il_pct(self):
        r = self.forecaster.forecast(_pool(
            price_scenarios=[1.0],
            expected_volume_usd_per_day=0,
        ))
        self.assertAlmostEqual(r["scenarios"][0]["il_pct"], 0.0, places=4)

    def test_price_doubling_negative_il(self):
        r = self.forecaster.forecast(_pool(
            price_scenarios=[2.0],
            expected_volume_usd_per_day=0,
        ))
        self.assertLess(r["scenarios"][0]["il_pct"], 0.0)

    def test_break_even_true_when_fees_cover_il(self):
        # 0% fee income, no price change → break even
        r = self.forecaster.forecast(_pool(
            price_scenarios=[1.0],
            expected_volume_usd_per_day=0,
        ))
        self.assertTrue(r["scenarios"][0]["break_even"])

    def test_break_even_false_when_large_il(self):
        # Large price change, zero volume → can't break even
        r = self.forecaster.forecast(_pool(
            price_scenarios=[4.0],
            expected_volume_usd_per_day=0,
        ))
        self.assertFalse(r["scenarios"][0]["break_even"])

    def test_empty_scenarios(self):
        r = self.forecaster.forecast(_pool(price_scenarios=[]))
        self.assertEqual(r["scenarios"], [])
        self.assertEqual(r["worst_case_il_pct"], 0.0)
        self.assertEqual(r["best_case_net_pnl_pct"], 0.0)


# --------------------------------------------------------------------------- #
# Tests: ProtocolDeFiAmmImpermanentLossForecaster — worst/best aggregates
# --------------------------------------------------------------------------- #

class TestForecasterWorstBest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.forecaster = ProtocolDeFiAmmImpermanentLossForecaster(
            log_path=os.path.join(self.tmpdir, "log.json")
        )

    def test_worst_case_il_is_most_negative(self):
        r = self.forecaster.forecast(_pool(
            price_scenarios=[1.0, 2.0, 4.0],
            expected_volume_usd_per_day=0,
        ))
        min_il = min(s["il_pct"] for s in r["scenarios"])
        self.assertAlmostEqual(r["worst_case_il_pct"], min_il, places=4)

    def test_best_case_net_pnl_is_maximum(self):
        r = self.forecaster.forecast(_pool(
            price_scenarios=[1.0, 2.0],
            expected_volume_usd_per_day=0,
        ))
        max_net = max(s["net_pnl_pct"] for s in r["scenarios"])
        self.assertAlmostEqual(r["best_case_net_pnl_pct"], max_net, places=4)

    def test_stable_swap_worst_il_less_severe(self):
        r_cp = self.forecaster.forecast(_pool(price_scenarios=[4.0], pool_type="constant_product"))
        r_ss = self.forecaster.forecast(_pool(price_scenarios=[4.0], pool_type="stable_swap"))
        self.assertGreater(r_ss["worst_case_il_pct"], r_cp["worst_case_il_pct"])

    def test_fees_improve_best_case(self):
        r_no_fee = self.forecaster.forecast(_pool(
            price_scenarios=[1.0],
            expected_volume_usd_per_day=0,
        ))
        r_with_fee = self.forecaster.forecast(_pool(
            price_scenarios=[1.0],
            expected_volume_usd_per_day=5_000_000,
        ))
        self.assertGreater(r_with_fee["best_case_net_pnl_pct"], r_no_fee["best_case_net_pnl_pct"])

    def test_worst_case_il_pct_non_positive(self):
        r = self.forecaster.forecast(_pool(price_scenarios=[0.5, 1.0, 2.0]))
        self.assertLessEqual(r["worst_case_il_pct"], 0.0)

    def test_il_risk_label_in_valid_set(self):
        valid = {LABEL_IL_NEGLIGIBLE, LABEL_LOW_IL_RISK, LABEL_MODERATE_IL, LABEL_HIGH_IL, LABEL_SEVERE_IL}
        r = self.forecaster.forecast(_pool())
        self.assertIn(r["il_risk_label"], valid)

    def test_severe_il_label_for_large_price_swing(self):
        r = self.forecaster.forecast(_pool(
            price_scenarios=[10.0],
            expected_volume_usd_per_day=0,
        ))
        self.assertEqual(r["il_risk_label"], LABEL_SEVERE_IL)

    def test_negligible_il_label_near_1(self):
        r = self.forecaster.forecast(_pool(
            price_scenarios=[1.001],
            expected_volume_usd_per_day=0,
        ))
        self.assertEqual(r["il_risk_label"], LABEL_IL_NEGLIGIBLE)


# --------------------------------------------------------------------------- #
# Tests: ProtocolDeFiAmmImpermanentLossForecaster — edge cases
# --------------------------------------------------------------------------- #

class TestForecasterEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.forecaster = ProtocolDeFiAmmImpermanentLossForecaster(
            log_path=os.path.join(self.tmpdir, "log.json")
        )

    def test_missing_pool_name_defaults(self):
        r = self.forecaster.forecast({})
        self.assertIn("pool_name", r)

    def test_zero_position_usd(self):
        r = self.forecaster.forecast(_pool(position_usd=0, price_scenarios=[2.0]))
        # Should not raise; fee income defaults to 0
        self.assertLess(r["scenarios"][0]["fee_income_pct"], 0.01)

    def test_zero_fee_tier(self):
        r = self.forecaster.forecast(_pool(fee_tier_bps=0, price_scenarios=[1.0]))
        self.assertAlmostEqual(r["scenarios"][0]["fee_income_pct"], 0.0)

    def test_zero_holding_days(self):
        r = self.forecaster.forecast(_pool(holding_period_days=0, price_scenarios=[2.0]))
        self.assertAlmostEqual(r["scenarios"][0]["fee_income_pct"], 0.0)

    def test_worst_case_il_is_float(self):
        r = self.forecaster.forecast(_pool())
        self.assertIsInstance(r["worst_case_il_pct"], float)

    def test_best_case_net_pnl_is_float(self):
        r = self.forecaster.forecast(_pool())
        self.assertIsInstance(r["best_case_net_pnl_pct"], float)

    def test_very_high_fee_can_turn_net_pnl_positive(self):
        # fee_tier=10000 bps = 100%!  => massive fee income overcoming IL
        r = self.forecaster.forecast(_pool(
            fee_tier_bps=10000,
            expected_volume_usd_per_day=10_000_000,
            position_usd=100_000,
            holding_period_days=365,
            price_scenarios=[2.0],
        ))
        self.assertGreater(r["scenarios"][0]["net_pnl_pct"], 0.0)

    def test_stable_swap_pool_type_in_output(self):
        r = self.forecaster.forecast(_pool(pool_type="stable_swap"))
        self.assertEqual(r["pool_type"], "stable_swap")


# --------------------------------------------------------------------------- #
# Tests: ProtocolDeFiAmmImpermanentLossForecaster — log file
# --------------------------------------------------------------------------- #

class TestForecasterLogFile(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "il_log.json")
        self.forecaster = ProtocolDeFiAmmImpermanentLossForecaster(log_path=self.log_path)

    def test_log_created_on_forecast(self):
        self.forecaster.forecast(_pool())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_valid_json_list(self):
        self.forecaster.forecast(_pool())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_required_keys(self):
        self.forecaster.forecast(_pool(pool_name="WBTC/USDC"))
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        for key in ("timestamp", "pool_name", "worst_case_il_pct", "il_risk_label", "scenario_count"):
            self.assertIn(key, entry)

    def test_log_pool_name_recorded(self):
        self.forecaster.forecast(_pool(pool_name="SpecialPool"))
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["pool_name"], "SpecialPool")

    def test_log_ring_buffer_enforced(self):
        forecaster = ProtocolDeFiAmmImpermanentLossForecaster(log_path=self.log_path, log_cap=4)
        for _ in range(8):
            forecaster.forecast(_pool())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 4)

    def test_log_no_tmp_file_remains(self):
        self.forecaster.forecast(_pool())
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_custom_log_dir_created(self):
        custom_path = os.path.join(self.tmpdir, "nested", "il.json")
        f = ProtocolDeFiAmmImpermanentLossForecaster(log_path=custom_path)
        f.forecast(_pool())
        self.assertTrue(os.path.exists(custom_path))

    def test_log_scenario_count_correct(self):
        self.forecaster.forecast(_pool(price_scenarios=[0.5, 1.0, 2.0]))
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["scenario_count"], 3)


# --------------------------------------------------------------------------- #
# Tests: ProtocolDeFiAmmImpermanentLossForecaster — real scenario math
# --------------------------------------------------------------------------- #

class TestForecasterMathVerification(unittest.TestCase):
    """Verify key numerical results against manual calculations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.forecaster = ProtocolDeFiAmmImpermanentLossForecaster(
            log_path=os.path.join(self.tmpdir, "log.json")
        )

    def test_k4_il_is_exactly_minus_20_pct(self):
        # k=4: 2*sqrt(4)/(1+4) - 1 = 4/5 - 1 = -0.2 → -20%
        r = self.forecaster.forecast(_pool(
            price_scenarios=[4.0],
            expected_volume_usd_per_day=0,
        ))
        self.assertAlmostEqual(r["scenarios"][0]["il_pct"], -20.0, places=4)

    def test_k025_il_is_also_minus_20_pct(self):
        # Symmetric with k=4
        r = self.forecaster.forecast(_pool(
            price_scenarios=[0.25],
            expected_volume_usd_per_day=0,
        ))
        self.assertAlmostEqual(r["scenarios"][0]["il_pct"], -20.0, places=4)

    def test_k2_il_approx_minus_5_72_pct(self):
        # k=2: IL ≈ -5.72%
        r = self.forecaster.forecast(_pool(
            price_scenarios=[2.0],
            expected_volume_usd_per_day=0,
        ))
        self.assertAlmostEqual(r["scenarios"][0]["il_pct"], -5.719, places=2)

    def test_fee_income_pct_calculation(self):
        # fee=30bps, vol=1M/day, 30 days, position=100k
        # income = 0.003 * 1_000_000 * 30 / 100_000 = 0.9 → 90%
        r = self.forecaster.forecast(_pool(
            price_scenarios=[1.0],
            fee_tier_bps=30,
            expected_volume_usd_per_day=1_000_000,
            position_usd=100_000,
            holding_period_days=30,
        ))
        self.assertAlmostEqual(r["scenarios"][0]["fee_income_pct"], 90.0, places=4)

    def test_price_ratio_change_is_correct(self):
        r = self.forecaster.forecast(_pool(price_scenarios=[1.5]))
        self.assertAlmostEqual(r["scenarios"][0]["price_ratio_change_pct"], 50.0)

    def test_net_pnl_is_sum_of_il_and_fee(self):
        r = self.forecaster.forecast(_pool(
            price_scenarios=[2.0],
            fee_tier_bps=30,
            expected_volume_usd_per_day=1_000_000,
            position_usd=100_000,
            holding_period_days=30,
        ))
        s = r["scenarios"][0]
        expected_net = s["il_pct"] + s["fee_income_pct"]
        self.assertAlmostEqual(s["net_pnl_pct"], expected_net, places=4)


if __name__ == "__main__":
    unittest.main()
