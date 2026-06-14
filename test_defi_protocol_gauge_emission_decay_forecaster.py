"""
Tests for MP-1074 DeFiProtocolGaugeEmissionDecayForecaster
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

from spa_core.analytics.defi_protocol_gauge_emission_decay_forecaster import (
    analyze,
    analyze_portfolio,
    _incentive_apr_pct,
    _project_emission_tokens,
    _incentive_apr_half_life_weeks,
    _weeks_until_incentive_below_base,
    _incentive_dependence_pct,
    _apr_cliff_severity_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    DeFiProtocolGaugeEmissionDecayForecaster,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_STABLE,
    CLASS_GENTLE_DECAY,
    CLASS_MODERATE_DECAY,
    CLASS_STEEP_DECAY,
    CLASS_EMISSION_CLIFF,
    FLAG_HIGH_INCENTIVE_DEPENDENCE,
    FLAG_STEEP_DECAY,
    FLAG_FAST_HALF_LIFE,
    FLAG_INCENTIVE_BELOW_BASE_SOON,
    FLAG_EMISSION_FLOOR_SUPPORT,
    FLAG_LOW_REWARD_TOKEN_PRICE_RISK,
    FLAG_STABLE_EMISSIONS,
    FLAG_INSUFFICIENT_DATA,
    _NEVER_WEEKS,
    _WEEKS_PER_YEAR,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _tmp_log():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _gauge(
    name="TestGauge",
    current_emission_tokens_per_week=100_000.0,
    emission_decay_pct_per_week=1.5,
    reward_token_price_usd=0.50,
    lp_tvl_usd=2_000_000.0,
    base_yield_apr_pct=3.0,
    weeks_horizon=52.0,
    gauge_share_pct=100.0,
    emission_floor_tokens_per_week=0.0,
):
    return {
        "name": name,
        "current_emission_tokens_per_week": current_emission_tokens_per_week,
        "emission_decay_pct_per_week": emission_decay_pct_per_week,
        "reward_token_price_usd": reward_token_price_usd,
        "lp_tvl_usd": lp_tvl_usd,
        "base_yield_apr_pct": base_yield_apr_pct,
        "weeks_horizon": weeks_horizon,
        "gauge_share_pct": gauge_share_pct,
        "emission_floor_tokens_per_week": emission_floor_tokens_per_week,
    }


def _cfg():
    return {"log_path": _tmp_log()}


# ===========================================================================
# 1. _incentive_apr_pct
# ===========================================================================

class TestIncentiveApr:
    def test_basic_math(self):
        # 100k * $0.5 * 100% * 52 / 2M * 100 = 130%
        r = _incentive_apr_pct(100_000.0, 0.50, 100.0, 2_000_000.0)
        assert r == pytest.approx(130.0)

    def test_zero_tvl_returns_zero(self):
        assert _incentive_apr_pct(100_000.0, 0.50, 100.0, 0.0) == 0.0

    def test_negative_tvl_returns_zero(self):
        assert _incentive_apr_pct(100_000.0, 0.50, 100.0, -5.0) == 0.0

    def test_zero_emission(self):
        assert _incentive_apr_pct(0.0, 0.50, 100.0, 2_000_000.0) == pytest.approx(0.0)

    def test_zero_price(self):
        assert _incentive_apr_pct(100_000.0, 0.0, 100.0, 2_000_000.0) == pytest.approx(0.0)

    def test_half_share_halves_apr(self):
        full = _incentive_apr_pct(100_000.0, 0.50, 100.0, 2_000_000.0)
        half = _incentive_apr_pct(100_000.0, 0.50, 50.0, 2_000_000.0)
        assert half == pytest.approx(full / 2.0)

    def test_scales_linearly_with_emission(self):
        a = _incentive_apr_pct(50_000.0, 0.50, 100.0, 2_000_000.0)
        b = _incentive_apr_pct(100_000.0, 0.50, 100.0, 2_000_000.0)
        assert b == pytest.approx(2 * a)

    def test_negative_emission_clamped(self):
        assert _incentive_apr_pct(-100_000.0, 0.50, 100.0, 2_000_000.0) == pytest.approx(0.0)

    def test_negative_price_clamped(self):
        assert _incentive_apr_pct(100_000.0, -0.50, 100.0, 2_000_000.0) == pytest.approx(0.0)

    def test_no_zero_division(self):
        _incentive_apr_pct(0.0, 0.0, 0.0, 0.0)

    def test_uses_weeks_per_year_constant(self):
        # annualisation factor is 52
        assert _WEEKS_PER_YEAR == 52.0


# ===========================================================================
# 2. _project_emission_tokens
# ===========================================================================

class TestProjectEmission:
    def test_no_decay_unchanged(self):
        assert _project_emission_tokens(100_000.0, 0.0, 52.0, 0.0) == pytest.approx(100_000.0)

    def test_decay_reduces_emission(self):
        p = _project_emission_tokens(100_000.0, 2.0, 10.0, 0.0)
        assert p < 100_000.0
        assert p > 0.0

    def test_geometric_math(self):
        # 100k * 0.98^10
        p = _project_emission_tokens(100_000.0, 2.0, 10.0, 0.0)
        assert p == pytest.approx(100_000.0 * (0.98 ** 10))

    def test_floor_respected(self):
        p = _project_emission_tokens(100_000.0, 50.0, 20.0, 30_000.0)
        assert p >= 30_000.0

    def test_floor_when_decay_collapses(self):
        # factor <= 0 → returns floor
        p = _project_emission_tokens(100_000.0, 150.0, 5.0, 12_345.0)
        assert p == pytest.approx(12_345.0)

    def test_zero_weeks_returns_current(self):
        p = _project_emission_tokens(100_000.0, 5.0, 0.0, 0.0)
        assert p == pytest.approx(100_000.0)

    def test_growth_negative_decay(self):
        # negative decay = growth
        p = _project_emission_tokens(100_000.0, -1.0, 10.0, 0.0)
        assert p > 100_000.0

    def test_monotonic_decay_over_time(self):
        p1 = _project_emission_tokens(100_000.0, 3.0, 5.0, 0.0)
        p2 = _project_emission_tokens(100_000.0, 3.0, 20.0, 0.0)
        assert p2 < p1

    def test_never_negative(self):
        p = _project_emission_tokens(100_000.0, 5.0, 500.0, 0.0)
        assert p >= 0.0

    def test_negative_current_clamped(self):
        p = _project_emission_tokens(-100_000.0, 2.0, 10.0, 0.0)
        assert p >= 0.0


# ===========================================================================
# 3. _incentive_apr_half_life_weeks
# ===========================================================================

class TestHalfLife:
    def test_no_decay_never(self):
        assert _incentive_apr_half_life_weeks(0.0, 100_000.0, 0.0) == _NEVER_WEEKS

    def test_negative_decay_never(self):
        assert _incentive_apr_half_life_weeks(-1.0, 100_000.0, 0.0) == _NEVER_WEEKS

    def test_basic_half_life(self):
        # ln(0.5)/ln(0.98)
        hl = _incentive_apr_half_life_weeks(2.0, 100_000.0, 0.0)
        assert hl == pytest.approx(math.log(0.5) / math.log(0.98))

    def test_steeper_decay_shorter_half_life(self):
        slow = _incentive_apr_half_life_weeks(1.0, 100_000.0, 0.0)
        fast = _incentive_apr_half_life_weeks(5.0, 100_000.0, 0.0)
        assert fast < slow

    def test_floor_above_half_never(self):
        # floor at 60k > half of 100k → can never halve
        hl = _incentive_apr_half_life_weeks(3.0, 100_000.0, 60_000.0)
        assert hl == _NEVER_WEEKS

    def test_floor_below_half_still_finite(self):
        hl = _incentive_apr_half_life_weeks(3.0, 100_000.0, 10_000.0)
        assert hl < _NEVER_WEEKS

    def test_collapse_factor_returns_one(self):
        hl = _incentive_apr_half_life_weeks(150.0, 100_000.0, 0.0)
        assert hl == pytest.approx(1.0)

    def test_positive_result(self):
        hl = _incentive_apr_half_life_weeks(2.0, 100_000.0, 0.0)
        assert hl > 0.0

    def test_no_zero_division(self):
        _incentive_apr_half_life_weeks(0.0, 0.0, 0.0)


# ===========================================================================
# 4. _weeks_until_incentive_below_base
# ===========================================================================

class TestWeeksBelowBase:
    def test_already_below_returns_zero(self):
        w = _weeks_until_incentive_below_base(2.0, 5.0, 2.0, 100_000.0, 0.0)
        assert w == 0.0

    def test_no_decay_never(self):
        w = _weeks_until_incentive_below_base(50.0, 5.0, 0.0, 100_000.0, 0.0)
        assert w == _NEVER_WEEKS

    def test_basic_crossing_positive(self):
        w = _weeks_until_incentive_below_base(50.0, 5.0, 2.0, 100_000.0, 0.0)
        assert 0.0 < w < _NEVER_WEEKS

    def test_steeper_decay_crosses_sooner(self):
        slow = _weeks_until_incentive_below_base(50.0, 5.0, 1.0, 100_000.0, 0.0)
        fast = _weeks_until_incentive_below_base(50.0, 5.0, 5.0, 100_000.0, 0.0)
        assert fast < slow

    def test_floor_holds_above_base_never(self):
        # floor fraction (0.8) >= target fraction (5/50=0.1) → never crosses
        w = _weeks_until_incentive_below_base(50.0, 5.0, 3.0, 100_000.0, 80_000.0)
        assert w == _NEVER_WEEKS

    def test_collapse_factor_returns_one(self):
        w = _weeks_until_incentive_below_base(50.0, 5.0, 150.0, 100_000.0, 0.0)
        assert w == pytest.approx(1.0)

    def test_zero_incentive_apr(self):
        w = _weeks_until_incentive_below_base(0.0, 5.0, 2.0, 100_000.0, 0.0)
        assert w == 0.0  # 0 <= base → already below

    def test_zero_base_with_decay(self):
        # base 0, target fraction 0 → never reaches exactly 0
        w = _weeks_until_incentive_below_base(50.0, 0.0, 2.0, 100_000.0, 0.0)
        assert w == _NEVER_WEEKS

    def test_no_zero_division(self):
        _weeks_until_incentive_below_base(0.0, 0.0, 0.0, 0.0, 0.0)


# ===========================================================================
# 5. _incentive_dependence_pct
# ===========================================================================

class TestDependence:
    def test_basic_math(self):
        # 6 / (6+2) = 75%
        d = _incentive_dependence_pct(6.0, 2.0)
        assert d == pytest.approx(75.0)

    def test_all_incentive(self):
        d = _incentive_dependence_pct(10.0, 0.0)
        assert d == pytest.approx(100.0)

    def test_no_incentive(self):
        d = _incentive_dependence_pct(0.0, 5.0)
        assert d == pytest.approx(0.0)

    def test_both_zero_returns_zero(self):
        assert _incentive_dependence_pct(0.0, 0.0) == 0.0

    def test_bounded_0_100(self):
        for inc in [0.0, 1.0, 50.0, 500.0]:
            for base in [0.0, 1.0, 50.0]:
                d = _incentive_dependence_pct(inc, base)
                assert 0.0 <= d <= 100.0

    def test_higher_incentive_higher_dependence(self):
        d1 = _incentive_dependence_pct(2.0, 5.0)
        d2 = _incentive_dependence_pct(10.0, 5.0)
        assert d2 > d1

    def test_no_zero_division(self):
        _incentive_dependence_pct(0.0, 0.0)


# ===========================================================================
# 6. _apr_cliff_severity_score
# ===========================================================================

class TestSeverityScore:
    def test_no_data_zero(self):
        assert _apr_cliff_severity_score(90.0, 5.0, 90.0, has_data=False) == 0.0

    def test_max_all_drivers(self):
        s = _apr_cliff_severity_score(100.0, 5.0, 100.0, has_data=True)
        assert s == pytest.approx(100.0)

    def test_zero_all_drivers(self):
        s = _apr_cliff_severity_score(0.0, 0.0, 0.0, has_data=True)
        assert s == pytest.approx(0.0)

    def test_bounded_0_100(self):
        for dep in [0.0, 50.0, 100.0]:
            for decay in [0.0, 1.5, 10.0]:
                for drop in [0.0, 50.0, 100.0, 200.0]:
                    s = _apr_cliff_severity_score(dep, decay, drop, has_data=True)
                    assert 0.0 <= s <= 100.0

    def test_higher_dependence_higher_score(self):
        s1 = _apr_cliff_severity_score(20.0, 2.0, 50.0, has_data=True)
        s2 = _apr_cliff_severity_score(80.0, 2.0, 50.0, has_data=True)
        assert s2 > s1

    def test_higher_decay_higher_score(self):
        s1 = _apr_cliff_severity_score(50.0, 0.5, 50.0, has_data=True)
        s2 = _apr_cliff_severity_score(50.0, 5.0, 50.0, has_data=True)
        assert s2 > s1

    def test_higher_drop_higher_score(self):
        s1 = _apr_cliff_severity_score(50.0, 2.0, 10.0, has_data=True)
        s2 = _apr_cliff_severity_score(50.0, 2.0, 90.0, has_data=True)
        assert s2 > s1

    def test_negative_decay_no_decay_component(self):
        s = _apr_cliff_severity_score(0.0, -5.0, 0.0, has_data=True)
        assert s == pytest.approx(0.0)


# ===========================================================================
# 7. _classify
# ===========================================================================

class TestClassify:
    def test_no_data_stable(self):
        assert _classify(0.0, 0.0, _NEVER_WEEKS, has_data=False) == CLASS_STABLE

    def test_stable(self):
        assert _classify(0.0, 0.0, _NEVER_WEEKS, has_data=True) == CLASS_STABLE

    def test_gentle_decay(self):
        assert _classify(0.5, 10.0, _NEVER_WEEKS, has_data=True) == CLASS_GENTLE_DECAY

    def test_moderate_decay(self):
        assert _classify(1.5, 10.0, _NEVER_WEEKS, has_data=True) == CLASS_MODERATE_DECAY

    def test_steep_decay(self):
        assert _classify(4.0, 30.0, _NEVER_WEEKS, has_data=True) == CLASS_STEEP_DECAY

    def test_emission_cliff_steep_and_severe(self):
        assert _classify(5.0, 80.0, _NEVER_WEEKS, has_data=True) == CLASS_EMISSION_CLIFF

    def test_emission_cliff_soon_cross(self):
        # crossing below base within 8 weeks → cliff even at low decay
        assert _classify(0.5, 10.0, 4.0, has_data=True) == CLASS_EMISSION_CLIFF

    def test_all_bands_reachable(self):
        seen = set()
        seen.add(_classify(0.0, 0.0, _NEVER_WEEKS, has_data=True))
        seen.add(_classify(0.5, 10.0, _NEVER_WEEKS, has_data=True))
        seen.add(_classify(1.5, 10.0, _NEVER_WEEKS, has_data=True))
        seen.add(_classify(4.0, 30.0, _NEVER_WEEKS, has_data=True))
        seen.add(_classify(5.0, 80.0, _NEVER_WEEKS, has_data=True))
        assert seen == set(ALL_CLASSIFICATIONS)

    def test_returns_valid_classification(self):
        for decay in [0.0, 0.5, 1.5, 4.0, 10.0]:
            for sev in [0, 50, 100]:
                c = _classify(decay, sev, _NEVER_WEEKS, has_data=True)
                assert c in ALL_CLASSIFICATIONS

    def test_boundary_steep_threshold(self):
        # exactly 3.0 is steep (>=)
        assert _classify(3.0, 10.0, _NEVER_WEEKS, has_data=True) in (
            CLASS_STEEP_DECAY, CLASS_EMISSION_CLIFF,
        )

    def test_boundary_moderate_threshold(self):
        assert _classify(1.0, 10.0, _NEVER_WEEKS, has_data=True) == CLASS_MODERATE_DECAY


# ===========================================================================
# 8. _grade
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
            # higher severity is never a better grade
            assert rank[grades[i]] <= rank[grades[i + 1]]

    def test_all_grades_reachable(self):
        seen = {_grade(s) for s in [0, 20, 40, 60, 90]}
        assert seen == {"A", "B", "C", "D", "F"}

    def test_all_grades_constant(self):
        assert set(ALL_GRADES) == {"A", "B", "C", "D", "F"}


# ===========================================================================
# 9. _flags
# ===========================================================================

class TestFlags:
    def test_insufficient_data_only(self):
        f = _flags(90.0, 5.0, 10.0, 4.0, 0.0, 0.0, 0.5, has_data=False)
        assert f == [FLAG_INSUFFICIENT_DATA]

    def test_high_dependence(self):
        f = _flags(70.0, 1.5, 100.0, 100.0, 0.0, 50_000.0, 0.5, has_data=True)
        assert FLAG_HIGH_INCENTIVE_DEPENDENCE in f

    def test_low_dependence_no_flag(self):
        f = _flags(40.0, 1.5, 100.0, 100.0, 0.0, 50_000.0, 0.5, has_data=True)
        assert FLAG_HIGH_INCENTIVE_DEPENDENCE not in f

    def test_steep_decay_flag(self):
        f = _flags(50.0, 4.0, 100.0, 100.0, 0.0, 50_000.0, 0.5, has_data=True)
        assert FLAG_STEEP_DECAY in f

    def test_fast_half_life(self):
        f = _flags(50.0, 1.5, 10.0, 100.0, 0.0, 50_000.0, 0.5, has_data=True)
        assert FLAG_FAST_HALF_LIFE in f

    def test_slow_half_life_no_flag(self):
        f = _flags(50.0, 1.5, 100.0, 200.0, 0.0, 50_000.0, 0.5, has_data=True)
        assert FLAG_FAST_HALF_LIFE not in f

    def test_incentive_below_base_soon(self):
        f = _flags(50.0, 1.5, 100.0, 10.0, 0.0, 50_000.0, 0.5, has_data=True)
        assert FLAG_INCENTIVE_BELOW_BASE_SOON in f

    def test_never_below_base_no_flag(self):
        f = _flags(50.0, 1.5, 100.0, _NEVER_WEEKS, 0.0, 50_000.0, 0.5, has_data=True)
        assert FLAG_INCENTIVE_BELOW_BASE_SOON not in f

    def test_emission_floor_support(self):
        # projected reached floor (30k <= 30k)
        f = _flags(50.0, 5.0, 10.0, 100.0, 30_000.0, 30_000.0, 0.5, has_data=True)
        assert FLAG_EMISSION_FLOOR_SUPPORT in f

    def test_no_floor_no_support_flag(self):
        f = _flags(50.0, 5.0, 10.0, 100.0, 0.0, 5_000.0, 0.5, has_data=True)
        assert FLAG_EMISSION_FLOOR_SUPPORT not in f

    def test_low_reward_price_risk(self):
        f = _flags(50.0, 1.5, 100.0, 100.0, 0.0, 50_000.0, 0.005, has_data=True)
        assert FLAG_LOW_REWARD_TOKEN_PRICE_RISK in f

    def test_normal_price_no_flag(self):
        f = _flags(50.0, 1.5, 100.0, 100.0, 0.0, 50_000.0, 1.0, has_data=True)
        assert FLAG_LOW_REWARD_TOKEN_PRICE_RISK not in f

    def test_stable_emissions(self):
        f = _flags(50.0, 0.0, _NEVER_WEEKS, _NEVER_WEEKS, 0.0, 50_000.0, 0.5, has_data=True)
        assert FLAG_STABLE_EMISSIONS in f

    def test_decaying_no_stable_flag(self):
        f = _flags(50.0, 2.0, 50.0, 100.0, 0.0, 50_000.0, 0.5, has_data=True)
        assert FLAG_STABLE_EMISSIONS not in f

    def test_all_flags_valid(self):
        f = _flags(90.0, 5.0, 5.0, 4.0, 30_000.0, 30_000.0, 0.005, has_data=True)
        for flag in f:
            assert flag in ALL_FLAGS


# ===========================================================================
# 10. _recommendations
# ===========================================================================

class TestRecommendations:
    def test_insufficient_data(self):
        recs = _recommendations(
            CLASS_STABLE, [FLAG_INSUFFICIENT_DATA], 0.0, 0.0, 0.0,
            _NEVER_WEEKS, _NEVER_WEEKS, has_data=False,
        )
        assert len(recs) >= 1
        assert any("insufficient" in r.lower() for r in recs)

    def test_emission_cliff_mentions_cliff(self):
        recs = _recommendations(
            CLASS_EMISSION_CLIFF, [], 130.0, 15.0, 95.0, 17.0, 30.0,
            has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "cliff" in combined

    def test_returns_list_for_each_class(self):
        for c in ALL_CLASSIFICATIONS:
            recs = _recommendations(
                c, [], 10.0, 5.0, 50.0, 30.0, 50.0, has_data=True,
            )
            assert isinstance(recs, list)
            assert len(recs) >= 1

    def test_high_dependence_mentioned(self):
        recs = _recommendations(
            CLASS_MODERATE_DECAY, [FLAG_HIGH_INCENTIVE_DEPENDENCE],
            10.0, 5.0, 80.0, 30.0, 50.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "dependence" in combined or "depend" in combined

    def test_fast_half_life_mentioned(self):
        recs = _recommendations(
            CLASS_MODERATE_DECAY, [FLAG_FAST_HALF_LIFE],
            10.0, 5.0, 50.0, 12.0, 50.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "half-life" in combined or "half" in combined

    def test_below_base_mentioned(self):
        recs = _recommendations(
            CLASS_STEEP_DECAY, [FLAG_INCENTIVE_BELOW_BASE_SOON],
            10.0, 2.0, 50.0, 30.0, 12.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "base" in combined

    def test_floor_support_mentioned(self):
        recs = _recommendations(
            CLASS_STEEP_DECAY, [FLAG_EMISSION_FLOOR_SUPPORT],
            10.0, 5.0, 50.0, 30.0, 50.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "floor" in combined

    def test_low_price_mentioned(self):
        recs = _recommendations(
            CLASS_MODERATE_DECAY, [FLAG_LOW_REWARD_TOKEN_PRICE_RISK],
            10.0, 5.0, 50.0, 30.0, 50.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "price" in combined

    def test_stable_emissions_path(self):
        recs = _recommendations(
            CLASS_STABLE, [FLAG_STABLE_EMISSIONS],
            10.0, 10.0, 50.0, _NEVER_WEEKS, _NEVER_WEEKS, has_data=True,
        )
        assert len(recs) >= 1


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

    def test_creates_parent_dirs(self):
        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "a", "b", "log.json")
        _atomic_log(path, {"deep": True})
        assert os.path.exists(path)


# ===========================================================================
# 12. _safe_float / _clamp
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
# 13. analyze — integration
# ===========================================================================

class TestAnalyze:
    def test_returns_dict(self):
        r = analyze(_gauge(), config=_cfg())
        assert isinstance(r, dict)

    def test_required_keys(self):
        r = analyze(_gauge(), config=_cfg())
        for key in [
            "name",
            "current_incentive_apr_pct",
            "projected_incentive_apr_at_horizon_pct",
            "incentive_apr_half_life_weeks",
            "total_apr_now_pct",
            "total_apr_at_horizon_pct",
            "incentive_dependence_pct",
            "weeks_until_incentive_below_base",
            "apr_cliff_severity_score",
            "classification",
            "grade",
            "flags",
            "recommendations",
            "timestamp",
        ]:
            assert key in r

    def test_incentive_apr_math(self):
        r = analyze(_gauge(current_emission_tokens_per_week=100_000.0,
                           reward_token_price_usd=0.50, gauge_share_pct=100.0,
                           lp_tvl_usd=2_000_000.0), config=_cfg())
        assert r["current_incentive_apr_pct"] == pytest.approx(130.0)

    def test_total_apr_now_math(self):
        r = analyze(_gauge(base_yield_apr_pct=3.0), config=_cfg())
        assert r["total_apr_now_pct"] == pytest.approx(
            r["current_incentive_apr_pct"] + 3.0
        )

    def test_total_apr_horizon_math(self):
        r = analyze(_gauge(), config=_cfg())
        assert r["total_apr_at_horizon_pct"] == pytest.approx(
            r["projected_incentive_apr_at_horizon_pct"] + r["base_yield_apr_pct"]
        )

    def test_projected_below_current_when_decaying(self):
        r = analyze(_gauge(emission_decay_pct_per_week=3.0), config=_cfg())
        assert r["projected_incentive_apr_at_horizon_pct"] < r["current_incentive_apr_pct"]

    def test_classification_valid(self):
        r = analyze(_gauge(), config=_cfg())
        assert r["classification"] in ALL_CLASSIFICATIONS

    def test_grade_valid(self):
        r = analyze(_gauge(), config=_cfg())
        assert r["grade"] in ALL_GRADES

    def test_stable_scenario(self):
        r = analyze(_gauge(emission_decay_pct_per_week=0.0), config=_cfg())
        assert r["classification"] == CLASS_STABLE
        assert FLAG_STABLE_EMISSIONS in r["flags"]

    def test_steep_decay_scenario(self):
        r = analyze(_gauge(emission_decay_pct_per_week=4.0), config=_cfg())
        assert r["classification"] in (CLASS_STEEP_DECAY, CLASS_EMISSION_CLIFF)
        assert FLAG_STEEP_DECAY in r["flags"]

    def test_emission_cliff_scenario(self):
        r = analyze(_gauge(current_emission_tokens_per_week=100_000.0,
                           emission_decay_pct_per_week=5.0,
                           reward_token_price_usd=0.50,
                           lp_tvl_usd=2_000_000.0,
                           base_yield_apr_pct=2.0), config=_cfg())
        assert r["classification"] == CLASS_EMISSION_CLIFF

    def test_gentle_decay_scenario(self):
        r = analyze(_gauge(emission_decay_pct_per_week=0.3), config=_cfg())
        assert r["classification"] == CLASS_GENTLE_DECAY

    def test_moderate_decay_scenario(self):
        r = analyze(_gauge(emission_decay_pct_per_week=1.5), config=_cfg())
        assert r["classification"] == CLASS_MODERATE_DECAY

    def test_high_dependence_flag(self):
        r = analyze(_gauge(current_emission_tokens_per_week=100_000.0,
                           reward_token_price_usd=0.50, lp_tvl_usd=2_000_000.0,
                           base_yield_apr_pct=1.0), config=_cfg())
        assert FLAG_HIGH_INCENTIVE_DEPENDENCE in r["flags"]

    def test_low_reward_price_flag(self):
        r = analyze(_gauge(reward_token_price_usd=0.005), config=_cfg())
        assert FLAG_LOW_REWARD_TOKEN_PRICE_RISK in r["flags"]

    def test_emission_floor_support_flag(self):
        r = analyze(_gauge(current_emission_tokens_per_week=100_000.0,
                           emission_decay_pct_per_week=10.0,
                           emission_floor_tokens_per_week=50_000.0,
                           weeks_horizon=52.0), config=_cfg())
        assert FLAG_EMISSION_FLOOR_SUPPORT in r["flags"]

    def test_insufficient_data_flag_zero_tvl(self):
        r = analyze(_gauge(lp_tvl_usd=0.0), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]
        assert r["classification"] == CLASS_STABLE

    def test_insufficient_data_zero_emission(self):
        r = analyze(_gauge(current_emission_tokens_per_week=0.0), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]

    def test_insufficient_data_zero_price(self):
        r = analyze(_gauge(reward_token_price_usd=0.0), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]

    def test_name_preserved(self):
        r = analyze(_gauge(name="vAMM-USDC/ETH"), config=_cfg())
        assert r["name"] == "vAMM-USDC/ETH"

    def test_recommendations_is_list(self):
        r = analyze(_gauge(), config=_cfg())
        assert isinstance(r["recommendations"], list)
        assert len(r["recommendations"]) >= 1

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_gauge(), config=_cfg())
        after = time.time()
        assert before <= r["timestamp"] <= after

    def test_flags_valid(self):
        r = analyze(_gauge(emission_decay_pct_per_week=5.0,
                           reward_token_price_usd=0.005,
                           base_yield_apr_pct=1.0), config=_cfg())
        for flag in r["flags"]:
            assert flag in ALL_FLAGS

    def test_severity_bounded(self):
        r = analyze(_gauge(), config=_cfg())
        assert 0.0 <= r["apr_cliff_severity_score"] <= 100.0

    def test_dependence_bounded(self):
        r = analyze(_gauge(), config=_cfg())
        assert 0.0 <= r["incentive_dependence_pct"] <= 100.0

    def test_clamps_gauge_share(self):
        r = analyze(_gauge(gauge_share_pct=200.0), config=_cfg())
        assert r["gauge_share_pct"] == 100.0

    def test_kwargs_override_dict(self):
        r = analyze(_gauge(lp_tvl_usd=2_000_000.0), lp_tvl_usd=4_000_000.0,
                    config=_cfg())
        assert r["lp_tvl_usd"] == 4_000_000.0

    def test_kwargs_only(self):
        r = analyze(current_emission_tokens_per_week=100_000.0,
                    reward_token_price_usd=0.50, lp_tvl_usd=2_000_000.0,
                    config=_cfg())
        assert r["current_incentive_apr_pct"] == pytest.approx(130.0)

    def test_default_weeks_horizon(self):
        r = analyze(_gauge(), config=_cfg())
        # weeks_horizon default carried from dict, but check default kicks in
        r2 = analyze(current_emission_tokens_per_week=100_000.0,
                     reward_token_price_usd=0.50, lp_tvl_usd=2_000_000.0,
                     config=_cfg())
        assert r2["weeks_horizon"] == 52.0

    def test_default_gauge_share(self):
        r = analyze(current_emission_tokens_per_week=100_000.0,
                    reward_token_price_usd=0.50, lp_tvl_usd=2_000_000.0,
                    config=_cfg())
        assert r["gauge_share_pct"] == 100.0


# ===========================================================================
# 14. analyze — robustness / no crash
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
        r = analyze({"name": "X", "current_emission_tokens_per_week": "100000",
                     "reward_token_price_usd": "0.5", "lp_tvl_usd": "2000000",
                     "gauge_share_pct": "100"}, config=_cfg())
        assert r["current_incentive_apr_pct"] == pytest.approx(130.0)

    def test_garbage_numeric_fields(self):
        r = analyze({"name": "X", "current_emission_tokens_per_week": "abc",
                     "reward_token_price_usd": None, "lp_tvl_usd": "xyz"},
                    config=_cfg())
        assert "classification" in r

    def test_no_zero_division_all_zeros(self):
        r = analyze(_gauge(current_emission_tokens_per_week=0.0,
                           emission_decay_pct_per_week=0.0,
                           reward_token_price_usd=0.0, lp_tvl_usd=0.0,
                           base_yield_apr_pct=0.0), config=_cfg())
        assert "classification" in r

    def test_negative_tvl_clamped(self):
        r = analyze(_gauge(lp_tvl_usd=-1e6), config=_cfg())
        assert r["lp_tvl_usd"] == 0.0

    def test_negative_emission_clamped(self):
        r = analyze(_gauge(current_emission_tokens_per_week=-100.0), config=_cfg())
        assert r["current_emission_tokens_per_week"] == 0.0

    def test_negative_price_clamped(self):
        r = analyze(_gauge(reward_token_price_usd=-1.0), config=_cfg())
        assert r["reward_token_price_usd"] == 0.0

    def test_negative_floor_clamped(self):
        r = analyze(_gauge(emission_floor_tokens_per_week=-5.0), config=_cfg())
        assert r["emission_floor_tokens_per_week"] == 0.0

    def test_does_not_raise_on_bad_log_path(self):
        r = analyze(_gauge(), config={"log_path": "/dev/null/cannot/log.json"})
        assert "classification" in r

    def test_default_log_path_used(self):
        r = analyze(_gauge())
        assert "classification" in r


# ===========================================================================
# 15. Logging via config
# ===========================================================================

class TestLogging:
    def test_writes_log(self):
        path = _tmp_log()
        analyze(_gauge(), config={"log_path": path})
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 1
        os.unlink(path)

    def test_log_accumulates(self):
        path = _tmp_log()
        analyze(_gauge(name="A"), config={"log_path": path})
        analyze(_gauge(name="B"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 2
        assert data[0]["name"] == "A"
        assert data[1]["name"] == "B"
        os.unlink(path)

    def test_log_ring_buffer_cap(self, tmp_path):
        path = str(tmp_path / "gauge_log.json")
        for i in range(120):
            analyze(_gauge(name=f"G{i}"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 100
        assert data[-1]["name"] == "G119"
        assert data[0]["name"] == "G20"

    def test_idempotent_rerun(self, tmp_path):
        path = str(tmp_path / "gauge_log.json")
        g = _gauge(name="Same")
        r1 = analyze(g, config={"log_path": path})
        r2 = analyze(g, config={"log_path": path})
        assert r1["classification"] == r2["classification"]
        assert r1["apr_cliff_severity_score"] == r2["apr_cliff_severity_score"]
        assert r1["flags"] == r2["flags"]

    def test_log_via_tmp_path(self, tmp_path):
        path = str(tmp_path / "out.json")
        analyze(_gauge(), config={"log_path": path})
        assert os.path.exists(path)


# ===========================================================================
# 16. Determinism
# ===========================================================================

class TestDeterminism:
    def test_same_inputs_same_metrics(self):
        g = _gauge(name="Det")
        r1 = analyze(g, config=_cfg())
        r2 = analyze(g, config=_cfg())
        assert r1["current_incentive_apr_pct"] == r2["current_incentive_apr_pct"]
        assert r1["projected_incentive_apr_at_horizon_pct"] == \
            r2["projected_incentive_apr_at_horizon_pct"]
        assert r1["apr_cliff_severity_score"] == r2["apr_cliff_severity_score"]
        assert r1["classification"] == r2["classification"]
        assert r1["grade"] == r2["grade"]

    def test_half_life_deterministic(self):
        hl1 = _incentive_apr_half_life_weeks(2.0, 100_000.0, 0.0)
        hl2 = _incentive_apr_half_life_weeks(2.0, 100_000.0, 0.0)
        assert hl1 == hl2


# ===========================================================================
# 17. Monotonicity sanity checks
# ===========================================================================

class TestMonotonicity:
    def test_more_decay_higher_severity(self):
        slow = analyze(_gauge(emission_decay_pct_per_week=0.5), config=_cfg())
        fast = analyze(_gauge(emission_decay_pct_per_week=4.0), config=_cfg())
        assert fast["apr_cliff_severity_score"] >= slow["apr_cliff_severity_score"]

    def test_higher_dependence_higher_severity(self):
        low_dep = analyze(_gauge(base_yield_apr_pct=100.0,
                                 emission_decay_pct_per_week=2.0), config=_cfg())
        high_dep = analyze(_gauge(base_yield_apr_pct=1.0,
                                  emission_decay_pct_per_week=2.0), config=_cfg())
        assert high_dep["apr_cliff_severity_score"] >= low_dep["apr_cliff_severity_score"]

    def test_more_decay_lower_projected_apr(self):
        slow = analyze(_gauge(emission_decay_pct_per_week=1.0), config=_cfg())
        fast = analyze(_gauge(emission_decay_pct_per_week=4.0), config=_cfg())
        assert fast["projected_incentive_apr_at_horizon_pct"] <= \
            slow["projected_incentive_apr_at_horizon_pct"]

    def test_more_decay_shorter_half_life(self):
        slow = analyze(_gauge(emission_decay_pct_per_week=1.0), config=_cfg())
        fast = analyze(_gauge(emission_decay_pct_per_week=4.0), config=_cfg())
        assert fast["incentive_apr_half_life_weeks"] <= \
            slow["incentive_apr_half_life_weeks"]

    def test_higher_tvl_lower_apr(self):
        small = analyze(_gauge(lp_tvl_usd=1_000_000.0), config=_cfg())
        big = analyze(_gauge(lp_tvl_usd=4_000_000.0), config=_cfg())
        assert big["current_incentive_apr_pct"] < small["current_incentive_apr_pct"]


# ===========================================================================
# 18. analyze_portfolio
# ===========================================================================

class TestAnalyzePortfolio:
    def test_empty_list(self):
        s = analyze_portfolio([], config=_cfg())
        assert s["total_gauges"] == 0
        assert s["most_at_risk_gauge"] is None
        assert s["least_at_risk_gauge"] is None
        assert s["avg_apr_cliff_severity_score"] == 0.0
        assert s["steep_decay_count"] == 0
        assert s["results"] == []

    def test_single_gauge(self):
        s = analyze_portfolio([_gauge(name="Solo")], config=_cfg())
        assert s["total_gauges"] == 1
        assert s["most_at_risk_gauge"] == "Solo"
        assert s["least_at_risk_gauge"] == "Solo"
        assert len(s["results"]) == 1

    def test_multiple_picks_most_and_least(self):
        steep = _gauge(name="Steep", emission_decay_pct_per_week=5.0,
                       base_yield_apr_pct=1.0)
        stable = _gauge(name="Stable", emission_decay_pct_per_week=0.0,
                        base_yield_apr_pct=5.0)
        s = analyze_portfolio([steep, stable], config=_cfg())
        assert s["total_gauges"] == 2
        assert s["most_at_risk_gauge"] == "Steep"
        assert s["least_at_risk_gauge"] == "Stable"

    def test_avg_score(self):
        gauges = [_gauge(name="A"), _gauge(name="B")]
        s = analyze_portfolio(gauges, config=_cfg())
        per = [r["apr_cliff_severity_score"] for r in s["results"]]
        assert s["avg_apr_cliff_severity_score"] == pytest.approx(sum(per) / len(per))

    def test_steep_decay_count(self):
        gauges = [
            _gauge(name="Stable", emission_decay_pct_per_week=0.0),
            _gauge(name="Steep1", emission_decay_pct_per_week=5.0,
                   base_yield_apr_pct=1.0),
            _gauge(name="Steep2", emission_decay_pct_per_week=4.0,
                   base_yield_apr_pct=1.0),
        ]
        s = analyze_portfolio(gauges, config=_cfg())
        assert s["steep_decay_count"] == 2

    def test_results_count_matches(self):
        gauges = [_gauge(name=f"G{i}") for i in range(5)]
        s = analyze_portfolio(gauges, config=_cfg())
        assert len(s["results"]) == 5
        assert s["total_gauges"] == 5

    def test_non_list_input(self):
        s = analyze_portfolio("notalist", config=_cfg())
        assert s["total_gauges"] == 0

    def test_handles_non_dict_entries(self):
        s = analyze_portfolio([_gauge(name="ok"), "garbage", 42], config=_cfg())
        assert s["total_gauges"] == 3

    def test_all_results_have_classification(self):
        gauges = [_gauge(name=f"G{i}") for i in range(3)]
        s = analyze_portfolio(gauges, config=_cfg())
        for r in s["results"]:
            assert r["classification"] in ALL_CLASSIFICATIONS

    def test_avg_bounded(self):
        gauges = [_gauge(name=f"G{i}", emission_decay_pct_per_week=i)
                  for i in range(5)]
        s = analyze_portfolio(gauges, config=_cfg())
        assert 0.0 <= s["avg_apr_cliff_severity_score"] <= 100.0


# ===========================================================================
# 19. Class wrapper parity
# ===========================================================================

class TestClassWrapper:
    def test_instantiation(self):
        f = DeFiProtocolGaugeEmissionDecayForecaster()
        assert f is not None

    def test_analyze_returns_dict(self):
        f = DeFiProtocolGaugeEmissionDecayForecaster(config=_cfg())
        r = f.analyze(_gauge())
        assert isinstance(r, dict)

    def test_analyze_parity_with_function(self):
        cfg = _cfg()
        g = _gauge(name="Parity")
        r_func = analyze(g, config=cfg)
        r_class = DeFiProtocolGaugeEmissionDecayForecaster(config=cfg).analyze(g)
        assert r_func["classification"] == r_class["classification"]
        assert r_func["apr_cliff_severity_score"] == r_class["apr_cliff_severity_score"]
        assert r_func["flags"] == r_class["flags"]

    def test_analyze_kwargs_via_class(self):
        f = DeFiProtocolGaugeEmissionDecayForecaster(config=_cfg())
        r = f.analyze(current_emission_tokens_per_week=100_000.0,
                      reward_token_price_usd=0.50, lp_tvl_usd=2_000_000.0)
        assert r["current_incentive_apr_pct"] == pytest.approx(130.0)

    def test_portfolio_parity(self):
        cfg = _cfg()
        gauges = [_gauge(name="A"), _gauge(name="B")]
        r_func = analyze_portfolio(gauges, config=cfg)
        r_class = DeFiProtocolGaugeEmissionDecayForecaster(
            config=cfg).analyze_portfolio(gauges)
        assert r_func["total_gauges"] == r_class["total_gauges"]
        assert r_func["most_at_risk_gauge"] == r_class["most_at_risk_gauge"]

    def test_config_forwarded_to_log(self):
        path = _tmp_log()
        f = DeFiProtocolGaugeEmissionDecayForecaster(config={"log_path": path})
        f.analyze(_gauge())
        assert os.path.exists(path)
        with open(path) as fh:
            data = json.load(fh)
        assert len(data) == 1
        os.unlink(path)

    def test_no_config_uses_default(self):
        f = DeFiProtocolGaugeEmissionDecayForecaster()
        r = f.analyze(_gauge())
        assert "classification" in r

    def test_multiple_calls_accumulate(self):
        path = _tmp_log()
        f = DeFiProtocolGaugeEmissionDecayForecaster(config={"log_path": path})
        f.analyze(_gauge(name="A"))
        f.analyze(_gauge(name="B"))
        with open(path) as fh:
            data = json.load(fh)
        assert len(data) == 2
        os.unlink(path)

    def test_class_portfolio_returns_summary(self):
        f = DeFiProtocolGaugeEmissionDecayForecaster(config=_cfg())
        s = f.analyze_portfolio([_gauge(name="X")])
        assert s["total_gauges"] == 1


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

    def test_never_weeks_large(self):
        assert _NEVER_WEEKS >= 1000.0
        assert not math.isinf(_NEVER_WEEKS)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
