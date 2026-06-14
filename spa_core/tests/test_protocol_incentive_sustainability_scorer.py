"""
Tests for MP-983: ProtocolIncentiveSustainabilityScorer
Run with: python3 -m unittest spa_core.tests.test_protocol_incentive_sustainability_scorer -v
"""

import json
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_incentive_sustainability_scorer import (
    ProtocolIncentiveSustainabilityScorer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_program(
    protocol="ProtoA",
    incentive_token="TKN",
    budget=1_000_000,
    revenue=500_000,
    inc_tvl=20_000_000,
    org_tvl=80_000_000,
    treasury=12.0,
    i2r_ratio=2.0,
    retention=60.0,
    benchmark_drop=30.0,
):
    return {
        "protocol":                                     protocol,
        "incentive_token":                              incentive_token,
        "monthly_incentive_budget_usd":                 budget,
        "monthly_organic_revenue_usd":                  revenue,
        "incentive_tvl_usd":                            inc_tvl,
        "organic_tvl_usd":                              org_tvl,
        "token_treasury_remaining_months":              treasury,
        "incentive_to_revenue_ratio":                   i2r_ratio,
        "user_retention_rate_pct":                      retention,
        "similar_protocol_post_incentive_tvl_drop_pct": benchmark_drop,
    }


def _self_sustaining():
    """Revenue > budget AND retention >= 70% → SELF_SUSTAINING."""
    return _make_program(
        protocol="SelfSustaining",
        budget=500_000,
        revenue=800_000,
        retention=75.0,
        inc_tvl=10_000_000,
        org_tvl=90_000_000,
        treasury=24.0,
        benchmark_drop=20.0,
    )


def _ponzi():
    """ratio < 0.1 AND treasury < 6 months → PONZI_FLYWHEEL."""
    return _make_program(
        protocol="Ponzi",
        budget=10_000_000,
        revenue=100_000,  # ratio 0.01
        inc_tvl=200_000_000,
        org_tvl=2_000_000,
        treasury=3.0,
        retention=10.0,
        benchmark_drop=90.0,
    )


class TestBasicReturnStructure(unittest.TestCase):
    def setUp(self):
        self.scorer = ProtocolIncentiveSustainabilityScorer()

    def test_returns_dict(self):
        r = self.scorer.score([_make_program()], {"write_log": False})
        self.assertIsInstance(r, dict)

    def test_has_programs_key(self):
        r = self.scorer.score([_make_program()], {"write_log": False})
        self.assertIn("programs", r)

    def test_has_aggregate_key(self):
        r = self.scorer.score([_make_program()], {"write_log": False})
        self.assertIn("aggregate", r)

    def test_has_scored_at_key(self):
        r = self.scorer.score([_make_program()], {"write_log": False})
        self.assertIn("scored_at", r)

    def test_programs_is_list(self):
        r = self.scorer.score([_make_program()], {"write_log": False})
        self.assertIsInstance(r["programs"], list)

    def test_programs_length_matches_input(self):
        r = self.scorer.score([_make_program("A"), _make_program("B")], {"write_log": False})
        self.assertEqual(len(r["programs"]), 2)

    def test_scored_at_is_string(self):
        r = self.scorer.score([_make_program()], {"write_log": False})
        self.assertIsInstance(r["scored_at"], str)

    def test_scored_at_ends_with_z(self):
        r = self.scorer.score([_make_program()], {"write_log": False})
        self.assertTrue(r["scored_at"].endswith("Z"))

    def test_empty_programs_returns_error(self):
        r = self.scorer.score([], {"write_log": False})
        self.assertIn("error", r)

    def test_empty_programs_list_is_empty(self):
        r = self.scorer.score([], {"write_log": False})
        self.assertEqual(r["programs"], [])

    def test_empty_aggregate_on_empty_input(self):
        r = self.scorer.score([], {"write_log": False})
        self.assertEqual(r["aggregate"], {})


class TestPerProgramFields(unittest.TestCase):
    def setUp(self):
        self.scorer = ProtocolIncentiveSustainabilityScorer()
        self.result = self.scorer.score([_make_program()], {"write_log": False})
        self.p = self.result["programs"][0]

    def test_protocol_field_present(self):
        self.assertIn("protocol", self.p)

    def test_incentive_token_field_present(self):
        self.assertIn("incentive_token", self.p)

    def test_sustainability_ratio_present(self):
        self.assertIn("sustainability_ratio", self.p)

    def test_tvl_at_risk_usd_present(self):
        self.assertIn("tvl_at_risk_usd", self.p)

    def test_monthly_cash_burn_net_usd_present(self):
        self.assertIn("monthly_cash_burn_net_usd", self.p)

    def test_runway_months_present(self):
        self.assertIn("runway_months", self.p)

    def test_organic_tvl_ratio_pct_present(self):
        self.assertIn("organic_tvl_ratio_pct", self.p)

    def test_sustainability_label_present(self):
        self.assertIn("sustainability_label", self.p)

    def test_flags_present(self):
        self.assertIn("flags", self.p)

    def test_flags_is_list(self):
        self.assertIsInstance(self.p["flags"], list)

    def test_protocol_name_preserved(self):
        self.assertEqual(self.p["protocol"], "ProtoA")

    def test_incentive_token_preserved(self):
        self.assertEqual(self.p["incentive_token"], "TKN")


class TestSustainabilityRatio(unittest.TestCase):
    def setUp(self):
        self.scorer = ProtocolIncentiveSustainabilityScorer()

    def test_ratio_correct_budget_greater_than_revenue(self):
        p = _make_program(budget=2_000_000, revenue=1_000_000)
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["sustainability_ratio"], 0.5, places=5)

    def test_ratio_correct_revenue_greater_than_budget(self):
        p = _make_program(budget=500_000, revenue=2_000_000)
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["sustainability_ratio"], 4.0, places=5)

    def test_ratio_none_when_budget_zero(self):
        p = _make_program(budget=0, revenue=500_000)
        r = self.scorer.score([p], {"write_log": False})
        # sustainability_ratio is None (infinite)
        self.assertIsNone(r["programs"][0]["sustainability_ratio"])

    def test_ratio_zero_when_revenue_zero(self):
        p = _make_program(budget=1_000_000, revenue=0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["sustainability_ratio"], 0.0, places=5)


class TestTVLAtRisk(unittest.TestCase):
    def setUp(self):
        self.scorer = ProtocolIncentiveSustainabilityScorer()

    def test_tvl_at_risk_correct(self):
        """tvl_at_risk = incentive_tvl × (1 - retention/100)"""
        p = _make_program(inc_tvl=100_000_000, retention=60.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["tvl_at_risk_usd"], 40_000_000.0, places=0)

    def test_tvl_at_risk_zero_when_full_retention(self):
        p = _make_program(inc_tvl=100_000_000, retention=100.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["tvl_at_risk_usd"], 0.0, places=0)

    def test_tvl_at_risk_full_when_zero_retention(self):
        p = _make_program(inc_tvl=100_000_000, retention=0.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["tvl_at_risk_usd"], 100_000_000.0, places=0)


class TestCashBurnAndRunway(unittest.TestCase):
    def setUp(self):
        self.scorer = ProtocolIncentiveSustainabilityScorer()

    def test_cash_burn_positive_when_budget_gt_revenue(self):
        p = _make_program(budget=1_000_000, revenue=600_000)
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["monthly_cash_burn_net_usd"], 400_000.0, places=0)

    def test_cash_burn_negative_when_revenue_gt_budget(self):
        p = _make_program(budget=500_000, revenue=900_000)
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["monthly_cash_burn_net_usd"], -400_000.0, places=0)

    def test_runway_none_when_not_burning(self):
        """Revenue ≥ budget → no burn → runway = None (infinite)."""
        p = _make_program(budget=500_000, revenue=900_000, treasury=12.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertIsNone(r["programs"][0]["runway_months"])

    def test_runway_equals_treasury_when_burning(self):
        p = _make_program(budget=1_000_000, revenue=500_000, treasury=18.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["runway_months"], 18.0, places=2)


class TestOrganicTVLRatio(unittest.TestCase):
    def setUp(self):
        self.scorer = ProtocolIncentiveSustainabilityScorer()

    def test_organic_tvl_ratio_correct(self):
        p = _make_program(inc_tvl=20_000_000, org_tvl=80_000_000)
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["organic_tvl_ratio_pct"], 80.0, places=4)

    def test_organic_tvl_ratio_zero_when_all_incentive(self):
        p = _make_program(inc_tvl=100_000_000, org_tvl=0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["organic_tvl_ratio_pct"], 0.0, places=4)

    def test_organic_tvl_ratio_100_when_all_organic(self):
        p = _make_program(inc_tvl=0, org_tvl=100_000_000)
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["organic_tvl_ratio_pct"], 100.0, places=4)

    def test_organic_tvl_ratio_zero_when_no_tvl(self):
        p = _make_program(inc_tvl=0, org_tvl=0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["organic_tvl_ratio_pct"], 0.0, places=4)


class TestSustainabilityLabels(unittest.TestCase):
    def setUp(self):
        self.scorer = ProtocolIncentiveSustainabilityScorer()

    def test_self_sustaining_label(self):
        r = self.scorer.score([_self_sustaining()], {"write_log": False})
        self.assertEqual(r["programs"][0]["sustainability_label"], "SELF_SUSTAINING")

    def test_ponzi_flywheel_label(self):
        r = self.scorer.score([_ponzi()], {"write_log": False})
        self.assertEqual(r["programs"][0]["sustainability_label"], "PONZI_FLYWHEEL")

    def test_transition_phase_label(self):
        """sustainability_ratio 0.5–0.99 (budget > revenue but close)."""
        p = _make_program(budget=1_000_000, revenue=600_000, retention=50.0, treasury=12.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertEqual(r["programs"][0]["sustainability_label"], "TRANSITION_PHASE")

    def test_dependent_label(self):
        """ratio 0.1–0.49 AND treasury >= 6."""
        p = _make_program(budget=1_000_000, revenue=200_000, treasury=10.0, retention=40.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertEqual(r["programs"][0]["sustainability_label"], "DEPENDENT")

    def test_unsustainable_label_low_treasury(self):
        """ratio 0.1–0.49 AND treasury < 6."""
        p = _make_program(budget=1_000_000, revenue=200_000, treasury=4.0, retention=40.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertEqual(r["programs"][0]["sustainability_label"], "UNSUSTAINABLE")

    def test_self_sustaining_requires_both_conditions(self):
        """High revenue but low retention → NOT SELF_SUSTAINING."""
        p = _make_program(budget=500_000, revenue=800_000, retention=30.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertNotEqual(r["programs"][0]["sustainability_label"], "SELF_SUSTAINING")

    def test_self_sustaining_requires_revenue_gte_budget(self):
        """High retention but revenue < budget → NOT SELF_SUSTAINING."""
        p = _make_program(budget=1_000_000, revenue=800_000, retention=90.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertNotEqual(r["programs"][0]["sustainability_label"], "SELF_SUSTAINING")

    def test_label_is_string(self):
        r = self.scorer.score([_make_program()], {"write_log": False})
        self.assertIsInstance(r["programs"][0]["sustainability_label"], str)

    def test_unsustainable_high_ratio_low_treasury(self):
        """ratio >= 0.1, treasury < 6, no income surplus → UNSUSTAINABLE."""
        p = _make_program(budget=1_000_000, revenue=150_000, treasury=3.0, retention=50.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertEqual(r["programs"][0]["sustainability_label"], "UNSUSTAINABLE")


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.scorer = ProtocolIncentiveSustainabilityScorer()

    def test_treasury_runway_short_flag(self):
        """Treasury < 6 months AND burning cash."""
        p = _make_program(budget=1_000_000, revenue=500_000, treasury=4.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertIn("TREASURY_RUNWAY_SHORT", r["programs"][0]["flags"])

    def test_no_treasury_runway_short_when_treasury_ok(self):
        p = _make_program(budget=1_000_000, revenue=500_000, treasury=8.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertNotIn("TREASURY_RUNWAY_SHORT", r["programs"][0]["flags"])

    def test_no_treasury_runway_short_when_not_burning(self):
        p = _make_program(budget=500_000, revenue=900_000, treasury=4.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertNotIn("TREASURY_RUNWAY_SHORT", r["programs"][0]["flags"])

    def test_high_tvl_at_risk_flag(self):
        """at_risk > 50% total_tvl."""
        p = _make_program(inc_tvl=100_000_000, org_tvl=10_000_000, retention=0.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertIn("HIGH_TVL_AT_RISK", r["programs"][0]["flags"])

    def test_no_high_tvl_at_risk_when_low(self):
        p = _make_program(inc_tvl=10_000_000, org_tvl=200_000_000, retention=80.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertNotIn("HIGH_TVL_AT_RISK", r["programs"][0]["flags"])

    def test_organic_majority_flag(self):
        """organic_tvl > 50% total."""
        p = _make_program(inc_tvl=20_000_000, org_tvl=80_000_000)
        r = self.scorer.score([p], {"write_log": False})
        self.assertIn("ORGANIC_MAJORITY", r["programs"][0]["flags"])

    def test_no_organic_majority_when_incentive_dominates(self):
        p = _make_program(inc_tvl=80_000_000, org_tvl=20_000_000)
        r = self.scorer.score([p], {"write_log": False})
        self.assertNotIn("ORGANIC_MAJORITY", r["programs"][0]["flags"])

    def test_retention_risk_flag(self):
        """retention < 40%."""
        p = _make_program(retention=30.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertIn("RETENTION_RISK", r["programs"][0]["flags"])

    def test_no_retention_risk_when_retention_ok(self):
        p = _make_program(retention=50.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertNotIn("RETENTION_RISK", r["programs"][0]["flags"])

    def test_benchmark_worse_flag(self):
        """post_incentive_drop > 60%."""
        p = _make_program(benchmark_drop=75.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertIn("BENCHMARK_WORSE", r["programs"][0]["flags"])

    def test_no_benchmark_worse_when_drop_ok(self):
        p = _make_program(benchmark_drop=40.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertNotIn("BENCHMARK_WORSE", r["programs"][0]["flags"])

    def test_ponzi_flags_multiple(self):
        r = self.scorer.score([_ponzi()], {"write_log": False})
        flags = r["programs"][0]["flags"]
        # Ponzi should have TREASURY_RUNWAY_SHORT and RETENTION_RISK and BENCHMARK_WORSE
        self.assertIn("TREASURY_RUNWAY_SHORT", flags)
        self.assertIn("RETENTION_RISK", flags)
        self.assertIn("BENCHMARK_WORSE", flags)

    def test_flags_empty_for_clean_program(self):
        """Self-sustaining, equal organic/incentive TVL split, long runway.
        With inc_tvl==org_tvl the ORGANIC_MAJORITY flag is NOT set (50% is not >50%),
        and all other conditions are clean, so flags list should be empty.
        """
        p = _make_program(
            budget=500_000, revenue=1_000_000, retention=80.0,
            inc_tvl=50_000_000, org_tvl=50_000_000,
            treasury=24.0, benchmark_drop=20.0,
        )
        r = self.scorer.score([p], {"write_log": False})
        self.assertEqual(r["programs"][0]["flags"], [])


class TestAggregateMetrics(unittest.TestCase):
    def setUp(self):
        self.scorer = ProtocolIncentiveSustainabilityScorer()

    def test_aggregate_has_most_sustainable(self):
        r = self.scorer.score([_self_sustaining(), _ponzi()], {"write_log": False})
        self.assertIn("most_sustainable", r["aggregate"])

    def test_aggregate_has_least_sustainable(self):
        r = self.scorer.score([_self_sustaining(), _ponzi()], {"write_log": False})
        self.assertIn("least_sustainable", r["aggregate"])

    def test_aggregate_has_total_tvl_at_risk(self):
        r = self.scorer.score([_self_sustaining(), _ponzi()], {"write_log": False})
        self.assertIn("total_tvl_at_risk_usd", r["aggregate"])

    def test_aggregate_has_self_sustaining_count(self):
        r = self.scorer.score([_self_sustaining(), _ponzi()], {"write_log": False})
        self.assertIn("self_sustaining_count", r["aggregate"])

    def test_aggregate_has_ponzi_flywheel_count(self):
        r = self.scorer.score([_self_sustaining(), _ponzi()], {"write_log": False})
        self.assertIn("ponzi_flywheel_count", r["aggregate"])

    def test_aggregate_has_total_programs_scored(self):
        r = self.scorer.score([_self_sustaining(), _ponzi()], {"write_log": False})
        self.assertIn("total_programs_scored", r["aggregate"])

    def test_most_sustainable_is_self_sustaining(self):
        r = self.scorer.score([_self_sustaining(), _ponzi()], {"write_log": False})
        self.assertEqual(r["aggregate"]["most_sustainable"], "SelfSustaining")

    def test_least_sustainable_is_ponzi(self):
        r = self.scorer.score([_self_sustaining(), _ponzi()], {"write_log": False})
        self.assertEqual(r["aggregate"]["least_sustainable"], "Ponzi")

    def test_self_sustaining_count_correct(self):
        r = self.scorer.score([_self_sustaining(), _self_sustaining(), _ponzi()], {"write_log": False})
        self.assertEqual(r["aggregate"]["self_sustaining_count"], 2)

    def test_ponzi_flywheel_count_correct(self):
        r = self.scorer.score([_ponzi(), _ponzi()], {"write_log": False})
        self.assertEqual(r["aggregate"]["ponzi_flywheel_count"], 2)

    def test_total_tvl_at_risk_sum(self):
        p1 = _make_program("A", inc_tvl=100_000_000, retention=0.0)
        p2 = _make_program("B", inc_tvl=50_000_000, retention=0.0)
        r = self.scorer.score([p1, p2], {"write_log": False})
        self.assertAlmostEqual(r["aggregate"]["total_tvl_at_risk_usd"], 150_000_000.0, places=0)

    def test_total_programs_scored(self):
        r = self.scorer.score([_make_program("A"), _make_program("B"), _make_program("C")],
                              {"write_log": False})
        self.assertEqual(r["aggregate"]["total_programs_scored"], 3)


class TestLogFileWriting(unittest.TestCase):
    def setUp(self):
        self.scorer = ProtocolIncentiveSustainabilityScorer()
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "incentive_sustainability_log.json")

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.remove(self.log_path)
        os.rmdir(self.tmpdir)

    def test_log_file_created(self):
        self.scorer.score([_make_program()], {"write_log": True, "log_path": self.log_path})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_file_is_valid_json(self):
        self.scorer.score([_make_program()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_has_one_entry_after_one_call(self):
        self.scorer.score([_make_program()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_log_appends_on_second_call(self):
        cfg = {"write_log": True, "log_path": self.log_path}
        self.scorer.score([_make_program()], cfg)
        self.scorer.score([_make_program()], cfg)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap_at_100(self):
        cfg = {"write_log": True, "log_path": self.log_path}
        for _ in range(110):
            self.scorer.score([_make_program()], cfg)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)

    def test_no_log_when_write_log_false(self):
        self.scorer.score([_make_program()], {"write_log": False, "log_path": self.log_path})
        self.assertFalse(os.path.exists(self.log_path))

    def test_log_entry_has_programs_key(self):
        self.scorer.score([_make_program()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as fh:
            entry = json.load(fh)[0]
        self.assertIn("programs", entry)

    def test_log_entry_has_scored_at_key(self):
        self.scorer.score([_make_program()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as fh:
            entry = json.load(fh)[0]
        self.assertIn("scored_at", entry)

    def test_atomic_write_no_tmp_file_left(self):
        self.scorer.score([_make_program()], {"write_log": True, "log_path": self.log_path})
        tmp_files = [f for f in os.listdir(self.tmpdir) if f != os.path.basename(self.log_path)]
        self.assertEqual(tmp_files, [])

    def test_log_overwrite_bad_json_gracefully(self):
        with open(self.log_path, "w") as fh:
            fh.write("NOT JSON")
        self.scorer.score([_make_program()], {"write_log": True, "log_path": self.log_path})
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.scorer = ProtocolIncentiveSustainabilityScorer()

    def test_missing_optional_fields_handled(self):
        minimal = {"protocol": "Min"}
        r = self.scorer.score([minimal], {"write_log": False})
        self.assertEqual(len(r["programs"]), 1)

    def test_protocol_defaults_to_unknown(self):
        r = self.scorer.score([{}], {"write_log": False})
        self.assertEqual(r["programs"][0]["protocol"], "unknown")

    def test_numeric_strings_coerced(self):
        p = {"protocol": "X", "monthly_incentive_budget_usd": "1000000",
             "monthly_organic_revenue_usd": "500000"}
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["monthly_cash_burn_net_usd"], 500_000.0, places=0)

    def test_large_number_of_programs(self):
        programs = [_make_program(f"Proto{i}") for i in range(50)]
        r = self.scorer.score(programs, {"write_log": False})
        self.assertEqual(len(r["programs"]), 50)

    def test_config_none_uses_defaults(self):
        r = self.scorer.score([_make_program()], {"write_log": False})
        self.assertIn("programs", r)

    def test_all_zero_values(self):
        p = _make_program(budget=0, revenue=0, inc_tvl=0, org_tvl=0, treasury=0,
                          retention=0.0, benchmark_drop=0.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertEqual(len(r["programs"]), 1)

    def test_very_high_budget_ratio(self):
        p = _make_program(budget=100_000_000, revenue=1_000)
        r = self.scorer.score([p], {"write_log": False})
        self.assertAlmostEqual(r["programs"][0]["sustainability_ratio"], 0.00001, places=5)

    def test_incentive_token_defaults_to_unknown(self):
        r = self.scorer.score([{"protocol": "X"}], {"write_log": False})
        self.assertEqual(r["programs"][0]["incentive_token"], "UNKNOWN")

    def test_single_program_aggregate_has_same_most_and_least_sustainable(self):
        r = self.scorer.score([_make_program("Solo")], {"write_log": False})
        agg = r["aggregate"]
        self.assertEqual(agg["most_sustainable"], "Solo")
        self.assertEqual(agg["least_sustainable"], "Solo")


class TestScorerInstantiation(unittest.TestCase):
    def test_can_instantiate(self):
        s = ProtocolIncentiveSustainabilityScorer()
        self.assertIsNotNone(s)

    def test_can_call_multiple_times(self):
        s = ProtocolIncentiveSustainabilityScorer()
        for _ in range(5):
            r = s.score([_make_program()], {"write_log": False})
            self.assertIn("programs", r)

    def test_results_independent_per_call(self):
        s = ProtocolIncentiveSustainabilityScorer()
        r1 = s.score([_make_program("Alpha")], {"write_log": False})
        r2 = s.score([_make_program("Beta")], {"write_log": False})
        self.assertEqual(r1["programs"][0]["protocol"], "Alpha")
        self.assertEqual(r2["programs"][0]["protocol"], "Beta")


class TestBoundaryValues(unittest.TestCase):
    def setUp(self):
        self.scorer = ProtocolIncentiveSustainabilityScorer()

    def test_retention_exactly_40_no_risk_flag(self):
        """retention = 40.0 is not < 40 so no RETENTION_RISK flag."""
        p = _make_program(retention=40.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertNotIn("RETENTION_RISK", r["programs"][0]["flags"])

    def test_retention_exactly_70_needed_for_self_sustaining(self):
        """budget=500k, revenue=800k, retention=70 → SELF_SUSTAINING."""
        p = _make_program(budget=500_000, revenue=800_000, retention=70.0,
                          inc_tvl=10_000_000, org_tvl=90_000_000, treasury=24.0,
                          benchmark_drop=20.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertEqual(r["programs"][0]["sustainability_label"], "SELF_SUSTAINING")

    def test_treasury_exactly_6_no_short_flag_when_not_burning(self):
        """Not burning cash → no TREASURY_RUNWAY_SHORT regardless of treasury value."""
        p = _make_program(budget=500_000, revenue=900_000, treasury=6.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertNotIn("TREASURY_RUNWAY_SHORT", r["programs"][0]["flags"])

    def test_benchmark_exactly_60_no_worse_flag(self):
        """drop = 60.0 is not > 60 so no BENCHMARK_WORSE."""
        p = _make_program(benchmark_drop=60.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertNotIn("BENCHMARK_WORSE", r["programs"][0]["flags"])

    def test_organic_tvl_exactly_50pct_no_flag(self):
        """organic_tvl = 50% → not > 50 → no ORGANIC_MAJORITY flag."""
        p = _make_program(inc_tvl=50_000_000, org_tvl=50_000_000)
        r = self.scorer.score([p], {"write_log": False})
        self.assertNotIn("ORGANIC_MAJORITY", r["programs"][0]["flags"])

    def test_sustainability_ratio_exactly_05_is_transition(self):
        """ratio = 0.5 → TRANSITION_PHASE."""
        p = _make_program(budget=1_000_000, revenue=500_000, retention=50.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertEqual(r["programs"][0]["sustainability_label"], "TRANSITION_PHASE")

    def test_sustainability_ratio_exactly_01_with_long_treasury_is_dependent(self):
        """ratio = 0.1 exactly → DEPENDENT (if treasury >= 6)."""
        p = _make_program(budget=1_000_000, revenue=100_000, treasury=12.0, retention=30.0)
        r = self.scorer.score([p], {"write_log": False})
        self.assertEqual(r["programs"][0]["sustainability_label"], "DEPENDENT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
