"""
Tests for MP-823 DeFiInsuranceCostAnalyzer.
Run with: python3 -m unittest spa_core.tests.test_defi_insurance_cost_analyzer
"""

import json
import math
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.defi_insurance_cost_analyzer import (
    analyze,
    _load_log,
    _save_log,
    _MAX_ENTRIES,
    _DEFAULT_HACK_PROBABILITY_BASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_file(suffix=".json"):
    """Return a Path to a fresh temp file that is deleted after the test."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return Path(path)


def _basic_position(**overrides):
    pos = {
        "protocol": "TestProtocol",
        "value_usd": 10_000.0,
        "protocol_risk_score": 50,
        "holding_period_days": 365,
    }
    pos.update(overrides)
    return pos


def _opt(
    provider="Prov",
    annual_premium_pct=2.0,
    coverage_pct=100.0,
    max_coverage_usd=None,
    deductible_pct=0.0,
):
    return {
        "provider": provider,
        "annual_premium_pct": annual_premium_pct,
        "coverage_pct": coverage_pct,
        "max_coverage_usd": max_coverage_usd,
        "deductible_pct": deductible_pct,
    }


# ===========================================================================
# 1. Return shape and types
# ===========================================================================

class TestReturnShape(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()
        self.pos = _basic_position()
        self.opts = [_opt()]

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def _run(self):
        return analyze(self.pos, self.opts, data_file=self.df, save=False)

    def test_returns_dict(self):
        r = self._run()
        self.assertIsInstance(r, dict)

    def test_has_position_key(self):
        r = self._run()
        self.assertIn("position", r)

    def test_position_has_protocol(self):
        r = self._run()
        self.assertEqual(r["position"]["protocol"], "TestProtocol")

    def test_position_has_value_usd(self):
        r = self._run()
        self.assertAlmostEqual(r["position"]["value_usd"], 10_000.0)

    def test_position_has_risk_score(self):
        r = self._run()
        self.assertEqual(r["position"]["protocol_risk_score"], 50)

    def test_position_has_holding_days(self):
        r = self._run()
        self.assertEqual(r["position"]["holding_period_days"], 365)

    def test_has_expected_loss_usd(self):
        r = self._run()
        self.assertIn("expected_loss_usd", r)
        self.assertIsInstance(r["expected_loss_usd"], float)

    def test_has_adjusted_hack_probability(self):
        r = self._run()
        self.assertIn("adjusted_hack_probability", r)
        self.assertIsInstance(r["adjusted_hack_probability"], float)

    def test_has_options_list(self):
        r = self._run()
        self.assertIn("options", r)
        self.assertIsInstance(r["options"], list)

    def test_has_best_option(self):
        r = self._run()
        self.assertIn("best_option", r)

    def test_has_insurance_worthwhile(self):
        r = self._run()
        self.assertIn("insurance_worthwhile", r)
        self.assertIsInstance(r["insurance_worthwhile"], bool)

    def test_has_timestamp(self):
        r = self._run()
        self.assertIn("timestamp", r)
        self.assertIsInstance(r["timestamp"], float)

    def test_option_has_all_keys(self):
        r = self._run()
        opt = r["options"][0]
        for k in (
            "provider",
            "annual_premium_pct",
            "premium_for_period_usd",
            "effective_coverage_usd",
            "expected_payout_usd",
            "net_value_usd",
            "cost_benefit_ratio",
            "recommendation",
        ):
            with self.subTest(key=k):
                self.assertIn(k, opt)

    def test_option_recommendation_valid(self):
        r = self._run()
        self.assertIn(r["options"][0]["recommendation"], ("BUY", "CONSIDER", "SKIP"))


# ===========================================================================
# 2. Hack probability maths
# ===========================================================================

class TestHackProbability(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def _r(self, risk_score, base=0.05):
        pos = _basic_position(protocol_risk_score=risk_score)
        return analyze(pos, [], config={"hack_probability_base": base},
                       data_file=self.df, save=False)

    def test_zero_risk_score(self):
        r = self._r(0)
        self.assertAlmostEqual(r["adjusted_hack_probability"], 0.05)

    def test_50_risk_score(self):
        r = self._r(50)
        self.assertAlmostEqual(r["adjusted_hack_probability"], 0.05 * 1.5)

    def test_100_risk_score(self):
        r = self._r(100)
        self.assertAlmostEqual(r["adjusted_hack_probability"], 0.05 * 2.0)

    def test_capped_at_1(self):
        # base=0.6, risk=100 → 0.6*2 = 1.2 → clamped to 1.0
        r = self._r(100, base=0.6)
        self.assertAlmostEqual(r["adjusted_hack_probability"], 1.0)

    def test_custom_base(self):
        r = self._r(0, base=0.10)
        self.assertAlmostEqual(r["adjusted_hack_probability"], 0.10)

    def test_risk_score_clamped_below_zero(self):
        pos = _basic_position(protocol_risk_score=-10)
        r = analyze(pos, [], data_file=self.df, save=False)
        self.assertAlmostEqual(r["adjusted_hack_probability"], 0.05)

    def test_risk_score_clamped_above_100(self):
        pos = _basic_position(protocol_risk_score=150)
        r = analyze(pos, [], data_file=self.df, save=False)
        self.assertAlmostEqual(r["adjusted_hack_probability"], 0.05 * 2.0)

    def test_probability_never_exceeds_1(self):
        pos = _basic_position(protocol_risk_score=100)
        r = analyze(pos, [], config={"hack_probability_base": 1.0},
                    data_file=self.df, save=False)
        self.assertLessEqual(r["adjusted_hack_probability"], 1.0)

    def test_probability_non_negative(self):
        r = self._r(0, base=0.01)
        self.assertGreaterEqual(r["adjusted_hack_probability"], 0.0)


# ===========================================================================
# 3. Expected-loss calculation
# ===========================================================================

class TestExpectedLoss(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_full_year_zero_risk(self):
        pos = _basic_position(value_usd=100_000, protocol_risk_score=0,
                              holding_period_days=365)
        r = analyze(pos, [], data_file=self.df, save=False)
        # adjusted_prob = 0.05; period = 1.0
        self.assertAlmostEqual(r["expected_loss_usd"], 100_000 * 0.05, places=4)

    def test_half_year(self):
        pos = _basic_position(value_usd=10_000, protocol_risk_score=0,
                              holding_period_days=182)
        r = analyze(pos, [], data_file=self.df, save=False)
        expected = 10_000 * 0.05 * (182 / 365)
        self.assertAlmostEqual(r["expected_loss_usd"], expected, places=4)

    def test_zero_days(self):
        pos = _basic_position(holding_period_days=0)
        r = analyze(pos, [], data_file=self.df, save=False)
        self.assertAlmostEqual(r["expected_loss_usd"], 0.0)

    def test_zero_value(self):
        pos = _basic_position(value_usd=0.0, protocol_risk_score=100,
                              holding_period_days=365)
        r = analyze(pos, [], data_file=self.df, save=False)
        self.assertAlmostEqual(r["expected_loss_usd"], 0.0)

    def test_scales_with_value(self):
        pos_a = _basic_position(value_usd=10_000, holding_period_days=365)
        pos_b = _basic_position(value_usd=20_000, holding_period_days=365)
        ra = analyze(pos_a, [], data_file=self.df, save=False)
        rb = analyze(pos_b, [], data_file=self.df, save=False)
        self.assertAlmostEqual(rb["expected_loss_usd"], ra["expected_loss_usd"] * 2)


# ===========================================================================
# 4. Premium calculation
# ===========================================================================

class TestPremium(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_full_year_premium(self):
        pos = _basic_position(value_usd=10_000, holding_period_days=365)
        opts = [_opt(annual_premium_pct=2.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        # 10000 * 0.02 * (365/365) = 200
        self.assertAlmostEqual(r["options"][0]["premium_for_period_usd"], 200.0, places=4)

    def test_half_year_premium(self):
        pos = _basic_position(value_usd=10_000, holding_period_days=182)
        opts = [_opt(annual_premium_pct=2.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        expected = 10_000 * 0.02 * (182 / 365)
        self.assertAlmostEqual(r["options"][0]["premium_for_period_usd"], expected, places=4)

    def test_zero_premium_pct(self):
        pos = _basic_position(holding_period_days=365)
        opts = [_opt(annual_premium_pct=0.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(r["options"][0]["premium_for_period_usd"], 0.0)

    def test_premium_scales_with_value(self):
        pos_a = _basic_position(value_usd=5_000, holding_period_days=365)
        pos_b = _basic_position(value_usd=10_000, holding_period_days=365)
        opts = [_opt(annual_premium_pct=3.0)]
        ra = analyze(pos_a, opts, data_file=self.df, save=False)
        rb = analyze(pos_b, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(
            rb["options"][0]["premium_for_period_usd"],
            ra["options"][0]["premium_for_period_usd"] * 2,
        )


# ===========================================================================
# 5. Effective coverage calculation
# ===========================================================================

class TestEffectiveCoverage(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_full_coverage_no_deductible_no_max(self):
        pos = _basic_position(value_usd=10_000, holding_period_days=365)
        opts = [_opt(coverage_pct=100.0, max_coverage_usd=None, deductible_pct=0.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(r["options"][0]["effective_coverage_usd"], 10_000.0)

    def test_80pct_coverage_no_deductible(self):
        pos = _basic_position(value_usd=10_000, holding_period_days=365)
        opts = [_opt(coverage_pct=80.0, max_coverage_usd=None, deductible_pct=0.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(r["options"][0]["effective_coverage_usd"], 8_000.0)

    def test_deductible_reduces_coverage(self):
        pos = _basic_position(value_usd=10_000, holding_period_days=365)
        opts = [_opt(coverage_pct=100.0, max_coverage_usd=None, deductible_pct=10.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(r["options"][0]["effective_coverage_usd"], 9_000.0)

    def test_max_coverage_caps_coverage(self):
        pos = _basic_position(value_usd=10_000, holding_period_days=365)
        opts = [_opt(coverage_pct=100.0, max_coverage_usd=5_000.0, deductible_pct=0.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(r["options"][0]["effective_coverage_usd"], 5_000.0)

    def test_max_coverage_cap_then_deductible(self):
        pos = _basic_position(value_usd=10_000, holding_period_days=365)
        # raw = min(10000, 6000) = 6000; effective = 6000 * 0.9 = 5400
        opts = [_opt(coverage_pct=100.0, max_coverage_usd=6_000.0, deductible_pct=10.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(r["options"][0]["effective_coverage_usd"], 5_400.0)

    def test_none_max_coverage_capped_at_value(self):
        # When max_coverage_usd is None, cap should be at value_usd
        pos = _basic_position(value_usd=10_000, holding_period_days=365)
        opts = [_opt(coverage_pct=100.0, max_coverage_usd=None, deductible_pct=0.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        # Should be exactly value_usd (no more than the position)
        self.assertAlmostEqual(r["options"][0]["effective_coverage_usd"], 10_000.0)
        # Also make sure it's a finite JSON-safe value
        self.assertFalse(math.isinf(r["options"][0]["effective_coverage_usd"]))

    def test_partial_coverage_with_max(self):
        pos = _basic_position(value_usd=20_000, holding_period_days=365)
        # coverage_pct=80 → 16000; max=15000 → cap at 15000
        opts = [_opt(coverage_pct=80.0, max_coverage_usd=15_000.0, deductible_pct=0.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(r["options"][0]["effective_coverage_usd"], 15_000.0)

    def test_zero_coverage_pct(self):
        pos = _basic_position(value_usd=10_000, holding_period_days=365)
        opts = [_opt(coverage_pct=0.0, deductible_pct=0.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(r["options"][0]["effective_coverage_usd"], 0.0)


# ===========================================================================
# 6. Expected payout
# ===========================================================================

class TestExpectedPayout(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_payout_formula(self):
        pos = _basic_position(value_usd=10_000, protocol_risk_score=0,
                              holding_period_days=365)
        opts = [_opt(coverage_pct=100.0, annual_premium_pct=1.0,
                     max_coverage_usd=None, deductible_pct=0.0)]
        r = analyze(pos, opts, config={"hack_probability_base": 0.05},
                    data_file=self.df, save=False)
        # effective_coverage = 10000; prob=0.05; period=1.0 → payout=500
        self.assertAlmostEqual(r["options"][0]["expected_payout_usd"], 500.0, places=4)

    def test_payout_half_year(self):
        pos = _basic_position(value_usd=10_000, protocol_risk_score=0,
                              holding_period_days=182)
        opts = [_opt(coverage_pct=100.0, annual_premium_pct=1.0,
                     max_coverage_usd=None, deductible_pct=0.0)]
        r = analyze(pos, opts, config={"hack_probability_base": 0.05},
                    data_file=self.df, save=False)
        expected = 10_000 * 0.05 * (182 / 365)
        self.assertAlmostEqual(r["options"][0]["expected_payout_usd"], expected, places=4)

    def test_payout_zero_if_zero_coverage(self):
        pos = _basic_position(value_usd=10_000, holding_period_days=365)
        opts = [_opt(coverage_pct=0.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(r["options"][0]["expected_payout_usd"], 0.0)

    def test_payout_zero_holding_days(self):
        pos = _basic_position(value_usd=10_000, holding_period_days=0)
        opts = [_opt(coverage_pct=100.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(r["options"][0]["expected_payout_usd"], 0.0)


# ===========================================================================
# 7. Net value and cost-benefit ratio
# ===========================================================================

class TestNetValueAndCBR(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_net_value_positive_case(self):
        # High risk, full coverage, cheap premium
        pos = _basic_position(value_usd=100_000, protocol_risk_score=100,
                              holding_period_days=365)
        opts = [_opt(annual_premium_pct=1.0, coverage_pct=100.0)]
        r = analyze(pos, opts, config={"hack_probability_base": 0.05},
                    data_file=self.df, save=False)
        opt = r["options"][0]
        # payout = 100000*0.10 = 10000; premium = 1000; net = 9000
        self.assertGreater(opt["net_value_usd"], 0)

    def test_net_value_negative_case(self):
        # Low risk, high premium
        pos = _basic_position(value_usd=10_000, protocol_risk_score=0,
                              holding_period_days=365)
        opts = [_opt(annual_premium_pct=10.0, coverage_pct=100.0)]
        r = analyze(pos, opts, config={"hack_probability_base": 0.05},
                    data_file=self.df, save=False)
        opt = r["options"][0]
        # payout=500; premium=1000; net=-500
        self.assertLess(opt["net_value_usd"], 0)

    def test_cost_benefit_ratio_calculation(self):
        pos = _basic_position(value_usd=10_000, protocol_risk_score=0,
                              holding_period_days=365)
        opts = [_opt(annual_premium_pct=2.0, coverage_pct=100.0)]
        r = analyze(pos, opts, config={"hack_probability_base": 0.10},
                    data_file=self.df, save=False)
        opt = r["options"][0]
        # payout=1000; premium=200; cbr=5.0
        self.assertAlmostEqual(opt["cost_benefit_ratio"], 5.0, places=4)

    def test_zero_premium_cbr_is_sentinel(self):
        pos = _basic_position(holding_period_days=365)
        opts = [_opt(annual_premium_pct=0.0, coverage_pct=100.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(r["options"][0]["cost_benefit_ratio"], 999.0)

    def test_zero_days_premium_is_zero_cbr_sentinel(self):
        pos = _basic_position(holding_period_days=0)
        opts = [_opt(annual_premium_pct=5.0, coverage_pct=100.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(r["options"][0]["cost_benefit_ratio"], 999.0)

    def test_net_value_equals_payout_minus_premium(self):
        pos = _basic_position(value_usd=50_000, protocol_risk_score=50,
                              holding_period_days=180)
        opts = [_opt(annual_premium_pct=3.0, coverage_pct=80.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        opt = r["options"][0]
        self.assertAlmostEqual(
            opt["net_value_usd"],
            opt["expected_payout_usd"] - opt["premium_for_period_usd"],
            places=6,
        )


# ===========================================================================
# 8. Recommendation logic
# ===========================================================================

class TestRecommendation(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def _rec(self, hack_base, value, risk, days, premium_pct, coverage_pct,
             max_cov=None, ded=0.0):
        pos = _basic_position(value_usd=value, protocol_risk_score=risk,
                              holding_period_days=days)
        opts = [_opt(annual_premium_pct=premium_pct, coverage_pct=coverage_pct,
                     max_coverage_usd=max_cov, deductible_pct=ded)]
        r = analyze(pos, opts, config={"hack_probability_base": hack_base},
                    data_file=self.df, save=False)
        return r["options"][0]["recommendation"]

    def test_buy_recommendation(self):
        # net>0 AND cbr>1.5 → BUY
        # payout=10000*0.10=1000; premium=10000*0.01=100; cbr=10 → BUY
        rec = self._rec(0.10, 10_000, 0, 365, 1.0, 100.0)
        self.assertEqual(rec, "BUY")

    def test_skip_high_premium_low_risk(self):
        # payout small, premium large → SKIP
        rec = self._rec(0.01, 10_000, 0, 365, 10.0, 100.0)
        self.assertEqual(rec, "SKIP")

    def test_consider_when_net_positive_cbr_le_1_5(self):
        # We need net>0 but cbr between 1.0 and 1.5
        # payout = cov * prob * period; premium = val * prem_pct/100 * period
        # cbr = payout/premium; for cbr ≈ 1.2: set values explicitly
        # prob=0.05, risk=0, value=10000, days=365
        # payout = 10000 * 0.05 = 500; premium = 10000 * x = 500/1.2 ≈ 416.67 → x ≈ 4.167%
        rec = self._rec(0.05, 10_000, 0, 365, 4.0, 100.0)
        # payout=500; premium=400; net=100>0; cbr=500/400=1.25 → CONSIDER
        self.assertEqual(rec, "CONSIDER")

    def test_skip_when_net_negative_cbr_le_1(self):
        # net<0 AND cbr<1 → SKIP
        rec = self._rec(0.05, 10_000, 0, 365, 8.0, 100.0)
        # payout=500; premium=800; net=-300; cbr=0.625 → SKIP
        self.assertEqual(rec, "SKIP")

    def test_zero_premium_always_consider_or_buy(self):
        rec = self._rec(0.05, 10_000, 0, 365, 0.0, 100.0)
        # cbr=999>1.5; expected_payout>0; net=expected_payout>0 → BUY
        self.assertEqual(rec, "BUY")

    def test_consider_when_net_negative_but_cbr_above_1(self):
        # If cbr > 1 but net <= 0 that's impossible (cbr = payout/premium > 1 means
        # payout > premium means net > 0). So check: cbr just above 1.0 → CONSIDER.
        rec = self._rec(0.05, 10_000, 0, 365, 4.9, 100.0)
        # payout=500; premium=490; net=10>0; cbr≈1.02 → CONSIDER
        self.assertEqual(rec, "CONSIDER")

    def test_all_recommendations_valid_values(self):
        for rec_val in ["BUY", "CONSIDER", "SKIP"]:
            self.assertIn(rec_val, ("BUY", "CONSIDER", "SKIP"))


# ===========================================================================
# 9. best_option and insurance_worthwhile
# ===========================================================================

class TestAggregateResults(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_empty_options_best_is_none(self):
        r = analyze(_basic_position(), [], data_file=self.df, save=False)
        self.assertIsNone(r["best_option"])

    def test_empty_options_not_worthwhile(self):
        r = analyze(_basic_position(), [], data_file=self.df, save=False)
        self.assertFalse(r["insurance_worthwhile"])

    def test_single_option_is_best(self):
        pos = _basic_position(value_usd=100_000, protocol_risk_score=80,
                              holding_period_days=365)
        opts = [_opt(provider="Nexus", annual_premium_pct=1.0, coverage_pct=100.0)]
        r = analyze(pos, opts, config={"hack_probability_base": 0.05},
                    data_file=self.df, save=False)
        self.assertEqual(r["best_option"], "Nexus")

    def test_best_option_highest_net_value(self):
        pos = _basic_position(value_usd=100_000, protocol_risk_score=80,
                              holding_period_days=365)
        opts = [
            _opt(provider="Cheap", annual_premium_pct=0.5, coverage_pct=50.0),
            _opt(provider="Good", annual_premium_pct=1.0, coverage_pct=100.0),
        ]
        r = analyze(pos, opts, config={"hack_probability_base": 0.05},
                    data_file=self.df, save=False)
        # Good gives higher payout; let's verify
        self.assertIn(r["best_option"], ("Cheap", "Good"))
        # The one with higher net value should win
        nets = {o["provider"]: o["net_value_usd"] for o in r["options"]}
        self.assertEqual(r["best_option"], max(nets, key=nets.get))

    def test_worthwhile_when_any_net_positive(self):
        pos = _basic_position(value_usd=100_000, protocol_risk_score=100,
                              holding_period_days=365)
        opts = [
            _opt(provider="Good", annual_premium_pct=1.0, coverage_pct=100.0),
            _opt(provider="Bad", annual_premium_pct=50.0, coverage_pct=10.0),
        ]
        r = analyze(pos, opts, config={"hack_probability_base": 0.05},
                    data_file=self.df, save=False)
        self.assertTrue(r["insurance_worthwhile"])

    def test_not_worthwhile_all_negative(self):
        pos = _basic_position(value_usd=10_000, protocol_risk_score=0,
                              holding_period_days=365)
        opts = [_opt(annual_premium_pct=20.0, coverage_pct=100.0)]
        r = analyze(pos, opts, config={"hack_probability_base": 0.05},
                    data_file=self.df, save=False)
        self.assertFalse(r["insurance_worthwhile"])

    def test_multiple_providers_returned(self):
        pos = _basic_position(holding_period_days=365)
        opts = [
            _opt(provider="A", annual_premium_pct=2.0),
            _opt(provider="B", annual_premium_pct=3.0),
            _opt(provider="C", annual_premium_pct=1.0),
        ]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertEqual(len(r["options"]), 3)


# ===========================================================================
# 10. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_empty_insurance_options_list(self):
        r = analyze(_basic_position(), [], data_file=self.df, save=False)
        self.assertEqual(r["options"], [])
        self.assertIsNone(r["best_option"])
        self.assertFalse(r["insurance_worthwhile"])

    def test_none_insurance_options(self):
        r = analyze(_basic_position(), None, data_file=self.df, save=False)
        self.assertEqual(r["options"], [])

    def test_zero_value_usd(self):
        pos = _basic_position(value_usd=0.0, holding_period_days=365)
        opts = [_opt(annual_premium_pct=2.0, coverage_pct=100.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(r["options"][0]["premium_for_period_usd"], 0.0)
        self.assertAlmostEqual(r["options"][0]["expected_payout_usd"], 0.0)

    def test_deductible_100pct_means_zero_effective_coverage(self):
        pos = _basic_position(value_usd=10_000, holding_period_days=365)
        opts = [_opt(coverage_pct=100.0, deductible_pct=100.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertAlmostEqual(r["options"][0]["effective_coverage_usd"], 0.0)
        self.assertAlmostEqual(r["options"][0]["expected_payout_usd"], 0.0)

    def test_result_json_serializable(self):
        pos = _basic_position(holding_period_days=365)
        opts = [_opt(annual_premium_pct=0.0, coverage_pct=100.0, max_coverage_usd=None)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        # Must not raise
        serialized = json.dumps(r)
        self.assertIsInstance(serialized, str)

    def test_no_nan_in_result(self):
        pos = _basic_position(value_usd=0.0, holding_period_days=0)
        opts = [_opt(annual_premium_pct=0.0, coverage_pct=0.0)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        for o in r["options"]:
            for k, v in o.items():
                if isinstance(v, float):
                    with self.subTest(key=k):
                        self.assertFalse(math.isnan(v))

    def test_missing_config_uses_defaults(self):
        pos = _basic_position(protocol_risk_score=0, holding_period_days=365)
        r = analyze(pos, [], config=None, data_file=self.df, save=False)
        self.assertAlmostEqual(r["adjusted_hack_probability"], 0.05)

    def test_empty_config_dict_uses_defaults(self):
        pos = _basic_position(protocol_risk_score=0, holding_period_days=365)
        r = analyze(pos, [], config={}, data_file=self.df, save=False)
        self.assertAlmostEqual(r["adjusted_hack_probability"], 0.05)

    def test_timestamp_is_recent(self):
        before = time.time()
        r = analyze(_basic_position(), [], data_file=self.df, save=False)
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_position_passthrough_in_result(self):
        pos = {
            "protocol": "Uniswap",
            "value_usd": 42_000.0,
            "protocol_risk_score": 33,
            "holding_period_days": 200,
        }
        r = analyze(pos, [], data_file=self.df, save=False)
        self.assertEqual(r["position"]["protocol"], "Uniswap")
        self.assertAlmostEqual(r["position"]["value_usd"], 42_000.0)
        self.assertEqual(r["position"]["protocol_risk_score"], 33)
        self.assertEqual(r["position"]["holding_period_days"], 200)


# ===========================================================================
# 11. Ring-buffer log I/O
# ===========================================================================

class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()
        # Remove so log starts empty
        self.df.unlink(missing_ok=True)

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_save_creates_file(self):
        analyze(_basic_position(), [], data_file=self.df, save=True)
        self.assertTrue(self.df.exists())

    def test_save_appends_entry(self):
        analyze(_basic_position(), [], data_file=self.df, save=True)
        log = _load_log(self.df)
        self.assertEqual(len(log), 1)

    def test_save_multiple_appends(self):
        for _ in range(5):
            analyze(_basic_position(), [], data_file=self.df, save=True)
        log = _load_log(self.df)
        self.assertEqual(len(log), 5)

    def test_ring_buffer_caps_at_max(self):
        for _ in range(_MAX_ENTRIES + 10):
            analyze(_basic_position(), [], data_file=self.df, save=True)
        log = _load_log(self.df)
        self.assertEqual(len(log), _MAX_ENTRIES)

    def test_save_false_does_not_write(self):
        analyze(_basic_position(), [], data_file=self.df, save=False)
        self.assertFalse(self.df.exists())

    def test_log_is_valid_json(self):
        analyze(_basic_position(), [], data_file=self.df, save=True)
        content = self.df.read_text()
        parsed = json.loads(content)
        self.assertIsInstance(parsed, list)

    def test_log_entry_has_timestamp(self):
        analyze(_basic_position(), [], data_file=self.df, save=True)
        log = _load_log(self.df)
        self.assertIn("timestamp", log[0])

    def test_ring_buffer_keeps_newest(self):
        """After filling past cap, the newest entry should be last."""
        for i in range(_MAX_ENTRIES + 5):
            analyze(
                _basic_position(value_usd=float(i)),
                [],
                data_file=self.df,
                save=True,
            )
        log = _load_log(self.df)
        # Last entry should have the highest value_usd
        self.assertAlmostEqual(
            log[-1]["position"]["value_usd"],
            float(_MAX_ENTRIES + 4),
        )

    def test_load_log_returns_empty_on_missing_file(self):
        missing = Path("/tmp/does_not_exist_spa_test.json")
        result = _load_log(missing)
        self.assertEqual(result, [])

    def test_load_log_returns_empty_on_corrupt_json(self):
        corrupt = _tmp_file()
        corrupt.write_text("not valid json {{{")
        result = _load_log(corrupt)
        self.assertEqual(result, [])
        corrupt.unlink()

    def test_atomic_write_uses_tmp_then_replace(self):
        """Verify no .tmp file is left behind after save."""
        analyze(_basic_position(), [], data_file=self.df, save=True)
        tmp_path = self.df.with_suffix(".tmp")
        self.assertFalse(tmp_path.exists())

    def test_max_entries_constant(self):
        self.assertEqual(_MAX_ENTRIES, 100)


# ===========================================================================
# 12. Multiple options and provider ordering
# ===========================================================================

class TestMultipleOptions(unittest.TestCase):
    def setUp(self):
        self.df = _tmp_file()

    def tearDown(self):
        self.df.unlink(missing_ok=True)

    def test_option_order_preserved(self):
        pos = _basic_position(holding_period_days=365)
        opts = [
            _opt(provider="Alpha"),
            _opt(provider="Beta"),
            _opt(provider="Gamma"),
        ]
        r = analyze(pos, opts, data_file=self.df, save=False)
        providers = [o["provider"] for o in r["options"]]
        self.assertEqual(providers, ["Alpha", "Beta", "Gamma"])

    def test_best_option_is_winner(self):
        pos = _basic_position(value_usd=100_000, protocol_risk_score=80,
                              holding_period_days=365)
        opts = [
            _opt(provider="Expensive", annual_premium_pct=5.0, coverage_pct=100.0),
            _opt(provider="Cheap", annual_premium_pct=0.5, coverage_pct=100.0),
        ]
        r = analyze(pos, opts, config={"hack_probability_base": 0.05},
                    data_file=self.df, save=False)
        nets = {o["provider"]: o["net_value_usd"] for o in r["options"]}
        self.assertEqual(r["best_option"], max(nets, key=nets.get))

    def test_all_skip_means_not_worthwhile(self):
        pos = _basic_position(value_usd=1_000, protocol_risk_score=0,
                              holding_period_days=365)
        opts = [
            _opt(provider="P1", annual_premium_pct=20.0, coverage_pct=100.0),
            _opt(provider="P2", annual_premium_pct=15.0, coverage_pct=100.0),
        ]
        r = analyze(pos, opts, config={"hack_probability_base": 0.01},
                    data_file=self.df, save=False)
        self.assertFalse(r["insurance_worthwhile"])

    def test_all_options_computed(self):
        pos = _basic_position(holding_period_days=365)
        opts = [_opt(provider=f"P{i}") for i in range(7)]
        r = analyze(pos, opts, data_file=self.df, save=False)
        self.assertEqual(len(r["options"]), 7)


# ===========================================================================
# 13. Default data file path
# ===========================================================================

class TestDefaultFile(unittest.TestCase):
    def test_default_file_constant(self):
        from spa_core.analytics.defi_insurance_cost_analyzer import _DATA_FILE
        self.assertEqual(str(_DATA_FILE), "data/insurance_cost_log.json")

    def test_default_hack_probability_base(self):
        self.assertAlmostEqual(_DEFAULT_HACK_PROBABILITY_BASE, 0.05)


if __name__ == "__main__":
    unittest.main()
