"""
Tests for MP-1171: DeFiProtocolVaultRelativeYieldOutlierAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_vault_relative_yield_outlier_analyzer -v
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

from spa_core.analytics.defi_protocol_vault_relative_yield_outlier_analyzer import (  # noqa: E501
    DeFiProtocolVaultRelativeYieldOutlierAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    Z_SCORE_CEILING,
    EXTREME_HIGH_Z,
    HIGH_Z,
    LOW_Z,
    THIN_COHORT_MAX,
    MIN_PEERS,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    apr_pct=9.5,
    peer_aprs_pct=None,
):
    if peer_aprs_pct is None:
        peer_aprs_pct = [9.0, 9.2, 9.8, 10.1, 8.9]
    return {
        "vault": vault,
        "apr_pct": apr_pct,
        "peer_aprs_pct": peer_aprs_pct,
    }


def A():
    return DeFiProtocolVaultRelativeYieldOutlierAnalyzer()


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

    def test_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(10, 2, 1e9), 5.0)

    def test_safe_div_zero_denominator(self):
        self.assertEqual(_safe_div(10, 0, 1e9), 1e9)

    def test_safe_div_none_sentinel(self):
        self.assertIsNone(_safe_div(10, 0, None))

    def test_build_default_cfg(self):
        cfg = _build_default_cfg()
        self.assertEqual(cfg["log_path"], LOG_PATH)
        self.assertEqual(cfg["log_cap"], LOG_CAP)

    def test_build_default_cfg_override(self):
        cfg = _build_default_cfg({"log_cap": 5})
        self.assertEqual(cfg["log_cap"], 5)

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

    def test_grade_zero(self):
        self.assertEqual(_grade_from_score(0.0), "F")

    def test_grade_hundred(self):
        self.assertEqual(_grade_from_score(100.0), "A")

    def test_constants_sane(self):
        self.assertGreater(Z_SCORE_CEILING, 0)
        self.assertGreaterEqual(EXTREME_HIGH_Z, HIGH_Z)
        self.assertLess(LOW_Z, 0)
        self.assertGreater(THIN_COHORT_MAX, 0)
        self.assertEqual(MIN_PEERS, 2)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "apr_pct", "peer_count", "peer_median", "peer_mean",
            "peer_stdev", "excess_apr_pct", "excess_vs_mean_pct", "z_score",
            "pct_above_median", "percentile_rank", "is_high_outlier",
            "is_low_outlier", "score", "classification", "recommendation",
            "grade", "flags",
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
        r = A().analyze({"token": "AltKey", "apr_pct": 9.0,
                         "peer_aprs_pct": [9, 10]})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "apr_pct": 9.0,
                         "peer_aprs_pct": [9, 10]})
        self.assertEqual(r["token"], "V")

    def test_token_default_unknown(self):
        r = A().analyze({"apr_pct": 9.0, "peer_aprs_pct": [9, 10]})
        self.assertEqual(r["token"], "UNKNOWN")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        finite_check(self, self.r)

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {
            "HOLD", "VERIFY_OR_AVOID", "INVESTIGATE_BEFORE_SIZING",
            "CONSIDER_PEER_ALTERNATIVE", "DEPLOY_OK",
        })

    def test_grade_known(self):
        self.assertIn(self.r["grade"], {"A", "B", "C", "D", "F"})

    def test_classification_known(self):
        self.assertIn(self.r["classification"], {
            "EXTREME_HIGH_OUTLIER", "HIGH_OUTLIER", "LOW_OUTLIER",
            "IN_LINE", "INSUFFICIENT_DATA",
        })

    def test_peer_count_is_int(self):
        self.assertIsInstance(self.r["peer_count"], int)

    def test_is_high_outlier_is_bool(self):
        self.assertIsInstance(self.r["is_high_outlier"], bool)

    def test_is_low_outlier_is_bool(self):
        self.assertIsInstance(self.r["is_low_outlier"], bool)


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_apr_echo(self):
        r = A().analyze(make_pos(apr_pct=12.34))
        self.assertAlmostEqual(r["apr_pct"], 12.34)

    def test_peer_count(self):
        r = A().analyze(make_pos(peer_aprs_pct=[1, 2, 3, 4]))
        self.assertEqual(r["peer_count"], 4)

    def test_peer_count_filters_non_finite(self):
        r = A().analyze(make_pos(
            apr_pct=9.0,
            peer_aprs_pct=[9.0, 10.0, "bad", None]))
        # "bad"/None drop out → 2 valid peers
        self.assertEqual(r["peer_count"], 2)

    def test_peer_median(self):
        r = A().analyze(make_pos(apr_pct=10.0, peer_aprs_pct=[8, 10, 12]))
        self.assertAlmostEqual(r["peer_median"], 10.0)

    def test_peer_mean(self):
        r = A().analyze(make_pos(apr_pct=10.0, peer_aprs_pct=[8, 10, 12]))
        self.assertAlmostEqual(r["peer_mean"], 10.0)

    def test_peer_stdev_present(self):
        r = A().analyze(make_pos(apr_pct=10.0, peer_aprs_pct=[8, 10, 12]))
        self.assertGreater(r["peer_stdev"], 0.0)

    def test_peer_stdev_zero_identical(self):
        r = A().analyze(make_pos(apr_pct=10.0, peer_aprs_pct=[9, 9, 9]))
        self.assertAlmostEqual(r["peer_stdev"], 0.0)

    def test_excess_apr(self):
        r = A().analyze(make_pos(apr_pct=15.0, peer_aprs_pct=[8, 10, 12]))
        self.assertAlmostEqual(r["excess_apr_pct"], 15.0 - 10.0)

    def test_excess_vs_mean(self):
        r = A().analyze(make_pos(apr_pct=15.0, peer_aprs_pct=[8, 10, 12]))
        self.assertAlmostEqual(r["excess_vs_mean_pct"], 15.0 - 10.0)

    def test_z_score_value(self):
        # apr=20, peers mean=10, pstdev computed
        peers = [8.0, 9.0, 10.0, 11.0, 12.0]
        import statistics
        mean = statistics.mean(peers)
        sd = statistics.pstdev(peers)
        r = A().analyze(make_pos(apr_pct=20.0, peer_aprs_pct=peers))
        self.assertAlmostEqual(r["z_score"], round((20.0 - mean) / sd, 4),
                               places=3)

    def test_z_score_none_thin(self):
        r = A().analyze(make_pos(apr_pct=10.0, peer_aprs_pct=[9]))
        self.assertIsNone(r["z_score"])

    def test_z_score_none_identical_peers(self):
        r = A().analyze(make_pos(apr_pct=20.0, peer_aprs_pct=[9, 9, 9, 9]))
        self.assertIsNone(r["z_score"])

    def test_pct_above_median(self):
        r = A().analyze(make_pos(apr_pct=15.0, peer_aprs_pct=[8, 10, 12]))
        # excess=5, median=10 → 50%
        self.assertAlmostEqual(r["pct_above_median"], 50.0)

    def test_pct_above_median_none_zero_median(self):
        r = A().analyze(make_pos(apr_pct=5.0, peer_aprs_pct=[0, 0, 0]))
        self.assertIsNone(r["pct_above_median"])

    def test_percentile_rank(self):
        # apr=11; peers 8,9,10,12,13 → 3 strictly below → 60%
        r = A().analyze(make_pos(apr_pct=11.0,
                                 peer_aprs_pct=[8, 9, 10, 12, 13]))
        self.assertAlmostEqual(r["percentile_rank"], 60.0)

    def test_percentile_rank_zero(self):
        # apr below all
        r = A().analyze(make_pos(apr_pct=1.0, peer_aprs_pct=[8, 9, 10]))
        self.assertAlmostEqual(r["percentile_rank"], 0.0)

    def test_percentile_rank_hundred(self):
        # apr above all
        r = A().analyze(make_pos(apr_pct=100.0, peer_aprs_pct=[8, 9, 10]))
        self.assertAlmostEqual(r["percentile_rank"], 100.0)

    def test_percentile_rank_in_range(self):
        r = A().analyze(make_pos())
        self.assertGreaterEqual(r["percentile_rank"], 0.0)
        self.assertLessEqual(r["percentile_rank"], 100.0)

    def test_is_high_outlier_true(self):
        r = A().analyze(make_pos(apr_pct=42.0,
                                 peer_aprs_pct=[8, 9, 10, 9.5, 8.5]))
        self.assertTrue(r["is_high_outlier"])

    def test_is_low_outlier_true(self):
        r = A().analyze(make_pos(apr_pct=1.0,
                                 peer_aprs_pct=[9, 9.5, 10, 9.8, 9.2]))
        self.assertTrue(r["is_low_outlier"])

    def test_metrics_rounded(self):
        r = A().analyze(make_pos())
        for k in ("apr_pct", "peer_median", "peer_mean", "peer_stdev",
                  "excess_apr_pct", "excess_vs_mean_pct", "percentile_rank"):
            self.assertEqual(r[k], round(r[k], 4))


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_insufficient_no_peers(self):
        r = A().analyze(make_pos(peer_aprs_pct=[]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_one_peer(self):
        r = A().analyze(make_pos(peer_aprs_pct=[9]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_identical_peers(self):
        # >=2 peers but stdev 0 → z None → INSUFFICIENT_DATA
        r = A().analyze(make_pos(apr_pct=20.0, peer_aprs_pct=[9, 9, 9]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_extreme_high_outlier(self):
        r = A().analyze(make_pos(apr_pct=60.0,
                                 peer_aprs_pct=[8, 9, 10, 9.5, 8.5]))
        self.assertEqual(r["classification"], "EXTREME_HIGH_OUTLIER")

    def test_high_outlier(self):
        # z between 2 and 3
        # peers mean 10, pstdev ~1.414; apr ~12.8 → z ~2 (need 2<=z<3)
        peers = [8.0, 9.0, 10.0, 11.0, 12.0]
        r = A().analyze(make_pos(apr_pct=16.0, peer_aprs_pct=peers))
        # z = (16-10)/1.414 = 4.24 → extreme; pick smaller apr
        r2 = A().analyze(make_pos(apr_pct=13.0, peer_aprs_pct=peers))
        # z=(13-10)/1.414=2.12 → high
        self.assertEqual(r2["classification"], "HIGH_OUTLIER")
        self.assertEqual(r["classification"], "EXTREME_HIGH_OUTLIER")

    def test_low_outlier(self):
        peers = [8.0, 9.0, 10.0, 11.0, 12.0]
        # apr=7 → z=(7-10)/1.414=-2.12 → low
        r = A().analyze(make_pos(apr_pct=7.0, peer_aprs_pct=peers))
        self.assertEqual(r["classification"], "LOW_OUTLIER")

    def test_in_line(self):
        peers = [8.0, 9.0, 10.0, 11.0, 12.0]
        r = A().analyze(make_pos(apr_pct=10.0, peer_aprs_pct=peers))
        self.assertEqual(r["classification"], "IN_LINE")

    def test_classification_known_many(self):
        for pos in [make_pos(peer_aprs_pct=[]),
                    make_pos(peer_aprs_pct=[9]),
                    make_pos(apr_pct=20.0, peer_aprs_pct=[9, 9, 9]),
                    make_pos(apr_pct=60.0,
                             peer_aprs_pct=[8, 9, 10, 9.5, 8.5]),
                    make_pos(apr_pct=10.0,
                             peer_aprs_pct=[8, 9, 10, 11, 12])]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "EXTREME_HIGH_OUTLIER", "HIGH_OUTLIER", "LOW_OUTLIER",
                "IN_LINE", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_insufficient_hold(self):
        r = A().analyze(make_pos(peer_aprs_pct=[]))
        self.assertEqual(r["recommendation"], "HOLD")

    def test_extreme_verify_or_avoid(self):
        r = A().analyze(make_pos(apr_pct=60.0,
                                 peer_aprs_pct=[8, 9, 10, 9.5, 8.5]))
        self.assertEqual(r["recommendation"], "VERIFY_OR_AVOID")

    def test_high_investigate(self):
        peers = [8.0, 9.0, 10.0, 11.0, 12.0]
        r = A().analyze(make_pos(apr_pct=13.0, peer_aprs_pct=peers))
        self.assertEqual(r["recommendation"], "INVESTIGATE_BEFORE_SIZING")

    def test_low_consider_alternative(self):
        peers = [8.0, 9.0, 10.0, 11.0, 12.0]
        r = A().analyze(make_pos(apr_pct=7.0, peer_aprs_pct=peers))
        self.assertEqual(r["recommendation"], "CONSIDER_PEER_ALTERNATIVE")

    def test_in_line_deploy_ok(self):
        peers = [8.0, 9.0, 10.0, 11.0, 12.0]
        r = A().analyze(make_pos(apr_pct=10.0, peer_aprs_pct=peers))
        self.assertEqual(r["recommendation"], "DEPLOY_OK")

    def test_rec_known_many(self):
        for pos in [make_pos(peer_aprs_pct=[]),
                    make_pos(apr_pct=60.0,
                             peer_aprs_pct=[8, 9, 10, 9.5, 8.5]),
                    make_pos(apr_pct=7.0,
                             peer_aprs_pct=[8, 9, 10, 11, 12]),
                    make_pos(apr_pct=10.0,
                             peer_aprs_pct=[8, 9, 10, 11, 12])]:
            r = A().analyze(pos)
            self.assertIn(r["recommendation"], {
                "HOLD", "VERIFY_OR_AVOID", "INVESTIGATE_BEFORE_SIZING",
                "CONSIDER_PEER_ALTERNATIVE", "DEPLOY_OK",
            })


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_extreme_high_flag(self):
        r = A().analyze(make_pos(apr_pct=60.0,
                                 peer_aprs_pct=[8, 9, 10, 9.5, 8.5]))
        self.assertIn("EXTREME_HIGH_OUTLIER", r["flags"])

    def test_high_flag(self):
        peers = [8.0, 9.0, 10.0, 11.0, 12.0]
        r = A().analyze(make_pos(apr_pct=13.0, peer_aprs_pct=peers))
        self.assertIn("HIGH_OUTLIER", r["flags"])

    def test_low_flag(self):
        peers = [8.0, 9.0, 10.0, 11.0, 12.0]
        r = A().analyze(make_pos(apr_pct=7.0, peer_aprs_pct=peers))
        self.assertIn("LOW_OUTLIER", r["flags"])

    def test_in_line_flag(self):
        peers = [8.0, 9.0, 10.0, 11.0, 12.0]
        r = A().analyze(make_pos(apr_pct=10.0, peer_aprs_pct=peers))
        self.assertIn("IN_LINE", r["flags"])

    def test_above_median_flag(self):
        r = A().analyze(make_pos(apr_pct=15.0,
                                 peer_aprs_pct=[8, 9, 10, 11, 12]))
        self.assertIn("ABOVE_MEDIAN", r["flags"])

    def test_below_median_flag(self):
        r = A().analyze(make_pos(apr_pct=5.0,
                                 peer_aprs_pct=[8, 9, 10, 11, 12]))
        self.assertIn("BELOW_MEDIAN", r["flags"])

    def test_above_below_mutually_exclusive(self):
        r = A().analyze(make_pos(apr_pct=15.0,
                                 peer_aprs_pct=[8, 9, 10, 11, 12]))
        self.assertNotIn("BELOW_MEDIAN", r["flags"])

    def test_thin_cohort_flag(self):
        # 2 valid peers < 5
        r = A().analyze(make_pos(apr_pct=10.0, peer_aprs_pct=[9, 11]))
        self.assertIn("THIN_COHORT", r["flags"])

    def test_thin_cohort_absent_large(self):
        r = A().analyze(make_pos(apr_pct=10.0,
                                 peer_aprs_pct=[8, 9, 10, 11, 12, 13]))
        self.assertNotIn("THIN_COHORT", r["flags"])

    def test_thin_cohort_boundary(self):
        # exactly 5 → not thin
        r = A().analyze(make_pos(apr_pct=10.0,
                                 peer_aprs_pct=[8, 9, 10, 11, 12]))
        self.assertNotIn("THIN_COHORT", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(peer_aprs_pct=[]))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_no_peers(self):
        r = A().analyze(make_pos(peer_aprs_pct=[]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_one_peer(self):
        r = A().analyze(make_pos(peer_aprs_pct=[9.0]))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_score_zero(self):
        r = A().analyze(make_pos(peer_aprs_pct=[]))
        self.assertEqual(r["score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_z_none(self):
        r = A().analyze(make_pos(peer_aprs_pct=[]))
        self.assertIsNone(r["z_score"])

    def test_pct_above_median_none(self):
        r = A().analyze(make_pos(peer_aprs_pct=[]))
        self.assertIsNone(r["pct_above_median"])

    def test_recommendation(self):
        r = A().analyze(make_pos(peer_aprs_pct=[]))
        self.assertEqual(r["recommendation"], "HOLD")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")

    def test_apr_still_echoed(self):
        r = A().analyze(make_pos(apr_pct=15.0, peer_aprs_pct=[]))
        self.assertAlmostEqual(r["apr_pct"], 15.0)

    def test_insufficient_fields(self):
        r = A().analyze({})
        self.assertEqual(r["grade"], "F")
        self.assertEqual(r["flags"], ["INSUFFICIENT_DATA"])
        self.assertFalse(r["is_high_outlier"])
        self.assertFalse(r["is_low_outlier"])

    def test_insufficient_no_inf_nan(self):
        finite_check(self, A().analyze({}))

    def test_insufficient_json(self):
        json.dumps(A().analyze({}))

    def test_non_list_peers(self):
        r = A().analyze({"vault": "S", "apr_pct": 9.0,
                         "peer_aprs_pct": "notalist"})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_all_garbage_peers(self):
        r = A().analyze({"vault": "S", "apr_pct": 9.0,
                         "peer_aprs_pct": ["a", None, {}]})
        self.assertEqual(r["peer_count"], 0)
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_valid_with_two_distinct_peers(self):
        r = A().analyze(make_pos(apr_pct=10.0, peer_aprs_pct=[9, 11]))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")


# ── scoring ────────────────────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_in_line_scores_high(self):
        peers = [8.0, 9.0, 10.0, 11.0, 12.0]
        r = A().analyze(make_pos(apr_pct=10.0, peer_aprs_pct=peers))
        self.assertGreater(r["score"], 85.0)

    def test_extreme_outlier_scores_low(self):
        r = A().analyze(make_pos(apr_pct=60.0,
                                 peer_aprs_pct=[8, 9, 10, 9.5, 8.5]))
        self.assertLess(r["score"], 40.0)

    def test_closer_to_median_scores_higher(self):
        peers = [8.0, 9.0, 10.0, 11.0, 12.0]
        close = A().analyze(make_pos(apr_pct=10.0, peer_aprs_pct=peers))
        far = A().analyze(make_pos(apr_pct=13.0, peer_aprs_pct=peers))
        self.assertGreater(close["score"], far["score"])

    def test_high_outlier_penalised(self):
        peers = [8.0, 9.0, 10.0, 11.0, 12.0]
        high = A().analyze(make_pos(apr_pct=13.0, peer_aprs_pct=peers))
        low = A().analyze(make_pos(apr_pct=7.0, peer_aprs_pct=peers))
        # both |z| ~2.1; high outlier loses the 30-pt not-high component
        self.assertLess(high["score"], low["score"])

    def test_score_floor(self):
        r = A().analyze(make_pos(apr_pct=1e6,
                                 peer_aprs_pct=[8, 9, 10, 11, 12]))
        self.assertGreaterEqual(r["score"], 0.0)

    def test_score_extreme_bounds(self):
        r = A().analyze(make_pos(apr_pct=1e9,
                                 peer_aprs_pct=[8, 9, 10, 11, 12]))
        self.assertGreaterEqual(r["score"], 0.0)
        self.assertLessEqual(r["score"], 100.0)

    def test_score_in_range_many(self):
        for pos in [make_pos(peer_aprs_pct=[]),
                    make_pos(apr_pct=10.0, peer_aprs_pct=[8, 9, 10, 11, 12]),
                    make_pos(apr_pct=60.0,
                             peer_aprs_pct=[8, 9, 10, 9.5, 8.5]),
                    make_pos(apr_pct=20.0, peer_aprs_pct=[9, 9, 9])]:
            r = A().analyze(pos)
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 100.0)

    def test_grade_maps_from_score(self):
        for pos in [make_pos(apr_pct=10.0, peer_aprs_pct=[8, 9, 10, 11, 12]),
                    make_pos(apr_pct=60.0,
                             peer_aprs_pct=[8, 9, 10, 9.5, 8.5])]:
            r = A().analyze(pos)
            self.assertEqual(r["grade"], _grade_from_score(r["score"]))


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Trusted", apr_pct=10.0,
                     peer_aprs_pct=[8, 9, 10, 11, 12]),
            make_pos(vault="Sketchy", apr_pct=60.0,
                     peer_aprs_pct=[8, 9, 10, 9.5, 8.5]),
            make_pos(vault="Mid", apr_pct=13.0,
                     peer_aprs_pct=[8, 9, 10, 11, 12]),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_trustworthy_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["most_trustworthy_vault"]],
                         max(scores.values()))

    def test_least_trustworthy_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["score"] for p in self.res["positions"]}
        self.assertEqual(scores[agg["least_trustworthy_vault"]],
                         min(scores.values()))

    def test_most_trustworthy_is_trusted(self):
        self.assertEqual(self.res["aggregate"]["most_trustworthy_vault"],
                         "Trusted")

    def test_least_trustworthy_is_sketchy(self):
        self.assertEqual(self.res["aggregate"]["least_trustworthy_vault"],
                         "Sketchy")

    def test_high_outlier_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["high_outlier_count"], 1)

    def test_avg_in_range(self):
        avg = self.res["aggregate"]["avg_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_trustworthy_vault"])
        self.assertIsNone(res["aggregate"]["least_trustworthy_vault"])
        self.assertEqual(res["aggregate"]["position_count"], 0)
        self.assertEqual(res["aggregate"]["high_outlier_count"], 0)

    def test_all_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(peer_aprs_pct=[]),
            make_pos(peer_aprs_pct=[9]),
        ])
        self.assertIsNone(res["aggregate"]["most_trustworthy_vault"])
        self.assertEqual(res["aggregate"]["avg_score"], 0.0)
        self.assertEqual(res["aggregate"]["position_count"], 2)

    def test_single_position(self):
        res = A().analyze_portfolio([make_pos(vault="Solo")])
        self.assertEqual(res["aggregate"]["most_trustworthy_vault"], "Solo")
        self.assertEqual(res["aggregate"]["least_trustworthy_vault"], "Solo")

    def test_portfolio_json(self):
        json.dumps(self.res)

    def test_high_outlier_count_value(self):
        res = A().analyze_portfolio([
            make_pos(vault="H1", apr_pct=60.0,
                     peer_aprs_pct=[8, 9, 10, 9.5, 8.5]),
            make_pos(vault="H2", apr_pct=13.0,
                     peer_aprs_pct=[8, 9, 10, 11, 12]),
            make_pos(vault="OK", apr_pct=10.0,
                     peer_aprs_pct=[8, 9, 10, 11, 12]),
        ])
        self.assertEqual(res["aggregate"]["high_outlier_count"], 2)

    def test_avg_excludes_insufficient(self):
        res = A().analyze_portfolio([
            make_pos(vault="Good", apr_pct=10.0,
                     peer_aprs_pct=[8, 9, 10, 11, 12]),
            make_pos(vault="Ins", peer_aprs_pct=[]),
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

    def test_log_has_snapshots(self):
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

    def test_log_no_inf_nan(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([
                make_pos(),
                make_pos(vault="big", apr_pct=1e9,
                         peer_aprs_pct=[8, 9, 10, 11, 12]),
                make_pos(vault="ins", peer_aprs_pct=[]),
            ], cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            json.loads(raw)

    def test_log_null_z_serialized(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            # insufficient (z None) result still logs cleanly
            res = A().analyze(make_pos(peer_aprs_pct=[]))
            json.dumps(res)
            A().analyze(make_pos(peer_aprs_pct=[]),
                        cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                raw = fh.read()
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

    def test_no_write_demo_no_production_log(self):
        before = os.path.exists(LOG_PATH)
        A().analyze_portfolio(_demo_positions())
        after = os.path.exists(LOG_PATH)
        self.assertEqual(before, after)


# ── robustness ────────────────────────────────────────────────────────────────

class TestRobustness(unittest.TestCase):
    def test_string_numbers_coerced(self):
        r = A().analyze({
            "vault": "S",
            "apr_pct": "10.0",
            "peer_aprs_pct": ["8", "9", "10", "11", "12"],
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_peer_field(self):
        r = A().analyze({"vault": "S", "apr_pct": 9.0})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_large_portfolio(self):
        res = A().analyze_portfolio(
            [make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_json_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(),
            make_pos(peer_aprs_pct=[]),
            make_pos(apr_pct=60.0, peer_aprs_pct=[8, 9, 10, 9.5, 8.5]),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(),
                    make_pos(peer_aprs_pct=[]),
                    make_pos(apr_pct=20.0, peer_aprs_pct=[9, 9, 9]),
                    make_pos(apr_pct=1e9,
                             peer_aprs_pct=[8, 9, 10, 11, 12]),
                    make_pos(apr_pct=-1e9,
                             peer_aprs_pct=[8, 9, 10, 11, 12]),
                    make_pos(apr_pct=5.0, peer_aprs_pct=[0, 0, 0]),
                    make_pos(apr_pct=5.0,
                             peer_aprs_pct=[float("inf"), 9, 10, 11])]:
            r = A().analyze(pos)
            finite_check(self, r)

    def test_inf_peers_filtered(self):
        r = A().analyze(make_pos(apr_pct=10.0,
                                 peer_aprs_pct=[float("inf"),
                                                float("-inf"), 9, 11]))
        # only 9 and 11 survive
        self.assertEqual(r["peer_count"], 2)
        finite_check(self, r)

    def test_nan_peers_filtered(self):
        r = A().analyze(make_pos(apr_pct=10.0,
                                 peer_aprs_pct=[float("nan"), 9, 11, 12]))
        self.assertEqual(r["peer_count"], 3)
        finite_check(self, r)

    def test_huge_apr_no_crash(self):
        r = A().analyze(make_pos(apr_pct=1e15,
                                 peer_aprs_pct=[8, 9, 10, 11, 12]))
        self.assertIn("classification", r)
        self.assertLessEqual(r["score"], 100.0)
        finite_check(self, r)

    def test_negative_apr_no_crash(self):
        r = A().analyze(make_pos(apr_pct=-50.0,
                                 peer_aprs_pct=[8, 9, 10, 11, 12]))
        self.assertIn("classification", r)
        finite_check(self, r)

    def test_identical_peers_no_inf(self):
        r = A().analyze(make_pos(apr_pct=20.0, peer_aprs_pct=[9, 9, 9, 9]))
        finite_check(self, r)
        self.assertIsNone(r["z_score"])


# ── CLI smoke ─────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    def test_demo_nonempty(self):
        self.assertGreater(len(_demo_positions()), 0)

    def test_demo_count(self):
        self.assertEqual(len(_demo_positions()), 4)

    def test_demo_runs(self):
        res = A().analyze_portfolio(_demo_positions())
        self.assertEqual(len(res["positions"]), len(_demo_positions()))
        self.assertIn("aggregate", res)

    def test_demo_json(self):
        json.dumps(A().analyze_portfolio(_demo_positions()))

    def test_demo_no_inf_nan(self):
        raw = json.dumps(A().analyze_portfolio(_demo_positions()))
        self.assertNotIn("Infinity", raw)
        self.assertNotIn("NaN", raw)

    def test_demo_varied_classifications(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertGreater(len(classes), 1)

    def test_demo_includes_insufficient(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("INSUFFICIENT_DATA", classes)

    def test_demo_includes_extreme_high(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("EXTREME_HIGH_OUTLIER", classes)

    def test_demo_includes_in_line(self):
        res = A().analyze_portfolio(_demo_positions())
        classes = {p["classification"] for p in res["positions"]}
        self.assertIn("IN_LINE", classes)

    def test_demo_each_finite(self):
        res = A().analyze_portfolio(_demo_positions())
        for p in res["positions"]:
            finite_check(self, p)


if __name__ == "__main__":
    unittest.main()
