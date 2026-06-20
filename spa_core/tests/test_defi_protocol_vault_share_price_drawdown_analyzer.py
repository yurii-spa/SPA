"""
Tests for MP-1168: DeFiProtocolVaultSharePriceDrawdownAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_share_price_drawdown_analyzer -v
"""

import json
import math
import os
import sys
import unittest
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spa_core.analytics.defi_protocol_vault_share_price_drawdown_analyzer import (
    DeFiProtocolVaultSharePriceDrawdownAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DRAWDOWN_SCORE_CEILING_PCT,
    UNDERWATER_DAYS_SCORE_CEILING,
    AT_HIGH_DRAWDOWN_PCT,
    SHALLOW_DRAWDOWN_PCT,
    MODERATE_DRAWDOWN_PCT,
    FRESH_DRAWDOWN_DAYS,
    STALE_DRAWDOWN_DAYS,
    DEEP_DRAWDOWN_FLAG_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    current_share_price_usd=0.95,
    high_water_mark_usd=1.0,
    entry_share_price_usd=0.90,
    days_underwater=10.0,
    recent_share_price_usd=0.94,
):
    return {
        "vault": vault,
        "current_share_price_usd": current_share_price_usd,
        "high_water_mark_usd": high_water_mark_usd,
        "entry_share_price_usd": entry_share_price_usd,
        "days_underwater": days_underwater,
        "recent_share_price_usd": recent_share_price_usd,
    }


def A():
    return DeFiProtocolVaultSharePriceDrawdownAnalyzer()


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

    def test_constants_sane(self):
        self.assertGreater(DRAWDOWN_SCORE_CEILING_PCT, 0)
        self.assertGreater(UNDERWATER_DAYS_SCORE_CEILING, 0)
        self.assertLess(AT_HIGH_DRAWDOWN_PCT, SHALLOW_DRAWDOWN_PCT)
        self.assertLess(SHALLOW_DRAWDOWN_PCT, MODERATE_DRAWDOWN_PCT)
        self.assertLess(FRESH_DRAWDOWN_DAYS, STALE_DRAWDOWN_DAYS)
        self.assertGreater(DEEP_DRAWDOWN_FLAG_PCT, 0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "current_share_price_usd", "high_water_mark_usd",
            "entry_share_price_usd", "days_underwater", "recent_share_price_usd",
            "drawdown_pct", "recovery_needed_pct", "underwater_vs_entry_pct",
            "position_underwater", "is_stale_drawdown", "recovering",
            "deepening", "trend_pct", "score", "classification",
            "recommendation", "grade", "flags",
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
        r = A().analyze({"token": "AltKey", "current_share_price_usd": 0.9,
                         "high_water_mark_usd": 1.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "current_share_price_usd": 0.9,
                         "high_water_mark_usd": 1.0})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"current_share_price_usd": 0.9,
                         "high_water_mark_usd": 1.0})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "HOLD", "HOLD_FOR_RECOVERY", "EXIT",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "AT_HIGH", "SHALLOW_DRAWDOWN", "MODERATE_DRAWDOWN",
            "DEEP_DRAWDOWN", "INSUFFICIENT_DATA",
        })

    def test_position_underwater_is_bool(self):
        self.assertIsInstance(self.r["position_underwater"], bool)

    def test_recovering_is_bool(self):
        self.assertIsInstance(self.r["recovering"], bool)

    def test_deepening_is_bool(self):
        self.assertIsInstance(self.r["deepening"], bool)

    def test_stale_is_bool(self):
        self.assertIsInstance(self.r["is_stale_drawdown"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_days_underwater_negative_clamped(self):
        r = A().analyze(make_pos(days_underwater=-10.0))
        self.assertAlmostEqual(r["days_underwater"], 0.0)

    def test_drawdown_pct(self):
        # (1.0 - 0.95)/1.0 * 100 = 5.0
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 high_water_mark_usd=1.0))
        self.assertAlmostEqual(r["drawdown_pct"], 5.0)

    def test_drawdown_pct_at_high(self):
        r = A().analyze(make_pos(current_share_price_usd=1.0,
                                 high_water_mark_usd=1.0))
        self.assertAlmostEqual(r["drawdown_pct"], 0.0)

    def test_drawdown_pct_clamped_above_hwm(self):
        # current above hwm → drawdown clamped to 0
        r = A().analyze(make_pos(current_share_price_usd=1.2,
                                 high_water_mark_usd=1.0))
        self.assertAlmostEqual(r["drawdown_pct"], 0.0)

    def test_drawdown_deep(self):
        # (1.0 - 0.7)/1.0*100 = 30
        r = A().analyze(make_pos(current_share_price_usd=0.7,
                                 high_water_mark_usd=1.0))
        self.assertAlmostEqual(r["drawdown_pct"], 30.0)

    def test_recovery_needed_pct(self):
        # (1.0/0.95 - 1)*100 = 5.263...
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 high_water_mark_usd=1.0))
        self.assertAlmostEqual(r["recovery_needed_pct"],
                               (1.0 / 0.95 - 1.0) * 100.0, places=2)

    def test_recovery_needed_zero_at_high(self):
        r = A().analyze(make_pos(current_share_price_usd=1.0,
                                 high_water_mark_usd=1.0))
        self.assertAlmostEqual(r["recovery_needed_pct"], 0.0)

    def test_recovery_needed_clamped_when_above(self):
        r = A().analyze(make_pos(current_share_price_usd=1.2,
                                 high_water_mark_usd=1.0))
        self.assertAlmostEqual(r["recovery_needed_pct"], 0.0)

    def test_underwater_vs_entry_pct(self):
        # (0.90 - 0.95)/0.90 * 100 = -5.555...
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 entry_share_price_usd=0.90))
        self.assertAlmostEqual(r["underwater_vs_entry_pct"],
                               (0.90 - 0.95) / 0.90 * 100.0, places=2)

    def test_underwater_vs_entry_positive(self):
        # current below entry → positive
        r = A().analyze(make_pos(current_share_price_usd=0.85,
                                 entry_share_price_usd=0.95))
        self.assertGreater(r["underwater_vs_entry_pct"], 0.0)

    def test_underwater_vs_entry_zero_no_entry(self):
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 entry_share_price_usd=0.0))
        self.assertAlmostEqual(r["underwater_vs_entry_pct"], 0.0)

    def test_position_underwater_true(self):
        r = A().analyze(make_pos(current_share_price_usd=0.85,
                                 entry_share_price_usd=0.95))
        self.assertTrue(r["position_underwater"])

    def test_position_underwater_false_above_entry(self):
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 entry_share_price_usd=0.90))
        self.assertFalse(r["position_underwater"])

    def test_position_underwater_false_no_entry(self):
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 entry_share_price_usd=0.0))
        self.assertFalse(r["position_underwater"])

    def test_is_stale_drawdown_true(self):
        r = A().analyze(make_pos(days_underwater=35.0))
        self.assertTrue(r["is_stale_drawdown"])

    def test_is_stale_drawdown_boundary(self):
        r = A().analyze(make_pos(days_underwater=30.0))
        self.assertTrue(r["is_stale_drawdown"])

    def test_is_stale_drawdown_false(self):
        r = A().analyze(make_pos(days_underwater=10.0))
        self.assertFalse(r["is_stale_drawdown"])

    def test_recovering_true(self):
        # current 0.95 > recent 0.90
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 recent_share_price_usd=0.90))
        self.assertTrue(r["recovering"])
        self.assertFalse(r["deepening"])

    def test_deepening_true(self):
        # current 0.90 < recent 0.95
        r = A().analyze(make_pos(current_share_price_usd=0.90,
                                 recent_share_price_usd=0.95))
        self.assertTrue(r["deepening"])
        self.assertFalse(r["recovering"])

    def test_flat_neither(self):
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 recent_share_price_usd=0.95))
        self.assertFalse(r["recovering"])
        self.assertFalse(r["deepening"])

    def test_no_recent_neither(self):
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 recent_share_price_usd=0.0))
        self.assertFalse(r["recovering"])
        self.assertFalse(r["deepening"])

    def test_trend_pct(self):
        # (0.95/0.90 - 1)*100 = 5.555...
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 recent_share_price_usd=0.90))
        self.assertAlmostEqual(r["trend_pct"],
                               (0.95 / 0.90 - 1.0) * 100.0, places=2)

    def test_trend_pct_negative(self):
        r = A().analyze(make_pos(current_share_price_usd=0.90,
                                 recent_share_price_usd=0.95))
        self.assertLess(r["trend_pct"], 0.0)

    def test_trend_pct_zero_no_recent(self):
        r = A().analyze(make_pos(recent_share_price_usd=0.0))
        self.assertAlmostEqual(r["trend_pct"], 0.0)

    def test_passthrough_fields(self):
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 high_water_mark_usd=1.0,
                                 entry_share_price_usd=0.90,
                                 recent_share_price_usd=0.94))
        self.assertAlmostEqual(r["current_share_price_usd"], 0.95)
        self.assertAlmostEqual(r["high_water_mark_usd"], 1.0)
        self.assertAlmostEqual(r["entry_share_price_usd"], 0.90)
        self.assertAlmostEqual(r["recent_share_price_usd"], 0.94)

    def test_all_metrics_rounded(self):
        r = A().analyze(make_pos())
        for k in ("drawdown_pct", "recovery_needed_pct",
                  "underwater_vs_entry_pct", "trend_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_at_high(self):
        # drawdown 0 <= 0.5
        r = A().analyze(make_pos(current_share_price_usd=1.0,
                                 high_water_mark_usd=1.0))
        self.assertEqual(r["classification"], "AT_HIGH")

    def test_at_high_boundary(self):
        # drawdown ~0.4 (just inside AT_HIGH band)
        r = A().analyze(make_pos(current_share_price_usd=0.996,
                                 high_water_mark_usd=1.0))
        self.assertEqual(r["classification"], "AT_HIGH")

    def test_shallow_drawdown(self):
        # drawdown ~4 (inside SHALLOW band)
        r = A().analyze(make_pos(current_share_price_usd=0.96,
                                 high_water_mark_usd=1.0))
        self.assertEqual(r["classification"], "SHALLOW_DRAWDOWN")

    def test_shallow_drawdown_mid(self):
        # drawdown 3.0
        r = A().analyze(make_pos(current_share_price_usd=0.97,
                                 high_water_mark_usd=1.0))
        self.assertEqual(r["classification"], "SHALLOW_DRAWDOWN")

    def test_moderate_drawdown(self):
        # drawdown 10.0
        r = A().analyze(make_pos(current_share_price_usd=0.90,
                                 high_water_mark_usd=1.0))
        self.assertEqual(r["classification"], "MODERATE_DRAWDOWN")

    def test_moderate_drawdown_boundary(self):
        # drawdown exactly 20
        r = A().analyze(make_pos(current_share_price_usd=0.80,
                                 high_water_mark_usd=1.0))
        self.assertEqual(r["classification"], "MODERATE_DRAWDOWN")

    def test_deep_drawdown(self):
        # drawdown 30
        r = A().analyze(make_pos(current_share_price_usd=0.70,
                                 high_water_mark_usd=1.0))
        self.assertEqual(r["classification"], "DEEP_DRAWDOWN")

    def test_insufficient_no_current(self):
        r = A().analyze(make_pos(current_share_price_usd=0.0,
                                 high_water_mark_usd=1.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_no_hwm(self):
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 high_water_mark_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_classification_known_value(self):
        for pos in [make_pos(current_share_price_usd=1.0),
                    make_pos(current_share_price_usd=0.95),
                    make_pos(current_share_price_usd=0.90),
                    make_pos(current_share_price_usd=0.70),
                    make_pos(current_share_price_usd=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "AT_HIGH", "SHALLOW_DRAWDOWN", "MODERATE_DRAWDOWN",
                "DEEP_DRAWDOWN", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_hold_at_high(self):
        r = A().analyze(make_pos(current_share_price_usd=1.0,
                                 high_water_mark_usd=1.0,
                                 recent_share_price_usd=1.0))
        self.assertEqual(r["recommendation"], "HOLD")

    def test_hold_shallow(self):
        r = A().analyze(make_pos(current_share_price_usd=0.96,
                                 high_water_mark_usd=1.0,
                                 recent_share_price_usd=0.96))
        self.assertEqual(r["recommendation"], "HOLD")

    def test_hold_for_recovery_moderate(self):
        # moderate, not recovering
        r = A().analyze(make_pos(current_share_price_usd=0.90,
                                 high_water_mark_usd=1.0,
                                 recent_share_price_usd=0.90))
        self.assertEqual(r["recommendation"], "HOLD_FOR_RECOVERY")

    def test_moderate_recovering_softens_to_hold(self):
        # moderate but recovering → HOLD
        r = A().analyze(make_pos(current_share_price_usd=0.90,
                                 high_water_mark_usd=1.0,
                                 recent_share_price_usd=0.85))
        self.assertEqual(r["recommendation"], "HOLD")

    def test_exit_deep(self):
        # deep, not recovering
        r = A().analyze(make_pos(current_share_price_usd=0.70,
                                 high_water_mark_usd=1.0,
                                 recent_share_price_usd=0.70))
        self.assertEqual(r["recommendation"], "EXIT")

    def test_deep_recovering_softens_to_hold_for_recovery(self):
        r = A().analyze(make_pos(current_share_price_usd=0.70,
                                 high_water_mark_usd=1.0,
                                 recent_share_price_usd=0.65))
        self.assertEqual(r["recommendation"], "HOLD_FOR_RECOVERY")

    def test_insufficient_rec(self):
        r = A().analyze(make_pos(current_share_price_usd=0.0,
                                 high_water_mark_usd=0.0))
        self.assertEqual(r["recommendation"], "HOLD")

    def test_rec_known_many(self):
        for pos in [make_pos(current_share_price_usd=1.0),
                    make_pos(current_share_price_usd=0.95),
                    make_pos(current_share_price_usd=0.90),
                    make_pos(current_share_price_usd=0.70)]:
            r = A().analyze(pos)
            self.assertIn(r["recommendation"],
                          {"HOLD", "HOLD_FOR_RECOVERY", "EXIT"})


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_at_high_flag(self):
        r = A().analyze(make_pos(current_share_price_usd=1.0,
                                 high_water_mark_usd=1.0))
        self.assertIn("AT_HIGH", r["flags"])

    def test_at_high_flag_absent(self):
        r = A().analyze(make_pos(current_share_price_usd=0.90,
                                 high_water_mark_usd=1.0))
        self.assertNotIn("AT_HIGH", r["flags"])

    def test_fresh_drawdown_flag(self):
        # days 2 < 7 and drawdown 5 > 0.5
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 high_water_mark_usd=1.0,
                                 days_underwater=2.0))
        self.assertIn("FRESH_DRAWDOWN", r["flags"])

    def test_fresh_drawdown_flag_absent_at_high(self):
        # at high → not fresh-drawdown even if 0 days
        r = A().analyze(make_pos(current_share_price_usd=1.0,
                                 high_water_mark_usd=1.0,
                                 days_underwater=2.0))
        self.assertNotIn("FRESH_DRAWDOWN", r["flags"])

    def test_fresh_drawdown_flag_absent_old(self):
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 high_water_mark_usd=1.0,
                                 days_underwater=20.0))
        self.assertNotIn("FRESH_DRAWDOWN", r["flags"])

    def test_stale_drawdown_flag(self):
        r = A().analyze(make_pos(days_underwater=40.0))
        self.assertIn("STALE_DRAWDOWN", r["flags"])

    def test_stale_drawdown_flag_absent(self):
        r = A().analyze(make_pos(days_underwater=10.0))
        self.assertNotIn("STALE_DRAWDOWN", r["flags"])

    def test_recovering_flag(self):
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 recent_share_price_usd=0.90))
        self.assertIn("RECOVERING", r["flags"])

    def test_deepening_flag(self):
        r = A().analyze(make_pos(current_share_price_usd=0.90,
                                 recent_share_price_usd=0.95))
        self.assertIn("DEEPENING", r["flags"])

    def test_position_underwater_flag(self):
        r = A().analyze(make_pos(current_share_price_usd=0.85,
                                 entry_share_price_usd=0.95))
        self.assertIn("POSITION_UNDERWATER", r["flags"])

    def test_position_underwater_flag_absent(self):
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 entry_share_price_usd=0.90))
        self.assertNotIn("POSITION_UNDERWATER", r["flags"])

    def test_deep_drawdown_flag(self):
        # drawdown 25 >= 20
        r = A().analyze(make_pos(current_share_price_usd=0.75,
                                 high_water_mark_usd=1.0))
        self.assertIn("DEEP_DRAWDOWN", r["flags"])

    def test_deep_drawdown_flag_boundary(self):
        # drawdown ~21 (at/above the deep flag threshold)
        r = A().analyze(make_pos(current_share_price_usd=0.79,
                                 high_water_mark_usd=1.0))
        self.assertIn("DEEP_DRAWDOWN", r["flags"])

    def test_deep_drawdown_flag_absent(self):
        r = A().analyze(make_pos(current_share_price_usd=0.90,
                                 high_water_mark_usd=1.0))
        self.assertNotIn("DEEP_DRAWDOWN", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(current_share_price_usd=0.0,
                                 high_water_mark_usd=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_current(self):
        r = A().analyze(make_pos(current_share_price_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_no_hwm(self):
        r = A().analyze(make_pos(high_water_mark_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(current_share_price_usd=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(current_share_price_usd=0.0))
        self.assertEqual(r["recommendation"], "HOLD")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_negative_current_insufficient(self):
        r = A().analyze(make_pos(current_share_price_usd=-1.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_hwm_insufficient(self):
        r = A().analyze(make_pos(high_water_mark_usd=-1.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_all_numeric_zero(self):
        r = A().analyze({})
        for k in ("current_share_price_usd", "high_water_mark_usd",
                  "entry_share_price_usd", "days_underwater",
                  "recent_share_price_usd", "drawdown_pct",
                  "recovery_needed_pct", "underwater_vs_entry_pct",
                  "trend_pct", "score"):
            self.assertAlmostEqual(r[k], 0.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["position_underwater"])
        self.assertFalse(r["recovering"])
        self.assertFalse(r["deepening"])
        self.assertFalse(r["is_stale_drawdown"])

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_json_serializable(self):
        json.dumps(A().analyze({}))

    def test_valid_when_both_present(self):
        r = A().analyze(make_pos(current_share_price_usd=0.95,
                                 high_water_mark_usd=1.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_shallower_drawdown_scores_higher(self):
        shallow = A().analyze(make_pos(current_share_price_usd=0.98,
                                       high_water_mark_usd=1.0,
                                       recent_share_price_usd=0.98))
        deep = A().analyze(make_pos(current_share_price_usd=0.70,
                                    high_water_mark_usd=1.0,
                                    recent_share_price_usd=0.70))
        self.assertGreater(shallow["score"], deep["score"])

    def test_fresher_scores_higher(self):
        fresh = A().analyze(make_pos(current_share_price_usd=0.95,
                                     high_water_mark_usd=1.0,
                                     days_underwater=2.0,
                                     recent_share_price_usd=0.95))
        stale = A().analyze(make_pos(current_share_price_usd=0.95,
                                     high_water_mark_usd=1.0,
                                     days_underwater=55.0,
                                     recent_share_price_usd=0.95))
        self.assertGreater(fresh["score"], stale["score"])

    def test_recovering_scores_higher_than_deepening(self):
        rec = A().analyze(make_pos(current_share_price_usd=0.95,
                                   high_water_mark_usd=1.0,
                                   recent_share_price_usd=0.90))
        deep = A().analyze(make_pos(current_share_price_usd=0.95,
                                    high_water_mark_usd=1.0,
                                    recent_share_price_usd=0.97))
        self.assertGreater(rec["score"], deep["score"])

    def test_at_high_scores_high(self):
        r = A().analyze(make_pos(current_share_price_usd=1.0,
                                 high_water_mark_usd=1.0,
                                 days_underwater=0.0,
                                 recent_share_price_usd=0.99))
        self.assertGreater(r["score"], 85.0)

    def test_deep_deepening_scores_low(self):
        r = A().analyze(make_pos(current_share_price_usd=0.70,
                                 high_water_mark_usd=1.0,
                                 days_underwater=50.0,
                                 recent_share_price_usd=0.75))
        self.assertLess(r["score"], 40.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(current_share_price_usd=1e12,
                                 high_water_mark_usd=1e12,
                                 recent_share_price_usd=1.0))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(current_share_price_usd=0.01,
                                 high_water_mark_usd=1e9,
                                 days_underwater=1e9,
                                 recent_share_price_usd=0.02))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(current_share_price_usd=1.0),
                    make_pos(current_share_price_usd=0.95),
                    make_pos(current_share_price_usd=0.90),
                    make_pos(current_share_price_usd=0.70),
                    make_pos(current_share_price_usd=0.0)]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(current_share_price_usd=1.0),
                    make_pos(current_share_price_usd=0.70,
                             recent_share_price_usd=0.75)]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Shallow", current_share_price_usd=0.99,
                     high_water_mark_usd=1.0, days_underwater=1.0,
                     recent_share_price_usd=0.98),
            make_pos(vault="Deep", current_share_price_usd=0.70,
                     high_water_mark_usd=1.0, days_underwater=50.0,
                     recent_share_price_usd=0.72),
            make_pos(vault="Mid", current_share_price_usd=0.90,
                     high_water_mark_usd=1.0, days_underwater=20.0,
                     recent_share_price_usd=0.90),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_shallowest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["shallowest_vault"]], max(scores.values()))

    def test_deepest_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["deepest_vault"]], min(scores.values()))

    def test_shallowest_is_shallow(self):
        self.assertEqual(self.res["aggregate"]["shallowest_vault"], "Shallow")

    def test_deepest_is_deep(self):
        self.assertEqual(self.res["aggregate"]["deepest_vault"], "Deep")

    def test_deep_drawdown_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["deep_drawdown_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["shallowest_vault"])
        self.assertIsNone(res["aggregate"]["deepest_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(current_share_price_usd=0.0),
            make_pos(high_water_mark_usd=0.0),
        ])
        self.assertIsNone(res["aggregate"]["shallowest_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["deep_drawdown_count"], 0)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["shallowest_vault"], "Solo")
        self.assertEqual(res["aggregate"]["deepest_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", current_share_price_usd=0.99,
                     high_water_mark_usd=1.0),
            make_pos(vault="Ins", current_share_price_usd=0.0),
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
                make_pos(vault="big", current_share_price_usd=1e12,
                         high_water_mark_usd=1e12,
                         recent_share_price_usd=1.0),
                make_pos(vault="ins", current_share_price_usd=0.0),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)

    def test_log_none_fields_serialize_null(self):
        # insufficient result has no None float fields, but trend/etc finite;
        # ensure full json round-trips with nulls handled
        res = A().analyze({})
        raw = json.dumps(res)
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
            "current_share_price_usd": "0.95",
            "high_water_mark_usd": "1.0",
            "entry_share_price_usd": "0.90",
            "days_underwater": "10",
            "recent_share_price_usd": "0.94",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "current_share_price_usd": 0.95,
                         "high_water_mark_usd": 1.0})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(current_share_price_usd=0.0),
            make_pos(current_share_price_usd=0.70),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(current_share_price_usd=0.90),
                    make_pos(current_share_price_usd=0.0),
                    make_pos(high_water_mark_usd=0.0),
                    make_pos(current_share_price_usd=1e12,
                             high_water_mark_usd=1e12),
                    make_pos(recent_share_price_usd=0.0),
                    make_pos(days_underwater=1e9),
                    make_pos(current_share_price_usd=1e-9,
                             high_water_mark_usd=1e12),
                    make_pos(current_share_price_usd=-100.0)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_no_recent_no_crash(self):
        r = A().analyze(make_pos(recent_share_price_usd=0.0))
        self.assertAlmostEqual(r["trend_pct"], 0.0)
        self.assertFalse(r["recovering"])
        self.assertFalse(r["deepening"])
        finite_check(self, r)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(current_share_price_usd=1e9,
                                 high_water_mark_usd=1e12,
                                 entry_share_price_usd=1e12,
                                 days_underwater=1e9,
                                 recent_share_price_usd=1e8))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_tiny_current_no_inf(self):
        r = A().analyze(make_pos(current_share_price_usd=1e-12,
                                 high_water_mark_usd=1.0))
        finite_check(self, r)

    def test_negative_inputs_no_crash(self):
        r = A().analyze(make_pos(current_share_price_usd=-1.0,
                                 high_water_mark_usd=-1.0,
                                 entry_share_price_usd=-1.0,
                                 days_underwater=-10.0,
                                 recent_share_price_usd=-1.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_current_above_hwm_no_crash(self):
        r = A().analyze(make_pos(current_share_price_usd=1.5,
                                 high_water_mark_usd=1.0))
        self.assertAlmostEqual(r["drawdown_pct"], 0.0)
        self.assertAlmostEqual(r["recovery_needed_pct"], 0.0)
        finite_check(self, r)


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_positions_count(self):
        self.assertEqual(len(_demo_positions()), 3)

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

    def test_demo_includes_at_high(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("AT_HIGH", classes)

    def test_demo_includes_deep(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("DEEP_DRAWDOWN", classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
