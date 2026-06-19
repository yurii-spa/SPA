"""
tests/test_rs001_stress_engine.py

40 unit tests for spa_core/analytics/rs001_stress_engine.py

Coverage:
  TestInstantiation        (3 tests)  — engine constructs; slot weights sum to 1.0
  TestRunScenario          (8 tests)  — return type, field types, invalid scenario
  TestBtcCrash80           (5 tests)  — survivable, drawdown, APY, recovery_days
  TestGmxExploit           (4 tests)  — survivable, drawdown, APY, recovery_days
  TestIlExtreme            (4 tests)  — survivable, drawdown, APY, recovery_days
  TestFeedDown             (3 tests)  — survivable, drawdown, APY
  TestMultiContagion       (5 tests)  — not survivable, drawdown, APY, failed slots
  TestStablecoinDepeg      (3 tests)  — survivable, drawdown, APY
  TestBtcCrash50           (3 tests)  — survivable, drawdown
  TestRunAll               (4 tests)  — length 7, all StressResult, all names covered
  TestWorstCase            (3 tests)  — returns StressResult, min APY, is il_extreme
  TestAllSurvivable        (2 tests)  — returns bool; is False
  TestSummaryTable         (3 tests)  — string, contains all 7 scenario names

Sprint v9.77 — MP-1361
Date: 2026-06-19
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from spa_core.analytics.rs001_stress_engine import (
    RS001StressEngine,
    SCENARIOS,
    StressResult,
)


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _engine() -> RS001StressEngine:
    return RS001StressEngine()


# ── Tests ────────────────────────────────────────────────────────────────────────

class TestInstantiation(unittest.TestCase):
    """Engine constructs without arguments; structural invariants hold."""

    def test_engine_instantiates(self):
        engine = RS001StressEngine()
        self.assertIsInstance(engine, RS001StressEngine)

    def test_slot_weights_sum_to_one(self):
        engine = _engine()
        total = sum(engine.SLOT_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_fallback_apys_all_positive(self):
        engine = _engine()
        for slot, apy in engine.FALLBACK_APYS.items():
            with self.subTest(slot=slot):
                self.assertGreater(apy, 0.0)


class TestRunScenario(unittest.TestCase):
    """run_scenario() return types and field types."""

    def setUp(self):
        self.engine = _engine()

    def test_run_scenario_returns_stress_result(self):
        result = self.engine.run_scenario("btc_crash_80")
        self.assertIsInstance(result, StressResult)

    def test_stress_result_scenario_name_matches(self):
        result = self.engine.run_scenario("btc_crash_80")
        self.assertEqual(result.scenario, "btc_crash_80")

    def test_stress_result_portfolio_apy_is_float(self):
        result = self.engine.run_scenario("feed_down")
        self.assertIsInstance(result.portfolio_apy, float)

    def test_stress_result_max_drawdown_is_float(self):
        result = self.engine.run_scenario("gmx_exploit")
        self.assertIsInstance(result.max_drawdown, float)

    def test_stress_result_recovery_days_is_int(self):
        result = self.engine.run_scenario("il_extreme")
        self.assertIsInstance(result.recovery_days, int)

    def test_stress_result_survivable_is_bool(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                result = self.engine.run_scenario(scenario)
                self.assertIsInstance(result.survivable, bool)

    def test_stress_result_has_details_dict(self):
        result = self.engine.run_scenario("stablecoin_depeg")
        self.assertIsInstance(result.details, dict)

    def test_invalid_scenario_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.engine.run_scenario("nonexistent_scenario_xyz")


class TestMaxDrawdownInvariant(unittest.TestCase):
    """max_drawdown must be <= 0 for every scenario."""

    def setUp(self):
        self.engine = _engine()

    def test_max_drawdown_always_non_positive(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                result = self.engine.run_scenario(scenario)
                self.assertLessEqual(result.max_drawdown, 0.0,
                    msg=f"{scenario}: max_drawdown={result.max_drawdown} should be <= 0")


class TestBtcCrash80(unittest.TestCase):

    def setUp(self):
        self.engine = _engine()
        self.result = self.engine.run_scenario("btc_crash_80")

    def test_btc_crash_80_survivable_true(self):
        self.assertTrue(self.result.survivable)

    def test_btc_crash_80_max_drawdown_value(self):
        self.assertAlmostEqual(self.result.max_drawdown, -0.20, places=9)

    def test_btc_crash_80_portfolio_apy_positive(self):
        self.assertGreater(self.result.portfolio_apy, 0.0)

    def test_btc_crash_80_portfolio_apy_expected(self):
        # gmx_btc(20%×15) + gmx_eth(20%×15) + btc_pool(15%×0) + eth_agg(15%×0) + gold(15%×8) + stable(15%×6)
        expected = 0.20 * 15.0 + 0.20 * 15.0 + 0.0 + 0.0 + 0.15 * 8.0 + 0.15 * 6.0
        self.assertAlmostEqual(self.result.portfolio_apy, expected, places=3)

    def test_btc_crash_80_recovery_days(self):
        self.assertEqual(self.result.recovery_days, 180)


class TestGmxExploit(unittest.TestCase):

    def setUp(self):
        self.engine = _engine()
        self.result = self.engine.run_scenario("gmx_exploit")

    def test_gmx_exploit_survivable_true(self):
        self.assertTrue(self.result.survivable)

    def test_gmx_exploit_max_drawdown(self):
        self.assertAlmostEqual(self.result.max_drawdown, -0.40, places=9)

    def test_gmx_exploit_portfolio_apy(self):
        # Only non-GMX slots earn
        expected = 0.15 * 8.0 + 0.15 * 12.0 + 0.15 * 8.0 + 0.15 * 6.0
        self.assertAlmostEqual(self.result.portfolio_apy, expected, places=3)

    def test_gmx_exploit_recovery_days(self):
        self.assertEqual(self.result.recovery_days, 365)


class TestIlExtreme(unittest.TestCase):

    def setUp(self):
        self.engine = _engine()
        self.result = self.engine.run_scenario("il_extreme")

    def test_il_extreme_survivable_true(self):
        self.assertTrue(self.result.survivable)

    def test_il_extreme_max_drawdown(self):
        self.assertAlmostEqual(self.result.max_drawdown, -0.15, places=9)

    def test_il_extreme_portfolio_apy(self):
        # Only gold_proxy and stablecoin_t1 earn
        expected = 0.15 * 8.0 + 0.15 * 6.0
        self.assertAlmostEqual(self.result.portfolio_apy, expected, places=3)

    def test_il_extreme_recovery_days(self):
        self.assertEqual(self.result.recovery_days, 60)


class TestFeedDown(unittest.TestCase):

    def setUp(self):
        self.engine = _engine()
        self.result = self.engine.run_scenario("feed_down")

    def test_feed_down_survivable_true(self):
        self.assertTrue(self.result.survivable)

    def test_feed_down_max_drawdown(self):
        self.assertAlmostEqual(self.result.max_drawdown, -0.01, places=9)

    def test_feed_down_portfolio_apy(self):
        # All slots at FALLBACK_APYS
        engine = self.engine
        expected = sum(
            engine.SLOT_WEIGHTS[s] * engine.FALLBACK_APYS[s]
            for s in engine.SLOT_WEIGHTS
        )
        self.assertAlmostEqual(self.result.portfolio_apy, expected, places=3)


class TestMultiContagion(unittest.TestCase):

    def setUp(self):
        self.engine = _engine()
        self.result = self.engine.run_scenario("multi_contagion")

    def test_multi_contagion_survivable_false(self):
        self.assertFalse(self.result.survivable)

    def test_multi_contagion_max_drawdown(self):
        # top-3 by weight: gmx_btc(20%) + gmx_eth(20%) + btc_pool(15%) = 55%
        self.assertAlmostEqual(self.result.max_drawdown, -0.55, places=4)

    def test_multi_contagion_portfolio_apy(self):
        # top-3 failed → only eth_aggressive + gold_proxy + stablecoin_t1 earn
        expected = 0.15 * 12.0 + 0.15 * 8.0 + 0.15 * 6.0
        self.assertAlmostEqual(self.result.portfolio_apy, expected, places=3)

    def test_multi_contagion_recovery_days_long(self):
        self.assertGreaterEqual(self.result.recovery_days, 700)

    def test_multi_contagion_details_has_failed_slots(self):
        self.assertIn("failed_slots", self.result.details)
        self.assertEqual(len(self.result.details["failed_slots"]), 3)


class TestStablecoinDepeg(unittest.TestCase):

    def setUp(self):
        self.engine = _engine()
        self.result = self.engine.run_scenario("stablecoin_depeg")

    def test_stablecoin_depeg_survivable_true(self):
        self.assertTrue(self.result.survivable)

    def test_stablecoin_depeg_max_drawdown(self):
        self.assertAlmostEqual(self.result.max_drawdown, -0.03, places=9)

    def test_stablecoin_depeg_portfolio_apy(self):
        # stablecoin_t1 → 0; others at FALLBACK_APYS
        engine = self.engine
        expected = (
            0.20 * 15.0 + 0.20 * 15.0
            + 0.15 * 8.0 + 0.15 * 12.0
            + 0.15 * 8.0 + 0.15 * 0.0
        )
        self.assertAlmostEqual(self.result.portfolio_apy, expected, places=3)


class TestBtcCrash50(unittest.TestCase):

    def setUp(self):
        self.engine = _engine()
        self.result = self.engine.run_scenario("btc_crash_50")

    def test_btc_crash_50_survivable_true(self):
        self.assertTrue(self.result.survivable)

    def test_btc_crash_50_max_drawdown(self):
        self.assertAlmostEqual(self.result.max_drawdown, -0.10, places=9)

    def test_btc_crash_50_less_severe_than_80(self):
        result_80 = self.engine.run_scenario("btc_crash_80")
        # -50% crash → higher APY than -80% crash
        self.assertGreater(self.result.portfolio_apy, result_80.portfolio_apy)


class TestRunAll(unittest.TestCase):

    def setUp(self):
        self.engine = _engine()

    def test_run_all_returns_list_of_7(self):
        results = self.engine.run_all()
        self.assertEqual(len(results), 7)

    def test_run_all_all_are_stress_results(self):
        results = self.engine.run_all()
        for r in results:
            with self.subTest(scenario=r.scenario):
                self.assertIsInstance(r, StressResult)

    def test_run_all_covers_all_scenario_names(self):
        results = self.engine.run_all()
        names = {r.scenario for r in results}
        self.assertEqual(names, set(SCENARIOS))

    def test_run_all_no_exception(self):
        try:
            self.engine.run_all()
        except Exception as exc:
            self.fail(f"run_all() raised {exc!r}")


class TestWorstCase(unittest.TestCase):

    def setUp(self):
        self.engine = _engine()

    def test_worst_case_returns_stress_result(self):
        wc = self.engine.worst_case()
        self.assertIsInstance(wc, StressResult)

    def test_worst_case_has_lowest_portfolio_apy(self):
        results = self.engine.run_all()
        wc = self.engine.worst_case()
        min_apy = min(r.portfolio_apy for r in results)
        self.assertAlmostEqual(wc.portfolio_apy, min_apy, places=9)

    def test_worst_case_is_il_extreme(self):
        wc = self.engine.worst_case()
        self.assertEqual(wc.scenario, "il_extreme")


class TestAllSurvivable(unittest.TestCase):

    def setUp(self):
        self.engine = _engine()

    def test_all_survivable_returns_bool(self):
        result = self.engine.all_survivable()
        self.assertIsInstance(result, bool)

    def test_all_survivable_is_false(self):
        # multi_contagion.survivable == False → portfolio does NOT survive all scenarios
        self.assertFalse(self.engine.all_survivable())


class TestSummaryTable(unittest.TestCase):

    def setUp(self):
        self.engine = _engine()
        self.table = self.engine.summary_table()

    def test_summary_table_is_string(self):
        self.assertIsInstance(self.table, str)

    def test_summary_table_contains_all_scenario_names(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                self.assertIn(scenario, self.table)

    def test_summary_table_has_header_row(self):
        self.assertIn("Scenario", self.table)
        self.assertIn("Max Drawdown", self.table)


if __name__ == "__main__":
    unittest.main(verbosity=2)
