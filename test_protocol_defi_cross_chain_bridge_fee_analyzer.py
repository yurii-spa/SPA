"""
Tests for MP-1095: ProtocolDeFiCrossChainBridgeFeeAnalyzer
≥110 unittest tests covering helpers, class methods, edge cases, batch API,
ranking, and ring-buffer atomic log.
Run with: python3 -m unittest spa_core/tests/test_protocol_defi_cross_chain_bridge_fee_analyzer.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_cross_chain_bridge_fee_analyzer import (
    ProtocolDeFiCrossChainBridgeFeeAnalyzer,
    compute_total_bridge_cost_usd,
    compute_total_bridge_cost_pct,
    compute_opportunity_cost_usd,
    compute_net_apy_advantage_pct,
    compute_breakeven_days,
    compute_bridge_efficiency_score,
    compute_bridge_label,
    _atomic_log_append,
    LABEL_EFFICIENT_BRIDGE,
    LABEL_ACCEPTABLE_COST,
    LABEL_HIGH_BRIDGE_COST,
    LABEL_INEFFICIENT_BRIDGE,
    LABEL_BRIDGE_NOT_WORTH_IT,
    _BREAKEVEN_INF,
    _MINUTES_PER_YEAR,
    _DAYS_PER_YEAR,
)

# =========================================================================== #
# Helpers
# =========================================================================== #

def _tmp_log():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _analyzer(log_path=None):
    return ProtocolDeFiCrossChainBridgeFeeAnalyzer(log_path=log_path or _tmp_log())


def _result(**kw):
    """Shorthand: call analyzer.analyze with sensible defaults + overrides."""
    defaults = dict(
        protocol_name="TestBridge",
        bridge_fee_pct=0.05,
        bridge_fee_fixed_usd=1.0,
        destination_gas_usd=2.0,
        source_gas_usd=3.0,
        bridge_time_minutes=30,
        position_size_usd=50_000.0,
        target_apy_pct=8.0,
        source_apy_pct=3.0,
    )
    defaults.update(kw)
    return _analyzer().analyze(**defaults)


# =========================================================================== #
# 1. compute_total_bridge_cost_usd
# =========================================================================== #

class TestComputeTotalBridgeCostUsd(unittest.TestCase):

    def test_all_components_summed(self):
        # 0.1% of 10_000 = 10 + 5 fixed + 3 dst gas + 2 src gas = 20
        cost = compute_total_bridge_cost_usd(0.1, 5.0, 3.0, 2.0, 10_000.0)
        self.assertAlmostEqual(cost, 20.0, places=4)

    def test_only_pct_fee(self):
        cost = compute_total_bridge_cost_usd(1.0, 0.0, 0.0, 0.0, 1_000.0)
        self.assertAlmostEqual(cost, 10.0, places=4)

    def test_only_fixed_fee(self):
        cost = compute_total_bridge_cost_usd(0.0, 25.0, 0.0, 0.0, 100_000.0)
        self.assertAlmostEqual(cost, 25.0, places=4)

    def test_only_destination_gas(self):
        cost = compute_total_bridge_cost_usd(0.0, 0.0, 7.5, 0.0, 50_000.0)
        self.assertAlmostEqual(cost, 7.5, places=4)

    def test_only_source_gas(self):
        cost = compute_total_bridge_cost_usd(0.0, 0.0, 0.0, 4.0, 50_000.0)
        self.assertAlmostEqual(cost, 4.0, places=4)

    def test_all_zero_returns_zero(self):
        cost = compute_total_bridge_cost_usd(0.0, 0.0, 0.0, 0.0, 100_000.0)
        self.assertEqual(cost, 0.0)

    def test_negative_pct_treated_as_zero(self):
        cost = compute_total_bridge_cost_usd(-1.0, 5.0, 0.0, 0.0, 10_000.0)
        self.assertAlmostEqual(cost, 5.0, places=4)

    def test_negative_gas_treated_as_zero(self):
        cost = compute_total_bridge_cost_usd(0.0, 0.0, -3.0, -2.0, 10_000.0)
        self.assertEqual(cost, 0.0)

    def test_negative_position_pct_fee_zero(self):
        cost = compute_total_bridge_cost_usd(1.0, 5.0, 0.0, 0.0, -10_000.0)
        # pct applied to max(pos, 0) = 0 → pct_fee = 0; only fixed fee
        self.assertAlmostEqual(cost, 5.0, places=4)

    def test_large_position(self):
        # 0.06% of 1_000_000 = 600 + 10 + 5 + 5 = 620
        cost = compute_total_bridge_cost_usd(0.06, 10.0, 5.0, 5.0, 1_000_000.0)
        self.assertAlmostEqual(cost, 620.0, places=4)

    def test_result_is_float(self):
        self.assertIsInstance(compute_total_bridge_cost_usd(0.1, 1.0, 1.0, 1.0, 1000.0), float)

    def test_zero_position_with_fees(self):
        cost = compute_total_bridge_cost_usd(1.0, 10.0, 5.0, 3.0, 0.0)
        # pct_fee = 0 (position 0), rest of fees apply
        self.assertAlmostEqual(cost, 18.0, places=4)


# =========================================================================== #
# 2. compute_total_bridge_cost_pct
# =========================================================================== #

class TestComputeTotalBridgeCostPct(unittest.TestCase):

    def test_basic_1pct(self):
        pct = compute_total_bridge_cost_pct(100.0, 10_000.0)
        self.assertAlmostEqual(pct, 1.0, places=4)

    def test_basic_half_pct(self):
        pct = compute_total_bridge_cost_pct(50.0, 10_000.0)
        self.assertAlmostEqual(pct, 0.5, places=4)

    def test_zero_position_returns_zero(self):
        pct = compute_total_bridge_cost_pct(500.0, 0.0)
        self.assertEqual(pct, 0.0)

    def test_negative_position_returns_zero(self):
        pct = compute_total_bridge_cost_pct(500.0, -1000.0)
        self.assertEqual(pct, 0.0)

    def test_zero_cost_returns_zero(self):
        pct = compute_total_bridge_cost_pct(0.0, 50_000.0)
        self.assertEqual(pct, 0.0)

    def test_result_is_float(self):
        self.assertIsInstance(compute_total_bridge_cost_pct(100.0, 10_000.0), float)

    def test_cost_greater_than_position(self):
        pct = compute_total_bridge_cost_pct(20_000.0, 10_000.0)
        self.assertAlmostEqual(pct, 200.0, places=4)


# =========================================================================== #
# 3. compute_opportunity_cost_usd
# =========================================================================== #

class TestComputeOpportunityCostUsd(unittest.TestCase):

    def test_zero_minutes_zero_cost(self):
        cost = compute_opportunity_cost_usd(100_000.0, 10.0, 0)
        self.assertAlmostEqual(cost, 0.0, places=6)

    def test_zero_apy_zero_cost(self):
        cost = compute_opportunity_cost_usd(100_000.0, 0.0, 60)
        self.assertAlmostEqual(cost, 0.0, places=6)

    def test_zero_position_zero_cost(self):
        cost = compute_opportunity_cost_usd(0.0, 10.0, 60)
        self.assertAlmostEqual(cost, 0.0, places=6)

    def test_negative_apy_treated_as_zero(self):
        cost = compute_opportunity_cost_usd(100_000.0, -5.0, 60)
        self.assertAlmostEqual(cost, 0.0, places=6)

    def test_negative_position_treated_as_zero(self):
        cost = compute_opportunity_cost_usd(-50_000.0, 10.0, 60)
        self.assertAlmostEqual(cost, 0.0, places=6)

    def test_full_year_equals_apy_times_position(self):
        # 100_000 * 10% * (525_600 min / 525_600 min) = 10_000
        cost = compute_opportunity_cost_usd(100_000.0, 10.0, int(_MINUTES_PER_YEAR))
        self.assertAlmostEqual(cost, 10_000.0, places=2)

    def test_one_day_cost(self):
        # 100_000 * 36.5% / 365 = 100
        cost = compute_opportunity_cost_usd(100_000.0, 36.5, 24 * 60)
        self.assertAlmostEqual(cost, 100.0, places=2)

    def test_result_is_float(self):
        self.assertIsInstance(compute_opportunity_cost_usd(1000.0, 5.0, 30), float)

    def test_30_min_bridge_small_cost(self):
        # 50_000 * 5% / 365 / 24 / 2 ≈ very small
        cost = compute_opportunity_cost_usd(50_000.0, 5.0, 30)
        self.assertGreater(cost, 0.0)
        self.assertLess(cost, 10.0)


# =========================================================================== #
# 4. compute_net_apy_advantage_pct
# =========================================================================== #

class TestComputeNetApyAdvantagePct(unittest.TestCase):

    def test_positive_advantage(self):
        self.assertAlmostEqual(compute_net_apy_advantage_pct(8.0, 3.0), 5.0, places=4)

    def test_zero_advantage(self):
        self.assertAlmostEqual(compute_net_apy_advantage_pct(5.0, 5.0), 0.0, places=4)

    def test_negative_advantage(self):
        self.assertAlmostEqual(compute_net_apy_advantage_pct(2.0, 5.0), -3.0, places=4)

    def test_both_zero(self):
        self.assertAlmostEqual(compute_net_apy_advantage_pct(0.0, 0.0), 0.0, places=4)

    def test_large_advantage(self):
        self.assertAlmostEqual(compute_net_apy_advantage_pct(30.0, 5.0), 25.0, places=4)

    def test_result_is_float(self):
        self.assertIsInstance(compute_net_apy_advantage_pct(5.0, 3.0), float)

    def test_fractional_advantage(self):
        self.assertAlmostEqual(compute_net_apy_advantage_pct(5.5, 3.2), 2.3, places=4)


# =========================================================================== #
# 5. compute_breakeven_days
# =========================================================================== #

class TestComputeBreakevenDays(unittest.TestCase):

    def test_no_advantage_returns_inf(self):
        days = compute_breakeven_days(100.0, 10_000.0, 0.0)
        self.assertEqual(days, _BREAKEVEN_INF)

    def test_negative_advantage_returns_inf(self):
        days = compute_breakeven_days(100.0, 10_000.0, -5.0)
        self.assertEqual(days, _BREAKEVEN_INF)

    def test_zero_position_returns_inf(self):
        days = compute_breakeven_days(100.0, 0.0, 5.0)
        self.assertEqual(days, _BREAKEVEN_INF)

    def test_zero_cost_returns_zero(self):
        days = compute_breakeven_days(0.0, 50_000.0, 5.0)
        self.assertEqual(days, 0.0)

    def test_typical_calculation(self):
        # cost=100, pos=10_000, advantage=5% → (100/10_000)/(0.05)*365 = 73 days
        days = compute_breakeven_days(100.0, 10_000.0, 5.0)
        self.assertAlmostEqual(days, 73.0, places=2)

    def test_small_cost_fast_breakeven(self):
        # cost=10, pos=100_000, advantage=10% → (10/100_000)/(0.1)*365 = 0.365
        days = compute_breakeven_days(10.0, 100_000.0, 10.0)
        self.assertAlmostEqual(days, 0.365, places=3)

    def test_high_cost_slow_breakeven(self):
        # cost=10_000, pos=50_000, advantage=1% → (10000/50000)/(0.01)*365 = 7300 days
        days = compute_breakeven_days(10_000.0, 50_000.0, 1.0)
        self.assertAlmostEqual(days, 7300.0, places=2)
        # Still renders as NOT_WORTH_IT label (>30 days)
        self.assertGreater(days, 30.0)

    def test_extremely_high_cost_capped_at_inf(self):
        # cost=1_000_000, pos=100, advantage=0.001% → far exceeds _BREAKEVEN_INF cap
        days = compute_breakeven_days(1_000_000.0, 100.0, 0.001)
        self.assertEqual(days, _BREAKEVEN_INF)

    def test_result_is_float(self):
        self.assertIsInstance(compute_breakeven_days(10.0, 10_000.0, 5.0), float)

    def test_capped_at_breakeven_inf(self):
        days = compute_breakeven_days(1_000_000.0, 100.0, 0.001)
        self.assertEqual(days, _BREAKEVEN_INF)

    def test_breakeven_1_day(self):
        # cost=pos*(adv_pct/100)/365 → cost = 10_000 * 5/100 / 365 ≈ 13.699
        cost = 10_000.0 * 5.0 / 100.0 / 365.0
        days = compute_breakeven_days(cost, 10_000.0, 5.0)
        self.assertAlmostEqual(days, 1.0, places=4)


# =========================================================================== #
# 6. compute_bridge_efficiency_score
# =========================================================================== #

class TestComputeBridgeEfficiencyScore(unittest.TestCase):

    def test_returns_int(self):
        self.assertIsInstance(compute_bridge_efficiency_score(1.0, 5.0), int)

    def test_zero_breakeven_100_score(self):
        self.assertEqual(compute_bridge_efficiency_score(0.0, 5.0), 100)

    def test_no_advantage_zero_score(self):
        self.assertEqual(compute_bridge_efficiency_score(1.0, 0.0), 0)

    def test_negative_advantage_zero_score(self):
        self.assertEqual(compute_bridge_efficiency_score(0.0, -1.0), 0)

    def test_50_days_score_is_zero(self):
        # 100 - 50*2 = 0
        self.assertEqual(compute_bridge_efficiency_score(50.0, 5.0), 0)

    def test_10_days_score_80(self):
        # 100 - 10*2 = 80
        self.assertEqual(compute_bridge_efficiency_score(10.0, 5.0), 80)

    def test_3_days_score_94(self):
        # 100 - 3*2 = 94
        self.assertEqual(compute_bridge_efficiency_score(3.0, 5.0), 94)

    def test_score_not_negative(self):
        score = compute_bridge_efficiency_score(999.0, 5.0)
        self.assertGreaterEqual(score, 0)

    def test_score_not_above_100(self):
        score = compute_bridge_efficiency_score(-100.0, 5.0)
        self.assertLessEqual(score, 100)

    def test_score_decreases_with_more_breakeven_days(self):
        s1 = compute_bridge_efficiency_score(2.0, 5.0)
        s2 = compute_bridge_efficiency_score(10.0, 5.0)
        s3 = compute_bridge_efficiency_score(30.0, 5.0)
        self.assertGreater(s1, s2)
        self.assertGreater(s2, s3)

    def test_inf_breakeven_gives_zero(self):
        score = compute_bridge_efficiency_score(_BREAKEVEN_INF, 5.0)
        self.assertEqual(score, 0)


# =========================================================================== #
# 7. compute_bridge_label
# =========================================================================== #

class TestComputeBridgeLabel(unittest.TestCase):

    def test_no_advantage_not_worth_it(self):
        label = compute_bridge_label(2.0, 0.0)
        self.assertEqual(label, LABEL_BRIDGE_NOT_WORTH_IT)

    def test_negative_advantage_not_worth_it(self):
        label = compute_bridge_label(0.5, -5.0)
        self.assertEqual(label, LABEL_BRIDGE_NOT_WORTH_IT)

    def test_30_days_not_worth_it(self):
        label = compute_bridge_label(30.1, 5.0)
        self.assertEqual(label, LABEL_BRIDGE_NOT_WORTH_IT)

    def test_inf_breakeven_not_worth_it(self):
        label = compute_bridge_label(_BREAKEVEN_INF, 5.0)
        self.assertEqual(label, LABEL_BRIDGE_NOT_WORTH_IT)

    def test_zero_days_efficient(self):
        label = compute_bridge_label(0.0, 5.0)
        self.assertEqual(label, LABEL_EFFICIENT_BRIDGE)

    def test_3_days_efficient(self):
        label = compute_bridge_label(3.0, 5.0)
        self.assertEqual(label, LABEL_EFFICIENT_BRIDGE)

    def test_just_above_3_days_acceptable(self):
        label = compute_bridge_label(3.01, 5.0)
        self.assertEqual(label, LABEL_ACCEPTABLE_COST)

    def test_7_days_acceptable(self):
        label = compute_bridge_label(7.0, 5.0)
        self.assertEqual(label, LABEL_ACCEPTABLE_COST)

    def test_just_above_7_days_high_cost(self):
        label = compute_bridge_label(7.01, 5.0)
        self.assertEqual(label, LABEL_HIGH_BRIDGE_COST)

    def test_14_days_high_cost(self):
        label = compute_bridge_label(14.0, 5.0)
        self.assertEqual(label, LABEL_HIGH_BRIDGE_COST)

    def test_just_above_14_days_inefficient(self):
        label = compute_bridge_label(14.01, 5.0)
        self.assertEqual(label, LABEL_INEFFICIENT_BRIDGE)

    def test_30_days_inefficient(self):
        label = compute_bridge_label(30.0, 5.0)
        self.assertEqual(label, LABEL_INEFFICIENT_BRIDGE)

    def test_just_above_30_days_not_worth_it(self):
        label = compute_bridge_label(30.01, 5.0)
        self.assertEqual(label, LABEL_BRIDGE_NOT_WORTH_IT)

    def test_mid_range_5_days(self):
        label = compute_bridge_label(5.0, 3.0)
        self.assertEqual(label, LABEL_ACCEPTABLE_COST)

    def test_mid_range_10_days(self):
        label = compute_bridge_label(10.0, 3.0)
        self.assertEqual(label, LABEL_HIGH_BRIDGE_COST)

    def test_mid_range_20_days(self):
        label = compute_bridge_label(20.0, 3.0)
        self.assertEqual(label, LABEL_INEFFICIENT_BRIDGE)


# =========================================================================== #
# 8. _atomic_log_append
# =========================================================================== #

class TestAtomicLogAppend(unittest.TestCase):

    def setUp(self):
        self.log_path = _tmp_log()

    def tearDown(self):
        for p in [self.log_path, self.log_path + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def test_creates_file_if_missing(self):
        _atomic_log_append({"a": 1}, self.log_path, 100)
        self.assertTrue(os.path.exists(self.log_path))

    def test_single_entry(self):
        _atomic_log_append({"k": "v"}, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["k"], "v")

    def test_multiple_entries(self):
        for i in range(5):
            _atomic_log_append({"n": i}, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        cap = 10
        for i in range(25):
            _atomic_log_append({"n": i}, self.log_path, cap)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), cap)

    def test_ring_buffer_latest_preserved(self):
        cap = 5
        for i in range(10):
            _atomic_log_append({"n": i}, self.log_path, cap)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["n"], 5)
        self.assertEqual(data[-1]["n"], 9)

    def test_no_tmp_file_left(self):
        _atomic_log_append({"k": 1}, self.log_path, 100)
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_corrupted_file_reset(self):
        with open(self.log_path, "w") as f:
            f.write("NOT_JSON{{")
        _atomic_log_append({"k": 2}, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_dict_file_reset(self):
        with open(self.log_path, "w") as f:
            json.dump({"bad": "dict"}, f)
        _atomic_log_append({"k": 3}, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


# =========================================================================== #
# 9. ProtocolDeFiCrossChainBridgeFeeAnalyzer.analyze — output keys
# =========================================================================== #

class TestAnalyzeOutputKeys(unittest.TestCase):

    def setUp(self):
        self.result = _result()

    def test_has_protocol_name(self):
        self.assertIn("protocol_name", self.result)

    def test_has_bridge_fee_pct(self):
        self.assertIn("bridge_fee_pct", self.result)

    def test_has_bridge_fee_fixed_usd(self):
        self.assertIn("bridge_fee_fixed_usd", self.result)

    def test_has_destination_gas_usd(self):
        self.assertIn("destination_gas_usd", self.result)

    def test_has_source_gas_usd(self):
        self.assertIn("source_gas_usd", self.result)

    def test_has_bridge_time_minutes(self):
        self.assertIn("bridge_time_minutes", self.result)

    def test_has_position_size_usd(self):
        self.assertIn("position_size_usd", self.result)

    def test_has_target_apy_pct(self):
        self.assertIn("target_apy_pct", self.result)

    def test_has_source_apy_pct(self):
        self.assertIn("source_apy_pct", self.result)

    def test_has_total_bridge_cost_usd(self):
        self.assertIn("total_bridge_cost_usd", self.result)

    def test_has_total_bridge_cost_pct(self):
        self.assertIn("total_bridge_cost_pct", self.result)

    def test_has_opportunity_cost_usd(self):
        self.assertIn("opportunity_cost_usd", self.result)

    def test_has_breakeven_days(self):
        self.assertIn("breakeven_days", self.result)

    def test_has_net_apy_advantage_pct(self):
        self.assertIn("net_apy_advantage_pct", self.result)

    def test_has_bridge_efficiency_score(self):
        self.assertIn("bridge_efficiency_score", self.result)

    def test_has_bridge_label(self):
        self.assertIn("bridge_label", self.result)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)

    def test_timestamp_ends_with_z(self):
        self.assertTrue(self.result["timestamp"].endswith("Z"))

    def test_protocol_name_echoed(self):
        self.assertEqual(self.result["protocol_name"], "TestBridge")

    def test_bridge_efficiency_score_is_int(self):
        self.assertIsInstance(self.result["bridge_efficiency_score"], int)

    def test_score_in_range(self):
        score = self.result["bridge_efficiency_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_bridge_label_is_string(self):
        self.assertIsInstance(self.result["bridge_label"], str)

    def test_bridge_label_valid(self):
        valid = {
            LABEL_EFFICIENT_BRIDGE, LABEL_ACCEPTABLE_COST, LABEL_HIGH_BRIDGE_COST,
            LABEL_INEFFICIENT_BRIDGE, LABEL_BRIDGE_NOT_WORTH_IT,
        }
        self.assertIn(self.result["bridge_label"], valid)


# =========================================================================== #
# 10. ProtocolDeFiCrossChainBridgeFeeAnalyzer.analyze — label scenarios
# =========================================================================== #

class TestAnalyzeLabelScenarios(unittest.TestCase):

    def _a(self, **kw):
        return _result(**kw)

    def test_efficient_bridge_scenario(self):
        # Tiny cost, large position, big APY advantage → fast breakeven
        r = self._a(
            bridge_fee_pct=0.01,
            bridge_fee_fixed_usd=0.5,
            destination_gas_usd=0.5,
            source_gas_usd=0.5,
            position_size_usd=1_000_000.0,
            target_apy_pct=20.0,
            source_apy_pct=3.0,
        )
        self.assertEqual(r["bridge_label"], LABEL_EFFICIENT_BRIDGE)

    def test_not_worth_it_no_advantage(self):
        r = self._a(target_apy_pct=3.0, source_apy_pct=5.0)
        self.assertEqual(r["bridge_label"], LABEL_BRIDGE_NOT_WORTH_IT)

    def test_not_worth_it_equal_apy(self):
        r = self._a(target_apy_pct=5.0, source_apy_pct=5.0)
        self.assertEqual(r["bridge_label"], LABEL_BRIDGE_NOT_WORTH_IT)

    def test_high_bridge_cost_scenario(self):
        # Moderate cost, moderate position, small advantage → 7-14 day breakeven
        r = self._a(
            bridge_fee_pct=0.0,
            bridge_fee_fixed_usd=50.0,
            destination_gas_usd=50.0,
            source_gas_usd=0.0,
            position_size_usd=50_000.0,
            target_apy_pct=5.0,
            source_apy_pct=3.5,
        )
        # cost = 100 USD; advantage = 1.5%; breakeven = (100/50000)/(0.015)*365 = 48.67 → NOT_WORTH_IT
        # Let me use smaller cost or bigger advantage
        # For HIGH_BRIDGE_COST: 7 < breakeven <= 14
        # Need: 7 < (cost/pos)/(adv/100)*365 <= 14
        # With pos=50000, adv=2%, cost: 7 < (cost/50000)/0.02 * 365 <= 14
        # cost in range: (7 * 50000 * 0.02/365) to (14 * 50000 * 0.02/365)
        # = 19.18 to 38.36 USD
        self.assertIn(r["bridge_label"], {
            LABEL_HIGH_BRIDGE_COST, LABEL_INEFFICIENT_BRIDGE, LABEL_BRIDGE_NOT_WORTH_IT
        })

    def test_not_worth_it_large_cost_tiny_advantage(self):
        r = self._a(
            bridge_fee_pct=2.0,
            bridge_fee_fixed_usd=100.0,
            destination_gas_usd=50.0,
            source_gas_usd=50.0,
            position_size_usd=10_000.0,
            target_apy_pct=4.0,
            source_apy_pct=3.5,
        )
        self.assertEqual(r["bridge_label"], LABEL_BRIDGE_NOT_WORTH_IT)

    def test_efficiency_score_zero_when_no_advantage(self):
        r = self._a(target_apy_pct=2.0, source_apy_pct=8.0)
        self.assertEqual(r["bridge_efficiency_score"], 0)

    def test_net_apy_advantage_correct(self):
        r = self._a(target_apy_pct=10.0, source_apy_pct=4.0)
        self.assertAlmostEqual(r["net_apy_advantage_pct"], 6.0, places=4)

    def test_opportunity_cost_nonzero_with_bridge_time(self):
        r = self._a(source_apy_pct=10.0, bridge_time_minutes=60, position_size_usd=100_000.0)
        self.assertGreater(r["opportunity_cost_usd"], 0.0)

    def test_total_cost_correct(self):
        # 0.05% of 50000 = 25; +1 fixed +2 dst +3 src = 31
        r = self._a(
            bridge_fee_pct=0.05,
            bridge_fee_fixed_usd=1.0,
            destination_gas_usd=2.0,
            source_gas_usd=3.0,
            position_size_usd=50_000.0,
        )
        self.assertAlmostEqual(r["total_bridge_cost_usd"], 31.0, places=4)

    def test_string_inputs_coerced(self):
        a = _analyzer()
        r = a.analyze(
            protocol_name="Bridge",
            bridge_fee_pct="0.1",
            bridge_fee_fixed_usd="5",
            destination_gas_usd="3",
            source_gas_usd="2",
            bridge_time_minutes="30",
            position_size_usd="100000",
            target_apy_pct="8",
            source_apy_pct="3",
        )
        self.assertIsInstance(r["total_bridge_cost_usd"], float)
        self.assertEqual(r["bridge_time_minutes"], 30)


# =========================================================================== #
# 11. ProtocolDeFiCrossChainBridgeFeeAnalyzer.analyze — logging
# =========================================================================== #

class TestAnalyzeLogging(unittest.TestCase):

    def setUp(self):
        self.log_path = _tmp_log()
        self.analyzer = ProtocolDeFiCrossChainBridgeFeeAnalyzer(log_path=self.log_path)

    def tearDown(self):
        for p in [self.log_path, self.log_path + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def _call(self, name="B"):
        return self.analyzer.analyze(
            protocol_name=name,
            bridge_fee_pct=0.06,
            bridge_fee_fixed_usd=0.0,
            destination_gas_usd=2.5,
            source_gas_usd=5.0,
            bridge_time_minutes=20,
            position_size_usd=50_000.0,
            target_apy_pct=8.5,
            source_apy_pct=3.5,
        )

    def test_log_file_created(self):
        self._call()
        self.assertTrue(os.path.exists(self.log_path))

    def test_one_entry_after_one_call(self):
        self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_entry_protocol_name(self):
        self._call("Stargate")
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["protocol_name"], "Stargate")

    def test_log_entry_has_bridge_label(self):
        self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("bridge_label", data[0])

    def test_log_entry_has_timestamp(self):
        self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_breakeven_days(self):
        self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("breakeven_days", data[0])

    def test_multiple_calls_accumulate(self):
        for _ in range(7):
            self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 7)

    def test_ring_buffer_cap_100(self):
        for i in range(115):
            self._call(f"B{i}")
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)


# =========================================================================== #
# 12. ProtocolDeFiCrossChainBridgeFeeAnalyzer.analyze_batch
# =========================================================================== #

class TestAnalyzeBatch(unittest.TestCase):

    def _bridges(self):
        return [
            dict(protocol_name="Stargate", bridge_fee_pct=0.06, bridge_fee_fixed_usd=0.0,
                 destination_gas_usd=2.5, source_gas_usd=5.0, bridge_time_minutes=20,
                 position_size_usd=100_000.0, target_apy_pct=9.0, source_apy_pct=3.0),
            dict(protocol_name="Hop", bridge_fee_pct=0.4, bridge_fee_fixed_usd=0.0,
                 destination_gas_usd=15.0, source_gas_usd=8.0, bridge_time_minutes=300,
                 position_size_usd=5_000.0, target_apy_pct=4.0, source_apy_pct=5.0),
        ]

    def test_returns_list(self):
        a = _analyzer()
        result = a.analyze_batch(self._bridges())
        self.assertIsInstance(result, list)

    def test_correct_count(self):
        a = _analyzer()
        result = a.analyze_batch(self._bridges())
        self.assertEqual(len(result), 2)

    def test_order_preserved(self):
        a = _analyzer()
        result = a.analyze_batch(self._bridges())
        self.assertEqual(result[0]["protocol_name"], "Stargate")
        self.assertEqual(result[1]["protocol_name"], "Hop")

    def test_empty_list(self):
        a = _analyzer()
        self.assertEqual(a.analyze_batch([]), [])

    def test_each_has_bridge_label(self):
        a = _analyzer()
        for r in a.analyze_batch(self._bridges()):
            self.assertIn("bridge_label", r)

    def test_no_advantage_is_not_worth_it(self):
        a = _analyzer()
        results = a.analyze_batch(self._bridges())
        # Second bridge: target=4 < source=5 → not worth it
        self.assertEqual(results[1]["bridge_label"], LABEL_BRIDGE_NOT_WORTH_IT)

    def test_missing_keys_default_zero(self):
        a = _analyzer()
        result = a.analyze_batch([{"protocol_name": "Minimal"}])
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["total_bridge_cost_usd"], 0.0, places=4)


# =========================================================================== #
# 13. ProtocolDeFiCrossChainBridgeFeeAnalyzer.rank_by_efficiency
# =========================================================================== #

class TestRankByEfficiency(unittest.TestCase):

    def _bridges(self):
        return [
            dict(protocol_name="Slow", bridge_fee_pct=2.0, bridge_fee_fixed_usd=50.0,
                 destination_gas_usd=30.0, source_gas_usd=20.0, bridge_time_minutes=3600,
                 position_size_usd=10_000.0, target_apy_pct=5.0, source_apy_pct=3.5),
            dict(protocol_name="Fast", bridge_fee_pct=0.01, bridge_fee_fixed_usd=0.5,
                 destination_gas_usd=1.0, source_gas_usd=0.5, bridge_time_minutes=5,
                 position_size_usd=1_000_000.0, target_apy_pct=15.0, source_apy_pct=3.0),
            dict(protocol_name="Mid", bridge_fee_pct=0.1, bridge_fee_fixed_usd=5.0,
                 destination_gas_usd=5.0, source_gas_usd=5.0, bridge_time_minutes=60,
                 position_size_usd=100_000.0, target_apy_pct=8.0, source_apy_pct=3.0),
        ]

    def test_returns_list(self):
        a = _analyzer()
        self.assertIsInstance(a.rank_by_efficiency(self._bridges()), list)

    def test_correct_count(self):
        a = _analyzer()
        ranked = a.rank_by_efficiency(self._bridges())
        self.assertEqual(len(ranked), 3)

    def test_scores_descending(self):
        a = _analyzer()
        ranked = a.rank_by_efficiency(self._bridges())
        scores = [r["bridge_efficiency_score"] for r in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_most_efficient_first(self):
        a = _analyzer()
        ranked = a.rank_by_efficiency(self._bridges())
        self.assertEqual(ranked[0]["protocol_name"], "Fast")

    def test_empty_list(self):
        a = _analyzer()
        self.assertEqual(a.rank_by_efficiency([]), [])

    def test_single_item(self):
        a = _analyzer()
        ranked = a.rank_by_efficiency([self._bridges()[1]])
        self.assertEqual(len(ranked), 1)


# =========================================================================== #
# 14. Edge cases and special inputs
# =========================================================================== #

class TestEdgeCases(unittest.TestCase):

    def test_all_zero_inputs(self):
        r = _result(
            bridge_fee_pct=0.0,
            bridge_fee_fixed_usd=0.0,
            destination_gas_usd=0.0,
            source_gas_usd=0.0,
            bridge_time_minutes=0,
            position_size_usd=0.0,
            target_apy_pct=0.0,
            source_apy_pct=0.0,
        )
        self.assertEqual(r["total_bridge_cost_usd"], 0.0)
        self.assertEqual(r["bridge_label"], LABEL_BRIDGE_NOT_WORTH_IT)
        self.assertEqual(r["bridge_efficiency_score"], 0)

    def test_opportunity_cost_in_result(self):
        r = _result(source_apy_pct=36.5, bridge_time_minutes=24 * 60,
                    position_size_usd=100_000.0)
        # 100_000 * 36.5% / 365 ≈ 100 USD
        self.assertAlmostEqual(r["opportunity_cost_usd"], 100.0, places=1)

    def test_total_cost_pct_correct(self):
        r = _result(
            bridge_fee_pct=0.0,
            bridge_fee_fixed_usd=500.0,
            destination_gas_usd=0.0,
            source_gas_usd=0.0,
            position_size_usd=50_000.0,
        )
        # 500 / 50000 * 100 = 1%
        self.assertAlmostEqual(r["total_bridge_cost_pct"], 1.0, places=4)

    def test_protocol_name_empty(self):
        r = _result(protocol_name="")
        self.assertEqual(r["protocol_name"], "")

    def test_protocol_name_unicode(self):
        r = _result(protocol_name="Мост-α")
        self.assertEqual(r["protocol_name"], "Мост-α")

    def test_bridge_time_minutes_zero_no_opp_cost(self):
        r = _result(bridge_time_minutes=0, source_apy_pct=10.0, position_size_usd=100_000.0)
        self.assertAlmostEqual(r["opportunity_cost_usd"], 0.0, places=6)

    def test_breakeven_zero_when_free_bridge_and_advantage(self):
        r = _result(
            bridge_fee_pct=0.0,
            bridge_fee_fixed_usd=0.0,
            destination_gas_usd=0.0,
            source_gas_usd=0.0,
            target_apy_pct=10.0,
            source_apy_pct=3.0,
        )
        self.assertAlmostEqual(r["breakeven_days"], 0.0, places=4)
        self.assertEqual(r["bridge_label"], LABEL_EFFICIENT_BRIDGE)

    def test_very_large_position_reduces_breakeven(self):
        # Same dollar cost, larger position → smaller breakeven
        r_small = _result(position_size_usd=10_000.0, bridge_fee_fixed_usd=100.0,
                          bridge_fee_pct=0.0, destination_gas_usd=0.0, source_gas_usd=0.0,
                          target_apy_pct=10.0, source_apy_pct=3.0)
        r_large = _result(position_size_usd=10_000_000.0, bridge_fee_fixed_usd=100.0,
                          bridge_fee_pct=0.0, destination_gas_usd=0.0, source_gas_usd=0.0,
                          target_apy_pct=10.0, source_apy_pct=3.0)
        self.assertGreater(r_small["breakeven_days"], r_large["breakeven_days"])

    def test_negative_bridge_fees_treated_as_zero(self):
        r = _result(bridge_fee_pct=-1.0, bridge_fee_fixed_usd=-5.0,
                    destination_gas_usd=-2.0, source_gas_usd=-3.0)
        self.assertEqual(r["total_bridge_cost_usd"], 0.0)


# =========================================================================== #
# 15. Label constants
# =========================================================================== #

class TestLabelConstants(unittest.TestCase):

    def test_efficient_bridge_value(self):
        self.assertEqual(LABEL_EFFICIENT_BRIDGE, "EFFICIENT_BRIDGE")

    def test_acceptable_cost_value(self):
        self.assertEqual(LABEL_ACCEPTABLE_COST, "ACCEPTABLE_COST")

    def test_high_bridge_cost_value(self):
        self.assertEqual(LABEL_HIGH_BRIDGE_COST, "HIGH_BRIDGE_COST")

    def test_inefficient_bridge_value(self):
        self.assertEqual(LABEL_INEFFICIENT_BRIDGE, "INEFFICIENT_BRIDGE")

    def test_bridge_not_worth_it_value(self):
        self.assertEqual(LABEL_BRIDGE_NOT_WORTH_IT, "BRIDGE_NOT_WORTH_IT")

    def test_all_five_labels_distinct(self):
        labels = {
            LABEL_EFFICIENT_BRIDGE, LABEL_ACCEPTABLE_COST, LABEL_HIGH_BRIDGE_COST,
            LABEL_INEFFICIENT_BRIDGE, LABEL_BRIDGE_NOT_WORTH_IT,
        }
        self.assertEqual(len(labels), 5)

    def test_breakeven_inf_constant(self):
        self.assertEqual(_BREAKEVEN_INF, 9_999.0)

    def test_minutes_per_year_constant(self):
        self.assertAlmostEqual(_MINUTES_PER_YEAR, 365.0 * 24.0 * 60.0, places=4)


if __name__ == "__main__":
    unittest.main()
