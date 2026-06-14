#!/usr/bin/env python3
"""Unit tests for MP-770 CapitalEfficiencyTracker (SPA-V622).

Run:
    python3 -m unittest spa_core/tests/test_capital_efficiency_tracker.py -v

All tests use stdlib unittest only — no pytest, no numpy.
"""
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root on path
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.capital_efficiency_tracker import (
    CapitalEfficiencyTracker,
    _grade,
    _clamp,
    _atomic_write,
    _load_json_list,
    build_capital_efficiency_report,
    compute_position_efficiency,
    write_status,
    DEFAULT_BENCHMARK_APY,
    MAX_APY,
    RING_BUFFER_CAP,
    LOG_FILENAME,
    GRADE_THRESHOLDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pos(
    protocol="test_proto",
    deployed_usd=50000.0,
    idle_usd=5000.0,
    apy=0.05,
    utilization_rate_pct=90.0,
):
    return {
        "protocol": protocol,
        "deployed_usd": deployed_usd,
        "idle_usd": idle_usd,
        "apy": apy,
        "utilization_rate_pct": utilization_rate_pct,
    }


# ===========================================================================
# 1. _clamp helper
# ===========================================================================

class TestClamp(unittest.TestCase):

    def test_clamp_within_range(self):
        self.assertEqual(_clamp(50.0, 0.0, 100.0), 50.0)

    def test_clamp_at_lower(self):
        self.assertEqual(_clamp(0.0, 0.0, 100.0), 0.0)

    def test_clamp_at_upper(self):
        self.assertEqual(_clamp(100.0, 0.0, 100.0), 100.0)

    def test_clamp_below_lower(self):
        self.assertEqual(_clamp(-5.0, 0.0, 100.0), 0.0)

    def test_clamp_above_upper(self):
        self.assertEqual(_clamp(150.0, 0.0, 100.0), 100.0)

    def test_clamp_negative_range(self):
        self.assertEqual(_clamp(-3.0, -5.0, -1.0), -3.0)


# ===========================================================================
# 2. _grade helper
# ===========================================================================

class TestGrade(unittest.TestCase):

    def test_grade_A_exact(self):
        self.assertEqual(_grade(80.0), "A")

    def test_grade_A_above(self):
        self.assertEqual(_grade(95.0), "A")

    def test_grade_A_hundred(self):
        self.assertEqual(_grade(100.0), "A")

    def test_grade_B_exact(self):
        self.assertEqual(_grade(60.0), "B")

    def test_grade_B_midpoint(self):
        self.assertEqual(_grade(70.0), "B")

    def test_grade_B_just_below_A(self):
        self.assertEqual(_grade(79.9), "B")

    def test_grade_C_exact(self):
        self.assertEqual(_grade(40.0), "C")

    def test_grade_C_midpoint(self):
        self.assertEqual(_grade(50.0), "C")

    def test_grade_C_just_below_B(self):
        self.assertEqual(_grade(59.9), "C")

    def test_grade_D_exact(self):
        self.assertEqual(_grade(20.0), "D")

    def test_grade_D_midpoint(self):
        self.assertEqual(_grade(30.0), "D")

    def test_grade_D_just_below_C(self):
        self.assertEqual(_grade(39.9), "D")

    def test_grade_F_zero(self):
        self.assertEqual(_grade(0.0), "F")

    def test_grade_F_near_zero(self):
        self.assertEqual(_grade(0.001), "F")

    def test_grade_F_just_below_D(self):
        self.assertEqual(_grade(19.9), "F")


# ===========================================================================
# 3. compute_position_efficiency — core formula
# ===========================================================================

class TestComputePositionEfficiency(unittest.TestCase):

    def _call(self, **kwargs):
        defaults = dict(
            protocol="proto",
            deployed_usd=50000.0,
            idle_usd=5000.0,
            apy=0.10,
            utilization_rate_pct=80.0,
            benchmark_apy=0.05,
        )
        defaults.update(kwargs)
        return compute_position_efficiency(**defaults)

    # --- Score formula ---

    def test_score_is_float(self):
        r = self._call()
        self.assertIsInstance(r["capital_efficiency_score"], float)

    def test_score_range_zero_to_hundred(self):
        for util in [0, 25, 50, 75, 100]:
            for apy in [0.0, 0.05, 0.15, 0.30, 0.60]:
                r = self._call(utilization_rate_pct=util, apy=apy)
                self.assertGreaterEqual(r["capital_efficiency_score"], 0.0)
                self.assertLessEqual(r["capital_efficiency_score"], 100.0)

    def test_score_zero_when_utilization_zero(self):
        r = self._call(utilization_rate_pct=0.0, apy=0.10)
        self.assertEqual(r["capital_efficiency_score"], 0.0)

    def test_score_zero_when_apy_zero(self):
        r = self._call(utilization_rate_pct=100.0, apy=0.0)
        self.assertEqual(r["capital_efficiency_score"], 0.0)

    def test_score_max_at_full_utilization_max_apy(self):
        r = self._call(utilization_rate_pct=100.0, apy=MAX_APY)
        self.assertAlmostEqual(r["capital_efficiency_score"], 100.0, places=4)

    def test_score_capped_at_hundred_when_apy_exceeds_max(self):
        r = self._call(utilization_rate_pct=100.0, apy=MAX_APY * 2)
        self.assertAlmostEqual(r["capital_efficiency_score"], 100.0, places=4)

    def test_score_half_utilization_half_apy(self):
        # util=50%, apy=MAX_APY/2 → score = 0.5 * 0.5 * 100 = 25.0
        r = self._call(utilization_rate_pct=50.0, apy=MAX_APY / 2)
        self.assertAlmostEqual(r["capital_efficiency_score"], 25.0, places=4)

    def test_apy_weight_capped_at_one(self):
        r = self._call(apy=MAX_APY * 5, utilization_rate_pct=100.0)
        self.assertAlmostEqual(r["apy_weight"], 1.0, places=6)

    def test_apy_weight_proportional(self):
        r = self._call(apy=MAX_APY / 2)
        self.assertAlmostEqual(r["apy_weight"], 0.5, places=6)

    # --- Zero deployed ---

    def test_zero_deployed_usd(self):
        r = self._call(deployed_usd=0.0, idle_usd=10000.0)
        self.assertEqual(r["deployed_usd"], 0.0)
        self.assertGreaterEqual(r["idle_capital_pct"], 0.0)

    def test_zero_deployed_and_zero_idle(self):
        r = self._call(deployed_usd=0.0, idle_usd=0.0)
        self.assertEqual(r["idle_capital_pct"], 0.0)
        self.assertIn("Both deployed_usd and idle_usd are zero", r["warnings"])

    # --- 100% utilization ---

    def test_full_utilization_no_idle(self):
        r = self._call(
            deployed_usd=100000.0,
            idle_usd=0.0,
            utilization_rate_pct=100.0,
            apy=0.05,
        )
        self.assertEqual(r["idle_capital_pct"], 0.0)
        self.assertEqual(r["opportunity_cost_usd_daily"], 0.0)

    def test_full_utilization_grade(self):
        r = self._call(
            deployed_usd=100000.0,
            idle_usd=0.0,
            utilization_rate_pct=100.0,
            apy=MAX_APY,
        )
        self.assertEqual(r["efficiency_grade"], "A")

    # --- Zero APY ---

    def test_zero_apy_gives_zero_score(self):
        r = self._call(apy=0.0, utilization_rate_pct=100.0)
        self.assertEqual(r["capital_efficiency_score"], 0.0)

    def test_zero_apy_grade_is_F(self):
        r = self._call(apy=0.0, utilization_rate_pct=100.0)
        self.assertEqual(r["efficiency_grade"], "F")

    # --- Negative APY ---

    def test_negative_apy_treated_as_zero(self):
        r = self._call(apy=-0.05)
        self.assertEqual(r["apy"], 0.0)
        self.assertIn("Negative APY", " ".join(r["warnings"]))

    # --- Idle capital pct ---

    def test_idle_capital_pct_calculation(self):
        r = self._call(deployed_usd=90000.0, idle_usd=10000.0)
        self.assertAlmostEqual(r["idle_capital_pct"], 10.0, places=4)

    def test_idle_capital_pct_all_idle(self):
        r = self._call(deployed_usd=0.0, idle_usd=50000.0)
        self.assertAlmostEqual(r["idle_capital_pct"], 100.0, places=4)

    # --- Opportunity cost ---

    def test_opportunity_cost_formula(self):
        idle = 10000.0
        bench = 0.05
        expected = idle * bench / 365.0
        r = self._call(idle_usd=idle, benchmark_apy=bench)
        self.assertAlmostEqual(r["opportunity_cost_usd_daily"], expected, places=6)

    def test_opportunity_cost_zero_idle(self):
        r = self._call(idle_usd=0.0)
        self.assertEqual(r["opportunity_cost_usd_daily"], 0.0)

    # --- Grade boundary correctness ---

    def test_grade_A_boundary(self):
        # utilization 100%, apy such that score = 80
        # score = 1.0 * (apy/MAX_APY) * 100 = 80  → apy = 0.8 * MAX_APY
        r = self._call(utilization_rate_pct=100.0, apy=0.8 * MAX_APY)
        self.assertAlmostEqual(r["capital_efficiency_score"], 80.0, places=3)
        self.assertEqual(r["efficiency_grade"], "A")

    def test_grade_B_boundary(self):
        r = self._call(utilization_rate_pct=100.0, apy=0.6 * MAX_APY)
        self.assertAlmostEqual(r["capital_efficiency_score"], 60.0, places=3)
        self.assertEqual(r["efficiency_grade"], "B")

    def test_grade_C_boundary(self):
        r = self._call(utilization_rate_pct=100.0, apy=0.4 * MAX_APY)
        self.assertAlmostEqual(r["capital_efficiency_score"], 40.0, places=3)
        self.assertEqual(r["efficiency_grade"], "C")

    def test_grade_D_boundary(self):
        r = self._call(utilization_rate_pct=100.0, apy=0.2 * MAX_APY)
        self.assertAlmostEqual(r["capital_efficiency_score"], 20.0, places=3)
        self.assertEqual(r["efficiency_grade"], "D")

    def test_grade_F_below_D(self):
        r = self._call(utilization_rate_pct=100.0, apy=0.19 * MAX_APY)
        self.assertLess(r["capital_efficiency_score"], 20.0)
        self.assertEqual(r["efficiency_grade"], "F")

    # --- Out-of-range inputs ---

    def test_utilization_above_100_clamped(self):
        r = self._call(utilization_rate_pct=150.0)
        self.assertLessEqual(r["capital_efficiency_score"], 100.0)
        self.assertIn("clamped", " ".join(r["warnings"]))

    def test_utilization_below_0_clamped(self):
        r = self._call(utilization_rate_pct=-10.0)
        self.assertEqual(r["capital_efficiency_score"], 0.0)
        self.assertIn("clamped", " ".join(r["warnings"]))

    # --- Protocol name preserved ---

    def test_protocol_name_preserved(self):
        r = self._call(protocol="aave_v3")
        self.assertEqual(r["protocol"], "aave_v3")

    # --- Return keys ---

    def test_required_keys_present(self):
        r = self._call()
        for key in [
            "protocol", "deployed_usd", "idle_usd", "apy",
            "utilization_rate_pct", "benchmark_apy", "apy_weight",
            "capital_efficiency_score", "idle_capital_pct",
            "opportunity_cost_usd_daily", "efficiency_grade", "warnings",
        ]:
            self.assertIn(key, r, f"Missing key: {key}")


# ===========================================================================
# 4. CapitalEfficiencyTracker.track()
# ===========================================================================

class TestTrackerTrack(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = CapitalEfficiencyTracker(data_dir=self.tmp)

    def _positions(self, n=2):
        return [
            _make_pos(protocol=f"proto_{i}", deployed_usd=10000.0 * (i + 1))
            for i in range(n)
        ]

    def test_track_returns_dict(self):
        r = self.tracker.track(self._positions())
        self.assertIsInstance(r, dict)

    def test_track_result_has_schema_version(self):
        r = self.tracker.track(self._positions())
        self.assertEqual(r["schema_version"], 1)

    def test_track_result_has_mp_tag(self):
        r = self.tracker.track(self._positions())
        self.assertEqual(r["mp_tag"], "MP-770")

    def test_track_position_count(self):
        r = self.tracker.track(self._positions(3))
        self.assertEqual(r["position_count"], 3)

    def test_track_empty_positions(self):
        r = self.tracker.track([])
        self.assertEqual(r["position_count"], 0)
        self.assertEqual(r["aggregate"]["portfolio_efficiency_score"], 0.0)
        self.assertEqual(r["aggregate"]["portfolio_grade"], "F")

    def test_track_per_position_list(self):
        r = self.tracker.track(self._positions(2))
        self.assertEqual(len(r["per_position"]), 2)

    def test_track_aggregate_present(self):
        r = self.tracker.track(self._positions())
        self.assertIn("aggregate", r)

    def test_track_portfolio_score_average_of_positions(self):
        positions = [
            _make_pos("a", utilization_rate_pct=100.0, apy=MAX_APY),     # score=100
            _make_pos("b", utilization_rate_pct=0.0, apy=0.0),           # score=0
        ]
        r = self.tracker.track(positions)
        self.assertAlmostEqual(
            r["aggregate"]["portfolio_efficiency_score"], 50.0, places=2
        )

    def test_track_grade_distribution(self):
        positions = [
            _make_pos("a", utilization_rate_pct=100.0, apy=MAX_APY),   # A
            _make_pos("b", utilization_rate_pct=0.0, apy=0.0),          # F
        ]
        r = self.tracker.track(positions)
        dist = r["aggregate"]["grade_distribution"]
        self.assertIn("A", dist)
        self.assertIn("F", dist)

    def test_track_malformed_position_handled(self):
        bad_pos = {"protocol": "bad", "deployed_usd": "not_a_number"}
        # Should not raise; might include error key or degrade gracefully
        try:
            r = self.tracker.track([bad_pos])
            self.assertIsInstance(r, dict)
        except Exception:  # pragma: no cover
            self.fail("track() raised on malformed position")

    def test_track_total_deployed_sum(self):
        positions = [
            _make_pos("a", deployed_usd=30000.0, idle_usd=0.0),
            _make_pos("b", deployed_usd=70000.0, idle_usd=0.0),
        ]
        r = self.tracker.track(positions)
        self.assertAlmostEqual(
            r["aggregate"]["total_deployed_usd"], 100000.0, places=2
        )

    def test_track_total_idle_sum(self):
        positions = [
            _make_pos("a", deployed_usd=50000.0, idle_usd=10000.0),
            _make_pos("b", deployed_usd=50000.0, idle_usd=5000.0),
        ]
        r = self.tracker.track(positions)
        self.assertAlmostEqual(
            r["aggregate"]["total_idle_usd"], 15000.0, places=2
        )

    def test_track_portfolio_idle_pct(self):
        positions = [
            _make_pos("a", deployed_usd=90000.0, idle_usd=10000.0),
        ]
        r = self.tracker.track(positions)
        self.assertAlmostEqual(
            r["aggregate"]["portfolio_idle_pct"], 10.0, places=2
        )

    def test_track_total_opportunity_cost(self):
        idle = 10000.0
        bench = 0.05
        positions = [_make_pos("a", idle_usd=idle)]
        r = self.tracker.track(positions, benchmark_apy=bench)
        expected = idle * bench / 365.0
        self.assertAlmostEqual(
            r["aggregate"]["total_opportunity_cost_usd_daily"], expected, places=6
        )

    def test_track_stores_last_result(self):
        self.assertIsNone(self.tracker._last_result)
        self.tracker.track(self._positions())
        self.assertIsNotNone(self.tracker._last_result)

    def test_track_benchmark_apy_default(self):
        r = self.tracker.track(self._positions())
        self.assertEqual(r["benchmark_apy"], DEFAULT_BENCHMARK_APY)

    def test_track_benchmark_apy_custom(self):
        r = self.tracker.track(self._positions(), benchmark_apy=0.08)
        self.assertEqual(r["benchmark_apy"], 0.08)


# ===========================================================================
# 5. CapitalEfficiencyTracker.get_efficiency_score()
# ===========================================================================

class TestGetEfficiencyScore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = CapitalEfficiencyTracker(data_dir=self.tmp)

    def test_returns_none_before_track(self):
        self.assertIsNone(self.tracker.get_efficiency_score())

    def test_returns_float_after_track(self):
        self.tracker.track([_make_pos()])
        score = self.tracker.get_efficiency_score()
        self.assertIsInstance(score, float)

    def test_score_in_range(self):
        self.tracker.track([_make_pos(utilization_rate_pct=50.0, apy=0.10)])
        score = self.tracker.get_efficiency_score()
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_score_updates_on_second_track(self):
        self.tracker.track([_make_pos(utilization_rate_pct=0.0)])
        score1 = self.tracker.get_efficiency_score()
        self.tracker.track([_make_pos(utilization_rate_pct=100.0, apy=MAX_APY)])
        score2 = self.tracker.get_efficiency_score()
        self.assertGreater(score2, score1)


# ===========================================================================
# 6. CapitalEfficiencyTracker.get_idle_capital_report()
# ===========================================================================

class TestGetIdleCapitalReport(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = CapitalEfficiencyTracker(data_dir=self.tmp)

    def test_empty_report_before_track(self):
        rep = self.tracker.get_idle_capital_report()
        self.assertEqual(rep["total_idle_usd"], 0.0)
        self.assertEqual(rep["total_deployed_usd"], 0.0)
        self.assertEqual(rep["portfolio_idle_pct"], 0.0)
        self.assertEqual(rep["total_opportunity_cost_usd_daily"], 0.0)
        self.assertEqual(rep["per_position"], [])

    def test_report_has_required_keys(self):
        self.tracker.track([_make_pos()])
        rep = self.tracker.get_idle_capital_report()
        for k in [
            "total_idle_usd", "total_deployed_usd",
            "portfolio_idle_pct", "total_opportunity_cost_usd_daily",
            "per_position",
        ]:
            self.assertIn(k, rep)

    def test_per_position_count_matches(self):
        self.tracker.track([_make_pos("a"), _make_pos("b")])
        rep = self.tracker.get_idle_capital_report()
        self.assertEqual(len(rep["per_position"]), 2)

    def test_per_position_fields(self):
        self.tracker.track([_make_pos("x", idle_usd=5000.0)])
        rep = self.tracker.get_idle_capital_report()
        pos = rep["per_position"][0]
        self.assertIn("protocol", pos)
        self.assertIn("idle_usd", pos)
        self.assertIn("idle_capital_pct", pos)
        self.assertIn("opportunity_cost_usd_daily", pos)

    def test_report_total_idle_correct(self):
        self.tracker.track([
            _make_pos("a", idle_usd=3000.0),
            _make_pos("b", idle_usd=7000.0),
        ])
        rep = self.tracker.get_idle_capital_report()
        self.assertAlmostEqual(rep["total_idle_usd"], 10000.0, places=4)


# ===========================================================================
# 7. CapitalEfficiencyTracker.save() — ring buffer & atomic write
# ===========================================================================

class TestTrackerSave(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tracker = CapitalEfficiencyTracker(data_dir=self.tmp)

    def _log_path(self):
        return Path(self.tmp) / LOG_FILENAME

    def test_save_returns_false_before_track(self):
        self.assertFalse(self.tracker.save())

    def test_save_returns_true_after_track(self):
        self.tracker.track([_make_pos()])
        self.assertTrue(self.tracker.save())

    def test_save_creates_file(self):
        self.tracker.track([_make_pos()])
        self.tracker.save()
        self.assertTrue(self._log_path().exists())

    def test_save_file_is_valid_json(self):
        self.tracker.track([_make_pos()])
        self.tracker.save()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_save_appends_entries(self):
        for i in range(3):
            self.tracker.track([_make_pos(f"p{i}")])
            self.tracker.save()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_caps_at_100(self):
        tracker = CapitalEfficiencyTracker(data_dir=self.tmp, ring_cap=5)
        for i in range(8):
            tracker.track([_make_pos(f"p{i}")])
            tracker.save()
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_keeps_newest(self):
        tracker = CapitalEfficiencyTracker(data_dir=self.tmp, ring_cap=3)
        for i in range(5):
            tracker.track([_make_pos(f"proto_{i}")])
            tracker.save()
        with open(self._log_path()) as f:
            data = json.load(f)
        protocols_in_log = [
            d["per_position"][0]["protocol"] for d in data if d["per_position"]
        ]
        self.assertIn("proto_4", protocols_in_log)
        self.assertNotIn("proto_0", protocols_in_log)

    def test_ring_buffer_default_cap_100(self):
        self.assertEqual(RING_BUFFER_CAP, 100)


# ===========================================================================
# 8. _atomic_write and _load_json_list helpers
# ===========================================================================

class TestAtomicWriteAndLoad(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def test_atomic_write_creates_file(self):
        p = Path(self.tmp_dir) / "test.json"
        _atomic_write(p, [{"key": "val"}])
        self.assertTrue(p.exists())

    def test_atomic_write_valid_json(self):
        p = Path(self.tmp_dir) / "test.json"
        _atomic_write(p, {"a": 1})
        with open(p) as f:
            self.assertEqual(json.load(f), {"a": 1})

    def test_atomic_write_no_tmp_leftover(self):
        p = Path(self.tmp_dir) / "sub" / "test.json"
        _atomic_write(p, [])
        tmp_files = list(Path(self.tmp_dir).rglob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_load_json_list_missing_file(self):
        p = Path(self.tmp_dir) / "nonexistent.json"
        result = _load_json_list(p)
        self.assertEqual(result, [])

    def test_load_json_list_empty_file(self):
        p = Path(self.tmp_dir) / "empty.json"
        p.write_text("[]")
        self.assertEqual(_load_json_list(p), [])

    def test_load_json_list_valid(self):
        p = Path(self.tmp_dir) / "data.json"
        _atomic_write(p, [{"x": 1}, {"x": 2}])
        result = _load_json_list(p)
        self.assertEqual(len(result), 2)

    def test_load_json_list_non_list_returns_empty(self):
        p = Path(self.tmp_dir) / "obj.json"
        _atomic_write(p, {"key": "val"})
        self.assertEqual(_load_json_list(p), [])

    def test_load_json_list_invalid_json_returns_empty(self):
        p = Path(self.tmp_dir) / "bad.json"
        p.write_text("not json {{")
        self.assertEqual(_load_json_list(p), [])


# ===========================================================================
# 9. build_capital_efficiency_report functional API
# ===========================================================================

class TestBuildReport(unittest.TestCase):

    def test_functional_api_returns_dict(self):
        r = build_capital_efficiency_report([_make_pos()])
        self.assertIsInstance(r, dict)

    def test_functional_api_empty(self):
        r = build_capital_efficiency_report([])
        self.assertEqual(r["position_count"], 0)

    def test_functional_api_per_position_count(self):
        positions = [_make_pos(f"p{i}") for i in range(4)]
        r = build_capital_efficiency_report(positions)
        self.assertEqual(r["position_count"], 4)

    def test_functional_api_custom_benchmark(self):
        r = build_capital_efficiency_report([_make_pos()], benchmark_apy=0.08)
        self.assertEqual(r["benchmark_apy"], 0.08)


# ===========================================================================
# 10. write_status functional API
# ===========================================================================

class TestWriteStatus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_write_status_creates_log_file(self):
        write_status([_make_pos()], data_dir=self.tmp)
        log_file = Path(self.tmp) / LOG_FILENAME
        self.assertTrue(log_file.exists())

    def test_write_status_returns_dict(self):
        r = write_status([_make_pos()], data_dir=self.tmp)
        self.assertIsInstance(r, dict)

    def test_write_status_empty_positions(self):
        r = write_status([], data_dir=self.tmp)
        self.assertEqual(r["position_count"], 0)


# ===========================================================================
# 11. Edge cases / integration
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_single_position_no_idle(self):
        pos = _make_pos(deployed_usd=100000.0, idle_usd=0.0, utilization_rate_pct=100.0)
        r = build_capital_efficiency_report([pos])
        self.assertEqual(r["aggregate"]["total_idle_usd"], 0.0)

    def test_all_positions_grade_A(self):
        positions = [
            _make_pos(f"p{i}", utilization_rate_pct=100.0, apy=MAX_APY)
            for i in range(5)
        ]
        r = build_capital_efficiency_report(positions)
        dist = r["aggregate"]["grade_distribution"]
        self.assertEqual(dist.get("A", 0), 5)
        self.assertEqual(dist.get("F", 0), 0)

    def test_all_positions_grade_F(self):
        positions = [
            _make_pos(f"p{i}", utilization_rate_pct=0.0, apy=0.0)
            for i in range(3)
        ]
        r = build_capital_efficiency_report(positions)
        dist = r["aggregate"]["grade_distribution"]
        self.assertEqual(dist.get("F", 0), 3)

    def test_large_idle_usd_opportunity_cost(self):
        idle = 1_000_000.0
        bench = 0.10
        pos = _make_pos(idle_usd=idle)
        r = compute_position_efficiency(
            protocol="test", deployed_usd=0.0, idle_usd=idle,
            apy=0.0, utilization_rate_pct=0.0, benchmark_apy=bench
        )
        expected = idle * bench / 365.0
        self.assertAlmostEqual(r["opportunity_cost_usd_daily"], expected, places=4)

    def test_multiple_saves_ring_buffer_integrity(self):
        tracker = CapitalEfficiencyTracker(data_dir=self.tmp, ring_cap=100)
        for i in range(50):
            tracker.track([_make_pos(f"p{i}")])
            tracker.save()
        log_path = Path(self.tmp) / LOG_FILENAME
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 50)

    def test_tracker_position_count_valid_in_aggregate(self):
        tracker = CapitalEfficiencyTracker(data_dir=self.tmp)
        positions = [_make_pos(f"p{i}") for i in range(6)]
        r = tracker.track(positions)
        self.assertEqual(r["aggregate"]["position_count_valid"], 6)

    def test_very_small_apy_still_produces_score(self):
        r = compute_position_efficiency(
            protocol="test", deployed_usd=50000.0, idle_usd=0.0,
            apy=0.0001, utilization_rate_pct=100.0
        )
        self.assertGreater(r["capital_efficiency_score"], 0.0)
        self.assertLess(r["capital_efficiency_score"], 1.0)

    def test_result_is_json_serialisable(self):
        tracker = CapitalEfficiencyTracker(data_dir=self.tmp)
        r = tracker.track([_make_pos()])
        try:
            json.dumps(r)
        except (TypeError, ValueError) as e:
            self.fail(f"Result is not JSON serialisable: {e}")

    def test_grade_thresholds_count(self):
        self.assertEqual(len(GRADE_THRESHOLDS), 5)

    def test_max_apy_constant(self):
        self.assertAlmostEqual(MAX_APY, 0.30, places=6)

    def test_default_benchmark_apy(self):
        self.assertAlmostEqual(DEFAULT_BENCHMARK_APY, 0.05, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
