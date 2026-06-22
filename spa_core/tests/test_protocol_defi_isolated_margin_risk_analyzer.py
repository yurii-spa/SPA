#!/usr/bin/env python3
"""Unit tests for MP-1035 ProtocolDeFiIsolatedMarginRiskAnalyzer (SPA-V755).

Run:
    python3 -m unittest spa_core/tests/test_protocol_defi_isolated_margin_risk_analyzer.py -v

stdlib unittest only — no pytest, no numpy.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.protocol_defi_isolated_margin_risk_analyzer import (
    ProtocolDeFiIsolatedMarginRiskAnalyzer,
    _clamp,
    _compute_liquidation_price,
    _compute_margin_of_safety,
    _compute_health_score,
    _compute_time_to_liquidation,
    _compute_label,
    _load_json_list,
    _atomic_write,
    analyze_isolated_margin,
    write_log,
    RING_BUFFER_CAP,
    LOG_FILENAME,
    LIQUIDATION_IMMINENT_HF,
    LIQUIDATION_IMMINENT_DAYS,
    WARNING_HF,
    WARNING_DAYS,
    MONITOR_HF,
    SAFE_HF,
)


# ===========================================================================
# 1. _clamp helper
# ===========================================================================

class TestClamp(unittest.TestCase):

    def test_clamp_within_range(self):
        self.assertAlmostEqual(_clamp(5.0, 0.0, 100.0), 5.0)

    def test_clamp_below_low(self):
        self.assertAlmostEqual(_clamp(-1.0, 0.0, 100.0), 0.0)

    def test_clamp_above_high(self):
        self.assertAlmostEqual(_clamp(110.0, 0.0, 100.0), 100.0)

    def test_clamp_at_boundaries(self):
        self.assertAlmostEqual(_clamp(0.0, 0.0, 100.0), 0.0)
        self.assertAlmostEqual(_clamp(100.0, 0.0, 100.0), 100.0)


# ===========================================================================
# 2. _compute_liquidation_price
# ===========================================================================

class TestComputeLiquidationPrice(unittest.TestCase):

    def test_basic_case(self):
        # liq_price = borrow * oracle / (collateral * ltv)
        # = 80000 * 2000 / (150000 * 0.825)
        # = 160000000 / 123750 = 1292.929...
        liq, warnings = _compute_liquidation_price(150_000, 80_000, 2_000, 0.825)
        expected = 80_000 * 2_000 / (150_000 * 0.825)
        self.assertAlmostEqual(liq, expected, places=4)
        self.assertEqual(warnings, [])

    def test_zero_borrow_gives_zero_liquidation_price(self):
        liq, _ = _compute_liquidation_price(100_000, 0.0, 2_000, 0.825)
        self.assertAlmostEqual(liq, 0.0, places=6)

    def test_zero_collateral_returns_none_with_warning(self):
        liq, warnings = _compute_liquidation_price(0.0, 80_000, 2_000, 0.825)
        self.assertIsNone(liq)
        self.assertGreater(len(warnings), 0)

    def test_zero_ltv_returns_none_with_warning(self):
        liq, warnings = _compute_liquidation_price(150_000, 80_000, 2_000, 0.0)
        self.assertIsNone(liq)
        self.assertGreater(len(warnings), 0)

    def test_zero_oracle_price_returns_none_with_warning(self):
        liq, warnings = _compute_liquidation_price(150_000, 80_000, 0.0, 0.825)
        self.assertIsNone(liq)
        self.assertGreater(len(warnings), 0)

    def test_higher_ltv_lower_liquidation_price(self):
        liq_low_ltv, _ = _compute_liquidation_price(100_000, 50_000, 1_000, 0.5)
        liq_high_ltv, _ = _compute_liquidation_price(100_000, 50_000, 1_000, 0.9)
        self.assertGreater(liq_low_ltv, liq_high_ltv)

    def test_higher_borrow_higher_liquidation_price(self):
        liq_low, _ = _compute_liquidation_price(100_000, 30_000, 1_000, 0.8)
        liq_high, _ = _compute_liquidation_price(100_000, 70_000, 1_000, 0.8)
        self.assertLess(liq_low, liq_high)

    def test_higher_collateral_lower_liquidation_price(self):
        liq_low_coll, _ = _compute_liquidation_price(80_000, 50_000, 1_000, 0.8)
        liq_high_coll, _ = _compute_liquidation_price(200_000, 50_000, 1_000, 0.8)
        self.assertGreater(liq_low_coll, liq_high_coll)

    def test_liquidation_price_below_oracle_for_safe_position(self):
        # Healthy position: collateral=200k, borrow=80k, oracle=2000, ltv=0.825
        liq, _ = _compute_liquidation_price(200_000, 80_000, 2_000, 0.825)
        self.assertLess(liq, 2_000)

    def test_ltv_of_1_liquidation_price_equals_borrow_per_collateral_tokens(self):
        # liq = borrow * oracle / (collateral * 1.0) = 80000*2000/150000 = 1066.67
        liq, _ = _compute_liquidation_price(150_000, 80_000, 2_000, 1.0)
        expected = 80_000 * 2_000 / 150_000
        self.assertAlmostEqual(liq, expected, places=4)

    def test_proportional_to_oracle_price(self):
        liq1, _ = _compute_liquidation_price(100_000, 50_000, 1_000, 0.8)
        liq2, _ = _compute_liquidation_price(100_000, 50_000, 2_000, 0.8)
        self.assertAlmostEqual(liq2, 2 * liq1, places=4)

    def test_negative_collateral_returns_none(self):
        liq, warnings = _compute_liquidation_price(-1_000, 50_000, 1_000, 0.8)
        self.assertIsNone(liq)
        self.assertGreater(len(warnings), 0)

    def test_negative_ltv_returns_none(self):
        liq, warnings = _compute_liquidation_price(100_000, 50_000, 1_000, -0.1)
        self.assertIsNone(liq)
        self.assertGreater(len(warnings), 0)


# ===========================================================================
# 3. _compute_margin_of_safety
# ===========================================================================

class TestComputeMarginOfSafety(unittest.TestCase):

    def test_basic_margin(self):
        # oracle=2000, liq=1000 → margin=(2000-1000)/2000*100=50%
        margin, warnings = _compute_margin_of_safety(2_000.0, 1_000.0)
        self.assertAlmostEqual(margin, 50.0, places=6)
        self.assertEqual(warnings, [])

    def test_margin_zero_when_at_liquidation(self):
        margin, _ = _compute_margin_of_safety(1_000.0, 1_000.0)
        self.assertAlmostEqual(margin, 0.0, places=6)

    def test_negative_margin_when_underwater(self):
        # liq > oracle → already underwater
        margin, _ = _compute_margin_of_safety(1_000.0, 1_200.0)
        self.assertLess(margin, 0.0)

    def test_100_pct_margin_when_borrow_zero(self):
        margin, _ = _compute_margin_of_safety(2_000.0, 0.0)
        self.assertAlmostEqual(margin, 100.0, places=6)

    def test_none_liquidation_price_returns_none(self):
        margin, warnings = _compute_margin_of_safety(2_000.0, None)
        self.assertIsNone(margin)
        self.assertGreater(len(warnings), 0)

    def test_zero_oracle_returns_none(self):
        margin, warnings = _compute_margin_of_safety(0.0, 500.0)
        self.assertIsNone(margin)
        self.assertGreater(len(warnings), 0)

    def test_30pct_margin(self):
        # oracle=1000, liq=700 → margin=30%
        margin, _ = _compute_margin_of_safety(1_000.0, 700.0)
        self.assertAlmostEqual(margin, 30.0, places=6)

    def test_margin_proportional_to_distance(self):
        m1, _ = _compute_margin_of_safety(2_000.0, 1_800.0)  # 10%
        m2, _ = _compute_margin_of_safety(2_000.0, 1_600.0)  # 20%
        self.assertAlmostEqual(m2, 2 * m1, places=6)


# ===========================================================================
# 4. _compute_health_score
# ===========================================================================

class TestComputeHealthScore(unittest.TestCase):

    def test_health_factor_0(self):
        score = _compute_health_score(0.0, 0.0)
        self.assertAlmostEqual(score, 0.0, places=4)

    def test_health_factor_1(self):
        # Band1: score = 1.0 * 20 = 20
        score = _compute_health_score(1.0, 0.0)
        self.assertAlmostEqual(score, 20.0, places=4)

    def test_health_factor_1_5(self):
        # Band2: score = 20 + (1.5-1.0)*40 = 20+20 = 40
        score = _compute_health_score(1.5, 0.0)
        self.assertAlmostEqual(score, 40.0, places=4)

    def test_health_factor_2(self):
        # Band2: score = 20 + (2.0-1.0)*40 = 20+40 = 60
        score = _compute_health_score(2.0, 0.0)
        self.assertAlmostEqual(score, 60.0, places=4)

    def test_health_factor_2_5(self):
        # Band3: score = 60 + (2.5-2.0)*30 = 60+15 = 75
        score = _compute_health_score(2.5, 0.0)
        self.assertAlmostEqual(score, 75.0, places=4)

    def test_health_factor_3(self):
        # Band3 top: score = 60 + (3.0-2.0)*30 = 60+30 = 90
        score = _compute_health_score(3.0, 0.0)
        self.assertAlmostEqual(score, 90.0, places=4)

    def test_health_factor_4(self):
        # Band4: score = 90 + min(10, (4-3)*5) = 90+5 = 95
        score = _compute_health_score(4.0, 0.0)
        self.assertAlmostEqual(score, 95.0, places=4)

    def test_health_factor_5(self):
        # Band4: score = 90 + min(10, (5-3)*5) = 90+10 = 100
        score = _compute_health_score(5.0, 0.0)
        self.assertAlmostEqual(score, 100.0, places=4)

    def test_health_factor_10_caps_at_100(self):
        score = _compute_health_score(10.0, 0.0)
        self.assertAlmostEqual(score, 100.0, places=4)

    def test_score_never_negative(self):
        score = _compute_health_score(-1.0, 0.0)
        self.assertGreaterEqual(score, 0.0)

    def test_score_never_above_100(self):
        score = _compute_health_score(100.0, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_high_volatility_penalises_score(self):
        low_vol = _compute_health_score(2.0, 10.0)
        high_vol = _compute_health_score(2.0, 50.0)
        self.assertGreater(low_vol, high_vol)

    def test_low_volatility_no_penalty(self):
        no_vol = _compute_health_score(2.0, 0.0)
        some_vol = _compute_health_score(2.0, 25.0)  # below threshold 30%
        self.assertAlmostEqual(no_vol, some_vol, places=4)

    def test_volatility_penalty_at_threshold(self):
        no_penalty = _compute_health_score(2.0, 30.0)  # exactly at threshold → no penalty
        self.assertAlmostEqual(no_penalty, _compute_health_score(2.0, 0.0), places=4)

    def test_score_increases_with_health_factor(self):
        s1 = _compute_health_score(1.0, 0.0)
        s2 = _compute_health_score(1.5, 0.0)
        s3 = _compute_health_score(2.0, 0.0)
        self.assertLess(s1, s2)
        self.assertLess(s2, s3)


# ===========================================================================
# 5. _compute_time_to_liquidation
# ===========================================================================

class TestComputeTimeToLiquidation(unittest.TestCase):

    def test_already_liquidatable(self):
        ttl = _compute_time_to_liquidation(0.9, 100.0)
        self.assertAlmostEqual(ttl, 0.0, places=6)

    def test_hf_exactly_1_not_yet_liquidatable(self):
        ttl = _compute_time_to_liquidation(1.0, 50.0)
        self.assertAlmostEqual(ttl, 50.0, places=6)

    def test_none_trend_returns_none(self):
        ttl = _compute_time_to_liquidation(1.5, None)
        self.assertIsNone(ttl)

    def test_positive_trend_passed_through(self):
        ttl = _compute_time_to_liquidation(1.5, 30.0)
        self.assertAlmostEqual(ttl, 30.0, places=6)

    def test_zero_trend_returns_zero(self):
        ttl = _compute_time_to_liquidation(1.5, 0.0)
        self.assertAlmostEqual(ttl, 0.0, places=6)

    def test_negative_trend_returns_zero(self):
        ttl = _compute_time_to_liquidation(1.5, -5.0)
        self.assertAlmostEqual(ttl, 0.0, places=6)

    def test_hf_exactly_1_is_not_liquidatable(self):
        # HF=1.0 is exactly at the threshold (not < 1), so use trend
        ttl = _compute_time_to_liquidation(1.0, 20.0)
        self.assertAlmostEqual(ttl, 20.0, places=6)


# ===========================================================================
# 6. _compute_label
# ===========================================================================

class TestComputeLabel(unittest.TestCase):

    def test_liquidation_imminent_low_hf(self):
        self.assertEqual(_compute_label(1.05, 20.0, 100.0), "LIQUIDATION_IMMINENT")

    def test_liquidation_imminent_hf_below_threshold(self):
        self.assertEqual(_compute_label(0.9, 0.0, None), "LIQUIDATION_IMMINENT")

    def test_liquidation_imminent_short_ttl(self):
        # HF=1.5 but ttl=2 → LIQUIDATION_IMMINENT
        self.assertEqual(_compute_label(1.5, 40.0, 2.0), "LIQUIDATION_IMMINENT")

    def test_liquidation_imminent_ttl_exactly_3(self):
        self.assertEqual(_compute_label(1.5, 40.0, 3.0), "LIQUIDATION_IMMINENT")

    def test_warning_hf(self):
        # HF=1.2 < 1.3 → WARNING
        self.assertEqual(_compute_label(1.2, 25.0, None), "WARNING")

    def test_warning_ttl_14(self):
        # HF=2.0 but ttl=14 → WARNING
        self.assertEqual(_compute_label(2.0, 40.0, 14.0), "WARNING")

    def test_monitor_hf(self):
        # HF=1.4 < 1.6 → MONITOR
        self.assertEqual(_compute_label(1.4, 25.0, None), "MONITOR")

    def test_monitor_low_margin(self):
        # HF=2.0 but margin=10 < 15 → MONITOR
        self.assertEqual(_compute_label(2.0, 10.0, None), "MONITOR")

    def test_safe_hf(self):
        # HF=2.0 < 2.5, margin=25 < 30 → SAFE
        self.assertEqual(_compute_label(2.0, 25.0, None), "SAFE")

    def test_safe_margin(self):
        # HF=3.0 but margin=20 < 30 → SAFE
        self.assertEqual(_compute_label(3.0, 20.0, None), "SAFE")

    def test_fortress_position(self):
        # HF=3.0 >= 2.5, margin=40 >= 30 → FORTRESS_POSITION
        self.assertEqual(_compute_label(3.0, 40.0, None), "FORTRESS_POSITION")

    def test_fortress_large_hf(self):
        self.assertEqual(_compute_label(10.0, 80.0, None), "FORTRESS_POSITION")

    def test_liquidation_imminent_trumps_all(self):
        # Even with good margin, low HF → LIQUIDATION_IMMINENT
        self.assertEqual(_compute_label(0.5, 90.0, None), "LIQUIDATION_IMMINENT")

    def test_ttl_just_above_3_not_imminent(self):
        # ttl=4 > 3 days, HF=1.5 → not LIQUIDATION_IMMINENT
        label = _compute_label(1.5, 25.0, 4.0)
        self.assertNotEqual(label, "LIQUIDATION_IMMINENT")

    def test_ttl_just_above_14_not_warning(self):
        # ttl=15 > 14, HF=2.0 → not WARNING from TTL alone
        label = _compute_label(2.0, 40.0, 15.0)
        self.assertNotEqual(label, "WARNING")


# ===========================================================================
# 7. ProtocolDeFiIsolatedMarginRiskAnalyzer.analyze() — structure
# ===========================================================================

class TestAnalyzerStructure(unittest.TestCase):

    def _default(self, **kwargs):
        params = dict(
            position_size_usd=100_000.0,
            collateral_value_usd=150_000.0,
            borrow_value_usd=80_000.0,
            oracle_price_usd=2_000.0,
            liquidation_ltv=0.825,
            health_factor=1.55,
            days_to_liquidation_at_trend=None,
            collateral_volatility_30d_pct=25.0,
        )
        params.update(kwargs)
        return ProtocolDeFiIsolatedMarginRiskAnalyzer(**params).analyze()

    def test_has_all_required_keys(self):
        result = self._default()
        for key in [
            "health_score", "margin_of_safety_pct", "liquidation_price_usd",
            "time_to_liquidation_days", "label", "current_ltv_pct", "warnings",
        ]:
            self.assertIn(key, result)

    def test_schema_version(self):
        self.assertEqual(self._default()["schema_version"], 1)

    def test_mp_tag(self):
        self.assertEqual(self._default()["mp_tag"], "MP-1035")

    def test_source(self):
        self.assertIn("isolated_margin", self._default()["source"])

    def test_health_score_in_range(self):
        result = self._default()
        self.assertGreaterEqual(result["health_score"], 0.0)
        self.assertLessEqual(result["health_score"], 100.0)

    def test_label_valid_value(self):
        valid = {"FORTRESS_POSITION", "SAFE", "MONITOR", "WARNING", "LIQUIDATION_IMMINENT"}
        self.assertIn(self._default()["label"], valid)

    def test_warnings_is_list(self):
        self.assertIsInstance(self._default()["warnings"], list)

    def test_no_warnings_for_valid_inputs(self):
        self.assertEqual(len(self._default()["warnings"]), 0)

    def test_current_ltv_not_none(self):
        result = self._default()
        self.assertIsNotNone(result["current_ltv_pct"])

    def test_liquidation_price_not_none(self):
        self.assertIsNotNone(self._default()["liquidation_price_usd"])

    def test_margin_of_safety_not_none(self):
        self.assertIsNotNone(self._default()["margin_of_safety_pct"])

    def test_result_is_json_serializable(self):
        json.dumps(self._default())  # must not raise

    def test_timestamp_present(self):
        self.assertIn("timestamp_utc", self._default())


# ===========================================================================
# 8. Analyzer — specific value checks
# ===========================================================================

class TestAnalyzerValues(unittest.TestCase):

    def test_liquidation_price_value(self):
        # liq = 80000 * 2000 / (150000 * 0.825)
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            collateral_value_usd=150_000, borrow_value_usd=80_000,
            oracle_price_usd=2_000, liquidation_ltv=0.825,
        ).analyze()
        expected = 80_000 * 2_000 / (150_000 * 0.825)
        self.assertAlmostEqual(result["liquidation_price_usd"], expected, places=2)

    def test_margin_of_safety_value(self):
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            collateral_value_usd=150_000, borrow_value_usd=80_000,
            oracle_price_usd=2_000, liquidation_ltv=0.825,
        ).analyze()
        liq = 80_000 * 2_000 / (150_000 * 0.825)
        expected_margin = (2_000 - liq) / 2_000 * 100
        self.assertAlmostEqual(result["margin_of_safety_pct"], expected_margin, places=2)

    def test_current_ltv_pct(self):
        # ltv = 80000/150000 * 100 = 53.33%
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            collateral_value_usd=150_000, borrow_value_usd=80_000,
        ).analyze()
        self.assertAlmostEqual(result["current_ltv_pct"], 80_000 / 150_000 * 100, places=2)

    def test_health_factor_1_is_liquidation_imminent(self):
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            health_factor=1.0,
            days_to_liquidation_at_trend=None,
        ).analyze()
        # HF=1.0 < LIQUIDATION_IMMINENT_HF=1.1 → LIQUIDATION_IMMINENT
        self.assertEqual(result["label"], "LIQUIDATION_IMMINENT")

    def test_health_factor_3_fortress(self):
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            collateral_value_usd=300_000, borrow_value_usd=50_000,
            oracle_price_usd=2_000, liquidation_ltv=0.825,
            health_factor=3.5,
        ).analyze()
        self.assertEqual(result["label"], "FORTRESS_POSITION")

    def test_ttl_none_when_not_provided(self):
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            health_factor=2.0,
            days_to_liquidation_at_trend=None,
        ).analyze()
        self.assertIsNone(result["time_to_liquidation_days"])

    def test_ttl_passed_through(self):
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            health_factor=2.0,
            days_to_liquidation_at_trend=45.0,
        ).analyze()
        self.assertAlmostEqual(result["time_to_liquidation_days"], 45.0, places=1)

    def test_zero_borrow_no_liquidation_risk(self):
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            collateral_value_usd=100_000, borrow_value_usd=0.0,
            oracle_price_usd=2_000, liquidation_ltv=0.825,
            health_factor=999.0,
        ).analyze()
        self.assertEqual(result["label"], "FORTRESS_POSITION")

    def test_high_volatility_reduces_health_score(self):
        low = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            health_factor=2.0, collateral_volatility_30d_pct=10.0
        ).analyze()
        high = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            health_factor=2.0, collateral_volatility_30d_pct=60.0
        ).analyze()
        self.assertGreater(low["health_score"], high["health_score"])


# ===========================================================================
# 9. analyze_isolated_margin convenience wrapper
# ===========================================================================

class TestAnalyzeIsolatedMarginWrapper(unittest.TestCase):

    def test_returns_dict(self):
        self.assertIsInstance(analyze_isolated_margin(), dict)

    def test_matches_class_output(self):
        class_result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            health_factor=1.8, collateral_value_usd=200_000
        ).analyze()
        fn_result = analyze_isolated_margin(
            health_factor=1.8, collateral_value_usd=200_000
        )
        self.assertAlmostEqual(
            class_result["health_score"], fn_result["health_score"], places=4
        )

    def test_default_result_has_label(self):
        self.assertIn("label", analyze_isolated_margin())

    def test_various_health_factors(self):
        for hf in [0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 5.0]:
            result = analyze_isolated_margin(health_factor=hf)
            self.assertIn("label", result)


# ===========================================================================
# 10. Ring-buffer and persistence
# ===========================================================================

class TestRingBufferAndPersistence(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)

    def test_write_log_creates_file(self):
        log_path = write_log(analyze_isolated_margin(), self.data_dir)
        self.assertTrue(log_path.exists())

    def test_write_log_contains_one_entry(self):
        log_path = write_log(analyze_isolated_margin(), self.data_dir)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_write_log_appends(self):
        for _ in range(5):
            write_log(analyze_isolated_margin(), self.data_dir)
        log_path = self.data_dir / LOG_FILENAME
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap_enforced(self):
        for _ in range(RING_BUFFER_CAP + 10):
            write_log(analyze_isolated_margin(), self.data_dir)
        log_path = self.data_dir / LOG_FILENAME
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), RING_BUFFER_CAP)

    def test_atomic_write_valid_json(self):
        path = self.data_dir / "test_atomic.json"
        _atomic_write(path, [{"health": 1.5}])
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["health"], 1.5)

    def test_load_json_list_missing_returns_empty(self):
        self.assertEqual(_load_json_list(self.data_dir / "no_file.json"), [])

    def test_load_json_list_invalid_returns_empty(self):
        bad = self.data_dir / "bad.json"
        bad.write_text("GARBAGE")
        self.assertEqual(_load_json_list(bad), [])

    def test_ring_buffer_keeps_latest_entries(self):
        for i in range(RING_BUFFER_CAP + 5):
            result = analyze_isolated_margin(health_factor=float(i) + 1.0)
            result["_seq"] = i
            write_log(result, self.data_dir)
        log_path = self.data_dir / LOG_FILENAME
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["_seq"], 5)  # oldest kept is index 5


# ===========================================================================
# 11. Constants
# ===========================================================================

class TestConstants(unittest.TestCase):

    def test_ring_buffer_cap(self):
        self.assertEqual(RING_BUFFER_CAP, 100)

    def test_log_filename(self):
        self.assertEqual(LOG_FILENAME, "isolated_margin_risk_log.json")

    def test_liquidation_imminent_hf(self):
        self.assertAlmostEqual(LIQUIDATION_IMMINENT_HF, 1.1, places=4)

    def test_liquidation_imminent_days(self):
        self.assertEqual(LIQUIDATION_IMMINENT_DAYS, 3)

    def test_warning_hf(self):
        self.assertAlmostEqual(WARNING_HF, 1.3, places=4)

    def test_warning_days(self):
        self.assertEqual(WARNING_DAYS, 14)

    def test_monitor_hf(self):
        self.assertAlmostEqual(MONITOR_HF, 1.6, places=4)

    def test_safe_hf(self):
        self.assertAlmostEqual(SAFE_HF, 2.5, places=4)


# ===========================================================================
# 12. Edge cases and boundary conditions
# ===========================================================================

class TestEdgeCasesAndBoundaries(unittest.TestCase):

    def test_zero_collateral_produces_warning(self):
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            collateral_value_usd=0.0, borrow_value_usd=50_000,
            oracle_price_usd=2_000, liquidation_ltv=0.825,
        ).analyze()
        self.assertGreater(len(result["warnings"]), 0)

    def test_zero_oracle_price_produces_warning(self):
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            collateral_value_usd=100_000, oracle_price_usd=0.0,
        ).analyze()
        self.assertGreater(len(result["warnings"]), 0)

    def test_health_factor_negative_does_not_crash(self):
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(health_factor=-1.0).analyze()
        self.assertEqual(result["label"], "LIQUIDATION_IMMINENT")

    def test_very_high_health_factor(self):
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            health_factor=100.0,
            collateral_value_usd=1_000_000,
            borrow_value_usd=10_000,
            oracle_price_usd=2_000,
            liquidation_ltv=0.825,
        ).analyze()
        self.assertEqual(result["label"], "FORTRESS_POSITION")
        self.assertAlmostEqual(result["health_score"], 100.0, places=1)

    def test_result_not_none_for_degenerate_inputs(self):
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            collateral_value_usd=0.0, borrow_value_usd=0.0,
            oracle_price_usd=0.0, liquidation_ltv=0.0,
        ).analyze()
        self.assertIsNotNone(result)
        self.assertIn("label", result)

    def test_very_low_volatility(self):
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            health_factor=2.0, collateral_volatility_30d_pct=0.0
        ).analyze()
        self.assertGreaterEqual(result["health_score"], 0.0)

    def test_extremely_high_volatility_doesnt_crash(self):
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            health_factor=2.0, collateral_volatility_30d_pct=500.0
        ).analyze()
        self.assertGreaterEqual(result["health_score"], 0.0)

    def test_collateral_amount_in_result(self):
        result = ProtocolDeFiIsolatedMarginRiskAnalyzer(
            collateral_value_usd=200_000, oracle_price_usd=2_000
        ).analyze()
        # collateral_amount = 200000/2000 = 100 tokens
        self.assertAlmostEqual(result["collateral_amount"], 100.0, places=4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
