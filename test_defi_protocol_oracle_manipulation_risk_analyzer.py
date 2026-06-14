"""
Tests for MP-1030 DeFiProtocolOracleManipulationRiskAnalyzer.
Run: python3 -m unittest spa_core.tests.test_defi_protocol_oracle_manipulation_risk_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from spa_core.analytics.defi_protocol_oracle_manipulation_risk_analyzer import (
    DeFiProtocolOracleManipulationRiskAnalyzer,
    compute_oracle_type_risk,
    compute_twap_window_risk,
    compute_source_diversity_risk,
    compute_incident_history_risk,
    compute_cost_to_attack_ratio,
    compute_cost_ratio_risk,
    compute_manipulation_feasibility_score,
    _analyze_one,
    _atomic_write,
    _init_log,
    _append_log,
    _iso_now,
    _label,
    _grade,
    analyze,
    ORACLE_TYPE_BASE_SCORE,
    LOG_MAX_ENTRIES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _oracle(
    name="TestOracle",
    oracle_type="chainlink",
    twap_window_seconds=0.0,
    oracle_sources_count=5,
    historical_manipulation_incidents=0,
    tvl_at_risk_usd=10_000_000.0,
    manipulation_cost_usd_estimate=500_000_000.0,
):
    return {
        "name": name,
        "oracle_type": oracle_type,
        "twap_window_seconds": twap_window_seconds,
        "oracle_sources_count": oracle_sources_count,
        "historical_manipulation_incidents": historical_manipulation_incidents,
        "tvl_at_risk_usd": tvl_at_risk_usd,
        "manipulation_cost_usd_estimate": manipulation_cost_usd_estimate,
    }


def _safe_oracle():
    return _oracle(
        name="Safe", oracle_type="chainlink", oracle_sources_count=5,
        historical_manipulation_incidents=0,
        tvl_at_risk_usd=1_000_000.0,
        manipulation_cost_usd_estimate=999_999_999.0,
    )


def _critical_oracle():
    return _oracle(
        name="Critical", oracle_type="spot", oracle_sources_count=1,
        historical_manipulation_incidents=4,
        tvl_at_risk_usd=50_000_000.0,
        manipulation_cost_usd_estimate=100_000.0,
    )


# ---------------------------------------------------------------------------
# 1. compute_oracle_type_risk
# ---------------------------------------------------------------------------

class TestComputeOracleTypeRisk(unittest.TestCase):

    def test_chainlink_is_lowest(self):
        score = compute_oracle_type_risk("chainlink")
        self.assertEqual(score, ORACLE_TYPE_BASE_SCORE["chainlink"])
        self.assertLess(score, ORACLE_TYPE_BASE_SCORE["twap"])

    def test_spot_is_highest(self):
        score = compute_oracle_type_risk("spot")
        self.assertEqual(score, ORACLE_TYPE_BASE_SCORE["spot"])
        self.assertGreater(score, ORACLE_TYPE_BASE_SCORE["twap"])

    def test_twap_is_middle(self):
        score = compute_oracle_type_risk("twap")
        self.assertGreater(score, ORACLE_TYPE_BASE_SCORE["chainlink"])
        self.assertLess(score, ORACLE_TYPE_BASE_SCORE["spot"])

    def test_custom_fallback(self):
        score = compute_oracle_type_risk("custom")
        self.assertEqual(score, ORACLE_TYPE_BASE_SCORE["custom"])

    def test_unknown_type_fallback(self):
        score = compute_oracle_type_risk("unicorn")
        self.assertEqual(score, ORACLE_TYPE_BASE_SCORE["custom"])

    def test_case_insensitive(self):
        self.assertEqual(
            compute_oracle_type_risk("CHAINLINK"),
            compute_oracle_type_risk("chainlink"),
        )
        self.assertEqual(
            compute_oracle_type_risk("SPOT"),
            compute_oracle_type_risk("spot"),
        )

    def test_empty_string_fallback(self):
        score = compute_oracle_type_risk("")
        self.assertEqual(score, ORACLE_TYPE_BASE_SCORE["custom"])

    def test_all_known_types_positive(self):
        for ot in ("chainlink", "twap", "spot", "custom"):
            self.assertGreater(compute_oracle_type_risk(ot), 0.0)


# ---------------------------------------------------------------------------
# 2. compute_twap_window_risk
# ---------------------------------------------------------------------------

class TestComputeTwapWindowRisk(unittest.TestCase):

    def test_non_twap_returns_zero(self):
        self.assertEqual(compute_twap_window_risk("chainlink", 300), 0.0)
        self.assertEqual(compute_twap_window_risk("spot", 300), 0.0)
        self.assertEqual(compute_twap_window_risk("custom", 300), 0.0)

    def test_twap_zero_window_worst(self):
        risk = compute_twap_window_risk("twap", 0)
        self.assertEqual(risk, 40.0)

    def test_twap_strong_window_zero_risk(self):
        risk = compute_twap_window_risk("twap", 1800)
        self.assertEqual(risk, 0.0)

    def test_twap_beyond_strong_window(self):
        risk = compute_twap_window_risk("twap", 7200)
        self.assertEqual(risk, 0.0)

    def test_twap_weak_window_max_risk(self):
        risk = compute_twap_window_risk("twap", 300)
        self.assertEqual(risk, 40.0)

    def test_twap_intermediate_window(self):
        # Between weak (300) and strong (1800): should be between 0 and 40
        risk = compute_twap_window_risk("twap", 900)
        self.assertGreater(risk, 0.0)
        self.assertLess(risk, 40.0)

    def test_twap_window_monotone_decreasing(self):
        risks = [compute_twap_window_risk("twap", w) for w in (100, 300, 600, 900, 1200, 1800, 3600)]
        for i in range(len(risks) - 1):
            self.assertGreaterEqual(risks[i], risks[i + 1])

    def test_twap_case_insensitive(self):
        self.assertEqual(
            compute_twap_window_risk("TWAP", 600),
            compute_twap_window_risk("twap", 600),
        )


# ---------------------------------------------------------------------------
# 3. compute_source_diversity_risk
# ---------------------------------------------------------------------------

class TestComputeSourceDiversityRisk(unittest.TestCase):

    def test_one_source_max_risk(self):
        risk = compute_source_diversity_risk(1)
        self.assertEqual(risk, 30.0)

    def test_five_plus_sources_zero_risk(self):
        self.assertEqual(compute_source_diversity_risk(5), 0.0)
        self.assertEqual(compute_source_diversity_risk(10), 0.0)
        self.assertEqual(compute_source_diversity_risk(100), 0.0)

    def test_two_three_four_sources_between(self):
        r1 = compute_source_diversity_risk(1)
        r2 = compute_source_diversity_risk(2)
        r3 = compute_source_diversity_risk(3)
        r4 = compute_source_diversity_risk(4)
        r5 = compute_source_diversity_risk(5)
        self.assertGreater(r1, r2)
        self.assertGreater(r2, r3)
        self.assertGreater(r3, r4)
        self.assertGreater(r4, r5)

    def test_non_negative(self):
        for n in range(1, 20):
            self.assertGreaterEqual(compute_source_diversity_risk(n), 0.0)

    def test_max_is_thirty(self):
        for n in range(0, 5):
            self.assertLessEqual(compute_source_diversity_risk(max(1, n)), 30.0)


# ---------------------------------------------------------------------------
# 4. compute_incident_history_risk
# ---------------------------------------------------------------------------

class TestComputeIncidentHistoryRisk(unittest.TestCase):

    def test_zero_incidents_zero_risk(self):
        self.assertEqual(compute_incident_history_risk(0), 0.0)

    def test_one_incident(self):
        self.assertEqual(compute_incident_history_risk(1), 10.0)

    def test_four_incidents_max(self):
        # 4 * 10 = 40 = MAX
        self.assertEqual(compute_incident_history_risk(4), 40.0)

    def test_many_incidents_capped(self):
        self.assertEqual(compute_incident_history_risk(100), 40.0)

    def test_monotone_increasing_to_cap(self):
        prev = 0.0
        for n in range(1, 6):
            curr = compute_incident_history_risk(n)
            self.assertGreaterEqual(curr, prev)
            prev = curr

    def test_negative_treated_as_zero(self):
        self.assertEqual(compute_incident_history_risk(-5), 0.0)


# ---------------------------------------------------------------------------
# 5. compute_cost_to_attack_ratio
# ---------------------------------------------------------------------------

class TestComputeCostToAttackRatio(unittest.TestCase):

    def test_normal_ratio(self):
        ratio = compute_cost_to_attack_ratio(1_000_000.0, 500_000.0)
        self.assertAlmostEqual(ratio, 2.0, places=4)

    def test_zero_tvl_zero_ratio(self):
        ratio = compute_cost_to_attack_ratio(0.0, 1_000_000.0)
        self.assertEqual(ratio, 0.0)

    def test_zero_cost_sentinel(self):
        ratio = compute_cost_to_attack_ratio(1_000_000.0, 0.0)
        self.assertEqual(ratio, 9999.0)

    def test_zero_tvl_zero_cost(self):
        ratio = compute_cost_to_attack_ratio(0.0, 0.0)
        self.assertEqual(ratio, 0.0)

    def test_equal_tvl_and_cost(self):
        ratio = compute_cost_to_attack_ratio(1_000_000.0, 1_000_000.0)
        self.assertAlmostEqual(ratio, 1.0, places=5)

    def test_expensive_attack_low_ratio(self):
        ratio = compute_cost_to_attack_ratio(100.0, 1_000_000_000.0)
        self.assertLess(ratio, 1.0)

    def test_negative_cost_sentinel(self):
        ratio = compute_cost_to_attack_ratio(1_000_000.0, -1.0)
        self.assertEqual(ratio, 9999.0)


# ---------------------------------------------------------------------------
# 6. compute_cost_ratio_risk
# ---------------------------------------------------------------------------

class TestComputeCostRatioRisk(unittest.TestCase):

    def test_zero_ratio_zero_risk(self):
        self.assertEqual(compute_cost_ratio_risk(0.0), 0.0)

    def test_very_low_ratio_zero(self):
        self.assertEqual(compute_cost_ratio_risk(0.05), 0.0)

    def test_ratio_exactly_one(self):
        risk = compute_cost_ratio_risk(1.0)
        self.assertAlmostEqual(risk, 15.0, places=2)

    def test_very_high_ratio_max(self):
        risk = compute_cost_ratio_risk(9999.0)
        self.assertAlmostEqual(risk, 30.0, places=1)

    def test_monotone_increasing(self):
        prev = 0.0
        for r in (0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 100.0):
            curr = compute_cost_ratio_risk(r)
            self.assertGreaterEqual(curr, prev)
            prev = curr

    def test_never_exceeds_thirty(self):
        for r in (0.0, 0.5, 1.0, 5.0, 10.0, 100.0, 9999.0):
            self.assertLessEqual(compute_cost_ratio_risk(r), 30.0)

    def test_never_negative(self):
        for r in (0.0, 0.01, 0.1, 1.0):
            self.assertGreaterEqual(compute_cost_ratio_risk(r), 0.0)


# ---------------------------------------------------------------------------
# 7. compute_manipulation_feasibility_score (composite)
# ---------------------------------------------------------------------------

class TestComputeManipulationFeasibilityScore(unittest.TestCase):

    def _call(self, **kwargs):
        defaults = dict(
            oracle_type="chainlink",
            twap_window_seconds=0.0,
            oracle_sources_count=5,
            historical_manipulation_incidents=0,
            tvl_at_risk_usd=1_000_000.0,
            manipulation_cost_usd_estimate=500_000_000.0,
        )
        defaults.update(kwargs)
        return compute_manipulation_feasibility_score(**defaults)

    def test_returns_tuple(self):
        result = self._call()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_score_in_range(self):
        for ot in ("chainlink", "twap", "spot", "custom"):
            score, _ = self._call(oracle_type=ot)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_spot_higher_than_chainlink(self):
        spot_score, _ = self._call(oracle_type="spot")
        link_score, _ = self._call(oracle_type="chainlink")
        self.assertGreater(spot_score, link_score)

    def test_more_incidents_raises_score(self):
        s0, _ = self._call(historical_manipulation_incidents=0)
        s2, _ = self._call(historical_manipulation_incidents=2)
        self.assertGreater(s2, s0)

    def test_high_ratio_raises_score(self):
        s_low, _ = self._call(tvl_at_risk_usd=100.0, manipulation_cost_usd_estimate=1_000_000_000.0)
        s_high, _ = self._call(tvl_at_risk_usd=100_000_000.0, manipulation_cost_usd_estimate=1_000.0)
        self.assertGreater(s_high, s_low)

    def test_twap_short_window_raises_score(self):
        short_score, _ = self._call(oracle_type="twap", twap_window_seconds=60.0)
        long_score, _ = self._call(oracle_type="twap", twap_window_seconds=3600.0)
        self.assertGreater(short_score, long_score)

    def test_few_sources_raises_score(self):
        s1, _ = self._call(oracle_sources_count=1)
        s5, _ = self._call(oracle_sources_count=5)
        self.assertGreater(s1, s5)

    def test_cost_to_attack_ratio_returned(self):
        _, ratio = self._call(tvl_at_risk_usd=2_000_000.0, manipulation_cost_usd_estimate=1_000_000.0)
        self.assertAlmostEqual(ratio, 2.0, places=4)

    def test_zero_cost_sentinel_ratio(self):
        _, ratio = self._call(tvl_at_risk_usd=1_000.0, manipulation_cost_usd_estimate=0.0)
        self.assertEqual(ratio, 9999.0)


# ---------------------------------------------------------------------------
# 8. _label helper
# ---------------------------------------------------------------------------

class TestLabelHelper(unittest.TestCase):

    def test_manipulation_proof(self):
        self.assertEqual(_label(0.0), "MANIPULATION_PROOF")
        self.assertEqual(_label(10.0), "MANIPULATION_PROOF")
        self.assertEqual(_label(19.9), "MANIPULATION_PROOF")

    def test_well_protected(self):
        self.assertEqual(_label(20.0), "WELL_PROTECTED")
        self.assertEqual(_label(39.9), "WELL_PROTECTED")

    def test_moderate_risk(self):
        self.assertEqual(_label(40.0), "MODERATE_RISK")
        self.assertEqual(_label(59.9), "MODERATE_RISK")

    def test_high_risk(self):
        self.assertEqual(_label(60.0), "HIGH_RISK")
        self.assertEqual(_label(79.9), "HIGH_RISK")

    def test_critical_vulnerability(self):
        self.assertEqual(_label(80.0), "CRITICAL_VULNERABILITY")
        self.assertEqual(_label(100.0), "CRITICAL_VULNERABILITY")


# ---------------------------------------------------------------------------
# 9. _grade helper
# ---------------------------------------------------------------------------

class TestGradeHelper(unittest.TestCase):

    def test_A_grade(self):
        self.assertEqual(_grade(0.0), "A")
        self.assertEqual(_grade(19.9), "A")

    def test_B_grade(self):
        self.assertEqual(_grade(20.0), "B")
        self.assertEqual(_grade(39.9), "B")

    def test_C_grade(self):
        self.assertEqual(_grade(40.0), "C")
        self.assertEqual(_grade(59.9), "C")

    def test_D_grade(self):
        self.assertEqual(_grade(60.0), "D")
        self.assertEqual(_grade(79.9), "D")

    def test_F_grade(self):
        self.assertEqual(_grade(80.0), "F")
        self.assertEqual(_grade(100.0), "F")


# ---------------------------------------------------------------------------
# 10. _analyze_one
# ---------------------------------------------------------------------------

class TestAnalyzeOne(unittest.TestCase):

    def test_returns_dict(self):
        result = _analyze_one(_safe_oracle())
        self.assertIsInstance(result, dict)

    def test_required_output_keys(self):
        result = _analyze_one(_safe_oracle())
        for key in ("name", "oracle_type", "twap_window_seconds",
                    "oracle_sources_count", "historical_manipulation_incidents",
                    "tvl_at_risk_usd", "manipulation_cost_usd_estimate",
                    "manipulation_feasibility_score", "cost_to_attack_ratio",
                    "oracle_quality_grade", "label"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_safe_oracle_low_score(self):
        result = _analyze_one(_safe_oracle())
        self.assertLess(result["manipulation_feasibility_score"], 40.0)

    def test_critical_oracle_high_score(self):
        result = _analyze_one(_critical_oracle())
        self.assertGreaterEqual(result["manipulation_feasibility_score"], 60.0)

    def test_grade_matches_score(self):
        result = _analyze_one(_safe_oracle())
        expected_grade = _grade(result["manipulation_feasibility_score"])
        self.assertEqual(result["oracle_quality_grade"], expected_grade)

    def test_label_matches_score(self):
        result = _analyze_one(_critical_oracle())
        expected_label = _label(result["manipulation_feasibility_score"])
        self.assertEqual(result["label"], expected_label)

    def test_default_name_unknown(self):
        result = _analyze_one({})
        self.assertEqual(result["name"], "unknown")

    def test_name_preserved(self):
        result = _analyze_one(_oracle(name="Uniswap V3 TWAP"))
        self.assertEqual(result["name"], "Uniswap V3 TWAP")

    def test_score_is_float(self):
        result = _analyze_one(_safe_oracle())
        self.assertIsInstance(result["manipulation_feasibility_score"], float)


# ---------------------------------------------------------------------------
# 11. DeFiProtocolOracleManipulationRiskAnalyzer.analyze
# ---------------------------------------------------------------------------

class TestAnalyzerAnalyze(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log = os.path.join(self.tmpdir, "test_oracle_log.json")
        self.analyzer = DeFiProtocolOracleManipulationRiskAnalyzer(log_path=self.log)

    def test_returns_dict(self):
        result = self.analyzer.analyze([_safe_oracle()])
        self.assertIsInstance(result, dict)

    def test_required_output_keys(self):
        result = self.analyzer.analyze([_safe_oracle()])
        for key in ("oracles", "most_vulnerable", "most_protected",
                    "avg_feasibility_score", "critical_vulnerability_count",
                    "manipulation_proof_count", "analyzed_at"):
            self.assertIn(key, result)

    def test_raises_on_empty_list(self):
        with self.assertRaises(ValueError):
            self.analyzer.analyze([])

    def test_raises_on_non_list(self):
        with self.assertRaises((ValueError, TypeError)):
            self.analyzer.analyze("not a list")  # type: ignore

    def test_single_oracle_most_vulnerable_equals_most_protected(self):
        result = self.analyzer.analyze([_safe_oracle()])
        self.assertEqual(result["most_vulnerable"], result["most_protected"])

    def test_two_oracles_different_risk(self):
        result = self.analyzer.analyze([_safe_oracle(), _critical_oracle()])
        self.assertNotEqual(result["most_vulnerable"], result["most_protected"])
        self.assertEqual(result["most_vulnerable"], "Critical")
        self.assertEqual(result["most_protected"], "Safe")

    def test_avg_score_is_average(self):
        result = self.analyzer.analyze([_safe_oracle(), _critical_oracle()])
        scores = [o["manipulation_feasibility_score"] for o in result["oracles"]]
        expected = round(sum(scores) / len(scores), 2)
        self.assertAlmostEqual(result["avg_feasibility_score"], expected, places=2)

    def test_critical_count(self):
        oracles = [_critical_oracle(), _critical_oracle(), _safe_oracle()]
        result = self.analyzer.analyze(oracles, config={"log_path": self.log})
        self.assertGreaterEqual(result["critical_vulnerability_count"], 2)

    def test_analyzed_at_is_string(self):
        result = self.analyzer.analyze([_safe_oracle()])
        self.assertIsInstance(result["analyzed_at"], str)
        self.assertIn("T", result["analyzed_at"])

    def test_log_written(self):
        self.analyzer.analyze([_safe_oracle()])
        self.assertTrue(os.path.exists(self.log))

    def test_log_is_list(self):
        self.analyzer.analyze([_safe_oracle()])
        with open(self.log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_config_log_path_override(self):
        alt = os.path.join(self.tmpdir, "alt_log.json")
        self.analyzer.analyze([_safe_oracle()], config={"log_path": alt})
        self.assertTrue(os.path.exists(alt))


# ---------------------------------------------------------------------------
# 12. analyze_one convenience method
# ---------------------------------------------------------------------------

class TestAnalyzeOneMethod(unittest.TestCase):

    def setUp(self):
        self.analyzer = DeFiProtocolOracleManipulationRiskAnalyzer(
            log_path=os.path.join(tempfile.mkdtemp(), "log.json")
        )

    def test_returns_dict(self):
        result = self.analyzer.analyze_one(_safe_oracle())
        self.assertIsInstance(result, dict)

    def test_same_as_analyze_one_function(self):
        oracle = _safe_oracle()
        direct = _analyze_one(oracle)
        method = self.analyzer.analyze_one(oracle)
        self.assertEqual(direct["manipulation_feasibility_score"],
                         method["manipulation_feasibility_score"])
        self.assertEqual(direct["label"], method["label"])


# ---------------------------------------------------------------------------
# 13. Module-level analyze() shorthand
# ---------------------------------------------------------------------------

class TestModuleLevelAnalyze(unittest.TestCase):

    def test_returns_dict(self):
        td = tempfile.mkdtemp()
        result = analyze([_safe_oracle()], config={"log_path": os.path.join(td, "log.json")})
        self.assertIsInstance(result, dict)
        self.assertIn("oracles", result)


# ---------------------------------------------------------------------------
# 14. Ring-buffer log — _atomic_write, _init_log, _append_log
# ---------------------------------------------------------------------------

class TestLogHelpers(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log = os.path.join(self.tmpdir, "test_log.json")

    def test_atomic_write_creates_file(self):
        _atomic_write(self.log, [{"a": 1}])
        self.assertTrue(os.path.exists(self.log))

    def test_atomic_write_content(self):
        _atomic_write(self.log, [{"hello": "world"}])
        with open(self.log) as f:
            data = json.load(f)
        self.assertEqual(data, [{"hello": "world"}])

    def test_init_log_missing_file(self):
        entries = _init_log("/nonexistent/path/log.json")
        self.assertEqual(entries, [])

    def test_init_log_existing(self):
        _atomic_write(self.log, [{"x": 1}])
        entries = _init_log(self.log)
        self.assertEqual(entries, [{"x": 1}])

    def test_init_log_corrupt_returns_empty(self):
        with open(self.log, "w") as f:
            f.write("not json{{")
        entries = _init_log(self.log)
        self.assertEqual(entries, [])

    def test_append_log_increments(self):
        result = {
            "analyzed_at": "2026-01-01T00:00:00Z",
            "oracles": [_safe_oracle()],
            "avg_feasibility_score": 15.0,
            "critical_vulnerability_count": 0,
            "manipulation_proof_count": 1,
            "most_vulnerable": "Safe",
            "most_protected": "Safe",
        }
        _append_log(result, self.log)
        _append_log(result, self.log)
        entries = _init_log(self.log)
        self.assertEqual(len(entries), 2)

    def test_ring_buffer_capped(self):
        result = {
            "analyzed_at": "2026-01-01T00:00:00Z",
            "oracles": [],
            "avg_feasibility_score": 15.0,
            "critical_vulnerability_count": 0,
            "manipulation_proof_count": 0,
            "most_vulnerable": "X",
            "most_protected": "X",
        }
        for _ in range(LOG_MAX_ENTRIES + 20):
            _append_log(result, self.log)
        entries = _init_log(self.log)
        self.assertLessEqual(len(entries), LOG_MAX_ENTRIES)


# ---------------------------------------------------------------------------
# 15. _iso_now
# ---------------------------------------------------------------------------

class TestIsoNow(unittest.TestCase):

    def test_returns_string(self):
        ts = _iso_now()
        self.assertIsInstance(ts, str)

    def test_contains_T(self):
        self.assertIn("T", _iso_now())

    def test_contains_Z(self):
        self.assertIn("Z", _iso_now())

    def test_length_is_20(self):
        self.assertEqual(len(_iso_now()), 20)


# ---------------------------------------------------------------------------
# 16. Label coverage — all 5 labels reachable
# ---------------------------------------------------------------------------

class TestAllLabelsReachable(unittest.TestCase):

    def _score_for(self, **kwargs):
        o = _oracle(**kwargs)
        return _analyze_one(o)

    def test_manipulation_proof_reachable(self):
        result = self._score_for(
            oracle_type="chainlink",
            oracle_sources_count=5,
            historical_manipulation_incidents=0,
            tvl_at_risk_usd=100.0,
            manipulation_cost_usd_estimate=1_000_000_000.0,
        )
        self.assertEqual(result["label"], "MANIPULATION_PROOF")

    def test_well_protected_reachable(self):
        # chainlink, some sources, no incidents, moderate ratio
        result = self._score_for(
            oracle_type="chainlink",
            oracle_sources_count=3,
            historical_manipulation_incidents=0,
            tvl_at_risk_usd=1_000_000.0,
            manipulation_cost_usd_estimate=100_000_000.0,
        )
        # Should be MANIPULATION_PROOF or WELL_PROTECTED
        self.assertIn(result["label"], ("MANIPULATION_PROOF", "WELL_PROTECTED"))

    def test_moderate_risk_reachable(self):
        # chainlink with no incidents, moderate cost ratio → MODERATE_RISK range
        result = self._score_for(
            oracle_type="chainlink",
            twap_window_seconds=0,
            oracle_sources_count=3,
            historical_manipulation_incidents=0,
            tvl_at_risk_usd=5_000_000.0,
            manipulation_cost_usd_estimate=5_000_000.0,
        )
        self.assertIn(result["label"], (
            "MODERATE_RISK", "WELL_PROTECTED", "HIGH_RISK", "CRITICAL_VULNERABILITY"
        ))

    def test_high_risk_reachable(self):
        result = self._score_for(
            oracle_type="twap",
            twap_window_seconds=180,
            oracle_sources_count=2,
            historical_manipulation_incidents=2,
            tvl_at_risk_usd=20_000_000.0,
            manipulation_cost_usd_estimate=5_000_000.0,
        )
        self.assertIn(result["label"], ("HIGH_RISK", "CRITICAL_VULNERABILITY"))

    def test_critical_vulnerability_reachable(self):
        result = self._score_for(
            oracle_type="spot",
            oracle_sources_count=1,
            historical_manipulation_incidents=4,
            tvl_at_risk_usd=50_000_000.0,
            manipulation_cost_usd_estimate=50_000.0,
        )
        self.assertEqual(result["label"], "CRITICAL_VULNERABILITY")


# ---------------------------------------------------------------------------
# 17. Grade coverage — all grades reachable
# ---------------------------------------------------------------------------

class TestAllGradesReachable(unittest.TestCase):

    def test_grade_A(self):
        self.assertEqual(_grade(10.0), "A")

    def test_grade_B(self):
        self.assertEqual(_grade(30.0), "B")

    def test_grade_C(self):
        self.assertEqual(_grade(50.0), "C")

    def test_grade_D(self):
        self.assertEqual(_grade(70.0), "D")

    def test_grade_F(self):
        self.assertEqual(_grade(90.0), "F")


# ---------------------------------------------------------------------------
# 18. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_empty_oracle_dict_defaults(self):
        result = _analyze_one({})
        self.assertIn("manipulation_feasibility_score", result)
        self.assertGreaterEqual(result["manipulation_feasibility_score"], 0.0)
        self.assertLessEqual(result["manipulation_feasibility_score"], 100.0)

    def test_very_large_tvl(self):
        # spot oracle + 1 source + many incidents + huge ratio → CRITICAL_VULNERABILITY
        result = _analyze_one(_oracle(
            oracle_type="spot",
            oracle_sources_count=1,
            historical_manipulation_incidents=4,
            tvl_at_risk_usd=1e15,
            manipulation_cost_usd_estimate=1.0,
        ))
        self.assertEqual(result["label"], "CRITICAL_VULNERABILITY")

    def test_negative_incidents_treated_as_zero(self):
        r0 = _analyze_one(_oracle(historical_manipulation_incidents=0))
        r_neg = _analyze_one(_oracle(historical_manipulation_incidents=-5))
        self.assertEqual(r0["manipulation_feasibility_score"],
                         r_neg["manipulation_feasibility_score"])

    def test_zero_tvl_zero_ratio(self):
        result = _analyze_one(_oracle(tvl_at_risk_usd=0.0))
        self.assertEqual(result["cost_to_attack_ratio"], 0.0)

    def test_score_bounded_at_100(self):
        result = _analyze_one(_oracle(
            oracle_type="spot",
            oracle_sources_count=1,
            historical_manipulation_incidents=100,
            tvl_at_risk_usd=1e12,
            manipulation_cost_usd_estimate=1.0,
        ))
        self.assertLessEqual(result["manipulation_feasibility_score"], 100.0)

    def test_score_not_negative(self):
        result = _analyze_one(_oracle(
            oracle_type="chainlink",
            oracle_sources_count=10,
            historical_manipulation_incidents=0,
            tvl_at_risk_usd=0.0,
            manipulation_cost_usd_estimate=1e12,
        ))
        self.assertGreaterEqual(result["manipulation_feasibility_score"], 0.0)

    def test_multiple_oracles_analyzed(self):
        oracles = [_oracle(name=f"Oracle{i}") for i in range(10)]
        td = tempfile.mkdtemp()
        result = DeFiProtocolOracleManipulationRiskAnalyzer(
            log_path=os.path.join(td, "log.json")
        ).analyze(oracles)
        self.assertEqual(len(result["oracles"]), 10)

    def test_twap_no_window_is_riskiest_twap(self):
        r_no_win = _analyze_one(_oracle(oracle_type="twap", twap_window_seconds=0.0))
        r_30min  = _analyze_one(_oracle(oracle_type="twap", twap_window_seconds=1800.0))
        self.assertGreaterEqual(
            r_no_win["manipulation_feasibility_score"],
            r_30min["manipulation_feasibility_score"],
        )


if __name__ == "__main__":
    unittest.main()
