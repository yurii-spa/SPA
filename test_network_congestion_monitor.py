"""Tests for MP-696 NetworkCongestionMonitor.

Run with:
    python3 -m unittest spa_core.tests.test_network_congestion_monitor -v
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from spa_core.analytics.network_congestion_monitor import (
    CongestionReport,
    NetworkCongestionMonitor,
    NetworkSnapshot,
    NETWORK_PARAMS,
    _base_gas,
    _block_time,
    _congestion_level,
    _cost_urgency,
    _gas_premium_pct,
    _optimal_window,
    _recommendations,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _snap(
    network="ethereum",
    current_gas=20.0,
    pending=500,
    utilization=50.0,
    ts=None,
):
    return NetworkSnapshot(
        network=network,
        current_gas_gwei=current_gas,
        pending_tx_count=pending,
        avg_block_utilization_pct=utilization,
        timestamp=ts or time.time(),
    )


# ---------------------------------------------------------------------------
# 1. gas_premium_pct formula
# ---------------------------------------------------------------------------

class TestGasPremiumPct(unittest.TestCase):

    def test_zero_premium_when_current_equals_base(self):
        self.assertAlmostEqual(_gas_premium_pct(20.0, 20.0), 0.0)

    def test_positive_premium(self):
        # (40 - 20) / 20 * 100 = 100%
        self.assertAlmostEqual(_gas_premium_pct(40.0, 20.0), 100.0)

    def test_negative_premium(self):
        # (10 - 20) / 20 * 100 = -50%
        self.assertAlmostEqual(_gas_premium_pct(10.0, 20.0), -50.0)

    def test_zero_base_returns_zero(self):
        self.assertEqual(_gas_premium_pct(100.0, 0.0), 0.0)

    def test_large_premium(self):
        # (100 - 20) / 20 * 100 = 400%
        self.assertAlmostEqual(_gas_premium_pct(100.0, 20.0), 400.0)

    def test_fractional_base(self):
        # L2: base = 0.1, current = 0.3 → 200%
        self.assertAlmostEqual(_gas_premium_pct(0.3, 0.1), 200.0)


# ---------------------------------------------------------------------------
# 2. congestion_level thresholds
# ---------------------------------------------------------------------------

class TestCongestionLevel(unittest.TestCase):

    def test_low_boundary_zero(self):
        self.assertEqual(_congestion_level(0.0), "LOW")

    def test_low_just_below_threshold(self):
        self.assertEqual(_congestion_level(19.99), "LOW")

    def test_moderate_at_20(self):
        self.assertEqual(_congestion_level(20.0), "MODERATE")

    def test_moderate_midrange(self):
        self.assertEqual(_congestion_level(50.0), "MODERATE")

    def test_moderate_just_below_100(self):
        self.assertEqual(_congestion_level(99.99), "MODERATE")

    def test_high_at_100(self):
        self.assertEqual(_congestion_level(100.0), "HIGH")

    def test_high_midrange(self):
        self.assertEqual(_congestion_level(200.0), "HIGH")

    def test_high_just_below_300(self):
        self.assertEqual(_congestion_level(299.99), "HIGH")

    def test_extreme_at_300(self):
        self.assertEqual(_congestion_level(300.0), "EXTREME")

    def test_extreme_very_high(self):
        self.assertEqual(_congestion_level(1000.0), "EXTREME")

    def test_negative_premium_is_low(self):
        self.assertEqual(_congestion_level(-10.0), "LOW")


# ---------------------------------------------------------------------------
# 3. estimated_wait_blocks maps from level
# ---------------------------------------------------------------------------

class TestEstimatedWaitBlocks(unittest.TestCase):

    def _wait_blocks(self, level):
        from spa_core.analytics.network_congestion_monitor import _WAIT_BLOCKS
        return _WAIT_BLOCKS[level]

    def test_low_1_block(self):
        self.assertEqual(self._wait_blocks("LOW"), 1)

    def test_moderate_2_blocks(self):
        self.assertEqual(self._wait_blocks("MODERATE"), 2)

    def test_high_5_blocks(self):
        self.assertEqual(self._wait_blocks("HIGH"), 5)

    def test_extreme_20_blocks(self):
        self.assertEqual(self._wait_blocks("EXTREME"), 20)


# ---------------------------------------------------------------------------
# 4. estimated_wait_seconds = wait_blocks * block_time
# ---------------------------------------------------------------------------

class TestEstimatedWaitSeconds(unittest.TestCase):

    def _get_report(self, network, gas):
        monitor = NetworkCongestionMonitor()
        return monitor.analyze(_snap(network=network, current_gas=gas))

    def test_ethereum_low_gas_wait_seconds(self):
        # LOW → 1 block * 12s = 12s
        r = self._get_report("ethereum", 10.0)
        self.assertEqual(r.congestion_level, "LOW")
        self.assertAlmostEqual(r.estimated_wait_seconds, 12.0)

    def test_ethereum_extreme_wait_seconds(self):
        # EXTREME → 20 blocks * 12s = 240s
        r = self._get_report("ethereum", 100.0)
        self.assertEqual(r.congestion_level, "EXTREME")
        self.assertAlmostEqual(r.estimated_wait_seconds, 240.0)

    def test_arbitrum_block_time_025(self):
        # base=0.1, current=0.2 → premium=100% → HIGH → 5 blocks * 0.25s = 1.25s
        r = self._get_report("arbitrum", 0.2)
        self.assertEqual(r.congestion_level, "HIGH")
        self.assertAlmostEqual(r.estimated_wait_seconds, 1.25)

    def test_base_low_wait_seconds(self):
        # base=0.1, current=0.05 → LOW → 1 block * 2s = 2s
        r = self._get_report("base", 0.05)
        self.assertEqual(r.congestion_level, "LOW")
        self.assertAlmostEqual(r.estimated_wait_seconds, 2.0)

    def test_unknown_network_uses_default_block_time_12(self):
        r = self._get_report("polygon", 25.0)
        # block_time default = 12; check it's a multiple of 12
        self.assertEqual(r.estimated_wait_seconds % 12, 0.0)


# ---------------------------------------------------------------------------
# 5. cost_urgency thresholds
# ---------------------------------------------------------------------------

class TestCostUrgency(unittest.TestCase):

    def test_optimal_at_zero(self):
        self.assertEqual(_cost_urgency(0.0), "OPTIMAL")

    def test_optimal_just_below_10(self):
        self.assertEqual(_cost_urgency(9.99), "OPTIMAL")

    def test_elevated_at_10(self):
        self.assertEqual(_cost_urgency(10.0), "ELEVATED")

    def test_elevated_midrange(self):
        self.assertEqual(_cost_urgency(30.0), "ELEVATED")

    def test_elevated_just_below_50(self):
        self.assertEqual(_cost_urgency(49.99), "ELEVATED")

    def test_expensive_at_50(self):
        self.assertEqual(_cost_urgency(50.0), "EXPENSIVE")

    def test_expensive_midrange(self):
        self.assertEqual(_cost_urgency(100.0), "EXPENSIVE")

    def test_expensive_just_below_200(self):
        self.assertEqual(_cost_urgency(199.99), "EXPENSIVE")

    def test_prohibitive_at_200(self):
        self.assertEqual(_cost_urgency(200.0), "PROHIBITIVE")

    def test_prohibitive_very_high(self):
        self.assertEqual(_cost_urgency(500.0), "PROHIBITIVE")

    def test_negative_premium_is_optimal(self):
        self.assertEqual(_cost_urgency(-5.0), "OPTIMAL")


# ---------------------------------------------------------------------------
# 6. optimal_window logic
# ---------------------------------------------------------------------------

class TestOptimalWindow(unittest.TestCase):

    def test_optimal_urgency_returns_now(self):
        self.assertEqual(_optimal_window("OPTIMAL", "LOW"), "NOW")

    def test_elevated_urgency_returns_now(self):
        self.assertEqual(_optimal_window("ELEVATED", "MODERATE"), "NOW")

    def test_expensive_returns_wait_1h(self):
        self.assertEqual(_optimal_window("EXPENSIVE", "HIGH"), "WAIT_1H")

    def test_expensive_with_any_level_wait_1h(self):
        for level in ("LOW", "MODERATE", "HIGH", "EXTREME"):
            self.assertEqual(_optimal_window("EXPENSIVE", level), "WAIT_1H")

    def test_prohibitive_high_returns_wait_4h(self):
        self.assertEqual(_optimal_window("PROHIBITIVE", "HIGH"), "WAIT_4H")

    def test_prohibitive_extreme_returns_wait_night(self):
        self.assertEqual(_optimal_window("PROHIBITIVE", "EXTREME"), "WAIT_NIGHT")

    def test_prohibitive_low_returns_wait_4h(self):
        self.assertEqual(_optimal_window("PROHIBITIVE", "LOW"), "WAIT_4H")

    def test_prohibitive_moderate_returns_wait_4h(self):
        self.assertEqual(_optimal_window("PROHIBITIVE", "MODERATE"), "WAIT_4H")


# ---------------------------------------------------------------------------
# 7. _recommendations
# ---------------------------------------------------------------------------

class TestRecommendations(unittest.TestCase):

    def _recs(self, network="ethereum", current=20.0, urgency="OPTIMAL",
               level="LOW", utilization=50.0):
        return _recommendations(network, current, urgency, level, utilization)

    def test_prohibitive_postpone_message(self):
        recs = self._recs(urgency="PROHIBITIVE", level="LOW")
        self.assertTrue(any("postpone" in r.lower() for r in recs))

    def test_high_congestion_execute_l2(self):
        recs = self._recs(current=80.0, urgency="EXPENSIVE", level="HIGH")
        self.assertTrue(any("L2" in r for r in recs))

    def test_extreme_congestion_execute_l2(self):
        recs = self._recs(current=200.0, urgency="PROHIBITIVE", level="EXTREME")
        self.assertTrue(any("L2" in r for r in recs))

    def test_ethereum_low_gas_excellent_timing(self):
        recs = self._recs(network="ethereum", current=10.0,
                          urgency="OPTIMAL", level="LOW")
        self.assertTrue(any("excellent" in r.lower() for r in recs))

    def test_ethereum_14_gwei_below_15_threshold(self):
        recs = self._recs(network="ethereum", current=14.0)
        self.assertTrue(any("excellent" in r.lower() for r in recs))

    def test_ethereum_15_gwei_no_excellent_msg(self):
        recs = self._recs(network="ethereum", current=15.0)
        self.assertFalse(any("excellent" in r.lower() for r in recs))

    def test_blocks_full_warning(self):
        recs = self._recs(utilization=95.0)
        self.assertTrue(any("Blocks" in r for r in recs))

    def test_blocks_below_91_no_warning(self):
        recs = self._recs(utilization=90.0)
        self.assertFalse(any("Blocks" in r for r in recs))

    def test_base_l2_minimal_fees_message(self):
        recs = self._recs(network="base")
        self.assertTrue(any("L2 network" in r for r in recs))

    def test_arbitrum_l2_minimal_fees_message(self):
        recs = self._recs(network="arbitrum")
        self.assertTrue(any("L2 network" in r for r in recs))

    def test_optimism_l2_minimal_fees_message(self):
        recs = self._recs(network="optimism")
        self.assertTrue(any("L2 network" in r for r in recs))

    def test_ethereum_no_l2_message(self):
        recs = self._recs(network="ethereum")
        self.assertFalse(any("L2 network" in r for r in recs))

    def test_low_utilization_no_blocks_full(self):
        recs = self._recs(utilization=50.0)
        self.assertFalse(any("Blocks" in r for r in recs))


# ---------------------------------------------------------------------------
# 8. analyze() integration — ETH high gas
# ---------------------------------------------------------------------------

class TestAnalyzeEthHighGas(unittest.TestCase):

    def setUp(self):
        self.monitor = NetworkCongestionMonitor()
        # base=20, current=100 → premium=400% → EXTREME, PROHIBITIVE, WAIT_NIGHT
        self.snap = _snap(network="ethereum", current_gas=100.0, utilization=60.0)
        self.report = self.monitor.analyze(self.snap)

    def test_congestion_level_extreme(self):
        self.assertEqual(self.report.congestion_level, "EXTREME")

    def test_cost_urgency_prohibitive(self):
        self.assertEqual(self.report.cost_urgency, "PROHIBITIVE")

    def test_optimal_window_wait_night(self):
        self.assertEqual(self.report.optimal_window, "WAIT_NIGHT")

    def test_estimated_wait_blocks_20(self):
        self.assertEqual(self.report.estimated_wait_blocks, 20)

    def test_estimated_wait_seconds_240(self):
        self.assertAlmostEqual(self.report.estimated_wait_seconds, 240.0)

    def test_base_gas_correct(self):
        self.assertAlmostEqual(self.report.base_gas_gwei, 20.0)

    def test_gas_premium_correct(self):
        self.assertAlmostEqual(self.report.gas_premium_pct, 400.0)

    def test_pending_tx_count_propagated(self):
        self.assertEqual(self.report.pending_tx_count, 500)

    def test_has_postpone_recommendation(self):
        self.assertTrue(any("postpone" in r.lower() for r in self.report.recommendations))


# ---------------------------------------------------------------------------
# 9. analyze() integration — Base low gas
# ---------------------------------------------------------------------------

class TestAnalyzeBaseLowGas(unittest.TestCase):

    def setUp(self):
        self.monitor = NetworkCongestionMonitor()
        # base=0.1, current=0.05 → premium=-50% → LOW, OPTIMAL, NOW
        self.snap = _snap(network="base", current_gas=0.05, utilization=20.0)
        self.report = self.monitor.analyze(self.snap)

    def test_congestion_level_low(self):
        self.assertEqual(self.report.congestion_level, "LOW")

    def test_cost_urgency_optimal(self):
        self.assertEqual(self.report.cost_urgency, "OPTIMAL")

    def test_optimal_window_now(self):
        self.assertEqual(self.report.optimal_window, "NOW")

    def test_estimated_wait_blocks_1(self):
        self.assertEqual(self.report.estimated_wait_blocks, 1)

    def test_base_gas_correct(self):
        self.assertAlmostEqual(self.report.base_gas_gwei, 0.1)

    def test_l2_recommendation_present(self):
        self.assertTrue(any("L2 network" in r for r in self.report.recommendations))

    def test_network_name_preserved(self):
        self.assertEqual(self.report.network, "base")


# ---------------------------------------------------------------------------
# 10. analyze_batch
# ---------------------------------------------------------------------------

class TestAnalyzeBatch(unittest.TestCase):

    def setUp(self):
        self.monitor = NetworkCongestionMonitor()

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(self.monitor.analyze_batch([]), [])

    def test_single_snapshot(self):
        result = self.monitor.analyze_batch([_snap("ethereum", 20.0)])
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], CongestionReport)

    def test_multiple_snapshots_length(self):
        snaps = [
            _snap("ethereum", 20.0),
            _snap("base", 0.1),
            _snap("arbitrum", 0.08),
        ]
        result = self.monitor.analyze_batch(snaps)
        self.assertEqual(len(result), 3)

    def test_networks_preserved_in_order(self):
        snaps = [_snap("ethereum"), _snap("base"), _snap("arbitrum")]
        result = self.monitor.analyze_batch(snaps)
        self.assertEqual([r.network for r in result], ["ethereum", "base", "arbitrum"])


# ---------------------------------------------------------------------------
# 11. compare_networks
# ---------------------------------------------------------------------------

class TestCompareNetworks(unittest.TestCase):

    def setUp(self):
        self.monitor = NetworkCongestionMonitor()

    def test_returns_cheapest_network(self):
        # ethereum 400% premium; base -50%; arbitrum -20%
        snaps = [
            _snap("ethereum", 100.0),
            _snap("base", 0.05),
            _snap("arbitrum", 0.08),
        ]
        result = self.monitor.compare_networks(snaps)
        self.assertEqual(result, "base")

    def test_empty_input_returns_empty_string(self):
        self.assertEqual(self.monitor.compare_networks([]), "")

    def test_single_network_returns_itself(self):
        result = self.monitor.compare_networks([_snap("ethereum", 20.0)])
        self.assertEqual(result, "ethereum")

    def test_tie_broken_consistently(self):
        # Both at exactly the same gas = base gas
        snaps = [
            _snap("ethereum", 20.0),   # premium 0%
            _snap("base", 0.1),        # premium 0%
        ]
        result = self.monitor.compare_networks(snaps)
        self.assertIn(result, ("ethereum", "base"))


# ---------------------------------------------------------------------------
# 12. save_results / load_history (ring-buffer + atomic write)
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.monitor = NetworkCongestionMonitor(data_dir=self.tmpdir)
        self.data_file = Path(self.tmpdir) / "congestion_monitor_log.json"

    def _make_report(self, network="ethereum", gas=20.0) -> CongestionReport:
        return self.monitor.analyze(_snap(network=network, current_gas=gas))

    def test_load_history_missing_file_returns_empty(self):
        self.assertEqual(self.monitor.load_history(), [])

    def test_save_creates_file(self):
        self.monitor.save_results([self._make_report()])
        self.assertTrue(self.data_file.exists())

    def test_saved_file_is_valid_json(self):
        self.monitor.save_results([self._make_report()])
        with open(self.data_file) as fh:
            data = json.load(fh)
        self.assertIn("entries", data)

    def test_load_history_after_save(self):
        self.monitor.save_results([self._make_report()])
        history = self.monitor.load_history()
        self.assertEqual(len(history), 1)

    def test_append_accumulates(self):
        self.monitor.save_results([self._make_report("ethereum")])
        self.monitor.save_results([self._make_report("base")])
        history = self.monitor.load_history()
        self.assertEqual(len(history), 2)

    def test_ring_buffer_caps_at_100(self):
        reports = [self._make_report() for _ in range(105)]
        self.monitor.save_results(reports)
        history = self.monitor.load_history()
        self.assertEqual(len(history), 100)

    def test_ring_buffer_keeps_newest(self):
        # Save 101 reports; the 101st should appear in history
        reports_1 = [self._make_report("ethereum") for _ in range(100)]
        self.monitor.save_results(reports_1)
        last_report = self._make_report("arbitrum")
        self.monitor.save_results([last_report])
        history = self.monitor.load_history()
        self.assertEqual(len(history), 100)
        self.assertEqual(history[-1]["network"], "arbitrum")

    def test_atomic_write_no_tmp_file_remains(self):
        self.monitor.save_results([self._make_report()])
        tmp = self.data_file.with_suffix(".tmp")
        self.assertFalse(tmp.exists())

    def test_schema_version_in_file(self):
        self.monitor.save_results([self._make_report()])
        with open(self.data_file) as fh:
            data = json.load(fh)
        self.assertEqual(data["schema_version"], "1.0")

    def test_load_corrupt_file_returns_empty(self):
        self.data_file.write_text("NOT JSON")
        self.assertEqual(self.monitor.load_history(), [])


# ---------------------------------------------------------------------------
# 13. NETWORK_PARAMS completeness
# ---------------------------------------------------------------------------

class TestNetworkParams(unittest.TestCase):

    def test_ethereum_params_present(self):
        self.assertIn("ethereum", NETWORK_PARAMS)

    def test_base_params_present(self):
        self.assertIn("base", NETWORK_PARAMS)

    def test_arbitrum_params_present(self):
        self.assertIn("arbitrum", NETWORK_PARAMS)

    def test_optimism_params_present(self):
        self.assertIn("optimism", NETWORK_PARAMS)

    def test_base_gas_helper_default_unknown_network(self):
        self.assertEqual(_base_gas("unknown"), 20.0)

    def test_block_time_helper_default_unknown_network(self):
        self.assertEqual(_block_time("unknown"), 12.0)

    def test_ethereum_base_gas_20(self):
        self.assertAlmostEqual(_base_gas("ethereum"), 20.0)

    def test_base_base_gas_01(self):
        self.assertAlmostEqual(_base_gas("base"), 0.1)


if __name__ == "__main__":
    unittest.main()
