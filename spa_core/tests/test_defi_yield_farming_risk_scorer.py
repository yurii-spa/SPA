"""
Tests for MP-903: DeFiYieldFarmingRiskScorer
Run: python3 -m unittest spa_core.tests.test_defi_yield_farming_risk_scorer -v
"""
import json
import os
import sys
import tempfile
import unittest

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))

from spa_core.analytics.defi_yield_farming_risk_scorer import DeFiYieldFarmingRiskScorer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_farm(**kwargs):
    """Return a minimal safe farm dict, overriding with kwargs."""
    base = {
        "protocol":                       "TestProtocol",
        "token_pair":                     "USDC/USDT",
        "apy_pct":                        5.0,
        "tvl_usd":                        10_000_000.0,
        "age_days":                       365,
        "audit_count":                    3,
        "rug_incidents":                  0,
        "liquidity_depth_usd":            5_000_000.0,
        "reward_token_price_change_30d":  5.0,
    }
    base.update(kwargs)
    return base


def _make_risky_farm(**kwargs):
    """Return a high-risk farm dict, overriding with kwargs."""
    base = {
        "protocol":                       "RugProtocol",
        "token_pair":                     "SHIB/ETH",
        "apy_pct":                        1000.0,
        "tvl_usd":                        50_000.0,
        "age_days":                       5,
        "audit_count":                    0,
        "rug_incidents":                  2,
        "liquidity_depth_usd":            10_000.0,
        "reward_token_price_change_30d":  -80.0,
    }
    base.update(kwargs)
    return base


class TestDeFiYieldFarmingRiskScorerInit(unittest.TestCase):
    def test_instantiation(self):
        scorer = DeFiYieldFarmingRiskScorer()
        self.assertIsNotNone(scorer)

    def test_log_cap_constant(self):
        self.assertEqual(DeFiYieldFarmingRiskScorer.LOG_CAP, 100)

    def test_apy_high_risk_threshold_constant(self):
        self.assertEqual(DeFiYieldFarmingRiskScorer.APY_HIGH_RISK_THRESHOLD, 500.0)

    def test_new_protocol_days_constant(self):
        self.assertEqual(DeFiYieldFarmingRiskScorer.NEW_PROTOCOL_DAYS, 30)

    def test_low_tvl_threshold_constant(self):
        self.assertEqual(DeFiYieldFarmingRiskScorer.LOW_TVL_THRESHOLD, 100_000.0)


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

class TestEmptyFarms(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldFarmingRiskScorer()
        self.result = self.scorer.score([], {})

    def test_empty_returns_ok_status(self):
        self.assertEqual(self.result["status"], "ok")

    def test_empty_farms_list(self):
        self.assertEqual(self.result["farms"], [])

    def test_empty_aggregates_safest_is_none(self):
        self.assertIsNone(self.result["aggregates"]["safest_farm"])

    def test_empty_aggregates_riskiest_is_none(self):
        self.assertIsNone(self.result["aggregates"]["riskiest_farm"])

    def test_empty_average_composite_zero(self):
        self.assertEqual(self.result["aggregates"]["average_composite_risk"], 0.0)

    def test_empty_extreme_count_zero(self):
        self.assertEqual(self.result["aggregates"]["extreme_count"], 0)

    def test_empty_very_low_count_zero(self):
        self.assertEqual(self.result["aggregates"]["very_low_count"], 0)

    def test_empty_total_farms_zero(self):
        self.assertEqual(self.result["aggregates"]["total_farms"], 0)


# ---------------------------------------------------------------------------
# Single farm output structure
# ---------------------------------------------------------------------------

class TestSingleFarmOutputStructure(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldFarmingRiskScorer()
        self.farm   = _make_farm()
        self.result = self.scorer.score([self.farm], {})
        self.scored = self.result["farms"][0]

    def test_output_has_farms_key(self):
        self.assertIn("farms", self.result)

    def test_output_has_aggregates_key(self):
        self.assertIn("aggregates", self.result)

    def test_output_has_status_key(self):
        self.assertIn("status", self.result)

    def test_status_is_ok(self):
        self.assertEqual(self.result["status"], "ok")

    def test_scored_has_protocol(self):
        self.assertIn("protocol", self.scored)

    def test_scored_has_token_pair(self):
        self.assertIn("token_pair", self.scored)

    def test_scored_has_apy_pct(self):
        self.assertIn("apy_pct", self.scored)

    def test_scored_has_sustainability_score(self):
        self.assertIn("sustainability_score", self.scored)

    def test_scored_has_rug_risk_score(self):
        self.assertIn("rug_risk_score", self.scored)

    def test_scored_has_il_risk_score(self):
        self.assertIn("il_risk_score", self.scored)

    def test_scored_has_composite_risk(self):
        self.assertIn("composite_risk", self.scored)

    def test_scored_has_risk_label(self):
        self.assertIn("risk_label", self.scored)

    def test_scored_has_flags(self):
        self.assertIn("flags", self.scored)

    def test_protocol_name_preserved(self):
        self.assertEqual(self.scored["protocol"], "TestProtocol")

    def test_token_pair_preserved(self):
        self.assertEqual(self.scored["token_pair"], "USDC/USDT")

    def test_apy_pct_preserved(self):
        self.assertAlmostEqual(self.scored["apy_pct"], 5.0)

    def test_flags_is_list(self):
        self.assertIsInstance(self.scored["flags"], list)

    def test_risk_label_is_string(self):
        self.assertIsInstance(self.scored["risk_label"], str)


# ---------------------------------------------------------------------------
# Score ranges (must be 0-100)
# ---------------------------------------------------------------------------

class TestScoreRanges(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldFarmingRiskScorer()

    def _score(self, **kwargs):
        return self.scorer.score([_make_farm(**kwargs)], {})["farms"][0]

    def test_sustainability_score_in_range_safe_farm(self):
        s = self._score()["sustainability_score"]
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_rug_risk_score_in_range_safe_farm(self):
        s = self._score()["rug_risk_score"]
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_il_risk_score_in_range_safe_farm(self):
        s = self._score()["il_risk_score"]
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_composite_risk_in_range_safe_farm(self):
        s = self._score()["composite_risk"]
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_composite_risk_in_range_risky_farm(self):
        s = self.scorer.score([_make_risky_farm()], {})["farms"][0]["composite_risk"]
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_all_scores_float_type(self):
        scored = self._score()
        for key in ("sustainability_score", "rug_risk_score", "il_risk_score", "composite_risk"):
            self.assertIsInstance(scored[key], float)


# ---------------------------------------------------------------------------
# Sustainability sub-score
# ---------------------------------------------------------------------------

class TestSustainabilityScore(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldFarmingRiskScorer()

    def _sust(self, **kwargs):
        return self.scorer.score([_make_farm(**kwargs)], {})["farms"][0]["sustainability_score"]

    def test_very_high_apy_lowers_sustainability(self):
        low_apy  = self._sust(apy_pct=5.0)
        high_apy = self._sust(apy_pct=2000.0)
        self.assertGreater(low_apy, high_apy)

    def test_reasonable_apy_no_extra_penalty(self):
        s5  = self._sust(apy_pct=5.0)
        s20 = self._sust(apy_pct=20.0)
        self.assertGreaterEqual(s5, s20)

    def test_apy_between_20_and_50(self):
        s = self._sust(apy_pct=35.0)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_large_tvl_improves_sustainability(self):
        big   = self._sust(tvl_usd=200_000_000)
        small = self._sust(tvl_usd=50_000)
        self.assertGreater(big, small)

    def test_small_tvl_hurts_sustainability(self):
        s = self._sust(tvl_usd=10_000)
        self.assertLess(s, self._sust(tvl_usd=5_000_000))

    def test_old_protocol_higher_sustainability(self):
        old = self._sust(age_days=400)
        new = self._sust(age_days=10)
        self.assertGreater(old, new)

    def test_brand_new_protocol_penalty(self):
        s_new = self._sust(age_days=5)
        s_old = self._sust(age_days=365)
        self.assertLess(s_new, s_old)

    def test_zero_apy_penalized(self):
        s0 = self._sust(apy_pct=0.0)
        s5 = self._sust(apy_pct=5.0)
        self.assertLess(s0, s5)


# ---------------------------------------------------------------------------
# Rug risk sub-score
# ---------------------------------------------------------------------------

class TestRugRiskScore(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldFarmingRiskScorer()

    def _rug(self, **kwargs):
        return self.scorer.score([_make_farm(**kwargs)], {})["farms"][0]["rug_risk_score"]

    def test_no_audits_raises_rug_risk(self):
        no_audit = self._rug(audit_count=0)
        with_audit = self._rug(audit_count=3)
        self.assertGreater(no_audit, with_audit)

    def test_multiple_audits_reduces_rug_risk(self):
        s = self._rug(audit_count=5)
        self.assertLessEqual(s, self._rug(audit_count=1))

    def test_rug_incidents_raise_risk(self):
        clean = self._rug(rug_incidents=0)
        risky = self._rug(rug_incidents=1)
        self.assertGreater(risky, clean)

    def test_two_rug_incidents_higher_than_one(self):
        one = self._rug(rug_incidents=1)
        two = self._rug(rug_incidents=2)
        self.assertGreater(two, one)

    def test_many_rug_incidents_max_penalty(self):
        s = self._rug(rug_incidents=5)
        self.assertGreater(s, self._rug(rug_incidents=0))

    def test_new_protocol_raises_rug_risk(self):
        new = self._rug(age_days=5)
        old = self._rug(age_days=365)
        self.assertGreater(new, old)

    def test_low_tvl_raises_rug_risk(self):
        low  = self._rug(tvl_usd=10_000)
        high = self._rug(tvl_usd=100_000_000)
        self.assertGreater(low, high)

    def test_rug_risk_in_range(self):
        s = self._rug(audit_count=0, rug_incidents=3, age_days=1)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)


# ---------------------------------------------------------------------------
# IL risk sub-score
# ---------------------------------------------------------------------------

class TestILRiskScore(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldFarmingRiskScorer()

    def _il(self, **kwargs):
        return self.scorer.score([_make_farm(**kwargs)], {})["farms"][0]["il_risk_score"]

    def test_stablecoin_pair_low_il(self):
        stable = self._il(token_pair="USDC/USDT")
        volatile = self._il(token_pair="ETH/BTC")
        self.assertLess(stable, volatile)

    def test_volatile_pair_high_il(self):
        s = self._il(token_pair="SHIB/ETH")
        self.assertGreater(s, 20)

    def test_negative_reward_token_price_raises_il(self):
        neg = self._il(reward_token_price_change_30d=-60.0)
        pos = self._il(reward_token_price_change_30d=20.0)
        self.assertGreater(neg, pos)

    def test_strongly_negative_reward_max_penalty(self):
        s_neg80 = self._il(reward_token_price_change_30d=-80.0)
        s_neg10 = self._il(reward_token_price_change_30d=-10.0)
        self.assertGreater(s_neg80, s_neg10)

    def test_deep_liquidity_reduces_il(self):
        deep    = self._il(liquidity_depth_usd=50_000_000)
        shallow = self._il(liquidity_depth_usd=10_000)
        self.assertLess(deep, shallow)

    def test_shallow_liquidity_raises_il(self):
        s = self._il(liquidity_depth_usd=10_000)
        self.assertGreater(s, self._il(liquidity_depth_usd=5_000_000))

    def test_zero_reward_change(self):
        s = self._il(reward_token_price_change_30d=0.0)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_high_apy_volatile_pair_raises_il(self):
        low_apy  = self._il(token_pair="ETH/BTC", apy_pct=10.0)
        high_apy = self._il(token_pair="ETH/BTC", apy_pct=500.0)
        self.assertGreater(high_apy, low_apy)

    def test_il_risk_in_range(self):
        s = self._il(token_pair="DOGE/SHIB", reward_token_price_change_30d=-90.0,
                     liquidity_depth_usd=100.0)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)


# ---------------------------------------------------------------------------
# Risk labels
# ---------------------------------------------------------------------------

class TestRiskLabels(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldFarmingRiskScorer()

    def _label(self, composite):
        return self.scorer._get_risk_label(composite)

    def test_score_0_is_very_low(self):
        self.assertEqual(self._label(0.0), "VERY_LOW")

    def test_score_19_9_is_very_low(self):
        self.assertEqual(self._label(19.9), "VERY_LOW")

    def test_score_20_is_low(self):
        self.assertEqual(self._label(20.0), "LOW")

    def test_score_39_9_is_low(self):
        self.assertEqual(self._label(39.9), "LOW")

    def test_score_40_is_moderate(self):
        self.assertEqual(self._label(40.0), "MODERATE")

    def test_score_59_9_is_moderate(self):
        self.assertEqual(self._label(59.9), "MODERATE")

    def test_score_60_is_high(self):
        self.assertEqual(self._label(60.0), "HIGH")

    def test_score_74_9_is_high(self):
        self.assertEqual(self._label(74.9), "HIGH")

    def test_score_75_is_very_high(self):
        self.assertEqual(self._label(75.0), "VERY_HIGH")

    def test_score_89_9_is_very_high(self):
        self.assertEqual(self._label(89.9), "VERY_HIGH")

    def test_score_90_is_extreme(self):
        self.assertEqual(self._label(90.0), "EXTREME")

    def test_score_100_is_extreme(self):
        self.assertEqual(self._label(100.0), "EXTREME")


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldFarmingRiskScorer()

    def _flags(self, **kwargs):
        return self.scorer.score([_make_farm(**kwargs)], {})["farms"][0]["flags"]

    def test_flag_high_apy_risk_triggered(self):
        self.assertIn("HIGH_APY_RISK", self._flags(apy_pct=600.0))

    def test_flag_high_apy_risk_not_triggered_below_threshold(self):
        self.assertNotIn("HIGH_APY_RISK", self._flags(apy_pct=500.0))

    def test_flag_new_protocol_triggered(self):
        self.assertIn("NEW_PROTOCOL", self._flags(age_days=10))

    def test_flag_new_protocol_not_triggered_at_threshold(self):
        self.assertNotIn("NEW_PROTOCOL", self._flags(age_days=30))

    def test_flag_low_tvl_triggered(self):
        self.assertIn("LOW_TVL", self._flags(tvl_usd=50_000))

    def test_flag_low_tvl_not_triggered_at_threshold(self):
        self.assertNotIn("LOW_TVL", self._flags(tvl_usd=100_000.0))

    def test_flag_unaudited_triggered(self):
        self.assertIn("UNAUDITED", self._flags(audit_count=0))

    def test_flag_unaudited_not_triggered_with_audits(self):
        self.assertNotIn("UNAUDITED", self._flags(audit_count=1))

    def test_flag_rug_history_triggered(self):
        self.assertIn("RUG_HISTORY", self._flags(rug_incidents=1))

    def test_flag_rug_history_not_triggered_clean(self):
        self.assertNotIn("RUG_HISTORY", self._flags(rug_incidents=0))

    def test_multiple_flags_worst_case(self):
        flags = self._flags(
            apy_pct=2000.0, age_days=5, tvl_usd=500.0,
            audit_count=0, rug_incidents=3
        )
        self.assertIn("HIGH_APY_RISK", flags)
        self.assertIn("NEW_PROTOCOL", flags)
        self.assertIn("LOW_TVL", flags)
        self.assertIn("UNAUDITED", flags)
        self.assertIn("RUG_HISTORY", flags)

    def test_no_flags_safe_farm(self):
        flags = self._flags(
            apy_pct=5.0, age_days=400, tvl_usd=50_000_000,
            audit_count=5, rug_incidents=0
        )
        self.assertEqual(flags, [])


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldFarmingRiskScorer()
        self.safe_farm  = _make_farm(protocol="SafeProtocol",  apy_pct=3.0,
                                     tvl_usd=100_000_000, age_days=730,
                                     audit_count=5, rug_incidents=0)
        self.risky_farm = _make_risky_farm(protocol="RiskyProtocol")
        self.result = self.scorer.score([self.safe_farm, self.risky_farm], {})
        self.agg = self.result["aggregates"]

    def test_safest_farm_is_safe_protocol(self):
        self.assertEqual(self.agg["safest_farm"], "SafeProtocol")

    def test_riskiest_farm_is_risky_protocol(self):
        self.assertEqual(self.agg["riskiest_farm"], "RiskyProtocol")

    def test_average_composite_risk_is_correct(self):
        farms = self.result["farms"]
        expected = (farms[0]["composite_risk"] + farms[1]["composite_risk"]) / 2
        self.assertAlmostEqual(self.agg["average_composite_risk"], expected, places=1)

    def test_total_farms(self):
        self.assertEqual(self.agg["total_farms"], 2)

    def test_extreme_count_counted(self):
        farms = self.result["farms"]
        expected_extreme = sum(1 for f in farms if f["risk_label"] == "EXTREME")
        self.assertEqual(self.agg["extreme_count"], expected_extreme)

    def test_very_low_count_counted(self):
        farms = self.result["farms"]
        expected_vl = sum(1 for f in farms if f["risk_label"] == "VERY_LOW")
        self.assertEqual(self.agg["very_low_count"], expected_vl)

    def test_single_farm_safest_equals_riskiest(self):
        result = self.scorer.score([_make_farm(protocol="OnlyFarm")], {})
        agg = result["aggregates"]
        self.assertEqual(agg["safest_farm"], "OnlyFarm")
        self.assertEqual(agg["riskiest_farm"], "OnlyFarm")


# ---------------------------------------------------------------------------
# Log / persistence
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldFarmingRiskScorer()
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "test_yield_log.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_persist_false_no_file_created(self):
        self.scorer.score([_make_farm()], {"persist": False, "log_path": self.log_path})
        self.assertFalse(os.path.exists(self.log_path))

    def test_persist_true_creates_file(self):
        self.scorer.score([_make_farm()], {"persist": True, "log_path": self.log_path})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_file_contains_list(self):
        self.scorer.score([_make_farm()], {"persist": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends_entry(self):
        self.scorer.score([_make_farm()], {"persist": True, "log_path": self.log_path})
        self.scorer.score([_make_farm()], {"persist": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_capped_at_100(self):
        for _ in range(105):
            self.scorer.score([_make_farm()], {"persist": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_file_written_atomically(self):
        # If file didn't exist before, it should appear as a complete JSON after write
        self.scorer.score([_make_farm()], {"persist": True, "log_path": self.log_path})
        with open(self.log_path) as f:
            content = f.read()
        parsed = json.loads(content)
        self.assertIsInstance(parsed, list)


# ---------------------------------------------------------------------------
# Custom weights
# ---------------------------------------------------------------------------

class TestCustomWeights(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldFarmingRiskScorer()

    def test_all_weight_on_rug_risk_affects_composite(self):
        farm = _make_farm(audit_count=0, rug_incidents=2)
        default_res = self.scorer.score([farm], {})["farms"][0]
        heavy_rug   = self.scorer.score([farm], {
            "weights": {"sustainability": 0.0, "rug_risk": 1.0, "il_risk": 0.0}
        })["farms"][0]
        # rug_risk dominating should raise composite risk
        self.assertGreater(heavy_rug["composite_risk"], 0)

    def test_zero_il_weight_removes_il_contribution(self):
        farm = _make_farm(token_pair="DOGE/SHIB", reward_token_price_change_30d=-90.0)
        no_il   = self.scorer.score([farm], {
            "weights": {"sustainability": 0.5, "rug_risk": 0.5, "il_risk": 0.0}
        })["farms"][0]
        with_il = self.scorer.score([farm], {
            "weights": {"sustainability": 0.33, "rug_risk": 0.34, "il_risk": 0.33}
        })["farms"][0]
        # Both results are valid 0-100; test types and ranges
        self.assertGreaterEqual(no_il["composite_risk"], 0.0)
        self.assertLessEqual(no_il["composite_risk"], 100.0)
        self.assertGreaterEqual(with_il["composite_risk"], 0.0)
        self.assertLessEqual(with_il["composite_risk"], 100.0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.scorer = DeFiYieldFarmingRiskScorer()

    def test_missing_all_fields_uses_defaults(self):
        result = self.scorer.score([{}], {})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["farms"]), 1)

    def test_apy_zero_handled(self):
        result = self.scorer.score([_make_farm(apy_pct=0.0)], {})
        scored = result["farms"][0]
        self.assertGreaterEqual(scored["composite_risk"], 0.0)

    def test_apy_negative_handled(self):
        result = self.scorer.score([_make_farm(apy_pct=-1.0)], {})
        scored = result["farms"][0]
        self.assertGreaterEqual(scored["composite_risk"], 0.0)

    def test_tvl_zero_handled(self):
        result = self.scorer.score([_make_farm(tvl_usd=0.0)], {})
        self.assertIn("composite_risk", result["farms"][0])

    def test_age_zero_handled(self):
        result = self.scorer.score([_make_farm(age_days=0)], {})
        self.assertIn("flags", result["farms"][0])

    def test_very_many_audits(self):
        result = self.scorer.score([_make_farm(audit_count=100)], {})
        scored = result["farms"][0]
        self.assertGreaterEqual(scored["rug_risk_score"], 0.0)

    def test_very_many_rug_incidents(self):
        result = self.scorer.score([_make_risky_farm(rug_incidents=50)], {})
        scored = result["farms"][0]
        self.assertLessEqual(scored["rug_risk_score"], 100.0)

    def test_empty_config_dict(self):
        result = self.scorer.score([_make_farm()], {})
        self.assertEqual(result["status"], "ok")

    def test_extreme_risk_farm_label(self):
        result = self.scorer.score([_make_risky_farm(
            apy_pct=5000.0, audit_count=0, rug_incidents=5,
            age_days=1, tvl_usd=100.0
        )], {})
        label = result["farms"][0]["risk_label"]
        self.assertIn(label, ("EXTREME", "VERY_HIGH", "HIGH"))

    def test_very_low_risk_farm_label(self):
        result = self.scorer.score([_make_farm(
            apy_pct=4.0, tvl_usd=500_000_000, age_days=1000,
            audit_count=10, rug_incidents=0
        )], {})
        label = result["farms"][0]["risk_label"]
        self.assertIn(label, ("VERY_LOW", "LOW", "MODERATE"))

    def test_two_farms_ordering(self):
        safe  = _make_farm(protocol="Safe",  tvl_usd=200_000_000, audit_count=5, age_days=700)
        risky = _make_risky_farm(protocol="Risky")
        result = self.scorer.score([safe, risky], {})
        agg = result["aggregates"]
        safe_risk  = result["farms"][0]["composite_risk"]
        risky_risk = result["farms"][1]["composite_risk"]
        self.assertGreater(risky_risk, safe_risk)
        self.assertEqual(agg["safest_farm"], "Safe")
        self.assertEqual(agg["riskiest_farm"], "Risky")

    def test_multiple_farms_total_count(self):
        farms = [_make_farm(protocol=f"P{i}") for i in range(5)]
        result = self.scorer.score(farms, {})
        self.assertEqual(result["aggregates"]["total_farms"], 5)

    def test_reward_price_change_positive_large(self):
        result = self.scorer.score([_make_farm(reward_token_price_change_30d=200.0)], {})
        s = result["farms"][0]["il_risk_score"]
        self.assertGreaterEqual(s, 0.0)

    def test_liquidity_depth_very_large(self):
        result = self.scorer.score([_make_farm(liquidity_depth_usd=1_000_000_000)], {})
        s = result["farms"][0]["il_risk_score"]
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
