"""
Tests for MP-1094: DeFiProtocolYieldReserveBufferAnalyzer
≥110 unittest tests covering helpers, class methods, edge cases, batch API,
ranking, and ring-buffer atomic log.
Run with: python3 -m unittest spa_core/tests/test_defi_protocol_yield_reserve_buffer_analyzer.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_protocol_yield_reserve_buffer_analyzer import (
    DeFiProtocolYieldReserveBufferAnalyzer,
    compute_reserve_ratio_pct,
    compute_bad_debt_coverage_ratio,
    compute_days_to_deplete,
    compute_reserve_adequacy_score,
    compute_reserve_label,
    _atomic_log_append,
    LABEL_FORTRESS_RESERVES,
    LABEL_ADEQUATE_BUFFER,
    LABEL_THIN_RESERVES,
    LABEL_UNDERFUNDED,
    LABEL_CRITICALLY_UNDERFUNDED,
)


# =========================================================================== #
# Helpers
# =========================================================================== #

def _tmp_log():
    """Create a temporary file path for log tests."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # Remove so log starts fresh
    return path


def _analyzer(log_path=None):
    return DeFiProtocolYieldReserveBufferAnalyzer(log_path=log_path or _tmp_log())


def _result(**kw):
    """Shorthand for calling analyzer.analyze with default values + overrides."""
    defaults = dict(
        protocol_name="TestProto",
        reserve_usd=10_000_000.0,
        total_tvl_usd=100_000_000.0,
        bad_debt_history_usd=1_000_000.0,
        daily_yield_usd=10_000.0,
        insured_tvl_pct=50.0,
    )
    defaults.update(kw)
    return _analyzer().analyze(**defaults)


# =========================================================================== #
# 1. compute_reserve_ratio_pct
# =========================================================================== #

class TestComputeReserveRatioPct(unittest.TestCase):

    def test_basic_10_percent(self):
        self.assertAlmostEqual(compute_reserve_ratio_pct(10_000, 100_000), 10.0, places=4)

    def test_basic_5_percent(self):
        self.assertAlmostEqual(compute_reserve_ratio_pct(5_000, 100_000), 5.0, places=4)

    def test_zero_tvl_returns_zero(self):
        self.assertEqual(compute_reserve_ratio_pct(1_000_000, 0), 0.0)

    def test_negative_tvl_returns_zero(self):
        self.assertEqual(compute_reserve_ratio_pct(1_000, -500), 0.0)

    def test_zero_reserve(self):
        self.assertEqual(compute_reserve_ratio_pct(0, 1_000_000), 0.0)

    def test_fractional_ratio(self):
        ratio = compute_reserve_ratio_pct(1, 1000)
        self.assertAlmostEqual(ratio, 0.1, places=4)

    def test_100_percent(self):
        self.assertAlmostEqual(compute_reserve_ratio_pct(500_000, 500_000), 100.0, places=4)

    def test_large_reserve_exceeds_tvl(self):
        ratio = compute_reserve_ratio_pct(200_000, 100_000)
        self.assertAlmostEqual(ratio, 200.0, places=4)

    def test_result_is_float(self):
        result = compute_reserve_ratio_pct(1_000, 50_000)
        self.assertIsInstance(result, float)

    def test_small_values(self):
        ratio = compute_reserve_ratio_pct(0.5, 100.0)
        self.assertAlmostEqual(ratio, 0.5, places=4)

    def test_precisely_threshold_2pct(self):
        ratio = compute_reserve_ratio_pct(2_000, 100_000)
        self.assertAlmostEqual(ratio, 2.0, places=4)

    def test_precisely_threshold_05pct(self):
        ratio = compute_reserve_ratio_pct(500, 100_000)
        self.assertAlmostEqual(ratio, 0.5, places=4)


# =========================================================================== #
# 2. compute_bad_debt_coverage_ratio
# =========================================================================== #

class TestComputeBadDebtCoverageRatio(unittest.TestCase):

    def test_5x_coverage(self):
        self.assertAlmostEqual(compute_bad_debt_coverage_ratio(5_000_000, 1_000_000), 5.0, places=4)

    def test_2x_coverage(self):
        self.assertAlmostEqual(compute_bad_debt_coverage_ratio(2_000_000, 1_000_000), 2.0, places=4)

    def test_1x_coverage(self):
        self.assertAlmostEqual(compute_bad_debt_coverage_ratio(1_000_000, 1_000_000), 1.0, places=4)

    def test_zero_bad_debt_uses_floor_1(self):
        # max(0, 1) = 1 → coverage = reserve / 1
        ratio = compute_bad_debt_coverage_ratio(500_000, 0)
        self.assertAlmostEqual(ratio, 500_000.0, places=1)

    def test_negative_bad_debt_uses_floor_1(self):
        ratio = compute_bad_debt_coverage_ratio(100_000, -500)
        self.assertAlmostEqual(ratio, 100_000.0, places=1)

    def test_zero_reserve(self):
        self.assertAlmostEqual(compute_bad_debt_coverage_ratio(0, 1_000_000), 0.0, places=4)

    def test_partial_coverage(self):
        ratio = compute_bad_debt_coverage_ratio(500_000, 1_000_000)
        self.assertAlmostEqual(ratio, 0.5, places=4)

    def test_result_is_float(self):
        result = compute_bad_debt_coverage_ratio(1_000, 2_000)
        self.assertIsInstance(result, float)

    def test_large_numbers(self):
        ratio = compute_bad_debt_coverage_ratio(1e9, 2e8)
        self.assertAlmostEqual(ratio, 5.0, places=4)

    def test_bad_debt_equals_1(self):
        ratio = compute_bad_debt_coverage_ratio(1_000, 1)
        self.assertAlmostEqual(ratio, 1_000.0, places=1)


# =========================================================================== #
# 3. compute_days_to_deplete
# =========================================================================== #

class TestComputeDaysToDeplete(unittest.TestCase):

    def test_basic_1000_days(self):
        # 1_000_000 / 1_000 = 1000 days
        self.assertAlmostEqual(compute_days_to_deplete(1_000_000, 1_000), 1000.0, places=2)

    def test_zero_yield_uses_floor_001(self):
        # 10_000 / 0.01 = 1_000_000 → capped at 99_999
        result = compute_days_to_deplete(10_000, 0)
        self.assertEqual(result, 99_999.0)

    def test_negative_yield_uses_floor_001(self):
        result = compute_days_to_deplete(10_000, -500)
        self.assertEqual(result, 99_999.0)

    def test_cap_at_99999(self):
        # Very small daily yield → would exceed cap
        result = compute_days_to_deplete(1_000_000_000, 1)
        self.assertEqual(result, 99_999.0)

    def test_small_reserve(self):
        # 100 / 10 = 10 days
        self.assertAlmostEqual(compute_days_to_deplete(100, 10), 10.0, places=4)

    def test_365_days(self):
        # 36_500 / 100 = 365
        self.assertAlmostEqual(compute_days_to_deplete(36_500, 100), 365.0, places=4)

    def test_zero_reserve(self):
        self.assertAlmostEqual(compute_days_to_deplete(0, 10_000), 0.0, places=4)

    def test_result_is_float(self):
        result = compute_days_to_deplete(50_000, 500)
        self.assertIsInstance(result, float)

    def test_fractional_days(self):
        # 150 / 100 = 1.5 days
        self.assertAlmostEqual(compute_days_to_deplete(150, 100), 1.5, places=4)

    def test_very_small_daily_yield_below_floor(self):
        # daily_yield=0.001 < 0.01, so uses 0.01 floor
        result = compute_days_to_deplete(1_000, 0.001)
        self.assertEqual(result, 99_999.0)  # 1_000/0.01 = 100_000 > cap → 99_999


# =========================================================================== #
# 4. compute_reserve_adequacy_score
# =========================================================================== #

class TestComputeReserveAdequacyScore(unittest.TestCase):

    def test_returns_int(self):
        score = compute_reserve_adequacy_score(10.0, 5.0, 365.0, 100.0)
        self.assertIsInstance(score, int)

    def test_perfect_inputs_give_100(self):
        score = compute_reserve_adequacy_score(10.0, 5.0, 365.0, 100.0)
        self.assertEqual(score, 100)

    def test_zero_inputs_give_0(self):
        score = compute_reserve_adequacy_score(0.0, 0.0, 0.0, 0.0)
        self.assertEqual(score, 0)

    def test_score_bounded_above_100(self):
        score = compute_reserve_adequacy_score(999.0, 999.0, 999_999.0, 999.0)
        self.assertEqual(score, 100)

    def test_score_not_negative(self):
        score = compute_reserve_adequacy_score(-10.0, -5.0, -365.0, -100.0)
        self.assertGreaterEqual(score, 0)

    def test_half_each_component(self):
        # Each component at 50% of cap
        score = compute_reserve_adequacy_score(5.0, 2.5, 182.5, 50.0)
        self.assertEqual(score, 50)

    def test_only_reserve_ratio_contribution(self):
        # Full reserve ratio (10%), others zero
        score = compute_reserve_adequacy_score(10.0, 0.0, 0.0, 0.0)
        self.assertEqual(score, 40)

    def test_only_bad_debt_coverage_contribution(self):
        # Full bad debt coverage (5x), others zero
        score = compute_reserve_adequacy_score(0.0, 5.0, 0.0, 0.0)
        self.assertEqual(score, 30)

    def test_only_days_deplete_contribution(self):
        # Full days deplete (365), others zero
        score = compute_reserve_adequacy_score(0.0, 0.0, 365.0, 0.0)
        self.assertEqual(score, 20)

    def test_only_insured_tvl_contribution(self):
        # Full insured TVL (100%), others zero
        score = compute_reserve_adequacy_score(0.0, 0.0, 0.0, 100.0)
        self.assertEqual(score, 10)

    def test_typical_fortress_scenario(self):
        # 15% ratio (capped at 10→40pts), 10x cov (capped at 5→30pts),
        # 1000 days (capped at 365→20pts), 100% insured (→10pts) = 100
        score = compute_reserve_adequacy_score(15.0, 10.0, 1000.0, 100.0)
        self.assertEqual(score, 100)

    def test_thin_reserve_scenario(self):
        # 2% ratio, 1x coverage, 60 days, 20% insured
        score = compute_reserve_adequacy_score(2.0, 1.0, 60.0, 20.0)
        self.assertGreater(score, 0)
        self.assertLess(score, 50)

    def test_score_increases_with_better_inputs(self):
        low  = compute_reserve_adequacy_score(1.0, 0.5, 30.0, 10.0)
        high = compute_reserve_adequacy_score(8.0, 4.0, 300.0, 80.0)
        self.assertGreater(high, low)

    def test_days_capped_at_365_for_scoring(self):
        score_365   = compute_reserve_adequacy_score(0.0, 0.0, 365.0,   0.0)
        score_10000 = compute_reserve_adequacy_score(0.0, 0.0, 10000.0, 0.0)
        self.assertEqual(score_365, score_10000)


# =========================================================================== #
# 5. compute_reserve_label
# =========================================================================== #

class TestComputeReserveLabel(unittest.TestCase):

    def test_fortress_reserves(self):
        label = compute_reserve_label(10.0, 5.0)
        self.assertEqual(label, LABEL_FORTRESS_RESERVES)

    def test_fortress_reserves_exactly_at_thresholds(self):
        label = compute_reserve_label(10.0, 5.0)
        self.assertEqual(label, LABEL_FORTRESS_RESERVES)

    def test_fortress_requires_both_conditions(self):
        # 10% ratio but only 4x coverage → not fortress
        label = compute_reserve_label(10.0, 4.9)
        self.assertNotEqual(label, LABEL_FORTRESS_RESERVES)

    def test_fortress_requires_both_conditions_ratio(self):
        # 5x coverage but only 9% ratio → not fortress
        label = compute_reserve_label(9.9, 5.0)
        self.assertNotEqual(label, LABEL_FORTRESS_RESERVES)

    def test_adequate_buffer(self):
        label = compute_reserve_label(5.0, 2.0)
        self.assertEqual(label, LABEL_ADEQUATE_BUFFER)

    def test_adequate_buffer_exactly_at_thresholds(self):
        label = compute_reserve_label(5.0, 2.0)
        self.assertEqual(label, LABEL_ADEQUATE_BUFFER)

    def test_adequate_buffer_high_ratio_low_coverage(self):
        # 8% ratio but only 1.9x coverage → not adequate (falls through to thin)
        label = compute_reserve_label(8.0, 1.9)
        self.assertEqual(label, LABEL_THIN_RESERVES)

    def test_thin_reserves(self):
        label = compute_reserve_label(2.0, 0.5)
        self.assertEqual(label, LABEL_THIN_RESERVES)

    def test_thin_reserves_at_exactly_2pct(self):
        label = compute_reserve_label(2.0, 0.1)
        self.assertEqual(label, LABEL_THIN_RESERVES)

    def test_underfunded(self):
        label = compute_reserve_label(0.5, 0.1)
        self.assertEqual(label, LABEL_UNDERFUNDED)

    def test_underfunded_at_exactly_05pct(self):
        label = compute_reserve_label(0.5, 0.0)
        self.assertEqual(label, LABEL_UNDERFUNDED)

    def test_critically_underfunded(self):
        label = compute_reserve_label(0.1, 0.0)
        self.assertEqual(label, LABEL_CRITICALLY_UNDERFUNDED)

    def test_zero_ratio(self):
        label = compute_reserve_label(0.0, 0.0)
        self.assertEqual(label, LABEL_CRITICALLY_UNDERFUNDED)

    def test_just_below_thin_threshold(self):
        label = compute_reserve_label(1.99, 1.0)
        self.assertEqual(label, LABEL_UNDERFUNDED)

    def test_just_above_underfunded_threshold(self):
        # 0.51% is between 0.5% and 2% → UNDERFUNDED (not THIN_RESERVES)
        label = compute_reserve_label(0.51, 0.0)
        self.assertEqual(label, LABEL_UNDERFUNDED)

    def test_high_ratio_high_coverage_is_fortress(self):
        label = compute_reserve_label(50.0, 100.0)
        self.assertEqual(label, LABEL_FORTRESS_RESERVES)

    def test_adequate_no_bad_debt_coverage_falls_through(self):
        # 6% ratio but 0x coverage → adequate needs >=2x → falls to thin
        label = compute_reserve_label(6.0, 1.5)
        self.assertEqual(label, LABEL_THIN_RESERVES)


# =========================================================================== #
# 6. _atomic_log_append (ring-buffer)
# =========================================================================== #

class TestAtomicLogAppend(unittest.TestCase):

    def setUp(self):
        self.log_path = _tmp_log()

    def tearDown(self):
        for p in [self.log_path, self.log_path + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def test_creates_file_if_missing(self):
        _atomic_log_append({"x": 1}, self.log_path, 100)
        self.assertTrue(os.path.exists(self.log_path))

    def test_single_entry_readable(self):
        _atomic_log_append({"k": "v"}, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["k"], "v")

    def test_multiple_entries_accumulate(self):
        for i in range(5):
            _atomic_log_append({"n": i}, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap_enforced(self):
        cap = 10
        for i in range(25):
            _atomic_log_append({"n": i}, self.log_path, cap)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), cap)

    def test_ring_buffer_keeps_latest_entries(self):
        cap = 5
        for i in range(10):
            _atomic_log_append({"n": i}, self.log_path, cap)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["n"], 5)
        self.assertEqual(data[-1]["n"], 9)

    def test_tmp_file_not_left_behind(self):
        _atomic_log_append({"k": 1}, self.log_path, 100)
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_invalid_existing_file_is_reset(self):
        with open(self.log_path, "w") as f:
            f.write("NOT JSON {{{")
        _atomic_log_append({"k": 1}, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_non_list_existing_file_is_reset(self):
        with open(self.log_path, "w") as f:
            json.dump({"bad": "structure"}, f)
        _atomic_log_append({"k": 2}, self.log_path, 100)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


# =========================================================================== #
# 7. DeFiProtocolYieldReserveBufferAnalyzer.analyze — output keys
# =========================================================================== #

class TestAnalyzeOutputKeys(unittest.TestCase):

    def setUp(self):
        self.result = _result()

    def test_has_protocol_name(self):
        self.assertIn("protocol_name", self.result)

    def test_has_reserve_usd(self):
        self.assertIn("reserve_usd", self.result)

    def test_has_total_tvl_usd(self):
        self.assertIn("total_tvl_usd", self.result)

    def test_has_bad_debt_history_usd(self):
        self.assertIn("bad_debt_history_usd", self.result)

    def test_has_daily_yield_usd(self):
        self.assertIn("daily_yield_usd", self.result)

    def test_has_insured_tvl_pct(self):
        self.assertIn("insured_tvl_pct", self.result)

    def test_has_reserve_ratio_pct(self):
        self.assertIn("reserve_ratio_pct", self.result)

    def test_has_bad_debt_coverage_ratio(self):
        self.assertIn("bad_debt_coverage_ratio", self.result)

    def test_has_days_to_deplete(self):
        self.assertIn("days_to_deplete", self.result)

    def test_has_reserve_adequacy_score(self):
        self.assertIn("reserve_adequacy_score", self.result)

    def test_has_reserve_label(self):
        self.assertIn("reserve_label", self.result)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)

    def test_timestamp_ends_with_z(self):
        self.assertTrue(self.result["timestamp"].endswith("Z"))

    def test_protocol_name_echoed(self):
        self.assertEqual(self.result["protocol_name"], "TestProto")

    def test_reserve_adequacy_score_is_int(self):
        self.assertIsInstance(self.result["reserve_adequacy_score"], int)

    def test_score_in_range(self):
        score = self.result["reserve_adequacy_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_reserve_label_is_string(self):
        self.assertIsInstance(self.result["reserve_label"], str)

    def test_reserve_label_is_valid(self):
        valid = {
            LABEL_FORTRESS_RESERVES, LABEL_ADEQUATE_BUFFER,
            LABEL_THIN_RESERVES, LABEL_UNDERFUNDED, LABEL_CRITICALLY_UNDERFUNDED,
        }
        self.assertIn(self.result["reserve_label"], valid)


# =========================================================================== #
# 8. DeFiProtocolYieldReserveBufferAnalyzer.analyze — label scenarios
# =========================================================================== #

class TestAnalyzeLabelScenarios(unittest.TestCase):

    def _a(self, **kw):
        return _result(**kw)

    def test_fortress_reserves_scenario(self):
        r = self._a(
            reserve_usd=50_000_000,
            total_tvl_usd=500_000_000,
            bad_debt_history_usd=5_000_000,
        )
        self.assertEqual(r["reserve_label"], LABEL_FORTRESS_RESERVES)

    def test_adequate_buffer_scenario(self):
        r = self._a(
            reserve_usd=5_000_000,
            total_tvl_usd=100_000_000,  # 5%
            bad_debt_history_usd=2_000_000,  # 2.5x coverage
        )
        self.assertEqual(r["reserve_label"], LABEL_ADEQUATE_BUFFER)

    def test_thin_reserves_scenario(self):
        r = self._a(
            reserve_usd=3_000_000,
            total_tvl_usd=100_000_000,  # 3%
            bad_debt_history_usd=5_000_000,  # 0.6x → not adequate
        )
        self.assertEqual(r["reserve_label"], LABEL_THIN_RESERVES)

    def test_underfunded_scenario(self):
        r = self._a(
            reserve_usd=1_000_000,
            total_tvl_usd=100_000_000,  # 1%
            bad_debt_history_usd=10_000_000,
        )
        self.assertEqual(r["reserve_label"], LABEL_UNDERFUNDED)

    def test_critically_underfunded_scenario(self):
        r = self._a(
            reserve_usd=100_000,
            total_tvl_usd=100_000_000,  # 0.1%
            bad_debt_history_usd=10_000_000,
        )
        self.assertEqual(r["reserve_label"], LABEL_CRITICALLY_UNDERFUNDED)

    def test_zero_reserve_is_critically_underfunded(self):
        r = self._a(reserve_usd=0, total_tvl_usd=100_000_000)
        self.assertEqual(r["reserve_label"], LABEL_CRITICALLY_UNDERFUNDED)

    def test_high_ratio_low_coverage_is_thin(self):
        # 12% ratio but bad debt >> reserve → low coverage
        r = self._a(
            reserve_usd=12_000_000,
            total_tvl_usd=100_000_000,  # 12% ratio
            bad_debt_history_usd=500_000_000,  # 0.024x coverage
        )
        # ratio >= 2% so THIN_RESERVES
        self.assertEqual(r["reserve_label"], LABEL_THIN_RESERVES)

    def test_exact_10pct_ratio_5x_coverage_is_fortress(self):
        r = self._a(
            reserve_usd=10_000,
            total_tvl_usd=100_000,   # exactly 10%
            bad_debt_history_usd=2_000,  # 5x coverage
        )
        self.assertEqual(r["reserve_label"], LABEL_FORTRESS_RESERVES)


# =========================================================================== #
# 9. DeFiProtocolYieldReserveBufferAnalyzer.analyze — computed values
# =========================================================================== #

class TestAnalyzeComputedValues(unittest.TestCase):

    def test_reserve_ratio_correct(self):
        r = _result(reserve_usd=5_000_000, total_tvl_usd=100_000_000)
        self.assertAlmostEqual(r["reserve_ratio_pct"], 5.0, places=4)

    def test_bad_debt_coverage_correct(self):
        r = _result(reserve_usd=10_000_000, bad_debt_history_usd=2_000_000)
        self.assertAlmostEqual(r["bad_debt_coverage_ratio"], 5.0, places=4)

    def test_days_to_deplete_correct(self):
        r = _result(reserve_usd=1_000_000, daily_yield_usd=10_000)
        self.assertAlmostEqual(r["days_to_deplete"], 100.0, places=2)

    def test_zero_tvl_gives_zero_ratio(self):
        r = _result(total_tvl_usd=0)
        self.assertEqual(r["reserve_ratio_pct"], 0.0)

    def test_zero_bad_debt_coverage_large(self):
        r = _result(reserve_usd=500_000, bad_debt_history_usd=0)
        self.assertAlmostEqual(r["bad_debt_coverage_ratio"], 500_000.0, places=0)

    def test_zero_daily_yield_caps_days(self):
        r = _result(reserve_usd=50_000, daily_yield_usd=0)
        self.assertEqual(r["days_to_deplete"], 99_999.0)

    def test_inputs_echoed_in_output(self):
        r = _result(
            reserve_usd=12_345.0,
            total_tvl_usd=999_000.0,
            bad_debt_history_usd=111.0,
            daily_yield_usd=222.0,
            insured_tvl_pct=33.3,
        )
        self.assertAlmostEqual(r["reserve_usd"], 12_345.0, places=2)
        self.assertAlmostEqual(r["total_tvl_usd"], 999_000.0, places=2)
        self.assertAlmostEqual(r["bad_debt_history_usd"], 111.0, places=2)
        self.assertAlmostEqual(r["daily_yield_usd"], 222.0, places=2)
        self.assertAlmostEqual(r["insured_tvl_pct"], 33.3, places=2)

    def test_string_inputs_coerced(self):
        a = _analyzer()
        r = a.analyze(
            protocol_name="P",
            reserve_usd="5000000",
            total_tvl_usd="100000000",
            bad_debt_history_usd="1000000",
            daily_yield_usd="10000",
            insured_tvl_pct="50",
        )
        self.assertAlmostEqual(r["reserve_ratio_pct"], 5.0, places=4)


# =========================================================================== #
# 10. DeFiProtocolYieldReserveBufferAnalyzer.analyze — logging
# =========================================================================== #

class TestAnalyzeLogging(unittest.TestCase):

    def setUp(self):
        self.log_path = _tmp_log()
        self.analyzer = DeFiProtocolYieldReserveBufferAnalyzer(log_path=self.log_path)

    def tearDown(self):
        for p in [self.log_path, self.log_path + ".tmp"]:
            if os.path.exists(p):
                os.unlink(p)

    def _call(self, name="P"):
        return self.analyzer.analyze(
            protocol_name=name,
            reserve_usd=5_000_000,
            total_tvl_usd=100_000_000,
            bad_debt_history_usd=500_000,
            daily_yield_usd=5_000,
            insured_tvl_pct=60.0,
        )

    def test_log_file_created_on_first_call(self):
        self._call()
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_contains_one_entry_after_one_call(self):
        self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_entry_has_protocol_name(self):
        self._call("AaveV3")
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["protocol_name"], "AaveV3")

    def test_log_entry_has_reserve_label(self):
        self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("reserve_label", data[0])

    def test_log_entry_has_timestamp(self):
        self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_multiple_calls_accumulate(self):
        for _ in range(5):
            self._call()
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap_100(self):
        for i in range(120):
            self._call(f"P{i}")
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)


# =========================================================================== #
# 11. DeFiProtocolYieldReserveBufferAnalyzer.analyze_batch
# =========================================================================== #

class TestAnalyzeBatch(unittest.TestCase):

    def _protocols(self):
        return [
            dict(protocol_name="A", reserve_usd=10_000_000, total_tvl_usd=100_000_000,
                 bad_debt_history_usd=1_000_000, daily_yield_usd=10_000, insured_tvl_pct=80.0),
            dict(protocol_name="B", reserve_usd=500_000,    total_tvl_usd=100_000_000,
                 bad_debt_history_usd=5_000_000, daily_yield_usd=500,    insured_tvl_pct=20.0),
        ]

    def test_returns_list(self):
        a = _analyzer()
        result = a.analyze_batch(self._protocols())
        self.assertIsInstance(result, list)

    def test_returns_correct_count(self):
        a = _analyzer()
        result = a.analyze_batch(self._protocols())
        self.assertEqual(len(result), 2)

    def test_order_preserved(self):
        a = _analyzer()
        result = a.analyze_batch(self._protocols())
        self.assertEqual(result[0]["protocol_name"], "A")
        self.assertEqual(result[1]["protocol_name"], "B")

    def test_empty_list_returns_empty(self):
        a = _analyzer()
        result = a.analyze_batch([])
        self.assertEqual(result, [])

    def test_each_result_has_reserve_label(self):
        a = _analyzer()
        for r in a.analyze_batch(self._protocols()):
            self.assertIn("reserve_label", r)

    def test_each_result_has_score(self):
        a = _analyzer()
        for r in a.analyze_batch(self._protocols()):
            self.assertIn("reserve_adequacy_score", r)

    def test_missing_keys_default_to_zero(self):
        a = _analyzer()
        result = a.analyze_batch([{"protocol_name": "Minimal"}])
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["reserve_ratio_pct"], 0.0, places=4)


# =========================================================================== #
# 12. DeFiProtocolYieldReserveBufferAnalyzer.rank_by_adequacy
# =========================================================================== #

class TestRankByAdequacy(unittest.TestCase):

    def _protocols(self):
        return [
            dict(protocol_name="Low",  reserve_usd=100_000,    total_tvl_usd=100_000_000,
                 bad_debt_history_usd=50_000_000, daily_yield_usd=100,    insured_tvl_pct=5.0),
            dict(protocol_name="High", reserve_usd=50_000_000, total_tvl_usd=500_000_000,
                 bad_debt_history_usd=2_000_000,  daily_yield_usd=100_000, insured_tvl_pct=90.0),
            dict(protocol_name="Mid",  reserve_usd=3_000_000,  total_tvl_usd=100_000_000,
                 bad_debt_history_usd=3_000_000,  daily_yield_usd=5_000,   insured_tvl_pct=40.0),
        ]

    def test_returns_list(self):
        a = _analyzer()
        ranked = a.rank_by_adequacy(self._protocols())
        self.assertIsInstance(ranked, list)

    def test_returns_correct_count(self):
        a = _analyzer()
        ranked = a.rank_by_adequacy(self._protocols())
        self.assertEqual(len(ranked), 3)

    def test_first_has_highest_score(self):
        a = _analyzer()
        ranked = a.rank_by_adequacy(self._protocols())
        scores = [r["reserve_adequacy_score"] for r in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_best_protocol_first(self):
        a = _analyzer()
        ranked = a.rank_by_adequacy(self._protocols())
        self.assertEqual(ranked[0]["protocol_name"], "High")

    def test_worst_protocol_last(self):
        a = _analyzer()
        ranked = a.rank_by_adequacy(self._protocols())
        self.assertEqual(ranked[-1]["protocol_name"], "Low")

    def test_empty_list_returns_empty(self):
        a = _analyzer()
        self.assertEqual(a.rank_by_adequacy([]), [])

    def test_single_item_rank(self):
        a = _analyzer()
        protocols = [dict(protocol_name="Solo", reserve_usd=1_000_000,
                          total_tvl_usd=10_000_000, bad_debt_history_usd=100_000,
                          daily_yield_usd=1_000, insured_tvl_pct=50.0)]
        ranked = a.rank_by_adequacy(protocols)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["protocol_name"], "Solo")


# =========================================================================== #
# 13. Edge cases and special inputs
# =========================================================================== #

class TestEdgeCases(unittest.TestCase):

    def test_all_zero_inputs(self):
        r = _result(
            reserve_usd=0,
            total_tvl_usd=0,
            bad_debt_history_usd=0,
            daily_yield_usd=0,
            insured_tvl_pct=0,
        )
        self.assertEqual(r["reserve_ratio_pct"], 0.0)
        self.assertEqual(r["reserve_label"], LABEL_CRITICALLY_UNDERFUNDED)
        self.assertEqual(r["reserve_adequacy_score"], 0)

    def test_insured_tvl_over_100_does_not_exceed_score(self):
        score = compute_reserve_adequacy_score(10.0, 5.0, 365.0, 200.0)
        self.assertEqual(score, 100)

    def test_negative_insured_tvl_gives_zero_component(self):
        score_neg  = compute_reserve_adequacy_score(0.0, 0.0, 0.0, -50.0)
        score_zero = compute_reserve_adequacy_score(0.0, 0.0, 0.0, 0.0)
        self.assertEqual(score_neg, score_zero)

    def test_float_coercion_of_int_inputs(self):
        r = _result(reserve_usd=5_000_000, total_tvl_usd=100_000_000,
                    bad_debt_history_usd=1_000_000, daily_yield_usd=10_000,
                    insured_tvl_pct=50)
        self.assertIsInstance(r["reserve_ratio_pct"], float)

    def test_very_large_reserve(self):
        # With insured_tvl_pct=100 all four components max out → score=100
        r = _result(reserve_usd=1e12, total_tvl_usd=1e10, insured_tvl_pct=100.0)
        self.assertGreater(r["reserve_ratio_pct"], 100.0)
        self.assertEqual(r["reserve_adequacy_score"], 100)

    def test_protocol_name_empty_string(self):
        r = _result(protocol_name="")
        self.assertEqual(r["protocol_name"], "")

    def test_protocol_name_unicode(self):
        r = _result(protocol_name="Протокол-α")
        self.assertEqual(r["protocol_name"], "Протокол-α")

    def test_days_to_deplete_with_tiny_daily_yield(self):
        r = _result(reserve_usd=1_000, daily_yield_usd=0.001)
        self.assertEqual(r["days_to_deplete"], 99_999.0)

    def test_exact_boundary_05pct_is_underfunded(self):
        ratio = compute_reserve_ratio_pct(500, 100_000)  # exactly 0.5%
        label = compute_reserve_label(ratio, 0.1)
        self.assertEqual(label, LABEL_UNDERFUNDED)

    def test_just_below_05pct_is_critically_underfunded(self):
        ratio = compute_reserve_ratio_pct(499, 100_000)  # 0.499%
        label = compute_reserve_label(ratio, 0.1)
        self.assertEqual(label, LABEL_CRITICALLY_UNDERFUNDED)


# =========================================================================== #
# 14. Label constants exposed
# =========================================================================== #

class TestLabelConstants(unittest.TestCase):

    def test_fortress_constant_value(self):
        self.assertEqual(LABEL_FORTRESS_RESERVES, "FORTRESS_RESERVES")

    def test_adequate_constant_value(self):
        self.assertEqual(LABEL_ADEQUATE_BUFFER, "ADEQUATE_BUFFER")

    def test_thin_constant_value(self):
        self.assertEqual(LABEL_THIN_RESERVES, "THIN_RESERVES")

    def test_underfunded_constant_value(self):
        self.assertEqual(LABEL_UNDERFUNDED, "UNDERFUNDED")

    def test_critically_underfunded_constant_value(self):
        self.assertEqual(LABEL_CRITICALLY_UNDERFUNDED, "CRITICALLY_UNDERFUNDED")

    def test_all_five_labels_are_distinct(self):
        labels = {
            LABEL_FORTRESS_RESERVES, LABEL_ADEQUATE_BUFFER,
            LABEL_THIN_RESERVES, LABEL_UNDERFUNDED, LABEL_CRITICALLY_UNDERFUNDED,
        }
        self.assertEqual(len(labels), 5)


if __name__ == "__main__":
    unittest.main()
