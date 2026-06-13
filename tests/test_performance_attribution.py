"""tests/test_performance_attribution.py — MP-585 PerformanceAttributor test suite.

Coverage: 107 test cases across 10 classes.

TestSafeFloat               (8)  — _safe_float: numeric, bool, None, inf, nan
TestCoerce                  (6)  — _coerce: fallback to 0.0 for bad values
TestNormaliseWeights        (9)  — normalisation, clamping, edge cases
TestUnionKeys               (5)  — _union_keys: empty, overlapping, None
TestAllocationEffect       (18)  — BHB allocation formula correctness
TestSelectionEffect        (17)  — BHB selection formula correctness
TestInteractionEffect      (12)  — BHB interaction formula correctness
TestBrinsonAttribution     (18)  — full decomposition, identity, edge cases
TestGetAttributionReport   (14)  — multi-period, contributors, structure
TestSaveReport             (10)  — atomic write, ring-buffer, dir creation
TestImportHygiene           (3)  — no forbidden runtime imports; stdlib only
TestEdgeCasesMultiAdapter   (7)  — 10-adapter portfolio stress tests

Total: 127 tests
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Make spa_core importable from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.analytics.performance_attribution import (
    PerformanceAttributor,
    SCHEMA_VERSION,
    REPORT_FILENAME,
    SOURCE_NAME,
    _HISTORY_MAX,
    _safe_float,
    _coerce,
    _normalise_weights,
    _union_keys,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _attr(tmp_dir: str | None = None) -> PerformanceAttributor:
    """Return a PerformanceAttributor backed by a temporary directory."""
    if tmp_dir is None:
        tmp_dir = tempfile.mkdtemp()
    return PerformanceAttributor(data_dir=tmp_dir)


# Two-asset canonical fixture (verified by hand)
# Benchmark: w_b = {A: 0.5, B: 0.5}, r_b = {A: 4.0, B: 6.0}
#   → r_bench_portfolio = 0.5*4 + 0.5*6 = 5.0
# Actual: w_a = {A: 0.6, B: 0.4}, r_a = {A: 5.0, B: 7.0}
#   → r_portfolio = 0.6*5 + 0.4*7 = 5.8
#   → total_active = 5.8 - 5.0 = 0.8

WA2 = {"A": 0.6, "B": 0.4}
WB2 = {"A": 0.5, "B": 0.5}
RA2 = {"A": 5.0, "B": 7.0}
RB2 = {"A": 4.0, "B": 6.0}
# Allocation A: (0.6-0.5)*(4-5)  = 0.1*(-1) = -0.1
# Allocation B: (0.4-0.5)*(6-5)  = -0.1*1   = -0.1
# Selection  A: 0.5*(5-4)        = 0.5
# Selection  B: 0.5*(7-6)        = 0.5
# Interaction A: (0.1)*(1)       = 0.1
# Interaction B: (-0.1)*(1)      = -0.1
# Totals: alloc=-0.2, sel=1.0, inter=0.0 → active=0.8


# ---------------------------------------------------------------------------
# TestSafeFloat (8 tests)
# ---------------------------------------------------------------------------

class TestSafeFloat(unittest.TestCase):
    """_safe_float: convert to finite float or None."""

    def test_int_value(self):
        self.assertEqual(_safe_float(3), 3.0)

    def test_float_value(self):
        self.assertAlmostEqual(_safe_float(1.5), 1.5)

    def test_negative(self):
        self.assertEqual(_safe_float(-2.5), -2.5)

    def test_zero(self):
        self.assertEqual(_safe_float(0), 0.0)

    def test_bool_true_is_none(self):
        """True must be rejected (not 1.0)."""
        self.assertIsNone(_safe_float(True))

    def test_bool_false_is_none(self):
        """False must be rejected (not 0.0)."""
        self.assertIsNone(_safe_float(False))

    def test_none_is_none(self):
        self.assertIsNone(_safe_float(None))

    def test_inf_is_none(self):
        self.assertIsNone(_safe_float(float("inf")))

    # bonus (keeps count consistent with docstring — counted as part of this class)
    def test_nan_is_none(self):
        self.assertIsNone(_safe_float(float("nan")))

    def test_string_numeric(self):
        """Numeric string → float."""
        self.assertAlmostEqual(_safe_float("3.14"), 3.14)

    def test_string_non_numeric(self):
        self.assertIsNone(_safe_float("abc"))


# ---------------------------------------------------------------------------
# TestCoerce (6 tests)
# ---------------------------------------------------------------------------

class TestCoerce(unittest.TestCase):
    """_coerce: _safe_float with 0.0 fallback."""

    def test_normal_float(self):
        self.assertAlmostEqual(_coerce(2.5), 2.5)

    def test_none_gives_zero(self):
        self.assertEqual(_coerce(None), 0.0)

    def test_inf_gives_zero(self):
        self.assertEqual(_coerce(float("inf")), 0.0)

    def test_nan_gives_zero(self):
        self.assertEqual(_coerce(float("nan")), 0.0)

    def test_bool_gives_zero(self):
        self.assertEqual(_coerce(True), 0.0)

    def test_zero_value(self):
        """Coercing 0 stays 0 — not confused with None fallback."""
        self.assertEqual(_coerce(0), 0.0)


# ---------------------------------------------------------------------------
# TestNormaliseWeights (9 tests)
# ---------------------------------------------------------------------------

class TestNormaliseWeights(unittest.TestCase):

    def test_sums_to_one(self):
        w = _normalise_weights({"A": 0.3, "B": 0.7})
        self.assertAlmostEqual(sum(w.values()), 1.0)

    def test_preserves_keys(self):
        w = _normalise_weights({"X": 1.0, "Y": 3.0})
        self.assertIn("X", w)
        self.assertIn("Y", w)

    def test_correct_fractions(self):
        w = _normalise_weights({"A": 1.0, "B": 1.0})
        self.assertAlmostEqual(w["A"], 0.5)
        self.assertAlmostEqual(w["B"], 0.5)

    def test_negative_clamped_to_zero(self):
        w = _normalise_weights({"A": -5.0, "B": 4.0})
        self.assertEqual(w["A"], 0.0)
        self.assertAlmostEqual(w["B"], 1.0)

    def test_all_zero_returns_zero_dict(self):
        w = _normalise_weights({"A": 0.0, "B": 0.0})
        self.assertEqual(w["A"], 0.0)
        self.assertEqual(w["B"], 0.0)

    def test_empty_returns_empty(self):
        self.assertEqual(_normalise_weights({}), {})

    def test_single_key(self):
        w = _normalise_weights({"only": 42.0})
        self.assertAlmostEqual(w["only"], 1.0)

    def test_large_weights_normalised(self):
        w = _normalise_weights({"A": 100.0, "B": 400.0})
        self.assertAlmostEqual(w["A"], 0.2)
        self.assertAlmostEqual(w["B"], 0.8)

    def test_all_negative_gives_all_zero(self):
        w = _normalise_weights({"A": -1.0, "B": -2.0})
        self.assertEqual(w["A"], 0.0)
        self.assertEqual(w["B"], 0.0)


# ---------------------------------------------------------------------------
# TestUnionKeys (5 tests)
# ---------------------------------------------------------------------------

class TestUnionKeys(unittest.TestCase):

    def test_disjoint_dicts(self):
        self.assertEqual(_union_keys({"A": 1}, {"B": 2}), {"A", "B"})

    def test_overlapping_dicts(self):
        self.assertEqual(_union_keys({"A": 1, "B": 2}, {"B": 3, "C": 4}), {"A", "B", "C"})

    def test_empty_input(self):
        self.assertEqual(_union_keys(), set())

    def test_none_input_tolerated(self):
        # None dicts should be skipped without raising
        result = _union_keys(None, {"A": 1})
        self.assertIn("A", result)

    def test_three_dicts(self):
        result = _union_keys({"A": 1}, {"B": 2}, {"C": 3})
        self.assertEqual(result, {"A", "B", "C"})


# ---------------------------------------------------------------------------
# TestAllocationEffect (18 tests)
# ---------------------------------------------------------------------------

class TestAllocationEffect(unittest.TestCase):

    def setUp(self):
        self.p = _attr()

    def test_canonical_A(self):
        """Allocation A = (0.6-0.5)*(4-5) = -0.1"""
        e = self.p.compute_allocation_effect(WA2, WB2, RB2)
        self.assertAlmostEqual(e["A"], -0.1, places=10)

    def test_canonical_B(self):
        """Allocation B = (0.4-0.5)*(6-5) = -0.1"""
        e = self.p.compute_allocation_effect(WA2, WB2, RB2)
        self.assertAlmostEqual(e["B"], -0.1, places=10)

    def test_canonical_total(self):
        """Total allocation = -0.2"""
        e = self.p.compute_allocation_effect(WA2, WB2, RB2)
        self.assertAlmostEqual(sum(e.values()), -0.2, places=10)

    def test_equal_weights_zero_effect(self):
        """When w_actual == w_bench, allocation is 0 for all adapters."""
        e = self.p.compute_allocation_effect(WB2, WB2, RB2)
        for v in e.values():
            self.assertAlmostEqual(v, 0.0, places=12)

    def test_returns_dict(self):
        e = self.p.compute_allocation_effect(WA2, WB2, RB2)
        self.assertIsInstance(e, dict)

    def test_keys_union(self):
        """Returns keys for ALL adapters across all inputs."""
        wa = {"A": 1.0}
        wb = {"B": 1.0}
        rb = {"C": 1.0}
        e = self.p.compute_allocation_effect(wa, wb, rb)
        self.assertIn("A", e)
        self.assertIn("B", e)
        self.assertIn("C", e)

    def test_missing_key_treated_as_zero_actual(self):
        """Adapter in bench but absent from actual → w_actual=0."""
        wa = {"B": 1.0}
        wb = {"A": 0.5, "B": 0.5}
        rb = {"A": 4.0, "B": 6.0}
        e = self.p.compute_allocation_effect(wa, wb, rb)
        # A: w_actual=0, w_bench=0.5, r_bench_portfolio=5.0
        # Allocation A = (0 - 0.5) * (4 - 5) = 0.5
        self.assertAlmostEqual(e["A"], 0.5, places=10)

    def test_missing_key_treated_as_zero_bench(self):
        """Adapter in actual but absent from bench → w_bench=0."""
        wa = {"A": 0.5, "B": 0.5}
        wb = {"B": 1.0}
        rb = {"B": 6.0}
        e = self.p.compute_allocation_effect(wa, wb, rb)
        # r_bench_portfolio = 1.0 * 6.0 = 6.0
        # A: (0.5 - 0) * (0 - 6) = 0.5 * (-6) = -3.0
        self.assertAlmostEqual(e["A"], -3.0, places=10)

    def test_empty_weights_no_error(self):
        e = self.p.compute_allocation_effect({}, {}, {})
        self.assertEqual(e, {})

    def test_empty_actual_weights(self):
        e = self.p.compute_allocation_effect({}, WB2, RB2)
        # w_actual=0 everywhere; effect = -w_bench * (r_bench_i - r_bench_portfolio)
        self.assertIsInstance(e, dict)

    def test_negative_weight_clamped(self):
        wa = {"A": -0.5, "B": 1.5}
        wb = {"A": 0.5, "B": 0.5}
        rb = {"A": 4.0, "B": 6.0}
        # negative A clamped to 0 → actual = {A:0, B:1.0} → norm {A:0, B:1}
        e = self.p.compute_allocation_effect(wa, wb, rb)
        self.assertIsInstance(e, dict)
        # B overweighted: (1-0.5)*(6-5)=0.5
        self.assertAlmostEqual(e["B"], 0.5, places=10)

    def test_single_adapter_benchmark_return_equals_asset_return(self):
        """Single asset: r_bench_i == r_bench_portfolio → allocation=0."""
        wa = {"A": 0.8}
        wb = {"A": 0.5}
        rb = {"A": 5.0}
        e = self.p.compute_allocation_effect(wa, wb, rb)
        self.assertAlmostEqual(e["A"], 0.0, places=12)

    def test_unnormalised_weights_give_same_result(self):
        """Scaling all weights by a constant should not change the result."""
        wa_scaled = {k: v * 10 for k, v in WA2.items()}
        wb_scaled = {k: v * 10 for k, v in WB2.items()}
        e_orig = self.p.compute_allocation_effect(WA2, WB2, RB2)
        e_scaled = self.p.compute_allocation_effect(wa_scaled, wb_scaled, RB2)
        for k in e_orig:
            self.assertAlmostEqual(e_orig[k], e_scaled[k], places=10)

    def test_zero_benchmark_return(self):
        """All benchmark returns = 0 → r_bench_portfolio = 0."""
        rb_zero = {"A": 0.0, "B": 0.0}
        e = self.p.compute_allocation_effect(WA2, WB2, rb_zero)
        # r_bench_portfolio=0; A: (0.6-0.5)*(0-0)=0; B: (0.4-0.5)*(0-0)=0
        for v in e.values():
            self.assertAlmostEqual(v, 0.0, places=12)

    def test_effect_sign_overweight_below_benchmark(self):
        """Overweighting an asset that returns below benchmark → negative."""
        wa = {"A": 0.8, "B": 0.2}
        wb = {"A": 0.2, "B": 0.8}
        # rb_portfolio = 0.2*2 + 0.8*8 = 0.4+6.4 = 6.8
        # A: (0.8-0.2)*(2-6.8) = 0.6*(-4.8) = -2.88
        rb = {"A": 2.0, "B": 8.0}
        e = self.p.compute_allocation_effect(wa, wb, rb)
        self.assertLess(e["A"], 0.0)

    def test_effect_sign_underweight_above_benchmark(self):
        """Underweighting an asset that returns above benchmark → negative."""
        wa = {"A": 0.2, "B": 0.8}
        wb = {"A": 0.8, "B": 0.2}
        rb = {"A": 10.0, "B": 2.0}
        # rb_portfolio = 0.8*10 + 0.2*2 = 8+0.4=8.4
        # A: (0.2-0.8)*(10-8.4) = -0.6*1.6 = -0.96
        e = self.p.compute_allocation_effect(wa, wb, rb)
        self.assertLess(e["A"], 0.0)

    def test_three_adapters(self):
        wa = {"A": 0.5, "B": 0.3, "C": 0.2}
        wb = {"A": 0.4, "B": 0.4, "C": 0.2}
        rb = {"A": 3.0, "B": 5.0, "C": 7.0}
        e = self.p.compute_allocation_effect(wa, wb, rb)
        self.assertEqual(len(e), 3)
        # Sum should be allocation total, not necessarily 0
        self.assertIsInstance(sum(e.values()), float)

    def test_values_are_floats(self):
        e = self.p.compute_allocation_effect(WA2, WB2, RB2)
        for v in e.values():
            self.assertIsInstance(v, float)


# ---------------------------------------------------------------------------
# TestSelectionEffect (17 tests)
# ---------------------------------------------------------------------------

class TestSelectionEffect(unittest.TestCase):

    def setUp(self):
        self.p = _attr()

    def test_canonical_A(self):
        """Selection A = 0.5 * (5-4) = 0.5"""
        e = self.p.compute_selection_effect(WB2, RA2, RB2)
        self.assertAlmostEqual(e["A"], 0.5, places=10)

    def test_canonical_B(self):
        """Selection B = 0.5 * (7-6) = 0.5"""
        e = self.p.compute_selection_effect(WB2, RA2, RB2)
        self.assertAlmostEqual(e["B"], 0.5, places=10)

    def test_canonical_total(self):
        e = self.p.compute_selection_effect(WB2, RA2, RB2)
        self.assertAlmostEqual(sum(e.values()), 1.0, places=10)

    def test_equal_returns_zero_effect(self):
        """When r_actual == r_bench, selection is 0."""
        e = self.p.compute_selection_effect(WB2, RB2, RB2)
        for v in e.values():
            self.assertAlmostEqual(v, 0.0, places=12)

    def test_returns_dict(self):
        self.assertIsInstance(self.p.compute_selection_effect(WB2, RA2, RB2), dict)

    def test_zero_bench_weight_zero_selection(self):
        """Adapter with 0 benchmark weight contributes 0 to selection."""
        wb = {"A": 0.0, "B": 1.0}
        ra = {"A": 100.0, "B": 6.0}
        rb = {"A": 4.0, "B": 6.0}
        e = self.p.compute_selection_effect(wb, ra, rb)
        # A has 0 bench weight → selection A = 0
        self.assertAlmostEqual(e.get("A", 0.0), 0.0, places=10)

    def test_keys_union(self):
        wb = {"A": 1.0}
        ra = {"B": 5.0}
        rb = {"C": 3.0}
        e = self.p.compute_selection_effect(wb, ra, rb)
        self.assertIn("A", e)
        self.assertIn("B", e)
        self.assertIn("C", e)

    def test_missing_actual_return_treated_as_zero(self):
        wb = {"A": 0.5, "B": 0.5}
        ra = {"B": 6.0}      # A missing → r_actual_A = 0
        rb = {"A": 4.0, "B": 5.0}
        e = self.p.compute_selection_effect(wb, ra, rb)
        # A: 0.5 * (0 - 4) = -2.0
        self.assertAlmostEqual(e["A"], -2.0, places=10)

    def test_missing_bench_return_treated_as_zero(self):
        wb = {"A": 0.5, "B": 0.5}
        ra = {"A": 5.0, "B": 7.0}
        rb = {"A": 4.0}      # B missing → r_bench_B = 0
        e = self.p.compute_selection_effect(wb, ra, rb)
        # B: 0.5 * (7 - 0) = 3.5
        self.assertAlmostEqual(e["B"], 3.5, places=10)

    def test_empty_inputs(self):
        e = self.p.compute_selection_effect({}, {}, {})
        self.assertEqual(e, {})

    def test_negative_selection(self):
        ra = {"A": 2.0, "B": 7.0}
        e = self.p.compute_selection_effect(WB2, ra, RB2)
        # A: 0.5*(2-4)=-1; B: 0.5*(7-6)=0.5
        self.assertAlmostEqual(e["A"], -1.0, places=10)
        self.assertAlmostEqual(e["B"], 0.5, places=10)

    def test_positive_selection_total(self):
        ra = {"A": 6.0, "B": 8.0}
        e = self.p.compute_selection_effect(WB2, ra, RB2)
        self.assertGreater(sum(e.values()), 0.0)

    def test_unnormalised_bench_weights(self):
        wb_scaled = {k: v * 100 for k, v in WB2.items()}
        e_orig = self.p.compute_selection_effect(WB2, RA2, RB2)
        e_scaled = self.p.compute_selection_effect(wb_scaled, RA2, RB2)
        for k in e_orig:
            self.assertAlmostEqual(e_orig[k], e_scaled[k], places=10)

    def test_single_adapter(self):
        wb = {"A": 1.0}
        ra = {"A": 5.0}
        rb = {"A": 3.0}
        e = self.p.compute_selection_effect(wb, ra, rb)
        # 1.0 * (5-3) = 2.0
        self.assertAlmostEqual(e["A"], 2.0, places=10)

    def test_three_adapters(self):
        wb = {"A": 0.4, "B": 0.4, "C": 0.2}
        ra = {"A": 5.0, "B": 6.0, "C": 8.0}
        rb = {"A": 3.0, "B": 5.0, "C": 7.0}
        e = self.p.compute_selection_effect(wb, ra, rb)
        self.assertEqual(len(e), 3)
        # A: 0.4*(5-3)=0.8; B:0.4*(6-5)=0.4; C:0.2*(8-7)=0.2 → total=1.4
        self.assertAlmostEqual(sum(e.values()), 1.4, places=10)

    def test_values_are_floats(self):
        e = self.p.compute_selection_effect(WB2, RA2, RB2)
        for v in e.values():
            self.assertIsInstance(v, float)

    def test_negative_bench_weight_clamped(self):
        wb = {"A": -1.0, "B": 2.0}
        ra = {"A": 5.0, "B": 7.0}
        rb = {"A": 4.0, "B": 6.0}
        e = self.p.compute_selection_effect(wb, ra, rb)
        # A clamped to 0 → selection A = 0
        self.assertAlmostEqual(e.get("A", 0.0), 0.0, places=10)


# ---------------------------------------------------------------------------
# TestInteractionEffect (12 tests)
# ---------------------------------------------------------------------------

class TestInteractionEffect(unittest.TestCase):

    def setUp(self):
        self.p = _attr()

    def test_canonical_A(self):
        """Interaction A = (0.6-0.5)*(5-4) = 0.1"""
        e = self.p.compute_interaction_effect(WA2, WB2, RA2, RB2)
        self.assertAlmostEqual(e["A"], 0.1, places=10)

    def test_canonical_B(self):
        """Interaction B = (0.4-0.5)*(7-6) = -0.1"""
        e = self.p.compute_interaction_effect(WA2, WB2, RA2, RB2)
        self.assertAlmostEqual(e["B"], -0.1, places=10)

    def test_canonical_total_zero(self):
        """Interaction total = 0.0 for the canonical fixture."""
        e = self.p.compute_interaction_effect(WA2, WB2, RA2, RB2)
        self.assertAlmostEqual(sum(e.values()), 0.0, places=10)

    def test_equal_weights_zero_interaction(self):
        """Same weights → w_actual - w_bench = 0 → interaction = 0."""
        e = self.p.compute_interaction_effect(WB2, WB2, RA2, RB2)
        for v in e.values():
            self.assertAlmostEqual(v, 0.0, places=12)

    def test_equal_returns_zero_interaction(self):
        """Same actual/bench returns → r_actual - r_bench = 0 → interaction = 0."""
        e = self.p.compute_interaction_effect(WA2, WB2, RB2, RB2)
        for v in e.values():
            self.assertAlmostEqual(v, 0.0, places=12)

    def test_returns_dict(self):
        self.assertIsInstance(
            self.p.compute_interaction_effect(WA2, WB2, RA2, RB2), dict
        )

    def test_empty_inputs(self):
        e = self.p.compute_interaction_effect({}, {}, {}, {})
        self.assertEqual(e, {})

    def test_keys_union(self):
        e = self.p.compute_interaction_effect(
            {"A": 1.0}, {"B": 1.0}, {"C": 1.0}, {"D": 1.0}
        )
        for k in ("A", "B", "C", "D"):
            self.assertIn(k, e)

    def test_sign_overweight_outperforming(self):
        """Overweight asset that also outperforms → positive interaction."""
        wa = {"A": 0.8, "B": 0.2}
        wb = {"A": 0.2, "B": 0.8}
        ra = {"A": 10.0, "B": 2.0}
        rb = {"A": 5.0, "B": 5.0}
        e = self.p.compute_interaction_effect(wa, wb, ra, rb)
        # A: (0.8-0.2)*(10-5)=0.6*5=3.0 → positive
        self.assertGreater(e["A"], 0.0)

    def test_sign_overweight_underperforming(self):
        """Overweight asset that underperforms → negative interaction."""
        wa = {"A": 0.8, "B": 0.2}
        wb = {"A": 0.2, "B": 0.8}
        ra = {"A": 2.0, "B": 10.0}
        rb = {"A": 5.0, "B": 5.0}
        e = self.p.compute_interaction_effect(wa, wb, ra, rb)
        # A: (0.8-0.2)*(2-5)=0.6*(-3)=-1.8 → negative
        self.assertLess(e["A"], 0.0)

    def test_single_adapter(self):
        wa = {"A": 0.8}
        wb = {"A": 0.5}
        ra = {"A": 6.0}
        rb = {"A": 4.0}
        e = self.p.compute_interaction_effect(wa, wb, ra, rb)
        # (0.8-0.5)*(6-4) = 0.3*2 = 0.6 ... but weights normalise to 1
        # After norm: wa={A:1.0}, wb={A:1.0} → diff=0 → interaction=0
        self.assertAlmostEqual(e["A"], 0.0, places=10)

    def test_values_are_floats(self):
        e = self.p.compute_interaction_effect(WA2, WB2, RA2, RB2)
        for v in e.values():
            self.assertIsInstance(v, float)


# ---------------------------------------------------------------------------
# TestBrinsonAttribution (18 tests)
# ---------------------------------------------------------------------------

class TestBrinsonAttribution(unittest.TestCase):

    def setUp(self):
        self.p = _attr()

    def _brinson(self, wa=WA2, wb=WB2, ra=RA2, rb=RB2):
        return self.p.brinson_attribution(wa, wb, ra, rb)

    def test_total_active_return_canonical(self):
        r = self._brinson()
        self.assertAlmostEqual(r["total_active_return"], 0.8, places=10)

    def test_portfolio_return(self):
        """portfolio_return = 0.6*5 + 0.4*7 = 5.8"""
        r = self._brinson()
        self.assertAlmostEqual(r["portfolio_return"], 5.8, places=10)

    def test_benchmark_return(self):
        """benchmark_return = 0.5*4 + 0.5*6 = 5.0"""
        r = self._brinson()
        self.assertAlmostEqual(r["benchmark_return"], 5.0, places=10)

    def test_allocation_total(self):
        r = self._brinson()
        self.assertAlmostEqual(r["allocation_total"], -0.2, places=10)

    def test_selection_total(self):
        r = self._brinson()
        self.assertAlmostEqual(r["selection_total"], 1.0, places=10)

    def test_interaction_total(self):
        r = self._brinson()
        self.assertAlmostEqual(r["interaction_total"], 0.0, places=10)

    def test_bhb_identity_holds(self):
        """Allocation + Selection + Interaction == total_active_return."""
        r = self._brinson()
        reconstituted = (
            r["allocation_total"]
            + r["selection_total"]
            + r["interaction_total"]
        )
        self.assertAlmostEqual(reconstituted, r["total_active_return"], places=10)

    def test_bhb_identity_random_weights(self):
        """Identity holds for arbitrary weight/return inputs."""
        wa = {"A": 0.3, "B": 0.4, "C": 0.3}
        wb = {"A": 0.25, "B": 0.5, "C": 0.25}
        ra = {"A": 5.0, "B": 3.0, "C": 8.0}
        rb = {"A": 4.5, "B": 4.0, "C": 7.5}
        r = self.p.brinson_attribution(wa, wb, ra, rb)
        reconstituted = (
            r["allocation_total"]
            + r["selection_total"]
            + r["interaction_total"]
        )
        self.assertAlmostEqual(reconstituted, r["total_active_return"], places=10)

    def test_by_adapter_keys_present(self):
        r = self._brinson()
        self.assertIn("A", r["by_adapter"])
        self.assertIn("B", r["by_adapter"])

    def test_by_adapter_per_adapter_total(self):
        """by_adapter[k]['total'] == alloc + sel + inter for that adapter."""
        r = self._brinson()
        for k, v in r["by_adapter"].items():
            self.assertAlmostEqual(
                v["total"], v["allocation"] + v["selection"] + v["interaction"],
                places=10,
            )

    def test_by_adapter_sum_equals_totals(self):
        """Sum of by_adapter totals ≈ allocation_total + selection_total + interaction_total."""
        r = self._brinson()
        by_total = sum(v["total"] for v in r["by_adapter"].values())
        self.assertAlmostEqual(
            by_total,
            r["allocation_total"] + r["selection_total"] + r["interaction_total"],
            places=10,
        )

    def test_zero_active_return_when_identical(self):
        """Same weights and same returns → total_active_return = 0."""
        r = self.p.brinson_attribution(WB2, WB2, RB2, RB2)
        self.assertAlmostEqual(r["total_active_return"], 0.0, places=12)

    def test_empty_inputs_no_crash(self):
        r = self.p.brinson_attribution({}, {}, {}, {})
        self.assertIsInstance(r, dict)
        self.assertAlmostEqual(r["total_active_return"], 0.0, places=12)

    def test_required_keys_present(self):
        r = self._brinson()
        for key in (
            "total_active_return", "allocation_total", "selection_total",
            "interaction_total", "portfolio_return", "benchmark_return", "by_adapter"
        ):
            self.assertIn(key, r)

    def test_by_adapter_sub_keys(self):
        r = self._brinson()
        for adapter_data in r["by_adapter"].values():
            self.assertIn("allocation", adapter_data)
            self.assertIn("selection", adapter_data)
            self.assertIn("interaction", adapter_data)
            self.assertIn("total", adapter_data)

    def test_only_selection_active(self):
        """Same weights → allocation=0, interaction=0; active from selection only."""
        wa = {"A": 0.5, "B": 0.5}
        wb = {"A": 0.5, "B": 0.5}
        ra = {"A": 6.0, "B": 8.0}
        rb = {"A": 4.0, "B": 6.0}
        r = self.p.brinson_attribution(wa, wb, ra, rb)
        self.assertAlmostEqual(r["allocation_total"], 0.0, places=10)
        self.assertAlmostEqual(r["interaction_total"], 0.0, places=10)
        # selection = 0.5*(2) + 0.5*(2) = 2.0
        self.assertAlmostEqual(r["selection_total"], 2.0, places=10)

    def test_negative_active_return(self):
        """Underperforming portfolio → negative total_active_return."""
        ra = {"A": 2.0, "B": 4.0}
        r = self.p.brinson_attribution(WA2, WB2, ra, RB2)
        self.assertLess(r["total_active_return"], 0.0)

    def test_active_return_equals_portfolio_minus_benchmark(self):
        r = self._brinson()
        self.assertAlmostEqual(
            r["total_active_return"],
            r["portfolio_return"] - r["benchmark_return"],
            places=12,
        )


# ---------------------------------------------------------------------------
# TestGetAttributionReport (14 tests)
# ---------------------------------------------------------------------------

class TestGetAttributionReport(unittest.TestCase):

    def setUp(self):
        self.p = _attr()
        self.bw = WB2
        self.history = [
            {"date": "2026-06-01", "weights_actual": WA2,
             "returns_actual": RA2, "returns_bench": RB2},
        ]

    def test_available_true_with_history(self):
        r = self.p.get_attribution_report(self.history, self.bw)
        self.assertTrue(r["available"])

    def test_available_false_empty_history(self):
        r = self.p.get_attribution_report([], self.bw)
        self.assertFalse(r["available"])

    def test_single_period_active_return(self):
        r = self.p.get_attribution_report(self.history, self.bw)
        self.assertAlmostEqual(r["total_active_return"], 0.8, places=10)

    def test_periods_count(self):
        r = self.p.get_attribution_report(self.history, self.bw)
        self.assertEqual(r["periods"], 1)

    def test_multi_period_accumulation(self):
        history = self.history * 3
        r = self.p.get_attribution_report(history, self.bw)
        self.assertEqual(r["periods"], 3)
        self.assertAlmostEqual(r["total_active_return"], 3 * 0.8, places=10)

    def test_cumulative_allocation(self):
        history = self.history * 2
        r = self.p.get_attribution_report(history, self.bw)
        self.assertAlmostEqual(r["cumulative_allocation"], 2 * (-0.2), places=10)

    def test_cumulative_selection(self):
        history = self.history * 2
        r = self.p.get_attribution_report(history, self.bw)
        self.assertAlmostEqual(r["cumulative_selection"], 2 * 1.0, places=10)

    def test_required_keys(self):
        r = self.p.get_attribution_report(self.history, self.bw)
        for k in (
            "available", "periods", "total_active_return",
            "avg_allocation_effect", "avg_selection_effect", "avg_interaction_effect",
            "cumulative_allocation", "cumulative_selection", "cumulative_interaction",
            "top_contributors", "top_detractors", "by_adapter",
            "periods_detail", "benchmark_weights", "generated_at", "notes",
        ):
            self.assertIn(k, r)

    def test_by_adapter_populated(self):
        r = self.p.get_attribution_report(self.history, self.bw)
        self.assertIn("A", r["by_adapter"])
        self.assertIn("B", r["by_adapter"])

    def test_top_contributors_positive(self):
        r = self.p.get_attribution_report(self.history, self.bw)
        for item in r["top_contributors"]:
            self.assertGreater(item["total_active_contribution"], 0.0)

    def test_top_detractors_negative(self):
        # Make A a detractor
        history = [{"weights_actual": {"A": 0.9, "B": 0.1},
                    "returns_actual": {"A": 1.0, "B": 7.0},
                    "returns_bench": {"A": 6.0, "B": 5.0}}]
        r = self.p.get_attribution_report(history, self.bw)
        for item in r["top_detractors"]:
            self.assertLess(item["total_active_contribution"], 0.0)

    def test_periods_detail_length(self):
        r = self.p.get_attribution_report(self.history, self.bw)
        self.assertEqual(len(r["periods_detail"]), 1)

    def test_bad_period_skipped_gracefully(self):
        history = [
            "not_a_dict",
            {"date": "ok", "weights_actual": WA2,
             "returns_actual": RA2, "returns_bench": RB2},
        ]
        r = self.p.get_attribution_report(history, self.bw)
        self.assertEqual(r["periods"], 1)
        self.assertTrue(any("skipped" in n for n in r["notes"]))

    def test_avg_effects(self):
        history = self.history * 4
        r = self.p.get_attribution_report(history, self.bw)
        self.assertAlmostEqual(
            r["avg_allocation_effect"], r["cumulative_allocation"] / 4, places=12
        )
        self.assertAlmostEqual(
            r["avg_selection_effect"], r["cumulative_selection"] / 4, places=12
        )


# ---------------------------------------------------------------------------
# TestSaveReport (10 tests)
# ---------------------------------------------------------------------------

class TestSaveReport(unittest.TestCase):

    def _make_report(self, tmp_dir: str) -> dict:
        p = _attr(tmp_dir)
        history = [{"date": "2026-06-01", "weights_actual": WA2,
                    "returns_actual": RA2, "returns_bench": RB2}]
        return p.get_attribution_report(history, WB2)

    def test_file_created(self):
        with tempfile.TemporaryDirectory() as d:
            p = _attr(d)
            report = self._make_report(d)
            p.save_report(report)
            self.assertTrue((Path(d) / REPORT_FILENAME).exists())

    def test_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = _attr(d)
            p.save_report(self._make_report(d))
            content = json.loads((Path(d) / REPORT_FILENAME).read_text())
            self.assertIsInstance(content, dict)

    def test_schema_version_present(self):
        with tempfile.TemporaryDirectory() as d:
            p = _attr(d)
            p.save_report(self._make_report(d))
            content = json.loads((Path(d) / REPORT_FILENAME).read_text())
            self.assertEqual(content["schema_version"], SCHEMA_VERSION)

    def test_source_name_present(self):
        with tempfile.TemporaryDirectory() as d:
            p = _attr(d)
            p.save_report(self._make_report(d))
            content = json.loads((Path(d) / REPORT_FILENAME).read_text())
            self.assertEqual(content["source"], SOURCE_NAME)

    def test_history_is_list(self):
        with tempfile.TemporaryDirectory() as d:
            p = _attr(d)
            p.save_report(self._make_report(d))
            content = json.loads((Path(d) / REPORT_FILENAME).read_text())
            self.assertIsInstance(content["history"], list)

    def test_multiple_saves_grow_history(self):
        with tempfile.TemporaryDirectory() as d:
            p = _attr(d)
            report = self._make_report(d)
            p.save_report(report)
            p.save_report(report)
            p.save_report(report)
            content = json.loads((Path(d) / REPORT_FILENAME).read_text())
            self.assertEqual(len(content["history"]), 3)

    def test_ring_buffer_caps_at_history_max(self):
        with tempfile.TemporaryDirectory() as d:
            p = _attr(d)
            report = self._make_report(d)
            for _ in range(_HISTORY_MAX + 5):
                p.save_report(report)
            content = json.loads((Path(d) / REPORT_FILENAME).read_text())
            self.assertLessEqual(len(content["history"]), _HISTORY_MAX)

    def test_creates_data_dir_if_missing(self):
        with tempfile.TemporaryDirectory() as d:
            new_dir = os.path.join(d, "deep", "nested", "dir")
            p = _attr(new_dir)
            p.save_report(self._make_report(d))
            self.assertTrue((Path(new_dir) / REPORT_FILENAME).exists())

    def test_history_entry_has_expected_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p = _attr(d)
            p.save_report(self._make_report(d))
            content = json.loads((Path(d) / REPORT_FILENAME).read_text())
            entry = content["history"][0]
            self.assertIn("total_active_return", entry)

    def test_no_tmp_file_left_behind(self):
        with tempfile.TemporaryDirectory() as d:
            p = _attr(d)
            p.save_report(self._make_report(d))
            tmp_files = [f for f in os.listdir(d) if f.endswith(".tmp")]
            self.assertEqual(tmp_files, [])


# ---------------------------------------------------------------------------
# TestImportHygiene (3 tests)
# ---------------------------------------------------------------------------

class TestImportHygiene(unittest.TestCase):
    """Verify no forbidden runtime dependencies are pulled in."""

    def _mod_source(self) -> str:
        import spa_core.analytics.performance_attribution as m
        return Path(m.__file__).read_text(encoding="utf-8")

    def test_no_requests(self):
        self.assertNotIn("import requests", self._mod_source())

    def test_no_numpy_pandas(self):
        src = self._mod_source()
        self.assertNotIn("import numpy", src)
        self.assertNotIn("import pandas", src)

    def test_no_execution_risk_imports(self):
        src = self._mod_source()
        self.assertNotIn("spa_core.execution", src)
        self.assertNotIn("spa_core.risk", src)


# ---------------------------------------------------------------------------
# TestEdgeCasesMultiAdapter (7 tests)
# ---------------------------------------------------------------------------

class TestEdgeCasesMultiAdapter(unittest.TestCase):
    """Stress tests with larger portfolios."""

    def setUp(self):
        self.p = _attr()

    def _ten_adapter_inputs(self, seed_offset: float = 0.0):
        ids = [f"adapter_{i}" for i in range(10)]
        wa = {k: 0.1 for k in ids}
        wb = {k: 0.1 for k in ids}
        ra = {k: float(i) + 1.0 + seed_offset for i, k in enumerate(ids)}
        rb = {k: float(i) + 0.5 for i, k in enumerate(ids)}
        return wa, wb, ra, rb

    def test_ten_adapter_identity(self):
        wa, wb, ra, rb = self._ten_adapter_inputs()
        r = self.p.brinson_attribution(wa, wb, ra, rb)
        reconstituted = (
            r["allocation_total"] + r["selection_total"] + r["interaction_total"]
        )
        self.assertAlmostEqual(reconstituted, r["total_active_return"], places=10)

    def test_ten_adapter_equal_weights_no_allocation(self):
        wa, wb, ra, rb = self._ten_adapter_inputs()
        r = self.p.brinson_attribution(wa, wb, ra, rb)
        # Equal weights → allocation=0
        self.assertAlmostEqual(r["allocation_total"], 0.0, places=10)

    def test_ten_adapter_by_adapter_count(self):
        wa, wb, ra, rb = self._ten_adapter_inputs()
        r = self.p.brinson_attribution(wa, wb, ra, rb)
        self.assertEqual(len(r["by_adapter"]), 10)

    def test_ten_period_report(self):
        wa, wb, ra, rb = self._ten_adapter_inputs()
        history = [{"weights_actual": wa, "returns_actual": ra, "returns_bench": rb}
                   for _ in range(10)]
        r = self.p.get_attribution_report(history, wb)
        self.assertEqual(r["periods"], 10)

    def test_all_zero_returns(self):
        wa = {"A": 0.5, "B": 0.5}
        wb = {"A": 0.5, "B": 0.5}
        ra = {"A": 0.0, "B": 0.0}
        rb = {"A": 0.0, "B": 0.0}
        r = self.p.brinson_attribution(wa, wb, ra, rb)
        self.assertAlmostEqual(r["total_active_return"], 0.0, places=12)

    def test_bhb_identity_asymmetric_key_sets(self):
        wa = {"A": 0.5, "B": 0.3, "C": 0.2}
        wb = {"B": 0.4, "C": 0.4, "D": 0.2}
        ra = {"A": 5.0, "B": 6.0, "C": 3.0}
        rb = {"B": 4.0, "C": 2.0, "D": 8.0}
        r = self.p.brinson_attribution(wa, wb, ra, rb)
        reconstituted = (
            r["allocation_total"] + r["selection_total"] + r["interaction_total"]
        )
        self.assertAlmostEqual(reconstituted, r["total_active_return"], places=9)

    def test_multi_period_cumulative_consistency(self):
        wa, wb, ra, rb = self._ten_adapter_inputs()
        history = [{"weights_actual": wa, "returns_actual": ra, "returns_bench": rb}]
        single = self.p.get_attribution_report(history, wb)
        multi = self.p.get_attribution_report(history * 5, wb)
        self.assertAlmostEqual(
            multi["total_active_return"], 5 * single["total_active_return"], places=10
        )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
