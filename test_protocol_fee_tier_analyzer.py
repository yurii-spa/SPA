"""
Tests for MP-844 ProtocolFeeTierAnalyzer
==========================================
Run with: python3 -m unittest spa_core/tests/test_protocol_fee_tier_analyzer.py
≥ 65 test cases.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_fee_tier_analyzer import (
    _annualized_fee_yield_pct,
    _capital_efficiency,
    _effective_yield_pct,
    _fee_tier_label,
    _is_filtered,
    _log_result,
    _lp_recommendation,
    _range_risk,
    _volume_to_tvl_ratio,
    analyze,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool(
    protocol="Uniswap V3",
    pair="USDC/ETH",
    fee_tier_bps=30,
    tvl_usd=1_000_000.0,
    volume_24h_usd=100_000.0,
    liquidity_concentration=0.5,
    in_range_pct=75.0,
):
    return dict(
        protocol=protocol,
        pair=pair,
        fee_tier_bps=fee_tier_bps,
        tvl_usd=tvl_usd,
        volume_24h_usd=volume_24h_usd,
        liquidity_concentration=liquidity_concentration,
        in_range_pct=in_range_pct,
    )


# ===========================================================================
# Unit helper tests
# ===========================================================================

class TestFeeTierLabel(unittest.TestCase):
    def test_5bps(self):
        self.assertEqual(_fee_tier_label(5), "0.05%")

    def test_30bps(self):
        self.assertEqual(_fee_tier_label(30), "0.30%")

    def test_100bps(self):
        self.assertEqual(_fee_tier_label(100), "1.00%")

    def test_1bps(self):
        self.assertEqual(_fee_tier_label(1), "0.01%")

    def test_200bps(self):
        self.assertEqual(_fee_tier_label(200), "2.00%")

    def test_zero_bps(self):
        self.assertEqual(_fee_tier_label(0), "0.00%")


class TestVolumeToTvlRatio(unittest.TestCase):
    def test_basic_ratio(self):
        result = _volume_to_tvl_ratio(1_000.0, 10_000.0)
        self.assertAlmostEqual(result, 0.1)

    def test_zero_tvl_returns_zero(self):
        self.assertAlmostEqual(_volume_to_tvl_ratio(1_000.0, 0.0), 0.0)

    def test_zero_volume(self):
        self.assertAlmostEqual(_volume_to_tvl_ratio(0.0, 10_000.0), 0.0)

    def test_equal_volume_tvl(self):
        self.assertAlmostEqual(_volume_to_tvl_ratio(5_000.0, 5_000.0), 1.0)

    def test_volume_greater_than_tvl(self):
        result = _volume_to_tvl_ratio(20_000.0, 10_000.0)
        self.assertAlmostEqual(result, 2.0)


class TestAnnualizedFeeYield(unittest.TestCase):
    def test_basic_formula(self):
        # vol=1_000_000, fee=30bps, tvl=10_000_000
        expected = (1_000_000.0 * 30 / 10_000.0) / 10_000_000.0 * 365.0 * 100.0
        result = _annualized_fee_yield_pct(1_000_000.0, 30, 10_000_000.0)
        self.assertAlmostEqual(result, expected, places=8)

    def test_zero_tvl_returns_zero(self):
        self.assertAlmostEqual(_annualized_fee_yield_pct(1_000_000.0, 30, 0.0), 0.0)

    def test_zero_volume_returns_zero(self):
        self.assertAlmostEqual(_annualized_fee_yield_pct(0.0, 30, 10_000_000.0), 0.0)

    def test_zero_fee_returns_zero(self):
        self.assertAlmostEqual(_annualized_fee_yield_pct(1_000_000.0, 0, 10_000_000.0), 0.0)

    def test_higher_fee_tier_higher_yield(self):
        yield_5 = _annualized_fee_yield_pct(1_000_000.0, 5, 10_000_000.0)
        yield_100 = _annualized_fee_yield_pct(1_000_000.0, 100, 10_000_000.0)
        self.assertGreater(yield_100, yield_5)

    def test_yield_scales_with_volume(self):
        y1 = _annualized_fee_yield_pct(1_000_000.0, 30, 10_000_000.0)
        y2 = _annualized_fee_yield_pct(2_000_000.0, 30, 10_000_000.0)
        self.assertAlmostEqual(y2, y1 * 2, places=6)


class TestEffectiveYield(unittest.TestCase):
    def test_100pct_in_range(self):
        result = _effective_yield_pct(10.0, 100.0)
        self.assertAlmostEqual(result, 10.0)

    def test_50pct_in_range(self):
        result = _effective_yield_pct(10.0, 50.0)
        self.assertAlmostEqual(result, 5.0)

    def test_zero_in_range(self):
        result = _effective_yield_pct(10.0, 0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_zero_annualized_yield(self):
        result = _effective_yield_pct(0.0, 80.0)
        self.assertAlmostEqual(result, 0.0)

    def test_formula(self):
        ann = 15.5
        rng = 72.0
        expected = ann * rng / 100.0
        result = _effective_yield_pct(ann, rng)
        self.assertAlmostEqual(result, expected, places=8)


class TestCapitalEfficiency(unittest.TestCase):
    def test_high_conc_high_range(self):
        self.assertEqual(_capital_efficiency(0.7, 80.0), "HIGH")

    def test_high_conc_border(self):
        self.assertEqual(_capital_efficiency(0.7, 80.0), "HIGH")

    def test_below_high_conc(self):
        # conc=0.69, range=80 → MEDIUM (or)
        self.assertEqual(_capital_efficiency(0.69, 80.0), "MEDIUM")

    def test_high_conc_below_range(self):
        # conc=0.8, range=79 → MEDIUM (second condition: conc>=0.4)
        self.assertEqual(_capital_efficiency(0.8, 79.0), "MEDIUM")

    def test_medium_by_concentration(self):
        self.assertEqual(_capital_efficiency(0.4, 50.0), "MEDIUM")

    def test_medium_by_in_range(self):
        self.assertEqual(_capital_efficiency(0.3, 60.0), "MEDIUM")

    def test_low_both_below(self):
        self.assertEqual(_capital_efficiency(0.3, 50.0), "LOW")

    def test_low_zero_both(self):
        self.assertEqual(_capital_efficiency(0.0, 0.0), "LOW")


class TestRangeRisk(unittest.TestCase):
    def test_low_risk_above_85(self):
        self.assertEqual(_range_risk(85.0), "LOW")

    def test_low_risk_100(self):
        self.assertEqual(_range_risk(100.0), "LOW")

    def test_medium_risk_60_to_84(self):
        self.assertEqual(_range_risk(60.0), "MEDIUM")
        self.assertEqual(_range_risk(84.9), "MEDIUM")

    def test_high_risk_below_60(self):
        self.assertEqual(_range_risk(59.9), "HIGH")
        self.assertEqual(_range_risk(0.0), "HIGH")

    def test_border_85(self):
        self.assertEqual(_range_risk(85.0), "LOW")

    def test_border_60(self):
        self.assertEqual(_range_risk(60.0), "MEDIUM")


class TestLpRecommendation(unittest.TestCase):
    def test_preferred_high_yield_low_risk(self):
        self.assertEqual(_lp_recommendation(10.0, "LOW", 90.0, False), "PREFERRED")

    def test_preferred_high_yield_medium_risk(self):
        self.assertEqual(_lp_recommendation(15.0, "MEDIUM", 70.0, False), "PREFERRED")

    def test_skip_high_range_risk_below_40(self):
        self.assertEqual(_lp_recommendation(5.0, "HIGH", 35.0, False), "SKIP")

    def test_viable_medium_yield(self):
        self.assertEqual(_lp_recommendation(5.0, "LOW", 90.0, False), "VIABLE")

    def test_viable_high_risk_above_40(self):
        # range_risk HIGH but in_range_pct >= 40 → VIABLE
        self.assertEqual(_lp_recommendation(5.0, "HIGH", 45.0, False), "VIABLE")

    def test_skip_when_filtered(self):
        self.assertEqual(_lp_recommendation(20.0, "LOW", 95.0, True), "SKIP")

    def test_preferred_exact_10_yield(self):
        self.assertEqual(_lp_recommendation(10.0, "MEDIUM", 75.0, False), "PREFERRED")

    def test_viable_below_10_yield_low_risk(self):
        self.assertEqual(_lp_recommendation(9.99, "LOW", 90.0, False), "VIABLE")


class TestIsFiltered(unittest.TestCase):
    def test_not_filtered_both_above(self):
        self.assertFalse(_is_filtered(200_000.0, 20_000.0, 100_000.0, 10_000.0))

    def test_filtered_low_tvl(self):
        self.assertTrue(_is_filtered(50_000.0, 20_000.0, 100_000.0, 10_000.0))

    def test_filtered_low_volume(self):
        self.assertTrue(_is_filtered(200_000.0, 5_000.0, 100_000.0, 10_000.0))

    def test_filtered_both_low(self):
        self.assertTrue(_is_filtered(50_000.0, 5_000.0, 100_000.0, 10_000.0))

    def test_exact_threshold_not_filtered(self):
        self.assertFalse(_is_filtered(100_000.0, 10_000.0, 100_000.0, 10_000.0))


# ===========================================================================
# analyze() integration tests
# ===========================================================================

class TestAnalyzeEmpty(unittest.TestCase):
    def test_empty_returns_structure(self):
        result = analyze([])
        self.assertEqual(result["pools"], [])
        self.assertIsNone(result["best_pool"])
        self.assertEqual(result["pair_summary"], {})
        self.assertAlmostEqual(result["total_tvl_analyzed_usd"], 0.0)
        self.assertIsInstance(result["timestamp"], float)


class TestAnalyzeSinglePool(unittest.TestCase):
    def setUp(self):
        self.p = _pool(fee_tier_bps=30, tvl_usd=1_000_000.0,
                       volume_24h_usd=500_000.0, in_range_pct=90.0,
                       liquidity_concentration=0.8)
        self.result = analyze([self.p])

    def test_one_pool_returned(self):
        self.assertEqual(len(self.result["pools"]), 1)

    def test_fee_tier_label(self):
        self.assertEqual(self.result["pools"][0]["fee_tier_label"], "0.30%")

    def test_not_filtered(self):
        self.assertFalse(self.result["pools"][0]["filtered"])

    def test_total_tvl(self):
        self.assertAlmostEqual(self.result["total_tvl_analyzed_usd"], 1_000_000.0)

    def test_capital_efficiency_high(self):
        self.assertEqual(self.result["pools"][0]["capital_efficiency"], "HIGH")

    def test_range_risk_low(self):
        self.assertEqual(self.result["pools"][0]["range_risk"], "LOW")

    def test_output_keys(self):
        expected = {
            "protocol", "pair", "fee_tier_bps", "fee_tier_label",
            "volume_to_tvl_ratio", "annualized_fee_yield_pct", "effective_yield_pct",
            "capital_efficiency", "range_risk", "lp_recommendation", "filtered",
        }
        for key in expected:
            self.assertIn(key, self.result["pools"][0])


class TestAnalyzeYieldMath(unittest.TestCase):
    def test_annualized_yield_formula(self):
        p = _pool(fee_tier_bps=30, tvl_usd=10_000_000.0,
                  volume_24h_usd=1_000_000.0, in_range_pct=100.0)
        result = analyze([p])
        r = result["pools"][0]
        expected_ann = (1_000_000.0 * 30 / 10_000.0) / 10_000_000.0 * 365.0 * 100.0
        self.assertAlmostEqual(r["annualized_fee_yield_pct"], expected_ann, places=6)

    def test_effective_yield_scales_with_in_range(self):
        p90 = _pool(in_range_pct=90.0)
        p45 = _pool(in_range_pct=45.0)
        r90 = analyze([p90])["pools"][0]
        r45 = analyze([p45])["pools"][0]
        self.assertAlmostEqual(r90["effective_yield_pct"],
                                r45["effective_yield_pct"] * 2, places=6)

    def test_zero_volume_zero_yield(self):
        p = _pool(volume_24h_usd=0.0)
        result = analyze([p])
        r = result["pools"][0]
        self.assertAlmostEqual(r["annualized_fee_yield_pct"], 0.0)
        self.assertAlmostEqual(r["effective_yield_pct"], 0.0)

    def test_zero_tvl_zero_yield(self):
        p = _pool(tvl_usd=0.0, volume_24h_usd=500_000.0)
        result = analyze([p], config={"min_tvl_usd": 0.0, "min_volume_usd": 0.0})
        r = result["pools"][0]
        self.assertAlmostEqual(r["annualized_fee_yield_pct"], 0.0)


class TestAnalyzeFiltering(unittest.TestCase):
    def test_low_tvl_filtered(self):
        p = _pool(tvl_usd=50_000.0)
        result = analyze([p])
        self.assertTrue(result["pools"][0]["filtered"])

    def test_low_volume_filtered(self):
        p = _pool(volume_24h_usd=5_000.0)
        result = analyze([p])
        self.assertTrue(result["pools"][0]["filtered"])

    def test_filtered_not_in_total_tvl(self):
        p = _pool(tvl_usd=50_000.0)
        result = analyze([p])
        self.assertAlmostEqual(result["total_tvl_analyzed_usd"], 0.0)

    def test_filtered_not_in_pair_summary(self):
        p = _pool(tvl_usd=50_000.0, pair="USDC/ETH")
        result = analyze([p])
        self.assertNotIn("USDC/ETH", result["pair_summary"])

    def test_custom_min_tvl_config(self):
        p = _pool(tvl_usd=50_000.0)
        result = analyze([p], config={"min_tvl_usd": 10_000.0, "min_volume_usd": 1_000.0})
        self.assertFalse(result["pools"][0]["filtered"])

    def test_filtered_has_skip_recommendation(self):
        p = _pool(tvl_usd=50_000.0)
        result = analyze([p])
        self.assertEqual(result["pools"][0]["lp_recommendation"], "SKIP")

    def test_not_in_best_pool_when_filtered(self):
        p_filtered = _pool(pair="A/B", tvl_usd=50_000.0, volume_24h_usd=999_000.0)
        p_ok = _pool(pair="C/D", volume_24h_usd=100_000.0)
        result = analyze([p_filtered, p_ok])
        if result["best_pool"]:
            self.assertNotEqual(result["best_pool"]["pair"], "A/B")


class TestAnalyzeBestPool(unittest.TestCase):
    def test_best_pool_highest_effective_yield(self):
        p1 = _pool(pair="A/B", fee_tier_bps=100, volume_24h_usd=5_000_000.0,
                   in_range_pct=90.0)
        p2 = _pool(pair="C/D", fee_tier_bps=5, volume_24h_usd=100_000.0,
                   in_range_pct=90.0)
        result = analyze([p1, p2])
        self.assertIsNotNone(result["best_pool"])
        # p1 has far higher fee revenue → higher effective yield
        self.assertEqual(result["best_pool"]["pair"], "A/B")

    def test_best_pool_none_when_all_filtered(self):
        p = _pool(tvl_usd=50_000.0)
        result = analyze([p])
        self.assertIsNone(result["best_pool"])

    def test_best_pool_none_when_all_skip_range(self):
        # in_range_pct < 40 → SKIP even if not filtered
        p = _pool(in_range_pct=30.0)
        result = analyze([p])
        self.assertIsNone(result["best_pool"])

    def test_best_pool_is_dict(self):
        p = _pool(in_range_pct=90.0, volume_24h_usd=500_000.0)
        result = analyze([p])
        if result["best_pool"] is not None:
            self.assertIsInstance(result["best_pool"], dict)


class TestAnalyzePairSummary(unittest.TestCase):
    def test_pair_summary_groups_by_pair(self):
        p1 = _pool(pair="USDC/ETH", fee_tier_bps=5, volume_24h_usd=1_000_000.0)
        p2 = _pool(pair="USDC/ETH", fee_tier_bps=30, volume_24h_usd=500_000.0)
        result = analyze([p1, p2])
        self.assertIn("USDC/ETH", result["pair_summary"])
        self.assertEqual(result["pair_summary"]["USDC/ETH"]["pool_count"], 2)

    def test_pair_summary_best_fee_tier(self):
        # p1 with fee_tier_bps=100 should dominate if volume is same
        p1 = _pool(pair="X/Y", fee_tier_bps=5, volume_24h_usd=500_000.0,
                   in_range_pct=90.0)
        p2 = _pool(pair="X/Y", fee_tier_bps=100, volume_24h_usd=500_000.0,
                   in_range_pct=90.0)
        result = analyze([p1, p2])
        # fee_tier_bps=100 gives higher annualized yield
        self.assertEqual(result["pair_summary"]["X/Y"]["best_fee_tier_bps"], 100)

    def test_pair_summary_best_effective_yield(self):
        p1 = _pool(pair="A/B", fee_tier_bps=30, volume_24h_usd=200_000.0,
                   in_range_pct=90.0)
        p2 = _pool(pair="A/B", fee_tier_bps=30, volume_24h_usd=100_000.0,
                   in_range_pct=90.0)
        result = analyze([p1, p2])
        best_eff = result["pair_summary"]["A/B"]["best_effective_yield"]
        expected = analyze([p1])["pools"][0]["effective_yield_pct"]
        self.assertAlmostEqual(best_eff, expected, places=6)

    def test_multiple_pairs(self):
        p1 = _pool(pair="A/B")
        p2 = _pool(pair="C/D")
        result = analyze([p1, p2])
        self.assertIn("A/B", result["pair_summary"])
        self.assertIn("C/D", result["pair_summary"])

    def test_filtered_pool_excluded_from_pair_summary(self):
        p = _pool(pair="X/Y", tvl_usd=50_000.0)
        result = analyze([p])
        self.assertNotIn("X/Y", result["pair_summary"])


class TestAnalyzeTotalTvl(unittest.TestCase):
    def test_total_tvl_sums_non_filtered(self):
        p1 = _pool(tvl_usd=1_000_000.0)
        p2 = _pool(tvl_usd=2_000_000.0)
        result = analyze([p1, p2])
        self.assertAlmostEqual(result["total_tvl_analyzed_usd"], 3_000_000.0)

    def test_total_tvl_excludes_filtered(self):
        p1 = _pool(tvl_usd=1_000_000.0)
        p2 = _pool(tvl_usd=50_000.0)  # filtered
        result = analyze([p1, p2])
        self.assertAlmostEqual(result["total_tvl_analyzed_usd"], 1_000_000.0)

    def test_total_tvl_zero_when_all_filtered(self):
        p = _pool(tvl_usd=50_000.0)
        result = analyze([p])
        self.assertAlmostEqual(result["total_tvl_analyzed_usd"], 0.0)


class TestAnalyzeTimestamp(unittest.TestCase):
    def test_timestamp_is_float(self):
        result = analyze([])
        self.assertIsInstance(result["timestamp"], float)

    def test_timestamp_recent(self):
        before = time.time() - 1
        result = analyze([])
        after = time.time() + 1
        self.assertGreater(result["timestamp"], before)
        self.assertLess(result["timestamp"], after)


class TestAnalyzeOutputStructure(unittest.TestCase):
    def test_top_level_keys(self):
        result = analyze([])
        for key in ("pools", "best_pool", "pair_summary",
                    "total_tvl_analyzed_usd", "timestamp"):
            self.assertIn(key, result)

    def test_ordering_preserved(self):
        pools = [_pool(pair=f"P{i}/USD") for i in range(5)]
        result = analyze(pools)
        for i, r in enumerate(result["pools"]):
            self.assertEqual(r["pair"], f"P{i}/USD")


class TestAnalyzeRecommendationVariants(unittest.TestCase):
    def test_preferred_high_yield_low_risk_pool(self):
        # Need high effective yield ≥ 10 and range_risk LOW/MEDIUM
        p = _pool(
            fee_tier_bps=100,
            tvl_usd=1_000_000.0,
            volume_24h_usd=5_000_000.0,
            in_range_pct=90.0,
            liquidity_concentration=0.8,
        )
        result = analyze([p])
        r = result["pools"][0]
        # Should be PREFERRED if effective_yield >= 10
        if r["effective_yield_pct"] >= 10.0:
            self.assertEqual(r["lp_recommendation"], "PREFERRED")

    def test_skip_out_of_range_pool(self):
        p = _pool(in_range_pct=30.0)
        result = analyze([p])
        r = result["pools"][0]
        self.assertEqual(r["lp_recommendation"], "SKIP")
        self.assertEqual(r["range_risk"], "HIGH")

    def test_viable_moderate_pool(self):
        p = _pool(in_range_pct=75.0, volume_24h_usd=100_000.0, fee_tier_bps=30)
        result = analyze([p])
        r = result["pools"][0]
        # effective_yield < 10 and range_risk MEDIUM → VIABLE
        if r["effective_yield_pct"] < 10.0 and r["range_risk"] == "MEDIUM":
            self.assertEqual(r["lp_recommendation"], "VIABLE")


class TestLogResult(unittest.TestCase):
    def test_log_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = analyze([])
            _log_result(result, tmpdir)
            log_path = os.path.join(tmpdir, "fee_tier_log.json")
            self.assertTrue(os.path.exists(log_path))

    def test_log_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = analyze([])
            _log_result(result, tmpdir)
            log_path = os.path.join(tmpdir, "fee_tier_log.json")
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, list)

    def test_log_appends_multiple(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for _ in range(5):
                result = analyze([])
                _log_result(result, tmpdir)
            log_path = os.path.join(tmpdir, "fee_tier_log.json")
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 5)

    def test_log_ring_buffer_100(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for _ in range(110):
                result = analyze([])
                _log_result(result, tmpdir)
            log_path = os.path.join(tmpdir, "fee_tier_log.json")
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertLessEqual(len(data), 100)

    def test_log_exactly_100_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for _ in range(100):
                result = analyze([])
                _log_result(result, tmpdir)
            log_path = os.path.join(tmpdir, "fee_tier_log.json")
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 100)

    def test_log_recovers_from_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "fee_tier_log.json")
            with open(log_path, "w") as fh:
                fh.write("not valid json!!!")
            result = analyze([])
            _log_result(result, tmpdir)
            with open(log_path) as fh:
                data = json.load(fh)
            self.assertEqual(len(data), 1)


class TestAnalyzeVolumeToTvlField(unittest.TestCase):
    def test_volume_to_tvl_correct(self):
        p = _pool(tvl_usd=2_000_000.0, volume_24h_usd=500_000.0)
        result = analyze([p])
        r = result["pools"][0]
        self.assertAlmostEqual(r["volume_to_tvl_ratio"], 0.25, places=8)

    def test_zero_tvl_pool_ratio_zero(self):
        p = _pool(tvl_usd=0.0, volume_24h_usd=100_000.0)
        result = analyze([p], config={"min_tvl_usd": 0.0, "min_volume_usd": 0.0})
        r = result["pools"][0]
        self.assertAlmostEqual(r["volume_to_tvl_ratio"], 0.0)


if __name__ == "__main__":
    unittest.main()
