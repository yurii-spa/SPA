"""
Tests for MP-1107 ProtocolDeFiCollateralHealthFactorSimulator
Comprehensive unittest suite — pure stdlib, no third-party dependencies.
Run: python3 -m unittest spa_core.tests.test_protocol_defi_collateral_health_factor_simulator
"""

import json
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

from spa_core.analytics.protocol_defi_collateral_health_factor_simulator import (
    _safe_float,
    _safe_int,
    _atomic_log,
    _compute_health_factor,
    _compute_ltv_pct,
    _compute_debt_with_interest,
    _compute_safe_price_drop_pct,
    _compute_days_to_liquidation_at_flat_rate,
    _compute_scenario_results,
    _compute_hf_label,
    analyze,
    ProtocolDeFiCollateralHealthFactorSimulator,
    ALL_HF_LABELS,
    LABEL_FORTRESS,
    LABEL_HEALTHY,
    LABEL_CAUTION,
    LABEL_DANGER,
    LABEL_LIQUIDATED,
    _LOG_CAP,
    _EPS,
    _NEVER,
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


def _std_data(**overrides):
    base = {
        "protocol_name": "TestAave",
        "collateral_usd": 100_000.0,
        "collateral_liquidation_threshold_pct": 85.0,
        "total_debt_usd": 60_000.0,
        "debt_interest_rate_annual_pct": 5.0,
        "scenario_price_drop_pcts": [10.0, 20.0, 30.0, 50.0],
        "days_to_simulate": 90,
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. _safe_float
# ===========================================================================
class TestSafeFloat(unittest.TestCase):

    def test_int_to_float(self):
        self.assertEqual(_safe_float(10), 10.0)

    def test_float_unchanged(self):
        self.assertAlmostEqual(_safe_float(3.14), 3.14)

    def test_numeric_string(self):
        self.assertAlmostEqual(_safe_float("2.5"), 2.5)

    def test_none_default(self):
        self.assertEqual(_safe_float(None, -1.0), -1.0)

    def test_non_numeric_string_default(self):
        self.assertEqual(_safe_float("xyz", 99.0), 99.0)

    def test_default_zero(self):
        self.assertEqual(_safe_float("bad"), 0.0)

    def test_zero_string(self):
        self.assertEqual(_safe_float("0"), 0.0)

    def test_negative_string(self):
        self.assertAlmostEqual(_safe_float("-5.5"), -5.5)

    def test_list_returns_default(self):
        self.assertEqual(_safe_float([], 7.0), 7.0)


# ===========================================================================
# 2. _safe_int
# ===========================================================================
class TestSafeInt(unittest.TestCase):

    def test_int_passthrough(self):
        self.assertEqual(_safe_int(5), 5)

    def test_float_truncated(self):
        self.assertEqual(_safe_int(3.9), 3)

    def test_string_numeric(self):
        self.assertEqual(_safe_int("30"), 30)

    def test_none_default(self):
        self.assertEqual(_safe_int(None, 7), 7)

    def test_invalid_string_default(self):
        self.assertEqual(_safe_int("abc", 99), 99)

    def test_zero_string(self):
        self.assertEqual(_safe_int("0"), 0)

    def test_default_zero(self):
        self.assertEqual(_safe_int("bad"), 0)


# ===========================================================================
# 3. _compute_health_factor
# ===========================================================================
class TestComputeHealthFactor(unittest.TestCase):

    def test_basic_hf(self):
        # 100_000 * 85/100 / 60_000 = 85_000 / 60_000 ≈ 1.4167
        hf = _compute_health_factor(100_000.0, 85.0, 60_000.0)
        self.assertAlmostEqual(hf, 85_000.0 / 60_000.0, places=5)

    def test_no_debt_returns_inf(self):
        hf = _compute_health_factor(100_000.0, 85.0, 0.0)
        self.assertEqual(hf, float("inf"))

    def test_near_zero_debt_returns_inf(self):
        hf = _compute_health_factor(100_000.0, 85.0, _EPS / 10)
        self.assertEqual(hf, float("inf"))

    def test_zero_collateral_zero_hf(self):
        hf = _compute_health_factor(0.0, 85.0, 60_000.0)
        self.assertAlmostEqual(hf, 0.0)

    def test_full_threshold(self):
        # 100% threshold: HF = collateral / debt
        hf = _compute_health_factor(100.0, 100.0, 80.0)
        self.assertAlmostEqual(hf, 100.0 / 80.0)

    def test_zero_threshold(self):
        hf = _compute_health_factor(100_000.0, 0.0, 60_000.0)
        self.assertAlmostEqual(hf, 0.0)

    def test_hf_greater_than_one_when_safe(self):
        hf = _compute_health_factor(200_000.0, 80.0, 100_000.0)
        self.assertGreater(hf, 1.0)

    def test_hf_less_than_one_when_liquidated(self):
        hf = _compute_health_factor(100_000.0, 80.0, 90_000.0)
        self.assertLess(hf, 1.0)

    def test_hf_exactly_one(self):
        # 100k * 80% / 80k = 1.0
        hf = _compute_health_factor(100_000.0, 80.0, 80_000.0)
        self.assertAlmostEqual(hf, 1.0)

    def test_large_values(self):
        hf = _compute_health_factor(1e9, 85.0, 5e8)
        self.assertAlmostEqual(hf, 1e9 * 0.85 / 5e8)

    def test_returns_float(self):
        self.assertIsInstance(_compute_health_factor(100_000.0, 80.0, 50_000.0), float)


# ===========================================================================
# 4. _compute_ltv_pct
# ===========================================================================
class TestComputeLtvPct(unittest.TestCase):

    def test_basic_ltv(self):
        # 60k debt / 100k collateral = 60%
        ltv = _compute_ltv_pct(100_000.0, 60_000.0)
        self.assertAlmostEqual(ltv, 60.0)

    def test_zero_collateral_returns_zero(self):
        self.assertEqual(_compute_ltv_pct(0.0, 60_000.0), 0.0)

    def test_zero_debt_zero_ltv(self):
        self.assertAlmostEqual(_compute_ltv_pct(100_000.0, 0.0), 0.0)

    def test_100pct_ltv(self):
        self.assertAlmostEqual(_compute_ltv_pct(100_000.0, 100_000.0), 100.0)

    def test_over_100pct_possible(self):
        # If debt > collateral
        ltv = _compute_ltv_pct(100.0, 150.0)
        self.assertAlmostEqual(ltv, 150.0)

    def test_small_ltv(self):
        ltv = _compute_ltv_pct(1_000_000.0, 50_000.0)
        self.assertAlmostEqual(ltv, 5.0)

    def test_returns_float(self):
        self.assertIsInstance(_compute_ltv_pct(100_000.0, 50_000.0), float)

    def test_near_zero_collateral_returns_zero(self):
        self.assertEqual(_compute_ltv_pct(_EPS / 10, 60_000.0), 0.0)


# ===========================================================================
# 5. _compute_debt_with_interest
# ===========================================================================
class TestComputeDebtWithInterest(unittest.TestCase):

    def test_zero_days_unchanged(self):
        d = _compute_debt_with_interest(100_000.0, 5.0, 0)
        self.assertAlmostEqual(d, 100_000.0)

    def test_negative_days_unchanged(self):
        d = _compute_debt_with_interest(100_000.0, 5.0, -10)
        self.assertAlmostEqual(d, 100_000.0)

    def test_one_year_at_10pct(self):
        # 100k * (1 + 0.10 * 365/365) = 110k
        d = _compute_debt_with_interest(100_000.0, 10.0, 365)
        self.assertAlmostEqual(d, 110_000.0)

    def test_half_year_at_10pct(self):
        d = _compute_debt_with_interest(100_000.0, 10.0, 182)
        expected = 100_000.0 * (1 + 0.10 * 182 / 365)
        self.assertAlmostEqual(d, expected, places=4)

    def test_zero_rate_unchanged(self):
        d = _compute_debt_with_interest(80_000.0, 0.0, 90)
        self.assertAlmostEqual(d, 80_000.0)

    def test_debt_increases_with_days(self):
        d90 = _compute_debt_with_interest(100_000.0, 5.0, 90)
        d180 = _compute_debt_with_interest(100_000.0, 5.0, 180)
        self.assertGreater(d180, d90)

    def test_debt_increases_with_rate(self):
        d5 = _compute_debt_with_interest(100_000.0, 5.0, 90)
        d10 = _compute_debt_with_interest(100_000.0, 10.0, 90)
        self.assertGreater(d10, d5)

    def test_returns_float(self):
        self.assertIsInstance(_compute_debt_with_interest(60_000.0, 5.0, 90), float)

    def test_90_days_5pct(self):
        d = _compute_debt_with_interest(60_000.0, 5.0, 90)
        expected = 60_000.0 * (1 + 0.05 * 90 / 365)
        self.assertAlmostEqual(d, expected, places=4)

    def test_large_rate(self):
        d = _compute_debt_with_interest(10_000.0, 100.0, 365)
        self.assertAlmostEqual(d, 20_000.0)


# ===========================================================================
# 6. _compute_safe_price_drop_pct
# ===========================================================================
class TestComputeSafePriceDrop(unittest.TestCase):

    def test_basic_safe_drop(self):
        # HF = 85k / 60k ≈ 1.4167; safe drop = (1 - 60k/85k)*100 ≈ 29.41%
        safe = _compute_safe_price_drop_pct(100_000.0, 85.0, 60_000.0)
        expected = (1.0 - 60_000.0 / 85_000.0) * 100.0
        self.assertAlmostEqual(safe, expected, places=4)

    def test_no_debt_returns_100(self):
        self.assertAlmostEqual(_compute_safe_price_drop_pct(100_000.0, 85.0, 0.0), 100.0)

    def test_zero_collateral_adj_returns_zero(self):
        # 0 threshold → adj = 0
        safe = _compute_safe_price_drop_pct(100_000.0, 0.0, 60_000.0)
        self.assertAlmostEqual(safe, 0.0)

    def test_already_liquidated_returns_zero(self):
        # debt > adj_collateral → already underwater
        safe = _compute_safe_price_drop_pct(100_000.0, 50.0, 80_000.0)
        self.assertAlmostEqual(safe, 0.0)

    def test_result_in_range_0_100(self):
        safe = _compute_safe_price_drop_pct(100_000.0, 80.0, 60_000.0)
        self.assertGreaterEqual(safe, 0.0)
        self.assertLessEqual(safe, 100.0)

    def test_higher_debt_smaller_safe_drop(self):
        safe_low = _compute_safe_price_drop_pct(100_000.0, 85.0, 40_000.0)
        safe_high = _compute_safe_price_drop_pct(100_000.0, 85.0, 70_000.0)
        self.assertGreater(safe_low, safe_high)

    def test_higher_threshold_bigger_safe_drop(self):
        safe_80 = _compute_safe_price_drop_pct(100_000.0, 80.0, 60_000.0)
        safe_90 = _compute_safe_price_drop_pct(100_000.0, 90.0, 60_000.0)
        self.assertGreater(safe_90, safe_80)

    def test_equal_debt_and_adj_returns_zero(self):
        # debt == adj → p = 0
        safe = _compute_safe_price_drop_pct(100_000.0, 80.0, 80_000.0)
        self.assertAlmostEqual(safe, 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_compute_safe_price_drop_pct(100_000.0, 85.0, 60_000.0), float)


# ===========================================================================
# 7. _compute_days_to_liquidation_at_flat_rate
# ===========================================================================
class TestComputeDaysToLiquidation(unittest.TestCase):

    def test_already_liquidated_returns_zero(self):
        # HF < 1.0: debt > adj_collateral
        days = _compute_days_to_liquidation_at_flat_rate(100_000.0, 50.0, 90_000.0, 5.0)
        self.assertAlmostEqual(days, 0.0)

    def test_no_debt_returns_inf(self):
        days = _compute_days_to_liquidation_at_flat_rate(100_000.0, 85.0, 0.0, 5.0)
        self.assertEqual(days, float("inf"))

    def test_zero_rate_returns_inf(self):
        days = _compute_days_to_liquidation_at_flat_rate(100_000.0, 85.0, 60_000.0, 0.0)
        self.assertEqual(days, float("inf"))

    def test_positive_days_when_safe(self):
        days = _compute_days_to_liquidation_at_flat_rate(100_000.0, 85.0, 60_000.0, 5.0)
        self.assertGreater(days, 0.0)
        self.assertLess(days, float("inf"))

    def test_higher_rate_fewer_days(self):
        days_low = _compute_days_to_liquidation_at_flat_rate(100_000.0, 80.0, 60_000.0, 2.0)
        days_high = _compute_days_to_liquidation_at_flat_rate(100_000.0, 80.0, 60_000.0, 20.0)
        self.assertGreater(days_low, days_high)

    def test_higher_debt_fewer_days(self):
        days_low = _compute_days_to_liquidation_at_flat_rate(100_000.0, 80.0, 40_000.0, 5.0)
        days_high = _compute_days_to_liquidation_at_flat_rate(100_000.0, 80.0, 70_000.0, 5.0)
        self.assertGreater(days_low, days_high)

    def test_formula_consistency(self):
        # t = 365 * (HF - 1) / (rate/100)
        # HF = 100k * 80% / 60k = 1.3333
        rate = 5.0
        hf = 100_000.0 * 0.80 / 60_000.0
        expected = 365.0 * (hf - 1.0) / (rate / 100.0)
        days = _compute_days_to_liquidation_at_flat_rate(100_000.0, 80.0, 60_000.0, rate)
        self.assertAlmostEqual(days, expected, places=3)

    def test_returns_float(self):
        days = _compute_days_to_liquidation_at_flat_rate(100_000.0, 85.0, 60_000.0, 5.0)
        self.assertIsInstance(days, float)

    def test_near_zero_rate_returns_inf(self):
        days = _compute_days_to_liquidation_at_flat_rate(100_000.0, 85.0, 60_000.0, _EPS / 10)
        self.assertEqual(days, float("inf"))

    def test_near_zero_debt_returns_inf(self):
        days = _compute_days_to_liquidation_at_flat_rate(100_000.0, 85.0, _EPS / 10, 5.0)
        self.assertEqual(days, float("inf"))


# ===========================================================================
# 8. _compute_scenario_results
# ===========================================================================
class TestComputeScenarioResults(unittest.TestCase):

    def test_empty_scenarios(self):
        results = _compute_scenario_results(100_000.0, 85.0, 60_000.0, [])
        self.assertEqual(results, [])

    def test_single_scenario(self):
        results = _compute_scenario_results(100_000.0, 85.0, 60_000.0, [20.0])
        self.assertEqual(len(results), 1)

    def test_zero_drop_hf_unchanged(self):
        hf_orig = _compute_health_factor(100_000.0, 85.0, 60_000.0)
        results = _compute_scenario_results(100_000.0, 85.0, 60_000.0, [0.0])
        self.assertAlmostEqual(results[0]["new_hf"], hf_orig, places=5)

    def test_100_drop_adj_collateral_zero(self):
        results = _compute_scenario_results(100_000.0, 85.0, 60_000.0, [100.0])
        self.assertAlmostEqual(results[0]["adj_collateral"], 0.0)
        self.assertTrue(results[0]["is_liquidated"])

    def test_is_liquidated_false_when_safe(self):
        results = _compute_scenario_results(200_000.0, 85.0, 60_000.0, [5.0])
        self.assertFalse(results[0]["is_liquidated"])

    def test_is_liquidated_true_when_unsafe(self):
        # Large drop → liquidated
        results = _compute_scenario_results(100_000.0, 85.0, 90_000.0, [50.0])
        self.assertTrue(results[0]["is_liquidated"])

    def test_multiple_scenarios_ordered(self):
        results = _compute_scenario_results(100_000.0, 85.0, 60_000.0, [10.0, 20.0, 50.0])
        self.assertEqual(len(results), 3)
        # HF decreases as drop increases
        self.assertGreater(results[0]["new_hf"], results[1]["new_hf"])
        self.assertGreater(results[1]["new_hf"], results[2]["new_hf"])

    def test_adj_collateral_formula(self):
        results = _compute_scenario_results(100_000.0, 85.0, 60_000.0, [30.0])
        self.assertAlmostEqual(results[0]["adj_collateral"], 70_000.0)

    def test_price_drop_clamped_to_0_100(self):
        results = _compute_scenario_results(100_000.0, 85.0, 60_000.0, [-10.0, 150.0])
        self.assertAlmostEqual(results[0]["price_drop_pct"], 0.0)
        self.assertAlmostEqual(results[1]["price_drop_pct"], 100.0)

    def test_no_debt_scenario_never_liquidated(self):
        results = _compute_scenario_results(100_000.0, 85.0, 0.0, [50.0])
        self.assertFalse(results[0]["is_liquidated"])

    def test_result_has_required_keys(self):
        results = _compute_scenario_results(100_000.0, 85.0, 60_000.0, [20.0])
        for key in ["price_drop_pct", "adj_collateral", "new_hf", "is_liquidated"]:
            self.assertIn(key, results[0])

    def test_is_liquidated_is_bool(self):
        results = _compute_scenario_results(100_000.0, 85.0, 60_000.0, [20.0])
        self.assertIsInstance(results[0]["is_liquidated"], bool)


# ===========================================================================
# 9. _compute_hf_label
# ===========================================================================
class TestComputeHfLabel(unittest.TestCase):

    def test_hf_3_is_fortress(self):
        self.assertEqual(_compute_hf_label(3.0), LABEL_FORTRESS)

    def test_hf_2_1_is_fortress(self):
        self.assertEqual(_compute_hf_label(2.1), LABEL_FORTRESS)

    def test_hf_exactly_2_is_healthy(self):
        self.assertEqual(_compute_hf_label(2.0), LABEL_HEALTHY)

    def test_hf_1_8_is_healthy(self):
        self.assertEqual(_compute_hf_label(1.8), LABEL_HEALTHY)

    def test_hf_1_5_is_healthy(self):
        self.assertEqual(_compute_hf_label(1.5), LABEL_HEALTHY)

    def test_hf_1_49_is_caution(self):
        self.assertEqual(_compute_hf_label(1.49), LABEL_CAUTION)

    def test_hf_1_3_is_caution(self):
        self.assertEqual(_compute_hf_label(1.3), LABEL_CAUTION)

    def test_hf_1_2_is_caution(self):
        self.assertEqual(_compute_hf_label(1.2), LABEL_CAUTION)

    def test_hf_1_19_is_danger(self):
        self.assertEqual(_compute_hf_label(1.19), LABEL_DANGER)

    def test_hf_1_05_is_danger(self):
        self.assertEqual(_compute_hf_label(1.05), LABEL_DANGER)

    def test_hf_1_0_is_danger(self):
        self.assertEqual(_compute_hf_label(1.0), LABEL_DANGER)

    def test_hf_0_99_is_liquidated(self):
        self.assertEqual(_compute_hf_label(0.99), LABEL_LIQUIDATED)

    def test_hf_0_is_liquidated(self):
        self.assertEqual(_compute_hf_label(0.0), LABEL_LIQUIDATED)

    def test_hf_negative_is_liquidated(self):
        self.assertEqual(_compute_hf_label(-1.0), LABEL_LIQUIDATED)

    def test_hf_inf_is_fortress(self):
        self.assertEqual(_compute_hf_label(float("inf")), LABEL_FORTRESS)

    def test_returns_string(self):
        self.assertIsInstance(_compute_hf_label(1.5), str)

    def test_all_labels_reachable(self):
        produced = {
            _compute_hf_label(3.0),
            _compute_hf_label(1.7),
            _compute_hf_label(1.35),
            _compute_hf_label(1.1),
            _compute_hf_label(0.5),
        }
        self.assertEqual(produced, set(ALL_HF_LABELS))


# ===========================================================================
# 10. _atomic_log  (ring-buffer behaviour)
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

    def test_accumulation(self):
        for i in range(10):
            _atomic_log(self.log_path, {"i": i})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 10)

    def test_ring_buffer_cap_100(self):
        for i in range(110):
            _atomic_log(self.log_path, {"i": i})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_CAP)

    def test_ring_buffer_newest_kept(self):
        for i in range(105):
            _atomic_log(self.log_path, {"i": i})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], 104)

    def test_corrupted_file_reset(self):
        with open(self.log_path, "w") as f:
            f.write("CORRUPT")
        _atomic_log(self.log_path, {"ok": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_non_list_json_reset(self):
        with open(self.log_path, "w") as f:
            json.dump({"not": "list"}, f)
        _atomic_log(self.log_path, {"ok": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_valid_json_after_write(self):
        _atomic_log(self.log_path, {"test": 1})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_entry_is_last(self):
        _atomic_log(self.log_path, {"first": 1})
        _atomic_log(self.log_path, {"last": 2})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["last"], 2)

    def test_log_cap_constant_100(self):
        self.assertEqual(_LOG_CAP, 100)


# ===========================================================================
# 11. analyze — core function
# ===========================================================================
class TestAnalyzeFunction(unittest.TestCase):

    def test_returns_dict(self):
        r = analyze(_std_data(), config=_cfg())
        self.assertIsInstance(r, dict)

    def test_all_required_keys_present(self):
        r = analyze(_std_data(), config=_cfg())
        for key in [
            "protocol_name", "current_health_factor", "current_ltv_pct",
            "debt_with_interest_usd", "scenario_results", "safe_price_drop_pct",
            "days_to_liquidation_at_flat_rate", "health_factor_label", "timestamp",
        ]:
            self.assertIn(key, r, f"Missing key: {key}")

    def test_protocol_name_from_dict(self):
        r = analyze(_std_data(protocol_name="Compound"), config=_cfg())
        self.assertEqual(r["protocol_name"], "Compound")

    def test_protocol_name_keyword_overrides(self):
        r = analyze(_std_data(), protocol_name="Override", config=_cfg())
        self.assertEqual(r["protocol_name"], "Override")

    def test_health_factor_caution(self):
        # 100k * 85% / 60k ≈ 1.4167 → CAUTION
        r = analyze(_std_data(), config=_cfg())
        self.assertEqual(r["health_factor_label"], LABEL_CAUTION)

    def test_health_factor_fortress(self):
        r = analyze(_std_data(collateral_usd=500_000.0, total_debt_usd=50_000.0), config=_cfg())
        self.assertEqual(r["health_factor_label"], LABEL_FORTRESS)

    def test_health_factor_liquidated(self):
        r = analyze(_std_data(collateral_usd=100_000.0, total_debt_usd=120_000.0), config=_cfg())
        self.assertEqual(r["health_factor_label"], LABEL_LIQUIDATED)

    def test_health_factor_danger(self):
        r = analyze(
            _std_data(collateral_usd=100_000.0, total_debt_usd=80_000.0),
            config=_cfg(),
        )
        self.assertEqual(r["health_factor_label"], LABEL_DANGER)

    def test_health_factor_healthy(self):
        # HF = 250k * 85% / 120k = 212500/120000 ≈ 1.77 → HEALTHY
        r = analyze(
            _std_data(collateral_usd=250_000.0, total_debt_usd=120_000.0),
            config=_cfg(),
        )
        self.assertEqual(r["health_factor_label"], LABEL_HEALTHY)

    def test_scenario_results_list(self):
        r = analyze(_std_data(), config=_cfg())
        self.assertIsInstance(r["scenario_results"], list)
        self.assertEqual(len(r["scenario_results"]), 4)

    def test_scenario_results_structure(self):
        r = analyze(_std_data(), config=_cfg())
        for s in r["scenario_results"]:
            self.assertIn("price_drop_pct", s)
            self.assertIn("new_hf", s)
            self.assertIn("is_liquidated", s)

    def test_ltv_pct_correct(self):
        r = analyze(_std_data(), config=_cfg())
        # 60k / 100k = 60%
        self.assertAlmostEqual(r["current_ltv_pct"], 60.0)

    def test_debt_with_interest_greater_than_debt(self):
        r = analyze(_std_data(debt_interest_rate_annual_pct=5.0, days_to_simulate=90), config=_cfg())
        self.assertGreater(r["debt_with_interest_usd"], 60_000.0)

    def test_safe_price_drop_is_positive(self):
        r = analyze(_std_data(), config=_cfg())
        self.assertGreater(r["safe_price_drop_pct"], 0.0)

    def test_days_to_liquidation_positive_when_safe(self):
        r = analyze(_std_data(), config=_cfg())
        self.assertGreater(r["days_to_liquidation_at_flat_rate"], 0.0)

    def test_no_debt_inf_days_to_liq(self):
        r = analyze(_std_data(total_debt_usd=0.0), config=_cfg())
        self.assertEqual(r["days_to_liquidation_at_flat_rate"], float("inf"))

    def test_empty_scenarios(self):
        r = analyze(_std_data(scenario_price_drop_pcts=[]), config=_cfg())
        self.assertEqual(r["scenario_results"], [])

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_std_data(), config=_cfg())
        self.assertGreaterEqual(r["timestamp"], before)

    def test_none_data_no_crash(self):
        r = analyze(None, config=_cfg())
        self.assertIn("health_factor_label", r)

    def test_empty_dict_no_crash(self):
        r = analyze({}, config=_cfg())
        self.assertIn("health_factor_label", r)

    def test_keyword_override_collateral(self):
        r = analyze(_std_data(collateral_usd=50_000.0), collateral_usd=200_000.0, config=_cfg())
        self.assertAlmostEqual(r["collateral_usd"], 200_000.0)

    def test_negative_collateral_clamped(self):
        r = analyze(_std_data(collateral_usd=-50_000.0), config=_cfg())
        self.assertGreaterEqual(r["collateral_usd"], 0.0)

    def test_negative_debt_clamped(self):
        r = analyze(_std_data(total_debt_usd=-10_000.0), config=_cfg())
        self.assertGreaterEqual(r["total_debt_usd"], 0.0)

    def test_threshold_clamped_above_100(self):
        r = analyze(_std_data(collateral_liquidation_threshold_pct=150.0), config=_cfg())
        self.assertLessEqual(r["collateral_liquidation_threshold_pct"], 100.0)

    def test_threshold_clamped_below_0(self):
        r = analyze(_std_data(collateral_liquidation_threshold_pct=-10.0), config=_cfg())
        self.assertGreaterEqual(r["collateral_liquidation_threshold_pct"], 0.0)


# ===========================================================================
# 12. ProtocolDeFiCollateralHealthFactorSimulator class
# ===========================================================================
class TestClassWrapper(unittest.TestCase):

    def _sim(self):
        return ProtocolDeFiCollateralHealthFactorSimulator(config={"log_path": _tmp_log()})

    def test_instantiation(self):
        s = self._sim()
        self.assertIsNotNone(s)

    def test_analyze_returns_dict(self):
        s = self._sim()
        r = s.analyze(_std_data())
        self.assertIsInstance(r, dict)

    def test_analyze_uses_config_log(self):
        log_path = _tmp_log()
        s = ProtocolDeFiCollateralHealthFactorSimulator(config={"log_path": log_path})
        s.analyze(_std_data())
        self.assertTrue(os.path.exists(log_path))
        os.unlink(log_path)

    def test_analyze_accepts_kwargs(self):
        s = self._sim()
        r = s.analyze(protocol_name="KwargProtocol")
        self.assertEqual(r["protocol_name"], "KwargProtocol")

    def test_default_config_no_crash(self):
        s = ProtocolDeFiCollateralHealthFactorSimulator()
        r = s.analyze(_std_data())
        self.assertIn("health_factor_label", r)

    def test_multiple_calls_consistent(self):
        s = self._sim()
        r1 = s.analyze(_std_data())
        r2 = s.analyze(_std_data())
        self.assertEqual(r1["health_factor_label"], r2["health_factor_label"])
        self.assertAlmostEqual(r1["current_health_factor"], r2["current_health_factor"])

    def test_analyze_with_none(self):
        s = self._sim()
        r = s.analyze(None)
        self.assertIn("health_factor_label", r)

    def test_class_has_analyze_method(self):
        self.assertTrue(hasattr(ProtocolDeFiCollateralHealthFactorSimulator, "analyze"))


# ===========================================================================
# 13. Constants and module-level sanity
# ===========================================================================
class TestConstants(unittest.TestCase):

    def test_all_hf_labels_five(self):
        self.assertEqual(len(ALL_HF_LABELS), 5)

    def test_fortress_in_all_labels(self):
        self.assertIn(LABEL_FORTRESS, ALL_HF_LABELS)

    def test_liquidated_in_all_labels(self):
        self.assertIn(LABEL_LIQUIDATED, ALL_HF_LABELS)

    def test_log_cap_100(self):
        self.assertEqual(_LOG_CAP, 100)

    def test_eps_positive(self):
        self.assertGreater(_EPS, 0.0)

    def test_eps_small(self):
        self.assertLess(_EPS, 1e-6)

    def test_never_is_inf(self):
        self.assertEqual(_NEVER, float("inf"))

    def test_all_labels_strings(self):
        for lbl in ALL_HF_LABELS:
            self.assertIsInstance(lbl, str)

    def test_healthy_in_all_labels(self):
        self.assertIn(LABEL_HEALTHY, ALL_HF_LABELS)

    def test_caution_in_all_labels(self):
        self.assertIn(LABEL_CAUTION, ALL_HF_LABELS)


# ===========================================================================
# 14. Edge-case integration scenarios
# ===========================================================================
class TestEdgeCaseScenarios(unittest.TestCase):

    def test_zero_collateral_zero_hf(self):
        r = analyze(
            _std_data(collateral_usd=0.0, total_debt_usd=10_000.0),
            config=_cfg(),
        )
        self.assertAlmostEqual(r["current_health_factor"], 0.0)
        self.assertEqual(r["health_factor_label"], LABEL_LIQUIDATED)

    def test_zero_rate_debt_unchanged(self):
        r = analyze(
            _std_data(debt_interest_rate_annual_pct=0.0),
            config=_cfg(),
        )
        self.assertAlmostEqual(r["debt_with_interest_usd"], 60_000.0)

    def test_scenario_50pct_drop_usually_liquidated(self):
        r = analyze(_std_data(), config=_cfg())
        drop_50 = [s for s in r["scenario_results"] if s["price_drop_pct"] == 50.0]
        self.assertEqual(len(drop_50), 1)
        self.assertTrue(drop_50[0]["is_liquidated"])

    def test_very_high_collateral_fortress(self):
        r = analyze(
            _std_data(collateral_usd=10_000_000.0, total_debt_usd=100_000.0),
            config=_cfg(),
        )
        self.assertEqual(r["health_factor_label"], LABEL_FORTRESS)

    def test_string_numeric_inputs(self):
        d = {k: str(v) if isinstance(v, (int, float)) else v for k, v in _std_data().items()}
        d["scenario_price_drop_pcts"] = [10.0, 20.0]
        r = analyze(d, config=_cfg())
        self.assertIsInstance(r["current_health_factor"], float)

    def test_days_to_simulate_zero(self):
        r = analyze(_std_data(days_to_simulate=0), config=_cfg())
        self.assertAlmostEqual(r["debt_with_interest_usd"], 60_000.0)

    def test_safe_price_drop_0_when_liquidated(self):
        r = analyze(
            _std_data(collateral_usd=50_000.0, total_debt_usd=60_000.0),
            config=_cfg(),
        )
        self.assertAlmostEqual(r["safe_price_drop_pct"], 0.0)

    def test_all_scenarios_liquidated_at_99pct_drop(self):
        r = analyze(
            _std_data(scenario_price_drop_pcts=[99.0]),
            config=_cfg(),
        )
        self.assertTrue(r["scenario_results"][0]["is_liquidated"])

    def test_ltv_zero_when_no_debt(self):
        r = analyze(_std_data(total_debt_usd=0.0), config=_cfg())
        self.assertAlmostEqual(r["current_ltv_pct"], 0.0)

    def test_health_factor_scales_with_collateral(self):
        r1 = analyze(_std_data(collateral_usd=100_000.0), config=_cfg())
        r2 = analyze(_std_data(collateral_usd=200_000.0), config=_cfg())
        self.assertGreater(r2["current_health_factor"], r1["current_health_factor"])

    def test_non_dict_data_no_crash(self):
        r = analyze("NOT A DICT", config=_cfg())
        self.assertIn("health_factor_label", r)

    def test_large_scenario_list(self):
        drops = list(range(0, 100, 5))
        r = analyze(_std_data(scenario_price_drop_pcts=drops), config=_cfg())
        self.assertEqual(len(r["scenario_results"]), len(drops))


if __name__ == "__main__":
    unittest.main()
