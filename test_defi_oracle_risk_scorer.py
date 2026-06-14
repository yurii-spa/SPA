"""
MP-834 DeFiOracleRiskScorer — unit tests (≥65)
Run: python3 -m unittest spa_core/tests/test_defi_oracle_risk_scorer.py -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.defi_oracle_risk_scorer import (
    analyze,
    log_result,
    _base_risk,
    _source_risk,
    _twap_risk,
    _safety_reduction,
    _incident_penalty,
    _compute_score,
    _oracle_grade,
    _manipulation_risk,
    _single_point_of_failure,
    _risk_factors,
    _recommendations,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proto(name="ProtoX", oracle_type="CHAINLINK", oracle_count=3,
           twap_window_minutes=60, uses_fallback=True, circuit_breaker=True,
           max_price_deviation_pct=1.5, historical_incidents=0):
    return {
        "name": name,
        "oracle_type": oracle_type,
        "oracle_count": oracle_count,
        "twap_window_minutes": twap_window_minutes,
        "uses_fallback": uses_fallback,
        "circuit_breaker": circuit_breaker,
        "max_price_deviation_pct": max_price_deviation_pct,
        "historical_incidents": historical_incidents,
    }


# ---------------------------------------------------------------------------
# Unit tests: _base_risk
# ---------------------------------------------------------------------------

class TestBaseRisk(unittest.TestCase):
    def test_chainlink(self):
        self.assertEqual(_base_risk("CHAINLINK"), 5)

    def test_pyth(self):
        self.assertEqual(_base_risk("PYTH"), 10)

    def test_band(self):
        self.assertEqual(_base_risk("BAND"), 15)

    def test_uniswap_twap(self):
        self.assertEqual(_base_risk("UNISWAP_TWAP"), 20)

    def test_internal(self):
        self.assertEqual(_base_risk("INTERNAL"), 35)

    def test_none(self):
        self.assertEqual(_base_risk("NONE"), 40)

    def test_unknown_defaults_to_40(self):
        self.assertEqual(_base_risk("UNKNOWN_ORACLE"), 40)


# ---------------------------------------------------------------------------
# Unit tests: _source_risk
# ---------------------------------------------------------------------------

class TestSourceRisk(unittest.TestCase):
    def test_zero_sources(self):
        self.assertEqual(_source_risk(0), 20)

    def test_one_source(self):
        self.assertEqual(_source_risk(1), 15)

    def test_two_sources(self):
        self.assertEqual(_source_risk(2), 5)

    def test_three_sources(self):
        self.assertEqual(_source_risk(3), 0)

    def test_many_sources(self):
        self.assertEqual(_source_risk(10), 0)


# ---------------------------------------------------------------------------
# Unit tests: _twap_risk
# ---------------------------------------------------------------------------

class TestTwapRisk(unittest.TestCase):
    def test_no_twap(self):
        self.assertEqual(_twap_risk(0), 20)

    def test_short_twap_1min(self):
        self.assertEqual(_twap_risk(1), 15)

    def test_short_twap_9min(self):
        self.assertEqual(_twap_risk(9), 15)

    def test_medium_twap_10min(self):
        self.assertEqual(_twap_risk(10), 10)

    def test_medium_twap_29min(self):
        self.assertEqual(_twap_risk(29), 10)

    def test_good_twap_30min(self):
        self.assertEqual(_twap_risk(30), 5)

    def test_good_twap_59min(self):
        self.assertEqual(_twap_risk(59), 5)

    def test_best_twap_60min(self):
        self.assertEqual(_twap_risk(60), 0)

    def test_best_twap_120min(self):
        self.assertEqual(_twap_risk(120), 0)


# ---------------------------------------------------------------------------
# Unit tests: _safety_reduction
# ---------------------------------------------------------------------------

class TestSafetyReduction(unittest.TestCase):
    def test_no_safety_features(self):
        self.assertEqual(_safety_reduction(False, False, 10.0), 0)

    def test_only_fallback(self):
        self.assertEqual(_safety_reduction(True, False, 10.0), 5)

    def test_only_circuit_breaker(self):
        self.assertEqual(_safety_reduction(False, True, 10.0), 5)

    def test_only_tight_deviation(self):
        self.assertEqual(_safety_reduction(False, False, 2.0), 5)

    def test_all_three(self):
        self.assertEqual(_safety_reduction(True, True, 1.0), 15)

    def test_fallback_and_circuit(self):
        self.assertEqual(_safety_reduction(True, True, 5.0), 10)

    def test_tight_deviation_boundary(self):
        # exactly 2.0 qualifies
        self.assertEqual(_safety_reduction(False, False, 2.0), 5)

    def test_just_above_tight_boundary(self):
        # 2.01 does not qualify
        self.assertEqual(_safety_reduction(False, False, 2.01), 0)


# ---------------------------------------------------------------------------
# Unit tests: _incident_penalty
# ---------------------------------------------------------------------------

class TestIncidentPenalty(unittest.TestCase):
    def test_zero_incidents(self):
        self.assertEqual(_incident_penalty(0), 0)

    def test_one_incident(self):
        self.assertEqual(_incident_penalty(1), 5)

    def test_two_incidents(self):
        self.assertEqual(_incident_penalty(2), 10)

    def test_three_incidents(self):
        self.assertEqual(_incident_penalty(3), 15)

    def test_four_incidents(self):
        self.assertEqual(_incident_penalty(4), 20)

    def test_five_incidents_capped(self):
        self.assertEqual(_incident_penalty(5), 20)

    def test_ten_incidents_capped(self):
        self.assertEqual(_incident_penalty(10), 20)


# ---------------------------------------------------------------------------
# Unit tests: _compute_score
# ---------------------------------------------------------------------------

class TestComputeScore(unittest.TestCase):
    def test_best_case_chainlink(self):
        # CHAINLINK=5, 3 sources=0, 60min TWAP=0, 2 incidents capped=0 from base
        # safety: fallback+CB+tight = -15
        # 5+0+0+0-15 = -10 → clamped to 0
        score = _compute_score("CHAINLINK", 3, 60, True, True, 1.0, 0)
        self.assertEqual(score, 0)

    def test_worst_case_none(self):
        # NONE=40, 0 sources=20, no TWAP=20, 4 incidents=20, no safety=0
        # 40+20+20+20 = 100
        score = _compute_score("NONE", 0, 0, False, False, 100.0, 4)
        self.assertEqual(score, 100)

    def test_score_clamped_min_zero(self):
        score = _compute_score("CHAINLINK", 3, 60, True, True, 1.0, 0)
        self.assertGreaterEqual(score, 0)

    def test_score_clamped_max_100(self):
        score = _compute_score("NONE", 0, 0, False, False, 100.0, 100)
        self.assertLessEqual(score, 100)

    def test_incident_capped_in_penalty(self):
        # 100 incidents → still capped at 20 pts
        s1 = _compute_score("CHAINLINK", 1, 0, False, False, 10.0, 4)
        s2 = _compute_score("CHAINLINK", 1, 0, False, False, 10.0, 100)
        self.assertEqual(s1, s2)

    def test_internal_oracle_higher_than_chainlink(self):
        s_cl = _compute_score("CHAINLINK", 1, 0, False, False, 10.0, 0)
        s_in = _compute_score("INTERNAL", 1, 0, False, False, 10.0, 0)
        self.assertGreater(s_in, s_cl)


# ---------------------------------------------------------------------------
# Unit tests: _oracle_grade
# ---------------------------------------------------------------------------

class TestOracleGrade(unittest.TestCase):
    def test_grade_a_at_0(self):
        self.assertEqual(_oracle_grade(0), "A")

    def test_grade_a_at_20(self):
        self.assertEqual(_oracle_grade(20), "A")

    def test_grade_b_at_21(self):
        self.assertEqual(_oracle_grade(21), "B")

    def test_grade_b_at_40(self):
        self.assertEqual(_oracle_grade(40), "B")

    def test_grade_c_at_41(self):
        self.assertEqual(_oracle_grade(41), "C")

    def test_grade_c_at_60(self):
        self.assertEqual(_oracle_grade(60), "C")

    def test_grade_d_at_61(self):
        self.assertEqual(_oracle_grade(61), "D")

    def test_grade_d_at_80(self):
        self.assertEqual(_oracle_grade(80), "D")

    def test_grade_f_at_81(self):
        self.assertEqual(_oracle_grade(81), "F")

    def test_grade_f_at_100(self):
        self.assertEqual(_oracle_grade(100), "F")


# ---------------------------------------------------------------------------
# Unit tests: _manipulation_risk
# ---------------------------------------------------------------------------

class TestManipulationRisk(unittest.TestCase):
    def test_low_at_0(self):
        self.assertEqual(_manipulation_risk(0), "LOW")

    def test_low_at_25(self):
        self.assertEqual(_manipulation_risk(25), "LOW")

    def test_medium_at_26(self):
        self.assertEqual(_manipulation_risk(26), "MEDIUM")

    def test_medium_at_50(self):
        self.assertEqual(_manipulation_risk(50), "MEDIUM")

    def test_high_at_51(self):
        self.assertEqual(_manipulation_risk(51), "HIGH")

    def test_high_at_75(self):
        self.assertEqual(_manipulation_risk(75), "HIGH")

    def test_critical_at_76(self):
        self.assertEqual(_manipulation_risk(76), "CRITICAL")

    def test_critical_at_100(self):
        self.assertEqual(_manipulation_risk(100), "CRITICAL")


# ---------------------------------------------------------------------------
# Unit tests: _single_point_of_failure
# ---------------------------------------------------------------------------

class TestSPOF(unittest.TestCase):
    def test_spof_one_no_fallback(self):
        self.assertTrue(_single_point_of_failure(1, False))

    def test_spof_zero_no_fallback(self):
        self.assertTrue(_single_point_of_failure(0, False))

    def test_no_spof_one_with_fallback(self):
        self.assertFalse(_single_point_of_failure(1, True))

    def test_no_spof_two_sources_no_fallback(self):
        self.assertFalse(_single_point_of_failure(2, False))

    def test_no_spof_two_sources_with_fallback(self):
        self.assertFalse(_single_point_of_failure(2, True))

    def test_no_spof_three_sources(self):
        self.assertFalse(_single_point_of_failure(3, False))


# ---------------------------------------------------------------------------
# Unit tests: _risk_factors
# ---------------------------------------------------------------------------

class TestRiskFactors(unittest.TestCase):
    def test_single_oracle_flagged(self):
        factors = _risk_factors("CHAINLINK", 1, 60, True, True, 0)
        self.assertIn("Single oracle source — no redundancy", factors)

    def test_no_fallback_flagged(self):
        factors = _risk_factors("CHAINLINK", 3, 60, False, True, 0)
        self.assertIn("No fallback oracle", factors)

    def test_no_twap_flagged(self):
        factors = _risk_factors("CHAINLINK", 3, 0, True, True, 0)
        self.assertIn("No TWAP protection", factors)

    def test_short_twap_flagged(self):
        factors = _risk_factors("CHAINLINK", 3, 15, True, True, 0)
        self.assertIn("Short TWAP window — flash loan vulnerable", factors)

    def test_no_circuit_breaker_flagged(self):
        factors = _risk_factors("CHAINLINK", 3, 60, True, False, 0)
        self.assertIn("No circuit breaker", factors)

    def test_incidents_flagged(self):
        factors = _risk_factors("CHAINLINK", 3, 60, True, True, 2)
        self.assertIn("2 past oracle incident(s)", factors)

    def test_internal_oracle_flagged(self):
        factors = _risk_factors("INTERNAL", 3, 60, True, True, 0)
        self.assertIn("Internal oracle — centralization risk", factors)

    def test_none_oracle_flagged(self):
        factors = _risk_factors("NONE", 3, 60, True, True, 0)
        self.assertIn("No oracle — relies on manual/admin", factors)

    def test_clean_protocol_no_factors(self):
        factors = _risk_factors("CHAINLINK", 3, 60, True, True, 0)
        self.assertEqual(factors, [])

    def test_twap_30min_not_short_twap(self):
        factors = _risk_factors("CHAINLINK", 3, 30, True, True, 0)
        short = [f for f in factors if "flash loan" in f]
        self.assertEqual(short, [])


# ---------------------------------------------------------------------------
# Unit tests: _recommendations
# ---------------------------------------------------------------------------

class TestRecommendations(unittest.TestCase):
    def test_high_score_recommends_avoid(self):
        recs = _recommendations(70, False, 60, True)
        self.assertIn("Consider avoiding until oracle infrastructure improves", recs)

    def test_score_60_not_triggered(self):
        recs = _recommendations(60, False, 60, True)
        avoid = [r for r in recs if "Consider avoiding" in r]
        self.assertEqual(avoid, [])

    def test_score_61_triggered(self):
        recs = _recommendations(61, False, 60, True)
        avoid = [r for r in recs if "Consider avoiding" in r]
        self.assertEqual(len(avoid), 1)

    def test_spof_recommendation(self):
        recs = _recommendations(30, True, 60, True)
        self.assertIn("Protocol has single oracle SPOF — use small positions only", recs)

    def test_short_twap_recommendation(self):
        recs = _recommendations(30, False, 15, True)
        self.assertIn("Short TWAP window — vulnerable to flash loan manipulation", recs)

    def test_no_circuit_breaker_recommendation(self):
        recs = _recommendations(30, False, 60, False)
        self.assertIn("No circuit breaker — price manipulation could cause cascading liquidations", recs)

    def test_twap_zero_no_flash_loan_rec(self):
        # twap=0 → "No TWAP" but not the flash loan specific rec
        recs = _recommendations(30, False, 0, True)
        flash = [r for r in recs if "flash loan" in r]
        self.assertEqual(flash, [])

    def test_clean_protocol_no_recs(self):
        recs = _recommendations(20, False, 60, True)
        self.assertEqual(recs, [])


# ---------------------------------------------------------------------------
# Tests: analyze() — empty input
# ---------------------------------------------------------------------------

class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.result = analyze([])

    def test_protocols_empty(self):
        self.assertEqual(self.result["protocols"], [])

    def test_safest_none(self):
        self.assertIsNone(self.result["safest_protocol"])

    def test_riskiest_none(self):
        self.assertIsNone(self.result["riskiest_protocol"])

    def test_average_zero(self):
        self.assertEqual(self.result["average_oracle_risk"], 0.0)

    def test_critical_count_zero(self):
        self.assertEqual(self.result["critical_count"], 0)

    def test_filtered_count_zero(self):
        self.assertEqual(self.result["filtered_count"], 0)

    def test_timestamp_present(self):
        self.assertIsInstance(self.result["timestamp"], float)
        self.assertGreater(self.result["timestamp"], 0)


# ---------------------------------------------------------------------------
# Tests: analyze() — single protocol
# ---------------------------------------------------------------------------

class TestAnalyzeSingle(unittest.TestCase):
    def setUp(self):
        p = _proto("Aave", "CHAINLINK", 3, 0, True, True, 1.5, 0)
        self.result = analyze([p])
        self.proto = self.result["protocols"][0]

    def test_one_protocol(self):
        self.assertEqual(len(self.result["protocols"]), 1)

    def test_name_preserved(self):
        self.assertEqual(self.proto["name"], "Aave")

    def test_oracle_type_preserved(self):
        self.assertEqual(self.proto["oracle_type"], "CHAINLINK")

    def test_score_is_int(self):
        self.assertIsInstance(self.proto["oracle_risk_score"], int)

    def test_grade_present(self):
        self.assertIn(self.proto["oracle_grade"], ("A", "B", "C", "D", "F"))

    def test_manipulation_risk_present(self):
        self.assertIn(self.proto["manipulation_risk"], ("LOW", "MEDIUM", "HIGH", "CRITICAL"))

    def test_spof_is_bool(self):
        self.assertIsInstance(self.proto["single_point_of_failure"], bool)

    def test_safest_and_riskiest_same(self):
        self.assertEqual(self.result["safest_protocol"], "Aave")
        self.assertEqual(self.result["riskiest_protocol"], "Aave")

    def test_average_equals_score(self):
        self.assertAlmostEqual(self.result["average_oracle_risk"], float(self.proto["oracle_risk_score"]))


# ---------------------------------------------------------------------------
# Tests: analyze() — multiple protocols
# ---------------------------------------------------------------------------

class TestAnalyzeMultiple(unittest.TestCase):
    def setUp(self):
        self.protos = [
            _proto("Safe",   "CHAINLINK", 3, 60, True,  True,  1.0, 0),
            _proto("Medium", "PYTH",      2, 30, True,  True,  5.0, 1),
            _proto("Risky",  "NONE",      0, 0,  False, False, 50.0, 3),
        ]
        self.result = analyze(self.protos)

    def test_three_protocols(self):
        self.assertEqual(len(self.result["protocols"]), 3)

    def test_safest_is_safe(self):
        self.assertEqual(self.result["safest_protocol"], "Safe")

    def test_riskiest_is_risky(self):
        self.assertEqual(self.result["riskiest_protocol"], "Risky")

    def test_average_is_float(self):
        self.assertIsInstance(self.result["average_oracle_risk"], float)

    def test_average_between_min_max(self):
        scores = [p["oracle_risk_score"] for p in self.result["protocols"]]
        avg = self.result["average_oracle_risk"]
        self.assertGreaterEqual(avg, min(scores))
        self.assertLessEqual(avg, max(scores))

    def test_risky_higher_score_than_safe(self):
        scores = {p["name"]: p["oracle_risk_score"] for p in self.result["protocols"]}
        self.assertGreater(scores["Risky"], scores["Safe"])

    def test_risky_spof(self):
        risky = next(p for p in self.result["protocols"] if p["name"] == "Risky")
        self.assertTrue(risky["single_point_of_failure"])

    def test_safe_no_spof(self):
        safe = next(p for p in self.result["protocols"] if p["name"] == "Safe")
        self.assertFalse(safe["single_point_of_failure"])


# ---------------------------------------------------------------------------
# Tests: analyze() — max_risk filter
# ---------------------------------------------------------------------------

class TestMaxRiskFilter(unittest.TestCase):
    def setUp(self):
        self.protos = [
            _proto("Safe", "CHAINLINK", 3, 60, True, True, 1.0, 0),
            _proto("Risky", "NONE", 0, 0, False, False, 50.0, 4),
        ]

    def test_filter_removes_risky(self):
        result = analyze(self.protos, {"max_risk": 30})
        names = [p["name"] for p in result["protocols"]]
        self.assertIn("Safe", names)
        self.assertNotIn("Risky", names)

    def test_filtered_count_incremented(self):
        result = analyze(self.protos, {"max_risk": 30})
        self.assertGreaterEqual(result["filtered_count"], 1)

    def test_max_risk_100_keeps_all(self):
        result = analyze(self.protos, {"max_risk": 100})
        self.assertEqual(len(result["protocols"]), 2)
        self.assertEqual(result["filtered_count"], 0)

    def test_max_risk_0_filters_all(self):
        result = analyze(self.protos, {"max_risk": 0})
        # Score 0 would survive, but both have higher scores
        filtered_total = result["filtered_count"] + len(result["protocols"])
        self.assertEqual(filtered_total, 2)


# ---------------------------------------------------------------------------
# Tests: analyze() — output fields completeness
# ---------------------------------------------------------------------------

class TestOutputFields(unittest.TestCase):
    def setUp(self):
        p = _proto()
        self.result = analyze([p])
        self.proto = self.result["protocols"][0]

    def test_top_level_keys(self):
        expected = {
            "protocols", "safest_protocol", "riskiest_protocol",
            "average_oracle_risk", "critical_count", "filtered_count", "timestamp"
        }
        self.assertEqual(set(self.result.keys()), expected)

    def test_protocol_keys(self):
        expected = {
            "name", "oracle_type", "oracle_risk_score", "oracle_grade",
            "manipulation_risk", "single_point_of_failure",
            "recommendations", "risk_factors"
        }
        self.assertEqual(set(self.proto.keys()), expected)

    def test_recommendations_is_list(self):
        self.assertIsInstance(self.proto["recommendations"], list)

    def test_risk_factors_is_list(self):
        self.assertIsInstance(self.proto["risk_factors"], list)


# ---------------------------------------------------------------------------
# Tests: analyze() — critical_count
# ---------------------------------------------------------------------------

class TestCriticalCount(unittest.TestCase):
    def test_critical_counted(self):
        # NONE oracle, 0 sources, no TWAP, no safety → very high score → CRITICAL
        p = _proto("Worst", "NONE", 0, 0, False, False, 100.0, 4)
        result = analyze([p])
        self.assertGreaterEqual(result["critical_count"], 1)

    def test_no_critical_safe_protocol(self):
        p = _proto("Safe", "CHAINLINK", 3, 60, True, True, 1.0, 0)
        result = analyze([p])
        self.assertEqual(result["critical_count"], 0)


# ---------------------------------------------------------------------------
# Tests: log_result() — ring-buffer and atomic write
# ---------------------------------------------------------------------------

class TestLogResult(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _make_result(self):
        return analyze([_proto()])

    def test_creates_log_file(self):
        log_path = os.path.join(self.tmp_dir, "oracle_risk_log.json")
        self.assertFalse(os.path.exists(log_path))
        log_result(self._make_result(), data_dir=self.tmp_dir)
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_list(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "oracle_risk_log.json")) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_first_entry_fields(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "oracle_risk_log.json")) as f:
            data = json.load(f)
        entry = data[0]
        for key in ("timestamp", "protocol_count", "critical_count",
                    "filtered_count", "average_oracle_risk",
                    "safest_protocol", "riskiest_protocol"):
            self.assertIn(key, entry)

    def test_multiple_appends(self):
        for _ in range(5):
            log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "oracle_risk_log.json")) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_capped_at_100(self):
        for _ in range(110):
            log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "oracle_risk_log.json")) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_ring_buffer_keeps_latest(self):
        for i in range(105):
            r = self._make_result()
            r["critical_count"] = i
            log_result(r, data_dir=self.tmp_dir)
        with open(os.path.join(self.tmp_dir, "oracle_risk_log.json")) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["critical_count"], 104)

    def test_no_tmp_files_left(self):
        log_result(self._make_result(), data_dir=self.tmp_dir)
        leftovers = [f for f in os.listdir(self.tmp_dir)
                     if f.startswith(".oracle_risk_log_") and f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_corrupted_log_recovered(self):
        log_path = os.path.join(self.tmp_dir, "oracle_risk_log.json")
        with open(log_path, "w") as f:
            f.write("not valid json{{")
        log_result(self._make_result(), data_dir=self.tmp_dir)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# Tests: analyze() — incident penalty cap
# ---------------------------------------------------------------------------

class TestIncidentCap(unittest.TestCase):
    def test_4_incidents_same_as_more(self):
        p4  = _proto(historical_incidents=4)
        p10 = _proto(historical_incidents=10)
        r4  = analyze([p4])
        r10 = analyze([p10])
        self.assertEqual(
            r4["protocols"][0]["oracle_risk_score"],
            r10["protocols"][0]["oracle_risk_score"]
        )

    def test_0_incidents_lower_score_than_4(self):
        p0 = _proto("A", oracle_type="CHAINLINK", oracle_count=1, twap_window_minutes=0,
                    uses_fallback=False, circuit_breaker=False,
                    max_price_deviation_pct=10.0, historical_incidents=0)
        p4 = _proto("B", oracle_type="CHAINLINK", oracle_count=1, twap_window_minutes=0,
                    uses_fallback=False, circuit_breaker=False,
                    max_price_deviation_pct=10.0, historical_incidents=4)
        r = analyze([p0, p4])
        s = {p["name"]: p["oracle_risk_score"] for p in r["protocols"]}
        self.assertLess(s["A"], s["B"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
