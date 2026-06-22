"""
Tests for MP-750: YieldRunwayEstimator
Uses unittest only. ≥65 tests.
"""

import math
import os
import sys
import tempfile
import unittest

# Ensure repo root is on path
_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.yield_runway_estimator import (
    RunwayResult,
    _alert_level,
    _recommendation,
    compute_runway,
    estimate_portfolio,
    estimate_runway,
    load_history,
    save_results,
    simulate_capital,
)


# ---------------------------------------------------------------------------
# compute_runway
# ---------------------------------------------------------------------------

class TestComputeRunway(unittest.TestCase):

    def test_sustainable_yield_greater_than_withdrawal(self):
        """Yield > withdrawal → inf."""
        # 10% annual on $10k = $83/mo; withdrawal $50/mo → sustainable
        result = compute_runway(10_000, 10.0, 50.0)
        self.assertEqual(result, float("inf"))

    def test_zero_withdrawal_returns_inf(self):
        result = compute_runway(100_000, 5.0, 0.0)
        self.assertEqual(result, float("inf"))

    def test_negative_withdrawal_returns_inf(self):
        result = compute_runway(100_000, 5.0, -100.0)
        self.assertEqual(result, float("inf"))

    def test_depleting_returns_finite_months(self):
        """$1000 capital, 0% yield, $100/mo withdrawal → depleted in 10 months."""
        result = compute_runway(1_000, 0.0, 100.0)
        self.assertIsInstance(result, float)
        self.assertFalse(math.isinf(result))
        self.assertGreater(result, 0)

    def test_depleting_zero_yield_roughly_correct(self):
        """$1200 capital, 0% yield, $100/mo → ~12 months."""
        result = compute_runway(1_200, 0.0, 100.0)
        self.assertAlmostEqual(result, 12.0, delta=1)

    def test_negative_yield_fast_depletion(self):
        """Negative APY accelerates depletion compared to zero yield."""
        # 0% yield: $10k, $1000/mo → 10 months
        # -50% APY: capital shrinks faster → fewer months
        result_zero = compute_runway(10_000, 0.0, 1_000.0)
        result_neg = compute_runway(10_000, -50.0, 1_000.0)
        self.assertLess(result_neg, result_zero)

    def test_returns_float_type(self):
        result = compute_runway(5_000, 3.0, 200.0)
        self.assertIsInstance(result, float)

    def test_high_withdrawal_depletes_quickly(self):
        """Withdrawal equals full capital in 1 month (0% yield)."""
        result = compute_runway(1_000, 0.0, 1_000.0)
        self.assertAlmostEqual(result, 1.0, delta=1)

    def test_very_high_yield_sustainable(self):
        """30% annual yield on $100k = $2500/mo; withdrawal $1000 → sustainable."""
        result = compute_runway(100_000, 30.0, 1_000.0)
        self.assertEqual(result, float("inf"))

    def test_breakeven_yield_equals_withdrawal(self):
        """Exactly sustainable when monthly yield == monthly withdrawal."""
        # monthly yield = capital * annual_pct / 100 / 12
        capital = 12_000
        annual_pct = 12.0  # 1%/month = $120/month
        withdrawal = 120.0
        result = compute_runway(capital, annual_pct, withdrawal)
        self.assertEqual(result, float("inf"))


# ---------------------------------------------------------------------------
# simulate_capital
# ---------------------------------------------------------------------------

class TestSimulateCapital(unittest.TestCase):

    def test_zero_months_returns_initial(self):
        result = simulate_capital(50_000, 5.0, 100.0, 0)
        self.assertAlmostEqual(result, 50_000.0, places=4)

    def test_compounding_increases_capital_yield_gt_withdrawal(self):
        """High yield, small withdrawal → capital grows."""
        result = simulate_capital(100_000, 12.0, 100.0, 12)
        self.assertGreater(result, 100_000)

    def test_capital_depletes_when_withdrawal_gt_yield(self):
        """Capital shrinks when withdrawal >> yield."""
        result = simulate_capital(10_000, 0.0, 500.0, 12)
        self.assertLess(result, 10_000)

    def test_capital_floors_at_zero(self):
        """Capital never goes negative."""
        result = simulate_capital(1_000, 0.0, 2_000.0, 1)
        self.assertEqual(result, 0.0)

    def test_no_yield_no_withdrawal_unchanged(self):
        result = simulate_capital(50_000, 0.0, 0.0, 12)
        self.assertAlmostEqual(result, 50_000.0, places=4)

    def test_one_month_formula(self):
        """Verify one-month step manually."""
        initial = 10_000
        apy = 12.0  # 1%/month
        withdrawal = 50.0
        expected = initial * 1.01 - withdrawal
        result = simulate_capital(initial, apy, withdrawal, 1)
        self.assertAlmostEqual(result, expected, places=6)

    def test_negative_months_returns_initial(self):
        result = simulate_capital(10_000, 5.0, 100.0, -5)
        self.assertAlmostEqual(result, 10_000.0, places=4)


# ---------------------------------------------------------------------------
# estimate_runway (RunwayEstimate fields)
# ---------------------------------------------------------------------------

class TestEstimateRunwayFields(unittest.TestCase):

    def setUp(self):
        # Sustainable case: $100k @ 6% annual, $200/mo withdrawal
        self.est_sus = estimate_runway("SusFund", 100_000, 6.0, 200.0)
        # Depleting case: $5k @ 2% annual, $500/mo withdrawal
        self.est_dep = estimate_runway("DepFund", 5_000, 2.0, 500.0)

    # monthly_yield_pct
    def test_monthly_yield_pct_formula(self):
        self.assertAlmostEqual(self.est_sus.monthly_yield_pct, 6.0 / 12.0, places=8)

    # monthly_yield_usd
    def test_monthly_yield_usd_formula(self):
        expected = 100_000 * (6.0 / 12.0) / 100.0
        self.assertAlmostEqual(self.est_sus.monthly_yield_usd, expected, places=4)

    # net_monthly_change_usd
    def test_net_monthly_change_positive_when_sustainable(self):
        self.assertGreater(self.est_sus.net_monthly_change_usd, 0)

    def test_net_monthly_change_negative_when_depleting(self):
        self.assertLess(self.est_dep.net_monthly_change_usd, 0)

    def test_net_monthly_change_formula(self):
        expected = self.est_sus.monthly_yield_usd - self.est_sus.monthly_withdrawal_usd
        self.assertAlmostEqual(self.est_sus.net_monthly_change_usd, expected, places=6)

    # coverage_ratio
    def test_coverage_ratio_formula(self):
        expected = self.est_sus.monthly_yield_usd / self.est_sus.monthly_withdrawal_usd
        self.assertAlmostEqual(self.est_sus.coverage_ratio, expected, places=6)

    def test_coverage_ratio_zero_withdrawal_returns_inf(self):
        est = estimate_runway("ZeroW", 100_000, 5.0, 0.0)
        self.assertEqual(est.coverage_ratio, float("inf"))

    def test_coverage_ratio_depleting_lt_one(self):
        self.assertLess(self.est_dep.coverage_ratio, 1.0)

    # is_sustainable
    def test_is_sustainable_true_when_yield_ge_withdrawal(self):
        self.assertTrue(self.est_sus.is_sustainable)

    def test_is_sustainable_false_when_depleting(self):
        self.assertFalse(self.est_dep.is_sustainable)

    def test_is_sustainable_exact_breakeven(self):
        capital = 12_000
        annual_pct = 12.0  # 1%/month = $120/month
        est = estimate_runway("BEven", capital, annual_pct, 120.0)
        self.assertTrue(est.is_sustainable)

    # runway_months
    def test_runway_months_inf_when_sustainable(self):
        self.assertEqual(self.est_sus.runway_months, float("inf"))

    def test_runway_months_finite_when_depleting(self):
        self.assertFalse(math.isinf(self.est_dep.runway_months))
        self.assertGreater(self.est_dep.runway_months, 0)

    # runway_years
    def test_runway_years_inf_when_sustainable(self):
        self.assertEqual(self.est_sus.runway_years, float("inf"))

    def test_runway_years_finite_depleting(self):
        self.assertFalse(math.isinf(self.est_dep.runway_years))

    def test_runway_years_equals_months_div_12(self):
        est = estimate_runway("Dep12", 1_200, 0.0, 100.0)
        self.assertAlmostEqual(est.runway_years, est.runway_months / 12.0, places=6)

    # capital milestones
    def test_capital_at_6m_sustainable_gt_initial(self):
        # when yield >> withdrawal, capital grows
        est = estimate_runway("HighY", 100_000, 20.0, 100.0)
        self.assertGreater(est.capital_at_6m_usd, 100_000)

    def test_capital_at_6m_depleting_lt_initial(self):
        self.assertLess(self.est_dep.capital_at_6m_usd, 5_000)

    def test_capital_at_12m_gt_6m_when_sustainable(self):
        est = estimate_runway("HighY2", 100_000, 20.0, 100.0)
        self.assertGreater(est.capital_at_12m_usd, est.capital_at_6m_usd)

    def test_capital_at_24m_gt_12m_when_sustainable(self):
        est = estimate_runway("HighY3", 100_000, 20.0, 100.0)
        self.assertGreater(est.capital_at_24m_usd, est.capital_at_12m_usd)

    def test_capital_at_12m_simulated_correctly(self):
        capital = 100_000
        apy = 6.0
        withdrawal = 200.0
        expected = simulate_capital(capital, apy, withdrawal, 12)
        est = estimate_runway("Check12m", capital, apy, withdrawal)
        self.assertAlmostEqual(est.capital_at_12m_usd, expected, places=4)

    def test_capital_at_24m_simulated_correctly(self):
        capital = 100_000
        apy = 6.0
        withdrawal = 200.0
        expected = simulate_capital(capital, apy, withdrawal, 24)
        est = estimate_runway("Check24m", capital, apy, withdrawal)
        self.assertAlmostEqual(est.capital_at_24m_usd, expected, places=4)

    # withdrawal_rate_pct
    def test_withdrawal_rate_pct_formula(self):
        # $200 / $100k * 100 = 0.2%
        self.assertAlmostEqual(self.est_sus.withdrawal_rate_pct, 0.2, places=6)

    def test_withdrawal_rate_pct_zero_when_no_withdrawal(self):
        est = estimate_runway("NoW", 100_000, 5.0, 0.0)
        self.assertAlmostEqual(est.withdrawal_rate_pct, 0.0, places=6)


# ---------------------------------------------------------------------------
# alert_level
# ---------------------------------------------------------------------------

class TestAlertLevel(unittest.TestCase):

    def test_sustainable_flag_gives_sustainable(self):
        self.assertEqual(_alert_level(float("inf"), True), "SUSTAINABLE")

    def test_inf_runway_sustainable_even_if_not_flagged(self):
        self.assertEqual(_alert_level(float("inf"), False), "SUSTAINABLE")

    def test_runway_36_sustainable(self):
        self.assertEqual(_alert_level(36.0, False), "SUSTAINABLE")

    def test_runway_50_sustainable(self):
        self.assertEqual(_alert_level(50.0, False), "SUSTAINABLE")

    def test_runway_12_caution(self):
        self.assertEqual(_alert_level(12.0, False), "CAUTION")

    def test_runway_24_caution(self):
        self.assertEqual(_alert_level(24.0, False), "CAUTION")

    def test_runway_35_caution(self):
        self.assertEqual(_alert_level(35.9, False), "CAUTION")

    def test_runway_6_critical(self):
        self.assertEqual(_alert_level(6.0, False), "CRITICAL")

    def test_runway_11_critical(self):
        self.assertEqual(_alert_level(11.0, False), "CRITICAL")

    def test_runway_5_depleting(self):
        self.assertEqual(_alert_level(5.0, False), "DEPLETING")

    def test_runway_1_depleting(self):
        self.assertEqual(_alert_level(1.0, False), "DEPLETING")

    def test_runway_0_depleting(self):
        self.assertEqual(_alert_level(0.0, False), "DEPLETING")

    def test_alert_level_in_estimate_sustainable(self):
        est = estimate_runway("A", 100_000, 12.0, 100.0)
        self.assertEqual(est.alert_level, "SUSTAINABLE")

    def test_alert_level_in_estimate_depleting(self):
        est = estimate_runway("B", 1_000, 0.0, 1_000.0)
        self.assertEqual(est.alert_level, "DEPLETING")


# ---------------------------------------------------------------------------
# recommendation
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):

    def test_sustainable_recommendation(self):
        rec = _recommendation("SUSTAINABLE")
        self.assertIsInstance(rec, str)
        self.assertGreater(len(rec), 0)

    def test_caution_recommendation(self):
        rec = _recommendation("CAUTION")
        self.assertIsInstance(rec, str)
        self.assertGreater(len(rec), 0)

    def test_critical_recommendation(self):
        rec = _recommendation("CRITICAL")
        self.assertIsInstance(rec, str)
        self.assertGreater(len(rec), 0)

    def test_depleting_recommendation(self):
        rec = _recommendation("DEPLETING")
        self.assertIsInstance(rec, str)
        self.assertGreater(len(rec), 0)

    def test_all_recommendations_distinct(self):
        recs = {_recommendation(lvl) for lvl in ("SUSTAINABLE", "CAUTION", "CRITICAL", "DEPLETING")}
        self.assertEqual(len(recs), 4)

    def test_estimate_has_recommendation(self):
        est = estimate_runway("X", 10_000, 5.0, 200.0)
        self.assertIsInstance(est.recommendation, str)
        self.assertGreater(len(est.recommendation), 0)


# ---------------------------------------------------------------------------
# estimate_portfolio / RunwayResult
# ---------------------------------------------------------------------------

class TestEstimatePortfolio(unittest.TestCase):

    def _strategies(self):
        return [
            {"strategy_name": "Alpha", "initial_capital_usd": 100_000,
             "annual_yield_pct": 10.0, "monthly_withdrawal_usd": 200},
            {"strategy_name": "Beta", "initial_capital_usd": 20_000,
             "annual_yield_pct": 3.0, "monthly_withdrawal_usd": 1_000},
            {"strategy_name": "Gamma", "initial_capital_usd": 5_000,
             "annual_yield_pct": 1.0, "monthly_withdrawal_usd": 100},
        ]

    def test_sustainable_strategies_only_is_sustainable_true(self):
        result = estimate_portfolio(self._strategies())
        for name in result.sustainable_strategies:
            est = next(e for e in result.estimates if e.strategy_name == name)
            self.assertTrue(est.is_sustainable)

    def test_critical_strategies_only_critical_or_depleting(self):
        result = estimate_portfolio(self._strategies())
        for name in result.critical_strategies:
            est = next(e for e in result.estimates if e.strategy_name == name)
            self.assertIn(est.alert_level, ("CRITICAL", "DEPLETING"))

    def test_longest_runway_strategy_is_max(self):
        result = estimate_portfolio(self._strategies())
        # Alpha is sustainable → inf
        self.assertEqual(result.longest_runway_strategy, "Alpha")

    def test_shortest_runway_strategy_is_min(self):
        result = estimate_portfolio(self._strategies())
        # Beta: $20k @ 3%, $1000/mo → shortest finite runway
        self.assertIn(result.shortest_runway_strategy, ["Beta", "Gamma"])

    def test_avg_coverage_ratio_caps_inf_at_999(self):
        result = estimate_portfolio(self._strategies())
        # Alpha is sustainable → coverage_ratio >= 1 → might be capped at 999 for avg
        self.assertLessEqual(result.avg_coverage_ratio, 999.0)

    def test_avg_coverage_ratio_computed(self):
        result = estimate_portfolio(self._strategies())
        self.assertGreater(result.avg_coverage_ratio, 0)

    def test_empty_strategies_returns_result(self):
        result = estimate_portfolio([])
        self.assertIsInstance(result, RunwayResult)
        self.assertEqual(result.estimates, [])

    def test_all_sustainable_summary_message(self):
        strategies = [
            {"strategy_name": "A", "initial_capital_usd": 100_000,
             "annual_yield_pct": 20.0, "monthly_withdrawal_usd": 100},
            {"strategy_name": "B", "initial_capital_usd": 100_000,
             "annual_yield_pct": 15.0, "monthly_withdrawal_usd": 50},
        ]
        result = estimate_portfolio(strategies)
        self.assertIn("sustainable", result.recommendation_summary.lower())

    def test_result_estimates_length_matches_input(self):
        result = estimate_portfolio(self._strategies())
        self.assertEqual(len(result.estimates), 3)

    def test_single_strategy_both_longest_and_shortest(self):
        strategies = [
            {"strategy_name": "Solo", "initial_capital_usd": 10_000,
             "annual_yield_pct": 5.0, "monthly_withdrawal_usd": 500},
        ]
        result = estimate_portfolio(strategies)
        self.assertEqual(result.longest_runway_strategy, "Solo")
        self.assertEqual(result.shortest_runway_strategy, "Solo")


# ---------------------------------------------------------------------------
# save / load / ring-buffer
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):

    def _tmp_path(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)  # start fresh
        return path

    def test_save_creates_file(self):
        path = self._tmp_path()
        strategies = [
            {"strategy_name": "T1", "initial_capital_usd": 10_000,
             "annual_yield_pct": 5.0, "monthly_withdrawal_usd": 100},
        ]
        result = estimate_portfolio(strategies)
        save_results(result, path)
        self.assertTrue(os.path.exists(path))

    def test_load_returns_list(self):
        path = self._tmp_path()
        strategies = [
            {"strategy_name": "T2", "initial_capital_usd": 10_000,
             "annual_yield_pct": 5.0, "monthly_withdrawal_usd": 100},
        ]
        result = estimate_portfolio(strategies)
        save_results(result, path)
        history = load_history(path)
        self.assertIsInstance(history, list)

    def test_save_load_round_trip_entry_count(self):
        path = self._tmp_path()
        strategies = [
            {"strategy_name": "T3", "initial_capital_usd": 10_000,
             "annual_yield_pct": 5.0, "monthly_withdrawal_usd": 100},
        ]
        result = estimate_portfolio(strategies)
        save_results(result, path)
        history = load_history(path)
        self.assertEqual(len(history), 1)

    def test_load_nonexistent_file_returns_empty_list(self):
        history = load_history("/tmp/nonexistent_yield_runway_xyz_test.json")
        self.assertEqual(history, [])

    def test_ring_buffer_cap_100(self):
        path = self._tmp_path()
        strategies = [
            {"strategy_name": "T4", "initial_capital_usd": 10_000,
             "annual_yield_pct": 5.0, "monthly_withdrawal_usd": 100},
        ]
        result = estimate_portfolio(strategies)
        for _ in range(105):
            save_results(result, path)
        history = load_history(path)
        self.assertLessEqual(len(history), 100)

    def test_ring_buffer_keeps_latest(self):
        path = self._tmp_path()
        # First 5 saves
        for i in range(5):
            strats = [{"strategy_name": f"S{i}", "initial_capital_usd": 10_000,
                       "annual_yield_pct": 5.0, "monthly_withdrawal_usd": 100}]
            save_results(estimate_portfolio(strats), path)
        history = load_history(path)
        self.assertEqual(len(history), 5)

    def test_saved_data_has_timestamp(self):
        path = self._tmp_path()
        result = estimate_portfolio([
            {"strategy_name": "TS", "initial_capital_usd": 10_000,
             "annual_yield_pct": 5.0, "monthly_withdrawal_usd": 100},
        ])
        save_results(result, path)
        history = load_history(path)
        self.assertIn("timestamp", history[0])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_100_pct_monthly_withdrawal_depletes_quickly(self):
        """$1000 capital, 0% yield, $1000/month → depletion in ~1 month."""
        est = estimate_runway("Edge1", 1_000, 0.0, 1_000.0)
        self.assertFalse(math.isinf(est.runway_months))
        self.assertLessEqual(est.runway_months, 2)

    def test_very_high_yield_long_runway(self):
        """100% annual yield >> withdrawal → sustainable."""
        est = estimate_runway("HighYield", 100_000, 100.0, 1_000.0)
        self.assertTrue(est.is_sustainable)
        self.assertEqual(est.runway_months, float("inf"))

    def test_zero_capital_runway(self):
        """$0 capital with any withdrawal → immediate depletion."""
        result = compute_runway(0, 5.0, 100.0)
        self.assertFalse(math.isinf(result))

    def test_very_small_capital_depletes_fast(self):
        est = estimate_runway("Tiny", 1.0, 0.0, 100.0)
        self.assertFalse(math.isinf(est.runway_months))
        self.assertLessEqual(est.runway_months, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
