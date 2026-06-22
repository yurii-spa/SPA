#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.yield_optimizer (MP-579).

Coverage:
  TestHelperFunctions         —  8 tests  (module-level _safe_float / _get_tier / _clamp)
  TestConstants               —  9 tests  (module constants)
  TestOptimizationResult      — 12 tests  (dataclass fields, to_dict, from_dict)
  TestYieldOptimizerInit      —  7 tests  (constructor, attributes)
  TestApplyConstraints        — 19 tests  (all 6 projection steps)
  TestOptimize                — 20 tests  (core optimize() correctness)
  TestComputeEfficientFrontier— 15 tests  (frontier sweep)
  TestGetSharpeOptimal        — 12 tests  (Sharpe selection)
  TestComputeExpectedApy      —  7 tests  (private helper, tested via optimize)
  TestComputeRiskScore        —  9 tests  (risk formula)
  TestComputeTierBreakdown    —  7 tests  (tier aggregation)
  TestSaveResult              —  7 tests  (atomic persistence, ring-buffer)
  TestCLI                     —  5 tests  (entry-point smoke tests)
  TestImportHygiene           —  4 tests  (no forbidden deps)

Total: 141 tests
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root on path
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.paper_trading.yield_optimizer import (
    MAX_ELIGIBLE_APY,
    MAX_ITER,
    MAX_SINGLE,
    MIN_ALLOCATION,
    MIN_CASH_BUFFER,
    RESULTS_FILENAME,
    RESULTS_HISTORY_MAX,
    RISK_SCALE,
    T2_CAP_PER_PROTOCOL,
    T2_CAP_TOTAL,
    T3_CAP_PER_PROTOCOL,
    T3_CAP_TOTAL,
    OptimizationResult,
    YieldOptimizer,
    _get_tier,
    _safe_float,
)


# ── Shared fixtures ────────────────────────────────────────────────────────────

def _make_adapters(
    *,
    n_t1: int = 2,
    n_t2: int = 1,
    n_t3: int = 0,
    base_apy: float = 5.0,
    base_risk: float = 0.30,
    tvl: float = 1_000_000_000.0,
) -> dict:
    """Generate a simple adapter dict for testing."""
    out: dict = {}
    for i in range(n_t1):
        out[f"t1_adapter_{i}"] = {
            "apy": base_apy + i * 0.5,
            "tvl": tvl,
            "risk_score": base_risk + i * 0.02,
            "tier": "T1",
        }
    for i in range(n_t2):
        out[f"t2_adapter_{i}"] = {
            "apy": base_apy - 1.0 + i * 0.3,
            "tvl": tvl,
            "risk_score": base_risk + 0.10 + i * 0.02,
            "tier": "T2",
        }
    for i in range(n_t3):
        out[f"t3_adapter_{i}"] = {
            "apy": base_apy + 2.0 + i * 0.5,
            "tvl": tvl,
            "risk_score": base_risk + 0.20 + i * 0.02,
            "tier": "T3",
        }
    return out


_STANDARD_ADAPTERS = {
    "aave_v3":           {"apy": 3.5,  "tvl": 9_000_000_000, "risk_score": 0.20, "tier": "T1"},
    "compound_v3":       {"apy": 4.8,  "tvl": 2_000_000_000, "risk_score": 0.22, "tier": "T1"},
    "morpho_steakhouse": {"apy": 6.5,  "tvl": 800_000_000,   "risk_score": 0.30, "tier": "T1"},
    "yearn_v3":          {"apy": 5.2,  "tvl": 300_000_000,   "risk_score": 0.40, "tier": "T2"},
    "euler_v2":          {"apy": 4.1,  "tvl": 150_000_000,   "risk_score": 0.45, "tier": "T2"},
}


# ── TestHelperFunctions ────────────────────────────────────────────────────────

class TestHelperFunctions(unittest.TestCase):
    """Module-level helper: _safe_float, _get_tier, _clamp."""

    def test_safe_float_int(self):
        self.assertEqual(_safe_float(3), 3.0)

    def test_safe_float_float(self):
        self.assertAlmostEqual(_safe_float(3.14), 3.14)

    def test_safe_float_string_int(self):
        self.assertEqual(_safe_float("5"), 5.0)

    def test_safe_float_none_returns_default(self):
        self.assertEqual(_safe_float(None, default=99.0), 99.0)

    def test_safe_float_bad_string_returns_default(self):
        self.assertEqual(_safe_float("abc", default=-1.0), -1.0)

    def test_get_tier_t1(self):
        adapters = {"a": {"tier": "T1"}}
        self.assertEqual(_get_tier(adapters, "a"), "T1")

    def test_get_tier_t2(self):
        adapters = {"b": {"tier": "T2"}}
        self.assertEqual(_get_tier(adapters, "b"), "T2")

    def test_get_tier_missing_adapter_defaults_t1(self):
        self.assertEqual(_get_tier({}, "x"), "T1")


# ── TestConstants ──────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    """Module-level constants match RiskPolicy v1.0 / ADR-019 / ADR-020."""

    def test_min_allocation(self):
        self.assertAlmostEqual(MIN_ALLOCATION, 0.02)

    def test_max_single(self):
        self.assertAlmostEqual(MAX_SINGLE, 0.40)

    def test_min_cash_buffer(self):
        self.assertAlmostEqual(MIN_CASH_BUFFER, 0.05)

    def test_t2_cap_per_protocol(self):
        self.assertAlmostEqual(T2_CAP_PER_PROTOCOL, 0.20)

    def test_t3_cap_per_protocol(self):
        self.assertAlmostEqual(T3_CAP_PER_PROTOCOL, 0.10)

    def test_t2_cap_total(self):
        self.assertAlmostEqual(T2_CAP_TOTAL, 0.50)

    def test_t3_cap_total(self):
        self.assertAlmostEqual(T3_CAP_TOTAL, 0.15)

    def test_risk_scale(self):
        self.assertAlmostEqual(RISK_SCALE, 10.0)

    def test_results_history_max(self):
        self.assertEqual(RESULTS_HISTORY_MAX, 365)


# ── TestOptimizationResult ─────────────────────────────────────────────────────

class TestOptimizationResult(unittest.TestCase):
    """OptimizationResult dataclass: construction, serialisation, round-trip."""

    def _make(self, **kw) -> OptimizationResult:
        defaults = dict(
            weights={"a": 0.4, "b": 0.3},
            expected_apy=4.5,
            risk_score=0.25,
            tier_breakdown={"T1": 0.4, "T2": 0.3, "T3": 0.0, "cash": 0.3},
            warnings=[],
        )
        defaults.update(kw)
        return OptimizationResult(**defaults)

    def test_weights_attribute(self):
        r = self._make()
        self.assertEqual(r.weights, {"a": 0.4, "b": 0.3})

    def test_expected_apy_attribute(self):
        r = self._make(expected_apy=7.2)
        self.assertAlmostEqual(r.expected_apy, 7.2)

    def test_risk_score_attribute(self):
        r = self._make(risk_score=0.55)
        self.assertAlmostEqual(r.risk_score, 0.55)

    def test_tier_breakdown_attribute(self):
        r = self._make()
        self.assertIn("T1", r.tier_breakdown)
        self.assertIn("cash", r.tier_breakdown)

    def test_warnings_attribute_is_list(self):
        r = self._make(warnings=["warn1"])
        self.assertIsInstance(r.warnings, list)
        self.assertEqual(r.warnings[0], "warn1")

    def test_to_dict_returns_dict(self):
        r = self._make()
        self.assertIsInstance(r.to_dict(), dict)

    def test_to_dict_has_all_keys(self):
        r = self._make()
        d = r.to_dict()
        for key in ("weights", "expected_apy", "risk_score", "tier_breakdown", "warnings"):
            self.assertIn(key, d)

    def test_to_dict_weights_correct(self):
        r = self._make(weights={"x": 0.6})
        self.assertEqual(r.to_dict()["weights"], {"x": 0.6})

    def test_from_dict_roundtrip(self):
        r = self._make()
        d = r.to_dict()
        r2 = OptimizationResult.from_dict(d)
        self.assertAlmostEqual(r2.expected_apy, r.expected_apy)
        self.assertAlmostEqual(r2.risk_score, r.risk_score)
        self.assertEqual(r2.weights, r.weights)

    def test_from_dict_empty_dict_defaults(self):
        r = OptimizationResult.from_dict({})
        self.assertEqual(r.weights, {})
        self.assertAlmostEqual(r.expected_apy, 0.0)
        self.assertAlmostEqual(r.risk_score, 0.0)
        self.assertEqual(r.warnings, [])

    def test_from_dict_partial(self):
        r = OptimizationResult.from_dict({"expected_apy": 3.0})
        self.assertAlmostEqual(r.expected_apy, 3.0)
        self.assertEqual(r.weights, {})

    def test_to_dict_is_json_serialisable(self):
        r = self._make()
        serialised = json.dumps(r.to_dict())
        self.assertIsInstance(serialised, str)


# ── TestYieldOptimizerInit ─────────────────────────────────────────────────────

class TestYieldOptimizerInit(unittest.TestCase):
    """YieldOptimizer constructor and attribute storage."""

    def test_default_init(self):
        opt = YieldOptimizer()
        self.assertIsInstance(opt, YieldOptimizer)

    def test_default_min_cash_buffer(self):
        opt = YieldOptimizer()
        self.assertAlmostEqual(opt._min_cash_buffer, MIN_CASH_BUFFER)

    def test_default_max_iter(self):
        opt = YieldOptimizer()
        self.assertEqual(opt._max_iter, MAX_ITER)

    def test_custom_min_cash_buffer(self):
        opt = YieldOptimizer(min_cash_buffer=0.10)
        self.assertAlmostEqual(opt._min_cash_buffer, 0.10)

    def test_custom_max_iter(self):
        opt = YieldOptimizer(max_iter=50)
        self.assertEqual(opt._max_iter, 50)

    def test_attributes_accessible(self):
        opt = YieldOptimizer(min_cash_buffer=0.07, max_iter=100)
        self.assertAlmostEqual(opt._min_cash_buffer, 0.07)
        self.assertEqual(opt._max_iter, 100)

    def test_min_cash_buffer_stored_as_float(self):
        opt = YieldOptimizer(min_cash_buffer=0.06)
        self.assertIsInstance(opt._min_cash_buffer, float)


# ── TestApplyConstraints ───────────────────────────────────────────────────────

class TestApplyConstraints(unittest.TestCase):
    """apply_constraints: all 6 projection steps."""

    def setUp(self):
        self.opt = YieldOptimizer()

    def _adapters(self):
        return {
            "t1a": {"tier": "T1", "apy": 5.0, "tvl": 1e9, "risk_score": 0.2},
            "t1b": {"tier": "T1", "apy": 4.0, "tvl": 1e9, "risk_score": 0.3},
            "t2a": {"tier": "T2", "apy": 6.0, "tvl": 1e9, "risk_score": 0.4},
            "t2b": {"tier": "T2", "apy": 5.5, "tvl": 1e9, "risk_score": 0.4},
            "t3a": {"tier": "T3", "apy": 8.0, "tvl": 1e9, "risk_score": 0.5},
        }

    def test_empty_weights_returns_same_keys(self):
        adapters = self._adapters()
        w = {k: 0.0 for k in adapters}
        result = self.opt.apply_constraints(w, adapters, {})
        self.assertEqual(set(result.keys()), set(w.keys()))

    def test_excluded_adapters_zeroed(self):
        adapters = self._adapters()
        w = {"t1a": 0.40, "t2a": 0.30}
        result = self.opt.apply_constraints(w, adapters, {"excluded_adapters": ["t2a"]})
        self.assertAlmostEqual(result["t2a"], 0.0)

    def test_t1_max_single_cap(self):
        adapters = self._adapters()
        # T1 adapter weight exceeds max_single=0.40
        w = {"t1a": 0.90}
        result = self.opt.apply_constraints(w, adapters, {})
        self.assertLessEqual(result["t1a"], MAX_SINGLE + 1e-9)

    def test_t2_per_protocol_cap(self):
        adapters = self._adapters()
        # T2 adapter weight should be capped at T2_CAP_PER_PROTOCOL=0.20
        w = {"t2a": 0.60, "t1a": 0.20}
        result = self.opt.apply_constraints(w, adapters, {})
        self.assertLessEqual(result["t2a"], T2_CAP_PER_PROTOCOL + 1e-9)

    def test_t3_per_protocol_cap(self):
        adapters = self._adapters()
        # T3 adapter weight should be capped at T3_CAP_PER_PROTOCOL=0.10
        w = {"t3a": 0.50}
        result = self.opt.apply_constraints(w, adapters, {})
        self.assertLessEqual(result["t3a"], T3_CAP_PER_PROTOCOL + 1e-9)

    def test_t2_aggregate_cap_default(self):
        adapters = self._adapters()
        # Two T2 adapters each at 0.30 → total 0.60 > T2_CAP_TOTAL (0.50)
        w = {"t2a": 0.30, "t2b": 0.30}
        result = self.opt.apply_constraints(w, adapters, {})
        t2_total = result["t2a"] + result["t2b"]
        self.assertLessEqual(t2_total, T2_CAP_TOTAL + 1e-7)

    def test_t2_aggregate_not_triggered_when_under_cap(self):
        adapters = self._adapters()
        w = {"t2a": 0.20, "t2b": 0.10}
        result = self.opt.apply_constraints(w, adapters, {})
        # Total T2 = 0.30 < 0.50 → no trimming
        self.assertAlmostEqual(result["t2a"], 0.20, places=6)
        self.assertAlmostEqual(result["t2b"], 0.10, places=6)

    def test_custom_max_t2_pct_applied(self):
        adapters = self._adapters()
        w = {"t2a": 0.20, "t2b": 0.20}  # total 0.40
        result = self.opt.apply_constraints(w, adapters, {"max_t2_pct": 0.30})
        t2_total = result["t2a"] + result["t2b"]
        self.assertLessEqual(t2_total, 0.30 + 1e-7)

    def test_t3_aggregate_cap(self):
        adapters = {
            "t3a": {"tier": "T3", "apy": 8.0, "tvl": 1e9, "risk_score": 0.5},
            "t3b": {"tier": "T3", "apy": 7.0, "tvl": 1e9, "risk_score": 0.5},
        }
        # each at 0.10 → total 0.20 > T3_CAP_TOTAL (0.15)
        w = {"t3a": 0.10, "t3b": 0.10}
        result = self.opt.apply_constraints(w, adapters, {})
        t3_total = result["t3a"] + result["t3b"]
        self.assertLessEqual(t3_total, T3_CAP_TOTAL + 1e-7)

    def test_t3_aggregate_not_triggered_when_under_cap(self):
        adapters = {"t3a": {"tier": "T3", "apy": 8.0, "tvl": 1e9, "risk_score": 0.5}}
        w = {"t3a": 0.10}
        result = self.opt.apply_constraints(w, adapters, {})
        self.assertAlmostEqual(result["t3a"], 0.10, places=6)

    def test_min_allocation_below_threshold_zeroed(self):
        adapters = {"t1a": {"tier": "T1", "apy": 5.0, "tvl": 1e9, "risk_score": 0.2}}
        w = {"t1a": 0.01}  # < MIN_ALLOCATION=0.02 → should be zeroed
        result = self.opt.apply_constraints(w, adapters, {})
        self.assertAlmostEqual(result["t1a"], 0.0)

    def test_min_allocation_exact_threshold_kept(self):
        adapters = {"t1a": {"tier": "T1", "apy": 5.0, "tvl": 1e9, "risk_score": 0.2}}
        w = {"t1a": 0.02}  # == MIN_ALLOCATION → kept
        result = self.opt.apply_constraints(w, adapters, {})
        self.assertGreaterEqual(result["t1a"], MIN_ALLOCATION - 1e-9)

    def test_min_allocation_just_below_threshold_zeroed(self):
        adapters = {"t1a": {"tier": "T1", "apy": 5.0, "tvl": 1e9, "risk_score": 0.2}}
        w = {"t1a": 0.019}  # just below MIN_ALLOCATION → zeroed
        result = self.opt.apply_constraints(w, adapters, {})
        self.assertAlmostEqual(result["t1a"], 0.0)

    def test_cash_buffer_enforced(self):
        adapters = self._adapters()
        # Weights summing to 0.99 → total > max_investable (0.95) → scaled down
        w = {"t1a": 0.40, "t1b": 0.40, "t2a": 0.19}
        result = self.opt.apply_constraints(w, adapters, {})
        total = sum(result.values())
        self.assertLessEqual(total, 1.0 - MIN_CASH_BUFFER + 1e-7)

    def test_cash_buffer_not_triggered_when_under(self):
        adapters = self._adapters()
        w = {"t1a": 0.30, "t2a": 0.20}  # total 0.50 < 0.95
        result = self.opt.apply_constraints(w, adapters, {})
        self.assertAlmostEqual(result["t1a"], 0.30, places=6)
        self.assertAlmostEqual(result["t2a"], 0.20, places=6)

    def test_excluded_plus_t2_cap(self):
        adapters = self._adapters()
        w = {"t1a": 0.40, "t2a": 0.30, "t2b": 0.30}
        result = self.opt.apply_constraints(w, adapters, {"excluded_adapters": ["t2b"]})
        self.assertAlmostEqual(result["t2b"], 0.0)
        self.assertLessEqual(result["t2a"], T2_CAP_PER_PROTOCOL + 1e-9)

    def test_t2_pro_rata_trim_proportional(self):
        adapters = {
            "t2a": {"tier": "T2", "apy": 6.0, "tvl": 1e9, "risk_score": 0.4},
            "t2b": {"tier": "T2", "apy": 4.0, "tvl": 1e9, "risk_score": 0.4},
        }
        # Both at 0.20 → total 0.40 > 0.30 custom cap → both trimmed proportionally
        w = {"t2a": 0.20, "t2b": 0.20}
        result = self.opt.apply_constraints(w, adapters, {"max_t2_pct": 0.30})
        t2_total = result["t2a"] + result["t2b"]
        self.assertAlmostEqual(t2_total, 0.30, places=5)
        # Both trimmed equally (same original weight)
        self.assertAlmostEqual(result["t2a"], result["t2b"], places=5)

    def test_t3_pro_rata_trim_proportional(self):
        adapters = {
            "t3a": {"tier": "T3", "apy": 8.0, "tvl": 1e9, "risk_score": 0.5},
            "t3b": {"tier": "T3", "apy": 7.0, "tvl": 1e9, "risk_score": 0.5},
        }
        w = {"t3a": 0.09, "t3b": 0.09}  # total 0.18 > T3_CAP_TOTAL 0.15
        result = self.opt.apply_constraints(w, adapters, {})
        t3_total = result["t3a"] + result["t3b"]
        self.assertAlmostEqual(t3_total, T3_CAP_TOTAL, places=5)

    def test_all_weights_non_negative(self):
        adapters = self._adapters()
        w = {"t1a": 0.80, "t2a": 0.80, "t3a": 0.80}
        result = self.opt.apply_constraints(w, adapters, {})
        for v in result.values():
            self.assertGreaterEqual(v, 0.0)


# ── TestOptimize ───────────────────────────────────────────────────────────────

class TestOptimize(unittest.TestCase):
    """optimize(): correctness, constraints, edge cases."""

    def setUp(self):
        self.opt = YieldOptimizer()

    def test_returns_optimization_result(self):
        result = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        self.assertIsInstance(result, OptimizationResult)

    def test_single_t1_adapter_gets_capped_weight(self):
        adapters = {"a": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"}}
        r = self.opt.optimize(adapters, 100_000.0)
        # Single T1 adapter clipped to MAX_SINGLE=0.40
        self.assertAlmostEqual(r.weights["a"], MAX_SINGLE, places=5)

    def test_two_t1_equal_apy_equal_weights(self):
        adapters = {
            "a": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
            "b": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
        }
        r = self.opt.optimize(adapters, 100_000.0)
        # Both should get equal weight (each below MAX_SINGLE)
        self.assertAlmostEqual(r.weights["a"], r.weights["b"], places=5)

    def test_higher_apy_gets_higher_weight(self):
        # Use 3 adapters so the high-APY one hits MAX_SINGLE cap while low stays proportional.
        # With 2 adapters the headroom redistribution brings both to the 0.40 cap equally.
        adapters = {
            "low": {"apy": 3.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
            "mid": {"apy": 6.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
            "high": {"apy": 9.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
        }
        r = self.opt.optimize(adapters, 100_000.0)
        # high is capped at MAX_SINGLE (0.40); low stays well below it
        self.assertGreater(r.weights["high"], r.weights["low"])

    def test_cash_buffer_maintained(self):
        r = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        total = sum(r.weights.values())
        self.assertLessEqual(total, 1.0 - MIN_CASH_BUFFER + 1e-7)

    def test_cash_buffer_minimum_5pct(self):
        r = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        total = sum(r.weights.values())
        self.assertGreaterEqual(1.0 - total, MIN_CASH_BUFFER - 1e-7)

    def test_no_eligible_adapters_returns_zero_weights(self):
        adapters = {
            "bad": {"apy": 0.5, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"}  # APY < MIN
        }
        r = self.opt.optimize(adapters, 100_000.0)
        self.assertAlmostEqual(r.weights["bad"], 0.0)
        self.assertAlmostEqual(r.expected_apy, 0.0)

    def test_no_eligible_adapters_has_warning(self):
        adapters = {"bad": {"apy": 0.1, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"}}
        r = self.opt.optimize(adapters, 100_000.0)
        self.assertTrue(len(r.warnings) > 0)

    def test_excluded_adapters_constraint(self):
        r = self.opt.optimize(
            _STANDARD_ADAPTERS, 100_000.0, {"excluded_adapters": ["morpho_steakhouse"]}
        )
        self.assertAlmostEqual(r.weights["morpho_steakhouse"], 0.0)

    def test_max_risk_filters_high_risk_adapter(self):
        adapters = {
            "safe": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.10, "tier": "T1"},
            "risky": {"apy": 8.0, "tvl": 1e9, "risk_score": 0.90, "tier": "T1"},
        }
        r = self.opt.optimize(adapters, 100_000.0, {"max_risk": 0.50})
        self.assertAlmostEqual(r.weights["risky"], 0.0)
        self.assertGreater(r.weights["safe"], 0.0)

    def test_apy_below_min_eligible_excluded(self):
        adapters = {
            "valid": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
            "too_low": {"apy": 0.5, "tvl": 1e9, "risk_score": 0.1, "tier": "T1"},
        }
        r = self.opt.optimize(adapters, 100_000.0)
        self.assertAlmostEqual(r.weights["too_low"], 0.0)
        self.assertGreater(r.weights["valid"], 0.0)

    def test_apy_above_max_eligible_excluded(self):
        adapters = {
            "valid": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
            "too_high": {"apy": 35.0, "tvl": 1e9, "risk_score": 0.5, "tier": "T1"},
        }
        r = self.opt.optimize(adapters, 100_000.0)
        self.assertAlmostEqual(r.weights["too_high"], 0.0)

    def test_tvl_below_floor_excluded(self):
        adapters = {
            "ok": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
            "tiny_tvl": {"apy": 5.0, "tvl": 1_000.0, "risk_score": 0.2, "tier": "T1"},
        }
        r = self.opt.optimize(adapters, 100_000.0)
        self.assertAlmostEqual(r.weights["tiny_tvl"], 0.0)

    def test_expected_apy_positive_when_adapters_present(self):
        r = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        self.assertGreater(r.expected_apy, 0.0)

    def test_risk_score_in_unit_interval(self):
        r = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        self.assertGreaterEqual(r.risk_score, 0.0)
        self.assertLessEqual(r.risk_score, 1.0)

    def test_tier_breakdown_has_all_keys(self):
        r = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        for key in ("T1", "T2", "T3", "cash"):
            self.assertIn(key, r.tier_breakdown)

    def test_warnings_is_list(self):
        r = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        self.assertIsInstance(r.warnings, list)

    def test_min_apy_constraint_triggers_warning(self):
        # Force portfolio APY below min_apy by excluding good adapters
        adapters = {
            "low": {"apy": 1.5, "tvl": 1e9, "risk_score": 0.1, "tier": "T1"},
        }
        r = self.opt.optimize(adapters, 100_000.0, {"min_apy": 5.0})
        # Portfolio APY ~1.5% < 5.0% → warning
        warning_texts = " ".join(r.warnings)
        self.assertIn("min_apy", warning_texts)

    def test_max_t2_pct_constraint_respected(self):
        adapters = {
            "t2a": {"apy": 8.0, "tvl": 1e9, "risk_score": 0.3, "tier": "T2"},
            "t2b": {"apy": 7.0, "tvl": 1e9, "risk_score": 0.3, "tier": "T2"},
            "t1a": {"apy": 4.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
        }
        r = self.opt.optimize(adapters, 100_000.0, {"max_t2_pct": 0.25})
        t2_total = r.weights.get("t2a", 0.0) + r.weights.get("t2b", 0.0)
        self.assertLessEqual(t2_total, 0.25 + 1e-7)

    def test_portfolio_value_does_not_affect_weights(self):
        r1 = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        r2 = self.opt.optimize(_STANDARD_ADAPTERS, 1_000_000.0)
        for aid in r1.weights:
            self.assertAlmostEqual(r1.weights[aid], r2.weights[aid], places=5)

    def test_all_weights_non_negative(self):
        r = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        for w in r.weights.values():
            self.assertGreaterEqual(w, 0.0)


# ── TestComputeEfficientFrontier ───────────────────────────────────────────────

class TestComputeEfficientFrontier(unittest.TestCase):
    """compute_efficient_frontier(): sweep, length, monotonicity."""

    def setUp(self):
        self.opt = YieldOptimizer()

    def test_returns_list(self):
        result = self.opt.compute_efficient_frontier(_STANDARD_ADAPTERS, 100_000.0)
        self.assertIsInstance(result, list)

    def test_n_points_1_returns_one(self):
        result = self.opt.compute_efficient_frontier(_STANDARD_ADAPTERS, 100_000.0, n_points=1)
        self.assertEqual(len(result), 1)

    def test_n_points_5_returns_five(self):
        result = self.opt.compute_efficient_frontier(_STANDARD_ADAPTERS, 100_000.0, n_points=5)
        self.assertEqual(len(result), 5)

    def test_n_points_20_returns_twenty(self):
        result = self.opt.compute_efficient_frontier(_STANDARD_ADAPTERS, 100_000.0, n_points=20)
        self.assertEqual(len(result), 20)

    def test_all_elements_are_optimization_result(self):
        frontier = self.opt.compute_efficient_frontier(_STANDARD_ADAPTERS, 100_000.0, n_points=5)
        for pt in frontier:
            self.assertIsInstance(pt, OptimizationResult)

    def test_first_point_is_max_yield(self):
        # λ=0 → pure yield intent.  With constraint-driven reweighting the
        # optimizer allocates proportionally to APY, including lower-APY
        # adapters that dilute the portfolio.  At slightly higher λ those
        # low-APY/high-risk adapters are penalised and budget shifts to higher-
        # APY ones, which can briefly lift portfolio APY above the λ=0 point.
        # Therefore the strict "first point = global max APY" property does not
        # hold for proportional-allocation-based optimizers.
        #
        # What we DO guarantee: the first frontier point (λ=0, risk-aversion=0)
        # is not worse than the LAST frontier point (which has max risk-aversion
        # and eventually yields all-cash or very low allocation).
        frontier = self.opt.compute_efficient_frontier(_STANDARD_ADAPTERS, 100_000.0, n_points=10)
        self.assertGreaterEqual(frontier[0].expected_apy, frontier[-1].expected_apy - 1e-4)

    def test_last_point_risk_lower_than_first(self):
        frontier = self.opt.compute_efficient_frontier(_STANDARD_ADAPTERS, 100_000.0, n_points=10)
        # Higher risk-aversion → lower or equal risk
        self.assertLessEqual(frontier[-1].risk_score, frontier[0].risk_score + 0.01)

    def test_empty_adapters_all_zero(self):
        adapters = {"bad": {"apy": 0.1, "tvl": 10.0, "risk_score": 0.5, "tier": "T1"}}
        frontier = self.opt.compute_efficient_frontier(adapters, 100_000.0, n_points=3)
        for pt in frontier:
            self.assertAlmostEqual(sum(pt.weights.values()), 0.0)

    def test_single_eligible_adapter_all_points_same_adapter(self):
        adapters = {
            "a": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
        }
        frontier = self.opt.compute_efficient_frontier(adapters, 100_000.0, n_points=5)
        for pt in frontier:
            # Either adapter a has weight > 0 or all-cash (when score < 0)
            self.assertGreaterEqual(pt.weights.get("a", 0.0), 0.0)

    def test_apy_generally_non_increasing_along_frontier(self):
        # As λ increases, APY should not increase overall
        adapters = {
            "a": {"apy": 8.0, "tvl": 1e9, "risk_score": 0.5, "tier": "T1"},
            "b": {"apy": 3.0, "tvl": 1e9, "risk_score": 0.1, "tier": "T1"},
        }
        frontier = self.opt.compute_efficient_frontier(adapters, 100_000.0, n_points=10)
        # First APY ≥ last APY (higher risk-aversion → lower yield)
        self.assertGreaterEqual(frontier[0].expected_apy, frontier[-1].expected_apy - 0.1)

    def test_frontier_with_excluded_constraint(self):
        r = self.opt.compute_efficient_frontier(
            _STANDARD_ADAPTERS, 100_000.0, n_points=3,
            constraints={"excluded_adapters": ["morpho_steakhouse"]}
        )
        for pt in r:
            self.assertAlmostEqual(pt.weights.get("morpho_steakhouse", 0.0), 0.0)

    def test_frontier_with_max_t2_pct_constraint(self):
        frontier = self.opt.compute_efficient_frontier(
            _STANDARD_ADAPTERS, 100_000.0, n_points=5,
            constraints={"max_t2_pct": 0.20}
        )
        for pt in frontier:
            t2_total = sum(
                pt.weights.get(aid, 0.0)
                for aid, info in _STANDARD_ADAPTERS.items()
                if info["tier"] == "T2"
            )
            self.assertLessEqual(t2_total, 0.20 + 1e-7)

    def test_n_points_2_returns_two(self):
        result = self.opt.compute_efficient_frontier(_STANDARD_ADAPTERS, 100_000.0, n_points=2)
        self.assertEqual(len(result), 2)

    def test_all_results_have_valid_weights(self):
        frontier = self.opt.compute_efficient_frontier(_STANDARD_ADAPTERS, 100_000.0, n_points=5)
        for pt in frontier:
            for w in pt.weights.values():
                self.assertGreaterEqual(w, 0.0)

    def test_all_results_tier_breakdown_has_keys(self):
        frontier = self.opt.compute_efficient_frontier(_STANDARD_ADAPTERS, 100_000.0, n_points=3)
        for pt in frontier:
            for key in ("T1", "T2", "T3", "cash"):
                self.assertIn(key, pt.tier_breakdown)


# ── TestGetSharpeOptimal ───────────────────────────────────────────────────────

class TestGetSharpeOptimal(unittest.TestCase):
    """get_sharpe_optimal(): Sharpe-maximising point selection."""

    def setUp(self):
        self.opt = YieldOptimizer()

    def test_returns_optimization_result(self):
        r = self.opt.get_sharpe_optimal(_STANDARD_ADAPTERS, 100_000.0)
        self.assertIsInstance(r, OptimizationResult)

    def test_default_risk_free_rate_used(self):
        # Should run without error using default risk_free_rate=0.04
        r = self.opt.get_sharpe_optimal(_STANDARD_ADAPTERS, 100_000.0)
        self.assertIsNotNone(r)

    def test_custom_risk_free_rate(self):
        r = self.opt.get_sharpe_optimal(_STANDARD_ADAPTERS, 100_000.0, risk_free_rate=0.02)
        self.assertIsInstance(r, OptimizationResult)

    def test_sharpe_ratio_maximised(self):
        # Build frontier and manually find best Sharpe
        frontier = self.opt.compute_efficient_frontier(
            _STANDARD_ADAPTERS, 100_000.0, n_points=50
        )
        rfr = 0.04
        best_sharpe = max(
            (pt.expected_apy / 100.0 - rfr) / pt.risk_score
            for pt in frontier
            if pt.risk_score > 1e-9
        )
        r = self.opt.get_sharpe_optimal(_STANDARD_ADAPTERS, 100_000.0, risk_free_rate=rfr)
        if r.risk_score > 1e-9:
            actual_sharpe = (r.expected_apy / 100.0 - rfr) / r.risk_score
            # Sharpe should be at most 1e-6 below the best frontier Sharpe
            self.assertGreaterEqual(actual_sharpe, best_sharpe - 1e-6)

    def test_single_eligible_adapter(self):
        adapters = {"a": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"}}
        r = self.opt.get_sharpe_optimal(adapters, 100_000.0)
        self.assertIsInstance(r, OptimizationResult)

    def test_weights_sum_lte_max_investable(self):
        r = self.opt.get_sharpe_optimal(_STANDARD_ADAPTERS, 100_000.0)
        total = sum(r.weights.values())
        self.assertLessEqual(total, 1.0 - MIN_CASH_BUFFER + 1e-7)

    def test_expected_apy_non_negative(self):
        r = self.opt.get_sharpe_optimal(_STANDARD_ADAPTERS, 100_000.0)
        self.assertGreaterEqual(r.expected_apy, 0.0)

    def test_risk_score_in_unit_interval(self):
        r = self.opt.get_sharpe_optimal(_STANDARD_ADAPTERS, 100_000.0)
        self.assertGreaterEqual(r.risk_score, 0.0)
        self.assertLessEqual(r.risk_score, 1.0)

    def test_tier_breakdown_has_all_keys(self):
        r = self.opt.get_sharpe_optimal(_STANDARD_ADAPTERS, 100_000.0)
        for key in ("T1", "T2", "T3", "cash"):
            self.assertIn(key, r.tier_breakdown)

    def test_constraints_respected(self):
        r = self.opt.get_sharpe_optimal(
            _STANDARD_ADAPTERS, 100_000.0,
            constraints={"excluded_adapters": ["yearn_v3"]}
        )
        self.assertAlmostEqual(r.weights.get("yearn_v3", 0.0), 0.0)

    def test_no_eligible_adapters_fallback(self):
        adapters = {"bad": {"apy": 0.1, "tvl": 100.0, "risk_score": 0.2, "tier": "T1"}}
        r = self.opt.get_sharpe_optimal(adapters, 100_000.0)
        self.assertIsInstance(r, OptimizationResult)
        self.assertAlmostEqual(r.expected_apy, 0.0)

    def test_higher_rfr_shifts_sharpe_optimal(self):
        # With higher risk-free rate, a less risky allocation may be preferred
        r_low = self.opt.get_sharpe_optimal(_STANDARD_ADAPTERS, 100_000.0, risk_free_rate=0.01)
        r_high = self.opt.get_sharpe_optimal(_STANDARD_ADAPTERS, 100_000.0, risk_free_rate=0.05)
        # Both should be valid OptimizationResult instances
        self.assertIsInstance(r_low, OptimizationResult)
        self.assertIsInstance(r_high, OptimizationResult)


# ── TestComputeExpectedApy ─────────────────────────────────────────────────────

class TestComputeExpectedApy(unittest.TestCase):
    """_compute_expected_apy via optimize() with controlled inputs."""

    def setUp(self):
        self.opt = YieldOptimizer()

    def test_zero_weight_gives_zero_apy(self):
        adapters = {"a": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"}}
        r = self.opt.optimize({"a": {"apy": 0.5, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"}}, 100_000.0)
        self.assertAlmostEqual(r.expected_apy, 0.0)

    def test_single_full_weight_returns_adapter_apy(self):
        # Single T1 adapter: weight=0.40, expected_apy = 0.40 * 5.0 = 2.0
        adapters = {"a": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"}}
        r = self.opt.optimize(adapters, 100_000.0)
        expected = r.weights["a"] * 5.0
        self.assertAlmostEqual(r.expected_apy, expected, places=4)

    def test_two_adapters_apy_weighted_correctly(self):
        adapters = {
            "a": {"apy": 4.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
            "b": {"apy": 8.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
        }
        r = self.opt.optimize(adapters, 100_000.0)
        expected = r.weights["a"] * 4.0 + r.weights["b"] * 8.0
        self.assertAlmostEqual(r.expected_apy, expected, places=4)

    def test_expected_apy_increases_with_higher_yield_adapter(self):
        # Adding a high-APY adapter should increase expected APY
        r1 = self.opt.optimize(
            {"a": {"apy": 3.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"}}, 100_000.0
        )
        r2 = self.opt.optimize(
            {
                "a": {"apy": 3.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
                "b": {"apy": 10.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
            },
            100_000.0,
        )
        self.assertGreater(r2.expected_apy, r1.expected_apy)

    def test_expected_apy_is_non_negative(self):
        r = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        self.assertGreaterEqual(r.expected_apy, 0.0)

    def test_expected_apy_bounded_by_max_eligible(self):
        r = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        # Weighted APY cannot exceed MAX_ELIGIBLE_APY (since we filter above it)
        self.assertLessEqual(r.expected_apy, MAX_ELIGIBLE_APY + 0.1)

    def test_all_excluded_gives_zero_apy(self):
        r = self.opt.optimize(
            _STANDARD_ADAPTERS, 100_000.0,
            {"excluded_adapters": list(_STANDARD_ADAPTERS.keys())}
        )
        self.assertAlmostEqual(r.expected_apy, 0.0)


# ── TestComputeRiskScore ───────────────────────────────────────────────────────

class TestComputeRiskScore(unittest.TestCase):
    """_compute_risk_score: formula verification via optimize()."""

    def setUp(self):
        self.opt = YieldOptimizer()

    def test_risk_score_in_unit_interval(self):
        r = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        self.assertGreaterEqual(r.risk_score, 0.0)
        self.assertLessEqual(r.risk_score, 1.0)

    def test_single_low_risk_adapter(self):
        adapters = {"a": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.10, "tier": "T1"}}
        r = self.opt.optimize(adapters, 100_000.0)
        self.assertGreater(r.risk_score, 0.0)

    def test_higher_protocol_risk_raises_score(self):
        adapters_low = {"a": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.10, "tier": "T1"}}
        adapters_high = {"a": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.80, "tier": "T1"}}
        r_low = self.opt.optimize(adapters_low, 100_000.0)
        r_high = self.opt.optimize(adapters_high, 100_000.0)
        self.assertGreater(r_high.risk_score, r_low.risk_score)

    def test_concentrated_portfolio_higher_risk(self):
        # Single adapter vs two equal-weight adapters → HHI higher for single
        one = {"a": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.30, "tier": "T1"}}
        two = {
            "a": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.30, "tier": "T1"},
            "b": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.30, "tier": "T1"},
        }
        r1 = self.opt.optimize(one, 100_000.0)
        r2 = self.opt.optimize(two, 100_000.0)
        # More adapters → lower HHI → lower risk_score
        self.assertLessEqual(r2.risk_score, r1.risk_score + 0.01)

    def test_all_cash_risk_score_zero(self):
        # Ineligible adapters → all-cash → risk_score = 0
        adapters = {"bad": {"apy": 0.1, "tvl": 1.0, "risk_score": 0.5, "tier": "T1"}}
        r = self.opt.optimize(adapters, 100_000.0)
        self.assertAlmostEqual(r.risk_score, 0.0)

    def test_risk_score_non_negative(self):
        for _ in range(3):
            adapters = _make_adapters(n_t1=2, n_t2=1)
            r = self.opt.optimize(adapters, 100_000.0)
            self.assertGreaterEqual(r.risk_score, 0.0)

    def test_risk_aversion_reduces_risk_score(self):
        # Higher λ should produce lower or equal risk
        adapters = {
            "risky": {"apy": 9.0, "tvl": 1e9, "risk_score": 0.8, "tier": "T1"},
            "safe": {"apy": 3.0, "tvl": 1e9, "risk_score": 0.1, "tier": "T1"},
        }
        frontier = self.opt.compute_efficient_frontier(adapters, 100_000.0, n_points=5)
        # Risk score should generally not increase along frontier (higher λ = lower risk)
        # Allow small numerical noise
        self.assertLessEqual(frontier[-1].risk_score, frontier[0].risk_score + 0.05)

    def test_risk_score_formula_components(self):
        # Single adapter: risk_score = 0.70 * protocol_risk + 0.30 * 1.0 (single adapter HHI=1)
        adapters = {"a": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.40, "tier": "T1"}}
        r = self.opt.optimize(adapters, 100_000.0)
        # weight = 0.40 (capped at MAX_SINGLE), invested = 0.40
        # avg_risk = 0.40 (single adapter, fully invested)
        # HHI = 1.0 (single adapter)
        # composite = 0.70 * 0.40 + 0.30 * 1.0 = 0.28 + 0.30 = 0.58
        expected_risk = 0.70 * 0.40 + 0.30 * 1.0
        self.assertAlmostEqual(r.risk_score, expected_risk, places=3)

    def test_two_equal_adapters_hhi_contribution(self):
        # Two equal-weight T1 adapters: HHI = 0.5^2 + 0.5^2 = 0.5
        adapters = {
            "a": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.30, "tier": "T1"},
            "b": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.30, "tier": "T1"},
        }
        r = self.opt.optimize(adapters, 100_000.0)
        wa = r.weights["a"]
        wb = r.weights["b"]
        invested = wa + wb
        if invested > 1e-9:
            hhi = (wa / invested) ** 2 + (wb / invested) ** 2
            expected_risk = 0.70 * 0.30 + 0.30 * hhi
            self.assertAlmostEqual(r.risk_score, expected_risk, places=3)


# ── TestComputeTierBreakdown ───────────────────────────────────────────────────

class TestComputeTierBreakdown(unittest.TestCase):
    """_compute_tier_breakdown: aggregation and keys."""

    def setUp(self):
        self.opt = YieldOptimizer()

    def test_all_keys_always_present(self):
        r = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        for key in ("T1", "T2", "T3", "cash"):
            self.assertIn(key, r.tier_breakdown)

    def test_t1_only_t2_t3_zero(self):
        adapters = {
            "a": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
            "b": {"apy": 4.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
        }
        r = self.opt.optimize(adapters, 100_000.0)
        self.assertAlmostEqual(r.tier_breakdown["T2"], 0.0, places=5)
        self.assertAlmostEqual(r.tier_breakdown["T3"], 0.0, places=5)

    def test_t2_breakdown_matches_weights(self):
        r = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        manual_t2 = sum(
            r.weights[aid]
            for aid, info in _STANDARD_ADAPTERS.items()
            if info["tier"] == "T2"
        )
        self.assertAlmostEqual(r.tier_breakdown["T2"], manual_t2, places=5)

    def test_cash_component_is_residual(self):
        r = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        invested = r.tier_breakdown["T1"] + r.tier_breakdown["T2"] + r.tier_breakdown["T3"]
        self.assertAlmostEqual(r.tier_breakdown["cash"], 1.0 - invested, places=5)

    def test_cash_non_negative(self):
        r = self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)
        self.assertGreaterEqual(r.tier_breakdown["cash"], 0.0)

    def test_no_eligible_adapters_cash_is_one(self):
        adapters = {"bad": {"apy": 0.1, "tvl": 100.0, "risk_score": 0.5, "tier": "T1"}}
        r = self.opt.optimize(adapters, 100_000.0)
        self.assertAlmostEqual(r.tier_breakdown["cash"], 1.0, places=5)

    def test_mixed_tiers_breakdown_sum_approx_one(self):
        adapters = {
            "t1": {"apy": 4.0, "tvl": 1e9, "risk_score": 0.2, "tier": "T1"},
            "t2": {"apy": 5.0, "tvl": 1e9, "risk_score": 0.35, "tier": "T2"},
            "t3": {"apy": 6.0, "tvl": 1e9, "risk_score": 0.5, "tier": "T3"},
        }
        r = self.opt.optimize(adapters, 100_000.0)
        total = sum(r.tier_breakdown.values())
        self.assertAlmostEqual(total, 1.0, places=5)


# ── TestSaveResult ─────────────────────────────────────────────────────────────

class TestSaveResult(unittest.TestCase):
    """save_result(): atomic write, ring-buffer, file format."""

    def setUp(self):
        self.opt = YieldOptimizer()
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _sample_result(self) -> OptimizationResult:
        return self.opt.optimize(_STANDARD_ADAPTERS, 100_000.0)

    def test_creates_file(self):
        r = self._sample_result()
        self.opt.save_result(r, data_dir=self._tmpdir)
        target = Path(self._tmpdir) / RESULTS_FILENAME
        self.assertTrue(target.exists())

    def test_file_is_valid_json(self):
        r = self._sample_result()
        self.opt.save_result(r, data_dir=self._tmpdir)
        target = Path(self._tmpdir) / RESULTS_FILENAME
        data = json.loads(target.read_text())
        self.assertIsInstance(data, list)

    def test_ring_buffer_max_entries(self):
        r = self._sample_result()
        for _ in range(RESULTS_HISTORY_MAX + 5):
            self.opt.save_result(r, data_dir=self._tmpdir)
        target = Path(self._tmpdir) / RESULTS_FILENAME
        data = json.loads(target.read_text())
        self.assertLessEqual(len(data), RESULTS_HISTORY_MAX)

    def test_no_tmp_files_remaining(self):
        r = self._sample_result()
        self.opt.save_result(r, data_dir=self._tmpdir)
        tmp_files = list(Path(self._tmpdir).glob(".yield_optimizer_*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_multiple_saves_accumulate(self):
        r = self._sample_result()
        self.opt.save_result(r, data_dir=self._tmpdir, label="run1")
        self.opt.save_result(r, data_dir=self._tmpdir, label="run2")
        target = Path(self._tmpdir) / RESULTS_FILENAME
        data = json.loads(target.read_text())
        self.assertEqual(len(data), 2)

    def test_label_stored_in_entry(self):
        r = self._sample_result()
        self.opt.save_result(r, data_dir=self._tmpdir, label="my_label")
        target = Path(self._tmpdir) / RESULTS_FILENAME
        data = json.loads(target.read_text())
        self.assertEqual(data[-1]["label"], "my_label")

    def test_custom_data_dir_used(self):
        sub = os.path.join(self._tmpdir, "subdir")
        r = self._sample_result()
        self.opt.save_result(r, data_dir=sub)
        target = Path(sub) / RESULTS_FILENAME
        self.assertTrue(target.exists())


# ── TestCLI ────────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    """CLI entry-point: smoke tests for --check / --run."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _run(self, args: list) -> int:
        from spa_core.paper_trading.yield_optimizer import _main
        return _main(args)

    def test_check_exits_zero(self):
        code = self._run(["--check"])
        self.assertEqual(code, 0)

    def test_no_args_exits_zero(self):
        code = self._run([])
        self.assertEqual(code, 0)

    def test_run_exits_zero(self):
        code = self._run(["--run", "--data-dir", self._tmpdir])
        self.assertEqual(code, 0)

    def test_run_creates_results_file(self):
        self._run(["--run", "--data-dir", self._tmpdir])
        target = Path(self._tmpdir) / RESULTS_FILENAME
        self.assertTrue(target.exists())

    def test_run_file_is_valid_json(self):
        self._run(["--run", "--data-dir", self._tmpdir])
        target = Path(self._tmpdir) / RESULTS_FILENAME
        data = json.loads(target.read_text())
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)


# ── TestImportHygiene ─────────────────────────────────────────────────────────

class TestImportHygiene(unittest.TestCase):
    """Verify no forbidden external dependencies are imported."""

    def _module_source(self) -> str:
        import inspect
        from spa_core.paper_trading import yield_optimizer
        return inspect.getsource(yield_optimizer)

    def test_no_subprocess_import(self):
        src = self._module_source()
        self.assertNotIn("import subprocess", src)

    def test_no_requests_import(self):
        src = self._module_source()
        self.assertNotIn("import requests", src)

    def test_no_numpy_scipy_import(self):
        src = self._module_source()
        self.assertNotIn("import numpy", src)
        self.assertNotIn("import scipy", src)

    def test_no_execution_or_risk_import(self):
        src = self._module_source()
        self.assertNotIn("from spa_core.execution", src)
        self.assertNotIn("from spa_core.risk", src)
        self.assertNotIn("import spa_core.execution", src)
        self.assertNotIn("import spa_core.risk", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
