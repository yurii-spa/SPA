"""
Tests for MP-1183: DeFiProtocolVaultUnclaimedRewardForfeitureAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_unclaimed_reward_forfeiture_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_unclaimed_reward_forfeiture_analyzer import (
    DeFiProtocolVaultUnclaimedRewardForfeitureAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DEFAULT_CLAIM_CADENCE_HOURS,
    SAFE_RATIO,
    WATCH_RATIO,
    ATRISK_RATIO,
    LARGE_FORFEIT_USD,
    URGENCY_RATIO_CAP,
    FORFEIT_PCT_CEILING,
    EXPIRED_SCORE,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    unclaimed_reward_usd=100.0,
    hours_to_deadline=400.0,
    claim_cadence_hours=100.0,
    forfeit_fraction=1.0,
):
    return {
        "vault": vault,
        "unclaimed_reward_usd": unclaimed_reward_usd,
        "hours_to_deadline": hours_to_deadline,
        "claim_cadence_hours": claim_cadence_hours,
        "forfeit_fraction": forfeit_fraction,
    }


def A():
    return DeFiProtocolVaultUnclaimedRewardForfeitureAnalyzer()


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

    def test_f_string_number(self):
        self.assertEqual(_f("168"), 168.0)

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
        self.assertLess(SAFE_RATIO, WATCH_RATIO)
        self.assertLess(WATCH_RATIO, ATRISK_RATIO)
        self.assertGreater(DEFAULT_CLAIM_CADENCE_HOURS, 0)
        self.assertGreater(LARGE_FORFEIT_USD, 0)
        self.assertGreater(URGENCY_RATIO_CAP, 0)
        self.assertGreater(FORFEIT_PCT_CEILING, 0)
        self.assertGreaterEqual(EXPIRED_SCORE, 0)
        self.assertEqual(LOG_CAP, 100)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "unclaimed_reward_usd", "hours_to_deadline",
            "claim_cadence_hours", "forfeit_fraction", "urgency_ratio",
            "is_expired", "miss_probability", "expected_forfeit_usd",
            "expected_forfeit_pct", "high_miss_probability", "large_forfeit",
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
        r = A().analyze({"token": "AltKey", "unclaimed_reward_usd": 100.0,
                         "hours_to_deadline": 400.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "unclaimed_reward_usd": 100.0,
                         "hours_to_deadline": 400.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"unclaimed_reward_usd": 100.0,
                         "hours_to_deadline": 400.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "NO_ACTION", "SCHEDULE_CLAIM", "CLAIM_SOON", "CLAIM_NOW",
            "DEADLINE_PASSED_VERIFY", "VERIFY_DATA",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "SAFE", "WATCH", "AT_RISK", "CRITICAL", "EXPIRED",
            "INSUFFICIENT_DATA",
        })

    def test_is_expired_is_bool(self):
        self.assertIsInstance(self.r["is_expired"], bool)

    def test_high_miss_is_bool(self):
        self.assertIsInstance(self.r["high_miss_probability"], bool)

    def test_large_forfeit_is_bool(self):
        self.assertIsInstance(self.r["large_forfeit"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_urgency_ratio(self):
        # cadence 100 / deadline 400 = 0.25
        r = A().analyze(make_pos(claim_cadence_hours=100.0,
                                 hours_to_deadline=400.0))
        self.assertAlmostEqual(r["urgency_ratio"], 0.25, places=4)

    def test_urgency_ratio_above_one(self):
        # cadence 168 / deadline 24 = 7.0
        r = A().analyze(make_pos(claim_cadence_hours=168.0,
                                 hours_to_deadline=24.0))
        self.assertAlmostEqual(r["urgency_ratio"], 7.0, places=4)

    def test_urgency_ratio_capped(self):
        r = A().analyze(make_pos(claim_cadence_hours=1e9,
                                 hours_to_deadline=1.0))
        self.assertAlmostEqual(r["urgency_ratio"], URGENCY_RATIO_CAP, places=4)

    def test_urgency_ratio_expired_is_cap(self):
        r = A().analyze(make_pos(hours_to_deadline=0.0))
        self.assertAlmostEqual(r["urgency_ratio"], URGENCY_RATIO_CAP, places=4)

    def test_is_expired_true(self):
        r = A().analyze(make_pos(hours_to_deadline=0.0))
        self.assertTrue(r["is_expired"])

    def test_is_expired_false(self):
        r = A().analyze(make_pos(hours_to_deadline=400.0))
        self.assertFalse(r["is_expired"])

    def test_hours_to_deadline_negative_clamped(self):
        r = A().analyze(make_pos(hours_to_deadline=-10.0))
        self.assertAlmostEqual(r["hours_to_deadline"], 0.0)
        self.assertTrue(r["is_expired"])

    def test_miss_probability_low(self):
        # ratio 0.25 → miss 0.25
        r = A().analyze(make_pos(claim_cadence_hours=100.0,
                                 hours_to_deadline=400.0))
        self.assertAlmostEqual(r["miss_probability"], 0.25, places=4)

    def test_miss_probability_at_half(self):
        # ratio 0.5 → miss 0.5
        r = A().analyze(make_pos(claim_cadence_hours=100.0,
                                 hours_to_deadline=200.0))
        self.assertAlmostEqual(r["miss_probability"], 0.5, places=4)

    def test_miss_probability_saturates_at_one(self):
        # ratio 7.0 → miss 1.0
        r = A().analyze(make_pos(claim_cadence_hours=168.0,
                                 hours_to_deadline=24.0))
        self.assertAlmostEqual(r["miss_probability"], 1.0, places=4)

    def test_miss_probability_monotonic(self):
        prev = None
        for dl in (1000.0, 400.0, 200.0, 100.0, 50.0):
            r = A().analyze(make_pos(claim_cadence_hours=100.0,
                                     hours_to_deadline=dl))
            if prev is not None:
                self.assertGreaterEqual(r["miss_probability"], prev - 1e-9)
            prev = r["miss_probability"]

    def test_expected_forfeit_usd(self):
        # 100 * 1.0 * 0.25 = 25.0
        r = A().analyze(make_pos(unclaimed_reward_usd=100.0,
                                 claim_cadence_hours=100.0,
                                 hours_to_deadline=400.0,
                                 forfeit_fraction=1.0))
        self.assertAlmostEqual(r["expected_forfeit_usd"], 25.0, places=4)

    def test_expected_forfeit_usd_partial_fraction(self):
        # 100 * 0.5 * 0.25 = 12.5
        r = A().analyze(make_pos(unclaimed_reward_usd=100.0,
                                 claim_cadence_hours=100.0,
                                 hours_to_deadline=400.0,
                                 forfeit_fraction=0.5))
        self.assertAlmostEqual(r["expected_forfeit_usd"], 12.5, places=4)

    def test_expected_forfeit_pct(self):
        # 25/100 * 100 = 25.0
        r = A().analyze(make_pos(unclaimed_reward_usd=100.0,
                                 claim_cadence_hours=100.0,
                                 hours_to_deadline=400.0))
        self.assertAlmostEqual(r["expected_forfeit_pct"], 25.0, places=4)

    def test_expected_forfeit_full_when_expired(self):
        # expired → miss 1.0 → forfeit = unclaimed
        r = A().analyze(make_pos(unclaimed_reward_usd=200.0,
                                 hours_to_deadline=0.0,
                                 forfeit_fraction=1.0))
        self.assertAlmostEqual(r["expected_forfeit_usd"], 200.0, places=4)
        self.assertAlmostEqual(r["expected_forfeit_pct"], 100.0, places=4)

    def test_forfeit_fraction_clamped_high(self):
        r = A().analyze(make_pos(forfeit_fraction=5.0))
        self.assertAlmostEqual(r["forfeit_fraction"], 1.0)

    def test_forfeit_fraction_clamped_low(self):
        r = A().analyze(make_pos(forfeit_fraction=-1.0))
        self.assertAlmostEqual(r["forfeit_fraction"], 0.0)

    def test_cadence_default_when_zero(self):
        r = A().analyze(make_pos(claim_cadence_hours=0.0))
        self.assertAlmostEqual(r["claim_cadence_hours"],
                               DEFAULT_CLAIM_CADENCE_HOURS)

    def test_cadence_default_when_negative(self):
        r = A().analyze(make_pos(claim_cadence_hours=-5.0))
        self.assertAlmostEqual(r["claim_cadence_hours"],
                               DEFAULT_CLAIM_CADENCE_HOURS)

    def test_cadence_default_when_missing(self):
        r = A().analyze({"vault": "X", "unclaimed_reward_usd": 100.0,
                         "hours_to_deadline": 400.0})
        self.assertAlmostEqual(r["claim_cadence_hours"],
                               DEFAULT_CLAIM_CADENCE_HOURS)

    def test_unclaimed_passthrough(self):
        r = A().analyze(make_pos(unclaimed_reward_usd=250.0))
        self.assertAlmostEqual(r["unclaimed_reward_usd"], 250.0)

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos(unclaimed_reward_usd=123.4567,
                                 claim_cadence_hours=111.1111,
                                 hours_to_deadline=333.3333,
                                 forfeit_fraction=0.7777))
        for k in ("unclaimed_reward_usd", "hours_to_deadline",
                  "claim_cadence_hours", "forfeit_fraction", "urgency_ratio",
                  "miss_probability", "expected_forfeit_usd",
                  "expected_forfeit_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_safe(self):
        # ratio 0.25
        r = A().analyze(make_pos(claim_cadence_hours=100.0,
                                 hours_to_deadline=400.0))
        self.assertEqual(r["classification"], "SAFE")

    def test_safe_boundary(self):
        # ratio exactly 0.5 → SAFE
        r = A().analyze(make_pos(claim_cadence_hours=100.0,
                                 hours_to_deadline=200.0))
        self.assertEqual(r["classification"], "SAFE")

    def test_watch(self):
        # ratio 0.75
        r = A().analyze(make_pos(claim_cadence_hours=150.0,
                                 hours_to_deadline=200.0))
        self.assertEqual(r["classification"], "WATCH")

    def test_watch_boundary(self):
        # ratio exactly 1.0 → WATCH
        r = A().analyze(make_pos(claim_cadence_hours=100.0,
                                 hours_to_deadline=100.0))
        self.assertEqual(r["classification"], "WATCH")

    def test_at_risk(self):
        # ratio 1.5
        r = A().analyze(make_pos(claim_cadence_hours=150.0,
                                 hours_to_deadline=100.0))
        self.assertEqual(r["classification"], "AT_RISK")

    def test_at_risk_boundary(self):
        # ratio exactly 2.0 → AT_RISK
        r = A().analyze(make_pos(claim_cadence_hours=200.0,
                                 hours_to_deadline=100.0))
        self.assertEqual(r["classification"], "AT_RISK")

    def test_critical(self):
        # ratio 5.0
        r = A().analyze(make_pos(claim_cadence_hours=500.0,
                                 hours_to_deadline=100.0))
        self.assertEqual(r["classification"], "CRITICAL")

    def test_just_above_safe(self):
        # ratio 0.51 → WATCH
        r = A().analyze(make_pos(claim_cadence_hours=102.0,
                                 hours_to_deadline=200.0))
        self.assertEqual(r["classification"], "WATCH")

    def test_just_above_watch(self):
        # ratio 1.01 → AT_RISK
        r = A().analyze(make_pos(claim_cadence_hours=101.0,
                                 hours_to_deadline=100.0))
        self.assertEqual(r["classification"], "AT_RISK")

    def test_just_above_at_risk(self):
        # ratio 2.01 → CRITICAL
        r = A().analyze(make_pos(claim_cadence_hours=201.0,
                                 hours_to_deadline=100.0))
        self.assertEqual(r["classification"], "CRITICAL")

    def test_expired(self):
        r = A().analyze(make_pos(hours_to_deadline=0.0))
        self.assertEqual(r["classification"], "EXPIRED")

    def test_insufficient_no_unclaimed(self):
        r = A().analyze(make_pos(unclaimed_reward_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(hours_to_deadline=400.0),
                    make_pos(claim_cadence_hours=150.0,
                             hours_to_deadline=200.0),
                    make_pos(claim_cadence_hours=150.0,
                             hours_to_deadline=100.0),
                    make_pos(claim_cadence_hours=500.0,
                             hours_to_deadline=100.0),
                    make_pos(hours_to_deadline=0.0),
                    make_pos(unclaimed_reward_usd=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "SAFE", "WATCH", "AT_RISK", "CRITICAL", "EXPIRED",
                "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_no_action_safe(self):
        r = A().analyze(make_pos(hours_to_deadline=400.0))
        self.assertEqual(r["recommendation"], "NO_ACTION")

    def test_schedule_claim_watch(self):
        r = A().analyze(make_pos(claim_cadence_hours=150.0,
                                 hours_to_deadline=200.0))
        self.assertEqual(r["recommendation"], "SCHEDULE_CLAIM")

    def test_claim_soon_at_risk(self):
        r = A().analyze(make_pos(claim_cadence_hours=150.0,
                                 hours_to_deadline=100.0))
        self.assertEqual(r["recommendation"], "CLAIM_SOON")

    def test_claim_now_critical(self):
        r = A().analyze(make_pos(claim_cadence_hours=500.0,
                                 hours_to_deadline=100.0))
        self.assertEqual(r["recommendation"], "CLAIM_NOW")

    def test_deadline_passed_expired(self):
        r = A().analyze(make_pos(hours_to_deadline=0.0))
        self.assertEqual(r["recommendation"], "DEADLINE_PASSED_VERIFY")

    def test_verify_insufficient(self):
        r = A().analyze(make_pos(unclaimed_reward_usd=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_recommendation_matches_classification(self):
        mapping = {
            "SAFE": "NO_ACTION",
            "WATCH": "SCHEDULE_CLAIM",
            "AT_RISK": "CLAIM_SOON",
            "CRITICAL": "CLAIM_NOW",
            "EXPIRED": "DEADLINE_PASSED_VERIFY",
        }
        cases = [
            make_pos(hours_to_deadline=400.0),
            make_pos(claim_cadence_hours=150.0, hours_to_deadline=200.0),
            make_pos(claim_cadence_hours=150.0, hours_to_deadline=100.0),
            make_pos(claim_cadence_hours=500.0, hours_to_deadline=100.0),
            make_pos(hours_to_deadline=0.0),
        ]
        for pos in cases:
            r = A().analyze(pos)
            self.assertEqual(r["recommendation"], mapping[r["classification"]])


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_safe_flag(self):
        r = A().analyze(make_pos(hours_to_deadline=400.0))
        self.assertIn("SAFE", r["flags"])

    def test_watch_flag(self):
        r = A().analyze(make_pos(claim_cadence_hours=150.0,
                                 hours_to_deadline=200.0))
        self.assertIn("WATCH", r["flags"])

    def test_at_risk_flag(self):
        r = A().analyze(make_pos(claim_cadence_hours=150.0,
                                 hours_to_deadline=100.0))
        self.assertIn("AT_RISK", r["flags"])

    def test_critical_flag(self):
        r = A().analyze(make_pos(claim_cadence_hours=500.0,
                                 hours_to_deadline=100.0))
        self.assertIn("CRITICAL", r["flags"])

    def test_expired_flag(self):
        r = A().analyze(make_pos(hours_to_deadline=0.0))
        self.assertIn("EXPIRED", r["flags"])

    def test_high_miss_flag(self):
        # ratio 1.0 → miss 1.0 → high
        r = A().analyze(make_pos(claim_cadence_hours=100.0,
                                 hours_to_deadline=100.0))
        self.assertIn("HIGH_MISS_PROBABILITY", r["flags"])

    def test_high_miss_flag_boundary(self):
        # ratio 0.5 → miss 0.5 → flagged (>=0.5)
        r = A().analyze(make_pos(claim_cadence_hours=100.0,
                                 hours_to_deadline=200.0))
        self.assertIn("HIGH_MISS_PROBABILITY", r["flags"])

    def test_high_miss_flag_absent(self):
        # ratio 0.25 → miss 0.25 → not flagged
        r = A().analyze(make_pos(claim_cadence_hours=100.0,
                                 hours_to_deadline=400.0))
        self.assertNotIn("HIGH_MISS_PROBABILITY", r["flags"])

    def test_large_forfeit_flag(self):
        # expired → forfeit 200 >= 100
        r = A().analyze(make_pos(unclaimed_reward_usd=200.0,
                                 hours_to_deadline=0.0))
        self.assertIn("LARGE_FORFEIT_AT_RISK", r["flags"])

    def test_large_forfeit_flag_boundary(self):
        # forfeit exactly 100: unclaimed 200, miss 0.5 → 100
        r = A().analyze(make_pos(unclaimed_reward_usd=200.0,
                                 claim_cadence_hours=100.0,
                                 hours_to_deadline=200.0))
        self.assertAlmostEqual(r["expected_forfeit_usd"], 100.0, places=4)
        self.assertIn("LARGE_FORFEIT_AT_RISK", r["flags"])

    def test_large_forfeit_flag_absent(self):
        r = A().analyze(make_pos(unclaimed_reward_usd=10.0,
                                 hours_to_deadline=400.0))
        self.assertNotIn("LARGE_FORFEIT_AT_RISK", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(unclaimed_reward_usd=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_classification_flags_mutually_exclusive(self):
        r = A().analyze(make_pos(hours_to_deadline=400.0))
        self.assertIn("SAFE", r["flags"])
        self.assertNotIn("CRITICAL", r["flags"])

    def test_expired_no_double_flag(self):
        r = A().analyze(make_pos(hours_to_deadline=0.0))
        self.assertEqual(r["flags"].count("EXPIRED"), 1)

    def test_critical_and_large_forfeit_together(self):
        r = A().analyze(make_pos(unclaimed_reward_usd=500.0,
                                 claim_cadence_hours=500.0,
                                 hours_to_deadline=100.0))
        self.assertIn("CRITICAL", r["flags"])
        self.assertIn("HIGH_MISS_PROBABILITY", r["flags"])
        self.assertIn("LARGE_FORFEIT_AT_RISK", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_unclaimed(self):
        r = A().analyze(make_pos(unclaimed_reward_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_negative_unclaimed(self):
        r = A().analyze(make_pos(unclaimed_reward_usd=-50.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(unclaimed_reward_usd=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(unclaimed_reward_usd=0.0))
        self.assertEqual(r["recommendation"], "VERIFY_DATA")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_insufficient_metrics_none(self):
        r = A().analyze({})
        self.assertIsNone(r["urgency_ratio"])
        self.assertIsNone(r["miss_probability"])
        self.assertIsNone(r["expected_forfeit_usd"])
        self.assertIsNone(r["expected_forfeit_pct"])

    def test_insufficient_bools_false(self):
        r = A().analyze({})
        self.assertFalse(r["is_expired"])
        self.assertFalse(r["high_miss_probability"])
        self.assertFalse(r["large_forfeit"])

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_insufficient_numeric_zero(self):
        r = A().analyze({})
        for k in ("unclaimed_reward_usd", "hours_to_deadline", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_no_inf_nan(self):
        finite_check(self, A().analyze({}))

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_valid_with_unclaimed(self):
        r = A().analyze(make_pos())
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring ───────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_safer_scores_higher(self):
        safe = A().analyze(make_pos(hours_to_deadline=1000.0))
        risky = A().analyze(make_pos(claim_cadence_hours=500.0,
                                     hours_to_deadline=100.0))
        self.assertGreater(safe["score"], risky["score"])

    def test_zero_urgency_full_score(self):
        # tiny ratio → near full. ratio 0.01 → miss 0.01
        r = A().analyze(make_pos(claim_cadence_hours=1.0,
                                 hours_to_deadline=100000.0))
        self.assertGreater(r["score"], 99.0)

    def test_known_score(self):
        # ratio 0.25 → miss 0.25, forfeit_pct 25
        # safety = 70*(1-0.25)=52.5; size = 30*(1-0.25)=22.5; total 75.0
        r = A().analyze(make_pos(unclaimed_reward_usd=100.0,
                                 claim_cadence_hours=100.0,
                                 hours_to_deadline=400.0,
                                 forfeit_fraction=1.0))
        miss = 0.25
        pct = 25.0
        safety = 70.0 * (1.0 - miss)
        size = 30.0 * (1.0 - min(pct / FORFEIT_PCT_CEILING, 1.0))
        expected = safety + size
        self.assertAlmostEqual(r["score"], round(expected, 2), places=2)

    def test_known_score_half_miss(self):
        # ratio 0.5 → miss 0.5, forfeit_pct 50
        # safety 35; size 30*0.5=15 → 50.0
        r = A().analyze(make_pos(unclaimed_reward_usd=100.0,
                                 claim_cadence_hours=100.0,
                                 hours_to_deadline=200.0,
                                 forfeit_fraction=1.0))
        self.assertAlmostEqual(r["score"], 50.0, places=2)

    def test_expired_low_score(self):
        r = A().analyze(make_pos(hours_to_deadline=0.0))
        self.assertAlmostEqual(r["score"], EXPIRED_SCORE, places=4)

    def test_expired_grade_f(self):
        r = A().analyze(make_pos(hours_to_deadline=0.0))
        self.assertEqual(r["grade"], "F")

    def test_partial_forfeit_higher_score(self):
        full = A().analyze(make_pos(claim_cadence_hours=100.0,
                                    hours_to_deadline=200.0,
                                    forfeit_fraction=1.0))
        partial = A().analyze(make_pos(claim_cadence_hours=100.0,
                                       hours_to_deadline=200.0,
                                       forfeit_fraction=0.2))
        self.assertGreater(partial["score"], full["score"])

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(claim_cadence_hours=1e9,
                                 hours_to_deadline=1.0))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(unclaimed_reward_usd=1e9,
                                 claim_cadence_hours=1e9,
                                 hours_to_deadline=1e-9,
                                 forfeit_fraction=1.0))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(hours_to_deadline=400.0),
                    make_pos(claim_cadence_hours=500.0,
                             hours_to_deadline=100.0),
                    make_pos(hours_to_deadline=0.0),
                    make_pos(unclaimed_reward_usd=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(hours_to_deadline=1000.0),
                    make_pos(claim_cadence_hours=500.0,
                             hours_to_deadline=100.0)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))

    def test_higher_miss_lower_score(self):
        low = A().analyze(make_pos(claim_cadence_hours=100.0,
                                   hours_to_deadline=400.0))
        high = A().analyze(make_pos(claim_cadence_hours=100.0,
                                    hours_to_deadline=120.0))
        self.assertGreater(low["score"], high["score"])

    def test_monotonic_in_deadline(self):
        prev = None
        for dl in (50.0, 100.0, 200.0, 400.0, 1000.0):
            r = A().analyze(make_pos(claim_cadence_hours=100.0,
                                     hours_to_deadline=dl))
            if prev is not None:
                self.assertGreaterEqual(r["score"], prev - 1e-6)
            prev = r["score"]


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Safe", hours_to_deadline=1000.0),
            make_pos(vault="Risky", claim_cadence_hours=500.0,
                     hours_to_deadline=100.0, unclaimed_reward_usd=300.0),
            make_pos(vault="Mid", claim_cadence_hours=150.0,
                     hours_to_deadline=200.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_safest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["safest_vault"]], max(scores.values()))

    def test_most_at_risk_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_at_risk_vault"]],
                         min(scores.values()))

    def test_safest_is_safe(self):
        self.assertEqual(self.res["aggregate"]["safest_vault"], "Safe")

    def test_most_at_risk_is_risky(self):
        self.assertEqual(self.res["aggregate"]["most_at_risk_vault"], "Risky")

    def test_critical_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["critical_count"], 1)

    def test_total_expected_forfeit(self):
        total = self.res["aggregate"]["total_expected_forfeit_usd"]
        manual = sum(p["expected_forfeit_usd"] for p in self.res["positions"]
                     if isinstance(p["expected_forfeit_usd"], (int, float)))
        self.assertAlmostEqual(total, round(manual, 4), places=2)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_critical_count_exact(self):
        res = A().analyze_portfolio([
            make_pos(vault="A", claim_cadence_hours=500.0,
                     hours_to_deadline=100.0),
            make_pos(vault="B", claim_cadence_hours=600.0,
                     hours_to_deadline=100.0),
            make_pos(vault="C", hours_to_deadline=1000.0),
        ])
        self.assertEqual(res["aggregate"]["critical_count"], 2)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["safest_vault"])
        self.assertIsNone(res["aggregate"]["most_at_risk_vault"])
        self.assertEqual(res["aggregate"]["total_expected_forfeit_usd"], 0.0)

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(unclaimed_reward_usd=0.0),
            make_pos(unclaimed_reward_usd=0.0),
        ])
        self.assertIsNone(res["aggregate"]["safest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["critical_count"], 0)
        self.assertEqual(res["aggregate"]["total_expected_forfeit_usd"], 0.0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["safest_vault"], "Solo")
        self.assertEqual(res["aggregate"]["most_at_risk_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good"),
            make_pos(vault="Ins", unclaimed_reward_usd=0.0),
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
                make_pos(vault="big", unclaimed_reward_usd=1e9,
                         claim_cadence_hours=1e9, hours_to_deadline=1e-9),
                make_pos(vault="ins", unclaimed_reward_usd=0.0),
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
            "unclaimed_reward_usd": "100",
            "hours_to_deadline": "400",
            "claim_cadence_hours": "100",
            "forfeit_fraction": "1.0",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "unclaimed_reward_usd": 100.0,
                         "hours_to_deadline": 400.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(unclaimed_reward_usd=0.0),
            make_pos(claim_cadence_hours=500.0, hours_to_deadline=100.0),
            make_pos(hours_to_deadline=0.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(claim_cadence_hours=500.0,
                             hours_to_deadline=100.0),
                    make_pos(unclaimed_reward_usd=0.0),
                    make_pos(hours_to_deadline=0.0),
                    make_pos(claim_cadence_hours=0.0),
                    make_pos(unclaimed_reward_usd=1e9,
                             claim_cadence_hours=1e9,
                             hours_to_deadline=1e-9),
                    make_pos(unclaimed_reward_usd=-1e9),
                    make_pos(hours_to_deadline=-1e9,
                             claim_cadence_hours=-1e9)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(unclaimed_reward_usd=1e12,
                                 claim_cadence_hours=1e9,
                                 hours_to_deadline=1e-9,
                                 forfeit_fraction=1.0))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(hours_to_deadline=-10.0,
                                 claim_cadence_hours=-8.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_expired_classification_for_zero_deadline(self):
        r = A().analyze(make_pos(hours_to_deadline=0.0))
        self.assertEqual(r["classification"], "EXPIRED")

    def test_none_inputs_no_crash(self):
        r = A().analyze({"vault": "X", "unclaimed_reward_usd": 100.0,
                         "hours_to_deadline": None,
                         "claim_cadence_hours": None,
                         "forfeit_fraction": None})
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_none_unclaimed_insufficient(self):
        r = A().analyze({"vault": "X", "unclaimed_reward_usd": None,
                         "hours_to_deadline": 400.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")


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

    def test_demo_includes_safe_and_critical(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("SAFE", classes)
        self.assertIn("CRITICAL", classes)

    def test_demo_includes_expired(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("EXPIRED", classes)

    def test_demo_spans_full_range(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        for c in ("SAFE", "WATCH", "AT_RISK", "CRITICAL", "EXPIRED",
                  "INSUFFICIENT_DATA"):
            self.assertIn(c, classes)

    def test_demo_includes_claim_now_and_no_action(self):
        res = A().analyze_portfolio(_demo_positions())
        recs = {p["recommendation"] for p in res["positions"]}
        self.assertIn("CLAIM_NOW", recs)
        self.assertIn("NO_ACTION", recs)

    def test_demo_includes_high_miss(self):
        res = A().analyze_portfolio(_demo_positions())
        hm = any("HIGH_MISS_PROBABILITY" in p["flags"]
                 for p in res["positions"])
        self.assertTrue(hm)

    def test_demo_includes_large_forfeit(self):
        res = A().analyze_portfolio(_demo_positions())
        lf = any("LARGE_FORFEIT_AT_RISK" in p["flags"]
                 for p in res["positions"])
        self.assertTrue(lf)

    def test_demo_total_forfeit_positive(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertGreater(
            res["aggregate"]["total_expected_forfeit_usd"], 0.0)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
