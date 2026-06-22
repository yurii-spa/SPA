"""
Tests for MP-709 PositionAgeOptimizer (spa_core/analytics/position_age_optimizer.py)
≥ 65 unit tests — stdlib unittest only, no external deps.
"""
from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.position_age_optimizer import (
    AgeAnalysis,
    RING_BUFFER_CAP,
    analyze,
    batch_analyze,
    find_rebalance_candidates,
    load_history,
    save_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def simple(
    age: int,
    apy: float = 10.0,
    entry: float = 0.5,
    exit_: float = 0.5,
    alt_apy: float = 0.0,
) -> AgeAnalysis:
    """Convenience wrapper: total_cost=1%, breakeven≈36.5 days at apy=10."""
    return analyze("aave", "USDC", entry, exit_, apy, age, alt_apy)


# ---------------------------------------------------------------------------
# 1. breakeven_days
# ---------------------------------------------------------------------------

class TestBreakevenDays(unittest.TestCase):

    def test_formula_apy10_total_cost_1pct(self):
        """Spec example: apy=10, total cost=1% → 36.5 days."""
        result = simple(age=0, apy=10.0, entry=0.5, exit_=0.5)
        self.assertAlmostEqual(result.breakeven_days, 36.5, places=4)

    def test_zero_apy_gives_zero_breakeven(self):
        result = simple(age=0, apy=0.0, entry=0.5, exit_=0.5)
        self.assertEqual(result.breakeven_days, 0.0)

    def test_higher_cost_longer_breakeven(self):
        low_cost  = simple(age=0, apy=10.0, entry=0.5, exit_=0.5)
        high_cost = simple(age=0, apy=10.0, entry=1.0, exit_=1.0)
        self.assertLess(low_cost.breakeven_days, high_cost.breakeven_days)

    def test_higher_apy_shorter_breakeven(self):
        low_apy  = simple(age=0, apy=5.0)
        high_apy = simple(age=0, apy=20.0)
        self.assertGreater(low_apy.breakeven_days, high_apy.breakeven_days)

    def test_breakeven_exact_formula(self):
        result = analyze("x", "y", 1.0, 0.5, 15.0, 0)
        expected = 1.5 / (15.0 / 365)
        self.assertAlmostEqual(result.breakeven_days, expected, places=5)

    def test_breakeven_zero_costs(self):
        result = analyze("x", "y", 0.0, 0.0, 10.0, 30)
        self.assertEqual(result.breakeven_days, 0.0)


# ---------------------------------------------------------------------------
# 2. net_return_pct
# ---------------------------------------------------------------------------

class TestNetReturnPct(unittest.TestCase):

    def test_negative_at_age_zero(self):
        result = simple(age=0, apy=10.0, entry=0.5, exit_=0.5)
        # Net = 0 - 1.0 = -1.0
        self.assertAlmostEqual(result.net_return_pct, -1.0, places=5)

    def test_zero_at_breakeven(self):
        # age = breakeven_days = 36.5 → net_return ≈ 0
        result = analyze("a", "b", 0.5, 0.5, 10.0, 365, 0.0)
        # net = (10/365 * 365) - 1.0 = 10 - 1 = 9.0 at age 365
        # Let's pick age = 36 (just before breakeven)
        result = analyze("a", "b", 0.5, 0.5, 10.0, 36, 0.0)
        self.assertLess(result.net_return_pct, 0.0)

    def test_positive_after_breakeven(self):
        result = simple(age=100, apy=10.0)
        # net = (10/365 * 100) - 1.0 ≈ 2.74 - 1.0 = 1.74
        self.assertGreater(result.net_return_pct, 0.0)

    def test_formula_explicit(self):
        result = analyze("a", "b", 0.5, 0.5, 10.0, 100, 0.0)
        expected = (10.0 / 365 * 100) - 0.5 - 0.5
        self.assertAlmostEqual(result.net_return_pct, expected, places=5)

    def test_zero_apy_net_return_is_negative(self):
        result = analyze("a", "b", 0.5, 0.5, 0.0, 100, 0.0)
        self.assertAlmostEqual(result.net_return_pct, -1.0, places=5)

    def test_zero_costs_net_return_is_gross_yield(self):
        result = analyze("a", "b", 0.0, 0.0, 10.0, 365, 0.0)
        self.assertAlmostEqual(result.net_return_pct, 10.0, places=5)

    def test_net_return_includes_entry_cost(self):
        r_with = analyze("a", "b", 1.0, 0.0, 10.0, 50, 0.0)
        r_without = analyze("a", "b", 0.0, 0.0, 10.0, 50, 0.0)
        self.assertLess(r_with.net_return_pct, r_without.net_return_pct)

    def test_net_return_includes_exit_cost(self):
        r_with = analyze("a", "b", 0.0, 1.0, 10.0, 50, 0.0)
        r_without = analyze("a", "b", 0.0, 0.0, 10.0, 50, 0.0)
        self.assertLess(r_with.net_return_pct, r_without.net_return_pct)


# ---------------------------------------------------------------------------
# 3. days_past_breakeven
# ---------------------------------------------------------------------------

class TestDaysPastBreakeven(unittest.TestCase):

    def test_never_negative(self):
        result = simple(age=0)
        self.assertGreaterEqual(result.days_past_breakeven, 0)

    def test_zero_before_breakeven(self):
        result = simple(age=10)   # breakeven ≈ 36.5
        self.assertEqual(result.days_past_breakeven, 0)

    def test_positive_after_breakeven(self):
        result = simple(age=100)  # breakeven ≈ 36.5
        self.assertGreater(result.days_past_breakeven, 0)

    def test_value_at_age_100_breakeven_36(self):
        result = simple(age=100)
        # days_past = max(0, int(100 - 36.5)) = int(63.5) = 63
        self.assertEqual(result.days_past_breakeven, 63)


# ---------------------------------------------------------------------------
# 4. optimal_hold_days
# ---------------------------------------------------------------------------

class TestOptimalHoldDays(unittest.TestCase):

    def test_equals_3x_breakeven(self):
        result = simple(age=0, apy=10.0)
        self.assertAlmostEqual(result.optimal_hold_days, result.breakeven_days * 3, places=5)

    def test_zero_apy_gives_zero_optimal(self):
        result = simple(age=0, apy=0.0)
        self.assertEqual(result.optimal_hold_days, 0.0)

    def test_proportional_to_costs(self):
        r1 = analyze("a", "b", 1.0, 0.0, 10.0, 0)
        r2 = analyze("a", "b", 2.0, 0.0, 10.0, 0)
        self.assertAlmostEqual(r2.optimal_hold_days, r1.optimal_hold_days * 2, places=5)


# ---------------------------------------------------------------------------
# 5. maturity_label (breakeven ≈ 36.5 days with entry=exit=0.5, apy=10)
# ---------------------------------------------------------------------------

class TestMaturityLabel(unittest.TestCase):

    def test_too_early_age_10(self):
        self.assertEqual(simple(age=10).maturity_label, "TOO_EARLY")

    def test_too_early_age_0(self):
        self.assertEqual(simple(age=0).maturity_label, "TOO_EARLY")

    def test_maturing_age_50(self):
        # 36.5 <= 50 < 2*36.5=73
        self.assertEqual(simple(age=50).maturity_label, "MATURING")

    def test_maturing_age_60(self):
        self.assertEqual(simple(age=60).maturity_label, "MATURING")

    def test_optimal_age_90(self):
        # 73 <= 90 < 4*36.5=146
        self.assertEqual(simple(age=90).maturity_label, "OPTIMAL")

    def test_optimal_age_120(self):
        self.assertEqual(simple(age=120).maturity_label, "OPTIMAL")

    def test_diminishing_age_200(self):
        self.assertEqual(simple(age=200).maturity_label, "DIMINISHING")

    def test_diminishing_age_500(self):
        self.assertEqual(simple(age=500).maturity_label, "DIMINISHING")

    def test_boundary_at_breakeven_is_maturing(self):
        # age == 37 > 36.5 → MATURING (age < 2*36.5=73)
        self.assertEqual(simple(age=37).maturity_label, "MATURING")

    def test_maturity_with_zero_apy_is_diminishing(self):
        # breakeven=0, all ages → DIMINISHING (age >= 4*0=0)
        result = analyze("a", "b", 0.5, 0.5, 0.0, 10)
        self.assertEqual(result.maturity_label, "DIMINISHING")


# ---------------------------------------------------------------------------
# 6. action
# ---------------------------------------------------------------------------

class TestAction(unittest.TestCase):

    def test_too_early_action(self):
        self.assertEqual(simple(age=10).action, "HOLD_TO_BREAKEVEN")

    def test_maturing_action(self):
        self.assertEqual(simple(age=50).action, "CONTINUE_HOLD")

    def test_optimal_action(self):
        self.assertEqual(simple(age=90).action, "CONSIDER_REBALANCE")

    def test_diminishing_action(self):
        self.assertEqual(simple(age=200).action, "REBALANCE_NOW")

    def test_action_consistent_with_maturity(self):
        for age, expected_action in [
            (10, "HOLD_TO_BREAKEVEN"),
            (50, "CONTINUE_HOLD"),
            (90, "CONSIDER_REBALANCE"),
            (200, "REBALANCE_NOW"),
        ]:
            with self.subTest(age=age):
                result = simple(age=age)
                self.assertEqual(result.action, expected_action)


# ---------------------------------------------------------------------------
# 7. next_review_days
# ---------------------------------------------------------------------------

class TestNextReviewDays(unittest.TestCase):

    def test_too_early_is_remaining_to_breakeven(self):
        # breakeven=36.5, age=10 → ceil(26.5) = 27
        result = simple(age=10)
        self.assertEqual(result.next_review_days, 27)

    def test_too_early_age_0(self):
        # breakeven=36.5, age=0 → ceil(36.5) = 37
        result = simple(age=0)
        self.assertEqual(result.next_review_days, 37)

    def test_maturing_is_30(self):
        self.assertEqual(simple(age=50).next_review_days, 30)

    def test_optimal_is_7(self):
        self.assertEqual(simple(age=90).next_review_days, 7)

    def test_diminishing_is_7(self):
        self.assertEqual(simple(age=200).next_review_days, 7)

    def test_too_early_uses_ceil(self):
        # age=20, breakeven=36.5 → remaining=16.5 → ceil=17
        result = simple(age=20)
        self.assertEqual(result.next_review_days, 17)


# ---------------------------------------------------------------------------
# 8. opportunity_cost_pct
# ---------------------------------------------------------------------------

class TestOpportunityCost(unittest.TestCase):

    def test_positive_when_alt_higher(self):
        result = analyze("a", "b", 0.5, 0.5, 10.0, 50, 15.0)
        self.assertGreater(result.opportunity_cost_pct, 0.0)

    def test_zero_when_alt_lower(self):
        result = analyze("a", "b", 0.5, 0.5, 10.0, 50, 5.0)
        self.assertEqual(result.opportunity_cost_pct, 0.0)

    def test_zero_when_alt_equal(self):
        result = analyze("a", "b", 0.5, 0.5, 10.0, 50, 10.0)
        self.assertEqual(result.opportunity_cost_pct, 0.0)

    def test_formula_explicit(self):
        result = analyze("a", "b", 0.5, 0.5, 10.0, 90, 15.0)
        # OPTIMAL → next_review=7
        expected = (15.0 - 10.0) / 365.0 * 7
        self.assertAlmostEqual(result.opportunity_cost_pct, expected, places=5)

    def test_uses_next_review_days(self):
        r_maturing  = analyze("a", "b", 0.5, 0.5, 10.0, 50,  15.0)  # review=30
        r_optimal   = analyze("a", "b", 0.5, 0.5, 10.0, 90,  15.0)  # review=7
        self.assertGreater(r_maturing.opportunity_cost_pct, r_optimal.opportunity_cost_pct)

    def test_non_negative(self):
        for alt in [0.0, 5.0, 10.0, 20.0]:
            with self.subTest(alt=alt):
                result = analyze("a", "b", 0.5, 0.5, 10.0, 50, alt)
                self.assertGreaterEqual(result.opportunity_cost_pct, 0.0)


# ---------------------------------------------------------------------------
# 9. hold_efficiency
# ---------------------------------------------------------------------------

class TestHoldEfficiency(unittest.TestCase):

    def test_at_breakeven_is_zero(self):
        # age = 37 (just past breakeven 36.5) → net ≈ 0+ → efficiency ≈ 0
        result = simple(age=37)
        # net_return = (10/365*37) - 1.0 ≈ 0.0137
        self.assertGreaterEqual(result.hold_efficiency, 0.0)

    def test_negative_before_breakeven(self):
        result = simple(age=10)
        self.assertLess(result.hold_efficiency, 0.0)

    def test_positive_after_breakeven(self):
        result = simple(age=100)
        self.assertGreater(result.hold_efficiency, 0.0)

    def test_zero_apy_denominator_guard(self):
        result = analyze("a", "b", 0.5, 0.5, 0.0, 10)
        # Should not raise; denominator = max(0.001, 0) = 0.001
        self.assertIsInstance(result.hold_efficiency, float)

    def test_perfect_efficiency_near_2x_breakeven(self):
        # At 2×breakeven: net = breakeven*daily_apy, efficiency ≈ 1.0
        breakeven = 36.5
        age = round(2 * breakeven)   # 73
        result = simple(age=age)
        self.assertAlmostEqual(result.hold_efficiency, 1.0, delta=0.05)


# ---------------------------------------------------------------------------
# 10. batch_analyze
# ---------------------------------------------------------------------------

class TestBatchAnalyze(unittest.TestCase):

    def _positions(self):
        return [
            {"protocol": "aave",   "pool": "USDC", "entry_cost_pct": 0.5, "exit_cost_pct": 0.5,
             "current_apy": 10.0, "position_age_days": 100},
            {"protocol": "morpho", "pool": "USDC", "entry_cost_pct": 0.5, "exit_cost_pct": 0.5,
             "current_apy": 10.0, "position_age_days": 10},
            {"protocol": "comp",   "pool": "USDC", "entry_cost_pct": 0.5, "exit_cost_pct": 0.5,
             "current_apy": 10.0, "position_age_days": 50},
        ]

    def test_returns_list(self):
        result = batch_analyze(self._positions())
        self.assertIsInstance(result, list)

    def test_sorted_by_net_return_desc(self):
        result = batch_analyze(self._positions())
        nets = [r.net_return_pct for r in result]
        self.assertEqual(nets, sorted(nets, reverse=True))

    def test_empty_input_returns_empty(self):
        self.assertEqual(batch_analyze([]), [])

    def test_single_position(self):
        positions = [{"protocol": "a", "pool": "b", "entry_cost_pct": 0.5,
                      "exit_cost_pct": 0.5, "current_apy": 10.0, "position_age_days": 50}]
        result = batch_analyze(positions)
        self.assertEqual(len(result), 1)

    def test_uses_best_alternative_apy(self):
        positions = [{"protocol": "a", "pool": "b", "entry_cost_pct": 0.5,
                      "exit_cost_pct": 0.5, "current_apy": 10.0,
                      "position_age_days": 90, "best_alternative_apy": 15.0}]
        result = batch_analyze(positions)
        self.assertGreater(result[0].opportunity_cost_pct, 0.0)


# ---------------------------------------------------------------------------
# 11. find_rebalance_candidates
# ---------------------------------------------------------------------------

class TestFindRebalanceCandidates(unittest.TestCase):

    def test_filters_consider_rebalance(self):
        result = simple(age=90)   # OPTIMAL → CONSIDER_REBALANCE
        self.assertEqual(result.action, "CONSIDER_REBALANCE")
        candidates = find_rebalance_candidates([result])
        self.assertEqual(len(candidates), 1)

    def test_filters_rebalance_now(self):
        result = simple(age=200)  # DIMINISHING → REBALANCE_NOW
        candidates = find_rebalance_candidates([result])
        self.assertEqual(len(candidates), 1)

    def test_excludes_hold(self):
        result = simple(age=10)   # TOO_EARLY → HOLD_TO_BREAKEVEN
        candidates = find_rebalance_candidates([result])
        self.assertEqual(len(candidates), 0)

    def test_excludes_continue_hold(self):
        result = simple(age=50)   # MATURING → CONTINUE_HOLD
        candidates = find_rebalance_candidates([result])
        self.assertEqual(len(candidates), 0)

    def test_empty_input_returns_empty(self):
        self.assertEqual(find_rebalance_candidates([]), [])

    def test_mixed_returns_only_candidates(self):
        r_hold    = simple(age=10)
        r_mature  = simple(age=50)
        r_optimal = simple(age=90)
        r_dim     = simple(age=200)
        candidates = find_rebalance_candidates([r_hold, r_mature, r_optimal, r_dim])
        self.assertEqual(len(candidates), 2)
        for c in candidates:
            self.assertIn(c.action, ("CONSIDER_REBALANCE", "REBALANCE_NOW"))


# ---------------------------------------------------------------------------
# 12. save / load / ring-buffer
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.data_file = Path(self._tmpdir.name) / "position_age_log.json"
        self.data_file.write_text("[]")

    def tearDown(self):
        self._tmpdir.cleanup()

    def _analysis(self, pool: str = "USDC") -> AgeAnalysis:
        return analyze("aave", pool, 0.5, 0.5, 10.0, 50)

    def test_save_increments_history(self):
        save_results(self._analysis(), self.data_file)
        self.assertEqual(len(load_history(self.data_file)), 1)

    def test_save_sets_saved_to(self):
        a = self._analysis()
        save_results(a, self.data_file)
        self.assertEqual(a.saved_to, str(self.data_file))

    def test_load_round_trip_protocol(self):
        save_results(self._analysis(), self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(history[0]["protocol"], "aave")

    def test_load_round_trip_pool(self):
        save_results(self._analysis("DAI"), self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(history[0]["pool"], "DAI")

    def test_load_round_trip_maturity(self):
        save_results(self._analysis(), self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(history[0]["maturity_label"], "MATURING")

    def test_load_empty_file(self):
        self.assertEqual(load_history(self.data_file), [])

    def test_load_missing_file(self):
        missing = Path(self._tmpdir.name) / "no_file.json"
        self.assertEqual(load_history(missing), [])

    def test_load_corrupted_file(self):
        self.data_file.write_text("{bad json}")
        self.assertEqual(load_history(self.data_file), [])

    def test_ring_buffer_cap_100(self):
        for i in range(110):
            a = analyze("p", f"pool_{i}", 0.5, 0.5, 10.0, 50)
            save_results(a, self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), RING_BUFFER_CAP)

    def test_ring_buffer_keeps_newest(self):
        for i in range(110):
            a = analyze("p", f"pool_{i}", 0.5, 0.5, 10.0, 50)
            save_results(a, self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(history[-1]["pool"], "pool_109")

    def test_multiple_saves_accumulate(self):
        for i in range(5):
            save_results(self._analysis(f"pool_{i}"), self.data_file)
        self.assertEqual(len(load_history(self.data_file)), 5)

    def test_save_returns_analysis(self):
        a = self._analysis()
        returned = save_results(a, self.data_file)
        self.assertIs(returned, a)


# ---------------------------------------------------------------------------
# 13. edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_apy_zero_no_division_error(self):
        result = analyze("a", "b", 0.5, 0.5, 0.0, 10)
        self.assertEqual(result.breakeven_days, 0.0)

    def test_entry_exit_zero_breakeven_zero(self):
        result = analyze("a", "b", 0.0, 0.0, 10.0, 30)
        self.assertEqual(result.breakeven_days, 0.0)

    def test_entry_exit_zero_net_return_positive(self):
        result = analyze("a", "b", 0.0, 0.0, 10.0, 100)
        self.assertGreater(result.net_return_pct, 0.0)

    def test_age_zero_net_return_is_negative_cost(self):
        result = analyze("a", "b", 0.5, 0.5, 10.0, 0)
        self.assertAlmostEqual(result.net_return_pct, -1.0, places=5)

    def test_large_age_diminishing(self):
        result = analyze("a", "b", 0.5, 0.5, 10.0, 1000)
        self.assertEqual(result.maturity_label, "DIMINISHING")
        self.assertEqual(result.action, "REBALANCE_NOW")

    def test_only_entry_cost(self):
        result = analyze("a", "b", 1.0, 0.0, 10.0, 100)
        self.assertIsInstance(result.breakeven_days, float)

    def test_only_exit_cost(self):
        result = analyze("a", "b", 0.0, 1.0, 10.0, 100)
        self.assertIsInstance(result.breakeven_days, float)

    def test_analysis_fields_present(self):
        result = simple(age=50)
        for field in [
            "protocol", "pool", "breakeven_days", "net_return_pct",
            "maturity_label", "action", "next_review_days",
            "opportunity_cost_pct", "hold_efficiency",
        ]:
            self.assertTrue(hasattr(result, field), f"Missing field: {field}")


if __name__ == "__main__":
    unittest.main()
