"""
Tests for MP-977: ProtocolUpgradeImpactAssessor
Run: python3 -m unittest spa_core.tests.test_protocol_upgrade_impact_assessor
"""

import json
import math
import os
import tempfile
import unittest

from spa_core.analytics.protocol_upgrade_impact_assessor import (
    ProtocolUpgradeImpactAssessor,
    FLAG_USER_ACTION_REQUIRED,
    FLAG_NO_AUDIT,
    FLAG_LOW_COMMUNITY_SUPPORT,
    FLAG_IMMINENT,
    FLAG_REPEAT_ISSUES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_upgrade(**kwargs):
    """Return a minimal valid upgrade dict with overridable defaults."""
    base = {
        "protocol": "TestProtocol",
        "upgrade_type": "smart_contract",
        "scheduled_date_days": 30,
        "magnitude_score": 5.0,
        "affected_tvl_usd": 100_000_000.0,
        "user_action_required": False,
        "migration_period_days": 14,
        "historical_similar_upgrades_count": 2,
        "last_upgrade_issues_count": 0,
        "community_approval_pct": 80.0,
        "has_audit": True,
    }
    base.update(kwargs)
    return base


class TestProtocolUpgradeImpactAssessor(unittest.TestCase):
    """Unit tests for ProtocolUpgradeImpactAssessor."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "upgrade_impact_log.json")
        self.assessor = ProtocolUpgradeImpactAssessor(data_file=self.log_file)

    # ------------------------------------------------------------------
    # 1. Basic structure
    # ------------------------------------------------------------------

    def test_assess_returns_dict(self):
        result = self.assessor.assess([_make_upgrade()])
        self.assertIsInstance(result, dict)

    def test_assess_has_assessments_key(self):
        result = self.assessor.assess([_make_upgrade()])
        self.assertIn("assessments", result)

    def test_assess_has_aggregates_key(self):
        result = self.assessor.assess([_make_upgrade()])
        self.assertIn("aggregates", result)

    def test_assess_has_run_ts(self):
        result = self.assessor.assess([_make_upgrade()])
        self.assertIn("run_ts", result)

    def test_assess_has_upgrade_count(self):
        result = self.assessor.assess([_make_upgrade(), _make_upgrade()])
        self.assertEqual(result["upgrade_count"], 2)

    def test_assess_empty_list(self):
        result = self.assessor.assess([])
        self.assertEqual(result["assessments"], [])
        self.assertEqual(result["upgrade_count"], 0)

    def test_assess_single_upgrade(self):
        result = self.assessor.assess([_make_upgrade()])
        self.assertEqual(len(result["assessments"]), 1)

    def test_assess_multiple_upgrades(self):
        upgrades = [_make_upgrade(protocol=f"P{i}") for i in range(5)]
        result = self.assessor.assess(upgrades)
        self.assertEqual(len(result["assessments"]), 5)

    # ------------------------------------------------------------------
    # 2. Assessment fields
    # ------------------------------------------------------------------

    def test_assessment_has_protocol(self):
        result = self.assessor.assess([_make_upgrade(protocol="Aave")])
        self.assertEqual(result["assessments"][0]["protocol"], "Aave")

    def test_assessment_has_upgrade_type(self):
        result = self.assessor.assess([_make_upgrade(upgrade_type="fee_change")])
        self.assertEqual(result["assessments"][0]["upgrade_type"], "fee_change")

    def test_assessment_has_urgency_score(self):
        result = self.assessor.assess([_make_upgrade()])
        self.assertIn("urgency_score", result["assessments"][0])

    def test_assessment_has_disruption_score(self):
        result = self.assessor.assess([_make_upgrade()])
        self.assertIn("disruption_score", result["assessments"][0])

    def test_assessment_has_preparedness_score(self):
        result = self.assessor.assess([_make_upgrade()])
        self.assertIn("preparedness_score", result["assessments"][0])

    def test_assessment_has_net_risk_score(self):
        result = self.assessor.assess([_make_upgrade()])
        self.assertIn("net_risk_score", result["assessments"][0])

    def test_assessment_has_label(self):
        result = self.assessor.assess([_make_upgrade()])
        self.assertIn("label", result["assessments"][0])

    def test_assessment_has_flags(self):
        result = self.assessor.assess([_make_upgrade()])
        self.assertIn("flags", result["assessments"][0])

    def test_assessment_has_scheduled_date_days(self):
        result = self.assessor.assess([_make_upgrade(scheduled_date_days=14)])
        self.assertEqual(result["assessments"][0]["scheduled_date_days"], 14)

    def test_assessment_has_magnitude_score(self):
        result = self.assessor.assess([_make_upgrade(magnitude_score=7.0)])
        self.assertAlmostEqual(result["assessments"][0]["magnitude_score"], 7.0)

    def test_assessment_has_affected_tvl_usd(self):
        result = self.assessor.assess([_make_upgrade(affected_tvl_usd=5e8)])
        self.assertAlmostEqual(result["assessments"][0]["affected_tvl_usd"], 5e8)

    def test_assessment_has_community_approval_pct(self):
        result = self.assessor.assess([_make_upgrade(community_approval_pct=75.0)])
        self.assertAlmostEqual(result["assessments"][0]["community_approval_pct"], 75.0)

    def test_assessment_has_has_audit(self):
        result = self.assessor.assess([_make_upgrade(has_audit=True)])
        self.assertTrue(result["assessments"][0]["has_audit"])

    # ------------------------------------------------------------------
    # 3. Urgency score
    # ------------------------------------------------------------------

    def test_urgency_zero_days_is_100(self):
        result = self.assessor.assess([_make_upgrade(scheduled_date_days=0)])
        self.assertAlmostEqual(result["assessments"][0]["urgency_score"], 100.0, places=1)

    def test_urgency_decreases_with_days(self):
        r1 = self.assessor.assess([_make_upgrade(scheduled_date_days=5)])["assessments"][0]["urgency_score"]
        r2 = self.assessor.assess([_make_upgrade(scheduled_date_days=60)])["assessments"][0]["urgency_score"]
        self.assertGreater(r1, r2)

    def test_urgency_past_events(self):
        # Negative days (past) should still compute urgency based on abs()
        r1 = self.assessor.assess([_make_upgrade(scheduled_date_days=-5)])["assessments"][0]["urgency_score"]
        r2 = self.assessor.assess([_make_upgrade(scheduled_date_days=5)])["assessments"][0]["urgency_score"]
        self.assertAlmostEqual(r1, r2, places=2)

    def test_urgency_between_0_100(self):
        result = self.assessor.assess([_make_upgrade(scheduled_date_days=100)])
        self.assertGreaterEqual(result["assessments"][0]["urgency_score"], 0.0)
        self.assertLessEqual(result["assessments"][0]["urgency_score"], 100.0)

    def test_urgency_far_future_low(self):
        result = self.assessor.assess([_make_upgrade(scheduled_date_days=365)])
        self.assertLess(result["assessments"][0]["urgency_score"], 5.0)

    # ------------------------------------------------------------------
    # 4. Disruption score
    # ------------------------------------------------------------------

    def test_disruption_increases_with_magnitude(self):
        r1 = self.assessor.assess([_make_upgrade(magnitude_score=2)])["assessments"][0]["disruption_score"]
        r2 = self.assessor.assess([_make_upgrade(magnitude_score=9)])["assessments"][0]["disruption_score"]
        self.assertGreater(r2, r1)

    def test_disruption_increases_with_tvl(self):
        r1 = self.assessor.assess([_make_upgrade(affected_tvl_usd=1e6)])["assessments"][0]["disruption_score"]
        r2 = self.assessor.assess([_make_upgrade(affected_tvl_usd=1e10)])["assessments"][0]["disruption_score"]
        self.assertGreater(r2, r1)

    def test_disruption_zero_tvl(self):
        result = self.assessor.assess([_make_upgrade(affected_tvl_usd=0.0)])
        self.assertGreaterEqual(result["assessments"][0]["disruption_score"], 0.0)

    def test_disruption_between_0_100(self):
        result = self.assessor.assess([_make_upgrade(magnitude_score=10, affected_tvl_usd=1e12)])
        self.assertLessEqual(result["assessments"][0]["disruption_score"], 100.0)

    def test_disruption_max_magnitude_max_tvl(self):
        result = self.assessor.assess([_make_upgrade(magnitude_score=10, affected_tvl_usd=1e12)])
        self.assertAlmostEqual(result["assessments"][0]["disruption_score"], 100.0, places=0)

    # ------------------------------------------------------------------
    # 5. Preparedness score
    # ------------------------------------------------------------------

    def test_preparedness_max_with_audit_high_approval_long_migration(self):
        result = self.assessor.assess([
            _make_upgrade(
                has_audit=True,
                community_approval_pct=100.0,
                migration_period_days=30,
                historical_similar_upgrades_count=5,
            )
        ])
        self.assertAlmostEqual(result["assessments"][0]["preparedness_score"], 100.0, places=0)

    def test_preparedness_no_audit_reduces_score(self):
        r_audit = self.assessor.assess([_make_upgrade(has_audit=True)])["assessments"][0]["preparedness_score"]
        r_no_audit = self.assessor.assess([_make_upgrade(has_audit=False)])["assessments"][0]["preparedness_score"]
        self.assertGreater(r_audit, r_no_audit)

    def test_preparedness_zero_community_approval(self):
        result = self.assessor.assess([_make_upgrade(community_approval_pct=0.0)])
        self.assertGreaterEqual(result["assessments"][0]["preparedness_score"], 0.0)

    def test_preparedness_longer_migration_better(self):
        r1 = self.assessor.assess([_make_upgrade(migration_period_days=0)])["assessments"][0]["preparedness_score"]
        r2 = self.assessor.assess([_make_upgrade(migration_period_days=30)])["assessments"][0]["preparedness_score"]
        self.assertGreater(r2, r1)

    def test_preparedness_between_0_100(self):
        result = self.assessor.assess([_make_upgrade()])
        score = result["assessments"][0]["preparedness_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    # ------------------------------------------------------------------
    # 6. Net risk score
    # ------------------------------------------------------------------

    def test_net_risk_between_0_100(self):
        result = self.assessor.assess([_make_upgrade()])
        score = result["assessments"][0]["net_risk_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_net_risk_lower_with_high_preparedness(self):
        # Well-audited, high community support, long migration
        r_good = self.assessor.assess([_make_upgrade(
            has_audit=True, community_approval_pct=95.0, migration_period_days=60,
            historical_similar_upgrades_count=5, magnitude_score=5
        )])["assessments"][0]["net_risk_score"]

        # No audit, no community support, no migration
        r_bad = self.assessor.assess([_make_upgrade(
            has_audit=False, community_approval_pct=10.0, migration_period_days=0,
            historical_similar_upgrades_count=0, magnitude_score=5
        )])["assessments"][0]["net_risk_score"]

        self.assertGreater(r_bad, r_good)

    def test_net_risk_high_magnitude_increases_risk(self):
        r1 = self.assessor.assess([_make_upgrade(magnitude_score=1)])["assessments"][0]["net_risk_score"]
        r2 = self.assessor.assess([_make_upgrade(magnitude_score=10)])["assessments"][0]["net_risk_score"]
        self.assertGreaterEqual(r2, r1)

    # ------------------------------------------------------------------
    # 7. Labels
    # ------------------------------------------------------------------

    def test_label_smooth_transition(self):
        # Low disruption + high preparedness → SMOOTH_TRANSITION
        result = self.assessor.assess([_make_upgrade(
            magnitude_score=1,
            affected_tvl_usd=1e5,
            has_audit=True,
            community_approval_pct=100.0,
            migration_period_days=60,
            historical_similar_upgrades_count=5,
            user_action_required=False,
        )])
        self.assertEqual(result["assessments"][0]["label"], "SMOOTH_TRANSITION")

    def test_label_critical_upgrade(self):
        # user_action + high net risk
        result = self.assessor.assess([_make_upgrade(
            user_action_required=True,
            has_audit=False,
            community_approval_pct=10.0,
            migration_period_days=0,
            magnitude_score=10,
            affected_tvl_usd=1e12,
            historical_similar_upgrades_count=0,
        )])
        self.assertEqual(result["assessments"][0]["label"], "CRITICAL_UPGRADE")

    def test_label_is_string(self):
        result = self.assessor.assess([_make_upgrade()])
        self.assertIsInstance(result["assessments"][0]["label"], str)

    def test_valid_label_set(self):
        valid = {
            "SMOOTH_TRANSITION", "LOW_IMPACT", "MODERATE_DISRUPTION",
            "HIGH_IMPACT", "CRITICAL_UPGRADE"
        }
        result = self.assessor.assess([_make_upgrade()])
        self.assertIn(result["assessments"][0]["label"], valid)

    def test_label_high_impact(self):
        result = self.assessor.assess([_make_upgrade(
            magnitude_score=10,
            affected_tvl_usd=1e11,
            has_audit=False,
            community_approval_pct=20.0,
            migration_period_days=0,
            historical_similar_upgrades_count=0,
            user_action_required=False,
        )])
        label = result["assessments"][0]["label"]
        self.assertIn(label, ["HIGH_IMPACT", "CRITICAL_UPGRADE"])

    def test_label_low_impact(self):
        result = self.assessor.assess([_make_upgrade(
            magnitude_score=2,
            affected_tvl_usd=1e5,
            has_audit=True,
            community_approval_pct=70.0,
            migration_period_days=14,
            historical_similar_upgrades_count=3,
        )])
        label = result["assessments"][0]["label"]
        self.assertIn(label, ["SMOOTH_TRANSITION", "LOW_IMPACT", "MODERATE_DISRUPTION"])

    # ------------------------------------------------------------------
    # 8. Flags
    # ------------------------------------------------------------------

    def test_flag_user_action_required(self):
        result = self.assessor.assess([_make_upgrade(user_action_required=True)])
        self.assertIn(FLAG_USER_ACTION_REQUIRED, result["assessments"][0]["flags"])

    def test_no_flag_user_action_when_false(self):
        result = self.assessor.assess([_make_upgrade(user_action_required=False)])
        self.assertNotIn(FLAG_USER_ACTION_REQUIRED, result["assessments"][0]["flags"])

    def test_flag_no_audit(self):
        result = self.assessor.assess([_make_upgrade(has_audit=False)])
        self.assertIn(FLAG_NO_AUDIT, result["assessments"][0]["flags"])

    def test_no_flag_no_audit_when_audited(self):
        result = self.assessor.assess([_make_upgrade(has_audit=True)])
        self.assertNotIn(FLAG_NO_AUDIT, result["assessments"][0]["flags"])

    def test_flag_low_community_support(self):
        result = self.assessor.assess([_make_upgrade(community_approval_pct=40.0)])
        self.assertIn(FLAG_LOW_COMMUNITY_SUPPORT, result["assessments"][0]["flags"])

    def test_no_flag_low_community_support_when_high(self):
        result = self.assessor.assess([_make_upgrade(community_approval_pct=90.0)])
        self.assertNotIn(FLAG_LOW_COMMUNITY_SUPPORT, result["assessments"][0]["flags"])

    def test_flag_imminent_within_7_days(self):
        result = self.assessor.assess([_make_upgrade(scheduled_date_days=3)])
        self.assertIn(FLAG_IMMINENT, result["assessments"][0]["flags"])

    def test_flag_imminent_on_day_zero(self):
        result = self.assessor.assess([_make_upgrade(scheduled_date_days=0)])
        self.assertIn(FLAG_IMMINENT, result["assessments"][0]["flags"])

    def test_flag_imminent_past_event_within_7_days(self):
        result = self.assessor.assess([_make_upgrade(scheduled_date_days=-3)])
        self.assertIn(FLAG_IMMINENT, result["assessments"][0]["flags"])

    def test_no_flag_imminent_when_far(self):
        result = self.assessor.assess([_make_upgrade(scheduled_date_days=30)])
        self.assertNotIn(FLAG_IMMINENT, result["assessments"][0]["flags"])

    def test_flag_repeat_issues(self):
        result = self.assessor.assess([_make_upgrade(last_upgrade_issues_count=2)])
        self.assertIn(FLAG_REPEAT_ISSUES, result["assessments"][0]["flags"])

    def test_no_flag_repeat_issues_when_clean(self):
        result = self.assessor.assess([_make_upgrade(last_upgrade_issues_count=0)])
        self.assertNotIn(FLAG_REPEAT_ISSUES, result["assessments"][0]["flags"])

    def test_flags_is_list(self):
        result = self.assessor.assess([_make_upgrade()])
        self.assertIsInstance(result["assessments"][0]["flags"], list)

    def test_multiple_flags_possible(self):
        result = self.assessor.assess([_make_upgrade(
            user_action_required=True,
            has_audit=False,
            community_approval_pct=30.0,
            scheduled_date_days=2,
            last_upgrade_issues_count=3,
        )])
        flags = result["assessments"][0]["flags"]
        self.assertEqual(len(flags), 5)

    def test_low_community_support_boundary_exactly_60(self):
        # < 60 triggers flag
        result = self.assessor.assess([_make_upgrade(community_approval_pct=59.9)])
        self.assertIn(FLAG_LOW_COMMUNITY_SUPPORT, result["assessments"][0]["flags"])

    def test_low_community_support_boundary_60_not_triggered(self):
        result = self.assessor.assess([_make_upgrade(community_approval_pct=60.0)])
        self.assertNotIn(FLAG_LOW_COMMUNITY_SUPPORT, result["assessments"][0]["flags"])

    def test_imminent_boundary_exactly_7_days(self):
        result = self.assessor.assess([_make_upgrade(scheduled_date_days=7)])
        self.assertIn(FLAG_IMMINENT, result["assessments"][0]["flags"])

    def test_no_imminent_8_days(self):
        result = self.assessor.assess([_make_upgrade(scheduled_date_days=8)])
        self.assertNotIn(FLAG_IMMINENT, result["assessments"][0]["flags"])

    # ------------------------------------------------------------------
    # 9. Aggregates
    # ------------------------------------------------------------------

    def test_aggregates_highest_impact(self):
        u_high = _make_upgrade(protocol="HighRisk", magnitude_score=10,
                                affected_tvl_usd=1e11, has_audit=False,
                                community_approval_pct=10.0, migration_period_days=0)
        u_low = _make_upgrade(protocol="LowRisk", magnitude_score=1,
                               affected_tvl_usd=1e5, has_audit=True,
                               community_approval_pct=95.0, migration_period_days=60)
        result = self.assessor.assess([u_high, u_low])
        self.assertEqual(result["aggregates"]["highest_impact"], "HighRisk")

    def test_aggregates_smoothest(self):
        u_high = _make_upgrade(protocol="HighRisk", magnitude_score=10,
                                affected_tvl_usd=1e11, has_audit=False,
                                community_approval_pct=10.0, migration_period_days=0)
        u_low = _make_upgrade(protocol="LowRisk", magnitude_score=1,
                               affected_tvl_usd=1e4, has_audit=True,
                               community_approval_pct=100.0, migration_period_days=60,
                               historical_similar_upgrades_count=5)
        result = self.assessor.assess([u_high, u_low])
        self.assertEqual(result["aggregates"]["smoothest"], "LowRisk")

    def test_aggregates_total_affected_tvl(self):
        u1 = _make_upgrade(affected_tvl_usd=1_000_000.0)
        u2 = _make_upgrade(affected_tvl_usd=2_000_000.0)
        result = self.assessor.assess([u1, u2])
        self.assertAlmostEqual(result["aggregates"]["total_affected_tvl_usd"], 3_000_000.0, places=0)

    def test_aggregates_critical_count(self):
        u_critical = _make_upgrade(
            user_action_required=True,
            has_audit=False,
            community_approval_pct=5.0,
            migration_period_days=0,
            magnitude_score=10,
            affected_tvl_usd=1e12,
            historical_similar_upgrades_count=0,
        )
        u_smooth = _make_upgrade(
            magnitude_score=1, affected_tvl_usd=1e4,
            has_audit=True, community_approval_pct=100.0,
            migration_period_days=60, historical_similar_upgrades_count=5
        )
        result = self.assessor.assess([u_critical, u_smooth])
        self.assertGreaterEqual(result["aggregates"]["critical_count"], 1)

    def test_aggregates_imminent_count(self):
        u_imminent = _make_upgrade(scheduled_date_days=2)
        u_far = _make_upgrade(scheduled_date_days=90)
        result = self.assessor.assess([u_imminent, u_far])
        self.assertEqual(result["aggregates"]["imminent_count"], 1)

    def test_aggregates_empty_returns_defaults(self):
        result = self.assessor.assess([])
        agg = result["aggregates"]
        self.assertIsNone(agg["highest_impact"])
        self.assertIsNone(agg["smoothest"])
        self.assertEqual(agg["total_affected_tvl_usd"], 0.0)
        self.assertEqual(agg["critical_count"], 0)
        self.assertEqual(agg["imminent_count"], 0)

    def test_aggregates_total_tvl_zero_when_empty(self):
        result = self.assessor.assess([])
        self.assertEqual(result["aggregates"]["total_affected_tvl_usd"], 0.0)

    # ------------------------------------------------------------------
    # 10. Log file (ring-buffer)
    # ------------------------------------------------------------------

    def test_log_file_created(self):
        self.assessor.assess([_make_upgrade()])
        self.assertTrue(os.path.exists(self.log_file))

    def test_log_file_is_valid_json(self):
        self.assessor.assess([_make_upgrade()])
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends_entries(self):
        for i in range(4):
            self.assessor.assess([_make_upgrade(protocol=f"P{i}")])
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 4)

    def test_log_ring_buffer_cap(self):
        for _ in range(110):
            self.assessor.assess([_make_upgrade()])
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertLessEqual(len(log), 100)

    def test_log_ring_buffer_exactly_100(self):
        for _ in range(105):
            self.assessor.assess([_make_upgrade()])
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 100)

    def test_log_has_run_ts(self):
        self.assessor.assess([_make_upgrade()])
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertIn("run_ts", log[0])

    def test_log_has_assessments(self):
        self.assessor.assess([_make_upgrade()])
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertIn("assessments", log[0])

    def test_log_has_upgrade_count(self):
        self.assessor.assess([_make_upgrade(), _make_upgrade()])
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(log[0]["upgrade_count"], 2)

    # ------------------------------------------------------------------
    # 11. Custom config
    # ------------------------------------------------------------------

    def test_custom_imminent_days_threshold(self):
        config = {"imminent_days_threshold": 30}
        result = self.assessor.assess([_make_upgrade(scheduled_date_days=20)], config=config)
        self.assertIn(FLAG_IMMINENT, result["assessments"][0]["flags"])

    def test_custom_low_community_support_threshold(self):
        config = {"low_community_support_threshold": 90.0}
        result = self.assessor.assess([_make_upgrade(community_approval_pct=80.0)], config=config)
        self.assertIn(FLAG_LOW_COMMUNITY_SUPPORT, result["assessments"][0]["flags"])

    def test_custom_critical_net_risk_threshold(self):
        config = {"critical_net_risk_threshold": 10.0}
        result = self.assessor.assess([_make_upgrade(
            user_action_required=True,
            magnitude_score=5,
            has_audit=False,
            community_approval_pct=50.0,
            migration_period_days=0,
        )], config=config)
        label = result["assessments"][0]["label"]
        self.assertEqual(label, "CRITICAL_UPGRADE")

    def test_none_config_uses_defaults(self):
        result = self.assessor.assess([_make_upgrade()], config=None)
        self.assertIn("label", result["assessments"][0])

    # ------------------------------------------------------------------
    # 12. Edge cases
    # ------------------------------------------------------------------

    def test_negative_scheduled_date_past_event(self):
        result = self.assessor.assess([_make_upgrade(scheduled_date_days=-30)])
        self.assertIsNotNone(result["assessments"][0])

    def test_zero_tvl_no_crash(self):
        result = self.assessor.assess([_make_upgrade(affected_tvl_usd=0.0)])
        self.assertGreaterEqual(result["assessments"][0]["disruption_score"], 0.0)

    def test_magnitude_1_low_disruption(self):
        r1 = self.assessor.assess([_make_upgrade(magnitude_score=1)])["assessments"][0]["disruption_score"]
        r10 = self.assessor.assess([_make_upgrade(magnitude_score=10)])["assessments"][0]["disruption_score"]
        self.assertLess(r1, r10)

    def test_all_upgrade_types_accepted(self):
        upgrade_types = [
            "fee_change", "collateral_factor", "rate_model",
            "oracle", "smart_contract", "tokenomics", "governance"
        ]
        for ut in upgrade_types:
            result = self.assessor.assess([_make_upgrade(upgrade_type=ut)])
            self.assertEqual(result["assessments"][0]["upgrade_type"], ut)

    def test_user_action_false_no_flag(self):
        result = self.assessor.assess([_make_upgrade(user_action_required=False)])
        self.assertNotIn(FLAG_USER_ACTION_REQUIRED, result["assessments"][0]["flags"])

    def test_large_number_of_upgrades(self):
        upgrades = [_make_upgrade(protocol=f"P{i}") for i in range(50)]
        result = self.assessor.assess(upgrades)
        self.assertEqual(result["upgrade_count"], 50)
        self.assertEqual(len(result["assessments"]), 50)

    def test_different_data_file_path(self):
        other_log = os.path.join(self.tmp_dir, "other_upgrade_log.json")
        assessor = ProtocolUpgradeImpactAssessor(data_file=other_log)
        assessor.assess([_make_upgrade()])
        self.assertTrue(os.path.exists(other_log))

    def test_protocol_name_preserved(self):
        result = self.assessor.assess([_make_upgrade(protocol="Compound")])
        self.assertEqual(result["assessments"][0]["protocol"], "Compound")

    def test_migration_period_days_preserved(self):
        result = self.assessor.assess([_make_upgrade(migration_period_days=21)])
        self.assertEqual(result["assessments"][0]["migration_period_days"], 21)

    def test_user_action_required_preserved(self):
        result = self.assessor.assess([_make_upgrade(user_action_required=True)])
        self.assertTrue(result["assessments"][0]["user_action_required"])

    def test_has_audit_false_preserved(self):
        result = self.assessor.assess([_make_upgrade(has_audit=False)])
        self.assertFalse(result["assessments"][0]["has_audit"])


if __name__ == "__main__":
    unittest.main()
