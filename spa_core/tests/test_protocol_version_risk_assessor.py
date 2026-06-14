"""
Tests for MP-783: ProtocolVersionRiskAssessor
≥ 65 unit tests covering:
  - Maturity score (linear ramp, cap at 40)
  - Security score (audit count + recency)
  - Adoption score (log-scale TVS, 0-20 pts)
  - Vulnerability penalty
  - Total version score
  - Risk tier classification
  - assess() result structure
  - get_risk_tier() / get_score_breakdown() helpers
  - Ring-buffer cap at 100
  - Atomic write / file persistence
  - Edge cases
"""

import json
import math
import os
import shutil
import tempfile
import unittest

from spa_core.analytics.protocol_version_risk_assessor import (
    ProtocolVersionRiskAssessor,
    compute_maturity_score,
    compute_security_score,
    compute_adoption_score,
    classify_risk_tier,
    TIER_BATTLE_TESTED,
    TIER_ESTABLISHED,
    TIER_MATURING,
    TIER_EXPERIMENTAL,
    VULNERABILITY_PENALTY,
    RING_BUFFER_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proto(
    protocol="TestProto",
    version_string="v1.0",
    days_since_release=365,
    total_value_secured_usd=1_000_000_000,
    known_vulnerabilities=0,
    audit_count=4,
    last_audit_days_ago=30,
):
    return {
        "protocol": protocol,
        "version_string": version_string,
        "days_since_release": days_since_release,
        "total_value_secured_usd": total_value_secured_usd,
        "known_vulnerabilities": known_vulnerabilities,
        "audit_count": audit_count,
        "last_audit_days_ago": last_audit_days_ago,
    }


# ---------------------------------------------------------------------------
# 1. compute_maturity_score
# ---------------------------------------------------------------------------

class TestMaturityScore(unittest.TestCase):

    def test_zero_days(self):
        self.assertEqual(compute_maturity_score(0), 0.0)

    def test_negative_days(self):
        self.assertEqual(compute_maturity_score(-10), 0.0)

    def test_one_day(self):
        score = compute_maturity_score(1)
        self.assertAlmostEqual(score, 40 / 365, places=6)

    def test_30_days(self):
        score = compute_maturity_score(30)
        self.assertAlmostEqual(score, 30 / 365 * 40, places=6)

    def test_182_days_half_max(self):
        score = compute_maturity_score(182.5)
        self.assertAlmostEqual(score, 20.0, places=4)

    def test_365_days_full(self):
        self.assertAlmostEqual(compute_maturity_score(365), 40.0, places=10)

    def test_exactly_365_equals_max(self):
        self.assertEqual(compute_maturity_score(365.0), 40.0)

    def test_over_365_capped_at_40(self):
        self.assertEqual(compute_maturity_score(730), 40.0)

    def test_1000_days_capped(self):
        self.assertEqual(compute_maturity_score(1000), 40.0)

    def test_linear_interpolation(self):
        s1 = compute_maturity_score(100)
        s2 = compute_maturity_score(200)
        self.assertAlmostEqual(s2, 2 * s1, places=8)


# ---------------------------------------------------------------------------
# 2. compute_security_score
# ---------------------------------------------------------------------------

class TestSecurityScore(unittest.TestCase):

    def test_no_audits_zero_score(self):
        self.assertEqual(compute_security_score(0, 0), 0.0)

    def test_no_audits_any_recency(self):
        self.assertEqual(compute_security_score(0, 30), 0.0)

    def test_one_audit_fresh(self):
        score = compute_security_score(1, 0)
        # audit pts = 5, recency = 20 → 25
        self.assertAlmostEqual(score, 25.0, places=8)

    def test_two_audits_fresh(self):
        score = compute_security_score(2, 0)
        self.assertAlmostEqual(score, 30.0, places=8)

    def test_four_audits_fresh(self):
        """Max audit pts (20) + full recency (20) = 40."""
        score = compute_security_score(4, 0)
        self.assertAlmostEqual(score, 40.0, places=8)

    def test_more_than_four_audits_capped(self):
        score = compute_security_score(10, 0)
        self.assertAlmostEqual(score, 40.0, places=8)

    def test_one_audit_365_days_ago(self):
        """Recency pts = 0 (365 days ago), audit pts = 5."""
        score = compute_security_score(1, 365)
        self.assertAlmostEqual(score, 5.0, places=8)

    def test_four_audits_365_days_ago(self):
        """audit=20 + recency=0 = 20."""
        score = compute_security_score(4, 365)
        self.assertAlmostEqual(score, 20.0, places=8)

    def test_recency_decays_linearly(self):
        s0  = compute_security_score(1, 0)
        s90 = compute_security_score(1, 90)
        s180 = compute_security_score(1, 180)
        # recency part: 20, 20*(1-90/365), 20*(1-180/365)
        self.assertGreater(s0, s90)
        self.assertGreater(s90, s180)

    def test_recency_never_negative(self):
        score = compute_security_score(2, 9999)
        self.assertGreaterEqual(score, 0.0)

    def test_recency_exactly_half_year(self):
        score = compute_security_score(1, 182.5)
        expected_recency = 20.0 * (1 - 182.5 / 365.0)
        self.assertAlmostEqual(score, 5.0 + expected_recency, places=6)


# ---------------------------------------------------------------------------
# 3. compute_adoption_score
# ---------------------------------------------------------------------------

class TestAdoptionScore(unittest.TestCase):

    def test_zero_tvs(self):
        self.assertEqual(compute_adoption_score(0), 0.0)

    def test_negative_tvs(self):
        self.assertEqual(compute_adoption_score(-1000), 0.0)

    def test_below_100k_zero(self):
        self.assertEqual(compute_adoption_score(50_000), 0.0)

    def test_exactly_100k_zero(self):
        self.assertAlmostEqual(compute_adoption_score(100_000), 0.0, places=8)

    def test_1m_tvs(self):
        """log10(1e6)=6 → (6-5)/4*20 = 5 pts."""
        score = compute_adoption_score(1_000_000)
        self.assertAlmostEqual(score, 5.0, places=8)

    def test_10m_tvs(self):
        """log10(1e7)=7 → 10 pts."""
        score = compute_adoption_score(10_000_000)
        self.assertAlmostEqual(score, 10.0, places=8)

    def test_100m_tvs(self):
        """log10(1e8)=8 → 15 pts."""
        score = compute_adoption_score(100_000_000)
        self.assertAlmostEqual(score, 15.0, places=8)

    def test_1b_tvs_full(self):
        """log10(1e9)=9 → 20 pts."""
        score = compute_adoption_score(1_000_000_000)
        self.assertAlmostEqual(score, 20.0, places=8)

    def test_10b_tvs_capped_at_20(self):
        score = compute_adoption_score(10_000_000_000)
        self.assertAlmostEqual(score, 20.0, places=8)

    def test_monotone_increasing(self):
        tvs_vals = [100_000, 1_000_000, 10_000_000, 100_000_000, 1_000_000_000]
        scores = [compute_adoption_score(t) for t in tvs_vals]
        for i in range(len(scores) - 1):
            self.assertLessEqual(scores[i], scores[i + 1])

    def test_log_scale_midpoint(self):
        """At √(1e5 * 1e9) ≈ 3.162e7, should be ~10 pts."""
        mid_tvs = math.sqrt(1e5 * 1e9)  # geometric mean
        score = compute_adoption_score(mid_tvs)
        self.assertAlmostEqual(score, 10.0, places=4)


# ---------------------------------------------------------------------------
# 4. classify_risk_tier
# ---------------------------------------------------------------------------

class TestClassifyRiskTier(unittest.TestCase):

    def test_below_40_experimental(self):
        self.assertEqual(classify_risk_tier(0), TIER_EXPERIMENTAL)
        self.assertEqual(classify_risk_tier(39.9), TIER_EXPERIMENTAL)

    def test_exactly_40_maturing(self):
        self.assertEqual(classify_risk_tier(40), TIER_MATURING)

    def test_between_40_60_maturing(self):
        self.assertEqual(classify_risk_tier(55), TIER_MATURING)

    def test_exactly_60_established(self):
        self.assertEqual(classify_risk_tier(60), TIER_ESTABLISHED)

    def test_between_60_80_established(self):
        self.assertEqual(classify_risk_tier(70), TIER_ESTABLISHED)

    def test_exactly_80_battle_tested(self):
        self.assertEqual(classify_risk_tier(80), TIER_BATTLE_TESTED)

    def test_above_80_battle_tested(self):
        self.assertEqual(classify_risk_tier(100), TIER_BATTLE_TESTED)

    def test_zero_is_experimental(self):
        self.assertEqual(classify_risk_tier(0.0), TIER_EXPERIMENTAL)


# ---------------------------------------------------------------------------
# 5. ProtocolVersionRiskAssessor.assess()
# ---------------------------------------------------------------------------

class TestAssess(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmpdir, "pvr_log.json")
        self.assessor = ProtocolVersionRiskAssessor(data_file=self.data_file)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_dict(self):
        result = self.assessor.assess(_proto())
        self.assertIsInstance(result, dict)

    def test_all_expected_keys(self):
        result = self.assessor.assess(_proto())
        for key in [
            "protocol", "version_string", "days_since_release",
            "total_value_secured_usd", "known_vulnerabilities",
            "audit_count", "last_audit_days_ago",
            "score_breakdown", "total_version_score", "risk_tier", "timestamp",
        ]:
            self.assertIn(key, result, msg=f"Missing key: {key}")

    def test_score_breakdown_has_components(self):
        result = self.assessor.assess(_proto())
        bd = result["score_breakdown"]
        for key in ["maturity_score", "security_score", "adoption_score",
                    "raw_score", "vuln_penalty", "total_version_score"]:
            self.assertIn(key, bd, msg=f"Missing breakdown key: {key}")

    def test_protocol_name_in_result(self):
        result = self.assessor.assess(_proto(protocol="Aave"))
        self.assertEqual(result["protocol"], "Aave")

    def test_version_string_in_result(self):
        result = self.assessor.assess(_proto(version_string="v3.1"))
        self.assertEqual(result["version_string"], "v3.1")

    def test_timestamp_present(self):
        import time
        before = time.time()
        result = self.assessor.assess(_proto())
        self.assertGreaterEqual(result["timestamp"], before)

    def test_total_score_sums_components(self):
        result = self.assessor.assess(_proto(known_vulnerabilities=0))
        bd = result["score_breakdown"]
        expected = bd["maturity_score"] + bd["security_score"] + bd["adoption_score"]
        self.assertAlmostEqual(bd["raw_score"], expected, places=10)
        self.assertAlmostEqual(result["total_version_score"], expected, places=10)

    def test_well_known_protocol_battle_tested(self):
        """Aave-like: 1y+, 4 audits, fresh, $1B TVS → BATTLE_TESTED."""
        result = self.assessor.assess(_proto(
            days_since_release=730,
            audit_count=4,
            last_audit_days_ago=30,
            total_value_secured_usd=5_000_000_000,
            known_vulnerabilities=0,
        ))
        self.assertEqual(result["risk_tier"], TIER_BATTLE_TESTED)

    def test_new_protocol_experimental(self):
        result = self.assessor.assess(_proto(
            days_since_release=10,
            audit_count=0,
            last_audit_days_ago=9999,
            total_value_secured_usd=10_000,
            known_vulnerabilities=0,
        ))
        self.assertEqual(result["risk_tier"], TIER_EXPERIMENTAL)

    def test_vulnerability_penalty_applied(self):
        r0 = self.assessor.assess(_proto(known_vulnerabilities=0))
        r1 = self.assessor.assess(_proto(known_vulnerabilities=1))
        self.assertAlmostEqual(
            r0["total_version_score"] - r1["total_version_score"],
            VULNERABILITY_PENALTY,
            places=8,
        )

    def test_vulnerability_penalty_two(self):
        r0 = self.assessor.assess(_proto(known_vulnerabilities=0))
        r2 = self.assessor.assess(_proto(known_vulnerabilities=2))
        diff = r0["total_version_score"] - r2["total_version_score"]
        self.assertAlmostEqual(diff, 2 * VULNERABILITY_PENALTY, places=8)

    def test_vulnerability_penalty_floors_at_zero(self):
        result = self.assessor.assess(_proto(
            days_since_release=10,
            audit_count=0,
            last_audit_days_ago=9999,
            total_value_secured_usd=1000,
            known_vulnerabilities=99,
        ))
        self.assertEqual(result["total_version_score"], 0.0)

    def test_score_never_negative(self):
        result = self.assessor.assess(_proto(known_vulnerabilities=100))
        self.assertGreaterEqual(result["total_version_score"], 0.0)

    def test_maturity_score_in_breakdown(self):
        result = self.assessor.assess(_proto(days_since_release=365))
        self.assertAlmostEqual(result["score_breakdown"]["maturity_score"], 40.0, places=8)

    def test_security_score_in_breakdown(self):
        result = self.assessor.assess(_proto(audit_count=4, last_audit_days_ago=0))
        self.assertAlmostEqual(result["score_breakdown"]["security_score"], 40.0, places=8)

    def test_adoption_score_in_breakdown(self):
        result = self.assessor.assess(_proto(total_value_secured_usd=1_000_000_000))
        self.assertAlmostEqual(result["score_breakdown"]["adoption_score"], 20.0, places=8)

    def test_vuln_penalty_in_breakdown(self):
        result = self.assessor.assess(_proto(known_vulnerabilities=1))
        self.assertAlmostEqual(
            result["score_breakdown"]["vuln_penalty"], VULNERABILITY_PENALTY, places=8
        )

    def test_log_appended(self):
        self.assessor.assess(_proto())
        self.assertEqual(len(self.assessor.get_log()), 1)

    def test_file_created(self):
        self.assessor.assess(_proto())
        self.assertTrue(os.path.exists(self.data_file))

    def test_file_valid_json(self):
        self.assessor.assess(_proto())
        with open(self.data_file) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_persists_across_instances(self):
        self.assessor.assess(_proto())
        a2 = ProtocolVersionRiskAssessor(data_file=self.data_file)
        self.assertEqual(len(a2.get_log()), 1)

    def test_no_tmp_files_left(self):
        self.assessor.assess(_proto())
        tmp_files = [f for f in os.listdir(self.tmpdir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_defaults_do_not_raise(self):
        """All-defaults dict should work without error."""
        result = self.assessor.assess({})
        self.assertIn("risk_tier", result)


# ---------------------------------------------------------------------------
# 6. get_risk_tier() / get_score_breakdown()
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.assessor = ProtocolVersionRiskAssessor(
            data_file=os.path.join(self.tmpdir, "pvr.json")
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_risk_tier_none_before_assess(self):
        self.assertIsNone(self.assessor.get_risk_tier())

    def test_get_score_breakdown_none_before_assess(self):
        self.assertIsNone(self.assessor.get_score_breakdown())

    def test_get_risk_tier_after_assess(self):
        self.assessor.assess(_proto())
        self.assertIsNotNone(self.assessor.get_risk_tier())

    def test_get_score_breakdown_after_assess(self):
        self.assessor.assess(_proto())
        bd = self.assessor.get_score_breakdown()
        self.assertIsInstance(bd, dict)

    def test_get_score_breakdown_is_copy(self):
        self.assessor.assess(_proto())
        bd = self.assessor.get_score_breakdown()
        bd["maturity_score"] = 999.0
        bd2 = self.assessor.get_score_breakdown()
        self.assertNotEqual(bd2["maturity_score"], 999.0)

    def test_get_risk_tier_reflects_last_assess(self):
        self.assessor.assess(_proto(days_since_release=1, audit_count=0,
                                    total_value_secured_usd=1000))
        tier1 = self.assessor.get_risk_tier()
        self.assessor.assess(_proto(days_since_release=730, audit_count=4,
                                    total_value_secured_usd=1_000_000_000))
        tier2 = self.assessor.get_risk_tier()
        self.assertNotEqual(tier1, tier2)


# ---------------------------------------------------------------------------
# 7. Ring-buffer
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmpdir, "pvr_log.json")
        self.assessor = ProtocolVersionRiskAssessor(data_file=self.data_file)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ring_buffer_cap_100(self):
        for i in range(110):
            self.assessor.assess(_proto(days_since_release=float(i)))
        self.assertEqual(len(self.assessor.get_log()), RING_BUFFER_SIZE)

    def test_file_respects_ring_buffer(self):
        for i in range(110):
            self.assessor.assess(_proto(days_since_release=float(i)))
        with open(self.data_file) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), RING_BUFFER_SIZE)

    def test_get_log_returns_copy(self):
        self.assessor.assess(_proto())
        log1 = self.assessor.get_log()
        log1.append({"fake": True})
        self.assertEqual(len(self.assessor.get_log()), 1)

    def test_initial_log_empty(self):
        self.assertEqual(self.assessor.get_log(), [])


# ---------------------------------------------------------------------------
# 8. Full scenario tests
# ---------------------------------------------------------------------------

class TestFullScenarios(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.assessor = ProtocolVersionRiskAssessor(
            data_file=os.path.join(self.tmpdir, "pvr.json")
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_experimental_all_zeros(self):
        result = self.assessor.assess(_proto(
            days_since_release=0, audit_count=0,
            last_audit_days_ago=9999, total_value_secured_usd=0,
            known_vulnerabilities=0,
        ))
        self.assertEqual(result["risk_tier"], TIER_EXPERIMENTAL)
        self.assertEqual(result["total_version_score"], 0.0)

    def test_maturing_mid_range(self):
        """~6 months, 2 audits, moderate TVS → MATURING expected."""
        result = self.assessor.assess(_proto(
            days_since_release=180,
            audit_count=2,
            last_audit_days_ago=90,
            total_value_secured_usd=5_000_000,
            known_vulnerabilities=0,
        ))
        self.assertIn(result["risk_tier"], [TIER_MATURING, TIER_ESTABLISHED])

    def test_penalty_pushes_tier_down(self):
        """A well-scored protocol with a vulnerability drops a tier."""
        r_clean = self.assessor.assess(_proto(
            days_since_release=365, audit_count=4, last_audit_days_ago=30,
            total_value_secured_usd=1_000_000_000, known_vulnerabilities=0,
        ))
        r_vuln = self.assessor.assess(_proto(
            days_since_release=365, audit_count=4, last_audit_days_ago=30,
            total_value_secured_usd=1_000_000_000, known_vulnerabilities=1,
        ))
        self.assertGreater(r_clean["total_version_score"], r_vuln["total_version_score"])

    def test_tier_ordering_consistent(self):
        tiers = [TIER_EXPERIMENTAL, TIER_MATURING, TIER_ESTABLISHED, TIER_BATTLE_TESTED]
        scores = [0, 40, 60, 80]
        for tier, score in zip(tiers, scores):
            self.assertEqual(classify_risk_tier(score), tier)


if __name__ == "__main__":
    unittest.main()
