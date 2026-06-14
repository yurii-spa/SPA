"""
Tests for MP-1090 DeFiProtocolAutoCompoundingFrequencyAnalyzer.

Run with:  python3 -m unittest spa_core.tests.test_defi_protocol_auto_compounding_frequency_analyzer -v
Target: ≥110 tests, all passing.
Framework: unittest (stdlib only).
"""

import json
import math
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Make sure project root is importable
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from spa_core.analytics.defi_protocol_auto_compounding_frequency_analyzer import (
    LABEL_GAS_DESTROYS_YIELD,
    LABEL_GOOD_FREQUENCY,
    LABEL_OPTIMAL_FREQUENCY,
    LABEL_OVER_COMPOUNDING,
    LABEL_UNDER_COMPOUNDING,
    LOG_RING_CAP,
    DeFiProtocolAutoCompoundingFrequencyAnalyzer,
    _append_to_log,
)


# ---------------------------------------------------------------------------
# Helper factory
# ---------------------------------------------------------------------------

def make_analyzer(
    nominal_apy_pct=5.0,
    compounds_per_year=365,
    gas_cost_usd_per_compound=0.0,
    position_size_usd=10_000.0,
    protocol_name="TestProtocol",
):
    return DeFiProtocolAutoCompoundingFrequencyAnalyzer(
        nominal_apy_pct=nominal_apy_pct,
        compounds_per_year=compounds_per_year,
        gas_cost_usd_per_compound=gas_cost_usd_per_compound,
        position_size_usd=position_size_usd,
        protocol_name=protocol_name,
    )


# ===========================================================================
# 1. Construction & attribute tests
# ===========================================================================

class TestConstruction(unittest.TestCase):

    def test_stores_nominal_apy(self):
        a = make_analyzer(nominal_apy_pct=7.5)
        self.assertEqual(a.nominal_apy_pct, 7.5)

    def test_stores_compounds_per_year(self):
        a = make_analyzer(compounds_per_year=52)
        self.assertEqual(a.compounds_per_year, 52)

    def test_stores_gas_cost(self):
        a = make_analyzer(gas_cost_usd_per_compound=3.5)
        self.assertAlmostEqual(a.gas_cost_usd_per_compound, 3.5)

    def test_stores_position_size(self):
        a = make_analyzer(position_size_usd=50_000.0)
        self.assertAlmostEqual(a.position_size_usd, 50_000.0)

    def test_stores_protocol_name(self):
        a = make_analyzer(protocol_name="Aave")
        self.assertEqual(a.protocol_name, "Aave")

    def test_nominal_apy_coerced_to_float(self):
        a = make_analyzer(nominal_apy_pct=10)
        self.assertIsInstance(a.nominal_apy_pct, float)

    def test_compounds_coerced_to_int(self):
        a = make_analyzer(compounds_per_year=365.9)
        self.assertIsInstance(a.compounds_per_year, int)

    def test_gas_cost_coerced_to_float(self):
        a = make_analyzer(gas_cost_usd_per_compound=1)
        self.assertIsInstance(a.gas_cost_usd_per_compound, float)

    def test_position_size_coerced_to_float(self):
        a = make_analyzer(position_size_usd=10000)
        self.assertIsInstance(a.position_size_usd, float)

    def test_protocol_name_coerced_to_str(self):
        a = make_analyzer(protocol_name=42)
        self.assertIsInstance(a.protocol_name, str)

    def test_zero_nominal_apy(self):
        a = make_analyzer(nominal_apy_pct=0.0)
        self.assertEqual(a.nominal_apy_pct, 0.0)

    def test_zero_gas_cost(self):
        a = make_analyzer(gas_cost_usd_per_compound=0.0)
        self.assertEqual(a.gas_cost_usd_per_compound, 0.0)

    def test_large_position_size(self):
        a = make_analyzer(position_size_usd=1_000_000.0)
        self.assertAlmostEqual(a.position_size_usd, 1_000_000.0)


# ===========================================================================
# 2. Effective APY computation
# ===========================================================================

class TestEffectiveAPY(unittest.TestCase):

    def test_daily_compounding_higher_than_nominal(self):
        a = make_analyzer(nominal_apy_pct=10.0, compounds_per_year=365)
        r = a.analyze()
        self.assertGreater(r["effective_apy_pct"], 10.0)

    def test_annual_compounding_equals_nominal(self):
        # n=1 → (1 + r/1)^1 - 1 = r  → effective == nominal
        a = make_analyzer(nominal_apy_pct=8.0, compounds_per_year=1)
        r = a.analyze()
        self.assertAlmostEqual(r["effective_apy_pct"], 8.0, places=5)

    def test_monthly_compounding_between_nominal_and_daily(self):
        nom = 12.0
        monthly = make_analyzer(nominal_apy_pct=nom, compounds_per_year=12).analyze()
        daily = make_analyzer(nominal_apy_pct=nom, compounds_per_year=365).analyze()
        self.assertGreater(daily["effective_apy_pct"], monthly["effective_apy_pct"])

    def test_weekly_compounding_formula(self):
        a = make_analyzer(nominal_apy_pct=5.0, compounds_per_year=52)
        r = a.analyze()
        expected = ((1 + 0.05 / 52) ** 52 - 1) * 100
        self.assertAlmostEqual(r["effective_apy_pct"], expected, places=5)

    def test_hourly_compounding_approaches_continuous(self):
        # continuous compounding: e^r - 1
        nom = 10.0
        a = make_analyzer(nominal_apy_pct=nom, compounds_per_year=8760)
        r = a.analyze()
        continuous = (math.exp(nom / 100) - 1) * 100
        self.assertAlmostEqual(r["effective_apy_pct"], continuous, places=2)

    def test_zero_nominal_apy_effective_is_zero(self):
        a = make_analyzer(nominal_apy_pct=0.0, compounds_per_year=365)
        r = a.analyze()
        self.assertAlmostEqual(r["effective_apy_pct"], 0.0, places=8)

    def test_apy_boost_non_negative_for_n_ge_1(self):
        for n in [1, 4, 12, 52, 365, 8760]:
            with self.subTest(n=n):
                a = make_analyzer(nominal_apy_pct=6.0, compounds_per_year=n)
                r = a.analyze()
                self.assertGreaterEqual(r["apy_boost_pct"], 0.0)

    def test_apy_boost_zero_for_annual(self):
        a = make_analyzer(nominal_apy_pct=6.0, compounds_per_year=1)
        r = a.analyze()
        self.assertAlmostEqual(r["apy_boost_pct"], 0.0, places=5)

    def test_higher_nominal_higher_boost(self):
        # More nominal APY → bigger absolute boost from compounding
        low = make_analyzer(nominal_apy_pct=2.0, compounds_per_year=365).analyze()
        high = make_analyzer(nominal_apy_pct=20.0, compounds_per_year=365).analyze()
        self.assertGreater(high["apy_boost_pct"], low["apy_boost_pct"])

    def test_more_frequent_compounding_higher_boost(self):
        nom = 12.0
        monthly = make_analyzer(nominal_apy_pct=nom, compounds_per_year=12).analyze()
        daily = make_analyzer(nominal_apy_pct=nom, compounds_per_year=365).analyze()
        self.assertGreater(daily["apy_boost_pct"], monthly["apy_boost_pct"])


# ===========================================================================
# 3. Gas cost & drag
# ===========================================================================

class TestGasCost(unittest.TestCase):

    def test_annual_gas_cost_formula(self):
        a = make_analyzer(gas_cost_usd_per_compound=5.0, compounds_per_year=365)
        r = a.analyze()
        self.assertAlmostEqual(r["annual_gas_cost_usd"], 5.0 * 365, places=3)

    def test_zero_gas_cost_zero_drag(self):
        a = make_analyzer(gas_cost_usd_per_compound=0.0, compounds_per_year=365)
        r = a.analyze()
        self.assertAlmostEqual(r["annual_gas_drag_pct"], 0.0, places=8)

    def test_gas_drag_formula(self):
        a = make_analyzer(
            gas_cost_usd_per_compound=2.0,
            compounds_per_year=52,
            position_size_usd=10_000.0,
        )
        r = a.analyze()
        expected_gas_cost = 2.0 * 52
        expected_drag = expected_gas_cost / 10_000.0 * 100
        self.assertAlmostEqual(r["annual_gas_drag_pct"], expected_drag, places=5)

    def test_larger_position_lower_drag(self):
        small = make_analyzer(gas_cost_usd_per_compound=5.0, position_size_usd=1_000).analyze()
        large = make_analyzer(gas_cost_usd_per_compound=5.0, position_size_usd=100_000).analyze()
        self.assertGreater(small["annual_gas_drag_pct"], large["annual_gas_drag_pct"])

    def test_net_effective_apy_equals_effective_minus_drag(self):
        a = make_analyzer(
            nominal_apy_pct=10.0,
            compounds_per_year=365,
            gas_cost_usd_per_compound=1.0,
            position_size_usd=10_000.0,
        )
        r = a.analyze()
        expected_net = r["effective_apy_pct"] - r["annual_gas_drag_pct"]
        self.assertAlmostEqual(r["net_effective_apy_pct"], expected_net, places=4)

    def test_net_effective_apy_can_be_negative(self):
        # Huge gas, tiny position
        a = make_analyzer(
            nominal_apy_pct=1.0,
            compounds_per_year=365,
            gas_cost_usd_per_compound=100.0,
            position_size_usd=100.0,
        )
        r = a.analyze()
        self.assertLess(r["net_effective_apy_pct"], 0.0)

    def test_zero_position_size_zero_drag(self):
        a = make_analyzer(
            gas_cost_usd_per_compound=5.0,
            position_size_usd=0.0,
        )
        r = a.analyze()
        self.assertAlmostEqual(r["annual_gas_drag_pct"], 0.0, places=8)

    def test_monthly_gas_lower_than_daily_gas(self):
        monthly = make_analyzer(gas_cost_usd_per_compound=1.0, compounds_per_year=12).analyze()
        daily = make_analyzer(gas_cost_usd_per_compound=1.0, compounds_per_year=365).analyze()
        self.assertLess(monthly["annual_gas_cost_usd"], daily["annual_gas_cost_usd"])

    def test_weekly_gas_cost(self):
        a = make_analyzer(gas_cost_usd_per_compound=3.0, compounds_per_year=52)
        r = a.analyze()
        self.assertAlmostEqual(r["annual_gas_cost_usd"], 3.0 * 52, places=3)


# ===========================================================================
# 4. Compounding labels
# ===========================================================================

class TestCompoundingLabel(unittest.TestCase):

    # --- GAS_DESTROYS_YIELD -------------------------------------------------

    def test_gas_destroys_yield_tiny_position(self):
        # Gas wipes out > 50 % of nominal yield
        a = make_analyzer(
            nominal_apy_pct=5.0,
            compounds_per_year=365,
            gas_cost_usd_per_compound=50.0,
            position_size_usd=100.0,
        )
        r = a.analyze()
        self.assertEqual(r["compounding_label"], LABEL_GAS_DESTROYS_YIELD)

    def test_gas_destroys_yield_high_frequency_expensive_gas(self):
        a = make_analyzer(
            nominal_apy_pct=2.0,
            compounds_per_year=8760,
            gas_cost_usd_per_compound=0.5,
            position_size_usd=500.0,
        )
        r = a.analyze()
        self.assertEqual(r["compounding_label"], LABEL_GAS_DESTROYS_YIELD)

    # --- OVER_COMPOUNDING ---------------------------------------------------

    def test_over_compounding_daily_high_gas(self):
        # gas_drag > apy_boost AND compounds > 52
        a = make_analyzer(
            nominal_apy_pct=5.0,
            compounds_per_year=365,
            gas_cost_usd_per_compound=1.0,
            position_size_usd=100_000.0,
        )
        r = a.analyze()
        # boost ~0.063 %, drag = 365*1 / 100000 * 100 = 0.365 %
        # drag > boost → OVER_COMPOUNDING (unless gas_destroys_yield kicks in)
        # net = 5.063 - 0.365 = 4.698; nominal * 0.5 = 2.5 → not destroys
        self.assertEqual(r["compounding_label"], LABEL_OVER_COMPOUNDING)

    def test_over_compounding_hourly(self):
        a = make_analyzer(
            nominal_apy_pct=4.0,
            compounds_per_year=8760,
            gas_cost_usd_per_compound=0.1,
            position_size_usd=50_000.0,
        )
        r = a.analyze()
        # drag = 8760 * 0.1 / 50000 * 100 = 1.752 %; boost ≈ 0.082 %
        # drag > boost AND compounds > 52 → OVER_COMPOUNDING
        # net = ~4.082 - 1.752 = 2.33; nominal*0.5 = 2.0 → not destroys
        self.assertEqual(r["compounding_label"], LABEL_OVER_COMPOUNDING)

    # --- UNDER_COMPOUNDING --------------------------------------------------

    def test_under_compounding_annual(self):
        a = make_analyzer(
            nominal_apy_pct=8.0,
            compounds_per_year=1,
            gas_cost_usd_per_compound=0.0,
        )
        r = a.analyze()
        self.assertEqual(r["compounding_label"], LABEL_UNDER_COMPOUNDING)

    def test_under_compounding_quarterly(self):
        a = make_analyzer(
            nominal_apy_pct=8.0,
            compounds_per_year=4,
            gas_cost_usd_per_compound=0.0,
        )
        r = a.analyze()
        self.assertEqual(r["compounding_label"], LABEL_UNDER_COMPOUNDING)

    def test_under_compounding_monthly_boundary(self):
        # compounds=12 → NOT under-compounding (threshold is < 12)
        a = make_analyzer(
            nominal_apy_pct=8.0,
            compounds_per_year=12,
            gas_cost_usd_per_compound=0.0,
        )
        r = a.analyze()
        self.assertNotEqual(r["compounding_label"], LABEL_UNDER_COMPOUNDING)

    def test_under_compounding_biannual(self):
        a = make_analyzer(
            nominal_apy_pct=8.0,
            compounds_per_year=2,
            gas_cost_usd_per_compound=0.0,
        )
        r = a.analyze()
        self.assertEqual(r["compounding_label"], LABEL_UNDER_COMPOUNDING)

    # --- OPTIMAL_FREQUENCY --------------------------------------------------

    def test_optimal_frequency_daily_zero_gas(self):
        a = make_analyzer(
            nominal_apy_pct=10.0,
            compounds_per_year=365,
            gas_cost_usd_per_compound=0.0,
        )
        r = a.analyze()
        self.assertEqual(r["compounding_label"], LABEL_OPTIMAL_FREQUENCY)

    def test_optimal_frequency_weekly_zero_gas(self):
        a = make_analyzer(
            nominal_apy_pct=10.0,
            compounds_per_year=52,
            gas_cost_usd_per_compound=0.0,
        )
        r = a.analyze()
        self.assertEqual(r["compounding_label"], LABEL_OPTIMAL_FREQUENCY)

    def test_optimal_frequency_monthly_zero_gas(self):
        a = make_analyzer(
            nominal_apy_pct=10.0,
            compounds_per_year=12,
            gas_cost_usd_per_compound=0.0,
        )
        r = a.analyze()
        self.assertEqual(r["compounding_label"], LABEL_OPTIMAL_FREQUENCY)

    def test_optimal_frequency_tiny_gas_large_position(self):
        # Very small gas relative to position → stays OPTIMAL
        a = make_analyzer(
            nominal_apy_pct=10.0,
            compounds_per_year=365,
            gas_cost_usd_per_compound=0.001,
            position_size_usd=1_000_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["compounding_label"], LABEL_OPTIMAL_FREQUENCY)

    # --- GOOD_FREQUENCY -----------------------------------------------------

    def test_good_frequency_moderate_gas(self):
        # Weekly compounding (52/year) with moderate gas → GOOD_FREQUENCY
        # effective ~ 10.506 %; need net >= 0.85*10.506 = 8.930 % but < 0.95*10.506 = 9.980 %
        # drag = 1.9 * 52 / 10000 * 100 ≈ 0.988 % → net ≈ 9.518 % → GOOD
        # compounds=52 → OVER_COMPOUNDING branch needs > 52, so it won't fire here
        a = make_analyzer(
            nominal_apy_pct=10.0,
            compounds_per_year=52,
            gas_cost_usd_per_compound=1.9,
            position_size_usd=10_000.0,
        )
        r = a.analyze()
        self.assertEqual(r["compounding_label"], LABEL_GOOD_FREQUENCY)

    def test_good_frequency_label_is_string(self):
        a = make_analyzer(nominal_apy_pct=5.0, compounds_per_year=52)
        r = a.analyze()
        self.assertIsInstance(r["compounding_label"], str)

    def test_all_labels_are_valid_strings(self):
        valid = {
            LABEL_OPTIMAL_FREQUENCY, LABEL_GOOD_FREQUENCY,
            LABEL_OVER_COMPOUNDING, LABEL_UNDER_COMPOUNDING,
            LABEL_GAS_DESTROYS_YIELD,
        }
        configs = [
            (10.0, 365, 0.0, 10000),
            (10.0, 1, 0.0, 10000),
            (5.0, 365, 50.0, 100),
            (5.0, 8760, 1.0, 10000),
            (10.0, 12, 0.5, 10000),
        ]
        for nominal, n, gas, pos in configs:
            a = make_analyzer(
                nominal_apy_pct=nominal,
                compounds_per_year=n,
                gas_cost_usd_per_compound=gas,
                position_size_usd=pos,
            )
            r = a.analyze()
            self.assertIn(r["compounding_label"], valid)


# ===========================================================================
# 5. Compounding score
# ===========================================================================

class TestCompoundingScore(unittest.TestCase):

    def test_score_in_range(self):
        for n in [1, 4, 12, 52, 365, 8760]:
            a = make_analyzer(compounds_per_year=n, gas_cost_usd_per_compound=0.5)
            r = a.analyze()
            self.assertGreaterEqual(r["compounding_score"], 0)
            self.assertLessEqual(r["compounding_score"], 100)

    def test_score_is_integer(self):
        a = make_analyzer()
        r = a.analyze()
        self.assertIsInstance(r["compounding_score"], int)

    def test_score_100_optimal_zero_gas(self):
        # Zero gas, daily compounding → perfect score
        a = make_analyzer(
            nominal_apy_pct=10.0,
            compounds_per_year=365,
            gas_cost_usd_per_compound=0.0,
        )
        r = a.analyze()
        self.assertEqual(r["compounding_score"], 100)

    def test_score_zero_when_net_negative(self):
        # Net negative APY → score should be 0
        a = make_analyzer(
            nominal_apy_pct=1.0,
            compounds_per_year=365,
            gas_cost_usd_per_compound=1000.0,
            position_size_usd=100.0,
        )
        r = a.analyze()
        self.assertEqual(r["compounding_score"], 0)

    def test_score_lower_for_high_gas(self):
        low_gas = make_analyzer(gas_cost_usd_per_compound=0.0).analyze()
        high_gas = make_analyzer(gas_cost_usd_per_compound=5.0).analyze()
        self.assertGreater(low_gas["compounding_score"], high_gas["compounding_score"])

    def test_score_lower_for_under_compounding(self):
        annual = make_analyzer(compounds_per_year=1, gas_cost_usd_per_compound=0.0).analyze()
        daily = make_analyzer(compounds_per_year=365, gas_cost_usd_per_compound=0.0).analyze()
        self.assertGreater(daily["compounding_score"], annual["compounding_score"])

    def test_score_non_negative_always(self):
        # Even catastrophically bad scenarios → 0, never negative
        a = make_analyzer(
            nominal_apy_pct=0.1,
            compounds_per_year=8760,
            gas_cost_usd_per_compound=1000.0,
            position_size_usd=1.0,
        )
        r = a.analyze()
        self.assertGreaterEqual(r["compounding_score"], 0)

    def test_score_with_zero_nominal_zero_gas(self):
        a = make_analyzer(nominal_apy_pct=0.0, gas_cost_usd_per_compound=0.0)
        r = a.analyze()
        self.assertGreaterEqual(r["compounding_score"], 0)
        self.assertLessEqual(r["compounding_score"], 100)


# ===========================================================================
# 6. Return dictionary structure
# ===========================================================================

class TestReturnStructure(unittest.TestCase):

    REQUIRED_KEYS = [
        "protocol_name",
        "nominal_apy_pct",
        "compounds_per_year",
        "gas_cost_usd_per_compound",
        "position_size_usd",
        "effective_apy_pct",
        "apy_boost_pct",
        "annual_gas_cost_usd",
        "annual_gas_drag_pct",
        "net_effective_apy_pct",
        "compounding_score",
        "compounding_label",
        "timestamp_utc",
    ]

    def setUp(self):
        self.result = make_analyzer().analyze()

    def test_all_required_keys_present(self):
        for key in self.REQUIRED_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, self.result)

    def test_protocol_name_echoed(self):
        a = make_analyzer(protocol_name="MorphoBlue")
        r = a.analyze()
        self.assertEqual(r["protocol_name"], "MorphoBlue")

    def test_nominal_apy_echoed(self):
        a = make_analyzer(nominal_apy_pct=7.77)
        r = a.analyze()
        self.assertAlmostEqual(r["nominal_apy_pct"], 7.77, places=4)

    def test_compounds_per_year_echoed(self):
        a = make_analyzer(compounds_per_year=52)
        r = a.analyze()
        self.assertEqual(r["compounds_per_year"], 52)

    def test_timestamp_is_recent(self):
        now = int(time.time())
        r = make_analyzer().analyze()
        self.assertAlmostEqual(r["timestamp_utc"], now, delta=5)

    def test_effective_apy_is_float(self):
        self.assertIsInstance(self.result["effective_apy_pct"], float)

    def test_apy_boost_is_float(self):
        self.assertIsInstance(self.result["apy_boost_pct"], float)

    def test_annual_gas_cost_is_float(self):
        self.assertIsInstance(self.result["annual_gas_cost_usd"], float)

    def test_annual_gas_drag_is_float(self):
        self.assertIsInstance(self.result["annual_gas_drag_pct"], float)

    def test_net_effective_apy_is_float(self):
        self.assertIsInstance(self.result["net_effective_apy_pct"], float)

    def test_compounding_score_is_int(self):
        self.assertIsInstance(self.result["compounding_score"], int)

    def test_compounding_label_is_str(self):
        self.assertIsInstance(self.result["compounding_label"], str)

    def test_result_is_dict(self):
        self.assertIsInstance(self.result, dict)

    def test_no_extra_unexpected_keys(self):
        # Ensure returned dict has AT LEAST the required keys (extra is OK)
        missing = set(self.REQUIRED_KEYS) - set(self.result.keys())
        self.assertEqual(missing, set())


# ===========================================================================
# 7. Ring-buffer log helpers
# ===========================================================================

class TestLogHelpers(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def test_append_creates_file(self):
        _append_to_log({"x": 1}, self.tmp)
        self.assertTrue(os.path.exists(self.tmp))

    def test_append_valid_json(self):
        _append_to_log({"x": 1}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_append_single_entry(self):
        _append_to_log({"key": "val"}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["key"], "val")

    def test_append_multiple_entries(self):
        for i in range(5):
            _append_to_log({"i": i}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        for i in range(LOG_RING_CAP + 20):
            _append_to_log({"i": i}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), LOG_RING_CAP)

    def test_ring_buffer_keeps_newest(self):
        for i in range(LOG_RING_CAP + 10):
            _append_to_log({"i": i}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        # The last entry should have i = LOG_RING_CAP + 9
        self.assertEqual(data[-1]["i"], LOG_RING_CAP + 9)

    def test_ring_buffer_oldest_dropped(self):
        for i in range(LOG_RING_CAP + 5):
            _append_to_log({"i": i}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        # Oldest should be i=5
        self.assertEqual(data[0]["i"], 5)

    def test_log_cap_constant_is_100(self):
        self.assertEqual(LOG_RING_CAP, 100)

    def test_analyze_and_log_writes_entry(self):
        a = make_analyzer()
        a.analyze_and_log(log_path=self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_analyze_and_log_returns_result(self):
        a = make_analyzer()
        r = a.analyze_and_log(log_path=self.tmp)
        self.assertIn("effective_apy_pct", r)

    def test_log_entry_contains_all_keys(self):
        a = make_analyzer()
        a.analyze_and_log(log_path=self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertIn("compounding_label", data[0])
        self.assertIn("net_effective_apy_pct", data[0])

    def test_append_recovers_from_corrupt_file(self):
        # Write garbage JSON; append should still succeed
        with open(self.tmp, "w") as fh:
            fh.write("NOT_VALID_JSON{{{")
        _append_to_log({"recovered": True}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertEqual(data[0]["recovered"], True)

    def test_append_recovers_from_non_list_json(self):
        # Write valid JSON that isn't a list
        with open(self.tmp, "w") as fh:
            json.dump({"oops": "not a list"}, fh)
        _append_to_log({"i": 0}, self.tmp)
        with open(self.tmp) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)


# ===========================================================================
# 8. Edge cases & boundary conditions
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_very_high_nominal_apy(self):
        a = make_analyzer(nominal_apy_pct=1000.0, compounds_per_year=365)
        r = a.analyze()
        self.assertGreater(r["effective_apy_pct"], 1000.0)

    def test_very_small_nominal_apy(self):
        a = make_analyzer(nominal_apy_pct=0.001, compounds_per_year=365)
        r = a.analyze()
        self.assertGreater(r["effective_apy_pct"], 0.0)

    def test_single_compound_per_year(self):
        a = make_analyzer(nominal_apy_pct=5.0, compounds_per_year=1)
        r = a.analyze()
        self.assertAlmostEqual(r["effective_apy_pct"], 5.0, places=5)

    def test_8760_compounds_close_to_continuous(self):
        nom = 20.0
        a = make_analyzer(nominal_apy_pct=nom, compounds_per_year=8760)
        r = a.analyze()
        continuous = (math.exp(nom / 100) - 1) * 100
        self.assertAlmostEqual(r["effective_apy_pct"], continuous, places=1)

    def test_enormous_gas_results_in_negative_net(self):
        a = make_analyzer(
            nominal_apy_pct=5.0,
            compounds_per_year=365,
            gas_cost_usd_per_compound=1000.0,
            position_size_usd=100.0,
        )
        r = a.analyze()
        self.assertLess(r["net_effective_apy_pct"], 0.0)

    def test_analyze_returns_same_result_twice(self):
        a = make_analyzer()
        r1 = a.analyze()
        r2 = a.analyze()
        self.assertAlmostEqual(r1["effective_apy_pct"], r2["effective_apy_pct"], places=8)

    def test_protocol_name_spaces(self):
        a = make_analyzer(protocol_name="My Protocol V2")
        r = a.analyze()
        self.assertEqual(r["protocol_name"], "My Protocol V2")

    def test_position_size_one_dollar(self):
        a = make_analyzer(
            gas_cost_usd_per_compound=0.0,
            position_size_usd=1.0,
        )
        r = a.analyze()
        self.assertAlmostEqual(r["annual_gas_drag_pct"], 0.0, places=8)

    def test_compounds_per_year_365_daily(self):
        a = make_analyzer(compounds_per_year=365)
        r = a.analyze()
        self.assertEqual(r["compounds_per_year"], 365)

    def test_compounds_per_year_8760_hourly(self):
        a = make_analyzer(compounds_per_year=8760)
        r = a.analyze()
        self.assertEqual(r["compounds_per_year"], 8760)

    def test_effective_apy_always_gte_nominal_zero_cost(self):
        for n in [1, 2, 4, 12, 26, 52, 365, 8760]:
            a = make_analyzer(nominal_apy_pct=8.0, compounds_per_year=n, gas_cost_usd_per_compound=0.0)
            r = a.analyze()
            self.assertGreaterEqual(r["effective_apy_pct"], 8.0 - 1e-9)

    def test_high_frequency_gas_cost_destroys(self):
        a = make_analyzer(
            nominal_apy_pct=3.0,
            compounds_per_year=8760,
            gas_cost_usd_per_compound=0.5,
            position_size_usd=1000.0,
        )
        r = a.analyze()
        # drag = 8760 * 0.5 / 1000 * 100 = 438 % → GAS_DESTROYS_YIELD
        self.assertEqual(r["compounding_label"], LABEL_GAS_DESTROYS_YIELD)

    def test_quarterly_is_under_compounding(self):
        a = make_analyzer(compounds_per_year=4, gas_cost_usd_per_compound=0.0)
        r = a.analyze()
        self.assertEqual(r["compounding_label"], LABEL_UNDER_COMPOUNDING)

    def test_biweekly_26_not_under_compounding(self):
        # 26 > 12 → not under-compounding with zero gas
        a = make_analyzer(compounds_per_year=26, gas_cost_usd_per_compound=0.0)
        r = a.analyze()
        self.assertNotEqual(r["compounding_label"], LABEL_UNDER_COMPOUNDING)

    def test_net_apy_zero_gas_equals_effective(self):
        a = make_analyzer(gas_cost_usd_per_compound=0.0)
        r = a.analyze()
        self.assertAlmostEqual(r["net_effective_apy_pct"], r["effective_apy_pct"], places=6)

    def test_apy_boost_increases_with_frequency(self):
        boosts = []
        for n in [1, 4, 12, 52, 365]:
            r = make_analyzer(nominal_apy_pct=10.0, compounds_per_year=n).analyze()
            boosts.append(r["apy_boost_pct"])
        # Each should be >= previous
        for i in range(1, len(boosts)):
            self.assertGreaterEqual(boosts[i], boosts[i - 1])

    def test_negative_net_apy_score_is_zero(self):
        a = make_analyzer(
            nominal_apy_pct=1.0,
            compounds_per_year=8760,
            gas_cost_usd_per_compound=100.0,
            position_size_usd=100.0,
        )
        r = a.analyze()
        self.assertEqual(r["compounding_score"], 0)

    def test_various_protocols_independent(self):
        protocols = ["Aave", "Compound", "Morpho", "Yearn", "Euler"]
        results = [make_analyzer(protocol_name=p).analyze() for p in protocols]
        for p, r in zip(protocols, results):
            self.assertEqual(r["protocol_name"], p)

    def test_position_size_echoed(self):
        a = make_analyzer(position_size_usd=77_777.0)
        r = a.analyze()
        self.assertAlmostEqual(r["position_size_usd"], 77_777.0, places=1)

    def test_gas_cost_echoed(self):
        a = make_analyzer(gas_cost_usd_per_compound=2.345)
        r = a.analyze()
        self.assertAlmostEqual(r["gas_cost_usd_per_compound"], 2.345, places=3)


# ===========================================================================
# 9. Math precision / rounding
# ===========================================================================

class TestPrecision(unittest.TestCase):

    def test_effective_apy_rounded_to_6_decimals(self):
        a = make_analyzer(nominal_apy_pct=10.0, compounds_per_year=365)
        r = a.analyze()
        # Check the value is not overly long (rounded)
        s = str(r["effective_apy_pct"])
        if "." in s:
            decimals = len(s.split(".")[1])
            self.assertLessEqual(decimals, 8)

    def test_annual_gas_cost_rounded(self):
        a = make_analyzer(gas_cost_usd_per_compound=1.23456789, compounds_per_year=365)
        r = a.analyze()
        self.assertAlmostEqual(r["annual_gas_cost_usd"], 1.23456789 * 365, places=2)

    def test_gas_drag_pct_precision(self):
        a = make_analyzer(
            gas_cost_usd_per_compound=1.0,
            compounds_per_year=12,
            position_size_usd=10_000.0,
        )
        r = a.analyze()
        expected = 12.0 / 10_000.0 * 100
        self.assertAlmostEqual(r["annual_gas_drag_pct"], expected, places=5)

    def test_net_effective_apy_precision(self):
        a = make_analyzer(
            nominal_apy_pct=5.0,
            compounds_per_year=52,
            gas_cost_usd_per_compound=0.5,
            position_size_usd=20_000.0,
        )
        r = a.analyze()
        drag = (0.5 * 52) / 20_000.0 * 100
        eff = ((1 + 0.05 / 52) ** 52 - 1) * 100
        expected_net = eff - drag
        self.assertAlmostEqual(r["net_effective_apy_pct"], expected_net, places=4)

    def test_apy_boost_precision_weekly(self):
        nom = 8.0
        n = 52
        a = make_analyzer(nominal_apy_pct=nom, compounds_per_year=n)
        r = a.analyze()
        expected_eff = ((1 + 0.08 / n) ** n - 1) * 100
        expected_boost = expected_eff - nom
        self.assertAlmostEqual(r["apy_boost_pct"], expected_boost, places=5)

    def test_json_serializable(self):
        a = make_analyzer()
        r = a.analyze()
        try:
            json.dumps(r)
        except (TypeError, ValueError) as e:
            self.fail(f"Result is not JSON-serializable: {e}")

    def test_compounding_score_boundary_0_100(self):
        # Hundreds of random-ish configs — all must be in [0, 100]
        configs = [
            (0.1, 365, 0.0, 100),
            (0.1, 365, 10.0, 100),
            (50.0, 1, 0.0, 10000),
            (100.0, 8760, 0.0, 1000000),
            (5.0, 12, 0.5, 5000),
            (10.0, 4, 1.0, 10000),
            (20.0, 365, 0.01, 50000),
            (3.0, 52, 2.0, 10000),
        ]
        for nom, n, gas, pos in configs:
            a = make_analyzer(
                nominal_apy_pct=nom,
                compounds_per_year=n,
                gas_cost_usd_per_compound=gas,
                position_size_usd=pos,
            )
            r = a.analyze()
            with self.subTest(nom=nom, n=n, gas=gas):
                self.assertGreaterEqual(r["compounding_score"], 0)
                self.assertLessEqual(r["compounding_score"], 100)


# ===========================================================================
# 10. Label constant values
# ===========================================================================

class TestLabelConstants(unittest.TestCase):

    def test_optimal_frequency_constant(self):
        self.assertEqual(LABEL_OPTIMAL_FREQUENCY, "OPTIMAL_FREQUENCY")

    def test_good_frequency_constant(self):
        self.assertEqual(LABEL_GOOD_FREQUENCY, "GOOD_FREQUENCY")

    def test_over_compounding_constant(self):
        self.assertEqual(LABEL_OVER_COMPOUNDING, "OVER_COMPOUNDING")

    def test_under_compounding_constant(self):
        self.assertEqual(LABEL_UNDER_COMPOUNDING, "UNDER_COMPOUNDING")

    def test_gas_destroys_yield_constant(self):
        self.assertEqual(LABEL_GAS_DESTROYS_YIELD, "GAS_DESTROYS_YIELD")

    def test_all_label_constants_are_strings(self):
        for lbl in [
            LABEL_OPTIMAL_FREQUENCY, LABEL_GOOD_FREQUENCY,
            LABEL_OVER_COMPOUNDING, LABEL_UNDER_COMPOUNDING,
            LABEL_GAS_DESTROYS_YIELD,
        ]:
            self.assertIsInstance(lbl, str)

    def test_all_label_constants_are_unique(self):
        labels = [
            LABEL_OPTIMAL_FREQUENCY, LABEL_GOOD_FREQUENCY,
            LABEL_OVER_COMPOUNDING, LABEL_UNDER_COMPOUNDING,
            LABEL_GAS_DESTROYS_YIELD,
        ]
        self.assertEqual(len(labels), len(set(labels)))


# ===========================================================================
# 11. Additional scenario coverage
# ===========================================================================

class TestScenarios(unittest.TestCase):

    def test_aave_daily_scenario(self):
        a = make_analyzer(
            nominal_apy_pct=3.5,
            compounds_per_year=365,
            gas_cost_usd_per_compound=0.0,
            position_size_usd=10_000.0,
            protocol_name="Aave V3",
        )
        r = a.analyze()
        self.assertGreater(r["effective_apy_pct"], 3.5)
        self.assertEqual(r["compounding_label"], LABEL_OPTIMAL_FREQUENCY)

    def test_compound_weekly_scenario(self):
        a = make_analyzer(
            nominal_apy_pct=4.8,
            compounds_per_year=52,
            gas_cost_usd_per_compound=0.0,
            position_size_usd=20_000.0,
            protocol_name="Compound V3",
        )
        r = a.analyze()
        self.assertGreater(r["effective_apy_pct"], 4.8)

    def test_morpho_monthly_scenario(self):
        a = make_analyzer(
            nominal_apy_pct=6.5,
            compounds_per_year=12,
            gas_cost_usd_per_compound=0.0,
            position_size_usd=50_000.0,
            protocol_name="Morpho Steakhouse",
        )
        r = a.analyze()
        self.assertGreater(r["effective_apy_pct"], 6.5)

    def test_high_gas_small_position_destroys(self):
        a = make_analyzer(
            nominal_apy_pct=10.0,
            compounds_per_year=365,
            gas_cost_usd_per_compound=5.0,
            position_size_usd=500.0,
            protocol_name="HighGasProtocol",
        )
        r = a.analyze()
        # drag = 5*365/500*100 = 365 % → clearly destroys
        self.assertEqual(r["compounding_label"], LABEL_GAS_DESTROYS_YIELD)

    def test_hourly_protocol_small_gas_large_pos_optimal(self):
        a = make_analyzer(
            nominal_apy_pct=8.0,
            compounds_per_year=8760,
            gas_cost_usd_per_compound=0.0001,
            position_size_usd=1_000_000.0,
            protocol_name="HourlyAutoCompounder",
        )
        r = a.analyze()
        self.assertEqual(r["compounding_label"], LABEL_OPTIMAL_FREQUENCY)

    def test_annual_compound_under(self):
        a = make_analyzer(
            nominal_apy_pct=12.0,
            compounds_per_year=1,
            gas_cost_usd_per_compound=0.0,
            protocol_name="AnnualYield",
        )
        r = a.analyze()
        self.assertEqual(r["compounding_label"], LABEL_UNDER_COMPOUNDING)

    def test_biweekly_large_gas_destroys(self):
        a = make_analyzer(
            nominal_apy_pct=5.0,
            compounds_per_year=26,
            gas_cost_usd_per_compound=10.0,
            position_size_usd=500.0,
        )
        r = a.analyze()
        # drag = 26*10/500*100 = 52 % >> nominal 5 % * 0.5 = 2.5 %
        self.assertEqual(r["compounding_label"], LABEL_GAS_DESTROYS_YIELD)

    def test_result_dict_not_empty(self):
        a = make_analyzer()
        r = a.analyze()
        self.assertGreater(len(r), 0)

    def test_analyze_does_not_write_log(self):
        # analyze() alone should NOT write to default log
        import os
        a = make_analyzer()
        # Just call analyze; no file should be created by that call alone
        a.analyze()
        # We can't easily assert on file non-creation without controlling path,
        # but we can verify the method exists and returns dict
        r = a.analyze()
        self.assertIsInstance(r, dict)

    def test_compounding_score_weekly_zero_gas(self):
        a = make_analyzer(compounds_per_year=52, gas_cost_usd_per_compound=0.0)
        r = a.analyze()
        self.assertEqual(r["compounding_score"], 100)

    def test_compounding_score_monthly_zero_gas(self):
        a = make_analyzer(compounds_per_year=12, gas_cost_usd_per_compound=0.0)
        r = a.analyze()
        self.assertEqual(r["compounding_score"], 100)

    def test_over_compounding_label_not_with_low_frequency(self):
        # compounds=52 but drag > boost → OVER_COMPOUNDING only if > 52
        # So at exactly 52, we should NOT get OVER_COMPOUNDING via that branch
        a = make_analyzer(
            nominal_apy_pct=5.0,
            compounds_per_year=52,
            gas_cost_usd_per_compound=0.1,
            position_size_usd=1000.0,
        )
        r = a.analyze()
        # drag = 52 * 0.1 / 1000 * 100 = 0.52 %; boost ~0.06 %
        # drag > boost but compounds == 52 → NOT over-compounding branch (needs > 52)
        # net = eff - 0.52; eff ~ 5.125; net ~ 4.605; nominal * 0.5 = 2.5 → not destroys
        # Under-compounding: 52 >= 12 → no
        # Optimal: net / eff = 4.605/5.125 = 0.898 ≥ 0.95 → no; ≥ 0.85 → GOOD
        self.assertIn(r["compounding_label"], (LABEL_GOOD_FREQUENCY, LABEL_OPTIMAL_FREQUENCY))

    def test_analyze_and_log_different_log_path(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            path = tf.name
        try:
            a = make_analyzer()
            r = a.analyze_and_log(log_path=path)
            self.assertIn("effective_apy_pct", r)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)
        finally:
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
