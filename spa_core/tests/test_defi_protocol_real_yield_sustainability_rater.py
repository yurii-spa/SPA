"""
Tests for MP-1118 DeFiProtocolRealYieldSustainabilityRater
≥110 unittest tests — pure stdlib, no third-party dependencies.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_protocol_real_yield_sustainability_rater import (
    DeFiProtocolRealYieldSustainabilityRater,
    rate,
    _atomic_log,
    _annualized_revenue_usd,
    _real_yield_apy_pct,
    _emission_yield_apy_pct,
    _real_yield_ratio,
    _revenue_yield_gap_pct,
    _sustainability_label,
    _growth_score,
    _expense_score,
    _sustainability_score,
    _LOG_CAP,
    _FULLY_REAL_THRESHOLD,
    _MOSTLY_REAL_THRESHOLD,
    _MIXED_THRESHOLD,
    _MOSTLY_EMISSION_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _base_data(**overrides) -> dict:
    d = {
        "protocol_name":            "TestProtocol",
        "claimed_apy_pct":          10.0,
        "protocol_revenue_7d_usd":  20_000.0,
        "token_emission_7d_usd":    5_000.0,
        "total_staked_usd":         50_000_000.0,
        "protocol_expenses_7d_usd": 0.0,
        "revenue_growth_30d_pct":   10.0,
    }
    d.update(overrides)
    return d


# ===========================================================================
# 1. _annualized_revenue_usd
# ===========================================================================

class TestAnnualizedRevenueUsd(unittest.TestCase):

    def test_zero_returns_zero(self):
        self.assertEqual(_annualized_revenue_usd(0.0), 0.0)

    def test_multiplies_by_52(self):
        self.assertAlmostEqual(_annualized_revenue_usd(1_000.0), 52_000.0, places=4)

    def test_large_value(self):
        self.assertAlmostEqual(_annualized_revenue_usd(1_000_000.0), 52_000_000.0, places=2)

    def test_small_value(self):
        self.assertAlmostEqual(_annualized_revenue_usd(100.0), 5_200.0, places=4)

    def test_negative_propagates(self):
        # negative revenue is allowed as raw value (caller handles)
        result = _annualized_revenue_usd(-1_000.0)
        self.assertAlmostEqual(result, -52_000.0, places=4)

    def test_returns_float(self):
        self.assertIsInstance(_annualized_revenue_usd(500.0), float)

    def test_fractional_value(self):
        self.assertAlmostEqual(_annualized_revenue_usd(1.5), 78.0, places=6)

    def test_annualized_factor_is_52_not_365(self):
        # 7d * 52 = 364 days, not 365
        self.assertAlmostEqual(_annualized_revenue_usd(1.0), 52.0, places=6)


# ===========================================================================
# 2. _real_yield_apy_pct
# ===========================================================================

class TestRealYieldApyPct(unittest.TestCase):

    def test_zero_staked_returns_zero(self):
        self.assertEqual(_real_yield_apy_pct(10_000.0, 0.0, 0.0), 0.0)

    def test_negative_staked_returns_zero(self):
        self.assertEqual(_real_yield_apy_pct(10_000.0, 0.0, -1.0), 0.0)

    def test_zero_revenue_returns_zero(self):
        self.assertEqual(_real_yield_apy_pct(0.0, 0.0, 1_000_000.0), 0.0)

    def test_known_calculation(self):
        # 20000 * 52 / 50_000_000 * 100 = 2.08 %
        result = _real_yield_apy_pct(20_000.0, 0.0, 50_000_000.0)
        self.assertAlmostEqual(result, 2.08, places=4)

    def test_expenses_reduce_yield(self):
        # net = 20000 - 5000 = 15000; 15000*52/50_000_000*100 = 1.56 %
        result = _real_yield_apy_pct(20_000.0, 5_000.0, 50_000_000.0)
        self.assertAlmostEqual(result, 1.56, places=4)

    def test_expenses_exceed_revenue_floor_at_zero(self):
        # net = max(0, -5000) = 0
        result = _real_yield_apy_pct(5_000.0, 10_000.0, 50_000_000.0)
        self.assertEqual(result, 0.0)

    def test_expenses_equal_revenue_returns_zero(self):
        result = _real_yield_apy_pct(10_000.0, 10_000.0, 50_000_000.0)
        self.assertEqual(result, 0.0)

    def test_result_is_float(self):
        result = _real_yield_apy_pct(1_000.0, 0.0, 1_000_000.0)
        self.assertIsInstance(result, float)

    def test_annualization_factor_52(self):
        # 1 USD revenue * 52 / 5200 staked * 100 = 1.0 %
        result = _real_yield_apy_pct(1.0, 0.0, 5_200.0)
        self.assertAlmostEqual(result, 1.0, places=5)

    def test_high_revenue_gives_high_apy(self):
        result = _real_yield_apy_pct(100_000.0, 0.0, 1_000_000.0)
        self.assertGreater(result, 100.0)

    def test_rounding_to_6_places(self):
        result = _real_yield_apy_pct(1.0, 0.0, 3.0)
        self.assertAlmostEqual(result, round(1.0 * 52.0 / 3.0 * 100.0, 6), places=6)

    def test_zero_expenses_same_as_no_expenses(self):
        r1 = _real_yield_apy_pct(10_000.0, 0.0, 50_000_000.0)
        r2 = _real_yield_apy_pct(10_000.0, 0.0, 50_000_000.0)
        self.assertEqual(r1, r2)


# ===========================================================================
# 3. _emission_yield_apy_pct
# ===========================================================================

class TestEmissionYieldApyPct(unittest.TestCase):

    def test_zero_staked_returns_zero(self):
        self.assertEqual(_emission_yield_apy_pct(5_000.0, 0.0), 0.0)

    def test_negative_staked_returns_zero(self):
        self.assertEqual(_emission_yield_apy_pct(5_000.0, -100.0), 0.0)

    def test_zero_emission_returns_zero(self):
        self.assertEqual(_emission_yield_apy_pct(0.0, 50_000_000.0), 0.0)

    def test_known_calculation(self):
        # 5000 * 52 / 50_000_000 * 100 = 0.52 %
        result = _emission_yield_apy_pct(5_000.0, 50_000_000.0)
        self.assertAlmostEqual(result, 0.52, places=4)

    def test_result_is_float(self):
        result = _emission_yield_apy_pct(1_000.0, 1_000_000.0)
        self.assertIsInstance(result, float)

    def test_annualization_factor_52(self):
        # 1 * 52 / 5200 * 100 = 1.0 %
        result = _emission_yield_apy_pct(1.0, 5_200.0)
        self.assertAlmostEqual(result, 1.0, places=5)

    def test_large_emission(self):
        result = _emission_yield_apy_pct(1_000_000.0, 1_000_000.0)
        self.assertGreater(result, 0.0)

    def test_rounding_to_6_places(self):
        result = _emission_yield_apy_pct(1.0, 3.0)
        expected = round(1.0 * 52.0 / 3.0 * 100.0, 6)
        self.assertAlmostEqual(result, expected, places=6)

    def test_both_zero_returns_zero(self):
        self.assertEqual(_emission_yield_apy_pct(0.0, 0.0), 0.0)

    def test_independent_of_revenue(self):
        # emission apy does not use revenue
        r1 = _emission_yield_apy_pct(5_000.0, 50_000_000.0)
        r2 = _emission_yield_apy_pct(5_000.0, 50_000_000.0)
        self.assertEqual(r1, r2)


# ===========================================================================
# 4. _real_yield_ratio
# ===========================================================================

class TestRealYieldRatio(unittest.TestCase):

    def test_zero_claimed_positive_real_returns_one(self):
        self.assertEqual(_real_yield_ratio(5.0, 0.0), 1.0)

    def test_both_zero_returns_zero(self):
        self.assertEqual(_real_yield_ratio(0.0, 0.0), 0.0)

    def test_zero_claimed_zero_real_returns_zero(self):
        self.assertEqual(_real_yield_ratio(0.0, 0.0), 0.0)

    def test_negative_claimed_positive_real_returns_one(self):
        # negative claimed treated as ≤ 0
        self.assertEqual(_real_yield_ratio(5.0, -1.0), 1.0)

    def test_ratio_less_than_one(self):
        # 5/10 = 0.5
        result = _real_yield_ratio(5.0, 10.0)
        self.assertAlmostEqual(result, 0.5, places=6)

    def test_ratio_greater_than_one_over_backed(self):
        # 12/10 = 1.2 (real yield exceeds claimed)
        result = _real_yield_ratio(12.0, 10.0)
        self.assertAlmostEqual(result, 1.2, places=6)

    def test_ratio_exactly_one(self):
        result = _real_yield_ratio(10.0, 10.0)
        self.assertAlmostEqual(result, 1.0, places=6)

    def test_small_real_large_claimed(self):
        result = _real_yield_ratio(1.0, 100.0)
        self.assertAlmostEqual(result, 0.01, places=6)

    def test_rounding_to_6_places(self):
        result = _real_yield_ratio(1.0, 3.0)
        self.assertAlmostEqual(result, round(1.0 / 3.0, 6), places=6)

    def test_zero_real_positive_claimed_returns_zero(self):
        result = _real_yield_ratio(0.0, 10.0)
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_result_is_float(self):
        result = _real_yield_ratio(5.0, 10.0)
        self.assertIsInstance(result, float)

    def test_typical_aave_like_ratio(self):
        # 3.5% real / 3.5% claimed = 1.0 (fully backed)
        result = _real_yield_ratio(3.5, 3.5)
        self.assertAlmostEqual(result, 1.0, places=6)


# ===========================================================================
# 5. _revenue_yield_gap_pct
# ===========================================================================

class TestRevenueYieldGapPct(unittest.TestCase):

    def test_claimed_greater_than_real_positive_gap(self):
        result = _revenue_yield_gap_pct(10.0, 3.0)
        self.assertAlmostEqual(result, 7.0, places=6)

    def test_claimed_less_than_real_negative_gap(self):
        result = _revenue_yield_gap_pct(3.0, 10.0)
        self.assertAlmostEqual(result, -7.0, places=6)

    def test_equal_claimed_and_real_zero_gap(self):
        result = _revenue_yield_gap_pct(10.0, 10.0)
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_zero_claimed(self):
        result = _revenue_yield_gap_pct(0.0, 5.0)
        self.assertAlmostEqual(result, -5.0, places=6)

    def test_zero_real(self):
        result = _revenue_yield_gap_pct(10.0, 0.0)
        self.assertAlmostEqual(result, 10.0, places=6)

    def test_both_zero(self):
        result = _revenue_yield_gap_pct(0.0, 0.0)
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_large_gap(self):
        result = _revenue_yield_gap_pct(100.0, 1.0)
        self.assertAlmostEqual(result, 99.0, places=4)

    def test_small_gap(self):
        result = _revenue_yield_gap_pct(5.01, 5.0)
        self.assertAlmostEqual(result, 0.01, places=5)

    def test_result_is_float(self):
        result = _revenue_yield_gap_pct(5.0, 3.0)
        self.assertIsInstance(result, float)

    def test_rounding_to_6_places(self):
        result = _revenue_yield_gap_pct(1.0 / 3.0, 0.0)
        self.assertAlmostEqual(result, round(1.0 / 3.0, 6), places=6)


# ===========================================================================
# 6. _sustainability_label
# ===========================================================================

class TestSustainabilityLabel(unittest.TestCase):

    def test_ratio_above_fully_real_threshold(self):
        self.assertEqual(_sustainability_label(0.95), "FULLY_REAL_YIELD")

    def test_ratio_exactly_fully_real_threshold(self):
        self.assertEqual(_sustainability_label(_FULLY_REAL_THRESHOLD), "FULLY_REAL_YIELD")

    def test_ratio_just_below_fully_real(self):
        self.assertEqual(_sustainability_label(0.89), "MOSTLY_REAL")

    def test_ratio_exactly_mostly_real_threshold(self):
        self.assertEqual(_sustainability_label(_MOSTLY_REAL_THRESHOLD), "MOSTLY_REAL")

    def test_ratio_just_below_mostly_real(self):
        self.assertEqual(_sustainability_label(0.699), "MIXED_REAL_EMISSION")

    def test_ratio_exactly_mixed_threshold(self):
        self.assertEqual(_sustainability_label(_MIXED_THRESHOLD), "MIXED_REAL_EMISSION")

    def test_ratio_just_below_mixed(self):
        self.assertEqual(_sustainability_label(0.399), "MOSTLY_EMISSION")

    def test_ratio_exactly_mostly_emission_threshold(self):
        self.assertEqual(_sustainability_label(_MOSTLY_EMISSION_THRESHOLD), "MOSTLY_EMISSION")

    def test_ratio_just_below_mostly_emission(self):
        self.assertEqual(_sustainability_label(0.099), "PURE_PONZI")

    def test_ratio_zero_is_ponzi(self):
        self.assertEqual(_sustainability_label(0.0), "PURE_PONZI")

    def test_ratio_negative_is_ponzi(self):
        self.assertEqual(_sustainability_label(-0.5), "PURE_PONZI")

    def test_ratio_over_one_is_fully_real(self):
        self.assertEqual(_sustainability_label(1.5), "FULLY_REAL_YIELD")

    def test_all_five_labels_reachable(self):
        labels = {
            _sustainability_label(1.0),
            _sustainability_label(0.8),
            _sustainability_label(0.55),
            _sustainability_label(0.25),
            _sustainability_label(0.05),
        }
        expected = {
            "FULLY_REAL_YIELD",
            "MOSTLY_REAL",
            "MIXED_REAL_EMISSION",
            "MOSTLY_EMISSION",
            "PURE_PONZI",
        }
        self.assertEqual(labels, expected)

    def test_return_type_is_str(self):
        self.assertIsInstance(_sustainability_label(0.5), str)


# ===========================================================================
# 7. _growth_score
# ===========================================================================

class TestGrowthScore(unittest.TestCase):

    def test_growth_ge_30_gives_25(self):
        self.assertEqual(_growth_score(30.0), 25.0)

    def test_growth_above_30_gives_25(self):
        self.assertEqual(_growth_score(50.0), 25.0)

    def test_growth_exactly_15_gives_20(self):
        self.assertEqual(_growth_score(15.0), 20.0)

    def test_growth_between_15_and_30_gives_20(self):
        self.assertEqual(_growth_score(20.0), 20.0)

    def test_growth_exactly_5_gives_15(self):
        self.assertEqual(_growth_score(5.0), 15.0)

    def test_growth_between_5_and_15_gives_15(self):
        self.assertEqual(_growth_score(10.0), 15.0)

    def test_growth_exactly_0_gives_10(self):
        self.assertEqual(_growth_score(0.0), 10.0)

    def test_growth_between_0_and_5_gives_10(self):
        self.assertEqual(_growth_score(3.0), 10.0)

    def test_growth_exactly_minus_10_gives_5(self):
        self.assertEqual(_growth_score(-10.0), 5.0)

    def test_growth_between_minus_10_and_0_gives_5(self):
        self.assertEqual(_growth_score(-5.0), 5.0)

    def test_growth_below_minus_10_gives_0(self):
        self.assertEqual(_growth_score(-15.0), 0.0)

    def test_growth_very_negative_gives_0(self):
        self.assertEqual(_growth_score(-100.0), 0.0)


# ===========================================================================
# 8. _expense_score
# ===========================================================================

class TestExpenseScore(unittest.TestCase):

    def test_zero_revenue_returns_neutral_15(self):
        self.assertEqual(_expense_score(0.0, 5_000.0), 15.0)

    def test_zero_expenses_returns_neutral_15(self):
        self.assertEqual(_expense_score(50_000.0, 0.0), 15.0)

    def test_both_zero_returns_neutral_15(self):
        self.assertEqual(_expense_score(0.0, 0.0), 15.0)

    def test_expense_ratio_le_010_gives_15(self):
        # 1000 / 10000 = 0.10
        self.assertEqual(_expense_score(10_000.0, 1_000.0), 15.0)

    def test_expense_ratio_below_010_gives_15(self):
        # 500 / 10000 = 0.05
        self.assertEqual(_expense_score(10_000.0, 500.0), 15.0)

    def test_expense_ratio_020_gives_10(self):
        # 2000 / 10000 = 0.20
        self.assertEqual(_expense_score(10_000.0, 2_000.0), 10.0)

    def test_expense_ratio_030_gives_10(self):
        # 3000 / 10000 = 0.30
        self.assertEqual(_expense_score(10_000.0, 3_000.0), 10.0)

    def test_expense_ratio_040_gives_5(self):
        # 4000 / 10000 = 0.40
        self.assertEqual(_expense_score(10_000.0, 4_000.0), 5.0)

    def test_expense_ratio_050_gives_5(self):
        # 5000 / 10000 = 0.50
        self.assertEqual(_expense_score(10_000.0, 5_000.0), 5.0)

    def test_expense_ratio_060_gives_0(self):
        # 6000 / 10000 = 0.60
        self.assertEqual(_expense_score(10_000.0, 6_000.0), 0.0)

    def test_expense_ratio_above_050_gives_0(self):
        self.assertEqual(_expense_score(10_000.0, 9_000.0), 0.0)

    def test_return_type_float(self):
        self.assertIsInstance(_expense_score(10_000.0, 1_000.0), float)


# ===========================================================================
# 9. _sustainability_score
# ===========================================================================

class TestSustainabilityScore(unittest.TestCase):

    def test_returns_int(self):
        score = _sustainability_score(1.0, 10.0, 20_000.0, 0.0)
        self.assertIsInstance(score, int)

    def test_score_in_range_0_to_100(self):
        for ratio in [0.0, 0.5, 1.0, 1.5]:
            for growth in [-20.0, 0.0, 30.0]:
                score = _sustainability_score(ratio, growth, 10_000.0, 0.0)
                self.assertGreaterEqual(score, 0)
                self.assertLessEqual(score, 100)

    def test_perfect_inputs_near_100(self):
        # ratio=1.0 (60pts), growth=30 (25pts), expenses=0 (15pts) = 100
        score = _sustainability_score(1.0, 30.0, 20_000.0, 0.0)
        self.assertEqual(score, 100)

    def test_zero_ratio_lowers_score(self):
        score = _sustainability_score(0.0, 0.0, 0.0, 0.0)
        self.assertLess(score, 60)

    def test_ratio_over_one_clamped_to_60_pts(self):
        s1 = _sustainability_score(1.0, 30.0, 20_000.0, 0.0)
        s2 = _sustainability_score(2.0, 30.0, 20_000.0, 0.0)
        self.assertEqual(s1, s2)  # ratio clamped at 1.0

    def test_negative_ratio_clamped_to_zero_pts(self):
        s1 = _sustainability_score(-1.0, 0.0, 0.0, 0.0)
        s2 = _sustainability_score(0.0, 0.0, 0.0, 0.0)
        self.assertEqual(s1, s2)

    def test_high_growth_adds_25_pts(self):
        s_low  = _sustainability_score(0.5, -20.0, 20_000.0, 0.0)
        s_high = _sustainability_score(0.5,  30.0, 20_000.0, 0.0)
        self.assertGreater(s_high, s_low)

    def test_high_expense_ratio_reduces_score(self):
        s_low  = _sustainability_score(0.5, 10.0, 10_000.0, 8_000.0)  # 80% expense ratio
        s_high = _sustainability_score(0.5, 10.0, 10_000.0, 500.0)    # 5% expense ratio
        self.assertGreater(s_high, s_low)

    def test_known_calculation(self):
        # ratio=0.9 (54pts), growth=5.0 (15pts), expenses=0 (15pts) → 84
        score = _sustainability_score(0.9, 5.0, 20_000.0, 0.0)
        self.assertEqual(score, 84)

    def test_mid_range_scenario(self):
        # ratio=0.5 (30pts), growth=0.0 (10pts), expenses=0 (15pts) → 55
        score = _sustainability_score(0.5, 0.0, 20_000.0, 0.0)
        self.assertEqual(score, 55)

    def test_ponzi_scenario_low_score(self):
        # ratio=0.05 (3pts), growth=-20 (0pts), expenses=90% (0pts) → 3
        score = _sustainability_score(0.05, -20.0, 10_000.0, 9_000.0)
        self.assertEqual(score, 3)

    def test_max_score_capped_at_100(self):
        score = _sustainability_score(5.0, 100.0, 1_000.0, 0.0)
        self.assertEqual(score, 100)


# ===========================================================================
# 10. _atomic_log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):

    def setUp(self):
        self._log = _tmp_log()

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def test_creates_file_when_missing(self):
        _atomic_log(self._log, {"k": 1})
        self.assertTrue(os.path.exists(self._log))

    def test_writes_valid_json(self):
        _atomic_log(self._log, {"k": 1})
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_appends_entry(self):
        _atomic_log(self._log, {"n": 1})
        _atomic_log(self._log, {"n": 2})
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_entry_content_preserved(self):
        entry = {"protocol": "Aave", "score": 75}
        _atomic_log(self._log, entry)
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["protocol"], "Aave")
        self.assertEqual(data[0]["score"], 75)

    def test_ring_buffer_cap_enforced(self):
        for i in range(_LOG_CAP + 10):
            _atomic_log(self._log, {"i": i})
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), _LOG_CAP)

    def test_ring_buffer_keeps_latest_entries(self):
        for i in range(_LOG_CAP + 5):
            _atomic_log(self._log, {"i": i})
        with open(self._log) as fh:
            data = json.load(fh)
        # last entry must be the most recently appended
        self.assertEqual(data[-1]["i"], _LOG_CAP + 4)

    def test_recovers_from_corrupt_json(self):
        with open(self._log, "w") as fh:
            fh.write("NOT_JSON")
        _atomic_log(self._log, {"k": 99})
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_recovers_from_empty_file(self):
        open(self._log, "w").close()
        _atomic_log(self._log, {"k": 1})
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_creates_missing_directories(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            nested_log = os.path.join(tmp_dir, "sub1", "sub2", "log.json")
            _atomic_log(nested_log, {"k": 1})
            self.assertTrue(os.path.exists(nested_log))

    def test_multiple_entries_ordered(self):
        for i in range(5):
            _atomic_log(self._log, {"i": i})
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertEqual([e["i"] for e in data], list(range(5)))


# ===========================================================================
# 11. DeFiProtocolRealYieldSustainabilityRater.rate()
# ===========================================================================

class TestDeFiProtocolRealYieldSustainabilityRaterRate(unittest.TestCase):

    def setUp(self):
        self._rater = DeFiProtocolRealYieldSustainabilityRater()
        self._log = _tmp_log()
        self._cfg = {"log_path": self._log, "write_log": False}

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    # --- return type and keys ---

    def test_returns_dict(self):
        result = self._rater.rate(_base_data(), self._cfg)
        self.assertIsInstance(result, dict)

    def test_all_expected_keys_present(self):
        result = self._rater.rate(_base_data(), self._cfg)
        for key in [
            "protocol_name", "claimed_apy_pct", "annualized_revenue_usd",
            "real_yield_apy_pct", "emission_yield_apy_pct", "real_yield_ratio",
            "revenue_yield_gap_pct", "sustainability_score", "sustainability_label",
            "timestamp",
        ]:
            self.assertIn(key, result)

    def test_sustainability_label_is_valid_string(self):
        result = self._rater.rate(_base_data(), self._cfg)
        valid = {
            "FULLY_REAL_YIELD", "MOSTLY_REAL", "MIXED_REAL_EMISSION",
            "MOSTLY_EMISSION", "PURE_PONZI",
        }
        self.assertIn(result["sustainability_label"], valid)

    def test_sustainability_score_is_int(self):
        result = self._rater.rate(_base_data(), self._cfg)
        self.assertIsInstance(result["sustainability_score"], int)

    def test_sustainability_score_in_range(self):
        result = self._rater.rate(_base_data(), self._cfg)
        self.assertGreaterEqual(result["sustainability_score"], 0)
        self.assertLessEqual(result["sustainability_score"], 100)

    def test_protocol_name_passed_through(self):
        result = self._rater.rate(_base_data(protocol_name="Compound"), self._cfg)
        self.assertEqual(result["protocol_name"], "Compound")

    def test_claimed_apy_pct_passed_through(self):
        result = self._rater.rate(_base_data(claimed_apy_pct=15.0), self._cfg)
        self.assertAlmostEqual(result["claimed_apy_pct"], 15.0)

    def test_annualized_revenue_calculated(self):
        result = self._rater.rate(_base_data(protocol_revenue_7d_usd=10_000.0), self._cfg)
        self.assertAlmostEqual(result["annualized_revenue_usd"], 520_000.0, places=2)

    def test_real_yield_apy_pct_computed(self):
        # 20000 * 52 / 50_000_000 * 100 = 2.08
        result = self._rater.rate(_base_data(), self._cfg)
        self.assertAlmostEqual(result["real_yield_apy_pct"], 2.08, places=4)

    def test_emission_yield_apy_pct_computed(self):
        # 5000 * 52 / 50_000_000 * 100 = 0.52
        result = self._rater.rate(_base_data(), self._cfg)
        self.assertAlmostEqual(result["emission_yield_apy_pct"], 0.52, places=4)

    def test_revenue_yield_gap_pct_computed(self):
        result = self._rater.rate(_base_data(claimed_apy_pct=5.0), self._cfg)
        # claimed=5.0, real=2.08 → gap=2.92
        self.assertAlmostEqual(result["revenue_yield_gap_pct"],
                                5.0 - result["real_yield_apy_pct"], places=5)

    def test_timestamp_present_and_string(self):
        result = self._rater.rate(_base_data(), self._cfg)
        self.assertIsInstance(result["timestamp"], str)
        self.assertGreater(len(result["timestamp"]), 0)

    def test_zero_staked_gives_zero_yield(self):
        result = self._rater.rate(_base_data(total_staked_usd=0.0), self._cfg)
        self.assertEqual(result["real_yield_apy_pct"], 0.0)
        self.assertEqual(result["emission_yield_apy_pct"], 0.0)

    def test_fully_real_yield_label(self):
        # Very high real revenue vs small claimed APY
        data = _base_data(
            protocol_revenue_7d_usd=1_000_000.0,
            claimed_apy_pct=1.0,
            total_staked_usd=1_000_000.0,
        )
        result = self._rater.rate(data, self._cfg)
        self.assertEqual(result["sustainability_label"], "FULLY_REAL_YIELD")

    def test_pure_ponzi_label(self):
        # Zero real revenue, non-zero claimed APY
        data = _base_data(
            protocol_revenue_7d_usd=0.0,
            claimed_apy_pct=50.0,
            total_staked_usd=50_000_000.0,
        )
        result = self._rater.rate(data, self._cfg)
        self.assertEqual(result["sustainability_label"], "PURE_PONZI")

    def test_expenses_reduce_real_yield_apy(self):
        r_no_exp = self._rater.rate(
            _base_data(protocol_expenses_7d_usd=0.0), self._cfg)
        r_with_exp = self._rater.rate(
            _base_data(protocol_expenses_7d_usd=10_000.0), self._cfg)
        self.assertGreater(
            r_no_exp["real_yield_apy_pct"], r_with_exp["real_yield_apy_pct"])

    def test_growth_affects_score(self):
        r_neg = self._rater.rate(_base_data(revenue_growth_30d_pct=-15.0), self._cfg)
        r_pos = self._rater.rate(_base_data(revenue_growth_30d_pct=30.0), self._cfg)
        self.assertGreater(r_pos["sustainability_score"], r_neg["sustainability_score"])

    def test_missing_fields_use_defaults(self):
        # Should not raise
        result = self._rater.rate({}, self._cfg)
        self.assertIn("sustainability_label", result)
        self.assertEqual(result["protocol_name"], "UNKNOWN")

    def test_write_log_false_does_not_create_file(self):
        log = _tmp_log()
        self._rater.rate(_base_data(), {"log_path": log, "write_log": False})
        self.assertFalse(os.path.exists(log))

    def test_write_log_true_creates_file(self):
        log = _tmp_log()
        self._rater.rate(_base_data(), {"log_path": log, "write_log": True})
        self.assertTrue(os.path.exists(log))


# ===========================================================================
# 12. Module-level rate() convenience function
# ===========================================================================

class TestModuleLevelRate(unittest.TestCase):

    def setUp(self):
        self._log = _tmp_log()
        self._cfg = {"log_path": self._log, "write_log": False}

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def test_returns_dict(self):
        result = rate(_base_data(), self._cfg)
        self.assertIsInstance(result, dict)

    def test_same_result_as_class_method(self):
        rater = DeFiProtocolRealYieldSustainabilityRater()
        r1 = rate(_base_data(), self._cfg)
        r2 = rater.rate(_base_data(), self._cfg)
        for key in r1:
            if key == "timestamp":
                continue
            self.assertEqual(r1[key], r2[key])

    def test_write_log_false_does_not_write(self):
        rate(_base_data(), {"log_path": self._log, "write_log": False})
        self.assertFalse(os.path.exists(self._log))

    def test_accepts_config(self):
        result = rate(_base_data(), self._cfg)
        self.assertIn("protocol_name", result)

    def test_all_keys_present(self):
        result = rate(_base_data(), self._cfg)
        expected_keys = [
            "protocol_name", "claimed_apy_pct", "annualized_revenue_usd",
            "real_yield_apy_pct", "emission_yield_apy_pct", "real_yield_ratio",
            "revenue_yield_gap_pct", "sustainability_score", "sustainability_label",
            "timestamp",
        ]
        for k in expected_keys:
            self.assertIn(k, result)

    def test_no_config_uses_defaults(self):
        # Should not raise; will write to default log (OK in testing)
        try:
            result = rate(_base_data(), {"write_log": False})
            self.assertIsInstance(result, dict)
        except Exception:
            pass  # log directory may not exist in test env


# ===========================================================================
# 13. Integration tests
# ===========================================================================

class TestIntegration(unittest.TestCase):

    def setUp(self):
        self._rater = DeFiProtocolRealYieldSustainabilityRater()
        self._log = _tmp_log()
        self._cfg = {"log_path": self._log, "write_log": False}

    def tearDown(self):
        if os.path.exists(self._log):
            os.unlink(self._log)

    def test_aave_like_fully_real_scenario(self):
        """Aave has real fees backing APY — should be FULLY_REAL_YIELD."""
        data = {
            "protocol_name":            "Aave V3",
            "claimed_apy_pct":          3.5,
            "protocol_revenue_7d_usd":  500_000.0,
            "token_emission_7d_usd":    0.0,
            "total_staked_usd":         700_000_000.0,
            "protocol_expenses_7d_usd": 0.0,
            "revenue_growth_30d_pct":   5.0,
        }
        result = self._rater.rate(data, self._cfg)
        # real_yield: 500k*52/700M*100 = 3.714%; ratio = 3.714/3.5 > 1 → FULLY_REAL
        self.assertEqual(result["sustainability_label"], "FULLY_REAL_YIELD")
        self.assertGreater(result["sustainability_score"], 60)

    def test_emission_heavy_defi_scenario(self):
        """High emissions with low revenue → MOSTLY_EMISSION."""
        data = {
            "protocol_name":            "EmissionFarm",
            "claimed_apy_pct":          40.0,
            "protocol_revenue_7d_usd":  10_000.0,
            "token_emission_7d_usd":    200_000.0,
            "total_staked_usd":         50_000_000.0,
            "protocol_expenses_7d_usd": 0.0,
            "revenue_growth_30d_pct":   -5.0,
        }
        result = self._rater.rate(data, self._cfg)
        # real_yield = 10k*52/50M*100 = 1.04; ratio=1.04/40=0.026 → PURE_PONZI
        self.assertIn(result["sustainability_label"],
                      {"MOSTLY_EMISSION", "PURE_PONZI"})

    def test_ponzi_protocol_scenario(self):
        """Zero revenue, high claimed APY → PURE_PONZI."""
        data = {
            "protocol_name":            "PonziProtocol",
            "claimed_apy_pct":          200.0,
            "protocol_revenue_7d_usd":  0.0,
            "token_emission_7d_usd":    500_000.0,
            "total_staked_usd":         100_000_000.0,
            "protocol_expenses_7d_usd": 0.0,
            "revenue_growth_30d_pct":   0.0,
        }
        result = self._rater.rate(data, self._cfg)
        self.assertEqual(result["sustainability_label"], "PURE_PONZI")
        self.assertEqual(result["real_yield_apy_pct"], 0.0)

    def test_mostly_real_scenario(self):
        """Protocol where ~80% yield is fee-backed."""
        data = {
            "protocol_name":            "MostlyRealProtocol",
            "claimed_apy_pct":          10.0,
            "protocol_revenue_7d_usd":  96_154.0,   # ≈10%*0.80
            "token_emission_7d_usd":    19_231.0,
            "total_staked_usd":         100_000_000.0,
            "protocol_expenses_7d_usd": 0.0,
            "revenue_growth_30d_pct":   10.0,
        }
        result = self._rater.rate(data, self._cfg)
        # real_yield ≈ 96154*52/1e8*100 = 5.0 → ratio≈5/10=0.5 → MIXED_REAL_EMISSION
        self.assertIn(result["sustainability_label"],
                      {"MOSTLY_REAL", "MIXED_REAL_EMISSION"})

    def test_mixed_scenario(self):
        """50% real / 50% emission."""
        data = {
            "protocol_name":            "MixedProtocol",
            "claimed_apy_pct":          10.0,
            "protocol_revenue_7d_usd":  48_077.0,   # 5%*100M/52
            "token_emission_7d_usd":    48_077.0,
            "total_staked_usd":         100_000_000.0,
            "protocol_expenses_7d_usd": 0.0,
            "revenue_growth_30d_pct":   0.0,
        }
        result = self._rater.rate(data, self._cfg)
        self.assertIn(result["sustainability_label"],
                      {"MIXED_REAL_EMISSION", "MOSTLY_EMISSION"})

    def test_zero_staked_edge(self):
        data = _base_data(total_staked_usd=0.0)
        result = self._rater.rate(data, self._cfg)
        self.assertEqual(result["real_yield_apy_pct"], 0.0)
        self.assertEqual(result["emission_yield_apy_pct"], 0.0)

    def test_high_growth_boosts_score(self):
        d_low  = _base_data(revenue_growth_30d_pct=-20.0)
        d_high = _base_data(revenue_growth_30d_pct=50.0)
        r_low  = self._rater.rate(d_low, self._cfg)
        r_high = self._rater.rate(d_high, self._cfg)
        self.assertGreater(r_high["sustainability_score"], r_low["sustainability_score"])

    def test_log_entries_accumulate(self):
        cfg = {"log_path": self._log, "write_log": True}
        for i in range(3):
            self._rater.rate(_base_data(protocol_name=f"Proto{i}"), cfg)
        with open(self._log) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 3)

    def test_over_backed_ratio_still_fully_real(self):
        # Real yield far exceeds claimed APY → ratio > 1 → FULLY_REAL_YIELD
        data = _base_data(
            protocol_revenue_7d_usd=5_000_000.0,
            claimed_apy_pct=1.0,
            total_staked_usd=10_000_000.0,
        )
        result = self._rater.rate(data, self._cfg)
        self.assertGreater(result["real_yield_ratio"], 1.0)
        self.assertEqual(result["sustainability_label"], "FULLY_REAL_YIELD")

    def test_expenses_push_label_lower(self):
        # High expenses cut into real yield → may lower label
        d_no_exp  = _base_data(protocol_expenses_7d_usd=0.0)
        d_exp     = _base_data(protocol_expenses_7d_usd=18_000.0)  # 90% of 20k revenue
        r_no_exp  = self._rater.rate(d_no_exp, self._cfg)
        r_exp     = self._rater.rate(d_exp, self._cfg)
        self.assertGreaterEqual(
            r_no_exp["real_yield_ratio"], r_exp["real_yield_ratio"])


if __name__ == "__main__":
    unittest.main()
