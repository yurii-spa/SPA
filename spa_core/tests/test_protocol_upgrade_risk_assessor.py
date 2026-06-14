"""
Tests for MP-687: ProtocolUpgradeRiskAssessor
60+ tests covering all logic branches.
Uses unittest only (pure stdlib).
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.protocol_upgrade_risk_assessor import (
    UpgradeProposal,
    UpgradeRiskReport,
    _code_change_risk,
    _audit_risk,
    _governance_risk,
    _operational_risk,
    _composite_risk,
    _risk_category,
    _recommendation,
    _action_items,
    assess,
    assess_batch,
    save_results,
    load_history,
)


def make_proposal(
    proposal_id="PROP-TEST",
    protocol="TestProto",
    upgrade_type="PARAMETER_CHANGE",
    lines_changed=10,
    audit_status="AUDITED",
    timelock_hours=72,
    has_rollback=True,
    affected_tvl_usd=1_000_000,
    community_vote_pct=75.0,
    days_since_last_upgrade=180,
):
    return UpgradeProposal(
        proposal_id=proposal_id,
        protocol=protocol,
        upgrade_type=upgrade_type,
        lines_changed=lines_changed,
        audit_status=audit_status,
        timelock_hours=timelock_hours,
        has_rollback=has_rollback,
        affected_tvl_usd=affected_tvl_usd,
        community_vote_pct=community_vote_pct,
        days_since_last_upgrade=days_since_last_upgrade,
    )


class TestCodeChangeRisk(unittest.TestCase):
    def test_full_rewrite(self):
        p = make_proposal(upgrade_type="FULL_REWRITE")
        self.assertAlmostEqual(_code_change_risk(p), 0.9)

    def test_migration(self):
        p = make_proposal(upgrade_type="MIGRATION")
        self.assertAlmostEqual(_code_change_risk(p), 0.7)

    def test_proxy_upgrade_zero_lines(self):
        p = make_proposal(upgrade_type="PROXY_UPGRADE", lines_changed=0)
        self.assertAlmostEqual(_code_change_risk(p), 0.2)

    def test_proxy_upgrade_1000_lines(self):
        p = make_proposal(upgrade_type="PROXY_UPGRADE", lines_changed=1000)
        expected = min(1.0, 0.2 + 1000 / 5000.0)
        self.assertAlmostEqual(_code_change_risk(p), expected)

    def test_proxy_upgrade_5000_lines(self):
        p = make_proposal(upgrade_type="PROXY_UPGRADE", lines_changed=5000)
        self.assertAlmostEqual(_code_change_risk(p), 1.0)

    def test_proxy_upgrade_capped_at_1(self):
        p = make_proposal(upgrade_type="PROXY_UPGRADE", lines_changed=50000)
        self.assertAlmostEqual(_code_change_risk(p), 1.0)

    def test_proxy_upgrade_4000_lines(self):
        p = make_proposal(upgrade_type="PROXY_UPGRADE", lines_changed=4000)
        expected = min(1.0, 0.2 + 4000 / 5000.0)
        self.assertAlmostEqual(_code_change_risk(p), expected)

    def test_parameter_change_zero_lines(self):
        p = make_proposal(upgrade_type="PARAMETER_CHANGE", lines_changed=0)
        self.assertAlmostEqual(_code_change_risk(p), 0.0)

    def test_parameter_change_100_lines(self):
        p = make_proposal(upgrade_type="PARAMETER_CHANGE", lines_changed=100)
        expected = min(0.3, 100 / 500.0)
        self.assertAlmostEqual(_code_change_risk(p), expected)

    def test_parameter_change_500_lines_cap(self):
        p = make_proposal(upgrade_type="PARAMETER_CHANGE", lines_changed=500)
        self.assertAlmostEqual(_code_change_risk(p), 0.3)

    def test_parameter_change_capped_at_0_3(self):
        p = make_proposal(upgrade_type="PARAMETER_CHANGE", lines_changed=10000)
        self.assertAlmostEqual(_code_change_risk(p), 0.3)


class TestAuditRisk(unittest.TestCase):
    def test_unaudited(self):
        p = make_proposal(audit_status="UNAUDITED")
        self.assertAlmostEqual(_audit_risk(p), 0.9)

    def test_in_progress(self):
        p = make_proposal(audit_status="IN_PROGRESS")
        self.assertAlmostEqual(_audit_risk(p), 0.6)

    def test_audited(self):
        p = make_proposal(audit_status="AUDITED")
        self.assertAlmostEqual(_audit_risk(p), 0.2)

    def test_multi_audited(self):
        p = make_proposal(audit_status="MULTI_AUDITED")
        self.assertAlmostEqual(_audit_risk(p), 0.05)

    def test_unknown_audit_defaults_high(self):
        p = make_proposal(audit_status="UNKNOWN_STATUS")
        self.assertAlmostEqual(_audit_risk(p), 0.9)


class TestGovernanceRisk(unittest.TestCase):
    def test_base_case(self):
        # vote=50, days=180 → no adjustments → 0.3
        p = make_proposal(community_vote_pct=50, days_since_last_upgrade=180)
        self.assertAlmostEqual(_governance_risk(p), 0.3)

    def test_low_vote_below_10(self):
        p = make_proposal(community_vote_pct=5.0, days_since_last_upgrade=180)
        self.assertAlmostEqual(_governance_risk(p), 0.6)

    def test_low_vote_exactly_10_not_triggered(self):
        # < 10 triggers the +0.3; == 10 does not
        p = make_proposal(community_vote_pct=10.0, days_since_last_upgrade=180)
        self.assertAlmostEqual(_governance_risk(p), 0.3)

    def test_high_vote_above_66(self):
        p = make_proposal(community_vote_pct=80.0, days_since_last_upgrade=180)
        self.assertAlmostEqual(_governance_risk(p), 0.15)

    def test_high_vote_exactly_66_not_triggered(self):
        # > 66 triggers -0.15; == 66 does not
        p = make_proposal(community_vote_pct=66.0, days_since_last_upgrade=180)
        self.assertAlmostEqual(_governance_risk(p), 0.3)

    def test_recent_upgrade_adds_0_2(self):
        p = make_proposal(community_vote_pct=50.0, days_since_last_upgrade=10)
        self.assertAlmostEqual(_governance_risk(p), 0.5)

    def test_recent_upgrade_exactly_30_not_triggered(self):
        p = make_proposal(community_vote_pct=50.0, days_since_last_upgrade=30)
        self.assertAlmostEqual(_governance_risk(p), 0.3)

    def test_combined_low_vote_and_recent_upgrade(self):
        p = make_proposal(community_vote_pct=5.0, days_since_last_upgrade=10)
        # 0.3 + 0.3 + 0.2 = 0.8
        self.assertAlmostEqual(_governance_risk(p), 0.8)

    def test_clamped_max(self):
        # Worst case: low_vote (+0.3), recent (+0.2) → 0.8, well under 0.95
        p = make_proposal(community_vote_pct=1.0, days_since_last_upgrade=1)
        result = _governance_risk(p)
        self.assertLessEqual(result, 0.95)
        self.assertGreaterEqual(result, 0.05)

    def test_clamped_min(self):
        # Best case: high vote (-0.15) → 0.15, well above 0.05
        p = make_proposal(community_vote_pct=99.0, days_since_last_upgrade=180)
        result = _governance_risk(p)
        self.assertGreaterEqual(result, 0.05)


class TestOperationalRisk(unittest.TestCase):
    def test_base_no_adjustments(self):
        # timelock < 48 (so no -0.2), no rollback, timelock > 0 → base = 0.5
        p = make_proposal(timelock_hours=24, has_rollback=False)
        self.assertAlmostEqual(_operational_risk(p), 0.5)

    def test_timelock_gte_48_reduces(self):
        p = make_proposal(timelock_hours=48, has_rollback=False)
        self.assertAlmostEqual(_operational_risk(p), 0.3)

    def test_rollback_reduces(self):
        p = make_proposal(timelock_hours=24, has_rollback=True)
        self.assertAlmostEqual(_operational_risk(p), 0.3)

    def test_both_timelock_and_rollback(self):
        p = make_proposal(timelock_hours=72, has_rollback=True)
        # 0.5 - 0.2 - 0.2 = 0.1
        self.assertAlmostEqual(_operational_risk(p), 0.1)

    def test_timelock_zero_adds_0_3(self):
        p = make_proposal(timelock_hours=0, has_rollback=False)
        # 0.5 + 0.3 = 0.8
        self.assertAlmostEqual(_operational_risk(p), 0.8)

    def test_timelock_zero_with_rollback(self):
        p = make_proposal(timelock_hours=0, has_rollback=True)
        # 0.5 + 0.3 - 0.2 = 0.6
        self.assertAlmostEqual(_operational_risk(p), 0.6)

    def test_clamped_min(self):
        p = make_proposal(timelock_hours=72, has_rollback=True)
        result = _operational_risk(p)
        self.assertGreaterEqual(result, 0.05)

    def test_clamped_max(self):
        # Worst: timelock=0, no rollback → 0.8, well under 0.95
        p = make_proposal(timelock_hours=0, has_rollback=False)
        result = _operational_risk(p)
        self.assertLessEqual(result, 0.95)

    def test_timelock_exactly_48(self):
        p = make_proposal(timelock_hours=48, has_rollback=False)
        # >= 48 → -0.2 applied → 0.3
        self.assertAlmostEqual(_operational_risk(p), 0.3)

    def test_timelock_47_no_reduction(self):
        p = make_proposal(timelock_hours=47, has_rollback=False)
        self.assertAlmostEqual(_operational_risk(p), 0.5)


class TestCompositeRisk(unittest.TestCase):
    def test_all_zeros(self):
        self.assertAlmostEqual(_composite_risk(0, 0, 0, 0), 0.0)

    def test_all_ones(self):
        self.assertAlmostEqual(_composite_risk(1, 1, 1, 1), 1.0)

    def test_weighted_sum(self):
        # code=0.4, audit=0.6, gov=0.2, ops=0.8
        # = 0.4*0.30 + 0.6*0.35 + 0.2*0.15 + 0.8*0.20
        expected = 0.4*0.30 + 0.6*0.35 + 0.2*0.15 + 0.8*0.20
        self.assertAlmostEqual(_composite_risk(0.4, 0.6, 0.2, 0.8), expected)

    def test_weights_sum_to_one(self):
        # composite(1,1,1,1) should equal 1.0
        self.assertAlmostEqual(_composite_risk(1, 1, 1, 1), 1.0)


class TestRiskCategory(unittest.TestCase):
    def test_routine_threshold(self):
        self.assertEqual(_risk_category(0.0), "ROUTINE")
        self.assertEqual(_risk_category(0.24), "ROUTINE")

    def test_elevated_threshold(self):
        self.assertEqual(_risk_category(0.25), "ELEVATED")
        self.assertEqual(_risk_category(0.44), "ELEVATED")

    def test_high_threshold(self):
        self.assertEqual(_risk_category(0.45), "HIGH")
        self.assertEqual(_risk_category(0.64), "HIGH")

    def test_critical_threshold(self):
        self.assertEqual(_risk_category(0.65), "CRITICAL")
        self.assertEqual(_risk_category(1.0), "CRITICAL")

    def test_boundary_exactly_0_25(self):
        self.assertEqual(_risk_category(0.25), "ELEVATED")

    def test_boundary_exactly_0_45(self):
        self.assertEqual(_risk_category(0.45), "HIGH")

    def test_boundary_exactly_0_65(self):
        self.assertEqual(_risk_category(0.65), "CRITICAL")


class TestRecommendation(unittest.TestCase):
    def test_routine_monitor(self):
        self.assertEqual(_recommendation("ROUTINE"), "MONITOR")

    def test_elevated_pause(self):
        self.assertEqual(_recommendation("ELEVATED"), "PAUSE_NEW_DEPOSITS")

    def test_high_reduce(self):
        self.assertEqual(_recommendation("HIGH"), "REDUCE_EXPOSURE")

    def test_critical_exit(self):
        self.assertEqual(_recommendation("CRITICAL"), "EXIT")


class TestActionItems(unittest.TestCase):
    def _make_critical_proposal(self):
        return make_proposal(
            upgrade_type="FULL_REWRITE",
            audit_status="UNAUDITED",
            timelock_hours=0,
            has_rollback=False,
        )

    def test_unaudited_audit_wait(self):
        p = make_proposal(audit_status="UNAUDITED")
        items = _action_items(p, "ELEVATED")
        self.assertTrue(any("audit" in i.lower() for i in items))

    def test_in_progress_audit_wait(self):
        p = make_proposal(audit_status="IN_PROGRESS")
        items = _action_items(p, "ELEVATED")
        self.assertTrue(any("audit" in i.lower() for i in items))

    def test_audited_no_audit_wait(self):
        p = make_proposal(audit_status="AUDITED")
        items = _action_items(p, "ROUTINE")
        self.assertFalse(any("audit" in i.lower() for i in items))

    def test_short_timelock_warning(self):
        p = make_proposal(timelock_hours=12)
        items = _action_items(p, "ELEVATED")
        self.assertTrue(any("timelock" in i.lower() for i in items))

    def test_long_timelock_no_warning(self):
        p = make_proposal(timelock_hours=72)
        items = _action_items(p, "ROUTINE")
        self.assertFalse(any("Short timelock" in i for i in items))

    def test_no_rollback_warning(self):
        p = make_proposal(has_rollback=False)
        items = _action_items(p, "ELEVATED")
        self.assertTrue(any("rollback" in i.lower() for i in items))

    def test_has_rollback_no_warning(self):
        p = make_proposal(has_rollback=True)
        items = _action_items(p, "ROUTINE")
        self.assertFalse(any("No rollback" in i for i in items))

    def test_full_rewrite_warning(self):
        p = make_proposal(upgrade_type="FULL_REWRITE")
        items = _action_items(p, "HIGH")
        self.assertTrue(any("Full rewrite" in i or "rewrite" in i.lower() for i in items))

    def test_critical_exit_action(self):
        p = self._make_critical_proposal()
        items = _action_items(p, "CRITICAL")
        self.assertTrue(any("Exit" in i for i in items))

    def test_routine_monitoring_action(self):
        p = make_proposal(audit_status="AUDITED", timelock_hours=72, has_rollback=True)
        items = _action_items(p, "ROUTINE")
        self.assertTrue(any("Routine" in i for i in items))


class TestAssess(unittest.TestCase):
    def test_returns_upgrade_risk_report(self):
        report = assess(make_proposal())
        self.assertIsInstance(report, UpgradeRiskReport)

    def test_proposal_id_preserved(self):
        p = make_proposal(proposal_id="PROP-XYZ")
        self.assertEqual(assess(p).proposal_id, "PROP-XYZ")

    def test_parameter_change_audited_good_timelock_routine(self):
        p = make_proposal(
            upgrade_type="PARAMETER_CHANGE",
            lines_changed=10,
            audit_status="MULTI_AUDITED",
            timelock_hours=72,
            has_rollback=True,
            community_vote_pct=80.0,
            days_since_last_upgrade=180,
        )
        report = assess(p)
        self.assertEqual(report.risk_category, "ROUTINE")
        self.assertEqual(report.recommendation, "MONITOR")

    def test_full_rewrite_unaudited_no_timelock_critical(self):
        p = make_proposal(
            upgrade_type="FULL_REWRITE",
            lines_changed=20000,
            audit_status="UNAUDITED",
            timelock_hours=0,
            has_rollback=False,
            community_vote_pct=5.0,
            days_since_last_upgrade=5,
        )
        report = assess(p)
        self.assertEqual(report.risk_category, "CRITICAL")
        self.assertEqual(report.recommendation, "EXIT")

    def test_tvl_at_risk_computed(self):
        p = make_proposal(affected_tvl_usd=10_000_000)
        report = assess(p)
        self.assertAlmostEqual(report.tvl_at_risk_usd, 10_000_000 * report.composite_risk)

    def test_composite_risk_between_0_and_1(self):
        p = make_proposal()
        report = assess(p)
        self.assertGreaterEqual(report.composite_risk, 0.0)
        self.assertLessEqual(report.composite_risk, 1.0)

    def test_action_items_is_list(self):
        self.assertIsInstance(assess(make_proposal()).action_items, list)

    def test_risk_fields_match_helpers(self):
        p = make_proposal()
        report = assess(p)
        self.assertAlmostEqual(report.code_change_risk, _code_change_risk(p))
        self.assertAlmostEqual(report.audit_risk, _audit_risk(p))
        self.assertAlmostEqual(report.governance_risk, _governance_risk(p))
        self.assertAlmostEqual(report.operational_risk, _operational_risk(p))


class TestAssessBatch(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(assess_batch([]), [])

    def test_single_proposal(self):
        result = assess_batch([make_proposal()])
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], UpgradeRiskReport)

    def test_multiple_proposals(self):
        proposals = [make_proposal(proposal_id=f"P{i}") for i in range(5)]
        result = assess_batch(proposals)
        self.assertEqual(len(result), 5)

    def test_preserves_order(self):
        p1 = make_proposal(proposal_id="A")
        p2 = make_proposal(proposal_id="B")
        result = assess_batch([p1, p2])
        self.assertEqual(result[0].proposal_id, "A")
        self.assertEqual(result[1].proposal_id, "B")


class TestSaveAndLoadHistory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = Path(self.tmpdir) / "upgrade_risk_log.json"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_report(self, proposal_id="PROP-001"):
        return assess(make_proposal(proposal_id=proposal_id))

    def test_load_missing_returns_empty(self):
        self.assertEqual(load_history(self.data_file), [])

    def test_save_then_load(self):
        save_results(self._make_report(), self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["proposal_id"], "PROP-001")

    def test_save_multiple(self):
        for i in range(5):
            save_results(self._make_report(f"P{i}"), self.data_file)
        self.assertEqual(len(load_history(self.data_file)), 5)

    def test_ring_buffer_cap(self):
        from spa_core.analytics.protocol_upgrade_risk_assessor import MAX_ENTRIES
        for i in range(MAX_ENTRIES + 10):
            save_results(self._make_report(f"P{i}"), self.data_file)
        self.assertEqual(len(load_history(self.data_file)), MAX_ENTRIES)

    def test_ring_buffer_keeps_newest(self):
        from spa_core.analytics.protocol_upgrade_risk_assessor import MAX_ENTRIES
        for i in range(MAX_ENTRIES + 5):
            save_results(self._make_report(f"P{i}"), self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(history[-1]["proposal_id"], f"P{MAX_ENTRIES + 4}")

    def test_atomic_write_no_tmp_left(self):
        save_results(self._make_report(), self.data_file)
        self.assertFalse(self.data_file.with_suffix(".tmp").exists())

    def test_save_creates_parent_dir(self):
        nested = Path(self.tmpdir) / "nested" / "deep" / "upgrade_risk_log.json"
        save_results(self._make_report(), nested)
        self.assertTrue(nested.exists())

    def test_saved_json_valid(self):
        save_results(self._make_report(), self.data_file)
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)
        self.assertIsInstance(data[0], dict)

    def test_load_invalid_json_returns_empty(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.data_file.write_text("{bad json}")
        self.assertEqual(load_history(self.data_file), [])

    def test_report_fields_saved(self):
        save_results(self._make_report(), self.data_file)
        entry = load_history(self.data_file)[0]
        for field in ["proposal_id", "protocol", "upgrade_type", "code_change_risk",
                      "audit_risk", "governance_risk", "operational_risk",
                      "composite_risk", "risk_category", "tvl_at_risk_usd",
                      "recommendation", "action_items", "timestamp"]:
            self.assertIn(field, entry)


if __name__ == "__main__":
    unittest.main(verbosity=2)
