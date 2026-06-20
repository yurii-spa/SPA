"""tests/test_kelly_optimizer.py — MP-1231 Kelly sizing & parameter optimization.

38 unit tests covering:
  - kelly_criterion / kelly_fraction math (verified against textbook values)
  - KellySizer.compute_weights (sum=1.0, fallbacks, edge cases)
  - ParameterOptimizer grid search (81 combos, scoring, save, sorting)
  - DynamicAllocator (Kelly×equal blend, RiskConfig caps, edge cases)

Stdlib only. No external deps.
"""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.allocator.kelly_sizer import (
    DEFAULT_RISK_FREE_PCT,
    KellyResult,
    KellySizer,
    hack_probability,
    kelly_criterion,
    kelly_fraction,
)
from spa_core.allocator.parameter_optimizer import (
    DEFAULT_GRID,
    OptimizationResult,
    ParameterOptimizer,
)
from spa_core.allocator.dynamic_allocator import (
    T1_CAP,
    T2_CAP,
    T2_TOTAL_CAP,
    DynamicAllocator,
    DynamicAllocationResult,
)


# Синтетические адаптеры (protocol / apy_pct / tier).
def _adapters_mixed():
    return [
        {"protocol": "aave_v3", "apy_pct": 5.0, "tier": "T1"},
        {"protocol": "compound_v3", "apy_pct": 8.0, "tier": "T1"},
        {"protocol": "morpho_blue", "apy_pct": 12.0, "tier": "T2"},
        {"protocol": "yearn_v3", "apy_pct": 10.0, "tier": "T2"},
    ]


def _adapters_all_t1():
    return [
        {"protocol": "aave_v3", "apy_pct": 6.0, "tier": "T1"},
        {"protocol": "compound_v3", "apy_pct": 8.0, "tier": "T1"},
        {"protocol": "morpho_steakhouse", "apy_pct": 10.0, "tier": "T1"},
    ]


def _synthetic_equity():
    return {
        "daily": [
            {"daily_return_pct": 0.012},
            {"daily_return_pct": 0.008},
            {"daily_return_pct": 0.015},
            {"daily_return_pct": 0.005},
            {"daily_return_pct": 0.010},
        ]
    }


# ---------------------------------------------------------------------------
# Group 1: Kelly formula math (10 tests)
# ---------------------------------------------------------------------------
class TestKellyFormula(unittest.TestCase):
    def test_even_money_60pct(self):
        # Textbook: even-money bet, p=0.6 → bet 20% of bankroll.
        self.assertAlmostEqual(kelly_criterion(0.6, 1.0), 0.2, places=9)

    def test_fair_coin_zero(self):
        # p=0.5 even-money → no edge → 0.
        self.assertAlmostEqual(kelly_criterion(0.5, 1.0), 0.0, places=9)

    def test_payout_two_to_one(self):
        # p=0.7, b=2.0 → (0.7*2 - 0.3)/2 = 0.55.
        self.assertAlmostEqual(kelly_criterion(0.7, 2.0), 0.55, places=9)

    def test_nonpositive_b_returns_zero(self):
        self.assertEqual(kelly_criterion(0.9, 0.0), 0.0)
        self.assertEqual(kelly_criterion(0.9, -0.5), 0.0)

    def test_negative_fstar_unclamped(self):
        # p=0.5, b=0.5 → (0.25-0.5)/0.5 = -0.5 (raw, unclamped).
        self.assertAlmostEqual(kelly_criterion(0.5, 0.5), -0.5, places=9)

    def test_hack_probability_tiers(self):
        self.assertEqual(hack_probability("T1"), 0.005)
        self.assertEqual(hack_probability("T2"), 0.020)
        self.assertEqual(hack_probability("T3"), 0.050)

    def test_hack_probability_unknown_tier_default(self):
        self.assertEqual(hack_probability("T9"), 0.020)
        self.assertEqual(hack_probability("t1"), 0.005)  # case-insensitive

    def test_kelly_fraction_positive_edge(self):
        # T1, apy=10, rf=4 → b=0.06, p=0.995, q=0.005.
        # f* = (0.995*0.06 - 0.005)/0.06 = 0.911667; half = 0.455833.
        f = kelly_fraction(10.0, "T1", risk_free_pct=4.0, safety_factor=0.5)
        self.assertAlmostEqual(f, 0.455833, places=5)

    def test_kelly_fraction_below_risk_free_zero(self):
        # apy < risk-free → no edge → 0.
        self.assertEqual(kelly_fraction(3.0, "T1", risk_free_pct=4.0), 0.0)

    def test_half_kelly_is_half_of_full(self):
        full = kelly_fraction(12.0, "T2", risk_free_pct=4.0, safety_factor=1.0)
        half = kelly_fraction(12.0, "T2", risk_free_pct=4.0, safety_factor=0.5)
        self.assertAlmostEqual(half, full * 0.5, places=9)

    def test_kelly_fraction_clamped_to_unit(self):
        # Extreme edge would push f*>1; must clamp to 1.0.
        f = kelly_fraction(200.0, "T1", risk_free_pct=4.0, safety_factor=1.0)
        self.assertLessEqual(f, 1.0)
        self.assertGreaterEqual(f, 0.0)


# ---------------------------------------------------------------------------
# Group 2: KellySizer weights (9 tests)
# ---------------------------------------------------------------------------
class TestKellySizer(unittest.TestCase):
    def setUp(self):
        self.sizer = KellySizer()

    def test_weights_sum_to_one(self):
        res = self.sizer.compute_weights(_adapters_mixed())
        # optimal_weights rounded to 6 dp → sum tolerance at 5 dp.
        self.assertAlmostEqual(sum(res.optimal_weights.values()), 1.0, places=5)

    def test_empty_adapters(self):
        res = self.sizer.compute_weights([])
        self.assertEqual(res.optimal_weights, {})
        self.assertEqual(res.raw_kelly_fractions, {})

    def test_single_protocol_full_weight(self):
        res = self.sizer.compute_weights(
            [{"protocol": "aave_v3", "apy_pct": 9.0, "tier": "T1"}]
        )
        self.assertAlmostEqual(res.optimal_weights["aave_v3"], 1.0, places=6)

    def test_higher_apy_higher_weight(self):
        res = self.sizer.compute_weights(
            [
                {"protocol": "low", "apy_pct": 6.0, "tier": "T1"},
                {"protocol": "high", "apy_pct": 12.0, "tier": "T1"},
            ]
        )
        self.assertGreater(res.optimal_weights["high"], res.optimal_weights["low"])

    def test_t1_favored_over_t2_same_apy(self):
        # Same APY: T1 (lower hack prob) gets a larger Kelly weight.
        res = self.sizer.compute_weights(
            [
                {"protocol": "t1p", "apy_pct": 10.0, "tier": "T1"},
                {"protocol": "t2p", "apy_pct": 10.0, "tier": "T2"},
            ]
        )
        self.assertGreater(res.optimal_weights["t1p"], res.optimal_weights["t2p"])

    def test_all_zero_edge_fallback_equal(self):
        # All APY ≤ risk-free → fallback equal weight.
        res = self.sizer.compute_weights(
            [
                {"protocol": "a", "apy_pct": 2.0, "tier": "T1"},
                {"protocol": "b", "apy_pct": 3.0, "tier": "T1"},
            ]
        )
        self.assertAlmostEqual(res.optimal_weights["a"], 0.5, places=6)
        self.assertAlmostEqual(res.optimal_weights["b"], 0.5, places=6)
        self.assertTrue(any("fallback" in n.lower() for n in res.notes))

    def test_per_protocol_breakdown_populated(self):
        res = self.sizer.compute_weights(_adapters_mixed())
        for p in ("aave_v3", "morpho_blue"):
            self.assertIn(p, res.per_protocol)
            self.assertIn("hack_probability", res.per_protocol[p])
            self.assertIn("edge_pct", res.per_protocol[p])
            self.assertIn("optimal_weight", res.per_protocol[p])

    def test_raw_fractions_present_and_nonnegative(self):
        res = self.sizer.compute_weights(_adapters_mixed())
        self.assertEqual(set(res.raw_kelly_fractions), {a["protocol"] for a in _adapters_mixed()})
        for f in res.raw_kelly_fractions.values():
            self.assertGreaterEqual(f, 0.0)

    def test_result_is_serializable(self):
        res = self.sizer.compute_weights(_adapters_mixed())
        self.assertIsInstance(res, KellyResult)
        s = json.dumps(res.to_dict())  # must not raise
        self.assertIn("optimal_weights", s)


# ---------------------------------------------------------------------------
# Group 3: ParameterOptimizer (10 tests)
# ---------------------------------------------------------------------------
class TestParameterOptimizer(unittest.TestCase):
    def setUp(self):
        self.opt = ParameterOptimizer(
            adapters=_adapters_mixed(), equity_data=_synthetic_equity()
        )

    def test_grid_has_81_combinations(self):
        result = self.opt.optimize()
        self.assertEqual(result.num_combinations, 81)

    def test_default_grid_shape(self):
        self.assertEqual(set(DEFAULT_GRID), {
            "t1_cap", "t2_cap", "cash_buffer", "rebalance_threshold"
        })
        for vals in DEFAULT_GRID.values():
            self.assertEqual(len(vals), 3)

    def test_optimize_returns_result(self):
        result = self.opt.optimize()
        self.assertIsInstance(result, OptimizationResult)

    def test_best_params_has_all_keys(self):
        result = self.opt.optimize()
        self.assertEqual(set(result.best_params), {
            "t1_cap", "t2_cap", "cash_buffer", "rebalance_threshold"
        })

    def test_best_params_values_in_grid(self):
        result = self.opt.optimize()
        for k, v in result.best_params.items():
            self.assertIn(v, DEFAULT_GRID[k])

    def test_paper_sharpe_computed(self):
        sharpe = self.opt.paper_sharpe()
        self.assertGreater(sharpe, 0.0)
        self.assertTrue(math.isfinite(sharpe))

    def test_paper_sharpe_zero_without_data(self):
        opt = ParameterOptimizer(adapters=_adapters_mixed(), equity_data={})
        self.assertEqual(opt.paper_sharpe(), 0.0)

    def test_all_results_length_matches(self):
        result = self.opt.optimize()
        self.assertEqual(len(result.all_results), result.num_combinations)

    def test_results_sorted_descending(self):
        result = self.opt.optimize()
        scores = [r["score"] for r in result.all_results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_save_writes_valid_json(self):
        result = self.opt.optimize()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "optimized_params.json"
            self.opt.save(result, out)
            self.assertTrue(out.exists())
            loaded = json.loads(out.read_text())
            self.assertIn("best_params", loaded)
            self.assertEqual(set(loaded["best_params"]), {
                "t1_cap", "t2_cap", "cash_buffer", "rebalance_threshold"
            })

    def test_custom_grid_respected(self):
        opt = ParameterOptimizer(
            adapters=_adapters_mixed(),
            equity_data=_synthetic_equity(),
            grid={
                "t1_cap": [0.4],
                "t2_cap": [0.2],
                "cash_buffer": [0.05],
                "rebalance_threshold": [0.03, 0.08],
            },
        )
        result = opt.optimize()
        self.assertEqual(result.num_combinations, 2)

    def test_no_adapters_graceful(self):
        opt = ParameterOptimizer(adapters=[], equity_data=_synthetic_equity())
        result = opt.optimize()
        self.assertEqual(result.num_combinations, 81)
        self.assertIn("t1_cap", result.best_params)


# ---------------------------------------------------------------------------
# Group 4: DynamicAllocator (9 tests)
# ---------------------------------------------------------------------------
class TestDynamicAllocator(unittest.TestCase):
    def setUp(self):
        self.alloc = DynamicAllocator()

    def test_returns_result_type(self):
        res = self.alloc.allocate(_adapters_mixed())
        self.assertIsInstance(res, DynamicAllocationResult)

    def test_weights_within_unit_sum(self):
        res = self.alloc.allocate(_adapters_mixed())
        total = sum(res.target_weights.values())
        self.assertLessEqual(total, 1.0 + 1e-6)
        self.assertAlmostEqual(total + res.cash_pct, 1.0, places=5)

    def test_respects_t1_cap(self):
        res = self.alloc.allocate(_adapters_mixed())
        tier = {a["protocol"]: a["tier"] for a in _adapters_mixed()}
        for p, w in res.target_weights.items():
            if tier[p] == "T1":
                self.assertLessEqual(w, T1_CAP + 1e-6)

    def test_respects_t2_cap(self):
        res = self.alloc.allocate(_adapters_mixed())
        tier = {a["protocol"]: a["tier"] for a in _adapters_mixed()}
        for p, w in res.target_weights.items():
            if tier[p] == "T2":
                self.assertLessEqual(w, T2_CAP + 1e-6)

    def test_respects_t2_total_cap(self):
        # Many high-APY T2 protocols would blow past the 50% T2-total cap.
        adapters = [
            {"protocol": f"t2_{i}", "apy_pct": 15.0, "tier": "T2"} for i in range(6)
        ]
        res = self.alloc.allocate(adapters)
        self.assertLessEqual(res.t2_pct, T2_TOTAL_CAP + 1e-6)

    def test_no_t2_protocols(self):
        res = self.alloc.allocate(_adapters_all_t1())
        self.assertAlmostEqual(res.t2_pct, 0.0, places=6)
        for p, w in res.target_weights.items():
            self.assertLessEqual(w, T1_CAP + 1e-6)

    def test_empty_adapters_all_cash(self):
        res = self.alloc.allocate([])
        self.assertEqual(res.target_weights, {})
        self.assertAlmostEqual(res.cash_pct, 1.0, places=6)

    def test_single_protocol(self):
        res = self.alloc.allocate(
            [{"protocol": "aave_v3", "apy_pct": 9.0, "tier": "T1"}]
        )
        # Single T1 protocol capped at T1_CAP; remainder is cash.
        self.assertLessEqual(res.target_weights["aave_v3"], T1_CAP + 1e-6)

    def test_blend_zero_equals_equal_weight(self):
        # kelly_blend=0 → pure equal weight; all-T1 under cap → ~1/3 each.
        alloc = DynamicAllocator(kelly_blend=0.0)
        res = alloc.allocate(_adapters_all_t1())
        for w in res.target_weights.values():
            self.assertAlmostEqual(w, 1.0 / 3.0, places=4)

    def test_blend_one_equals_pure_kelly(self):
        # kelly_blend=1 → pure Kelly; all-T1 weights stay under cap → unchanged.
        alloc = DynamicAllocator(kelly_blend=1.0)
        adapters = _adapters_all_t1()
        res = alloc.allocate(adapters)
        kelly = KellySizer().compute_weights(adapters).optimal_weights
        for p in kelly:
            self.assertAlmostEqual(res.target_weights[p], kelly[p], places=5)

    def test_blend_is_fifty_fifty_by_default(self):
        res = self.alloc.allocate(_adapters_all_t1())
        kelly = KellySizer().compute_weights(_adapters_all_t1()).optimal_weights
        # Default blend: each blended weight = 0.5*kelly + 0.5*(1/3).
        for p in kelly:
            expected = 0.5 * kelly[p] + 0.5 * (1.0 / 3.0)
            self.assertAlmostEqual(res.blended_weights[p], expected, places=4)


if __name__ == "__main__":
    unittest.main()
