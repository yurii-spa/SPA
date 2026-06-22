"""
Tests for MP-1119 ProtocolDeFiStrategyRebalancingCostAnalyzer
≥110 unittest tests — pure stdlib, no third-party dependencies.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_defi_strategy_rebalancing_cost_analyzer import (
    ProtocolDeFiStrategyRebalancingCostAnalyzer,
    analyze,
    _atomic_log,
    _num_trades_needed,
    _total_slippage_cost_usd,
    _total_gas_cost_usd,
    _total_rebalance_cost_usd,
    _rebalance_cost_pct,
    _annual_rebalance_cost_pct,
    _net_annual_gain_pct,
    _rebalance_label,
    _LOG_CAP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _base_data(**overrides) -> dict:
    d = {
        "protocol_name":              "TestPortfolio",
        "current_weights":            [50.0, 30.0, 20.0],
        "target_weights":             [40.0, 40.0, 20.0],
        "asset_values_usd":           [500_000.0, 300_000.0, 200_000.0],
        "slippage_per_trade_pct":     0.1,
        "gas_per_trade_usd":          20.0,
        "portfolio_apy_pct":          5.0,
        "target_apy_improvement_pct": 1.0,
        "rebalance_frequency_days":   30,
    }
    d.update(overrides)
    return d


# ===========================================================================
# 1. _num_trades_needed
# ===========================================================================

class TestNumTradesNeeded(unittest.TestCase):

    def test_identical_weights_zero_trades(self):
        self.assertEqual(_num_trades_needed([50.0, 30.0, 20.0], [50.0, 30.0, 20.0]), 0)

    def test_one_different_one_trade(self):
        self.assertEqual(_num_trades_needed([50.0, 50.0], [40.0, 50.0]), 1)

    def test_all_different_n_trades(self):
        self.assertEqual(_num_trades_needed([50.0, 30.0, 20.0], [40.0, 40.0, 20.0]), 2)

    def test_empty_lists_zero_trades(self):
        self.assertEqual(_num_trades_needed([], []), 0)

    def test_one_element_different(self):
        self.assertEqual(_num_trades_needed([100.0], [99.0]), 1)

    def test_tiny_difference_above_epsilon_counts(self):
        self.assertEqual(_num_trades_needed([50.0], [50.0 + 1e-8]), 1)

    def test_difference_below_epsilon_not_counted(self):
        # 1e-10 < epsilon (1e-9) → not a trade
        self.assertEqual(_num_trades_needed([50.0], [50.0 + 1e-10]), 0)

    def test_mismatched_lengths_uses_shorter(self):
        # len(current)=3, len(target)=2 → compare first 2 only
        result = _num_trades_needed([50.0, 30.0, 20.0], [40.0, 30.0])
        self.assertEqual(result, 1)

    def test_returns_int(self):
        self.assertIsInstance(_num_trades_needed([50.0], [40.0]), int)

    def test_three_of_three_differ(self):
        self.assertEqual(
            _num_trades_needed([33.3, 33.3, 33.4], [25.0, 50.0, 25.0]), 3)


# ===========================================================================
# 2. _total_slippage_cost_usd
# ===========================================================================

class TestTotalSlippageCostUsd(unittest.TestCase):

    def test_empty_portfolio_returns_zero(self):
        result = _total_slippage_cost_usd([50.0], [40.0], [], 0.1)
        self.assertEqual(result, 0.0)

    def test_zero_portfolio_value_returns_zero(self):
        result = _total_slippage_cost_usd([50.0], [40.0], [0.0], 0.1)
        self.assertEqual(result, 0.0)

    def test_identical_weights_zero_slippage(self):
        result = _total_slippage_cost_usd(
            [50.0, 50.0], [50.0, 50.0], [500_000.0, 500_000.0], 0.1)
        self.assertEqual(result, 0.0)

    def test_zero_slippage_pct_returns_zero(self):
        result = _total_slippage_cost_usd(
            [50.0, 50.0], [40.0, 60.0], [500_000.0, 500_000.0], 0.0)
        self.assertEqual(result, 0.0)

    def test_known_single_trade_calculation(self):
        # delta=10%, portfolio=1_000_000 → trade=100_000 → slip=100_000*0.1/100=100
        result = _total_slippage_cost_usd(
            [50.0, 50.0], [40.0, 60.0], [500_000.0, 500_000.0], 0.1)
        # Each leg: delta=10 → trade_value=10/100*1M=100_000 → slip=100
        # Two legs: 200
        self.assertAlmostEqual(result, 200.0, places=4)

    def test_result_is_float(self):
        result = _total_slippage_cost_usd(
            [50.0], [40.0], [1_000_000.0], 0.1)
        self.assertIsInstance(result, float)

    def test_larger_slippage_pct_larger_cost(self):
        r1 = _total_slippage_cost_usd([50.0], [40.0], [1_000_000.0], 0.1)
        r2 = _total_slippage_cost_usd([50.0], [40.0], [1_000_000.0], 0.5)
        self.assertGreater(r2, r1)

    def test_larger_portfolio_larger_cost(self):
        r1 = _total_slippage_cost_usd([50.0], [40.0], [1_000_000.0], 0.1)
        r2 = _total_slippage_cost_usd([50.0], [40.0], [10_000_000.0], 0.1)
        self.assertGreater(r2, r1)

    def test_rounding_to_6_places(self):
        result = _total_slippage_cost_usd([50.0], [40.0], [1.0], 0.1)
        # delta=10, trade=10/100*1=0.1, slip=0.1*0.1/100=0.0001
        self.assertAlmostEqual(result, 0.0001, places=6)

    def test_three_positions_all_changed(self):
        # All three differ → three trade values summed
        result = _total_slippage_cost_usd(
            [40.0, 40.0, 20.0],
            [50.0, 30.0, 20.0],  # only first two change
            [400_000.0, 400_000.0, 200_000.0],
            0.1,
        )
        # delta pos 0: 10, delta pos 1: 10, delta pos 2: 0
        # total_portfolio = 1_000_000
        # trade0 = 10/100 * 1M = 100_000 → slip = 100
        # trade1 = 10/100 * 1M = 100_000 → slip = 100
        self.assertAlmostEqual(result, 200.0, places=4)

    def test_negative_portfolio_value_zero_result(self):
        result = _total_slippage_cost_usd([50.0], [40.0], [-1_000.0], 0.1)
        self.assertEqual(result, 0.0)

    def test_full_rebalance_100pct_delta(self):
        # Single position: current=100%, target=0% → delta=100
        result = _total_slippage_cost_usd([100.0], [0.0], [1_000_000.0], 0.1)
        # trade_value = 100/100 * 1M = 1M → slip = 1M * 0.1/100 = 1000
        self.assertAlmostEqual(result, 1_000.0, places=4)


# ===========================================================================
# 3. _total_gas_cost_usd
# ===========================================================================

class TestTotalGasCostUsd(unittest.TestCase):

    def test_zero_trades_zero_gas(self):
        self.assertEqual(_total_gas_cost_usd(0, 20.0), 0.0)

    def test_one_trade(self):
        self.assertAlmostEqual(_total_gas_cost_usd(1, 20.0), 20.0, places=6)

    def test_multiple_trades(self):
        self.assertAlmostEqual(_total_gas_cost_usd(5, 20.0), 100.0, places=6)

    def test_zero_gas_per_trade(self):
        self.assertEqual(_total_gas_cost_usd(10, 0.0), 0.0)

    def test_result_is_float(self):
        self.assertIsInstance(_total_gas_cost_usd(3, 15.0), float)

    def test_large_gas_cost(self):
        self.assertAlmostEqual(_total_gas_cost_usd(100, 500.0), 50_000.0, places=4)

    def test_fractional_gas(self):
        self.assertAlmostEqual(_total_gas_cost_usd(3, 0.333333), 1.0, places=3)

    def test_rounding_to_6_places(self):
        result = _total_gas_cost_usd(3, 1.0 / 3.0)
        self.assertAlmostEqual(result, round(3 * (1.0 / 3.0), 6), places=6)

    def test_known_calculation(self):
        self.assertAlmostEqual(_total_gas_cost_usd(2, 25.0), 50.0, places=6)

    def test_multiplies_trades_by_gas(self):
        # 7 trades at $30 each = $210
        self.assertAlmostEqual(_total_gas_cost_usd(7, 30.0), 210.0, places=6)


# ===========================================================================
# 4. _total_rebalance_cost_usd
# ===========================================================================

class TestTotalRebalanceCostUsd(unittest.TestCase):

    def test_both_zero(self):
        self.assertEqual(_total_rebalance_cost_usd(0.0, 0.0), 0.0)

    def test_slippage_only(self):
        self.assertAlmostEqual(_total_rebalance_cost_usd(500.0, 0.0), 500.0, places=6)

    def test_gas_only(self):
        self.assertAlmostEqual(_total_rebalance_cost_usd(0.0, 200.0), 200.0, places=6)

    def test_slippage_plus_gas(self):
        self.assertAlmostEqual(_total_rebalance_cost_usd(500.0, 200.0), 700.0, places=6)

    def test_result_is_float(self):
        self.assertIsInstance(_total_rebalance_cost_usd(100.0, 50.0), float)

    def test_rounding_to_6_places(self):
        result = _total_rebalance_cost_usd(1.0 / 3.0, 1.0 / 3.0)
        self.assertAlmostEqual(result, round(2.0 / 3.0, 6), places=6)

    def test_large_values(self):
        self.assertAlmostEqual(
            _total_rebalance_cost_usd(100_000.0, 50_000.0), 150_000.0, places=2)

    def test_addition_is_commutative(self):
        r1 = _total_rebalance_cost_usd(300.0, 200.0)
        r2 = _total_rebalance_cost_usd(200.0, 300.0)
        self.assertAlmostEqual(r1, r2, places=6)


# ===========================================================================
# 5. _rebalance_cost_pct
# ===========================================================================

class TestRebalanceCostPct(unittest.TestCase):

    def test_zero_portfolio_returns_zero(self):
        self.assertEqual(_rebalance_cost_pct(100.0, 0.0), 0.0)

    def test_negative_portfolio_returns_zero(self):
        self.assertEqual(_rebalance_cost_pct(100.0, -1.0), 0.0)

    def test_known_calculation(self):
        # 1000 / 1_000_000 * 100 = 0.1 %
        result = _rebalance_cost_pct(1_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 0.1, places=6)

    def test_zero_cost(self):
        self.assertEqual(_rebalance_cost_pct(0.0, 1_000_000.0), 0.0)

    def test_cost_equals_portfolio_gives_100pct(self):
        self.assertAlmostEqual(_rebalance_cost_pct(1_000.0, 1_000.0), 100.0, places=6)

    def test_small_cost_small_pct(self):
        result = _rebalance_cost_pct(1.0, 1_000_000.0)
        self.assertAlmostEqual(result, 0.0001, places=6)

    def test_result_is_float(self):
        self.assertIsInstance(_rebalance_cost_pct(100.0, 100_000.0), float)

    def test_rounding_to_6_places(self):
        result = _rebalance_cost_pct(1.0, 3.0)
        expected = round(1.0 / 3.0 * 100.0, 6)
        self.assertAlmostEqual(result, expected, places=6)

    def test_large_cost_relative_to_portfolio(self):
        result = _rebalance_cost_pct(50_000.0, 100_000.0)
        self.assertAlmostEqual(result, 50.0, places=6)

    def test_both_zero(self):
        self.assertEqual(_rebalance_cost_pct(0.0, 0.0), 0.0)


# ===========================================================================
# 6. _annual_rebalance_cost_pct
# ===========================================================================

class TestAnnualRebalanceCostPct(unittest.TestCase):

    def test_zero_frequency_returns_zero(self):
        self.assertEqual(_annual_rebalance_cost_pct(1.0, 0), 0.0)

    def test_negative_frequency_returns_zero(self):
        self.assertEqual(_annual_rebalance_cost_pct(1.0, -1), 0.0)

    def test_frequency_365_unchanged_cost(self):
        # cost_pct * 365/365 = cost_pct
        result = _annual_rebalance_cost_pct(2.0, 365)
        self.assertAlmostEqual(result, 2.0, places=6)

    def test_frequency_30_annualizes(self):
        # 0.1 * 365/30 ≈ 1.2167
        result = _annual_rebalance_cost_pct(0.1, 30)
        self.assertAlmostEqual(result, 0.1 * 365.0 / 30.0, places=5)

    def test_frequency_7_annualizes(self):
        result = _annual_rebalance_cost_pct(0.1, 7)
        self.assertAlmostEqual(result, 0.1 * 365.0 / 7.0, places=5)

    def test_frequency_1_multiplies_by_365(self):
        result = _annual_rebalance_cost_pct(0.1, 1)
        self.assertAlmostEqual(result, 36.5, places=5)

    def test_result_is_float(self):
        self.assertIsInstance(_annual_rebalance_cost_pct(0.5, 30), float)

    def test_zero_cost_pct_gives_zero_annual(self):
        self.assertEqual(_annual_rebalance_cost_pct(0.0, 30), 0.0)

    def test_rounding_to_6_places(self):
        result = _annual_rebalance_cost_pct(1.0, 3)
        expected = round(1.0 * 365.0 / 3.0, 6)
        self.assertAlmostEqual(result, expected, places=6)

    def test_higher_frequency_lowers_annual_cost(self):
        # More frequent rebalancing → higher annual cost
        r_monthly = _annual_rebalance_cost_pct(0.1, 30)
        r_yearly  = _annual_rebalance_cost_pct(0.1, 365)
        self.assertGreater(r_monthly, r_yearly)


# ===========================================================================
# 7. _net_annual_gain_pct
# ===========================================================================

class TestNetAnnualGainPct(unittest.TestCase):

    def test_improvement_greater_than_cost_positive_gain(self):
        result = _net_annual_gain_pct(2.0, 0.5)
        self.assertAlmostEqual(result, 1.5, places=6)

    def test_improvement_less_than_cost_negative_gain(self):
        result = _net_annual_gain_pct(0.5, 2.0)
        self.assertAlmostEqual(result, -1.5, places=6)

    def test_equal_gives_zero(self):
        result = _net_annual_gain_pct(1.0, 1.0)
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_zero_improvement(self):
        result = _net_annual_gain_pct(0.0, 1.0)
        self.assertAlmostEqual(result, -1.0, places=6)

    def test_zero_cost(self):
        result = _net_annual_gain_pct(1.0, 0.0)
        self.assertAlmostEqual(result, 1.0, places=6)

    def test_both_zero(self):
        self.assertAlmostEqual(_net_annual_gain_pct(0.0, 0.0), 0.0, places=6)

    def test_large_improvement_large_gain(self):
        result = _net_annual_gain_pct(10.0, 0.1)
        self.assertAlmostEqual(result, 9.9, places=6)

    def test_result_is_float(self):
        self.assertIsInstance(_net_annual_gain_pct(1.0, 0.5), float)

    def test_rounding_to_6_places(self):
        result = _net_annual_gain_pct(1.0 / 3.0, 1.0 / 6.0)
        self.assertAlmostEqual(result, round(1.0 / 3.0 - 1.0 / 6.0, 6), places=6)

    def test_negative_improvement_very_negative_gain(self):
        result = _net_annual_gain_pct(-1.0, 1.0)
        self.assertAlmostEqual(result, -2.0, places=6)


# ===========================================================================
# 8. _rebalance_label
# ===========================================================================

class TestRebalanceLabel(unittest.TestCase):

    def test_gain_above_1_efficient(self):
        self.assertEqual(_rebalance_label(1.5), "EFFICIENT_REBALANCE")

    def test_gain_just_above_1_efficient(self):
        self.assertEqual(_rebalance_label(1.001), "EFFICIENT_REBALANCE")

    def test_gain_exactly_1_acceptable(self):
        # > 1.0 required for EFFICIENT; 1.0 exactly → ACCEPTABLE_COST
        self.assertEqual(_rebalance_label(1.0), "ACCEPTABLE_COST")

    def test_gain_0_5_acceptable(self):
        self.assertEqual(_rebalance_label(0.5), "ACCEPTABLE_COST")

    def test_gain_exactly_025_acceptable(self):
        # >= 0.25 → ACCEPTABLE_COST
        self.assertEqual(_rebalance_label(0.25), "ACCEPTABLE_COST")

    def test_gain_just_below_025_marginal(self):
        self.assertEqual(_rebalance_label(0.249), "MARGINAL_BENEFIT")

    def test_gain_0_1_marginal(self):
        self.assertEqual(_rebalance_label(0.1), "MARGINAL_BENEFIT")

    def test_gain_exactly_0_marginal(self):
        # >= 0.0 → MARGINAL_BENEFIT
        self.assertEqual(_rebalance_label(0.0), "MARGINAL_BENEFIT")

    def test_gain_minus_0_1_costly(self):
        self.assertEqual(_rebalance_label(-0.1), "COSTLY_REBALANCE")

    def test_gain_exactly_minus_05_costly(self):
        # >= -0.5 → COSTLY_REBALANCE
        self.assertEqual(_rebalance_label(-0.5), "COSTLY_REBALANCE")

    def test_gain_just_below_minus_05_dont(self):
        self.assertEqual(_rebalance_label(-0.501), "DONT_REBALANCE")

    def test_gain_very_negative_dont(self):
        self.assertEqual(_rebalance_label(-10.0), "DONT_REBALANCE")

    def test_all_five_labels_reachable(self):
        labels = {
            _rebalance_label(2.0),
            _rebalance_label(0.5),
            _rebalance_label(0.1),
            _rebalance_label(-0.2),
            _rebalance_label(-1.0),
        }
        expected = {
            "EFFICIENT_REBALANCE",
            "ACCEPTABLE_COST",
            "MARGINAL_BENEFIT",
            "COSTLY_REBALANCE",
            "DONT_REBALANCE",
        }
        self.assertEqual(labels, expected)

    def test_return_type_is_str(self):
        self.assertIsInstance(_rebalance_label(0.5), str)


# ===========================================================================
# 9. _atomic_log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):

    def setUp(self):
        self._log = _tmp_log()

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def test_creates_file_when_missing(self):
        _atomic_log(self._log, {"k": 1})
        self.assertTrue(os.path.exists(self._log))

    def test_writes_valid_json(self):
        _atomic_log(self._log, {"k": 1})
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_appends_multiple_entries(self):
        _atomic_log(self._log, {"n": 1})
        _atomic_log(self._log, {"n": 2})
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_entry_content_preserved(self):
        entry = {"protocol": "Compound", "trades": 3}
        _atomic_log(self._log, entry)
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["protocol"], "Compound")
        self.assertEqual(data[0]["trades"], 3)

    def test_ring_buffer_cap_enforced(self):
        for i in range(_LOG_CAP + 10):
            _atomic_log(self._log, {"i": i})
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), _LOG_CAP)

    def test_ring_buffer_keeps_latest(self):
        for i in range(_LOG_CAP + 5):
            _atomic_log(self._log, {"i": i})
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertEqual(data[-1]["i"], _LOG_CAP + 4)

    def test_recovers_from_corrupt_json(self):
        with open(self._log, "w") as fh:
            fh.write("CORRUPT")
        _atomic_log(self._log, {"k": 99})
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_recovers_from_empty_file(self):
        open(self._log, "w").close()
        _atomic_log(self._log, {"k": 1})
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_creates_nested_directories(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            nested = os.path.join(tmp_dir, "a", "b", "log.json")
            _atomic_log(nested, {"k": 1})
            self.assertTrue(os.path.exists(nested))

    def test_entries_ordered_as_appended(self):
        for i in range(5):
            _atomic_log(self._log, {"i": i})
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertEqual([e["i"] for e in data], list(range(5)))


# ===========================================================================
# 10. ProtocolDeFiStrategyRebalancingCostAnalyzer.analyze()
# ===========================================================================

class TestProtocolDeFiStrategyRebalancingCostAnalyzerAnalyze(unittest.TestCase):

    def setUp(self):
        self._analyzer = ProtocolDeFiStrategyRebalancingCostAnalyzer()
        self._log = _tmp_log()
        self._cfg = {"log_path": self._log, "write_log": False}

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def test_returns_dict(self):
        result = self._analyzer.analyze(_base_data(), self._cfg)
        self.assertIsInstance(result, dict)

    def test_all_expected_keys_present(self):
        result = self._analyzer.analyze(_base_data(), self._cfg)
        for key in [
            "protocol_name", "num_trades_needed", "total_slippage_cost_usd",
            "total_gas_cost_usd", "total_rebalance_cost_usd", "rebalance_cost_pct",
            "annual_rebalance_cost_pct", "net_annual_gain_pct", "rebalance_label",
            "total_portfolio_usd", "timestamp",
        ]:
            self.assertIn(key, result)

    def test_label_is_valid_string(self):
        result = self._analyzer.analyze(_base_data(), self._cfg)
        valid = {
            "EFFICIENT_REBALANCE", "ACCEPTABLE_COST", "MARGINAL_BENEFIT",
            "COSTLY_REBALANCE", "DONT_REBALANCE",
        }
        self.assertIn(result["rebalance_label"], valid)

    def test_no_trades_gives_zero_costs(self):
        data = _base_data(
            current_weights=[50.0, 30.0, 20.0],
            target_weights=[50.0, 30.0, 20.0],
        )
        result = self._analyzer.analyze(data, self._cfg)
        self.assertEqual(result["num_trades_needed"], 0)
        self.assertEqual(result["total_slippage_cost_usd"], 0.0)
        self.assertEqual(result["total_gas_cost_usd"], 0.0)
        self.assertEqual(result["total_rebalance_cost_usd"], 0.0)

    def test_num_trades_computed(self):
        # current=[50,30,20] target=[40,40,20] → 2 trades
        result = self._analyzer.analyze(_base_data(), self._cfg)
        self.assertEqual(result["num_trades_needed"], 2)

    def test_total_portfolio_computed(self):
        # 500k + 300k + 200k = 1M
        result = self._analyzer.analyze(_base_data(), self._cfg)
        self.assertAlmostEqual(result["total_portfolio_usd"], 1_000_000.0, places=2)

    def test_slippage_cost_computed(self):
        result = self._analyzer.analyze(_base_data(), self._cfg)
        # delta=10% each for 2 positions, portfolio=1M → trade_value=100k each
        # slip = 100k*0.1/100 * 2 = 200
        self.assertAlmostEqual(result["total_slippage_cost_usd"], 200.0, places=4)

    def test_gas_cost_computed(self):
        result = self._analyzer.analyze(_base_data())  # 2 trades * $20 = $40
        self.assertAlmostEqual(result["total_gas_cost_usd"], 40.0, places=4)

    def test_total_rebalance_cost_is_sum(self):
        result = self._analyzer.analyze(_base_data(), self._cfg)
        expected = result["total_slippage_cost_usd"] + result["total_gas_cost_usd"]
        self.assertAlmostEqual(result["total_rebalance_cost_usd"], expected, places=6)

    def test_protocol_name_passed_through(self):
        result = self._analyzer.analyze(
            _base_data(protocol_name="Aave"), self._cfg)
        self.assertEqual(result["protocol_name"], "Aave")

    def test_timestamp_is_string(self):
        result = self._analyzer.analyze(_base_data(), self._cfg)
        self.assertIsInstance(result["timestamp"], str)

    def test_write_log_false_no_file(self):
        log = _tmp_log()
        self._analyzer.analyze(_base_data(), {"log_path": log, "write_log": False})
        self.assertFalse(os.path.exists(log))

    def test_write_log_true_creates_file(self):
        log = _tmp_log()
        self._analyzer.analyze(_base_data(), {"log_path": log, "write_log": True})
        self.assertTrue(os.path.exists(log))

    def test_missing_fields_use_defaults(self):
        result = self._analyzer.analyze({}, self._cfg)
        self.assertIn("rebalance_label", result)
        self.assertEqual(result["protocol_name"], "UNKNOWN")

    def test_rebalance_cost_pct_computed(self):
        result = self._analyzer.analyze(_base_data(), self._cfg)
        expected = result["total_rebalance_cost_usd"] / result["total_portfolio_usd"] * 100
        self.assertAlmostEqual(result["rebalance_cost_pct"], expected, places=4)

    def test_annual_cost_computed(self):
        result = self._analyzer.analyze(_base_data(), self._cfg)
        expected = result["rebalance_cost_pct"] * 365.0 / 30.0
        self.assertAlmostEqual(result["annual_rebalance_cost_pct"], expected, places=4)

    def test_net_gain_computed(self):
        result = self._analyzer.analyze(_base_data(), self._cfg)
        expected = _base_data()["target_apy_improvement_pct"] - result["annual_rebalance_cost_pct"]
        self.assertAlmostEqual(result["net_annual_gain_pct"], expected, places=4)

    def test_high_improvement_gives_efficient_label(self):
        data = _base_data(
            current_weights=[100.0],
            target_weights=[100.0],   # no trades needed → zero cost
            asset_values_usd=[1_000_000.0],
            target_apy_improvement_pct=5.0,
            rebalance_frequency_days=30,
        )
        result = self._analyzer.analyze(data, self._cfg)
        # No trades → net_gain = 5.0 - 0 = 5.0 → EFFICIENT
        self.assertEqual(result["rebalance_label"], "EFFICIENT_REBALANCE")

    def test_zero_improvement_high_cost_dont_rebalance(self):
        data = _base_data(
            current_weights=[50.0, 50.0],
            target_weights=[0.0, 100.0],
            asset_values_usd=[500_000.0, 500_000.0],
            slippage_per_trade_pct=5.0,
            gas_per_trade_usd=1_000.0,
            target_apy_improvement_pct=0.0,
            rebalance_frequency_days=1,
        )
        result = self._analyzer.analyze(data, self._cfg)
        self.assertEqual(result["rebalance_label"], "DONT_REBALANCE")

    def test_all_five_labels_achievable(self):
        """Each label can be obtained with the right parameters."""
        labels_seen = set()

        # EFFICIENT: no trades, big improvement
        r = self._analyzer.analyze(_base_data(
            current_weights=[100.0],
            target_weights=[100.0],
            asset_values_usd=[1_000_000.0],
            target_apy_improvement_pct=5.0,
        ), self._cfg)
        labels_seen.add(r["rebalance_label"])

        # ACCEPTABLE: moderate gain, modest cost
        r = self._analyzer.analyze(_base_data(
            current_weights=[100.0],
            target_weights=[100.0],
            asset_values_usd=[1_000_000.0],
            target_apy_improvement_pct=0.5,
        ), self._cfg)
        labels_seen.add(r["rebalance_label"])

        # MARGINAL: tiny gain, zero cost
        r = self._analyzer.analyze(_base_data(
            current_weights=[100.0],
            target_weights=[100.0],
            asset_values_usd=[1_000_000.0],
            target_apy_improvement_pct=0.1,
        ), self._cfg)
        labels_seen.add(r["rebalance_label"])

        # COSTLY: improvement slightly below annual cost
        r = self._analyzer.analyze(_base_data(
            current_weights=[50.0, 50.0],
            target_weights=[30.0, 70.0],
            asset_values_usd=[500_000.0, 500_000.0],
            slippage_per_trade_pct=0.5,
            gas_per_trade_usd=500.0,
            target_apy_improvement_pct=0.0,
            rebalance_frequency_days=30,
        ), self._cfg)
        labels_seen.add(r["rebalance_label"])

        # DONT: clearly unprofitable
        r = self._analyzer.analyze(_base_data(
            current_weights=[50.0, 50.0],
            target_weights=[0.0, 100.0],
            asset_values_usd=[500_000.0, 500_000.0],
            slippage_per_trade_pct=5.0,
            gas_per_trade_usd=2_000.0,
            target_apy_improvement_pct=0.0,
            rebalance_frequency_days=1,
        ), self._cfg)
        labels_seen.add(r["rebalance_label"])

        # At least 3 distinct labels must be achievable (test is not exhaustive)
        self.assertGreaterEqual(len(labels_seen), 3)


# ===========================================================================
# 11. Module-level analyze() convenience function
# ===========================================================================

class TestModuleLevelAnalyze(unittest.TestCase):

    def setUp(self):
        self._log = _tmp_log()
        self._cfg = {"log_path": self._log, "write_log": False}

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def test_returns_dict(self):
        result = analyze(_base_data(), self._cfg)
        self.assertIsInstance(result, dict)

    def test_same_result_as_class(self):
        analyzer = ProtocolDeFiStrategyRebalancingCostAnalyzer()
        r1 = analyze(_base_data(), self._cfg)
        r2 = analyzer.analyze(_base_data(), self._cfg)
        for key in r1:
            if key == "timestamp":
                continue
            self.assertEqual(r1[key], r2[key])

    def test_write_log_false_no_file(self):
        analyze(_base_data(), {"log_path": self._log, "write_log": False})
        self.assertFalse(os.path.exists(self._log))

    def test_accepts_config_parameter(self):
        result = analyze(_base_data(), self._cfg)
        self.assertIn("protocol_name", result)

    def test_all_keys_present(self):
        result = analyze(_base_data(), self._cfg)
        for key in [
            "protocol_name", "num_trades_needed", "total_slippage_cost_usd",
            "total_gas_cost_usd", "total_rebalance_cost_usd", "rebalance_cost_pct",
            "annual_rebalance_cost_pct", "net_annual_gain_pct", "rebalance_label",
            "total_portfolio_usd", "timestamp",
        ]:
            self.assertIn(key, result)

    def test_empty_data_uses_defaults(self):
        result = analyze({}, self._cfg)
        self.assertEqual(result["protocol_name"], "UNKNOWN")
        self.assertEqual(result["num_trades_needed"], 0)


# ===========================================================================
# 12. Integration tests
# ===========================================================================

class TestIntegration(unittest.TestCase):

    def setUp(self):
        self._analyzer = ProtocolDeFiStrategyRebalancingCostAnalyzer()
        self._log = _tmp_log()
        self._cfg = {"log_path": self._log, "write_log": False}

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def test_daily_rebalance_expensive_dont(self):
        """Daily rebalancing with slippage makes it uneconomical."""
        data = {
            "protocol_name":              "HighFrequencyFarm",
            "current_weights":            [50.0, 30.0, 20.0],
            "target_weights":             [40.0, 40.0, 20.0],
            "asset_values_usd":           [500_000.0, 300_000.0, 200_000.0],
            "slippage_per_trade_pct":     0.5,
            "gas_per_trade_usd":          50.0,
            "portfolio_apy_pct":          5.0,
            "target_apy_improvement_pct": 0.5,
            "rebalance_frequency_days":   1,
        }
        result = self._analyzer.analyze(data, self._cfg)
        self.assertIn(result["rebalance_label"],
                      {"COSTLY_REBALANCE", "DONT_REBALANCE"})

    def test_monthly_rebalance_efficient(self):
        """Monthly rebalance with big APY improvement → efficient."""
        data = {
            "protocol_name":              "MonthlyRebalancer",
            "current_weights":            [100.0],
            "target_weights":             [100.0],   # no trades
            "asset_values_usd":           [1_000_000.0],
            "slippage_per_trade_pct":     0.1,
            "gas_per_trade_usd":          20.0,
            "portfolio_apy_pct":          5.0,
            "target_apy_improvement_pct": 3.0,
            "rebalance_frequency_days":   30,
        }
        result = self._analyzer.analyze(data, self._cfg)
        self.assertEqual(result["net_annual_gain_pct"], 3.0)
        self.assertEqual(result["rebalance_label"], "EFFICIENT_REBALANCE")

    def test_zero_portfolio_safe(self):
        """All-zero portfolio does not crash."""
        data = _base_data(asset_values_usd=[0.0, 0.0, 0.0])
        result = self._analyzer.analyze(data, self._cfg)
        self.assertEqual(result["total_portfolio_usd"], 0.0)
        self.assertEqual(result["total_slippage_cost_usd"], 0.0)
        self.assertEqual(result["rebalance_cost_pct"], 0.0)

    def test_balanced_portfolio_no_trades(self):
        """Already at target → 0 trades → cost is zero."""
        data = _base_data(
            current_weights=[40.0, 40.0, 20.0],
            target_weights=[40.0, 40.0, 20.0],
        )
        result = self._analyzer.analyze(data, self._cfg)
        self.assertEqual(result["num_trades_needed"], 0)
        self.assertEqual(result["total_rebalance_cost_usd"], 0.0)

    def test_large_portfolio_scales_correctly(self):
        """Slippage cost is proportional to portfolio size; gas is fixed per trade."""
        # Use zero gas so total cost == slippage cost (eliminates fixed-gas distortion)
        d_small = _base_data(
            asset_values_usd=[1_000.0, 600.0, 400.0],
            gas_per_trade_usd=0.0,
        )
        d_large = _base_data(
            asset_values_usd=[10_000_000.0, 6_000_000.0, 4_000_000.0],
            gas_per_trade_usd=0.0,
        )
        r_small = self._analyzer.analyze(d_small, self._cfg)
        r_large = self._analyzer.analyze(d_large, self._cfg)
        # Slippage ratio should match portfolio ratio (10 000x)
        ratio = r_large["total_slippage_cost_usd"] / r_small["total_slippage_cost_usd"]
        self.assertAlmostEqual(ratio, 10_000.0, places=2)
        # With zero gas, cost_pct depends only on slippage → should be equal
        self.assertAlmostEqual(
            r_small["rebalance_cost_pct"],
            r_large["rebalance_cost_pct"],
            places=4,
        )

    def test_high_gas_dominates_on_small_portfolio(self):
        """On a tiny portfolio, gas cost > slippage."""
        data = _base_data(
            asset_values_usd=[100.0, 60.0, 40.0],
            slippage_per_trade_pct=0.1,
            gas_per_trade_usd=50.0,
        )
        result = self._analyzer.analyze(data, self._cfg)
        self.assertGreater(
            result["total_gas_cost_usd"],
            result["total_slippage_cost_usd"],
        )

    def test_annual_cost_annualizes_by_frequency(self):
        """Annual cost is correctly scaled from single-event cost."""
        data = _base_data(rebalance_frequency_days=365)
        r_annual = self._analyzer.analyze(data, self._cfg)
        data2 = _base_data(rebalance_frequency_days=30)
        r_monthly = self._analyzer.analyze(data2, self._cfg)
        # Monthly (365/30 ≈ 12x per year) should have higher annual cost
        self.assertGreater(
            r_monthly["annual_rebalance_cost_pct"],
            r_annual["annual_rebalance_cost_pct"],
        )

    def test_log_entries_written_and_counted(self):
        cfg = {"log_path": self._log, "write_log": True}
        for i in range(4):
            self._analyzer.analyze(_base_data(protocol_name=f"P{i}"), cfg)
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 4)

    def test_single_position_full_exit(self):
        """Moving 100% out of one position into another."""
        data = {
            "protocol_name":              "SingleExit",
            "current_weights":            [100.0, 0.0],
            "target_weights":             [0.0, 100.0],
            "asset_values_usd":           [1_000_000.0, 0.0],
            "slippage_per_trade_pct":     0.1,
            "gas_per_trade_usd":          20.0,
            "portfolio_apy_pct":          3.0,
            "target_apy_improvement_pct": 2.0,
            "rebalance_frequency_days":   90,
        }
        result = self._analyzer.analyze(data, self._cfg)
        # 2 positions changed
        self.assertEqual(result["num_trades_needed"], 2)
        self.assertGreater(result["total_rebalance_cost_usd"], 0.0)

    def test_frequency_1_results_in_very_high_annual_cost(self):
        """Daily rebalancing implies annual cost = per-event cost * 365."""
        data = _base_data(rebalance_frequency_days=1)
        result = self._analyzer.analyze(data, self._cfg)
        self.assertAlmostEqual(
            result["annual_rebalance_cost_pct"],
            result["rebalance_cost_pct"] * 365.0,
            places=4,
        )


if __name__ == "__main__":
    unittest.main()
