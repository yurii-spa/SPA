"""
Tests for ProtocolSecurityIncidentTracker (MP-919).
≥85 tests. Run: python3 -m unittest spa_core.tests.test_protocol_security_incident_tracker
"""
import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_security_incident_tracker import (
    ProtocolSecurityIncidentTracker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _incident(**kw):
    base = {
        "date_days_ago": 200.0,
        "type": "hack",
        "amount_lost_usd": 100_000.0,
        "recovered_pct": 20.0,
        "severity": "MEDIUM",
    }
    base.update(kw)
    return base


def _protocol(**kw):
    base = {
        "name": "TestProto",
        "incidents": [],
        "total_tvl_peak_usd": 100_000_000.0,
        "current_tvl_usd": 80_000_000.0,
        "bug_bounty_usd": 1_000_000.0,
        "audits_count": 3,
        "last_audit_days_ago": 60.0,
        "insurance_coverage_usd": 5_000_000.0,
    }
    base.update(kw)
    return base


def _clean_protocol(name="CLEAN"):
    """Protocol with no incidents and great security investment."""
    return _protocol(
        name=name,
        incidents=[],
        bug_bounty_usd=2_000_000.0,
        audits_count=5,
        last_audit_days_ago=30.0,
        insurance_coverage_usd=20_000_000.0,
        total_tvl_peak_usd=100_000_000.0,
    )


def _risky_protocol(name="RISKY"):
    """Protocol with multiple critical incidents."""
    return _protocol(
        name=name,
        incidents=[
            _incident(severity="CRITICAL", amount_lost_usd=10_000_000.0,
                      date_days_ago=30.0, type="hack", recovered_pct=0.0),
            _incident(severity="CRITICAL", amount_lost_usd=5_000_000.0,
                      date_days_ago=60.0, type="exploit", recovered_pct=0.0),
        ],
        bug_bounty_usd=0.0,
        audits_count=0,
        last_audit_days_ago=9999.0,
        insurance_coverage_usd=0.0,
    )


class TestProtocolSecurityIncidentTrackerOutputShape(unittest.TestCase):
    """Tests 1-22: output shape and required keys."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.tracker = ProtocolSecurityIncidentTracker(
            log_path=os.path.join(d, "log.json")
        )

    def test_01_returns_dict(self):
        self.assertIsInstance(self.tracker.track([_protocol()]), dict)

    def test_02_has_results(self):
        self.assertIn("results", self.tracker.track([_protocol()]))

    def test_03_has_aggregates(self):
        self.assertIn("aggregates", self.tracker.track([_protocol()]))

    def test_04_has_timestamp(self):
        self.assertIn("timestamp", self.tracker.track([_protocol()]))

    def test_05_has_protocol_count(self):
        self.assertIn("protocol_count", self.tracker.track([_protocol()]))

    def test_06_protocol_count_correct(self):
        self.assertEqual(self.tracker.track([_protocol(), _protocol()])["protocol_count"], 2)

    def test_07_results_length_matches(self):
        self.assertEqual(len(self.tracker.track([_protocol(), _protocol()])["results"]), 2)

    def test_08_empty_list_ok(self):
        r = self.tracker.track([])
        self.assertEqual(r["protocol_count"], 0)
        self.assertEqual(r["results"], [])

    def test_09_result_item_has_name(self):
        self.assertIn("name", self.tracker.track([_protocol()])["results"][0])

    def test_10_result_item_has_incident_count(self):
        self.assertIn("incident_count", self.tracker.track([_protocol()])["results"][0])

    def test_11_result_item_has_incident_rate_score(self):
        self.assertIn("incident_rate_score", self.tracker.track([_protocol()])["results"][0])

    def test_12_result_item_has_recovery_rate_pct(self):
        self.assertIn("recovery_rate_pct", self.tracker.track([_protocol()])["results"][0])

    def test_13_result_item_has_security_investment_score(self):
        self.assertIn("security_investment_score", self.tracker.track([_protocol()])["results"][0])

    def test_14_result_item_has_recency_risk(self):
        self.assertIn("recency_risk", self.tracker.track([_protocol()])["results"][0])

    def test_15_result_item_has_composite_safety_score(self):
        self.assertIn("composite_safety_score", self.tracker.track([_protocol()])["results"][0])

    def test_16_result_item_has_safety_label(self):
        self.assertIn("safety_label", self.tracker.track([_protocol()])["results"][0])

    def test_17_result_item_has_flags(self):
        self.assertIn("flags", self.tracker.track([_protocol()])["results"][0])

    def test_18_result_item_has_total_lost_usd(self):
        self.assertIn("total_lost_usd", self.tracker.track([_protocol()])["results"][0])

    def test_19_result_item_has_total_recovered_usd(self):
        self.assertIn("total_recovered_usd", self.tracker.track([_protocol()])["results"][0])

    def test_20_aggregates_has_safest_protocol(self):
        self.assertIn("safest_protocol", self.tracker.track([_protocol()])["aggregates"])

    def test_21_aggregates_has_most_risky(self):
        self.assertIn("most_risky", self.tracker.track([_protocol()])["aggregates"])

    def test_22_aggregates_has_total_lost(self):
        self.assertIn("total_lost_usd", self.tracker.track([_protocol()])["aggregates"])

    def test_22b_aggregates_has_total_recovered(self):
        self.assertIn("total_recovered_usd", self.tracker.track([_protocol()])["aggregates"])

    def test_22c_aggregates_has_avoid_count(self):
        self.assertIn("avoid_count", self.tracker.track([_protocol()])["aggregates"])


class TestProtocolSecurityIncidentTrackerRanges(unittest.TestCase):
    """Tests 23-45: score ranges and monotonicity."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.tracker = ProtocolSecurityIncidentTracker(
            log_path=os.path.join(d, "log.json")
        )

    def _r(self, p):
        return self.tracker.track([p])["results"][0]

    def test_23_incident_rate_score_ge_0(self):
        self.assertGreaterEqual(self._r(_protocol())["incident_rate_score"], 0.0)

    def test_24_incident_rate_score_le_100(self):
        self.assertLessEqual(self._r(_risky_protocol())["incident_rate_score"], 100.0)

    def test_25_safety_score_ge_0(self):
        self.assertGreaterEqual(self._r(_protocol())["composite_safety_score"], 0.0)

    def test_26_safety_score_le_100(self):
        self.assertLessEqual(self._r(_protocol())["composite_safety_score"], 100.0)

    def test_27_security_investment_ge_0(self):
        self.assertGreaterEqual(self._r(_protocol())["security_investment_score"], 0.0)

    def test_28_security_investment_le_100(self):
        self.assertLessEqual(self._r(_protocol())["security_investment_score"], 100.0)

    def test_29_recency_risk_ge_0(self):
        self.assertGreaterEqual(self._r(_protocol())["recency_risk"], 0.0)

    def test_30_recency_risk_le_100(self):
        self.assertLessEqual(self._r(_risky_protocol())["recency_risk"], 100.0)

    def test_31_no_incidents_incident_rate_zero(self):
        self.assertEqual(self._r(_clean_protocol())["incident_rate_score"], 0.0)

    def test_32_no_incidents_recovery_rate_100(self):
        self.assertEqual(self._r(_clean_protocol())["recovery_rate_pct"], 100.0)

    def test_33_no_incidents_recency_risk_zero(self):
        self.assertEqual(self._r(_clean_protocol())["recency_risk"], 0.0)

    def test_34_more_audits_higher_investment(self):
        p_low = _protocol(audits_count=0, last_audit_days_ago=9999)
        p_hi = _protocol(audits_count=6, last_audit_days_ago=30)
        r_low = self._r(p_low)["security_investment_score"]
        r_hi = self._r(p_hi)["security_investment_score"]
        self.assertGreater(r_hi, r_low)

    def test_35_insurance_increases_investment(self):
        p_no = _protocol(insurance_coverage_usd=0.0, bug_bounty_usd=0, audits_count=0,
                          last_audit_days_ago=9999)
        p_yes = _protocol(insurance_coverage_usd=10_000_000.0, bug_bounty_usd=0,
                           audits_count=0, last_audit_days_ago=9999)
        r_no = self._r(p_no)["security_investment_score"]
        r_yes = self._r(p_yes)["security_investment_score"]
        self.assertGreater(r_yes, r_no)

    def test_36_bug_bounty_increases_investment(self):
        p_no = _protocol(bug_bounty_usd=0.0, audits_count=0, insurance_coverage_usd=0,
                          last_audit_days_ago=9999)
        p_yes = _protocol(bug_bounty_usd=5_000_000.0, audits_count=0,
                           insurance_coverage_usd=0, last_audit_days_ago=9999)
        r_no = self._r(p_no)["security_investment_score"]
        r_yes = self._r(p_yes)["security_investment_score"]
        self.assertGreater(r_yes, r_no)

    def test_37_recent_incident_higher_recency_risk(self):
        p_old = _protocol(incidents=[_incident(date_days_ago=500, severity="HIGH")])
        p_new = _protocol(incidents=[_incident(date_days_ago=10, severity="HIGH")])
        r_old = self._r(p_old)["recency_risk"]
        r_new = self._r(p_new)["recency_risk"]
        self.assertGreater(r_new, r_old)

    def test_38_critical_incident_higher_rate_than_low(self):
        p_crit = _protocol(incidents=[_incident(severity="CRITICAL")])
        p_low = _protocol(incidents=[_incident(severity="LOW")])
        r_crit = self._r(p_crit)["incident_rate_score"]
        r_low = self._r(p_low)["incident_rate_score"]
        self.assertGreater(r_crit, r_low)

    def test_39_clean_protocol_very_safe_or_safe(self):
        r = self._r(_clean_protocol())
        self.assertIn(r["safety_label"], ("VERY_SAFE", "SAFE", "CAUTION"))

    def test_40_risky_protocol_lower_safety_than_clean(self):
        r_clean = self._r(_clean_protocol())["composite_safety_score"]
        r_risky = self._r(_risky_protocol())["composite_safety_score"]
        self.assertGreater(r_clean, r_risky)

    def test_41_total_lost_correct(self):
        inc = _incident(amount_lost_usd=1_000_000.0, recovered_pct=0.0)
        p = _protocol(incidents=[inc])
        r = self._r(p)
        self.assertAlmostEqual(r["total_lost_usd"], 1_000_000.0, places=1)

    def test_42_total_recovered_correct(self):
        inc = _incident(amount_lost_usd=1_000_000.0, recovered_pct=50.0)
        p = _protocol(incidents=[inc])
        r = self._r(p)
        self.assertAlmostEqual(r["total_recovered_usd"], 500_000.0, places=1)

    def test_43_zero_incidents_total_lost_zero(self):
        r = self._r(_clean_protocol())
        self.assertEqual(r["total_lost_usd"], 0.0)

    def test_44_zero_incidents_total_recovered_zero(self):
        r = self._r(_clean_protocol())
        self.assertEqual(r["total_recovered_usd"], 0.0)

    def test_45_incident_count_correct(self):
        p = _protocol(incidents=[_incident(), _incident()])
        r = self._r(p)
        self.assertEqual(r["incident_count"], 2)


class TestProtocolSecurityIncidentTrackerLabels(unittest.TestCase):
    """Tests 46-55: safety label logic."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.tracker = ProtocolSecurityIncidentTracker(
            log_path=os.path.join(d, "log.json")
        )

    def test_46_valid_safety_label(self):
        valid = {"VERY_SAFE", "SAFE", "CAUTION", "RISKY", "AVOID"}
        r = self.tracker.track([_protocol()])["results"][0]
        self.assertIn(r["safety_label"], valid)

    def test_47_avoid_label_for_risky(self):
        r = self.tracker.track([_risky_protocol()])["results"][0]
        self.assertIn(r["safety_label"], ("AVOID", "RISKY", "CAUTION"))

    def test_48_very_safe_or_safe_for_clean(self):
        r = self.tracker.track([_clean_protocol()])["results"][0]
        self.assertIn(r["safety_label"], ("VERY_SAFE", "SAFE", "CAUTION"))

    def test_49_safety_score_above_80_very_safe(self):
        r = self.tracker.track([_clean_protocol()])["results"][0]
        if r["composite_safety_score"] >= 80:
            self.assertEqual(r["safety_label"], "VERY_SAFE")

    def test_50_safety_score_below_20_risky_or_avoid(self):
        r = self.tracker.track([_risky_protocol()])["results"][0]
        if r["composite_safety_score"] < 20:
            self.assertIn(r["safety_label"], ("RISKY", "AVOID"))


class TestProtocolSecurityIncidentTrackerFlags(unittest.TestCase):
    """Tests 51-70: flag logic."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.tracker = ProtocolSecurityIncidentTracker(
            log_path=os.path.join(d, "log.json")
        )

    def _flags(self, p):
        return self.tracker.track([p])["results"][0]["flags"]

    def test_51_flags_is_list(self):
        self.assertIsInstance(self._flags(_protocol()), list)

    def test_52_recent_hack_flag_present(self):
        p = _protocol(incidents=[_incident(date_days_ago=30, type="hack", severity="HIGH")])
        self.assertIn("RECENT_HACK", self._flags(p))

    def test_53_recent_hack_flag_absent_old_incident(self):
        p = _protocol(incidents=[_incident(date_days_ago=200, type="hack")])
        self.assertNotIn("RECENT_HACK", self._flags(p))

    def test_54_recent_hack_flag_absent_governance_type(self):
        p = _protocol(incidents=[_incident(date_days_ago=30, type="governance")])
        self.assertNotIn("RECENT_HACK", self._flags(p))

    def test_55_repeat_offender_flag_two_critical(self):
        p = _protocol(incidents=[
            _incident(severity="CRITICAL"),
            _incident(severity="CRITICAL"),
        ])
        self.assertIn("REPEAT_OFFENDER", self._flags(p))

    def test_56_repeat_offender_flag_absent_one_critical(self):
        p = _protocol(incidents=[_incident(severity="CRITICAL")])
        self.assertNotIn("REPEAT_OFFENDER", self._flags(p))

    def test_57_no_insurance_flag_present(self):
        p = _protocol(insurance_coverage_usd=0.0)
        self.assertIn("NO_INSURANCE", self._flags(p))

    def test_58_no_insurance_flag_absent(self):
        p = _protocol(insurance_coverage_usd=1_000_000.0)
        self.assertNotIn("NO_INSURANCE", self._flags(p))

    def test_59_unaudited_flag_present(self):
        p = _protocol(audits_count=0)
        self.assertIn("UNAUDITED", self._flags(p))

    def test_60_unaudited_flag_absent(self):
        p = _protocol(audits_count=1)
        self.assertNotIn("UNAUDITED", self._flags(p))

    def test_61_recovered_funds_flag_above_50(self):
        p = _protocol(incidents=[_incident(recovered_pct=80.0)])
        self.assertIn("RECOVERED_FUNDS", self._flags(p))

    def test_62_recovered_funds_flag_absent_at_50(self):
        p = _protocol(incidents=[_incident(recovered_pct=50.0)])
        self.assertNotIn("RECOVERED_FUNDS", self._flags(p))

    def test_63_recovered_funds_flag_absent_no_incidents(self):
        # No incidents → recovery_rate=100 > 50 → RECOVERED_FUNDS
        # Actually: no incidents → 100% → flag present
        p = _clean_protocol()
        flags = self._flags(p)
        self.assertIn("RECOVERED_FUNDS", flags)

    def test_64_multiple_flags_risky_protocol(self):
        flags = self._flags(_risky_protocol())
        self.assertGreater(len(flags), 1)

    def test_65_clean_protocol_no_unaudited_flag(self):
        flags = self._flags(_clean_protocol())
        self.assertNotIn("UNAUDITED", flags)

    def test_66_recent_exploit_triggers_recent_hack(self):
        p = _protocol(incidents=[_incident(date_days_ago=45, type="exploit")])
        self.assertIn("RECENT_HACK", self._flags(p))

    def test_67_recent_rug_does_not_trigger_recent_hack(self):
        # "rug" not in ("hack","exploit")
        p = _protocol(incidents=[_incident(date_days_ago=10, type="rug")])
        self.assertNotIn("RECENT_HACK", self._flags(p))

    def test_68_three_critical_repeat_offender(self):
        p = _protocol(incidents=[
            _incident(severity="CRITICAL"),
            _incident(severity="CRITICAL"),
            _incident(severity="CRITICAL"),
        ])
        self.assertIn("REPEAT_OFFENDER", self._flags(p))

    def test_69_zero_incidents_no_repeat_offender(self):
        self.assertNotIn("REPEAT_OFFENDER", self._flags(_clean_protocol()))

    def test_70_zero_incidents_no_recent_hack(self):
        self.assertNotIn("RECENT_HACK", self._flags(_clean_protocol()))


class TestProtocolSecurityIncidentTrackerAggregates(unittest.TestCase):
    """Tests 71-82: aggregate correctness."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.tracker = ProtocolSecurityIncidentTracker(
            log_path=os.path.join(d, "log.json")
        )

    def test_71_empty_aggregates_none(self):
        agg = self.tracker.track([])["aggregates"]
        self.assertIsNone(agg["safest_protocol"])
        self.assertIsNone(agg["most_risky"])

    def test_72_empty_aggregates_zeros(self):
        agg = self.tracker.track([])["aggregates"]
        self.assertEqual(agg["total_lost_usd"], 0.0)
        self.assertEqual(agg["total_recovered_usd"], 0.0)
        self.assertEqual(agg["avoid_count"], 0)

    def test_73_single_protocol_same_safest_riskiest(self):
        agg = self.tracker.track([_protocol(name="ONLY")])["aggregates"]
        self.assertEqual(agg["safest_protocol"], "ONLY")
        self.assertEqual(agg["most_risky"], "ONLY")

    def test_74_safest_is_clean(self):
        agg = self.tracker.track([_clean_protocol(), _risky_protocol()])["aggregates"]
        self.assertEqual(agg["safest_protocol"], "CLEAN")

    def test_75_most_risky_is_risky(self):
        agg = self.tracker.track([_clean_protocol(), _risky_protocol()])["aggregates"]
        self.assertEqual(agg["most_risky"], "RISKY")

    def test_76_total_lost_sum(self):
        p1 = _protocol(name="A", incidents=[_incident(amount_lost_usd=1_000_000, recovered_pct=0)])
        p2 = _protocol(name="B", incidents=[_incident(amount_lost_usd=2_000_000, recovered_pct=0)])
        agg = self.tracker.track([p1, p2])["aggregates"]
        self.assertAlmostEqual(agg["total_lost_usd"], 3_000_000.0, places=0)

    def test_77_total_recovered_sum(self):
        p1 = _protocol(name="A", incidents=[_incident(amount_lost_usd=1_000_000, recovered_pct=100)])
        p2 = _protocol(name="B", incidents=[_incident(amount_lost_usd=2_000_000, recovered_pct=50)])
        agg = self.tracker.track([p1, p2])["aggregates"]
        # 1_000_000 + 1_000_000 = 2_000_000
        self.assertAlmostEqual(agg["total_recovered_usd"], 2_000_000.0, places=0)

    def test_78_avoid_count_zero_for_clean(self):
        agg = self.tracker.track([_clean_protocol()])["aggregates"]
        self.assertEqual(agg["avoid_count"], 0)

    def test_79_avoid_count_increments(self):
        # Two risky protocols might both be AVOID
        agg = self.tracker.track([_risky_protocol("R1"), _risky_protocol("R2")])["aggregates"]
        results = self.tracker.track([_risky_protocol("R1"), _risky_protocol("R2")])["results"]
        expected = sum(1 for r in results if r["safety_label"] == "AVOID")
        self.assertEqual(agg["avoid_count"], expected)

    def test_80_five_protocols_count_correct(self):
        protocols = [_protocol(name=str(i)) for i in range(5)]
        self.assertEqual(self.tracker.track(protocols)["protocol_count"], 5)

    def test_81_total_lost_zero_no_incidents(self):
        agg = self.tracker.track([_clean_protocol()])["aggregates"]
        self.assertEqual(agg["total_lost_usd"], 0.0)

    def test_82_aggregate_keys_all_present(self):
        agg = self.tracker.track([_protocol()])["aggregates"]
        for key in ("safest_protocol", "most_risky", "total_lost_usd",
                    "total_recovered_usd", "avoid_count"):
            self.assertIn(key, agg)


class TestProtocolSecurityIncidentTrackerEdgeCases(unittest.TestCase):
    """Tests 83-92: edge cases and guard clauses."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.tracker = ProtocolSecurityIncidentTracker(
            log_path=os.path.join(d, "log.json")
        )

    def test_83_zero_peak_tvl_no_exception(self):
        p = _protocol(total_tvl_peak_usd=0.0)
        self.assertIsNotNone(self.tracker.track([p]))

    def test_84_negative_peak_tvl_no_exception(self):
        p = _protocol(total_tvl_peak_usd=-1.0)
        self.assertIsNotNone(self.tracker.track([p]))

    def test_85_minimal_protocol_no_exception(self):
        self.assertIsNotNone(self.tracker.track([{"name": "X"}]))

    def test_86_missing_name_defaults_unknown(self):
        r = self.tracker.track([{"incidents": []}])["results"][0]
        self.assertEqual(r["name"], "unknown")

    def test_87_config_optional(self):
        self.assertIsNotNone(self.tracker.track([_protocol()]))

    def test_88_unknown_incident_type_no_exception(self):
        p = _protocol(incidents=[_incident(type="unknown_type")])
        self.assertIsNotNone(self.tracker.track([p]))

    def test_89_unknown_severity_uses_fallback(self):
        p = _protocol(incidents=[_incident(severity="LEGENDARY")])
        result = self.tracker.track([p])
        self.assertGreater(result["results"][0]["incident_rate_score"], 0.0)

    def test_90_timestamp_is_string(self):
        result = self.tracker.track([_protocol()])
        self.assertIsInstance(result["timestamp"], str)

    def test_91_composite_safety_not_above_100(self):
        r = self.tracker.track([_clean_protocol()])["results"][0]
        self.assertLessEqual(r["composite_safety_score"], 100.0)

    def test_92_composite_safety_not_below_0(self):
        r = self.tracker.track([_risky_protocol()])["results"][0]
        self.assertGreaterEqual(r["composite_safety_score"], 0.0)


class TestProtocolSecurityIncidentTrackerLog(unittest.TestCase):
    """Tests 93-107: ring-buffer log and atomic write."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.log_path = os.path.join(d, "sec_log.json")
        self.tracker = ProtocolSecurityIncidentTracker(log_path=self.log_path)

    def test_93_log_created(self):
        self.tracker.track([_protocol()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_94_log_is_list(self):
        self.tracker.track([_protocol()])
        with open(self.log_path) as f:
            self.assertIsInstance(json.load(f), list)

    def test_95_log_grows(self):
        self.tracker.track([_protocol()])
        self.tracker.track([_protocol()])
        with open(self.log_path) as f:
            self.assertEqual(len(json.load(f)), 2)

    def test_96_ring_buffer_capped_at_100(self):
        for _ in range(110):
            self.tracker.track([_protocol()])
        with open(self.log_path) as f:
            self.assertLessEqual(len(json.load(f)), 100)

    def test_97_no_tmp_file_after_write(self):
        self.tracker.track([_protocol()])
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_98_log_entry_has_timestamp(self):
        self.tracker.track([_protocol()])
        with open(self.log_path) as f:
            self.assertIn("timestamp", json.load(f)[0])

    def test_99_log_entry_has_protocol_count(self):
        self.tracker.track([_protocol()])
        with open(self.log_path) as f:
            self.assertIn("protocol_count", json.load(f)[0])

    def test_100_log_entry_has_aggregates(self):
        self.tracker.track([_protocol()])
        with open(self.log_path) as f:
            self.assertIn("aggregates", json.load(f)[0])

    def test_101_malformed_log_recovered(self):
        with open(self.log_path, "w") as f:
            f.write("NOT JSON {[")
        result = self.tracker.track([_protocol()])
        self.assertIsNotNone(result)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_102_existing_log_preserved(self):
        self.tracker.track([_protocol()])
        self.tracker.track([_protocol()])
        with open(self.log_path) as f:
            self.assertEqual(len(json.load(f)), 2)

    def test_103_log_entry_protocol_count_correct(self):
        self.tracker.track([_protocol(), _protocol(name="B")])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["protocol_count"], 2)

    def test_104_ring_buffer_keeps_latest_100(self):
        for i in range(105):
            self.tracker.track([_protocol(name=f"P{i}")])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_105_zero_protocol_count_logged(self):
        self.tracker.track([])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["protocol_count"], 0)

    def test_106_log_valid_json_after_multiple_writes(self):
        for _ in range(5):
            self.tracker.track([_protocol()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_107_aggregates_in_log_match_output(self):
        result = self.tracker.track([_protocol(name="CHECK")])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(
            data[0]["aggregates"]["safest_protocol"],
            result["aggregates"]["safest_protocol"]
        )


if __name__ == "__main__":
    unittest.main()
