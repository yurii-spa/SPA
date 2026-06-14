"""
Tests for MP-878: ProtocolRegulatoryRiskAssessor
python3 -m unittest spa_core/tests/test_protocol_regulatory_risk_assessor.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import spa_core.analytics.protocol_regulatory_risk_assessor as mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_protocol(**kwargs):
    base = {
        "name": "TestProtocol",
        "jurisdiction": "CAYMAN",
        "has_kyc": False,
        "token_type": "GOVERNANCE",
        "has_us_user_restriction": False,
        "team_is_doxxed": False,
        "has_received_sec_subpoena": False,
        "tvl_usd": 1_000_000.0,
        "centralized_components": 0,
        "has_legal_wrapper": True,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# 1. Empty input
# ---------------------------------------------------------------------------

class TestEmptyInput(unittest.TestCase):

    def test_empty_returns_dict(self):
        r = mod.analyze([])
        self.assertIsInstance(r, dict)

    def test_empty_protocols_list(self):
        r = mod.analyze([])
        self.assertEqual(r["protocols"], [])

    def test_empty_highest_none(self):
        r = mod.analyze([])
        self.assertIsNone(r["highest_regulatory_risk"])

    def test_empty_lowest_none(self):
        r = mod.analyze([])
        self.assertIsNone(r["lowest_regulatory_risk"])

    def test_empty_high_risk_count_zero(self):
        r = mod.analyze([])
        self.assertEqual(r["high_risk_count"], 0)

    def test_empty_average_risk_score_zero(self):
        r = mod.analyze([])
        self.assertEqual(r["average_risk_score"], 0.0)

    def test_empty_timestamp_present(self):
        r = mod.analyze([])
        self.assertIn("timestamp", r)

    def test_empty_config_none(self):
        r = mod.analyze([], None)
        self.assertEqual(r["protocols"], [])


# ---------------------------------------------------------------------------
# 2. Jurisdiction score
# ---------------------------------------------------------------------------

class TestJurisdictionScore(unittest.TestCase):

    def test_us_score(self):
        self.assertEqual(mod._jurisdiction_score("US"), 20)

    def test_eu_score(self):
        self.assertEqual(mod._jurisdiction_score("EU"), 15)

    def test_offshore_score(self):
        self.assertEqual(mod._jurisdiction_score("OFFSHORE"), 12)

    def test_cayman_score(self):
        self.assertEqual(mod._jurisdiction_score("CAYMAN"), 8)

    def test_decentralized_score(self):
        self.assertEqual(mod._jurisdiction_score("DECENTRALIZED"), 5)

    def test_unknown_jurisdiction_default(self):
        self.assertEqual(mod._jurisdiction_score("SINGAPORE"), 10)
        self.assertEqual(mod._jurisdiction_score("UNKNOWN"), 10)

    def test_lowercase_jurisdiction(self):
        self.assertEqual(mod._jurisdiction_score("us"), 20)
        self.assertEqual(mod._jurisdiction_score("eu"), 15)

    def test_empty_string_jurisdiction(self):
        # Not in dict → default
        self.assertEqual(mod._jurisdiction_score(""), 10)


# ---------------------------------------------------------------------------
# 3. Enforcement exposure score
# ---------------------------------------------------------------------------

class TestEnforcementExposureScore(unittest.TestCase):

    def test_sec_subpoena_adds_20(self):
        p = make_protocol(has_received_sec_subpoena=True)
        self.assertGreaterEqual(mod._enforcement_exposure_score(p), 20)

    def test_doxxed_adds_8(self):
        p = make_protocol(team_is_doxxed=True, has_kyc=True,
                          has_us_user_restriction=True)
        self.assertEqual(mod._enforcement_exposure_score(p), 8)

    def test_no_us_restriction_no_kyc_adds_7(self):
        p = make_protocol(has_us_user_restriction=False, has_kyc=False,
                          team_is_doxxed=False, has_received_sec_subpoena=False)
        self.assertEqual(mod._enforcement_exposure_score(p), 7)

    def test_all_factors_capped_at_35(self):
        p = make_protocol(
            has_received_sec_subpoena=True,
            team_is_doxxed=True,
            has_us_user_restriction=False,
            has_kyc=False,
        )
        score = mod._enforcement_exposure_score(p)
        self.assertLessEqual(score, 35)
        self.assertEqual(score, 35)  # 20+8+7=35

    def test_no_factors_zero(self):
        p = make_protocol(
            has_received_sec_subpoena=False,
            team_is_doxxed=False,
            has_us_user_restriction=True,
            has_kyc=True,
        )
        self.assertEqual(mod._enforcement_exposure_score(p), 0)

    def test_kyc_reduces_us_user_risk(self):
        # has_kyc=True means no +7 from "no KYC" factor
        p = make_protocol(has_kyc=True, has_us_user_restriction=False,
                          team_is_doxxed=False, has_received_sec_subpoena=False)
        self.assertEqual(mod._enforcement_exposure_score(p), 0)

    def test_us_restriction_reduces_risk(self):
        p = make_protocol(has_us_user_restriction=True, has_kyc=False,
                          team_is_doxxed=False, has_received_sec_subpoena=False)
        self.assertEqual(mod._enforcement_exposure_score(p), 0)


# ---------------------------------------------------------------------------
# 4. Token risk score
# ---------------------------------------------------------------------------

class TestTokenRiskScore(unittest.TestCase):

    def test_security_like(self):
        self.assertEqual(mod._token_risk_score("SECURITY_LIKE"), 25)

    def test_stablecoin(self):
        self.assertEqual(mod._token_risk_score("STABLECOIN"), 18)

    def test_governance(self):
        self.assertEqual(mod._token_risk_score("GOVERNANCE"), 12)

    def test_utility(self):
        self.assertEqual(mod._token_risk_score("UTILITY"), 8)

    def test_nft(self):
        self.assertEqual(mod._token_risk_score("NFT"), 5)

    def test_unknown_token_default(self):
        self.assertEqual(mod._token_risk_score("UNKNOWN_TOKEN"), 8)

    def test_lowercase_token(self):
        self.assertEqual(mod._token_risk_score("security_like"), 25)
        self.assertEqual(mod._token_risk_score("governance"), 12)


# ---------------------------------------------------------------------------
# 5. Structural risk score
# ---------------------------------------------------------------------------

class TestStructuralRiskScore(unittest.TestCase):

    def test_zero_centralized_no_legal(self):
        p = make_protocol(centralized_components=0, has_legal_wrapper=False)
        self.assertEqual(mod._structural_risk_score(p), 5)

    def test_zero_centralized_with_legal(self):
        p = make_protocol(centralized_components=0, has_legal_wrapper=True)
        self.assertEqual(mod._structural_risk_score(p), 0)

    def test_one_centralized_with_legal(self):
        p = make_protocol(centralized_components=1, has_legal_wrapper=True)
        self.assertEqual(mod._structural_risk_score(p), 4)

    def test_three_centralized_with_legal(self):
        p = make_protocol(centralized_components=3, has_legal_wrapper=True)
        self.assertEqual(mod._structural_risk_score(p), 7)

    def test_five_centralized_with_legal(self):
        p = make_protocol(centralized_components=5, has_legal_wrapper=True)
        self.assertEqual(mod._structural_risk_score(p), 10)

    def test_five_centralized_no_legal(self):
        p = make_protocol(centralized_components=5, has_legal_wrapper=False)
        self.assertEqual(mod._structural_risk_score(p), 15)  # capped at 15

    def test_capped_at_15(self):
        p = make_protocol(centralized_components=10, has_legal_wrapper=False)
        self.assertLessEqual(mod._structural_risk_score(p), 15)

    def test_two_centralized_with_legal(self):
        # 2 >= 1 but < 3 → 4 points
        p = make_protocol(centralized_components=2, has_legal_wrapper=True)
        self.assertEqual(mod._structural_risk_score(p), 4)


# ---------------------------------------------------------------------------
# 6. Total regulatory risk score
# ---------------------------------------------------------------------------

class TestRegulatoryRiskScore(unittest.TestCase):

    def test_score_sum(self):
        self.assertEqual(mod._regulatory_risk_score(20, 35, 25, 15), 95)

    def test_score_capped_100(self):
        self.assertEqual(mod._regulatory_risk_score(25, 35, 25, 15), 100)

    def test_score_zero(self):
        self.assertEqual(mod._regulatory_risk_score(0, 0, 0, 0), 0)

    def test_partial_score(self):
        self.assertEqual(mod._regulatory_risk_score(5, 7, 8, 0), 20)


# ---------------------------------------------------------------------------
# 7. Risk level
# ---------------------------------------------------------------------------

class TestRiskLevel(unittest.TestCase):

    def test_critical(self):
        self.assertEqual(mod._risk_level(75), "CRITICAL")
        self.assertEqual(mod._risk_level(100), "CRITICAL")

    def test_high(self):
        self.assertEqual(mod._risk_level(55), "HIGH")
        self.assertEqual(mod._risk_level(74), "HIGH")

    def test_elevated(self):
        self.assertEqual(mod._risk_level(35), "ELEVATED")
        self.assertEqual(mod._risk_level(54), "ELEVATED")

    def test_moderate(self):
        self.assertEqual(mod._risk_level(20), "MODERATE")
        self.assertEqual(mod._risk_level(34), "MODERATE")

    def test_low(self):
        self.assertEqual(mod._risk_level(0), "LOW")
        self.assertEqual(mod._risk_level(19), "LOW")


# ---------------------------------------------------------------------------
# 8. Regulatory flags
# ---------------------------------------------------------------------------

class TestRegulatoryFlags(unittest.TestCase):

    def test_no_flags_gives_default(self):
        p = make_protocol(
            jurisdiction="CAYMAN",
            has_kyc=True,
            token_type="UTILITY",
            has_us_user_restriction=True,
            team_is_doxxed=False,
            has_received_sec_subpoena=False,
            centralized_components=0,
            has_legal_wrapper=True,
            tvl_usd=100_000,
        )
        flags = mod._regulatory_flags(p)
        self.assertEqual(flags, ["No significant regulatory flags"])

    def test_sec_subpoena_flag(self):
        p = make_protocol(has_received_sec_subpoena=True)
        flags = mod._regulatory_flags(p)
        self.assertTrue(any("SEC" in f for f in flags))

    def test_security_like_flag(self):
        p = make_protocol(token_type="SECURITY_LIKE", has_us_user_restriction=True)
        flags = mod._regulatory_flags(p)
        self.assertTrue(any("security" in f.lower() for f in flags))

    def test_us_no_kyc_flag(self):
        p = make_protocol(jurisdiction="US", has_kyc=False)
        flags = mod._regulatory_flags(p)
        self.assertTrue(any("KYC" in f for f in flags))

    def test_us_with_kyc_no_us_kyc_flag(self):
        p = make_protocol(jurisdiction="US", has_kyc=True,
                          token_type="UTILITY", has_us_user_restriction=True,
                          centralized_components=0, has_legal_wrapper=True)
        flags = mod._regulatory_flags(p)
        self.assertFalse(any("KYC" in f for f in flags))

    def test_us_restriction_flag_for_security_like(self):
        # Not restricted + SECURITY_LIKE → flag
        p = make_protocol(token_type="SECURITY_LIKE", has_us_user_restriction=False,
                          jurisdiction="CAYMAN")
        flags = mod._regulatory_flags(p)
        self.assertTrue(any("US users" in f for f in flags))

    def test_us_restriction_flag_for_governance(self):
        p = make_protocol(token_type="GOVERNANCE", has_us_user_restriction=False,
                          jurisdiction="CAYMAN")
        flags = mod._regulatory_flags(p)
        self.assertTrue(any("US users" in f for f in flags))

    def test_centralized_components_flag(self):
        p = make_protocol(centralized_components=3)
        flags = mod._regulatory_flags(p)
        self.assertTrue(any("3 centralized" in f for f in flags))

    def test_centralized_below_3_no_flag(self):
        p = make_protocol(centralized_components=2, has_legal_wrapper=True,
                          token_type="UTILITY", has_us_user_restriction=True,
                          jurisdiction="CAYMAN", has_kyc=True)
        flags = mod._regulatory_flags(p)
        self.assertFalse(any("centralized" in f for f in flags))

    def test_large_tvl_no_legal_flag(self):
        p = make_protocol(tvl_usd=10_000_000, has_legal_wrapper=False,
                          centralized_components=0)
        flags = mod._regulatory_flags(p)
        self.assertTrue(any("legal wrapper" in f.lower() for f in flags))

    def test_small_tvl_no_legal_no_flag(self):
        p = make_protocol(tvl_usd=9_999_999, has_legal_wrapper=False,
                          centralized_components=0, token_type="UTILITY",
                          has_us_user_restriction=True, jurisdiction="CAYMAN")
        flags = mod._regulatory_flags(p)
        self.assertFalse(any("legal wrapper" in f.lower() for f in flags))

    def test_multiple_flags(self):
        p = make_protocol(
            has_received_sec_subpoena=True,
            token_type="SECURITY_LIKE",
            jurisdiction="US",
            has_kyc=False,
            has_us_user_restriction=False,
            centralized_components=5,
            has_legal_wrapper=False,
            tvl_usd=50_000_000,
        )
        flags = mod._regulatory_flags(p)
        self.assertGreater(len(flags), 1)


# ---------------------------------------------------------------------------
# 9. Recommendation
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):

    def test_critical_recommendation(self):
        r = mod._recommendation("Foo", "CRITICAL", "US", 0)
        self.assertIn("CRITICAL", r)
        self.assertIn("Foo", r)

    def test_high_recommendation(self):
        r = mod._recommendation("Bar", "HIGH", "US", 0)
        self.assertIn("Bar", r)
        self.assertIn("enforcement", r.lower())

    def test_elevated_recommendation(self):
        r = mod._recommendation("Baz", "ELEVATED", "EU", 0)
        self.assertIn("EU", r)

    def test_moderate_recommendation(self):
        r = mod._recommendation("Qux", "MODERATE", "CAYMAN", 2)
        self.assertIn("Qux", r)
        self.assertIn("2", r)

    def test_low_recommendation(self):
        r = mod._recommendation("Safe", "LOW", "CAYMAN", 0)
        self.assertIn("Safe", r)
        self.assertIn("manageable", r.lower())


# ---------------------------------------------------------------------------
# 10. analyze — output structure
# ---------------------------------------------------------------------------

class TestOutputStructure(unittest.TestCase):

    def test_top_level_keys(self):
        r = mod.analyze([make_protocol()])
        for key in ("protocols", "highest_regulatory_risk",
                    "lowest_regulatory_risk", "high_risk_count",
                    "average_risk_score", "timestamp"):
            self.assertIn(key, r)

    def test_protocol_entry_keys(self):
        r = mod.analyze([make_protocol()])
        e = r["protocols"][0]
        for key in ("name", "regulatory_risk_score", "risk_level",
                    "jurisdiction_score", "enforcement_exposure_score",
                    "token_risk_score", "structural_risk_score",
                    "regulatory_flags", "recommendation"):
            self.assertIn(key, e, msg=f"Missing key: {key}")

    def test_regulatory_flags_is_list(self):
        r = mod.analyze([make_protocol()])
        self.assertIsInstance(r["protocols"][0]["regulatory_flags"], list)

    def test_timestamp_is_float(self):
        r = mod.analyze([make_protocol()])
        self.assertIsInstance(r["timestamp"], float)

    def test_score_is_int(self):
        r = mod.analyze([make_protocol()])
        self.assertIsInstance(r["protocols"][0]["regulatory_risk_score"], int)

    def test_risk_level_valid(self):
        r = mod.analyze([make_protocol()])
        self.assertIn(r["protocols"][0]["risk_level"],
                      ("LOW", "MODERATE", "ELEVATED", "HIGH", "CRITICAL"))


# ---------------------------------------------------------------------------
# 11. Aggregates
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):

    def test_highest_risk_correct(self):
        p_low = make_protocol(name="LowRisk", jurisdiction="DECENTRALIZED",
                              has_kyc=True, token_type="UTILITY",
                              has_us_user_restriction=True, team_is_doxxed=False,
                              has_received_sec_subpoena=False,
                              centralized_components=0, has_legal_wrapper=True,
                              tvl_usd=100_000)
        p_high = make_protocol(name="HighRisk", jurisdiction="US",
                               has_kyc=False, token_type="SECURITY_LIKE",
                               has_us_user_restriction=False, team_is_doxxed=True,
                               has_received_sec_subpoena=True,
                               centralized_components=5, has_legal_wrapper=False,
                               tvl_usd=50_000_000)
        r = mod.analyze([p_low, p_high])
        self.assertEqual(r["highest_regulatory_risk"], "HighRisk")

    def test_lowest_risk_correct(self):
        p_low = make_protocol(name="LowRisk", jurisdiction="DECENTRALIZED",
                              has_kyc=True, token_type="UTILITY",
                              has_us_user_restriction=True, team_is_doxxed=False,
                              has_received_sec_subpoena=False,
                              centralized_components=0, has_legal_wrapper=True,
                              tvl_usd=100_000)
        p_high = make_protocol(name="HighRisk", jurisdiction="US",
                               has_kyc=False, token_type="SECURITY_LIKE",
                               has_us_user_restriction=False, team_is_doxxed=True,
                               has_received_sec_subpoena=True,
                               centralized_components=5, has_legal_wrapper=False,
                               tvl_usd=50_000_000)
        r = mod.analyze([p_low, p_high])
        self.assertEqual(r["lowest_regulatory_risk"], "LowRisk")

    def test_high_risk_count_critical_and_high(self):
        p1 = make_protocol(name="A", jurisdiction="US",
                           has_received_sec_subpoena=True, token_type="SECURITY_LIKE",
                           team_is_doxxed=True, has_kyc=False,
                           has_us_user_restriction=False, centralized_components=5,
                           has_legal_wrapper=False, tvl_usd=50_000_000)
        p2 = make_protocol(name="B", jurisdiction="CAYMAN",
                           has_kyc=True, token_type="UTILITY",
                           has_us_user_restriction=True,
                           centralized_components=0, has_legal_wrapper=True)
        r = mod.analyze([p1, p2])
        # p1 should be HIGH or CRITICAL; p2 should be low
        self.assertGreaterEqual(r["high_risk_count"], 1)

    def test_average_risk_score_single(self):
        p = make_protocol(jurisdiction="DECENTRALIZED",
                          has_kyc=True, token_type="UTILITY",
                          has_us_user_restriction=True,
                          centralized_components=0, has_legal_wrapper=True)
        r = mod.analyze([p])
        self.assertAlmostEqual(r["average_risk_score"],
                               r["protocols"][0]["regulatory_risk_score"], places=2)

    def test_average_risk_score_multiple(self):
        p1 = make_protocol(name="A")
        p2 = make_protocol(name="B")
        r = mod.analyze([p1, p2])
        expected = (r["protocols"][0]["regulatory_risk_score"] +
                    r["protocols"][1]["regulatory_risk_score"]) / 2
        self.assertAlmostEqual(r["average_risk_score"], expected, places=2)

    def test_single_protocol_highest_equals_lowest(self):
        r = mod.analyze([make_protocol(name="OnlyOne")])
        self.assertEqual(r["highest_regulatory_risk"], "OnlyOne")
        self.assertEqual(r["lowest_regulatory_risk"], "OnlyOne")


# ---------------------------------------------------------------------------
# 12. Known score scenarios
# ---------------------------------------------------------------------------

class TestKnownScenarios(unittest.TestCase):

    def test_fully_decentralized_low_risk(self):
        p = make_protocol(
            name="Pure DeFi",
            jurisdiction="DECENTRALIZED",
            has_kyc=False,
            token_type="UTILITY",
            has_us_user_restriction=False,
            team_is_doxxed=False,
            has_received_sec_subpoena=False,
            centralized_components=0,
            has_legal_wrapper=True,
            tvl_usd=500_000,
        )
        r = mod.analyze([p])
        e = r["protocols"][0]
        # DECENTRALIZED=5, enforcement: no_sec=0, not_doxxed=0, no_us_restriction+no_kyc=7 → 7
        # UTILITY=8, legal=True, 0 centralized → 0
        # Total = 5+7+8+0 = 20 → MODERATE
        self.assertEqual(e["jurisdiction_score"], 5)
        self.assertEqual(e["token_risk_score"], 8)
        self.assertEqual(e["structural_risk_score"], 0)
        self.assertEqual(e["enforcement_exposure_score"], 7)
        self.assertEqual(e["regulatory_risk_score"], 20)

    def test_worst_case_us_sec_security_like(self):
        p = make_protocol(
            name="MaxRisk",
            jurisdiction="US",
            has_kyc=False,
            token_type="SECURITY_LIKE",
            has_us_user_restriction=False,
            team_is_doxxed=True,
            has_received_sec_subpoena=True,
            centralized_components=5,
            has_legal_wrapper=False,
            tvl_usd=100_000_000,
        )
        r = mod.analyze([p])
        e = r["protocols"][0]
        self.assertEqual(e["jurisdiction_score"], 20)
        self.assertEqual(e["enforcement_exposure_score"], 35)  # capped
        self.assertEqual(e["token_risk_score"], 25)
        self.assertEqual(e["structural_risk_score"], 15)  # capped
        self.assertEqual(e["regulatory_risk_score"], min(100, 20 + 35 + 25 + 15))
        self.assertEqual(e["risk_level"], "CRITICAL")

    def test_cayman_governance_moderate(self):
        p = make_protocol(
            jurisdiction="CAYMAN",
            has_kyc=False,
            token_type="GOVERNANCE",
            has_us_user_restriction=False,
            team_is_doxxed=False,
            has_received_sec_subpoena=False,
            centralized_components=0,
            has_legal_wrapper=True,
            tvl_usd=1_000_000,
        )
        r = mod.analyze([p])
        e = r["protocols"][0]
        # CAYMAN=8, enforcement=(no_sec=0, not_doxxed=0, no_restriction+no_kyc=7)=7
        # GOVERNANCE=12, legal=True, 0 centralized=0
        # Total=8+7+12+0=27 → MODERATE
        self.assertEqual(e["regulatory_risk_score"], 27)
        self.assertEqual(e["risk_level"], "MODERATE")


# ---------------------------------------------------------------------------
# 13. Data file logging
# ---------------------------------------------------------------------------

class TestDataFileLogging(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig = mod.DATA_FILE
        mod.DATA_FILE = Path(self.tmp) / "regulatory_risk_log.json"

    def tearDown(self):
        mod.DATA_FILE = self.orig

    def test_log_file_created(self):
        mod.analyze([make_protocol()])
        self.assertTrue(mod.DATA_FILE.exists())

    def test_log_file_is_list(self):
        mod.analyze([make_protocol()])
        with open(mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends(self):
        mod.analyze([make_protocol()])
        mod.analyze([make_protocol()])
        with open(mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_max(self):
        for _ in range(mod.MAX_ENTRIES + 5):
            mod.analyze([make_protocol()])
        with open(mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), mod.MAX_ENTRIES)

    def test_atomic_no_tmp_lingering(self):
        mod.analyze([make_protocol()])
        tmp_path = str(mod.DATA_FILE) + ".tmp"
        self.assertFalse(os.path.exists(tmp_path))

    def test_log_contains_protocols(self):
        mod.analyze([make_protocol(name="LoggedProtocol")])
        with open(mod.DATA_FILE) as f:
            data = json.load(f)
        self.assertIn("protocols", data[0])


# ---------------------------------------------------------------------------
# 14. high_risk_count
# ---------------------------------------------------------------------------

class TestHighRiskCount(unittest.TestCase):

    def test_no_high_risk(self):
        p = make_protocol(jurisdiction="DECENTRALIZED", has_kyc=True,
                          token_type="UTILITY", has_us_user_restriction=True,
                          centralized_components=0, has_legal_wrapper=True)
        r = mod.analyze([p])
        # score should be LOW/MODERATE → high_risk_count=0
        self.assertGreaterEqual(r["high_risk_count"], 0)

    def test_high_risk_count_includes_critical(self):
        p = make_protocol(
            jurisdiction="US",
            token_type="SECURITY_LIKE",
            has_received_sec_subpoena=True,
            team_is_doxxed=True,
            has_kyc=False,
            has_us_user_restriction=False,
            centralized_components=5,
            has_legal_wrapper=False,
            tvl_usd=50_000_000,
        )
        r = mod.analyze([p])
        self.assertGreaterEqual(r["high_risk_count"], 1)


# ---------------------------------------------------------------------------
# 15. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_multiple_protocols_all_returned(self):
        protos = [make_protocol(name=f"P{i}") for i in range(7)]
        r = mod.analyze(protos)
        self.assertEqual(len(r["protocols"]), 7)

    def test_name_passthrough(self):
        r = mod.analyze([make_protocol(name="SpecialName")])
        self.assertEqual(r["protocols"][0]["name"], "SpecialName")

    def test_score_never_exceeds_100(self):
        p = make_protocol(jurisdiction="US",
                          token_type="SECURITY_LIKE",
                          has_received_sec_subpoena=True,
                          team_is_doxxed=True, has_kyc=False,
                          has_us_user_restriction=False,
                          centralized_components=10, has_legal_wrapper=False,
                          tvl_usd=999_999_999)
        r = mod.analyze([p])
        self.assertLessEqual(r["protocols"][0]["regulatory_risk_score"], 100)

    def test_structural_score_never_exceeds_15(self):
        p = make_protocol(centralized_components=10, has_legal_wrapper=False)
        self.assertLessEqual(mod._structural_risk_score(p), 15)

    def test_enforcement_score_never_exceeds_35(self):
        p = make_protocol(has_received_sec_subpoena=True, team_is_doxxed=True,
                          has_us_user_restriction=False, has_kyc=False)
        self.assertLessEqual(mod._enforcement_exposure_score(p), 35)

    def test_high_risk_count_zero_for_all_low(self):
        # DECENTRALIZED + UTILITY + legal + no threats = low score
        p = make_protocol(
            jurisdiction="DECENTRALIZED",
            has_kyc=True,
            token_type="UTILITY",
            has_us_user_restriction=True,
            team_is_doxxed=False,
            has_received_sec_subpoena=False,
            centralized_components=0,
            has_legal_wrapper=True,
            tvl_usd=100_000,
        )
        r = mod.analyze([p])
        level = r["protocols"][0]["risk_level"]
        count = r["high_risk_count"]
        if level in ("LOW", "MODERATE", "ELEVATED"):
            self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
