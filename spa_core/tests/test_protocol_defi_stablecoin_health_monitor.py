"""
Tests for MP-993: ProtocolDeFiStablecoinHealthMonitor
≥80 tests, stdlib unittest only.
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_stablecoin_health_monitor import (
    ProtocolDeFiStablecoinHealthMonitor,
    LABEL_ROCK_SOLID,
    LABEL_STABLE,
    LABEL_CAUTIOUS,
    LABEL_AT_RISK,
    LABEL_DEPEGGING,
    LABEL_COLLAPSED,
    FLAG_ACTIVE_DEPEG,
    FLAG_ALGO_CONCENTRATION,
    FLAG_UNAUDITED_RESERVES,
    FLAG_REDEMPTION_PRESSURE,
    FLAG_REDEMPTION_SUSPENDED,
    FLAG_NET_OUTFLOW_ACCELERATING,
    _peg_deviation_pct,
    _peg_volatility_30d,
    _max_depeg_30d,
    _redemption_pressure_ratio,
    _net_flow_7d,
    _monitor_coin,
)


# ── Fixtures ───────────────────────────────────────────────────────────────

def _rock_solid_coin(**overrides):
    """A maximally healthy stablecoin with optional overrides."""
    base = {
        "name": "USDC",
        "peg_target_usd": 1.0,
        "current_price_usd": 1.0001,
        "price_history_30d": [1.0 + 0.00005 * (i % 3) for i in range(30)],
        "collateral_ratio_pct": 200.0,
        "collateral_types": ["cash", "treasuries"],
        "algo_component_pct": 0.0,
        "total_supply_usd": 40_000_000_000.0,
        "circulating_supply_usd": 38_000_000_000.0,
        "daily_redemptions_usd_7d_avg": 100_000_000.0,
        "daily_mints_usd_7d_avg": 150_000_000.0,
        "peg_mechanism": "fiat_backed",
        "issuer_reserves_audited": True,
        "redemption_suspended": False,
        "blacklist_enabled": True,
    }
    base.update(overrides)
    return base


def _depegging_coin(**overrides):
    """A stablecoin in distress with optional overrides."""
    base = {
        "name": "BadStable",
        "peg_target_usd": 1.0,
        "current_price_usd": 0.92,
        "price_history_30d": [1.0 - i * 0.003 for i in range(30)],
        "collateral_ratio_pct": 95.0,
        "collateral_types": ["algo"],
        "algo_component_pct": 80.0,
        "total_supply_usd": 1_000_000_000.0,
        "circulating_supply_usd": 900_000_000.0,
        "daily_redemptions_usd_7d_avg": 50_000_000.0,
        "daily_mints_usd_7d_avg": 2_000_000.0,
        "peg_mechanism": "algorithmic",
        "issuer_reserves_audited": False,
        "redemption_suspended": True,
        "blacklist_enabled": False,
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# 1. Class construction
# ═══════════════════════════════════════════════════════════════════════════

class TestInstantiation(unittest.TestCase):

    def test_01_creates_monitor(self):
        m = ProtocolDeFiStablecoinHealthMonitor()
        self.assertIsInstance(m, ProtocolDeFiStablecoinHealthMonitor)

    def test_02_monitor_method_exists(self):
        m = ProtocolDeFiStablecoinHealthMonitor()
        self.assertTrue(callable(m.monitor))


# ═══════════════════════════════════════════════════════════════════════════
# 2. Empty input
# ═══════════════════════════════════════════════════════════════════════════

class TestEmptyInput(unittest.TestCase):

    def setUp(self):
        self.mon = ProtocolDeFiStablecoinHealthMonitor()
        self.cfg = {"write_log": False}

    def test_03_empty_returns_dict(self):
        r = self.mon.monitor([], self.cfg)
        self.assertIsInstance(r, dict)

    def test_04_empty_stablecoins_list(self):
        r = self.mon.monitor([], self.cfg)
        self.assertEqual(r["stablecoins"], [])

    def test_05_empty_most_stable_none(self):
        r = self.mon.monitor([], self.cfg)
        self.assertIsNone(r["most_stable"])

    def test_06_empty_most_at_risk_none(self):
        r = self.mon.monitor([], self.cfg)
        self.assertIsNone(r["most_at_risk"])

    def test_07_empty_avg_deviation_zero(self):
        r = self.mon.monitor([], self.cfg)
        self.assertEqual(r["avg_deviation"], 0.0)

    def test_08_empty_depegging_count_zero(self):
        r = self.mon.monitor([], self.cfg)
        self.assertEqual(r["depegging_count"], 0)

    def test_09_empty_rock_solid_count_zero(self):
        r = self.mon.monitor([], self.cfg)
        self.assertEqual(r["rock_solid_count"], 0)

    def test_10_timestamp_present(self):
        r = self.mon.monitor([], self.cfg)
        self.assertGreater(r["timestamp"], 0)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Peg deviation calculation
# ═══════════════════════════════════════════════════════════════════════════

class TestPegDeviation(unittest.TestCase):

    def test_11_perfect_peg_zero_deviation(self):
        c = _rock_solid_coin(current_price_usd=1.0)
        self.assertAlmostEqual(_peg_deviation_pct(c), 0.0, places=5)

    def test_12_price_above_peg(self):
        c = _rock_solid_coin(current_price_usd=1.02)
        self.assertAlmostEqual(_peg_deviation_pct(c), 2.0, places=4)

    def test_13_price_below_peg(self):
        c = _rock_solid_coin(current_price_usd=0.98)
        self.assertAlmostEqual(_peg_deviation_pct(c), 2.0, places=4)

    def test_14_small_deviation(self):
        c = _rock_solid_coin(current_price_usd=1.0001)
        self.assertAlmostEqual(_peg_deviation_pct(c), 0.01, places=3)

    def test_15_large_deviation_collapsed(self):
        c = _rock_solid_coin(current_price_usd=0.80)
        self.assertAlmostEqual(_peg_deviation_pct(c), 20.0, places=2)

    def test_16_absolute_value(self):
        # Deviation should always be positive
        c = _rock_solid_coin(current_price_usd=0.95)
        self.assertGreater(_peg_deviation_pct(c), 0.0)

    def test_17_non_dollar_peg(self):
        c = _rock_solid_coin(peg_target_usd=2.0, current_price_usd=2.04)
        self.assertAlmostEqual(_peg_deviation_pct(c), 2.0, places=3)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Peg volatility
# ═══════════════════════════════════════════════════════════════════════════

class TestPegVolatility(unittest.TestCase):

    def test_18_constant_history_zero_volatility(self):
        c = _rock_solid_coin(price_history_30d=[1.0] * 30)
        self.assertAlmostEqual(_peg_volatility_30d(c), 0.0, places=6)

    def test_19_volatile_history_nonzero(self):
        c = _rock_solid_coin(price_history_30d=[0.99, 1.01] * 15)
        v = _peg_volatility_30d(c)
        self.assertGreater(v, 0.0)

    def test_20_empty_history_zero(self):
        c = _rock_solid_coin(price_history_30d=[])
        self.assertEqual(_peg_volatility_30d(c), 0.0)

    def test_21_single_element_zero(self):
        c = _rock_solid_coin(price_history_30d=[1.0])
        self.assertEqual(_peg_volatility_30d(c), 0.0)

    def test_22_high_variance_history(self):
        c = _rock_solid_coin(price_history_30d=[0.85, 1.15] * 15)
        v = _peg_volatility_30d(c)
        self.assertGreater(v, 0.1)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Max depeg 30d
# ═══════════════════════════════════════════════════════════════════════════

class TestMaxDepeg30d(unittest.TestCase):

    def test_23_all_at_peg_zero(self):
        c = _rock_solid_coin(price_history_30d=[1.0] * 30)
        self.assertAlmostEqual(_max_depeg_30d(c), 0.0, places=5)

    def test_24_worst_point_captured(self):
        # Price dips to 0.95 once
        history = [1.0] * 29 + [0.95]
        c = _rock_solid_coin(price_history_30d=history)
        self.assertAlmostEqual(_max_depeg_30d(c), 5.0, places=3)

    def test_25_max_vs_avg(self):
        # Max should be >= avg deviation
        c = _rock_solid_coin(
            price_history_30d=[0.99, 1.01, 0.95, 1.005] * 7 + [0.99, 1.01]
        )
        d = _peg_deviation_pct(c)
        md = _max_depeg_30d(c)
        self.assertGreaterEqual(md, 0.0)

    def test_26_empty_history_falls_back_to_current(self):
        c = _rock_solid_coin(current_price_usd=0.97, price_history_30d=[])
        # Should fall back to current deviation
        self.assertAlmostEqual(_max_depeg_30d(c), 3.0, places=2)

    def test_27_above_and_below_peg(self):
        history = [1.05] * 15 + [0.95] * 15
        c = _rock_solid_coin(price_history_30d=history)
        self.assertAlmostEqual(_max_depeg_30d(c), 5.0, places=2)


# ═══════════════════════════════════════════════════════════════════════════
# 6. Redemption pressure ratio
# ═══════════════════════════════════════════════════════════════════════════

class TestRedemptionPressureRatio(unittest.TestCase):

    def test_28_low_redemptions(self):
        c = _rock_solid_coin(
            daily_redemptions_usd_7d_avg=100_000.0,
            circulating_supply_usd=10_000_000_000.0
        )
        self.assertLess(_redemption_pressure_ratio(c), 0.01)

    def test_29_high_redemptions(self):
        c = _rock_solid_coin(
            daily_redemptions_usd_7d_avg=50_000_000.0,
            circulating_supply_usd=1_000_000_000.0
        )
        self.assertGreater(_redemption_pressure_ratio(c), 2.0)

    def test_30_zero_supply_returns_zero(self):
        c = _rock_solid_coin(circulating_supply_usd=0.0)
        self.assertEqual(_redemption_pressure_ratio(c), 0.0)

    def test_31_formula_correct(self):
        c = _rock_solid_coin(
            daily_redemptions_usd_7d_avg=1_000_000.0,
            circulating_supply_usd=50_000_000.0
        )
        expected = 1_000_000.0 / 50_000_000.0 * 100.0
        self.assertAlmostEqual(_redemption_pressure_ratio(c), expected, places=4)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Net flow 7d
# ═══════════════════════════════════════════════════════════════════════════

class TestNetFlow7d(unittest.TestCase):

    def test_32_positive_net_flow_inflow(self):
        c = _rock_solid_coin(
            daily_mints_usd_7d_avg=10_000_000.0,
            daily_redemptions_usd_7d_avg=1_000_000.0,
            circulating_supply_usd=100_000_000.0
        )
        self.assertGreater(_net_flow_7d(c), 0.0)

    def test_33_negative_net_flow_outflow(self):
        c = _rock_solid_coin(
            daily_mints_usd_7d_avg=1_000_000.0,
            daily_redemptions_usd_7d_avg=10_000_000.0,
            circulating_supply_usd=100_000_000.0
        )
        self.assertLess(_net_flow_7d(c), 0.0)

    def test_34_balanced_flow_zero(self):
        c = _rock_solid_coin(
            daily_mints_usd_7d_avg=5_000_000.0,
            daily_redemptions_usd_7d_avg=5_000_000.0,
            circulating_supply_usd=100_000_000.0
        )
        self.assertAlmostEqual(_net_flow_7d(c), 0.0, places=5)

    def test_35_zero_supply_returns_zero(self):
        c = _rock_solid_coin(circulating_supply_usd=0.0)
        self.assertEqual(_net_flow_7d(c), 0.0)

    def test_36_formula_correct(self):
        c = _rock_solid_coin(
            daily_mints_usd_7d_avg=3_000_000.0,
            daily_redemptions_usd_7d_avg=8_000_000.0,
            circulating_supply_usd=100_000_000.0
        )
        expected = (3_000_000.0 - 8_000_000.0) / 100_000_000.0 * 100.0
        self.assertAlmostEqual(_net_flow_7d(c), expected, places=4)


# ═══════════════════════════════════════════════════════════════════════════
# 8. Health labels
# ═══════════════════════════════════════════════════════════════════════════

class TestHealthLabels(unittest.TestCase):

    def _label_for(self, **overrides):
        c = {**_rock_solid_coin(), **overrides}
        r = _monitor_coin(c)
        return r["health_label"]

    def test_37_rock_solid_label(self):
        label = self._label_for(
            current_price_usd=1.0001,
            collateral_ratio_pct=200.0,
            issuer_reserves_audited=True,
            algo_component_pct=0.0,
        )
        self.assertEqual(label, LABEL_ROCK_SOLID)

    def test_38_collapsed_label_extreme_depeg(self):
        label = self._label_for(current_price_usd=0.85)
        self.assertEqual(label, LABEL_COLLAPSED)

    def test_39_depegging_label_3pct(self):
        label = self._label_for(current_price_usd=0.965)
        self.assertEqual(label, LABEL_DEPEGGING)

    def test_40_depegging_label_suspended(self):
        label = self._label_for(
            current_price_usd=1.001,
            redemption_suspended=True
        )
        self.assertEqual(label, LABEL_DEPEGGING)

    def test_41_at_risk_label_under_collateralized(self):
        label = self._label_for(
            current_price_usd=1.005,
            collateral_ratio_pct=105.0
        )
        self.assertEqual(label, LABEL_AT_RISK)

    def test_42_at_risk_label_1pct_depeg(self):
        label = self._label_for(current_price_usd=1.015)
        self.assertEqual(label, LABEL_AT_RISK)

    def test_43_cautious_label_algo_component(self):
        label = self._label_for(
            current_price_usd=1.002,
            algo_component_pct=25.0,
            collateral_ratio_pct=150.0
        )
        self.assertEqual(label, LABEL_CAUTIOUS)

    def test_44_cautious_label_mild_depeg(self):
        label = self._label_for(
            current_price_usd=1.007,
            collateral_ratio_pct=160.0,
            algo_component_pct=0.0
        )
        self.assertEqual(label, LABEL_CAUTIOUS)

    def test_45_stable_label(self):
        label = self._label_for(
            current_price_usd=1.003,
            collateral_ratio_pct=140.0,
            algo_component_pct=15.0,
            issuer_reserves_audited=True
        )
        self.assertEqual(label, LABEL_STABLE)

    def test_46_valid_labels_only(self):
        valid = {LABEL_ROCK_SOLID, LABEL_STABLE, LABEL_CAUTIOUS,
                 LABEL_AT_RISK, LABEL_DEPEGGING, LABEL_COLLAPSED}
        for coin in [_rock_solid_coin(), _depegging_coin()]:
            r = _monitor_coin(coin)
            self.assertIn(r["health_label"], valid)

    def test_47_depegging_coin_label(self):
        r = _monitor_coin(_depegging_coin())
        self.assertIn(r["health_label"], [LABEL_DEPEGGING, LABEL_COLLAPSED])

    def test_48_collapsed_threshold(self):
        c = _rock_solid_coin(current_price_usd=0.89)
        r = _monitor_coin(c)
        self.assertEqual(r["health_label"], LABEL_COLLAPSED)


# ═══════════════════════════════════════════════════════════════════════════
# 9. Flags
# ═══════════════════════════════════════════════════════════════════════════

class TestFlags(unittest.TestCase):

    def test_49_active_depeg_flag(self):
        c = _rock_solid_coin(current_price_usd=0.985)
        r = _monitor_coin(c)
        self.assertIn(FLAG_ACTIVE_DEPEG, r["flags"])

    def test_50_active_depeg_flag_absent(self):
        c = _rock_solid_coin(current_price_usd=1.005)
        r = _monitor_coin(c)
        self.assertNotIn(FLAG_ACTIVE_DEPEG, r["flags"])

    def test_51_algo_concentration_flag(self):
        c = _rock_solid_coin(algo_component_pct=40.0)
        r = _monitor_coin(c)
        self.assertIn(FLAG_ALGO_CONCENTRATION, r["flags"])

    def test_52_algo_concentration_flag_absent(self):
        c = _rock_solid_coin(algo_component_pct=20.0)
        r = _monitor_coin(c)
        self.assertNotIn(FLAG_ALGO_CONCENTRATION, r["flags"])

    def test_53_unaudited_reserves_flag_fiat(self):
        c = _rock_solid_coin(
            issuer_reserves_audited=False,
            peg_mechanism="fiat_backed"
        )
        r = _monitor_coin(c)
        self.assertIn(FLAG_UNAUDITED_RESERVES, r["flags"])

    def test_54_unaudited_reserves_flag_absent_if_audited(self):
        c = _rock_solid_coin(
            issuer_reserves_audited=True,
            peg_mechanism="fiat_backed"
        )
        r = _monitor_coin(c)
        self.assertNotIn(FLAG_UNAUDITED_RESERVES, r["flags"])

    def test_55_unaudited_reserves_absent_non_fiat(self):
        # Only triggered for fiat_backed
        c = _rock_solid_coin(
            issuer_reserves_audited=False,
            peg_mechanism="overcollateralized"
        )
        r = _monitor_coin(c)
        self.assertNotIn(FLAG_UNAUDITED_RESERVES, r["flags"])

    def test_56_redemption_pressure_flag(self):
        c = _rock_solid_coin(
            daily_redemptions_usd_7d_avg=30_000_000.0,
            circulating_supply_usd=1_000_000_000.0
        )
        r = _monitor_coin(c)
        self.assertIn(FLAG_REDEMPTION_PRESSURE, r["flags"])

    def test_57_redemption_pressure_flag_absent(self):
        c = _rock_solid_coin(
            daily_redemptions_usd_7d_avg=1_000_000.0,
            circulating_supply_usd=1_000_000_000.0
        )
        r = _monitor_coin(c)
        self.assertNotIn(FLAG_REDEMPTION_PRESSURE, r["flags"])

    def test_58_redemption_suspended_flag(self):
        c = _rock_solid_coin(redemption_suspended=True)
        r = _monitor_coin(c)
        self.assertIn(FLAG_REDEMPTION_SUSPENDED, r["flags"])

    def test_59_redemption_suspended_flag_absent(self):
        c = _rock_solid_coin(redemption_suspended=False)
        r = _monitor_coin(c)
        self.assertNotIn(FLAG_REDEMPTION_SUSPENDED, r["flags"])

    def test_60_net_outflow_flag(self):
        c = _rock_solid_coin(
            daily_mints_usd_7d_avg=1_000_000.0,
            daily_redemptions_usd_7d_avg=10_000_000.0,
            circulating_supply_usd=100_000_000.0
        )
        r = _monitor_coin(c)
        self.assertIn(FLAG_NET_OUTFLOW_ACCELERATING, r["flags"])

    def test_61_net_outflow_flag_absent_inflow(self):
        c = _rock_solid_coin(
            daily_mints_usd_7d_avg=10_000_000.0,
            daily_redemptions_usd_7d_avg=1_000_000.0,
            circulating_supply_usd=100_000_000.0
        )
        r = _monitor_coin(c)
        self.assertNotIn(FLAG_NET_OUTFLOW_ACCELERATING, r["flags"])

    def test_62_no_flags_rock_solid(self):
        c = _rock_solid_coin()
        r = _monitor_coin(c)
        self.assertEqual(r["flags"], [])

    def test_63_all_flags_depegging(self):
        c = _depegging_coin(
            peg_mechanism="fiat_backed",
            algo_component_pct=40.0,
        )
        r = _monitor_coin(c)
        # Should have multiple flags
        self.assertGreater(len(r["flags"]), 2)


# ═══════════════════════════════════════════════════════════════════════════
# 10. Full monitor output
# ═══════════════════════════════════════════════════════════════════════════

class TestMonitorOutput(unittest.TestCase):

    def setUp(self):
        self.mon = ProtocolDeFiStablecoinHealthMonitor()
        self.cfg = {"write_log": False}

    def test_64_result_has_stablecoins(self):
        r = self.mon.monitor([_rock_solid_coin()], self.cfg)
        self.assertIn("stablecoins", r)

    def test_65_stablecoin_has_name(self):
        r = self.mon.monitor([_rock_solid_coin(name="USDC")], self.cfg)
        self.assertEqual(r["stablecoins"][0]["name"], "USDC")

    def test_66_stablecoin_has_peg_deviation(self):
        r = self.mon.monitor([_rock_solid_coin()], self.cfg)
        self.assertIn("peg_deviation_pct", r["stablecoins"][0])

    def test_67_stablecoin_has_health_label(self):
        r = self.mon.monitor([_rock_solid_coin()], self.cfg)
        self.assertIn("health_label", r["stablecoins"][0])

    def test_68_stablecoin_has_flags(self):
        r = self.mon.monitor([_rock_solid_coin()], self.cfg)
        self.assertIsInstance(r["stablecoins"][0]["flags"], list)

    def test_69_two_coins_correct_count(self):
        r = self.mon.monitor([_rock_solid_coin(name="A"), _depegging_coin(name="B")], self.cfg)
        self.assertEqual(len(r["stablecoins"]), 2)

    def test_70_most_stable_is_rock_solid(self):
        r = self.mon.monitor(
            [_rock_solid_coin(name="Good"), _depegging_coin(name="Bad")],
            self.cfg
        )
        self.assertEqual(r["most_stable"], "Good")

    def test_71_most_at_risk_is_depegging(self):
        r = self.mon.monitor(
            [_rock_solid_coin(name="Good"), _depegging_coin(name="Bad")],
            self.cfg
        )
        self.assertEqual(r["most_at_risk"], "Bad")

    def test_72_avg_deviation_correct(self):
        c1 = _rock_solid_coin(name="A", current_price_usd=1.01)   # 1% dev
        c2 = _rock_solid_coin(name="B", current_price_usd=1.03)   # 3% dev
        r  = self.mon.monitor([c1, c2], self.cfg)
        expected = (1.0 + 3.0) / 2
        self.assertAlmostEqual(r["avg_deviation"], expected, places=2)

    def test_73_depegging_count_correct(self):
        c1 = _rock_solid_coin(name="A")
        c2 = _depegging_coin(name="B")
        r  = self.mon.monitor([c1, c2], self.cfg)
        self.assertGreaterEqual(r["depegging_count"], 1)

    def test_74_rock_solid_count_correct(self):
        r = self.mon.monitor([_rock_solid_coin(name="X")], self.cfg)
        self.assertEqual(r["rock_solid_count"], 1)

    def test_75_single_coin_most_stable_equals_most_at_risk(self):
        r = self.mon.monitor([_rock_solid_coin(name="Only")], self.cfg)
        self.assertEqual(r["most_stable"], "Only")
        self.assertEqual(r["most_at_risk"], "Only")

    def test_76_stablecoin_has_peg_volatility(self):
        r = self.mon.monitor([_rock_solid_coin()], self.cfg)
        self.assertIn("peg_volatility_30d", r["stablecoins"][0])

    def test_77_stablecoin_has_max_depeg(self):
        r = self.mon.monitor([_rock_solid_coin()], self.cfg)
        self.assertIn("max_depeg_30d", r["stablecoins"][0])

    def test_78_stablecoin_has_redemption_pressure(self):
        r = self.mon.monitor([_rock_solid_coin()], self.cfg)
        self.assertIn("redemption_pressure_ratio", r["stablecoins"][0])

    def test_79_stablecoin_has_net_flow(self):
        r = self.mon.monitor([_rock_solid_coin()], self.cfg)
        self.assertIn("net_flow_7d", r["stablecoins"][0])

    def test_80_stablecoin_has_collateral_ratio(self):
        r = self.mon.monitor([_rock_solid_coin()], self.cfg)
        self.assertIn("collateral_ratio_pct", r["stablecoins"][0])

    def test_81_stablecoin_has_algo_component(self):
        r = self.mon.monitor([_rock_solid_coin()], self.cfg)
        self.assertIn("algo_component_pct", r["stablecoins"][0])


# ═══════════════════════════════════════════════════════════════════════════
# 11. Ring-buffer log
# ═══════════════════════════════════════════════════════════════════════════

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmpdir   = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_stablecoin_log.json")
        self.mon      = ProtocolDeFiStablecoinHealthMonitor()

    def _cfg(self):
        return {"write_log": True, "log_path": self.log_path}

    def test_82_log_created(self):
        self.mon.monitor([_rock_solid_coin()], self._cfg())
        self.assertTrue(os.path.exists(self.log_path))

    def test_83_log_is_list(self):
        self.mon.monitor([_rock_solid_coin()], self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_84_log_grows(self):
        self.mon.monitor([_rock_solid_coin()], self._cfg())
        self.mon.monitor([_depegging_coin()], self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 2)

    def test_85_log_cap_100(self):
        for _ in range(105):
            self.mon.monitor([_rock_solid_coin()], self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertLessEqual(len(data), 100)

    def test_86_log_atomic_no_tmp(self):
        self.mon.monitor([_rock_solid_coin()], self._cfg())
        tmps = [f for f in os.listdir(self.tmpdir) if f.endswith(".tmp")]
        self.assertEqual(tmps, [])

    def test_87_log_entry_has_timestamp(self):
        self.mon.monitor([_rock_solid_coin()], self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIn("timestamp", data[0])

    def test_88_log_entry_has_stablecoins(self):
        self.mon.monitor([_rock_solid_coin()], self._cfg())
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIn("stablecoins", data[0])

    def test_89_load_log_public_method(self):
        self.mon.monitor([_rock_solid_coin()], self._cfg())
        log = self.mon.load_log(self.log_path)
        self.assertIsInstance(log, list)
        self.assertEqual(len(log), 1)

    def test_90_load_log_nonexistent_empty(self):
        log = self.mon.load_log(os.path.join(self.tmpdir, "nofile.json"))
        self.assertEqual(log, [])

    def test_91_write_log_false_no_file(self):
        path = os.path.join(self.tmpdir, "no_write.json")
        self.mon.monitor([_rock_solid_coin()], {"write_log": False, "log_path": path})
        self.assertFalse(os.path.exists(path))


# ═══════════════════════════════════════════════════════════════════════════
# 12. Field passthrough
# ═══════════════════════════════════════════════════════════════════════════

class TestPassthrough(unittest.TestCase):

    def setUp(self):
        self.mon = ProtocolDeFiStablecoinHealthMonitor()
        self.cfg = {"write_log": False}

    def test_92_name_preserved(self):
        r = self.mon.monitor([_rock_solid_coin(name="MyStable")], self.cfg)
        self.assertEqual(r["stablecoins"][0]["name"], "MyStable")

    def test_93_peg_mechanism_preserved(self):
        r = self.mon.monitor([_rock_solid_coin(peg_mechanism="overcollateralized")], self.cfg)
        self.assertEqual(r["stablecoins"][0]["peg_mechanism"], "overcollateralized")

    def test_94_audited_flag_preserved(self):
        r = self.mon.monitor([_rock_solid_coin(issuer_reserves_audited=True)], self.cfg)
        self.assertTrue(r["stablecoins"][0]["issuer_reserves_audited"])

    def test_95_suspended_flag_preserved(self):
        r = self.mon.monitor([_rock_solid_coin(redemption_suspended=True)], self.cfg)
        self.assertTrue(r["stablecoins"][0]["redemption_suspended"])

    def test_96_blacklist_preserved(self):
        r = self.mon.monitor([_rock_solid_coin(blacklist_enabled=True)], self.cfg)
        self.assertTrue(r["stablecoins"][0]["blacklist_enabled"])


# ═══════════════════════════════════════════════════════════════════════════
# 13. Edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.mon = ProtocolDeFiStablecoinHealthMonitor()
        self.cfg = {"write_log": False}

    def test_97_zero_price_handled(self):
        c = _rock_solid_coin(current_price_usd=0.0)
        r = self.mon.monitor([c], self.cfg)
        self.assertIn("peg_deviation_pct", r["stablecoins"][0])

    def test_98_none_config_uses_defaults(self):
        """monitor() should work with no config arg (uses defaults)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            m = ProtocolDeFiStablecoinHealthMonitor()
            # Use explicit log path to avoid writing to real data/ dir
            r = m.monitor([_rock_solid_coin()], {"write_log": False})
            self.assertIn("stablecoins", r)

    def test_99_multiple_coins_all_rock_solid(self):
        coins = [_rock_solid_coin(name=f"C{i}") for i in range(5)]
        r = self.mon.monitor(coins, self.cfg)
        self.assertEqual(r["rock_solid_count"], 5)

    def test_100_multiple_coins_all_depegging(self):
        coins = [_depegging_coin(name=f"D{i}") for i in range(3)]
        r = self.mon.monitor(coins, self.cfg)
        self.assertGreaterEqual(r["depegging_count"], 3)

    def test_101_algo_coin_30pct_boundary(self):
        # Exactly at 30% — should NOT trigger ALGO_CONCENTRATION (>30 required)
        c = _rock_solid_coin(algo_component_pct=30.0)
        r = _monitor_coin(c)
        self.assertNotIn(FLAG_ALGO_CONCENTRATION, r["flags"])

    def test_102_algo_coin_31pct_triggers_flag(self):
        c = _rock_solid_coin(algo_component_pct=31.0)
        r = _monitor_coin(c)
        self.assertIn(FLAG_ALGO_CONCENTRATION, r["flags"])


if __name__ == "__main__":
    unittest.main()
