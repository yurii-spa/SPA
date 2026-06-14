"""
Tests for MP-882 YieldBearingStablecoinComparator
Run: python3 -m unittest spa_core.tests.test_yield_bearing_stablecoin_comparator -v
"""
import json
import os
import tempfile
import unittest

from spa_core.analytics.yield_bearing_stablecoin_comparator import (
    analyze,
    _clamp,
    _peg_stability_score,
    _liquidity_score,
    _safety_score,
    _redemption_score,
    _apy_norm,
    _composite_score,
    _risk_label,
    _flags,
    _recommendation,
    _append_log,
    _RING_BUFFER_MAX,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_stablecoin(**kwargs):
    base = {
        "symbol": "sDAI",
        "underlying": "DAI",
        "current_apy_pct": 5.0,
        "tvl_usd": 500_000_000.0,
        "peg_deviation_30d_max_pct": 0.1,
        "yield_source": "LENDING",
        "redemption_mechanism": "INSTANT",
        "collateral_ratio_pct": 150.0,
        "days_since_peg_incident": 9999,
        "liquidity_depth_usd": 50_000_000.0,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Unit tests – _clamp
# ---------------------------------------------------------------------------

class TestClamp(unittest.TestCase):
    def test_below_zero(self):
        self.assertEqual(_clamp(-5), 0)

    def test_above_100(self):
        self.assertEqual(_clamp(105), 100)

    def test_zero(self):
        self.assertEqual(_clamp(0), 0)

    def test_100(self):
        self.assertEqual(_clamp(100), 100)

    def test_midrange(self):
        self.assertEqual(_clamp(63.9), 63)

    def test_returns_int(self):
        self.assertIsInstance(_clamp(50.5), int)


# ---------------------------------------------------------------------------
# Unit tests – _peg_stability_score
# ---------------------------------------------------------------------------

class TestPegStabilityScore(unittest.TestCase):
    def test_zero_deviation(self):
        # 100 - min(100, int(0*200)) = 100
        self.assertEqual(_peg_stability_score(0.0), 100)

    def test_small_deviation(self):
        # 0.1 → 100 - int(20) = 80
        self.assertEqual(_peg_stability_score(0.1), 80)

    def test_half_pct(self):
        # 0.5 → 100 - int(100) = 0
        self.assertEqual(_peg_stability_score(0.5), 0)

    def test_large_deviation_capped(self):
        # 2.0 → 100 - min(100, 400) = 0
        self.assertEqual(_peg_stability_score(2.0), 0)

    def test_quarter_pct(self):
        # 0.25 → 100 - int(50) = 50
        self.assertEqual(_peg_stability_score(0.25), 50)

    def test_tiny_deviation(self):
        # 0.05 → 100 - int(10) = 90
        self.assertEqual(_peg_stability_score(0.05), 90)


# ---------------------------------------------------------------------------
# Unit tests – _liquidity_score
# ---------------------------------------------------------------------------

class TestLiquidityScore(unittest.TestCase):
    def test_zero_tvl(self):
        self.assertEqual(_liquidity_score(1_000_000, 0), 0)

    def test_10_pct_depth(self):
        # 50M / 500M * 100 = 10
        self.assertEqual(_liquidity_score(50_000_000, 500_000_000), 10)

    def test_full_depth(self):
        # 500M / 500M * 100 = 100
        self.assertEqual(_liquidity_score(500_000_000, 500_000_000), 100)

    def test_over_100_capped(self):
        # depth > tvl → capped at 100
        self.assertEqual(_liquidity_score(1_000_000, 500_000), 100)

    def test_zero_depth(self):
        self.assertEqual(_liquidity_score(0, 500_000_000), 0)


# ---------------------------------------------------------------------------
# Unit tests – _safety_score
# ---------------------------------------------------------------------------

class TestSafetyScore(unittest.TestCase):
    def test_150_pct_collateral(self):
        # (150-100)*2+50 = 150 → capped 100
        self.assertEqual(_safety_score(150.0), 100)

    def test_110_pct_collateral(self):
        # (110-100)*2+50 = 70
        self.assertEqual(_safety_score(110.0), 70)

    def test_100_pct_collateral(self):
        # (100-100)*2+50 = 50
        self.assertEqual(_safety_score(100.0), 50)

    def test_90_pct_collateral(self):
        # (90-100)*2+50 = 30
        self.assertEqual(_safety_score(90.0), 30)

    def test_75_pct_collateral(self):
        # (75-100)*2+50 = 0 → capped 0
        self.assertEqual(_safety_score(75.0), 0)

    def test_50_pct_collateral(self):
        # (50-100)*2+50 = -50 → capped 0
        self.assertEqual(_safety_score(50.0), 0)

    def test_200_pct_collateral(self):
        # (200-100)*2+50 = 250 → capped 100
        self.assertEqual(_safety_score(200.0), 100)


# ---------------------------------------------------------------------------
# Unit tests – _redemption_score
# ---------------------------------------------------------------------------

class TestRedemptionScore(unittest.TestCase):
    def test_instant(self):
        self.assertEqual(_redemption_score("INSTANT"), 100)

    def test_queued(self):
        self.assertEqual(_redemption_score("QUEUED"), 70)

    def test_timelocked(self):
        self.assertEqual(_redemption_score("TIMELOCKED"), 40)

    def test_amm_only(self):
        self.assertEqual(_redemption_score("AMM_ONLY"), 20)

    def test_case_insensitive(self):
        self.assertEqual(_redemption_score("instant"), 100)
        self.assertEqual(_redemption_score("Queued"), 70)

    def test_unknown_returns_zero(self):
        self.assertEqual(_redemption_score("UNKNOWN"), 0)


# ---------------------------------------------------------------------------
# Unit tests – _apy_norm
# ---------------------------------------------------------------------------

class TestApyNorm(unittest.TestCase):
    def test_5_pct(self):
        self.assertEqual(_apy_norm(5.0), 50)

    def test_10_pct(self):
        self.assertEqual(_apy_norm(10.0), 100)

    def test_15_pct_capped(self):
        self.assertEqual(_apy_norm(15.0), 100)

    def test_zero(self):
        self.assertEqual(_apy_norm(0.0), 0)

    def test_2_5_pct(self):
        self.assertEqual(_apy_norm(2.5), 25)


# ---------------------------------------------------------------------------
# Unit tests – _composite_score
# ---------------------------------------------------------------------------

class TestCompositeScore(unittest.TestCase):
    def test_all_100(self):
        # int(100*0.25 + 100*0.30 + 100*0.25 + 100*0.10 + 100*0.10) = int(100.0) = 100
        self.assertEqual(_composite_score(100, 100, 100, 100, 100), 100)

    def test_all_zero(self):
        self.assertEqual(_composite_score(0, 0, 0, 0, 0), 0)

    def test_formula(self):
        # apy=50, peg=80, safety=70, redemption=100, liquidity=10
        # int(50*0.25 + 80*0.30 + 70*0.25 + 100*0.10 + 10*0.10)
        # = int(12.5 + 24 + 17.5 + 10 + 1) = int(65.0) = 65
        self.assertEqual(_composite_score(50, 80, 70, 100, 10), 65)

    def test_clamped_not_negative(self):
        self.assertGreaterEqual(_composite_score(0, 0, 0, 0, 0), 0)

    def test_clamped_not_above_100(self):
        self.assertLessEqual(_composite_score(100, 100, 100, 100, 100), 100)


# ---------------------------------------------------------------------------
# Unit tests – _risk_label
# ---------------------------------------------------------------------------

class TestRiskLabel(unittest.TestCase):
    def test_very_low_risk(self):
        self.assertEqual(_risk_label(80), "VERY_LOW_RISK")

    def test_very_low_risk_100(self):
        self.assertEqual(_risk_label(100), "VERY_LOW_RISK")

    def test_low_risk(self):
        self.assertEqual(_risk_label(65), "LOW_RISK")

    def test_low_risk_boundary(self):
        self.assertEqual(_risk_label(79), "LOW_RISK")

    def test_moderate_risk(self):
        self.assertEqual(_risk_label(50), "MODERATE_RISK")

    def test_moderate_risk_boundary(self):
        self.assertEqual(_risk_label(64), "MODERATE_RISK")

    def test_high_risk(self):
        self.assertEqual(_risk_label(35), "HIGH_RISK")

    def test_high_risk_boundary(self):
        self.assertEqual(_risk_label(49), "HIGH_RISK")

    def test_very_high_risk(self):
        self.assertEqual(_risk_label(0), "VERY_HIGH_RISK")

    def test_very_high_risk_boundary(self):
        self.assertEqual(_risk_label(34), "VERY_HIGH_RISK")


# ---------------------------------------------------------------------------
# Unit tests – _flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):
    def _no_flags(self):
        return _flags(
            tvl_usd=500_000_000,
            peg_deviation_30d_max_pct=0.1,
            collateral_ratio_pct=150.0,
            days_since_peg_incident=9999,
            min_tvl_usd=50_000_000,
            max_peg_deviation_pct=0.5,
        )

    def test_no_flags(self):
        self.assertEqual(self._no_flags(), [])

    def test_low_tvl(self):
        result = _flags(10_000_000, 0.1, 150.0, 9999, 50_000_000, 0.5)
        self.assertIn("LOW_TVL", result)

    def test_peg_instability(self):
        result = _flags(500_000_000, 0.8, 150.0, 9999, 50_000_000, 0.5)
        self.assertIn("PEG_INSTABILITY", result)

    def test_peg_at_boundary_no_flag(self):
        # max_peg=0.5, deviation=0.5 → NOT flagged (> not >=)
        result = _flags(500_000_000, 0.5, 150.0, 9999, 50_000_000, 0.5)
        self.assertNotIn("PEG_INSTABILITY", result)

    def test_undercollateralized(self):
        result = _flags(500_000_000, 0.1, 99.9, 9999, 50_000_000, 0.5)
        self.assertIn("UNDERCOLLATERALIZED", result)

    def test_collateral_100_not_flagged(self):
        result = _flags(500_000_000, 0.1, 100.0, 9999, 50_000_000, 0.5)
        self.assertNotIn("UNDERCOLLATERALIZED", result)

    def test_recent_incident(self):
        result = _flags(500_000_000, 0.1, 150.0, 30, 50_000_000, 0.5)
        self.assertIn("RECENT_INCIDENT", result)

    def test_recent_incident_boundary_not_flagged(self):
        # 90 is not < 90
        result = _flags(500_000_000, 0.1, 150.0, 90, 50_000_000, 0.5)
        self.assertNotIn("RECENT_INCIDENT", result)

    def test_all_flags(self):
        result = _flags(10_000_000, 1.0, 80.0, 30, 50_000_000, 0.5)
        self.assertIn("LOW_TVL", result)
        self.assertIn("PEG_INSTABILITY", result)
        self.assertIn("UNDERCOLLATERALIZED", result)
        self.assertIn("RECENT_INCIDENT", result)

    def test_9999_days_no_incident(self):
        result = _flags(500_000_000, 0.1, 150.0, 9999, 50_000_000, 0.5)
        self.assertNotIn("RECENT_INCIDENT", result)


# ---------------------------------------------------------------------------
# Unit tests – _recommendation
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):
    def test_very_low_risk_high_apy(self):
        rec = _recommendation("VERY_LOW_RISK", 6.0, [])
        self.assertIn("Excellent choice", rec)
        self.assertIn("6.0%", rec)

    def test_very_low_risk_low_apy(self):
        rec = _recommendation("VERY_LOW_RISK", 3.0, [])
        self.assertIn("Safe but modest yield", rec)

    def test_very_low_risk_exactly_5(self):
        rec = _recommendation("VERY_LOW_RISK", 5.0, [])
        self.assertIn("Excellent choice", rec)

    def test_low_risk(self):
        rec = _recommendation("LOW_RISK", 7.0, [])
        self.assertIn("Good risk-adjusted yield", rec)
        self.assertIn("7.0%", rec)

    def test_moderate_risk_no_flags(self):
        rec = _recommendation("MODERATE_RISK", 5.0, [])
        self.assertIn("Acceptable yield-risk tradeoff", rec)
        self.assertIn("none", rec)

    def test_moderate_risk_with_flags(self):
        rec = _recommendation("MODERATE_RISK", 5.0, ["LOW_TVL"])
        self.assertIn("LOW_TVL", rec)

    def test_high_risk(self):
        rec = _recommendation("HIGH_RISK", 12.0, ["PEG_INSTABILITY"])
        self.assertIn("High risk", rec)
        self.assertIn("PEG_INSTABILITY", rec)

    def test_very_high_risk_no_flags(self):
        rec = _recommendation("VERY_HIGH_RISK", 20.0, [])
        self.assertIn("low composite score", rec)

    def test_very_high_risk_with_flags(self):
        rec = _recommendation("VERY_HIGH_RISK", 20.0, ["UNDERCOLLATERALIZED"])
        self.assertIn("UNDERCOLLATERALIZED", rec)


# ---------------------------------------------------------------------------
# Integration tests – analyze()
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):
    def test_empty_returns_defaults(self):
        result = analyze([])
        self.assertEqual(result["stablecoins"], [])
        self.assertIsNone(result["best_yield"])
        self.assertIsNone(result["safest"])
        self.assertAlmostEqual(result["average_apy_pct"], 0.0)
        self.assertIn("timestamp", result)

    def test_timestamp_float(self):
        result = analyze([])
        self.assertIsInstance(result["timestamp"], float)


class TestAnalyzeSingle(unittest.TestCase):
    def setUp(self):
        self.coin = _make_stablecoin(
            symbol="sDAI",
            current_apy_pct=5.0,
            tvl_usd=500_000_000,
            peg_deviation_30d_max_pct=0.1,
            redemption_mechanism="INSTANT",
            collateral_ratio_pct=150.0,
            days_since_peg_incident=9999,
            liquidity_depth_usd=50_000_000,
        )
        self.result = analyze([self.coin])

    def test_one_result(self):
        self.assertEqual(len(self.result["stablecoins"]), 1)

    def test_symbol_preserved(self):
        self.assertEqual(self.result["stablecoins"][0]["symbol"], "sDAI")

    def test_best_yield_is_symbol(self):
        self.assertEqual(self.result["best_yield"], "sDAI")

    def test_safest_is_symbol(self):
        self.assertEqual(self.result["safest"], "sDAI")

    def test_average_apy_equals_single(self):
        self.assertAlmostEqual(self.result["average_apy_pct"], 5.0)

    def test_peg_stability_score(self):
        # 0.1 → 100 - int(0.1*200) = 100 - 20 = 80
        self.assertEqual(self.result["stablecoins"][0]["peg_stability_score"], 80)

    def test_safety_score(self):
        # 150% → capped 100
        self.assertEqual(self.result["stablecoins"][0]["safety_score"], 100)

    def test_redemption_score(self):
        self.assertEqual(self.result["stablecoins"][0]["redemption_score"], 100)

    def test_liquidity_score(self):
        # 50M / 500M * 100 = 10
        self.assertEqual(self.result["stablecoins"][0]["liquidity_score"], 10)

    def test_composite_score_range(self):
        score = self.result["stablecoins"][0]["composite_score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_risk_label_valid(self):
        self.assertIn(
            self.result["stablecoins"][0]["risk_label"],
            ["VERY_LOW_RISK", "LOW_RISK", "MODERATE_RISK", "HIGH_RISK", "VERY_HIGH_RISK"],
        )

    def test_flags_is_list(self):
        self.assertIsInstance(self.result["stablecoins"][0]["flags"], list)

    def test_recommendation_is_str(self):
        self.assertIsInstance(self.result["stablecoins"][0]["recommendation"], str)

    def test_no_flags_for_good_stablecoin(self):
        self.assertEqual(self.result["stablecoins"][0]["flags"], [])


class TestAnalyzeMultiple(unittest.TestCase):
    def setUp(self):
        self.coins = [
            _make_stablecoin(symbol="sDAI", current_apy_pct=5.0, collateral_ratio_pct=150),
            _make_stablecoin(symbol="eUSD", current_apy_pct=12.0, collateral_ratio_pct=105),
            _make_stablecoin(symbol="sUSDS", current_apy_pct=4.5, collateral_ratio_pct=200),
        ]
        self.result = analyze(self.coins)

    def test_three_results(self):
        self.assertEqual(len(self.result["stablecoins"]), 3)

    def test_best_yield_is_eUSD(self):
        self.assertEqual(self.result["best_yield"], "eUSD")

    def test_safest_is_highest_composite(self):
        # Find manually
        scores = {s["symbol"]: s["composite_score"] for s in self.result["stablecoins"]}
        expected_safest = max(scores, key=scores.get)
        self.assertEqual(self.result["safest"], expected_safest)

    def test_average_apy(self):
        expected = (5.0 + 12.0 + 4.5) / 3
        self.assertAlmostEqual(self.result["average_apy_pct"], expected)


class TestAnalyzeEdgeCases(unittest.TestCase):
    def test_zero_tvl_liquidity_score_zero(self):
        s = _make_stablecoin(tvl_usd=0)
        result = analyze([s])
        self.assertEqual(result["stablecoins"][0]["liquidity_score"], 0)

    def test_low_tvl_flag(self):
        s = _make_stablecoin(tvl_usd=10_000_000)
        result = analyze([s])
        self.assertIn("LOW_TVL", result["stablecoins"][0]["flags"])

    def test_custom_min_tvl_no_flag(self):
        s = _make_stablecoin(tvl_usd=10_000_000)
        result = analyze([s], config={"min_tvl_usd": 5_000_000})
        self.assertNotIn("LOW_TVL", result["stablecoins"][0]["flags"])

    def test_peg_instability_flag(self):
        s = _make_stablecoin(peg_deviation_30d_max_pct=1.0)
        result = analyze([s])
        self.assertIn("PEG_INSTABILITY", result["stablecoins"][0]["flags"])

    def test_custom_max_peg_deviation(self):
        s = _make_stablecoin(peg_deviation_30d_max_pct=0.3)
        result = analyze([s], config={"max_peg_deviation_pct": 0.2})
        self.assertIn("PEG_INSTABILITY", result["stablecoins"][0]["flags"])

    def test_undercollateralized_flag(self):
        s = _make_stablecoin(collateral_ratio_pct=95.0)
        result = analyze([s])
        self.assertIn("UNDERCOLLATERALIZED", result["stablecoins"][0]["flags"])

    def test_recent_incident_flag(self):
        s = _make_stablecoin(days_since_peg_incident=30)
        result = analyze([s])
        self.assertIn("RECENT_INCIDENT", result["stablecoins"][0]["flags"])

    def test_amm_only_redemption(self):
        s = _make_stablecoin(redemption_mechanism="AMM_ONLY")
        result = analyze([s])
        self.assertEqual(result["stablecoins"][0]["redemption_score"], 20)

    def test_timelocked_redemption(self):
        s = _make_stablecoin(redemption_mechanism="TIMELOCKED")
        result = analyze([s])
        self.assertEqual(result["stablecoins"][0]["redemption_score"], 40)

    def test_high_apy_norm_capped(self):
        s = _make_stablecoin(current_apy_pct=20.0)
        result = analyze([s])
        # apy_norm = min(100, int(20*10)) = 100
        # score should reflect max apy contribution
        self.assertGreaterEqual(result["stablecoins"][0]["composite_score"], 0)

    def test_result_has_all_keys(self):
        result = analyze([_make_stablecoin()])
        for key in ["stablecoins", "best_yield", "safest", "average_apy_pct", "timestamp"]:
            self.assertIn(key, result)

    def test_stablecoin_has_all_keys(self):
        result = analyze([_make_stablecoin()])
        s = result["stablecoins"][0]
        for key in [
            "symbol", "yield_source", "current_apy_pct",
            "peg_stability_score", "liquidity_score", "safety_score",
            "redemption_score", "composite_score", "risk_label",
            "flags", "recommendation",
        ]:
            self.assertIn(key, s)

    def test_zero_deviation_peg_score_100(self):
        s = _make_stablecoin(peg_deviation_30d_max_pct=0.0)
        result = analyze([s])
        self.assertEqual(result["stablecoins"][0]["peg_stability_score"], 100)

    def test_very_high_risk_scenario(self):
        s = _make_stablecoin(
            collateral_ratio_pct=70.0,
            peg_deviation_30d_max_pct=2.0,
            redemption_mechanism="AMM_ONLY",
            current_apy_pct=0.5,
            liquidity_depth_usd=0,
            tvl_usd=1_000_000,
        )
        result = analyze([s])
        self.assertIn(result["stablecoins"][0]["risk_label"], ["HIGH_RISK", "VERY_HIGH_RISK"])


# ---------------------------------------------------------------------------
# Composite score formula validation
# ---------------------------------------------------------------------------

class TestCompositeScoringFormula(unittest.TestCase):
    def test_known_values(self):
        """
        sDAI-like: apy=5%, peg_dev=0.1%, coll=150%, INSTANT, liq=50M/500M
        apy_norm = min(100, int(5*10)) = 50
        peg_stability = 100 - int(0.1*200) = 80
        safety = min(100, max(0, int((150-100)*2+50))) = 100
        redemption = 100
        liquidity = min(100, int(50M/500M*100)) = 10
        composite = int(50*0.25 + 80*0.30 + 100*0.25 + 100*0.10 + 10*0.10)
                  = int(12.5 + 24 + 25 + 10 + 1) = int(72.5) = 72
        """
        result = analyze([_make_stablecoin(
            current_apy_pct=5.0,
            tvl_usd=500_000_000,
            peg_deviation_30d_max_pct=0.1,
            redemption_mechanism="INSTANT",
            collateral_ratio_pct=150.0,
            liquidity_depth_usd=50_000_000,
        )])
        self.assertEqual(result["stablecoins"][0]["composite_score"], 72)

    def test_queued_redemption_penalized(self):
        r_instant = analyze([_make_stablecoin(redemption_mechanism="INSTANT")])
        r_queued = analyze([_make_stablecoin(redemption_mechanism="QUEUED")])
        self.assertGreater(
            r_instant["stablecoins"][0]["composite_score"],
            r_queued["stablecoins"][0]["composite_score"],
        )

    def test_high_peg_deviation_lowers_composite(self):
        r_good = analyze([_make_stablecoin(peg_deviation_30d_max_pct=0.0)])
        r_bad = analyze([_make_stablecoin(peg_deviation_30d_max_pct=0.4)])
        self.assertGreater(
            r_good["stablecoins"][0]["composite_score"],
            r_bad["stablecoins"][0]["composite_score"],
        )

    def test_undercollateralized_lowers_safety(self):
        r_full = analyze([_make_stablecoin(collateral_ratio_pct=150.0)])
        r_under = analyze([_make_stablecoin(collateral_ratio_pct=90.0)])
        self.assertGreater(
            r_full["stablecoins"][0]["safety_score"],
            r_under["stablecoins"][0]["safety_score"],
        )


# ---------------------------------------------------------------------------
# Log tests
# ---------------------------------------------------------------------------

class TestAppendLog(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._log_path = os.path.join(self._tmpdir, "test_log.json")

    def test_creates_file(self):
        _append_log({"x": 1}, self._log_path)
        self.assertTrue(os.path.exists(self._log_path))

    def test_content_is_list(self):
        _append_log({"x": 1}, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_single_entry(self):
        _append_log({"x": 1}, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_multiple_entries(self):
        for i in range(5):
            _append_log({"i": i}, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer(self):
        for i in range(_RING_BUFFER_MAX + 10):
            _append_log({"i": i}, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), _RING_BUFFER_MAX)

    def test_ring_buffer_keeps_latest(self):
        for i in range(_RING_BUFFER_MAX + 3):
            _append_log({"i": i}, self._log_path)
        with open(self._log_path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], _RING_BUFFER_MAX + 2)

    def test_analyze_no_exception(self):
        result = analyze([_make_stablecoin()])
        self.assertIn("timestamp", result)


if __name__ == "__main__":
    unittest.main()
