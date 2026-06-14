"""
Tests for MP-744: ProtocolTVLMomentumTracker
≥65 tests using unittest only (no pytest).
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from spa_core.analytics.protocol_tvl_momentum_tracker import (
    TVLSnapshot,
    TVLMomentum,
    TVLMomentumResult,
    compute_pct_change,
    compute_momentum_score,
    momentum_label,
    compute_sma_tvl,
    analyze_protocol,
    analyze_market,
    save_results,
    load_history,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_snapshots(tvl_values, protocol="TestProto"):
    """Build a List[TVLSnapshot] from raw TVL values (ascending dates)."""
    base = datetime(2026, 1, 1)
    snaps = []
    for i, v in enumerate(tvl_values):
        ts = (base + timedelta(days=i)).isoformat()
        snaps.append(TVLSnapshot(protocol=protocol, tvl_usd=v, timestamp_iso=ts))
    return snaps


def make_pd(protocol, tvl_values):
    """Build protocols_data dict entry."""
    base = datetime(2026, 1, 1)
    snaps = [
        {"tvl_usd": v, "timestamp_iso": (base + timedelta(days=i)).isoformat()}
        for i, v in enumerate(tvl_values)
    ]
    return {"protocol": protocol, "snapshots": snaps}


# ---------------------------------------------------------------------------
# compute_pct_change
# ---------------------------------------------------------------------------

class TestComputePctChange(unittest.TestCase):

    def test_basic_increase(self):
        self.assertAlmostEqual(compute_pct_change(110, 100), 10.0)

    def test_basic_decrease(self):
        self.assertAlmostEqual(compute_pct_change(90, 100), -10.0)

    def test_no_change_returns_zero(self):
        self.assertAlmostEqual(compute_pct_change(100, 100), 0.0)

    def test_previous_zero_returns_zero(self):
        self.assertEqual(compute_pct_change(100, 0), 0.0)

    def test_negative_previous_returns_zero(self):
        self.assertEqual(compute_pct_change(100, -50), 0.0)

    def test_fifty_pct_increase(self):
        self.assertAlmostEqual(compute_pct_change(150, 100), 50.0)

    def test_hundred_pct_increase(self):
        self.assertAlmostEqual(compute_pct_change(200, 100), 100.0)

    def test_fractional_values(self):
        self.assertAlmostEqual(compute_pct_change(1.05, 1.00), 5.0)

    def test_returns_float(self):
        self.assertIsInstance(compute_pct_change(110, 100), float)


# ---------------------------------------------------------------------------
# compute_momentum_score
# ---------------------------------------------------------------------------

class TestComputeMomentumScore(unittest.TestCase):

    def test_weighted_formula(self):
        expected = 0.5 * 10 + 0.3 * 20 + 0.2 * 30
        self.assertAlmostEqual(compute_momentum_score(10, 20, 30), expected)

    def test_all_zeros(self):
        self.assertAlmostEqual(compute_momentum_score(0, 0, 0), 0.0)

    def test_negative_values(self):
        expected = 0.5 * (-10) + 0.3 * (-20) + 0.2 * (-30)
        self.assertAlmostEqual(compute_momentum_score(-10, -20, -30), expected)

    def test_mixed_values(self):
        expected = 0.5 * 5 + 0.3 * (-3) + 0.2 * 2
        self.assertAlmostEqual(compute_momentum_score(5, -3, 2), expected)

    def test_equal_inputs_return_same_value(self):
        # weights sum to 1 so equal inputs → same value
        self.assertAlmostEqual(compute_momentum_score(7, 7, 7), 7.0)

    def test_only_1d_weight(self):
        # c7d=c30d=0 → score = 0.5*c1d
        self.assertAlmostEqual(compute_momentum_score(8, 0, 0), 4.0)


# ---------------------------------------------------------------------------
# momentum_label
# ---------------------------------------------------------------------------

class TestMomentumLabel(unittest.TestCase):

    def test_strong_inflow_above_10(self):
        self.assertEqual(momentum_label(15), "STRONG_INFLOW")

    def test_strong_inflow_at_100(self):
        self.assertEqual(momentum_label(100), "STRONG_INFLOW")

    def test_strong_inflow_just_above_10(self):
        self.assertEqual(momentum_label(10.001), "STRONG_INFLOW")

    def test_inflow_at_exactly_10(self):
        # score=10.0 → score > 10 is False → INFLOW
        self.assertEqual(momentum_label(10.0), "INFLOW")

    def test_inflow_at_5(self):
        self.assertEqual(momentum_label(5), "INFLOW")

    def test_inflow_just_above_2(self):
        self.assertEqual(momentum_label(2.001), "INFLOW")

    def test_neutral_at_exactly_2(self):
        self.assertEqual(momentum_label(2.0), "NEUTRAL")

    def test_neutral_at_zero(self):
        self.assertEqual(momentum_label(0), "NEUTRAL")

    def test_neutral_at_minus_2(self):
        self.assertEqual(momentum_label(-2.0), "NEUTRAL")

    def test_outflow_just_below_minus_2(self):
        self.assertEqual(momentum_label(-2.001), "OUTFLOW")

    def test_outflow_at_minus_5(self):
        self.assertEqual(momentum_label(-5), "OUTFLOW")

    def test_outflow_just_above_minus_10(self):
        self.assertEqual(momentum_label(-9.999), "OUTFLOW")

    def test_outflow_at_exactly_minus_10(self):
        # -10 >= -10 → OUTFLOW
        self.assertEqual(momentum_label(-10.0), "OUTFLOW")

    def test_strong_outflow_just_below_minus_10(self):
        self.assertEqual(momentum_label(-10.001), "STRONG_OUTFLOW")

    def test_strong_outflow_at_minus_50(self):
        self.assertEqual(momentum_label(-50), "STRONG_OUTFLOW")


# ---------------------------------------------------------------------------
# compute_sma_tvl
# ---------------------------------------------------------------------------

class TestComputeSmaTvl(unittest.TestCase):

    def test_average_of_last_7(self):
        snaps = make_snapshots([10, 20, 30, 40, 50, 60, 70])
        self.assertAlmostEqual(compute_sma_tvl(snaps, 7), 40.0)

    def test_uses_last_window_only(self):
        # 10 snaps; last 7 are 10,20,30,40,50,60,70
        snaps = make_snapshots([1, 2, 3, 10, 20, 30, 40, 50, 60, 70])
        expected = (10 + 20 + 30 + 40 + 50 + 60 + 70) / 7
        self.assertAlmostEqual(compute_sma_tvl(snaps, 7), expected)

    def test_fewer_than_window_uses_all(self):
        snaps = make_snapshots([10, 20, 30])
        self.assertAlmostEqual(compute_sma_tvl(snaps, 7), 20.0)

    def test_single_snapshot(self):
        snaps = make_snapshots([42.0])
        self.assertAlmostEqual(compute_sma_tvl(snaps, 7), 42.0)

    def test_empty_returns_zero(self):
        self.assertEqual(compute_sma_tvl([], 7), 0.0)

    def test_window_one_returns_last(self):
        snaps = make_snapshots([5, 10, 15])
        self.assertAlmostEqual(compute_sma_tvl(snaps, 1), 15.0)


# ---------------------------------------------------------------------------
# analyze_protocol
# ---------------------------------------------------------------------------

class TestAnalyzeProtocol(unittest.TestCase):

    def test_single_snapshot_1d_pct_zero(self):
        m = analyze_protocol("P", make_snapshots([1_000_000]))
        self.assertAlmostEqual(m.tvl_change_1d_pct, 0.0)

    def test_single_snapshot_7d_pct_zero(self):
        m = analyze_protocol("P", make_snapshots([1_000_000]))
        self.assertAlmostEqual(m.tvl_change_7d_pct, 0.0)

    def test_single_snapshot_30d_pct_zero(self):
        m = analyze_protocol("P", make_snapshots([1_000_000]))
        self.assertAlmostEqual(m.tvl_change_30d_pct, 0.0)

    def test_single_snapshot_score_zero(self):
        m = analyze_protocol("P", make_snapshots([1_000_000]))
        self.assertAlmostEqual(m.momentum_score, 0.0)

    def test_tvl_change_1d_pct_increase(self):
        m = analyze_protocol("P", make_snapshots([1_000_000, 1_100_000]))
        self.assertAlmostEqual(m.tvl_change_1d_pct, 10.0)

    def test_tvl_change_1d_pct_decrease(self):
        m = analyze_protocol("P", make_snapshots([1_000_000, 900_000]))
        self.assertAlmostEqual(m.tvl_change_1d_pct, -10.0)

    def test_tvl_change_7d_uses_index_minus8(self):
        # 8 snaps: index 0 = snapshots[-8]
        tvls = [1_000_000] + [1_000_000] * 6 + [1_200_000]
        m = analyze_protocol("P", make_snapshots(tvls))
        self.assertAlmostEqual(m.tvl_change_7d_pct, 20.0)

    def test_tvl_change_7d_uses_first_if_fewer_than_8(self):
        # 4 snaps → ref is index 0
        tvls = [1_000_000, 1_000_000, 1_000_000, 1_500_000]
        m = analyze_protocol("P", make_snapshots(tvls))
        self.assertAlmostEqual(m.tvl_change_7d_pct, 50.0)

    def test_tvl_change_30d_uses_index_minus31(self):
        # 31 snaps: index 0 = snapshots[-31]
        tvls = [1_000_000] + [1_000_000] * 29 + [1_200_000]
        m = analyze_protocol("P", make_snapshots(tvls))
        self.assertAlmostEqual(m.tvl_change_30d_pct, 20.0)

    def test_tvl_change_30d_uses_first_if_fewer_than_31(self):
        # 11 snaps → ref is index 0
        tvls = [2_000_000] + [1_000_000] * 9 + [2_200_000]
        m = analyze_protocol("P", make_snapshots(tvls))
        self.assertAlmostEqual(m.tvl_change_30d_pct, 10.0)

    def test_ath_is_max_tvl(self):
        m = analyze_protocol("P", make_snapshots([1e6, 5e6, 3e6, 2e6]))
        self.assertAlmostEqual(m.all_time_high_tvl_usd, 5e6)

    def test_drawdown_from_ath_formula(self):
        # ATH=10M, current=5M → 50%
        m = analyze_protocol("P", make_snapshots([1e6, 10e6, 5e6]))
        self.assertAlmostEqual(m.drawdown_from_ath_pct, 50.0)

    def test_no_drawdown_when_at_ath(self):
        m = analyze_protocol("P", make_snapshots([1e6, 3e6, 5e6]))
        self.assertAlmostEqual(m.drawdown_from_ath_pct, 0.0)

    def test_is_trending_up_true(self):
        # last snapshot much higher than SMA of last 7
        snaps = make_snapshots([1e6, 1e6, 1e6, 1e6, 1e6, 1e6, 2e6])
        self.assertTrue(analyze_protocol("P", snaps).is_trending_up)

    def test_is_trending_up_false(self):
        snaps = make_snapshots([2e6, 2e6, 2e6, 2e6, 2e6, 2e6, 1e6])
        self.assertFalse(analyze_protocol("P", snaps).is_trending_up)

    def test_monotonically_increasing_is_trending_up(self):
        m = analyze_protocol("P", make_snapshots([1e6, 2e6, 3e6, 4e6, 5e6, 6e6, 7e6]))
        self.assertTrue(m.is_trending_up)

    def test_monotonically_increasing_no_drawdown(self):
        m = analyze_protocol("P", make_snapshots([1e6, 2e6, 3e6, 4e6, 5e6, 6e6, 7e6]))
        self.assertAlmostEqual(m.drawdown_from_ath_pct, 0.0)

    def test_outflow_alert_trigger(self):
        # 9 snaps: big drop on last → score << -5
        snaps = make_snapshots([1e7] * 8 + [5e6])
        m = analyze_protocol("P", snaps)
        self.assertEqual(m.alert, "OUTFLOW_ALERT")

    def test_outflow_alert_recommendation(self):
        snaps = make_snapshots([1e7] * 8 + [5e6])
        m = analyze_protocol("P", snaps)
        self.assertIn("outflow", m.recommendation.lower())

    def test_inflow_signal_trigger(self):
        # 9 snaps: big jump on last → score >> 5
        snaps = make_snapshots([1e6] * 8 + [2e6])
        m = analyze_protocol("P", snaps)
        self.assertEqual(m.alert, "INFLOW_SIGNAL")

    def test_inflow_signal_recommendation(self):
        snaps = make_snapshots([1e6] * 8 + [2e6])
        m = analyze_protocol("P", snaps)
        self.assertIn("inflows", m.recommendation.lower())

    def test_none_alert_when_flat(self):
        snaps = make_snapshots([1e6] * 9)
        m = analyze_protocol("P", snaps)
        self.assertEqual(m.alert, "NONE")

    def test_none_alert_recommendation(self):
        snaps = make_snapshots([1e6] * 9)
        m = analyze_protocol("P", snaps)
        self.assertIn("normal range", m.recommendation.lower())

    def test_protocol_name_stored(self):
        m = analyze_protocol("MyProtocol", make_snapshots([1e6]))
        self.assertEqual(m.protocol, "MyProtocol")

    def test_current_tvl_is_last_snapshot(self):
        m = analyze_protocol("P", make_snapshots([1e6, 2e6, 5e6]))
        self.assertAlmostEqual(m.current_tvl_usd, 5e6)

    def test_returns_tvl_momentum_dataclass(self):
        m = analyze_protocol("P", make_snapshots([1e6]))
        self.assertIsInstance(m, TVLMomentum)

    def test_momentum_label_set(self):
        m = analyze_protocol("P", make_snapshots([1e6]))
        valid = {"STRONG_INFLOW", "INFLOW", "NEUTRAL", "OUTFLOW", "STRONG_OUTFLOW"}
        self.assertIn(m.momentum_label, valid)


# ---------------------------------------------------------------------------
# analyze_market
# ---------------------------------------------------------------------------

class TestAnalyzeMarket(unittest.TestCase):

    def test_top_inflow_top_3_by_score(self):
        pds = [
            make_pd("A", [1e6, 1.5e6]),  # +50%
            make_pd("B", [1e6, 1.3e6]),  # +30%
            make_pd("C", [1e6, 1.1e6]),  # +10%
            make_pd("D", [1e6, 0.9e6]),  # -10%
        ]
        result = analyze_market(pds)
        self.assertIn("A", result.top_inflow_protocols)
        self.assertIn("B", result.top_inflow_protocols)
        self.assertIn("C", result.top_inflow_protocols)
        self.assertNotIn("D", result.top_inflow_protocols)

    def test_top_outflow_bottom_3_by_score(self):
        pds = [
            make_pd("A", [1e6, 0.5e6]),  # -50%
            make_pd("B", [1e6, 0.7e6]),  # -30%
            make_pd("C", [1e6, 0.9e6]),  # -10%
            make_pd("D", [1e6, 1.5e6]),  # +50%
        ]
        result = analyze_market(pds)
        self.assertIn("A", result.top_outflow_protocols)
        self.assertIn("B", result.top_outflow_protocols)
        self.assertNotIn("D", result.top_outflow_protocols)

    def test_market_label_bull(self):
        # all gaining → avg > 3
        pds = [make_pd(f"P{i}", [1e6, 1.2e6]) for i in range(4)]
        self.assertEqual(analyze_market(pds).market_momentum_label, "BULL")

    def test_market_label_bear(self):
        # all losing → avg < -3
        pds = [make_pd(f"P{i}", [1e6, 0.5e6]) for i in range(4)]
        self.assertEqual(analyze_market(pds).market_momentum_label, "BEAR")

    def test_market_label_neutral(self):
        # flat → avg ≈ 0
        pds = [make_pd(f"P{i}", [1e6, 1e6]) for i in range(4)]
        self.assertEqual(analyze_market(pds).market_momentum_label, "NEUTRAL")

    def test_returns_tvl_momentum_result(self):
        result = analyze_market([make_pd("A", [1e6, 1.1e6])])
        self.assertIsInstance(result, TVLMomentumResult)

    def test_protocols_list_populated(self):
        pds = [make_pd(f"P{i}", [1e6, 1.1e6]) for i in range(3)]
        result = analyze_market(pds)
        self.assertEqual(len(result.protocols), 3)

    def test_avg_momentum_score_is_float(self):
        pds = [make_pd("A", [1e6, 1.1e6]), make_pd("B", [1e6, 0.9e6])]
        result = analyze_market(pds)
        self.assertIsInstance(result.avg_momentum_score, float)

    def test_recommendation_summary_nonempty(self):
        pds = [make_pd("A", [1e6, 1.1e6])]
        result = analyze_market(pds)
        self.assertGreater(len(result.recommendation_summary), 0)


# ---------------------------------------------------------------------------
# save_results / load_history
# ---------------------------------------------------------------------------

class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_file = os.path.join(self.tmp_dir, "tvl_momentum_log.json")

    def _make_result(self):
        return analyze_market([make_pd("Aave", [1e6, 1.1e6])])

    def test_save_creates_file(self):
        save_results(self._make_result(), self.data_file)
        self.assertTrue(os.path.exists(self.data_file))

    def test_load_empty_on_missing_file(self):
        self.assertEqual(load_history(self.data_file), [])

    def test_save_load_single_entry(self):
        save_results(self._make_result(), self.data_file)
        history = load_history(self.data_file)
        self.assertEqual(len(history), 1)

    def test_save_accumulates(self):
        save_results(self._make_result(), self.data_file)
        save_results(self._make_result(), self.data_file)
        self.assertEqual(len(load_history(self.data_file)), 2)

    def test_ring_buffer_cap_100(self):
        r = self._make_result()
        for _ in range(105):
            save_results(r, self.data_file)
        self.assertEqual(len(load_history(self.data_file)), 100)

    def test_file_is_valid_json(self):
        save_results(self._make_result(), self.data_file)
        with open(self.data_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_single_snapshot_no_drawdown(self):
        m = analyze_protocol("P", make_snapshots([5e6]))
        self.assertAlmostEqual(m.drawdown_from_ath_pct, 0.0)

    def test_monotonically_increasing_no_drawdown_trending_up(self):
        m = analyze_protocol("P", make_snapshots([1e6, 2e6, 3e6, 4e6, 5e6, 6e6, 7e6]))
        self.assertAlmostEqual(m.drawdown_from_ath_pct, 0.0)
        self.assertTrue(m.is_trending_up)

    def test_single_snapshot_alert_none(self):
        m = analyze_protocol("P", make_snapshots([1e6]))
        self.assertEqual(m.alert, "NONE")


if __name__ == "__main__":
    unittest.main()
