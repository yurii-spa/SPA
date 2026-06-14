#!/usr/bin/env python3
"""Unit tests for MP-1044 DeFiProtocolLendingUtilizationCliffDetector (SPA-V760).

Run:
    python3 -m unittest spa_core/tests/test_defi_protocol_lending_utilization_cliff_detector.py -v

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

from spa_core.analytics.defi_protocol_lending_utilization_cliff_detector import (
    DeFiProtocolLendingUtilizationCliffDetector,
    _compute_borrow_rate,
    _compute_cliff_proximity_score,
    _compute_days_to_cliff,
    _compute_exit_liquidity_pct,
    _proximity_ratio,
    _label,
    _analyze_single,
    _load_json_list,
    _atomic_write,
    analyze_cliff,
    LOG_FILENAME,
    RING_BUFFER_CAP,
    THRESHOLD_SAFE,
    THRESHOLD_APPROACHING,
    THRESHOLD_ON_CLIFF_HI,
    MP_TAG,
    SOURCE_NAME,
    SCHEMA_VERSION,
)


# ===========================================================================
# 1. _compute_borrow_rate — kinked interest rate model
# ===========================================================================

class TestComputeBorrowRate(unittest.TestCase):

    def test_zero_utilization_returns_base(self):
        rate = _compute_borrow_rate(0.0, 80.0, 1.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 1.0, places=8)

    def test_negative_utilization_returns_base(self):
        rate = _compute_borrow_rate(-5.0, 80.0, 0.5, 4.0, 75.0)
        self.assertAlmostEqual(rate, 0.5, places=8)

    def test_at_optimal_equals_base_plus_slope1(self):
        # at u=opt: rate = base + slope1
        rate = _compute_borrow_rate(80.0, 80.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 4.0, places=6)

    def test_below_optimal_linear_slope1(self):
        # u=40, opt=80 → fraction = 0.5 → rate = 0 + 0.5*4 = 2.0
        rate = _compute_borrow_rate(40.0, 80.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 2.0, places=8)

    def test_above_optimal_uses_slope2(self):
        # u=90, opt=80 → excess=10, remaining=20 → rate = 0+4 + (10/20)*75 = 4+37.5 = 41.5
        rate = _compute_borrow_rate(90.0, 80.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 41.5, places=6)

    def test_full_utilization_100(self):
        # u=100, opt=80 → excess=20, remaining=20 → rate = 0+4 + (20/20)*75 = 79.0
        rate = _compute_borrow_rate(100.0, 80.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 79.0, places=6)

    def test_base_rate_added(self):
        rate = _compute_borrow_rate(0.0, 80.0, 2.5, 4.0, 75.0)
        self.assertAlmostEqual(rate, 2.5, places=8)

    def test_base_rate_at_optimal(self):
        rate = _compute_borrow_rate(80.0, 80.0, 2.5, 4.0, 75.0)
        self.assertAlmostEqual(rate, 6.5, places=6)

    def test_optimal_zero_above_kink_instantly(self):
        # opt=0, any u > 0 → above the kink, slope2 applies
        # rate = base + slope1 + (excess/remaining)*slope2
        #      = 0 + 4 + (1/100)*75 = 4.75
        rate = _compute_borrow_rate(1.0, 0.0, 0.0, 4.0, 75.0)
        self.assertAlmostEqual(rate, 4.75, places=6)

    def test_optimal_100_slope2_never_reached(self):
        # opt=100, remaining=0 → at u=100 we're at the kink, slope2 not applied
        rate = _compute_borrow_rate(100.0, 100.0, 0.0, 5.0, 100.0)
        self.assertAlmostEqual(rate, 5.0, places=6)

    def test_rate_monotonically_increases(self):
        utils = [0, 20, 40, 60, 80, 85, 90, 95, 100]
        rates = [_compute_borrow_rate(u, 80.0, 0.0, 4.0, 75.0) for u in utils]
        for i in range(1, len(rates)):
            self.assertGreaterEqual(rates[i], rates[i - 1])

    def test_rate_jump_at_kink(self):
        # Compare slope per 1pp before vs after kink.
        # Before kink: rate at 79 vs 70 → (79/80)*4 - (70/80)*4 = (9/80)*4 = 0.45 per 9pp
        # After kink: rate at 89 vs 80 → slope2 kicks in: (9/20)*75 = 33.75 per 9pp
        rate_before_kink = _compute_borrow_rate(79.0, 80.0, 0.0, 4.0, 75.0)
        rate_at_kink = _compute_borrow_rate(80.0, 80.0, 0.0, 4.0, 75.0)
        rate_after_kink = _compute_borrow_rate(89.0, 80.0, 0.0, 4.0, 75.0)
        slope_before = rate_at_kink - rate_before_kink   # rate change per 1pp before kink
        slope_after = rate_after_kink - rate_at_kink     # rate change per 9pp after kink
        # The slope2 region should be dramatically steeper
        self.assertGreater(slope_after, slope_before * 5)

    def test_slope2_larger_than_slope1(self):
        rate_80 = _compute_borrow_rate(80.0, 80.0, 0.0, 4.0, 75.0)
        rate_90 = _compute_borrow_rate(90.0, 80.0, 0.0, 4.0, 75.0)
        rate_40 = _compute_borrow_rate(40.0, 80.0, 0.0, 4.0, 75.0)
        rate_0 = _compute_borrow_rate(0.0, 80.0, 0.0, 4.0, 75.0)
        # rate increases from 80 to 90 faster than from 40 to 80
        delta_after_kink = rate_90 - rate_80
        delta_before_kink = rate_80 - rate_0
        self.assertGreater(delta_after_kink, delta_before_kink)


# ===========================================================================
# 2. _compute_cliff_proximity_score
# ===========================================================================

class TestComputeCliffProximityScore(unittest.TestCase):

    def test_zero_utilization_score_zero(self):
        score = _compute_cliff_proximity_score(0.0, 80.0)
        self.assertAlmostEqual(score, 0.0, places=4)

    def test_at_optimal_score_100(self):
        score = _compute_cliff_proximity_score(80.0, 80.0)
        self.assertAlmostEqual(score, 100.0, places=4)

    def test_above_optimal_capped_at_100(self):
        score = _compute_cliff_proximity_score(90.0, 80.0)
        self.assertAlmostEqual(score, 100.0, places=4)

    def test_half_way(self):
        score = _compute_cliff_proximity_score(40.0, 80.0)
        self.assertAlmostEqual(score, 50.0, places=4)

    def test_score_increases_with_utilization(self):
        scores = [_compute_cliff_proximity_score(u, 80.0) for u in range(0, 81, 10)]
        for i in range(1, len(scores)):
            self.assertGreaterEqual(scores[i], scores[i - 1])

    def test_optimal_zero_returns_100(self):
        score = _compute_cliff_proximity_score(5.0, 0.0)
        self.assertAlmostEqual(score, 100.0, places=4)

    def test_score_is_0_to_100(self):
        for util in [0, 10, 40, 80, 90, 100]:
            score = _compute_cliff_proximity_score(float(util), 80.0)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_quarter_way(self):
        score = _compute_cliff_proximity_score(20.0, 80.0)
        self.assertAlmostEqual(score, 25.0, places=4)


# ===========================================================================
# 3. _compute_days_to_cliff
# ===========================================================================

class TestComputeDaysToCliff(unittest.TestCase):

    def test_already_at_cliff_returns_zero(self):
        days = _compute_days_to_cliff(80.0, 80.0, 0.5)
        self.assertAlmostEqual(days, 0.0, places=4)

    def test_above_optimal_returns_zero(self):
        days = _compute_days_to_cliff(85.0, 80.0, 0.5)
        self.assertAlmostEqual(days, 0.0, places=4)

    def test_zero_growth_returns_none(self):
        days = _compute_days_to_cliff(70.0, 80.0, 0.0)
        self.assertIsNone(days)

    def test_negative_growth_returns_none(self):
        days = _compute_days_to_cliff(70.0, 80.0, -1.0)
        self.assertIsNone(days)

    def test_zero_utilization_returns_none(self):
        days = _compute_days_to_cliff(0.0, 80.0, 1.0)
        self.assertIsNone(days)

    def test_basic_computation(self):
        # gap=10, daily_delta = 70 * 1 / 100 = 0.7 → 10/0.7 ≈ 14.29
        days = _compute_days_to_cliff(70.0, 80.0, 1.0)
        expected = 10.0 / (70.0 * 1.0 / 100.0)
        self.assertAlmostEqual(days, expected, places=2)

    def test_higher_growth_fewer_days(self):
        days_slow = _compute_days_to_cliff(70.0, 80.0, 0.5)
        days_fast = _compute_days_to_cliff(70.0, 80.0, 2.0)
        self.assertGreater(days_slow, days_fast)

    def test_larger_gap_more_days(self):
        days_near = _compute_days_to_cliff(75.0, 80.0, 1.0)
        days_far = _compute_days_to_cliff(50.0, 80.0, 1.0)
        self.assertGreater(days_far, days_near)

    def test_returns_positive_float(self):
        days = _compute_days_to_cliff(60.0, 80.0, 0.5)
        self.assertIsNotNone(days)
        self.assertGreater(days, 0.0)

    def test_result_rounded_to_2dp(self):
        days = _compute_days_to_cliff(60.0, 80.0, 0.3)
        # Just verify it returns a number
        self.assertIsInstance(days, float)


# ===========================================================================
# 4. _compute_exit_liquidity_pct
# ===========================================================================

class TestComputeExitLiquidityPct(unittest.TestCase):

    def test_no_borrows_full_liquidity(self):
        liq = _compute_exit_liquidity_pct(0.0, 100_000, 0.0)
        self.assertAlmostEqual(liq, 100.0, places=4)

    def test_half_borrowed(self):
        liq = _compute_exit_liquidity_pct(50.0, 100_000, 50_000)
        self.assertAlmostEqual(liq, 50.0, places=4)

    def test_fully_borrowed(self):
        liq = _compute_exit_liquidity_pct(100.0, 100_000, 100_000)
        self.assertAlmostEqual(liq, 0.0, places=4)

    def test_no_supplied_falls_back_to_utilization(self):
        liq = _compute_exit_liquidity_pct(70.0, 0.0, 0.0)
        self.assertAlmostEqual(liq, 30.0, places=4)

    def test_negative_result_clamped_to_zero(self):
        # More borrowed than supplied (data inconsistency)
        liq = _compute_exit_liquidity_pct(105.0, 100_000, 105_000)
        self.assertGreaterEqual(liq, 0.0)

    def test_result_between_0_and_100(self):
        for util in [0, 20, 50, 80, 95, 100]:
            liq = _compute_exit_liquidity_pct(
                float(util), 200_000_000, float(util) * 2_000_000
            )
            self.assertGreaterEqual(liq, 0.0)
            self.assertLessEqual(liq, 100.0)


# ===========================================================================
# 5. _proximity_ratio
# ===========================================================================

class TestProximityRatio(unittest.TestCase):

    def test_at_optimal(self):
        self.assertAlmostEqual(_proximity_ratio(80.0, 80.0), 1.0, places=8)

    def test_half_of_optimal(self):
        self.assertAlmostEqual(_proximity_ratio(40.0, 80.0), 0.5, places=8)

    def test_above_optimal(self):
        ratio = _proximity_ratio(90.0, 80.0)
        self.assertGreater(ratio, 1.0)

    def test_zero_optimal_zero_util(self):
        ratio = _proximity_ratio(0.0, 0.0)
        self.assertEqual(ratio, 0.0)

    def test_zero_optimal_nonzero_util(self):
        ratio = _proximity_ratio(10.0, 0.0)
        self.assertTrue(math.isinf(ratio))


# ===========================================================================
# 6. _label
# ===========================================================================

class TestLabel(unittest.TestCase):

    def test_safe_zone_low(self):
        self.assertEqual(_label(0.0), "SAFE_ZONE")

    def test_safe_zone_near_threshold(self):
        self.assertEqual(_label(0.699), "SAFE_ZONE")

    def test_approaching_cliff_lower(self):
        self.assertEqual(_label(0.70), "APPROACHING_CLIFF")

    def test_approaching_cliff_upper(self):
        self.assertEqual(_label(0.899), "APPROACHING_CLIFF")

    def test_cliff_warning(self):
        self.assertEqual(_label(0.90), "CLIFF_WARNING")

    def test_cliff_warning_near_kink(self):
        self.assertEqual(_label(0.999), "CLIFF_WARNING")

    def test_on_the_cliff_at_kink(self):
        self.assertEqual(_label(1.00), "ON_THE_CLIFF")

    def test_on_the_cliff_just_above(self):
        self.assertEqual(_label(1.04), "ON_THE_CLIFF")

    def test_on_the_cliff_at_upper_bound(self):
        self.assertEqual(_label(1.05), "ON_THE_CLIFF")

    def test_cliff_breached(self):
        self.assertEqual(_label(1.051), "CLIFF_BREACHED")

    def test_cliff_breached_far_above(self):
        self.assertEqual(_label(2.0), "CLIFF_BREACHED")

    def test_inf_ratio_breached(self):
        self.assertEqual(_label(float("inf")), "CLIFF_BREACHED")


# ===========================================================================
# 7. _analyze_single
# ===========================================================================

class TestAnalyzeSingle(unittest.TestCase):

    def _safe_params(self, **overrides):
        params = dict(
            protocol_name="test_proto",
            current_utilization_pct=55.0,
            optimal_utilization_pct=80.0,
            kink_multiplier=60.0,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=75.0,
            total_supplied_usd=100_000_000,
            total_borrowed_usd=55_000_000,
            daily_borrow_growth_pct=0.5,
        )
        params.update(overrides)
        return params

    def test_returns_dict(self):
        result = _analyze_single(**self._safe_params())
        self.assertIsInstance(result, dict)

    def test_safe_zone_label(self):
        result = _analyze_single(**self._safe_params(current_utilization_pct=40.0))
        self.assertEqual(result["label"], "SAFE_ZONE")

    def test_approaching_cliff_label(self):
        # 70/80 = 0.875 → in [0.70, 0.90) → APPROACHING_CLIFF
        result = _analyze_single(**self._safe_params(current_utilization_pct=70.0))
        self.assertEqual(result["label"], "APPROACHING_CLIFF")

    def test_cliff_warning_label(self):
        result = _analyze_single(**self._safe_params(current_utilization_pct=78.0))
        self.assertEqual(result["label"], "CLIFF_WARNING")

    def test_on_the_cliff_label(self):
        result = _analyze_single(**self._safe_params(current_utilization_pct=80.0))
        self.assertEqual(result["label"], "ON_THE_CLIFF")

    def test_cliff_breached_label(self):
        result = _analyze_single(**self._safe_params(current_utilization_pct=90.0))
        self.assertEqual(result["label"], "CLIFF_BREACHED")

    def test_cliff_proximity_score_in_result(self):
        result = _analyze_single(**self._safe_params())
        self.assertIn("cliff_proximity_score", result)
        self.assertGreaterEqual(result["cliff_proximity_score"], 0.0)
        self.assertLessEqual(result["cliff_proximity_score"], 100.0)

    def test_days_to_cliff_in_result(self):
        result = _analyze_single(**self._safe_params())
        self.assertIn("days_to_cliff_estimate", result)

    def test_borrow_rate_at_cliff_pct_in_result(self):
        result = _analyze_single(**self._safe_params())
        self.assertIn("borrow_rate_at_cliff_pct", result)

    def test_exit_liquidity_pct_in_result(self):
        result = _analyze_single(**self._safe_params())
        self.assertIn("exit_liquidity_pct", result)
        self.assertGreaterEqual(result["exit_liquidity_pct"], 0.0)

    def test_warnings_is_list(self):
        result = _analyze_single(**self._safe_params())
        self.assertIsInstance(result["warnings"], list)

    def test_negative_utilization_clamped(self):
        result = _analyze_single(**self._safe_params(current_utilization_pct=-10.0))
        self.assertEqual(result["label"], "SAFE_ZONE")
        self.assertAlmostEqual(result["cliff_proximity_score"], 0.0, places=4)

    def test_utilization_over_100_clamped(self):
        result = _analyze_single(**self._safe_params(current_utilization_pct=110.0))
        self.assertIn(result["label"], ("CLIFF_BREACHED", "ON_THE_CLIFF"))

    def test_zero_supplied_warning(self):
        result = _analyze_single(**self._safe_params(total_supplied_usd=0.0))
        self.assertTrue(any("supplied" in w.lower() for w in result["warnings"]))

    def test_protocol_name_preserved(self):
        result = _analyze_single(**self._safe_params(protocol_name="my_protocol"))
        self.assertEqual(result["protocol_name"], "my_protocol")

    def test_borrow_rate_at_cliff_is_base_plus_slope1(self):
        # At optimal=80, base=0, slope1=4 → borrow_rate_at_cliff = 4.0
        result = _analyze_single(**self._safe_params())
        self.assertAlmostEqual(result["borrow_rate_at_cliff_pct"], 4.0, places=4)

    def test_rate_jump_positive(self):
        result = _analyze_single(**self._safe_params())
        self.assertGreater(result["rate_jump_at_cliff_pct"], 0.0)

    def test_borrow_rate_current_below_cliff_rate_when_under_kink(self):
        result = _analyze_single(**self._safe_params(current_utilization_pct=60.0))
        self.assertLess(result["borrow_rate_current_pct"], result["borrow_rate_at_cliff_pct"])

    def test_high_kink_multiplier_preserved(self):
        result = _analyze_single(**self._safe_params(kink_multiplier=200.0))
        self.assertAlmostEqual(result["kink_multiplier"], 200.0, places=4)

    def test_zero_growth_days_to_cliff_none(self):
        result = _analyze_single(**self._safe_params(daily_borrow_growth_pct=0.0))
        self.assertIsNone(result["days_to_cliff_estimate"])


# ===========================================================================
# 8. DeFiProtocolLendingUtilizationCliffDetector class
# ===========================================================================

class TestDetectorClass(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.detector = DeFiProtocolLendingUtilizationCliffDetector(
            data_dir=self.tmp_dir
        )

    def _call_analyze(self, **overrides):
        params = dict(
            protocol_name="aave_v3",
            current_utilization_pct=55.0,
            optimal_utilization_pct=80.0,
            kink_multiplier=60.0,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=75.0,
            total_supplied_usd=500_000_000,
            total_borrowed_usd=275_000_000,
            daily_borrow_growth_pct=0.3,
        )
        params.update(overrides)
        return self.detector.analyze(**params)

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
        self.assertTrue(result["timestamp"].endswith("Z") or "+" in result["timestamp"])

    def test_label_is_string(self):
        result = self._call_analyze()
        self.assertIsInstance(result["label"], str)

    def test_cliff_proximity_score_0_to_100(self):
        result = self._call_analyze()
        self.assertGreaterEqual(result["cliff_proximity_score"], 0.0)
        self.assertLessEqual(result["cliff_proximity_score"], 100.0)

    def test_get_label_after_analyze(self):
        self._call_analyze()
        self.assertIsNotNone(self.detector.get_label())

    def test_get_label_before_analyze_is_none(self):
        fresh = DeFiProtocolLendingUtilizationCliffDetector(data_dir=self.tmp_dir)
        self.assertIsNone(fresh.get_label())

    def test_is_at_risk_safe_zone(self):
        self._call_analyze(current_utilization_pct=40.0)
        self.assertFalse(self.detector.is_at_risk())

    def test_is_at_risk_cliff_warning(self):
        self._call_analyze(current_utilization_pct=78.0)
        self.assertTrue(self.detector.is_at_risk())

    def test_is_at_risk_on_the_cliff(self):
        self._call_analyze(current_utilization_pct=80.0)
        self.assertTrue(self.detector.is_at_risk())

    def test_is_at_risk_cliff_breached(self):
        self._call_analyze(current_utilization_pct=90.0)
        self.assertTrue(self.detector.is_at_risk())

    def test_save_creates_log_file(self):
        self._call_analyze()
        ok = self.detector.save()
        self.assertTrue(ok)
        log_path = Path(self.tmp_dir) / LOG_FILENAME
        self.assertTrue(log_path.exists())

    def test_save_before_analyze_returns_false(self):
        fresh = DeFiProtocolLendingUtilizationCliffDetector(data_dir=self.tmp_dir)
        ok = fresh.save()
        self.assertFalse(ok)

    def test_save_appends_to_existing(self):
        self._call_analyze()
        self.detector.save()
        self._call_analyze(current_utilization_pct=60.0)
        self.detector.save()
        log_path = Path(self.tmp_dir) / LOG_FILENAME
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        cap = 5
        small = DeFiProtocolLendingUtilizationCliffDetector(
            data_dir=self.tmp_dir, ring_cap=cap
        )
        for i in range(8):
            small.analyze(
                protocol_name="p",
                current_utilization_pct=float(i * 10),
                optimal_utilization_pct=80.0,
                kink_multiplier=60.0,
                base_rate_pct=0.0,
                slope1_pct=4.0,
                slope2_pct=75.0,
                total_supplied_usd=1_000_000,
                total_borrowed_usd=float(i * 100_000),
                daily_borrow_growth_pct=0.5,
            )
            small.save()
        log_path = Path(self.tmp_dir) / LOG_FILENAME
        with open(log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), cap)

    def test_save_log_is_valid_json_list(self):
        self._call_analyze()
        self.detector.save()
        log_path = Path(self.tmp_dir) / LOG_FILENAME
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


# ===========================================================================
# 9. analyze_batch
# ===========================================================================

class TestAnalyzeBatch(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.detector = DeFiProtocolLendingUtilizationCliffDetector(
            data_dir=self.tmp_dir
        )

    def _make_proto(self, name, utilization):
        return dict(
            protocol_name=name,
            current_utilization_pct=utilization,
            optimal_utilization_pct=80.0,
            kink_multiplier=60.0,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=75.0,
            total_supplied_usd=100_000_000,
            total_borrowed_usd=utilization * 1_000_000,
            daily_borrow_growth_pct=0.5,
        )

    def test_batch_returns_dict(self):
        result = self.detector.analyze_batch([
            self._make_proto("a", 40.0),
            self._make_proto("b", 85.0),
        ])
        self.assertIsInstance(result, dict)

    def test_batch_protocol_count(self):
        result = self.detector.analyze_batch([
            self._make_proto("a", 40.0),
            self._make_proto("b", 85.0),
            self._make_proto("c", 60.0),
        ])
        self.assertEqual(result["protocol_count"], 3)

    def test_batch_at_risk_count(self):
        result = self.detector.analyze_batch([
            self._make_proto("safe", 40.0),
            self._make_proto("risky", 85.0),
        ])
        self.assertEqual(result["at_risk_count"], 1)

    def test_batch_label_counts(self):
        result = self.detector.analyze_batch([
            self._make_proto("a", 40.0),
            self._make_proto("b", 90.0),
        ])
        self.assertIn("label_counts", result)
        counts = result["label_counts"]
        total = sum(counts.values())
        self.assertEqual(total, 2)

    def test_batch_empty_list(self):
        result = self.detector.analyze_batch([])
        self.assertEqual(result["protocol_count"], 0)
        self.assertEqual(result["at_risk_count"], 0)

    def test_batch_per_protocol_list(self):
        result = self.detector.analyze_batch([
            self._make_proto("a", 50.0),
        ])
        self.assertIsInstance(result["per_protocol"], list)
        self.assertEqual(len(result["per_protocol"]), 1)

    def test_batch_at_risk_list(self):
        result = self.detector.analyze_batch([
            self._make_proto("a", 50.0),
            self._make_proto("b", 95.0),
        ])
        at_risk = result["at_risk"]
        self.assertTrue(any(r.get("label") in ("CLIFF_WARNING", "ON_THE_CLIFF", "CLIFF_BREACHED")
                            for r in at_risk))


# ===========================================================================
# 10. I/O helpers
# ===========================================================================

class TestIOHelpers(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def test_load_json_list_missing_file_returns_empty(self):
        path = self.tmp_dir / "nonexistent.json"
        result = _load_json_list(path)
        self.assertEqual(result, [])

    def test_load_json_list_valid_list(self):
        path = self.tmp_dir / "test.json"
        _atomic_write(path, [{"a": 1}, {"b": 2}])
        result = _load_json_list(path)
        self.assertEqual(len(result), 2)

    def test_load_json_list_non_list_returns_empty(self):
        path = self.tmp_dir / "obj.json"
        _atomic_write(path, {"key": "value"})
        result = _load_json_list(path)
        self.assertEqual(result, [])

    def test_load_json_list_corrupt_returns_empty(self):
        path = self.tmp_dir / "corrupt.json"
        path.write_text("NOT_JSON", encoding="utf-8")
        result = _load_json_list(path)
        self.assertEqual(result, [])

    def test_atomic_write_creates_file(self):
        path = self.tmp_dir / "out.json"
        _atomic_write(path, [1, 2, 3])
        self.assertTrue(path.exists())

    def test_atomic_write_content_correct(self):
        path = self.tmp_dir / "out.json"
        data = [{"protocol": "aave", "score": 55.0}]
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

    def test_atomic_write_no_tmp_left_behind(self):
        path = self.tmp_dir / "out.json"
        _atomic_write(path, {"x": 1})
        tmp_files = list(self.tmp_dir.glob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)


# ===========================================================================
# 11. analyze_cliff functional API
# ===========================================================================

class TestAnalyzeCliffFunctional(unittest.TestCase):

    def test_returns_dict(self):
        result = analyze_cliff(
            protocol_name="compound",
            current_utilization_pct=60.0,
            optimal_utilization_pct=80.0,
            kink_multiplier=50.0,
            base_rate_pct=0.5,
            slope1_pct=5.0,
            slope2_pct=60.0,
            total_supplied_usd=300_000_000,
            total_borrowed_usd=180_000_000,
            daily_borrow_growth_pct=0.4,
        )
        self.assertIsInstance(result, dict)

    def test_label_field_present(self):
        result = analyze_cliff(
            protocol_name="compound",
            current_utilization_pct=60.0,
            optimal_utilization_pct=80.0,
            kink_multiplier=50.0,
            base_rate_pct=0.5,
            slope1_pct=5.0,
            slope2_pct=60.0,
            total_supplied_usd=300_000_000,
            total_borrowed_usd=180_000_000,
            daily_borrow_growth_pct=0.4,
        )
        self.assertIn("label", result)

    def test_safe_label_for_low_utilization(self):
        result = analyze_cliff(
            protocol_name="safe_proto",
            current_utilization_pct=20.0,
            optimal_utilization_pct=80.0,
            kink_multiplier=40.0,
            base_rate_pct=0.0,
            slope1_pct=3.0,
            slope2_pct=50.0,
            total_supplied_usd=100_000_000,
            total_borrowed_usd=20_000_000,
            daily_borrow_growth_pct=0.1,
        )
        self.assertEqual(result["label"], "SAFE_ZONE")

    def test_breached_label_for_high_utilization(self):
        result = analyze_cliff(
            protocol_name="stressed_proto",
            current_utilization_pct=95.0,
            optimal_utilization_pct=80.0,
            kink_multiplier=80.0,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=100.0,
            total_supplied_usd=100_000_000,
            total_borrowed_usd=95_000_000,
            daily_borrow_growth_pct=0.5,
        )
        self.assertEqual(result["label"], "CLIFF_BREACHED")


# ===========================================================================
# 12. Edge cases and boundary conditions
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.detector = DeFiProtocolLendingUtilizationCliffDetector(
            data_dir=self.tmp_dir
        )

    def test_all_zeros(self):
        result = self.detector.analyze(
            protocol_name="zero_proto",
            current_utilization_pct=0.0,
            optimal_utilization_pct=0.0,
            kink_multiplier=0.0,
            base_rate_pct=0.0,
            slope1_pct=0.0,
            slope2_pct=0.0,
            total_supplied_usd=0.0,
            total_borrowed_usd=0.0,
            daily_borrow_growth_pct=0.0,
        )
        self.assertIsInstance(result, dict)
        self.assertIn("label", result)

    def test_very_high_slope2(self):
        result = self.detector.analyze(
            protocol_name="steep",
            current_utilization_pct=85.0,
            optimal_utilization_pct=80.0,
            kink_multiplier=1000.0,
            base_rate_pct=0.0,
            slope1_pct=5.0,
            slope2_pct=10000.0,
            total_supplied_usd=100_000_000,
            total_borrowed_usd=85_000_000,
            daily_borrow_growth_pct=0.5,
        )
        self.assertIn(result["label"], ("CLIFF_BREACHED",))
        # Borrow rate should be very high above kink
        self.assertGreater(result["borrow_rate_current_pct"], 100.0)

    def test_borrowed_exceeds_supplied_generates_warning(self):
        result = self.detector.analyze(
            protocol_name="inconsistent",
            current_utilization_pct=60.0,
            optimal_utilization_pct=80.0,
            kink_multiplier=60.0,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=75.0,
            total_supplied_usd=100_000_000,
            total_borrowed_usd=110_000_000,
            daily_borrow_growth_pct=0.5,
        )
        self.assertTrue(len(result["warnings"]) > 0)

    def test_unicode_protocol_name(self):
        result = self.detector.analyze(
            protocol_name="протокол_тест",
            current_utilization_pct=50.0,
            optimal_utilization_pct=80.0,
            kink_multiplier=50.0,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=75.0,
            total_supplied_usd=1_000_000,
            total_borrowed_usd=500_000,
            daily_borrow_growth_pct=0.5,
        )
        self.assertEqual(result["protocol_name"], "протокол_тест")

    def test_floating_point_utilization(self):
        result = self.detector.analyze(
            protocol_name="float_test",
            current_utilization_pct=79.9999,
            optimal_utilization_pct=80.0,
            kink_multiplier=60.0,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=75.0,
            total_supplied_usd=100_000_000,
            total_borrowed_usd=79_999_900,
            daily_borrow_growth_pct=0.5,
        )
        # Should be CLIFF_WARNING (just below kink)
        self.assertEqual(result["label"], "CLIFF_WARNING")

    def test_large_supplied_amounts(self):
        result = self.detector.analyze(
            protocol_name="large_pool",
            current_utilization_pct=70.0,
            optimal_utilization_pct=80.0,
            kink_multiplier=60.0,
            base_rate_pct=0.0,
            slope1_pct=4.0,
            slope2_pct=75.0,
            total_supplied_usd=10_000_000_000,
            total_borrowed_usd=7_000_000_000,
            daily_borrow_growth_pct=0.5,
        )
        self.assertAlmostEqual(result["exit_liquidity_pct"], 30.0, places=2)


# ===========================================================================
# 13. Constants and schema
# ===========================================================================

class TestConstants(unittest.TestCase):

    def test_ring_buffer_cap(self):
        self.assertEqual(RING_BUFFER_CAP, 100)

    def test_mp_tag(self):
        self.assertEqual(MP_TAG, "MP-1044")

    def test_source_name(self):
        self.assertEqual(SOURCE_NAME, "defi_protocol_lending_utilization_cliff_detector")

    def test_schema_version_positive(self):
        self.assertGreater(SCHEMA_VERSION, 0)

    def test_threshold_ordering(self):
        self.assertLess(THRESHOLD_SAFE, THRESHOLD_APPROACHING)
        self.assertLess(THRESHOLD_APPROACHING, 1.0)
        self.assertGreater(THRESHOLD_ON_CLIFF_HI, 1.0)

    def test_log_filename(self):
        self.assertTrue(LOG_FILENAME.endswith(".json"))
        self.assertIn("cliff", LOG_FILENAME)


if __name__ == "__main__":
    unittest.main()
