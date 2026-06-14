"""
Tests for MP-892 ProtocolMarketCapToTVLAnalyzer.
Run with: python3 -m unittest spa_core.tests.test_protocol_market_cap_to_tvl_analyzer -v
"""
import json
import os
import sys
import tempfile
import time
import unittest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_market_cap_to_tvl_analyzer import (
    analyze,
    log_result,
    _valuation_label,
    _dilution_risk,
    _revenue_multiple_label,
    _valuation_score,
    _dilution_score,
    _revenue_score,
    _composite_attractiveness,
    _build_recommendation,
    _load_log,
    _atomic_write,
    _RING_BUFFER_CAP,
    _DEFAULT_UNDERVALUED_THRESHOLD,
    _DEFAULT_OVERVALUED_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proto(
    name="TestProto",
    market_cap_usd=1_000_000_000,
    fully_diluted_valuation_usd=2_000_000_000,
    tvl_usd=2_000_000_000,
    revenue_30d_usd=5_000_000,
    token_circulating_pct=75.0,
    sector="LENDING",
):
    return {
        "name": name,
        "market_cap_usd": market_cap_usd,
        "fully_diluted_valuation_usd": fully_diluted_valuation_usd,
        "tvl_usd": tvl_usd,
        "revenue_30d_usd": revenue_30d_usd,
        "token_circulating_pct": token_circulating_pct,
        "sector": sector,
    }


_DEFAULT_THRESHOLDS = (0.5, 3.0)


# ---------------------------------------------------------------------------
# 1. _valuation_label
# ---------------------------------------------------------------------------

class TestValuationLabel(unittest.TestCase):
    def _label(self, mc_to_tvl):
        return _valuation_label(mc_to_tvl, *_DEFAULT_THRESHOLDS)

    def test_unanalyzable_for_negative(self):
        self.assertEqual(self._label(-1.0), "UNANALYZABLE")

    def test_deeply_undervalued_below_025(self):
        self.assertEqual(self._label(0.1), "DEEPLY_UNDERVALUED")

    def test_deeply_undervalued_at_024(self):
        self.assertEqual(self._label(0.24), "DEEPLY_UNDERVALUED")

    def test_undervalued_at_025(self):
        self.assertEqual(self._label(0.25), "UNDERVALUED")

    def test_undervalued_just_below_05(self):
        self.assertEqual(self._label(0.49), "UNDERVALUED")

    def test_fair_value_at_05(self):
        self.assertEqual(self._label(0.5), "FAIR_VALUE")

    def test_fair_value_between(self):
        self.assertEqual(self._label(1.5), "FAIR_VALUE")

    def test_fair_value_just_below_30(self):
        self.assertEqual(self._label(2.99), "FAIR_VALUE")

    def test_overvalued_at_30(self):
        self.assertEqual(self._label(3.0), "OVERVALUED")

    def test_overvalued_just_below_10(self):
        self.assertEqual(self._label(9.99), "OVERVALUED")

    def test_extremely_overvalued_at_10(self):
        self.assertEqual(self._label(10.0), "EXTREMELY_OVERVALUED")

    def test_extremely_overvalued_above_10(self):
        self.assertEqual(self._label(100.0), "EXTREMELY_OVERVALUED")

    def test_custom_undervalued_threshold(self):
        label = _valuation_label(0.4, 0.3, 3.0)
        self.assertEqual(label, "FAIR_VALUE")

    def test_custom_overvalued_threshold(self):
        label = _valuation_label(2.0, 0.5, 1.5)
        self.assertEqual(label, "OVERVALUED")


# ---------------------------------------------------------------------------
# 2. _dilution_risk
# ---------------------------------------------------------------------------

class TestDilutionRisk(unittest.TestCase):
    def test_low_above_80(self):
        self.assertEqual(_dilution_risk(90.0), "LOW")

    def test_low_just_above_80(self):
        self.assertEqual(_dilution_risk(80.1), "LOW")

    def test_moderate_at_80(self):
        # 80 is NOT > 80, falls to > 50 branch
        self.assertEqual(_dilution_risk(80.0), "MODERATE")

    def test_moderate_between_50_and_80(self):
        self.assertEqual(_dilution_risk(65.0), "MODERATE")

    def test_moderate_just_above_50(self):
        self.assertEqual(_dilution_risk(50.1), "MODERATE")

    def test_high_at_50(self):
        # 50 is NOT > 50, falls to > 30 branch
        self.assertEqual(_dilution_risk(50.0), "HIGH")

    def test_high_between_30_and_50(self):
        self.assertEqual(_dilution_risk(40.0), "HIGH")

    def test_high_just_above_30(self):
        self.assertEqual(_dilution_risk(30.1), "HIGH")

    def test_critical_at_30(self):
        self.assertEqual(_dilution_risk(30.0), "CRITICAL")

    def test_critical_below_30(self):
        self.assertEqual(_dilution_risk(10.0), "CRITICAL")

    def test_critical_zero(self):
        self.assertEqual(_dilution_risk(0.0), "CRITICAL")


# ---------------------------------------------------------------------------
# 3. _revenue_multiple_label
# ---------------------------------------------------------------------------

class TestRevenueMultipleLabel(unittest.TestCase):
    def test_no_revenue_for_negative(self):
        self.assertEqual(_revenue_multiple_label(-1.0), "NO_REVENUE")

    def test_cheap_below_10(self):
        self.assertEqual(_revenue_multiple_label(5.0), "CHEAP")

    def test_cheap_just_below_10(self):
        self.assertEqual(_revenue_multiple_label(9.99), "CHEAP")

    def test_fair_at_10(self):
        self.assertEqual(_revenue_multiple_label(10.0), "FAIR")

    def test_fair_between(self):
        self.assertEqual(_revenue_multiple_label(20.0), "FAIR")

    def test_fair_just_below_25(self):
        self.assertEqual(_revenue_multiple_label(24.99), "FAIR")

    def test_expensive_at_25(self):
        self.assertEqual(_revenue_multiple_label(25.0), "EXPENSIVE")

    def test_expensive_between(self):
        self.assertEqual(_revenue_multiple_label(40.0), "EXPENSIVE")

    def test_expensive_just_below_50(self):
        self.assertEqual(_revenue_multiple_label(49.99), "EXPENSIVE")

    def test_very_expensive_at_50(self):
        self.assertEqual(_revenue_multiple_label(50.0), "VERY_EXPENSIVE")

    def test_very_expensive_above_50(self):
        self.assertEqual(_revenue_multiple_label(200.0), "VERY_EXPENSIVE")


# ---------------------------------------------------------------------------
# 4. _valuation_score
# ---------------------------------------------------------------------------

class TestValuationScore(unittest.TestCase):
    def test_deeply_undervalued(self):
        self.assertEqual(_valuation_score("DEEPLY_UNDERVALUED"), 100)

    def test_undervalued(self):
        self.assertEqual(_valuation_score("UNDERVALUED"), 80)

    def test_fair_value(self):
        self.assertEqual(_valuation_score("FAIR_VALUE"), 60)

    def test_overvalued(self):
        self.assertEqual(_valuation_score("OVERVALUED"), 30)

    def test_extremely_overvalued(self):
        self.assertEqual(_valuation_score("EXTREMELY_OVERVALUED"), 10)

    def test_unanalyzable(self):
        self.assertEqual(_valuation_score("UNANALYZABLE"), 50)


# ---------------------------------------------------------------------------
# 5. _dilution_score
# ---------------------------------------------------------------------------

class TestDilutionScore(unittest.TestCase):
    def test_low(self):
        self.assertEqual(_dilution_score("LOW"), 30)

    def test_moderate(self):
        self.assertEqual(_dilution_score("MODERATE"), 20)

    def test_high(self):
        self.assertEqual(_dilution_score("HIGH"), 10)

    def test_critical(self):
        self.assertEqual(_dilution_score("CRITICAL"), 0)


# ---------------------------------------------------------------------------
# 6. _revenue_score
# ---------------------------------------------------------------------------

class TestRevenueScore(unittest.TestCase):
    def test_cheap(self):
        self.assertEqual(_revenue_score("CHEAP"), 20)

    def test_fair(self):
        self.assertEqual(_revenue_score("FAIR"), 15)

    def test_expensive(self):
        self.assertEqual(_revenue_score("EXPENSIVE"), 8)

    def test_very_expensive(self):
        self.assertEqual(_revenue_score("VERY_EXPENSIVE"), 3)

    def test_no_revenue(self):
        self.assertEqual(_revenue_score("NO_REVENUE"), 0)


# ---------------------------------------------------------------------------
# 7. _composite_attractiveness
# ---------------------------------------------------------------------------

class TestCompositeAttractiveness(unittest.TestCase):
    def test_max_score_capped_at_100(self):
        # 100 + 30 + 20 = 150 → capped at 100
        score = _composite_attractiveness("DEEPLY_UNDERVALUED", "LOW", "CHEAP")
        self.assertEqual(score, 100)

    def test_min_score(self):
        score = _composite_attractiveness("EXTREMELY_OVERVALUED", "CRITICAL", "NO_REVENUE")
        self.assertEqual(score, 10)

    def test_unanalyzable_base(self):
        score = _composite_attractiveness("UNANALYZABLE", "LOW", "NO_REVENUE")
        self.assertEqual(score, 80)  # 50 + 30 + 0

    def test_fair_moderate_fair(self):
        score = _composite_attractiveness("FAIR_VALUE", "MODERATE", "FAIR")
        self.assertEqual(score, 95)  # 60 + 20 + 15 = 95

    def test_overvalued_critical_no_revenue(self):
        score = _composite_attractiveness("OVERVALUED", "CRITICAL", "NO_REVENUE")
        self.assertEqual(score, 30)  # 30 + 0 + 0


# ---------------------------------------------------------------------------
# 8. analyze() — empty input
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.result = analyze([])

    def test_protocols_empty(self):
        self.assertEqual(self.result["protocols"], [])

    def test_by_sector_empty(self):
        self.assertEqual(self.result["by_sector"], {})

    def test_most_attractive_none(self):
        self.assertIsNone(self.result["most_attractive"])

    def test_most_overvalued_none(self):
        self.assertIsNone(self.result["most_overvalued"])

    def test_market_avg_mc_to_tvl_zero(self):
        self.assertAlmostEqual(self.result["market_avg_mc_to_tvl"], 0.0)

    def test_timestamp_present(self):
        self.assertIn("timestamp", self.result)
        self.assertIsInstance(self.result["timestamp"], float)


# ---------------------------------------------------------------------------
# 9. analyze() — single protocol with TVL
# ---------------------------------------------------------------------------

class TestAnalyzeSingle(unittest.TestCase):
    def setUp(self):
        self.p = _proto(
            name="Aave",
            market_cap_usd=1_500_000_000,
            fully_diluted_valuation_usd=2_000_000_000,
            tvl_usd=15_000_000_000,
            revenue_30d_usd=10_000_000,
            token_circulating_pct=75.0,
            sector="LENDING",
        )
        self.result = analyze([self.p])
        self.proto = self.result["protocols"][0]

    def test_mc_to_tvl(self):
        self.assertAlmostEqual(self.proto["mc_to_tvl"], 1_500_000_000 / 15_000_000_000)

    def test_fdv_to_tvl(self):
        self.assertAlmostEqual(self.proto["fdv_to_tvl"], 2_000_000_000 / 15_000_000_000)

    def test_price_to_revenue(self):
        expected = 1_500_000_000 / (10_000_000 * 12)
        self.assertAlmostEqual(self.proto["price_to_revenue"], expected)

    def test_valuation_label_fair(self):
        # mc_to_tvl ≈ 0.1 → DEEPLY_UNDERVALUED
        self.assertEqual(self.proto["valuation_label"], "DEEPLY_UNDERVALUED")

    def test_dilution_risk_moderate(self):
        # 75 is NOT > 80 → MODERATE
        self.assertEqual(self.proto["dilution_risk"], "MODERATE")

    def test_sector_preserved(self):
        self.assertEqual(self.proto["sector"], "LENDING")

    def test_name_preserved(self):
        self.assertEqual(self.proto["name"], "Aave")

    def test_most_attractive_aave(self):
        self.assertEqual(self.result["most_attractive"], "Aave")

    def test_most_overvalued_aave(self):
        self.assertEqual(self.result["most_overvalued"], "Aave")

    def test_market_avg_mc_to_tvl(self):
        self.assertAlmostEqual(
            self.result["market_avg_mc_to_tvl"],
            1_500_000_000 / 15_000_000_000,
        )


# ---------------------------------------------------------------------------
# 10. analyze() — TVL = 0 (UNANALYZABLE)
# ---------------------------------------------------------------------------

class TestAnalyzeTvlZero(unittest.TestCase):
    def setUp(self):
        self.p = _proto(tvl_usd=0.0)
        self.result = analyze([self.p])
        self.proto = self.result["protocols"][0]

    def test_mc_to_tvl_minus_one(self):
        self.assertAlmostEqual(self.proto["mc_to_tvl"], -1.0)

    def test_fdv_to_tvl_minus_one(self):
        self.assertAlmostEqual(self.proto["fdv_to_tvl"], -1.0)

    def test_valuation_label_unanalyzable(self):
        self.assertEqual(self.proto["valuation_label"], "UNANALYZABLE")

    def test_recommendation_insufficient_tvl(self):
        self.assertIn("Insufficient TVL", self.proto["recommendation"])

    def test_most_overvalued_none_when_all_unanalyzable(self):
        self.assertIsNone(self.result["most_overvalued"])

    def test_market_avg_zero_when_all_unanalyzable(self):
        self.assertAlmostEqual(self.result["market_avg_mc_to_tvl"], 0.0)


# ---------------------------------------------------------------------------
# 11. analyze() — revenue = 0 (NO_REVENUE)
# ---------------------------------------------------------------------------

class TestAnalyzeNoRevenue(unittest.TestCase):
    def setUp(self):
        self.p = _proto(revenue_30d_usd=0.0)
        self.result = analyze([self.p])
        self.proto = self.result["protocols"][0]

    def test_price_to_revenue_minus_one(self):
        self.assertAlmostEqual(self.proto["price_to_revenue"], -1.0)

    def test_revenue_multiple_label_no_revenue(self):
        self.assertEqual(self.proto["revenue_multiple_label"], "NO_REVENUE")


# ---------------------------------------------------------------------------
# 12. by_sector aggregation
# ---------------------------------------------------------------------------

class TestBySector(unittest.TestCase):
    def setUp(self):
        protos = [
            _proto(name="A", market_cap_usd=1_000_000_000, tvl_usd=2_000_000_000, sector="LENDING"),
            _proto(name="B", market_cap_usd=3_000_000_000, tvl_usd=2_000_000_000, sector="LENDING"),
            _proto(name="C", market_cap_usd=500_000_000, tvl_usd=1_000_000_000, sector="DEX"),
        ]
        self.result = analyze(protos)

    def test_lending_in_by_sector(self):
        self.assertIn("LENDING", self.result["by_sector"])

    def test_dex_in_by_sector(self):
        self.assertIn("DEX", self.result["by_sector"])

    def test_lending_count(self):
        self.assertEqual(self.result["by_sector"]["LENDING"]["count"], 2)

    def test_dex_count(self):
        self.assertEqual(self.result["by_sector"]["DEX"]["count"], 1)

    def test_lending_avg_mc_to_tvl(self):
        # A: 0.5, B: 1.5 → avg 1.0
        self.assertAlmostEqual(self.result["by_sector"]["LENDING"]["avg_mc_to_tvl"], 1.0)

    def test_dex_avg_mc_to_tvl(self):
        self.assertAlmostEqual(self.result["by_sector"]["DEX"]["avg_mc_to_tvl"], 0.5)


# ---------------------------------------------------------------------------
# 13. most_attractive and most_overvalued
# ---------------------------------------------------------------------------

class TestMostAttractiveMostOvervalued(unittest.TestCase):
    def setUp(self):
        protos = [
            # DEEPLY_UNDERVALUED + LOW dilution + CHEAP → very high composite
            _proto(name="Underdog", market_cap_usd=100_000_000, tvl_usd=5_000_000_000,
                   token_circulating_pct=90.0, revenue_30d_usd=5_000_000, sector="LENDING"),
            # EXTREMELY_OVERVALUED + CRITICAL dilution → very low composite
            _proto(name="Moonshot", market_cap_usd=50_000_000_000, tvl_usd=1_000_000_000,
                   token_circulating_pct=10.0, revenue_30d_usd=0.0, sector="DEX"),
        ]
        self.result = analyze(protos)

    def test_most_attractive_is_underdog(self):
        self.assertEqual(self.result["most_attractive"], "Underdog")

    def test_most_overvalued_is_moonshot(self):
        self.assertEqual(self.result["most_overvalued"], "Moonshot")


# ---------------------------------------------------------------------------
# 14. market_avg_mc_to_tvl excludes negatives
# ---------------------------------------------------------------------------

class TestMarketAvg(unittest.TestCase):
    def test_excludes_unanalyzable(self):
        protos = [
            _proto(name="A", market_cap_usd=2_000_000_000, tvl_usd=4_000_000_000),
            _proto(name="B", tvl_usd=0.0),  # -1, excluded
        ]
        result = analyze(protos)
        # Only A contributes: 0.5
        self.assertAlmostEqual(result["market_avg_mc_to_tvl"], 0.5)

    def test_all_unanalyzable_returns_zero(self):
        protos = [_proto(tvl_usd=0.0), _proto(tvl_usd=0.0)]
        result = analyze(protos)
        self.assertAlmostEqual(result["market_avg_mc_to_tvl"], 0.0)


# ---------------------------------------------------------------------------
# 15. Output schema completeness
# ---------------------------------------------------------------------------

class TestOutputSchema(unittest.TestCase):
    PROTO_KEYS = {
        "name", "sector", "mc_to_tvl", "fdv_to_tvl", "price_to_revenue",
        "valuation_label", "dilution_risk", "revenue_multiple_label",
        "composite_attractiveness", "recommendation",
    }
    TOP_KEYS = {
        "protocols", "by_sector", "most_attractive",
        "most_overvalued", "market_avg_mc_to_tvl", "timestamp",
    }

    def test_top_level_keys(self):
        result = analyze([_proto()])
        self.assertEqual(set(result.keys()), self.TOP_KEYS)

    def test_protocol_keys(self):
        result = analyze([_proto()])
        self.assertEqual(set(result["protocols"][0].keys()), self.PROTO_KEYS)

    def test_composite_attractiveness_is_int(self):
        result = analyze([_proto()])
        self.assertIsInstance(result["protocols"][0]["composite_attractiveness"], int)

    def test_composite_in_range(self):
        result = analyze([_proto()])
        val = result["protocols"][0]["composite_attractiveness"]
        self.assertGreaterEqual(val, 0)
        self.assertLessEqual(val, 100)


# ---------------------------------------------------------------------------
# 16. Recommendations
# ---------------------------------------------------------------------------

class TestRecommendations(unittest.TestCase):
    def test_highly_attractive_recommendation(self):
        # DEEPLY_UNDERVALUED(100) + LOW(30) + CHEAP(20) = 150 → capped at 100 ≥ 85
        rec = _build_recommendation(100, "DEEPLY_UNDERVALUED", 0.1, "CHEAP", "LOW")
        self.assertIn("Highly attractive", rec)

    def test_solid_value_recommendation(self):
        # composite 65-84
        rec = _build_recommendation(70, "FAIR_VALUE", 1.5, "FAIR", "MODERATE")
        self.assertIn("Solid value", rec)

    def test_fair_valuation_recommendation(self):
        rec = _build_recommendation(50, "FAIR_VALUE", 2.0, "EXPENSIVE", "HIGH")
        self.assertIn("Fair valuation", rec)

    def test_avoid_recommendation(self):
        rec = _build_recommendation(30, "OVERVALUED", 5.0, "VERY_EXPENSIVE", "CRITICAL")
        self.assertIn("Avoid", rec)

    def test_unanalyzable_recommendation(self):
        rec = _build_recommendation(50, "UNANALYZABLE", -1.0, "NO_REVENUE", "LOW")
        self.assertIn("Insufficient TVL", rec)


# ---------------------------------------------------------------------------
# 17. Config overrides
# ---------------------------------------------------------------------------

class TestConfigOverrides(unittest.TestCase):
    def test_custom_undervalued_threshold(self):
        # mc_to_tvl = 0.4, default undervalued_threshold=0.5 → UNDERVALUED
        # custom = 0.3 → FAIR_VALUE (0.4 >= 0.3)
        p = _proto(market_cap_usd=400_000_000, tvl_usd=1_000_000_000)
        result = analyze([p], config={"undervalued_threshold": 0.3, "overvalued_threshold": 3.0})
        self.assertEqual(result["protocols"][0]["valuation_label"], "FAIR_VALUE")

    def test_custom_overvalued_threshold(self):
        # mc_to_tvl = 2.0, default overvalued_threshold=3.0 → FAIR_VALUE
        # custom = 1.5 → OVERVALUED (2.0 >= 1.5)
        p = _proto(market_cap_usd=2_000_000_000, tvl_usd=1_000_000_000)
        result = analyze([p], config={"undervalued_threshold": 0.5, "overvalued_threshold": 1.5})
        self.assertEqual(result["protocols"][0]["valuation_label"], "OVERVALUED")

    def test_none_config_uses_defaults(self):
        p = _proto(market_cap_usd=400_000_000, tvl_usd=1_000_000_000)
        result = analyze([p], config=None)
        # mc_to_tvl = 0.4 < 0.5 default → UNDERVALUED
        self.assertEqual(result["protocols"][0]["valuation_label"], "UNDERVALUED")


# ---------------------------------------------------------------------------
# 18. log_result and persistence
# ---------------------------------------------------------------------------

class TestLogResult(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_log.json")

    def test_creates_log_file(self):
        result = analyze([_proto()])
        log_result(result, data_file=self.log_path)
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        result = analyze([_proto()])
        log_result(result, data_file=self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends(self):
        for _ in range(5):
            log_result(analyze([_proto()]), data_file=self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        for _ in range(_RING_BUFFER_CAP + 10):
            log_result(analyze([_proto()]), data_file=self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _RING_BUFFER_CAP)

    def test_atomic_write_produces_valid_json(self):
        path = os.path.join(self.tmpdir, "atomic.json")
        _atomic_write(path, [{"key": "value"}])
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data, [{"key": "value"}])


# ---------------------------------------------------------------------------
# 19. _load_log edge cases
# ---------------------------------------------------------------------------

class TestLoadLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_missing_file_returns_empty_list(self):
        result = _load_log(os.path.join(self.tmpdir, "nonexistent.json"))
        self.assertEqual(result, [])

    def test_corrupt_json_returns_empty_list(self):
        path = os.path.join(self.tmpdir, "corrupt.json")
        with open(path, "w") as f:
            f.write("NOT_JSON{{{{")
        result = _load_log(path)
        self.assertEqual(result, [])

    def test_non_list_json_returns_empty_list(self):
        path = os.path.join(self.tmpdir, "dict.json")
        with open(path, "w") as f:
            json.dump({"key": "val"}, f)
        result = _load_log(path)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# 20. Timestamp
# ---------------------------------------------------------------------------

class TestTimestamp(unittest.TestCase):
    def test_timestamp_is_recent(self):
        before = time.time()
        result = analyze([_proto()])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)


# ---------------------------------------------------------------------------
# 21. Constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_ring_buffer_cap(self):
        self.assertEqual(_RING_BUFFER_CAP, 100)

    def test_default_undervalued_threshold(self):
        self.assertAlmostEqual(_DEFAULT_UNDERVALUED_THRESHOLD, 0.5)

    def test_default_overvalued_threshold(self):
        self.assertAlmostEqual(_DEFAULT_OVERVALUED_THRESHOLD, 3.0)


# ---------------------------------------------------------------------------
# 22. Multiple protocols — counts and names
# ---------------------------------------------------------------------------

class TestMultipleProtocols(unittest.TestCase):
    def setUp(self):
        self.protos = [
            _proto(name="P1", market_cap_usd=100_000_000, tvl_usd=2_000_000_000),
            _proto(name="P2", market_cap_usd=500_000_000, tvl_usd=2_000_000_000),
            _proto(name="P3", market_cap_usd=6_000_000_000, tvl_usd=2_000_000_000),
        ]
        self.result = analyze(self.protos)

    def test_protocol_count(self):
        self.assertEqual(len(self.result["protocols"]), 3)

    def test_most_overvalued_is_p3(self):
        self.assertEqual(self.result["most_overvalued"], "P3")

    def test_most_attractive_is_p1(self):
        self.assertEqual(self.result["most_attractive"], "P1")

    def test_market_avg(self):
        # mc_to_tvls: 0.05, 0.25, 3.0 → avg = (0.05+0.25+3.0)/3
        expected = (0.05 + 0.25 + 3.0) / 3
        self.assertAlmostEqual(self.result["market_avg_mc_to_tvl"], expected)


# ---------------------------------------------------------------------------
# 23. by_sector excludes -1 from avg_mc_to_tvl
# ---------------------------------------------------------------------------

class TestBySectorExcludesNegative(unittest.TestCase):
    def test_unanalyzable_excluded_from_avg(self):
        protos = [
            _proto(name="A", market_cap_usd=2_000_000_000, tvl_usd=4_000_000_000, sector="DEX"),
            _proto(name="B", tvl_usd=0.0, sector="DEX"),  # UNANALYZABLE
        ]
        result = analyze(protos)
        # Only A contributes to avg: 0.5
        self.assertAlmostEqual(result["by_sector"]["DEX"]["avg_mc_to_tvl"], 0.5)
        self.assertEqual(result["by_sector"]["DEX"]["count"], 2)

    def test_sector_all_unanalyzable_avg_zero(self):
        protos = [
            _proto(name="A", tvl_usd=0.0, sector="BRIDGE"),
            _proto(name="B", tvl_usd=0.0, sector="BRIDGE"),
        ]
        result = analyze(protos)
        self.assertAlmostEqual(result["by_sector"]["BRIDGE"]["avg_mc_to_tvl"], 0.0)


if __name__ == "__main__":
    unittest.main()
