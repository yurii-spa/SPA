"""
Tests for MP-1042 DeFiProtocolPointsToTokenConversionRiskAnalyzer
≥90 unittest tests — pure stdlib, no third-party dependencies.
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

from spa_core.analytics.defi_protocol_points_to_token_conversion_risk_analyzer import (
    analyze,
    _total_implied_value_usd,
    _implied_vs_tvl_ratio,
    _dilution_risk_score,
    _lock_value_score,
    _expected_tge_dump_pct,
    _real_yield_after_tge_pct,
    _conversion_label,
    _recommendations,
    _atomic_log,
    DeFiProtocolPointsToTokenConversionRiskAnalyzer,
    ALL_LABELS,
    LABEL_HIGH_VALUE_LOCKED,
    LABEL_REASONABLE_CONVERSION,
    LABEL_DILUTION_WARNING,
    LABEL_FARM_AND_DUMP_RISK,
    LABEL_POINTS_WORTHLESS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _proto(
    protocol_name: str = "TestProto",
    total_points_outstanding: float = 1_000_000.0,
    estimated_token_supply: float = 50_000_000.0,
    implied_point_value_usd: float = 0.10,
    tge_date_days_away: float = 90.0,
    vesting_cliff_days: float = 90.0,
    vesting_duration_days: float = 365.0,
    current_tvl_usd: float = 200_000_000.0,
    points_farming_tvl_ratio: float = 0.30,
) -> dict:
    return {
        "protocol_name": protocol_name,
        "total_points_outstanding": total_points_outstanding,
        "estimated_token_supply": estimated_token_supply,
        "implied_point_value_usd": implied_point_value_usd,
        "tge_date_days_away": tge_date_days_away,
        "vesting_cliff_days": vesting_cliff_days,
        "vesting_duration_days": vesting_duration_days,
        "current_tvl_usd": current_tvl_usd,
        "points_farming_tvl_ratio": points_farming_tvl_ratio,
    }


# ===========================================================================
# 1. _total_implied_value_usd
# ===========================================================================

class TestTotalImpliedValueUsd(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(
            _total_implied_value_usd(1_000_000.0, 0.10), 100_000.0
        )

    def test_zero_points(self):
        self.assertEqual(_total_implied_value_usd(0.0, 0.10), 0.0)

    def test_zero_value(self):
        self.assertEqual(_total_implied_value_usd(1_000_000.0, 0.0), 0.0)

    def test_negative_points_clamped(self):
        # negative points should yield 0
        self.assertEqual(_total_implied_value_usd(-500.0, 1.0), 0.0)

    def test_negative_value_clamped(self):
        self.assertEqual(_total_implied_value_usd(1000.0, -1.0), 0.0)

    def test_large_numbers(self):
        v = _total_implied_value_usd(1e9, 0.50)
        self.assertAlmostEqual(v, 5e8)

    def test_small_fractional(self):
        v = _total_implied_value_usd(100.0, 0.001)
        self.assertAlmostEqual(v, 0.1)


# ===========================================================================
# 2. _implied_vs_tvl_ratio
# ===========================================================================

class TestImpliedVsTvlRatio(unittest.TestCase):
    def test_basic(self):
        # 100_000 / 1_000_000 = 0.1
        self.assertAlmostEqual(_implied_vs_tvl_ratio(100_000.0, 1_000_000.0), 0.1)

    def test_zero_tvl_returns_worst_case(self):
        v = _implied_vs_tvl_ratio(100.0, 0.0)
        self.assertGreaterEqual(v, 1.0)

    def test_negative_tvl_returns_worst_case(self):
        v = _implied_vs_tvl_ratio(100.0, -500.0)
        self.assertGreaterEqual(v, 1.0)

    def test_higher_implied_gives_higher_ratio(self):
        r1 = _implied_vs_tvl_ratio(1_000_000.0, 10_000_000.0)
        r2 = _implied_vs_tvl_ratio(5_000_000.0, 10_000_000.0)
        self.assertLess(r1, r2)

    def test_equal_values_gives_one(self):
        self.assertAlmostEqual(_implied_vs_tvl_ratio(1_000.0, 1_000.0), 1.0)


# ===========================================================================
# 3. _dilution_risk_score
# ===========================================================================

class TestDilutionRiskScore(unittest.TestCase):
    def test_range_low(self):
        # Long TGE horizon, low farming ratio, low implied ratio
        score = _dilution_risk_score(100.0, 0.01, 100_000_000.0, 0.05, 500.0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)
        self.assertLess(score, 30.0)

    def test_range_high(self):
        # Imminent TGE, high farming ratio, high implied ratio
        score = _dilution_risk_score(1_000_000.0, 10.0, 100_000.0, 0.95, 0.0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)
        self.assertGreater(score, 60.0)

    def test_always_in_0_100(self):
        for pts in [0, 1e6, 1e9]:
            for val in [0.0, 0.5, 100.0]:
                for tvl in [0.0, 1e6, 1e10]:
                    for fr in [0.0, 0.5, 1.0]:
                        for days in [0.0, 100.0, 500.0]:
                            s = _dilution_risk_score(pts, val, tvl, fr, days)
                            self.assertGreaterEqual(s, 0.0)
                            self.assertLessEqual(s, 100.0)

    def test_zero_farming_reduces_risk(self):
        s_low = _dilution_risk_score(1e6, 1.0, 1e8, 0.0, 90.0)
        s_high = _dilution_risk_score(1e6, 1.0, 1e8, 0.9, 90.0)
        self.assertLess(s_low, s_high)

    def test_imminent_tge_increases_risk(self):
        s_near = _dilution_risk_score(1e6, 1.0, 1e8, 0.5, 0.0)
        s_far = _dilution_risk_score(1e6, 1.0, 1e8, 0.5, 400.0)
        self.assertGreater(s_near, s_far)

    def test_high_implied_vs_tvl_increases_risk(self):
        s_high = _dilution_risk_score(1e6, 10.0, 1e6, 0.3, 90.0)
        s_low = _dilution_risk_score(1e6, 0.001, 1e8, 0.3, 90.0)
        self.assertGreater(s_high, s_low)

    def test_zero_all_inputs(self):
        score = _dilution_risk_score(0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)


# ===========================================================================
# 4. _lock_value_score
# ===========================================================================

class TestLockValueScore(unittest.TestCase):
    def test_no_vesting(self):
        score = _lock_value_score(0.0, 0.0)
        self.assertAlmostEqual(score, 0.0)

    def test_long_cliff_and_duration(self):
        score = _lock_value_score(365.0, 730.0)
        self.assertGreaterEqual(score, 80.0)

    def test_always_in_0_100(self):
        for cliff in [0, 30, 90, 180, 365, 730]:
            for dur in [0, 90, 180, 365, 730, 1460]:
                s = _lock_value_score(float(cliff), float(dur))
                self.assertGreaterEqual(s, 0.0)
                self.assertLessEqual(s, 100.0)

    def test_longer_cliff_gives_higher_score(self):
        s_short = _lock_value_score(30.0, 365.0)
        s_long = _lock_value_score(180.0, 365.0)
        self.assertLess(s_short, s_long)

    def test_longer_duration_gives_higher_score(self):
        s_short = _lock_value_score(90.0, 180.0)
        s_long = _lock_value_score(90.0, 730.0)
        self.assertLess(s_short, s_long)

    def test_negative_inputs_treated_as_zero(self):
        s = _lock_value_score(-100.0, -200.0)
        self.assertAlmostEqual(s, 0.0)

    def test_cliff_contribution(self):
        # With only cliff (no duration): score should be positive
        s = _lock_value_score(180.0, 0.0)
        self.assertGreater(s, 0.0)

    def test_duration_contribution(self):
        # With only duration (no cliff): score should be positive
        s = _lock_value_score(0.0, 365.0)
        self.assertGreater(s, 0.0)


# ===========================================================================
# 5. _expected_tge_dump_pct
# ===========================================================================

class TestExpectedTgeDumpPct(unittest.TestCase):
    def test_no_vesting_high_farming_is_high(self):
        dump = _expected_tge_dump_pct(0.8, 0.0, 0.0)
        self.assertGreater(dump, 50.0)

    def test_long_cliff_reduces_dump(self):
        dump_no_cliff = _expected_tge_dump_pct(0.7, 0.0, 365.0)
        dump_with_cliff = _expected_tge_dump_pct(0.7, 180.0, 365.0)
        self.assertGreater(dump_no_cliff, dump_with_cliff)

    def test_zero_farming_means_zero_dump(self):
        dump = _expected_tge_dump_pct(0.0, 0.0, 0.0)
        self.assertAlmostEqual(dump, 0.0)

    def test_always_in_0_95(self):
        for fr in [0.0, 0.3, 0.7, 1.0]:
            for cliff in [0.0, 90.0, 365.0]:
                for dur in [0.0, 180.0, 730.0]:
                    d = _expected_tge_dump_pct(fr, cliff, dur)
                    self.assertGreaterEqual(d, 0.0)
                    self.assertLessEqual(d, 95.0)

    def test_farming_ratio_clamp_above_one(self):
        d1 = _expected_tge_dump_pct(1.0, 0.0, 0.0)
        d2 = _expected_tge_dump_pct(2.0, 0.0, 0.0)
        self.assertAlmostEqual(d1, d2)

    def test_negative_farming_is_zero(self):
        d = _expected_tge_dump_pct(-0.5, 0.0, 0.0)
        self.assertAlmostEqual(d, 0.0)

    def test_long_duration_no_cliff_reduces_dump(self):
        d_short = _expected_tge_dump_pct(0.6, 0.0, 30.0)
        d_long = _expected_tge_dump_pct(0.6, 0.0, 730.0)
        self.assertGreater(d_short, d_long)

    def test_partial_farming_scales_linearly(self):
        # With no vesting, ratio 0.5x vs 0.25x should give 2x dump (cap doesn't apply)
        d_quarter = _expected_tge_dump_pct(0.25, 0.0, 0.0)
        d_half = _expected_tge_dump_pct(0.50, 0.0, 0.0)
        self.assertAlmostEqual(d_half, d_quarter * 2.0, places=5)


# ===========================================================================
# 6. _real_yield_after_tge_pct
# ===========================================================================

class TestRealYieldAfterTgePct(unittest.TestCase):
    def test_basic(self):
        # 1M pts * $0.10 = $100K / $1M TVL = 10%, dump 50% → 5%
        y = _real_yield_after_tge_pct(1_000_000.0, 0.10, 1_000_000.0, 50.0)
        self.assertAlmostEqual(y, 5.0)

    def test_no_dump_full_yield(self):
        y = _real_yield_after_tge_pct(1_000_000.0, 0.10, 1_000_000.0, 0.0)
        self.assertAlmostEqual(y, 10.0)

    def test_full_dump_zero_yield(self):
        y = _real_yield_after_tge_pct(1_000_000.0, 0.10, 1_000_000.0, 100.0)
        self.assertAlmostEqual(y, 0.0)

    def test_zero_tvl_returns_zero(self):
        y = _real_yield_after_tge_pct(1_000_000.0, 0.10, 0.0, 30.0)
        self.assertEqual(y, 0.0)

    def test_always_non_negative(self):
        for pts in [0.0, 1e6, 1e9]:
            for val in [0.0, 0.5]:
                for tvl in [0.0, 1e6]:
                    for dump in [0.0, 50.0, 100.0, 110.0]:
                        r = _real_yield_after_tge_pct(pts, val, tvl, dump)
                        self.assertGreaterEqual(r, 0.0)

    def test_higher_implied_value_higher_yield(self):
        y1 = _real_yield_after_tge_pct(1e6, 0.05, 1e8, 20.0)
        y2 = _real_yield_after_tge_pct(1e6, 0.20, 1e8, 20.0)
        self.assertLess(y1, y2)


# ===========================================================================
# 7. _conversion_label
# ===========================================================================

class TestConversionLabel(unittest.TestCase):
    def test_points_worthless_zero_value(self):
        label = _conversion_label(20.0, 70.0, 5.0, 0.0, 0.2, 90.0)
        self.assertEqual(label, LABEL_POINTS_WORTHLESS)

    def test_points_worthless_zero_real_yield(self):
        label = _conversion_label(20.0, 70.0, 0.0, 0.05, 0.2, 90.0)
        self.assertEqual(label, LABEL_POINTS_WORTHLESS)

    def test_points_worthless_negative_value(self):
        label = _conversion_label(20.0, 70.0, 5.0, -0.01, 0.2, 90.0)
        self.assertEqual(label, LABEL_POINTS_WORTHLESS)

    def test_farm_and_dump_high_dilution(self):
        label = _conversion_label(80.0, 30.0, 3.0, 0.05, 0.50, 90.0)
        self.assertEqual(label, LABEL_FARM_AND_DUMP_RISK)

    def test_farm_and_dump_high_farming_no_cliff(self):
        # farming_ratio 0.7 > 0.65 and cliff < 30
        label = _conversion_label(50.0, 40.0, 5.0, 0.05, 0.70, 20.0)
        self.assertEqual(label, LABEL_FARM_AND_DUMP_RISK)

    def test_dilution_warning_moderate_score(self):
        label = _conversion_label(60.0, 40.0, 5.0, 0.05, 0.40, 90.0)
        self.assertEqual(label, LABEL_DILUTION_WARNING)

    def test_high_value_locked(self):
        label = _conversion_label(20.0, 80.0, 10.0, 0.05, 0.10, 180.0)
        self.assertEqual(label, LABEL_HIGH_VALUE_LOCKED)

    def test_reasonable_conversion_default(self):
        label = _conversion_label(30.0, 50.0, 5.0, 0.05, 0.30, 90.0)
        self.assertEqual(label, LABEL_REASONABLE_CONVERSION)

    def test_all_labels_are_valid(self):
        test_cases = [
            (20.0, 70.0, 5.0, 0.0, 0.2, 90.0),   # worthless
            (80.0, 30.0, 3.0, 0.05, 0.50, 90.0),  # farm and dump (high dilution)
            (60.0, 40.0, 5.0, 0.05, 0.40, 90.0),  # dilution warning
            (20.0, 80.0, 10.0, 0.05, 0.10, 180.0), # high value locked
            (30.0, 50.0, 5.0, 0.05, 0.30, 90.0),  # reasonable
        ]
        for args in test_cases:
            label = _conversion_label(*args)
            self.assertIn(label, ALL_LABELS)

    def test_farm_and_dump_boundary_exact_75(self):
        label = _conversion_label(75.0, 30.0, 3.0, 0.05, 0.50, 90.0)
        self.assertEqual(label, LABEL_FARM_AND_DUMP_RISK)

    def test_dilution_warning_boundary_exact_55(self):
        label = _conversion_label(55.0, 40.0, 5.0, 0.05, 0.40, 90.0)
        self.assertEqual(label, LABEL_DILUTION_WARNING)

    def test_not_high_value_locked_when_dilution_too_high(self):
        # lock_value_score >= 65 but dilution >= 40 → not HIGH_VALUE_LOCKED
        label = _conversion_label(45.0, 80.0, 5.0, 0.05, 0.20, 90.0)
        self.assertNotEqual(label, LABEL_HIGH_VALUE_LOCKED)


# ===========================================================================
# 8. _recommendations
# ===========================================================================

class TestRecommendations(unittest.TestCase):
    def test_worthless_has_message(self):
        recs = _recommendations(LABEL_POINTS_WORTHLESS, 20.0, 70.0, 30.0, 0.0, 0.2, 90.0, 365.0)
        self.assertGreater(len(recs), 0)
        self.assertTrue(any("zero" in r.lower() or "no economic" in r.lower() or "non-positive" in r.lower() for r in recs))

    def test_farm_and_dump_has_message(self):
        recs = _recommendations(LABEL_FARM_AND_DUMP_RISK, 80.0, 20.0, 70.0, 5.0, 0.80, 10.0, 90.0)
        self.assertGreater(len(recs), 0)

    def test_high_value_locked_has_message(self):
        recs = _recommendations(LABEL_HIGH_VALUE_LOCKED, 15.0, 80.0, 10.0, 12.0, 0.10, 180.0, 730.0)
        self.assertGreater(len(recs), 0)

    def test_dilution_warning_has_message(self):
        recs = _recommendations(LABEL_DILUTION_WARNING, 60.0, 40.0, 40.0, 5.0, 0.40, 90.0, 365.0)
        self.assertGreater(len(recs), 0)

    def test_reasonable_conversion_has_message(self):
        recs = _recommendations(LABEL_REASONABLE_CONVERSION, 30.0, 50.0, 20.0, 8.0, 0.30, 90.0, 365.0)
        self.assertGreater(len(recs), 0)

    def test_high_dump_triggers_extra_rec(self):
        # expected_tge_dump_pct > 30 should add a size-cautiously message
        recs = _recommendations(LABEL_FARM_AND_DUMP_RISK, 80.0, 20.0, 60.0, 5.0, 0.80, 10.0, 90.0)
        combined = " ".join(recs).lower()
        self.assertTrue("tge" in combined or "price" in combined or "60" in combined)

    def test_returns_list(self):
        for label in ALL_LABELS:
            recs = _recommendations(label, 50.0, 50.0, 30.0, 5.0, 0.50, 30.0, 180.0)
            self.assertIsInstance(recs, list)


# ===========================================================================
# 9. _atomic_log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):
    def test_creates_file(self):
        path = _tmp_log()
        _atomic_log(path, {"x": 1})
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["x"], 1)
        os.unlink(path)

    def test_appends(self):
        path = _tmp_log()
        _atomic_log(path, {"n": 1})
        _atomic_log(path, {"n": 2})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(path)

    def test_ring_buffer_cap(self):
        path = _tmp_log()
        for i in range(105):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)
        self.assertEqual(data[-1]["i"], 104)
        os.unlink(path)

    def test_recovers_from_corrupt_file(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("NOT JSON{{")
        _atomic_log(path, {"ok": True})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_creates_directories(self):
        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "sub", "deep", "log.json")
        _atomic_log(path, {"hello": "world"})
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["hello"], "world")


# ===========================================================================
# 10. analyze — integration tests
# ===========================================================================

class TestAnalyze(unittest.TestCase):
    def _cfg(self) -> dict:
        return {"log_path": _tmp_log()}

    def test_returns_dict(self):
        r = analyze(_proto(), config=self._cfg())
        self.assertIsInstance(r, dict)

    def test_required_keys(self):
        r = analyze(_proto(), config=self._cfg())
        for key in [
            "protocol_name", "dilution_risk_score", "lock_value_score",
            "expected_tge_dump_pct", "real_yield_after_tge_pct",
            "label", "recommendations", "timestamp",
        ]:
            self.assertIn(key, r)

    def test_label_in_all_labels(self):
        r = analyze(_proto(), config=self._cfg())
        self.assertIn(r["label"], ALL_LABELS)

    def test_scores_in_range(self):
        r = analyze(_proto(), config=self._cfg())
        self.assertGreaterEqual(r["dilution_risk_score"], 0.0)
        self.assertLessEqual(r["dilution_risk_score"], 100.0)
        self.assertGreaterEqual(r["lock_value_score"], 0.0)
        self.assertLessEqual(r["lock_value_score"], 100.0)

    def test_dump_in_range(self):
        r = analyze(_proto(), config=self._cfg())
        self.assertGreaterEqual(r["expected_tge_dump_pct"], 0.0)
        self.assertLessEqual(r["expected_tge_dump_pct"], 95.0)

    def test_farm_and_dump_scenario(self):
        p = _proto(
            points_farming_tvl_ratio=0.85,
            vesting_cliff_days=0.0,
            vesting_duration_days=30.0,
            tge_date_days_away=10.0,
            total_points_outstanding=5_000_000.0,
            implied_point_value_usd=0.50,
            current_tvl_usd=10_000_000.0,
        )
        r = analyze(p, config=self._cfg())
        self.assertIn(r["label"], [LABEL_FARM_AND_DUMP_RISK, LABEL_DILUTION_WARNING])

    def test_high_value_locked_scenario(self):
        p = _proto(
            points_farming_tvl_ratio=0.05,
            vesting_cliff_days=365.0,
            vesting_duration_days=730.0,
            tge_date_days_away=400.0,
            total_points_outstanding=100_000.0,
            implied_point_value_usd=0.01,
            current_tvl_usd=500_000_000.0,
        )
        r = analyze(p, config=self._cfg())
        self.assertEqual(r["label"], LABEL_HIGH_VALUE_LOCKED)

    def test_points_worthless_scenario(self):
        p = _proto(implied_point_value_usd=0.0)
        r = analyze(p, config=self._cfg())
        self.assertEqual(r["label"], LABEL_POINTS_WORTHLESS)

    def test_recommendations_is_list(self):
        r = analyze(_proto(), config=self._cfg())
        self.assertIsInstance(r["recommendations"], list)

    def test_timestamp_is_recent(self):
        before = time.time()
        r = analyze(_proto(), config=self._cfg())
        after = time.time()
        self.assertGreaterEqual(r["timestamp"], before)
        self.assertLessEqual(r["timestamp"], after)

    def test_missing_keys_handled_gracefully(self):
        r = analyze({}, config=self._cfg())
        self.assertIsInstance(r, dict)
        self.assertIn("label", r)

    def test_protocol_name_preserved(self):
        p = _proto(protocol_name="FancyProtocol")
        r = analyze(p, config=self._cfg())
        self.assertEqual(r["protocol_name"], "FancyProtocol")

    def test_estimated_token_supply_passed_through(self):
        p = _proto(estimated_token_supply=200_000_000.0)
        r = analyze(p, config=self._cfg())
        self.assertAlmostEqual(r["estimated_token_supply"], 200_000_000.0)

    def test_input_values_in_result(self):
        p = _proto(tge_date_days_away=120.0)
        r = analyze(p, config=self._cfg())
        self.assertAlmostEqual(r["tge_date_days_away"], 120.0)

    def test_total_implied_value_in_result(self):
        p = _proto(total_points_outstanding=500_000.0, implied_point_value_usd=0.20)
        r = analyze(p, config=self._cfg())
        self.assertAlmostEqual(r["total_implied_value_usd"], 100_000.0)

    def test_dilution_warning_scenario(self):
        # score: c1=30 (ratio 1.2x), c2=65 (farming 65%), c3=100 (tge imminent)
        # → 30*0.45 + 65*0.35 + 100*0.20 = 13.5+22.75+20 = 56.25 → DILUTION_WARNING
        p = _proto(
            points_farming_tvl_ratio=0.65,
            vesting_cliff_days=30.0,
            vesting_duration_days=180.0,
            total_points_outstanding=3_000_000.0,
            implied_point_value_usd=2.0,
            current_tvl_usd=5_000_000.0,
            tge_date_days_away=0.0,
        )
        r = analyze(p, config=self._cfg())
        self.assertIn(r["label"], [LABEL_DILUTION_WARNING, LABEL_FARM_AND_DUMP_RISK])


# ===========================================================================
# 11. DeFiProtocolPointsToTokenConversionRiskAnalyzer class
# ===========================================================================

class TestClass(unittest.TestCase):
    def test_instantiation(self):
        a = DeFiProtocolPointsToTokenConversionRiskAnalyzer()
        self.assertIsNotNone(a)

    def test_analyze_returns_dict(self):
        cfg = {"log_path": _tmp_log()}
        a = DeFiProtocolPointsToTokenConversionRiskAnalyzer(config=cfg)
        r = a.analyze(_proto())
        self.assertIsInstance(r, dict)

    def test_analyze_label_valid(self):
        cfg = {"log_path": _tmp_log()}
        a = DeFiProtocolPointsToTokenConversionRiskAnalyzer(config=cfg)
        r = a.analyze(_proto())
        self.assertIn(r["label"], ALL_LABELS)

    def test_config_forwarded(self):
        path = _tmp_log()
        cfg = {"log_path": path}
        a = DeFiProtocolPointsToTokenConversionRiskAnalyzer(config=cfg)
        a.analyze(_proto())
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_multiple_calls_accumulate(self):
        path = _tmp_log()
        cfg = {"log_path": path}
        a = DeFiProtocolPointsToTokenConversionRiskAnalyzer(config=cfg)
        a.analyze(_proto())
        a.analyze(_proto(protocol_name="Proto2"))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        os.unlink(path)

    def test_no_config_uses_default(self):
        a = DeFiProtocolPointsToTokenConversionRiskAnalyzer()
        r = a.analyze(_proto())
        self.assertIn("label", r)

    def test_real_yield_non_negative(self):
        cfg = {"log_path": _tmp_log()}
        a = DeFiProtocolPointsToTokenConversionRiskAnalyzer(config=cfg)
        r = a.analyze(_proto(points_farming_tvl_ratio=1.0, vesting_cliff_days=0.0))
        self.assertGreaterEqual(r["real_yield_after_tge_pct"], 0.0)

    def test_implied_vs_tvl_ratio_in_result(self):
        cfg = {"log_path": _tmp_log()}
        a = DeFiProtocolPointsToTokenConversionRiskAnalyzer(config=cfg)
        r = a.analyze(_proto())
        self.assertIn("implied_vs_tvl_ratio", r)
        self.assertGreaterEqual(r["implied_vs_tvl_ratio"], 0.0)


# ===========================================================================
# 12. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def test_all_zeros(self):
        p = {k: 0.0 for k in [
            "total_points_outstanding", "estimated_token_supply",
            "implied_point_value_usd", "tge_date_days_away",
            "vesting_cliff_days", "vesting_duration_days",
            "current_tvl_usd", "points_farming_tvl_ratio",
        ]}
        p["protocol_name"] = "ZeroProto"
        r = analyze(p, config={"log_path": _tmp_log()})
        self.assertIn(r["label"], ALL_LABELS)
        self.assertGreaterEqual(r["dilution_risk_score"], 0.0)

    def test_very_large_points_outstanding(self):
        p = _proto(total_points_outstanding=1e15, implied_point_value_usd=0.001)
        r = analyze(p, config={"log_path": _tmp_log()})
        self.assertLessEqual(r["dilution_risk_score"], 100.0)

    def test_tge_very_far_away(self):
        p = _proto(tge_date_days_away=3650.0)
        r = analyze(p, config={"log_path": _tmp_log()})
        self.assertLessEqual(r["dilution_risk_score"], 100.0)

    def test_farming_ratio_above_one_is_clamped(self):
        p = _proto(points_farming_tvl_ratio=5.0)
        r = analyze(p, config={"log_path": _tmp_log()})
        # Should not crash; dump_pct should be capped at 95
        self.assertLessEqual(r["expected_tge_dump_pct"], 95.0)

    def test_string_numbers_converted(self):
        p = _proto()
        p["tge_date_days_away"] = "120"
        p["vesting_cliff_days"] = "60"
        r = analyze(p, config={"log_path": _tmp_log()})
        self.assertIn("label", r)

    def test_reasonable_conversion_label_variety(self):
        p = _proto(
            points_farming_tvl_ratio=0.20,
            vesting_cliff_days=60.0,
            vesting_duration_days=365.0,
            tge_date_days_away=180.0,
            total_points_outstanding=500_000.0,
            implied_point_value_usd=0.05,
            current_tvl_usd=100_000_000.0,
        )
        r = analyze(p, config={"log_path": _tmp_log()})
        self.assertIn(r["label"], ALL_LABELS)


if __name__ == "__main__":
    unittest.main()
