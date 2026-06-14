"""
Tests for MP-857: ProtocolUpgradeRiskMonitor
>=65 tests covering all scoring logic branches, edge cases, aggregates,
log append, and CLI helpers.
Uses unittest only (pure stdlib).
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_upgrade_risk_monitor import (
    analyze,
    _timelock_safety,
    _governance_safety,
    _audit_safety,
    _track_record_safety,
    _code_change_penalty,
    _risk_level,
    _recommendation,
    _key_risk_factors,
    _append_log,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upgrade(
    protocol="TestProto",
    upgrade_status="PENDING",
    timelock_hours=48.0,
    governance_approval_pct=75.0,
    audit_coverage_pct=90.0,
    auditor_count=2,
    days_since_last_incident=200,
    code_change_size="MINOR",
    previous_upgrade_success_rate=1.0,
):
    return {
        "protocol": protocol,
        "upgrade_status": upgrade_status,
        "timelock_hours": timelock_hours,
        "governance_approval_pct": governance_approval_pct,
        "audit_coverage_pct": audit_coverage_pct,
        "auditor_count": auditor_count,
        "days_since_last_incident": days_since_last_incident,
        "code_change_size": code_change_size,
        "previous_upgrade_success_rate": previous_upgrade_success_rate,
    }


# ---------------------------------------------------------------------------
# _timelock_safety
# ---------------------------------------------------------------------------

class TestTimelockSafety(unittest.TestCase):

    def test_gte_168_returns_25(self):
        self.assertEqual(_timelock_safety(168), 25)

    def test_exactly_168(self):
        self.assertEqual(_timelock_safety(168.0), 25)

    def test_above_168(self):
        self.assertEqual(_timelock_safety(336), 25)

    def test_gte_72_lt_168_returns_20(self):
        self.assertEqual(_timelock_safety(72), 20)
        self.assertEqual(_timelock_safety(100), 20)
        self.assertEqual(_timelock_safety(167), 20)

    def test_gte_48_lt_72_returns_15(self):
        self.assertEqual(_timelock_safety(48), 15)
        self.assertEqual(_timelock_safety(60), 15)
        self.assertEqual(_timelock_safety(71), 15)

    def test_gte_24_lt_48_returns_10(self):
        self.assertEqual(_timelock_safety(24), 10)
        self.assertEqual(_timelock_safety(36), 10)
        self.assertEqual(_timelock_safety(47), 10)

    def test_gte_12_lt_24_returns_5(self):
        self.assertEqual(_timelock_safety(12), 5)
        self.assertEqual(_timelock_safety(18), 5)
        self.assertEqual(_timelock_safety(23), 5)

    def test_lt_12_returns_0(self):
        self.assertEqual(_timelock_safety(0), 0)
        self.assertEqual(_timelock_safety(6), 0)
        self.assertEqual(_timelock_safety(11.9), 0)


# ---------------------------------------------------------------------------
# _governance_safety
# ---------------------------------------------------------------------------

class TestGovernanceSafety(unittest.TestCase):

    def test_gte_80_returns_25(self):
        self.assertEqual(_governance_safety(80), 25)
        self.assertEqual(_governance_safety(100), 25)

    def test_gte_60_lt_80_returns_20(self):
        self.assertEqual(_governance_safety(60), 20)
        self.assertEqual(_governance_safety(70), 20)
        self.assertEqual(_governance_safety(79), 20)

    def test_gte_40_lt_60_returns_15(self):
        self.assertEqual(_governance_safety(40), 15)
        self.assertEqual(_governance_safety(50), 15)
        self.assertEqual(_governance_safety(59), 15)

    def test_gte_20_lt_40_returns_8(self):
        self.assertEqual(_governance_safety(20), 8)
        self.assertEqual(_governance_safety(30), 8)
        self.assertEqual(_governance_safety(39), 8)

    def test_lt_20_returns_0(self):
        self.assertEqual(_governance_safety(0), 0)
        self.assertEqual(_governance_safety(10), 0)
        self.assertEqual(_governance_safety(19.9), 0)


# ---------------------------------------------------------------------------
# _audit_safety
# ---------------------------------------------------------------------------

class TestAuditSafety(unittest.TestCase):

    def test_high_coverage_multi_auditor_returns_25(self):
        self.assertEqual(_audit_safety(95, 2), 25)
        self.assertEqual(_audit_safety(100, 3), 25)

    def test_high_coverage_single_auditor_returns_20(self):
        # coverage >= 95 but auditor_count < 2 falls through to >= 80 branch
        self.assertEqual(_audit_safety(95, 1), 20)

    def test_gte_80_lt_95_returns_20(self):
        self.assertEqual(_audit_safety(80, 1), 20)
        self.assertEqual(_audit_safety(90, 2), 20)

    def test_gte_60_lt_80_returns_15(self):
        self.assertEqual(_audit_safety(60, 1), 15)
        self.assertEqual(_audit_safety(70, 2), 15)
        self.assertEqual(_audit_safety(79, 1), 15)

    def test_gte_40_lt_60_returns_10(self):
        self.assertEqual(_audit_safety(40, 1), 10)
        self.assertEqual(_audit_safety(55, 3), 10)

    def test_gte_20_lt_40_returns_5(self):
        self.assertEqual(_audit_safety(20, 1), 5)
        self.assertEqual(_audit_safety(30, 2), 5)

    def test_lt_20_returns_0(self):
        self.assertEqual(_audit_safety(0, 0), 0)
        self.assertEqual(_audit_safety(10, 1), 0)
        self.assertEqual(_audit_safety(19, 2), 0)


# ---------------------------------------------------------------------------
# _track_record_safety
# ---------------------------------------------------------------------------

class TestTrackRecordSafety(unittest.TestCase):

    def test_perfect_rate_long_incident_free(self):
        # base=15, bonus=10 -> 25
        self.assertEqual(_track_record_safety(1.0, 365), 25)

    def test_capped_at_25(self):
        self.assertEqual(_track_record_safety(1.0, 400), 25)

    def test_rate_gte_09(self):
        self.assertEqual(_track_record_safety(0.9, 365), 22)   # 12+10
        self.assertEqual(_track_record_safety(0.95, 0), 12)    # 12+0

    def test_rate_gte_075(self):
        self.assertEqual(_track_record_safety(0.75, 180), 15)  # 8+7
        self.assertEqual(_track_record_safety(0.8, 90), 13)    # 8+5

    def test_rate_gte_05(self):
        self.assertEqual(_track_record_safety(0.5, 30), 7)     # 4+3
        self.assertEqual(_track_record_safety(0.6, 0), 4)      # 4+0

    def test_rate_lt_05(self):
        self.assertEqual(_track_record_safety(0.4, 365), 10)   # 0+10
        self.assertEqual(_track_record_safety(0.0, 0), 0)

    def test_days_since_incident_tiers(self):
        # base=15 (rate=1.0)
        self.assertEqual(_track_record_safety(1.0, 364), 22)   # 15+7 (>=180)
        self.assertEqual(_track_record_safety(1.0, 90), 20)    # 15+5 (>=90)
        self.assertEqual(_track_record_safety(1.0, 89), 18)    # 15+3 (>=30, 89<90)
        self.assertEqual(_track_record_safety(1.0, 30), 18)    # 15+3 (>=30)
        self.assertEqual(_track_record_safety(1.0, 29), 15)    # 15+0 (<30)


# ---------------------------------------------------------------------------
# _code_change_penalty
# ---------------------------------------------------------------------------

class TestCodeChangePenalty(unittest.TestCase):

    def test_critical(self):
        self.assertEqual(_code_change_penalty("CRITICAL"), 15)

    def test_major(self):
        self.assertEqual(_code_change_penalty("MAJOR"), 10)

    def test_moderate(self):
        self.assertEqual(_code_change_penalty("MODERATE"), 5)

    def test_minor(self):
        self.assertEqual(_code_change_penalty("MINOR"), 0)

    def test_unknown_returns_0(self):
        self.assertEqual(_code_change_penalty("UNKNOWN"), 0)


# ---------------------------------------------------------------------------
# _risk_level
# ---------------------------------------------------------------------------

class TestRiskLevel(unittest.TestCase):

    def test_critical_threshold(self):
        self.assertEqual(_risk_level(75), "CRITICAL")
        self.assertEqual(_risk_level(100), "CRITICAL")

    def test_high_threshold(self):
        self.assertEqual(_risk_level(50), "HIGH")
        self.assertEqual(_risk_level(74), "HIGH")

    def test_moderate_threshold(self):
        self.assertEqual(_risk_level(25), "MODERATE")
        self.assertEqual(_risk_level(49), "MODERATE")

    def test_low_threshold(self):
        self.assertEqual(_risk_level(0), "LOW")
        self.assertEqual(_risk_level(24), "LOW")


# ---------------------------------------------------------------------------
# _key_risk_factors
# ---------------------------------------------------------------------------

class TestKeyRiskFactors(unittest.TestCase):

    def _call(self, **kw):
        defaults = dict(
            timelock_hours=24, governance_approval_pct=60,
            audit_coverage_pct=80, auditor_count=2,
            code_change_size="MINOR", days_since_last_incident=90,
            previous_upgrade_success_rate=0.9,
        )
        defaults.update(kw)
        return _key_risk_factors(**defaults)

    def test_no_factors_returns_sentinel(self):
        factors = self._call()
        self.assertEqual(factors, ["No significant risk factors identified"])

    def test_short_timelock_flagged(self):
        factors = self._call(timelock_hours=23)
        self.assertIn("Short or no timelock", factors)

    def test_zero_timelock_flagged(self):
        factors = self._call(timelock_hours=0)
        self.assertIn("Short or no timelock", factors)

    def test_exactly_24_not_flagged(self):
        factors = self._call(timelock_hours=24)
        self.assertNotIn("Short or no timelock", factors)

    def test_low_governance_flagged(self):
        factors = self._call(governance_approval_pct=59)
        self.assertIn("Low governance approval", factors)

    def test_exactly_60_not_flagged(self):
        factors = self._call(governance_approval_pct=60)
        self.assertNotIn("Low governance approval", factors)

    def test_partial_audit_flagged(self):
        factors = self._call(audit_coverage_pct=79)
        self.assertIn("Partial audit coverage (79%)", factors)

    def test_exactly_80_audit_not_flagged(self):
        factors = self._call(audit_coverage_pct=80)
        self.assertNotIn("Partial audit coverage (80%)", factors)

    def test_single_auditor_flagged(self):
        factors = self._call(auditor_count=1)
        self.assertIn("Single auditor", factors)

    def test_zero_auditors_flagged(self):
        factors = self._call(auditor_count=0)
        self.assertIn("Single auditor", factors)

    def test_two_auditors_not_flagged(self):
        factors = self._call(auditor_count=2)
        self.assertNotIn("Single auditor", factors)

    def test_major_change_flagged(self):
        factors = self._call(code_change_size="MAJOR")
        self.assertIn("Large scope change (MAJOR)", factors)

    def test_critical_change_flagged(self):
        factors = self._call(code_change_size="CRITICAL")
        self.assertIn("Large scope change (CRITICAL)", factors)

    def test_minor_change_not_flagged(self):
        factors = self._call(code_change_size="MINOR")
        large = [f for f in factors if "Large scope" in f]
        self.assertEqual(large, [])

    def test_moderate_change_not_flagged(self):
        factors = self._call(code_change_size="MODERATE")
        large = [f for f in factors if "Large scope" in f]
        self.assertEqual(large, [])

    def test_recent_incident_flagged(self):
        factors = self._call(days_since_last_incident=89)
        self.assertIn("Recent incident history", factors)

    def test_zero_days_incident_flagged(self):
        factors = self._call(days_since_last_incident=0)
        self.assertIn("Recent incident history", factors)

    def test_90_days_incident_not_flagged(self):
        factors = self._call(days_since_last_incident=90)
        self.assertNotIn("Recent incident history", factors)

    def test_below_avg_track_record_flagged(self):
        factors = self._call(previous_upgrade_success_rate=0.89)
        self.assertIn("Below-average upgrade track record", factors)

    def test_exactly_09_not_flagged(self):
        factors = self._call(previous_upgrade_success_rate=0.9)
        self.assertNotIn("Below-average upgrade track record", factors)

    def test_multiple_factors_returned(self):
        factors = self._call(
            timelock_hours=0, governance_approval_pct=10,
            audit_coverage_pct=50, auditor_count=1,
            code_change_size="CRITICAL", days_since_last_incident=5,
            previous_upgrade_success_rate=0.5,
        )
        self.assertGreater(len(factors), 1)


# ---------------------------------------------------------------------------
# analyze() -- empty input
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):

    def test_empty_returns_nones_and_zeros(self):
        result = analyze([])
        self.assertIsNone(result["highest_risk_upgrade"])
        self.assertIsNone(result["lowest_risk_upgrade"])
        self.assertEqual(result["pending_high_risk_count"], 0)
        self.assertEqual(result["average_risk_score"], 0.0)
        self.assertEqual(result["upgrades"], [])
        self.assertIn("timestamp", result)

    def test_empty_with_config(self):
        result = analyze([], config={})
        self.assertIsNone(result["highest_risk_upgrade"])


# ---------------------------------------------------------------------------
# analyze() -- single upgrade
# ---------------------------------------------------------------------------

class TestAnalyzeSingle(unittest.TestCase):

    def test_safe_upgrade_low_risk(self):
        u = _upgrade(
            timelock_hours=168, governance_approval_pct=90,
            audit_coverage_pct=100, auditor_count=3,
            days_since_last_incident=400, code_change_size="MINOR",
            previous_upgrade_success_rate=1.0,
        )
        res = analyze([u])
        entry = res["upgrades"][0]
        self.assertEqual(entry["risk_score"], 0)
        self.assertEqual(entry["risk_level"], "LOW")

    def test_worst_case_upgrade_critical(self):
        u = _upgrade(
            timelock_hours=0, governance_approval_pct=0,
            audit_coverage_pct=0, auditor_count=0,
            days_since_last_incident=0, code_change_size="CRITICAL",
            previous_upgrade_success_rate=0.0,
        )
        res = analyze([u])
        entry = res["upgrades"][0]
        self.assertEqual(entry["risk_score"], 100)
        self.assertEqual(entry["risk_level"], "CRITICAL")

    def test_highest_and_lowest_same_when_single(self):
        res = analyze([_upgrade(protocol="OnlyOne")])
        self.assertEqual(res["highest_risk_upgrade"], "OnlyOne")
        self.assertEqual(res["lowest_risk_upgrade"], "OnlyOne")

    def test_average_risk_single(self):
        u = _upgrade(
            timelock_hours=0, governance_approval_pct=0,
            audit_coverage_pct=0, auditor_count=0,
            days_since_last_incident=0, code_change_size="MINOR",
            previous_upgrade_success_rate=0.0,
        )
        res = analyze([u])
        self.assertEqual(res["average_risk_score"], float(res["upgrades"][0]["risk_score"]))

    def test_scores_present_in_output(self):
        res = analyze([_upgrade()])
        entry = res["upgrades"][0]
        for key in ("timelock_score", "governance_score", "audit_score", "track_record_score"):
            self.assertIn(key, entry)

    def test_recommendation_low(self):
        u = _upgrade(
            timelock_hours=168, governance_approval_pct=90,
            audit_coverage_pct=100, auditor_count=3,
            days_since_last_incident=400, code_change_size="MINOR",
            previous_upgrade_success_rate=1.0,
        )
        res = analyze([u])
        rec = res["upgrades"][0]["recommendation"]
        self.assertIn("well-governed", rec)

    def test_recommendation_critical(self):
        u = _upgrade(
            timelock_hours=0, governance_approval_pct=0,
            audit_coverage_pct=0, auditor_count=0,
            days_since_last_incident=0, code_change_size="CRITICAL",
            previous_upgrade_success_rate=0.0,
        )
        res = analyze([u])
        rec = res["upgrades"][0]["recommendation"]
        self.assertIn("Avoid interaction", rec)

    def test_upgrade_status_preserved(self):
        res = analyze([_upgrade(upgrade_status="EXECUTED")])
        self.assertEqual(res["upgrades"][0]["upgrade_status"], "EXECUTED")

    def test_protocol_name_preserved(self):
        res = analyze([_upgrade(protocol="Morpho")])
        self.assertEqual(res["upgrades"][0]["protocol"], "Morpho")

    def test_key_risk_factors_is_list(self):
        res = analyze([_upgrade()])
        self.assertIsInstance(res["upgrades"][0]["key_risk_factors"], list)


# ---------------------------------------------------------------------------
# analyze() -- multiple upgrades
# ---------------------------------------------------------------------------

class TestAnalyzeMultiple(unittest.TestCase):

    def _safe(self, name="Safe"):
        return _upgrade(
            protocol=name,
            timelock_hours=168, governance_approval_pct=90,
            audit_coverage_pct=100, auditor_count=3,
            days_since_last_incident=400, code_change_size="MINOR",
            previous_upgrade_success_rate=1.0,
        )

    def _risky(self, name="Risky"):
        return _upgrade(
            protocol=name,
            timelock_hours=0, governance_approval_pct=0,
            audit_coverage_pct=0, auditor_count=0,
            days_since_last_incident=0, code_change_size="CRITICAL",
            previous_upgrade_success_rate=0.0,
        )

    def test_highest_and_lowest_identified(self):
        res = analyze([self._safe("A"), self._risky("B")])
        self.assertEqual(res["highest_risk_upgrade"], "B")
        self.assertEqual(res["lowest_risk_upgrade"], "A")

    def test_average_risk_correct(self):
        res = analyze([self._safe("A"), self._risky("B")])
        scores = [e["risk_score"] for e in res["upgrades"]]
        expected = sum(scores) / len(scores)
        self.assertAlmostEqual(res["average_risk_score"], expected)

    def test_pending_high_risk_count(self):
        u1 = _upgrade(
            protocol="P1", upgrade_status="PENDING",
            timelock_hours=0, governance_approval_pct=0,
            audit_coverage_pct=0, auditor_count=0,
            days_since_last_incident=0, code_change_size="CRITICAL",
            previous_upgrade_success_rate=0.0,
        )
        u2 = _upgrade(
            protocol="P2", upgrade_status="TIMELOCKED",
            timelock_hours=0, governance_approval_pct=0,
            audit_coverage_pct=0, auditor_count=0,
            days_since_last_incident=0, code_change_size="CRITICAL",
            previous_upgrade_success_rate=0.0,
        )
        u3 = _upgrade(
            protocol="P3", upgrade_status="EXECUTED",
            timelock_hours=0, governance_approval_pct=0,
            audit_coverage_pct=0, auditor_count=0,
            days_since_last_incident=0, code_change_size="CRITICAL",
            previous_upgrade_success_rate=0.0,
        )
        res = analyze([u1, u2, u3, self._safe("P4")])
        # P1 PENDING+CRITICAL, P2 TIMELOCKED+CRITICAL counted; P3 EXECUTED excluded; P4 LOW excluded
        self.assertEqual(res["pending_high_risk_count"], 2)

    def test_cancelled_not_counted_in_pending_high_risk(self):
        u = _upgrade(
            protocol="C1", upgrade_status="CANCELLED",
            timelock_hours=0, governance_approval_pct=0,
            audit_coverage_pct=0, auditor_count=0,
            days_since_last_incident=0, code_change_size="CRITICAL",
            previous_upgrade_success_rate=0.0,
        )
        res = analyze([u])
        self.assertEqual(res["pending_high_risk_count"], 0)

    def test_three_upgrades_count(self):
        res = analyze([self._safe(), self._safe("B"), self._risky()])
        self.assertEqual(len(res["upgrades"]), 3)

    def test_timestamp_is_float(self):
        res = analyze([self._safe()])
        self.assertIsInstance(res["timestamp"], float)
        self.assertGreater(res["timestamp"], 0)


# ---------------------------------------------------------------------------
# Score math verification
# ---------------------------------------------------------------------------

class TestScoreMath(unittest.TestCase):

    def test_safety_100_risk_score_0_minor(self):
        u = _upgrade(
            timelock_hours=168, governance_approval_pct=90,
            audit_coverage_pct=100, auditor_count=3,
            days_since_last_incident=400, code_change_size="MINOR",
            previous_upgrade_success_rate=1.0,
        )
        res = analyze([u])
        entry = res["upgrades"][0]
        self.assertEqual(entry["timelock_score"], 25)
        self.assertEqual(entry["governance_score"], 25)
        self.assertEqual(entry["audit_score"], 25)
        self.assertEqual(entry["track_record_score"], 25)
        self.assertEqual(entry["risk_score"], 0)

    def test_safety_0_risk_100_with_critical_penalty(self):
        u = _upgrade(
            timelock_hours=0, governance_approval_pct=0,
            audit_coverage_pct=0, auditor_count=0,
            days_since_last_incident=0, code_change_size="CRITICAL",
            previous_upgrade_success_rate=0.0,
        )
        res = analyze([u])
        entry = res["upgrades"][0]
        self.assertEqual(entry["timelock_score"], 0)
        self.assertEqual(entry["governance_score"], 0)
        self.assertEqual(entry["audit_score"], 0)
        self.assertEqual(entry["track_record_score"], 0)
        # raw_risk = 100 + 15 = 115, capped at 100
        self.assertEqual(entry["risk_score"], 100)

    def test_moderate_penalty_applied(self):
        # safety=100; raw=0; moderate penalty=+5 -> risk_score=5
        u = _upgrade(
            timelock_hours=168, governance_approval_pct=90,
            audit_coverage_pct=100, auditor_count=3,
            days_since_last_incident=400, code_change_size="MODERATE",
            previous_upgrade_success_rate=1.0,
        )
        res = analyze([u])
        self.assertEqual(res["upgrades"][0]["risk_score"], 5)

    def test_major_penalty_applied(self):
        u = _upgrade(
            timelock_hours=168, governance_approval_pct=90,
            audit_coverage_pct=100, auditor_count=3,
            days_since_last_incident=400, code_change_size="MAJOR",
            previous_upgrade_success_rate=1.0,
        )
        res = analyze([u])
        self.assertEqual(res["upgrades"][0]["risk_score"], 10)

    def test_risk_score_never_negative(self):
        u = _upgrade(code_change_size="MINOR", previous_upgrade_success_rate=1.0,
                     timelock_hours=336, governance_approval_pct=100)
        res = analyze([u])
        self.assertGreaterEqual(res["upgrades"][0]["risk_score"], 0)

    def test_risk_score_never_exceeds_100(self):
        u = _upgrade(
            timelock_hours=0, governance_approval_pct=0,
            audit_coverage_pct=0, auditor_count=0,
            days_since_last_incident=0, code_change_size="CRITICAL",
            previous_upgrade_success_rate=0.0,
        )
        res = analyze([u])
        self.assertLessEqual(res["upgrades"][0]["risk_score"], 100)


# ---------------------------------------------------------------------------
# _append_log
# ---------------------------------------------------------------------------

class TestAppendLog(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "protocol_upgrade_risk_log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_creates_file_if_missing(self):
        result = analyze([_upgrade()])
        _append_log(result, self.log_file)
        self.assertTrue(os.path.exists(self.log_file))

    def test_appends_entry(self):
        result = analyze([_upgrade()])
        _append_log(result, self.log_file)
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 1)

    def test_appends_multiple(self):
        for _ in range(5):
            _append_log(analyze([_upgrade()]), self.log_file)
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 5)

    def test_ring_buffer_cap_100(self):
        for _ in range(110):
            _append_log(analyze([_upgrade()]), self.log_file)
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(5):
            res = analyze([_upgrade(protocol=f"P{i}")])
            res["_seq"] = i
            _append_log(res, self.log_file)
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(log[-1]["_seq"], 4)

    def test_corrupt_file_recovered(self):
        with open(self.log_file, "w") as f:
            f.write("NOT JSON{{{{")
        _append_log(analyze([_upgrade()]), self.log_file)
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 1)

    def test_non_list_file_recovered(self):
        with open(self.log_file, "w") as f:
            json.dump({"bad": "data"}, f)
        _append_log(analyze([_upgrade()]), self.log_file)
        with open(self.log_file) as f:
            log = json.load(f)
        self.assertEqual(len(log), 1)

    def test_atomic_write_valid_json(self):
        result = analyze([_upgrade()])
        _append_log(result, self.log_file)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


# ---------------------------------------------------------------------------
# analyze() -- key_risk_factors inside result
# ---------------------------------------------------------------------------

class TestAnalyzeKeyRiskFactors(unittest.TestCase):

    def test_perfect_upgrade_no_risk_factors(self):
        u = _upgrade(
            timelock_hours=168, governance_approval_pct=90,
            audit_coverage_pct=100, auditor_count=3,
            days_since_last_incident=400, code_change_size="MINOR",
            previous_upgrade_success_rate=1.0,
        )
        res = analyze([u])
        factors = res["upgrades"][0]["key_risk_factors"]
        self.assertEqual(factors, ["No significant risk factors identified"])

    def test_bad_upgrade_many_risk_factors(self):
        u = _upgrade(
            timelock_hours=0, governance_approval_pct=10,
            audit_coverage_pct=10, auditor_count=1,
            days_since_last_incident=5, code_change_size="CRITICAL",
            previous_upgrade_success_rate=0.5,
        )
        res = analyze([u])
        factors = res["upgrades"][0]["key_risk_factors"]
        self.assertGreater(len(factors), 3)

    def test_partial_audit_string_format(self):
        u = _upgrade(audit_coverage_pct=55.0, auditor_count=1)
        res = analyze([u])
        factors = res["upgrades"][0]["key_risk_factors"]
        audit_factors = [f for f in factors if "audit" in f.lower()]
        self.assertTrue(len(audit_factors) >= 1)


# ---------------------------------------------------------------------------
# Boundary / edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_timelock_exactly_168(self):
        u = _upgrade(timelock_hours=168)
        res = analyze([u])
        self.assertEqual(res["upgrades"][0]["timelock_score"], 25)

    def test_timelock_exactly_12(self):
        u = _upgrade(timelock_hours=12)
        res = analyze([u])
        self.assertEqual(res["upgrades"][0]["timelock_score"], 5)

    def test_governance_exactly_60(self):
        u = _upgrade(governance_approval_pct=60)
        res = analyze([u])
        self.assertEqual(res["upgrades"][0]["governance_score"], 20)

    def test_audit_exactly_95_two_auditors(self):
        u = _upgrade(audit_coverage_pct=95, auditor_count=2)
        res = analyze([u])
        self.assertEqual(res["upgrades"][0]["audit_score"], 25)

    def test_track_record_cap(self):
        u = _upgrade(previous_upgrade_success_rate=1.0, days_since_last_incident=1000)
        res = analyze([u])
        self.assertEqual(res["upgrades"][0]["track_record_score"], 25)

    def test_executed_status_not_in_pending_count(self):
        u = _upgrade(
            upgrade_status="EXECUTED",
            timelock_hours=0, governance_approval_pct=0,
            audit_coverage_pct=0, auditor_count=0,
            days_since_last_incident=0, code_change_size="CRITICAL",
            previous_upgrade_success_rate=0.0,
        )
        res = analyze([u])
        self.assertEqual(res["pending_high_risk_count"], 0)

    def test_config_none_accepted(self):
        res = analyze([_upgrade()], config=None)
        self.assertIn("upgrades", res)

    def test_config_dict_accepted(self):
        res = analyze([_upgrade()], config={"some_key": 1})
        self.assertIn("upgrades", res)

    def test_float_timelock_accepted(self):
        res = analyze([_upgrade(timelock_hours=47.5)])
        self.assertEqual(res["upgrades"][0]["timelock_score"], 10)

    def test_output_keys_complete(self):
        res = analyze([_upgrade()])
        for key in ("upgrades", "highest_risk_upgrade", "lowest_risk_upgrade",
                    "pending_high_risk_count", "average_risk_score", "timestamp"):
            self.assertIn(key, res)


if __name__ == "__main__":
    unittest.main()
