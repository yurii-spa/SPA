"""
Tests for MP-1163: DeFiProtocolVaultInstantExitNavDiscountAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_instant_exit_nav_discount_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_instant_exit_nav_discount_analyzer import (
    DeFiProtocolVaultInstantExitNavDiscountAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    HIGH_DISCOUNT_PCT,
    MODERATE_DISCOUNT_PCT,
    MINIMAL_DISCOUNT_PCT,
    LONG_QUEUE_DAYS,
    HIGH_WAIT_COST_PCT,
    DAYS_PER_YEAR,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    position_usd=10000.0,
    nav_per_share_usd=1.0,
    instant_exit_price_usd=0.97,
    instant_exit_discount_pct=0.0,
    queue_wait_days=10.0,
    redeploy_apr_pct=10.0,
    vault_apr_pct=4.0,
):
    return {
        "vault": vault,
        "position_usd": position_usd,
        "nav_per_share_usd": nav_per_share_usd,
        "instant_exit_price_usd": instant_exit_price_usd,
        "instant_exit_discount_pct": instant_exit_discount_pct,
        "queue_wait_days": queue_wait_days,
        "redeploy_apr_pct": redeploy_apr_pct,
        "vault_apr_pct": vault_apr_pct,
    }


def A():
    return DeFiProtocolVaultInstantExitNavDiscountAnalyzer()


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

    def test_f_float_passthrough(self):
        self.assertEqual(_f(1.25), 1.25)

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
        self.assertEqual(_clamp(-0.5, 0.0, 1.0), 0.0)

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

    def test_constants_sane(self):
        self.assertEqual(DAYS_PER_YEAR, 365.0)
        self.assertLess(MINIMAL_DISCOUNT_PCT, MODERATE_DISCOUNT_PCT)
        self.assertLess(MODERATE_DISCOUNT_PCT, HIGH_DISCOUNT_PCT)
        self.assertGreater(LONG_QUEUE_DAYS, 0)
        self.assertGreater(HIGH_WAIT_COST_PCT, 0)

    def test_constant_values(self):
        self.assertEqual(HIGH_DISCOUNT_PCT, 5.0)
        self.assertEqual(MODERATE_DISCOUNT_PCT, 2.0)
        self.assertEqual(MINIMAL_DISCOUNT_PCT, 0.5)
        self.assertEqual(LONG_QUEUE_DAYS, 30.0)
        self.assertEqual(HIGH_WAIT_COST_PCT, 5.0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "position_usd", "nav_per_share_usd",
            "instant_exit_price_usd", "instant_exit_discount_pct",
            "queue_wait_days", "redeploy_apr_pct", "vault_apr_pct",
            "instant_exit_cost_usd", "excess_apr_pct",
            "wait_opportunity_cost_pct", "wait_opportunity_cost_usd",
            "breakeven_wait_days", "instant_cheaper",
            "savings_by_waiting_pct", "savings_by_waiting_usd",
            "has_queue_option", "score", "classification",
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
        r = A().analyze({"token": "AltKey", "nav_per_share_usd": 1.0,
                         "instant_exit_price_usd": 0.95})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T",
                         "nav_per_share_usd": 1.0,
                         "instant_exit_price_usd": 0.95})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"nav_per_share_usd": 1.0,
                         "instant_exit_price_usd": 0.95})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "EXIT_OK", "EXIT_INSTANT", "WAIT_FOR_NAV",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_instant_cheaper_is_bool(self):
        self.assertIsInstance(self.r["instant_cheaper"], bool)

    def test_has_queue_option_is_bool(self):
        self.assertIsInstance(self.r["has_queue_option"], bool)

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "MINIMAL_DISCOUNT", "LOW_DISCOUNT", "MODERATE_DISCOUNT",
            "STEEP_DISCOUNT", "INSUFFICIENT_DATA",
        })


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_discount_derived_from_nav_price(self):
        # nav 1.0, price 0.95 → 5% discount
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.95))
        self.assertAlmostEqual(r["instant_exit_discount_pct"], 5.0, places=4)

    def test_discount_derived_3pct(self):
        r = A().analyze(make_pos(nav_per_share_usd=2.0,
                                 instant_exit_price_usd=1.94))
        # (2-1.94)/2*100 = 3.0
        self.assertAlmostEqual(r["instant_exit_discount_pct"], 3.0, places=4)

    def test_discount_fallback_to_direct_input(self):
        # nav or price missing → use direct discount input
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=4.0,
                                 queue_wait_days=5.0))
        self.assertAlmostEqual(r["instant_exit_discount_pct"], 4.0, places=4)

    def test_discount_fallback_when_price_zero(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=3.0,
                                 queue_wait_days=5.0))
        self.assertAlmostEqual(r["instant_exit_discount_pct"], 3.0, places=4)

    def test_discount_derived_overrides_direct(self):
        # both present → nav/price wins over direct input
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.90,
                                 instant_exit_discount_pct=2.0))
        self.assertAlmostEqual(r["instant_exit_discount_pct"], 10.0, places=4)

    def test_discount_clamped_when_price_above_nav(self):
        # price > nav → negative raw discount → clamped to 0
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=1.10,
                                 queue_wait_days=5.0))
        self.assertAlmostEqual(r["instant_exit_discount_pct"], 0.0, places=4)

    def test_discount_direct_clamped_high(self):
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=250.0,
                                 queue_wait_days=5.0))
        self.assertAlmostEqual(r["instant_exit_discount_pct"], 100.0, places=4)

    def test_discount_direct_clamped_low(self):
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=-5.0,
                                 queue_wait_days=5.0))
        self.assertAlmostEqual(r["instant_exit_discount_pct"], 0.0, places=4)

    def test_position_usd_negative_clamped(self):
        r = A().analyze(make_pos(position_usd=-100.0))
        self.assertAlmostEqual(r["position_usd"], 0.0)

    def test_nav_negative_clamped(self):
        r = A().analyze(make_pos(nav_per_share_usd=-1.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=3.0,
                                 queue_wait_days=5.0))
        self.assertAlmostEqual(r["nav_per_share_usd"], 0.0)

    def test_price_negative_clamped(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=-0.5,
                                 instant_exit_discount_pct=3.0,
                                 queue_wait_days=5.0))
        self.assertAlmostEqual(r["instant_exit_price_usd"], 0.0)

    def test_queue_wait_negative_clamped(self):
        r = A().analyze(make_pos(queue_wait_days=-10.0))
        self.assertAlmostEqual(r["queue_wait_days"], 0.0)

    def test_redeploy_apr_negative_clamped(self):
        r = A().analyze(make_pos(redeploy_apr_pct=-5.0))
        self.assertAlmostEqual(r["redeploy_apr_pct"], 0.0)

    def test_vault_apr_negative_clamped(self):
        r = A().analyze(make_pos(vault_apr_pct=-5.0))
        self.assertAlmostEqual(r["vault_apr_pct"], 0.0)

    def test_instant_exit_cost_usd(self):
        # discount 5% on 10000 → 500
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.95,
                                 position_usd=10000.0))
        self.assertAlmostEqual(r["instant_exit_cost_usd"], 500.0, places=2)

    def test_excess_apr_pct(self):
        # redeploy 10, vault 4 → 6
        r = A().analyze(make_pos(redeploy_apr_pct=10.0, vault_apr_pct=4.0))
        self.assertAlmostEqual(r["excess_apr_pct"], 6.0, places=4)

    def test_excess_apr_floored_at_zero(self):
        # vault apr higher than redeploy → excess 0
        r = A().analyze(make_pos(redeploy_apr_pct=3.0, vault_apr_pct=8.0))
        self.assertAlmostEqual(r["excess_apr_pct"], 0.0, places=4)

    def test_wait_opportunity_cost_pct(self):
        # excess 6%, queue 10 days → 6*10/365
        r = A().analyze(make_pos(redeploy_apr_pct=10.0, vault_apr_pct=4.0,
                                 queue_wait_days=10.0))
        self.assertAlmostEqual(r["wait_opportunity_cost_pct"],
                               6.0 * 10.0 / 365.0, places=4)

    def test_wait_opportunity_cost_usd(self):
        r = A().analyze(make_pos(redeploy_apr_pct=10.0, vault_apr_pct=4.0,
                                 queue_wait_days=10.0, position_usd=10000.0))
        expected = 10000.0 * (6.0 * 10.0 / 365.0) / 100.0
        self.assertAlmostEqual(r["wait_opportunity_cost_usd"], expected,
                               places=2)

    def test_wait_cost_zero_when_no_excess(self):
        r = A().analyze(make_pos(redeploy_apr_pct=2.0, vault_apr_pct=8.0))
        self.assertAlmostEqual(r["wait_opportunity_cost_pct"], 0.0)

    def test_wait_cost_zero_when_no_queue(self):
        r = A().analyze(make_pos(queue_wait_days=0.0,
                                 nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.95))
        self.assertAlmostEqual(r["wait_opportunity_cost_pct"], 0.0)

    def test_breakeven_none_when_no_excess(self):
        r = A().analyze(make_pos(redeploy_apr_pct=2.0, vault_apr_pct=8.0))
        self.assertIsNone(r["breakeven_wait_days"])

    def test_breakeven_numeric_when_excess(self):
        # discount 5%, excess 6% → 5*365/6
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.95,
                                 redeploy_apr_pct=10.0, vault_apr_pct=4.0))
        self.assertIsNotNone(r["breakeven_wait_days"])
        self.assertAlmostEqual(r["breakeven_wait_days"],
                               5.0 * 365.0 / 6.0, places=4)

    def test_breakeven_is_float_or_none(self):
        r = A().analyze(make_pos())
        self.assertTrue(r["breakeven_wait_days"] is None
                        or isinstance(r["breakeven_wait_days"], float))

    def test_savings_by_waiting_pct(self):
        # discount 5%, wait cost ~0.164% → savings positive
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.95,
                                 redeploy_apr_pct=10.0, vault_apr_pct=4.0,
                                 queue_wait_days=10.0))
        expected = 5.0 - (6.0 * 10.0 / 365.0)
        self.assertAlmostEqual(r["savings_by_waiting_pct"], expected, places=4)

    def test_savings_by_waiting_usd(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.95,
                                 redeploy_apr_pct=10.0, vault_apr_pct=4.0,
                                 queue_wait_days=10.0, position_usd=10000.0))
        pct = 5.0 - (6.0 * 10.0 / 365.0)
        self.assertAlmostEqual(r["savings_by_waiting_usd"],
                               10000.0 * pct / 100.0, places=2)

    def test_savings_floored_at_zero(self):
        # instant cheaper than waiting → savings 0
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.999,
                                 redeploy_apr_pct=50.0, vault_apr_pct=0.0,
                                 queue_wait_days=300.0))
        self.assertAlmostEqual(r["savings_by_waiting_pct"], 0.0)

    def test_has_queue_option_true(self):
        r = A().analyze(make_pos(queue_wait_days=10.0))
        self.assertTrue(r["has_queue_option"])

    def test_has_queue_option_false(self):
        r = A().analyze(make_pos(queue_wait_days=0.0,
                                 nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.95))
        self.assertFalse(r["has_queue_option"])

    def test_instant_cheaper_true(self):
        # tiny discount, huge wait cost → instant cheaper
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.999,
                                 redeploy_apr_pct=50.0, vault_apr_pct=0.0,
                                 queue_wait_days=300.0))
        self.assertTrue(r["instant_cheaper"])

    def test_instant_cheaper_false(self):
        # big discount, tiny wait cost → wait cheaper
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.90,
                                 redeploy_apr_pct=5.0, vault_apr_pct=4.0,
                                 queue_wait_days=5.0))
        self.assertFalse(r["instant_cheaper"])

    def test_instant_cheaper_boundary(self):
        # construct discount very close to wait cost via direct discount input.
        # excess 6, queue 365/6 → wait_cost = 6*(365/6)/365 = 1.0; discount 1.0
        q = 365.0 / 6.0
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=1.0,
                                 redeploy_apr_pct=10.0, vault_apr_pct=4.0,
                                 queue_wait_days=q))
        # discount_pct <= wait_cost_pct (==) → instant_cheaper True (<=)
        self.assertTrue(r["instant_cheaper"])
        self.assertAlmostEqual(r["instant_exit_discount_pct"],
                               r["wait_opportunity_cost_pct"], places=3)

    def test_all_numeric_rounded(self):
        r = A().analyze(make_pos())
        for k in ("instant_exit_cost_usd", "wait_opportunity_cost_pct",
                  "savings_by_waiting_pct"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_minimal_discount(self):
        # nav 1.0, price 0.997 → 0.3% <= 0.5
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.997))
        self.assertEqual(r["classification"], "MINIMAL_DISCOUNT")

    def test_minimal_discount_boundary(self):
        # exactly 0.5% → MINIMAL (<=); use direct input for an exact boundary
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=0.5,
                                 queue_wait_days=5.0))
        self.assertEqual(r["classification"], "MINIMAL_DISCOUNT")

    def test_low_discount(self):
        # 1.5% in (0.5, 2.0]
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.985))
        self.assertEqual(r["classification"], "LOW_DISCOUNT")

    def test_low_discount_boundary(self):
        # exactly 2.0% → LOW (<=); use direct input for an exact boundary
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=2.0,
                                 queue_wait_days=5.0))
        self.assertEqual(r["classification"], "LOW_DISCOUNT")

    def test_moderate_discount(self):
        # 3.5% in (2.0, 5.0]
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.965))
        self.assertEqual(r["classification"], "MODERATE_DISCOUNT")

    def test_moderate_discount_boundary(self):
        # exactly 5.0% → MODERATE (<=); use direct input for an exact boundary
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=5.0,
                                 queue_wait_days=5.0))
        self.assertEqual(r["classification"], "MODERATE_DISCOUNT")

    def test_steep_discount(self):
        # 7% > 5.0
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.93))
        self.assertEqual(r["classification"], "STEEP_DISCOUNT")

    def test_classification_known_value(self):
        for price in [0.997, 0.985, 0.965, 0.93]:
            r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                     instant_exit_price_usd=price))
            self.assertIn(r["classification"], {
                "MINIMAL_DISCOUNT", "LOW_DISCOUNT", "MODERATE_DISCOUNT",
                "STEEP_DISCOUNT",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_exit_instant_when_instant_cheaper(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.999,
                                 redeploy_apr_pct=50.0, vault_apr_pct=0.0,
                                 queue_wait_days=300.0))
        self.assertTrue(r["instant_cheaper"])
        self.assertEqual(r["recommendation"], "EXIT_INSTANT")

    def test_wait_for_nav_when_queue_and_not_cheaper(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.90,
                                 redeploy_apr_pct=5.0, vault_apr_pct=4.0,
                                 queue_wait_days=5.0))
        self.assertFalse(r["instant_cheaper"])
        self.assertTrue(r["has_queue_option"])
        self.assertEqual(r["recommendation"], "WAIT_FOR_NAV")

    def test_exit_instant_when_no_queue_option(self):
        # discount present, no queue → must exit instant
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.95,
                                 queue_wait_days=0.0))
        self.assertFalse(r["has_queue_option"])
        self.assertEqual(r["recommendation"], "EXIT_INSTANT")

    def test_exit_ok_when_insufficient(self):
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=0.0,
                                 queue_wait_days=0.0))
        self.assertEqual(r["recommendation"], "EXIT_OK")

    def test_recommendation_in_known_set(self):
        for pos in [make_pos(),
                    make_pos(queue_wait_days=0.0,
                             nav_per_share_usd=1.0,
                             instant_exit_price_usd=0.95),
                    make_pos(nav_per_share_usd=1.0,
                             instant_exit_price_usd=0.999,
                             redeploy_apr_pct=50.0, vault_apr_pct=0.0,
                             queue_wait_days=300.0)]:
            r = A().analyze(pos)
            self.assertIn(r["recommendation"],
                          {"EXIT_OK", "EXIT_INSTANT", "WAIT_FOR_NAV"})


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_nav_exit_available_flag(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.997))
        self.assertIn("NAV_EXIT_AVAILABLE", r["flags"])

    def test_nav_exit_available_boundary(self):
        # exactly minimal discount → flag (<=); direct input for exactness
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=0.5,
                                 queue_wait_days=5.0))
        self.assertIn("NAV_EXIT_AVAILABLE", r["flags"])

    def test_nav_exit_available_absent(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.93))
        self.assertNotIn("NAV_EXIT_AVAILABLE", r["flags"])

    def test_steep_exit_discount_flag(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.93))
        self.assertIn("STEEP_EXIT_DISCOUNT", r["flags"])

    def test_steep_exit_discount_boundary(self):
        # exactly 5% → flag (>=)
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.95))
        self.assertIn("STEEP_EXIT_DISCOUNT", r["flags"])

    def test_steep_exit_discount_absent(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.985))
        self.assertNotIn("STEEP_EXIT_DISCOUNT", r["flags"])

    def test_long_redemption_queue_flag(self):
        r = A().analyze(make_pos(queue_wait_days=45.0))
        self.assertIn("LONG_REDEMPTION_QUEUE", r["flags"])

    def test_long_redemption_queue_boundary(self):
        # exactly 30 days → flag (>=)
        r = A().analyze(make_pos(queue_wait_days=30.0))
        self.assertIn("LONG_REDEMPTION_QUEUE", r["flags"])

    def test_long_redemption_queue_absent(self):
        r = A().analyze(make_pos(queue_wait_days=10.0))
        self.assertNotIn("LONG_REDEMPTION_QUEUE", r["flags"])

    def test_instant_exit_cheaper_flag(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.999,
                                 redeploy_apr_pct=50.0, vault_apr_pct=0.0,
                                 queue_wait_days=300.0))
        self.assertIn("INSTANT_EXIT_CHEAPER", r["flags"])

    def test_instant_exit_cheaper_absent_when_no_queue(self):
        # instant_cheaper requires has_queue_option for the flag
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.95,
                                 queue_wait_days=0.0))
        self.assertNotIn("INSTANT_EXIT_CHEAPER", r["flags"])

    def test_wait_saves_vs_discount_flag(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.90,
                                 redeploy_apr_pct=5.0, vault_apr_pct=4.0,
                                 queue_wait_days=5.0))
        self.assertIn("WAIT_SAVES_VS_DISCOUNT", r["flags"])

    def test_wait_saves_vs_discount_absent(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.999,
                                 redeploy_apr_pct=50.0, vault_apr_pct=0.0,
                                 queue_wait_days=300.0))
        self.assertNotIn("WAIT_SAVES_VS_DISCOUNT", r["flags"])

    def test_high_wait_opportunity_cost_flag(self):
        # excess 50%, queue 60 days → 50*60/365 ~ 8.2% >= 5
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.95,
                                 redeploy_apr_pct=50.0, vault_apr_pct=0.0,
                                 queue_wait_days=60.0))
        self.assertIn("HIGH_WAIT_OPPORTUNITY_COST", r["flags"])

    def test_high_wait_opportunity_cost_absent(self):
        r = A().analyze(make_pos(redeploy_apr_pct=6.0, vault_apr_pct=4.0,
                                 queue_wait_days=5.0))
        self.assertNotIn("HIGH_WAIT_OPPORTUNITY_COST", r["flags"])

    def test_no_queue_option_flag(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.95,
                                 queue_wait_days=0.0))
        self.assertIn("NO_QUEUE_OPTION", r["flags"])

    def test_no_queue_option_absent_when_queue(self):
        r = A().analyze(make_pos(queue_wait_days=10.0))
        self.assertNotIn("NO_QUEUE_OPTION", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=0.0,
                                 queue_wait_days=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_only_one_flag(self):
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=0.0,
                                 queue_wait_days=0.0))
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])

    def test_flags_all_strings(self):
        r = A().analyze(make_pos())
        for f in r["flags"]:
            self.assertIsInstance(f, str)


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_discount_no_queue(self):
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=0.0,
                                 queue_wait_days=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_nav_equals_price_no_queue(self):
        # nav == price → 0 discount, no queue → insufficient
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=1.0,
                                 queue_wait_days=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=0.0,
                                 queue_wait_days=0.0))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation_exit_ok(self):
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=0.0,
                                 queue_wait_days=0.0))
        self.assertEqual(r["recommendation"], "EXIT_OK")

    def test_insufficient_breakeven_none(self):
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=0.0,
                                 queue_wait_days=0.0))
        self.assertIsNone(r["breakeven_wait_days"])

    def test_insufficient_bools_false(self):
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=0.0,
                                 queue_wait_days=0.0))
        self.assertFalse(r["instant_cheaper"])
        self.assertFalse(r["has_queue_option"])

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_only_queue_is_sufficient(self):
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=0.0,
                                 queue_wait_days=10.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_only_discount_is_sufficient(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.95,
                                 queue_wait_days=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_only_direct_discount_is_sufficient(self):
        r = A().analyze(make_pos(nav_per_share_usd=0.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=3.0,
                                 queue_wait_days=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_no_inf_nan(self):
        r = A().analyze({})
        finite_check(self, r)

    def test_insufficient_has_all_keys(self):
        r = A().analyze({})
        full = A().analyze(make_pos())
        self.assertEqual(set(r.keys()), set(full.keys()))

    def test_insufficient_json_serializable(self):
        r = A().analyze({})
        json.dumps(r)


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_lower_discount_scores_higher(self):
        low = A().analyze(make_pos(nav_per_share_usd=1.0,
                                   instant_exit_price_usd=0.99,
                                   queue_wait_days=10.0))
        high = A().analyze(make_pos(nav_per_share_usd=1.0,
                                    instant_exit_price_usd=0.92,
                                    queue_wait_days=10.0))
        self.assertGreater(low["score"], high["score"])

    def test_shorter_queue_scores_higher(self):
        short = A().analyze(make_pos(nav_per_share_usd=1.0,
                                     instant_exit_price_usd=0.97,
                                     queue_wait_days=2.0,
                                     redeploy_apr_pct=10.0, vault_apr_pct=4.0))
        long = A().analyze(make_pos(nav_per_share_usd=1.0,
                                    instant_exit_price_usd=0.97,
                                    queue_wait_days=25.0,
                                    redeploy_apr_pct=10.0, vault_apr_pct=4.0))
        self.assertGreater(short["score"], long["score"])

    def test_lower_wait_cost_scores_higher(self):
        low = A().analyze(make_pos(nav_per_share_usd=1.0,
                                   instant_exit_price_usd=0.97,
                                   queue_wait_days=10.0,
                                   redeploy_apr_pct=6.0, vault_apr_pct=4.0))
        high = A().analyze(make_pos(nav_per_share_usd=1.0,
                                    instant_exit_price_usd=0.97,
                                    queue_wait_days=10.0,
                                    redeploy_apr_pct=40.0, vault_apr_pct=0.0))
        self.assertGreater(low["score"], high["score"])

    def test_minimal_friction_scores_high(self):
        # tiny discount, no queue → near max score
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.999,
                                 queue_wait_days=0.0))
        self.assertGreater(r["score"], 85.0)

    def test_steep_long_high_cost_scores_low(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.90,
                                 queue_wait_days=60.0,
                                 redeploy_apr_pct=50.0, vault_apr_pct=0.0))
        self.assertLess(r["score"], 40.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.01,
                                 queue_wait_days=1e6,
                                 redeploy_apr_pct=1e6, vault_apr_pct=0.0,
                                 position_usd=1e12))
        self.assertLessEqual(r["score"], 100.0)
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_floor_zero(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.0,
                                 instant_exit_discount_pct=100.0,
                                 queue_wait_days=1000.0,
                                 redeploy_apr_pct=1000.0, vault_apr_pct=0.0))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_grade_matches_score(self):
        r = A().analyze(make_pos())
        self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Easy", nav_per_share_usd=1.0,
                     instant_exit_price_usd=0.999, queue_wait_days=0.0),
            make_pos(vault="Hard", nav_per_share_usd=1.0,
                     instant_exit_price_usd=0.90, queue_wait_days=60.0,
                     redeploy_apr_pct=50.0, vault_apr_pct=0.0),
            make_pos(vault="Mid", nav_per_share_usd=1.0,
                     instant_exit_price_usd=0.97, queue_wait_days=10.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_easiest_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["easiest_exit_vault"]],
                         max(scores.values()))

    def test_hardest_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["hardest_exit_vault"]],
                         min(scores.values()))

    def test_easiest_is_easy(self):
        self.assertEqual(self.res["aggregate"]["easiest_exit_vault"], "Easy")

    def test_hardest_is_hard(self):
        self.assertEqual(self.res["aggregate"]["hardest_exit_vault"], "Hard")

    def test_steep_discount_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["steep_discount_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["easiest_exit_vault"])
        self.assertIsNone(res["aggregate"]["hardest_exit_vault"])

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(nav_per_share_usd=0.0, instant_exit_price_usd=0.0,
                     instant_exit_discount_pct=0.0, queue_wait_days=0.0),
            make_pos(nav_per_share_usd=0.0, instant_exit_price_usd=0.0,
                     instant_exit_discount_pct=0.0, queue_wait_days=0.0),
        ])
        self.assertIsNone(res["aggregate"]["easiest_exit_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["easiest_exit_vault"], "Solo")
        self.assertEqual(res["aggregate"]["hardest_exit_vault"], "Solo")

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_steep_discount_count_counts_classification(self):
        res = A().analyze_portfolio([
            make_pos(vault="S", nav_per_share_usd=1.0,
                     instant_exit_price_usd=0.90, queue_wait_days=5.0),
        ])
        self.assertEqual(res["aggregate"]["steep_discount_count"], 1)

    def test_aggregate_has_all_keys(self):
        for k in ("easiest_exit_vault", "hardest_exit_vault", "avg_score",
                  "steep_discount_count", "position_count"):
            self.assertIn(k, self.res["aggregate"])

    def test_mixed_with_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good"),
            make_pos(vault="Ins", nav_per_share_usd=0.0,
                     instant_exit_price_usd=0.0,
                     instant_exit_discount_pct=0.0, queue_wait_days=0.0),
        ])
        self.assertEqual(res["aggregate"]["position_count"], 2)
        self.assertEqual(res["aggregate"]["easiest_exit_vault"], "Good")


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
                make_pos(vault="big", nav_per_share_usd=1.0,
                         instant_exit_price_usd=0.0,
                         instant_exit_discount_pct=100.0,
                         queue_wait_days=1e6, redeploy_apr_pct=1e6,
                         position_usd=1e9),
                make_pos(vault="ins", nav_per_share_usd=0.0,
                         instant_exit_price_usd=0.0,
                         instant_exit_discount_pct=0.0, queue_wait_days=0.0),
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

    def test_log_does_not_touch_production(self):
        before = os.path.exists(LOG_PATH)
        A().analyze(make_pos())
        after = os.path.exists(LOG_PATH)
        self.assertEqual(before, after)

    def test_no_write_analyze_does_not_create_production_log(self):
        # An analyze with default cfg and no write_log must not create or
        # modify the production LOG_PATH file.
        before_exists = os.path.exists(LOG_PATH)
        before_mtime = (os.path.getmtime(LOG_PATH)
                        if before_exists else None)
        A().analyze_portfolio(_demo_positions())
        after_exists = os.path.exists(LOG_PATH)
        self.assertEqual(before_exists, after_exists)
        if before_exists:
            self.assertEqual(before_mtime, os.path.getmtime(LOG_PATH))

    def test_breakeven_none_survives_json(self):
        # vault apr >= redeploy → breakeven None → null in json dump of result
        r = A().analyze(make_pos(redeploy_apr_pct=2.0, vault_apr_pct=8.0))
        self.assertIsNone(r["breakeven_wait_days"])
        raw = json.dumps(r)
        self.assertIn("null", raw)
        reloaded = json.loads(raw)
        self.assertIsNone(reloaded["breakeven_wait_days"])

    def test_log_write_with_breakeven_none_ok(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_pos(redeploy_apr_pct=2.0, vault_apr_pct=8.0),
                        cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "position_usd": "10000",
            "nav_per_share_usd": "1.0",
            "instant_exit_price_usd": "0.95",
            "queue_wait_days": "10",
            "redeploy_apr_pct": "10",
            "vault_apr_pct": "4",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "nav_per_share_usd": 1.0,
                         "instant_exit_price_usd": 0.95})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(nav_per_share_usd=0.0, instant_exit_price_usd=0.0,
                     instant_exit_discount_pct=0.0, queue_wait_days=0.0),
            make_pos(queue_wait_days=60.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(queue_wait_days=0.0,
                             nav_per_share_usd=1.0,
                             instant_exit_price_usd=0.95),
                    make_pos(nav_per_share_usd=0.0,
                             instant_exit_price_usd=0.0,
                             instant_exit_discount_pct=0.0,
                             queue_wait_days=0.0),
                    make_pos(nav_per_share_usd=1.0,
                             instant_exit_price_usd=0.0,
                             instant_exit_discount_pct=100.0,
                             queue_wait_days=1000.0),
                    make_pos(redeploy_apr_pct=-50.0),
                    make_pos(vault_apr_pct=-50.0),
                    make_pos(position_usd=-100.0),
                    make_pos(nav_per_share_usd=1.0,
                             instant_exit_price_usd=1.10,
                             queue_wait_days=5.0)]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_breakeven_finite_or_none_many(self):
        for pos in [make_pos(),
                    make_pos(redeploy_apr_pct=2.0, vault_apr_pct=8.0),
                    make_pos(redeploy_apr_pct=0.0, vault_apr_pct=0.0)]:
            r = A().analyze(pos)
            bw = r["breakeven_wait_days"]
            self.assertTrue(bw is None or math.isfinite(bw))

    def test_zero_position_usd_no_crash(self):
        r = A().analyze(make_pos(position_usd=0.0))
        self.assertIn("classification", r)
        self.assertAlmostEqual(r["instant_exit_cost_usd"], 0.0)

    def test_huge_values_no_crash(self):
        r = A().analyze(make_pos(nav_per_share_usd=1e9,
                                 instant_exit_price_usd=1.0,
                                 queue_wait_days=1e6,
                                 redeploy_apr_pct=1e6, vault_apr_pct=0.0,
                                 position_usd=1e12))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_apr_no_crash(self):
        r = A().analyze(make_pos(redeploy_apr_pct=-10.0, vault_apr_pct=-5.0))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_extreme_discount_score_bounded(self):
        r = A().analyze(make_pos(nav_per_share_usd=1.0,
                                 instant_exit_price_usd=0.001,
                                 queue_wait_days=10000.0,
                                 redeploy_apr_pct=99999.0, vault_apr_pct=0.0))
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_none_fields_default(self):
        r = A().analyze({"vault": "N", "nav_per_share_usd": None,
                         "instant_exit_price_usd": None,
                         "instant_exit_discount_pct": 3.0,
                         "queue_wait_days": None})
        self.assertIn("classification", r)
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

    def test_demo_includes_steep_discount(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("STEEP_DISCOUNT", classes)

    def test_demo_each_position_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)

    def test_demo_breakeven_json_null_ok(self):
        res = A().analyze_portfolio(_demo_positions())
        raw = json.dumps(res)
        # breakeven_wait_days None serializes to null cleanly
        json.loads(raw)


if __name__ == "__main__":
    unittest.main()
