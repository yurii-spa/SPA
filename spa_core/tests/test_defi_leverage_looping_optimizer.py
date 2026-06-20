"""
Tests for MP-948 DeFiLeverageLoopingOptimizer
Run: python3 -m unittest spa_core.tests.test_defi_leverage_looping_optimizer -v
"""

import json
import os
import sys
import unittest
import tempfile

# Ensure the repo root is on the path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_leverage_looping_optimizer import (
    DeFiLeverageLoopingOptimizer,
    _clamp,
    _grade_from_score,
    _classify,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(
    name="loopETH",
    supply_apy_pct=6.0,
    borrow_apy_pct=2.0,
    ltv=0.8,
    liquidation_ltv=None,
    max_loops=10,
    reward_apy_pct=0.0,
):
    p = {
        "name": name,
        "supply_apy_pct": supply_apy_pct,
        "borrow_apy_pct": borrow_apy_pct,
        "ltv": ltv,
        "max_loops": max_loops,
        "reward_apy_pct": reward_apy_pct,
    }
    if liquidation_ltv is not None:
        p["liquidation_ltv"] = liquidation_ltv
    return p


NO_LOG = {"write_log": False}


# ===========================================================================
# 1. Instantiation and structure
# ===========================================================================

class TestInstantiation(unittest.TestCase):
    def test_instantiation(self):
        self.assertIsNotNone(DeFiLeverageLoopingOptimizer())

    def test_analyze_returns_dict(self):
        a = DeFiLeverageLoopingOptimizer()
        self.assertIsInstance(a.analyze([_pool()], NO_LOG), dict)

    def test_top_level_keys(self):
        a = DeFiLeverageLoopingOptimizer()
        out = a.analyze([_pool()], NO_LOG)
        for key in ("results", "aggregates", "timestamp"):
            self.assertIn(key, out)

    def test_results_length(self):
        a = DeFiLeverageLoopingOptimizer()
        out = a.analyze([_pool(), _pool(name="b")], NO_LOG)
        self.assertEqual(len(out["results"]), 2)

    def test_per_pool_keys(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool()], NO_LOG)["results"][0]
        for key in (
            "name", "supply_apy_pct", "borrow_apy_pct", "reward_apy_pct",
            "ltv", "liquidation_ltv", "max_loops", "optimal_loops",
            "leverage_ratio", "net_apy_pct", "current_ltv", "health_factor",
            "liquidation_buffer_pct", "score", "classification", "grade",
            "flags",
        ):
            self.assertIn(key, r)

    def test_symbol_fallback_for_name(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([{"symbol": "wstETH", "supply_apy_pct": 6.0,
                        "borrow_apy_pct": 2.0, "ltv": 0.8}], NO_LOG)
        self.assertEqual(r["results"][0]["name"], "wstETH")

    def test_unknown_name(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([{"supply_apy_pct": 6.0, "borrow_apy_pct": 2.0,
                        "ltv": 0.8}], NO_LOG)
        self.assertEqual(r["results"][0]["name"], "unknown")

    def test_timestamp_float(self):
        a = DeFiLeverageLoopingOptimizer()
        self.assertIsInstance(a.analyze([_pool()], NO_LOG)["timestamp"], float)


# ===========================================================================
# 2. _clamp helper
# ===========================================================================

class TestClamp(unittest.TestCase):
    def test_within(self):
        self.assertEqual(_clamp(50.0, 0.0, 100.0), 50.0)

    def test_below(self):
        self.assertEqual(_clamp(-10.0, 0.0, 100.0), 0.0)

    def test_above(self):
        self.assertEqual(_clamp(150.0, 0.0, 100.0), 100.0)

    def test_low_boundary(self):
        self.assertEqual(_clamp(0.0, 0.0, 100.0), 0.0)

    def test_high_boundary(self):
        self.assertEqual(_clamp(100.0, 0.0, 100.0), 100.0)


# ===========================================================================
# 3. Grade & classification helpers
# ===========================================================================

class TestGrade(unittest.TestCase):
    def test_a(self):
        self.assertEqual(_grade_from_score(90.0), "A")

    def test_a_boundary(self):
        self.assertEqual(_grade_from_score(85.0), "A")

    def test_b_boundary(self):
        self.assertEqual(_grade_from_score(70.0), "B")

    def test_c_boundary(self):
        self.assertEqual(_grade_from_score(55.0), "C")

    def test_d_boundary(self):
        self.assertEqual(_grade_from_score(40.0), "D")

    def test_f(self):
        self.assertEqual(_grade_from_score(30.0), "F")


class TestClassify(unittest.TestCase):
    def test_negative_carry(self):
        self.assertEqual(_classify(-1.0, 5.0), "NEGATIVE_CARRY")

    def test_unprofitable_equal(self):
        self.assertEqual(_classify(5.0, 5.0), "UNPROFITABLE")

    def test_unprofitable_below(self):
        self.assertEqual(_classify(3.0, 5.0), "UNPROFITABLE")

    def test_highly_profitable(self):
        # uplift (10-5=5) >= base (5) -> HIGHLY_PROFITABLE
        self.assertEqual(_classify(10.0, 5.0), "HIGHLY_PROFITABLE")

    def test_profitable(self):
        # uplift 2 (< base 5, >= 1) -> PROFITABLE
        self.assertEqual(_classify(7.0, 5.0), "PROFITABLE")

    def test_marginal(self):
        # uplift 0.5 (< 1) -> MARGINAL
        self.assertEqual(_classify(5.5, 5.0), "MARGINAL")


# ===========================================================================
# 4. Geometric multipliers / leverage
# ===========================================================================

class TestLeverageMath(unittest.TestCase):
    def test_leverage_ratio_formula(self):
        # ltv 0.8, optimal at max loops 10 -> supplied_mult = (1-0.8^11)/(1-0.8)
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(ltv=0.8, supply_apy_pct=6.0, borrow_apy_pct=2.0,
                             max_loops=10)], NO_LOG)["results"][0]
        expected = (1.0 - 0.8 ** 11) / (1.0 - 0.8)
        self.assertAlmostEqual(r["leverage_ratio"], round(expected, 6), places=5)

    def test_leverage_increases_with_ltv(self):
        a = DeFiLeverageLoopingOptimizer()
        low = a.analyze([_pool(ltv=0.5)], NO_LOG)["results"][0]["leverage_ratio"]
        high = a.analyze([_pool(ltv=0.8)], NO_LOG)["results"][0]["leverage_ratio"]
        self.assertGreater(high, low)

    def test_zero_loops_leverage_one(self):
        # borrow > supply -> optimal 0 loops -> leverage 1.0
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=3.0, borrow_apy_pct=5.0,
                             ltv=0.8)], NO_LOG)["results"][0]
        self.assertEqual(r["optimal_loops"], 0)
        self.assertAlmostEqual(r["leverage_ratio"], 1.0)

    def test_health_factor_infinite_no_debt(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=3.0, borrow_apy_pct=5.0,
                             ltv=0.8)], NO_LOG)["results"][0]
        # 0 loops -> no borrow -> capped health factor
        self.assertEqual(r["health_factor"], 999.0)

    def test_health_factor_finite_with_leverage(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=6.0, borrow_apy_pct=2.0,
                             ltv=0.8)], NO_LOG)["results"][0]
        self.assertLess(r["health_factor"], 999.0)
        self.assertGreater(r["health_factor"], 0.0)


# ===========================================================================
# 5. Net APY and optimal-loop selection
# ===========================================================================

class TestNetApyOptimal(unittest.TestCase):
    def test_profitable_loops_to_max(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=6.0, borrow_apy_pct=2.0,
                             ltv=0.8, max_loops=10)], NO_LOG)["results"][0]
        self.assertEqual(r["optimal_loops"], 10)

    def test_negative_carry_zero_loops(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=2.0, borrow_apy_pct=8.0,
                             ltv=0.8)], NO_LOG)["results"][0]
        self.assertEqual(r["optimal_loops"], 0)

    def test_net_apy_at_zero_loops_equals_supply(self):
        # When optimal is 0 loops, net apy == base supply apy
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=3.0, borrow_apy_pct=9.0,
                             ltv=0.8, reward_apy_pct=0.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["net_apy_pct"], 3.0)

    def test_net_apy_amplified_when_profitable(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=6.0, borrow_apy_pct=2.0,
                             ltv=0.8, max_loops=10)], NO_LOG)["results"][0]
        self.assertGreater(r["net_apy_pct"], 6.0)

    def test_reward_apy_boosts_net(self):
        a = DeFiLeverageLoopingOptimizer()
        base = a.analyze([_pool(supply_apy_pct=4.0, borrow_apy_pct=3.0,
                                ltv=0.7, reward_apy_pct=0.0)], NO_LOG)["results"][0]
        boosted = a.analyze([_pool(supply_apy_pct=4.0, borrow_apy_pct=3.0,
                                   ltv=0.7, reward_apy_pct=5.0)], NO_LOG)["results"][0]
        self.assertGreater(boosted["net_apy_pct"], base["net_apy_pct"])

    def test_optimal_loops_within_cap(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(max_loops=3, supply_apy_pct=6.0,
                             borrow_apy_pct=2.0, ltv=0.8)], NO_LOG)["results"][0]
        self.assertLessEqual(r["optimal_loops"], 3)
        self.assertEqual(r["optimal_loops"], 3)

    def test_net_apy_truly_negative_classification(self):
        # Construct so that even optimal (0 loops) supply is negative-ish:
        # supply 0 not allowed (invalid), so use reward only with high borrow
        # and tiny supply so base net (0 loops) = supply, still >=0.
        # Instead test classification NEGATIVE_CARRY when net<0 is impossible
        # at 0 loops; verify flag instead.
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=1.0, borrow_apy_pct=9.0,
                             ltv=0.8)], NO_LOG)["results"][0]
        self.assertIn("NEGATIVE_CARRY", r["flags"])


# ===========================================================================
# 6. Liquidation buffer & defaults
# ===========================================================================

class TestLiquidation(unittest.TestCase):
    def test_default_liquidation_ltv(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(ltv=0.8)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["liquidation_ltv"], 0.85, places=6)

    def test_explicit_liquidation_ltv(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(ltv=0.8, liquidation_ltv=0.9)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["liquidation_ltv"], 0.9, places=6)

    def test_liquidation_ltv_clamped_below_one(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(ltv=0.8, liquidation_ltv=1.5)], NO_LOG)["results"][0]
        self.assertLess(r["liquidation_ltv"], 1.0)

    def test_buffer_positive_for_safe(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(ltv=0.5, supply_apy_pct=6.0,
                             borrow_apy_pct=2.0)], NO_LOG)["results"][0]
        self.assertGreater(r["liquidation_buffer_pct"], 0.0)

    def test_current_ltv_zero_no_loops(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=2.0, borrow_apy_pct=9.0,
                             ltv=0.8)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["current_ltv"], 0.0)


# ===========================================================================
# 7. Flags
# ===========================================================================

class TestFlags(unittest.TestCase):
    def test_insufficient_data_ltv_zero(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(ltv=0.0)], NO_LOG)["results"][0]
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_data_ltv_one(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(ltv=1.0)], NO_LOG)["results"][0]
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_data_no_yield(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=0.0, reward_apy_pct=0.0,
                             ltv=0.8)], NO_LOG)["results"][0]
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_data_only_flag(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(ltv=0.0)], NO_LOG)["results"][0]
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_negative_carry_flag(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=2.0, borrow_apy_pct=5.0,
                             ltv=0.8)], NO_LOG)["results"][0]
        self.assertIn("NEGATIVE_CARRY", r["flags"])

    def test_negative_carry_with_reward(self):
        # borrow 5 <= supply 2 + reward 4 = 6 -> NOT negative carry
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=2.0, borrow_apy_pct=5.0,
                             reward_apy_pct=4.0, ltv=0.7)], NO_LOG)["results"][0]
        self.assertNotIn("NEGATIVE_CARRY", r["flags"])

    def test_thin_liquidation_buffer_flag(self):
        # high ltv near liquidation, full loops -> thin buffer
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(ltv=0.9, liquidation_ltv=0.92,
                             supply_apy_pct=8.0, borrow_apy_pct=2.0,
                             max_loops=10)], NO_LOG)["results"][0]
        self.assertIn("THIN_LIQUIDATION_BUFFER", r["flags"])

    def test_high_leverage_flag(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(ltv=0.85, supply_apy_pct=8.0,
                             borrow_apy_pct=2.0, max_loops=10)], NO_LOG)["results"][0]
        self.assertIn("HIGH_LEVERAGE", r["flags"])

    def test_no_profitable_loop_flag(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=2.0, borrow_apy_pct=8.0,
                             ltv=0.8)], NO_LOG)["results"][0]
        self.assertIn("NO_PROFITABLE_LOOP", r["flags"])

    def test_aggressive_ltv_flag(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(ltv=0.9, supply_apy_pct=8.0,
                             borrow_apy_pct=2.0)], NO_LOG)["results"][0]
        self.assertIn("AGGRESSIVE_LTV", r["flags"])

    def test_no_aggressive_ltv_below_threshold(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(ltv=0.8)], NO_LOG)["results"][0]
        self.assertNotIn("AGGRESSIVE_LTV", r["flags"])

    def test_flags_is_list(self):
        a = DeFiLeverageLoopingOptimizer()
        self.assertIsInstance(a.analyze([_pool()], NO_LOG)["results"][0]["flags"], list)

    def test_clean_pool_no_negative_carry(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(ltv=0.5, supply_apy_pct=8.0,
                             borrow_apy_pct=2.0, max_loops=5)], NO_LOG)["results"][0]
        self.assertNotIn("NEGATIVE_CARRY", r["flags"])
        self.assertNotIn("NO_PROFITABLE_LOOP", r["flags"])


# ===========================================================================
# 8. Classification (instance-level)
# ===========================================================================

class TestClassificationLevels(unittest.TestCase):
    def test_highly_profitable(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=6.0, borrow_apy_pct=1.0,
                             ltv=0.8, max_loops=10)], NO_LOG)["results"][0]
        self.assertEqual(r["classification"], "HIGHLY_PROFITABLE")

    def test_unprofitable_when_zero_loops(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=3.0, borrow_apy_pct=9.0,
                             ltv=0.8)], NO_LOG)["results"][0]
        # net == supply -> UNPROFITABLE
        self.assertEqual(r["classification"], "UNPROFITABLE")

    def test_grade_assigned(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool()], NO_LOG)["results"][0]
        self.assertIn(r["grade"], ("A", "B", "C", "D", "F"))

    def test_score_clamped(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool(supply_apy_pct=50.0, borrow_apy_pct=1.0,
                             ltv=0.85, max_loops=10)], NO_LOG)["results"][0]
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)


# ===========================================================================
# 9. Aggregates
# ===========================================================================

class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.a = DeFiLeverageLoopingOptimizer()
        self.pools = [
            _pool(name="Good", supply_apy_pct=8.0, borrow_apy_pct=1.0,
                  ltv=0.8, max_loops=10),
            _pool(name="Bad", supply_apy_pct=2.0, borrow_apy_pct=9.0, ltv=0.8),
            _pool(name="Mid", supply_apy_pct=5.0, borrow_apy_pct=4.0, ltv=0.6),
        ]
        self.out = self.a.analyze(self.pools, NO_LOG)
        self.agg = self.out["aggregates"]

    def test_aggregate_keys(self):
        for key in (
            "best_loop_opportunity", "worst_loop_opportunity",
            "average_net_apy_pct", "highest_leverage_pool",
            "negative_carry_count", "profitable_count",
        ):
            self.assertIn(key, self.agg)

    def test_best_opportunity(self):
        self.assertEqual(self.agg["best_loop_opportunity"], "Good")

    def test_worst_opportunity(self):
        self.assertEqual(self.agg["worst_loop_opportunity"], "Bad")

    def test_highest_leverage(self):
        # Good loops to max at ltv 0.8 -> highest leverage
        self.assertEqual(self.agg["highest_leverage_pool"], "Good")

    def test_negative_carry_count(self):
        self.assertEqual(self.agg["negative_carry_count"], 1)

    def test_profitable_count(self):
        self.assertGreaterEqual(self.agg["profitable_count"], 1)

    def test_average_net_apy_is_float(self):
        self.assertIsInstance(self.agg["average_net_apy_pct"], float)


# ===========================================================================
# 10. Empty input
# ===========================================================================

class TestEmptyInput(unittest.TestCase):
    def test_empty_results(self):
        a = DeFiLeverageLoopingOptimizer()
        self.assertEqual(a.analyze([], NO_LOG)["results"], [])

    def test_empty_aggregates(self):
        a = DeFiLeverageLoopingOptimizer()
        agg = a.analyze([], NO_LOG)["aggregates"]
        self.assertIsNone(agg["best_loop_opportunity"])
        self.assertIsNone(agg["worst_loop_opportunity"])
        self.assertIsNone(agg["highest_leverage_pool"])
        self.assertEqual(agg["negative_carry_count"], 0)
        self.assertEqual(agg["profitable_count"], 0)
        self.assertEqual(agg["average_net_apy_pct"], 0.0)


# ===========================================================================
# 11. Input validation & defaults
# ===========================================================================

class TestInputValidation(unittest.TestCase):
    def test_non_list_raises(self):
        a = DeFiLeverageLoopingOptimizer()
        with self.assertRaises(TypeError):
            a.analyze("nope", NO_LOG)

    def test_dict_raises(self):
        a = DeFiLeverageLoopingOptimizer()
        with self.assertRaises(TypeError):
            a.analyze({"name": "x"}, NO_LOG)

    def test_default_max_loops(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([{"name": "x", "supply_apy_pct": 6.0,
                        "borrow_apy_pct": 2.0, "ltv": 0.8}], NO_LOG)["results"][0]
        self.assertEqual(r["max_loops"], 10)

    def test_default_reward_zero(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([{"name": "x", "supply_apy_pct": 6.0,
                        "borrow_apy_pct": 2.0, "ltv": 0.8}], NO_LOG)["results"][0]
        self.assertEqual(r["reward_apy_pct"], 0.0)

    def test_config_none_writes_default(self):
        # config None defaults to write_log True; just ensure no crash on a
        # custom temp path via config dict.
        a = DeFiLeverageLoopingOptimizer()
        out = a.analyze([_pool()], None)
        self.assertIn("results", out)


# ===========================================================================
# 12. Logging / persistence
# ===========================================================================

class TestLogging(unittest.TestCase):
    def test_no_log_disabled(self):
        a = DeFiLeverageLoopingOptimizer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_pool()], {"write_log": False, "log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_log_written(self):
        a = DeFiLeverageLoopingOptimizer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_pool()], {"write_log": True, "log_path": path})
            self.assertTrue(os.path.exists(path))

    def test_log_is_valid_json_array(self):
        a = DeFiLeverageLoopingOptimizer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_pool()], {"write_log": True, "log_path": path})
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_log_entry_fields(self):
        a = DeFiLeverageLoopingOptimizer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_pool()], {"write_log": True, "log_path": path})
            with open(path) as fh:
                entry = json.load(fh)[0]
            self.assertIn("timestamp", entry)
            self.assertIn("item_count", entry)
            self.assertIn("aggregates", entry)

    def test_ring_buffer_cap(self):
        a = DeFiLeverageLoopingOptimizer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(103):
                a.analyze([_pool()], {"write_log": True, "log_path": path})
            with open(path) as fh:
                self.assertEqual(len(json.load(fh)), 100)

    def test_atomic_log_direct(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _atomic_log(path, {"x": 1})
            _atomic_log(path, {"x": 2})
            with open(path) as fh:
                self.assertEqual(len(json.load(fh)), 2)

    def test_atomic_log_corrupt_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                fh.write("{garbage")
            _atomic_log(path, {"x": 1})
            with open(path) as fh:
                self.assertEqual(json.load(fh), [{"x": 1}])


# ===========================================================================
# 13. Determinism
# ===========================================================================

class TestDeterminism(unittest.TestCase):
    def test_repeatable(self):
        a = DeFiLeverageLoopingOptimizer()
        r1 = a.analyze([_pool()], NO_LOG)["results"]
        r2 = a.analyze([_pool()], NO_LOG)["results"]
        self.assertEqual(r1, r2)

    def test_independent_pools(self):
        a = DeFiLeverageLoopingOptimizer()
        out = a.analyze([
            _pool(name="A", supply_apy_pct=8.0, borrow_apy_pct=1.0, ltv=0.8),
            _pool(name="B", supply_apy_pct=2.0, borrow_apy_pct=9.0, ltv=0.8),
        ], NO_LOG)
        self.assertGreater(out["results"][0]["score"], out["results"][1]["score"])

    def test_net_apy_rounded_six(self):
        a = DeFiLeverageLoopingOptimizer()
        r = a.analyze([_pool()], NO_LOG)["results"][0]
        self.assertEqual(r["net_apy_pct"], round(r["net_apy_pct"], 6))


if __name__ == "__main__":
    unittest.main()
