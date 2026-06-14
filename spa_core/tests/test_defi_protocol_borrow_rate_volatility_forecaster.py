"""
Tests for MP-1109 DeFiProtocolBorrowRateVolatilityForecaster
Comprehensive pytest suite - pure stdlib, no third-party dependencies.
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

from spa_core.analytics.defi_protocol_borrow_rate_volatility_forecaster import (
    analyze,
    analyze_portfolio,
    _rate_sensitivity_factor,
    _forecast_borrow_apr_vol_pct,
    _borrow_apr_p95_pct,
    _borrow_apr_p05_pct,
    _net_carry_now_pct,
    _net_carry_at_p95_borrow_pct,
    _carry_wipeout_probability_pct,
    _rate_stability_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _norm_sf,
    _atomic_log,
    _safe_float,
    _clamp,
    DeFiProtocolBorrowRateVolatilityForecaster,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_VERY_STABLE,
    CLASS_STABLE,
    CLASS_MODERATE,
    CLASS_VOLATILE,
    CLASS_HIGHLY_VOLATILE,
    FLAG_HIGH_RATE_VOLATILITY,
    FLAG_CARRY_WIPEOUT_RISK,
    FLAG_HIGH_UTILIZATION_SENSITIVITY,
    FLAG_NEGATIVE_CARRY_AT_P95,
    FLAG_THIN_CARRY_MARGIN,
    FLAG_STABLE_BORROW_COST,
    FLAG_INSUFFICIENT_DATA,
    _Z_95,
    _EPS,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _tmp_log():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _market(
    name="TestMarket",
    current_borrow_apr_pct=4.0,
    current_utilization_pct=50.0,
    utilization_volatility_pct=10.0,
    kink_utilization_pct=80.0,
    slope1_pct=4.0,
    slope2_pct=60.0,
    farm_apr_pct=8.0,
    horizon_days=30.0,
    data_quality="ok",
):
    return {
        "name": name,
        "current_borrow_apr_pct": current_borrow_apr_pct,
        "current_utilization_pct": current_utilization_pct,
        "utilization_volatility_pct": utilization_volatility_pct,
        "kink_utilization_pct": kink_utilization_pct,
        "slope1_pct": slope1_pct,
        "slope2_pct": slope2_pct,
        "farm_apr_pct": farm_apr_pct,
        "horizon_days": horizon_days,
        "data_quality": data_quality,
    }


def _volatile(name="Volatile"):
    # past kink, high sensitivity, high vol
    return _market(
        name=name,
        current_borrow_apr_pct=46.0,
        current_utilization_pct=94.0,
        utilization_volatility_pct=8.0,
        farm_apr_pct=50.0,
    )


def _stable(name="Stable"):
    # below kink, low sensitivity, fat carry
    return _market(
        name=name,
        current_borrow_apr_pct=1.5,
        current_utilization_pct=30.0,
        utilization_volatility_pct=5.0,
        farm_apr_pct=10.0,
    )


def _cfg():
    return {"log_path": _tmp_log()}


# ===========================================================================
# 1. _norm_sf
# ===========================================================================

class TestNormSf:
    def test_zero_is_half(self):
        assert _norm_sf(0.0) == pytest.approx(0.5)

    def test_large_positive_near_zero(self):
        assert _norm_sf(5.0) < 0.001

    def test_large_negative_near_one(self):
        assert _norm_sf(-5.0) > 0.999

    def test_one_sigma(self):
        # P(Z >= 1) ~ 0.1587
        assert _norm_sf(1.0) == pytest.approx(0.1587, abs=0.001)

    def test_negative_one_sigma(self):
        assert _norm_sf(-1.0) == pytest.approx(0.8413, abs=0.001)

    def test_1645_is_5pct(self):
        assert _norm_sf(1.645) == pytest.approx(0.05, abs=0.002)

    def test_monotonic_decreasing(self):
        prev = 2.0
        for z in [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0]:
            cur = _norm_sf(z)
            assert cur < prev
            prev = cur

    def test_bounded_0_1(self):
        for z in [-10.0, -1.0, 0.0, 1.0, 10.0, 100.0, -100.0]:
            r = _norm_sf(z)
            assert 0.0 <= r <= 1.0

    def test_returns_float(self):
        assert isinstance(_norm_sf(0.5), float)

    def test_huge_positive(self):
        assert _norm_sf(1e6) == pytest.approx(0.0, abs=1e-9)

    def test_huge_negative(self):
        assert _norm_sf(-1e6) == pytest.approx(1.0, abs=1e-9)

    def test_symmetry(self):
        assert _norm_sf(1.0) + _norm_sf(-1.0) == pytest.approx(1.0)


# ===========================================================================
# 2. _rate_sensitivity_factor
# ===========================================================================

class TestRateSensitivity:
    def test_below_kink(self):
        # slope1/kink = 4/80 = 0.05
        assert _rate_sensitivity_factor(50.0, 80.0, 4.0, 60.0) == pytest.approx(0.05)

    def test_above_kink(self):
        # slope2/(100-kink) = 60/20 = 3.0
        assert _rate_sensitivity_factor(90.0, 80.0, 4.0, 60.0) == pytest.approx(3.0)

    def test_at_kink_uses_first_slope(self):
        # util == kink -> first slope (util <= kink)
        assert _rate_sensitivity_factor(80.0, 80.0, 4.0, 60.0) == pytest.approx(0.05)

    def test_above_more_sensitive_than_below(self):
        below = _rate_sensitivity_factor(50.0, 80.0, 4.0, 60.0)
        above = _rate_sensitivity_factor(90.0, 80.0, 4.0, 60.0)
        assert above > below

    def test_at_zero_util_below(self):
        assert _rate_sensitivity_factor(0.0, 80.0, 4.0, 60.0) == pytest.approx(0.05)

    def test_at_full_util_above(self):
        assert _rate_sensitivity_factor(100.0, 80.0, 4.0, 60.0) == pytest.approx(3.0)

    def test_kink_zero_uses_second(self):
        # degenerate kink 0 -> slope2/100
        assert _rate_sensitivity_factor(50.0, 0.0, 4.0, 60.0) == pytest.approx(0.6)

    def test_kink_zero_no_crash(self):
        r = _rate_sensitivity_factor(50.0, 0.0, 4.0, 60.0)
        assert math.isfinite(r)

    def test_kink_100_no_crash(self):
        # util <= 100 == kink -> first slope slope1/100
        r = _rate_sensitivity_factor(50.0, 100.0, 4.0, 60.0)
        assert math.isfinite(r)
        assert r == pytest.approx(0.04)

    def test_kink_negative_guarded(self):
        r = _rate_sensitivity_factor(50.0, -10.0, 4.0, 60.0)
        assert math.isfinite(r)

    def test_no_zero_division_kink_zero(self):
        _rate_sensitivity_factor(0.0, 0.0, 4.0, 60.0)

    def test_returns_float(self):
        assert isinstance(_rate_sensitivity_factor(50.0, 80.0, 4.0, 60.0), float)

    def test_steeper_slope2_higher_sensitivity(self):
        gentle = _rate_sensitivity_factor(90.0, 80.0, 4.0, 20.0)
        steep = _rate_sensitivity_factor(90.0, 80.0, 4.0, 80.0)
        assert steep > gentle


# ===========================================================================
# 3. _forecast_borrow_apr_vol_pct
# ===========================================================================

class TestForecastVol:
    def test_basic(self):
        assert _forecast_borrow_apr_vol_pct(3.0, 8.0) == pytest.approx(24.0)

    def test_zero_sensitivity(self):
        assert _forecast_borrow_apr_vol_pct(0.0, 10.0) == pytest.approx(0.0)

    def test_zero_vol(self):
        assert _forecast_borrow_apr_vol_pct(3.0, 0.0) == pytest.approx(0.0)

    def test_floored_at_zero_negative_sensitivity(self):
        assert _forecast_borrow_apr_vol_pct(-3.0, 8.0) == pytest.approx(0.0)

    def test_floored_at_zero_negative_vol(self):
        assert _forecast_borrow_apr_vol_pct(3.0, -8.0) == pytest.approx(0.0)

    def test_never_negative(self):
        for s in [-5.0, 0.0, 0.05, 3.0]:
            for v in [-10.0, 0.0, 10.0]:
                assert _forecast_borrow_apr_vol_pct(s, v) >= 0.0

    def test_returns_float(self):
        assert isinstance(_forecast_borrow_apr_vol_pct(3.0, 8.0), float)

    def test_higher_sensitivity_higher_vol(self):
        low = _forecast_borrow_apr_vol_pct(0.05, 10.0)
        high = _forecast_borrow_apr_vol_pct(3.0, 10.0)
        assert high > low

    def test_higher_util_vol_higher_forecast(self):
        low = _forecast_borrow_apr_vol_pct(3.0, 2.0)
        high = _forecast_borrow_apr_vol_pct(3.0, 20.0)
        assert high > low


# ===========================================================================
# 4. _borrow_apr_p95 / p05
# ===========================================================================

class TestCones:
    def test_p95_basic(self):
        # 10 + 1.645 * 5 = 18.225
        assert _borrow_apr_p95_pct(10.0, 5.0) == pytest.approx(18.225)

    def test_p05_basic(self):
        # 10 - 1.645 * 5 = 1.775
        assert _borrow_apr_p05_pct(10.0, 5.0) == pytest.approx(1.775)

    def test_p05_floored_at_zero(self):
        # 2 - 1.645 * 10 < 0 -> 0
        assert _borrow_apr_p05_pct(2.0, 10.0) == pytest.approx(0.0)

    def test_p95_above_p05(self):
        p95 = _borrow_apr_p95_pct(10.0, 5.0)
        p05 = _borrow_apr_p05_pct(10.0, 5.0)
        assert p95 > p05

    def test_zero_vol_p95_equals_current(self):
        assert _borrow_apr_p95_pct(10.0, 0.0) == pytest.approx(10.0)

    def test_zero_vol_p05_equals_current(self):
        assert _borrow_apr_p05_pct(10.0, 0.0) == pytest.approx(10.0)

    def test_p95_returns_float(self):
        assert isinstance(_borrow_apr_p95_pct(10.0, 5.0), float)

    def test_p05_returns_float(self):
        assert isinstance(_borrow_apr_p05_pct(10.0, 5.0), float)

    def test_p05_never_negative(self):
        for c in [0.0, 5.0, 50.0]:
            for v in [0.0, 5.0, 100.0]:
                assert _borrow_apr_p05_pct(c, v) >= 0.0

    def test_higher_vol_wider_p95(self):
        low = _borrow_apr_p95_pct(10.0, 2.0)
        high = _borrow_apr_p95_pct(10.0, 20.0)
        assert high > low


# ===========================================================================
# 5. net carry
# ===========================================================================

class TestNetCarry:
    def test_now_basic(self):
        assert _net_carry_now_pct(8.0, 4.0) == pytest.approx(4.0)

    def test_now_negative(self):
        assert _net_carry_now_pct(4.0, 8.0) == pytest.approx(-4.0)

    def test_now_zero(self):
        assert _net_carry_now_pct(5.0, 5.0) == pytest.approx(0.0)

    def test_p95_basic(self):
        assert _net_carry_at_p95_borrow_pct(8.0, 18.0) == pytest.approx(-10.0)

    def test_p95_positive(self):
        assert _net_carry_at_p95_borrow_pct(20.0, 10.0) == pytest.approx(10.0)

    def test_p95_lower_than_now(self):
        # p95 borrow > current borrow -> carry lower
        now = _net_carry_now_pct(10.0, 4.0)
        p95 = _net_carry_at_p95_borrow_pct(10.0, 8.0)
        assert p95 < now

    def test_now_returns_float(self):
        assert isinstance(_net_carry_now_pct(8.0, 4.0), float)

    def test_p95_returns_float(self):
        assert isinstance(_net_carry_at_p95_borrow_pct(8.0, 18.0), float)

    def test_higher_farm_higher_carry(self):
        low = _net_carry_now_pct(5.0, 4.0)
        high = _net_carry_now_pct(15.0, 4.0)
        assert high > low

    def test_higher_borrow_lower_carry(self):
        low_b = _net_carry_now_pct(10.0, 2.0)
        high_b = _net_carry_now_pct(10.0, 8.0)
        assert high_b < low_b


# ===========================================================================
# 6. _carry_wipeout_probability_pct
# ===========================================================================

class TestWipeoutProb:
    def test_positive_carry_zero_vol(self):
        # carry positive, no vol -> 0%
        assert _carry_wipeout_probability_pct(10.0, 4.0, 0.0) == pytest.approx(0.0)

    def test_negative_carry_zero_vol(self):
        # carry negative, no vol -> 100%
        assert _carry_wipeout_probability_pct(4.0, 10.0, 0.0) == pytest.approx(100.0)

    def test_break_even_zero_vol(self):
        # carry == 0 -> 0% (>= 0 branch)
        assert _carry_wipeout_probability_pct(5.0, 5.0, 0.0) == pytest.approx(0.0)

    def test_break_even_with_vol_is_50(self):
        # z = 0 -> sf=0.5 -> 50%
        assert _carry_wipeout_probability_pct(5.0, 5.0, 3.0) == pytest.approx(50.0)

    def test_one_sigma_carry(self):
        # carry=3, vol=3 -> z=1 -> sf(1)~0.1587 -> ~15.87%
        assert _carry_wipeout_probability_pct(7.0, 4.0, 3.0) == pytest.approx(15.87, abs=0.2)

    def test_negative_carry_with_vol_high(self):
        # carry=-3, vol=3 -> z=-1 -> sf(-1)~0.8413 -> ~84%
        p = _carry_wipeout_probability_pct(1.0, 4.0, 3.0)
        assert p == pytest.approx(84.13, abs=0.3)

    def test_bounded_0_100(self):
        for farm in [-10.0, 0.0, 10.0, 100.0]:
            for borrow in [0.0, 5.0, 50.0]:
                for vol in [0.0, 1.0, 10.0, 100.0]:
                    p = _carry_wipeout_probability_pct(farm, borrow, vol)
                    assert 0.0 <= p <= 100.0

    def test_fat_carry_low_prob(self):
        # huge carry, small vol -> ~0%
        assert _carry_wipeout_probability_pct(100.0, 4.0, 1.0) < 1.0

    def test_higher_vol_higher_prob_when_positive_carry(self):
        low = _carry_wipeout_probability_pct(10.0, 4.0, 1.0)
        high = _carry_wipeout_probability_pct(10.0, 4.0, 20.0)
        assert high > low

    def test_no_zero_division(self):
        _carry_wipeout_probability_pct(10.0, 4.0, 0.0)

    def test_returns_float(self):
        assert isinstance(_carry_wipeout_probability_pct(10.0, 4.0, 3.0), float)

    def test_lower_carry_higher_prob(self):
        high_carry = _carry_wipeout_probability_pct(20.0, 4.0, 5.0)
        low_carry = _carry_wipeout_probability_pct(6.0, 4.0, 5.0)
        assert low_carry > high_carry


# ===========================================================================
# 7. _rate_stability_score
# ===========================================================================

class TestStabilityScore:
    def test_no_data_zero(self):
        s = _rate_stability_score(2.0, 5.0, 5.0, has_data=False)
        assert s == 0.0

    def test_very_stable_high_score(self):
        # zero vol, fat carry, zero wipeout
        s = _rate_stability_score(0.0, 10.0, 0.0, has_data=True)
        assert s == pytest.approx(100.0)

    def test_highly_volatile_low_score(self):
        s = _rate_stability_score(50.0, -10.0, 100.0, has_data=True)
        assert s < 10.0

    def test_bounded_0_100(self):
        for vol in [0.0, 3.0, 12.0, 50.0]:
            for carry in [-10.0, 0.0, 5.0, 20.0]:
                for wp in [0.0, 25.0, 50.0, 100.0]:
                    s = _rate_stability_score(vol, carry, wp, has_data=True)
                    assert 0.0 <= s <= 100.0

    def test_lower_vol_higher_score(self):
        low_vol = _rate_stability_score(1.0, 5.0, 10.0, has_data=True)
        high_vol = _rate_stability_score(10.0, 5.0, 10.0, has_data=True)
        assert low_vol > high_vol

    def test_higher_carry_higher_score(self):
        low = _rate_stability_score(3.0, 1.0, 10.0, has_data=True)
        high = _rate_stability_score(3.0, 9.0, 10.0, has_data=True)
        assert high > low

    def test_lower_wipeout_higher_score(self):
        low_wp = _rate_stability_score(3.0, 5.0, 5.0, has_data=True)
        high_wp = _rate_stability_score(3.0, 5.0, 80.0, has_data=True)
        assert low_wp > high_wp

    def test_negative_carry_contributes_zero(self):
        s = _rate_stability_score(50.0, -50.0, 100.0, has_data=True)
        assert s == pytest.approx(0.0)

    def test_returns_float(self):
        assert isinstance(_rate_stability_score(3.0, 5.0, 10.0, has_data=True), float)


# ===========================================================================
# 8. _classify
# ===========================================================================

class TestClassify:
    def test_no_data_very_stable(self):
        assert _classify(50.0, 0.0, has_data=False) == CLASS_VERY_STABLE

    def test_very_stable(self):
        assert _classify(0.5, 0.0, has_data=True) == CLASS_VERY_STABLE

    def test_stable(self):
        assert _classify(2.0, 0.0, has_data=True) == CLASS_STABLE

    def test_moderate(self):
        assert _classify(4.0, 0.0, has_data=True) == CLASS_MODERATE

    def test_volatile(self):
        assert _classify(8.0, 0.0, has_data=True) == CLASS_VOLATILE

    def test_highly_volatile(self):
        assert _classify(20.0, 0.0, has_data=True) == CLASS_HIGHLY_VOLATILE

    def test_wipeout_forces_moderate(self):
        # low vol but high wipeout prob -> at least MODERATE
        c = _classify(0.5, 30.0, has_data=True)
        assert c in (CLASS_MODERATE, CLASS_VOLATILE, CLASS_HIGHLY_VOLATILE)

    def test_wipeout_does_not_downgrade_worse(self):
        c = _classify(20.0, 30.0, has_data=True)
        assert c == CLASS_HIGHLY_VOLATILE

    def test_boundary_1(self):
        assert _classify(0.999, 0.0, has_data=True) == CLASS_VERY_STABLE
        assert _classify(1.0, 0.0, has_data=True) == CLASS_STABLE

    def test_boundary_3(self):
        assert _classify(2.999, 0.0, has_data=True) == CLASS_STABLE
        assert _classify(3.0, 0.0, has_data=True) == CLASS_MODERATE

    def test_boundary_6(self):
        assert _classify(5.999, 0.0, has_data=True) == CLASS_MODERATE
        assert _classify(6.0, 0.0, has_data=True) == CLASS_VOLATILE

    def test_boundary_12(self):
        assert _classify(11.999, 0.0, has_data=True) == CLASS_VOLATILE
        assert _classify(12.0, 0.0, has_data=True) == CLASS_HIGHLY_VOLATILE

    def test_all_bands_reachable(self):
        seen = {
            _classify(0.5, 0.0, has_data=True),
            _classify(2.0, 0.0, has_data=True),
            _classify(4.0, 0.0, has_data=True),
            _classify(8.0, 0.0, has_data=True),
            _classify(20.0, 0.0, has_data=True),
        }
        assert seen == set(ALL_CLASSIFICATIONS)

    def test_returns_valid(self):
        for vol in [0.0, 1.0, 3.0, 6.0, 12.0, 50.0]:
            for wp in [0.0, 30.0]:
                c = _classify(vol, wp, has_data=True)
                assert c in ALL_CLASSIFICATIONS

    def test_wipeout_threshold_exact(self):
        # exactly 25% forces moderate from stable
        c = _classify(2.0, 25.0, has_data=True)
        assert c == CLASS_MODERATE

    def test_wipeout_below_threshold_no_force(self):
        c = _classify(2.0, 24.0, has_data=True)
        assert c == CLASS_STABLE


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
        f = _flags(20.0, 50.0, 3.0, -5.0, -10.0, has_data=False)
        assert f == [FLAG_INSUFFICIENT_DATA]

    def test_high_rate_volatility(self):
        f = _flags(10.0, 5.0, 0.5, 5.0, 2.0, has_data=True)
        assert FLAG_HIGH_RATE_VOLATILITY in f

    def test_low_vol_no_flag(self):
        f = _flags(2.0, 5.0, 0.05, 5.0, 4.0, has_data=True)
        assert FLAG_HIGH_RATE_VOLATILITY not in f

    def test_carry_wipeout_risk(self):
        f = _flags(2.0, 30.0, 0.05, 5.0, 4.0, has_data=True)
        assert FLAG_CARRY_WIPEOUT_RISK in f

    def test_low_wipeout_no_flag(self):
        f = _flags(2.0, 10.0, 0.05, 5.0, 4.0, has_data=True)
        assert FLAG_CARRY_WIPEOUT_RISK not in f

    def test_high_sensitivity(self):
        f = _flags(2.0, 5.0, 3.0, 5.0, 4.0, has_data=True)
        assert FLAG_HIGH_UTILIZATION_SENSITIVITY in f

    def test_low_sensitivity_no_flag(self):
        f = _flags(2.0, 5.0, 0.05, 5.0, 4.0, has_data=True)
        assert FLAG_HIGH_UTILIZATION_SENSITIVITY not in f

    def test_negative_carry_at_p95(self):
        f = _flags(2.0, 5.0, 0.05, 5.0, -3.0, has_data=True)
        assert FLAG_NEGATIVE_CARRY_AT_P95 in f

    def test_positive_p95_no_flag(self):
        f = _flags(2.0, 5.0, 0.05, 5.0, 3.0, has_data=True)
        assert FLAG_NEGATIVE_CARRY_AT_P95 not in f

    def test_thin_carry_margin(self):
        f = _flags(2.0, 5.0, 0.05, 0.5, 0.2, has_data=True)
        assert FLAG_THIN_CARRY_MARGIN in f

    def test_fat_carry_no_thin_flag(self):
        f = _flags(2.0, 5.0, 0.05, 8.0, 6.0, has_data=True)
        assert FLAG_THIN_CARRY_MARGIN not in f

    def test_negative_carry_is_thin(self):
        f = _flags(2.0, 5.0, 0.05, -2.0, -4.0, has_data=True)
        assert FLAG_THIN_CARRY_MARGIN in f

    def test_stable_borrow_cost(self):
        f = _flags(0.5, 5.0, 0.05, 8.0, 6.0, has_data=True)
        assert FLAG_STABLE_BORROW_COST in f

    def test_high_vol_no_stable_flag(self):
        f = _flags(5.0, 5.0, 0.05, 8.0, 6.0, has_data=True)
        assert FLAG_STABLE_BORROW_COST not in f

    def test_all_flags_valid(self):
        f = _flags(20.0, 50.0, 3.0, 0.5, -10.0, has_data=True)
        for flag in f:
            assert flag in ALL_FLAGS

    def test_wipeout_threshold_exact(self):
        f = _flags(2.0, 25.0, 0.05, 5.0, 4.0, has_data=True)
        assert FLAG_CARRY_WIPEOUT_RISK in f


# ===========================================================================
# 11. _recommendations
# ===========================================================================

class TestRecommendations:
    def test_insufficient_data(self):
        recs = _recommendations(
            CLASS_VERY_STABLE, [FLAG_INSUFFICIENT_DATA], 0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, has_data=False,
        )
        assert len(recs) >= 1
        assert any("insufficient" in r.lower() for r in recs)

    def test_highly_volatile_mentions(self):
        recs = _recommendations(
            CLASS_HIGHLY_VOLATILE, [], 24.0, 46.0, 85.0, 4.0, -35.0, 43.0,
            has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "volatile" in combined

    def test_returns_list_each_class(self):
        for c in ALL_CLASSIFICATIONS:
            recs = _recommendations(
                c, [], 3.0, 8.0, 12.0, 4.0, 2.0, 10.0, has_data=True,
            )
            assert isinstance(recs, list)
            assert len(recs) >= 1

    def test_wipeout_mentioned(self):
        recs = _recommendations(
            CLASS_MODERATE, [FLAG_CARRY_WIPEOUT_RISK], 4.0, 8.0, 14.0, 2.0,
            -2.0, 40.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "wipeout" in combined or "carry" in combined

    def test_negative_p95_mentioned(self):
        recs = _recommendations(
            CLASS_VOLATILE, [FLAG_NEGATIVE_CARRY_AT_P95], 8.0, 10.0, 23.0,
            2.0, -13.0, 20.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "p95" in combined or "stress" in combined or "negative" in combined

    def test_high_sensitivity_mentioned(self):
        recs = _recommendations(
            CLASS_VOLATILE, [FLAG_HIGH_UTILIZATION_SENSITIVITY], 8.0, 10.0,
            23.0, 2.0, 1.0, 10.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "sensitiv" in combined or "kink" in combined or "slope" in combined

    def test_thin_margin_mentioned(self):
        recs = _recommendations(
            CLASS_STABLE, [FLAG_THIN_CARRY_MARGIN], 2.0, 8.0, 11.0, 0.5,
            -0.5, 5.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "thin" in combined or "margin" in combined or "carry" in combined

    def test_stable_mentioned(self):
        recs = _recommendations(
            CLASS_VERY_STABLE, [FLAG_STABLE_BORROW_COST], 0.5, 4.0, 5.0,
            6.0, 5.0, 1.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "stable" in combined


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

    def test_recovers_from_non_list(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump({"not": "a list"}, f)
        _atomic_log(path, {"ok": True})
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 1
        os.unlink(path)

    def test_creates_parent_dirs(self):
        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "a", "b", "log.json")
        _atomic_log(path, {"deep": True})
        assert os.path.exists(path)

    def test_handles_missing_file(self):
        path = _tmp_log()
        assert not os.path.exists(path)
        _atomic_log(path, {"first": True})
        assert os.path.exists(path)
        os.unlink(path)

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

    def test_safe_float_int(self):
        assert _safe_float(5) == 5.0

    def test_safe_float_string(self):
        assert _safe_float("10") == 10.0

    def test_safe_float_negative_string(self):
        assert _safe_float("-3.5") == -3.5

    def test_safe_float_invalid(self):
        assert _safe_float("abc") == 0.0

    def test_safe_float_none(self):
        assert _safe_float(None) == 0.0

    def test_safe_float_list(self):
        assert _safe_float([1, 2]) == 0.0

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

    def test_clamp_exact_bounds(self):
        assert _clamp(0.0) == 0.0
        assert _clamp(100.0) == 100.0


# ===========================================================================
# 14. analyze - integration
# ===========================================================================

class TestAnalyze:
    def test_returns_dict(self):
        r = analyze(_market(), config=_cfg())
        assert isinstance(r, dict)

    def test_required_keys(self):
        r = analyze(_market(), config=_cfg())
        for key in [
            "name",
            "current_borrow_apr_pct",
            "rate_sensitivity_factor",
            "forecast_borrow_apr_vol_pct",
            "borrow_apr_p95_pct",
            "borrow_apr_p05_pct",
            "net_carry_now_pct",
            "net_carry_at_p95_borrow_pct",
            "carry_wipeout_probability_pct",
            "rate_stability_score",
            "classification",
            "grade",
            "flags",
            "recommendations",
            "timestamp",
        ]:
            assert key in r

    def test_sensitivity_math_below_kink(self):
        r = analyze(_market(current_utilization_pct=50.0, kink_utilization_pct=80.0,
                            slope1_pct=4.0, slope2_pct=60.0), config=_cfg())
        assert r["rate_sensitivity_factor"] == pytest.approx(0.05)

    def test_sensitivity_math_above_kink(self):
        r = analyze(_market(current_utilization_pct=90.0, kink_utilization_pct=80.0,
                            slope1_pct=4.0, slope2_pct=60.0), config=_cfg())
        assert r["rate_sensitivity_factor"] == pytest.approx(3.0)

    def test_forecast_vol_math(self):
        # sensitivity 3.0 (above kink), util_vol 8 -> 24
        r = analyze(_market(current_utilization_pct=90.0, utilization_volatility_pct=8.0),
                    config=_cfg())
        assert r["forecast_borrow_apr_vol_pct"] == pytest.approx(24.0)

    def test_p95_math(self):
        # borrow 46, vol 24 -> 46 + 1.645*24 = 85.48
        r = analyze(_market(current_borrow_apr_pct=46.0, current_utilization_pct=94.0,
                            utilization_volatility_pct=8.0), config=_cfg())
        assert r["borrow_apr_p95_pct"] == pytest.approx(85.48)

    def test_net_carry_now_math(self):
        r = analyze(_market(farm_apr_pct=8.0, current_borrow_apr_pct=4.0),
                    config=_cfg())
        assert r["net_carry_now_pct"] == pytest.approx(4.0)

    def test_net_carry_p95_math(self):
        r = analyze(_market(current_borrow_apr_pct=46.0, current_utilization_pct=94.0,
                            utilization_volatility_pct=8.0, farm_apr_pct=50.0),
                    config=_cfg())
        # 50 - 85.48 = -35.48
        assert r["net_carry_at_p95_borrow_pct"] == pytest.approx(-35.48)

    def test_classification_valid(self):
        r = analyze(_market(), config=_cfg())
        assert r["classification"] in ALL_CLASSIFICATIONS

    def test_grade_valid(self):
        r = analyze(_market(), config=_cfg())
        assert r["grade"] in ALL_GRADES

    def test_volatile_scenario(self):
        r = analyze(_volatile(), config=_cfg())
        assert r["classification"] in (CLASS_VOLATILE, CLASS_HIGHLY_VOLATILE)
        assert FLAG_HIGH_RATE_VOLATILITY in r["flags"]

    def test_stable_scenario(self):
        r = analyze(_stable(), config=_cfg())
        assert r["classification"] in (CLASS_VERY_STABLE, CLASS_STABLE, CLASS_MODERATE)

    def test_high_sensitivity_flag(self):
        r = analyze(_volatile(), config=_cfg())
        assert FLAG_HIGH_UTILIZATION_SENSITIVITY in r["flags"]

    def test_carry_wipeout_flag(self):
        r = analyze(_volatile(), config=_cfg())
        assert FLAG_CARRY_WIPEOUT_RISK in r["flags"]

    def test_negative_p95_flag(self):
        r = analyze(_volatile(), config=_cfg())
        assert FLAG_NEGATIVE_CARRY_AT_P95 in r["flags"]

    def test_stable_borrow_cost_flag(self):
        r = analyze(_market(current_utilization_pct=30.0,
                            utilization_volatility_pct=2.0), config=_cfg())
        assert FLAG_STABLE_BORROW_COST in r["flags"]

    def test_thin_carry_flag(self):
        r = analyze(_market(farm_apr_pct=4.5, current_borrow_apr_pct=4.0),
                    config=_cfg())
        assert FLAG_THIN_CARRY_MARGIN in r["flags"]

    def test_insufficient_data_flag(self):
        r = analyze(_market(current_borrow_apr_pct=0.0, current_utilization_pct=0.0,
                            farm_apr_pct=0.0), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]
        assert r["classification"] == CLASS_VERY_STABLE

    def test_poor_data_quality(self):
        r = analyze(_market(data_quality="poor"), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]

    def test_name_preserved(self):
        r = analyze(_market(name="USDC"), config=_cfg())
        assert r["name"] == "USDC"

    def test_recommendations_list(self):
        r = analyze(_market(), config=_cfg())
        assert isinstance(r["recommendations"], list)
        assert len(r["recommendations"]) >= 1

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_market(), config=_cfg())
        after = time.time()
        assert before <= r["timestamp"] <= after

    def test_flags_valid(self):
        r = analyze(_volatile(), config=_cfg())
        for flag in r["flags"]:
            assert flag in ALL_FLAGS

    def test_score_bounded(self):
        r = analyze(_market(), config=_cfg())
        assert 0.0 <= r["rate_stability_score"] <= 100.0

    def test_wipeout_bounded(self):
        r = analyze(_market(), config=_cfg())
        assert 0.0 <= r["carry_wipeout_probability_pct"] <= 100.0

    def test_p05_non_negative(self):
        r = analyze(_market(), config=_cfg())
        assert r["borrow_apr_p05_pct"] >= 0.0

    def test_kwargs_override_dict(self):
        r = analyze(_market(current_borrow_apr_pct=4.0),
                    current_borrow_apr_pct=20.0, config=_cfg())
        assert r["current_borrow_apr_pct"] == 20.0

    def test_kwargs_only(self):
        r = analyze(current_utilization_pct=90.0, utilization_volatility_pct=8.0,
                    config=_cfg())
        assert r["forecast_borrow_apr_vol_pct"] == pytest.approx(24.0)

    def test_util_clamped(self):
        r = analyze(_market(current_utilization_pct=150.0), config=_cfg())
        assert r["current_utilization_pct"] == 100.0


# ===========================================================================
# 15. analyze - robustness / no crash
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
        r = analyze({"name": "X", "current_utilization_pct": "90",
                     "utilization_volatility_pct": "8"}, config=_cfg())
        assert r["forecast_borrow_apr_vol_pct"] == pytest.approx(24.0)

    def test_garbage_numeric_fields(self):
        r = analyze({"name": "X", "current_borrow_apr_pct": "abc",
                     "current_utilization_pct": None}, config=_cfg())
        assert "classification" in r

    def test_no_zero_division_all_zeros(self):
        r = analyze(_market(current_borrow_apr_pct=0.0, current_utilization_pct=0.0,
                            utilization_volatility_pct=0.0, kink_utilization_pct=0.0,
                            slope1_pct=0.0, slope2_pct=0.0, farm_apr_pct=0.0),
                    config=_cfg())
        assert "classification" in r

    def test_kink_zero_no_crash(self):
        r = analyze(_market(kink_utilization_pct=0.0, current_utilization_pct=50.0),
                    config=_cfg())
        assert "classification" in r

    def test_kink_100_no_crash(self):
        r = analyze(_market(kink_utilization_pct=100.0, current_utilization_pct=100.0),
                    config=_cfg())
        assert "classification" in r

    def test_zero_vol_no_crash(self):
        r = analyze(_market(utilization_volatility_pct=0.0), config=_cfg())
        assert math.isfinite(r["carry_wipeout_probability_pct"])

    def test_does_not_raise_on_bad_log_path(self):
        r = analyze(_market(), config={"log_path": "/dev/null/cannot/log.json"})
        assert "classification" in r

    def test_default_log_path_used(self):
        r = analyze(_market())
        assert "classification" in r

    def test_extreme_values(self):
        r = analyze(_market(current_borrow_apr_pct=1e9, utilization_volatility_pct=1e9,
                            slope2_pct=1e9, current_utilization_pct=99.0),
                    config=_cfg())
        assert 0.0 <= r["rate_stability_score"] <= 100.0

    def test_negative_values(self):
        r = analyze(_market(current_borrow_apr_pct=-10.0, slope1_pct=-4.0,
                            utilization_volatility_pct=-5.0), config=_cfg())
        assert "classification" in r

    def test_huge_numbers(self):
        r = analyze(_market(farm_apr_pct=1e300, current_borrow_apr_pct=1e300),
                    config=_cfg())
        assert math.isfinite(r["rate_stability_score"])

    def test_garbage_strings_everywhere(self):
        r = analyze({"name": 123, "current_borrow_apr_pct": "xx",
                     "current_utilization_pct": "yy",
                     "utilization_volatility_pct": [],
                     "kink_utilization_pct": {}, "slope1_pct": "z",
                     "slope2_pct": "w", "farm_apr_pct": "v",
                     "horizon_days": "h"}, config=_cfg())
        assert "classification" in r


# ===========================================================================
# 16. Logging via config
# ===========================================================================

class TestLogging:
    def test_writes_log(self):
        path = _tmp_log()
        analyze(_market(), config={"log_path": path})
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 1
        os.unlink(path)

    def test_log_accumulates(self):
        path = _tmp_log()
        analyze(_market(name="A"), config={"log_path": path})
        analyze(_market(name="B"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 2
        assert data[0]["name"] == "A"
        assert data[1]["name"] == "B"
        os.unlink(path)

    def test_log_ring_buffer_cap(self, tmp_path):
        path = str(tmp_path / "vol_log.json")
        for i in range(120):
            analyze(_market(name=f"T{i}"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 100
        assert data[-1]["name"] == "T119"
        assert data[0]["name"] == "T20"

    def test_idempotent_rerun(self, tmp_path):
        path = str(tmp_path / "vol_log.json")
        m = _market(name="Same")
        r1 = analyze(m, config={"log_path": path})
        r2 = analyze(m, config={"log_path": path})
        assert r1["classification"] == r2["classification"]
        assert r1["rate_stability_score"] == r2["rate_stability_score"]
        assert r1["flags"] == r2["flags"]

    def test_log_via_tmp_path(self, tmp_path):
        path = str(tmp_path / "out.json")
        analyze(_market(), config={"log_path": path})
        assert os.path.exists(path)

    def test_log_is_valid_json(self, tmp_path):
        path = str(tmp_path / "vol_log.json")
        for i in range(150):
            analyze(_market(name=f"T{i}"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) <= 100


# ===========================================================================
# 17. Determinism
# ===========================================================================

class TestDeterminism:
    def test_same_inputs_same_metrics(self):
        m = _market(name="Det")
        r1 = analyze(m, config=_cfg())
        r2 = analyze(m, config=_cfg())
        assert r1["forecast_borrow_apr_vol_pct"] == r2["forecast_borrow_apr_vol_pct"]
        assert r1["rate_stability_score"] == r2["rate_stability_score"]
        assert r1["classification"] == r2["classification"]
        assert r1["grade"] == r2["grade"]

    def test_score_deterministic(self):
        s1 = _rate_stability_score(3.0, 5.0, 10.0, has_data=True)
        s2 = _rate_stability_score(3.0, 5.0, 10.0, has_data=True)
        assert s1 == s2


# ===========================================================================
# 18. Monotonicity sanity
# ===========================================================================

class TestMonotonicity:
    def test_volatile_lower_score_than_stable(self):
        stable = analyze(_stable(), config=_cfg())
        volatile = analyze(_volatile(), config=_cfg())
        assert volatile["rate_stability_score"] < stable["rate_stability_score"]

    def test_higher_util_vol_higher_forecast(self):
        low = analyze(_market(current_utilization_pct=90.0,
                              utilization_volatility_pct=2.0), config=_cfg())
        high = analyze(_market(current_utilization_pct=90.0,
                               utilization_volatility_pct=20.0), config=_cfg())
        assert high["forecast_borrow_apr_vol_pct"] > low["forecast_borrow_apr_vol_pct"]

    def test_above_kink_higher_sensitivity(self):
        below = analyze(_market(current_utilization_pct=50.0), config=_cfg())
        above = analyze(_market(current_utilization_pct=90.0), config=_cfg())
        assert above["rate_sensitivity_factor"] > below["rate_sensitivity_factor"]

    def test_higher_farm_higher_carry(self):
        low = analyze(_market(farm_apr_pct=5.0), config=_cfg())
        high = analyze(_market(farm_apr_pct=15.0), config=_cfg())
        assert high["net_carry_now_pct"] > low["net_carry_now_pct"]

    def test_higher_vol_wider_p95(self):
        low = analyze(_market(current_utilization_pct=90.0,
                              utilization_volatility_pct=2.0), config=_cfg())
        high = analyze(_market(current_utilization_pct=90.0,
                               utilization_volatility_pct=20.0), config=_cfg())
        assert high["borrow_apr_p95_pct"] > low["borrow_apr_p95_pct"]

    def test_lower_vol_higher_stability(self):
        low_vol = analyze(_market(current_utilization_pct=30.0,
                                  utilization_volatility_pct=2.0,
                                  farm_apr_pct=10.0), config=_cfg())
        high_vol = analyze(_market(current_utilization_pct=95.0,
                                   utilization_volatility_pct=20.0,
                                   farm_apr_pct=10.0), config=_cfg())
        assert low_vol["rate_stability_score"] > high_vol["rate_stability_score"]


# ===========================================================================
# 19. analyze_portfolio
# ===========================================================================

class TestAnalyzePortfolio:
    def test_empty_list(self):
        s = analyze_portfolio([], config=_cfg())
        assert s["total_positions"] == 0
        assert s["most_stable_market"] is None
        assert s["most_volatile_market"] is None
        assert s["avg_rate_stability_score"] == 0.0
        assert s["wipeout_risk_count"] == 0
        assert s["results"] == []

    def test_summary_keys_present(self):
        s = analyze_portfolio([_market()], config=_cfg())
        for key in ["total_positions", "results", "most_stable_market",
                    "most_volatile_market", "avg_rate_stability_score",
                    "wipeout_risk_count", "timestamp"]:
            assert key in s

    def test_single_position(self):
        s = analyze_portfolio([_market(name="Solo")], config=_cfg())
        assert s["total_positions"] == 1
        assert s["most_stable_market"] == "Solo"
        assert s["most_volatile_market"] == "Solo"
        assert len(s["results"]) == 1

    def test_multiple_stable_volatile(self):
        s = analyze_portfolio([_volatile("Vol"), _stable("Stab")], config=_cfg())
        assert s["total_positions"] == 2
        assert s["most_stable_market"] == "Stab"
        assert s["most_volatile_market"] == "Vol"

    def test_avg_score(self):
        markets = [_market(name="A"), _market(name="B")]
        s = analyze_portfolio(markets, config=_cfg())
        per = [r["rate_stability_score"] for r in s["results"]]
        assert s["avg_rate_stability_score"] == pytest.approx(sum(per) / len(per))

    def test_wipeout_risk_count(self):
        markets = [_stable("S"), _volatile("V1"), _volatile("V2")]
        s = analyze_portfolio(markets, config=_cfg())
        assert s["wipeout_risk_count"] == 2

    def test_results_count_matches(self):
        markets = [_market(name=f"T{i}") for i in range(5)]
        s = analyze_portfolio(markets, config=_cfg())
        assert len(s["results"]) == 5
        assert s["total_positions"] == 5

    def test_non_list_input(self):
        s = analyze_portfolio("notalist", config=_cfg())
        assert s["total_positions"] == 0

    def test_handles_non_dict_entries(self):
        s = analyze_portfolio([_market(name="ok"), "garbage", 42], config=_cfg())
        assert s["total_positions"] == 3

    def test_all_results_have_classification(self):
        markets = [_market(name=f"T{i}") for i in range(3)]
        s = analyze_portfolio(markets, config=_cfg())
        for r in s["results"]:
            assert r["classification"] in ALL_CLASSIFICATIONS

    def test_avg_bounded(self):
        markets = [_volatile("V"), _stable("S"), _market(name="Mid")]
        s = analyze_portfolio(markets, config=_cfg())
        assert 0.0 <= s["avg_rate_stability_score"] <= 100.0

    def test_many_positions(self):
        markets = [_market(name=f"T{i}", current_utilization_pct=float(i % 100))
                   for i in range(50)]
        s = analyze_portfolio(markets, config=_cfg())
        assert s["total_positions"] == 50
        assert len(s["results"]) == 50

    def test_wipeout_count_via_negative_p95(self):
        # a position with negative carry at p95 but lower wipeout prob still counts
        markets = [_stable("S"), _volatile("V")]
        s = analyze_portfolio(markets, config=_cfg())
        assert s["wipeout_risk_count"] >= 1


# ===========================================================================
# 20. Class wrapper parity
# ===========================================================================

class TestClassWrapper:
    def test_instantiation(self):
        f = DeFiProtocolBorrowRateVolatilityForecaster()
        assert f is not None

    def test_analyze_returns_dict(self):
        f = DeFiProtocolBorrowRateVolatilityForecaster(config=_cfg())
        r = f.analyze(_market())
        assert isinstance(r, dict)

    def test_analyze_parity(self):
        cfg = _cfg()
        m = _market(name="Parity")
        r_func = analyze(m, config=cfg)
        r_class = DeFiProtocolBorrowRateVolatilityForecaster(
            config=cfg).analyze(m)
        assert r_func["classification"] == r_class["classification"]
        assert r_func["rate_stability_score"] == r_class["rate_stability_score"]
        assert r_func["flags"] == r_class["flags"]

    def test_analyze_kwargs_via_class(self):
        f = DeFiProtocolBorrowRateVolatilityForecaster(config=_cfg())
        r = f.analyze(current_utilization_pct=90.0, utilization_volatility_pct=8.0)
        assert r["forecast_borrow_apr_vol_pct"] == pytest.approx(24.0)

    def test_portfolio_parity(self):
        cfg = _cfg()
        markets = [_market(name="A"), _market(name="B")]
        r_func = analyze_portfolio(markets, config=cfg)
        r_class = DeFiProtocolBorrowRateVolatilityForecaster(
            config=cfg).analyze_portfolio(markets)
        assert r_func["total_positions"] == r_class["total_positions"]
        assert r_func["most_stable_market"] == r_class["most_stable_market"]

    def test_config_forwarded_to_log(self):
        path = _tmp_log()
        f = DeFiProtocolBorrowRateVolatilityForecaster(config={"log_path": path})
        f.analyze(_market())
        assert os.path.exists(path)
        with open(path) as fh:
            data = json.load(fh)
        assert len(data) == 1
        os.unlink(path)

    def test_no_config_uses_default(self):
        f = DeFiProtocolBorrowRateVolatilityForecaster()
        r = f.analyze(_market())
        assert "classification" in r

    def test_multiple_calls_accumulate(self):
        path = _tmp_log()
        f = DeFiProtocolBorrowRateVolatilityForecaster(config={"log_path": path})
        f.analyze(_market(name="A"))
        f.analyze(_market(name="B"))
        with open(path) as fh:
            data = json.load(fh)
        assert len(data) == 2
        os.unlink(path)

    def test_class_portfolio_summary(self):
        f = DeFiProtocolBorrowRateVolatilityForecaster(config=_cfg())
        s = f.analyze_portfolio([_market(name="X")])
        assert s["total_positions"] == 1


# ===========================================================================
# 21. Constants sanity
# ===========================================================================

class TestConstants:
    def test_all_classifications_count(self):
        assert len(ALL_CLASSIFICATIONS) == 5

    def test_all_flags_count(self):
        assert len(ALL_FLAGS) == 7

    def test_classifications_unique(self):
        assert len(set(ALL_CLASSIFICATIONS)) == len(ALL_CLASSIFICATIONS)

    def test_flags_unique(self):
        assert len(set(ALL_FLAGS)) == len(ALL_FLAGS)

    def test_z_95(self):
        assert _Z_95 == pytest.approx(1.645)

    def test_eps_small(self):
        assert _EPS < 1e-6


# ===========================================================================
# 22. never-raises contract (parametrized garbage)
# ===========================================================================

@pytest.mark.parametrize("bad", [
    None, {}, [], "string", 42, 3.14, True, False,
    {"current_borrow_apr_pct": None},
    {"current_borrow_apr_pct": "abc"},
    {"current_utilization_pct": -100.0},
    {"current_utilization_pct": 1e18},
    {"utilization_volatility_pct": -10.0},
    {"utilization_volatility_pct": "x"},
    {"kink_utilization_pct": 0.0},
    {"kink_utilization_pct": -50.0},
    {"kink_utilization_pct": "y"},
    {"slope1_pct": float("inf")},
    {"slope2_pct": float("nan")},
    {"farm_apr_pct": -100.0},
    {"farm_apr_pct": 1e18},
    {"horizon_days": -30.0},
    {"horizon_days": "h"},
    {"name": None},
    {"name": 123},
    {"data_quality": None},
    {"data_quality": ""},
    {"data_quality": "poor"},
    {"data_quality": 0},
])
def test_never_raises_on_garbage(bad):
    r = analyze(bad, config=_cfg())
    assert isinstance(r, dict)
    assert "classification" in r
    assert r["classification"] in ALL_CLASSIFICATIONS
    assert r["grade"] in ALL_GRADES


@pytest.mark.parametrize("util", [-100.0, 0.0, 0.001, 40.0, 79.0, 80.0, 81.0, 99.0, 100.0, 1e9])
def test_never_raises_util_sweep(util):
    r = analyze(_market(current_utilization_pct=util), config=_cfg())
    assert isinstance(r, dict)
    assert 0.0 <= r["rate_stability_score"] <= 100.0


@pytest.mark.parametrize("vol", [-10.0, 0.0, 0.001, 1.0, 5.0, 10.0, 50.0, 1e9])
def test_never_raises_vol_sweep(vol):
    r = analyze(_market(utilization_volatility_pct=vol), config=_cfg())
    assert isinstance(r, dict)
    assert 0.0 <= r["carry_wipeout_probability_pct"] <= 100.0


@pytest.mark.parametrize("kink", [-50.0, 0.0, 1.0, 50.0, 80.0, 99.0, 100.0, 1e9])
def test_never_raises_kink_sweep(kink):
    r = analyze(_market(kink_utilization_pct=kink), config=_cfg())
    assert isinstance(r, dict)
    assert math.isfinite(r["rate_sensitivity_factor"])


@pytest.mark.parametrize("farm", [-100.0, 0.0, 4.0, 8.0, 50.0, 1e6])
def test_never_raises_farm_sweep(farm):
    r = analyze(_market(farm_apr_pct=farm), config=_cfg())
    assert isinstance(r, dict)
    assert math.isfinite(r["net_carry_now_pct"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
