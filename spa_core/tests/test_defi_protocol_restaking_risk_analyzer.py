"""
Tests for MP-1054: DeFiProtocolRestakingRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_restaking_risk_analyzer
"""

import json
import os
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from spa_core.analytics.defi_protocol_restaking_risk_analyzer import (
    DeFiProtocolRestakingRiskAnalyzer,
    _clamp,
    _saturation_score,
    _compute_slashing_risk_score,
    _compute_concentration_risk_score,
    _compute_composite_risk,
    _compute_label,
    _atomic_append_log,
    _LOG_CAP,
    _AVS_MAX_SCORE,
    _CONDITIONS_MAX_SCORE,
    _AUDIT_MAX_REDUCTION,
    _AGE_MAX_SCORE,
    _W_SLASHING,
    _W_CONCENTRATION,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_data(**overrides):
    """Return a baseline input dict."""
    base = {
        "protocol_name": "EigenLayer",
        "restaked_asset": "stETH",
        "avs_count": 8,
        "slashing_conditions": ["double-signing", "liveness"],
        "operator_concentration_pct": 45.0,
        "tvl_usd": 8_000_000_000.0,
        "base_staking_apy_pct": 3.8,
        "restaking_bonus_apy_pct": 2.1,
        "smart_contract_audits": 3,
        "days_since_launch": 400.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Helper functions: _clamp
# ---------------------------------------------------------------------------

class TestClamp(unittest.TestCase):
    def test_below_lo(self):
        self.assertEqual(_clamp(-10.0), 0.0)

    def test_above_hi(self):
        self.assertEqual(_clamp(200.0), 100.0)

    def test_inside_range(self):
        self.assertAlmostEqual(_clamp(50.0), 50.0)

    def test_at_lo(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_at_hi(self):
        self.assertEqual(_clamp(100.0), 100.0)

    def test_custom_bounds(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_custom_lo(self):
        self.assertEqual(_clamp(-1.0, 0.0, 10.0), 0.0)

    def test_custom_hi(self):
        self.assertEqual(_clamp(15.0, 0.0, 10.0), 10.0)


# ---------------------------------------------------------------------------
# 2. Helper functions: _saturation_score
# ---------------------------------------------------------------------------

class TestSaturationScore(unittest.TestCase):
    def test_zero_value(self):
        self.assertEqual(_saturation_score(0.0, 20.0, 40.0), 0.0)

    def test_at_saturation(self):
        self.assertAlmostEqual(_saturation_score(20.0, 20.0, 40.0), 40.0)

    def test_above_saturation_clamped(self):
        self.assertAlmostEqual(_saturation_score(30.0, 20.0, 40.0), 40.0)

    def test_mid_saturation(self):
        self.assertAlmostEqual(_saturation_score(10.0, 20.0, 40.0), 20.0)

    def test_quarter_saturation(self):
        self.assertAlmostEqual(_saturation_score(5.0, 20.0, 40.0), 10.0)

    def test_zero_saturation_nonzero_value(self):
        # saturation=0 → full score when value > 0
        self.assertAlmostEqual(_saturation_score(1.0, 0.0, 40.0), 40.0)

    def test_zero_saturation_zero_value(self):
        self.assertEqual(_saturation_score(0.0, 0.0, 40.0), 0.0)


# ---------------------------------------------------------------------------
# 3. Slashing risk score
# ---------------------------------------------------------------------------

class TestSlashingRiskScore(unittest.TestCase):
    def test_all_zero(self):
        # brand-new protocol (days=0) with no risk factors → age_component=10
        score = _compute_slashing_risk_score(0, [], 0, 0.0)
        self.assertAlmostEqual(score, 10.0)

    def test_mature_no_risk(self):
        # Well-audited, mature protocol, no avs, no conditions → near 0
        score = _compute_slashing_risk_score(0, [], 4, 365.0)
        self.assertAlmostEqual(score, 0.0)

    def test_max_avs_only(self):
        # avs_count at saturation (20), no conditions, mature, audited → 40-20 = 20
        score = _compute_slashing_risk_score(20, [], 4, 365.0)
        self.assertAlmostEqual(score, 20.0)

    def test_half_avs(self):
        # avs=10 → 20 pts; age=10 (brand new); audit=0
        score = _compute_slashing_risk_score(10, [], 0, 0.0)
        self.assertAlmostEqual(score, 30.0)  # 20 + 0 + 10 - 0 = 30

    def test_avs_saturates_above_20(self):
        score_at_20 = _compute_slashing_risk_score(20, [], 0, 0.0)
        score_at_40 = _compute_slashing_risk_score(40, [], 0, 0.0)
        self.assertAlmostEqual(score_at_20, score_at_40)

    def test_max_conditions_only(self):
        # 6 conditions = 30 pts; age=10 (brand new); no avs; no audit
        score = _compute_slashing_risk_score(0, ["a"] * 6, 0, 0.0)
        self.assertAlmostEqual(score, 40.0)  # 0 + 30 + 10 - 0 = 40

    def test_mid_conditions(self):
        # 3 conditions = 15 pts; brand new; no avs; no audit
        score = _compute_slashing_risk_score(0, ["a", "b", "c"], 0, 0.0)
        self.assertAlmostEqual(score, 25.0)  # 0 + 15 + 10 - 0 = 25

    def test_conditions_saturate_above_6(self):
        score_at_6 = _compute_slashing_risk_score(0, ["a"] * 6, 0, 0.0)
        score_at_10 = _compute_slashing_risk_score(0, ["a"] * 10, 0, 0.0)
        self.assertAlmostEqual(score_at_6, score_at_10)

    def test_empty_conditions(self):
        score = _compute_slashing_risk_score(0, [], 0, 365.0)
        self.assertAlmostEqual(score, 0.0)

    def test_max_audits_reduces(self):
        # 4 audits → -20 pts
        baseline = _compute_slashing_risk_score(10, [], 0, 0.0)
        audited = _compute_slashing_risk_score(10, [], 4, 0.0)
        self.assertAlmostEqual(baseline - audited, 20.0)

    def test_mid_audits_reduces(self):
        # 2 audits → -10 pts
        baseline = _compute_slashing_risk_score(10, [], 0, 0.0)
        audited = _compute_slashing_risk_score(10, [], 2, 0.0)
        self.assertAlmostEqual(baseline - audited, 10.0)

    def test_audit_saturation(self):
        # >4 audits same as 4
        score_4 = _compute_slashing_risk_score(10, [], 4, 365.0)
        score_8 = _compute_slashing_risk_score(10, [], 8, 365.0)
        self.assertAlmostEqual(score_4, score_8)

    def test_age_brand_new_adds_10(self):
        # days=0 adds 10 pts vs days=365 (adds 0)
        new_score = _compute_slashing_risk_score(0, [], 0, 0.0)
        old_score = _compute_slashing_risk_score(0, [], 0, 365.0)
        self.assertAlmostEqual(new_score - old_score, 10.0)

    def test_age_mature_adds_zero(self):
        score = _compute_slashing_risk_score(0, [], 0, 365.0)
        self.assertAlmostEqual(score, 0.0)

    def test_age_very_old_adds_zero(self):
        # Beyond 365 days → age_component = max(0, ...) = 0
        score_365 = _compute_slashing_risk_score(0, [], 0, 365.0)
        score_730 = _compute_slashing_risk_score(0, [], 0, 730.0)
        self.assertAlmostEqual(score_365, score_730)

    def test_all_max_no_audits(self):
        # avs=20(40) + cond=6(30) + age=0(0) + audit=0 → 70 (days=365 so age=0)
        score = _compute_slashing_risk_score(20, ["x"] * 6, 0, 365.0)
        self.assertAlmostEqual(score, 70.0)

    def test_all_max_brand_new_no_audits(self):
        # avs=20(40) + cond=6(30) + age=10 + audit=0 → 80
        score = _compute_slashing_risk_score(20, ["x"] * 6, 0, 0.0)
        self.assertAlmostEqual(score, 80.0)

    def test_all_max_with_audits(self):
        # avs=40 + cond=30 + age=10 - audit=20 = 60
        score = _compute_slashing_risk_score(20, ["x"] * 6, 4, 0.0)
        self.assertAlmostEqual(score, 60.0)

    def test_clamped_not_negative(self):
        # Lots of audits with minimal risk factors → clamped to 0
        score = _compute_slashing_risk_score(0, [], 4, 365.0)
        self.assertGreaterEqual(score, 0.0)

    def test_score_in_range(self):
        for avs in [0, 5, 20, 50]:
            for conds in [0, 3, 6]:
                for audits in [0, 2, 4]:
                    for days in [0, 180, 365]:
                        s = _compute_slashing_risk_score(
                            avs, ["x"] * conds, audits, days
                        )
                        self.assertGreaterEqual(s, 0.0)
                        self.assertLessEqual(s, 100.0)

    def test_combined_typical(self):
        # avs=10(20) + cond=3(15) + age@days=0(10) - audit=2(10) = 35
        score = _compute_slashing_risk_score(10, ["a", "b", "c"], 2, 0.0)
        self.assertAlmostEqual(score, 35.0)


# ---------------------------------------------------------------------------
# 4. Concentration risk score
# ---------------------------------------------------------------------------

class TestConcentrationRiskScore(unittest.TestCase):
    def test_zero_concentration_medium_tvl(self):
        # base=0; tvl=$100M → adj=0
        score = _compute_concentration_risk_score(0.0, 100_000_000.0)
        self.assertAlmostEqual(score, 0.0)

    def test_50pct_concentration_100M_tvl(self):
        # base=50*1.2=60; log10(100M)=8.0; adj=0 → 60
        score = _compute_concentration_risk_score(50.0, 100_000_000.0)
        self.assertAlmostEqual(score, 60.0)

    def test_50pct_concentration_10M_tvl(self):
        # base=60; log10(10M)=7.0; adj=(8-7)*5=5 → 65
        score = _compute_concentration_risk_score(50.0, 10_000_000.0)
        self.assertAlmostEqual(score, 65.0)

    def test_50pct_concentration_1B_tvl(self):
        # base=60; log10(1B)=9.0; adj=(8-9)*5=-5 → 55
        score = _compute_concentration_risk_score(50.0, 1_000_000_000.0)
        self.assertAlmostEqual(score, 55.0)

    def test_full_concentration_clamped(self):
        # base=100*1.2=120→clamped to 100; adj=0 (at $100M)
        score = _compute_concentration_risk_score(100.0, 100_000_000.0)
        self.assertAlmostEqual(score, 100.0)

    def test_zero_tvl_adds_penalty(self):
        # tvl=0 → tvl_adj=5; base=50*1.2=60 → score=65
        score = _compute_concentration_risk_score(50.0, 0.0)
        self.assertAlmostEqual(score, 65.0)

    def test_very_large_tvl_reduces_score(self):
        # High TVL (>$100M) reduces score vs $100M
        score_100M = _compute_concentration_risk_score(50.0, 100_000_000.0)
        score_1B = _compute_concentration_risk_score(50.0, 1_000_000_000.0)
        self.assertLess(score_1B, score_100M)

    def test_small_tvl_increases_score(self):
        # Small TVL (<$100M) increases score vs $100M
        score_100M = _compute_concentration_risk_score(50.0, 100_000_000.0)
        score_10M = _compute_concentration_risk_score(50.0, 10_000_000.0)
        self.assertGreater(score_10M, score_100M)

    def test_high_concentration_low_tvl(self):
        # 90% concentration + small TVL → very high score
        score = _compute_concentration_risk_score(90.0, 1_000_000.0)
        self.assertGreaterEqual(score, 90.0)

    def test_score_clamped_at_0(self):
        score = _compute_concentration_risk_score(0.0, 1_000_000_000_000.0)
        self.assertGreaterEqual(score, 0.0)

    def test_score_clamped_at_100(self):
        score = _compute_concentration_risk_score(100.0, 1.0)
        self.assertLessEqual(score, 100.0)

    def test_score_in_range(self):
        for conc in [0, 25, 50, 75, 100]:
            for tvl in [0, 1e6, 1e8, 1e10]:
                s = _compute_concentration_risk_score(float(conc), tvl)
                self.assertGreaterEqual(s, 0.0)
                self.assertLessEqual(s, 100.0)


# ---------------------------------------------------------------------------
# 5. Composite risk
# ---------------------------------------------------------------------------

class TestCompositeRisk(unittest.TestCase):
    def test_zero_zero(self):
        self.assertAlmostEqual(_compute_composite_risk(0.0, 0.0), 0.0)

    def test_equal_components(self):
        # 0.55*50 + 0.45*50 = 50
        self.assertAlmostEqual(_compute_composite_risk(50.0, 50.0), 50.0)

    def test_slashing_only(self):
        # 0.55*80 + 0.45*0 = 44
        self.assertAlmostEqual(_compute_composite_risk(80.0, 0.0), 44.0)

    def test_concentration_only(self):
        # 0.55*0 + 0.45*100 = 45
        self.assertAlmostEqual(_compute_composite_risk(0.0, 100.0), 45.0)

    def test_max_both(self):
        # 0.55*80 + 0.45*100 = 44+45 = 89
        self.assertAlmostEqual(_compute_composite_risk(80.0, 100.0), 89.0)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(_W_SLASHING + _W_CONCENTRATION, 1.0)

    def test_clamped_not_negative(self):
        result = _compute_composite_risk(-10.0, -10.0)
        self.assertGreaterEqual(result, 0.0)

    def test_clamped_at_100(self):
        result = _compute_composite_risk(200.0, 200.0)
        self.assertLessEqual(result, 100.0)

    def test_asymmetric_weights(self):
        # slashing has higher weight
        s_heavy = _compute_composite_risk(100.0, 0.0)
        c_heavy = _compute_composite_risk(0.0, 100.0)
        self.assertGreater(s_heavy, c_heavy)

    def test_typical_calculation(self):
        # slashing=40, concentration=60 → 0.55*40+0.45*60 = 22+27 = 49
        self.assertAlmostEqual(_compute_composite_risk(40.0, 60.0), 49.0)


# ---------------------------------------------------------------------------
# 6. Labels
# ---------------------------------------------------------------------------

class TestLabel(unittest.TestCase):
    def test_zero_is_conservative(self):
        self.assertEqual(_compute_label(0.0), "CONSERVATIVE_RESTAKING")

    def test_just_below_20_is_conservative(self):
        self.assertEqual(_compute_label(19.9), "CONSERVATIVE_RESTAKING")

    def test_at_20_is_balanced(self):
        self.assertEqual(_compute_label(20.0), "BALANCED_RESTAKING")

    def test_mid_balanced(self):
        self.assertEqual(_compute_label(30.0), "BALANCED_RESTAKING")

    def test_just_below_40_is_balanced(self):
        self.assertEqual(_compute_label(39.9), "BALANCED_RESTAKING")

    def test_at_40_is_elevated(self):
        self.assertEqual(_compute_label(40.0), "ELEVATED_RISK")

    def test_mid_elevated(self):
        self.assertEqual(_compute_label(50.0), "ELEVATED_RISK")

    def test_just_below_60_is_elevated(self):
        self.assertEqual(_compute_label(59.9), "ELEVATED_RISK")

    def test_at_60_is_high(self):
        self.assertEqual(_compute_label(60.0), "HIGH_RISK")

    def test_mid_high(self):
        self.assertEqual(_compute_label(70.0), "HIGH_RISK")

    def test_just_below_80_is_high(self):
        self.assertEqual(_compute_label(79.9), "HIGH_RISK")

    def test_at_80_is_avoid(self):
        self.assertEqual(_compute_label(80.0), "AVOID_RESTAKING")

    def test_100_is_avoid(self):
        self.assertEqual(_compute_label(100.0), "AVOID_RESTAKING")

    def test_all_labels_covered(self):
        expected = {
            "CONSERVATIVE_RESTAKING", "BALANCED_RESTAKING",
            "ELEVATED_RISK", "HIGH_RISK", "AVOID_RESTAKING"
        }
        produced = {
            _compute_label(5.0), _compute_label(25.0),
            _compute_label(45.0), _compute_label(65.0),
            _compute_label(85.0),
        }
        self.assertEqual(produced, expected)


# ---------------------------------------------------------------------------
# 7. analyze() method
# ---------------------------------------------------------------------------

class TestAnalyzeMethod(unittest.TestCase):
    def _make_analyzer(self):
        tmp = tempfile.mktemp(suffix=".json")
        return DeFiProtocolRestakingRiskAnalyzer(log_path=tmp), tmp

    def test_output_keys_present(self):
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(make_data(), write_log=False)
        expected_keys = {
            "protocol_name", "restaked_asset", "total_apy_pct",
            "slashing_risk_score", "concentration_risk_score",
            "restaking_composite_risk", "label", "analyzed_at",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_total_apy_sum(self):
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(
            make_data(base_staking_apy_pct=3.0, restaking_bonus_apy_pct=2.0),
            write_log=False,
        )
        self.assertAlmostEqual(result["total_apy_pct"], 5.0)

    def test_total_apy_zero(self):
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(
            make_data(base_staking_apy_pct=0.0, restaking_bonus_apy_pct=0.0),
            write_log=False,
        )
        self.assertAlmostEqual(result["total_apy_pct"], 0.0)

    def test_total_apy_large(self):
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(
            make_data(base_staking_apy_pct=15.0, restaking_bonus_apy_pct=10.0),
            write_log=False,
        )
        self.assertAlmostEqual(result["total_apy_pct"], 25.0)

    def test_protocol_name_echoed(self):
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(
            make_data(protocol_name="TestProtocol"), write_log=False
        )
        self.assertEqual(result["protocol_name"], "TestProtocol")

    def test_restaked_asset_echoed(self):
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(
            make_data(restaked_asset="ETH"), write_log=False
        )
        self.assertEqual(result["restaked_asset"], "ETH")

    def test_analyzed_at_present(self):
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(make_data(), write_log=False)
        self.assertIn("analyzed_at", result)
        self.assertIsInstance(result["analyzed_at"], str)
        self.assertGreater(len(result["analyzed_at"]), 10)

    def test_label_string(self):
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(make_data(), write_log=False)
        valid_labels = {
            "CONSERVATIVE_RESTAKING", "BALANCED_RESTAKING",
            "ELEVATED_RISK", "HIGH_RISK", "AVOID_RESTAKING",
        }
        self.assertIn(result["label"], valid_labels)

    def test_scores_in_range(self):
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(make_data(), write_log=False)
        for key in ("slashing_risk_score", "concentration_risk_score",
                    "restaking_composite_risk"):
            self.assertGreaterEqual(result[key], 0.0)
            self.assertLessEqual(result[key], 100.0)

    def test_conservative_restaking_scenario(self):
        # Mature, well-audited, low concentration, large TVL
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(
            make_data(
                avs_count=0,
                slashing_conditions=[],
                smart_contract_audits=4,
                days_since_launch=730.0,
                operator_concentration_pct=0.0,
                tvl_usd=10_000_000_000.0,
            ),
            write_log=False,
        )
        self.assertEqual(result["label"], "CONSERVATIVE_RESTAKING")

    def test_avoid_restaking_scenario(self):
        # Brand-new, no audits, max avs, max conditions, very concentrated, tiny TVL
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(
            make_data(
                avs_count=20,
                slashing_conditions=["a"] * 6,
                smart_contract_audits=0,
                days_since_launch=0.0,
                operator_concentration_pct=90.0,
                tvl_usd=10_000_000.0,
            ),
            write_log=False,
        )
        self.assertEqual(result["label"], "AVOID_RESTAKING")

    def test_elevated_risk_scenario(self):
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(
            make_data(
                avs_count=10,
                slashing_conditions=["a", "b", "c", "d"],
                smart_contract_audits=1,
                days_since_launch=180.0,
                operator_concentration_pct=45.0,
                tvl_usd=50_000_000.0,
            ),
            write_log=False,
        )
        self.assertIn(result["label"], ["ELEVATED_RISK", "HIGH_RISK"])

    def test_write_log_false_no_file(self):
        tmp = tempfile.mktemp(suffix=".json")
        analyzer = DeFiProtocolRestakingRiskAnalyzer(log_path=tmp)
        analyzer.analyze(make_data(), write_log=False)
        self.assertFalse(os.path.exists(tmp))

    def test_write_log_true_creates_file(self):
        tmp = tempfile.mktemp(suffix=".json")
        analyzer = DeFiProtocolRestakingRiskAnalyzer(log_path=tmp)
        try:
            analyzer.analyze(make_data(), write_log=True)
            self.assertTrue(os.path.exists(tmp))
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def test_empty_slashing_conditions(self):
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(
            make_data(slashing_conditions=[]), write_log=False
        )
        self.assertIn("slashing_risk_score", result)

    def test_many_slashing_conditions(self):
        analyzer, _ = self._make_analyzer()
        r_base = analyzer.analyze(
            make_data(slashing_conditions=["x"] * 6), write_log=False
        )
        r_many = analyzer.analyze(
            make_data(slashing_conditions=["x"] * 20), write_log=False
        )
        # Saturated — should be equal
        self.assertAlmostEqual(
            r_base["slashing_risk_score"], r_many["slashing_risk_score"]
        )

    def test_zero_tvl(self):
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(make_data(tvl_usd=0.0), write_log=False)
        self.assertIn("concentration_risk_score", result)
        self.assertGreaterEqual(result["concentration_risk_score"], 0.0)

    def test_type_coercion_numeric_strings(self):
        # avs_count given as float (int() should coerce)
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(
            make_data(avs_count=8, smart_contract_audits=2), write_log=False
        )
        self.assertIsInstance(result["total_apy_pct"], float)

    def test_composite_is_weighted_combination(self):
        analyzer, _ = self._make_analyzer()
        result = analyzer.analyze(make_data(), write_log=False)
        expected = round(
            _W_SLASHING * result["slashing_risk_score"]
            + _W_CONCENTRATION * result["concentration_risk_score"],
            4,
        )
        # Allow for minor floating-point differences due to clamping
        self.assertAlmostEqual(result["restaking_composite_risk"], expected, places=3)

    def test_more_avs_higher_slashing(self):
        analyzer, _ = self._make_analyzer()
        r_low = analyzer.analyze(make_data(avs_count=2), write_log=False)
        r_high = analyzer.analyze(make_data(avs_count=15), write_log=False)
        self.assertGreater(
            r_high["slashing_risk_score"], r_low["slashing_risk_score"]
        )

    def test_more_audits_lower_slashing(self):
        analyzer, _ = self._make_analyzer()
        r_unaudited = analyzer.analyze(
            make_data(smart_contract_audits=0, avs_count=10, days_since_launch=365.0),
            write_log=False,
        )
        r_audited = analyzer.analyze(
            make_data(smart_contract_audits=4, avs_count=10, days_since_launch=365.0),
            write_log=False,
        )
        self.assertLess(
            r_audited["slashing_risk_score"], r_unaudited["slashing_risk_score"]
        )

    def test_higher_concentration_higher_cr_score(self):
        analyzer, _ = self._make_analyzer()
        r_low = analyzer.analyze(
            make_data(operator_concentration_pct=10.0), write_log=False
        )
        r_high = analyzer.analyze(
            make_data(operator_concentration_pct=80.0), write_log=False
        )
        self.assertGreater(
            r_high["concentration_risk_score"], r_low["concentration_risk_score"]
        )


# ---------------------------------------------------------------------------
# 8. Log / ring-buffer behaviour
# ---------------------------------------------------------------------------

class TestLogBehaviour(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def test_log_creates_file(self):
        _atomic_append_log(self.tmp, {"x": 1})
        self.assertTrue(os.path.exists(self.tmp))

    def test_log_first_entry(self):
        _atomic_append_log(self.tmp, {"val": 42})
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["val"], 42)

    def test_log_appends_multiple(self):
        for i in range(5):
            _atomic_append_log(self.tmp, {"i": i})
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)
        self.assertEqual(data[-1]["i"], 4)

    def test_log_ring_buffer_cap(self):
        for i in range(_LOG_CAP + 10):
            _atomic_append_log(self.tmp, {"i": i}, cap=_LOG_CAP)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_CAP)

    def test_log_ring_buffer_keeps_latest(self):
        # Write cap+5 entries with custom cap=3
        for i in range(8):
            _atomic_append_log(self.tmp, {"i": i}, cap=3)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)
        self.assertEqual(data[-1]["i"], 7)  # most recent entry

    def test_log_invalid_json_resets(self):
        with open(self.tmp, "w") as f:
            f.write("NOT JSON")
        _atomic_append_log(self.tmp, {"x": 1})
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_non_list_json_resets(self):
        with open(self.tmp, "w") as f:
            json.dump({"not": "a list"}, f)
        _atomic_append_log(self.tmp, {"x": 1})
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_valid_json(self):
        _atomic_append_log(self.tmp, {"val": "test"})
        with open(self.tmp) as f:
            content = f.read()
        json.loads(content)  # must not raise

    def test_analyzer_writes_log(self):
        analyzer = DeFiProtocolRestakingRiskAnalyzer(log_path=self.tmp)
        analyzer.analyze(make_data(), write_log=True)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertIn("label", data[0])

    def test_analyzer_multiple_writes(self):
        analyzer = DeFiProtocolRestakingRiskAnalyzer(log_path=self.tmp)
        for _ in range(3):
            analyzer.analyze(make_data(), write_log=True)
        with open(self.tmp) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)


# ---------------------------------------------------------------------------
# 9. Static method API
# ---------------------------------------------------------------------------

class TestStaticMethods(unittest.TestCase):
    def test_static_slashing_risk_score(self):
        s = DeFiProtocolRestakingRiskAnalyzer.slashing_risk_score(
            avs_count=20, slashing_conditions=["x"] * 6,
            smart_contract_audits=0, days_since_launch=0.0,
        )
        self.assertAlmostEqual(s, 80.0)

    def test_static_concentration_risk_score(self):
        s = DeFiProtocolRestakingRiskAnalyzer.concentration_risk_score(
            operator_concentration_pct=50.0, tvl_usd=100_000_000.0
        )
        self.assertAlmostEqual(s, 60.0)

    def test_static_composite_risk(self):
        s = DeFiProtocolRestakingRiskAnalyzer.composite_risk(50.0, 50.0)
        self.assertAlmostEqual(s, 50.0)

    def test_static_label_for_conservative(self):
        self.assertEqual(
            DeFiProtocolRestakingRiskAnalyzer.label_for(10.0),
            "CONSERVATIVE_RESTAKING",
        )

    def test_static_label_for_avoid(self):
        self.assertEqual(
            DeFiProtocolRestakingRiskAnalyzer.label_for(89.0),
            "AVOID_RESTAKING",
        )


# ---------------------------------------------------------------------------
# 10. Integration / sensitivity
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    def _analyzer(self):
        return DeFiProtocolRestakingRiskAnalyzer(
            log_path=tempfile.mktemp(suffix=".json")
        )

    def test_sensitivity_avs_increases_risk(self):
        a = self._analyzer()
        r0 = a.analyze(make_data(avs_count=0), write_log=False)
        r20 = a.analyze(make_data(avs_count=20), write_log=False)
        self.assertGreater(r20["restaking_composite_risk"],
                           r0["restaking_composite_risk"])

    def test_sensitivity_concentration_increases_risk(self):
        a = self._analyzer()
        r0 = a.analyze(make_data(operator_concentration_pct=5.0), write_log=False)
        r90 = a.analyze(make_data(operator_concentration_pct=90.0), write_log=False)
        self.assertGreater(r90["restaking_composite_risk"],
                           r0["restaking_composite_risk"])

    def test_sensitivity_audits_lower_risk(self):
        a = self._analyzer()
        r0 = a.analyze(make_data(smart_contract_audits=0, days_since_launch=365.0,
                                  avs_count=10), write_log=False)
        r4 = a.analyze(make_data(smart_contract_audits=4, days_since_launch=365.0,
                                  avs_count=10), write_log=False)
        self.assertLess(r4["restaking_composite_risk"],
                        r0["restaking_composite_risk"])

    def test_sensitivity_days_since_launch(self):
        # New protocols have higher slashing risk (age_component > 0)
        a = self._analyzer()
        r_new = a.analyze(make_data(days_since_launch=0.0, avs_count=5,
                                     slashing_conditions=[]), write_log=False)
        r_old = a.analyze(make_data(days_since_launch=365.0, avs_count=5,
                                     slashing_conditions=[]), write_log=False)
        self.assertGreater(r_new["slashing_risk_score"],
                           r_old["slashing_risk_score"])

    def test_full_low_risk_protocol(self):
        a = self._analyzer()
        result = a.analyze(
            make_data(
                avs_count=1,
                slashing_conditions=["liveness"],
                smart_contract_audits=4,
                days_since_launch=500.0,
                operator_concentration_pct=15.0,
                tvl_usd=5_000_000_000.0,
                base_staking_apy_pct=3.5,
                restaking_bonus_apy_pct=1.0,
            ),
            write_log=False,
        )
        self.assertIn(result["label"],
                      ["CONSERVATIVE_RESTAKING", "BALANCED_RESTAKING"])
        self.assertAlmostEqual(result["total_apy_pct"], 4.5)

    def test_full_high_risk_protocol(self):
        a = self._analyzer()
        result = a.analyze(
            make_data(
                avs_count=18,
                slashing_conditions=["a", "b", "c", "d", "e"],
                smart_contract_audits=0,
                days_since_launch=30.0,
                operator_concentration_pct=75.0,
                tvl_usd=5_000_000.0,
            ),
            write_log=False,
        )
        self.assertIn(result["label"], ["HIGH_RISK", "AVOID_RESTAKING"])

    def test_result_is_deterministic(self):
        a = self._analyzer()
        data = make_data()
        r1 = a.analyze(data, write_log=False)
        r2 = a.analyze(data, write_log=False)
        self.assertEqual(r1["slashing_risk_score"], r2["slashing_risk_score"])
        self.assertEqual(r1["concentration_risk_score"],
                         r2["concentration_risk_score"])
        self.assertEqual(r1["label"], r2["label"])

    def test_bonus_apy_increases_total_apy(self):
        a = self._analyzer()
        r_no_bonus = a.analyze(
            make_data(base_staking_apy_pct=4.0, restaking_bonus_apy_pct=0.0),
            write_log=False,
        )
        r_with_bonus = a.analyze(
            make_data(base_staking_apy_pct=4.0, restaking_bonus_apy_pct=3.0),
            write_log=False,
        )
        self.assertAlmostEqual(r_with_bonus["total_apy_pct"],
                               r_no_bonus["total_apy_pct"] + 3.0)


if __name__ == "__main__":
    unittest.main()
