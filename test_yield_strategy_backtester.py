"""
Tests for MP-886 YieldStrategyBacktester
=========================================
Run: python3 -m unittest spa_core.tests.test_yield_strategy_backtester -v
"""
import json
import math
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.analytics.yield_strategy_backtester import (
    analyze,
    save_result,
    _mean,
    _population_std_dev,
    _compound_final_capital,
    _performance_label,
    _consistency_label,
    _build_recommendation,
    _atomic_write_json,
    _load_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strat(
    name="TestStrat",
    daily_apy_history=None,
    initial_capital_usd=100_000.0,
    rebalance_cost_bps=5.0,
):
    if daily_apy_history is None:
        daily_apy_history = [5.0] * 30
    return {
        "name": name,
        "daily_apy_history": daily_apy_history,
        "initial_capital_usd": initial_capital_usd,
        "rebalance_cost_bps": rebalance_cost_bps,
    }


# ===========================================================================
# 1. _mean tests
# ===========================================================================
class TestMean(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_single(self):
        self.assertEqual(_mean([5.0]), 5.0)

    def test_two_equal(self):
        self.assertEqual(_mean([4.0, 6.0]), 5.0)

    def test_multiple(self):
        self.assertAlmostEqual(_mean([1.0, 2.0, 3.0, 4.0, 5.0]), 3.0, places=10)

    def test_returns_float(self):
        self.assertIsInstance(_mean([1.0, 2.0]), float)

    def test_negative_values(self):
        self.assertAlmostEqual(_mean([-1.0, 1.0]), 0.0, places=10)


# ===========================================================================
# 2. _population_std_dev tests
# ===========================================================================
class TestPopulationStdDev(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(_population_std_dev([]), 0.0)

    def test_single_element(self):
        self.assertEqual(_population_std_dev([5.0]), 0.0)

    def test_identical_values(self):
        self.assertAlmostEqual(_population_std_dev([3.0, 3.0, 3.0]), 0.0, places=10)

    def test_two_values(self):
        # mean=5, deviations: [-1, 1], variance=1, std=1
        self.assertAlmostEqual(_population_std_dev([4.0, 6.0]), 1.0, places=10)

    def test_known_std(self):
        # [2, 4, 4, 4, 5, 5, 7, 9] population std = 2
        data = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        self.assertAlmostEqual(_population_std_dev(data), 2.0, places=10)

    def test_returns_float(self):
        self.assertIsInstance(_population_std_dev([1.0, 2.0, 3.0]), float)

    def test_non_negative(self):
        self.assertGreaterEqual(_population_std_dev([1.0, 5.0, 9.0]), 0.0)


# ===========================================================================
# 3. _compound_final_capital tests
# ===========================================================================
class TestCompoundFinalCapital(unittest.TestCase):

    def test_empty_history(self):
        self.assertEqual(_compound_final_capital(100_000.0, []), 100_000.0)

    def test_zero_apy(self):
        result = _compound_final_capital(100_000.0, [0.0] * 365)
        self.assertAlmostEqual(result, 100_000.0, places=2)

    def test_single_day_5_pct(self):
        expected = 100_000.0 * (1 + 5.0 / 100.0 / 365.0)
        result = _compound_final_capital(100_000.0, [5.0])
        self.assertAlmostEqual(result, expected, places=6)

    def test_one_year_10_pct(self):
        result = _compound_final_capital(100_000.0, [10.0] * 365)
        expected = 100_000.0 * (1 + 0.10 / 365.0) ** 365
        self.assertAlmostEqual(result, expected, places=2)

    def test_capital_increases_positive_apy(self):
        result = _compound_final_capital(100_000.0, [5.0] * 30)
        self.assertGreater(result, 100_000.0)

    def test_zero_initial_capital(self):
        result = _compound_final_capital(0.0, [5.0] * 30)
        self.assertEqual(result, 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_compound_final_capital(1000.0, [5.0]), float)


# ===========================================================================
# 4. _performance_label tests
# ===========================================================================
class TestPerformanceLabel(unittest.TestCase):

    def test_exceptional(self):
        self.assertEqual(_performance_label(51.0), "EXCEPTIONAL")

    def test_not_exceptional_at_50(self):
        # 50.0 is NOT exceptional (need >50)
        self.assertEqual(_performance_label(50.0), "STRONG")

    def test_strong(self):
        self.assertEqual(_performance_label(21.0), "STRONG")

    def test_strong_at_50(self):
        self.assertEqual(_performance_label(50.0), "STRONG")

    def test_good(self):
        self.assertEqual(_performance_label(11.0), "GOOD")

    def test_good_at_20(self):
        self.assertEqual(_performance_label(20.0), "GOOD")

    def test_moderate(self):
        self.assertEqual(_performance_label(0.5), "MODERATE")

    def test_poor_zero(self):
        self.assertEqual(_performance_label(0.0), "POOR")

    def test_poor_negative(self):
        self.assertEqual(_performance_label(-5.0), "POOR")

    def test_returns_string(self):
        self.assertIsInstance(_performance_label(5.0), str)


# ===========================================================================
# 5. _consistency_label tests
# ===========================================================================
class TestConsistencyLabel(unittest.TestCase):

    def test_very_consistent_zero(self):
        self.assertEqual(_consistency_label(0.0), "VERY_CONSISTENT")

    def test_very_consistent_below_2(self):
        self.assertEqual(_consistency_label(1.99), "VERY_CONSISTENT")

    def test_consistent_at_2(self):
        self.assertEqual(_consistency_label(2.0), "CONSISTENT")

    def test_consistent_below_5(self):
        self.assertEqual(_consistency_label(4.99), "CONSISTENT")

    def test_variable_at_5(self):
        self.assertEqual(_consistency_label(5.0), "VARIABLE")

    def test_variable_below_10(self):
        self.assertEqual(_consistency_label(9.99), "VARIABLE")

    def test_highly_variable_at_10(self):
        self.assertEqual(_consistency_label(10.0), "HIGHLY_VARIABLE")

    def test_highly_variable_above_10(self):
        self.assertEqual(_consistency_label(20.0), "HIGHLY_VARIABLE")

    def test_returns_string(self):
        self.assertIsInstance(_consistency_label(3.0), str)


# ===========================================================================
# 6. _build_recommendation tests
# ===========================================================================
class TestBuildRecommendation(unittest.TestCase):

    def test_exceptional_high_sharpe_outstanding(self):
        rec = _build_recommendation("EXCEPTIONAL", "VERY_CONSISTENT", 75.0, 3.0, 180, 8.5, 25)
        self.assertIn("Outstanding", rec)
        self.assertIn("75.0", rec)
        self.assertIn("3.00", rec)

    def test_exceptional_low_sharpe_strong_performer(self):
        rec = _build_recommendation("EXCEPTIONAL", "VERY_CONSISTENT", 75.0, 1.5, 180, 8.5, 25)
        self.assertIn("Strong performer", rec)
        self.assertIn("75.0", rec)
        self.assertIn("180", rec)

    def test_strong_recommendation(self):
        rec = _build_recommendation("STRONG", "CONSISTENT", 25.0, 1.0, 365, 7.0, 52)
        self.assertIn("Strong performer", rec)
        self.assertIn("25.0", rec)
        self.assertIn("365", rec)

    def test_good_recommendation(self):
        rec = _build_recommendation("GOOD", "CONSISTENT", 12.0, 0.5, 180, 5.0, 25)
        self.assertIn("Solid yield", rec)
        self.assertIn("5.0", rec)
        self.assertIn("25", rec)

    def test_moderate_recommendation(self):
        rec = _build_recommendation("MODERATE", "VARIABLE", 5.0, 0.1, 90, 4.5, 12)
        self.assertIn("Positive but modest", rec)

    def test_poor_recommendation(self):
        rec = _build_recommendation("POOR", "HIGHLY_VARIABLE", -3.0, -0.5, 30, 2.0, 4)
        self.assertIn("underperformed", rec)
        self.assertIn("-3.0", rec)

    def test_returns_string(self):
        self.assertIsInstance(
            _build_recommendation("GOOD", "CONSISTENT", 15.0, 1.0, 100, 5.0, 10), str
        )


# ===========================================================================
# 7. analyze() core integration tests
# ===========================================================================
class TestAnalyze(unittest.TestCase):

    def test_empty_input(self):
        result = analyze([])
        self.assertEqual(result["strategies"], [])
        self.assertIsNone(result["best_strategy"])
        self.assertIsNone(result["best_sharpe"])
        self.assertIn("timestamp", result)

    def test_single_strategy_keys(self):
        strat = _make_strat()
        result = analyze([strat])
        s = result["strategies"][0]
        for key in [
            "name", "days_tested", "average_apy_pct", "min_apy_pct", "max_apy_pct",
            "apy_std_dev", "final_capital_usd", "total_return_pct", "rebalance_count",
            "total_rebalance_cost_usd", "net_return_pct", "sharpe_ratio",
            "performance_label", "consistency_label", "recommendation",
        ]:
            self.assertIn(key, s)

    def test_days_tested_correct(self):
        strat = _make_strat(daily_apy_history=[5.0] * 45)
        result = analyze([strat])
        self.assertEqual(result["strategies"][0]["days_tested"], 45)

    def test_average_apy_correct(self):
        strat = _make_strat(daily_apy_history=[4.0, 6.0])
        result = analyze([strat])
        self.assertAlmostEqual(result["strategies"][0]["average_apy_pct"], 5.0, places=10)

    def test_min_apy_correct(self):
        strat = _make_strat(daily_apy_history=[2.0, 5.0, 8.0])
        result = analyze([strat])
        self.assertAlmostEqual(result["strategies"][0]["min_apy_pct"], 2.0, places=10)

    def test_max_apy_correct(self):
        strat = _make_strat(daily_apy_history=[2.0, 5.0, 8.0])
        result = analyze([strat])
        self.assertAlmostEqual(result["strategies"][0]["max_apy_pct"], 8.0, places=10)

    def test_empty_history_zero_stats(self):
        strat = _make_strat(daily_apy_history=[])
        result = analyze([strat])
        s = result["strategies"][0]
        self.assertEqual(s["days_tested"], 0)
        self.assertEqual(s["average_apy_pct"], 0.0)
        self.assertEqual(s["min_apy_pct"], 0.0)
        self.assertEqual(s["max_apy_pct"], 0.0)
        self.assertEqual(s["apy_std_dev"], 0.0)

    def test_empty_history_final_capital_equals_initial(self):
        strat = _make_strat(daily_apy_history=[], initial_capital_usd=50_000.0)
        result = analyze([strat])
        self.assertAlmostEqual(
            result["strategies"][0]["final_capital_usd"], 50_000.0, places=6
        )

    def test_empty_history_total_return_zero(self):
        strat = _make_strat(daily_apy_history=[])
        result = analyze([strat])
        self.assertAlmostEqual(result["strategies"][0]["total_return_pct"], 0.0, places=10)

    def test_empty_history_rebalance_count_zero(self):
        strat = _make_strat(daily_apy_history=[])
        result = analyze([strat])
        self.assertEqual(result["strategies"][0]["rebalance_count"], 0)

    def test_rebalance_count_floor_division(self):
        # 30 days, freq=7 → floor(30/7)=4
        strat = _make_strat(daily_apy_history=[5.0] * 30)
        result = analyze([strat], config={"rebalance_frequency_days": 7})
        self.assertEqual(result["strategies"][0]["rebalance_count"], 4)

    def test_rebalance_count_exact(self):
        # 28 days, freq=7 → floor(28/7)=4
        strat = _make_strat(daily_apy_history=[5.0] * 28)
        result = analyze([strat], config={"rebalance_frequency_days": 7})
        self.assertEqual(result["strategies"][0]["rebalance_count"], 4)

    def test_rebalance_cost_calculation(self):
        # count=4, cost_bps=10, capital=100k → 4*(10/10000)*100000=400
        strat = _make_strat(
            daily_apy_history=[5.0] * 30,
            initial_capital_usd=100_000.0,
            rebalance_cost_bps=10.0,
        )
        result = analyze([strat], config={"rebalance_frequency_days": 7})
        self.assertAlmostEqual(
            result["strategies"][0]["total_rebalance_cost_usd"], 400.0, places=6
        )

    def test_net_return_less_than_total_with_costs(self):
        strat = _make_strat(
            daily_apy_history=[5.0] * 30,
            rebalance_cost_bps=10.0,
        )
        result = analyze([strat])
        s = result["strategies"][0]
        self.assertLessEqual(s["net_return_pct"], s["total_return_pct"])

    def test_sharpe_zero_when_std_zero(self):
        strat = _make_strat(daily_apy_history=[5.0] * 30)
        result = analyze([strat])
        self.assertEqual(result["strategies"][0]["sharpe_ratio"], 0.0)

    def test_sharpe_positive_above_risk_free(self):
        strat = _make_strat(daily_apy_history=[10.0, 12.0, 11.0, 9.0] * 20)
        result = analyze([strat])
        self.assertGreater(result["strategies"][0]["sharpe_ratio"], 0.0)

    def test_sharpe_negative_below_risk_free(self):
        strat = _make_strat(daily_apy_history=[1.0, 2.0, 1.5, 0.5] * 20)
        result = analyze([strat])
        self.assertLess(result["strategies"][0]["sharpe_ratio"], 0.0)

    def test_custom_risk_free_rate(self):
        strat = _make_strat(daily_apy_history=[4.0, 6.0] * 10)
        result = analyze([strat], config={"risk_free_rate_pct": 0.0})
        s = result["strategies"][0]
        expected_sharpe = s["average_apy_pct"] / s["apy_std_dev"]
        self.assertAlmostEqual(s["sharpe_ratio"], expected_sharpe, places=10)

    def test_best_strategy_single(self):
        strat = _make_strat(name="Alpha")
        result = analyze([strat])
        self.assertEqual(result["best_strategy"], "Alpha")

    def test_best_strategy_multiple(self):
        low = _make_strat(name="Low", daily_apy_history=[3.0] * 30)
        high = _make_strat(name="High", daily_apy_history=[15.0] * 30)
        result = analyze([low, high])
        self.assertEqual(result["best_strategy"], "High")

    def test_best_sharpe_single(self):
        strat = _make_strat(name="Alpha")
        result = analyze([strat])
        self.assertEqual(result["best_sharpe"], "Alpha")

    def test_best_sharpe_multiple(self):
        # s1 has lower std → higher Sharpe
        s1 = _make_strat(name="S1", daily_apy_history=[5.0, 7.0] * 20)
        s2 = _make_strat(name="S2", daily_apy_history=[5.0, 15.0] * 20)
        result = analyze([s1, s2])
        self.assertEqual(result["best_sharpe"], "S1")

    def test_timestamp_is_recent(self):
        before = time.time()
        result = analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after + 1)

    def test_multiple_strategies_all_returned(self):
        strats = [_make_strat(name=f"S{i}") for i in range(5)]
        result = analyze(strats)
        self.assertEqual(len(result["strategies"]), 5)

    def test_strategy_name_preserved(self):
        strat = _make_strat(name="MyStrategy")
        result = analyze([strat])
        self.assertEqual(result["strategies"][0]["name"], "MyStrategy")

    def test_none_config_uses_defaults(self):
        strat = _make_strat()
        result = analyze([strat], config=None)
        self.assertIn("strategies", result)

    def test_initial_capital_zero_returns_zero(self):
        strat = _make_strat(daily_apy_history=[5.0] * 30, initial_capital_usd=0.0)
        result = analyze([strat])
        s = result["strategies"][0]
        self.assertEqual(s["total_return_pct"], 0.0)
        self.assertEqual(s["net_return_pct"], 0.0)

    def test_recommendation_is_string(self):
        result = analyze([_make_strat()])
        self.assertIsInstance(result["strategies"][0]["recommendation"], str)

    def test_recommendation_not_empty(self):
        result = analyze([_make_strat()])
        self.assertTrue(len(result["strategies"][0]["recommendation"]) > 0)

    def test_performance_label_present(self):
        result = analyze([_make_strat()])
        perf = result["strategies"][0]["performance_label"]
        self.assertIn(perf, ["EXCEPTIONAL", "STRONG", "GOOD", "MODERATE", "POOR"])

    def test_consistency_label_present(self):
        result = analyze([_make_strat()])
        cons = result["strategies"][0]["consistency_label"]
        self.assertIn(
            cons,
            ["VERY_CONSISTENT", "CONSISTENT", "VARIABLE", "HIGHLY_VARIABLE"],
        )

    def test_very_consistent_constant_apy(self):
        strat = _make_strat(daily_apy_history=[5.0] * 30)
        result = analyze([strat])
        self.assertEqual(result["strategies"][0]["consistency_label"], "VERY_CONSISTENT")

    def test_highly_variable_label(self):
        strat = _make_strat(daily_apy_history=[0.0, 20.0, 0.0, 20.0] * 20)
        result = analyze([strat])
        self.assertEqual(result["strategies"][0]["consistency_label"], "HIGHLY_VARIABLE")

    def test_final_capital_greater_initial_positive_apy(self):
        strat = _make_strat(daily_apy_history=[5.0] * 30, initial_capital_usd=100_000.0)
        result = analyze([strat])
        self.assertGreater(result["strategies"][0]["final_capital_usd"], 100_000.0)

    def test_custom_rebalance_frequency(self):
        strat = _make_strat(daily_apy_history=[5.0] * 100)
        result = analyze([strat], config={"rebalance_frequency_days": 10})
        self.assertEqual(result["strategies"][0]["rebalance_count"], 10)

    def test_std_dev_constant_is_zero(self):
        strat = _make_strat(daily_apy_history=[8.0] * 50)
        result = analyze([strat])
        self.assertEqual(result["strategies"][0]["apy_std_dev"], 0.0)

    def test_apy_std_dev_nonzero_variable(self):
        strat = _make_strat(daily_apy_history=[4.0, 6.0] * 10)
        result = analyze([strat])
        self.assertGreater(result["strategies"][0]["apy_std_dev"], 0.0)


# ===========================================================================
# 8. Persistence tests
# ===========================================================================
class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = Path(self.tmp_dir) / "backtest_results_log.json"

    def test_save_creates_file(self):
        result = analyze([_make_strat()])
        save_result(result, self.log_path)
        self.assertTrue(self.log_path.exists())

    def test_save_creates_list(self):
        result = analyze([_make_strat()])
        save_result(result, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_save_multiple_entries(self):
        for i in range(5):
            result = analyze([_make_strat(name=f"S{i}")])
            save_result(result, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_caps_at_100(self):
        for i in range(110):
            result = analyze([_make_strat(name=f"S{i}")])
            save_result(result, self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_load_missing_file_returns_empty(self):
        missing = Path(self.tmp_dir) / "nonexistent.json"
        data = _load_log(missing)
        self.assertEqual(data, [])

    def test_atomic_write_json(self):
        path = Path(self.tmp_dir) / "test_atomic.json"
        payload = {"strategies": [], "timestamp": 12345.0}
        _atomic_write_json(path, payload)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["strategies"], [])
        self.assertAlmostEqual(data["timestamp"], 12345.0, places=5)

    def test_load_corrupt_file_returns_empty(self):
        corrupt = Path(self.tmp_dir) / "corrupt.json"
        corrupt.write_text("{not valid json", encoding="utf-8")
        data = _load_log(corrupt)
        self.assertEqual(data, [])

    def test_load_non_list_returns_empty(self):
        path = Path(self.tmp_dir) / "not_list.json"
        with open(path, "w") as f:
            json.dump({"key": "val"}, f)
        data = _load_log(path)
        self.assertEqual(data, [])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)


# ===========================================================================
# 9. Edge case / boundary tests
# ===========================================================================
class TestEdgeCases(unittest.TestCase):

    def test_empty_strategies_returns_empty_list(self):
        result = analyze([])
        self.assertEqual(result["strategies"], [])

    def test_empty_strategies_best_none(self):
        result = analyze([])
        self.assertIsNone(result["best_strategy"])
        self.assertIsNone(result["best_sharpe"])

    def test_single_day_history(self):
        strat = _make_strat(daily_apy_history=[5.0])
        result = analyze([strat])
        s = result["strategies"][0]
        self.assertEqual(s["days_tested"], 1)
        self.assertEqual(s["apy_std_dev"], 0.0)

    def test_no_rebalance_within_period(self):
        strat = _make_strat(daily_apy_history=[5.0] * 5)
        result = analyze([strat], config={"rebalance_frequency_days": 7})
        self.assertEqual(result["strategies"][0]["rebalance_count"], 0)
        self.assertEqual(result["strategies"][0]["total_rebalance_cost_usd"], 0.0)

    def test_missing_fields_handled(self):
        strat = {"name": "Minimal"}
        result = analyze([strat])
        s = result["strategies"][0]
        self.assertEqual(s["name"], "Minimal")
        self.assertEqual(s["days_tested"], 0)

    def test_poor_label_negative_return(self):
        strat = _make_strat(
            daily_apy_history=[0.0] * 30,
            rebalance_cost_bps=100.0,
        )
        result = analyze([strat])
        self.assertEqual(result["strategies"][0]["performance_label"], "POOR")

    def test_total_rebalance_cost_zero_when_no_rebalance(self):
        strat = _make_strat(daily_apy_history=[5.0] * 5)
        result = analyze([strat], config={"rebalance_frequency_days": 7})
        self.assertEqual(result["strategies"][0]["total_rebalance_cost_usd"], 0.0)

    def test_net_equals_total_when_no_cost(self):
        strat = _make_strat(
            daily_apy_history=[5.0] * 5,
            rebalance_cost_bps=0.0,
        )
        result = analyze([strat], config={"rebalance_frequency_days": 7})
        s = result["strategies"][0]
        self.assertAlmostEqual(s["net_return_pct"], s["total_return_pct"], places=10)

    def test_large_apy_history(self):
        strat = _make_strat(daily_apy_history=[5.0] * 365)
        result = analyze([strat])
        self.assertEqual(result["strategies"][0]["days_tested"], 365)

    def test_best_sharpe_tie_first_occurrence(self):
        # Both have same sharpe (constant APY → std=0 → sharpe=0)
        s1 = _make_strat(name="First", daily_apy_history=[5.0] * 10)
        s2 = _make_strat(name="Second", daily_apy_history=[5.0] * 10)
        result = analyze([s1, s2])
        self.assertEqual(result["best_sharpe"], "First")

    def test_all_output_types_correct(self):
        strat = _make_strat()
        result = analyze([strat])
        s = result["strategies"][0]
        self.assertIsInstance(s["name"], str)
        self.assertIsInstance(s["days_tested"], int)
        self.assertIsInstance(s["average_apy_pct"], float)
        self.assertIsInstance(s["min_apy_pct"], float)
        self.assertIsInstance(s["max_apy_pct"], float)
        self.assertIsInstance(s["apy_std_dev"], float)
        self.assertIsInstance(s["final_capital_usd"], float)
        self.assertIsInstance(s["total_return_pct"], float)
        self.assertIsInstance(s["rebalance_count"], int)
        self.assertIsInstance(s["total_rebalance_cost_usd"], float)
        self.assertIsInstance(s["net_return_pct"], float)
        self.assertIsInstance(s["sharpe_ratio"], float)
        self.assertIsInstance(s["performance_label"], str)
        self.assertIsInstance(s["consistency_label"], str)
        self.assertIsInstance(s["recommendation"], str)

    def test_exceptional_recommendation_outstanding_path(self):
        # Force exceptional performance label + sharpe > 2
        # 200 days at ~100% APY: (1+1/365)^200-1 ≈74%; std=5 → sharpe=(100-4)/5=19.2
        strat = _make_strat(
            name="Epic",
            daily_apy_history=[95.0, 105.0] * 100,  # mean=100, std=5, sharpe=19.2>2
            initial_capital_usd=100_000.0,
            rebalance_cost_bps=0.0,
        )
        result = analyze([strat], config={"risk_free_rate_pct": 4.0, "rebalance_frequency_days": 365})
        s = result["strategies"][0]
        # Net return ~74% → EXCEPTIONAL; sharpe ~19 > 2 → "Outstanding"
        rec = s["recommendation"]
        self.assertIn("Outstanding", rec)


if __name__ == "__main__":
    unittest.main()
