"""
MP-836 LendingPoolUtilizationAnalyzer — unit tests (>=60)
Run: python3 -m unittest spa_core.tests.test_lending_pool_utilization_analyzer -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.lending_pool_utilization_analyzer import (
    analyze,
    log_result,
    _utilization,
    _borrow_rate,
    _supply_rate,
    _regime,
    _liquidity_risk,
    _health_score,
    _grade,
    _flags,
    _recommendations,
)


def _pool(name="PoolX", total_supplied=100.0, total_borrowed=80.0,
          optimal_utilization=0.80, base_rate=0.0, slope1=0.04,
          slope2=0.75, reserve_factor=0.10):
    return {
        "name": name,
        "total_supplied": total_supplied,
        "total_borrowed": total_borrowed,
        "optimal_utilization": optimal_utilization,
        "base_rate": base_rate,
        "slope1": slope1,
        "slope2": slope2,
        "reserve_factor": reserve_factor,
    }


# ---------------------------------------------------------------------------
# _utilization
# ---------------------------------------------------------------------------

class TestUtilization(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(_utilization(100, 80), 0.80)

    def test_zero_supply(self):
        self.assertEqual(_utilization(0, 50), 0.0)

    def test_negative_supply(self):
        self.assertEqual(_utilization(-10, 50), 0.0)

    def test_none_supply(self):
        self.assertEqual(_utilization(None, 50), 0.0)

    def test_zero_borrowed(self):
        self.assertEqual(_utilization(100, 0), 0.0)

    def test_full_utilization(self):
        self.assertAlmostEqual(_utilization(100, 100), 1.0)

    def test_over_one(self):
        # borrowed > supplied (e.g. accrued interest) still computed
        self.assertAlmostEqual(_utilization(100, 110), 1.10)

    def test_negative_borrowed_clamped(self):
        self.assertEqual(_utilization(100, -10), 0.0)


# ---------------------------------------------------------------------------
# _borrow_rate
# ---------------------------------------------------------------------------

class TestBorrowRate(unittest.TestCase):
    def test_zero_util(self):
        self.assertAlmostEqual(_borrow_rate(0.0, 0.0, 0.04, 0.75, 0.80), 0.0)

    def test_below_kink(self):
        # u=0.4, opt=0.8 -> 0.5*0.04 = 0.02
        self.assertAlmostEqual(_borrow_rate(0.4, 0.0, 0.04, 0.75, 0.80), 0.02)

    def test_at_kink(self):
        # u=0.8 == opt -> slope1 fully applied = 0.04
        self.assertAlmostEqual(_borrow_rate(0.8, 0.0, 0.04, 0.75, 0.80), 0.04)

    def test_above_kink(self):
        # u=0.9 -> 0.04 + 0.5*0.75 = 0.415
        self.assertAlmostEqual(_borrow_rate(0.9, 0.0, 0.04, 0.75, 0.80), 0.415)

    def test_full_util(self):
        # u=1.0 -> 0.04 + 0.75 = 0.79
        self.assertAlmostEqual(_borrow_rate(1.0, 0.0, 0.04, 0.75, 0.80), 0.79)

    def test_base_rate_added(self):
        # base 0.01 at u=0 -> 0.01
        self.assertAlmostEqual(_borrow_rate(0.0, 0.01, 0.04, 0.75, 0.80), 0.01)

    def test_optimal_zero_fallback(self):
        # degenerate optimal=0 -> linear base + u*slope1
        self.assertAlmostEqual(_borrow_rate(0.5, 0.0, 0.04, 0.75, 0.0), 0.5 * 0.04)

    def test_optimal_one_fallback(self):
        # degenerate optimal=1 -> linear
        self.assertAlmostEqual(_borrow_rate(0.5, 0.0, 0.04, 0.75, 1.0), 0.5 * 0.04)

    def test_monotonic_increasing(self):
        r1 = _borrow_rate(0.5, 0.0, 0.04, 0.75, 0.80)
        r2 = _borrow_rate(0.85, 0.0, 0.04, 0.75, 0.80)
        r3 = _borrow_rate(0.99, 0.0, 0.04, 0.75, 0.80)
        self.assertLess(r1, r2)
        self.assertLess(r2, r3)

    def test_never_negative(self):
        self.assertGreaterEqual(_borrow_rate(0.0, 0.0, 0.04, 0.75, 0.80), 0.0)


# ---------------------------------------------------------------------------
# _supply_rate
# ---------------------------------------------------------------------------

class TestSupplyRate(unittest.TestCase):
    def test_basic(self):
        # 0.04 * 0.8 * (1-0.10) = 0.0288
        self.assertAlmostEqual(_supply_rate(0.04, 0.8, 0.10), 0.0288)

    def test_zero_util(self):
        self.assertAlmostEqual(_supply_rate(0.04, 0.0, 0.10), 0.0)

    def test_zero_reserve(self):
        self.assertAlmostEqual(_supply_rate(0.04, 0.8, 0.0), 0.04 * 0.8)

    def test_full_reserve(self):
        self.assertAlmostEqual(_supply_rate(0.04, 0.8, 1.0), 0.0)

    def test_negative_reserve_clamped(self):
        self.assertAlmostEqual(_supply_rate(0.04, 0.8, -0.5), 0.04 * 0.8)

    def test_over_one_reserve_clamped(self):
        self.assertAlmostEqual(_supply_rate(0.04, 0.8, 1.5), 0.0)

    def test_never_negative(self):
        self.assertGreaterEqual(_supply_rate(0.04, 0.8, 0.5), 0.0)

    def test_less_than_borrow(self):
        # supply rate always <= borrow rate (since u<=1, rf>=0)
        self.assertLess(_supply_rate(0.10, 0.8, 0.10), 0.10)


# ---------------------------------------------------------------------------
# _regime
# ---------------------------------------------------------------------------

class TestRegime(unittest.TestCase):
    def test_underutilized(self):
        self.assertEqual(_regime(0.30, 0.80), "UNDERUTILIZED")

    def test_underutilized_just_below_40(self):
        self.assertEqual(_regime(0.399, 0.80), "UNDERUTILIZED")

    def test_optimal_at_40(self):
        self.assertEqual(_regime(0.40, 0.80), "OPTIMAL")

    def test_optimal_at_kink(self):
        self.assertEqual(_regime(0.80, 0.80), "OPTIMAL")

    def test_high_just_above_kink(self):
        self.assertEqual(_regime(0.801, 0.80), "HIGH")

    def test_high_at_95(self):
        self.assertEqual(_regime(0.95, 0.80), "HIGH")

    def test_critical_above_95(self):
        self.assertEqual(_regime(0.96, 0.80), "CRITICAL")

    def test_critical_full(self):
        self.assertEqual(_regime(1.0, 0.80), "CRITICAL")

    def test_zero_underutilized(self):
        self.assertEqual(_regime(0.0, 0.80), "UNDERUTILIZED")


# ---------------------------------------------------------------------------
# _liquidity_risk
# ---------------------------------------------------------------------------

class TestLiquidityRisk(unittest.TestCase):
    def test_illiquid(self):
        self.assertEqual(_liquidity_risk(0.02, 0.05), "ILLIQUID")

    def test_illiquid_boundary(self):
        # exactly at min is not illiquid (< min)
        self.assertEqual(_liquidity_risk(0.05, 0.05), "TIGHT")

    def test_tight(self):
        self.assertEqual(_liquidity_risk(0.10, 0.05), "TIGHT")

    def test_tight_boundary(self):
        # exactly 0.15 is HEALTHY (< 0.15 is tight)
        self.assertEqual(_liquidity_risk(0.15, 0.05), "HEALTHY")

    def test_healthy(self):
        self.assertEqual(_liquidity_risk(0.50, 0.05), "HEALTHY")

    def test_just_below_tight(self):
        self.assertEqual(_liquidity_risk(0.149, 0.05), "TIGHT")

    def test_zero_illiquid(self):
        self.assertEqual(_liquidity_risk(0.0, 0.05), "ILLIQUID")


# ---------------------------------------------------------------------------
# _health_score
# ---------------------------------------------------------------------------

class TestHealthScore(unittest.TestCase):
    def test_optimal_high(self):
        # u==opt, good liquidity -> high score
        s = _health_score(0.80, 0.80, 0.20, 0.05)
        self.assertGreaterEqual(s, 85.0)

    def test_zero_util_low_util_component(self):
        # u=0 -> util component 0, only liquidity
        s = _health_score(0.0, 0.80, 1.0, 0.05)
        self.assertLessEqual(s, 40.0)

    def test_critical_low(self):
        s = _health_score(0.98, 0.80, 0.02, 0.05)
        self.assertLess(s, 30.0)

    def test_illiquid_zeros_liquidity_component(self):
        # liquidity below floor -> only util component matters
        s_illiquid = _health_score(0.80, 0.80, 0.01, 0.05)
        s_liquid = _health_score(0.80, 0.80, 0.30, 0.05)
        self.assertLess(s_illiquid, s_liquid)

    def test_clamped_max_100(self):
        s = _health_score(0.80, 0.80, 1.0, 0.05)
        self.assertLessEqual(s, 100.0)

    def test_clamped_min_0(self):
        s = _health_score(1.0, 0.80, 0.0, 0.05)
        self.assertGreaterEqual(s, 0.0)

    def test_degenerate_optimal(self):
        s = _health_score(0.5, 0.0, 0.3, 0.05)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_near_optimal_better_than_far(self):
        near = _health_score(0.75, 0.80, 0.25, 0.05)
        far = _health_score(0.10, 0.80, 0.90, 0.05)
        self.assertGreater(near, far)


# ---------------------------------------------------------------------------
# _grade
# ---------------------------------------------------------------------------

class TestGrade(unittest.TestCase):
    def test_a_at_85(self):
        self.assertEqual(_grade(85), "A")

    def test_a_at_100(self):
        self.assertEqual(_grade(100), "A")

    def test_b_at_70(self):
        self.assertEqual(_grade(70), "B")

    def test_b_just_below_85(self):
        self.assertEqual(_grade(84.9), "B")

    def test_c_at_50(self):
        self.assertEqual(_grade(50), "C")

    def test_d_at_30(self):
        self.assertEqual(_grade(30), "D")

    def test_d_just_below_50(self):
        self.assertEqual(_grade(49.9), "D")

    def test_f_below_30(self):
        self.assertEqual(_grade(29.9), "F")

    def test_f_at_zero(self):
        self.assertEqual(_grade(0), "F")


# ---------------------------------------------------------------------------
# _flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):
    def test_zero_supply(self):
        flags = _flags(0.0, 0.80, 0.0, 0.05, 0.0)
        self.assertIn("ZERO_SUPPLY", flags)

    def test_illiquid(self):
        flags = _flags(0.98, 0.80, 0.02, 0.05, 100.0)
        self.assertIn("ILLIQUID", flags)

    def test_over_kink(self):
        flags = _flags(0.90, 0.80, 0.10, 0.05, 100.0)
        self.assertIn("OVER_KINK", flags)

    def test_no_over_kink_at_optimal(self):
        flags = _flags(0.80, 0.80, 0.20, 0.05, 100.0)
        self.assertNotIn("OVER_KINK", flags)

    def test_rate_spike_risk(self):
        flags = _flags(0.96, 0.80, 0.04, 0.05, 100.0)
        self.assertIn("RATE_SPIKE_RISK", flags)

    def test_no_rate_spike_at_95(self):
        flags = _flags(0.95, 0.80, 0.05, 0.05, 100.0)
        self.assertNotIn("RATE_SPIKE_RISK", flags)

    def test_underutilized(self):
        flags = _flags(0.20, 0.80, 0.80, 0.05, 100.0)
        self.assertIn("UNDERUTILIZED", flags)

    def test_no_underutilized_at_40(self):
        flags = _flags(0.40, 0.80, 0.60, 0.05, 100.0)
        self.assertNotIn("UNDERUTILIZED", flags)

    def test_clean_optimal_no_risk_flags(self):
        flags = _flags(0.80, 0.80, 0.20, 0.05, 100.0)
        self.assertEqual(flags, [])

    def test_critical_multiple_flags(self):
        flags = _flags(0.98, 0.80, 0.02, 0.05, 100.0)
        self.assertIn("OVER_KINK", flags)
        self.assertIn("RATE_SPIKE_RISK", flags)
        self.assertIn("ILLIQUID", flags)


# ---------------------------------------------------------------------------
# _recommendations
# ---------------------------------------------------------------------------

class TestRecommendations(unittest.TestCase):
    def test_optimal_good(self):
        recs = _recommendations("OPTIMAL", "HEALTHY", [])
        self.assertTrue(any("Good supply target" in r for r in recs))

    def test_underutilized_rec(self):
        recs = _recommendations("UNDERUTILIZED", "HEALTHY", ["UNDERUTILIZED"])
        self.assertTrue(any("underutilized" in r.lower() for r in recs))

    def test_high_rec(self):
        recs = _recommendations("HIGH", "TIGHT", ["OVER_KINK"])
        self.assertTrue(any("above the kink" in r for r in recs))

    def test_critical_rec(self):
        recs = _recommendations("CRITICAL", "ILLIQUID", ["RATE_SPIKE_RISK"])
        self.assertTrue(any("critical" in r.lower() for r in recs))

    def test_illiquid_slippage_rec(self):
        recs = _recommendations("CRITICAL", "ILLIQUID", ["ILLIQUID"])
        self.assertTrue(any("slippage" in r for r in recs))

    def test_tight_rec(self):
        recs = _recommendations("HIGH", "TIGHT", [])
        self.assertTrue(any("tight" in r.lower() for r in recs))

    def test_zero_supply_rec(self):
        recs = _recommendations("UNDERUTILIZED", "ILLIQUID", ["ZERO_SUPPLY"])
        self.assertTrue(any("no supplied liquidity" in r for r in recs))

    def test_rate_spike_rec(self):
        recs = _recommendations("CRITICAL", "ILLIQUID", ["RATE_SPIKE_RISK"])
        self.assertTrue(any("spike" in r.lower() for r in recs))

    def test_returns_list(self):
        self.assertIsInstance(_recommendations("OPTIMAL", "HEALTHY", []), list)


# ---------------------------------------------------------------------------
# analyze() — empty
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.result = analyze([])

    def test_pools_empty(self):
        self.assertEqual(self.result["pools"], [])

    def test_average_zero(self):
        self.assertEqual(self.result["average_utilization"], 0.0)

    def test_highest_none(self):
        self.assertIsNone(self.result["highest_borrow_rate_pool"])

    def test_most_illiquid_none(self):
        self.assertIsNone(self.result["most_illiquid_pool"])

    def test_critical_zero(self):
        self.assertEqual(self.result["critical_count"], 0)

    def test_timestamp(self):
        self.assertIsInstance(self.result["timestamp"], float)


# ---------------------------------------------------------------------------
# analyze() — single pool
# ---------------------------------------------------------------------------

class TestAnalyzeSingle(unittest.TestCase):
    def setUp(self):
        self.result = analyze([_pool("Aave", 100.0, 80.0)])
        self.p = self.result["pools"][0]

    def test_one_pool(self):
        self.assertEqual(len(self.result["pools"]), 1)

    def test_name_preserved(self):
        self.assertEqual(self.p["name"], "Aave")

    def test_utilization(self):
        self.assertAlmostEqual(self.p["utilization"], 0.80)

    def test_available_liquidity(self):
        self.assertAlmostEqual(self.p["available_liquidity"], 20.0)

    def test_liquidity_ratio(self):
        self.assertAlmostEqual(self.p["liquidity_ratio"], 0.20)

    def test_regime_optimal(self):
        self.assertEqual(self.p["regime"], "OPTIMAL")

    def test_grade_present(self):
        self.assertIn(self.p["grade"], ("A", "B", "C", "D", "F"))

    def test_pool_keys(self):
        expected = {
            "name", "utilization", "borrow_rate", "supply_rate",
            "available_liquidity", "liquidity_ratio", "regime",
            "liquidity_risk", "health_score", "grade", "flags",
            "recommendations",
        }
        self.assertEqual(set(self.p.keys()), expected)

    def test_highest_borrow_is_only_pool(self):
        self.assertEqual(self.result["highest_borrow_rate_pool"], "Aave")

    def test_average_equals_util(self):
        self.assertAlmostEqual(self.result["average_utilization"], 0.80)


# ---------------------------------------------------------------------------
# analyze() — multiple pools + summary
# ---------------------------------------------------------------------------

class TestAnalyzeMultiple(unittest.TestCase):
    def setUp(self):
        self.pools = [
            _pool("Healthy", 100.0, 50.0),    # u=0.50 OPTIMAL
            _pool("Hot", 100.0, 98.0),        # u=0.98 CRITICAL, illiquid
            _pool("Idle", 100.0, 10.0),       # u=0.10 UNDERUTILIZED
        ]
        self.result = analyze(self.pools)

    def test_three_pools(self):
        self.assertEqual(len(self.result["pools"]), 3)

    def test_highest_borrow_is_hot(self):
        self.assertEqual(self.result["highest_borrow_rate_pool"], "Hot")

    def test_most_illiquid_is_hot(self):
        self.assertEqual(self.result["most_illiquid_pool"], "Hot")

    def test_critical_count(self):
        self.assertEqual(self.result["critical_count"], 1)

    def test_average_between_min_max(self):
        utils = [p["utilization"] for p in self.result["pools"]]
        avg = self.result["average_utilization"]
        self.assertGreaterEqual(avg, min(utils))
        self.assertLessEqual(avg, max(utils))

    def test_hot_critical_regime(self):
        hot = next(p for p in self.result["pools"] if p["name"] == "Hot")
        self.assertEqual(hot["regime"], "CRITICAL")

    def test_idle_underutilized(self):
        idle = next(p for p in self.result["pools"] if p["name"] == "Idle")
        self.assertEqual(idle["regime"], "UNDERUTILIZED")

    def test_hot_has_rate_spike_flag(self):
        hot = next(p for p in self.result["pools"] if p["name"] == "Hot")
        self.assertIn("RATE_SPIKE_RISK", hot["flags"])

    def test_top_level_keys(self):
        expected = {
            "pools", "average_utilization", "highest_borrow_rate_pool",
            "most_illiquid_pool", "critical_count", "timestamp",
        }
        self.assertEqual(set(self.result.keys()), expected)


# ---------------------------------------------------------------------------
# analyze() — zero supply pool + config defaults
# ---------------------------------------------------------------------------

class TestAnalyzeEdge(unittest.TestCase):
    def test_zero_supply_pool(self):
        r = analyze([_pool("Empty", 0.0, 0.0)])
        p = r["pools"][0]
        self.assertEqual(p["utilization"], 0.0)
        self.assertIn("ZERO_SUPPLY", p["flags"])

    def test_zero_supply_liquidity_ratio_zero(self):
        r = analyze([_pool("Empty", 0.0, 0.0)])
        self.assertEqual(r["pools"][0]["liquidity_ratio"], 0.0)

    def test_global_config_optimal(self):
        # pool omits optimal_utilization; config supplies it
        pool = {"name": "P", "total_supplied": 100.0, "total_borrowed": 70.0}
        r = analyze([pool], {"optimal_utilization": 0.70})
        p = r["pools"][0]
        # u=0.70 == optimal -> OPTIMAL
        self.assertEqual(p["regime"], "OPTIMAL")

    def test_min_liquidity_ratio_config(self):
        # raise min_liquidity_ratio so a normally-tight pool becomes illiquid
        pool = _pool("P", 100.0, 88.0)  # liquidity_ratio = 0.12
        r = analyze([pool], {"min_liquidity_ratio": 0.20})
        self.assertEqual(r["pools"][0]["liquidity_risk"], "ILLIQUID")

    def test_pool_overrides_config(self):
        pool = _pool("P", 100.0, 90.0, optimal_utilization=0.90)
        r = analyze([pool], {"optimal_utilization": 0.50})
        # pool value 0.90 wins -> u=0.90 == optimal -> OPTIMAL
        self.assertEqual(r["pools"][0]["regime"], "OPTIMAL")

    def test_defaults_applied_when_missing(self):
        pool = {"name": "P", "total_supplied": 100.0, "total_borrowed": 80.0}
        r = analyze([pool])
        # default optimal 0.80, u=0.80 -> OPTIMAL, borrow rate at kink = 0.04
        p = r["pools"][0]
        self.assertEqual(p["regime"], "OPTIMAL")
        self.assertAlmostEqual(p["borrow_rate"], 0.04)


# ---------------------------------------------------------------------------
# log_result() — ring-buffer and atomic write
# ---------------------------------------------------------------------------

class TestLogResult(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _make_result(self):
        return analyze([_pool("Aave", 100.0, 80.0)])

    def test_creates_log_file(self):
        log_path = os.path.join(self.tmp_dir, "lending_pool_utilization_log.json")
        self.assertFalse(os.path.exists(log_path))
        log_result(self._make_result(), data_dir=self.tmp_dir)
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_list(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "lending_pool_utilization_log.json")) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_snapshot_fields(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "lending_pool_utilization_log.json")) as f:
            data = json.load(f)
        entry = data[0]
        for key in ("timestamp", "pool_count", "average_utilization",
                    "critical_count", "highest_borrow_rate_pool",
                    "most_illiquid_pool"):
            self.assertIn(key, entry)

    def test_multiple_appends(self):
        for _ in range(5):
            log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "lending_pool_utilization_log.json")) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_capped_at_100(self):
        for _ in range(110):
            log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "lending_pool_utilization_log.json")) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            r = self._make_result()
            r["critical_count"] = i
            log_result(r, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "lending_pool_utilization_log.json")) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["critical_count"], 104)

    def test_no_tmp_files_left(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        leftovers = [f for f in os.listdir(self.tmp_dir)
                     if f.startswith(".lending_pool_utilization_log_")
                     and f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_corrupted_log_recovered(self):
        log_path = os.path.join(self.tmp_dir, "lending_pool_utilization_log.json")
        with open(log_path, "w") as f:
            f.write("not valid json{{")
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_roundtrip_pool_count(self):
        r = self._make_result()
        log_result(r, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "lending_pool_utilization_log.json")) as f:
            data = json.load(f)
        self.assertEqual(data[0]["pool_count"], len(r["pools"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
