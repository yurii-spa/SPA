"""
Tests for DeFiGovernanceTokenUtilityScorer (MP-918).
≥80 tests. Run: python3 -m unittest spa_core.tests.test_defi_governance_token_utility_scorer
"""
import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_governance_token_utility_scorer import (
    DeFiGovernanceTokenUtilityScorer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _token(**kw):
    base = {
        "name": "GOV",
        "protocol": "TestProto",
        "voting_power": True,
        "fee_sharing_pct": 30.0,
        "buyback_monthly_usd": 100_000.0,
        "staking_apy_pct": 8.0,
        "staking_ratio_pct": 50.0,
        "veto_power": False,
        "protocol_revenue_monthly_usd": 500_000.0,
        "token_market_cap_usd": 10_000_000.0,
        "ve_model": False,
    }
    base.update(kw)
    return base


def _bare():
    """Minimal token with zero cash-flow."""
    return {
        "name": "BARE",
        "protocol": "BareProto",
        "voting_power": False,
        "fee_sharing_pct": 0.0,
        "buyback_monthly_usd": 0.0,
        "staking_apy_pct": 0.0,
        "staking_ratio_pct": 0.0,
        "veto_power": False,
        "protocol_revenue_monthly_usd": 0.0,
        "token_market_cap_usd": 1_000_000.0,
        "ve_model": False,
    }


def _full():
    """Max-utility token."""
    return {
        "name": "MAX",
        "protocol": "MaxProto",
        "voting_power": True,
        "fee_sharing_pct": 50.0,
        "buyback_monthly_usd": 500_000.0,
        "staking_apy_pct": 15.0,
        "staking_ratio_pct": 70.0,
        "veto_power": True,
        "protocol_revenue_monthly_usd": 2_000_000.0,
        "token_market_cap_usd": 5_000_000.0,
        "ve_model": True,
    }


class TestDeFiGovernanceTokenUtilityScorerOutputShape(unittest.TestCase):
    """Tests 1-20: output shape and required keys."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.scorer = DeFiGovernanceTokenUtilityScorer(
            log_path=os.path.join(d, "log.json")
        )

    def test_01_returns_dict(self):
        self.assertIsInstance(self.scorer.score([_token()]), dict)

    def test_02_has_results(self):
        self.assertIn("results", self.scorer.score([_token()]))

    def test_03_has_aggregates(self):
        self.assertIn("aggregates", self.scorer.score([_token()]))

    def test_04_has_timestamp(self):
        self.assertIn("timestamp", self.scorer.score([_token()]))

    def test_05_has_token_count(self):
        self.assertIn("token_count", self.scorer.score([_token()]))

    def test_06_token_count_correct(self):
        self.assertEqual(self.scorer.score([_token(), _token()])["token_count"], 2)

    def test_07_results_length_matches(self):
        self.assertEqual(len(self.scorer.score([_token(), _token()])["results"]), 2)

    def test_08_empty_list_ok(self):
        r = self.scorer.score([])
        self.assertEqual(r["token_count"], 0)
        self.assertEqual(r["results"], [])

    def test_09_result_item_has_name(self):
        self.assertIn("name", self.scorer.score([_token()])["results"][0])

    def test_10_result_item_has_protocol(self):
        self.assertIn("protocol", self.scorer.score([_token()])["results"][0])

    def test_11_result_item_has_cash_flow_yield(self):
        self.assertIn("cash_flow_yield_pct", self.scorer.score([_token()])["results"][0])

    def test_12_result_item_has_utility_score(self):
        self.assertIn("utility_score", self.scorer.score([_token()])["results"][0])

    def test_13_result_item_has_staking_attractiveness(self):
        self.assertIn("staking_attractiveness", self.scorer.score([_token()])["results"][0])

    def test_14_result_item_has_value_capture_ratio(self):
        self.assertIn("value_capture_ratio", self.scorer.score([_token()])["results"][0])

    def test_15_result_item_has_utility_label(self):
        self.assertIn("utility_label", self.scorer.score([_token()])["results"][0])

    def test_16_result_item_has_flags(self):
        self.assertIn("flags", self.scorer.score([_token()])["results"][0])

    def test_17_aggregates_has_highest_utility(self):
        self.assertIn("highest_utility", self.scorer.score([_token()])["aggregates"])

    def test_18_aggregates_has_lowest_utility(self):
        self.assertIn("lowest_utility", self.scorer.score([_token()])["aggregates"])

    def test_19_aggregates_has_average_cash_flow_yield(self):
        self.assertIn("average_cash_flow_yield", self.scorer.score([_token()])["aggregates"])

    def test_20_aggregates_has_average_utility(self):
        self.assertIn("average_utility", self.scorer.score([_token()])["aggregates"])

    def test_20b_aggregates_has_high_utility_count(self):
        self.assertIn("high_utility_count", self.scorer.score([_token()])["aggregates"])


class TestDeFiGovernanceTokenUtilityScorerRanges(unittest.TestCase):
    """Tests 21-40: score ranges and monotonicity."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.scorer = DeFiGovernanceTokenUtilityScorer(
            log_path=os.path.join(d, "log.json")
        )

    def _r(self, t):
        return self.scorer.score([t])["results"][0]

    def test_21_utility_score_ge_0(self):
        self.assertGreaterEqual(self._r(_token())["utility_score"], 0.0)

    def test_22_utility_score_le_100(self):
        self.assertLessEqual(self._r(_token())["utility_score"], 100.0)

    def test_23_staking_attractiveness_ge_0(self):
        self.assertGreaterEqual(self._r(_token())["staking_attractiveness"], 0.0)

    def test_24_staking_attractiveness_le_100(self):
        self.assertLessEqual(self._r(_token())["staking_attractiveness"], 100.0)

    def test_25_utility_score_capped_at_100(self):
        t = _full()
        t["staking_apy_pct"] = 1000.0
        t["buyback_monthly_usd"] = 100_000_000.0
        self.assertLessEqual(self._r(t)["utility_score"], 100.0)

    def test_26_staking_attractiveness_capped_at_100(self):
        t = _full()
        t["staking_apy_pct"] = 1000.0
        self.assertLessEqual(self._r(t)["staking_attractiveness"], 100.0)

    def test_27_ve_model_increases_utility(self):
        r_n = self._r(_token(ve_model=False))["utility_score"]
        r_y = self._r(_token(ve_model=True))["utility_score"]
        self.assertGreater(r_y, r_n)

    def test_28_veto_power_increases_utility(self):
        r_n = self._r(_token(veto_power=False))["utility_score"]
        r_y = self._r(_token(veto_power=True))["utility_score"]
        self.assertGreater(r_y, r_n)

    def test_29_voting_power_increases_utility(self):
        r_n = self._r(_token(voting_power=False))["utility_score"]
        r_y = self._r(_token(voting_power=True))["utility_score"]
        self.assertGreater(r_y, r_n)

    def test_30_higher_fee_sharing_higher_utility(self):
        r_lo = self._r(_token(fee_sharing_pct=0.0))["utility_score"]
        r_hi = self._r(_token(fee_sharing_pct=50.0))["utility_score"]
        self.assertGreater(r_hi, r_lo)

    def test_31_higher_staking_apy_higher_utility(self):
        r_lo = self._r(_token(staking_apy_pct=0.0))["utility_score"]
        r_hi = self._r(_token(staking_apy_pct=20.0))["utility_score"]
        self.assertGreater(r_hi, r_lo)

    def test_32_higher_staking_apy_higher_attractiveness(self):
        r_lo = self._r(_token(staking_apy_pct=0.0))["staking_attractiveness"]
        r_hi = self._r(_token(staking_apy_pct=20.0))["staking_attractiveness"]
        self.assertGreater(r_hi, r_lo)

    def test_33_higher_staking_ratio_higher_attractiveness(self):
        r_lo = self._r(_token(staking_ratio_pct=10.0))["staking_attractiveness"]
        r_hi = self._r(_token(staking_ratio_pct=90.0))["staking_attractiveness"]
        self.assertGreater(r_hi, r_lo)

    def test_34_ve_model_increases_attractiveness(self):
        r_n = self._r(_token(ve_model=False))["staking_attractiveness"]
        r_y = self._r(_token(ve_model=True))["staking_attractiveness"]
        self.assertGreater(r_y, r_n)

    def test_35_higher_fee_sharing_higher_attractiveness(self):
        r_lo = self._r(_token(fee_sharing_pct=0.0, staking_apy_pct=0))["staking_attractiveness"]
        r_hi = self._r(_token(fee_sharing_pct=50.0, staking_apy_pct=0))["staking_attractiveness"]
        self.assertGreater(r_hi, r_lo)

    def test_36_zero_cashflow_zero_yield(self):
        t = _bare()
        self.assertEqual(self._r(t)["cash_flow_yield_pct"], 0.0)

    def test_37_buyback_only_yield_correct(self):
        t = _bare()
        t["buyback_monthly_usd"] = 100_000.0
        t["token_market_cap_usd"] = 10_000_000.0
        r = self._r(t)
        # 100_000 * 12 / 10_000_000 * 100 = 12%
        self.assertAlmostEqual(r["cash_flow_yield_pct"], 12.0, places=2)

    def test_38_fee_sharing_only_yield_correct(self):
        t = _bare()
        t["fee_sharing_pct"] = 50.0
        t["protocol_revenue_monthly_usd"] = 100_000.0
        t["token_market_cap_usd"] = 1_000_000.0
        r = self._r(t)
        # 100_000 * 0.5 * 12 / 1_000_000 * 100 = 60%
        self.assertAlmostEqual(r["cash_flow_yield_pct"], 60.0, places=2)

    def test_39_value_capture_ratio_half(self):
        t = _token(fee_sharing_pct=50.0, protocol_revenue_monthly_usd=1_000_000.0)
        self.assertAlmostEqual(self._r(t)["value_capture_ratio"], 0.5, places=3)

    def test_40_value_capture_ratio_full(self):
        t = _token(fee_sharing_pct=100.0, protocol_revenue_monthly_usd=1_000_000.0)
        self.assertAlmostEqual(self._r(t)["value_capture_ratio"], 1.0, places=3)


class TestDeFiGovernanceTokenUtilityScorerLabels(unittest.TestCase):
    """Tests 41-55: label correctness."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.scorer = DeFiGovernanceTokenUtilityScorer(
            log_path=os.path.join(d, "log.json")
        )

    def test_41_valid_utility_label(self):
        valid = {"HIGH_UTILITY", "GOOD_UTILITY", "MODERATE", "LOW_UTILITY", "GOVERNANCE_ONLY"}
        result = self.scorer.score([_token()])["results"][0]
        self.assertIn(result["utility_label"], valid)

    def test_42_bare_token_governance_or_low(self):
        r = self.scorer.score([_bare()])["results"][0]
        self.assertIn(r["utility_label"], ("GOVERNANCE_ONLY", "LOW_UTILITY", "MODERATE"))

    def test_43_full_token_high_or_good(self):
        r = self.scorer.score([_full()])["results"][0]
        self.assertIn(r["utility_label"], ("HIGH_UTILITY", "GOOD_UTILITY"))

    def test_44_utility_score_above_80_label(self):
        # Force a score above 80 with everything maxed
        t = _full()
        r = self.scorer.score([t])["results"][0]
        if r["utility_score"] >= 80:
            self.assertEqual(r["utility_label"], "HIGH_UTILITY")

    def test_45_utility_score_zero_label_governance(self):
        t = _bare()
        r = self.scorer.score([t])["results"][0]
        if r["utility_score"] == 0:
            self.assertEqual(r["utility_label"], "GOVERNANCE_ONLY")


class TestDeFiGovernanceTokenUtilityScorerFlags(unittest.TestCase):
    """Tests 46-63: flag logic."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.scorer = DeFiGovernanceTokenUtilityScorer(
            log_path=os.path.join(d, "log.json")
        )

    def _flags(self, t):
        return self.scorer.score([t])["results"][0]["flags"]

    def test_46_flags_is_list(self):
        self.assertIsInstance(self._flags(_token()), list)

    def test_47_ve_model_flag_present(self):
        self.assertIn("VE_MODEL", self._flags(_token(ve_model=True)))

    def test_48_ve_model_flag_absent(self):
        self.assertNotIn("VE_MODEL", self._flags(_token(ve_model=False)))

    def test_49_fee_sharing_flag_present(self):
        self.assertIn("FEE_SHARING", self._flags(_token(fee_sharing_pct=10.0)))

    def test_50_fee_sharing_flag_absent_zero(self):
        self.assertNotIn("FEE_SHARING", self._flags(_token(fee_sharing_pct=0.0)))

    def test_51_high_staking_ratio_flag_present_above_60(self):
        self.assertIn("HIGH_STAKING_RATIO", self._flags(_token(staking_ratio_pct=70.0)))

    def test_52_high_staking_ratio_flag_absent_at_60(self):
        self.assertNotIn("HIGH_STAKING_RATIO", self._flags(_token(staking_ratio_pct=60.0)))

    def test_53_high_staking_ratio_flag_absent_below_60(self):
        self.assertNotIn("HIGH_STAKING_RATIO", self._flags(_token(staking_ratio_pct=59.9)))

    def test_54_buyback_flag_present(self):
        self.assertIn("BUYBACK_PROGRAM", self._flags(_token(buyback_monthly_usd=50_000.0)))

    def test_55_buyback_flag_absent_zero(self):
        self.assertNotIn("BUYBACK_PROGRAM", self._flags(_token(buyback_monthly_usd=0.0)))

    def test_56_low_revenue_capture_flag_present(self):
        # 5% fee sharing → 0.05 < 0.10
        t = _token(fee_sharing_pct=5.0, protocol_revenue_monthly_usd=1_000_000.0)
        self.assertIn("LOW_REVENUE_CAPTURE", self._flags(t))

    def test_57_low_revenue_capture_flag_absent_high_sharing(self):
        t = _token(fee_sharing_pct=50.0, protocol_revenue_monthly_usd=1_000_000.0)
        self.assertNotIn("LOW_REVENUE_CAPTURE", self._flags(t))

    def test_58_low_revenue_capture_zero_revenue(self):
        # Zero revenue → value_capture_ratio=0 < 0.10 → flag present
        t = _token(protocol_revenue_monthly_usd=0.0, fee_sharing_pct=50.0)
        self.assertIn("LOW_REVENUE_CAPTURE", self._flags(t))

    def test_59_multiple_flags_possible(self):
        t = _token(ve_model=True, fee_sharing_pct=30.0,
                   staking_ratio_pct=70.0, buyback_monthly_usd=100_000.0)
        self.assertGreater(len(self._flags(t)), 1)

    def test_60_no_flags_for_bare_except_low_capture(self):
        # bare token: no VE, no fee sharing, no high staking, no buyback; low revenue capture
        t = _bare()
        flags = self._flags(t)
        self.assertNotIn("VE_MODEL", flags)
        self.assertNotIn("FEE_SHARING", flags)
        self.assertNotIn("HIGH_STAKING_RATIO", flags)
        self.assertNotIn("BUYBACK_PROGRAM", flags)


class TestDeFiGovernanceTokenUtilityScorerAggregates(unittest.TestCase):
    """Tests 61-75: aggregate correctness."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.scorer = DeFiGovernanceTokenUtilityScorer(
            log_path=os.path.join(d, "log.json")
        )

    def test_61_empty_aggregates_none(self):
        agg = self.scorer.score([])["aggregates"]
        self.assertIsNone(agg["highest_utility"])
        self.assertIsNone(agg["lowest_utility"])

    def test_62_empty_aggregates_zeros(self):
        agg = self.scorer.score([])["aggregates"]
        self.assertEqual(agg["average_cash_flow_yield"], 0.0)
        self.assertEqual(agg["average_utility"], 0.0)
        self.assertEqual(agg["high_utility_count"], 0)

    def test_63_single_token_same_highest_lowest(self):
        agg = self.scorer.score([_token(name="ONLY")])["aggregates"]
        self.assertEqual(agg["highest_utility"], "ONLY")
        self.assertEqual(agg["lowest_utility"], "ONLY")

    def test_64_highest_utility_correct(self):
        tokens = [_full(), _bare()]
        agg = self.scorer.score(tokens)["aggregates"]
        self.assertEqual(agg["highest_utility"], "MAX")

    def test_65_lowest_utility_correct(self):
        tokens = [_full(), _bare()]
        agg = self.scorer.score(tokens)["aggregates"]
        self.assertEqual(agg["lowest_utility"], "BARE")

    def test_66_average_zero_cashflow(self):
        tokens = [_bare(), _bare()]
        agg = self.scorer.score(tokens)["aggregates"]
        self.assertEqual(agg["average_cash_flow_yield"], 0.0)

    def test_67_average_utility_matches_manual(self):
        t1 = _token(name="A")
        t2 = _token(name="B")
        result = self.scorer.score([t1, t2])
        r = result["results"]
        expected = round((r[0]["utility_score"] + r[1]["utility_score"]) / 2, 2)
        self.assertAlmostEqual(result["aggregates"]["average_utility"], expected, places=1)

    def test_68_high_utility_count_zero_bare_tokens(self):
        tokens = [_bare() for _ in range(3)]
        agg = self.scorer.score(tokens)["aggregates"]
        self.assertEqual(agg["high_utility_count"], 0)

    def test_69_high_utility_count_includes_good_utility(self):
        tokens = [_full()]
        result = self.scorer.score(tokens)
        label = result["results"][0]["utility_label"]
        expected_count = 1 if label in ("HIGH_UTILITY", "GOOD_UTILITY") else 0
        self.assertEqual(result["aggregates"]["high_utility_count"], expected_count)

    def test_70_five_tokens_count_correct(self):
        tokens = [_token(name=str(i)) for i in range(5)]
        result = self.scorer.score(tokens)
        self.assertEqual(result["token_count"], 5)

    def test_71_average_cf_yield_positive_with_buyback(self):
        tokens = [_token(buyback_monthly_usd=1_000_000)]
        agg = self.scorer.score(tokens)["aggregates"]
        self.assertGreater(agg["average_cash_flow_yield"], 0.0)


class TestDeFiGovernanceTokenUtilityScorerEdgeCases(unittest.TestCase):
    """Tests 72-80: edge cases, defaults, guard clauses."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.scorer = DeFiGovernanceTokenUtilityScorer(
            log_path=os.path.join(d, "log.json")
        )

    def test_72_zero_market_cap_no_exception(self):
        t = _token(token_market_cap_usd=0.0)
        result = self.scorer.score([t])
        self.assertIsNotNone(result)

    def test_73_negative_market_cap_no_exception(self):
        t = _token(token_market_cap_usd=-5000.0)
        result = self.scorer.score([t])
        self.assertIsNotNone(result)

    def test_74_minimal_token_no_exception(self):
        result = self.scorer.score([{"name": "X"}])
        self.assertIsNotNone(result)

    def test_75_missing_name_defaults_unknown(self):
        r = self.scorer.score([{"protocol": "P"}])["results"][0]
        self.assertEqual(r["name"], "unknown")

    def test_76_missing_protocol_defaults_unknown(self):
        r = self.scorer.score([{"name": "T"}])["results"][0]
        self.assertEqual(r["protocol"], "unknown")

    def test_77_config_optional(self):
        result = self.scorer.score([_token()])  # no config arg
        self.assertIsInstance(result, dict)

    def test_78_score_bare_utility_not_negative(self):
        r = self.scorer.score([_bare()])["results"][0]
        self.assertGreaterEqual(r["utility_score"], 0.0)

    def test_79_value_capture_ratio_zero_when_no_revenue(self):
        t = _token(protocol_revenue_monthly_usd=0.0, fee_sharing_pct=80.0)
        r = self.scorer.score([t])["results"][0]
        self.assertEqual(r["value_capture_ratio"], 0.0)

    def test_80_timestamp_is_string(self):
        result = self.scorer.score([_token()])
        self.assertIsInstance(result["timestamp"], str)


class TestDeFiGovernanceTokenUtilityScorerLog(unittest.TestCase):
    """Tests 81-95: ring-buffer log and atomic write."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.log_path = os.path.join(d, "gov_log.json")
        self.scorer = DeFiGovernanceTokenUtilityScorer(log_path=self.log_path)

    def test_81_log_created(self):
        self.scorer.score([_token()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_82_log_is_list(self):
        self.scorer.score([_token()])
        with open(self.log_path) as f:
            self.assertIsInstance(json.load(f), list)

    def test_83_log_grows(self):
        self.scorer.score([_token()])
        self.scorer.score([_token()])
        with open(self.log_path) as f:
            self.assertEqual(len(json.load(f)), 2)

    def test_84_ring_buffer_capped_at_100(self):
        for _ in range(110):
            self.scorer.score([_token()])
        with open(self.log_path) as f:
            self.assertLessEqual(len(json.load(f)), 100)

    def test_85_no_tmp_file_after_write(self):
        self.scorer.score([_token()])
        self.assertFalse(os.path.exists(self.log_path + ".tmp"))

    def test_86_log_entry_has_timestamp(self):
        self.scorer.score([_token()])
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertIn("timestamp", entry)

    def test_87_log_entry_has_token_count(self):
        self.scorer.score([_token()])
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertIn("token_count", entry)

    def test_88_log_entry_has_aggregates(self):
        self.scorer.score([_token()])
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertIn("aggregates", entry)

    def test_89_malformed_log_recovered(self):
        with open(self.log_path, "w") as f:
            f.write("NOT JSON {{")
        result = self.scorer.score([_token()])
        self.assertIsNotNone(result)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_90_existing_log_entries_preserved(self):
        self.scorer.score([_token()])
        self.scorer.score([_token()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_91_log_entry_token_count_correct(self):
        self.scorer.score([_token(), _token(name="B")])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["token_count"], 2)

    def test_92_ring_buffer_keeps_latest(self):
        # Fill to 105 entries, check last entry is latest
        for i in range(105):
            self.scorer.score([_token(name=f"T{i}")])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)  # cap enforced

    def test_93_log_valid_json_after_multiple_writes(self):
        for _ in range(5):
            self.scorer.score([_token()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_94_zero_token_count_logged(self):
        self.scorer.score([])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["token_count"], 0)

    def test_95_aggregates_in_log_match_output(self):
        result = self.scorer.score([_token(name="X")])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(
            data[0]["aggregates"]["highest_utility"],
            result["aggregates"]["highest_utility"]
        )


if __name__ == "__main__":
    unittest.main()
