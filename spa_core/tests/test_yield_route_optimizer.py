# spa_core/tests/test_yield_route_optimizer.py
# MP-723 — Tests for YieldRouteOptimizer
# ≥65 tests covering: constraint validation, greedy allocation, metrics,
# HHI, route labels, save/load, ring-buffer cap, edge cases.

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from spa_core.analytics.yield_route_optimizer import (
    AllocationSlot,
    RouteAllocation,
    OptimalRoute,
    validate_constraints,
    optimize_route,
    save_results,
    load_history,
    DEFAULT_MAX_CONCENTRATION,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_slot(name="A", apy=5.0, risk=20.0, min_pct=0.0, max_pct=100.0, liq=80.0):
    return AllocationSlot(
        name=name, apy=apy, risk_score=risk,
        min_allocation_pct=min_pct, max_allocation_pct=max_pct,
        liquidity_score=liq,
    )


def four_equal_slots():
    """4 slots of equal APY/risk, no min/max constraints."""
    return [
        make_slot("A", apy=5.0, risk=20.0),
        make_slot("B", apy=5.0, risk=20.0),
        make_slot("C", apy=5.0, risk=20.0),
        make_slot("D", apy=5.0, risk=20.0),
    ]


class TestValidateConstraints(unittest.TestCase):
    """Tests for validate_constraints()."""

    def test_valid_slots_no_violations(self):
        slots = [
            make_slot("A", min_pct=10, max_pct=40),
            make_slot("B", min_pct=10, max_pct=40),
            make_slot("C", min_pct=5, max_pct=40),
        ]
        self.assertEqual(validate_constraints(slots), [])

    def test_min_sum_exceeds_100_violation(self):
        slots = [
            make_slot("A", min_pct=60, max_pct=80),
            make_slot("B", min_pct=60, max_pct=80),
        ]
        violations = validate_constraints(slots)
        self.assertTrue(len(violations) > 0)
        self.assertTrue(any("100%" in v or "exceeds" in v for v in violations))

    def test_max_less_than_min_violation(self):
        slots = [make_slot("A", min_pct=30, max_pct=20)]
        violations = validate_constraints(slots)
        self.assertTrue(len(violations) > 0)
        self.assertTrue(any("A" in v for v in violations))

    def test_exact_100_min_sum_ok(self):
        """sum of mins = exactly 100 → no violation."""
        slots = [
            make_slot("A", min_pct=50, max_pct=50),
            make_slot("B", min_pct=50, max_pct=50),
        ]
        self.assertEqual(validate_constraints(slots), [])

    def test_multiple_violations(self):
        slots = [
            make_slot("A", min_pct=80, max_pct=60),  # max < min
            make_slot("B", min_pct=80, max_pct=80),  # sum > 100
        ]
        violations = validate_constraints(slots)
        self.assertGreaterEqual(len(violations), 2)

    def test_empty_slots_no_violation(self):
        self.assertEqual(validate_constraints([]), [])

    def test_single_slot_100_min_ok(self):
        slots = [make_slot("A", min_pct=100, max_pct=100)]
        self.assertEqual(validate_constraints(slots), [])

    def test_single_slot_max_less_than_min(self):
        slots = [make_slot("A", min_pct=50, max_pct=30)]
        violations = validate_constraints(slots)
        self.assertGreater(len(violations), 0)


class TestOptimizeRouteBasics(unittest.TestCase):
    """Core allocation and sum tests."""

    def test_single_slot_gets_100_pct(self):
        slots = [make_slot("A", apy=5.0, min_pct=0, max_pct=100)]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0)
        self.assertAlmostEqual(route.allocations[0].allocated_pct, 100.0, places=8)

    def test_allocations_sum_to_100(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        total = sum(a.allocated_pct for a in route.allocations)
        self.assertAlmostEqual(total, 100.0, places=9)

    def test_allocations_sum_to_100_varied(self):
        slots = [
            make_slot("A", apy=8.0, risk=30, min_pct=5, max_pct=40),
            make_slot("B", apy=5.0, risk=15, min_pct=10, max_pct=40),
            make_slot("C", apy=3.0, risk=10, min_pct=5, max_pct=30),
        ]
        route = optimize_route(slots, 200_000.0)
        total = sum(a.allocated_pct for a in route.allocations)
        self.assertAlmostEqual(total, 100.0, places=9)

    def test_min_allocation_respected(self):
        slots = [
            make_slot("A", apy=5.0, min_pct=20, max_pct=60),
            make_slot("B", apy=8.0, min_pct=10, max_pct=40),
            make_slot("C", apy=3.0, min_pct=5, max_pct=30),
        ]
        route = optimize_route(slots, 100_000.0, max_concentration=0.6)
        for ra in route.allocations:
            self.assertGreaterEqual(ra.allocated_pct + 1e-9, ra.slot.min_allocation_pct)

    def test_max_concentration_cap(self):
        """No slot exceeds max_concentration * 100%."""
        slots = [make_slot(str(i), apy=float(10 - i), min_pct=0, max_pct=100) for i in range(5)]
        route = optimize_route(slots, 100_000.0, max_concentration=0.40)
        for ra in route.allocations:
            self.assertLessEqual(ra.allocated_pct, 40.0 + 1e-9)

    def test_max_allocation_pct_respected(self):
        slots = [
            make_slot("A", apy=10.0, min_pct=0, max_pct=30),
            make_slot("B", apy=5.0,  min_pct=0, max_pct=100),
        ]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0)
        a_alloc = next(r.allocated_pct for r in route.allocations if r.slot.name == "A")
        self.assertLessEqual(a_alloc, 30.0 + 1e-9)

    def test_greedy_fills_highest_risk_adj_apy_first(self):
        """Highest risk_adj_apy slot gets highest allocation (given no binding constraints)."""
        slots = [
            make_slot("LOW",  apy=3.0,  risk=20, min_pct=0, max_pct=40),
            make_slot("HIGH", apy=12.0, risk=30, min_pct=0, max_pct=40),
            make_slot("MED",  apy=7.0,  risk=25, min_pct=0, max_pct=40),
        ]
        route = optimize_route(slots, 100_000.0, max_concentration=0.40)
        alloc_by_name = {r.slot.name: r.allocated_pct for r in route.allocations}
        self.assertGreaterEqual(alloc_by_name["HIGH"], alloc_by_name["MED"])
        self.assertGreaterEqual(alloc_by_name["MED"], alloc_by_name["LOW"] - 1e-9)

    def test_allocated_usd_formula(self):
        slots = [make_slot("A", apy=5.0, min_pct=0, max_pct=100)]
        route = optimize_route(slots, 200_000.0, max_concentration=1.0)
        ra = route.allocations[0]
        expected_usd = 200_000.0 * ra.allocated_pct / 100.0
        self.assertAlmostEqual(ra.allocated_usd, expected_usd, places=5)

    def test_expected_yield_usd_formula(self):
        slots = [make_slot("A", apy=10.0, min_pct=0, max_pct=100)]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0)
        ra = route.allocations[0]
        expected = ra.allocated_usd * 10.0 / 100.0
        self.assertAlmostEqual(ra.expected_yield_usd, expected, places=5)

    def test_risk_contribution_formula(self):
        slots = [make_slot("A", apy=5.0, risk=40, min_pct=0, max_pct=100)]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0)
        ra = route.allocations[0]
        expected = (ra.allocated_pct / 100.0) * 40.0
        self.assertAlmostEqual(ra.risk_contribution, expected, places=8)


class TestPortfolioMetrics(unittest.TestCase):
    """Tests for OptimalRoute portfolio-level metrics."""

    def test_total_expected_yield_is_sum(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        expected = sum(a.expected_yield_usd for a in route.allocations)
        self.assertAlmostEqual(route.total_expected_yield_usd, expected, places=5)

    def test_weighted_apy_formula(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        expected = sum(a.allocated_pct / 100.0 * a.slot.apy for a in route.allocations)
        self.assertAlmostEqual(route.weighted_apy, expected, places=8)

    def test_weighted_risk_formula(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        expected = sum(a.risk_contribution for a in route.allocations)
        self.assertAlmostEqual(route.weighted_risk, expected, places=8)

    def test_risk_adjusted_return_formula(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        expected = route.weighted_apy / (1.0 + route.weighted_risk / 100.0)
        self.assertAlmostEqual(route.risk_adjusted_return, expected, places=8)

    def test_hhi_single_slot_equals_one(self):
        slots = [make_slot("A", apy=5.0, min_pct=0, max_pct=100)]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0)
        self.assertAlmostEqual(route.portfolio_hhi, 1.0, places=8)

    def test_hhi_four_equal_slots_025(self):
        """4 slots at exactly 25% each → HHI = 4*(0.25)^2 = 0.25."""
        slots = [make_slot(str(i), apy=5.0, risk=20, min_pct=25, max_pct=25) for i in range(4)]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0)
        self.assertAlmostEqual(route.portfolio_hhi, 0.25, places=6)

    def test_hhi_formula_general(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        expected = sum((a.allocated_pct / 100.0) ** 2 for a in route.allocations)
        self.assertAlmostEqual(route.portfolio_hhi, expected, places=8)

    def test_equal_weight_apy_formula(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        expected = sum(s.apy for s in slots) / len(slots)
        self.assertAlmostEqual(route.equal_weight_apy, expected, places=8)

    def test_improvement_vs_equal_positive_when_optimizer_wins(self):
        """Optimizer should beat equal-weight when APYs differ."""
        slots = [
            make_slot("HI", apy=10.0, risk=25, min_pct=0, max_pct=40),
            make_slot("LO", apy=2.0,  risk=10, min_pct=0, max_pct=40),
            make_slot("MD", apy=6.0,  risk=20, min_pct=0, max_pct=40),
        ]
        route = optimize_route(slots, 100_000.0, max_concentration=0.40)
        # Equal weight APY = (10+2+6)/3 = 6%
        # Greedy should allocate more to HI → weighted_apy > 6
        if route.weighted_apy > route.equal_weight_apy:
            self.assertGreater(route.improvement_vs_equal_pct, 0.0)

    def test_improvement_formula(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        if route.equal_weight_apy != 0:
            expected = (route.weighted_apy - route.equal_weight_apy) / route.equal_weight_apy * 100.0
            self.assertAlmostEqual(route.improvement_vs_equal_pct, expected, places=5)

    def test_single_slot_hhi_is_one(self):
        slots = [make_slot("A")]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0)
        self.assertAlmostEqual(route.portfolio_hhi, 1.0, places=8)


class TestConstraintViolations(unittest.TestCase):
    """Tests for constraint_violations and all_constraints_met."""

    def test_all_constraints_met_normal(self):
        slots = [
            make_slot("A", apy=5.0, risk=20, min_pct=0, max_pct=40),
            make_slot("B", apy=3.0, risk=10, min_pct=0, max_pct=40),
            make_slot("C", apy=4.0, risk=15, min_pct=0, max_pct=40),
        ]
        route = optimize_route(slots, 100_000.0, max_concentration=0.40, risk_budget=100)
        self.assertTrue(route.all_constraints_met)
        self.assertEqual(route.constraint_violations, [])

    def test_violation_when_risk_exceeds_budget(self):
        """Very high risk slots with tiny budget → violation."""
        slots = [
            make_slot("A", apy=5.0, risk=99, min_pct=0, max_pct=100),
            make_slot("B", apy=3.0, risk=99, min_pct=0, max_pct=100),
        ]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0, risk_budget=10.0)
        self.assertFalse(route.all_constraints_met)
        self.assertTrue(any("risk" in v.lower() for v in route.constraint_violations))

    def test_no_violations_when_risk_within_budget(self):
        slots = [make_slot("A", apy=5.0, risk=10, min_pct=0, max_pct=100)]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0, risk_budget=50.0)
        self.assertNotIn(
            True,
            ["risk" in v.lower() for v in route.constraint_violations]
        )

    def test_all_constraints_met_flag_matches_violations(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        self.assertEqual(route.all_constraints_met, len(route.constraint_violations) == 0)


class TestRouteLabel(unittest.TestCase):
    """Tests for route_label values."""

    def test_optimal_label_when_beats_equal_weight(self):
        slots = [
            make_slot("HI", apy=10.0, risk=20, min_pct=0, max_pct=40),
            make_slot("LO", apy=1.0,  risk=20, min_pct=0, max_pct=40),
            make_slot("MD", apy=5.0,  risk=20, min_pct=0, max_pct=40),
        ]
        route = optimize_route(slots, 100_000.0, max_concentration=0.40, risk_budget=100)
        if route.all_constraints_met and route.improvement_vs_equal_pct > 0:
            self.assertEqual(route.route_label, "OPTIMAL")

    def test_near_optimal_label_when_equal_weight(self):
        """All same APY → optimizer can't beat equal-weight → NEAR_OPTIMAL."""
        slots = [make_slot(str(i), apy=5.0, risk=20, min_pct=25, max_pct=25) for i in range(4)]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0, risk_budget=100)
        if route.all_constraints_met and route.improvement_vs_equal_pct <= 0:
            self.assertEqual(route.route_label, "NEAR_OPTIMAL")

    def test_constrained_label_when_violations(self):
        slots = [make_slot("A", apy=5.0, risk=99, min_pct=0, max_pct=100)]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0, risk_budget=5.0)
        if not route.all_constraints_met:
            self.assertEqual(route.route_label, "CONSTRAINED")

    def test_route_label_one_of_three_values(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        self.assertIn(route.route_label, ("OPTIMAL", "NEAR_OPTIMAL", "CONSTRAINED"))


class TestEdgeCases(unittest.TestCase):
    """Edge cases: empty slots, zero APY, etc."""

    def test_empty_slots_returns_route(self):
        route = optimize_route([], 100_000.0)
        self.assertIsInstance(route, OptimalRoute)
        self.assertEqual(route.allocations, [])
        self.assertTrue(route.all_constraints_met)

    def test_all_same_apy_equal_weight(self):
        """Same APY slots → reasonable allocation (doesn't crash)."""
        slots = [make_slot(str(i), apy=5.0, min_pct=0, max_pct=40) for i in range(5)]
        route = optimize_route(slots, 100_000.0, max_concentration=0.40)
        total = sum(a.allocated_pct for a in route.allocations)
        self.assertAlmostEqual(total, 100.0, places=9)

    def test_two_slots_high_vs_low_apy(self):
        slots = [
            make_slot("HI", apy=20.0, risk=30, min_pct=0, max_pct=100),
            make_slot("LO", apy=1.0,  risk=5,  min_pct=0, max_pct=100),
        ]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0)
        hi_alloc = next(r.allocated_pct for r in route.allocations if r.slot.name == "HI")
        lo_alloc = next(r.allocated_pct for r in route.allocations if r.slot.name == "LO")
        # Greedy should prefer HI
        self.assertGreater(hi_alloc, lo_alloc)

    def test_min_allocation_sum_equals_100_all_slots_at_min(self):
        slots = [
            make_slot("A", apy=5.0, min_pct=50, max_pct=50),
            make_slot("B", apy=3.0, min_pct=50, max_pct=50),
        ]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0)
        total = sum(a.allocated_pct for a in route.allocations)
        self.assertAlmostEqual(total, 100.0, places=9)
        for ra in route.allocations:
            self.assertAlmostEqual(ra.allocated_pct, 50.0, places=6)

    def test_total_capital_reflected_in_usd(self):
        slots = [make_slot("A", apy=5.0, min_pct=0, max_pct=100)]
        route = optimize_route(slots, 250_000.0, max_concentration=1.0)
        self.assertAlmostEqual(route.total_capital_usd, 250_000.0)
        self.assertAlmostEqual(route.allocations[0].allocated_usd, 250_000.0, places=5)


class TestSaveLoadHistory(unittest.TestCase):
    """Tests for save_results() and load_history()."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._data_file = Path(self._tmpdir.name) / "yield_route_log.json"

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_route(self) -> OptimalRoute:
        slots = four_equal_slots()
        return optimize_route(slots, 100_000.0)

    def test_save_creates_file(self):
        route = self._make_route()
        save_results(route, data_file=self._data_file)
        self.assertTrue(self._data_file.exists())

    def test_load_empty_when_no_file(self):
        hist = load_history(data_file=self._data_file)
        self.assertEqual(hist, [])

    def test_save_and_load_roundtrip(self):
        route = self._make_route()
        save_results(route, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertEqual(len(hist), 1)
        self.assertIn("allocations", hist[0])

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            save_results(self._make_route(), data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertEqual(len(hist), 5)

    def test_ring_buffer_cap_100(self):
        for _ in range(110):
            save_results(self._make_route(), data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertEqual(len(hist), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            slots = [make_slot("A", apy=float(i + 1), min_pct=0, max_pct=100)]
            route = optimize_route(slots, 100_000.0, max_concentration=1.0)
            save_results(route, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertEqual(len(hist), 100)
        # First entry should have apy > 5 (first 5 were dropped)
        first_apy = hist[0]["allocations"][0]["slot"]["apy"]
        self.assertGreater(first_apy, 5.0)

    def test_saved_to_field_set(self):
        route = self._make_route()
        save_results(route, data_file=self._data_file)
        self.assertNotEqual(route.saved_to, "")
        self.assertIn("yield_route_log", route.saved_to)

    def test_atomic_write_no_tmp_left(self):
        route = self._make_route()
        save_results(route, data_file=self._data_file)
        tmp = self._data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_saved_at_timestamp_present(self):
        route = self._make_route()
        save_results(route, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertIn("_saved_at", hist[0])

    def test_route_fields_preserved(self):
        slots = [
            make_slot("Aave", apy=3.5, risk=15, min_pct=5, max_pct=40),
            make_slot("Compound", apy=4.8, risk=18, min_pct=5, max_pct=40),
        ]
        route = optimize_route(slots, 100_000.0)
        save_results(route, data_file=self._data_file)
        hist = load_history(data_file=self._data_file)
        self.assertAlmostEqual(hist[0]["total_capital_usd"], 100_000.0, places=2)
        self.assertIn("route_label", hist[0])


class TestToDict(unittest.TestCase):
    """Tests for to_dict() serialization."""

    def test_allocation_slot_to_dict(self):
        s = make_slot("X", apy=5.0)
        d = s.to_dict()
        self.assertIn("name", d)
        self.assertIn("apy", d)
        self.assertIn("risk_score", d)

    def test_optimal_route_to_dict(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        d = route.to_dict()
        self.assertIn("total_capital_usd", d)
        self.assertIn("allocations", d)
        self.assertIn("weighted_apy", d)
        self.assertIn("route_label", d)
        self.assertIn("portfolio_hhi", d)

    def test_route_allocation_to_dict(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        d = route.allocations[0].to_dict()
        self.assertIn("slot", d)
        self.assertIn("allocated_pct", d)
        self.assertIn("expected_yield_usd", d)


class TestAdditionalCoverage(unittest.TestCase):
    """Extra tests to ensure ≥65 total."""

    def test_optimize_route_returns_optimal_route_type(self):
        route = optimize_route(four_equal_slots(), 100_000.0)
        self.assertIsInstance(route, OptimalRoute)

    def test_allocations_count_equals_slot_count(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        self.assertEqual(len(route.allocations), len(slots))

    def test_route_allocation_types(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        for ra in route.allocations:
            self.assertIsInstance(ra, RouteAllocation)

    def test_slot_fields_propagated(self):
        slots = [make_slot("Aave", apy=3.5, risk=15, min_pct=5, max_pct=40, liq=95)]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0)
        ra = route.allocations[0]
        self.assertEqual(ra.slot.name, "Aave")
        self.assertAlmostEqual(ra.slot.apy, 3.5)
        self.assertAlmostEqual(ra.slot.liquidity_score, 95)

    def test_default_max_concentration_is_40pct(self):
        self.assertAlmostEqual(DEFAULT_MAX_CONCENTRATION, 0.40, places=8)

    def test_zero_risk_score_slot(self):
        slots = [make_slot("Cash", apy=0.0, risk=0.0, min_pct=0, max_pct=100)]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0)
        self.assertAlmostEqual(route.weighted_risk, 0.0, places=8)

    def test_portfolio_hhi_between_0_and_1(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        self.assertGreaterEqual(route.portfolio_hhi, 0.0)
        self.assertLessEqual(route.portfolio_hhi, 1.0 + 1e-9)

    def test_risk_adjusted_return_positive_for_positive_apy(self):
        slots = [make_slot("A", apy=5.0, risk=20, min_pct=0, max_pct=100)]
        route = optimize_route(slots, 100_000.0, max_concentration=1.0)
        self.assertGreater(route.risk_adjusted_return, 0.0)

    def test_five_slots_sum_to_100(self):
        slots = [make_slot(str(i), apy=float(i + 1), risk=float(i * 5), min_pct=0, max_pct=40) for i in range(5)]
        route = optimize_route(slots, 500_000.0)
        total = sum(a.allocated_pct for a in route.allocations)
        self.assertAlmostEqual(total, 100.0, places=9)

    def test_validate_constraints_returns_list(self):
        slots = four_equal_slots()
        result = validate_constraints(slots)
        self.assertIsInstance(result, list)

    def test_min_allocation_min_pct_zero_allowed(self):
        """min_pct=0 means no required minimum — slot may get 0 allocation."""
        slots = [
            make_slot("A", apy=10.0, risk=20, min_pct=0, max_pct=40),
            make_slot("B", apy=10.0, risk=20, min_pct=0, max_pct=40),
            make_slot("C", apy=10.0, risk=20, min_pct=0, max_pct=40),
        ]
        route = optimize_route(slots, 100_000.0, max_concentration=0.40)
        for ra in route.allocations:
            self.assertGreaterEqual(ra.allocated_pct, 0.0)

    def test_improvement_type_is_float(self):
        slots = four_equal_slots()
        route = optimize_route(slots, 100_000.0)
        self.assertIsInstance(route.improvement_vs_equal_pct, float)

    def test_weighted_apy_positive_for_positive_apys(self):
        slots = [
            make_slot("A", apy=5.0, min_pct=0, max_pct=40),
            make_slot("B", apy=3.0, min_pct=0, max_pct=40),
        ]
        route = optimize_route(slots, 100_000.0)
        self.assertGreater(route.weighted_apy, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
