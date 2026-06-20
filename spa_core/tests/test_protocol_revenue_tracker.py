"""
Tests for MP-762: ProtocolRevenueTracker
≥65 unittest tests covering all specified cases.

Run: python3 -m unittest spa_core.tests.test_protocol_revenue_tracker -v
"""
from __future__ import annotations

import json
import os
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.protocol_revenue_tracker import (
    _RING_BUFFER_MAX,
    RevenueDataPoint,
    RevenueResult,
    RevenueTrend,
    analyze_market,
    analyze_protocol,
    compute_daily_fee,
    compute_growth,
    compute_revenue_to_tvl,
    get_trend_label,
    load_history,
    save_results,
    sustainability_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dp_dict(
    date_iso: str = "2026-06-01",
    daily_volume_usd: float = 1_000_000.0,
    fee_rate_bps: float = 30.0,
    tvl_usd: float = 10_000_000.0,
) -> dict:
    return {
        "date_iso": date_iso,
        "daily_volume_usd": daily_volume_usd,
        "fee_rate_bps": fee_rate_bps,
        "tvl_usd": tvl_usd,
    }


def _three_point_data(
    vol_first: float = 1_000_000,
    vol_last: float = 1_200_000,
    bps: float = 30,
    tvl: float = 10_000_000,
) -> list:
    return [
        _make_dp_dict("2026-06-01", vol_first, bps, tvl),
        _make_dp_dict("2026-06-07", (vol_first + vol_last) / 2, bps, tvl),
        _make_dp_dict("2026-06-13", vol_last, bps, tvl),
    ]


def _market_data(n: int = 2) -> list:
    protocols = [
        {"protocol": "ProtoA", "data_points": _three_point_data(1_000_000, 1_200_000)},
        {"protocol": "ProtoB", "data_points": _three_point_data(500_000, 600_000)},
        {"protocol": "ProtoC", "data_points": _three_point_data(2_000_000, 2_400_000)},
    ]
    return protocols[:n]


# ===========================================================================
# 1. compute_daily_fee
# ===========================================================================

class TestComputeDailyFee(unittest.TestCase):

    def test_formula_basic(self):
        # 1_000_000 * 30 / 10000 = 3000
        self.assertAlmostEqual(compute_daily_fee(1_000_000, 30), 3_000.0)

    def test_formula_10bps(self):
        # 50_000_000 * 10 / 10000 = 50_000
        self.assertAlmostEqual(compute_daily_fee(50_000_000, 10), 50_000.0)

    def test_zero_volume(self):
        self.assertAlmostEqual(compute_daily_fee(0.0, 30), 0.0)

    def test_zero_fee_rate(self):
        self.assertAlmostEqual(compute_daily_fee(1_000_000, 0), 0.0)

    def test_high_fee_rate(self):
        # 100bps = 1%  → 1_000_000 * 100 / 10000 = 10_000
        self.assertAlmostEqual(compute_daily_fee(1_000_000, 100), 10_000.0)

    def test_fractional_bps(self):
        # 0.5 bps
        self.assertAlmostEqual(compute_daily_fee(2_000_000, 0.5), 100.0)


# ===========================================================================
# 2. compute_revenue_to_tvl
# ===========================================================================

class TestComputeRevenueToTvl(unittest.TestCase):

    def test_formula_basic(self):
        # annualized=1_000_000, tvl=100_000_000 → 1.0%
        self.assertAlmostEqual(compute_revenue_to_tvl(1_000_000, 100_000_000), 1.0)

    def test_tvl_zero_returns_zero(self):
        self.assertAlmostEqual(compute_revenue_to_tvl(500_000, 0), 0.0)

    def test_tvl_equals_annualized(self):
        # 100% revenue/TVL
        self.assertAlmostEqual(compute_revenue_to_tvl(5_000, 5_000), 100.0)

    def test_very_small_tvl(self):
        result = compute_revenue_to_tvl(100, 10)
        self.assertAlmostEqual(result, 1000.0)

    def test_zero_annualized(self):
        self.assertAlmostEqual(compute_revenue_to_tvl(0, 1_000_000), 0.0)


# ===========================================================================
# 3. compute_growth
# ===========================================================================

class TestComputeGrowth(unittest.TestCase):

    def test_positive_growth(self):
        # (120 - 100) / 100 * 100 = 20%
        self.assertAlmostEqual(compute_growth(100, 120), 20.0)

    def test_negative_growth(self):
        # (80 - 100) / 100 * 100 = -20%
        self.assertAlmostEqual(compute_growth(100, 80), -20.0)

    def test_first_zero_returns_zero(self):
        self.assertAlmostEqual(compute_growth(0, 100), 0.0)

    def test_no_change(self):
        self.assertAlmostEqual(compute_growth(50, 50), 0.0)

    def test_zero_latest(self):
        # (0 - 100) / 100 * 100 = -100%
        self.assertAlmostEqual(compute_growth(100, 0), -100.0)

    def test_double(self):
        self.assertAlmostEqual(compute_growth(50, 100), 100.0)


# ===========================================================================
# 4. sustainability_score
# ===========================================================================

class TestSustainabilityScore(unittest.TestCase):

    def test_formula_basic(self):
        # 5% revenue/TVL → 50
        self.assertAlmostEqual(sustainability_score(5.0), 50.0)

    def test_ten_pct_gives_100(self):
        self.assertAlmostEqual(sustainability_score(10.0), 100.0)

    def test_capped_at_100(self):
        self.assertAlmostEqual(sustainability_score(15.0), 100.0)
        self.assertAlmostEqual(sustainability_score(50.0), 100.0)

    def test_zero(self):
        self.assertAlmostEqual(sustainability_score(0.0), 0.0)

    def test_small(self):
        self.assertAlmostEqual(sustainability_score(0.1), 1.0)


# ===========================================================================
# 5. get_trend_label
# ===========================================================================

class TestGetTrendLabel(unittest.TestCase):

    def test_growing(self):
        self.assertEqual(get_trend_label(20.0), "GROWING")

    def test_growing_boundary_just_above_10(self):
        self.assertEqual(get_trend_label(10.1), "GROWING")

    def test_stable_exactly_10(self):
        self.assertEqual(get_trend_label(10.0), "STABLE")

    def test_stable_zero(self):
        self.assertEqual(get_trend_label(0.0), "STABLE")

    def test_stable_exactly_minus10(self):
        self.assertEqual(get_trend_label(-10.0), "STABLE")

    def test_declining(self):
        self.assertEqual(get_trend_label(-20.0), "DECLINING")

    def test_declining_boundary_just_below_minus10(self):
        self.assertEqual(get_trend_label(-10.1), "DECLINING")


# ===========================================================================
# 6. RevenueDataPoint dataclass
# ===========================================================================

class TestRevenueDataPoint(unittest.TestCase):

    def _make(self, vol=1_000_000, bps=30, tvl=10_000_000):
        return RevenueDataPoint(
            protocol="TestProto",
            date_iso="2026-06-01",
            daily_volume_usd=vol,
            fee_rate_bps=bps,
            tvl_usd=tvl,
        )

    def test_protocol_field(self):
        dp = self._make()
        self.assertEqual(dp.protocol, "TestProto")

    def test_date_iso_field(self):
        dp = self._make()
        self.assertEqual(dp.date_iso, "2026-06-01")

    def test_daily_volume_field(self):
        dp = self._make()
        self.assertAlmostEqual(dp.daily_volume_usd, 1_000_000.0)

    def test_fee_rate_bps_field(self):
        dp = self._make()
        self.assertAlmostEqual(dp.fee_rate_bps, 30.0)

    def test_tvl_usd_field(self):
        dp = self._make()
        self.assertAlmostEqual(dp.tvl_usd, 10_000_000.0)

    def test_daily_fee_computed(self):
        # 1_000_000 * 30 / 10000 = 3000
        dp = self._make()
        self.assertAlmostEqual(dp.daily_fee_revenue_usd, 3_000.0)

    def test_annualized_revenue_is_daily_times_365(self):
        dp = self._make()
        self.assertAlmostEqual(dp.annualized_revenue_usd, dp.daily_fee_revenue_usd * 365)

    def test_revenue_to_tvl_computed(self):
        dp = self._make()
        expected = dp.annualized_revenue_usd / dp.tvl_usd * 100
        self.assertAlmostEqual(dp.revenue_to_tvl_pct, expected, places=6)

    def test_revenue_to_tvl_zero_tvl(self):
        dp = self._make(tvl=0)
        self.assertAlmostEqual(dp.revenue_to_tvl_pct, 0.0)

    def test_zero_volume_zero_fee(self):
        dp = self._make(vol=0)
        self.assertAlmostEqual(dp.daily_fee_revenue_usd, 0.0)
        self.assertAlmostEqual(dp.annualized_revenue_usd, 0.0)


# ===========================================================================
# 7. analyze_protocol
# ===========================================================================

class TestAnalyzeProtocol(unittest.TestCase):

    def _trend(self, data_points=None, **kwargs):
        if data_points is None:
            data_points = _three_point_data(**kwargs)
        return analyze_protocol("TestProto", data_points)

    def test_returns_revenue_trend(self):
        self.assertIsInstance(self._trend(), RevenueTrend)

    def test_protocol_name(self):
        t = self._trend()
        self.assertEqual(t.protocol, "TestProto")

    def test_data_points_count(self):
        t = self._trend()
        self.assertEqual(len(t.data_points), 3)

    def test_data_points_sorted_by_date(self):
        # Provide out-of-order data
        data = [
            _make_dp_dict("2026-06-13", 1_200_000),
            _make_dp_dict("2026-06-01", 1_000_000),
            _make_dp_dict("2026-06-07", 1_100_000),
        ]
        t = analyze_protocol("P", data)
        dates = [dp.date_iso for dp in t.data_points]
        self.assertEqual(dates, sorted(dates))

    def test_total_cumulative_is_sum_of_daily_fees(self):
        t = self._trend()
        expected = sum(dp.daily_fee_revenue_usd for dp in t.data_points)
        self.assertAlmostEqual(t.total_cumulative_revenue_usd, expected, places=6)

    def test_avg_daily_revenue(self):
        t = self._trend()
        expected = t.total_cumulative_revenue_usd / len(t.data_points)
        self.assertAlmostEqual(t.avg_daily_revenue_usd, expected, places=6)

    def test_peak_daily_revenue(self):
        t = self._trend()
        expected = max(dp.daily_fee_revenue_usd for dp in t.data_points)
        self.assertAlmostEqual(t.peak_daily_revenue_usd, expected, places=6)

    def test_latest_daily_revenue_is_last_point(self):
        t = self._trend()
        self.assertAlmostEqual(
            t.latest_daily_revenue_usd,
            t.data_points[-1].daily_fee_revenue_usd,
            places=6,
        )

    def test_growth_pct_growing(self):
        # vol goes from 1M to 1.2M → 20% growth in fee
        t = self._trend(vol_first=1_000_000, vol_last=1_200_000)
        self.assertAlmostEqual(t.revenue_growth_pct, 20.0, places=6)

    def test_growth_pct_declining(self):
        t = self._trend(vol_first=1_200_000, vol_last=1_000_000)
        # (1M - 1.2M) / 1.2M * 100 = -16.67%
        self.assertAlmostEqual(t.revenue_growth_pct,
                               (1_000_000 - 1_200_000) / 1_200_000 * 100, places=4)

    def test_trend_label_growing(self):
        # 20% growth → GROWING
        t = self._trend(vol_first=1_000_000, vol_last=1_200_000)
        self.assertEqual(t.trend_label, "GROWING")

    def test_trend_label_stable(self):
        # Same volume → 0% → STABLE
        t = self._trend(vol_first=1_000_000, vol_last=1_000_000)
        self.assertEqual(t.trend_label, "STABLE")

    def test_trend_label_declining(self):
        t = self._trend(vol_first=1_000_000, vol_last=800_000)
        self.assertEqual(t.trend_label, "DECLINING")

    def test_sustainability_score_from_latest_r2tvl(self):
        t = self._trend()
        latest_r2tvl = t.data_points[-1].revenue_to_tvl_pct
        expected = min(100.0, latest_r2tvl * 10.0)
        self.assertAlmostEqual(t.sustainability_score, expected, places=6)

    def test_implied_apy_equals_latest_r2tvl(self):
        t = self._trend()
        self.assertAlmostEqual(
            t.implied_sustainable_apy_pct,
            t.data_points[-1].revenue_to_tvl_pct,
            places=6,
        )

    def test_recommendation_declining(self):
        t = self._trend(vol_first=1_000_000, vol_last=800_000)
        self.assertIn("declining", t.recommendation.lower())

    def test_recommendation_growing(self):
        t = self._trend(vol_first=1_000_000, vol_last=1_200_000)
        self.assertIn("growing", t.recommendation.lower())

    def test_recommendation_stable(self):
        t = self._trend(vol_first=1_000_000, vol_last=1_000_000)
        self.assertIn("stable", t.recommendation.lower())

    def test_recommendation_is_string(self):
        t = self._trend()
        self.assertIsInstance(t.recommendation, str)
        self.assertGreater(len(t.recommendation), 0)

    def test_single_data_point_growth_zero(self):
        data = [_make_dp_dict("2026-06-01", 1_000_000)]
        t = analyze_protocol("Solo", data)
        self.assertAlmostEqual(t.revenue_growth_pct, 0.0)

    def test_single_data_point_trend_stable(self):
        data = [_make_dp_dict("2026-06-01", 1_000_000)]
        t = analyze_protocol("Solo", data)
        self.assertEqual(t.trend_label, "STABLE")

    def test_single_data_point_peak_equals_avg_equals_latest(self):
        data = [_make_dp_dict("2026-06-01", 1_000_000, 30, 10_000_000)]
        t = analyze_protocol("Solo", data)
        self.assertAlmostEqual(t.peak_daily_revenue_usd, t.avg_daily_revenue_usd)
        self.assertAlmostEqual(t.peak_daily_revenue_usd, t.latest_daily_revenue_usd)

    def test_all_same_volume_zero_growth_stable(self):
        data = [
            _make_dp_dict("2026-06-01", 1_000_000),
            _make_dp_dict("2026-06-05", 1_000_000),
            _make_dp_dict("2026-06-10", 1_000_000),
        ]
        t = analyze_protocol("Flat", data)
        self.assertAlmostEqual(t.revenue_growth_pct, 0.0)
        self.assertEqual(t.trend_label, "STABLE")

    def test_large_growth_high_sustainability(self):
        # Very high tvl → low r2tvl; or low tvl → high r2tvl
        data = [
            _make_dp_dict("2026-06-01", 1_000_000, 30, 100_000),   # small TVL → high r2tvl
        ]
        t = analyze_protocol("HighR2TVL", data)
        # annualized = 3000*365=1_095_000; r2tvl = 1_095_000/100_000*100 = 1095%
        # sustainability = min(100, 1095*10) = 100
        self.assertAlmostEqual(t.sustainability_score, 100.0)


# ===========================================================================
# 8. analyze_market
# ===========================================================================

class TestAnalyzeMarket(unittest.TestCase):

    def test_returns_revenue_result(self):
        r = analyze_market(_market_data(2))
        self.assertIsInstance(r, RevenueResult)

    def test_highest_revenue_protocol(self):
        # ProtoC has double the volume of ProtoA
        data = [
            {"protocol": "Small", "data_points": _three_point_data(500_000, 600_000)},
            {"protocol": "Large", "data_points": _three_point_data(2_000_000, 2_400_000)},
        ]
        r = analyze_market(data)
        self.assertEqual(r.highest_revenue_protocol, "Large")

    def test_fastest_growing_protocol(self):
        data = [
            {"protocol": "Slow", "data_points": _three_point_data(1_000_000, 1_050_000)},
            {"protocol": "Fast", "data_points": _three_point_data(1_000_000, 2_000_000)},
        ]
        r = analyze_market(data)
        self.assertEqual(r.fastest_growing_protocol, "Fast")

    def test_most_sustainable_protocol(self):
        # Low TVL → high r2tvl → high sustainability
        data = [
            {"protocol": "LowSus", "data_points": [_make_dp_dict("2026-06-01", 1_000, 10, 1_000_000_000)]},
            {"protocol": "HighSus", "data_points": [_make_dp_dict("2026-06-01", 1_000_000, 30, 100_000)]},
        ]
        r = analyze_market(data)
        self.assertEqual(r.most_sustainable_protocol, "HighSus")

    def test_avg_sustainability_formula(self):
        r = analyze_market(_market_data(3))
        expected = sum(t.sustainability_score for t in r.trends) / len(r.trends)
        self.assertAlmostEqual(r.avg_sustainability_score, expected, places=6)

    def test_market_label_bull(self):
        # All fast-growing protocols → BULL
        data = [
            {"protocol": f"P{i}", "data_points": _three_point_data(1_000_000, 2_000_000)}
            for i in range(3)
        ]
        r = analyze_market(data)
        self.assertEqual(r.market_revenue_label, "BULL_REVENUE")

    def test_market_label_stable(self):
        data = [
            {"protocol": f"P{i}", "data_points": _three_point_data(1_000_000, 1_000_000)}
            for i in range(3)
        ]
        r = analyze_market(data)
        self.assertEqual(r.market_revenue_label, "STABLE_REVENUE")

    def test_market_label_bear(self):
        data = [
            {"protocol": f"P{i}", "data_points": _three_point_data(2_000_000, 1_000_000)}
            for i in range(3)
        ]
        r = analyze_market(data)
        self.assertEqual(r.market_revenue_label, "BEAR_REVENUE")

    def test_recommendation_summary_is_string(self):
        r = analyze_market(_market_data(2))
        self.assertIsInstance(r.recommendation_summary, str)
        self.assertGreater(len(r.recommendation_summary), 0)

    def test_saved_to_defaults_empty(self):
        r = analyze_market(_market_data(2))
        self.assertEqual(r.saved_to, "")

    def test_single_protocol(self):
        data = [{"protocol": "Only", "data_points": _three_point_data()}]
        r = analyze_market(data)
        self.assertEqual(r.highest_revenue_protocol, "Only")
        self.assertEqual(r.fastest_growing_protocol, "Only")
        self.assertEqual(r.most_sustainable_protocol, "Only")

    def test_trends_list_length(self):
        data = _market_data(3)
        r = analyze_market(data)
        self.assertEqual(len(r.trends), 3)

    def test_market_boundary_exactly_10pct_stable(self):
        # Construct data with exactly 10% growth → avg_growth = 10 → STABLE (not > 10)
        data = [
            {"protocol": "Boundary", "data_points": _three_point_data(1_000_000, 1_100_000)},
        ]
        r = analyze_market(data)
        # growth = (1.1M - 1M) / 1M * 100 = 10%  → STABLE
        self.assertEqual(r.market_revenue_label, "STABLE_REVENUE")

    def test_market_boundary_exactly_minus10pct_stable(self):
        data = [
            {"protocol": "Boundary", "data_points": _three_point_data(1_100_000, 1_000_000)},
        ]
        r = analyze_market(data)
        # growth = (1M - 1.1M) / 1.1M * 100 ≈ -9.09%  → STABLE
        self.assertEqual(r.market_revenue_label, "STABLE_REVENUE")


# ===========================================================================
# 9. Persistence: save_results / load_history
# ===========================================================================

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _result(self):
        return analyze_market(_market_data(2))

    def test_load_history_empty_when_file_missing(self):
        h = load_history(self.data_dir)
        self.assertEqual(h, [])

    def test_load_history_empty_on_corrupt_file(self):
        log = self.data_dir / "protocol_revenue_log.json"
        log.write_text("NOT JSON !!!")
        h = load_history(self.data_dir)
        self.assertEqual(h, [])

    def test_save_creates_file(self):
        r = self._result()
        save_results(r, self.data_dir)
        self.assertTrue((self.data_dir / "protocol_revenue_log.json").exists())

    def test_save_sets_saved_to(self):
        r = self._result()
        save_results(r, self.data_dir)
        self.assertIn("protocol_revenue_log.json", r.saved_to)

    def test_round_trip(self):
        r = self._result()
        save_results(r, self.data_dir)
        history = load_history(self.data_dir)
        self.assertEqual(len(history), 1)
        self.assertIn("market_revenue_label", history[0])
        self.assertIn("trends", history[0])

    def test_appends_to_existing(self):
        for _ in range(3):
            save_results(self._result(), self.data_dir)
        history = load_history(self.data_dir)
        self.assertEqual(len(history), 3)

    def test_ring_buffer_cap(self):
        for _ in range(_RING_BUFFER_MAX + 5):
            save_results(self._result(), self.data_dir)
        history = load_history(self.data_dir)
        self.assertLessEqual(len(history), _RING_BUFFER_MAX)

    def test_ring_buffer_keeps_latest(self):
        # Save 105 entries; only last 100 remain
        for i in range(105):
            r = self._result()
            save_results(r, self.data_dir)
        history = load_history(self.data_dir)
        self.assertEqual(len(history), _RING_BUFFER_MAX)

    def test_saved_at_key_present(self):
        r = self._result()
        save_results(r, self.data_dir)
        history = load_history(self.data_dir)
        self.assertIn("saved_at", history[0])

    def test_market_label_preserved_in_history(self):
        r = self._result()
        save_results(r, self.data_dir)
        history = load_history(self.data_dir)
        self.assertEqual(
            history[0]["market_revenue_label"],
            r.market_revenue_label,
        )

    def test_highest_revenue_protocol_preserved(self):
        r = self._result()
        save_results(r, self.data_dir)
        history = load_history(self.data_dir)
        self.assertEqual(
            history[0]["highest_revenue_protocol"],
            r.highest_revenue_protocol,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
