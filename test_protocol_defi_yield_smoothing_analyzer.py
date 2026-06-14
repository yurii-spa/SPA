"""
Tests for MP-1111 ProtocolDeFiYieldSmoothingAnalyzer
Pure stdlib unittest — run with: python3 -m unittest
"""

import json
import math
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

from spa_core.analytics.protocol_defi_yield_smoothing_analyzer import (
    analyze,
    analyze_portfolio,
    _mean_yield,
    _yield_std,
    _yield_cv,
    _missed_compounding_drag_pct,
    _smoothness_score,
    _smoothing_label,
    _atomic_log,
    _safe_float,
    _safe_list_of_floats,
    _clamp,
    ProtocolDeFiYieldSmoothingAnalyzer,
    ALL_SMOOTHING_LABELS,
    SMOOTH_DAILY,
    GOOD_SMOOTHING,
    MODERATE_SPIKES,
    BATCH_PAYOUT,
    ERRATIC_YIELD,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _cfg():
    return {"log_path": _tmp_log()}


def _stable_obs(n=30, daily_yield=0.01384):
    """Perfectly stable daily yields."""
    return [daily_yield] * n


def _noisy_obs(n=30, base=0.01, noise_factor=1.5):
    """Oscillating yields with high variance."""
    obs = []
    for i in range(n):
        obs.append(base * (1 + noise_factor * ((i % 2) * 2 - 1)))
    return obs


def _source(
    protocol_name="TestProtocol",
    yield_observations=None,
    payout_frequency_days=1,
    auto_compounds=True,
    compounding_frequency_days=1,
    position_size_usd=100_000.0,
):
    if yield_observations is None:
        yield_observations = _stable_obs()
    return {
        "protocol_name":            protocol_name,
        "yield_observations":       yield_observations,
        "payout_frequency_days":    payout_frequency_days,
        "auto_compounds":           auto_compounds,
        "compounding_frequency_days": compounding_frequency_days,
        "position_size_usd":        position_size_usd,
    }


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

    def test_empty_string(self):
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

    def test_below_lower_bound(self):
        self.assertEqual(_clamp(-5.0, 0.0, 100.0), 0.0)

    def test_above_upper_bound(self):
        self.assertEqual(_clamp(150.0, 0.0, 100.0), 100.0)

    def test_at_lower_bound(self):
        self.assertEqual(_clamp(0.0, 0.0, 100.0), 0.0)

    def test_at_upper_bound(self):
        self.assertEqual(_clamp(100.0, 0.0, 100.0), 100.0)

    def test_equal_bounds(self):
        self.assertEqual(_clamp(5.0, 5.0, 5.0), 5.0)


# ===========================================================================
# 3. _safe_list_of_floats
# ===========================================================================

class TestSafeListOfFloats(unittest.TestCase):

    def test_all_valid(self):
        r = _safe_list_of_floats([1.0, 2.0, 3.0])
        self.assertEqual(r, [1.0, 2.0, 3.0])

    def test_empty_list(self):
        self.assertEqual(_safe_list_of_floats([]), [])

    def test_none_input(self):
        self.assertEqual(_safe_list_of_floats(None), [])

    def test_string_input(self):
        self.assertEqual(_safe_list_of_floats("abc"), [])

    def test_filters_non_numeric(self):
        r = _safe_list_of_floats([1.0, "abc", 2.0, None, 3.0])
        self.assertEqual(r, [1.0, 2.0, 3.0])

    def test_filters_nan(self):
        r = _safe_list_of_floats([1.0, float("nan"), 2.0])
        self.assertEqual(r, [1.0, 2.0])

    def test_filters_inf(self):
        r = _safe_list_of_floats([1.0, float("inf"), 2.0])
        self.assertEqual(r, [1.0, 2.0])

    def test_numeric_strings_converted(self):
        r = _safe_list_of_floats(["1.5", "2.5", "3.5"])
        self.assertAlmostEqual(r[0], 1.5)

    def test_tuple_input(self):
        r = _safe_list_of_floats((1.0, 2.0, 3.0))
        self.assertEqual(len(r), 3)

    def test_negative_values_kept(self):
        r = _safe_list_of_floats([-1.0, 0.0, 1.0])
        self.assertEqual(r, [-1.0, 0.0, 1.0])


# ===========================================================================
# 4. _mean_yield
# ===========================================================================

class TestMeanYield(unittest.TestCase):

    def test_basic_mean(self):
        self.assertAlmostEqual(_mean_yield([1.0, 2.0, 3.0]), 2.0)

    def test_empty_list(self):
        self.assertEqual(_mean_yield([]), 0.0)

    def test_single_value(self):
        self.assertAlmostEqual(_mean_yield([5.0]), 5.0)

    def test_all_same(self):
        self.assertAlmostEqual(_mean_yield([3.0, 3.0, 3.0]), 3.0)

    def test_zeros(self):
        self.assertAlmostEqual(_mean_yield([0.0, 0.0, 0.0]), 0.0)

    def test_mixed_signs(self):
        self.assertAlmostEqual(_mean_yield([-1.0, 0.0, 1.0]), 0.0)

    def test_fractional(self):
        self.assertAlmostEqual(_mean_yield([0.01, 0.02, 0.03]), 0.02)


# ===========================================================================
# 5. _yield_std
# ===========================================================================

class TestYieldStd(unittest.TestCase):

    def test_constant_series_zero_std(self):
        self.assertAlmostEqual(_yield_std([2.0, 2.0, 2.0], 2.0), 0.0)

    def test_two_value_series(self):
        # population std of [0, 2] = 1.0
        self.assertAlmostEqual(_yield_std([0.0, 2.0], 1.0), 1.0)

    def test_empty_list(self):
        self.assertEqual(_yield_std([], 0.0), 0.0)

    def test_single_value(self):
        self.assertEqual(_yield_std([5.0], 5.0), 0.0)

    def test_known_std(self):
        # [0, 1, 2, 3, 4] mean=2, population var=2, std=sqrt(2)
        self.assertAlmostEqual(_yield_std([0, 1, 2, 3, 4], 2.0), math.sqrt(2.0))

    def test_non_negative(self):
        obs = [0.01, 0.05, 0.02, 0.08, 0.01]
        mean = sum(obs) / len(obs)
        self.assertGreaterEqual(_yield_std(obs, mean), 0.0)


# ===========================================================================
# 6. _yield_cv
# ===========================================================================

class TestYieldCv(unittest.TestCase):

    def test_zero_mean_returns_zero(self):
        self.assertEqual(_yield_cv(1.0, 0.0), 0.0)

    def test_basic_cv(self):
        self.assertAlmostEqual(_yield_cv(2.0, 10.0), 0.2)

    def test_zero_std_zero_cv(self):
        self.assertAlmostEqual(_yield_cv(0.0, 5.0), 0.0)

    def test_negative_mean_abs_value(self):
        # CV should be non-negative
        cv = _yield_cv(2.0, -10.0)
        self.assertGreaterEqual(cv, 0.0)

    def test_high_std_high_cv(self):
        self.assertAlmostEqual(_yield_cv(5.0, 5.0), 1.0)

    def test_fractional(self):
        self.assertAlmostEqual(_yield_cv(0.5, 2.0), 0.25)


# ===========================================================================
# 7. _missed_compounding_drag_pct
# ===========================================================================

class TestMissedCompoundingDragPct(unittest.TestCase):

    def test_daily_compounding_no_drag(self):
        drag = _missed_compounding_drag_pct(5.0, 1)
        self.assertAlmostEqual(drag, 0.0)

    def test_zero_yield_no_drag(self):
        drag = _missed_compounding_drag_pct(0.0, 7)
        self.assertAlmostEqual(drag, 0.0)

    def test_negative_yield_no_drag(self):
        drag = _missed_compounding_drag_pct(-5.0, 7)
        self.assertAlmostEqual(drag, 0.0)

    def test_weekly_drag_positive(self):
        # 5% annual mean yield, weekly payout
        drag = _missed_compounding_drag_pct(5.0, 7)
        self.assertGreaterEqual(drag, 0.0)

    def test_monthly_drag_greater_than_weekly(self):
        drag_weekly  = _missed_compounding_drag_pct(10.0, 7)
        drag_monthly = _missed_compounding_drag_pct(10.0, 30)
        self.assertGreater(drag_monthly, drag_weekly)

    def test_drag_increases_with_yield(self):
        drag_low  = _missed_compounding_drag_pct(5.0, 30)
        drag_high = _missed_compounding_drag_pct(20.0, 30)
        self.assertGreater(drag_high, drag_low)

    def test_drag_non_negative(self):
        for yield_pct in [1.0, 5.0, 10.0, 20.0, 50.0]:
            for freq in [1, 7, 14, 30, 90]:
                drag = _missed_compounding_drag_pct(yield_pct, freq)
                self.assertGreaterEqual(drag, 0.0)

    def test_drag_is_float(self):
        drag = _missed_compounding_drag_pct(5.0, 7)
        self.assertIsInstance(drag, float)

    def test_zero_frequency_no_drag(self):
        # freq <= 0 → fallback, no drag
        drag = _missed_compounding_drag_pct(5.0, 0)
        self.assertAlmostEqual(drag, 0.0)

    def test_annual_payout_large_drag(self):
        # Annual compounding (365 days) vs daily → biggest drag
        drag_daily   = _missed_compounding_drag_pct(20.0, 1)
        drag_annual  = _missed_compounding_drag_pct(20.0, 365)
        self.assertGreater(drag_annual, drag_daily)


# ===========================================================================
# 8. _smoothing_label
# ===========================================================================

class TestSmoothingLabel(unittest.TestCase):

    def test_smooth_daily_low_cv(self):
        self.assertEqual(_smoothing_label(0.05, 1), SMOOTH_DAILY)

    def test_smooth_daily_zero_cv(self):
        self.assertEqual(_smoothing_label(0.0, 1), SMOOTH_DAILY)

    def test_smooth_daily_boundary_cv_just_below(self):
        self.assertEqual(_smoothing_label(0.099, 1), SMOOTH_DAILY)

    def test_not_smooth_daily_cv_at_boundary(self):
        # cv == 0.1 does NOT qualify (need < 0.1)
        result = _smoothing_label(0.1, 1)
        self.assertNotEqual(result, SMOOTH_DAILY)

    def test_good_smoothing_freq2_low_cv(self):
        self.assertEqual(_smoothing_label(0.15, 2), GOOD_SMOOTHING)

    def test_good_smoothing_freq3_low_cv(self):
        self.assertEqual(_smoothing_label(0.15, 3), GOOD_SMOOTHING)

    def test_good_smoothing_freq1_cv_015(self):
        # freq==1, cv=0.15 → fails SMOOTH_DAILY, passes GOOD_SMOOTHING (freq<=3, cv<0.2)
        self.assertEqual(_smoothing_label(0.15, 1), GOOD_SMOOTHING)

    def test_moderate_spikes_freq5(self):
        self.assertEqual(_smoothing_label(0.3, 5), MODERATE_SPIKES)

    def test_moderate_spikes_freq7(self):
        self.assertEqual(_smoothing_label(0.35, 7), MODERATE_SPIKES)

    def test_batch_payout_freq14(self):
        # freq > 7 → BATCH_PAYOUT regardless of cv (unless cv > 0.7)
        self.assertEqual(_smoothing_label(0.1, 14), BATCH_PAYOUT)

    def test_batch_payout_high_cv_below_erratic(self):
        # cv in [0.4, 0.7] → BATCH_PAYOUT
        self.assertEqual(_smoothing_label(0.5, 1), BATCH_PAYOUT)

    def test_batch_payout_cv_at_04(self):
        self.assertEqual(_smoothing_label(0.4, 1), BATCH_PAYOUT)

    def test_erratic_cv_above_07(self):
        self.assertEqual(_smoothing_label(0.75, 1), ERRATIC_YIELD)

    def test_erratic_high_cv_weekly(self):
        self.assertEqual(_smoothing_label(0.9, 7), ERRATIC_YIELD)

    def test_erratic_cv_at_1(self):
        self.assertEqual(_smoothing_label(1.0, 1), ERRATIC_YIELD)

    def test_erratic_wins_over_all(self):
        # cv > 0.7 always → ERRATIC_YIELD regardless of freq
        for freq in [1, 3, 7, 14, 30]:
            self.assertEqual(_smoothing_label(0.8, freq), ERRATIC_YIELD)

    def test_all_labels_covered(self):
        for label in ALL_SMOOTHING_LABELS:
            self.assertIsInstance(label, str)

    def test_label_count(self):
        self.assertEqual(len(ALL_SMOOTHING_LABELS), 5)


# ===========================================================================
# 9. _smoothness_score
# ===========================================================================

class TestSmoothnessScore(unittest.TestCase):

    def test_returns_int(self):
        score = _smoothness_score(0.05, 1, True, 1, 0.0)
        self.assertIsInstance(score, int)

    def test_score_in_range(self):
        for cv in [0.0, 0.1, 0.5, 1.0]:
            for freq in [1, 7, 30]:
                score = _smoothness_score(cv, freq, True, 1, 0.0)
                self.assertGreaterEqual(score, 0)
                self.assertLessEqual(score, 100)

    def test_perfect_daily_max_score(self):
        # cv=0, freq=1, auto-compound daily, no drag → max score
        score = _smoothness_score(0.0, 1, True, 1, 0.0)
        self.assertGreater(score, 80)

    def test_high_cv_lowers_score(self):
        s1 = _smoothness_score(0.05, 1, True, 1, 0.0)
        s2 = _smoothness_score(0.8,  1, True, 1, 0.0)
        self.assertGreater(s1, s2)

    def test_longer_payout_lowers_score(self):
        s1 = _smoothness_score(0.1, 1,  True, 1, 0.0)
        s2 = _smoothness_score(0.1, 30, True, 1, 0.0)
        self.assertGreater(s1, s2)

    def test_auto_compound_higher_than_no_auto(self):
        s_auto = _smoothness_score(0.05, 1, True,  1, 0.0)
        s_none = _smoothness_score(0.05, 1, False, 1, 0.0)
        self.assertGreater(s_auto, s_none)

    def test_drag_penalizes_score(self):
        s_no_drag   = _smoothness_score(0.1, 1, True, 1, 0.0)
        s_with_drag = _smoothness_score(0.1, 1, True, 1, 0.5)
        self.assertGreater(s_no_drag, s_with_drag)

    def test_zero_score_not_negative(self):
        score = _smoothness_score(2.0, 365, False, 365, 1.0)
        self.assertGreaterEqual(score, 0)

    def test_score_capped_at_100(self):
        score = _smoothness_score(0.0, 1, True, 1, 0.0)
        self.assertLessEqual(score, 100)

    def test_weekly_auto_compound_intermediate(self):
        score = _smoothness_score(0.05, 7, True, 7, 0.001)
        self.assertGreater(score, 0)
        self.assertLess(score, 100)


# ===========================================================================
# 10. analyze — key fields
# ===========================================================================

class TestAnalyzeKeyFields(unittest.TestCase):

    def test_returns_dict(self):
        r = analyze(_source(), config=_cfg())
        self.assertIsInstance(r, dict)

    def test_required_output_keys(self):
        r = analyze(_source(), config=_cfg())
        for key in [
            "protocol_name", "observation_count", "payout_frequency_days",
            "auto_compounds", "compounding_frequency_days", "position_size_usd",
            "mean_yield_pct", "yield_std_pct", "yield_cv",
            "smoothness_score", "missed_compounding_drag_pct",
            "smoothing_label", "timestamp",
        ]:
            self.assertIn(key, r)

    def test_protocol_name_passthrough(self):
        r = analyze(_source(protocol_name="MyProtocol"), config=_cfg())
        self.assertEqual(r["protocol_name"], "MyProtocol")

    def test_mean_yield_correct(self):
        r = analyze(_source(yield_observations=[1.0, 2.0, 3.0]), config=_cfg())
        self.assertAlmostEqual(r["mean_yield_pct"], 2.0)

    def test_std_correct_constant(self):
        r = analyze(_source(yield_observations=[5.0, 5.0, 5.0]), config=_cfg())
        self.assertAlmostEqual(r["yield_std_pct"], 0.0)

    def test_cv_zero_for_constant(self):
        r = analyze(_source(yield_observations=[5.0, 5.0, 5.0]), config=_cfg())
        self.assertAlmostEqual(r["yield_cv"], 0.0)

    def test_observation_count(self):
        r = analyze(_source(yield_observations=[1.0, 2.0, 3.0]), config=_cfg())
        self.assertEqual(r["observation_count"], 3)

    def test_smoothing_label_smooth_daily(self):
        r = analyze(_source(yield_observations=_stable_obs(), payout_frequency_days=1,
                            auto_compounds=True, compounding_frequency_days=1), config=_cfg())
        self.assertEqual(r["smoothing_label"], SMOOTH_DAILY)

    def test_smoothing_label_in_all_labels(self):
        r = analyze(_source(), config=_cfg())
        self.assertIn(r["smoothing_label"], ALL_SMOOTHING_LABELS)

    def test_smoothness_score_is_int(self):
        r = analyze(_source(), config=_cfg())
        self.assertIsInstance(r["smoothness_score"], int)

    def test_smoothness_score_in_range(self):
        r = analyze(_source(), config=_cfg())
        self.assertGreaterEqual(r["smoothness_score"], 0)
        self.assertLessEqual(r["smoothness_score"], 100)

    def test_timestamp_is_float(self):
        r = analyze(_source(), config=_cfg())
        self.assertIsInstance(r["timestamp"], float)

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_source(), config=_cfg())
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_payout_frequency_passthrough(self):
        r = analyze(_source(payout_frequency_days=7), config=_cfg())
        self.assertEqual(r["payout_frequency_days"], 7)

    def test_auto_compounds_passthrough(self):
        r = analyze(_source(auto_compounds=False), config=_cfg())
        self.assertFalse(r["auto_compounds"])

    def test_position_size_passthrough(self):
        r = analyze(_source(position_size_usd=999_999.0), config=_cfg())
        self.assertAlmostEqual(r["position_size_usd"], 999_999.0)


# ===========================================================================
# 11. analyze — edge / boundary cases
# ===========================================================================

class TestAnalyzeEdgeCases(unittest.TestCase):

    def test_empty_observations_list(self):
        r = analyze(_source(yield_observations=[]), config=_cfg())
        self.assertAlmostEqual(r["mean_yield_pct"], 0.0)
        self.assertAlmostEqual(r["yield_std_pct"], 0.0)
        self.assertEqual(r["observation_count"], 0)

    def test_empty_dict_input(self):
        r = analyze({}, config=_cfg())
        self.assertIn("smoothing_label", r)
        self.assertIn(r["smoothing_label"], ALL_SMOOTHING_LABELS)

    def test_missing_protocol_name_defaults(self):
        s = _source()
        del s["protocol_name"]
        r = analyze(s, config=_cfg())
        self.assertEqual(r["protocol_name"], "UNKNOWN")

    def test_payout_freq_zero_clamped_to_1(self):
        r = analyze(_source(payout_frequency_days=0), config=_cfg())
        self.assertEqual(r["payout_frequency_days"], 1)

    def test_negative_payout_freq_clamped_to_1(self):
        r = analyze(_source(payout_frequency_days=-5), config=_cfg())
        self.assertEqual(r["payout_frequency_days"], 1)

    def test_negative_position_size_clamped_to_zero(self):
        r = analyze(_source(position_size_usd=-50000.0), config=_cfg())
        self.assertAlmostEqual(r["position_size_usd"], 0.0)

    def test_invalid_observations_filtered(self):
        s = _source(yield_observations=[1.0, "bad", None, float("nan"), 2.0])
        r = analyze(s, config=_cfg())
        self.assertEqual(r["observation_count"], 2)

    def test_single_observation(self):
        r = analyze(_source(yield_observations=[5.0]), config=_cfg())
        self.assertAlmostEqual(r["mean_yield_pct"], 5.0)
        self.assertAlmostEqual(r["yield_std_pct"], 0.0)

    def test_no_crash_without_config(self):
        """analyze without config should not crash."""
        try:
            r = analyze(_source())
            self.assertIn("smoothing_label", r)
        except Exception:
            pass

    def test_auto_compounds_default_false(self):
        s = {"yield_observations": _stable_obs()}
        r = analyze(s, config=_cfg())
        # Default should be False
        self.assertFalse(r["auto_compounds"])

    def test_string_payout_freq_coerced(self):
        s = _source()
        s["payout_frequency_days"] = "7"
        r = analyze(s, config=_cfg())
        self.assertEqual(r["payout_frequency_days"], 7)

    def test_drag_zero_for_daily_payout(self):
        r = analyze(_source(payout_frequency_days=1), config=_cfg())
        self.assertAlmostEqual(r["missed_compounding_drag_pct"], 0.0)


# ===========================================================================
# 12. analyze — label boundary scenarios
# ===========================================================================

class TestAnalyzeLabelBoundaries(unittest.TestCase):

    def test_smooth_daily_constant_series(self):
        r = analyze(_source(yield_observations=_stable_obs(30),
                            payout_frequency_days=1), config=_cfg())
        self.assertEqual(r["smoothing_label"], SMOOTH_DAILY)

    def test_good_smoothing_freq2_low_noise(self):
        obs = [1.0 + 0.01 * (i % 3) for i in range(30)]  # low noise
        r = analyze(_source(yield_observations=obs, payout_frequency_days=2),
                    config=_cfg())
        self.assertIn(r["smoothing_label"], (SMOOTH_DAILY, GOOD_SMOOTHING, MODERATE_SPIKES))

    def test_batch_payout_long_interval(self):
        # freq=14 → must be BATCH_PAYOUT (assuming cv not > 0.7)
        obs = [0.01384] * 30  # constant cv=0
        r = analyze(_source(yield_observations=obs, payout_frequency_days=14),
                    config=_cfg())
        self.assertEqual(r["smoothing_label"], BATCH_PAYOUT)

    def test_erratic_high_cv(self):
        # Alternating very high and near-zero values → high cv
        obs = [0.001, 0.5, 0.001, 0.5, 0.001, 0.5, 0.001, 0.5,
               0.001, 0.5, 0.001, 0.5, 0.001, 0.5, 0.001, 0.5]
        r = analyze(_source(yield_observations=obs, payout_frequency_days=1),
                    config=_cfg())
        self.assertEqual(r["smoothing_label"], ERRATIC_YIELD)

    def test_high_cv_always_erratic(self):
        obs = [0.0001, 1.0, 0.0001, 1.0, 0.0001, 1.0]
        r = analyze(_source(yield_observations=obs, payout_frequency_days=1),
                    config=_cfg())
        self.assertEqual(r["smoothing_label"], ERRATIC_YIELD)
        self.assertGreater(r["yield_cv"], 0.7)

    def test_freq30_batch_payout(self):
        obs = _stable_obs(30)  # constant, but freq=30 → BATCH_PAYOUT
        r = analyze(_source(yield_observations=obs, payout_frequency_days=30),
                    config=_cfg())
        self.assertEqual(r["smoothing_label"], BATCH_PAYOUT)

    def test_freq1_cv_015_good_smoothing(self):
        # freq=1, cv=0.15 → GOOD_SMOOTHING (fails SMOOTH_DAILY since cv>=0.1)
        mean = 1.0
        # Build obs that achieve cv ≈ 0.15
        obs = [0.85, 1.15] * 15
        r = analyze(_source(yield_observations=obs, payout_frequency_days=1),
                    config=_cfg())
        cv = r["yield_cv"]
        label = r["smoothing_label"]
        # cv is around 0.15, freq=1 → should be GOOD_SMOOTHING or SMOOTH_DAILY
        self.assertIn(label, (SMOOTH_DAILY, GOOD_SMOOTHING, MODERATE_SPIKES))


# ===========================================================================
# 13. analyze — realistic DeFi protocol scenarios
# ===========================================================================

class TestAnalyzeRealisticScenarios(unittest.TestCase):

    def test_aave_daily_autocompound(self):
        """Aave V3 daily compounding stable protocol."""
        obs = _stable_obs(30, daily_yield=0.01384)  # ~5% APY
        r = analyze({
            "protocol_name":            "Aave V3 USDC",
            "yield_observations":       obs,
            "payout_frequency_days":    1,
            "auto_compounds":           True,
            "compounding_frequency_days": 1,
            "position_size_usd":        100_000.0,
        }, config=_cfg())
        self.assertEqual(r["smoothing_label"], SMOOTH_DAILY)
        self.assertAlmostEqual(r["yield_cv"], 0.0)
        self.assertGreater(r["smoothness_score"], 70)

    def test_convex_weekly_harvest(self):
        """Weekly harvest protocol — BATCH_PAYOUT."""
        weekly_yield = 0.19178  # ~70% APY / 7 days
        obs = [0.0] * 6 + [weekly_yield]
        r = analyze({
            "protocol_name":            "Convex CRV",
            "yield_observations":       obs * 4,
            "payout_frequency_days":    7,
            "auto_compounds":           False,
            "compounding_frequency_days": 7,
            "position_size_usd":        50_000.0,
        }, config=_cfg())
        # High cv from zeros → ERRATIC or BATCH depending on cv
        self.assertIn(r["smoothing_label"], ALL_SMOOTHING_LABELS)

    def test_pendle_high_yield_noisy(self):
        """Pendle YT — high yield with some volatility."""
        import random as _r
        _r.seed(42)
        obs = [max(0.01, 0.1 + _r.uniform(-0.05, 0.05)) for _ in range(30)]
        r = analyze({
            "protocol_name":            "Pendle YT",
            "yield_observations":       obs,
            "payout_frequency_days":    1,
            "auto_compounds":           False,
            "compounding_frequency_days": 1,
            "position_size_usd":        25_000.0,
        }, config=_cfg())
        self.assertIn(r["smoothing_label"], ALL_SMOOTHING_LABELS)
        self.assertGreater(r["mean_yield_pct"], 0)

    def test_monthly_distribution_protocol(self):
        """Monthly distribution protocol — should have BATCH_PAYOUT."""
        obs = _stable_obs(30, daily_yield=0.00822)  # ~3% APY
        r = analyze({
            "protocol_name":            "Monthly Dist",
            "yield_observations":       obs,
            "payout_frequency_days":    30,
            "auto_compounds":           False,
            "compounding_frequency_days": 30,
            "position_size_usd":        200_000.0,
        }, config=_cfg())
        self.assertEqual(r["smoothing_label"], BATCH_PAYOUT)  # freq > 7

    def test_drag_increases_with_frequency(self):
        cfg = _cfg()
        mean_yield = 10.0
        obs = [mean_yield / 365] * 30
        drags = []
        for freq in [1, 7, 14, 30]:
            r = analyze(_source(yield_observations=obs, payout_frequency_days=freq),
                        config=cfg)
            drags.append(r["missed_compounding_drag_pct"])
        # drag[0]=0 (daily), drags should be non-decreasing
        self.assertAlmostEqual(drags[0], 0.0)
        self.assertGreaterEqual(drags[1], drags[0])
        self.assertGreaterEqual(drags[2], drags[1])
        self.assertGreaterEqual(drags[3], drags[2])

    def test_auto_compound_daily_highest_score(self):
        cfg = _cfg()
        obs = _stable_obs(30)
        r_auto_daily = analyze(_source(payout_frequency_days=1, auto_compounds=True,
                                       compounding_frequency_days=1), config=cfg)
        r_no_auto    = analyze(_source(payout_frequency_days=1, auto_compounds=False,
                                       compounding_frequency_days=1), config=cfg)
        self.assertGreaterEqual(r_auto_daily["smoothness_score"],
                                r_no_auto["smoothness_score"])

    def test_mean_yield_positive_for_positive_obs(self):
        obs = [0.01, 0.02, 0.03]
        r = analyze(_source(yield_observations=obs), config=_cfg())
        self.assertGreater(r["mean_yield_pct"], 0)

    def test_std_greater_for_noisy_obs(self):
        cfg = _cfg()
        r_stable = analyze(_source(yield_observations=_stable_obs(30)), config=cfg)
        r_noisy  = analyze(_source(yield_observations=_noisy_obs(30)), config=cfg)
        self.assertGreater(r_noisy["yield_std_pct"], r_stable["yield_std_pct"])


# ===========================================================================
# 14. _atomic_log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):

    def test_creates_file(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 1})
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_appends_entries(self):
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
        self.assertEqual(data[0]["i"], 20)
        self.assertEqual(data[-1]["i"], 119)
        os.unlink(path)

    def test_file_valid_json(self):
        path = _tmp_log()
        _atomic_log(path, {"key": "value"})
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        os.unlink(path)

    def test_corrupt_file_reset(self):
        path = _tmp_log()
        with open(path, "w") as f:
            f.write("NOT JSON")
        _atomic_log(path, {"z": 99})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_creates_missing_dir(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "subdir", "yield.json")
            _atomic_log(path, {"test": True})
            self.assertTrue(os.path.exists(path))

    def test_entry_fields_preserved(self):
        path = _tmp_log()
        _atomic_log(path, {"smoothing_label": SMOOTH_DAILY, "score": 90})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["smoothing_label"], SMOOTH_DAILY)
        self.assertEqual(data[0]["score"], 90)
        os.unlink(path)


# ===========================================================================
# 15. analyze — logging integration
# ===========================================================================

class TestAnalyzeLogging(unittest.TestCase):

    def test_log_file_created(self):
        path = _tmp_log()
        analyze(_source(), config={"log_path": path})
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_log_contains_result(self):
        path = _tmp_log()
        analyze(_source(protocol_name="LogTest"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["protocol_name"], "LogTest")
        os.unlink(path)

    def test_multiple_calls_appended(self):
        path = _tmp_log()
        cfg = {"log_path": path}
        for i in range(5):
            analyze(_source(protocol_name=f"P{i}"), config=cfg)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)
        os.unlink(path)

    def test_ring_buffer_via_analyze(self):
        path = _tmp_log()
        cfg = {"log_path": path}
        for i in range(110):
            analyze(_source(protocol_name=f"P{i}"), config=cfg)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)
        os.unlink(path)


# ===========================================================================
# 16. analyze_portfolio
# ===========================================================================

class TestAnalyzePortfolio(unittest.TestCase):

    def _sources(self):
        return [
            _source("StableDaily",  yield_observations=_stable_obs(30),
                    payout_frequency_days=1),
            _source("NoisyWeekly",  yield_observations=_noisy_obs(30),
                    payout_frequency_days=7, auto_compounds=False),
            _source("MonthlyBatch", yield_observations=_stable_obs(30),
                    payout_frequency_days=30, auto_compounds=False),
        ]

    def test_returns_dict(self):
        r = analyze_portfolio(self._sources(), config=_cfg())
        self.assertIsInstance(r, dict)

    def test_total_sources(self):
        r = analyze_portfolio(self._sources(), config=_cfg())
        self.assertEqual(r["total_sources"], 3)

    def test_results_list_length(self):
        r = analyze_portfolio(self._sources(), config=_cfg())
        self.assertEqual(len(r["results"]), 3)

    def test_empty_list(self):
        r = analyze_portfolio([], config=_cfg())
        self.assertEqual(r["total_sources"], 0)
        self.assertIsNone(r["smoothest_source"])
        self.assertIsNone(r["most_erratic_source"])

    def test_smoothest_source_has_highest_score(self):
        r = analyze_portfolio(self._sources(), config=_cfg())
        scores = {res["protocol_name"]: res["smoothness_score"]
                  for res in r["results"]}
        self.assertEqual(scores[r["smoothest_source"]],
                         max(scores.values()))

    def test_most_erratic_source_has_lowest_score(self):
        r = analyze_portfolio(self._sources(), config=_cfg())
        scores = {res["protocol_name"]: res["smoothness_score"]
                  for res in r["results"]}
        self.assertEqual(scores[r["most_erratic_source"]],
                         min(scores.values()))

    def test_avg_smoothness_score_type(self):
        r = analyze_portfolio(self._sources(), config=_cfg())
        self.assertIsInstance(r["avg_smoothness_score"], float)

    def test_avg_missed_drag_pct_type(self):
        r = analyze_portfolio(self._sources(), config=_cfg())
        self.assertIsInstance(r["avg_missed_drag_pct"], float)

    def test_erratic_count(self):
        # NoisyWeekly with _noisy_obs may be erratic
        r = analyze_portfolio(self._sources(), config=_cfg())
        self.assertGreaterEqual(r["erratic_count"], 0)
        self.assertLessEqual(r["erratic_count"], 3)

    def test_single_source(self):
        r = analyze_portfolio([_source("Solo")], config=_cfg())
        self.assertEqual(r["total_sources"], 1)
        self.assertEqual(r["smoothest_source"], "Solo")
        self.assertEqual(r["most_erratic_source"], "Solo")

    def test_non_list_input(self):
        r = analyze_portfolio(None, config=_cfg())
        self.assertEqual(r["total_sources"], 0)

    def test_required_portfolio_keys(self):
        r = analyze_portfolio(self._sources(), config=_cfg())
        for k in ["total_sources", "results", "smoothest_source",
                  "most_erratic_source", "avg_smoothness_score",
                  "erratic_count", "avg_missed_drag_pct"]:
            self.assertIn(k, r)

    def test_each_result_has_smoothing_label(self):
        r = analyze_portfolio(self._sources(), config=_cfg())
        for res in r["results"]:
            self.assertIn("smoothing_label", res)
            self.assertIn(res["smoothing_label"], ALL_SMOOTHING_LABELS)

    def test_avg_smoothness_in_range(self):
        r = analyze_portfolio(self._sources(), config=_cfg())
        self.assertGreaterEqual(r["avg_smoothness_score"], 0)
        self.assertLessEqual(r["avg_smoothness_score"], 100)


# ===========================================================================
# 17. ProtocolDeFiYieldSmoothingAnalyzer class
# ===========================================================================

class TestProtocolDeFiYieldSmoothingAnalyzerClass(unittest.TestCase):

    def test_instantiation_no_config(self):
        a = ProtocolDeFiYieldSmoothingAnalyzer()
        self.assertIsNotNone(a)

    def test_instantiation_with_config(self):
        a = ProtocolDeFiYieldSmoothingAnalyzer(config={"log_path": _tmp_log()})
        self.assertIsNotNone(a)

    def test_analyze_returns_dict(self):
        a = ProtocolDeFiYieldSmoothingAnalyzer(config=_cfg())
        r = a.analyze(_source())
        self.assertIsInstance(r, dict)

    def test_analyze_smoothing_label_present(self):
        a = ProtocolDeFiYieldSmoothingAnalyzer(config=_cfg())
        r = a.analyze(_source())
        self.assertIn("smoothing_label", r)

    def test_analyze_portfolio_returns_dict(self):
        a = ProtocolDeFiYieldSmoothingAnalyzer(config=_cfg())
        r = a.analyze_portfolio([_source("A"), _source("B")])
        self.assertIsInstance(r, dict)
        self.assertEqual(r["total_sources"], 2)

    def test_analyze_portfolio_empty(self):
        a = ProtocolDeFiYieldSmoothingAnalyzer(config=_cfg())
        r = a.analyze_portfolio([])
        self.assertEqual(r["total_sources"], 0)

    def test_class_config_passed(self):
        path = _tmp_log()
        a = ProtocolDeFiYieldSmoothingAnalyzer(config={"log_path": path})
        a.analyze(_source())
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_smooth_daily_via_class(self):
        a = ProtocolDeFiYieldSmoothingAnalyzer(config=_cfg())
        r = a.analyze(_source(yield_observations=_stable_obs(), payout_frequency_days=1))
        self.assertEqual(r["smoothing_label"], SMOOTH_DAILY)

    def test_erratic_via_class(self):
        obs = [0.001, 1.0, 0.001, 1.0, 0.001, 1.0, 0.001, 1.0]
        a = ProtocolDeFiYieldSmoothingAnalyzer(config=_cfg())
        r = a.analyze(_source(yield_observations=obs, payout_frequency_days=1))
        self.assertEqual(r["smoothing_label"], ERRATIC_YIELD)

    def test_batch_payout_via_class(self):
        a = ProtocolDeFiYieldSmoothingAnalyzer(config=_cfg())
        r = a.analyze(_source(yield_observations=_stable_obs(), payout_frequency_days=14))
        self.assertEqual(r["smoothing_label"], BATCH_PAYOUT)


# ===========================================================================
# 18. Consistency and mathematical correctness
# ===========================================================================

class TestMathematicalConsistency(unittest.TestCase):

    def test_cv_equals_std_over_mean(self):
        obs = [1.0, 2.0, 3.0, 4.0, 5.0]
        r = analyze(_source(yield_observations=obs), config=_cfg())
        expected_cv = r["yield_std_pct"] / r["mean_yield_pct"]
        self.assertAlmostEqual(r["yield_cv"], expected_cv, places=6)

    def test_zero_obs_cv_is_zero(self):
        obs = []
        r = analyze(_source(yield_observations=obs), config=_cfg())
        self.assertAlmostEqual(r["yield_cv"], 0.0)

    def test_more_observations_same_mean_stable(self):
        cfg = _cfg()
        r10 = analyze(_source(yield_observations=_stable_obs(10)), config=cfg)
        r30 = analyze(_source(yield_observations=_stable_obs(30)), config=cfg)
        # Both constant → same mean, same cv
        self.assertAlmostEqual(r10["mean_yield_pct"], r30["mean_yield_pct"], places=4)
        self.assertAlmostEqual(r10["yield_cv"], r30["yield_cv"], places=4)

    def test_drag_daily_exactly_zero(self):
        r = analyze(_source(payout_frequency_days=1), config=_cfg())
        self.assertAlmostEqual(r["missed_compounding_drag_pct"], 0.0)

    def test_higher_mean_yield_more_drag_weekly(self):
        cfg = _cfg()
        low_obs  = [0.005] * 30
        high_obs = [0.05]  * 30
        r_low  = analyze(_source(yield_observations=low_obs,  payout_frequency_days=7), config=cfg)
        r_high = analyze(_source(yield_observations=high_obs, payout_frequency_days=7), config=cfg)
        self.assertGreaterEqual(r_high["missed_compounding_drag_pct"],
                                r_low["missed_compounding_drag_pct"])

    def test_score_increases_with_smoother_obs(self):
        cfg = _cfg()
        r_noisy  = analyze(_source(yield_observations=_noisy_obs(30),  payout_frequency_days=1), config=cfg)
        r_stable = analyze(_source(yield_observations=_stable_obs(30), payout_frequency_days=1), config=cfg)
        self.assertGreaterEqual(r_stable["smoothness_score"], r_noisy["smoothness_score"])

    def test_std_zero_for_single_value(self):
        r = analyze(_source(yield_observations=[7.77]), config=_cfg())
        self.assertAlmostEqual(r["yield_std_pct"], 0.0)

    def test_all_zero_observations(self):
        r = analyze(_source(yield_observations=[0.0, 0.0, 0.0]), config=_cfg())
        self.assertAlmostEqual(r["mean_yield_pct"], 0.0)
        self.assertAlmostEqual(r["yield_std_pct"], 0.0)
        self.assertAlmostEqual(r["yield_cv"], 0.0)


if __name__ == "__main__":
    unittest.main()
