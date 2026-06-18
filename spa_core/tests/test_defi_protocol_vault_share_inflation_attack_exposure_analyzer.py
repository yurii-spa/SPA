"""
Tests for MP-1156: DeFiProtocolVaultShareInflationAttackExposureAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_share_inflation_attack_exposure_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_share_inflation_attack_exposure_analyzer import (
    DeFiProtocolVaultShareInflationAttackExposureAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    PRICE_SENTINEL_MAX,
    LARGE_SHARE_SUPPLY,
    TINY_SHARE_SUPPLY,
    MIN_DECIMALS_OFFSET,
    MIN_DEAD_SHARES,
    PROTECTED_ROUNDING_SCALE,
    HIGH_ROUNDING_LOSS_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    total_shares=5_000_000.0,
    total_assets_usd=5_000_000.0,
    has_virtual_shares=False,
    dead_shares_burned=0.0,
    decimals_offset=0.0,
    intended_deposit_usd=100_000.0,
):
    return {
        "vault": vault,
        "total_shares": total_shares,
        "total_assets_usd": total_assets_usd,
        "has_virtual_shares": has_virtual_shares,
        "dead_shares_burned": dead_shares_burned,
        "decimals_offset": decimals_offset,
        "intended_deposit_usd": intended_deposit_usd,
    }


def A():
    return DeFiProtocolVaultShareInflationAttackExposureAnalyzer()


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

    def test_clamp_within(self):
        self.assertEqual(_clamp(5, 0, 10), 5)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1, 0, 10), 0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(11, 0, 10), 10)

    def test_clamp_exact_bounds(self):
        self.assertEqual(_clamp(0, 0, 10), 0)
        self.assertEqual(_clamp(10, 0, 10), 10)

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
        self.assertGreater(PRICE_SENTINEL_MAX, 0)
        self.assertGreater(LARGE_SHARE_SUPPLY, TINY_SHARE_SUPPLY)
        self.assertGreater(MIN_DECIMALS_OFFSET, 0)
        self.assertGreater(MIN_DEAD_SHARES, 0)
        self.assertGreater(PROTECTED_ROUNDING_SCALE, 0)
        self.assertLess(PROTECTED_ROUNDING_SCALE, 1)
        self.assertGreater(HIGH_ROUNDING_LOSS_PCT, 0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "total_shares", "total_assets_usd", "share_price_usd",
            "has_virtual_shares", "dead_shares_burned", "decimals_offset",
            "intended_deposit_usd", "effective_protection",
            "donation_to_inflate_usd", "shares_i_would_get",
            "rounding_loss_shares_pct", "vulnerability_score",
            "classification", "recommendation", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["vulnerability_score"], 0.0)
        self.assertLessEqual(self.r["vulnerability_score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "USDC-Vault")

    def test_token_field_alias(self):
        r = A().analyze({"token": "AltKey", "total_assets_usd": 1e6,
                         "total_shares": 1e6})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "total_assets_usd": 1e6,
                         "total_shares": 1e6})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"total_assets_usd": 1e6, "total_shares": 1e6})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        for v in self.r.values():
            if isinstance(v, float):
                self.assertFalse(math.isinf(v))
                self.assertFalse(math.isnan(v))

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"],
                      {"DEPLOY", "DEPLOY_CAUTIOUSLY", "AVOID"})

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_has_virtual_shares_is_bool(self):
        self.assertIsInstance(self.r["has_virtual_shares"], bool)

    def test_effective_protection_is_bool(self):
        self.assertIsInstance(self.r["effective_protection"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_share_price_basic(self):
        r = A().analyze(make_pos(total_shares=1000.0, total_assets_usd=2000.0))
        self.assertAlmostEqual(r["share_price_usd"], 2.0)

    def test_share_price_zero_shares_sentinel(self):
        r = A().analyze(make_pos(total_shares=0.0, total_assets_usd=1000.0))
        self.assertIsNone(r["share_price_usd"])

    def test_share_price_negative_shares_sentinel(self):
        r = A().analyze(make_pos(total_shares=-5.0, total_assets_usd=1000.0))
        self.assertIsNone(r["share_price_usd"])

    def test_donation_equals_assets(self):
        r = A().analyze(make_pos(total_assets_usd=750_000.0))
        self.assertAlmostEqual(r["donation_to_inflate_usd"], 750_000.0)

    def test_shares_i_would_get_basic(self):
        # price = 2.0, deposit 100 → 50 shares
        r = A().analyze(make_pos(total_shares=1000.0, total_assets_usd=2000.0,
                                 intended_deposit_usd=100.0))
        self.assertAlmostEqual(r["shares_i_would_get"], 50.0)

    def test_shares_i_would_get_zero_when_no_deposit(self):
        r = A().analyze(make_pos(intended_deposit_usd=0.0))
        self.assertAlmostEqual(r["shares_i_would_get"], 0.0)

    def test_rounding_loss_zero_when_no_deposit(self):
        r = A().analyze(make_pos(intended_deposit_usd=0.0))
        self.assertAlmostEqual(r["rounding_loss_shares_pct"], 0.0)

    def test_rounding_loss_zero_when_many_shares(self):
        # deposit mints >> 1 share → no rounding loss
        r = A().analyze(make_pos(total_shares=1e6, total_assets_usd=1e6,
                                 intended_deposit_usd=100_000.0))
        self.assertAlmostEqual(r["rounding_loss_shares_pct"], 0.0)

    def test_rounding_loss_high_when_tiny_deposit_vs_huge_price(self):
        # huge share price (tiny supply), small deposit → <1 share → high loss
        r = A().analyze(make_pos(total_shares=1.0, total_assets_usd=1_000_000.0,
                                 intended_deposit_usd=1.0))
        self.assertGreater(r["rounding_loss_shares_pct"], 50.0)

    def test_rounding_loss_scaled_when_protected(self):
        unprot = A().analyze(make_pos(total_shares=1.0,
                                      total_assets_usd=1_000_000.0,
                                      intended_deposit_usd=100.0,
                                      has_virtual_shares=False))
        prot = A().analyze(make_pos(total_shares=1.0,
                                    total_assets_usd=1_000_000.0,
                                    intended_deposit_usd=100.0,
                                    has_virtual_shares=True))
        self.assertGreater(unprot["rounding_loss_shares_pct"],
                           prot["rounding_loss_shares_pct"])

    def test_negative_deposit_treated_as_zero(self):
        r = A().analyze(make_pos(intended_deposit_usd=-1000.0))
        self.assertAlmostEqual(r["intended_deposit_usd"], 0.0)
        self.assertAlmostEqual(r["rounding_loss_shares_pct"], 0.0)

    def test_negative_dead_shares_treated_as_zero(self):
        r = A().analyze(make_pos(dead_shares_burned=-500.0))
        self.assertAlmostEqual(r["dead_shares_burned"], 0.0)

    def test_negative_decimals_offset_treated_as_zero(self):
        r = A().analyze(make_pos(decimals_offset=-3.0))
        self.assertAlmostEqual(r["decimals_offset"], 0.0)

    def test_total_shares_preserved(self):
        r = A().analyze(make_pos(total_shares=12345.0))
        self.assertAlmostEqual(r["total_shares"], 12345.0)

    def test_total_assets_preserved(self):
        r = A().analyze(make_pos(total_assets_usd=999.0))
        self.assertAlmostEqual(r["total_assets_usd"], 999.0)


# ── effective_protection logic ────────────────────────────────────────────────

class TestEffectiveProtection(unittest.TestCase):
    def test_virtual_shares_protects(self):
        r = A().analyze(make_pos(has_virtual_shares=True))
        self.assertTrue(r["effective_protection"])

    def test_decimals_offset_protects(self):
        r = A().analyze(make_pos(decimals_offset=3))
        self.assertTrue(r["effective_protection"])

    def test_decimals_offset_below_threshold_no_protect(self):
        r = A().analyze(make_pos(decimals_offset=2,
                                 has_virtual_shares=False,
                                 dead_shares_burned=0.0))
        self.assertFalse(r["effective_protection"])

    def test_dead_shares_protects(self):
        r = A().analyze(make_pos(dead_shares_burned=1000.0))
        self.assertTrue(r["effective_protection"])

    def test_dead_shares_below_threshold_no_protect(self):
        r = A().analyze(make_pos(dead_shares_burned=999.0,
                                 has_virtual_shares=False,
                                 decimals_offset=0))
        self.assertFalse(r["effective_protection"])

    def test_no_protection(self):
        r = A().analyze(make_pos(has_virtual_shares=False,
                                 decimals_offset=0,
                                 dead_shares_burned=0.0))
        self.assertFalse(r["effective_protection"])

    def test_decimals_offset_exactly_threshold(self):
        r = A().analyze(make_pos(decimals_offset=MIN_DECIMALS_OFFSET))
        self.assertTrue(r["effective_protection"])

    def test_dead_shares_exactly_threshold(self):
        r = A().analyze(make_pos(dead_shares_burned=MIN_DEAD_SHARES))
        self.assertTrue(r["effective_protection"])


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_well_protected(self):
        r = A().analyze(make_pos(total_shares=5e6, has_virtual_shares=True))
        self.assertEqual(r["classification"], "WELL_PROTECTED")

    def test_high_risk(self):
        # no protection AND tiny supply
        r = A().analyze(make_pos(total_shares=100.0, has_virtual_shares=False,
                                 decimals_offset=0, dead_shares_burned=0.0))
        self.assertEqual(r["classification"], "HIGH_RISK")

    def test_low_risk_large_supply_no_protection(self):
        r = A().analyze(make_pos(total_shares=2e6, has_virtual_shares=False,
                                 decimals_offset=0, dead_shares_burned=0.0))
        self.assertEqual(r["classification"], "LOW_RISK")

    def test_low_risk_protected_small_supply(self):
        r = A().analyze(make_pos(total_shares=5000.0, has_virtual_shares=True))
        self.assertEqual(r["classification"], "LOW_RISK")

    def test_moderate_risk(self):
        # no protection, supply between tiny and large
        r = A().analyze(make_pos(total_shares=50_000.0, has_virtual_shares=False,
                                 decimals_offset=0, dead_shares_burned=0.0))
        self.assertEqual(r["classification"], "MODERATE_RISK")

    def test_classification_known_value(self):
        for pos in [make_pos(), make_pos(total_shares=100.0,
                                         has_virtual_shares=False),
                    make_pos(total_assets_usd=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "WELL_PROTECTED", "LOW_RISK", "MODERATE_RISK", "HIGH_RISK",
                "INSUFFICIENT_DATA",
            })

    def test_boundary_tiny_supply_high_risk(self):
        r = A().analyze(make_pos(total_shares=TINY_SHARE_SUPPLY,
                                 has_virtual_shares=False,
                                 decimals_offset=0, dead_shares_burned=0.0))
        self.assertEqual(r["classification"], "HIGH_RISK")

    def test_boundary_large_supply_low_risk(self):
        r = A().analyze(make_pos(total_shares=LARGE_SHARE_SUPPLY,
                                 has_virtual_shares=False,
                                 decimals_offset=0, dead_shares_burned=0.0))
        self.assertEqual(r["classification"], "LOW_RISK")

    def test_well_protected_needs_large_supply(self):
        # protected but small supply → LOW_RISK, not WELL_PROTECTED
        r = A().analyze(make_pos(total_shares=100.0, has_virtual_shares=True))
        self.assertEqual(r["classification"], "LOW_RISK")


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_deploy_when_well_protected(self):
        r = A().analyze(make_pos(total_shares=5e6, has_virtual_shares=True))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_deploy_when_low_risk(self):
        r = A().analyze(make_pos(total_shares=2e6, has_virtual_shares=False,
                                 decimals_offset=0, dead_shares_burned=0.0))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_deploy_cautiously_when_moderate(self):
        r = A().analyze(make_pos(total_shares=50_000.0, has_virtual_shares=False,
                                 decimals_offset=0, dead_shares_burned=0.0))
        self.assertEqual(r["recommendation"], "DEPLOY_CAUTIOUSLY")

    def test_avoid_when_high_risk(self):
        r = A().analyze(make_pos(total_shares=100.0, has_virtual_shares=False,
                                 decimals_offset=0, dead_shares_burned=0.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_avoid_when_insufficient(self):
        r = A().analyze(make_pos(total_assets_usd=0.0))
        self.assertEqual(r["recommendation"], "AVOID")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_well_protected_flag(self):
        r = A().analyze(make_pos(total_shares=5e6, has_virtual_shares=True))
        self.assertIn("WELL_PROTECTED", r["flags"])

    def test_well_protected_flag_absent(self):
        r = A().analyze(make_pos(total_shares=100.0, has_virtual_shares=False,
                                 decimals_offset=0, dead_shares_burned=0.0))
        self.assertNotIn("WELL_PROTECTED", r["flags"])

    def test_has_virtual_shares_flag(self):
        r = A().analyze(make_pos(has_virtual_shares=True))
        self.assertIn("HAS_VIRTUAL_SHARES", r["flags"])

    def test_has_virtual_shares_flag_absent(self):
        r = A().analyze(make_pos(has_virtual_shares=False))
        self.assertNotIn("HAS_VIRTUAL_SHARES", r["flags"])

    def test_dead_shares_buffer_flag(self):
        r = A().analyze(make_pos(dead_shares_burned=2000.0))
        self.assertIn("DEAD_SHARES_BUFFER", r["flags"])

    def test_dead_shares_buffer_flag_absent(self):
        r = A().analyze(make_pos(dead_shares_burned=100.0))
        self.assertNotIn("DEAD_SHARES_BUFFER", r["flags"])

    def test_decimals_offset_protection_flag(self):
        r = A().analyze(make_pos(decimals_offset=6))
        self.assertIn("DECIMALS_OFFSET_PROTECTION", r["flags"])

    def test_decimals_offset_protection_flag_absent(self):
        r = A().analyze(make_pos(decimals_offset=1))
        self.assertNotIn("DECIMALS_OFFSET_PROTECTION", r["flags"])

    def test_tiny_share_supply_flag(self):
        r = A().analyze(make_pos(total_shares=500.0))
        self.assertIn("TINY_SHARE_SUPPLY", r["flags"])

    def test_tiny_share_supply_flag_absent(self):
        r = A().analyze(make_pos(total_shares=5e6))
        self.assertNotIn("TINY_SHARE_SUPPLY", r["flags"])

    def test_no_inflation_protection_flag(self):
        r = A().analyze(make_pos(has_virtual_shares=False, decimals_offset=0,
                                 dead_shares_burned=0.0))
        self.assertIn("NO_INFLATION_PROTECTION", r["flags"])

    def test_no_inflation_protection_flag_absent(self):
        r = A().analyze(make_pos(has_virtual_shares=True))
        self.assertNotIn("NO_INFLATION_PROTECTION", r["flags"])

    def test_high_rounding_loss_risk_flag(self):
        r = A().analyze(make_pos(total_shares=1.0, total_assets_usd=1_000_000.0,
                                 intended_deposit_usd=1.0,
                                 has_virtual_shares=False))
        self.assertIn("HIGH_ROUNDING_LOSS_RISK", r["flags"])

    def test_high_rounding_loss_risk_flag_absent(self):
        r = A().analyze(make_pos(total_shares=1e6, total_assets_usd=1e6,
                                 intended_deposit_usd=100_000.0))
        self.assertNotIn("HIGH_ROUNDING_LOSS_RISK", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(total_assets_usd=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_zero_assets(self):
        r = A().analyze(make_pos(total_assets_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_negative_assets(self):
        r = A().analyze(make_pos(total_assets_usd=-100.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(total_assets_usd=0.0))
        self.assertEqual(r["vulnerability_score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_share_price_none(self):
        r = A().analyze(make_pos(total_assets_usd=0.0))
        self.assertIsNone(r["share_price_usd"])

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(total_assets_usd=0.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_insufficient_effective_protection_false(self):
        r = A().analyze(make_pos(total_assets_usd=0.0))
        self.assertFalse(r["effective_protection"])

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_zero_shares_still_analyzable(self):
        # zero shares but assets present → MAX vulnerability, not insufficient
        r = A().analyze(make_pos(total_shares=0.0, total_assets_usd=1000.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_larger_supply_scores_higher(self):
        small = A().analyze(make_pos(total_shares=1000.0,
                                     has_virtual_shares=False,
                                     decimals_offset=0, dead_shares_burned=0.0))
        large = A().analyze(make_pos(total_shares=1e6,
                                     has_virtual_shares=False,
                                     decimals_offset=0, dead_shares_burned=0.0))
        self.assertGreater(large["vulnerability_score"],
                           small["vulnerability_score"])

    def test_protected_scores_higher(self):
        unprot = A().analyze(make_pos(total_shares=10_000.0,
                                      has_virtual_shares=False,
                                      decimals_offset=0, dead_shares_burned=0.0))
        prot = A().analyze(make_pos(total_shares=10_000.0,
                                    has_virtual_shares=True))
        self.assertGreater(prot["vulnerability_score"],
                           unprot["vulnerability_score"])

    def test_lower_rounding_loss_scores_higher(self):
        high_loss = A().analyze(make_pos(total_shares=1.0,
                                         total_assets_usd=1_000_000.0,
                                         intended_deposit_usd=1.0,
                                         has_virtual_shares=False))
        low_loss = A().analyze(make_pos(total_shares=1.0,
                                        total_assets_usd=1_000_000.0,
                                        intended_deposit_usd=0.0,
                                        has_virtual_shares=False))
        self.assertGreaterEqual(low_loss["vulnerability_score"],
                                high_loss["vulnerability_score"])

    def test_high_risk_scores_low(self):
        r = A().analyze(make_pos(total_shares=1.0, total_assets_usd=1_000_000.0,
                                 intended_deposit_usd=1.0,
                                 has_virtual_shares=False,
                                 decimals_offset=0, dead_shares_burned=0.0))
        self.assertLess(r["vulnerability_score"], 40.0)

    def test_well_protected_scores_high(self):
        r = A().analyze(make_pos(total_shares=5e6, total_assets_usd=5e6,
                                 has_virtual_shares=True, decimals_offset=6,
                                 dead_shares_burned=1000.0,
                                 intended_deposit_usd=100_000.0))
        self.assertGreater(r["vulnerability_score"], 85.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(total_shares=1e12, total_assets_usd=1e12,
                                 has_virtual_shares=True, decimals_offset=18,
                                 dead_shares_burned=1e9))
        self.assertLessEqual(r["vulnerability_score"], 100.0)
        self.assertGreaterEqual(r["vulnerability_score"], 0.0)

    def test_score_floor_extreme_bad(self):
        r = A().analyze(make_pos(total_shares=0.0, total_assets_usd=1e6,
                                 intended_deposit_usd=1.0,
                                 has_virtual_shares=False))
        self.assertGreaterEqual(r["vulnerability_score"], 0.0)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Safe", total_shares=5e6, total_assets_usd=5e6,
                     has_virtual_shares=True, decimals_offset=6,
                     dead_shares_burned=1000.0),
            make_pos(vault="Risky", total_shares=1.0,
                     total_assets_usd=1_000_000.0, intended_deposit_usd=1.0,
                     has_virtual_shares=False, decimals_offset=0,
                     dead_shares_burned=0.0),
            make_pos(vault="Mid", total_shares=50_000.0,
                     total_assets_usd=200_000.0, has_virtual_shares=False,
                     decimals_offset=0, dead_shares_burned=0.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_vulnerable_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["vulnerability_score"]
                  for p in self.res["positions"]}
        most = agg["most_vulnerable_vault"]
        self.assertEqual(scores[most], min(scores.values()))

    def test_least_vulnerable_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["vulnerability_score"]
                  for p in self.res["positions"]}
        least = agg["least_vulnerable_vault"]
        self.assertEqual(scores[least], max(scores.values()))

    def test_most_vulnerable_is_risky(self):
        self.assertEqual(self.res["aggregate"]["most_vulnerable_vault"],
                         "Risky")

    def test_least_vulnerable_is_safe(self):
        self.assertEqual(self.res["aggregate"]["least_vulnerable_vault"],
                         "Safe")

    def test_high_risk_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["high_risk_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_vulnerability_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_vulnerable_vault"])
        self.assertIsNone(res["aggregate"]["least_vulnerable_vault"])

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(total_assets_usd=0.0), make_pos(total_assets_usd=-1.0),
        ])
        self.assertIsNone(res["aggregate"]["most_vulnerable_vault"])
        self.assertEqual(res["aggregate"]["avg_vulnerability_score"], 0.0)

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)


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
                make_pos(vault="risky", total_shares=1.0,
                         total_assets_usd=1e6, intended_deposit_usd=1.0),
                make_pos(vault="ins", total_assets_usd=0.0),
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
            for k in ("token", "classification", "vulnerability_score",
                      "recommendation", "flags"):
                self.assertIn(k, snap)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "total_shares": "1000000",
            "total_assets_usd": "1000000",
            "intended_deposit_usd": "100000",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({
            "vault": "S",
            "total_shares": 1e6,
            "total_assets_usd": 1e6,
        })
        self.assertIn("classification", r)

    def test_missing_total_shares(self):
        r = A().analyze({"vault": "S", "total_assets_usd": 1e6})
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio([make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(), make_pos(total_assets_usd=0.0),
            make_pos(total_shares=1.0, total_assets_usd=1e6),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(), make_pos(total_assets_usd=0.0),
                    make_pos(total_shares=0.0, total_assets_usd=1e6),
                    make_pos(total_shares=1.0, intended_deposit_usd=1.0),
                    make_pos(total_assets_usd=1.0, total_shares=1.0)]:
            r = A().analyze(pos)
            for v in r.values():
                if isinstance(v, float):
                    self.assertFalse(math.isinf(v))
                    self.assertFalse(math.isnan(v))

    def test_zero_shares_no_crash(self):
        r = A().analyze(make_pos(total_shares=0.0, total_assets_usd=1000.0,
                                 intended_deposit_usd=1000.0))
        self.assertIn("classification", r)

    def test_bool_coercion_truthy(self):
        r = A().analyze(make_pos(has_virtual_shares=1))
        self.assertTrue(r["has_virtual_shares"])


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_positions_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

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


if __name__ == "__main__":
    unittest.main()
