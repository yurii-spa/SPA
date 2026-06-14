"""
Tests for MP-1045 DeFiProtocolReserveFactorEconomicsAnalyzer
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

from spa_core.analytics.defi_protocol_reserve_factor_economics_analyzer import (
    analyze,
    analyze_portfolio,
    _reserve_income_annual_usd,
    _supplier_apy_drag_pct,
    _reserve_to_borrows_pct,
    _bad_debt_coverage_ratio,
    _reserve_adequacy_score,
    _classify,
    _grade,
    _flags,
    _recommendations,
    _atomic_log,
    _safe_float,
    _clamp,
    DeFiProtocolReserveFactorEconomicsAnalyzer,
    ALL_CLASSIFICATIONS,
    ALL_FLAGS,
    CLASS_UNDERFUNDED,
    CLASS_THIN,
    CLASS_ADEQUATE,
    CLASS_WELL_CAPITALIZED,
    CLASS_OVERCAPITALIZED,
    FLAG_NO_RESERVE_FACTOR,
    FLAG_EXCESSIVE_RESERVE_FACTOR,
    FLAG_HIGH_SUPPLIER_DRAG,
    FLAG_THIN_RESERVES,
    FLAG_UNCOVERED_BAD_DEBT,
    FLAG_NO_BAD_DEBT,
    FLAG_STRONG_BUFFER,
    FLAG_OVERCAPITALIZED,
    FLAG_INSUFFICIENT_DATA,
    _NO_BAD_DEBT_COVERAGE,
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
    reserve_factor_pct=10.0,
    borrow_apr_pct=6.0,
    utilization_pct=80.0,
    total_borrows_usd=1_000_000_000.0,
    current_reserves_usd=70_000_000.0,
    bad_debt_usd=0.0,
    supply_apy_pct=4.3,
):
    return {
        "name": name,
        "reserve_factor_pct": reserve_factor_pct,
        "borrow_apr_pct": borrow_apr_pct,
        "utilization_pct": utilization_pct,
        "total_borrows_usd": total_borrows_usd,
        "current_reserves_usd": current_reserves_usd,
        "bad_debt_usd": bad_debt_usd,
        "supply_apy_pct": supply_apy_pct,
    }


def _cfg():
    return {"log_path": _tmp_log()}


# ===========================================================================
# 1. _reserve_income_annual_usd
# ===========================================================================

class TestReserveIncome:
    def test_basic_math(self):
        # 1e9 * 6% * 10% = 6,000,000
        r = _reserve_income_annual_usd(1_000_000_000.0, 6.0, 10.0)
        assert r == pytest.approx(6_000_000.0)

    def test_zero_borrows(self):
        assert _reserve_income_annual_usd(0.0, 6.0, 10.0) == pytest.approx(0.0)

    def test_zero_apr(self):
        assert _reserve_income_annual_usd(1e9, 0.0, 10.0) == pytest.approx(0.0)

    def test_zero_factor(self):
        assert _reserve_income_annual_usd(1e9, 6.0, 0.0) == pytest.approx(0.0)

    def test_full_factor(self):
        # 100% factor → all borrow interest goes to reserves
        r = _reserve_income_annual_usd(1e9, 5.0, 100.0)
        assert r == pytest.approx(50_000_000.0)

    def test_negative_borrows_clamped(self):
        assert _reserve_income_annual_usd(-1e9, 6.0, 10.0) == pytest.approx(0.0)

    def test_scales_linearly_with_borrows(self):
        r1 = _reserve_income_annual_usd(1e8, 6.0, 10.0)
        r2 = _reserve_income_annual_usd(2e8, 6.0, 10.0)
        assert r2 == pytest.approx(2 * r1)

    def test_no_zero_division(self):
        # should never raise
        _reserve_income_annual_usd(0.0, 0.0, 0.0)


# ===========================================================================
# 2. _supplier_apy_drag_pct
# ===========================================================================

class TestSupplierDrag:
    def test_basic_math(self):
        # 6 * 80% * 10% = 0.48
        d = _supplier_apy_drag_pct(6.0, 80.0, 10.0)
        assert d == pytest.approx(0.48)

    def test_zero_factor_no_drag(self):
        assert _supplier_apy_drag_pct(6.0, 80.0, 0.0) == pytest.approx(0.0)

    def test_zero_utilization_no_drag(self):
        assert _supplier_apy_drag_pct(6.0, 0.0, 10.0) == pytest.approx(0.0)

    def test_zero_apr_no_drag(self):
        assert _supplier_apy_drag_pct(0.0, 80.0, 10.0) == pytest.approx(0.0)

    def test_full_util_full_factor(self):
        # 6 * 100% * 100% = 6
        d = _supplier_apy_drag_pct(6.0, 100.0, 100.0)
        assert d == pytest.approx(6.0)

    def test_high_drag_scenario(self):
        d = _supplier_apy_drag_pct(25.0, 90.0, 35.0)
        assert d == pytest.approx(7.875)

    def test_scales_with_factor(self):
        d1 = _supplier_apy_drag_pct(6.0, 80.0, 10.0)
        d2 = _supplier_apy_drag_pct(6.0, 80.0, 20.0)
        assert d2 == pytest.approx(2 * d1)

    def test_no_zero_division(self):
        _supplier_apy_drag_pct(0.0, 0.0, 0.0)


# ===========================================================================
# 3. _reserve_to_borrows_pct
# ===========================================================================

class TestReserveToBorrows:
    def test_basic_math(self):
        # 70M / 1000M = 7%
        r = _reserve_to_borrows_pct(70_000_000.0, 1_000_000_000.0)
        assert r == pytest.approx(7.0)

    def test_zero_borrows_returns_zero(self):
        assert _reserve_to_borrows_pct(70_000_000.0, 0.0) == 0.0

    def test_negative_borrows_returns_zero(self):
        assert _reserve_to_borrows_pct(70_000_000.0, -5.0) == 0.0

    def test_zero_reserves(self):
        assert _reserve_to_borrows_pct(0.0, 1e9) == pytest.approx(0.0)

    def test_equal_reserves_and_borrows(self):
        assert _reserve_to_borrows_pct(1e9, 1e9) == pytest.approx(100.0)

    def test_reserves_exceed_borrows(self):
        assert _reserve_to_borrows_pct(2e9, 1e9) == pytest.approx(200.0)

    def test_no_zero_division(self):
        _reserve_to_borrows_pct(0.0, 0.0)


# ===========================================================================
# 4. _bad_debt_coverage_ratio
# ===========================================================================

class TestBadDebtCoverage:
    def test_basic_math(self):
        ratio, no_bad = _bad_debt_coverage_ratio(2_000_000.0, 1_000_000.0)
        assert ratio == pytest.approx(2.0)
        assert no_bad is False

    def test_no_bad_debt_sentinel(self):
        ratio, no_bad = _bad_debt_coverage_ratio(1_000_000.0, 0.0)
        assert ratio == _NO_BAD_DEBT_COVERAGE
        assert no_bad is True

    def test_negative_bad_debt_treated_as_none(self):
        ratio, no_bad = _bad_debt_coverage_ratio(1e6, -100.0)
        assert no_bad is True
        assert ratio == _NO_BAD_DEBT_COVERAGE

    def test_uncovered_bad_debt(self):
        ratio, no_bad = _bad_debt_coverage_ratio(500_000.0, 1_000_000.0)
        assert ratio == pytest.approx(0.5)
        assert no_bad is False

    def test_exactly_covered(self):
        ratio, no_bad = _bad_debt_coverage_ratio(1e6, 1e6)
        assert ratio == pytest.approx(1.0)
        assert no_bad is False

    def test_zero_reserves_with_bad_debt(self):
        ratio, no_bad = _bad_debt_coverage_ratio(0.0, 1e6)
        assert ratio == pytest.approx(0.0)
        assert no_bad is False

    def test_no_zero_division(self):
        _bad_debt_coverage_ratio(0.0, 0.0)

    def test_sentinel_is_large(self):
        assert _NO_BAD_DEBT_COVERAGE >= 100.0
        # avoid float('inf')
        import math
        assert not math.isinf(_NO_BAD_DEBT_COVERAGE)


# ===========================================================================
# 5. _reserve_adequacy_score
# ===========================================================================

class TestAdequacyScore:
    def test_no_data_zero(self):
        s = _reserve_adequacy_score(50.0, 999.0, True, has_data=False)
        assert s == 0.0

    def test_strong_buffer_no_bad_debt_high(self):
        # 25% buffer (saturates) + no bad debt = 60 + 40 = 100
        s = _reserve_adequacy_score(25.0, 999.0, True, has_data=True)
        assert s == pytest.approx(100.0)

    def test_zero_buffer_no_bad_debt(self):
        # 0 buffer + 40 coverage = 40
        s = _reserve_adequacy_score(0.0, 999.0, True, has_data=True)
        assert s == pytest.approx(40.0)

    def test_uncovered_bad_debt_heavily_penalised(self):
        good = _reserve_adequacy_score(10.0, 999.0, True, has_data=True)
        bad = _reserve_adequacy_score(10.0, 0.2, False, has_data=True)
        assert bad < good

    def test_covered_bad_debt_full_coverage_component(self):
        # coverage >= 1 → full 40 coverage component
        s = _reserve_adequacy_score(25.0, 1.5, False, has_data=True)
        assert s == pytest.approx(100.0)

    def test_bounded_0_100(self):
        for btb in [0.0, 1.0, 5.0, 25.0, 100.0, 500.0]:
            for cov, nbd in [(999.0, True), (0.5, False), (2.0, False)]:
                s = _reserve_adequacy_score(btb, cov, nbd, has_data=True)
                assert 0.0 <= s <= 100.0

    def test_more_buffer_higher_score(self):
        s1 = _reserve_adequacy_score(2.0, 999.0, True, has_data=True)
        s2 = _reserve_adequacy_score(10.0, 999.0, True, has_data=True)
        assert s2 > s1

    def test_uncovered_zero_coverage(self):
        s = _reserve_adequacy_score(10.0, 0.0, False, has_data=True)
        assert 0.0 <= s <= 100.0


# ===========================================================================
# 6. _classify
# ===========================================================================

class TestClassify:
    def test_no_data_underfunded(self):
        c = _classify(0.0, 0.0, True, 999.0, has_data=False)
        assert c == CLASS_UNDERFUNDED

    def test_uncovered_bad_debt_underfunded(self):
        c = _classify(80.0, 10.0, False, 0.5, has_data=True)
        assert c == CLASS_UNDERFUNDED

    def test_low_score_underfunded(self):
        c = _classify(10.0, 0.5, True, 999.0, has_data=True)
        assert c == CLASS_UNDERFUNDED

    def test_overcapitalized(self):
        c = _classify(100.0, 30.0, True, 999.0, has_data=True)
        assert c == CLASS_OVERCAPITALIZED

    def test_well_capitalized(self):
        c = _classify(80.0, 7.0, True, 999.0, has_data=True)
        assert c == CLASS_WELL_CAPITALIZED

    def test_thin(self):
        c = _classify(45.0, 0.5, True, 999.0, has_data=True)
        assert c == CLASS_THIN

    def test_adequate(self):
        c = _classify(60.0, 3.0, True, 999.0, has_data=True)
        assert c == CLASS_ADEQUATE

    def test_all_bands_reachable(self):
        seen = set()
        seen.add(_classify(0.0, 0.0, True, 999.0, has_data=False))
        seen.add(_classify(100.0, 30.0, True, 999.0, has_data=True))
        seen.add(_classify(80.0, 7.0, True, 999.0, has_data=True))
        seen.add(_classify(60.0, 3.0, True, 999.0, has_data=True))
        seen.add(_classify(45.0, 0.5, True, 999.0, has_data=True))
        assert seen == set(ALL_CLASSIFICATIONS)

    def test_returns_valid_classification(self):
        for score in [0, 25, 50, 75, 100]:
            for btb in [0.0, 0.5, 3.0, 7.0, 30.0]:
                c = _classify(score, btb, True, 999.0, has_data=True)
                assert c in ALL_CLASSIFICATIONS


# ===========================================================================
# 7. _grade
# ===========================================================================

class TestGrade:
    def test_a(self):
        assert _grade(95.0) == "A"
        assert _grade(90.0) == "A"

    def test_b(self):
        assert _grade(80.0) == "B"
        assert _grade(75.0) == "B"

    def test_c(self):
        assert _grade(65.0) == "C"
        assert _grade(60.0) == "C"

    def test_d(self):
        assert _grade(50.0) == "D"
        assert _grade(40.0) == "D"

    def test_f(self):
        assert _grade(30.0) == "F"
        assert _grade(0.0) == "F"

    def test_monotonic(self):
        order = "FFFFDDCCBBA"
        grades = [_grade(s) for s in range(0, 101, 10)]
        # higher scores are never worse grades
        rank = {"F": 0, "D": 1, "C": 2, "B": 3, "A": 4}
        for i in range(len(grades) - 1):
            assert rank[grades[i]] <= rank[grades[i + 1]]

    def test_all_grades_reachable(self):
        seen = {_grade(s) for s in [0, 45, 65, 80, 95]}
        assert seen == {"A", "B", "C", "D", "F"}


# ===========================================================================
# 8. _flags
# ===========================================================================

class TestFlags:
    def test_insufficient_data_only(self):
        f = _flags(10.0, 0.5, 5.0, 0.0, 999.0, True, has_data=False)
        assert f == [FLAG_INSUFFICIENT_DATA]

    def test_no_reserve_factor(self):
        f = _flags(0.0, 0.0, 5.0, 0.0, 999.0, True, has_data=True)
        assert FLAG_NO_RESERVE_FACTOR in f

    def test_excessive_reserve_factor(self):
        f = _flags(35.0, 0.5, 5.0, 0.0, 999.0, True, has_data=True)
        assert FLAG_EXCESSIVE_RESERVE_FACTOR in f

    def test_exactly_30_not_excessive(self):
        f = _flags(30.0, 0.5, 5.0, 0.0, 999.0, True, has_data=True)
        assert FLAG_EXCESSIVE_RESERVE_FACTOR not in f

    def test_high_supplier_drag(self):
        f = _flags(10.0, 2.0, 5.0, 0.0, 999.0, True, has_data=True)
        assert FLAG_HIGH_SUPPLIER_DRAG in f

    def test_low_drag_no_flag(self):
        f = _flags(10.0, 0.3, 5.0, 0.0, 999.0, True, has_data=True)
        assert FLAG_HIGH_SUPPLIER_DRAG not in f

    def test_thin_reserves(self):
        f = _flags(10.0, 0.5, 0.5, 0.0, 999.0, True, has_data=True)
        assert FLAG_THIN_RESERVES in f

    def test_strong_buffer(self):
        f = _flags(10.0, 0.5, 7.0, 0.0, 999.0, True, has_data=True)
        assert FLAG_STRONG_BUFFER in f

    def test_overcapitalized_flag(self):
        f = _flags(10.0, 0.5, 30.0, 0.0, 999.0, True, has_data=True)
        assert FLAG_OVERCAPITALIZED in f
        assert FLAG_STRONG_BUFFER in f

    def test_no_bad_debt_flag(self):
        f = _flags(10.0, 0.5, 5.0, 0.0, 999.0, True, has_data=True)
        assert FLAG_NO_BAD_DEBT in f

    def test_uncovered_bad_debt_flag(self):
        f = _flags(10.0, 0.5, 5.0, 1_000_000.0, 0.5, False, has_data=True)
        assert FLAG_UNCOVERED_BAD_DEBT in f
        assert FLAG_NO_BAD_DEBT not in f

    def test_covered_bad_debt_no_uncovered_flag(self):
        f = _flags(10.0, 0.5, 5.0, 1_000_000.0, 2.0, False, has_data=True)
        assert FLAG_UNCOVERED_BAD_DEBT not in f
        assert FLAG_NO_BAD_DEBT not in f

    def test_thin_and_strong_mutually_exclusive(self):
        f_thin = _flags(10.0, 0.5, 0.5, 0.0, 999.0, True, has_data=True)
        assert not (FLAG_THIN_RESERVES in f_thin and FLAG_STRONG_BUFFER in f_thin)

    def test_all_flags_valid(self):
        f = _flags(35.0, 5.0, 30.0, 1e6, 0.5, False, has_data=True)
        for flag in f:
            assert flag in ALL_FLAGS


# ===========================================================================
# 9. _recommendations
# ===========================================================================

class TestRecommendations:
    def test_insufficient_data(self):
        recs = _recommendations(
            CLASS_UNDERFUNDED, [FLAG_INSUFFICIENT_DATA], 10.0, 0.5, 0.0,
            999.0, True, 0.0, has_data=False,
        )
        assert len(recs) >= 1
        assert any("insufficient" in r.lower() for r in recs)

    def test_uncovered_bad_debt_critical(self):
        recs = _recommendations(
            CLASS_UNDERFUNDED, [FLAG_UNCOVERED_BAD_DEBT], 10.0, 0.5, 5.0,
            0.5, False, 100.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "critical" in combined

    def test_overcapitalized_suggests_lower_factor(self):
        recs = _recommendations(
            CLASS_OVERCAPITALIZED, [FLAG_OVERCAPITALIZED], 10.0, 0.5, 30.0,
            999.0, True, 100.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "lower" in combined or "overcapitalised" in combined

    def test_no_reserve_factor_mentioned(self):
        recs = _recommendations(
            CLASS_UNDERFUNDED, [FLAG_NO_RESERVE_FACTOR], 0.0, 0.0, 0.0,
            999.0, True, 0.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "0%" in combined or "reserve factor" in combined

    def test_high_drag_mentioned(self):
        recs = _recommendations(
            CLASS_ADEQUATE, [FLAG_HIGH_SUPPLIER_DRAG], 10.0, 3.0, 3.0,
            999.0, True, 100.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "drag" in combined

    def test_returns_list_for_each_class(self):
        for c in ALL_CLASSIFICATIONS:
            recs = _recommendations(
                c, [], 10.0, 0.5, 5.0, 999.0, True, 100.0, has_data=True,
            )
            assert isinstance(recs, list)
            assert len(recs) >= 1

    def test_income_mentioned(self):
        recs = _recommendations(
            CLASS_ADEQUATE, [], 10.0, 0.5, 3.0, 999.0, True, 6_000_000.0,
            has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "income" in combined

    def test_well_capitalized(self):
        recs = _recommendations(
            CLASS_WELL_CAPITALIZED, [FLAG_STRONG_BUFFER], 10.0, 0.5, 7.0,
            999.0, True, 100.0, has_data=True,
        )
        assert len(recs) >= 1

    def test_thin(self):
        recs = _recommendations(
            CLASS_THIN, [FLAG_THIN_RESERVES], 10.0, 0.5, 0.5,
            999.0, True, 100.0, has_data=True,
        )
        combined = " ".join(recs).lower()
        assert "thin" in combined or "build" in combined


# ===========================================================================
# 10. _atomic_log
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
# 11. _safe_float / _clamp
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
        assert _clamp(15.0, 0.0, 10.0) == 10.0


# ===========================================================================
# 12. analyze — integration
# ===========================================================================

class TestAnalyze:
    def test_returns_dict(self):
        r = analyze(_market(), config=_cfg())
        assert isinstance(r, dict)

    def test_required_keys(self):
        r = analyze(_market(), config=_cfg())
        for key in [
            "name",
            "reserve_income_annual_usd",
            "supplier_apy_drag_pct",
            "reserve_to_borrows_pct",
            "bad_debt_coverage_ratio",
            "reserve_adequacy_score",
            "classification",
            "grade",
            "flags",
            "recommendations",
            "timestamp",
        ]:
            assert key in r

    def test_reserve_income_math(self):
        r = analyze(_market(total_borrows_usd=1e9, borrow_apr_pct=6.0,
                            reserve_factor_pct=10.0), config=_cfg())
        assert r["reserve_income_annual_usd"] == pytest.approx(6_000_000.0)

    def test_supplier_drag_math(self):
        r = analyze(_market(borrow_apr_pct=6.0, utilization_pct=80.0,
                            reserve_factor_pct=10.0), config=_cfg())
        assert r["supplier_apy_drag_pct"] == pytest.approx(0.48)

    def test_reserve_to_borrows_math(self):
        r = analyze(_market(current_reserves_usd=70e6,
                            total_borrows_usd=1e9), config=_cfg())
        assert r["reserve_to_borrows_pct"] == pytest.approx(7.0)

    def test_bad_debt_coverage_math(self):
        r = analyze(_market(current_reserves_usd=2e6, bad_debt_usd=1e6),
                    config=_cfg())
        assert r["bad_debt_coverage_ratio"] == pytest.approx(2.0)
        assert r["no_bad_debt"] is False

    def test_no_bad_debt_sentinel(self):
        r = analyze(_market(bad_debt_usd=0.0), config=_cfg())
        assert r["bad_debt_coverage_ratio"] == _NO_BAD_DEBT_COVERAGE
        assert r["no_bad_debt"] is True
        assert FLAG_NO_BAD_DEBT in r["flags"]

    def test_classification_valid(self):
        r = analyze(_market(), config=_cfg())
        assert r["classification"] in ALL_CLASSIFICATIONS

    def test_grade_valid(self):
        r = analyze(_market(), config=_cfg())
        assert r["grade"] in {"A", "B", "C", "D", "F"}

    def test_well_capitalized_scenario(self):
        r = analyze(_market(current_reserves_usd=70e6, total_borrows_usd=1e9,
                            bad_debt_usd=0.0), config=_cfg())
        assert r["classification"] == CLASS_WELL_CAPITALIZED

    def test_underfunded_with_uncovered_bad_debt(self):
        r = analyze(_market(current_reserves_usd=200_000.0,
                            total_borrows_usd=50e6, bad_debt_usd=1e6),
                    config=_cfg())
        assert r["classification"] == CLASS_UNDERFUNDED
        assert FLAG_UNCOVERED_BAD_DEBT in r["flags"]

    def test_overcapitalized_scenario(self):
        r = analyze(_market(current_reserves_usd=500e6, total_borrows_usd=1e9,
                            bad_debt_usd=0.0), config=_cfg())
        assert r["classification"] == CLASS_OVERCAPITALIZED
        assert FLAG_OVERCAPITALIZED in r["flags"]

    def test_thin_reserves_scenario(self):
        r = analyze(_market(current_reserves_usd=2e6, total_borrows_usd=1e9,
                            bad_debt_usd=0.0), config=_cfg())
        assert FLAG_THIN_RESERVES in r["flags"]

    def test_no_reserve_factor_flag(self):
        r = analyze(_market(reserve_factor_pct=0.0), config=_cfg())
        assert FLAG_NO_RESERVE_FACTOR in r["flags"]
        assert r["reserve_income_annual_usd"] == pytest.approx(0.0)

    def test_excessive_reserve_factor_flag(self):
        r = analyze(_market(reserve_factor_pct=40.0), config=_cfg())
        assert FLAG_EXCESSIVE_RESERVE_FACTOR in r["flags"]

    def test_high_supplier_drag_flag(self):
        r = analyze(_market(borrow_apr_pct=25.0, utilization_pct=90.0,
                            reserve_factor_pct=35.0), config=_cfg())
        assert FLAG_HIGH_SUPPLIER_DRAG in r["flags"]

    def test_insufficient_data_flag(self):
        r = analyze(_market(total_borrows_usd=0.0), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]
        assert r["classification"] == CLASS_UNDERFUNDED

    def test_insufficient_data_negative_borrows(self):
        r = analyze(_market(total_borrows_usd=-100.0), config=_cfg())
        assert FLAG_INSUFFICIENT_DATA in r["flags"]

    def test_name_preserved(self):
        r = analyze(_market(name="USDC-Aave"), config=_cfg())
        assert r["name"] == "USDC-Aave"

    def test_recommendations_is_list(self):
        r = analyze(_market(), config=_cfg())
        assert isinstance(r["recommendations"], list)
        assert len(r["recommendations"]) >= 1

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_market(), config=_cfg())
        after = time.time()
        assert before <= r["timestamp"] <= after

    def test_flags_valid(self):
        r = analyze(_market(reserve_factor_pct=40.0, borrow_apr_pct=25.0,
                            utilization_pct=90.0, current_reserves_usd=100.0,
                            total_borrows_usd=1e9, bad_debt_usd=1e6),
                    config=_cfg())
        for flag in r["flags"]:
            assert flag in ALL_FLAGS

    def test_adequacy_score_bounded(self):
        r = analyze(_market(), config=_cfg())
        assert 0.0 <= r["reserve_adequacy_score"] <= 100.0

    def test_clamps_reserve_factor(self):
        r = analyze(_market(reserve_factor_pct=200.0), config=_cfg())
        assert r["reserve_factor_pct"] == 100.0

    def test_clamps_utilization(self):
        r = analyze(_market(utilization_pct=150.0), config=_cfg())
        assert r["utilization_pct"] == 100.0


# ===========================================================================
# 13. analyze — robustness / no crash
# ===========================================================================

class TestAnalyzeRobustness:
    def test_empty_dict(self):
        r = analyze({}, config=_cfg())
        assert "classification" in r
        assert FLAG_INSUFFICIENT_DATA in r["flags"]

    def test_missing_keys(self):
        r = analyze({"name": "X"}, config=_cfg())
        assert r["name"] == "X"
        assert "grade" in r

    def test_string_numeric_fields(self):
        r = analyze({"name": "X", "reserve_factor_pct": "10",
                     "borrow_apr_pct": "6", "utilization_pct": "80",
                     "total_borrows_usd": "1000000000",
                     "current_reserves_usd": "70000000"}, config=_cfg())
        assert r["reserve_income_annual_usd"] == pytest.approx(6_000_000.0)

    def test_garbage_numeric_fields(self):
        r = analyze({"name": "X", "reserve_factor_pct": "abc",
                     "borrow_apr_pct": None, "total_borrows_usd": "xyz"},
                    config=_cfg())
        assert "classification" in r

    def test_no_zero_division_all_zeros(self):
        r = analyze(_market(reserve_factor_pct=0.0, borrow_apr_pct=0.0,
                            utilization_pct=0.0, total_borrows_usd=0.0,
                            current_reserves_usd=0.0, bad_debt_usd=0.0),
                    config=_cfg())
        assert "classification" in r

    def test_zero_borrows_no_crash(self):
        r = analyze(_market(total_borrows_usd=0.0, current_reserves_usd=5e6),
                    config=_cfg())
        assert r["reserve_to_borrows_pct"] == 0.0

    def test_negative_reserves_clamped(self):
        r = analyze(_market(current_reserves_usd=-1e6), config=_cfg())
        assert r["current_reserves_usd"] == 0.0

    def test_negative_bad_debt_clamped(self):
        r = analyze(_market(bad_debt_usd=-5e6), config=_cfg())
        assert r["bad_debt_usd"] == 0.0
        assert r["no_bad_debt"] is True

    def test_does_not_raise_on_bad_log_path(self):
        # log path pointing into a file-as-dir; analyze must still return
        r = analyze(_market(), config={"log_path": "/dev/null/cannot/log.json"})
        assert "classification" in r

    def test_default_log_path_used(self):
        # no config → uses default path; should not raise
        r = analyze(_market())
        assert "classification" in r


# ===========================================================================
# 14. Logging via config
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
        path = str(tmp_path / "rf_log.json")
        for i in range(120):
            analyze(_market(name=f"M{i}"), config={"log_path": path})
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 100
        assert data[-1]["name"] == "M119"
        assert data[0]["name"] == "M20"

    def test_idempotent_rerun(self, tmp_path):
        path = str(tmp_path / "rf_log.json")
        m = _market(name="Same")
        r1 = analyze(m, config={"log_path": path})
        r2 = analyze(m, config={"log_path": path})
        # same inputs → same derived metrics (timestamp aside)
        assert r1["classification"] == r2["classification"]
        assert r1["reserve_adequacy_score"] == r2["reserve_adequacy_score"]
        assert r1["flags"] == r2["flags"]

    def test_log_via_tmp_path(self, tmp_path):
        path = str(tmp_path / "out.json")
        analyze(_market(), config={"log_path": path})
        assert os.path.exists(path)


# ===========================================================================
# 15. analyze_portfolio
# ===========================================================================

class TestAnalyzePortfolio:
    def test_empty_list(self):
        s = analyze_portfolio([], config=_cfg())
        assert s["total_markets"] == 0
        assert s["safest_market"] is None
        assert s["riskiest_market"] is None
        assert s["avg_reserve_adequacy_score"] == 0.0
        assert s["underfunded_count"] == 0
        assert s["results"] == []

    def test_single_market(self):
        s = analyze_portfolio([_market(name="Solo")], config=_cfg())
        assert s["total_markets"] == 1
        assert s["safest_market"] == "Solo"
        assert s["riskiest_market"] == "Solo"
        assert len(s["results"]) == 1

    def test_multiple_markets_picks_safest_and_riskiest(self):
        safe = _market(name="Safe", current_reserves_usd=70e6,
                       total_borrows_usd=1e9, bad_debt_usd=0.0)
        risky = _market(name="Risky", current_reserves_usd=100.0,
                        total_borrows_usd=50e6, bad_debt_usd=5e6)
        s = analyze_portfolio([safe, risky], config=_cfg())
        assert s["total_markets"] == 2
        assert s["safest_market"] == "Safe"
        assert s["riskiest_market"] == "Risky"

    def test_avg_score(self):
        markets = [
            _market(name="A", current_reserves_usd=70e6, total_borrows_usd=1e9),
            _market(name="B", current_reserves_usd=70e6, total_borrows_usd=1e9),
        ]
        s = analyze_portfolio(markets, config=_cfg())
        avg = s["avg_reserve_adequacy_score"]
        per = [r["reserve_adequacy_score"] for r in s["results"]]
        assert avg == pytest.approx(sum(per) / len(per))

    def test_underfunded_count(self):
        markets = [
            _market(name="Good", current_reserves_usd=70e6, total_borrows_usd=1e9),
            _market(name="Bad1", current_reserves_usd=10.0,
                    total_borrows_usd=50e6, bad_debt_usd=5e6),
            _market(name="Bad2", total_borrows_usd=0.0),
        ]
        s = analyze_portfolio(markets, config=_cfg())
        assert s["underfunded_count"] == 2

    def test_results_count_matches(self):
        markets = [_market(name=f"M{i}") for i in range(5)]
        s = analyze_portfolio(markets, config=_cfg())
        assert len(s["results"]) == 5
        assert s["total_markets"] == 5

    def test_non_list_input(self):
        s = analyze_portfolio("notalist", config=_cfg())
        assert s["total_markets"] == 0

    def test_handles_non_dict_entries(self):
        s = analyze_portfolio([_market(name="ok"), "garbage", 42], config=_cfg())
        assert s["total_markets"] == 3

    def test_all_results_have_classification(self):
        markets = [_market(name=f"M{i}") for i in range(3)]
        s = analyze_portfolio(markets, config=_cfg())
        for r in s["results"]:
            assert r["classification"] in ALL_CLASSIFICATIONS


# ===========================================================================
# 16. Class wrapper parity
# ===========================================================================

class TestClassWrapper:
    def test_instantiation(self):
        a = DeFiProtocolReserveFactorEconomicsAnalyzer()
        assert a is not None

    def test_analyze_returns_dict(self):
        a = DeFiProtocolReserveFactorEconomicsAnalyzer(config=_cfg())
        r = a.analyze(_market())
        assert isinstance(r, dict)

    def test_analyze_parity_with_function(self):
        cfg = _cfg()
        m = _market(name="Parity")
        r_func = analyze(m, config=cfg)
        r_class = DeFiProtocolReserveFactorEconomicsAnalyzer(config=cfg).analyze(m)
        assert r_func["classification"] == r_class["classification"]
        assert r_func["reserve_adequacy_score"] == r_class["reserve_adequacy_score"]
        assert r_func["flags"] == r_class["flags"]

    def test_portfolio_parity(self):
        cfg = _cfg()
        markets = [_market(name="A"), _market(name="B")]
        r_func = analyze_portfolio(markets, config=cfg)
        r_class = DeFiProtocolReserveFactorEconomicsAnalyzer(
            config=cfg).analyze_portfolio(markets)
        assert r_func["total_markets"] == r_class["total_markets"]
        assert r_func["safest_market"] == r_class["safest_market"]

    def test_config_forwarded_to_log(self):
        path = _tmp_log()
        a = DeFiProtocolReserveFactorEconomicsAnalyzer(config={"log_path": path})
        a.analyze(_market())
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 1
        os.unlink(path)

    def test_no_config_uses_default(self):
        a = DeFiProtocolReserveFactorEconomicsAnalyzer()
        r = a.analyze(_market())
        assert "classification" in r

    def test_multiple_calls_accumulate(self):
        path = _tmp_log()
        a = DeFiProtocolReserveFactorEconomicsAnalyzer(config={"log_path": path})
        a.analyze(_market(name="A"))
        a.analyze(_market(name="B"))
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 2
        os.unlink(path)

    def test_class_portfolio_returns_summary(self):
        a = DeFiProtocolReserveFactorEconomicsAnalyzer(config=_cfg())
        s = a.analyze_portfolio([_market(name="X")])
        assert s["total_markets"] == 1


# ===========================================================================
# 17. Constants sanity
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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
