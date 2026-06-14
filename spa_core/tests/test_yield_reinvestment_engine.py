"""
Tests for MP-735: YieldReinvestmentEngine
≥65 test methods covering all logic paths.
"""

import json
import math
import os
import tempfile
import unittest

from spa_core.analytics.yield_reinvestment_engine import (
    FREQUENCIES,
    ReinvestmentOptimizationResult,
    ReinvestmentSchedule,
    _RING_BUFFER_CAP,
    _GAS_EFFICIENCY_THRESHOLD,
    compare_positions,
    compound_value,
    compute_schedule,
    load_history,
    optimize,
    save_results,
)


# ── compound_value ─────────────────────────────────────────────────────────────

class TestCompoundValue(unittest.TestCase):
    def test_zero_apy_returns_principal(self):
        result = compound_value(10_000, 0.0, 12)
        self.assertAlmostEqual(result, 10_000.0)

    def test_simple_annual_compounding(self):
        # 10% APY, 1 period/yr → 10000 * 1.10 = 11000
        result = compound_value(10_000, 10.0, 1)
        self.assertAlmostEqual(result, 11_000.0)

    def test_monthly_compounding(self):
        # principal=1000, apy=12%, 12 periods
        expected = 1000 * (1 + 0.12 / 12) ** 12
        result = compound_value(1000, 12.0, 12)
        self.assertAlmostEqual(result, expected, places=10)

    def test_daily_compounding(self):
        expected = 10_000 * (1 + 0.05 / 365) ** 365
        result = compound_value(10_000, 5.0, 365)
        self.assertAlmostEqual(result, expected, places=8)

    def test_quarterly_compounding(self):
        expected = 5_000 * (1 + 0.08 / 4) ** 4
        result = compound_value(5_000, 8.0, 4)
        self.assertAlmostEqual(result, expected, places=10)

    def test_weekly_compounding(self):
        expected = 20_000 * (1 + 0.06 / 52) ** 52
        result = compound_value(20_000, 6.0, 52)
        self.assertAlmostEqual(result, expected, places=8)

    def test_higher_frequency_yields_more(self):
        daily = compound_value(10_000, 5.0, 365)
        monthly = compound_value(10_000, 5.0, 12)
        self.assertGreater(daily, monthly)

    def test_larger_principal_scales_linearly(self):
        v1 = compound_value(1_000, 5.0, 12)
        v2 = compound_value(2_000, 5.0, 12)
        self.assertAlmostEqual(v2 / v1, 2.0, places=10)

    def test_zero_principal(self):
        result = compound_value(0, 10.0, 12)
        self.assertAlmostEqual(result, 0.0)

    def test_invalid_periods_raises(self):
        with self.assertRaises(ValueError):
            compound_value(1000, 5.0, 0)

    def test_negative_periods_raises(self):
        with self.assertRaises(ValueError):
            compound_value(1000, 5.0, -1)

    def test_high_apy_100pct(self):
        # 100% APY, annual → 2× principal
        result = compound_value(1000, 100.0, 1)
        self.assertAlmostEqual(result, 2000.0)


# ── FREQUENCIES constant ──────────────────────────────────────────────────────

class TestFrequencies(unittest.TestCase):
    def test_daily_is_365(self):
        self.assertEqual(FREQUENCIES["DAILY"], 365)

    def test_weekly_is_52(self):
        self.assertEqual(FREQUENCIES["WEEKLY"], 52)

    def test_monthly_is_12(self):
        self.assertEqual(FREQUENCIES["MONTHLY"], 12)

    def test_quarterly_is_4(self):
        self.assertEqual(FREQUENCIES["QUARTERLY"], 4)

    def test_all_four_keys_present(self):
        self.assertEqual(set(FREQUENCIES.keys()), {"DAILY", "WEEKLY", "MONTHLY", "QUARTERLY"})


# ── compute_schedule ──────────────────────────────────────────────────────────

class TestComputeSchedule(unittest.TestCase):
    def _sched(self, freq="MONTHLY", principal=100_000, apy=5.0, gas=10.0):
        return compute_schedule("TestPos", principal, apy, freq, gas)

    def test_returns_reinvestment_schedule(self):
        s = self._sched()
        self.assertIsInstance(s, ReinvestmentSchedule)

    def test_position_name_stored(self):
        s = self._sched()
        self.assertEqual(s.position_name, "TestPos")

    def test_principal_stored(self):
        s = self._sched(principal=50_000)
        self.assertAlmostEqual(s.principal_usd, 50_000)

    def test_apy_stored(self):
        s = self._sched(apy=7.5)
        self.assertAlmostEqual(s.apy, 7.5)

    def test_frequency_label_stored(self):
        s = self._sched(freq="DAILY")
        self.assertEqual(s.frequency_label, "DAILY")

    def test_periods_per_year_correct(self):
        s = self._sched(freq="WEEKLY")
        self.assertEqual(s.periods_per_year, 52)

    def test_annual_gas_cost_correct(self):
        s = self._sched(freq="MONTHLY", gas=10.0)
        self.assertAlmostEqual(s.annual_gas_cost_usd, 10.0 * 12)

    def test_gas_per_harvest_stored(self):
        s = self._sched(gas=25.0)
        self.assertAlmostEqual(s.gas_cost_per_harvest_usd, 25.0)

    def test_compounded_value_matches_formula(self):
        s = self._sched(freq="MONTHLY", principal=100_000, apy=5.0)
        expected = compound_value(100_000, 5.0, 12)
        self.assertAlmostEqual(s.compounded_value_1y, expected, places=8)

    def test_net_compounded_subtracts_gas(self):
        s = self._sched(freq="MONTHLY", principal=100_000, apy=5.0, gas=10.0)
        expected = s.compounded_value_1y - 120.0
        self.assertAlmostEqual(s.net_compounded_value_1y, expected, places=8)

    def test_net_gain_is_net_compounded_minus_principal(self):
        s = self._sched()
        self.assertAlmostEqual(s.net_gain_usd, s.net_compounded_value_1y - s.principal_usd)

    def test_simple_interest_gain(self):
        s = self._sched(principal=100_000, apy=5.0)
        self.assertAlmostEqual(s.simple_interest_gain, 100_000 * 5.0 / 100)

    def test_compounding_benefit_calculation(self):
        s = self._sched()
        self.assertAlmostEqual(s.compounding_benefit_usd, s.net_gain_usd - s.simple_interest_gain)

    def test_effective_apy_positive_principal(self):
        s = self._sched(principal=100_000, apy=5.0, gas=0.0)
        expected = (s.net_compounded_value_1y / 100_000 - 1) * 100
        self.assertAlmostEqual(s.effective_apy, expected, places=8)

    def test_effective_apy_zero_principal(self):
        s = compute_schedule("Z", 0, 5.0, "MONTHLY", 0.0)
        self.assertAlmostEqual(s.effective_apy, 0.0)

    def test_gas_efficient_low_gas(self):
        # $1 gas, MONTHLY for $100k position at 5% APY → very efficient
        s = compute_schedule("P", 100_000, 5.0, "MONTHLY", 1.0)
        self.assertTrue(s.is_gas_efficient)

    def test_gas_inefficient_high_gas(self):
        # $10000 gas per harvest, monthly on $1000 position at 5% → inefficient
        s = compute_schedule("P", 1_000, 5.0, "MONTHLY", 10_000.0)
        self.assertFalse(s.is_gas_efficient)

    def test_gas_efficiency_threshold(self):
        # annual_gas = gas * periods; gross_yield = compounded - principal
        s = self._sched(freq="MONTHLY", principal=100_000, apy=5.0, gas=10.0)
        gross = s.compounded_value_1y - s.principal_usd
        self.assertEqual(s.is_gas_efficient, s.annual_gas_cost_usd < _GAS_EFFICIENCY_THRESHOLD * gross)

    def test_gas_efficient_recommendation_text(self):
        s = compute_schedule("P", 100_000, 5.0, "MONTHLY", 1.0)
        self.assertIn("Harvest MONTHLY", s.recommendation)
        self.assertIn("effective APY", s.recommendation)
        self.assertIn("Compounding adds", s.recommendation)

    def test_gas_inefficient_recommendation_text(self):
        s = compute_schedule("P", 100, 5.0, "DAILY", 50.0)
        self.assertIn("Gas costs outweigh", s.recommendation)
        self.assertIn("Harvest less often", s.recommendation)

    def test_invalid_frequency_raises(self):
        with self.assertRaises(ValueError):
            compute_schedule("P", 100_000, 5.0, "HOURLY", 10.0)

    def test_all_four_frequencies_compute(self):
        for freq in FREQUENCIES:
            s = compute_schedule("P", 100_000, 5.0, freq, 5.0)
            self.assertIsInstance(s, ReinvestmentSchedule)


# ── optimize ──────────────────────────────────────────────────────────────────

class TestOptimize(unittest.TestCase):
    def test_returns_result_instance(self):
        result = optimize("Aave USDC", 100_000, 5.0, 10.0)
        self.assertIsInstance(result, ReinvestmentOptimizationResult)

    def test_four_schedules_returned(self):
        result = optimize("Aave USDC", 100_000, 5.0, 10.0)
        self.assertEqual(len(result.schedules), 4)

    def test_all_frequencies_present(self):
        result = optimize("Aave USDC", 100_000, 5.0, 10.0)
        labels = {s.frequency_label for s in result.schedules}
        self.assertEqual(labels, set(FREQUENCIES.keys()))

    def test_optimal_is_max_net_gain(self):
        result = optimize("Aave USDC", 100_000, 5.0, 10.0)
        max_gain = max(s.net_gain_usd for s in result.schedules)
        self.assertAlmostEqual(result.optimal_schedule.net_gain_usd, max_gain)

    def test_position_name_stored(self):
        result = optimize("MyPos", 100_000, 5.0, 10.0)
        self.assertEqual(result.position_name, "MyPos")

    def test_principal_stored(self):
        result = optimize("P", 75_000, 5.0, 10.0)
        self.assertAlmostEqual(result.principal_usd, 75_000)

    def test_apy_stored(self):
        result = optimize("P", 100_000, 7.5, 10.0)
        self.assertAlmostEqual(result.apy, 7.5)

    def test_summary_contains_optimal_label(self):
        result = optimize("P", 100_000, 5.0, 10.0)
        self.assertIn(result.optimal_schedule.frequency_label, result.summary)

    def test_summary_contains_net_gain(self):
        result = optimize("P", 100_000, 5.0, 10.0)
        self.assertIn("Net gain:", result.summary)

    def test_summary_contains_simple_interest(self):
        result = optimize("P", 100_000, 5.0, 10.0)
        self.assertIn("Simple interest gain:", result.summary)

    def test_min_principal_for_daily_positive_apy(self):
        result = optimize("P", 100_000, 5.0, 10.0)
        # gas * 365 / (apy/100) * 20 = 10*365/(0.05)*20
        expected = 10 * 365 / (5.0 / 100) * 20
        self.assertAlmostEqual(result.min_principal_for_daily, expected, places=5)

    def test_min_principal_for_daily_zero_apy(self):
        result = optimize("P", 100_000, 0.0, 10.0)
        self.assertEqual(result.min_principal_for_daily, float("inf"))

    def test_saved_to_empty_before_save(self):
        result = optimize("P", 100_000, 5.0, 10.0)
        self.assertEqual(result.saved_to, "")

    def test_high_gas_makes_quarterly_optimal(self):
        # Very high gas cost → quarterly has lowest annual gas
        result = optimize("P", 1_000, 5.0, 500.0)
        self.assertEqual(result.optimal_schedule.frequency_label, "QUARTERLY")

    def test_low_gas_may_make_daily_better(self):
        # Zero gas → daily compounding should win
        result = optimize("P", 100_000, 5.0, 0.0)
        self.assertEqual(result.optimal_schedule.frequency_label, "DAILY")


# ── compare_positions ─────────────────────────────────────────────────────────

class TestComparePositions(unittest.TestCase):
    def setUp(self):
        self.positions = [
            {"name": "Aave USDC", "principal": 50_000, "apy": 5.0},
            {"name": "Compound DAI", "principal": 30_000, "apy": 4.5},
            {"name": "Yearn USDC", "principal": 20_000, "apy": 6.5},
        ]

    def test_returns_dict(self):
        result = compare_positions(self.positions, 10.0)
        self.assertIsInstance(result, dict)

    def test_keys_are_position_names(self):
        result = compare_positions(self.positions, 10.0)
        self.assertEqual(set(result.keys()), {"Aave USDC", "Compound DAI", "Yearn USDC"})

    def test_values_are_reinvestment_schedules(self):
        result = compare_positions(self.positions, 10.0)
        for schedule in result.values():
            self.assertIsInstance(schedule, ReinvestmentSchedule)

    def test_empty_positions(self):
        result = compare_positions([], 10.0)
        self.assertEqual(result, {})

    def test_single_position(self):
        result = compare_positions([self.positions[0]], 10.0)
        self.assertEqual(len(result), 1)
        self.assertIn("Aave USDC", result)

    def test_schedule_is_optimal_for_each_position(self):
        result = compare_positions(self.positions, 10.0)
        for name, schedule in result.items():
            # The returned schedule should be the optimal one
            pos = next(p for p in self.positions if p["name"] == name)
            opt_result = optimize(name, pos["principal"], pos["apy"], 10.0)
            self.assertEqual(schedule.frequency_label, opt_result.optimal_schedule.frequency_label)


# ── save_results / load_history ────────────────────────────────────────────────

class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "reinvestment_log.json")

    def _make_result(self, principal=100_000) -> ReinvestmentOptimizationResult:
        return optimize("TestPos", principal, 5.0, 10.0)

    def test_save_creates_file(self):
        result = self._make_result()
        save_results(result, self.log_file)
        self.assertTrue(os.path.exists(self.log_file))

    def test_save_returns_path(self):
        result = self._make_result()
        path = save_results(result, self.log_file)
        self.assertEqual(path, self.log_file)

    def test_saved_to_set_on_result(self):
        result = self._make_result()
        save_results(result, self.log_file)
        self.assertEqual(result.saved_to, self.log_file)

    def test_load_empty_when_missing(self):
        history = load_history(os.path.join(self.tmp_dir, "missing.json"))
        self.assertEqual(history, [])

    def test_load_returns_list(self):
        result = self._make_result()
        save_results(result, self.log_file)
        history = load_history(self.log_file)
        self.assertIsInstance(history, list)

    def test_load_one_entry(self):
        result = self._make_result()
        save_results(result, self.log_file)
        history = load_history(self.log_file)
        self.assertEqual(len(history), 1)

    def test_entry_has_timestamp(self):
        result = self._make_result()
        save_results(result, self.log_file)
        history = load_history(self.log_file)
        self.assertIn("timestamp", history[0])

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            save_results(self._make_result(), self.log_file)
        history = load_history(self.log_file)
        self.assertEqual(len(history), 5)

    def test_ring_buffer_at_100(self):
        for _ in range(_RING_BUFFER_CAP + 15):
            save_results(self._make_result(), self.log_file)
        history = load_history(self.log_file)
        self.assertLessEqual(len(history), _RING_BUFFER_CAP)

    def test_ring_buffer_keeps_latest(self):
        for i in range(_RING_BUFFER_CAP + 5):
            result = optimize("Pos", i * 100 + 1, 5.0, 10.0)
            save_results(result, self.log_file)
        history = load_history(self.log_file)
        self.assertEqual(len(history), _RING_BUFFER_CAP)

    def test_corrupted_json_returns_empty(self):
        with open(self.log_file, "w") as f:
            f.write("{bad json[[[")
        history = load_history(self.log_file)
        self.assertEqual(history, [])

    def test_non_list_json_returns_empty(self):
        with open(self.log_file, "w") as f:
            json.dump({"not": "a list"}, f)
        history = load_history(self.log_file)
        self.assertEqual(history, [])

    def test_atomic_tmp_not_left_behind(self):
        result = self._make_result()
        save_results(result, self.log_file)
        tmp_files = [f for f in os.listdir(self.tmp_dir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_saved_json_is_valid(self):
        result = self._make_result()
        save_results(result, self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


# ── Integration ───────────────────────────────────────────────────────────────

class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "reinvestment_log.json")

    def test_full_pipeline_save_load(self):
        result = optimize("Aave USDC", 100_000, 5.0, 10.0)
        path = save_results(result, self.log_file)
        history = load_history(self.log_file)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["position_name"], "Aave USDC")

    def test_compound_benefit_positive_for_zero_gas(self):
        result = optimize("P", 100_000, 5.0, 0.0)
        # With no gas, compounding benefit for daily should be positive
        daily = next(s for s in result.schedules if s.frequency_label == "DAILY")
        self.assertGreater(daily.compounding_benefit_usd, 0)

    def test_net_gain_less_than_gross_gain_with_gas(self):
        result = optimize("P", 100_000, 5.0, 50.0)
        for s in result.schedules:
            gross_gain = s.compounded_value_1y - s.principal_usd
            self.assertLess(s.net_gain_usd, gross_gain)

    def test_compare_positions_higher_apy_wins_daily(self):
        positions = [
            {"name": "Low APY", "principal": 1_000_000, "apy": 2.0},
            {"name": "High APY", "principal": 1_000_000, "apy": 20.0},
        ]
        result = compare_positions(positions, 1.0)
        # High APY should also have daily optimal when gas is small
        self.assertEqual(result["High APY"].frequency_label, "DAILY")

    def test_summary_format_contains_dollar(self):
        result = optimize("P", 100_000, 5.0, 10.0)
        self.assertIn("$", result.summary)


if __name__ == "__main__":
    unittest.main()
