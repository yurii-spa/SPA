"""
Tests for MP-838 ProtocolSecurityAuditTracker
≥65 unittest tests covering all scoring components, edge-cases, and flags.
Run: python3 -m unittest spa_core.tests.test_protocol_security_audit_tracker -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.protocol_security_audit_tracker import (
    DEFAULT_STALE_AUDIT_DAYS,
    FRESHNESS_FRESH,
    FRESHNESS_RECENT,
    FRESHNESS_STALE,
    FRESHNESS_UNAUDITED,
    RISK_SAFE,
    RISK_CAUTION,
    RISK_RISKY,
    RISK_AVOID,
    _compute_audit_volume_score,
    _compute_freshness,
    _compute_coverage_score,
    _compute_open_findings,
    _compute_findings_penalty,
    _compute_bonus_score,
    _compute_change_penalty,
    _score_to_grade,
    _grade_to_risk,
    _compute_flags,
    analyze,
    append_log,
)
from datetime import date


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

TODAY_STR = "2025-06-01"
TODAY = date(2025, 6, 1)

FRESH_DATE = "2025-04-01"       # ~61 days ago — within half of 365 = 182 days → FRESH
RECENT_DATE = "2024-11-01"      # ~212 days ago — within 365 days, past half → RECENT
STALE_DATE = "2023-01-01"       # >365 days → STALE


def _audit(
    auditor="Trail of Bits",
    date_str=FRESH_DATE,
    scope_pct=90.0,
    critical_findings=0,
    high_findings=0,
    resolved_pct=100.0,
) -> dict:
    return {
        "auditor": auditor,
        "date": date_str,
        "scope_pct": scope_pct,
        "critical_findings": critical_findings,
        "high_findings": high_findings,
        "resolved_pct": resolved_pct,
    }


def _proto(
    name="TestProto",
    audits=None,
    days_since_major_change=30,
    bug_bounty_usd=0.0,
    formal_verification=False,
) -> dict:
    if audits is None:
        audits = [_audit()]
    return {
        "name": name,
        "audits": audits,
        "days_since_major_change": days_since_major_change,
        "bug_bounty_usd": bug_bounty_usd,
        "formal_verification": formal_verification,
    }


def _cfg(today=TODAY_STR, stale=DEFAULT_STALE_AUDIT_DAYS) -> dict:
    return {"today": today, "stale_audit_days": stale}


# ===========================================================================
# 1. _compute_audit_volume_score
# ===========================================================================

class TestAuditVolumeScore(unittest.TestCase):

    def test_zero_audits(self):
        self.assertEqual(_compute_audit_volume_score(0), 0)

    def test_one_audit(self):
        self.assertEqual(_compute_audit_volume_score(1), 5)

    def test_two_audits(self):
        self.assertEqual(_compute_audit_volume_score(2), 10)

    def test_three_audits(self):
        self.assertEqual(_compute_audit_volume_score(3), 15)

    def test_four_audits(self):
        self.assertEqual(_compute_audit_volume_score(4), 20)

    def test_many_audits(self):
        self.assertEqual(_compute_audit_volume_score(10), 20)

    def test_score_non_negative(self):
        self.assertGreaterEqual(_compute_audit_volume_score(0), 0)


# ===========================================================================
# 2. _compute_freshness
# ===========================================================================

class TestComputeFreshness(unittest.TestCase):

    def test_no_audits_unaudited(self):
        label, score, days = _compute_freshness([], 365, TODAY)
        self.assertEqual(label, FRESHNESS_UNAUDITED)
        self.assertEqual(score, 0)
        self.assertIsNone(days)

    def test_fresh_audit(self):
        audits = [_audit(date_str=FRESH_DATE)]
        label, score, days = _compute_freshness(audits, 365, TODAY)
        self.assertEqual(label, FRESHNESS_FRESH)
        self.assertEqual(score, 25)
        self.assertIsNotNone(days)

    def test_recent_audit(self):
        audits = [_audit(date_str=RECENT_DATE)]
        label, score, days = _compute_freshness(audits, 365, TODAY)
        self.assertEqual(label, FRESHNESS_RECENT)
        self.assertEqual(score, 15)

    def test_stale_audit(self):
        audits = [_audit(date_str=STALE_DATE)]
        label, score, days = _compute_freshness(audits, 365, TODAY)
        self.assertEqual(label, FRESHNESS_STALE)
        self.assertEqual(score, 5)

    def test_uses_latest_audit_date(self):
        audits = [_audit(date_str=STALE_DATE), _audit(date_str=FRESH_DATE)]
        label, score, days = _compute_freshness(audits, 365, TODAY)
        self.assertEqual(label, FRESHNESS_FRESH)

    def test_custom_stale_days(self):
        # stale=30 → half=15; FRESH_DATE is ~61 days ago → not fresh → RECENT or STALE
        audits = [_audit(date_str=FRESH_DATE)]
        label, score, days = _compute_freshness(audits, 30, TODAY)
        self.assertIn(label, (FRESHNESS_RECENT, FRESHNESS_STALE))

    def test_days_since_latest_correct(self):
        audits = [_audit(date_str="2025-05-01")]
        label, score, days = _compute_freshness(audits, 365, TODAY)
        self.assertEqual(days, 31)  # May 1 to June 1 = 31 days


# ===========================================================================
# 3. _compute_coverage_score
# ===========================================================================

class TestCoverageScore(unittest.TestCase):

    def test_no_audits(self):
        self.assertAlmostEqual(_compute_coverage_score([]), 0.0)

    def test_full_coverage(self):
        audits = [_audit(scope_pct=100.0)]
        self.assertAlmostEqual(_compute_coverage_score(audits), 20.0)

    def test_half_coverage(self):
        audits = [_audit(scope_pct=50.0)]
        self.assertAlmostEqual(_compute_coverage_score(audits), 10.0)

    def test_mean_coverage(self):
        audits = [_audit(scope_pct=80.0), _audit(scope_pct=60.0)]
        # mean = 70, score = 70 * 0.20 = 14
        self.assertAlmostEqual(_compute_coverage_score(audits), 14.0)

    def test_zero_coverage(self):
        audits = [_audit(scope_pct=0.0)]
        self.assertAlmostEqual(_compute_coverage_score(audits), 0.0)

    def test_max_score_is_20(self):
        audits = [_audit(scope_pct=100.0)] * 5
        self.assertAlmostEqual(_compute_coverage_score(audits), 20.0)


# ===========================================================================
# 4. _compute_open_findings
# ===========================================================================

class TestOpenFindings(unittest.TestCase):

    def test_no_audits(self):
        c, h = _compute_open_findings([])
        self.assertEqual(c, 0)
        self.assertEqual(h, 0)

    def test_all_resolved(self):
        audits = [_audit(critical_findings=5, high_findings=3, resolved_pct=100.0)]
        c, h = _compute_open_findings(audits)
        self.assertEqual(c, 0)
        self.assertEqual(h, 0)

    def test_none_resolved(self):
        audits = [_audit(critical_findings=2, high_findings=4, resolved_pct=0.0)]
        c, h = _compute_open_findings(audits)
        self.assertEqual(c, 2)
        self.assertEqual(h, 4)

    def test_half_resolved_ceil(self):
        # 3 critical, 50% resolved → ceil(3 * 0.5) = ceil(1.5) = 2
        audits = [_audit(critical_findings=3, high_findings=0, resolved_pct=50.0)]
        c, h = _compute_open_findings(audits)
        self.assertEqual(c, 2)

    def test_accumulates_across_audits(self):
        audits = [
            _audit(critical_findings=1, high_findings=0, resolved_pct=0.0),
            _audit(critical_findings=2, high_findings=1, resolved_pct=0.0),
        ]
        c, h = _compute_open_findings(audits)
        self.assertEqual(c, 3)
        self.assertEqual(h, 1)

    def test_partial_resolution(self):
        # 4 high, 75% resolved → ceil(4 * 0.25) = ceil(1.0) = 1
        audits = [_audit(critical_findings=0, high_findings=4, resolved_pct=75.0)]
        c, h = _compute_open_findings(audits)
        self.assertEqual(h, 1)

    def test_full_resolution_mixed(self):
        audits = [_audit(critical_findings=3, high_findings=5, resolved_pct=100.0)]
        c, h = _compute_open_findings(audits)
        self.assertEqual(c, 0)
        self.assertEqual(h, 0)


# ===========================================================================
# 5. _compute_findings_penalty
# ===========================================================================

class TestFindingsPenalty(unittest.TestCase):

    def test_no_findings(self):
        self.assertEqual(_compute_findings_penalty(0, 0), 0)

    def test_one_critical(self):
        self.assertEqual(_compute_findings_penalty(1, 0), 8)

    def test_one_high(self):
        self.assertEqual(_compute_findings_penalty(0, 1), 4)

    def test_critical_cap_at_5(self):
        # 6 critical → min(48, 40) = 40
        self.assertEqual(_compute_findings_penalty(6, 0), 40)

    def test_high_cap_at_5(self):
        # 6 high → min(24, 20) = 20
        self.assertEqual(_compute_findings_penalty(0, 6), 20)

    def test_both_uncapped(self):
        self.assertEqual(_compute_findings_penalty(2, 2), 2*8 + 2*4)

    def test_both_capped(self):
        self.assertEqual(_compute_findings_penalty(10, 10), 40 + 20)

    def test_critical_exactly_5(self):
        # 5 * 8 = 40 → at cap
        self.assertEqual(_compute_findings_penalty(5, 0), 40)

    def test_high_exactly_5(self):
        # 5 * 4 = 20 → at cap
        self.assertEqual(_compute_findings_penalty(0, 5), 20)


# ===========================================================================
# 6. _compute_bonus_score
# ===========================================================================

class TestBonusScore(unittest.TestCase):

    def test_no_bonus(self):
        self.assertEqual(_compute_bonus_score(False, 0.0), 0)

    def test_formal_verification_only(self):
        self.assertEqual(_compute_bonus_score(True, 0.0), 10)

    def test_small_bounty(self):
        self.assertEqual(_compute_bonus_score(False, 50_000.0), 1)

    def test_medium_bounty(self):
        self.assertEqual(_compute_bonus_score(False, 100_000.0), 3)

    def test_large_bounty(self):
        self.assertEqual(_compute_bonus_score(False, 1_000_000.0), 5)

    def test_formal_plus_large_bounty(self):
        self.assertEqual(_compute_bonus_score(True, 1_000_000.0), 15)

    def test_formal_plus_medium_bounty(self):
        self.assertEqual(_compute_bonus_score(True, 100_000.0), 13)

    def test_formal_plus_small_bounty(self):
        self.assertEqual(_compute_bonus_score(True, 1.0), 11)

    def test_bounty_just_below_100k(self):
        self.assertEqual(_compute_bonus_score(False, 99_999.0), 1)

    def test_bounty_exactly_1m(self):
        self.assertEqual(_compute_bonus_score(False, 1_000_000.0), 5)


# ===========================================================================
# 7. _compute_change_penalty
# ===========================================================================

class TestChangePenalty(unittest.TestCase):

    def test_no_penalty(self):
        self.assertEqual(_compute_change_penalty(30, 365), 0)

    def test_moderate_penalty(self):
        # > 365 but <= 730 → -5
        self.assertEqual(_compute_change_penalty(400, 365), 5)

    def test_severe_penalty(self):
        # > 730 → -10
        self.assertEqual(_compute_change_penalty(800, 365), 10)

    def test_exactly_stale(self):
        # == stale_days → not > → no penalty
        self.assertEqual(_compute_change_penalty(365, 365), 0)

    def test_one_over_stale(self):
        self.assertEqual(_compute_change_penalty(366, 365), 5)

    def test_exactly_double_stale(self):
        # == 730 → not > 730 → moderate penalty
        self.assertEqual(_compute_change_penalty(730, 365), 5)

    def test_one_over_double(self):
        self.assertEqual(_compute_change_penalty(731, 365), 10)


# ===========================================================================
# 8. _score_to_grade and _grade_to_risk
# ===========================================================================

class TestGradeAndRisk(unittest.TestCase):

    def test_grade_A(self):
        self.assertEqual(_score_to_grade(80), "A")
        self.assertEqual(_score_to_grade(100), "A")

    def test_grade_B(self):
        self.assertEqual(_score_to_grade(60), "B")
        self.assertEqual(_score_to_grade(79), "B")

    def test_grade_C(self):
        self.assertEqual(_score_to_grade(40), "C")
        self.assertEqual(_score_to_grade(59), "C")

    def test_grade_D(self):
        self.assertEqual(_score_to_grade(20), "D")
        self.assertEqual(_score_to_grade(39), "D")

    def test_grade_F(self):
        self.assertEqual(_score_to_grade(0), "F")
        self.assertEqual(_score_to_grade(19), "F")

    def test_risk_safe_A(self):
        self.assertEqual(_grade_to_risk("A"), RISK_SAFE)

    def test_risk_safe_B(self):
        self.assertEqual(_grade_to_risk("B"), RISK_SAFE)

    def test_risk_caution_C(self):
        self.assertEqual(_grade_to_risk("C"), RISK_CAUTION)

    def test_risk_risky_D(self):
        self.assertEqual(_grade_to_risk("D"), RISK_RISKY)

    def test_risk_avoid_F(self):
        self.assertEqual(_grade_to_risk("F"), RISK_AVOID)


# ===========================================================================
# 9. _compute_flags
# ===========================================================================

class TestComputeFlags(unittest.TestCase):

    def _flags(self, audit_count=1, freshness=FRESHNESS_FRESH, open_c=0, open_h=0,
               bounty=0.0, days_change=30, stale=365):
        return _compute_flags(audit_count, freshness, open_c, open_h, bounty, days_change, stale)

    def test_no_audits_flag(self):
        flags = self._flags(audit_count=0)
        self.assertIn("No security audits", flags)

    def test_stale_flag(self):
        flags = self._flags(freshness=FRESHNESS_STALE)
        self.assertTrue(any("stale" in f.lower() for f in flags))

    def test_critical_finding_flag(self):
        flags = self._flags(open_c=2)
        self.assertTrue(any("critical" in f for f in flags))

    def test_high_finding_flag(self):
        flags = self._flags(open_h=3)
        self.assertTrue(any("high-severity" in f for f in flags))

    def test_no_bounty_flag(self):
        flags = self._flags(bounty=0.0)
        self.assertIn("No bug bounty program", flags)

    def test_major_code_change_flag(self):
        flags = self._flags(days_change=400, stale=365)
        self.assertTrue(any("Major code changes" in f for f in flags))

    def test_no_flags_on_clean_protocol(self):
        flags = self._flags(
            audit_count=3, freshness=FRESHNESS_FRESH,
            open_c=0, open_h=0, bounty=500_000.0, days_change=30
        )
        self.assertEqual(len(flags), 0)

    def test_critical_count_in_flag_text(self):
        flags = self._flags(open_c=3)
        matching = [f for f in flags if "3 unresolved critical" in f]
        self.assertEqual(len(matching), 1)

    def test_high_count_in_flag_text(self):
        flags = self._flags(open_h=5)
        matching = [f for f in flags if "5 unresolved high-severity" in f]
        self.assertEqual(len(matching), 1)


# ===========================================================================
# 10. analyze() top-level tests
# ===========================================================================

class TestAnalyze(unittest.TestCase):

    def _cfg(self):
        return _cfg()

    def test_empty_protocols(self):
        r = analyze([])
        self.assertEqual(r["protocols"], [])
        self.assertIsNone(r["best_security"])
        self.assertIsNone(r["riskiest_protocol"])
        self.assertEqual(r["unaudited_count"], 0)
        self.assertEqual(r["avoid_count"], 0)
        self.assertAlmostEqual(r["average_security_score"], 0.0)

    def test_empty_has_timestamp(self):
        r = analyze([])
        self.assertIn("timestamp", r)

    def test_single_protocol_structure(self):
        r = analyze([_proto()], self._cfg())
        self.assertEqual(len(r["protocols"]), 1)
        p = r["protocols"][0]
        for key in ("name", "audit_count", "security_score", "security_grade",
                    "audit_freshness", "open_critical_count", "open_high_count",
                    "risk_label", "flags"):
            self.assertIn(key, p)

    def test_unaudited_protocol(self):
        r = analyze([_proto(audits=[])], self._cfg())
        self.assertEqual(r["protocols"][0]["audit_freshness"], FRESHNESS_UNAUDITED)
        self.assertEqual(r["unaudited_count"], 1)

    def test_unaudited_has_no_audit_flag(self):
        r = analyze([_proto(audits=[])], self._cfg())
        flags = r["protocols"][0]["flags"]
        self.assertIn("No security audits", flags)

    def test_avoid_count_f_grade(self):
        # Unaudited + no bounty + high findings = very low score → F → AVOID
        proto = _proto(
            audits=[_audit(critical_findings=5, high_findings=5, resolved_pct=0.0,
                           date_str=STALE_DATE, scope_pct=10.0)],
            bug_bounty_usd=0.0,
            days_since_major_change=800,
        )
        r = analyze([proto], self._cfg())
        p = r["protocols"][0]
        # Score should be low
        self.assertIn(p["risk_label"], (RISK_AVOID, RISK_RISKY))

    def test_best_security_name(self):
        p1 = _proto(name="Good", formal_verification=True, bug_bounty_usd=2_000_000.0,
                    audits=[_audit(scope_pct=100.0)] * 4)
        p2 = _proto(name="Bad", audits=[])
        r = analyze([p1, p2], self._cfg())
        self.assertEqual(r["best_security"], "Good")

    def test_riskiest_protocol_name(self):
        p1 = _proto(name="Good", formal_verification=True, bug_bounty_usd=2_000_000.0,
                    audits=[_audit(scope_pct=100.0)] * 4)
        p2 = _proto(name="Bad", audits=[])
        r = analyze([p1, p2], self._cfg())
        self.assertEqual(r["riskiest_protocol"], "Bad")

    def test_average_security_score(self):
        p1 = _proto(name="A", audits=[_audit()])
        p2 = _proto(name="B", audits=[_audit()])
        r = analyze([p1, p2], self._cfg())
        score1 = r["protocols"][0]["security_score"]
        score2 = r["protocols"][1]["security_score"]
        expected_avg = (score1 + score2) / 2
        self.assertAlmostEqual(r["average_security_score"], expected_avg)

    def test_score_clamped_0_100(self):
        # Clean protocol with everything perfect
        p = _proto(
            formal_verification=True,
            bug_bounty_usd=2_000_000.0,
            audits=[_audit(scope_pct=100.0)] * 5,
        )
        r = analyze([p], self._cfg())
        score = r["protocols"][0]["security_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_fresh_audit_gets_fresh_label(self):
        p = _proto(audits=[_audit(date_str=FRESH_DATE)])
        r = analyze([p], _cfg())
        self.assertEqual(r["protocols"][0]["audit_freshness"], FRESHNESS_FRESH)

    def test_stale_audit_gets_stale_label(self):
        p = _proto(audits=[_audit(date_str=STALE_DATE)])
        r = analyze([p], _cfg())
        self.assertEqual(r["protocols"][0]["audit_freshness"], FRESHNESS_STALE)

    def test_open_critical_counted(self):
        p = _proto(audits=[_audit(critical_findings=3, resolved_pct=0.0)])
        r = analyze([p], self._cfg())
        self.assertEqual(r["protocols"][0]["open_critical_count"], 3)

    def test_open_high_counted(self):
        p = _proto(audits=[_audit(high_findings=4, resolved_pct=0.0)])
        r = analyze([p], self._cfg())
        self.assertEqual(r["protocols"][0]["open_high_count"], 4)

    def test_formal_verification_boosts_score(self):
        p_no_fv = _proto(audits=[_audit()], formal_verification=False)
        p_fv = _proto(audits=[_audit()], formal_verification=True)
        r_no = analyze([p_no_fv], self._cfg())
        r_yes = analyze([p_fv], self._cfg())
        self.assertGreater(r_yes["protocols"][0]["security_score"],
                           r_no["protocols"][0]["security_score"])

    def test_bug_bounty_boosts_score(self):
        p_no = _proto(audits=[_audit()], bug_bounty_usd=0.0)
        p_yes = _proto(audits=[_audit()], bug_bounty_usd=1_000_000.0)
        r_no = analyze([p_no], self._cfg())
        r_yes = analyze([p_yes], self._cfg())
        self.assertGreater(r_yes["protocols"][0]["security_score"],
                           r_no["protocols"][0]["security_score"])

    def test_unaudited_count_multiple(self):
        protos = [_proto(audits=[]), _proto(audits=[]), _proto(audits=[_audit()])]
        r = analyze(protos, self._cfg())
        self.assertEqual(r["unaudited_count"], 2)

    def test_grade_A_is_safe(self):
        p = _proto(
            formal_verification=True,
            bug_bounty_usd=2_000_000.0,
            audits=[_audit(scope_pct=100.0)] * 4,
        )
        r = analyze([p], self._cfg())
        result_p = r["protocols"][0]
        if result_p["security_grade"] == "A":
            self.assertEqual(result_p["risk_label"], RISK_SAFE)

    def test_no_config_uses_defaults(self):
        r = analyze([_proto()], config=None)
        self.assertIn("protocols", r)

    def test_timestamp_is_float(self):
        r = analyze([_proto()], self._cfg())
        self.assertIsInstance(r["timestamp"], float)

    def test_multiple_audits_freshness_uses_latest(self):
        p = _proto(audits=[
            _audit(date_str=STALE_DATE),
            _audit(date_str=FRESH_DATE),
        ])
        r = analyze([p], self._cfg())
        self.assertEqual(r["protocols"][0]["audit_freshness"], FRESHNESS_FRESH)

    def test_audit_count_correct(self):
        p = _proto(audits=[_audit(), _audit(), _audit()])
        r = analyze([p], self._cfg())
        self.assertEqual(r["protocols"][0]["audit_count"], 3)

    def test_findings_penalty_reduces_score(self):
        p_clean = _proto(audits=[_audit(critical_findings=0, high_findings=0, resolved_pct=100.0)])
        p_dirty = _proto(audits=[_audit(critical_findings=3, high_findings=3, resolved_pct=0.0)])
        r_clean = analyze([p_clean], self._cfg())
        r_dirty = analyze([p_dirty], self._cfg())
        self.assertGreater(r_clean["protocols"][0]["security_score"],
                           r_dirty["protocols"][0]["security_score"])

    def test_score_is_integer(self):
        r = analyze([_proto()], self._cfg())
        self.assertIsInstance(r["protocols"][0]["security_score"], int)

    def test_flags_is_list(self):
        r = analyze([_proto()], self._cfg())
        self.assertIsInstance(r["protocols"][0]["flags"], list)


# ===========================================================================
# 11. append_log ring-buffer tests
# ===========================================================================

class TestAppendLog(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._log_path = Path(self._tmpdir) / "security_audit_log.json"

    def _read_log(self) -> list:
        with open(self._log_path) as f:
            return json.load(f)

    def test_creates_log_file(self):
        append_log({"x": 1}, self._log_path)
        self.assertTrue(self._log_path.exists())

    def test_initial_is_list(self):
        append_log({"x": 1}, self._log_path)
        self.assertIsInstance(self._read_log(), list)

    def test_one_entry(self):
        append_log({"a": 1}, self._log_path)
        log = self._read_log()
        self.assertEqual(len(log), 1)

    def test_ring_buffer_cap_100(self):
        for i in range(115):
            append_log({"i": i}, self._log_path)
        log = self._read_log()
        self.assertEqual(len(log), 100)

    def test_ring_buffer_newest_kept(self):
        for i in range(110):
            append_log({"i": i}, self._log_path)
        log = self._read_log()
        self.assertEqual(log[0]["i"], 10)
        self.assertEqual(log[-1]["i"], 109)

    def test_atomic_no_tmp_left(self):
        append_log({"x": 1}, self._log_path)
        remaining = [f for f in os.listdir(self._tmpdir) if f.endswith(".tmp")]
        self.assertEqual(len(remaining), 0)

    def test_valid_json_output(self):
        append_log({"k": "v"}, self._log_path)
        data = json.loads(self._log_path.read_text())
        self.assertIsInstance(data, list)

    def test_corrupted_log_reset(self):
        self._log_path.write_text("BAD_JSON")
        append_log({"safe": True}, self._log_path)
        log = self._read_log()
        self.assertEqual(len(log), 1)

    def test_nested_data_preserved(self):
        r = analyze([_proto()], _cfg())
        append_log(r, self._log_path)
        log = self._read_log()
        self.assertIn("protocols", log[0])

    def test_creates_parent_dirs(self):
        deep = Path(self._tmpdir) / "a" / "b" / "security_audit_log.json"
        append_log({"x": 1}, deep)
        self.assertTrue(deep.exists())


# ===========================================================================
# 12. Constants
# ===========================================================================

class TestConstants(unittest.TestCase):

    def test_default_stale_days(self):
        self.assertEqual(DEFAULT_STALE_AUDIT_DAYS, 365)

    def test_freshness_labels_unique(self):
        labels = {FRESHNESS_FRESH, FRESHNESS_RECENT, FRESHNESS_STALE, FRESHNESS_UNAUDITED}
        self.assertEqual(len(labels), 4)

    def test_risk_labels_unique(self):
        labels = {RISK_SAFE, RISK_CAUTION, RISK_RISKY, RISK_AVOID}
        self.assertEqual(len(labels), 4)


if __name__ == "__main__":
    unittest.main()
