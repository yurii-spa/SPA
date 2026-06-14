#!/usr/bin/env python3
"""Unit tests for MP-1045 ProtocolDeFiLPFeeVsILBreakevenAnalyzer (SPA-V760).

Run:
    python3 -m unittest spa_core/tests/test_protocol_defi_lp_fee_vs_il_breakeven_analyzer.py -v

All tests use stdlib unittest only — no pytest, no numpy.
"""
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.protocol_defi_lp_fee_vs_il_breakeven_analyzer import (
    ProtocolDeFiLPFeeVsILBreakevenAnalyzer,
    _compute_impermanent_loss_pct,
    _compute_daily_fee_rate_pct,
    _compute_fee_income_pct,
    _compute_breakeven_days,
    _label,
    _annualized_fee_apy_pct,
    _expected_il_from_volatility,
    _analyze_single,
    _load_json_list,
    _atomic_write,
    analyze_lp,
    LOG_FILENAME,
    RING_BUFFER_CAP,
    NET_FEE_DOMINANT,
    NET_BREAKEVEN_BAND,
    NET_IL_FUTILE,
    MP_TAG,
    SOURCE_NAME,
    SCHEMA_VERSION,
)


# ===========================================================================
# 1. _compute_impermanent_loss_pct
# ===========================================================================

class TestComputeImpermanentLossPct(unittest.TestCase):

    def test_no_price_change_zero_il(self):
        il = _compute_impermanent_loss_pct(1.0, 1.0)
        self.assertAlmostEqual(il, 0.0, places=8)

    def test_price_doubled_known_il(self):
        # k=2 → IL = 2*sqrt(2)/3 - 1 ≈ -5.7191%
        il = _compute_impermanent_loss_pct(1.0, 2.0)
        expected = (2.0 * math.sqrt(2.0) / 3.0 - 1.0) * 100.0
        self.assertAlmostEqual(il, expected, places=4)

    def test_price_halved_same_il_as_doubled(self):
        # IL is symmetric: k=0.5 and k=2 give same |IL|
        il_up = _compute_impermanent_loss_pct(1.0, 2.0)
        il_down = _compute_impermanent_loss_pct(1.0, 0.5)
        self.assertAlmostEqual(abs(il_up), abs(il_down), places=4)

    def test_il_always_non_positive(self):
        for ratio in [0.5, 0.75, 1.0, 1.5, 2.0, 4.0, 10.0]:
            il = _compute_impermanent_loss_pct(1.0, ratio)
            self.assertLessEqual(il, 0.0)

    def test_initial_zero_returns_zero(self):
        il = _compute_impermanent_loss_pct(0.0, 1.0)
        self.assertAlmostEqual(il, 0.0, places=8)

    def test_current_zero_returns_zero(self):
        il = _compute_impermanent_loss_pct(1.0, 0.0)
        self.assertAlmostEqual(il, 0.0, places=8)

    def test_both_zero_returns_zero(self):
        il = _compute_impermanent_loss_pct(0.0, 0.0)
        self.assertAlmostEqual(il, 0.0, places=8)

    def test_price_quadrupled(self):
        # k=4 → IL = 2*sqrt(4)/5 - 1 = 4/5-1 = -0.2 = -20%
        il = _compute_impermanent_loss_pct(1.0, 4.0)
        self.assertAlmostEqual(il, -20.0, places=4)

    def test_arbitrary_initial_price(self):
        # Should only depend on the ratio
        il1 = _compute_impermanent_loss_pct(100.0, 200.0)  # k=2
        il2 = _compute_impermanent_loss_pct(2000.0, 4000.0)  # k=2
        self.assertAlmostEqual(il1, il2, places=6)

    def test_il_approaches_minus100_for_large_k(self):
        # For very large k, IL → -100%
        il = _compute_impermanent_loss_pct(1.0, 1_000_000.0)
        self.assertLess(il, -99.0)

    def test_il_negative_for_price_drop(self):
        il = _compute_impermanent_loss_pct(1.0, 0.25)
        self.assertLess(il, 0.0)

    def test_il_for_k_09(self):
        # k=0.9 → IL = 2*sqrt(0.9)/1.9 - 1
        k = 0.9
        il = _compute_impermanent_loss_pct(1.0, 0.9)
        expected = (2.0 * math.sqrt(k) / (1.0 + k) - 1.0) * 100.0
        self.assertAlmostEqual(il, expected, places=6)

    def test_negative_prices_return_zero(self):
        il = _compute_impermanent_loss_pct(-1.0, 2.0)
        self.assertAlmostEqual(il, 0.0, places=8)


# ===========================================================================
# 2. _compute_daily_fee_rate_pct
# ===========================================================================

class TestComputeDailyFeeRatePct(unittest.TestCase):

    def test_standard_uniswap_v2_fee(self):
        # 30bps, 10% daily volume/tvl → 0.3% * 10% = 0.03%/day
        rate = _compute_daily_fee_rate_pct(30, 0.10)
        self.assertAlmostEqual(rate, 0.03, places=8)

    def test_zero_fee_bps(self):
        rate = _compute_daily_fee_rate_pct(0, 0.10)
        self.assertAlmostEqual(rate, 0.0, places=8)

    def test_zero_volume_ratio(self):
        rate = _compute_daily_fee_rate_pct(30, 0.0)
        self.assertAlmostEqual(rate, 0.0, places=8)

    def test_5bps_tier(self):
        # 5bps, 20% daily vol/tvl → 0.05% * 20% = 0.01%/day
        rate = _compute_daily_fee_rate_pct(5, 0.20)
        self.assertAlmostEqual(rate, 0.01, places=8)

    def test_100bps_tier(self):
        rate = _compute_daily_fee_rate_pct(100, 0.10)
        self.assertAlmostEqual(rate, 0.10, places=8)

    def test_negative_bps_returns_zero(self):
        rate = _compute_daily_fee_rate_pct(-10, 0.10)
        self.assertAlmostEqual(rate, 0.0, places=8)

    def test_negative_vol_ratio_returns_zero(self):
        rate = _compute_daily_fee_rate_pct(30, -0.5)
        self.assertAlmostEqual(rate, 0.0, places=8)

    def test_high_volume_pool(self):
        # 30bps, 100% daily vol/tvl (1x turnover/day)
        rate = _compute_daily_fee_rate_pct(30, 1.0)
        self.assertAlmostEqual(rate, 0.30, places=8)

    def test_rate_scales_with_bps(self):
        rate1 = _compute_daily_fee_rate_pct(30, 0.10)
        rate2 = _compute_daily_fee_rate_pct(60, 0.10)
        self.assertAlmostEqual(rate2, 2.0 * rate1, places=8)

    def test_rate_scales_with_volume(self):
        rate1 = _compute_daily_fee_rate_pct(30, 0.10)
        rate2 = _compute_daily_fee_rate_pct(30, 0.20)
        self.assertAlmostEqual(rate2, 2.0 * rate1, places=8)


# ===========================================================================
# 3. _compute_fee_income_pct
# ===========================================================================

class TestComputeFeeIncomePct(unittest.TestCase):

    def test_zero_days(self):
        income = _compute_fee_income_pct(0.03, 0.0)
        self.assertAlmostEqual(income, 0.0, places=8)

    def test_negative_days(self):
        income = _compute_fee_income_pct(0.03, -10.0)
        self.assertAlmostEqual(income, 0.0, places=8)

    def test_30_days(self):
        income = _compute_fee_income_pct(0.03, 30.0)
        self.assertAlmostEqual(income, 0.9, places=8)

    def test_365_days(self):
        income = _compute_fee_income_pct(0.03, 365.0)
        self.assertAlmostEqual(income, 10.95, places=6)

    def test_linear_accumulation(self):
        income_30 = _compute_fee_income_pct(0.05, 30.0)
        income_60 = _compute_fee_income_pct(0.05, 60.0)
        self.assertAlmostEqual(income_60, 2.0 * income_30, places=8)

    def test_zero_rate(self):
        income = _compute_fee_income_pct(0.0, 100.0)
        self.assertAlmostEqual(income, 0.0, places=8)

    def test_one_day(self):
        income = _compute_fee_income_pct(0.03, 1.0)
        self.assertAlmostEqual(income, 0.03, places=8)


# ===========================================================================
# 4. _compute_breakeven_days
# ===========================================================================

class TestComputeBreakevenDays(unittest.TestCase):

    def test_no_il_returns_zero(self):
        days = _compute_breakeven_days(0.0, 0.03)
        self.assertEqual(days, 0.0)

    def test_positive_il_returns_zero(self):
        days = _compute_breakeven_days(1.0, 0.03)
        self.assertEqual(days, 0.0)

    def test_il_but_no_fee_returns_none(self):
        days = _compute_breakeven_days(-5.0, 0.0)
        self.assertIsNone(days)

    def test_basic_breakeven(self):
        # IL = -5%, fee rate = 0.03%/day → breakeven = 5/0.03 ≈ 166.67 days
        days = _compute_breakeven_days(-5.0, 0.03)
        self.assertAlmostEqual(days, 5.0 / 0.03, places=2)

    def test_higher_fee_rate_fewer_days(self):
        days_slow = _compute_breakeven_days(-5.0, 0.01)
        days_fast = _compute_breakeven_days(-5.0, 0.05)
        self.assertGreater(days_slow, days_fast)

    def test_larger_il_more_days(self):
        days_small = _compute_breakeven_days(-2.0, 0.03)
        days_large = _compute_breakeven_days(-10.0, 0.03)
        self.assertGreater(days_large, days_small)

    def test_result_positive(self):
        days = _compute_breakeven_days(-5.7, 0.03)
        self.assertIsNotNone(days)
        self.assertGreater(days, 0.0)

    def test_negative_fee_rate_returns_none(self):
        days = _compute_breakeven_days(-5.0, -0.01)
        self.assertIsNone(days)


# ===========================================================================
# 5. _label
# ===========================================================================

class TestLabel(unittest.TestCase):

    def test_fee_dominant_high(self):
        self.assertEqual(_label(10.0), "FEE_DOMINANT")

    def test_fee_dominant_just_above(self):
        self.assertEqual(_label(2.01), "FEE_DOMINANT")

    def test_profitable_just_above_breakeven(self):
        self.assertEqual(_label(0.6), "PROFITABLE")

    def test_profitable_at_two(self):
        # 2.0 is not > NET_FEE_DOMINANT(2.0) → PROFITABLE (boundary exclusive)
        self.assertEqual(_label(2.0), "PROFITABLE")

    def test_breakeven_at_zero(self):
        self.assertEqual(_label(0.0), "BREAKEVEN")

    def test_breakeven_slightly_positive(self):
        # 0.4 is within ±0.5 band → BREAKEVEN
        self.assertEqual(_label(0.4), "BREAKEVEN")

    def test_breakeven_slightly_negative(self):
        self.assertEqual(_label(-0.4), "BREAKEVEN")

    def test_breakeven_at_lower_band(self):
        self.assertEqual(_label(-0.5), "BREAKEVEN")

    def test_il_dominant_just_below_breakeven(self):
        self.assertEqual(_label(-0.51), "IL_DOMINANT")

    def test_il_dominant_moderate(self):
        self.assertEqual(_label(-5.0), "IL_DOMINANT")

    def test_il_dominant_just_above_futile(self):
        self.assertEqual(_label(-9.99), "IL_DOMINANT")

    def test_fee_futile_at_threshold(self):
        self.assertEqual(_label(-10.0), "FEE_FUTILE")

    def test_fee_futile_severe(self):
        self.assertEqual(_label(-50.0), "FEE_FUTILE")


# ===========================================================================
# 6. _annualized_fee_apy_pct
# ===========================================================================

class TestAnnualizedFeeApy(unittest.TestCase):

    def test_daily_003_annualized(self):
        # 0.03%/day * 365 = 10.95%
        apy = _annualized_fee_apy_pct(0.03)
        self.assertAlmostEqual(apy, 10.95, places=4)

    def test_zero_rate(self):
        apy = _annualized_fee_apy_pct(0.0)
        self.assertAlmostEqual(apy, 0.0, places=4)

    def test_higher_rate_higher_apy(self):
        apy1 = _annualized_fee_apy_pct(0.03)
        apy2 = _annualized_fee_apy_pct(0.06)
        self.assertAlmostEqual(apy2, 2.0 * apy1, places=4)


# ===========================================================================
# 7. _expected_il_from_volatility
# ===========================================================================

class TestExpectedILFromVolatility(unittest.TestCase):

    def test_zero_volatility(self):
        il = _expected_il_from_volatility(0.0, 30.0)
        self.assertAlmostEqual(il, 0.0, places=8)

    def test_zero_days(self):
        il = _expected_il_from_volatility(80.0, 0.0)
        self.assertAlmostEqual(il, 0.0, places=8)

    def test_expected_il_non_positive(self):
        il = _expected_il_from_volatility(80.0, 30.0)
        self.assertLessEqual(il, 0.0)

    def test_higher_vol_more_negative_il(self):
        il_low = _expected_il_from_volatility(20.0, 30.0)
        il_high = _expected_il_from_volatility(80.0, 30.0)
        self.assertLess(il_high, il_low)

    def test_longer_time_more_negative_il(self):
        il_short = _expected_il_from_volatility(80.0, 10.0)
        il_long = _expected_il_from_volatility(80.0, 100.0)
        self.assertLess(il_long, il_short)

    def test_returns_float(self):
        il = _expected_il_from_volatility(50.0, 30.0)
        self.assertIsInstance(il, float)


# ===========================================================================
# 8. _analyze_single
# ===========================================================================

class TestAnalyzeSingle(unittest.TestCase):

    def _default_params(self, **overrides):
        params = dict(
            initial_price_ratio=1.0,
            current_price_ratio=1.0,
            fee_tier_bps=30,
            daily_volume_to_tvl_ratio=0.10,
            days_in_position=30,
            volatility_30d_pct=50.0,
            position_size_usd=10_000,
        )
        params.update(overrides)
        return params

    def test_returns_dict(self):
        result = _analyze_single(**self._default_params())
        self.assertIsInstance(result, dict)

    def test_no_price_change_zero_il(self):
        result = _analyze_single(**self._default_params())
        self.assertAlmostEqual(result["impermanent_loss_pct"], 0.0, places=6)

    def test_breakeven_zero_when_no_il(self):
        result = _analyze_single(**self._default_params())
        self.assertAlmostEqual(result["breakeven_days"], 0.0, places=4)

    def test_fee_income_positive_when_volume_positive(self):
        result = _analyze_single(**self._default_params())
        self.assertGreater(result["fee_income_pct"], 0.0)

    def test_net_pnl_equals_fee_minus_il(self):
        result = _analyze_single(**self._default_params(current_price_ratio=2.0))
        expected_net = result["fee_income_pct"] + result["impermanent_loss_pct"]
        self.assertAlmostEqual(result["net_lp_pnl_pct"], expected_net, places=5)

    def test_label_breakeven_no_price_change(self):
        # No IL, small fees → PROFITABLE or FEE_DOMINANT
        result = _analyze_single(**self._default_params())
        self.assertIn(result["label"], ("PROFITABLE", "FEE_DOMINANT", "BREAKEVEN"))

    def test_label_il_dominant_large_price_move(self):
        result = _analyze_single(**self._default_params(
            current_price_ratio=4.0,
            days_in_position=10,
            fee_tier_bps=5,
            daily_volume_to_tvl_ratio=0.01,
        ))
        self.assertIn(result["label"], ("IL_DOMINANT", "FEE_FUTILE"))

    def test_label_fee_dominant_many_days(self):
        result = _analyze_single(**self._default_params(
            current_price_ratio=1.1,
            days_in_position=365,
            fee_tier_bps=100,
            daily_volume_to_tvl_ratio=0.5,
        ))
        self.assertEqual(result["label"], "FEE_DOMINANT")

    def test_impermanent_loss_pct_in_result(self):
        result = _analyze_single(**self._default_params())
        self.assertIn("impermanent_loss_pct", result)

    def test_fee_income_pct_in_result(self):
        result = _analyze_single(**self._default_params())
        self.assertIn("fee_income_pct", result)

    def test_net_lp_pnl_pct_in_result(self):
        result = _analyze_single(**self._default_params())
        self.assertIn("net_lp_pnl_pct", result)

    def test_breakeven_days_in_result(self):
        result = _analyze_single(**self._default_params())
        self.assertIn("breakeven_days", result)

    def test_label_in_result(self):
        result = _analyze_single(**self._default_params())
        self.assertIn("label", result)

    def test_warnings_is_list(self):
        result = _analyze_single(**self._default_params())
        self.assertIsInstance(result["warnings"], list)

    def test_il_usd_when_position_size_positive(self):
        result = _analyze_single(**self._default_params(
            current_price_ratio=2.0,
            position_size_usd=10_000
        ))
        self.assertIsNotNone(result["impermanent_loss_usd"])
        self.assertLess(result["impermanent_loss_usd"], 0.0)

    def test_fee_usd_when_position_size_positive(self):
        result = _analyze_single(**self._default_params())
        self.assertIsNotNone(result["fee_income_usd"])
        self.assertGreater(result["fee_income_usd"], 0.0)

    def test_net_usd_when_position_size_positive(self):
        result = _analyze_single(**self._default_params())
        self.assertIsNotNone(result["net_lp_pnl_usd"])

    def test_no_position_size_usd_null(self):
        result = _analyze_single(**self._default_params(position_size_usd=0.0))
        self.assertIsNone(result["impermanent_loss_usd"])
        self.assertIsNone(result["fee_income_usd"])
        self.assertIsNone(result["net_lp_pnl_usd"])

    def test_annualized_fee_apy_in_result(self):
        result = _analyze_single(**self._default_params())
        self.assertIn("annualized_fee_apy_pct", result)
        self.assertGreater(result["annualized_fee_apy_pct"], 0.0)

    def test_already_broken_even_when_no_il(self):
        result = _analyze_single(**self._default_params())
        self.assertTrue(result["already_broken_even"])

    def test_price_change_factor_k(self):
        result = _analyze_single(**self._default_params(
            initial_price_ratio=1000.0,
            current_price_ratio=2000.0,
        ))
        self.assertAlmostEqual(result["price_change_factor_k"], 2.0, places=6)

    def test_zero_initial_price_ratio_warning(self):
        result = _analyze_single(**self._default_params(initial_price_ratio=0.0))
        self.assertTrue(any("initial" in w.lower() for w in result["warnings"]))

    def test_expected_il_from_vol_in_result(self):
        result = _analyze_single(**self._default_params())
        self.assertIn("expected_il_from_vol_pct", result)


# ===========================================================================
# 9. ProtocolDeFiLPFeeVsILBreakevenAnalyzer class
# ===========================================================================

class TestAnalyzerClass(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiLPFeeVsILBreakevenAnalyzer(data_dir=self.tmp_dir)

    def _call_analyze(self, **overrides):
        params = dict(
            initial_price_ratio=1.0,
            current_price_ratio=1.5,
            fee_tier_bps=30,
            daily_volume_to_tvl_ratio=0.10,
            days_in_position=60,
            volatility_30d_pct=80.0,
            position_size_usd=50_000,
        )
        params.update(overrides)
        return self.analyzer.analyze(**params)

    def test_analyze_returns_dict(self):
        result = self._call_analyze()
        self.assertIsInstance(result, dict)

    def test_schema_version_present(self):
        result = self._call_analyze()
        self.assertEqual(result["schema_version"], SCHEMA_VERSION)

    def test_source_present(self):
        result = self._call_analyze()
        self.assertEqual(result["source"], SOURCE_NAME)

    def test_mp_tag_present(self):
        result = self._call_analyze()
        self.assertEqual(result["mp_tag"], MP_TAG)

    def test_timestamp_present(self):
        result = self._call_analyze()
        self.assertIn("timestamp", result)

    def test_label_is_string(self):
        result = self._call_analyze()
        self.assertIsInstance(result["label"], str)

    def test_valid_label_values(self):
        valid = {"FEE_DOMINANT", "PROFITABLE", "BREAKEVEN", "IL_DOMINANT", "FEE_FUTILE"}
        result = self._call_analyze()
        self.assertIn(result["label"], valid)

    def test_get_label_after_analyze(self):
        self._call_analyze()
        self.assertIsNotNone(self.analyzer.get_label())

    def test_get_label_before_analyze_is_none(self):
        fresh = ProtocolDeFiLPFeeVsILBreakevenAnalyzer(data_dir=self.tmp_dir)
        self.assertIsNone(fresh.get_label())

    def test_is_il_dominant_safe_case(self):
        # No price change → breakeven or profitable
        self._call_analyze(current_price_ratio=1.0, days_in_position=30)
        self.assertFalse(self.analyzer.is_il_dominant())

    def test_is_il_dominant_stressed_case(self):
        # Large price move, low fee, few days
        self._call_analyze(
            current_price_ratio=5.0,
            days_in_position=5,
            fee_tier_bps=5,
            daily_volume_to_tvl_ratio=0.01,
        )
        self.assertTrue(self.analyzer.is_il_dominant())

    def test_save_creates_log_file(self):
        self._call_analyze()
        ok = self.analyzer.save()
        self.assertTrue(ok)
        log_path = Path(self.tmp_dir) / LOG_FILENAME
        self.assertTrue(log_path.exists())

    def test_save_before_analyze_returns_false(self):
        fresh = ProtocolDeFiLPFeeVsILBreakevenAnalyzer(data_dir=self.tmp_dir)
        ok = fresh.save()
        self.assertFalse(ok)

    def test_save_appends_entries(self):
        self._call_analyze()
        self.analyzer.save()
        self._call_analyze(current_price_ratio=2.0)
        self.analyzer.save()
        log_path = Path(self.tmp_dir) / LOG_FILENAME
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        cap = 5
        small = ProtocolDeFiLPFeeVsILBreakevenAnalyzer(
            data_dir=self.tmp_dir, ring_cap=cap
        )
        for i in range(8):
            small.analyze(
                initial_price_ratio=1.0,
                current_price_ratio=1.0 + i * 0.1,
                fee_tier_bps=30,
                daily_volume_to_tvl_ratio=0.10,
                days_in_position=30,
                volatility_30d_pct=50.0,
                position_size_usd=10_000,
            )
            small.save()
        log_path = Path(self.tmp_dir) / LOG_FILENAME
        with open(log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), cap)

    def test_save_log_valid_json_list(self):
        self._call_analyze()
        self.analyzer.save()
        log_path = Path(self.tmp_dir) / LOG_FILENAME
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


# ===========================================================================
# 10. analyze_batch
# ===========================================================================

class TestAnalyzeBatch(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiLPFeeVsILBreakevenAnalyzer(data_dir=self.tmp_dir)

    def _pos(self, curr_ratio, days=30, fee_bps=30, vol=0.10):
        return dict(
            initial_price_ratio=1.0,
            current_price_ratio=curr_ratio,
            fee_tier_bps=fee_bps,
            daily_volume_to_tvl_ratio=vol,
            days_in_position=days,
            volatility_30d_pct=50.0,
            position_size_usd=10_000,
        )

    def test_batch_returns_dict(self):
        result = self.analyzer.analyze_batch([self._pos(1.0), self._pos(2.0)])
        self.assertIsInstance(result, dict)

    def test_batch_position_count(self):
        result = self.analyzer.analyze_batch([self._pos(1.0), self._pos(1.5), self._pos(4.0)])
        self.assertEqual(result["position_count"], 3)

    def test_batch_il_dominated_count(self):
        result = self.analyzer.analyze_batch([
            self._pos(1.0, days=30),            # breakeven/profitable
            self._pos(4.0, days=5, fee_bps=5, vol=0.01),  # fee_futile or il_dominant
        ])
        self.assertGreater(result["il_dominated_count"], 0)

    def test_batch_label_counts_sum_to_position_count(self):
        positions = [self._pos(r) for r in [1.0, 1.5, 2.0]]
        result = self.analyzer.analyze_batch(positions)
        total = sum(result["label_counts"].values())
        self.assertEqual(total, 3)

    def test_batch_empty_list(self):
        result = self.analyzer.analyze_batch([])
        self.assertEqual(result["position_count"], 0)
        self.assertEqual(result["il_dominated_count"], 0)

    def test_batch_per_position_list(self):
        result = self.analyzer.analyze_batch([self._pos(1.0)])
        self.assertIsInstance(result["per_position"], list)
        self.assertEqual(len(result["per_position"]), 1)

    def test_batch_il_dominated_list(self):
        result = self.analyzer.analyze_batch([
            self._pos(1.0),
            self._pos(10.0, days=1, fee_bps=1, vol=0.001),
        ])
        dominated = result["il_dominated"]
        self.assertTrue(all(
            r.get("label") in ("IL_DOMINANT", "FEE_FUTILE") for r in dominated
        ))


# ===========================================================================
# 11. I/O helpers
# ===========================================================================

class TestIOHelpers(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def test_load_json_list_missing_file(self):
        path = self.tmp_dir / "nonexistent.json"
        result = _load_json_list(path)
        self.assertEqual(result, [])

    def test_load_json_list_valid(self):
        path = self.tmp_dir / "test.json"
        _atomic_write(path, [{"x": 1}, {"y": 2}])
        result = _load_json_list(path)
        self.assertEqual(len(result), 2)

    def test_load_json_list_non_list_returns_empty(self):
        path = self.tmp_dir / "obj.json"
        _atomic_write(path, {"key": "val"})
        result = _load_json_list(path)
        self.assertEqual(result, [])

    def test_load_json_list_corrupt(self):
        path = self.tmp_dir / "bad.json"
        path.write_text("{NOT JSON]", encoding="utf-8")
        result = _load_json_list(path)
        self.assertEqual(result, [])

    def test_atomic_write_creates_file(self):
        path = self.tmp_dir / "out.json"
        _atomic_write(path, [1, 2, 3])
        self.assertTrue(path.exists())

    def test_atomic_write_correct_content(self):
        path = self.tmp_dir / "out.json"
        data = [{"il": -5.7, "fees": 2.1}]
        _atomic_write(path, data)
        with open(path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_atomic_write_overwrites(self):
        path = self.tmp_dir / "out.json"
        _atomic_write(path, [1])
        _atomic_write(path, [2, 3])
        with open(path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, [2, 3])

    def test_atomic_write_no_tmp_leftover(self):
        path = self.tmp_dir / "out.json"
        _atomic_write(path, {"data": True})
        tmps = list(self.tmp_dir.glob("*.tmp"))
        self.assertEqual(len(tmps), 0)


# ===========================================================================
# 12. analyze_lp functional API
# ===========================================================================

class TestAnalyzeLPFunctional(unittest.TestCase):

    def test_returns_dict(self):
        result = analyze_lp(
            initial_price_ratio=1.0,
            current_price_ratio=1.5,
            fee_tier_bps=30,
            daily_volume_to_tvl_ratio=0.10,
            days_in_position=60,
            volatility_30d_pct=80.0,
            position_size_usd=50_000,
        )
        self.assertIsInstance(result, dict)

    def test_label_present(self):
        result = analyze_lp(
            initial_price_ratio=1.0,
            current_price_ratio=1.0,
            fee_tier_bps=30,
            daily_volume_to_tvl_ratio=0.10,
            days_in_position=30,
            volatility_30d_pct=50.0,
            position_size_usd=10_000,
        )
        self.assertIn("label", result)

    def test_stable_pair_profitable(self):
        result = analyze_lp(
            initial_price_ratio=1.0,
            current_price_ratio=1.0,
            fee_tier_bps=5,
            daily_volume_to_tvl_ratio=1.0,  # high volume stablecoin pair
            days_in_position=90,
            volatility_30d_pct=1.0,
            position_size_usd=100_000,
        )
        self.assertIn(result["label"], ("FEE_DOMINANT", "PROFITABLE"))


# ===========================================================================
# 13. Edge cases and special scenarios
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiLPFeeVsILBreakevenAnalyzer(data_dir=self.tmp_dir)

    def test_all_zeros(self):
        result = self.analyzer.analyze(
            initial_price_ratio=0.0,
            current_price_ratio=0.0,
            fee_tier_bps=0.0,
            daily_volume_to_tvl_ratio=0.0,
            days_in_position=0.0,
            volatility_30d_pct=0.0,
            position_size_usd=0.0,
        )
        self.assertIsInstance(result, dict)
        self.assertIn("label", result)

    def test_very_large_price_move(self):
        result = self.analyzer.analyze(
            initial_price_ratio=1.0,
            current_price_ratio=1_000_000.0,
            fee_tier_bps=30,
            daily_volume_to_tvl_ratio=0.10,
            days_in_position=30,
            volatility_30d_pct=200.0,
            position_size_usd=10_000,
        )
        # Very large price move → large IL → FEE_FUTILE or IL_DOMINANT
        self.assertIn(result["label"], ("FEE_FUTILE", "IL_DOMINANT"))
        self.assertLess(result["impermanent_loss_pct"], -90.0)

    def test_negative_days_in_position_clamped(self):
        result = self.analyzer.analyze(
            initial_price_ratio=1.0,
            current_price_ratio=1.5,
            fee_tier_bps=30,
            daily_volume_to_tvl_ratio=0.10,
            days_in_position=-10.0,
            volatility_30d_pct=50.0,
            position_size_usd=10_000,
        )
        self.assertAlmostEqual(result["fee_income_pct"], 0.0, places=6)

    def test_exact_breakeven(self):
        # Set up so current fee income exactly equals IL
        # IL at k=2 ≈ -5.7191%
        il = _compute_impermanent_loss_pct(1.0, 2.0)
        daily_fee = _compute_daily_fee_rate_pct(30, 0.10)
        if daily_fee > 0:
            days_needed = abs(il) / daily_fee
            result = self.analyzer.analyze(
                initial_price_ratio=1.0,
                current_price_ratio=2.0,
                fee_tier_bps=30,
                daily_volume_to_tvl_ratio=0.10,
                days_in_position=days_needed,
                volatility_30d_pct=80.0,
                position_size_usd=10_000,
            )
            self.assertAlmostEqual(result["net_lp_pnl_pct"], 0.0, places=4)

    def test_symmetric_il_for_price_up_and_down(self):
        r_up = self.analyzer.analyze(
            initial_price_ratio=1.0, current_price_ratio=2.0,
            fee_tier_bps=30, daily_volume_to_tvl_ratio=0.1,
            days_in_position=0, volatility_30d_pct=0, position_size_usd=0,
        )
        r_down = self.analyzer.analyze(
            initial_price_ratio=1.0, current_price_ratio=0.5,
            fee_tier_bps=30, daily_volume_to_tvl_ratio=0.1,
            days_in_position=0, volatility_30d_pct=0, position_size_usd=0,
        )
        self.assertAlmostEqual(
            abs(r_up["impermanent_loss_pct"]),
            abs(r_down["impermanent_loss_pct"]),
            places=4
        )

    def test_fee_none_returns_none_breakeven_for_il(self):
        result = self.analyzer.analyze(
            initial_price_ratio=1.0,
            current_price_ratio=2.0,
            fee_tier_bps=0,
            daily_volume_to_tvl_ratio=0.10,
            days_in_position=30,
            volatility_30d_pct=50.0,
            position_size_usd=10_000,
        )
        self.assertIsNone(result["breakeven_days"])

    def test_already_broken_even_field(self):
        result = self.analyzer.analyze(
            initial_price_ratio=1.0,
            current_price_ratio=1.0,
            fee_tier_bps=30,
            daily_volume_to_tvl_ratio=0.10,
            days_in_position=30,
            volatility_30d_pct=0.0,
            position_size_usd=10_000,
        )
        # No IL → already broken even
        self.assertTrue(result["already_broken_even"])


# ===========================================================================
# 14. Constants and schema
# ===========================================================================

class TestConstants(unittest.TestCase):

    def test_ring_buffer_cap(self):
        self.assertEqual(RING_BUFFER_CAP, 100)

    def test_mp_tag(self):
        self.assertEqual(MP_TAG, "MP-1045")

    def test_source_name(self):
        self.assertIn("lp", SOURCE_NAME.lower())

    def test_schema_version_positive(self):
        self.assertGreater(SCHEMA_VERSION, 0)

    def test_thresholds_ordering(self):
        self.assertGreater(NET_FEE_DOMINANT, 0.0)
        self.assertGreater(NET_BREAKEVEN_BAND, 0.0)
        self.assertLess(NET_IL_FUTILE, 0.0)

    def test_log_filename_json(self):
        self.assertTrue(LOG_FILENAME.endswith(".json"))
        self.assertIn("lp", LOG_FILENAME.lower())


if __name__ == "__main__":
    unittest.main()
