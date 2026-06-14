"""
Tests for MP-1150: DeFiProtocolMinimumProfitablePositionSizeAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_minimum_profitable_position_size_analyzer -v
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

from spa_core.analytics.defi_protocol_minimum_profitable_position_size_analyzer import (
    DeFiProtocolMinimumProfitablePositionSizeAnalyzer,
    _f,
    _clamp,
    _mean,
    _safe_div,
    _build_default_cfg,
    _grade_from_score,
    SIZE_SENTINEL_NEVER,
    DAYS_SENTINEL_NEVER,
    RATIO_SENTINEL_INF,
    DEFAULT_HOLDING_DAYS,
    DEFAULT_OPP_COST_APR,
    HIGH_GAS_DRAG_PCT,
    LOW_GAS_DRAG_PCT,
    EXCESS_HIGH,
    EXCESS_GOOD,
    EXCESS_MARGINAL,
    FAST_BREAKEVEN_FRAC,
    LONG_BREAKEVEN_FRAC,
    LOG_PATH,
    LOG_CAP,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_pos(
    token="USDC",
    position_usd=100_000.0,
    gross_apr_pct=8.0,
    entry_gas_usd=15.0,
    exit_gas_usd=15.0,
    holding_period_days=365.0,
    opportunity_cost_apr_pct=4.0,
    expected_extra_tx_count=0,
    gas_per_extra_tx_usd=0.0,
):
    return {
        "token": token,
        "position_usd": position_usd,
        "gross_apr_pct": gross_apr_pct,
        "entry_gas_usd": entry_gas_usd,
        "exit_gas_usd": exit_gas_usd,
        "holding_period_days": holding_period_days,
        "opportunity_cost_apr_pct": opportunity_cost_apr_pct,
        "expected_extra_tx_count": expected_extra_tx_count,
        "gas_per_extra_tx_usd": gas_per_extra_tx_usd,
    }


def A():
    return DeFiProtocolMinimumProfitablePositionSizeAnalyzer()


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

    def test_constants_sane(self):
        self.assertGreater(SIZE_SENTINEL_NEVER, 0)
        self.assertGreater(DAYS_SENTINEL_NEVER, 0)
        self.assertGreater(RATIO_SENTINEL_INF, 0)
        self.assertEqual(DEFAULT_HOLDING_DAYS, 365.0)
        self.assertEqual(DEFAULT_OPP_COST_APR, 4.0)
        self.assertGreater(EXCESS_HIGH, EXCESS_GOOD)
        self.assertGreaterEqual(EXCESS_GOOD, EXCESS_MARGINAL)
        self.assertGreater(HIGH_GAS_DRAG_PCT, LOW_GAS_DRAG_PCT)
        self.assertLess(FAST_BREAKEVEN_FRAC, LONG_BREAKEVEN_FRAC)


# ── structural / contract tests ───────────────────────────────────────────────

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.r = A().analyze(make_pos())

    def test_has_all_keys(self):
        for k in [
            "token", "position_usd", "roundtrip_gas_usd",
            "gross_yield_over_horizon_usd", "opportunity_cost_over_horizon_usd",
            "net_excess_over_horizon_usd", "gas_as_pct_of_position",
            "min_profitable_position_usd", "entry_breakeven_days",
            "yield_per_gas_ratio", "capital_efficiency_score",
            "classification", "recommendation", "grade", "flags",
        ]:
            self.assertIn(k, self.r)

    def test_score_in_range(self):
        self.assertGreaterEqual(self.r["capital_efficiency_score"], 0.0)
        self.assertLessEqual(self.r["capital_efficiency_score"], 100.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_token_preserved(self):
        self.assertEqual(self.r["token"], "USDC")

    def test_json_serializable(self):
        json.dumps(self.r)

    def test_no_inf_or_nan_in_output(self):
        for v in self.r.values():
            if isinstance(v, float):
                self.assertFalse(math.isinf(v))
                self.assertFalse(math.isnan(v))

    def test_recommendation_known(self):
        self.assertIn(self.r["recommendation"], {"DEPLOY", "DEPLOY_LARGER", "SKIP"})


# ── metrics correctness ───────────────────────────────────────────────────────

class TestMetrics(unittest.TestCase):
    def test_roundtrip_gas_basic(self):
        r = A().analyze(make_pos(entry_gas_usd=10.0, exit_gas_usd=20.0))
        self.assertAlmostEqual(r["roundtrip_gas_usd"], 30.0)

    def test_roundtrip_gas_with_extra_tx(self):
        r = A().analyze(make_pos(
            entry_gas_usd=10.0, exit_gas_usd=10.0,
            expected_extra_tx_count=4, gas_per_extra_tx_usd=5.0,
        ))
        self.assertAlmostEqual(r["roundtrip_gas_usd"], 40.0)

    def test_gross_yield_over_horizon(self):
        # 100k * 8% * 1yr = 8000
        r = A().analyze(make_pos(position_usd=100_000.0, gross_apr_pct=8.0,
                                 holding_period_days=365.0))
        self.assertAlmostEqual(r["gross_yield_over_horizon_usd"], 8000.0)

    def test_gross_yield_half_year(self):
        r = A().analyze(make_pos(position_usd=100_000.0, gross_apr_pct=10.0,
                                 holding_period_days=182.5))
        self.assertAlmostEqual(r["gross_yield_over_horizon_usd"], 5000.0)

    def test_opportunity_cost_over_horizon(self):
        # 100k * 4% * 1yr = 4000
        r = A().analyze(make_pos(position_usd=100_000.0, opportunity_cost_apr_pct=4.0,
                                 holding_period_days=365.0))
        self.assertAlmostEqual(r["opportunity_cost_over_horizon_usd"], 4000.0)

    def test_net_excess(self):
        # gross 8000 - opp 4000 - gas 30 = 3970
        r = A().analyze(make_pos(position_usd=100_000.0, gross_apr_pct=8.0,
                                 opportunity_cost_apr_pct=4.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0))
        self.assertAlmostEqual(r["net_excess_over_horizon_usd"], 3970.0)

    def test_gas_as_pct_of_position(self):
        # gas 30 / position 100000 * 100 = 0.03
        r = A().analyze(make_pos(position_usd=100_000.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0))
        self.assertAlmostEqual(r["gas_as_pct_of_position"], 0.03)

    def test_min_profitable_position(self):
        # gas 30 / ((8-4)/100 * 1) = 30 / 0.04 = 750
        r = A().analyze(make_pos(position_usd=100_000.0, gross_apr_pct=8.0,
                                 opportunity_cost_apr_pct=4.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0,
                                 holding_period_days=365.0))
        self.assertAlmostEqual(r["min_profitable_position_usd"], 750.0)

    def test_min_profitable_none_when_negative_spread(self):
        r = A().analyze(make_pos(gross_apr_pct=3.0, opportunity_cost_apr_pct=4.0))
        self.assertIsNone(r["min_profitable_position_usd"])

    def test_entry_breakeven_days(self):
        # gas 30 / (100000*(8-4)/100/365) = 30 / 10.9589 = ~2.7375
        r = A().analyze(make_pos(position_usd=100_000.0, gross_apr_pct=8.0,
                                 opportunity_cost_apr_pct=4.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0))
        self.assertAlmostEqual(r["entry_breakeven_days"], 2.74, places=2)

    def test_entry_breakeven_none_when_negative_spread(self):
        r = A().analyze(make_pos(gross_apr_pct=3.0, opportunity_cost_apr_pct=4.0))
        self.assertIsNone(r["entry_breakeven_days"])

    def test_yield_per_gas_ratio(self):
        # gross 8000 / gas 30 = 266.67
        r = A().analyze(make_pos(position_usd=100_000.0, gross_apr_pct=8.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0))
        self.assertAlmostEqual(r["yield_per_gas_ratio"], 8000.0 / 30.0, places=2)

    def test_yield_per_gas_none_when_zero_gas(self):
        r = A().analyze(make_pos(entry_gas_usd=0.0, exit_gas_usd=0.0,
                                 expected_extra_tx_count=0))
        self.assertIsNone(r["yield_per_gas_ratio"])

    def test_default_holding_period_applied(self):
        p = make_pos()
        del p["holding_period_days"]
        r = A().analyze(p)
        # 100k * 8% * 1yr = 8000 with default 365 days
        self.assertAlmostEqual(r["gross_yield_over_horizon_usd"], 8000.0)

    def test_zero_holding_period_falls_back_default(self):
        r = A().analyze(make_pos(holding_period_days=0.0))
        self.assertAlmostEqual(r["gross_yield_over_horizon_usd"], 8000.0)

    def test_default_opp_cost_applied(self):
        p = make_pos()
        del p["opportunity_cost_apr_pct"]
        r = A().analyze(p)
        self.assertAlmostEqual(r["opportunity_cost_over_horizon_usd"], 4000.0)

    def test_negative_gas_treated_as_zero(self):
        r = A().analyze(make_pos(entry_gas_usd=-50.0, exit_gas_usd=-50.0))
        self.assertEqual(r["roundtrip_gas_usd"], 0.0)


# ── classification behaviour ──────────────────────────────────────────────────

class TestClassification(unittest.TestCase):
    def test_highly_profitable(self):
        r = A().analyze(make_pos(position_usd=1_000_000.0, gross_apr_pct=12.0,
                                 entry_gas_usd=10.0, exit_gas_usd=10.0))
        self.assertEqual(r["classification"], "HIGHLY_PROFITABLE")

    def test_profitable_band(self):
        # net excess between 1.5x and 5x gas
        r = A().analyze(make_pos(position_usd=2_000.0, gross_apr_pct=8.0,
                                 opportunity_cost_apr_pct=4.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0))
        # gross=160, opp=80, gas=30, net=50 → ratio ~1.67 → PROFITABLE
        self.assertEqual(r["classification"], "PROFITABLE")

    def test_marginal_band(self):
        # net excess positive but < 1.5x gas
        r = A().analyze(make_pos(position_usd=1_100.0, gross_apr_pct=8.0,
                                 opportunity_cost_apr_pct=4.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0))
        # gross=88, opp=44, gas=30, net=14 → ratio ~0.47 → MARGINAL
        self.assertEqual(r["classification"], "MARGINAL")

    def test_dust_below_min(self):
        # positive spread, but position below min profitable → DUST
        r = A().analyze(make_pos(position_usd=500.0, gross_apr_pct=8.0,
                                 opportunity_cost_apr_pct=4.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0))
        # min profitable = 750, position 500 < 750, net excess negative → DUST
        self.assertEqual(r["classification"], "DUST")

    def test_unprofitable_negative_spread(self):
        r = A().analyze(make_pos(gross_apr_pct=3.0, opportunity_cost_apr_pct=4.0))
        self.assertEqual(r["classification"], "UNPROFITABLE")

    def test_classification_known_value(self):
        for pos in [make_pos(), make_pos(gross_apr_pct=3.0), make_pos(position_usd=0.0)]:
            r = A().analyze(pos)
            self.assertIn(r["classification"], {
                "HIGHLY_PROFITABLE", "PROFITABLE", "MARGINAL", "DUST",
                "UNPROFITABLE", "INSUFFICIENT_DATA",
            })


# ── recommendation behaviour ──────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def test_deploy_when_profitable(self):
        r = A().analyze(make_pos(position_usd=1_000_000.0, gross_apr_pct=12.0))
        self.assertEqual(r["recommendation"], "DEPLOY")

    def test_deploy_larger_when_dust(self):
        r = A().analyze(make_pos(position_usd=500.0, gross_apr_pct=8.0,
                                 opportunity_cost_apr_pct=4.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0))
        self.assertEqual(r["recommendation"], "DEPLOY_LARGER")

    def test_skip_when_negative_spread(self):
        r = A().analyze(make_pos(gross_apr_pct=3.0, opportunity_cost_apr_pct=4.0))
        self.assertEqual(r["recommendation"], "SKIP")

    def test_skip_when_insufficient(self):
        r = A().analyze(make_pos(position_usd=0.0))
        self.assertEqual(r["recommendation"], "SKIP")


# ── flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_clears_hurdle_flag(self):
        r = A().analyze(make_pos(position_usd=1_000_000.0, gross_apr_pct=12.0))
        self.assertIn("CLEARS_HURDLE", r["flags"])

    def test_clears_hurdle_absent_when_dust(self):
        r = A().analyze(make_pos(position_usd=500.0, gross_apr_pct=8.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0))
        self.assertNotIn("CLEARS_HURDLE", r["flags"])

    def test_below_min_size_flag(self):
        r = A().analyze(make_pos(position_usd=500.0, gross_apr_pct=8.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0))
        self.assertIn("BELOW_MIN_SIZE", r["flags"])

    def test_below_min_size_absent_when_large(self):
        r = A().analyze(make_pos(position_usd=1_000_000.0, gross_apr_pct=12.0))
        self.assertNotIn("BELOW_MIN_SIZE", r["flags"])

    def test_dust_position_flag(self):
        r = A().analyze(make_pos(position_usd=500.0, gross_apr_pct=8.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0))
        self.assertIn("DUST_POSITION", r["flags"])

    def test_high_gas_drag_flag(self):
        # gas / position >= 2%
        r = A().analyze(make_pos(position_usd=1_000.0, gross_apr_pct=8.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0))
        # 30/1000*100 = 3% >= 2 → flag
        self.assertIn("HIGH_GAS_DRAG", r["flags"])

    def test_high_gas_drag_absent_when_low(self):
        r = A().analyze(make_pos(position_usd=1_000_000.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0))
        self.assertNotIn("HIGH_GAS_DRAG", r["flags"])

    def test_negative_spread_flag(self):
        r = A().analyze(make_pos(gross_apr_pct=3.0, opportunity_cost_apr_pct=4.0))
        self.assertIn("NEGATIVE_SPREAD", r["flags"])

    def test_negative_spread_absent_when_positive(self):
        r = A().analyze(make_pos(gross_apr_pct=8.0, opportunity_cost_apr_pct=4.0))
        self.assertNotIn("NEGATIVE_SPREAD", r["flags"])

    def test_long_breakeven_flag(self):
        # breakeven days > horizon: tiny position, long gas, short horizon
        r = A().analyze(make_pos(position_usd=600.0, gross_apr_pct=8.0,
                                 opportunity_cost_apr_pct=4.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0,
                                 holding_period_days=30.0))
        self.assertIn("LONG_BREAKEVEN", r["flags"])

    def test_fast_breakeven_flag(self):
        # breakeven well within horizon
        r = A().analyze(make_pos(position_usd=1_000_000.0, gross_apr_pct=12.0,
                                 entry_gas_usd=10.0, exit_gas_usd=10.0,
                                 holding_period_days=365.0))
        self.assertIn("FAST_BREAKEVEN", r["flags"])

    def test_unprofitable_at_horizon_flag(self):
        r = A().analyze(make_pos(position_usd=500.0, gross_apr_pct=8.0,
                                 entry_gas_usd=15.0, exit_gas_usd=15.0))
        self.assertIn("UNPROFITABLE_AT_HORIZON", r["flags"])

    def test_unprofitable_at_horizon_absent_when_profitable(self):
        r = A().analyze(make_pos(position_usd=1_000_000.0, gross_apr_pct=12.0))
        self.assertNotIn("UNPROFITABLE_AT_HORIZON", r["flags"])


# ── insufficient data ─────────────────────────────────────────────────────────

class TestInsufficientData(unittest.TestCase):
    def test_zero_position(self):
        r = A().analyze(make_pos(position_usd=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertIn("INSUFFICIENT_DATA", r["flags"])

    def test_negative_position(self):
        r = A().analyze(make_pos(position_usd=-100.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_zero_gross_apr(self):
        r = A().analyze(make_pos(gross_apr_pct=0.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_negative_gross_apr(self):
        r = A().analyze(make_pos(gross_apr_pct=-5.0))
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_insufficient_score_zero(self):
        r = A().analyze(make_pos(position_usd=0.0))
        self.assertEqual(r["capital_efficiency_score"], 0.0)
        self.assertEqual(r["grade"], "F")

    def test_insufficient_sentinels_none(self):
        r = A().analyze(make_pos(position_usd=0.0))
        self.assertIsNone(r["min_profitable_position_usd"])
        self.assertIsNone(r["entry_breakeven_days"])
        self.assertIsNone(r["gas_as_pct_of_position"])
        self.assertIsNone(r["yield_per_gas_ratio"])

    def test_empty_dict(self):
        r = A().analyze({})
        self.assertEqual(r["classification"], "INSUFFICIENT_DATA")
        self.assertEqual(r["token"], "UNKNOWN")


# ── scoring monotonicity ──────────────────────────────────────────────────────

class TestScoring(unittest.TestCase):
    def test_bigger_position_scores_higher(self):
        small = A().analyze(make_pos(position_usd=2_000.0, gross_apr_pct=8.0,
                                     entry_gas_usd=15.0, exit_gas_usd=15.0))
        big = A().analyze(make_pos(position_usd=1_000_000.0, gross_apr_pct=8.0,
                                   entry_gas_usd=15.0, exit_gas_usd=15.0))
        self.assertGreater(big["capital_efficiency_score"],
                           small["capital_efficiency_score"])

    def test_higher_apr_scores_higher(self):
        low = A().analyze(make_pos(gross_apr_pct=5.0))
        high = A().analyze(make_pos(gross_apr_pct=15.0))
        self.assertGreater(high["capital_efficiency_score"],
                           low["capital_efficiency_score"])

    def test_higher_gas_scores_lower(self):
        cheap = A().analyze(make_pos(position_usd=10_000.0, entry_gas_usd=5.0,
                                     exit_gas_usd=5.0))
        pricey = A().analyze(make_pos(position_usd=10_000.0, entry_gas_usd=100.0,
                                      exit_gas_usd=100.0))
        self.assertGreater(cheap["capital_efficiency_score"],
                           pricey["capital_efficiency_score"])

    def test_negative_spread_scores_low(self):
        r = A().analyze(make_pos(gross_apr_pct=3.0, opportunity_cost_apr_pct=4.0))
        self.assertLess(r["capital_efficiency_score"], 40.0)

    def test_score_never_exceeds_bounds_extreme(self):
        r = A().analyze(make_pos(position_usd=1e12, gross_apr_pct=100.0,
                                 entry_gas_usd=0.0, exit_gas_usd=0.0,
                                 opportunity_cost_apr_pct=0.0))
        self.assertLessEqual(r["capital_efficiency_score"], 100.0)
        self.assertGreaterEqual(r["capital_efficiency_score"], 0.0)

    def test_zero_gas_scores_well(self):
        r = A().analyze(make_pos(position_usd=100_000.0, gross_apr_pct=12.0,
                                 entry_gas_usd=0.0, exit_gas_usd=0.0))
        self.assertGreater(r["capital_efficiency_score"], 70.0)


# ── portfolio aggregate ───────────────────────────────────────────────────────

class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.res = A().analyze_portfolio([
            make_pos(token="Good", position_usd=1_000_000.0, gross_apr_pct=12.0),
            make_pos(token="Dust", position_usd=500.0, gross_apr_pct=8.0,
                     entry_gas_usd=15.0, exit_gas_usd=15.0),
            make_pos(token="Mid", position_usd=5_000.0, gross_apr_pct=8.0,
                     entry_gas_usd=15.0, exit_gas_usd=15.0),
        ])

    def test_returns_positions_and_aggregate(self):
        self.assertIn("positions", self.res)
        self.assertIn("aggregate", self.res)
        self.assertEqual(len(self.res["positions"]), 3)

    def test_most_efficient_is_highest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["capital_efficiency_score"]
                  for p in self.res["positions"]}
        most = agg["most_efficient_position"]
        self.assertEqual(scores[most], max(scores.values()))

    def test_least_efficient_is_lowest_score(self):
        agg = self.res["aggregate"]
        scores = {p["token"]: p["capital_efficiency_score"]
                  for p in self.res["positions"]}
        least = agg["least_efficient_position"]
        self.assertEqual(scores[least], min(scores.values()))

    def test_most_efficient_is_good(self):
        self.assertEqual(self.res["aggregate"]["most_efficient_position"], "Good")

    def test_dust_count(self):
        self.assertGreaterEqual(self.res["aggregate"]["dust_count"], 1)

    def test_avg_score_in_range(self):
        avg = self.res["aggregate"]["avg_capital_efficiency_score"]
        self.assertGreaterEqual(avg, 0.0)
        self.assertLessEqual(avg, 100.0)

    def test_position_count(self):
        self.assertEqual(self.res["aggregate"]["position_count"], 3)

    def test_empty_portfolio(self):
        res = A().analyze_portfolio([])
        self.assertEqual(res["positions"], [])
        self.assertIsNone(res["aggregate"]["most_efficient_position"])
        self.assertIsNone(res["aggregate"]["least_efficient_position"])

    def test_all_insufficient_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(position_usd=0.0), make_pos(gross_apr_pct=0.0),
        ])
        self.assertIsNone(res["aggregate"]["most_efficient_position"])
        self.assertEqual(res["aggregate"]["avg_capital_efficiency_score"], 0.0)

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
                A().analyze([make_pos()][0], cfg=cfg, write_log=True)
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

    def test_log_entry_has_snapshots(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([make_pos(), make_pos(token="B")],
                                  cfg={"log_path": path}, write_log=True)
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(data[0]["position_count"], 2)
            self.assertEqual(len(data[0]["snapshots"]), 2)

    def test_log_json_no_inf_nan(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            A().analyze_portfolio([
                make_pos(),
                make_pos(token="ne", entry_gas_usd=0.0, exit_gas_usd=0.0),
                make_pos(token="ns", gross_apr_pct=3.0),
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
            "position_usd": "100000",
            "gross_apr_pct": "8",
            "entry_gas_usd": "15",
            "exit_gas_usd": "15",
        })
        self.assertNotEqual(r["classification"], "INSUFFICIENT_DATA")

    def test_missing_optional_fields(self):
        r = A().analyze({
            "token": "S",
            "position_usd": 100_000.0,
            "gross_apr_pct": 8.0,
        })
        self.assertIn("classification", r)

    def test_negative_extra_tx_treated_as_zero(self):
        r = A().analyze(make_pos(entry_gas_usd=10.0, exit_gas_usd=10.0,
                                 expected_extra_tx_count=-5,
                                 gas_per_extra_tx_usd=5.0))
        self.assertAlmostEqual(r["roundtrip_gas_usd"], 20.0)

    def test_large_portfolio_performance(self):
        res = A().analyze_portfolio([make_pos(token=f"T{i}") for i in range(200)])
        self.assertEqual(len(res["positions"]), 200)

    def test_output_fully_json_serializable_portfolio(self):
        res = A().analyze_portfolio([
            make_pos(), make_pos(position_usd=0.0), make_pos(gross_apr_pct=3.0),
        ])
        json.dumps(res)

    def test_vault_field_alias_not_required(self):
        # token preferred; should still work fine
        r = A().analyze(make_pos(token="MyVault"))
        self.assertEqual(r["token"], "MyVault")

    def test_no_inf_nan_across_many(self):
        for pos in [make_pos(), make_pos(gross_apr_pct=3.0),
                    make_pos(entry_gas_usd=0.0, exit_gas_usd=0.0),
                    make_pos(position_usd=1.0)]:
            r = A().analyze(pos)
            for v in r.values():
                if isinstance(v, float):
                    self.assertFalse(math.isinf(v))
                    self.assertFalse(math.isnan(v))


if __name__ == "__main__":
    unittest.main()
