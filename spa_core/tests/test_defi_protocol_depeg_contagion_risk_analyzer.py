"""
Tests for MP-1032: DeFiProtocolDepegContagionRiskAnalyzer
Run: python3 -m unittest spa_core.tests.test_defi_protocol_depeg_contagion_risk_analyzer -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics.defi_protocol_depeg_contagion_risk_analyzer import (
    DeFiProtocolDepegContagionRiskAnalyzer,
    _compute_contagion_spread_score,
    _compute_direct_loss_usd,
    _compute_cascading_loss_multiplier,
    _compute_affected_protocols_estimate,
    _contagion_label,
    _compute_flags,
    _append_log,
    DATA_FILE,
    MAX_ENTRIES,
    ASSET_TYPE_BASE_SPREAD,
    ASSET_TYPE_CASCADE_MULTIPLIER,
)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _stablecoin_scenario(**kw):
    base = dict(
        asset_type="stablecoin",
        collateral_usage_pct=30.0,
        depeg_magnitude_pct=5.0,
        protocol_interconnection_score=0.5,
        insurance_coverage_pct=20.0,
        tvl_exposed_usd=10_000_000_000,
        asset_name="USDC",
    )
    base.update(kw)
    return base


def _lst_scenario(**kw):
    base = dict(
        asset_type="lst",
        collateral_usage_pct=20.0,
        depeg_magnitude_pct=3.0,
        protocol_interconnection_score=0.4,
        insurance_coverage_pct=15.0,
        tvl_exposed_usd=5_000_000_000,
        asset_name="stETH",
    )
    base.update(kw)
    return base


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_contagion_spread_score
# ─────────────────────────────────────────────────────────────────

class TestComputeContagionSpreadScore(unittest.TestCase):

    def test_returns_float(self):
        s = _compute_contagion_spread_score("stablecoin", 30.0, 5.0, 0.5, 20.0)
        self.assertIsInstance(s, float)

    def test_score_range_min(self):
        s = _compute_contagion_spread_score("stablecoin", 0.0, 0.0, 0.0, 100.0)
        self.assertGreaterEqual(s, 0.0)

    def test_score_range_max(self):
        s = _compute_contagion_spread_score("stablecoin", 100.0, 100.0, 1.0, 0.0)
        self.assertLessEqual(s, 100.0)

    def test_stablecoin_higher_than_wrapped_same_inputs(self):
        s_stable = _compute_contagion_spread_score("stablecoin", 30.0, 5.0, 0.5, 0.0)
        s_wrapped = _compute_contagion_spread_score("wrapped", 30.0, 5.0, 0.5, 0.0)
        self.assertGreater(s_stable, s_wrapped)

    def test_lst_lower_than_stablecoin_base(self):
        s_stable = _compute_contagion_spread_score("stablecoin", 0.0, 0.0, 0.0, 0.0)
        s_lst = _compute_contagion_spread_score("lst", 0.0, 0.0, 0.0, 0.0)
        self.assertGreater(s_stable, s_lst)

    def test_collateral_usage_100_adds_30(self):
        s_full = _compute_contagion_spread_score("stablecoin", 100.0, 0.0, 0.0, 0.0)
        s_zero = _compute_contagion_spread_score("stablecoin", 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(s_full - s_zero, 30.0, places=3)

    def test_collateral_usage_50_adds_15(self):
        s_half = _compute_contagion_spread_score("stablecoin", 50.0, 0.0, 0.0, 0.0)
        s_zero = _compute_contagion_spread_score("stablecoin", 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(s_half - s_zero, 15.0, places=3)

    def test_severe_depeg_30pct_adds_20(self):
        s_high = _compute_contagion_spread_score("stablecoin", 0.0, 30.0, 0.0, 0.0)
        s_zero = _compute_contagion_spread_score("stablecoin", 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(s_high - s_zero, 20.0, places=3)

    def test_depeg_15pct_adds_13(self):
        s = _compute_contagion_spread_score("stablecoin", 0.0, 15.0, 0.0, 0.0)
        s0 = _compute_contagion_spread_score("stablecoin", 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(s - s0, 13.0, places=3)

    def test_depeg_5pct_adds_7(self):
        s = _compute_contagion_spread_score("stablecoin", 0.0, 5.0, 0.0, 0.0)
        s0 = _compute_contagion_spread_score("stablecoin", 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(s - s0, 7.0, places=3)

    def test_depeg_1pct_adds_2(self):
        s = _compute_contagion_spread_score("stablecoin", 0.0, 1.0, 0.0, 0.0)
        s0 = _compute_contagion_spread_score("stablecoin", 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(s - s0, 2.0, places=3)

    def test_interconnection_1_adds_15(self):
        s = _compute_contagion_spread_score("stablecoin", 0.0, 0.0, 1.0, 0.0)
        s0 = _compute_contagion_spread_score("stablecoin", 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(s - s0, 15.0, places=3)

    def test_full_insurance_reduces_by_20(self):
        s_insured = _compute_contagion_spread_score("stablecoin", 0.0, 0.0, 0.0, 100.0)
        s_none = _compute_contagion_spread_score("stablecoin", 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(s_none - s_insured, 20.0, places=3)

    def test_collateral_capped_at_100(self):
        s1 = _compute_contagion_spread_score("stablecoin", 100.0, 0.0, 0.0, 0.0)
        s2 = _compute_contagion_spread_score("stablecoin", 200.0, 0.0, 0.0, 0.0)
        self.assertEqual(s1, s2)

    def test_interconnection_capped_at_1(self):
        s1 = _compute_contagion_spread_score("stablecoin", 0.0, 0.0, 1.0, 0.0)
        s2 = _compute_contagion_spread_score("stablecoin", 0.0, 0.0, 1.5, 0.0)
        self.assertEqual(s1, s2)

    def test_unknown_asset_type_uses_default(self):
        s = _compute_contagion_spread_score("exotic", 0.0, 0.0, 0.0, 0.0)
        self.assertGreaterEqual(s, 0.0)

    def test_depeg_over_100_capped(self):
        s1 = _compute_contagion_spread_score("stablecoin", 0.0, 100.0, 0.0, 0.0)
        s2 = _compute_contagion_spread_score("stablecoin", 0.0, 999.0, 0.0, 0.0)
        self.assertEqual(s1, s2)


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_direct_loss_usd
# ─────────────────────────────────────────────────────────────────

class TestComputeDirectLossUsd(unittest.TestCase):

    def test_zero_tvl_returns_zero(self):
        loss = _compute_direct_loss_usd(0.0, 10.0, 50.0)
        self.assertEqual(loss, 0.0)

    def test_zero_depeg_returns_zero(self):
        loss = _compute_direct_loss_usd(1_000_000.0, 0.0, 50.0)
        self.assertEqual(loss, 0.0)

    def test_zero_collateral_usage_returns_zero(self):
        loss = _compute_direct_loss_usd(1_000_000.0, 10.0, 0.0)
        self.assertEqual(loss, 0.0)

    def test_basic_calculation(self):
        # 100M TVL × 10% depeg × 50% collateral = $5M
        loss = _compute_direct_loss_usd(100_000_000.0, 10.0, 50.0)
        self.assertAlmostEqual(loss, 5_000_000.0, places=1)

    def test_full_depeg_full_collateral(self):
        # 10B × 100% × 100% = 10B
        loss = _compute_direct_loss_usd(10_000_000_000.0, 100.0, 100.0)
        self.assertAlmostEqual(loss, 10_000_000_000.0, places=1)

    def test_proportional_to_tvl(self):
        loss1 = _compute_direct_loss_usd(1_000_000.0, 5.0, 40.0)
        loss2 = _compute_direct_loss_usd(2_000_000.0, 5.0, 40.0)
        self.assertAlmostEqual(loss2, loss1 * 2, places=5)

    def test_proportional_to_depeg(self):
        loss1 = _compute_direct_loss_usd(1_000_000.0, 5.0, 40.0)
        loss2 = _compute_direct_loss_usd(1_000_000.0, 10.0, 40.0)
        self.assertAlmostEqual(loss2, loss1 * 2, places=5)

    def test_depeg_capped_at_100(self):
        loss1 = _compute_direct_loss_usd(1_000_000.0, 100.0, 100.0)
        loss2 = _compute_direct_loss_usd(1_000_000.0, 200.0, 100.0)
        self.assertEqual(loss1, loss2)

    def test_result_is_float(self):
        loss = _compute_direct_loss_usd(500_000.0, 3.0, 25.0)
        self.assertIsInstance(loss, float)


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_cascading_loss_multiplier
# ─────────────────────────────────────────────────────────────────

class TestComputeCascadingLossMultiplier(unittest.TestCase):

    def test_minimum_is_1(self):
        m = _compute_cascading_loss_multiplier("stablecoin", 0.0, 0.0, 100.0)
        self.assertGreaterEqual(m, 1.0)

    def test_stablecoin_base_higher_than_wrapped(self):
        m_stable = _compute_cascading_loss_multiplier("stablecoin", 0.0, 0.0, 0.0)
        m_wrapped = _compute_cascading_loss_multiplier("wrapped", 0.0, 0.0, 0.0)
        self.assertGreater(m_stable, m_wrapped)

    def test_high_interconnection_increases_multiplier(self):
        m_high = _compute_cascading_loss_multiplier("stablecoin", 1.0, 5.0, 0.0)
        m_low = _compute_cascading_loss_multiplier("stablecoin", 0.0, 5.0, 0.0)
        self.assertGreater(m_high, m_low)

    def test_interconnection_adds_1_5_at_max(self):
        m_1 = _compute_cascading_loss_multiplier("stablecoin", 1.0, 0.0, 0.0)
        m_0 = _compute_cascading_loss_multiplier("stablecoin", 0.0, 0.0, 0.0)
        self.assertAlmostEqual(m_1 - m_0, 1.5, places=3)

    def test_severe_depeg_adds_1(self):
        m_high = _compute_cascading_loss_multiplier("stablecoin", 0.0, 30.0, 0.0)
        m_none = _compute_cascading_loss_multiplier("stablecoin", 0.0, 0.0, 0.0)
        self.assertAlmostEqual(m_high - m_none, 1.0, places=3)

    def test_depeg_15_adds_05(self):
        m_h = _compute_cascading_loss_multiplier("stablecoin", 0.0, 15.0, 0.0)
        m_n = _compute_cascading_loss_multiplier("stablecoin", 0.0, 0.0, 0.0)
        self.assertAlmostEqual(m_h - m_n, 0.5, places=3)

    def test_depeg_5_adds_02(self):
        m_h = _compute_cascading_loss_multiplier("stablecoin", 0.0, 5.0, 0.0)
        m_n = _compute_cascading_loss_multiplier("stablecoin", 0.0, 0.0, 0.0)
        self.assertAlmostEqual(m_h - m_n, 0.2, places=3)

    def test_full_insurance_reduces_by_1(self):
        m_ins = _compute_cascading_loss_multiplier("stablecoin", 0.0, 0.0, 100.0)
        m_none = _compute_cascading_loss_multiplier("stablecoin", 0.0, 0.0, 0.0)
        self.assertAlmostEqual(m_none - m_ins, 1.0, places=3)

    def test_returns_float(self):
        m = _compute_cascading_loss_multiplier("lst", 0.5, 10.0, 20.0)
        self.assertIsInstance(m, float)

    def test_unknown_asset_type_default(self):
        m = _compute_cascading_loss_multiplier("exotic", 0.0, 0.0, 0.0)
        self.assertGreaterEqual(m, 1.0)

    def test_rounding_to_3_places(self):
        m = _compute_cascading_loss_multiplier("stablecoin", 0.333, 5.0, 0.0)
        # result should be rounded to 3 decimal places
        self.assertEqual(m, round(m, 3))


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_affected_protocols_estimate
# ─────────────────────────────────────────────────────────────────

class TestComputeAffectedProtocolsEstimate(unittest.TestCase):

    def test_returns_int(self):
        n = _compute_affected_protocols_estimate(30.0, 0.5, 10.0)
        self.assertIsInstance(n, int)

    def test_zero_inputs_returns_zero(self):
        n = _compute_affected_protocols_estimate(0.0, 0.0, 0.0)
        self.assertEqual(n, 0)

    def test_100pct_collateral_all_directly_exposed(self):
        n = _compute_affected_protocols_estimate(100.0, 0.0, 0.0)
        self.assertEqual(n, 200)

    def test_50pct_collateral_100_directly(self):
        n = _compute_affected_protocols_estimate(50.0, 0.0, 0.0)
        self.assertEqual(n, 100)

    def test_interconnection_increases_affected(self):
        n_high = _compute_affected_protocols_estimate(30.0, 1.0, 50.0)
        n_low = _compute_affected_protocols_estimate(30.0, 0.0, 50.0)
        self.assertGreater(n_high, n_low)

    def test_larger_depeg_increases_affected(self):
        n_big = _compute_affected_protocols_estimate(30.0, 0.5, 50.0)
        n_small = _compute_affected_protocols_estimate(30.0, 0.5, 5.0)
        self.assertGreaterEqual(n_big, n_small)

    def test_max_does_not_exceed_200(self):
        n = _compute_affected_protocols_estimate(100.0, 1.0, 100.0)
        self.assertLessEqual(n, 200)

    def test_non_negative(self):
        n = _compute_affected_protocols_estimate(0.0, 0.0, 0.0)
        self.assertGreaterEqual(n, 0)

    def test_collateral_capped_at_100(self):
        n1 = _compute_affected_protocols_estimate(100.0, 0.0, 0.0)
        n2 = _compute_affected_protocols_estimate(200.0, 0.0, 0.0)
        self.assertEqual(n1, n2)


# ─────────────────────────────────────────────────────────────────
# Tests: _contagion_label
# ─────────────────────────────────────────────────────────────────

class TestContagionLabel(unittest.TestCase):

    def test_systemic_meltdown_at_85(self):
        self.assertEqual(_contagion_label(85.0), "SYSTEMIC_MELTDOWN")

    def test_systemic_meltdown_at_100(self):
        self.assertEqual(_contagion_label(100.0), "SYSTEMIC_MELTDOWN")

    def test_high_contagion_at_65(self):
        self.assertEqual(_contagion_label(65.0), "HIGH_CONTAGION")

    def test_high_contagion_at_84(self):
        self.assertEqual(_contagion_label(84.9), "HIGH_CONTAGION")

    def test_moderate_contagion_at_45(self):
        self.assertEqual(_contagion_label(45.0), "MODERATE_CONTAGION")

    def test_moderate_contagion_at_64(self):
        self.assertEqual(_contagion_label(64.9), "MODERATE_CONTAGION")

    def test_low_contagion_at_25(self):
        self.assertEqual(_contagion_label(25.0), "LOW_CONTAGION")

    def test_low_contagion_at_44(self):
        self.assertEqual(_contagion_label(44.9), "LOW_CONTAGION")

    def test_contained_at_0(self):
        self.assertEqual(_contagion_label(0.0), "CONTAINED")

    def test_contained_at_24(self):
        self.assertEqual(_contagion_label(24.9), "CONTAINED")

    def test_boundary_85(self):
        self.assertEqual(_contagion_label(85.0), "SYSTEMIC_MELTDOWN")

    def test_boundary_just_below_85(self):
        self.assertEqual(_contagion_label(84.999), "HIGH_CONTAGION")


# ─────────────────────────────────────────────────────────────────
# Tests: _compute_flags
# ─────────────────────────────────────────────────────────────────

class TestComputeFlags(unittest.TestCase):

    def test_no_flags_mild_scenario(self):
        flags = _compute_flags("stablecoin", 1.0, 0.3, 10.0, 30.0)
        self.assertEqual(flags, [])

    def test_severe_depeg_flag(self):
        flags = _compute_flags("stablecoin", 25.0, 0.5, 30.0, 10.0)
        self.assertIn("SEVERE_DEPEG", flags)

    def test_high_interconnection_flag(self):
        flags = _compute_flags("stablecoin", 5.0, 0.80, 30.0, 10.0)
        self.assertIn("HIGH_INTERCONNECTION", flags)

    def test_widespread_collateral_flag_at_50(self):
        flags = _compute_flags("stablecoin", 5.0, 0.3, 50.0, 10.0)
        self.assertIn("WIDESPREAD_COLLATERAL_USE", flags)

    def test_minimal_insurance_flag(self):
        flags = _compute_flags("stablecoin", 5.0, 0.3, 30.0, 5.0)
        self.assertIn("MINIMAL_INSURANCE", flags)

    def test_stablecoin_peg_break_flag(self):
        flags = _compute_flags("stablecoin", 5.0, 0.5, 30.0, 10.0)
        self.assertIn("STABLECOIN_PEG_BREAK", flags)

    def test_lst_slashing_event_flag(self):
        flags = _compute_flags("lst", 3.5, 0.5, 30.0, 10.0)
        self.assertIn("LST_SLASHING_EVENT", flags)

    def test_lst_no_peg_break_flag(self):
        flags = _compute_flags("lst", 5.0, 0.5, 30.0, 10.0)
        self.assertNotIn("STABLECOIN_PEG_BREAK", flags)

    def test_returns_list(self):
        flags = _compute_flags("wrapped", 5.0, 0.5, 30.0, 10.0)
        self.assertIsInstance(flags, list)

    def test_multiple_flags_possible(self):
        flags = _compute_flags("stablecoin", 25.0, 0.9, 60.0, 0.0)
        self.assertGreater(len(flags), 2)


# ─────────────────────────────────────────────────────────────────
# Tests: DeFiProtocolDepegContagionRiskAnalyzer.analyze()
# ─────────────────────────────────────────────────────────────────

class TestDeFiProtocolDepegContagionRiskAnalyzer(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.analyzer = DeFiProtocolDepegContagionRiskAnalyzer()

    def _analyze(self, **kw):
        defaults = _stablecoin_scenario()
        defaults.update(kw)
        defaults["data_dir"] = self.tmpdir
        return self.analyzer.analyze(**defaults)

    def test_returns_dict(self):
        r = self._analyze()
        self.assertIsInstance(r, dict)

    def test_all_keys_present(self):
        r = self._analyze()
        expected = [
            "asset_name", "asset_type", "collateral_usage_pct",
            "depeg_magnitude_pct", "protocol_interconnection_score",
            "insurance_coverage_pct", "tvl_exposed_usd",
            "contagion_spread_score", "direct_loss_usd",
            "cascading_loss_multiplier", "total_estimated_loss_usd",
            "affected_protocols_estimate", "label", "flags", "timestamp",
        ]
        for k in expected:
            self.assertIn(k, r, msg=f"Missing key: {k}")

    def test_contagion_score_in_range(self):
        r = self._analyze()
        self.assertGreaterEqual(r["contagion_spread_score"], 0.0)
        self.assertLessEqual(r["contagion_spread_score"], 100.0)

    def test_cascading_multiplier_ge_1(self):
        r = self._analyze()
        self.assertGreaterEqual(r["cascading_loss_multiplier"], 1.0)

    def test_total_loss_ge_direct_loss(self):
        r = self._analyze()
        self.assertGreaterEqual(r["total_estimated_loss_usd"], r["direct_loss_usd"])

    def test_affected_protocols_non_negative(self):
        r = self._analyze()
        self.assertGreaterEqual(r["affected_protocols_estimate"], 0)

    def test_label_is_valid(self):
        r = self._analyze()
        valid = {"CONTAINED", "LOW_CONTAGION", "MODERATE_CONTAGION",
                 "HIGH_CONTAGION", "SYSTEMIC_MELTDOWN"}
        self.assertIn(r["label"], valid)

    def test_flags_is_list(self):
        r = self._analyze()
        self.assertIsInstance(r["flags"], list)

    def test_timestamp_is_float(self):
        r = self._analyze()
        self.assertIsInstance(r["timestamp"], float)

    def test_asset_name_preserved(self):
        r = self._analyze(asset_name="USDT")
        self.assertEqual(r["asset_name"], "USDT")

    def test_asset_type_lowercase(self):
        r = self._analyze(asset_type="Stablecoin")
        self.assertEqual(r["asset_type"], "stablecoin")

    def test_collateral_pct_clamped_to_100(self):
        r = self._analyze(collateral_usage_pct=150.0)
        self.assertEqual(r["collateral_usage_pct"], 100.0)

    def test_insurance_pct_clamped_to_100(self):
        r = self._analyze(insurance_coverage_pct=200.0)
        self.assertEqual(r["insurance_coverage_pct"], 100.0)

    def test_interconnect_clamped_to_1(self):
        r = self._analyze(protocol_interconnection_score=2.0)
        self.assertEqual(r["protocol_interconnection_score"], 1.0)

    def test_zero_tvl_zero_losses(self):
        r = self._analyze(tvl_exposed_usd=0.0)
        self.assertEqual(r["direct_loss_usd"], 0.0)
        self.assertEqual(r["total_estimated_loss_usd"], 0.0)

    def test_systemic_scenario_label(self):
        r = self._analyze(
            asset_type="stablecoin",
            collateral_usage_pct=90.0,
            depeg_magnitude_pct=50.0,
            protocol_interconnection_score=0.95,
            insurance_coverage_pct=0.0,
        )
        self.assertEqual(r["label"], "SYSTEMIC_MELTDOWN")

    def test_contained_scenario_label(self):
        r = self._analyze(
            asset_type="wrapped",
            collateral_usage_pct=5.0,
            depeg_magnitude_pct=0.5,
            protocol_interconnection_score=0.1,
            insurance_coverage_pct=80.0,
        )
        self.assertIn(r["label"], {"CONTAINED", "LOW_CONTAGION"})

    def test_lst_scenario(self):
        r = self.analyzer.analyze(
            **{**_lst_scenario(), "data_dir": self.tmpdir}
        )
        self.assertIn(r["label"], {
            "CONTAINED", "LOW_CONTAGION", "MODERATE_CONTAGION",
            "HIGH_CONTAGION", "SYSTEMIC_MELTDOWN"
        })

    def test_log_file_created(self):
        self._analyze()
        log_path = Path(self.tmpdir) / "depeg_contagion_risk_log.json"
        self.assertTrue(log_path.exists())

    def test_log_file_is_valid_json_list(self):
        self._analyze()
        log_path = Path(self.tmpdir) / "depeg_contagion_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_file_contains_entry(self):
        self._analyze()
        log_path = Path(self.tmpdir) / "depeg_contagion_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_accumulates_entries(self):
        for _ in range(5):
            self._analyze()
        log_path = Path(self.tmpdir) / "depeg_contagion_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_ring_buffer_cap(self):
        for _ in range(MAX_ENTRIES + 10):
            self._analyze()
        log_path = Path(self.tmpdir) / "depeg_contagion_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), MAX_ENTRIES)

    def test_atomic_write_no_partial_file(self):
        # Write multiple times; file should always be valid JSON
        for i in range(20):
            self._analyze(depeg_magnitude_pct=float(i))
        log_path = Path(self.tmpdir) / "depeg_contagion_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_wrapped_asset_type(self):
        r = self.analyzer.analyze(
            asset_type="wrapped",
            collateral_usage_pct=20.0,
            depeg_magnitude_pct=2.0,
            protocol_interconnection_score=0.3,
            insurance_coverage_pct=10.0,
            tvl_exposed_usd=1_000_000_000,
            data_dir=self.tmpdir,
        )
        self.assertEqual(r["asset_type"], "wrapped")

    def test_direct_loss_matches_helper(self):
        r = self._analyze(
            tvl_exposed_usd=1_000_000_000,
            collateral_usage_pct=40.0,
            depeg_magnitude_pct=10.0,
        )
        expected = _compute_direct_loss_usd(1_000_000_000, 10.0, 40.0)
        self.assertAlmostEqual(r["direct_loss_usd"], expected, places=0)

    def test_negative_tvl_clamped(self):
        r = self._analyze(tvl_exposed_usd=-1_000.0)
        self.assertEqual(r["tvl_exposed_usd"], 0.0)

    def test_negative_collateral_clamped(self):
        r = self._analyze(collateral_usage_pct=-10.0)
        self.assertEqual(r["collateral_usage_pct"], 0.0)

    def test_negative_depeg_clamped(self):
        r = self._analyze(depeg_magnitude_pct=-5.0)
        self.assertEqual(r["depeg_magnitude_pct"], 0.0)

    def test_score_rounded_to_4_places(self):
        r = self._analyze()
        s = r["contagion_spread_score"]
        self.assertEqual(s, round(s, 4))


# ─────────────────────────────────────────────────────────────────
# Tests: constants
# ─────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):

    def test_asset_type_base_spread_keys(self):
        for k in ("stablecoin", "lst", "wrapped"):
            self.assertIn(k, ASSET_TYPE_BASE_SPREAD)

    def test_asset_type_base_spread_values_positive(self):
        for v in ASSET_TYPE_BASE_SPREAD.values():
            self.assertGreater(v, 0)

    def test_cascade_multiplier_keys(self):
        for k in ("stablecoin", "lst", "wrapped"):
            self.assertIn(k, ASSET_TYPE_CASCADE_MULTIPLIER)

    def test_cascade_multiplier_stablecoin_highest(self):
        self.assertGreater(
            ASSET_TYPE_CASCADE_MULTIPLIER["stablecoin"],
            ASSET_TYPE_CASCADE_MULTIPLIER["wrapped"]
        )

    def test_max_entries(self):
        self.assertEqual(MAX_ENTRIES, 100)

    def test_data_file_is_path(self):
        self.assertIsInstance(DATA_FILE, Path)


# ─────────────────────────────────────────────────────────────────
# Tests: _append_log
# ─────────────────────────────────────────────────────────────────

class TestAppendLog(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_creates_file_if_absent(self):
        _append_log({"test": 1}, data_dir=self.tmpdir)
        log_path = Path(self.tmpdir) / "depeg_contagion_risk_log.json"
        self.assertTrue(log_path.exists())

    def test_file_contains_entry(self):
        _append_log({"x": 42}, data_dir=self.tmpdir)
        log_path = Path(self.tmpdir) / "depeg_contagion_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["x"], 42)

    def test_appends_successive_entries(self):
        for i in range(5):
            _append_log({"i": i}, data_dir=self.tmpdir)
        log_path = Path(self.tmpdir) / "depeg_contagion_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_capped_at_max(self):
        for i in range(MAX_ENTRIES + 20):
            _append_log({"i": i}, data_dir=self.tmpdir)
        log_path = Path(self.tmpdir) / "depeg_contagion_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), MAX_ENTRIES)

    def test_ring_buffer_keeps_latest(self):
        for i in range(MAX_ENTRIES + 5):
            _append_log({"i": i}, data_dir=self.tmpdir)
        log_path = Path(self.tmpdir) / "depeg_contagion_risk_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], MAX_ENTRIES + 4)

    def test_corrupt_file_resets_gracefully(self):
        log_path = Path(self.tmpdir) / "depeg_contagion_risk_log.json"
        log_path.write_text("NOT JSON", encoding="utf-8")
        _append_log({"new": True}, data_dir=self.tmpdir)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertTrue(data[0]["new"])

    def test_tmp_file_not_left_behind(self):
        _append_log({"t": 1}, data_dir=self.tmpdir)
        tmp_files = list(Path(self.tmpdir).glob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)


if __name__ == "__main__":
    unittest.main()
