"""
Tests for MP-673: DEXRoutingRiskAnalyzer
≥60 test cases using unittest only (no pytest, no numpy, no pandas).
"""

import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.dex_routing_risk_analyzer import (
    MAX_ENTRIES,
    DEXRoutingRiskAnalyzer,
    RoutingHop,
    RoutingProfile,
    RoutingRiskReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hop(dex_id="uniswap", slippage_bps=10.0, tvl=5_000_000.0) -> RoutingHop:
    return RoutingHop(
        dex_id=dex_id,
        pool_address="0xABCD",
        token_in="USDC",
        token_out="WETH",
        pool_tvl_usd=tvl,
        hop_slippage_bps=slippage_bps,
    )


def _profile(
    route_id="route_test",
    trade_amount_usd=10_000.0,
    hops=None,
    gas_price_gwei=20.0,
    eth_price_usd=2_000.0,
    max_slippage_tolerance_bps=50.0,
) -> RoutingProfile:
    if hops is None:
        hops = [_hop()]
    return RoutingProfile(
        route_id=route_id,
        trade_amount_usd=trade_amount_usd,
        hops=hops,
        gas_price_gwei=gas_price_gwei,
        eth_price_usd=eth_price_usd,
        max_slippage_tolerance_bps=max_slippage_tolerance_bps,
    )


def _make_analyzer():
    return DEXRoutingRiskAnalyzer()


# ---------------------------------------------------------------------------
# _total_slippage_bps
# ---------------------------------------------------------------------------

class TestTotalSlippageBps(unittest.TestCase):
    def setUp(self):
        self.az = _make_analyzer()

    def test_single_hop_returns_hop_slippage(self):
        hops = [_hop(slippage_bps=25.0)]
        self.assertAlmostEqual(self.az._total_slippage_bps(hops), 25.0)

    def test_two_hops_sums_correctly(self):
        hops = [_hop(slippage_bps=10.0), _hop(slippage_bps=15.0)]
        self.assertAlmostEqual(self.az._total_slippage_bps(hops), 25.0)

    def test_three_hops_sums_correctly(self):
        hops = [_hop(slippage_bps=10.0), _hop(slippage_bps=20.0), _hop(slippage_bps=30.0)]
        self.assertAlmostEqual(self.az._total_slippage_bps(hops), 60.0)

    def test_empty_hops_returns_zero(self):
        self.assertAlmostEqual(self.az._total_slippage_bps([]), 0.0)


# ---------------------------------------------------------------------------
# _cumulative_slippage_pct
# ---------------------------------------------------------------------------

class TestCumulativeSlippagePct(unittest.TestCase):
    def setUp(self):
        self.az = _make_analyzer()

    def test_100bps_gives_1pct(self):
        self.assertAlmostEqual(self.az._cumulative_slippage_pct(100.0), 1.0)

    def test_50bps_gives_05pct(self):
        self.assertAlmostEqual(self.az._cumulative_slippage_pct(50.0), 0.5)

    def test_10bps_gives_01pct(self):
        self.assertAlmostEqual(self.az._cumulative_slippage_pct(10.0), 0.1)

    def test_zero_bps_gives_zero_pct(self):
        self.assertAlmostEqual(self.az._cumulative_slippage_pct(0.0), 0.0)


# ---------------------------------------------------------------------------
# _gas_cost_usd
# ---------------------------------------------------------------------------

class TestGasCostUsd(unittest.TestCase):
    def setUp(self):
        self.az = _make_analyzer()

    def test_1hop_20gwei_2000eth_gives_6usd(self):
        # 150000 * 1 * 20 * 1e-9 * 2000 = 6.0
        self.assertAlmostEqual(self.az._gas_cost_usd(1, 20.0, 2000.0), 6.0)

    def test_2hops_20gwei_2000eth_gives_12usd(self):
        self.assertAlmostEqual(self.az._gas_cost_usd(2, 20.0, 2000.0), 12.0)

    def test_3hops_50gwei_3000eth_gives_67_5usd(self):
        # 150000 * 3 * 50 * 1e-9 * 3000 = 67.5
        self.assertAlmostEqual(self.az._gas_cost_usd(3, 50.0, 3000.0), 67.5)

    def test_1hop_100gwei_4000eth_gives_60usd(self):
        # 150000 * 1 * 100 * 1e-9 * 4000 = 60.0
        self.assertAlmostEqual(self.az._gas_cost_usd(1, 100.0, 4000.0), 60.0)

    def test_4hops_30gwei_1500eth_gives_27usd(self):
        # 150000 * 4 * 30 * 1e-9 * 1500 = 27.0
        self.assertAlmostEqual(self.az._gas_cost_usd(4, 30.0, 1500.0), 27.0)


# ---------------------------------------------------------------------------
# _gas_as_pct_of_trade
# ---------------------------------------------------------------------------

class TestGasAsPctOfTrade(unittest.TestCase):
    def setUp(self):
        self.az = _make_analyzer()

    def test_gas_6_trade_10000_gives_006pct(self):
        self.assertAlmostEqual(self.az._gas_as_pct_of_trade(6.0, 10_000.0), 0.06)

    def test_gas_100_trade_1000_gives_10pct(self):
        self.assertAlmostEqual(self.az._gas_as_pct_of_trade(100.0, 1_000.0), 10.0)

    def test_gas_50_trade_1000_gives_5pct(self):
        self.assertAlmostEqual(self.az._gas_as_pct_of_trade(50.0, 1_000.0), 5.0)

    def test_zero_trade_returns_zero(self):
        self.assertAlmostEqual(self.az._gas_as_pct_of_trade(100.0, 0.0), 0.0)


# ---------------------------------------------------------------------------
# _mev_risk_score
# ---------------------------------------------------------------------------

class TestMevRiskScore(unittest.TestCase):
    def setUp(self):
        self.az = _make_analyzer()

    def test_1hop_small_trade_base_plus_hop(self):
        # 0.1 + 0.15 = 0.25
        self.assertAlmostEqual(self.az._mev_risk_score(1, 5_000.0), 0.25)

    def test_1hop_large_trade_adds_020(self):
        # 0.1 + 0.15 + 0.2 = 0.45
        self.assertAlmostEqual(self.az._mev_risk_score(1, 10_001.0), 0.45)

    def test_exactly_10000_does_not_trigger_large_trade(self):
        # 10000 is NOT > 10000
        self.assertAlmostEqual(self.az._mev_risk_score(1, 10_000.0), 0.25)

    def test_2hops_small_trade(self):
        # 0.1 + 0.30 = 0.40
        self.assertAlmostEqual(self.az._mev_risk_score(2, 5_000.0), 0.40)

    def test_3hops_small_trade(self):
        # 0.1 + 0.45 = 0.55
        self.assertAlmostEqual(self.az._mev_risk_score(3, 5_000.0), 0.55)

    def test_4hops_small_trade(self):
        # 0.1 + 0.60 = 0.70
        self.assertAlmostEqual(self.az._mev_risk_score(4, 5_000.0), 0.70)

    def test_capped_at_1_with_6_hops(self):
        # 0.1 + 0.9 = 1.0 capped
        self.assertAlmostEqual(self.az._mev_risk_score(6, 5_000.0), 1.0)

    def test_capped_at_1_with_5_hops_large_trade(self):
        # 0.1 + 0.75 + 0.2 = 1.05 → capped 1.0
        self.assertAlmostEqual(self.az._mev_risk_score(5, 20_000.0), 1.0)


# ---------------------------------------------------------------------------
# _execution_risk
# ---------------------------------------------------------------------------

class TestExecutionRisk(unittest.TestCase):
    def setUp(self):
        self.az = _make_analyzer()

    def test_slippage_exceeds_tolerance_is_critical(self):
        self.assertEqual(self.az._execution_risk(120.0, 100.0, 1, 0.5), "CRITICAL")

    def test_slippage_exactly_equal_tolerance_not_critical(self):
        # 100 is NOT > 100
        result = self.az._execution_risk(100.0, 100.0, 1, 0.5)
        self.assertNotEqual(result, "CRITICAL")

    def test_4hops_under_tolerance_is_high(self):
        self.assertEqual(self.az._execution_risk(80.0, 100.0, 4, 0.5), "HIGH")

    def test_5hops_under_tolerance_is_high(self):
        self.assertEqual(self.az._execution_risk(80.0, 100.0, 5, 0.5), "HIGH")

    def test_2hops_under_tolerance_is_medium(self):
        self.assertEqual(self.az._execution_risk(10.0, 100.0, 2, 1.0), "MEDIUM")

    def test_high_gas_pct_triggers_medium(self):
        # 1 hop, gas > 5% → MEDIUM
        self.assertEqual(self.az._execution_risk(10.0, 100.0, 1, 6.0), "MEDIUM")

    def test_exactly_5_gas_pct_not_medium_from_gas(self):
        # 5.0 is NOT > 5, 1 hop < 2 → LOW
        self.assertEqual(self.az._execution_risk(10.0, 100.0, 1, 5.0), "LOW")

    def test_1hop_low_gas_under_tolerance_is_low(self):
        self.assertEqual(self.az._execution_risk(10.0, 100.0, 1, 0.5), "LOW")


# ---------------------------------------------------------------------------
# _expected_output_usd
# ---------------------------------------------------------------------------

class TestExpectedOutputUsd(unittest.TestCase):
    def setUp(self):
        self.az = _make_analyzer()

    def test_basic_calculation(self):
        # trade=10000, cumulative=1.0%, gas=50
        # 10000*(1-0.01) - 50 = 9900 - 50 = 9850
        self.assertAlmostEqual(self.az._expected_output_usd(10_000.0, 1.0, 50.0), 9850.0)

    def test_small_slippage_small_gas(self):
        # trade=1000, cum=0.1%, gas=6
        # 1000*(1-0.001) - 6 = 999 - 6 = 993
        self.assertAlmostEqual(self.az._expected_output_usd(1_000.0, 0.1, 6.0), 993.0)

    def test_never_negative(self):
        # Huge gas eats all value
        result = self.az._expected_output_usd(100.0, 50.0, 200.0)
        self.assertGreaterEqual(result, 0.0)

    def test_zero_slippage_zero_gas_returns_trade_amount(self):
        self.assertAlmostEqual(self.az._expected_output_usd(5_000.0, 0.0, 0.0), 5_000.0)

    def test_exact_zero_output_when_losses_equal_trade(self):
        # 1000*(1-1.0) - 0 = 0
        self.assertAlmostEqual(self.az._expected_output_usd(1_000.0, 100.0, 0.0), 0.0)


# ---------------------------------------------------------------------------
# _verdict
# ---------------------------------------------------------------------------

class TestVerdict(unittest.TestCase):
    def setUp(self):
        self.az = _make_analyzer()

    def test_critical_risk_gives_reject(self):
        self.assertEqual(self.az._verdict("CRITICAL", 9900.0, 10_000.0, 1, 0.5), "REJECT")

    def test_low_expected_output_gives_reject(self):
        # output 9600 < 10000*0.97=9700 → REJECT
        self.assertEqual(self.az._verdict("LOW", 9_600.0, 10_000.0, 1, 0.5), "REJECT")

    def test_output_exactly_97pct_no_reject(self):
        # 9700 is NOT < 9700
        result = self.az._verdict("LOW", 9_700.0, 10_000.0, 1, 0.5)
        self.assertNotEqual(result, "REJECT")

    def test_3hop_good_output_gives_split(self):
        # hop_count=3 >= 3 → SPLIT
        self.assertEqual(self.az._verdict("MEDIUM", 9_800.0, 10_000.0, 3, 1.0), "SPLIT")

    def test_high_gas_pct_gives_split(self):
        # gas_pct=4 > 3 → SPLIT
        self.assertEqual(self.az._verdict("LOW", 9_800.0, 10_000.0, 1, 4.0), "SPLIT")

    def test_exactly_3_gas_pct_not_split_from_gas(self):
        # 3.0 is NOT > 3, 1 hop < 3 → EXECUTE
        self.assertEqual(self.az._verdict("LOW", 9_800.0, 10_000.0, 1, 3.0), "EXECUTE")

    def test_simple_1hop_good_output_gives_execute(self):
        self.assertEqual(self.az._verdict("LOW", 9_984.0, 10_000.0, 1, 0.06), "EXECUTE")

    def test_2hop_low_gas_good_output_gives_execute(self):
        # hop=2 < 3, gas_pct=0.5 < 3, output > 97% → EXECUTE
        self.assertEqual(self.az._verdict("MEDIUM", 9_900.0, 10_000.0, 2, 0.5), "EXECUTE")


# ---------------------------------------------------------------------------
# _warnings
# ---------------------------------------------------------------------------

class TestWarnings(unittest.TestCase):
    def setUp(self):
        self.az = _make_analyzer()

    def test_3hop_route_warns_direct_path(self):
        w = self.az._warnings(3, 30.0, 50.0, 1.0, 0.3)
        self.assertTrue(any("3-hop route" in x for x in w))

    def test_2hop_no_hop_warning(self):
        w = self.az._warnings(2, 30.0, 50.0, 1.0, 0.3)
        self.assertFalse(any("hop route" in x for x in w))

    def test_slippage_exceeds_tolerance_warns(self):
        w = self.az._warnings(1, 120.0, 50.0, 1.0, 0.3)
        self.assertTrue(any("exceeds tolerance" in x for x in w))

    def test_slippage_under_tolerance_no_warning(self):
        w = self.az._warnings(1, 30.0, 50.0, 1.0, 0.3)
        self.assertFalse(any("exceeds tolerance" in x for x in w))

    def test_high_gas_pct_warns(self):
        w = self.az._warnings(1, 10.0, 50.0, 6.0, 0.3)
        self.assertTrue(any("Gas cost" in x for x in w))

    def test_high_mev_warns_private_rpc(self):
        w = self.az._warnings(1, 10.0, 50.0, 1.0, 0.7)
        self.assertTrue(any("private RPC" in x for x in w))

    def test_low_mev_no_mev_warning(self):
        w = self.az._warnings(1, 10.0, 50.0, 1.0, 0.5)
        self.assertFalse(any("private RPC" in x for x in w))

    def test_all_good_no_warnings(self):
        w = self.az._warnings(1, 10.0, 50.0, 1.0, 0.25)
        self.assertEqual(w, [])


# ---------------------------------------------------------------------------
# analyze (integration)
# ---------------------------------------------------------------------------

class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.az = _make_analyzer()

    def test_returns_routing_risk_report(self):
        result = self.az.analyze(_profile())
        self.assertIsInstance(result, RoutingRiskReport)

    def test_1hop_low_slippage_execute_low(self):
        # 1 hop, 10 bps, tolerance=50, trade=10000, gas=20g/ETH=2000 → gas=6 USD → LOW / EXECUTE
        p = _profile(
            hops=[_hop(slippage_bps=10.0)],
            trade_amount_usd=10_000.0,
            gas_price_gwei=20.0,
            eth_price_usd=2_000.0,
            max_slippage_tolerance_bps=50.0,
        )
        result = self.az.analyze(p)
        self.assertEqual(result.execution_risk, "LOW")
        self.assertEqual(result.verdict, "EXECUTE")

    def test_4hop_high_slippage_reject_critical(self):
        # 4 hops * 30 bps = 120 bps > tolerance=50 → CRITICAL → REJECT
        hops = [_hop(slippage_bps=30.0) for _ in range(4)]
        p = _profile(
            hops=hops,
            trade_amount_usd=50_000.0,
            gas_price_gwei=50.0,
            eth_price_usd=3_000.0,
            max_slippage_tolerance_bps=50.0,
        )
        result = self.az.analyze(p)
        self.assertEqual(result.execution_risk, "CRITICAL")
        self.assertEqual(result.verdict, "REJECT")

    def test_3hop_moderate_is_split(self):
        # 3 hops, 10 bps each, tolerance=50 → MEDIUM + SPLIT (3 hops >= 3)
        hops = [_hop(slippage_bps=10.0) for _ in range(3)]
        p = _profile(
            hops=hops,
            trade_amount_usd=5_000.0,
            gas_price_gwei=30.0,
            eth_price_usd=2_000.0,
            max_slippage_tolerance_bps=50.0,
        )
        result = self.az.analyze(p)
        self.assertEqual(result.verdict, "SPLIT")

    def test_hop_count_matches_hops_length(self):
        hops = [_hop() for _ in range(3)]
        result = self.az.analyze(_profile(hops=hops))
        self.assertEqual(result.hop_count, 3)

    def test_route_id_propagated(self):
        result = self.az.analyze(_profile(route_id="my_route_99"))
        self.assertEqual(result.route_id, "my_route_99")

    def test_total_slippage_sums_hops(self):
        hops = [_hop(slippage_bps=15.0), _hop(slippage_bps=25.0)]
        result = self.az.analyze(_profile(hops=hops))
        self.assertAlmostEqual(result.total_slippage_bps, 40.0)

    def test_warnings_is_list(self):
        result = self.az.analyze(_profile())
        self.assertIsInstance(result.warnings, list)

    def test_expected_output_not_negative(self):
        # Force a scenario with near-zero expected output
        hops = [_hop(slippage_bps=5000.0)]  # 50x tolerance, huge slippage
        p = _profile(hops=hops, trade_amount_usd=100.0, max_slippage_tolerance_bps=10.0)
        result = self.az.analyze(p)
        self.assertGreaterEqual(result.expected_output_usd, 0.0)


# ---------------------------------------------------------------------------
# analyze_batch
# ---------------------------------------------------------------------------

class TestAnalyzeBatch(unittest.TestCase):
    def setUp(self):
        self.az = _make_analyzer()

    def test_empty_batch_returns_empty_list(self):
        self.assertEqual(self.az.analyze_batch([]), [])

    def test_single_profile_returns_one_report(self):
        results = self.az.analyze_batch([_profile()])
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], RoutingRiskReport)

    def test_multiple_profiles_correct_count(self):
        profiles = [_profile(route_id=f"r{i}") for i in range(5)]
        results = self.az.analyze_batch(profiles)
        self.assertEqual(len(results), 5)

    def test_batch_preserves_order(self):
        profiles = [_profile(route_id="alpha"), _profile(route_id="beta")]
        results = self.az.analyze_batch(profiles)
        self.assertEqual(results[0].route_id, "alpha")
        self.assertEqual(results[1].route_id, "beta")


# ---------------------------------------------------------------------------
# save_results / load_history
# ---------------------------------------------------------------------------

class TestSaveLoadHistory(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        data_file = Path(self.tmp_dir.name) / "dex_routing_log.json"
        self.az = DEXRoutingRiskAnalyzer(data_file=data_file)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(self.az.load_history(), [])

    def test_save_creates_file(self):
        report = self.az.analyze(_profile())
        self.az.save_results([report])
        self.assertTrue(self.az.data_file.exists())

    def test_save_and_load_roundtrip(self):
        report = self.az.analyze(_profile(route_id="test_route"))
        self.az.save_results([report])
        history = self.az.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["route_id"], "test_route")

    def test_ring_buffer_caps_at_max_entries(self):
        for i in range(MAX_ENTRIES + 1):
            self.az.save_results([self.az.analyze(_profile(route_id=f"r{i}"))])
        history = self.az.load_history()
        self.assertEqual(len(history), MAX_ENTRIES)

    def test_atomic_write_no_tmp_file_left(self):
        self.az.save_results([self.az.analyze(_profile())])
        tmp_path = self.az.data_file.with_suffix(".tmp")
        self.assertFalse(tmp_path.exists())

    def test_history_contains_timestamp_and_verdict(self):
        report = self.az.analyze(_profile())
        self.az.save_results([report])
        history = self.az.load_history()
        self.assertIn("timestamp", history[0])
        self.assertIn("verdict", history[0])


if __name__ == "__main__":
    unittest.main()
