"""
Tests for MP-1075 ProtocolDeFiMercenaryCapitalRiskAnalyzer
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

from spa_core.analytics.protocol_defi_mercenary_capital_risk_analyzer import (
    analyze,
    analyze_portfolio,
    _incentive_apr_premium_pct,
    _incentivized_share_pct,
    _tvl_churn_rate_pct,
    _incentive_cost_coverage_ratio,
    _mercenary_tvl_pct,
    _projected_tvl_retention_pct,
    _mercenary_risk_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    ProtocolDeFiMercenaryCapitalRiskAnalyzer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    ALL_GRADES,
    CLASS_STICKY,
    CLASS_MOSTLY_ORGANIC,
    CLASS_MIXED,
    CLASS_INCENTIVE_DEPENDENT,
    CLASS_MERCENARY_DOMINATED,
    FLAG_HIGH_MERCENARY_SHARE,
    FLAG_EMISSIONS_EXCEED_REVENUE,
    FLAG_HIGH_CHURN,
    FLAG_YOUNG_DEPOSIT_BASE,
    FLAG_LARGE_INCENTIVE_PREMIUM,
    FLAG_LOW_RETENTION_RISK,
    FLAG_STICKY_BASE,
    FLAG_ORGANIC_YIELD_STRONG,
    FLAG_INSUFFICIENT_DATA,
    _NO_EMISSIONS_COVERAGE,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _tmp_log():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _protocol(
    name="TestProtocol",
    total_tvl_usd=100_000_000.0,
    incentivized_tvl_usd=40_000_000.0,
    incentive_apr_pct=8.0,
    base_organic_apr_pct=4.0,
    avg_deposit_age_days=90.0,
    tvl_inflow_30d_usd=10_000_000.0,
    tvl_outflow_30d_usd=8_000_000.0,
    reward_token_emissions_usd_per_day=20_000.0,
    protocol_revenue_usd_per_day=30_000.0,
):
    return {
        "name": name,
        "total_tvl_usd": total_tvl_usd,
        "incentivized_tvl_usd": incentivized_tvl_usd,
        "incentive_apr_pct": incentive_apr_pct,
        "base_organic_apr_pct": base_organic_apr_pct,
        "avg_deposit_age_days": avg_deposit_age_days,
        "tvl_inflow_30d_usd": tvl_inflow_30d_usd,
        "tvl_outflow_30d_usd": tvl_outflow_30d_usd,
        "reward_token_emissions_usd_per_day": reward_token_emissions_usd_per_day,
        "protocol_revenue_usd_per_day": protocol_revenue_usd_per_day,
    }


def _mercenary(name="Merc"):
    """A protocol expected to classify as mercenary-dominated."""
    return _protocol(
        name=name,
        total_tvl_usd=50_000_000.0,
        incentivized_tvl_usd=48_000_000.0,
        incentive_apr_pct=40.0,
        base_organic_apr_pct=2.0,
        avg_deposit_age_days=9.0,
        tvl_inflow_30d_usd=30_000_000.0,
        tvl_outflow_30d_usd=25_000_000.0,
        reward_token_emissions_usd_per_day=100_000.0,
        protocol_revenue_usd_per_day=20_000.0,
    )


def _sticky(name="Sticky"):
    """A protocol expected to classify as sticky / organic."""
    return _protocol(
        name=name,
        total_tvl_usd=800_000_000.0,
        incentivized_tvl_usd=20_000_000.0,
        incentive_apr_pct=5.0,
        base_organic_apr_pct=4.5,
        avg_deposit_age_days=250.0,
        tvl_inflow_30d_usd=10_000_000.0,
        tvl_outflow_30d_usd=5_000_000.0,
        reward_token_emissions_usd_per_day=3_000.0,
        protocol_revenue_usd_per_day=60_000.0,
    )


def _cfg():
    return {"log_path": _tmp_log()}


# ===========================================================================
# 1. _incentive_apr_premium_pct
# ===========================================================================

class TestPremium:
    def test_basic_math(self):
        assert _incentive_apr_premium_pct(8.0, 4.0) == pytest.approx(4.0)

    def test_no_premium_when_equal(self):
        assert _incentive_apr_premium_pct(4.0, 4.0) == pytest.approx(0.0)

    def test_clamped_to_zero_when_negative(self):
        assert _incentive_apr_premium_pct(2.0, 5.0) == pytest.approx(0.0)

    def test_large_premium(self):
        assert _incentive_apr_premium_pct(40.0, 2.0) == pytest.approx(38.0)

    def test_zero_base(self):
        assert _incentive_apr_premium_pct(10.0, 0.0) == pytest.approx(10.0)

    def test_never_negative(self):
        for inc in [0.0, 5.0, 10.0]:
            for base in [0.0, 5.0, 20.0]:
                assert _incentive_apr_premium_pct(inc, base) >= 0.0


# ===========================================================================
# 2. _incentivized_share_pct
# ===========================================================================

class TestIncentivizedShare:
    def test_basic_math(self):
        assert _incentivized_share_pct(40_000_000.0, 100_000_000.0) == pytest.approx(40.0)

    def test_zero_total_returns_zero(self):
        assert _incentivized_share_pct(40_000_000.0, 0.0) == 0.0

    def test_negative_total_returns_zero(self):
        assert _incentivized_share_pct(40_000_000.0, -5.0) == 0.0

    def test_all_incentivized(self):
        assert _incentivized_share_pct(1e8, 1e8) == pytest.approx(100.0)

    def test_clamped_above_100(self):
        # cannot exceed 100 even if input is malformed
        assert _incentivized_share_pct(2e8, 1e8) == pytest.approx(100.0)

    def test_zero_incentivized(self):
        assert _incentivized_share_pct(0.0, 1e8) == pytest.approx(0.0)

    def test_no_zero_division(self):
        _incentivized_share_pct(0.0, 0.0)


# ===========================================================================
# 3. _tvl_churn_rate_pct
# ===========================================================================

class TestChurn:
    def test_basic_math(self):
        assert _tvl_churn_rate_pct(8_000_000.0, 100_000_000.0) == pytest.approx(8.0)

    def test_zero_total_returns_zero(self):
        assert _tvl_churn_rate_pct(8_000_000.0, 0.0) == 0.0

    def test_negative_total_returns_zero(self):
        assert _tvl_churn_rate_pct(8_000_000.0, -1.0) == 0.0

    def test_zero_outflow(self):
        assert _tvl_churn_rate_pct(0.0, 1e8) == pytest.approx(0.0)

    def test_outflow_exceeds_tvl(self):
        # not clamped above 100
        assert _tvl_churn_rate_pct(1.5e8, 1e8) == pytest.approx(150.0)

    def test_never_negative(self):
        assert _tvl_churn_rate_pct(-5.0, 1e8) >= 0.0

    def test_no_zero_division(self):
        _tvl_churn_rate_pct(0.0, 0.0)


# ===========================================================================
# 4. _incentive_cost_coverage_ratio
# ===========================================================================

class TestCoverage:
    def test_basic_math(self):
        ratio, no_em = _incentive_cost_coverage_ratio(30_000.0, 20_000.0)
        assert ratio == pytest.approx(1.5)
        assert no_em is False

    def test_no_emissions_sentinel(self):
        ratio, no_em = _incentive_cost_coverage_ratio(30_000.0, 0.0)
        assert ratio == _NO_EMISSIONS_COVERAGE
        assert no_em is True

    def test_negative_emissions_treated_as_none(self):
        ratio, no_em = _incentive_cost_coverage_ratio(30_000.0, -5.0)
        assert no_em is True
        assert ratio == _NO_EMISSIONS_COVERAGE

    def test_undercovered(self):
        ratio, no_em = _incentive_cost_coverage_ratio(10_000.0, 20_000.0)
        assert ratio == pytest.approx(0.5)
        assert no_em is False

    def test_exactly_covered(self):
        ratio, no_em = _incentive_cost_coverage_ratio(20_000.0, 20_000.0)
        assert ratio == pytest.approx(1.0)
        assert no_em is False

    def test_zero_revenue_with_emissions(self):
        ratio, no_em = _incentive_cost_coverage_ratio(0.0, 20_000.0)
        assert ratio == pytest.approx(0.0)
        assert no_em is False

    def test_no_zero_division(self):
        _incentive_cost_coverage_ratio(0.0, 0.0)

    def test_sentinel_is_large_finite(self):
        assert _NO_EMISSIONS_COVERAGE >= 100.0
        assert not math.isinf(_NO_EMISSIONS_COVERAGE)


# ===========================================================================
# 5. _mercenary_tvl_pct
# ===========================================================================

class TestMercenaryPct:
    def test_zero_incentivized_share_zero(self):
        # nothing incentivized → no mercenary capital
        assert _mercenary_tvl_pct(0.0, 40.0, 5.0, 50.0) == pytest.approx(0.0)

    def test_capped_by_incentivized_share(self):
        m = _mercenary_tvl_pct(50.0, 40.0, 0.0, 100.0)
        assert m <= 50.0

    def test_bounded_0_100(self):
        for share in [0.0, 50.0, 100.0]:
            for prem in [0.0, 10.0, 50.0]:
                for age in [0.0, 30.0, 200.0]:
                    for churn in [0.0, 30.0, 100.0]:
                        m = _mercenary_tvl_pct(share, prem, age, churn)
                        assert 0.0 <= m <= 100.0

    def test_higher_premium_more_mercenary(self):
        low = _mercenary_tvl_pct(100.0, 1.0, 90.0, 10.0)
        high = _mercenary_tvl_pct(100.0, 20.0, 90.0, 10.0)
        assert high > low

    def test_younger_more_mercenary(self):
        old = _mercenary_tvl_pct(100.0, 10.0, 180.0, 10.0)
        young = _mercenary_tvl_pct(100.0, 10.0, 1.0, 10.0)
        assert young > old

    def test_higher_churn_more_mercenary(self):
        low = _mercenary_tvl_pct(100.0, 10.0, 90.0, 5.0)
        high = _mercenary_tvl_pct(100.0, 10.0, 90.0, 60.0)
        assert high > low

    def test_more_incentivized_share_more_mercenary(self):
        low = _mercenary_tvl_pct(20.0, 20.0, 5.0, 50.0)
        high = _mercenary_tvl_pct(90.0, 20.0, 5.0, 50.0)
        assert high > low

    def test_extreme_mercenary_scenario(self):
        m = _mercenary_tvl_pct(100.0, 50.0, 0.0, 100.0)
        assert m >= 80.0


# ===========================================================================
# 6. _projected_tvl_retention_pct
# ===========================================================================

class TestRetention:
    def test_starts_from_sticky(self):
        # 0 mercenary, 0 organic, 0 premium → 100 retention
        r = _projected_tvl_retention_pct(0.0, 0.0, 0.0)
        assert r == pytest.approx(100.0)

    def test_high_mercenary_low_retention(self):
        r = _projected_tvl_retention_pct(90.0, 0.0, 0.0)
        assert r < 20.0

    def test_organic_bonus_raises(self):
        no_organic = _projected_tvl_retention_pct(50.0, 0.0, 0.0)
        with_organic = _projected_tvl_retention_pct(50.0, 8.0, 0.0)
        assert with_organic > no_organic

    def test_premium_drag_lowers(self):
        no_prem = _projected_tvl_retention_pct(50.0, 0.0, 0.0)
        big_prem = _projected_tvl_retention_pct(50.0, 0.0, 20.0)
        assert big_prem < no_prem

    def test_bounded_0_100(self):
        for merc in [0.0, 50.0, 100.0]:
            for organic in [0.0, 4.0, 20.0]:
                for prem in [0.0, 5.0, 50.0]:
                    r = _projected_tvl_retention_pct(merc, organic, prem)
                    assert 0.0 <= r <= 100.0

    def test_higher_mercenary_lower_retention(self):
        low = _projected_tvl_retention_pct(20.0, 4.0, 5.0)
        high = _projected_tvl_retention_pct(80.0, 4.0, 5.0)
        assert high < low


# ===========================================================================
# 7. _mercenary_risk_score
# ===========================================================================

class TestRiskScore:
    def test_no_data_zero(self):
        s = _mercenary_risk_score(90.0, 50.0, 0.2, False, 5.0, has_data=False)
        assert s == 0.0

    def test_max_risk(self):
        s = _mercenary_risk_score(100.0, 100.0, 0.0, False, 0.0, has_data=True)
        assert s == pytest.approx(100.0)

    def test_min_risk(self):
        s = _mercenary_risk_score(0.0, 0.0, 5.0, False, 100.0, has_data=True)
        assert s == pytest.approx(0.0)

    def test_bounded_0_100(self):
        for merc in [0.0, 50.0, 100.0]:
            for churn in [0.0, 30.0, 100.0]:
                for cov in [0.0, 0.5, 2.0]:
                    for ret in [0.0, 50.0, 100.0]:
                        s = _mercenary_risk_score(merc, churn, cov, False, ret,
                                                  has_data=True)
                        assert 0.0 <= s <= 100.0

    def test_higher_mercenary_higher_risk(self):
        low = _mercenary_risk_score(20.0, 10.0, 1.5, False, 80.0, has_data=True)
        high = _mercenary_risk_score(80.0, 10.0, 1.5, False, 80.0, has_data=True)
        assert high > low

    def test_higher_churn_higher_risk(self):
        low = _mercenary_risk_score(50.0, 5.0, 1.5, False, 50.0, has_data=True)
        high = _mercenary_risk_score(50.0, 60.0, 1.5, False, 50.0, has_data=True)
        assert high > low

    def test_poor_coverage_higher_risk(self):
        good = _mercenary_risk_score(50.0, 10.0, 2.0, False, 50.0, has_data=True)
        bad = _mercenary_risk_score(50.0, 10.0, 0.1, False, 50.0, has_data=True)
        assert bad > good

    def test_no_emissions_no_coverage_penalty(self):
        s_no_em = _mercenary_risk_score(50.0, 10.0, 999.0, True, 50.0, has_data=True)
        s_covered = _mercenary_risk_score(50.0, 10.0, 2.0, False, 50.0, has_data=True)
        assert s_no_em == pytest.approx(s_covered)

    def test_lower_retention_higher_risk(self):
        high_ret = _mercenary_risk_score(50.0, 10.0, 1.5, False, 90.0, has_data=True)
        low_ret = _mercenary_risk_score(50.0, 10.0, 1.5, False, 10.0, has_data=True)
        assert low_ret > high_ret


# ===========================================================================
# 8. _classify
# ===========================================================================

class TestClassify:
    def test_no_data_sticky(self):
        assert _classify(90.0, 90.0, has_data=False) == CLASS_STICKY

    def test_sticky(self):
        assert _classify(10.0, 5.0, has_data=True) == CLASS_STICKY

    def test_mostly_organic(self):
        assert _classify(30.0, 20.0, has_data=True) == CLASS_MOSTLY_ORGANIC

    def test_mixed(self):
        assert _classify(50.0, 30.0, has_data=True) == CLASS_MIXED

    def test_incentive_dependent(self):
        assert _classify(70.0, 50.0, has_data=True) == CLASS_INCENTIVE_DEPENDENT

    def test_mercenary_dominated(self):
        assert _classify(90.0, 50.0, has_data=True) == CLASS_MERCENARY_DOMINATED

    def test_risk_downgrade(self):
        # 70 → INCENTIVE_DEPENDENT, but high risk downgrades to MERCENARY_DOMINATED
        base = _classify(70.0, 10.0, has_data=True)
        downgraded = _classify(70.0, 80.0, has_data=True)
        assert base == CLASS_INCENTIVE_DEPENDENT
        assert downgraded == CLASS_MERCENARY_DOMINATED

    def test_all_bands_reachable(self):
        seen = {
            _classify(10.0, 5.0, has_data=True),
            _classify(30.0, 20.0, has_data=True),
            _classify(50.0, 30.0, has_data=True),
            _classify(70.0, 50.0, has_data=True),
            _classify(90.0, 50.0, has_data=True),
        }
        assert seen == set(ALL_CLASSIFICATIONS)

    def test_returns_valid_classification(self):
        for merc in [0, 20, 40, 60, 80, 100]:
            for risk in [0, 50, 100]:
                c = _classify(merc, risk, has_data=True)
                assert c in ALL_CLASSIFICATIONS

    def test_boundary_20(self):
        assert _classify(19.99, 10.0, has_data=True) == CLASS_STICKY
        assert _classify(20.0, 10.0, has_data=True) == CLASS_MOSTLY_ORGANIC

    def test_boundary_80(self):
        assert _classify(79.99, 10.0, has_data=True) == CLASS_INCENTIVE_DEPENDENT
        assert _classify(80.0, 10.0, has_data=True) == CLASS_MERCENARY_DOMINATED


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
        f = _flags(90.0, 10.0, 0.2, False, 50.0, 5.0, 30.0, 5.0, 2.0,
                   has_data=False)
        assert f == [FLAG_INSUFFICIENT_DATA]

    def test_high_mercenary_share(self):
        f = _flags(70.0, 30.0, 1.5, False, 10.0, 90.0, 2.0, 80.0, 4.0,
                   has_data=True)
        assert FLAG_HIGH_MERCENARY_SHARE in f

    def test_low_mercenary_no_flag(self):
        f = _flags(30.0, 70.0, 1.5, False, 10.0, 90.0, 2.0, 80.0, 4.0,
                   has_data=True)
        assert FLAG_HIGH_MERCENARY_SHARE not in f

    def test_emissions_exceed_revenue(self):
        f = _flags(50.0, 50.0, 0.5, False, 10.0, 90.0, 2.0, 80.0, 4.0,
                   has_data=True)
        assert FLAG_EMISSIONS_EXCEED_REVENUE in f

    def test_covered_no_exceed_flag(self):
        f = _flags(50.0, 50.0, 1.5, False, 10.0, 90.0, 2.0, 80.0, 4.0,
                   has_data=True)
        assert FLAG_EMISSIONS_EXCEED_REVENUE not in f

    def test_no_emissions_no_exceed_flag(self):
        f = _flags(50.0, 50.0, 999.0, True, 10.0, 90.0, 2.0, 80.0, 4.0,
                   has_data=True)
        assert FLAG_EMISSIONS_EXCEED_REVENUE not in f

    def test_high_churn(self):
        f = _flags(50.0, 50.0, 1.5, False, 40.0, 90.0, 2.0, 80.0, 4.0,
                   has_data=True)
        assert FLAG_HIGH_CHURN in f

    def test_low_churn_no_flag(self):
        f = _flags(50.0, 50.0, 1.5, False, 5.0, 90.0, 2.0, 80.0, 4.0,
                   has_data=True)
        assert FLAG_HIGH_CHURN not in f

    def test_young_deposit_base(self):
        f = _flags(50.0, 50.0, 1.5, False, 10.0, 9.0, 2.0, 80.0, 4.0,
                   has_data=True)
        assert FLAG_YOUNG_DEPOSIT_BASE in f

    def test_old_deposit_no_flag(self):
        f = _flags(50.0, 50.0, 1.5, False, 10.0, 200.0, 2.0, 80.0, 4.0,
                   has_data=True)
        assert FLAG_YOUNG_DEPOSIT_BASE not in f

    def test_zero_age_no_young_flag(self):
        # 0 age means unknown, not flagged
        f = _flags(50.0, 50.0, 1.5, False, 10.0, 0.0, 2.0, 80.0, 4.0,
                   has_data=True)
        assert FLAG_YOUNG_DEPOSIT_BASE not in f

    def test_large_incentive_premium(self):
        f = _flags(50.0, 50.0, 1.5, False, 10.0, 90.0, 10.0, 80.0, 4.0,
                   has_data=True)
        assert FLAG_LARGE_INCENTIVE_PREMIUM in f

    def test_small_premium_no_flag(self):
        f = _flags(50.0, 50.0, 1.5, False, 10.0, 90.0, 1.0, 80.0, 4.0,
                   has_data=True)
        assert FLAG_LARGE_INCENTIVE_PREMIUM not in f

    def test_low_retention_risk(self):
        f = _flags(70.0, 30.0, 1.5, False, 10.0, 90.0, 2.0, 20.0, 4.0,
                   has_data=True)
        assert FLAG_LOW_RETENTION_RISK in f

    def test_high_retention_no_flag(self):
        f = _flags(30.0, 70.0, 1.5, False, 10.0, 90.0, 2.0, 80.0, 4.0,
                   has_data=True)
        assert FLAG_LOW_RETENTION_RISK not in f

    def test_sticky_base(self):
        f = _flags(30.0, 70.0, 1.5, False, 10.0, 90.0, 2.0, 80.0, 4.0,
                   has_data=True)
        assert FLAG_STICKY_BASE in f

    def test_organic_yield_strong(self):
        f = _flags(50.0, 50.0, 1.5, False, 10.0, 90.0, 2.0, 80.0, 5.0,
                   has_data=True)
        assert FLAG_ORGANIC_YIELD_STRONG in f

    def test_weak_organic_no_flag(self):
        f = _flags(50.0, 50.0, 1.5, False, 10.0, 90.0, 2.0, 80.0, 2.0,
                   has_data=True)
        assert FLAG_ORGANIC_YIELD_STRONG not in f

    def test_all_flags_valid(self):
        f = _flags(90.0, 10.0, 0.2, False, 50.0, 9.0, 30.0, 10.0, 5.0,
                   has_data=True)
        for flag in f:
            assert flag in ALL_FLAGS


# ===========================================================================
# 11. _recommendations
# ===========================================================================

class TestRecommendations:
    def test_insufficient_data(self):
        recs = _recommendations(
            CLASS_STICKY, [FLAG_INSUFFICIENT_DATA], 0.0, 0.0, 0.0,
            999.0, 0.0, has_data=False,
        )
        assert len(recs) >= 1
        assert any("insufficient" in r.lower() for r in recs)

    def test_mercenary_dominated_mentions(self):
        recs = _recommendations(
            CLASS_MERCENARY_DOMINATED, [], 90.0, 10.0, 5.0, 0.2, 50.0,
            has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "mercenary" in combined

    def test_returns_list_for_each_class(self):
        for c in ALL_CLASSIFICATIONS:
            recs = _recommendations(
                c, [], 50.0, 50.0, 50.0, 1.0, 20.0, has_data=True,
            )
            assert isinstance(recs, list)
            assert len(recs) >= 1

    def test_emissions_exceed_mentioned(self):
        recs = _recommendations(
            CLASS_INCENTIVE_DEPENDENT, [FLAG_EMISSIONS_EXCEED_REVENUE],
            70.0, 30.0, 30.0, 0.2, 20.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "emission" in combined or "revenue" in combined

    def test_high_churn_mentioned(self):
        recs = _recommendations(
            CLASS_MIXED, [FLAG_HIGH_CHURN],
            50.0, 50.0, 50.0, 1.0, 40.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "churn" in combined

    def test_young_base_mentioned(self):
        recs = _recommendations(
            CLASS_MIXED, [FLAG_YOUNG_DEPOSIT_BASE],
            50.0, 50.0, 50.0, 1.0, 10.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "young" in combined or "recent" in combined or "deposit" in combined

    def test_large_premium_mentioned(self):
        recs = _recommendations(
            CLASS_MIXED, [FLAG_LARGE_INCENTIVE_PREMIUM],
            50.0, 50.0, 50.0, 1.0, 10.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "premium" in combined or "subsid" in combined

    def test_low_retention_mentioned(self):
        recs = _recommendations(
            CLASS_INCENTIVE_DEPENDENT, [FLAG_LOW_RETENTION_RISK],
            70.0, 30.0, 20.0, 1.0, 10.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "retention" in combined or "remain" in combined

    def test_sticky_base_mentioned(self):
        recs = _recommendations(
            CLASS_STICKY, [FLAG_STICKY_BASE],
            10.0, 90.0, 90.0, 1.0, 10.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "sticky" in combined

    def test_organic_strong_mentioned(self):
        recs = _recommendations(
            CLASS_STICKY, [FLAG_ORGANIC_YIELD_STRONG],
            10.0, 90.0, 90.0, 1.0, 10.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "organic" in combined


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
        r = analyze(_protocol(), config=_cfg())
        assert isinstance(r, dict)

    def test_required_keys(self):
        r = analyze(_protocol(), config=_cfg())
        for key in [
            "name",
            "incentive_apr_premium_pct",
            "mercenary_tvl_pct",
            "sticky_tvl_pct",
            "tvl_churn_rate_pct",
            "incentive_cost_coverage_ratio",
            "projected_tvl_retention_pct",
            "mercenary_risk_score",
            "classification",
            "grade",
            "flags",
            "recommendations",
            "timestamp",
        ]:
            assert key in r

    def test_premium_math(self):
        r = analyze(_protocol(incentive_apr_pct=8.0, base_organic_apr_pct=4.0),
                    config=_cfg())
        assert r["incentive_apr_premium_pct"] == pytest.approx(4.0)

    def test_churn_math(self):
        r = analyze(_protocol(tvl_outflow_30d_usd=8_000_000.0,
                              total_tvl_usd=100_000_000.0), config=_cfg())
        assert r["tvl_churn_rate_pct"] == pytest.approx(8.0)

    def test_coverage_math(self):
        r = analyze(_protocol(protocol_revenue_usd_per_day=30_000.0,
                              reward_token_emissions_usd_per_day=20_000.0),
                    config=_cfg())
        assert r["incentive_cost_coverage_ratio"] == pytest.approx(1.5)

    def test_sticky_plus_mercenary_100(self):
        r = analyze(_protocol(), config=_cfg())
        assert r["mercenary_tvl_pct"] + r["sticky_tvl_pct"] == pytest.approx(100.0)

    def test_classification_valid(self):
        r = analyze(_protocol(), config=_cfg())
        assert r["classification"] in ALL_CLASSIFICATIONS

    def test_grade_valid(self):
        r = analyze(_protocol(), config=_cfg())
        assert r["grade"] in ALL_GRADES

    def test_mercenary_dominated_scenario(self):
        r = analyze(_mercenary(), config=_cfg())
        assert r["classification"] == CLASS_MERCENARY_DOMINATED
        assert FLAG_HIGH_MERCENARY_SHARE in r["flags"]

    def test_sticky_scenario(self):
        r = analyze(_sticky(), config=_cfg())
        assert r["classification"] in (CLASS_STICKY, CLASS_MOSTLY_ORGANIC)
        assert FLAG_STICKY_BASE in r["flags"]

    def test_no_emissions_sentinel(self):
        r = analyze(_protocol(reward_token_emissions_usd_per_day=0.0),
                    config=_cfg())
        assert r["incentive_cost_coverage_ratio"] == _NO_EMISSIONS_COVERAGE
        assert r["no_emissions"] is True

    def test_emissions_exceed_revenue_flag(self):
        r = analyze(_mercenary(), config=_cfg())
        assert FLAG_EMISSIONS_EXCEED_REVENUE in r["flags"]

    def test_high_churn_flag(self):
        r = analyze(_protocol(tvl_outflow_30d_usd=40_000_000.0,
                              total_tvl_usd=100_000_000.0), config=_cfg())
        assert FLAG_HIGH_CHURN in r["flags"]

    def test_young_deposit_flag(self):
        r = analyze(_protocol(avg_deposit_age_days=10.0), config=_cfg())
        assert FLAG_YOUNG_DEPOSIT_BASE in r["flags"]

    def test_large_premium_flag(self):
        r = analyze(_protocol(incentive_apr_pct=40.0, base_organic_apr_pct=2.0),
                    config=_cfg())
        assert FLAG_LARGE_INCENTIVE_PREMIUM in r["flags"]

    def test_low_retention_flag(self):
        r = analyze(_mercenary(), config=_cfg())
        assert FLAG_LOW_RETENTION_RISK in r["flags"]

    def test_organic_yield_strong_flag(self):
        r = analyze(_protocol(base_organic_apr_pct=5.0), config=_cfg())
        assert FLAG_ORGANIC_YIELD_STRONG in r["flags"]

    def test_insufficient_data_flag(self):
        r = analyze(_protocol(total_tvl_usd=0.0), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]
        assert r["classification"] == CLASS_STICKY

    def test_insufficient_data_negative_tvl(self):
        r = analyze(_protocol(total_tvl_usd=-100.0), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]

    def test_name_preserved(self):
        r = analyze(_protocol(name="Convex"), config=_cfg())
        assert r["name"] == "Convex"

    def test_recommendations_is_list(self):
        r = analyze(_protocol(), config=_cfg())
        assert isinstance(r["recommendations"], list)
        assert len(r["recommendations"]) >= 1

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_protocol(), config=_cfg())
        after = time.time()
        assert before <= r["timestamp"] <= after

    def test_flags_valid(self):
        r = analyze(_mercenary(), config=_cfg())
        for flag in r["flags"]:
            assert flag in ALL_FLAGS

    def test_risk_bounded(self):
        r = analyze(_protocol(), config=_cfg())
        assert 0.0 <= r["mercenary_risk_score"] <= 100.0

    def test_mercenary_pct_bounded(self):
        r = analyze(_mercenary(), config=_cfg())
        assert 0.0 <= r["mercenary_tvl_pct"] <= 100.0

    def test_retention_bounded(self):
        r = analyze(_protocol(), config=_cfg())
        assert 0.0 <= r["projected_tvl_retention_pct"] <= 100.0

    def test_incentivized_clamped_to_total(self):
        r = analyze(_protocol(incentivized_tvl_usd=200_000_000.0,
                              total_tvl_usd=100_000_000.0), config=_cfg())
        assert r["incentivized_tvl_usd"] == 100_000_000.0

    def test_kwargs_override_dict(self):
        r = analyze(_protocol(total_tvl_usd=100_000_000.0),
                    total_tvl_usd=50_000_000.0, config=_cfg())
        assert r["total_tvl_usd"] == 50_000_000.0

    def test_kwargs_only(self):
        r = analyze(total_tvl_usd=100_000_000.0,
                    incentivized_tvl_usd=40_000_000.0,
                    config=_cfg())
        assert r["total_tvl_usd"] == 100_000_000.0
        assert r["incentivized_share_pct"] == pytest.approx(40.0)


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
        r = analyze({"name": "X", "total_tvl_usd": "100000000",
                     "incentivized_tvl_usd": "40000000",
                     "tvl_outflow_30d_usd": "8000000"}, config=_cfg())
        assert r["tvl_churn_rate_pct"] == pytest.approx(8.0)

    def test_garbage_numeric_fields(self):
        r = analyze({"name": "X", "total_tvl_usd": "abc",
                     "incentive_apr_pct": None}, config=_cfg())
        assert "classification" in r

    def test_no_zero_division_all_zeros(self):
        r = analyze(_protocol(total_tvl_usd=0.0, incentivized_tvl_usd=0.0,
                              incentive_apr_pct=0.0, base_organic_apr_pct=0.0,
                              avg_deposit_age_days=0.0, tvl_inflow_30d_usd=0.0,
                              tvl_outflow_30d_usd=0.0,
                              reward_token_emissions_usd_per_day=0.0,
                              protocol_revenue_usd_per_day=0.0), config=_cfg())
        assert "classification" in r

    def test_negative_tvl_clamped(self):
        r = analyze(_protocol(total_tvl_usd=-1e6), config=_cfg())
        assert r["total_tvl_usd"] == 0.0

    def test_negative_emissions_clamped(self):
        r = analyze(_protocol(reward_token_emissions_usd_per_day=-100.0),
                    config=_cfg())
        assert r["reward_token_emissions_usd_per_day"] == 0.0

    def test_negative_outflow_clamped(self):
        r = analyze(_protocol(tvl_outflow_30d_usd=-5e6), config=_cfg())
        assert r["tvl_outflow_30d_usd"] == 0.0
        assert r["tvl_churn_rate_pct"] == pytest.approx(0.0)

    def test_does_not_raise_on_bad_log_path(self):
        r = analyze(_protocol(), config={"log_path": "/dev/null/cannot/log.json"})
        assert "classification" in r

    def test_default_log_path_used(self):
        r = analyze(_protocol())
        assert "classification" in r


# ===========================================================================
# 16. Logging via config
# ===========================================================================

class TestLogging:
    def test_writes_log(self):
        path = _tmp_log()
        analyze(_protocol(), config={"log_path": path})
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 1
        os.unlink(path)

    def test_log_accumulates(self):
        path = _tmp_log()
        analyze(_protocol(name="A"), config={"log_path": path})
        analyze(_protocol(name="B"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 2
        assert data[0]["name"] == "A"
        assert data[1]["name"] == "B"
        os.unlink(path)

    def test_log_ring_buffer_cap(self, tmp_path):
        path = str(tmp_path / "merc_log.json")
        for i in range(120):
            analyze(_protocol(name=f"P{i}"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 100
        assert data[-1]["name"] == "P119"
        assert data[0]["name"] == "P20"

    def test_idempotent_rerun(self, tmp_path):
        path = str(tmp_path / "merc_log.json")
        p = _protocol(name="Same")
        r1 = analyze(p, config={"log_path": path})
        r2 = analyze(p, config={"log_path": path})
        assert r1["classification"] == r2["classification"]
        assert r1["mercenary_risk_score"] == r2["mercenary_risk_score"]
        assert r1["flags"] == r2["flags"]

    def test_log_via_tmp_path(self, tmp_path):
        path = str(tmp_path / "out.json")
        analyze(_protocol(), config={"log_path": path})
        assert os.path.exists(path)


# ===========================================================================
# 17. Determinism
# ===========================================================================

class TestDeterminism:
    def test_same_inputs_same_metrics(self):
        p = _protocol(name="Det")
        r1 = analyze(p, config=_cfg())
        r2 = analyze(p, config=_cfg())
        assert r1["mercenary_tvl_pct"] == r2["mercenary_tvl_pct"]
        assert r1["mercenary_risk_score"] == r2["mercenary_risk_score"]
        assert r1["projected_tvl_retention_pct"] == r2["projected_tvl_retention_pct"]
        assert r1["classification"] == r2["classification"]
        assert r1["grade"] == r2["grade"]

    def test_mercenary_pct_deterministic(self):
        m1 = _mercenary_tvl_pct(50.0, 10.0, 30.0, 20.0)
        m2 = _mercenary_tvl_pct(50.0, 10.0, 30.0, 20.0)
        assert m1 == m2


# ===========================================================================
# 18. Monotonicity sanity checks
# ===========================================================================

class TestMonotonicity:
    def test_more_mercenary_higher_risk(self):
        sticky = analyze(_sticky(), config=_cfg())
        merc = analyze(_mercenary(), config=_cfg())
        assert merc["mercenary_risk_score"] > sticky["mercenary_risk_score"]

    def test_higher_premium_higher_mercenary(self):
        low = analyze(_protocol(incentive_apr_pct=5.0, base_organic_apr_pct=4.0,
                                incentivized_tvl_usd=90_000_000.0,
                                total_tvl_usd=100_000_000.0), config=_cfg())
        high = analyze(_protocol(incentive_apr_pct=40.0, base_organic_apr_pct=4.0,
                                 incentivized_tvl_usd=90_000_000.0,
                                 total_tvl_usd=100_000_000.0), config=_cfg())
        assert high["mercenary_tvl_pct"] >= low["mercenary_tvl_pct"]

    def test_younger_higher_mercenary(self):
        old = analyze(_protocol(avg_deposit_age_days=200.0,
                                incentivized_tvl_usd=90_000_000.0,
                                total_tvl_usd=100_000_000.0), config=_cfg())
        young = analyze(_protocol(avg_deposit_age_days=2.0,
                                  incentivized_tvl_usd=90_000_000.0,
                                  total_tvl_usd=100_000_000.0), config=_cfg())
        assert young["mercenary_tvl_pct"] >= old["mercenary_tvl_pct"]

    def test_higher_churn_higher_risk(self):
        low = analyze(_protocol(tvl_outflow_30d_usd=2_000_000.0,
                                total_tvl_usd=100_000_000.0), config=_cfg())
        high = analyze(_protocol(tvl_outflow_30d_usd=50_000_000.0,
                                 total_tvl_usd=100_000_000.0), config=_cfg())
        assert high["mercenary_risk_score"] >= low["mercenary_risk_score"]

    def test_higher_mercenary_lower_retention(self):
        sticky = analyze(_sticky(), config=_cfg())
        merc = analyze(_mercenary(), config=_cfg())
        assert merc["projected_tvl_retention_pct"] < sticky["projected_tvl_retention_pct"]


# ===========================================================================
# 19. analyze_portfolio
# ===========================================================================

class TestAnalyzePortfolio:
    def test_empty_list(self):
        s = analyze_portfolio([], config=_cfg())
        assert s["total_protocols"] == 0
        assert s["most_mercenary_protocol"] is None
        assert s["least_mercenary_protocol"] is None
        assert s["avg_mercenary_risk_score"] == 0.0
        assert s["mercenary_dominated_count"] == 0
        assert s["results"] == []

    def test_single_protocol(self):
        s = analyze_portfolio([_protocol(name="Solo")], config=_cfg())
        assert s["total_protocols"] == 1
        assert s["most_mercenary_protocol"] == "Solo"
        assert s["least_mercenary_protocol"] == "Solo"
        assert len(s["results"]) == 1

    def test_multiple_picks_most_and_least(self):
        s = analyze_portfolio([_mercenary("Merc"), _sticky("Sticky")],
                              config=_cfg())
        assert s["total_protocols"] == 2
        assert s["most_mercenary_protocol"] == "Merc"
        assert s["least_mercenary_protocol"] == "Sticky"

    def test_avg_score(self):
        protocols = [_protocol(name="A"), _protocol(name="B")]
        s = analyze_portfolio(protocols, config=_cfg())
        per = [r["mercenary_risk_score"] for r in s["results"]]
        assert s["avg_mercenary_risk_score"] == pytest.approx(sum(per) / len(per))

    def test_mercenary_dominated_count(self):
        protocols = [_sticky("S"), _mercenary("M1"), _mercenary("M2")]
        s = analyze_portfolio(protocols, config=_cfg())
        assert s["mercenary_dominated_count"] == 2

    def test_results_count_matches(self):
        protocols = [_protocol(name=f"P{i}") for i in range(5)]
        s = analyze_portfolio(protocols, config=_cfg())
        assert len(s["results"]) == 5
        assert s["total_protocols"] == 5

    def test_non_list_input(self):
        s = analyze_portfolio("notalist", config=_cfg())
        assert s["total_protocols"] == 0

    def test_handles_non_dict_entries(self):
        s = analyze_portfolio([_protocol(name="ok"), "garbage", 42], config=_cfg())
        assert s["total_protocols"] == 3

    def test_all_results_have_classification(self):
        protocols = [_protocol(name=f"P{i}") for i in range(3)]
        s = analyze_portfolio(protocols, config=_cfg())
        for r in s["results"]:
            assert r["classification"] in ALL_CLASSIFICATIONS

    def test_avg_bounded(self):
        protocols = [_mercenary("M"), _sticky("S"), _protocol(name="Mid")]
        s = analyze_portfolio(protocols, config=_cfg())
        assert 0.0 <= s["avg_mercenary_risk_score"] <= 100.0


# ===========================================================================
# 20. Class wrapper parity
# ===========================================================================

class TestClassWrapper:
    def test_instantiation(self):
        a = ProtocolDeFiMercenaryCapitalRiskAnalyzer()
        assert a is not None

    def test_analyze_returns_dict(self):
        a = ProtocolDeFiMercenaryCapitalRiskAnalyzer(config=_cfg())
        r = a.analyze(_protocol())
        assert isinstance(r, dict)

    def test_analyze_parity_with_function(self):
        cfg = _cfg()
        p = _protocol(name="Parity")
        r_func = analyze(p, config=cfg)
        r_class = ProtocolDeFiMercenaryCapitalRiskAnalyzer(config=cfg).analyze(p)
        assert r_func["classification"] == r_class["classification"]
        assert r_func["mercenary_risk_score"] == r_class["mercenary_risk_score"]
        assert r_func["flags"] == r_class["flags"]

    def test_analyze_kwargs_via_class(self):
        a = ProtocolDeFiMercenaryCapitalRiskAnalyzer(config=_cfg())
        r = a.analyze(total_tvl_usd=100_000_000.0,
                      incentivized_tvl_usd=40_000_000.0)
        assert r["incentivized_share_pct"] == pytest.approx(40.0)

    def test_portfolio_parity(self):
        cfg = _cfg()
        protocols = [_protocol(name="A"), _protocol(name="B")]
        r_func = analyze_portfolio(protocols, config=cfg)
        r_class = ProtocolDeFiMercenaryCapitalRiskAnalyzer(
            config=cfg).analyze_portfolio(protocols)
        assert r_func["total_protocols"] == r_class["total_protocols"]
        assert r_func["most_mercenary_protocol"] == r_class["most_mercenary_protocol"]

    def test_config_forwarded_to_log(self):
        path = _tmp_log()
        a = ProtocolDeFiMercenaryCapitalRiskAnalyzer(config={"log_path": path})
        a.analyze(_protocol())
        assert os.path.exists(path)
        with open(path) as fh:
            data = json.load(fh)
        assert len(data) == 1
        os.unlink(path)

    def test_no_config_uses_default(self):
        a = ProtocolDeFiMercenaryCapitalRiskAnalyzer()
        r = a.analyze(_protocol())
        assert "classification" in r

    def test_multiple_calls_accumulate(self):
        path = _tmp_log()
        a = ProtocolDeFiMercenaryCapitalRiskAnalyzer(config={"log_path": path})
        a.analyze(_protocol(name="A"))
        a.analyze(_protocol(name="B"))
        with open(path) as fh:
            data = json.load(fh)
        assert len(data) == 2
        os.unlink(path)

    def test_class_portfolio_returns_summary(self):
        a = ProtocolDeFiMercenaryCapitalRiskAnalyzer(config=_cfg())
        s = a.analyze_portfolio([_protocol(name="X")])
        assert s["total_protocols"] == 1


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

    def test_no_emissions_coverage_large_finite(self):
        assert _NO_EMISSIONS_COVERAGE >= 100.0
        assert not math.isinf(_NO_EMISSIONS_COVERAGE)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
