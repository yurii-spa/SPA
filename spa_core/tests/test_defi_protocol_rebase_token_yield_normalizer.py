"""
Tests for MP-1090 DeFiProtocolRebaseTokenYieldNormalizer
Comprehensive pytest suite — pure stdlib, no third-party dependencies.
"""

import json
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

from spa_core.analytics.defi_protocol_rebase_token_yield_normalizer import (
    analyze,
    analyze_portfolio,
    _effective_compounding_apy_pct,
    _real_economic_yield_pct,
    _dilution_drag_pct,
    _cosmetic_rebase_ratio,
    _purchasing_power_yield_pct,
    _normalization_gap_pct,
    _rebase_quality_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    DeFiProtocolRebaseTokenYieldNormalizer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_REAL_YIELD,
    CLASS_MOSTLY_REAL,
    CLASS_MIXED,
    CLASS_MOSTLY_COSMETIC,
    CLASS_FULLY_DILUTIVE,
    FLAG_HIGH_DILUTION_DRAG,
    FLAG_COSMETIC_REBASE,
    FLAG_NEGATIVE_REAL_YIELD,
    FLAG_PRICE_BELOW_NAV,
    FLAG_HEADLINE_OVERSTATES_YIELD,
    FLAG_STRONG_REAL_YIELD,
    FLAG_BACKING_OUTPACES_SUPPLY,
    FLAG_INSUFFICIENT_DATA,
    _DAYS_PER_YEAR,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _tmp_log():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _token(
    name="TestToken",
    advertised_apy_pct=5.0,
    rebase_frequency_per_day=1.0,
    backing_value_growth_pct=5.0,
    supply_growth_pct=0.5,
    token_price_change_pct=0.0,
    holder_share_pct=100.0,
    data_quality="ok",
):
    return {
        "name": name,
        "advertised_apy_pct": advertised_apy_pct,
        "rebase_frequency_per_day": rebase_frequency_per_day,
        "backing_value_growth_pct": backing_value_growth_pct,
        "supply_growth_pct": supply_growth_pct,
        "token_price_change_pct": token_price_change_pct,
        "holder_share_pct": holder_share_pct,
        "data_quality": data_quality,
    }


def _cosmetic(name="Cosmetic"):
    """A token expected to classify as fully dilutive / cosmetic."""
    return _token(
        name=name,
        advertised_apy_pct=1000.0,
        rebase_frequency_per_day=3.0,
        backing_value_growth_pct=50.0,
        supply_growth_pct=900.0,
        token_price_change_pct=-40.0,
    )


def _real(name="Real"):
    """A token expected to classify as real yield."""
    return _token(
        name=name,
        advertised_apy_pct=4.0,
        rebase_frequency_per_day=1.0,
        backing_value_growth_pct=4.0,
        supply_growth_pct=0.2,
        token_price_change_pct=0.1,
    )


def _cfg():
    return {"log_path": _tmp_log()}


# ===========================================================================
# 1. _effective_compounding_apy_pct
# ===========================================================================

class TestEffectiveApy:
    def test_zero_frequency_returns_advertised(self):
        assert _effective_compounding_apy_pct(5.0, 0.0) == pytest.approx(5.0)

    def test_negative_frequency_returns_advertised(self):
        assert _effective_compounding_apy_pct(5.0, -1.0) == pytest.approx(5.0)

    def test_compounding_raises_apy(self):
        # daily compounding of a 10% nominal exceeds 10%
        eff = _effective_compounding_apy_pct(10.0, 1.0)
        assert eff > 10.0

    def test_more_frequent_more_compounding(self):
        once = _effective_compounding_apy_pct(20.0, 1.0)
        thrice = _effective_compounding_apy_pct(20.0, 3.0)
        assert thrice >= once

    def test_zero_apy_zero_eff(self):
        assert _effective_compounding_apy_pct(0.0, 1.0) == pytest.approx(0.0)

    def test_no_overflow_on_huge_inputs(self):
        # should not raise even on absurd inputs
        r = _effective_compounding_apy_pct(1e9, 100.0)
        assert isinstance(r, float)

    def test_no_zero_division(self):
        _effective_compounding_apy_pct(5.0, 0.0)

    def test_small_apy_close_to_nominal(self):
        eff = _effective_compounding_apy_pct(1.0, 1.0)
        assert eff == pytest.approx(1.0, abs=0.1)

    def test_returns_float(self):
        assert isinstance(_effective_compounding_apy_pct(5.0, 1.0), float)

    def test_negative_apy_handled(self):
        r = _effective_compounding_apy_pct(-5.0, 1.0)
        assert isinstance(r, float)


# ===========================================================================
# 2. _real_economic_yield_pct
# ===========================================================================

class TestRealYield:
    def test_basic_math(self):
        # backing 5, supply 0.5 -> 4.5
        assert _real_economic_yield_pct(5.0, 5.0, 0.5) == pytest.approx(4.5)

    def test_falls_back_to_advertised_when_no_signal(self):
        assert _real_economic_yield_pct(5.0, 0.0, 0.0) == pytest.approx(5.0)

    def test_capped_at_advertised(self):
        # backing huge but cannot exceed headline
        assert _real_economic_yield_pct(5.0, 100.0, 0.0) == pytest.approx(5.0)

    def test_negative_when_supply_outpaces(self):
        r = _real_economic_yield_pct(1000.0, 50.0, 900.0)
        assert r < 0.0

    def test_dilution_reduces_real(self):
        no_dilution = _real_economic_yield_pct(5.0, 5.0, 0.0)
        with_dilution = _real_economic_yield_pct(5.0, 5.0, 3.0)
        assert with_dilution < no_dilution

    def test_returns_float(self):
        assert isinstance(_real_economic_yield_pct(5.0, 5.0, 0.5), float)

    def test_higher_backing_higher_real(self):
        low = _real_economic_yield_pct(100.0, 2.0, 1.0)
        high = _real_economic_yield_pct(100.0, 8.0, 1.0)
        assert high > low

    def test_higher_supply_lower_real(self):
        low_supply = _real_economic_yield_pct(100.0, 10.0, 1.0)
        high_supply = _real_economic_yield_pct(100.0, 10.0, 5.0)
        assert high_supply < low_supply


# ===========================================================================
# 3. _dilution_drag_pct
# ===========================================================================

class TestDilutionDrag:
    def test_basic_math(self):
        assert _dilution_drag_pct(10.0, 4.0) == pytest.approx(6.0)

    def test_floored_at_zero(self):
        assert _dilution_drag_pct(4.0, 10.0) == pytest.approx(0.0)

    def test_zero_when_equal(self):
        assert _dilution_drag_pct(5.0, 5.0) == pytest.approx(0.0)

    def test_negative_real_widens_drag(self):
        assert _dilution_drag_pct(10.0, -5.0) == pytest.approx(15.0)

    def test_never_negative(self):
        for adv in [0.0, 5.0, 100.0]:
            for real in [-50.0, 0.0, 50.0, 200.0]:
                assert _dilution_drag_pct(adv, real) >= 0.0

    def test_returns_float(self):
        assert isinstance(_dilution_drag_pct(10.0, 4.0), float)


# ===========================================================================
# 4. _cosmetic_rebase_ratio
# ===========================================================================

class TestCosmeticRatio:
    def test_basic_math(self):
        # supply 9, backing 1 -> 0.9
        assert _cosmetic_rebase_ratio(9.0, 1.0) == pytest.approx(0.9)

    def test_all_backing_zero_ratio(self):
        assert _cosmetic_rebase_ratio(0.0, 5.0) == pytest.approx(0.0)

    def test_all_supply_one_ratio(self):
        assert _cosmetic_rebase_ratio(5.0, 0.0) == pytest.approx(1.0)

    def test_zero_zero_returns_zero(self):
        assert _cosmetic_rebase_ratio(0.0, 0.0) == 0.0

    def test_no_zero_division(self):
        _cosmetic_rebase_ratio(0.0, 0.0)

    def test_bounded_0_1(self):
        for sup in [0.0, 1.0, 100.0, 1000.0]:
            for back in [0.0, 1.0, 100.0]:
                r = _cosmetic_rebase_ratio(sup, back)
                assert 0.0 <= r <= 1.0

    def test_negative_supply_zero(self):
        assert _cosmetic_rebase_ratio(-5.0, 10.0) == pytest.approx(0.0)

    def test_negative_backing_treated_as_zero(self):
        assert _cosmetic_rebase_ratio(5.0, -10.0) == pytest.approx(1.0)

    def test_half_half(self):
        assert _cosmetic_rebase_ratio(5.0, 5.0) == pytest.approx(0.5)

    def test_more_supply_higher_ratio(self):
        low = _cosmetic_rebase_ratio(2.0, 8.0)
        high = _cosmetic_rebase_ratio(8.0, 2.0)
        assert high > low


# ===========================================================================
# 5. _purchasing_power_yield_pct
# ===========================================================================

class TestPurchasingPower:
    def test_basic_math(self):
        assert _purchasing_power_yield_pct(5.0, -2.0) == pytest.approx(3.0)

    def test_positive_price_adds(self):
        assert _purchasing_power_yield_pct(5.0, 2.0) == pytest.approx(7.0)

    def test_zero_price_unchanged(self):
        assert _purchasing_power_yield_pct(5.0, 0.0) == pytest.approx(5.0)

    def test_negative_price_can_go_negative(self):
        assert _purchasing_power_yield_pct(2.0, -10.0) == pytest.approx(-8.0)

    def test_returns_float(self):
        assert isinstance(_purchasing_power_yield_pct(5.0, 1.0), float)

    def test_lower_price_lower_pp(self):
        high = _purchasing_power_yield_pct(5.0, 1.0)
        low = _purchasing_power_yield_pct(5.0, -5.0)
        assert low < high


# ===========================================================================
# 6. _normalization_gap_pct
# ===========================================================================

class TestNormalizationGap:
    def test_basic_math(self):
        assert _normalization_gap_pct(10.0, 3.0) == pytest.approx(7.0)

    def test_zero_gap(self):
        assert _normalization_gap_pct(5.0, 5.0) == pytest.approx(0.0)

    def test_negative_gap_when_pp_exceeds(self):
        assert _normalization_gap_pct(5.0, 7.0) == pytest.approx(-2.0)

    def test_returns_float(self):
        assert isinstance(_normalization_gap_pct(10.0, 3.0), float)

    def test_larger_gap_when_pp_lower(self):
        small = _normalization_gap_pct(10.0, 8.0)
        big = _normalization_gap_pct(10.0, 1.0)
        assert big > small


# ===========================================================================
# 7. _rebase_quality_score
# ===========================================================================

class TestQualityScore:
    def test_no_data_zero(self):
        s = _rebase_quality_score(5.0, 5.0, 0.1, 5.0, has_data=False)
        assert s == 0.0

    def test_perfect_real_high_score(self):
        # all real, no cosmetic, full pp
        s = _rebase_quality_score(5.0, 5.0, 0.0, 5.0, has_data=True)
        assert s == pytest.approx(100.0)

    def test_fully_cosmetic_low_score(self):
        s = _rebase_quality_score(100.0, -50.0, 1.0, -60.0, has_data=True)
        assert s < 20.0

    def test_bounded_0_100(self):
        for adv in [0.0, 5.0, 100.0]:
            for real in [-50.0, 0.0, 50.0, 100.0]:
                for cos in [0.0, 0.5, 1.0]:
                    for pp in [-50.0, 0.0, 50.0, 100.0]:
                        s = _rebase_quality_score(adv, real, cos, pp,
                                                  has_data=True)
                        assert 0.0 <= s <= 100.0

    def test_higher_real_higher_score(self):
        low = _rebase_quality_score(100.0, 20.0, 0.5, 20.0, has_data=True)
        high = _rebase_quality_score(100.0, 80.0, 0.5, 80.0, has_data=True)
        assert high > low

    def test_more_cosmetic_lower_score(self):
        low_cos = _rebase_quality_score(100.0, 50.0, 0.1, 50.0, has_data=True)
        high_cos = _rebase_quality_score(100.0, 50.0, 0.9, 50.0, has_data=True)
        assert high_cos < low_cos

    def test_lower_pp_lower_score(self):
        high_pp = _rebase_quality_score(100.0, 50.0, 0.3, 90.0, has_data=True)
        low_pp = _rebase_quality_score(100.0, 50.0, 0.3, 10.0, has_data=True)
        assert low_pp < high_pp

    def test_zero_headline_uses_non_cosmetic(self):
        # no headline; honest flat token scores by non-cosmetic share
        s = _rebase_quality_score(0.0, 0.0, 0.0, 0.0, has_data=True)
        assert s == pytest.approx(100.0)

    def test_zero_headline_cosmetic_low(self):
        s = _rebase_quality_score(0.0, 0.0, 1.0, 0.0, has_data=True)
        assert s == pytest.approx(0.0)

    def test_negative_real_contributes_zero(self):
        s = _rebase_quality_score(100.0, -100.0, 1.0, -100.0, has_data=True)
        assert s == pytest.approx(0.0)


# ===========================================================================
# 8. _classify
# ===========================================================================

class TestClassify:
    def test_no_data_real_yield(self):
        assert _classify(0.9, 5.0, 50.0, has_data=False) == CLASS_REAL_YIELD

    def test_real_yield(self):
        assert _classify(0.1, 5.0, 90.0, has_data=True) == CLASS_REAL_YIELD

    def test_mostly_real(self):
        assert _classify(0.3, 5.0, 70.0, has_data=True) == CLASS_MOSTLY_REAL

    def test_mixed(self):
        assert _classify(0.5, 5.0, 50.0, has_data=True) == CLASS_MIXED

    def test_mostly_cosmetic(self):
        assert _classify(0.7, 1.0, 30.0, has_data=True) == CLASS_MOSTLY_COSMETIC

    def test_fully_dilutive(self):
        assert _classify(0.9, -5.0, 10.0, has_data=True) == CLASS_FULLY_DILUTIVE

    def test_negative_real_forces_cosmetic(self):
        # low cosmetic ratio but negative real -> at least mostly cosmetic
        c = _classify(0.1, -5.0, 50.0, has_data=True)
        assert c in (CLASS_MOSTLY_COSMETIC, CLASS_FULLY_DILUTIVE)

    def test_negative_real_does_not_downgrade_already_worse(self):
        c = _classify(0.9, -5.0, 10.0, has_data=True)
        assert c == CLASS_FULLY_DILUTIVE

    def test_all_bands_reachable(self):
        seen = {
            _classify(0.1, 5.0, 90.0, has_data=True),
            _classify(0.3, 5.0, 70.0, has_data=True),
            _classify(0.5, 5.0, 50.0, has_data=True),
            _classify(0.7, 1.0, 30.0, has_data=True),
            _classify(0.9, -5.0, 10.0, has_data=True),
        }
        assert seen == set(ALL_CLASSIFICATIONS)

    def test_returns_valid_classification(self):
        for cos in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]:
            for real in [-5.0, 5.0]:
                c = _classify(cos, real, 50.0, has_data=True)
                assert c in ALL_CLASSIFICATIONS

    def test_boundary_020(self):
        assert _classify(0.199, 5.0, 50.0, has_data=True) == CLASS_REAL_YIELD
        assert _classify(0.20, 5.0, 50.0, has_data=True) == CLASS_MOSTLY_REAL

    def test_boundary_080(self):
        assert _classify(0.799, 5.0, 50.0, has_data=True) == CLASS_MOSTLY_COSMETIC
        assert _classify(0.80, 5.0, 50.0, has_data=True) == CLASS_FULLY_DILUTIVE


# ===========================================================================
# 9. _grade
# ===========================================================================

class TestGrade:
    def test_a(self):
        assert _grade(95.0) == "A"
        assert _grade(100.0) == "A"

    def test_b(self):
        assert _grade(75.0) == "B"

    def test_c(self):
        assert _grade(55.0) == "C"

    def test_d(self):
        assert _grade(35.0) == "D"

    def test_f(self):
        assert _grade(10.0) == "F"
        assert _grade(0.0) == "F"

    def test_boundaries(self):
        assert _grade(90.0) == "A"
        assert _grade(89.99) == "B"
        assert _grade(70.0) == "B"
        assert _grade(69.99) == "C"
        assert _grade(50.0) == "C"
        assert _grade(49.99) == "D"
        assert _grade(30.0) == "D"
        assert _grade(29.99) == "F"

    def test_monotonic(self):
        rank = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}
        grades = [_grade(s) for s in range(100, -1, -5)]
        for i in range(len(grades) - 1):
            assert rank[grades[i]] <= rank[grades[i + 1]]

    def test_all_grades_reachable(self):
        seen = {_grade(s) for s in [95, 75, 55, 35, 5]}
        assert seen == {"A", "B", "C", "D", "F"}

    def test_all_grades_constant(self):
        assert set(ALL_GRADES) == {"A", "B", "C", "D", "F"}


# ===========================================================================
# 10. _flags
# ===========================================================================

class TestFlags:
    def test_insufficient_data_only(self):
        f = _flags(10.0, 0.9, -5.0, -10.0, 8.0, 50.0, 900.0, has_data=False)
        assert f == [FLAG_INSUFFICIENT_DATA]

    def test_high_dilution_drag(self):
        f = _flags(10.0, 0.5, 2.0, 0.0, 2.0, 5.0, 1.0, has_data=True)
        assert FLAG_HIGH_DILUTION_DRAG in f

    def test_low_drag_no_flag(self):
        f = _flags(2.0, 0.3, 4.0, 0.0, 1.0, 5.0, 1.0, has_data=True)
        assert FLAG_HIGH_DILUTION_DRAG not in f

    def test_cosmetic_rebase(self):
        f = _flags(2.0, 0.6, 4.0, 0.0, 1.0, 6.0, 4.0, has_data=True)
        assert FLAG_COSMETIC_REBASE in f

    def test_low_cosmetic_no_flag(self):
        f = _flags(2.0, 0.3, 4.0, 0.0, 1.0, 6.0, 1.0, has_data=True)
        assert FLAG_COSMETIC_REBASE not in f

    def test_negative_real_yield(self):
        f = _flags(10.0, 0.9, -5.0, 0.0, 2.0, 5.0, 900.0, has_data=True)
        assert FLAG_NEGATIVE_REAL_YIELD in f

    def test_positive_real_no_neg_flag(self):
        f = _flags(2.0, 0.3, 5.0, 0.0, 1.0, 6.0, 1.0, has_data=True)
        assert FLAG_NEGATIVE_REAL_YIELD not in f

    def test_price_below_nav(self):
        f = _flags(2.0, 0.3, 4.0, -5.0, 1.0, 6.0, 1.0, has_data=True)
        assert FLAG_PRICE_BELOW_NAV in f

    def test_price_above_nav_no_flag(self):
        f = _flags(2.0, 0.3, 4.0, 5.0, 1.0, 6.0, 1.0, has_data=True)
        assert FLAG_PRICE_BELOW_NAV not in f

    def test_headline_overstates(self):
        f = _flags(2.0, 0.3, 4.0, 0.0, 5.0, 6.0, 1.0, has_data=True)
        assert FLAG_HEADLINE_OVERSTATES_YIELD in f

    def test_small_gap_no_overstate_flag(self):
        f = _flags(2.0, 0.3, 4.0, 0.0, 1.0, 6.0, 1.0, has_data=True)
        assert FLAG_HEADLINE_OVERSTATES_YIELD not in f

    def test_strong_real_yield(self):
        f = _flags(2.0, 0.3, 5.0, 0.0, 1.0, 6.0, 1.0, has_data=True)
        assert FLAG_STRONG_REAL_YIELD in f

    def test_weak_real_no_strong_flag(self):
        f = _flags(2.0, 0.3, 1.0, 0.0, 1.0, 6.0, 1.0, has_data=True)
        assert FLAG_STRONG_REAL_YIELD not in f

    def test_backing_outpaces_supply(self):
        f = _flags(2.0, 0.3, 5.0, 0.0, 1.0, 6.0, 1.0, has_data=True)
        assert FLAG_BACKING_OUTPACES_SUPPLY in f

    def test_supply_outpaces_no_flag(self):
        f = _flags(10.0, 0.9, -5.0, 0.0, 2.0, 1.0, 900.0, has_data=True)
        assert FLAG_BACKING_OUTPACES_SUPPLY not in f

    def test_all_flags_valid(self):
        f = _flags(10.0, 0.9, -5.0, -10.0, 8.0, 6.0, 4.0, has_data=True)
        for flag in f:
            assert flag in ALL_FLAGS


# ===========================================================================
# 11. _recommendations
# ===========================================================================

class TestRecommendations:
    def test_insufficient_data(self):
        recs = _recommendations(
            CLASS_REAL_YIELD, [FLAG_INSUFFICIENT_DATA], 0.0, 0.0, 0.0,
            0.0, 0.0, has_data=False,
        )
        assert len(recs) >= 1
        assert any("insufficient" in r.lower() for r in recs)

    def test_fully_dilutive_mentions(self):
        recs = _recommendations(
            CLASS_FULLY_DILUTIVE, [], 1000.0, -850.0, -890.0, 0.95, 1890.0,
            has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "dilutive" in combined or "cosmetic" in combined

    def test_returns_list_for_each_class(self):
        for c in ALL_CLASSIFICATIONS:
            recs = _recommendations(
                c, [], 5.0, 4.0, 4.0, 0.4, 1.0, has_data=True,
            )
            assert isinstance(recs, list)
            assert len(recs) >= 1

    def test_high_drag_mentioned(self):
        recs = _recommendations(
            CLASS_MIXED, [FLAG_HIGH_DILUTION_DRAG], 10.0, 4.0, 4.0, 0.5, 6.0,
            has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "dilution" in combined or "drag" in combined

    def test_negative_real_mentioned(self):
        recs = _recommendations(
            CLASS_FULLY_DILUTIVE, [FLAG_NEGATIVE_REAL_YIELD],
            100.0, -10.0, -10.0, 0.9, 110.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "negative" in combined or "purchasing power" in combined

    def test_price_below_nav_mentioned(self):
        recs = _recommendations(
            CLASS_MIXED, [FLAG_PRICE_BELOW_NAV], 5.0, 4.0, 0.0, 0.5, 5.0,
            has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "nav" in combined or "peg" in combined or "discount" in combined

    def test_overstates_mentioned(self):
        recs = _recommendations(
            CLASS_MIXED, [FLAG_HEADLINE_OVERSTATES_YIELD],
            10.0, 4.0, 3.0, 0.5, 7.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "overstate" in combined or "headline" in combined

    def test_strong_real_mentioned(self):
        recs = _recommendations(
            CLASS_REAL_YIELD, [FLAG_STRONG_REAL_YIELD],
            5.0, 5.0, 5.0, 0.1, 0.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "strong" in combined or "healthy" in combined

    def test_backing_outpaces_mentioned(self):
        recs = _recommendations(
            CLASS_REAL_YIELD, [FLAG_BACKING_OUTPACES_SUPPLY],
            5.0, 5.0, 5.0, 0.1, 0.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "backing" in combined or "accretive" in combined


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
        r = analyze(_token(), config=_cfg())
        assert isinstance(r, dict)

    def test_required_keys(self):
        r = analyze(_token(), config=_cfg())
        for key in [
            "name",
            "effective_compounding_apy_pct",
            "real_economic_yield_pct",
            "dilution_drag_pct",
            "cosmetic_rebase_ratio",
            "purchasing_power_yield_pct",
            "normalization_gap_pct",
            "rebase_quality_score",
            "classification",
            "grade",
            "flags",
            "recommendations",
            "timestamp",
        ]:
            assert key in r

    def test_real_yield_math(self):
        r = analyze(_token(advertised_apy_pct=5.0, backing_value_growth_pct=5.0,
                           supply_growth_pct=0.5), config=_cfg())
        assert r["real_economic_yield_pct"] == pytest.approx(4.5)

    def test_dilution_drag_math(self):
        r = analyze(_token(advertised_apy_pct=5.0, backing_value_growth_pct=5.0,
                           supply_growth_pct=0.5), config=_cfg())
        assert r["dilution_drag_pct"] == pytest.approx(0.5)

    def test_purchasing_power_math(self):
        r = analyze(_token(advertised_apy_pct=5.0, backing_value_growth_pct=5.0,
                           supply_growth_pct=0.5, token_price_change_pct=-1.0),
                    config=_cfg())
        # real 4.5, pp 3.5
        assert r["purchasing_power_yield_pct"] == pytest.approx(3.5)

    def test_classification_valid(self):
        r = analyze(_token(), config=_cfg())
        assert r["classification"] in ALL_CLASSIFICATIONS

    def test_grade_valid(self):
        r = analyze(_token(), config=_cfg())
        assert r["grade"] in ALL_GRADES

    def test_cosmetic_scenario(self):
        r = analyze(_cosmetic(), config=_cfg())
        assert r["classification"] == CLASS_FULLY_DILUTIVE
        assert FLAG_COSMETIC_REBASE in r["flags"]

    def test_real_scenario(self):
        r = analyze(_real(), config=_cfg())
        assert r["classification"] in (CLASS_REAL_YIELD, CLASS_MOSTLY_REAL)

    def test_negative_real_flag(self):
        r = analyze(_cosmetic(), config=_cfg())
        assert FLAG_NEGATIVE_REAL_YIELD in r["flags"]

    def test_price_below_nav_flag(self):
        r = analyze(_token(token_price_change_pct=-5.0), config=_cfg())
        assert FLAG_PRICE_BELOW_NAV in r["flags"]

    def test_high_dilution_drag_flag(self):
        r = analyze(_token(advertised_apy_pct=20.0, backing_value_growth_pct=5.0,
                           supply_growth_pct=10.0), config=_cfg())
        assert FLAG_HIGH_DILUTION_DRAG in r["flags"]

    def test_strong_real_yield_flag(self):
        r = analyze(_token(advertised_apy_pct=8.0, backing_value_growth_pct=8.0,
                           supply_growth_pct=1.0), config=_cfg())
        assert FLAG_STRONG_REAL_YIELD in r["flags"]

    def test_backing_outpaces_flag(self):
        r = analyze(_token(backing_value_growth_pct=5.0, supply_growth_pct=0.5),
                    config=_cfg())
        assert FLAG_BACKING_OUTPACES_SUPPLY in r["flags"]

    def test_headline_overstates_flag(self):
        r = analyze(_cosmetic(), config=_cfg())
        assert FLAG_HEADLINE_OVERSTATES_YIELD in r["flags"]

    def test_insufficient_data_flag(self):
        r = analyze(_token(advertised_apy_pct=0.0, backing_value_growth_pct=0.0,
                           supply_growth_pct=0.0), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]
        assert r["classification"] == CLASS_REAL_YIELD

    def test_poor_data_quality_insufficient(self):
        r = analyze(_token(data_quality="poor"), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]

    def test_name_preserved(self):
        r = analyze(_token(name="stETH"), config=_cfg())
        assert r["name"] == "stETH"

    def test_recommendations_is_list(self):
        r = analyze(_token(), config=_cfg())
        assert isinstance(r["recommendations"], list)
        assert len(r["recommendations"]) >= 1

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_token(), config=_cfg())
        after = time.time()
        assert before <= r["timestamp"] <= after

    def test_flags_valid(self):
        r = analyze(_cosmetic(), config=_cfg())
        for flag in r["flags"]:
            assert flag in ALL_FLAGS

    def test_quality_bounded(self):
        r = analyze(_token(), config=_cfg())
        assert 0.0 <= r["rebase_quality_score"] <= 100.0

    def test_cosmetic_ratio_bounded(self):
        r = analyze(_cosmetic(), config=_cfg())
        assert 0.0 <= r["cosmetic_rebase_ratio"] <= 1.0

    def test_dilution_drag_non_negative(self):
        r = analyze(_token(), config=_cfg())
        assert r["dilution_drag_pct"] >= 0.0

    def test_kwargs_override_dict(self):
        r = analyze(_token(advertised_apy_pct=5.0),
                    advertised_apy_pct=20.0, config=_cfg())
        assert r["advertised_apy_pct"] == 20.0

    def test_kwargs_only(self):
        r = analyze(advertised_apy_pct=10.0, backing_value_growth_pct=10.0,
                    supply_growth_pct=2.0, config=_cfg())
        assert r["real_economic_yield_pct"] == pytest.approx(8.0)

    def test_effective_apy_present(self):
        r = analyze(_token(advertised_apy_pct=10.0, rebase_frequency_per_day=1.0),
                    config=_cfg())
        assert r["effective_compounding_apy_pct"] > 10.0

    def test_holder_share_clamped(self):
        r = analyze(_token(holder_share_pct=150.0), config=_cfg())
        assert r["holder_share_pct"] == 100.0


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
        r = analyze({"name": "X", "advertised_apy_pct": "5",
                     "backing_value_growth_pct": "5",
                     "supply_growth_pct": "0.5"}, config=_cfg())
        assert r["real_economic_yield_pct"] == pytest.approx(4.5)

    def test_garbage_numeric_fields(self):
        r = analyze({"name": "X", "advertised_apy_pct": "abc",
                     "supply_growth_pct": None}, config=_cfg())
        assert "classification" in r

    def test_no_zero_division_all_zeros(self):
        r = analyze(_token(advertised_apy_pct=0.0, rebase_frequency_per_day=0.0,
                           backing_value_growth_pct=0.0, supply_growth_pct=0.0,
                           token_price_change_pct=0.0, holder_share_pct=0.0),
                    config=_cfg())
        assert "classification" in r

    def test_zero_frequency_no_crash(self):
        r = analyze(_token(rebase_frequency_per_day=0.0), config=_cfg())
        assert "classification" in r

    def test_does_not_raise_on_bad_log_path(self):
        r = analyze(_token(), config={"log_path": "/dev/null/cannot/log.json"})
        assert "classification" in r

    def test_default_log_path_used(self):
        r = analyze(_token())
        assert "classification" in r

    def test_extreme_values(self):
        r = analyze(_token(advertised_apy_pct=1e9, supply_growth_pct=1e9,
                           backing_value_growth_pct=1e9), config=_cfg())
        assert 0.0 <= r["rebase_quality_score"] <= 100.0


# ===========================================================================
# 16. Logging via config
# ===========================================================================

class TestLogging:
    def test_writes_log(self):
        path = _tmp_log()
        analyze(_token(), config={"log_path": path})
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 1
        os.unlink(path)

    def test_log_accumulates(self):
        path = _tmp_log()
        analyze(_token(name="A"), config={"log_path": path})
        analyze(_token(name="B"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 2
        assert data[0]["name"] == "A"
        assert data[1]["name"] == "B"
        os.unlink(path)

    def test_log_ring_buffer_cap(self, tmp_path):
        path = str(tmp_path / "rebase_log.json")
        for i in range(120):
            analyze(_token(name=f"T{i}"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 100
        assert data[-1]["name"] == "T119"
        assert data[0]["name"] == "T20"

    def test_idempotent_rerun(self, tmp_path):
        path = str(tmp_path / "rebase_log.json")
        t = _token(name="Same")
        r1 = analyze(t, config={"log_path": path})
        r2 = analyze(t, config={"log_path": path})
        assert r1["classification"] == r2["classification"]
        assert r1["rebase_quality_score"] == r2["rebase_quality_score"]
        assert r1["flags"] == r2["flags"]

    def test_log_via_tmp_path(self, tmp_path):
        path = str(tmp_path / "out.json")
        analyze(_token(), config={"log_path": path})
        assert os.path.exists(path)

    def test_log_is_valid_json(self, tmp_path):
        path = str(tmp_path / "rebase_log.json")
        for i in range(150):
            analyze(_token(name=f"T{i}"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) <= 100


# ===========================================================================
# 17. Determinism
# ===========================================================================

class TestDeterminism:
    def test_same_inputs_same_metrics(self):
        t = _token(name="Det")
        r1 = analyze(t, config=_cfg())
        r2 = analyze(t, config=_cfg())
        assert r1["real_economic_yield_pct"] == r2["real_economic_yield_pct"]
        assert r1["cosmetic_rebase_ratio"] == r2["cosmetic_rebase_ratio"]
        assert r1["rebase_quality_score"] == r2["rebase_quality_score"]
        assert r1["classification"] == r2["classification"]
        assert r1["grade"] == r2["grade"]

    def test_quality_deterministic(self):
        s1 = _rebase_quality_score(100.0, 50.0, 0.3, 50.0, has_data=True)
        s2 = _rebase_quality_score(100.0, 50.0, 0.3, 50.0, has_data=True)
        assert s1 == s2


# ===========================================================================
# 18. Monotonicity sanity checks
# ===========================================================================

class TestMonotonicity:
    def test_cosmetic_lower_quality_than_real(self):
        real = analyze(_real(), config=_cfg())
        cosmetic = analyze(_cosmetic(), config=_cfg())
        assert cosmetic["rebase_quality_score"] < real["rebase_quality_score"]

    def test_more_supply_higher_cosmetic_ratio(self):
        low = analyze(_token(supply_growth_pct=0.5, backing_value_growth_pct=5.0),
                      config=_cfg())
        high = analyze(_token(supply_growth_pct=20.0, backing_value_growth_pct=5.0),
                       config=_cfg())
        assert high["cosmetic_rebase_ratio"] > low["cosmetic_rebase_ratio"]

    def test_more_supply_lower_real_yield(self):
        low = analyze(_token(advertised_apy_pct=20.0, supply_growth_pct=1.0,
                             backing_value_growth_pct=10.0), config=_cfg())
        high = analyze(_token(advertised_apy_pct=20.0, supply_growth_pct=8.0,
                              backing_value_growth_pct=10.0), config=_cfg())
        assert high["real_economic_yield_pct"] < low["real_economic_yield_pct"]

    def test_lower_price_lower_purchasing_power(self):
        high = analyze(_token(token_price_change_pct=2.0), config=_cfg())
        low = analyze(_token(token_price_change_pct=-5.0), config=_cfg())
        assert low["purchasing_power_yield_pct"] < high["purchasing_power_yield_pct"]

    def test_more_dilution_lower_quality(self):
        low_dil = analyze(_token(advertised_apy_pct=10.0, backing_value_growth_pct=10.0,
                                 supply_growth_pct=0.5), config=_cfg())
        high_dil = analyze(_token(advertised_apy_pct=10.0, backing_value_growth_pct=10.0,
                                  supply_growth_pct=8.0), config=_cfg())
        assert high_dil["rebase_quality_score"] < low_dil["rebase_quality_score"]


# ===========================================================================
# 19. analyze_portfolio
# ===========================================================================

class TestAnalyzePortfolio:
    def test_empty_list(self):
        s = analyze_portfolio([], config=_cfg())
        assert s["total_positions"] == 0
        assert s["best_token"] is None
        assert s["worst_token"] is None
        assert s["avg_rebase_quality_score"] == 0.0
        assert s["cosmetic_count"] == 0
        assert s["fully_dilutive_count"] == 0
        assert s["results"] == []

    def test_single_position(self):
        s = analyze_portfolio([_token(name="Solo")], config=_cfg())
        assert s["total_positions"] == 1
        assert s["best_token"] == "Solo"
        assert s["worst_token"] == "Solo"
        assert len(s["results"]) == 1

    def test_multiple_picks_best_and_worst(self):
        s = analyze_portfolio([_cosmetic("Cos"), _real("Real")], config=_cfg())
        assert s["total_positions"] == 2
        assert s["best_token"] == "Real"
        assert s["worst_token"] == "Cos"

    def test_avg_score(self):
        tokens = [_token(name="A"), _token(name="B")]
        s = analyze_portfolio(tokens, config=_cfg())
        per = [r["rebase_quality_score"] for r in s["results"]]
        assert s["avg_rebase_quality_score"] == pytest.approx(sum(per) / len(per))

    def test_cosmetic_count(self):
        tokens = [_real("R"), _cosmetic("C1"), _cosmetic("C2")]
        s = analyze_portfolio(tokens, config=_cfg())
        assert s["cosmetic_count"] == 2

    def test_fully_dilutive_count(self):
        tokens = [_real("R"), _cosmetic("C1"), _cosmetic("C2")]
        s = analyze_portfolio(tokens, config=_cfg())
        assert s["fully_dilutive_count"] == 2

    def test_results_count_matches(self):
        tokens = [_token(name=f"T{i}") for i in range(5)]
        s = analyze_portfolio(tokens, config=_cfg())
        assert len(s["results"]) == 5
        assert s["total_positions"] == 5

    def test_non_list_input(self):
        s = analyze_portfolio("notalist", config=_cfg())
        assert s["total_positions"] == 0

    def test_handles_non_dict_entries(self):
        s = analyze_portfolio([_token(name="ok"), "garbage", 42], config=_cfg())
        assert s["total_positions"] == 3

    def test_all_results_have_classification(self):
        tokens = [_token(name=f"T{i}") for i in range(3)]
        s = analyze_portfolio(tokens, config=_cfg())
        for r in s["results"]:
            assert r["classification"] in ALL_CLASSIFICATIONS

    def test_avg_bounded(self):
        tokens = [_cosmetic("C"), _real("R"), _token(name="Mid")]
        s = analyze_portfolio(tokens, config=_cfg())
        assert 0.0 <= s["avg_rebase_quality_score"] <= 100.0


# ===========================================================================
# 20. Class wrapper parity
# ===========================================================================

class TestClassWrapper:
    def test_instantiation(self):
        n = DeFiProtocolRebaseTokenYieldNormalizer()
        assert n is not None

    def test_analyze_returns_dict(self):
        n = DeFiProtocolRebaseTokenYieldNormalizer(config=_cfg())
        r = n.analyze(_token())
        assert isinstance(r, dict)

    def test_analyze_parity_with_function(self):
        cfg = _cfg()
        t = _token(name="Parity")
        r_func = analyze(t, config=cfg)
        r_class = DeFiProtocolRebaseTokenYieldNormalizer(config=cfg).analyze(t)
        assert r_func["classification"] == r_class["classification"]
        assert r_func["rebase_quality_score"] == r_class["rebase_quality_score"]
        assert r_func["flags"] == r_class["flags"]

    def test_analyze_kwargs_via_class(self):
        n = DeFiProtocolRebaseTokenYieldNormalizer(config=_cfg())
        r = n.analyze(advertised_apy_pct=10.0, backing_value_growth_pct=10.0,
                      supply_growth_pct=2.0)
        assert r["real_economic_yield_pct"] == pytest.approx(8.0)

    def test_portfolio_parity(self):
        cfg = _cfg()
        tokens = [_token(name="A"), _token(name="B")]
        r_func = analyze_portfolio(tokens, config=cfg)
        r_class = DeFiProtocolRebaseTokenYieldNormalizer(
            config=cfg).analyze_portfolio(tokens)
        assert r_func["total_positions"] == r_class["total_positions"]
        assert r_func["best_token"] == r_class["best_token"]

    def test_config_forwarded_to_log(self):
        path = _tmp_log()
        n = DeFiProtocolRebaseTokenYieldNormalizer(config={"log_path": path})
        n.analyze(_token())
        assert os.path.exists(path)
        with open(path) as fh:
            data = json.load(fh)
        assert len(data) == 1
        os.unlink(path)

    def test_no_config_uses_default(self):
        n = DeFiProtocolRebaseTokenYieldNormalizer()
        r = n.analyze(_token())
        assert "classification" in r

    def test_multiple_calls_accumulate(self):
        path = _tmp_log()
        n = DeFiProtocolRebaseTokenYieldNormalizer(config={"log_path": path})
        n.analyze(_token(name="A"))
        n.analyze(_token(name="B"))
        with open(path) as fh:
            data = json.load(fh)
        assert len(data) == 2
        os.unlink(path)

    def test_class_portfolio_returns_summary(self):
        n = DeFiProtocolRebaseTokenYieldNormalizer(config=_cfg())
        s = n.analyze_portfolio([_token(name="X")])
        assert s["total_positions"] == 1


# ===========================================================================
# 21. Constants sanity
# ===========================================================================

class TestConstants:
    def test_all_classifications_count(self):
        assert len(ALL_CLASSIFICATIONS) == 5

    def test_all_flags_count(self):
        assert len(ALL_FLAGS) == 8

    def test_classifications_unique(self):
        assert len(set(ALL_CLASSIFICATIONS)) == len(ALL_CLASSIFICATIONS)

    def test_flags_unique(self):
        assert len(set(ALL_FLAGS)) == len(ALL_FLAGS)

    def test_days_per_year(self):
        assert _DAYS_PER_YEAR == pytest.approx(365.0)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
