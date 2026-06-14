"""
MP-981: Tests for ProtocolHackRecoveryTracker
Run: python3 -m unittest spa_core.tests.test_protocol_hack_recovery_tracker -v
≥80 tests, stdlib unittest only.
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_hack_recovery_tracker import ProtocolHackRecoveryTracker


def _inc(**kwargs):
    """Build a minimal valid incident dict."""
    base = {
        "protocol": "TestProto",
        "hack_date_days_ago": 90.0,
        "amount_hacked_usd": 1_000_000.0,
        "amount_recovered_usd": 800_000.0,
        "recovery_mechanism": "insurance",
        "tvl_before_hack_usd": 50_000_000.0,
        "tvl_current_usd": 40_000_000.0,
        "users_compensated_pct": 80.0,
        "audit_count_post_hack": 2,
        "new_security_measures": ["bug_bounty", "multisig"],
        "days_since_resumption": 45.0,
        "prior_hacks": [],
    }
    base.update(kwargs)
    return base


class TestEmptyInput(unittest.TestCase):
    def setUp(self):
        self.tracker = ProtocolHackRecoveryTracker()
        self.cfg = {"log_path": "/tmp/test_hack_empty.json"}

    def test_empty_returns_dict(self):
        r = self.tracker.track([], self.cfg)
        self.assertIsInstance(r, dict)

    def test_empty_incidents_list(self):
        r = self.tracker.track([], self.cfg)
        self.assertEqual(r["incidents"], [])

    def test_empty_best_is_none(self):
        r = self.tracker.track([], self.cfg)
        self.assertIsNone(r["best_recovery"])

    def test_empty_worst_is_none(self):
        r = self.tracker.track([], self.cfg)
        self.assertIsNone(r["worst_recovery"])

    def test_empty_average_score_none(self):
        r = self.tracker.track([], self.cfg)
        self.assertIsNone(r["average_recovery_score"])

    def test_empty_fully_recovered_zero(self):
        r = self.tracker.track([], self.cfg)
        self.assertEqual(r["fully_recovered_count"], 0)

    def test_empty_abandoned_count_zero(self):
        r = self.tracker.track([], self.cfg)
        self.assertEqual(r["abandoned_count"], 0)

    def test_empty_config_preserved(self):
        r = self.tracker.track([], self.cfg)
        self.assertIn("config_used", r)


class TestSingleIncidentFields(unittest.TestCase):
    def setUp(self):
        self.tracker = ProtocolHackRecoveryTracker()
        self.cfg = {"log_path": "/tmp/test_hack_single.json"}

    def _run(self, **kw):
        return self.tracker.track([_inc(**kw)], self.cfg)["incidents"][0]

    def test_protocol_preserved(self):
        r = self._run(protocol="Euler")
        self.assertEqual(r["protocol"], "Euler")

    def test_amount_hacked_preserved(self):
        r = self._run(amount_hacked_usd=5_000_000.0)
        self.assertEqual(r["amount_hacked_usd"], 5_000_000.0)

    def test_amount_recovered_preserved(self):
        r = self._run(amount_recovered_usd=4_000_000.0)
        self.assertEqual(r["amount_recovered_usd"], 4_000_000.0)

    def test_recovery_rate_pct_present(self):
        r = self._run()
        self.assertIn("recovery_rate_pct", r)

    def test_tvl_recovery_pct_present(self):
        r = self._run()
        self.assertIn("tvl_recovery_pct", r)

    def test_compensation_score_present(self):
        r = self._run()
        self.assertIn("compensation_score", r)

    def test_security_improvement_score_present(self):
        r = self._run()
        self.assertIn("security_improvement_score", r)

    def test_overall_recovery_score_present(self):
        r = self._run()
        self.assertIn("overall_recovery_score", r)

    def test_label_present(self):
        r = self._run()
        self.assertIn("label", r)

    def test_flags_list(self):
        r = self._run()
        self.assertIsInstance(r["flags"], list)

    def test_days_since_resumption_preserved(self):
        r = self._run(days_since_resumption=10.0)
        self.assertEqual(r["days_since_resumption"], 10.0)

    def test_users_compensated_preserved(self):
        r = self._run(users_compensated_pct=75.0)
        self.assertEqual(r["users_compensated_pct"], 75.0)


class TestRecoveryRateCalculation(unittest.TestCase):
    def setUp(self):
        self.tracker = ProtocolHackRecoveryTracker()
        self.cfg = {"log_path": "/tmp/test_hack_rate.json"}

    def _run(self, **kw):
        return self.tracker.track([_inc(**kw)], self.cfg)["incidents"][0]

    def test_full_recovery_rate(self):
        r = self._run(amount_hacked_usd=1_000_000, amount_recovered_usd=1_000_000)
        self.assertAlmostEqual(r["recovery_rate_pct"], 100.0, places=2)

    def test_zero_recovery_rate(self):
        r = self._run(amount_hacked_usd=1_000_000, amount_recovered_usd=0)
        self.assertAlmostEqual(r["recovery_rate_pct"], 0.0, places=2)

    def test_partial_recovery_rate(self):
        r = self._run(amount_hacked_usd=1_000_000, amount_recovered_usd=500_000)
        self.assertAlmostEqual(r["recovery_rate_pct"], 50.0, places=2)

    def test_over_recovery_capped(self):
        # over-recovery capped at 200%
        r = self._run(amount_hacked_usd=1_000_000, amount_recovered_usd=3_000_000)
        self.assertLessEqual(r["recovery_rate_pct"], 200.0)

    def test_zero_hacked_no_crash(self):
        r = self._run(amount_hacked_usd=0, amount_recovered_usd=0)
        self.assertIsNotNone(r["recovery_rate_pct"])


class TestTVLRecoveryCalculation(unittest.TestCase):
    def setUp(self):
        self.tracker = ProtocolHackRecoveryTracker()
        self.cfg = {"log_path": "/tmp/test_tvl_rate.json"}

    def _run(self, **kw):
        return self.tracker.track([_inc(**kw)], self.cfg)["incidents"][0]

    def test_full_tvl_recovery(self):
        r = self._run(tvl_before_hack_usd=50_000_000, tvl_current_usd=50_000_000)
        self.assertAlmostEqual(r["tvl_recovery_pct"], 100.0, places=2)

    def test_zero_tvl_recovery(self):
        r = self._run(tvl_before_hack_usd=50_000_000, tvl_current_usd=0)
        self.assertAlmostEqual(r["tvl_recovery_pct"], 0.0, places=2)

    def test_half_tvl_recovery(self):
        r = self._run(tvl_before_hack_usd=100_000_000, tvl_current_usd=50_000_000)
        self.assertAlmostEqual(r["tvl_recovery_pct"], 50.0, places=2)

    def test_over_tvl_recovery_allowed(self):
        r = self._run(tvl_before_hack_usd=50_000_000, tvl_current_usd=100_000_000)
        self.assertGreater(r["tvl_recovery_pct"], 100.0)

    def test_zero_tvl_before_no_crash(self):
        r = self._run(tvl_before_hack_usd=0, tvl_current_usd=0)
        self.assertIsNotNone(r["tvl_recovery_pct"])


class TestLabels(unittest.TestCase):
    def setUp(self):
        self.tracker = ProtocolHackRecoveryTracker()
        self.cfg = {"log_path": "/tmp/test_hack_labels.json"}

    def _label(self, **kw):
        return self.tracker.track([_inc(**kw)], self.cfg)["incidents"][0]["label"]

    def test_fully_recovered(self):
        lbl = self._label(tvl_before_hack_usd=100, tvl_current_usd=95, users_compensated_pct=95.0,
                          hack_date_days_ago=60, days_since_resumption=30)
        self.assertEqual(lbl, "FULLY_RECOVERED")

    def test_mostly_recovered_by_tvl(self):
        lbl = self._label(tvl_before_hack_usd=100, tvl_current_usd=80, users_compensated_pct=50.0,
                          hack_date_days_ago=60, days_since_resumption=30)
        self.assertEqual(lbl, "MOSTLY_RECOVERED")

    def test_mostly_recovered_by_users(self):
        lbl = self._label(tvl_before_hack_usd=100, tvl_current_usd=50, users_compensated_pct=75.0,
                          hack_date_days_ago=60, days_since_resumption=30)
        self.assertEqual(lbl, "MOSTLY_RECOVERED")

    def test_partially_recovered(self):
        lbl = self._label(tvl_before_hack_usd=100, tvl_current_usd=50, users_compensated_pct=30.0,
                          hack_date_days_ago=60, days_since_resumption=30)
        self.assertEqual(lbl, "PARTIALLY_RECOVERED")

    def test_struggling(self):
        lbl = self._label(tvl_before_hack_usd=100, tvl_current_usd=10, users_compensated_pct=10.0,
                          hack_date_days_ago=60, days_since_resumption=30)
        self.assertEqual(lbl, "STRUGGLING")

    def test_abandoned_not_resumed_old(self):
        lbl = self._label(hack_date_days_ago=400.0, days_since_resumption=None,
                          tvl_current_usd=10, users_compensated_pct=10.0)
        self.assertEqual(lbl, "ABANDONED")

    def test_not_abandoned_if_resumed(self):
        lbl = self._label(hack_date_days_ago=400.0, days_since_resumption=200.0,
                          tvl_before_hack_usd=100, tvl_current_usd=10, users_compensated_pct=10.0)
        self.assertNotEqual(lbl, "ABANDONED")

    def test_not_abandoned_if_recent_hack(self):
        lbl = self._label(hack_date_days_ago=100.0, days_since_resumption=None,
                          tvl_current_usd=10, users_compensated_pct=10.0)
        self.assertNotEqual(lbl, "ABANDONED")

    def test_fully_recovered_boundary(self):
        lbl = self._label(tvl_before_hack_usd=100, tvl_current_usd=91, users_compensated_pct=91.0,
                          hack_date_days_ago=60, days_since_resumption=30)
        self.assertEqual(lbl, "FULLY_RECOVERED")

    def test_partially_at_boundary_30(self):
        lbl = self._label(tvl_before_hack_usd=100, tvl_current_usd=30, users_compensated_pct=5.0,
                          hack_date_days_ago=60, days_since_resumption=30)
        self.assertEqual(lbl, "PARTIALLY_RECOVERED")


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.tracker = ProtocolHackRecoveryTracker()
        self.cfg = {"log_path": "/tmp/test_hack_flags.json"}

    def _flags(self, **kw):
        return self.tracker.track([_inc(**kw)], self.cfg)["incidents"][0]["flags"]

    def test_uncompensated_users_flag(self):
        flags = self._flags(users_compensated_pct=49.0)
        self.assertIn("UNCOMPENSATED_USERS", flags)

    def test_no_uncompensated_flag_at_50(self):
        flags = self._flags(users_compensated_pct=50.0)
        self.assertNotIn("UNCOMPENSATED_USERS", flags)

    def test_no_post_audit_flag(self):
        flags = self._flags(audit_count_post_hack=0)
        self.assertIn("NO_POST_AUDIT", flags)

    def test_no_post_audit_flag_cleared_with_audits(self):
        flags = self._flags(audit_count_post_hack=1)
        self.assertNotIn("NO_POST_AUDIT", flags)

    def test_resumed_quickly_flag(self):
        flags = self._flags(days_since_resumption=20.0)
        self.assertIn("RESUMED_QUICKLY", flags)

    def test_no_resumed_quickly_at_30(self):
        flags = self._flags(days_since_resumption=30.0)
        self.assertNotIn("RESUMED_QUICKLY", flags)

    def test_no_resumed_quickly_when_none(self):
        flags = self._flags(days_since_resumption=None)
        self.assertNotIn("RESUMED_QUICKLY", flags)

    def test_over_insured_recovery_flag(self):
        flags = self._flags(amount_hacked_usd=1_000_000, amount_recovered_usd=1_500_000)
        self.assertIn("OVER_INSURED_RECOVERY", flags)

    def test_no_over_insured_when_equal(self):
        flags = self._flags(amount_hacked_usd=1_000_000, amount_recovered_usd=1_000_000)
        self.assertNotIn("OVER_INSURED_RECOVERY", flags)

    def test_no_over_insured_when_under(self):
        flags = self._flags(amount_hacked_usd=1_000_000, amount_recovered_usd=900_000)
        self.assertNotIn("OVER_INSURED_RECOVERY", flags)

    def test_repeat_hack_flag(self):
        flags = self._flags(hack_date_days_ago=100.0, prior_hacks=["2024-01-01"])
        self.assertIn("REPEAT_HACK", flags)

    def test_no_repeat_hack_when_old(self):
        flags = self._flags(hack_date_days_ago=200.0, prior_hacks=["2024-01-01"])
        self.assertNotIn("REPEAT_HACK", flags)

    def test_no_repeat_hack_when_no_prior(self):
        flags = self._flags(hack_date_days_ago=50.0, prior_hacks=[])
        self.assertNotIn("REPEAT_HACK", flags)


class TestScoresCalculation(unittest.TestCase):
    def setUp(self):
        self.tracker = ProtocolHackRecoveryTracker()
        self.cfg = {"log_path": "/tmp/test_hack_scores.json"}

    def _run(self, **kw):
        return self.tracker.track([_inc(**kw)], self.cfg)["incidents"][0]

    def test_compensation_score_range(self):
        r = self._run()
        self.assertGreaterEqual(r["compensation_score"], 0.0)
        self.assertLessEqual(r["compensation_score"], 100.0)

    def test_security_improvement_score_range(self):
        r = self._run()
        self.assertGreaterEqual(r["security_improvement_score"], 0.0)
        self.assertLessEqual(r["security_improvement_score"], 100.0)

    def test_overall_score_range(self):
        r = self._run()
        self.assertGreaterEqual(r["overall_recovery_score"], 0.0)
        self.assertLessEqual(r["overall_recovery_score"], 100.0)

    def test_zero_users_comp_low_compensation_score(self):
        r = self._run(users_compensated_pct=0.0)
        self.assertAlmostEqual(r["compensation_score"], 0.0, places=2)

    def test_full_users_comp_high_compensation_score(self):
        r = self._run(users_compensated_pct=100.0, amount_recovered_usd=1_000_000, amount_hacked_usd=1_000_000)
        self.assertAlmostEqual(r["compensation_score"], 100.0, places=2)

    def test_no_measures_no_audits_zero_security(self):
        r = self._run(new_security_measures=[], audit_count_post_hack=0)
        self.assertAlmostEqual(r["security_improvement_score"], 0.0, places=2)

    def test_all_five_measures_fifty_points(self):
        measures = ["bug_bounty", "formal_verification", "multisig", "timelock", "insurance"]
        r = self._run(new_security_measures=measures, audit_count_post_hack=0)
        self.assertAlmostEqual(r["security_improvement_score"], 50.0, places=2)

    def test_five_audits_fifty_points(self):
        r = self._run(new_security_measures=[], audit_count_post_hack=5)
        self.assertAlmostEqual(r["security_improvement_score"], 50.0, places=2)

    def test_all_measures_five_audits_max_100(self):
        measures = ["bug_bounty", "formal_verification", "multisig", "timelock", "insurance"]
        r = self._run(new_security_measures=measures, audit_count_post_hack=5)
        self.assertAlmostEqual(r["security_improvement_score"], 100.0, places=2)

    def test_duplicate_measures_not_double_counted(self):
        r1 = self._run(new_security_measures=["bug_bounty"], audit_count_post_hack=0)
        r2 = self._run(new_security_measures=["bug_bounty", "bug_bounty"], audit_count_post_hack=0)
        self.assertAlmostEqual(r1["security_improvement_score"], r2["security_improvement_score"], places=2)

    def test_overall_score_components_sum(self):
        # fully recovered + perfect security → near 100
        measures = ["bug_bounty", "formal_verification", "multisig", "timelock", "insurance"]
        r = self._run(tvl_before_hack_usd=100, tvl_current_usd=100,
                      users_compensated_pct=100.0, amount_hacked_usd=100, amount_recovered_usd=100,
                      new_security_measures=measures, audit_count_post_hack=5)
        self.assertAlmostEqual(r["overall_recovery_score"], 100.0, places=2)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.tracker = ProtocolHackRecoveryTracker()
        self.cfg = {"log_path": "/tmp/test_hack_agg.json"}

    def _run(self, incs):
        return self.tracker.track(incs, self.cfg)

    def test_best_recovery_is_highest_score(self):
        incs = [
            _inc(protocol="A", tvl_before_hack_usd=100, tvl_current_usd=100, users_compensated_pct=100,
                 amount_hacked_usd=100, amount_recovered_usd=100,
                 new_security_measures=["bug_bounty","multisig"], audit_count_post_hack=2),
            _inc(protocol="B", tvl_before_hack_usd=100, tvl_current_usd=10, users_compensated_pct=10,
                 amount_hacked_usd=100, amount_recovered_usd=0,
                 new_security_measures=[], audit_count_post_hack=0),
        ]
        r = self._run(incs)
        self.assertEqual(r["best_recovery"], "A")

    def test_worst_recovery_is_lowest_score(self):
        incs = [
            _inc(protocol="A", tvl_before_hack_usd=100, tvl_current_usd=100, users_compensated_pct=100,
                 amount_hacked_usd=100, amount_recovered_usd=100,
                 new_security_measures=[], audit_count_post_hack=0),
            _inc(protocol="B", tvl_before_hack_usd=100, tvl_current_usd=5, users_compensated_pct=5,
                 amount_hacked_usd=100, amount_recovered_usd=0,
                 new_security_measures=[], audit_count_post_hack=0),
        ]
        r = self._run(incs)
        self.assertEqual(r["worst_recovery"], "B")

    def test_average_score_correct(self):
        # Two identical incidents → avg equals individual score
        incs = [_inc(protocol="A"), _inc(protocol="B")]
        r = self._run(incs)
        self.assertAlmostEqual(
            r["average_recovery_score"],
            r["incidents"][0]["overall_recovery_score"],
            places=2
        )

    def test_fully_recovered_count(self):
        incs = [
            _inc(protocol="A", tvl_before_hack_usd=100, tvl_current_usd=95, users_compensated_pct=95,
                 hack_date_days_ago=60, days_since_resumption=30),
            _inc(protocol="B", tvl_before_hack_usd=100, tvl_current_usd=10, users_compensated_pct=10,
                 hack_date_days_ago=60, days_since_resumption=30),
        ]
        r = self._run(incs)
        self.assertEqual(r["fully_recovered_count"], 1)

    def test_abandoned_count(self):
        incs = [
            _inc(protocol="A", hack_date_days_ago=400, days_since_resumption=None,
                 tvl_current_usd=5, users_compensated_pct=5),
            _inc(protocol="B", hack_date_days_ago=400, days_since_resumption=None,
                 tvl_current_usd=5, users_compensated_pct=5),
            _inc(protocol="C", hack_date_days_ago=60, days_since_resumption=30),
        ]
        r = self._run(incs)
        self.assertEqual(r["abandoned_count"], 2)

    def test_single_incident_best_equals_worst(self):
        r = self._run([_inc(protocol="Solo")])
        self.assertEqual(r["best_recovery"], "Solo")
        self.assertEqual(r["worst_recovery"], "Solo")


class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.tracker = ProtocolHackRecoveryTracker()
        self.tmp = tempfile.mktemp(suffix=".json")
        self.cfg = {"log_path": self.tmp}

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)
        tmp2 = self.tmp + ".tmp"
        if os.path.exists(tmp2):
            os.remove(tmp2)

    def test_log_file_created(self):
        self.tracker.track([_inc()], self.cfg)
        self.assertTrue(os.path.exists(self.tmp))

    def test_log_is_json_list(self):
        self.tracker.track([_inc()], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_ts(self):
        self.tracker.track([_inc()], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertIn("ts", data[0])

    def test_log_entry_has_incident_count(self):
        self.tracker.track([_inc(), _inc(protocol="B")], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["incident_count"], 2)

    def test_log_accumulates(self):
        for _ in range(5):
            self.tracker.track([_inc()], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_cap_100(self):
        for _ in range(110):
            self.tracker.track([_inc()], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_log_cap_keeps_latest(self):
        for i in range(105):
            self.tracker.track([_inc(protocol=f"P{i}")], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_atomic_write_no_tmp_left(self):
        self.tracker.track([_inc()], self.cfg)
        self.assertFalse(os.path.exists(self.tmp + ".tmp"))

    def test_log_best_recovery_recorded(self):
        self.tracker.track([_inc(protocol="Euler")], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["best_recovery"], "Euler")

    def test_log_fully_recovered_count_recorded(self):
        self.tracker.track([
            _inc(protocol="A", tvl_before_hack_usd=100, tvl_current_usd=95, users_compensated_pct=95,
                 hack_date_days_ago=60, days_since_resumption=30)
        ], self.cfg)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["fully_recovered_count"], 1)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tracker = ProtocolHackRecoveryTracker()
        self.cfg = {"log_path": "/tmp/test_hack_edge.json"}

    def _run(self, **kw):
        return self.tracker.track([_inc(**kw)], self.cfg)["incidents"][0]

    def test_none_resumption_no_crash(self):
        r = self._run(days_since_resumption=None)
        self.assertIsNone(r["days_since_resumption"])

    def test_empty_security_measures(self):
        r = self._run(new_security_measures=[], audit_count_post_hack=0)
        self.assertEqual(r["security_improvement_score"], 0.0)

    def test_unknown_security_measure_not_counted(self):
        r = self._run(new_security_measures=["unknown_measure"], audit_count_post_hack=0)
        self.assertEqual(r["security_improvement_score"], 0.0)

    def test_more_than_5_audits_capped(self):
        r1 = self._run(audit_count_post_hack=5, new_security_measures=[])
        r2 = self._run(audit_count_post_hack=10, new_security_measures=[])
        self.assertAlmostEqual(r1["security_improvement_score"], r2["security_improvement_score"], places=2)

    def test_zero_tvl_before_no_crash(self):
        r = self._run(tvl_before_hack_usd=0.0)
        self.assertIsNotNone(r["tvl_recovery_pct"])

    def test_all_mechanisms_accepted(self):
        for mech in ["insurance", "treasury", "fundraise", "none", "partial_reimbursement"]:
            r = self._run(recovery_mechanism=mech)
            self.assertEqual(r["recovery_mechanism"], mech)

    def test_protocol_name_preserved(self):
        r = self._run(protocol="curve-finance")
        self.assertEqual(r["protocol"], "curve-finance")

    def test_large_hack_amounts_no_overflow(self):
        r = self._run(amount_hacked_usd=1e12, amount_recovered_usd=9e11)
        self.assertAlmostEqual(r["recovery_rate_pct"], 90.0, places=2)

    def test_five_incidents_analyzed(self):
        incs = [_inc(protocol=f"P{i}") for i in range(5)]
        r = self.tracker.track(incs, self.cfg)
        self.assertEqual(len(r["incidents"]), 5)

    def test_all_labels_valid(self):
        valid = {"FULLY_RECOVERED", "MOSTLY_RECOVERED", "PARTIALLY_RECOVERED", "STRUGGLING", "ABANDONED"}
        incs = [
            _inc(protocol="FR", tvl_before_hack_usd=100, tvl_current_usd=95, users_compensated_pct=95,
                 hack_date_days_ago=60, days_since_resumption=30),
            _inc(protocol="MR", tvl_before_hack_usd=100, tvl_current_usd=75, users_compensated_pct=50,
                 hack_date_days_ago=60, days_since_resumption=30),
            _inc(protocol="PR", tvl_before_hack_usd=100, tvl_current_usd=50, users_compensated_pct=30,
                 hack_date_days_ago=60, days_since_resumption=30),
            _inc(protocol="ST", tvl_before_hack_usd=100, tvl_current_usd=10, users_compensated_pct=10,
                 hack_date_days_ago=60, days_since_resumption=30),
            _inc(protocol="AB", hack_date_days_ago=400, days_since_resumption=None,
                 tvl_current_usd=5, users_compensated_pct=5),
        ]
        r = self.tracker.track(incs, self.cfg)
        for inc in r["incidents"]:
            self.assertIn(inc["label"], valid)


if __name__ == "__main__":
    unittest.main()
