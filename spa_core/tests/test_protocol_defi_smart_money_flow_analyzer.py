"""
Tests for MP-1115 — ProtocolDeFiSmartMoneyFlowAnalyzer
≥110 test cases using unittest (NOT pytest).
Run: python3 -m unittest spa_core.tests.test_protocol_defi_smart_money_flow_analyzer -v
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_smart_money_flow_analyzer import (
    ProtocolDeFiSmartMoneyFlowAnalyzer,
    analyze_smart_money_flow,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _analyze(
    tvl_now=100_000_000,
    tvl_24h_ago=100_000_000,
    tvl_7d_ago=100_000_000,
    depositors_now=1000,
    depositors_7d_ago=1000,
    top10_share=30.0,
    deposit_24h=500_000,
    withdrawal_24h=200_000,
    protocol="TestProto",
    log_path="/tmp/test_smf_log.json",
    write_log=False,
):
    a = ProtocolDeFiSmartMoneyFlowAnalyzer(log_path=log_path)
    return a.analyze(
        tvl_now_usd=tvl_now,
        tvl_24h_ago_usd=tvl_24h_ago,
        tvl_7d_ago_usd=tvl_7d_ago,
        unique_depositors_now=depositors_now,
        unique_depositors_7d_ago=depositors_7d_ago,
        top10_wallets_share_pct=top10_share,
        largest_single_deposit_24h_usd=deposit_24h,
        largest_single_withdrawal_24h_usd=withdrawal_24h,
        protocol_name=protocol,
        write_log=write_log,
    )


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------
class TestReturnStructure(unittest.TestCase):
    def test_returns_dict(self):
        r = _analyze()
        self.assertIsInstance(r, dict)

    def test_has_module_key(self):
        r = _analyze()
        self.assertEqual(r["module"], "MP-1115")

    def test_has_protocol_name(self):
        r = _analyze(protocol="Aave")
        self.assertEqual(r["protocol_name"], "Aave")

    def test_has_tvl_change_24h_pct(self):
        r = _analyze()
        self.assertIn("tvl_change_24h_pct", r)

    def test_has_tvl_change_7d_pct(self):
        r = _analyze()
        self.assertIn("tvl_change_7d_pct", r)

    def test_has_depositor_growth_7d_pct(self):
        r = _analyze()
        self.assertIn("depositor_growth_7d_pct", r)

    def test_has_avg_position_size_usd(self):
        r = _analyze()
        self.assertIn("avg_position_size_usd", r)

    def test_has_whale_concentration_score(self):
        r = _analyze()
        self.assertIn("whale_concentration_score", r)

    def test_has_flow_signal(self):
        r = _analyze()
        self.assertIn("flow_signal", r)

    def test_has_smart_money_label(self):
        r = _analyze()
        self.assertIn("smart_money_label", r)

    def test_has_timestamp(self):
        r = _analyze()
        self.assertIn("timestamp", r)


class TestTVLChange24h(unittest.TestCase):
    def test_no_change_is_zero(self):
        r = _analyze(tvl_now=100_000_000, tvl_24h_ago=100_000_000)
        self.assertAlmostEqual(r["tvl_change_24h_pct"], 0.0, places=4)

    def test_10_pct_increase(self):
        r = _analyze(tvl_now=110_000_000, tvl_24h_ago=100_000_000)
        self.assertAlmostEqual(r["tvl_change_24h_pct"], 10.0, places=4)

    def test_10_pct_decrease(self):
        r = _analyze(tvl_now=90_000_000, tvl_24h_ago=100_000_000)
        self.assertAlmostEqual(r["tvl_change_24h_pct"], -10.0, places=4)

    def test_50_pct_increase(self):
        r = _analyze(tvl_now=150_000_000, tvl_24h_ago=100_000_000)
        self.assertAlmostEqual(r["tvl_change_24h_pct"], 50.0, places=4)

    def test_zero_base_returns_zero(self):
        r = _analyze(tvl_now=100_000_000, tvl_24h_ago=0)
        self.assertAlmostEqual(r["tvl_change_24h_pct"], 0.0, places=4)

    def test_negative_change(self):
        r = _analyze(tvl_now=80_000_000, tvl_24h_ago=100_000_000)
        self.assertAlmostEqual(r["tvl_change_24h_pct"], -20.0, places=4)


class TestTVLChange7d(unittest.TestCase):
    def test_no_change(self):
        r = _analyze(tvl_now=100_000_000, tvl_7d_ago=100_000_000)
        self.assertAlmostEqual(r["tvl_change_7d_pct"], 0.0, places=4)

    def test_20_pct_increase(self):
        r = _analyze(tvl_now=120_000_000, tvl_7d_ago=100_000_000)
        self.assertAlmostEqual(r["tvl_change_7d_pct"], 20.0, places=4)

    def test_25_pct_decrease(self):
        r = _analyze(tvl_now=75_000_000, tvl_7d_ago=100_000_000)
        self.assertAlmostEqual(r["tvl_change_7d_pct"], -25.0, places=4)

    def test_zero_7d_base_returns_zero(self):
        r = _analyze(tvl_now=100_000_000, tvl_7d_ago=0)
        self.assertAlmostEqual(r["tvl_change_7d_pct"], 0.0, places=4)


class TestDepositorGrowth(unittest.TestCase):
    def test_no_change(self):
        r = _analyze(depositors_now=1000, depositors_7d_ago=1000)
        self.assertAlmostEqual(r["depositor_growth_7d_pct"], 0.0, places=4)

    def test_20_pct_growth(self):
        r = _analyze(depositors_now=1200, depositors_7d_ago=1000)
        self.assertAlmostEqual(r["depositor_growth_7d_pct"], 20.0, places=4)

    def test_50_pct_decline(self):
        r = _analyze(depositors_now=500, depositors_7d_ago=1000)
        self.assertAlmostEqual(r["depositor_growth_7d_pct"], -50.0, places=4)

    def test_zero_base_depositors(self):
        r = _analyze(depositors_now=100, depositors_7d_ago=0)
        self.assertAlmostEqual(r["depositor_growth_7d_pct"], 0.0, places=4)


class TestAvgPositionSize(unittest.TestCase):
    def test_basic_calculation(self):
        r = _analyze(tvl_now=10_000_000, depositors_now=1000)
        self.assertAlmostEqual(r["avg_position_size_usd"], 10_000.0, places=2)

    def test_single_depositor(self):
        r = _analyze(tvl_now=5_000_000, depositors_now=1)
        self.assertAlmostEqual(r["avg_position_size_usd"], 5_000_000.0, places=2)

    def test_zero_depositors_returns_tvl(self):
        r = _analyze(tvl_now=1_000_000, depositors_now=0)
        self.assertAlmostEqual(r["avg_position_size_usd"], 1_000_000.0, places=2)

    def test_large_depositor_count(self):
        r = _analyze(tvl_now=1_000_000, depositors_now=10000)
        self.assertAlmostEqual(r["avg_position_size_usd"], 100.0, places=2)


class TestWhaleConcentrationScore(unittest.TestCase):
    def test_score_is_int(self):
        r = _analyze()
        self.assertIsInstance(r["whale_concentration_score"], int)

    def test_score_range_0_to_100(self):
        r = _analyze(top10_share=0.0, deposit_24h=0, withdrawal_24h=0)
        self.assertGreaterEqual(r["whale_concentration_score"], 0)
        self.assertLessEqual(r["whale_concentration_score"], 100)

    def test_high_top10_share_high_score(self):
        r = _analyze(top10_share=90.0, deposit_24h=0, withdrawal_24h=0)
        self.assertGreater(r["whale_concentration_score"], 50)

    def test_zero_share_zero_move_low_score(self):
        r = _analyze(top10_share=0.0, deposit_24h=0, withdrawal_24h=0, tvl_now=100_000_000)
        self.assertEqual(r["whale_concentration_score"], 0)

    def test_100_pct_top10_share_is_max_influence(self):
        r = _analyze(top10_share=100.0, deposit_24h=0, withdrawal_24h=0)
        self.assertGreater(r["whale_concentration_score"], 50)

    def test_large_withdrawal_increases_score(self):
        r_small = _analyze(tvl_now=100_000_000, withdrawal_24h=100_000, top10_share=20)
        r_large = _analyze(tvl_now=100_000_000, withdrawal_24h=50_000_000, top10_share=20)
        self.assertGreater(r_large["whale_concentration_score"], r_small["whale_concentration_score"])

    def test_score_capped_at_100(self):
        r = _analyze(top10_share=100.0, deposit_24h=1_000_000_000, withdrawal_24h=1_000_000_000, tvl_now=1_000)
        self.assertLessEqual(r["whale_concentration_score"], 100)


class TestFlowSignal(unittest.TestCase):
    def test_strong_inflow_above_10pct(self):
        r = _analyze(tvl_now=115_000_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "STRONG_INFLOW")

    def test_exact_10pct_is_strong_inflow(self):
        r = _analyze(tvl_now=110_000_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "STRONG_INFLOW")

    def test_moderate_inflow_2_to_10(self):
        r = _analyze(tvl_now=105_000_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "MODERATE_INFLOW")

    def test_neutral_near_zero(self):
        r = _analyze(tvl_now=100_500_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "NEUTRAL")

    def test_neutral_zero_change(self):
        r = _analyze(tvl_now=100_000_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "NEUTRAL")

    def test_neutral_small_negative(self):
        r = _analyze(tvl_now=98_500_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "NEUTRAL")

    def test_moderate_outflow_2_to_10pct_drop(self):
        r = _analyze(tvl_now=94_000_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "MODERATE_OUTFLOW")

    def test_whale_exit_below_minus_10(self):
        r = _analyze(tvl_now=85_000_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "WHALE_EXIT")

    def test_whale_exit_massive_drop(self):
        r = _analyze(tvl_now=40_000_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "WHALE_EXIT")

    def test_flow_signal_is_string(self):
        r = _analyze()
        self.assertIsInstance(r["flow_signal"], str)

    def test_flow_signal_valid_values(self):
        valid = {"STRONG_INFLOW", "MODERATE_INFLOW", "NEUTRAL", "MODERATE_OUTFLOW", "WHALE_EXIT"}
        for tvl_now in [120_000_000, 105_000_000, 100_000_000, 93_000_000, 80_000_000]:
            r = _analyze(tvl_now=tvl_now, tvl_24h_ago=100_000_000)
            self.assertIn(r["flow_signal"], valid)

    def test_exactly_minus_2_is_neutral(self):
        r = _analyze(tvl_now=98_000_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "NEUTRAL")

    def test_exactly_minus_10_is_moderate_outflow(self):
        r = _analyze(tvl_now=90_000_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "MODERATE_OUTFLOW")


class TestSmartMoneyLabel(unittest.TestCase):
    def test_accumulation_tvl_plus10_dep_plus5(self):
        # TVL +12%, depositors +8%
        r = _analyze(
            tvl_now=112_000_000, tvl_7d_ago=100_000_000,
            depositors_now=1080, depositors_7d_ago=1000,
        )
        self.assertEqual(r["smart_money_label"], "ACCUMULATION")

    def test_growing_tvl_plus5_only(self):
        # TVL +7%, depositors -2% (not qualifying for ACCUMULATION)
        r = _analyze(
            tvl_now=107_000_000, tvl_7d_ago=100_000_000,
            depositors_now=980, depositors_7d_ago=1000,
        )
        self.assertEqual(r["smart_money_label"], "GROWING")

    def test_growing_depositors_plus10_only(self):
        # TVL +1%, depositors +15%
        r = _analyze(
            tvl_now=101_000_000, tvl_7d_ago=100_000_000,
            depositors_now=1150, depositors_7d_ago=1000,
        )
        self.assertEqual(r["smart_money_label"], "GROWING")

    def test_stable_near_zero_tvl(self):
        r = _analyze(
            tvl_now=101_000_000, tvl_7d_ago=100_000_000,
            depositors_now=1000, depositors_7d_ago=1000,
        )
        self.assertEqual(r["smart_money_label"], "STABLE")

    def test_stable_exact_zero_change(self):
        r = _analyze(
            tvl_now=100_000_000, tvl_7d_ago=100_000_000,
            depositors_now=1000, depositors_7d_ago=1000,
        )
        self.assertEqual(r["smart_money_label"], "STABLE")

    def test_distribution_tvl_down_depositors_up(self):
        # TVL -10%, depositors +5%
        r = _analyze(
            tvl_now=90_000_000, tvl_7d_ago=100_000_000,
            depositors_now=1050, depositors_7d_ago=1000,
        )
        self.assertEqual(r["smart_money_label"], "DISTRIBUTION")

    def test_panic_exit_tvl_below_minus_15(self):
        # TVL -20%
        r = _analyze(
            tvl_now=80_000_000, tvl_7d_ago=100_000_000,
            depositors_now=1000, depositors_7d_ago=1000,
        )
        self.assertEqual(r["smart_money_label"], "PANIC_EXIT")

    def test_panic_exit_tvl_minus_5_depositors_falling(self):
        # TVL -7%, depositors -10%
        r = _analyze(
            tvl_now=93_000_000, tvl_7d_ago=100_000_000,
            depositors_now=900, depositors_7d_ago=1000,
        )
        self.assertEqual(r["smart_money_label"], "PANIC_EXIT")

    def test_label_is_string(self):
        r = _analyze()
        self.assertIsInstance(r["smart_money_label"], str)

    def test_label_valid_values(self):
        valid = {"ACCUMULATION", "GROWING", "STABLE", "DISTRIBUTION", "PANIC_EXIT"}
        r = _analyze()
        self.assertIn(r["smart_money_label"], valid)

    def test_panic_exit_exact_minus_15(self):
        # TVL exactly -15%
        r = _analyze(
            tvl_now=85_000_000, tvl_7d_ago=100_000_000,
            depositors_now=900, depositors_7d_ago=1000,
        )
        self.assertEqual(r["smart_money_label"], "PANIC_EXIT")

    def test_accumulation_exact_boundaries(self):
        # TVL exactly +10%, depositors exactly +5%
        r = _analyze(
            tvl_now=110_000_000, tvl_7d_ago=100_000_000,
            depositors_now=1050, depositors_7d_ago=1000,
        )
        self.assertEqual(r["smart_money_label"], "ACCUMULATION")

    def test_stable_small_negative_tvl(self):
        # TVL -3% (within |<5%|), depositors flat
        r = _analyze(
            tvl_now=97_000_000, tvl_7d_ago=100_000_000,
            depositors_now=1000, depositors_7d_ago=1000,
        )
        self.assertEqual(r["smart_money_label"], "STABLE")

    def test_growing_high_depositor_growth_low_tvl(self):
        # TVL +1%, depositors +20%
        r = _analyze(
            tvl_now=101_000_000, tvl_7d_ago=100_000_000,
            depositors_now=1200, depositors_7d_ago=1000,
        )
        self.assertEqual(r["smart_money_label"], "GROWING")


class TestFlowSignalBoundaries(unittest.TestCase):
    """Detailed boundary tests for flow_signal thresholds."""

    def test_exactly_plus_2_is_moderate_inflow(self):
        r = _analyze(tvl_now=102_000_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "MODERATE_INFLOW")

    def test_just_below_plus_2_is_neutral(self):
        r = _analyze(tvl_now=101_900_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "NEUTRAL")

    def test_just_above_minus_2_is_neutral(self):
        r = _analyze(tvl_now=98_100_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "NEUTRAL")

    def test_just_below_minus_10_is_whale_exit(self):
        r = _analyze(tvl_now=89_500_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "WHALE_EXIT")

    def test_just_above_minus_10_is_moderate_outflow(self):
        r = _analyze(tvl_now=90_500_000, tvl_24h_ago=100_000_000)
        self.assertEqual(r["flow_signal"], "MODERATE_OUTFLOW")


class TestLogging(unittest.TestCase):
    def test_log_file_created(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            log_path = f.name
        os.unlink(log_path)
        a = ProtocolDeFiSmartMoneyFlowAnalyzer(log_path=log_path)
        a.analyze(
            100_000_000, 100_000_000, 100_000_000,
            1000, 1000, 30.0, 500_000, 200_000,
            write_log=True,
        )
        self.assertTrue(os.path.exists(log_path))
        os.unlink(log_path)

    def test_log_is_list(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            log_path = f.name
        os.unlink(log_path)
        a = ProtocolDeFiSmartMoneyFlowAnalyzer(log_path=log_path)
        a.analyze(100_000_000, 100_000_000, 100_000_000, 1000, 1000, 30.0, 500_000, 200_000, write_log=True)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        os.unlink(log_path)

    def test_log_accumulates_5_entries(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            log_path = f.name
        os.unlink(log_path)
        a = ProtocolDeFiSmartMoneyFlowAnalyzer(log_path=log_path)
        for _ in range(5):
            a.analyze(100_000_000, 100_000_000, 100_000_000, 1000, 1000, 30.0, 500_000, 200_000, write_log=True)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)
        os.unlink(log_path)

    def test_log_ring_buffer_caps_at_100(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            log_path = f.name
        os.unlink(log_path)
        a = ProtocolDeFiSmartMoneyFlowAnalyzer(log_path=log_path)
        for _ in range(110):
            a.analyze(100_000_000, 100_000_000, 100_000_000, 1000, 1000, 30.0, 500_000, 200_000, write_log=True)
        with open(log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)
        os.unlink(log_path)

    def test_log_entry_has_log_id(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            log_path = f.name
        os.unlink(log_path)
        a = ProtocolDeFiSmartMoneyFlowAnalyzer(log_path=log_path)
        a.analyze(100_000_000, 100_000_000, 100_000_000, 1000, 1000, 30.0, 500_000, 200_000, write_log=True)
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("log_id", data[0])
        os.unlink(log_path)

    def test_log_entry_has_module_key(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            log_path = f.name
        os.unlink(log_path)
        a = ProtocolDeFiSmartMoneyFlowAnalyzer(log_path=log_path)
        a.analyze(100_000_000, 100_000_000, 100_000_000, 1000, 1000, 30.0, 500_000, 200_000, write_log=True)
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(data[0]["module"], "MP-1115")
        os.unlink(log_path)

    def test_no_log_when_write_false(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            log_path = f.name
        os.unlink(log_path)
        a = ProtocolDeFiSmartMoneyFlowAnalyzer(log_path=log_path)
        a.analyze(100_000_000, 100_000_000, 100_000_000, 1000, 1000, 30.0, 500_000, 200_000, write_log=False)
        self.assertFalse(os.path.exists(log_path))


class TestConvenienceFunction(unittest.TestCase):
    def test_returns_dict(self):
        r = analyze_smart_money_flow(100_000_000, 100_000_000, 100_000_000, 1000, 1000, 30.0, 500_000, 200_000)
        self.assertIsInstance(r, dict)

    def test_protocol_name_passed(self):
        r = analyze_smart_money_flow(100_000_000, 100_000_000, 100_000_000, 1000, 1000, 30.0, 500_000, 200_000, protocol_name="Aave")
        self.assertEqual(r["protocol_name"], "Aave")

    def test_no_log_by_default(self):
        tmp = "/tmp/conv_smf_test_log.json"
        if os.path.exists(tmp):
            os.unlink(tmp)
        analyze_smart_money_flow(100_000_000, 100_000_000, 100_000_000, 1000, 1000, 30.0, 500_000, 200_000, log_path=tmp, write_log=False)
        self.assertFalse(os.path.exists(tmp))

    def test_flow_signal_present(self):
        r = analyze_smart_money_flow(120_000_000, 100_000_000, 100_000_000, 1000, 1000, 30.0, 500_000, 200_000)
        self.assertIn("flow_signal", r)


class TestStaticMethods(unittest.TestCase):
    def test_pct_change_increase(self):
        pct = ProtocolDeFiSmartMoneyFlowAnalyzer._pct_change(110, 100)
        self.assertAlmostEqual(pct, 10.0, places=4)

    def test_pct_change_decrease(self):
        pct = ProtocolDeFiSmartMoneyFlowAnalyzer._pct_change(90, 100)
        self.assertAlmostEqual(pct, -10.0, places=4)

    def test_pct_change_zero_base(self):
        pct = ProtocolDeFiSmartMoneyFlowAnalyzer._pct_change(100, 0)
        self.assertAlmostEqual(pct, 0.0, places=4)

    def test_avg_position_normal(self):
        avg = ProtocolDeFiSmartMoneyFlowAnalyzer._avg_position(10_000_000, 1000)
        self.assertAlmostEqual(avg, 10_000.0, places=2)

    def test_avg_position_zero_depositors(self):
        avg = ProtocolDeFiSmartMoneyFlowAnalyzer._avg_position(5_000_000, 0)
        self.assertAlmostEqual(avg, 5_000_000.0, places=2)

    def test_flow_signal_strong_inflow(self):
        self.assertEqual(
            ProtocolDeFiSmartMoneyFlowAnalyzer._flow_signal(15.0), "STRONG_INFLOW"
        )

    def test_flow_signal_moderate_inflow(self):
        self.assertEqual(
            ProtocolDeFiSmartMoneyFlowAnalyzer._flow_signal(5.0), "MODERATE_INFLOW"
        )

    def test_flow_signal_neutral(self):
        self.assertEqual(
            ProtocolDeFiSmartMoneyFlowAnalyzer._flow_signal(0.0), "NEUTRAL"
        )

    def test_flow_signal_moderate_outflow(self):
        self.assertEqual(
            ProtocolDeFiSmartMoneyFlowAnalyzer._flow_signal(-5.0), "MODERATE_OUTFLOW"
        )

    def test_flow_signal_whale_exit(self):
        self.assertEqual(
            ProtocolDeFiSmartMoneyFlowAnalyzer._flow_signal(-15.0), "WHALE_EXIT"
        )

    def test_smart_money_label_accumulation(self):
        self.assertEqual(
            ProtocolDeFiSmartMoneyFlowAnalyzer._smart_money_label(12.0, 7.0),
            "ACCUMULATION",
        )

    def test_smart_money_label_growing_tvl(self):
        self.assertEqual(
            ProtocolDeFiSmartMoneyFlowAnalyzer._smart_money_label(7.0, 2.0),
            "GROWING",
        )

    def test_smart_money_label_stable(self):
        self.assertEqual(
            ProtocolDeFiSmartMoneyFlowAnalyzer._smart_money_label(0.0, 0.0),
            "STABLE",
        )

    def test_smart_money_label_distribution(self):
        self.assertEqual(
            ProtocolDeFiSmartMoneyFlowAnalyzer._smart_money_label(-10.0, 5.0),
            "DISTRIBUTION",
        )

    def test_smart_money_label_panic_exit_deep(self):
        self.assertEqual(
            ProtocolDeFiSmartMoneyFlowAnalyzer._smart_money_label(-20.0, 0.0),
            "PANIC_EXIT",
        )

    def test_whale_concentration_score_zero(self):
        score = ProtocolDeFiSmartMoneyFlowAnalyzer._whale_concentration_score(0.0, 0, 0, 1_000_000)
        self.assertEqual(score, 0)

    def test_whale_concentration_score_max(self):
        score = ProtocolDeFiSmartMoneyFlowAnalyzer._whale_concentration_score(100.0, 1_000_000, 1_000_000, 1_000)
        self.assertEqual(score, 100)


class TestRealWorldScenarios(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiSmartMoneyFlowAnalyzer(log_path="/tmp/test_smf_log.json")

    def _run(self, **kw):
        defaults = dict(
            tvl_now_usd=100_000_000,
            tvl_24h_ago_usd=100_000_000,
            tvl_7d_ago_usd=100_000_000,
            unique_depositors_now=1000,
            unique_depositors_7d_ago=1000,
            top10_wallets_share_pct=30.0,
            largest_single_deposit_24h_usd=500_000,
            largest_single_withdrawal_24h_usd=200_000,
            protocol_name="Test",
            write_log=False,
        )
        defaults.update(kw)
        return self.a.analyze(**defaults)

    def test_aave_healthy_growth_scenario(self):
        r = self._run(tvl_now_usd=108_000_000, tvl_24h_ago_usd=107_000_000, tvl_7d_ago_usd=100_000_000, unique_depositors_now=1100, unique_depositors_7d_ago=1000)
        self.assertIn(r["smart_money_label"], {"ACCUMULATION", "GROWING"})

    def test_protocol_rug_pull_scenario(self):
        r = self._run(tvl_now_usd=20_000_000, tvl_24h_ago_usd=100_000_000, tvl_7d_ago_usd=100_000_000)
        self.assertEqual(r["flow_signal"], "WHALE_EXIT")
        self.assertEqual(r["smart_money_label"], "PANIC_EXIT")

    def test_new_protocol_launch_scenario(self):
        # TVL surges, many new depositors
        r = self._run(tvl_now_usd=200_000_000, tvl_24h_ago_usd=100_000_000, tvl_7d_ago_usd=100_000_000, unique_depositors_now=2000, unique_depositors_7d_ago=1000)
        self.assertEqual(r["flow_signal"], "STRONG_INFLOW")
        self.assertEqual(r["smart_money_label"], "ACCUMULATION")

    def test_stable_mature_protocol(self):
        r = self._run(tvl_now_usd=100_500_000, tvl_24h_ago_usd=100_000_000, tvl_7d_ago_usd=100_200_000)
        self.assertEqual(r["flow_signal"], "NEUTRAL")
        self.assertEqual(r["smart_money_label"], "STABLE")

    def test_whale_leaving_retail_staying(self):
        # Distribution: TVL -10%, depositors +5%
        r = self._run(tvl_now_usd=90_000_000, tvl_7d_ago_usd=100_000_000, unique_depositors_now=1050, unique_depositors_7d_ago=1000)
        self.assertEqual(r["smart_money_label"], "DISTRIBUTION")

    def test_avg_position_size_whale_indicator(self):
        # High avg position = few big wallets
        r = self._run(tvl_now_usd=100_000_000, unique_depositors_now=10)
        self.assertEqual(r["avg_position_size_usd"], 10_000_000.0)

    def test_avg_position_size_retail_indicator(self):
        r = self._run(tvl_now_usd=100_000_000, unique_depositors_now=100_000)
        self.assertEqual(r["avg_position_size_usd"], 1_000.0)

    def test_protocol_name_stored_correctly(self):
        r = self._run(protocol_name="Compound V3")
        self.assertEqual(r["protocol_name"], "Compound V3")

    def test_type_coercion_float_input(self):
        r = self._run(tvl_now_usd=100_000_000.0, unique_depositors_now=1000)
        self.assertIsInstance(r["avg_position_size_usd"], float)

    def test_type_coercion_string_numerics(self):
        a = ProtocolDeFiSmartMoneyFlowAnalyzer(log_path="/tmp/test_smf_log.json")
        # Should not raise; string numerics are coerced
        r = a.analyze(
            tvl_now_usd="100000000",
            tvl_24h_ago_usd="100000000",
            tvl_7d_ago_usd="100000000",
            unique_depositors_now="1000",
            unique_depositors_7d_ago="1000",
            top10_wallets_share_pct="30.0",
            largest_single_deposit_24h_usd="500000",
            largest_single_withdrawal_24h_usd="200000",
            protocol_name="Test",
            write_log=False,
        )
        self.assertIsInstance(r, dict)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.a = ProtocolDeFiSmartMoneyFlowAnalyzer(log_path="/tmp/test_smf_log.json")

    def test_zero_tvl(self):
        r = self.a.analyze(0, 0, 0, 0, 0, 0.0, 0, 0, write_log=False)
        self.assertEqual(r["tvl_change_24h_pct"], 0.0)

    def test_very_large_tvl(self):
        r = self.a.analyze(1e12, 9e11, 8e11, 1000, 1000, 30.0, 1e10, 1e9, write_log=False)
        self.assertIsInstance(r, dict)

    def test_zero_top10_share(self):
        r = self.a.analyze(100_000_000, 100_000_000, 100_000_000, 1000, 1000, 0.0, 0, 0, write_log=False)
        self.assertEqual(r["whale_concentration_score"], 0)

    def test_100_top10_share(self):
        r = self.a.analyze(100_000_000, 100_000_000, 100_000_000, 1000, 1000, 100.0, 0, 0, write_log=False)
        self.assertGreater(r["whale_concentration_score"], 50)

    def test_empty_protocol_name(self):
        r = self.a.analyze(100_000_000, 100_000_000, 100_000_000, 1000, 1000, 30.0, 500_000, 200_000, protocol_name="", write_log=False)
        self.assertEqual(r["protocol_name"], "")

    def test_tvl_from_zero_to_positive(self):
        r = self.a.analyze(
            tvl_now_usd=10_000_000, tvl_24h_ago_usd=0,
            tvl_7d_ago_usd=0, unique_depositors_now=100, unique_depositors_7d_ago=0,
            top10_wallets_share_pct=30.0, largest_single_deposit_24h_usd=500_000,
            largest_single_withdrawal_24h_usd=0, write_log=False
        )
        self.assertAlmostEqual(r["tvl_change_24h_pct"], 0.0, places=4)

    def test_depositor_growth_from_zero(self):
        r = self.a.analyze(
            tvl_now_usd=100_000_000, tvl_24h_ago_usd=100_000_000,
            tvl_7d_ago_usd=100_000_000, unique_depositors_now=100,
            unique_depositors_7d_ago=0, top10_wallets_share_pct=30.0,
            largest_single_deposit_24h_usd=500_000, largest_single_withdrawal_24h_usd=200_000,
            write_log=False,
        )
        self.assertAlmostEqual(r["depositor_growth_7d_pct"], 0.0, places=4)


if __name__ == "__main__":
    unittest.main()
