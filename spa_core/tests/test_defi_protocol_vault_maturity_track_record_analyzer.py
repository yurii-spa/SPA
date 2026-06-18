"""
Tests for MP-1171: DeFiProtocolVaultMaturityTrackRecordAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_maturity_track_record_analyzer -v
"""

import json
import math
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_vault_maturity_track_record_analyzer import (
    DeFiProtocolVaultMaturityTrackRecordAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _maturity_label,
    _demo_positions,
    AGE_FULL_DAYS,
    EPOCHS_FULL,
    AUDIT_COUNT_FULL,
    DAYS_PER_MONTH,
    BRAND_NEW_AGE_DAYS,
    UNPROVEN_EPOCHS,
    EMERGING_AGE_DAYS,
    EMERGING_EPOCHS,
    ESTABLISHED_AGE_DAYS,
    ESTABLISHED_EPOCHS,
    SEASONED_AGE_DAYS,
    SEASONED_EPOCHS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    vault_age_days=200.0,
    epochs_completed=15.0,
    is_audited=True,
    audit_count=2,
    survived_stress_event=True,
):
    return {
        "vault": vault,
        "vault_age_days": vault_age_days,
        "epochs_completed": epochs_completed,
        "is_audited": is_audited,
        "audit_count": audit_count,
        "survived_stress_event": survived_stress_event,
    }


def A():
    return DeFiProtocolVaultMaturityTrackRecordAnalyzer()


def finite_check(testcase, result):
    for v in result.values():
        if isinstance(v, float):
            testcase.assertTrue(math.isfinite(v), f"non-finite: {v}")


# ── helper-function tests ─────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):
    def test_f_valid(self):
        self.assertEqual(_f("3.5"), 3.5)
        self.assertEqual(_f(7), 7.0)

    def test_f_none_default(self):
        self.assertEqual(_f(None), 0.0)
        self.assertEqual(_f(None, 9.0), 9.0)

    def test_f_bad_value(self):
        self.assertEqual(_f("abc"), 0.0)
        self.assertEqual(_f([], 1.0), 1.0)

    def test_f_negative(self):
        self.assertEqual(_f("-5"), -5.0)

    def test_f_int_zero(self):
        self.assertEqual(_f(0), 0.0)

    def test_f_dict_default(self):
        self.assertEqual(_f({}, 2.0), 2.0)

    def test_f_default_used_for_none(self):
        self.assertEqual(_f(None, 3.0), 3.0)

    def test_clamp_within(self):
        self.assertEqual(_clamp(5, 0, 10), 5)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1, 0, 10), 0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(11, 0, 10), 10)

    def test_clamp_exact_bounds(self):
        self.assertEqual(_clamp(0, 0, 10), 0)
        self.assertEqual(_clamp(10, 0, 10), 10)

    def test_clamp_unit_interval(self):
        self.assertEqual(_clamp(1.5, 0.0, 1.0), 1.0)
        self.assertEqual(_clamp(-0.2, 0.0, 1.0), 0.0)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertAlmostEqual(_mean([2, 4, 6]), 4.0)

    def test_mean_single(self):
        self.assertAlmostEqual(_mean([8.0]), 8.0)

    def test_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(10, 2, 1e9), 5.0)

    def test_safe_div_zero_denominator(self):
        self.assertEqual(_safe_div(10, 0, 1e9), 1e9)

    def test_safe_div_negative_denominator(self):
        self.assertEqual(_safe_div(10, -5, 7.0), 7.0)

    def test_safe_div_none_sentinel(self):
        self.assertIsNone(_safe_div(10, 0, None))

    def test_safe_div_zero_sentinel(self):
        self.assertEqual(_safe_div(5, 0, 0.0), 0.0)

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)
        self.assertEqual(cfg["log_path"], LOG_PATH)

    def test_build_default_cfg_none(self):
        cfg = _build_default_cfg(None)
        self.assertIn("log_path", cfg)

    def test_build_default_cfg_extra_key(self):
        cfg = _build_default_cfg({"extra": 1})
        self.assertEqual(cfg["extra"], 1)

    def test_grade_from_score_bands(self):
        self.assertEqual(_grade_from_score(90), "A")
        self.assertEqual(_grade_from_score(72), "B")
        self.assertEqual(_grade_from_score(60), "C")
        self.assertEqual(_grade_from_score(45), "D")
        self.assertEqual(_grade_from_score(10), "F")

    def test_grade_boundaries(self):
        self.assertEqual(_grade_from_score(85), "A")
        self.assertEqual(_grade_from_score(70), "B")
        self.assertEqual(_grade_from_score(55), "C")
        self.assertEqual(_grade_from_score(40), "D")
        self.assertEqual(_grade_from_score(39.9), "F")

    def test_grade_zero(self):
        self.assertEqual(_grade_from_score(0.0), "F")

    def test_grade_hundred(self):
        self.assertEqual(_grade_from_score(100.0), "A")

    def test_maturity_label_known(self):
        self.assertEqual(_maturity_label("UNPROVEN"), "unproven")
        self.assertEqual(_maturity_label("EMERGING"), "emerging")
        self.assertEqual(_maturity_label("ESTABLISHED"), "established")
        self.assertEqual(_maturity_label("BATTLE_TESTED"), "battle-tested")
        self.assertEqual(_maturity_label("INSUFFICIENT_DATA"), "unknown")

    def test_maturity_label_unknown_fallback(self):
        self.assertEqual(_maturity_label("WHATEVER"), "unknown")

    def test_constants_sane(self):
        self.assertGreater(AGE_FULL_DAYS, 0)
        self.assertGreater(EPOCHS_FULL, 0)
        self.assertGreater(AUDIT_COUNT_FULL, 0)
        self.assertGreater(DAYS_PER_MONTH, 0)
        self.assertLess(BRAND_NEW_AGE_DAYS, EMERGING_AGE_DAYS)
        self.assertLess(EMERGING_AGE_DAYS, ESTABLISHED_AGE_DAYS)
        self.assertLess(UNPROVEN_EPOCHS, EMERGING_EPOCHS)
        self.assertLess(EMERGING_EPOCHS, ESTABLISHED_EPOCHS)
        self.assertEqual(SEASONED_AGE_DAYS, ESTABLISHED_AGE_DAYS)
        self.assertEqual(SEASONED_EPOCHS, ESTABLISHED_EPOCHS)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "vault_age_days", "epochs_completed", "age_months",
            "is_audited", "audit_count", "survived_stress_event",
            "maturity_label", "is_brand_new", "is_seasoned", "score",
            "classification", "recommendation", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["score"], 0.0)
        self.assertLessEqual(self.r["score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "USDC-Vault")

    def test_token_field_alias(self):
        r = A().analyze({"token": "AltKey", "vault_age_days": 200.0,
                         "epochs_completed": 15.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "vault_age_days": 200.0, "epochs_completed": 15.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"vault_age_days": 200.0, "epochs_completed": 15.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "DEPLOY_FULL_SIZE", "DEPLOY", "DEPLOY_REDUCED_SIZE",
            "WAIT_OR_TINY_SIZE", "AVOID_OR_VERIFY",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "UNPROVEN", "EMERGING", "ESTABLISHED", "BATTLE_TESTED",
            "INSUFFICIENT_DATA",
        })

    def test_is_audited_is_bool(self):
        self.assertIsInstance(self.r["is_audited"], bool)

    def test_is_brand_new_is_bool(self):
        self.assertIsInstance(self.r["is_brand_new"], bool)

    def test_is_seasoned_is_bool(self):
        self.assertIsInstance(self.r["is_seasoned"], bool)

    def test_survived_stress_is_bool(self):
        self.assertIsInstance(self.r["survived_stress_event"], bool)

    def test_audit_count_is_int(self):
        self.assertIsInstance(self.r["audit_count"], int)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_age_passthrough(self):
        r = A().analyze(make_pos(vault_age_days=200.0))
        self.assertAlmostEqual(r["vault_age_days"], 200.0)

    def test_age_negative_clamped(self):
        r = A().analyze(make_pos(vault_age_days=-50.0, epochs_completed=15.0))
        self.assertAlmostEqual(r["vault_age_days"], 0.0)

    def test_epochs_passthrough(self):
        r = A().analyze(make_pos(epochs_completed=15.0))
        self.assertAlmostEqual(r["epochs_completed"], 15.0)

    def test_epochs_negative_clamped(self):
        r = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=-3.0))
        self.assertAlmostEqual(r["epochs_completed"], 0.0)

    def test_age_months(self):
        # 200 / 30.4375 = 6.5707...
        r = A().analyze(make_pos(vault_age_days=200.0))
        self.assertAlmostEqual(r["age_months"], 200.0 / DAYS_PER_MONTH, places=3)

    def test_age_months_zero_when_no_age(self):
        r = A().analyze(make_pos(vault_age_days=0.0, epochs_completed=5.0))
        self.assertAlmostEqual(r["age_months"], 0.0)

    def test_is_audited_true(self):
        r = A().analyze(make_pos(is_audited=True))
        self.assertTrue(r["is_audited"])

    def test_is_audited_false(self):
        r = A().analyze(make_pos(is_audited=False))
        self.assertFalse(r["is_audited"])

    def test_audit_count_passthrough(self):
        r = A().analyze(make_pos(audit_count=3))
        self.assertEqual(r["audit_count"], 3)

    def test_audit_count_negative_clamped(self):
        r = A().analyze(make_pos(audit_count=-2))
        self.assertEqual(r["audit_count"], 0)

    def test_audit_count_float_truncated(self):
        r = A().analyze(make_pos(audit_count=2.9))
        self.assertEqual(r["audit_count"], 2)

    def test_survived_stress_true(self):
        r = A().analyze(make_pos(survived_stress_event=True))
        self.assertTrue(r["survived_stress_event"])

    def test_survived_stress_false(self):
        r = A().analyze(make_pos(survived_stress_event=False))
        self.assertFalse(r["survived_stress_event"])

    def test_is_brand_new_true(self):
        r = A().analyze(make_pos(vault_age_days=9.0, epochs_completed=1.0))
        self.assertTrue(r["is_brand_new"])

    def test_is_brand_new_false(self):
        r = A().analyze(make_pos(vault_age_days=200.0))
        self.assertFalse(r["is_brand_new"])

    def test_is_brand_new_boundary(self):
        # exactly 14 → not brand new (< 14)
        r = A().analyze(make_pos(vault_age_days=14.0, epochs_completed=5.0))
        self.assertFalse(r["is_brand_new"])

    def test_is_seasoned_true(self):
        r = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0))
        self.assertTrue(r["is_seasoned"])

    def test_is_seasoned_false_young(self):
        r = A().analyze(make_pos(vault_age_days=100.0, epochs_completed=15.0))
        self.assertFalse(r["is_seasoned"])

    def test_is_seasoned_false_few_epochs(self):
        r = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=5.0))
        self.assertFalse(r["is_seasoned"])

    def test_is_seasoned_boundary(self):
        # exactly 180 and 12 → seasoned
        r = A().analyze(make_pos(vault_age_days=180.0, epochs_completed=12.0))
        self.assertTrue(r["is_seasoned"])

    def test_maturity_label_matches_classification(self):
        r = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0,
                                 survived_stress_event=True))
        self.assertEqual(r["maturity_label"], _maturity_label(r["classification"]))

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(vault_age_days=200.3333,
                                 epochs_completed=15.1111))
        for k in ("vault_age_days", "epochs_completed", "age_months"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_unproven_young(self):
        # age 9 < 14 → unproven
        r = A().analyze(make_pos(vault_age_days=9.0, epochs_completed=1.0,
                                 is_audited=False, survived_stress_event=False))
        self.assertEqual(r["classification"], "UNPROVEN")

    def test_unproven_few_epochs(self):
        # epochs 1 < 2 → unproven even if old
        r = A().analyze(make_pos(vault_age_days=300.0, epochs_completed=1.0))
        self.assertEqual(r["classification"], "UNPROVEN")

    def test_unproven_age_boundary(self):
        # age exactly 14 (not < 14), epochs 5 → not unproven by age
        r = A().analyze(make_pos(vault_age_days=14.0, epochs_completed=5.0,
                                 survived_stress_event=False))
        self.assertNotEqual(r["classification"], "UNPROVEN")

    def test_unproven_epochs_boundary(self):
        # epochs exactly 2 (not < 2) → not unproven by epochs
        r = A().analyze(make_pos(vault_age_days=100.0, epochs_completed=2.0,
                                 survived_stress_event=False))
        self.assertNotEqual(r["classification"], "UNPROVEN")

    def test_emerging_young(self):
        # age 40 < 60 → emerging
        r = A().analyze(make_pos(vault_age_days=40.0, epochs_completed=5.0,
                                 survived_stress_event=False))
        self.assertEqual(r["classification"], "EMERGING")

    def test_emerging_few_epochs(self):
        # epochs 5 < 6 → emerging
        r = A().analyze(make_pos(vault_age_days=100.0, epochs_completed=5.0,
                                 survived_stress_event=False))
        self.assertEqual(r["classification"], "EMERGING")

    def test_established_age(self):
        # age 100 < 180 → established (passes emerging gates)
        r = A().analyze(make_pos(vault_age_days=100.0, epochs_completed=10.0,
                                 survived_stress_event=True))
        self.assertEqual(r["classification"], "ESTABLISHED")

    def test_established_few_epochs(self):
        # epochs 10 < 12 → established
        r = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=10.0,
                                 survived_stress_event=True))
        self.assertEqual(r["classification"], "ESTABLISHED")

    def test_established_not_stress_tested(self):
        # old + many epochs but never stress-tested → established (not battle)
        r = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0,
                                 survived_stress_event=False))
        self.assertEqual(r["classification"], "ESTABLISHED")

    def test_battle_tested(self):
        # age >= 180, epochs >= 12, survived stress → battle tested
        r = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0,
                                 survived_stress_event=True))
        self.assertEqual(r["classification"], "BATTLE_TESTED")

    def test_battle_tested_boundary(self):
        # exactly 180, 12, survived → battle tested
        r = A().analyze(make_pos(vault_age_days=180.0, epochs_completed=12.0,
                                 survived_stress_event=True))
        self.assertEqual(r["classification"], "BATTLE_TESTED")

    def test_insufficient_no_age_no_epochs(self):
        r = A().analyze(make_pos(vault_age_days=0.0, epochs_completed=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_not_insufficient_with_age_only(self):
        r = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_not_insufficient_with_epochs_only(self):
        r = A().analyze(make_pos(vault_age_days=0.0, epochs_completed=5.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(vault_age_days=9.0, epochs_completed=1.0),
                    make_pos(vault_age_days=40.0, epochs_completed=5.0,
                             survived_stress_event=False),
                    make_pos(vault_age_days=100.0, epochs_completed=10.0,
                             survived_stress_event=True),
                    make_pos(vault_age_days=200.0, epochs_completed=15.0,
                             survived_stress_event=True),
                    make_pos(vault_age_days=0.0, epochs_completed=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "UNPROVEN", "EMERGING", "ESTABLISHED", "BATTLE_TESTED",
                "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_deploy_full_battle_tested(self):
        r = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0,
                                 survived_stress_event=True))
        self.assertEqual(r["recommendation"], "DEPLOY_FULL_SIZE")

    def test_deploy_established(self):
        r = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0,
                                 survived_stress_event=False))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_deploy_reduced_emerging(self):
        r = A().analyze(make_pos(vault_age_days=40.0, epochs_completed=5.0,
                                 survived_stress_event=False))
        self.assertEqual(r["recommendation"], "DEPLOY_REDUCED_SIZE")

    def test_wait_unproven(self):
        r = A().analyze(make_pos(vault_age_days=9.0, epochs_completed=1.0))
        self.assertEqual(r["recommendation"], "WAIT_OR_TINY_SIZE")

    def test_avoid_insufficient(self):
        r = A().analyze(make_pos(vault_age_days=0.0, epochs_completed=0.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_unproven_flag(self):
        r = A().analyze(make_pos(vault_age_days=9.0, epochs_completed=1.0))
        self.assertIn("UNPROVEN", r["flags"])

    def test_emerging_flag(self):
        r = A().analyze(make_pos(vault_age_days=40.0, epochs_completed=5.0,
                                 survived_stress_event=False))
        self.assertIn("EMERGING", r["flags"])

    def test_established_flag(self):
        r = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0,
                                 survived_stress_event=False))
        self.assertIn("ESTABLISHED", r["flags"])

    def test_battle_tested_flag(self):
        r = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0,
                                 survived_stress_event=True))
        self.assertIn("BATTLE_TESTED", r["flags"])

    def test_brand_new_flag(self):
        r = A().analyze(make_pos(vault_age_days=5.0, epochs_completed=1.0))
        self.assertIn("BRAND_NEW", r["flags"])

    def test_brand_new_flag_absent(self):
        r = A().analyze(make_pos(vault_age_days=200.0))
        self.assertNotIn("BRAND_NEW", r["flags"])

    def test_seasoned_flag(self):
        r = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0))
        self.assertIn("SEASONED", r["flags"])

    def test_seasoned_flag_absent(self):
        r = A().analyze(make_pos(vault_age_days=40.0, epochs_completed=5.0,
                                 survived_stress_event=False))
        self.assertNotIn("SEASONED", r["flags"])

    def test_audited_flag(self):
        r = A().analyze(make_pos(is_audited=True))
        self.assertIn("AUDITED", r["flags"])
        self.assertNotIn("UNAUDITED", r["flags"])

    def test_unaudited_flag(self):
        r = A().analyze(make_pos(is_audited=False))
        self.assertIn("UNAUDITED", r["flags"])
        self.assertNotIn("AUDITED", r["flags"])

    def test_survived_stress_flag(self):
        r = A().analyze(make_pos(survived_stress_event=True))
        self.assertIn("SURVIVED_STRESS_EVENT", r["flags"])
        self.assertNotIn("NEVER_STRESS_TESTED", r["flags"])

    def test_never_stress_tested_flag(self):
        r = A().analyze(make_pos(survived_stress_event=False))
        self.assertIn("NEVER_STRESS_TESTED", r["flags"])
        self.assertNotIn("SURVIVED_STRESS_EVENT", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(vault_age_days=0.0, epochs_completed=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_audited_unaudited_mutually_exclusive(self):
        for audited in (True, False):
            r = A().analyze(make_pos(is_audited=audited))
            self.assertFalse(
                "AUDITED" in r["flags"] and "UNAUDITED" in r["flags"])

    def test_stress_flags_mutually_exclusive(self):
        for survived in (True, False):
            r = A().analyze(make_pos(survived_stress_event=survived))
            self.assertFalse(
                "SURVIVED_STRESS_EVENT" in r["flags"]
                and "NEVER_STRESS_TESTED" in r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_age_no_epochs(self):
        r = A().analyze(make_pos(vault_age_days=0.0, epochs_completed=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(vault_age_days=0.0, epochs_completed=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(vault_age_days=0.0, epochs_completed=0.0))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_none_fields(self):
        r = A().analyze({})
        self.assertIsNone(r["age_months"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("vault_age_days", "epochs_completed", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["is_audited"])
        self.assertFalse(r["is_brand_new"])
        self.assertFalse(r["is_seasoned"])
        self.assertFalse(r["survived_stress_event"])
        self.assertEqual(r["audit_count"], 0)
        self.assertEqual(r["maturity_label"], "unknown")

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_valid_with_age(self):
        r = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_valid_with_epochs(self):
        r = A().analyze(make_pos(vault_age_days=0.0, epochs_completed=5.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_older_scores_higher(self):
        young = A().analyze(make_pos(vault_age_days=30.0, epochs_completed=5.0,
                                     is_audited=False,
                                     survived_stress_event=False))
        old = A().analyze(make_pos(vault_age_days=300.0, epochs_completed=5.0,
                                   is_audited=False,
                                   survived_stress_event=False))
        self.assertGreater(old["score"], young["score"])

    def test_more_epochs_scores_higher(self):
        few = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=2.0,
                                   is_audited=False,
                                   survived_stress_event=False))
        many = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=20.0,
                                    is_audited=False,
                                    survived_stress_event=False))
        self.assertGreater(many["score"], few["score"])

    def test_audited_scores_higher(self):
        no = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0,
                                  is_audited=False,
                                  survived_stress_event=False))
        yes = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0,
                                   is_audited=True, audit_count=1,
                                   survived_stress_event=False))
        self.assertGreater(yes["score"], no["score"])

    def test_more_audits_scores_higher(self):
        one = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0,
                                   is_audited=True, audit_count=1,
                                   survived_stress_event=False))
        three = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0,
                                     is_audited=True, audit_count=3,
                                     survived_stress_event=False))
        self.assertGreater(three["score"], one["score"])

    def test_stress_survived_scores_higher(self):
        no = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0,
                                  is_audited=True,
                                  survived_stress_event=False))
        yes = A().analyze(make_pos(vault_age_days=200.0, epochs_completed=15.0,
                                   is_audited=True,
                                   survived_stress_event=True))
        self.assertGreater(yes["score"], no["score"])

    def test_battle_tested_high_score(self):
        r = A().analyze(make_pos(vault_age_days=400.0, epochs_completed=50.0,
                                 is_audited=True, audit_count=3,
                                 survived_stress_event=True))
        self.assertGreater(r["score"], 85.0)

    def test_unproven_low_score(self):
        r = A().analyze(make_pos(vault_age_days=9.0, epochs_completed=1.0,
                                 is_audited=False, audit_count=0,
                                 survived_stress_event=False))
        self.assertLess(r["score"], 40.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(vault_age_days=1e12, epochs_completed=1e12,
                                 is_audited=True, audit_count=1000,
                                 survived_stress_event=True))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(vault_age_days=1.0, epochs_completed=0.0,
                                 is_audited=False, audit_count=0,
                                 survived_stress_event=False))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(vault_age_days=9.0, epochs_completed=1.0),
                    make_pos(vault_age_days=40.0, epochs_completed=5.0),
                    make_pos(vault_age_days=200.0, epochs_completed=15.0),
                    make_pos(vault_age_days=0.0, epochs_completed=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(vault_age_days=400.0, epochs_completed=50.0),
                    make_pos(vault_age_days=9.0, epochs_completed=1.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Mature", vault_age_days=400.0,
                     epochs_completed=50.0, is_audited=True, audit_count=3,
                     survived_stress_event=True),
            make_pos(vault="New", vault_age_days=9.0, epochs_completed=1.0,
                     is_audited=False, audit_count=0,
                     survived_stress_event=False),
            make_pos(vault="Mid", vault_age_days=40.0, epochs_completed=5.0,
                     is_audited=True, audit_count=1,
                     survived_stress_event=False),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_mature_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_mature_vault"]], max(scores.values()))

    def test_least_mature_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["least_mature_vault"]], min(scores.values()))

    def test_most_mature_is_mature(self):
        self.assertEqual(self.res["aggregate"]["most_mature_vault"], "Mature")

    def test_least_mature_is_new(self):
        self.assertEqual(self.res["aggregate"]["least_mature_vault"], "New")

    def test_unproven_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["unproven_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_mature_vault"])
        self.assertIsNone(res["aggregate"]["least_mature_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(vault_age_days=0.0, epochs_completed=0.0),
            make_pos(vault_age_days=0.0, epochs_completed=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_mature_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["unproven_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_mature_vault"], "Solo")
        self.assertEqual(res["aggregate"]["least_mature_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", vault_age_days=200.0, epochs_completed=15.0),
            make_pos(vault="Ins", vault_age_days=0.0, epochs_completed=0.0),
        ])
        scored = [p["score"] for p in res["positions"]
                  if p["classification"] != "INSUFFICIENT_DATA"]
        self.assertAlmostEqual(res["aggregate"]["avg_score"],
                               round(sum(scored) / len(scored), 2))


# ── logging ───────────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            self.assertTrue(os.path.exists(path))
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_no_write_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_ring_buffer_cap_3(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            cfg = {"log_path": path, "log_cap": 3}
            for _ in range(6):
                A().analyze_portfolio([make_pos()], cfg=cfg, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_ring_buffer_cap_100_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            cfg = {"log_path": path, "log_cap": LOG_CAP}
            for _ in range(105):
                A().analyze(make_pos(), cfg=cfg, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 100)

    def test_corrupt_log_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                fh.write("{not valid json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_non_list_log_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                json.dump({"not": "a list"}, fh)
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_log_entry_has_snapshots(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([make_pos(), make_pos(vault="B")],
                                  cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(data[0]["position_count"], 2)
            self.assertEqual(len(data[0]["snapshots"]), 2)

    def test_atomic_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_log_json_no_inf_nan(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([
                make_pos(),
                make_pos(vault="big", vault_age_days=1e12,
                         epochs_completed=1e12, audit_count=1000),
                make_pos(vault="ins", vault_age_days=0.0,
                         epochs_completed=0.0),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)

    def test_log_none_fields_serialize_null(self):
        res = A().analyze(make_pos(vault_age_days=0.0, epochs_completed=0.0))
        raw = json.dumps(res)
        self.assertIn("null", raw)
        json.loads(raw)

    def test_log_snapshot_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            snap = data[0]["snapshots"][0]
            for k in ("token", "classification", "score",
                      "recommendation", "flags"):
                self.assertIn(k, snap)

    def test_log_has_aggregate(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([make_pos()],
                                  cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIn("aggregate", data[0])

    def test_log_does_not_touch_production(self):
        before = os.path.exists(LOG_PATH)
        A().analyze(make_pos())
        after = os.path.exists(LOG_PATH)
        self.assertEqual(before, after)

    def test_no_write_analyze_does_not_create_production_log(self):
        before = os.path.exists(LOG_PATH)
        A().analyze_portfolio(_demo_positions())
        after = os.path.exists(LOG_PATH)
        self.assertEqual(before, after)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "vault_age_days": "200",
            "epochs_completed": "15",
            "audit_count": "2",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "vault_age_days": 200.0,
                         "epochs_completed": 15.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(vault_age_days=0.0, epochs_completed=0.0),
            make_pos(vault_age_days=9.0, epochs_completed=1.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(vault_age_days=9.0, epochs_completed=1.0),
                    make_pos(vault_age_days=0.0, epochs_completed=0.0),
                    make_pos(vault_age_days=1e12, epochs_completed=1e12,
                             audit_count=1000),
                    make_pos(vault_age_days=-1e9, epochs_completed=-1e9),
                    make_pos(audit_count=-1e9)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(vault_age_days=1e12, epochs_completed=1e9))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(vault_age_days=-10.0, epochs_completed=-8.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_none_fields_are_none_or_finite(self):
        for pos in [make_pos(), make_pos(vault_age_days=0.0,
                                         epochs_completed=0.0),
                    make_pos(vault_age_days=9.0, epochs_completed=1.0)]:
            r = A().analyze(pos)
            v = r["age_months"]
            if v is not None:
                self.assertTrue(math.isfinite(v))

    def test_truthy_audit_flag(self):
        # is_audited passed as truthy non-bool int still coerces
        r = A().analyze(make_pos(is_audited=1))
        self.assertTrue(r["is_audited"])

    def test_falsy_audit_flag(self):
        r = A().analyze(make_pos(is_audited=0))
        self.assertFalse(r["is_audited"])


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 5)

    def test_demo_runs_through_portfolio(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertEqual(len(res["positions"]), len(_demo_positions()))
        self.assertIn("aggregate", res)

    def test_demo_json_serializable(self):
        res = A().analyze_portfolio(_demo_positions())
        json.dumps(res)

    def test_demo_no_inf_nan(self):
        res = A().analyze_portfolio(_demo_positions())
        raw = json.dumps(res)
        self.assertNotIn("Infinity", raw)
        self.assertNotIn("NaN", raw)

    def test_demo_has_varied_classifications(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertGreater(len(classes), 1)

    def test_demo_includes_insufficient(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_includes_battle_and_unproven(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("BATTLE_TESTED", classes)
        self.assertIn("UNPROVEN", classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
