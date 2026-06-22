"""
Tests for MP-703: LiquidityIncentiveAnalyzer
≥65 unittest tests covering all specified cases.
Run: python3 -m unittest spa_core.tests.test_liquidity_incentive_analyzer -v
"""

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.liquidity_incentive_analyzer import (
    MAX_ENTRIES,
    IncentiveProgram,
    LiquidityIncentiveAnalyzer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_analyzer(tmp_dir=None):
    if tmp_dir:
        data_file = Path(tmp_dir) / "liquidity_incentive_log.json"
    else:
        data_file = Path(tempfile.mktemp(suffix=".json"))
    return LiquidityIncentiveAnalyzer(data_file=data_file)


def simple_program(
    analyzer=None,
    protocol="TestProto",
    pool_name="ETH/USDC",
    tvl_usd=10_000_000,
    base_apy=5.0,
    reward_apy=3.0,
    reward_token_price_usd=2.0,
    daily_emission_usd=1_000,
    treasury_usd=500_000,
):
    if analyzer is None:
        analyzer = make_analyzer()
    return analyzer.analyze(
        protocol=protocol,
        pool_name=pool_name,
        tvl_usd=tvl_usd,
        base_apy=base_apy,
        reward_apy=reward_apy,
        reward_token_price_usd=reward_token_price_usd,
        daily_emission_usd=daily_emission_usd,
        treasury_usd=treasury_usd,
    )


# ---------------------------------------------------------------------------
# IncentiveProgram dataclass
# ---------------------------------------------------------------------------

class TestIncentiveProgramDataclass(unittest.TestCase):

    def test_fields_present(self):
        a = make_analyzer()
        p = simple_program(a)
        self.assertIsInstance(p, IncentiveProgram)
        self.assertEqual(p.protocol, "TestProto")
        self.assertEqual(p.pool_name, "ETH/USDC")


# ---------------------------------------------------------------------------
# real_yield_ratio
# ---------------------------------------------------------------------------

class TestRealYieldRatio(unittest.TestCase):

    def setUp(self):
        self.a = make_analyzer()

    def test_base5_reward0_ratio_is_1(self):
        # base=5, reward=0 → total=5 → ratio=1.0
        p = self.a.analyze("P", "pool", 1e7, 5.0, 0.0, 2.0, 1000, 500_000)
        self.assertAlmostEqual(p.real_yield_ratio, 1.0, places=6)

    def test_base0_reward5_ratio_is_0(self):
        # base=0, reward=5 → total=5 → ratio=0
        p = self.a.analyze("P", "pool", 1e7, 0.0, 5.0, 2.0, 1000, 500_000)
        self.assertAlmostEqual(p.real_yield_ratio, 0.0, places=6)

    def test_base5_reward5_ratio_is_half(self):
        # base=5, reward=5 → total=10 → ratio=0.5
        p = self.a.analyze("P", "pool", 1e7, 5.0, 5.0, 2.0, 1000, 500_000)
        self.assertAlmostEqual(p.real_yield_ratio, 0.5, places=6)

    def test_base3_reward7_ratio(self):
        p = self.a.analyze("P", "pool", 1e7, 3.0, 7.0, 2.0, 1000, 500_000)
        self.assertAlmostEqual(p.real_yield_ratio, 0.3, places=6)

    def test_both_zero_ratio_is_zero(self):
        p = self.a.analyze("P", "pool", 1e7, 0.0, 0.0, 2.0, 0.0, 500_000)
        self.assertAlmostEqual(p.real_yield_ratio, 0.0, places=6)

    def test_total_apy_is_sum(self):
        p = self.a.analyze("P", "pool", 1e7, 4.0, 6.0, 2.0, 1000, 500_000)
        self.assertAlmostEqual(p.total_apy, 10.0, places=6)


# ---------------------------------------------------------------------------
# emission_sustainability_days
# ---------------------------------------------------------------------------

class TestEmissionSustainabilityDays(unittest.TestCase):

    def setUp(self):
        self.a = make_analyzer()

    def test_treasury_0_emission_100_is_zero(self):
        p = self.a.analyze("P", "pool", 1e7, 5.0, 3.0, 2.0, 100.0, 0.0)
        self.assertAlmostEqual(p.emission_sustainability_days, 0.0, places=6)

    def test_emission_zero_returns_9999(self):
        p = self.a.analyze("P", "pool", 1e7, 5.0, 0.0, 2.0, 0.0, 500_000)
        self.assertAlmostEqual(p.emission_sustainability_days, 9999.0, places=6)

    def test_standard_formula(self):
        # treasury=30000, emission=1000/day → 30 days
        p = self.a.analyze("P", "pool", 1e7, 5.0, 3.0, 2.0, 1000.0, 30_000.0)
        self.assertAlmostEqual(p.emission_sustainability_days, 30.0, places=4)

    def test_large_treasury(self):
        # treasury=365000, emission=1000 → 365 days
        p = self.a.analyze("P", "pool", 1e7, 5.0, 3.0, 2.0, 1000.0, 365_000.0)
        self.assertAlmostEqual(p.emission_sustainability_days, 365.0, places=4)

    def test_small_emission(self):
        # treasury=1000, emission=10 → 100 days
        p = self.a.analyze("P", "pool", 1e7, 5.0, 3.0, 2.0, 10.0, 1_000.0)
        self.assertAlmostEqual(p.emission_sustainability_days, 100.0, places=4)


# ---------------------------------------------------------------------------
# mercenary_risk
# ---------------------------------------------------------------------------

class TestMercenaryRisk(unittest.TestCase):

    def setUp(self):
        self.a = make_analyzer()

    def test_fully_organic_risk_is_0(self):
        # base=5, reward=0 → ratio=1.0 → risk=0
        p = self.a.analyze("P", "pool", 1e7, 5.0, 0.0, 2.0, 0.0, 500_000)
        self.assertAlmostEqual(p.mercenary_risk, 0.0, places=6)

    def test_fully_emission_risk_is_100(self):
        # base=0, reward=5 → ratio=0 → risk=100
        p = self.a.analyze("P", "pool", 1e7, 0.0, 5.0, 2.0, 1000, 500_000)
        self.assertAlmostEqual(p.mercenary_risk, 100.0, places=6)

    def test_half_half_risk_is_50(self):
        p = self.a.analyze("P", "pool", 1e7, 5.0, 5.0, 2.0, 1000, 500_000)
        self.assertAlmostEqual(p.mercenary_risk, 50.0, places=6)

    def test_30pct_organic_risk_is_70(self):
        p = self.a.analyze("P", "pool", 1e7, 3.0, 7.0, 2.0, 1000, 500_000)
        self.assertAlmostEqual(p.mercenary_risk, 70.0, places=5)


# ---------------------------------------------------------------------------
# quality_label — all 4 paths
# ---------------------------------------------------------------------------

class TestQualityLabel(unittest.TestCase):

    def setUp(self):
        self.a = make_analyzer()

    def test_organic_when_ratio_gte_0_7(self):
        # base=7, reward=3 → ratio=0.7 → ORGANIC
        p = self.a.analyze("P", "pool", 1e7, 7.0, 3.0, 2.0, 1000, 500_000)
        self.assertEqual(p.quality_label, "ORGANIC")

    def test_organic_when_ratio_above_0_7(self):
        # base=8, reward=2 → ratio=0.8 → ORGANIC
        p = self.a.analyze("P", "pool", 1e7, 8.0, 2.0, 2.0, 1000, 500_000)
        self.assertEqual(p.quality_label, "ORGANIC")

    def test_healthy_when_ratio_gte_0_4_and_sustainability_above_180(self):
        # base=4, reward=6 → ratio=0.4; treasury=190000, emission=1000 → 190 days
        p = self.a.analyze("P", "pool", 1e7, 4.0, 6.0, 2.0, 1000.0, 190_000.0)
        self.assertEqual(p.quality_label, "HEALTHY")

    def test_not_healthy_when_sustainability_lte_180(self):
        # base=4, reward=6 → ratio=0.4; treasury=180000, emission=1000 → exactly 180 days
        p = self.a.analyze("P", "pool", 1e7, 4.0, 6.0, 2.0, 1000.0, 180_000.0)
        # sustainability = 180, NOT > 180 → not HEALTHY
        self.assertNotEqual(p.quality_label, "HEALTHY")

    def test_emission_dependent_when_ratio_gte_0_2(self):
        # base=2, reward=8 → ratio=0.2 → EMISSION_DEPENDENT
        p = self.a.analyze("P", "pool", 1e7, 2.0, 8.0, 2.0, 1000, 500_000)
        self.assertEqual(p.quality_label, "EMISSION_DEPENDENT")

    def test_emission_dependent_ratio_0_5(self):
        # base=5, reward=5 → ratio=0.5; sustainability < 180 (treasury=100000, emission=1000 → 100d)
        p = self.a.analyze("P", "pool", 1e7, 5.0, 5.0, 2.0, 1000.0, 100_000.0)
        self.assertEqual(p.quality_label, "EMISSION_DEPENDENT")

    def test_mercenary_when_ratio_below_0_2(self):
        # base=1, reward=9 → ratio=0.1 → MERCENARY
        p = self.a.analyze("P", "pool", 1e7, 1.0, 9.0, 2.0, 1000, 500_000)
        self.assertEqual(p.quality_label, "MERCENARY")

    def test_mercenary_all_emissions(self):
        p = self.a.analyze("P", "pool", 1e7, 0.0, 10.0, 2.0, 1000, 500_000)
        self.assertEqual(p.quality_label, "MERCENARY")


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------

class TestWarnings(unittest.TestCase):

    def setUp(self):
        self.a = make_analyzer()

    def test_sustainability_warning_when_lt_30_days(self):
        # treasury=29000, emission=1000 → 29 days < 30
        p = self.a.analyze("P", "pool", 1e7, 5.0, 3.0, 2.0, 1000.0, 29_000.0)
        self.assertIn("emissions run out in <30 days", p.warnings)

    def test_no_sustainability_warning_when_gte_30_days(self):
        # treasury=30000, emission=1000 → 30 days (not < 30)
        p = self.a.analyze("P", "pool", 1e7, 5.0, 3.0, 2.0, 1000.0, 30_000.0)
        self.assertNotIn("emissions run out in <30 days", p.warnings)

    def test_mercenary_risk_warning_when_gt_80(self):
        # base=0, reward=10 → ratio=0 → risk=100 > 80
        p = self.a.analyze("P", "pool", 1e7, 0.0, 10.0, 2.0, 1000, 500_000)
        self.assertIn("high mercenary risk", p.warnings)

    def test_no_mercenary_warning_when_lte_80(self):
        # base=5, reward=5 → ratio=0.5 → risk=50
        p = self.a.analyze("P", "pool", 1e7, 5.0, 5.0, 2.0, 1000, 500_000)
        self.assertNotIn("high mercenary risk", p.warnings)

    def test_reward_dominates_warning_when_reward_gt_base_times_5(self):
        # base=2, reward=11 → 11 > 2*5=10 → reward dominates
        p = self.a.analyze("P", "pool", 1e7, 2.0, 11.0, 2.0, 1000, 500_000)
        self.assertIn("reward dominates", p.warnings)

    def test_no_reward_dominates_when_reward_lte_base_times_5(self):
        # base=2, reward=10 → 10 == 2*5 → NOT > base*5
        p = self.a.analyze("P", "pool", 1e7, 2.0, 10.0, 2.0, 1000, 500_000)
        self.assertNotIn("reward dominates", p.warnings)

    def test_reward_dominates_when_base_zero_and_reward_positive(self):
        # base=0, reward=5 → reward dominates (special case)
        p = self.a.analyze("P", "pool", 1e7, 0.0, 5.0, 2.0, 1000, 500_000)
        self.assertIn("reward dominates", p.warnings)

    def test_no_warnings_when_all_clear(self):
        # treasury=365000, emission=1000 → 365 days; base=7, reward=1 → ratio=0.875 → risk=12.5
        p = self.a.analyze("P", "pool", 1e7, 7.0, 1.0, 2.0, 1000.0, 365_000.0)
        self.assertNotIn("emissions run out in <30 days", p.warnings)
        self.assertNotIn("high mercenary risk", p.warnings)
        self.assertNotIn("reward dominates", p.warnings)

    def test_multiple_warnings_coexist(self):
        # treasury=1000, emission=1000 → 1 day; base=0, reward=10 → risk=100
        p = self.a.analyze("P", "pool", 1e7, 0.0, 10.0, 2.0, 1000.0, 1_000.0)
        self.assertIn("emissions run out in <30 days", p.warnings)
        self.assertIn("high mercenary risk", p.warnings)
        self.assertIn("reward dominates", p.warnings)


# ---------------------------------------------------------------------------
# tvl_per_emission_dollar
# ---------------------------------------------------------------------------

class TestTvlPerEmissionDollar(unittest.TestCase):

    def setUp(self):
        self.a = make_analyzer()

    def test_standard_formula(self):
        # tvl=10M, emission=1000/day → 10000 TVL per emission dollar
        p = self.a.analyze("P", "pool", 10_000_000, 5.0, 3.0, 2.0, 1000.0, 500_000)
        self.assertAlmostEqual(p.tvl_per_emission_dollar, 10000.0, places=4)

    def test_emission_zero_returns_zero(self):
        p = self.a.analyze("P", "pool", 10_000_000, 5.0, 0.0, 2.0, 0.0, 500_000)
        self.assertAlmostEqual(p.tvl_per_emission_dollar, 0.0, places=6)

    def test_large_emission(self):
        # tvl=1M, emission=100000 → ratio=10
        p = self.a.analyze("P", "pool", 1_000_000, 5.0, 3.0, 2.0, 100_000.0, 500_000)
        self.assertAlmostEqual(p.tvl_per_emission_dollar, 10.0, places=4)


# ---------------------------------------------------------------------------
# incentive_roi
# ---------------------------------------------------------------------------

class TestIncentiveROI(unittest.TestCase):

    def setUp(self):
        self.a = make_analyzer()

    def test_roi_formula(self):
        # emission_rate_annual = (1000 / 10_000_000) * 365 * 100 = 0.365
        # roi = 5.0 / 0.365 ≈ 13.699
        p = self.a.analyze("P", "pool", 10_000_000, 5.0, 3.0, 2.0, 1000.0, 500_000)
        expected = 5.0 / ((1000.0 / 10_000_000) * 365 * 100)
        self.assertAlmostEqual(p.incentive_roi, expected, places=4)

    def test_roi_zero_when_emission_zero(self):
        p = self.a.analyze("P", "pool", 10_000_000, 5.0, 0.0, 2.0, 0.0, 500_000)
        self.assertAlmostEqual(p.incentive_roi, 0.0, places=6)

    def test_roi_zero_when_tvl_zero(self):
        p = self.a.analyze("P", "pool", 0.0, 5.0, 3.0, 2.0, 1000.0, 500_000)
        self.assertAlmostEqual(p.incentive_roi, 0.0, places=6)

    def test_roi_zero_when_base_apy_zero(self):
        p = self.a.analyze("P", "pool", 10_000_000, 0.0, 3.0, 2.0, 1000.0, 500_000)
        self.assertAlmostEqual(p.incentive_roi, 0.0, places=6)


# ---------------------------------------------------------------------------
# compare_pools
# ---------------------------------------------------------------------------

class TestComparePools(unittest.TestCase):

    def setUp(self):
        self.a = make_analyzer()

    def _prog(self, base, reward, name="pool"):
        return self.a.analyze("P", name, 1e7, base, reward, 2.0, 1000, 500_000)

    def test_sorted_by_real_yield_ratio_descending(self):
        p1 = self._prog(2, 8, "low")    # ratio=0.2
        p2 = self._prog(7, 3, "high")   # ratio=0.7
        p3 = self._prog(5, 5, "mid")    # ratio=0.5
        result = self.a.compare_pools([p1, p2, p3])
        self.assertEqual(result[0].pool_name, "high")
        self.assertEqual(result[1].pool_name, "mid")
        self.assertEqual(result[2].pool_name, "low")

    def test_returns_list(self):
        p = self._prog(5, 5)
        result = self.a.compare_pools([p])
        self.assertIsInstance(result, list)

    def test_empty_list(self):
        result = self.a.compare_pools([])
        self.assertEqual(result, [])

    def test_single_program(self):
        p = self._prog(5, 5)
        result = self.a.compare_pools([p])
        self.assertEqual(len(result), 1)

    def test_all_same_ratio_preserves_order(self):
        # Two with same ratio=0.5 — result length should be 2
        p1 = self._prog(5, 5, "a")
        p2 = self._prog(5, 5, "b")
        result = self.a.compare_pools([p1, p2])
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# find_best_risk_adjusted
# ---------------------------------------------------------------------------

class TestFindBestRiskAdjusted(unittest.TestCase):

    def setUp(self):
        self.a = make_analyzer()

    def _prog(self, base, reward, name="pool"):
        return self.a.analyze("P", name, 1e7, base, reward, 2.0, 1000, 500_000)

    def test_picks_highest_base_per_risk(self):
        # p1: base=2, reward=8 → ratio=0.2, risk=80, score=2/80=0.025
        # p2: base=7, reward=3 → ratio=0.7, risk=30, score=7/30≈0.233
        # p3: base=3, reward=7 → ratio=0.3, risk=70, score=3/70≈0.043
        p1 = self._prog(2, 8, "low")
        p2 = self._prog(7, 3, "high")
        p3 = self._prog(3, 7, "mid")
        best = self.a.find_best_risk_adjusted([p1, p2, p3])
        self.assertEqual(best.pool_name, "high")

    def test_returns_none_for_empty(self):
        result = self.a.find_best_risk_adjusted([])
        self.assertIsNone(result)

    def test_single_program_returned(self):
        p = self._prog(5, 5)
        result = self.a.find_best_risk_adjusted([p])
        self.assertIs(result, p)

    def test_fully_organic_wins_over_mixed(self):
        # p1: base=10, reward=0 → risk=0 → score = 10/max(0,1) = 10
        # p2: base=20, reward=20 → risk=50 → score = 20/50 = 0.4
        p1 = self._prog(10, 0, "organic")
        p2 = self._prog(20, 20, "mixed")
        best = self.a.find_best_risk_adjusted([p1, p2])
        self.assertEqual(best.pool_name, "organic")


# ---------------------------------------------------------------------------
# Edge cases: tvl=0, all zeros
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.a = make_analyzer()

    def test_all_zeros(self):
        p = self.a.analyze("P", "pool", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(p.real_yield_ratio, 0.0, places=6)
        self.assertAlmostEqual(p.emission_sustainability_days, 9999.0, places=4)
        self.assertAlmostEqual(p.mercenary_risk, 100.0, places=6)
        self.assertAlmostEqual(p.tvl_per_emission_dollar, 0.0, places=6)
        self.assertAlmostEqual(p.incentive_roi, 0.0, places=6)

    def test_tvl_zero_tvl_per_emission_irrelevant(self):
        p = self.a.analyze("P", "pool", 0.0, 5.0, 3.0, 2.0, 1000.0, 500_000)
        self.assertAlmostEqual(p.tvl_per_emission_dollar, 0.0, places=6)

    def test_tvl_zero_incentive_roi_zero(self):
        p = self.a.analyze("P", "pool", 0.0, 5.0, 3.0, 2.0, 1000.0, 500_000)
        self.assertAlmostEqual(p.incentive_roi, 0.0, places=6)

    def test_quality_label_is_string(self):
        p = simple_program()
        self.assertIsInstance(p.quality_label, str)

    def test_warnings_is_list(self):
        p = simple_program()
        self.assertIsInstance(p.warnings, list)


# ---------------------------------------------------------------------------
# save_results / load_history / ring-buffer
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.a = make_analyzer(self.tmp_dir)

    def test_load_history_empty_when_no_file(self):
        self.assertEqual(self.a.load_history(), [])

    def test_save_creates_file(self):
        p = simple_program(self.a)
        self.a.save_results(p)
        self.assertTrue(self.a.data_file.exists())

    def test_save_and_load_round_trip(self):
        p = self.a.analyze("Curve", "3pool", 1e7, 5.0, 3.0, 2.0, 1000, 500_000)
        self.a.save_results(p)
        history = self.a.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["protocol"], "Curve")
        self.assertEqual(history[0]["pool_name"], "3pool")

    def test_ring_buffer_cap_at_100(self):
        for _ in range(MAX_ENTRIES + 15):
            p = simple_program(self.a)
            self.a.save_results(p)
        history = self.a.load_history()
        self.assertEqual(len(history), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest_entries(self):
        for i in range(MAX_ENTRIES + 5):
            p = self.a.analyze(f"Proto{i}", "pool", 1e7, 5.0, 3.0, 2.0, 1000, 500_000)
            self.a.save_results(p)
        history = self.a.load_history()
        self.assertEqual(history[-1]["protocol"], f"Proto{MAX_ENTRIES + 4}")

    def test_saved_entry_has_timestamp(self):
        p = simple_program(self.a)
        self.a.save_results(p)
        history = self.a.load_history()
        self.assertIn("timestamp", history[0])

    def test_saved_entry_has_quality_label(self):
        p = simple_program(self.a)
        self.a.save_results(p)
        history = self.a.load_history()
        self.assertIn("quality_label", history[0])

    def test_atomic_write_no_tmp_left(self):
        p = simple_program(self.a)
        self.a.save_results(p)
        tmp = self.a.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_valid_json_after_save(self):
        p = simple_program(self.a)
        self.a.save_results(p)
        raw = self.a.data_file.read_text()
        parsed = json.loads(raw)
        self.assertIsInstance(parsed, list)

    def test_save_multiple_entries(self):
        for i in range(5):
            p = simple_program(self.a, protocol=f"P{i}")
            self.a.save_results(p)
        history = self.a.load_history()
        self.assertEqual(len(history), 5)


# ---------------------------------------------------------------------------
# saved_to field
# ---------------------------------------------------------------------------

class TestSavedToField(unittest.TestCase):

    def test_saved_to_contains_filename(self):
        # Use the default data file so the path contains "liquidity_incentive"
        a_default = LiquidityIncentiveAnalyzer()
        p = simple_program(a_default)
        self.assertIn("liquidity_incentive", p.saved_to.replace("\\", "/"))


if __name__ == "__main__":
    unittest.main()
