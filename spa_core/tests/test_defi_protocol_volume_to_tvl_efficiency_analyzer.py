"""
Tests for MP-998: DeFiProtocolVolumeToTVLEfficiencyAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_volume_to_tvl_efficiency_analyzer
"""

import json
import os
import unittest
import tempfile

from spa_core.analytics.defi_protocol_volume_to_tvl_efficiency_analyzer import (
    DeFiProtocolVolumeToTVLEfficiencyAnalyzer,
    CATEGORY_BENCHMARKS,
    _clamp,
    _safe_div,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_protocol(
    name="TestDEX",
    category="dex",
    tvl=100_000_000,
    vol7=50_000_000,
    vol30=45_000_000,
    fees7=150_000,
    fees30=140_000,
    active_markets=20,
    protocol_rev_share=20.0,
    lp_rev_share=80.0,
    il_estimate=2.0,
):
    return {
        "name": name,
        "category": category,
        "total_tvl_usd": tvl,
        "daily_volume_7d_avg_usd": vol7,
        "daily_volume_30d_avg_usd": vol30,
        "daily_fees_7d_avg_usd": fees7,
        "daily_fees_30d_avg_usd": fees30,
        "active_pairs_or_markets": active_markets,
        "protocol_revenue_share_pct": protocol_rev_share,
        "lp_revenue_share_pct": lp_rev_share,
        "impermanent_loss_estimate_pct": il_estimate,
    }


class TestHelpers(unittest.TestCase):
    """T001-T010: Helper functions."""

    def test_t001_clamp_lo(self):
        self.assertEqual(_clamp(-5), 0.0)

    def test_t002_clamp_hi(self):
        self.assertEqual(_clamp(200), 100.0)

    def test_t003_clamp_mid(self):
        self.assertEqual(_clamp(50), 50.0)

    def test_t004_clamp_zero(self):
        self.assertEqual(_clamp(0), 0.0)

    def test_t005_clamp_hundred(self):
        self.assertEqual(_clamp(100), 100.0)

    def test_t006_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(10, 2), 5.0)

    def test_t007_safe_div_zero_denom(self):
        self.assertEqual(_safe_div(10, 0), 0.0)

    def test_t008_safe_div_zero_denom_default(self):
        self.assertEqual(_safe_div(10, 0, 99.0), 99.0)

    def test_t009_safe_div_zero_num(self):
        self.assertEqual(_safe_div(0, 5), 0.0)

    def test_t010_safe_div_both_zero(self):
        self.assertEqual(_safe_div(0, 0), 0.0)


class TestCategoryBenchmarks(unittest.TestCase):
    """T011-T015: Category benchmark values."""

    def test_t011_dex_benchmark(self):
        self.assertEqual(CATEGORY_BENCHMARKS["dex"], 0.5)

    def test_t012_lending_benchmark(self):
        self.assertEqual(CATEGORY_BENCHMARKS["lending"], 0.1)

    def test_t013_perps_benchmark(self):
        self.assertEqual(CATEGORY_BENCHMARKS["perps"], 2.0)

    def test_t014_options_benchmark(self):
        self.assertEqual(CATEGORY_BENCHMARKS["options"], 0.3)

    def test_t015_stablecoin_benchmark(self):
        self.assertIn("stablecoin", CATEGORY_BENCHMARKS)


class TestReturnStructure(unittest.TestCase):
    """T016-T025: Return structure validation."""

    def setUp(self):
        self.a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
        self.cfg = {"skip_log": True}

    def test_t016_returns_dict(self):
        r = self.a.analyze([make_protocol()], self.cfg)
        self.assertIsInstance(r, dict)

    def test_t017_has_protocols_key(self):
        r = self.a.analyze([make_protocol()], self.cfg)
        self.assertIn("protocols", r)

    def test_t018_has_aggregates_key(self):
        r = self.a.analyze([make_protocol()], self.cfg)
        self.assertIn("aggregates", r)

    def test_t019_has_timestamp(self):
        r = self.a.analyze([make_protocol()], self.cfg)
        self.assertIn("timestamp", r)

    def test_t020_has_version(self):
        r = self.a.analyze([make_protocol()], self.cfg)
        self.assertIn("version", r)

    def test_t021_has_module(self):
        r = self.a.analyze([make_protocol()], self.cfg)
        self.assertEqual(r["module"], "MP-998")

    def test_t022_protocols_is_list(self):
        r = self.a.analyze([make_protocol()], self.cfg)
        self.assertIsInstance(r["protocols"], list)

    def test_t023_protocols_count(self):
        r = self.a.analyze([make_protocol(), make_protocol(name="P2")], self.cfg)
        self.assertEqual(len(r["protocols"]), 2)

    def test_t024_aggregates_is_dict(self):
        r = self.a.analyze([make_protocol()], self.cfg)
        self.assertIsInstance(r["aggregates"], dict)

    def test_t025_empty_protocols(self):
        r = self.a.analyze([], self.cfg)
        self.assertEqual(len(r["protocols"]), 0)
        self.assertEqual(r["aggregates"]["total_protocols"], 0)


class TestPerProtocolFields(unittest.TestCase):
    """T026-T040: Per-protocol fields."""

    def setUp(self):
        self.a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
        self.cfg = {"skip_log": True}
        self.p = make_protocol()
        self.r = self.a.analyze([self.p], self.cfg)["protocols"][0]

    def test_t026_name(self):
        self.assertEqual(self.r["name"], "TestDEX")

    def test_t027_category(self):
        self.assertEqual(self.r["category"], "dex")

    def test_t028_volume_to_tvl_ratio_present(self):
        self.assertIn("volume_to_tvl_ratio", self.r)

    def test_t029_volume_to_tvl_ratio_value(self):
        self.assertAlmostEqual(self.r["volume_to_tvl_ratio"], 0.5, places=4)

    def test_t030_fee_to_tvl_annualized_present(self):
        self.assertIn("fee_to_tvl_annualized_pct", self.r)

    def test_t031_fee_to_tvl_annualized_value(self):
        # fees7=150k / tvl=100M * 365 * 100 = 0.0015 * 365 * 100 = 54.75%
        expected = (150_000 / 100_000_000) * 365 * 100
        self.assertAlmostEqual(self.r["fee_to_tvl_annualized_pct"], expected, places=2)

    def test_t032_lp_net_apy_present(self):
        self.assertIn("lp_net_apy_pct", self.r)

    def test_t033_capital_efficiency_score_in_range(self):
        s = self.r["capital_efficiency_score"]
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)

    def test_t034_revenue_quality_score_in_range(self):
        s = self.r["revenue_quality_score"]
        self.assertGreaterEqual(s, 0)
        self.assertLessEqual(s, 100)

    def test_t035_benchmark_velocity_dex(self):
        self.assertEqual(self.r["benchmark_velocity"], 0.5)

    def test_t036_velocity_ratio_vs_benchmark(self):
        self.assertIn("velocity_ratio_vs_benchmark", self.r)

    def test_t037_efficiency_label_present(self):
        self.assertIn("efficiency_label", self.r)

    def test_t038_flags_is_list(self):
        self.assertIsInstance(self.r["flags"], list)

    def test_t039_active_markets_preserved(self):
        self.assertEqual(self.r["active_pairs_or_markets"], 20)

    def test_t040_il_estimate_preserved(self):
        self.assertEqual(self.r["impermanent_loss_estimate_pct"], 2.0)


class TestVolumeToTVLRatio(unittest.TestCase):
    """T041-T046: volume_to_tvl_ratio computation."""

    def setUp(self):
        self.a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
        self.cfg = {"skip_log": True}

    def test_t041_ratio_calculation(self):
        p = make_protocol(tvl=200_000_000, vol7=100_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertAlmostEqual(r["volume_to_tvl_ratio"], 0.5, places=4)

    def test_t042_zero_tvl_returns_zero(self):
        p = make_protocol(tvl=0, vol7=1_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertEqual(r["volume_to_tvl_ratio"], 0.0)

    def test_t043_zero_vol_returns_zero(self):
        p = make_protocol(vol7=0)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertEqual(r["volume_to_tvl_ratio"], 0.0)

    def test_t044_high_velocity(self):
        p = make_protocol(tvl=10_000_000, vol7=50_000_000)  # 5.0 ratio
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertAlmostEqual(r["volume_to_tvl_ratio"], 5.0, places=4)

    def test_t045_perps_high_velocity(self):
        p = make_protocol(category="perps", tvl=50_000_000, vol7=200_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertAlmostEqual(r["volume_to_tvl_ratio"], 4.0, places=4)

    def test_t046_lending_low_velocity(self):
        p = make_protocol(category="lending", tvl=500_000_000, vol7=25_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertAlmostEqual(r["volume_to_tvl_ratio"], 0.05, places=4)


class TestLPNetAPY(unittest.TestCase):
    """T047-T051: LP net APY calculation."""

    def setUp(self):
        self.a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
        self.cfg = {"skip_log": True}

    def test_t047_lp_net_apy_positive(self):
        p = make_protocol(tvl=100_000_000, fees7=300_000, il_estimate=2.0)
        # fee_to_tvl = 300k/100M * 365 * 100 = 109.5%; net = 107.5%
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertGreater(r["lp_net_apy_pct"], 0)

    def test_t048_lp_net_apy_negative_when_il_high(self):
        p = make_protocol(tvl=100_000_000, fees7=100, il_estimate=50.0)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertLess(r["lp_net_apy_pct"], 0)

    def test_t049_lp_negative_yield_flag(self):
        p = make_protocol(tvl=100_000_000, fees7=100, il_estimate=50.0)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertIn("LP_NEGATIVE_YIELD", r["flags"])

    def test_t050_no_lp_negative_flag_when_positive(self):
        p = make_protocol(tvl=100_000_000, fees7=300_000, il_estimate=2.0)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertNotIn("LP_NEGATIVE_YIELD", r["flags"])

    def test_t051_zero_il_estimate(self):
        p = make_protocol(tvl=100_000_000, fees7=150_000, il_estimate=0.0)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        expected_fee_annualized = (150_000 / 100_000_000) * 365 * 100
        self.assertAlmostEqual(r["lp_net_apy_pct"], expected_fee_annualized, places=2)


class TestEfficiencyLabels(unittest.TestCase):
    """T052-T062: Efficiency label assignment."""

    def setUp(self):
        self.a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
        self.cfg = {"skip_log": True}

    def _label_for(self, velocity_ratio, score):
        return self.a._efficiency_label(velocity_ratio, score)

    def test_t052_capital_powerhouse(self):
        self.assertEqual(self._label_for(2.1, 85), "CAPITAL_POWERHOUSE")

    def test_t053_powerhouse_boundary_velocity(self):
        # 2.0 is NOT > 2.0, so not powerhouse
        self.assertNotEqual(self._label_for(2.0, 85), "CAPITAL_POWERHOUSE")

    def test_t054_powerhouse_boundary_score(self):
        # score=80 is NOT > 80
        self.assertNotEqual(self._label_for(2.1, 80), "CAPITAL_POWERHOUSE")

    def test_t055_high_efficiency(self):
        self.assertEqual(self._label_for(1.6, 75), "HIGH_EFFICIENCY")

    def test_t056_high_efficiency_boundary(self):
        # 1.5 is NOT > 1.5 so falls to AVERAGE
        self.assertNotEqual(self._label_for(1.5, 75), "HIGH_EFFICIENCY")

    def test_t057_average_label(self):
        self.assertEqual(self._label_for(1.0, 60), "AVERAGE")

    def test_t058_average_boundary_lo(self):
        self.assertEqual(self._label_for(0.8, 60), "AVERAGE")

    def test_t059_underperforming(self):
        self.assertEqual(self._label_for(0.6, 40), "UNDERPERFORMING")

    def test_t060_capital_idle(self):
        self.assertEqual(self._label_for(0.2, 10), "CAPITAL_IDLE")

    def test_t061_capital_idle_zero_velocity(self):
        self.assertEqual(self._label_for(0.0, 0), "CAPITAL_IDLE")

    def test_t062_underperforming_boundary_hi(self):
        # 0.8 is AVERAGE
        self.assertEqual(self._label_for(0.8, 50), "AVERAGE")


class TestFlags(unittest.TestCase):
    """T063-T080: Flag detection."""

    def setUp(self):
        self.a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
        self.cfg = {"skip_log": True}

    def test_t063_above_benchmark_flag(self):
        p = make_protocol(category="dex", tvl=100_000_000, vol7=60_000_000)
        # velocity = 0.6 > 0.5 benchmark → ABOVE_BENCHMARK
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertIn("ABOVE_BENCHMARK", r["flags"])

    def test_t064_no_above_benchmark_below(self):
        p = make_protocol(category="dex", tvl=100_000_000, vol7=40_000_000)
        # velocity = 0.4 < 0.5 benchmark
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertNotIn("ABOVE_BENCHMARK", r["flags"])

    def test_t065_below_benchmark_flag(self):
        p = make_protocol(category="dex", tvl=100_000_000, vol7=20_000_000)
        # velocity = 0.2 < 0.5*0.5=0.25 → BELOW_BENCHMARK
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertIn("BELOW_BENCHMARK", r["flags"])

    def test_t066_no_below_benchmark_when_above(self):
        p = make_protocol(category="dex", tvl=100_000_000, vol7=60_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertNotIn("BELOW_BENCHMARK", r["flags"])

    def test_t067_high_fee_generation_flag(self):
        # fees7/tvl * 365 * 100 > 30%
        # 30% / 365 / 100 * tvl = 0.0008219 * tvl
        # fees7 = 0.0008219 * 100M = 82,191
        p = make_protocol(tvl=100_000_000, fees7=100_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertIn("HIGH_FEE_GENERATION", r["flags"])

    def test_t068_no_high_fee_flag_when_low(self):
        p = make_protocol(tvl=100_000_000, fees7=1_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertNotIn("HIGH_FEE_GENERATION", r["flags"])

    def test_t069_lp_negative_yield_flag(self):
        p = make_protocol(tvl=100_000_000, fees7=10, il_estimate=50.0)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertIn("LP_NEGATIVE_YIELD", r["flags"])

    def test_t070_volume_declining_flag(self):
        # vol30 < vol7 * 0.7 → VOLUME_DECLINING
        p = make_protocol(vol7=100_000_000, vol30=60_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertIn("VOLUME_DECLINING", r["flags"])

    def test_t071_no_volume_declining_flag_when_stable(self):
        p = make_protocol(vol7=100_000_000, vol30=90_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertNotIn("VOLUME_DECLINING", r["flags"])

    def test_t072_concentrated_volume_flag(self):
        p = make_protocol(active_markets=3, vol7=50_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertIn("CONCENTRATED_VOLUME", r["flags"])

    def test_t073_no_concentrated_flag_when_many_markets(self):
        p = make_protocol(active_markets=20, vol7=50_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertNotIn("CONCENTRATED_VOLUME", r["flags"])

    def test_t074_concentrated_flag_boundary(self):
        # active_markets=4 (< 5) → flag
        p = make_protocol(active_markets=4, vol7=10_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertIn("CONCENTRATED_VOLUME", r["flags"])

    def test_t075_concentrated_flag_boundary_5(self):
        # active_markets=5 is NOT < 5, so no flag
        p = make_protocol(active_markets=5, vol7=10_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertNotIn("CONCENTRATED_VOLUME", r["flags"])

    def test_t076_above_and_high_fee_combo(self):
        p = make_protocol(tvl=100_000_000, vol7=80_000_000, fees7=200_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertIn("ABOVE_BENCHMARK", r["flags"])
        self.assertIn("HIGH_FEE_GENERATION", r["flags"])

    def test_t077_flags_list_empty_when_all_normal(self):
        # Zero vol, zero fees → below_benchmark; also low fee
        p = make_protocol(tvl=100_000_000, vol7=0, fees7=0, il_estimate=0.0, active_markets=20)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        # Below benchmark because velocity=0 < 0.5*0.5=0.25
        self.assertIn("BELOW_BENCHMARK", r["flags"])

    def test_t078_perps_above_benchmark(self):
        # perps benchmark = 2.0; velocity = 5.0 → ABOVE_BENCHMARK
        p = make_protocol(category="perps", tvl=10_000_000, vol7=50_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertIn("ABOVE_BENCHMARK", r["flags"])

    def test_t079_lending_below_benchmark(self):
        # lending benchmark=0.1; velocity=0.01 → BELOW_BENCHMARK
        p = make_protocol(category="lending", tvl=1_000_000_000, vol7=10_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertIn("BELOW_BENCHMARK", r["flags"])

    def test_t080_declining_volume_30d_zero(self):
        # vol30=0 → no declining flag (vol30=0 is not < vol7*0.7 in a useful sense)
        p = make_protocol(vol7=100_000_000, vol30=0)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        # vol30=0 < vol7*0.7 → actually triggers the flag
        # The check is: vol30 > 0 AND vol30 < vol7 * 0.7 → vol30=0 does NOT satisfy vol30>0
        self.assertNotIn("VOLUME_DECLINING", r["flags"])


class TestAggregates(unittest.TestCase):
    """T081-T090: Aggregate statistics."""

    def setUp(self):
        self.a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
        self.cfg = {"skip_log": True}

    def test_t081_empty_aggregates(self):
        r = self.a.analyze([], self.cfg)
        agg = r["aggregates"]
        self.assertIsNone(agg["most_efficient"])
        self.assertIsNone(agg["least_efficient"])
        self.assertEqual(agg["avg_capital_efficiency"], 0.0)
        self.assertEqual(agg["powerhouse_count"], 0)
        self.assertEqual(agg["idle_count"], 0)
        self.assertEqual(agg["total_protocols"], 0)

    def test_t082_single_protocol_aggregates(self):
        r = self.a.analyze([make_protocol(name="OnlyOne")], self.cfg)
        agg = r["aggregates"]
        self.assertEqual(agg["most_efficient"], "OnlyOne")
        self.assertEqual(agg["least_efficient"], "OnlyOne")
        self.assertEqual(agg["total_protocols"], 1)

    def test_t083_most_efficient_identified(self):
        p1 = make_protocol(name="Fast", tvl=10_000_000, vol7=100_000_000)
        p2 = make_protocol(name="Slow", tvl=100_000_000, vol7=1_000_000)
        r = self.a.analyze([p1, p2], self.cfg)
        self.assertEqual(r["aggregates"]["most_efficient"], "Fast")

    def test_t084_least_efficient_identified(self):
        p1 = make_protocol(name="Fast", tvl=10_000_000, vol7=100_000_000)
        p2 = make_protocol(name="Slow", tvl=100_000_000, vol7=1_000_000)
        r = self.a.analyze([p1, p2], self.cfg)
        self.assertEqual(r["aggregates"]["least_efficient"], "Slow")

    def test_t085_avg_capital_efficiency_two_protocols(self):
        p1 = make_protocol(name="A", tvl=10_000_000, vol7=100_000_000)
        p2 = make_protocol(name="B", tvl=100_000_000, vol7=1_000_000)
        r = self.a.analyze([p1, p2], self.cfg)
        scores = [pr["capital_efficiency_score"] for pr in r["protocols"]]
        expected_avg = round(sum(scores) / 2, 2)
        self.assertAlmostEqual(r["aggregates"]["avg_capital_efficiency"], expected_avg, places=1)

    def test_t086_powerhouse_count(self):
        # velocity_ratio>2 and score>80 → CAPITAL_POWERHOUSE
        p1 = make_protocol(name="Power", category="dex", tvl=10_000_000, vol7=200_000_000)
        p2 = make_protocol(name="Slow")
        r = self.a.analyze([p1, p2], self.cfg)
        # p1: velocity=20, ratio=40, score likely 100 → CAPITAL_POWERHOUSE
        self.assertGreaterEqual(r["aggregates"]["powerhouse_count"], 1)

    def test_t087_idle_count(self):
        p = make_protocol(name="Idle", tvl=100_000_000, vol7=1_000)
        r = self.a.analyze([p], self.cfg)
        self.assertGreaterEqual(r["aggregates"]["idle_count"], 1)

    def test_t088_total_protocols_count(self):
        protocols = [make_protocol(name=f"P{i}") for i in range(5)]
        r = self.a.analyze(protocols, self.cfg)
        self.assertEqual(r["aggregates"]["total_protocols"], 5)

    def test_t089_powerhouse_count_zero_by_default(self):
        p = make_protocol(tvl=100_000_000, vol7=10_000_000)
        r = self.a.analyze([p], self.cfg)
        # velocity=0.1, ratio=0.2, label=CAPITAL_IDLE
        self.assertEqual(r["aggregates"]["powerhouse_count"], 0)

    def test_t090_idle_count_zero_when_efficient(self):
        p = make_protocol(category="dex", tvl=10_000_000, vol7=200_000_000)
        r = self.a.analyze([p], self.cfg)
        self.assertEqual(r["aggregates"]["idle_count"], 0)


class TestCategoryHandling(unittest.TestCase):
    """T091-T096: Category-specific benchmark handling."""

    def setUp(self):
        self.a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
        self.cfg = {"skip_log": True}

    def test_t091_options_category(self):
        p = make_protocol(category="options", tvl=50_000_000, vol7=15_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertEqual(r["benchmark_velocity"], 0.3)

    def test_t092_lending_category(self):
        p = make_protocol(category="lending", tvl=100_000_000, vol7=15_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertEqual(r["benchmark_velocity"], 0.1)

    def test_t093_perps_category(self):
        p = make_protocol(category="perps", tvl=100_000_000, vol7=400_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertEqual(r["benchmark_velocity"], 2.0)

    def test_t094_unknown_category_uses_default(self):
        p = make_protocol(category="exotic", tvl=100_000_000, vol7=40_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertEqual(r["benchmark_velocity"], 0.2)

    def test_t095_category_uppercase_normalized(self):
        p = make_protocol(category="DEX")
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertEqual(r["category"], "dex")

    def test_t096_stablecoin_category(self):
        p = make_protocol(category="stablecoin", tvl=5_000_000_000, vol7=250_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertEqual(r["benchmark_velocity"], 0.05)


class TestRingBufferLog(unittest.TestCase):
    """T097-T105: Ring-buffer log and atomic write."""

    def _make_cfg(self, tmpdir, cap=100):
        return {"data_dir": tmpdir, "log_cap": cap}

    def test_t097_creates_log_file(self):
        with tempfile.TemporaryDirectory() as d:
            a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
            a.analyze([make_protocol()], self._make_cfg(d))
            self.assertTrue(os.path.exists(os.path.join(d, "volume_tvl_efficiency_log.json")))

    def test_t098_log_is_list(self):
        with tempfile.TemporaryDirectory() as d:
            a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
            a.analyze([make_protocol()], self._make_cfg(d))
            with open(os.path.join(d, "volume_tvl_efficiency_log.json")) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)

    def test_t099_log_entry_has_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
            a.analyze([make_protocol()], self._make_cfg(d))
            with open(os.path.join(d, "volume_tvl_efficiency_log.json")) as f:
                data = json.load(f)
            self.assertIn("timestamp", data[0])

    def test_t100_log_entry_has_avg_efficiency(self):
        with tempfile.TemporaryDirectory() as d:
            a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
            a.analyze([make_protocol()], self._make_cfg(d))
            with open(os.path.join(d, "volume_tvl_efficiency_log.json")) as f:
                data = json.load(f)
            self.assertIn("avg_capital_efficiency", data[0])

    def test_t101_log_accumulates_entries(self):
        with tempfile.TemporaryDirectory() as d:
            a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
            cfg = self._make_cfg(d)
            a.analyze([make_protocol()], cfg)
            a.analyze([make_protocol()], cfg)
            a.analyze([make_protocol()], cfg)
            with open(os.path.join(d, "volume_tvl_efficiency_log.json")) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)

    def test_t102_ring_buffer_cap_enforced(self):
        with tempfile.TemporaryDirectory() as d:
            a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
            cfg = self._make_cfg(d, cap=3)
            for _ in range(5):
                a.analyze([make_protocol()], cfg)
            with open(os.path.join(d, "volume_tvl_efficiency_log.json")) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)

    def test_t103_skip_log_no_file_created(self):
        with tempfile.TemporaryDirectory() as d:
            a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
            cfg = {"data_dir": d, "skip_log": True}
            a.analyze([make_protocol()], cfg)
            self.assertFalse(
                os.path.exists(os.path.join(d, "volume_tvl_efficiency_log.json"))
            )

    def test_t104_no_tmp_file_left_after_write(self):
        with tempfile.TemporaryDirectory() as d:
            a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
            cfg = self._make_cfg(d)
            a.analyze([make_protocol()], cfg)
            tmp = os.path.join(d, "volume_tvl_efficiency_log.json.tmp")
            self.assertFalse(os.path.exists(tmp))

    def test_t105_log_entry_total_protocols(self):
        with tempfile.TemporaryDirectory() as d:
            a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
            a.analyze([make_protocol(), make_protocol(name="P2")], self._make_cfg(d))
            with open(os.path.join(d, "volume_tvl_efficiency_log.json")) as f:
                data = json.load(f)
            self.assertEqual(data[0]["total_protocols"], 2)


class TestEdgeCases(unittest.TestCase):
    """T106-T115: Edge cases and robustness."""

    def setUp(self):
        self.a = DeFiProtocolVolumeToTVLEfficiencyAnalyzer()
        self.cfg = {"skip_log": True}

    def test_t106_missing_name_defaults(self):
        p = {"category": "dex", "total_tvl_usd": 100_000_000, "daily_volume_7d_avg_usd": 50_000_000}
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertEqual(r["name"], "unknown")

    def test_t107_all_zero_protocol(self):
        p = make_protocol(tvl=0, vol7=0, fees7=0)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertEqual(r["volume_to_tvl_ratio"], 0.0)
        self.assertEqual(r["fee_to_tvl_ratio_daily"], 0.0)

    def test_t108_very_high_tvl(self):
        p = make_protocol(tvl=100_000_000_000, vol7=1_000_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertAlmostEqual(r["volume_to_tvl_ratio"], 0.01, places=4)

    def test_t109_score_never_below_zero(self):
        p = make_protocol(tvl=0, vol7=0, fees7=0)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertGreaterEqual(r["capital_efficiency_score"], 0)

    def test_t110_score_never_above_100(self):
        p = make_protocol(tvl=1, vol7=1_000_000_000)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertLessEqual(r["capital_efficiency_score"], 100)

    def test_t111_revenue_quality_never_below_zero(self):
        p = make_protocol(protocol_rev_share=0)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertGreaterEqual(r["revenue_quality_score"], 0)

    def test_t112_revenue_quality_never_above_100(self):
        p = make_protocol(protocol_rev_share=100)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertLessEqual(r["revenue_quality_score"], 100)

    def test_t113_many_markets_bonus(self):
        p_few = make_protocol(active_markets=1, vol7=50_000_000)
        p_many = make_protocol(active_markets=50, vol7=50_000_000)
        r_few = self.a.analyze([p_few], self.cfg)["protocols"][0]
        r_many = self.a.analyze([p_many], self.cfg)["protocols"][0]
        self.assertGreaterEqual(r_many["capital_efficiency_score"], r_few["capital_efficiency_score"])

    def test_t114_float_inputs(self):
        p = make_protocol(tvl=1.5e8, vol7=7.5e7)
        r = self.a.analyze([p], self.cfg)["protocols"][0]
        self.assertAlmostEqual(r["volume_to_tvl_ratio"], 0.5, places=4)

    def test_t115_multiple_identical_protocols(self):
        protocols = [make_protocol(name=f"P{i}") for i in range(10)]
        r = self.a.analyze(protocols, self.cfg)
        self.assertEqual(len(r["protocols"]), 10)
        self.assertEqual(r["aggregates"]["total_protocols"], 10)


if __name__ == "__main__":
    unittest.main()
