"""
MP-894 ProtocolCommunitySentimentScorer — unit tests (≥65).
Run: python3 -m unittest spa_core.tests.test_protocol_community_sentiment_scorer -v
"""

import json
import os
import sys
import tempfile
import time
import unittest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.protocol_community_sentiment_scorer import (
    analyze,
    _governance_health_score,
    _social_presence_score,
    _developer_activity_score,
    _community_investment_score,
    _security_trust_score,
    _composite_score,
    _sentiment_label,
    _build_flags,
    _recommendation,
    _append_log,
)

# ─── fixture helpers ─────────────────────────────────────────────────────────

def _proto(
    name="Aave",
    proposals=5,
    voter_pct=12.0,
    discord=3000,
    followers=250_000,
    engagement=1.5,
    commits=80,
    bugs=3,
    grants=500_000.0,
    days_exploit=9999,
):
    return {
        "name": name,
        "governance_proposals_90d": proposals,
        "governance_voter_participation_pct": voter_pct,
        "discord_active_members_30d": discord,
        "twitter_followers": followers,
        "twitter_engagement_rate_pct": engagement,
        "github_commits_30d": commits,
        "bug_reports_open": bugs,
        "community_grants_usd": grants,
        "days_since_exploit": days_exploit,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. _governance_health_score
# ═══════════════════════════════════════════════════════════════════════════════

class TestGovernanceHealthScore(unittest.TestCase):
    def test_zero_input(self):
        self.assertEqual(_governance_health_score(0, 0.0), 0)

    def test_one_proposal_no_voter(self):
        self.assertEqual(_governance_health_score(1, 0.0), 15)

    def test_two_proposals_ten_pct(self):
        # 2*15 + 10*2 = 50
        self.assertEqual(_governance_health_score(2, 10.0), 50)

    def test_capped_at_100(self):
        self.assertEqual(_governance_health_score(10, 50.0), 100)

    def test_only_voter_pct(self):
        # 0*15 + 50*2 = 100
        self.assertEqual(_governance_health_score(0, 50.0), 100)

    def test_fractional_voter_pct(self):
        # 1*15 + 2.5*2 = 20
        self.assertEqual(_governance_health_score(1, 2.5), 20)

    def test_large_proposals_capped(self):
        self.assertLessEqual(_governance_health_score(100, 100.0), 100)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. _social_presence_score
# ═══════════════════════════════════════════════════════════════════════════════

class TestSocialPresenceScore(unittest.TestCase):
    def test_zero_inputs(self):
        self.assertEqual(_social_presence_score(0, 0.0), 0)

    def test_twitter_score_50_at_500k(self):
        # int(500_000/10_000)=50, engagement=0 → total=50
        self.assertEqual(_social_presence_score(500_000, 0.0), 50)

    def test_twitter_score_capped_above_500k(self):
        self.assertEqual(_social_presence_score(1_000_000, 0.0), 50)

    def test_engagement_score_50_at_5pct(self):
        # followers=0, int(5.0*10)=50
        self.assertEqual(_social_presence_score(0, 5.0), 50)

    def test_engagement_score_capped_above_5pct(self):
        self.assertEqual(_social_presence_score(0, 10.0), 50)

    def test_max_score_100(self):
        self.assertEqual(_social_presence_score(1_000_000, 10.0), 100)

    def test_moderate_followers_partial(self):
        # int(100_000/10_000)=10; int(1.5*10)=15 → 25
        self.assertEqual(_social_presence_score(100_000, 1.5), 25)

    def test_250k_followers(self):
        # int(250_000/10_000)=25
        self.assertEqual(_social_presence_score(250_000, 0.0), 25)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _developer_activity_score
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeveloperActivityScore(unittest.TestCase):
    def test_zero_commits(self):
        self.assertEqual(_developer_activity_score(0), 0)

    def test_one_commit(self):
        self.assertEqual(_developer_activity_score(1), 3)

    def test_10_commits(self):
        self.assertEqual(_developer_activity_score(10), 30)

    def test_33_commits_capped(self):
        # 33*3=99
        self.assertEqual(_developer_activity_score(33), 99)

    def test_34_commits(self):
        self.assertEqual(_developer_activity_score(34), 100)

    def test_100_commits_capped(self):
        self.assertEqual(_developer_activity_score(100), 100)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _community_investment_score
# ═══════════════════════════════════════════════════════════════════════════════

class TestCommunityInvestmentScore(unittest.TestCase):
    def test_zero_grants(self):
        self.assertEqual(_community_investment_score(0.0), 0)

    def test_100k_grants(self):
        # int(100_000/100_000*10) = 10
        self.assertEqual(_community_investment_score(100_000.0), 10)

    def test_500k_grants(self):
        self.assertEqual(_community_investment_score(500_000.0), 50)

    def test_1M_grants_max(self):
        self.assertEqual(_community_investment_score(1_000_000.0), 100)

    def test_above_1M_capped(self):
        self.assertEqual(_community_investment_score(2_000_000.0), 100)

    def test_partial_50k(self):
        # int(50_000/100_000*10) = int(5.0) = 5
        self.assertEqual(_community_investment_score(50_000.0), 5)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _security_trust_score
# ═══════════════════════════════════════════════════════════════════════════════

class TestSecurityTrustScore(unittest.TestCase):
    def test_never_exploited_9999(self):
        self.assertEqual(_security_trust_score(9999), 100)

    def test_never_exploited_above_9999(self):
        self.assertEqual(_security_trust_score(10000), 100)

    def test_366_days(self):
        self.assertEqual(_security_trust_score(366), 50)

    def test_exactly_365_days(self):
        # >365 → not; >90 → 20
        self.assertEqual(_security_trust_score(365), 20)

    def test_91_days(self):
        self.assertEqual(_security_trust_score(91), 20)

    def test_90_days(self):
        # >90 not true (90==90); <=90 → 0
        self.assertEqual(_security_trust_score(90), 0)

    def test_60_days(self):
        self.assertEqual(_security_trust_score(60), 0)

    def test_0_days(self):
        self.assertEqual(_security_trust_score(0), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. _composite_score
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompositeScore(unittest.TestCase):
    def test_all_100(self):
        self.assertEqual(_composite_score(100, 100, 100, 100, 100), 100)

    def test_all_zero(self):
        self.assertEqual(_composite_score(0, 0, 0, 0, 0), 0)

    def test_weights_correct(self):
        # gov=100, rest=0 → 100*0.25=25
        self.assertEqual(_composite_score(100, 0, 0, 0, 0), 25)

    def test_social_weight(self):
        # social=100, rest=0 → 100*0.20=20
        self.assertEqual(_composite_score(0, 100, 0, 0, 0), 20)

    def test_dev_weight(self):
        # dev=100 → 25
        self.assertEqual(_composite_score(0, 0, 100, 0, 0), 25)

    def test_invest_weight(self):
        # invest=100 → 15
        self.assertEqual(_composite_score(0, 0, 0, 100, 0), 15)

    def test_security_weight(self):
        # sec=100 → 15
        self.assertEqual(_composite_score(0, 0, 0, 0, 100), 15)

    def test_clamped_at_100(self):
        self.assertLessEqual(_composite_score(100, 100, 100, 100, 100), 100)

    def test_non_negative(self):
        self.assertGreaterEqual(_composite_score(0, 0, 0, 0, 0), 0)

    def test_returns_int(self):
        self.assertIsInstance(_composite_score(50, 50, 50, 50, 50), int)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. _sentiment_label
# ═══════════════════════════════════════════════════════════════════════════════

class TestSentimentLabel(unittest.TestCase):
    def test_thriving_at_80(self):
        self.assertEqual(_sentiment_label(80), "THRIVING")

    def test_thriving_at_100(self):
        self.assertEqual(_sentiment_label(100), "THRIVING")

    def test_healthy_at_65(self):
        self.assertEqual(_sentiment_label(65), "HEALTHY")

    def test_healthy_at_79(self):
        self.assertEqual(_sentiment_label(79), "HEALTHY")

    def test_stable_at_50(self):
        self.assertEqual(_sentiment_label(50), "STABLE")

    def test_stable_at_64(self):
        self.assertEqual(_sentiment_label(64), "STABLE")

    def test_declining_at_35(self):
        self.assertEqual(_sentiment_label(35), "DECLINING")

    def test_declining_at_49(self):
        self.assertEqual(_sentiment_label(49), "DECLINING")

    def test_at_risk_at_34(self):
        self.assertEqual(_sentiment_label(34), "AT_RISK")

    def test_at_risk_at_0(self):
        self.assertEqual(_sentiment_label(0), "AT_RISK")


# ═══════════════════════════════════════════════════════════════════════════════
# 8. _build_flags
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildFlags(unittest.TestCase):
    def test_no_flags_healthy(self):
        flags = _build_flags(5, 1.0, 30, 9999, 0.0)
        self.assertEqual(flags, [])

    def test_inactive_governance(self):
        flags = _build_flags(1, 1.0, 30, 9999, 0.0)
        self.assertIn("INACTIVE_GOVERNANCE", flags)

    def test_inactive_governance_at_zero(self):
        flags = _build_flags(0, 1.0, 30, 9999, 0.0)
        self.assertIn("INACTIVE_GOVERNANCE", flags)

    def test_no_inactive_governance_at_2(self):
        flags = _build_flags(2, 1.0, 30, 9999, 0.0)
        self.assertNotIn("INACTIVE_GOVERNANCE", flags)

    def test_low_engagement(self):
        flags = _build_flags(5, 0.4, 30, 9999, 0.0)
        self.assertIn("LOW_ENGAGEMENT", flags)

    def test_low_engagement_boundary_not_flagged(self):
        flags = _build_flags(5, 0.5, 30, 9999, 0.0)
        self.assertNotIn("LOW_ENGAGEMENT", flags)

    def test_no_development(self):
        flags = _build_flags(5, 1.0, 0, 9999, 0.0)
        self.assertIn("NO_DEVELOPMENT", flags)

    def test_no_flag_with_1_commit(self):
        flags = _build_flags(5, 1.0, 1, 9999, 0.0)
        self.assertNotIn("NO_DEVELOPMENT", flags)

    def test_recent_exploit_below_365(self):
        flags = _build_flags(5, 1.0, 30, 300, 0.0)
        self.assertIn("RECENT_EXPLOIT", flags)

    def test_no_recent_exploit_at_365(self):
        flags = _build_flags(5, 1.0, 30, 365, 0.0)
        self.assertNotIn("RECENT_EXPLOIT", flags)

    def test_grant_funded_positive_grants(self):
        flags = _build_flags(5, 1.0, 30, 9999, 100.0)
        self.assertIn("GRANT_FUNDED", flags)

    def test_no_grant_funded_at_zero(self):
        flags = _build_flags(5, 1.0, 30, 9999, 0.0)
        self.assertNotIn("GRANT_FUNDED", flags)

    def test_all_flags(self):
        flags = _build_flags(0, 0.1, 0, 30, 100_000.0)
        self.assertIn("INACTIVE_GOVERNANCE", flags)
        self.assertIn("LOW_ENGAGEMENT", flags)
        self.assertIn("NO_DEVELOPMENT", flags)
        self.assertIn("RECENT_EXPLOIT", flags)
        self.assertIn("GRANT_FUNDED", flags)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. _recommendation strings
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecommendation(unittest.TestCase):
    def test_thriving_mentions_commits(self):
        r = _recommendation("THRIVING", 80, 12.0, 90, 5, 1.5, [])
        self.assertIn("80", r)
        self.assertIn("12", r)

    def test_healthy_mentions_score(self):
        r = _recommendation("HEALTHY", 30, 10.0, 70, 4, 1.0, [])
        self.assertIn("70", r)
        self.assertIn("4", r)

    def test_stable_mentions_engagement(self):
        r = _recommendation("STABLE", 20, 5.0, 55, 3, 0.8, [])
        self.assertIn("0.8", r)

    def test_declining_mentions_flags(self):
        flags = ["INACTIVE_GOVERNANCE", "LOW_ENGAGEMENT"]
        r = _recommendation("DECLINING", 0, 0.0, 40, 1, 0.2, flags)
        self.assertIn("INACTIVE_GOVERNANCE", r)

    def test_declining_no_flags_fallback(self):
        r = _recommendation("DECLINING", 0, 0.0, 40, 1, 0.2, [])
        self.assertIn("low engagement", r)

    def test_at_risk_mentions_flag_count(self):
        flags = ["A", "B", "C"]
        r = _recommendation("AT_RISK", 0, 0.0, 10, 0, 0.0, flags)
        self.assertIn("3", r)
        self.assertIn("red flags", r)

    def test_at_risk_zero_flags(self):
        r = _recommendation("AT_RISK", 0, 0.0, 10, 0, 0.0, [])
        self.assertIn("0", r)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. analyze() – empty
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyzeEmpty(unittest.TestCase):
    def test_empty_list(self):
        r = analyze([])
        self.assertEqual(r["protocols"], [])
        self.assertIsNone(r["most_vibrant"])
        self.assertEqual(r["average_composite_score"], 0.0)
        self.assertEqual(r["thriving_count"], 0)
        self.assertIn("timestamp", r)

    def test_timestamp_range(self):
        before = time.time()
        r = analyze([])
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. analyze() – single protocol
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyzeSingle(unittest.TestCase):
    def setUp(self):
        self.r = analyze([_proto()])

    def test_one_protocol(self):
        self.assertEqual(len(self.r["protocols"]), 1)

    def test_most_vibrant_set(self):
        self.assertEqual(self.r["most_vibrant"], "Aave")

    def test_thriving_count_if_high_score(self):
        p = self.r["protocols"][0]
        expected = 1 if p["sentiment_label"] == "THRIVING" else 0
        self.assertEqual(self.r["thriving_count"], expected)

    def test_average_equals_single(self):
        p = self.r["protocols"][0]
        self.assertAlmostEqual(self.r["average_composite_score"], p["composite_score"])

    def test_output_keys(self):
        p = self.r["protocols"][0]
        for k in (
            "name", "governance_health_score", "social_presence_score",
            "developer_activity_score", "community_investment_score",
            "security_trust_score", "composite_score", "sentiment_label",
            "flags", "recommendation",
        ):
            self.assertIn(k, p)

    def test_security_never_exploited(self):
        self.assertEqual(self.r["protocols"][0]["security_trust_score"], 100)

    def test_grant_funded_flag(self):
        self.assertIn("GRANT_FUNDED", self.r["protocols"][0]["flags"])

    def test_no_inactive_governance(self):
        self.assertNotIn("INACTIVE_GOVERNANCE", self.r["protocols"][0]["flags"])

    def test_composite_int(self):
        self.assertIsInstance(self.r["protocols"][0]["composite_score"], int)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. analyze() – all zeros
# ═══════════════════════════════════════════════════════════════════════════════

class TestAllZeros(unittest.TestCase):
    def setUp(self):
        self.r = analyze([_proto(
            proposals=0, voter_pct=0.0, discord=0,
            followers=0, engagement=0.0, commits=0, bugs=0,
            grants=0.0, days_exploit=9999,
        )])

    def test_governance_zero(self):
        self.assertEqual(self.r["protocols"][0]["governance_health_score"], 0)

    def test_social_zero(self):
        self.assertEqual(self.r["protocols"][0]["social_presence_score"], 0)

    def test_dev_zero(self):
        self.assertEqual(self.r["protocols"][0]["developer_activity_score"], 0)

    def test_invest_zero(self):
        self.assertEqual(self.r["protocols"][0]["community_investment_score"], 0)

    def test_security_100_never_exploited(self):
        self.assertEqual(self.r["protocols"][0]["security_trust_score"], 100)

    def test_composite_15_security_only(self):
        # 0+0+0+0 + 100*0.15 = 15
        self.assertEqual(self.r["protocols"][0]["composite_score"], 15)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. analyze() – multiple protocols, aggregates
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyzeMulti(unittest.TestCase):
    def setUp(self):
        self.r = analyze([
            _proto("Aave", proposals=6, commits=100, grants=1_000_000),
            _proto("NewCo", proposals=0, commits=0, grants=0, days_exploit=30,
                   followers=1000, engagement=0.1),
            _proto("MidProto", proposals=3, commits=20, grants=200_000),
        ])

    def test_three_protocols(self):
        self.assertEqual(len(self.r["protocols"]), 3)

    def test_most_vibrant_is_aave(self):
        self.assertEqual(self.r["most_vibrant"], "Aave")

    def test_average_is_mean(self):
        scores = [p["composite_score"] for p in self.r["protocols"]]
        expected = sum(scores) / 3
        self.assertAlmostEqual(self.r["average_composite_score"], expected)

    def test_newco_at_risk(self):
        newco = next(p for p in self.r["protocols"] if p["name"] == "NewCo")
        self.assertIn(newco["sentiment_label"], ("AT_RISK", "DECLINING"))

    def test_newco_has_recent_exploit(self):
        newco = next(p for p in self.r["protocols"] if p["name"] == "NewCo")
        self.assertIn("RECENT_EXPLOIT", newco["flags"])


# ═══════════════════════════════════════════════════════════════════════════════
# 14. _append_log ring-buffer
# ═══════════════════════════════════════════════════════════════════════════════

class TestAppendLog(unittest.TestCase):
    def _tmp(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)
        return path

    def test_creates_file(self):
        path = self._tmp()
        _append_log({"x": 1}, log_path=path)
        self.assertTrue(os.path.exists(path))

    def test_first_entry(self):
        path = self._tmp()
        _append_log({"v": 99}, log_path=path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["v"], 99)

    def test_ring_buffer_cap_100(self):
        path = self._tmp()
        for i in range(110):
            _append_log({"i": i}, log_path=path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)
        self.assertEqual(data[-1]["i"], 109)

    def test_invalid_json_recovers(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("GARBAGE")
        _append_log({"ok": True}, log_path=path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_multiple_entries(self):
        path = self._tmp()
        _append_log({"a": 1}, log_path=path)
        _append_log({"b": 2}, log_path=path)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Output structure completeness
# ═══════════════════════════════════════════════════════════════════════════════

class TestOutputStructure(unittest.TestCase):
    def test_top_level_keys(self):
        r = analyze([_proto()])
        for k in ("protocols", "most_vibrant", "average_composite_score",
                   "thriving_count", "timestamp"):
            self.assertIn(k, r)

    def test_protocol_score_bounds(self):
        r = analyze([_proto()])
        p = r["protocols"][0]
        for k in ("governance_health_score", "social_presence_score",
                   "developer_activity_score", "community_investment_score",
                   "security_trust_score", "composite_score"):
            self.assertGreaterEqual(p[k], 0)
            self.assertLessEqual(p[k], 100)

    def test_recommendation_is_string(self):
        r = analyze([_proto()])
        self.assertIsInstance(r["protocols"][0]["recommendation"], str)

    def test_flags_is_list(self):
        r = analyze([_proto()])
        self.assertIsInstance(r["protocols"][0]["flags"], list)

    def test_sentiment_label_valid(self):
        valid = {"THRIVING", "HEALTHY", "STABLE", "DECLINING", "AT_RISK"}
        r = analyze([_proto()])
        self.assertIn(r["protocols"][0]["sentiment_label"], valid)


# ═══════════════════════════════════════════════════════════════════════════════
# 16. Thriving count
# ═══════════════════════════════════════════════════════════════════════════════

class TestThrivingCount(unittest.TestCase):
    def test_none_thriving(self):
        r = analyze([_proto(proposals=0, commits=0, grants=0, followers=0)])
        if r["protocols"][0]["sentiment_label"] != "THRIVING":
            self.assertEqual(r["thriving_count"], 0)

    def test_all_thriving(self):
        protos = [
            _proto("P1", proposals=6, commits=34, grants=1_000_000,
                   followers=500_000, engagement=5.0, voter_pct=50.0),
            _proto("P2", proposals=6, commits=34, grants=1_000_000,
                   followers=500_000, engagement=5.0, voter_pct=50.0),
        ]
        r = analyze(protos)
        self.assertEqual(r["thriving_count"], 2)

    def test_config_none_allowed(self):
        r = analyze([_proto()], config=None)
        self.assertIn("protocols", r)


# ═══════════════════════════════════════════════════════════════════════════════
# 17. Edge: security trust = 50 for >365 days
# ═══════════════════════════════════════════════════════════════════════════════

class TestSecurityEdges(unittest.TestCase):
    def test_366_days_score_50(self):
        r = analyze([_proto(days_exploit=366)])
        self.assertEqual(r["protocols"][0]["security_trust_score"], 50)

    def test_exactly_365_days_score_20(self):
        r = analyze([_proto(days_exploit=365)])
        self.assertEqual(r["protocols"][0]["security_trust_score"], 20)

    def test_91_days_score_20(self):
        r = analyze([_proto(days_exploit=91)])
        self.assertEqual(r["protocols"][0]["security_trust_score"], 20)

    def test_90_days_score_0(self):
        r = analyze([_proto(days_exploit=90)])
        self.assertEqual(r["protocols"][0]["security_trust_score"], 0)

    def test_0_days_score_0(self):
        r = analyze([_proto(days_exploit=0)])
        self.assertEqual(r["protocols"][0]["security_trust_score"], 0)

    def test_recent_exploit_flagged_below_365(self):
        r = analyze([_proto(days_exploit=200)])
        self.assertIn("RECENT_EXPLOIT", r["protocols"][0]["flags"])

    def test_recent_exploit_not_flagged_at_365(self):
        r = analyze([_proto(days_exploit=365)])
        self.assertNotIn("RECENT_EXPLOIT", r["protocols"][0]["flags"])


if __name__ == "__main__":
    unittest.main()
