"""
MP-910 — Unit tests for ProtocolFeeStructureAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_fee_structure_analyzer -v
Target: ≥85 tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from spa_core.analytics.protocol_fee_structure_analyzer import (
    DEFAULT_CONFIG,
    LABEL_VERY_COMPETITIVE,
    LABEL_COMPETITIVE,
    LABEL_MARKET_RATE,
    LABEL_EXPENSIVE,
    LABEL_VERY_EXPENSIVE,
    FLAG_FEE_SWITCH,
    FLAG_HIGH_PROTOCOL_CUT,
    FLAG_EXPENSIVE_VS_MARKET,
    FLAG_NO_TIERS,
    VALID_CATEGORIES,
    ProtocolFeeStructureAnalyzer,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _tier(tier_name="0.3%", fee_pct=0.3, volume_24h_usd=1_000_000.0):
    return {"tier_name": tier_name, "fee_pct": fee_pct, "volume_24h_usd": volume_24h_usd}


def _proto(
    name="Uniswap",
    category="dex",
    fee_tiers=None,
    protocol_fee_pct=0.0,
    fee_switch_active=False,
    total_volume_30d_usd=30_000_000.0,
    competitor_avg_fee_pct=0.3,
):
    if fee_tiers is None:
        fee_tiers = [_tier()]
    return {
        "name": name,
        "category": category,
        "fee_tiers": fee_tiers,
        "protocol_fee_pct": protocol_fee_pct,
        "fee_switch_active": fee_switch_active,
        "total_volume_30d_usd": total_volume_30d_usd,
        "competitor_avg_fee_pct": competitor_avg_fee_pct,
    }


# ── test class ────────────────────────────────────────────────────────────────

class TestConstruction(unittest.TestCase):
    def test_01_instantiate(self):
        a = ProtocolFeeStructureAnalyzer()
        self.assertIsNotNone(a)

    def test_02_analyze_returns_dict(self):
        a = ProtocolFeeStructureAnalyzer()
        r = a.analyze([])
        self.assertIsInstance(r, dict)

    def test_03_has_protocols_detail(self):
        a = ProtocolFeeStructureAnalyzer()
        r = a.analyze([])
        self.assertIn("protocols_detail", r)

    def test_04_has_cheapest_protocol(self):
        a = ProtocolFeeStructureAnalyzer()
        r = a.analyze([])
        self.assertIn("cheapest_protocol", r)

    def test_05_has_most_expensive(self):
        a = ProtocolFeeStructureAnalyzer()
        r = a.analyze([])
        self.assertIn("most_expensive", r)

    def test_06_has_total_ecosystem_revenue(self):
        a = ProtocolFeeStructureAnalyzer()
        r = a.analyze([])
        self.assertIn("total_ecosystem_revenue_30d_usd", r)

    def test_07_has_average_effective_rate(self):
        a = ProtocolFeeStructureAnalyzer()
        r = a.analyze([])
        self.assertIn("average_effective_rate", r)

    def test_08_has_fee_switch_count(self):
        a = ProtocolFeeStructureAnalyzer()
        r = a.analyze([])
        self.assertIn("fee_switch_count", r)

    def test_09_has_timestamp_utc(self):
        a = ProtocolFeeStructureAnalyzer()
        r = a.analyze([])
        self.assertIn("timestamp_utc", r)

    def test_10_has_config_used(self):
        a = ProtocolFeeStructureAnalyzer()
        r = a.analyze([])
        self.assertIn("config_used", r)


class TestEmptyInput(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolFeeStructureAnalyzer()
        self.r = self.a.analyze([])

    def test_11_empty_protocols_detail_list(self):
        self.assertIsInstance(self.r["protocols_detail"], list)

    def test_12_empty_protocols_detail_len(self):
        self.assertEqual(len(self.r["protocols_detail"]), 0)

    def test_13_empty_cheapest_none(self):
        self.assertIsNone(self.r["cheapest_protocol"])

    def test_14_empty_most_expensive_none(self):
        self.assertIsNone(self.r["most_expensive"])

    def test_15_empty_revenue_zero(self):
        self.assertEqual(self.r["total_ecosystem_revenue_30d_usd"], 0.0)

    def test_16_empty_avg_rate_none(self):
        self.assertIsNone(self.r["average_effective_rate"])

    def test_17_empty_fee_switch_count_zero(self):
        self.assertEqual(self.r["fee_switch_count"], 0)


class TestEffectiveFeeRate(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolFeeStructureAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_18_single_tier_rate(self):
        p = _proto(fee_tiers=[_tier(fee_pct=0.3, volume_24h_usd=1_000.0)])
        r = self.a.analyze([p], self.cfg)
        self.assertAlmostEqual(r["protocols_detail"][0]["effective_fee_rate_pct"], 0.3, places=4)

    def test_19_two_tier_volume_weighted(self):
        tiers = [
            _tier("low", fee_pct=0.1, volume_24h_usd=1_000.0),
            _tier("high", fee_pct=0.9, volume_24h_usd=1_000.0),
        ]
        p = _proto(fee_tiers=tiers)
        r = self.a.analyze([p], self.cfg)
        # equal volumes → avg = 0.5
        self.assertAlmostEqual(r["protocols_detail"][0]["effective_fee_rate_pct"], 0.5, places=4)

    def test_20_volume_weighted_skew_high_vol(self):
        tiers = [
            _tier("low", fee_pct=0.05, volume_24h_usd=9_000.0),
            _tier("high", fee_pct=1.0, volume_24h_usd=1_000.0),
        ]
        p = _proto(fee_tiers=tiers)
        r = self.a.analyze([p], self.cfg)
        eff = r["protocols_detail"][0]["effective_fee_rate_pct"]
        # 0.05*0.9 + 1.0*0.1 = 0.045 + 0.1 = 0.145
        self.assertAlmostEqual(eff, 0.145, places=3)

    def test_21_empty_tiers_rate_zero(self):
        p = _proto(fee_tiers=[])
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols_detail"][0]["effective_fee_rate_pct"], 0.0)

    def test_22_zero_volume_equal_weight(self):
        tiers = [
            _tier("a", fee_pct=0.2, volume_24h_usd=0.0),
            _tier("b", fee_pct=0.4, volume_24h_usd=0.0),
        ]
        p = _proto(fee_tiers=tiers)
        r = self.a.analyze([p], self.cfg)
        eff = r["protocols_detail"][0]["effective_fee_rate_pct"]
        self.assertAlmostEqual(eff, 0.3, places=4)


class TestFeeLabels(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolFeeStructureAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_23_label_very_competitive(self):
        p = _proto(
            fee_tiers=[_tier(fee_pct=0.1)],
            competitor_avg_fee_pct=0.3,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols_detail"][0]["fee_label"], LABEL_VERY_COMPETITIVE)

    def test_24_label_market_rate(self):
        p = _proto(
            fee_tiers=[_tier(fee_pct=0.3)],
            competitor_avg_fee_pct=0.3,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols_detail"][0]["fee_label"], LABEL_MARKET_RATE)

    def test_25_label_very_expensive(self):
        p = _proto(
            fee_tiers=[_tier(fee_pct=1.0)],
            competitor_avg_fee_pct=0.3,
        )
        r = self.a.analyze([p], self.cfg)
        label = r["protocols_detail"][0]["fee_label"]
        self.assertIn(label, [LABEL_EXPENSIVE, LABEL_VERY_EXPENSIVE])

    def test_26_label_competitive(self):
        p = _proto(
            fee_tiers=[_tier(fee_pct=0.25)],
            competitor_avg_fee_pct=0.3,
        )
        r = self.a.analyze([p], self.cfg)
        label = r["protocols_detail"][0]["fee_label"]
        self.assertIn(label, [LABEL_COMPETITIVE, LABEL_MARKET_RATE])

    def test_27_label_is_string(self):
        p = _proto()
        r = self.a.analyze([p], self.cfg)
        self.assertIsInstance(r["protocols_detail"][0]["fee_label"], str)

    def test_28_all_label_constants_distinct(self):
        labels = {LABEL_VERY_COMPETITIVE, LABEL_COMPETITIVE, LABEL_MARKET_RATE,
                  LABEL_EXPENSIVE, LABEL_VERY_EXPENSIVE}
        self.assertEqual(len(labels), 5)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolFeeStructureAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_29_flag_fee_switch_on(self):
        p = _proto(fee_switch_active=True)
        r = self.a.analyze([p], self.cfg)
        self.assertIn(FLAG_FEE_SWITCH, r["protocols_detail"][0]["flags"])

    def test_30_flag_fee_switch_off_absent(self):
        p = _proto(fee_switch_active=False)
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn(FLAG_FEE_SWITCH, r["protocols_detail"][0]["flags"])

    def test_31_flag_high_protocol_cut(self):
        p = _proto(protocol_fee_pct=25.0)
        r = self.a.analyze([p], self.cfg)
        self.assertIn(FLAG_HIGH_PROTOCOL_CUT, r["protocols_detail"][0]["flags"])

    def test_32_flag_high_protocol_cut_absent(self):
        p = _proto(protocol_fee_pct=10.0)
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn(FLAG_HIGH_PROTOCOL_CUT, r["protocols_detail"][0]["flags"])

    def test_33_flag_expensive_vs_market(self):
        p = _proto(
            fee_tiers=[_tier(fee_pct=1.0)],
            competitor_avg_fee_pct=0.3,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertIn(FLAG_EXPENSIVE_VS_MARKET, r["protocols_detail"][0]["flags"])

    def test_34_flag_expensive_vs_market_absent(self):
        p = _proto(
            fee_tiers=[_tier(fee_pct=0.3)],
            competitor_avg_fee_pct=0.3,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn(FLAG_EXPENSIVE_VS_MARKET, r["protocols_detail"][0]["flags"])

    def test_35_flag_no_tiers_single_tier(self):
        p = _proto(fee_tiers=[_tier()])
        r = self.a.analyze([p], self.cfg)
        self.assertIn(FLAG_NO_TIERS, r["protocols_detail"][0]["flags"])

    def test_36_flag_no_tiers_absent_multiple(self):
        p = _proto(fee_tiers=[_tier("a"), _tier("b")])
        r = self.a.analyze([p], self.cfg)
        self.assertNotIn(FLAG_NO_TIERS, r["protocols_detail"][0]["flags"])

    def test_37_flag_no_tiers_empty_tiers(self):
        p = _proto(fee_tiers=[])
        r = self.a.analyze([p], self.cfg)
        self.assertIn(FLAG_NO_TIERS, r["protocols_detail"][0]["flags"])

    def test_38_flags_is_list(self):
        p = _proto()
        r = self.a.analyze([p], self.cfg)
        self.assertIsInstance(r["protocols_detail"][0]["flags"], list)

    def test_39_multiple_flags_combined(self):
        p = _proto(
            fee_switch_active=True,
            protocol_fee_pct=30.0,
            fee_tiers=[_tier(fee_pct=1.5)],
            competitor_avg_fee_pct=0.3,
        )
        r = self.a.analyze([p], self.cfg)
        flags = r["protocols_detail"][0]["flags"]
        self.assertIn(FLAG_FEE_SWITCH, flags)
        self.assertIn(FLAG_HIGH_PROTOCOL_CUT, flags)
        self.assertIn(FLAG_EXPENSIVE_VS_MARKET, flags)


class TestRevenue(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolFeeStructureAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_40_revenue_calculation(self):
        # volume=30M, fee=0.3%, protocol_fee=10% → 30M * 0.003 * 0.1 = 9000
        p = _proto(
            fee_tiers=[_tier(fee_pct=0.3, volume_24h_usd=1_000_000.0)],
            protocol_fee_pct=10.0,
            total_volume_30d_usd=30_000_000.0,
        )
        r = self.a.analyze([p], self.cfg)
        rev = r["protocols_detail"][0]["protocol_revenue_30d_usd"]
        self.assertAlmostEqual(rev, 9000.0, places=0)

    def test_41_revenue_zero_when_no_volume(self):
        p = _proto(total_volume_30d_usd=0.0, protocol_fee_pct=10.0)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols_detail"][0]["protocol_revenue_30d_usd"], 0.0)

    def test_42_revenue_zero_when_protocol_fee_zero(self):
        p = _proto(protocol_fee_pct=0.0)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols_detail"][0]["protocol_revenue_30d_usd"], 0.0)

    def test_43_total_ecosystem_revenue_sum(self):
        p1 = _proto("A", total_volume_30d_usd=10_000_000.0, protocol_fee_pct=10.0,
                    fee_tiers=[_tier(fee_pct=0.3)])
        p2 = _proto("B", total_volume_30d_usd=20_000_000.0, protocol_fee_pct=10.0,
                    fee_tiers=[_tier(fee_pct=0.3)])
        r = self.a.analyze([p1, p2], self.cfg)
        # 10M*0.003*0.1 + 20M*0.003*0.1 = 3000 + 6000 = 9000
        self.assertAlmostEqual(r["total_ecosystem_revenue_30d_usd"], 9000.0, places=0)

    def test_44_revenue_is_float(self):
        p = _proto()
        r = self.a.analyze([p], self.cfg)
        self.assertIsInstance(r["protocols_detail"][0]["protocol_revenue_30d_usd"], float)


class TestUserCostScore(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolFeeStructureAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_45_cost_score_range_0_100(self):
        p = _proto()
        r = self.a.analyze([p], self.cfg)
        score = r["protocols_detail"][0]["user_cost_score"]
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_46_cost_score_zero_when_free(self):
        p = _proto(fee_tiers=[_tier(fee_pct=0.0)])
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols_detail"][0]["user_cost_score"], 0.0)

    def test_47_cost_score_50_at_competitor_avg(self):
        p = _proto(
            fee_tiers=[_tier(fee_pct=0.3, volume_24h_usd=1.0)],
            competitor_avg_fee_pct=0.3,
        )
        r = self.a.analyze([p], self.cfg)
        self.assertAlmostEqual(r["protocols_detail"][0]["user_cost_score"], 50.0, places=2)

    def test_48_cost_score_is_float(self):
        p = _proto()
        r = self.a.analyze([p], self.cfg)
        self.assertIsInstance(r["protocols_detail"][0]["user_cost_score"], float)

    def test_49_higher_fee_higher_score(self):
        p_cheap = _proto(fee_tiers=[_tier(fee_pct=0.05)])
        p_expensive = _proto(fee_tiers=[_tier(fee_pct=1.0)])
        r1 = self.a.analyze([p_cheap], self.cfg)
        r2 = self.a.analyze([p_expensive], self.cfg)
        self.assertLess(
            r1["protocols_detail"][0]["user_cost_score"],
            r2["protocols_detail"][0]["user_cost_score"],
        )


class TestCompetitivePosition(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolFeeStructureAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_50_competitive_position_is_string(self):
        p = _proto()
        r = self.a.analyze([p], self.cfg)
        self.assertIsInstance(r["protocols_detail"][0]["competitive_position"], str)

    def test_51_at_market_rate(self):
        p = _proto(fee_tiers=[_tier(fee_pct=0.3)], competitor_avg_fee_pct=0.3)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols_detail"][0]["competitive_position"], "at_market")

    def test_52_cheaper_position(self):
        p = _proto(fee_tiers=[_tier(fee_pct=0.1)], competitor_avg_fee_pct=0.3)
        r = self.a.analyze([p], self.cfg)
        pos = r["protocols_detail"][0]["competitive_position"]
        self.assertIn(pos, ["cheaper", "significantly_cheaper"])

    def test_53_more_expensive_position(self):
        p = _proto(fee_tiers=[_tier(fee_pct=0.5)], competitor_avg_fee_pct=0.3)
        r = self.a.analyze([p], self.cfg)
        pos = r["protocols_detail"][0]["competitive_position"]
        self.assertIn(pos, ["more_expensive", "significantly_more_expensive"])


class TestAggregation(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolFeeStructureAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_54_cheapest_is_lowest_fee(self):
        p1 = _proto("Cheap", fee_tiers=[_tier(fee_pct=0.05)])
        p2 = _proto("Expensive", fee_tiers=[_tier(fee_pct=0.9)])
        r = self.a.analyze([p1, p2], self.cfg)
        self.assertEqual(r["cheapest_protocol"], "Cheap")

    def test_55_most_expensive_is_highest_fee(self):
        p1 = _proto("Cheap", fee_tiers=[_tier(fee_pct=0.05)])
        p2 = _proto("Expensive", fee_tiers=[_tier(fee_pct=0.9)])
        r = self.a.analyze([p1, p2], self.cfg)
        self.assertEqual(r["most_expensive"], "Expensive")

    def test_56_fee_switch_count_correct(self):
        p1 = _proto("A", fee_switch_active=True)
        p2 = _proto("B", fee_switch_active=False)
        p3 = _proto("C", fee_switch_active=True)
        r = self.a.analyze([p1, p2, p3], self.cfg)
        self.assertEqual(r["fee_switch_count"], 2)

    def test_57_average_effective_rate_correct(self):
        p1 = _proto("A", fee_tiers=[_tier(fee_pct=0.1)])
        p2 = _proto("B", fee_tiers=[_tier(fee_pct=0.3)])
        r = self.a.analyze([p1, p2], self.cfg)
        self.assertAlmostEqual(r["average_effective_rate"], 0.2, places=4)

    def test_58_single_protocol_cheapest_equals_most_expensive(self):
        p = _proto("Solo")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["cheapest_protocol"], r["most_expensive"])

    def test_59_total_revenue_is_float(self):
        p = _proto()
        r = self.a.analyze([p], self.cfg)
        self.assertIsInstance(r["total_ecosystem_revenue_30d_usd"], float)


class TestTierAnalysis(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolFeeStructureAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_60_tier_analysis_present(self):
        p = _proto()
        r = self.a.analyze([p], self.cfg)
        self.assertIn("tier_analysis", r["protocols_detail"][0])

    def test_61_tier_analysis_is_list(self):
        p = _proto()
        r = self.a.analyze([p], self.cfg)
        self.assertIsInstance(r["protocols_detail"][0]["tier_analysis"], list)

    def test_62_tier_analysis_len_matches_tiers(self):
        tiers = [_tier("a"), _tier("b"), _tier("c")]
        p = _proto(fee_tiers=tiers)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(len(r["protocols_detail"][0]["tier_analysis"]), 3)

    def test_63_tier_analysis_volume_share_sums_100(self):
        tiers = [
            _tier("a", volume_24h_usd=500.0),
            _tier("b", volume_24h_usd=500.0),
        ]
        p = _proto(fee_tiers=tiers)
        r = self.a.analyze([p], self.cfg)
        shares = [t["volume_share_pct"] for t in r["protocols_detail"][0]["tier_analysis"]]
        self.assertAlmostEqual(sum(shares), 100.0, places=1)

    def test_64_tier_analysis_has_tier_name(self):
        p = _proto()
        r = self.a.analyze([p], self.cfg)
        ta = r["protocols_detail"][0]["tier_analysis"]
        if ta:
            self.assertIn("tier_name", ta[0])


class TestProtocolFields(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolFeeStructureAnalyzer()
        self.cfg = {"log_enabled": False}
        self.detail = self.a.analyze([_proto()], self.cfg)["protocols_detail"][0]

    def test_65_name_field(self):
        self.assertEqual(self.detail["name"], "Uniswap")

    def test_66_category_field(self):
        self.assertEqual(self.detail["category"], "dex")

    def test_67_fee_tiers_count(self):
        self.assertEqual(self.detail["fee_tiers_count"], 1)

    def test_68_protocol_fee_pct_field(self):
        self.assertEqual(self.detail["protocol_fee_pct"], 0.0)

    def test_69_fee_switch_active_field(self):
        self.assertFalse(self.detail["fee_switch_active"])

    def test_70_total_volume_30d_field(self):
        self.assertEqual(self.detail["total_volume_30d_usd"], 30_000_000.0)

    def test_71_competitor_avg_fee_field(self):
        self.assertEqual(self.detail["competitor_avg_fee_pct"], 0.3)


class TestCategoryValidation(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolFeeStructureAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_72_valid_dex_category(self):
        p = _proto(category="dex")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols_detail"][0]["category"], "dex")

    def test_73_valid_lending_category(self):
        p = _proto(category="lending")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols_detail"][0]["category"], "lending")

    def test_74_invalid_category_becomes_unknown(self):
        p = _proto(category="exotic_thing")
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols_detail"][0]["category"], "unknown")

    def test_75_valid_categories_set(self):
        self.assertIn("dex", VALID_CATEGORIES)
        self.assertIn("lending", VALID_CATEGORIES)
        self.assertIn("yield", VALID_CATEGORIES)
        self.assertIn("bridge", VALID_CATEGORIES)
        self.assertIn("perps", VALID_CATEGORIES)


class TestConfigOverrides(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolFeeStructureAnalyzer()

    def test_76_custom_high_protocol_cut_threshold(self):
        cfg = {"high_protocol_cut_pct": 5.0, "log_enabled": False}
        p = _proto(protocol_fee_pct=8.0)
        r = self.a.analyze([p], cfg)
        self.assertIn(FLAG_HIGH_PROTOCOL_CUT, r["protocols_detail"][0]["flags"])

    def test_77_custom_expensive_vs_market_multiplier(self):
        cfg = {"expensive_vs_market_multiplier": 1.5, "log_enabled": False}
        p = _proto(fee_tiers=[_tier(fee_pct=0.5)], competitor_avg_fee_pct=0.3)
        r = self.a.analyze([p], cfg)
        self.assertIn(FLAG_EXPENSIVE_VS_MARKET, r["protocols_detail"][0]["flags"])

    def test_78_none_config_uses_defaults(self):
        p = _proto()
        r = self.a.analyze([p], None)
        self.assertIn("high_protocol_cut_pct", r["config_used"])

    def test_79_config_merged_with_defaults(self):
        cfg = {"log_enabled": False}
        r = self.a.analyze([_proto()], cfg)
        self.assertIn("very_competitive_ratio", r["config_used"])

    def test_80_custom_label_thresholds(self):
        # Very high competitive ratio → market_rate for avg fee
        cfg = {"very_competitive_ratio": 0.99, "competitive_ratio": 0.999,
               "market_rate_ratio": 1.001, "log_enabled": False}
        p = _proto(fee_tiers=[_tier(fee_pct=0.3)], competitor_avg_fee_pct=0.3)
        r = self.a.analyze([p], cfg)
        label = r["protocols_detail"][0]["fee_label"]
        self.assertIn(label, [LABEL_MARKET_RATE, LABEL_COMPETITIVE])


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolFeeStructureAnalyzer()
        self.cfg = {"log_enabled": False}

    def test_81_protocol_fee_clamped_above_100(self):
        p = _proto(protocol_fee_pct=150.0)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols_detail"][0]["protocol_fee_pct"], 100.0)

    def test_82_zero_competitor_avg_no_crash(self):
        p = _proto(competitor_avg_fee_pct=0.0)
        r = self.a.analyze([p], self.cfg)
        self.assertIsNotNone(r["protocols_detail"][0]["fee_label"])

    def test_83_multiple_protocols_count(self):
        protos = [_proto(name=f"P{i}") for i in range(5)]
        r = self.a.analyze(protos, self.cfg)
        self.assertEqual(len(r["protocols_detail"]), 5)

    def test_84_all_fee_switch_active(self):
        protos = [_proto(name=f"P{i}", fee_switch_active=True) for i in range(3)]
        r = self.a.analyze(protos, self.cfg)
        self.assertEqual(r["fee_switch_count"], 3)

    def test_85_no_fee_switch_active(self):
        protos = [_proto(name=f"P{i}", fee_switch_active=False) for i in range(3)]
        r = self.a.analyze(protos, self.cfg)
        self.assertEqual(r["fee_switch_count"], 0)

    def test_86_very_high_fee_very_expensive(self):
        p = _proto(fee_tiers=[_tier(fee_pct=10.0)], competitor_avg_fee_pct=0.3)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols_detail"][0]["fee_label"], LABEL_VERY_EXPENSIVE)

    def test_87_zero_fee_very_competitive(self):
        p = _proto(fee_tiers=[_tier(fee_pct=0.0)], competitor_avg_fee_pct=0.3)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["protocols_detail"][0]["fee_label"], LABEL_VERY_COMPETITIVE)

    def test_88_timestamp_is_int(self):
        r = self.a.analyze([_proto()], self.cfg)
        self.assertIsInstance(r["timestamp_utc"], int)

    def test_89_timestamp_positive(self):
        r = self.a.analyze([_proto()], self.cfg)
        self.assertGreater(r["timestamp_utc"], 0)

    def test_90_analyze_multiple_same_name(self):
        # Duplicate names should not crash
        protos = [_proto("Same"), _proto("Same")]
        r = self.a.analyze(protos, self.cfg)
        self.assertEqual(len(r["protocols_detail"]), 2)


class TestDefaultConfigConstants(unittest.TestCase):
    def test_91_default_config_has_very_competitive_ratio(self):
        self.assertIn("very_competitive_ratio", DEFAULT_CONFIG)

    def test_92_default_config_has_log_enabled(self):
        self.assertIn("log_enabled", DEFAULT_CONFIG)

    def test_93_flag_constants_distinct(self):
        flags = {FLAG_FEE_SWITCH, FLAG_HIGH_PROTOCOL_CUT,
                 FLAG_EXPENSIVE_VS_MARKET, FLAG_NO_TIERS}
        self.assertEqual(len(flags), 4)

    def test_94_log_cap_is_100(self):
        from spa_core.analytics.protocol_fee_structure_analyzer import LOG_CAP
        self.assertEqual(LOG_CAP, 100)

    def test_95_valid_categories_has_five(self):
        self.assertEqual(len(VALID_CATEGORIES), 5)


if __name__ == "__main__":
    unittest.main()
