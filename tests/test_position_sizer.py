"""Tests for spa_core.paper_trading.position_sizer (MP-576).

Run:
    python3 -m pytest tests/test_position_sizer.py -v
    python3 -m unittest tests.test_position_sizer
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

# ─── ensure repo root is on sys.path ──────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading.position_sizer import (
    DEFAULT_MAX_SINGLE,
    MIN_CASH_BUFFER,
    MIN_ELIGIBLE_APY,
    MIN_ELIGIBLE_TVL,
    REPORT_FILENAME,
    REPORT_HISTORY_MAX,
    TIER_CAP_T1_PER_PROTOCOL,
    TIER_CAP_T1_TOTAL,
    TIER_CAP_T2_PER_PROTOCOL,
    TIER_CAP_T2_TOTAL,
    TIER_CAP_T3_PER_PROTOCOL,
    TIER_CAP_T3_TOTAL,
    PositionSizer,
    _normalise_weights,
    _safe_float,
)


# ─── Shared fixtures ──────────────────────────────────────────────────────────

def _t1_adapters() -> Dict[str, Any]:
    return {
        "aave_v3":     {"apy": 3.5,  "tvl": 9_000_000_000},
        "compound_v3": {"apy": 4.8,  "tvl": 2_000_000_000},
    }


def _mixed_adapters() -> Dict[str, Any]:
    return {
        "aave_v3":           {"apy": 3.5,  "tvl": 9_000_000_000},
        "compound_v3":       {"apy": 4.8,  "tvl": 2_000_000_000},
        "morpho_steakhouse": {"apy": 6.5,  "tvl": 800_000_000},
        "yearn_v3":          {"apy": 5.2,  "tvl": 300_000_000},
        "euler_v2":          {"apy": 4.1,  "tvl": 150_000_000},
    }


def _mixed_tiers() -> Dict[str, str]:
    return {
        "aave_v3":           "T1",
        "compound_v3":       "T1",
        "morpho_steakhouse": "T1",
        "yearn_v3":          "T2",
        "euler_v2":          "T2",
    }


def _default_risk_limits() -> Dict[str, Any]:
    return {
        "max_single":      0.40,
        "min_cash_buffer": 0.05,
        "min_apy":         1.0,
        "max_apy":         30.0,
        "min_tvl":         5_000_000.0,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 1. Module-level constants
# ═════════════════════════════════════════════════════════════════════════════

class TestConstants(unittest.TestCase):
    """Verify exported constants have the correct values (aligns with RiskPolicy v1.0 / ADR-019/020)."""

    def test_tier_cap_t1_per_protocol(self):
        self.assertAlmostEqual(TIER_CAP_T1_PER_PROTOCOL, 0.60)

    def test_tier_cap_t2_per_protocol(self):
        self.assertAlmostEqual(TIER_CAP_T2_PER_PROTOCOL, 0.25)

    def test_tier_cap_t3_per_protocol(self):
        self.assertAlmostEqual(TIER_CAP_T3_PER_PROTOCOL, 0.10)

    def test_tier_cap_t1_total(self):
        self.assertAlmostEqual(TIER_CAP_T1_TOTAL, 0.60)

    def test_tier_cap_t2_total(self):
        self.assertAlmostEqual(TIER_CAP_T2_TOTAL, 0.50)

    def test_tier_cap_t3_total(self):
        self.assertAlmostEqual(TIER_CAP_T3_TOTAL, 0.15)

    def test_default_max_single(self):
        self.assertAlmostEqual(DEFAULT_MAX_SINGLE, 0.40)

    def test_min_cash_buffer(self):
        self.assertAlmostEqual(MIN_CASH_BUFFER, 0.05)

    def test_min_eligible_apy(self):
        self.assertAlmostEqual(MIN_ELIGIBLE_APY, 1.0)

    def test_min_eligible_tvl(self):
        self.assertAlmostEqual(MIN_ELIGIBLE_TVL, 5_000_000.0)


# ═════════════════════════════════════════════════════════════════════════════
# 2. Helper functions
# ═════════════════════════════════════════════════════════════════════════════

class TestHelpers(unittest.TestCase):
    def test_safe_float_numeric(self):
        self.assertAlmostEqual(_safe_float(3.14), 3.14)

    def test_safe_float_string(self):
        self.assertAlmostEqual(_safe_float("2.5"), 2.5)

    def test_safe_float_none(self):
        self.assertAlmostEqual(_safe_float(None), 0.0)

    def test_safe_float_bad_string(self):
        self.assertAlmostEqual(_safe_float("abc"), 0.0)

    def test_safe_float_custom_default(self):
        self.assertAlmostEqual(_safe_float(None, default=99.0), 99.0)

    def test_normalise_weights_sums_to_one(self):
        w = {"a": 2.0, "b": 3.0}
        n = _normalise_weights(w)
        self.assertAlmostEqual(sum(n.values()), 1.0)

    def test_normalise_weights_proportions(self):
        w = {"a": 2.0, "b": 2.0}
        n = _normalise_weights(w)
        self.assertAlmostEqual(n["a"], 0.5)
        self.assertAlmostEqual(n["b"], 0.5)

    def test_normalise_weights_zero_total(self):
        w = {"a": 0.0, "b": 0.0}
        n = _normalise_weights(w)
        self.assertEqual(n, {"a": 0.0, "b": 0.0})


# ═════════════════════════════════════════════════════════════════════════════
# 3. PositionSizer — initialisation
# ═════════════════════════════════════════════════════════════════════════════

class TestPositionSizerInit(unittest.TestCase):
    def test_default_init(self):
        ps = PositionSizer()
        self.assertIsInstance(ps, PositionSizer)

    def test_default_per_proto_caps(self):
        ps = PositionSizer()
        self.assertAlmostEqual(ps._per_proto_caps["T1"], 0.60)
        self.assertAlmostEqual(ps._per_proto_caps["T2"], 0.25)
        self.assertAlmostEqual(ps._per_proto_caps["T3"], 0.10)

    def test_default_total_caps(self):
        ps = PositionSizer()
        self.assertAlmostEqual(ps._total_caps["T1"], 0.60)
        self.assertAlmostEqual(ps._total_caps["T2"], 0.50)
        self.assertAlmostEqual(ps._total_caps["T3"], 0.15)

    def test_default_cash_buffer(self):
        ps = PositionSizer()
        self.assertAlmostEqual(ps._min_cash_buffer, 0.05)

    def test_custom_per_proto_caps(self):
        ps = PositionSizer(tier_caps_per_protocol={"T2": 0.15})
        self.assertAlmostEqual(ps._per_proto_caps["T2"], 0.15)

    def test_custom_total_caps(self):
        ps = PositionSizer(tier_caps_total={"T3": 0.10})
        self.assertAlmostEqual(ps._total_caps["T3"], 0.10)

    def test_custom_cash_buffer(self):
        ps = PositionSizer(min_cash_buffer=0.10)
        self.assertAlmostEqual(ps._min_cash_buffer, 0.10)


# ═════════════════════════════════════════════════════════════════════════════
# 4. compute_target_weights
# ═════════════════════════════════════════════════════════════════════════════

class TestComputeTargetWeights(unittest.TestCase):
    def setUp(self):
        self.ps = PositionSizer()
        self.pv = 100_000.0

    def test_returns_dict(self):
        w = self.ps.compute_target_weights(_t1_adapters(), self.pv)
        self.assertIsInstance(w, dict)

    def test_all_keys_present(self):
        w = self.ps.compute_target_weights(_t1_adapters(), self.pv)
        self.assertEqual(set(w.keys()), set(_t1_adapters().keys()))

    def test_weights_non_negative(self):
        w = self.ps.compute_target_weights(_mixed_adapters(), self.pv)
        for v in w.values():
            self.assertGreaterEqual(v, 0.0)

    def test_weights_sum_le_one(self):
        w = self.ps.compute_target_weights(_mixed_adapters(), self.pv)
        self.assertLessEqual(sum(w.values()), 1.0 + 1e-9)

    def test_cash_buffer_respected(self):
        rl = {"min_cash_buffer": 0.10}
        w = self.ps.compute_target_weights(_mixed_adapters(), self.pv, rl)
        self.assertLessEqual(sum(w.values()), 0.90 + 1e-9)

    def test_max_single_respected(self):
        rl = {"max_single": 0.30}
        w = self.ps.compute_target_weights(_mixed_adapters(), self.pv, rl)
        for v in w.values():
            self.assertLessEqual(v, 0.30 + 1e-9)

    def test_ineligible_apy_too_low(self):
        adapters = {"low_apy": {"apy": 0.5, "tvl": 1_000_000_000}}
        w = self.ps.compute_target_weights(adapters, self.pv)
        self.assertAlmostEqual(w["low_apy"], 0.0)

    def test_ineligible_apy_too_high(self):
        adapters = {"high_apy": {"apy": 35.0, "tvl": 1_000_000_000}}
        w = self.ps.compute_target_weights(adapters, self.pv)
        self.assertAlmostEqual(w["high_apy"], 0.0)

    def test_ineligible_tvl_too_low(self):
        adapters = {"small_tvl": {"apy": 5.0, "tvl": 100_000}}
        w = self.ps.compute_target_weights(adapters, self.pv)
        self.assertAlmostEqual(w["small_tvl"], 0.0)

    def test_excluded_adapter_gets_zero(self):
        rl = {"excluded": ["aave_v3"]}
        w = self.ps.compute_target_weights(_t1_adapters(), self.pv, rl)
        self.assertAlmostEqual(w["aave_v3"], 0.0)

    def test_no_eligible_adapters_all_zero(self):
        adapters = {"x": {"apy": 0.0, "tvl": 0.0}}
        w = self.ps.compute_target_weights(adapters, self.pv)
        self.assertAlmostEqual(w["x"], 0.0)

    def test_higher_apy_gets_higher_weight(self):
        adapters = {
            "low":  {"apy": 2.0, "tvl": 1_000_000_000},
            "high": {"apy": 8.0, "tvl": 1_000_000_000},
        }
        w = self.ps.compute_target_weights(adapters, self.pv)
        self.assertGreater(w["high"], w["low"])

    def test_equal_apy_equal_weight(self):
        adapters = {
            "a": {"apy": 5.0, "tvl": 1_000_000_000},
            "b": {"apy": 5.0, "tvl": 1_000_000_000},
        }
        w = self.ps.compute_target_weights(adapters, self.pv)
        self.assertAlmostEqual(w["a"], w["b"], places=6)

    def test_missing_apy_field_treated_as_zero(self):
        adapters = {"no_apy": {"tvl": 1_000_000_000}}
        w = self.ps.compute_target_weights(adapters, self.pv)
        self.assertAlmostEqual(w["no_apy"], 0.0)

    def test_missing_tvl_field_treated_as_zero(self):
        adapters = {"no_tvl": {"apy": 5.0}}
        w = self.ps.compute_target_weights(adapters, self.pv)
        self.assertAlmostEqual(w["no_tvl"], 0.0)

    def test_empty_adapters_returns_empty(self):
        w = self.ps.compute_target_weights({}, self.pv)
        self.assertEqual(w, {})

    def test_portfolio_value_does_not_change_weights(self):
        w1 = self.ps.compute_target_weights(_t1_adapters(), 100_000.0)
        w2 = self.ps.compute_target_weights(_t1_adapters(), 500_000.0)
        for aid in w1:
            self.assertAlmostEqual(w1[aid], w2[aid], places=6)

    def test_custom_min_tvl_in_risk_limits(self):
        adapters = {"tiny": {"apy": 5.0, "tvl": 1_000_000}}
        rl = {"min_tvl": 500_000.0}
        w = self.ps.compute_target_weights(adapters, self.pv, rl)
        self.assertGreater(w["tiny"], 0.0)

    def test_custom_min_apy_in_risk_limits(self):
        adapters = {"borderline": {"apy": 0.8, "tvl": 1_000_000_000}}
        rl = {"min_apy": 0.5}
        w = self.ps.compute_target_weights(adapters, self.pv, rl)
        self.assertGreater(w["borderline"], 0.0)


# ═════════════════════════════════════════════════════════════════════════════
# 5. compute_dollar_allocations
# ═════════════════════════════════════════════════════════════════════════════

class TestComputeDollarAllocations(unittest.TestCase):
    def setUp(self):
        self.ps = PositionSizer()

    def test_returns_dict(self):
        allocs = self.ps.compute_dollar_allocations({"a": 0.5, "b": 0.3}, 100_000.0)
        self.assertIsInstance(allocs, dict)

    def test_same_keys_as_weights(self):
        weights = {"a": 0.4, "b": 0.3, "c": 0.2}
        allocs = self.ps.compute_dollar_allocations(weights, 100_000.0)
        self.assertEqual(set(allocs.keys()), set(weights.keys()))

    def test_dollar_value_correct(self):
        allocs = self.ps.compute_dollar_allocations({"a": 0.40}, 100_000.0)
        self.assertAlmostEqual(allocs["a"], 40_000.0, places=2)

    def test_zero_weight_zero_dollars(self):
        allocs = self.ps.compute_dollar_allocations({"a": 0.0}, 100_000.0)
        self.assertAlmostEqual(allocs["a"], 0.0)

    def test_proportional_to_portfolio_value(self):
        w = {"a": 0.30}
        a1 = self.ps.compute_dollar_allocations(w, 100_000.0)
        a2 = self.ps.compute_dollar_allocations(w, 200_000.0)
        self.assertAlmostEqual(a2["a"] / a1["a"], 2.0, places=6)

    def test_sum_of_allocations(self):
        w = {"a": 0.40, "b": 0.35, "c": 0.20}
        allocs = self.ps.compute_dollar_allocations(w, 100_000.0)
        self.assertAlmostEqual(sum(allocs.values()), 95_000.0, places=2)

    def test_empty_weights_empty_allocs(self):
        allocs = self.ps.compute_dollar_allocations({}, 100_000.0)
        self.assertEqual(allocs, {})


# ═════════════════════════════════════════════════════════════════════════════
# 6. apply_tier_caps
# ═════════════════════════════════════════════════════════════════════════════

class TestApplyTierCaps(unittest.TestCase):
    def setUp(self):
        self.ps = PositionSizer()

    def test_returns_dict(self):
        result = self.ps.apply_tier_caps({"a": 0.5}, {"a": "T1"})
        self.assertIsInstance(result, dict)

    def test_same_keys_preserved(self):
        weights = {"a": 0.3, "b": 0.4}
        tiers   = {"a": "T1", "b": "T2"}
        result  = self.ps.apply_tier_caps(weights, tiers)
        self.assertEqual(set(result.keys()), set(weights.keys()))

    def test_t2_per_proto_cap_applied(self):
        # T2 per-protocol cap is 0.25; weight 0.45 should be clamped
        weights = {"yearn": 0.45}
        tiers   = {"yearn": "T2"}
        result  = self.ps.apply_tier_caps(weights, tiers)
        self.assertLessEqual(result["yearn"], 0.25 + 1e-9)

    def test_t3_per_proto_cap_applied(self):
        weights = {"pendle": 0.30}
        tiers   = {"pendle": "T3"}
        result  = self.ps.apply_tier_caps(weights, tiers)
        self.assertLessEqual(result["pendle"], 0.10 + 1e-9)

    def test_t1_within_cap_unchanged(self):
        weights = {"aave": 0.35}
        tiers   = {"aave": "T1"}
        result  = self.ps.apply_tier_caps(weights, tiers)
        self.assertAlmostEqual(result["aave"], 0.35)

    def test_t2_aggregate_cap_enforced(self):
        # Two T2 adapters each at 0.30 = 0.60 total > T2 total cap 0.50
        weights = {"yearn": 0.30, "euler": 0.30}
        tiers   = {"yearn": "T2", "euler": "T2"}
        result  = self.ps.apply_tier_caps(weights, tiers)
        self.assertLessEqual(sum(result.values()), 0.50 + 1e-9)

    def test_t3_aggregate_cap_enforced(self):
        # Two T3 adapters summing to 0.20 > T3 total cap 0.15
        weights = {"p1": 0.10, "p2": 0.10}
        tiers   = {"p1": "T3", "p2": "T3"}
        result  = self.ps.apply_tier_caps(weights, tiers)
        self.assertLessEqual(sum(result.values()), 0.15 + 1e-9)

    def test_missing_tier_treated_as_t1(self):
        weights = {"unknown": 0.55}  # > T1 per-protocol cap 0.60 → unchanged below 0.60
        result  = self.ps.apply_tier_caps(weights, {})
        # T1 per-proto cap is 0.60, so 0.55 should pass through
        self.assertAlmostEqual(result["unknown"], 0.55)

    def test_does_not_mutate_input(self):
        weights = {"a": 0.45}
        tiers   = {"a": "T2"}
        orig = dict(weights)
        self.ps.apply_tier_caps(weights, tiers)
        self.assertEqual(weights, orig)

    def test_t2_pro_rata_reduction(self):
        # T2 adapters equal weight, 0.30 each → total 0.60 > cap 0.50
        # After trim, each should be 0.25
        weights = {"y": 0.30, "e": 0.30}
        tiers   = {"y": "T2", "e": "T2"}
        result  = self.ps.apply_tier_caps(weights, tiers)
        self.assertAlmostEqual(result["y"], result["e"], places=6)
        self.assertAlmostEqual(result["y"] + result["e"], 0.50, places=6)

    def test_mixed_tiers_t1_not_affected_by_t2_trim(self):
        weights = {"aave": 0.40, "yearn": 0.30, "euler": 0.30}
        tiers   = {"aave": "T1", "yearn": "T2", "euler": "T2"}
        result  = self.ps.apply_tier_caps(weights, tiers)
        # T1 aave should be unchanged
        self.assertAlmostEqual(result["aave"], 0.40)
        # T2 total should be ≤ 0.50
        t2_total = result["yearn"] + result["euler"]
        self.assertLessEqual(t2_total, 0.50 + 1e-9)


# ═════════════════════════════════════════════════════════════════════════════
# 7. apply_concentration_limit
# ═════════════════════════════════════════════════════════════════════════════

class TestApplyConcentrationLimit(unittest.TestCase):
    def setUp(self):
        self.ps = PositionSizer()

    def test_returns_dict(self):
        result = self.ps.apply_concentration_limit({"a": 0.5})
        self.assertIsInstance(result, dict)

    def test_cap_applied(self):
        result = self.ps.apply_concentration_limit({"a": 0.60}, max_single=0.40)
        self.assertAlmostEqual(result["a"], 0.40)

    def test_below_cap_unchanged(self):
        result = self.ps.apply_concentration_limit({"a": 0.30}, max_single=0.40)
        self.assertAlmostEqual(result["a"], 0.30)

    def test_exact_cap_unchanged(self):
        result = self.ps.apply_concentration_limit({"a": 0.40}, max_single=0.40)
        self.assertAlmostEqual(result["a"], 0.40)

    def test_multiple_adapters(self):
        weights = {"a": 0.50, "b": 0.25, "c": 0.10}
        result  = self.ps.apply_concentration_limit(weights, max_single=0.40)
        self.assertAlmostEqual(result["a"], 0.40)
        self.assertAlmostEqual(result["b"], 0.25)
        self.assertAlmostEqual(result["c"], 0.10)

    def test_default_cap_is_40pct(self):
        result = self.ps.apply_concentration_limit({"a": 0.55})
        self.assertAlmostEqual(result["a"], 0.40)

    def test_zero_weight_unchanged(self):
        result = self.ps.apply_concentration_limit({"a": 0.0}, max_single=0.40)
        self.assertAlmostEqual(result["a"], 0.0)

    def test_does_not_mutate_input(self):
        weights = {"a": 0.60}
        orig = dict(weights)
        self.ps.apply_concentration_limit(weights, max_single=0.40)
        self.assertEqual(weights, orig)

    def test_empty_input(self):
        result = self.ps.apply_concentration_limit({})
        self.assertEqual(result, {})

    def test_custom_high_cap(self):
        result = self.ps.apply_concentration_limit({"a": 0.80}, max_single=0.90)
        self.assertAlmostEqual(result["a"], 0.80)

    def test_all_capped(self):
        weights = {"a": 0.90, "b": 0.80, "c": 0.70}
        result  = self.ps.apply_concentration_limit(weights, max_single=0.30)
        for v in result.values():
            self.assertAlmostEqual(v, 0.30)


# ═════════════════════════════════════════════════════════════════════════════
# 8. get_sizing_report — structure
# ═════════════════════════════════════════════════════════════════════════════

class TestGetSizingReportStructure(unittest.TestCase):
    def setUp(self):
        self.ps = PositionSizer()
        self.report = self.ps.get_sizing_report(
            _mixed_adapters(),
            100_000.0,
            _default_risk_limits(),
            _mixed_tiers(),
        )

    def test_returns_dict(self):
        self.assertIsInstance(self.report, dict)

    def test_generated_at_present(self):
        self.assertIn("generated_at", self.report)

    def test_portfolio_value_correct(self):
        self.assertAlmostEqual(self.report["portfolio_value"], 100_000.0)

    def test_weights_raw_present(self):
        self.assertIn("weights_raw", self.report)
        self.assertIsInstance(self.report["weights_raw"], dict)

    def test_weights_after_tier_caps_present(self):
        self.assertIn("weights_after_tier_caps", self.report)

    def test_weights_final_present(self):
        self.assertIn("weights_final", self.report)

    def test_dollar_allocations_present(self):
        self.assertIn("dollar_allocations", self.report)

    def test_cash_buffer_usd_present(self):
        self.assertIn("cash_buffer_usd", self.report)

    def test_cash_buffer_pct_present(self):
        self.assertIn("cash_buffer_pct", self.report)

    def test_adapter_count_correct(self):
        self.assertEqual(self.report["adapter_count"], len(_mixed_adapters()))

    def test_eligible_count_present(self):
        self.assertIn("eligible_count", self.report)

    def test_tier_summary_present(self):
        self.assertIn("tier_summary", self.report)
        self.assertIn("T1", self.report["tier_summary"])
        self.assertIn("T2", self.report["tier_summary"])
        self.assertIn("T3", self.report["tier_summary"])

    def test_risk_limits_applied_present(self):
        self.assertIn("risk_limits_applied", self.report)

    def test_warnings_is_list(self):
        self.assertIsInstance(self.report["warnings"], list)

    def test_keys_in_dollar_allocations(self):
        self.assertEqual(
            set(self.report["dollar_allocations"].keys()),
            set(_mixed_adapters().keys()),
        )


# ═════════════════════════════════════════════════════════════════════════════
# 9. get_sizing_report — semantics
# ═════════════════════════════════════════════════════════════════════════════

class TestGetSizingReportSemantics(unittest.TestCase):
    def setUp(self):
        self.ps = PositionSizer()
        self.pv = 100_000.0

    def test_cash_buffer_at_least_5pct(self):
        report = self.ps.get_sizing_report(
            _mixed_adapters(), self.pv, _default_risk_limits(), _mixed_tiers()
        )
        self.assertGreaterEqual(report["cash_buffer_pct"], 0.05 - 1e-9)

    def test_cash_buffer_usd_consistent(self):
        report = self.ps.get_sizing_report(
            _mixed_adapters(), self.pv, _default_risk_limits(), _mixed_tiers()
        )
        expected_usd = report["cash_buffer_pct"] * self.pv
        self.assertAlmostEqual(report["cash_buffer_usd"], expected_usd, places=2)

    def test_weights_final_le_one(self):
        report = self.ps.get_sizing_report(
            _mixed_adapters(), self.pv, _default_risk_limits(), _mixed_tiers()
        )
        total = sum(report["weights_final"].values())
        self.assertLessEqual(total, 1.0 + 1e-9)

    def test_dollar_allocations_sum_consistent(self):
        report = self.ps.get_sizing_report(
            _mixed_adapters(), self.pv, _default_risk_limits(), _mixed_tiers()
        )
        total_alloc = sum(report["dollar_allocations"].values())
        expected = sum(report["weights_final"].values()) * self.pv
        self.assertAlmostEqual(total_alloc, expected, places=2)

    def test_no_eligible_adapters_eligible_count_zero(self):
        adapters = {"x": {"apy": 0.0, "tvl": 0.0}}
        report = self.ps.get_sizing_report(adapters, self.pv)
        self.assertEqual(report["eligible_count"], 0)

    def test_no_eligible_adapters_warning_present(self):
        adapters = {"x": {"apy": 0.0, "tvl": 0.0}}
        report = self.ps.get_sizing_report(adapters, self.pv)
        self.assertTrue(len(report["warnings"]) > 0)

    def test_tier_summary_usd_adds_up(self):
        report = self.ps.get_sizing_report(
            _mixed_adapters(), self.pv, _default_risk_limits(), _mixed_tiers()
        )
        ts = report["tier_summary"]
        t1_usd = ts["T1"]["total_usd"]
        t2_usd = ts["T2"]["total_usd"]
        # T1 + T2 should approximately equal total allocated
        total_alloc = sum(report["dollar_allocations"].values())
        self.assertAlmostEqual(t1_usd + t2_usd, total_alloc, places=2)

    def test_no_tiers_skips_tier_capping(self):
        # Without adapter_tiers, tier caps are skipped; weights should still be valid
        report = self.ps.get_sizing_report(_t1_adapters(), self.pv, _default_risk_limits())
        total = sum(report["weights_final"].values())
        self.assertLessEqual(total, 1.0 + 1e-9)

    def test_risk_limits_applied_fields(self):
        report = self.ps.get_sizing_report(
            _mixed_adapters(), self.pv, _default_risk_limits(), _mixed_tiers()
        )
        rl = report["risk_limits_applied"]
        self.assertIn("max_single", rl)
        self.assertIn("min_cash_buffer", rl)
        self.assertIn("min_apy", rl)
        self.assertIn("max_apy", rl)
        self.assertIn("min_tvl", rl)

    def test_empty_adapters_no_crash(self):
        report = self.ps.get_sizing_report({}, self.pv)
        self.assertEqual(report["adapter_count"], 0)
        self.assertEqual(report["eligible_count"], 0)

    def test_single_eligible_adapter(self):
        adapters = {"a": {"apy": 5.0, "tvl": 1_000_000_000}}
        report = self.ps.get_sizing_report(adapters, self.pv, _default_risk_limits())
        self.assertEqual(report["eligible_count"], 1)
        self.assertGreater(report["weights_final"]["a"], 0.0)

    def test_weights_final_max_single_respected(self):
        report = self.ps.get_sizing_report(
            _mixed_adapters(), self.pv, _default_risk_limits(), _mixed_tiers()
        )
        for w in report["weights_final"].values():
            self.assertLessEqual(w, 0.40 + 1e-9)


# ═════════════════════════════════════════════════════════════════════════════
# 10. save_report (persistence + atomic write)
# ═════════════════════════════════════════════════════════════════════════════

class TestSaveReport(unittest.TestCase):
    def setUp(self):
        self.ps = PositionSizer()
        self.tmp_dir = tempfile.mkdtemp()
        self.report = self.ps.get_sizing_report(
            _mixed_adapters(), 100_000.0, _default_risk_limits(), _mixed_tiers()
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_file_created(self):
        self.ps.save_report(self.report, data_dir=self.tmp_dir)
        p = Path(self.tmp_dir) / REPORT_FILENAME
        self.assertTrue(p.exists())

    def test_file_is_valid_json(self):
        self.ps.save_report(self.report, data_dir=self.tmp_dir)
        p = Path(self.tmp_dir) / REPORT_FILENAME
        data = json.loads(p.read_text())
        self.assertIsInstance(data, list)

    def test_file_contains_one_entry_initially(self):
        self.ps.save_report(self.report, data_dir=self.tmp_dir)
        p = Path(self.tmp_dir) / REPORT_FILENAME
        data = json.loads(p.read_text())
        self.assertEqual(len(data), 1)

    def test_appends_on_second_write(self):
        self.ps.save_report(self.report, data_dir=self.tmp_dir)
        self.ps.save_report(self.report, data_dir=self.tmp_dir)
        p = Path(self.tmp_dir) / REPORT_FILENAME
        data = json.loads(p.read_text())
        self.assertEqual(len(data), 2)

    def test_no_tmp_files_left_after_write(self):
        self.ps.save_report(self.report, data_dir=self.tmp_dir)
        tmp_files = [f for f in os.listdir(self.tmp_dir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_ring_buffer_enforced(self):
        for _ in range(REPORT_HISTORY_MAX + 5):
            self.ps.save_report(self.report, data_dir=self.tmp_dir)
        p = Path(self.tmp_dir) / REPORT_FILENAME
        data = json.loads(p.read_text())
        self.assertLessEqual(len(data), REPORT_HISTORY_MAX)

    def test_creates_data_dir_if_missing(self):
        nested = os.path.join(self.tmp_dir, "new_dir")
        self.ps.save_report(self.report, data_dir=nested)
        p = Path(nested) / REPORT_FILENAME
        self.assertTrue(p.exists())


# ═════════════════════════════════════════════════════════════════════════════
# 11. CLI (main)
# ═════════════════════════════════════════════════════════════════════════════

class TestCLI(unittest.TestCase):
    def setUp(self):
        # Import _main locally to avoid circular import issues
        from spa_core.paper_trading.position_sizer import _main
        self._main = _main
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_check_exits_zero(self):
        rc = self._main(["--check"])
        self.assertEqual(rc, 0)

    def test_no_args_exits_zero(self):
        rc = self._main([])
        self.assertEqual(rc, 0)

    def test_run_exits_zero(self):
        rc = self._main(["--run", "--data-dir", self.tmp_dir])
        self.assertEqual(rc, 0)

    def test_run_creates_file(self):
        self._main(["--run", "--data-dir", self.tmp_dir])
        p = Path(self.tmp_dir) / REPORT_FILENAME
        self.assertTrue(p.exists())

    def test_check_does_not_create_file(self):
        self._main(["--check", "--data-dir", self.tmp_dir])
        p = Path(self.tmp_dir) / REPORT_FILENAME
        self.assertFalse(p.exists())


# ═════════════════════════════════════════════════════════════════════════════
# 12. Import hygiene (no forbidden deps)
# ═════════════════════════════════════════════════════════════════════════════

class TestImportHygiene(unittest.TestCase):
    """Ensure the module uses only stdlib; no external or forbidden imports."""

    _MODULE_PATH = Path(_REPO_ROOT) / "spa_core" / "paper_trading" / "position_sizer.py"
    _FORBIDDEN = {
        "requests", "web3", "numpy", "pandas", "scipy",
        "openai", "anthropic", "aiohttp", "httpx",
        "subprocess", "eval", "exec",
    }
    _FORBIDDEN_DOMAIN_IMPORTS = {"execution", "feed_health", "monitoring"}

    def _get_imports(self):
        src = self._MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split(".")[0])
                    imported.add(node.module)
        return imported

    def test_no_forbidden_packages(self):
        imported = self._get_imports()
        for bad in self._FORBIDDEN:
            self.assertNotIn(bad, imported,
                             f"Forbidden import {bad!r} found in position_sizer.py")

    def test_no_execution_domain_import(self):
        src = self._MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("from spa_core.execution", src)
        # Check there's no bare "import execution" as a Python statement (not in comments/docstrings)
        import ast as _ast
        tree = _ast.parse(src)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    self.assertNotIn("execution", alias.name,
                                     f"Forbidden import of execution module: {alias.name}")
            elif isinstance(node, _ast.ImportFrom):
                module = node.module or ""
                self.assertNotIn("execution", module,
                                 f"Forbidden from-import of execution module: {module}")

    def test_no_monitoring_domain_import(self):
        src = self._MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("from spa_core.monitoring", src)

    def test_no_risk_policy_import(self):
        # PositionSizer is advisory; it must not import risk.policy directly
        src = self._MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("from spa_core.risk", src)

    def test_file_compiles(self):
        import py_compile
        try:
            py_compile.compile(str(self._MODULE_PATH), doraise=True)
        except py_compile.PyCompileError as e:
            self.fail(f"position_sizer.py failed py_compile: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# 13. Edge cases & numerical stability
# ═════════════════════════════════════════════════════════════════════════════

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.ps = PositionSizer()

    def test_very_large_portfolio_value(self):
        w = self.ps.compute_target_weights(_t1_adapters(), 1_000_000_000.0)
        self.assertLessEqual(sum(w.values()), 1.0 + 1e-9)

    def test_very_small_portfolio_value(self):
        allocs = self.ps.compute_dollar_allocations({"a": 0.5}, 1.0)
        self.assertAlmostEqual(allocs["a"], 0.5, places=6)

    def test_weights_with_float_precision(self):
        # Should not raise even with many adapters
        adapters = {f"p{i}": {"apy": float(i), "tvl": 1e10} for i in range(1, 21)}
        w = self.ps.compute_target_weights(adapters, 100_000.0)
        self.assertLessEqual(sum(w.values()), 1.0 + 1e-9)

    def test_single_adapter_gets_capped_not_full_portfolio(self):
        adapters = {"solo": {"apy": 5.0, "tvl": 1e10}}
        w = self.ps.compute_target_weights(adapters, 100_000.0, {"min_cash_buffer": 0.10})
        self.assertLessEqual(sum(w.values()), 0.90 + 1e-9)

    def test_t3_adapter_over_total_cap_trimmed(self):
        # Single T3 with weight 0.20 > T3 per-proto cap 0.10
        weights = {"pendle": 0.20}
        tiers   = {"pendle": "T3"}
        result  = self.ps.apply_tier_caps(weights, tiers)
        self.assertLessEqual(result["pendle"], 0.10 + 1e-9)

    def test_concentration_limit_zero_max_single(self):
        result = self.ps.apply_concentration_limit({"a": 0.5, "b": 0.3}, max_single=0.0)
        for v in result.values():
            self.assertAlmostEqual(v, 0.0)

    def test_sizing_report_no_tiers_no_crash(self):
        report = self.ps.get_sizing_report(_mixed_adapters(), 100_000.0)
        self.assertIn("weights_final", report)

    def test_all_adapters_excluded(self):
        rl = {"excluded": list(_t1_adapters().keys())}
        w = self.ps.compute_target_weights(_t1_adapters(), 100_000.0, rl)
        for v in w.values():
            self.assertAlmostEqual(v, 0.0)

    def test_tier_caps_all_zero_weights(self):
        weights = {"a": 0.0, "b": 0.0}
        tiers   = {"a": "T2", "b": "T2"}
        result  = self.ps.apply_tier_caps(weights, tiers)
        for v in result.values():
            self.assertAlmostEqual(v, 0.0)

    def test_report_generated_at_is_string(self):
        report = self.ps.get_sizing_report(_t1_adapters(), 100_000.0)
        self.assertIsInstance(report["generated_at"], str)
        self.assertIn("T", report["generated_at"])  # ISO 8601


if __name__ == "__main__":
    unittest.main(verbosity=2)
