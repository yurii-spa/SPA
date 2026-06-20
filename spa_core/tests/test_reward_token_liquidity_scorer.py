"""
Tests for MP-817 RewardTokenLiquidityScorer.
Run: python3 -m unittest spa_core.tests.test_reward_token_liquidity_scorer -v
"""

import json
import math
import os
import sys
import time
import unittest
import tempfile

# Ensure project root is importable
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.reward_token_liquidity_scorer import (
    score,
    score_and_log,
    log_result,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _p(token="ARB", liq=25_000_000.0, vol=80_000_000.0, emis=500_000.0, mc=2_000_000_000.0):
    return {
        "reward_token": token,
        "token_liquidity_usd": liq,
        "daily_volume_usd": vol,
        "daily_emission_usd": emis,
        "market_cap_usd": mc,
    }


# ---------------------------------------------------------------------------
# 1. Return-structure tests
# ---------------------------------------------------------------------------
class TestReturnStructure(unittest.TestCase):

    def setUp(self):
        self.result = score("TestProto", _p())

    def test_has_protocol(self):
        self.assertIn("protocol", self.result)

    def test_has_reward_token(self):
        self.assertIn("reward_token", self.result)

    def test_has_token_liquidity_usd(self):
        self.assertIn("token_liquidity_usd", self.result)

    def test_has_daily_volume_usd(self):
        self.assertIn("daily_volume_usd", self.result)

    def test_has_daily_emission_usd(self):
        self.assertIn("daily_emission_usd", self.result)

    def test_has_market_cap_usd(self):
        self.assertIn("market_cap_usd", self.result)

    def test_has_liquidity_score(self):
        self.assertIn("liquidity_score", self.result)

    def test_has_volume_ratio(self):
        self.assertIn("volume_ratio", self.result)

    def test_has_sell_pressure_pct(self):
        self.assertIn("sell_pressure_pct", self.result)

    def test_has_depth_ratio(self):
        self.assertIn("depth_ratio", self.result)

    def test_has_volume_subscore(self):
        self.assertIn("volume_subscore", self.result)

    def test_has_depth_subscore(self):
        self.assertIn("depth_subscore", self.result)

    def test_has_composite_score(self):
        self.assertIn("composite_score", self.result)

    def test_has_liquidity_grade(self):
        self.assertIn("liquidity_grade", self.result)

    def test_has_exit_feasibility(self):
        self.assertIn("exit_feasibility", self.result)

    def test_has_risk_flags(self):
        self.assertIn("risk_flags", self.result)

    def test_has_recommendation(self):
        self.assertIn("recommendation", self.result)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)

    def test_protocol_matches(self):
        self.assertEqual(self.result["protocol"], "TestProto")

    def test_reward_token_matches(self):
        self.assertEqual(self.result["reward_token"], "ARB")

    def test_risk_flags_is_list(self):
        self.assertIsInstance(self.result["risk_flags"], list)

    def test_recommendation_is_string(self):
        self.assertIsInstance(self.result["recommendation"], str)

    def test_liquidity_grade_is_string(self):
        self.assertIsInstance(self.result["liquidity_grade"], str)


# ---------------------------------------------------------------------------
# 2. Liquidity score tests (log scale)
# ---------------------------------------------------------------------------
class TestLiquidityScore(unittest.TestCase):

    def test_score_10k_is_zero(self):
        r = score("P", _p(liq=10_000.0))
        self.assertAlmostEqual(r["liquidity_score"], 0.0)

    def test_score_100k_is_25(self):
        r = score("P", _p(liq=100_000.0))
        self.assertAlmostEqual(r["liquidity_score"], 25.0)

    def test_score_1m_is_50(self):
        r = score("P", _p(liq=1_000_000.0))
        self.assertAlmostEqual(r["liquidity_score"], 50.0)

    def test_score_10m_is_75(self):
        r = score("P", _p(liq=10_000_000.0))
        self.assertAlmostEqual(r["liquidity_score"], 75.0)

    def test_score_100m_is_100(self):
        r = score("P", _p(liq=100_000_000.0))
        self.assertAlmostEqual(r["liquidity_score"], 100.0)

    def test_score_clamped_at_100(self):
        r = score("P", _p(liq=1_000_000_000.0))
        self.assertEqual(r["liquidity_score"], 100.0)

    def test_score_clamped_at_zero_below_10k(self):
        r = score("P", _p(liq=1_000.0))
        self.assertEqual(r["liquidity_score"], 0.0)

    def test_score_zero_liquidity_clamped(self):
        r = score("P", _p(liq=0.0))
        self.assertEqual(r["liquidity_score"], 0.0)

    def test_score_negative_liquidity_clamped(self):
        r = score("P", _p(liq=-5000.0))
        self.assertEqual(r["liquidity_score"], 0.0)

    def test_score_in_range(self):
        r = score("P", _p(liq=3_000_000.0))
        self.assertGreaterEqual(r["liquidity_score"], 0.0)
        self.assertLessEqual(r["liquidity_score"], 100.0)


# ---------------------------------------------------------------------------
# 3. Ratio math tests
# ---------------------------------------------------------------------------
class TestRatioMath(unittest.TestCase):

    def test_volume_ratio_basic(self):
        r = score("P", _p(vol=80_000_000.0, emis=500_000.0))
        self.assertAlmostEqual(r["volume_ratio"], 160.0)

    def test_sell_pressure_pct_basic(self):
        r = score("P", _p(vol=80_000_000.0, emis=500_000.0))
        self.assertAlmostEqual(r["sell_pressure_pct"], 0.625, places=3)

    def test_depth_ratio_basic(self):
        r = score("P", _p(liq=25_000_000.0, emis=500_000.0))
        self.assertAlmostEqual(r["depth_ratio"], 50.0)

    def test_volume_ratio_zero_emission_guarded(self):
        r = score("P", _p(emis=0.0))
        self.assertFalse(math.isinf(r["volume_ratio"]))

    def test_sell_pressure_zero_volume_guarded(self):
        r = score("P", _p(vol=0.0))
        self.assertFalse(math.isinf(r["sell_pressure_pct"]))

    def test_depth_ratio_zero_emission_guarded(self):
        r = score("P", _p(emis=0.0))
        self.assertFalse(math.isinf(r["depth_ratio"]))

    def test_high_emission_high_sell_pressure(self):
        r = score("P", _p(vol=1_000_000.0, emis=500_000.0))
        self.assertAlmostEqual(r["sell_pressure_pct"], 50.0)

    def test_low_emission_low_sell_pressure(self):
        r = score("P", _p(vol=100_000_000.0, emis=100_000.0))
        self.assertAlmostEqual(r["sell_pressure_pct"], 0.1, places=3)

    def test_sell_pressure_inverse_of_volume_ratio(self):
        r = score("P", _p(vol=10_000_000.0, emis=1_000_000.0))
        # vr = 10, sp = 10% → product ~ 100*... consistency
        self.assertAlmostEqual(r["volume_ratio"], 10.0)
        self.assertAlmostEqual(r["sell_pressure_pct"], 10.0)


# ---------------------------------------------------------------------------
# 4. Sub-score tests
# ---------------------------------------------------------------------------
class TestSubScores(unittest.TestCase):

    def test_volume_subscore_in_range(self):
        r = score("P", _p())
        self.assertGreaterEqual(r["volume_subscore"], 0.0)
        self.assertLessEqual(r["volume_subscore"], 100.0)

    def test_depth_subscore_in_range(self):
        r = score("P", _p())
        self.assertGreaterEqual(r["depth_subscore"], 0.0)
        self.assertLessEqual(r["depth_subscore"], 100.0)

    def test_volume_subscore_zero_when_ratio_at_one(self):
        r = score("P", _p(vol=1_000_000.0, emis=1_000_000.0))
        self.assertAlmostEqual(r["volume_subscore"], 0.0)

    def test_volume_subscore_max_at_high_ratio(self):
        r = score("P", _p(vol=100_000_000.0, emis=100_000.0))
        self.assertAlmostEqual(r["volume_subscore"], 100.0)

    def test_volume_subscore_zero_below_one(self):
        r = score("P", _p(vol=500_000.0, emis=1_000_000.0))
        self.assertAlmostEqual(r["volume_subscore"], 0.0)

    def test_depth_subscore_zero_when_depth_low(self):
        # depth_ratio = 5 (<=10) → 0
        r = score("P", _p(liq=500_000.0, emis=100_000.0))
        self.assertAlmostEqual(r["depth_subscore"], 0.0)

    def test_depth_subscore_max_at_high_depth(self):
        # depth_ratio = 10000 → clamp 100
        r = score("P", _p(liq=1_000_000_000.0, emis=100_000.0))
        self.assertAlmostEqual(r["depth_subscore"], 100.0)

    def test_higher_volume_higher_subscore(self):
        low = score("P", _p(vol=2_000_000.0, emis=1_000_000.0))
        high = score("P", _p(vol=50_000_000.0, emis=1_000_000.0))
        self.assertGreater(high["volume_subscore"], low["volume_subscore"])


# ---------------------------------------------------------------------------
# 5. Composite + grade tests
# ---------------------------------------------------------------------------
class TestCompositeGrade(unittest.TestCase):

    def test_composite_weighting(self):
        r = score("P", _p())
        expected = (r["liquidity_score"] * 0.5
                    + r["volume_subscore"] * 0.3
                    + r["depth_subscore"] * 0.2)
        self.assertAlmostEqual(r["composite_score"], expected)

    def test_composite_in_range(self):
        r = score("P", _p())
        self.assertGreaterEqual(r["composite_score"], 0.0)
        self.assertLessEqual(r["composite_score"], 100.0)

    def test_grade_a_high_quality(self):
        # deep liquidity, huge volume vs emission
        r = score("P", _p(liq=200_000_000.0, vol=500_000_000.0, emis=100_000.0))
        self.assertEqual(r["liquidity_grade"], "A")

    def test_grade_f_terrible(self):
        r = score("P", _p(liq=5_000.0, vol=10_000.0, emis=20_000.0))
        self.assertEqual(r["liquidity_grade"], "F")

    def test_grade_is_letter(self):
        r = score("P", _p())
        self.assertIn(r["liquidity_grade"], ["A", "B", "C", "D", "F"])

    def test_grade_a_threshold_boundary(self):
        # construct composite exactly >=80 via deep liquidity
        r = score("P", _p(liq=100_000_000.0, vol=100_000_000.0, emis=100_000.0))
        self.assertEqual(r["liquidity_grade"], "A")

    def test_grade_f_zero_everything(self):
        r = score("P", _p(liq=0.0, vol=0.0, emis=1.0, mc=0.0))
        self.assertEqual(r["liquidity_grade"], "F")

    def test_better_liquidity_better_grade_order(self):
        good = score("P", _p(liq=100_000_000.0, vol=200_000_000.0, emis=100_000.0))
        bad = score("P", _p(liq=50_000.0, vol=50_000.0, emis=40_000.0))
        grades = "FDCBA"
        self.assertGreater(grades.index(good["liquidity_grade"]),
                           grades.index(bad["liquidity_grade"]))

    def test_custom_grade_thresholds(self):
        # lower A threshold so a moderate position grades A
        r = score("P", _p(liq=10_000_000.0, vol=10_000_000.0, emis=500_000.0),
                  config={"grade_a_threshold": 40.0})
        self.assertEqual(r["liquidity_grade"], "A")


# ---------------------------------------------------------------------------
# 6. Exit feasibility tests
# ---------------------------------------------------------------------------
class TestExitFeasibility(unittest.TestCase):

    def test_easy_exit(self):
        # sp<5 and liquidity_score>=60
        r = score("P", _p(liq=10_000_000.0, vol=100_000_000.0, emis=100_000.0))
        self.assertEqual(r["exit_feasibility"], "EASY")

    def test_moderate_exit(self):
        # sp between 5 and 20
        r = score("P", _p(liq=5_000_000.0, vol=1_000_000.0, emis=100_000.0))
        # sp = 10% → MODERATE
        self.assertEqual(r["exit_feasibility"], "MODERATE")

    def test_difficult_exit(self):
        # sp between 20 and 50
        r = score("P", _p(liq=5_000_000.0, vol=1_000_000.0, emis=300_000.0))
        # sp = 30% → DIFFICULT
        self.assertEqual(r["exit_feasibility"], "DIFFICULT")

    def test_illiquid_exit(self):
        # sp >= 50
        r = score("P", _p(liq=1_000_000.0, vol=1_000_000.0, emis=600_000.0))
        # sp = 60% → ILLIQUID
        self.assertEqual(r["exit_feasibility"], "ILLIQUID")

    def test_easy_requires_high_liquidity_score(self):
        # sp<5 but liquidity_score<60 → MODERATE not EASY
        r = score("P", _p(liq=200_000.0, vol=100_000_000.0, emis=100_000.0))
        # ls ~ 30 (<60), sp tiny → MODERATE
        self.assertEqual(r["exit_feasibility"], "MODERATE")

    def test_feasibility_is_valid_category(self):
        r = score("P", _p())
        self.assertIn(r["exit_feasibility"], ["EASY", "MODERATE", "DIFFICULT", "ILLIQUID"])

    def test_sell_pressure_exactly_5_not_easy(self):
        # sp = 5 exactly → not <5 → MODERATE
        r = score("P", _p(liq=100_000_000.0, vol=2_000_000.0, emis=100_000.0))
        # sp = 5% → MODERATE
        self.assertEqual(r["exit_feasibility"], "MODERATE")

    def test_sell_pressure_exactly_20_difficult(self):
        # sp=20 exactly → not <20 → DIFFICULT
        r = score("P", _p(liq=5_000_000.0, vol=1_000_000.0, emis=200_000.0))
        self.assertEqual(r["exit_feasibility"], "DIFFICULT")

    def test_sell_pressure_exactly_50_illiquid(self):
        r = score("P", _p(liq=5_000_000.0, vol=1_000_000.0, emis=500_000.0))
        self.assertEqual(r["exit_feasibility"], "ILLIQUID")


# ---------------------------------------------------------------------------
# 7. Risk flags tests
# ---------------------------------------------------------------------------
class TestRiskFlags(unittest.TestCase):

    def test_large_emissions_flag(self):
        # sp > 20
        r = score("P", _p(liq=5_000_000.0, vol=1_000_000.0, emis=300_000.0))
        self.assertIn("Daily emissions large vs market volume", r["risk_flags"])

    def test_no_large_emissions_flag_when_small(self):
        r = score("P", _p())
        self.assertNotIn("Daily emissions large vs market volume", r["risk_flags"])

    def test_thin_liquidity_flag(self):
        r = score("P", _p(liq=50_000.0))
        self.assertIn("Thin reward-token liquidity", r["risk_flags"])

    def test_no_thin_liquidity_flag_when_deep(self):
        r = score("P", _p(liq=25_000_000.0))
        self.assertNotIn("Thin reward-token liquidity", r["risk_flags"])

    def test_high_inflation_flag(self):
        # emis/mc*100 > 1: emis 30M, mc 1B → 3%
        r = score("P", _p(liq=25_000_000.0, vol=80_000_000.0, emis=30_000_000.0, mc=1_000_000_000.0))
        self.assertIn("High inflation vs market cap", r["risk_flags"])

    def test_no_inflation_flag_when_mc_zero(self):
        r = score("P", _p(mc=0.0))
        self.assertNotIn("High inflation vs market cap", r["risk_flags"])

    def test_no_inflation_flag_when_low(self):
        # emis 500k mc 2B → 0.025% < 1
        r = score("P", _p())
        self.assertNotIn("High inflation vs market cap", r["risk_flags"])

    def test_no_flags_for_clean_token(self):
        r = score("P", _p(liq=50_000_000.0, vol=200_000_000.0, emis=200_000.0, mc=5_000_000_000.0))
        self.assertEqual(r["risk_flags"], [])

    def test_multiple_flags_coexist(self):
        # thin liquidity + high sell pressure + high inflation
        r = score("P", _p(liq=50_000.0, vol=100_000.0, emis=50_000.0, mc=1_000_000.0))
        self.assertGreaterEqual(len(r["risk_flags"]), 2)

    def test_flags_are_strings(self):
        r = score("P", _p(liq=50_000.0))
        for f in r["risk_flags"]:
            self.assertIsInstance(f, str)


# ---------------------------------------------------------------------------
# 8. Recommendation tests
# ---------------------------------------------------------------------------
class TestRecommendation(unittest.TestCase):

    def test_recommendation_easy(self):
        r = score("P", _p(liq=10_000_000.0, vol=100_000_000.0, emis=100_000.0))
        self.assertIn("minimal slippage", r["recommendation"].lower())

    def test_recommendation_moderate(self):
        r = score("P", _p(liq=5_000_000.0, vol=1_000_000.0, emis=100_000.0))
        self.assertIn("tranches", r["recommendation"].lower())

    def test_recommendation_difficult(self):
        r = score("P", _p(liq=5_000_000.0, vol=1_000_000.0, emis=300_000.0))
        self.assertIn("slippage", r["recommendation"].lower())

    def test_recommendation_illiquid(self):
        r = score("P", _p(liq=1_000_000.0, vol=1_000_000.0, emis=600_000.0))
        self.assertIn("avoid", r["recommendation"].lower())

    def test_recommendation_nonempty(self):
        r = score("P", _p())
        self.assertGreater(len(r["recommendation"]), 0)

    def test_recommendation_is_string(self):
        r = score("P", _p())
        self.assertIsInstance(r["recommendation"], str)


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases(unittest.TestCase):

    def test_all_zeros(self):
        r = score("P", _p(liq=0.0, vol=0.0, emis=0.0, mc=0.0))
        self.assertIn("liquidity_grade", r)

    def test_zero_emission_no_division_error(self):
        r = score("P", _p(emis=0.0))
        self.assertIn("composite_score", r)

    def test_zero_volume_no_division_error(self):
        r = score("P", _p(vol=0.0))
        self.assertIn("sell_pressure_pct", r)

    def test_empty_params_defaults(self):
        r = score("P", {})
        self.assertEqual(r["reward_token"], "")
        self.assertEqual(r["token_liquidity_usd"], 0.0)

    def test_missing_market_cap_defaults_zero(self):
        r = score("P", {"reward_token": "X", "token_liquidity_usd": 1e6,
                        "daily_volume_usd": 1e6, "daily_emission_usd": 1e4})
        self.assertEqual(r["market_cap_usd"], 0.0)

    def test_large_values(self):
        r = score("P", _p(liq=1e12, vol=1e12, emis=1e6, mc=1e13))
        self.assertLessEqual(r["liquidity_score"], 100.0)

    def test_small_values(self):
        r = score("P", _p(liq=100.0, vol=50.0, emis=10.0, mc=1000.0))
        self.assertIn("liquidity_grade", r)

    def test_config_none_uses_defaults(self):
        r1 = score("P", _p(), config=None)
        r2 = score("P", _p(), config={})
        self.assertEqual(r1["liquidity_grade"], r2["liquidity_grade"])

    def test_extra_config_keys_ignored(self):
        r = score("P", _p(), config={"unknown_key": 999})
        self.assertIn("liquidity_grade", r)

    def test_timestamp_is_recent(self):
        before = time.time()
        r = score("P", _p())
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_protocol_name_preserved(self):
        r = score("GMX", _p())
        self.assertEqual(r["protocol"], "GMX")

    def test_reward_token_preserved(self):
        r = score("P", _p(token="CRV"))
        self.assertEqual(r["reward_token"], "CRV")

    def test_negative_inputs_no_crash(self):
        r = score("P", _p(liq=-100.0, vol=-50.0, emis=-10.0, mc=-1000.0))
        self.assertIn("liquidity_grade", r)

    def test_composite_never_nan(self):
        r = score("P", _p(liq=0.0, vol=0.0, emis=0.0))
        self.assertFalse(math.isnan(r["composite_score"]))

    def test_thin_liquidity_custom_threshold(self):
        # liq 200k, custom thin threshold 500k → flagged
        r = score("P", _p(liq=200_000.0), config={"thin_liquidity_usd": 500_000.0})
        self.assertIn("Thin reward-token liquidity", r["risk_flags"])


# ---------------------------------------------------------------------------
# 10. Log / IO tests
# ---------------------------------------------------------------------------
class TestLogging(unittest.TestCase):

    def test_log_result_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            r = score("P", _p())
            log_result(r, log_path=path)
            self.assertTrue(os.path.exists(path))

    def test_log_result_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            r = score("P", _p())
            log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_log_result_appends(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            for i in range(3):
                r = score(f"P{i}", _p())
                log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)

    def test_log_ring_buffer_capped_at_100(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            for i in range(120):
                r = score(f"P{i}", _p())
                log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 100)

    def test_log_keeps_most_recent_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_log.json")
            for i in range(110):
                r = score(f"PROTO_{i}", _p())
                log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data[-1]["protocol"], "PROTO_109")
            self.assertEqual(data[0]["protocol"], "PROTO_10")

    def test_score_and_log_returns_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            r = score_and_log("P", _p(), log_path=path)
            self.assertIn("protocol", r)

    def test_score_and_log_writes_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            score_and_log("P", _p(), log_path=path)
            self.assertTrue(os.path.exists(path))

    def test_log_handles_corrupt_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            with open(path, "w") as f:
                f.write("not valid json {{{")
            r = score("P", _p())
            log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)

    def test_log_creates_missing_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "nested", "deep", "log.json")
            r = score("P", _p())
            log_result(r, log_path=path)
            self.assertTrue(os.path.exists(path))

    def test_log_no_stray_tmp_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            r = score("P", _p())
            log_result(r, log_path=path)
            tmps = [f for f in os.listdir(tmpdir) if f.endswith(".tmp")]
            self.assertEqual(tmps, [])

    def test_log_roundtrip_preserves_grade(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "log.json")
            r = score("P", _p())
            log_result(r, log_path=path)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data[0]["liquidity_grade"], r["liquidity_grade"])


if __name__ == "__main__":
    unittest.main()
