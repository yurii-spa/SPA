"""
Tests for MP-1033: ProtocolDeFiLiquidationCascadeRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_liquidation_cascade_risk_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.protocol_defi_liquidation_cascade_risk_analyzer import (
    ProtocolDeFiLiquidationCascadeRiskAnalyzer,
    _compute_cascade_risk_score,
    _compute_estimated_liquidation_volume_usd,
    _compute_market_impact_pct,
    _compute_recovery_time_days,
    _cascade_label,
    _compute_flags,
    _append_log,
    DATA_FILE,
    MAX_ENTRIES,
    _LABEL_THRESHOLDS,
    _MARKET_IMPACT_COEFF,
)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _eth_scenario(**kw):
    base = dict(
        collateral_asset="ETH",
        ltv_ratio=0.65,
        liquidation_threshold=0.80,
        total_collateral_usd=5_000_000_000,
        daily_volume_usd=10_000_000_000,
        concentrated_positions_pct=20.0,
        price_drop_trigger_pct=15.0,
    )
    base.update(kw)
    return base


def _risky_scenario(**kw):
    base = dict(
        collateral_asset="LUNA",
        ltv_ratio=0.78,
        liquidation_threshold=0.80,
        total_collateral_usd=18_000_000_000,
        daily_volume_usd=300_000_000,
        concentrated_positions_pct=75.0,
        price_drop_trigger_pct=40.0,
    )
    base.update(kw)
    return base


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_cascade_risk_score
# ─────────────────────────────────────────────────────────────────

class TestComputeCascadeRiskScore(unittest.TestCase):

    def test_returns_float(self):
        s = _compute_cascade_risk_score(0.65, 0.80, 15.0, 20.0, 5e9, 10e9)
        self.assertIsInstance(s, float)

    def test_score_min_0(self):
        s = _compute_cascade_risk_score(0.0, 0.80, 0.0, 0.0, 0.0, 1e12)
        self.assertGreaterEqual(s, 0.0)

    def test_score_max_100(self):
        s = _compute_cascade_risk_score(0.799, 0.80, 100.0, 100.0, 1e15, 1.0)
        self.assertLessEqual(s, 100.0)

    def test_high_ltv_proximity_raises_score(self):
        # LTV just below threshold → high score
        s_near = _compute_cascade_risk_score(0.79, 0.80, 10.0, 20.0, 1e9, 5e9)
        s_far = _compute_cascade_risk_score(0.30, 0.80, 10.0, 20.0, 1e9, 5e9)
        self.assertGreater(s_near, s_far)

    def test_larger_pdrop_increases_score(self):
        s_big = _compute_cascade_risk_score(0.65, 0.80, 50.0, 20.0, 1e9, 5e9)
        s_small = _compute_cascade_risk_score(0.65, 0.80, 5.0, 20.0, 1e9, 5e9)
        self.assertGreater(s_big, s_small)

    def test_pdrop_50_adds_25(self):
        s_high = _compute_cascade_risk_score(0.0, 0.80, 50.0, 0.0, 0.0, 1.0)
        s_none = _compute_cascade_risk_score(0.0, 0.80, 0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(s_high - s_none, 25.0, places=3)

    def test_pdrop_30_adds_18(self):
        s_high = _compute_cascade_risk_score(0.0, 0.80, 30.0, 0.0, 0.0, 1.0)
        s_none = _compute_cascade_risk_score(0.0, 0.80, 0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(s_high - s_none, 18.0, places=3)

    def test_pdrop_15_adds_12(self):
        s_high = _compute_cascade_risk_score(0.0, 0.80, 15.0, 0.0, 0.0, 1.0)
        s_none = _compute_cascade_risk_score(0.0, 0.80, 0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(s_high - s_none, 12.0, places=3)

    def test_pdrop_5_adds_6(self):
        s_high = _compute_cascade_risk_score(0.0, 0.80, 5.0, 0.0, 0.0, 1.0)
        s_none = _compute_cascade_risk_score(0.0, 0.80, 0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(s_high - s_none, 6.0, places=3)

    def test_pdrop_1_adds_2(self):
        s_high = _compute_cascade_risk_score(0.0, 0.80, 1.0, 0.0, 0.0, 1.0)
        s_none = _compute_cascade_risk_score(0.0, 0.80, 0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(s_high - s_none, 2.0, places=3)

    def test_concentration_adds_up_to_20(self):
        s_full_conc = _compute_cascade_risk_score(0.0, 0.80, 0.0, 100.0, 0.0, 1.0)
        s_no_conc = _compute_cascade_risk_score(0.0, 0.80, 0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(s_full_conc - s_no_conc, 20.0, places=3)

    def test_liquidity_ratio_5x_adds_20(self):
        # collateral 5x daily vol → liquidity_ratio = 5
        s = _compute_cascade_risk_score(0.0, 0.80, 0.0, 0.0, 5_000_000.0, 1_000_000.0)
        s0 = _compute_cascade_risk_score(0.0, 0.80, 0.0, 0.0, 0.0, 1_000_000.0)
        self.assertAlmostEqual(s - s0, 20.0, places=3)

    def test_liquidity_ratio_2x_adds_12(self):
        s = _compute_cascade_risk_score(0.0, 0.80, 0.0, 0.0, 2_000_000.0, 1_000_000.0)
        s0 = _compute_cascade_risk_score(0.0, 0.80, 0.0, 0.0, 0.0, 1_000_000.0)
        self.assertAlmostEqual(s - s0, 12.0, places=3)

    def test_liquidity_ratio_1x_adds_6(self):
        s = _compute_cascade_risk_score(0.0, 0.80, 0.0, 0.0, 1_000_000.0, 1_000_000.0)
        s0 = _compute_cascade_risk_score(0.0, 0.80, 0.0, 0.0, 0.0, 1_000_000.0)
        self.assertAlmostEqual(s - s0, 6.0, places=3)

    def test_risky_scenario_high_score(self):
        s = _compute_cascade_risk_score(0.78, 0.80, 40.0, 75.0, 18e9, 300e6)
        self.assertGreater(s, 60.0)


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_estimated_liquidation_volume_usd
# ─────────────────────────────────────────────────────────────────

class TestComputeEstimatedLiquidationVolume(unittest.TestCase):

    def test_returns_float(self):
        v = _compute_estimated_liquidation_volume_usd(1e9, 0.65, 0.80, 15.0, 20.0)
        self.assertIsInstance(v, float)

    def test_zero_collateral_returns_zero(self):
        v = _compute_estimated_liquidation_volume_usd(0.0, 0.65, 0.80, 15.0, 20.0)
        self.assertEqual(v, 0.0)

    def test_zero_price_drop_no_liquidation(self):
        v = _compute_estimated_liquidation_volume_usd(1e9, 0.65, 0.80, 0.0, 20.0)
        self.assertEqual(v, 0.0)

    def test_ltv_below_threshold_zero_liquidations(self):
        # LTV 0.5, threshold 0.80, small drop → stays below threshold
        v = _compute_estimated_liquidation_volume_usd(1e9, 0.50, 0.80, 5.0, 0.0)
        self.assertEqual(v, 0.0)

    def test_100pct_drop_liquidates_all(self):
        v = _compute_estimated_liquidation_volume_usd(1e9, 0.65, 0.80, 100.0, 0.0)
        self.assertAlmostEqual(v, 1e9, delta=1.0)

    def test_larger_drop_triggers_more_liquidation(self):
        v_big = _compute_estimated_liquidation_volume_usd(1e9, 0.75, 0.80, 30.0, 20.0)
        v_small = _compute_estimated_liquidation_volume_usd(1e9, 0.75, 0.80, 10.0, 20.0)
        self.assertGreaterEqual(v_big, v_small)

    def test_concentration_amplifies_volume(self):
        v_conc = _compute_estimated_liquidation_volume_usd(1e9, 0.75, 0.80, 20.0, 80.0)
        v_disp = _compute_estimated_liquidation_volume_usd(1e9, 0.75, 0.80, 20.0, 10.0)
        self.assertGreaterEqual(v_conc, v_disp)

    def test_result_non_negative(self):
        v = _compute_estimated_liquidation_volume_usd(1e9, 0.65, 0.80, 10.0, 20.0)
        self.assertGreaterEqual(v, 0.0)

    def test_result_max_is_collateral(self):
        v = _compute_estimated_liquidation_volume_usd(1e9, 0.79, 0.80, 50.0, 90.0)
        self.assertLessEqual(v, 1e9)


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_market_impact_pct
# ─────────────────────────────────────────────────────────────────

class TestComputeMarketImpactPct(unittest.TestCase):

    def test_returns_float(self):
        m = _compute_market_impact_pct(1e8, 1e9)
        self.assertIsInstance(m, float)

    def test_zero_liquidation_zero_impact(self):
        m = _compute_market_impact_pct(0.0, 1e9)
        self.assertEqual(m, 0.0)

    def test_impact_range_0_100(self):
        m = _compute_market_impact_pct(1e12, 1.0)
        self.assertLessEqual(m, 100.0)
        self.assertGreaterEqual(m, 0.0)

    def test_larger_liquidation_higher_impact(self):
        m_big = _compute_market_impact_pct(1e9, 1e9)
        m_small = _compute_market_impact_pct(1e7, 1e9)
        self.assertGreater(m_big, m_small)

    def test_larger_volume_lower_impact(self):
        m_thin = _compute_market_impact_pct(1e8, 1e8)
        m_deep = _compute_market_impact_pct(1e8, 1e10)
        self.assertGreater(m_thin, m_deep)

    def test_rounded_to_4_places(self):
        m = _compute_market_impact_pct(5e8, 2e9)
        self.assertEqual(m, round(m, 4))

    def test_square_root_model_used(self):
        # ratio = 0.25, so sqrt(0.25) = 0.5; impact = coeff * 0.5 * 100
        m = _compute_market_impact_pct(2.5e8, 1e9)
        expected = round(_MARKET_IMPACT_COEFF * (0.25 ** 0.5) * 100.0, 4)
        self.assertAlmostEqual(m, expected, places=4)


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_recovery_time_days
# ─────────────────────────────────────────────────────────────────

class TestComputeRecoveryTimeDays(unittest.TestCase):

    def test_returns_int(self):
        d = _compute_recovery_time_days(50.0, 5.0, 1e9, 1e9)
        self.assertIsInstance(d, int)

    def test_zero_score_zero_days(self):
        d = _compute_recovery_time_days(0.0, 0.0, 1e9, 0.0)
        self.assertEqual(d, 0)

    def test_higher_score_longer_recovery(self):
        d_high = _compute_recovery_time_days(80.0, 5.0, 1e9, 1e9)
        d_low = _compute_recovery_time_days(20.0, 5.0, 1e9, 1e9)
        self.assertGreater(d_high, d_low)

    def test_higher_impact_longer_recovery(self):
        d_high = _compute_recovery_time_days(50.0, 30.0, 1e9, 1e9)
        d_low = _compute_recovery_time_days(50.0, 2.0, 1e9, 1e9)
        self.assertGreater(d_high, d_low)

    def test_non_negative(self):
        d = _compute_recovery_time_days(0.0, 0.0, 0.0, 0.0)
        self.assertGreaterEqual(d, 0)

    def test_large_liquidity_ratio_longer_recovery(self):
        d_illiq = _compute_recovery_time_days(50.0, 5.0, 1.0, 1e12)
        d_liq = _compute_recovery_time_days(50.0, 5.0, 1e9, 1e9)
        self.assertGreaterEqual(d_illiq, d_liq)


# ─────────────────────────────────────────────────────────────────
# Tests: _cascade_label
# ─────────────────────────────────────────────────────────────────

class TestCascadeLabel(unittest.TestCase):

    def test_death_spiral_at_85(self):
        self.assertEqual(_cascade_label(85.0), "DEATH_SPIRAL")

    def test_death_spiral_at_100(self):
        self.assertEqual(_cascade_label(100.0), "DEATH_SPIRAL")

    def test_high_cascade_at_65(self):
        self.assertEqual(_cascade_label(65.0), "HIGH_CASCADE")

    def test_high_cascade_at_84(self):
        self.assertEqual(_cascade_label(84.9), "HIGH_CASCADE")

    def test_moderate_cascade_at_45(self):
        self.assertEqual(_cascade_label(45.0), "MODERATE_CASCADE")

    def test_moderate_cascade_at_64(self):
        self.assertEqual(_cascade_label(64.9), "MODERATE_CASCADE")

    def test_low_cascade_at_25(self):
        self.assertEqual(_cascade_label(25.0), "LOW_CASCADE")

    def test_low_cascade_at_44(self):
        self.assertEqual(_cascade_label(44.9), "LOW_CASCADE")

    def test_stable_at_0(self):
        self.assertEqual(_cascade_label(0.0), "STABLE")

    def test_stable_at_24(self):
        self.assertEqual(_cascade_label(24.9), "STABLE")

    def test_boundary_85_exactly(self):
        self.assertEqual(_cascade_label(85.0), "DEATH_SPIRAL")

    def test_boundary_just_below_85(self):
        self.assertEqual(_cascade_label(84.999), "HIGH_CASCADE")


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_flags
# ─────────────────────────────────────────────────────────────────

class TestComputeFlags(unittest.TestCase):

    def test_no_flags_safe_scenario(self):
        flags = _compute_flags(0.50, 0.80, 10.0, 20.0, 1e9, 5e9)
        self.assertEqual(flags, [])

    def test_near_liquidation_flag(self):
        # buffer = (0.80 - 0.78) / 0.80 = 2.5% < 10%
        flags = _compute_flags(0.78, 0.80, 10.0, 20.0, 1e9, 5e9)
        self.assertIn("NEAR_LIQUIDATION_THRESHOLD", flags)

    def test_severe_price_drop_flag(self):
        flags = _compute_flags(0.50, 0.80, 35.0, 20.0, 1e9, 5e9)
        self.assertIn("SEVERE_PRICE_DROP_SCENARIO", flags)

    def test_highly_concentrated_flag(self):
        flags = _compute_flags(0.50, 0.80, 10.0, 65.0, 1e9, 5e9)
        self.assertIn("HIGHLY_CONCENTRATED_POSITIONS", flags)

    def test_illiquid_market_flag(self):
        # collateral 3x daily vol → illiquid
        flags = _compute_flags(0.50, 0.80, 10.0, 20.0, 3e9, 1e9)
        self.assertIn("ILLIQUID_MARKET", flags)

    def test_high_portfolio_ltv_flag(self):
        flags = _compute_flags(0.76, 0.80, 10.0, 20.0, 1e9, 5e9)
        self.assertIn("HIGH_PORTFOLIO_LTV", flags)

    def test_critical_ltv_buffer_flag(self):
        # ltv/threshold = 0.76/0.80 = 0.95 → critical
        flags = _compute_flags(0.76, 0.80, 10.0, 20.0, 1e9, 5e9)
        self.assertIn("CRITICAL_LTV_BUFFER", flags)

    def test_returns_list(self):
        flags = _compute_flags(0.65, 0.80, 15.0, 25.0, 1e9, 5e9)
        self.assertIsInstance(flags, list)

    def test_multiple_flags_possible(self):
        flags = _compute_flags(0.79, 0.80, 50.0, 70.0, 20e9, 1e9)
        self.assertGreater(len(flags), 2)


# ─────────────────────────────────────────────────────────────────
# Tests: ProtocolDeFiLiquidationCascadeRiskAnalyzer.analyze()
# ─────────────────────────────────────────────────────────────────

class TestProtocolDeFiLiquidationCascadeRiskAnalyzer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiLiquidationCascadeRiskAnalyzer()

    def _analyze(self, **kw):
        defaults = _eth_scenario()
        defaults.update(kw)
        defaults["data_dir"] = self.tmpdir
        return self.analyzer.analyze(**defaults)

    def test_returns_dict(self):
        r = self._analyze()
        self.assertIsInstance(r, dict)

    def test_all_keys_present(self):
        r = self._analyze()
        expected = [
            "collateral_asset", "ltv_ratio", "liquidation_threshold",
            "total_collateral_usd", "daily_volume_usd",
            "concentrated_positions_pct", "price_drop_trigger_pct",
            "cascade_risk_score", "estimated_liquidation_volume_usd",
            "market_impact_pct", "recovery_time_days",
            "label", "flags", "timestamp",
        ]
        for k in expected:
            self.assertIn(k, r, msg=f"Missing key: {k}")

    def test_cascade_score_in_range(self):
        r = self._analyze()
        self.assertGreaterEqual(r["cascade_risk_score"], 0.0)
        self.assertLessEqual(r["cascade_risk_score"], 100.0)

    def test_liquidation_volume_non_negative(self):
        r = self._analyze()
        self.assertGreaterEqual(r["estimated_liquidation_volume_usd"], 0.0)

    def test_market_impact_in_range(self):
        r = self._analyze()
        self.assertGreaterEqual(r["market_impact_pct"], 0.0)
        self.assertLessEqual(r["market_impact_pct"], 100.0)

    def test_recovery_time_non_negative(self):
        r = self._analyze()
        self.assertGreaterEqual(r["recovery_time_days"], 0)

    def test_recovery_time_is_int(self):
        r = self._analyze()
        self.assertIsInstance(r["recovery_time_days"], int)

    def test_label_is_valid(self):
        r = self._analyze()
        valid = {"STABLE", "LOW_CASCADE", "MODERATE_CASCADE",
                 "HIGH_CASCADE", "DEATH_SPIRAL"}
        self.assertIn(r["label"], valid)

    def test_flags_is_list(self):
        r = self._analyze()
        self.assertIsInstance(r["flags"], list)

    def test_timestamp_is_float(self):
        r = self._analyze()
        self.assertIsInstance(r["timestamp"], float)

    def test_collateral_asset_preserved(self):
        r = self._analyze(collateral_asset="wBTC")
        self.assertEqual(r["collateral_asset"], "wBTC")

    def test_ltv_clamped_to_0_1(self):
        r = self._analyze(ltv_ratio=1.5)
        self.assertLessEqual(r["ltv_ratio"], 1.0)

    def test_ltv_threshold_gte_ltv(self):
        # If user passes threshold < ltv, it should be clamped to ltv
        r = self._analyze(ltv_ratio=0.85, liquidation_threshold=0.75)
        self.assertGreaterEqual(r["liquidation_threshold"], r["ltv_ratio"])

    def test_pdrop_clamped_to_100(self):
        r = self._analyze(price_drop_trigger_pct=150.0)
        self.assertEqual(r["price_drop_trigger_pct"], 100.0)

    def test_concentration_clamped_to_100(self):
        r = self._analyze(concentrated_positions_pct=120.0)
        self.assertEqual(r["concentrated_positions_pct"], 100.0)

    def test_zero_collateral_zero_liquidation(self):
        r = self._analyze(total_collateral_usd=0.0)
        self.assertEqual(r["estimated_liquidation_volume_usd"], 0.0)

    def test_zero_pdrop_no_liquidation(self):
        r = self._analyze(price_drop_trigger_pct=0.0)
        self.assertEqual(r["estimated_liquidation_volume_usd"], 0.0)

    def test_death_spiral_scenario(self):
        r = self.analyzer.analyze(
            **{**_risky_scenario(), "data_dir": self.tmpdir}
        )
        self.assertIn(r["label"], {"DEATH_SPIRAL", "HIGH_CASCADE"})

    def test_stable_safe_scenario(self):
        r = self._analyze(
            ltv_ratio=0.30,
            liquidation_threshold=0.80,
            price_drop_trigger_pct=2.0,
            concentrated_positions_pct=5.0,
            total_collateral_usd=1e8,
            daily_volume_usd=1e10,
        )
        self.assertIn(r["label"], {"STABLE", "LOW_CASCADE"})

    def test_log_file_created(self):
        self._analyze()
        log_path = Path(self.tmpdir) / "liquidation_cascade_risk_log.json"
        self.assertTrue(log_path.exists())

    def test_log_file_valid_json_list(self):
        self._analyze()
        log_path = Path(self.tmpdir) / "liquidation_cascade_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_contains_entry(self):
        self._analyze()
        log_path = Path(self.tmpdir) / "liquidation_cascade_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_accumulates(self):
        for _ in range(5):
            self._analyze()
        log_path = Path(self.tmpdir) / "liquidation_cascade_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        for _ in range(MAX_ENTRIES + 15):
            self._analyze()
        log_path = Path(self.tmpdir) / "liquidation_cascade_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), MAX_ENTRIES)

    def test_negative_collateral_clamped(self):
        r = self._analyze(total_collateral_usd=-1000.0)
        self.assertEqual(r["total_collateral_usd"], 0.0)

    def test_negative_ltv_clamped(self):
        r = self._analyze(ltv_ratio=-0.5)
        self.assertEqual(r["ltv_ratio"], 0.0)

    def test_score_rounded_to_4_places(self):
        r = self._analyze()
        s = r["cascade_risk_score"]
        self.assertEqual(s, round(s, 4))

    def test_market_impact_rounded_to_4_places(self):
        r = self._analyze()
        m = r["market_impact_pct"]
        self.assertEqual(m, round(m, 4))


# ─────────────────────────────────────────────────────────────────
# Tests: _append_log
# ─────────────────────────────────────────────────────────────────

class TestAppendLog(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_creates_file_if_absent(self):
        _append_log({"test": 1}, data_dir=self.tmpdir)
        log_path = Path(self.tmpdir) / "liquidation_cascade_risk_log.json"
        self.assertTrue(log_path.exists())

    def test_file_contains_single_entry(self):
        _append_log({"x": 99}, data_dir=self.tmpdir)
        log_path = Path(self.tmpdir) / "liquidation_cascade_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["x"], 99)

    def test_appends_multiple_entries(self):
        for i in range(7):
            _append_log({"i": i}, data_dir=self.tmpdir)
        log_path = Path(self.tmpdir) / "liquidation_cascade_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 7)

    def test_ring_buffer_at_max(self):
        for i in range(MAX_ENTRIES + 25):
            _append_log({"i": i}, data_dir=self.tmpdir)
        log_path = Path(self.tmpdir) / "liquidation_cascade_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        for i in range(MAX_ENTRIES + 5):
            _append_log({"i": i}, data_dir=self.tmpdir)
        log_path = Path(self.tmpdir) / "liquidation_cascade_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], MAX_ENTRIES + 4)

    def test_corrupt_file_resets(self):
        log_path = Path(self.tmpdir) / "liquidation_cascade_risk_log.json"
        log_path.write_text("CORRUPT", encoding="utf-8")
        _append_log({"new": True}, data_dir=self.tmpdir)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertTrue(data[0]["new"])

    def test_tmp_file_not_left_behind(self):
        _append_log({"t": 1}, data_dir=self.tmpdir)
        tmp_files = list(Path(self.tmpdir).glob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_non_list_file_resets(self):
        log_path = Path(self.tmpdir) / "liquidation_cascade_risk_log.json"
        log_path.write_text('{"key": "value"}', encoding="utf-8")
        _append_log({"new": True}, data_dir=self.tmpdir)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)


# ─────────────────────────────────────────────────────────────────
# Tests: constants & module structure
# ─────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):

    def test_max_entries_is_100(self):
        self.assertEqual(MAX_ENTRIES, 100)

    def test_data_file_is_path(self):
        self.assertIsInstance(DATA_FILE, Path)

    def test_label_thresholds_descending(self):
        thresholds = [t for t, _ in _LABEL_THRESHOLDS]
        self.assertEqual(thresholds, sorted(thresholds, reverse=True))

    def test_all_five_labels_present(self):
        labels = {lbl for _, lbl in _LABEL_THRESHOLDS}
        expected = {"DEATH_SPIRAL", "HIGH_CASCADE", "MODERATE_CASCADE",
                    "LOW_CASCADE", "STABLE"}
        self.assertEqual(labels, expected)

    def test_market_impact_coeff_positive(self):
        self.assertGreater(_MARKET_IMPACT_COEFF, 0.0)


if __name__ == "__main__":
    unittest.main()
