"""
Tests for MP-949 DeFiFixedRateDurationAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_fixed_rate_duration_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure the repo root is on the path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.defi_fixed_rate_duration_analyzer import (
    DeFiFixedRateDurationAnalyzer,
    _clamp,
    _grade_from_score,
    _classify,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inst(
    name="PT-stETH",
    price_usd=0.95,
    face_value_usd=1.0,
    days_to_maturity=182.5,
    spot_apy_pct=5.0,
):
    return {
        "name": name,
        "price_usd": price_usd,
        "face_value_usd": face_value_usd,
        "days_to_maturity": days_to_maturity,
        "spot_apy_pct": spot_apy_pct,
    }


NO_LOG = {"write_log": False}


# ===========================================================================
# 1. Instantiation and structure
# ===========================================================================

class TestInstantiation(unittest.TestCase):
    def test_instantiation(self):
        self.assertIsNotNone(DeFiFixedRateDurationAnalyzer())

    def test_analyze_returns_dict(self):
        a = DeFiFixedRateDurationAnalyzer()
        self.assertIsInstance(a.analyze([_inst()], NO_LOG), dict)

    def test_top_level_keys(self):
        a = DeFiFixedRateDurationAnalyzer()
        out = a.analyze([_inst()], NO_LOG)
        for key in ("results", "aggregates", "timestamp"):
            self.assertIn(key, out)

    def test_results_length(self):
        a = DeFiFixedRateDurationAnalyzer()
        out = a.analyze([_inst(), _inst(name="b")], NO_LOG)
        self.assertEqual(len(out["results"]), 2)

    def test_per_instrument_keys(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst()], NO_LOG)["results"][0]
        for key in (
            "name", "price_usd", "face_value_usd", "days_to_maturity",
            "t_years", "spot_apy_pct", "ytm_pct", "macaulay_duration",
            "modified_duration", "convexity", "price_sensitivity_pct_per_1pct",
            "yield_pickup_pct", "classification", "score", "grade", "flags",
        ):
            self.assertIn(key, r)

    def test_symbol_fallback_for_name(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([{"symbol": "fCash", "price_usd": 0.95,
                        "days_to_maturity": 100.0}], NO_LOG)
        self.assertEqual(r["results"][0]["name"], "fCash")

    def test_unknown_name(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([{"price_usd": 0.95, "days_to_maturity": 100.0}], NO_LOG)
        self.assertEqual(r["results"][0]["name"], "unknown")

    def test_timestamp_float(self):
        a = DeFiFixedRateDurationAnalyzer()
        self.assertIsInstance(a.analyze([_inst()], NO_LOG)["timestamp"], float)


# ===========================================================================
# 2. _clamp helper
# ===========================================================================

class TestClamp(unittest.TestCase):
    def test_within(self):
        self.assertEqual(_clamp(50.0, 0.0, 100.0), 50.0)

    def test_below(self):
        self.assertEqual(_clamp(-10.0, 0.0, 100.0), 0.0)

    def test_above(self):
        self.assertEqual(_clamp(150.0, 0.0, 100.0), 100.0)

    def test_low_boundary(self):
        self.assertEqual(_clamp(0.0, 0.0, 100.0), 0.0)

    def test_high_boundary(self):
        self.assertEqual(_clamp(100.0, 0.0, 100.0), 100.0)


# ===========================================================================
# 3. Grade & classification helpers
# ===========================================================================

class TestGrade(unittest.TestCase):
    def test_a(self):
        self.assertEqual(_grade_from_score(90.0), "A")

    def test_a_boundary(self):
        self.assertEqual(_grade_from_score(85.0), "A")

    def test_b_boundary(self):
        self.assertEqual(_grade_from_score(70.0), "B")

    def test_c_boundary(self):
        self.assertEqual(_grade_from_score(55.0), "C")

    def test_d_boundary(self):
        self.assertEqual(_grade_from_score(40.0), "D")

    def test_f(self):
        self.assertEqual(_grade_from_score(30.0), "F")


class TestClassify(unittest.TestCase):
    def test_short(self):
        self.assertEqual(_classify(15.0), "SHORT")

    def test_short_boundary(self):
        self.assertEqual(_classify(30.0), "SHORT")

    def test_medium(self):
        self.assertEqual(_classify(90.0), "MEDIUM")

    def test_medium_boundary(self):
        self.assertEqual(_classify(180.0), "MEDIUM")

    def test_long(self):
        self.assertEqual(_classify(300.0), "LONG")

    def test_long_boundary(self):
        self.assertEqual(_classify(365.0), "LONG")

    def test_very_long(self):
        self.assertEqual(_classify(400.0), "VERY_LONG")


# ===========================================================================
# 4. YTM & duration math
# ===========================================================================

class TestDurationMath(unittest.TestCase):
    def test_ytm_positive_for_discount(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(price_usd=0.95, face_value_usd=1.0,
                             days_to_maturity=365.0)], NO_LOG)["results"][0]
        self.assertGreater(r["ytm_pct"], 0.0)

    def test_ytm_formula_one_year(self):
        # 1 year: ytm = (1/0.95 - 1)*100
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(price_usd=0.95, face_value_usd=1.0,
                             days_to_maturity=365.0)], NO_LOG)["results"][0]
        expected = (1.0 / 0.95 - 1.0) * 100.0
        self.assertAlmostEqual(r["ytm_pct"], round(expected, 6), places=4)

    def test_macaulay_equals_t_years(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(days_to_maturity=365.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["macaulay_duration"], 1.0, places=6)

    def test_macaulay_half_year(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(days_to_maturity=182.5)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["macaulay_duration"], 0.5, places=6)

    def test_modified_less_than_macaulay(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(price_usd=0.9, days_to_maturity=365.0)], NO_LOG)["results"][0]
        self.assertLess(r["modified_duration"], r["macaulay_duration"])

    def test_modified_duration_formula(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(price_usd=0.95, face_value_usd=1.0,
                             days_to_maturity=365.0)], NO_LOG)["results"][0]
        ytm_dec = r["ytm_pct"] / 100.0
        expected = round(r["macaulay_duration"] / (1.0 + ytm_dec), 6)
        self.assertAlmostEqual(r["modified_duration"], expected, places=6)

    def test_convexity_positive(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(days_to_maturity=365.0)], NO_LOG)["results"][0]
        self.assertGreater(r["convexity"], 0.0)

    def test_convexity_formula(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(price_usd=0.95, days_to_maturity=365.0)], NO_LOG)["results"][0]
        t = r["t_years"]
        ytm_dec = r["ytm_pct"] / 100.0
        expected = round(t * (t + 1.0) / (1.0 + ytm_dec) ** 2, 6)
        self.assertAlmostEqual(r["convexity"], expected, places=5)

    def test_price_sensitivity_is_neg_modified(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst()], NO_LOG)["results"][0]
        self.assertAlmostEqual(
            r["price_sensitivity_pct_per_1pct"], -r["modified_duration"], places=6
        )

    def test_yield_pickup_formula(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(price_usd=0.9, days_to_maturity=365.0,
                             spot_apy_pct=4.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["yield_pickup_pct"], round(r["ytm_pct"] - 4.0, 6))

    def test_t_years_value(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(days_to_maturity=730.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["t_years"], 2.0, places=6)


# ===========================================================================
# 5. Classification (by maturity)
# ===========================================================================

class TestClassificationLevels(unittest.TestCase):
    def test_short(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(days_to_maturity=20.0)], NO_LOG)["results"][0]
        self.assertEqual(r["classification"], "SHORT")

    def test_medium(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(days_to_maturity=120.0)], NO_LOG)["results"][0]
        self.assertEqual(r["classification"], "MEDIUM")

    def test_long(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(days_to_maturity=300.0)], NO_LOG)["results"][0]
        self.assertEqual(r["classification"], "LONG")

    def test_very_long(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(days_to_maturity=500.0)], NO_LOG)["results"][0]
        self.assertEqual(r["classification"], "VERY_LONG")


# ===========================================================================
# 6. Score & grade
# ===========================================================================

class TestScore(unittest.TestCase):
    def test_score_clamped(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(price_usd=0.5, days_to_maturity=30.0,
                             spot_apy_pct=0.0)], NO_LOG)["results"][0]
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_grade_assigned(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst()], NO_LOG)["results"][0]
        self.assertIn(r["grade"], ("A", "B", "C", "D", "F"))

    def test_positive_pickup_scores_higher(self):
        a = DeFiFixedRateDurationAnalyzer()
        good = a.analyze([_inst(price_usd=0.9, days_to_maturity=90.0,
                                spot_apy_pct=1.0)], NO_LOG)["results"][0]
        worse = a.analyze([_inst(price_usd=0.99, days_to_maturity=90.0,
                                 spot_apy_pct=20.0)], NO_LOG)["results"][0]
        self.assertGreater(good["score"], worse["score"])

    def test_long_duration_penalized(self):
        a = DeFiFixedRateDurationAnalyzer()
        short = a.analyze([_inst(price_usd=0.95, days_to_maturity=30.0,
                                 spot_apy_pct=0.0)], NO_LOG)["results"][0]
        long = a.analyze([_inst(price_usd=0.95, days_to_maturity=700.0,
                                spot_apy_pct=0.0)], NO_LOG)["results"][0]
        self.assertGreater(short["score"], long["score"])


# ===========================================================================
# 7. Flags
# ===========================================================================

class TestFlags(unittest.TestCase):
    def test_insufficient_data_zero_price(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(price_usd=0.0)], NO_LOG)["results"][0]
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_data_zero_face(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(face_value_usd=0.0)], NO_LOG)["results"][0]
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_data_zero_days(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(days_to_maturity=0.0)], NO_LOG)["results"][0]
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_data_only_flag(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(price_usd=0.0, days_to_maturity=0.0)], NO_LOG)["results"][0]
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_discount_to_face_flag(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(price_usd=0.95, face_value_usd=1.0)], NO_LOG)["results"][0]
        self.assertIn("DISCOUNT_TO_FACE", r["flags"])

    def test_premium_to_face_flag(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(price_usd=1.05, face_value_usd=1.0,
                             days_to_maturity=90.0)], NO_LOG)["results"][0]
        self.assertIn("PREMIUM_TO_FACE", r["flags"])

    def test_high_duration_risk_flag(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(days_to_maturity=500.0)], NO_LOG)["results"][0]
        self.assertIn("HIGH_DURATION_RISK", r["flags"])

    def test_no_high_duration_risk_short(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(days_to_maturity=90.0)], NO_LOG)["results"][0]
        self.assertNotIn("HIGH_DURATION_RISK", r["flags"])

    def test_negative_yield_pickup_flag(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(price_usd=0.99, days_to_maturity=180.0,
                             spot_apy_pct=20.0)], NO_LOG)["results"][0]
        self.assertIn("NEGATIVE_YIELD_PICKUP", r["flags"])

    def test_deep_discount_flag(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(price_usd=0.85, face_value_usd=1.0,
                             days_to_maturity=180.0)], NO_LOG)["results"][0]
        self.assertIn("DEEP_DISCOUNT", r["flags"])

    def test_no_deep_discount_shallow(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst(price_usd=0.95, face_value_usd=1.0,
                             days_to_maturity=180.0)], NO_LOG)["results"][0]
        self.assertNotIn("DEEP_DISCOUNT", r["flags"])

    def test_flags_is_list(self):
        a = DeFiFixedRateDurationAnalyzer()
        self.assertIsInstance(a.analyze([_inst()], NO_LOG)["results"][0]["flags"], list)


# ===========================================================================
# 8. Aggregates
# ===========================================================================

class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.a = DeFiFixedRateDurationAnalyzer()
        self.insts = [
            _inst(name="Best", price_usd=0.9, days_to_maturity=60.0, spot_apy_pct=1.0),
            _inst(name="Longest", price_usd=0.95, days_to_maturity=700.0, spot_apy_pct=1.0),
            _inst(name="NegPickup", price_usd=0.99, days_to_maturity=180.0, spot_apy_pct=30.0),
        ]
        self.out = self.a.analyze(self.insts, NO_LOG)
        self.agg = self.out["aggregates"]

    def test_aggregate_keys(self):
        for key in (
            "best_fixed_rate", "longest_duration_instrument",
            "average_ytm_pct", "average_modified_duration",
            "highest_yield_pickup_instrument", "negative_pickup_count",
        ):
            self.assertIn(key, self.agg)

    def test_longest_duration(self):
        self.assertEqual(self.agg["longest_duration_instrument"], "Longest")

    def test_negative_pickup_count(self):
        self.assertEqual(self.agg["negative_pickup_count"], 1)

    def test_highest_yield_pickup(self):
        self.assertEqual(self.agg["highest_yield_pickup_instrument"], "Best")

    def test_average_ytm_float(self):
        self.assertIsInstance(self.agg["average_ytm_pct"], float)

    def test_average_modified_duration_float(self):
        self.assertIsInstance(self.agg["average_modified_duration"], float)

    def test_best_fixed_rate_set(self):
        self.assertIsNotNone(self.agg["best_fixed_rate"])


# ===========================================================================
# 9. Empty input
# ===========================================================================

class TestEmptyInput(unittest.TestCase):
    def test_empty_results(self):
        a = DeFiFixedRateDurationAnalyzer()
        self.assertEqual(a.analyze([], NO_LOG)["results"], [])

    def test_empty_aggregates(self):
        a = DeFiFixedRateDurationAnalyzer()
        agg = a.analyze([], NO_LOG)["aggregates"]
        self.assertIsNone(agg["best_fixed_rate"])
        self.assertIsNone(agg["longest_duration_instrument"])
        self.assertIsNone(agg["highest_yield_pickup_instrument"])
        self.assertEqual(agg["negative_pickup_count"], 0)
        self.assertEqual(agg["average_ytm_pct"], 0.0)
        self.assertEqual(agg["average_modified_duration"], 0.0)


# ===========================================================================
# 10. Input validation & defaults
# ===========================================================================

class TestInputValidation(unittest.TestCase):
    def test_non_list_raises(self):
        a = DeFiFixedRateDurationAnalyzer()
        with self.assertRaises(TypeError):
            a.analyze("nope", NO_LOG)

    def test_dict_raises(self):
        a = DeFiFixedRateDurationAnalyzer()
        with self.assertRaises(TypeError):
            a.analyze({"name": "x"}, NO_LOG)

    def test_default_face_value(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([{"name": "x", "price_usd": 0.95,
                        "days_to_maturity": 100.0}], NO_LOG)["results"][0]
        self.assertEqual(r["face_value_usd"], 1.0)

    def test_default_spot_apy_zero(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([{"name": "x", "price_usd": 0.95,
                        "days_to_maturity": 100.0}], NO_LOG)["results"][0]
        self.assertEqual(r["spot_apy_pct"], 0.0)

    def test_config_none_no_crash(self):
        a = DeFiFixedRateDurationAnalyzer()
        out = a.analyze([_inst()], None)
        self.assertIn("results", out)


# ===========================================================================
# 11. Logging / persistence
# ===========================================================================

class TestLogging(unittest.TestCase):
    def test_no_log_disabled(self):
        a = DeFiFixedRateDurationAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_inst()], {"write_log": False, "log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_log_written(self):
        a = DeFiFixedRateDurationAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_inst()], {"write_log": True, "log_path": path})
            self.assertTrue(os.path.exists(path))

    def test_log_is_valid_json_array(self):
        a = DeFiFixedRateDurationAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_inst()], {"write_log": True, "log_path": path})
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_log_entry_fields(self):
        a = DeFiFixedRateDurationAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_inst()], {"write_log": True, "log_path": path})
            with open(path) as fh:
                entry = json.load(fh)[0]
            self.assertIn("timestamp", entry)
            self.assertIn("item_count", entry)
            self.assertIn("aggregates", entry)

    def test_ring_buffer_cap(self):
        a = DeFiFixedRateDurationAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(103):
                a.analyze([_inst()], {"write_log": True, "log_path": path})
            with open(path) as fh:
                self.assertEqual(len(json.load(fh)), 100)

    def test_atomic_log_direct(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _atomic_log(path, {"x": 1})
            _atomic_log(path, {"x": 2})
            with open(path) as fh:
                self.assertEqual(len(json.load(fh)), 2)

    def test_atomic_log_corrupt_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                fh.write("{garbage")
            _atomic_log(path, {"x": 1})
            with open(path) as fh:
                self.assertEqual(json.load(fh), [{"x": 1}])


# ===========================================================================
# 12. Determinism
# ===========================================================================

class TestDeterminism(unittest.TestCase):
    def test_repeatable(self):
        a = DeFiFixedRateDurationAnalyzer()
        r1 = a.analyze([_inst()], NO_LOG)["results"]
        r2 = a.analyze([_inst()], NO_LOG)["results"]
        self.assertEqual(r1, r2)

    def test_ytm_rounded_six(self):
        a = DeFiFixedRateDurationAnalyzer()
        r = a.analyze([_inst()], NO_LOG)["results"][0]
        self.assertEqual(r["ytm_pct"], round(r["ytm_pct"], 6))

    def test_independent_instruments(self):
        a = DeFiFixedRateDurationAnalyzer()
        out = a.analyze([
            _inst(name="A", price_usd=0.9, days_to_maturity=60.0, spot_apy_pct=1.0),
            _inst(name="B", price_usd=0.99, days_to_maturity=700.0, spot_apy_pct=20.0),
        ], NO_LOG)
        self.assertGreater(out["results"][0]["score"], out["results"][1]["score"])


if __name__ == "__main__":
    unittest.main()
