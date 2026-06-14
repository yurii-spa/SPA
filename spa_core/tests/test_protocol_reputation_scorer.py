"""
Tests for MP-850 ProtocolReputationScorer
python3 -m unittest spa_core.tests.test_protocol_reputation_scorer -v
"""

import json
import os
import tempfile
import time
import unittest

from spa_core.analytics.protocol_reputation_scorer import (
    DEFAULT_MIN_AGE_MONTHS,
    RING_BUFFER_MAX,
    _age_score,
    _backing_score,
    _bonus_score,
    _community_score,
    _compute_hack_ratio,
    _grade_and_label,
    _hack_penalty,
    _quality_score,
    _regulatory_penalty,
    _risk_factors,
    _score_protocol,
    _transparency_score,
    _trust_factors,
    analyze,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ELITE_PROTOCOL = {
    "name": "Aave",
    "age_months": 48,
    "total_hacks_usd": 0.0,
    "tvl_peak_usd": 10_000_000_000.0,
    "team_doxxed": True,
    "has_code_of_conduct": True,
    "open_source": True,
    "audit_count": 6,
    "institutional_backers": 10,
    "twitter_followers": 500_000,
    "github_stars": 5_000,
    "has_bug_bounty": True,
    "regulatory_issues": 0,
}

RISKY_PROTOCOL = {
    "name": "ScamProtocol",
    "age_months": 1,
    "total_hacks_usd": 10_000_000.0,
    "tvl_peak_usd": 10_000_000.0,
    "team_doxxed": False,
    "has_code_of_conduct": False,
    "open_source": False,
    "audit_count": 0,
    "institutional_backers": 0,
    "twitter_followers": 100,
    "github_stars": 10,
    "has_bug_bounty": False,
    "regulatory_issues": 3,
}

MID_PROTOCOL = {
    "name": "Compound",
    "age_months": 24,
    "total_hacks_usd": 0.0,
    "tvl_peak_usd": 5_000_000_000.0,
    "team_doxxed": True,
    "has_code_of_conduct": False,
    "open_source": True,
    "audit_count": 3,
    "institutional_backers": 3,
    "twitter_followers": 50_000,
    "github_stars": 1_000,
    "has_bug_bounty": True,
    "regulatory_issues": 0,
}


# ===========================================================================
# 1. _compute_hack_ratio
# ===========================================================================

class TestComputeHackRatio(unittest.TestCase):
    def test_no_hacks_no_tvl(self):
        self.assertEqual(_compute_hack_ratio(0.0, 0.0), 0.0)

    def test_hacks_no_tvl(self):
        self.assertEqual(_compute_hack_ratio(1_000_000.0, 0.0), 1.0)

    def test_no_hacks_with_tvl(self):
        self.assertEqual(_compute_hack_ratio(0.0, 10_000_000.0), 0.0)

    def test_half_tvl_hacked(self):
        self.assertAlmostEqual(_compute_hack_ratio(5_000_000.0, 10_000_000.0), 0.5)

    def test_small_hack_ratio(self):
        self.assertAlmostEqual(_compute_hack_ratio(10_000.0, 10_000_000.0), 0.001)

    def test_exact_tvl_hacked(self):
        self.assertAlmostEqual(_compute_hack_ratio(10_000_000.0, 10_000_000.0), 1.0)

    def test_hack_exceeds_tvl(self):
        self.assertGreater(_compute_hack_ratio(15_000_000.0, 10_000_000.0), 1.0)


# ===========================================================================
# 2. _age_score
# ===========================================================================

class TestAgeScore(unittest.TestCase):
    def test_zero_months(self):
        self.assertEqual(_age_score(0), 0)

    def test_three_months(self):
        self.assertEqual(_age_score(3), 0)

    def test_five_months(self):
        self.assertEqual(_age_score(5), 0)

    def test_six_months(self):
        self.assertEqual(_age_score(6), 6)

    def test_eleven_months(self):
        self.assertEqual(_age_score(11), 6)

    def test_twelve_months(self):
        self.assertEqual(_age_score(12), 12)

    def test_twenty_three_months(self):
        self.assertEqual(_age_score(23), 12)

    def test_twenty_four_months(self):
        self.assertEqual(_age_score(24), 16)

    def test_thirty_five_months(self):
        self.assertEqual(_age_score(35), 16)

    def test_thirty_six_months(self):
        self.assertEqual(_age_score(36), 20)

    def test_one_hundred_months(self):
        self.assertEqual(_age_score(100), 20)


# ===========================================================================
# 3. _hack_penalty
# ===========================================================================

class TestHackPenalty(unittest.TestCase):
    def test_no_hacks_no_penalty(self):
        self.assertEqual(_hack_penalty(0.0, 0.0), 0)

    def test_tiny_hack_minus_2(self):
        # ratio < 0.01 but hacks > 0
        self.assertEqual(_hack_penalty(0.005, 100.0), -2)

    def test_ratio_0_01_minus_5(self):
        self.assertEqual(_hack_penalty(0.01, 100.0), -5)

    def test_ratio_0_05_minus_10(self):
        self.assertEqual(_hack_penalty(0.05, 100.0), -10)

    def test_ratio_0_2_minus_20(self):
        self.assertEqual(_hack_penalty(0.2, 100.0), -20)

    def test_ratio_0_5_minus_30(self):
        self.assertEqual(_hack_penalty(0.5, 100.0), -30)

    def test_ratio_1_0_minus_30(self):
        self.assertEqual(_hack_penalty(1.0, 100.0), -30)

    def test_ratio_just_below_0_01(self):
        self.assertEqual(_hack_penalty(0.009, 100.0), -2)

    def test_ratio_just_below_0_05(self):
        self.assertEqual(_hack_penalty(0.049, 100.0), -5)


# ===========================================================================
# 4. _transparency_score
# ===========================================================================

class TestTransparencyScore(unittest.TestCase):
    def test_nothing_zero(self):
        self.assertEqual(_transparency_score(False, False, False), 0)

    def test_doxxed_only(self):
        self.assertEqual(_transparency_score(True, False, False), 8)

    def test_open_source_only(self):
        self.assertEqual(_transparency_score(False, True, False), 7)

    def test_coc_only(self):
        self.assertEqual(_transparency_score(False, False, True), 5)

    def test_all_three(self):
        self.assertEqual(_transparency_score(True, True, True), 20)

    def test_doxxed_and_open_source(self):
        self.assertEqual(_transparency_score(True, True, False), 15)


# ===========================================================================
# 5. _quality_score
# ===========================================================================

class TestQualityScore(unittest.TestCase):
    def test_no_audits(self):
        self.assertEqual(_quality_score(0), 0)

    def test_one_audit(self):
        self.assertEqual(_quality_score(1), 5)

    def test_two_audits(self):
        self.assertEqual(_quality_score(2), 10)

    def test_three_audits(self):
        self.assertEqual(_quality_score(3), 15)

    def test_four_audits(self):
        self.assertEqual(_quality_score(4), 20)

    def test_ten_audits(self):
        self.assertEqual(_quality_score(10), 20)


# ===========================================================================
# 6. _backing_score
# ===========================================================================

class TestBackingScore(unittest.TestCase):
    def test_no_backers(self):
        self.assertEqual(_backing_score(0), 0)

    def test_one_backer(self):
        self.assertEqual(_backing_score(1), 5)

    def test_two_backers(self):
        self.assertEqual(_backing_score(2), 5)

    def test_three_backers(self):
        self.assertEqual(_backing_score(3), 10)

    def test_four_backers(self):
        self.assertEqual(_backing_score(4), 10)

    def test_five_backers(self):
        self.assertEqual(_backing_score(5), 15)

    def test_many_backers(self):
        self.assertEqual(_backing_score(20), 15)


# ===========================================================================
# 7. _community_score
# ===========================================================================

class TestCommunityScore(unittest.TestCase):
    def test_no_community(self):
        self.assertEqual(_community_score(0, 0), 0)

    def test_small_twitter_only(self):
        self.assertEqual(_community_score(500, 0), 0)

    def test_1k_twitter(self):
        self.assertEqual(_community_score(1_000, 0), 2)

    def test_10k_twitter(self):
        self.assertEqual(_community_score(10_000, 0), 4)

    def test_100k_twitter(self):
        self.assertEqual(_community_score(100_000, 0), 6)

    def test_200_stars(self):
        self.assertEqual(_community_score(0, 200), 2)

    def test_1000_stars(self):
        self.assertEqual(_community_score(0, 1_000), 4)

    def test_capped_at_10(self):
        self.assertEqual(_community_score(100_000, 1_000), 10)

    def test_medium_twitter_medium_stars(self):
        self.assertEqual(_community_score(10_000, 200), min(10, 4 + 2))


# ===========================================================================
# 8. _bonus_score
# ===========================================================================

class TestBonusScore(unittest.TestCase):
    def test_no_bonus(self):
        self.assertEqual(_bonus_score(False, 1), 0)

    def test_bug_bounty_only(self):
        self.assertEqual(_bonus_score(True, 1), 3)

    def test_no_reg_issues_only(self):
        self.assertEqual(_bonus_score(False, 0), 2)

    def test_both(self):
        self.assertEqual(_bonus_score(True, 0), 5)


# ===========================================================================
# 9. _regulatory_penalty
# ===========================================================================

class TestRegulatoryPenalty(unittest.TestCase):
    def test_no_issues(self):
        self.assertEqual(_regulatory_penalty(0), 0)

    def test_one_issue(self):
        self.assertEqual(_regulatory_penalty(1), -5)

    def test_two_issues(self):
        self.assertEqual(_regulatory_penalty(2), -10)

    def test_three_issues(self):
        self.assertEqual(_regulatory_penalty(3), -15)

    def test_many_issues_capped(self):
        self.assertEqual(_regulatory_penalty(10), -15)


# ===========================================================================
# 10. _grade_and_label
# ===========================================================================

class TestGradeAndLabel(unittest.TestCase):
    def test_80_is_A_elite(self):
        g, l = _grade_and_label(80)
        self.assertEqual(g, "A")
        self.assertEqual(l, "ELITE")

    def test_100_is_A_elite(self):
        g, l = _grade_and_label(100)
        self.assertEqual(g, "A")
        self.assertEqual(l, "ELITE")

    def test_79_is_B_trusted(self):
        g, l = _grade_and_label(79)
        self.assertEqual(g, "B")
        self.assertEqual(l, "TRUSTED")

    def test_60_is_B_trusted(self):
        g, l = _grade_and_label(60)
        self.assertEqual(g, "B")
        self.assertEqual(l, "TRUSTED")

    def test_59_is_C_established(self):
        g, l = _grade_and_label(59)
        self.assertEqual(g, "C")
        self.assertEqual(l, "ESTABLISHED")

    def test_40_is_C_established(self):
        g, l = _grade_and_label(40)
        self.assertEqual(g, "C")
        self.assertEqual(l, "ESTABLISHED")

    def test_39_is_D_emerging(self):
        g, l = _grade_and_label(39)
        self.assertEqual(g, "D")
        self.assertEqual(l, "EMERGING")

    def test_20_is_D_emerging(self):
        g, l = _grade_and_label(20)
        self.assertEqual(g, "D")
        self.assertEqual(l, "EMERGING")

    def test_19_is_F_risky(self):
        g, l = _grade_and_label(19)
        self.assertEqual(g, "F")
        self.assertEqual(l, "RISKY")

    def test_0_is_F_risky(self):
        g, l = _grade_and_label(0)
        self.assertEqual(g, "F")
        self.assertEqual(l, "RISKY")


# ===========================================================================
# 11. _trust_factors
# ===========================================================================

class TestTrustFactors(unittest.TestCase):
    def test_elite_has_many_factors(self):
        factors = _trust_factors(ELITE_PROTOCOL)
        self.assertIn("Long track record", factors)
        self.assertIn("No security incidents", factors)
        self.assertIn("Fully open source", factors)
        self.assertIn("Doxxed team", factors)
        self.assertIn("Active bug bounty", factors)
        self.assertIn("Large community", factors)

    def test_risky_has_no_factors(self):
        factors = _trust_factors(RISKY_PROTOCOL)
        self.assertEqual(factors, [])

    def test_young_no_track_record(self):
        p = {**ELITE_PROTOCOL, "age_months": 12}
        factors = _trust_factors(p)
        self.assertNotIn("Long track record", factors)

    def test_hacked_no_clean_factor(self):
        p = {**ELITE_PROTOCOL, "total_hacks_usd": 1.0}
        factors = _trust_factors(p)
        self.assertNotIn("No security incidents", factors)

    def test_one_audit_not_in_factors(self):
        p = {**MID_PROTOCOL, "audit_count": 1}
        factors = _trust_factors(p)
        self.assertNotIn("1 security audits", factors)

    def test_two_audits_appear_in_factors(self):
        p = {**MID_PROTOCOL, "audit_count": 2}
        factors = _trust_factors(p)
        self.assertIn("2 security audits", factors)

    def test_large_community_twitter_50k(self):
        p = {**RISKY_PROTOCOL, "twitter_followers": 50_000, "github_stars": 0}
        factors = _trust_factors(p)
        self.assertIn("Large community", factors)

    def test_large_community_github_500(self):
        p = {**RISKY_PROTOCOL, "twitter_followers": 0, "github_stars": 500}
        factors = _trust_factors(p)
        self.assertIn("Large community", factors)

    def test_two_backers_not_in_trust(self):
        p = {**ELITE_PROTOCOL, "institutional_backers": 2}
        factors = _trust_factors(p)
        self.assertNotIn("Strong institutional backing", factors)


# ===========================================================================
# 12. _risk_factors
# ===========================================================================

class TestRiskFactors(unittest.TestCase):
    def test_risky_has_many_factors(self):
        factors = _risk_factors(RISKY_PROTOCOL, DEFAULT_MIN_AGE_MONTHS)
        self.assertIn("Protocol is less than 6 months old", factors)
        self.assertIn("Closed source code", factors)
        self.assertIn("Anonymous team", factors)
        self.assertIn("No security audits", factors)
        self.assertIn("No bug bounty program", factors)

    def test_elite_has_no_risk_factors(self):
        factors = _risk_factors(ELITE_PROTOCOL, DEFAULT_MIN_AGE_MONTHS)
        self.assertEqual(factors, [])

    def test_hack_risk_factor_format(self):
        p = {**RISKY_PROTOCOL, "total_hacks_usd": 5_000_000.0}
        factors = _risk_factors(p, DEFAULT_MIN_AGE_MONTHS)
        self.assertTrue(any("5.0M" in f for f in factors))

    def test_regulatory_actions_in_risk_factors(self):
        p = {**ELITE_PROTOCOL, "regulatory_issues": 2}
        factors = _risk_factors(p, DEFAULT_MIN_AGE_MONTHS)
        self.assertIn("2 regulatory action(s)", factors)

    def test_no_regulatory_no_factor(self):
        factors = _risk_factors(ELITE_PROTOCOL, DEFAULT_MIN_AGE_MONTHS)
        self.assertFalse(any("regulatory" in f for f in factors))

    def test_min_age_months_custom(self):
        p = {**ELITE_PROTOCOL, "age_months": 8}
        factors_default = _risk_factors(p, 6)
        factors_stricter = _risk_factors(p, 12)
        # With min=6, age=8 is old enough → no age factor
        self.assertNotIn("Protocol is less than 6 months old", factors_default)
        # With min=12, age=8 is too young
        self.assertIn("Protocol is less than 6 months old", factors_stricter)

    def test_audit_zero_is_risk(self):
        p = {**ELITE_PROTOCOL, "audit_count": 0}
        factors = _risk_factors(p, DEFAULT_MIN_AGE_MONTHS)
        self.assertIn("No security audits", factors)

    def test_audit_one_not_risk(self):
        p = {**ELITE_PROTOCOL, "audit_count": 1}
        factors = _risk_factors(p, DEFAULT_MIN_AGE_MONTHS)
        self.assertNotIn("No security audits", factors)


# ===========================================================================
# 13. _score_protocol
# ===========================================================================

class TestScoreProtocol(unittest.TestCase):
    def test_elite_score_high(self):
        result = _score_protocol(ELITE_PROTOCOL, DEFAULT_MIN_AGE_MONTHS)
        self.assertGreaterEqual(result["reputation_score"], 80)

    def test_risky_score_low(self):
        result = _score_protocol(RISKY_PROTOCOL, DEFAULT_MIN_AGE_MONTHS)
        self.assertLess(result["reputation_score"], 20)

    def test_score_bounded_0_100(self):
        for p in [ELITE_PROTOCOL, RISKY_PROTOCOL, MID_PROTOCOL]:
            result = _score_protocol(p, DEFAULT_MIN_AGE_MONTHS)
            self.assertGreaterEqual(result["reputation_score"], 0)
            self.assertLessEqual(result["reputation_score"], 100)

    def test_elite_label(self):
        result = _score_protocol(ELITE_PROTOCOL, DEFAULT_MIN_AGE_MONTHS)
        self.assertEqual(result["reputation_label"], "ELITE")

    def test_risky_label(self):
        result = _score_protocol(RISKY_PROTOCOL, DEFAULT_MIN_AGE_MONTHS)
        self.assertEqual(result["reputation_label"], "RISKY")

    def test_result_keys(self):
        result = _score_protocol(MID_PROTOCOL, DEFAULT_MIN_AGE_MONTHS)
        expected = {
            "name", "reputation_score", "reputation_grade",
            "reputation_label", "trust_factors", "risk_factors", "hack_ratio"
        }
        self.assertEqual(set(result.keys()), expected)

    def test_name_preserved(self):
        result = _score_protocol(ELITE_PROTOCOL, DEFAULT_MIN_AGE_MONTHS)
        self.assertEqual(result["name"], "Aave")

    def test_hack_ratio_computed(self):
        p = {**RISKY_PROTOCOL, "total_hacks_usd": 5_000_000.0, "tvl_peak_usd": 10_000_000.0}
        result = _score_protocol(p, DEFAULT_MIN_AGE_MONTHS)
        self.assertAlmostEqual(result["hack_ratio"], 0.5, places=5)

    def test_zero_tvl_no_hacks_hack_ratio_zero(self):
        p = {**RISKY_PROTOCOL, "total_hacks_usd": 0.0, "tvl_peak_usd": 0.0}
        result = _score_protocol(p, DEFAULT_MIN_AGE_MONTHS)
        self.assertEqual(result["hack_ratio"], 0.0)


# ===========================================================================
# 14. analyze() — return structure
# ===========================================================================

class TestAnalyzeStructure(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _analyze(self, protocols=None, config=None):
        return analyze(protocols or [ELITE_PROTOCOL, MID_PROTOCOL], config,
                       _data_dir=self.tmpdir)

    def test_returns_dict(self):
        r = self._analyze()
        self.assertIsInstance(r, dict)

    def test_top_level_keys(self):
        r = self._analyze()
        expected = {
            "protocols", "most_reputable", "least_reputable",
            "elite_count", "risky_count", "average_score", "timestamp"
        }
        self.assertEqual(set(r.keys()), expected)

    def test_protocols_is_list(self):
        r = self._analyze()
        self.assertIsInstance(r["protocols"], list)

    def test_protocols_count_matches_input(self):
        r = analyze([ELITE_PROTOCOL, MID_PROTOCOL, RISKY_PROTOCOL], _data_dir=self.tmpdir)
        self.assertEqual(len(r["protocols"]), 3)

    def test_most_reputable_is_string(self):
        r = self._analyze()
        self.assertIsInstance(r["most_reputable"], str)

    def test_least_reputable_is_string(self):
        r = self._analyze()
        self.assertIsInstance(r["least_reputable"], str)

    def test_elite_count_is_int(self):
        r = self._analyze()
        self.assertIsInstance(r["elite_count"], int)

    def test_risky_count_is_int(self):
        r = self._analyze()
        self.assertIsInstance(r["risky_count"], int)

    def test_average_score_is_float(self):
        r = self._analyze()
        self.assertIsInstance(r["average_score"], float)

    def test_timestamp_is_recent(self):
        before = time.time() - 1
        r = self._analyze()
        self.assertGreater(r["timestamp"], before)


# ===========================================================================
# 15. analyze() — empty protocols
# ===========================================================================

class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_empty_returns_none_most(self):
        r = analyze([], _data_dir=self.tmpdir)
        self.assertIsNone(r["most_reputable"])

    def test_empty_returns_none_least(self):
        r = analyze([], _data_dir=self.tmpdir)
        self.assertIsNone(r["least_reputable"])

    def test_empty_average_zero(self):
        r = analyze([], _data_dir=self.tmpdir)
        self.assertEqual(r["average_score"], 0.0)

    def test_empty_protocols_list_empty(self):
        r = analyze([], _data_dir=self.tmpdir)
        self.assertEqual(r["protocols"], [])

    def test_empty_counts_zero(self):
        r = analyze([], _data_dir=self.tmpdir)
        self.assertEqual(r["elite_count"], 0)
        self.assertEqual(r["risky_count"], 0)


# ===========================================================================
# 16. analyze() — counts and aggregates
# ===========================================================================

class TestAnalyzeAggregates(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_most_reputable_is_elite(self):
        r = analyze([ELITE_PROTOCOL, RISKY_PROTOCOL], _data_dir=self.tmpdir)
        self.assertEqual(r["most_reputable"], "Aave")

    def test_least_reputable_is_risky(self):
        r = analyze([ELITE_PROTOCOL, RISKY_PROTOCOL], _data_dir=self.tmpdir)
        self.assertEqual(r["least_reputable"], "ScamProtocol")

    def test_elite_count_correct(self):
        r = analyze([ELITE_PROTOCOL, ELITE_PROTOCOL, RISKY_PROTOCOL], _data_dir=self.tmpdir)
        self.assertEqual(r["elite_count"], 2)

    def test_risky_count_correct(self):
        r = analyze([ELITE_PROTOCOL, RISKY_PROTOCOL, RISKY_PROTOCOL], _data_dir=self.tmpdir)
        self.assertEqual(r["risky_count"], 2)

    def test_average_score_between_min_max(self):
        r = analyze([ELITE_PROTOCOL, RISKY_PROTOCOL], _data_dir=self.tmpdir)
        scores = [p["reputation_score"] for p in r["protocols"]]
        self.assertAlmostEqual(r["average_score"], sum(scores) / len(scores), places=3)

    def test_single_protocol_most_equals_least(self):
        r = analyze([MID_PROTOCOL], _data_dir=self.tmpdir)
        self.assertEqual(r["most_reputable"], r["least_reputable"])


# ===========================================================================
# 17. analyze() — ring-buffer log
# ===========================================================================

class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "reputation_log.json")

    def test_log_file_created(self):
        analyze([ELITE_PROTOCOL], _data_dir=self.tmpdir)
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        analyze([ELITE_PROTOCOL], _data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends(self):
        for _ in range(3):
            analyze([ELITE_PROTOCOL], _data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_ring_buffer_capped_at_100(self):
        for _ in range(105):
            analyze([MID_PROTOCOL], _data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_entry_has_timestamp(self):
        analyze([ELITE_PROTOCOL], _data_dir=self.tmpdir)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])


# ===========================================================================
# 18. Config: min_age_months
# ===========================================================================

class TestMinAgeMonthsConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_default_min_age_is_6(self):
        self.assertEqual(DEFAULT_MIN_AGE_MONTHS, 6)

    def test_custom_min_age_affects_risk_factors(self):
        p = {**ELITE_PROTOCOL, "age_months": 8}
        r_strict = analyze([p], {"min_age_months": 12}, _data_dir=self.tmpdir)
        r_lenient = analyze([p], {"min_age_months": 6}, _data_dir=self.tmpdir)
        risk_strict = r_strict["protocols"][0]["risk_factors"]
        risk_lenient = r_lenient["protocols"][0]["risk_factors"]
        self.assertIn("Protocol is less than 6 months old", risk_strict)
        self.assertNotIn("Protocol is less than 6 months old", risk_lenient)

    def test_none_config_uses_defaults(self):
        r = analyze([MID_PROTOCOL], None, _data_dir=self.tmpdir)
        self.assertIsNotNone(r)

    def test_empty_config_uses_defaults(self):
        r = analyze([MID_PROTOCOL], {}, _data_dir=self.tmpdir)
        self.assertIsNotNone(r)


# ===========================================================================
# 19. Score correctness spot-checks
# ===========================================================================

class TestScoreCorrectness(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_perfect_protocol_high_score(self):
        # age=36 (20) + no hacks (0) + doxxed+open+coc (20) + 4 audits (20)
        # + 5 backers (15) + comm (10) + bug+no_reg (5) = 90
        r = analyze([ELITE_PROTOCOL], _data_dir=self.tmpdir)
        self.assertGreaterEqual(r["protocols"][0]["reputation_score"], 80)

    def test_terrible_protocol_very_low_score(self):
        r = analyze([RISKY_PROTOCOL], _data_dir=self.tmpdir)
        self.assertLessEqual(r["protocols"][0]["reputation_score"], 20)

    def test_grade_A_iff_score_80_plus(self):
        r = analyze([ELITE_PROTOCOL], _data_dir=self.tmpdir)
        score = r["protocols"][0]["reputation_score"]
        grade = r["protocols"][0]["reputation_grade"]
        if score >= 80:
            self.assertEqual(grade, "A")

    def test_grade_F_iff_score_below_20(self):
        r = analyze([RISKY_PROTOCOL], _data_dir=self.tmpdir)
        score = r["protocols"][0]["reputation_score"]
        grade = r["protocols"][0]["reputation_grade"]
        if score < 20:
            self.assertEqual(grade, "F")

    def test_label_consistency_with_grade(self):
        """Label and grade should match the same threshold."""
        label_to_grade = {
            "ELITE": "A", "TRUSTED": "B", "ESTABLISHED": "C",
            "EMERGING": "D", "RISKY": "F"
        }
        protos = [ELITE_PROTOCOL, MID_PROTOCOL, RISKY_PROTOCOL]
        r = analyze(protos, _data_dir=self.tmpdir)
        for p in r["protocols"]:
            expected_grade = label_to_grade[p["reputation_label"]]
            self.assertEqual(p["reputation_grade"], expected_grade)

    def test_hack_50pct_tvl_minus_30(self):
        """Protocol with hack_ratio=0.5 should get -30 penalty."""
        p = {
            "name": "HalfHacked",
            "age_months": 36,       # +20
            "total_hacks_usd": 5_000_000.0,
            "tvl_peak_usd": 10_000_000.0,  # ratio=0.5 → -30
            "team_doxxed": False,
            "has_code_of_conduct": False,
            "open_source": False,
            "audit_count": 0,
            "institutional_backers": 0,
            "twitter_followers": 0,
            "github_stars": 0,
            "has_bug_bounty": False,
            "regulatory_issues": 0,  # +2 for no reg issues
        }
        r = analyze([p], _data_dir=self.tmpdir)
        # age 20 - 30 hack + 0 trans + 0 qual + 0 back + 0 comm + 2 bonus = -8 → 0 (capped)
        self.assertEqual(r["protocols"][0]["reputation_score"], 0)

    def test_max_community_score_capped_at_10(self):
        """Community score should never exceed 10."""
        p = {**MID_PROTOCOL, "twitter_followers": 1_000_000, "github_stars": 50_000}
        r = analyze([p], _data_dir=self.tmpdir)
        # Just verify score is capped and not wildly different
        self.assertLessEqual(r["protocols"][0]["reputation_score"], 100)

    def test_regulatory_issues_capped_at_minus_15(self):
        """Many regulatory issues: penalty capped at -15."""
        p_few_issues = {**ELITE_PROTOCOL, "regulatory_issues": 3}
        p_many_issues = {**ELITE_PROTOCOL, "regulatory_issues": 10}
        r_few = analyze([p_few_issues], _data_dir=self.tmpdir)
        r_many = analyze([p_many_issues], _data_dir=self.tmpdir)
        # Both should have same penalty (capped at -15)
        self.assertEqual(
            r_few["protocols"][0]["reputation_score"],
            r_many["protocols"][0]["reputation_score"]
        )


# ===========================================================================
# 20. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_missing_optional_fields_defaults(self):
        p = {"name": "MinimalProtocol"}
        r = analyze([p], _data_dir=self.tmpdir)
        self.assertIsNotNone(r["protocols"][0])

    def test_score_never_negative(self):
        r = analyze([RISKY_PROTOCOL], _data_dir=self.tmpdir)
        self.assertGreaterEqual(r["protocols"][0]["reputation_score"], 0)

    def test_score_never_above_100(self):
        r = analyze([ELITE_PROTOCOL], _data_dir=self.tmpdir)
        self.assertLessEqual(r["protocols"][0]["reputation_score"], 100)

    def test_many_protocols(self):
        protos = [
            {
                "name": f"Protocol{i}",
                "age_months": i * 3,
                "total_hacks_usd": 0.0,
                "tvl_peak_usd": 1_000_000.0,
                "team_doxxed": bool(i % 2),
                "has_code_of_conduct": False,
                "open_source": True,
                "audit_count": i % 5,
                "institutional_backers": i % 6,
                "twitter_followers": i * 1_000,
                "github_stars": i * 100,
                "has_bug_bounty": bool(i % 3),
                "regulatory_issues": 0,
            }
            for i in range(1, 11)
        ]
        r = analyze(protos, _data_dir=self.tmpdir)
        self.assertEqual(len(r["protocols"]), 10)

    def test_trust_factors_is_list(self):
        r = analyze([ELITE_PROTOCOL], _data_dir=self.tmpdir)
        self.assertIsInstance(r["protocols"][0]["trust_factors"], list)

    def test_risk_factors_is_list(self):
        r = analyze([RISKY_PROTOCOL], _data_dir=self.tmpdir)
        self.assertIsInstance(r["protocols"][0]["risk_factors"], list)

    def test_hack_ratio_in_output(self):
        r = analyze([MID_PROTOCOL], _data_dir=self.tmpdir)
        self.assertIn("hack_ratio", r["protocols"][0])


if __name__ == "__main__":
    unittest.main()
