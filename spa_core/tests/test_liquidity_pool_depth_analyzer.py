"""
Tests for MP-672: LiquidityPoolDepthAnalyzer
≥65 test cases using unittest only (no pytest, no numpy, no pandas).
"""

import json
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.liquidity_pool_depth_analyzer import (
    MAX_ENTRIES,
    LiquidityPoolDepthAnalyzer,
    PoolDepthProfile,
    PoolDepthReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cp(
    pool_id="cp_pool",
    tvl_usd=1_000_000.0,
    volume_24h_usd=10_000.0,
    trade_size_usd=10_000.0,
    active_liquidity_pct=100.0,
) -> PoolDepthProfile:
    return PoolDepthProfile(
        pool_id=pool_id,
        pool_type="CONSTANT_PRODUCT",
        tvl_usd=tvl_usd,
        volume_24h_usd=volume_24h_usd,
        trade_size_usd=trade_size_usd,
        tick_spacing=None,
        active_liquidity_pct=active_liquidity_pct,
    )


def _ss(
    pool_id="ss_pool",
    tvl_usd=1_000_000.0,
    volume_24h_usd=10_000.0,
    trade_size_usd=10_000.0,
    active_liquidity_pct=100.0,
) -> PoolDepthProfile:
    return PoolDepthProfile(
        pool_id=pool_id,
        pool_type="STABLE_SWAP",
        tvl_usd=tvl_usd,
        volume_24h_usd=volume_24h_usd,
        trade_size_usd=trade_size_usd,
        tick_spacing=None,
        active_liquidity_pct=active_liquidity_pct,
    )


def _conc(
    pool_id="conc_pool",
    tvl_usd=1_000_000.0,
    volume_24h_usd=10_000.0,
    trade_size_usd=10_000.0,
    tick_spacing=10.0,
    active_liquidity_pct=100.0,
) -> PoolDepthProfile:
    return PoolDepthProfile(
        pool_id=pool_id,
        pool_type="CONCENTRATED",
        tvl_usd=tvl_usd,
        volume_24h_usd=volume_24h_usd,
        trade_size_usd=trade_size_usd,
        tick_spacing=tick_spacing,
        active_liquidity_pct=active_liquidity_pct,
    )


# ---------------------------------------------------------------------------
# _price_impact_pct
# ---------------------------------------------------------------------------

class TestPriceImpactPct(unittest.TestCase):
    def setUp(self):
        self.az = LiquidityPoolDepthAnalyzer()

    # CONSTANT_PRODUCT
    def test_cp_1pct_trade_gives_2pct_impact(self):
        # 1% of TVL → 2% impact
        p = _cp(tvl_usd=1_000_000, trade_size_usd=10_000)
        self.assertAlmostEqual(self.az._price_impact_pct(p), 2.0)

    def test_cp_10pct_trade_gives_20pct_impact(self):
        p = _cp(tvl_usd=1_000_000, trade_size_usd=100_000)
        self.assertAlmostEqual(self.az._price_impact_pct(p), 20.0)

    def test_cp_zero_trade_gives_zero_impact(self):
        p = _cp(tvl_usd=1_000_000, trade_size_usd=0)
        self.assertAlmostEqual(self.az._price_impact_pct(p), 0.0)

    def test_cp_trade_equals_tvl_capped_at_100(self):
        p = _cp(tvl_usd=1_000_000, trade_size_usd=1_000_000)
        # (1/1)*100*2 = 200 → capped at 100
        self.assertAlmostEqual(self.az._price_impact_pct(p), 100.0)

    def test_cp_very_large_trade_capped_at_100(self):
        p = _cp(tvl_usd=100_000, trade_size_usd=1_000_000)
        self.assertAlmostEqual(self.az._price_impact_pct(p), 100.0)

    # STABLE_SWAP
    def test_ss_1pct_trade_gives_01pct_impact(self):
        p = _ss(tvl_usd=1_000_000, trade_size_usd=10_000)
        self.assertAlmostEqual(self.az._price_impact_pct(p), 0.1)

    def test_ss_10pct_trade_gives_1pct_impact(self):
        p = _ss(tvl_usd=1_000_000, trade_size_usd=100_000)
        self.assertAlmostEqual(self.az._price_impact_pct(p), 1.0)

    def test_ss_large_pool_small_trade_tiny_impact(self):
        p = _ss(tvl_usd=50_000_000, trade_size_usd=10_000)
        # (10000/50M)*100*0.1 = 0.002
        self.assertAlmostEqual(self.az._price_impact_pct(p), 0.002)

    # CONCENTRATED
    def test_conc_100pct_active_equals_cp(self):
        p_conc = _conc(tvl_usd=1_000_000, trade_size_usd=10_000, active_liquidity_pct=100.0)
        p_cp = _cp(tvl_usd=1_000_000, trade_size_usd=10_000)
        self.assertAlmostEqual(
            self.az._price_impact_pct(p_conc),
            self.az._price_impact_pct(p_cp),
        )

    def test_conc_50pct_active_doubles_impact_vs_cp(self):
        p_conc = _conc(tvl_usd=1_000_000, trade_size_usd=10_000, active_liquidity_pct=50.0)
        p_cp = _cp(tvl_usd=1_000_000, trade_size_usd=10_000)
        self.assertAlmostEqual(
            self.az._price_impact_pct(p_conc),
            self.az._price_impact_pct(p_cp) * 2,
        )

    def test_conc_25pct_active_quadruples_impact_vs_cp(self):
        p_conc = _conc(tvl_usd=1_000_000, trade_size_usd=10_000, active_liquidity_pct=25.0)
        p_cp = _cp(tvl_usd=1_000_000, trade_size_usd=10_000)
        self.assertAlmostEqual(
            self.az._price_impact_pct(p_conc),
            self.az._price_impact_pct(p_cp) * 4,
        )

    def test_conc_zero_active_pct_returns_100(self):
        p = _conc(tvl_usd=1_000_000, trade_size_usd=10_000, active_liquidity_pct=0.0)
        self.assertAlmostEqual(self.az._price_impact_pct(p), 100.0)


# ---------------------------------------------------------------------------
# _fee_apy_estimate_pct
# ---------------------------------------------------------------------------

class TestFeeApyEstimate(unittest.TestCase):
    def setUp(self):
        self.az = LiquidityPoolDepthAnalyzer()

    def test_exact_100pct_apy(self):
        # tvl=1_095_000, vol=1_000_000 → (1M*365*0.003)/1.095M*100 = 100.0
        p = _cp(tvl_usd=1_095_000, volume_24h_usd=1_000_000)
        self.assertAlmostEqual(self.az._fee_apy_estimate_pct(p), 100.0, places=4)

    def test_zero_volume_gives_zero_apy(self):
        p = _cp(tvl_usd=1_000_000, volume_24h_usd=0)
        self.assertAlmostEqual(self.az._fee_apy_estimate_pct(p), 0.0)

    def test_capped_at_999(self):
        # extremely high volume
        p = _cp(tvl_usd=1, volume_24h_usd=1_000_000_000)
        self.assertAlmostEqual(self.az._fee_apy_estimate_pct(p), 999.0)

    def test_specific_value_10k_vol_on_1m_tvl(self):
        # (10000*365*0.003)/1000000*100 = 1.095%
        p = _cp(tvl_usd=1_000_000, volume_24h_usd=10_000)
        self.assertAlmostEqual(self.az._fee_apy_estimate_pct(p), 1.095, places=4)

    def test_specific_value_100k_vol_on_1m_tvl(self):
        # (100000*365*0.003)/1000000*100 = 10.95%
        p = _cp(tvl_usd=1_000_000, volume_24h_usd=100_000)
        self.assertAlmostEqual(self.az._fee_apy_estimate_pct(p), 10.95, places=4)

    def test_zero_tvl_returns_zero(self):
        p = _cp(tvl_usd=0, volume_24h_usd=1_000)
        self.assertAlmostEqual(self.az._fee_apy_estimate_pct(p), 0.0)


# ---------------------------------------------------------------------------
# _depth_score
# ---------------------------------------------------------------------------

class TestDepthScore(unittest.TestCase):
    def setUp(self):
        self.az = LiquidityPoolDepthAnalyzer()

    def test_zero_impact_gives_score_1(self):
        self.assertAlmostEqual(self.az._depth_score(0.0), 1.0)

    def test_5pct_impact_gives_score_05(self):
        self.assertAlmostEqual(self.az._depth_score(5.0), 0.5)

    def test_10pct_impact_gives_score_0(self):
        self.assertAlmostEqual(self.az._depth_score(10.0), 0.0)

    def test_20pct_impact_clamped_to_0(self):
        self.assertAlmostEqual(self.az._depth_score(20.0), 0.0)

    def test_1pct_impact_gives_09(self):
        self.assertAlmostEqual(self.az._depth_score(1.0), 0.9)

    def test_8pct_impact_gives_02(self):
        self.assertAlmostEqual(self.az._depth_score(8.0), 0.2)

    def test_100pct_impact_clamped_to_0(self):
        self.assertAlmostEqual(self.az._depth_score(100.0), 0.0)

    def test_2pct_impact_gives_08(self):
        self.assertAlmostEqual(self.az._depth_score(2.0), 0.8)


# ---------------------------------------------------------------------------
# _depth_rating
# ---------------------------------------------------------------------------

class TestDepthRating(unittest.TestCase):
    def setUp(self):
        self.az = LiquidityPoolDepthAnalyzer()

    def test_score_10_is_deep(self):
        self.assertEqual(self.az._depth_rating(1.0), "DEEP")

    def test_score_08_is_deep(self):
        self.assertEqual(self.az._depth_rating(0.8), "DEEP")

    def test_score_just_below_08_is_adequate(self):
        self.assertEqual(self.az._depth_rating(0.799), "ADEQUATE")

    def test_score_05_is_adequate(self):
        self.assertEqual(self.az._depth_rating(0.5), "ADEQUATE")

    def test_score_just_below_05_is_shallow(self):
        self.assertEqual(self.az._depth_rating(0.499), "SHALLOW")

    def test_score_02_is_shallow(self):
        self.assertEqual(self.az._depth_rating(0.2), "SHALLOW")

    def test_score_just_below_02_is_very_shallow(self):
        self.assertEqual(self.az._depth_rating(0.199), "VERY_SHALLOW")

    def test_score_00_is_very_shallow(self):
        self.assertEqual(self.az._depth_rating(0.0), "VERY_SHALLOW")


# ---------------------------------------------------------------------------
# _liquidity_quality
# ---------------------------------------------------------------------------

class TestLiquidityQuality(unittest.TestCase):
    def setUp(self):
        self.az = LiquidityPoolDepthAnalyzer()

    def test_high_fee_deep_is_excellent(self):
        self.assertEqual(self.az._liquidity_quality("DEEP", 10.0), "EXCELLENT")

    def test_high_fee_adequate_is_excellent(self):
        self.assertEqual(self.az._liquidity_quality("ADEQUATE", 6.0), "EXCELLENT")

    def test_high_fee_shallow_is_good_not_excellent(self):
        # fee>5 but depth is SHALLOW, not ADEQUATE/DEEP
        self.assertEqual(self.az._liquidity_quality("SHALLOW", 10.0), "GOOD")

    def test_high_fee_very_shallow_is_fair(self):
        # fee>5 but depth too shallow for GOOD (VERY_SHALLOW not in SHALLOW+)
        self.assertEqual(self.az._liquidity_quality("VERY_SHALLOW", 10.0), "FAIR")

    def test_moderate_fee_deep_is_good(self):
        self.assertEqual(self.az._liquidity_quality("DEEP", 3.0), "GOOD")

    def test_moderate_fee_shallow_is_good(self):
        self.assertEqual(self.az._liquidity_quality("SHALLOW", 3.0), "GOOD")

    def test_moderate_fee_very_shallow_is_fair(self):
        # fee>2 but VERY_SHALLOW not in (DEEP, ADEQUATE, SHALLOW)
        self.assertEqual(self.az._liquidity_quality("VERY_SHALLOW", 3.0), "FAIR")

    def test_low_fee_any_depth_is_fair(self):
        self.assertEqual(self.az._liquidity_quality("DEEP", 1.0), "FAIR")

    def test_zero_fee_deep_is_poor(self):
        self.assertEqual(self.az._liquidity_quality("DEEP", 0.0), "POOR")

    def test_zero_fee_very_shallow_is_poor(self):
        self.assertEqual(self.az._liquidity_quality("VERY_SHALLOW", 0.0), "POOR")


# ---------------------------------------------------------------------------
# _recommendations
# ---------------------------------------------------------------------------

class TestRecommendations(unittest.TestCase):
    def setUp(self):
        self.az = LiquidityPoolDepthAnalyzer()

    def _recs(self, p, impact, rating="ADEQUATE", fee_apy=5.0):
        return self.az._recommendations(p, impact, rating, fee_apy)

    def test_high_impact_warns_split_trade(self):
        p = _cp()
        recs = self._recs(p, impact=5.0)
        self.assertTrue(any("split trade" in r for r in recs))

    def test_high_impact_message_contains_value(self):
        p = _cp()
        recs = self._recs(p, impact=5.0)
        self.assertTrue(any("5.0%" in r for r in recs))

    def test_moderate_impact_warns_splitting(self):
        p = _cp()
        recs = self._recs(p, impact=1.0)
        self.assertTrue(any("Moderate price impact" in r for r in recs))

    def test_low_impact_no_impact_warning(self):
        p = _cp()
        recs = self._recs(p, impact=0.2)
        self.assertFalse(any("price impact" in r.lower() for r in recs))

    def test_exactly_2pct_impact_is_moderate_not_high(self):
        # 2.0 is NOT > 2.0, should fall through to elif > 0.5
        p = _cp()
        recs = self._recs(p, impact=2.0)
        self.assertTrue(any("Moderate" in r for r in recs))
        self.assertFalse(any("split trade or use aggregator" in r for r in recs))

    def test_cp_low_tvl_warns_liquidity_risk(self):
        p = _cp(tvl_usd=500_000)
        recs = self._recs(p, impact=0.1)
        self.assertTrue(any("Low TVL pool" in r for r in recs))

    def test_cp_high_tvl_no_tvl_warning(self):
        p = _cp(tvl_usd=2_000_000)
        recs = self._recs(p, impact=0.1)
        self.assertFalse(any("Low TVL pool" in r for r in recs))

    def test_ss_low_tvl_no_tvl_warning(self):
        # TVL warning is only for CONSTANT_PRODUCT pools
        p = _ss(tvl_usd=500_000)
        recs = self._recs(p, impact=0.1)
        self.assertFalse(any("Low TVL pool" in r for r in recs))

    def test_active_pct_below_50_warns_concentration(self):
        p = _conc(active_liquidity_pct=30.0)
        recs = self._recs(p, impact=0.1)
        self.assertTrue(any("30% active" in r for r in recs))

    def test_active_pct_49_warns_concentration(self):
        p = _conc(active_liquidity_pct=49.0)
        recs = self._recs(p, impact=0.1)
        self.assertTrue(any("Concentrated LP" in r for r in recs))

    def test_active_pct_50_no_concentration_warning(self):
        # exactly 50 is NOT < 50
        p = _conc(active_liquidity_pct=50.0)
        recs = self._recs(p, impact=0.1)
        self.assertFalse(any("Concentrated LP" in r for r in recs))

    def test_high_fee_apy_gives_lp_opportunity_message(self):
        p = _cp()
        recs = self._recs(p, impact=0.1, fee_apy=25.0)
        self.assertTrue(any("High fee APY" in r for r in recs))

    def test_fee_apy_exactly_20_no_high_fee_warning(self):
        # 20 is NOT > 20
        p = _cp()
        recs = self._recs(p, impact=0.1, fee_apy=20.0)
        self.assertFalse(any("High fee APY" in r for r in recs))

    def test_shallow_depth_warns_execution_quality(self):
        p = _cp()
        recs = self._recs(p, impact=0.1, rating="SHALLOW")
        self.assertTrue(any("Shallow pool" in r for r in recs))

    def test_very_shallow_depth_warns_execution_quality(self):
        p = _cp()
        recs = self._recs(p, impact=0.1, rating="VERY_SHALLOW")
        self.assertTrue(any("Shallow pool" in r for r in recs))

    def test_deep_depth_no_shallow_warning(self):
        p = _cp()
        recs = self._recs(p, impact=0.1, rating="DEEP")
        self.assertFalse(any("Shallow pool" in r for r in recs))


# ---------------------------------------------------------------------------
# analyze (integration)
# ---------------------------------------------------------------------------

class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.az = LiquidityPoolDepthAnalyzer()

    def test_returns_pool_depth_report(self):
        p = _cp()
        result = self.az.analyze(p)
        self.assertIsInstance(result, PoolDepthReport)

    def test_stable_swap_large_pool_small_trade_is_deep(self):
        p = _ss(tvl_usd=50_000_000, trade_size_usd=10_000)
        result = self.az.analyze(p)
        self.assertLess(result.price_impact_pct, 0.1)
        self.assertEqual(result.depth_rating, "DEEP")

    def test_cp_small_pool_large_trade_is_very_shallow(self):
        p = _cp(tvl_usd=100_000, trade_size_usd=50_000)
        result = self.az.analyze(p)
        self.assertEqual(result.depth_rating, "VERY_SHALLOW")

    def test_conc_100pct_active_same_impact_as_cp(self):
        p_conc = _conc(tvl_usd=1_000_000, trade_size_usd=10_000, active_liquidity_pct=100.0)
        p_cp = _cp(tvl_usd=1_000_000, trade_size_usd=10_000)
        self.assertAlmostEqual(
            self.az.analyze(p_conc).price_impact_pct,
            self.az.analyze(p_cp).price_impact_pct,
        )

    def test_pool_id_propagated(self):
        p = _cp(pool_id="test_pool_xyz")
        result = self.az.analyze(p)
        self.assertEqual(result.pool_id, "test_pool_xyz")

    def test_pool_type_propagated(self):
        p = _ss()
        result = self.az.analyze(p)
        self.assertEqual(result.pool_type, "STABLE_SWAP")

    def test_recommendations_is_list(self):
        p = _cp()
        result = self.az.analyze(p)
        self.assertIsInstance(result.recommendations, list)

    def test_depth_score_in_range(self):
        p = _cp()
        result = self.az.analyze(p)
        self.assertGreaterEqual(result.depth_score, 0.0)
        self.assertLessEqual(result.depth_score, 1.0)


# ---------------------------------------------------------------------------
# analyze_batch
# ---------------------------------------------------------------------------

class TestAnalyzeBatch(unittest.TestCase):
    def setUp(self):
        self.az = LiquidityPoolDepthAnalyzer()

    def test_empty_batch_returns_empty_list(self):
        self.assertEqual(self.az.analyze_batch([]), [])

    def test_single_profile_returns_single_report(self):
        result = self.az.analyze_batch([_cp()])
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], PoolDepthReport)

    def test_multiple_profiles_returns_correct_count(self):
        profiles = [_cp(pool_id="a"), _ss(pool_id="b"), _conc(pool_id="c")]
        results = self.az.analyze_batch(profiles)
        self.assertEqual(len(results), 3)

    def test_batch_preserves_order(self):
        profiles = [_cp(pool_id="first"), _ss(pool_id="second")]
        results = self.az.analyze_batch(profiles)
        self.assertEqual(results[0].pool_id, "first")
        self.assertEqual(results[1].pool_id, "second")


# ---------------------------------------------------------------------------
# save_results / load_history
# ---------------------------------------------------------------------------

class TestSaveLoadHistory(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        data_file = Path(self.tmp_dir.name) / "pool_depth_log.json"
        self.az = LiquidityPoolDepthAnalyzer(data_file=data_file)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(self.az.load_history(), [])

    def test_save_creates_file(self):
        report = self.az.analyze(_cp())
        self.az.save_results([report])
        self.assertTrue(self.az.data_file.exists())

    def test_save_and_load_roundtrip(self):
        report = self.az.analyze(_cp(pool_id="roundtrip"))
        self.az.save_results([report])
        history = self.az.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["pool_id"], "roundtrip")

    def test_ring_buffer_caps_at_max_entries(self):
        # Save 101 entries
        for i in range(MAX_ENTRIES + 1):
            self.az.save_results([self.az.analyze(_cp(pool_id=f"p{i}"))])
        history = self.az.load_history()
        self.assertEqual(len(history), MAX_ENTRIES)

    def test_atomic_write_no_tmp_file_left(self):
        report = self.az.analyze(_cp())
        self.az.save_results([report])
        tmp_path = self.az.data_file.with_suffix(".tmp")
        self.assertFalse(tmp_path.exists())

    def test_history_contains_timestamp(self):
        report = self.az.analyze(_cp())
        self.az.save_results([report])
        history = self.az.load_history()
        self.assertIn("timestamp", history[0])


if __name__ == "__main__":
    unittest.main()
