"""
Tests for MP-1108 ProtocolDeFiInterestRateKinkProximityAnalyzer
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

from spa_core.analytics.protocol_defi_interest_rate_kink_proximity_analyzer import (
    analyze,
    analyze_portfolio,
    _borrow_apr_at_util,
    _utilization_headroom_pct,
    _rate_shock_if_crossed_pct,
    _supply_apr_now_pct,
    _liquidity_buffer_pct,
    _kink_proximity_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    ProtocolDeFiInterestRateKinkProximityAnalyzer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_AMPLE_HEADROOM,
    CLASS_COMFORTABLE,
    CLASS_APPROACHING_KINK,
    CLASS_AT_KINK,
    CLASS_PAST_KINK,
    FLAG_PAST_KINK,
    FLAG_AT_KINK,
    FLAG_THIN_LIQUIDITY_BUFFER,
    FLAG_STEEP_SECOND_SLOPE,
    FLAG_LARGE_RATE_SHOCK,
    FLAG_AMPLE_HEADROOM,
    FLAG_LOW_UTILIZATION_IDLE,
    FLAG_INSUFFICIENT_DATA,
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
    utilization_pct=50.0,
    kink_utilization_pct=80.0,
    base_rate_pct=0.0,
    slope1_pct=4.0,
    slope2_pct=60.0,
    reserve_factor_pct=10.0,
    available_liquidity_usd=50_000_000.0,
    total_supplied_usd=100_000_000.0,
    data_quality="ok",
):
    return {
        "name": name,
        "utilization_pct": utilization_pct,
        "kink_utilization_pct": kink_utilization_pct,
        "base_rate_pct": base_rate_pct,
        "slope1_pct": slope1_pct,
        "slope2_pct": slope2_pct,
        "reserve_factor_pct": reserve_factor_pct,
        "available_liquidity_usd": available_liquidity_usd,
        "total_supplied_usd": total_supplied_usd,
        "data_quality": data_quality,
    }


def _past_kink(name="PastKink"):
    return _market(
        name=name,
        utilization_pct=94.0,
        available_liquidity_usd=6_000_000.0,
        total_supplied_usd=100_000_000.0,
    )


def _ample(name="Ample"):
    return _market(
        name=name,
        utilization_pct=30.0,
        available_liquidity_usd=70_000_000.0,
        total_supplied_usd=100_000_000.0,
    )


def _cfg():
    return {"log_path": _tmp_log()}


# ===========================================================================
# 1. _borrow_apr_at_util
# ===========================================================================

class TestBorrowAprAtUtil:
    def test_at_zero_is_base_plus_zero(self):
        # below kink: base + slope1*(0/kink) = base
        assert _borrow_apr_at_util(0.0, 80.0, 0.0, 4.0, 60.0) == pytest.approx(0.0)

    def test_at_zero_with_base(self):
        assert _borrow_apr_at_util(0.0, 80.0, 2.0, 4.0, 60.0) == pytest.approx(2.0)

    def test_at_kink(self):
        # base + slope1
        assert _borrow_apr_at_util(80.0, 80.0, 0.0, 4.0, 60.0) == pytest.approx(4.0)

    def test_at_full(self):
        # base + slope1 + slope2
        assert _borrow_apr_at_util(100.0, 80.0, 0.0, 4.0, 60.0) == pytest.approx(64.0)

    def test_half_first_slope(self):
        # util=40, kink=80 -> base + 4*(40/80) = 2
        assert _borrow_apr_at_util(40.0, 80.0, 0.0, 4.0, 60.0) == pytest.approx(2.0)

    def test_midway_second_slope(self):
        # util=90, kink=80 -> 0 + 4 + 60*((90-80)/(100-80)) = 4 + 30 = 34
        assert _borrow_apr_at_util(90.0, 80.0, 0.0, 4.0, 60.0) == pytest.approx(34.0)

    def test_just_below_kink(self):
        r = _borrow_apr_at_util(79.0, 80.0, 0.0, 4.0, 60.0)
        assert r < 4.0

    def test_just_above_kink(self):
        r = _borrow_apr_at_util(81.0, 80.0, 0.0, 4.0, 60.0)
        assert r > 4.0

    def test_monotonic_increasing(self):
        prev = -1.0
        for u in range(0, 101, 5):
            cur = _borrow_apr_at_util(float(u), 80.0, 0.0, 4.0, 60.0)
            assert cur >= prev
            prev = cur

    def test_kink_zero_no_crash(self):
        # degenerate kink at 0 -> all second slope
        r = _borrow_apr_at_util(50.0, 0.0, 0.0, 4.0, 60.0)
        assert isinstance(r, float)

    def test_kink_zero_at_full(self):
        r = _borrow_apr_at_util(100.0, 0.0, 0.0, 4.0, 60.0)
        assert r == pytest.approx(64.0)

    def test_kink_100_no_crash(self):
        # kink at 100 -> 100-kink guarded with eps; util never exceeds
        r = _borrow_apr_at_util(100.0, 100.0, 0.0, 4.0, 60.0)
        assert isinstance(r, float)

    def test_kink_negative_guarded(self):
        r = _borrow_apr_at_util(50.0, -10.0, 0.0, 4.0, 60.0)
        assert isinstance(r, float)
        assert math.isfinite(r)

    def test_util_clamped_above_100(self):
        a = _borrow_apr_at_util(150.0, 80.0, 0.0, 4.0, 60.0)
        b = _borrow_apr_at_util(100.0, 80.0, 0.0, 4.0, 60.0)
        assert a == pytest.approx(b)

    def test_util_clamped_below_0(self):
        a = _borrow_apr_at_util(-50.0, 80.0, 0.0, 4.0, 60.0)
        b = _borrow_apr_at_util(0.0, 80.0, 0.0, 4.0, 60.0)
        assert a == pytest.approx(b)

    def test_returns_float(self):
        assert isinstance(_borrow_apr_at_util(50.0, 80.0, 0.0, 4.0, 60.0), float)

    def test_no_zero_division_kink_zero(self):
        _borrow_apr_at_util(0.0, 0.0, 0.0, 4.0, 60.0)

    def test_base_offsets_curve(self):
        with_base = _borrow_apr_at_util(50.0, 80.0, 3.0, 4.0, 60.0)
        without = _borrow_apr_at_util(50.0, 80.0, 0.0, 4.0, 60.0)
        assert with_base == pytest.approx(without + 3.0)

    def test_steeper_slope2_higher_at_full(self):
        gentle = _borrow_apr_at_util(100.0, 80.0, 0.0, 4.0, 20.0)
        steep = _borrow_apr_at_util(100.0, 80.0, 0.0, 4.0, 80.0)
        assert steep > gentle


# ===========================================================================
# 2. _utilization_headroom_pct
# ===========================================================================

class TestHeadroom:
    def test_basic(self):
        assert _utilization_headroom_pct(50.0, 80.0) == pytest.approx(30.0)

    def test_at_kink_zero(self):
        assert _utilization_headroom_pct(80.0, 80.0) == pytest.approx(0.0)

    def test_past_kink_negative(self):
        assert _utilization_headroom_pct(90.0, 80.0) == pytest.approx(-10.0)

    def test_zero_util_full_headroom(self):
        assert _utilization_headroom_pct(0.0, 80.0) == pytest.approx(80.0)

    def test_returns_float(self):
        assert isinstance(_utilization_headroom_pct(50.0, 80.0), float)

    def test_lower_util_more_headroom(self):
        low = _utilization_headroom_pct(70.0, 80.0)
        high = _utilization_headroom_pct(20.0, 80.0)
        assert high > low


# ===========================================================================
# 3. _rate_shock_if_crossed_pct
# ===========================================================================

class TestRateShock:
    def test_basic(self):
        assert _rate_shock_if_crossed_pct(4.0, 64.0) == pytest.approx(60.0)

    def test_floored_at_zero(self):
        assert _rate_shock_if_crossed_pct(64.0, 4.0) == pytest.approx(0.0)

    def test_zero_when_equal(self):
        assert _rate_shock_if_crossed_pct(10.0, 10.0) == pytest.approx(0.0)

    def test_never_negative(self):
        for k in [0.0, 4.0, 50.0]:
            for f in [0.0, 4.0, 64.0]:
                assert _rate_shock_if_crossed_pct(k, f) >= 0.0

    def test_returns_float(self):
        assert isinstance(_rate_shock_if_crossed_pct(4.0, 64.0), float)

    def test_larger_full_larger_shock(self):
        small = _rate_shock_if_crossed_pct(4.0, 20.0)
        big = _rate_shock_if_crossed_pct(4.0, 80.0)
        assert big > small


# ===========================================================================
# 4. _supply_apr_now_pct
# ===========================================================================

class TestSupplyApr:
    def test_basic(self):
        # borrow 10, util 50, reserve 10 -> 10 * 0.5 * 0.9 = 4.5
        assert _supply_apr_now_pct(10.0, 50.0, 10.0) == pytest.approx(4.5)

    def test_zero_util_zero_supply(self):
        assert _supply_apr_now_pct(10.0, 0.0, 10.0) == pytest.approx(0.0)

    def test_full_util_no_reserve(self):
        assert _supply_apr_now_pct(10.0, 100.0, 0.0) == pytest.approx(10.0)

    def test_full_reserve_zero_supply(self):
        assert _supply_apr_now_pct(10.0, 50.0, 100.0) == pytest.approx(0.0)

    def test_reserve_clamped(self):
        # reserve >100 clamps to 100 -> zero
        assert _supply_apr_now_pct(10.0, 50.0, 150.0) == pytest.approx(0.0)

    def test_util_clamped(self):
        a = _supply_apr_now_pct(10.0, 150.0, 0.0)
        b = _supply_apr_now_pct(10.0, 100.0, 0.0)
        assert a == pytest.approx(b)

    def test_returns_float(self):
        assert isinstance(_supply_apr_now_pct(10.0, 50.0, 10.0), float)

    def test_higher_util_higher_supply(self):
        low = _supply_apr_now_pct(10.0, 30.0, 10.0)
        high = _supply_apr_now_pct(10.0, 90.0, 10.0)
        assert high > low

    def test_higher_reserve_lower_supply(self):
        low_r = _supply_apr_now_pct(10.0, 50.0, 5.0)
        high_r = _supply_apr_now_pct(10.0, 50.0, 50.0)
        assert high_r < low_r


# ===========================================================================
# 5. _liquidity_buffer_pct
# ===========================================================================

class TestLiquidityBuffer:
    def test_basic(self):
        assert _liquidity_buffer_pct(40.0, 100.0, 60.0) == pytest.approx(40.0)

    def test_both_zero_falls_back(self):
        # both ~0 -> 100 - util
        assert _liquidity_buffer_pct(0.0, 0.0, 60.0) == pytest.approx(40.0)

    def test_both_zero_high_util(self):
        assert _liquidity_buffer_pct(0.0, 0.0, 95.0) == pytest.approx(5.0)

    def test_supply_zero_avail_positive(self):
        assert _liquidity_buffer_pct(10.0, 0.0, 50.0) == pytest.approx(100.0)

    def test_no_zero_division(self):
        _liquidity_buffer_pct(0.0, 0.0, 50.0)

    def test_capped_at_100(self):
        assert _liquidity_buffer_pct(200.0, 100.0, 50.0) == pytest.approx(100.0)

    def test_negative_avail_treated_zero(self):
        # negative avail clamped to 0; supply positive -> 0
        assert _liquidity_buffer_pct(-10.0, 100.0, 50.0) == pytest.approx(0.0)

    def test_returns_float(self):
        assert isinstance(_liquidity_buffer_pct(40.0, 100.0, 60.0), float)

    def test_bounded_0_100(self):
        for a in [0.0, 10.0, 100.0, 500.0]:
            for s in [0.0, 100.0, 1000.0]:
                r = _liquidity_buffer_pct(a, s, 50.0)
                assert 0.0 <= r <= 100.0

    def test_more_avail_higher_buffer(self):
        low = _liquidity_buffer_pct(10.0, 100.0, 50.0)
        high = _liquidity_buffer_pct(80.0, 100.0, 50.0)
        assert high > low


# ===========================================================================
# 6. _kink_proximity_score
# ===========================================================================

class TestProximityScore:
    def test_no_data_zero(self):
        s = _kink_proximity_score(50.0, 80.0, 30.0, 50.0, 60.0, has_data=False)
        assert s == 0.0

    def test_ample_high_score(self):
        s = _kink_proximity_score(10.0, 80.0, 70.0, 90.0, 0.0, has_data=True)
        assert s > 70.0

    def test_past_kink_capped_low(self):
        s = _kink_proximity_score(95.0, 80.0, -15.0, 5.0, 60.0, has_data=True)
        assert s <= 25.0

    def test_bounded_0_100(self):
        for util in [0.0, 50.0, 80.0, 95.0, 100.0]:
            for buf in [0.0, 50.0, 100.0]:
                for shock in [0.0, 30.0, 100.0]:
                    head = 80.0 - util
                    s = _kink_proximity_score(util, 80.0, head, buf, shock,
                                              has_data=True)
                    assert 0.0 <= s <= 100.0

    def test_more_headroom_higher_score(self):
        low = _kink_proximity_score(70.0, 80.0, 10.0, 50.0, 30.0, has_data=True)
        high = _kink_proximity_score(20.0, 80.0, 60.0, 50.0, 30.0, has_data=True)
        assert high > low

    def test_more_buffer_higher_score(self):
        low = _kink_proximity_score(40.0, 80.0, 40.0, 10.0, 30.0, has_data=True)
        high = _kink_proximity_score(40.0, 80.0, 40.0, 90.0, 30.0, has_data=True)
        assert high > low

    def test_larger_shock_lower_score(self):
        low_shock = _kink_proximity_score(40.0, 80.0, 40.0, 50.0, 0.0,
                                          has_data=True)
        high_shock = _kink_proximity_score(40.0, 80.0, 40.0, 50.0, 100.0,
                                           has_data=True)
        assert high_shock < low_shock

    def test_kink_zero_no_crash(self):
        s = _kink_proximity_score(50.0, 0.0, -50.0, 50.0, 60.0, has_data=True)
        assert 0.0 <= s <= 100.0

    def test_returns_float(self):
        s = _kink_proximity_score(40.0, 80.0, 40.0, 50.0, 30.0, has_data=True)
        assert isinstance(s, float)

    def test_past_kink_lower_than_ample(self):
        past = _kink_proximity_score(95.0, 80.0, -15.0, 5.0, 60.0, has_data=True)
        ample = _kink_proximity_score(10.0, 80.0, 70.0, 90.0, 0.0, has_data=True)
        assert past < ample


# ===========================================================================
# 7. _classify
# ===========================================================================

class TestClassify:
    def test_no_data_ample(self):
        assert _classify(90.0, 80.0, has_data=False) == CLASS_AMPLE_HEADROOM

    def test_ample(self):
        # ratio < 0.6: util 40, kink 80 -> 0.5
        assert _classify(40.0, 80.0, has_data=True) == CLASS_AMPLE_HEADROOM

    def test_comfortable(self):
        # ratio 0.6..0.85: util 56, kink 80 -> 0.7
        assert _classify(56.0, 80.0, has_data=True) == CLASS_COMFORTABLE

    def test_approaching(self):
        # ratio 0.85..0.98: util 72, kink 80 -> 0.9
        assert _classify(72.0, 80.0, has_data=True) == CLASS_APPROACHING_KINK

    def test_at_kink(self):
        # ratio 0.98..1.0: util 79.5, kink 80 -> 0.99375
        assert _classify(79.5, 80.0, has_data=True) == CLASS_AT_KINK

    def test_at_kink_exact(self):
        assert _classify(80.0, 80.0, has_data=True) == CLASS_AT_KINK

    def test_past_kink(self):
        assert _classify(90.0, 80.0, has_data=True) == CLASS_PAST_KINK

    def test_kink_zero_util_positive_past(self):
        assert _classify(50.0, 0.0, has_data=True) == CLASS_PAST_KINK

    def test_kink_zero_util_zero_at(self):
        assert _classify(0.0, 0.0, has_data=True) == CLASS_AT_KINK

    def test_boundary_060(self):
        # 0.599 ample, 0.60 comfortable
        assert _classify(0.599 * 80.0, 80.0, has_data=True) == CLASS_AMPLE_HEADROOM
        assert _classify(0.60 * 80.0, 80.0, has_data=True) == CLASS_COMFORTABLE

    def test_boundary_085(self):
        assert _classify(0.849 * 80.0, 80.0, has_data=True) == CLASS_COMFORTABLE
        assert _classify(0.85 * 80.0, 80.0, has_data=True) == CLASS_APPROACHING_KINK

    def test_boundary_098(self):
        assert _classify(0.979 * 80.0, 80.0, has_data=True) == CLASS_APPROACHING_KINK
        assert _classify(0.98 * 80.0, 80.0, has_data=True) == CLASS_AT_KINK

    def test_boundary_100(self):
        assert _classify(1.0 * 80.0, 80.0, has_data=True) == CLASS_AT_KINK
        assert _classify(1.0001 * 80.0, 80.0, has_data=True) == CLASS_PAST_KINK

    def test_all_bands_reachable(self):
        seen = {
            _classify(40.0, 80.0, has_data=True),
            _classify(56.0, 80.0, has_data=True),
            _classify(72.0, 80.0, has_data=True),
            _classify(79.5, 80.0, has_data=True),
            _classify(90.0, 80.0, has_data=True),
        }
        assert seen == set(ALL_CLASSIFICATIONS)

    def test_returns_valid(self):
        for util in [0.0, 30.0, 60.0, 79.0, 80.0, 95.0, 100.0]:
            c = _classify(util, 80.0, has_data=True)
            assert c in ALL_CLASSIFICATIONS


# ===========================================================================
# 8. _grade
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
# 9. _flags
# ===========================================================================

class TestFlags:
    def test_insufficient_data_only(self):
        f = _flags(50.0, 80.0, 30.0, 5.0, 60.0, 60.0, CLASS_AMPLE_HEADROOM,
                   has_data=False)
        assert f == [FLAG_INSUFFICIENT_DATA]

    def test_past_kink_flag(self):
        f = _flags(95.0, 80.0, -15.0, 5.0, 60.0, 60.0, CLASS_PAST_KINK,
                   has_data=True)
        assert FLAG_PAST_KINK in f

    def test_at_kink_flag(self):
        f = _flags(80.0, 80.0, 0.0, 20.0, 60.0, 60.0, CLASS_AT_KINK,
                   has_data=True)
        assert FLAG_AT_KINK in f

    def test_thin_liquidity_buffer(self):
        f = _flags(50.0, 80.0, 30.0, 5.0, 60.0, 60.0, CLASS_AMPLE_HEADROOM,
                   has_data=True)
        assert FLAG_THIN_LIQUIDITY_BUFFER in f

    def test_thick_buffer_no_flag(self):
        f = _flags(50.0, 80.0, 30.0, 50.0, 60.0, 60.0, CLASS_AMPLE_HEADROOM,
                   has_data=True)
        assert FLAG_THIN_LIQUIDITY_BUFFER not in f

    def test_steep_second_slope(self):
        f = _flags(50.0, 80.0, 30.0, 50.0, 60.0, 60.0, CLASS_AMPLE_HEADROOM,
                   has_data=True)
        assert FLAG_STEEP_SECOND_SLOPE in f

    def test_gentle_slope_no_flag(self):
        f = _flags(50.0, 80.0, 30.0, 50.0, 20.0, 20.0, CLASS_AMPLE_HEADROOM,
                   has_data=True)
        assert FLAG_STEEP_SECOND_SLOPE not in f

    def test_large_rate_shock(self):
        f = _flags(50.0, 80.0, 30.0, 50.0, 60.0, 60.0, CLASS_AMPLE_HEADROOM,
                   has_data=True)
        assert FLAG_LARGE_RATE_SHOCK in f

    def test_small_shock_no_flag(self):
        f = _flags(50.0, 80.0, 30.0, 50.0, 20.0, 10.0, CLASS_AMPLE_HEADROOM,
                   has_data=True)
        assert FLAG_LARGE_RATE_SHOCK not in f

    def test_ample_headroom_flag(self):
        f = _flags(40.0, 80.0, 40.0, 50.0, 60.0, 60.0, CLASS_AMPLE_HEADROOM,
                   has_data=True)
        assert FLAG_AMPLE_HEADROOM in f

    def test_low_headroom_no_ample_flag(self):
        f = _flags(72.0, 80.0, 8.0, 50.0, 60.0, 60.0, CLASS_APPROACHING_KINK,
                   has_data=True)
        assert FLAG_AMPLE_HEADROOM not in f

    def test_low_utilization_idle(self):
        f = _flags(10.0, 80.0, 70.0, 90.0, 60.0, 60.0, CLASS_AMPLE_HEADROOM,
                   has_data=True)
        assert FLAG_LOW_UTILIZATION_IDLE in f

    def test_high_util_no_idle_flag(self):
        f = _flags(50.0, 80.0, 30.0, 50.0, 60.0, 60.0, CLASS_AMPLE_HEADROOM,
                   has_data=True)
        assert FLAG_LOW_UTILIZATION_IDLE not in f

    def test_all_flags_valid(self):
        f = _flags(95.0, 80.0, -15.0, 5.0, 60.0, 60.0, CLASS_PAST_KINK,
                   has_data=True)
        for flag in f:
            assert flag in ALL_FLAGS

    def test_past_kink_no_at_kink(self):
        f = _flags(95.0, 80.0, -15.0, 5.0, 60.0, 60.0, CLASS_PAST_KINK,
                   has_data=True)
        assert FLAG_AT_KINK not in f


# ===========================================================================
# 10. _recommendations
# ===========================================================================

class TestRecommendations:
    def test_insufficient_data(self):
        recs = _recommendations(
            CLASS_AMPLE_HEADROOM, [FLAG_INSUFFICIENT_DATA], 0.0, 80.0, 0.0,
            0.0, 0.0, 0.0, has_data=False,
        )
        assert len(recs) >= 1
        assert any("insufficient" in r.lower() for r in recs)

    def test_past_kink_mentions(self):
        recs = _recommendations(
            CLASS_PAST_KINK, [FLAG_PAST_KINK], 94.0, 80.0, -14.0, 60.0,
            38.0, 6.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "kink" in combined

    def test_returns_list_each_class(self):
        for c in ALL_CLASSIFICATIONS:
            recs = _recommendations(
                c, [], 50.0, 80.0, 30.0, 60.0, 5.0, 50.0, has_data=True,
            )
            assert isinstance(recs, list)
            assert len(recs) >= 1

    def test_large_shock_mentioned(self):
        recs = _recommendations(
            CLASS_AT_KINK, [FLAG_LARGE_RATE_SHOCK], 80.0, 80.0, 0.0, 60.0,
            5.0, 50.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "shock" in combined

    def test_steep_slope_mentioned(self):
        recs = _recommendations(
            CLASS_COMFORTABLE, [FLAG_STEEP_SECOND_SLOPE], 60.0, 80.0, 20.0,
            60.0, 5.0, 50.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "slope" in combined or "steep" in combined

    def test_thin_buffer_mentioned(self):
        recs = _recommendations(
            CLASS_PAST_KINK, [FLAG_THIN_LIQUIDITY_BUFFER], 94.0, 80.0, -14.0,
            60.0, 38.0, 6.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "liquidity" in combined or "withdraw" in combined

    def test_idle_mentioned(self):
        recs = _recommendations(
            CLASS_AMPLE_HEADROOM, [FLAG_LOW_UTILIZATION_IDLE], 10.0, 80.0,
            70.0, 60.0, 1.0, 90.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "idle" in combined or "under-deployed" in combined or "low util" in combined

    def test_ample_mentioned(self):
        recs = _recommendations(
            CLASS_AMPLE_HEADROOM, [FLAG_AMPLE_HEADROOM], 20.0, 80.0, 60.0,
            60.0, 5.0, 80.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "headroom" in combined


# ===========================================================================
# 11. _atomic_log
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
# 12. _safe_float / _clamp
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
# 13. analyze - integration
# ===========================================================================

class TestAnalyze:
    def test_returns_dict(self):
        r = analyze(_market(), config=_cfg())
        assert isinstance(r, dict)

    def test_required_keys(self):
        r = analyze(_market(), config=_cfg())
        for key in [
            "name",
            "utilization_pct",
            "kink_utilization_pct",
            "utilization_headroom_pct",
            "projected_borrow_apr_now_pct",
            "projected_borrow_apr_at_kink_pct",
            "projected_borrow_apr_at_full_pct",
            "rate_shock_if_crossed_pct",
            "supply_apr_now_pct",
            "liquidity_buffer_pct",
            "kink_proximity_score",
            "classification",
            "grade",
            "flags",
            "recommendations",
            "timestamp",
        ]:
            assert key in r

    def test_headroom_math(self):
        r = analyze(_market(utilization_pct=50.0, kink_utilization_pct=80.0),
                    config=_cfg())
        assert r["utilization_headroom_pct"] == pytest.approx(30.0)

    def test_borrow_apr_now_math(self):
        r = analyze(_market(utilization_pct=40.0, kink_utilization_pct=80.0,
                            base_rate_pct=0.0, slope1_pct=4.0, slope2_pct=60.0),
                    config=_cfg())
        assert r["projected_borrow_apr_now_pct"] == pytest.approx(2.0)

    def test_apr_at_kink_math(self):
        r = analyze(_market(), config=_cfg())
        assert r["projected_borrow_apr_at_kink_pct"] == pytest.approx(4.0)

    def test_apr_at_full_math(self):
        r = analyze(_market(), config=_cfg())
        assert r["projected_borrow_apr_at_full_pct"] == pytest.approx(64.0)

    def test_rate_shock_math(self):
        r = analyze(_market(), config=_cfg())
        assert r["rate_shock_if_crossed_pct"] == pytest.approx(60.0)

    def test_supply_apr_math(self):
        # util 50, borrow at 50 = 2.5, reserve 10 -> 2.5 * 0.5 * 0.9 = 1.125
        r = analyze(_market(utilization_pct=50.0, reserve_factor_pct=10.0),
                    config=_cfg())
        assert r["supply_apr_now_pct"] == pytest.approx(1.125)

    def test_liquidity_buffer_math(self):
        r = analyze(_market(available_liquidity_usd=40_000_000.0,
                            total_supplied_usd=100_000_000.0), config=_cfg())
        assert r["liquidity_buffer_pct"] == pytest.approx(40.0)

    def test_classification_valid(self):
        r = analyze(_market(), config=_cfg())
        assert r["classification"] in ALL_CLASSIFICATIONS

    def test_grade_valid(self):
        r = analyze(_market(), config=_cfg())
        assert r["grade"] in ALL_GRADES

    def test_past_kink_scenario(self):
        r = analyze(_past_kink(), config=_cfg())
        assert r["classification"] == CLASS_PAST_KINK
        assert FLAG_PAST_KINK in r["flags"]

    def test_ample_scenario(self):
        r = analyze(_ample(), config=_cfg())
        assert r["classification"] == CLASS_AMPLE_HEADROOM

    def test_past_kink_low_score(self):
        r = analyze(_past_kink(), config=_cfg())
        assert r["kink_proximity_score"] <= 25.0

    def test_thin_buffer_flag(self):
        r = analyze(_market(available_liquidity_usd=5_000_000.0,
                            total_supplied_usd=100_000_000.0), config=_cfg())
        assert FLAG_THIN_LIQUIDITY_BUFFER in r["flags"]

    def test_steep_slope_flag(self):
        r = analyze(_market(slope2_pct=60.0), config=_cfg())
        assert FLAG_STEEP_SECOND_SLOPE in r["flags"]

    def test_large_shock_flag(self):
        r = analyze(_market(slope2_pct=60.0), config=_cfg())
        assert FLAG_LARGE_RATE_SHOCK in r["flags"]

    def test_ample_headroom_flag(self):
        r = analyze(_market(utilization_pct=30.0), config=_cfg())
        assert FLAG_AMPLE_HEADROOM in r["flags"]

    def test_low_util_idle_flag(self):
        r = analyze(_market(utilization_pct=10.0), config=_cfg())
        assert FLAG_LOW_UTILIZATION_IDLE in r["flags"]

    def test_at_kink_flag(self):
        r = analyze(_market(utilization_pct=80.0), config=_cfg())
        assert FLAG_AT_KINK in r["flags"]

    def test_insufficient_data_flag(self):
        r = analyze(_market(utilization_pct=0.0, available_liquidity_usd=0.0,
                            total_supplied_usd=0.0), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]
        assert r["classification"] == CLASS_AMPLE_HEADROOM

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
        r = analyze(_past_kink(), config=_cfg())
        for flag in r["flags"]:
            assert flag in ALL_FLAGS

    def test_score_bounded(self):
        r = analyze(_market(), config=_cfg())
        assert 0.0 <= r["kink_proximity_score"] <= 100.0

    def test_buffer_bounded(self):
        r = analyze(_market(), config=_cfg())
        assert 0.0 <= r["liquidity_buffer_pct"] <= 100.0

    def test_kwargs_override_dict(self):
        r = analyze(_market(utilization_pct=50.0), utilization_pct=90.0,
                    config=_cfg())
        assert r["utilization_pct"] == 90.0

    def test_kwargs_only(self):
        r = analyze(utilization_pct=40.0, kink_utilization_pct=80.0,
                    config=_cfg())
        assert r["projected_borrow_apr_now_pct"] == pytest.approx(2.0)

    def test_util_clamped_in_result(self):
        r = analyze(_market(utilization_pct=150.0), config=_cfg())
        assert r["utilization_pct"] == 100.0

    def test_kink_clamped_in_result(self):
        r = analyze(_market(kink_utilization_pct=150.0), config=_cfg())
        assert r["kink_utilization_pct"] == 100.0


# ===========================================================================
# 14. analyze - robustness / no crash
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
        r = analyze({"name": "X", "utilization_pct": "40",
                     "kink_utilization_pct": "80"}, config=_cfg())
        assert r["projected_borrow_apr_now_pct"] == pytest.approx(2.0)

    def test_garbage_numeric_fields(self):
        r = analyze({"name": "X", "utilization_pct": "abc",
                     "kink_utilization_pct": None}, config=_cfg())
        assert "classification" in r

    def test_no_zero_division_all_zeros(self):
        r = analyze(_market(utilization_pct=0.0, kink_utilization_pct=0.0,
                            slope1_pct=0.0, slope2_pct=0.0,
                            available_liquidity_usd=0.0,
                            total_supplied_usd=0.0), config=_cfg())
        assert "classification" in r

    def test_kink_zero_no_crash(self):
        r = analyze(_market(kink_utilization_pct=0.0, utilization_pct=50.0),
                    config=_cfg())
        assert "classification" in r

    def test_kink_100_no_crash(self):
        r = analyze(_market(kink_utilization_pct=100.0, utilization_pct=100.0),
                    config=_cfg())
        assert "classification" in r

    def test_does_not_raise_on_bad_log_path(self):
        r = analyze(_market(), config={"log_path": "/dev/null/cannot/log.json"})
        assert "classification" in r

    def test_default_log_path_used(self):
        r = analyze(_market())
        assert "classification" in r

    def test_extreme_values(self):
        r = analyze(_market(utilization_pct=1e9, slope2_pct=1e9,
                            available_liquidity_usd=1e18,
                            total_supplied_usd=1.0), config=_cfg())
        assert 0.0 <= r["kink_proximity_score"] <= 100.0

    def test_negative_values(self):
        r = analyze(_market(utilization_pct=-50.0, slope1_pct=-4.0,
                            available_liquidity_usd=-100.0), config=_cfg())
        assert "classification" in r

    def test_huge_numbers(self):
        r = analyze(_market(total_supplied_usd=1e300,
                            available_liquidity_usd=1e300), config=_cfg())
        assert math.isfinite(r["liquidity_buffer_pct"])

    def test_garbage_strings_everywhere(self):
        r = analyze({"name": 123, "utilization_pct": "xx",
                     "kink_utilization_pct": "yy", "base_rate_pct": [],
                     "slope1_pct": {}, "slope2_pct": "z",
                     "available_liquidity_usd": "a",
                     "total_supplied_usd": "b"}, config=_cfg())
        assert "classification" in r


# ===========================================================================
# 15. Logging via config
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
        path = str(tmp_path / "kink_log.json")
        for i in range(120):
            analyze(_market(name=f"T{i}"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 100
        assert data[-1]["name"] == "T119"
        assert data[0]["name"] == "T20"

    def test_idempotent_rerun(self, tmp_path):
        path = str(tmp_path / "kink_log.json")
        m = _market(name="Same")
        r1 = analyze(m, config={"log_path": path})
        r2 = analyze(m, config={"log_path": path})
        assert r1["classification"] == r2["classification"]
        assert r1["kink_proximity_score"] == r2["kink_proximity_score"]
        assert r1["flags"] == r2["flags"]

    def test_log_via_tmp_path(self, tmp_path):
        path = str(tmp_path / "out.json")
        analyze(_market(), config={"log_path": path})
        assert os.path.exists(path)

    def test_log_is_valid_json(self, tmp_path):
        path = str(tmp_path / "kink_log.json")
        for i in range(150):
            analyze(_market(name=f"T{i}"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) <= 100


# ===========================================================================
# 16. Determinism
# ===========================================================================

class TestDeterminism:
    def test_same_inputs_same_metrics(self):
        m = _market(name="Det")
        r1 = analyze(m, config=_cfg())
        r2 = analyze(m, config=_cfg())
        assert r1["projected_borrow_apr_now_pct"] == r2["projected_borrow_apr_now_pct"]
        assert r1["kink_proximity_score"] == r2["kink_proximity_score"]
        assert r1["classification"] == r2["classification"]
        assert r1["grade"] == r2["grade"]

    def test_score_deterministic(self):
        s1 = _kink_proximity_score(40.0, 80.0, 40.0, 50.0, 30.0, has_data=True)
        s2 = _kink_proximity_score(40.0, 80.0, 40.0, 50.0, 30.0, has_data=True)
        assert s1 == s2


# ===========================================================================
# 17. Monotonicity sanity
# ===========================================================================

class TestMonotonicity:
    def test_past_kink_lower_score_than_ample(self):
        ample = analyze(_ample(), config=_cfg())
        past = analyze(_past_kink(), config=_cfg())
        assert past["kink_proximity_score"] < ample["kink_proximity_score"]

    def test_higher_util_lower_headroom(self):
        low = analyze(_market(utilization_pct=30.0), config=_cfg())
        high = analyze(_market(utilization_pct=70.0), config=_cfg())
        assert high["utilization_headroom_pct"] < low["utilization_headroom_pct"]

    def test_higher_util_higher_borrow_apr(self):
        low = analyze(_market(utilization_pct=30.0), config=_cfg())
        high = analyze(_market(utilization_pct=70.0), config=_cfg())
        assert high["projected_borrow_apr_now_pct"] > low["projected_borrow_apr_now_pct"]

    def test_more_liquidity_higher_buffer(self):
        low = analyze(_market(available_liquidity_usd=10_000_000.0,
                              total_supplied_usd=100_000_000.0), config=_cfg())
        high = analyze(_market(available_liquidity_usd=80_000_000.0,
                               total_supplied_usd=100_000_000.0), config=_cfg())
        assert high["liquidity_buffer_pct"] > low["liquidity_buffer_pct"]

    def test_steeper_slope_higher_shock(self):
        gentle = analyze(_market(slope2_pct=20.0), config=_cfg())
        steep = analyze(_market(slope2_pct=80.0), config=_cfg())
        assert steep["rate_shock_if_crossed_pct"] > gentle["rate_shock_if_crossed_pct"]

    def test_lower_util_higher_score(self):
        low_u = analyze(_market(utilization_pct=20.0,
                                available_liquidity_usd=80_000_000.0),
                        config=_cfg())
        high_u = analyze(_market(utilization_pct=75.0,
                                 available_liquidity_usd=25_000_000.0),
                         config=_cfg())
        assert low_u["kink_proximity_score"] > high_u["kink_proximity_score"]


# ===========================================================================
# 18. analyze_portfolio
# ===========================================================================

class TestAnalyzePortfolio:
    def test_empty_list(self):
        s = analyze_portfolio([], config=_cfg())
        assert s["total_positions"] == 0
        assert s["safest_market"] is None
        assert s["riskiest_market"] is None
        assert s["avg_kink_proximity_score"] == 0.0
        assert s["past_kink_count"] == 0
        assert s["results"] == []

    def test_summary_keys_present(self):
        s = analyze_portfolio([_market()], config=_cfg())
        for key in ["total_positions", "results", "safest_market",
                    "riskiest_market", "avg_kink_proximity_score",
                    "past_kink_count", "timestamp"]:
            assert key in s

    def test_single_position(self):
        s = analyze_portfolio([_market(name="Solo")], config=_cfg())
        assert s["total_positions"] == 1
        assert s["safest_market"] == "Solo"
        assert s["riskiest_market"] == "Solo"
        assert len(s["results"]) == 1

    def test_multiple_safest_riskiest(self):
        s = analyze_portfolio([_past_kink("Past"), _ample("Ample")], config=_cfg())
        assert s["total_positions"] == 2
        assert s["safest_market"] == "Ample"
        assert s["riskiest_market"] == "Past"

    def test_avg_score(self):
        markets = [_market(name="A"), _market(name="B")]
        s = analyze_portfolio(markets, config=_cfg())
        per = [r["kink_proximity_score"] for r in s["results"]]
        assert s["avg_kink_proximity_score"] == pytest.approx(sum(per) / len(per))

    def test_past_kink_count(self):
        markets = [_ample("A"), _past_kink("P1"), _past_kink("P2")]
        s = analyze_portfolio(markets, config=_cfg())
        assert s["past_kink_count"] == 2

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
        markets = [_past_kink("P"), _ample("A"), _market(name="Mid")]
        s = analyze_portfolio(markets, config=_cfg())
        assert 0.0 <= s["avg_kink_proximity_score"] <= 100.0

    def test_many_positions(self):
        markets = [_market(name=f"T{i}", utilization_pct=float(i % 100))
                   for i in range(50)]
        s = analyze_portfolio(markets, config=_cfg())
        assert s["total_positions"] == 50
        assert len(s["results"]) == 50


# ===========================================================================
# 19. Class wrapper parity
# ===========================================================================

class TestClassWrapper:
    def test_instantiation(self):
        a = ProtocolDeFiInterestRateKinkProximityAnalyzer()
        assert a is not None

    def test_analyze_returns_dict(self):
        a = ProtocolDeFiInterestRateKinkProximityAnalyzer(config=_cfg())
        r = a.analyze(_market())
        assert isinstance(r, dict)

    def test_analyze_parity(self):
        cfg = _cfg()
        m = _market(name="Parity")
        r_func = analyze(m, config=cfg)
        r_class = ProtocolDeFiInterestRateKinkProximityAnalyzer(
            config=cfg).analyze(m)
        assert r_func["classification"] == r_class["classification"]
        assert r_func["kink_proximity_score"] == r_class["kink_proximity_score"]
        assert r_func["flags"] == r_class["flags"]

    def test_analyze_kwargs_via_class(self):
        a = ProtocolDeFiInterestRateKinkProximityAnalyzer(config=_cfg())
        r = a.analyze(utilization_pct=40.0, kink_utilization_pct=80.0)
        assert r["projected_borrow_apr_now_pct"] == pytest.approx(2.0)

    def test_portfolio_parity(self):
        cfg = _cfg()
        markets = [_market(name="A"), _market(name="B")]
        r_func = analyze_portfolio(markets, config=cfg)
        r_class = ProtocolDeFiInterestRateKinkProximityAnalyzer(
            config=cfg).analyze_portfolio(markets)
        assert r_func["total_positions"] == r_class["total_positions"]
        assert r_func["safest_market"] == r_class["safest_market"]

    def test_config_forwarded_to_log(self):
        path = _tmp_log()
        a = ProtocolDeFiInterestRateKinkProximityAnalyzer(
            config={"log_path": path})
        a.analyze(_market())
        assert os.path.exists(path)
        with open(path) as fh:
            data = json.load(fh)
        assert len(data) == 1
        os.unlink(path)

    def test_no_config_uses_default(self):
        a = ProtocolDeFiInterestRateKinkProximityAnalyzer()
        r = a.analyze(_market())
        assert "classification" in r

    def test_multiple_calls_accumulate(self):
        path = _tmp_log()
        a = ProtocolDeFiInterestRateKinkProximityAnalyzer(
            config={"log_path": path})
        a.analyze(_market(name="A"))
        a.analyze(_market(name="B"))
        with open(path) as fh:
            data = json.load(fh)
        assert len(data) == 2
        os.unlink(path)

    def test_class_portfolio_summary(self):
        a = ProtocolDeFiInterestRateKinkProximityAnalyzer(config=_cfg())
        s = a.analyze_portfolio([_market(name="X")])
        assert s["total_positions"] == 1


# ===========================================================================
# 20. Constants sanity
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

    def test_eps_small(self):
        assert _EPS < 1e-6


# ===========================================================================
# 21. never-raises contract (parametrized garbage)
# ===========================================================================

@pytest.mark.parametrize("bad", [
    None, {}, [], "string", 42, 3.14, True, False,
    {"utilization_pct": None},
    {"utilization_pct": "abc"},
    {"utilization_pct": -100.0},
    {"utilization_pct": 1e18},
    {"kink_utilization_pct": 0.0},
    {"kink_utilization_pct": -50.0},
    {"kink_utilization_pct": "x"},
    {"slope1_pct": float("inf")},
    {"slope2_pct": float("nan")},
    {"available_liquidity_usd": -1.0},
    {"total_supplied_usd": 0.0, "available_liquidity_usd": 0.0},
    {"reserve_factor_pct": 999.0},
    {"reserve_factor_pct": -10.0},
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
    r = analyze(_market(utilization_pct=util), config=_cfg())
    assert isinstance(r, dict)
    assert 0.0 <= r["kink_proximity_score"] <= 100.0


@pytest.mark.parametrize("kink", [-50.0, 0.0, 1.0, 50.0, 80.0, 99.0, 100.0, 1e9])
def test_never_raises_kink_sweep(kink):
    r = analyze(_market(kink_utilization_pct=kink), config=_cfg())
    assert isinstance(r, dict)
    assert r["classification"] in ALL_CLASSIFICATIONS


@pytest.mark.parametrize("slope2", [-60.0, 0.0, 4.0, 40.0, 60.0, 200.0, 1e6])
def test_never_raises_slope2_sweep(slope2):
    r = analyze(_market(slope2_pct=slope2), config=_cfg())
    assert isinstance(r, dict)
    assert math.isfinite(r["rate_shock_if_crossed_pct"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
