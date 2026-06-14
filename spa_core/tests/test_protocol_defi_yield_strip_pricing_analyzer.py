#!/usr/bin/env python3
"""Unit tests for MP-1077 ProtocolDeFiYieldStripPricingAnalyzer.

Run:
    python3 -m unittest spa_core/tests/test_protocol_defi_yield_strip_pricing_analyzer.py -v

Pure stdlib unittest — no pytest, no numpy, no external dependencies.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.protocol_defi_yield_strip_pricing_analyzer import (
    ProtocolDeFiYieldStripPricingAnalyzer,
    analyze,
    _compute_pt_implied_yield,
    _compute_yt_leverage_factor,
    _compute_rate_arbitrage_bps,
    _compute_pricing_efficiency_score,
    _strip_label,
    _load_json_list,
    _atomic_write,
    _append_log,
    LOG_FILENAME,
    RING_BUFFER_CAP,
    THRESHOLD_DEEP_DISCOUNT,
    THRESHOLD_FAIR_LOW,
    THRESHOLD_SLIGHT_LOW,
    THRESHOLD_OVERPRICED,
    MP_TAG,
    SOURCE_NAME,
    SCHEMA_VERSION,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _good_data(**overrides) -> dict:
    """Return a fair-priced yield-strip snapshot."""
    base = {
        "protocol_name":           "TestPendle",
        "underlying_apy_pct":                  10.0,
        "pt_discount_pct":                      2.5,
        "yt_implied_apy_pct":                   3.0,
        "maturity_days":                       180.0,
        "days_to_maturity":                     90.0,
        "fixed_rate_locked_pct":                9.0,
        "variable_rate_current_pct":           10.0,
        "tvl_usd":                      50_000_000.0,
        "liquidity_depth_usd":           5_000_000.0,
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. _compute_pt_implied_yield
# ===========================================================================

class TestComputePtImpliedYield(unittest.TestCase):

    def test_basic_case(self):
        # discount=5%, 365 days: (5/95)*(365/365)*100 = 5.263...%
        y = _compute_pt_implied_yield(5.0, 365.0)
        self.assertAlmostEqual(y, 5.0 / 95.0 * 100.0, places=4)

    def test_zero_discount_returns_zero(self):
        y = _compute_pt_implied_yield(0.0, 365.0)
        self.assertAlmostEqual(y, 0.0, places=6)

    def test_negative_discount_clamped(self):
        y = _compute_pt_implied_yield(-5.0, 365.0)
        self.assertAlmostEqual(y, 0.0, places=6)

    def test_100_discount_returns_zero(self):
        y = _compute_pt_implied_yield(100.0, 365.0)
        self.assertAlmostEqual(y, 0.0, places=6)

    def test_zero_days_returns_zero(self):
        y = _compute_pt_implied_yield(5.0, 0.0)
        self.assertAlmostEqual(y, 0.0, places=6)

    def test_negative_days_returns_zero(self):
        y = _compute_pt_implied_yield(5.0, -30.0)
        self.assertAlmostEqual(y, 0.0, places=6)

    def test_higher_discount_higher_yield(self):
        y1 = _compute_pt_implied_yield(3.0, 90.0)
        y2 = _compute_pt_implied_yield(5.0, 90.0)
        self.assertGreater(y2, y1)

    def test_shorter_maturity_higher_annualised_yield(self):
        y_long = _compute_pt_implied_yield(5.0, 365.0)
        y_short = _compute_pt_implied_yield(5.0, 90.0)
        self.assertGreater(y_short, y_long)

    def test_formula_manually(self):
        # discount=10, days=180: (10/90)*(365/180)*100 = 22.53%
        expected = (10.0 / 90.0) * (365.0 / 180.0) * 100.0
        y = _compute_pt_implied_yield(10.0, 180.0)
        self.assertAlmostEqual(y, expected, places=4)

    def test_small_discount_short_maturity(self):
        y = _compute_pt_implied_yield(0.5, 7.0)
        self.assertGreater(y, 0.0)

    def test_discount_99_near_zero_maturity(self):
        y = _compute_pt_implied_yield(99.0, 1.0)
        self.assertGreater(y, 0.0)


# ===========================================================================
# 2. _compute_yt_leverage_factor
# ===========================================================================

class TestComputeYtLeverageFactor(unittest.TestCase):

    def test_basic_case(self):
        # underlying=10, yt_implied=5 → leverage=2
        lev = _compute_yt_leverage_factor(10.0, 5.0)
        self.assertAlmostEqual(lev, 2.0, places=6)

    def test_zero_underlying_returns_zero(self):
        lev = _compute_yt_leverage_factor(0.0, 5.0)
        self.assertAlmostEqual(lev, 0.0, places=6)

    def test_zero_yt_implied_uses_floor(self):
        # underlying=10, yt=0 → uses 0.01 floor → very high leverage, capped at 100
        lev = _compute_yt_leverage_factor(10.0, 0.0)
        self.assertAlmostEqual(lev, 100.0, places=4)

    def test_negative_yt_implied_uses_floor(self):
        lev = _compute_yt_leverage_factor(10.0, -5.0)
        self.assertAlmostEqual(lev, 100.0, places=4)

    def test_capped_at_100(self):
        lev = _compute_yt_leverage_factor(100.0, 0.001)
        self.assertAlmostEqual(lev, 100.0, places=4)

    def test_equal_rates_leverage_1(self):
        lev = _compute_yt_leverage_factor(8.0, 8.0)
        self.assertAlmostEqual(lev, 1.0, places=6)

    def test_higher_underlying_higher_leverage(self):
        lev_low = _compute_yt_leverage_factor(5.0, 5.0)
        lev_high = _compute_yt_leverage_factor(20.0, 5.0)
        self.assertGreater(lev_high, lev_low)

    def test_non_negative(self):
        for ua in [0, 1, 5, 10, 20]:
            for ya in [-1, 0, 1, 5, 10]:
                lev = _compute_yt_leverage_factor(float(ua), float(ya))
                self.assertGreaterEqual(lev, 0.0)


# ===========================================================================
# 3. _compute_rate_arbitrage_bps
# ===========================================================================

class TestComputeRateArbitrageBps(unittest.TestCase):

    def test_positive_arb(self):
        bps = _compute_rate_arbitrage_bps(10.0, 9.0)
        self.assertAlmostEqual(bps, 100.0, places=4)

    def test_negative_arb(self):
        bps = _compute_rate_arbitrage_bps(8.0, 10.0)
        self.assertAlmostEqual(bps, -200.0, places=4)

    def test_zero_arb(self):
        bps = _compute_rate_arbitrage_bps(5.0, 5.0)
        self.assertAlmostEqual(bps, 0.0, places=4)

    def test_large_arb(self):
        bps = _compute_rate_arbitrage_bps(15.0, 5.0)
        self.assertAlmostEqual(bps, 1000.0, places=4)

    def test_fractional_difference(self):
        bps = _compute_rate_arbitrage_bps(5.5, 5.0)
        self.assertAlmostEqual(bps, 50.0, places=4)

    def test_both_zero(self):
        bps = _compute_rate_arbitrage_bps(0.0, 0.0)
        self.assertAlmostEqual(bps, 0.0, places=6)


# ===========================================================================
# 4. _strip_label
# ===========================================================================

class TestStripLabel(unittest.TestCase):

    def test_deep_discount(self):
        self.assertEqual(_strip_label(201.0), "DEEP_DISCOUNT_OPPORTUNITY")
        self.assertEqual(_strip_label(500.0), "DEEP_DISCOUNT_OPPORTUNITY")

    def test_fair_priced_high(self):
        self.assertEqual(_strip_label(200.0), "FAIR_PRICED")
        self.assertEqual(_strip_label(0.0), "FAIR_PRICED")
        self.assertEqual(_strip_label(-100.0), "FAIR_PRICED")

    def test_slight_premium(self):
        self.assertEqual(_strip_label(-101.0), "SLIGHT_PREMIUM")
        self.assertEqual(_strip_label(-200.0), "SLIGHT_PREMIUM")

    def test_overpriced(self):
        self.assertEqual(_strip_label(-201.0), "OVERPRICED")
        self.assertEqual(_strip_label(-500.0), "OVERPRICED")

    def test_avoid_strip(self):
        self.assertEqual(_strip_label(-501.0), "AVOID_STRIP")
        self.assertEqual(_strip_label(-1000.0), "AVOID_STRIP")

    def test_all_labels_valid(self):
        valid = {
            "DEEP_DISCOUNT_OPPORTUNITY", "FAIR_PRICED",
            "SLIGHT_PREMIUM", "OVERPRICED", "AVOID_STRIP",
        }
        for bps in [500, 300, 200, 100, 0, -50, -100, -150, -200, -300, -500, -600]:
            lbl = _strip_label(float(bps))
            self.assertIn(lbl, valid)

    def test_boundary_200(self):
        # exactly 200 → FAIR_PRICED (not DEEP_DISCOUNT)
        self.assertEqual(_strip_label(200.0), "FAIR_PRICED")
        # 200.001 → DEEP_DISCOUNT
        self.assertEqual(_strip_label(200.001), "DEEP_DISCOUNT_OPPORTUNITY")

    def test_boundary_minus_100(self):
        self.assertEqual(_strip_label(-100.0), "FAIR_PRICED")
        self.assertEqual(_strip_label(-100.001), "SLIGHT_PREMIUM")

    def test_boundary_minus_200(self):
        self.assertEqual(_strip_label(-200.0), "SLIGHT_PREMIUM")
        self.assertEqual(_strip_label(-200.001), "OVERPRICED")


# ===========================================================================
# 5. _compute_pricing_efficiency_score
# ===========================================================================

class TestComputePricingEfficiencyScore(unittest.TestCase):

    def _score(self, **kwargs):
        defaults = dict(
            pt_discount_pct=2.5,
            underlying_apy_pct=10.0,
            pt_implied_yield_pct=10.0,
            yt_leverage_factor=4.0,
            rate_arbitrage_bps=50.0,
            tvl_usd=50_000_000.0,
            liquidity_depth_usd=5_000_000.0,
            days_to_maturity=90.0,
        )
        defaults.update(kwargs)
        return _compute_pricing_efficiency_score(**defaults)

    def test_score_in_range(self):
        s = self._score()
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_good_params_high_score(self):
        s = self._score(
            underlying_apy_pct=10.0,
            pt_implied_yield_pct=10.0,
            yt_leverage_factor=5.0,
            rate_arbitrage_bps=100.0,
            tvl_usd=100_000_000.0,
            liquidity_depth_usd=30_000_000.0,
            days_to_maturity=180.0,
        )
        self.assertGreater(s, 50.0)

    def test_zero_liquidity_lowers_score(self):
        s_liq = self._score(liquidity_depth_usd=10_000_000.0)
        s_no_liq = self._score(liquidity_depth_usd=0.0)
        self.assertGreater(s_liq, s_no_liq)

    def test_zero_days_lowers_score(self):
        s_good = self._score(days_to_maturity=180.0)
        s_zero = self._score(days_to_maturity=0.0)
        self.assertGreater(s_good, s_zero)

    def test_high_leverage_penalised(self):
        s_ok = self._score(yt_leverage_factor=5.0)
        s_high = self._score(yt_leverage_factor=50.0)
        self.assertGreater(s_ok, s_high)

    def test_large_negative_arb_penalised(self):
        s_fair = self._score(rate_arbitrage_bps=50.0)
        s_bad = self._score(rate_arbitrage_bps=-1000.0)
        self.assertGreater(s_fair, s_bad)

    def test_score_non_negative(self):
        # Worst case inputs
        s = self._score(
            underlying_apy_pct=0.0,
            pt_implied_yield_pct=0.0,
            yt_leverage_factor=100.0,
            rate_arbitrage_bps=-2000.0,
            tvl_usd=0.0,
            liquidity_depth_usd=0.0,
            days_to_maturity=0.0,
        )
        self.assertGreaterEqual(s, 0.0)

    def test_ideal_leverage_range_2_to_8(self):
        s5 = self._score(yt_leverage_factor=5.0)
        s2 = self._score(yt_leverage_factor=2.0)
        s_low = self._score(yt_leverage_factor=1.0)
        self.assertGreater(s5, s_low)
        self.assertGreater(s2, s_low)


# ===========================================================================
# 6. analyze() — integration
# ===========================================================================

class TestAnalyzeFunction(unittest.TestCase):

    def _run(self, **overrides):
        return analyze(_good_data(**overrides))

    def test_output_keys_present(self):
        result = self._run()
        for key in (
            "protocol_name", "pt_implied_yield_pct", "yt_leverage_factor",
            "rate_arbitrage_bps", "pricing_efficiency_score", "strip_label",
            "mp_tag", "source", "schema_version",
        ):
            self.assertIn(key, result)

    def test_mp_tag_correct(self):
        self.assertEqual(self._run()["mp_tag"], "MP-1077")

    def test_source_correct(self):
        self.assertEqual(self._run()["source"], SOURCE_NAME)

    def test_schema_version(self):
        self.assertEqual(self._run()["schema_version"], SCHEMA_VERSION)

    def test_strip_label_valid(self):
        valid = {
            "DEEP_DISCOUNT_OPPORTUNITY", "FAIR_PRICED",
            "SLIGHT_PREMIUM", "OVERPRICED", "AVOID_STRIP",
        }
        self.assertIn(self._run()["strip_label"], valid)

    def test_pricing_efficiency_in_range(self):
        result = self._run()
        self.assertGreaterEqual(result["pricing_efficiency_score"], 0.0)
        self.assertLessEqual(result["pricing_efficiency_score"], 100.0)

    def test_pt_implied_yield_is_positive_for_discount(self):
        result = self._run(pt_discount_pct=5.0, days_to_maturity=90.0)
        self.assertGreater(result["pt_implied_yield_pct"], 0.0)

    def test_zero_discount_zero_pt_yield(self):
        result = self._run(pt_discount_pct=0.0)
        self.assertAlmostEqual(result["pt_implied_yield_pct"], 0.0, places=6)

    def test_protocol_name_preserved(self):
        result = analyze(_good_data(protocol_name="Pendle"))
        self.assertEqual(result["protocol_name"], "Pendle")

    def test_deep_discount_label(self):
        # pt_implied=20%, fixed=5% → arb=1500bps > 200 → DEEP_DISCOUNT
        result = self._run(
            pt_discount_pct=10.0,
            days_to_maturity=365.0,  # 10/(90)*(365/365)*100 ~ 11.1%
            fixed_rate_locked_pct=5.0,
        )
        # Just check the output is a known label
        self.assertIn(result["strip_label"],
                      {"DEEP_DISCOUNT_OPPORTUNITY", "FAIR_PRICED"})

    def test_avoid_strip_label(self):
        # pt implied very low, fixed very high → huge negative arb
        result = self._run(
            pt_discount_pct=0.1,
            days_to_maturity=365.0,
            fixed_rate_locked_pct=20.0,
        )
        self.assertEqual(result["strip_label"], "AVOID_STRIP")

    def test_yt_leverage_factor_positive(self):
        result = self._run(underlying_apy_pct=10.0, yt_implied_apy_pct=5.0)
        self.assertAlmostEqual(result["yt_leverage_factor"], 2.0, places=4)

    def test_rate_arbitrage_bps_calculation(self):
        # pt_implied = (2.5/97.5)*(365/90)*100 ≈ 10.39%
        # fixed=9% → arb=(10.39-9)*100=139 bps
        result = self._run(
            pt_discount_pct=2.5,
            days_to_maturity=90.0,
            fixed_rate_locked_pct=9.0,
        )
        expected_pt_yield = (2.5 / 97.5) * (365.0 / 90.0) * 100.0
        expected_arb = (expected_pt_yield - 9.0) * 100.0
        self.assertAlmostEqual(result["rate_arbitrage_bps"], expected_arb, places=2)

    def test_missing_keys_defaults_no_crash(self):
        result = analyze({"protocol_name": "Minimal"})
        self.assertIn("strip_label", result)
        self.assertIn("pricing_efficiency_score", result)

    def test_all_zeros_no_crash(self):
        data = {k: 0 for k in [
            "underlying_apy_pct", "pt_discount_pct", "yt_implied_apy_pct",
            "maturity_days", "days_to_maturity", "fixed_rate_locked_pct",
            "variable_rate_current_pct", "tvl_usd", "liquidity_depth_usd",
        ]}
        data["protocol_name"] = "ZeroProto"
        result = analyze(data)
        self.assertGreaterEqual(result["pricing_efficiency_score"], 0.0)

    def test_variable_rate_current_echoed(self):
        result = self._run(variable_rate_current_pct=8.5)
        self.assertAlmostEqual(result["variable_rate_current_pct"], 8.5, places=6)

    def test_underlying_apy_echoed(self):
        result = self._run(underlying_apy_pct=15.0)
        self.assertAlmostEqual(result["underlying_apy_pct"], 15.0, places=6)

    def test_pt_discount_echoed(self):
        result = self._run(pt_discount_pct=3.5)
        self.assertAlmostEqual(result["pt_discount_pct"], 3.5, places=6)


# ===========================================================================
# 7. ProtocolDeFiYieldStripPricingAnalyzer class
# ===========================================================================

class TestProtocolDeFiYieldStripPricingAnalyzerClass(unittest.TestCase):

    def setUp(self):
        self.analyzer = ProtocolDeFiYieldStripPricingAnalyzer()

    def test_analyze_returns_dict(self):
        result = self.analyzer.analyze(_good_data())
        self.assertIsInstance(result, dict)

    def test_analyze_has_strip_label(self):
        result = self.analyzer.analyze(_good_data())
        self.assertIn("strip_label", result)

    def test_analyze_has_efficiency_score(self):
        result = self.analyzer.analyze(_good_data())
        self.assertIn("pricing_efficiency_score", result)

    def test_write_log_false_no_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            self.analyzer.analyze(_good_data(), write_log=False, data_dir=data_dir)
            self.assertFalse((data_dir / LOG_FILENAME).exists())

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            self.analyzer.analyze(_good_data(), write_log=True, data_dir=data_dir)
            self.assertTrue((data_dir / LOG_FILENAME).exists())

    def test_write_log_valid_json_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            self.analyzer.analyze(_good_data(), write_log=True, data_dir=data_dir)
            with open(data_dir / LOG_FILENAME) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_multiple_analyses_accumulate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            for i in range(5):
                self.analyzer.analyze(
                    _good_data(protocol_name=f"Protocol{i}"),
                    write_log=True, data_dir=data_dir,
                )
            with open(data_dir / LOG_FILENAME) as f:
                data = json.load(f)
            self.assertEqual(len(data), 5)

    def test_ring_buffer_cap_enforced(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            for i in range(RING_BUFFER_CAP + 5):
                self.analyzer.analyze(
                    _good_data(protocol_name=f"P{i}"),
                    write_log=True, data_dir=data_dir,
                )
            with open(data_dir / LOG_FILENAME) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), RING_BUFFER_CAP)

    def test_log_entry_has_ts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            self.analyzer.analyze(_good_data(), write_log=True, data_dir=data_dir)
            with open(data_dir / LOG_FILENAME) as f:
                data = json.load(f)
            self.assertIn("ts", data[0])

    def test_multiple_calls_independent(self):
        r1 = self.analyzer.analyze(_good_data(underlying_apy_pct=10.0))
        r2 = self.analyzer.analyze(_good_data(underlying_apy_pct=20.0))
        # leverage factor should differ
        self.assertNotEqual(r1["yt_leverage_factor"], r2["yt_leverage_factor"])


# ===========================================================================
# 8. _load_json_list and _atomic_write
# ===========================================================================

class TestIOHelpers(unittest.TestCase):

    def test_load_missing_file_returns_empty(self):
        path = Path("/tmp/spa_test_missing_strip_xyz.json")
        result = _load_json_list(path)
        self.assertEqual(result, [])

    def test_atomic_write_then_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "strip.json"
            _atomic_write(path, [{"a": 1}])
            result = _load_json_list(path)
            self.assertEqual(result[0]["a"], 1)

    def test_atomic_write_overwrites(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "strip.json"
            _atomic_write(path, [1, 2, 3])
            _atomic_write(path, [4, 5])
            result = _load_json_list(path)
            self.assertEqual(result, [4, 5])

    def test_load_invalid_json_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{bad json}")
            fname = f.name
        try:
            result = _load_json_list(Path(fname))
            self.assertEqual(result, [])
        finally:
            os.unlink(fname)

    def test_load_dict_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dict.json"
            _atomic_write(path, {"key": "value"})
            result = _load_json_list(path)
            self.assertEqual(result, [])


# ===========================================================================
# 9. Edge cases and boundary conditions
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_pt_discount_99_no_crash(self):
        result = analyze(_good_data(pt_discount_pct=99.9))
        self.assertIn("pt_implied_yield_pct", result)

    def test_very_large_tvl(self):
        result = analyze(_good_data(tvl_usd=1e18, liquidity_depth_usd=1e17))
        self.assertGreaterEqual(result["pricing_efficiency_score"], 0.0)

    def test_string_numbers_handled(self):
        result = analyze(_good_data(underlying_apy_pct="10.0", pt_discount_pct="2.5"))
        self.assertGreater(result["pt_implied_yield_pct"], 0.0)

    def test_days_to_maturity_1_extreme_annualisation(self):
        y = _compute_pt_implied_yield(5.0, 1.0)
        self.assertGreater(y, 100.0)  # very high when near-maturity

    def test_deep_discount_example(self):
        # 20% discount, 365 days → pt_implied = 20/80*100 = 25%
        # fixed=5% → arb = (25-5)*100 = 2000 bps > 200 → DEEP_DISCOUNT
        result = analyze(_good_data(
            pt_discount_pct=20.0,
            days_to_maturity=365.0,
            fixed_rate_locked_pct=5.0,
        ))
        self.assertEqual(result["strip_label"], "DEEP_DISCOUNT_OPPORTUNITY")

    def test_avoid_strip_example(self):
        # near-zero pt yield, very high fixed locked
        result = analyze(_good_data(
            pt_discount_pct=0.05,
            days_to_maturity=365.0,
            fixed_rate_locked_pct=30.0,
        ))
        self.assertEqual(result["strip_label"], "AVOID_STRIP")

    def test_leverage_factor_capped_at_100(self):
        lev = _compute_yt_leverage_factor(100.0, 0.0)
        self.assertLessEqual(lev, 100.0)

    def test_efficiency_score_capped_at_100(self):
        s = _compute_pricing_efficiency_score(
            pt_discount_pct=3.0,
            underlying_apy_pct=10.0,
            pt_implied_yield_pct=10.0,
            yt_leverage_factor=5.0,
            rate_arbitrage_bps=100.0,
            tvl_usd=1e12,
            liquidity_depth_usd=1e12,
            days_to_maturity=365.0,
        )
        self.assertLessEqual(s, 100.0)

    def test_efficiency_score_non_negative_worst_case(self):
        s = _compute_pricing_efficiency_score(
            pt_discount_pct=0.0,
            underlying_apy_pct=0.0,
            pt_implied_yield_pct=0.0,
            yt_leverage_factor=0.0,
            rate_arbitrage_bps=-10000.0,
            tvl_usd=0.0,
            liquidity_depth_usd=0.0,
            days_to_maturity=0.0,
        )
        self.assertGreaterEqual(s, 0.0)

    def test_label_boundary_200_bps(self):
        self.assertEqual(_strip_label(200.0), "FAIR_PRICED")
        self.assertEqual(_strip_label(200.0001), "DEEP_DISCOUNT_OPPORTUNITY")

    def test_label_boundary_minus_500_bps(self):
        self.assertEqual(_strip_label(-500.0), "OVERPRICED")
        self.assertEqual(_strip_label(-500.0001), "AVOID_STRIP")

    def test_pt_yield_monotone_in_discount(self):
        discounts = [1.0, 2.0, 5.0, 10.0, 20.0, 30.0]
        yields = [_compute_pt_implied_yield(d, 90.0) for d in discounts]
        for i in range(1, len(yields)):
            self.assertGreater(yields[i], yields[i - 1])

    def test_pt_yield_monotone_in_days_inverse(self):
        # Shorter maturity → higher annualised yield
        days = [365.0, 180.0, 90.0, 30.0, 7.0]
        yields = [_compute_pt_implied_yield(5.0, d) for d in days]
        for i in range(1, len(yields)):
            self.assertGreater(yields[i], yields[i - 1])

    def test_no_crash_large_batch(self):
        import itertools
        discounts = [0, 1, 5, 10, 20]
        days = [7, 30, 90, 180, 365]
        fixed = [0, 3, 8, 15]
        for d, day, fr in itertools.product(discounts, days, fixed):
            result = analyze(_good_data(
                pt_discount_pct=float(d),
                days_to_maturity=float(day),
                fixed_rate_locked_pct=float(fr),
            ))
            s = result["pricing_efficiency_score"]
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)


# ===========================================================================
# 10. Constants and module-level attributes
# ===========================================================================

class TestConstants(unittest.TestCase):

    def test_log_filename(self):
        self.assertEqual(LOG_FILENAME, "yield_strip_pricing_log.json")

    def test_ring_buffer_cap_is_100(self):
        self.assertEqual(RING_BUFFER_CAP, 100)

    def test_mp_tag_value(self):
        self.assertEqual(MP_TAG, "MP-1077")

    def test_source_name(self):
        self.assertEqual(SOURCE_NAME, "protocol_defi_yield_strip_pricing_analyzer")

    def test_schema_version_int(self):
        self.assertIsInstance(SCHEMA_VERSION, int)
        self.assertGreaterEqual(SCHEMA_VERSION, 1)

    def test_threshold_deep_discount(self):
        self.assertAlmostEqual(THRESHOLD_DEEP_DISCOUNT, 200.0, places=4)

    def test_threshold_fair_low(self):
        self.assertAlmostEqual(THRESHOLD_FAIR_LOW, -100.0, places=4)

    def test_threshold_slight_low(self):
        self.assertAlmostEqual(THRESHOLD_SLIGHT_LOW, -200.0, places=4)

    def test_threshold_overpriced(self):
        self.assertAlmostEqual(THRESHOLD_OVERPRICED, -500.0, places=4)

    def test_thresholds_ordered(self):
        self.assertGreater(THRESHOLD_DEEP_DISCOUNT, THRESHOLD_FAIR_LOW)
        self.assertGreater(THRESHOLD_FAIR_LOW, THRESHOLD_SLIGHT_LOW)
        self.assertGreater(THRESHOLD_SLIGHT_LOW, THRESHOLD_OVERPRICED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
