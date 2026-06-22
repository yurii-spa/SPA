"""Tests for MP-697 FeeMarketAnalyzer.

Run with:
    python3 -m unittest spa_core.tests.test_fee_market_analyzer -v
"""
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.fee_market_analyzer import (
    FeeAnalysis,
    FeeMarketAnalyzer,
    FeePool,
    MarketFeeReport,
    FEE_APY_CAP,
    _attractiveness,
    _fee_apy_pct,
    _fee_efficiency,
    _fee_tier_label,
    _implied_volume_ratio,
    _insights,
    _recommended_for,
    _revenue_per_lp,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _pool(
    pool_id="pool_a",
    protocol="Uniswap V3",
    fee_tier_bps=30.0,
    volume_24h_usd=10_000_000.0,
    tvl_usd=5_000_000.0,
    fee_revenue_24h_usd=3_000.0,
    lp_count=50,
):
    return FeePool(
        pool_id=pool_id,
        protocol=protocol,
        fee_tier_bps=fee_tier_bps,
        volume_24h_usd=volume_24h_usd,
        tvl_usd=tvl_usd,
        fee_revenue_24h_usd=fee_revenue_24h_usd,
        lp_count=lp_count,
    )


# ---------------------------------------------------------------------------
# 1. implied_volume_ratio
# ---------------------------------------------------------------------------

class TestImpliedVolumeRatio(unittest.TestCase):

    def test_basic_ratio(self):
        self.assertAlmostEqual(_implied_volume_ratio(10_000, 5_000), 2.0)

    def test_zero_tvl_returns_zero(self):
        self.assertEqual(_implied_volume_ratio(10_000, 0), 0.0)

    def test_negative_tvl_returns_zero(self):
        self.assertEqual(_implied_volume_ratio(10_000, -1), 0.0)

    def test_ratio_less_than_one(self):
        self.assertAlmostEqual(_implied_volume_ratio(1_000, 10_000), 0.1)

    def test_equal_volume_and_tvl(self):
        self.assertAlmostEqual(_implied_volume_ratio(5_000, 5_000), 1.0)

    def test_very_high_ratio(self):
        self.assertAlmostEqual(_implied_volume_ratio(100_000, 10_000), 10.0)


# ---------------------------------------------------------------------------
# 2. fee_apy_pct formula and cap
# ---------------------------------------------------------------------------

class TestFeeApyPct(unittest.TestCase):

    def test_basic_formula(self):
        # 1000 * 365 / 100_000 * 100 = 365%
        self.assertAlmostEqual(_fee_apy_pct(1_000, 100_000), 365.0)

    def test_zero_tvl_returns_zero(self):
        self.assertEqual(_fee_apy_pct(1_000, 0), 0.0)

    def test_negative_tvl_returns_zero(self):
        self.assertEqual(_fee_apy_pct(1_000, -1), 0.0)

    def test_cap_at_999(self):
        # Very high revenue → capped at 999
        result = _fee_apy_pct(1_000_000, 1_000)
        self.assertAlmostEqual(result, FEE_APY_CAP)

    def test_below_cap_not_capped(self):
        result = _fee_apy_pct(1_000, 1_000_000)
        self.assertLess(result, FEE_APY_CAP)

    def test_exact_at_cap_boundary(self):
        # 999/365*100_000/100 ≈ 2737 daily revenue needed to hit 999%
        daily = 999.0 / 365.0 / 100.0 * 100_000
        result = _fee_apy_pct(daily, 100_000)
        self.assertAlmostEqual(result, FEE_APY_CAP, places=3)


# ---------------------------------------------------------------------------
# 3. revenue_per_lp_daily_usd
# ---------------------------------------------------------------------------

class TestRevenuePerLp(unittest.TestCase):

    def test_basic(self):
        self.assertAlmostEqual(_revenue_per_lp(1_000, 10), 100.0)

    def test_zero_lp_count_returns_zero(self):
        self.assertEqual(_revenue_per_lp(1_000, 0), 0.0)

    def test_negative_lp_count_returns_zero(self):
        self.assertEqual(_revenue_per_lp(1_000, -5), 0.0)

    def test_single_lp(self):
        self.assertAlmostEqual(_revenue_per_lp(500, 1), 500.0)

    def test_fractional_result(self):
        self.assertAlmostEqual(_revenue_per_lp(100, 3), 100 / 3)


# ---------------------------------------------------------------------------
# 4. fee_efficiency
# ---------------------------------------------------------------------------

class TestFeeEfficiency(unittest.TestCase):

    def test_expected_efficiency_is_one(self):
        # fee_revenue = volume * fee / 10000 → efficiency = 1
        vol = 1_000_000
        fee_bps = 30.0
        expected_rev = vol * fee_bps / 10_000
        self.assertAlmostEqual(_fee_efficiency(expected_rev, vol, fee_bps), 1.0)

    def test_higher_than_expected(self):
        # twice the expected revenue → efficiency = 2
        vol = 1_000_000
        fee_bps = 30.0
        expected_rev = vol * fee_bps / 10_000 * 2
        self.assertAlmostEqual(_fee_efficiency(expected_rev, vol, fee_bps), 2.0)

    def test_zero_volume_returns_zero(self):
        self.assertEqual(_fee_efficiency(100, 0, 30), 0.0)

    def test_zero_fee_bps_returns_zero(self):
        self.assertEqual(_fee_efficiency(100, 1_000_000, 0), 0.0)

    def test_below_expected(self):
        vol = 1_000_000
        fee_bps = 30.0
        half_rev = vol * fee_bps / 10_000 * 0.5
        self.assertAlmostEqual(_fee_efficiency(half_rev, vol, fee_bps), 0.5)


# ---------------------------------------------------------------------------
# 5. fee_tier_label thresholds
# ---------------------------------------------------------------------------

class TestFeeTierLabel(unittest.TestCase):

    def test_1bps_ultra_low(self):
        self.assertEqual(_fee_tier_label(1), "ULTRA_LOW")

    def test_5bps_ultra_low(self):
        self.assertEqual(_fee_tier_label(5), "ULTRA_LOW")

    def test_6bps_low(self):
        self.assertEqual(_fee_tier_label(6), "LOW")

    def test_30bps_low(self):
        self.assertEqual(_fee_tier_label(30), "LOW")

    def test_31bps_standard(self):
        self.assertEqual(_fee_tier_label(31), "STANDARD")

    def test_50bps_standard(self):
        self.assertEqual(_fee_tier_label(50), "STANDARD")

    def test_51bps_high(self):
        self.assertEqual(_fee_tier_label(51), "HIGH")

    def test_100bps_high(self):
        self.assertEqual(_fee_tier_label(100), "HIGH")


# ---------------------------------------------------------------------------
# 6. attractiveness thresholds
# ---------------------------------------------------------------------------

class TestAttractiveness(unittest.TestCase):

    def test_highly_attractive_above_20(self):
        self.assertEqual(_attractiveness(20.1), "HIGHLY_ATTRACTIVE")

    def test_highly_attractive_very_high(self):
        self.assertEqual(_attractiveness(100.0), "HIGHLY_ATTRACTIVE")

    def test_attractive_above_10(self):
        self.assertEqual(_attractiveness(15.0), "ATTRACTIVE")

    def test_attractive_just_above_10(self):
        self.assertEqual(_attractiveness(10.1), "ATTRACTIVE")

    def test_fair_above_3(self):
        self.assertEqual(_attractiveness(5.0), "FAIR")

    def test_fair_just_above_3(self):
        self.assertEqual(_attractiveness(3.1), "FAIR")

    def test_poor_at_3(self):
        self.assertEqual(_attractiveness(3.0), "POOR")

    def test_poor_below_3(self):
        self.assertEqual(_attractiveness(1.0), "POOR")

    def test_poor_at_zero(self):
        self.assertEqual(_attractiveness(0.0), "POOR")


# ---------------------------------------------------------------------------
# 7. recommended_for conditions
# ---------------------------------------------------------------------------

class TestRecommendedFor(unittest.TestCase):

    def test_both_high_apy_low_fee(self):
        # apy > 10 AND fee <= 30
        self.assertEqual(_recommended_for(15.0, 30.0, 1.0), "BOTH")

    def test_lp_high_apy_but_high_fee(self):
        # apy > 10 but fee > 30 → LP (not BOTH)
        self.assertEqual(_recommended_for(15.0, 50.0, 1.0), "LP")

    def test_lp_apy_above_5(self):
        self.assertEqual(_recommended_for(7.0, 50.0, 1.0), "LP")

    def test_trader_low_fee_high_volume_ratio(self):
        # apy <= 5, fee <= 10, vol_ratio > 0.5
        self.assertEqual(_recommended_for(2.0, 5.0, 1.0), "TRADER")

    def test_neither_low_apy_high_fee_low_volume(self):
        self.assertEqual(_recommended_for(1.0, 100.0, 0.1), "NEITHER")

    def test_trader_volume_ratio_boundary(self):
        # exactly 0.5 → not > 0.5 → NEITHER
        self.assertEqual(_recommended_for(2.0, 5.0, 0.5), "NEITHER")

    def test_trader_volume_above_boundary(self):
        self.assertEqual(_recommended_for(2.0, 5.0, 0.51), "TRADER")


# ---------------------------------------------------------------------------
# 8. _insights
# ---------------------------------------------------------------------------

class TestInsights(unittest.TestCase):

    def _call(self, eff=1.0, vol_ratio=1.0, rev_lp=10.0, apy=5.0, lp_count=20):
        return _insights(eff, vol_ratio, rev_lp, apy, lp_count)

    def test_high_efficiency_flash_loan_note(self):
        notes = self._call(eff=2.0)
        self.assertTrue(any("flash loan" in n.lower() for n in notes))

    def test_efficiency_15_triggers_note(self):
        notes = self._call(eff=1.5)
        # exactly 1.5 — boundary: NOT > 1.5, so no note
        self.assertFalse(any("flash loan" in n.lower() for n in notes))

    def test_efficiency_above_15_triggers_note(self):
        notes = self._call(eff=1.51)
        self.assertTrue(any("flash loan" in n.lower() for n in notes))

    def test_high_turnover_note(self):
        notes = self._call(vol_ratio=6.0)
        self.assertTrue(any("turnover" in n.lower() for n in notes))

    def test_turnover_exactly_5_no_note(self):
        notes = self._call(vol_ratio=5.0)
        self.assertFalse(any("turnover" in n.lower() for n in notes))

    def test_strong_lp_revenue_note(self):
        notes = self._call(rev_lp=150.0)
        self.assertTrue(any("LP revenue" in n for n in notes))

    def test_lp_revenue_exactly_100_no_note(self):
        notes = self._call(rev_lp=100.0)
        self.assertFalse(any("LP revenue" in n for n in notes))

    def test_high_fee_apy_sustainability_warning(self):
        notes = self._call(apy=55.0)
        self.assertTrue(any("verify volume" in n.lower() for n in notes))

    def test_apy_exactly_50_no_warning(self):
        notes = self._call(apy=50.0)
        self.assertFalse(any("verify volume" in n.lower() for n in notes))

    def test_few_lps_warning(self):
        notes = self._call(lp_count=4)
        self.assertTrue(any("few LPs" in n for n in notes))

    def test_exactly_5_lps_no_warning(self):
        notes = self._call(lp_count=5)
        self.assertFalse(any("few LPs" in n for n in notes))

    def test_normal_conditions_no_warnings(self):
        notes = self._call(eff=1.0, vol_ratio=1.0, rev_lp=10.0, apy=5.0, lp_count=20)
        self.assertEqual(notes, [])


# ---------------------------------------------------------------------------
# 9. analyze_pool() integration
# ---------------------------------------------------------------------------

class TestAnalyzePool(unittest.TestCase):

    def setUp(self):
        self.analyzer = FeeMarketAnalyzer()

    def test_returns_fee_analysis(self):
        result = self.analyzer.analyze_pool(_pool())
        self.assertIsInstance(result, FeeAnalysis)

    def test_pool_id_preserved(self):
        result = self.analyzer.analyze_pool(_pool(pool_id="test_pool"))
        self.assertEqual(result.pool_id, "test_pool")

    def test_protocol_preserved(self):
        result = self.analyzer.analyze_pool(_pool(protocol="Curve"))
        self.assertEqual(result.protocol, "Curve")

    def test_fee_tier_preserved(self):
        result = self.analyzer.analyze_pool(_pool(fee_tier_bps=5.0))
        self.assertAlmostEqual(result.fee_tier_bps, 5.0)

    def test_high_fee_apy_highly_attractive(self):
        # Very high fee revenue → HIGHLY_ATTRACTIVE
        p = _pool(fee_revenue_24h_usd=300_000, tvl_usd=1_000_000)
        result = self.analyzer.analyze_pool(p)
        self.assertEqual(result.attractiveness, "HIGHLY_ATTRACTIVE")

    def test_zero_tvl_graceful(self):
        p = _pool(tvl_usd=0)
        result = self.analyzer.analyze_pool(p)
        self.assertEqual(result.fee_apy_pct, 0.0)
        self.assertEqual(result.implied_volume_ratio, 0.0)

    def test_zero_lp_count_graceful(self):
        p = _pool(lp_count=0)
        result = self.analyzer.analyze_pool(p)
        self.assertEqual(result.revenue_per_lp_daily_usd, 0.0)


# ---------------------------------------------------------------------------
# 10. analyze_market() — best_for_lp, best_for_trader, avg, empty
# ---------------------------------------------------------------------------

class TestAnalyzeMarket(unittest.TestCase):

    def setUp(self):
        self.analyzer = FeeMarketAnalyzer()

    def _build_pools(self):
        return [
            _pool("pool_high_apy",  fee_tier_bps=30, fee_revenue_24h_usd=50_000,  tvl_usd=100_000,   lp_count=10),
            _pool("pool_low_fee",   fee_tier_bps=1,  fee_revenue_24h_usd=1_000,   tvl_usd=5_000_000, lp_count=200),
            _pool("pool_mid",       fee_tier_bps=10, fee_revenue_24h_usd=5_000,   tvl_usd=500_000,   lp_count=30),
        ]

    def test_empty_pools_no_crash(self):
        report = self.analyzer.analyze_market([])
        self.assertIsInstance(report, MarketFeeReport)

    def test_empty_pools_best_lp_empty(self):
        report = self.analyzer.analyze_market([])
        self.assertEqual(report.best_for_lp, "")

    def test_empty_pools_best_trader_empty(self):
        report = self.analyzer.analyze_market([])
        self.assertEqual(report.best_for_trader, "")

    def test_empty_pools_avg_zero(self):
        report = self.analyzer.analyze_market([])
        self.assertAlmostEqual(report.avg_fee_apy_pct, 0.0)

    def test_best_for_lp_highest_apy(self):
        pools = self._build_pools()
        report = self.analyzer.analyze_market(pools)
        # pool_high_apy has 50000*365/100000*100 = capped at 999 or very high
        self.assertEqual(report.best_for_lp, "pool_high_apy")

    def test_best_for_trader_lowest_fee_bps(self):
        pools = self._build_pools()
        report = self.analyzer.analyze_market(pools)
        self.assertEqual(report.best_for_trader, "pool_low_fee")

    def test_avg_fee_apy_correct(self):
        pools = self._build_pools()
        report = self.analyzer.analyze_market(pools)
        apys = [a.fee_apy_pct for a in report.pools]
        expected = sum(apys) / len(apys)
        self.assertAlmostEqual(report.avg_fee_apy_pct, expected, places=5)

    def test_market_summary_not_empty(self):
        pools = self._build_pools()
        report = self.analyzer.analyze_market(pools)
        self.assertTrue(len(report.market_summary) > 0)

    def test_pools_count_in_report(self):
        pools = self._build_pools()
        report = self.analyzer.analyze_market(pools)
        self.assertEqual(len(report.pools), 3)

    def test_single_pool_best_lp_and_trader_same(self):
        p = _pool("solo", fee_tier_bps=30)
        report = self.analyzer.analyze_market([p])
        self.assertEqual(report.best_for_lp, "solo")
        self.assertEqual(report.best_for_trader, "solo")


# ---------------------------------------------------------------------------
# 11. save_results / load_history (ring-buffer + atomic write)
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analyzer = FeeMarketAnalyzer(data_dir=self.tmpdir)
        self.data_file = Path(self.tmpdir) / "fee_market_log.json"

    def _make_report(self):
        return self.analyzer.analyze_market([_pool()])

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(self.analyzer.load_history(), [])

    def test_save_creates_file(self):
        self.analyzer.save_results([self._make_report()])
        self.assertTrue(self.data_file.exists())

    def test_saved_file_is_valid_json(self):
        self.analyzer.save_results([self._make_report()])
        with open(self.data_file) as fh:
            data = json.load(fh)
        self.assertIn("entries", data)

    def test_load_history_after_save(self):
        self.analyzer.save_results([self._make_report()])
        history = self.analyzer.load_history()
        self.assertEqual(len(history), 1)

    def test_append_accumulates(self):
        self.analyzer.save_results([self._make_report()])
        self.analyzer.save_results([self._make_report()])
        history = self.analyzer.load_history()
        self.assertEqual(len(history), 2)

    def test_ring_buffer_caps_at_100(self):
        reports = [self._make_report() for _ in range(105)]
        self.analyzer.save_results(reports)
        history = self.analyzer.load_history()
        self.assertEqual(len(history), 100)

    def test_ring_buffer_keeps_newest(self):
        old_reports = [self._make_report() for _ in range(100)]
        self.analyzer.save_results(old_reports)
        # force a unique marker via summary
        extra_pool = _pool(pool_id="unique_marker_pool")
        extra_report = self.analyzer.analyze_market([extra_pool])
        self.analyzer.save_results([extra_report])
        history = self.analyzer.load_history()
        self.assertEqual(len(history), 100)
        self.assertEqual(history[-1]["best_for_lp"], "unique_marker_pool")

    def test_atomic_write_no_tmp_file_remains(self):
        self.analyzer.save_results([self._make_report()])
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_schema_version_in_file(self):
        self.analyzer.save_results([self._make_report()])
        with open(self.data_file) as fh:
            data = json.load(fh)
        self.assertEqual(data["schema_version"], "1.0")

    def test_load_corrupt_file_returns_empty(self):
        self.data_file.write_text("NOT JSON")
        self.assertEqual(self.analyzer.load_history(), [])


if __name__ == "__main__":
    unittest.main()
