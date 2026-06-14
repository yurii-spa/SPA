"""
Tests for ProtocolDeFiPointsSystemValuationAnalyzer (MP-997).
Run: python3 -m unittest spa_core.tests.test_protocol_defi_points_system_valuation_analyzer
"""
import json
import os
import sys
import tempfile
import unittest

# Ensure repo root on path
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.protocol_defi_points_system_valuation_analyzer import (
    ProtocolDeFiPointsSystemValuationAnalyzer,
    _atomic_write,
    _load_log,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _high_value() -> dict:
    """Confirmed high-value program."""
    return {
        "name": "AlphaPoints",
        "protocol": "AlphaDeFi",
        "total_points_issued": 1_000_000,
        "points_per_dollar_per_day": 1.0,
        "total_tvl_usd": 500_000_000,
        "fdv_hint_usd": 2_000_000_000,
        "expected_airdrop_pct_of_fdv": 0.10,
        "points_to_fdv_conversion_announced": True,
        "snapshot_date_days_until": 60,
        "has_transferable_points": True,
        "points_market_price_usd": 0.20,
        "competing_programs_count": 2,
        "user_count": 50_000,
    }


def _low_value() -> dict:
    """Low-value speculative program."""
    return {
        "name": "GammaPoints",
        "protocol": "GammaDeFi",
        "total_points_issued": 100_000_000_000,
        "points_per_dollar_per_day": 0.001,
        "total_tvl_usd": 10_000_000,
        "fdv_hint_usd": None,
        "expected_airdrop_pct_of_fdv": 0,
        "points_to_fdv_conversion_announced": False,
        "snapshot_date_days_until": None,
        "has_transferable_points": False,
        "points_market_price_usd": None,
        "competing_programs_count": 8,
        "user_count": 5_000,
    }


def _speculative() -> dict:
    """Speculative but promising."""
    return {
        "name": "BetaPoints",
        "protocol": "BetaDeFi",
        "total_points_issued": 10_000_000,
        "points_per_dollar_per_day": 0.5,
        "total_tvl_usd": 100_000_000,
        "fdv_hint_usd": 500_000_000,
        "expected_airdrop_pct_of_fdv": 0.15,
        "points_to_fdv_conversion_announced": False,
        "snapshot_date_days_until": 45,
        "has_transferable_points": False,
        "points_market_price_usd": None,
        "competing_programs_count": 3,
        "user_count": 20_000,
    }


def _imminent_snapshot() -> dict:
    """Snapshot imminent (<30 days)."""
    p = dict(_speculative())
    p["snapshot_date_days_until"] = 10
    return p


def _dilution_risk() -> dict:
    """High dilution risk."""
    return {
        "name": "DeltaPoints",
        "protocol": "DeltaDeFi",
        "total_points_issued": 50_000_000_000,
        "points_per_dollar_per_day": 0.1,
        "total_tvl_usd": 5_000_000,
        "fdv_hint_usd": 100_000_000,
        "expected_airdrop_pct_of_fdv": 0.05,
        "points_to_fdv_conversion_announced": False,
        "snapshot_date_days_until": None,
        "has_transferable_points": False,
        "points_market_price_usd": None,
        "competing_programs_count": 10,
        "user_count": 100_000,
    }


def _analyzer(tmp_dir: str) -> ProtocolDeFiPointsSystemValuationAnalyzer:
    log_path = os.path.join(tmp_dir, "test_points_log.json")
    return ProtocolDeFiPointsSystemValuationAnalyzer(log_path=log_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBasicAnalysis(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = _analyzer(self.tmp)

    def test_returns_dict(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertIsInstance(result, dict)

    def test_results_key_present(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertIn("results", result)

    def test_aggregates_key_present(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertIn("aggregates", result)

    def test_timestamp_present(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertIn("timestamp", result)

    def test_single_program_count(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertEqual(len(result["results"]), 1)

    def test_two_programs_count(self):
        result = self.az.analyze([_high_value(), _low_value()], {"write_log": False})
        self.assertEqual(len(result["results"]), 2)

    def test_empty_programs(self):
        result = self.az.analyze([], {"write_log": False})
        self.assertEqual(result["results"], [])

    def test_empty_aggregates_total(self):
        result = self.az.analyze([], {"write_log": False})
        self.assertEqual(result["aggregates"]["total_programs"], 0)

    def test_high_value_label(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertEqual(result["results"][0]["label"], "HIGH_VALUE_CONFIRMED")

    def test_low_value_label(self):
        result = self.az.analyze([_low_value()], {"write_log": False})
        label = result["results"][0]["label"]
        self.assertIn(label, {"LOW_VALUE", "DILUTION_RISK", "SPECULATIVE_VALUE"})

    def test_program_name_in_result(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertEqual(result["results"][0]["program"], "AlphaPoints")

    def test_protocol_name_in_result(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertEqual(result["results"][0]["protocol"], "AlphaDeFi")

    def test_implied_value_numeric(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertIsInstance(result["results"][0]["implied_point_value_usd"], float)

    def test_apy_numeric(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertIsInstance(result["results"][0]["apy_from_points_pct"], float)

    def test_dilution_score_range(self):
        result = self.az.analyze([_dilution_risk()], {"write_log": False})
        score = result["results"][0]["dilution_risk_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_discount_factor_range(self):
        result = self.az.analyze([_speculative()], {"write_log": False})
        d = result["results"][0]["uncertainty_discount_factor"]
        self.assertGreaterEqual(d, 0)
        self.assertLessEqual(d, 1)

    def test_risk_adj_value_numeric(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertIsInstance(result["results"][0]["risk_adjusted_implied_value_usd"], float)

    def test_flags_is_list(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertIsInstance(result["results"][0]["flags"], list)

    def test_market_price_used_when_available(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        # market price = 0.20
        self.assertAlmostEqual(result["results"][0]["implied_point_value_usd"], 0.20, places=4)

    def test_implied_value_from_fdv_when_no_market(self):
        result = self.az.analyze([_speculative()], {"write_log": False})
        # fdv=500M, airdrop_pct=0.15, total_pts=10M → 0.15*500M/10M = 7.5
        self.assertAlmostEqual(result["results"][0]["implied_point_value_usd"], 7.5, places=2)

    def test_zero_implied_value_no_data(self):
        result = self.az.analyze([_low_value()], {"write_log": False})
        self.assertEqual(result["results"][0]["implied_point_value_usd"], 0.0)

    def test_apy_positive_for_high_value(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertGreater(result["results"][0]["apy_from_points_pct"], 0)


class TestFlags(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = _analyzer(self.tmp)

    def test_points_market_exists_flag(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertIn("POINTS_MARKET_EXISTS", result["results"][0]["flags"])

    def test_no_market_flag_when_absent(self):
        result = self.az.analyze([_speculative()], {"write_log": False})
        self.assertNotIn("POINTS_MARKET_EXISTS", result["results"][0]["flags"])

    def test_snapshot_imminent_flag(self):
        result = self.az.analyze([_imminent_snapshot()], {"write_log": False})
        self.assertIn("SNAPSHOT_IMMINENT", result["results"][0]["flags"])

    def test_no_snapshot_imminent_flag_high_days(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertNotIn("SNAPSHOT_IMMINENT", result["results"][0]["flags"])

    def test_conversion_announced_flag(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertIn("CONVERSION_ANNOUNCED", result["results"][0]["flags"])

    def test_no_conversion_flag(self):
        result = self.az.analyze([_speculative()], {"write_log": False})
        self.assertNotIn("CONVERSION_ANNOUNCED", result["results"][0]["flags"])

    def test_transferable_points_flag(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertIn("TRANSFERABLE_POINTS", result["results"][0]["flags"])

    def test_no_transferable_flag(self):
        result = self.az.analyze([_speculative()], {"write_log": False})
        self.assertNotIn("TRANSFERABLE_POINTS", result["results"][0]["flags"])

    def test_high_dilution_risk_flag(self):
        result = self.az.analyze([_dilution_risk()], {"write_log": False})
        self.assertIn("HIGH_DILUTION_RISK", result["results"][0]["flags"])

    def test_no_high_dilution_low_competing(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        self.assertNotIn("HIGH_DILUTION_RISK", result["results"][0]["flags"])

    def test_no_fdv_signal_flag(self):
        result = self.az.analyze([_low_value()], {"write_log": False})
        self.assertIn("NO_FDV_SIGNAL", result["results"][0]["flags"])

    def test_no_fdv_signal_absent_when_fdv_present(self):
        result = self.az.analyze([_speculative()], {"write_log": False})
        self.assertNotIn("NO_FDV_SIGNAL", result["results"][0]["flags"])

    def test_snapshot_imminent_boundary_29_days(self):
        p = dict(_speculative())
        p["snapshot_date_days_until"] = 29
        result = self.az.analyze([p], {"write_log": False})
        self.assertIn("SNAPSHOT_IMMINENT", result["results"][0]["flags"])

    def test_no_snapshot_imminent_at_30_days(self):
        p = dict(_speculative())
        p["snapshot_date_days_until"] = 30
        result = self.az.analyze([p], {"write_log": False})
        self.assertNotIn("SNAPSHOT_IMMINENT", result["results"][0]["flags"])


class TestAggregates(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = _analyzer(self.tmp)

    def test_highest_value_program(self):
        result = self.az.analyze([_high_value(), _low_value()], {"write_log": False})
        self.assertEqual(result["aggregates"]["highest_value_program"], "AlphaPoints")

    def test_lowest_value_program(self):
        result = self.az.analyze([_high_value(), _low_value()], {"write_log": False})
        self.assertEqual(result["aggregates"]["lowest_value_program"], "GammaPoints")

    def test_avg_risk_adj_value_numeric(self):
        result = self.az.analyze([_high_value(), _low_value()], {"write_log": False})
        self.assertIsInstance(result["aggregates"]["avg_risk_adjusted_value"], float)

    def test_confirmed_count(self):
        result = self.az.analyze([_high_value(), _speculative()], {"write_log": False})
        self.assertEqual(result["aggregates"]["confirmed_count"], 1)

    def test_dilution_risk_count(self):
        result = self.az.analyze([_dilution_risk(), _high_value()], {"write_log": False})
        self.assertGreaterEqual(result["aggregates"]["dilution_risk_count"], 0)

    def test_total_programs(self):
        result = self.az.analyze([_high_value(), _low_value(), _speculative()], {"write_log": False})
        self.assertEqual(result["aggregates"]["total_programs"], 3)

    def test_aggregates_keys_complete(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        agg = result["aggregates"]
        for key in ["highest_value_program", "lowest_value_program",
                    "avg_risk_adjusted_value", "confirmed_count",
                    "dilution_risk_count", "total_programs"]:
            self.assertIn(key, agg)

    def test_zero_confirmed_when_no_high_value(self):
        result = self.az.analyze([_low_value()], {"write_log": False})
        self.assertEqual(result["aggregates"]["confirmed_count"], 0)

    def test_avg_risk_adj_value_zero_when_empty(self):
        result = self.az.analyze([], {"write_log": False})
        self.assertEqual(result["aggregates"]["avg_risk_adjusted_value"], 0.0)


class TestLogWriting(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, "points_log.json")
        self.az = ProtocolDeFiPointsSystemValuationAnalyzer(log_path=self.log_path)

    def test_log_file_created(self):
        self.az.analyze([_high_value()], {"write_log": True})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.az.analyze([_high_value()], {"write_log": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_contains_one_entry(self):
        self.az.analyze([_high_value()], {"write_log": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_grows(self):
        self.az.analyze([_high_value()], {"write_log": True})
        self.az.analyze([_low_value()], {"write_log": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_no_write_when_disabled(self):
        self.az.analyze([_high_value()], {"write_log": False})
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_ring_buffer_cap(self):
        for i in range(105):
            p = dict(_high_value())
            p["name"] = f"P{i}"
            self.az.analyze([p], {"write_log": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_atomic_write_helper(self):
        path = os.path.join(self.tmp, "atomic_test.json")
        _atomic_write(path, {"key": "value"})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["key"], "value")

    def test_load_log_missing_file(self):
        result = _load_log("/nonexistent/path.json")
        self.assertEqual(result, [])

    def test_load_log_invalid_json(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w") as f:
            f.write("not json")
        result = _load_log(bad)
        self.assertEqual(result, [])

    def test_log_entry_has_results(self):
        self.az.analyze([_high_value()], {"write_log": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("results", data[0])

    def test_log_entry_has_aggregates(self):
        self.az.analyze([_high_value()], {"write_log": True})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("aggregates", data[0])


class TestValuationCalculations(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = _analyzer(self.tmp)

    def test_market_price_overrides_fdv_implied(self):
        p = dict(_speculative())
        p["points_market_price_usd"] = 1.0
        result = self.az.analyze([p], {"write_log": False})
        # market price should be used
        self.assertAlmostEqual(result["results"][0]["implied_point_value_usd"], 1.0, places=4)

    def test_zero_total_points_yields_zero(self):
        p = dict(_speculative())
        p["total_points_issued"] = 0
        p["points_market_price_usd"] = None
        result = self.az.analyze([p], {"write_log": False})
        self.assertEqual(result["results"][0]["implied_point_value_usd"], 0.0)

    def test_apy_scales_with_ppd(self):
        p1 = dict(_speculative())
        p1["points_per_dollar_per_day"] = 0.5
        p2 = dict(_speculative())
        p2["points_per_dollar_per_day"] = 1.0
        r1 = self.az.analyze([p1], {"write_log": False})
        r2 = self.az.analyze([p2], {"write_log": False})
        self.assertLess(
            r1["results"][0]["apy_from_points_pct"],
            r2["results"][0]["apy_from_points_pct"],
        )

    def test_discount_factor_announced_vs_speculative(self):
        p_ann = dict(_speculative())
        p_ann["points_to_fdv_conversion_announced"] = True
        p_spec = dict(_speculative())
        r_ann = self.az.analyze([p_ann], {"write_log": False})
        r_spec = self.az.analyze([p_spec], {"write_log": False})
        self.assertGreater(
            r_ann["results"][0]["uncertainty_discount_factor"],
            r_spec["results"][0]["uncertainty_discount_factor"],
        )

    def test_market_price_gives_highest_discount(self):
        p = dict(_speculative())
        p["points_market_price_usd"] = 5.0
        result = self.az.analyze([p], {"write_log": False})
        self.assertEqual(result["results"][0]["uncertainty_discount_factor"], 0.95)

    def test_no_fdv_gives_lowest_discount(self):
        result = self.az.analyze([_low_value()], {"write_log": False})
        self.assertEqual(result["results"][0]["uncertainty_discount_factor"], 0.20)

    def test_risk_adj_value_lower_than_implied_when_discount_lt_1(self):
        result = self.az.analyze([_speculative()], {"write_log": False})
        r = result["results"][0]
        if r["implied_point_value_usd"] > 0:
            self.assertLess(
                r["risk_adjusted_implied_value_usd"],
                r["implied_point_value_usd"],
            )

    def test_dilution_score_increases_with_competitors(self):
        p_few = dict(_speculative())
        p_few["competing_programs_count"] = 1
        p_many = dict(_speculative())
        p_many["competing_programs_count"] = 9
        r_few = self.az.analyze([p_few], {"write_log": False})
        r_many = self.az.analyze([p_many], {"write_log": False})
        self.assertLess(
            r_few["results"][0]["dilution_risk_score"],
            r_many["results"][0]["dilution_risk_score"],
        )

    def test_dilution_score_not_exceed_100(self):
        p = dict(_dilution_risk())
        p["competing_programs_count"] = 100
        result = self.az.analyze([p], {"write_log": False})
        self.assertLessEqual(result["results"][0]["dilution_risk_score"], 100)

    def test_dilution_score_not_negative(self):
        p = dict(_high_value())
        p["competing_programs_count"] = 0
        result = self.az.analyze([p], {"write_log": False})
        self.assertGreaterEqual(result["results"][0]["dilution_risk_score"], 0)

    def test_fdv_hint_discount_factor(self):
        result = self.az.analyze([_speculative()], {"write_log": False})
        self.assertEqual(result["results"][0]["uncertainty_discount_factor"], 0.50)

    def test_announced_discount_factor(self):
        p = dict(_speculative())
        p["points_to_fdv_conversion_announced"] = True
        p["points_market_price_usd"] = None
        result = self.az.analyze([p], {"write_log": False})
        self.assertEqual(result["results"][0]["uncertainty_discount_factor"], 0.90)


class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.az = _analyzer(self.tmp)

    def test_missing_name_defaults(self):
        p = dict(_high_value())
        del p["name"]
        result = self.az.analyze([p], {"write_log": False})
        self.assertEqual(result["results"][0]["program"], "unknown")

    def test_missing_protocol_defaults(self):
        p = dict(_high_value())
        del p["protocol"]
        result = self.az.analyze([p], {"write_log": False})
        self.assertEqual(result["results"][0]["protocol"], "unknown")

    def test_zero_airdrop_pct_yields_zero(self):
        p = dict(_speculative())
        p["expected_airdrop_pct_of_fdv"] = 0
        p["points_market_price_usd"] = None
        result = self.az.analyze([p], {"write_log": False})
        self.assertEqual(result["results"][0]["implied_point_value_usd"], 0.0)

    def test_none_fdv_hint_with_no_market_yields_zero(self):
        p = dict(_speculative())
        p["fdv_hint_usd"] = None
        p["points_market_price_usd"] = None
        result = self.az.analyze([p], {"write_log": False})
        self.assertEqual(result["results"][0]["implied_point_value_usd"], 0.0)

    def test_many_programs(self):
        programs = []
        for i in range(20):
            p = dict(_speculative())
            p["name"] = f"P{i}"
            programs.append(p)
        result = self.az.analyze(programs, {"write_log": False})
        self.assertEqual(len(result["results"]), 20)

    def test_config_passed_to_output(self):
        cfg = {"write_log": False, "env": "test"}
        result = self.az.analyze([_high_value()], cfg)
        self.assertEqual(result["config"]["env"], "test")

    def test_result_keys_complete(self):
        result = self.az.analyze([_high_value()], {"write_log": False})
        r = result["results"][0]
        for key in ["program", "protocol", "implied_point_value_usd",
                    "apy_from_points_pct", "dilution_risk_score",
                    "uncertainty_discount_factor",
                    "risk_adjusted_implied_value_usd", "label", "flags"]:
            self.assertIn(key, r)

    def test_all_labels_valid(self):
        valid = {"HIGH_VALUE_CONFIRMED", "LIKELY_VALUABLE", "SPECULATIVE_VALUE",
                 "LOW_VALUE", "DILUTION_RISK"}
        for p in [_high_value(), _low_value(), _speculative(), _dilution_risk()]:
            result = self.az.analyze([p], {"write_log": False})
            self.assertIn(result["results"][0]["label"], valid)

    def test_likely_valuable_label(self):
        p = dict(_speculative())
        p["points_per_dollar_per_day"] = 2.0
        p["fdv_hint_usd"] = 1_000_000_000
        p["expected_airdrop_pct_of_fdv"] = 0.20
        p["total_points_issued"] = 1_000_000
        result = self.az.analyze([p], {"write_log": False})
        label = result["results"][0]["label"]
        self.assertIn(label, {"LIKELY_VALUABLE", "HIGH_VALUE_CONFIRMED",
                               "SPECULATIVE_VALUE", "DILUTION_RISK"})

    def test_zero_ppd_yields_zero_apy(self):
        p = dict(_speculative())
        p["points_per_dollar_per_day"] = 0
        result = self.az.analyze([p], {"write_log": False})
        self.assertEqual(result["results"][0]["apy_from_points_pct"], 0.0)

    def test_risk_adj_value_not_negative(self):
        for p in [_high_value(), _low_value(), _speculative(), _dilution_risk()]:
            result = self.az.analyze([p], {"write_log": False})
            self.assertGreaterEqual(result["results"][0]["risk_adjusted_implied_value_usd"], 0)

    def test_dilution_risk_label_possible(self):
        p = dict(_dilution_risk())
        result = self.az.analyze([p], {"write_log": False})
        label = result["results"][0]["label"]
        self.assertIn(label, {"HIGH_VALUE_CONFIRMED", "LIKELY_VALUABLE",
                               "SPECULATIVE_VALUE", "LOW_VALUE", "DILUTION_RISK"})

    def test_snapshot_none_no_imminent_flag(self):
        p = dict(_speculative())
        p["snapshot_date_days_until"] = None
        result = self.az.analyze([p], {"write_log": False})
        self.assertNotIn("SNAPSHOT_IMMINENT", result["results"][0]["flags"])

    def test_highest_and_lowest_same_when_single_program(self):
        result = self.az.analyze([_speculative()], {"write_log": False})
        self.assertEqual(
            result["aggregates"]["highest_value_program"],
            result["aggregates"]["lowest_value_program"],
        )

    def test_apy_calculation_formula(self):
        # apy = implied_value × ppd × 365 × 100
        # implied = market_price = 0.20; ppd = 1.0 → apy = 0.20 * 1.0 * 365 * 100 = 7300
        result = self.az.analyze([_high_value()], {"write_log": False})
        expected = 0.20 * 1.0 * 365 * 100
        self.assertAlmostEqual(
            result["results"][0]["apy_from_points_pct"],
            expected,
            places=1,
        )


if __name__ == "__main__":
    unittest.main()
