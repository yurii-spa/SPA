"""
Tests for MP-938: DeFiLiquidStakingRateComparator
Run: python3 -m unittest spa_core.tests.test_defi_liquid_staking_rate_comparator -v
Target: ≥80 tests, stdlib unittest only.
"""
import json
import math
import os
import sys
import unittest
import tempfile

# Allow direct module import regardless of working directory
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.defi_liquid_staking_rate_comparator import (
    DeFiLiquidStakingRateComparator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_protocol(**kwargs):
    base = {
        "name": "TestLST",
        "token": "tLST",
        "base_staking_apy_pct": 4.0,
        "defi_boost_apy_pct": 1.0,
        "commission_pct": 10.0,
        "slash_incidents_count": 0,
        "validator_count": 100,
        "client_diversity_score": 70,
        "tvl_usd": 1_000_000_000,
        "withdrawal_delay_days": 1,
        "is_liquid": True,
        "peg_discount_pct": 0.1,
    }
    base.update(kwargs)
    return base


def _lido():
    return _make_protocol(
        name="Lido",
        token="stETH",
        base_staking_apy_pct=3.8,
        defi_boost_apy_pct=1.2,
        commission_pct=10.0,
        slash_incidents_count=0,
        validator_count=300_000,
        client_diversity_score=75,
        tvl_usd=30_000_000_000,
        withdrawal_delay_days=0,
        is_liquid=True,
        peg_discount_pct=0.02,
    )


def _rocketpool():
    return _make_protocol(
        name="RocketPool",
        token="rETH",
        base_staking_apy_pct=3.6,
        defi_boost_apy_pct=0.9,
        commission_pct=14.0,
        slash_incidents_count=0,
        validator_count=5000,
        client_diversity_score=85,
        tvl_usd=3_000_000_000,
        withdrawal_delay_days=2,
        is_liquid=True,
        peg_discount_pct=0.01,
    )


def _risky():
    return _make_protocol(
        name="SketchyStake",
        token="sLST",
        base_staking_apy_pct=20.0,
        defi_boost_apy_pct=5.0,
        commission_pct=25.0,
        slash_incidents_count=5,
        validator_count=3,
        client_diversity_score=10,
        tvl_usd=500_000,
        withdrawal_delay_days=30,
        is_liquid=False,
        peg_discount_pct=3.0,
    )


class TestInstantiation(unittest.TestCase):
    def test_can_instantiate(self):
        c = DeFiLiquidStakingRateComparator()
        self.assertIsNotNone(c)


class TestCompareReturnStructure(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_returns_dict(self):
        result = self.c.compare([_lido()], {})
        self.assertIsInstance(result, dict)

    def test_has_protocols_key(self):
        result = self.c.compare([_lido()], {})
        self.assertIn("protocols", result)

    def test_has_aggregates_key(self):
        result = self.c.compare([_lido()], {})
        self.assertIn("aggregates", result)

    def test_has_timestamp_key(self):
        result = self.c.compare([_lido()], {})
        self.assertIn("timestamp", result)

    def test_has_config_used_key(self):
        result = self.c.compare([_lido()], {})
        self.assertIn("config_used", result)

    def test_protocols_is_list(self):
        result = self.c.compare([_lido()], {})
        self.assertIsInstance(result["protocols"], list)

    def test_aggregates_is_dict(self):
        result = self.c.compare([_lido()], {})
        self.assertIsInstance(result["aggregates"], dict)


class TestProtocolOutputFields(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()
        result = self.c.compare([_lido()], {})
        self.p = result["protocols"][0]

    def test_has_name(self):
        self.assertIn("name", self.p)

    def test_has_token(self):
        self.assertIn("token", self.p)

    def test_has_total_effective_apy(self):
        self.assertIn("total_effective_apy_pct", self.p)

    def test_has_net_slash_risk_score(self):
        self.assertIn("net_slash_risk_score", self.p)

    def test_has_decentralization_score(self):
        self.assertIn("decentralization_score", self.p)

    def test_has_composite_quality_score(self):
        self.assertIn("composite_quality_score", self.p)

    def test_has_quality_label(self):
        self.assertIn("quality_label", self.p)

    def test_has_flags(self):
        self.assertIn("flags", self.p)

    def test_flags_is_list(self):
        self.assertIsInstance(self.p["flags"], list)


class TestEffectiveAPYCalculation(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_no_commission_no_drag(self):
        p = _make_protocol(base_staking_apy_pct=5.0, defi_boost_apy_pct=2.0, commission_pct=0.0)
        result = self.c.compare([p], {})
        apy = result["protocols"][0]["total_effective_apy_pct"]
        self.assertAlmostEqual(apy, 7.0, places=4)

    def test_commission_reduces_base(self):
        p = _make_protocol(base_staking_apy_pct=4.0, defi_boost_apy_pct=0.0, commission_pct=10.0)
        result = self.c.compare([p], {})
        apy = result["protocols"][0]["total_effective_apy_pct"]
        # 4.0 - 4.0*0.10 = 3.6
        self.assertAlmostEqual(apy, 3.6, places=4)

    def test_defi_boost_added(self):
        p = _make_protocol(base_staking_apy_pct=3.0, defi_boost_apy_pct=2.5, commission_pct=0.0)
        result = self.c.compare([p], {})
        apy = result["protocols"][0]["total_effective_apy_pct"]
        self.assertAlmostEqual(apy, 5.5, places=4)

    def test_full_commission_example(self):
        # base=4, boost=1, commission=10 → drag=0.4 → total=4.6
        p = _make_protocol(base_staking_apy_pct=4.0, defi_boost_apy_pct=1.0, commission_pct=10.0)
        result = self.c.compare([p], {})
        apy = result["protocols"][0]["total_effective_apy_pct"]
        self.assertAlmostEqual(apy, 4.6, places=4)

    def test_zero_base_apy(self):
        p = _make_protocol(base_staking_apy_pct=0.0, defi_boost_apy_pct=0.0, commission_pct=10.0)
        result = self.c.compare([p], {})
        apy = result["protocols"][0]["total_effective_apy_pct"]
        self.assertAlmostEqual(apy, 0.0, places=4)


class TestSlashRiskScore(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_zero_slashes_zero_risk(self):
        p = _make_protocol(slash_incidents_count=0)
        result = self.c.compare([p], {})
        self.assertEqual(result["protocols"][0]["net_slash_risk_score"], 0.0)

    def test_one_slash_low_risk(self):
        p = _make_protocol(slash_incidents_count=1)
        result = self.c.compare([p], {})
        self.assertGreater(result["protocols"][0]["net_slash_risk_score"], 0)

    def test_five_slashes_high_risk(self):
        p = _make_protocol(slash_incidents_count=5)
        result = self.c.compare([p], {})
        self.assertGreaterEqual(result["protocols"][0]["net_slash_risk_score"], 80)

    def test_slash_risk_capped_at_100(self):
        p = _make_protocol(slash_incidents_count=999)
        result = self.c.compare([p], {})
        self.assertLessEqual(result["protocols"][0]["net_slash_risk_score"], 100.0)

    def test_slash_risk_is_float(self):
        p = _make_protocol(slash_incidents_count=3)
        result = self.c.compare([p], {})
        self.assertIsInstance(result["protocols"][0]["net_slash_risk_score"], float)


class TestDecentralizationScore(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_score_in_range(self):
        p = _make_protocol(validator_count=100, client_diversity_score=70)
        result = self.c.compare([p], {})
        score = result["protocols"][0]["decentralization_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_high_validators_high_score(self):
        low = _make_protocol(validator_count=1, client_diversity_score=50)
        high = _make_protocol(validator_count=100_000, client_diversity_score=50)
        r_low = self.c.compare([low], {})["protocols"][0]["decentralization_score"]
        r_high = self.c.compare([high], {})["protocols"][0]["decentralization_score"]
        self.assertGreater(r_high, r_low)

    def test_high_diversity_increases_score(self):
        low = _make_protocol(validator_count=100, client_diversity_score=10)
        high = _make_protocol(validator_count=100, client_diversity_score=90)
        r_low = self.c.compare([low], {})["protocols"][0]["decentralization_score"]
        r_high = self.c.compare([high], {})["protocols"][0]["decentralization_score"]
        self.assertGreater(r_high, r_low)

    def test_zero_validators_low_score(self):
        p = _make_protocol(validator_count=0, client_diversity_score=0)
        result = self.c.compare([p], {})
        self.assertGreaterEqual(result["protocols"][0]["decentralization_score"], 0)


class TestCompositeQualityScore(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_score_in_range(self):
        result = self.c.compare([_lido()], {})
        score = result["protocols"][0]["composite_quality_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_risky_protocol_lower_score(self):
        r_good = self.c.compare([_lido()], {})["protocols"][0]["composite_quality_score"]
        r_bad = self.c.compare([_risky()], {})["protocols"][0]["composite_quality_score"]
        self.assertGreater(r_good, r_bad)

    def test_score_is_float(self):
        result = self.c.compare([_lido()], {})
        self.assertIsInstance(result["protocols"][0]["composite_quality_score"], float)


class TestQualityLabels(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    _VALID = {"PREMIUM", "GOOD", "STANDARD", "BELOW_AVERAGE", "AVOID"}

    def test_label_is_valid(self):
        result = self.c.compare([_lido()], {})
        label = result["protocols"][0]["quality_label"]
        self.assertIn(label, self._VALID)

    def test_risky_label_avoid_or_below(self):
        result = self.c.compare([_risky()], {})
        label = result["protocols"][0]["quality_label"]
        self.assertIn(label, {"AVOID", "BELOW_AVERAGE"})

    def test_all_labels_valid_for_mixed(self):
        result = self.c.compare([_lido(), _rocketpool(), _risky()], {})
        for p in result["protocols"]:
            self.assertIn(p["quality_label"], self._VALID)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_slashing_history_flag(self):
        p = _make_protocol(slash_incidents_count=2)
        result = self.c.compare([p], {})
        self.assertIn("SLASHING_HISTORY", result["protocols"][0]["flags"])

    def test_no_slashing_flag_if_clean(self):
        p = _make_protocol(slash_incidents_count=0)
        result = self.c.compare([p], {})
        self.assertNotIn("SLASHING_HISTORY", result["protocols"][0]["flags"])

    def test_high_commission_flag(self):
        p = _make_protocol(commission_pct=20.0)
        result = self.c.compare([p], {})
        self.assertIn("HIGH_COMMISSION", result["protocols"][0]["flags"])

    def test_no_high_commission_flag_below_threshold(self):
        p = _make_protocol(commission_pct=5.0)
        result = self.c.compare([p], {})
        self.assertNotIn("HIGH_COMMISSION", result["protocols"][0]["flags"])

    def test_trading_at_discount_flag(self):
        p = _make_protocol(peg_discount_pct=2.0)
        result = self.c.compare([p], {})
        self.assertIn("TRADING_AT_DISCOUNT", result["protocols"][0]["flags"])

    def test_no_discount_flag_below_threshold(self):
        p = _make_protocol(peg_discount_pct=0.1)
        result = self.c.compare([p], {})
        self.assertNotIn("TRADING_AT_DISCOUNT", result["protocols"][0]["flags"])

    def test_centralized_flag_low_validators(self):
        p = _make_protocol(validator_count=5, client_diversity_score=80)
        result = self.c.compare([p], {})
        self.assertIn("CENTRALIZED", result["protocols"][0]["flags"])

    def test_centralized_flag_low_diversity(self):
        p = _make_protocol(validator_count=1000, client_diversity_score=10)
        result = self.c.compare([p], {})
        self.assertIn("CENTRALIZED", result["protocols"][0]["flags"])

    def test_withdrawal_delay_flag(self):
        p = _make_protocol(withdrawal_delay_days=14)
        result = self.c.compare([p], {})
        self.assertIn("WITHDRAWAL_DELAY", result["protocols"][0]["flags"])

    def test_no_withdrawal_delay_flag(self):
        p = _make_protocol(withdrawal_delay_days=1)
        result = self.c.compare([p], {})
        self.assertNotIn("WITHDRAWAL_DELAY", result["protocols"][0]["flags"])

    def test_risky_has_multiple_flags(self):
        result = self.c.compare([_risky()], {})
        flags = result["protocols"][0]["flags"]
        self.assertGreaterEqual(len(flags), 3)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()
        self.result = self.c.compare([_lido(), _rocketpool(), _risky()], {})
        self.agg = self.result["aggregates"]

    def test_has_best_lst(self):
        self.assertIn("best_lst", self.agg)

    def test_has_worst_lst(self):
        self.assertIn("worst_lst", self.agg)

    def test_has_highest_total_apy(self):
        self.assertIn("highest_total_apy", self.agg)

    def test_has_average_composite_quality(self):
        self.assertIn("average_composite_quality", self.agg)

    def test_has_premium_count(self):
        self.assertIn("premium_count", self.agg)

    def test_protocol_count_correct(self):
        self.assertEqual(self.agg["protocol_count"], 3)

    def test_best_lst_is_string(self):
        self.assertIsInstance(self.agg["best_lst"], str)

    def test_worst_lst_is_string(self):
        self.assertIsInstance(self.agg["worst_lst"], str)

    def test_highest_total_apy_is_numeric(self):
        self.assertIsInstance(self.agg["highest_total_apy"], float)

    def test_average_quality_in_range(self):
        self.assertGreaterEqual(self.agg["average_composite_quality"], 0)
        self.assertLessEqual(self.agg["average_composite_quality"], 100)

    def test_premium_count_nonneg(self):
        self.assertGreaterEqual(self.agg["premium_count"], 0)


class TestEmptyInput(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_empty_list_returns_dict(self):
        result = self.c.compare([], {})
        self.assertIsInstance(result, dict)

    def test_empty_protocols_list(self):
        result = self.c.compare([], {})
        self.assertEqual(result["protocols"], [])

    def test_empty_aggregates_best_none(self):
        result = self.c.compare([], {})
        self.assertIsNone(result["aggregates"]["best_lst"])

    def test_empty_aggregates_count_zero(self):
        result = self.c.compare([], {})
        self.assertEqual(result["aggregates"]["protocol_count"], 0)


class TestSingleProtocol(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()
        self.result = self.c.compare([_lido()], {})

    def test_single_best_equals_worst(self):
        agg = self.result["aggregates"]
        self.assertEqual(agg["best_lst"], agg["worst_lst"])

    def test_single_protocol_count(self):
        self.assertEqual(self.result["aggregates"]["protocol_count"], 1)


class TestTypeValidation(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_raises_on_non_list_protocols(self):
        with self.assertRaises(TypeError):
            self.c.compare("not_a_list", {})

    def test_raises_on_non_dict_config(self):
        with self.assertRaises(TypeError):
            self.c.compare([], "bad_config")


class TestConfigOverrides(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_custom_high_commission_threshold(self):
        p = _make_protocol(commission_pct=12.0)
        # Default threshold is 15% → should NOT flag
        result = self.c.compare([p], {})
        self.assertNotIn("HIGH_COMMISSION", result["protocols"][0]["flags"])
        # Lower threshold to 10% → should flag
        result2 = self.c.compare([p], {"high_commission_threshold_pct": 10.0})
        self.assertIn("HIGH_COMMISSION", result2["protocols"][0]["flags"])

    def test_custom_peg_discount_threshold(self):
        p = _make_protocol(peg_discount_pct=0.4)
        result = self.c.compare([p], {"peg_discount_threshold_pct": 0.3})
        self.assertIn("TRADING_AT_DISCOUNT", result["protocols"][0]["flags"])

    def test_custom_withdrawal_delay(self):
        p = _make_protocol(withdrawal_delay_days=5)
        result_default = self.c.compare([p], {})
        self.assertNotIn("WITHDRAWAL_DELAY", result_default["protocols"][0]["flags"])
        result_strict = self.c.compare([p], {"withdrawal_delay_threshold_days": 3})
        self.assertIn("WITHDRAWAL_DELAY", result_strict["protocols"][0]["flags"])

    def test_config_reflected_in_config_used(self):
        cfg = {"high_commission_threshold_pct": 12.0}
        result = self.c.compare([_lido()], cfg)
        self.assertEqual(result["config_used"]["high_commission_threshold_pct"], 12.0)


class TestMultipleProtocols(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_three_protocols_count(self):
        result = self.c.compare([_lido(), _rocketpool(), _risky()], {})
        self.assertEqual(len(result["protocols"]), 3)

    def test_names_preserved(self):
        result = self.c.compare([_lido(), _rocketpool()], {})
        names = {p["name"] for p in result["protocols"]}
        self.assertEqual(names, {"Lido", "RocketPool"})

    def test_tokens_preserved(self):
        result = self.c.compare([_lido(), _rocketpool()], {})
        tokens = {p["token"] for p in result["protocols"]}
        self.assertEqual(tokens, {"stETH", "rETH"})


class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()
        self._orig_log = __import__(
            "spa_core.analytics.defi_liquid_staking_rate_comparator",
            fromlist=["LOG_PATH"]
        )

    def test_log_does_not_crash(self):
        # Just ensure compare() doesn't throw even if log dir is weird
        self.c.compare([_lido()], {})

    def test_log_written_to_file(self):
        import spa_core.analytics.defi_liquid_staking_rate_comparator as mod
        with tempfile.TemporaryDirectory() as d:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(d, "liquid_staking_comparison_log.json")
            try:
                self.c.compare([_lido()], {})
                self.assertTrue(os.path.exists(mod.LOG_PATH))
                with open(mod.LOG_PATH) as f:
                    buf = json.load(f)
                self.assertIsInstance(buf, list)
                self.assertEqual(len(buf), 1)
            finally:
                mod.LOG_PATH = orig

    def test_log_ring_buffer_cap(self):
        import spa_core.analytics.defi_liquid_staking_rate_comparator as mod
        with tempfile.TemporaryDirectory() as d:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(d, "liquid_staking_comparison_log.json")
            try:
                orig_cap = mod.LOG_CAP
                mod.LOG_CAP = 3
                for _ in range(5):
                    self.c.compare([_lido()], {})
                with open(mod.LOG_PATH) as f:
                    buf = json.load(f)
                self.assertLessEqual(len(buf), 3)
            finally:
                mod.LOG_PATH = orig
                mod.LOG_CAP = orig_cap

    def test_log_entry_has_ts(self):
        import spa_core.analytics.defi_liquid_staking_rate_comparator as mod
        with tempfile.TemporaryDirectory() as d:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(d, "liquid_staking_comparison_log.json")
            try:
                self.c.compare([_lido()], {})
                with open(mod.LOG_PATH) as f:
                    buf = json.load(f)
                self.assertIn("ts", buf[0])
            finally:
                mod.LOG_PATH = orig

    def test_log_entry_has_protocol_count(self):
        import spa_core.analytics.defi_liquid_staking_rate_comparator as mod
        with tempfile.TemporaryDirectory() as d:
            orig = mod.LOG_PATH
            mod.LOG_PATH = os.path.join(d, "liquid_staking_comparison_log.json")
            try:
                self.c.compare([_lido(), _rocketpool()], {})
                with open(mod.LOG_PATH) as f:
                    buf = json.load(f)
                self.assertEqual(buf[0]["protocol_count"], 2)
            finally:
                mod.LOG_PATH = orig


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_100pct_commission(self):
        p = _make_protocol(commission_pct=100.0, base_staking_apy_pct=5.0, defi_boost_apy_pct=0.0)
        result = self.c.compare([p], {})
        apy = result["protocols"][0]["total_effective_apy_pct"]
        self.assertAlmostEqual(apy, 0.0, places=4)

    def test_negative_peg_discount(self):
        # Premium (negative discount) should not add TRADING_AT_DISCOUNT
        p = _make_protocol(peg_discount_pct=-0.5)
        result = self.c.compare([p], {})
        self.assertNotIn("TRADING_AT_DISCOUNT", result["protocols"][0]["flags"])

    def test_very_high_tvl_accepted(self):
        p = _make_protocol(tvl_usd=1e15)
        result = self.c.compare([p], {})
        self.assertIsNotNone(result["protocols"][0])

    def test_zero_tvl_accepted(self):
        p = _make_protocol(tvl_usd=0)
        result = self.c.compare([p], {})
        self.assertIsNotNone(result["protocols"][0])

    def test_is_liquid_false_preserved(self):
        p = _make_protocol(is_liquid=False)
        result = self.c.compare([p], {})
        self.assertFalse(result["protocols"][0]["is_liquid"])

    def test_is_liquid_true_preserved(self):
        p = _make_protocol(is_liquid=True)
        result = self.c.compare([p], {})
        self.assertTrue(result["protocols"][0]["is_liquid"])

    def test_extra_fields_in_protocol_ignored(self):
        p = _make_protocol()
        p["unknown_field"] = "should_not_crash"
        result = self.c.compare([p], {})
        self.assertIsNotNone(result)

    def test_zero_defi_boost(self):
        p = _make_protocol(defi_boost_apy_pct=0.0)
        result = self.c.compare([p], {})
        apy = result["protocols"][0]["total_effective_apy_pct"]
        expected = 4.0 - 4.0 * 0.1
        self.assertAlmostEqual(apy, expected, places=4)

    def test_large_defi_boost(self):
        p = _make_protocol(base_staking_apy_pct=4.0, defi_boost_apy_pct=50.0, commission_pct=0.0)
        result = self.c.compare([p], {})
        apy = result["protocols"][0]["total_effective_apy_pct"]
        self.assertAlmostEqual(apy, 54.0, places=4)


class TestScoreOrdering(unittest.TestCase):
    """Tests that the ordering of quality scores is consistent."""

    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_more_slashes_lower_composite(self):
        clean = _make_protocol(slash_incidents_count=0)
        slashed = _make_protocol(slash_incidents_count=5)
        r_clean = self.c.compare([clean], {})["protocols"][0]["composite_quality_score"]
        r_slashed = self.c.compare([slashed], {})["protocols"][0]["composite_quality_score"]
        self.assertGreater(r_clean, r_slashed)

    def test_more_validators_better_decentralization(self):
        few = _make_protocol(validator_count=5, client_diversity_score=50)
        many = _make_protocol(validator_count=50_000, client_diversity_score=50)
        r_few = self.c.compare([few], {})["protocols"][0]["decentralization_score"]
        r_many = self.c.compare([many], {})["protocols"][0]["decentralization_score"]
        self.assertGreater(r_many, r_few)

    def test_higher_peg_discount_lower_composite(self):
        good_peg = _make_protocol(peg_discount_pct=0.0)
        bad_peg = _make_protocol(peg_discount_pct=5.0)
        r_good = self.c.compare([good_peg], {})["protocols"][0]["composite_quality_score"]
        r_bad = self.c.compare([bad_peg], {})["protocols"][0]["composite_quality_score"]
        self.assertGreater(r_good, r_bad)


class TestTimestamp(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_timestamp_is_string(self):
        result = self.c.compare([_lido()], {})
        self.assertIsInstance(result["timestamp"], str)

    def test_timestamp_contains_T(self):
        result = self.c.compare([_lido()], {})
        self.assertIn("T", result["timestamp"])

    def test_timestamp_contains_Z_or_plus(self):
        result = self.c.compare([_lido()], {})
        ts = result["timestamp"]
        self.assertTrue("Z" in ts or "+" in ts or ts.endswith("+00:00"))


class TestDecentralizationScoreDirect(unittest.TestCase):
    """Direct unit tests for _decentralization_score."""

    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_zero_zero(self):
        score = self.c._decentralization_score(0, 0)
        self.assertGreaterEqual(score, 0)

    def test_max_validators_max_diversity(self):
        score = self.c._decentralization_score(1_000_000, 100)
        self.assertLessEqual(score, 100)
        self.assertGreater(score, 50)

    def test_monotone_validators(self):
        s1 = self.c._decentralization_score(10, 50)
        s2 = self.c._decentralization_score(1000, 50)
        self.assertGreater(s2, s1)

    def test_monotone_diversity(self):
        s1 = self.c._decentralization_score(100, 20)
        s2 = self.c._decentralization_score(100, 80)
        self.assertGreater(s2, s1)


class TestSlashRiskDirect(unittest.TestCase):
    """Direct unit tests for _slash_risk_score."""

    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_zero(self):
        self.assertEqual(self.c._slash_risk_score(0), 0.0)

    def test_one(self):
        self.assertGreater(self.c._slash_risk_score(1), 0)

    def test_ten_capped(self):
        self.assertLessEqual(self.c._slash_risk_score(10), 100.0)

    def test_negative_treated_as_zero(self):
        self.assertGreaterEqual(self.c._slash_risk_score(-1), 0)


class TestQualityLabelDirect(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_90_premium(self):
        self.assertEqual(self.c._quality_label(90), "PREMIUM")

    def test_70_good(self):
        self.assertEqual(self.c._quality_label(70), "GOOD")

    def test_55_standard(self):
        self.assertEqual(self.c._quality_label(55), "STANDARD")

    def test_40_below_average(self):
        self.assertEqual(self.c._quality_label(40), "BELOW_AVERAGE")

    def test_10_avoid(self):
        self.assertEqual(self.c._quality_label(10), "AVOID")


class TestHighestAPY(unittest.TestCase):
    def setUp(self):
        self.c = DeFiLiquidStakingRateComparator()

    def test_highest_apy_corresponds_to_correct_protocol(self):
        low_apy = _make_protocol(name="LowAPY", base_staking_apy_pct=2.0, defi_boost_apy_pct=0.0, commission_pct=0.0)
        high_apy = _make_protocol(name="HighAPY", base_staking_apy_pct=10.0, defi_boost_apy_pct=0.0, commission_pct=0.0)
        result = self.c.compare([low_apy, high_apy], {})
        agg = result["aggregates"]
        self.assertEqual(agg["highest_total_apy_protocol"], "HighAPY")
        self.assertAlmostEqual(agg["highest_total_apy"], 10.0, places=4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
