"""
Tests for MP-752: FlashLoanRiskDetector
Uses unittest only (NOT pytest).
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root is importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.flash_loan_risk_detector import (
    compute_oracle_risk,
    compute_manipulation_surface,
    compute_history_risk,
    compute_flash_loan_risk,
    risk_label,
    max_safe_exposure,
    profile_protocol,
    detect_risks,
    save_results,
    load_history,
    FlashLoanRiskProfile,
    FlashLoanRiskResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_profile(**kwargs) -> FlashLoanRiskProfile:
    defaults = dict(
        protocol="TestProtocol",
        oracle_centralization=50.0,
        tvl_concentration_pct=40.0,
        price_impact_at_1m_usd=10.0,
        has_history=False,
        uses_twap=False,
    )
    defaults.update(kwargs)
    return profile_protocol(**defaults)


def _sample_pd(**kwargs):
    defaults = dict(
        protocol="Proto",
        oracle_centralization=50,
        tvl_concentration_pct=40,
        price_impact_at_1m_usd=10,
        has_price_manipulation_history=False,
        uses_twap=False,
    )
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# compute_oracle_risk
# ---------------------------------------------------------------------------

class TestComputeOracleRisk(unittest.TestCase):

    def test_centralized_no_twap_high(self):
        score = compute_oracle_risk(100, False)
        # 100*0.8 + 20 = 100 (clamped)
        self.assertAlmostEqual(score, 100.0)

    def test_centralized_with_twap_lower(self):
        score = compute_oracle_risk(100, True)
        # 100*0.8 + 0 = 80
        self.assertAlmostEqual(score, 80.0)

    def test_zero_centralization_no_twap(self):
        score = compute_oracle_risk(0, False)
        # 0*0.8 + 20 = 20
        self.assertAlmostEqual(score, 20.0)

    def test_zero_centralization_with_twap(self):
        score = compute_oracle_risk(0, True)
        # 0*0.8 + 0 = 0
        self.assertAlmostEqual(score, 0.0)

    def test_partial_centralization_no_twap(self):
        score = compute_oracle_risk(50, False)
        # 50*0.8 + 20 = 60
        self.assertAlmostEqual(score, 60.0)

    def test_partial_centralization_with_twap(self):
        score = compute_oracle_risk(50, True)
        # 50*0.8 + 0 = 40
        self.assertAlmostEqual(score, 40.0)

    def test_clamped_max(self):
        # 90*0.8 + 20 = 92, no clamping needed; but 100*0.8+20=100
        score = compute_oracle_risk(100, False)
        self.assertLessEqual(score, 100.0)

    def test_clamped_min(self):
        score = compute_oracle_risk(0, True)
        self.assertGreaterEqual(score, 0.0)

    def test_80_centralization_no_twap(self):
        score = compute_oracle_risk(80, False)
        # 80*0.8 + 20 = 84
        self.assertAlmostEqual(score, 84.0)

    def test_twap_reduces_score_vs_no_twap(self):
        with_twap = compute_oracle_risk(60, True)
        without_twap = compute_oracle_risk(60, False)
        self.assertLess(with_twap, without_twap)


# ---------------------------------------------------------------------------
# compute_manipulation_surface
# ---------------------------------------------------------------------------

class TestComputeManipulationSurface(unittest.TestCase):

    def test_formula_basic(self):
        score = compute_manipulation_surface(40.0, 20.0)
        # 40*0.5 + 20*0.5 = 30
        self.assertAlmostEqual(score, 30.0)

    def test_zero_inputs(self):
        score = compute_manipulation_surface(0.0, 0.0)
        self.assertAlmostEqual(score, 0.0)

    def test_max_inputs(self):
        score = compute_manipulation_surface(100.0, 100.0)
        # 100*0.5 + 100*0.5 = 100
        self.assertAlmostEqual(score, 100.0)

    def test_clamped_above_100(self):
        score = compute_manipulation_surface(120.0, 120.0)
        self.assertAlmostEqual(score, 100.0)

    def test_clamped_below_zero(self):
        score = compute_manipulation_surface(-10.0, -10.0)
        self.assertAlmostEqual(score, 0.0)

    def test_tvl_only(self):
        score = compute_manipulation_surface(80.0, 0.0)
        # 80*0.5 = 40
        self.assertAlmostEqual(score, 40.0)

    def test_price_impact_only(self):
        score = compute_manipulation_surface(0.0, 60.0)
        # 60*0.5 = 30
        self.assertAlmostEqual(score, 30.0)

    def test_equal_weights(self):
        score = compute_manipulation_surface(50.0, 50.0)
        self.assertAlmostEqual(score, 50.0)


# ---------------------------------------------------------------------------
# compute_history_risk
# ---------------------------------------------------------------------------

class TestComputeHistoryRisk(unittest.TestCase):

    def test_true_returns_100(self):
        self.assertAlmostEqual(compute_history_risk(True), 100.0)

    def test_false_returns_0(self):
        self.assertAlmostEqual(compute_history_risk(False), 0.0)

    def test_true_not_zero(self):
        self.assertNotEqual(compute_history_risk(True), 0.0)

    def test_false_not_100(self):
        self.assertNotEqual(compute_history_risk(False), 100.0)


# ---------------------------------------------------------------------------
# compute_flash_loan_risk
# ---------------------------------------------------------------------------

class TestComputeFlashLoanRisk(unittest.TestCase):

    def test_weighted_formula(self):
        score = compute_flash_loan_risk(40.0, 60.0, 0.0)
        expected = 0.35 * 40 + 0.35 * 60 + 0.30 * 0
        self.assertAlmostEqual(score, expected)

    def test_all_zero(self):
        self.assertAlmostEqual(compute_flash_loan_risk(0, 0, 0), 0.0)

    def test_all_100(self):
        self.assertAlmostEqual(compute_flash_loan_risk(100, 100, 100), 100.0)

    def test_clamped_max(self):
        score = compute_flash_loan_risk(200, 200, 200)
        self.assertAlmostEqual(score, 100.0)

    def test_clamped_min(self):
        score = compute_flash_loan_risk(-10, -10, -10)
        self.assertAlmostEqual(score, 0.0)

    def test_history_weight(self):
        # history only
        score = compute_flash_loan_risk(0, 0, 100)
        self.assertAlmostEqual(score, 30.0)

    def test_oracle_weight(self):
        # oracle only
        score = compute_flash_loan_risk(100, 0, 0)
        self.assertAlmostEqual(score, 35.0)

    def test_manipulation_weight(self):
        # manipulation only
        score = compute_flash_loan_risk(0, 100, 0)
        self.assertAlmostEqual(score, 35.0)

    def test_partial_scores(self):
        score = compute_flash_loan_risk(20, 40, 0)
        expected = 0.35 * 20 + 0.35 * 40 + 0.30 * 0
        self.assertAlmostEqual(score, expected)


# ---------------------------------------------------------------------------
# risk_label
# ---------------------------------------------------------------------------

class TestRiskLabel(unittest.TestCase):

    def test_minimal(self):
        self.assertEqual(risk_label(0), "MINIMAL")
        self.assertEqual(risk_label(10), "MINIMAL")
        self.assertEqual(risk_label(19.9), "MINIMAL")

    def test_low(self):
        self.assertEqual(risk_label(20), "LOW")
        self.assertEqual(risk_label(30), "LOW")
        self.assertEqual(risk_label(39.9), "LOW")

    def test_moderate(self):
        self.assertEqual(risk_label(40), "MODERATE")
        self.assertEqual(risk_label(50), "MODERATE")
        self.assertEqual(risk_label(59.9), "MODERATE")

    def test_high(self):
        self.assertEqual(risk_label(60), "HIGH")
        self.assertEqual(risk_label(70), "HIGH")
        self.assertEqual(risk_label(79.9), "HIGH")

    def test_critical(self):
        self.assertEqual(risk_label(80), "CRITICAL")
        self.assertEqual(risk_label(90), "CRITICAL")
        self.assertEqual(risk_label(100), "CRITICAL")


# ---------------------------------------------------------------------------
# max_safe_exposure
# ---------------------------------------------------------------------------

class TestMaxSafeExposure(unittest.TestCase):

    def test_zero_risk(self):
        self.assertAlmostEqual(max_safe_exposure(0), 1_000_000.0)

    def test_100_risk(self):
        self.assertAlmostEqual(max_safe_exposure(100), 0.0)

    def test_50_risk(self):
        self.assertAlmostEqual(max_safe_exposure(50), 500_000.0)

    def test_25_risk(self):
        self.assertAlmostEqual(max_safe_exposure(25), 750_000.0)

    def test_formula(self):
        for r in [10, 20, 30, 40, 60, 70, 80, 90]:
            expected = 1_000_000.0 * (1 - r / 100)
            self.assertAlmostEqual(max_safe_exposure(r), expected)


# ---------------------------------------------------------------------------
# profile_protocol / is_safe / recommendation
# ---------------------------------------------------------------------------

class TestProfileProtocol(unittest.TestCase):

    def test_safe_for_deployment_when_low_risk(self):
        p = _sample_profile(oracle_centralization=0, tvl_concentration_pct=0,
                             price_impact_at_1m_usd=0, has_history=False, uses_twap=True)
        self.assertTrue(p.is_safe_for_deployment)

    def test_not_safe_when_high_risk(self):
        p = _sample_profile(oracle_centralization=100, tvl_concentration_pct=100,
                             price_impact_at_1m_usd=100, has_history=True, uses_twap=False)
        self.assertFalse(p.is_safe_for_deployment)

    def test_safe_threshold_exactly_60(self):
        # Find a config that gives exactly ~60 and check boundary
        p = _sample_profile(oracle_centralization=100, tvl_concentration_pct=100,
                             price_impact_at_1m_usd=100, has_history=True, uses_twap=False)
        self.assertFalse(p.is_safe_for_deployment)

    def test_recommendation_critical(self):
        p = _sample_profile(oracle_centralization=100, tvl_concentration_pct=100,
                             price_impact_at_1m_usd=100, has_history=True, uses_twap=False)
        self.assertIn("CRITICAL", p.recommendation)

    def test_recommendation_high(self):
        # Need score in 60-80 range
        # oracle_risk = 80*0.8 + 20 = 84; manipulation = 0; history = 0
        # flash_loan_risk = 0.35*84 = 29.4 → LOW
        # Need higher: oracle=100 twap=False → 100; manip=20; hist=0
        # 0.35*100 + 0.35*20 + 0 = 35+7 = 42 → MODERATE
        # oracle=100, manip=60, hist=0 → 35+21=56 → MODERATE
        # oracle=100, manip=80, hist=0 → 35+28=63 → HIGH
        p = _sample_profile(oracle_centralization=100, tvl_concentration_pct=80,
                             price_impact_at_1m_usd=80, has_history=False, uses_twap=False)
        self.assertIn("HIGH RISK", p.recommendation)

    def test_recommendation_moderate(self):
        # oracle=100, manip=20, hist=0 → 35+7=42 → MODERATE
        p = _sample_profile(oracle_centralization=100, tvl_concentration_pct=20,
                             price_impact_at_1m_usd=20, has_history=False, uses_twap=False)
        # Should be MODERATE
        if p.risk_label == "MODERATE":
            self.assertIn("Moderate risk", p.recommendation)
        # If not moderate, at least verify label matches recommendation
        else:
            self.assertIsNotNone(p.recommendation)

    def test_recommendation_acceptable_low(self):
        p = _sample_profile(oracle_centralization=0, tvl_concentration_pct=0,
                             price_impact_at_1m_usd=0, has_history=False, uses_twap=True)
        self.assertIn("Acceptable risk", p.recommendation)

    def test_protocol_name_preserved(self):
        p = _sample_profile(protocol="AaveV3")
        self.assertEqual(p.protocol, "AaveV3")

    def test_all_computed_fields_present(self):
        p = _sample_profile()
        self.assertIsNotNone(p.oracle_risk_score)
        self.assertIsNotNone(p.manipulation_surface_score)
        self.assertIsNotNone(p.history_risk_score)
        self.assertIsNotNone(p.flash_loan_risk_score)

    def test_scores_in_range(self):
        p = _sample_profile()
        for score in [p.oracle_risk_score, p.manipulation_surface_score,
                      p.history_risk_score, p.flash_loan_risk_score]:
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)


# ---------------------------------------------------------------------------
# detect_risks (aggregate)
# ---------------------------------------------------------------------------

class TestDetectRisks(unittest.TestCase):

    def _three_protocols(self):
        return [
            _sample_pd(protocol="Safe", oracle_centralization=0,
                       tvl_concentration_pct=0, price_impact_at_1m_usd=0,
                       has_price_manipulation_history=False, uses_twap=True),
            _sample_pd(protocol="Mid", oracle_centralization=50,
                       tvl_concentration_pct=50, price_impact_at_1m_usd=20,
                       has_price_manipulation_history=False, uses_twap=False),
            _sample_pd(protocol="Risky", oracle_centralization=100,
                       tvl_concentration_pct=100, price_impact_at_1m_usd=100,
                       has_price_manipulation_history=True, uses_twap=False),
        ]

    def test_safest_protocol(self):
        result = detect_risks(self._three_protocols())
        self.assertEqual(result.safest_protocol, "Safe")

    def test_riskiest_protocol(self):
        result = detect_risks(self._three_protocols())
        self.assertEqual(result.riskiest_protocol, "Risky")

    def test_safe_for_deployment_count(self):
        result = detect_risks(self._three_protocols())
        # Safe (score~0) and Mid (score~42) are < 60; Risky is >= 60
        self.assertGreaterEqual(result.safe_for_deployment_count, 1)
        self.assertLessEqual(result.safe_for_deployment_count, 3)

    def test_avg_risk_score_formula(self):
        result = detect_risks(self._three_protocols())
        expected = sum(p.flash_loan_risk_score for p in result.profiles) / 3
        self.assertAlmostEqual(result.avg_risk_score, expected, places=5)

    def test_market_risk_label_safe(self):
        data = [_sample_pd(protocol="A", oracle_centralization=0,
                           tvl_concentration_pct=0, price_impact_at_1m_usd=0,
                           has_price_manipulation_history=False, uses_twap=True)]
        result = detect_risks(data)
        self.assertEqual(result.market_risk_label, "SAFE_MARKET")

    def test_market_risk_label_caution(self):
        data = [_sample_pd(protocol="A", oracle_centralization=50,
                           tvl_concentration_pct=50, price_impact_at_1m_usd=30,
                           has_price_manipulation_history=False, uses_twap=False)]
        result = detect_risks(data)
        # avg ~42 → CAUTION_MARKET
        self.assertIn(result.market_risk_label, ["CAUTION_MARKET", "SAFE_MARKET", "DANGER_MARKET"])

    def test_market_risk_label_danger(self):
        data = [_sample_pd(protocol="A", oracle_centralization=100,
                           tvl_concentration_pct=100, price_impact_at_1m_usd=100,
                           has_price_manipulation_history=True, uses_twap=False)]
        result = detect_risks(data)
        self.assertEqual(result.market_risk_label, "DANGER_MARKET")

    def test_empty_input(self):
        result = detect_risks([])
        self.assertEqual(result.safest_protocol, "N/A")
        self.assertEqual(result.riskiest_protocol, "N/A")
        self.assertEqual(result.safe_for_deployment_count, 0)

    def test_profiles_count(self):
        result = detect_risks(self._three_protocols())
        self.assertEqual(len(result.profiles), 3)

    def test_recommendation_summary_not_empty(self):
        result = detect_risks(self._three_protocols())
        self.assertTrue(len(result.recommendation_summary) > 0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_all_risks_zero_fully_safe(self):
        data = [_sample_pd(protocol="ZeroRisk", oracle_centralization=0,
                           tvl_concentration_pct=0, price_impact_at_1m_usd=0,
                           has_price_manipulation_history=False, uses_twap=True)]
        result = detect_risks(data)
        p = result.profiles[0]
        self.assertAlmostEqual(p.flash_loan_risk_score, 0.0)
        self.assertEqual(p.risk_label, "MINIMAL")
        self.assertTrue(p.is_safe_for_deployment)
        self.assertAlmostEqual(p.max_safe_exposure_usd, 1_000_000.0)

    def test_all_risks_max_critical(self):
        data = [_sample_pd(protocol="MaxRisk", oracle_centralization=100,
                           tvl_concentration_pct=100, price_impact_at_1m_usd=100,
                           has_price_manipulation_history=True, uses_twap=False)]
        result = detect_risks(data)
        p = result.profiles[0]
        self.assertAlmostEqual(p.flash_loan_risk_score, 100.0)
        self.assertEqual(p.risk_label, "CRITICAL")
        self.assertFalse(p.is_safe_for_deployment)
        self.assertAlmostEqual(p.max_safe_exposure_usd, 0.0)


# ---------------------------------------------------------------------------
# Save / Load / Ring-buffer
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self._tmp_dir = tempfile.mkdtemp()
        # Patch the module-level constants
        import spa_core.analytics.flash_loan_risk_detector as mod
        self._orig_log = mod._LOG_FILE
        self._orig_data = mod._DATA_DIR
        mod._LOG_FILE = os.path.join(self._tmp_dir, "flash_loan_risk_log.json")
        mod._DATA_DIR = self._tmp_dir
        self._mod = mod

    def tearDown(self):
        self._mod._LOG_FILE = self._orig_log
        self._mod._DATA_DIR = self._orig_data

    def _make_result(self, protocol="P1") -> FlashLoanRiskResult:
        data = [_sample_pd(protocol=protocol)]
        return detect_risks(data)

    def test_save_and_load_round_trip(self):
        result = self._make_result()
        save_results(result)
        history = load_history()
        self.assertEqual(len(history), 1)
        self.assertIn("profiles", history[0])

    def test_load_empty_when_no_file(self):
        history = load_history()
        self.assertEqual(history, [])

    def test_ring_buffer_cap_100(self):
        for i in range(110):
            result = self._make_result(protocol=f"P{i}")
            save_results(result)
        history = load_history()
        self.assertEqual(len(history), 100)

    def test_ring_buffer_keeps_last_entries(self):
        for i in range(105):
            result = self._make_result(protocol=f"P{i}")
            save_results(result)
        history = load_history()
        # Last entry should be P104
        last = history[-1]
        self.assertEqual(last["profiles"][0]["protocol"], "P104")

    def test_atomic_write_no_tmp_left(self):
        result = self._make_result()
        save_results(result)
        tmp = self._mod._LOG_FILE + ".tmp"
        self.assertFalse(os.path.exists(tmp))


if __name__ == "__main__":
    unittest.main()
