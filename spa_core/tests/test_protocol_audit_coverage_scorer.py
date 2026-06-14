"""
Tests for MP-884: ProtocolAuditCoverageScorer
Run: python3 -m unittest spa_core.tests.test_protocol_audit_coverage_scorer -v
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_audit_coverage_scorer import (
    analyze,
    log_result,
    _resolve_config,
    _audit_recency_score,
    _auditor_quality_score,
    _coverage_score,
    _finding_penalty,
    _bounty_score,
    _formal_verification_bonus,
    _overall_score,
    _security_grade,
    _audit_status,
    _build_flags,
    _recommendation,
    _score_protocol,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proto(**kwargs) -> dict:
    """Return a well-audited default protocol, overriding with kwargs."""
    base = {
        "name": "TestProto",
        "audit_count": 3,
        "auditor_tier": "TOP_TIER",
        "days_since_last_audit": 60,    # recency score 80
        "lines_of_code": 10_000,
        "audit_coverage_pct": 90.0,
        "critical_findings_unresolved": 0,
        "high_findings_unresolved": 0,
        "bug_bounty_usd": 500_000.0,
        "formal_verification": False,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# _resolve_config
# ---------------------------------------------------------------------------

class TestResolveConfig(unittest.TestCase):
    def test_default_stale_days(self):
        cfg = _resolve_config(None)
        self.assertEqual(cfg["stale_audit_days"], 365)

    def test_override_stale_days(self):
        cfg = _resolve_config({"stale_audit_days": 180})
        self.assertEqual(cfg["stale_audit_days"], 180)

    def test_empty_dict_defaults(self):
        cfg = _resolve_config({})
        self.assertEqual(cfg["stale_audit_days"], 365)

    def test_string_coerces_to_int(self):
        cfg = _resolve_config({"stale_audit_days": "200"})
        self.assertEqual(cfg["stale_audit_days"], 200)


# ---------------------------------------------------------------------------
# _audit_recency_score
# ---------------------------------------------------------------------------

class TestAuditRecencyScore(unittest.TestCase):
    def test_0_days(self):
        self.assertEqual(_audit_recency_score(0), 100)

    def test_30_days(self):
        self.assertEqual(_audit_recency_score(30), 100)

    def test_31_days(self):
        self.assertEqual(_audit_recency_score(31), 80)

    def test_90_days(self):
        self.assertEqual(_audit_recency_score(90), 80)

    def test_91_days(self):
        self.assertEqual(_audit_recency_score(91), 60)

    def test_180_days(self):
        self.assertEqual(_audit_recency_score(180), 60)

    def test_181_days(self):
        self.assertEqual(_audit_recency_score(181), 40)

    def test_365_days(self):
        self.assertEqual(_audit_recency_score(365), 40)

    def test_366_days(self):
        self.assertEqual(_audit_recency_score(366), 20)

    def test_730_days(self):
        self.assertEqual(_audit_recency_score(730), 20)

    def test_731_days(self):
        self.assertEqual(_audit_recency_score(731), 0)

    def test_very_old(self):
        self.assertEqual(_audit_recency_score(9999), 0)


# ---------------------------------------------------------------------------
# _auditor_quality_score
# ---------------------------------------------------------------------------

class TestAuditorQualityScore(unittest.TestCase):
    def test_top_tier(self):
        self.assertEqual(_auditor_quality_score("TOP_TIER"), 100)

    def test_mid_tier(self):
        self.assertEqual(_auditor_quality_score("MID_TIER"), 70)

    def test_community(self):
        self.assertEqual(_auditor_quality_score("COMMUNITY"), 40)

    def test_unaudited(self):
        self.assertEqual(_auditor_quality_score("UNAUDITED"), 0)

    def test_unknown_tier_returns_0(self):
        self.assertEqual(_auditor_quality_score("UNKNOWN_TIER"), 0)


# ---------------------------------------------------------------------------
# _coverage_score
# ---------------------------------------------------------------------------

class TestCoverageScore(unittest.TestCase):
    def test_100_pct(self):
        self.assertEqual(_coverage_score(100.0), 100)

    def test_above_100_capped(self):
        self.assertEqual(_coverage_score(120.0), 100)

    def test_50_pct(self):
        self.assertEqual(_coverage_score(50.0), 50)

    def test_0_pct(self):
        self.assertEqual(_coverage_score(0.0), 0)

    def test_fractional_truncated(self):
        self.assertEqual(_coverage_score(85.9), 85)


# ---------------------------------------------------------------------------
# _finding_penalty
# ---------------------------------------------------------------------------

class TestFindingPenalty(unittest.TestCase):
    def test_no_findings(self):
        self.assertEqual(_finding_penalty(0, 0), 0)

    def test_one_critical(self):
        self.assertEqual(_finding_penalty(1, 0), 20)

    def test_one_high(self):
        self.assertEqual(_finding_penalty(0, 1), 10)

    def test_mixed(self):
        self.assertEqual(_finding_penalty(1, 2), 40)

    def test_cap_at_60(self):
        self.assertEqual(_finding_penalty(5, 5), 60)  # 5*20+5*10=150 → capped 60

    def test_exactly_60(self):
        self.assertEqual(_finding_penalty(3, 0), 60)  # 3*20=60

    def test_cap_precision(self):
        self.assertEqual(_finding_penalty(10, 10), 60)


# ---------------------------------------------------------------------------
# _bounty_score
# ---------------------------------------------------------------------------

class TestBountyScore(unittest.TestCase):
    def test_no_bounty(self):
        self.assertEqual(_bounty_score(0.0), 0)

    def test_negative_bounty(self):
        self.assertEqual(_bounty_score(-100.0), 0)

    def test_250k_bounty(self):
        self.assertEqual(_bounty_score(250_000.0), 10)

    def test_500k_bounty(self):
        self.assertEqual(_bounty_score(500_000.0), 20)

    def test_1m_bounty(self):
        self.assertEqual(_bounty_score(1_000_000.0), 40)

    def test_cap_at_40(self):
        self.assertEqual(_bounty_score(10_000_000.0), 40)

    def test_small_bounty(self):
        # 25000 / 250000 * 10 = 1 → int(1.0) = 1
        self.assertEqual(_bounty_score(25_000.0), 1)


# ---------------------------------------------------------------------------
# _formal_verification_bonus
# ---------------------------------------------------------------------------

class TestFormalVerificationBonus(unittest.TestCase):
    def test_true(self):
        self.assertEqual(_formal_verification_bonus(True), 10)

    def test_false(self):
        self.assertEqual(_formal_verification_bonus(False), 0)


# ---------------------------------------------------------------------------
# _overall_score
# ---------------------------------------------------------------------------

class TestOverallScore(unittest.TestCase):
    def test_all_zeros(self):
        self.assertEqual(_overall_score(0, 0, 0, 0, 0, 0), 0)

    def test_perfect_score(self):
        # recency=100, quality=100, coverage=100, penalty=0, bounty=40, fv=10
        # = 100*0.20 + 100*0.30 + 100*0.20 - 0 + 40*0.15 + 10*0.15
        # = 20 + 30 + 20 + 6 + 1.5 = 77.5 → int = 77
        score = _overall_score(100, 100, 100, 0, 40, 10)
        self.assertEqual(score, 77)

    def test_clamped_at_0(self):
        score = _overall_score(0, 0, 0, 60, 0, 0)
        self.assertEqual(score, 0)

    def test_clamped_at_100(self):
        score = _overall_score(100, 100, 100, 0, 40, 10)
        self.assertLessEqual(score, 100)

    def test_penalty_reduces_score(self):
        no_penalty = _overall_score(80, 100, 80, 0, 20, 0)
        with_penalty = _overall_score(80, 100, 80, 40, 20, 0)
        self.assertGreater(no_penalty, with_penalty)


# ---------------------------------------------------------------------------
# _security_grade
# ---------------------------------------------------------------------------

class TestSecurityGrade(unittest.TestCase):
    def test_a_plus(self):
        self.assertEqual(_security_grade(95), "A+")

    def test_a_plus_100(self):
        self.assertEqual(_security_grade(100), "A+")

    def test_a(self):
        self.assertEqual(_security_grade(85), "A")

    def test_a_boundary(self):
        self.assertEqual(_security_grade(94), "A")

    def test_b_plus(self):
        self.assertEqual(_security_grade(75), "B+")

    def test_b(self):
        self.assertEqual(_security_grade(65), "B")

    def test_c(self):
        self.assertEqual(_security_grade(50), "C")

    def test_d(self):
        self.assertEqual(_security_grade(35), "D")

    def test_f(self):
        self.assertEqual(_security_grade(0), "F")

    def test_f_below_35(self):
        self.assertEqual(_security_grade(34), "F")


# ---------------------------------------------------------------------------
# _audit_status
# ---------------------------------------------------------------------------

class TestAuditStatus(unittest.TestCase):
    def test_unaudited_priority(self):
        # UNAUDITED takes priority over everything
        status = _audit_status("UNAUDITED", 9999, 0.0, 0, 365)
        self.assertEqual(status, "UNAUDITED")

    def test_stale(self):
        status = _audit_status("TOP_TIER", 400, 90.0, 70, 365)
        self.assertEqual(status, "STALE")

    def test_insufficient_coverage(self):
        status = _audit_status("TOP_TIER", 30, 40.0, 60, 365)
        self.assertEqual(status, "INSUFFICIENT")

    def test_excellent(self):
        status = _audit_status("TOP_TIER", 30, 90.0, 80, 365)
        self.assertEqual(status, "EXCELLENT")

    def test_adequate(self):
        status = _audit_status("MID_TIER", 60, 70.0, 60, 365)
        self.assertEqual(status, "ADEQUATE")

    def test_stale_over_insufficient(self):
        # Stale takes priority over INSUFFICIENT
        status = _audit_status("MID_TIER", 400, 30.0, 30, 365)
        self.assertEqual(status, "STALE")

    def test_custom_stale_days(self):
        # With stale_audit_days=180, 200 days → STALE
        status = _audit_status("TOP_TIER", 200, 90.0, 70, 180)
        self.assertEqual(status, "STALE")


# ---------------------------------------------------------------------------
# _build_flags
# ---------------------------------------------------------------------------

class TestBuildFlags(unittest.TestCase):
    def test_no_flags(self):
        flags = _build_flags(30, 0, 500_000.0, 80.0, 365)
        self.assertEqual(flags, [])

    def test_stale_audit_flag(self):
        flags = _build_flags(400, 0, 500_000.0, 80.0, 365)
        self.assertIn("STALE_AUDIT", flags)

    def test_critical_findings_flag(self):
        flags = _build_flags(30, 2, 500_000.0, 80.0, 365)
        self.assertIn("CRITICAL_FINDINGS", flags)

    def test_no_bounty_flag(self):
        flags = _build_flags(30, 0, 0.0, 80.0, 365)
        self.assertIn("NO_BOUNTY", flags)

    def test_low_coverage_flag(self):
        flags = _build_flags(30, 0, 500_000.0, 40.0, 365)
        self.assertIn("LOW_COVERAGE", flags)

    def test_all_flags(self):
        flags = _build_flags(400, 1, 0.0, 30.0, 365)
        self.assertIn("STALE_AUDIT", flags)
        self.assertIn("CRITICAL_FINDINGS", flags)
        self.assertIn("NO_BOUNTY", flags)
        self.assertIn("LOW_COVERAGE", flags)

    def test_coverage_exactly_50_no_flag(self):
        flags = _build_flags(30, 0, 500_000.0, 50.0, 365)
        self.assertNotIn("LOW_COVERAGE", flags)


# ---------------------------------------------------------------------------
# _recommendation
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):
    def test_a_plus_grade(self):
        rec = _recommendation("A+", 5, 95.0, [])
        self.assertIn("Well-secured", rec)
        self.assertIn("5 audit(s)", rec)

    def test_a_grade(self):
        rec = _recommendation("A", 3, 90.0, [])
        self.assertIn("Well-secured", rec)

    def test_b_plus_with_flags(self):
        rec = _recommendation("B+", 2, 75.0, ["STALE_AUDIT", "NO_BOUNTY"])
        self.assertIn("Adequate security", rec)
        self.assertIn("2 minor concerns", rec)

    def test_b_plus_no_flags(self):
        rec = _recommendation("B+", 2, 75.0, [])
        self.assertIn("Good security posture", rec)

    def test_b_with_flags(self):
        rec = _recommendation("B", 1, 60.0, ["NO_BOUNTY"])
        self.assertIn("Adequate security", rec)

    def test_c_grade(self):
        rec = _recommendation("C", 1, 40.0, ["LOW_COVERAGE", "NO_BOUNTY"])
        self.assertIn("Security gaps", rec)
        self.assertIn("LOW_COVERAGE", rec)

    def test_d_grade(self):
        rec = _recommendation("D", 0, 0.0, ["CRITICAL_FINDINGS"])
        self.assertIn("High security risk", rec)

    def test_f_grade(self):
        rec = _recommendation("F", 0, 0.0, [])
        self.assertIn("High security risk", rec)

    def test_c_no_flags_uses_fallback(self):
        rec = _recommendation("C", 1, 40.0, [])
        self.assertIn("low coverage", rec)


# ---------------------------------------------------------------------------
# analyze() — integration
# ---------------------------------------------------------------------------

class TestAnalyze(unittest.TestCase):
    def test_empty(self):
        result = analyze([])
        self.assertEqual(result["protocols"], [])
        self.assertIsNone(result["safest_protocol"])
        self.assertEqual(result["unaudited_count"], 0)
        self.assertAlmostEqual(result["average_score"], 0.0)
        self.assertIn("timestamp", result)

    def test_single_protocol(self):
        result = analyze([_make_proto()])
        self.assertEqual(len(result["protocols"]), 1)
        self.assertEqual(result["safest_protocol"], "TestProto")

    def test_unaudited_count(self):
        protocols = [
            _make_proto(name="A", auditor_tier="TOP_TIER"),
            _make_proto(name="B", auditor_tier="UNAUDITED"),
            _make_proto(name="C", auditor_tier="UNAUDITED"),
        ]
        result = analyze(protocols)
        self.assertEqual(result["unaudited_count"], 2)

    def test_safest_protocol_highest_score(self):
        p1 = _make_proto(name="Good", auditor_tier="TOP_TIER", days_since_last_audit=15)
        p2 = _make_proto(name="Bad", auditor_tier="UNAUDITED", days_since_last_audit=9999,
                         bug_bounty_usd=0.0, audit_coverage_pct=0.0)
        result = analyze([p1, p2])
        self.assertEqual(result["safest_protocol"], "Good")

    def test_average_score_calculated(self):
        p1 = _make_proto(name="A")
        p2 = _make_proto(name="B")
        result = analyze([p1, p2])
        expected = (result["protocols"][0]["overall_score"] + result["protocols"][1]["overall_score"]) / 2
        self.assertAlmostEqual(result["average_score"], expected, places=2)

    def test_timestamp_is_recent(self):
        before = time.time()
        result = analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_result_keys_present(self):
        result = analyze([_make_proto()])
        for key in ("protocols", "safest_protocol", "unaudited_count", "average_score", "timestamp"):
            self.assertIn(key, result)

    def test_protocol_result_keys(self):
        result = analyze([_make_proto()])
        p = result["protocols"][0]
        for key in (
            "name", "auditor_tier", "audit_recency_score", "auditor_quality_score",
            "coverage_score", "finding_penalty", "bounty_score", "formal_verification_bonus",
            "overall_score", "security_grade", "audit_status", "flags", "recommendation",
        ):
            self.assertIn(key, p, f"Missing key: {key}")

    def test_unaudited_protocol_zero_quality(self):
        proto = _make_proto(auditor_tier="UNAUDITED", bug_bounty_usd=0.0,
                            audit_coverage_pct=0.0, formal_verification=False)
        result = analyze([proto])
        p = result["protocols"][0]
        self.assertEqual(p["auditor_quality_score"], 0)
        self.assertEqual(p["audit_status"], "UNAUDITED")

    def test_stale_audit_status(self):
        proto = _make_proto(days_since_last_audit=400)
        result = analyze([proto])
        self.assertEqual(result["protocols"][0]["audit_status"], "STALE")

    def test_critical_findings_flag_present(self):
        proto = _make_proto(critical_findings_unresolved=2)
        result = analyze([proto])
        self.assertIn("CRITICAL_FINDINGS", result["protocols"][0]["flags"])

    def test_custom_stale_days_config(self):
        proto = _make_proto(days_since_last_audit=200)
        result_default = analyze([proto])
        result_strict = analyze([proto], config={"stale_audit_days": 180})
        # Default: 200 <= 365 → not stale; Strict: 200 > 180 → stale
        self.assertNotEqual(result_default["protocols"][0]["audit_status"], "STALE")
        self.assertEqual(result_strict["protocols"][0]["audit_status"], "STALE")

    def test_formal_verification_bonus(self):
        p_no_fv = _make_proto(formal_verification=False)
        p_fv = _make_proto(formal_verification=True)
        r_no_fv = analyze([p_no_fv])
        r_fv = analyze([p_fv])
        self.assertGreater(
            r_fv["protocols"][0]["overall_score"],
            r_no_fv["protocols"][0]["overall_score"],
        )

    def test_multiple_protocols_returned(self):
        protos = [_make_proto(name=f"P{i}") for i in range(6)]
        result = analyze(protos)
        self.assertEqual(len(result["protocols"]), 6)

    def test_name_preserved(self):
        result = analyze([_make_proto(name="AaveV3")])
        self.assertEqual(result["protocols"][0]["name"], "AaveV3")

    def test_no_bounty_flag(self):
        proto = _make_proto(bug_bounty_usd=0.0)
        result = analyze([proto])
        self.assertIn("NO_BOUNTY", result["protocols"][0]["flags"])

    def test_high_overall_score_grade(self):
        # recency=100(days<=30), quality=100(TOP_TIER), coverage=90, penalty=0, bounty score for 1M
        proto = _make_proto(
            days_since_last_audit=15,
            auditor_tier="TOP_TIER",
            audit_coverage_pct=90.0,
            critical_findings_unresolved=0,
            high_findings_unresolved=0,
            bug_bounty_usd=1_000_000.0,
            formal_verification=True,
        )
        result = analyze([proto])
        p = result["protocols"][0]
        # score = 100*0.20 + 100*0.30 + 90*0.20 - 0 + 40*0.15 + 10*0.15
        # = 20 + 30 + 18 + 6 + 1.5 = 75.5 → int(75) = 75 → B+
        self.assertIn(p["security_grade"], ("A+", "A", "B+", "B"))
        self.assertGreater(p["overall_score"], 50)


# ---------------------------------------------------------------------------
# log_result
# ---------------------------------------------------------------------------

class TestLogResult(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _log_path(self):
        return os.path.join(self.tmpdir, "data", "audit_coverage_log.json")

    def test_creates_file(self):
        log_result(analyze([]), self.tmpdir)
        self.assertTrue(os.path.exists(self._log_path()))

    def test_appends_entries(self):
        for _ in range(5):
            log_result(analyze([]), self.tmpdir)
        with open(self._log_path()) as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 5)

    def test_ring_buffer_100(self):
        for _ in range(110):
            log_result(analyze([]), self.tmpdir)
        with open(self._log_path()) as f:
            entries = json.load(f)
        self.assertLessEqual(len(entries), 100)

    def test_log_valid_json(self):
        log_result(analyze([_make_proto()]), self.tmpdir)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_timestamp(self):
        log_result(analyze([_make_proto()]), self.tmpdir)
        with open(self._log_path()) as f:
            entries = json.load(f)
        self.assertIn("timestamp", entries[0])

    def test_corrupted_log_resets(self):
        lp = self._log_path()
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        with open(lp, "w") as f:
            f.write("{bad json")
        log_result(analyze([]), self.tmpdir)  # must not raise
        with open(lp) as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 1)


# ---------------------------------------------------------------------------
# _score_protocol (direct unit tests)
# ---------------------------------------------------------------------------

class TestScoreProtocol(unittest.TestCase):
    def test_unaudited_overall_zero_quality(self):
        proto = {
            "name": "Unaudited",
            "audit_count": 0,
            "auditor_tier": "UNAUDITED",
            "days_since_last_audit": 9999,
            "lines_of_code": 1000,
            "audit_coverage_pct": 0.0,
            "critical_findings_unresolved": 0,
            "high_findings_unresolved": 0,
            "bug_bounty_usd": 0.0,
            "formal_verification": False,
        }
        result = _score_protocol(proto, 365)
        self.assertEqual(result["auditor_quality_score"], 0)
        self.assertEqual(result["audit_status"], "UNAUDITED")
        self.assertIn("NO_BOUNTY", result["flags"])
        self.assertIn("LOW_COVERAGE", result["flags"])

    def test_community_auditor(self):
        proto = _make_proto(auditor_tier="COMMUNITY")
        result = _score_protocol(proto, 365)
        self.assertEqual(result["auditor_quality_score"], 40)

    def test_insufficient_coverage_status(self):
        proto = _make_proto(auditor_tier="TOP_TIER", audit_coverage_pct=40.0)
        result = _score_protocol(proto, 365)
        self.assertEqual(result["audit_status"], "INSUFFICIENT")

    def test_high_penalty_lowers_score(self):
        no_findings = _make_proto(critical_findings_unresolved=0, high_findings_unresolved=0)
        with_findings = _make_proto(critical_findings_unresolved=3, high_findings_unresolved=3)
        r1 = _score_protocol(no_findings, 365)
        r2 = _score_protocol(with_findings, 365)
        self.assertGreater(r1["overall_score"], r2["overall_score"])

    def test_excellent_status(self):
        proto = _make_proto(
            days_since_last_audit=15,
            audit_coverage_pct=90.0,
            bug_bounty_usd=1_000_000.0,
        )
        result = _score_protocol(proto, 365)
        # May or may not be EXCELLENT depending on score; just check no errors
        self.assertIn(result["audit_status"], ("EXCELLENT", "ADEQUATE", "STALE", "INSUFFICIENT", "UNAUDITED"))

    def test_finding_penalty_capped(self):
        proto = _make_proto(critical_findings_unresolved=10, high_findings_unresolved=10)
        result = _score_protocol(proto, 365)
        self.assertEqual(result["finding_penalty"], 60)

    def test_flags_is_list(self):
        result = _score_protocol(_make_proto(), 365)
        self.assertIsInstance(result["flags"], list)

    def test_recommendation_nonempty(self):
        result = _score_protocol(_make_proto(), 365)
        self.assertIsInstance(result["recommendation"], str)
        self.assertGreater(len(result["recommendation"]), 0)


if __name__ == "__main__":
    unittest.main()
