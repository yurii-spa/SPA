"""
Tests for MP-774: OraclePriceDeviationDetector
================================================
71 tests — unittest only, temporary directories for log isolation.
"""

import json
import os
import sys
import unittest
import tempfile

# Ensure project root is on sys.path so spa_core.analytics is importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from spa_core.analytics.oracle_price_deviation_detector import (
    OraclePriceDeviationDetector,
    _atomic_write,
    _load_log,
    compute_deviation_pct,
    compute_manipulation_risk_score,
    compute_status,
    LOG_MAX_ENTRIES,
    STATUS_CRITICAL,
    STATUS_MANIPULATED,
    STATUS_NORMAL,
    STATUS_WARNING,
)


# ---------------------------------------------------------------------------
# TestComputeDeviationPct  (8 tests)
# ---------------------------------------------------------------------------

class TestComputeDeviationPct(unittest.TestCase):
    """Pure function: deviation_pct = abs(oracle - reference) / reference * 100"""

    def test_zero_reference_returns_zero(self):
        self.assertEqual(compute_deviation_pct(1.0, 0), 0.0)

    def test_equal_prices_returns_zero(self):
        self.assertEqual(compute_deviation_pct(1.0, 1.0), 0.0)

    def test_oracle_higher_returns_positive(self):
        result = compute_deviation_pct(1.05, 1.0)
        self.assertAlmostEqual(result, 5.0, places=6)

    def test_oracle_lower_abs_value(self):
        """Deviation must be positive even when oracle < reference."""
        result = compute_deviation_pct(0.95, 1.0)
        self.assertAlmostEqual(result, 5.0, places=6)

    def test_ten_percent_deviation(self):
        result = compute_deviation_pct(1.1, 1.0)
        self.assertAlmostEqual(result, 10.0, places=6)

    def test_large_deviation_100_pct(self):
        result = compute_deviation_pct(2.0, 1.0)
        self.assertAlmostEqual(result, 100.0, places=6)

    def test_small_deviation_0_1_pct(self):
        result = compute_deviation_pct(1.001, 1.0)
        self.assertAlmostEqual(result, 0.1, places=4)

    def test_three_pct_exact(self):
        result = compute_deviation_pct(1.03, 1.0)
        self.assertAlmostEqual(result, 3.0, places=6)


# ---------------------------------------------------------------------------
# TestComputeStatus  (16 tests)
# ---------------------------------------------------------------------------

class TestComputeStatus(unittest.TestCase):
    """Status boundaries relative to max_deviation_pct."""

    def test_zero_deviation_is_normal(self):
        self.assertEqual(compute_status(0.0, 1.0), STATUS_NORMAL)

    def test_below_max_is_normal(self):
        self.assertEqual(compute_status(0.5, 1.0), STATUS_NORMAL)

    def test_exactly_at_max_is_normal(self):
        # max * 1.0 < 1.5x threshold — still NORMAL
        self.assertEqual(compute_status(1.0, 1.0), STATUS_NORMAL)

    def test_just_below_warning_is_normal(self):
        self.assertEqual(compute_status(1.49, 1.0), STATUS_NORMAL)

    def test_exactly_1_5x_is_warning(self):
        self.assertEqual(compute_status(1.5, 1.0), STATUS_WARNING)

    def test_between_1_5x_and_2x_is_warning(self):
        self.assertEqual(compute_status(1.7, 1.0), STATUS_WARNING)

    def test_just_below_critical_is_warning(self):
        self.assertEqual(compute_status(1.99, 1.0), STATUS_WARNING)

    def test_exactly_2x_is_critical(self):
        self.assertEqual(compute_status(2.0, 1.0), STATUS_CRITICAL)

    def test_between_2x_and_3x_is_critical(self):
        self.assertEqual(compute_status(2.5, 1.0), STATUS_CRITICAL)

    def test_just_below_manipulated_is_critical(self):
        self.assertEqual(compute_status(2.99, 1.0), STATUS_CRITICAL)

    def test_exactly_3x_is_manipulated(self):
        self.assertEqual(compute_status(3.0, 1.0), STATUS_MANIPULATED)

    def test_above_3x_is_manipulated(self):
        self.assertEqual(compute_status(5.0, 1.0), STATUS_MANIPULATED)

    def test_with_max_2_warning(self):
        # max=2%, deviation=3% → 1.5x → WARNING
        self.assertEqual(compute_status(3.0, 2.0), STATUS_WARNING)

    def test_with_max_2_critical(self):
        # max=2%, deviation=4% → 2x → CRITICAL
        self.assertEqual(compute_status(4.0, 2.0), STATUS_CRITICAL)

    def test_large_max_keeps_normal(self):
        # max=10%, deviation=5% → 0.5x → NORMAL
        self.assertEqual(compute_status(5.0, 10.0), STATUS_NORMAL)

    def test_status_string_constants(self):
        self.assertEqual(STATUS_NORMAL, "NORMAL")
        self.assertEqual(STATUS_WARNING, "WARNING")
        self.assertEqual(STATUS_CRITICAL, "CRITICAL")
        self.assertEqual(STATUS_MANIPULATED, "MANIPULATED")


# ---------------------------------------------------------------------------
# TestComputeManipulationRiskScore  (12 tests)
# ---------------------------------------------------------------------------

class TestComputeManipulationRiskScore(unittest.TestCase):

    def test_zero_deviation_score_zero(self):
        self.assertEqual(compute_manipulation_risk_score(0.0, 1.0), 0)

    def test_zero_max_returns_zero(self):
        self.assertEqual(compute_manipulation_risk_score(5.0, 0), 0)

    def test_negative_max_returns_zero(self):
        self.assertEqual(compute_manipulation_risk_score(1.0, -1.0), 0)

    def test_at_1x_max_score_33(self):
        self.assertEqual(compute_manipulation_risk_score(1.0, 1.0), 33)

    def test_above_3x_max_score_100(self):
        self.assertEqual(compute_manipulation_risk_score(10.0, 1.0), 100)

    def test_score_is_int(self):
        score = compute_manipulation_risk_score(2.0, 1.0)
        self.assertIsInstance(score, int)

    def test_score_bounded_zero_to_100(self):
        for dev in [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 5.0, 100.0]:
            score = compute_manipulation_risk_score(dev, 1.0)
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_score_monotone_increasing(self):
        devs = [i * 0.5 for i in range(7)]
        scores = [compute_manipulation_risk_score(d, 1.0) for d in devs]
        for i in range(len(scores) - 1):
            self.assertLessEqual(scores[i], scores[i + 1])

    def test_normal_range_score_under_34(self):
        score = compute_manipulation_risk_score(0.9, 1.0)
        self.assertLess(score, 34)

    def test_warning_range_score_33_to_49(self):
        score = compute_manipulation_risk_score(1.25, 1.0)
        self.assertGreaterEqual(score, 33)
        self.assertLess(score, 50)

    def test_critical_range_score_49_to_74(self):
        score = compute_manipulation_risk_score(1.75, 1.0)
        self.assertGreaterEqual(score, 49)
        self.assertLessEqual(score, 74)

    def test_manipulated_range_score_74_to_100(self):
        score = compute_manipulation_risk_score(2.5, 1.0)
        self.assertGreaterEqual(score, 74)
        self.assertLessEqual(score, 100)


# ---------------------------------------------------------------------------
# TestDetect  (15 tests)
# ---------------------------------------------------------------------------

class TestDetect(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmpdir.name, "oracle_log.json")
        self.det = OraclePriceDeviationDetector(log_path=self.log)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _entry(self, protocol="aave", oracle=1.0, ref=1.0, max_dev=1.0):
        return {
            "protocol": protocol,
            "oracle_price": oracle,
            "reference_price": ref,
            "max_deviation_pct": max_dev,
        }

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(self.det.detect([]), [])

    def test_single_normal_protocol(self):
        result = self.det.detect([self._entry("aave", 1.0, 1.0, 1.0)])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], STATUS_NORMAL)

    def test_single_warning_protocol(self):
        # 1.016 / 1.0 → 1.6 % → 1.6× 1% max → WARNING (using 1.016 not 1.015 to avoid FP edge)
        result = self.det.detect([self._entry("aave", 1.016, 1.0, 1.0)])
        self.assertEqual(result[0]["status"], STATUS_WARNING)

    def test_single_critical_protocol(self):
        # 1.02 → 2% → 2× 1% → CRITICAL
        result = self.det.detect([self._entry("aave", 1.02, 1.0, 1.0)])
        self.assertEqual(result[0]["status"], STATUS_CRITICAL)

    def test_single_manipulated_protocol(self):
        # 1.03 → 3% → 3× 1% → MANIPULATED
        result = self.det.detect([self._entry("aave", 1.03, 1.0, 1.0)])
        self.assertEqual(result[0]["status"], STATUS_MANIPULATED)

    def test_multiple_protocols_all_returned(self):
        data = [self._entry("aave"), self._entry("compound")]
        result = self.det.detect(data)
        self.assertEqual(len(result), 2)

    def test_result_has_all_required_fields(self):
        result = self.det.detect([self._entry()])
        required = [
            "timestamp", "protocol", "oracle_price", "reference_price",
            "max_deviation_pct", "deviation_pct", "status",
            "manipulation_risk_score",
        ]
        for field in required:
            self.assertIn(field, result[0], msg=f"Missing field: {field}")

    def test_deviation_pct_computed_correctly(self):
        result = self.det.detect([self._entry("aave", 1.05, 1.0, 10.0)])
        self.assertAlmostEqual(result[0]["deviation_pct"], 5.0, places=4)

    def test_protocol_name_preserved(self):
        result = self.det.detect([self._entry("morpho")])
        self.assertEqual(result[0]["protocol"], "morpho")

    def test_log_file_created_after_detect(self):
        self.det.detect([self._entry()])
        self.assertTrue(os.path.exists(self.log))

    def test_log_file_is_valid_json_list(self):
        self.det.detect([self._entry()])
        with open(self.log) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_ring_buffer_cap_100(self):
        for i in range(105):
            self.det.detect([self._entry(f"proto{i}")])
        with open(self.log) as fh:
            log = json.load(fh)
        self.assertLessEqual(len(log), LOG_MAX_ENTRIES)

    def test_timestamp_is_iso_string(self):
        result = self.det.detect([self._entry()])
        ts = result[0]["timestamp"]
        self.assertIn("T", ts)  # ISO-8601 contains 'T'

    def test_risk_score_is_integer(self):
        result = self.det.detect([self._entry()])
        self.assertIsInstance(result[0]["manipulation_risk_score"], int)

    def test_zero_reference_handled_gracefully(self):
        result = self.det.detect([self._entry("aave", 1.0, 0, 1.0)])
        self.assertEqual(result[0]["deviation_pct"], 0.0)
        self.assertEqual(result[0]["status"], STATUS_NORMAL)


# ---------------------------------------------------------------------------
# TestGetManipulatedProtocols  (8 tests)
# ---------------------------------------------------------------------------

class TestGetManipulatedProtocols(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.det = OraclePriceDeviationDetector(
            log_path=os.path.join(self.tmpdir.name, "log.json")
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _detect_one(self, protocol, oracle, ref=1.0, max_dev=1.0):
        self.det.detect([{
            "protocol": protocol,
            "oracle_price": oracle,
            "reference_price": ref,
            "max_deviation_pct": max_dev,
        }])

    def test_empty_before_detect_returns_empty(self):
        self.assertEqual(self.det.get_manipulated_protocols(), [])

    def test_returns_list(self):
        self.assertIsInstance(self.det.get_manipulated_protocols(), list)

    def test_normal_protocol_not_returned(self):
        self._detect_one("aave", 1.0)
        self.assertNotIn("aave", self.det.get_manipulated_protocols())

    def test_warning_protocol_not_returned(self):
        self._detect_one("aave", 1.015)
        self.assertNotIn("aave", self.det.get_manipulated_protocols())

    def test_critical_protocol_not_returned(self):
        self._detect_one("aave", 1.02)
        self.assertNotIn("aave", self.det.get_manipulated_protocols())

    def test_manipulated_protocol_returned(self):
        self._detect_one("compound", 1.04)
        self.assertIn("compound", self.det.get_manipulated_protocols())

    def test_multiple_manipulated_all_returned(self):
        self.det.detect([
            {"protocol": "a", "oracle_price": 1.04, "reference_price": 1.0, "max_deviation_pct": 1.0},
            {"protocol": "b", "oracle_price": 1.05, "reference_price": 1.0, "max_deviation_pct": 1.0},
        ])
        manip = self.det.get_manipulated_protocols()
        self.assertIn("a", manip)
        self.assertIn("b", manip)

    def test_mixed_only_manipulated_returned(self):
        self.det.detect([
            {"protocol": "good",  "oracle_price": 1.00, "reference_price": 1.0, "max_deviation_pct": 1.0},
            {"protocol": "manip", "oracle_price": 1.04, "reference_price": 1.0, "max_deviation_pct": 1.0},
        ])
        manip = self.det.get_manipulated_protocols()
        self.assertNotIn("good", manip)
        self.assertIn("manip", manip)


# ---------------------------------------------------------------------------
# TestGetPortfolioOracleRisk  (12 tests)
# ---------------------------------------------------------------------------

class TestGetPortfolioOracleRisk(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.det = OraclePriceDeviationDetector(
            log_path=os.path.join(self.tmpdir.name, "log.json")
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _e(self, protocol, oracle, ref=1.0, max_dev=1.0):
        return {"protocol": protocol, "oracle_price": oracle,
                "reference_price": ref, "max_deviation_pct": max_dev}

    def test_empty_before_detect_returns_defaults(self):
        risk = self.det.get_portfolio_oracle_risk()
        self.assertEqual(risk["overall_status"], STATUS_NORMAL)
        self.assertEqual(risk["max_risk_score"], 0)
        self.assertEqual(risk["manipulated_count"], 0)
        self.assertEqual(risk["critical_count"], 0)
        self.assertEqual(risk["protocols_at_risk"], [])

    def test_all_normal_status_normal(self):
        self.det.detect([self._e("a", 1.0), self._e("b", 1.0)])
        self.assertEqual(self.det.get_portfolio_oracle_risk()["overall_status"], STATUS_NORMAL)

    def test_warning_protocol_upgrades_status(self):
        # 1.016 → 1.6% deviation > 1.5× 1.0% max → WARNING (1.015 hits FP edge)
        self.det.detect([self._e("a", 1.016)])
        self.assertEqual(self.det.get_portfolio_oracle_risk()["overall_status"], STATUS_WARNING)

    def test_critical_protocol_upgrades_status(self):
        self.det.detect([self._e("a", 1.02)])
        self.assertEqual(self.det.get_portfolio_oracle_risk()["overall_status"], STATUS_CRITICAL)

    def test_manipulated_protocol_upgrades_status(self):
        self.det.detect([self._e("a", 1.04)])
        self.assertEqual(self.det.get_portfolio_oracle_risk()["overall_status"], STATUS_MANIPULATED)

    def test_worst_case_wins(self):
        self.det.detect([
            self._e("x", 1.0),    # NORMAL
            self._e("y", 1.015),  # WARNING
            self._e("z", 1.04),   # MANIPULATED
        ])
        self.assertEqual(
            self.det.get_portfolio_oracle_risk()["overall_status"],
            STATUS_MANIPULATED,
        )

    def test_manipulated_count_correct(self):
        self.det.detect([self._e("a", 1.04), self._e("b", 1.05)])
        self.assertEqual(self.det.get_portfolio_oracle_risk()["manipulated_count"], 2)

    def test_critical_count_correct(self):
        self.det.detect([self._e("a", 1.02), self._e("b", 1.0)])
        self.assertEqual(self.det.get_portfolio_oracle_risk()["critical_count"], 1)

    def test_max_risk_score_is_max_of_all(self):
        self.det.detect([self._e("a", 1.0), self._e("b", 1.04)])
        risk = self.det.get_portfolio_oracle_risk()
        self.assertGreater(risk["max_risk_score"], 0)

    def test_avg_risk_score_is_float(self):
        self.det.detect([self._e("a", 1.0)])
        self.assertIsInstance(self.det.get_portfolio_oracle_risk()["avg_risk_score"], float)

    def test_protocols_at_risk_empty_when_all_normal(self):
        self.det.detect([self._e("aave", 1.0)])
        self.assertEqual(self.det.get_portfolio_oracle_risk()["protocols_at_risk"], [])

    def test_protocols_at_risk_includes_warning_and_above(self):
        # 1.016 → 1.6% > 1.5× 1% max → WARNING; 1.04 → MANIPULATED
        self.det.detect([
            self._e("safe", 1.0),
            self._e("risky", 1.016),
            self._e("danger", 1.04),
        ])
        at_risk = self.det.get_portfolio_oracle_risk()["protocols_at_risk"]
        self.assertNotIn("safe", at_risk)
        self.assertIn("risky", at_risk)
        self.assertIn("danger", at_risk)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
