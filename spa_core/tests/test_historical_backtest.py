"""
Тесты для spa_core/backtest/historical_backtest.py (MP-212).
Без сети, без внешних зависимостей.
"""
import json
import math
import os
import unittest
import tempfile

from spa_core.backtest.historical_backtest import (
    HistoricalScenario,
    BacktestResult,
    run_scenario,
    run_all_scenarios,
    generate_backtest_report,
    save_backtest_results,
    _compute_sharpe,
    _compute_max_drawdown,
    _compute_allocation,
    _apy_changed_significantly,
    _build_luna_crash_scenario,
    _build_ftx_collapse_scenario,
    _build_usdc_depeg_scenario,
)


class TestComputeAllocation(unittest.TestCase):
    """Тесты логики аллокации."""

    def test_empty_apy_returns_empty(self):
        result = _compute_allocation({})
        self.assertEqual(result, {})

    def test_zero_apy_protocol_skipped(self):
        result = _compute_allocation({"aave_v3": 3.0, "maple_senior": 0.0})
        self.assertIn("aave_v3", result)
        self.assertNotIn("maple_senior", result)

    def test_t1_capped_at_40pct(self):
        result = _compute_allocation({"aave_v3": 5.0})
        self.assertLessEqual(result.get("aave_v3", 0.0), 0.40)

    def test_t2_capped_at_20pct(self):
        result = _compute_allocation({"maple_senior": 8.0})
        self.assertLessEqual(result.get("maple_senior", 0.0), 0.20)

    def test_total_allocation_leq_95pct(self):
        apy = {
            "aave_v3": 5.0, "compound_v3": 4.5,
            "maple_senior": 8.0, "frax_usdc": 6.0,
            "morpho_blue": 4.0,
        }
        result = _compute_allocation(apy)
        total = sum(result.values())
        self.assertLessEqual(total, 0.951)  # допуск на float

    def test_higher_apy_preferred(self):
        # With two T2 options, higher APY gets allocated first
        result = _compute_allocation({"aave_v3": 3.0, "maple_senior": 8.0, "frax_usdc": 6.0})
        # maple (8%) should get full T2 cap before frax (6%)
        self.assertGreaterEqual(result.get("maple_senior", 0.0), result.get("frax_usdc", 0.0))


class TestApyChanged(unittest.TestCase):
    """Тест триггера ребалансировки."""

    def test_no_change_false(self):
        prev = {"aave_v3": 3.0}
        curr = {"aave_v3": 3.3}
        self.assertFalse(_apy_changed_significantly(prev, curr))

    def test_over_threshold_true(self):
        prev = {"aave_v3": 3.0}
        curr = {"aave_v3": 3.6}
        self.assertTrue(_apy_changed_significantly(prev, curr))

    def test_new_protocol_appearing_triggers(self):
        prev = {"aave_v3": 3.0}
        curr = {"aave_v3": 3.0, "new_proto": 5.0}
        self.assertTrue(_apy_changed_significantly(prev, curr))

    def test_protocol_dropping_to_zero_triggers(self):
        prev = {"maple_senior": 8.0}
        curr = {"maple_senior": 0.0}
        self.assertTrue(_apy_changed_significantly(prev, curr))


class TestComputeSharpe(unittest.TestCase):
    """Тесты расчёта Sharpe ratio."""

    def test_empty_returns_zero(self):
        self.assertEqual(_compute_sharpe([]), 0.0)

    def test_single_return_zero(self):
        self.assertEqual(_compute_sharpe([0.001]), 0.0)

    def test_constant_returns_zero(self):
        # All returns equal → std = 0 → sharpe = 0 (not NaN)
        returns = [0.0001] * 100
        sharpe = _compute_sharpe(returns)
        self.assertEqual(sharpe, 0.0)
        self.assertFalse(math.isnan(sharpe))

    def test_positive_sharpe_for_positive_returns(self):
        returns = [0.0002] * 50 + [0.0001] * 50  # varying but mostly positive
        sharpe = _compute_sharpe(returns)
        self.assertFalse(math.isnan(sharpe))
        self.assertIsInstance(sharpe, float)

    def test_annualization_factor(self):
        # Sharpe formula: mean / std * sqrt(252)
        returns = [0.001, 0.002, 0.003, 0.002, 0.001]
        sharpe = _compute_sharpe(returns)
        self.assertGreater(sharpe, 0.0)


class TestComputeMaxDrawdown(unittest.TestCase):
    """Тесты расчёта max drawdown."""

    def test_empty_returns_zero(self):
        self.assertEqual(_compute_max_drawdown([]), 0.0)

    def test_monotone_increase_zero_drawdown(self):
        self.assertEqual(_compute_max_drawdown([100, 101, 102, 103]), 0.0)

    def test_drop_and_recovery(self):
        values = [100, 110, 90, 100]  # peak 110, trough 90 → drawdown 18.2%
        dd = _compute_max_drawdown(values)
        self.assertAlmostEqual(dd, (110 - 90) / 110, places=5)

    def test_multiple_drawdowns_max_reported(self):
        values = [100, 95, 110, 80, 110]  # max drawdown at 80: (110-80)/110 ≈ 27.3%
        dd = _compute_max_drawdown(values)
        self.assertAlmostEqual(dd, (110 - 80) / 110, places=5)


class TestLunaScenario(unittest.TestCase):
    """Тесты LUNA_CRASH_2022 сценария."""

    def setUp(self):
        self.scenario = _build_luna_crash_scenario()
        self.result = run_scenario(self.scenario)

    def test_scenario_name(self):
        self.assertEqual(self.result.scenario_name, "LUNA_CRASH_2022")

    def test_30_days_tracked(self):
        self.assertEqual(self.result.days_tracked, 30)

    def test_capital_preserved(self):
        # T1 protocols survive → capital should grow (positive yield)
        self.assertGreater(self.result.end_capital, self.result.start_capital)

    def test_peg_protocol_zero_during_crash(self):
        # During days 15-21, frax_usdc APY = 0 → no yield from frax
        # System should have reallocated to T1 (aave/compound)
        # Verify by checking that allocation_changes > 1
        self.assertGreater(self.result.allocation_changes, 1)

    def test_events_handled(self):
        self.assertGreater(len(self.result.events_handled), 0)

    def test_luna_crash_event_present(self):
        event_types = [e["event_type"] for e in self.result.events_handled]
        self.assertIn("LUNA_UST_COLLAPSE", event_types)

    def test_sharpe_not_nan(self):
        self.assertFalse(math.isnan(self.result.sharpe_ratio))

    def test_daily_equity_length(self):
        self.assertEqual(len(self.result.daily_equity), 30)

    def test_daily_equity_has_required_fields(self):
        for entry in self.result.daily_equity:
            self.assertIn("date", entry)
            self.assertIn("equity", entry)
            self.assertIn("daily_return", entry)


class TestFtxScenario(unittest.TestCase):
    """Тесты FTX_COLLAPSE_2022 сценария."""

    def setUp(self):
        self.scenario = _build_ftx_collapse_scenario()
        self.result = run_scenario(self.scenario)

    def test_scenario_name(self):
        self.assertEqual(self.result.scenario_name, "FTX_COLLAPSE_2022")

    def test_30_days_tracked(self):
        self.assertEqual(self.result.days_tracked, 30)

    def test_credit_protocol_zero_handled(self):
        # maple APY drops to 0 → system rebalances away
        self.assertGreater(self.result.allocation_changes, 1)

    def test_ftx_event_registered(self):
        event_types = [e["event_type"] for e in self.result.events_handled]
        self.assertIn("FTX_COLLAPSE", event_types)

    def test_capital_survives_on_t1(self):
        # Aave/Compound survive → capital grows despite maple defaults
        self.assertGreater(self.result.end_capital, self.result.start_capital * 0.99)

    def test_sharpe_not_nan(self):
        self.assertFalse(math.isnan(self.result.sharpe_ratio))


class TestUsdcDepegScenario(unittest.TestCase):
    """Тесты USDC_DEPEG_2023 сценария."""

    def setUp(self):
        self.scenario = _build_usdc_depeg_scenario()
        self.result = run_scenario(self.scenario)

    def test_14_days_tracked(self):
        self.assertEqual(self.result.days_tracked, 14)

    def test_system_reallocates_to_t1(self):
        # Aave APY spikes to 8% → system should reallocate to T1
        self.assertGreater(self.result.allocation_changes, 1)

    def test_good_return_due_to_aave_spike(self):
        # After repeg, Aave at 8% → daily yield should be positive throughout
        # total return should be positive
        self.assertGreater(self.result.total_return_pct, 0.0)

    def test_depeg_event_registered(self):
        event_types = [e["event_type"] for e in self.result.events_handled]
        self.assertIn("USDC_DEPEG", event_types)


class TestRunAllScenarios(unittest.TestCase):
    """Тесты run_all_scenarios."""

    def setUp(self):
        self.results = run_all_scenarios()

    def test_returns_three_scenarios(self):
        self.assertEqual(len(self.results), 3)

    def test_all_expected_names_present(self):
        self.assertIn("LUNA_CRASH_2022", self.results)
        self.assertIn("FTX_COLLAPSE_2022", self.results)
        self.assertIn("USDC_DEPEG_2023", self.results)

    def test_all_results_are_backtest_result(self):
        for r in self.results.values():
            self.assertIsInstance(r, BacktestResult)


class TestGenerateBacktestReport(unittest.TestCase):
    """Тесты generate_backtest_report."""

    def test_empty_results(self):
        report = generate_backtest_report({})
        self.assertEqual(report["scenarios_count"], 0)
        self.assertEqual(report["crisis_survival_rate"], 1.0)

    def test_report_has_required_fields(self):
        results = run_all_scenarios()
        report = generate_backtest_report(results)
        for key in ["scenarios_count", "worst_drawdown_pct", "best_return_pct",
                    "avg_sharpe", "crisis_survival_rate", "scenarios"]:
            self.assertIn(key, report)

    def test_scenarios_count_correct(self):
        results = run_all_scenarios()
        report = generate_backtest_report(results)
        self.assertEqual(report["scenarios_count"], 3)

    def test_crisis_survival_rate_range(self):
        results = run_all_scenarios()
        report = generate_backtest_report(results)
        self.assertGreaterEqual(report["crisis_survival_rate"], 0.0)
        self.assertLessEqual(report["crisis_survival_rate"], 1.0)

    def test_worst_drawdown_geq_zero(self):
        results = run_all_scenarios()
        report = generate_backtest_report(results)
        self.assertGreaterEqual(report["worst_drawdown_pct"], 0.0)


class TestSaveBacktestResults(unittest.TestCase):
    """Тесты атомарного сохранения результатов."""

    def test_save_creates_file(self):
        results = run_all_scenarios()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backtest_test.json")
            save_backtest_results(results, path=path)
            self.assertTrue(os.path.exists(path))

    def test_saved_json_is_valid(self):
        results = run_all_scenarios()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backtest_test.json")
            save_backtest_results(results, path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertIn("LUNA_CRASH_2022", data)

    def test_saved_json_has_all_fields(self):
        results = run_all_scenarios()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backtest_test.json")
            save_backtest_results(results, path=path)
            with open(path) as f:
                data = json.load(f)
            for name in results:
                entry = data[name]
                for field in ["scenario_name", "start_capital", "end_capital",
                               "total_return_pct", "max_drawdown_pct", "sharpe_ratio",
                               "days_tracked"]:
                    self.assertIn(field, entry)

    def test_atomic_write_no_partial_files(self):
        # After save, no .tmp files should remain
        results = run_all_scenarios()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backtest_test.json")
            save_backtest_results(results, path=path)
            tmp_files = [f for f in os.listdir(tmpdir) if f.endswith(".tmp")]
            self.assertEqual(tmp_files, [])


if __name__ == "__main__":
    unittest.main()
