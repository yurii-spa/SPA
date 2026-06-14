"""
Tests for MP-1151: DeFiProtocolAutoCompoundKeeperReliabilityAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_autocompound_keeper_reliability_analyzer -v
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

from spa_core.analytics.defi_protocol_autocompound_keeper_reliability_analyzer import (
    DeFiProtocolAutoCompoundKeeperReliabilityAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    RATIO_SENTINEL_INF,
    PCT_SENTINEL_CAP,
    STALE_RATIO,
    SEVERELY_STALE_RATIO,
    STALLED_RATIO,
    HIGH_COMPLETION_PCT,
    MISSED_HARVEST_PCT,
    SIGNIFICANT_APY_DRAG_PCT,
    KEEPER_CENTRALIZATION,
    DEFAULT_CENTRALIZATION,
    DECENTRALIZED_KEEPERS,
    CENTRALIZED_KEEPERS,
    SCORE_HIGHLY_RELIABLE,
    SCORE_RELIABLE,
    SCORE_DEGRADED,
    SCORE_UNRELIABLE,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_vault(
    token="yvUSDC",
    expected_harvest_interval_hours=24.0,
    hours_since_last_harvest=6.0,
    observed_harvests_last_30d=30.0,
    expected_harvests_last_30d=30.0,
    keeper_type="PERMISSIONLESS",
    theoretical_apy_pct=9.0,
    realized_apy_pct=8.8,
    harvest_incentive_pct=0.0,
):
    return {
        "token": token,
        "expected_harvest_interval_hours": expected_harvest_interval_hours,
        "hours_since_last_harvest": hours_since_last_harvest,
        "observed_harvests_last_30d": observed_harvests_last_30d,
        "expected_harvests_last_30d": expected_harvests_last_30d,
        "keeper_type": keeper_type,
        "theoretical_apy_pct": theoretical_apy_pct,
        "realized_apy_pct": realized_apy_pct,
        "harvest_incentive_pct": harvest_incentive_pct,
    }


def A():
    return DeFiProtocolAutoCompoundKeeperReliabilityAnalyzer()


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

    def test_clamp_within(self):
        self.assertEqual(_clamp(5, 0, 10), 5)

    def test_clamp_low(self):
        self.assertEqual(_clamp(-1, 0, 10), 0)

    def test_clamp_high(self):
        self.assertEqual(_clamp(11, 0, 10), 10)

    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_values(self):
        self.assertAlmostEqual(_mean([2, 4, 6]), 4.0)

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

    def test_keeper_centralization_map(self):
        self.assertEqual(KEEPER_CENTRALIZATION["PERMISSIONLESS"], 5.0)
        self.assertEqual(KEEPER_CENTRALIZATION["INCENTIVIZED_BOT"], 20.0)
        self.assertEqual(KEEPER_CENTRALIZATION["MULTI_KEEPER"], 35.0)
        self.assertEqual(KEEPER_CENTRALIZATION["SINGLE_KEEPER"], 80.0)
        self.assertEqual(KEEPER_CENTRALIZATION["MANUAL"], 95.0)

    def test_constants_sane(self):
        self.assertLess(STALE_RATIO, SEVERELY_STALE_RATIO)
        self.assertLess(SEVERELY_STALE_RATIO, STALLED_RATIO)
        self.assertGreater(HIGH_COMPLETION_PCT, 0)
        self.assertGreater(MISSED_HARVEST_PCT, 0)
        self.assertGreater(SIGNIFICANT_APY_DRAG_PCT, 0)
        self.assertGreater(SCORE_HIGHLY_RELIABLE, SCORE_RELIABLE)
        self.assertGreater(SCORE_RELIABLE, SCORE_DEGRADED)
        self.assertGreater(SCORE_DEGRADED, SCORE_UNRELIABLE)
        self.assertIn("PERMISSIONLESS", DECENTRALIZED_KEEPERS)
        self.assertIn("MANUAL", CENTRALIZED_KEEPERS)
        self.assertEqual(DEFAULT_CENTRALIZATION, 80.0)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_vault())

    def test_has_all_keys(self):
        for k in [
            "token", "harvest_staleness_ratio", "is_stale",
            "harvest_completion_rate_pct", "missed_harvest_rate_pct",
            "apy_drag_pct", "apy_realization_pct", "keeper_centralization_pct",
            "reliability_score", "classification", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["reliability_score"], 0.0)
        self.assertLessEqual(self.r["reliability_score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "yvUSDC")

    def test_is_stale_is_bool(self):
        self.assertIsInstance(self.r["is_stale"], bool)

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        for v in self.r.values():
            if isinstance(v, float):
                self.assertFalse(math.isinf(v))
                self.assertFalse(math.isnan(v))


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_staleness_ratio(self):
        # 6 / 24 = 0.25
        r = A().analyze(make_vault(hours_since_last_harvest=6.0,
                                   expected_harvest_interval_hours=24.0))
        self.assertAlmostEqual(r["harvest_staleness_ratio"], 0.25)

    def test_staleness_ratio_none_when_no_interval(self):
        r = A().analyze(make_vault(expected_harvest_interval_hours=0.0,
                                   theoretical_apy_pct=9.0))
        self.assertIsNone(r["harvest_staleness_ratio"])

    def test_is_stale_true(self):
        # 48 / 24 = 2.0 > 1.5 → stale
        r = A().analyze(make_vault(hours_since_last_harvest=48.0,
                                   expected_harvest_interval_hours=24.0))
        self.assertTrue(r["is_stale"])

    def test_is_stale_false(self):
        r = A().analyze(make_vault(hours_since_last_harvest=6.0))
        self.assertFalse(r["is_stale"])

    def test_completion_rate(self):
        # 30 / 30 * 100 = 100
        r = A().analyze(make_vault(observed_harvests_last_30d=30.0,
                                   expected_harvests_last_30d=30.0))
        self.assertAlmostEqual(r["harvest_completion_rate_pct"], 100.0)

    def test_completion_rate_partial(self):
        r = A().analyze(make_vault(observed_harvests_last_30d=15.0,
                                   expected_harvests_last_30d=30.0))
        self.assertAlmostEqual(r["harvest_completion_rate_pct"], 50.0)

    def test_completion_rate_none_when_no_expected(self):
        r = A().analyze(make_vault(expected_harvests_last_30d=0.0))
        self.assertIsNone(r["harvest_completion_rate_pct"])

    def test_missed_harvest_rate(self):
        r = A().analyze(make_vault(observed_harvests_last_30d=24.0,
                                   expected_harvests_last_30d=30.0))
        self.assertAlmostEqual(r["missed_harvest_rate_pct"], 20.0)

    def test_missed_harvest_zero_when_complete(self):
        r = A().analyze(make_vault(observed_harvests_last_30d=30.0,
                                   expected_harvests_last_30d=30.0))
        self.assertEqual(r["missed_harvest_rate_pct"], 0.0)

    def test_apy_drag(self):
        # 9 - 8.8 = 0.2
        r = A().analyze(make_vault(theoretical_apy_pct=9.0, realized_apy_pct=8.8))
        self.assertAlmostEqual(r["apy_drag_pct"], 0.2, places=4)

    def test_apy_realization(self):
        # 8.8 / 9.0 * 100 = ~97.78
        r = A().analyze(make_vault(theoretical_apy_pct=9.0, realized_apy_pct=8.8))
        self.assertAlmostEqual(r["apy_realization_pct"], 8.8 / 9.0 * 100.0, places=2)

    def test_apy_realization_none_when_no_theoretical(self):
        r = A().analyze(make_vault(theoretical_apy_pct=0.0,
                                   expected_harvest_interval_hours=24.0))
        self.assertIsNone(r["apy_realization_pct"])

    def test_keeper_centralization_permissionless(self):
        r = A().analyze(make_vault(keeper_type="PERMISSIONLESS"))
        self.assertEqual(r["keeper_centralization_pct"], 5.0)

    def test_keeper_centralization_single(self):
        r = A().analyze(make_vault(keeper_type="SINGLE_KEEPER"))
        self.assertEqual(r["keeper_centralization_pct"], 80.0)

    def test_keeper_centralization_manual(self):
        r = A().analyze(make_vault(keeper_type="MANUAL"))
        self.assertEqual(r["keeper_centralization_pct"], 95.0)

    def test_keeper_centralization_multi(self):
        r = A().analyze(make_vault(keeper_type="MULTI_KEEPER"))
        self.assertEqual(r["keeper_centralization_pct"], 35.0)

    def test_keeper_centralization_bot(self):
        r = A().analyze(make_vault(keeper_type="INCENTIVIZED_BOT"))
        self.assertEqual(r["keeper_centralization_pct"], 20.0)

    def test_keeper_centralization_unknown_default(self):
        r = A().analyze(make_vault(keeper_type="WEIRD_TYPE"))
        self.assertEqual(r["keeper_centralization_pct"], DEFAULT_CENTRALIZATION)

    def test_keeper_type_case_insensitive(self):
        r = A().analyze(make_vault(keeper_type="permissionless"))
        self.assertEqual(r["keeper_centralization_pct"], 5.0)

    def test_negative_hours_treated_as_zero(self):
        r = A().analyze(make_vault(hours_since_last_harvest=-10.0))
        self.assertAlmostEqual(r["harvest_staleness_ratio"], 0.0)


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_highly_reliable(self):
        r = A().analyze(make_vault(
            hours_since_last_harvest=3.0, observed_harvests_last_30d=30.0,
            expected_harvests_last_30d=30.0, keeper_type="PERMISSIONLESS",
            theoretical_apy_pct=9.0, realized_apy_pct=9.0,
        ))
        self.assertEqual(r["classification"], "HIGHLY_RELIABLE")

    def test_stalled_severe_staleness(self):
        # 200 / 24 = 8.3 > STALLED_RATIO
        r = A().analyze(make_vault(hours_since_last_harvest=200.0,
                                   expected_harvest_interval_hours=24.0))
        self.assertEqual(r["classification"], "STALLED")

    def test_degraded_mid(self):
        r = A().analyze(make_vault(
            hours_since_last_harvest=36.0, observed_harvests_last_30d=20.0,
            expected_harvests_last_30d=30.0, keeper_type="SINGLE_KEEPER",
            theoretical_apy_pct=12.0, realized_apy_pct=8.0,
        ))
        self.assertIn(r["classification"], {"DEGRADED", "UNRELIABLE", "RELIABLE"})

    def test_unreliable_low(self):
        r = A().analyze(make_vault(
            hours_since_last_harvest=60.0, observed_harvests_last_30d=8.0,
            expected_harvests_last_30d=30.0, keeper_type="MANUAL",
            theoretical_apy_pct=12.0, realized_apy_pct=3.0,
        ))
        self.assertIn(r["classification"], {"UNRELIABLE", "STALLED", "DEGRADED"})

    def test_classification_known_value(self):
        for v in [make_vault(), make_vault(hours_since_last_harvest=200.0),
                  make_vault(expected_harvest_interval_hours=0.0, theoretical_apy_pct=0.0)]:
            r = A().analyze(v)
            self.assertIn(r["classification"], {
                "HIGHLY_RELIABLE", "RELIABLE", "DEGRADED", "UNRELIABLE",
                "STALLED", "INSUFFICIENT_DATA",
            })

    def test_reliable_band(self):
        r = A().analyze(make_vault(
            hours_since_last_harvest=24.0, observed_harvests_last_30d=27.0,
            expected_harvests_last_30d=30.0, keeper_type="INCENTIVIZED_BOT",
            theoretical_apy_pct=10.0, realized_apy_pct=9.0,
        ))
        self.assertIn(r["classification"], {"RELIABLE", "HIGHLY_RELIABLE", "DEGRADED"})


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_fresh_harvest_flag(self):
        r = A().analyze(make_vault(hours_since_last_harvest=6.0))
        self.assertIn("FRESH_HARVEST", r["flags"])

    def test_stale_harvest_flag(self):
        r = A().analyze(make_vault(hours_since_last_harvest=48.0,
                                   expected_harvest_interval_hours=24.0))
        self.assertIn("STALE_HARVEST", r["flags"])

    def test_fresh_absent_when_stale(self):
        r = A().analyze(make_vault(hours_since_last_harvest=48.0,
                                   expected_harvest_interval_hours=24.0))
        self.assertNotIn("FRESH_HARVEST", r["flags"])

    def test_severely_stale_flag(self):
        # 100 / 24 = 4.16 > 3
        r = A().analyze(make_vault(hours_since_last_harvest=100.0,
                                   expected_harvest_interval_hours=24.0))
        self.assertIn("SEVERELY_STALE", r["flags"])

    def test_severely_stale_absent_when_fresh(self):
        r = A().analyze(make_vault(hours_since_last_harvest=6.0))
        self.assertNotIn("SEVERELY_STALE", r["flags"])

    def test_high_completion_flag(self):
        r = A().analyze(make_vault(observed_harvests_last_30d=29.0,
                                   expected_harvests_last_30d=30.0))
        self.assertIn("HIGH_COMPLETION", r["flags"])

    def test_high_completion_absent_when_low(self):
        r = A().analyze(make_vault(observed_harvests_last_30d=15.0,
                                   expected_harvests_last_30d=30.0))
        self.assertNotIn("HIGH_COMPLETION", r["flags"])

    def test_missed_harvests_flag(self):
        # missed 33% >= 20
        r = A().analyze(make_vault(observed_harvests_last_30d=20.0,
                                   expected_harvests_last_30d=30.0))
        self.assertIn("MISSED_HARVESTS", r["flags"])

    def test_missed_harvests_absent_when_complete(self):
        r = A().analyze(make_vault(observed_harvests_last_30d=30.0,
                                   expected_harvests_last_30d=30.0))
        self.assertNotIn("MISSED_HARVESTS", r["flags"])

    def test_significant_apy_drag_flag(self):
        r = A().analyze(make_vault(theoretical_apy_pct=12.0, realized_apy_pct=8.0))
        self.assertIn("SIGNIFICANT_APY_DRAG", r["flags"])

    def test_significant_apy_drag_absent_when_small(self):
        r = A().analyze(make_vault(theoretical_apy_pct=9.0, realized_apy_pct=8.8))
        self.assertNotIn("SIGNIFICANT_APY_DRAG", r["flags"])

    def test_centralized_keeper_flag_single(self):
        r = A().analyze(make_vault(keeper_type="SINGLE_KEEPER"))
        self.assertIn("CENTRALIZED_KEEPER", r["flags"])

    def test_centralized_keeper_flag_manual(self):
        r = A().analyze(make_vault(keeper_type="MANUAL"))
        self.assertIn("CENTRALIZED_KEEPER", r["flags"])

    def test_decentralized_keeper_flag_permissionless(self):
        r = A().analyze(make_vault(keeper_type="PERMISSIONLESS"))
        self.assertIn("DECENTRALIZED_KEEPER", r["flags"])

    def test_decentralized_keeper_flag_multi(self):
        r = A().analyze(make_vault(keeper_type="MULTI_KEEPER"))
        self.assertIn("DECENTRALIZED_KEEPER", r["flags"])

    def test_centralized_absent_for_permissionless(self):
        r = A().analyze(make_vault(keeper_type="PERMISSIONLESS"))
        self.assertNotIn("CENTRALIZED_KEEPER", r["flags"])

    def test_no_harvest_incentive_flag(self):
        # single keeper, no incentive
        r = A().analyze(make_vault(keeper_type="SINGLE_KEEPER",
                                   harvest_incentive_pct=0.0))
        self.assertIn("NO_HARVEST_INCENTIVE", r["flags"])

    def test_no_harvest_incentive_absent_when_permissionless(self):
        r = A().analyze(make_vault(keeper_type="PERMISSIONLESS",
                                   harvest_incentive_pct=0.0))
        self.assertNotIn("NO_HARVEST_INCENTIVE", r["flags"])

    def test_no_harvest_incentive_absent_when_paid(self):
        r = A().analyze(make_vault(keeper_type="SINGLE_KEEPER",
                                   harvest_incentive_pct=0.5))
        self.assertNotIn("NO_HARVEST_INCENTIVE", r["flags"])

    def test_stalled_flag(self):
        r = A().analyze(make_vault(hours_since_last_harvest=200.0,
                                   expected_harvest_interval_hours=24.0))
        self.assertIn("STALLED", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_interval_no_theoretical(self):
        r = A().analyze(make_vault(expected_harvest_interval_hours=0.0,
                                   theoretical_apy_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_insufficient_score_zero(self):
        r = A().analyze(make_vault(expected_harvest_interval_hours=0.0,
                                   theoretical_apy_pct=0.0))
        self.assertEqual(r["reliability_score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_sentinels_none(self):
        r = A().analyze(make_vault(expected_harvest_interval_hours=0.0,
                                   theoretical_apy_pct=0.0))
        self.assertIsNone(r["harvest_staleness_ratio"])
        self.assertIsNone(r["harvest_completion_rate_pct"])
        self.assertIsNone(r["apy_realization_pct"])

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_interval_only_sufficient(self):
        r = A().analyze(make_vault(expected_harvest_interval_hours=24.0,
                                   theoretical_apy_pct=0.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_theoretical_only_sufficient(self):
        r = A().analyze(make_vault(expected_harvest_interval_hours=0.0,
                                   theoretical_apy_pct=9.0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_fresher_harvest_scores_higher(self):
        fresh = A().analyze(make_vault(hours_since_last_harvest=3.0))
        stale = A().analyze(make_vault(hours_since_last_harvest=60.0))
        self.assertGreater(fresh["reliability_score"], stale["reliability_score"])

    def test_higher_completion_scores_higher(self):
        good = A().analyze(make_vault(observed_harvests_last_30d=30.0,
                                      expected_harvests_last_30d=30.0))
        bad = A().analyze(make_vault(observed_harvests_last_30d=10.0,
                                     expected_harvests_last_30d=30.0))
        self.assertGreater(good["reliability_score"], bad["reliability_score"])

    def test_higher_apy_realization_scores_higher(self):
        good = A().analyze(make_vault(theoretical_apy_pct=10.0, realized_apy_pct=10.0))
        bad = A().analyze(make_vault(theoretical_apy_pct=10.0, realized_apy_pct=3.0))
        self.assertGreater(good["reliability_score"], bad["reliability_score"])

    def test_more_decentralized_scores_higher(self):
        dec = A().analyze(make_vault(keeper_type="PERMISSIONLESS"))
        cen = A().analyze(make_vault(keeper_type="MANUAL"))
        self.assertGreater(dec["reliability_score"], cen["reliability_score"])

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_vault(
            hours_since_last_harvest=0.0, observed_harvests_last_30d=30.0,
            expected_harvests_last_30d=30.0, keeper_type="PERMISSIONLESS",
            theoretical_apy_pct=10.0, realized_apy_pct=10.0,
        ))
        self.assertLessEqual(r["reliability_score"], 100.0)
        self.assertGreaterEqual(r["reliability_score"], 0.0)

    def test_severe_staleness_scores_low(self):
        # Heavily stalled + missed harvests + big apy drag + centralized keeper.
        r = A().analyze(make_vault(hours_since_last_harvest=300.0,
                                   expected_harvest_interval_hours=24.0,
                                   observed_harvests_last_30d=5.0,
                                   expected_harvests_last_30d=30.0,
                                   keeper_type="MANUAL",
                                   theoretical_apy_pct=12.0,
                                   realized_apy_pct=2.0))
        self.assertLess(r["reliability_score"], 50.0)

    def test_freshness_component_lowers_score(self):
        # Same vault except staleness — fresh should beat severely stale.
        fresh = A().analyze(make_vault(hours_since_last_harvest=3.0))
        stale = A().analyze(make_vault(hours_since_last_harvest=300.0,
                                       expected_harvest_interval_hours=24.0))
        self.assertGreater(fresh["reliability_score"], stale["reliability_score"])


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_vault(token="Good"),
            make_vault(token="Stalled", hours_since_last_harvest=200.0,
                       expected_harvest_interval_hours=24.0,
                       keeper_type="SINGLE_KEEPER",
                       theoretical_apy_pct=12.0, realized_apy_pct=4.0),
            make_vault(token="Mid", hours_since_last_harvest=30.0,
                       observed_harvests_last_30d=22.0,
                       expected_harvests_last_30d=30.0,
                       keeper_type="INCENTIVIZED_BOT"),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_reliable_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["reliability_score"]
                  for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_reliable_vault"]], max(scores.values()))

    def test_least_reliable_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["reliability_score"]
                  for p in self.res["positions"]}
        self.assertEqual(scores[agg["least_reliable_vault"]], min(scores.values()))

    def test_most_reliable_is_good(self):
        self.assertEqual(self.res["aggregate"]["most_reliable_vault"], "Good")

    def test_stalled_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["stalled_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_reliability_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_reliable_vault"])
        self.assertIsNone(res["aggregate"]["least_reliable_vault"])

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_vault(expected_harvest_interval_hours=0.0, theoretical_apy_pct=0.0),
            make_vault(expected_harvest_interval_hours=0.0, theoretical_apy_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_reliable_vault"])
        self.assertEqual(res["aggregate"]["avg_reliability_score"], 0.0)

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)


# ── logging ───────────────────────────────────────────────────────────────────

class TestLogging(unittest.TestCase):
    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_vault(), cfg={"log_path": path}, write_log=True)
            self.assertTrue(os.path.exists(path))
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)

    def test_no_write_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze(make_vault(), cfg={"log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            cfg = {"log_path": path, "log_cap": 3}
            for _ in range(6):
                A().analyze_portfolio([make_vault()], cfg=cfg, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 3)

    def test_ring_buffer_cap_100_default(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            cfg = {"log_path": path, "log_cap": LOG_CAP}
            for _ in range(105):
                A().analyze(make_vault(), cfg=cfg, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 100)

    def test_corrupt_log_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            with open(path, "w") as fh:
                fh.write("{not valid json")
            A().analyze(make_vault(), cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)

    def test_log_entry_has_snapshots(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([make_vault(), make_vault(token="B")],
                                  cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(data[0]["position_count"], 2)
            self.assertEqual(len(data[0]["snapshots"]), 2)

    def test_log_json_no_inf_nan(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([
                make_vault(),
                make_vault(token="ni", expected_harvest_interval_hours=0.0,
                           theoretical_apy_pct=9.0),
                make_vault(token="ne", expected_harvests_last_30d=0.0),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "token": "S",
            "expected_harvest_interval_hours": "24",
            "hours_since_last_harvest": "6",
            "observed_harvests_last_30d": "30",
            "expected_harvests_last_30d": "30",
            "keeper_type": "PERMISSIONLESS",
            "theoretical_apy_pct": "9",
            "realized_apy_pct": "8.8",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({
            "token": "S",
            "expected_harvest_interval_hours": 24.0,
            "theoretical_apy_pct": 9.0,
        })
        self.assertIn("classification", r)

    def test_vault_field_alias(self):
        r = A().analyze({
            "vault": "MyVault",
            "expected_harvest_interval_hours": 24.0,
            "theoretical_apy_pct": 9.0,
        })
        self.assertEqual(r["token"], "MyVault")

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio([make_vault(token=f"V{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_vault(),
            make_vault(expected_harvest_interval_hours=0.0, theoretical_apy_pct=0.0),
            make_vault(hours_since_last_harvest=200.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for v in [make_vault(), make_vault(expected_harvests_last_30d=0.0),
                  make_vault(theoretical_apy_pct=0.0),
                  make_vault(hours_since_last_harvest=500.0)]:
            r = A().analyze(v)
            for val in r.values():
                if isinstance(val, float):
                    self.assertFalse(math.isinf(val))
                    self.assertFalse(math.isnan(val))

    def test_negative_incentive_treated_as_zero(self):
        r = A().analyze(make_vault(keeper_type="SINGLE_KEEPER",
                                   harvest_incentive_pct=-5.0))
        self.assertIn("NO_HARVEST_INCENTIVE", r["flags"])


if __name__ == "__main__":
    unittest.main()
