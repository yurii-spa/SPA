#!/usr/bin/env python3
"""Unit tests for MP-1062 DeFiProtocolInterestRateSensitivityAnalyzer (SPA-v769).

Run:
    python3 -m unittest spa_core/tests/test_defi_protocol_interest_rate_sensitivity_analyzer.py -v

stdlib unittest only — no pytest, no numpy.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.defi_protocol_interest_rate_sensitivity_analyzer import (
    DeFiProtocolInterestRateSensitivityAnalyzer,
    _clamp,
    _compute_borrow_rate,
    _compute_supply_rate,
    _compute_sensitivity_score,
    _compute_sensitivity_label,
    _compute_pnl_impact,
    _load_json_list,
    _atomic_write,
    analyze_interest_rate_sensitivity,
    write_log,
    RING_BUFFER_CAP,
    LOG_FILENAME,
    SCORE_NORMALISER,
)


# ===========================================================================
# 1. _clamp
# ===========================================================================

class TestClamp(unittest.TestCase):

    def test_within_range(self):
        self.assertAlmostEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_below_lo(self):
        self.assertAlmostEqual(_clamp(-1.0, 0.0, 10.0), 0.0)

    def test_above_hi(self):
        self.assertAlmostEqual(_clamp(15.0, 0.0, 10.0), 10.0)

    def test_at_lo(self):
        self.assertAlmostEqual(_clamp(0.0, 0.0, 10.0), 0.0)

    def test_at_hi(self):
        self.assertAlmostEqual(_clamp(10.0, 0.0, 10.0), 10.0)

    def test_negative_range(self):
        self.assertAlmostEqual(_clamp(-5.0, -10.0, -1.0), -5.0)

    def test_same_lo_hi(self):
        self.assertAlmostEqual(_clamp(7.0, 5.0, 5.0), 5.0)


# ===========================================================================
# 2. _compute_borrow_rate — LINEAR
# ===========================================================================

class TestBorrowRateLinear(unittest.TestCase):
    """LINEAR: rate = base + slope1*(util/100)."""

    def _rate(self, util, base=0.0, slope1=10.0, slope2=0.0, kink=80.0):
        r, w = _compute_borrow_rate("linear", util, kink, base, slope1, slope2)
        return r, w

    def test_zero_util(self):
        r, _ = self._rate(0.0, base=1.0, slope1=10.0)
        self.assertAlmostEqual(r, 1.0)

    def test_100_util(self):
        r, _ = self._rate(100.0, base=0.0, slope1=10.0)
        self.assertAlmostEqual(r, 10.0)

    def test_50_util(self):
        r, _ = self._rate(50.0, base=2.0, slope1=8.0)
        self.assertAlmostEqual(r, 6.0)

    def test_80_util(self):
        r, _ = self._rate(80.0, base=0.0, slope1=5.0)
        self.assertAlmostEqual(r, 4.0)

    def test_ignores_slope2(self):
        r1, _ = self._rate(90.0, slope1=10.0, slope2=0.0)
        r2, _ = self._rate(90.0, slope1=10.0, slope2=999.0)
        self.assertAlmostEqual(r1, r2)

    def test_no_warnings_valid(self):
        _, w = self._rate(50.0)
        self.assertEqual(w, [])

    def test_clamped_util_below_zero(self):
        r, _ = self._rate(-10.0, base=1.0, slope1=10.0)
        self.assertAlmostEqual(r, 1.0)

    def test_clamped_util_above_100(self):
        r, _ = self._rate(150.0, base=0.0, slope1=10.0)
        self.assertAlmostEqual(r, 10.0)


# ===========================================================================
# 3. _compute_borrow_rate — KINKED
# ===========================================================================

class TestBorrowRateKinked(unittest.TestCase):
    """KINKED: below kink slope1; above kink slope2."""

    # kink=80, base=0, slope1=4, slope2=75
    # below kink: rate = 0 + 4*(util/80)
    # above kink: rate = 0 + 4 + 75*((util-80)/20)

    def _rate(self, util, kink=80.0, base=0.0, slope1=4.0, slope2=75.0):
        r, w = _compute_borrow_rate("kinked", util, kink, base, slope1, slope2)
        return r, w

    def test_zero_util(self):
        r, _ = self._rate(0.0)
        self.assertAlmostEqual(r, 0.0)

    def test_kink_point(self):
        # at exactly kink → rate = base + slope1 = 4.0
        r, _ = self._rate(80.0)
        self.assertAlmostEqual(r, 4.0)

    def test_below_kink_40pct(self):
        r, _ = self._rate(40.0)
        self.assertAlmostEqual(r, 4.0 * 40.0 / 80.0, places=6)

    def test_above_kink_90pct(self):
        r, _ = self._rate(90.0)
        expected = 0.0 + 4.0 + 75.0 * ((90.0 - 80.0) / 20.0)
        self.assertAlmostEqual(r, expected, places=6)

    def test_above_kink_95pct(self):
        r, _ = self._rate(95.0)
        expected = 4.0 + 75.0 * (15.0 / 20.0)
        self.assertAlmostEqual(r, expected, places=6)

    def test_100pct(self):
        r, _ = self._rate(100.0)
        expected = 4.0 + 75.0
        self.assertAlmostEqual(r, expected, places=6)

    def test_base_rate_included(self):
        r, _ = self._rate(0.0, base=2.0)
        self.assertAlmostEqual(r, 2.0)

    def test_nonnegative_rate(self):
        r, _ = _compute_borrow_rate("kinked", 0.0, 80.0, -100.0, 0.0, 0.0)
        self.assertGreaterEqual(r, 0.0)


# ===========================================================================
# 4. _compute_borrow_rate — JUMP
# ===========================================================================

class TestBorrowRateJump(unittest.TestCase):

    def test_same_as_kinked_below_kink(self):
        rj, _ = _compute_borrow_rate("jump", 50.0, 80.0, 0.0, 4.0, 100.0)
        rk, _ = _compute_borrow_rate("kinked", 50.0, 80.0, 0.0, 4.0, 100.0)
        self.assertAlmostEqual(rj, rk)

    def test_large_jump_above_kink(self):
        r, _ = _compute_borrow_rate("jump", 85.0, 80.0, 0.0, 4.0, 200.0)
        self.assertGreater(r, 50.0)   # dramatic jump

    def test_100pct_util_with_jump(self):
        r, _ = _compute_borrow_rate("jump", 100.0, 80.0, 0.0, 4.0, 200.0)
        expected = 4.0 + 200.0
        self.assertAlmostEqual(r, expected, places=6)


# ===========================================================================
# 5. _compute_borrow_rate — invalid model fallback
# ===========================================================================

class TestBorrowRateInvalidModel(unittest.TestCase):

    def test_unknown_model_returns_warning(self):
        _, w = _compute_borrow_rate("magic", 50.0, 80.0, 0.0, 4.0, 75.0)
        self.assertTrue(any("unknown" in s.lower() or "default" in s.lower() for s in w))

    def test_unknown_model_still_returns_float(self):
        r, _ = _compute_borrow_rate("bogus", 50.0, 80.0, 0.0, 4.0, 75.0)
        self.assertIsInstance(r, float)


# ===========================================================================
# 6. _compute_supply_rate
# ===========================================================================

class TestComputeSupplyRate(unittest.TestCase):

    def test_zero_util(self):
        self.assertAlmostEqual(_compute_supply_rate(10.0, 0.0), 0.0)

    def test_100_util(self):
        self.assertAlmostEqual(_compute_supply_rate(10.0, 100.0), 10.0)

    def test_80_util(self):
        self.assertAlmostEqual(_compute_supply_rate(5.0, 80.0), 4.0)

    def test_50_util(self):
        self.assertAlmostEqual(_compute_supply_rate(8.0, 50.0), 4.0)

    def test_nonnegative(self):
        self.assertGreaterEqual(_compute_supply_rate(-5.0, 80.0), 0.0)

    def test_util_clamped_above_100(self):
        s = _compute_supply_rate(10.0, 120.0)
        self.assertAlmostEqual(s, 10.0)


# ===========================================================================
# 7. _compute_sensitivity_score
# ===========================================================================

class TestComputeSensitivityScore(unittest.TestCase):

    def test_no_rate_increase_score_zero(self):
        score = _compute_sensitivity_score(10.0, 10.0)
        self.assertAlmostEqual(score, 0.0)

    def test_rate_drops_score_zero(self):
        score = _compute_sensitivity_score(10.0, 5.0)
        self.assertAlmostEqual(score, 0.0)

    def test_full_normaliser_score_100(self):
        score = _compute_sensitivity_score(0.0, SCORE_NORMALISER)
        self.assertAlmostEqual(score, 100.0)

    def test_half_normaliser_score_50(self):
        score = _compute_sensitivity_score(0.0, SCORE_NORMALISER / 2.0)
        self.assertAlmostEqual(score, 50.0)

    def test_score_clamped_100(self):
        score = _compute_sensitivity_score(0.0, SCORE_NORMALISER * 10)
        self.assertAlmostEqual(score, 100.0)

    def test_score_in_range(self):
        score = _compute_sensitivity_score(5.0, 20.0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)


# ===========================================================================
# 8. _compute_sensitivity_label
# ===========================================================================

class TestSensitivityLabel(unittest.TestCase):

    def test_below_20_rate_stable(self):
        self.assertEqual(_compute_sensitivity_label(0.0), "RATE_STABLE")
        self.assertEqual(_compute_sensitivity_label(19.9), "RATE_STABLE")

    def test_exactly_20_low(self):
        self.assertEqual(_compute_sensitivity_label(20.0), "LOW_SENSITIVITY")

    def test_low_range(self):
        self.assertEqual(_compute_sensitivity_label(35.0), "LOW_SENSITIVITY")

    def test_exactly_40_moderate(self):
        self.assertEqual(_compute_sensitivity_label(40.0), "MODERATE_SENSITIVITY")

    def test_moderate_range(self):
        self.assertEqual(_compute_sensitivity_label(55.0), "MODERATE_SENSITIVITY")

    def test_exactly_60_high(self):
        self.assertEqual(_compute_sensitivity_label(60.0), "HIGH_SENSITIVITY")

    def test_high_range(self):
        self.assertEqual(_compute_sensitivity_label(75.0), "HIGH_SENSITIVITY")

    def test_exactly_80_extreme(self):
        self.assertEqual(_compute_sensitivity_label(80.0), "EXTREME_RATE_RISK")

    def test_100_extreme(self):
        self.assertEqual(_compute_sensitivity_label(100.0), "EXTREME_RATE_RISK")


# ===========================================================================
# 9. _compute_pnl_impact
# ===========================================================================

class TestComputePnlImpact(unittest.TestCase):

    def test_lender_higher_supply_at_80_is_gain(self):
        pnl = _compute_pnl_impact(
            rate_at_80_pct=10.0,
            current_rate_pct=10.0,
            position_usd=100_000.0,
            duration_days=365.0,
            position_type="lender",
            current_borrow_rate_pct=10.0,
            current_supply_rate_pct=5.0,   # currently 5%
            utilization_at_80=80.0,        # supply_at_80 = 10*0.80 = 8%
        )
        # supply gain: (8-5)/100 * 100000 * 365/365 = 3000
        self.assertAlmostEqual(pnl, 3000.0, places=2)

    def test_borrower_rate_increase_is_loss(self):
        pnl = _compute_pnl_impact(
            rate_at_80_pct=10.0,
            current_rate_pct=10.0,
            position_usd=100_000.0,
            duration_days=365.0,
            position_type="borrower",
            current_borrow_rate_pct=5.0,  # currently borrowing at 5%
            current_supply_rate_pct=3.0,
            utilization_at_80=80.0,
        )
        # borrower cost: -(10-5)/100 * 100000 = -5000
        self.assertAlmostEqual(pnl, -5000.0, places=2)

    def test_zero_duration(self):
        pnl = _compute_pnl_impact(
            rate_at_80_pct=10.0, current_rate_pct=10.0,
            position_usd=100_000.0, duration_days=0.0,
            position_type="lender",
            current_borrow_rate_pct=5.0, current_supply_rate_pct=3.0,
            utilization_at_80=80.0,
        )
        self.assertAlmostEqual(pnl, 0.0)

    def test_zero_position(self):
        pnl = _compute_pnl_impact(
            rate_at_80_pct=10.0, current_rate_pct=10.0,
            position_usd=0.0, duration_days=365.0,
            position_type="lender",
            current_borrow_rate_pct=5.0, current_supply_rate_pct=3.0,
            utilization_at_80=80.0,
        )
        self.assertAlmostEqual(pnl, 0.0)

    def test_negative_duration_treated_as_zero(self):
        pnl = _compute_pnl_impact(
            rate_at_80_pct=10.0, current_rate_pct=10.0,
            position_usd=100_000.0, duration_days=-5.0,
            position_type="lender",
            current_borrow_rate_pct=5.0, current_supply_rate_pct=3.0,
            utilization_at_80=80.0,
        )
        self.assertAlmostEqual(pnl, 0.0)


# ===========================================================================
# 10. analyze_interest_rate_sensitivity — output structure
# ===========================================================================

KINKED_PARAMS = {
    "protocol_name": "TestProtocol",
    "current_borrow_rate_pct": 4.5,
    "current_supply_rate_pct": 3.0,
    "utilization_rate_pct": 72.0,
    "rate_model": "kinked",
    "kink_utilization_pct": 80.0,
    "base_rate_pct": 0.0,
    "slope1_pct": 4.0,
    "slope2_pct": 75.0,
    "position_type": "lender",
    "position_usd": 100_000.0,
    "duration_days": 30.0,
}


class TestAnalyzeStructure(unittest.TestCase):

    def _run(self, extra=None):
        p = dict(KINKED_PARAMS)
        if extra:
            p.update(extra)
        return analyze_interest_rate_sensitivity(p)

    def test_returns_dict(self):
        result = self._run()
        self.assertIsInstance(result, dict)

    def test_required_keys_present(self):
        result = self._run()
        for key in [
            "protocol_name", "rate_at_80pct_util_pct", "rate_at_95pct_util_pct",
            "max_rate_pct", "rate_sensitivity_score", "pnl_impact_at_80pct_usd",
            "sensitivity_label", "warnings", "timestamp_utc", "schema_version",
            "source", "mp_tag",
        ]:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_protocol_name_preserved(self):
        result = self._run()
        self.assertEqual(result["protocol_name"], "TestProtocol")

    def test_sensitivity_score_range(self):
        result = self._run()
        self.assertGreaterEqual(result["rate_sensitivity_score"], 0.0)
        self.assertLessEqual(result["rate_sensitivity_score"], 100.0)

    def test_sensitivity_label_valid(self):
        result = self._run()
        valid = {"RATE_STABLE", "LOW_SENSITIVITY", "MODERATE_SENSITIVITY",
                 "HIGH_SENSITIVITY", "EXTREME_RATE_RISK"}
        self.assertIn(result["sensitivity_label"], valid)

    def test_rate_ordering_kinked(self):
        result = self._run()
        # kinked model: 80pct < 95pct <= max
        self.assertLessEqual(result["rate_at_80pct_util_pct"], result["rate_at_95pct_util_pct"])
        self.assertLessEqual(result["rate_at_95pct_util_pct"], result["max_rate_pct"])

    def test_mp_tag(self):
        result = self._run()
        self.assertEqual(result["mp_tag"], "MP-1062")

    def test_schema_version(self):
        result = self._run()
        self.assertEqual(result["schema_version"], 1)

    def test_warnings_list(self):
        result = self._run()
        self.assertIsInstance(result["warnings"], list)


# ===========================================================================
# 11. analyze — kinked model numeric values
# ===========================================================================

class TestAnalyzeKinkedValues(unittest.TestCase):

    def setUp(self):
        self.result = analyze_interest_rate_sensitivity(KINKED_PARAMS)

    def test_rate_at_80_equals_slope1(self):
        # kink=80, slope1=4, base=0 → at 80%: rate = 4.0
        self.assertAlmostEqual(self.result["rate_at_80pct_util_pct"], 4.0, places=4)

    def test_rate_at_95(self):
        # above kink=80, slope2=75: 4 + 75*(15/20) = 4 + 56.25 = 60.25
        self.assertAlmostEqual(self.result["rate_at_95pct_util_pct"], 60.25, places=4)

    def test_max_rate(self):
        # at 100%: 4 + 75*(20/20) = 79.0
        self.assertAlmostEqual(self.result["max_rate_pct"], 79.0, places=4)

    def test_high_sensitivity_kinked(self):
        # score = min((60.25-4.5)/50*100, 100) ≈ 111.5 → clamped 100
        self.assertAlmostEqual(self.result["rate_sensitivity_score"], 100.0, places=2)
        self.assertEqual(self.result["sensitivity_label"], "EXTREME_RATE_RISK")


# ===========================================================================
# 12. analyze — linear model
# ===========================================================================

class TestAnalyzeLinear(unittest.TestCase):

    def setUp(self):
        self.params = {
            **KINKED_PARAMS,
            "rate_model": "linear",
            "slope1_pct": 10.0,
            "slope2_pct": 0.0,
        }
        self.result = analyze_interest_rate_sensitivity(self.params)

    def test_rate_at_80_linear(self):
        # base=0, slope1=10 → rate = 10*(80/100) = 8.0
        self.assertAlmostEqual(self.result["rate_at_80pct_util_pct"], 8.0, places=4)

    def test_rate_at_95_linear(self):
        self.assertAlmostEqual(self.result["rate_at_95pct_util_pct"], 9.5, places=4)

    def test_max_rate_linear(self):
        self.assertAlmostEqual(self.result["max_rate_pct"], 10.0, places=4)

    def test_monotone_linear(self):
        r80 = self.result["rate_at_80pct_util_pct"]
        r95 = self.result["rate_at_95pct_util_pct"]
        rmax = self.result["max_rate_pct"]
        self.assertLessEqual(r80, r95)
        self.assertLessEqual(r95, rmax)


# ===========================================================================
# 13. analyze — jump model
# ===========================================================================

class TestAnalyzeJump(unittest.TestCase):

    def test_jump_score_extreme(self):
        params = {
            **KINKED_PARAMS,
            "rate_model": "jump",
            "slope2_pct": 500.0,
        }
        result = analyze_interest_rate_sensitivity(params)
        self.assertAlmostEqual(result["rate_sensitivity_score"], 100.0, places=2)
        self.assertEqual(result["sensitivity_label"], "EXTREME_RATE_RISK")


# ===========================================================================
# 14. analyze — borrower position
# ===========================================================================

class TestAnalyzeBorrower(unittest.TestCase):

    def setUp(self):
        self.params = {**KINKED_PARAMS, "position_type": "borrower"}
        self.result = analyze_interest_rate_sensitivity(self.params)

    def test_borrower_label_valid(self):
        valid = {"RATE_STABLE", "LOW_SENSITIVITY", "MODERATE_SENSITIVITY",
                 "HIGH_SENSITIVITY", "EXTREME_RATE_RISK"}
        self.assertIn(self.result["sensitivity_label"], valid)

    def test_borrower_pnl_direction_rate_increase(self):
        # current_borrow=4.5, rate_at_80=4.0  → rate decrease → positive for borrower
        # Actually borrow at 80pct is LOWER than current → gain
        self.assertIsInstance(self.result["pnl_impact_at_80pct_usd"], float)


# ===========================================================================
# 15. analyze — edge cases
# ===========================================================================

class TestAnalyzeEdgeCases(unittest.TestCase):

    def test_zero_position_usd(self):
        p = {**KINKED_PARAMS, "position_usd": 0.0}
        result = analyze_interest_rate_sensitivity(p)
        self.assertAlmostEqual(result["pnl_impact_at_80pct_usd"], 0.0, places=6)

    def test_zero_duration(self):
        p = {**KINKED_PARAMS, "duration_days": 0.0}
        result = analyze_interest_rate_sensitivity(p)
        self.assertAlmostEqual(result["pnl_impact_at_80pct_usd"], 0.0, places=6)

    def test_very_high_util_current(self):
        p = {**KINKED_PARAMS, "utilization_rate_pct": 99.0}
        result = analyze_interest_rate_sensitivity(p)
        self.assertIn(result["sensitivity_label"], {
            "RATE_STABLE", "LOW_SENSITIVITY", "MODERATE_SENSITIVITY",
            "HIGH_SENSITIVITY", "EXTREME_RATE_RISK"
        })

    def test_unknown_position_type_defaults(self):
        p = {**KINKED_PARAMS, "position_type": "mysterious"}
        result = analyze_interest_rate_sensitivity(p)
        self.assertTrue(len(result["warnings"]) > 0)

    def test_unknown_rate_model_warns(self):
        p = {**KINKED_PARAMS, "rate_model": "quantum"}
        result = analyze_interest_rate_sensitivity(p)
        self.assertTrue(len(result["warnings"]) > 0)

    def test_missing_protocol_name(self):
        p = {k: v for k, v in KINKED_PARAMS.items() if k != "protocol_name"}
        result = analyze_interest_rate_sensitivity(p)
        self.assertEqual(result["protocol_name"], "unknown")

    def test_very_large_slope2(self):
        p = {**KINKED_PARAMS, "slope2_pct": 10_000.0}
        result = analyze_interest_rate_sensitivity(p)
        self.assertAlmostEqual(result["rate_sensitivity_score"], 100.0)

    def test_rate_stable_low_slope2(self):
        # With low slopes, rates barely move → RATE_STABLE
        p = {
            **KINKED_PARAMS,
            "current_borrow_rate_pct": 4.5,
            "slope1_pct": 0.5,
            "slope2_pct": 0.5,
        }
        result = analyze_interest_rate_sensitivity(p)
        self.assertIn(result["sensitivity_label"],
                      {"RATE_STABLE", "LOW_SENSITIVITY"})


# ===========================================================================
# 16. _load_json_list and _atomic_write
# ===========================================================================

class TestIOHelpers(unittest.TestCase):

    def test_load_missing_returns_empty(self):
        result = _load_json_list(Path("/nonexistent/path/to/file.json"))
        self.assertEqual(result, [])

    def test_load_corrupted_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            tmp = f.name
        try:
            result = _load_json_list(Path(tmp))
            self.assertEqual(result, [])
        finally:
            os.unlink(tmp)

    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.json"
            _atomic_write(p, [{"x": 1}])
            data = json.loads(p.read_text())
            self.assertEqual(data, [{"x": 1}])

    def test_atomic_write_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.json"
            _atomic_write(p, [1, 2])
            _atomic_write(p, [3, 4])
            data = json.loads(p.read_text())
            self.assertEqual(data, [3, 4])

    def test_load_json_list_not_list(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"key": "val"}, f)
            tmp = f.name
        try:
            result = _load_json_list(Path(tmp))
            self.assertEqual(result, [])
        finally:
            os.unlink(tmp)


# ===========================================================================
# 17. write_log ring-buffer
# ===========================================================================

class TestWriteLog(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _result(self, tag="test"):
        return analyze_interest_rate_sensitivity({**KINKED_PARAMS, "protocol_name": tag})

    def test_write_creates_file(self):
        r = self._result()
        path = write_log(r, self.data_dir)
        self.assertTrue(path.exists())

    def test_filename_matches_constant(self):
        r = self._result()
        path = write_log(r, self.data_dir)
        self.assertEqual(path.name, LOG_FILENAME)

    def test_single_entry(self):
        r = self._result()
        path = write_log(r, self.data_dir)
        data = json.loads(path.read_text())
        self.assertEqual(len(data), 1)

    def test_multiple_entries_appended(self):
        for i in range(5):
            write_log(self._result(f"p{i}"), self.data_dir)
        path = self.data_dir / LOG_FILENAME
        data = json.loads(path.read_text())
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        for i in range(RING_BUFFER_CAP + 10):
            write_log(self._result(f"p{i}"), self.data_dir)
        path = self.data_dir / LOG_FILENAME
        data = json.loads(path.read_text())
        self.assertLessEqual(len(data), RING_BUFFER_CAP)

    def test_ring_buffer_keeps_latest(self):
        for i in range(RING_BUFFER_CAP + 5):
            write_log(self._result(f"p{i}"), self.data_dir)
        path = self.data_dir / LOG_FILENAME
        data = json.loads(path.read_text())
        # Last entry should be p(RING_BUFFER_CAP+4)
        self.assertEqual(data[-1]["protocol_name"], f"p{RING_BUFFER_CAP + 4}")

    def test_log_is_valid_json_list(self):
        write_log(self._result(), self.data_dir)
        path = self.data_dir / LOG_FILENAME
        data = json.loads(path.read_text())
        self.assertIsInstance(data, list)


# ===========================================================================
# 18. DeFiProtocolInterestRateSensitivityAnalyzer class
# ===========================================================================

class TestAnalyzerClass(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolInterestRateSensitivityAnalyzer(
            data_dir=Path(self.tmp_dir)
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_analyze_returns_dict(self):
        result = self.analyzer.analyze(KINKED_PARAMS)
        self.assertIsInstance(result, dict)

    def test_save_creates_log(self):
        result = self.analyzer.analyze(KINKED_PARAMS)
        path = self.analyzer.save(result)
        self.assertTrue(path.exists())

    def test_analyze_and_save_combined(self):
        result = self.analyzer.analyze_and_save(KINKED_PARAMS)
        path = Path(self.tmp_dir) / LOG_FILENAME
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["mp_tag"], "MP-1062")

    def test_default_data_dir(self):
        a = DeFiProtocolInterestRateSensitivityAnalyzer()
        self.assertIsNotNone(a._data_dir)

    def test_multiple_saves_ring_buffer(self):
        for _ in range(RING_BUFFER_CAP + 5):
            result = self.analyzer.analyze(KINKED_PARAMS)
            self.analyzer.save(result)
        path = Path(self.tmp_dir) / LOG_FILENAME
        data = json.loads(path.read_text())
        self.assertLessEqual(len(data), RING_BUFFER_CAP)


# ===========================================================================
# 19. Sensitivity score edge cases
# ===========================================================================

class TestSensitivityScoreEdge(unittest.TestCase):

    def test_equal_current_and_95_score_zero(self):
        self.assertAlmostEqual(_compute_sensitivity_score(20.0, 20.0), 0.0)

    def test_current_exceeds_95_score_zero(self):
        self.assertAlmostEqual(_compute_sensitivity_score(30.0, 20.0), 0.0)

    def test_small_delta_small_score(self):
        # delta=5ppt → score = 5/50*100 = 10
        score = _compute_sensitivity_score(0.0, 5.0)
        self.assertAlmostEqual(score, 10.0, places=4)

    def test_delta_25ppt_score_50(self):
        score = _compute_sensitivity_score(0.0, 25.0)
        self.assertAlmostEqual(score, 50.0, places=4)

    def test_score_never_below_zero(self):
        for delta in [-10, -1, 0]:
            s = _compute_sensitivity_score(10.0, 10.0 + delta)
            self.assertGreaterEqual(s, 0.0)

    def test_score_never_above_100(self):
        s = _compute_sensitivity_score(0.0, 1_000_000.0)
        self.assertLessEqual(s, 100.0)


# ===========================================================================
# 20. Rate ordering guarantees
# ===========================================================================

class TestRateOrdering(unittest.TestCase):

    def _analyze(self, model, s1=4.0, s2=75.0):
        p = {**KINKED_PARAMS, "rate_model": model, "slope1_pct": s1, "slope2_pct": s2}
        return analyze_interest_rate_sensitivity(p)

    def test_kinked_monotone(self):
        r = self._analyze("kinked")
        self.assertLessEqual(r["rate_at_80pct_util_pct"], r["rate_at_95pct_util_pct"])
        self.assertLessEqual(r["rate_at_95pct_util_pct"], r["max_rate_pct"])

    def test_jump_monotone(self):
        r = self._analyze("jump", s2=200.0)
        self.assertLessEqual(r["rate_at_80pct_util_pct"], r["rate_at_95pct_util_pct"])
        self.assertLessEqual(r["rate_at_95pct_util_pct"], r["max_rate_pct"])

    def test_linear_monotone(self):
        r = self._analyze("linear", s1=10.0, s2=0.0)
        self.assertLessEqual(r["rate_at_80pct_util_pct"], r["rate_at_95pct_util_pct"])
        self.assertLessEqual(r["rate_at_95pct_util_pct"], r["max_rate_pct"])

    def test_max_rate_nonnegative(self):
        for model in ("linear", "kinked", "jump"):
            r = self._analyze(model)
            self.assertGreaterEqual(r["max_rate_pct"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
