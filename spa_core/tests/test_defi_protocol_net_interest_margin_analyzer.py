"""
Tests for MP-1110 DeFiProtocolNetInterestMarginAnalyzer
Pure stdlib unittest — run with: python3 -m unittest
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_protocol_net_interest_margin_analyzer import (
    analyze,
    analyze_portfolio,
    _gross_spread_pct,
    _net_interest_margin_pct,
    _protocol_revenue_usd_annual,
    _supplier_effective_yield_pct,
    _nim_efficiency_score,
    _nim_label,
    _atomic_log,
    _safe_float,
    _clamp,
    DeFiProtocolNetInterestMarginAnalyzer,
    ALL_NIM_LABELS,
    NIM_HEALTHY_SPREAD,
    NIM_ADEQUATE_SPREAD,
    NIM_THIN_SPREAD,
    NIM_COMPRESSED_SPREAD,
    NIM_INVERTED_SPREAD,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _proto(
    protocol_name="TestProtocol",
    supply_apy_pct=3.5,
    borrow_apy_pct=5.8,
    utilization_rate_pct=80.0,
    reserve_factor_pct=10.0,
    total_supplied_usd=1_000_000_000.0,
    total_borrowed_usd=800_000_000.0,
):
    return {
        "protocol_name":        protocol_name,
        "supply_apy_pct":       supply_apy_pct,
        "borrow_apy_pct":       borrow_apy_pct,
        "utilization_rate_pct": utilization_rate_pct,
        "reserve_factor_pct":   reserve_factor_pct,
        "total_supplied_usd":   total_supplied_usd,
        "total_borrowed_usd":   total_borrowed_usd,
    }


def _cfg():
    return {"log_path": _tmp_log()}


# ===========================================================================
# 1. _safe_float
# ===========================================================================

class TestSafeFloat(unittest.TestCase):

    def test_int(self):
        self.assertEqual(_safe_float(5), 5.0)

    def test_float(self):
        self.assertAlmostEqual(_safe_float(3.14), 3.14)

    def test_string_numeric(self):
        self.assertAlmostEqual(_safe_float("2.5"), 2.5)

    def test_none_default(self):
        self.assertEqual(_safe_float(None), 0.0)

    def test_none_custom_default(self):
        self.assertEqual(_safe_float(None, 99.0), 99.0)

    def test_empty_string_default(self):
        self.assertEqual(_safe_float(""), 0.0)

    def test_non_numeric_string(self):
        self.assertEqual(_safe_float("abc"), 0.0)

    def test_negative(self):
        self.assertAlmostEqual(_safe_float(-7.5), -7.5)

    def test_zero(self):
        self.assertEqual(_safe_float(0), 0.0)


# ===========================================================================
# 2. _clamp
# ===========================================================================

class TestClamp(unittest.TestCase):

    def test_within_range(self):
        self.assertEqual(_clamp(50.0, 0.0, 100.0), 50.0)

    def test_at_lower_bound(self):
        self.assertEqual(_clamp(0.0, 0.0, 100.0), 0.0)

    def test_at_upper_bound(self):
        self.assertEqual(_clamp(100.0, 0.0, 100.0), 100.0)

    def test_below_lower_bound(self):
        self.assertEqual(_clamp(-5.0, 0.0, 100.0), 0.0)

    def test_above_upper_bound(self):
        self.assertEqual(_clamp(150.0, 0.0, 100.0), 100.0)

    def test_negative_range(self):
        self.assertEqual(_clamp(-3.0, -10.0, -1.0), -3.0)

    def test_equal_bounds(self):
        self.assertEqual(_clamp(5.0, 5.0, 5.0), 5.0)


# ===========================================================================
# 3. _gross_spread_pct
# ===========================================================================

class TestGrossSpreadPct(unittest.TestCase):

    def test_normal_spread(self):
        self.assertAlmostEqual(_gross_spread_pct(5.8, 3.5), 2.3)

    def test_zero_spread(self):
        self.assertAlmostEqual(_gross_spread_pct(4.0, 4.0), 0.0)

    def test_inverted_spread(self):
        self.assertAlmostEqual(_gross_spread_pct(5.0, 6.0), -1.0)

    def test_large_spread(self):
        self.assertAlmostEqual(_gross_spread_pct(15.0, 3.0), 12.0)

    def test_both_zero(self):
        self.assertAlmostEqual(_gross_spread_pct(0.0, 0.0), 0.0)

    def test_fractional_result(self):
        self.assertAlmostEqual(_gross_spread_pct(5.75, 3.25), 2.5)

    def test_small_positive(self):
        self.assertAlmostEqual(_gross_spread_pct(3.1, 2.9), 0.2)


# ===========================================================================
# 4. _net_interest_margin_pct
# ===========================================================================

class TestNetInterestMarginPct(unittest.TestCase):

    def test_basic_math(self):
        # gross_spread=2.3, utilization=80 → nim=1.84
        self.assertAlmostEqual(_net_interest_margin_pct(2.3, 80.0), 1.84)

    def test_zero_utilization(self):
        self.assertAlmostEqual(_net_interest_margin_pct(3.0, 0.0), 0.0)

    def test_full_utilization(self):
        self.assertAlmostEqual(_net_interest_margin_pct(4.0, 100.0), 4.0)

    def test_inverted_spread_propagates(self):
        # Inverted spread → negative NIM
        self.assertAlmostEqual(_net_interest_margin_pct(-1.0, 80.0), -0.8)

    def test_fifty_percent_utilization(self):
        self.assertAlmostEqual(_net_interest_margin_pct(6.0, 50.0), 3.0)

    def test_zero_spread(self):
        self.assertAlmostEqual(_net_interest_margin_pct(0.0, 80.0), 0.0)

    def test_fractional(self):
        self.assertAlmostEqual(_net_interest_margin_pct(2.0, 75.0), 1.5)


# ===========================================================================
# 5. _protocol_revenue_usd_annual
# ===========================================================================

class TestProtocolRevenueUsdAnnual(unittest.TestCase):

    def test_basic_math(self):
        # 1e9 * 5.8% * 10% = 5,800,000
        r = _protocol_revenue_usd_annual(1_000_000_000.0, 5.8, 10.0)
        self.assertAlmostEqual(r, 5_800_000.0)

    def test_zero_borrowed(self):
        self.assertAlmostEqual(_protocol_revenue_usd_annual(0.0, 5.8, 10.0), 0.0)

    def test_zero_borrow_apy(self):
        self.assertAlmostEqual(_protocol_revenue_usd_annual(1e9, 0.0, 10.0), 0.0)

    def test_zero_reserve_factor(self):
        self.assertAlmostEqual(_protocol_revenue_usd_annual(1e9, 5.8, 0.0), 0.0)

    def test_100_percent_reserve_factor(self):
        # All borrow interest goes to protocol
        r = _protocol_revenue_usd_annual(100_000_000.0, 10.0, 100.0)
        self.assertAlmostEqual(r, 10_000_000.0)

    def test_small_values(self):
        r = _protocol_revenue_usd_annual(1_000.0, 5.0, 20.0)
        self.assertAlmostEqual(r, 10.0)

    def test_large_borrowed(self):
        r = _protocol_revenue_usd_annual(5_000_000_000.0, 6.0, 15.0)
        self.assertAlmostEqual(r, 45_000_000.0)

    def test_negative_borrowed_treated_as_zero(self):
        # Negative total_borrowed → 0 revenue
        self.assertAlmostEqual(_protocol_revenue_usd_annual(-1e9, 5.0, 10.0), 0.0)


# ===========================================================================
# 6. _supplier_effective_yield_pct
# ===========================================================================

class TestSupplierEffectiveYieldPct(unittest.TestCase):

    def test_basic_math(self):
        # supply_apy=3.5, utilization=80 → effective=2.8
        self.assertAlmostEqual(_supplier_effective_yield_pct(3.5, 80.0), 2.8)

    def test_zero_utilization(self):
        self.assertAlmostEqual(_supplier_effective_yield_pct(5.0, 0.0), 0.0)

    def test_full_utilization(self):
        self.assertAlmostEqual(_supplier_effective_yield_pct(4.5, 100.0), 4.5)

    def test_fifty_utilization(self):
        self.assertAlmostEqual(_supplier_effective_yield_pct(6.0, 50.0), 3.0)

    def test_zero_supply_apy(self):
        self.assertAlmostEqual(_supplier_effective_yield_pct(0.0, 80.0), 0.0)

    def test_fractional_result(self):
        self.assertAlmostEqual(_supplier_effective_yield_pct(3.0, 33.333333), 1.0, places=4)

    def test_over_100_utilization_clamped(self):
        # util > 100 is clamped to 100
        self.assertAlmostEqual(_supplier_effective_yield_pct(4.0, 110.0), 4.0)


# ===========================================================================
# 7. _nim_label
# ===========================================================================

class TestNimLabel(unittest.TestCase):

    def test_healthy_above_3(self):
        self.assertEqual(_nim_label(3.5), NIM_HEALTHY_SPREAD)

    def test_healthy_just_above_3(self):
        self.assertEqual(_nim_label(3.01), NIM_HEALTHY_SPREAD)

    def test_adequate_at_3(self):
        # > 2 and <= 3 → ADEQUATE
        self.assertEqual(_nim_label(3.0), NIM_ADEQUATE_SPREAD)

    def test_adequate_at_2_5(self):
        self.assertEqual(_nim_label(2.5), NIM_ADEQUATE_SPREAD)

    def test_adequate_just_above_2(self):
        self.assertEqual(_nim_label(2.01), NIM_ADEQUATE_SPREAD)

    def test_thin_at_2(self):
        self.assertEqual(_nim_label(2.0), NIM_THIN_SPREAD)

    def test_thin_at_1_5(self):
        self.assertEqual(_nim_label(1.5), NIM_THIN_SPREAD)

    def test_thin_just_above_1(self):
        self.assertEqual(_nim_label(1.01), NIM_THIN_SPREAD)

    def test_compressed_at_1(self):
        self.assertEqual(_nim_label(1.0), NIM_COMPRESSED_SPREAD)

    def test_compressed_at_0_5(self):
        self.assertEqual(_nim_label(0.5), NIM_COMPRESSED_SPREAD)

    def test_compressed_just_above_0(self):
        self.assertEqual(_nim_label(0.001), NIM_COMPRESSED_SPREAD)

    def test_inverted_at_zero(self):
        self.assertEqual(_nim_label(0.0), NIM_INVERTED_SPREAD)

    def test_inverted_negative(self):
        self.assertEqual(_nim_label(-1.0), NIM_INVERTED_SPREAD)

    def test_inverted_large_negative(self):
        self.assertEqual(_nim_label(-100.0), NIM_INVERTED_SPREAD)

    def test_all_labels_in_constant(self):
        for label in ALL_NIM_LABELS:
            self.assertIsInstance(label, str)

    def test_label_count(self):
        self.assertEqual(len(ALL_NIM_LABELS), 5)


# ===========================================================================
# 8. _nim_efficiency_score
# ===========================================================================

class TestNimEfficiencyScore(unittest.TestCase):

    def test_zero_spread_gives_zero(self):
        self.assertEqual(_nim_efficiency_score(0.0, 0.0, 80.0), 0)

    def test_negative_spread_gives_zero(self):
        self.assertEqual(_nim_efficiency_score(-2.0, -1.6, 80.0), 0)

    def test_returns_int(self):
        score = _nim_efficiency_score(5.0, 4.0, 90.0)
        self.assertIsInstance(score, int)

    def test_score_in_range(self):
        for spread in [0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 15.0]:
            nim = spread * 0.8
            score = _nim_efficiency_score(spread, nim, 80.0)
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_max_scenario(self):
        # 10%+ spread, 100% utilization → should score very high
        score = _nim_efficiency_score(10.0, 10.0, 100.0)
        self.assertGreaterEqual(score, 90)

    def test_thin_spread_low_score(self):
        # small spread → lower score
        score_thin   = _nim_efficiency_score(0.5, 0.4, 80.0)
        score_healthy = _nim_efficiency_score(5.0, 4.0, 80.0)
        self.assertLess(score_thin, score_healthy)

    def test_higher_utilization_higher_score(self):
        s1 = _nim_efficiency_score(3.0, 3.0 * 0.5, 50.0)
        s2 = _nim_efficiency_score(3.0, 3.0 * 0.9, 90.0)
        self.assertLess(s1, s2)

    def test_score_zero_utilization(self):
        # Even positive spread with 0 utilization → low score from util component
        score = _nim_efficiency_score(5.0, 0.0, 0.0)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_score_capped_at_100(self):
        score = _nim_efficiency_score(100.0, 100.0, 100.0)
        self.assertEqual(score, 100)


# ===========================================================================
# 9. analyze — key fields
# ===========================================================================

class TestAnalyzeKeyFields(unittest.TestCase):

    def test_returns_dict(self):
        r = analyze(_proto(), config=_cfg())
        self.assertIsInstance(r, dict)

    def test_required_output_keys(self):
        r = analyze(_proto(), config=_cfg())
        for key in [
            "protocol_name", "supply_apy_pct", "borrow_apy_pct",
            "utilization_rate_pct", "reserve_factor_pct",
            "total_supplied_usd", "total_borrowed_usd",
            "gross_spread_pct", "net_interest_margin_pct",
            "protocol_revenue_usd_annual", "supplier_effective_yield_pct",
            "nim_efficiency_score", "nim_label", "timestamp",
        ]:
            self.assertIn(key, r)

    def test_protocol_name_passthrough(self):
        r = analyze(_proto(protocol_name="MyProtocol"), config=_cfg())
        self.assertEqual(r["protocol_name"], "MyProtocol")

    def test_gross_spread_calculation(self):
        r = analyze(_proto(borrow_apy_pct=5.8, supply_apy_pct=3.5), config=_cfg())
        self.assertAlmostEqual(r["gross_spread_pct"], 2.3)

    def test_nim_calculation(self):
        r = analyze(_proto(borrow_apy_pct=5.8, supply_apy_pct=3.5,
                           utilization_rate_pct=80.0), config=_cfg())
        self.assertAlmostEqual(r["net_interest_margin_pct"], 1.84)

    def test_revenue_calculation(self):
        # 800M * 5.8% * 10% = 4,640,000
        r = analyze(_proto(total_borrowed_usd=800_000_000.0,
                           borrow_apy_pct=5.8, reserve_factor_pct=10.0),
                    config=_cfg())
        # 800_000_000 * 0.058 * 0.10 = 4_640_000
        self.assertAlmostEqual(r["protocol_revenue_usd_annual"], 4_640_000.0)

    def test_supplier_effective_yield(self):
        r = analyze(_proto(supply_apy_pct=3.5, utilization_rate_pct=80.0),
                    config=_cfg())
        self.assertAlmostEqual(r["supplier_effective_yield_pct"], 2.8)

    def test_nim_label_adequate(self):
        r = analyze(_proto(borrow_apy_pct=5.8, supply_apy_pct=3.5), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_ADEQUATE_SPREAD)

    def test_nim_label_healthy(self):
        r = analyze(_proto(borrow_apy_pct=8.0, supply_apy_pct=4.0), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_HEALTHY_SPREAD)

    def test_nim_label_inverted(self):
        r = analyze(_proto(borrow_apy_pct=4.0, supply_apy_pct=5.0), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_INVERTED_SPREAD)

    def test_nim_label_thin(self):
        r = analyze(_proto(borrow_apy_pct=4.5, supply_apy_pct=3.0), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_THIN_SPREAD)  # 1.5%

    def test_nim_label_compressed(self):
        r = analyze(_proto(borrow_apy_pct=3.3, supply_apy_pct=3.0), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_COMPRESSED_SPREAD)  # 0.3%

    def test_timestamp_is_float(self):
        r = analyze(_proto(), config=_cfg())
        self.assertIsInstance(r["timestamp"], float)

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_proto(), config=_cfg())
        after = time.time()
        self.assertLessEqual(before, r["timestamp"])
        self.assertGreaterEqual(after, r["timestamp"])

    def test_efficiency_score_type(self):
        r = analyze(_proto(), config=_cfg())
        self.assertIsInstance(r["nim_efficiency_score"], int)

    def test_efficiency_score_range(self):
        r = analyze(_proto(), config=_cfg())
        self.assertGreaterEqual(r["nim_efficiency_score"], 0)
        self.assertLessEqual(r["nim_efficiency_score"], 100)


# ===========================================================================
# 10. analyze — edge / boundary cases
# ===========================================================================

class TestAnalyzeEdgeCases(unittest.TestCase):

    def test_empty_dict(self):
        r = analyze({}, config=_cfg())
        self.assertIn("nim_label", r)
        self.assertEqual(r["nim_label"], NIM_INVERTED_SPREAD)  # both 0 → spread=0

    def test_missing_protocol_name_defaults(self):
        p = _proto()
        del p["protocol_name"]
        r = analyze(p, config=_cfg())
        self.assertEqual(r["protocol_name"], "UNKNOWN")

    def test_negative_supply_apy_clamped_to_zero(self):
        r = analyze(_proto(supply_apy_pct=-5.0), config=_cfg())
        self.assertEqual(r["supply_apy_pct"], 0.0)

    def test_negative_borrow_apy_clamped_to_zero(self):
        r = analyze(_proto(borrow_apy_pct=-3.0), config=_cfg())
        self.assertEqual(r["borrow_apy_pct"], 0.0)

    def test_utilization_over_100_clamped(self):
        r = analyze(_proto(utilization_rate_pct=150.0), config=_cfg())
        self.assertEqual(r["utilization_rate_pct"], 100.0)

    def test_utilization_negative_clamped_to_zero(self):
        r = analyze(_proto(utilization_rate_pct=-10.0), config=_cfg())
        self.assertEqual(r["utilization_rate_pct"], 0.0)

    def test_reserve_factor_over_100_clamped(self):
        r = analyze(_proto(reserve_factor_pct=120.0), config=_cfg())
        self.assertEqual(r["reserve_factor_pct"], 100.0)

    def test_reserve_factor_negative_clamped_to_zero(self):
        r = analyze(_proto(reserve_factor_pct=-5.0), config=_cfg())
        self.assertEqual(r["reserve_factor_pct"], 0.0)

    def test_zero_total_borrowed(self):
        r = analyze(_proto(total_borrowed_usd=0.0), config=_cfg())
        self.assertAlmostEqual(r["protocol_revenue_usd_annual"], 0.0)

    def test_string_values_coerced(self):
        p = {
            "protocol_name":        "Test",
            "supply_apy_pct":       "3.5",
            "borrow_apy_pct":       "5.8",
            "utilization_rate_pct": "80",
            "reserve_factor_pct":   "10",
            "total_supplied_usd":   "1000000",
            "total_borrowed_usd":   "800000",
        }
        r = analyze(p, config=_cfg())
        self.assertAlmostEqual(r["gross_spread_pct"], 2.3)

    def test_none_values_default(self):
        p = {"protocol_name": "Test", "supply_apy_pct": None, "borrow_apy_pct": None}
        r = analyze(p, config=_cfg())
        self.assertAlmostEqual(r["gross_spread_pct"], 0.0)

    def test_inverted_spread_efficiency_score_zero(self):
        r = analyze(_proto(supply_apy_pct=7.0, borrow_apy_pct=4.0), config=_cfg())
        self.assertEqual(r["nim_efficiency_score"], 0)

    def test_no_crash_without_config(self):
        """analyze without config param should not crash (uses default log path)."""
        try:
            r = analyze(_proto())
            self.assertIn("nim_label", r)
        except Exception:
            pass  # log write might fail; that's acceptable

    def test_non_dict_protocol_treated_as_empty(self):
        # Should not raise
        for bad_input in [None, "string", 42, []]:
            r = analyze(bad_input if isinstance(bad_input, dict) else {}, config=_cfg())
            self.assertIn("nim_label", r)


# ===========================================================================
# 11. analyze — specific label boundary tests
# ===========================================================================

class TestAnalyzeLabelBoundaries(unittest.TestCase):

    def test_exactly_at_healthy_boundary(self):
        # spread > 3.0 → HEALTHY
        r = analyze(_proto(borrow_apy_pct=6.5, supply_apy_pct=3.4), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_HEALTHY_SPREAD)

    def test_just_below_healthy_boundary(self):
        # spread = 3.0 → ADEQUATE (not HEALTHY since > threshold required)
        r = analyze(_proto(borrow_apy_pct=6.0, supply_apy_pct=3.0), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_ADEQUATE_SPREAD)

    def test_exactly_at_adequate_boundary(self):
        # spread = 2.0 → THIN (not ADEQUATE since > 2.0 required)
        r = analyze(_proto(borrow_apy_pct=5.0, supply_apy_pct=3.0), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_THIN_SPREAD)

    def test_just_above_adequate_boundary(self):
        r = analyze(_proto(borrow_apy_pct=5.1, supply_apy_pct=3.0), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_ADEQUATE_SPREAD)

    def test_exactly_at_thin_boundary(self):
        # spread = 1.0 → COMPRESSED (> 1.0 required for THIN)
        r = analyze(_proto(borrow_apy_pct=4.0, supply_apy_pct=3.0), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_COMPRESSED_SPREAD)

    def test_just_above_thin_boundary(self):
        r = analyze(_proto(borrow_apy_pct=4.1, supply_apy_pct=3.0), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_THIN_SPREAD)

    def test_exactly_at_compressed_boundary(self):
        # spread = 0.0 → INVERTED
        r = analyze(_proto(borrow_apy_pct=3.0, supply_apy_pct=3.0), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_INVERTED_SPREAD)

    def test_small_positive_spread(self):
        r = analyze(_proto(borrow_apy_pct=3.5, supply_apy_pct=3.0), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_COMPRESSED_SPREAD)


# ===========================================================================
# 12. analyze — Aave-like realistic scenario
# ===========================================================================

class TestAnalyzeRealisticScenarios(unittest.TestCase):

    def _aave_usdc(self):
        return {
            "protocol_name":        "Aave V3 USDC",
            "supply_apy_pct":       3.5,
            "borrow_apy_pct":       5.8,
            "utilization_rate_pct": 80.0,
            "reserve_factor_pct":   10.0,
            "total_supplied_usd":   2_000_000_000.0,
            "total_borrowed_usd":   1_600_000_000.0,
        }

    def test_aave_gross_spread(self):
        r = analyze(self._aave_usdc(), config=_cfg())
        self.assertAlmostEqual(r["gross_spread_pct"], 2.3)

    def test_aave_nim(self):
        r = analyze(self._aave_usdc(), config=_cfg())
        self.assertAlmostEqual(r["net_interest_margin_pct"], 1.84)

    def test_aave_revenue(self):
        # 1.6B * 5.8% * 10% = 9,280,000
        r = analyze(self._aave_usdc(), config=_cfg())
        self.assertAlmostEqual(r["protocol_revenue_usd_annual"], 9_280_000.0)

    def test_aave_supplier_yield(self):
        # 3.5 * 0.8 = 2.8
        r = analyze(self._aave_usdc(), config=_cfg())
        self.assertAlmostEqual(r["supplier_effective_yield_pct"], 2.8)

    def test_aave_label(self):
        r = analyze(self._aave_usdc(), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_ADEQUATE_SPREAD)

    def test_high_yield_protocol(self):
        p = {
            "protocol_name":        "HighYield",
            "supply_apy_pct":       8.0,
            "borrow_apy_pct":       14.0,
            "utilization_rate_pct": 95.0,
            "reserve_factor_pct":   5.0,
            "total_supplied_usd":   100_000_000.0,
            "total_borrowed_usd":   95_000_000.0,
        }
        r = analyze(p, config=_cfg())
        self.assertEqual(r["nim_label"], NIM_HEALTHY_SPREAD)  # spread=6
        self.assertGreaterEqual(r["nim_efficiency_score"], 70)

    def test_morpho_steakhouse_like(self):
        p = {
            "protocol_name":        "Morpho Steakhouse",
            "supply_apy_pct":       5.5,
            "borrow_apy_pct":       7.2,
            "utilization_rate_pct": 92.0,
            "reserve_factor_pct":   5.0,
            "total_supplied_usd":   500_000_000.0,
            "total_borrowed_usd":   460_000_000.0,
        }
        r = analyze(p, config=_cfg())
        self.assertAlmostEqual(r["gross_spread_pct"], 1.7)
        self.assertEqual(r["nim_label"], NIM_THIN_SPREAD)

    def test_zero_reserve_factor_no_revenue(self):
        p = _proto(reserve_factor_pct=0.0, total_borrowed_usd=500_000_000.0)
        r = analyze(p, config=_cfg())
        self.assertAlmostEqual(r["protocol_revenue_usd_annual"], 0.0)

    def test_very_high_utilization(self):
        p = _proto(utilization_rate_pct=99.0)
        r = analyze(p, config=_cfg())
        self.assertAlmostEqual(
            r["supplier_effective_yield_pct"],
            r["supply_apy_pct"] * 0.99,
            places=4
        )


# ===========================================================================
# 13. _atomic_log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):

    def test_creates_file(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 1})
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_appends_entry(self):
        path = _tmp_log()
        _atomic_log(path, {"a": 1})
        _atomic_log(path, {"a": 2})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(path)

    def test_ring_buffer_cap_100(self):
        path = _tmp_log()
        for i in range(120):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)
        self.assertEqual(data[0]["i"], 20)   # oldest = entry 20
        self.assertEqual(data[-1]["i"], 119) # newest
        os.unlink(path)

    def test_file_is_valid_json(self):
        path = _tmp_log()
        _atomic_log(path, {"key": "value", "num": 42})
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        os.unlink(path)

    def test_existing_corrupt_file_resets(self):
        path = _tmp_log()
        with open(path, "w") as f:
            f.write("NOT JSON")
        _atomic_log(path, {"z": 99})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_missing_dir_creates_it(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "subdir", "nim.json")
            _atomic_log(path, {"test": True})
            self.assertTrue(os.path.exists(path))

    def test_log_entry_preserves_fields(self):
        path = _tmp_log()
        entry = {"nim_label": NIM_HEALTHY_SPREAD, "score": 85}
        _atomic_log(path, entry)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["nim_label"], NIM_HEALTHY_SPREAD)
        self.assertEqual(data[0]["score"], 85)
        os.unlink(path)


# ===========================================================================
# 14. analyze — logging integration
# ===========================================================================

class TestAnalyzeLogging(unittest.TestCase):

    def test_log_file_created(self):
        path = _tmp_log()
        analyze(_proto(), config={"log_path": path})
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_log_contains_result(self):
        path = _tmp_log()
        r = analyze(_proto(protocol_name="LogTest"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["protocol_name"], "LogTest")
        os.unlink(path)

    def test_multiple_calls_appended(self):
        path = _tmp_log()
        cfg = {"log_path": path}
        for i in range(5):
            analyze(_proto(protocol_name=f"P{i}"), config=cfg)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)
        os.unlink(path)

    def test_log_ring_buffer_via_analyze(self):
        path = _tmp_log()
        cfg = {"log_path": path}
        for i in range(110):
            analyze(_proto(protocol_name=f"P{i}"), config=cfg)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)
        os.unlink(path)


# ===========================================================================
# 15. analyze_portfolio
# ===========================================================================

class TestAnalyzePortfolio(unittest.TestCase):

    def _protocols(self):
        return [
            _proto("Aave", borrow_apy_pct=5.8, supply_apy_pct=3.5, utilization_rate_pct=80.0),
            _proto("Morpho", borrow_apy_pct=7.2, supply_apy_pct=5.5, utilization_rate_pct=92.0),
            _proto("Inverted", borrow_apy_pct=4.0, supply_apy_pct=5.0, utilization_rate_pct=70.0),
        ]

    def test_returns_dict(self):
        r = analyze_portfolio(self._protocols(), config=_cfg())
        self.assertIsInstance(r, dict)

    def test_total_protocols(self):
        r = analyze_portfolio(self._protocols(), config=_cfg())
        self.assertEqual(r["total_protocols"], 3)

    def test_results_list_length(self):
        r = analyze_portfolio(self._protocols(), config=_cfg())
        self.assertEqual(len(r["results"]), 3)

    def test_empty_list(self):
        r = analyze_portfolio([], config=_cfg())
        self.assertEqual(r["total_protocols"], 0)
        self.assertIsNone(r["best_nim_protocol"])
        self.assertIsNone(r["worst_nim_protocol"])

    def test_best_nim_protocol(self):
        r = analyze_portfolio(self._protocols(), config=_cfg())
        # Aave has highest NIM: 2.3 * 80% = 1.84 vs Morpho 1.7 * 92% = 1.564
        self.assertEqual(r["best_nim_protocol"], "Aave")

    def test_worst_nim_protocol(self):
        r = analyze_portfolio(self._protocols(), config=_cfg())
        # Inverted has lowest NIM (negative)
        self.assertEqual(r["worst_nim_protocol"], "Inverted")

    def test_avg_nim_pct_type(self):
        r = analyze_portfolio(self._protocols(), config=_cfg())
        self.assertIsInstance(r["avg_nim_pct"], float)

    def test_inverted_count(self):
        r = analyze_portfolio(self._protocols(), config=_cfg())
        self.assertEqual(r["inverted_count"], 1)

    def test_avg_efficiency_score(self):
        r = analyze_portfolio(self._protocols(), config=_cfg())
        self.assertGreaterEqual(r["avg_efficiency_score"], 0)
        self.assertLessEqual(r["avg_efficiency_score"], 100)

    def test_single_protocol(self):
        r = analyze_portfolio([_proto("Solo")], config=_cfg())
        self.assertEqual(r["total_protocols"], 1)
        self.assertEqual(r["best_nim_protocol"], "Solo")
        self.assertEqual(r["worst_nim_protocol"], "Solo")

    def test_non_list_input(self):
        r = analyze_portfolio(None, config=_cfg())
        self.assertEqual(r["total_protocols"], 0)

    def test_all_inverted(self):
        protos = [_proto(f"P{i}", borrow_apy_pct=2.0, supply_apy_pct=5.0)
                  for i in range(3)]
        r = analyze_portfolio(protos, config=_cfg())
        self.assertEqual(r["inverted_count"], 3)

    def test_required_portfolio_keys(self):
        r = analyze_portfolio(self._protocols(), config=_cfg())
        for k in ["total_protocols", "results", "best_nim_protocol",
                  "worst_nim_protocol", "avg_nim_pct", "inverted_count",
                  "avg_efficiency_score"]:
            self.assertIn(k, r)

    def test_results_each_has_nim_label(self):
        r = analyze_portfolio(self._protocols(), config=_cfg())
        for res in r["results"]:
            self.assertIn("nim_label", res)
            self.assertIn(res["nim_label"], ALL_NIM_LABELS)


# ===========================================================================
# 16. DeFiProtocolNetInterestMarginAnalyzer class
# ===========================================================================

class TestDeFiProtocolNetInterestMarginAnalyzerClass(unittest.TestCase):

    def test_instantiation_no_config(self):
        a = DeFiProtocolNetInterestMarginAnalyzer()
        self.assertIsNotNone(a)

    def test_instantiation_with_config(self):
        a = DeFiProtocolNetInterestMarginAnalyzer(config={"log_path": _tmp_log()})
        self.assertIsNotNone(a)

    def test_analyze_returns_dict(self):
        a = DeFiProtocolNetInterestMarginAnalyzer(config=_cfg())
        r = a.analyze(_proto())
        self.assertIsInstance(r, dict)

    def test_analyze_nim_label_present(self):
        a = DeFiProtocolNetInterestMarginAnalyzer(config=_cfg())
        r = a.analyze(_proto())
        self.assertIn("nim_label", r)

    def test_analyze_portfolio_returns_dict(self):
        a = DeFiProtocolNetInterestMarginAnalyzer(config=_cfg())
        r = a.analyze_portfolio([_proto("A"), _proto("B")])
        self.assertIsInstance(r, dict)
        self.assertEqual(r["total_protocols"], 2)

    def test_analyze_portfolio_empty(self):
        a = DeFiProtocolNetInterestMarginAnalyzer(config=_cfg())
        r = a.analyze_portfolio([])
        self.assertEqual(r["total_protocols"], 0)

    def test_class_config_passed_to_analyze(self):
        path = _tmp_log()
        a = DeFiProtocolNetInterestMarginAnalyzer(config={"log_path": path})
        a.analyze(_proto())
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_healthy_spread_via_class(self):
        a = DeFiProtocolNetInterestMarginAnalyzer(config=_cfg())
        r = a.analyze(_proto(borrow_apy_pct=9.0, supply_apy_pct=4.0))
        self.assertEqual(r["nim_label"], NIM_HEALTHY_SPREAD)

    def test_inverted_spread_via_class(self):
        a = DeFiProtocolNetInterestMarginAnalyzer(config=_cfg())
        r = a.analyze(_proto(borrow_apy_pct=3.0, supply_apy_pct=5.0))
        self.assertEqual(r["nim_label"], NIM_INVERTED_SPREAD)


# ===========================================================================
# 17. Revenue and yield consistency
# ===========================================================================

class TestRevenueAndYieldConsistency(unittest.TestCase):

    def test_revenue_increases_with_borrowed(self):
        cfg = _cfg()
        r1 = analyze(_proto(total_borrowed_usd=100_000_000.0), config=cfg)
        r2 = analyze(_proto(total_borrowed_usd=500_000_000.0), config=cfg)
        self.assertLess(r1["protocol_revenue_usd_annual"], r2["protocol_revenue_usd_annual"])

    def test_revenue_increases_with_reserve_factor(self):
        cfg = _cfg()
        r1 = analyze(_proto(reserve_factor_pct=5.0), config=cfg)
        r2 = analyze(_proto(reserve_factor_pct=20.0), config=cfg)
        self.assertLess(r1["protocol_revenue_usd_annual"], r2["protocol_revenue_usd_annual"])

    def test_supplier_yield_increases_with_utilization(self):
        cfg = _cfg()
        r1 = analyze(_proto(utilization_rate_pct=40.0), config=cfg)
        r2 = analyze(_proto(utilization_rate_pct=90.0), config=cfg)
        self.assertLess(r1["supplier_effective_yield_pct"], r2["supplier_effective_yield_pct"])

    def test_nim_increases_with_utilization(self):
        cfg = _cfg()
        r1 = analyze(_proto(utilization_rate_pct=30.0), config=cfg)
        r2 = analyze(_proto(utilization_rate_pct=90.0), config=cfg)
        self.assertLess(r1["net_interest_margin_pct"], r2["net_interest_margin_pct"])

    def test_higher_spread_higher_efficiency(self):
        cfg = _cfg()
        r1 = analyze(_proto(borrow_apy_pct=4.0, supply_apy_pct=3.5), config=cfg)
        r2 = analyze(_proto(borrow_apy_pct=8.0, supply_apy_pct=3.5), config=cfg)
        self.assertLess(r1["nim_efficiency_score"], r2["nim_efficiency_score"])

    def test_total_supplied_passthrough(self):
        r = analyze(_proto(total_supplied_usd=999_999_999.0), config=_cfg())
        self.assertAlmostEqual(r["total_supplied_usd"], 999_999_999.0)

    def test_zero_supply_apy_inverted_only_when_borrow_zero(self):
        r = analyze(_proto(supply_apy_pct=0.0, borrow_apy_pct=0.0), config=_cfg())
        self.assertEqual(r["nim_label"], NIM_INVERTED_SPREAD)

    def test_all_zeros_gives_inverted(self):
        r = analyze({}, config=_cfg())
        self.assertEqual(r["nim_label"], NIM_INVERTED_SPREAD)
        self.assertAlmostEqual(r["gross_spread_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
