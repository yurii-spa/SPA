"""
Tests for MP-675 GovernanceTokenRiskAnalyzer.
≥60 unittest cases. Pure stdlib (unittest only).
Run: python3 -m unittest spa_core.tests.test_governance_token_risk_analyzer -v
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.governance_token_risk_analyzer import (
    MAX_ENTRIES,
    GovernanceProfile,
    GovernanceRiskReport,
    GovernanceTokenRiskAnalyzer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _profile(**kwargs) -> GovernanceProfile:
    """Build a GovernanceProfile with sensible defaults."""
    defaults = dict(
        protocol_id="test-protocol",
        token_symbol="TST",
        total_supply=10_000_000.0,
        circulating_supply=8_000_000.0,
        top10_holder_pct=25.0,
        team_held_pct=10.0,
        dao_treasury_pct=15.0,
        active_voters_30d=200,
        total_proposals_90d=5,
        quorum_threshold_pct=5.0,
        timelock_hours=48,
        has_veto_multisig=True,
    )
    defaults.update(kwargs)
    return GovernanceProfile(**defaults)


ANA = GovernanceTokenRiskAnalyzer()


# ===========================================================================
# 1. _centralization_score
# ===========================================================================

class TestCentralizationScore(unittest.TestCase):

    def test_zero_concentration(self):
        score = ANA._centralization_score(0.0, 0.0)
        self.assertAlmostEqual(score, 0.0, places=6)

    def test_full_concentration(self):
        score = ANA._centralization_score(100.0, 100.0)
        self.assertAlmostEqual(score, 1.0, places=6)

    def test_equal_weights(self):
        # 50% top10, 50% team → (0.5*0.5)+(0.5*0.5) = 0.5
        score = ANA._centralization_score(50.0, 50.0)
        self.assertAlmostEqual(score, 0.5, places=6)

    def test_only_top10(self):
        # top10=80%, team=0% → 0.8*0.5 + 0*0.5 = 0.4
        score = ANA._centralization_score(80.0, 0.0)
        self.assertAlmostEqual(score, 0.4, places=6)

    def test_only_team(self):
        # top10=0%, team=60% → 0*0.5 + 0.6*0.5 = 0.3
        score = ANA._centralization_score(0.0, 60.0)
        self.assertAlmostEqual(score, 0.3, places=6)

    def test_clamped_at_1(self):
        score = ANA._centralization_score(200.0, 200.0)
        self.assertLessEqual(score, 1.0)

    def test_clamped_at_0(self):
        score = ANA._centralization_score(-10.0, -10.0)
        self.assertGreaterEqual(score, 0.0)

    def test_weighted_calculation(self):
        # top10=60%, team=20% → (0.6*0.5)+(0.2*0.5) = 0.4
        score = ANA._centralization_score(60.0, 20.0)
        self.assertAlmostEqual(score, 0.4, places=6)


# ===========================================================================
# 2. _plutocracy_risk
# ===========================================================================

class TestPlutocracyRisk(unittest.TestCase):

    def test_zero_top10_is_zero(self):
        self.assertAlmostEqual(ANA._plutocracy_risk(0.0), 0.0, places=6)

    def test_80_pct_top10_is_capped_at_1(self):
        # 80/100*1.5 = 1.2 → capped at 1.0
        self.assertAlmostEqual(ANA._plutocracy_risk(80.0), 1.0, places=6)

    def test_40_pct_top10(self):
        # 40/100*1.5 = 0.6
        self.assertAlmostEqual(ANA._plutocracy_risk(40.0), 0.6, places=6)

    def test_50_pct_top10(self):
        # 50/100*1.5 = 0.75
        self.assertAlmostEqual(ANA._plutocracy_risk(50.0), 0.75, places=6)

    def test_100_pct_top10_capped(self):
        self.assertAlmostEqual(ANA._plutocracy_risk(100.0), 1.0, places=6)

    def test_20_pct_top10(self):
        # 20/100*1.5 = 0.3
        self.assertAlmostEqual(ANA._plutocracy_risk(20.0), 0.3, places=6)

    def test_value_never_exceeds_1(self):
        for pct in [50, 70, 90, 100, 150]:
            self.assertLessEqual(ANA._plutocracy_risk(float(pct)), 1.0)


# ===========================================================================
# 3. _governance_activity
# ===========================================================================

class TestGovernanceActivity(unittest.TestCase):

    def test_active_condition(self):
        self.assertEqual(ANA._governance_activity(3, 100), "ACTIVE")

    def test_active_with_more(self):
        self.assertEqual(ANA._governance_activity(10, 500), "ACTIVE")

    def test_not_active_proposals_too_few(self):
        # proposals=2 < 3, voters=200 → not ACTIVE
        result = ANA._governance_activity(2, 200)
        self.assertNotEqual(result, "ACTIVE")

    def test_not_active_voters_too_few(self):
        # proposals=5, voters=50 < 100 → not ACTIVE
        result = ANA._governance_activity(5, 50)
        self.assertNotEqual(result, "ACTIVE")

    def test_moderate_condition(self):
        self.assertEqual(ANA._governance_activity(1, 20), "MODERATE")

    def test_moderate_with_more(self):
        self.assertEqual(ANA._governance_activity(2, 99), "MODERATE")

    def test_dormant_no_proposals(self):
        self.assertEqual(ANA._governance_activity(0, 200), "DORMANT")

    def test_dormant_no_voters(self):
        self.assertEqual(ANA._governance_activity(5, 0), "DORMANT")

    def test_dormant_both_low(self):
        self.assertEqual(ANA._governance_activity(0, 0), "DORMANT")

    def test_dormant_proposals_1_voters_19(self):
        # proposals=1 but voters=19 < 20 → DORMANT
        self.assertEqual(ANA._governance_activity(1, 19), "DORMANT")


# ===========================================================================
# 4. _voter_apathy_score
# ===========================================================================

class TestVoterApathyScore(unittest.TestCase):

    def test_500_voters_zero_apathy(self):
        self.assertAlmostEqual(ANA._voter_apathy_score(500), 0.0, places=6)

    def test_0_voters_full_apathy(self):
        self.assertAlmostEqual(ANA._voter_apathy_score(0), 1.0, places=6)

    def test_250_voters_half_apathy(self):
        self.assertAlmostEqual(ANA._voter_apathy_score(250), 0.5, places=6)

    def test_1000_voters_capped_at_zero(self):
        # min(1, 1000/500) = 1, so apathy = 0
        self.assertAlmostEqual(ANA._voter_apathy_score(1000), 0.0, places=6)

    def test_100_voters(self):
        # 1 - min(1, 100/500) = 1 - 0.2 = 0.8
        self.assertAlmostEqual(ANA._voter_apathy_score(100), 0.8, places=6)

    def test_never_below_zero(self):
        for v in [0, 100, 500, 1000]:
            self.assertGreaterEqual(ANA._voter_apathy_score(v), 0.0)

    def test_never_above_one(self):
        for v in [0, 100, 500, 1000]:
            self.assertLessEqual(ANA._voter_apathy_score(v), 1.0)


# ===========================================================================
# 5. _safety_score
# ===========================================================================

class TestSafetyScore(unittest.TestCase):

    def test_no_protections_base(self):
        # timelock=1 (not 0, not ≥48), no multisig, quorum=0
        # base=0.5, no bonuses, no penalties
        score = ANA._safety_score(1, False, 0.0)
        self.assertAlmostEqual(score, 0.5, places=6)

    def test_timelock_0_penalty(self):
        # base=0.5, timelock=0 → -0.2 = 0.3
        score = ANA._safety_score(0, False, 0.0)
        self.assertAlmostEqual(score, 0.3, places=6)

    def test_good_timelock_bonus(self):
        # base=0.5, timelock>=48 → +0.2 = 0.7
        score = ANA._safety_score(48, False, 0.0)
        self.assertAlmostEqual(score, 0.7, places=6)

    def test_multisig_bonus(self):
        # base=0.5, multisig → +0.2 = 0.7
        score = ANA._safety_score(1, True, 0.0)
        self.assertAlmostEqual(score, 0.7, places=6)

    def test_quorum_bonus(self):
        # base=0.5, quorum≥5 → +0.1 = 0.6
        score = ANA._safety_score(1, False, 5.0)
        self.assertAlmostEqual(score, 0.6, places=6)

    def test_all_bonuses(self):
        # base=0.5 +0.2 +0.2 +0.1 = 1.0
        score = ANA._safety_score(72, True, 10.0)
        self.assertAlmostEqual(score, 1.0, places=6)

    def test_clamped_at_1(self):
        score = ANA._safety_score(1000, True, 100.0)
        self.assertLessEqual(score, 1.0)

    def test_clamped_at_0(self):
        # timelock=0 → -0.2, but base=0.5 → 0.3 (won't go below 0 here without extras)
        score = ANA._safety_score(0, False, 0.0)
        self.assertGreaterEqual(score, 0.0)

    def test_timelock_zero_no_multisig_no_quorum(self):
        # 0.5 - 0.2 = 0.3
        score = ANA._safety_score(0, False, 0.0)
        self.assertAlmostEqual(score, 0.3, places=6)


# ===========================================================================
# 6. _capture_risk
# ===========================================================================

class TestCaptureRisk(unittest.TestCase):

    def test_team_above_50_is_critical(self):
        result = ANA._capture_risk(0.3, 51.0, 0.3)
        self.assertEqual(result, "CRITICAL")

    def test_centralization_above_07_is_critical(self):
        result = ANA._capture_risk(0.71, 10.0, 0.3)
        self.assertEqual(result, "CRITICAL")

    def test_centralization_above_05_is_high(self):
        result = ANA._capture_risk(0.51, 10.0, 0.3)
        self.assertEqual(result, "HIGH")

    def test_plutocracy_above_07_is_high(self):
        result = ANA._capture_risk(0.4, 10.0, 0.71)
        self.assertEqual(result, "HIGH")

    def test_centralization_above_03_is_medium(self):
        result = ANA._capture_risk(0.31, 10.0, 0.3)
        self.assertEqual(result, "MEDIUM")

    def test_low_everything_is_low(self):
        result = ANA._capture_risk(0.2, 5.0, 0.2)
        self.assertEqual(result, "LOW")

    def test_exact_boundary_07_is_not_critical(self):
        # centralization == 0.7 (not >0.7)
        result = ANA._capture_risk(0.7, 10.0, 0.3)
        # 0.7 is not > 0.7 → check HIGH
        self.assertNotEqual(result, "CRITICAL")

    def test_exact_boundary_05_is_not_high(self):
        # centralization == 0.5 (not >0.5), plutocracy == 0.7 (not >0.7)
        result = ANA._capture_risk(0.5, 10.0, 0.7)
        self.assertNotEqual(result, "HIGH")


# ===========================================================================
# 7. _overall_grade
# ===========================================================================

class TestOverallGrade(unittest.TestCase):

    def test_grade_a_conditions(self):
        # All best: centralization=0, plutocracy=0, safety=1, voter_apathy=0
        # avg = (1+1+1+1)/4 = 1.0 → A
        grade = ANA._overall_grade(0.0, 0.0, 1.0, 0.0)
        self.assertEqual(grade, "A")

    def test_grade_f_conditions(self):
        # Worst: centralization=1, plutocracy=1, safety=0, voter_apathy=1
        # avg = (0+0+0+0)/4 = 0 → F
        grade = ANA._overall_grade(1.0, 1.0, 0.0, 1.0)
        self.assertEqual(grade, "F")

    def test_grade_b_boundary(self):
        # avg = 0.65 → B
        # Need (1-c + 1-p + s + 1-v) / 4 = 0.65 → sum = 2.6
        # e.g. c=0.2, p=0.2, s=0.6, v=0.2 → (0.8+0.8+0.6+0.8)/4 = 3.0/4 = 0.75 → A
        # c=0.5, p=0.5, s=0.5, v=0.3 → (0.5+0.5+0.5+0.7)/4 = 2.2/4 = 0.55 → C
        # c=0.2, p=0.3, s=0.6, v=0.3 → (0.8+0.7+0.6+0.7)/4 = 2.8/4 = 0.7 → B
        grade = ANA._overall_grade(0.2, 0.3, 0.6, 0.3)
        self.assertEqual(grade, "B")

    def test_grade_c_conditions(self):
        # avg = 0.55: c=0.4, p=0.4, s=0.5, v=0.4 → (0.6+0.6+0.5+0.6)/4 = 2.3/4 = 0.575 → C
        grade = ANA._overall_grade(0.4, 0.4, 0.5, 0.4)
        self.assertEqual(grade, "C")

    def test_grade_d_conditions(self):
        # avg ~0.4: c=0.7, p=0.6, s=0.3, v=0.6 → (0.3+0.4+0.3+0.4)/4 = 1.4/4 = 0.35 → D
        grade = ANA._overall_grade(0.7, 0.6, 0.3, 0.6)
        self.assertEqual(grade, "D")

    def test_grade_boundaries_exhaustive(self):
        """Verify all grade thresholds with correct arithmetic."""
        # avg=0.85 → A: c=0.0, p=0.0, s=0.8, v=0.4 → (1.0+1.0+0.8+0.6)/4 = 3.4/4 = 0.85
        self.assertEqual(ANA._overall_grade(0.0, 0.0, 0.8, 0.4), "A")
        # avg=0.675 → B: c=0.3, p=0.3, s=0.7, v=0.4 → (0.7+0.7+0.7+0.6)/4 = 2.7/4 = 0.675
        self.assertEqual(ANA._overall_grade(0.3, 0.3, 0.7, 0.4), "B")
        # avg=0.625 → C: c=0.3, p=0.3, s=0.5, v=0.4 → (0.7+0.7+0.5+0.6)/4 = 2.5/4 = 0.625
        self.assertEqual(ANA._overall_grade(0.3, 0.3, 0.5, 0.4), "C")


# ===========================================================================
# 8. _recommendations
# ===========================================================================

class TestRecommendations(unittest.TestCase):

    def _clean_profile(self, **kwargs) -> GovernanceProfile:
        defaults = dict(
            top10_holder_pct=20.0,
            team_held_pct=5.0,
            timelock_hours=72,
            has_veto_multisig=True,
            quorum_threshold_pct=5.0,
            active_voters_30d=300,
        )
        defaults.update(kwargs)
        return _profile(**defaults)

    def test_no_recs_for_ideal_protocol(self):
        p = self._clean_profile()
        c_score = ANA._centralization_score(p.top10_holder_pct, p.team_held_pct)  # 0.125
        apathy = ANA._voter_apathy_score(p.active_voters_30d)   # 0.4
        safety = ANA._safety_score(p.timelock_hours, p.has_veto_multisig, p.quorum_threshold_pct)  # 1.0
        recs = ANA._recommendations(p, c_score, apathy, safety)
        # No centralization>0.6, no team>20%, no apathy>0.7, timelock>=24, has multisig
        # safety>0.7 → will add positive rec
        self.assertFalse(any("⚠️" in r or "🚨" in r for r in recs))

    def test_high_centralization_warning(self):
        p = self._clean_profile(top10_holder_pct=80.0, team_held_pct=50.0)
        c_score = ANA._centralization_score(80.0, 50.0)  # 0.65
        apathy = ANA._voter_apathy_score(300)
        safety = ANA._safety_score(72, True, 5.0)
        recs = ANA._recommendations(p, c_score, apathy, safety)
        self.assertTrue(any("concentration" in r.lower() for r in recs))

    def test_team_above_20_warning(self):
        p = self._clean_profile(team_held_pct=25.0)
        c_score = ANA._centralization_score(20.0, 25.0)
        apathy = ANA._voter_apathy_score(300)
        safety = ANA._safety_score(72, True, 5.0)
        recs = ANA._recommendations(p, c_score, apathy, safety)
        self.assertTrue(any("team" in r.lower() for r in recs))

    def test_high_voter_apathy_warning(self):
        p = self._clean_profile(active_voters_30d=50)  # apathy = 1-50/500 = 0.9
        c_score = ANA._centralization_score(20.0, 5.0)
        apathy = ANA._voter_apathy_score(50)
        safety = ANA._safety_score(72, True, 5.0)
        recs = ANA._recommendations(p, c_score, apathy, safety)
        self.assertTrue(any("voter" in r.lower() for r in recs))

    def test_short_timelock_warning(self):
        p = self._clean_profile(timelock_hours=6)
        c_score = ANA._centralization_score(20.0, 5.0)
        apathy = ANA._voter_apathy_score(300)
        safety = ANA._safety_score(6, True, 5.0)
        recs = ANA._recommendations(p, c_score, apathy, safety)
        self.assertTrue(any("timelock" in r.lower() for r in recs))

    def test_no_multisig_warning(self):
        p = self._clean_profile(has_veto_multisig=False)
        c_score = ANA._centralization_score(20.0, 5.0)
        apathy = ANA._voter_apathy_score(300)
        safety = ANA._safety_score(72, False, 5.0)
        recs = ANA._recommendations(p, c_score, apathy, safety)
        self.assertTrue(any("veto" in r.lower() for r in recs))

    def test_high_safety_positive_recommendation(self):
        p = self._clean_profile()
        c_score = 0.1
        apathy = 0.1
        safety = 0.8  # >0.7
        recs = ANA._recommendations(p, c_score, apathy, safety)
        self.assertTrue(any("✅" in r for r in recs))


# ===========================================================================
# 9. analyze (integration)
# ===========================================================================

class TestAnalyze(unittest.TestCase):

    def test_returns_report_type(self):
        report = ANA.analyze(_profile())
        self.assertIsInstance(report, GovernanceRiskReport)

    def test_protocol_id_preserved(self):
        report = ANA.analyze(_profile(protocol_id="my-protocol"))
        self.assertEqual(report.protocol_id, "my-protocol")

    def test_token_symbol_preserved(self):
        report = ANA.analyze(_profile(token_symbol="MKR"))
        self.assertEqual(report.token_symbol, "MKR")

    def test_decentralized_protocol_grade_a_or_b(self):
        p = _profile(
            top10_holder_pct=15.0,
            team_held_pct=5.0,
            active_voters_30d=500,
            total_proposals_90d=10,
            timelock_hours=72,
            has_veto_multisig=True,
            quorum_threshold_pct=10.0,
        )
        report = ANA.analyze(p)
        self.assertIn(report.overall_grade, ["A", "B"])

    def test_whale_dominated_protocol_critical(self):
        p = _profile(
            top10_holder_pct=90.0,
            team_held_pct=60.0,
            active_voters_30d=5,
            total_proposals_90d=0,
            timelock_hours=0,
            has_veto_multisig=False,
            quorum_threshold_pct=0.0,
        )
        report = ANA.analyze(p)
        self.assertEqual(report.capture_risk, "CRITICAL")

    def test_governance_activity_in_valid_values(self):
        report = ANA.analyze(_profile())
        self.assertIn(report.governance_activity, ["ACTIVE", "MODERATE", "DORMANT"])

    def test_capture_risk_in_valid_values(self):
        report = ANA.analyze(_profile())
        self.assertIn(report.capture_risk, ["LOW", "MEDIUM", "HIGH", "CRITICAL"])

    def test_overall_grade_in_valid_values(self):
        report = ANA.analyze(_profile())
        self.assertIn(report.overall_grade, ["A", "B", "C", "D", "F"])

    def test_recommendations_is_list(self):
        report = ANA.analyze(_profile())
        self.assertIsInstance(report.recommendations, list)

    def test_scores_in_range_0_1(self):
        report = ANA.analyze(_profile())
        self.assertGreaterEqual(report.centralization_score, 0.0)
        self.assertLessEqual(report.centralization_score, 1.0)
        self.assertGreaterEqual(report.plutocracy_risk, 0.0)
        self.assertLessEqual(report.plutocracy_risk, 1.0)
        self.assertGreaterEqual(report.voter_apathy_score, 0.0)
        self.assertLessEqual(report.voter_apathy_score, 1.0)
        self.assertGreaterEqual(report.safety_score, 0.0)
        self.assertLessEqual(report.safety_score, 1.0)


# ===========================================================================
# 10. analyze_batch
# ===========================================================================

class TestAnalyzeBatch(unittest.TestCase):

    def test_empty_list_returns_empty(self):
        result = ANA.analyze_batch([])
        self.assertEqual(result, [])

    def test_single_profile(self):
        result = ANA.analyze_batch([_profile(protocol_id="p1")])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].protocol_id, "p1")

    def test_multiple_profiles(self):
        profiles = [_profile(protocol_id=f"proto-{i}") for i in range(4)]
        results = ANA.analyze_batch(profiles)
        self.assertEqual(len(results), 4)

    def test_all_have_grades(self):
        profiles = [_profile(protocol_id=f"g-{i}") for i in range(3)]
        results = ANA.analyze_batch(profiles)
        for r in results:
            self.assertIn(r.overall_grade, ["A", "B", "C", "D", "F"])


# ===========================================================================
# 11. save_results / load_history
# ===========================================================================

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = Path(self.tmp_dir) / "test_gov_log.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(ANA.load_history(self.data_file), [])

    def test_save_creates_file(self):
        report = ANA.analyze(_profile())
        ANA.save_results([report], self.data_file)
        self.assertTrue(self.data_file.exists())

    def test_saved_file_is_valid_json(self):
        report = ANA.analyze(_profile())
        ANA.save_results([report], self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)

    def test_saved_entry_has_required_fields(self):
        report = ANA.analyze(_profile(protocol_id="field-test"))
        ANA.save_results([report], self.data_file)
        data = json.loads(self.data_file.read_text())
        entry = data[0]
        self.assertIn("timestamp", entry)
        self.assertIn("protocol_id", entry)
        self.assertIn("overall_grade", entry)
        self.assertIn("capture_risk", entry)
        self.assertIn("recommendations", entry)

    def test_round_trip_load(self):
        report = ANA.analyze(_profile(protocol_id="rt-gov"))
        ANA.save_results([report], self.data_file)
        loaded = ANA.load_history(self.data_file)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["protocol_id"], "rt-gov")

    def test_ring_buffer_max_entries(self):
        for i in range(MAX_ENTRIES + 15):
            report = ANA.analyze(_profile(protocol_id=f"rb-{i}"))
            ANA.save_results([report], self.data_file)
        loaded = ANA.load_history(self.data_file)
        self.assertLessEqual(len(loaded), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        for i in range(MAX_ENTRIES + 5):
            report = ANA.analyze(_profile(protocol_id=f"rb-{i}"))
            ANA.save_results([report], self.data_file)
        loaded = ANA.load_history(self.data_file)
        self.assertEqual(loaded[-1]["protocol_id"], f"rb-{MAX_ENTRIES + 4}")

    def test_atomic_write_no_tmp_remaining(self):
        report = ANA.analyze(_profile())
        ANA.save_results([report], self.data_file)
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_load_corrupt_json_returns_empty(self):
        self.data_file.write_text("{invalid-json")
        self.assertEqual(ANA.load_history(self.data_file), [])

    def test_save_batch_of_reports(self):
        profiles = [_profile(protocol_id=f"batch-{i}") for i in range(3)]
        reports = ANA.analyze_batch(profiles)
        ANA.save_results(reports, self.data_file)
        loaded = ANA.load_history(self.data_file)
        self.assertEqual(len(loaded), 3)


if __name__ == "__main__":
    unittest.main()
