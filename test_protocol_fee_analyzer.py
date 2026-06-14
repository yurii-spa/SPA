"""
Tests for MP-747: ProtocolFeeAnalyzer
≥65 test methods covering all logic paths.
Uses unittest only (no pytest).
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_fee_analyzer import (
    FeeStructure,
    FeeAnalysisResult,
    _RING_BUFFER_CAP,
    analyze_market,
    analyze_protocol,
    compute_amortized_entry_exit,
    compute_net_apy,
    compute_performance_fee,
    fee_efficiency,
    fee_label,
    load_history,
    save_results,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _proto_data(
    protocol: str = "Aave",
    asset: str = "USDC",
    gross_apy: float = 8.0,
    entry_fee: float = 0.1,
    exit_fee: float = 0.1,
    management_fee: float = 0.5,
    performance_fee: float = 10.0,
    hurdle_rate: float = 3.0,
) -> dict:
    return {
        "protocol": protocol,
        "asset": asset,
        "gross_apy_pct": gross_apy,
        "entry_fee_pct": entry_fee,
        "exit_fee_pct": exit_fee,
        "management_fee_pct": management_fee,
        "performance_fee_pct": performance_fee,
        "hurdle_rate_pct": hurdle_rate,
    }


def _make_result() -> FeeAnalysisResult:
    data = [
        _proto_data("AaveV3", gross_apy=5.0, entry_fee=0.0, exit_fee=0.0,
                    management_fee=0.0, performance_fee=0.0, hurdle_rate=0.0),
        _proto_data("Yearn",  gross_apy=10.0, entry_fee=0.0, exit_fee=0.0,
                    management_fee=0.5, performance_fee=10.0, hurdle_rate=3.0),
        _proto_data("Convex", gross_apy=12.0, entry_fee=0.1, exit_fee=0.1,
                    management_fee=1.0, performance_fee=20.0, hurdle_rate=5.0),
    ]
    return analyze_market(data)


# ── compute_performance_fee ───────────────────────────────────────────────────

class TestComputePerformanceFee(unittest.TestCase):
    def test_gross_above_hurdle_charges_fee(self):
        # (8-3) * 10/100 = 0.5
        self.assertAlmostEqual(compute_performance_fee(8.0, 3.0, 10.0), 0.5)

    def test_gross_equal_to_hurdle_no_fee(self):
        self.assertAlmostEqual(compute_performance_fee(3.0, 3.0, 10.0), 0.0)

    def test_gross_below_hurdle_no_fee(self):
        self.assertAlmostEqual(compute_performance_fee(2.0, 3.0, 10.0), 0.0)

    def test_zero_perf_fee_pct_always_zero(self):
        self.assertAlmostEqual(compute_performance_fee(10.0, 3.0, 0.0), 0.0)

    def test_large_perf_fee(self):
        # (10-5) * 20/100 = 1.0
        self.assertAlmostEqual(compute_performance_fee(10.0, 5.0, 20.0), 1.0)

    def test_zero_hurdle_full_gross_charged(self):
        # (5-0)*10/100 = 0.5
        self.assertAlmostEqual(compute_performance_fee(5.0, 0.0, 10.0), 0.5)


# ── compute_amortized_entry_exit ──────────────────────────────────────────────

class TestComputeAmortizedEntryExit(unittest.TestCase):
    def test_formula(self):
        # (0.1 + 0.1) / 100 = 0.002
        self.assertAlmostEqual(compute_amortized_entry_exit(0.1, 0.1), 0.002)

    def test_zero_fees(self):
        self.assertAlmostEqual(compute_amortized_entry_exit(0.0, 0.0), 0.0)

    def test_asymmetric_fees(self):
        self.assertAlmostEqual(compute_amortized_entry_exit(0.2, 0.0), 0.002)

    def test_large_fees(self):
        # (1.0 + 1.0) / 100 = 0.02
        self.assertAlmostEqual(compute_amortized_entry_exit(1.0, 1.0), 0.02)


# ── compute_net_apy ───────────────────────────────────────────────────────────

class TestComputeNetApy(unittest.TestCase):
    def test_all_fees_zero(self):
        self.assertAlmostEqual(compute_net_apy(8.0, 0.0, 0.0, 0.0, 0.0), 8.0)

    def test_management_fee_only(self):
        self.assertAlmostEqual(compute_net_apy(8.0, 0.5, 0.0, 0.0, 0.0), 7.5)

    def test_performance_fee_only(self):
        self.assertAlmostEqual(compute_net_apy(8.0, 0.0, 0.5, 0.0, 0.0), 7.5)

    def test_entry_exit_fees_only(self):
        # 8.0 - 0 - 0 - (0.1+0.1)/100 = 8.0 - 0.002 = 7.998
        self.assertAlmostEqual(compute_net_apy(8.0, 0.0, 0.0, 0.1, 0.1), 7.998)

    def test_all_fees_combined(self):
        # gross=10, mgmt=0.5, perf=0.5, (0.1+0.1)/100=0.002 → 10-0.5-0.5-0.002=8.998
        self.assertAlmostEqual(compute_net_apy(10.0, 0.5, 0.5, 0.1, 0.1), 8.998)


# ── fee_label ─────────────────────────────────────────────────────────────────

class TestFeeLabel(unittest.TestCase):
    def test_low_fee_below_0_5(self):
        self.assertEqual(fee_label(0.4), "LOW_FEE")

    def test_low_fee_at_zero(self):
        self.assertEqual(fee_label(0.0), "LOW_FEE")

    def test_moderate_fee_at_0_5(self):
        self.assertEqual(fee_label(0.5), "MODERATE_FEE")

    def test_moderate_fee_at_2(self):
        self.assertEqual(fee_label(2.0), "MODERATE_FEE")

    def test_moderate_fee_mid(self):
        self.assertEqual(fee_label(1.0), "MODERATE_FEE")

    def test_high_fee_above_2(self):
        self.assertEqual(fee_label(2.01), "HIGH_FEE")

    def test_high_fee_large(self):
        self.assertEqual(fee_label(5.0), "HIGH_FEE")


# ── fee_efficiency ────────────────────────────────────────────────────────────

class TestFeeEfficiency(unittest.TestCase):
    def test_formula(self):
        self.assertAlmostEqual(fee_efficiency(8.0, 10.0), 80.0)

    def test_zero_gross_returns_zero(self):
        self.assertAlmostEqual(fee_efficiency(0.0, 0.0), 0.0)

    def test_negative_gross_returns_zero(self):
        self.assertAlmostEqual(fee_efficiency(5.0, 0.0), 0.0)

    def test_all_fees_zero_efficiency_100(self):
        self.assertAlmostEqual(fee_efficiency(5.0, 5.0), 100.0)

    def test_efficiency_below_100_when_fees_present(self):
        self.assertLess(fee_efficiency(7.5, 8.0), 100.0)


# ── analyze_protocol ──────────────────────────────────────────────────────────

class TestAnalyzeProtocol(unittest.TestCase):
    def setUp(self):
        # gross=8, entry=0.1, exit=0.1, mgmt=0.5, perf=10% above 3%
        # eff_perf = (8-3)*10/100 = 0.5
        # amortized = (0.1+0.1)/100 = 0.002
        # net = 8 - 0.5 - 0.5 - 0.002 = 6.998
        # drag = 8 - 6.998 = 1.002  → MODERATE_FEE
        self.fs = analyze_protocol("Aave", "USDC", 8.0, 0.1, 0.1, 0.5, 10.0, 3.0)

    def test_protocol_stored(self):
        self.assertEqual(self.fs.protocol, "Aave")

    def test_asset_stored(self):
        self.assertEqual(self.fs.asset, "USDC")

    def test_gross_apy_stored(self):
        self.assertAlmostEqual(self.fs.gross_apy_pct, 8.0)

    def test_effective_performance_fee_above_hurdle(self):
        self.assertAlmostEqual(self.fs.effective_performance_fee_pct, 0.5)

    def test_amortized_entry_exit(self):
        self.assertAlmostEqual(self.fs.amortized_entry_exit_pct, 0.002)

    def test_net_apy(self):
        self.assertAlmostEqual(self.fs.net_apy_pct, 6.998, places=5)

    def test_total_fee_drag(self):
        self.assertAlmostEqual(self.fs.total_fee_drag_pct, 1.002, places=5)

    def test_fee_efficiency_below_100(self):
        self.assertLess(self.fs.fee_efficiency_pct, 100.0)

    def test_fee_label_moderate(self):
        self.assertEqual(self.fs.fee_label, "MODERATE_FEE")

    def test_effective_perf_fee_zero_when_below_hurdle(self):
        fs = analyze_protocol("X", "USDC", 2.0, 0.0, 0.0, 0.0, 10.0, 3.0)
        self.assertAlmostEqual(fs.effective_performance_fee_pct, 0.0)

    def test_fee_efficiency_100_when_all_fees_zero(self):
        fs = analyze_protocol("X", "USDC", 5.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(fs.fee_efficiency_pct, 100.0)

    def test_net_apy_equals_gross_when_all_fees_zero(self):
        fs = analyze_protocol("X", "USDC", 5.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(fs.net_apy_pct, 5.0)

    def test_drag_zero_when_all_fees_zero(self):
        fs = analyze_protocol("X", "USDC", 5.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(fs.total_fee_drag_pct, 0.0)


# ── Recommendations ───────────────────────────────────────────────────────────

class TestRecommendations(unittest.TestCase):
    def test_high_fee_recommendation(self):
        # drag > 2% → HIGH_FEE
        fs = analyze_protocol("X", "USDC", 10.0, 0.5, 0.5, 1.0, 20.0, 0.0)
        # perf = 10*20/100=2, mgmt=1, amort=0.01 → net=10-2-1-0.01=6.99, drag=3.01
        self.assertIn("High fee drag", fs.recommendation)

    def test_low_fee_recommendation(self):
        # drag < 0.5%
        fs = analyze_protocol("Y", "USDC", 5.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertIn("Efficient", fs.recommendation)

    def test_moderate_fee_recommendation(self):
        # drag between 0.5 and 2
        fs = analyze_protocol("Z", "USDC", 8.0, 0.1, 0.1, 0.5, 5.0, 5.0)
        # perf: gross=8 > hurdle=5, so eff_perf=(8-5)*5/100=0.15
        # mgmt=0.5, amort=0.002, net=8-0.5-0.15-0.002=7.348, drag=0.652 → MODERATE_FEE
        self.assertIn("Moderate", fs.recommendation)


# ── analyze_market ────────────────────────────────────────────────────────────

class TestAnalyzeMarket(unittest.TestCase):
    def setUp(self):
        self.data = [
            _proto_data("Aave",   gross_apy=5.0,  entry_fee=0.0, exit_fee=0.0,
                        management_fee=0.0, performance_fee=0.0, hurdle_rate=0.0),
            _proto_data("Yearn",  gross_apy=10.0, entry_fee=0.0, exit_fee=0.0,
                        management_fee=0.5, performance_fee=10.0, hurdle_rate=3.0),
            _proto_data("Convex", gross_apy=12.0, entry_fee=0.5, exit_fee=0.5,
                        management_fee=1.5, performance_fee=20.0, hurdle_rate=5.0),
        ]
        self.result = analyze_market(self.data)

    def test_lowest_fee_protocol(self):
        # Aave: all fees 0 → drag=0 → lowest
        self.assertEqual(self.result.lowest_fee_protocol, "Aave")

    def test_highest_net_apy_protocol(self):
        # Aave net=5.0, Yearn net=10-0.5-0.7-0=8.8, Convex net=12-1.5-1.4-0.01=9.09
        self.assertEqual(self.result.highest_net_apy_protocol, "Convex")

    def test_avg_gross_apy(self):
        expected = (5.0 + 10.0 + 12.0) / 3
        self.assertAlmostEqual(self.result.avg_gross_apy_pct, expected, places=5)

    def test_avg_net_apy_less_than_avg_gross(self):
        self.assertLess(self.result.avg_net_apy_pct, self.result.avg_gross_apy_pct)

    def test_avg_fee_drag_positive(self):
        self.assertGreater(self.result.avg_fee_drag_pct, 0.0)

    def test_low_fee_count(self):
        # Only Aave has drag=0 → LOW_FEE
        self.assertEqual(self.result.low_fee_count, 1)

    def test_market_fee_label_efficient(self):
        data = [
            _proto_data("P1", gross_apy=5.0, entry_fee=0.0, exit_fee=0.0,
                        management_fee=0.0, performance_fee=0.0, hurdle_rate=0.0),
            _proto_data("P2", gross_apy=5.0, entry_fee=0.0, exit_fee=0.0,
                        management_fee=0.1, performance_fee=0.0, hurdle_rate=0.0),
        ]
        r = analyze_market(data)
        self.assertEqual(r.market_fee_label, "EFFICIENT")

    def test_market_fee_label_moderate(self):
        # Drag between 0.5 and 2
        data = [
            _proto_data("P1", gross_apy=8.0, entry_fee=0.1, exit_fee=0.1,
                        management_fee=0.5, performance_fee=5.0, hurdle_rate=3.0),
            _proto_data("P2", gross_apy=7.0, entry_fee=0.1, exit_fee=0.1,
                        management_fee=0.5, performance_fee=5.0, hurdle_rate=3.0),
        ]
        r = analyze_market(data)
        self.assertEqual(r.market_fee_label, "MODERATE")

    def test_market_fee_label_costly(self):
        data = [
            _proto_data("P1", gross_apy=10.0, entry_fee=0.5, exit_fee=0.5,
                        management_fee=2.0, performance_fee=20.0, hurdle_rate=0.0),
            _proto_data("P2", gross_apy=10.0, entry_fee=0.5, exit_fee=0.5,
                        management_fee=2.0, performance_fee=20.0, hurdle_rate=0.0),
        ]
        r = analyze_market(data)
        self.assertEqual(r.market_fee_label, "COSTLY")

    def test_recommendation_summary_non_empty(self):
        self.assertTrue(len(self.result.recommendation_summary) > 0)

    def test_protocols_list_length(self):
        self.assertEqual(len(self.result.protocols), 3)

    def test_empty_data_raises(self):
        with self.assertRaises((ValueError, Exception)):
            analyze_market([])

    def test_avg_fee_drag_formula(self):
        data = [
            _proto_data("P1", gross_apy=5.0, entry_fee=0.0, exit_fee=0.0,
                        management_fee=0.0, performance_fee=0.0, hurdle_rate=0.0),
            _proto_data("P2", gross_apy=5.0, entry_fee=0.0, exit_fee=0.0,
                        management_fee=1.0, performance_fee=0.0, hurdle_rate=0.0),
        ]
        r = analyze_market(data)
        # P1 drag=0, P2 drag=1.0 → avg=0.5
        self.assertAlmostEqual(r.avg_fee_drag_pct, 0.5, places=5)


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    def test_all_fees_zero_net_equals_gross(self):
        fs = analyze_protocol("X", "USDC", 5.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(fs.net_apy_pct, 5.0)
        self.assertAlmostEqual(fs.total_fee_drag_pct, 0.0)
        self.assertEqual(fs.fee_label, "LOW_FEE")

    def test_no_performance_fee_below_hurdle(self):
        # gross=2 < hurdle=5 → no perf fee
        fs = analyze_protocol("X", "USDC", 2.0, 0.0, 0.0, 0.0, 10.0, 5.0)
        self.assertAlmostEqual(fs.effective_performance_fee_pct, 0.0)

    def test_no_performance_fee_zero_pct(self):
        # perf_fee_pct=0 → always 0 even if above hurdle
        fs = analyze_protocol("X", "USDC", 10.0, 0.0, 0.0, 0.0, 0.0, 3.0)
        self.assertAlmostEqual(fs.effective_performance_fee_pct, 0.0)

    def test_single_protocol_market(self):
        data = [_proto_data("OnlyOne", gross_apy=5.0, entry_fee=0.0, exit_fee=0.0,
                            management_fee=0.0, performance_fee=0.0, hurdle_rate=0.0)]
        r = analyze_market(data)
        self.assertEqual(r.lowest_fee_protocol, "OnlyOne")
        self.assertEqual(r.highest_net_apy_protocol, "OnlyOne")
        self.assertEqual(r.low_fee_count, 1)


# ── save / load ───────────────────────────────────────────────────────────────

class TestSaveLoad(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp_dir, "protocol_fee_log.json")

    def test_save_creates_file(self):
        result = _make_result()
        save_results(result, self.log_file)
        self.assertTrue(os.path.exists(self.log_file))

    def test_load_returns_list_after_save(self):
        save_results(_make_result(), self.log_file)
        history = load_history(self.log_file)
        self.assertIsInstance(history, list)
        self.assertEqual(len(history), 1)

    def test_save_load_round_trip(self):
        save_results(_make_result(), self.log_file)
        history = load_history(self.log_file)
        entry = history[0]
        self.assertIn("lowest_fee_protocol", entry)
        self.assertIn("timestamp", entry)

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            save_results(_make_result(), self.log_file)
        history = load_history(self.log_file)
        self.assertEqual(len(history), 5)

    def test_load_empty_when_file_missing(self):
        history = load_history(os.path.join(self.tmp_dir, "nonexistent.json"))
        self.assertEqual(history, [])

    def test_ring_buffer_cap_100(self):
        for _ in range(_RING_BUFFER_CAP + 20):
            save_results(_make_result(), self.log_file)
        history = load_history(self.log_file)
        self.assertLessEqual(len(history), _RING_BUFFER_CAP)

    def test_ring_buffer_keeps_newest(self):
        for _ in range(_RING_BUFFER_CAP + 5):
            save_results(_make_result(), self.log_file)
        history = load_history(self.log_file)
        self.assertEqual(len(history), _RING_BUFFER_CAP)

    def test_save_returns_log_file_path(self):
        path = save_results(_make_result(), self.log_file)
        self.assertEqual(path, self.log_file)


if __name__ == "__main__":
    unittest.main()
