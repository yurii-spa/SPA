"""
Tests for MP-1106 DeFiProtocolRewardDilutionVelocityTracker
Comprehensive unittest suite — pure stdlib, no third-party dependencies.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_reward_dilution_velocity_tracker
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

from spa_core.analytics.defi_protocol_reward_dilution_velocity_tracker import (
    _safe_float,
    _pct_change,
    _atomic_log,
    _compute_tvl_growth_7d_pct,
    _compute_tvl_growth_30d_pct,
    _compute_emission_change_7d_pct,
    _compute_apy_decay_7d_pct,
    _compute_apy_decay_30d_pct,
    _compute_dilution_velocity_score,
    _compute_predicted_apy_30d_pct,
    _compute_dilution_label,
    analyze,
    DeFiProtocolRewardDilutionVelocityTracker,
    ALL_LABELS,
    LABEL_STABLE_APY,
    LABEL_MILD_DILUTION,
    LABEL_MODERATE_DILUTION,
    LABEL_RAPID_DILUTION,
    LABEL_APY_COLLAPSE,
    _LOG_CAP,
    _EPS,
)


# ---------------------------------------------------------------------------
# Helper: temporary log path
# ---------------------------------------------------------------------------
def _tmp_log():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _std_data(**overrides):
    base = {
        "protocol_name": "TestProtocol",
        "current_tvl_usd": 100_000_000.0,
        "tvl_7d_ago_usd": 80_000_000.0,
        "tvl_30d_ago_usd": 60_000_000.0,
        "current_reward_emission_usd_per_day": 50_000.0,
        "emission_7d_ago_usd_per_day": 55_000.0,
        "current_apy_pct": 6.0,
        "apy_7d_ago_pct": 7.0,
        "apy_30d_ago_pct": 10.0,
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. _safe_float
# ===========================================================================
class TestSafeFloat(unittest.TestCase):

    def test_int_converted(self):
        self.assertEqual(_safe_float(5), 5.0)

    def test_float_passthrough(self):
        self.assertEqual(_safe_float(3.14), 3.14)

    def test_string_numeric(self):
        self.assertEqual(_safe_float("2.5"), 2.5)

    def test_none_returns_default(self):
        self.assertEqual(_safe_float(None, 99.0), 99.0)

    def test_string_non_numeric_returns_default(self):
        self.assertEqual(_safe_float("abc", -1.0), -1.0)

    def test_default_is_zero(self):
        self.assertEqual(_safe_float("bad"), 0.0)

    def test_list_returns_default(self):
        self.assertEqual(_safe_float([1, 2], 7.0), 7.0)

    def test_zero_string(self):
        self.assertEqual(_safe_float("0"), 0.0)

    def test_negative_string(self):
        self.assertAlmostEqual(_safe_float("-3.5"), -3.5)

    def test_dict_returns_default(self):
        self.assertEqual(_safe_float({}, 42.0), 42.0)


# ===========================================================================
# 2. _pct_change
# ===========================================================================
class TestPctChange(unittest.TestCase):

    def test_increase(self):
        # 200 to 250 = +25%
        self.assertAlmostEqual(_pct_change(250.0, 200.0), 25.0)

    def test_decrease(self):
        # 200 to 150 = -25%
        self.assertAlmostEqual(_pct_change(150.0, 200.0), -25.0)

    def test_no_change(self):
        self.assertAlmostEqual(_pct_change(100.0, 100.0), 0.0)

    def test_zero_prior_returns_zero(self):
        self.assertEqual(_pct_change(100.0, 0.0), 0.0)

    def test_near_zero_prior_returns_zero(self):
        self.assertEqual(_pct_change(100.0, _EPS / 10), 0.0)

    def test_double(self):
        self.assertAlmostEqual(_pct_change(200.0, 100.0), 100.0)

    def test_halved(self):
        self.assertAlmostEqual(_pct_change(50.0, 100.0), -50.0)

    def test_negative_current(self):
        # -100 from 100 = -200%
        self.assertAlmostEqual(_pct_change(-100.0, 100.0), -200.0)

    def test_large_values(self):
        result = _pct_change(1_000_000.0, 500_000.0)
        self.assertAlmostEqual(result, 100.0)

    def test_small_fractional(self):
        result = _pct_change(1.001, 1.0)
        self.assertAlmostEqual(result, 0.1, places=5)


# ===========================================================================
# 3. _compute_tvl_growth_7d_pct
# ===========================================================================
class TestTvlGrowth7d(unittest.TestCase):

    def test_25pct_growth(self):
        self.assertAlmostEqual(_compute_tvl_growth_7d_pct(125.0, 100.0), 25.0)

    def test_zero_prior(self):
        self.assertEqual(_compute_tvl_growth_7d_pct(100.0, 0.0), 0.0)

    def test_no_change(self):
        self.assertAlmostEqual(_compute_tvl_growth_7d_pct(100.0, 100.0), 0.0)

    def test_decline(self):
        self.assertAlmostEqual(_compute_tvl_growth_7d_pct(80.0, 100.0), -20.0)

    def test_double(self):
        self.assertAlmostEqual(_compute_tvl_growth_7d_pct(200_000.0, 100_000.0), 100.0)

    def test_symmetry(self):
        # Consistent formula: (cur-prior)/|prior|*100
        r = _compute_tvl_growth_7d_pct(50_000_000.0, 40_000_000.0)
        self.assertAlmostEqual(r, 25.0)

    def test_zero_current(self):
        self.assertAlmostEqual(_compute_tvl_growth_7d_pct(0.0, 100.0), -100.0)

    def test_large_growth(self):
        r = _compute_tvl_growth_7d_pct(1_000.0, 10.0)
        self.assertAlmostEqual(r, 9900.0)


# ===========================================================================
# 4. _compute_tvl_growth_30d_pct
# ===========================================================================
class TestTvlGrowth30d(unittest.TestCase):

    def test_basic(self):
        self.assertAlmostEqual(_compute_tvl_growth_30d_pct(150.0, 100.0), 50.0)

    def test_zero_prior(self):
        self.assertEqual(_compute_tvl_growth_30d_pct(100.0, 0.0), 0.0)

    def test_no_change(self):
        self.assertAlmostEqual(_compute_tvl_growth_30d_pct(75.0, 75.0), 0.0)

    def test_decline_50pct(self):
        self.assertAlmostEqual(_compute_tvl_growth_30d_pct(50.0, 100.0), -50.0)

    def test_large_scale(self):
        r = _compute_tvl_growth_30d_pct(500_000_000.0, 300_000_000.0)
        self.assertAlmostEqual(r, 200.0 / 3.0, places=4)

    def test_returns_float(self):
        r = _compute_tvl_growth_30d_pct(200.0, 100.0)
        self.assertIsInstance(r, float)


# ===========================================================================
# 5. _compute_emission_change_7d_pct
# ===========================================================================
class TestEmissionChange7d(unittest.TestCase):

    def test_emission_increase(self):
        self.assertAlmostEqual(_compute_emission_change_7d_pct(110.0, 100.0), 10.0)

    def test_emission_decrease(self):
        self.assertAlmostEqual(_compute_emission_change_7d_pct(90.0, 100.0), -10.0)

    def test_zero_prior(self):
        self.assertEqual(_compute_emission_change_7d_pct(100.0, 0.0), 0.0)

    def test_no_change(self):
        self.assertAlmostEqual(_compute_emission_change_7d_pct(50_000.0, 50_000.0), 0.0)

    def test_halved(self):
        self.assertAlmostEqual(_compute_emission_change_7d_pct(25_000.0, 50_000.0), -50.0)

    def test_doubled(self):
        self.assertAlmostEqual(_compute_emission_change_7d_pct(100_000.0, 50_000.0), 100.0)

    def test_returns_float(self):
        r = _compute_emission_change_7d_pct(55_000.0, 50_000.0)
        self.assertIsInstance(r, float)

    def test_small_values(self):
        r = _compute_emission_change_7d_pct(1.1, 1.0)
        self.assertAlmostEqual(r, 10.0, places=5)


# ===========================================================================
# 6. _compute_apy_decay_7d_pct
# ===========================================================================
class TestApyDecay7d(unittest.TestCase):

    def test_apy_falling(self):
        # 7.0 → 6.0 = -14.28...%
        r = _compute_apy_decay_7d_pct(6.0, 7.0)
        self.assertAlmostEqual(r, -100.0 / 7.0, places=5)

    def test_apy_rising(self):
        r = _compute_apy_decay_7d_pct(8.0, 7.0)
        self.assertAlmostEqual(r, 100.0 / 7.0, places=5)

    def test_apy_stable(self):
        self.assertAlmostEqual(_compute_apy_decay_7d_pct(5.0, 5.0), 0.0)

    def test_zero_prior(self):
        self.assertEqual(_compute_apy_decay_7d_pct(5.0, 0.0), 0.0)

    def test_50pct_drop(self):
        self.assertAlmostEqual(_compute_apy_decay_7d_pct(5.0, 10.0), -50.0)

    def test_100pct_drop(self):
        self.assertAlmostEqual(_compute_apy_decay_7d_pct(0.0, 10.0), -100.0)

    def test_result_sign_negative_when_falling(self):
        r = _compute_apy_decay_7d_pct(3.0, 6.0)
        self.assertLess(r, 0.0)

    def test_result_sign_positive_when_rising(self):
        r = _compute_apy_decay_7d_pct(8.0, 4.0)
        self.assertGreater(r, 0.0)


# ===========================================================================
# 7. _compute_apy_decay_30d_pct
# ===========================================================================
class TestApyDecay30d(unittest.TestCase):

    def test_10pct_30d_drop(self):
        self.assertAlmostEqual(_compute_apy_decay_30d_pct(9.0, 10.0), -10.0)

    def test_50pct_30d_drop(self):
        self.assertAlmostEqual(_compute_apy_decay_30d_pct(5.0, 10.0), -50.0)

    def test_no_change(self):
        self.assertAlmostEqual(_compute_apy_decay_30d_pct(4.5, 4.5), 0.0)

    def test_zero_prior(self):
        self.assertEqual(_compute_apy_decay_30d_pct(4.5, 0.0), 0.0)

    def test_apy_growth_positive(self):
        r = _compute_apy_decay_30d_pct(15.0, 10.0)
        self.assertAlmostEqual(r, 50.0)

    def test_complete_collapse(self):
        self.assertAlmostEqual(_compute_apy_decay_30d_pct(0.0, 10.0), -100.0)

    def test_mild_decline(self):
        r = _compute_apy_decay_30d_pct(9.5, 10.0)
        self.assertAlmostEqual(r, -5.0)

    def test_returns_float(self):
        r = _compute_apy_decay_30d_pct(8.0, 10.0)
        self.assertIsInstance(r, float)


# ===========================================================================
# 8. _compute_dilution_velocity_score
# ===========================================================================
class TestDilutionVelocityScore(unittest.TestCase):

    def test_zero_tvl_growth_zero_score(self):
        self.assertAlmostEqual(_compute_dilution_velocity_score(0.0, -10.0), 0.0)

    def test_negative_tvl_growth_zero_score(self):
        self.assertAlmostEqual(_compute_dilution_velocity_score(-20.0, -10.0), 0.0)

    def test_ratio_basic(self):
        # 50% TVL growth, 10% APY drop → score = 50/10 = 5.0
        self.assertAlmostEqual(_compute_dilution_velocity_score(50.0, -10.0), 5.0)

    def test_capped_at_100(self):
        # 1000% TVL, 0.1% APY drop → 10000 capped to 100
        score = _compute_dilution_velocity_score(1000.0, -0.1)
        self.assertLessEqual(score, 100.0)

    def test_flat_apy_score_equals_tvl_growth(self):
        # When APY is flat and TVL grows 30%, score = 30
        score = _compute_dilution_velocity_score(30.0, 0.0)
        self.assertAlmostEqual(score, 30.0)

    def test_flat_apy_capped_at_100(self):
        score = _compute_dilution_velocity_score(200.0, 0.0)
        self.assertAlmostEqual(score, 100.0)

    def test_zero_both_zero_score(self):
        self.assertAlmostEqual(_compute_dilution_velocity_score(0.0, 0.0), 0.0)

    def test_apy_rising_but_tvl_up(self):
        # APY rising → decay is positive → magnitude used
        # TVL grew 20%, APY "decay" = +5% (rising) → 20/5 = 4.0
        score = _compute_dilution_velocity_score(20.0, 5.0)
        self.assertAlmostEqual(score, 4.0)

    def test_always_non_negative(self):
        for tvl, apy in [(-50.0, -10.0), (-50.0, 10.0), (0.0, 0.0)]:
            self.assertGreaterEqual(_compute_dilution_velocity_score(tvl, apy), 0.0)

    def test_score_lte_100(self):
        score = _compute_dilution_velocity_score(500.0, -50.0)
        self.assertLessEqual(score, 100.0)

    def test_equal_tvl_apy_change_gives_one(self):
        # 20% TVL growth, 20% APY drop → score = 1.0
        self.assertAlmostEqual(_compute_dilution_velocity_score(20.0, -20.0), 1.0)

    def test_returns_float(self):
        score = _compute_dilution_velocity_score(25.0, -10.0)
        self.assertIsInstance(score, float)


# ===========================================================================
# 9. _compute_predicted_apy_30d_pct
# ===========================================================================
class TestPredictedApy(unittest.TestCase):

    def test_flat_trend_gives_same(self):
        # No change in 30d: predicted = current
        self.assertAlmostEqual(_compute_predicted_apy_30d_pct(5.0, 5.0), 5.0)

    def test_falling_extrapolation(self):
        # 10 → 5 in 30d (−50%); next 30d → 0.0
        self.assertAlmostEqual(_compute_predicted_apy_30d_pct(5.0, 10.0), 0.0)

    def test_rising_extrapolation(self):
        # 5 → 8 in 30d; next 30d → 11
        self.assertAlmostEqual(_compute_predicted_apy_30d_pct(8.0, 5.0), 11.0)

    def test_floor_at_zero(self):
        # 10 → 2 in 30d; next 30d would be −6 → floored at 0
        result = _compute_predicted_apy_30d_pct(2.0, 10.0)
        self.assertAlmostEqual(result, 0.0)

    def test_negative_apy_30d_ago_edge(self):
        # If apy_30d_ago is 0 and current is 5: predicted = 10
        self.assertAlmostEqual(_compute_predicted_apy_30d_pct(5.0, 0.0), 10.0)

    def test_returns_float(self):
        r = _compute_predicted_apy_30d_pct(4.0, 6.0)
        self.assertIsInstance(r, float)

    def test_always_non_negative(self):
        r = _compute_predicted_apy_30d_pct(1.0, 100.0)
        self.assertGreaterEqual(r, 0.0)

    def test_doubled_trend(self):
        # 3 → 6 in 30d; predicted = 9
        self.assertAlmostEqual(_compute_predicted_apy_30d_pct(6.0, 3.0), 9.0)

    def test_full_collapse(self):
        # 8 → 0 in 30d; predicted clamped to 0
        self.assertAlmostEqual(_compute_predicted_apy_30d_pct(0.0, 8.0), 0.0)

    def test_linear_formula(self):
        # Formula: 2*current - apy_30d_ago
        cur, ago = 7.0, 4.0
        expected = 2.0 * cur - ago
        self.assertAlmostEqual(_compute_predicted_apy_30d_pct(cur, ago), expected)


# ===========================================================================
# 10. _compute_dilution_label
# ===========================================================================
class TestDilutionLabel(unittest.TestCase):

    def test_zero_decay_is_stable(self):
        self.assertEqual(_compute_dilution_label(0.0), LABEL_STABLE_APY)

    def test_positive_decay_is_stable(self):
        # APY is rising (+20%) → stable
        self.assertEqual(_compute_dilution_label(20.0), LABEL_STABLE_APY)

    def test_minus_5_is_stable(self):
        self.assertEqual(_compute_dilution_label(-5.0), LABEL_STABLE_APY)

    def test_minus_9_99_is_stable(self):
        self.assertEqual(_compute_dilution_label(-9.99), LABEL_STABLE_APY)

    def test_exactly_minus_10_is_mild(self):
        self.assertEqual(_compute_dilution_label(-10.0), LABEL_MILD_DILUTION)

    def test_minus_15_is_mild(self):
        self.assertEqual(_compute_dilution_label(-15.0), LABEL_MILD_DILUTION)

    def test_minus_24_99_is_mild(self):
        self.assertEqual(_compute_dilution_label(-24.99), LABEL_MILD_DILUTION)

    def test_exactly_minus_25_is_moderate(self):
        self.assertEqual(_compute_dilution_label(-25.0), LABEL_MODERATE_DILUTION)

    def test_minus_40_is_moderate(self):
        self.assertEqual(_compute_dilution_label(-40.0), LABEL_MODERATE_DILUTION)

    def test_minus_49_99_is_moderate(self):
        self.assertEqual(_compute_dilution_label(-49.99), LABEL_MODERATE_DILUTION)

    def test_exactly_minus_50_is_rapid(self):
        self.assertEqual(_compute_dilution_label(-50.0), LABEL_RAPID_DILUTION)

    def test_minus_60_is_rapid(self):
        self.assertEqual(_compute_dilution_label(-60.0), LABEL_RAPID_DILUTION)

    def test_minus_74_99_is_rapid(self):
        self.assertEqual(_compute_dilution_label(-74.99), LABEL_RAPID_DILUTION)

    def test_exactly_minus_75_is_collapse(self):
        self.assertEqual(_compute_dilution_label(-75.0), LABEL_APY_COLLAPSE)

    def test_minus_90_is_collapse(self):
        self.assertEqual(_compute_dilution_label(-90.0), LABEL_APY_COLLAPSE)

    def test_minus_100_is_collapse(self):
        self.assertEqual(_compute_dilution_label(-100.0), LABEL_APY_COLLAPSE)

    def test_label_is_string(self):
        self.assertIsInstance(_compute_dilution_label(-30.0), str)

    def test_all_labels_covered(self):
        # Confirm all five labels can be returned
        produced = set()
        for decay in [0.0, -15.0, -30.0, -60.0, -80.0]:
            produced.add(_compute_dilution_label(decay))
        self.assertEqual(produced, set(ALL_LABELS))


# ===========================================================================
# 11. _atomic_log  (ring-buffer behaviour)
# ===========================================================================
class TestAtomicLog(unittest.TestCase):

    def setUp(self):
        self.log_path = _tmp_log()

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)

    def test_creates_file(self):
        _atomic_log(self.log_path, {"x": 1})
        self.assertTrue(os.path.exists(self.log_path))

    def test_single_entry(self):
        _atomic_log(self.log_path, {"a": 42})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["a"], 42)

    def test_multiple_entries_accumulated(self):
        for i in range(5):
            _atomic_log(self.log_path, {"i": i})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        for i in range(_LOG_CAP + 10):
            _atomic_log(self.log_path, {"i": i})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_CAP)

    def test_ring_buffer_keeps_newest(self):
        for i in range(_LOG_CAP + 5):
            _atomic_log(self.log_path, {"i": i})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], _LOG_CAP + 4)
        self.assertEqual(data[0]["i"], 5)

    def test_corrupted_file_recovered(self):
        with open(self.log_path, "w") as f:
            f.write("NOT JSON!!!")
        _atomic_log(self.log_path, {"recovered": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_valid_json_after_write(self):
        _atomic_log(self.log_path, {"test": "value"})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_non_list_json_recovered(self):
        with open(self.log_path, "w") as f:
            json.dump({"not": "a list"}, f)
        _atomic_log(self.log_path, {"ok": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_entry_is_last_item(self):
        _atomic_log(self.log_path, {"first": 1})
        _atomic_log(self.log_path, {"second": 2})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["second"], 2)

    def test_timestamp_string_not_json_error(self):
        # Entry with float('inf') must not crash (default=str used in log)
        entry = {"ts": float("inf")}
        try:
            _atomic_log(self.log_path, entry)
        except Exception:
            pass  # log errors are acceptable


# ===========================================================================
# 12. analyze — core function
# ===========================================================================
class TestAnalyzeFunction(unittest.TestCase):

    def _cfg(self):
        return {"log_path": _tmp_log()}

    def test_returns_dict(self):
        r = analyze(_std_data(), config=self._cfg())
        self.assertIsInstance(r, dict)

    def test_all_required_keys_present(self):
        r = analyze(_std_data(), config=self._cfg())
        for key in [
            "protocol_name", "tvl_growth_7d_pct", "tvl_growth_30d_pct",
            "emission_change_7d_pct", "apy_decay_7d_pct", "apy_decay_30d_pct",
            "dilution_velocity_score", "predicted_apy_30d_pct", "dilution_label",
            "timestamp",
        ]:
            self.assertIn(key, r, f"Missing key: {key}")

    def test_protocol_name_from_dict(self):
        r = analyze(_std_data(protocol_name="Aave"), config=self._cfg())
        self.assertEqual(r["protocol_name"], "Aave")

    def test_protocol_name_keyword_overrides_dict(self):
        r = analyze(_std_data(), protocol_name="Override", config=self._cfg())
        self.assertEqual(r["protocol_name"], "Override")

    def test_tvl_growth_7d_positive(self):
        # 100M now, 80M 7d ago → +25%
        r = analyze(_std_data(), config=self._cfg())
        self.assertAlmostEqual(r["tvl_growth_7d_pct"], 25.0)

    def test_tvl_growth_30d_positive(self):
        # 100M now, 60M 30d ago → +66.67%
        r = analyze(_std_data(), config=self._cfg())
        self.assertAlmostEqual(r["tvl_growth_30d_pct"], 200.0 / 3.0, places=3)

    def test_apy_decay_7d_negative(self):
        # 7 → 6: -(1/7)*100 ≈ -14.28%
        r = analyze(_std_data(), config=self._cfg())
        self.assertLess(r["apy_decay_7d_pct"], 0.0)

    def test_apy_decay_30d_negative(self):
        # 10 → 6: -40%
        r = analyze(_std_data(), config=self._cfg())
        self.assertAlmostEqual(r["apy_decay_30d_pct"], -40.0)

    def test_dilution_label_moderate(self):
        # apy_decay_30d = -40% → MODERATE_DILUTION
        r = analyze(_std_data(), config=self._cfg())
        self.assertEqual(r["dilution_label"], LABEL_MODERATE_DILUTION)

    def test_dilution_label_stable(self):
        r = analyze(
            _std_data(current_apy_pct=9.5, apy_30d_ago_pct=10.0),
            config=self._cfg(),
        )
        self.assertEqual(r["dilution_label"], LABEL_STABLE_APY)

    def test_dilution_label_collapse(self):
        r = analyze(
            _std_data(current_apy_pct=2.0, apy_30d_ago_pct=10.0),
            config=self._cfg(),
        )
        self.assertEqual(r["dilution_label"], LABEL_APY_COLLAPSE)

    def test_keyword_inputs_override_dict(self):
        r = analyze(
            _std_data(current_tvl_usd=100.0),
            current_tvl_usd=200_000_000.0,
            config=self._cfg(),
        )
        self.assertAlmostEqual(r["current_tvl_usd"], 200_000_000.0)

    def test_empty_data_does_not_raise(self):
        r = analyze({}, config=self._cfg())
        self.assertIn("dilution_label", r)

    def test_none_data_does_not_raise(self):
        r = analyze(None, config=self._cfg())
        self.assertIn("dilution_label", r)

    def test_timestamp_is_recent(self):
        before = time.time()
        r = analyze(_std_data(), config=self._cfg())
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_predicted_apy_non_negative(self):
        # Extreme collapse scenario: predicted should be clamped at 0
        r = analyze(
            _std_data(current_apy_pct=1.0, apy_30d_ago_pct=100.0),
            config=self._cfg(),
        )
        self.assertGreaterEqual(r["predicted_apy_30d_pct"], 0.0)

    def test_score_capped_at_100(self):
        r = analyze(
            _std_data(
                current_tvl_usd=10_000_000_000.0,
                tvl_7d_ago_usd=1.0,
                current_apy_pct=9.99,
                apy_7d_ago_pct=10.0,
            ),
            config=self._cfg(),
        )
        self.assertLessEqual(r["dilution_velocity_score"], 100.0)

    def test_negative_tvl_inputs_clamped_to_zero(self):
        r = analyze(
            _std_data(current_tvl_usd=-1_000.0, tvl_7d_ago_usd=-500.0),
            config=self._cfg(),
        )
        self.assertEqual(r["current_tvl_usd"], 0.0)

    def test_emission_change_detected(self):
        r = analyze(_std_data(), config=self._cfg())
        # 50k now, 55k 7d ago → -9.09%
        self.assertAlmostEqual(r["emission_change_7d_pct"], -100.0 / 11.0, places=3)

    def test_dilution_label_rapid(self):
        r = analyze(
            _std_data(current_apy_pct=4.0, apy_30d_ago_pct=10.0),
            config=self._cfg(),
        )
        self.assertEqual(r["dilution_label"], LABEL_RAPID_DILUTION)


# ===========================================================================
# 13. DeFiProtocolRewardDilutionVelocityTracker class
# ===========================================================================
class TestClassWrapper(unittest.TestCase):

    def _tracker(self):
        return DeFiProtocolRewardDilutionVelocityTracker(
            config={"log_path": _tmp_log()}
        )

    def test_instantiation(self):
        t = self._tracker()
        self.assertIsNotNone(t)

    def test_analyze_returns_dict(self):
        t = self._tracker()
        r = t.analyze(_std_data())
        self.assertIsInstance(r, dict)

    def test_analyze_uses_config(self):
        log_path = _tmp_log()
        t = DeFiProtocolRewardDilutionVelocityTracker(config={"log_path": log_path})
        t.analyze(_std_data())
        self.assertTrue(os.path.exists(log_path))
        os.unlink(log_path)

    def test_analyze_accepts_kwargs(self):
        t = self._tracker()
        r = t.analyze(protocol_name="KwargProto")
        self.assertEqual(r["protocol_name"], "KwargProto")

    def test_default_config_no_crash(self):
        t = DeFiProtocolRewardDilutionVelocityTracker()
        r = t.analyze(_std_data())
        self.assertIn("dilution_label", r)

    def test_multiple_calls_consistent(self):
        t = self._tracker()
        r1 = t.analyze(_std_data())
        r2 = t.analyze(_std_data())
        self.assertEqual(r1["dilution_label"], r2["dilution_label"])
        self.assertAlmostEqual(r1["tvl_growth_7d_pct"], r2["tvl_growth_7d_pct"])


# ===========================================================================
# 14. Constants and module-level sanity
# ===========================================================================
class TestConstants(unittest.TestCase):

    def test_all_labels_tuple_has_five(self):
        self.assertEqual(len(ALL_LABELS), 5)

    def test_all_labels_contains_stable(self):
        self.assertIn(LABEL_STABLE_APY, ALL_LABELS)

    def test_all_labels_contains_collapse(self):
        self.assertIn(LABEL_APY_COLLAPSE, ALL_LABELS)

    def test_log_cap_is_100(self):
        self.assertEqual(_LOG_CAP, 100)

    def test_eps_is_positive(self):
        self.assertGreater(_EPS, 0.0)

    def test_eps_is_small(self):
        self.assertLess(_EPS, 1e-6)

    def test_label_mild_in_all_labels(self):
        self.assertIn(LABEL_MILD_DILUTION, ALL_LABELS)

    def test_label_moderate_in_all_labels(self):
        self.assertIn(LABEL_MODERATE_DILUTION, ALL_LABELS)

    def test_label_rapid_in_all_labels(self):
        self.assertIn(LABEL_RAPID_DILUTION, ALL_LABELS)

    def test_all_labels_are_strings(self):
        for lbl in ALL_LABELS:
            self.assertIsInstance(lbl, str)


# ===========================================================================
# 15. Edge-case integration scenarios
# ===========================================================================
class TestEdgeCaseScenarios(unittest.TestCase):

    def _cfg(self):
        return {"log_path": _tmp_log()}

    def test_all_zeros(self):
        r = analyze({}, config=self._cfg())
        self.assertEqual(r["tvl_growth_7d_pct"], 0.0)
        self.assertEqual(r["dilution_label"], LABEL_STABLE_APY)

    def test_apy_collapsed_to_zero(self):
        r = analyze(
            _std_data(current_apy_pct=0.0, apy_7d_ago_pct=0.0, apy_30d_ago_pct=0.0),
            config=self._cfg(),
        )
        self.assertEqual(r["apy_decay_7d_pct"], 0.0)
        self.assertEqual(r["dilution_label"], LABEL_STABLE_APY)

    def test_tvl_shrinking_score_zero(self):
        r = analyze(
            _std_data(current_tvl_usd=50_000_000.0, tvl_7d_ago_usd=100_000_000.0),
            config=self._cfg(),
        )
        self.assertAlmostEqual(r["dilution_velocity_score"], 0.0)

    def test_string_numeric_inputs(self):
        d = {k: str(v) if isinstance(v, (int, float)) else v for k, v in _std_data().items()}
        r = analyze(d, config=self._cfg())
        self.assertIsInstance(r["tvl_growth_7d_pct"], float)

    def test_very_large_tvl_numbers(self):
        r = analyze(
            _std_data(
                current_tvl_usd=1e12,
                tvl_7d_ago_usd=9e11,
                tvl_30d_ago_usd=8e11,
            ),
            config=self._cfg(),
        )
        self.assertAlmostEqual(r["tvl_growth_7d_pct"], 100.0 / 9.0, places=3)

    def test_mild_dilution_boundary(self):
        # Exactly at -10% boundary → MILD
        r = analyze(
            _std_data(current_apy_pct=9.0, apy_30d_ago_pct=10.0),
            config=self._cfg(),
        )
        self.assertEqual(r["dilution_label"], LABEL_MILD_DILUTION)

    def test_predicted_rises_when_apy_rising(self):
        r = analyze(
            _std_data(current_apy_pct=12.0, apy_30d_ago_pct=8.0),
            config=self._cfg(),
        )
        self.assertGreater(r["predicted_apy_30d_pct"], 12.0)

    def test_score_is_float(self):
        r = analyze(_std_data(), config=self._cfg())
        self.assertIsInstance(r["dilution_velocity_score"], float)

    def test_non_dict_invalid_data_type(self):
        r = analyze("NOT A DICT", config=self._cfg())
        self.assertIn("dilution_label", r)


if __name__ == "__main__":
    unittest.main()
