"""
Tests for MP-1026: DeFiProtocolGovernanceProposalImpactScorer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_governance_proposal_impact_scorer
"""

import json
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from spa_core.analytics.defi_protocol_governance_proposal_impact_scorer import (
    DeFiProtocolGovernanceProposalImpactScorer,
    _compute_passage_probability,
    _compute_tvl_impact_ratio,
    _compute_urgency_score,
    _risk_category_score,
    _overall_impact_score,
    _impact_label,
    _compute_flags,
    _score_single,
    _compute_aggregates,
    _atomic_write,
    _append_log,
    RISK_CATEGORY_SCORES,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_proposal(**overrides):
    base = {
        "name": "Test Proposal",
        "protocol": "Aave",
        "proposal_type": "parameter_change",
        "description_keywords": ["rate", "adjustment"],
        "tvl_affected_usd": 10_000_000,
        "quorum_required_pct": 50.0,
        "current_votes_for_pct": 60.0,
        "current_votes_against_pct": 10.0,
        "days_to_vote_end": 5,
        "proposer_type": "dao",
        "historical_pass_rate_proposer": 0.7,
        "protocol_tvl_usd": 1_000_000_000,
        "emergency_proposal": False,
        "timelock_days": 2,
        "estimated_apy_impact_bps": None,
    }
    base.update(overrides)
    return base


def make_big_proposal(**overrides):
    """Proposal that triggers CRITICAL_PROPOSAL.
    Needs tvl_ratio > ~0.94 AND passage_prob near max (~0.924) to exceed impact>70.
    With tvl_ratio=0.96, passage_prob≈0.924, risk_cat=80: impact≈70.9 → CRITICAL.
    """
    p = make_proposal(
        tvl_affected_usd=960_000_000,    # 96% of 1B TVL
        protocol_tvl_usd=1_000_000_000,
        proposal_type="upgrade",
        current_votes_for_pct=100.0,     # maximise blend
        current_votes_against_pct=0.0,
        historical_pass_rate_proposer=1.0,
        quorum_required_pct=10.0,        # easy to meet → quorum_prox = 1
    )
    p.update(overrides)
    return p


# ── passage probability ────────────────────────────────────────────────────────

class TestPassageProbability(unittest.TestCase):

    def test_high_votes_gives_high_probability(self):
        p = make_proposal(current_votes_for_pct=90.0,
                          historical_pass_rate_proposer=0.9,
                          quorum_required_pct=20.0,
                          current_votes_against_pct=5.0)
        prob = _compute_passage_probability(p)
        self.assertGreater(prob, 0.7)

    def test_low_votes_gives_low_probability(self):
        p = make_proposal(current_votes_for_pct=5.0,
                          historical_pass_rate_proposer=0.1,
                          current_votes_against_pct=80.0)
        prob = _compute_passage_probability(p)
        self.assertLess(prob, 0.5)

    def test_probability_between_zero_and_one(self):
        for votes in [0, 25, 50, 75, 100]:
            p = make_proposal(current_votes_for_pct=float(votes))
            prob = _compute_passage_probability(p)
            self.assertGreaterEqual(prob, 0.0)
            self.assertLessEqual(prob, 1.0)

    def test_zero_quorum_handled(self):
        p = make_proposal(quorum_required_pct=0.0)
        prob = _compute_passage_probability(p)
        self.assertGreaterEqual(prob, 0.0)
        self.assertLessEqual(prob, 1.0)

    def test_perfect_hist_rate_increases_prob(self):
        p_low = make_proposal(historical_pass_rate_proposer=0.0)
        p_high = make_proposal(historical_pass_rate_proposer=1.0)
        self.assertGreater(_compute_passage_probability(p_high),
                           _compute_passage_probability(p_low))

    def test_default_proposal_reasonable_prob(self):
        p = make_proposal()
        prob = _compute_passage_probability(p)
        self.assertGreater(prob, 0.3)
        self.assertLess(prob, 1.0)

    def test_returns_float(self):
        p = make_proposal()
        self.assertIsInstance(_compute_passage_probability(p), float)

    def test_missing_fields_handled(self):
        p = {"name": "minimal"}
        prob = _compute_passage_probability(p)
        self.assertGreaterEqual(prob, 0.0)
        self.assertLessEqual(prob, 1.0)


# ── TVL impact ratio ──────────────────────────────────────────────────────────

class TestTVLImpactRatio(unittest.TestCase):

    def test_half_tvl_gives_half_ratio(self):
        p = make_proposal(tvl_affected_usd=500_000_000,
                          protocol_tvl_usd=1_000_000_000)
        self.assertAlmostEqual(_compute_tvl_impact_ratio(p), 0.5, places=3)

    def test_ratio_capped_at_one(self):
        p = make_proposal(tvl_affected_usd=2_000_000_000,
                          protocol_tvl_usd=1_000_000_000)
        self.assertEqual(_compute_tvl_impact_ratio(p), 1.0)

    def test_zero_affected_gives_zero(self):
        p = make_proposal(tvl_affected_usd=0)
        self.assertEqual(_compute_tvl_impact_ratio(p), 0.0)

    def test_zero_protocol_tvl_gives_zero(self):
        p = make_proposal(protocol_tvl_usd=0)
        self.assertEqual(_compute_tvl_impact_ratio(p), 0.0)

    def test_small_tvl_affected(self):
        # 100_000 / 1_000_000_000 = 0.0001, which survives 4-decimal rounding
        p = make_proposal(tvl_affected_usd=100_000, protocol_tvl_usd=1_000_000_000)
        ratio = _compute_tvl_impact_ratio(p)
        self.assertAlmostEqual(ratio, 0.0001, places=4)

    def test_returns_float(self):
        p = make_proposal()
        self.assertIsInstance(_compute_tvl_impact_ratio(p), float)

    def test_full_tvl_affected(self):
        p = make_proposal(tvl_affected_usd=1_000_000, protocol_tvl_usd=1_000_000)
        self.assertAlmostEqual(_compute_tvl_impact_ratio(p), 1.0, places=4)


# ── urgency score ─────────────────────────────────────────────────────────────

class TestUrgencyScore(unittest.TestCase):

    def test_emergency_adds_50(self):
        p = make_proposal(emergency_proposal=True, days_to_vote_end=10,
                          timelock_days=5)
        self.assertEqual(_compute_urgency_score(p), 50.0)

    def test_days_less_than_3_adds_30(self):
        p = make_proposal(emergency_proposal=False, days_to_vote_end=2,
                          timelock_days=5)
        self.assertEqual(_compute_urgency_score(p), 30.0)

    def test_no_timelock_adds_20(self):
        p = make_proposal(emergency_proposal=False, days_to_vote_end=10,
                          timelock_days=0)
        self.assertEqual(_compute_urgency_score(p), 20.0)

    def test_all_conditions_max_100(self):
        p = make_proposal(emergency_proposal=True, days_to_vote_end=1,
                          timelock_days=0)
        self.assertEqual(_compute_urgency_score(p), 100.0)

    def test_no_urgency_gives_zero(self):
        p = make_proposal(emergency_proposal=False, days_to_vote_end=10,
                          timelock_days=2)
        self.assertEqual(_compute_urgency_score(p), 0.0)

    def test_clamped_at_100(self):
        p = make_proposal(emergency_proposal=True, days_to_vote_end=1,
                          timelock_days=0)
        self.assertLessEqual(_compute_urgency_score(p), 100.0)

    def test_non_emergency_no_bonus(self):
        p = make_proposal(emergency_proposal=False, days_to_vote_end=7)
        self.assertLess(_compute_urgency_score(p), 100.0)

    def test_exactly_3_days_no_bonus(self):
        p = make_proposal(emergency_proposal=False, days_to_vote_end=3,
                          timelock_days=2)
        self.assertEqual(_compute_urgency_score(p), 0.0)


# ── risk category score ────────────────────────────────────────────────────────

class TestRiskCategoryScore(unittest.TestCase):

    def test_upgrade_is_80(self):
        p = make_proposal(proposal_type="upgrade")
        self.assertEqual(_risk_category_score(p), 80.0)

    def test_risk_parameter_is_70(self):
        p = make_proposal(proposal_type="risk_parameter")
        self.assertEqual(_risk_category_score(p), 70.0)

    def test_new_market_is_60(self):
        p = make_proposal(proposal_type="new_market")
        self.assertEqual(_risk_category_score(p), 60.0)

    def test_token_emission_is_50(self):
        p = make_proposal(proposal_type="token_emission")
        self.assertEqual(_risk_category_score(p), 50.0)

    def test_parameter_change_is_40(self):
        p = make_proposal(proposal_type="parameter_change")
        self.assertEqual(_risk_category_score(p), 40.0)

    def test_treasury_spend_is_40(self):
        p = make_proposal(proposal_type="treasury_spend")
        self.assertEqual(_risk_category_score(p), 40.0)

    def test_fee_change_is_30(self):
        p = make_proposal(proposal_type="fee_change")
        self.assertEqual(_risk_category_score(p), 30.0)

    def test_unknown_type_defaults_to_40(self):
        p = make_proposal(proposal_type="unknown_type")
        self.assertEqual(_risk_category_score(p), 40.0)

    def test_case_insensitive(self):
        p = make_proposal(proposal_type="UPGRADE")
        self.assertEqual(_risk_category_score(p), 80.0)

    def test_empty_type_defaults(self):
        p = make_proposal(proposal_type="")
        self.assertEqual(_risk_category_score(p), 40.0)


# ── overall impact score ──────────────────────────────────────────────────────

class TestOverallImpactScore(unittest.TestCase):

    def test_zero_passage_gives_zero(self):
        self.assertEqual(_overall_impact_score(0.0, 0.5, 80.0), 0.0)

    def test_zero_tvl_ratio_gives_zero(self):
        self.assertEqual(_overall_impact_score(0.9, 0.0, 80.0), 0.0)

    def test_product_formula(self):
        score = _overall_impact_score(0.8, 0.5, 80.0)
        expected = 0.8 * 0.5 * 80.0
        self.assertAlmostEqual(score, expected, places=2)

    def test_capped_at_100(self):
        score = _overall_impact_score(1.0, 1.0, 100.0)
        self.assertLessEqual(score, 100.0)

    def test_always_nonnegative(self):
        score = _overall_impact_score(0.5, 0.5, 50.0)
        self.assertGreaterEqual(score, 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_overall_impact_score(0.5, 0.5, 40.0), float)


# ── impact label ──────────────────────────────────────────────────────────────

class TestImpactLabel(unittest.TestCase):

    def test_critical_proposal_label(self):
        # impact > 70 AND tvl_ratio > 0.5
        label = _impact_label(75.0, 0.6, "upgrade")
        self.assertEqual(label, "CRITICAL_PROPOSAL")

    def test_high_impact_label(self):
        label = _impact_label(55.0, 0.3, "upgrade")
        self.assertEqual(label, "HIGH_IMPACT")

    def test_moderate_impact_label(self):
        label = _impact_label(30.0, 0.3, "upgrade")
        self.assertEqual(label, "MODERATE_IMPACT")

    def test_low_impact_label(self):
        label = _impact_label(12.0, 0.1, "fee_change")
        self.assertEqual(label, "LOW_IMPACT")

    def test_routine_for_parameter_change(self):
        label = _impact_label(5.0, 0.01, "parameter_change")
        self.assertEqual(label, "ROUTINE")

    def test_routine_for_near_zero_impact(self):
        label = _impact_label(1.0, 0.01, "fee_change")
        self.assertEqual(label, "ROUTINE")

    def test_critical_requires_large_tvl_ratio(self):
        # impact > 70 but tvl_ratio < 0.5 → not CRITICAL
        label = _impact_label(75.0, 0.3, "upgrade")
        self.assertNotEqual(label, "CRITICAL_PROPOSAL")

    def test_returns_string(self):
        label = _impact_label(50.0, 0.5, "upgrade")
        self.assertIsInstance(label, str)


# ── flags ────────────────────────────────────────────────────────────────────

class TestComputeFlags(unittest.TestCase):

    def test_emergency_governance_flag(self):
        p = make_proposal(emergency_proposal=True)
        flags = _compute_flags(p, 0.5, 0.1, 10_000_000)
        self.assertIn("EMERGENCY_GOVERNANCE", flags)

    def test_no_emergency_no_flag(self):
        p = make_proposal(emergency_proposal=False)
        flags = _compute_flags(p, 0.5, 0.1, 10_000_000)
        self.assertNotIn("EMERGENCY_GOVERNANCE", flags)

    def test_team_proposal_flag(self):
        p = make_proposal(proposer_type="team")
        flags = _compute_flags(p, 0.5, 0.1, 10_000_000)
        self.assertIn("TEAM_PROPOSAL", flags)

    def test_community_driven_flag(self):
        p = make_proposal(proposer_type="community")
        flags = _compute_flags(p, 0.5, 0.1, 10_000_000)
        self.assertIn("COMMUNITY_DRIVEN", flags)

    def test_likely_to_pass_flag(self):
        p = make_proposal()
        flags = _compute_flags(p, 0.8, 0.1, 10_000_000)
        self.assertIn("LIKELY_TO_PASS", flags)

    def test_not_likely_to_pass(self):
        p = make_proposal()
        flags = _compute_flags(p, 0.5, 0.1, 10_000_000)
        self.assertNotIn("LIKELY_TO_PASS", flags)

    def test_affects_large_tvl_flag(self):
        p = make_proposal()
        flags = _compute_flags(p, 0.5, 0.5, 150_000_000)
        self.assertIn("AFFECTS_LARGE_TVL", flags)

    def test_below_large_tvl_no_flag(self):
        p = make_proposal()
        flags = _compute_flags(p, 0.5, 0.5, 50_000_000)
        self.assertNotIn("AFFECTS_LARGE_TVL", flags)

    def test_no_timelock_risk_flag(self):
        p = make_proposal(proposal_type="upgrade", timelock_days=0)
        flags = _compute_flags(p, 0.5, 0.5, 10_000_000)
        self.assertIn("NO_TIMELOCK_RISK", flags)

    def test_no_timelock_risk_only_for_upgrade(self):
        p = make_proposal(proposal_type="fee_change", timelock_days=0)
        flags = _compute_flags(p, 0.5, 0.5, 10_000_000)
        self.assertNotIn("NO_TIMELOCK_RISK", flags)

    def test_returns_list(self):
        p = make_proposal()
        flags = _compute_flags(p, 0.5, 0.1, 10_000_000)
        self.assertIsInstance(flags, list)

    def test_empty_flags_when_none_apply(self):
        p = make_proposal(emergency_proposal=False, proposer_type="dao",
                          timelock_days=2, proposal_type="fee_change")
        flags = _compute_flags(p, 0.5, 0.1, 50_000_000)
        self.assertNotIn("EMERGENCY_GOVERNANCE", flags)
        self.assertNotIn("TEAM_PROPOSAL", flags)
        self.assertNotIn("COMMUNITY_DRIVEN", flags)


# ── score_single ──────────────────────────────────────────────────────────────

class TestScoreSingle(unittest.TestCase):

    def test_returns_dict(self):
        p = make_proposal()
        result = _score_single(p)
        self.assertIsInstance(result, dict)

    def test_contains_all_required_keys(self):
        p = make_proposal()
        result = _score_single(p)
        for key in ["name", "protocol", "proposal_type", "passage_probability",
                    "tvl_impact_ratio", "urgency_score", "risk_category_score",
                    "overall_impact_score", "impact_label", "flags",
                    "estimated_apy_impact_bps"]:
            self.assertIn(key, result)

    def test_name_preserved(self):
        p = make_proposal(name="My Proposal")
        result = _score_single(p)
        self.assertEqual(result["name"], "My Proposal")

    def test_protocol_preserved(self):
        p = make_proposal(protocol="Compound")
        result = _score_single(p)
        self.assertEqual(result["protocol"], "Compound")

    def test_apy_impact_preserved_when_set(self):
        p = make_proposal(estimated_apy_impact_bps=50)
        result = _score_single(p)
        self.assertEqual(result["estimated_apy_impact_bps"], 50)

    def test_apy_impact_none_when_not_set(self):
        p = make_proposal(estimated_apy_impact_bps=None)
        result = _score_single(p)
        self.assertIsNone(result["estimated_apy_impact_bps"])

    def test_upgrade_proposal_high_risk_score(self):
        p = make_proposal(proposal_type="upgrade")
        result = _score_single(p)
        self.assertEqual(result["risk_category_score"], 80.0)


# ── aggregates ────────────────────────────────────────────────────────────────

class TestComputeAggregates(unittest.TestCase):

    def _make_scored(self, impacts):
        return [
            {"overall_impact_score": imp, "impact_label": "ROUTINE" if imp < 5 else "HIGH_IMPACT",
             "name": f"P{i}", "protocol": "Aave"}
            for i, imp in enumerate(impacts)
        ]

    def test_empty_returns_nulls(self):
        agg = _compute_aggregates([])
        self.assertIsNone(agg["highest_impact"])
        self.assertIsNone(agg["lowest_impact"])
        self.assertEqual(agg["avg_impact_score"], 0.0)
        self.assertEqual(agg["critical_count"], 0)
        self.assertEqual(agg["routine_count"], 0)

    def test_single_item(self):
        scored = [{"overall_impact_score": 42.0, "impact_label": "HIGH_IMPACT",
                   "name": "P1", "protocol": "Aave"}]
        agg = _compute_aggregates(scored)
        self.assertEqual(agg["avg_impact_score"], 42.0)
        self.assertEqual(agg["highest_impact"]["name"], "P1")
        self.assertEqual(agg["lowest_impact"]["name"], "P1")

    def test_avg_correct(self):
        scored = self._make_scored([10.0, 20.0, 30.0])
        agg = _compute_aggregates(scored)
        self.assertAlmostEqual(agg["avg_impact_score"], 20.0, places=2)

    def test_highest_lowest_correct(self):
        scored = self._make_scored([10.0, 80.0, 30.0])
        agg = _compute_aggregates(scored)
        self.assertEqual(agg["highest_impact"]["overall_impact_score"], 80.0)
        self.assertEqual(agg["lowest_impact"]["overall_impact_score"], 10.0)

    def test_critical_count(self):
        scored = [
            {"overall_impact_score": 75.0, "impact_label": "CRITICAL_PROPOSAL",
             "name": "P1", "protocol": "A"},
            {"overall_impact_score": 10.0, "impact_label": "ROUTINE",
             "name": "P2", "protocol": "A"},
        ]
        agg = _compute_aggregates(scored)
        self.assertEqual(agg["critical_count"], 1)

    def test_routine_count(self):
        scored = [
            {"overall_impact_score": 5.0, "impact_label": "ROUTINE",
             "name": "P1", "protocol": "A"},
            {"overall_impact_score": 3.0, "impact_label": "ROUTINE",
             "name": "P2", "protocol": "A"},
        ]
        agg = _compute_aggregates(scored)
        self.assertEqual(agg["routine_count"], 2)


# ── main scorer class ─────────────────────────────────────────────────────────

class TestDeFiProtocolGovernanceProposalImpactScorer(unittest.TestCase):

    def setUp(self):
        self.scorer = DeFiProtocolGovernanceProposalImpactScorer()
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_governance_log.json")

    def _cfg(self):
        return {"log_path": self.log_path, "write_log": True}

    def test_returns_dict(self):
        result = self.scorer.score([make_proposal()], self._cfg())
        self.assertIsInstance(result, dict)

    def test_has_required_keys(self):
        result = self.scorer.score([make_proposal()], self._cfg())
        for key in ["ts", "proposal_count", "scored_proposals", "aggregates"]:
            self.assertIn(key, result)

    def test_empty_list_allowed(self):
        result = self.scorer.score([], {"log_path": self.log_path, "write_log": False})
        self.assertEqual(result["proposal_count"], 0)
        self.assertEqual(result["scored_proposals"], [])

    def test_proposal_count_matches_input(self):
        proposals = [make_proposal(name=f"P{i}") for i in range(5)]
        result = self.scorer.score(proposals, self._cfg())
        self.assertEqual(result["proposal_count"], 5)

    def test_non_list_raises_type_error(self):
        with self.assertRaises(TypeError):
            self.scorer.score({"invalid": "input"}, self._cfg())

    def test_log_written_after_score(self):
        self.scorer.score([make_proposal()], self._cfg())
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_json_list(self):
        self.scorer.score([make_proposal()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_ts(self):
        self.scorer.score([make_proposal()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("ts", data[-1])

    def test_log_ring_buffer_cap(self):
        for _ in range(LOG_CAP + 5):
            self.scorer.score([make_proposal()], self._cfg())
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), LOG_CAP)

    def test_write_log_false_does_not_write(self):
        cfg = {"log_path": self.log_path, "write_log": False}
        self.scorer.score([make_proposal()], cfg)
        self.assertFalse(os.path.exists(self.log_path))

    def test_scored_proposals_list_length(self):
        props = [make_proposal(name=f"P{i}") for i in range(3)]
        result = self.scorer.score(props, self._cfg())
        self.assertEqual(len(result["scored_proposals"]), 3)

    def test_ts_is_string(self):
        result = self.scorer.score([make_proposal()], self._cfg())
        self.assertIsInstance(result["ts"], str)

    def test_aggregates_present(self):
        result = self.scorer.score([make_proposal()], self._cfg())
        agg = result["aggregates"]
        self.assertIn("highest_impact", agg)
        self.assertIn("lowest_impact", agg)
        self.assertIn("avg_impact_score", agg)

    def test_upgrade_proposal_high_risk(self):
        p = make_proposal(proposal_type="upgrade",
                          tvl_affected_usd=200_000_000,
                          protocol_tvl_usd=300_000_000,
                          current_votes_for_pct=80.0,
                          historical_pass_rate_proposer=0.9)
        result = self.scorer.score([p], self._cfg())
        scored = result["scored_proposals"][0]
        self.assertEqual(scored["risk_category_score"], 80.0)

    def test_critical_proposal_scenario(self):
        p = make_big_proposal()
        result = self.scorer.score([p], self._cfg())
        scored = result["scored_proposals"][0]
        self.assertEqual(scored["impact_label"], "CRITICAL_PROPOSAL")

    def test_routine_scenario(self):
        p = make_proposal(
            proposal_type="parameter_change",
            tvl_affected_usd=1_000,
            protocol_tvl_usd=1_000_000_000,
            current_votes_for_pct=10.0,
            historical_pass_rate_proposer=0.1,
        )
        result = self.scorer.score([p], self._cfg())
        scored = result["scored_proposals"][0]
        self.assertEqual(scored["impact_label"], "ROUTINE")

    def test_emergency_flag_present(self):
        p = make_proposal(emergency_proposal=True)
        result = self.scorer.score([p], self._cfg())
        self.assertIn("EMERGENCY_GOVERNANCE", result["scored_proposals"][0]["flags"])

    def test_no_emergency_flag_absent(self):
        p = make_proposal(emergency_proposal=False)
        result = self.scorer.score([p], self._cfg())
        self.assertNotIn("EMERGENCY_GOVERNANCE", result["scored_proposals"][0]["flags"])

    def test_multiple_flags_can_be_set(self):
        p = make_proposal(
            emergency_proposal=True,
            proposer_type="team",
            tvl_affected_usd=200_000_000,
            current_votes_for_pct=85.0,
            historical_pass_rate_proposer=0.9,
        )
        result = self.scorer.score([p], self._cfg())
        flags = result["scored_proposals"][0]["flags"]
        self.assertIn("EMERGENCY_GOVERNANCE", flags)
        self.assertIn("TEAM_PROPOSAL", flags)

    def test_no_timelock_risk_flag(self):
        p = make_proposal(proposal_type="upgrade", timelock_days=0,
                          tvl_affected_usd=150_000_000)
        result = self.scorer.score([p], self._cfg())
        flags = result["scored_proposals"][0]["flags"]
        self.assertIn("NO_TIMELOCK_RISK", flags)
        self.assertIn("AFFECTS_LARGE_TVL", flags)

    def test_community_driven_flag(self):
        p = make_proposal(proposer_type="community")
        result = self.scorer.score([p], self._cfg())
        self.assertIn("COMMUNITY_DRIVEN", result["scored_proposals"][0]["flags"])

    def test_all_proposal_types_score(self):
        types = ["parameter_change", "fee_change", "upgrade", "treasury_spend",
                 "token_emission", "risk_parameter", "new_market"]
        for pt in types:
            p = make_proposal(proposal_type=pt)
            result = self.scorer.score([p], {"log_path": self.log_path, "write_log": False})
            self.assertIsNotNone(result["scored_proposals"][0]["impact_label"])

    def test_apy_impact_bps_in_output(self):
        p = make_proposal(estimated_apy_impact_bps=25)
        result = self.scorer.score([p], self._cfg())
        self.assertEqual(result["scored_proposals"][0]["estimated_apy_impact_bps"], 25)

    def test_passage_probability_in_output(self):
        p = make_proposal()
        result = self.scorer.score([p], self._cfg())
        prob = result["scored_proposals"][0]["passage_probability"]
        self.assertGreaterEqual(prob, 0.0)
        self.assertLessEqual(prob, 1.0)

    def test_urgency_score_in_output(self):
        p = make_proposal(emergency_proposal=True)
        result = self.scorer.score([p], self._cfg())
        self.assertGreaterEqual(result["scored_proposals"][0]["urgency_score"], 50.0)

    def test_multiple_proposals_aggregated(self):
        props = [
            make_big_proposal(),
            make_proposal(
                proposal_type="fee_change",
                tvl_affected_usd=100_000,
                protocol_tvl_usd=1_000_000_000,
                current_votes_for_pct=5.0,
                historical_pass_rate_proposer=0.1,
            )
        ]
        result = self.scorer.score(props, self._cfg())
        agg = result["aggregates"]
        self.assertIsNotNone(agg["highest_impact"])
        self.assertIsNotNone(agg["lowest_impact"])
        self.assertGreater(
            agg["highest_impact"]["overall_impact_score"],
            agg["lowest_impact"]["overall_impact_score"]
        )

    def test_default_config_none(self):
        # Should not raise even with no config (uses default LOG_FILE path)
        scorer = DeFiProtocolGovernanceProposalImpactScorer()
        # Just verify it doesn't raise a TypeError
        result = scorer.score([], {"log_path": self.log_path, "write_log": False})
        self.assertIsNotNone(result)

    def test_likely_to_pass_flag_scenario(self):
        p = make_proposal(
            current_votes_for_pct=90.0,
            historical_pass_rate_proposer=0.95,
            quorum_required_pct=20.0,
        )
        result = self.scorer.score([p], self._cfg())
        flags = result["scored_proposals"][0]["flags"]
        self.assertIn("LIKELY_TO_PASS", flags)

    def test_overall_impact_zero_for_zero_tvl(self):
        p = make_proposal(tvl_affected_usd=0, protocol_tvl_usd=1_000_000_000)
        result = self.scorer.score([p], self._cfg())
        self.assertEqual(result["scored_proposals"][0]["overall_impact_score"], 0.0)


# ── atomic write ──────────────────────────────────────────────────────────────

class TestAtomicWrite(unittest.TestCase):

    def test_file_written(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"a": 1})
            self.assertTrue(os.path.exists(path))

    def test_content_correct(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, [1, 2, 3])
            with open(path) as f:
                self.assertEqual(json.load(f), [1, 2, 3])

    def test_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"v": 1})
            _atomic_write(path, {"v": 2})
            with open(path) as f:
                self.assertEqual(json.load(f)["v"], 2)


# ── append log ────────────────────────────────────────────────────────────────

class TestAppendLog(unittest.TestCase):

    def test_log_created(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            _append_log({"proposal_count": 1, "aggregates": {"avg_impact_score": 5.0,
                          "critical_count": 0, "routine_count": 1}}, path)
            self.assertTrue(os.path.exists(path))

    def test_log_grows(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(5):
                _append_log({"proposal_count": 1,
                             "aggregates": {"avg_impact_score": 1.0,
                                            "critical_count": 0,
                                            "routine_count": 0}}, path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 5)

    def test_ring_buffer_capped(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            for _ in range(LOG_CAP + 10):
                _append_log({"proposal_count": 1,
                             "aggregates": {"avg_impact_score": 1.0,
                                            "critical_count": 0,
                                            "routine_count": 0}}, path)
            with open(path) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), LOG_CAP)


if __name__ == "__main__":
    unittest.main()
