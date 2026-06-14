"""Unit tests for spa_core.analytics.protocol_risk_scorer (MP-651).

Pure stdlib unittest only — no pytest, no numpy, no external deps.
File I/O tests use tempfile so real data/ is never touched.

Run:
    python3 -m unittest spa_core.tests.test_protocol_risk_scorer -v
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.protocol_risk_scorer import (
    MAX_ENTRIES,
    WEIGHTS,
    ProtocolInput,
    ProtocolRiskScore,
    ProtocolRiskScorer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pristine() -> ProtocolInput:
    """A protocol that should score very highly: grade A, T1."""
    return ProtocolInput(
        protocol_id="pristine",
        tvl_usd=500_000_000,
        audit_count=4,
        age_days=730,
        incident_count=0,
        is_upgradeable=False,
    )


def _make_risky() -> ProtocolInput:
    """A protocol that should score very poorly: grade D, SUSPEND."""
    return ProtocolInput(
        protocol_id="risky",
        tvl_usd=0,
        audit_count=0,
        age_days=10,
        incident_count=3,
        is_upgradeable=True,
    )


def _scorer_with_tmpdir() -> tuple[ProtocolRiskScorer, Path]:
    tmpdir = Path(tempfile.mkdtemp())
    data_file = tmpdir / "data" / "protocol_risk_scores.json"
    scorer = ProtocolRiskScorer(data_file=data_file)
    return scorer, data_file


# ---------------------------------------------------------------------------
# 1. WEIGHTS sum check
# ---------------------------------------------------------------------------

class TestWeights(unittest.TestCase):
    def test_weights_sum_to_one(self):
        total = sum(WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=10)

    def test_weights_all_positive(self):
        for k, v in WEIGHTS.items():
            self.assertGreater(v, 0.0, f"{k} weight must be positive")

    def test_weights_has_five_keys(self):
        self.assertEqual(len(WEIGHTS), 5)


# ---------------------------------------------------------------------------
# 2. _tvl_score
# ---------------------------------------------------------------------------

class TestTvlScore(unittest.TestCase):
    def setUp(self):
        self.s = ProtocolRiskScorer()

    def test_zero_tvl(self):
        self.assertAlmostEqual(self.s._tvl_score(0), 0.0)

    def test_500m_tvl(self):
        self.assertAlmostEqual(self.s._tvl_score(500_000_000), 100.0)

    def test_above_500m_tvl(self):
        self.assertAlmostEqual(self.s._tvl_score(1_000_000_000), 100.0)

    def test_100m_tvl(self):
        self.assertAlmostEqual(self.s._tvl_score(100_000_000), 80.0)

    def test_10m_tvl(self):
        self.assertAlmostEqual(self.s._tvl_score(10_000_000), 60.0)

    def test_1m_tvl(self):
        self.assertAlmostEqual(self.s._tvl_score(1_000_000), 30.0)

    def test_500k_tvl(self):
        # 0.5M: linear 0..30 → 0.5/1.0 * 30 = 15
        self.assertAlmostEqual(self.s._tvl_score(500_000), 15.0)

    def test_50m_tvl_interpolated(self):
        # between 10M and 100M: 60 + 20*(50M-10M)/90M
        expected = 60.0 + 20.0 * (50_000_000 - 10_000_000) / 90_000_000
        self.assertAlmostEqual(self.s._tvl_score(50_000_000), expected, places=6)

    def test_5m_tvl_interpolated(self):
        # between 1M and 10M: 30 + 30*(5M-1M)/9M
        expected = 30.0 + 30.0 * (5_000_000 - 1_000_000) / 9_000_000
        self.assertAlmostEqual(self.s._tvl_score(5_000_000), expected, places=6)

    def test_200m_tvl_interpolated(self):
        # between 100M and 500M: 80 + 20*(200M-100M)/400M
        expected = 80.0 + 20.0 * (200_000_000 - 100_000_000) / 400_000_000
        self.assertAlmostEqual(self.s._tvl_score(200_000_000), expected, places=6)

    def test_300m_tvl_interpolated(self):
        expected = 80.0 + 20.0 * (300_000_000 - 100_000_000) / 400_000_000
        self.assertAlmostEqual(self.s._tvl_score(300_000_000), expected, places=6)

    def test_score_non_negative(self):
        for tvl in [0, 1, 999, 1_000_000, 50_000_000, 500_000_000]:
            self.assertGreaterEqual(self.s._tvl_score(tvl), 0.0)

    def test_score_at_most_100(self):
        for tvl in [0, 10_000_000, 500_000_000, 10_000_000_000]:
            self.assertLessEqual(self.s._tvl_score(tvl), 100.0)


# ---------------------------------------------------------------------------
# 3. _audit_score
# ---------------------------------------------------------------------------

class TestAuditScore(unittest.TestCase):
    def setUp(self):
        self.s = ProtocolRiskScorer()

    def test_zero_audits(self):
        self.assertAlmostEqual(self.s._audit_score(0), 0.0)

    def test_one_audit(self):
        self.assertAlmostEqual(self.s._audit_score(1), 25.0)

    def test_two_audits(self):
        self.assertAlmostEqual(self.s._audit_score(2), 50.0)

    def test_three_audits(self):
        self.assertAlmostEqual(self.s._audit_score(3), 75.0)

    def test_four_audits(self):
        self.assertAlmostEqual(self.s._audit_score(4), 100.0)

    def test_ten_audits(self):
        self.assertAlmostEqual(self.s._audit_score(10), 100.0)

    def test_large_count(self):
        self.assertAlmostEqual(self.s._audit_score(100), 100.0)


# ---------------------------------------------------------------------------
# 4. _age_score
# ---------------------------------------------------------------------------

class TestAgeScore(unittest.TestCase):
    def setUp(self):
        self.s = ProtocolRiskScorer()

    def test_zero_days(self):
        self.assertAlmostEqual(self.s._age_score(0), 0.0)

    def test_30_days(self):
        self.assertAlmostEqual(self.s._age_score(30), 10.0)

    def test_180_days(self):
        self.assertAlmostEqual(self.s._age_score(180), 40.0)

    def test_365_days(self):
        self.assertAlmostEqual(self.s._age_score(365), 70.0)

    def test_730_days(self):
        self.assertAlmostEqual(self.s._age_score(730), 100.0)

    def test_above_730_days(self):
        self.assertAlmostEqual(self.s._age_score(2000), 100.0)

    def test_15_days_interpolated(self):
        # <30d: 15/30 * 10 = 5
        self.assertAlmostEqual(self.s._age_score(15), 5.0)

    def test_90_days_interpolated(self):
        # 30..180: 10 + 30*(90-30)/150 = 10+12 = 22
        expected = 10.0 + 30.0 * (90 - 30) / 150
        self.assertAlmostEqual(self.s._age_score(90), expected, places=6)

    def test_270_days_interpolated(self):
        # 180..365: 40 + 30*(270-180)/185
        expected = 40.0 + 30.0 * (270 - 180) / 185
        self.assertAlmostEqual(self.s._age_score(270), expected, places=6)

    def test_547_days_interpolated(self):
        # 365..730: 70 + 30*(547-365)/365
        expected = 70.0 + 30.0 * (547 - 365) / 365
        self.assertAlmostEqual(self.s._age_score(547), expected, places=6)

    def test_non_negative(self):
        for d in [0, 1, 10, 30, 180, 730, 3000]:
            self.assertGreaterEqual(self.s._age_score(d), 0.0)

    def test_at_most_100(self):
        for d in [0, 365, 730, 10000]:
            self.assertLessEqual(self.s._age_score(d), 100.0)


# ---------------------------------------------------------------------------
# 5. _incident_score
# ---------------------------------------------------------------------------

class TestIncidentScore(unittest.TestCase):
    def setUp(self):
        self.s = ProtocolRiskScorer()

    def test_zero_incidents(self):
        self.assertAlmostEqual(self.s._incident_score(0), 100.0)

    def test_one_incident(self):
        self.assertAlmostEqual(self.s._incident_score(1), 50.0)

    def test_two_incidents(self):
        self.assertAlmostEqual(self.s._incident_score(2), 20.0)

    def test_three_incidents(self):
        self.assertAlmostEqual(self.s._incident_score(3), 0.0)

    def test_many_incidents(self):
        self.assertAlmostEqual(self.s._incident_score(99), 0.0)

    def test_negative_treated_as_zero(self):
        # edge: negative incidents treated as 0
        self.assertAlmostEqual(self.s._incident_score(-1), 100.0)


# ---------------------------------------------------------------------------
# 6. _upgradeability_score
# ---------------------------------------------------------------------------

class TestUpgradeabilityScore(unittest.TestCase):
    def setUp(self):
        self.s = ProtocolRiskScorer()

    def test_upgradeable_true(self):
        self.assertAlmostEqual(self.s._upgradeability_score(True), 40.0)

    def test_upgradeable_false(self):
        self.assertAlmostEqual(self.s._upgradeability_score(False), 80.0)


# ---------------------------------------------------------------------------
# 7. _risk_flags
# ---------------------------------------------------------------------------

class TestRiskFlags(unittest.TestCase):
    def setUp(self):
        self.s = ProtocolRiskScorer()

    def test_no_flags_for_pristine(self):
        p = _make_pristine()
        flags = self.s._risk_flags(p, {})
        self.assertEqual(flags, [])

    def test_low_tvl_flag(self):
        p = ProtocolInput("x", tvl_usd=5_000_000, audit_count=4,
                          age_days=730, incident_count=0, is_upgradeable=False)
        flags = self.s._risk_flags(p, {})
        self.assertIn("LOW_TVL", flags)

    def test_no_audits_flag(self):
        p = ProtocolInput("x", tvl_usd=500_000_000, audit_count=0,
                          age_days=730, incident_count=0, is_upgradeable=False)
        flags = self.s._risk_flags(p, {})
        self.assertIn("NO_AUDITS", flags)

    def test_new_protocol_flag(self):
        p = ProtocolInput("x", tvl_usd=500_000_000, audit_count=4,
                          age_days=179, incident_count=0, is_upgradeable=False)
        flags = self.s._risk_flags(p, {})
        self.assertIn("NEW_PROTOCOL", flags)

    def test_prior_incident_flag(self):
        p = ProtocolInput("x", tvl_usd=500_000_000, audit_count=4,
                          age_days=730, incident_count=1, is_upgradeable=False)
        flags = self.s._risk_flags(p, {})
        self.assertIn("PRIOR_INCIDENT", flags)

    def test_upgradeable_flag(self):
        p = ProtocolInput("x", tvl_usd=500_000_000, audit_count=4,
                          age_days=730, incident_count=0, is_upgradeable=True)
        flags = self.s._risk_flags(p, {})
        self.assertIn("UPGRADEABLE_CONTRACTS", flags)

    def test_all_flags_triggered(self):
        p = _make_risky()
        flags = self.s._risk_flags(p, {})
        self.assertIn("LOW_TVL", flags)
        self.assertIn("NO_AUDITS", flags)
        self.assertIn("NEW_PROTOCOL", flags)
        self.assertIn("PRIOR_INCIDENT", flags)
        self.assertIn("UPGRADEABLE_CONTRACTS", flags)

    def test_exactly_10m_tvl_no_low_tvl_flag(self):
        # Boundary: exactly 10M should NOT trigger LOW_TVL
        p = ProtocolInput("x", tvl_usd=10_000_000, audit_count=4,
                          age_days=730, incident_count=0, is_upgradeable=False)
        flags = self.s._risk_flags(p, {})
        self.assertNotIn("LOW_TVL", flags)

    def test_exactly_180_days_no_new_protocol_flag(self):
        # Boundary: exactly 180d should NOT trigger NEW_PROTOCOL
        p = ProtocolInput("x", tvl_usd=500_000_000, audit_count=4,
                          age_days=180, incident_count=0, is_upgradeable=False)
        flags = self.s._risk_flags(p, {})
        self.assertNotIn("NEW_PROTOCOL", flags)


# ---------------------------------------------------------------------------
# 8. _tier_rec
# ---------------------------------------------------------------------------

class TestTierRec(unittest.TestCase):
    def setUp(self):
        self.s = ProtocolRiskScorer()

    def test_80_is_t1(self):
        self.assertEqual(self.s._tier_rec(80.0), "T1")

    def test_100_is_t1(self):
        self.assertEqual(self.s._tier_rec(100.0), "T1")

    def test_79_is_t2(self):
        self.assertEqual(self.s._tier_rec(79.9), "T2")

    def test_65_is_t2(self):
        self.assertEqual(self.s._tier_rec(65.0), "T2")

    def test_64_is_t3(self):
        self.assertEqual(self.s._tier_rec(64.9), "T3")

    def test_50_is_t3(self):
        self.assertEqual(self.s._tier_rec(50.0), "T3")

    def test_49_is_suspend(self):
        self.assertEqual(self.s._tier_rec(49.9), "SUSPEND")

    def test_0_is_suspend(self):
        self.assertEqual(self.s._tier_rec(0.0), "SUSPEND")


# ---------------------------------------------------------------------------
# 9. Grade thresholds
# ---------------------------------------------------------------------------

class TestGradeThresholds(unittest.TestCase):
    def setUp(self):
        self.s = ProtocolRiskScorer()

    def test_exactly_80_is_A(self):
        self.assertEqual(self.s._grade(80.0), "A")

    def test_100_is_A(self):
        self.assertEqual(self.s._grade(100.0), "A")

    def test_exactly_65_is_B(self):
        self.assertEqual(self.s._grade(65.0), "B")

    def test_79_is_B(self):
        self.assertEqual(self.s._grade(79.9), "B")

    def test_exactly_50_is_C(self):
        self.assertEqual(self.s._grade(50.0), "C")

    def test_64_is_C(self):
        self.assertEqual(self.s._grade(64.9), "C")

    def test_49_is_D(self):
        self.assertEqual(self.s._grade(49.9), "D")

    def test_0_is_D(self):
        self.assertEqual(self.s._grade(0.0), "D")


# ---------------------------------------------------------------------------
# 10. score() full integration
# ---------------------------------------------------------------------------

class TestScore(unittest.TestCase):
    def setUp(self):
        self.s = ProtocolRiskScorer()

    def test_pristine_protocol_grade_A(self):
        result = self.s.score(_make_pristine())
        self.assertEqual(result.grade, "A")

    def test_pristine_protocol_tier_T1(self):
        result = self.s.score(_make_pristine())
        self.assertEqual(result.tier_recommendation, "T1")

    def test_pristine_protocol_no_flags(self):
        result = self.s.score(_make_pristine())
        self.assertEqual(result.risk_flags, [])

    def test_pristine_composite_near_100(self):
        result = self.s.score(_make_pristine())
        # 100*0.25 + 100*0.25 + 100*0.20 + 100*0.20 + 80*0.10 = 98.0
        self.assertAlmostEqual(result.composite_score, 98.0, places=2)

    def test_risky_protocol_grade_D(self):
        result = self.s.score(_make_risky())
        self.assertEqual(result.grade, "D")

    def test_risky_protocol_tier_SUSPEND(self):
        result = self.s.score(_make_risky())
        self.assertEqual(result.tier_recommendation, "SUSPEND")

    def test_risky_protocol_all_flags(self):
        result = self.s.score(_make_risky())
        self.assertIn("LOW_TVL", result.risk_flags)
        self.assertIn("NO_AUDITS", result.risk_flags)
        self.assertIn("NEW_PROTOCOL", result.risk_flags)
        self.assertIn("PRIOR_INCIDENT", result.risk_flags)
        self.assertIn("UPGRADEABLE_CONTRACTS", result.risk_flags)

    def test_result_protocol_id_preserved(self):
        p = ProtocolInput("test_proto", 100_000_000, 2, 365, 0, False)
        result = self.s.score(p)
        self.assertEqual(result.protocol_id, "test_proto")

    def test_composite_weighted_sum_correct(self):
        # Manual check: tvl=100M->80, audits=2->50, age=365->70, inc=1->50, upgr=True->40
        p = ProtocolInput("manual", 100_000_000, 2, 365, 1, True)
        result = self.s.score(p)
        expected = 80*0.25 + 50*0.25 + 70*0.20 + 50*0.20 + 40*0.10
        self.assertAlmostEqual(result.composite_score, round(expected, 4), places=3)

    def test_score_fields_present(self):
        result = self.s.score(_make_pristine())
        self.assertIsInstance(result, ProtocolRiskScore)
        self.assertIsInstance(result.tvl_score, float)
        self.assertIsInstance(result.audit_score, float)
        self.assertIsInstance(result.age_score, float)
        self.assertIsInstance(result.incident_score, float)
        self.assertIsInstance(result.upgradeability_score, float)
        self.assertIsInstance(result.composite_score, float)
        self.assertIsInstance(result.grade, str)
        self.assertIsInstance(result.tier_recommendation, str)
        self.assertIsInstance(result.risk_flags, list)

    def test_composite_score_rounded_to_4dp(self):
        p = ProtocolInput("x", 50_000_000, 2, 270, 1, True)
        result = self.s.score(p)
        # Verify the composite is rounded to 4 decimal places
        as_str = str(result.composite_score)
        if '.' in as_str:
            decimals = len(as_str.split('.')[1])
            self.assertLessEqual(decimals, 4)

    def test_sub_scores_rounded_to_2dp(self):
        p = ProtocolInput("x", 50_000_000, 2, 270, 0, False)
        result = self.s.score(p)
        for val in [result.tvl_score, result.audit_score, result.age_score,
                    result.incident_score, result.upgradeability_score]:
            as_str = str(val)
            if '.' in as_str:
                decimals = len(as_str.split('.')[1])
                self.assertLessEqual(decimals, 2)

    def test_grade_B_protocol(self):
        # composite should land in [65, 80) for grade B
        # tvl=50M->interpolated, audits=2->50, age=365->70, inc=0->100, upgr=True->40
        p = ProtocolInput("gradeB", 50_000_000, 2, 365, 0, True)
        result = self.s.score(p)
        self.assertGreaterEqual(result.composite_score, 65.0)
        self.assertLess(result.composite_score, 80.0)
        self.assertEqual(result.grade, "B")

    def test_grade_C_protocol(self):
        # composite = 60*0.25 + 25*0.25 + 70*0.20 + 100*0.20 + 80*0.10 = 63.25 → C
        p = ProtocolInput("gradeC", 10_000_000, 1, 365, 0, False)
        result = self.s.score(p)
        self.assertGreaterEqual(result.composite_score, 50.0)
        self.assertLess(result.composite_score, 65.0)
        self.assertEqual(result.grade, "C")


# ---------------------------------------------------------------------------
# 11. score_batch()
# ---------------------------------------------------------------------------

class TestScoreBatch(unittest.TestCase):
    def setUp(self):
        self.s = ProtocolRiskScorer()

    def test_empty_batch(self):
        self.assertEqual(self.s.score_batch([]), [])

    def test_single_protocol(self):
        results = self.s.score_batch([_make_pristine()])
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], ProtocolRiskScore)

    def test_multiple_protocols(self):
        protocols = [_make_pristine(), _make_risky(),
                     ProtocolInput("mid", 10_000_000, 2, 365, 0, False)]
        results = self.s.score_batch(protocols)
        self.assertEqual(len(results), 3)

    def test_batch_preserves_ids(self):
        protocols = [
            ProtocolInput("aave", 500_000_000, 4, 730, 0, False),
            ProtocolInput("compound", 200_000_000, 3, 400, 0, True),
        ]
        results = self.s.score_batch(protocols)
        ids = [r.protocol_id for r in results]
        self.assertIn("aave", ids)
        self.assertIn("compound", ids)

    def test_batch_order_preserved(self):
        protocols = [_make_pristine(), _make_risky()]
        results = self.s.score_batch(protocols)
        self.assertEqual(results[0].protocol_id, "pristine")
        self.assertEqual(results[1].protocol_id, "risky")


# ---------------------------------------------------------------------------
# 12. save_scores() + load_history()
# ---------------------------------------------------------------------------

class TestSaveAndLoad(unittest.TestCase):

    def test_load_history_missing_file_returns_empty_list(self):
        scorer, _ = _scorer_with_tmpdir()
        self.assertEqual(scorer.load_history(), [])

    def test_save_creates_file(self):
        scorer, data_file = _scorer_with_tmpdir()
        scorer.save_scores([scorer.score(_make_pristine())])
        self.assertTrue(data_file.exists())

    def test_save_writes_valid_json(self):
        scorer, data_file = _scorer_with_tmpdir()
        scorer.save_scores([scorer.score(_make_pristine())])
        data = json.loads(data_file.read_text())
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_save_entry_fields(self):
        scorer, data_file = _scorer_with_tmpdir()
        scorer.save_scores([scorer.score(_make_pristine())])
        entry = json.loads(data_file.read_text())[0]
        self.assertIn("timestamp", entry)
        self.assertIn("protocol_id", entry)
        self.assertIn("composite_score", entry)
        self.assertIn("grade", entry)
        self.assertIn("tier_recommendation", entry)
        self.assertIn("risk_flags", entry)

    def test_save_appends_multiple_entries(self):
        scorer, data_file = _scorer_with_tmpdir()
        scorer.save_scores([scorer.score(_make_pristine())])
        scorer.save_scores([scorer.score(_make_risky())])
        data = json.loads(data_file.read_text())
        self.assertEqual(len(data), 2)
        ids = [d["protocol_id"] for d in data]
        self.assertIn("pristine", ids)
        self.assertIn("risky", ids)

    def test_ring_buffer_caps_at_max_entries(self):
        scorer, data_file = _scorer_with_tmpdir()
        protocols = [
            ProtocolInput(f"proto_{i}", 500_000_000, 4, 730, 0, False)
            for i in range(MAX_ENTRIES + 20)
        ]
        # Save in batches
        for p in protocols:
            scorer.save_scores([scorer.score(p)])
        data = json.loads(data_file.read_text())
        self.assertLessEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        scorer, data_file = _scorer_with_tmpdir()
        # Fill beyond capacity
        for i in range(MAX_ENTRIES + 5):
            p = ProtocolInput(f"p{i}", 500_000_000, 4, 730, 0, False)
            scorer.save_scores([scorer.score(p)])
        data = json.loads(data_file.read_text())
        # Last entry should be p(MAX_ENTRIES+4)
        self.assertEqual(data[-1]["protocol_id"], f"p{MAX_ENTRIES + 4}")

    def test_atomic_write_no_tmp_file_left(self):
        scorer, data_file = _scorer_with_tmpdir()
        scorer.save_scores([scorer.score(_make_pristine())])
        tmp = data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_load_history_returns_list(self):
        scorer, data_file = _scorer_with_tmpdir()
        scorer.save_scores([scorer.score(_make_pristine())])
        history = scorer.load_history()
        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 1)

    def test_save_batch_multiple_scores_single_call(self):
        scorer, data_file = _scorer_with_tmpdir()
        scores = scorer.score_batch([_make_pristine(), _make_risky()])
        scorer.save_scores(scores)
        data = json.loads(data_file.read_text())
        self.assertEqual(len(data), 2)

    def test_save_creates_parent_dirs(self):
        tmpdir = Path(tempfile.mkdtemp())
        # Nested path that doesn't exist
        data_file = tmpdir / "nested" / "sub" / "scores.json"
        scorer = ProtocolRiskScorer(data_file=data_file)
        scorer.save_scores([scorer.score(_make_pristine())])
        self.assertTrue(data_file.exists())


# ---------------------------------------------------------------------------
# 13. Grade + tier boundary edge cases (exact thresholds)
# ---------------------------------------------------------------------------

class TestGradeBoundaries(unittest.TestCase):
    """Verify grade/tier is assigned correctly at exact threshold values."""

    def setUp(self):
        self.s = ProtocolRiskScorer()

    def test_exactly_80_grade_A_tier_T1(self):
        self.assertEqual(self.s._grade(80.0), "A")
        self.assertEqual(self.s._tier_rec(80.0), "T1")

    def test_just_below_80_grade_B(self):
        self.assertEqual(self.s._grade(79.9999), "B")

    def test_exactly_65_grade_B_tier_T2(self):
        self.assertEqual(self.s._grade(65.0), "B")
        self.assertEqual(self.s._tier_rec(65.0), "T2")

    def test_just_below_65_grade_C(self):
        self.assertEqual(self.s._grade(64.9999), "C")

    def test_exactly_50_grade_C_tier_T3(self):
        self.assertEqual(self.s._grade(50.0), "C")
        self.assertEqual(self.s._tier_rec(50.0), "T3")

    def test_just_below_50_grade_D_tier_SUSPEND(self):
        self.assertEqual(self.s._grade(49.9999), "D")
        self.assertEqual(self.s._tier_rec(49.9999), "SUSPEND")


if __name__ == "__main__":
    unittest.main()
