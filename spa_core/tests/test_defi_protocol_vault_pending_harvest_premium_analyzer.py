"""
Tests for MP-1158: DeFiProtocolVaultPendingHarvestPremiumAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_pending_harvest_premium_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_pending_harvest_premium_analyzer import (
    DeFiProtocolVaultPendingHarvestPremiumAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    DEFAULT_HARVEST_INTERVAL_HOURS,
    CLEAN_PREMIUM_PCT,
    MINOR_PREMIUM_PCT,
    MODERATE_PREMIUM_PCT,
    JIT_PREMIUM_PCT,
    JIT_PROGRESS_PCT,
    HIGH_PERF_FEE_PCT,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    total_tvl_usd=100_000_000.0,
    pending_rewards_usd=1_000_000.0,
    hours_since_last_harvest=12.0,
    harvest_interval_hours=24.0,
    performance_fee_pct=10.0,
):
    p = {
        "vault": vault,
        "total_tvl_usd": total_tvl_usd,
        "hours_since_last_harvest": hours_since_last_harvest,
        "harvest_interval_hours": harvest_interval_hours,
        "performance_fee_pct": performance_fee_pct,
    }
    if pending_rewards_usd is not None:
        p["pending_rewards_usd"] = pending_rewards_usd
    return p


def A():
    return DeFiProtocolVaultPendingHarvestPremiumAnalyzer()


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
        self.assertGreater(DEFAULT_HARVEST_INTERVAL_HOURS, 0)
        self.assertLess(CLEAN_PREMIUM_PCT, MINOR_PREMIUM_PCT)
        self.assertLess(MINOR_PREMIUM_PCT, MODERATE_PREMIUM_PCT)
        self.assertGreater(JIT_PREMIUM_PCT, 0)
        self.assertGreater(JIT_PROGRESS_PCT, 0)
        self.assertLessEqual(JIT_PROGRESS_PCT, 100)
        self.assertGreater(HIGH_PERF_FEE_PCT, 0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "total_tvl_usd", "pending_rewards_usd",
            "pending_premium_pct", "net_premium_pct", "timing_edge_pct",
            "performance_fee_pct", "harvest_interval_hours",
            "hours_since_last_harvest", "harvest_progress_pct",
            "hours_to_next_harvest", "timing_score", "classification",
            "recommendation", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["timing_score"], 0.0)
        self.assertLessEqual(self.r["timing_score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "USDC-Vault")

    def test_token_field_alias(self):
        r = A().analyze({"token": "AltKey", "total_tvl_usd": 1e6})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "total_tvl_usd": 1e6})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"total_tvl_usd": 1e6})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        for v in self.r.values():
            if isinstance(v, float):
                self.assertFalse(math.isinf(v))
                self.assertFalse(math.isnan(v))

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "ENTER_BEFORE_HARVEST", "NEUTRAL", "NO_TIMING_EDGE", "AVOID",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_timing_edge_equals_net_premium(self):
        self.assertAlmostEqual(
            self.r["timing_edge_pct"], self.r["net_premium_pct"], places=4)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_pending_premium_basic(self):
        # 1M pending / 100M tvl = 1%
        r = A().analyze(make_pos(total_tvl_usd=100_000_000.0,
                                 pending_rewards_usd=1_000_000.0,
                                 performance_fee_pct=0.0))
        self.assertAlmostEqual(r["pending_premium_pct"], 1.0)

    def test_net_premium_after_fee(self):
        # 1% gross, 10% fee → 0.9% net
        r = A().analyze(make_pos(total_tvl_usd=100_000_000.0,
                                 pending_rewards_usd=1_000_000.0,
                                 performance_fee_pct=10.0))
        self.assertAlmostEqual(r["net_premium_pct"], 0.9)

    def test_net_premium_zero_fee_equals_gross(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=2.0,
                                 performance_fee_pct=0.0))
        self.assertAlmostEqual(r["net_premium_pct"], r["pending_premium_pct"])

    def test_net_premium_full_fee_zero(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=2.0,
                                 performance_fee_pct=100.0))
        self.assertAlmostEqual(r["net_premium_pct"], 0.0)

    def test_pending_premium_zero_when_no_pending(self):
        r = A().analyze(make_pos(pending_rewards_usd=0.0))
        self.assertAlmostEqual(r["pending_premium_pct"], 0.0)
        self.assertAlmostEqual(r["net_premium_pct"], 0.0)

    def test_pending_negative_treated_zero(self):
        r = A().analyze(make_pos(pending_rewards_usd=-100.0))
        self.assertAlmostEqual(r["pending_premium_pct"], 0.0)

    def test_harvest_progress_basic(self):
        # 12h since / 24h interval → 50%
        r = A().analyze(make_pos(hours_since_last_harvest=12.0,
                                 harvest_interval_hours=24.0))
        self.assertAlmostEqual(r["harvest_progress_pct"], 50.0)

    def test_harvest_progress_clamped_100(self):
        r = A().analyze(make_pos(hours_since_last_harvest=48.0,
                                 harvest_interval_hours=24.0))
        self.assertAlmostEqual(r["harvest_progress_pct"], 100.0)

    def test_harvest_progress_zero_at_start(self):
        r = A().analyze(make_pos(hours_since_last_harvest=0.0,
                                 harvest_interval_hours=24.0))
        self.assertAlmostEqual(r["harvest_progress_pct"], 0.0)

    def test_hours_to_next_basic(self):
        r = A().analyze(make_pos(hours_since_last_harvest=10.0,
                                 harvest_interval_hours=24.0))
        self.assertAlmostEqual(r["hours_to_next_harvest"], 14.0)

    def test_hours_to_next_floor_zero(self):
        r = A().analyze(make_pos(hours_since_last_harvest=30.0,
                                 harvest_interval_hours=24.0))
        self.assertAlmostEqual(r["hours_to_next_harvest"], 0.0)

    def test_interval_default_when_zero(self):
        r = A().analyze(make_pos(harvest_interval_hours=0.0,
                                 hours_since_last_harvest=12.0))
        self.assertAlmostEqual(r["harvest_interval_hours"],
                               DEFAULT_HARVEST_INTERVAL_HOURS)

    def test_interval_default_when_missing(self):
        r = A().analyze({"vault": "V", "total_tvl_usd": 100.0,
                         "pending_rewards_usd": 1.0,
                         "hours_since_last_harvest": 1.0})
        self.assertAlmostEqual(r["harvest_interval_hours"],
                               DEFAULT_HARVEST_INTERVAL_HOURS)

    def test_perf_fee_clamped_high(self):
        r = A().analyze(make_pos(performance_fee_pct=200.0))
        self.assertAlmostEqual(r["performance_fee_pct"], 100.0)

    def test_perf_fee_clamped_low(self):
        r = A().analyze(make_pos(performance_fee_pct=-20.0))
        self.assertAlmostEqual(r["performance_fee_pct"], 0.0)

    def test_hours_since_negative_treated_zero(self):
        r = A().analyze(make_pos(hours_since_last_harvest=-5.0))
        self.assertAlmostEqual(r["hours_since_last_harvest"], 0.0)

    def test_net_premium_nonnegative(self):
        r = A().analyze(make_pos(pending_rewards_usd=2_000_000.0,
                                 performance_fee_pct=50.0))
        self.assertGreaterEqual(r["net_premium_pct"], 0.0)

    def test_tvl_preserved(self):
        r = A().analyze(make_pos(total_tvl_usd=12_345.0))
        self.assertAlmostEqual(r["total_tvl_usd"], 12_345.0)


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_clean(self):
        # net premium ~0.05% < 0.10
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=0.05,
                                 performance_fee_pct=0.0))
        self.assertEqual(r["classification"], "CLEAN")

    def test_minor_premium(self):
        # net premium 0.3% in [0.10, 0.50)
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=0.3,
                                 performance_fee_pct=0.0))
        self.assertEqual(r["classification"], "MINOR_PREMIUM")

    def test_moderate_premium(self):
        # net premium 1.0% in [0.50, 1.50)
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=1.0,
                                 performance_fee_pct=0.0))
        self.assertEqual(r["classification"], "MODERATE_PREMIUM")

    def test_large_premium(self):
        # net premium 2.0% >= 1.50
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=2.0,
                                 performance_fee_pct=0.0))
        self.assertEqual(r["classification"], "LARGE_PREMIUM")

    def test_boundary_clean_at_010(self):
        # exactly 0.10% → not clean (>= boundary)
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=0.10,
                                 performance_fee_pct=0.0))
        self.assertEqual(r["classification"], "MINOR_PREMIUM")

    def test_boundary_minor_at_050(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=0.50,
                                 performance_fee_pct=0.0))
        self.assertEqual(r["classification"], "MODERATE_PREMIUM")

    def test_boundary_moderate_at_150(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=1.50,
                                 performance_fee_pct=0.0))
        self.assertEqual(r["classification"], "LARGE_PREMIUM")

    def test_classification_known_value(self):
        for pos in [make_pos(), make_pos(pending_rewards_usd=5_000_000.0),
                    make_pos(total_tvl_usd=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "CLEAN", "MINOR_PREMIUM", "MODERATE_PREMIUM",
                "LARGE_PREMIUM", "INSUFFICIENT_DATA",
            })

    def test_fee_pushes_down_classification(self):
        # gross 1.0% but 80% fee → net 0.2% → MINOR (not MODERATE)
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=1.0,
                                 performance_fee_pct=80.0))
        self.assertEqual(r["classification"], "MINOR_PREMIUM")

    def test_zero_pending_is_clean(self):
        r = A().analyze(make_pos(pending_rewards_usd=0.0))
        self.assertEqual(r["classification"], "CLEAN")


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_enter_when_large(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=2.0,
                                 performance_fee_pct=0.0))
        self.assertEqual(r["recommendation"], "ENTER_BEFORE_HARVEST")

    def test_enter_when_moderate(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=1.0,
                                 performance_fee_pct=0.0))
        self.assertEqual(r["recommendation"], "ENTER_BEFORE_HARVEST")

    def test_neutral_when_minor(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=0.3,
                                 performance_fee_pct=0.0))
        self.assertEqual(r["recommendation"], "NEUTRAL")

    def test_no_edge_when_clean(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=0.01,
                                 performance_fee_pct=0.0))
        self.assertEqual(r["recommendation"], "NO_TIMING_EDGE")

    def test_avoid_when_insufficient(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertEqual(r["recommendation"], "AVOID")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_just_in_time_flag(self):
        # net 2% >= 1.5 and progress 92% >= 75
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=2.0,
                                 performance_fee_pct=0.0,
                                 hours_since_last_harvest=22.0,
                                 harvest_interval_hours=24.0))
        self.assertIn("JUST_IN_TIME_OPPORTUNITY", r["flags"])

    def test_just_in_time_flag_absent_low_premium(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=0.5,
                                 performance_fee_pct=0.0,
                                 hours_since_last_harvest=22.0,
                                 harvest_interval_hours=24.0))
        self.assertNotIn("JUST_IN_TIME_OPPORTUNITY", r["flags"])

    def test_just_in_time_flag_absent_early_cycle(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=2.0,
                                 performance_fee_pct=0.0,
                                 hours_since_last_harvest=2.0,
                                 harvest_interval_hours=24.0))
        self.assertNotIn("JUST_IN_TIME_OPPORTUNITY", r["flags"])

    def test_stale_harvest_flag(self):
        # hours_since 60 > 2*24
        r = A().analyze(make_pos(hours_since_last_harvest=60.0,
                                 harvest_interval_hours=24.0))
        self.assertIn("STALE_HARVEST", r["flags"])

    def test_stale_harvest_flag_absent(self):
        r = A().analyze(make_pos(hours_since_last_harvest=30.0,
                                 harvest_interval_hours=24.0))
        self.assertNotIn("STALE_HARVEST", r["flags"])

    def test_high_perf_fee_flag(self):
        r = A().analyze(make_pos(performance_fee_pct=25.0))
        self.assertIn("HIGH_PERF_FEE_DRAG", r["flags"])

    def test_high_perf_fee_flag_at_20(self):
        r = A().analyze(make_pos(performance_fee_pct=20.0))
        self.assertIn("HIGH_PERF_FEE_DRAG", r["flags"])

    def test_high_perf_fee_flag_absent(self):
        r = A().analyze(make_pos(performance_fee_pct=10.0))
        self.assertNotIn("HIGH_PERF_FEE_DRAG", r["flags"])

    def test_clean_entry_flag(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=0.01,
                                 performance_fee_pct=0.0))
        self.assertIn("CLEAN_ENTRY", r["flags"])

    def test_clean_entry_flag_absent(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=2.0,
                                 performance_fee_pct=0.0))
        self.assertNotIn("CLEAN_ENTRY", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_flags_is_list_always(self):
        for pos in [make_pos(), make_pos(total_tvl_usd=0.0)]:
            self.assertIsInstance(A().analyze(pos)["flags"], list)


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_zero_tvl(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_negative_tvl(self):
        r = A().analyze(make_pos(total_tvl_usd=-100.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertEqual(r["timing_score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_insufficient_zero_metrics(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertEqual(r["pending_premium_pct"], 0.0)
        self.assertEqual(r["net_premium_pct"], 0.0)
        self.assertEqual(r["harvest_progress_pct"], 0.0)

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_zero_pending_is_sufficient(self):
        # tvl present, zero pending → analyzable (clean)
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_larger_premium_scores_higher(self):
        small = A().analyze(make_pos(total_tvl_usd=100.0,
                                     pending_rewards_usd=0.2,
                                     performance_fee_pct=0.0,
                                     hours_since_last_harvest=12.0))
        large = A().analyze(make_pos(total_tvl_usd=100.0,
                                     pending_rewards_usd=2.0,
                                     performance_fee_pct=0.0,
                                     hours_since_last_harvest=12.0))
        self.assertGreater(large["timing_score"], small["timing_score"])

    def test_later_cycle_scores_higher(self):
        early = A().analyze(make_pos(total_tvl_usd=100.0,
                                     pending_rewards_usd=1.0,
                                     performance_fee_pct=0.0,
                                     hours_since_last_harvest=2.0,
                                     harvest_interval_hours=24.0))
        late = A().analyze(make_pos(total_tvl_usd=100.0,
                                    pending_rewards_usd=1.0,
                                    performance_fee_pct=0.0,
                                    hours_since_last_harvest=22.0,
                                    harvest_interval_hours=24.0))
        self.assertGreater(late["timing_score"], early["timing_score"])

    def test_clean_scores_low(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=0.01,
                                 performance_fee_pct=0.0,
                                 hours_since_last_harvest=1.0))
        self.assertLess(r["timing_score"], 40.0)

    def test_jit_scores_high(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=2.0,
                                 performance_fee_pct=0.0,
                                 hours_since_last_harvest=23.0,
                                 harvest_interval_hours=24.0))
        self.assertGreater(r["timing_score"], 85.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0,
                                 pending_rewards_usd=100.0,
                                 performance_fee_pct=0.0,
                                 hours_since_last_harvest=100.0))
        self.assertLessEqual(r["timing_score"], 100.0)
        self.assertGreaterEqual(r["timing_score"], 0.0)

    def test_score_floor_zero_pending(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0, pending_rewards_usd=0.0,
                                 hours_since_last_harvest=0.0))
        self.assertGreaterEqual(r["timing_score"], 0.0)

    def test_higher_fee_lowers_score(self):
        low_fee = A().analyze(make_pos(total_tvl_usd=100.0,
                                       pending_rewards_usd=2.0,
                                       performance_fee_pct=0.0,
                                       hours_since_last_harvest=12.0))
        high_fee = A().analyze(make_pos(total_tvl_usd=100.0,
                                        pending_rewards_usd=2.0,
                                        performance_fee_pct=50.0,
                                        hours_since_last_harvest=12.0))
        self.assertGreater(low_fee["timing_score"], high_fee["timing_score"])


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Best", total_tvl_usd=100.0, pending_rewards_usd=2.0,
                     performance_fee_pct=0.0, hours_since_last_harvest=23.0),
            make_pos(vault="Clean", total_tvl_usd=100.0, pending_rewards_usd=0.01,
                     performance_fee_pct=0.0, hours_since_last_harvest=1.0),
            make_pos(vault="Mid", total_tvl_usd=100.0, pending_rewards_usd=1.0,
                     performance_fee_pct=0.0, hours_since_last_harvest=12.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_best_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["timing_score"]
                  for p in self.res["positions"]}
        best = agg["best_timing_vault"]
        self.assertEqual(scores[best], max(scores.values()))

    def test_best_is_best_vault(self):
        self.assertEqual(self.res["aggregate"]["best_timing_vault"], "Best")

    def test_large_premium_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["large_premium_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["best_timing_vault"])

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(total_tvl_usd=0.0), make_pos(total_tvl_usd=-1.0),
        ])
        self.assertIsNone(res["aggregate"]["best_timing_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)

    def test_empty_position_count_zero(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["aggregate"]["position_count"], 0)

    def test_large_premium_count_zero_when_none(self):
        res = A().analyze_portfolio([
            make_pos(total_tvl_usd=100.0, pending_rewards_usd=0.01,
                     performance_fee_pct=0.0),
        ])
        self.assertEqual(res["aggregate"]["large_premium_count"], 0)


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
                make_pos(vault="big", pending_rewards_usd=90_000_000.0),
                make_pos(vault="ins", total_tvl_usd=0.0),
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
            for k in ("token", "classification", "timing_score",
                      "recommendation", "flags"):
                self.assertIn(k, snap)

    def test_log_does_not_touch_production(self):
        # default analyze (no write) must not create production log
        before = os.path.exists(LOG_PATH)
        A().analyze(make_pos())
        after = os.path.exists(LOG_PATH)
        self.assertEqual(before, after)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "total_tvl_usd": "100",
            "pending_rewards_usd": "1",
            "hours_since_last_harvest": "12",
            "harvest_interval_hours": "24",
            "performance_fee_pct": "10",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({"vault": "S", "total_tvl_usd": 100.0})
        self.assertIn("classification", r)

    def test_only_tvl_given(self):
        r = A().analyze({"vault": "S", "total_tvl_usd": 100.0})
        # no pending → clean
        self.assertEqual(r["classification"], "CLEAN")

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(), make_pos(total_tvl_usd=0.0),
            make_pos(pending_rewards_usd=80_000_000.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(), make_pos(total_tvl_usd=0.0),
                    make_pos(pending_rewards_usd=100_000_000.0),
                    make_pos(pending_rewards_usd=0.0, performance_fee_pct=0.0),
                    make_pos(total_tvl_usd=1.0, pending_rewards_usd=1.0),
                    make_pos(harvest_interval_hours=0.0)]:
            r = A().analyze(pos)
            for v in r.values():
                if isinstance(v, float):
                    self.assertFalse(math.isinf(v))
                    self.assertFalse(math.isnan(v))

    def test_zero_interval_no_crash(self):
        r = A().analyze(make_pos(harvest_interval_hours=0.0))
        self.assertIn("classification", r)

    def test_pending_exceeds_tvl_no_crash(self):
        r = A().analyze(make_pos(total_tvl_usd=100.0,
                                 pending_rewards_usd=500.0,
                                 performance_fee_pct=0.0))
        self.assertIn("classification", r)
        self.assertGreaterEqual(r["pending_premium_pct"], 0.0)

    def test_negative_pending_clamped(self):
        r = A().analyze(make_pos(pending_rewards_usd=-1000.0))
        self.assertGreaterEqual(r["pending_premium_pct"], 0.0)


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

    def test_demo_includes_clean(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("CLEAN", classes)

    def test_demo_includes_large_premium(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("LARGE_PREMIUM", classes)


if __name__ == "__main__":
    unittest.main()
