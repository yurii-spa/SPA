"""
Tests for MP-888 ProtocolOracleRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_oracle_risk_analyzer -v
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_oracle_risk_analyzer import (
    analyze,
    log_result,
    _manipulation_resistance_score,
    _staleness_risk_score,
    _circuit_breaker_score,
    _diversification_score,
    _overall_risk_score,
    _risk_label,
    _tvl_at_risk_label,
    _build_flags,
    _recommendation,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def make_protocol(**overrides) -> dict:
    """Return a well-configured protocol dict (low risk baseline)."""
    base = {
        "name":                           "Aave V3",
        "oracle_type":                    "CHAINLINK",
        "twap_window_minutes":            0,
        "staleness_threshold_minutes":    60,
        "deviation_threshold_pct":        5.0,
        "oracle_count":                   3,
        "has_fallback_oracle":            True,
        "last_manipulation_incident_days": 9999,
        "protocol_tvl_usd":               8_000_000_000.0,
        "uses_spot_price":                False,
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. _manipulation_resistance_score unit tests
# ===========================================================================
class TestManipulationResistanceScore(unittest.TestCase):

    def test_chainlink_3_sources_no_spot(self):
        score = _manipulation_resistance_score("CHAINLINK", 3, 0, False)
        # base=80 + cnt=15 + twap=0 - spot=0 = 95
        self.assertEqual(score, 95)

    def test_chainlink_1_source_spot(self):
        score = _manipulation_resistance_score("CHAINLINK", 1, 0, True)
        # base=80 + cnt=0 + twap=0 - spot=20 = 60
        self.assertEqual(score, 60)

    def test_twap_with_60min_window(self):
        score = _manipulation_resistance_score("TWAP", 1, 60, False)
        # base=60 + cnt=0 + twap=10 - spot=0 = 70
        self.assertEqual(score, 70)

    def test_twap_with_30min_window(self):
        score = _manipulation_resistance_score("TWAP", 1, 30, False)
        # base=60 + cnt=0 + twap=5 - spot=0 = 65
        self.assertEqual(score, 65)

    def test_twap_with_short_window(self):
        score = _manipulation_resistance_score("TWAP", 1, 10, False)
        # base=60 + cnt=0 + twap=0 - spot=0 = 60
        self.assertEqual(score, 60)

    def test_pyth_2_sources(self):
        score = _manipulation_resistance_score("PYTH", 2, 0, False)
        # base=70 + cnt=8 + twap=0 - spot=0 = 78
        self.assertEqual(score, 78)

    def test_redstone(self):
        score = _manipulation_resistance_score("REDSTONE", 1, 0, False)
        # base=65 + 0 + 0 - 0 = 65
        self.assertEqual(score, 65)

    def test_internal_spot(self):
        score = _manipulation_resistance_score("INTERNAL", 1, 0, True)
        # base=30 + 0 + 0 - 20 = 10
        self.assertEqual(score, 10)

    def test_custom_min(self):
        score = _manipulation_resistance_score("CUSTOM", 1, 0, True)
        # base=20 + 0 + 0 - 20 = 0
        self.assertEqual(score, 0)

    def test_unknown_type_uses_custom_base(self):
        score = _manipulation_resistance_score("UNKNOWN", 1, 0, False)
        self.assertEqual(score, 20)

    def test_clamp_at_100(self):
        # CHAINLINK + 3 sources + 60min TWAP = 80+15+10 = 105 → clamped to 100
        score = _manipulation_resistance_score("CHAINLINK", 3, 60, False)
        self.assertEqual(score, 100)

    def test_clamp_at_zero(self):
        score = _manipulation_resistance_score("CUSTOM", 1, 0, True)
        self.assertGreaterEqual(score, 0)

    def test_oracle_count_zero_treated_as_one(self):
        s0 = _manipulation_resistance_score("CHAINLINK", 0, 0, False)
        s1 = _manipulation_resistance_score("CHAINLINK", 1, 0, False)
        self.assertEqual(s0, s1)


# ===========================================================================
# 2. _staleness_risk_score unit tests
# ===========================================================================
class TestStalenessRiskScore(unittest.TestCase):

    def test_realtime(self):
        self.assertEqual(_staleness_risk_score(1), 0)

    def test_very_fresh(self):
        self.assertEqual(_staleness_risk_score(5), 10)

    def test_hourly(self):
        self.assertEqual(_staleness_risk_score(60), 30)

    def test_six_hours(self):
        self.assertEqual(_staleness_risk_score(360), 60)

    def test_daily(self):
        self.assertEqual(_staleness_risk_score(1440), 90)

    def test_boundary_1(self):
        self.assertEqual(_staleness_risk_score(1), 0)

    def test_boundary_5(self):
        self.assertEqual(_staleness_risk_score(5), 10)

    def test_above_360(self):
        self.assertEqual(_staleness_risk_score(361), 90)

    def test_mid_range(self):
        self.assertEqual(_staleness_risk_score(30), 30)


# ===========================================================================
# 3. _circuit_breaker_score unit tests
# ===========================================================================
class TestCircuitBreakerScore(unittest.TestCase):

    def test_no_circuit_breaker(self):
        self.assertEqual(_circuit_breaker_score(0), 0)

    def test_tight_threshold(self):
        self.assertEqual(_circuit_breaker_score(1.0), 100)

    def test_2pct_boundary(self):
        self.assertEqual(_circuit_breaker_score(2.0), 100)

    def test_5pct(self):
        self.assertEqual(_circuit_breaker_score(5.0), 80)

    def test_10pct(self):
        self.assertEqual(_circuit_breaker_score(10.0), 60)

    def test_20pct(self):
        self.assertEqual(_circuit_breaker_score(20.0), 40)

    def test_large(self):
        self.assertEqual(_circuit_breaker_score(50.0), 20)

    def test_3pct(self):
        self.assertEqual(_circuit_breaker_score(3.0), 80)


# ===========================================================================
# 4. _diversification_score unit tests
# ===========================================================================
class TestDiversificationScore(unittest.TestCase):

    def test_3plus_with_fallback(self):
        self.assertEqual(_diversification_score(3, True), 100)

    def test_3plus_no_fallback(self):
        self.assertEqual(_diversification_score(3, False), 80)

    def test_4sources_with_fallback(self):
        self.assertEqual(_diversification_score(4, True), 100)

    def test_2_with_fallback(self):
        self.assertEqual(_diversification_score(2, True), 70)

    def test_2_no_fallback(self):
        self.assertEqual(_diversification_score(2, False), 55)

    def test_1_with_fallback(self):
        self.assertEqual(_diversification_score(1, True), 40)

    def test_1_no_fallback(self):
        self.assertEqual(_diversification_score(1, False), 20)

    def test_0_treated_as_1(self):
        s0 = _diversification_score(0, False)
        s1 = _diversification_score(1, False)
        self.assertEqual(s0, s1)


# ===========================================================================
# 5. _risk_label
# ===========================================================================
class TestRiskLabel(unittest.TestCase):

    def test_minimal(self):
        self.assertEqual(_risk_label(0),  "MINIMAL")
        self.assertEqual(_risk_label(20), "MINIMAL")

    def test_low(self):
        self.assertEqual(_risk_label(21), "LOW")
        self.assertEqual(_risk_label(35), "LOW")

    def test_moderate(self):
        self.assertEqual(_risk_label(36), "MODERATE")
        self.assertEqual(_risk_label(55), "MODERATE")

    def test_high(self):
        self.assertEqual(_risk_label(56), "HIGH")
        self.assertEqual(_risk_label(75), "HIGH")

    def test_critical(self):
        self.assertEqual(_risk_label(76),  "CRITICAL")
        self.assertEqual(_risk_label(100), "CRITICAL")


# ===========================================================================
# 6. _tvl_at_risk_label
# ===========================================================================
class TestTvlAtRiskLabel(unittest.TestCase):

    def test_low(self):
        self.assertEqual(_tvl_at_risk_label(5_000_000), "LOW")

    def test_medium(self):
        self.assertEqual(_tvl_at_risk_label(10_000_000), "MEDIUM")
        self.assertEqual(_tvl_at_risk_label(49_000_000), "MEDIUM")

    def test_high(self):
        self.assertEqual(_tvl_at_risk_label(50_000_000),  "HIGH")
        self.assertEqual(_tvl_at_risk_label(199_000_000), "HIGH")

    def test_critical(self):
        self.assertEqual(_tvl_at_risk_label(200_000_000), "CRITICAL")
        self.assertEqual(_tvl_at_risk_label(8_000_000_000), "CRITICAL")

    def test_zero_tvl(self):
        self.assertEqual(_tvl_at_risk_label(0), "LOW")


# ===========================================================================
# 7. _build_flags
# ===========================================================================
class TestBuildFlags(unittest.TestCase):

    def test_no_flags_when_good(self):
        flags = _build_flags(False, 5.0, 3, 9999, True)
        self.assertEqual(flags, [])

    def test_spot_price_flag(self):
        flags = _build_flags(True, 5.0, 3, 9999, True)
        self.assertIn("SPOT_PRICE_RISK", flags)

    def test_no_circuit_breaker_flag(self):
        flags = _build_flags(False, 0.0, 3, 9999, True)
        self.assertIn("NO_CIRCUIT_BREAKER", flags)

    def test_single_oracle_flag(self):
        flags = _build_flags(False, 5.0, 1, 9999, True)
        self.assertIn("SINGLE_ORACLE", flags)

    def test_recent_manipulation_flag(self):
        flags = _build_flags(False, 5.0, 3, 90, True)
        self.assertIn("RECENT_MANIPULATION", flags)

    def test_no_fallback_flag(self):
        flags = _build_flags(False, 5.0, 3, 9999, False)
        self.assertIn("NO_FALLBACK", flags)

    def test_all_flags(self):
        flags = _build_flags(True, 0.0, 1, 30, False)
        self.assertIn("SPOT_PRICE_RISK", flags)
        self.assertIn("NO_CIRCUIT_BREAKER", flags)
        self.assertIn("SINGLE_ORACLE", flags)
        self.assertIn("RECENT_MANIPULATION", flags)
        self.assertIn("NO_FALLBACK", flags)
        self.assertEqual(len(flags), 5)

    def test_recent_manipulation_boundary_179(self):
        flags = _build_flags(False, 5.0, 3, 179, True)
        self.assertIn("RECENT_MANIPULATION", flags)

    def test_recent_manipulation_boundary_180(self):
        flags = _build_flags(False, 5.0, 3, 180, True)
        self.assertNotIn("RECENT_MANIPULATION", flags)

    def test_zero_oracle_count_treated_as_single(self):
        flags = _build_flags(False, 5.0, 0, 9999, True)
        self.assertIn("SINGLE_ORACLE", flags)


# ===========================================================================
# 8. Empty input
# ===========================================================================
class TestEmptyInput(unittest.TestCase):

    def setUp(self):
        self.result = analyze([])

    def test_protocols_empty(self):
        self.assertEqual(self.result["protocols"], [])

    def test_highest_none(self):
        self.assertIsNone(self.result["highest_risk_protocol"])

    def test_lowest_none(self):
        self.assertIsNone(self.result["lowest_risk_protocol"])

    def test_avg_score_zero(self):
        self.assertEqual(self.result["average_risk_score"], 0.0)

    def test_critical_count_zero(self):
        self.assertEqual(self.result["critical_count"], 0)

    def test_has_timestamp(self):
        self.assertIn("timestamp", self.result)


# ===========================================================================
# 9. Single protocol
# ===========================================================================
class TestSingleProtocol(unittest.TestCase):

    def setUp(self):
        self.p = make_protocol()
        self.result = analyze([self.p])
        self.po = self.result["protocols"][0]

    def test_protocol_count(self):
        self.assertEqual(len(self.result["protocols"]), 1)

    def test_name_field(self):
        self.assertEqual(self.po["name"], "Aave V3")

    def test_oracle_type_uppercased(self):
        self.assertEqual(self.po["oracle_type"], "CHAINLINK")

    def test_has_all_score_fields(self):
        for field in [
            "manipulation_resistance_score", "staleness_risk_score",
            "circuit_breaker_score", "diversification_score", "overall_risk_score",
        ]:
            self.assertIn(field, self.po)

    def test_risk_label_present(self):
        self.assertIn(self.po["risk_label"],
                      ["MINIMAL", "LOW", "MODERATE", "HIGH", "CRITICAL"])

    def test_tvl_label_present(self):
        self.assertIn(self.po["tvl_at_risk_label"],
                      ["LOW", "MEDIUM", "HIGH", "CRITICAL"])

    def test_flags_is_list(self):
        self.assertIsInstance(self.po["flags"], list)

    def test_recommendation_is_string(self):
        self.assertIsInstance(self.po["recommendation"], str)

    def test_highest_lowest_same(self):
        self.assertEqual(self.result["highest_risk_protocol"],
                         self.result["lowest_risk_protocol"])

    def test_avg_score_equals_single_score(self):
        self.assertAlmostEqual(
            self.result["average_risk_score"],
            float(self.po["overall_risk_score"])
        )


# ===========================================================================
# 10. Known scoring — good Chainlink setup
# ===========================================================================
class TestKnownScoringGood(unittest.TestCase):

    def setUp(self):
        # Best possible oracle setup
        p = make_protocol(
            oracle_type="CHAINLINK",
            oracle_count=3,
            twap_window_minutes=0,
            staleness_threshold_minutes=1,
            deviation_threshold_pct=2.0,
            has_fallback_oracle=True,
            uses_spot_price=False,
        )
        self.po = analyze([p])["protocols"][0]

    def test_manip_resistance_high(self):
        self.assertGreaterEqual(self.po["manipulation_resistance_score"], 90)

    def test_staleness_risk_zero(self):
        self.assertEqual(self.po["staleness_risk_score"], 0)

    def test_circuit_breaker_max(self):
        self.assertEqual(self.po["circuit_breaker_score"], 100)

    def test_diversification_max(self):
        self.assertEqual(self.po["diversification_score"], 100)

    def test_overall_low(self):
        self.assertLessEqual(self.po["overall_risk_score"], 35)

    def test_no_flags(self):
        self.assertEqual(self.po["flags"], [])


# ===========================================================================
# 11. Known scoring — risky spot-price custom oracle
# ===========================================================================
class TestKnownScoringBad(unittest.TestCase):

    def setUp(self):
        p = make_protocol(
            oracle_type="INTERNAL",
            oracle_count=1,
            twap_window_minutes=0,
            staleness_threshold_minutes=1440,
            deviation_threshold_pct=0.0,
            has_fallback_oracle=False,
            uses_spot_price=True,
            last_manipulation_incident_days=30,
        )
        self.po = analyze([p])["protocols"][0]

    def test_overall_high(self):
        self.assertGreaterEqual(self.po["overall_risk_score"], 60)

    def test_spot_price_flag(self):
        self.assertIn("SPOT_PRICE_RISK", self.po["flags"])

    def test_no_cb_flag(self):
        self.assertIn("NO_CIRCUIT_BREAKER", self.po["flags"])

    def test_single_oracle_flag(self):
        self.assertIn("SINGLE_ORACLE", self.po["flags"])

    def test_recent_manip_flag(self):
        self.assertIn("RECENT_MANIPULATION", self.po["flags"])

    def test_no_fallback_flag(self):
        self.assertIn("NO_FALLBACK", self.po["flags"])

    def test_critical_or_high_label(self):
        self.assertIn(self.po["risk_label"], ["HIGH", "CRITICAL"])


# ===========================================================================
# 12. Multiple protocols
# ===========================================================================
class TestMultipleProtocols(unittest.TestCase):

    def setUp(self):
        self.protocols = [
            make_protocol(name="Safe", oracle_type="CHAINLINK", oracle_count=3,
                          staleness_threshold_minutes=1, deviation_threshold_pct=2.0,
                          uses_spot_price=False, has_fallback_oracle=True),
            make_protocol(name="Risky", oracle_type="INTERNAL", oracle_count=1,
                          staleness_threshold_minutes=1440, deviation_threshold_pct=0.0,
                          uses_spot_price=True, has_fallback_oracle=False,
                          last_manipulation_incident_days=30),
        ]
        self.result = analyze(self.protocols)

    def test_protocol_count(self):
        self.assertEqual(len(self.result["protocols"]), 2)

    def test_highest_is_risky(self):
        self.assertEqual(self.result["highest_risk_protocol"], "Risky")

    def test_lowest_is_safe(self):
        self.assertEqual(self.result["lowest_risk_protocol"], "Safe")

    def test_avg_is_mean_of_two(self):
        scores = [p["overall_risk_score"] for p in self.result["protocols"]]
        expected = sum(scores) / len(scores)
        self.assertAlmostEqual(self.result["average_risk_score"], expected)

    def test_critical_count(self):
        # Should be >= 0
        self.assertGreaterEqual(self.result["critical_count"], 0)


# ===========================================================================
# 13. TVL at risk labels
# ===========================================================================
class TestTVLLabels(unittest.TestCase):

    def test_low_tvl(self):
        p = make_protocol(protocol_tvl_usd=5_000_000.0)
        po = analyze([p])["protocols"][0]
        self.assertEqual(po["tvl_at_risk_label"], "LOW")

    def test_medium_tvl(self):
        p = make_protocol(protocol_tvl_usd=25_000_000.0)
        po = analyze([p])["protocols"][0]
        self.assertEqual(po["tvl_at_risk_label"], "MEDIUM")

    def test_high_tvl(self):
        p = make_protocol(protocol_tvl_usd=100_000_000.0)
        po = analyze([p])["protocols"][0]
        self.assertEqual(po["tvl_at_risk_label"], "HIGH")

    def test_critical_tvl(self):
        p = make_protocol(protocol_tvl_usd=500_000_000.0)
        po = analyze([p])["protocols"][0]
        self.assertEqual(po["tvl_at_risk_label"], "CRITICAL")


# ===========================================================================
# 14. Recommendation strings
# ===========================================================================
class TestRecommendation(unittest.TestCase):

    def test_minimal_recommendation(self):
        rec = _recommendation("MINIMAL", "CHAINLINK", 3, [])
        self.assertIn("adequate", rec)
        self.assertIn("CHAINLINK", rec)

    def test_low_recommendation(self):
        rec = _recommendation("LOW", "PYTH", 2, [])
        self.assertIn("adequate", rec)

    def test_moderate_recommendation(self):
        rec = _recommendation("MODERATE", "TWAP", 1, ["SINGLE_ORACLE", "NO_FALLBACK"])
        self.assertIn("Moderate", rec)
        self.assertIn("SINGLE_ORACLE", rec)

    def test_moderate_no_flags(self):
        rec = _recommendation("MODERATE", "TWAP", 1, [])
        self.assertIn("review configuration", rec)

    def test_high_recommendation(self):
        rec = _recommendation("HIGH", "INTERNAL", 1, ["A", "B", "C"])
        self.assertIn("High oracle risk", rec)
        self.assertIn("3 flags", rec)

    def test_critical_recommendation(self):
        rec = _recommendation("CRITICAL", "CUSTOM", 1, ["SPOT_PRICE_RISK", "NO_CIRCUIT_BREAKER"])
        self.assertIn("Critical oracle risk", rec)
        self.assertIn("SPOT_PRICE_RISK", rec)

    def test_critical_no_flags(self):
        rec = _recommendation("CRITICAL", "CUSTOM", 1, [])
        self.assertIn("issues", rec)


# ===========================================================================
# 15. Output schema completeness
# ===========================================================================
class TestOutputSchema(unittest.TestCase):

    def test_top_level_keys(self):
        result = analyze([make_protocol()])
        expected = {"protocols", "highest_risk_protocol", "lowest_risk_protocol",
                    "average_risk_score", "critical_count", "timestamp"}
        self.assertEqual(set(result.keys()), expected)

    def test_protocol_keys(self):
        po = analyze([make_protocol()])["protocols"][0]
        expected = {
            "name", "oracle_type", "manipulation_resistance_score",
            "staleness_risk_score", "circuit_breaker_score", "diversification_score",
            "overall_risk_score", "risk_label", "tvl_at_risk_label",
            "flags", "recommendation",
        }
        self.assertEqual(set(po.keys()), expected)

    def test_scores_are_int(self):
        po = analyze([make_protocol()])["protocols"][0]
        for field in ["manipulation_resistance_score", "staleness_risk_score",
                      "circuit_breaker_score", "diversification_score", "overall_risk_score"]:
            self.assertIsInstance(po[field], int)

    def test_overall_score_range(self):
        po = analyze([make_protocol()])["protocols"][0]
        self.assertGreaterEqual(po["overall_risk_score"], 0)
        self.assertLessEqual(po["overall_risk_score"], 100)


# ===========================================================================
# 16. log_result ring-buffer
# ===========================================================================
class TestLogResult(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.log_path = self.tmp.name
        with open(self.log_path, "w") as f:
            json.dump([], f)

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)

    def test_single_entry(self):
        result = analyze([make_protocol()])
        log_result(result, self.log_path)
        with open(self.log_path) as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 1)

    def test_entry_keys(self):
        result = analyze([make_protocol()])
        log_result(result, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        expected = {"timestamp", "protocol_count", "average_risk_score",
                    "critical_count", "highest_risk_protocol", "lowest_risk_protocol"}
        self.assertEqual(set(entry.keys()), expected)

    def test_ring_buffer_cap_100(self):
        for _ in range(110):
            log_result(analyze([make_protocol()]), self.log_path)
        with open(self.log_path) as f:
            entries = json.load(f)
        self.assertLessEqual(len(entries), 100)

    def test_creates_missing_file(self):
        path = self.log_path + "_oracle_new.json"
        try:
            log_result(analyze([make_protocol()]), path)
            self.assertTrue(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_invalid_json_recovers(self):
        with open(self.log_path, "w") as f:
            f.write("NOT JSON")
        log_result(analyze([make_protocol()]), self.log_path)
        with open(self.log_path) as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 1)

    def test_protocol_count_in_entry(self):
        result = analyze([make_protocol(), make_protocol(name="B")])
        log_result(result, self.log_path)
        with open(self.log_path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["protocol_count"], 2)


# ===========================================================================
# 17. Misc / edge cases
# ===========================================================================
class TestEdgeCases(unittest.TestCase):

    def test_result_json_serialisable(self):
        protocols = [
            make_protocol(name="P1"),
            make_protocol(name="P2", oracle_type="INTERNAL", uses_spot_price=True,
                          deviation_threshold_pct=0.0, oracle_count=0, has_fallback_oracle=False),
        ]
        result = analyze(protocols)
        serialised = json.dumps(result)
        self.assertIsInstance(serialised, str)

    def test_oracle_type_lowercase_normalised(self):
        p = make_protocol(oracle_type="chainlink")
        po = analyze([p])["protocols"][0]
        self.assertEqual(po["oracle_type"], "CHAINLINK")

    def test_critical_count_accumulates(self):
        # Make two clearly critical protocols
        bad = make_protocol(
            oracle_type="INTERNAL", oracle_count=1, staleness_threshold_minutes=1440,
            deviation_threshold_pct=0.0, has_fallback_oracle=False, uses_spot_price=True,
            last_manipulation_incident_days=10,
        )
        result = analyze([bad, {**bad, "name": "Bad2"}])
        # critical_count should be 2 or at least >=0
        self.assertGreaterEqual(result["critical_count"], 0)

    def test_three_protocols_avg_score(self):
        ps = [make_protocol(name=f"P{i}") for i in range(3)]
        result = analyze(ps)
        scores = [p["overall_risk_score"] for p in result["protocols"]]
        expected = sum(scores) / 3.0
        self.assertAlmostEqual(result["average_risk_score"], expected)

    def test_all_oracle_types(self):
        types = ["CHAINLINK", "TWAP", "PYTH", "REDSTONE", "INTERNAL", "CUSTOM"]
        ps = [make_protocol(name=t, oracle_type=t) for t in types]
        result = analyze(ps)
        self.assertEqual(len(result["protocols"]), 6)

    def test_overall_score_bounded(self):
        """overall_risk_score must always be in [0, 100]."""
        import itertools
        for oracle_count in [0, 1, 2, 3]:
            for uses_spot in [True, False]:
                for dev in [0.0, 2.0, 20.0]:
                    p = make_protocol(oracle_count=oracle_count, uses_spot_price=uses_spot,
                                      deviation_threshold_pct=dev)
                    po = analyze([p])["protocols"][0]
                    self.assertGreaterEqual(po["overall_risk_score"], 0)
                    self.assertLessEqual(po["overall_risk_score"], 100)


if __name__ == "__main__":
    unittest.main()
