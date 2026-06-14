"""
Tests for MP-657: FundingRateMonitor
≥65 unittest tests covering all specified cases.
Run: python3 -m unittest spa_core.tests.test_funding_rate_monitor -v
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics.funding_rate_monitor import (
    FundingRateMonitor,
    FundingRateSnapshot,
    THRESHOLDS,
    MAX_ENTRIES,
)


class TestAnnualize(unittest.TestCase):
    """_annualize: rate_8h → annual."""

    def setUp(self):
        self.m = FundingRateMonitor()

    def test_typical_positive(self):
        # 0.0001 * 3 * 365 = 0.1095
        self.assertAlmostEqual(self.m._annualize(0.0001), 0.1095, places=6)

    def test_zero_rate(self):
        self.assertEqual(self.m._annualize(0.0), 0.0)

    def test_negative_rate(self):
        # -0.0001 * 3 * 365 = -0.1095
        self.assertAlmostEqual(self.m._annualize(-0.0001), -0.1095, places=6)

    def test_large_positive(self):
        # 0.001 * 3 * 365 = 1.095
        self.assertAlmostEqual(self.m._annualize(0.001), 1.095, places=6)

    def test_small_rate(self):
        # 0.00001 * 3 * 365 = 0.01095
        self.assertAlmostEqual(self.m._annualize(0.00001), 0.01095, places=6)

    def test_return_is_rounded_6dp(self):
        result = self.m._annualize(0.0001234)
        self.assertEqual(result, round(0.0001234 * 3 * 365, 6))

    def test_formula_multiplier(self):
        # Verify factor is exactly 3*365 = 1095
        rate = 0.001
        self.assertAlmostEqual(self.m._annualize(rate), rate * 1095, places=9)


class TestRegime(unittest.TestCase):
    """_regime: correct classification for all zones."""

    def setUp(self):
        self.m = FundingRateMonitor()

    def test_extreme_positive_above(self):
        self.assertEqual(self.m._regime(0.60), "EXTREME_POSITIVE")

    def test_extreme_positive_boundary(self):
        self.assertEqual(self.m._regime(0.50), "EXTREME_POSITIVE")

    def test_bullish_above_threshold(self):
        self.assertEqual(self.m._regime(0.35), "BULLISH")

    def test_bullish_at_high_positive_boundary(self):
        self.assertEqual(self.m._regime(0.20), "BULLISH")

    def test_bullish_just_below_extreme(self):
        self.assertEqual(self.m._regime(0.499), "BULLISH")

    def test_neutral_mid(self):
        self.assertEqual(self.m._regime(0.00), "NEUTRAL")

    def test_neutral_at_upper(self):
        self.assertEqual(self.m._regime(0.05), "NEUTRAL")

    def test_neutral_just_above_lower(self):
        self.assertEqual(self.m._regime(-0.04), "NEUTRAL")

    def test_neutral_at_lower_boundary(self):
        self.assertEqual(self.m._regime(-0.05), "NEUTRAL")

    def test_bearish_below_neutral_lower(self):
        self.assertEqual(self.m._regime(-0.10), "BEARISH")

    def test_bearish_at_high_negative_boundary(self):
        self.assertEqual(self.m._regime(-0.20), "BEARISH")

    def test_bearish_just_above_extreme(self):
        self.assertEqual(self.m._regime(-0.199), "BEARISH")

    def test_extreme_negative_below(self):
        self.assertEqual(self.m._regime(-0.30), "EXTREME_NEGATIVE")

    def test_extreme_negative_far_below(self):
        self.assertEqual(self.m._regime(-1.00), "EXTREME_NEGATIVE")


class TestCarryOpportunity(unittest.TestCase):
    """_carry_opportunity: >10% annual is True, ≤10% is False."""

    def setUp(self):
        self.m = FundingRateMonitor()

    def test_above_10_pct(self):
        self.assertTrue(self.m._carry_opportunity(0.11))

    def test_exactly_10_pct_is_false(self):
        self.assertFalse(self.m._carry_opportunity(0.10))

    def test_below_10_pct(self):
        self.assertFalse(self.m._carry_opportunity(0.05))

    def test_zero(self):
        self.assertFalse(self.m._carry_opportunity(0.0))

    def test_negative(self):
        self.assertFalse(self.m._carry_opportunity(-0.05))

    def test_high_positive(self):
        self.assertTrue(self.m._carry_opportunity(0.50))

    def test_just_above_threshold(self):
        self.assertTrue(self.m._carry_opportunity(0.1001))

    def test_just_below_threshold(self):
        self.assertFalse(self.m._carry_opportunity(0.0999))


class TestAdvisory(unittest.TestCase):
    """_advisory: returns non-empty string for all 5 regimes."""

    def setUp(self):
        self.m = FundingRateMonitor()

    def test_extreme_positive_non_empty(self):
        s = self.m._advisory("EXTREME_POSITIVE", True, 500)
        self.assertTrue(len(s) > 0)

    def test_bullish_non_empty(self):
        s = self.m._advisory("BULLISH", True, 200)
        self.assertTrue(len(s) > 0)

    def test_neutral_non_empty(self):
        s = self.m._advisory("NEUTRAL", False, -100)
        self.assertTrue(len(s) > 0)

    def test_bearish_non_empty(self):
        s = self.m._advisory("BEARISH", False, -500)
        self.assertTrue(len(s) > 0)

    def test_extreme_negative_non_empty(self):
        s = self.m._advisory("EXTREME_NEGATIVE", False, -1000)
        self.assertTrue(len(s) > 0)

    def test_carry_and_positive_vs_spa_appends_bps(self):
        s = self.m._advisory("BULLISH", True, 300)
        self.assertIn("300", s)
        self.assertIn("bps", s)

    def test_carry_false_no_bps_appendix(self):
        s = self.m._advisory("BULLISH", False, 300)
        self.assertNotIn("bps", s)

    def test_carry_true_but_negative_vs_spa_no_appendix(self):
        s = self.m._advisory("BULLISH", True, -50)
        self.assertNotIn("bps", s)


class TestAnalyze(unittest.TestCase):
    """analyze(): correct field values for various inputs."""

    def setUp(self):
        self.m = FundingRateMonitor(spa_reference_apy=0.10)

    def test_returns_snapshot_instance(self):
        snap = self.m.analyze("ETH", "Binance", 0.0001)
        self.assertIsInstance(snap, FundingRateSnapshot)

    def test_asset_and_exchange_preserved(self):
        snap = self.m.analyze("BTC", "dYdX", 0.0002)
        self.assertEqual(snap.asset, "BTC")
        self.assertEqual(snap.exchange, "dYdX")

    def test_annualization_correct(self):
        snap = self.m.analyze("ETH", "Binance", 0.0001)
        self.assertAlmostEqual(snap.funding_rate_annual, 0.0001 * 3 * 365, places=6)

    def test_regime_assigned_correctly_bullish(self):
        # 0.0003 * 1095 = 0.3285 → BULLISH
        snap = self.m.analyze("ETH", "Binance", 0.0003)
        self.assertEqual(snap.regime, "BULLISH")

    def test_regime_neutral_zero_rate(self):
        snap = self.m.analyze("ETH", "Binance", 0.0)
        self.assertEqual(snap.regime, "NEUTRAL")

    def test_carry_opportunity_true_when_high(self):
        # 0.0001 * 1095 = 0.1095 > 0.10
        snap = self.m.analyze("ETH", "Binance", 0.0001)
        self.assertTrue(snap.carry_opportunity)

    def test_carry_opportunity_false_when_low(self):
        snap = self.m.analyze("ETH", "Binance", 0.00005)
        self.assertFalse(snap.carry_opportunity)

    def test_carry_vs_spa_bps_formula(self):
        # annual = 0.0001 * 1095 = 0.1095; bps = (0.1095 - 0.10) * 10000 = 95
        snap = self.m.analyze("ETH", "Binance", 0.0001)
        expected = round((snap.funding_rate_annual - 0.10) * 10000, 2)
        self.assertAlmostEqual(snap.carry_vs_spa_bps, expected, places=2)

    def test_funding_rate_8h_rounded(self):
        snap = self.m.analyze("ETH", "Binance", 0.000123456789)
        self.assertEqual(snap.funding_rate_8h, round(0.000123456789, 8))

    def test_advisory_non_empty(self):
        snap = self.m.analyze("ETH", "Binance", 0.0001)
        self.assertTrue(len(snap.advisory) > 0)

    def test_custom_spa_reference_apy(self):
        m2 = FundingRateMonitor(spa_reference_apy=0.05)
        snap = m2.analyze("ETH", "Binance", 0.0001)
        expected = round((snap.funding_rate_annual - 0.05) * 10000, 2)
        self.assertAlmostEqual(snap.carry_vs_spa_bps, expected, places=2)

    def test_negative_rate_regime_extreme_negative(self):
        # -0.001 * 1095 = -1.095 → EXTREME_NEGATIVE
        snap = self.m.analyze("ETH", "Binance", -0.001)
        self.assertEqual(snap.regime, "EXTREME_NEGATIVE")

    def test_extreme_positive_regime(self):
        # 0.0006 * 1095 = 0.657 → EXTREME_POSITIVE
        snap = self.m.analyze("ETH", "Binance", 0.0006)
        self.assertEqual(snap.regime, "EXTREME_POSITIVE")


class TestBestCarry(unittest.TestCase):
    """best_carry: returns highest annual rate or None."""

    def setUp(self):
        self.m = FundingRateMonitor()

    def test_empty_returns_none(self):
        self.assertIsNone(self.m.best_carry([]))

    def test_single_item(self):
        snap = self.m.analyze("ETH", "Binance", 0.0001)
        result = self.m.best_carry([snap])
        self.assertIs(result, snap)

    def test_picks_highest_annual_rate(self):
        s1 = self.m.analyze("ETH", "Binance", 0.0001)
        s2 = self.m.analyze("BTC", "Binance", 0.0005)
        s3 = self.m.analyze("SOL", "Binance", 0.0002)
        best = self.m.best_carry([s1, s2, s3])
        self.assertIs(best, s2)

    def test_negative_rates_picks_least_negative(self):
        s1 = self.m.analyze("ETH", "Binance", -0.001)
        s2 = self.m.analyze("BTC", "Binance", -0.0001)
        best = self.m.best_carry([s1, s2])
        self.assertIs(best, s2)

    def test_two_items_returns_correct_one(self):
        s1 = self.m.analyze("ETH", "Binance", 0.0003)
        s2 = self.m.analyze("BTC", "Binance", 0.0002)
        self.assertIs(self.m.best_carry([s1, s2]), s1)


class TestCarryOpportunities(unittest.TestCase):
    """carry_opportunities: filters to carry_opportunity=True."""

    def setUp(self):
        self.m = FundingRateMonitor()

    def test_empty_returns_empty(self):
        self.assertEqual(self.m.carry_opportunities([]), [])

    def test_none_qualify(self):
        s = self.m.analyze("ETH", "Binance", 0.00005)
        self.assertEqual(self.m.carry_opportunities([s]), [])

    def test_all_qualify(self):
        s1 = self.m.analyze("ETH", "Binance", 0.0002)
        s2 = self.m.analyze("BTC", "Binance", 0.0003)
        result = self.m.carry_opportunities([s1, s2])
        self.assertEqual(len(result), 2)

    def test_mixed_filters_correctly(self):
        s_high = self.m.analyze("ETH", "Binance", 0.0002)   # annual ≈ 0.219 > 0.10
        s_low = self.m.analyze("BTC", "Binance", 0.00005)   # annual ≈ 0.055 < 0.10
        result = self.m.carry_opportunities([s_high, s_low])
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], s_high)

    def test_boundary_exactly_10pct_excluded(self):
        # rate_8h where annual = exactly 0.10: 0.10 / 1095
        rate = 0.10 / 1095
        snap = self.m.analyze("ETH", "Binance", rate)
        self.assertFalse(snap.carry_opportunity)
        self.assertEqual(self.m.carry_opportunities([snap]), [])


class TestSaveAndLoad(unittest.TestCase):
    """save_snapshots / load_history: atomic write, ring-buffer, persistence."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_file = Path(self.tmpdir) / "test_funding_log.json"
        self.m = FundingRateMonitor(data_file=self.data_file)

    def _make_snap(self, asset="ETH", rate_8h=0.0001):
        return self.m.analyze(asset, "Binance", rate_8h)

    def test_save_creates_file(self):
        self.m.save_snapshots([self._make_snap()])
        self.assertTrue(self.data_file.exists())

    def test_save_is_valid_json(self):
        self.m.save_snapshots([self._make_snap()])
        data = json.loads(self.data_file.read_text())
        self.assertIsInstance(data, list)

    def test_saved_entry_has_required_keys(self):
        self.m.save_snapshots([self._make_snap()])
        entry = json.loads(self.data_file.read_text())[0]
        for key in ("timestamp", "asset", "exchange", "funding_rate_annual", "regime", "carry_opportunity"):
            self.assertIn(key, entry)

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(self.m.load_history(), [])

    def test_load_history_returns_saved_entries(self):
        self.m.save_snapshots([self._make_snap("ETH"), self._make_snap("BTC", 0.0002)])
        hist = self.m.load_history()
        self.assertEqual(len(hist), 2)

    def test_ring_buffer_max_100(self):
        snaps = [self._make_snap(f"A{i}", 0.0001) for i in range(110)]
        self.m.save_snapshots(snaps)
        hist = self.m.load_history()
        self.assertLessEqual(len(hist), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        # Save 60 entries, then 60 more; only last 100 remain
        for batch in range(2):
            snaps = [self._make_snap(f"X{batch}_{i}") for i in range(60)]
            self.m.save_snapshots(snaps)
        hist = self.m.load_history()
        self.assertEqual(len(hist), MAX_ENTRIES)

    def test_atomic_write_no_tmp_left_after_save(self):
        self.m.save_snapshots([self._make_snap()])
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_save_appends_across_calls(self):
        self.m.save_snapshots([self._make_snap("ETH")])
        self.m.save_snapshots([self._make_snap("BTC")])
        hist = self.m.load_history()
        self.assertEqual(len(hist), 2)

    def test_custom_spa_reference_in_constructor(self):
        m2 = FundingRateMonitor(data_file=self.data_file, spa_reference_apy=0.08)
        self.assertEqual(m2.spa_reference_apy, 0.08)
        snap = m2.analyze("ETH", "Binance", 0.0001)
        expected = round((snap.funding_rate_annual - 0.08) * 10000, 2)
        self.assertAlmostEqual(snap.carry_vs_spa_bps, expected, places=2)


if __name__ == "__main__":
    unittest.main()
