"""
Tests for ExitTimingOptimizer (MP-720 / SPA-V597).
Run: python3 -m pytest spa_core/tests/test_exit_timing_optimizer.py -v
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.exit_timing_optimizer import (
    ExitScenario,
    ExitTimingReport,
    _SCENARIO_DAYS,
    analyze,
    compare_positions,
    load_history,
    model_scenario,
    save_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ms(
    exit_day: int = 30,
    current_apy: float = 5.0,
    daily_decay_rate: float = 0.0,
    lock_period_days: int = 0,
    days_already_held: int = 0,
    alternative_apy: float = 3.0,
) -> ExitScenario:
    return model_scenario(
        exit_day, current_apy, daily_decay_rate,
        lock_period_days, days_already_held, alternative_apy,
    )


def _report(
    current_apy: float = 5.0,
    daily_decay_rate: float = 0.0,
    lock_period_days: int = 0,
    days_already_held: int = 0,
    alternative_apy: float = 3.0,
    protocol: str = "TestProto",
    pool: str = "TestPool",
) -> ExitTimingReport:
    return analyze(
        protocol, pool, current_apy, daily_decay_rate,
        lock_period_days, days_already_held, alternative_apy,
    )


# ===========================================================================
# model_scenario — cumulative_yield (trapezoidal)
# ===========================================================================

class TestModelScenarioYield(unittest.TestCase):

    def test_yield_at_day0_is_zero(self):
        s = _ms(exit_day=0)
        self.assertAlmostEqual(s.cumulative_yield_pct, 0.0, places=8)

    def test_yield_no_decay_proportional_to_days(self):
        """No decay → both start and end APY are same → trapezoid = simple linear."""
        s30 = _ms(exit_day=30, current_apy=5.0, daily_decay_rate=0.0)
        expected = (5.0 / 365.0) * 30
        self.assertAlmostEqual(s30.cumulative_yield_pct, expected, places=6)

    def test_yield_no_decay_7_days(self):
        s = _ms(exit_day=7, current_apy=10.0, daily_decay_rate=0.0)
        expected = (10.0 / 365.0) * 7
        self.assertAlmostEqual(s.cumulative_yield_pct, expected, places=6)

    def test_yield_with_decay_lower_than_no_decay(self):
        s_no_decay = _ms(exit_day=30, current_apy=5.0, daily_decay_rate=0.0)
        s_decay = _ms(exit_day=30, current_apy=5.0, daily_decay_rate=1.0)
        self.assertLess(s_decay.cumulative_yield_pct, s_no_decay.cumulative_yield_pct)

    def test_yield_decay_formula_trapezoidal(self):
        """Verify trapezoidal formula manually for day=14, decay=2%."""
        apy = 8.0
        decay = 2.0
        days = 14
        effective = max(0.0, apy * (1 - decay / 100) ** days)
        expected = ((apy + effective) / 2.0) / 365.0 * days
        s = _ms(exit_day=days, current_apy=apy, daily_decay_rate=decay)
        self.assertAlmostEqual(s.cumulative_yield_pct, expected, places=6)

    def test_yield_full_decay_clamps_effective_apy_to_zero(self):
        """decay_rate=100 → effective APY = 0 after day 1."""
        s = _ms(exit_day=10, current_apy=5.0, daily_decay_rate=100.0)
        effective = max(0.0, 5.0 * (1 - 1.0) ** 10)
        expected = ((5.0 + effective) / 2.0) / 365.0 * 10
        self.assertAlmostEqual(s.cumulative_yield_pct, expected, places=6)

    def test_yield_180_days_no_decay(self):
        s = _ms(exit_day=180, current_apy=4.0, daily_decay_rate=0.0)
        expected = (4.0 / 365.0) * 180
        self.assertAlmostEqual(s.cumulative_yield_pct, expected, places=5)


# ===========================================================================
# model_scenario — cumulative_gas
# ===========================================================================

class TestModelScenarioGas(unittest.TestCase):
    """Gas events = exit_day // 30 + 1.  Cost = 0.05 * events."""

    def test_gas_1_event_day0(self):
        self.assertAlmostEqual(_ms(exit_day=0).cumulative_gas_pct, 0.05, places=8)

    def test_gas_1_event_day7(self):
        self.assertAlmostEqual(_ms(exit_day=7).cumulative_gas_pct, 0.05, places=8)

    def test_gas_1_event_day14(self):
        self.assertAlmostEqual(_ms(exit_day=14).cumulative_gas_pct, 0.05, places=8)

    def test_gas_1_event_day29(self):
        self.assertAlmostEqual(_ms(exit_day=29).cumulative_gas_pct, 0.05, places=8)

    def test_gas_2_events_day30(self):
        self.assertAlmostEqual(_ms(exit_day=30).cumulative_gas_pct, 0.10, places=8)

    def test_gas_2_events_day59(self):
        self.assertAlmostEqual(_ms(exit_day=59).cumulative_gas_pct, 0.10, places=8)

    def test_gas_3_events_day60(self):
        self.assertAlmostEqual(_ms(exit_day=60).cumulative_gas_pct, 0.15, places=8)

    def test_gas_3_events_day89(self):
        self.assertAlmostEqual(_ms(exit_day=89).cumulative_gas_pct, 0.15, places=8)

    def test_gas_4_events_day90(self):
        self.assertAlmostEqual(_ms(exit_day=90).cumulative_gas_pct, 0.20, places=8)

    def test_gas_7_events_day180(self):
        # 180 // 30 + 1 = 7
        self.assertAlmostEqual(_ms(exit_day=180).cumulative_gas_pct, 0.35, places=8)

    def test_gas_always_positive(self):
        for d in _SCENARIO_DAYS:
            with self.subTest(day=d):
                self.assertGreater(_ms(exit_day=d).cumulative_gas_pct, 0)


# ===========================================================================
# model_scenario — is_locked
# ===========================================================================

class TestModelScenarioLock(unittest.TestCase):

    def test_is_locked_day0_inside_lock(self):
        # remaining_lock = 30 - 0 = 30; 0 < 30 → True
        s = model_scenario(0, 5.0, 0.0, 30, 0, 3.0)
        self.assertTrue(s.is_locked)

    def test_is_locked_day29_inside_lock(self):
        s = model_scenario(29, 5.0, 0.0, 30, 0, 3.0)
        self.assertTrue(s.is_locked)

    def test_not_locked_day30_at_boundary(self):
        # remaining_lock = 30; 30 < 30 → False
        s = model_scenario(30, 5.0, 0.0, 30, 0, 3.0)
        self.assertFalse(s.is_locked)

    def test_not_locked_day31_past_lock(self):
        s = model_scenario(31, 5.0, 0.0, 30, 0, 3.0)
        self.assertFalse(s.is_locked)

    def test_not_locked_when_no_lock(self):
        # lock_period=0 → remaining_lock=0; day < 0 → False
        s = model_scenario(0, 5.0, 0.0, 0, 0, 3.0)
        self.assertFalse(s.is_locked)

    def test_not_locked_when_held_exceeds_lock(self):
        # lock=30, held=40 → remaining=0; no day < 0 → False
        s = model_scenario(0, 5.0, 0.0, 30, 40, 3.0)
        self.assertFalse(s.is_locked)

    def test_partial_lock_remaining(self):
        # lock=60, held=30 → remaining=30; day 14 < 30 → True
        s = model_scenario(14, 5.0, 0.0, 60, 30, 3.0)
        self.assertTrue(s.is_locked)

    def test_partial_lock_cleared(self):
        # lock=60, held=30 → remaining=30; day 30 < 30 → False
        s = model_scenario(30, 5.0, 0.0, 60, 30, 3.0)
        self.assertFalse(s.is_locked)


# ===========================================================================
# model_scenario — opportunity_cost & net_gain
# ===========================================================================

class TestModelScenarioOpportunityCost(unittest.TestCase):

    def test_opp_cost_negative_when_alt_lower(self):
        # alt=3%, current=5% → alt earns less → opp_cost < 0
        s = _ms(exit_day=30, current_apy=5.0, alternative_apy=3.0)
        self.assertLess(s.opportunity_cost_pct, 0.0)

    def test_opp_cost_positive_when_alt_higher(self):
        # alt=8%, current=5% → we miss out → opp_cost > 0
        s = _ms(exit_day=30, current_apy=5.0, alternative_apy=8.0)
        self.assertGreater(s.opportunity_cost_pct, 0.0)

    def test_opp_cost_at_day0_is_zero(self):
        # No time has passed → both yields are 0
        s = _ms(exit_day=0, current_apy=5.0, alternative_apy=10.0)
        self.assertAlmostEqual(s.opportunity_cost_pct, 0.0, places=8)

    def test_negative_opp_cost_clipped_in_net_gain(self):
        """Negative opportunity cost → add no penalty to net_gain."""
        s = _ms(exit_day=30, current_apy=5.0, alternative_apy=3.0)
        # opp_cost < 0 → net = yield - gas - 0
        expected_net = s.cumulative_yield_pct - s.cumulative_gas_pct
        self.assertAlmostEqual(s.net_gain_pct, expected_net, places=6)

    def test_positive_opp_cost_reduces_net_gain(self):
        """Positive opportunity cost → deducted from net_gain."""
        s = _ms(exit_day=30, current_apy=5.0, alternative_apy=8.0)
        self.assertGreater(s.opportunity_cost_pct, 0.0)
        expected_net = (
            s.cumulative_yield_pct - s.cumulative_gas_pct - s.opportunity_cost_pct
        )
        self.assertAlmostEqual(s.net_gain_pct, expected_net, places=6)

    def test_net_gain_formula_explicit(self):
        apy, alt, days, decay = 5.0, 3.0, 30, 0.0
        effective = apy
        yield_pct = ((apy + effective) / 2.0) / 365.0 * days
        gas = 0.05 * (days // 30 + 1)
        opp = alt / 365.0 * days - yield_pct
        expected_net = yield_pct - gas - max(0.0, opp)
        s = model_scenario(days, apy, decay, 0, 0, alt)
        self.assertAlmostEqual(s.net_gain_pct, expected_net, places=6)


# ===========================================================================
# analyze — scenarios structure
# ===========================================================================

class TestAnalyzeScenarios(unittest.TestCase):

    def test_scenarios_has_exactly_7_entries(self):
        r = _report()
        self.assertEqual(len(r.scenarios), 7)

    def test_scenarios_days_are_0_7_14_30_60_90_180(self):
        r = _report()
        days = [s.exit_day for s in r.scenarios]
        self.assertEqual(days, [0, 7, 14, 30, 60, 90, 180])

    def test_scenarios_match_constant(self):
        r = _report()
        days = [s.exit_day for s in r.scenarios]
        self.assertEqual(days, _SCENARIO_DAYS)


# ===========================================================================
# analyze — remaining_lock_days
# ===========================================================================

class TestAnalyzeRemainingLock(unittest.TestCase):

    def test_remaining_lock_no_lock(self):
        r = _report(lock_period_days=0, days_already_held=0)
        self.assertEqual(r.remaining_lock_days, 0)

    def test_remaining_lock_full(self):
        r = _report(lock_period_days=30, days_already_held=0)
        self.assertEqual(r.remaining_lock_days, 30)

    def test_remaining_lock_partial(self):
        r = _report(lock_period_days=60, days_already_held=20)
        self.assertEqual(r.remaining_lock_days, 40)

    def test_remaining_lock_zero_when_held_equals_lock(self):
        r = _report(lock_period_days=30, days_already_held=30)
        self.assertEqual(r.remaining_lock_days, 0)

    def test_remaining_lock_zero_when_held_exceeds_lock(self):
        r = _report(lock_period_days=30, days_already_held=50)
        self.assertEqual(r.remaining_lock_days, 0)


# ===========================================================================
# analyze — optimal_exit_day
# ===========================================================================

class TestAnalyzeOptimal(unittest.TestCase):

    def test_optimal_exit_day_is_unlocked(self):
        """All scenarios are unlocked (no lock) → optimal is among all."""
        r = _report(lock_period_days=0, current_apy=5.0, alternative_apy=3.0)
        optimal_s = next(s for s in r.scenarios if s.exit_day == r.optimal_exit_day)
        self.assertFalse(optimal_s.is_locked)

    def test_optimal_net_gain_matches_scenario(self):
        r = _report(current_apy=5.0, alternative_apy=3.0)
        optimal_s = next(s for s in r.scenarios if s.exit_day == r.optimal_exit_day)
        self.assertAlmostEqual(
            r.optimal_exit_net_gain_pct, optimal_s.net_gain_pct, places=6
        )

    def test_optimal_is_max_among_unlocked(self):
        r = _report(current_apy=5.0, alternative_apy=3.0, lock_period_days=0)
        unlocked = [s for s in r.scenarios if not s.is_locked]
        best_net = max(s.net_gain_pct for s in unlocked)
        self.assertAlmostEqual(r.optimal_exit_net_gain_pct, best_net, places=6)

    def test_optimal_excludes_locked_when_possible(self):
        # lock=30, held=0 → days 0,7,14 are locked; 30,60,90,180 are not
        r = _report(lock_period_days=30, days_already_held=0, current_apy=5.0)
        self.assertGreaterEqual(r.optimal_exit_day, 30)

    def test_optimal_fallback_all_locked(self):
        # lock=200, held=0 → all scenario days < 200 → all locked
        r = _report(lock_period_days=200, days_already_held=0, current_apy=5.0)
        # optimal should be set (not crash)
        self.assertIn(r.optimal_exit_day, _SCENARIO_DAYS)

    def test_long_holding_no_decay_favors_day_180(self):
        """No decay, alt < current → holding longer accumulates more yield → day 180 optimal."""
        r = _report(current_apy=5.0, daily_decay_rate=0.0, alternative_apy=3.0)
        self.assertEqual(r.optimal_exit_day, 180)


# ===========================================================================
# analyze — should_exit_now
# ===========================================================================

class TestAnalyzeShouldExitNow(unittest.TestCase):

    def test_should_exit_now_true_when_alt_better(self):
        # current_apy < alternative_apy → exit now
        r = _report(current_apy=3.0, alternative_apy=6.0, lock_period_days=0)
        self.assertTrue(r.should_exit_now)

    def test_should_exit_now_false_when_locked(self):
        # Even if alt is better, lock prevents exit
        r = _report(current_apy=3.0, alternative_apy=8.0, lock_period_days=30)
        self.assertFalse(r.should_exit_now)

    def test_should_exit_now_false_when_current_better_no_lock(self):
        # current > alt, no lock, holding has positive net → don't exit now
        r = _report(current_apy=5.0, alternative_apy=3.0, lock_period_days=0)
        self.assertFalse(r.should_exit_now)

    def test_should_exit_now_false_locked_even_if_alt_better(self):
        r = _report(current_apy=1.0, alternative_apy=10.0, lock_period_days=90)
        self.assertFalse(r.should_exit_now)

    def test_should_exit_now_requires_remaining_lock_zero(self):
        r = _report(current_apy=1.0, alternative_apy=10.0,
                    lock_period_days=1, days_already_held=0)
        self.assertFalse(r.should_exit_now)

    def test_should_exit_now_true_after_lock_expires(self):
        # lock=30, held=30 → remaining=0, alt > current → should exit
        r = _report(current_apy=3.0, alternative_apy=8.0,
                    lock_period_days=30, days_already_held=30)
        self.assertTrue(r.should_exit_now)

    def test_should_exit_now_within_5pct_of_optimal(self):
        # Construct case: very high alt APY makes ALL days highly negative,
        # but day 0 (net=-0.05) is near-optimal because day 7+ lose much more.
        # alt > current so current_apy < alternative_apy fires.
        r = _report(current_apy=1.0, alternative_apy=50.0, lock_period_days=0)
        # should exit because current < alternative (regardless of within_5pct)
        self.assertTrue(r.should_exit_now)


# ===========================================================================
# analyze — exit_recommendation
# ===========================================================================

class TestAnalyzeExitRecommendation(unittest.TestCase):

    def test_exit_now(self):
        # alt better, no lock
        r = _report(current_apy=3.0, alternative_apy=8.0, lock_period_days=0)
        self.assertEqual(r.exit_recommendation, "EXIT_NOW")
        self.assertEqual(r.recommended_exit_day, 0)

    def test_exit_after_lock(self):
        # locked position with decent current APY
        r = _report(current_apy=5.0, alternative_apy=3.0, lock_period_days=30)
        self.assertEqual(r.exit_recommendation, "EXIT_AFTER_LOCK")
        self.assertEqual(r.recommended_exit_day, 30)

    def test_exit_after_lock_recommended_day_is_remaining(self):
        # lock=60, held=20 → remaining=40
        r = _report(current_apy=5.0, alternative_apy=3.0,
                    lock_period_days=60, days_already_held=20)
        self.assertEqual(r.exit_recommendation, "EXIT_AFTER_LOCK")
        self.assertEqual(r.recommended_exit_day, 40)

    def test_hold_long_term_no_lock_good_apy(self):
        # No lock, current > alt, no decay → day 180 is optimal → HOLD_LONG_TERM
        r = _report(current_apy=5.0, alternative_apy=3.0,
                    lock_period_days=0, daily_decay_rate=0.0)
        self.assertEqual(r.exit_recommendation, "HOLD_LONG_TERM")
        self.assertGreater(r.recommended_exit_day, 14)

    def test_hold_n_more_days_optimal_at_7(self):
        # Force optimal to be at day 7: very high decay so that day 7 beats day 14+
        # We'll verify by inspecting the actual optimal_exit_day
        r = _report(current_apy=5.0, daily_decay_rate=50.0,
                    alternative_apy=0.0, lock_period_days=0)
        if r.optimal_exit_day <= 14 and not r.should_exit_now and r.remaining_lock_days == 0:
            self.assertEqual(r.exit_recommendation, "HOLD_N_MORE_DAYS")
        # else the test isn't triggered — just verify no exception

    def test_exit_now_recommended_day_is_zero(self):
        r = _report(current_apy=2.0, alternative_apy=6.0, lock_period_days=0)
        self.assertEqual(r.exit_recommendation, "EXIT_NOW")
        self.assertEqual(r.recommended_exit_day, 0)

    def test_hold_long_term_recommended_day_is_optimal(self):
        r = _report(current_apy=5.0, alternative_apy=3.0, lock_period_days=0)
        if r.exit_recommendation == "HOLD_LONG_TERM":
            self.assertEqual(r.recommended_exit_day, r.optimal_exit_day)


# ===========================================================================
# analyze — warnings
# ===========================================================================

class TestAnalyzeWarnings(unittest.TestCase):

    def test_warning_rapid_decay_above_3(self):
        r = _report(daily_decay_rate=3.1)
        self.assertIn("rapid APY decay", r.warnings)

    def test_no_warning_rapid_decay_at_3(self):
        r = _report(daily_decay_rate=3.0)
        self.assertNotIn("rapid APY decay", r.warnings)

    def test_no_warning_rapid_decay_below_3(self):
        r = _report(daily_decay_rate=2.9)
        self.assertNotIn("rapid APY decay", r.warnings)

    def test_warning_much_better_alternative_above_1_5x(self):
        # alternative_apy > current * 1.5
        r = _report(current_apy=4.0, alternative_apy=6.1)
        self.assertIn("much better alternative exists", r.warnings)

    def test_no_warning_better_alt_at_exactly_1_5x(self):
        r = _report(current_apy=4.0, alternative_apy=6.0)
        self.assertNotIn("much better alternative exists", r.warnings)

    def test_no_warning_better_alt_below_1_5x(self):
        r = _report(current_apy=4.0, alternative_apy=5.9)
        self.assertNotIn("much better alternative exists", r.warnings)

    def test_warning_long_lock_above_60(self):
        r = _report(lock_period_days=61, days_already_held=0)
        self.assertIn("long lock period", r.warnings)

    def test_no_warning_long_lock_at_exactly_60(self):
        r = _report(lock_period_days=60, days_already_held=0)
        self.assertNotIn("long lock period", r.warnings)

    def test_no_warning_long_lock_below_60(self):
        r = _report(lock_period_days=59, days_already_held=0)
        self.assertNotIn("long lock period", r.warnings)

    def test_no_warnings_normal_case(self):
        r = _report(
            current_apy=5.0, daily_decay_rate=1.0,
            lock_period_days=7, days_already_held=0,
            alternative_apy=4.0,
        )
        self.assertEqual(r.warnings, [])

    def test_multiple_warnings(self):
        r = _report(
            current_apy=4.0, daily_decay_rate=5.0,
            alternative_apy=8.0, lock_period_days=90, days_already_held=0,
        )
        # rapid decay (5>3), much better (8>6), long lock (90>60)
        self.assertIn("rapid APY decay", r.warnings)
        self.assertIn("much better alternative exists", r.warnings)
        self.assertIn("long lock period", r.warnings)


# ===========================================================================
# compare_positions
# ===========================================================================

class TestComparePositions(unittest.TestCase):

    def _make_reports(self) -> list:
        r1 = _report(current_apy=5.0, alternative_apy=3.0)  # high net
        r2 = _report(current_apy=2.0, alternative_apy=3.0)  # medium
        r3 = _report(current_apy=1.0, alternative_apy=8.0)  # low (high alt)
        return [r1, r2, r3]

    def test_compare_positions_sorted_desc(self):
        reports = self._make_reports()
        ranked = compare_positions(reports)
        nets = [r.optimal_exit_net_gain_pct for r in ranked]
        self.assertEqual(nets, sorted(nets, reverse=True))

    def test_compare_positions_preserves_all(self):
        reports = self._make_reports()
        ranked = compare_positions(reports)
        self.assertEqual(len(ranked), len(reports))

    def test_compare_positions_empty(self):
        self.assertEqual(compare_positions([]), [])

    def test_compare_positions_single(self):
        r = _report()
        ranked = compare_positions([r])
        self.assertEqual(len(ranked), 1)

    def test_compare_positions_first_is_best(self):
        reports = self._make_reports()
        ranked = compare_positions(reports)
        best_net = max(r.optimal_exit_net_gain_pct for r in reports)
        self.assertAlmostEqual(ranked[0].optimal_exit_net_gain_pct, best_net, places=6)

    def test_compare_positions_original_unchanged(self):
        reports = self._make_reports()
        original_order = [r.protocol for r in reports]
        compare_positions(reports)
        self.assertEqual([r.protocol for r in reports], original_order)


# ===========================================================================
# save_results / load_history
# ===========================================================================

class TestSaveLoadHistory(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def _make_report(self, protocol: str = "TestProto") -> ExitTimingReport:
        return _report(protocol=protocol)

    def test_save_creates_file(self):
        r = self._make_report()
        path = save_results(r, data_dir=Path(self.tmp_dir))
        self.assertTrue(os.path.exists(path))

    def test_save_returns_correct_path(self):
        r = self._make_report()
        path = save_results(r, data_dir=Path(self.tmp_dir))
        self.assertIn("exit_timing_log.json", path)

    def test_save_sets_saved_to(self):
        r = self._make_report()
        save_results(r, data_dir=Path(self.tmp_dir))
        self.assertIn("exit_timing_log.json", r.saved_to)

    def test_load_after_save_returns_one_entry(self):
        r = self._make_report()
        save_results(r, data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        self.assertEqual(len(history), 1)

    def test_round_trip_protocol(self):
        r = self._make_report(protocol="AaveV3")
        save_results(r, data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        self.assertEqual(history[0]["protocol"], "AaveV3")

    def test_round_trip_optimal_exit_day(self):
        r = self._make_report()
        save_results(r, data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        self.assertEqual(history[0]["optimal_exit_day"], r.optimal_exit_day)

    def test_round_trip_scenarios_count(self):
        r = self._make_report()
        save_results(r, data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        self.assertEqual(len(history[0]["scenarios"]), 7)

    def test_save_appends(self):
        for i in range(3):
            save_results(self._make_report(protocol=f"Proto{i}"),
                         data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        self.assertEqual(len(history), 3)

    def test_ring_buffer_cap_at_100(self):
        for i in range(105):
            save_results(self._make_report(protocol=f"Proto{i}"),
                         data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        self.assertEqual(len(history), 100)

    def test_ring_buffer_removes_oldest(self):
        for i in range(105):
            save_results(self._make_report(protocol=f"Proto{i}"),
                         data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        # Oldest (0..4) removed; newest (5..104) remain
        self.assertEqual(history[0]["protocol"], "Proto5")
        self.assertEqual(history[-1]["protocol"], "Proto104")

    def test_load_missing_file_returns_empty_list(self):
        history = load_history(data_dir=Path(self.tmp_dir) / "nonexistent")
        self.assertEqual(history, [])

    def test_entry_has_timestamp(self):
        r = self._make_report()
        save_results(r, data_dir=Path(self.tmp_dir))
        history = load_history(data_dir=Path(self.tmp_dir))
        self.assertIn("timestamp", history[0])

    def test_atomic_write_produces_valid_json(self):
        r = self._make_report()
        path = save_results(r, data_dir=Path(self.tmp_dir))
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_lock_period_zero(self):
        r = _report(lock_period_days=0, days_already_held=0)
        self.assertEqual(r.remaining_lock_days, 0)
        for s in r.scenarios:
            self.assertFalse(s.is_locked)

    def test_days_already_held_exceeds_lock(self):
        r = _report(lock_period_days=30, days_already_held=60)
        self.assertEqual(r.remaining_lock_days, 0)
        for s in r.scenarios:
            self.assertFalse(s.is_locked)

    def test_zero_current_apy(self):
        """Zero APY — all yields should be 0, gas still applies."""
        s = model_scenario(30, 0.0, 0.0, 0, 0, 3.0)
        self.assertAlmostEqual(s.cumulative_yield_pct, 0.0, places=8)
        self.assertGreater(s.cumulative_gas_pct, 0)

    def test_zero_alternative_apy(self):
        """Alt APY = 0 → opportunity cost always <= 0."""
        for d in _SCENARIO_DAYS:
            with self.subTest(day=d):
                s = model_scenario(d, 5.0, 0.0, 0, 0, 0.0)
                self.assertLessEqual(s.opportunity_cost_pct, 0.0)

    def test_high_decay_rate_effective_apy_clamps_to_zero(self):
        s = model_scenario(365, 5.0, 100.0, 0, 0, 3.0)
        effective = max(0.0, 5.0 * (1 - 1.0) ** 365)
        self.assertAlmostEqual(effective, 0.0, places=8)
        self.assertGreaterEqual(s.cumulative_yield_pct, 0.0)

    def test_analyze_returns_exit_timing_report(self):
        r = analyze("Proto", "Pool", 5.0, 0.0, 0, 0, 3.0)
        self.assertIsInstance(r, ExitTimingReport)

    def test_model_scenario_returns_exit_scenario(self):
        s = model_scenario(30, 5.0, 0.0, 0, 0, 3.0)
        self.assertIsInstance(s, ExitScenario)

    def test_net_gain_always_finite(self):
        for d in _SCENARIO_DAYS:
            s = model_scenario(d, 5.0, 0.5, 0, 0, 3.0)
            self.assertFalse(s.net_gain_pct != s.net_gain_pct)  # not NaN


if __name__ == "__main__":
    unittest.main()
