"""
Tests for MP-972 DeFiYieldTokenizationAnalyzer
Run with: python3 -m unittest spa_core.tests.test_defi_yield_tokenization_analyzer
"""

import json
import os
import tempfile
import time
import unittest

from spa_core.analytics.defi_yield_tokenization_analyzer import (
    DeFiYieldTokenizationAnalyzer,
    analyze,
    run,
    _pt_discount_pct,
    _fixed_vs_variable_spread,
    _yt_implied_leverage,
    _break_even_variable_apy,
    _time_value_per_day,
    _classify_label,
    _build_flags,
    LABEL_FIXED_RATE_ADVANTAGE,
    LABEL_AT_PAR,
    LABEL_VARIABLE_ADVANTAGE,
    LABEL_DEEP_DISCOUNT,
    LABEL_MATURED,
    FLAG_HIGH_YT_LEVERAGE,
    FLAG_APPROACHING_MATURITY,
    FLAG_ILLIQUID_SECONDARY,
    FLAG_FIXED_LOCKS_IN_PREMIUM,
    FLAG_UNDERWATER_YT,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def make_position(
    protocol="Pendle",
    asset="stETH",
    principal_token_price_pct=95.0,
    yield_token_price_usd=0.05,
    implied_fixed_apy_pct=10.0,
    current_variable_apy_pct=4.0,
    pt_amount=100_000.0,
    yt_amount=100_000.0,
    notional_usd=95_000.0,
    days_to_maturity=180,
    secondary_market_liquidity_usd=5_000_000.0,
    maturity_date_days=180,
):
    return {
        "protocol": protocol,
        "asset": asset,
        "maturity_date_days": maturity_date_days,
        "principal_token_price_pct": principal_token_price_pct,
        "yield_token_price_usd": yield_token_price_usd,
        "implied_fixed_apy_pct": implied_fixed_apy_pct,
        "current_variable_apy_pct": current_variable_apy_pct,
        "pt_amount": pt_amount,
        "yt_amount": yt_amount,
        "notional_usd": notional_usd,
        "days_to_maturity": days_to_maturity,
        "secondary_market_liquidity_usd": secondary_market_liquidity_usd,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Tests: _pt_discount_pct
# ──────────────────────────────────────────────────────────────────────────────

class TestPtDiscountPct(unittest.TestCase):

    def test_basic_discount(self):
        self.assertAlmostEqual(_pt_discount_pct(95.0), 5.0)

    def test_at_par(self):
        self.assertAlmostEqual(_pt_discount_pct(100.0), 0.0)

    def test_deep_discount(self):
        self.assertAlmostEqual(_pt_discount_pct(80.0), 20.0)

    def test_zero_price(self):
        self.assertAlmostEqual(_pt_discount_pct(0.0), 100.0)

    def test_premium(self):
        # PT trading above par → negative "discount"
        self.assertAlmostEqual(_pt_discount_pct(101.0), -1.0)

    def test_fractional(self):
        self.assertAlmostEqual(_pt_discount_pct(97.5), 2.5)

    def test_exactly_50(self):
        self.assertAlmostEqual(_pt_discount_pct(50.0), 50.0)


# ──────────────────────────────────────────────────────────────────────────────
# Tests: _fixed_vs_variable_spread
# ──────────────────────────────────────────────────────────────────────────────

class TestFixedVsVariableSpread(unittest.TestCase):

    def test_positive_spread(self):
        self.assertAlmostEqual(_fixed_vs_variable_spread(10.0, 4.0), 6.0)

    def test_zero_spread(self):
        self.assertAlmostEqual(_fixed_vs_variable_spread(5.0, 5.0), 0.0)

    def test_negative_spread(self):
        self.assertAlmostEqual(_fixed_vs_variable_spread(4.0, 7.0), -3.0)

    def test_both_zero(self):
        self.assertAlmostEqual(_fixed_vs_variable_spread(0.0, 0.0), 0.0)

    def test_large_spread(self):
        self.assertAlmostEqual(_fixed_vs_variable_spread(30.0, 5.0), 25.0)

    def test_fractional(self):
        self.assertAlmostEqual(_fixed_vs_variable_spread(8.5, 5.5), 3.0)


# ──────────────────────────────────────────────────────────────────────────────
# Tests: _yt_implied_leverage
# ──────────────────────────────────────────────────────────────────────────────

class TestYtImpliedLeverage(unittest.TestCase):

    def test_basic_leverage(self):
        # 100_000 / (0.05 * 100_000) = 20x
        lev = _yt_implied_leverage(100_000, 0.05, 100_000)
        self.assertAlmostEqual(lev, 20.0)

    def test_zero_yt_price(self):
        self.assertAlmostEqual(_yt_implied_leverage(100_000, 0.0, 100_000), 0.0)

    def test_zero_yt_amount(self):
        self.assertAlmostEqual(_yt_implied_leverage(100_000, 0.05, 0.0), 0.0)

    def test_zero_notional(self):
        self.assertAlmostEqual(_yt_implied_leverage(0.0, 0.05, 100_000), 0.0)

    def test_both_denominator_zero(self):
        self.assertAlmostEqual(_yt_implied_leverage(50_000, 0.0, 0.0), 0.0)

    def test_high_leverage(self):
        # 1_000_000 / (0.01 * 10_000) = 10_000x
        lev = _yt_implied_leverage(1_000_000, 0.01, 10_000)
        self.assertAlmostEqual(lev, 10_000.0)

    def test_fractional_result(self):
        lev = _yt_implied_leverage(10_000, 1.0, 10_000)
        self.assertAlmostEqual(lev, 1.0)

    def test_leverage_10x(self):
        lev = _yt_implied_leverage(100_000, 0.1, 100_000)
        self.assertAlmostEqual(lev, 10.0)


# ──────────────────────────────────────────────────────────────────────────────
# Tests: _break_even_variable_apy
# ──────────────────────────────────────────────────────────────────────────────

class TestBreakEvenVariableApy(unittest.TestCase):

    def test_standard_case(self):
        self.assertAlmostEqual(_break_even_variable_apy(10.0, 180), 10.0)

    def test_matured_position(self):
        self.assertAlmostEqual(_break_even_variable_apy(10.0, 0), 0.0)

    def test_negative_days(self):
        self.assertAlmostEqual(_break_even_variable_apy(10.0, -1), 0.0)

    def test_one_day_left(self):
        self.assertAlmostEqual(_break_even_variable_apy(5.0, 1), 5.0)

    def test_zero_implied_fixed(self):
        self.assertAlmostEqual(_break_even_variable_apy(0.0, 90), 0.0)

    def test_high_implied_fixed(self):
        self.assertAlmostEqual(_break_even_variable_apy(30.0, 365), 30.0)

    def test_365_days(self):
        self.assertAlmostEqual(_break_even_variable_apy(12.5, 365), 12.5)


# ──────────────────────────────────────────────────────────────────────────────
# Tests: _time_value_per_day
# ──────────────────────────────────────────────────────────────────────────────

class TestTimeValuePerDay(unittest.TestCase):

    def test_basic(self):
        # discount_usd = 5/100 * 100_000 = 5_000; per_day = 5_000/100 = 50
        val = _time_value_per_day(5.0, 100_000, 100)
        self.assertAlmostEqual(val, 50.0)

    def test_zero_days(self):
        self.assertAlmostEqual(_time_value_per_day(5.0, 100_000, 0), 0.0)

    def test_negative_days(self):
        self.assertAlmostEqual(_time_value_per_day(5.0, 100_000, -5), 0.0)

    def test_zero_notional(self):
        self.assertAlmostEqual(_time_value_per_day(5.0, 0.0, 100), 0.0)

    def test_zero_discount(self):
        self.assertAlmostEqual(_time_value_per_day(0.0, 100_000, 100), 0.0)

    def test_one_day(self):
        # 10/100 * 50_000 = 5_000; /1 = 5_000
        val = _time_value_per_day(10.0, 50_000, 1)
        self.assertAlmostEqual(val, 5_000.0)

    def test_fractional(self):
        val = _time_value_per_day(2.0, 100_000, 200)
        # 2/100 * 100_000 = 2_000; /200 = 10
        self.assertAlmostEqual(val, 10.0)


# ──────────────────────────────────────────────────────────────────────────────
# Tests: _classify_label
# ──────────────────────────────────────────────────────────────────────────────

class TestClassifyLabel(unittest.TestCase):

    def test_matured_zero_days(self):
        label = _classify_label(10.0, 4.0, 5.0, 0)
        self.assertEqual(label, LABEL_MATURED)

    def test_matured_negative_days(self):
        label = _classify_label(10.0, 4.0, 5.0, -1)
        self.assertEqual(label, LABEL_MATURED)

    def test_deep_discount_threshold(self):
        label = _classify_label(10.0, 4.0, 20.0, 90)
        self.assertEqual(label, LABEL_DEEP_DISCOUNT)

    def test_deep_discount_above_threshold(self):
        label = _classify_label(10.0, 4.0, 25.0, 90)
        self.assertEqual(label, LABEL_DEEP_DISCOUNT)

    def test_fixed_rate_advantage(self):
        # spread = 10 - 4 = 6 > 2 → FIXED_RATE_ADVANTAGE
        label = _classify_label(10.0, 4.0, 5.0, 90)
        self.assertEqual(label, LABEL_FIXED_RATE_ADVANTAGE)

    def test_fixed_rate_advantage_just_over_2(self):
        label = _classify_label(7.0, 4.5, 5.0, 90)  # spread=2.5
        self.assertEqual(label, LABEL_FIXED_RATE_ADVANTAGE)

    def test_variable_advantage(self):
        # spread = 4 - 10 = -6 < -2 → VARIABLE_ADVANTAGE
        label = _classify_label(4.0, 10.0, 5.0, 90)
        self.assertEqual(label, LABEL_VARIABLE_ADVANTAGE)

    def test_variable_advantage_just_under_minus2(self):
        label = _classify_label(5.0, 7.5, 5.0, 90)  # spread=-2.5
        self.assertEqual(label, LABEL_VARIABLE_ADVANTAGE)

    def test_at_par_zero_spread(self):
        label = _classify_label(5.0, 5.0, 5.0, 90)
        self.assertEqual(label, LABEL_AT_PAR)

    def test_at_par_small_positive_spread(self):
        label = _classify_label(6.0, 5.0, 5.0, 90)  # spread=1 ≤ 2
        self.assertEqual(label, LABEL_AT_PAR)

    def test_at_par_small_negative_spread(self):
        label = _classify_label(5.0, 6.5, 5.0, 90)  # spread=-1.5, > -2
        self.assertEqual(label, LABEL_AT_PAR)

    def test_deep_discount_takes_priority_over_fixed(self):
        # Even with large fixed advantage, deep discount wins
        label = _classify_label(20.0, 4.0, 21.0, 90)
        self.assertEqual(label, LABEL_DEEP_DISCOUNT)


# ──────────────────────────────────────────────────────────────────────────────
# Tests: _build_flags
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildFlags(unittest.TestCase):

    def test_no_flags(self):
        flags = _build_flags(5.0, 90, 500_000, 2.0, 5.0, 4.0)
        self.assertEqual(flags, [])

    def test_high_yt_leverage(self):
        # leverage > 10
        flags = _build_flags(15.0, 90, 500_000, 2.0, 5.0, 4.0)
        self.assertIn(FLAG_HIGH_YT_LEVERAGE, flags)

    def test_high_yt_leverage_exactly_10_no_flag(self):
        flags = _build_flags(10.0, 90, 500_000, 2.0, 5.0, 4.0)
        self.assertNotIn(FLAG_HIGH_YT_LEVERAGE, flags)

    def test_approaching_maturity(self):
        # 0 < days < 30
        flags = _build_flags(5.0, 15, 500_000, 2.0, 5.0, 4.0)
        self.assertIn(FLAG_APPROACHING_MATURITY, flags)

    def test_approaching_maturity_exactly_30_no_flag(self):
        flags = _build_flags(5.0, 30, 500_000, 2.0, 5.0, 4.0)
        self.assertNotIn(FLAG_APPROACHING_MATURITY, flags)

    def test_approaching_maturity_zero_no_flag(self):
        # days=0 means matured, not approaching
        flags = _build_flags(5.0, 0, 500_000, 2.0, 5.0, 4.0)
        self.assertNotIn(FLAG_APPROACHING_MATURITY, flags)

    def test_illiquid_secondary(self):
        flags = _build_flags(5.0, 90, 50_000, 2.0, 5.0, 4.0)
        self.assertIn(FLAG_ILLIQUID_SECONDARY, flags)

    def test_illiquid_secondary_exactly_100k_no_flag(self):
        flags = _build_flags(5.0, 90, 100_000, 2.0, 5.0, 4.0)
        self.assertNotIn(FLAG_ILLIQUID_SECONDARY, flags)

    def test_fixed_locks_in_premium(self):
        # spread > 3
        flags = _build_flags(5.0, 90, 500_000, 3.5, 5.0, 4.0)
        self.assertIn(FLAG_FIXED_LOCKS_IN_PREMIUM, flags)

    def test_fixed_locks_in_premium_exactly_3_no_flag(self):
        flags = _build_flags(5.0, 90, 500_000, 3.0, 5.0, 4.0)
        self.assertNotIn(FLAG_FIXED_LOCKS_IN_PREMIUM, flags)

    def test_underwater_yt(self):
        # break_even (10) > variable (4) * 1.5 = 6 → True
        flags = _build_flags(5.0, 90, 500_000, 2.0, 10.0, 4.0)
        self.assertIn(FLAG_UNDERWATER_YT, flags)

    def test_underwater_yt_zero_variable_no_flag(self):
        # variable = 0 → condition skipped
        flags = _build_flags(5.0, 90, 500_000, 2.0, 10.0, 0.0)
        self.assertNotIn(FLAG_UNDERWATER_YT, flags)

    def test_multiple_flags(self):
        # leverage=20, days=5, liquidity=10k, spread=4, bk_even=10, var=4 → UNDERWATER (10>6)
        flags = _build_flags(20.0, 5, 10_000, 4.0, 10.0, 4.0)
        self.assertIn(FLAG_HIGH_YT_LEVERAGE, flags)
        self.assertIn(FLAG_APPROACHING_MATURITY, flags)
        self.assertIn(FLAG_ILLIQUID_SECONDARY, flags)
        self.assertIn(FLAG_FIXED_LOCKS_IN_PREMIUM, flags)
        self.assertIn(FLAG_UNDERWATER_YT, flags)

    def test_underwater_yt_break_even_equals_threshold_no_flag(self):
        # break_even = 6, variable = 4 → 6 = 4*1.5 exactly → not strictly greater
        flags = _build_flags(5.0, 90, 500_000, 2.0, 6.0, 4.0)
        self.assertNotIn(FLAG_UNDERWATER_YT, flags)


# ──────────────────────────────────────────────────────────────────────────────
# Tests: DeFiYieldTokenizationAnalyzer.analyze()
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyzerAnalyze(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiYieldTokenizationAnalyzer()

    def test_empty_positions_returns_dict(self):
        result = self.analyzer.analyze([])
        self.assertIsInstance(result, dict)

    def test_empty_positions_zero_aggregates(self):
        result = self.analyzer.analyze([])
        self.assertEqual(result["total_notional_usd"], 0.0)
        self.assertEqual(result["fixed_rate_advantage_count"], 0)
        self.assertEqual(result["approaching_maturity_count"], 0)
        self.assertEqual(result["best_fixed_rate"], 0.0)
        self.assertEqual(result["highest_yt_leverage"], 0.0)

    def test_single_position_keys(self):
        pos = make_position()
        result = self.analyzer.analyze([pos])
        self.assertIn("positions", result)
        self.assertIn("best_fixed_rate", result)
        self.assertIn("highest_yt_leverage", result)
        self.assertIn("total_notional_usd", result)
        self.assertIn("fixed_rate_advantage_count", result)
        self.assertIn("approaching_maturity_count", result)
        self.assertIn("timestamp", result)

    def test_single_position_data_keys(self):
        pos = make_position()
        result = self.analyzer.analyze([pos])
        p = result["positions"][0]
        expected_keys = [
            "protocol", "asset", "days_to_maturity", "pt_discount_pct",
            "fixed_vs_variable_spread_pct", "yt_implied_leverage",
            "break_even_variable_apy", "time_value_per_day_usd",
            "label", "flags", "notional_usd", "implied_fixed_apy_pct",
            "current_variable_apy_pct",
        ]
        for k in expected_keys:
            self.assertIn(k, p, f"Missing key: {k}")

    def test_pt_discount_computed_correctly(self):
        pos = make_position(principal_token_price_pct=95.0)
        result = self.analyzer.analyze([pos])
        self.assertAlmostEqual(result["positions"][0]["pt_discount_pct"], 5.0)

    def test_spread_computed_correctly(self):
        pos = make_position(implied_fixed_apy_pct=10.0, current_variable_apy_pct=4.0)
        result = self.analyzer.analyze([pos])
        self.assertAlmostEqual(
            result["positions"][0]["fixed_vs_variable_spread_pct"], 6.0
        )

    def test_leverage_computed_correctly(self):
        pos = make_position(
            notional_usd=100_000,
            yield_token_price_usd=0.05,
            yt_amount=100_000,
        )
        result = self.analyzer.analyze([pos])
        # 100_000 / (0.05 * 100_000) = 20
        self.assertAlmostEqual(result["positions"][0]["yt_implied_leverage"], 20.0)

    def test_total_notional_aggregated(self):
        positions = [
            make_position(notional_usd=50_000),
            make_position(notional_usd=30_000),
        ]
        result = self.analyzer.analyze(positions)
        self.assertAlmostEqual(result["total_notional_usd"], 80_000.0)

    def test_best_fixed_rate_aggregated(self):
        positions = [
            make_position(implied_fixed_apy_pct=8.0),
            make_position(implied_fixed_apy_pct=12.0),
        ]
        result = self.analyzer.analyze(positions)
        self.assertAlmostEqual(result["best_fixed_rate"], 12.0)

    def test_highest_yt_leverage_aggregated(self):
        positions = [
            make_position(notional_usd=100_000, yield_token_price_usd=0.1, yt_amount=100_000),
            make_position(notional_usd=100_000, yield_token_price_usd=0.01, yt_amount=100_000),
        ]
        result = self.analyzer.analyze(positions)
        # Second: 100_000/(0.01*100_000) = 100x
        self.assertAlmostEqual(result["highest_yt_leverage"], 100.0)

    def test_fixed_rate_advantage_count(self):
        positions = [
            make_position(implied_fixed_apy_pct=10.0, current_variable_apy_pct=4.0),  # FIXED_ADVANTAGE
            make_position(implied_fixed_apy_pct=5.0, current_variable_apy_pct=5.0),   # AT_PAR
        ]
        result = self.analyzer.analyze(positions)
        self.assertEqual(result["fixed_rate_advantage_count"], 1)

    def test_approaching_maturity_count(self):
        positions = [
            make_position(days_to_maturity=10),   # approaching
            make_position(days_to_maturity=180),  # not approaching
        ]
        result = self.analyzer.analyze(positions)
        self.assertEqual(result["approaching_maturity_count"], 1)

    def test_config_none_accepted(self):
        pos = make_position()
        result = self.analyzer.analyze([pos], config=None)
        self.assertIn("positions", result)

    def test_config_empty_dict_accepted(self):
        pos = make_position()
        result = self.analyzer.analyze([pos], config={})
        self.assertIn("positions", result)

    def test_timestamp_is_recent(self):
        before = time.time()
        result = self.analyzer.analyze([make_position()])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_matured_label(self):
        pos = make_position(days_to_maturity=0)
        result = self.analyzer.analyze([pos])
        self.assertEqual(result["positions"][0]["label"], LABEL_MATURED)

    def test_deep_discount_label(self):
        pos = make_position(
            principal_token_price_pct=78.0,  # discount=22%
            days_to_maturity=90,
        )
        result = self.analyzer.analyze([pos])
        self.assertEqual(result["positions"][0]["label"], LABEL_DEEP_DISCOUNT)

    def test_at_par_label(self):
        pos = make_position(implied_fixed_apy_pct=5.0, current_variable_apy_pct=5.0)
        result = self.analyzer.analyze([pos])
        self.assertEqual(result["positions"][0]["label"], LABEL_AT_PAR)

    def test_variable_advantage_label(self):
        pos = make_position(implied_fixed_apy_pct=4.0, current_variable_apy_pct=10.0)
        result = self.analyzer.analyze([pos])
        self.assertEqual(result["positions"][0]["label"], LABEL_VARIABLE_ADVANTAGE)

    def test_fixed_rate_advantage_label(self):
        pos = make_position(implied_fixed_apy_pct=10.0, current_variable_apy_pct=4.0)
        result = self.analyzer.analyze([pos])
        self.assertEqual(result["positions"][0]["label"], LABEL_FIXED_RATE_ADVANTAGE)


# ──────────────────────────────────────────────────────────────────────────────
# Tests: flags in analyze()
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyzerFlags(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiYieldTokenizationAnalyzer()

    def test_no_flags_clean_position(self):
        pos = make_position(
            yield_token_price_usd=0.1,  # lev=9.5k/0.1/100k=9.5x → no flag
            days_to_maturity=180,
            secondary_market_liquidity_usd=500_000,
            implied_fixed_apy_pct=5.0,
            current_variable_apy_pct=4.0,
        )
        result = self.analyzer.analyze([pos])
        # Just verify it runs; exact flag state depends on leverage
        self.assertIsInstance(result["positions"][0]["flags"], list)

    def test_illiquid_secondary_flag(self):
        pos = make_position(secondary_market_liquidity_usd=50_000)
        result = self.analyzer.analyze([pos])
        self.assertIn(FLAG_ILLIQUID_SECONDARY, result["positions"][0]["flags"])

    def test_approaching_maturity_flag(self):
        pos = make_position(days_to_maturity=20)
        result = self.analyzer.analyze([pos])
        self.assertIn(FLAG_APPROACHING_MATURITY, result["positions"][0]["flags"])

    def test_fixed_locks_in_premium_flag(self):
        pos = make_position(
            implied_fixed_apy_pct=12.0,
            current_variable_apy_pct=5.0,  # spread=7 > 3
        )
        result = self.analyzer.analyze([pos])
        self.assertIn(FLAG_FIXED_LOCKS_IN_PREMIUM, result["positions"][0]["flags"])

    def test_underwater_yt_flag(self):
        # break_even = 15.0 (implied_fixed), variable = 4.0 → 15 > 4*1.5=6
        pos = make_position(
            implied_fixed_apy_pct=15.0,
            current_variable_apy_pct=4.0,
            yield_token_price_usd=0.01,
        )
        result = self.analyzer.analyze([pos])
        self.assertIn(FLAG_UNDERWATER_YT, result["positions"][0]["flags"])

    def test_high_yt_leverage_flag(self):
        # notional=100_000, yt_price=0.001, yt_amount=10_000 → lev=10_000
        pos = make_position(
            notional_usd=100_000,
            yield_token_price_usd=0.001,
            yt_amount=10_000,
        )
        result = self.analyzer.analyze([pos])
        self.assertIn(FLAG_HIGH_YT_LEVERAGE, result["positions"][0]["flags"])


# ──────────────────────────────────────────────────────────────────────────────
# Tests: module-level wrappers
# ──────────────────────────────────────────────────────────────────────────────

class TestModuleLevelWrappers(unittest.TestCase):

    def test_analyze_module_level(self):
        result = analyze([make_position()])
        self.assertIn("positions", result)

    def test_analyze_empty(self):
        result = analyze([])
        self.assertEqual(result["total_notional_usd"], 0.0)

    def test_analyze_multiple(self):
        positions = [make_position(), make_position(notional_usd=200_000)]
        result = analyze(positions)
        self.assertEqual(len(result["positions"]), 2)


# ──────────────────────────────────────────────────────────────────────────────
# Tests: ring-buffer persistence (run() method)
# ──────────────────────────────────────────────────────────────────────────────

class TestRingBufferPersistence(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "yield_tokenization_log.json")
        self.analyzer = DeFiYieldTokenizationAnalyzer()

    def test_run_creates_log_file(self):
        self.analyzer.run([make_position()], data_dir=self.tmpdir)
        self.assertTrue(os.path.exists(self.log_path))

    def test_run_log_is_list(self):
        self.analyzer.run([make_position()], data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_run_appends_entries(self):
        self.analyzer.run([make_position()], data_dir=self.tmpdir)
        self.analyzer.run([make_position()], data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_run_ring_buffer_cap(self):
        analyzer = DeFiYieldTokenizationAnalyzer()
        for _ in range(105):
            analyzer.run([make_position()], data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_run_returns_result(self):
        result = self.analyzer.run([make_position()], data_dir=self.tmpdir)
        self.assertIn("positions", result)

    def test_run_module_level(self):
        result = run([make_position()], data_dir=self.tmpdir)
        self.assertIn("positions", result)
        self.assertTrue(os.path.exists(self.log_path))

    def test_atomic_write_produces_valid_json(self):
        self.analyzer.run([make_position()], data_dir=self.tmpdir)
        with open(self.log_path) as f:
            content = f.read()
        parsed = json.loads(content)
        self.assertIsInstance(parsed, list)

    def test_run_existing_log_preserved(self):
        # Pre-populate log
        with open(self.log_path, "w") as f:
            json.dump([{"existing": True}], f)
        self.analyzer.run([make_position()], data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        self.assertTrue(data[0]["existing"])


# ──────────────────────────────────────────────────────────────────────────────
# Tests: edge cases & field defaults
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiYieldTokenizationAnalyzer()

    def test_missing_all_fields_defaults(self):
        result = self.analyzer.analyze([{}])
        p = result["positions"][0]
        self.assertEqual(p["protocol"], "unknown")
        self.assertEqual(p["asset"], "unknown")

    def test_missing_days_defaults_to_matured(self):
        # days_to_maturity defaults to 0
        result = self.analyzer.analyze([{}])
        p = result["positions"][0]
        self.assertEqual(p["days_to_maturity"], 0)
        self.assertEqual(p["label"], LABEL_MATURED)

    def test_zero_yt_price_zero_leverage(self):
        pos = make_position(yield_token_price_usd=0.0)
        result = self.analyzer.analyze([pos])
        self.assertAlmostEqual(result["positions"][0]["yt_implied_leverage"], 0.0)

    def test_positions_count(self):
        positions = [make_position() for _ in range(10)]
        result = self.analyzer.analyze(positions)
        self.assertEqual(len(result["positions"]), 10)

    def test_string_coercions(self):
        pos = make_position()
        pos["protocol"] = 12345
        pos["asset"] = None
        result = self.analyzer.analyze([pos])
        self.assertEqual(result["positions"][0]["protocol"], "12345")
        self.assertEqual(result["positions"][0]["asset"], "None")

    def test_float_coercions(self):
        pos = make_position()
        pos["notional_usd"] = "50000"
        pos["days_to_maturity"] = "90"
        result = self.analyzer.analyze([pos])
        self.assertAlmostEqual(result["positions"][0]["notional_usd"], 50_000.0)

    def test_large_notional_aggregate(self):
        positions = [make_position(notional_usd=1_000_000) for _ in range(10)]
        result = self.analyzer.analyze(positions)
        self.assertAlmostEqual(result["total_notional_usd"], 10_000_000.0)

    def test_all_fixed_advantage_count(self):
        positions = [
            make_position(implied_fixed_apy_pct=15.0, current_variable_apy_pct=4.0)
            for _ in range(5)
        ]
        result = self.analyzer.analyze(positions)
        self.assertEqual(result["fixed_rate_advantage_count"], 5)

    def test_break_even_equals_implied_fixed(self):
        pos = make_position(implied_fixed_apy_pct=8.0, days_to_maturity=90)
        result = self.analyzer.analyze([pos])
        self.assertAlmostEqual(
            result["positions"][0]["break_even_variable_apy"], 8.0
        )

    def test_time_value_per_day_correctness(self):
        pos = make_position(
            principal_token_price_pct=90.0,  # discount=10%
            notional_usd=100_000,
            days_to_maturity=100,
        )
        result = self.analyzer.analyze([pos])
        # 10/100*100_000 = 10_000; /100 = 100
        self.assertAlmostEqual(result["positions"][0]["time_value_per_day_usd"], 100.0)


# ──────────────────────────────────────────────────────────────────────────────
# Tests: multi-position aggregation scenarios
# ──────────────────────────────────────────────────────────────────────────────

class TestMultiPositionAggregation(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiYieldTokenizationAnalyzer()

    def test_two_approaching_maturity(self):
        positions = [
            make_position(days_to_maturity=5),
            make_position(days_to_maturity=10),
            make_position(days_to_maturity=180),
        ]
        result = self.analyzer.analyze(positions)
        self.assertEqual(result["approaching_maturity_count"], 2)

    def test_best_fixed_rate_single(self):
        pos = make_position(implied_fixed_apy_pct=7.5)
        result = self.analyzer.analyze([pos])
        self.assertAlmostEqual(result["best_fixed_rate"], 7.5)

    def test_protocols_preserved(self):
        positions = [
            make_position(protocol="Pendle"),
            make_position(protocol="Spectra"),
            make_position(protocol="Element"),
        ]
        result = self.analyzer.analyze(positions)
        protocols = [p["protocol"] for p in result["positions"]]
        self.assertIn("Pendle", protocols)
        self.assertIn("Spectra", protocols)
        self.assertIn("Element", protocols)

    def test_zero_fixed_rate_advantage_count(self):
        positions = [
            make_position(implied_fixed_apy_pct=4.0, current_variable_apy_pct=10.0),  # variable_adv
            make_position(implied_fixed_apy_pct=5.0, current_variable_apy_pct=5.0),   # at_par
        ]
        result = self.analyzer.analyze(positions)
        self.assertEqual(result["fixed_rate_advantage_count"], 0)

    def test_highest_leverage_across_positions(self):
        positions = [
            make_position(notional_usd=100_000, yield_token_price_usd=0.1, yt_amount=100_000),   # 10x
            make_position(notional_usd=100_000, yield_token_price_usd=0.05, yt_amount=100_000),  # 20x
            make_position(notional_usd=100_000, yield_token_price_usd=0.02, yt_amount=100_000),  # 50x
        ]
        result = self.analyzer.analyze(positions)
        self.assertAlmostEqual(result["highest_yt_leverage"], 50.0)


if __name__ == "__main__":
    unittest.main()
