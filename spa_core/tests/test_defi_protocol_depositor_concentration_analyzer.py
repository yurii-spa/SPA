"""
Tests for MP-1155: DeFiProtocolDepositorConcentrationAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_depositor_concentration_analyzer -v
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

from spa_core.analytics.defi_protocol_depositor_concentration_analyzer import (
    DeFiProtocolDepositorConcentrationAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    _demo_positions,
    COUNT_SENTINEL_MAX,
    HHI_MAX,
    WHALE_DOMINATED_PCT,
    HIGHLY_CONCENTRATED_PCT,
    MODERATELY_CONCENTRATED_PCT,
    HIGH_TOP5_PCT,
    FEW_DEPOSITORS,
    SEVERE_EXIT_DROP_PCT,
    LOW_HHI,
    HIGH_HHI,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    vault="USDC-Vault",
    total_tvl_usd=100_000_000.0,
    top1_share_pct=6.0,
    top5_share_pct=22.0,
    depositor_count=4200,
    my_position_usd=500_000.0,
    hhi=None,
):
    p = {
        "vault": vault,
        "total_tvl_usd": total_tvl_usd,
        "top1_share_pct": top1_share_pct,
        "top5_share_pct": top5_share_pct,
        "depositor_count": depositor_count,
        "my_position_usd": my_position_usd,
    }
    if hhi is not None:
        p["hhi"] = hhi
    return p


def A():
    return DeFiProtocolDepositorConcentrationAnalyzer()


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
        self.assertGreater(COUNT_SENTINEL_MAX, 0)
        self.assertEqual(HHI_MAX, 10000.0)
        self.assertGreater(WHALE_DOMINATED_PCT, HIGHLY_CONCENTRATED_PCT)
        self.assertGreater(HIGHLY_CONCENTRATED_PCT, MODERATELY_CONCENTRATED_PCT)
        self.assertGreater(HIGH_TOP5_PCT, 0)
        self.assertGreater(FEW_DEPOSITORS, 0)
        self.assertGreater(SEVERE_EXIT_DROP_PCT, 0)
        self.assertGreater(HIGH_HHI, LOW_HHI)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "total_tvl_usd", "top1_share_pct", "top5_share_pct",
            "depositor_count", "effective_depositor_count",
            "whale_exit_tvl_drop_pct", "my_share_of_tvl_pct",
            "post_whale_exit_my_share_pct", "concentration_hhi",
            "concentration_score", "classification", "recommendation",
            "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["concentration_score"], 0.0)
        self.assertLessEqual(self.r["concentration_score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "USDC-Vault")

    def test_token_field_alias(self):
        r = A().analyze({"token": "AltKey", "total_tvl_usd": 1e6,
                         "top1_share_pct": 10.0})
        self.assertEqual(r["token"], "AltKey")

    def test_vault_preferred_over_token(self):
        r = A().analyze({"vault": "V", "token": "T", "total_tvl_usd": 1e6,
                         "top1_share_pct": 10.0})
        self.assertEqual(r["token"], "V")

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


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_top1_normalized(self):
        r = A().analyze(make_pos(top1_share_pct=35.0))
        self.assertAlmostEqual(r["top1_share_pct"], 35.0)

    def test_top1_clamped_high(self):
        r = A().analyze(make_pos(top1_share_pct=150.0))
        self.assertAlmostEqual(r["top1_share_pct"], 100.0)

    def test_top1_clamped_negative(self):
        r = A().analyze(make_pos(top1_share_pct=-10.0, top5_share_pct=20.0))
        self.assertAlmostEqual(r["top1_share_pct"], 0.0)

    def test_top5_at_least_top1(self):
        # top5 given lower than top1 → coerced up to top1
        r = A().analyze(make_pos(top1_share_pct=40.0, top5_share_pct=10.0))
        self.assertGreaterEqual(r["top5_share_pct"], 40.0)

    def test_top5_clamped_high(self):
        r = A().analyze(make_pos(top1_share_pct=10.0, top5_share_pct=200.0))
        self.assertAlmostEqual(r["top5_share_pct"], 100.0)

    def test_whale_exit_drop_equals_top1(self):
        r = A().analyze(make_pos(top1_share_pct=45.0))
        self.assertAlmostEqual(r["whale_exit_tvl_drop_pct"], 45.0)

    def test_my_share_of_tvl(self):
        # 500k / 100M = 0.5%
        r = A().analyze(make_pos(total_tvl_usd=100_000_000.0,
                                 my_position_usd=500_000.0))
        self.assertAlmostEqual(r["my_share_of_tvl_pct"], 0.5)

    def test_my_share_zero_when_no_position(self):
        r = A().analyze(make_pos(my_position_usd=0.0))
        self.assertAlmostEqual(r["my_share_of_tvl_pct"], 0.0)

    def test_post_whale_exit_my_share_increases(self):
        # whale exit shrinks denominator → my share rises
        r = A().analyze(make_pos(total_tvl_usd=10_000_000.0,
                                 top1_share_pct=50.0,
                                 my_position_usd=100_000.0))
        self.assertGreater(r["post_whale_exit_my_share_pct"],
                           r["my_share_of_tvl_pct"])

    def test_post_whale_exit_100pct_whale(self):
        # whale is the entire vault → remaining frac 0 → 0 share
        r = A().analyze(make_pos(total_tvl_usd=10_000_000.0,
                                 top1_share_pct=100.0,
                                 my_position_usd=100_000.0))
        self.assertAlmostEqual(r["post_whale_exit_my_share_pct"], 0.0)

    def test_effective_count_from_reported(self):
        r = A().analyze(make_pos(depositor_count=4200))
        self.assertAlmostEqual(r["effective_depositor_count"], 4200.0)

    def test_effective_count_estimated_when_no_count(self):
        # no depositor_count → derived from HHI
        r = A().analyze(make_pos(depositor_count=0, top1_share_pct=20.0,
                                 top5_share_pct=50.0, hhi=2000.0))
        # 1 / (2000/10000) = 5
        self.assertAlmostEqual(r["effective_depositor_count"], 5.0)

    def test_hhi_from_input(self):
        r = A().analyze(make_pos(hhi=3500.0))
        self.assertAlmostEqual(r["concentration_hhi"], 3500.0)

    def test_hhi_clamped(self):
        r = A().analyze(make_pos(hhi=20000.0))
        self.assertAlmostEqual(r["concentration_hhi"], HHI_MAX)

    def test_hhi_estimated_when_absent(self):
        # top1 50 → at least 50^2 = 2500
        r = A().analyze(make_pos(top1_share_pct=50.0, top5_share_pct=80.0,
                                 hhi=None))
        self.assertGreaterEqual(r["concentration_hhi"], 2500.0)

    def test_negative_my_position_treated_as_zero(self):
        r = A().analyze(make_pos(my_position_usd=-1000.0))
        self.assertAlmostEqual(r["my_share_of_tvl_pct"], 0.0)


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_well_distributed(self):
        r = A().analyze(make_pos(top1_share_pct=6.0))
        self.assertEqual(r["classification"], "WELL_DISTRIBUTED")

    def test_moderately_concentrated(self):
        r = A().analyze(make_pos(top1_share_pct=20.0))
        self.assertEqual(r["classification"], "MODERATELY_CONCENTRATED")

    def test_highly_concentrated(self):
        r = A().analyze(make_pos(top1_share_pct=35.0))
        self.assertEqual(r["classification"], "HIGHLY_CONCENTRATED")

    def test_whale_dominated(self):
        r = A().analyze(make_pos(top1_share_pct=65.0))
        self.assertEqual(r["classification"], "WHALE_DOMINATED")

    def test_classification_known_value(self):
        for pos in [make_pos(), make_pos(top1_share_pct=35.0),
                    make_pos(top1_share_pct=65.0), make_pos(total_tvl_usd=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "WELL_DISTRIBUTED", "MODERATELY_CONCENTRATED",
                "HIGHLY_CONCENTRATED", "WHALE_DOMINATED", "INSUFFICIENT_DATA",
            })

    def test_boundary_well_to_moderate(self):
        # exactly 15% → MODERATELY (>=15)
        r = A().analyze(make_pos(top1_share_pct=15.0))
        self.assertEqual(r["classification"], "MODERATELY_CONCENTRATED")

    def test_boundary_moderate_to_highly(self):
        # exactly 30% → HIGHLY (>=30)
        r = A().analyze(make_pos(top1_share_pct=30.0))
        self.assertEqual(r["classification"], "HIGHLY_CONCENTRATED")

    def test_boundary_highly_to_whale(self):
        # exactly 50% → WHALE_DOMINATED (>=50)
        r = A().analyze(make_pos(top1_share_pct=50.0))
        self.assertEqual(r["classification"], "WHALE_DOMINATED")


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_deploy_when_well_distributed(self):
        r = A().analyze(make_pos(top1_share_pct=6.0))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_deploy_cautiously_when_moderate(self):
        r = A().analyze(make_pos(top1_share_pct=20.0))
        self.assertEqual(r["recommendation"], "DEPLOY_CAUTIOUSLY")

    def test_deploy_cautiously_when_highly(self):
        r = A().analyze(make_pos(top1_share_pct=35.0))
        self.assertEqual(r["recommendation"], "DEPLOY_CAUTIOUSLY")

    def test_avoid_when_whale_dominated(self):
        r = A().analyze(make_pos(top1_share_pct=65.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_avoid_when_insufficient(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertEqual(r["recommendation"], "AVOID")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_well_distributed_flag(self):
        r = A().analyze(make_pos(top1_share_pct=6.0))
        self.assertIn("WELL_DISTRIBUTED", r["flags"])
        self.assertIn("DIVERSIFIED_BASE", r["flags"])

    def test_well_distributed_absent_when_concentrated(self):
        r = A().analyze(make_pos(top1_share_pct=35.0))
        self.assertNotIn("WELL_DISTRIBUTED", r["flags"])

    def test_whale_dominated_flag(self):
        r = A().analyze(make_pos(top1_share_pct=55.0))
        self.assertIn("WHALE_DOMINATED", r["flags"])

    def test_whale_dominated_absent_when_low(self):
        r = A().analyze(make_pos(top1_share_pct=20.0))
        self.assertNotIn("WHALE_DOMINATED", r["flags"])

    def test_high_top5_flag(self):
        r = A().analyze(make_pos(top1_share_pct=30.0, top5_share_pct=85.0))
        self.assertIn("HIGH_TOP5_CONCENTRATION", r["flags"])

    def test_high_top5_absent_when_low(self):
        r = A().analyze(make_pos(top1_share_pct=6.0, top5_share_pct=22.0))
        self.assertNotIn("HIGH_TOP5_CONCENTRATION", r["flags"])

    def test_few_depositors_flag(self):
        r = A().analyze(make_pos(depositor_count=4))
        self.assertIn("FEW_DEPOSITORS", r["flags"])
        self.assertIn("THIN_DEPOSITOR_BASE", r["flags"])

    def test_few_depositors_absent_when_many(self):
        r = A().analyze(make_pos(depositor_count=4200))
        self.assertNotIn("FEW_DEPOSITORS", r["flags"])

    def test_few_depositors_absent_when_zero(self):
        # zero count is "unknown", not "few"
        r = A().analyze(make_pos(depositor_count=0, top1_share_pct=20.0))
        self.assertNotIn("FEW_DEPOSITORS", r["flags"])

    def test_severe_exit_risk_flag(self):
        # top1 >=40% → severe exit risk
        r = A().analyze(make_pos(top1_share_pct=45.0))
        self.assertIn("SEVERE_EXIT_RISK", r["flags"])

    def test_severe_exit_risk_absent_when_low(self):
        r = A().analyze(make_pos(top1_share_pct=10.0))
        self.assertNotIn("SEVERE_EXIT_RISK", r["flags"])

    def test_insufficient_flag(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertIn("INSUFFICIENT_DATA", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_zero_tvl(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_negative_tvl(self):
        r = A().analyze(make_pos(total_tvl_usd=-100.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_no_signal_at_all(self):
        # tvl present but no top1, no top5, no count
        r = A().analyze(make_pos(top1_share_pct=0.0, top5_share_pct=0.0,
                                 depositor_count=0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_top5_only_is_sufficient(self):
        # top1=0 but top5 present → still analyzable
        r = A().analyze(make_pos(top1_share_pct=0.0, top5_share_pct=40.0,
                                 depositor_count=0))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_count_only_is_sufficient(self):
        r = A().analyze(make_pos(top1_share_pct=0.0, top5_share_pct=0.0,
                                 depositor_count=100))
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertEqual(r["concentration_score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_sentinels_none(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertIsNone(r["effective_depositor_count"])

    def test_insufficient_recommendation(self):
        r = A().analyze(make_pos(total_tvl_usd=0.0))
        self.assertEqual(r["recommendation"], "AVOID")

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_lower_top1_scores_higher(self):
        # higher score = safer = more diversified
        diverse = A().analyze(make_pos(top1_share_pct=5.0, top5_share_pct=20.0))
        concentrated = A().analyze(make_pos(top1_share_pct=60.0,
                                            top5_share_pct=85.0))
        self.assertGreater(diverse["concentration_score"],
                           concentrated["concentration_score"])

    def test_lower_top5_scores_higher(self):
        low5 = A().analyze(make_pos(top1_share_pct=10.0, top5_share_pct=25.0))
        high5 = A().analyze(make_pos(top1_share_pct=10.0, top5_share_pct=90.0))
        self.assertGreater(low5["concentration_score"],
                           high5["concentration_score"])

    def test_more_depositors_scores_higher(self):
        few = A().analyze(make_pos(top1_share_pct=10.0, depositor_count=3))
        many = A().analyze(make_pos(top1_share_pct=10.0, depositor_count=5000))
        self.assertGreater(many["concentration_score"],
                           few["concentration_score"])

    def test_lower_hhi_scores_higher(self):
        low_hhi = A().analyze(make_pos(top1_share_pct=10.0, hhi=1000.0))
        high_hhi = A().analyze(make_pos(top1_share_pct=10.0, hhi=3000.0))
        self.assertGreater(low_hhi["concentration_score"],
                           high_hhi["concentration_score"])

    def test_whale_dominated_scores_low(self):
        r = A().analyze(make_pos(top1_share_pct=70.0, top5_share_pct=95.0,
                                 depositor_count=3))
        self.assertLess(r["concentration_score"], 40.0)

    def test_well_distributed_scores_high(self):
        r = A().analyze(make_pos(top1_share_pct=4.0, top5_share_pct=15.0,
                                 depositor_count=10000, hhi=500.0))
        self.assertGreater(r["concentration_score"], 85.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(top1_share_pct=0.0, top5_share_pct=1.0,
                                 depositor_count=1e9, hhi=0.0))
        self.assertLessEqual(r["concentration_score"], 100.0)
        self.assertGreaterEqual(r["concentration_score"], 0.0)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(vault="Diverse", top1_share_pct=5.0, top5_share_pct=18.0,
                     depositor_count=5000),
            make_pos(vault="Whale", top1_share_pct=65.0, top5_share_pct=90.0,
                     depositor_count=4),
            make_pos(vault="Mid", top1_share_pct=20.0, top5_share_pct=55.0,
                     depositor_count=80),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_concentrated_is_lowest_score(self):
        # most concentrated = lowest (least safe) score
        agg = self.res["aggregate"]
        scores = {p["token"]: p["concentration_score"]
                  for p in self.res["positions"]}
        most = agg["most_concentrated_vault"]
        self.assertEqual(scores[most], min(scores.values()))

    def test_least_concentrated_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["concentration_score"]
                  for p in self.res["positions"]}
        least = agg["least_concentrated_vault"]
        self.assertEqual(scores[least], max(scores.values()))

    def test_most_concentrated_is_whale(self):
        self.assertEqual(self.res["aggregate"]["most_concentrated_vault"],
                         "Whale")

    def test_least_concentrated_is_diverse(self):
        self.assertEqual(self.res["aggregate"]["least_concentrated_vault"],
                         "Diverse")

    def test_whale_dominated_count(self):
        self.assertGreaterEqual(
            self.res["aggregate"]["whale_dominated_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_concentration_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_concentrated_vault"])
        self.assertIsNone(res["aggregate"]["least_concentrated_vault"])

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(total_tvl_usd=0.0), make_pos(total_tvl_usd=-1.0),
        ])
        self.assertIsNone(res["aggregate"]["most_concentrated_vault"])
        self.assertEqual(res["aggregate"]["avg_concentration_score"], 0.0)

    def test_portfolio_json_serializable(self):
        json.dumps(self.res)


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

    def test_ring_buffer_cap(self):
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
                make_pos(vault="whale", top1_share_pct=80.0),
                make_pos(vault="ins", total_tvl_usd=0.0),
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
            "vault": "S",
            "total_tvl_usd": "100000000",
            "top1_share_pct": "20",
            "top5_share_pct": "55",
            "depositor_count": "80",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({
            "vault": "S",
            "total_tvl_usd": 100_000_000.0,
            "top1_share_pct": 20.0,
        })
        self.assertIn("classification", r)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio([make_pos(vault=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(), make_pos(total_tvl_usd=0.0),
            make_pos(top1_share_pct=65.0),
        ])
        json.dumps(res)

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(), make_pos(total_tvl_usd=0.0),
                    make_pos(top1_share_pct=100.0),
                    make_pos(depositor_count=0, hhi=0.0),
                    make_pos(total_tvl_usd=1.0, my_position_usd=1.0)]:
            r = A().analyze(pos)
            for v in r.values():
                if isinstance(v, float):
                    self.assertFalse(math.isinf(v))
                    self.assertFalse(math.isnan(v))

    def test_whale_exit_100pct_no_crash(self):
        r = A().analyze(make_pos(top1_share_pct=100.0, my_position_usd=1000.0))
        self.assertIn("classification", r)
        self.assertAlmostEqual(r["post_whale_exit_my_share_pct"], 0.0)


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


if __name__ == "__main__":
    unittest.main()
