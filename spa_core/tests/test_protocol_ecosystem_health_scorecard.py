"""
Tests for MP-935 ProtocolEcosystemHealthScorecard
Run: python3 -m unittest spa_core.tests.test_protocol_ecosystem_health_scorecard -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_ecosystem_health_scorecard import (
    ProtocolEcosystemHealthScorecard,
    _clamp,
    _log_scale_score,
    _atomic_log,
    _health_label,
    _financial_health,
    _user_adoption,
    _security_posture,
    _developer_activity,
    _ecosystem_reach,
)

NO_LOG = {"write_log": False}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _thriving_protocol(name="Aave") -> dict:
    return {
        "name": name,
        "tvl_usd": 15_000_000_000.0,
        "tvl_30d_change_pct": 25.0,
        "daily_active_users": 50_000,
        "dau_30d_change_pct": 30.0,
        "revenue_monthly_usd": 5_000_000.0,
        "token_price_change_30d_pct": 20.0,
        "github_commits_30d": 300,
        "audit_count": 5,
        "incident_count_12m": 0,
        "community_score": 90.0,
        "developer_count": 80,
        "integrations_count": 40,
        "chain_count": 8,
    }


def _critical_protocol(name="BadFi") -> dict:
    return {
        "name": name,
        "tvl_usd": 50_000.0,
        "tvl_30d_change_pct": -40.0,
        "daily_active_users": 5,
        "dau_30d_change_pct": -50.0,
        "revenue_monthly_usd": 100.0,
        "token_price_change_30d_pct": -50.0,
        "github_commits_30d": 0,
        "audit_count": 0,
        "incident_count_12m": 3,
        "community_score": 5.0,
        "developer_count": 1,
        "integrations_count": 1,
        "chain_count": 1,
    }


# ===========================================================================
# 1. Utility helpers
# ===========================================================================

class TestClamp(unittest.TestCase):
    def test_within(self):
        self.assertEqual(_clamp(50.0), 50.0)

    def test_below_lo(self):
        self.assertEqual(_clamp(-1.0), 0.0)

    def test_above_hi(self):
        self.assertEqual(_clamp(101.0), 100.0)

    def test_boundary_lo(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_boundary_hi(self):
        self.assertEqual(_clamp(100.0), 100.0)

    def test_custom_range(self):
        self.assertEqual(_clamp(150.0, 0.0, 200.0), 150.0)


class TestLogScaleScore(unittest.TestCase):
    def test_at_lo(self):
        s = _log_scale_score(1e5, 1e5, 1e10)
        self.assertAlmostEqual(s, 0.0, places=2)

    def test_at_hi(self):
        s = _log_scale_score(1e10, 1e5, 1e10)
        self.assertAlmostEqual(s, 100.0, places=2)

    def test_zero_value(self):
        s = _log_scale_score(0.0, 1e5, 1e10)
        self.assertEqual(s, 0.0)

    def test_midpoint_roughly_50(self):
        # mid of log range
        lo, hi = 1e4, 1e8
        mid = 10 ** ((math.log10(lo) + math.log10(hi)) / 2)
        s = _log_scale_score(mid, lo, hi)
        self.assertAlmostEqual(s, 50.0, places=2)


class TestHealthLabel(unittest.TestCase):
    def test_thriving(self):
        self.assertEqual(_health_label(85.0), "THRIVING")

    def test_thriving_boundary(self):
        self.assertEqual(_health_label(80.0), "THRIVING")

    def test_healthy(self):
        self.assertEqual(_health_label(70.0), "HEALTHY")

    def test_healthy_boundary(self):
        self.assertEqual(_health_label(65.0), "HEALTHY")

    def test_stable(self):
        self.assertEqual(_health_label(55.0), "STABLE")

    def test_stable_boundary(self):
        self.assertEqual(_health_label(50.0), "STABLE")

    def test_declining(self):
        self.assertEqual(_health_label(40.0), "DECLINING")

    def test_declining_boundary(self):
        self.assertEqual(_health_label(35.0), "DECLINING")

    def test_critical(self):
        self.assertEqual(_health_label(20.0), "CRITICAL")

    def test_critical_zero(self):
        self.assertEqual(_health_label(0.0), "CRITICAL")


# ===========================================================================
# 2. Sub-score calculators
# ===========================================================================

class TestFinancialHealth(unittest.TestCase):
    def test_high_tvl_high_revenue_positive_trend(self):
        p = _thriving_protocol()
        s = _financial_health(p)
        self.assertGreater(s, 60.0)

    def test_low_tvl_negative_trend(self):
        p = _critical_protocol()
        s = _financial_health(p)
        self.assertLess(s, 30.0)

    def test_zero_tvl(self):
        p = {"tvl_usd": 0.0, "tvl_30d_change_pct": 0.0,
             "revenue_monthly_usd": 0.0, "token_price_change_30d_pct": 0.0}
        s = _financial_health(p)
        self.assertGreaterEqual(s, 0.0)

    def test_result_clamped(self):
        p = _thriving_protocol()
        s = _financial_health(p)
        self.assertLessEqual(s, 100.0)
        self.assertGreaterEqual(s, 0.0)

    def test_positive_token_price_boosts(self):
        p1 = dict(_thriving_protocol(), token_price_change_30d_pct=60.0)
        p2 = dict(_thriving_protocol(), token_price_change_30d_pct=-50.0)
        self.assertGreater(_financial_health(p1), _financial_health(p2))

    def test_tvl_trend_positive_boosts(self):
        p1 = dict(_thriving_protocol(), tvl_30d_change_pct=35.0)
        p2 = dict(_thriving_protocol(), tvl_30d_change_pct=-40.0)
        self.assertGreater(_financial_health(p1), _financial_health(p2))


class TestUserAdoption(unittest.TestCase):
    def test_high_dau_high_growth(self):
        p = _thriving_protocol()
        s = _user_adoption(p)
        self.assertGreater(s, 50.0)

    def test_low_dau_negative_growth(self):
        p = _critical_protocol()
        s = _user_adoption(p)
        self.assertLess(s, 30.0)

    def test_viral_growth_boosts(self):
        p1 = dict(_thriving_protocol(), dau_30d_change_pct=70.0)
        p2 = dict(_thriving_protocol(), dau_30d_change_pct=-40.0)
        self.assertGreater(_user_adoption(p1), _user_adoption(p2))

    def test_result_clamped(self):
        p = _thriving_protocol()
        s = _user_adoption(p)
        self.assertLessEqual(s, 100.0)
        self.assertGreaterEqual(s, 0.0)

    def test_zero_dau(self):
        p = {"daily_active_users": 0, "dau_30d_change_pct": 0.0}
        s = _user_adoption(p)
        self.assertGreaterEqual(s, 0.0)


class TestSecurityPosture(unittest.TestCase):
    def test_no_audits_no_incidents(self):
        p = {"audit_count": 0, "incident_count_12m": 0}
        s = _security_posture(p)
        self.assertAlmostEqual(s, 40.0, places=1)

    def test_5_audits_0_incidents(self):
        p = {"audit_count": 5, "incident_count_12m": 0}
        s = _security_posture(p)
        self.assertAlmostEqual(s, 100.0, places=1)

    def test_0_audits_3_incidents(self):
        p = {"audit_count": 0, "incident_count_12m": 3}
        s = _security_posture(p)
        self.assertAlmostEqual(s, 0.0, places=1)

    def test_3_audits_1_incident(self):
        p = {"audit_count": 3, "incident_count_12m": 1}
        s = _security_posture(p)
        self.assertAlmostEqual(s, 54.0 + 24.0, places=1)

    def test_result_clamped(self):
        p = {"audit_count": 10, "incident_count_12m": 0}
        s = _security_posture(p)
        self.assertLessEqual(s, 100.0)
        self.assertGreaterEqual(s, 0.0)

    def test_1_audit_boosts_over_0(self):
        p0 = {"audit_count": 0, "incident_count_12m": 0}
        p1 = {"audit_count": 1, "incident_count_12m": 0}
        self.assertGreater(_security_posture(p1), _security_posture(p0))


class TestDeveloperActivity(unittest.TestCase):
    def test_high_commits_devs_integrations(self):
        p = _thriving_protocol()
        s = _developer_activity(p)
        self.assertGreater(s, 60.0)

    def test_zero_activity(self):
        p = {"github_commits_30d": 0, "developer_count": 0, "integrations_count": 0}
        s = _developer_activity(p)
        self.assertGreaterEqual(s, 0.0)

    def test_result_clamped(self):
        p = _thriving_protocol()
        s = _developer_activity(p)
        self.assertLessEqual(s, 100.0)
        self.assertGreaterEqual(s, 0.0)

    def test_high_commits_more_than_low(self):
        p_hi = dict(_thriving_protocol(), github_commits_30d=500)
        p_lo = dict(_thriving_protocol(), github_commits_30d=5)
        self.assertGreater(_developer_activity(p_hi), _developer_activity(p_lo))


class TestEcosystemReach(unittest.TestCase):
    def test_high_ecosystem_score(self):
        p = _thriving_protocol()
        s = _ecosystem_reach(p)
        self.assertGreater(s, 50.0)

    def test_low_ecosystem_score(self):
        p = _critical_protocol()
        s = _ecosystem_reach(p)
        self.assertLessEqual(s, 50.0)

    def test_result_clamped(self):
        p = _thriving_protocol()
        s = _ecosystem_reach(p)
        self.assertLessEqual(s, 100.0)
        self.assertGreaterEqual(s, 0.0)

    def test_more_chains_boosts(self):
        p1 = dict(_thriving_protocol(), chain_count=15)
        p2 = dict(_thriving_protocol(), chain_count=1)
        self.assertGreater(_ecosystem_reach(p1), _ecosystem_reach(p2))

    def test_zero_chains(self):
        p = {"chain_count": 0, "community_score": 0.0, "integrations_count": 0}
        s = _ecosystem_reach(p)
        self.assertGreaterEqual(s, 0.0)


# ===========================================================================
# 3. Instantiation
# ===========================================================================

class TestInstantiation(unittest.TestCase):
    def test_create(self):
        sc = ProtocolEcosystemHealthScorecard()
        self.assertIsNotNone(sc)

    def test_score_callable(self):
        self.assertTrue(callable(ProtocolEcosystemHealthScorecard().score))

    def test_empty_list_returns_dict(self):
        r = ProtocolEcosystemHealthScorecard().score([], NO_LOG)
        self.assertIsInstance(r, dict)

    def test_raises_typeerror(self):
        with self.assertRaises(TypeError):
            ProtocolEcosystemHealthScorecard().score("bad", NO_LOG)

    def test_result_keys(self):
        r = ProtocolEcosystemHealthScorecard().score([], NO_LOG)
        for k in ("results", "aggregates", "timestamp"):
            self.assertIn(k, r)

    def test_timestamp_positive(self):
        r = ProtocolEcosystemHealthScorecard().score([], NO_LOG)
        self.assertGreater(r["timestamp"], 0)


# ===========================================================================
# 4. Per-protocol result structure
# ===========================================================================

class TestPerProtocolResult(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolEcosystemHealthScorecard()
        self.r = self.sc.score([_thriving_protocol()], NO_LOG)["results"][0]

    def test_name_preserved(self):
        self.assertEqual(self.r["name"], "Aave")

    def test_financial_health_present(self):
        self.assertIn("financial_health", self.r)

    def test_user_adoption_present(self):
        self.assertIn("user_adoption", self.r)

    def test_security_posture_present(self):
        self.assertIn("security_posture", self.r)

    def test_developer_activity_present(self):
        self.assertIn("developer_activity", self.r)

    def test_ecosystem_reach_present(self):
        self.assertIn("ecosystem_reach", self.r)

    def test_composite_score_present(self):
        self.assertIn("composite_score", self.r)

    def test_health_label_present(self):
        self.assertIn("health_label", self.r)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_sub_scores_in_range(self):
        for key in ("financial_health", "user_adoption", "security_posture",
                    "developer_activity", "ecosystem_reach", "composite_score"):
            v = self.r[key]
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 100.0)


# ===========================================================================
# 5. Health labels
# ===========================================================================

class TestHealthLabelAssignment(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolEcosystemHealthScorecard()

    def test_thriving_protocol_label(self):
        r = self.sc.score([_thriving_protocol()], NO_LOG)["results"][0]
        self.assertEqual(r["health_label"], "THRIVING")

    def test_critical_protocol_label(self):
        r = self.sc.score([_critical_protocol()], NO_LOG)["results"][0]
        self.assertEqual(r["health_label"], "CRITICAL")

    def test_health_label_valid_values(self):
        valid = {"THRIVING", "HEALTHY", "STABLE", "DECLINING", "CRITICAL"}
        for p in [_thriving_protocol(), _critical_protocol()]:
            r = self.sc.score([p], NO_LOG)["results"][0]
            self.assertIn(r["health_label"], valid)


# ===========================================================================
# 6. Flags
# ===========================================================================

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolEcosystemHealthScorecard()

    def test_all_metrics_positive_flag(self):
        # Need all 5 sub-scores > 70 — use extreme thriving protocol
        p = {
            "name": "SuperFi",
            "tvl_usd": 50_000_000_000.0,
            "tvl_30d_change_pct": 35.0,
            "daily_active_users": 500_000,
            "dau_30d_change_pct": 60.0,
            "revenue_monthly_usd": 50_000_000.0,
            "token_price_change_30d_pct": 60.0,
            "github_commits_30d": 600,
            "audit_count": 5,
            "incident_count_12m": 0,
            "community_score": 100.0,
            "developer_count": 150,
            "integrations_count": 60,
            "chain_count": 15,
        }
        r = self.sc.score([p], NO_LOG)["results"][0]
        self.assertIn("ALL_METRICS_POSITIVE", r["flags"])

    def test_security_concern_flag(self):
        p = {"name": "RiskyFi", "audit_count": 0, "incident_count_12m": 3,
             "tvl_usd": 1e6, "tvl_30d_change_pct": 0.0,
             "daily_active_users": 100, "dau_30d_change_pct": 0.0,
             "revenue_monthly_usd": 1000.0, "token_price_change_30d_pct": 0.0,
             "github_commits_30d": 50, "community_score": 50.0,
             "developer_count": 10, "integrations_count": 5, "chain_count": 2}
        r = self.sc.score([p], NO_LOG)["results"][0]
        self.assertIn("SECURITY_CONCERN", r["flags"])

    def test_no_security_concern_flag_when_secure(self):
        p = dict(_thriving_protocol(), audit_count=5, incident_count_12m=0)
        r = self.sc.score([p], NO_LOG)["results"][0]
        self.assertNotIn("SECURITY_CONCERN", r["flags"])

    def test_developer_exodus_flag(self):
        p = {"name": "FleeFi", "audit_count": 1, "incident_count_12m": 0,
             "tvl_usd": 1e7, "tvl_30d_change_pct": 0.0,
             "daily_active_users": 500, "dau_30d_change_pct": -10.0,
             "revenue_monthly_usd": 50_000.0, "token_price_change_30d_pct": 0.0,
             "github_commits_30d": 5, "community_score": 40.0,
             "developer_count": 2, "integrations_count": 3, "chain_count": 2}
        r = self.sc.score([p], NO_LOG)["results"][0]
        self.assertIn("DEVELOPER_EXODUS", r["flags"])

    def test_no_developer_exodus_flag_when_active(self):
        p = dict(_thriving_protocol(), github_commits_30d=300, developer_count=80)
        r = self.sc.score([p], NO_LOG)["results"][0]
        self.assertNotIn("DEVELOPER_EXODUS", r["flags"])

    def test_viral_adoption_flag(self):
        p = dict(_thriving_protocol(), dau_30d_change_pct=75.0)
        r = self.sc.score([p], NO_LOG)["results"][0]
        self.assertIn("VIRAL_ADOPTION", r["flags"])

    def test_no_viral_adoption_flag_low_growth(self):
        p = dict(_thriving_protocol(), dau_30d_change_pct=10.0)
        r = self.sc.score([p], NO_LOG)["results"][0]
        self.assertNotIn("VIRAL_ADOPTION", r["flags"])

    def test_tvl_dominance_flag(self):
        p = dict(_thriving_protocol(), tvl_usd=2_000_000_000.0)
        r = self.sc.score([p], NO_LOG)["results"][0]
        self.assertIn("TVL_DOMINANCE", r["flags"])

    def test_no_tvl_dominance_flag_small_tvl(self):
        p = dict(_thriving_protocol(), tvl_usd=500_000_000.0)
        r = self.sc.score([p], NO_LOG)["results"][0]
        self.assertNotIn("TVL_DOMINANCE", r["flags"])

    def test_flags_is_list(self):
        r = self.sc.score([_thriving_protocol()], NO_LOG)["results"][0]
        self.assertIsInstance(r["flags"], list)


# ===========================================================================
# 7. Aggregates
# ===========================================================================

class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolEcosystemHealthScorecard()

    def test_empty_aggregates(self):
        agg = self.sc.score([], NO_LOG)["aggregates"]
        self.assertIsNone(agg["healthiest_protocol"])
        self.assertIsNone(agg["most_critical"])
        self.assertEqual(agg["average_composite"], 0.0)
        self.assertEqual(agg["thriving_count"], 0)
        self.assertEqual(agg["critical_count"], 0)
        self.assertEqual(agg["ecosystem_composite_score"], 0.0)

    def test_healthiest_protocol(self):
        ps = [_thriving_protocol("Good"), _critical_protocol("Bad")]
        agg = self.sc.score(ps, NO_LOG)["aggregates"]
        self.assertEqual(agg["healthiest_protocol"], "Good")

    def test_most_critical_protocol(self):
        ps = [_thriving_protocol("Good"), _critical_protocol("Bad")]
        agg = self.sc.score(ps, NO_LOG)["aggregates"]
        self.assertEqual(agg["most_critical"], "Bad")

    def test_average_composite(self):
        ps = [_thriving_protocol(), _critical_protocol()]
        results = self.sc.score(ps, NO_LOG)["results"]
        expected_avg = sum(r["composite_score"] for r in results) / 2
        agg = self.sc.score(ps, NO_LOG)["aggregates"]
        self.assertAlmostEqual(agg["average_composite"], expected_avg, places=1)

    def test_thriving_count(self):
        ps = [_thriving_protocol("A"), _thriving_protocol("B"), _critical_protocol("C")]
        agg = self.sc.score(ps, NO_LOG)["aggregates"]
        self.assertGreaterEqual(agg["thriving_count"], 1)

    def test_critical_count(self):
        ps = [_critical_protocol("A"), _critical_protocol("B"), _thriving_protocol("C")]
        agg = self.sc.score(ps, NO_LOG)["aggregates"]
        self.assertGreaterEqual(agg["critical_count"], 1)

    def test_ecosystem_composite_matches_average(self):
        ps = [_thriving_protocol(), _critical_protocol()]
        agg = self.sc.score(ps, NO_LOG)["aggregates"]
        self.assertAlmostEqual(agg["ecosystem_composite_score"],
                               agg["average_composite"], places=4)

    def test_single_protocol_aggregates(self):
        agg = self.sc.score([_thriving_protocol("Solo")], NO_LOG)["aggregates"]
        self.assertEqual(agg["healthiest_protocol"], "Solo")
        self.assertEqual(agg["most_critical"], "Solo")


# ===========================================================================
# 8. Ring-buffer log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "eco_log.json")
            _atomic_log(p, {"x": 1})
            self.assertTrue(os.path.exists(p))

    def test_content_is_list(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "eco_log.json")
            _atomic_log(p, {"x": 1})
            with open(p) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_entry_appended(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "eco_log.json")
            _atomic_log(p, {"val": 99})
            with open(p) as f:
                data = json.load(f)
            self.assertEqual(data[0]["val"], 99)

    def test_cap_enforced(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "eco_log.json")
            for i in range(110):
                _atomic_log(p, {"i": i})
            with open(p) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), 100)

    def test_multiple_entries(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "eco_log.json")
            _atomic_log(p, {"n": 1})
            _atomic_log(p, {"n": 2})
            with open(p) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)

    def test_write_log_false_no_file(self):
        sc = ProtocolEcosystemHealthScorecard()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "no_log.json")
            sc.score([_thriving_protocol()], {"write_log": False, "log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_write_log_true_creates_file(self):
        sc = ProtocolEcosystemHealthScorecard()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            sc.score([_thriving_protocol()], {"write_log": True, "log_path": path})
            self.assertTrue(os.path.exists(path))


# ===========================================================================
# 9. Composite score weight validation
# ===========================================================================

class TestCompositeWeights(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolEcosystemHealthScorecard()

    def test_composite_between_0_100(self):
        for p in [_thriving_protocol(), _critical_protocol()]:
            r = self.sc.score([p], NO_LOG)["results"][0]
            self.assertGreaterEqual(r["composite_score"], 0.0)
            self.assertLessEqual(r["composite_score"], 100.0)

    def test_higher_all_inputs_higher_composite(self):
        r_hi = self.sc.score([_thriving_protocol()], NO_LOG)["results"][0]
        r_lo = self.sc.score([_critical_protocol()], NO_LOG)["results"][0]
        self.assertGreater(r_hi["composite_score"], r_lo["composite_score"])


# ===========================================================================
# 10. Edge cases & robustness
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.sc = ProtocolEcosystemHealthScorecard()

    def test_missing_fields_use_defaults(self):
        r = self.sc.score([{"name": "Empty"}], NO_LOG)
        self.assertIsInstance(r["results"][0], dict)

    def test_empty_dict(self):
        r = self.sc.score([{}], NO_LOG)
        self.assertIn("composite_score", r["results"][0])

    def test_none_config_defaults(self):
        r = ProtocolEcosystemHealthScorecard().score([_thriving_protocol()], None)
        self.assertIsInstance(r, dict)

    def test_large_batch(self):
        ps = [_thriving_protocol(f"Proto{i}") for i in range(20)]
        r = self.sc.score(ps, NO_LOG)
        self.assertEqual(len(r["results"]), 20)

    def test_name_defaults_to_unknown(self):
        r = self.sc.score([{}], NO_LOG)["results"][0]
        self.assertEqual(r["name"], "unknown")

    def test_zero_tvl_still_scores(self):
        p = dict(_critical_protocol(), tvl_usd=0.0)
        r = self.sc.score([p], NO_LOG)["results"][0]
        self.assertGreaterEqual(r["composite_score"], 0.0)

    def test_extreme_positive_values_clamp(self):
        p = {
            "name": "GodFi",
            "tvl_usd": 1e15, "tvl_30d_change_pct": 1000.0,
            "daily_active_users": 1_000_000_000, "dau_30d_change_pct": 1000.0,
            "revenue_monthly_usd": 1e12, "token_price_change_30d_pct": 1000.0,
            "github_commits_30d": 100_000, "audit_count": 100,
            "incident_count_12m": 0, "community_score": 100.0,
            "developer_count": 10_000, "integrations_count": 10_000, "chain_count": 1000,
        }
        r = self.sc.score([p], NO_LOG)["results"][0]
        self.assertLessEqual(r["composite_score"], 100.0)
        self.assertGreaterEqual(r["composite_score"], 0.0)

    def test_multiple_protocols_all_scored(self):
        ps = [_thriving_protocol("A"), _critical_protocol("B")]
        results = self.sc.score(ps, NO_LOG)["results"]
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["name"], "A")
        self.assertEqual(results[1]["name"], "B")


if __name__ == "__main__":
    unittest.main()
