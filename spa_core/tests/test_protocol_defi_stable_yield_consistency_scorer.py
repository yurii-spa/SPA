"""
Tests for MP-1055: ProtocolDeFiStableYieldConsistencyScorer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_stable_yield_consistency_scorer
"""

import json
import math
import os
import statistics
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from spa_core.analytics.protocol_defi_stable_yield_consistency_scorer import (
    ProtocolDeFiStableYieldConsistencyScorer,
    _clamp,
    _safe_mean,
    _safe_stdev,
    _coefficient_of_variation,
    _cv_component,
    _yield_source_component,
    _rate_lock_component,
    _withdrawal_component,
    _compute_consistency_score,
    _compute_label,
    _atomic_append_log,
    _LOG_CAP,
    _CV_MAX_COMPONENT,
    _CV_ZERO_THRESHOLD,
    _YIELD_SOURCE_SCORES,
    _RATE_LOCK_BASE,
    _LOCK_DURATION_MAX_BONUS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CONSTANT_APY = [3.5] * 7   # std = 0
VOLATILE_APY = [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 13.0]  # cv > 0.5
SMOOTH_APY = [4.9, 5.0, 5.1, 5.0, 4.9, 5.1, 5.0]       # cv very small


def make_data(**overrides):
    base = {
        "protocol_name": "Aave V3",
        "apy_history": CONSTANT_APY[:],
        "current_apy_pct": 3.5,
        "yield_source": "lending_interest",
        "has_rate_lock": False,
        "lock_duration_days": 0.0,
        "min_deposit_usd": 0.0,
        "withdrawal_delay_days": 0.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. _clamp helper
# ---------------------------------------------------------------------------

class TestClamp(unittest.TestCase):
    def test_below_lo(self):
        self.assertEqual(_clamp(-5.0), 0.0)

    def test_above_hi(self):
        self.assertEqual(_clamp(150.0), 100.0)

    def test_within_range(self):
        self.assertAlmostEqual(_clamp(42.0), 42.0)

    def test_at_lo(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_at_hi(self):
        self.assertEqual(_clamp(100.0), 100.0)

    def test_custom_range(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_clamp_custom_hi(self):
        self.assertEqual(_clamp(20.0, 0.0, 10.0), 10.0)


# ---------------------------------------------------------------------------
# 2. _safe_mean
# ---------------------------------------------------------------------------

class TestSafeMean(unittest.TestCase):
    def test_empty_returns_zero(self):
        self.assertEqual(_safe_mean([]), 0.0)

    def test_single_value(self):
        self.assertAlmostEqual(_safe_mean([7.0]), 7.0)

    def test_two_values(self):
        self.assertAlmostEqual(_safe_mean([2.0, 4.0]), 3.0)

    def test_all_same(self):
        self.assertAlmostEqual(_safe_mean([5.0] * 10), 5.0)

    def test_known_mean(self):
        self.assertAlmostEqual(_safe_mean([1.0, 2.0, 3.0, 4.0, 5.0]), 3.0)

    def test_float_precision(self):
        mean = _safe_mean([3.3, 3.3, 3.3, 3.3])
        self.assertAlmostEqual(mean, 3.3, places=5)

    def test_large_values(self):
        self.assertAlmostEqual(_safe_mean([1000.0, 2000.0, 3000.0]), 2000.0)

    def test_zeros(self):
        self.assertAlmostEqual(_safe_mean([0.0, 0.0, 0.0]), 0.0)


# ---------------------------------------------------------------------------
# 3. _safe_stdev
# ---------------------------------------------------------------------------

class TestSafeStdev(unittest.TestCase):
    def test_empty_returns_zero(self):
        self.assertEqual(_safe_stdev([]), 0.0)

    def test_single_value_returns_zero(self):
        self.assertEqual(_safe_stdev([5.0]), 0.0)

    def test_all_same_returns_zero(self):
        self.assertAlmostEqual(_safe_stdev([3.0] * 7), 0.0)

    def test_two_different_values(self):
        # std([1,3]) = 1.414... (sample)
        std = _safe_stdev([1.0, 3.0])
        self.assertAlmostEqual(std, math.sqrt(2.0), places=4)

    def test_known_values(self):
        # Verify _safe_stdev matches statistics.stdev (sample, N-1 denominator)
        vals = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        self.assertAlmostEqual(_safe_stdev(vals), statistics.stdev(vals), places=6)

    def test_stdev_is_sample(self):
        vals = [1.0, 2.0, 3.0]
        self.assertAlmostEqual(_safe_stdev(vals), statistics.stdev(vals), places=6)

    def test_positive_std(self):
        self.assertGreater(_safe_stdev([1.0, 5.0, 9.0, 2.0, 7.0, 3.0, 8.0]), 0.0)


# ---------------------------------------------------------------------------
# 4. _coefficient_of_variation
# ---------------------------------------------------------------------------

class TestCoefficientOfVariation(unittest.TestCase):
    def test_zero_mean_returns_zero(self):
        self.assertEqual(_coefficient_of_variation(1.0, 0.0), 0.0)

    def test_zero_std_returns_zero(self):
        self.assertAlmostEqual(_coefficient_of_variation(0.0, 5.0), 0.0)

    def test_equal_std_and_mean(self):
        self.assertAlmostEqual(_coefficient_of_variation(3.0, 3.0), 1.0)

    def test_half_cv(self):
        self.assertAlmostEqual(_coefficient_of_variation(1.0, 2.0), 0.5)

    def test_low_cv(self):
        self.assertAlmostEqual(_coefficient_of_variation(0.1, 5.0), 0.02)

    def test_cv_positive_for_positive_std_and_mean(self):
        cv = _coefficient_of_variation(2.0, 8.0)
        self.assertGreater(cv, 0.0)


# ---------------------------------------------------------------------------
# 5. _cv_component
# ---------------------------------------------------------------------------

class TestCVComponent(unittest.TestCase):
    def test_cv_zero(self):
        self.assertAlmostEqual(_cv_component(0.0), _CV_MAX_COMPONENT)

    def test_cv_at_threshold(self):
        self.assertAlmostEqual(_cv_component(_CV_ZERO_THRESHOLD), 0.0)

    def test_cv_above_threshold(self):
        self.assertAlmostEqual(_cv_component(0.6), 0.0)

    def test_cv_well_above_threshold(self):
        self.assertAlmostEqual(_cv_component(1.5), 0.0)

    def test_cv_half_of_threshold(self):
        # cv = 0.25 → 70*(1-0.5) = 35
        self.assertAlmostEqual(_cv_component(0.25), 35.0)

    def test_cv_0_1(self):
        # cv = 0.1 → 70*(1-0.2) = 56
        self.assertAlmostEqual(_cv_component(0.1), 56.0)

    def test_cv_0_2(self):
        # cv = 0.2 → 70*(1-0.4) = 42
        self.assertAlmostEqual(_cv_component(0.2), 42.0)

    def test_cv_0_3(self):
        # cv = 0.3 → 70*(1-0.6) = 28
        self.assertAlmostEqual(_cv_component(0.3), 28.0)

    def test_cv_0_4(self):
        # cv = 0.4 → 70*(1-0.8) = 14
        self.assertAlmostEqual(_cv_component(0.4), 14.0)

    def test_cv_not_negative(self):
        for cv in [0.0, 0.25, 0.5, 0.75, 1.0]:
            self.assertGreaterEqual(_cv_component(cv), 0.0)

    def test_cv_max_at_zero(self):
        self.assertAlmostEqual(_cv_component(0.0), 70.0)

    def test_cv_monotonically_decreasing(self):
        vals = [_cv_component(cv / 10.0) for cv in range(0, 11)]
        for i in range(len(vals) - 1):
            self.assertGreaterEqual(vals[i], vals[i + 1])


# ---------------------------------------------------------------------------
# 6. _yield_source_component
# ---------------------------------------------------------------------------

class TestYieldSourceComponent(unittest.TestCase):
    def test_real_yield(self):
        self.assertAlmostEqual(_yield_source_component("real_yield"), 20.0)

    def test_lending_interest(self):
        self.assertAlmostEqual(_yield_source_component("lending_interest"), 15.0)

    def test_trading_fees(self):
        self.assertAlmostEqual(_yield_source_component("trading_fees"), 8.0)

    def test_emissions(self):
        self.assertAlmostEqual(_yield_source_component("emissions"), 0.0)

    def test_unknown_source(self):
        self.assertAlmostEqual(_yield_source_component("unknown_type"), 5.0)

    def test_empty_string(self):
        self.assertAlmostEqual(_yield_source_component(""), 5.0)

    def test_case_sensitive(self):
        # Wrong case → default score
        self.assertAlmostEqual(_yield_source_component("Real_Yield"), 5.0)

    def test_real_yield_highest(self):
        self.assertGreater(
            _yield_source_component("real_yield"),
            _yield_source_component("emissions"),
        )

    def test_known_source_values(self):
        self.assertIn("real_yield", _YIELD_SOURCE_SCORES)
        self.assertIn("emissions", _YIELD_SOURCE_SCORES)


# ---------------------------------------------------------------------------
# 7. _rate_lock_component
# ---------------------------------------------------------------------------

class TestRateLockComponent(unittest.TestCase):
    def test_no_lock_returns_zero(self):
        self.assertAlmostEqual(_rate_lock_component(False, 0.0), 0.0)

    def test_no_lock_with_duration_still_zero(self):
        self.assertAlmostEqual(_rate_lock_component(False, 90.0), 0.0)

    def test_lock_zero_duration(self):
        # Just the base: 5 pts
        self.assertAlmostEqual(_rate_lock_component(True, 0.0), _RATE_LOCK_BASE)

    def test_lock_full_duration_90d(self):
        # 5 + 3 = 8
        self.assertAlmostEqual(
            _rate_lock_component(True, 90.0),
            _RATE_LOCK_BASE + _LOCK_DURATION_MAX_BONUS,
        )

    def test_lock_half_duration_45d(self):
        # 5 + 1.5 = 6.5
        self.assertAlmostEqual(_rate_lock_component(True, 45.0), 6.5)

    def test_lock_30d(self):
        # 5 + min(3, 30/90*3) = 5 + 1.0 = 6.0
        self.assertAlmostEqual(_rate_lock_component(True, 30.0), 6.0)

    def test_lock_beyond_saturation_capped(self):
        # 180d > 90d → same as 90d
        score_90 = _rate_lock_component(True, 90.0)
        score_180 = _rate_lock_component(True, 180.0)
        self.assertAlmostEqual(score_90, score_180)

    def test_lock_max_is_8(self):
        score = _rate_lock_component(True, 365.0)
        self.assertAlmostEqual(score, _RATE_LOCK_BASE + _LOCK_DURATION_MAX_BONUS)


# ---------------------------------------------------------------------------
# 8. _withdrawal_component
# ---------------------------------------------------------------------------

class TestWithdrawalComponent(unittest.TestCase):
    def test_zero_days(self):
        self.assertAlmostEqual(_withdrawal_component(0.0), 0.0)

    def test_5_days(self):
        # min(2, 5/10*2) = 1.0
        self.assertAlmostEqual(_withdrawal_component(5.0), 1.0)

    def test_10_days_full(self):
        # min(2, 10/10*2) = 2.0
        self.assertAlmostEqual(_withdrawal_component(10.0), 2.0)

    def test_beyond_saturation_clamped(self):
        # 20d > 10d → still 2.0
        self.assertAlmostEqual(_withdrawal_component(20.0), 2.0)

    def test_negative_clamped_to_zero(self):
        self.assertAlmostEqual(_withdrawal_component(-5.0), 0.0)

    def test_max_is_2(self):
        self.assertAlmostEqual(_withdrawal_component(100.0), 2.0)


# ---------------------------------------------------------------------------
# 9. _compute_consistency_score
# ---------------------------------------------------------------------------

class TestComputeConsistencyScore(unittest.TestCase):
    def test_perfect_score(self):
        # cv=0, real_yield, lock=True 90d, withdrawal=10d → 70+20+8+2 = 100
        score = _compute_consistency_score(0.0, "real_yield", True, 90.0, 10.0)
        self.assertAlmostEqual(score, 100.0)

    def test_zero_score(self):
        # cv >= 0.5, emissions, no lock, no withdrawal
        score = _compute_consistency_score(0.5, "emissions", False, 0.0, 0.0)
        self.assertAlmostEqual(score, 0.0)

    def test_emissions_reduces_score_vs_real_yield(self):
        base = _compute_consistency_score(0.1, "real_yield", False, 0.0, 0.0)
        lower = _compute_consistency_score(0.1, "emissions", False, 0.0, 0.0)
        self.assertGreater(base, lower)

    def test_lock_adds_points(self):
        no_lock = _compute_consistency_score(0.1, "lending_interest", False, 0.0, 0.0)
        with_lock = _compute_consistency_score(0.1, "lending_interest", True, 90.0, 0.0)
        self.assertGreater(with_lock, no_lock)

    def test_withdrawal_adds_points(self):
        no_wd = _compute_consistency_score(0.1, "lending_interest", False, 0.0, 0.0)
        with_wd = _compute_consistency_score(0.1, "lending_interest", False, 0.0, 10.0)
        self.assertGreater(with_wd, no_wd)

    def test_score_in_range(self):
        for cv in [0.0, 0.2, 0.5, 0.8]:
            for src in ["real_yield", "emissions", "lending_interest"]:
                for lock in [True, False]:
                    s = _compute_consistency_score(cv, src, lock, 90.0, 5.0)
                    self.assertGreaterEqual(s, 0.0)
                    self.assertLessEqual(s, 100.0)

    def test_clamped_not_above_100(self):
        score = _compute_consistency_score(0.0, "real_yield", True, 365.0, 100.0)
        self.assertLessEqual(score, 100.0)

    def test_clamped_not_below_zero(self):
        score = _compute_consistency_score(1.0, "emissions", False, 0.0, 0.0)
        self.assertGreaterEqual(score, 0.0)


# ---------------------------------------------------------------------------
# 10. _compute_label
# ---------------------------------------------------------------------------

class TestComputeLabel(unittest.TestCase):
    def test_zero_is_unpredictable(self):
        self.assertEqual(_compute_label(0.0), "UNPREDICTABLE")

    def test_10_is_unpredictable(self):
        self.assertEqual(_compute_label(10.0), "UNPREDICTABLE")

    def test_19_is_unpredictable(self):
        self.assertEqual(_compute_label(19.9), "UNPREDICTABLE")

    def test_at_20_is_volatile(self):
        self.assertEqual(_compute_label(20.0), "VOLATILE_YIELD")

    def test_30_is_volatile(self):
        self.assertEqual(_compute_label(30.0), "VOLATILE_YIELD")

    def test_39_is_volatile(self):
        self.assertEqual(_compute_label(39.9), "VOLATILE_YIELD")

    def test_at_40_is_moderately_consistent(self):
        self.assertEqual(_compute_label(40.0), "MODERATELY_CONSISTENT")

    def test_50_is_moderately_consistent(self):
        self.assertEqual(_compute_label(50.0), "MODERATELY_CONSISTENT")

    def test_59_is_moderately_consistent(self):
        self.assertEqual(_compute_label(59.9), "MODERATELY_CONSISTENT")

    def test_at_60_is_very_consistent(self):
        self.assertEqual(_compute_label(60.0), "VERY_CONSISTENT")

    def test_70_is_very_consistent(self):
        self.assertEqual(_compute_label(70.0), "VERY_CONSISTENT")

    def test_79_is_very_consistent(self):
        self.assertEqual(_compute_label(79.9), "VERY_CONSISTENT")

    def test_at_80_is_rock_solid(self):
        self.assertEqual(_compute_label(80.0), "ROCK_SOLID")

    def test_100_is_rock_solid(self):
        self.assertEqual(_compute_label(100.0), "ROCK_SOLID")

    def test_all_five_labels_producible(self):
        labels = {
            _compute_label(5.0),
            _compute_label(25.0),
            _compute_label(45.0),
            _compute_label(65.0),
            _compute_label(90.0),
        }
        expected = {
            "UNPREDICTABLE", "VOLATILE_YIELD",
            "MODERATELY_CONSISTENT", "VERY_CONSISTENT", "ROCK_SOLID",
        }
        self.assertEqual(labels, expected)


# ---------------------------------------------------------------------------
# 11. score() method
# ---------------------------------------------------------------------------

class TestScoreMethod(unittest.TestCase):
    def _make_scorer(self):
        tmp = tempfile.mktemp(suffix=".json")
        return ProtocolDeFiStableYieldConsistencyScorer(log_path=tmp), tmp

    def test_output_keys_present(self):
        scorer, _ = self._make_scorer()
        result = scorer.score(make_data(), write_log=False)
        expected_keys = {
            "protocol_name", "apy_mean_pct", "apy_std_pct",
            "coefficient_of_variation", "consistency_score",
            "predictability_label", "analyzed_at",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_mean_computed_correctly(self):
        scorer, _ = self._make_scorer()
        result = scorer.score(make_data(apy_history=[2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0]),
                              write_log=False)
        self.assertAlmostEqual(result["apy_mean_pct"], 8.0, places=3)

    def test_std_computed_correctly(self):
        scorer, _ = self._make_scorer()
        result = scorer.score(make_data(apy_history=CONSTANT_APY), write_log=False)
        self.assertAlmostEqual(result["apy_std_pct"], 0.0, places=5)

    def test_cv_zero_for_constant_history(self):
        scorer, _ = self._make_scorer()
        result = scorer.score(make_data(apy_history=CONSTANT_APY), write_log=False)
        self.assertAlmostEqual(result["coefficient_of_variation"], 0.0, places=5)

    def test_cv_positive_for_volatile_history(self):
        scorer, _ = self._make_scorer()
        result = scorer.score(make_data(apy_history=VOLATILE_APY), write_log=False)
        self.assertGreater(result["coefficient_of_variation"], 0.0)

    def test_consistency_score_float(self):
        scorer, _ = self._make_scorer()
        result = scorer.score(make_data(), write_log=False)
        self.assertIsInstance(result["consistency_score"], float)

    def test_consistency_score_in_range(self):
        scorer, _ = self._make_scorer()
        for history in [CONSTANT_APY, VOLATILE_APY, SMOOTH_APY]:
            result = scorer.score(make_data(apy_history=history), write_log=False)
            self.assertGreaterEqual(result["consistency_score"], 0.0)
            self.assertLessEqual(result["consistency_score"], 100.0)

    def test_label_is_valid(self):
        valid = {"UNPREDICTABLE", "VOLATILE_YIELD", "MODERATELY_CONSISTENT",
                 "VERY_CONSISTENT", "ROCK_SOLID"}
        scorer, _ = self._make_scorer()
        result = scorer.score(make_data(), write_log=False)
        self.assertIn(result["predictability_label"], valid)

    def test_protocol_name_echoed(self):
        scorer, _ = self._make_scorer()
        result = scorer.score(make_data(protocol_name="TestProto"), write_log=False)
        self.assertEqual(result["protocol_name"], "TestProto")

    def test_analyzed_at_present(self):
        scorer, _ = self._make_scorer()
        result = scorer.score(make_data(), write_log=False)
        self.assertIn("T", result["analyzed_at"])
        self.assertGreater(len(result["analyzed_at"]), 10)

    def test_constant_history_high_score(self):
        # cv=0 → high consistency
        scorer, _ = self._make_scorer()
        result = scorer.score(
            make_data(apy_history=CONSTANT_APY, yield_source="real_yield"),
            write_log=False,
        )
        self.assertGreater(result["consistency_score"], 70.0)

    def test_volatile_history_low_score(self):
        scorer, _ = self._make_scorer()
        result = scorer.score(
            make_data(apy_history=VOLATILE_APY, yield_source="emissions",
                      has_rate_lock=False, withdrawal_delay_days=0.0),
            write_log=False,
        )
        self.assertLess(result["consistency_score"], 20.0)

    def test_rock_solid_scenario(self):
        scorer, _ = self._make_scorer()
        result = scorer.score(
            make_data(
                apy_history=CONSTANT_APY,
                yield_source="real_yield",
                has_rate_lock=True,
                lock_duration_days=90.0,
                withdrawal_delay_days=10.0,
            ),
            write_log=False,
        )
        self.assertEqual(result["predictability_label"], "ROCK_SOLID")

    def test_unpredictable_scenario(self):
        scorer, _ = self._make_scorer()
        result = scorer.score(
            make_data(
                apy_history=VOLATILE_APY,
                yield_source="emissions",
                has_rate_lock=False,
                lock_duration_days=0.0,
                withdrawal_delay_days=0.0,
            ),
            write_log=False,
        )
        self.assertEqual(result["predictability_label"], "UNPREDICTABLE")

    def test_emissions_lower_score_than_real_yield(self):
        scorer, _ = self._make_scorer()
        r_real = scorer.score(
            make_data(yield_source="real_yield"), write_log=False
        )
        r_emit = scorer.score(
            make_data(yield_source="emissions"), write_log=False
        )
        self.assertGreater(r_real["consistency_score"], r_emit["consistency_score"])

    def test_rate_lock_increases_score(self):
        scorer, _ = self._make_scorer()
        r_no_lock = scorer.score(
            make_data(has_rate_lock=False), write_log=False
        )
        r_lock = scorer.score(
            make_data(has_rate_lock=True, lock_duration_days=90.0), write_log=False
        )
        self.assertGreater(r_lock["consistency_score"], r_no_lock["consistency_score"])

    def test_write_log_false(self):
        tmp = tempfile.mktemp(suffix=".json")
        scorer = ProtocolDeFiStableYieldConsistencyScorer(log_path=tmp)
        scorer.score(make_data(), write_log=False)
        self.assertFalse(os.path.exists(tmp))

    def test_write_log_true(self):
        tmp = tempfile.mktemp(suffix=".json")
        scorer = ProtocolDeFiStableYieldConsistencyScorer(log_path=tmp)
        try:
            scorer.score(make_data(), write_log=True)
            self.assertTrue(os.path.exists(tmp))
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_result_deterministic(self):
        scorer, _ = self._make_scorer()
        data = make_data()
        r1 = scorer.score(data, write_log=False)
        r2 = scorer.score(data, write_log=False)
        self.assertEqual(r1["consistency_score"], r2["consistency_score"])
        self.assertEqual(r1["predictability_label"], r2["predictability_label"])

    def test_very_consistent_scenario(self):
        scorer, _ = self._make_scorer()
        result = scorer.score(
            make_data(
                apy_history=SMOOTH_APY,
                yield_source="lending_interest",
                has_rate_lock=False,
                withdrawal_delay_days=0.0,
            ),
            write_log=False,
        )
        # smooth APY + lending_interest → should be at least moderately consistent
        self.assertGreater(result["consistency_score"], 50.0)


# ---------------------------------------------------------------------------
# 12. Log / ring-buffer behaviour
# ---------------------------------------------------------------------------

class TestLogBehaviour(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def test_log_creates_file(self):
        _atomic_append_log(self.tmp, {"x": 1})
        self.assertTrue(os.path.exists(self.tmp))

    def test_log_first_entry(self):
        _atomic_append_log(self.tmp, {"val": 99})
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["val"], 99)

    def test_log_appends_multiple(self):
        for i in range(5):
            _atomic_append_log(self.tmp, {"i": i})
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)
        self.assertEqual(data[-1]["i"], 4)

    def test_ring_buffer_cap(self):
        for i in range(_LOG_CAP + 15):
            _atomic_append_log(self.tmp, {"i": i}, cap=_LOG_CAP)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_CAP)

    def test_ring_buffer_keeps_latest(self):
        for i in range(8):
            _atomic_append_log(self.tmp, {"i": i}, cap=3)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)
        self.assertEqual(data[-1]["i"], 7)

    def test_invalid_json_resets(self):
        with open(self.tmp, "w") as f:
            f.write("<<INVALID>>")
        _atomic_append_log(self.tmp, {"x": 1})
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_non_list_json_resets(self):
        with open(self.tmp, "w") as f:
            json.dump({"key": "value"}, f)
        _atomic_append_log(self.tmp, {"x": 1})
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_output_is_valid_json(self):
        _atomic_append_log(self.tmp, {"key": "val"})
        with open(self.tmp) as f:
            content = f.read()
        json.loads(content)  # must not raise

    def test_scorer_writes_log_entry(self):
        scorer = ProtocolDeFiStableYieldConsistencyScorer(log_path=self.tmp)
        scorer.score(make_data(), write_log=True)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertIn("consistency_score", data[0])
        self.assertIn("predictability_label", data[0])

    def test_scorer_multiple_writes(self):
        scorer = ProtocolDeFiStableYieldConsistencyScorer(log_path=self.tmp)
        for _ in range(4):
            scorer.score(make_data(), write_log=True)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 4)


# ---------------------------------------------------------------------------
# 13. Static method API
# ---------------------------------------------------------------------------

class TestStaticMethods(unittest.TestCase):
    def test_compute_mean_static(self):
        m = ProtocolDeFiStableYieldConsistencyScorer.compute_mean([2.0, 4.0, 6.0])
        self.assertAlmostEqual(m, 4.0)

    def test_compute_std_static(self):
        s = ProtocolDeFiStableYieldConsistencyScorer.compute_std(CONSTANT_APY)
        self.assertAlmostEqual(s, 0.0, places=5)

    def test_compute_cv_static(self):
        cv = ProtocolDeFiStableYieldConsistencyScorer.compute_cv(0.0, 5.0)
        self.assertAlmostEqual(cv, 0.0)

    def test_cv_component_static(self):
        val = ProtocolDeFiStableYieldConsistencyScorer.cv_component(0.0)
        self.assertAlmostEqual(val, 70.0)

    def test_yield_source_component_static(self):
        val = ProtocolDeFiStableYieldConsistencyScorer.yield_source_component("real_yield")
        self.assertAlmostEqual(val, 20.0)

    def test_rate_lock_component_static(self):
        val = ProtocolDeFiStableYieldConsistencyScorer.rate_lock_component(False, 0.0)
        self.assertAlmostEqual(val, 0.0)

    def test_withdrawal_component_static(self):
        val = ProtocolDeFiStableYieldConsistencyScorer.withdrawal_component(10.0)
        self.assertAlmostEqual(val, 2.0)

    def test_consistency_score_static(self):
        val = ProtocolDeFiStableYieldConsistencyScorer.consistency_score(
            0.0, "real_yield", True, 90.0, 10.0
        )
        self.assertAlmostEqual(val, 100.0)

    def test_label_for_static(self):
        self.assertEqual(
            ProtocolDeFiStableYieldConsistencyScorer.label_for(90.0), "ROCK_SOLID"
        )

    def test_label_for_unpredictable_static(self):
        self.assertEqual(
            ProtocolDeFiStableYieldConsistencyScorer.label_for(5.0), "UNPREDICTABLE"
        )


if __name__ == "__main__":
    unittest.main()
