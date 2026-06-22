"""
Tests for MP-860: ProtocolDeveloperActivityTracker
Run: python3 -m unittest spa_core.tests.test_protocol_developer_activity_tracker -v
"""

import json
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.protocol_developer_activity_tracker import (
    analyze,
    _commit_momentum_score,
    _team_health_score,
    _maintenance_score,
    _security_investment_score,
    _activity_level,
    _velocity_trend,
    _issue_resolution_rate,
    MAX_ENTRIES,
)


# ---------------------------------------------------------------------------
# Helper factory
# ---------------------------------------------------------------------------

def make_protocol(**kwargs):
    base = {
        "name": "TestProtocol",
        "commits_last_30d": 20,
        "commits_last_90d": 60,
        "active_contributors_30d": 5,
        "total_contributors": 20,
        "open_issues": 10,
        "closed_issues_30d": 5,
        "days_since_last_commit": 3,
        "days_since_last_release": 20,
        "has_bug_bounty": True,
        "bug_bounty_usd": 500_000,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# _commit_momentum_score
# ---------------------------------------------------------------------------

class TestCommitMomentumScore(unittest.TestCase):

    def test_zero_commits(self):
        self.assertEqual(_commit_momentum_score(0), 0)

    def test_1_commit(self):
        self.assertEqual(_commit_momentum_score(1), 8)

    def test_4_commits(self):
        self.assertEqual(_commit_momentum_score(4), 8)

    def test_5_commits(self):
        self.assertEqual(_commit_momentum_score(5), 15)

    def test_9_commits(self):
        self.assertEqual(_commit_momentum_score(9), 15)

    def test_10_commits(self):
        self.assertEqual(_commit_momentum_score(10), 20)

    def test_19_commits(self):
        self.assertEqual(_commit_momentum_score(19), 20)

    def test_20_commits(self):
        self.assertEqual(_commit_momentum_score(20), 25)

    def test_49_commits(self):
        self.assertEqual(_commit_momentum_score(49), 25)

    def test_50_commits(self):
        self.assertEqual(_commit_momentum_score(50), 30)

    def test_100_commits(self):
        self.assertEqual(_commit_momentum_score(100), 30)


# ---------------------------------------------------------------------------
# _team_health_score
# ---------------------------------------------------------------------------

class TestTeamHealthScore(unittest.TestCase):

    def test_zero_contributors(self):
        self.assertEqual(_team_health_score(0, 10), 0)

    def test_one_contributor(self):
        # base=3, concentration=1/10=0.1 → no bonus
        self.assertEqual(_team_health_score(1, 10), 3)

    def test_two_contributors(self):
        # base=5, concentration=2/10=0.2 → bonus=3
        self.assertEqual(_team_health_score(2, 10), 8)

    def test_three_contributors(self):
        # base=8, concentration=3/10=0.3 → bonus=3
        self.assertEqual(_team_health_score(3, 10), 11)

    def test_five_contributors(self):
        # base=12, concentration=5/20=0.25 → bonus=3
        self.assertEqual(_team_health_score(5, 20), 15)

    def test_ten_contributors(self):
        # base=15, concentration=10/20=0.5 → bonus=5
        self.assertEqual(_team_health_score(10, 20), 20)

    def test_twelve_contributors_cap(self):
        # base=15, concentration=12/20=0.6 → bonus=5 → 20, cap=25 ok
        self.assertEqual(_team_health_score(12, 20), 20)

    def test_total_contributors_zero(self):
        # concentration=0, no bonus
        # active=10 → base=15, no bonus
        self.assertEqual(_team_health_score(10, 0), 15)

    def test_high_concentration_bonus(self):
        # active=5, total=5 → concentration=1.0 ≥ 0.5 → bonus=5
        # base=12 → total=17
        self.assertEqual(_team_health_score(5, 5), 17)

    def test_cap_at_25(self):
        # active=50 → base=15, concentration=50/50=1.0 → bonus=5 → 20, still <25
        result = _team_health_score(50, 50)
        self.assertLessEqual(result, 25)

    def test_zero_active_zero_total(self):
        self.assertEqual(_team_health_score(0, 0), 0)

    def test_moderate_concentration(self):
        # active=2, total=8 → concentration=0.25 ≥ 0.2 → bonus=3, base=5 → 8
        self.assertEqual(_team_health_score(2, 8), 8)


# ---------------------------------------------------------------------------
# _maintenance_score
# ---------------------------------------------------------------------------

class TestMaintenanceScore(unittest.TestCase):

    def test_very_recent_commit_and_release(self):
        # commit<=7 → 15, release<=30 → 10 → 25
        self.assertEqual(_maintenance_score(3, 15), 25)

    def test_commit_le_30(self):
        # 12 → 12
        self.assertEqual(_maintenance_score(12, 20), min(25, 12 + 10))

    def test_commit_le_90(self):
        self.assertEqual(_maintenance_score(60, 20), min(25, 8 + 10))

    def test_commit_le_180(self):
        self.assertEqual(_maintenance_score(120, 20), min(25, 4 + 10))

    def test_commit_gt_180(self):
        self.assertEqual(_maintenance_score(200, 20), min(25, 0 + 10))

    def test_release_le_30(self):
        self.assertEqual(_maintenance_score(3, 25), min(25, 15 + 10))

    def test_release_le_90(self):
        self.assertEqual(_maintenance_score(3, 60), min(25, 15 + 7))

    def test_release_le_180(self):
        self.assertEqual(_maintenance_score(3, 120), min(25, 15 + 5))

    def test_release_le_365(self):
        self.assertEqual(_maintenance_score(3, 200), min(25, 15 + 3))

    def test_release_gt_365(self):
        self.assertEqual(_maintenance_score(3, 400), min(25, 15 + 0))

    def test_stale_everything(self):
        # commit>180 → 0, release>365 → 0
        self.assertEqual(_maintenance_score(365, 400), 0)

    def test_boundary_commit_7(self):
        self.assertEqual(_maintenance_score(7, 20), min(25, 15 + 10))

    def test_boundary_commit_30(self):
        self.assertEqual(_maintenance_score(30, 20), min(25, 12 + 10))

    def test_boundary_commit_90(self):
        self.assertEqual(_maintenance_score(90, 20), min(25, 8 + 10))

    def test_boundary_commit_180(self):
        self.assertEqual(_maintenance_score(180, 20), min(25, 4 + 10))

    def test_cap_at_25(self):
        result = _maintenance_score(1, 1)
        self.assertLessEqual(result, 25)


# ---------------------------------------------------------------------------
# _security_investment_score
# ---------------------------------------------------------------------------

class TestSecurityInvestmentScore(unittest.TestCase):

    def test_no_bug_bounty_returns_0(self):
        self.assertEqual(_security_investment_score(False, 0), 0)

    def test_no_bug_bounty_large_usd_still_0(self):
        self.assertEqual(_security_investment_score(False, 5_000_000), 0)

    def test_bounty_1m_plus(self):
        # base=10 + 10 = 20
        self.assertEqual(_security_investment_score(True, 1_000_000), 20)

    def test_bounty_2m(self):
        self.assertEqual(_security_investment_score(True, 2_000_000), 20)

    def test_bounty_500k(self):
        # base=10 + 7 = 17
        self.assertEqual(_security_investment_score(True, 500_000), 17)

    def test_bounty_100k(self):
        # base=10 + 5 = 15
        self.assertEqual(_security_investment_score(True, 100_000), 15)

    def test_bounty_10k(self):
        # base=10 + 3 = 13
        self.assertEqual(_security_investment_score(True, 10_000), 13)

    def test_bounty_5k(self):
        # base=10 + 1 = 11
        self.assertEqual(_security_investment_score(True, 5_000), 11)

    def test_bounty_true_zero_usd(self):
        # has_bug_bounty=True but usd=0 → bounty_score=0 → total=10
        self.assertEqual(_security_investment_score(True, 0), 10)

    def test_cap_at_20(self):
        result = _security_investment_score(True, 10_000_000)
        self.assertLessEqual(result, 20)

    def test_boundary_500k_exact(self):
        self.assertEqual(_security_investment_score(True, 500_000), 17)

    def test_boundary_100k_exact(self):
        self.assertEqual(_security_investment_score(True, 100_000), 15)

    def test_boundary_1m_exact(self):
        self.assertEqual(_security_investment_score(True, 1_000_000), 20)

    def test_boundary_10k_exact(self):
        self.assertEqual(_security_investment_score(True, 10_000), 13)


# ---------------------------------------------------------------------------
# _activity_level
# ---------------------------------------------------------------------------

class TestActivityLevel(unittest.TestCase):

    def test_very_active_80(self):
        self.assertEqual(_activity_level(80), "VERY_ACTIVE")

    def test_very_active_100(self):
        self.assertEqual(_activity_level(100), "VERY_ACTIVE")

    def test_active_60(self):
        self.assertEqual(_activity_level(60), "ACTIVE")

    def test_active_79(self):
        self.assertEqual(_activity_level(79), "ACTIVE")

    def test_moderate_40(self):
        self.assertEqual(_activity_level(40), "MODERATE")

    def test_moderate_59(self):
        self.assertEqual(_activity_level(59), "MODERATE")

    def test_low_20(self):
        self.assertEqual(_activity_level(20), "LOW")

    def test_low_39(self):
        self.assertEqual(_activity_level(39), "LOW")

    def test_inactive_0(self):
        self.assertEqual(_activity_level(0), "INACTIVE")

    def test_inactive_19(self):
        self.assertEqual(_activity_level(19), "INACTIVE")


# ---------------------------------------------------------------------------
# _velocity_trend
# ---------------------------------------------------------------------------

class TestVelocityTrend(unittest.TestCase):

    def test_stagnant_zero_commits_30d(self):
        self.assertEqual(_velocity_trend(0, 90), "STAGNANT")

    def test_stagnant_zero_both(self):
        self.assertEqual(_velocity_trend(0, 0), "STAGNANT")

    def test_accelerating(self):
        # avg_30d = 90/3 = 30; 30*1.5 = 45; 50 > 45 → ACCELERATING
        self.assertEqual(_velocity_trend(50, 90), "ACCELERATING")

    def test_decelerating(self):
        # avg_30d = 90/3 = 30; 30*0.5 = 15; 5 < 15 → DECELERATING
        self.assertEqual(_velocity_trend(5, 90), "DECELERATING")

    def test_stable(self):
        # avg_30d = 90/3 = 30; 30 is exactly equal → STABLE
        self.assertEqual(_velocity_trend(30, 90), "STABLE")

    def test_zero_90d_not_stagnant_when_30d_positive(self):
        # commits_30d=5 > 0, commits_90d=0 → avg_30d=0; 5 > 0*1.5=0 → ACCELERATING
        self.assertEqual(_velocity_trend(5, 0), "ACCELERATING")

    def test_boundary_accelerating(self):
        # avg=10; threshold=15; 16>15 → ACCELERATING
        self.assertEqual(_velocity_trend(16, 30), "ACCELERATING")

    def test_boundary_not_accelerating(self):
        # avg=10; threshold=15; 15 not > 15 → not ACCELERATING; 15 not < 5 → STABLE
        self.assertEqual(_velocity_trend(15, 30), "STABLE")

    def test_boundary_decelerating(self):
        # avg=10; 0.5*10=5; 4<5 → DECELERATING (and commits_last_90d>0)
        self.assertEqual(_velocity_trend(4, 30), "DECELERATING")


# ---------------------------------------------------------------------------
# _issue_resolution_rate
# ---------------------------------------------------------------------------

class TestIssueResolutionRate(unittest.TestCase):

    def test_no_open_issues_returns_1(self):
        self.assertAlmostEqual(_issue_resolution_rate(0, 0), 1.0)

    def test_all_closed(self):
        self.assertAlmostEqual(_issue_resolution_rate(10, 10), 1.0)

    def test_partial_closure(self):
        self.assertAlmostEqual(_issue_resolution_rate(5, 10), 0.5)

    def test_zero_closed(self):
        self.assertAlmostEqual(_issue_resolution_rate(0, 10), 0.0)

    def test_more_closed_than_open(self):
        self.assertAlmostEqual(_issue_resolution_rate(20, 10), 2.0)


# ---------------------------------------------------------------------------
# analyze() — top-level
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):

    def test_empty_returns_nones(self):
        result = analyze([])
        self.assertIsNone(result["most_active"])
        self.assertIsNone(result["least_active"])
        self.assertEqual(result["inactive_protocols"], [])
        self.assertEqual(result["average_activity_score"], 0.0)
        self.assertEqual(result["protocols"], [])

    def test_timestamp_present(self):
        result = analyze([])
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)


class TestAnalyzeSingleActive(unittest.TestCase):

    def setUp(self):
        proto = make_protocol(
            name="Aave",
            commits_last_30d=60,
            commits_last_90d=180,
            active_contributors_30d=15,
            total_contributors=50,
            days_since_last_commit=1,
            days_since_last_release=10,
            has_bug_bounty=True,
            bug_bounty_usd=2_000_000,
        )
        self.result = analyze([proto])
        self.proto_out = self.result["protocols"][0]

    def test_name_preserved(self):
        self.assertEqual(self.proto_out["name"], "Aave")

    def test_activity_score_bounded(self):
        self.assertGreaterEqual(self.proto_out["activity_score"], 0)
        self.assertLessEqual(self.proto_out["activity_score"], 100)

    def test_activity_level_very_active(self):
        self.assertEqual(self.proto_out["activity_level"], "VERY_ACTIVE")

    def test_commit_momentum_max(self):
        self.assertEqual(self.proto_out["commit_momentum_score"], 30)

    def test_security_investment_max(self):
        self.assertEqual(self.proto_out["security_investment_score"], 20)

    def test_most_active_is_aave(self):
        self.assertEqual(self.result["most_active"], "Aave")

    def test_least_active_is_aave(self):
        self.assertEqual(self.result["least_active"], "Aave")

    def test_not_in_inactive(self):
        self.assertNotIn("Aave", self.result["inactive_protocols"])

    def test_summary_mentions_contributors(self):
        self.assertIn("15", self.proto_out["summary"])

    def test_velocity_trend_stable(self):
        # 60 vs 180/3=60 → 60 not > 90, not < 30 → STABLE
        self.assertEqual(self.proto_out["velocity_trend"], "STABLE")


class TestAnalyzeSingleInactive(unittest.TestCase):

    def setUp(self):
        proto = make_protocol(
            name="DeadProtocol",
            commits_last_30d=0,
            commits_last_90d=0,
            active_contributors_30d=0,
            total_contributors=3,
            open_issues=200,
            closed_issues_30d=0,
            days_since_last_commit=500,
            days_since_last_release=700,
            has_bug_bounty=False,
            bug_bounty_usd=0.0,
        )
        self.result = analyze([proto])
        self.proto_out = self.result["protocols"][0]

    def test_activity_level_inactive(self):
        self.assertEqual(self.proto_out["activity_level"], "INACTIVE")

    def test_in_inactive_protocols(self):
        self.assertIn("DeadProtocol", self.result["inactive_protocols"])

    def test_velocity_trend_stagnant(self):
        self.assertEqual(self.proto_out["velocity_trend"], "STAGNANT")

    def test_issue_resolution_rate_zero(self):
        self.assertAlmostEqual(self.proto_out["issue_resolution_rate"], 0.0)

    def test_security_score_zero(self):
        self.assertEqual(self.proto_out["security_investment_score"], 0)

    def test_summary_mentions_days_since_commit(self):
        self.assertIn("500", self.proto_out["summary"])


class TestAnalyzeMultiple(unittest.TestCase):

    def setUp(self):
        active = make_protocol(
            name="ActiveProto",
            commits_last_30d=55,
            commits_last_90d=165,
            active_contributors_30d=12,
            total_contributors=40,
            days_since_last_commit=1,
            days_since_last_release=5,
            has_bug_bounty=True,
            bug_bounty_usd=1_500_000,
        )
        inactive = make_protocol(
            name="InactiveProto",
            commits_last_30d=0,
            commits_last_90d=1,
            active_contributors_30d=0,
            total_contributors=2,
            open_issues=50,
            closed_issues_30d=0,
            days_since_last_commit=400,
            days_since_last_release=600,
            has_bug_bounty=False,
            bug_bounty_usd=0.0,
        )
        self.result = analyze([active, inactive])

    def test_most_active(self):
        self.assertEqual(self.result["most_active"], "ActiveProto")

    def test_least_active(self):
        self.assertEqual(self.result["least_active"], "InactiveProto")

    def test_inactive_in_list(self):
        self.assertIn("InactiveProto", self.result["inactive_protocols"])

    def test_active_not_inactive(self):
        self.assertNotIn("ActiveProto", self.result["inactive_protocols"])

    def test_two_protocols_in_output(self):
        self.assertEqual(len(self.result["protocols"]), 2)

    def test_average_score(self):
        protos = self.result["protocols"]
        expected = sum(p["activity_score"] for p in protos) / 2
        self.assertAlmostEqual(self.result["average_activity_score"], expected, places=5)


class TestOutputKeys(unittest.TestCase):

    def test_top_level_keys(self):
        result = analyze([make_protocol()])
        expected = {
            "protocols", "most_active", "least_active",
            "inactive_protocols", "average_activity_score", "timestamp"
        }
        self.assertEqual(set(result.keys()), expected)

    def test_protocol_keys(self):
        result = analyze([make_protocol()])
        proto = result["protocols"][0]
        expected = {
            "name", "activity_score", "activity_level",
            "commit_momentum_score", "team_health_score",
            "maintenance_score", "security_investment_score",
            "velocity_trend", "issue_resolution_rate", "summary",
        }
        self.assertEqual(set(proto.keys()), expected)


class TestAcceleratingDecelerating(unittest.TestCase):

    def test_accelerating_velocity(self):
        proto = make_protocol(
            name="FastGrowing",
            commits_last_30d=50,
            commits_last_90d=60,  # avg=20; 50 > 30 → ACCELERATING
        )
        result = analyze([proto])
        self.assertEqual(result["protocols"][0]["velocity_trend"], "ACCELERATING")

    def test_decelerating_velocity(self):
        proto = make_protocol(
            name="SlowingDown",
            commits_last_30d=5,
            commits_last_90d=90,  # avg=30; 30*0.5=15; 5<15 → DECELERATING
        )
        result = analyze([proto])
        self.assertEqual(result["protocols"][0]["velocity_trend"], "DECELERATING")


class TestIssueResolutionInAnalyze(unittest.TestCase):

    def test_resolution_rate_zero_open(self):
        proto = make_protocol(open_issues=0, closed_issues_30d=5)
        result = analyze([proto])
        self.assertAlmostEqual(result["protocols"][0]["issue_resolution_rate"], 1.0)

    def test_resolution_rate_half(self):
        proto = make_protocol(open_issues=20, closed_issues_30d=10)
        result = analyze([proto])
        self.assertAlmostEqual(result["protocols"][0]["issue_resolution_rate"], 0.5)


class TestDataFileRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run_with_tmp_path(self, n_runs: int):
        import spa_core.analytics.protocol_developer_activity_tracker as mod
        tmp_path = Path(self.tmpdir.name) / "data" / "developer_activity_log.json"
        old = mod.DATA_FILE
        mod.DATA_FILE = tmp_path
        try:
            proto = make_protocol()
            for _ in range(n_runs):
                analyze([proto])
        finally:
            mod.DATA_FILE = old
        return tmp_path

    def test_log_file_created(self):
        path = self._run_with_tmp_path(1)
        self.assertTrue(path.exists())

    def test_log_is_list(self):
        path = self._run_with_tmp_path(1)
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_grows(self):
        path = self._run_with_tmp_path(5)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_caps_at_100(self):
        path = self._run_with_tmp_path(110)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_log_entry_has_timestamp(self):
        path = self._run_with_tmp_path(1)
        with open(path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])


if __name__ == "__main__":
    unittest.main()
