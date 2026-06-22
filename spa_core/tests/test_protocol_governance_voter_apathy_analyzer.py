#!/usr/bin/env python3
"""Tests for ProtocolGovernanceVoterApathyAnalyzer (MP-967).

Run with:
    python3 -m unittest spa_core.tests.test_protocol_governance_voter_apathy_analyzer -v
"""
import json
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from spa_core.analytics.protocol_governance_voter_apathy_analyzer import (
    ProtocolGovernanceVoterApathyAnalyzer,
    write_log,
    LABEL_ENGAGED,
    LABEL_MODERATE,
    LABEL_APATHETIC,
    LABEL_CRITICALLY_APATHETIC,
    LABEL_ZOMBIE,
    LOG_FILE,
    LOG_CAP,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _prop(
    protocol="Aave",
    proposal_id="AIP-1",
    title="Test Proposal",
    total_eligible=100_000,
    votes_cast=50_000,
    votes_for=80.0,
    votes_against=20.0,
    quorum_required=30.0,
    quorum_reached=True,
    proposal_type="param_change",
    days_period=7.0,
    proposer_vp=2.0,
    top_voter_vp=15.0,
    outcome="passed",
):
    return {
        "protocol": protocol,
        "proposal_id": proposal_id,
        "title": title,
        "total_eligible_voters": total_eligible,
        "votes_cast": votes_cast,
        "votes_for_pct": votes_for,
        "votes_against_pct": votes_against,
        "quorum_required_pct": quorum_required,
        "quorum_reached": quorum_reached,
        "proposal_type": proposal_type,
        "days_voting_period": days_period,
        "proposer_vp_pct": proposer_vp,
        "top_voter_vp_pct": top_voter_vp,
        "outcome": outcome,
    }


class TestParticipationRate(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolGovernanceVoterApathyAnalyzer()

    def test_participation_rate_50_pct(self):
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=50_000)], {})
        self.assertAlmostEqual(r["proposals"][0]["participation_rate_pct"], 50.0, places=4)

    def test_participation_rate_zero(self):
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=0)], {})
        self.assertAlmostEqual(r["proposals"][0]["participation_rate_pct"], 0.0, places=4)

    def test_participation_rate_100_pct(self):
        r = self.a.analyze([_prop(total_eligible=1000, votes_cast=1000)], {})
        self.assertAlmostEqual(r["proposals"][0]["participation_rate_pct"], 100.0, places=4)

    def test_participation_rate_fractional(self):
        r = self.a.analyze([_prop(total_eligible=3, votes_cast=1)], {})
        self.assertAlmostEqual(r["proposals"][0]["participation_rate_pct"], 33.3333, places=2)

    def test_participation_rate_with_zero_eligible(self):
        r = self.a.analyze([_prop(total_eligible=0, votes_cast=0)], {})
        self.assertAlmostEqual(r["proposals"][0]["participation_rate_pct"], 0.0, places=4)

    def test_participation_rate_is_float(self):
        r = self.a.analyze([_prop()], {})
        self.assertIsInstance(r["proposals"][0]["participation_rate_pct"], float)


class TestEffectiveQuorumGap(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolGovernanceVoterApathyAnalyzer()

    def test_positive_quorum_gap(self):
        # quorum=40, participation=20 → gap=20
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=20_000, quorum_required=40.0)], {})
        self.assertAlmostEqual(r["proposals"][0]["effective_quorum_gap_pct"], 20.0, places=2)

    def test_negative_quorum_gap_when_exceeded(self):
        # quorum=20, participation=50 → gap=-30
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=50_000, quorum_required=20.0)], {})
        self.assertAlmostEqual(r["proposals"][0]["effective_quorum_gap_pct"], -30.0, places=2)

    def test_zero_quorum_gap(self):
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=30_000, quorum_required=30.0)], {})
        self.assertAlmostEqual(r["proposals"][0]["effective_quorum_gap_pct"], 0.0, places=2)


class TestWhaleDominance(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolGovernanceVoterApathyAnalyzer()

    def test_whale_dominance_passthrough(self):
        r = self.a.analyze([_prop(top_voter_vp=45.0, votes_cast=10_000)], {})
        self.assertAlmostEqual(r["proposals"][0]["whale_dominance_score"], 45.0, places=4)

    def test_whale_zero_when_no_votes_cast(self):
        r = self.a.analyze([_prop(top_voter_vp=50.0, votes_cast=0)], {})
        self.assertAlmostEqual(r["proposals"][0]["whale_dominance_score"], 0.0, places=4)

    def test_whale_score_is_float(self):
        r = self.a.analyze([_prop()], {})
        self.assertIsInstance(r["proposals"][0]["whale_dominance_score"], float)


class TestConsensusScore(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolGovernanceVoterApathyAnalyzer()

    def test_consensus_is_max_of_for_against(self):
        r = self.a.analyze([_prop(votes_for=75.0, votes_against=25.0)], {})
        self.assertAlmostEqual(r["proposals"][0]["consensus_score"], 75.0, places=2)

    def test_consensus_uses_against_when_dominant(self):
        r = self.a.analyze([_prop(votes_for=30.0, votes_against=70.0)], {})
        self.assertAlmostEqual(r["proposals"][0]["consensus_score"], 70.0, places=2)

    def test_consensus_50_50(self):
        r = self.a.analyze([_prop(votes_for=50.0, votes_against=50.0)], {})
        self.assertAlmostEqual(r["proposals"][0]["consensus_score"], 50.0, places=2)

    def test_consensus_near_100(self):
        r = self.a.analyze([_prop(votes_for=99.0, votes_against=1.0)], {})
        self.assertAlmostEqual(r["proposals"][0]["consensus_score"], 99.0, places=2)


class TestApathySeverityScore(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolGovernanceVoterApathyAnalyzer()

    def test_high_participation_low_severity(self):
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=80_000, quorum_required=30.0)], {})
        self.assertLess(r["proposals"][0]["apathy_severity_score"], 30.0)

    def test_low_participation_high_severity(self):
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=2_000, quorum_required=20.0)], {})
        self.assertGreater(r["proposals"][0]["apathy_severity_score"], 50.0)

    def test_severity_capped_at_100(self):
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=0, quorum_required=50.0)], {})
        self.assertLessEqual(r["proposals"][0]["apathy_severity_score"], 100.0)

    def test_severity_non_negative(self):
        r = self.a.analyze([_prop()], {})
        self.assertGreaterEqual(r["proposals"][0]["apathy_severity_score"], 0.0)

    def test_severity_is_float(self):
        r = self.a.analyze([_prop()], {})
        self.assertIsInstance(r["proposals"][0]["apathy_severity_score"], float)


class TestApathyLabels(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolGovernanceVoterApathyAnalyzer()

    def test_engaged_label(self):
        # 45% participation ≥ 40%
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=45_000)], {})
        self.assertEqual(r["proposals"][0]["label"], LABEL_ENGAGED)

    def test_moderate_label(self):
        # 25% participation: ≥20% but <40%
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=25_000)], {})
        self.assertEqual(r["proposals"][0]["label"], LABEL_MODERATE)

    def test_apathetic_label(self):
        # 15% participation: ≥10% but <20%
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=15_000)], {})
        self.assertEqual(r["proposals"][0]["label"], LABEL_APATHETIC)

    def test_critically_apathetic_label(self):
        # 7% participation: ≥5% but <10%
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=7_000)], {})
        self.assertEqual(r["proposals"][0]["label"], LABEL_CRITICALLY_APATHETIC)

    def test_zombie_label(self):
        # 3% participation: <5%
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=3_000)], {})
        self.assertEqual(r["proposals"][0]["label"], LABEL_ZOMBIE)

    def test_exactly_at_engaged_threshold(self):
        # exactly 40% → ENGAGED
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=40_000)], {})
        self.assertEqual(r["proposals"][0]["label"], LABEL_ENGAGED)

    def test_label_is_string(self):
        r = self.a.analyze([_prop()], {})
        self.assertIsInstance(r["proposals"][0]["label"], str)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolGovernanceVoterApathyAnalyzer()

    def test_quorum_failed_flag_when_not_reached(self):
        r = self.a.analyze([_prop(quorum_reached=False, outcome="quorum_failed")], {})
        self.assertIn("QUORUM_FAILED", r["proposals"][0]["flags"])

    def test_no_quorum_failed_flag_when_reached(self):
        r = self.a.analyze([_prop(quorum_reached=True, outcome="passed")], {})
        self.assertNotIn("QUORUM_FAILED", r["proposals"][0]["flags"])

    def test_whale_dominated_flag(self):
        # top_voter=45 > 30 threshold
        r = self.a.analyze([_prop(top_voter_vp=45.0, votes_cast=10_000)], {})
        self.assertIn("WHALE_DOMINATED", r["proposals"][0]["flags"])

    def test_no_whale_dominated_flag(self):
        r = self.a.analyze([_prop(top_voter_vp=20.0, votes_cast=10_000)], {})
        self.assertNotIn("WHALE_DOMINATED", r["proposals"][0]["flags"])

    def test_emergency_proposal_flag(self):
        r = self.a.analyze([_prop(proposal_type="emergency")], {})
        self.assertIn("EMERGENCY_PROPOSAL", r["proposals"][0]["flags"])

    def test_no_emergency_flag_for_param_change(self):
        r = self.a.analyze([_prop(proposal_type="param_change")], {})
        self.assertNotIn("EMERGENCY_PROPOSAL", r["proposals"][0]["flags"])

    def test_low_competition_flag(self):
        # consensus=95 > 90 threshold
        r = self.a.analyze([_prop(votes_for=95.0, votes_against=5.0)], {})
        self.assertIn("LOW_COMPETITION", r["proposals"][0]["flags"])

    def test_no_low_competition_when_contested(self):
        r = self.a.analyze([_prop(votes_for=60.0, votes_against=40.0)], {})
        self.assertNotIn("LOW_COMPETITION", r["proposals"][0]["flags"])

    def test_manipulable_flag(self):
        # participation < 10% AND quorum_required == 0
        r = self.a.analyze([
            _prop(total_eligible=100_000, votes_cast=5_000, quorum_required=0.0, quorum_reached=False)
        ], {})
        self.assertIn("MANIPULABLE", r["proposals"][0]["flags"])

    def test_no_manipulable_when_quorum_protected(self):
        r = self.a.analyze([
            _prop(total_eligible=100_000, votes_cast=5_000, quorum_required=20.0)
        ], {})
        self.assertNotIn("MANIPULABLE", r["proposals"][0]["flags"])

    def test_no_manipulable_when_high_participation(self):
        r = self.a.analyze([
            _prop(total_eligible=100_000, votes_cast=20_000, quorum_required=0.0)
        ], {})
        self.assertNotIn("MANIPULABLE", r["proposals"][0]["flags"])

    def test_flags_is_list(self):
        r = self.a.analyze([_prop()], {})
        self.assertIsInstance(r["proposals"][0]["flags"], list)

    def test_quorum_failed_from_outcome(self):
        # quorum_reached=True but outcome says quorum_failed → still flagged
        r = self.a.analyze([_prop(quorum_reached=False, outcome="passed")], {})
        self.assertIn("QUORUM_FAILED", r["proposals"][0]["flags"])


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolGovernanceVoterApathyAnalyzer()

    def test_aggregates_empty(self):
        r = self.a.analyze([], {})
        agg = r["aggregates"]
        self.assertIsNone(agg["most_engaged_proposal_id"])
        self.assertEqual(agg["total_proposals"], 0)

    def test_most_engaged_proposal(self):
        r = self.a.analyze([
            _prop(proposal_id="A", total_eligible=100_000, votes_cast=80_000),
            _prop(proposal_id="B", total_eligible=100_000, votes_cast=20_000),
        ], {})
        self.assertEqual(r["aggregates"]["most_engaged_proposal_id"], "A")

    def test_most_apathetic_proposal(self):
        r = self.a.analyze([
            _prop(proposal_id="A", total_eligible=100_000, votes_cast=80_000),
            _prop(proposal_id="B", total_eligible=100_000, votes_cast=5_000),
        ], {})
        self.assertEqual(r["aggregates"]["most_apathetic_proposal_id"], "B")

    def test_average_participation(self):
        r = self.a.analyze([
            _prop(total_eligible=100_000, votes_cast=40_000),  # 40%
            _prop(total_eligible=100_000, votes_cast=60_000),  # 60%
        ], {})
        self.assertAlmostEqual(r["aggregates"]["average_participation_pct"], 50.0, places=2)

    def test_zombie_count(self):
        r = self.a.analyze([
            _prop(total_eligible=100_000, votes_cast=3_000),   # 3% → ZOMBIE
            _prop(total_eligible=100_000, votes_cast=2_000),   # 2% → ZOMBIE
            _prop(total_eligible=100_000, votes_cast=50_000),  # 50% → ENGAGED
        ], {})
        self.assertEqual(r["aggregates"]["zombie_governance_count"], 2)

    def test_quorum_failure_rate(self):
        r = self.a.analyze([
            _prop(quorum_reached=False, outcome="quorum_failed"),
            _prop(quorum_reached=True, outcome="passed"),
        ], {})
        self.assertAlmostEqual(r["aggregates"]["quorum_failure_rate_pct"], 50.0, places=2)

    def test_whale_dominated_count(self):
        r = self.a.analyze([
            _prop(top_voter_vp=40.0, votes_cast=10_000),  # whale
            _prop(top_voter_vp=20.0, votes_cast=10_000),  # not whale
        ], {})
        self.assertEqual(r["aggregates"]["whale_dominated_count"], 1)

    def test_emergency_count(self):
        r = self.a.analyze([
            _prop(proposal_type="emergency"),
            _prop(proposal_type="param_change"),
            _prop(proposal_type="emergency"),
        ], {})
        self.assertEqual(r["aggregates"]["emergency_proposal_count"], 2)

    def test_total_proposals(self):
        r = self.a.analyze([_prop(), _prop(), _prop()], {})
        self.assertEqual(r["aggregates"]["total_proposals"], 3)

    def test_zero_quorum_failure_rate(self):
        r = self.a.analyze([
            _prop(quorum_reached=True, outcome="passed"),
            _prop(quorum_reached=True, outcome="failed"),
        ], {})
        self.assertAlmostEqual(r["aggregates"]["quorum_failure_rate_pct"], 0.0, places=2)


class TestOutputSchema(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolGovernanceVoterApathyAnalyzer()

    def test_output_has_proposals_key(self):
        r = self.a.analyze([_prop()], {})
        self.assertIn("proposals", r)

    def test_output_has_aggregates_key(self):
        r = self.a.analyze([_prop()], {})
        self.assertIn("aggregates", r)

    def test_output_has_meta_key(self):
        r = self.a.analyze([_prop()], {})
        self.assertIn("meta", r)

    def test_meta_module(self):
        r = self.a.analyze([_prop()], {})
        self.assertEqual(r["meta"]["module"], "MP-967")

    def test_meta_version(self):
        r = self.a.analyze([_prop()], {})
        self.assertIn("version", r["meta"])

    def test_meta_generated_at(self):
        r = self.a.analyze([_prop()], {})
        self.assertIn("generated_at", r["meta"])

    def test_proposal_has_participation_rate(self):
        r = self.a.analyze([_prop()], {})
        self.assertIn("participation_rate_pct", r["proposals"][0])

    def test_proposal_has_quorum_gap(self):
        r = self.a.analyze([_prop()], {})
        self.assertIn("effective_quorum_gap_pct", r["proposals"][0])

    def test_proposal_has_whale_dominance(self):
        r = self.a.analyze([_prop()], {})
        self.assertIn("whale_dominance_score", r["proposals"][0])

    def test_proposal_has_consensus_score(self):
        r = self.a.analyze([_prop()], {})
        self.assertIn("consensus_score", r["proposals"][0])

    def test_proposal_has_apathy_severity(self):
        r = self.a.analyze([_prop()], {})
        self.assertIn("apathy_severity_score", r["proposals"][0])

    def test_proposal_has_label(self):
        r = self.a.analyze([_prop()], {})
        self.assertIn("label", r["proposals"][0])

    def test_proposal_has_flags(self):
        r = self.a.analyze([_prop()], {})
        self.assertIn("flags", r["proposals"][0])

    def test_result_serializable(self):
        r = self.a.analyze([_prop()], {})
        json.dumps(r)  # must not raise

    def test_multiple_proposals(self):
        r = self.a.analyze([_prop(proposal_id=str(i)) for i in range(6)], {})
        self.assertEqual(len(r["proposals"]), 6)

    def test_meta_proposal_count_matches(self):
        r = self.a.analyze([_prop() for _ in range(4)], {})
        self.assertEqual(r["meta"]["proposal_count"], 4)


class TestConfigOverrides(unittest.TestCase):
    def test_custom_engaged_threshold(self):
        a = ProtocolGovernanceVoterApathyAnalyzer({"engaged_threshold": 60.0})
        # 50% participation → MODERATE (below new 60% threshold)
        r = a.analyze([_prop(total_eligible=100_000, votes_cast=50_000)], {})
        self.assertEqual(r["proposals"][0]["label"], LABEL_MODERATE)

    def test_custom_zombie_threshold(self):
        a = ProtocolGovernanceVoterApathyAnalyzer({"zombie_threshold": 10.0})
        # 8% participation → ZOMBIE with new threshold
        r = a.analyze([_prop(total_eligible=100_000, votes_cast=8_000)], {})
        self.assertEqual(r["proposals"][0]["label"], LABEL_ZOMBIE)

    def test_custom_whale_threshold(self):
        a = ProtocolGovernanceVoterApathyAnalyzer({"whale_dominated_threshold": 50.0})
        # top_voter=45 < 50 → not WHALE_DOMINATED
        r = a.analyze([_prop(top_voter_vp=45.0, votes_cast=10_000)], {})
        self.assertNotIn("WHALE_DOMINATED", r["proposals"][0]["flags"])

    def test_runtime_config_override(self):
        a = ProtocolGovernanceVoterApathyAnalyzer()
        r = a.analyze(
            [_prop(total_eligible=100_000, votes_cast=50_000)],
            {"engaged_threshold": 60.0},
        )
        self.assertEqual(r["proposals"][0]["label"], LABEL_MODERATE)

    def test_custom_low_competition_threshold(self):
        a = ProtocolGovernanceVoterApathyAnalyzer({"low_competition_consensus_threshold": 95.0})
        # consensus=92 < 95 → NOT LOW_COMPETITION
        r = a.analyze([_prop(votes_for=92.0, votes_against=8.0)], {})
        self.assertNotIn("LOW_COMPETITION", r["proposals"][0]["flags"])

    def test_custom_manipulable_threshold(self):
        a = ProtocolGovernanceVoterApathyAnalyzer({"manipulable_participation_threshold": 5.0})
        # 8% participation → NOT manipulable (threshold lowered to 5%)
        r = a.analyze([
            _prop(total_eligible=100_000, votes_cast=8_000, quorum_required=0.0, quorum_reached=False)
        ], {})
        self.assertNotIn("MANIPULABLE", r["proposals"][0]["flags"])


class TestProposalPassthrough(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolGovernanceVoterApathyAnalyzer()

    def test_protocol_passthrough(self):
        r = self.a.analyze([_prop(protocol="MakerDAO")], {})
        self.assertEqual(r["proposals"][0]["protocol"], "MakerDAO")

    def test_proposal_id_passthrough(self):
        r = self.a.analyze([_prop(proposal_id="MIP-99")], {})
        self.assertEqual(r["proposals"][0]["proposal_id"], "MIP-99")

    def test_title_passthrough(self):
        r = self.a.analyze([_prop(title="Adjust stability fee")], {})
        self.assertEqual(r["proposals"][0]["title"], "Adjust stability fee")

    def test_outcome_passthrough(self):
        r = self.a.analyze([_prop(outcome="failed")], {})
        self.assertEqual(r["proposals"][0]["outcome"], "failed")

    def test_proposal_type_passthrough(self):
        r = self.a.analyze([_prop(proposal_type="treasury")], {})
        self.assertEqual(r["proposals"][0]["proposal_type"], "treasury")

    def test_days_voting_period_passthrough(self):
        r = self.a.analyze([_prop(days_period=14.0)], {})
        self.assertAlmostEqual(r["proposals"][0]["days_voting_period"], 14.0, places=2)


class TestWriteLog(unittest.TestCase):
    def _make_result(self):
        a = ProtocolGovernanceVoterApathyAnalyzer()
        return a.analyze([_prop()], {})

    def test_write_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            write_log(self._make_result(), Path(td))
            self.assertTrue((Path(td) / LOG_FILE).exists())

    def test_write_is_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            write_log(self._make_result(), Path(td))
            data = json.loads((Path(td) / LOG_FILE).read_text())
            self.assertIsInstance(data, list)

    def test_write_appends(self):
        with tempfile.TemporaryDirectory() as td:
            write_log(self._make_result(), Path(td))
            write_log(self._make_result(), Path(td))
            data = json.loads((Path(td) / LOG_FILE).read_text())
            self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as td:
            for _ in range(LOG_CAP + 5):
                write_log(self._make_result(), Path(td))
            data = json.loads((Path(td) / LOG_FILE).read_text())
            self.assertLessEqual(len(data), LOG_CAP)

    def test_atomic_write_complete_json(self):
        with tempfile.TemporaryDirectory() as td:
            write_log(self._make_result(), Path(td))
            content = (Path(td) / LOG_FILE).read_text()
            json.loads(content)  # must not raise

    def test_write_to_nested_dir(self):
        with tempfile.TemporaryDirectory() as td:
            new_dir = Path(td) / "nested" / "data"
            write_log(self._make_result(), new_dir)
            self.assertTrue((new_dir / LOG_FILE).exists())

    def test_log_entry_has_meta(self):
        with tempfile.TemporaryDirectory() as td:
            write_log(self._make_result(), Path(td))
            data = json.loads((Path(td) / LOG_FILE).read_text())
            self.assertIn("meta", data[0])


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolGovernanceVoterApathyAnalyzer()

    def test_empty_proposals_list(self):
        r = self.a.analyze([], {})
        self.assertEqual(r["proposals"], [])
        self.assertEqual(r["aggregates"]["total_proposals"], 0)

    def test_none_config(self):
        r = self.a.analyze([_prop()], None)
        self.assertIn("proposals", r)

    def test_missing_optional_keys_dont_crash(self):
        minimal = {"protocol": "X", "proposal_id": "1"}
        r = self.a.analyze([minimal], {})
        self.assertEqual(len(r["proposals"]), 1)

    def test_single_proposal_aggregates(self):
        r = self.a.analyze([_prop(total_eligible=100_000, votes_cast=30_000)], {})
        agg = r["aggregates"]
        self.assertEqual(agg["most_engaged_proposal_id"], "AIP-1")
        self.assertEqual(agg["most_apathetic_proposal_id"], "AIP-1")
        self.assertAlmostEqual(agg["average_participation_pct"], 30.0, places=2)

    def test_all_proposals_zombie(self):
        r = self.a.analyze([
            _prop(total_eligible=100_000, votes_cast=1_000),
            _prop(total_eligible=100_000, votes_cast=500),
        ], {})
        self.assertEqual(r["aggregates"]["zombie_governance_count"], 2)

    def test_very_large_eligible_voters(self):
        r = self.a.analyze([_prop(total_eligible=10_000_000, votes_cast=4_500_000)], {})
        self.assertAlmostEqual(r["proposals"][0]["participation_rate_pct"], 45.0, places=2)

    def test_100_pct_quorum_required(self):
        r = self.a.analyze([_prop(total_eligible=100, votes_cast=50, quorum_required=100.0)], {})
        self.assertAlmostEqual(r["proposals"][0]["effective_quorum_gap_pct"], 50.0, places=2)

    def test_upgrade_proposal_type(self):
        r = self.a.analyze([_prop(proposal_type="upgrade")], {})
        self.assertEqual(r["proposals"][0]["proposal_type"], "upgrade")

    def test_zero_votes_for_and_against(self):
        r = self.a.analyze([_prop(votes_for=0.0, votes_against=0.0)], {})
        self.assertAlmostEqual(r["proposals"][0]["consensus_score"], 0.0, places=2)

    def test_quorum_failure_rate_all_fail(self):
        r = self.a.analyze([
            _prop(quorum_reached=False, outcome="quorum_failed"),
            _prop(quorum_reached=False, outcome="quorum_failed"),
        ], {})
        self.assertAlmostEqual(r["aggregates"]["quorum_failure_rate_pct"], 100.0, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
