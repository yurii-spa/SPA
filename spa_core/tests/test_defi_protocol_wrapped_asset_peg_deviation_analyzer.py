#!/usr/bin/env python3
"""Unit tests for MP-1092 DeFiProtocolWrappedAssetPegDeviationAnalyzer (SPA-V784).

Run:
    python3 -m unittest spa_core/tests/test_defi_protocol_wrapped_asset_peg_deviation_analyzer.py -v

All tests use stdlib unittest only — no pytest, no numpy, no external deps.
"""
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.defi_protocol_wrapped_asset_peg_deviation_analyzer import (
    DeFiProtocolWrappedAssetPegDeviationAnalyzer,
    analyze,
    compute_observed_ratio,
    compute_peg_deviation_pct,
    compute_redemption_pressure_ratio,
    peg_label,
    peg_risk_score,
    _load_json_list,
    _atomic_write,
    LOG_FILENAME,
    RING_BUFFER_CAP,
    LABEL_ON_PEG_MAX,
    LABEL_SLIGHT_MAX,
    LABEL_MODERATE_MAX,
    LABEL_SEVERE_MAX,
    REDEMPTION_PRESSURE_HIGH,
    REDEMPTION_PRESSURE_MED,
    SCHEMA_VERSION,
    SOURCE_NAME,
    MP_TAG,
    SCORE_AT_ON_PEG_MAX,
    SCORE_AT_SLIGHT_MAX,
    SCORE_AT_MODERATE_MAX,
    SCORE_AT_SEVERE_MAX,
    SCORE_MAX,
)


# ===========================================================================
# 1. compute_observed_ratio
# ===========================================================================

class TestComputeObservedRatio(unittest.TestCase):

    def test_equal_prices_ratio_one(self):
        """stETH at peg: 1:1 ratio."""
        self.assertAlmostEqual(compute_observed_ratio(3200.0, 3200.0), 1.0, places=10)

    def test_slight_discount_below_one(self):
        result = compute_observed_ratio(3190.0, 3200.0)
        self.assertAlmostEqual(result, 3190.0 / 3200.0, places=10)

    def test_premium_above_one(self):
        result = compute_observed_ratio(3250.0, 3200.0)
        self.assertAlmostEqual(result, 3250.0 / 3200.0, places=10)

    def test_wsteth_typical_ratio(self):
        """wstETH typically trades at ~1.15x ETH due to rebasing."""
        result = compute_observed_ratio(3680.0, 3200.0)
        self.assertAlmostEqual(result, 1.15, places=5)

    def test_zero_underlying_raises(self):
        with self.assertRaises(ValueError):
            compute_observed_ratio(3200.0, 0.0)

    def test_negative_underlying_raises(self):
        with self.assertRaises(ValueError):
            compute_observed_ratio(3200.0, -100.0)

    def test_zero_wrapped_price(self):
        """Zero wrapped price = 0.0 ratio (not an error)."""
        self.assertAlmostEqual(compute_observed_ratio(0.0, 3200.0), 0.0, places=10)

    def test_small_underlying_price(self):
        """USDC vs USDT: very close prices."""
        result = compute_observed_ratio(0.9995, 1.0)
        self.assertAlmostEqual(result, 0.9995, places=8)

    def test_large_values(self):
        result = compute_observed_ratio(1_000_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 1.0, places=10)


# ===========================================================================
# 2. compute_peg_deviation_pct
# ===========================================================================

class TestComputePegDeviationPct(unittest.TestCase):

    def test_perfect_peg_zero_deviation(self):
        dev = compute_peg_deviation_pct(1.0, 1.0)
        self.assertAlmostEqual(dev, 0.0, places=10)

    def test_negative_deviation_below_peg(self):
        """observed < expected => negative deviation."""
        dev = compute_peg_deviation_pct(0.99, 1.0)
        self.assertAlmostEqual(dev, -1.0, places=8)

    def test_positive_deviation_above_peg(self):
        """observed > expected => positive deviation."""
        dev = compute_peg_deviation_pct(1.01, 1.0)
        self.assertAlmostEqual(dev, 1.0, places=8)

    def test_signed_formula_steth(self):
        """stETH 0.0625% below peg."""
        obs = 3198.0 / 3200.0   # 0.999375
        dev = compute_peg_deviation_pct(obs, 1.0)
        expected = (obs - 1.0) / 1.0 * 100.0
        self.assertAlmostEqual(dev, expected, places=8)

    def test_expected_ratio_not_one(self):
        """wstETH: expected_ratio = 1.15."""
        obs = 1.18
        dev = compute_peg_deviation_pct(obs, 1.15)
        self.assertAlmostEqual(dev, (1.18 - 1.15) / 1.15 * 100.0, places=8)

    def test_zero_expected_ratio_raises(self):
        with self.assertRaises(ValueError):
            compute_peg_deviation_pct(1.0, 0.0)

    def test_negative_expected_ratio_raises(self):
        with self.assertRaises(ValueError):
            compute_peg_deviation_pct(1.0, -1.0)

    def test_large_deviation(self):
        """10% depeg."""
        dev = compute_peg_deviation_pct(0.9, 1.0)
        self.assertAlmostEqual(dev, -10.0, places=8)

    def test_deviation_is_signed_not_abs(self):
        """Confirm deviation preserves sign."""
        dev_neg = compute_peg_deviation_pct(0.99, 1.0)
        dev_pos = compute_peg_deviation_pct(1.01, 1.0)
        self.assertLess(dev_neg, 0.0)
        self.assertGreater(dev_pos, 0.0)


# ===========================================================================
# 3. compute_redemption_pressure_ratio
# ===========================================================================

class TestComputeRedemptionPressureRatio(unittest.TestCase):

    def test_normal_case(self):
        ratio = compute_redemption_pressure_ratio(50_000_000, 15_000_000_000)
        self.assertAlmostEqual(ratio, 50_000_000 / 15_000_000_000, places=12)

    def test_zero_tvl_returns_zero(self):
        self.assertAlmostEqual(compute_redemption_pressure_ratio(1_000_000, 0), 0.0, places=12)

    def test_negative_tvl_returns_zero(self):
        self.assertAlmostEqual(compute_redemption_pressure_ratio(1_000_000, -1_000_000), 0.0, places=12)

    def test_zero_volume(self):
        self.assertAlmostEqual(compute_redemption_pressure_ratio(0, 5_000_000), 0.0, places=12)

    def test_volume_equals_tvl(self):
        self.assertAlmostEqual(compute_redemption_pressure_ratio(1_000_000, 1_000_000), 1.0, places=12)

    def test_high_pressure_above_one(self):
        """Volume > TVL is technically possible in a crisis."""
        ratio = compute_redemption_pressure_ratio(2_000_000, 1_000_000)
        self.assertAlmostEqual(ratio, 2.0, places=12)

    def test_small_fractional_pressure(self):
        ratio = compute_redemption_pressure_ratio(100_000, 10_000_000)
        self.assertAlmostEqual(ratio, 0.01, places=10)


# ===========================================================================
# 4. peg_label — all categories and boundary conditions
# ===========================================================================

class TestPegLabel(unittest.TestCase):

    # ON_PEG: abs_deviation < 0.1%
    def test_on_peg_zero(self):
        self.assertEqual(peg_label(0.0), "ON_PEG")

    def test_on_peg_midpoint(self):
        self.assertEqual(peg_label(0.05), "ON_PEG")

    def test_on_peg_just_below_threshold(self):
        self.assertEqual(peg_label(0.0999), "ON_PEG")

    # SLIGHT_DEVIATION: 0.1% <= abs < 0.5%
    def test_slight_at_lower_bound(self):
        self.assertEqual(peg_label(0.1), "SLIGHT_DEVIATION")

    def test_slight_midpoint(self):
        self.assertEqual(peg_label(0.3), "SLIGHT_DEVIATION")

    def test_slight_just_below_upper(self):
        self.assertEqual(peg_label(0.4999), "SLIGHT_DEVIATION")

    # MODERATE_DEPEG: 0.5% <= abs < 2.0%
    def test_moderate_at_lower_bound(self):
        self.assertEqual(peg_label(0.5), "MODERATE_DEPEG")

    def test_moderate_midpoint(self):
        self.assertEqual(peg_label(1.0), "MODERATE_DEPEG")

    def test_moderate_just_below_upper(self):
        self.assertEqual(peg_label(1.999), "MODERATE_DEPEG")

    # SEVERE_DEPEG: 2.0% <= abs < 5.0%
    def test_severe_at_lower_bound(self):
        self.assertEqual(peg_label(2.0), "SEVERE_DEPEG")

    def test_severe_midpoint(self):
        self.assertEqual(peg_label(3.5), "SEVERE_DEPEG")

    def test_severe_just_below_upper(self):
        self.assertEqual(peg_label(4.999), "SEVERE_DEPEG")

    # CRITICAL_DEPEG: abs >= 5.0%
    def test_critical_at_threshold(self):
        self.assertEqual(peg_label(5.0), "CRITICAL_DEPEG")

    def test_critical_moderate_value(self):
        self.assertEqual(peg_label(10.0), "CRITICAL_DEPEG")

    def test_critical_extreme_value(self):
        self.assertEqual(peg_label(50.0), "CRITICAL_DEPEG")

    def test_critical_large_value(self):
        self.assertEqual(peg_label(100.0), "CRITICAL_DEPEG")

    # Boundary precision
    def test_on_peg_label_constant_check(self):
        """Label at exactly LABEL_ON_PEG_MAX should be SLIGHT_DEVIATION."""
        self.assertEqual(peg_label(LABEL_ON_PEG_MAX), "SLIGHT_DEVIATION")

    def test_moderate_at_LABEL_SLIGHT_MAX(self):
        self.assertEqual(peg_label(LABEL_SLIGHT_MAX), "MODERATE_DEPEG")

    def test_severe_at_LABEL_MODERATE_MAX(self):
        self.assertEqual(peg_label(LABEL_MODERATE_MAX), "SEVERE_DEPEG")

    def test_critical_at_LABEL_SEVERE_MAX(self):
        self.assertEqual(peg_label(LABEL_SEVERE_MAX), "CRITICAL_DEPEG")


# ===========================================================================
# 5. peg_risk_score — base score (no modifiers)
# ===========================================================================

class TestPegRiskScoreBase(unittest.TestCase):
    """Base score without modifiers (redemption enabled, pressure=0)."""

    def _base(self, dev):
        return peg_risk_score(dev, True, 0.0)

    def test_zero_deviation_score_zero(self):
        self.assertEqual(self._base(0.0), 0)

    def test_midpoint_on_peg_band(self):
        """abs_dev=0.05 → t=0.5 → score=round(5)=5"""
        self.assertEqual(self._base(0.05), 5)

    def test_score_at_on_peg_boundary(self):
        """abs_dev=0.1 → score=10 (SCORE_AT_ON_PEG_MAX)"""
        self.assertEqual(self._base(0.1), SCORE_AT_ON_PEG_MAX)

    def test_midpoint_slight_band(self):
        """abs_dev=0.3 → t=0.5 → score=round(10+10)=20"""
        self.assertEqual(self._base(0.3), 20)

    def test_score_at_slight_boundary(self):
        """abs_dev=0.5 → score=30 (SCORE_AT_SLIGHT_MAX)"""
        self.assertEqual(self._base(0.5), SCORE_AT_SLIGHT_MAX)

    def test_midpoint_moderate_band(self):
        """abs_dev=1.0 → t=1/3 → score=round(30+10)=40"""
        self.assertEqual(self._base(1.0), 40)

    def test_score_at_moderate_boundary(self):
        """abs_dev=2.0 → score=60 (SCORE_AT_MODERATE_MAX)"""
        self.assertEqual(self._base(2.0), SCORE_AT_MODERATE_MAX)

    def test_midpoint_severe_band(self):
        """abs_dev=3.5 → t=0.5 → score=round(60+12.5)=72 or 73 depending on rounding"""
        result = self._base(3.5)
        self.assertIn(result, [72, 73])  # banker's rounding may give either

    def test_score_at_severe_boundary(self):
        """abs_dev=5.0 → score=85 (SCORE_AT_SEVERE_MAX)"""
        self.assertEqual(self._base(5.0), SCORE_AT_SEVERE_MAX)

    def test_midpoint_critical_band(self):
        """abs_dev=7.5 → t=0.5 → score=round(85+7.5)=92 or 93"""
        result = self._base(7.5)
        self.assertIn(result, [92, 93])

    def test_score_at_critical_cap(self):
        """abs_dev=10.0 → score=100"""
        self.assertEqual(self._base(10.0), SCORE_MAX)

    def test_score_beyond_cap_clamped(self):
        """abs_dev=20.0 → score=100 (clamped at max)"""
        self.assertEqual(self._base(20.0), SCORE_MAX)

    def test_score_in_range(self):
        for dev in [0, 0.05, 0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 20.0]:
            s = self._base(dev)
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(s, 100)

    def test_score_monotonic(self):
        """Higher deviation => higher or equal base score."""
        devs = [0, 0.05, 0.1, 0.3, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0]
        scores = [self._base(d) for d in devs]
        for i in range(len(scores) - 1):
            self.assertLessEqual(scores[i], scores[i + 1],
                                 f"score not monotonic at dev={devs[i+1]}")

    def test_score_is_integer(self):
        for dev in [0, 0.1, 0.5, 2.0, 5.0]:
            self.assertIsInstance(self._base(dev), int)


# ===========================================================================
# 6. peg_risk_score — modifier effects
# ===========================================================================

class TestPegRiskScoreModifiers(unittest.TestCase):

    def test_no_modifier_on_peg_enabled(self):
        """ON_PEG + enabled + no pressure = 0."""
        self.assertEqual(peg_risk_score(0.0, True, 0.0), 0)

    def test_redemption_disabled_adds_10(self):
        base = peg_risk_score(0.0, True, 0.0)
        with_disabled = peg_risk_score(0.0, False, 0.0)
        self.assertEqual(with_disabled - base, 10)

    def test_high_pressure_adds_10(self):
        base = peg_risk_score(0.0, True, 0.0)
        high = peg_risk_score(0.0, True, 0.6)
        self.assertEqual(high - base, 10)

    def test_medium_pressure_adds_5(self):
        base = peg_risk_score(0.0, True, 0.0)
        med = peg_risk_score(0.0, True, 0.2)
        self.assertEqual(med - base, 5)

    def test_pressure_at_high_threshold_adds_10(self):
        """Exactly at 0.5 does NOT exceed threshold, so only +5."""
        base = peg_risk_score(0.0, True, 0.0)
        at_threshold = peg_risk_score(0.0, True, REDEMPTION_PRESSURE_HIGH)
        # 0.5 is NOT > 0.5, so only medium modifier (+5)
        self.assertEqual(at_threshold - base, 5)

    def test_pressure_just_above_high_threshold_adds_10(self):
        base = peg_risk_score(0.0, True, 0.0)
        above = peg_risk_score(0.0, True, 0.5001)
        self.assertEqual(above - base, 10)

    def test_pressure_at_med_threshold_no_modifier(self):
        """Exactly at 0.1 is NOT > 0.1, so no medium modifier."""
        base = peg_risk_score(0.0, True, 0.0)
        at_med = peg_risk_score(0.0, True, REDEMPTION_PRESSURE_MED)
        self.assertEqual(at_med, base)

    def test_disabled_plus_high_pressure_additive(self):
        base = peg_risk_score(0.0, True, 0.0)
        both = peg_risk_score(0.0, False, 0.6)
        self.assertEqual(both - base, 20)

    def test_disabled_plus_medium_pressure_additive(self):
        base = peg_risk_score(0.0, True, 0.0)
        both = peg_risk_score(0.0, False, 0.2)
        self.assertEqual(both - base, 15)

    def test_score_capped_at_100(self):
        """Even with all modifiers and high deviation, cannot exceed 100."""
        score = peg_risk_score(20.0, False, 1.0)
        self.assertEqual(score, 100)

    def test_modifier_on_critical_depeg_still_capped(self):
        score = peg_risk_score(10.0, False, 0.6)
        self.assertLessEqual(score, 100)

    def test_no_pressure_below_med_threshold(self):
        """Pressure = 0.05 is below 0.1, so no modifier."""
        s1 = peg_risk_score(0.0, True, 0.0)
        s2 = peg_risk_score(0.0, True, 0.05)
        self.assertEqual(s1, s2)


# ===========================================================================
# 7. analyze() — full end-to-end function
# ===========================================================================

class TestAnalyzeFunction(unittest.TestCase):

    def _call(self, **kw):
        defaults = dict(
            wrapped_price_usd=3200.0,
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
            redemption_enabled=True,
            protocol_tvl_usd=10_000_000_000,
            daily_redemption_volume_usd=50_000_000,
            asset_name="stETH",
            protocol_name="Lido",
        )
        defaults.update(kw)
        return analyze(**defaults)

    def test_returns_dict(self):
        self.assertIsInstance(self._call(), dict)

    def test_schema_version_present(self):
        self.assertEqual(self._call()["schema_version"], SCHEMA_VERSION)

    def test_source_present(self):
        self.assertEqual(self._call()["source"], SOURCE_NAME)

    def test_mp_tag_present(self):
        self.assertEqual(self._call()["mp_tag"], MP_TAG)

    def test_timestamp_present(self):
        r = self._call()
        self.assertIn("timestamp", r)
        self.assertTrue(r["timestamp"].endswith("Z") or "+" in r["timestamp"] or r["timestamp"].endswith("+00:00"))

    def test_asset_name_echoed(self):
        self.assertEqual(self._call(asset_name="wstETH")["asset_name"], "wstETH")

    def test_protocol_name_echoed(self):
        self.assertEqual(self._call(protocol_name="Coinbase")["protocol_name"], "Coinbase")

    def test_observed_ratio_correct(self):
        r = self._call(wrapped_price_usd=3680.0, underlying_price_usd=3200.0)
        self.assertAlmostEqual(r["observed_ratio"], 1.15, places=5)

    def test_peg_deviation_pct_signed(self):
        """stETH -0.0625% below peg."""
        r = self._call(wrapped_price_usd=3198.0, underlying_price_usd=3200.0, expected_ratio=1.0)
        self.assertLess(r["peg_deviation_pct"], 0.0)

    def test_abs_deviation_pct_nonnegative(self):
        r = self._call(wrapped_price_usd=3100.0, underlying_price_usd=3200.0)
        self.assertGreaterEqual(r["abs_deviation_pct"], 0.0)

    def test_abs_equals_abs_of_signed(self):
        r = self._call(wrapped_price_usd=3100.0, underlying_price_usd=3200.0)
        self.assertAlmostEqual(r["abs_deviation_pct"], abs(r["peg_deviation_pct"]), places=8)

    def test_on_peg_label(self):
        r = self._call(wrapped_price_usd=3200.0, underlying_price_usd=3200.0)
        self.assertEqual(r["peg_label"], "ON_PEG")

    def test_slight_deviation_label(self):
        """0.2% deviation → SLIGHT_DEVIATION."""
        r = self._call(
            wrapped_price_usd=3200.0 * (1 - 0.002),
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
        )
        self.assertEqual(r["peg_label"], "SLIGHT_DEVIATION")

    def test_moderate_depeg_label(self):
        """1% deviation → MODERATE_DEPEG."""
        r = self._call(
            wrapped_price_usd=3200.0 * (1 - 0.01),
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
        )
        self.assertEqual(r["peg_label"], "MODERATE_DEPEG")

    def test_severe_depeg_label(self):
        """3% deviation → SEVERE_DEPEG."""
        r = self._call(
            wrapped_price_usd=3200.0 * (1 - 0.03),
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
        )
        self.assertEqual(r["peg_label"], "SEVERE_DEPEG")

    def test_critical_depeg_label(self):
        """10% deviation → CRITICAL_DEPEG."""
        r = self._call(
            wrapped_price_usd=3200.0 * (1 - 0.10),
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
        )
        self.assertEqual(r["peg_label"], "CRITICAL_DEPEG")

    def test_peg_risk_score_int(self):
        self.assertIsInstance(self._call()["peg_risk_score"], int)

    def test_peg_risk_score_range(self):
        r = self._call()
        self.assertGreaterEqual(r["peg_risk_score"], 0)
        self.assertLessEqual(r["peg_risk_score"], 100)

    def test_redemption_pressure_ratio_in_result(self):
        r = self._call(daily_redemption_volume_usd=1_000_000_000, protocol_tvl_usd=10_000_000_000)
        self.assertAlmostEqual(r["redemption_pressure_ratio"], 0.1, places=8)

    def test_all_output_keys_present(self):
        r = self._call()
        for key in [
            "observed_ratio", "peg_deviation_pct", "abs_deviation_pct",
            "redemption_pressure_ratio", "peg_risk_score", "peg_label",
        ]:
            self.assertIn(key, r, f"Missing output key: {key}")

    def test_wsteth_expected_ratio_above_one(self):
        """wstETH with expected ratio 1.15 at peg."""
        r = self._call(
            wrapped_price_usd=3680.0,
            underlying_price_usd=3200.0,
            expected_ratio=1.15,
            asset_name="wstETH",
        )
        self.assertAlmostEqual(r["observed_ratio"], 1.15, places=5)
        self.assertAlmostEqual(r["peg_deviation_pct"], 0.0, places=3)
        self.assertEqual(r["peg_label"], "ON_PEG")

    def test_cbeth_no_redemption_higher_risk(self):
        """cbETH with redemption disabled scores higher."""
        r_enabled = self._call(redemption_enabled=True, wrapped_price_usd=3200.0)
        r_disabled = self._call(redemption_enabled=False, wrapped_price_usd=3200.0)
        self.assertGreater(r_disabled["peg_risk_score"], r_enabled["peg_risk_score"])

    def test_raw_inputs_echoed(self):
        r = self._call(
            wrapped_price_usd=3100.0,
            underlying_price_usd=3200.0,
            expected_ratio=0.95,
        )
        self.assertAlmostEqual(r["wrapped_price_usd"], 3100.0, places=5)
        self.assertAlmostEqual(r["underlying_price_usd"], 3200.0, places=5)
        self.assertAlmostEqual(r["expected_ratio"], 0.95, places=8)


# ===========================================================================
# 8. DeFiProtocolWrappedAssetPegDeviationAnalyzer class
# ===========================================================================

class TestAnalyzerClass(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.analyzer = DeFiProtocolWrappedAssetPegDeviationAnalyzer(
            data_dir=self.tmp_dir
        )

    def _run_steth(self, **kw):
        defaults = dict(
            wrapped_price_usd=3198.0,
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
            redemption_enabled=True,
            protocol_tvl_usd=15_000_000_000,
            daily_redemption_volume_usd=50_000_000,
            asset_name="stETH",
            protocol_name="Lido",
        )
        defaults.update(kw)
        return self.analyzer.analyze(**defaults)

    def test_analyze_returns_dict(self):
        r = self._run_steth()
        self.assertIsInstance(r, dict)

    def test_get_last_result_before_analyze_is_none(self):
        fresh = DeFiProtocolWrappedAssetPegDeviationAnalyzer(data_dir=self.tmp_dir)
        self.assertIsNone(fresh.get_last_result())

    def test_get_last_result_after_analyze(self):
        r = self._run_steth()
        self.assertEqual(self.analyzer.get_last_result(), r)

    def test_save_before_analyze_returns_false(self):
        fresh = DeFiProtocolWrappedAssetPegDeviationAnalyzer(data_dir=self.tmp_dir)
        self.assertFalse(fresh.save())

    def test_save_creates_log_file(self):
        self._run_steth()
        self.analyzer.save()
        log_path = self.tmp_dir / LOG_FILENAME
        self.assertTrue(log_path.exists())

    def test_save_returns_true_on_success(self):
        self._run_steth()
        self.assertTrue(self.analyzer.save())

    def test_log_file_contains_list(self):
        self._run_steth()
        self.analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_file_has_one_entry_after_one_save(self):
        self._run_steth()
        self.analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_file_accumulates_entries(self):
        for _ in range(3):
            self._run_steth()
            self.analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_last_result_updated_on_second_call(self):
        self._run_steth(asset_name="stETH")
        r2 = self._run_steth(asset_name="wstETH")
        self.assertEqual(self.analyzer.get_last_result()["asset_name"], "wstETH")
        self.assertEqual(r2["asset_name"], "wstETH")

    def test_ring_buffer_cap_enforced(self):
        for i in range(RING_BUFFER_CAP + 5):
            self._run_steth()
            self.analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertEqual(len(data), RING_BUFFER_CAP)

    def test_custom_ring_cap(self):
        small_analyzer = DeFiProtocolWrappedAssetPegDeviationAnalyzer(
            data_dir=self.tmp_dir, ring_cap=3
        )
        for i in range(5):
            small_analyzer.analyze(
                wrapped_price_usd=3200.0, underlying_price_usd=3200.0,
                expected_ratio=1.0, redemption_enabled=True,
                protocol_tvl_usd=1e9, daily_redemption_volume_usd=1e6,
                asset_name="X", protocol_name="P",
            )
            small_analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 3)

    def test_save_log_is_valid_json(self):
        self._run_steth()
        self.analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_peg_label(self):
        self._run_steth()
        self.analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertIn("peg_label", data[0])

    def test_log_entry_has_peg_risk_score(self):
        self._run_steth()
        self.analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertIn("peg_risk_score", data[0])


# ===========================================================================
# 9. I/O helpers — _load_json_list and _atomic_write
# ===========================================================================

class TestIOHelpers(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def test_load_nonexistent_returns_empty_list(self):
        result = _load_json_list(self.tmp_dir / "no_such_file.json")
        self.assertEqual(result, [])

    def test_load_valid_list(self):
        p = self.tmp_dir / "test.json"
        p.write_text(json.dumps([{"a": 1}, {"b": 2}]))
        self.assertEqual(_load_json_list(p), [{"a": 1}, {"b": 2}])

    def test_load_non_list_returns_empty(self):
        p = self.tmp_dir / "dict.json"
        p.write_text(json.dumps({"key": "value"}))
        self.assertEqual(_load_json_list(p), [])

    def test_load_malformed_json_returns_empty(self):
        p = self.tmp_dir / "bad.json"
        p.write_text("{not valid json")
        self.assertEqual(_load_json_list(p), [])

    def test_atomic_write_creates_file(self):
        p = self.tmp_dir / "out.json"
        _atomic_write(p, [{"x": 1}])
        self.assertTrue(p.exists())

    def test_atomic_write_content_correct(self):
        p = self.tmp_dir / "out.json"
        data = [{"key": "value", "num": 42}]
        _atomic_write(p, data)
        loaded = json.loads(p.read_text())
        self.assertEqual(loaded, data)

    def test_atomic_write_no_tmp_leftover(self):
        p = self.tmp_dir / "out.json"
        _atomic_write(p, [1, 2, 3])
        tmp_files = list(self.tmp_dir.glob("*.tmp"))
        self.assertEqual(tmp_files, [])

    def test_atomic_write_creates_parent_dirs(self):
        nested = self.tmp_dir / "sub" / "dir" / "out.json"
        _atomic_write(nested, [])
        self.assertTrue(nested.exists())


# ===========================================================================
# 10. Ring-buffer behaviour
# ===========================================================================

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def test_ring_buffer_cap_constant(self):
        self.assertEqual(RING_BUFFER_CAP, 100)

    def test_entries_below_cap_all_kept(self):
        analyzer = DeFiProtocolWrappedAssetPegDeviationAnalyzer(data_dir=self.tmp_dir)
        for i in range(50):
            analyzer.analyze(
                wrapped_price_usd=3200.0, underlying_price_usd=3200.0,
                expected_ratio=1.0, redemption_enabled=True,
                protocol_tvl_usd=1e9, daily_redemption_volume_usd=1e6,
                asset_name=f"A{i}", protocol_name="P",
            )
            analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertEqual(len(data), 50)

    def test_ring_buffer_retains_most_recent(self):
        """After overflow, last entries are retained (not first)."""
        cap = 5
        analyzer = DeFiProtocolWrappedAssetPegDeviationAnalyzer(
            data_dir=self.tmp_dir, ring_cap=cap
        )
        for i in range(cap + 3):
            analyzer.analyze(
                wrapped_price_usd=float(3000 + i),
                underlying_price_usd=3200.0,
                expected_ratio=1.0,
                redemption_enabled=True,
                protocol_tvl_usd=1e9,
                daily_redemption_volume_usd=1e6,
                asset_name=f"A{i}",
                protocol_name="P",
            )
            analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertEqual(len(data), cap)
        # Last entry should be the most recently saved one
        self.assertEqual(data[-1]["asset_name"], f"A{cap + 2}")

    def test_empty_log_file_loads_as_empty_list(self):
        log_path = self.tmp_dir / LOG_FILENAME
        log_path.write_text("[]")
        self.assertEqual(_load_json_list(log_path), [])

    def test_ring_buffer_overflow_exact(self):
        """Exactly cap+1 saves should yield exactly cap entries."""
        cap = 10
        analyzer = DeFiProtocolWrappedAssetPegDeviationAnalyzer(
            data_dir=self.tmp_dir, ring_cap=cap
        )
        for i in range(cap + 1):
            analyzer.analyze(
                wrapped_price_usd=3200.0, underlying_price_usd=3200.0,
                expected_ratio=1.0, redemption_enabled=True,
                protocol_tvl_usd=1e9, daily_redemption_volume_usd=0,
                asset_name="X", protocol_name="P",
            )
            analyzer.save()
        with open(self.tmp_dir / LOG_FILENAME) as f:
            data = json.load(f)
        self.assertEqual(len(data), cap)


# ===========================================================================
# 11. Constants and module metadata
# ===========================================================================

class TestConstantsAndMetadata(unittest.TestCase):

    def test_log_filename(self):
        self.assertEqual(LOG_FILENAME, "wrapped_asset_peg_deviation_log.json")

    def test_ring_buffer_cap(self):
        self.assertEqual(RING_BUFFER_CAP, 100)

    def test_schema_version(self):
        self.assertIsInstance(SCHEMA_VERSION, int)
        self.assertGreaterEqual(SCHEMA_VERSION, 1)

    def test_source_name(self):
        self.assertEqual(SOURCE_NAME, "defi_protocol_wrapped_asset_peg_deviation_analyzer")

    def test_mp_tag(self):
        self.assertEqual(MP_TAG, "MP-1092")

    def test_label_thresholds_ordering(self):
        self.assertLess(LABEL_ON_PEG_MAX, LABEL_SLIGHT_MAX)
        self.assertLess(LABEL_SLIGHT_MAX, LABEL_MODERATE_MAX)
        self.assertLess(LABEL_MODERATE_MAX, LABEL_SEVERE_MAX)

    def test_score_boundary_ordering(self):
        self.assertLess(SCORE_AT_ON_PEG_MAX, SCORE_AT_SLIGHT_MAX)
        self.assertLess(SCORE_AT_SLIGHT_MAX, SCORE_AT_MODERATE_MAX)
        self.assertLess(SCORE_AT_MODERATE_MAX, SCORE_AT_SEVERE_MAX)
        self.assertLess(SCORE_AT_SEVERE_MAX, SCORE_MAX)

    def test_redemption_pressure_thresholds(self):
        self.assertLess(REDEMPTION_PRESSURE_MED, REDEMPTION_PRESSURE_HIGH)
        self.assertGreater(REDEMPTION_PRESSURE_MED, 0)


# ===========================================================================
# 12. Edge cases and real-world scenarios
# ===========================================================================

class TestEdgeCasesAndRealWorld(unittest.TestCase):

    def test_usdc_usdt_peg(self):
        """USDC vs USDT near parity."""
        r = analyze(
            wrapped_price_usd=0.9998,
            underlying_price_usd=1.0,
            expected_ratio=1.0,
            redemption_enabled=True,
            protocol_tvl_usd=50_000_000_000,
            daily_redemption_volume_usd=1_000_000_000,
            asset_name="USDC",
            protocol_name="Circle",
        )
        self.assertEqual(r["peg_label"], "ON_PEG")
        self.assertAlmostEqual(r["abs_deviation_pct"], 0.02, places=4)

    def test_reth_slight_premium(self):
        """rETH trades at slight premium during validator queue."""
        r = analyze(
            wrapped_price_usd=3216.0,
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
            redemption_enabled=True,
            protocol_tvl_usd=3_000_000_000,
            daily_redemption_volume_usd=10_000_000,
            asset_name="rETH",
            protocol_name="RocketPool",
        )
        self.assertEqual(r["peg_label"], "SLIGHT_DEVIATION")

    def test_depeg_event_critical(self):
        """Simulate stETH March 2023 style depeg ~8%."""
        r = analyze(
            wrapped_price_usd=2944.0,
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
            redemption_enabled=False,
            protocol_tvl_usd=15_000_000_000,
            daily_redemption_volume_usd=2_000_000_000,
            asset_name="stETH",
            protocol_name="Lido",
        )
        self.assertEqual(r["peg_label"], "CRITICAL_DEPEG")
        self.assertEqual(r["peg_risk_score"], 100)

    def test_zero_tvl_no_crash(self):
        """TVL = 0 should not crash."""
        r = analyze(
            wrapped_price_usd=3200.0,
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
            redemption_enabled=True,
            protocol_tvl_usd=0,
            daily_redemption_volume_usd=0,
            asset_name="X",
            protocol_name="P",
        )
        self.assertAlmostEqual(r["redemption_pressure_ratio"], 0.0, places=8)

    def test_very_large_tvl(self):
        """Very large TVL produces small pressure ratio."""
        r = analyze(
            wrapped_price_usd=3200.0,
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
            redemption_enabled=True,
            protocol_tvl_usd=1e18,
            daily_redemption_volume_usd=1e6,
            asset_name="X",
            protocol_name="P",
        )
        self.assertLess(r["redemption_pressure_ratio"], 1e-9)

    def test_peg_deviation_pct_is_signed(self):
        """Negative peg_deviation_pct when wrapped trades below expected."""
        r = analyze(
            wrapped_price_usd=3100.0,
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
            redemption_enabled=True,
            protocol_tvl_usd=1e9,
            daily_redemption_volume_usd=0,
            asset_name="stETH",
            protocol_name="Lido",
        )
        self.assertLess(r["peg_deviation_pct"], 0.0)

    def test_output_values_are_numeric(self):
        r = analyze(
            wrapped_price_usd=3198.0,
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
            redemption_enabled=True,
            protocol_tvl_usd=15e9,
            daily_redemption_volume_usd=50e6,
            asset_name="stETH",
            protocol_name="Lido",
        )
        self.assertIsInstance(r["observed_ratio"], float)
        self.assertIsInstance(r["peg_deviation_pct"], float)
        self.assertIsInstance(r["abs_deviation_pct"], float)
        self.assertIsInstance(r["redemption_pressure_ratio"], float)
        self.assertIsInstance(r["peg_risk_score"], int)
        self.assertIsInstance(r["peg_label"], str)

    def test_positive_peg_deviation(self):
        """Wrapped trading above expected -> positive deviation."""
        r = analyze(
            wrapped_price_usd=3300.0,
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
            redemption_enabled=True,
            protocol_tvl_usd=1e9,
            daily_redemption_volume_usd=0,
            asset_name="rETH",
            protocol_name="RocketPool",
        )
        self.assertGreater(r["peg_deviation_pct"], 0.0)

    def test_boolean_redemption_enabled_in_output(self):
        r = analyze(
            wrapped_price_usd=3200.0,
            underlying_price_usd=3200.0,
            expected_ratio=1.0,
            redemption_enabled=True,
            protocol_tvl_usd=1e9,
            daily_redemption_volume_usd=0,
            asset_name="X",
            protocol_name="P",
        )
        self.assertIs(r["redemption_enabled"], True)


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
