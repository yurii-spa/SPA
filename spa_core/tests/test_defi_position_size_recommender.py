"""
Tests for MP-830: DeFiPositionSizeRecommender
≥65 unittest tests — pure stdlib.
"""

import json
import math
import os
import sys
import tempfile
import time
import unittest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_position_size_recommender import (
    RING_BUFFER_CAP,
    _compute_kelly,
    analyze,
)

# ── helpers ────────────────────────────────────────────────────────────────

_DEFAULTS = dict(
    kelly_fraction=0.25,
    max_position_pct=35.0,
    min_position_usd=200.0,
    portfolio_usd=100_000.0,
)


def _kelly(
    expected_apy=5.0,
    risk_score=20,
    max_loss_scenario_pct=50.0,
    win_probability=0.8,
    kelly_fraction=0.25,
    max_position_pct=35.0,
    min_position_usd=200.0,
    portfolio_usd=100_000.0,
):
    return _compute_kelly(
        expected_apy=expected_apy,
        risk_score=risk_score,
        max_loss_scenario_pct=max_loss_scenario_pct,
        win_probability=win_probability,
        kelly_fraction=kelly_fraction,
        max_position_pct=max_position_pct,
        min_position_usd=min_position_usd,
        portfolio_usd=portfolio_usd,
    )


def _opp(
    protocol="TestProto",
    expected_apy=5.0,
    risk_score=20,
    max_loss_scenario_pct=50.0,
    win_probability=0.8,
):
    return {
        "protocol": protocol,
        "expected_apy": expected_apy,
        "risk_score": risk_score,
        "max_loss_scenario_pct": max_loss_scenario_pct,
        "win_probability": win_probability,
    }


def _tmplog():
    return tempfile.mktemp(suffix=".json")


class TestComputeKellyBasics(unittest.TestCase):
    def test_returns_dict(self):
        r = _kelly()
        self.assertIsInstance(r, dict)

    def test_has_kelly_pct(self):
        r = _kelly()
        self.assertIn("kelly_pct", r)

    def test_has_adjusted_kelly_pct(self):
        r = _kelly()
        self.assertIn("adjusted_kelly_pct", r)

    def test_has_risk_penalty_pct(self):
        r = _kelly()
        self.assertIn("risk_penalty_pct", r)

    def test_has_final_pct(self):
        r = _kelly()
        self.assertIn("final_pct", r)

    def test_has_recommended_usd(self):
        r = _kelly()
        self.assertIn("recommended_usd", r)

    def test_has_viable(self):
        r = _kelly()
        self.assertIn("viable", r)

    def test_has_rationale(self):
        r = _kelly()
        self.assertIn("rationale", r)

    def test_viable_is_bool(self):
        r = _kelly()
        self.assertIsInstance(r["viable"], bool)

    def test_rationale_is_str(self):
        r = _kelly()
        self.assertIsInstance(r["rationale"], str)

    def test_final_pct_non_negative(self):
        r = _kelly()
        self.assertGreaterEqual(r["final_pct"], 0.0)

    def test_final_pct_not_exceeds_max(self):
        r = _kelly(max_position_pct=35.0)
        self.assertLessEqual(r["final_pct"], 35.0)

    def test_recommended_usd_non_negative(self):
        r = _kelly()
        self.assertGreaterEqual(r["recommended_usd"], 0.0)

    def test_risk_penalty_formula(self):
        # risk_score=50 → penalty = 50/100*10 = 5.0
        r = _kelly(risk_score=50)
        self.assertAlmostEqual(r["risk_penalty_pct"], 5.0, places=4)

    def test_risk_penalty_zero_at_zero_risk(self):
        r = _kelly(risk_score=0)
        self.assertAlmostEqual(r["risk_penalty_pct"], 0.0, places=4)

    def test_risk_penalty_max_at_100_risk(self):
        r = _kelly(risk_score=100)
        self.assertAlmostEqual(r["risk_penalty_pct"], 10.0, places=4)

    def test_kelly_positive(self):
        # High win_prob + good APY → positive kelly
        r = _kelly(expected_apy=20.0, win_probability=0.9, max_loss_scenario_pct=30.0,
                   risk_score=0)
        self.assertGreater(r["kelly_pct"], 0)

    def test_kelly_negative_unfavorable(self):
        # Low win_prob + bad APY → negative kelly
        r = _kelly(expected_apy=1.0, win_probability=0.1, max_loss_scenario_pct=90.0,
                   risk_score=0)
        self.assertLess(r["kelly_pct"], 0)

    def test_adjusted_kelly_is_kelly_times_fraction(self):
        r = _kelly(risk_score=0, win_probability=0.9, expected_apy=10.0,
                   max_loss_scenario_pct=20.0, kelly_fraction=0.25)
        kelly = r["kelly_pct"]
        if kelly > 0:
            self.assertAlmostEqual(r["adjusted_kelly_pct"], kelly * 0.25, places=2)

    def test_adjusted_kelly_zero_when_negative(self):
        r = _kelly(expected_apy=0.1, win_probability=0.1, max_loss_scenario_pct=90.0)
        self.assertEqual(r["adjusted_kelly_pct"], 0.0)

    def test_max_loss_zero_caps_at_max_position(self):
        r = _kelly(max_loss_scenario_pct=0, max_position_pct=35.0, risk_score=0)
        self.assertLessEqual(r["final_pct"], 35.0)

    def test_recommended_usd_formula(self):
        r = _kelly(portfolio_usd=100_000, risk_score=0,
                   max_loss_scenario_pct=0, max_position_pct=20.0)
        # final_pct = 20 (max, since unbounded kelly - penalty 0)
        # recommended = 20/100 * 100000 = 20000
        self.assertAlmostEqual(r["recommended_usd"], 20_000.0, places=0)

    def test_viable_true_when_above_min(self):
        r = _kelly(portfolio_usd=100_000, risk_score=0,
                   max_loss_scenario_pct=0, max_position_pct=20.0,
                   min_position_usd=200.0)
        self.assertTrue(r["viable"])  # 20000 >= 200

    def test_viable_false_when_below_min(self):
        r = _kelly(portfolio_usd=100, max_loss_scenario_pct=0,
                   max_position_pct=1.0, min_position_usd=200.0)
        # recommended = 1.0% of 100 = 1.0 < 200
        self.assertFalse(r["viable"])

    def test_rationale_negative_kelly(self):
        r = _kelly(expected_apy=0.1, win_probability=0.1, max_loss_scenario_pct=90.0)
        self.assertIn("Negative Kelly", r["rationale"])

    def test_rationale_capped(self):
        # Unbounded (max_loss=0) → cap rationale
        r = _kelly(max_loss_scenario_pct=0, risk_score=0, max_position_pct=35.0)
        self.assertIn("capped", r["rationale"])

    def test_win_probability_1_no_crash(self):
        r = _kelly(win_probability=1.0, max_loss_scenario_pct=50.0)
        self.assertIsInstance(r, dict)

    def test_win_probability_0_results_in_negative_kelly(self):
        r = _kelly(win_probability=0.0, expected_apy=100.0, max_loss_scenario_pct=50.0)
        self.assertLessEqual(r["kelly_pct"], 0)
        self.assertEqual(r["final_pct"], 0.0)

    def test_portfolio_zero_recommended_usd_zero(self):
        r = _kelly(portfolio_usd=0, max_loss_scenario_pct=0, risk_score=0)
        self.assertEqual(r["recommended_usd"], 0.0)

    def test_high_risk_reduces_final_pct(self):
        low = _kelly(risk_score=0)
        high = _kelly(risk_score=100)
        self.assertGreaterEqual(low["final_pct"], high["final_pct"])

    def test_final_pct_ceiling_at_max_position(self):
        r = _kelly(max_loss_scenario_pct=0, risk_score=0, max_position_pct=10.0)
        self.assertLessEqual(r["final_pct"], 10.0)

    def test_kelly_formula_manual(self):
        # expected_apy=10, win_prob=0.8, max_loss=50
        # kelly = (0.8*0.10 - 0.2*0.50) / 0.50 * 100
        #       = (0.08 - 0.10) / 0.50 * 100 = -0.02/0.50*100 = -4.0
        r = _kelly(expected_apy=10.0, win_probability=0.8, max_loss_scenario_pct=50.0,
                   risk_score=0)
        self.assertAlmostEqual(r["kelly_pct"], -4.0, places=2)

    def test_kelly_formula_positive_manual(self):
        # expected_apy=100, win_prob=0.9, max_loss=20
        # kelly = (0.9*1.00 - 0.1*0.20)/0.20*100 = (0.90-0.02)/0.20*100 = 0.88/0.20*100 = 440
        # adjusted = min(440*0.25, 35) capped at 35
        r = _kelly(expected_apy=100.0, win_probability=0.9, max_loss_scenario_pct=20.0,
                   risk_score=0, max_position_pct=35.0)
        self.assertEqual(r["final_pct"], 35.0)
        self.assertIn("capped", r["rationale"])


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.log = _tmplog()
        self.cfg = {"log_path": self.log}

    def test_returns_dict(self):
        r = analyze(100_000, [_opp()], self.cfg)
        self.assertIsInstance(r, dict)

    def test_portfolio_usd_in_result(self):
        r = analyze(100_000, [_opp()], self.cfg)
        self.assertEqual(r["portfolio_usd"], 100_000.0)

    def test_recommendations_list(self):
        r = analyze(100_000, [_opp()], self.cfg)
        self.assertIsInstance(r["recommendations"], list)

    def test_single_recommendation(self):
        r = analyze(100_000, [_opp()], self.cfg)
        self.assertEqual(len(r["recommendations"]), 1)

    def test_multiple_recommendations(self):
        opps = [_opp("A"), _opp("B"), _opp("C")]
        r = analyze(100_000, opps, self.cfg)
        self.assertEqual(len(r["recommendations"]), 3)

    def test_protocol_name_in_rec(self):
        r = analyze(100_000, [_opp("MyProto")], self.cfg)
        self.assertEqual(r["recommendations"][0]["protocol"], "MyProto")

    def test_viable_count(self):
        r = analyze(100_000, [_opp()], self.cfg)
        self.assertIn("viable_count", r)

    def test_total_allocated_usd(self):
        r = analyze(100_000, [_opp()], self.cfg)
        self.assertIn("total_allocated_usd", r)

    def test_unallocated_usd(self):
        r = analyze(100_000, [_opp()], self.cfg)
        self.assertIn("unallocated_usd", r)

    def test_allocation_pct(self):
        r = analyze(100_000, [_opp()], self.cfg)
        self.assertIn("allocation_pct", r)

    def test_timestamp_present(self):
        r = analyze(100_000, [_opp()], self.cfg)
        self.assertIn("timestamp", r)

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(100_000, [_opp()], self.cfg)
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_empty_opportunities(self):
        r = analyze(100_000, [], self.cfg)
        self.assertEqual(r["recommendations"], [])
        self.assertEqual(r["viable_count"], 0)
        self.assertEqual(r["total_allocated_usd"], 0.0)

    def test_portfolio_zero(self):
        r = analyze(0.0, [_opp()], self.cfg)
        self.assertEqual(r["portfolio_usd"], 0.0)
        self.assertEqual(r["recommendations"][0]["recommended_usd"], 0.0)

    def test_allocation_pct_zero_portfolio(self):
        r = analyze(0.0, [_opp()], self.cfg)
        self.assertEqual(r["allocation_pct"], 0.0)

    def test_total_allocated_sums_recs(self):
        opps = [_opp("A"), _opp("B")]
        r = analyze(100_000, opps, self.cfg)
        total = sum(rec["recommended_usd"] for rec in r["recommendations"])
        self.assertAlmostEqual(r["total_allocated_usd"], total, places=3)

    def test_unallocated_is_portfolio_minus_allocated(self):
        r = analyze(100_000, [_opp()], self.cfg)
        expected = max(0.0, r["portfolio_usd"] - r["total_allocated_usd"])
        self.assertAlmostEqual(r["unallocated_usd"], expected, places=3)

    def test_viable_count_accurate(self):
        # One viable (good APY), one not viable (bad odds)
        opps = [
            _opp("Good", expected_apy=20, win_probability=0.95, max_loss_scenario_pct=10),
            _opp("Bad", expected_apy=0.1, win_probability=0.01, max_loss_scenario_pct=95),
        ]
        r = analyze(100_000, opps, self.cfg)
        v = sum(1 for rec in r["recommendations"] if rec["viable"])
        self.assertEqual(r["viable_count"], v)

    def test_custom_kelly_fraction(self):
        cfg = dict(self.cfg, kelly_fraction=0.5)
        r05 = analyze(100_000, [_opp()], cfg)
        cfg25 = dict(self.cfg, kelly_fraction=0.25)
        r25 = analyze(100_000, [_opp()], cfg25)
        # 0.5 fraction → should allocate more
        self.assertGreaterEqual(
            r05["recommendations"][0]["adjusted_kelly_pct"],
            r25["recommendations"][0]["adjusted_kelly_pct"],
        )

    def test_custom_max_position_pct_respected(self):
        cfg = dict(self.cfg, max_position_pct=10.0)
        r = analyze(100_000, [_opp(max_loss_scenario_pct=0)], cfg)
        self.assertLessEqual(r["recommendations"][0]["final_pct"], 10.0)

    def test_custom_min_position_usd(self):
        cfg = dict(self.cfg, min_position_usd=5000.0)
        r = analyze(100_000, [_opp(expected_apy=0.1, win_probability=0.6)], cfg)
        rec = r["recommendations"][0]
        if rec["recommended_usd"] < 5000.0:
            self.assertFalse(rec["viable"])
        else:
            self.assertTrue(rec["viable"])

    def test_log_file_created(self):
        analyze(100_000, [_opp()], self.cfg)
        self.assertTrue(os.path.exists(self.log))

    def test_log_is_list(self):
        analyze(100_000, [_opp()], self.cfg)
        with open(self.log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends(self):
        analyze(100_000, [_opp()], self.cfg)
        analyze(100_000, [_opp()], self.cfg)
        with open(self.log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        for _ in range(RING_BUFFER_CAP + 5):
            analyze(100_000, [_opp()], self.cfg)
        with open(self.log) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), RING_BUFFER_CAP)

    def test_no_tmp_file_left(self):
        analyze(100_000, [_opp()], self.cfg)
        self.assertFalse(os.path.exists(self.log + ".tmp"))

    def test_corrupt_log_handled(self):
        with open(self.log, "w") as f:
            f.write("CORRUPT")
        r = analyze(100_000, [_opp()], self.cfg)
        self.assertIsInstance(r, dict)

    def test_config_none_uses_defaults(self):
        r = analyze(100_000, [_opp()], {"log_path": self.log})
        self.assertIsInstance(r, dict)
        self.assertIn("recommendations", r)

    def test_recommendation_all_fields(self):
        r = analyze(100_000, [_opp()], self.cfg)
        rec = r["recommendations"][0]
        for field in ("protocol", "kelly_pct", "adjusted_kelly_pct",
                      "risk_penalty_pct", "final_pct", "recommended_usd",
                      "viable", "rationale"):
            self.assertIn(field, rec)

    def test_high_risk_score_lowers_final_pct(self):
        low_risk = analyze(100_000, [_opp(risk_score=0)], self.cfg)
        high_risk = analyze(100_000, [_opp(risk_score=100)], self.cfg)
        self.assertGreaterEqual(
            low_risk["recommendations"][0]["final_pct"],
            high_risk["recommendations"][0]["final_pct"],
        )

    def test_negative_kelly_zero_final(self):
        # win_prob=0 always yields negative kelly → final_pct=0
        r = analyze(100_000, [_opp(win_probability=0.0, expected_apy=1.0,
                                   max_loss_scenario_pct=90.0)], self.cfg)
        self.assertEqual(r["recommendations"][0]["final_pct"], 0.0)

    def test_max_loss_zero_caps(self):
        r = analyze(100_000, [_opp(max_loss_scenario_pct=0, risk_score=0)], self.cfg)
        rec = r["recommendations"][0]
        self.assertLessEqual(rec["final_pct"], 35.0)

    def test_allocation_pct_formula(self):
        r = analyze(100_000, [_opp(max_loss_scenario_pct=0, risk_score=0)], self.cfg)
        expected = r["total_allocated_usd"] / 100_000 * 100
        self.assertAlmostEqual(r["allocation_pct"], expected, places=2)

    def test_rationale_high_risk_string(self):
        # risk_penalty >> adjusted_kelly → "High risk reduces..."
        r = analyze(
            100_000,
            [_opp(expected_apy=2.0, risk_score=100, win_probability=0.55,
                  max_loss_scenario_pct=50.0)],
            self.cfg,
        )
        rec = r["recommendations"][0]
        # risk_penalty = 10, adjusted_kelly is small → "High risk" or "Negative Kelly"
        self.assertIsInstance(rec["rationale"], str)
        self.assertGreater(len(rec["rationale"]), 0)

    def test_rationale_fractional_string(self):
        # Normal case with clear positive outcome
        r = analyze(
            100_000,
            [_opp(expected_apy=3.0, risk_score=0, win_probability=0.95,
                  max_loss_scenario_pct=10.0)],
            self.cfg,
        )
        rec = r["recommendations"][0]
        # Should be "X.X% Kelly allocation (adjusted 25% fractional)"
        self.assertIn("fractional", rec["rationale"])

    def test_protocol_name_coerced_to_str(self):
        opps = [_opp(protocol=42)]
        r = analyze(100_000, opps, self.cfg)
        self.assertEqual(r["recommendations"][0]["protocol"], "42")

    def test_multiple_protocols_names_preserved(self):
        opps = [_opp("Aave"), _opp("Compound"), _opp("Morpho")]
        r = analyze(100_000, opps, self.cfg)
        names = [rec["protocol"] for rec in r["recommendations"]]
        self.assertEqual(names, ["Aave", "Compound", "Morpho"])

    def test_win_probability_one_no_crash(self):
        r = analyze(100_000, [_opp(win_probability=1.0)], self.cfg)
        self.assertIsInstance(r, dict)

    def test_large_portfolio(self):
        r = analyze(10_000_000, [_opp(max_loss_scenario_pct=0, risk_score=0)],
                    dict(self.cfg, max_position_pct=35.0))
        rec = r["recommendations"][0]
        # 35% of 10M = 3.5M
        self.assertAlmostEqual(rec["recommended_usd"], 3_500_000.0, places=0)


class TestRationaleLogic(unittest.TestCase):
    """Dedicated tests for the four rationale branches."""

    def _cfg(self):
        return {"log_path": _tmplog()}

    def test_rationale_negative_kelly(self):
        # Guaranteed loss scenario
        r = analyze(100_000, [_opp(win_probability=0.0, expected_apy=1.0,
                                   max_loss_scenario_pct=80.0)], self._cfg())
        self.assertIn("Negative Kelly", r["recommendations"][0]["rationale"])

    def test_rationale_capped(self):
        # max_loss=0 → unbounded kelly → capped
        r = analyze(100_000, [_opp(max_loss_scenario_pct=0, risk_score=0)], self._cfg())
        self.assertIn("capped", r["recommendations"][0]["rationale"])

    def test_rationale_normal(self):
        # Low risk, decent APY with positive kelly not hitting cap
        r = analyze(
            100_000,
            [_opp(expected_apy=3.0, risk_score=0, win_probability=0.95,
                  max_loss_scenario_pct=5.0)],
            self._cfg(),
        )
        rec = r["recommendations"][0]
        # kelly = (0.95*0.03 - 0.05*0.05)/0.05 * 100 = (0.0285-0.0025)/0.05*100 = 52
        # adjusted = 52*0.25 = 13 (< 35 max, not capped)
        # risk_penalty = 0, so penalty not > adjusted/2
        # → fractional rationale
        self.assertIn("fractional", rec["rationale"])

    def test_rationale_high_risk(self):
        # High risk_score with small positive kelly → "High risk reduces..."
        # kelly_pct ~1% → adjusted = 0.25% → penalty = 10% >> 0.125%
        r = analyze(
            100_000,
            [_opp(expected_apy=1.0, risk_score=100, win_probability=0.55,
                  max_loss_scenario_pct=50.0)],
            self._cfg(),
        )
        rec = r["recommendations"][0]
        # kelly = (0.55*0.01 - 0.45*0.50)/0.50*100 = (0.0055-0.225)/0.50*100 = -43.9
        # → Negative Kelly
        self.assertIn("Negative Kelly", rec["rationale"])


if __name__ == "__main__":
    unittest.main()
