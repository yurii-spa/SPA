"""
Tests for MP-891 DeFiYieldSourceVerifier.
Run with: python3 -m unittest spa_core.tests.test_defi_yield_source_verifier -v
"""
import json
import os
import sys
import tempfile
import time
import unittest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_yield_source_verifier import (
    analyze,
    log_result,
    _sell_pressure_penalty,
    _price_penalty,
    _emission_sustainability_score,
    _yield_authenticity,
    _sustainability_risk,
    _load_log,
    _atomic_write,
    _RING_BUFFER_CAP,
    _DEFAULT_MIN_REAL_YIELD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proto(
    name="TestProto",
    claimed_apy_pct=10.0,
    real_revenue_apy_pct=8.0,
    token_emission_apy_pct=2.0,
    token_price_change_90d_pct=5.0,
    protocol_revenue_30d_usd=1_000_000,
    total_tvl_usd=100_000_000,
    emission_token_sell_pressure="LOW",
):
    return {
        "name": name,
        "claimed_apy_pct": claimed_apy_pct,
        "real_revenue_apy_pct": real_revenue_apy_pct,
        "token_emission_apy_pct": token_emission_apy_pct,
        "token_price_change_90d_pct": token_price_change_90d_pct,
        "protocol_revenue_30d_usd": protocol_revenue_30d_usd,
        "total_tvl_usd": total_tvl_usd,
        "emission_token_sell_pressure": emission_token_sell_pressure,
    }


# ---------------------------------------------------------------------------
# 1. _sell_pressure_penalty
# ---------------------------------------------------------------------------

class TestSellPressurePenalty(unittest.TestCase):
    def test_low(self):
        self.assertEqual(_sell_pressure_penalty("LOW"), 0)

    def test_moderate(self):
        self.assertEqual(_sell_pressure_penalty("MODERATE"), 10)

    def test_high(self):
        self.assertEqual(_sell_pressure_penalty("HIGH"), 25)

    def test_extreme(self):
        self.assertEqual(_sell_pressure_penalty("EXTREME"), 45)

    def test_unknown_returns_zero(self):
        self.assertEqual(_sell_pressure_penalty("UNKNOWN"), 0)

    def test_case_insensitive_low(self):
        self.assertEqual(_sell_pressure_penalty("low"), 0)

    def test_case_insensitive_extreme(self):
        self.assertEqual(_sell_pressure_penalty("extreme"), 45)


# ---------------------------------------------------------------------------
# 2. _price_penalty
# ---------------------------------------------------------------------------

class TestPricePenalty(unittest.TestCase):
    def test_very_negative(self):
        self.assertEqual(_price_penalty(-60), 30)

    def test_exactly_minus_50(self):
        # -50 is NOT < -50, falls into the < -20 branch → penalty 20
        self.assertEqual(_price_penalty(-50), 20)

    def test_between_minus_50_and_minus_20(self):
        self.assertEqual(_price_penalty(-30), 20)

    def test_exactly_minus_20(self):
        # -20 is NOT < -20, falls to < 0 branch
        self.assertEqual(_price_penalty(-20), 10)

    def test_slightly_negative(self):
        self.assertEqual(_price_penalty(-1), 10)

    def test_zero(self):
        self.assertEqual(_price_penalty(0), 0)

    def test_positive(self):
        self.assertEqual(_price_penalty(50), 0)

    def test_minus_51(self):
        self.assertEqual(_price_penalty(-51), 30)


# ---------------------------------------------------------------------------
# 3. _emission_sustainability_score
# ---------------------------------------------------------------------------

class TestEmissionSustainabilityScore(unittest.TestCase):
    def test_perfect_score(self):
        # LOW penalty + 0 price penalty → 100
        self.assertEqual(_emission_sustainability_score("LOW", 10.0), 100)

    def test_extreme_falling(self):
        # 45 + 30 = 75 penalty → 100-75 = 25
        self.assertEqual(_emission_sustainability_score("EXTREME", -60.0), 25)

    def test_clamp_min_zero(self):
        # Even if penalties exceed 100, score clamps at 0
        score = _emission_sustainability_score("EXTREME", -51.0)
        self.assertGreaterEqual(score, 0)

    def test_clamp_max_100(self):
        score = _emission_sustainability_score("LOW", 100.0)
        self.assertLessEqual(score, 100)

    def test_moderate_stable(self):
        # 10 + 0 = 10 → 90
        self.assertEqual(_emission_sustainability_score("MODERATE", 5.0), 90)

    def test_high_falling_price(self):
        # 25 + 20 = 45 → 55
        self.assertEqual(_emission_sustainability_score("HIGH", -30.0), 55)

    def test_returns_int(self):
        score = _emission_sustainability_score("LOW", 0.0)
        self.assertIsInstance(score, int)


# ---------------------------------------------------------------------------
# 4. _yield_authenticity
# ---------------------------------------------------------------------------

class TestYieldAuthenticity(unittest.TestCase):
    def test_genuine_boundary(self):
        self.assertEqual(_yield_authenticity(70.0), "GENUINE")

    def test_genuine_above(self):
        self.assertEqual(_yield_authenticity(95.0), "GENUINE")

    def test_mixed_at_40(self):
        self.assertEqual(_yield_authenticity(40.0), "MIXED")

    def test_mixed_between(self):
        self.assertEqual(_yield_authenticity(55.0), "MIXED")

    def test_emission_driven_at_20(self):
        self.assertEqual(_yield_authenticity(20.0), "EMISSION_DRIVEN")

    def test_emission_driven_between(self):
        self.assertEqual(_yield_authenticity(35.0), "EMISSION_DRIVEN")

    def test_unsustainable_below_20(self):
        self.assertEqual(_yield_authenticity(19.9), "UNSUSTAINABLE")

    def test_unsustainable_zero(self):
        self.assertEqual(_yield_authenticity(0.0), "UNSUSTAINABLE")


# ---------------------------------------------------------------------------
# 5. _sustainability_risk
# ---------------------------------------------------------------------------

class TestSustainabilityRisk(unittest.TestCase):
    def test_low_at_70(self):
        self.assertEqual(_sustainability_risk(70), "LOW")

    def test_low_above(self):
        self.assertEqual(_sustainability_risk(100), "LOW")

    def test_moderate_at_50(self):
        self.assertEqual(_sustainability_risk(50), "MODERATE")

    def test_moderate_between(self):
        self.assertEqual(_sustainability_risk(65), "MODERATE")

    def test_high_at_30(self):
        self.assertEqual(_sustainability_risk(30), "HIGH")

    def test_high_between(self):
        self.assertEqual(_sustainability_risk(45), "HIGH")

    def test_critical_below_30(self):
        self.assertEqual(_sustainability_risk(29), "CRITICAL")

    def test_critical_zero(self):
        self.assertEqual(_sustainability_risk(0), "CRITICAL")


# ---------------------------------------------------------------------------
# 6. analyze() — empty input
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.result = analyze([])

    def test_protocols_empty(self):
        self.assertEqual(self.result["protocols"], [])

    def test_avg_real_yield_zero(self):
        self.assertEqual(self.result["average_real_yield_pct"], 0.0)

    def test_genuine_count_zero(self):
        self.assertEqual(self.result["genuine_count"], 0)

    def test_unsustainable_count_zero(self):
        self.assertEqual(self.result["unsustainable_count"], 0)

    def test_timestamp_present(self):
        self.assertIn("timestamp", self.result)
        self.assertIsInstance(self.result["timestamp"], float)


# ---------------------------------------------------------------------------
# 7. analyze() — single genuine protocol
# ---------------------------------------------------------------------------

class TestAnalyzeSingleGenuine(unittest.TestCase):
    def setUp(self):
        self.p = _proto(
            claimed_apy_pct=10.0,
            real_revenue_apy_pct=8.0,
            token_emission_apy_pct=2.0,
            token_price_change_90d_pct=5.0,
            protocol_revenue_30d_usd=1_000_000,
            total_tvl_usd=100_000_000,
            emission_token_sell_pressure="LOW",
        )
        self.result = analyze([self.p])
        self.proto = self.result["protocols"][0]

    def test_real_yield_ratio(self):
        self.assertAlmostEqual(self.proto["real_yield_ratio"], 80.0)

    def test_yield_authenticity_genuine(self):
        self.assertEqual(self.proto["yield_authenticity"], "GENUINE")

    def test_emission_yield(self):
        self.assertAlmostEqual(self.proto["emission_yield_pct"], 2.0)

    def test_revenue_yield_pct(self):
        # 1_000_000 * 12 / 100_000_000 * 100 = 12.0
        self.assertAlmostEqual(self.proto["revenue_yield_pct"], 12.0)

    def test_emission_sustainability_score_low_positive(self):
        self.assertEqual(self.proto["emission_sustainability_score"], 100)

    def test_sustainability_risk_low(self):
        self.assertEqual(self.proto["sustainability_risk"], "LOW")

    def test_genuine_count_one(self):
        self.assertEqual(self.result["genuine_count"], 1)

    def test_unsustainable_count_zero(self):
        self.assertEqual(self.result["unsustainable_count"], 0)

    def test_avg_real_yield(self):
        self.assertAlmostEqual(self.result["average_real_yield_pct"], 8.0)


# ---------------------------------------------------------------------------
# 8. analyze() — single unsustainable protocol
# ---------------------------------------------------------------------------

class TestAnalyzeSingleUnsustainable(unittest.TestCase):
    def setUp(self):
        self.p = _proto(
            claimed_apy_pct=120.0,
            real_revenue_apy_pct=2.0,
            token_emission_apy_pct=118.0,
            token_price_change_90d_pct=-60.0,
            protocol_revenue_30d_usd=50_000,
            total_tvl_usd=30_000_000,
            emission_token_sell_pressure="EXTREME",
        )
        self.result = analyze([self.p])
        self.proto = self.result["protocols"][0]

    def test_yield_authenticity_unsustainable(self):
        self.assertEqual(self.proto["yield_authenticity"], "UNSUSTAINABLE")

    def test_real_yield_ratio(self):
        # 2/120 * 100 ≈ 1.667
        self.assertAlmostEqual(self.proto["real_yield_ratio"], 2.0 / 120.0 * 100, places=4)

    def test_sustainability_risk_critical(self):
        self.assertEqual(self.proto["sustainability_risk"], "CRITICAL")

    def test_flags_include_extreme_sell_pressure(self):
        self.assertIn("EXTREME_SELL_PRESSURE", self.proto["flags"])

    def test_flags_include_falling_token_price(self):
        self.assertIn("FALLING_TOKEN_PRICE", self.proto["flags"])

    def test_unsustainable_count_one(self):
        self.assertEqual(self.result["unsustainable_count"], 1)

    def test_genuine_count_zero(self):
        self.assertEqual(self.result["genuine_count"], 0)

    def test_recommendation_contains_avoid(self):
        self.assertIn("Avoid", self.proto["recommendation"])


# ---------------------------------------------------------------------------
# 9. analyze() — MIXED protocol
# ---------------------------------------------------------------------------

class TestAnalyzeMixed(unittest.TestCase):
    def setUp(self):
        # real_yield_ratio = 5/10 * 100 = 50 → MIXED
        self.p = _proto(
            claimed_apy_pct=10.0,
            real_revenue_apy_pct=5.0,
            token_emission_apy_pct=5.0,
            token_price_change_90d_pct=-10.0,
            emission_token_sell_pressure="MODERATE",
        )
        self.result = analyze([self.p])
        self.proto = self.result["protocols"][0]

    def test_yield_authenticity_mixed(self):
        self.assertEqual(self.proto["yield_authenticity"], "MIXED")

    def test_recommendation_contains_partial(self):
        self.assertIn("Partial", self.proto["recommendation"])

    def test_flags_no_falling_price_at_minus_10(self):
        # -10.0 is not < -20, so FALLING_TOKEN_PRICE should NOT be set
        self.assertNotIn("FALLING_TOKEN_PRICE", self.proto["flags"])


# ---------------------------------------------------------------------------
# 10. analyze() — EMISSION_DRIVEN protocol
# ---------------------------------------------------------------------------

class TestAnalyzeEmissionDriven(unittest.TestCase):
    def setUp(self):
        # real_yield_ratio = 3/15 * 100 = 20 → EMISSION_DRIVEN (boundary)
        self.p = _proto(
            claimed_apy_pct=15.0,
            real_revenue_apy_pct=3.0,
            token_emission_apy_pct=12.0,
            token_price_change_90d_pct=0.0,
            emission_token_sell_pressure="HIGH",
        )
        self.result = analyze([self.p])
        self.proto = self.result["protocols"][0]

    def test_yield_authenticity_emission_driven(self):
        self.assertEqual(self.proto["yield_authenticity"], "EMISSION_DRIVEN")

    def test_recommendation_contains_emission(self):
        self.assertIn("Emission-dependent", self.proto["recommendation"])


# ---------------------------------------------------------------------------
# 11. Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):
    def test_below_min_real_yield_default(self):
        p = _proto(real_revenue_apy_pct=2.0)  # < 3.0
        result = analyze([p])
        self.assertIn("BELOW_MIN_REAL_YIELD", result["protocols"][0]["flags"])

    def test_no_below_min_real_yield(self):
        p = _proto(real_revenue_apy_pct=5.0)
        result = analyze([p])
        self.assertNotIn("BELOW_MIN_REAL_YIELD", result["protocols"][0]["flags"])

    def test_custom_min_real_yield(self):
        p = _proto(real_revenue_apy_pct=4.0)
        result = analyze([p], config={"min_real_yield_pct": 5.0})
        self.assertIn("BELOW_MIN_REAL_YIELD", result["protocols"][0]["flags"])

    def test_extreme_sell_pressure_flag(self):
        p = _proto(emission_token_sell_pressure="EXTREME")
        result = analyze([p])
        self.assertIn("EXTREME_SELL_PRESSURE", result["protocols"][0]["flags"])

    def test_no_extreme_sell_pressure_flag_for_high(self):
        p = _proto(emission_token_sell_pressure="HIGH")
        result = analyze([p])
        self.assertNotIn("EXTREME_SELL_PRESSURE", result["protocols"][0]["flags"])

    def test_falling_token_price_flag(self):
        p = _proto(token_price_change_90d_pct=-25.0)
        result = analyze([p])
        self.assertIn("FALLING_TOKEN_PRICE", result["protocols"][0]["flags"])

    def test_no_falling_token_price_flag_at_minus_20(self):
        # exactly -20 → NOT < -20
        p = _proto(token_price_change_90d_pct=-20.0)
        result = analyze([p])
        self.assertNotIn("FALLING_TOKEN_PRICE", result["protocols"][0]["flags"])

    def test_revenue_mismatch_flag(self):
        # revenue_yield_pct = 100_000 * 12 / 10_000_000 * 100 = 12.0
        # real_revenue_apy_pct = 4.0 → |12 - 4| = 8 > 5 → flag
        p = _proto(
            real_revenue_apy_pct=4.0,
            protocol_revenue_30d_usd=100_000,
            total_tvl_usd=10_000_000,
        )
        result = analyze([p])
        self.assertIn("REVENUE_MISMATCH", result["protocols"][0]["flags"])

    def test_no_revenue_mismatch_when_tvl_zero(self):
        p = _proto(real_revenue_apy_pct=4.0, total_tvl_usd=0.0)
        result = analyze([p])
        self.assertNotIn("REVENUE_MISMATCH", result["protocols"][0]["flags"])


# ---------------------------------------------------------------------------
# 12. claimed_apy_pct = 0 edge case
# ---------------------------------------------------------------------------

class TestClaimedApyZero(unittest.TestCase):
    def test_real_yield_ratio_zero_when_claimed_zero(self):
        p = _proto(claimed_apy_pct=0.0, real_revenue_apy_pct=5.0)
        result = analyze([p])
        self.assertAlmostEqual(result["protocols"][0]["real_yield_ratio"], 0.0)

    def test_yield_authenticity_unsustainable_when_claimed_zero(self):
        p = _proto(claimed_apy_pct=0.0, real_revenue_apy_pct=5.0)
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["yield_authenticity"], "UNSUSTAINABLE")


# ---------------------------------------------------------------------------
# 13. tvl = 0 edge case
# ---------------------------------------------------------------------------

class TestTvlZero(unittest.TestCase):
    def test_revenue_yield_pct_zero_when_tvl_zero(self):
        p = _proto(total_tvl_usd=0.0, protocol_revenue_30d_usd=1_000_000)
        result = analyze([p])
        self.assertAlmostEqual(result["protocols"][0]["revenue_yield_pct"], 0.0)

    def test_no_revenue_mismatch_flag_when_tvl_zero(self):
        p = _proto(total_tvl_usd=0.0, real_revenue_apy_pct=1.0)
        result = analyze([p])
        self.assertNotIn("REVENUE_MISMATCH", result["protocols"][0]["flags"])


# ---------------------------------------------------------------------------
# 14. Multiple protocols aggregates
# ---------------------------------------------------------------------------

class TestMultipleProtocols(unittest.TestCase):
    def setUp(self):
        p1 = _proto(name="A", claimed_apy_pct=10.0, real_revenue_apy_pct=8.0)
        p2 = _proto(name="B", claimed_apy_pct=10.0, real_revenue_apy_pct=6.0)
        self.result = analyze([p1, p2])

    def test_protocol_count(self):
        self.assertEqual(len(self.result["protocols"]), 2)

    def test_avg_real_yield(self):
        self.assertAlmostEqual(self.result["average_real_yield_pct"], 7.0)

    def test_names_preserved(self):
        names = [r["name"] for r in self.result["protocols"]]
        self.assertIn("A", names)
        self.assertIn("B", names)


# ---------------------------------------------------------------------------
# 15. Recommendation strings
# ---------------------------------------------------------------------------

class TestRecommendations(unittest.TestCase):
    def test_genuine_high_real_yield(self):
        # real_revenue_apy_pct >= 5 and GENUINE
        p = _proto(claimed_apy_pct=10.0, real_revenue_apy_pct=7.0)
        result = analyze([p])
        rec = result["protocols"][0]["recommendation"]
        self.assertIn("Strong genuine yield", rec)

    def test_genuine_low_real_yield(self):
        # GENUINE but < 5%: 3.5/4 * 100 = 87.5 → GENUINE, real < 5
        p = _proto(claimed_apy_pct=4.0, real_revenue_apy_pct=3.5)
        result = analyze([p])
        rec = result["protocols"][0]["recommendation"]
        self.assertIn("Yield verified", rec)

    def test_mixed_recommendation(self):
        p = _proto(claimed_apy_pct=10.0, real_revenue_apy_pct=5.0)
        result = analyze([p])
        rec = result["protocols"][0]["recommendation"]
        self.assertIn("Partial emission reliance", rec)

    def test_emission_driven_recommendation(self):
        p = _proto(claimed_apy_pct=15.0, real_revenue_apy_pct=3.0)
        result = analyze([p])
        rec = result["protocols"][0]["recommendation"]
        self.assertIn("Emission-dependent", rec)

    def test_unsustainable_recommendation(self):
        p = _proto(claimed_apy_pct=100.0, real_revenue_apy_pct=1.0)
        result = analyze([p])
        rec = result["protocols"][0]["recommendation"]
        self.assertIn("Avoid", rec)
        self.assertIn("emission-based", rec)


# ---------------------------------------------------------------------------
# 16. Output schema completeness
# ---------------------------------------------------------------------------

class TestOutputSchema(unittest.TestCase):
    PROTO_KEYS = {
        "name", "claimed_apy_pct", "real_yield_pct", "emission_yield_pct",
        "real_yield_ratio", "revenue_yield_pct", "emission_sustainability_score",
        "yield_authenticity", "sustainability_risk", "flags", "recommendation",
    }
    TOP_KEYS = {
        "protocols", "average_real_yield_pct", "genuine_count",
        "unsustainable_count", "timestamp",
    }

    def test_top_level_keys(self):
        result = analyze([_proto()])
        self.assertEqual(set(result.keys()), self.TOP_KEYS)

    def test_protocol_keys(self):
        result = analyze([_proto()])
        self.assertEqual(set(result["protocols"][0].keys()), self.PROTO_KEYS)

    def test_flags_is_list(self):
        result = analyze([_proto()])
        self.assertIsInstance(result["protocols"][0]["flags"], list)

    def test_emission_sustainability_score_is_int(self):
        result = analyze([_proto()])
        self.assertIsInstance(result["protocols"][0]["emission_sustainability_score"], int)


# ---------------------------------------------------------------------------
# 17. log_result and _atomic_write
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
        for _ in range(3):
            log_result(analyze([_proto()]), data_file=self.log_path)
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

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
# 18. _load_log edge cases
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
# 19. Config overrides
# ---------------------------------------------------------------------------

class TestConfigOverrides(unittest.TestCase):
    def test_custom_min_real_yield_no_flag(self):
        p = _proto(real_revenue_apy_pct=4.5)
        result = analyze([p], config={"min_real_yield_pct": 4.0})
        self.assertNotIn("BELOW_MIN_REAL_YIELD", result["protocols"][0]["flags"])

    def test_custom_min_real_yield_flag_triggered(self):
        p = _proto(real_revenue_apy_pct=3.9)
        result = analyze([p], config={"min_real_yield_pct": 4.0})
        self.assertIn("BELOW_MIN_REAL_YIELD", result["protocols"][0]["flags"])

    def test_none_config_uses_defaults(self):
        p = _proto(real_revenue_apy_pct=2.5)
        result = analyze([p], config=None)
        self.assertIn("BELOW_MIN_REAL_YIELD", result["protocols"][0]["flags"])


# ---------------------------------------------------------------------------
# 20. Timestamp is recent
# ---------------------------------------------------------------------------

class TestTimestamp(unittest.TestCase):
    def test_timestamp_is_recent(self):
        before = time.time()
        result = analyze([_proto()])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)


# ---------------------------------------------------------------------------
# 21. Revenue yield calculation
# ---------------------------------------------------------------------------

class TestRevenueYieldCalculation(unittest.TestCase):
    def test_correct_annualization(self):
        # 500_000 * 12 / 50_000_000 * 100 = 12.0%
        p = _proto(protocol_revenue_30d_usd=500_000, total_tvl_usd=50_000_000)
        result = analyze([p])
        self.assertAlmostEqual(result["protocols"][0]["revenue_yield_pct"], 12.0)

    def test_zero_revenue(self):
        p = _proto(protocol_revenue_30d_usd=0.0, total_tvl_usd=50_000_000)
        result = analyze([p])
        self.assertAlmostEqual(result["protocols"][0]["revenue_yield_pct"], 0.0)


# ---------------------------------------------------------------------------
# 22. Boundary real_yield_ratio at 70 (GENUINE boundary)
# ---------------------------------------------------------------------------

class TestBoundaryConditions(unittest.TestCase):
    def test_exactly_70_is_genuine(self):
        # 7/10 * 100 = 70 → GENUINE
        p = _proto(claimed_apy_pct=10.0, real_revenue_apy_pct=7.0)
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["yield_authenticity"], "GENUINE")

    def test_just_below_70_is_mixed(self):
        # 6.9/10 * 100 = 69 → MIXED
        p = _proto(claimed_apy_pct=10.0, real_revenue_apy_pct=6.9)
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["yield_authenticity"], "MIXED")

    def test_exactly_40_is_mixed(self):
        p = _proto(claimed_apy_pct=10.0, real_revenue_apy_pct=4.0)
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["yield_authenticity"], "MIXED")

    def test_just_below_40_is_emission_driven(self):
        p = _proto(claimed_apy_pct=10.0, real_revenue_apy_pct=3.9)
        result = analyze([p])
        self.assertEqual(result["protocols"][0]["yield_authenticity"], "EMISSION_DRIVEN")


# ---------------------------------------------------------------------------
# 23. Genuine count / unsustainable count across multiple
# ---------------------------------------------------------------------------

class TestCountsMultiple(unittest.TestCase):
    def test_counts(self):
        protos = [
            _proto(name="G1", claimed_apy_pct=10.0, real_revenue_apy_pct=8.0),   # GENUINE
            _proto(name="G2", claimed_apy_pct=10.0, real_revenue_apy_pct=7.5),   # GENUINE
            _proto(name="M1", claimed_apy_pct=10.0, real_revenue_apy_pct=5.0),   # MIXED
            _proto(name="U1", claimed_apy_pct=100.0, real_revenue_apy_pct=1.0),  # UNSUSTAINABLE
        ]
        result = analyze(protos)
        self.assertEqual(result["genuine_count"], 2)
        self.assertEqual(result["unsustainable_count"], 1)


# ---------------------------------------------------------------------------
# 24. Default constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_ring_buffer_cap_is_100(self):
        self.assertEqual(_RING_BUFFER_CAP, 100)

    def test_default_min_real_yield(self):
        self.assertEqual(_DEFAULT_MIN_REAL_YIELD, 3.0)


if __name__ == "__main__":
    unittest.main()
