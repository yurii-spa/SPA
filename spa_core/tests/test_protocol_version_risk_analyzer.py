"""
Tests for MP-902 ProtocolVersionRiskAnalyzer.
Run: python3 -m unittest spa_core.tests.test_protocol_version_risk_analyzer -v
"""

import json
import os
import sys
import tempfile
import time
import unittest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from spa_core.analytics.protocol_version_risk_analyzer import (
    _append_log,
    _atomic_write,
    _audit_coverage_label,
    _audit_risk,
    _build_flags,
    _composite_risk,
    _governance_safety,
    _mechanism_risk,
    _migration_risk_score,
    _migration_urgency,
    _pending_upgrade_bonus,
    _read_log,
    _recommendation,
    _risk_label,
    _tvl_migration_risk_label,
    _upgrade_risk_score,
    _version_maturity_label,
    analyze,
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _proto(
    name="Proto",
    version="v1",
    days=200,
    pending=False,
    mechanism="GOVERNANCE",
    mig_required=False,
    mig_deadline=0,
    audit_cnt=3,
    tvl_risk=0.0,
    backward=True,
):
    return {
        "name": name,
        "current_version": version,
        "days_since_last_upgrade": days,
        "pending_upgrade": pending,
        "upgrade_mechanism": mechanism,
        "migration_required": mig_required,
        "migration_deadline_days": mig_deadline,
        "audit_count_for_current_version": audit_cnt,
        "tvl_at_risk_usd": tvl_risk,
        "backward_compatible": backward,
    }


# ---------------------------------------------------------------------------
# 1. _mechanism_risk
# ---------------------------------------------------------------------------

class TestMechanismRisk(unittest.TestCase):
    def test_immutable(self):
        self.assertEqual(_mechanism_risk("IMMUTABLE"), 0)

    def test_governance(self):
        self.assertEqual(_mechanism_risk("GOVERNANCE"), 10)

    def test_timelock_only(self):
        self.assertEqual(_mechanism_risk("TIMELOCK_ONLY"), 15)

    def test_multisig(self):
        self.assertEqual(_mechanism_risk("MULTISIG"), 30)

    def test_admin_key(self):
        self.assertEqual(_mechanism_risk("ADMIN_KEY"), 50)

    def test_unknown_defaults_to_multisig(self):
        self.assertEqual(_mechanism_risk("UNKNOWN_MECH"), 30)


# ---------------------------------------------------------------------------
# 2. _pending_upgrade_bonus
# ---------------------------------------------------------------------------

class TestPendingUpgradeBonus(unittest.TestCase):
    def test_pending_true(self):
        self.assertEqual(_pending_upgrade_bonus(True), 20)

    def test_pending_false(self):
        self.assertEqual(_pending_upgrade_bonus(False), 0)


# ---------------------------------------------------------------------------
# 3. _migration_risk_score
# ---------------------------------------------------------------------------

class TestMigrationRiskScore(unittest.TestCase):
    def test_no_migration(self):
        self.assertEqual(_migration_risk_score(False, 10, 14), 0)

    def test_urgent_deadline(self):
        # deadline < urgent_days (14) → 25
        self.assertEqual(_migration_risk_score(True, 10, 14), 25)

    def test_exactly_at_urgent(self):
        # deadline == urgent_days: 14 <= 14 → 25
        self.assertEqual(_migration_risk_score(True, 14, 14), 25)

    def test_soon_deadline(self):
        # 14 < deadline < 30 → 15
        self.assertEqual(_migration_risk_score(True, 20, 14), 15)

    def test_planned_deadline(self):
        # deadline >= 30 → 10
        self.assertEqual(_migration_risk_score(True, 60, 14), 10)

    def test_far_deadline(self):
        # deadline = 100 → 10
        self.assertEqual(_migration_risk_score(True, 100, 14), 10)


# ---------------------------------------------------------------------------
# 4. _audit_risk
# ---------------------------------------------------------------------------

class TestAuditRisk(unittest.TestCase):
    def test_zero_audits(self):
        self.assertEqual(_audit_risk(0), 10)

    def test_one_audit(self):
        self.assertEqual(_audit_risk(1), 5)

    def test_two_audits(self):
        self.assertEqual(_audit_risk(2), 0)

    def test_many_audits(self):
        self.assertEqual(_audit_risk(10), 0)


# ---------------------------------------------------------------------------
# 5. _upgrade_risk_score
# ---------------------------------------------------------------------------

class TestUpgradeRiskScore(unittest.TestCase):
    def test_immutable_no_risk(self):
        score = _upgrade_risk_score("IMMUTABLE", False, False, 0, 3, 14)
        self.assertEqual(score, 0)

    def test_admin_key_pending_urgent_unaudited(self):
        # 50 + 20 + 25 + 10 = 105 → capped at 100
        score = _upgrade_risk_score("ADMIN_KEY", True, True, 5, 0, 14)
        self.assertEqual(score, 100)

    def test_governance_clean(self):
        # 10 + 0 + 0 + 0 = 10
        score = _upgrade_risk_score("GOVERNANCE", False, False, 0, 3, 14)
        self.assertEqual(score, 10)

    def test_multisig_pending_soon(self):
        # 30 + 20 + 15 + 5 = 70
        score = _upgrade_risk_score("MULTISIG", True, True, 20, 1, 14)
        self.assertEqual(score, 70)

    def test_score_never_negative(self):
        score = _upgrade_risk_score("IMMUTABLE", False, False, 0, 5, 14)
        self.assertGreaterEqual(score, 0)

    def test_score_never_above_100(self):
        score = _upgrade_risk_score("ADMIN_KEY", True, True, 1, 0, 14)
        self.assertLessEqual(score, 100)


# ---------------------------------------------------------------------------
# 6. _migration_urgency
# ---------------------------------------------------------------------------

class TestMigrationUrgency(unittest.TestCase):
    def test_no_migration_required(self):
        self.assertEqual(_migration_urgency(False, 5, 14), "NONE")

    def test_zero_deadline(self):
        self.assertEqual(_migration_urgency(True, 0, 14), "NONE")

    def test_urgent(self):
        self.assertEqual(_migration_urgency(True, 10, 14), "URGENT")

    def test_urgent_boundary(self):
        # deadline == urgent_days - 1 → URGENT
        self.assertEqual(_migration_urgency(True, 13, 14), "URGENT")

    def test_soon(self):
        self.assertEqual(_migration_urgency(True, 20, 14), "SOON")

    def test_soon_boundary(self):
        # deadline >= urgent_days and < 30 → SOON
        self.assertEqual(_migration_urgency(True, 14, 14), "SOON")

    def test_planned(self):
        self.assertEqual(_migration_urgency(True, 60, 14), "PLANNED")

    def test_planned_boundary(self):
        self.assertEqual(_migration_urgency(True, 30, 14), "PLANNED")

    def test_none_far_deadline(self):
        # deadline >= 90 → NONE
        self.assertEqual(_migration_urgency(True, 90, 14), "NONE")

    def test_none_very_far_deadline(self):
        self.assertEqual(_migration_urgency(True, 365, 14), "NONE")


# ---------------------------------------------------------------------------
# 7. _version_maturity_label
# ---------------------------------------------------------------------------

class TestVersionMaturityLabel(unittest.TestCase):
    def test_battle_tested(self):
        self.assertEqual(_version_maturity_label(400), "BATTLE_TESTED")

    def test_battle_tested_boundary(self):
        self.assertEqual(_version_maturity_label(366), "BATTLE_TESTED")

    def test_stable(self):
        self.assertEqual(_version_maturity_label(200), "STABLE")

    def test_stable_boundary(self):
        self.assertEqual(_version_maturity_label(181), "STABLE")

    def test_maturing(self):
        self.assertEqual(_version_maturity_label(120), "MATURING")

    def test_maturing_boundary(self):
        self.assertEqual(_version_maturity_label(91), "MATURING")

    def test_fresh(self):
        self.assertEqual(_version_maturity_label(30), "FRESH")

    def test_fresh_boundary(self):
        self.assertEqual(_version_maturity_label(90), "FRESH")

    def test_fresh_zero(self):
        self.assertEqual(_version_maturity_label(0), "FRESH")


# ---------------------------------------------------------------------------
# 8. _governance_safety
# ---------------------------------------------------------------------------

class TestGovernanceSafety(unittest.TestCase):
    def test_immutable(self):
        self.assertEqual(_governance_safety("IMMUTABLE"), "IMMUTABLE")

    def test_governance(self):
        self.assertEqual(_governance_safety("GOVERNANCE"), "DECENTRALIZED")

    def test_timelock_only(self):
        self.assertEqual(_governance_safety("TIMELOCK_ONLY"), "DECENTRALIZED")

    def test_multisig(self):
        self.assertEqual(_governance_safety("MULTISIG"), "SEMI_DECENTRALIZED")

    def test_admin_key(self):
        self.assertEqual(_governance_safety("ADMIN_KEY"), "CENTRALIZED")

    def test_unknown(self):
        result = _governance_safety("SOME_NEW_MECH")
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# 9. _audit_coverage_label
# ---------------------------------------------------------------------------

class TestAuditCoverageLabel(unittest.TestCase):
    def test_zero_unaudited(self):
        self.assertEqual(_audit_coverage_label(0), "UNAUDITED")

    def test_one_audited(self):
        self.assertEqual(_audit_coverage_label(1), "AUDITED")

    def test_two_audited(self):
        self.assertEqual(_audit_coverage_label(2), "AUDITED")

    def test_three_well_audited(self):
        self.assertEqual(_audit_coverage_label(3), "WELL_AUDITED")

    def test_many_well_audited(self):
        self.assertEqual(_audit_coverage_label(10), "WELL_AUDITED")


# ---------------------------------------------------------------------------
# 10. _tvl_migration_risk_label
# ---------------------------------------------------------------------------

class TestTvlMigrationRiskLabel(unittest.TestCase):
    def test_critical(self):
        self.assertEqual(_tvl_migration_risk_label(200_000_000), "CRITICAL")

    def test_critical_boundary(self):
        self.assertEqual(_tvl_migration_risk_label(100_000_001), "CRITICAL")

    def test_high(self):
        self.assertEqual(_tvl_migration_risk_label(50_000_000), "HIGH")

    def test_high_boundary(self):
        self.assertEqual(_tvl_migration_risk_label(10_000_001), "HIGH")

    def test_moderate(self):
        self.assertEqual(_tvl_migration_risk_label(5_000_000), "MODERATE")

    def test_moderate_boundary(self):
        self.assertEqual(_tvl_migration_risk_label(1_000_001), "MODERATE")

    def test_low(self):
        self.assertEqual(_tvl_migration_risk_label(500_000), "LOW")

    def test_low_boundary(self):
        self.assertEqual(_tvl_migration_risk_label(1_000_000), "LOW")

    def test_zero(self):
        self.assertEqual(_tvl_migration_risk_label(0), "LOW")


# ---------------------------------------------------------------------------
# 11. _composite_risk
# ---------------------------------------------------------------------------

class TestCompositeRisk(unittest.TestCase):
    def test_zero_risk(self):
        self.assertEqual(_composite_risk(0, 0), 0)

    def test_pure_upgrade_risk(self):
        # 50 * 0.7 + 0 * 0.3 = 35
        self.assertEqual(_composite_risk(50, 0), 35)

    def test_high_tvl_bonus(self):
        # 50 * 0.7 + 25 * 0.3 = 35 + 7.5 = 42 → int = 42
        self.assertEqual(_composite_risk(50, 50_000_000), 42)

    def test_moderate_tvl_bonus(self):
        # 50 * 0.7 + 10 * 0.3 = 35 + 3 = 38
        self.assertEqual(_composite_risk(50, 5_000_000), 38)

    def test_max_inputs_gives_bounded_result(self):
        # 100 * 0.7 + 25 * 0.3 = 77.5 → 77; still <= 100
        result = _composite_risk(100, 200_000_000)
        self.assertLessEqual(result, 100)
        self.assertGreaterEqual(result, 0)

    def test_never_negative(self):
        self.assertGreaterEqual(_composite_risk(0, 0), 0)


# ---------------------------------------------------------------------------
# 12. _risk_label
# ---------------------------------------------------------------------------

class TestRiskLabel(unittest.TestCase):
    def test_minimal(self):
        self.assertEqual(_risk_label(0), "MINIMAL")

    def test_minimal_boundary(self):
        self.assertEqual(_risk_label(20), "MINIMAL")

    def test_low(self):
        self.assertEqual(_risk_label(25), "LOW")

    def test_low_boundary(self):
        self.assertEqual(_risk_label(35), "LOW")

    def test_moderate(self):
        self.assertEqual(_risk_label(45), "MODERATE")

    def test_moderate_boundary(self):
        self.assertEqual(_risk_label(55), "MODERATE")

    def test_high(self):
        self.assertEqual(_risk_label(65), "HIGH")

    def test_high_boundary(self):
        self.assertEqual(_risk_label(75), "HIGH")

    def test_critical(self):
        self.assertEqual(_risk_label(80), "CRITICAL")

    def test_critical_max(self):
        self.assertEqual(_risk_label(100), "CRITICAL")


# ---------------------------------------------------------------------------
# 13. _build_flags
# ---------------------------------------------------------------------------

class TestBuildFlags(unittest.TestCase):
    def test_no_flags(self):
        self.assertEqual(_build_flags("NONE", False, "GOVERNANCE", 3, 0), [])

    def test_urgent_migration(self):
        flags = _build_flags("URGENT", False, "GOVERNANCE", 3, 0)
        self.assertIn("URGENT_MIGRATION", flags)

    def test_pending_upgrade(self):
        flags = _build_flags("NONE", True, "GOVERNANCE", 3, 0)
        self.assertIn("PENDING_UPGRADE", flags)

    def test_centralized_admin(self):
        flags = _build_flags("NONE", False, "ADMIN_KEY", 3, 0)
        self.assertIn("CENTRALIZED_ADMIN", flags)

    def test_unaudited_version(self):
        flags = _build_flags("NONE", False, "GOVERNANCE", 0, 0)
        self.assertIn("UNAUDITED_VERSION", flags)

    def test_high_tvl_at_risk(self):
        flags = _build_flags("NONE", False, "GOVERNANCE", 3, 15_000_000)
        self.assertIn("HIGH_TVL_AT_RISK", flags)

    def test_all_flags(self):
        flags = _build_flags("URGENT", True, "ADMIN_KEY", 0, 20_000_000)
        self.assertIn("URGENT_MIGRATION", flags)
        self.assertIn("PENDING_UPGRADE", flags)
        self.assertIn("CENTRALIZED_ADMIN", flags)
        self.assertIn("UNAUDITED_VERSION", flags)
        self.assertIn("HIGH_TVL_AT_RISK", flags)

    def test_tvl_boundary_no_flag(self):
        # exactly 10M → not > 10M → no flag
        flags = _build_flags("NONE", False, "GOVERNANCE", 3, 10_000_000)
        self.assertNotIn("HIGH_TVL_AT_RISK", flags)


# ---------------------------------------------------------------------------
# 14. _recommendation
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):
    def test_minimal(self):
        rec = _recommendation("MINIMAL", "DECENTRALIZED", "WELL_AUDITED", [], "NONE", 0)
        self.assertIn("Low upgrade risk", rec)
        self.assertIn("DECENTRALIZED", rec)

    def test_low(self):
        rec = _recommendation("LOW", "SEMI_DECENTRALIZED", "AUDITED", [], "NONE", 0)
        self.assertIn("Low upgrade risk", rec)

    def test_moderate(self):
        rec = _recommendation("MODERATE", "MULTISIG", "AUDITED", ["PENDING_UPGRADE"], "NONE", 0)
        self.assertIn("Moderate risk", rec)
        self.assertIn("1 flag", rec)

    def test_moderate_no_flags(self):
        rec = _recommendation("MODERATE", "MULTISIG", "AUDITED", [], "NONE", 0)
        self.assertIn("pending changes", rec)

    def test_high(self):
        rec = _recommendation("HIGH", "CENTRALIZED", "UNAUDITED",
                              ["CENTRALIZED_ADMIN", "UNAUDITED_VERSION"], "NONE", 0)
        self.assertIn("High upgrade risk", rec)
        self.assertIn("Reduce exposure", rec)

    def test_high_no_flags(self):
        rec = _recommendation("HIGH", "GOVERNANCE", "AUDITED", [], "NONE", 0)
        self.assertIn("multiple concerns", rec)

    def test_critical_urgent(self):
        rec = _recommendation("CRITICAL", "ADMIN_KEY", "UNAUDITED",
                              ["URGENT_MIGRATION"], "URGENT", 7)
        self.assertIn("Critical", rec)
        self.assertIn("7", rec)
        self.assertIn("URGENT migration", rec)

    def test_critical_non_urgent(self):
        rec = _recommendation("CRITICAL", "ADMIN_KEY", "UNAUDITED", ["PENDING_UPGRADE"], "NONE", 0)
        self.assertIn("Critical", rec)
        self.assertIn("Multiple critical risks", rec)


# ---------------------------------------------------------------------------
# 15. analyze() — structure
# ---------------------------------------------------------------------------

class TestAnalyzeStructure(unittest.TestCase):
    def test_empty_input(self):
        result = analyze([])
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["highest_risk_protocol"])
        self.assertEqual(result["urgent_migrations"], [])
        self.assertAlmostEqual(result["average_risk_score"], 0.0)
        self.assertIn("timestamp", result)

    def test_single_protocol_keys(self):
        result = analyze([_proto()])
        p = result["protocols"][0]
        for key in (
            "name", "current_version", "upgrade_mechanism", "upgrade_risk_score",
            "migration_urgency", "version_maturity_label", "governance_safety",
            "audit_coverage_label", "tvl_migration_risk_label", "composite_risk",
            "risk_label", "flags", "recommendation",
        ):
            self.assertIn(key, p, f"Missing key: {key}")

    def test_timestamp_recent(self):
        before = time.time()
        result = analyze([_proto()])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_result_serializable(self):
        result = analyze([_proto("Aave", mechanism="ADMIN_KEY", audit_cnt=0, tvl_risk=50e6)])
        serialized = json.dumps(result)
        parsed = json.loads(serialized)
        self.assertIn("protocols", parsed)


# ---------------------------------------------------------------------------
# 16. analyze() — calculations
# ---------------------------------------------------------------------------

class TestAnalyzeCalculations(unittest.TestCase):
    def test_highest_risk_protocol(self):
        result = analyze([
            _proto("Safe", mechanism="GOVERNANCE", audit_cnt=5, days=400),
            _proto("Risky", mechanism="ADMIN_KEY", pending=True, mig_required=True,
                   mig_deadline=5, audit_cnt=0, tvl_risk=50e6),
        ])
        self.assertEqual(result["highest_risk_protocol"], "Risky")

    def test_average_risk_score_single(self):
        result = analyze([_proto("A", mechanism="IMMUTABLE", audit_cnt=5)])
        self.assertAlmostEqual(result["average_risk_score"], result["protocols"][0]["composite_risk"])

    def test_average_risk_score_two(self):
        result = analyze([
            _proto("A", mechanism="IMMUTABLE", audit_cnt=5),
            _proto("B", mechanism="ADMIN_KEY", pending=True, audit_cnt=0),
        ])
        scores = [p["composite_risk"] for p in result["protocols"]]
        expected = sum(scores) / len(scores)
        self.assertAlmostEqual(result["average_risk_score"], expected)

    def test_urgent_migrations_list(self):
        result = analyze([
            _proto("A", mig_required=True, mig_deadline=5),
            _proto("B", mig_required=True, mig_deadline=7),
            _proto("C", mig_required=False),
        ])
        self.assertIn("A", result["urgent_migrations"])
        self.assertIn("B", result["urgent_migrations"])
        self.assertNotIn("C", result["urgent_migrations"])

    def test_no_urgent_migrations(self):
        result = analyze([_proto()])
        self.assertEqual(result["urgent_migrations"], [])

    def test_immutable_protocol_zero_risk(self):
        result = analyze([_proto("Yearn", mechanism="IMMUTABLE", audit_cnt=5, days=500)])
        p = result["protocols"][0]
        self.assertEqual(p["upgrade_risk_score"], 0)
        self.assertEqual(p["migration_urgency"], "NONE")
        self.assertEqual(p["governance_safety"], "IMMUTABLE")
        self.assertNotIn("URGENT_MIGRATION", p["flags"])
        self.assertNotIn("CENTRALIZED_ADMIN", p["flags"])

    def test_admin_key_flag_present(self):
        result = analyze([_proto("Bad", mechanism="ADMIN_KEY")])
        self.assertIn("CENTRALIZED_ADMIN", result["protocols"][0]["flags"])

    def test_unaudited_flag(self):
        result = analyze([_proto("Unaudited", audit_cnt=0)])
        self.assertIn("UNAUDITED_VERSION", result["protocols"][0]["flags"])

    def test_pending_upgrade_flag(self):
        result = analyze([_proto("Pending", pending=True)])
        self.assertIn("PENDING_UPGRADE", result["protocols"][0]["flags"])

    def test_high_tvl_flag(self):
        result = analyze([_proto("BigTVL", tvl_risk=20_000_000)])
        self.assertIn("HIGH_TVL_AT_RISK", result["protocols"][0]["flags"])

    def test_version_passes_through(self):
        result = analyze([_proto("X", version="v3.2.1")])
        self.assertEqual(result["protocols"][0]["current_version"], "v3.2.1")

    def test_battle_tested_maturity(self):
        result = analyze([_proto("X", days=400)])
        self.assertEqual(result["protocols"][0]["version_maturity_label"], "BATTLE_TESTED")

    def test_fresh_maturity(self):
        result = analyze([_proto("X", days=30)])
        self.assertEqual(result["protocols"][0]["version_maturity_label"], "FRESH")

    def test_audit_coverage_well_audited(self):
        result = analyze([_proto("X", audit_cnt=5)])
        self.assertEqual(result["protocols"][0]["audit_coverage_label"], "WELL_AUDITED")

    def test_tvl_critical_label(self):
        result = analyze([_proto("X", tvl_risk=200_000_000)])
        self.assertEqual(result["protocols"][0]["tvl_migration_risk_label"], "CRITICAL")

    def test_composite_risk_bounded(self):
        result = analyze([_proto("X", mechanism="ADMIN_KEY", pending=True,
                                 mig_required=True, mig_deadline=3, audit_cnt=0,
                                 tvl_risk=500e6)])
        comp = result["protocols"][0]["composite_risk"]
        self.assertGreaterEqual(comp, 0)
        self.assertLessEqual(comp, 100)


# ---------------------------------------------------------------------------
# 17. Custom config
# ---------------------------------------------------------------------------

class TestCustomConfig(unittest.TestCase):
    def test_custom_urgent_days_looser(self):
        # With urgent_days=7, deadline=10 → NOT URGENT (SOON instead)
        result = analyze(
            [_proto("A", mig_required=True, mig_deadline=10)],
            config={"urgent_migration_days": 7},
        )
        self.assertEqual(result["protocols"][0]["migration_urgency"], "SOON")

    def test_custom_urgent_days_stricter(self):
        # With urgent_days=30, deadline=25 → URGENT
        result = analyze(
            [_proto("A", mig_required=True, mig_deadline=25)],
            config={"urgent_migration_days": 30},
        )
        self.assertEqual(result["protocols"][0]["migration_urgency"], "URGENT")

    def test_none_config_uses_defaults(self):
        result = analyze([_proto()], config=None)
        self.assertIsInstance(result, dict)

    def test_empty_config_uses_defaults(self):
        result = analyze([_proto()], config={})
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# 18. Persistence
# ---------------------------------------------------------------------------

class TestPersistenceVRA(unittest.TestCase):
    def _tmpdir(self):
        return tempfile.mkdtemp()

    def test_atomic_write_and_read(self):
        d = self._tmpdir()
        path = os.path.join(d, "test.json")
        _atomic_write(path, [{"x": 42}])
        data = _read_log(path)
        self.assertEqual(data, [{"x": 42}])

    def test_read_missing_file(self):
        d = self._tmpdir()
        path = os.path.join(d, "missing.json")
        self.assertEqual(_read_log(path), [])

    def test_read_invalid_json(self):
        d = self._tmpdir()
        path = os.path.join(d, "bad.json")
        with open(path, "w") as f:
            f.write("{{NOT JSON")
        self.assertEqual(_read_log(path), [])

    def test_read_non_list_json(self):
        d = self._tmpdir()
        path = os.path.join(d, "obj.json")
        _atomic_write(path, {"key": "val"})
        self.assertEqual(_read_log(path), [])

    def test_append_creates_file(self):
        d = self._tmpdir()
        path = os.path.join(d, "new.json")
        _append_log(path, {"entry": 1})
        data = _read_log(path)
        self.assertEqual(len(data), 1)

    def test_ring_buffer_cap(self):
        d = self._tmpdir()
        path = os.path.join(d, "ring.json")
        for i in range(110):
            _append_log(path, {"i": i})
        data = _read_log(path)
        self.assertEqual(len(data), 100)
        self.assertEqual(data[0]["i"], 10)
        self.assertEqual(data[-1]["i"], 109)

    def test_multiple_appends(self):
        d = self._tmpdir()
        path = os.path.join(d, "multi.json")
        _append_log(path, {"n": 1})
        _append_log(path, {"n": 2})
        data = _read_log(path)
        self.assertEqual(len(data), 2)

    def test_atomic_write_creates_dirs(self):
        d = self._tmpdir()
        path = os.path.join(d, "sub", "path", "file.json")
        _atomic_write(path, [])
        self.assertTrue(os.path.exists(path))


# ---------------------------------------------------------------------------
# 19. Integration scenario
# ---------------------------------------------------------------------------

class TestIntegrationScenario(unittest.TestCase):
    def test_full_realistic_scenario(self):
        protocols = [
            # Well-governed, battle-tested, audited → MINIMAL
            _proto("Aave V3", mechanism="GOVERNANCE", days=400, audit_cnt=5, tvl_risk=0),
            # Admin key, pending upgrade, unaudited, high TVL → CRITICAL
            _proto("BadActor", mechanism="ADMIN_KEY", pending=True,
                   mig_required=True, mig_deadline=5, audit_cnt=0, tvl_risk=50e6),
            # Multisig, soon migration, moderate tvl → HIGH
            _proto("MedRisk", mechanism="MULTISIG", days=60, pending=False,
                   mig_required=True, mig_deadline=20, audit_cnt=2, tvl_risk=2e6),
        ]
        result = analyze(protocols)

        aave = next(p for p in result["protocols"] if p["name"] == "Aave V3")
        bad = next(p for p in result["protocols"] if p["name"] == "BadActor")
        med = next(p for p in result["protocols"] if p["name"] == "MedRisk")

        self.assertIn(aave["risk_label"], ("MINIMAL", "LOW"))
        self.assertIn(bad["risk_label"], ("HIGH", "CRITICAL"))
        self.assertIn("CENTRALIZED_ADMIN", bad["flags"])
        self.assertIn("UNAUDITED_VERSION", bad["flags"])
        self.assertIn("HIGH_TVL_AT_RISK", bad["flags"])
        self.assertIn("URGENT_MIGRATION", bad["flags"])

        self.assertEqual(result["highest_risk_protocol"], "BadActor")
        self.assertIn("BadActor", result["urgent_migrations"])
        self.assertGreater(result["average_risk_score"], 0)

    def test_all_immutable_protocols(self):
        result = analyze([
            _proto("A", mechanism="IMMUTABLE", audit_cnt=5, days=500),
            _proto("B", mechanism="IMMUTABLE", audit_cnt=3, days=400),
        ])
        for p in result["protocols"]:
            self.assertEqual(p["upgrade_risk_score"], 0)
            self.assertEqual(p["migration_urgency"], "NONE")
            self.assertNotIn("CENTRALIZED_ADMIN", p["flags"])
        self.assertEqual(result["urgent_migrations"], [])

    def test_recommendation_is_non_empty(self):
        result = analyze([_proto("X")])
        rec = result["protocols"][0]["recommendation"]
        self.assertIsInstance(rec, str)
        self.assertGreater(len(rec), 0)


if __name__ == "__main__":
    unittest.main()
