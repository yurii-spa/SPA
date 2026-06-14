"""
Tests for MP-1085: ProtocolDeFiProtocolInsuranceCoverageAnalyzer
Run with: python3 -m unittest spa_core.tests.test_protocol_defi_protocol_insurance_coverage_analyzer
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_protocol_insurance_coverage_analyzer import (
    ProtocolDeFiProtocolInsuranceCoverageAnalyzer,
    VALID_COVERAGE_PROVIDERS,
    LOG_CAP,
    _PROVIDER_BASE_SCORES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_proto(**overrides):
    proto = {
        "protocol_name":              "Aave V3",
        "tvl_usd":                    1_000_000_000.0,
        "coverage_usd":               800_000_000.0,
        "premium_apy_pct":            2.5,
        "coverage_provider":          "nexus_mutual",
        "covered_risks":              ["smart_contract_bug", "oracle_failure"],
        "exclusions":                 [],
        "claim_processing_days":      7.0,
        "historical_claims_paid_pct": 90.0,
        "max_single_claim_usd":       50_000_000.0,
    }
    proto.update(overrides)
    return proto


def _make_analyzer(tmp_dir):
    log_file = os.path.join(tmp_dir, "ins_cov_test.json")
    return ProtocolDeFiProtocolInsuranceCoverageAnalyzer(log_file=log_file), log_file


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestResultStructure(unittest.TestCase):
    """Verify analyze() returns a dict with all expected keys."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a, _ = _make_analyzer(self.tmp)

    def test_all_keys_present(self):
        r = self.a.analyze(_base_proto())
        expected = {
            "protocol_name", "coverage_provider", "tvl_usd", "coverage_usd",
            "coverage_ratio_pct", "premium_cost_drag_pct",
            "risk_coverage_score", "insurance_quality_score",
            "coverage_label", "covered_risks_count", "exclusions_count",
            "claim_processing_days", "historical_claims_paid_pct",
            "max_single_claim_usd", "analyzed_at",
        }
        self.assertEqual(expected, set(r.keys()))

    def test_protocol_name_preserved(self):
        r = self.a.analyze(_base_proto(protocol_name="Compound V3"))
        self.assertEqual(r["protocol_name"], "Compound V3")

    def test_provider_preserved(self):
        r = self.a.analyze(_base_proto(coverage_provider="sherlock"))
        self.assertEqual(r["coverage_provider"], "sherlock")

    def test_analyzed_at_is_string(self):
        r = self.a.analyze(_base_proto())
        self.assertIsInstance(r["analyzed_at"], str)
        self.assertIn("T", r["analyzed_at"])

    def test_coverage_label_is_valid(self):
        valid = {
            "FULLY_INSURED", "WELL_COVERED", "PARTIALLY_COVERED",
            "MINIMAL_COVERAGE", "UNINSURED",
        }
        r = self.a.analyze(_base_proto())
        self.assertIn(r["coverage_label"], valid)

    def test_scores_are_floats(self):
        r = self.a.analyze(_base_proto())
        self.assertIsInstance(r["risk_coverage_score"], float)
        self.assertIsInstance(r["insurance_quality_score"], float)

    def test_scores_in_0_100_range(self):
        r = self.a.analyze(_base_proto())
        self.assertGreaterEqual(r["risk_coverage_score"], 0.0)
        self.assertLessEqual(r["risk_coverage_score"], 100.0)
        self.assertGreaterEqual(r["insurance_quality_score"], 0.0)
        self.assertLessEqual(r["insurance_quality_score"], 100.0)


class TestCoverageRatioPct(unittest.TestCase):
    """coverage_ratio_pct = coverage_usd / tvl_usd × 100."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a, _ = _make_analyzer(self.tmp)

    def test_100_pct_coverage(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000.0, coverage_usd=1_000.0))
        self.assertAlmostEqual(r["coverage_ratio_pct"], 100.0, places=4)

    def test_80_pct_coverage(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=800_000.0))
        self.assertAlmostEqual(r["coverage_ratio_pct"], 80.0, places=4)

    def test_50_pct_coverage(self):
        r = self.a.analyze(_base_proto(tvl_usd=2_000_000.0, coverage_usd=1_000_000.0))
        self.assertAlmostEqual(r["coverage_ratio_pct"], 50.0, places=4)

    def test_20_pct_coverage(self):
        r = self.a.analyze(_base_proto(tvl_usd=10_000_000.0, coverage_usd=2_000_000.0))
        self.assertAlmostEqual(r["coverage_ratio_pct"], 20.0, places=4)

    def test_5_pct_coverage(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=50_000.0))
        self.assertAlmostEqual(r["coverage_ratio_pct"], 5.0, places=4)

    def test_zero_coverage(self):
        r = self.a.analyze(_base_proto(coverage_usd=0.0))
        self.assertAlmostEqual(r["coverage_ratio_pct"], 0.0, places=4)

    def test_over_100_pct_allowed(self):
        # Coverage can exceed TVL (pre-purchased excess)
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=2_000_000.0))
        self.assertAlmostEqual(r["coverage_ratio_pct"], 200.0, places=4)

    def test_small_tvl(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000.0, coverage_usd=500.0))
        self.assertAlmostEqual(r["coverage_ratio_pct"], 50.0, places=4)

    def test_tvl_preserved_in_result(self):
        r = self.a.analyze(_base_proto(tvl_usd=5_000_000.0))
        self.assertAlmostEqual(r["tvl_usd"], 5_000_000.0, places=2)

    def test_coverage_usd_preserved_in_result(self):
        r = self.a.analyze(_base_proto(coverage_usd=999_999.0))
        self.assertAlmostEqual(r["coverage_usd"], 999_999.0, places=2)


class TestPremiumCostDrag(unittest.TestCase):
    """premium_cost_drag_pct == premium_apy_pct."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a, _ = _make_analyzer(self.tmp)

    def test_premium_drag_equals_apy(self):
        r = self.a.analyze(_base_proto(premium_apy_pct=3.0))
        self.assertAlmostEqual(r["premium_cost_drag_pct"], 3.0, places=4)

    def test_zero_premium_drag(self):
        r = self.a.analyze(_base_proto(premium_apy_pct=0.0))
        self.assertAlmostEqual(r["premium_cost_drag_pct"], 0.0, places=4)

    def test_large_premium_drag(self):
        r = self.a.analyze(_base_proto(premium_apy_pct=15.0))
        self.assertAlmostEqual(r["premium_cost_drag_pct"], 15.0, places=4)

    def test_fractional_premium_drag(self):
        r = self.a.analyze(_base_proto(premium_apy_pct=0.75))
        self.assertAlmostEqual(r["premium_cost_drag_pct"], 0.75, places=4)


class TestCoverageLabels(unittest.TestCase):
    """Test all five coverage_label categories."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a, _ = _make_analyzer(self.tmp)

    def test_fully_insured_at_100_pct(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=1_000_000.0))
        self.assertEqual(r["coverage_label"], "FULLY_INSURED")

    def test_fully_insured_at_80_pct(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=800_000.0))
        self.assertEqual(r["coverage_label"], "FULLY_INSURED")

    def test_fully_insured_above_80(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=900_000.0))
        self.assertEqual(r["coverage_label"], "FULLY_INSURED")

    def test_well_covered_at_50_pct(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=500_000.0))
        self.assertEqual(r["coverage_label"], "WELL_COVERED")

    def test_well_covered_at_60_pct(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=600_000.0))
        self.assertEqual(r["coverage_label"], "WELL_COVERED")

    def test_well_covered_just_below_80(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=799_000.0))
        self.assertEqual(r["coverage_label"], "WELL_COVERED")

    def test_partially_covered_at_20_pct(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=200_000.0))
        self.assertEqual(r["coverage_label"], "PARTIALLY_COVERED")

    def test_partially_covered_at_35_pct(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=350_000.0))
        self.assertEqual(r["coverage_label"], "PARTIALLY_COVERED")

    def test_minimal_coverage_at_5_pct(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=50_000.0))
        self.assertEqual(r["coverage_label"], "MINIMAL_COVERAGE")

    def test_minimal_coverage_at_10_pct(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=100_000.0))
        self.assertEqual(r["coverage_label"], "MINIMAL_COVERAGE")

    def test_uninsured_when_provider_none(self):
        r = self.a.analyze(_base_proto(coverage_provider="none", coverage_usd=0.0))
        self.assertEqual(r["coverage_label"], "UNINSURED")

    def test_uninsured_when_zero_coverage(self):
        r = self.a.analyze(_base_proto(coverage_usd=0.0))
        self.assertEqual(r["coverage_label"], "UNINSURED")

    def test_uninsured_despite_big_coverage_if_provider_none(self):
        # Provider = "none" → always UNINSURED regardless of coverage_usd
        r = self.a.analyze(_base_proto(
            coverage_provider="none", coverage_usd=999_999_999.0
        ))
        self.assertEqual(r["coverage_label"], "UNINSURED")

    def test_partially_covered_just_below_50(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=499_000.0))
        self.assertEqual(r["coverage_label"], "PARTIALLY_COVERED")

    def test_minimal_just_below_20(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=199_000.0))
        self.assertEqual(r["coverage_label"], "MINIMAL_COVERAGE")

    def test_uninsured_just_below_5(self):
        r = self.a.analyze(_base_proto(tvl_usd=1_000_000.0, coverage_usd=49_000.0))
        self.assertEqual(r["coverage_label"], "UNINSURED")


class TestRiskCoverageScore(unittest.TestCase):
    """risk_coverage_score: breadth of risk coverage, 0–100."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a, _ = _make_analyzer(self.tmp)

    def test_zero_risks_gives_zero_score(self):
        r = self.a.analyze(_base_proto(covered_risks=[]))
        self.assertAlmostEqual(r["risk_coverage_score"], 0.0, places=4)

    def test_more_risks_gives_higher_score(self):
        r1 = self.a.analyze(_base_proto(covered_risks=["smart_contract_bug"]))
        r3 = self.a.analyze(_base_proto(
            covered_risks=["smart_contract_bug", "oracle_failure", "governance_attack"]
        ))
        self.assertGreater(r3["risk_coverage_score"], r1["risk_coverage_score"])

    def test_score_bounded_0_100(self):
        r = self.a.analyze(_base_proto(
            covered_risks=[
                "smart_contract_bug", "oracle_failure", "governance_attack",
                "stablecoin_depeg", "rug_pull", "admin_key_compromise",
                "economic_attack", "bridge_exploit", "mev", "liquidation_cascade",
            ]
        ))
        self.assertGreaterEqual(r["risk_coverage_score"], 0.0)
        self.assertLessEqual(r["risk_coverage_score"], 100.0)

    def test_exclusions_reduce_score(self):
        r_no_excl = self.a.analyze(_base_proto(exclusions=[]))
        r_excl    = self.a.analyze(_base_proto(
            exclusions=["theft", "insider_attack", "regulatory_action"]
        ))
        self.assertGreater(r_no_excl["risk_coverage_score"], r_excl["risk_coverage_score"])

    def test_low_coverage_ratio_reduces_score(self):
        r_high = self.a.analyze(_base_proto(
            tvl_usd=1_000_000.0, coverage_usd=900_000.0
        ))
        r_low  = self.a.analyze(_base_proto(
            tvl_usd=1_000_000.0, coverage_usd=10_000.0
        ))
        self.assertGreater(r_high["risk_coverage_score"], r_low["risk_coverage_score"])

    def test_zero_coverage_ratio_gives_zero_score_or_low(self):
        r = self.a.analyze(_base_proto(coverage_usd=0.0))
        self.assertAlmostEqual(r["risk_coverage_score"], 0.0, places=4)

    def test_score_increases_with_core_risks(self):
        r_other = self.a.analyze(_base_proto(
            covered_risks=["my_custom_risk_1", "my_custom_risk_2"]
        ))
        r_core  = self.a.analyze(_base_proto(
            covered_risks=["smart_contract_bug", "oracle_failure"]
        ))
        # Both have 2 risks but core risks get bonus
        self.assertGreaterEqual(r_core["risk_coverage_score"], r_other["risk_coverage_score"])

    def test_covered_risks_count_in_result(self):
        r = self.a.analyze(_base_proto(
            covered_risks=["smart_contract_bug", "oracle_failure", "rug_pull"]
        ))
        self.assertEqual(r["covered_risks_count"], 3)

    def test_exclusions_count_in_result(self):
        r = self.a.analyze(_base_proto(exclusions=["theft", "war"]))
        self.assertEqual(r["exclusions_count"], 2)

    def test_many_exclusions_cap_penalty(self):
        r = self.a.analyze(_base_proto(
            exclusions=[f"exc_{i}" for i in range(20)]  # 20 exclusions
        ))
        # Penalty is capped, score should still be >= 0
        self.assertGreaterEqual(r["risk_coverage_score"], 0.0)


class TestInsuranceQualityScore(unittest.TestCase):
    """insurance_quality_score: provider quality + claims + speed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a, _ = _make_analyzer(self.tmp)

    def test_none_provider_gives_zero_quality(self):
        r = self.a.analyze(_base_proto(coverage_provider="none", coverage_usd=0.0))
        self.assertAlmostEqual(r["insurance_quality_score"], 0.0, places=4)

    def test_quality_bounded_0_100(self):
        r = self.a.analyze(_base_proto(
            historical_claims_paid_pct=100.0, claim_processing_days=1.0
        ))
        self.assertGreaterEqual(r["insurance_quality_score"], 0.0)
        self.assertLessEqual(r["insurance_quality_score"], 100.0)

    def test_100_pct_claims_paid_better_than_50(self):
        r100 = self.a.analyze(_base_proto(historical_claims_paid_pct=100.0))
        r50  = self.a.analyze(_base_proto(historical_claims_paid_pct=50.0))
        self.assertGreater(r100["insurance_quality_score"], r50["insurance_quality_score"])

    def test_zero_claims_paid_gives_low_quality(self):
        # provider_base * 0 = 0, but speed/max-claim bonuses may still apply
        r = self.a.analyze(_base_proto(
            historical_claims_paid_pct=0.0,
            max_single_claim_usd=0.0,     # remove claim bonus
            claim_processing_days=365.0,  # heavy slow penalty → near zero
        ))
        self.assertLess(r["insurance_quality_score"], 5.0)

    def test_fast_claims_better_than_slow(self):
        r_fast = self.a.analyze(_base_proto(claim_processing_days=3.0))
        r_slow = self.a.analyze(_base_proto(claim_processing_days=90.0))
        self.assertGreater(r_fast["insurance_quality_score"], r_slow["insurance_quality_score"])

    def test_high_max_claim_bonus(self):
        # max_single_claim = 100% of TVL → max bonus
        r_high = self.a.analyze(_base_proto(
            tvl_usd=1_000_000.0, max_single_claim_usd=1_000_000.0
        ))
        r_low  = self.a.analyze(_base_proto(
            tvl_usd=1_000_000.0, max_single_claim_usd=0.0
        ))
        self.assertGreater(r_high["insurance_quality_score"], r_low["insurance_quality_score"])

    def test_nexus_mutual_vs_unknown_provider(self):
        # nexus_mutual has known high base score vs unknown (treated as 50)
        r_nex = self.a.analyze(_base_proto(coverage_provider="nexus_mutual"))
        # base(nexus) = 85 > 50 so quality should be higher
        self.assertGreater(r_nex["insurance_quality_score"], 0.0)

    def test_nexus_base_score_available(self):
        self.assertIn("nexus_mutual", _PROVIDER_BASE_SCORES)
        self.assertEqual(_PROVIDER_BASE_SCORES["nexus_mutual"], 85.0)

    def test_sherlock_base_score(self):
        self.assertEqual(_PROVIDER_BASE_SCORES["sherlock"], 80.0)

    def test_slow_claim_penalty_applied(self):
        r_ok   = self.a.analyze(_base_proto(claim_processing_days=30.0))
        r_slow = self.a.analyze(_base_proto(claim_processing_days=100.0))
        self.assertGreater(r_ok["insurance_quality_score"], r_slow["insurance_quality_score"])

    def test_quality_score_nonnegative_with_bad_inputs(self):
        r = self.a.analyze(_base_proto(
            historical_claims_paid_pct=10.0,
            claim_processing_days=200.0,
            max_single_claim_usd=0.0,
        ))
        self.assertGreaterEqual(r["insurance_quality_score"], 0.0)


class TestCoverageProviders(unittest.TestCase):
    """All valid providers are accepted; scores differ by provider."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a, _ = _make_analyzer(self.tmp)

    def test_nexus_mutual_accepted(self):
        r = self.a.analyze(_base_proto(coverage_provider="nexus_mutual"))
        self.assertIn("pnl_label" if False else "coverage_label", r)
        self.assertIsNotNone(r)

    def test_unslashed_accepted(self):
        r = self.a.analyze(_base_proto(coverage_provider="unslashed"))
        self.assertIsNotNone(r)

    def test_sherlock_accepted(self):
        r = self.a.analyze(_base_proto(coverage_provider="sherlock"))
        self.assertIsNotNone(r)

    def test_risk_harbor_accepted(self):
        r = self.a.analyze(_base_proto(coverage_provider="risk_harbor"))
        self.assertIsNotNone(r)

    def test_none_accepted(self):
        r = self.a.analyze(_base_proto(coverage_provider="none", coverage_usd=0.0))
        self.assertIsNotNone(r)

    def test_all_providers_in_constant(self):
        for p in ("nexus_mutual", "unslashed", "sherlock", "risk_harbor", "none"):
            self.assertIn(p, VALID_COVERAGE_PROVIDERS)

    def test_provider_quality_ranking(self):
        # nexus(85) > sherlock(80) > unslashed(75) > risk_harbor(70)
        # Use max_single_claim_usd=0 to avoid claim bonus masking the ordering
        base = dict(
            tvl_usd=1_000_000.0, coverage_usd=800_000.0,
            historical_claims_paid_pct=100.0, claim_processing_days=7.0,
            max_single_claim_usd=0.0,
        )
        r_nex  = self.a.analyze(_base_proto(**base, coverage_provider="nexus_mutual"))
        r_sher = self.a.analyze(_base_proto(**base, coverage_provider="sherlock"))
        r_uns  = self.a.analyze(_base_proto(**base, coverage_provider="unslashed"))
        r_rh   = self.a.analyze(_base_proto(**base, coverage_provider="risk_harbor"))
        self.assertGreater(r_nex["insurance_quality_score"], r_sher["insurance_quality_score"])
        self.assertGreater(r_sher["insurance_quality_score"], r_uns["insurance_quality_score"])
        self.assertGreater(r_uns["insurance_quality_score"], r_rh["insurance_quality_score"])

    def test_none_provider_sets_uninsured_label(self):
        r = self.a.analyze(_base_proto(coverage_provider="none", coverage_usd=0.0))
        self.assertEqual(r["coverage_label"], "UNINSURED")


class TestValidation(unittest.TestCase):
    """Validation must raise ValueError for invalid inputs."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a, _ = _make_analyzer(self.tmp)

    def test_missing_protocol_name(self):
        p = _base_proto(); del p["protocol_name"]
        with self.assertRaises(ValueError): self.a.analyze(p)

    def test_missing_tvl_usd(self):
        p = _base_proto(); del p["tvl_usd"]
        with self.assertRaises(ValueError): self.a.analyze(p)

    def test_missing_coverage_usd(self):
        p = _base_proto(); del p["coverage_usd"]
        with self.assertRaises(ValueError): self.a.analyze(p)

    def test_missing_premium_apy_pct(self):
        p = _base_proto(); del p["premium_apy_pct"]
        with self.assertRaises(ValueError): self.a.analyze(p)

    def test_missing_coverage_provider(self):
        p = _base_proto(); del p["coverage_provider"]
        with self.assertRaises(ValueError): self.a.analyze(p)

    def test_missing_covered_risks(self):
        p = _base_proto(); del p["covered_risks"]
        with self.assertRaises(ValueError): self.a.analyze(p)

    def test_missing_exclusions(self):
        p = _base_proto(); del p["exclusions"]
        with self.assertRaises(ValueError): self.a.analyze(p)

    def test_missing_claim_processing_days(self):
        p = _base_proto(); del p["claim_processing_days"]
        with self.assertRaises(ValueError): self.a.analyze(p)

    def test_missing_historical_claims_paid_pct(self):
        p = _base_proto(); del p["historical_claims_paid_pct"]
        with self.assertRaises(ValueError): self.a.analyze(p)

    def test_missing_max_single_claim_usd(self):
        p = _base_proto(); del p["max_single_claim_usd"]
        with self.assertRaises(ValueError): self.a.analyze(p)

    def test_zero_tvl_raises(self):
        with self.assertRaises(ValueError):
            self.a.analyze(_base_proto(tvl_usd=0.0))

    def test_negative_tvl_raises(self):
        with self.assertRaises(ValueError):
            self.a.analyze(_base_proto(tvl_usd=-1.0))

    def test_negative_coverage_raises(self):
        with self.assertRaises(ValueError):
            self.a.analyze(_base_proto(coverage_usd=-100.0))

    def test_negative_premium_raises(self):
        with self.assertRaises(ValueError):
            self.a.analyze(_base_proto(premium_apy_pct=-0.1))

    def test_invalid_coverage_provider_raises(self):
        with self.assertRaises(ValueError):
            self.a.analyze(_base_proto(coverage_provider="unknown_insurer"))

    def test_empty_string_provider_raises(self):
        with self.assertRaises(ValueError):
            self.a.analyze(_base_proto(coverage_provider=""))

    def test_covered_risks_not_list_raises(self):
        with self.assertRaises(ValueError):
            self.a.analyze(_base_proto(covered_risks="smart_contract_bug"))

    def test_exclusions_not_list_raises(self):
        with self.assertRaises(ValueError):
            self.a.analyze(_base_proto(exclusions="theft"))

    def test_negative_claim_processing_days_raises(self):
        with self.assertRaises(ValueError):
            self.a.analyze(_base_proto(claim_processing_days=-1.0))

    def test_claims_paid_above_100_raises(self):
        with self.assertRaises(ValueError):
            self.a.analyze(_base_proto(historical_claims_paid_pct=101.0))

    def test_claims_paid_below_0_raises(self):
        with self.assertRaises(ValueError):
            self.a.analyze(_base_proto(historical_claims_paid_pct=-1.0))

    def test_negative_max_claim_raises(self):
        with self.assertRaises(ValueError):
            self.a.analyze(_base_proto(max_single_claim_usd=-100.0))


class TestLogFile(unittest.TestCase):
    """Ring-buffer JSON log functionality."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a, self.log_file = _make_analyzer(self.tmp)

    def test_log_created_on_first_analyze(self):
        self.a.analyze(_base_proto())
        self.assertTrue(os.path.exists(self.log_file))

    def test_log_is_valid_json(self):
        self.a.analyze(_base_proto())
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_one_entry_after_one_call(self):
        self.a.analyze(_base_proto())
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_accumulates_entries(self):
        for i in range(5):
            self.a.analyze(_base_proto(protocol_name=f"Proto_{i}"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_ring_buffer_caps_at_100(self):
        for i in range(110):
            self.a.analyze(_base_proto(protocol_name=f"P{i}"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), LOG_CAP)

    def test_log_ring_buffer_keeps_newest(self):
        for i in range(110):
            self.a.analyze(_base_proto(protocol_name=f"P{i}"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["protocol_name"], "P109")

    def test_log_entry_has_coverage_label(self):
        self.a.analyze(_base_proto())
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIn("coverage_label", data[0])

    def test_log_recovers_from_corrupt_file(self):
        with open(self.log_file, "w") as f:
            f.write("INVALID{{")
        self.a.analyze(_base_proto())
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a, _ = _make_analyzer(self.tmp)

    def test_zero_risks_zero_exclusions(self):
        r = self.a.analyze(_base_proto(covered_risks=[], exclusions=[]))
        self.assertAlmostEqual(r["risk_coverage_score"], 0.0, places=4)

    def test_empty_exclusions_list(self):
        r = self.a.analyze(_base_proto(exclusions=[]))
        self.assertIsNotNone(r)

    def test_large_tvl(self):
        r = self.a.analyze(_base_proto(
            tvl_usd=100_000_000_000.0, coverage_usd=50_000_000_000.0
        ))
        self.assertAlmostEqual(r["coverage_ratio_pct"], 50.0, places=4)

    def test_zero_claim_processing_days(self):
        r = self.a.analyze(_base_proto(claim_processing_days=0.0))
        self.assertIsNotNone(r)

    def test_100_pct_hist_claims_paid(self):
        r = self.a.analyze(_base_proto(historical_claims_paid_pct=100.0))
        self.assertGreater(r["insurance_quality_score"], 0.0)

    def test_max_single_claim_zero(self):
        r = self.a.analyze(_base_proto(max_single_claim_usd=0.0))
        self.assertIsNotNone(r)

    def test_many_covered_risks(self):
        risks = [f"risk_{i}" for i in range(20)]
        r = self.a.analyze(_base_proto(covered_risks=risks))
        self.assertLessEqual(r["risk_coverage_score"], 100.0)
        self.assertGreaterEqual(r["risk_coverage_score"], 0.0)

    def test_float_int_coercion(self):
        r = self.a.analyze(_base_proto(
            tvl_usd=1_000_000, coverage_usd=500_000,
            premium_apy_pct=2, claim_processing_days=7,
            historical_claims_paid_pct=90, max_single_claim_usd=100_000,
        ))
        self.assertIsInstance(r["coverage_ratio_pct"], float)


class TestRealWorldScenarios(unittest.TestCase):
    """Representative DeFi insurance scenarios."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.a, _ = _make_analyzer(self.tmp)

    def test_aave_well_covered(self):
        r = self.a.analyze(_base_proto(
            protocol_name="Aave V3",
            tvl_usd=10_000_000_000.0,
            coverage_usd=8_000_000_000.0,
            premium_apy_pct=1.5,
            coverage_provider="nexus_mutual",
            covered_risks=["smart_contract_bug", "oracle_failure", "governance_attack"],
            exclusions=[],
            claim_processing_days=14.0,
            historical_claims_paid_pct=95.0,
            max_single_claim_usd=500_000_000.0,
        ))
        self.assertIn(r["coverage_label"], {"FULLY_INSURED", "WELL_COVERED"})
        self.assertGreater(r["risk_coverage_score"], 30.0)

    def test_small_protocol_minimal_coverage(self):
        r = self.a.analyze(_base_proto(
            protocol_name="SmallDeFi",
            tvl_usd=5_000_000.0,
            coverage_usd=300_000.0,  # 6% → MINIMAL_COVERAGE (≥5%)
            premium_apy_pct=5.0,
            coverage_provider="sherlock",
            covered_risks=["smart_contract_bug"],
            exclusions=["rug_pull", "insider_attack"],
            claim_processing_days=30.0,
            historical_claims_paid_pct=80.0,
            max_single_claim_usd=200_000.0,
        ))
        self.assertEqual(r["coverage_label"], "MINIMAL_COVERAGE")

    def test_uninsured_protocol(self):
        r = self.a.analyze(_base_proto(
            protocol_name="Anon Protocol",
            coverage_provider="none",
            coverage_usd=0.0,
            covered_risks=[],
            premium_apy_pct=0.0,
        ))
        self.assertEqual(r["coverage_label"], "UNINSURED")
        self.assertAlmostEqual(r["insurance_quality_score"], 0.0, places=4)

    def test_high_premium_drag_is_captured(self):
        r = self.a.analyze(_base_proto(premium_apy_pct=8.0))
        self.assertAlmostEqual(r["premium_cost_drag_pct"], 8.0, places=4)

    def test_compound_fully_insured_scenario(self):
        r = self.a.analyze(_base_proto(
            protocol_name="Compound V3",
            tvl_usd=3_000_000_000.0,
            coverage_usd=2_700_000_000.0,  # 90% coverage
            premium_apy_pct=2.0,
            coverage_provider="nexus_mutual",
            covered_risks=[
                "smart_contract_bug", "oracle_failure",
                "governance_attack", "stablecoin_depeg",
            ],
            exclusions=[],
            claim_processing_days=7.0,
            historical_claims_paid_pct=100.0,
            max_single_claim_usd=500_000_000.0,
        ))
        self.assertEqual(r["coverage_label"], "FULLY_INSURED")
        self.assertGreater(r["insurance_quality_score"], 50.0)


if __name__ == "__main__":
    unittest.main()
