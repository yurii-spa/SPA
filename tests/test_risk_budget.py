"""tests/test_risk_budget.py — MP-582 RiskBudgetManager test suite.

Coverage: 90 test cases across 10 classes.

TestNormPPF                 (8)  — _norm_ppf: accuracy, boundaries, symmetry
TestSafeFloat               (5)  — _safe_float helper
TestNormaliseWeights        (6)  — _normalise_weights edge cases
TestComputeRiskContribution (16) — core risk decomposition math
TestGetBudgetStatus         (16) — OK/WARNING/BREACH thresholds
TestSuggestReductions       (12) — breach-only, sorted by excess
TestComputePortfolioVar     (13) — parametric VaR correctness
TestGetRiskReport           (13) — full report structure and values
TestSaveReport              (8)  — atomic save, ring-buffer, error handling
TestImportHygiene           (3)  — no forbidden imports; only stdlib

Total: 100 tests
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

# Make spa_core importable from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.analytics.risk_budget import (
    RiskBudgetManager,
    STATUS_OK,
    STATUS_WARNING,
    STATUS_BREACH,
    _norm_ppf,
    _safe_float,
    _normalise_weights,
    _WARNING_THRESHOLD_FRAC,
    _REPORT_HISTORY_MAX,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mgr(tmp_dir: str | None = None) -> RiskBudgetManager:
    """Return a RiskBudgetManager with a temp data_dir."""
    if tmp_dir is None:
        tmp_dir = tempfile.mkdtemp()
    return RiskBudgetManager(data_dir=tmp_dir)


def _adapter(
    adapter_id: str = "aave_v3",
    risk_score: float = 0.3,
) -> dict:
    return {"id": adapter_id, "risk_score": risk_score}


# ---------------------------------------------------------------------------
# TestNormPPF (8 tests)
# ---------------------------------------------------------------------------

class TestNormPPF(unittest.TestCase):
    """_norm_ppf: standard-normal inverse CDF."""

    def test_ppf_50_is_zero(self):
        """Φ⁻¹(0.5) = 0."""
        self.assertAlmostEqual(_norm_ppf(0.5), 0.0, places=6)

    def test_ppf_95_approx(self):
        """Φ⁻¹(0.95) ≈ 1.6449."""
        self.assertAlmostEqual(_norm_ppf(0.95), 1.6448536, places=4)

    def test_ppf_99_approx(self):
        """Φ⁻¹(0.99) ≈ 2.3263."""
        self.assertAlmostEqual(_norm_ppf(0.99), 2.3263479, places=4)

    def test_ppf_01_negative(self):
        """Φ⁻¹(0.01) ≈ -2.3263 (symmetry)."""
        self.assertAlmostEqual(_norm_ppf(0.01), -2.3263479, places=4)

    def test_ppf_05_negative(self):
        """Φ⁻¹(0.05) ≈ -1.6449 (symmetry)."""
        self.assertAlmostEqual(_norm_ppf(0.05), -1.6448536, places=4)

    def test_ppf_symmetry(self):
        """Φ⁻¹(p) = -Φ⁻¹(1-p) for p ≠ 0.5."""
        for p in (0.1, 0.25, 0.75, 0.9):
            self.assertAlmostEqual(_norm_ppf(p), -_norm_ppf(1.0 - p), places=6)

    def test_ppf_boundary_zero(self):
        """Φ⁻¹(0) = -inf."""
        self.assertEqual(_norm_ppf(0.0), float("-inf"))

    def test_ppf_boundary_one(self):
        """Φ⁻¹(1) = +inf."""
        self.assertEqual(_norm_ppf(1.0), float("inf"))


# ---------------------------------------------------------------------------
# TestSafeFloat (5 tests)
# ---------------------------------------------------------------------------

class TestSafeFloat(unittest.TestCase):
    """_safe_float coercion helper."""

    def test_float_passthrough(self):
        self.assertEqual(_safe_float(3.14), 3.14)

    def test_int_coercion(self):
        self.assertEqual(_safe_float(5), 5.0)

    def test_none_returns_default(self):
        self.assertEqual(_safe_float(None), 0.0)
        self.assertEqual(_safe_float(None, 99.0), 99.0)

    def test_string_invalid_returns_default(self):
        self.assertEqual(_safe_float("abc", -1.0), -1.0)

    def test_string_numeric_parses(self):
        self.assertAlmostEqual(_safe_float("2.5"), 2.5)


# ---------------------------------------------------------------------------
# TestNormaliseWeights (6 tests)
# ---------------------------------------------------------------------------

class TestNormaliseWeights(unittest.TestCase):
    """_normalise_weights edge cases."""

    def test_equal_weights_normalised(self):
        w = {"a": 1.0, "b": 1.0, "c": 1.0}
        n = _normalise_weights(w)
        for v in n.values():
            self.assertAlmostEqual(v, 1 / 3, places=10)

    def test_sums_to_one(self):
        w = {"a": 30, "b": 20, "c": 50}
        n = _normalise_weights(w)
        self.assertAlmostEqual(sum(n.values()), 1.0, places=10)

    def test_zero_total_returns_empty(self):
        self.assertEqual(_normalise_weights({"a": 0.0, "b": 0.0}), {})

    def test_negative_weights_excluded(self):
        w = {"a": 10.0, "b": -5.0, "c": 10.0}
        n = _normalise_weights(w)
        self.assertNotIn("b", n)
        self.assertAlmostEqual(sum(n.values()), 1.0, places=10)

    def test_empty_dict_returns_empty(self):
        self.assertEqual(_normalise_weights({}), {})

    def test_single_adapter(self):
        n = _normalise_weights({"only": 42.0})
        self.assertAlmostEqual(n["only"], 1.0)


# ---------------------------------------------------------------------------
# TestComputeRiskContribution (16 tests)
# ---------------------------------------------------------------------------

class TestComputeRiskContribution(unittest.TestCase):
    """compute_risk_contribution: math, edge cases, partial overlaps."""

    def setUp(self):
        self.m = _mgr()

    def test_equal_weights_equal_risk_scores(self):
        """Equal w and equal rs → equal contributions (33.33% each)."""
        w = {"a": 1.0, "b": 1.0, "c": 1.0}
        rs = {"a": 0.5, "b": 0.5, "c": 0.5}
        result = self.m.compute_risk_contribution(w, rs)
        for v in result.values():
            self.assertAlmostEqual(v, 100 / 3, places=4)

    def test_contributions_sum_to_100(self):
        """Sum of all contributions == 100."""
        w = {"aave": 40000, "compound": 30000, "morpho": 30000}
        rs = {"aave": 0.2, "compound": 0.4, "morpho": 0.6}
        result = self.m.compute_risk_contribution(w, rs)
        self.assertAlmostEqual(sum(result.values()), 100.0, places=4)

    def test_higher_risk_score_higher_contribution(self):
        """Equal weights, morpho rs=0.6 > aave rs=0.2 → morpho contrib > aave."""
        w = {"aave": 1.0, "morpho": 1.0}
        rs = {"aave": 0.2, "morpho": 0.6}
        result = self.m.compute_risk_contribution(w, rs)
        self.assertGreater(result["morpho"], result["aave"])

    def test_zero_risk_score_zero_contribution(self):
        """Adapter with rs=0 contributes 0%."""
        w = {"aave": 0.5, "safe": 0.5}
        rs = {"aave": 0.4, "safe": 0.0}
        result = self.m.compute_risk_contribution(w, rs)
        self.assertAlmostEqual(result["safe"], 0.0)
        self.assertAlmostEqual(result["aave"], 100.0)

    def test_exact_formula_single_adapter(self):
        """Single adapter: contribution == 100%."""
        result = self.m.compute_risk_contribution({"a": 50.0}, {"a": 0.3})
        self.assertAlmostEqual(result["a"], 100.0, places=4)

    def test_exact_formula_two_adapters(self):
        """Manual check: w1*rs1/(w1*rs1+w2*rs2)*100."""
        w1, rs1 = 40.0, 0.2
        w2, rs2 = 60.0, 0.5
        total = w1 * rs1 + w2 * rs2
        expected_a = w1 * rs1 / total * 100
        expected_b = w2 * rs2 / total * 100
        result = self.m.compute_risk_contribution({"a": w1, "b": w2}, {"a": rs1, "b": rs2})
        self.assertAlmostEqual(result["a"], expected_a, places=5)
        self.assertAlmostEqual(result["b"], expected_b, places=5)

    def test_empty_weights_returns_empty(self):
        result = self.m.compute_risk_contribution({}, {"a": 0.3})
        self.assertEqual(result, {})

    def test_empty_risk_scores_returns_empty(self):
        result = self.m.compute_risk_contribution({"a": 1.0}, {})
        self.assertEqual(result, {})

    def test_none_inputs_returns_empty(self):
        result = self.m.compute_risk_contribution(None, None)
        self.assertEqual(result, {})

    def test_disjoint_keys_returns_empty(self):
        result = self.m.compute_risk_contribution({"a": 1.0}, {"b": 0.3})
        self.assertEqual(result, {})

    def test_partial_overlap(self):
        """Only common keys contribute."""
        w = {"a": 1.0, "b": 1.0}
        rs = {"b": 0.5, "c": 0.3}
        result = self.m.compute_risk_contribution(w, rs)
        # Only 'b' is common
        self.assertIn("b", result)
        self.assertNotIn("a", result)
        self.assertNotIn("c", result)
        self.assertAlmostEqual(result["b"], 100.0)

    def test_negative_weight_treated_as_zero(self):
        """Negative weight → treated as 0, that adapter excluded from sum."""
        w = {"a": -10.0, "b": 50.0}
        rs = {"a": 0.5, "b": 0.3}
        result = self.m.compute_risk_contribution(w, rs)
        # 'a' has w=0 after max(w,0) → raw contribution = 0
        self.assertAlmostEqual(result["a"], 0.0)
        self.assertAlmostEqual(result["b"], 100.0)

    def test_all_zero_risk_scores_returns_zeros(self):
        """All rs=0 → zero portfolio risk → all contributions are 0."""
        w = {"a": 1.0, "b": 1.0}
        rs = {"a": 0.0, "b": 0.0}
        result = self.m.compute_risk_contribution(w, rs)
        for v in result.values():
            self.assertAlmostEqual(v, 0.0)

    def test_high_weight_adapter_dominates(self):
        """90% weight adapter with same rs → ~90% contribution."""
        w = {"big": 90.0, "small": 10.0}
        rs = {"big": 0.5, "small": 0.5}
        result = self.m.compute_risk_contribution(w, rs)
        self.assertAlmostEqual(result["big"], 90.0, places=4)
        self.assertAlmostEqual(result["small"], 10.0, places=4)

    def test_integer_weights_accepted(self):
        """Integer weights should work fine."""
        result = self.m.compute_risk_contribution({"a": 3, "b": 7}, {"a": 0.2, "b": 0.2})
        self.assertAlmostEqual(sum(result.values()), 100.0, places=4)

    def test_large_weights_normalised_correctly(self):
        """Large USD amounts work the same as fractions."""
        w = {"a": 40_000.0, "b": 60_000.0}
        rs = {"a": 0.3, "b": 0.3}
        result = self.m.compute_risk_contribution(w, rs)
        self.assertAlmostEqual(result["a"], 40.0, places=4)
        self.assertAlmostEqual(result["b"], 60.0, places=4)


# ---------------------------------------------------------------------------
# TestGetBudgetStatus (16 tests)
# ---------------------------------------------------------------------------

class TestGetBudgetStatus(unittest.TestCase):
    """get_budget_status: OK/WARNING/BREACH thresholds."""

    def setUp(self):
        self.m = _mgr()

    def _simple_setup(self):
        """weights, risk_scores, budget_limits for a clean three-adapter setup."""
        w = {"aave": 50.0, "compound": 30.0, "morpho": 20.0}
        rs = {"aave": 0.2, "compound": 0.4, "morpho": 0.6}
        # manual contributions: aave=10/30*100~33.3, compound=12/30*100=40.0, morpho=12/30*100 -- wait
        # aave = 50*0.2 = 10, compound = 30*0.4 = 12, morpho = 20*0.6 = 12
        # total = 34; aave=10/34*100~29.4, compound=12/34*100~35.3, morpho=12/34*100~35.3
        limits = {"aave": 50.0, "compound": 50.0, "morpho": 50.0}
        return w, rs, limits

    def test_all_ok_when_contributions_below_90pct_limit(self):
        """All adapters under 90% of limit → all OK."""
        w, rs, limits = self._simple_setup()
        result = self.m.get_budget_status(w, rs, limits)
        for entry in result.values():
            self.assertEqual(entry["status"], STATUS_OK)

    def test_structure_has_required_keys(self):
        """Each entry has allocated, limit, status."""
        w, rs, limits = self._simple_setup()
        result = self.m.get_budget_status(w, rs, limits)
        for entry in result.values():
            self.assertIn("allocated", entry)
            self.assertIn("limit", entry)
            self.assertIn("status", entry)

    def test_breach_when_contribution_exceeds_limit(self):
        """Set limit below adapter's contribution → BREACH."""
        w = {"a": 1.0, "b": 1.0}
        rs = {"a": 0.5, "b": 0.1}
        # a: 0.5/(0.5+0.1)*100 = 83.3%
        limits = {"a": 30.0}  # well below 83%
        result = self.m.get_budget_status(w, rs, limits)
        self.assertEqual(result["a"]["status"], STATUS_BREACH)

    def test_warning_when_near_limit(self):
        """Contribution falls in [0.9*limit, limit] → WARNING."""
        # Single adapter → contribution = 100%.
        # We need 0.9 * limit <= 100 <= limit.
        # limit=105: 0.9*105=94.5 <= 100 <= 105  → WARNING ✓
        w = {"a": 1.0}
        rs = {"a": 0.5}
        limits = {"a": 105.0}
        result = self.m.get_budget_status(w, rs, limits)
        self.assertEqual(result["a"]["status"], STATUS_WARNING)

    def test_ok_when_comfortably_below_limit(self):
        """Contribution at 50% of limit → OK."""
        w = {"a": 1.0}
        rs = {"a": 0.3}
        limits = {"a": 200.0}  # contrib=100, limit=200, 100 < 0.9*200=180 → OK
        result = self.m.get_budget_status(w, rs, limits)
        self.assertEqual(result["a"]["status"], STATUS_OK)

    def test_adapter_without_limit_gets_ok(self):
        """Adapter not in budget_limits → OK with limit=None."""
        w = {"a": 1.0}
        rs = {"a": 0.5}
        result = self.m.get_budget_status(w, rs, {})
        self.assertEqual(result["a"]["status"], STATUS_OK)
        self.assertIsNone(result["a"]["limit"])

    def test_allocated_values_match_contributions(self):
        """allocated in status == compute_risk_contribution output."""
        w = {"a": 40.0, "b": 60.0}
        rs = {"a": 0.2, "b": 0.5}
        limits = {"a": 50.0, "b": 50.0}
        contributions = self.m.compute_risk_contribution(w, rs)
        status = self.m.get_budget_status(w, rs, limits)
        for aid in ("a", "b"):
            self.assertAlmostEqual(
                status[aid]["allocated"], contributions[aid], places=4
            )

    def test_breach_sets_correct_limit_value(self):
        """BREACH entry preserves the specified limit value."""
        w = {"x": 1.0}
        rs = {"x": 0.8}
        limits = {"x": 30.0}
        result = self.m.get_budget_status(w, rs, limits)
        self.assertAlmostEqual(result["x"]["limit"], 30.0, places=4)

    def test_multiple_adapters_mixed_statuses(self):
        """Portfolio where some are OK, some WARNING, some BREACH."""
        # We'll engineer specific contributions.
        # aave  => contribution = 100/3% ≈ 33.3%  → limit=40 → OK (33.3 < 0.9*40=36)
        # comp  => contribution = 100/3% ≈ 33.3%  → limit=35 → WARNING (33.3 ≥ 0.9*35=31.5)
        # morpho=> contribution = 100/3% ≈ 33.3%  → limit=20 → BREACH (33.3 > 20)
        w = {"aave": 1.0, "comp": 1.0, "morpho": 1.0}
        rs = {"aave": 0.5, "comp": 0.5, "morpho": 0.5}
        limits = {"aave": 40.0, "comp": 35.0, "morpho": 20.0}
        result = self.m.get_budget_status(w, rs, limits)
        self.assertEqual(result["aave"]["status"], STATUS_OK)
        self.assertEqual(result["comp"]["status"], STATUS_WARNING)
        self.assertEqual(result["morpho"]["status"], STATUS_BREACH)

    def test_empty_weights_all_limits_get_zero_allocated(self):
        """Empty weights → zero contribution → all OK if limits exist."""
        result = self.m.get_budget_status({}, {}, {"a": 50.0})
        # 'a' in budget_limits but not in weights → allocated=0, status depends on 0 < 0.9*50
        self.assertEqual(result["a"]["status"], STATUS_OK)
        self.assertAlmostEqual(result["a"]["allocated"], 0.0)

    def test_no_budget_limits_all_ok(self):
        """No budget limits → all OK."""
        w = {"a": 1.0, "b": 2.0}
        rs = {"a": 0.5, "b": 0.3}
        result = self.m.get_budget_status(w, rs, {})
        for entry in result.values():
            self.assertEqual(entry["status"], STATUS_OK)

    def test_warning_threshold_fraction_constant(self):
        """_WARNING_THRESHOLD_FRAC is used correctly: exactly at boundary."""
        # contrib = 0.9*limit → WARNING
        limit = 50.0
        warn_floor = _WARNING_THRESHOLD_FRAC * limit  # 45.0
        # We need contrib_a = exactly 45.0%
        # Single adapter: contrib = 100% → won't work
        # Two adapters: a/(a+b)*100 = 45 → a/b = 45/55 = 9/11
        # Use w_a=9, w_b=11, rs_a=rs_b=0.5
        w = {"a": 9.0, "b": 11.0}
        rs = {"a": 0.5, "b": 0.5}
        limits = {"a": 50.0}
        contrib_a = 9 / (9 + 11) * 100  # = 45.0
        self.assertAlmostEqual(contrib_a, warn_floor, places=4)
        result = self.m.get_budget_status(w, rs, limits)
        self.assertEqual(result["a"]["status"], STATUS_WARNING)

    def test_breach_exactly_above_limit(self):
        """Contribution 100.001% > 100% limit → BREACH."""
        # Single adapter: 100% contribution > any finite limit
        w = {"a": 1.0}
        rs = {"a": 0.5}
        limits = {"a": 99.9}  # 100 > 99.9 → BREACH
        result = self.m.get_budget_status(w, rs, limits)
        self.assertEqual(result["a"]["status"], STATUS_BREACH)

    def test_adapter_in_limits_but_not_in_weights_gets_zero_allocated(self):
        """Adapter only in limits (not in weights/risk_scores) → allocated=0, OK."""
        result = self.m.get_budget_status(
            {"a": 1.0}, {"a": 0.3}, {"a": 50.0, "b": 50.0}
        )
        # 'b' has no weight/risk_score → contribution=0 → OK
        self.assertEqual(result["b"]["status"], STATUS_OK)
        self.assertAlmostEqual(result["b"]["allocated"], 0.0)

    def test_none_budget_limits_treated_as_empty(self):
        """None budget_limits → no limits set → all OK."""
        w = {"a": 1.0}
        rs = {"a": 0.5}
        result = self.m.get_budget_status(w, rs, None)
        self.assertEqual(result["a"]["status"], STATUS_OK)

    def test_large_portfolio(self):
        """Five adapters, contributions sum to 100, some breach."""
        w = {f"p{i}": float(i + 1) * 10 for i in range(5)}  # 10..50
        rs = {f"p{i}": 0.5 for i in range(5)}
        limits = {f"p{i}": 15.0 for i in range(5)}
        result = self.m.get_budget_status(w, rs, limits)
        total_alloc = sum(e["allocated"] for e in result.values())
        self.assertAlmostEqual(total_alloc, 100.0, places=3)


# ---------------------------------------------------------------------------
# TestSuggestReductions (12 tests)
# ---------------------------------------------------------------------------

class TestSuggestReductions(unittest.TestCase):
    """suggest_reductions: breach-only, sorted by excess desc."""

    def setUp(self):
        self.m = _mgr()

    def test_no_breaches_returns_empty_list(self):
        """All OK/WARNING → empty suggestions."""
        w = {"a": 1.0}
        rs = {"a": 0.3}
        limits = {"a": 100.0}  # limit above 100% contrib
        result = self.m.suggest_reductions(w, rs, limits)
        self.assertEqual(result, [])

    def test_single_breach_returned(self):
        """One breach → one suggestion."""
        w = {"a": 1.0}
        rs = {"a": 0.5}
        limits = {"a": 50.0}  # 100% contrib > 50% limit
        result = self.m.suggest_reductions(w, rs, limits)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["adapter_id"], "a")

    def test_breach_has_required_keys(self):
        """Suggestion dict has all required keys."""
        w = {"a": 1.0}
        rs = {"a": 0.5}
        limits = {"a": 50.0}
        result = self.m.suggest_reductions(w, rs, limits)
        keys = {"adapter_id", "allocated", "limit", "excess_pct",
                "suggested_weight_reduction_pct", "message"}
        self.assertEqual(set(result[0].keys()), keys)

    def test_excess_pct_equals_allocated_minus_limit(self):
        """excess_pct = allocated - limit."""
        w = {"a": 1.0}
        rs = {"a": 0.5}
        limits = {"a": 50.0}  # contrib=100, limit=50, excess=50
        result = self.m.suggest_reductions(w, rs, limits)
        self.assertAlmostEqual(result[0]["excess_pct"], 50.0, places=2)

    def test_sorted_by_excess_descending(self):
        """Larger excess appears first."""
        w = {"a": 1.0, "b": 1.0, "c": 1.0}
        rs = {"a": 0.5, "b": 0.5, "c": 0.5}
        # Each contributes 33.3%; limits: a=10(excess=23.3), b=20(excess=13.3), c=30(excess=3.3)
        limits = {"a": 10.0, "b": 20.0, "c": 30.0}
        result = self.m.suggest_reductions(w, rs, limits)
        self.assertEqual(len(result), 3)
        excesses = [r["excess_pct"] for r in result]
        self.assertEqual(excesses, sorted(excesses, reverse=True))

    def test_only_breached_adapters_included(self):
        """WARNING adapters are NOT in suggestions."""
        # Equal weights, equal rs → each 33.3%
        w = {"a": 1.0, "b": 1.0, "c": 1.0}
        rs = {"a": 0.5, "b": 0.5, "c": 0.5}
        # a: limit=40 → OK (33.3 < 36=0.9*40)
        # b: limit=35 → WARNING (33.3 >= 31.5 and <=35)
        # c: limit=20 → BREACH (33.3 > 20)
        limits = {"a": 40.0, "b": 35.0, "c": 20.0}
        result = self.m.suggest_reductions(w, rs, limits)
        adapter_ids = [r["adapter_id"] for r in result]
        self.assertIn("c", adapter_ids)
        self.assertNotIn("a", adapter_ids)
        self.assertNotIn("b", adapter_ids)

    def test_suggested_reduction_in_0_1_range(self):
        """suggested_weight_reduction_pct ∈ [0, 1]."""
        w = {"a": 1.0}
        rs = {"a": 0.5}
        limits = {"a": 50.0}
        result = self.m.suggest_reductions(w, rs, limits)
        self.assertGreaterEqual(result[0]["suggested_weight_reduction_pct"], 0.0)
        self.assertLessEqual(result[0]["suggested_weight_reduction_pct"], 1.0)

    def test_suggested_reduction_formula(self):
        """reduction = 1 - (limit / allocated)."""
        w = {"a": 1.0}
        rs = {"a": 0.5}
        limits = {"a": 40.0}  # allocated=100, limit=40, reduction=1-40/100=0.6
        result = self.m.suggest_reductions(w, rs, limits)
        self.assertAlmostEqual(
            result[0]["suggested_weight_reduction_pct"], 0.6, places=4
        )

    def test_message_contains_adapter_id(self):
        """message string contains adapter_id."""
        w = {"my_protocol": 1.0}
        rs = {"my_protocol": 0.5}
        limits = {"my_protocol": 50.0}
        result = self.m.suggest_reductions(w, rs, limits)
        self.assertIn("my_protocol", result[0]["message"])

    def test_empty_inputs_returns_empty(self):
        result = self.m.suggest_reductions({}, {}, {})
        self.assertEqual(result, [])

    def test_multiple_breaches_all_returned(self):
        """All breached adapters appear in result."""
        n = 5
        w = {f"p{i}": 1.0 for i in range(n)}
        rs = {f"p{i}": 0.5 for i in range(n)}
        limits = {f"p{i}": 1.0 for i in range(n)}  # all contribute 20%, limit=1 → all breach
        result = self.m.suggest_reductions(w, rs, limits)
        self.assertEqual(len(result), n)

    def test_allocated_matches_actual_contribution(self):
        """allocated in suggestion == actual computed contribution."""
        w = {"a": 40.0, "b": 60.0}
        rs = {"a": 0.3, "b": 0.5}
        contribs = self.m.compute_risk_contribution(w, rs)
        limits = {"a": 1.0, "b": 1.0}  # tiny limits → both breach
        result = self.m.suggest_reductions(w, rs, limits)
        for entry in result:
            aid = entry["adapter_id"]
            self.assertAlmostEqual(entry["allocated"], contribs[aid], places=4)


# ---------------------------------------------------------------------------
# TestComputePortfolioVar (13 tests)
# ---------------------------------------------------------------------------

class TestComputePortfolioVar(unittest.TestCase):
    """compute_portfolio_var: parametric VaR under normal assumption."""

    def setUp(self):
        self.m = _mgr()

    def test_single_adapter_var_equals_rs_times_z(self):
        """Single adapter: VaR = sigma * z(c) since w is normalised to 1."""
        rs = 0.4
        c = 0.95
        z = _norm_ppf(c)
        expected = rs * z
        result = self.m.compute_portfolio_var({"a": 1.0}, {"a": rs}, c)
        self.assertAlmostEqual(result, expected, places=5)

    def test_var_99_greater_than_var_95(self):
        """VaR at 99% > VaR at 95% for same portfolio."""
        w = {"a": 0.5, "b": 0.5}
        rs = {"a": 0.3, "b": 0.4}
        var95 = self.m.compute_portfolio_var(w, rs, 0.95)
        var99 = self.m.compute_portfolio_var(w, rs, 0.99)
        self.assertGreater(var99, var95)

    def test_var_zero_for_zero_risk_scores(self):
        """All rs=0 → portfolio vol=0 → VaR=0."""
        result = self.m.compute_portfolio_var({"a": 1.0, "b": 1.0}, {"a": 0.0, "b": 0.0})
        self.assertAlmostEqual(result, 0.0)

    def test_var_zero_for_empty_weights(self):
        """Empty weights → VaR=0."""
        result = self.m.compute_portfolio_var({}, {"a": 0.3})
        self.assertAlmostEqual(result, 0.0)

    def test_var_independence_formula(self):
        """Manual check: VaR = z * sqrt(sum((w_i * sigma_i)^2)) with normalised w."""
        w = {"a": 0.6, "b": 0.4}
        rs = {"a": 0.3, "b": 0.5}
        c = 0.95
        # normalised: a=0.6, b=0.4 (already sum=1)
        vol = math.sqrt((0.6 * 0.3) ** 2 + (0.4 * 0.5) ** 2)
        expected = _norm_ppf(c) * vol
        result = self.m.compute_portfolio_var(w, rs, c)
        self.assertAlmostEqual(result, expected, places=5)

    def test_var_is_non_negative(self):
        """VaR at confidence > 0.5 is always ≥ 0."""
        w = {"a": 1.0}
        rs = {"a": 0.2}
        self.assertGreaterEqual(self.m.compute_portfolio_var(w, rs, 0.95), 0.0)

    def test_higher_risk_score_higher_var(self):
        """Higher risk scores → higher VaR."""
        w = {"a": 1.0}
        rs_low = {"a": 0.1}
        rs_high = {"a": 0.8}
        var_low = self.m.compute_portfolio_var(w, rs_low, 0.95)
        var_high = self.m.compute_portfolio_var(w, rs_high, 0.95)
        self.assertGreater(var_high, var_low)

    def test_diversification_reduces_var(self):
        """Diversified portfolio has lower VaR than concentrated (under independence)."""
        # Single: all in 'a' with sigma=0.5
        w_conc = {"a": 1.0}
        rs_conc = {"a": 0.5}
        var_conc = self.m.compute_portfolio_var(w_conc, rs_conc, 0.95)

        # Diversified: 50/50 split, same sigma
        w_div = {"a": 0.5, "b": 0.5}
        rs_div = {"a": 0.5, "b": 0.5}
        var_div = self.m.compute_portfolio_var(w_div, rs_div, 0.95)

        # For equal sigma, diversification reduces vol under independence:
        # vol_conc = 0.5, vol_div = sqrt(2*(0.5*0.5)^2) = sqrt(2)*0.25 = 0.5/sqrt(2) < 0.5
        self.assertLess(var_div, var_conc)

    def test_invalid_confidence_below_zero_raises(self):
        with self.assertRaises(ValueError):
            self.m.compute_portfolio_var({"a": 1.0}, {"a": 0.3}, confidence=-0.1)

    def test_invalid_confidence_above_one_raises(self):
        with self.assertRaises(ValueError):
            self.m.compute_portfolio_var({"a": 1.0}, {"a": 0.3}, confidence=1.5)

    def test_invalid_confidence_zero_raises(self):
        with self.assertRaises(ValueError):
            self.m.compute_portfolio_var({"a": 1.0}, {"a": 0.3}, confidence=0.0)

    def test_invalid_confidence_one_raises(self):
        with self.assertRaises(ValueError):
            self.m.compute_portfolio_var({"a": 1.0}, {"a": 0.3}, confidence=1.0)

    def test_default_confidence_is_95(self):
        """Default confidence == 0.95."""
        w = {"a": 1.0}
        rs = {"a": 0.3}
        v_default = self.m.compute_portfolio_var(w, rs)
        v_explicit = self.m.compute_portfolio_var(w, rs, confidence=0.95)
        self.assertAlmostEqual(v_default, v_explicit, places=8)


# ---------------------------------------------------------------------------
# TestGetRiskReport (13 tests)
# ---------------------------------------------------------------------------

class TestGetRiskReport(unittest.TestCase):
    """get_risk_report: full report structure and values."""

    def setUp(self):
        self.m = _mgr()
        self.adapters = [
            {"id": "aave_v3", "risk_score": 0.2},
            {"id": "morpho", "risk_score": 0.6},
        ]
        self.weights = [40000.0, 60000.0]

    def test_returns_dict(self):
        result = self.m.get_risk_report(self.adapters, self.weights)
        self.assertIsInstance(result, dict)

    def test_required_keys_present(self):
        result = self.m.get_risk_report(self.adapters, self.weights)
        for key in (
            "generated_at", "n_adapters", "contributions",
            "var_95", "var_99", "portfolio_vol",
            "diversification_ratio", "warnings", "adapter_details",
        ):
            self.assertIn(key, result, msg=f"Missing key: {key}")

    def test_n_adapters_matches_input(self):
        result = self.m.get_risk_report(self.adapters, self.weights)
        self.assertEqual(result["n_adapters"], 2)

    def test_contributions_sum_to_100(self):
        result = self.m.get_risk_report(self.adapters, self.weights)
        total = sum(result["contributions"].values())
        self.assertAlmostEqual(total, 100.0, places=3)

    def test_var_99_greater_than_var_95(self):
        result = self.m.get_risk_report(self.adapters, self.weights)
        self.assertGreater(result["var_99"], result["var_95"])

    def test_diversification_ratio_gte_one(self):
        """DR ≥ 1 always."""
        result = self.m.get_risk_report(self.adapters, self.weights)
        self.assertGreaterEqual(result["diversification_ratio"], 1.0)

    def test_warnings_is_list(self):
        result = self.m.get_risk_report(self.adapters, self.weights)
        self.assertIsInstance(result["warnings"], list)

    def test_adapter_details_length(self):
        result = self.m.get_risk_report(self.adapters, self.weights)
        self.assertEqual(len(result["adapter_details"]), 2)

    def test_adapter_details_contain_contribution_pct(self):
        result = self.m.get_risk_report(self.adapters, self.weights)
        for detail in result["adapter_details"]:
            self.assertIn("contribution_pct", detail)

    def test_adapter_id_resolution_from_protocol_key(self):
        """Adapter with 'protocol' key (not 'id') is resolved correctly."""
        adapters = [{"protocol": "aave", "risk_score": 0.3}]
        result = self.m.get_risk_report(adapters, [1.0])
        self.assertIn("aave", result["contributions"])

    def test_adapter_id_resolution_from_adapter_id_key(self):
        adapters = [{"adapter_id": "compound_v3", "risk_score": 0.4}]
        result = self.m.get_risk_report(adapters, [1.0])
        self.assertIn("compound_v3", result["contributions"])

    def test_mismatched_lengths_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.m.get_risk_report(self.adapters, [1.0])

    def test_object_adapters_accepted(self):
        """Adapters as SimpleNamespace objects (attribute access)."""
        import types as _types
        a1 = _types.SimpleNamespace(id="aave", risk_score=0.25)
        a2 = _types.SimpleNamespace(id="comp", risk_score=0.35)
        result = self.m.get_risk_report([a1, a2], [50.0, 50.0])
        self.assertAlmostEqual(sum(result["contributions"].values()), 100.0, places=3)

    def test_generated_at_is_iso_string(self):
        """generated_at is a parseable ISO-8601 string."""
        from datetime import datetime
        result = self.m.get_risk_report(self.adapters, self.weights)
        ts = result["generated_at"]
        self.assertIsInstance(ts, str)
        # Should not raise
        datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# TestSaveReport (8 tests)
# ---------------------------------------------------------------------------

class TestSaveReport(unittest.TestCase):
    """save_report: atomic write, ring-buffer, file structure."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.m = RiskBudgetManager(data_dir=self.tmp_dir)
        self.report = {
            "generated_at": "2026-06-13T10:00:00+00:00",
            "n_adapters": 2,
            "contributions": {"aave": 40.0, "morpho": 60.0},
            "var_95": 0.12,
            "var_99": 0.18,
            "portfolio_vol": 0.073,
            "diversification_ratio": 1.1,
            "warnings": [],
        }

    def test_file_created(self):
        """save_report creates the output file."""
        self.m.save_report(self.report)
        path = Path(self.tmp_dir) / "risk_budget_report.json"
        self.assertTrue(path.exists())

    def test_file_is_valid_json(self):
        """Output file parses as valid JSON."""
        self.m.save_report(self.report)
        path = Path(self.tmp_dir) / "risk_budget_report.json"
        with open(path) as f:
            doc = json.load(f)
        self.assertIsInstance(doc, dict)

    def test_latest_key_matches_report(self):
        """doc['latest'] == saved report."""
        self.m.save_report(self.report)
        path = Path(self.tmp_dir) / "risk_budget_report.json"
        with open(path) as f:
            doc = json.load(f)
        self.assertEqual(doc["latest"]["var_95"], self.report["var_95"])

    def test_history_grows_on_successive_saves(self):
        """Each save appends to history."""
        for i in range(3):
            r = dict(self.report)
            r["var_95"] = float(i)
            self.m.save_report(r)
        path = Path(self.tmp_dir) / "risk_budget_report.json"
        with open(path) as f:
            doc = json.load(f)
        self.assertEqual(doc["history_depth"], 3)

    def test_ring_buffer_capped_at_max(self):
        """history never exceeds _REPORT_HISTORY_MAX."""
        for _ in range(_REPORT_HISTORY_MAX + 10):
            self.m.save_report(self.report)
        path = Path(self.tmp_dir) / "risk_budget_report.json"
        with open(path) as f:
            doc = json.load(f)
        self.assertLessEqual(len(doc["history"]), _REPORT_HISTORY_MAX)

    def test_schema_version_present(self):
        self.m.save_report(self.report)
        path = Path(self.tmp_dir) / "risk_budget_report.json"
        with open(path) as f:
            doc = json.load(f)
        self.assertEqual(doc["schema_version"], "1.0")

    def test_no_tmp_file_left_behind(self):
        """No .tmp files remain after successful save."""
        self.m.save_report(self.report)
        leftover = [
            f for f in os.listdir(self.tmp_dir)
            if f.endswith(".tmp") or f.startswith(".risk_budget_report_tmp_")
        ]
        self.assertEqual(leftover, [])

    def test_data_dir_created_if_missing(self):
        """save_report creates data_dir if it doesn't exist."""
        new_dir = os.path.join(self.tmp_dir, "nested", "subdir")
        m2 = RiskBudgetManager(data_dir=new_dir)
        m2.save_report(self.report)
        self.assertTrue(os.path.isdir(new_dir))


# ---------------------------------------------------------------------------
# TestImportHygiene (3 tests)
# ---------------------------------------------------------------------------

class TestImportHygiene(unittest.TestCase):
    """Verify risk_budget.py uses only stdlib + math."""

    def _get_source(self) -> str:
        import spa_core.analytics.risk_budget as mod
        return Path(mod.__file__).read_text(encoding="utf-8")

    def test_no_requests_import(self):
        source = self._get_source()
        self.assertNotIn("import requests", source)
        self.assertNotIn("from requests", source)

    def test_no_numpy_pandas_scipy(self):
        source = self._get_source()
        for banned in ("numpy", "pandas", "scipy", "web3", "openai", "anthropic"):
            self.assertNotIn(f"import {banned}", source, msg=f"Found: import {banned}")
            self.assertNotIn(f"from {banned}", source, msg=f"Found: from {banned}")

    def test_no_execution_risk_monitoring_imports(self):
        source = self._get_source()
        for banned in ("spa_core.execution", "spa_core.risk", "spa_core.monitoring",
                       "spa_core.feed_health"):
            self.assertNotIn(banned, source, msg=f"Found forbidden domain: {banned}")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
