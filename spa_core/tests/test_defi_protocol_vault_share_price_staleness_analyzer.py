"""
Tests for MP-1174: DeFiProtocolVaultSharePriceStalenessAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_share_price_staleness_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_share_price_staleness_analyzer import (
    DeFiProtocolVaultSharePriceStalenessAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    STALE_CEILING_RATIO,
    DRIFT_CEILING_PCT,
    SIGNIFICANT_DRIFT_PCT,
    FRESH_RATIO,
    STALE_RATIO,
    SEVERE_RATIO,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    expected_update_interval_hours=12.0,
    hours_since_last_nav_update=6.0,
    nav_drift_pct=0.1,
    is_oracle_priced=False,
):
    return {
        "vault": vault,
        "expected_update_interval_hours": expected_update_interval_hours,
        "hours_since_last_nav_update": hours_since_last_nav_update,
        "nav_drift_pct": nav_drift_pct,
        "is_oracle_priced": is_oracle_priced,
    }


def A():
    return DeFiProtocolVaultSharePriceStalenessAnalyzer()


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

    def test_f_float_passthrough(self):
        self.assertEqual(_f(4.25), 4.25)

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

    def test_constants_sane(self):
        self.assertEqual(FRESH_RATIO, 1.0)
        self.assertEqual(STALE_RATIO, 2.0)
        self.assertEqual(SEVERE_RATIO, 4.0)
        self.assertLess(FRESH_RATIO, STALE_RATIO)
        self.assertLess(STALE_RATIO, SEVERE_RATIO)
        self.assertGreater(STALE_CEILING_RATIO, 0)
        self.assertGreater(DRIFT_CEILING_PCT, 0)
        self.assertGreater(SIGNIFICANT_DRIFT_PCT, 0)
        self.assertEqual(LOG_CAP, 100)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "expected_update_interval_hours",
            "hours_since_last_nav_update", "staleness_ratio", "eff_ratio",
            "hours_overdue", "is_overdue", "nav_drift_pct", "abs_drift_pct",
            "is_oracle_priced", "significantly_stale", "mispricing_risk",
            "score", "classification", "recommendation", "grade", "flags",
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
        r = A().analyze({"token": "AltKey",
                         "expected_update_interval_hours": 12.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "expected_update_interval_hours": 12.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"expected_update_interval_hours": 12.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "TRUST_NAV", "VERIFY_NAV_BEFORE_TRADING", "AWAIT_NAV_UPDATE",
            "AVOID_OR_VERIFY", "VERIFY_DATA",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "FRESH", "SLIGHTLY_STALE", "STALE", "SEVERELY_STALE",
            "INSUFFICIENT_DATA",
        })

    def test_is_overdue_is_bool(self):
        self.assertIsInstance(self.r["is_overdue"], bool)

    def test_is_oracle_priced_is_bool(self):
        self.assertIsInstance(self.r["is_oracle_priced"], bool)

    def test_significantly_stale_is_bool(self):
        self.assertIsInstance(self.r["significantly_stale"], bool)

    def test_mispricing_risk_is_bool(self):
        self.assertIsInstance(self.r["mispricing_risk"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_interval_passthrough(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0))
        self.assertAlmostEqual(r["expected_update_interval_hours"], 12.0)

    def test_hours_since_negative_clamped(self):
        r = A().analyze(make_pos(hours_since_last_nav_update=-5.0))
        self.assertAlmostEqual(r["hours_since_last_nav_update"], 0.0)

    def test_staleness_ratio(self):
        # 6 / 12 = 0.5
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=6.0))
        self.assertAlmostEqual(r["staleness_ratio"], 0.5, places=4)

    def test_eff_ratio_matches_staleness_non_oracle(self):
        r = A().analyze(make_pos(expected_update_interval_hours=10.0,
                                 hours_since_last_nav_update=30.0,
                                 is_oracle_priced=False))
        self.assertAlmostEqual(r["eff_ratio"], 3.0, places=4)

    def test_eff_ratio_zero_for_oracle(self):
        r = A().analyze(make_pos(expected_update_interval_hours=2.0,
                                 hours_since_last_nav_update=100.0,
                                 is_oracle_priced=True))
        self.assertAlmostEqual(r["eff_ratio"], 0.0, places=4)

    def test_staleness_ratio_still_reported_for_oracle(self):
        # raw staleness_ratio is still computed; only eff_ratio is zeroed
        r = A().analyze(make_pos(expected_update_interval_hours=2.0,
                                 hours_since_last_nav_update=8.0,
                                 is_oracle_priced=True))
        self.assertAlmostEqual(r["staleness_ratio"], 4.0, places=4)
        self.assertAlmostEqual(r["eff_ratio"], 0.0, places=4)

    def test_hours_overdue(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=20.0))
        self.assertAlmostEqual(r["hours_overdue"], 8.0, places=4)

    def test_hours_overdue_floor_zero(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=6.0))
        self.assertAlmostEqual(r["hours_overdue"], 0.0, places=4)

    def test_is_overdue_true(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=13.0))
        self.assertTrue(r["is_overdue"])

    def test_is_overdue_boundary_equal_false(self):
        # exactly equal → not overdue (strict >)
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=12.0))
        self.assertFalse(r["is_overdue"])

    def test_is_overdue_false(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=6.0))
        self.assertFalse(r["is_overdue"])

    def test_nav_drift_signed_preserved(self):
        r = A().analyze(make_pos(nav_drift_pct=-0.9))
        self.assertAlmostEqual(r["nav_drift_pct"], -0.9, places=4)

    def test_abs_drift(self):
        r = A().analyze(make_pos(nav_drift_pct=-1.3))
        self.assertAlmostEqual(r["abs_drift_pct"], 1.3, places=4)

    def test_abs_drift_positive(self):
        r = A().analyze(make_pos(nav_drift_pct=0.7))
        self.assertAlmostEqual(r["abs_drift_pct"], 0.7, places=4)

    def test_significantly_stale_true(self):
        # eff ratio 24/12 = 2.0 >= STALE_RATIO
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=24.0))
        self.assertTrue(r["significantly_stale"])

    def test_significantly_stale_boundary(self):
        # exactly STALE_RATIO=2.0
        r = A().analyze(make_pos(expected_update_interval_hours=10.0,
                                 hours_since_last_nav_update=20.0))
        self.assertTrue(r["significantly_stale"])

    def test_significantly_stale_false(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=6.0))
        self.assertFalse(r["significantly_stale"])

    def test_oracle_not_significantly_stale(self):
        r = A().analyze(make_pos(expected_update_interval_hours=2.0,
                                 hours_since_last_nav_update=100.0,
                                 is_oracle_priced=True))
        self.assertFalse(r["significantly_stale"])

    def test_mispricing_risk_true(self):
        # eff 2.5 (not fresh) + drift 0.8 >= SIGNIFICANT
        r = A().analyze(make_pos(expected_update_interval_hours=10.0,
                                 hours_since_last_nav_update=25.0,
                                 nav_drift_pct=0.8))
        self.assertTrue(r["mispricing_risk"])

    def test_mispricing_risk_false_when_fresh(self):
        # fresh (eff <=1) even with big drift → no mispricing risk
        r = A().analyze(make_pos(expected_update_interval_hours=10.0,
                                 hours_since_last_nav_update=5.0,
                                 nav_drift_pct=1.9))
        self.assertFalse(r["mispricing_risk"])

    def test_mispricing_risk_false_small_drift(self):
        r = A().analyze(make_pos(expected_update_interval_hours=10.0,
                                 hours_since_last_nav_update=25.0,
                                 nav_drift_pct=0.2))
        self.assertFalse(r["mispricing_risk"])

    def test_mispricing_risk_drift_boundary(self):
        # drift exactly SIGNIFICANT_DRIFT_PCT and not fresh
        r = A().analyze(make_pos(expected_update_interval_hours=10.0,
                                 hours_since_last_nav_update=25.0,
                                 nav_drift_pct=SIGNIFICANT_DRIFT_PCT))
        self.assertTrue(r["mispricing_risk"])

    def test_oracle_priced_passthrough(self):
        r = A().analyze(make_pos(is_oracle_priced=True))
        self.assertTrue(r["is_oracle_priced"])

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.3333,
                                 hours_since_last_nav_update=6.1111,
                                 nav_drift_pct=0.4444))
        for k in ("expected_update_interval_hours",
                  "hours_since_last_nav_update", "eff_ratio", "hours_overdue",
                  "nav_drift_pct", "abs_drift_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_fresh(self):
        # 6/12 = 0.5 <= FRESH
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=6.0))
        self.assertEqual(r["classification"], "FRESH")

    def test_slightly_stale(self):
        # 18/12 = 1.5 (>FRESH, <=STALE)
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=18.0))
        self.assertEqual(r["classification"], "SLIGHTLY_STALE")

    def test_stale(self):
        # 36/12 = 3.0 (>STALE, <=SEVERE)
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=36.0))
        self.assertEqual(r["classification"], "STALE")

    def test_severely_stale(self):
        # 60/12 = 5.0 (>SEVERE)
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=60.0))
        self.assertEqual(r["classification"], "SEVERELY_STALE")

    def test_fresh_boundary(self):
        # exactly FRESH_RATIO=1.0
        r = A().analyze(make_pos(expected_update_interval_hours=10.0,
                                 hours_since_last_nav_update=10.0))
        self.assertEqual(r["classification"], "FRESH")

    def test_stale_boundary(self):
        # exactly STALE_RATIO=2.0 → SLIGHTLY_STALE (<=)
        r = A().analyze(make_pos(expected_update_interval_hours=10.0,
                                 hours_since_last_nav_update=20.0))
        self.assertEqual(r["classification"], "SLIGHTLY_STALE")

    def test_severe_boundary(self):
        # exactly SEVERE_RATIO=4.0 → STALE (<=)
        r = A().analyze(make_pos(expected_update_interval_hours=10.0,
                                 hours_since_last_nav_update=40.0))
        self.assertEqual(r["classification"], "STALE")

    def test_above_severe(self):
        # 4.1 → SEVERELY_STALE
        r = A().analyze(make_pos(expected_update_interval_hours=10.0,
                                 hours_since_last_nav_update=41.0))
        self.assertEqual(r["classification"], "SEVERELY_STALE")

    def test_oracle_always_fresh(self):
        r = A().analyze(make_pos(expected_update_interval_hours=2.0,
                                 hours_since_last_nav_update=100.0,
                                 is_oracle_priced=True))
        self.assertEqual(r["classification"], "FRESH")

    def test_insufficient_no_interval(self):
        r = A().analyze(make_pos(expected_update_interval_hours=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_negative_interval(self):
        r = A().analyze(make_pos(expected_update_interval_hours=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(hours_since_last_nav_update=6.0),
                    make_pos(hours_since_last_nav_update=18.0),
                    make_pos(hours_since_last_nav_update=36.0),
                    make_pos(hours_since_last_nav_update=60.0),
                    make_pos(expected_update_interval_hours=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "FRESH", "SLIGHTLY_STALE", "STALE", "SEVERELY_STALE",
                "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_trust_nav_fresh(self):
        r = A().analyze(make_pos(hours_since_last_nav_update=6.0,
                                 nav_drift_pct=0.1))
        self.assertEqual(r["recommendation"], "TRUST_NAV")

    def test_verify_before_trading_slightly_stale(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=18.0,
                                 nav_drift_pct=0.1))
        self.assertEqual(r["recommendation"], "VERIFY_NAV_BEFORE_TRADING")

    def test_await_nav_update_stale(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=36.0,
                                 nav_drift_pct=0.1))
        self.assertEqual(r["recommendation"], "AWAIT_NAV_UPDATE")

    def test_avoid_severely_stale(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=60.0,
                                 nav_drift_pct=0.1))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_verify_insufficient(self):
        r = A().analyze(make_pos(expected_update_interval_hours=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_mispricing_override_slightly_stale(self):
        # slightly stale but mispricing risk → AVOID_OR_VERIFY
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=18.0,
                                 nav_drift_pct=0.9))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_mispricing_override_stale(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=36.0,
                                 nav_drift_pct=0.9))
        self.assertEqual(r["recommendation"], "AVOID_OR_VERIFY")

    def test_fresh_with_high_drift_still_trusts(self):
        # fresh → no mispricing_risk even with big drift → TRUST_NAV
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=6.0,
                                 nav_drift_pct=1.9))
        self.assertEqual(r["recommendation"], "TRUST_NAV")

    def test_oracle_trusts_nav(self):
        r = A().analyze(make_pos(expected_update_interval_hours=2.0,
                                 hours_since_last_nav_update=100.0,
                                 nav_drift_pct=1.5,
                                 is_oracle_priced=True))
        self.assertEqual(r["recommendation"], "TRUST_NAV")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_fresh_flag(self):
        r = A().analyze(make_pos(hours_since_last_nav_update=6.0))
        self.assertIn("FRESH", r["flags"])

    def test_slightly_stale_flag(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=18.0))
        self.assertIn("SLIGHTLY_STALE", r["flags"])

    def test_stale_flag(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=36.0))
        self.assertIn("STALE", r["flags"])

    def test_severely_stale_flag(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=60.0))
        self.assertIn("SEVERELY_STALE", r["flags"])

    def test_overdue_flag(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=18.0))
        self.assertIn("OVERDUE", r["flags"])

    def test_overdue_flag_absent(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=6.0))
        self.assertNotIn("OVERDUE", r["flags"])

    def test_oracle_priced_flag(self):
        r = A().analyze(make_pos(is_oracle_priced=True))
        self.assertIn("ORACLE_PRICED", r["flags"])
        self.assertNotIn("SNAPSHOT_PRICED", r["flags"])

    def test_snapshot_priced_flag(self):
        r = A().analyze(make_pos(is_oracle_priced=False))
        self.assertIn("SNAPSHOT_PRICED", r["flags"])
        self.assertNotIn("ORACLE_PRICED", r["flags"])

    def test_unreflected_gain_flag(self):
        # drift > SIGNIFICANT (0.5)
        r = A().analyze(make_pos(nav_drift_pct=0.9))
        self.assertIn("UNREFLECTED_GAIN", r["flags"])

    def test_unreflected_gain_flag_boundary_excluded(self):
        # exactly SIGNIFICANT → strict > → not flagged
        r = A().analyze(make_pos(nav_drift_pct=SIGNIFICANT_DRIFT_PCT))
        self.assertNotIn("UNREFLECTED_GAIN", r["flags"])

    def test_unreflected_loss_flag(self):
        r = A().analyze(make_pos(nav_drift_pct=-0.9))
        self.assertIn("UNREFLECTED_LOSS", r["flags"])

    def test_unreflected_loss_flag_boundary_excluded(self):
        r = A().analyze(make_pos(nav_drift_pct=-SIGNIFICANT_DRIFT_PCT))
        self.assertNotIn("UNREFLECTED_LOSS", r["flags"])

    def test_no_unreflected_flag_small_drift(self):
        r = A().analyze(make_pos(nav_drift_pct=0.2))
        self.assertNotIn("UNREFLECTED_GAIN", r["flags"])
        self.assertNotIn("UNREFLECTED_LOSS", r["flags"])

    def test_mispricing_risk_flag(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=36.0,
                                 nav_drift_pct=0.9))
        self.assertIn("MISPRICING_RISK", r["flags"])

    def test_mispricing_risk_flag_absent_when_fresh(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=6.0,
                                 nav_drift_pct=0.9))
        self.assertNotIn("MISPRICING_RISK", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(expected_update_interval_hours=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_oracle_no_overdue_even_if_late(self):
        # is_overdue is based on raw hours, oracle still flags OVERDUE
        r = A().analyze(make_pos(expected_update_interval_hours=2.0,
                                 hours_since_last_nav_update=100.0,
                                 is_oracle_priced=True))
        # oracle priced, but raw hours_since > interval, so OVERDUE present
        self.assertIn("OVERDUE", r["flags"])
        self.assertIn("ORACLE_PRICED", r["flags"])
        self.assertIn("FRESH", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_interval(self):
        r = A().analyze(make_pos(expected_update_interval_hours=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(expected_update_interval_hours=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(expected_update_interval_hours=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_staleness_ratio_none(self):
        r = A().analyze({})
        self.assertIsNone(r["staleness_ratio"])

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["is_overdue"])
        self.assertFalse(r["is_oracle_priced"])
        self.assertFalse(r["significantly_stale"])
        self.assertFalse(r["mispricing_risk"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("expected_update_interval_hours",
                  "hours_since_last_nav_update", "eff_ratio", "hours_overdue",
                  "nav_drift_pct", "abs_drift_pct", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_no_inf_nan(self):
        finite_check(self, A().analyze({}))

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_valid_with_interval(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_fresher_scores_higher(self):
        fresh = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                     hours_since_last_nav_update=2.0,
                                     nav_drift_pct=0.1))
        stale = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                     hours_since_last_nav_update=30.0,
                                     nav_drift_pct=0.1))
        self.assertGreater(fresh["score"], stale["score"])

    def test_less_drift_scores_higher(self):
        low = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                   hours_since_last_nav_update=10.0,
                                   nav_drift_pct=0.1))
        high = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                    hours_since_last_nav_update=10.0,
                                    nav_drift_pct=1.9))
        self.assertGreater(low["score"], high["score"])

    def test_oracle_no_drift_full_score(self):
        r = A().analyze(make_pos(expected_update_interval_hours=2.0,
                                 hours_since_last_nav_update=100.0,
                                 nav_drift_pct=0.0,
                                 is_oracle_priced=True))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_fresh_zero_drift_high_score(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=0.0,
                                 nav_drift_pct=0.0))
        self.assertAlmostEqual(r["score"], 100.0, places=4)

    def test_very_stale_high_drift_low_score(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=120.0,
                                 nav_drift_pct=5.0))
        self.assertLess(r["score"], 5.0)

    def test_freshness_component_zero_at_ceiling(self):
        # eff ratio at STALE_CEILING_RATIO=2 → freshness comp 0, only drift
        r = A().analyze(make_pos(expected_update_interval_hours=10.0,
                                 hours_since_last_nav_update=20.0,
                                 nav_drift_pct=0.0))
        self.assertAlmostEqual(r["score"], 40.0, places=4)

    def test_drift_component_zero_at_ceiling(self):
        # fresh (eff 0) + drift at DRIFT_CEILING_PCT=2 → drift comp 0
        r = A().analyze(make_pos(expected_update_interval_hours=10.0,
                                 hours_since_last_nav_update=0.0,
                                 nav_drift_pct=2.0))
        self.assertAlmostEqual(r["score"], 60.0, places=4)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(expected_update_interval_hours=12.0,
                                 hours_since_last_nav_update=1e12,
                                 nav_drift_pct=1e9))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(expected_update_interval_hours=1e9,
                                 hours_since_last_nav_update=1e12,
                                 nav_drift_pct=1e9))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(hours_since_last_nav_update=6.0),
                    make_pos(hours_since_last_nav_update=18.0),
                    make_pos(hours_since_last_nav_update=60.0),
                    make_pos(is_oracle_priced=True),
                    make_pos(expected_update_interval_hours=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(hours_since_last_nav_update=0.0,
                             nav_drift_pct=0.0),
                    make_pos(hours_since_last_nav_update=120.0,
                             nav_drift_pct=5.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Fresh", expected_update_interval_hours=12.0,
                     hours_since_last_nav_update=1.0, nav_drift_pct=0.0),
            make_pos(vault="Stale", expected_update_interval_hours=12.0,
                     hours_since_last_nav_update=80.0, nav_drift_pct=1.9),
            make_pos(vault="Mid", expected_update_interval_hours=12.0,
                     hours_since_last_nav_update=18.0, nav_drift_pct=0.3),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_freshest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["freshest_vault"]], max(scores.values()))

    def test_stalest_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["stalest_vault"]], min(scores.values()))

    def test_freshest_is_fresh(self):
        self.assertEqual(self.res["aggregate"]["freshest_vault"], "Fresh")

    def test_stalest_is_stale(self):
        self.assertEqual(self.res["aggregate"]["stalest_vault"], "Stale")

    def test_stale_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["stale_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_stale_count_counts_stale_and_severe(self):
        res = A().analyze_portfolio([
            make_pos(vault="A", expected_update_interval_hours=12.0,
                     hours_since_last_nav_update=36.0),  # STALE
            make_pos(vault="B", expected_update_interval_hours=12.0,
                     hours_since_last_nav_update=60.0),  # SEVERELY_STALE
            make_pos(vault="C", expected_update_interval_hours=12.0,
                     hours_since_last_nav_update=6.0),   # FRESH
        ])
        self.assertEqual(res["aggregate"]["stale_count"], 2)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["freshest_vault"])
        self.assertIsNone(res["aggregate"]["stalest_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(expected_update_interval_hours=0.0),
            make_pos(expected_update_interval_hours=0.0),
        ])
        self.assertIsNone(res["aggregate"]["freshest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["stale_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["freshest_vault"], "Solo")
        self.assertEqual(res["aggregate"]["stalest_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good"),
            make_pos(vault="Ins", expected_update_interval_hours=0.0),
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
                make_pos(vault="big", expected_update_interval_hours=1e9,
                         hours_since_last_nav_update=1e12,
                         nav_drift_pct=1e9),
                make_pos(vault="ins", expected_update_interval_hours=0.0),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
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
            "expected_update_interval_hours": "12",
            "hours_since_last_nav_update": "6",
            "nav_drift_pct": "0.4",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "expected_update_interval_hours": 12.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(expected_update_interval_hours=0.0),
            make_pos(hours_since_last_nav_update=60.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(hours_since_last_nav_update=60.0),
                    make_pos(expected_update_interval_hours=0.0),
                    make_pos(is_oracle_priced=True),
                    make_pos(expected_update_interval_hours=1e9,
                             hours_since_last_nav_update=1e12,
                             nav_drift_pct=1e9),
                    make_pos(expected_update_interval_hours=-1e9,
                             hours_since_last_nav_update=-1e9),
                    make_pos(nav_drift_pct=-1e9)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(expected_update_interval_hours=1e12,
                                 hours_since_last_nav_update=1e9))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(hours_since_last_nav_update=-10.0,
                                 nav_drift_pct=-8.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_truthy_oracle_flag(self):
        r = A().analyze(make_pos(is_oracle_priced=1))
        self.assertTrue(r["is_oracle_priced"])

    def test_falsy_oracle_flag(self):
        r = A().analyze(make_pos(is_oracle_priced=0))
        self.assertFalse(r["is_oracle_priced"])

    def test_zero_hours_since_fresh(self):
        r = A().analyze(make_pos(hours_since_last_nav_update=0.0))
        self.assertEqual(r["classification"], "FRESH")


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 6)

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

    def test_demo_includes_fresh_and_severe(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("FRESH", classes)
        self.assertIn("SEVERELY_STALE", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("FRESH", "SLIGHTLY_STALE", "STALE", "SEVERELY_STALE",
                  "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_oracle_and_mispricing(self):
        res = A().analyze_portfolio(_demo_positions())
        has_oracle = any(p["is_oracle_priced"] for p in res["positions"])
        has_misprice = any(p["mispricing_risk"] for p in res["positions"])
        self.assertTrue(has_oracle)
        self.assertTrue(has_misprice)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
