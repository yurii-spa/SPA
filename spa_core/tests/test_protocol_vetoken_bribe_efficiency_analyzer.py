"""
Tests for MP-932 ProtocolVeTokenBribeEfficiencyAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_vetoken_bribe_efficiency_analyzer -v
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

from spa_core.analytics.protocol_vetoken_bribe_efficiency_analyzer import (
    ProtocolVeTokenBribeEfficiencyAnalyzer,
    _safe_div,
    _grade_from_efficiency,
    _classification_from_efficiency,
    _atomic_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gauge(
    name="GaugeA",
    votes=1000.0,
    bribe_usd=500.0,
    emissions_usd=1000.0,
    vote_value_usd=1.0,
    epochs_per_year=52.0,
):
    return {
        "name": name,
        "votes": votes,
        "bribe_usd": bribe_usd,
        "emissions_usd": emissions_usd,
        "vote_value_usd": vote_value_usd,
        "epochs_per_year": epochs_per_year,
    }


NO_LOG = {"write_log": False}


# ===========================================================================
# 1. Instantiation and basic structure
# ===========================================================================

class TestInstantiation(unittest.TestCase):
    def test_instantiation(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        self.assertIsNotNone(a)

    def test_analyze_returns_dict(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        out = a.analyze([_gauge()], NO_LOG)
        self.assertIsInstance(out, dict)

    def test_output_top_level_keys(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        out = a.analyze([_gauge()], NO_LOG)
        for key in ("results", "aggregates", "timestamp"):
            self.assertIn(key, out)

    def test_results_is_list(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        out = a.analyze([_gauge()], NO_LOG)
        self.assertIsInstance(out["results"], list)

    def test_results_length_matches_input(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        out = a.analyze([_gauge(), _gauge(name="B")], NO_LOG)
        self.assertEqual(len(out["results"]), 2)

    def test_timestamp_is_float(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        out = a.analyze([_gauge()], NO_LOG)
        self.assertIsInstance(out["timestamp"], float)

    def test_per_gauge_keys(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge()], NO_LOG)["results"][0]
        for key in (
            "name", "votes", "bribe_usd", "emissions_usd",
            "bribe_per_vote", "emission_value_per_vote",
            "briber_efficiency_ratio", "voter_apr_pct",
            "classification", "grade", "flags",
        ):
            self.assertIn(key, r)

    def test_name_passthrough(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(name="CurveTriCrypto")], NO_LOG)["results"][0]
        self.assertEqual(r["name"], "CurveTriCrypto")

    def test_missing_name_defaults_unknown(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([{"votes": 1.0, "bribe_usd": 1.0, "emissions_usd": 1.0}], NO_LOG)
        self.assertEqual(r["results"][0]["name"], "unknown")


# ===========================================================================
# 2. _safe_div helper
# ===========================================================================

class TestSafeDiv(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(_safe_div(10.0, 2.0), 5.0)

    def test_zero_denominator(self):
        self.assertEqual(_safe_div(10.0, 0.0), 0.0)

    def test_negative_denominator(self):
        self.assertEqual(_safe_div(10.0, -2.0), 0.0)

    def test_none_denominator(self):
        self.assertEqual(_safe_div(10.0, None), 0.0)

    def test_zero_numerator(self):
        self.assertEqual(_safe_div(0.0, 5.0), 0.0)

    def test_fractional(self):
        self.assertAlmostEqual(_safe_div(1.0, 4.0), 0.25)


# ===========================================================================
# 3. Grade & classification mapping
# ===========================================================================

class TestGradeMapping(unittest.TestCase):
    def test_grade_a(self):
        self.assertEqual(_grade_from_efficiency(2.5), "A")

    def test_grade_a_boundary(self):
        self.assertEqual(_grade_from_efficiency(2.0), "A")

    def test_grade_b(self):
        self.assertEqual(_grade_from_efficiency(1.5), "B")

    def test_grade_b_boundary(self):
        self.assertEqual(_grade_from_efficiency(1.3), "B")

    def test_grade_c(self):
        self.assertEqual(_grade_from_efficiency(1.0), "C")

    def test_grade_c_boundary(self):
        self.assertEqual(_grade_from_efficiency(0.9), "C")

    def test_grade_d(self):
        self.assertEqual(_grade_from_efficiency(0.6), "D")

    def test_grade_d_boundary(self):
        self.assertEqual(_grade_from_efficiency(0.5), "D")

    def test_grade_f(self):
        self.assertEqual(_grade_from_efficiency(0.2), "F")

    def test_grade_f_zero(self):
        self.assertEqual(_grade_from_efficiency(0.0), "F")


class TestClassificationMapping(unittest.TestCase):
    def test_highly_efficient(self):
        self.assertEqual(_classification_from_efficiency(3.0), "HIGHLY_EFFICIENT")

    def test_efficient(self):
        self.assertEqual(_classification_from_efficiency(1.4), "EFFICIENT")

    def test_break_even(self):
        self.assertEqual(_classification_from_efficiency(1.0), "BREAK_EVEN")

    def test_inefficient(self):
        self.assertEqual(_classification_from_efficiency(0.7), "INEFFICIENT")

    def test_wasteful(self):
        self.assertEqual(_classification_from_efficiency(0.1), "WASTEFUL")

    def test_classification_grade_consistency(self):
        # grade A always pairs with HIGHLY_EFFICIENT
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(bribe_usd=100.0, emissions_usd=500.0)], NO_LOG)["results"][0]
        self.assertEqual(r["grade"], "A")
        self.assertEqual(r["classification"], "HIGHLY_EFFICIENT")


# ===========================================================================
# 4. Briber efficiency ratio
# ===========================================================================

class TestBriberEfficiency(unittest.TestCase):
    def test_basic_ratio(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(bribe_usd=500.0, emissions_usd=1000.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["briber_efficiency_ratio"], 2.0)

    def test_break_even_ratio(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(bribe_usd=1000.0, emissions_usd=1000.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["briber_efficiency_ratio"], 1.0)

    def test_inefficient_ratio(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(bribe_usd=2000.0, emissions_usd=1000.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["briber_efficiency_ratio"], 0.5)

    def test_zero_bribe_ratio(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(bribe_usd=0.0, emissions_usd=1000.0)], NO_LOG)["results"][0]
        self.assertEqual(r["briber_efficiency_ratio"], 0.0)

    def test_high_efficiency_grade(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(bribe_usd=100.0, emissions_usd=1000.0)], NO_LOG)["results"][0]
        self.assertEqual(r["grade"], "A")


# ===========================================================================
# 5. Bribe-per-vote and emission-value-per-vote
# ===========================================================================

class TestPerVote(unittest.TestCase):
    def test_bribe_per_vote(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(votes=1000.0, bribe_usd=500.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["bribe_per_vote"], 0.5)

    def test_emission_value_per_vote(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(votes=1000.0, emissions_usd=2000.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["emission_value_per_vote"], 2.0)

    def test_zero_votes_bribe_per_vote(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(votes=0.0)], NO_LOG)["results"][0]
        self.assertEqual(r["bribe_per_vote"], 0.0)

    def test_zero_votes_emission_per_vote(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(votes=0.0)], NO_LOG)["results"][0]
        self.assertEqual(r["emission_value_per_vote"], 0.0)


# ===========================================================================
# 6. Voter APR
# ===========================================================================

class TestVoterAPR(unittest.TestCase):
    def test_basic_voter_apr(self):
        # bribe_per_vote = 500/1000 = 0.5; vote_value = 1; epochs = 52
        # apr = 0.5 * 52 * 100 = 2600 %
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(votes=1000.0, bribe_usd=500.0,
                              vote_value_usd=1.0, epochs_per_year=52.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["voter_apr_pct"], 2600.0)

    def test_voter_apr_with_vote_value(self):
        # bribe_per_vote = 0.5; vote_value = 10; epochs = 52
        # per_epoch = 0.05; apr = 0.05*52*100 = 260 %
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(votes=1000.0, bribe_usd=500.0,
                              vote_value_usd=10.0, epochs_per_year=52.0)], NO_LOG)["results"][0]
        self.assertAlmostEqual(r["voter_apr_pct"], 260.0)

    def test_voter_apr_zero_when_no_bribe(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(bribe_usd=0.0)], NO_LOG)["results"][0]
        self.assertEqual(r["voter_apr_pct"], 0.0)

    def test_voter_apr_zero_vote_value_guard(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(vote_value_usd=0.0)], NO_LOG)["results"][0]
        self.assertEqual(r["voter_apr_pct"], 0.0)

    def test_low_voter_apr(self):
        # small bribe relative to vote value
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(votes=1000.0, bribe_usd=1.0,
                              vote_value_usd=100.0, epochs_per_year=52.0)], NO_LOG)["results"][0]
        # bribe_per_vote = 0.001; per_epoch = 0.00001; apr = 0.052 %
        self.assertAlmostEqual(r["voter_apr_pct"], 0.052, places=4)

    def test_default_epochs_via_config(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        g = {"name": "X", "votes": 1000.0, "bribe_usd": 500.0, "vote_value_usd": 1.0}
        r = a.analyze([g], {"write_log": False, "epochs_per_year": 26.0})["results"][0]
        # gauge has no epochs_per_year, falls back to config 26
        self.assertAlmostEqual(r["voter_apr_pct"], 1300.0)


# ===========================================================================
# 7. Flags
# ===========================================================================

class TestFlags(unittest.TestCase):
    def test_no_votes_flag(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(votes=0.0)], NO_LOG)["results"][0]
        self.assertIn("NO_VOTES", r["flags"])

    def test_no_bribe_flag(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(bribe_usd=0.0)], NO_LOG)["results"][0]
        self.assertIn("NO_BRIBE", r["flags"])

    def test_overbribed_flag(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(bribe_usd=1500.0, emissions_usd=1000.0)], NO_LOG)["results"][0]
        self.assertIn("OVERBRIBED", r["flags"])

    def test_not_overbribed_when_equal(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(bribe_usd=1000.0, emissions_usd=1000.0)], NO_LOG)["results"][0]
        self.assertNotIn("OVERBRIBED", r["flags"])

    def test_underbribed_flag(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(bribe_usd=50.0, emissions_usd=1000.0)], NO_LOG)["results"][0]
        self.assertIn("UNDERBRIBED", r["flags"])

    def test_not_underbribed_above_threshold(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(bribe_usd=200.0, emissions_usd=1000.0)], NO_LOG)["results"][0]
        self.assertNotIn("UNDERBRIBED", r["flags"])

    def test_high_voter_apr_flag(self):
        # voter apr between 50 and 100
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(votes=1000.0, bribe_usd=15.0,
                              vote_value_usd=1.0, epochs_per_year=5.0)], NO_LOG)["results"][0]
        # bribe_per_vote = 0.015; per_epoch=0.015; apr = 0.015*5*100 = 7.5 -> too low
        # adjust: use direct check on a constructed high apr
        r2 = a.analyze([_gauge(votes=1000.0, bribe_usd=15.0,
                               vote_value_usd=1.0, epochs_per_year=50.0)], NO_LOG)["results"][0]
        # apr = 0.015*50*100 = 75 -> HIGH_VOTER_APR
        self.assertIn("HIGH_VOTER_APR", r2["flags"])
        self.assertNotIn("MERCENARY_RISK", r2["flags"])

    def test_mercenary_risk_flag(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(votes=1000.0, bribe_usd=500.0,
                              vote_value_usd=1.0, epochs_per_year=52.0)], NO_LOG)["results"][0]
        # apr = 2600 % -> mercenary
        self.assertIn("MERCENARY_RISK", r["flags"])
        self.assertNotIn("HIGH_VOTER_APR", r["flags"])

    def test_flags_is_list(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge()], NO_LOG)["results"][0]
        self.assertIsInstance(r["flags"], list)

    def test_clean_gauge_no_severe_flags(self):
        # moderate apr, balanced bribe
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(votes=100000.0, bribe_usd=400.0, emissions_usd=1000.0,
                              vote_value_usd=5.0, epochs_per_year=52.0)], NO_LOG)["results"][0]
        self.assertNotIn("NO_VOTES", r["flags"])
        self.assertNotIn("NO_BRIBE", r["flags"])
        self.assertNotIn("OVERBRIBED", r["flags"])


# ===========================================================================
# 8. Aggregates
# ===========================================================================

class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        self.gauges = [
            _gauge(name="Eff", bribe_usd=100.0, emissions_usd=1000.0),    # ratio 10
            _gauge(name="Mid", bribe_usd=1000.0, emissions_usd=1000.0),   # ratio 1
            _gauge(name="Bad", bribe_usd=2000.0, emissions_usd=1000.0),   # ratio 0.5
        ]
        self.out = self.a.analyze(self.gauges, NO_LOG)
        self.agg = self.out["aggregates"]

    def test_aggregate_keys(self):
        for key in (
            "most_efficient_gauge", "best_voter_apr_gauge",
            "average_briber_efficiency", "total_bribe_usd",
            "total_emissions_usd", "overall_efficiency_ratio",
            "overbribed_count", "efficient_count",
        ):
            self.assertIn(key, self.agg)

    def test_most_efficient_gauge(self):
        self.assertEqual(self.agg["most_efficient_gauge"], "Eff")

    def test_total_bribe(self):
        self.assertAlmostEqual(self.agg["total_bribe_usd"], 3100.0)

    def test_total_emissions(self):
        self.assertAlmostEqual(self.agg["total_emissions_usd"], 3000.0)

    def test_overall_efficiency_ratio(self):
        self.assertAlmostEqual(self.agg["overall_efficiency_ratio"], 3000.0 / 3100.0, places=5)

    def test_overbribed_count(self):
        self.assertEqual(self.agg["overbribed_count"], 1)  # only "Bad"

    def test_efficient_count(self):
        self.assertEqual(self.agg["efficient_count"], 1)  # only "Eff"

    def test_average_efficiency(self):
        expected = (10.0 + 1.0 + 0.5) / 3
        self.assertAlmostEqual(self.agg["average_briber_efficiency"], round(expected, 6))


# ===========================================================================
# 9. Empty input
# ===========================================================================

class TestEmptyInput(unittest.TestCase):
    def test_empty_results(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        out = a.analyze([], NO_LOG)
        self.assertEqual(out["results"], [])

    def test_empty_aggregates_defaults(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        agg = a.analyze([], NO_LOG)["aggregates"]
        self.assertIsNone(agg["most_efficient_gauge"])
        self.assertIsNone(agg["best_voter_apr_gauge"])
        self.assertEqual(agg["average_briber_efficiency"], 0.0)
        self.assertEqual(agg["total_bribe_usd"], 0.0)
        self.assertEqual(agg["overbribed_count"], 0)

    def test_empty_timestamp_present(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        out = a.analyze([], NO_LOG)
        self.assertIn("timestamp", out)


# ===========================================================================
# 10. Input validation
# ===========================================================================

class TestInputValidation(unittest.TestCase):
    def test_non_list_raises(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        with self.assertRaises(TypeError):
            a.analyze("not a list", NO_LOG)

    def test_dict_input_raises(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        with self.assertRaises(TypeError):
            a.analyze({"name": "x"}, NO_LOG)

    def test_none_config_ok(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        out = a.analyze([_gauge()], None)  # default write_log True; uses temp later
        self.assertIn("results", out)

    def test_missing_fields_default_zero(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([{"name": "Bare"}], NO_LOG)["results"][0]
        self.assertEqual(r["votes"], 0.0)
        self.assertEqual(r["bribe_usd"], 0.0)
        self.assertEqual(r["emissions_usd"], 0.0)


# ===========================================================================
# 11. Logging / persistence
# ===========================================================================

class TestLogging(unittest.TestCase):
    def test_no_log_when_disabled(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_gauge()], {"write_log": False, "log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_log_written_when_enabled(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_gauge()], {"write_log": True, "log_path": path})
            self.assertTrue(os.path.exists(path))

    def test_log_is_json_list(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_gauge()], {"write_log": True, "log_path": path})
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_log_entry_fields(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            a.analyze([_gauge()], {"write_log": True, "log_path": path})
            with open(path) as fh:
                entry = json.load(fh)[0]
            self.assertIn("timestamp", entry)
            self.assertIn("gauge_count", entry)
            self.assertIn("aggregates", entry)

    def test_ring_buffer_cap(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(105):
                a.analyze([_gauge()], {"write_log": True, "log_path": path})
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 100)

    def test_atomic_log_direct(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _atomic_log(path, {"a": 1})
            _atomic_log(path, {"a": 2})
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[1]["a"], 2)

    def test_atomic_log_corrupt_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                fh.write("not json")
            _atomic_log(path, {"a": 1})
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(data, [{"a": 1}])


# ===========================================================================
# 12. Determinism & rounding
# ===========================================================================

class TestDeterminism(unittest.TestCase):
    def test_same_input_same_results(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        out1 = a.analyze([_gauge()], NO_LOG)["results"]
        out2 = a.analyze([_gauge()], NO_LOG)["results"]
        self.assertEqual(out1, out2)

    def test_efficiency_rounded(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        r = a.analyze([_gauge(bribe_usd=3.0, emissions_usd=7.0)], NO_LOG)["results"][0]
        # 7/3 = 2.333333...
        self.assertEqual(r["briber_efficiency_ratio"], round(7.0 / 3.0, 6))

    def test_multiple_gauges_independent(self):
        a = ProtocolVeTokenBribeEfficiencyAnalyzer()
        out = a.analyze([
            _gauge(name="A", bribe_usd=100.0, emissions_usd=1000.0),
            _gauge(name="B", bribe_usd=5000.0, emissions_usd=1000.0),
        ], NO_LOG)
        self.assertEqual(out["results"][0]["grade"], "A")
        self.assertEqual(out["results"][1]["grade"], "F")


if __name__ == "__main__":
    unittest.main()
