#!/usr/bin/env python3
"""
Tests for MP-1058: DeFiProtocolCollateralEfficiencyRatioAnalyzer
Uses unittest only (no pytest). ≥90 tests.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_collateral_efficiency_ratio_analyzer
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_collateral_efficiency_ratio_analyzer import (
    DeFiProtocolCollateralEfficiencyRatioAnalyzer,
    RING_BUFFER_CAP,
    compute_capital_efficiency_score,
    compute_current_ltv,
    compute_net_carry,
    compute_safety_cushion,
    efficiency_label,
    _atomic_write_json,
    _load_json_list,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_params(**overrides):
    """Return valid base params with optional overrides."""
    base = {
        "protocol_name": "Aave V3",
        "collateral_asset": "wstETH",
        "collateral_value_usd": 100_000.0,
        "borrowed_value_usd": 70_000.0,
        "max_ltv_pct": 80.0,
        "liquidation_threshold_pct": 85.0,
        "current_apy_on_collateral_pct": 4.5,
        "borrow_rate_pct": 3.2,
        "oracle_deviation_tolerance_pct": 5.0,
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. compute_current_ltv
# ===========================================================================

class TestComputeCurrentLtv(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(compute_current_ltv(100_000, 70_000), 70.0)

    def test_zero_borrow(self):
        self.assertAlmostEqual(compute_current_ltv(100_000, 0), 0.0)

    def test_full_borrow(self):
        self.assertAlmostEqual(compute_current_ltv(100_000, 100_000), 100.0)

    def test_over_borrow(self):
        self.assertAlmostEqual(compute_current_ltv(100_000, 120_000), 120.0)

    def test_zero_collateral_returns_zero(self):
        self.assertEqual(compute_current_ltv(0, 50_000), 0.0)

    def test_negative_collateral_returns_zero(self):
        self.assertEqual(compute_current_ltv(-1, 50_000), 0.0)

    def test_small_values(self):
        self.assertAlmostEqual(compute_current_ltv(1000, 500), 50.0)

    def test_large_values(self):
        self.assertAlmostEqual(compute_current_ltv(1e9, 7.5e8), 75.0)

    def test_fractional_borrow(self):
        self.assertAlmostEqual(compute_current_ltv(10, 3.3), 33.0, places=5)

    def test_equal_collateral_borrow(self):
        self.assertAlmostEqual(compute_current_ltv(50_000, 50_000), 100.0)


# ===========================================================================
# 2. compute_safety_cushion
# ===========================================================================

class TestComputeSafetyCushion(unittest.TestCase):
    def test_positive_cushion(self):
        # liquidation=85, ltv=70 → cushion=15
        self.assertAlmostEqual(compute_safety_cushion(85.0, 70.0), 15.0)

    def test_zero_cushion(self):
        self.assertAlmostEqual(compute_safety_cushion(80.0, 80.0), 0.0)

    def test_negative_cushion(self):
        # ltv > threshold → negative (at-risk)
        self.assertAlmostEqual(compute_safety_cushion(80.0, 90.0), -10.0)

    def test_large_cushion(self):
        self.assertAlmostEqual(compute_safety_cushion(85.0, 10.0), 75.0)

    def test_threshold_zero(self):
        self.assertAlmostEqual(compute_safety_cushion(0.0, 0.0), 0.0)

    def test_typical_aave_params(self):
        ltv = compute_current_ltv(100_000, 60_000)  # 60%
        cushion = compute_safety_cushion(85.0, ltv)
        self.assertAlmostEqual(cushion, 25.0)

    def test_fractional_values(self):
        self.assertAlmostEqual(compute_safety_cushion(82.5, 77.3), 5.2, places=5)


# ===========================================================================
# 3. compute_net_carry
# ===========================================================================

class TestComputeNetCarry(unittest.TestCase):
    def test_positive_carry(self):
        self.assertAlmostEqual(compute_net_carry(4.5, 3.2), 1.3, places=5)

    def test_zero_carry(self):
        self.assertAlmostEqual(compute_net_carry(3.0, 3.0), 0.0)

    def test_negative_carry(self):
        self.assertAlmostEqual(compute_net_carry(2.0, 5.0), -3.0)

    def test_high_apy(self):
        self.assertAlmostEqual(compute_net_carry(10.0, 2.0), 8.0)

    def test_both_zero(self):
        self.assertAlmostEqual(compute_net_carry(0.0, 0.0), 0.0)

    def test_small_difference(self):
        self.assertAlmostEqual(compute_net_carry(3.01, 3.00), 0.01, places=5)

    def test_large_borrow_rate(self):
        self.assertAlmostEqual(compute_net_carry(1.0, 20.0), -19.0)


# ===========================================================================
# 4. compute_capital_efficiency_score
# ===========================================================================

class TestComputeCapitalEfficiencyScore(unittest.TestCase):
    def _score(self, **kw):
        defaults = dict(
            current_ltv_pct=70.0,
            max_ltv_pct=80.0,
            safety_cushion_pct=15.0,
            liquidation_threshold_pct=85.0,
            net_carry_pct=1.3,
            oracle_deviation_tolerance_pct=5.0,
        )
        defaults.update(kw)
        return compute_capital_efficiency_score(**defaults)

    def test_result_in_range(self):
        s = self._score()
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_max_ltv_zero_no_crash(self):
        s = self._score(max_ltv_pct=0.0, current_ltv_pct=0.0)
        self.assertGreaterEqual(s, 0.0)

    def test_negative_carry_reduces_score(self):
        s_positive = self._score(net_carry_pct=5.0)
        s_negative = self._score(net_carry_pct=-5.0)
        self.assertGreater(s_positive, s_negative)

    def test_higher_oracle_tolerance_increases_score(self):
        s_low = self._score(oracle_deviation_tolerance_pct=0.0)
        s_high = self._score(oracle_deviation_tolerance_pct=10.0)
        self.assertGreater(s_high, s_low)

    def test_full_utilization_raises_score(self):
        s_low = self._score(current_ltv_pct=10.0, max_ltv_pct=80.0)
        s_high = self._score(current_ltv_pct=80.0, max_ltv_pct=80.0)
        self.assertGreater(s_high, s_low)

    def test_big_cushion_raises_score(self):
        s_tight = self._score(safety_cushion_pct=1.0, liquidation_threshold_pct=85.0)
        s_wide = self._score(safety_cushion_pct=80.0, liquidation_threshold_pct=85.0)
        self.assertGreater(s_wide, s_tight)

    def test_score_clamped_to_100(self):
        s = self._score(
            current_ltv_pct=80.0, max_ltv_pct=80.0,
            safety_cushion_pct=85.0, liquidation_threshold_pct=85.0,
            net_carry_pct=100.0, oracle_deviation_tolerance_pct=100.0,
        )
        self.assertLessEqual(s, 100.0)

    def test_score_clamped_to_0(self):
        s = self._score(
            current_ltv_pct=0.0, max_ltv_pct=0.0,
            safety_cushion_pct=-100.0, liquidation_threshold_pct=0.0,
            net_carry_pct=-100.0, oracle_deviation_tolerance_pct=0.0,
        )
        self.assertGreaterEqual(s, 0.0)

    def test_typical_aave_score_is_reasonable(self):
        # ltv=70/80, cushion=15/85, carry=1.3, oracle=5 → expect decent score
        s = self._score()
        self.assertGreater(s, 30.0)

    def test_oracle_capped_at_10(self):
        s_10 = self._score(oracle_deviation_tolerance_pct=10.0)
        s_20 = self._score(oracle_deviation_tolerance_pct=20.0)
        self.assertAlmostEqual(s_10, s_20)

    def test_carry_capped_at_positive(self):
        s_5 = self._score(net_carry_pct=5.0)
        s_50 = self._score(net_carry_pct=50.0)
        self.assertAlmostEqual(s_5, s_50)

    def test_zero_collateral_no_crash(self):
        s = compute_capital_efficiency_score(
            current_ltv_pct=0.0, max_ltv_pct=80.0,
            safety_cushion_pct=85.0, liquidation_threshold_pct=85.0,
            net_carry_pct=0.0, oracle_deviation_tolerance_pct=5.0,
        )
        self.assertGreaterEqual(s, 0.0)


# ===========================================================================
# 5. efficiency_label
# ===========================================================================

class TestEfficiencyLabel(unittest.TestCase):
    def test_maximum_efficiency(self):
        self.assertEqual(efficiency_label(90.0), "MAXIMUM_EFFICIENCY")

    def test_maximum_efficiency_boundary(self):
        self.assertEqual(efficiency_label(85.0), "MAXIMUM_EFFICIENCY")

    def test_high_efficiency(self):
        self.assertEqual(efficiency_label(75.0), "HIGH_EFFICIENCY")

    def test_high_efficiency_boundary(self):
        self.assertEqual(efficiency_label(70.0), "HIGH_EFFICIENCY")

    def test_moderate_efficiency(self):
        self.assertEqual(efficiency_label(60.0), "MODERATE_EFFICIENCY")

    def test_moderate_efficiency_boundary(self):
        self.assertEqual(efficiency_label(50.0), "MODERATE_EFFICIENCY")

    def test_low_efficiency(self):
        self.assertEqual(efficiency_label(40.0), "LOW_EFFICIENCY")

    def test_low_efficiency_boundary(self):
        self.assertEqual(efficiency_label(30.0), "LOW_EFFICIENCY")

    def test_inefficient_collateral(self):
        self.assertEqual(efficiency_label(20.0), "INEFFICIENT_COLLATERAL")

    def test_inefficient_collateral_zero(self):
        self.assertEqual(efficiency_label(0.0), "INEFFICIENT_COLLATERAL")

    def test_just_below_high(self):
        self.assertEqual(efficiency_label(69.9), "MODERATE_EFFICIENCY")

    def test_just_below_maximum(self):
        self.assertEqual(efficiency_label(84.9), "HIGH_EFFICIENCY")

    def test_100_score(self):
        self.assertEqual(efficiency_label(100.0), "MAXIMUM_EFFICIENCY")

    def test_29_score(self):
        self.assertEqual(efficiency_label(29.0), "INEFFICIENT_COLLATERAL")

    def test_31_score(self):
        self.assertEqual(efficiency_label(31.0), "LOW_EFFICIENCY")


# ===========================================================================
# 6. DeFiProtocolCollateralEfficiencyRatioAnalyzer.analyze()
# ===========================================================================

class TestAnalyzerAnalyze(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolCollateralEfficiencyRatioAnalyzer(data_dir=Path(self.tmp))

    # --- output keys ---
    def test_result_has_current_ltv_pct(self):
        r = self.analyzer.analyze(_make_params())
        self.assertIn("current_ltv_pct", r)

    def test_result_has_safety_cushion_pct(self):
        r = self.analyzer.analyze(_make_params())
        self.assertIn("safety_cushion_pct", r)

    def test_result_has_capital_efficiency_score(self):
        r = self.analyzer.analyze(_make_params())
        self.assertIn("capital_efficiency_score", r)

    def test_result_has_net_carry_pct(self):
        r = self.analyzer.analyze(_make_params())
        self.assertIn("net_carry_pct", r)

    def test_result_has_efficiency_label(self):
        r = self.analyzer.analyze(_make_params())
        self.assertIn("efficiency_label", r)

    def test_result_has_schema_version(self):
        r = self.analyzer.analyze(_make_params())
        self.assertEqual(r["schema_version"], 1)

    def test_result_has_mp_tag(self):
        r = self.analyzer.analyze(_make_params())
        self.assertEqual(r["mp_tag"], "MP-1058")

    def test_result_has_timestamp(self):
        r = self.analyzer.analyze(_make_params())
        self.assertIn("timestamp", r)

    def test_result_has_protocol_name(self):
        r = self.analyzer.analyze(_make_params())
        self.assertEqual(r["protocol_name"], "Aave V3")

    def test_result_has_collateral_asset(self):
        r = self.analyzer.analyze(_make_params())
        self.assertEqual(r["collateral_asset"], "wstETH")

    # --- value correctness ---
    def test_current_ltv_value(self):
        r = self.analyzer.analyze(_make_params(
            collateral_value_usd=100_000, borrowed_value_usd=70_000
        ))
        self.assertAlmostEqual(r["current_ltv_pct"], 70.0, places=3)

    def test_safety_cushion_value(self):
        r = self.analyzer.analyze(_make_params(
            collateral_value_usd=100_000, borrowed_value_usd=70_000,
            liquidation_threshold_pct=85.0,
        ))
        self.assertAlmostEqual(r["safety_cushion_pct"], 15.0, places=3)

    def test_net_carry_value(self):
        r = self.analyzer.analyze(_make_params(
            current_apy_on_collateral_pct=5.0, borrow_rate_pct=3.0
        ))
        self.assertAlmostEqual(r["net_carry_pct"], 2.0, places=3)

    def test_efficiency_score_in_range(self):
        r = self.analyzer.analyze(_make_params())
        self.assertGreaterEqual(r["capital_efficiency_score"], 0.0)
        self.assertLessEqual(r["capital_efficiency_score"], 100.0)

    def test_label_is_valid(self):
        valid = {"MAXIMUM_EFFICIENCY", "HIGH_EFFICIENCY", "MODERATE_EFFICIENCY",
                 "LOW_EFFICIENCY", "INEFFICIENT_COLLATERAL"}
        r = self.analyzer.analyze(_make_params())
        self.assertIn(r["efficiency_label"], valid)

    def test_zero_collateral_no_crash(self):
        r = self.analyzer.analyze(_make_params(collateral_value_usd=0.0, borrowed_value_usd=0.0))
        self.assertEqual(r["current_ltv_pct"], 0.0)

    def test_negative_carry_propagates(self):
        r = self.analyzer.analyze(_make_params(
            current_apy_on_collateral_pct=1.0, borrow_rate_pct=8.0
        ))
        self.assertLess(r["net_carry_pct"], 0.0)

    def test_high_ltv_near_threshold_gives_low_cushion(self):
        r = self.analyzer.analyze(_make_params(
            collateral_value_usd=100_000, borrowed_value_usd=84_000,
            liquidation_threshold_pct=85.0,
        ))
        self.assertLess(r["safety_cushion_pct"], 2.0)

    def test_result_does_not_save_to_disk(self):
        """analyze() should NOT write any file."""
        log_path = Path(self.tmp) / "collateral_efficiency_ratio_log.json"
        self.analyzer.analyze(_make_params())
        self.assertFalse(log_path.exists())

    def test_source_field(self):
        r = self.analyzer.analyze(_make_params())
        self.assertEqual(r["source"], "defi_protocol_collateral_efficiency_ratio_analyzer")

    # --- validation errors ---
    def test_missing_protocol_name_raises(self):
        params = _make_params()
        del params["protocol_name"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_collateral_value_raises(self):
        params = _make_params()
        del params["collateral_value_usd"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_borrowed_value_raises(self):
        params = _make_params()
        del params["borrowed_value_usd"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_max_ltv_raises(self):
        params = _make_params()
        del params["max_ltv_pct"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_liquidation_threshold_raises(self):
        params = _make_params()
        del params["liquidation_threshold_pct"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_apy_raises(self):
        params = _make_params()
        del params["current_apy_on_collateral_pct"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_borrow_rate_raises(self):
        params = _make_params()
        del params["borrow_rate_pct"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_missing_oracle_tolerance_raises(self):
        params = _make_params()
        del params["oracle_deviation_tolerance_pct"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_string_numbers_coerced(self):
        r = self.analyzer.analyze(_make_params(
            collateral_value_usd="100000", borrowed_value_usd="70000"
        ))
        self.assertAlmostEqual(r["current_ltv_pct"], 70.0, places=3)


# ===========================================================================
# 7. DeFiProtocolCollateralEfficiencyRatioAnalyzer.analyze_and_save()
# ===========================================================================

class TestAnalyzerAnalyzeAndSave(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolCollateralEfficiencyRatioAnalyzer(data_dir=Path(self.tmp))
        self.log_path = Path(self.tmp) / "collateral_efficiency_ratio_log.json"

    def test_file_created(self):
        self.analyzer.analyze_and_save(_make_params())
        self.assertTrue(self.log_path.exists())

    def test_file_is_valid_json(self):
        self.analyzer.analyze_and_save(_make_params())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_file_has_one_entry_after_one_call(self):
        self.analyzer.analyze_and_save(_make_params())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_file_accumulates_entries(self):
        for _ in range(5):
            self.analyzer.analyze_and_save(_make_params())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 5)

    def test_result_has_saved_to_key(self):
        r = self.analyzer.analyze_and_save(_make_params())
        self.assertIn("saved_to", r)

    def test_saved_to_points_to_log(self):
        r = self.analyzer.analyze_and_save(_make_params())
        self.assertIn("collateral_efficiency_ratio_log.json", r["saved_to"])

    def test_ring_buffer_caps_at_100(self):
        for _ in range(RING_BUFFER_CAP + 10):
            self.analyzer.analyze_and_save(_make_params())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), RING_BUFFER_CAP)

    def test_oldest_entries_dropped_in_ring_buffer(self):
        for i in range(RING_BUFFER_CAP + 5):
            self.analyzer.analyze_and_save(_make_params(protocol_name=f"Proto-{i}"))
        with open(self.log_path) as fh:
            data = json.load(fh)
        # The first entry should NOT be Proto-0
        self.assertNotEqual(data[0]["protocol_name"], "Proto-0")

    def test_entry_contains_efficiency_label(self):
        self.analyzer.analyze_and_save(_make_params())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIn("efficiency_label", data[0])

    def test_entry_contains_current_ltv_pct(self):
        self.analyzer.analyze_and_save(_make_params())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIn("current_ltv_pct", data[0])

    def test_different_protocols_saved(self):
        for proto in ["Aave", "Compound", "Morpho"]:
            self.analyzer.analyze_and_save(_make_params(protocol_name=proto))
        with open(self.log_path) as fh:
            data = json.load(fh)
        names = [e["protocol_name"] for e in data]
        self.assertIn("Aave", names)
        self.assertIn("Morpho", names)


# ===========================================================================
# 8. _load_json_list / _atomic_write_json
# ===========================================================================

class TestJsonHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_load_missing_file_returns_empty(self):
        p = Path(self.tmp) / "nonexistent.json"
        self.assertEqual(_load_json_list(p), [])

    def test_load_invalid_json_returns_empty(self):
        p = Path(self.tmp) / "bad.json"
        p.write_text("not-json")
        self.assertEqual(_load_json_list(p), [])

    def test_load_valid_list(self):
        p = Path(self.tmp) / "good.json"
        p.write_text(json.dumps([{"a": 1}, {"b": 2}]))
        result = _load_json_list(p)
        self.assertEqual(len(result), 2)

    def test_load_non_list_returns_empty(self):
        p = Path(self.tmp) / "obj.json"
        p.write_text(json.dumps({"key": "val"}))
        self.assertEqual(_load_json_list(p), [])

    def test_atomic_write_creates_file(self):
        p = Path(self.tmp) / "out.json"
        _atomic_write_json(p, [{"x": 1}])
        self.assertTrue(p.exists())

    def test_atomic_write_content_correct(self):
        p = Path(self.tmp) / "out.json"
        data = [{"hello": "world", "n": 42}]
        _atomic_write_json(p, data)
        with open(p) as fh:
            loaded = json.load(fh)
        self.assertEqual(loaded, data)

    def test_atomic_write_creates_parent_dir(self):
        p = Path(self.tmp) / "subdir" / "deep" / "out.json"
        _atomic_write_json(p, [])
        self.assertTrue(p.exists())

    def test_load_then_write_round_trip(self):
        p = Path(self.tmp) / "rt.json"
        original = [{"k": 1}, {"k": 2}]
        _atomic_write_json(p, original)
        loaded = _load_json_list(p)
        self.assertEqual(loaded, original)


# ===========================================================================
# 9. Edge / boundary / integration scenarios
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolCollateralEfficiencyRatioAnalyzer(data_dir=Path(self.tmp))

    def test_very_high_collateral_low_borrow(self):
        r = self.analyzer.analyze(_make_params(
            collateral_value_usd=10_000_000, borrowed_value_usd=1_000
        ))
        self.assertLess(r["current_ltv_pct"], 1.0)
        self.assertAlmostEqual(r["safety_cushion_pct"], 85.0 - r["current_ltv_pct"], places=4)

    def test_label_consistency_with_score(self):
        r = self.analyzer.analyze(_make_params())
        score = r["capital_efficiency_score"]
        label = r["efficiency_label"]
        # Re-derive label and compare
        self.assertEqual(label, efficiency_label(score))

    def test_ltv_above_liquidation_negative_cushion(self):
        r = self.analyzer.analyze(_make_params(
            collateral_value_usd=100_000, borrowed_value_usd=90_000,
            liquidation_threshold_pct=85.0,
        ))
        self.assertLess(r["safety_cushion_pct"], 0.0)

    def test_maximum_oracle_tolerance_caps_oracle_score(self):
        r_max = self.analyzer.analyze(_make_params(oracle_deviation_tolerance_pct=100.0))
        r_ten = self.analyzer.analyze(_make_params(oracle_deviation_tolerance_pct=10.0))
        self.assertAlmostEqual(
            r_max["capital_efficiency_score"],
            r_ten["capital_efficiency_score"],
            places=3,
        )

    def test_morpho_protocol_name(self):
        r = self.analyzer.analyze(_make_params(protocol_name="Morpho Steakhouse"))
        self.assertEqual(r["protocol_name"], "Morpho Steakhouse")

    def test_compound_v3_scenario(self):
        r = self.analyzer.analyze({
            "protocol_name": "Compound V3",
            "collateral_asset": "USDC",
            "collateral_value_usd": 500_000.0,
            "borrowed_value_usd": 350_000.0,
            "max_ltv_pct": 75.0,
            "liquidation_threshold_pct": 80.0,
            "current_apy_on_collateral_pct": 4.8,
            "borrow_rate_pct": 4.0,
            "oracle_deviation_tolerance_pct": 3.0,
        })
        self.assertAlmostEqual(r["current_ltv_pct"], 70.0, places=3)
        self.assertAlmostEqual(r["safety_cushion_pct"], 10.0, places=3)

    def test_over_leveraged_scenario(self):
        r = self.analyzer.analyze(_make_params(
            collateral_value_usd=100_000,
            borrowed_value_usd=95_000,
            liquidation_threshold_pct=85.0,
        ))
        self.assertGreater(r["current_ltv_pct"], 85.0)
        self.assertLess(r["safety_cushion_pct"], 0.0)

    def test_zero_borrow_gives_full_cushion(self):
        r = self.analyzer.analyze(_make_params(
            borrowed_value_usd=0.0, liquidation_threshold_pct=85.0
        ))
        self.assertAlmostEqual(r["current_ltv_pct"], 0.0)
        self.assertAlmostEqual(r["safety_cushion_pct"], 85.0)

    def test_efficiency_label_in_valid_set(self):
        valid = {"MAXIMUM_EFFICIENCY", "HIGH_EFFICIENCY", "MODERATE_EFFICIENCY",
                 "LOW_EFFICIENCY", "INEFFICIENT_COLLATERAL"}
        for ltv in [10, 30, 50, 70, 90]:
            r = self.analyzer.analyze(_make_params(
                collateral_value_usd=100_000, borrowed_value_usd=ltv * 1000
            ))
            self.assertIn(r["efficiency_label"], valid)

    def test_multiple_analyze_calls_independent(self):
        r1 = self.analyzer.analyze(_make_params(borrowed_value_usd=60_000))
        r2 = self.analyzer.analyze(_make_params(borrowed_value_usd=80_000))
        self.assertAlmostEqual(r1["current_ltv_pct"], 60.0, places=3)
        self.assertAlmostEqual(r2["current_ltv_pct"], 80.0, places=3)

    def test_data_dir_nonexistent_created_on_save(self):
        new_dir = Path(self.tmp) / "new" / "subdir"
        analyzer = DeFiProtocolCollateralEfficiencyRatioAnalyzer(data_dir=new_dir)
        analyzer.analyze_and_save(_make_params())
        self.assertTrue((new_dir / "collateral_efficiency_ratio_log.json").exists())

    def test_very_high_apy_score_capped(self):
        r = self.analyzer.analyze(_make_params(
            current_apy_on_collateral_pct=99.0, borrow_rate_pct=0.0
        ))
        self.assertLessEqual(r["capital_efficiency_score"], 100.0)

    def test_very_high_negative_carry_score_floored(self):
        r = self.analyzer.analyze(_make_params(
            current_apy_on_collateral_pct=0.0, borrow_rate_pct=99.0
        ))
        self.assertGreaterEqual(r["capital_efficiency_score"], 0.0)

    def test_collateral_asset_stored_correctly(self):
        r = self.analyzer.analyze(_make_params(collateral_asset="rETH"))
        self.assertEqual(r["collateral_asset"], "rETH")

    def test_all_required_outputs_present(self):
        r = self.analyzer.analyze(_make_params())
        required_outputs = [
            "current_ltv_pct", "safety_cushion_pct",
            "capital_efficiency_score", "net_carry_pct", "efficiency_label",
        ]
        for key in required_outputs:
            self.assertIn(key, r)


if __name__ == "__main__":
    unittest.main()
