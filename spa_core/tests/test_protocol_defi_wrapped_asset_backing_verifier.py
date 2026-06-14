"""
Tests for MP-1044 ProtocolDeFiWrappedAssetBackingVerifier
Comprehensive unittest suite — pure stdlib, no third-party dependencies.
"""

import json
import os
import sys
import tempfile
import time
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_defi_wrapped_asset_backing_verifier import (
    analyze,
    analyze_portfolio,
    _atomic_log,
    _clamp,
    _safe_float,
    _safe_int,
    _backing_ratio_pct,
    _collateral_shortfall_pct,
    _custodian_concentration_score,
    _attestation_freshness_score,
    _backing_risk_score,
    _classification,
    _grade,
    _flags,
    _recommendations,
    ProtocolDeFiWrappedAssetBackingVerifier,
    ALL_CLASSIFICATIONS,
    ALL_GRADES,
    CLASS_FULLY_BACKED,
    CLASS_WELL_BACKED,
    CLASS_PARTIALLY_BACKED,
    CLASS_UNDERBACKED,
    CLASS_CRITICAL_SHORTFALL,
    FLAG_UNDERBACKED,
    FLAG_OVERCOLLATERALIZED,
    FLAG_SINGLE_CUSTODIAN,
    FLAG_HIGH_CUSTODIAN_CONCENTRATION,
    FLAG_STALE_ATTESTATION,
    FLAG_NO_REDEMPTION,
    FLAG_REDEMPTION_FEE,
    FLAG_UNAUDITED,
    FLAG_FULLY_BACKED,
    FLAG_INSUFFICIENT_DATA,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _cfg() -> dict:
    return {"log_path": _tmp_log()}


def _asset(**kwargs) -> dict:
    base = {
        "name": "Wrapped BTC",
        "symbol": "wBTC",
        "wrapped_supply": 1000.0,
        "reserve_balance": 1000.0,
        "custodian_count": 3,
        "largest_custodian_share_pct": 40.0,
        "attestation_age_days": 5.0,
        "can_redeem": True,
        "redemption_fee_pct": 0.0,
        "is_audited": True,
    }
    base.update(kwargs)
    return base


# ===========================================================================
# 1. _clamp / _safe_float / _safe_int
# ===========================================================================

class TestHelpers(unittest.TestCase):
    def test_clamp_within(self):
        self.assertEqual(_clamp(50.0), 50.0)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-5.0), 0.0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(150.0), 100.0)

    def test_clamp_custom_range(self):
        self.assertEqual(_clamp(5.0, 1.0, 3.0), 3.0)

    def test_safe_float_valid(self):
        self.assertEqual(_safe_float("12.5"), 12.5)

    def test_safe_float_invalid(self):
        self.assertEqual(_safe_float("abc"), 0.0)

    def test_safe_float_none(self):
        self.assertEqual(_safe_float(None), 0.0)

    def test_safe_float_default(self):
        self.assertEqual(_safe_float(None, 9.0), 9.0)

    def test_safe_int_valid(self):
        self.assertEqual(_safe_int("7"), 7)

    def test_safe_int_invalid(self):
        self.assertEqual(_safe_int("x"), 0)

    def test_safe_int_none(self):
        self.assertEqual(_safe_int(None), 0)


# ===========================================================================
# 2. _backing_ratio_pct
# ===========================================================================

class TestBackingRatio(unittest.TestCase):
    def test_exact_one_to_one(self):
        self.assertAlmostEqual(_backing_ratio_pct(1000.0, 1000.0), 100.0)

    def test_underbacked(self):
        self.assertAlmostEqual(_backing_ratio_pct(1000.0, 800.0), 80.0)

    def test_overcollateralized(self):
        self.assertAlmostEqual(_backing_ratio_pct(1000.0, 1200.0), 120.0)

    def test_zero_supply_returns_zero(self):
        self.assertEqual(_backing_ratio_pct(0.0, 500.0), 0.0)

    def test_negative_supply_returns_zero(self):
        self.assertEqual(_backing_ratio_pct(-10.0, 500.0), 0.0)

    def test_zero_reserve(self):
        self.assertAlmostEqual(_backing_ratio_pct(1000.0, 0.0), 0.0)

    def test_no_zero_division(self):
        # Must not raise
        try:
            _backing_ratio_pct(0.0, 0.0)
        except ZeroDivisionError:
            self.fail("ZeroDivisionError raised")

    def test_half_backed(self):
        self.assertAlmostEqual(_backing_ratio_pct(2000.0, 1000.0), 50.0)


# ===========================================================================
# 3. _collateral_shortfall_pct
# ===========================================================================

class TestShortfall(unittest.TestCase):
    def test_full_backing_no_shortfall(self):
        self.assertAlmostEqual(_collateral_shortfall_pct(100.0), 0.0)

    def test_underbacked_shortfall(self):
        self.assertAlmostEqual(_collateral_shortfall_pct(80.0), 20.0)

    def test_over_clamped_to_zero(self):
        self.assertAlmostEqual(_collateral_shortfall_pct(120.0), 0.0)

    def test_zero_backing_full_shortfall(self):
        self.assertAlmostEqual(_collateral_shortfall_pct(0.0), 100.0)

    def test_never_negative(self):
        for ratio in [0, 50, 100, 150, 200]:
            self.assertGreaterEqual(_collateral_shortfall_pct(ratio), 0.0)


# ===========================================================================
# 4. _custodian_concentration_score
# ===========================================================================

class TestCustodianConcentration(unittest.TestCase):
    def test_single_custodian_near_100(self):
        s = _custodian_concentration_score(1, 100.0)
        self.assertGreaterEqual(s, 95.0)

    def test_zero_custodians_high(self):
        s = _custodian_concentration_score(0, 0.0)
        self.assertGreaterEqual(s, 40.0)

    def test_many_custodians_low(self):
        s = _custodian_concentration_score(50, 5.0)
        self.assertLess(s, 20.0)

    def test_in_range(self):
        for cnt in range(0, 12):
            for share in [0, 25, 50, 75, 100]:
                s = _custodian_concentration_score(cnt, share)
                self.assertGreaterEqual(s, 0.0)
                self.assertLessEqual(s, 100.0)

    def test_more_custodians_lowers_score(self):
        s1 = _custodian_concentration_score(1, 50.0)
        s5 = _custodian_concentration_score(5, 50.0)
        self.assertGreater(s1, s5)

    def test_higher_share_raises_score(self):
        low = _custodian_concentration_score(5, 20.0)
        high = _custodian_concentration_score(5, 90.0)
        self.assertGreater(high, low)

    def test_negative_share_clamped(self):
        s = _custodian_concentration_score(3, -50.0)
        self.assertGreaterEqual(s, 0.0)

    def test_share_above_100_clamped(self):
        s = _custodian_concentration_score(3, 200.0)
        self.assertLessEqual(s, 100.0)


# ===========================================================================
# 5. _attestation_freshness_score
# ===========================================================================

class TestAttestationFreshness(unittest.TestCase):
    def test_zero_days_is_100(self):
        self.assertAlmostEqual(_attestation_freshness_score(0.0), 100.0)

    def test_90_days_is_zero(self):
        self.assertAlmostEqual(_attestation_freshness_score(90.0), 0.0)

    def test_above_90_is_zero(self):
        self.assertAlmostEqual(_attestation_freshness_score(365.0), 0.0)

    def test_30_days_around_67(self):
        s = _attestation_freshness_score(30.0)
        self.assertTrue(60.0 <= s <= 70.0)

    def test_45_days_is_50(self):
        self.assertAlmostEqual(_attestation_freshness_score(45.0), 50.0, places=4)

    def test_negative_treated_as_fresh(self):
        self.assertAlmostEqual(_attestation_freshness_score(-10.0), 100.0)

    def test_in_range(self):
        for age in [0, 1, 15, 30, 60, 89, 90, 200]:
            s = _attestation_freshness_score(age)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_monotonic_decreasing(self):
        ages = [0, 10, 20, 30, 50, 70, 89]
        scores = [_attestation_freshness_score(a) for a in ages]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])


# ===========================================================================
# 6. _backing_risk_score
# ===========================================================================

class TestBackingRiskScore(unittest.TestCase):
    def test_best_case_low(self):
        s = _backing_risk_score(0.0, 0.0, 100.0, True, True)
        self.assertLess(s, 10.0)

    def test_shortfall_dominant(self):
        s = _backing_risk_score(50.0, 0.0, 100.0, True, True)
        self.assertGreaterEqual(s, 45.0)

    def test_no_redemption_adds_risk(self):
        base = _backing_risk_score(0.0, 0.0, 100.0, True, True)
        no_redeem = _backing_risk_score(0.0, 0.0, 100.0, False, True)
        self.assertGreater(no_redeem, base)

    def test_unaudited_adds_risk(self):
        base = _backing_risk_score(0.0, 0.0, 100.0, True, True)
        unaud = _backing_risk_score(0.0, 0.0, 100.0, True, False)
        self.assertGreater(unaud, base)

    def test_concentration_adds_risk(self):
        base = _backing_risk_score(0.0, 0.0, 100.0, True, True)
        conc = _backing_risk_score(0.0, 100.0, 100.0, True, True)
        self.assertGreater(conc, base)

    def test_stale_adds_risk(self):
        base = _backing_risk_score(0.0, 0.0, 100.0, True, True)
        stale = _backing_risk_score(0.0, 0.0, 0.0, True, True)
        self.assertGreater(stale, base)

    def test_clamped_0_to_100(self):
        s = _backing_risk_score(100.0, 100.0, 0.0, False, False)
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_worst_case_high(self):
        s = _backing_risk_score(100.0, 100.0, 0.0, False, False)
        self.assertGreaterEqual(s, 90.0)


# ===========================================================================
# 7. _classification
# ===========================================================================

class TestClassification(unittest.TestCase):
    def test_fully_backed(self):
        self.assertEqual(_classification(100.0, 0.0, True), CLASS_FULLY_BACKED)

    def test_overcollateralized_is_fully_backed(self):
        self.assertEqual(_classification(150.0, 0.0, True), CLASS_FULLY_BACKED)

    def test_well_backed(self):
        self.assertEqual(_classification(99.5, 0.0, True), CLASS_WELL_BACKED)

    def test_partially_backed(self):
        self.assertEqual(_classification(95.0, 0.0, True), CLASS_PARTIALLY_BACKED)

    def test_underbacked(self):
        self.assertEqual(_classification(80.0, 0.0, True), CLASS_UNDERBACKED)

    def test_critical_shortfall(self):
        self.assertEqual(_classification(50.0, 0.0, True), CLASS_CRITICAL_SHORTFALL)

    def test_no_data_is_critical(self):
        self.assertEqual(_classification(0.0, 0.0, False), CLASS_CRITICAL_SHORTFALL)

    def test_high_risk_downgrades(self):
        # 100% ratio but risk >= 60 → downgrade from FULLY_BACKED
        c = _classification(100.0, 75.0, True)
        self.assertEqual(c, CLASS_WELL_BACKED)

    def test_high_risk_does_not_break_lowest(self):
        c = _classification(50.0, 90.0, True)
        self.assertEqual(c, CLASS_CRITICAL_SHORTFALL)

    def test_all_returns_valid(self):
        for ratio in [0, 50, 80, 95, 99.5, 100, 150]:
            for risk in [0, 65]:
                c = _classification(ratio, risk, True)
                self.assertIn(c, ALL_CLASSIFICATIONS)

    def test_boundary_99(self):
        self.assertEqual(_classification(99.0, 0.0, True), CLASS_WELL_BACKED)

    def test_boundary_90(self):
        self.assertEqual(_classification(90.0, 0.0, True), CLASS_PARTIALLY_BACKED)

    def test_boundary_75(self):
        self.assertEqual(_classification(75.0, 0.0, True), CLASS_UNDERBACKED)

    def test_just_below_75(self):
        self.assertEqual(_classification(74.9, 0.0, True), CLASS_CRITICAL_SHORTFALL)


# ===========================================================================
# 8. _grade
# ===========================================================================

class TestGrade(unittest.TestCase):
    def test_grade_a(self):
        self.assertEqual(_grade(5.0), "A")

    def test_grade_b(self):
        self.assertEqual(_grade(20.0), "B")

    def test_grade_c(self):
        self.assertEqual(_grade(35.0), "C")

    def test_grade_d(self):
        self.assertEqual(_grade(60.0), "D")

    def test_grade_f(self):
        self.assertEqual(_grade(90.0), "F")

    def test_grade_in_all_grades(self):
        for s in range(0, 101, 5):
            self.assertIn(_grade(float(s)), ALL_GRADES)

    def test_grade_monotonic(self):
        order = "ABCDF"
        prev = 0
        for s in [5, 20, 35, 60, 90]:
            g = _grade(float(s))
            self.assertGreaterEqual(order.index(g), prev)
            prev = order.index(g)

    def test_boundary_10(self):
        self.assertEqual(_grade(10.0), "B")

    def test_boundary_70(self):
        self.assertEqual(_grade(70.0), "F")


# ===========================================================================
# 9. _flags
# ===========================================================================

class TestFlags(unittest.TestCase):
    def test_insufficient_data_only(self):
        f = _flags(0.0, 0, 0.0, 0.0, True, 0.0, True, False)
        self.assertEqual(f, [FLAG_INSUFFICIENT_DATA])

    def test_fully_backed_flag(self):
        f = _flags(100.0, 3, 40.0, 100.0, True, 0.0, True, True)
        self.assertIn(FLAG_FULLY_BACKED, f)

    def test_underbacked_flag(self):
        f = _flags(80.0, 3, 40.0, 100.0, True, 0.0, True, True)
        self.assertIn(FLAG_UNDERBACKED, f)

    def test_overcollateralized_flag(self):
        f = _flags(120.0, 3, 40.0, 100.0, True, 0.0, True, True)
        self.assertIn(FLAG_OVERCOLLATERALIZED, f)

    def test_no_overcollat_at_exactly_105(self):
        f = _flags(105.0, 3, 40.0, 100.0, True, 0.0, True, True)
        self.assertNotIn(FLAG_OVERCOLLATERALIZED, f)

    def test_single_custodian_flag(self):
        f = _flags(100.0, 1, 100.0, 100.0, True, 0.0, True, True)
        self.assertIn(FLAG_SINGLE_CUSTODIAN, f)

    def test_high_concentration_flag(self):
        f = _flags(100.0, 2, 80.0, 100.0, True, 0.0, True, True)
        self.assertIn(FLAG_HIGH_CUSTODIAN_CONCENTRATION, f)

    def test_stale_attestation_flag(self):
        f = _flags(100.0, 3, 40.0, 20.0, True, 0.0, True, True)
        self.assertIn(FLAG_STALE_ATTESTATION, f)

    def test_no_redemption_flag(self):
        f = _flags(100.0, 3, 40.0, 100.0, False, 0.0, True, True)
        self.assertIn(FLAG_NO_REDEMPTION, f)

    def test_redemption_fee_flag(self):
        f = _flags(100.0, 3, 40.0, 100.0, True, 0.5, True, True)
        self.assertIn(FLAG_REDEMPTION_FEE, f)

    def test_no_redemption_fee_at_zero(self):
        f = _flags(100.0, 3, 40.0, 100.0, True, 0.0, True, True)
        self.assertNotIn(FLAG_REDEMPTION_FEE, f)

    def test_unaudited_flag(self):
        f = _flags(100.0, 3, 40.0, 100.0, True, 0.0, False, True)
        self.assertIn(FLAG_UNAUDITED, f)

    def test_audited_no_flag(self):
        f = _flags(100.0, 3, 40.0, 100.0, True, 0.0, True, True)
        self.assertNotIn(FLAG_UNAUDITED, f)

    def test_returns_list(self):
        f = _flags(100.0, 3, 40.0, 100.0, True, 0.0, True, True)
        self.assertIsInstance(f, list)

    def test_clean_asset_has_fully_backed(self):
        f = _flags(100.0, 5, 25.0, 100.0, True, 0.0, True, True)
        self.assertIn(FLAG_FULLY_BACKED, f)
        self.assertNotIn(FLAG_UNDERBACKED, f)


# ===========================================================================
# 10. _recommendations
# ===========================================================================

class TestRecommendations(unittest.TestCase):
    def test_insufficient_data(self):
        recs = _recommendations(CLASS_CRITICAL_SHORTFALL, [FLAG_INSUFFICIENT_DATA],
                                0.0, 0.0, 0.0, 0.0, False)
        self.assertGreater(len(recs), 0)
        self.assertIn("insufficient", " ".join(recs).lower())

    def test_critical(self):
        recs = _recommendations(CLASS_CRITICAL_SHORTFALL, [FLAG_UNDERBACKED],
                                50.0, 50.0, 0.0, 100.0, True)
        self.assertIn("critical", " ".join(recs).lower())

    def test_underbacked(self):
        recs = _recommendations(CLASS_UNDERBACKED, [FLAG_UNDERBACKED],
                                80.0, 20.0, 0.0, 100.0, True)
        self.assertGreater(len(recs), 0)

    def test_partially_backed(self):
        recs = _recommendations(CLASS_PARTIALLY_BACKED, [FLAG_UNDERBACKED],
                                95.0, 5.0, 0.0, 100.0, True)
        self.assertGreater(len(recs), 0)

    def test_well_backed(self):
        recs = _recommendations(CLASS_WELL_BACKED, [FLAG_FULLY_BACKED],
                                99.5, 0.0, 0.0, 100.0, True)
        self.assertGreater(len(recs), 0)

    def test_fully_backed(self):
        recs = _recommendations(CLASS_FULLY_BACKED, [FLAG_FULLY_BACKED],
                                100.0, 0.0, 0.0, 100.0, True)
        self.assertGreater(len(recs), 0)

    def test_single_custodian_mentioned(self):
        recs = _recommendations(CLASS_FULLY_BACKED, [FLAG_FULLY_BACKED, FLAG_SINGLE_CUSTODIAN],
                                100.0, 0.0, 100.0, 100.0, True)
        self.assertIn("custodian", " ".join(recs).lower())

    def test_high_concentration_mentioned(self):
        recs = _recommendations(CLASS_FULLY_BACKED, [FLAG_FULLY_BACKED, FLAG_HIGH_CUSTODIAN_CONCENTRATION],
                                100.0, 0.0, 80.0, 100.0, True)
        self.assertIn("concentration", " ".join(recs).lower())

    def test_stale_mentioned(self):
        recs = _recommendations(CLASS_FULLY_BACKED, [FLAG_FULLY_BACKED, FLAG_STALE_ATTESTATION],
                                100.0, 0.0, 0.0, 20.0, True)
        self.assertIn("attestation", " ".join(recs).lower())

    def test_no_redemption_mentioned(self):
        recs = _recommendations(CLASS_FULLY_BACKED, [FLAG_FULLY_BACKED, FLAG_NO_REDEMPTION],
                                100.0, 0.0, 0.0, 100.0, True)
        self.assertIn("redemption", " ".join(recs).lower())

    def test_redemption_fee_mentioned(self):
        recs = _recommendations(CLASS_FULLY_BACKED, [FLAG_FULLY_BACKED, FLAG_REDEMPTION_FEE],
                                100.0, 0.0, 0.0, 100.0, True)
        self.assertIn("fee", " ".join(recs).lower())

    def test_unaudited_mentioned(self):
        recs = _recommendations(CLASS_FULLY_BACKED, [FLAG_FULLY_BACKED, FLAG_UNAUDITED],
                                100.0, 0.0, 0.0, 100.0, True)
        self.assertIn("audit", " ".join(recs).lower())

    def test_returns_list_always(self):
        for c in ALL_CLASSIFICATIONS:
            recs = _recommendations(c, [], 90.0, 10.0, 0.0, 100.0, True)
            self.assertIsInstance(recs, list)


# ===========================================================================
# 11. _atomic_log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):
    def test_creates_file(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 42})
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["x"], 42)
        os.unlink(path)

    def test_appends_multiple(self):
        path = _tmp_log()
        _atomic_log(path, {"n": 1})
        _atomic_log(path, {"n": 2})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(path)

    def test_ring_buffer_caps_100(self):
        path = _tmp_log()
        for i in range(150):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)
        self.assertEqual(data[-1]["i"], 149)
        os.unlink(path)

    def test_oldest_dropped(self):
        path = _tmp_log()
        for i in range(105):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["i"], 5)
        os.unlink(path)

    def test_recovers_from_corrupt(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("{NOT JSON")
        _atomic_log(path, {"ok": True})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_creates_parent_dirs(self):
        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "a", "b", "log.json")
        _atomic_log(path, {"deep": True})
        self.assertTrue(os.path.exists(path))


# ===========================================================================
# 12. analyze — integration
# ===========================================================================

class TestAnalyze(unittest.TestCase):
    def test_returns_dict(self):
        r = analyze(_asset(), config=_cfg())
        self.assertIsInstance(r, dict)

    def test_required_keys(self):
        r = analyze(_asset(), config=_cfg())
        for key in [
            "name", "symbol", "backing_ratio_pct", "collateral_shortfall_pct",
            "custodian_concentration_score", "attestation_freshness_score",
            "backing_risk_score", "classification", "grade", "flags",
            "recommendations", "timestamp",
        ]:
            self.assertIn(key, r)

    def test_classification_valid(self):
        r = analyze(_asset(), config=_cfg())
        self.assertIn(r["classification"], ALL_CLASSIFICATIONS)

    def test_grade_valid(self):
        r = analyze(_asset(), config=_cfg())
        self.assertIn(r["grade"], ALL_GRADES)

    def test_exact_one_to_one(self):
        r = analyze(_asset(wrapped_supply=1000, reserve_balance=1000), config=_cfg())
        self.assertAlmostEqual(r["backing_ratio_pct"], 100.0)
        self.assertEqual(r["classification"], CLASS_FULLY_BACKED)

    def test_underbacked_asset(self):
        r = analyze(_asset(wrapped_supply=1000, reserve_balance=800), config=_cfg())
        self.assertAlmostEqual(r["backing_ratio_pct"], 80.0)
        self.assertIn(FLAG_UNDERBACKED, r["flags"])

    def test_overcollateralized_asset(self):
        r = analyze(_asset(wrapped_supply=1000, reserve_balance=1200), config=_cfg())
        self.assertIn(FLAG_OVERCOLLATERALIZED, r["flags"])

    def test_critical_shortfall(self):
        r = analyze(_asset(wrapped_supply=1000, reserve_balance=400), config=_cfg())
        self.assertEqual(r["classification"], CLASS_CRITICAL_SHORTFALL)

    def test_insufficient_data_zero_supply(self):
        r = analyze(_asset(wrapped_supply=0, reserve_balance=500), config=_cfg())
        self.assertIn(FLAG_INSUFFICIENT_DATA, r["flags"])
        self.assertEqual(r["classification"], CLASS_CRITICAL_SHORTFALL)

    def test_insufficient_data_negative_reserve(self):
        r = analyze(_asset(wrapped_supply=1000, reserve_balance=-5), config=_cfg())
        self.assertIn(FLAG_INSUFFICIENT_DATA, r["flags"])

    def test_single_custodian_flag(self):
        r = analyze(_asset(custodian_count=1, largest_custodian_share_pct=100.0), config=_cfg())
        self.assertIn(FLAG_SINGLE_CUSTODIAN, r["flags"])

    def test_stale_attestation_flag(self):
        r = analyze(_asset(attestation_age_days=120.0), config=_cfg())
        self.assertIn(FLAG_STALE_ATTESTATION, r["flags"])

    def test_no_redemption_flag(self):
        r = analyze(_asset(can_redeem=False), config=_cfg())
        self.assertIn(FLAG_NO_REDEMPTION, r["flags"])

    def test_redemption_fee_flag(self):
        r = analyze(_asset(redemption_fee_pct=0.25), config=_cfg())
        self.assertIn(FLAG_REDEMPTION_FEE, r["flags"])

    def test_unaudited_flag(self):
        r = analyze(_asset(is_audited=False), config=_cfg())
        self.assertIn(FLAG_UNAUDITED, r["flags"])

    def test_no_zero_division_zero_supply(self):
        try:
            analyze(_asset(wrapped_supply=0, reserve_balance=0), config=_cfg())
        except ZeroDivisionError:
            self.fail("ZeroDivisionError raised")

    def test_missing_keys_handled(self):
        r = analyze({}, config=_cfg())
        self.assertIn("classification", r)

    def test_not_a_dict_input(self):
        r = analyze("not a dict", config=_cfg())
        self.assertIn("classification", r)

    def test_none_input(self):
        r = analyze(None, config=_cfg())
        self.assertIn("classification", r)

    def test_malformed_string_numbers(self):
        r = analyze({"wrapped_supply": "abc", "reserve_balance": "xyz"}, config=_cfg())
        self.assertIn(FLAG_INSUFFICIENT_DATA, r["flags"])

    def test_string_numbers_parsed(self):
        r = analyze({"wrapped_supply": "1000", "reserve_balance": "1000"}, config=_cfg())
        self.assertAlmostEqual(r["backing_ratio_pct"], 100.0)

    def test_name_preserved(self):
        r = analyze(_asset(name="Bridged USDC"), config=_cfg())
        self.assertEqual(r["name"], "Bridged USDC")

    def test_symbol_fallback_to_name(self):
        r = analyze({"name": "Foo", "wrapped_supply": 10, "reserve_balance": 10}, config=_cfg())
        self.assertEqual(r["symbol"], "Foo")

    def test_can_redeem_defaults_true(self):
        r = analyze({"wrapped_supply": 10, "reserve_balance": 10}, config=_cfg())
        self.assertTrue(r["can_redeem"])
        self.assertNotIn(FLAG_NO_REDEMPTION, r["flags"])

    def test_is_audited_defaults_false(self):
        r = analyze({"wrapped_supply": 10, "reserve_balance": 10}, config=_cfg())
        self.assertFalse(r["is_audited"])

    def test_timestamp_recent(self):
        before = time.time()
        r = analyze(_asset(), config=_cfg())
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_recommendations_is_list(self):
        r = analyze(_asset(), config=_cfg())
        self.assertIsInstance(r["recommendations"], list)
        self.assertGreater(len(r["recommendations"]), 0)

    def test_negative_custodian_count_handled(self):
        r = analyze(_asset(custodian_count=-3), config=_cfg())
        self.assertEqual(r["custodian_count"], 0)

    def test_writes_log(self):
        path = _tmp_log()
        analyze(_asset(), config={"log_path": path})
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_clean_asset_fully_backed_grade_a(self):
        r = analyze(_asset(custodian_count=10, largest_custodian_share_pct=15.0,
                           attestation_age_days=1.0, is_audited=True), config=_cfg())
        self.assertEqual(r["classification"], CLASS_FULLY_BACKED)
        self.assertEqual(r["grade"], "A")


# ===========================================================================
# 13. analyze_portfolio
# ===========================================================================

class TestAnalyzePortfolio(unittest.TestCase):
    def test_empty_list(self):
        r = analyze_portfolio([], config=_cfg())
        self.assertEqual(r["total_assets"], 0)
        self.assertIsNone(r["safest_asset"])
        self.assertIsNone(r["riskiest_asset"])
        self.assertEqual(r["results"], [])

    def test_single_asset(self):
        r = analyze_portfolio([_asset()], config=_cfg())
        self.assertEqual(r["total_assets"], 1)
        self.assertIsNotNone(r["safest_asset"])

    def test_multiple_assets(self):
        assets = [
            _asset(wrapped_supply=1000, reserve_balance=1000),
            _asset(wrapped_supply=1000, reserve_balance=600),
            _asset(wrapped_supply=1000, reserve_balance=400),
        ]
        r = analyze_portfolio(assets, config=_cfg())
        self.assertEqual(r["total_assets"], 3)

    def test_identifies_safest(self):
        safe = _asset(symbol="SAFE", wrapped_supply=1000, reserve_balance=1100,
                      custodian_count=10, largest_custodian_share_pct=15.0,
                      attestation_age_days=1.0, is_audited=True)
        risky = _asset(symbol="RISKY", wrapped_supply=1000, reserve_balance=400,
                       custodian_count=1, largest_custodian_share_pct=100.0,
                       attestation_age_days=120.0, is_audited=False, can_redeem=False)
        r = analyze_portfolio([safe, risky], config=_cfg())
        self.assertEqual(r["safest_asset"]["symbol"], "SAFE")
        self.assertEqual(r["riskiest_asset"]["symbol"], "RISKY")

    def test_underbacked_count(self):
        assets = [
            _asset(wrapped_supply=1000, reserve_balance=1000),  # full
            _asset(wrapped_supply=1000, reserve_balance=800),   # under
            _asset(wrapped_supply=1000, reserve_balance=500),   # under
        ]
        r = analyze_portfolio(assets, config=_cfg())
        self.assertEqual(r["underbacked_count"], 2)

    def test_avg_risk_score(self):
        assets = [_asset(), _asset()]
        r = analyze_portfolio(assets, config=_cfg())
        self.assertGreaterEqual(r["avg_backing_risk_score"], 0.0)
        self.assertLessEqual(r["avg_backing_risk_score"], 100.0)

    def test_per_asset_results(self):
        assets = [_asset(symbol="A"), _asset(symbol="B")]
        r = analyze_portfolio(assets, config=_cfg())
        self.assertEqual(len(r["results"]), 2)

    def test_not_a_list_input(self):
        r = analyze_portfolio("not a list", config=_cfg())
        self.assertEqual(r["total_assets"], 0)

    def test_malformed_items(self):
        r = analyze_portfolio([{}, "junk", None], config=_cfg())
        self.assertEqual(r["total_assets"], 3)

    def test_timestamp_present(self):
        r = analyze_portfolio([_asset()], config=_cfg())
        self.assertIn("timestamp", r)


# ===========================================================================
# 14. Class wrapper parity
# ===========================================================================

class TestClassWrapper(unittest.TestCase):
    def test_instantiation(self):
        v = ProtocolDeFiWrappedAssetBackingVerifier()
        self.assertIsNotNone(v)

    def test_analyze_returns_dict(self):
        v = ProtocolDeFiWrappedAssetBackingVerifier(config=_cfg())
        r = v.analyze(_asset())
        self.assertIsInstance(r, dict)

    def test_parity_with_functional(self):
        cfg = _cfg()
        asset = _asset(wrapped_supply=1000, reserve_balance=850)
        func_r = analyze(asset, config=cfg)
        v = ProtocolDeFiWrappedAssetBackingVerifier(config=cfg)
        cls_r = v.analyze(asset)
        self.assertEqual(func_r["classification"], cls_r["classification"])
        self.assertEqual(func_r["grade"], cls_r["grade"])
        self.assertAlmostEqual(func_r["backing_ratio_pct"], cls_r["backing_ratio_pct"])
        self.assertEqual(func_r["flags"], cls_r["flags"])

    def test_portfolio_via_class(self):
        v = ProtocolDeFiWrappedAssetBackingVerifier(config=_cfg())
        r = v.analyze_portfolio([_asset(), _asset()])
        self.assertEqual(r["total_assets"], 2)

    def test_config_forwarded_to_log(self):
        path = _tmp_log()
        v = ProtocolDeFiWrappedAssetBackingVerifier(config={"log_path": path})
        v.analyze(_asset())
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_no_config_uses_default(self):
        v = ProtocolDeFiWrappedAssetBackingVerifier()
        r = v.analyze(_asset())
        self.assertIn("classification", r)


# ===========================================================================
# 15. Logging / idempotency
# ===========================================================================

class TestLogging(unittest.TestCase):
    def test_ring_buffer_caps_at_100_via_analyze(self):
        path = _tmp_log()
        cfg = {"log_path": path}
        for i in range(120):
            analyze(_asset(symbol=f"S{i}"), config=cfg)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)
        os.unlink(path)

    def test_idempotent_rerun_same_result(self):
        cfg = _cfg()
        asset = _asset(wrapped_supply=1000, reserve_balance=900)
        r1 = analyze(asset, config=cfg)
        r2 = analyze(asset, config=cfg)
        self.assertEqual(r1["classification"], r2["classification"])
        self.assertEqual(r1["grade"], r2["grade"])
        self.assertEqual(r1["flags"], r2["flags"])
        self.assertAlmostEqual(r1["backing_risk_score"], r2["backing_risk_score"])

    def test_log_accumulates(self):
        path = _tmp_log()
        cfg = {"log_path": path}
        analyze(_asset(symbol="A"), config=cfg)
        analyze(_asset(symbol="B"), config=cfg)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(path)

    def test_does_not_crash_on_unwritable_log(self):
        # Pointing at a path whose parent cannot be created should not raise.
        r = analyze(_asset(), config={"log_path": "/dev/null/cannot/log.json"})
        self.assertIn("classification", r)


# ===========================================================================
# 16. No-exception robustness sweep
# ===========================================================================

class TestRobustness(unittest.TestCase):
    def test_sweep_no_exceptions(self):
        cases = [
            {},
            {"wrapped_supply": 0},
            {"wrapped_supply": -100, "reserve_balance": 50},
            {"wrapped_supply": 1e18, "reserve_balance": 1e18},
            {"custodian_count": "bad"},
            {"largest_custodian_share_pct": "bad"},
            {"attestation_age_days": "bad"},
            {"redemption_fee_pct": -5},
            {"can_redeem": "yes"},
            {"is_audited": 1},
            {"wrapped_supply": 1000, "reserve_balance": 1000, "custodian_count": 0},
        ]
        for c in cases:
            r = analyze(c, config=_cfg())
            self.assertIn("classification", r)
            self.assertIn(r["classification"], ALL_CLASSIFICATIONS)
            self.assertIn(r["grade"], ALL_GRADES)

    def test_scores_always_in_range(self):
        for reserve in [0, 100, 500, 1000, 1500, 5000]:
            r = analyze(_asset(wrapped_supply=1000, reserve_balance=reserve), config=_cfg())
            self.assertGreaterEqual(r["backing_risk_score"], 0.0)
            self.assertLessEqual(r["backing_risk_score"], 100.0)
            self.assertGreaterEqual(r["custodian_concentration_score"], 0.0)
            self.assertLessEqual(r["custodian_concentration_score"], 100.0)
            self.assertGreaterEqual(r["attestation_freshness_score"], 0.0)
            self.assertLessEqual(r["attestation_freshness_score"], 100.0)


if __name__ == "__main__":
    unittest.main()
