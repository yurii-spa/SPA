"""
Tests for MP-730: FundingRateArbitrageAnalyzer
stdlib unittest only. ≥65 tests.
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.funding_rate_arbitrage_analyzer import (
    FundingRateSnapshot,
    FundingArbOpportunity,
    FundingRateAnalysisResult,
    annualize_funding,
    assess_liquidation_risk,
    assess_basis_risk,
    compute_opportunity,
    analyze_market,
    top_n,
    save_results,
    load_history,
)


def _snap(symbol="ETH", exchange="dYdX", rate_8h=0.01, spot_apy=3.5, ts="2026-01-01T00:00:00Z"):
    return FundingRateSnapshot(
        symbol=symbol,
        exchange=exchange,
        funding_rate_8h=rate_8h,
        spot_apy=spot_apy,
        timestamp_iso=ts,
    )


class TestAnnualizeFunding(unittest.TestCase):
    def test_positive_rate(self):
        # 0.001 * 3 * 365 = 1.095
        result = annualize_funding(0.001)
        self.assertAlmostEqual(result, 1.095, places=6)

    def test_zero_rate(self):
        self.assertEqual(annualize_funding(0.0), 0.0)

    def test_negative_rate(self):
        result = annualize_funding(-0.001)
        self.assertAlmostEqual(result, -1.095, places=6)

    def test_larger_positive_rate(self):
        # 0.01 * 3 * 365 = 10.95
        result = annualize_funding(0.01)
        self.assertAlmostEqual(result, 10.95, places=4)

    def test_high_rate(self):
        # 0.1 * 3 * 365 = 109.5
        result = annualize_funding(0.1)
        self.assertAlmostEqual(result, 109.5, places=4)

    def test_very_high_rate(self):
        # 1.0 * 3 * 365 = 1095.0
        result = annualize_funding(1.0)
        self.assertAlmostEqual(result, 1095.0, places=4)

    def test_small_negative(self):
        result = annualize_funding(-0.002)
        self.assertAlmostEqual(result, -2.19, places=4)

    def test_multiplier_is_1095(self):
        # Each unit of rate_8h multiplied by 1095
        self.assertAlmostEqual(annualize_funding(1.0), 1095.0, places=6)

    def test_proportional(self):
        # Double the rate → double the result
        r1 = annualize_funding(0.005)
        r2 = annualize_funding(0.010)
        self.assertAlmostEqual(r2, 2 * r1, places=8)


class TestAssessLiquidationRisk(unittest.TestCase):
    def test_low_risk(self):
        self.assertEqual(assess_liquidation_risk(1.095), "LOW")

    def test_medium_risk_border(self):
        # > 50 → MEDIUM
        self.assertEqual(assess_liquidation_risk(51.0), "MEDIUM")

    def test_medium_risk(self):
        self.assertEqual(assess_liquidation_risk(75.0), "MEDIUM")

    def test_high_risk(self):
        self.assertEqual(assess_liquidation_risk(101.0), "HIGH")

    def test_high_risk_large(self):
        self.assertEqual(assess_liquidation_risk(500.0), "HIGH")

    def test_negative_low(self):
        # Abs(-10) = 10 → LOW
        self.assertEqual(assess_liquidation_risk(-10.0), "LOW")

    def test_negative_medium(self):
        self.assertEqual(assess_liquidation_risk(-60.0), "MEDIUM")

    def test_negative_high(self):
        self.assertEqual(assess_liquidation_risk(-110.0), "HIGH")

    def test_exactly_50_is_low(self):
        # > 50 → MEDIUM, so exactly 50 → LOW
        self.assertEqual(assess_liquidation_risk(50.0), "LOW")

    def test_exactly_100_is_medium(self):
        # > 100 → HIGH, so exactly 100 → MEDIUM
        self.assertEqual(assess_liquidation_risk(100.0), "MEDIUM")

    def test_zero_rate(self):
        self.assertEqual(assess_liquidation_risk(0.0), "LOW")


class TestAssessBasisRisk(unittest.TestCase):
    def test_btc_is_low(self):
        self.assertEqual(assess_basis_risk("BTC"), "LOW")

    def test_eth_is_low(self):
        self.assertEqual(assess_basis_risk("ETH"), "LOW")

    def test_sol_is_medium(self):
        self.assertEqual(assess_basis_risk("SOL"), "MEDIUM")

    def test_bnb_is_medium(self):
        self.assertEqual(assess_basis_risk("BNB"), "MEDIUM")

    def test_avax_is_medium(self):
        self.assertEqual(assess_basis_risk("AVAX"), "MEDIUM")

    def test_shib_is_high(self):
        self.assertEqual(assess_basis_risk("SHIB"), "HIGH")

    def test_unknown_is_high(self):
        self.assertEqual(assess_basis_risk("MEME123"), "HIGH")

    def test_case_insensitive_btc(self):
        self.assertEqual(assess_basis_risk("btc"), "LOW")

    def test_case_insensitive_eth(self):
        self.assertEqual(assess_basis_risk("eth"), "LOW")

    def test_link_is_medium(self):
        self.assertEqual(assess_basis_risk("LINK"), "MEDIUM")

    def test_xrp_is_medium(self):
        self.assertEqual(assess_basis_risk("XRP"), "MEDIUM")


class TestComputeOpportunity(unittest.TestCase):
    def _make_snap(self, rate_8h=0.01, spot_apy=3.5, symbol="ETH", exchange="dYdX"):
        return _snap(symbol=symbol, exchange=exchange, rate_8h=rate_8h, spot_apy=spot_apy)

    def test_gross_yield_formula(self):
        snap = self._make_snap(rate_8h=0.01, spot_apy=3.5)
        opp = compute_opportunity(snap)
        expected_funding = annualize_funding(0.01)  # 10.95
        self.assertAlmostEqual(opp.gross_yield, 3.5 + expected_funding, places=6)

    def test_net_yield_formula(self):
        snap = self._make_snap(rate_8h=0.01, spot_apy=3.5)
        opp = compute_opportunity(snap)
        # net = gross - 2 * 0.5 = gross - 1.0
        self.assertAlmostEqual(opp.net_yield, opp.gross_yield - 1.0, places=8)

    def test_net_yield_is_gross_minus_one(self):
        snap = self._make_snap(rate_8h=0.005, spot_apy=2.0)
        opp = compute_opportunity(snap)
        self.assertAlmostEqual(opp.net_yield, opp.gross_yield - 1.0, places=8)

    def test_estimated_cost_pct_default(self):
        snap = self._make_snap()
        opp = compute_opportunity(snap)
        self.assertEqual(opp.estimated_cost_pct, 0.5)

    def test_is_attractive_true(self):
        # High funding rate → net_yield > 5
        snap = self._make_snap(rate_8h=0.05, spot_apy=4.0)
        opp = compute_opportunity(snap)
        self.assertTrue(opp.is_attractive)

    def test_is_attractive_false(self):
        # Low funding rate → net_yield < 5
        snap = self._make_snap(rate_8h=0.001, spot_apy=1.0)
        opp = compute_opportunity(snap)
        self.assertFalse(opp.is_attractive)

    def test_is_attractive_threshold(self):
        # net_yield must be > 5.0
        snap = self._make_snap(rate_8h=0.0, spot_apy=6.0)
        opp = compute_opportunity(snap)
        # net_yield = 6.0 - 1.0 = 5.0 → NOT attractive (> 5.0 required)
        self.assertFalse(opp.is_attractive)

    def test_confidence_high(self):
        # net_yield > 15 and liq_risk == LOW → HIGH
        snap = self._make_snap(rate_8h=0.01, spot_apy=10.0)
        opp = compute_opportunity(snap)
        # funding = 10.95, gross = 20.95, net = 19.95, liq_risk LOW
        self.assertEqual(opp.confidence, "HIGH")

    def test_confidence_medium(self):
        # net_yield > 8 but not HIGH
        snap = self._make_snap(rate_8h=0.005, spot_apy=5.0)
        opp = compute_opportunity(snap)
        # funding = 5.475, gross = 10.475, net = 9.475 → MEDIUM
        self.assertEqual(opp.confidence, "MEDIUM")

    def test_confidence_low(self):
        snap = self._make_snap(rate_8h=0.001, spot_apy=2.0)
        opp = compute_opportunity(snap)
        # funding = 1.095, gross = 3.095, net = 2.095 → LOW
        self.assertEqual(opp.confidence, "LOW")

    def test_recommendation_attractive(self):
        snap = self._make_snap(rate_8h=0.05, spot_apy=4.0)
        opp = compute_opportunity(snap)
        self.assertIn("Long ETH spot", opp.recommendation)
        self.assertIn("dYdX", opp.recommendation)
        self.assertIn("%/yr", opp.recommendation)

    def test_recommendation_unattractive(self):
        snap = self._make_snap(rate_8h=0.001, spot_apy=1.0)
        opp = compute_opportunity(snap)
        self.assertIn("Insufficient yield after costs", opp.recommendation)

    def test_symbol_passed_through(self):
        snap = self._make_snap(symbol="BTC")
        opp = compute_opportunity(snap)
        self.assertEqual(opp.symbol, "BTC")

    def test_exchange_in_short_venue(self):
        snap = self._make_snap(exchange="GMX")
        opp = compute_opportunity(snap)
        self.assertEqual(opp.short_venue, "GMX")

    def test_spot_apy_passed_through(self):
        snap = self._make_snap(spot_apy=5.5)
        opp = compute_opportunity(snap)
        self.assertEqual(opp.spot_apy, 5.5)

    def test_funding_rate_annual_correct(self):
        snap = self._make_snap(rate_8h=0.02)
        opp = compute_opportunity(snap)
        self.assertAlmostEqual(opp.funding_rate_annual, annualize_funding(0.02), places=8)

    def test_liquidation_risk_on_opportunity(self):
        # Low funding → LOW risk
        snap = self._make_snap(rate_8h=0.01)
        opp = compute_opportunity(snap)
        self.assertEqual(opp.liquidation_risk, "LOW")

    def test_basis_risk_eth(self):
        snap = self._make_snap(symbol="ETH")
        opp = compute_opportunity(snap)
        self.assertEqual(opp.basis_risk, "LOW")

    def test_basis_risk_shib(self):
        snap = self._make_snap(symbol="SHIB")
        opp = compute_opportunity(snap)
        self.assertEqual(opp.basis_risk, "HIGH")

    def test_custom_cost(self):
        snap = self._make_snap(rate_8h=0.01, spot_apy=3.5)
        opp = compute_opportunity(snap, estimated_cost_pct=1.0)
        self.assertAlmostEqual(opp.net_yield, opp.gross_yield - 2.0, places=8)


class TestAnalyzeMarket(unittest.TestCase):
    def _make_snapshots(self):
        ts = "2026-01-01T00:00:00Z"
        return [
            FundingRateSnapshot("ETH", "dYdX", 0.05, 3.5, ts),   # high positive
            FundingRateSnapshot("BTC", "dYdX", 0.01, 2.8, ts),   # moderate positive
            FundingRateSnapshot("SOL", "GMX", -0.002, 4.2, ts),  # negative (excluded)
        ]

    def test_empty_snapshots(self):
        result = analyze_market([])
        self.assertEqual(result.total_opportunities, 0)
        self.assertEqual(result.attractive_opportunities, 0)
        self.assertIsNone(result.best_opportunity)
        self.assertEqual(result.avg_funding_rate, 0.0)

    def test_opportunities_sorted_desc(self):
        snaps = self._make_snapshots()
        result = analyze_market(snaps)
        yields = [o.net_yield for o in result.opportunities]
        self.assertEqual(yields, sorted(yields, reverse=True))

    def test_negative_funding_excluded(self):
        # SOL has negative funding → not in opportunities
        snaps = self._make_snapshots()
        result = analyze_market(snaps)
        symbols_in_opps = [o.symbol for o in result.opportunities]
        self.assertNotIn("SOL", symbols_in_opps)

    def test_best_opportunity_is_highest_net_yield(self):
        snaps = self._make_snapshots()
        result = analyze_market(snaps)
        self.assertIsNotNone(result.best_opportunity)
        if result.opportunities:
            self.assertEqual(result.best_opportunity.net_yield, result.opportunities[0].net_yield)

    def test_avg_funding_rate_formula(self):
        ts = "2026-01-01T00:00:00Z"
        snaps = [
            FundingRateSnapshot("ETH", "dYdX", 0.01, 3.5, ts),
            FundingRateSnapshot("BTC", "dYdX", 0.03, 2.8, ts),
        ]
        result = analyze_market(snaps)
        expected_avg = (annualize_funding(0.01) + annualize_funding(0.03)) / 2
        self.assertAlmostEqual(result.avg_funding_rate, expected_avg, places=6)

    def test_max_funding_rate(self):
        snaps = self._make_snapshots()
        result = analyze_market(snaps)
        expected_max = max(annualize_funding(s.funding_rate_8h) for s in snaps)
        self.assertAlmostEqual(result.max_funding_rate, expected_max, places=6)

    def test_min_funding_rate(self):
        snaps = self._make_snapshots()
        result = analyze_market(snaps)
        expected_min = min(annualize_funding(s.funding_rate_8h) for s in snaps)
        self.assertAlmostEqual(result.min_funding_rate, expected_min, places=6)

    def test_attractive_opportunities_count(self):
        ts = "2026-01-01T00:00:00Z"
        snaps = [
            FundingRateSnapshot("ETH", "dYdX", 0.05, 4.0, ts),  # should be attractive
            FundingRateSnapshot("BTC", "dYdX", 0.001, 1.0, ts), # should not be attractive
        ]
        result = analyze_market(snaps)
        # Check each
        expected = sum(1 for o in result.opportunities if o.is_attractive)
        self.assertEqual(result.attractive_opportunities, expected)

    def test_total_opportunities_count(self):
        snaps = self._make_snapshots()
        result = analyze_market(snaps)
        # Only positive-funding snapshots
        expected = sum(1 for s in snaps if s.funding_rate_8h > 0)
        self.assertEqual(result.total_opportunities, expected)

    def test_regime_extreme_bull(self):
        ts = "2026-01-01T00:00:00Z"
        # avg > 50%
        snaps = [FundingRateSnapshot("ETH", "dYdX", 0.1, 3.5, ts)]  # 109.5% annual
        result = analyze_market(snaps)
        self.assertEqual(result.funding_regime, "EXTREME_BULL")

    def test_regime_bull(self):
        ts = "2026-01-01T00:00:00Z"
        # avg > 20%, ≤ 50%
        snaps = [FundingRateSnapshot("ETH", "dYdX", 0.025, 3.5, ts)]  # 27.375% annual
        result = analyze_market(snaps)
        self.assertEqual(result.funding_regime, "BULL")

    def test_regime_neutral(self):
        ts = "2026-01-01T00:00:00Z"
        # 0 < avg ≤ 20%
        snaps = [FundingRateSnapshot("ETH", "dYdX", 0.005, 3.5, ts)]  # 5.475% annual
        result = analyze_market(snaps)
        self.assertEqual(result.funding_regime, "NEUTRAL")

    def test_regime_bear(self):
        ts = "2026-01-01T00:00:00Z"
        # -20% ≤ avg < 0
        snaps = [FundingRateSnapshot("ETH", "dYdX", -0.005, 3.5, ts)]  # -5.475% annual
        result = analyze_market(snaps)
        self.assertEqual(result.funding_regime, "BEAR")

    def test_regime_extreme_bear(self):
        ts = "2026-01-01T00:00:00Z"
        # avg < -20%
        snaps = [FundingRateSnapshot("ETH", "dYdX", -0.025, 3.5, ts)]  # -27.375% annual
        result = analyze_market(snaps)
        self.assertEqual(result.funding_regime, "EXTREME_BEAR")

    def test_all_negative_funding_no_opps(self):
        ts = "2026-01-01T00:00:00Z"
        snaps = [
            FundingRateSnapshot("ETH", "dYdX", -0.01, 3.5, ts),
            FundingRateSnapshot("BTC", "dYdX", -0.005, 2.8, ts),
        ]
        result = analyze_market(snaps)
        self.assertEqual(result.total_opportunities, 0)
        self.assertEqual(result.attractive_opportunities, 0)
        self.assertIsNone(result.best_opportunity)

    def test_snapshots_preserved(self):
        snaps = self._make_snapshots()
        result = analyze_market(snaps)
        self.assertEqual(len(result.snapshots), len(snaps))


class TestTopN(unittest.TestCase):
    def test_top_n_returns_n_items(self):
        ts = "2026-01-01T00:00:00Z"
        snaps = [
            FundingRateSnapshot("ETH", "dYdX", 0.05, 3.5, ts),
            FundingRateSnapshot("BTC", "dYdX", 0.03, 2.8, ts),
            FundingRateSnapshot("SOL", "GMX", 0.01, 4.2, ts),
        ]
        result = analyze_market(snaps)
        top = top_n(result, 2)
        self.assertEqual(len(top), 2)

    def test_top_n_sorted_by_yield(self):
        ts = "2026-01-01T00:00:00Z"
        snaps = [
            FundingRateSnapshot("ETH", "dYdX", 0.05, 3.5, ts),
            FundingRateSnapshot("BTC", "dYdX", 0.01, 2.8, ts),
        ]
        result = analyze_market(snaps)
        top = top_n(result, 2)
        self.assertGreaterEqual(top[0].net_yield, top[1].net_yield)

    def test_top_n_larger_than_available(self):
        ts = "2026-01-01T00:00:00Z"
        snaps = [FundingRateSnapshot("ETH", "dYdX", 0.01, 3.5, ts)]
        result = analyze_market(snaps)
        top = top_n(result, 10)
        self.assertLessEqual(len(top), 10)

    def test_top_0_empty(self):
        ts = "2026-01-01T00:00:00Z"
        snaps = [FundingRateSnapshot("ETH", "dYdX", 0.01, 3.5, ts)]
        result = analyze_market(snaps)
        self.assertEqual(top_n(result, 0), [])


class TestSaveLoadHistory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_save_creates_file(self):
        snap = _snap()
        result = analyze_market([snap])
        save_results(result, data_dir=self.tmpdir)
        log_file = os.path.join(self.tmpdir, "funding_rate_arb_log.json")
        self.assertTrue(os.path.exists(log_file))

    def test_save_load_round_trip(self):
        snap = _snap()
        result = analyze_market([snap])
        save_results(result, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 1)

    def test_multiple_saves_accumulate(self):
        for _ in range(3):
            snap = _snap()
            result = analyze_market([snap])
            save_results(result, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 3)

    def test_ring_buffer_cap_100(self):
        for _ in range(105):
            snap = _snap()
            result = analyze_market([snap])
            save_results(result, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 100)

    def test_load_empty_returns_list(self):
        history = load_history(data_dir=self.tmpdir)
        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 0)

    def test_atomic_write_no_tmp_left(self):
        snap = _snap()
        result = analyze_market([snap])
        save_results(result, data_dir=self.tmpdir)
        tmp_file = os.path.join(self.tmpdir, "funding_rate_arb_log.json.tmp")
        self.assertFalse(os.path.exists(tmp_file))

    def test_saved_result_has_saved_at(self):
        snap = _snap()
        result = analyze_market([snap])
        save_results(result, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertIn("_saved_at", history[0])


class TestDataclassFields(unittest.TestCase):
    def test_snapshot_fields(self):
        snap = _snap()
        self.assertEqual(snap.symbol, "ETH")
        self.assertEqual(snap.exchange, "dYdX")
        self.assertEqual(snap.funding_rate_8h, 0.01)
        self.assertEqual(snap.spot_apy, 3.5)

    def test_result_fields_present(self):
        result = analyze_market([_snap()])
        self.assertIsInstance(result.snapshots, list)
        self.assertIsInstance(result.opportunities, list)
        self.assertIsInstance(result.avg_funding_rate, float)
        self.assertIsInstance(result.funding_regime, str)

    def test_opportunity_fields_present(self):
        opp = compute_opportunity(_snap())
        self.assertIsInstance(opp.gross_yield, float)
        self.assertIsInstance(opp.net_yield, float)
        self.assertIsInstance(opp.is_attractive, bool)
        self.assertIsInstance(opp.confidence, str)
        self.assertIsInstance(opp.recommendation, str)
        self.assertIsInstance(opp.liquidation_risk, str)
        self.assertIsInstance(opp.basis_risk, str)


if __name__ == "__main__":
    unittest.main()
