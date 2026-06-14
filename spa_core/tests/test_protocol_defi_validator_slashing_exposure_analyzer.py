"""
Tests for MP-1091 ProtocolDeFiValidatorSlashingExposureAnalyzer
Comprehensive pytest suite — pure stdlib, no third-party dependencies.
"""

import json
import math
import os
import sys
import tempfile
import time

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_defi_validator_slashing_exposure_analyzer import (
    analyze,
    analyze_portfolio,
    _restaking_amplification_factor,
    _expected_annual_slashing_loss_pct,
    _expected_annual_slashing_loss_usd,
    _worst_case_haircut_pct,
    _correlated_loss_contribution_pct,
    _effective_exposure_after_insurance_pct,
    _slashing_risk_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    ProtocolDeFiValidatorSlashingExposureAnalyzer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_MINIMAL,
    CLASS_LOW,
    CLASS_MODERATE,
    CLASS_HIGH,
    CLASS_SEVERE,
    FLAG_HIGH_OPERATOR_CONCENTRATION,
    FLAG_SINGLE_VALIDATOR,
    FLAG_HIGH_CORRELATED_RISK,
    FLAG_RESTAKING_AMPLIFIED,
    FLAG_UNINSURED,
    FLAG_LARGE_WORST_CASE_HAIRCUT,
    FLAG_WELL_DIVERSIFIED,
    FLAG_LOW_SLASHING_HISTORY,
    FLAG_INSUFFICIENT_DATA,
    _RESTAKING_LAYER_AMPLIFICATION,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _tmp_log():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _position(
    name="TestPosition",
    position_value_usd=1_000_000.0,
    num_validators=100.0,
    operator_concentration_pct=10.0,
    annual_downtime_slash_prob=0.01,
    annual_correlated_slash_prob=0.001,
    downtime_penalty_pct=0.1,
    correlated_penalty_pct=50.0,
    restaking_layers=0.0,
    insurance_coverage_pct=0.0,
    data_quality="ok",
):
    return {
        "name": name,
        "position_value_usd": position_value_usd,
        "num_validators": num_validators,
        "operator_concentration_pct": operator_concentration_pct,
        "annual_downtime_slash_prob": annual_downtime_slash_prob,
        "annual_correlated_slash_prob": annual_correlated_slash_prob,
        "downtime_penalty_pct": downtime_penalty_pct,
        "correlated_penalty_pct": correlated_penalty_pct,
        "restaking_layers": restaking_layers,
        "insurance_coverage_pct": insurance_coverage_pct,
        "data_quality": data_quality,
    }


def _severe(name="Severe"):
    """A position expected to classify as severe."""
    return _position(
        name=name,
        position_value_usd=1_000_000.0,
        num_validators=1.0,
        operator_concentration_pct=100.0,
        annual_downtime_slash_prob=0.05,
        annual_correlated_slash_prob=0.02,
        downtime_penalty_pct=0.5,
        correlated_penalty_pct=100.0,
        restaking_layers=4.0,
        insurance_coverage_pct=0.0,
    )


def _safe_position(name="Safe"):
    """A position expected to classify as minimal / low."""
    return _position(
        name=name,
        position_value_usd=1_000_000.0,
        num_validators=500.0,
        operator_concentration_pct=5.0,
        annual_downtime_slash_prob=0.001,
        annual_correlated_slash_prob=0.0001,
        downtime_penalty_pct=0.05,
        correlated_penalty_pct=30.0,
        restaking_layers=0.0,
        insurance_coverage_pct=80.0,
    )


def _cfg():
    return {"log_path": _tmp_log()}


# ===========================================================================
# 1. _restaking_amplification_factor
# ===========================================================================

class TestAmplification:
    def test_zero_layers_one(self):
        assert _restaking_amplification_factor(0.0) == pytest.approx(1.0)

    def test_one_layer(self):
        assert _restaking_amplification_factor(1.0) == pytest.approx(
            1.0 + _RESTAKING_LAYER_AMPLIFICATION)

    def test_more_layers_higher(self):
        assert _restaking_amplification_factor(4.0) > _restaking_amplification_factor(1.0)

    def test_negative_layers_one(self):
        assert _restaking_amplification_factor(-5.0) == pytest.approx(1.0)

    def test_always_at_least_one(self):
        for layers in [-10.0, 0.0, 1.0, 100.0]:
            assert _restaking_amplification_factor(layers) >= 1.0

    def test_returns_float(self):
        assert isinstance(_restaking_amplification_factor(2.0), float)


# ===========================================================================
# 2. _expected_annual_slashing_loss_pct
# ===========================================================================

class TestExpectedLossPct:
    def test_basic_math(self):
        # 0.01*0.1 + 0.001*50 = 0.001 + 0.05 = 0.051, x1
        r = _expected_annual_slashing_loss_pct(0.01, 0.1, 0.001, 50.0, 1.0)
        assert r == pytest.approx(0.051)

    def test_amplified(self):
        base = _expected_annual_slashing_loss_pct(0.01, 0.1, 0.001, 50.0, 1.0)
        amp = _expected_annual_slashing_loss_pct(0.01, 0.1, 0.001, 50.0, 2.0)
        assert amp == pytest.approx(base * 2.0)

    def test_zero_probs_zero(self):
        assert _expected_annual_slashing_loss_pct(0.0, 0.1, 0.0, 50.0, 1.0) == pytest.approx(0.0)

    def test_bounded_100(self):
        r = _expected_annual_slashing_loss_pct(1.0, 100.0, 1.0, 100.0, 5.0)
        assert r == pytest.approx(100.0)

    def test_probs_clamped(self):
        # prob > 1 clamped to 1
        r = _expected_annual_slashing_loss_pct(5.0, 1.0, 0.0, 0.0, 1.0)
        assert r == pytest.approx(1.0)

    def test_negative_penalty_floored(self):
        r = _expected_annual_slashing_loss_pct(0.5, -10.0, 0.0, 0.0, 1.0)
        assert r == pytest.approx(0.0)

    def test_amplification_min_one(self):
        # amplification < 1 treated as 1
        r = _expected_annual_slashing_loss_pct(0.01, 0.1, 0.0, 0.0, 0.5)
        assert r == pytest.approx(0.001)

    def test_higher_correlated_prob_higher_loss(self):
        low = _expected_annual_slashing_loss_pct(0.01, 0.1, 0.001, 50.0, 1.0)
        high = _expected_annual_slashing_loss_pct(0.01, 0.1, 0.02, 50.0, 1.0)
        assert high > low

    def test_bounded_0_100_always(self):
        for pd in [0.0, 0.5, 1.0]:
            for dp in [0.0, 50.0, 200.0]:
                for pc in [0.0, 0.5, 1.0]:
                    for cp in [0.0, 50.0, 200.0]:
                        r = _expected_annual_slashing_loss_pct(pd, dp, pc, cp, 1.0)
                        assert 0.0 <= r <= 100.0


# ===========================================================================
# 3. _expected_annual_slashing_loss_usd
# ===========================================================================

class TestExpectedLossUsd:
    def test_basic_math(self):
        # 5% of 1M = 50k
        assert _expected_annual_slashing_loss_usd(5.0, 1_000_000.0) == pytest.approx(50_000.0)

    def test_zero_value_zero(self):
        assert _expected_annual_slashing_loss_usd(5.0, 0.0) == 0.0

    def test_negative_value_zero(self):
        assert _expected_annual_slashing_loss_usd(5.0, -100.0) == 0.0

    def test_zero_pct_zero(self):
        assert _expected_annual_slashing_loss_usd(0.0, 1_000_000.0) == pytest.approx(0.0)

    def test_no_zero_division(self):
        _expected_annual_slashing_loss_usd(5.0, 0.0)

    def test_scales_with_value(self):
        small = _expected_annual_slashing_loss_usd(5.0, 100_000.0)
        big = _expected_annual_slashing_loss_usd(5.0, 1_000_000.0)
        assert big > small


# ===========================================================================
# 4. _worst_case_haircut_pct
# ===========================================================================

class TestWorstCase:
    def test_single_validator_full(self):
        # 1 validator, op 100% -> full correlated penalty
        r = _worst_case_haircut_pct(100.0, 100.0, 1.0, 1.0)
        assert r == pytest.approx(100.0)

    def test_diversified_smaller(self):
        conc = _worst_case_haircut_pct(100.0, 100.0, 1.0, 1.0)
        div = _worst_case_haircut_pct(100.0, 5.0, 100.0, 1.0)
        assert div < conc

    def test_operator_share_dominates(self):
        # op 50% with many validators -> 50% of penalty
        r = _worst_case_haircut_pct(100.0, 50.0, 100.0, 1.0)
        assert r == pytest.approx(50.0)

    def test_validator_frac_used_when_higher(self):
        # op 1%, 2 validators -> 1/2 = 50%
        r = _worst_case_haircut_pct(100.0, 1.0, 2.0, 1.0)
        assert r == pytest.approx(50.0)

    def test_zero_validators_full(self):
        # unknown validators -> fully concentrated
        r = _worst_case_haircut_pct(100.0, 0.0, 0.0, 1.0)
        assert r == pytest.approx(100.0)

    def test_amplification_increases(self):
        base = _worst_case_haircut_pct(40.0, 50.0, 100.0, 1.0)
        amp = _worst_case_haircut_pct(40.0, 50.0, 100.0, 2.0)
        assert amp >= base

    def test_bounded_0_100(self):
        for cp in [0.0, 50.0, 100.0, 200.0]:
            for op in [0.0, 50.0, 100.0]:
                for nv in [0.0, 1.0, 10.0, 1000.0]:
                    for amp in [1.0, 3.0]:
                        r = _worst_case_haircut_pct(cp, op, nv, amp)
                        assert 0.0 <= r <= 100.0

    def test_zero_penalty_zero(self):
        assert _worst_case_haircut_pct(0.0, 100.0, 1.0, 1.0) == pytest.approx(0.0)

    def test_no_zero_division_on_zero_validators(self):
        _worst_case_haircut_pct(100.0, 0.0, 0.0, 1.0)

    def test_higher_concentration_higher_haircut(self):
        low = _worst_case_haircut_pct(100.0, 10.0, 100.0, 1.0)
        high = _worst_case_haircut_pct(100.0, 80.0, 100.0, 1.0)
        assert high > low


# ===========================================================================
# 5. _correlated_loss_contribution_pct
# ===========================================================================

class TestCorrelatedContribution:
    def test_basic_math(self):
        # corr 0.001*50=0.05, down 0.01*0.1=0.001, share=0.05/0.051
        r = _correlated_loss_contribution_pct(0.001, 50.0, 0.01, 0.1)
        assert r == pytest.approx(0.05 / 0.051 * 100.0)

    def test_all_correlated_100(self):
        r = _correlated_loss_contribution_pct(0.01, 50.0, 0.0, 0.0)
        assert r == pytest.approx(100.0)

    def test_all_downtime_0(self):
        r = _correlated_loss_contribution_pct(0.0, 50.0, 0.01, 0.1)
        assert r == pytest.approx(0.0)

    def test_zero_zero_returns_zero(self):
        assert _correlated_loss_contribution_pct(0.0, 0.0, 0.0, 0.0) == 0.0

    def test_no_zero_division(self):
        _correlated_loss_contribution_pct(0.0, 0.0, 0.0, 0.0)

    def test_bounded_0_100(self):
        for pc in [0.0, 0.01, 1.0]:
            for cp in [0.0, 50.0, 100.0]:
                for pd in [0.0, 0.01, 1.0]:
                    for dp in [0.0, 0.1, 50.0]:
                        r = _correlated_loss_contribution_pct(pc, cp, pd, dp)
                        assert 0.0 <= r <= 100.0

    def test_higher_correlated_higher_share(self):
        low = _correlated_loss_contribution_pct(0.001, 50.0, 0.05, 1.0)
        high = _correlated_loss_contribution_pct(0.02, 50.0, 0.05, 1.0)
        assert high > low


# ===========================================================================
# 6. _effective_exposure_after_insurance_pct
# ===========================================================================

class TestEffectiveExposure:
    def test_no_insurance_unchanged(self):
        assert _effective_exposure_after_insurance_pct(5.0, 0.0) == pytest.approx(5.0)

    def test_full_insurance_zero(self):
        assert _effective_exposure_after_insurance_pct(5.0, 100.0) == pytest.approx(0.0)

    def test_half_insurance(self):
        assert _effective_exposure_after_insurance_pct(5.0, 50.0) == pytest.approx(2.5)

    def test_insurance_clamped_above_100(self):
        assert _effective_exposure_after_insurance_pct(5.0, 150.0) == pytest.approx(0.0)

    def test_negative_insurance_clamped(self):
        assert _effective_exposure_after_insurance_pct(5.0, -50.0) == pytest.approx(5.0)

    def test_never_negative(self):
        for loss in [0.0, 5.0, 100.0]:
            for ins in [-50.0, 0.0, 50.0, 200.0]:
                assert _effective_exposure_after_insurance_pct(loss, ins) >= 0.0

    def test_more_insurance_less_exposure(self):
        low = _effective_exposure_after_insurance_pct(5.0, 20.0)
        high = _effective_exposure_after_insurance_pct(5.0, 80.0)
        assert high < low


# ===========================================================================
# 7. _slashing_risk_score
# ===========================================================================

class TestRiskScore:
    def test_no_data_zero(self):
        s = _slashing_risk_score(5.0, 100.0, 100.0, 100.0, 5.0, has_data=False)
        assert s == 0.0

    def test_max_risk(self):
        s = _slashing_risk_score(100.0, 100.0, 100.0, 100.0, 100.0, has_data=True)
        assert s == pytest.approx(100.0)

    def test_min_risk(self):
        s = _slashing_risk_score(0.0, 0.0, 0.0, 0.0, 0.0, has_data=True)
        assert s == pytest.approx(0.0)

    def test_bounded_0_100(self):
        for loss in [0.0, 50.0, 100.0]:
            for hc in [0.0, 50.0, 100.0]:
                for op in [0.0, 50.0, 100.0]:
                    for tail in [0.0, 50.0, 100.0]:
                        for eff in [0.0, 5.0, 50.0]:
                            s = _slashing_risk_score(loss, hc, op, tail, eff,
                                                     has_data=True)
                            assert 0.0 <= s <= 100.0

    def test_higher_haircut_higher_risk(self):
        low = _slashing_risk_score(1.0, 10.0, 20.0, 20.0, 1.0, has_data=True)
        high = _slashing_risk_score(1.0, 90.0, 20.0, 20.0, 1.0, has_data=True)
        assert high > low

    def test_higher_concentration_higher_risk(self):
        low = _slashing_risk_score(1.0, 30.0, 10.0, 20.0, 1.0, has_data=True)
        high = _slashing_risk_score(1.0, 30.0, 90.0, 20.0, 1.0, has_data=True)
        assert high > low

    def test_higher_exposure_higher_risk(self):
        low = _slashing_risk_score(1.0, 30.0, 20.0, 20.0, 0.5, has_data=True)
        high = _slashing_risk_score(5.0, 30.0, 20.0, 20.0, 5.0, has_data=True)
        assert high > low

    def test_higher_tail_higher_risk(self):
        low = _slashing_risk_score(1.0, 30.0, 20.0, 10.0, 1.0, has_data=True)
        high = _slashing_risk_score(1.0, 30.0, 20.0, 90.0, 1.0, has_data=True)
        assert high > low


# ===========================================================================
# 8. _classify
# ===========================================================================

class TestClassify:
    def test_no_data_minimal(self):
        assert _classify(90.0, has_data=False) == CLASS_MINIMAL

    def test_minimal(self):
        assert _classify(10.0, has_data=True) == CLASS_MINIMAL

    def test_low(self):
        assert _classify(25.0, has_data=True) == CLASS_LOW

    def test_moderate(self):
        assert _classify(45.0, has_data=True) == CLASS_MODERATE

    def test_high(self):
        assert _classify(65.0, has_data=True) == CLASS_HIGH

    def test_severe(self):
        assert _classify(85.0, has_data=True) == CLASS_SEVERE

    def test_all_bands_reachable(self):
        seen = {
            _classify(10.0, has_data=True),
            _classify(25.0, has_data=True),
            _classify(45.0, has_data=True),
            _classify(65.0, has_data=True),
            _classify(85.0, has_data=True),
        }
        assert seen == set(ALL_CLASSIFICATIONS)

    def test_returns_valid_classification(self):
        for s in [0, 15, 35, 55, 75, 100]:
            assert _classify(s, has_data=True) in ALL_CLASSIFICATIONS

    def test_boundary_15(self):
        assert _classify(14.99, has_data=True) == CLASS_MINIMAL
        assert _classify(15.0, has_data=True) == CLASS_LOW

    def test_boundary_35(self):
        assert _classify(34.99, has_data=True) == CLASS_LOW
        assert _classify(35.0, has_data=True) == CLASS_MODERATE

    def test_boundary_55(self):
        assert _classify(54.99, has_data=True) == CLASS_MODERATE
        assert _classify(55.0, has_data=True) == CLASS_HIGH

    def test_boundary_75(self):
        assert _classify(74.99, has_data=True) == CLASS_HIGH
        assert _classify(75.0, has_data=True) == CLASS_SEVERE


# ===========================================================================
# 9. _grade
# ===========================================================================

class TestGrade:
    def test_a(self):
        assert _grade(5.0) == "A"
        assert _grade(0.0) == "A"

    def test_b(self):
        assert _grade(20.0) == "B"

    def test_c(self):
        assert _grade(40.0) == "C"

    def test_d(self):
        assert _grade(60.0) == "D"

    def test_f(self):
        assert _grade(80.0) == "F"
        assert _grade(100.0) == "F"

    def test_boundaries(self):
        assert _grade(9.99) == "A"
        assert _grade(10.0) == "B"
        assert _grade(29.99) == "B"
        assert _grade(30.0) == "C"
        assert _grade(49.99) == "C"
        assert _grade(50.0) == "D"
        assert _grade(69.99) == "D"
        assert _grade(70.0) == "F"

    def test_monotonic(self):
        rank = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}
        grades = [_grade(s) for s in range(0, 101, 5)]
        for i in range(len(grades) - 1):
            assert rank[grades[i]] <= rank[grades[i + 1]]

    def test_all_grades_reachable(self):
        seen = {_grade(s) for s in [0, 20, 40, 60, 90]}
        assert seen == {"A", "B", "C", "D", "F"}

    def test_all_grades_constant(self):
        assert set(ALL_GRADES) == {"A", "B", "C", "D", "F"}


# ===========================================================================
# 10. _flags
# ===========================================================================

class TestFlags:
    def test_insufficient_data_only(self):
        f = _flags(100.0, 1.0, 0.02, 2.4, 0.0, 100.0, 0.05, has_data=False)
        assert f == [FLAG_INSUFFICIENT_DATA]

    def test_high_operator_concentration(self):
        f = _flags(60.0, 100.0, 0.001, 1.0, 0.0, 10.0, 0.01, has_data=True)
        assert FLAG_HIGH_OPERATOR_CONCENTRATION in f

    def test_low_concentration_no_flag(self):
        f = _flags(10.0, 100.0, 0.001, 1.0, 0.0, 10.0, 0.01, has_data=True)
        assert FLAG_HIGH_OPERATOR_CONCENTRATION not in f

    def test_single_validator(self):
        f = _flags(100.0, 1.0, 0.001, 1.0, 0.0, 10.0, 0.01, has_data=True)
        assert FLAG_SINGLE_VALIDATOR in f

    def test_many_validators_no_single_flag(self):
        f = _flags(10.0, 100.0, 0.001, 1.0, 0.0, 10.0, 0.01, has_data=True)
        assert FLAG_SINGLE_VALIDATOR not in f

    def test_zero_validators_no_single_flag(self):
        # 0 validators is "unknown", not flagged as single
        f = _flags(10.0, 0.0, 0.001, 1.0, 0.0, 10.0, 0.01, has_data=True)
        assert FLAG_SINGLE_VALIDATOR not in f

    def test_high_correlated_risk(self):
        f = _flags(10.0, 100.0, 0.02, 1.0, 0.0, 10.0, 0.01, has_data=True)
        assert FLAG_HIGH_CORRELATED_RISK in f

    def test_low_correlated_no_flag(self):
        f = _flags(10.0, 100.0, 0.0001, 1.0, 0.0, 10.0, 0.01, has_data=True)
        assert FLAG_HIGH_CORRELATED_RISK not in f

    def test_restaking_amplified(self):
        f = _flags(10.0, 100.0, 0.001, 2.4, 0.0, 10.0, 0.01, has_data=True)
        assert FLAG_RESTAKING_AMPLIFIED in f

    def test_no_restaking_no_flag(self):
        f = _flags(10.0, 100.0, 0.001, 1.0, 0.0, 10.0, 0.01, has_data=True)
        assert FLAG_RESTAKING_AMPLIFIED not in f

    def test_uninsured(self):
        f = _flags(10.0, 100.0, 0.001, 1.0, 0.0, 10.0, 0.01, has_data=True)
        assert FLAG_UNINSURED in f

    def test_insured_no_flag(self):
        f = _flags(10.0, 100.0, 0.001, 1.0, 50.0, 10.0, 0.01, has_data=True)
        assert FLAG_UNINSURED not in f

    def test_large_worst_case_haircut(self):
        f = _flags(10.0, 100.0, 0.001, 1.0, 0.0, 50.0, 0.01, has_data=True)
        assert FLAG_LARGE_WORST_CASE_HAIRCUT in f

    def test_small_haircut_no_flag(self):
        f = _flags(10.0, 100.0, 0.001, 1.0, 0.0, 5.0, 0.01, has_data=True)
        assert FLAG_LARGE_WORST_CASE_HAIRCUT not in f

    def test_well_diversified(self):
        f = _flags(15.0, 50.0, 0.001, 1.0, 50.0, 5.0, 0.001, has_data=True)
        assert FLAG_WELL_DIVERSIFIED in f

    def test_concentrated_no_diversified_flag(self):
        f = _flags(60.0, 50.0, 0.001, 1.0, 50.0, 5.0, 0.001, has_data=True)
        assert FLAG_WELL_DIVERSIFIED not in f

    def test_few_validators_no_diversified_flag(self):
        f = _flags(15.0, 5.0, 0.001, 1.0, 50.0, 5.0, 0.001, has_data=True)
        assert FLAG_WELL_DIVERSIFIED not in f

    def test_low_slashing_history(self):
        f = _flags(10.0, 100.0, 0.0001, 1.0, 0.0, 5.0, 0.0001, has_data=True)
        assert FLAG_LOW_SLASHING_HISTORY in f

    def test_high_slashing_no_low_history_flag(self):
        f = _flags(10.0, 100.0, 0.02, 1.0, 0.0, 5.0, 0.05, has_data=True)
        assert FLAG_LOW_SLASHING_HISTORY not in f

    def test_all_flags_valid(self):
        f = _flags(60.0, 1.0, 0.02, 2.4, 0.0, 50.0, 0.05, has_data=True)
        for flag in f:
            assert flag in ALL_FLAGS


# ===========================================================================
# 11. _recommendations
# ===========================================================================

class TestRecommendations:
    def test_insufficient_data(self):
        recs = _recommendations(
            CLASS_MINIMAL, [FLAG_INSUFFICIENT_DATA], 0.0, 0.0, 0.0, 0.0, 1.0,
            has_data=False,
        )
        assert len(recs) >= 1
        assert any("insufficient" in r.lower() for r in recs)

    def test_severe_mentions(self):
        recs = _recommendations(
            CLASS_SEVERE, [], 5.0, 100.0, 99.0, 5.0, 2.4, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "severe" in combined

    def test_returns_list_for_each_class(self):
        for c in ALL_CLASSIFICATIONS:
            recs = _recommendations(
                c, [], 1.0, 30.0, 50.0, 1.0, 1.0, has_data=True,
            )
            assert isinstance(recs, list)
            assert len(recs) >= 1

    def test_high_concentration_mentioned(self):
        recs = _recommendations(
            CLASS_HIGH, [FLAG_HIGH_OPERATOR_CONCENTRATION],
            2.0, 60.0, 50.0, 2.0, 1.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "operator" in combined or "concentration" in combined

    def test_single_validator_mentioned(self):
        recs = _recommendations(
            CLASS_HIGH, [FLAG_SINGLE_VALIDATOR],
            2.0, 60.0, 50.0, 2.0, 1.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "single validator" in combined or "one validator" in combined

    def test_correlated_mentioned(self):
        recs = _recommendations(
            CLASS_HIGH, [FLAG_HIGH_CORRELATED_RISK],
            2.0, 60.0, 80.0, 2.0, 1.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "correlated" in combined or "double-sign" in combined

    def test_restaking_mentioned(self):
        recs = _recommendations(
            CLASS_HIGH, [FLAG_RESTAKING_AMPLIFIED],
            2.0, 60.0, 50.0, 2.0, 2.4, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "restaking" in combined or "avs" in combined

    def test_uninsured_mentioned(self):
        recs = _recommendations(
            CLASS_MODERATE, [FLAG_UNINSURED],
            2.0, 30.0, 50.0, 2.0, 1.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "uninsured" in combined or "coverage" in combined

    def test_large_haircut_mentioned(self):
        recs = _recommendations(
            CLASS_HIGH, [FLAG_LARGE_WORST_CASE_HAIRCUT],
            2.0, 60.0, 50.0, 2.0, 1.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "haircut" in combined

    def test_well_diversified_mentioned(self):
        recs = _recommendations(
            CLASS_MINIMAL, [FLAG_WELL_DIVERSIFIED],
            0.5, 5.0, 20.0, 0.5, 1.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "diversified" in combined

    def test_low_history_mentioned(self):
        recs = _recommendations(
            CLASS_MINIMAL, [FLAG_LOW_SLASHING_HISTORY],
            0.5, 5.0, 20.0, 0.5, 1.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "low" in combined or "history" in combined or "fault rate" in combined


# ===========================================================================
# 12. _atomic_log
# ===========================================================================

class TestAtomicLog:
    def test_creates_file(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 42})
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert data[0]["x"] == 42
        os.unlink(path)

    def test_appends_multiple(self):
        path = _tmp_log()
        _atomic_log(path, {"n": 1})
        _atomic_log(path, {"n": 2})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 2
        os.unlink(path)

    def test_ring_buffer_cap_100(self):
        path = _tmp_log()
        for i in range(110):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 100
        assert data[-1]["i"] == 109
        assert data[0]["i"] == 10
        os.unlink(path)

    def test_recovers_from_corrupt(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("{INVALID")
        _atomic_log(path, {"ok": True})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 1
        os.unlink(path)

    def test_creates_parent_dirs(self):
        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "a", "b", "log.json")
        _atomic_log(path, {"deep": True})
        assert os.path.exists(path)

    def test_produces_valid_json(self):
        path = _tmp_log()
        for i in range(5):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        os.unlink(path)


# ===========================================================================
# 13. _safe_float / _clamp
# ===========================================================================

class TestHelpers:
    def test_safe_float_number(self):
        assert _safe_float(5.0) == 5.0

    def test_safe_float_string(self):
        assert _safe_float("10") == 10.0

    def test_safe_float_invalid(self):
        assert _safe_float("abc") == 0.0

    def test_safe_float_none(self):
        assert _safe_float(None) == 0.0

    def test_safe_float_custom_default(self):
        assert _safe_float("x", default=5.0) == 5.0

    def test_clamp_within(self):
        assert _clamp(5.0, 0.0, 10.0) == 5.0

    def test_clamp_below(self):
        assert _clamp(-5.0, 0.0, 10.0) == 0.0

    def test_clamp_above(self):
        assert _clamp(150.0) == 100.0

    def test_clamp_default_range(self):
        assert _clamp(50.0) == 50.0


# ===========================================================================
# 14. analyze — integration
# ===========================================================================

class TestAnalyze:
    def test_returns_dict(self):
        r = analyze(_position(), config=_cfg())
        assert isinstance(r, dict)

    def test_required_keys(self):
        r = analyze(_position(), config=_cfg())
        for key in [
            "name",
            "expected_annual_slashing_loss_pct",
            "expected_annual_slashing_loss_usd",
            "worst_case_haircut_pct",
            "correlated_loss_contribution_pct",
            "restaking_amplification_factor",
            "effective_exposure_after_insurance_pct",
            "slashing_risk_score",
            "classification",
            "grade",
            "flags",
            "recommendations",
            "timestamp",
        ]:
            assert key in r

    def test_expected_loss_math(self):
        r = analyze(_position(annual_downtime_slash_prob=0.01,
                              downtime_penalty_pct=0.1,
                              annual_correlated_slash_prob=0.001,
                              correlated_penalty_pct=50.0,
                              restaking_layers=0.0), config=_cfg())
        assert r["expected_annual_slashing_loss_pct"] == pytest.approx(0.051)

    def test_expected_loss_usd_math(self):
        r = analyze(_position(annual_downtime_slash_prob=0.0,
                              downtime_penalty_pct=0.0,
                              annual_correlated_slash_prob=0.1,
                              correlated_penalty_pct=50.0,
                              position_value_usd=1_000_000.0,
                              restaking_layers=0.0), config=_cfg())
        # 5% of 1M = 50k
        assert r["expected_annual_slashing_loss_usd"] == pytest.approx(50_000.0)

    def test_amplification_math(self):
        r = analyze(_position(restaking_layers=2.0), config=_cfg())
        assert r["restaking_amplification_factor"] == pytest.approx(
            1.0 + 2.0 * _RESTAKING_LAYER_AMPLIFICATION)

    def test_classification_valid(self):
        r = analyze(_position(), config=_cfg())
        assert r["classification"] in ALL_CLASSIFICATIONS

    def test_grade_valid(self):
        r = analyze(_position(), config=_cfg())
        assert r["grade"] in ALL_GRADES

    def test_severe_scenario(self):
        r = analyze(_severe(), config=_cfg())
        assert r["classification"] == CLASS_SEVERE
        assert FLAG_SINGLE_VALIDATOR in r["flags"]

    def test_safe_scenario(self):
        r = analyze(_safe_position(), config=_cfg())
        assert r["classification"] in (CLASS_MINIMAL, CLASS_LOW)

    def test_high_operator_concentration_flag(self):
        r = analyze(_position(operator_concentration_pct=60.0), config=_cfg())
        assert FLAG_HIGH_OPERATOR_CONCENTRATION in r["flags"]

    def test_single_validator_flag(self):
        r = analyze(_position(num_validators=1.0), config=_cfg())
        assert FLAG_SINGLE_VALIDATOR in r["flags"]

    def test_high_correlated_flag(self):
        r = analyze(_position(annual_correlated_slash_prob=0.02), config=_cfg())
        assert FLAG_HIGH_CORRELATED_RISK in r["flags"]

    def test_restaking_amplified_flag(self):
        r = analyze(_position(restaking_layers=3.0), config=_cfg())
        assert FLAG_RESTAKING_AMPLIFIED in r["flags"]

    def test_uninsured_flag(self):
        r = analyze(_position(insurance_coverage_pct=0.0), config=_cfg())
        assert FLAG_UNINSURED in r["flags"]

    def test_large_worst_case_flag(self):
        r = analyze(_position(num_validators=1.0, operator_concentration_pct=100.0,
                              correlated_penalty_pct=100.0), config=_cfg())
        assert FLAG_LARGE_WORST_CASE_HAIRCUT in r["flags"]

    def test_well_diversified_flag(self):
        r = analyze(_position(num_validators=100.0, operator_concentration_pct=10.0),
                    config=_cfg())
        assert FLAG_WELL_DIVERSIFIED in r["flags"]

    def test_low_slashing_history_flag(self):
        r = analyze(_position(annual_downtime_slash_prob=0.0001,
                              annual_correlated_slash_prob=0.0001), config=_cfg())
        assert FLAG_LOW_SLASHING_HISTORY in r["flags"]

    def test_insufficient_data_flag(self):
        r = analyze(_position(position_value_usd=0.0), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]
        assert r["classification"] == CLASS_MINIMAL

    def test_no_signal_insufficient(self):
        r = analyze(_position(annual_downtime_slash_prob=0.0,
                              annual_correlated_slash_prob=0.0,
                              downtime_penalty_pct=0.0,
                              correlated_penalty_pct=0.0), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]

    def test_poor_data_quality_insufficient(self):
        r = analyze(_position(data_quality="poor"), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]

    def test_name_preserved(self):
        r = analyze(_position(name="stETH"), config=_cfg())
        assert r["name"] == "stETH"

    def test_recommendations_is_list(self):
        r = analyze(_position(), config=_cfg())
        assert isinstance(r["recommendations"], list)
        assert len(r["recommendations"]) >= 1

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_position(), config=_cfg())
        after = time.time()
        assert before <= r["timestamp"] <= after

    def test_flags_valid(self):
        r = analyze(_severe(), config=_cfg())
        for flag in r["flags"]:
            assert flag in ALL_FLAGS

    def test_risk_bounded(self):
        r = analyze(_position(), config=_cfg())
        assert 0.0 <= r["slashing_risk_score"] <= 100.0

    def test_expected_loss_bounded(self):
        r = analyze(_severe(), config=_cfg())
        assert 0.0 <= r["expected_annual_slashing_loss_pct"] <= 100.0

    def test_worst_case_bounded(self):
        r = analyze(_severe(), config=_cfg())
        assert 0.0 <= r["worst_case_haircut_pct"] <= 100.0

    def test_kwargs_override_dict(self):
        r = analyze(_position(position_value_usd=1_000_000.0),
                    position_value_usd=2_000_000.0, config=_cfg())
        assert r["position_value_usd"] == 2_000_000.0

    def test_kwargs_only(self):
        r = analyze(position_value_usd=1_000_000.0,
                    annual_correlated_slash_prob=0.1,
                    correlated_penalty_pct=50.0, config=_cfg())
        assert r["expected_annual_slashing_loss_usd"] == pytest.approx(50_000.0)

    def test_operator_concentration_clamped(self):
        r = analyze(_position(operator_concentration_pct=150.0), config=_cfg())
        assert r["operator_concentration_pct"] == 100.0

    def test_insurance_clamped(self):
        r = analyze(_position(insurance_coverage_pct=150.0), config=_cfg())
        assert r["insurance_coverage_pct"] == 100.0


# ===========================================================================
# 15. analyze — robustness / no crash
# ===========================================================================

class TestAnalyzeRobustness:
    def test_empty_dict(self):
        r = analyze({}, config=_cfg())
        assert "classification" in r
        assert FLAG_INSUFFICIENT_DATA in r["flags"]

    def test_none_input(self):
        r = analyze(None, config=_cfg())
        assert "classification" in r

    def test_missing_keys(self):
        r = analyze({"name": "X"}, config=_cfg())
        assert r["name"] == "X"
        assert "grade" in r

    def test_string_numeric_fields(self):
        r = analyze({"name": "X", "position_value_usd": "1000000",
                     "annual_correlated_slash_prob": "0.1",
                     "correlated_penalty_pct": "50"}, config=_cfg())
        assert r["expected_annual_slashing_loss_usd"] == pytest.approx(50_000.0)

    def test_garbage_numeric_fields(self):
        r = analyze({"name": "X", "position_value_usd": "abc",
                     "correlated_penalty_pct": None}, config=_cfg())
        assert "classification" in r

    def test_no_zero_division_all_zeros(self):
        r = analyze(_position(position_value_usd=0.0, num_validators=0.0,
                              operator_concentration_pct=0.0,
                              annual_downtime_slash_prob=0.0,
                              annual_correlated_slash_prob=0.0,
                              downtime_penalty_pct=0.0,
                              correlated_penalty_pct=0.0,
                              restaking_layers=0.0,
                              insurance_coverage_pct=0.0), config=_cfg())
        assert "classification" in r

    def test_zero_validators_no_crash(self):
        r = analyze(_position(num_validators=0.0), config=_cfg())
        assert "classification" in r

    def test_negative_position_clamped(self):
        r = analyze(_position(position_value_usd=-1e6), config=_cfg())
        assert r["position_value_usd"] == 0.0

    def test_negative_penalty_clamped(self):
        r = analyze(_position(correlated_penalty_pct=-50.0), config=_cfg())
        assert r["correlated_penalty_pct"] == 0.0

    def test_does_not_raise_on_bad_log_path(self):
        r = analyze(_position(), config={"log_path": "/dev/null/cannot/log.json"})
        assert "classification" in r

    def test_default_log_path_used(self):
        r = analyze(_position())
        assert "classification" in r

    def test_extreme_probs(self):
        r = analyze(_position(annual_downtime_slash_prob=5.0,
                              annual_correlated_slash_prob=5.0), config=_cfg())
        assert 0.0 <= r["expected_annual_slashing_loss_pct"] <= 100.0


# ===========================================================================
# 16. Logging via config
# ===========================================================================

class TestLogging:
    def test_writes_log(self):
        path = _tmp_log()
        analyze(_position(), config={"log_path": path})
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 1
        os.unlink(path)

    def test_log_accumulates(self):
        path = _tmp_log()
        analyze(_position(name="A"), config={"log_path": path})
        analyze(_position(name="B"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 2
        assert data[0]["name"] == "A"
        assert data[1]["name"] == "B"
        os.unlink(path)

    def test_log_ring_buffer_cap(self, tmp_path):
        path = str(tmp_path / "slash_log.json")
        for i in range(120):
            analyze(_position(name=f"P{i}"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 100
        assert data[-1]["name"] == "P119"
        assert data[0]["name"] == "P20"

    def test_idempotent_rerun(self, tmp_path):
        path = str(tmp_path / "slash_log.json")
        p = _position(name="Same")
        r1 = analyze(p, config={"log_path": path})
        r2 = analyze(p, config={"log_path": path})
        assert r1["classification"] == r2["classification"]
        assert r1["slashing_risk_score"] == r2["slashing_risk_score"]
        assert r1["flags"] == r2["flags"]

    def test_log_via_tmp_path(self, tmp_path):
        path = str(tmp_path / "out.json")
        analyze(_position(), config={"log_path": path})
        assert os.path.exists(path)

    def test_log_is_valid_json(self, tmp_path):
        path = str(tmp_path / "slash_log.json")
        for i in range(150):
            analyze(_position(name=f"P{i}"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) <= 100


# ===========================================================================
# 17. Determinism
# ===========================================================================

class TestDeterminism:
    def test_same_inputs_same_metrics(self):
        p = _position(name="Det")
        r1 = analyze(p, config=_cfg())
        r2 = analyze(p, config=_cfg())
        assert r1["expected_annual_slashing_loss_pct"] == r2["expected_annual_slashing_loss_pct"]
        assert r1["worst_case_haircut_pct"] == r2["worst_case_haircut_pct"]
        assert r1["slashing_risk_score"] == r2["slashing_risk_score"]
        assert r1["classification"] == r2["classification"]
        assert r1["grade"] == r2["grade"]

    def test_risk_deterministic(self):
        s1 = _slashing_risk_score(2.0, 50.0, 40.0, 60.0, 2.0, has_data=True)
        s2 = _slashing_risk_score(2.0, 50.0, 40.0, 60.0, 2.0, has_data=True)
        assert s1 == s2


# ===========================================================================
# 18. Monotonicity sanity checks
# ===========================================================================

class TestMonotonicity:
    def test_severe_higher_risk_than_safe(self):
        safe = analyze(_safe_position(), config=_cfg())
        severe = analyze(_severe(), config=_cfg())
        assert severe["slashing_risk_score"] > safe["slashing_risk_score"]

    def test_more_restaking_higher_loss(self):
        low = analyze(_position(restaking_layers=0.0), config=_cfg())
        high = analyze(_position(restaking_layers=4.0), config=_cfg())
        assert high["expected_annual_slashing_loss_pct"] >= low["expected_annual_slashing_loss_pct"]

    def test_more_concentration_higher_haircut(self):
        low = analyze(_position(operator_concentration_pct=10.0,
                                num_validators=100.0), config=_cfg())
        high = analyze(_position(operator_concentration_pct=90.0,
                                 num_validators=100.0), config=_cfg())
        assert high["worst_case_haircut_pct"] > low["worst_case_haircut_pct"]

    def test_more_insurance_lower_exposure(self):
        low_ins = analyze(_position(insurance_coverage_pct=10.0), config=_cfg())
        high_ins = analyze(_position(insurance_coverage_pct=80.0), config=_cfg())
        assert high_ins["effective_exposure_after_insurance_pct"] < low_ins["effective_exposure_after_insurance_pct"]

    def test_higher_correlated_prob_higher_risk(self):
        low = analyze(_position(annual_correlated_slash_prob=0.0001), config=_cfg())
        high = analyze(_position(annual_correlated_slash_prob=0.05), config=_cfg())
        assert high["slashing_risk_score"] >= low["slashing_risk_score"]


# ===========================================================================
# 19. analyze_portfolio
# ===========================================================================

class TestAnalyzePortfolio:
    def test_empty_list(self):
        s = analyze_portfolio([], config=_cfg())
        assert s["total_positions"] == 0
        assert s["most_exposed_position"] is None
        assert s["least_exposed_position"] is None
        assert s["avg_slashing_risk_score"] == 0.0
        assert s["severe_count"] == 0
        assert s["results"] == []

    def test_single_position(self):
        s = analyze_portfolio([_position(name="Solo")], config=_cfg())
        assert s["total_positions"] == 1
        assert s["most_exposed_position"] == "Solo"
        assert s["least_exposed_position"] == "Solo"
        assert len(s["results"]) == 1

    def test_multiple_picks_most_and_least(self):
        s = analyze_portfolio([_severe("Sev"), _safe_position("Safe")],
                              config=_cfg())
        assert s["total_positions"] == 2
        assert s["most_exposed_position"] == "Sev"
        assert s["least_exposed_position"] == "Safe"

    def test_avg_score(self):
        positions = [_position(name="A"), _position(name="B")]
        s = analyze_portfolio(positions, config=_cfg())
        per = [r["slashing_risk_score"] for r in s["results"]]
        assert s["avg_slashing_risk_score"] == pytest.approx(sum(per) / len(per))

    def test_severe_count(self):
        positions = [_safe_position("S"), _severe("V1"), _severe("V2")]
        s = analyze_portfolio(positions, config=_cfg())
        assert s["severe_count"] == 2

    def test_results_count_matches(self):
        positions = [_position(name=f"P{i}") for i in range(5)]
        s = analyze_portfolio(positions, config=_cfg())
        assert len(s["results"]) == 5
        assert s["total_positions"] == 5

    def test_non_list_input(self):
        s = analyze_portfolio("notalist", config=_cfg())
        assert s["total_positions"] == 0

    def test_handles_non_dict_entries(self):
        s = analyze_portfolio([_position(name="ok"), "garbage", 42], config=_cfg())
        assert s["total_positions"] == 3

    def test_all_results_have_classification(self):
        positions = [_position(name=f"P{i}") for i in range(3)]
        s = analyze_portfolio(positions, config=_cfg())
        for r in s["results"]:
            assert r["classification"] in ALL_CLASSIFICATIONS

    def test_avg_bounded(self):
        positions = [_severe("V"), _safe_position("S"), _position(name="Mid")]
        s = analyze_portfolio(positions, config=_cfg())
        assert 0.0 <= s["avg_slashing_risk_score"] <= 100.0


# ===========================================================================
# 20. Class wrapper parity
# ===========================================================================

class TestClassWrapper:
    def test_instantiation(self):
        a = ProtocolDeFiValidatorSlashingExposureAnalyzer()
        assert a is not None

    def test_analyze_returns_dict(self):
        a = ProtocolDeFiValidatorSlashingExposureAnalyzer(config=_cfg())
        r = a.analyze(_position())
        assert isinstance(r, dict)

    def test_analyze_parity_with_function(self):
        cfg = _cfg()
        p = _position(name="Parity")
        r_func = analyze(p, config=cfg)
        r_class = ProtocolDeFiValidatorSlashingExposureAnalyzer(config=cfg).analyze(p)
        assert r_func["classification"] == r_class["classification"]
        assert r_func["slashing_risk_score"] == r_class["slashing_risk_score"]
        assert r_func["flags"] == r_class["flags"]

    def test_analyze_kwargs_via_class(self):
        a = ProtocolDeFiValidatorSlashingExposureAnalyzer(config=_cfg())
        r = a.analyze(position_value_usd=1_000_000.0,
                      annual_correlated_slash_prob=0.1,
                      correlated_penalty_pct=50.0)
        assert r["expected_annual_slashing_loss_usd"] == pytest.approx(50_000.0)

    def test_portfolio_parity(self):
        cfg = _cfg()
        positions = [_position(name="A"), _position(name="B")]
        r_func = analyze_portfolio(positions, config=cfg)
        r_class = ProtocolDeFiValidatorSlashingExposureAnalyzer(
            config=cfg).analyze_portfolio(positions)
        assert r_func["total_positions"] == r_class["total_positions"]
        assert r_func["most_exposed_position"] == r_class["most_exposed_position"]

    def test_config_forwarded_to_log(self):
        path = _tmp_log()
        a = ProtocolDeFiValidatorSlashingExposureAnalyzer(config={"log_path": path})
        a.analyze(_position())
        assert os.path.exists(path)
        with open(path) as fh:
            data = json.load(fh)
        assert len(data) == 1
        os.unlink(path)

    def test_no_config_uses_default(self):
        a = ProtocolDeFiValidatorSlashingExposureAnalyzer()
        r = a.analyze(_position())
        assert "classification" in r

    def test_multiple_calls_accumulate(self):
        path = _tmp_log()
        a = ProtocolDeFiValidatorSlashingExposureAnalyzer(config={"log_path": path})
        a.analyze(_position(name="A"))
        a.analyze(_position(name="B"))
        with open(path) as fh:
            data = json.load(fh)
        assert len(data) == 2
        os.unlink(path)

    def test_class_portfolio_returns_summary(self):
        a = ProtocolDeFiValidatorSlashingExposureAnalyzer(config=_cfg())
        s = a.analyze_portfolio([_position(name="X")])
        assert s["total_positions"] == 1


# ===========================================================================
# 21. Constants sanity
# ===========================================================================

class TestConstants:
    def test_all_classifications_count(self):
        assert len(ALL_CLASSIFICATIONS) == 5

    def test_all_flags_count(self):
        assert len(ALL_FLAGS) == 9

    def test_classifications_unique(self):
        assert len(set(ALL_CLASSIFICATIONS)) == len(ALL_CLASSIFICATIONS)

    def test_flags_unique(self):
        assert len(set(ALL_FLAGS)) == len(ALL_FLAGS)

    def test_amplification_positive(self):
        assert _RESTAKING_LAYER_AMPLIFICATION > 0.0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
