"""
Tests for MP-1110: DeFiProtocolLendingUtilizationElasticityAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_lending_utilization_elasticity_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_lending_utilization_elasticity_analyzer import (
    DeFiProtocolLendingUtilizationElasticityAnalyzer,
    _clamp,
    _borrow_rate_at_util,
    _supply_apy_from_borrow,
    _rate_elasticity,
    _utilization_label,
    _build_default_cfg,
    KINK_PROXIMITY_WARNING,
    KINK_PROXIMITY_CRITICAL,
    UTIL_CRITICAL,
    UTIL_HIGH,
    UTIL_MODERATE,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_protocol(
    name="TestLender",
    category="lending",
    current_utilization=0.70,
    base_rate=0.02,
    slope1=0.10,
    slope2=3.00,
    kink=0.80,
    reserve_factor=0.10,
    total_supply_usd=1_000_000_000,
    total_borrow_usd=700_000_000,
    shock_scenarios=None,
):
    d = {
        "name": name,
        "category": category,
        "current_utilization": current_utilization,
        "base_rate": base_rate,
        "slope1": slope1,
        "slope2": slope2,
        "kink": kink,
        "reserve_factor": reserve_factor,
        "total_supply_usd": total_supply_usd,
        "total_borrow_usd": total_borrow_usd,
    }
    if shock_scenarios is not None:
        d["shock_scenarios"] = shock_scenarios
    return d


def tmp_cfg():
    td = tempfile.mkdtemp()
    return {"log_path": os.path.join(td, "util_elast.json"), "log_cap": 5}


# ── helper tests ──────────────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_clamp_within(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-1.0, 0.0, 10.0), 0.0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(15.0, 0.0, 10.0), 10.0)

    # _borrow_rate_at_util
    def test_borrow_rate_zero_util(self):
        rate = _borrow_rate_at_util(0.0, 0.02, 0.10, 3.0, 0.80)
        self.assertAlmostEqual(rate, 0.02)

    def test_borrow_rate_at_kink(self):
        # At kink=0.80: 0.02 + 0.80*0.10 = 0.02 + 0.08 = 0.10
        rate = _borrow_rate_at_util(0.80, 0.02, 0.10, 3.0, 0.80)
        self.assertAlmostEqual(rate, 0.10, places=5)

    def test_borrow_rate_above_kink(self):
        # At util=0.90, above kink: 0.02 + 0.80*0.10 + (0.90-0.80)*3.0 = 0.10 + 0.30 = 0.40
        rate = _borrow_rate_at_util(0.90, 0.02, 0.10, 3.0, 0.80)
        self.assertAlmostEqual(rate, 0.40, places=5)

    def test_borrow_rate_increases_with_util(self):
        r1 = _borrow_rate_at_util(0.50, 0.02, 0.10, 3.0, 0.80)
        r2 = _borrow_rate_at_util(0.75, 0.02, 0.10, 3.0, 0.80)
        self.assertGreater(r2, r1)

    def test_borrow_rate_steeper_above_kink(self):
        # Rate jump above kink should be much faster
        delta_below = _borrow_rate_at_util(0.79, 0.02, 0.10, 3.0, 0.80) - _borrow_rate_at_util(0.70, 0.02, 0.10, 3.0, 0.80)
        delta_above = _borrow_rate_at_util(0.90, 0.02, 0.10, 3.0, 0.80) - _borrow_rate_at_util(0.81, 0.02, 0.10, 3.0, 0.80)
        self.assertGreater(delta_above, delta_below)

    def test_borrow_rate_clamped_util(self):
        # util > 1.0 should be clamped
        r_clamped = _borrow_rate_at_util(1.5, 0.02, 0.10, 3.0, 0.80)
        r_one     = _borrow_rate_at_util(1.0, 0.02, 0.10, 3.0, 0.80)
        self.assertAlmostEqual(r_clamped, r_one, places=5)

    # _supply_apy_from_borrow
    def test_supply_apy_basic(self):
        # supply_apy = borrow * util * (1 - rf) = 0.10 * 0.80 * 0.90 = 0.072
        apy = _supply_apy_from_borrow(0.80, 0.10, 0.10)
        self.assertAlmostEqual(apy, 0.072, places=5)

    def test_supply_apy_zero_util(self):
        self.assertAlmostEqual(_supply_apy_from_borrow(0.0, 0.10, 0.10), 0.0)

    def test_supply_apy_zero_rf(self):
        apy = _supply_apy_from_borrow(0.80, 0.10, 0.0)
        self.assertAlmostEqual(apy, 0.08, places=5)

    def test_supply_apy_full_rf(self):
        # Reserve factor = 1 → all revenue kept, supply_apy = 0
        apy = _supply_apy_from_borrow(0.80, 0.10, 1.0)
        self.assertAlmostEqual(apy, 0.0, places=5)

    # _rate_elasticity
    def test_elasticity_below_kink(self):
        e = _rate_elasticity(0.50, 0.10, 3.0, 0.80)
        self.assertAlmostEqual(e, 0.10, places=3)  # below kink: slope = slope1

    def test_elasticity_above_kink(self):
        e = _rate_elasticity(0.85, 0.10, 3.0, 0.80)
        self.assertAlmostEqual(e, 3.0, places=2)  # above kink: slope = slope2

    def test_elasticity_positive(self):
        e = _rate_elasticity(0.60, 0.10, 3.0, 0.80)
        self.assertGreater(e, 0.0)

    def test_elasticity_above_kink_greater(self):
        e_below = _rate_elasticity(0.70, 0.10, 3.0, 0.80)
        e_above = _rate_elasticity(0.90, 0.10, 3.0, 0.80)
        self.assertGreater(e_above, e_below)

    # _utilization_label
    def test_util_label_critical(self):
        self.assertEqual(_utilization_label(0.97), "CRITICAL")

    def test_util_label_high(self):
        self.assertEqual(_utilization_label(0.85), "HIGH")

    def test_util_label_moderate(self):
        self.assertEqual(_utilization_label(0.70), "MODERATE")

    def test_util_label_low(self):
        self.assertEqual(_utilization_label(0.30), "LOW")

    def test_util_label_boundary_critical(self):
        self.assertEqual(_utilization_label(UTIL_CRITICAL), "CRITICAL")

    # constants
    def test_constants_order(self):
        self.assertLess(KINK_PROXIMITY_CRITICAL, KINK_PROXIMITY_WARNING)
        self.assertLess(UTIL_MODERATE, UTIL_HIGH)
        self.assertLess(UTIL_HIGH, UTIL_CRITICAL)

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertIn("log_path", cfg)
        self.assertIn("log_cap", cfg)


# ── analyzer tests ────────────────────────────────────────────────────────────

class TestUtilizationElasticityAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolLendingUtilizationElasticityAnalyzer()

    def test_analyze_returns_keys(self):
        result = self.analyzer.analyze([make_protocol()])
        self.assertIn("protocols", result)
        self.assertIn("aggregate", result)

    def test_analyze_empty(self):
        result = self.analyzer.analyze([])
        self.assertEqual(len(result["protocols"]), 0)
        self.assertIsNone(result["aggregate"]["highest_utilization"])

    def test_single_protocol(self):
        result = self.analyzer.analyze([make_protocol()])
        self.assertEqual(len(result["protocols"]), 1)

    def test_result_keys(self):
        result = self.analyzer.analyze([make_protocol()])
        p = result["protocols"][0]
        for k in [
            "name", "category", "current_utilization_pct", "utilization_label",
            "kink_utilization_pct", "kink_distance_pp", "current_borrow_rate_pct",
            "current_supply_apy_pct", "kink_borrow_rate_pct", "cliff_delta_pct",
            "rate_elasticity_pp_per_pp", "shock_scenarios", "flags",
        ]:
            self.assertIn(k, p)

    def test_utilization_pct_correct(self):
        p = make_protocol(current_utilization=0.75)
        result = self.analyzer.analyze([p])
        self.assertAlmostEqual(result["protocols"][0]["current_utilization_pct"], 75.0, places=1)

    def test_kink_distance_below_kink(self):
        # util=0.70, kink=0.80 → distance = 10pp
        p = make_protocol(current_utilization=0.70, kink=0.80)
        result = self.analyzer.analyze([p])
        self.assertAlmostEqual(result["protocols"][0]["kink_distance_pp"], 10.0, places=1)

    def test_kink_distance_above_kink_negative(self):
        # util=0.90, kink=0.80 → kink_distance = -10pp (negative)
        p = make_protocol(current_utilization=0.90, kink=0.80)
        result = self.analyzer.analyze([p])
        self.assertLess(result["protocols"][0]["kink_distance_pp"], 0.0)

    def test_borrow_rate_at_kink_correct(self):
        # At kink=0.80: base=0.02 + 0.80*slope1=0.10 → 0.02+0.08=0.10 → 10%
        p = make_protocol(current_utilization=0.80, base_rate=0.02, slope1=0.10, kink=0.80)
        result = self.analyzer.analyze([p])
        self.assertAlmostEqual(result["protocols"][0]["current_borrow_rate_pct"], 10.0, places=2)

    def test_supply_apy_less_than_borrow(self):
        result = self.analyzer.analyze([make_protocol()])
        p = result["protocols"][0]
        self.assertLessEqual(p["current_supply_apy_pct"], p["current_borrow_rate_pct"])

    def test_elasticity_higher_above_kink(self):
        p_below = make_protocol(current_utilization=0.70, kink=0.80)
        p_above = make_protocol(current_utilization=0.90, kink=0.80)
        r_below = self.analyzer.analyze([p_below])["protocols"][0]["rate_elasticity_pp_per_pp"]
        r_above = self.analyzer.analyze([p_above])["protocols"][0]["rate_elasticity_pp_per_pp"]
        self.assertGreater(r_above, r_below)

    def test_cliff_delta_positive(self):
        result = self.analyzer.analyze([make_protocol()])
        self.assertGreater(result["protocols"][0]["cliff_delta_pct"], 0.0)

    def test_shock_scenarios_count(self):
        p = make_protocol(shock_scenarios=[-0.10, -0.05, 0.05, 0.10])
        result = self.analyzer.analyze([p])
        self.assertEqual(len(result["protocols"][0]["shock_scenarios"]), 4)

    def test_shock_scenario_keys(self):
        result = self.analyzer.analyze([make_protocol()])
        sc = result["protocols"][0]["shock_scenarios"][0]
        for k in ["util_delta_pp", "new_utilization_pct", "new_borrow_rate_pct",
                   "new_supply_apy_pct", "borrow_rate_change_pp", "supply_apy_change_pp",
                   "crosses_kink"]:
            self.assertIn(k, sc)

    def test_shock_crosses_kink_detected(self):
        # util=0.75, kink=0.80, shock=+0.10 → crosses kink
        p = make_protocol(
            current_utilization=0.75,
            kink=0.80,
            shock_scenarios=[0.10],
        )
        result = self.analyzer.analyze([p])
        sc = result["protocols"][0]["shock_scenarios"][0]
        self.assertTrue(sc["crosses_kink"])

    def test_shock_not_crosses_kink(self):
        # util=0.50, kink=0.80, shock=+0.10 → new util=0.60, doesn't cross
        p = make_protocol(
            current_utilization=0.50,
            kink=0.80,
            shock_scenarios=[0.10],
        )
        result = self.analyzer.analyze([p])
        sc = result["protocols"][0]["shock_scenarios"][0]
        self.assertFalse(sc["crosses_kink"])

    def test_name_preserved(self):
        p = make_protocol(name="SpecialLender")
        result = self.analyzer.analyze([p])
        self.assertEqual(result["protocols"][0]["name"], "SpecialLender")

    def test_utilization_label_valid(self):
        for util in [0.2, 0.65, 0.82, 0.97]:
            p = make_protocol(current_utilization=util)
            result = self.analyzer.analyze([p])
            label = result["protocols"][0]["utilization_label"]
            self.assertIn(label, ("LOW", "MODERATE", "HIGH", "CRITICAL"))


# ── flag tests ────────────────────────────────────────────────────────────────

class TestUtilizationFlags(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolLendingUtilizationElasticityAnalyzer()

    def test_flag_utilization_critical(self):
        p = make_protocol(current_utilization=0.97)
        result = self.analyzer.analyze([p])
        self.assertIn("UTILIZATION_CRITICAL", result["protocols"][0]["flags"])

    def test_flag_utilization_high(self):
        p = make_protocol(current_utilization=0.85)
        result = self.analyzer.analyze([p])
        self.assertIn("UTILIZATION_HIGH", result["protocols"][0]["flags"])

    def test_no_util_flag_low(self):
        p = make_protocol(current_utilization=0.30)
        result = self.analyzer.analyze([p])
        flags = result["protocols"][0]["flags"]
        self.assertNotIn("UTILIZATION_HIGH", flags)
        self.assertNotIn("UTILIZATION_CRITICAL", flags)

    def test_flag_above_kink(self):
        p = make_protocol(current_utilization=0.85, kink=0.80)
        result = self.analyzer.analyze([p])
        self.assertIn("ABOVE_KINK", result["protocols"][0]["flags"])

    def test_no_flag_below_kink(self):
        p = make_protocol(current_utilization=0.70, kink=0.80)
        result = self.analyzer.analyze([p])
        self.assertNotIn("ABOVE_KINK", result["protocols"][0]["flags"])

    def test_flag_kink_proximity_critical(self):
        # util = 0.79, kink = 0.80 → distance = 1pp < 2pp → CRITICAL
        p = make_protocol(current_utilization=0.79, kink=0.80)
        result = self.analyzer.analyze([p])
        self.assertIn("KINK_PROXIMITY_CRITICAL", result["protocols"][0]["flags"])

    def test_flag_kink_proximity_warning(self):
        # util = 0.76, kink = 0.80 → distance = 4pp → WARNING (2-5pp range)
        p = make_protocol(current_utilization=0.76, kink=0.80)
        result = self.analyzer.analyze([p])
        self.assertIn("KINK_PROXIMITY_WARNING", result["protocols"][0]["flags"])

    def test_no_kink_proximity_far(self):
        # util = 0.50, kink = 0.80 → distance = 30pp → no proximity flag
        p = make_protocol(current_utilization=0.50, kink=0.80)
        result = self.analyzer.analyze([p])
        flags = result["protocols"][0]["flags"]
        self.assertNotIn("KINK_PROXIMITY_WARNING", flags)
        self.assertNotIn("KINK_PROXIMITY_CRITICAL", flags)

    def test_flag_high_rate_elasticity_above_kink(self):
        # Above kink with slope2=3 → elasticity = 3*100 = 300pp/pp → HIGH
        p = make_protocol(current_utilization=0.90, kink=0.80, slope2=3.0)
        result = self.analyzer.analyze([p])
        self.assertIn("HIGH_RATE_ELASTICITY", result["protocols"][0]["flags"])

    def test_flag_large_kink_cliff(self):
        # cliff_delta ≈ (slope2 - slope1) * 0.002 in rate terms.
        # For cliff_delta_pct >= 10pp: need (slope2-slope1)*0.002*100 >= 10
        #   → slope2 >= 50 + slope1.  Use slope2=100 to be safe.
        p = make_protocol(slope1=0.01, slope2=100.0)
        result = self.analyzer.analyze([p])
        self.assertIn("LARGE_KINK_CLIFF", result["protocols"][0]["flags"])

    def test_flags_list_type(self):
        result = self.analyzer.analyze([make_protocol()])
        self.assertIsInstance(result["protocols"][0]["flags"], list)


# ── aggregate tests ───────────────────────────────────────────────────────────

class TestUtilizationAggregate(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolLendingUtilizationElasticityAnalyzer()

    def test_highest_utilization(self):
        p_low  = make_protocol(name="LowUtil", current_utilization=0.30)
        p_high = make_protocol(name="HighUtil", current_utilization=0.90)
        result = self.analyzer.analyze([p_low, p_high])
        self.assertEqual(result["aggregate"]["highest_utilization"], "HighUtil")

    def test_lowest_utilization(self):
        p_low  = make_protocol(name="LowUtil", current_utilization=0.30)
        p_high = make_protocol(name="HighUtil", current_utilization=0.90)
        result = self.analyzer.analyze([p_low, p_high])
        self.assertEqual(result["aggregate"]["lowest_utilization"], "LowUtil")

    def test_avg_utilization_in_range(self):
        protos = [make_protocol() for _ in range(3)]
        result = self.analyzer.analyze(protos)
        avg = result["aggregate"]["avg_utilization_pct"]
        self.assertGreater(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_above_kink_count(self):
        p_above = make_protocol(current_utilization=0.90, kink=0.80)
        p_below = make_protocol(current_utilization=0.70, kink=0.80)
        result = self.analyzer.analyze([p_above, p_below])
        self.assertEqual(result["aggregate"]["above_kink_count"], 1)

    def test_critical_count_zero(self):
        protos = [make_protocol(current_utilization=0.60) for _ in range(3)]
        result = self.analyzer.analyze(protos)
        self.assertEqual(result["aggregate"]["critical_utilization_count"], 0)


# ── log tests ─────────────────────────────────────────────────────────────────

class TestUtilizationLog(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolLendingUtilizationElasticityAnalyzer()

    def test_write_log_creates_file(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        self.assertTrue(os.path.exists(cfg["log_path"]))

    def test_log_valid_json(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_entry_keys(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        entry = data[0]
        for k in ["ts", "protocol_count", "aggregates", "snapshots"]:
            self.assertIn(k, entry)

    def test_log_ring_buffer_cap(self):
        cfg = tmp_cfg()
        for _ in range(cfg["log_cap"] + 4):
            self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), cfg["log_cap"])

    def test_no_write_no_file(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=False)
        self.assertFalse(os.path.exists(cfg["log_path"]))

    def test_log_atomic_no_tmp(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        self.assertFalse(os.path.exists(cfg["log_path"] + ".tmp"))

    def test_log_accumulates(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_log_snapshot_keys(self):
        cfg = tmp_cfg()
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        snap = data[0]["snapshots"][0]
        for k in ["name", "utilization_pct", "util_label", "borrow_rate_pct", "flags"]:
            self.assertIn(k, snap)

    def test_log_recovers_from_corrupt(self):
        cfg = tmp_cfg()
        with open(cfg["log_path"], "w") as fh:
            fh.write("BAD_JSON")
        self.analyzer.analyze([make_protocol()], cfg=cfg, write_log=True)
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_protocol_count(self):
        cfg = tmp_cfg()
        self.analyzer.analyze(
            [make_protocol("A"), make_protocol("B")],
            cfg=cfg, write_log=True
        )
        with open(cfg["log_path"]) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["protocol_count"], 2)


if __name__ == "__main__":
    unittest.main()
