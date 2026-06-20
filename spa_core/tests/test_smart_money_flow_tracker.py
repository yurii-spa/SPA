"""
Tests for MP-694: SmartMoneyFlowTracker
≥65 tests covering all spec requirements.
Uses unittest only (no pytest).
"""

import json
import os
import time
import unittest
import tempfile
from pathlib import Path

from spa_core.analytics.smart_money_flow_tracker import (
    CapitalFlowEvent,
    FlowAnalysis,
    analyze,
    analyze_all,
    load_history,
    save_results,
    _compute_flow_direction,
    _compute_smart_money_score,
    _compute_signal,
    _build_recommendations,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_TS = 1_700_000_000.0  # fixed reference timestamp


def _event(
    protocol="Aave",
    direction="INFLOW",
    amount=1_000_000.0,
    wallet_type="WHALE",
    ts_offset=0,
    is_concentrated=False,
    event_id=None,
):
    return CapitalFlowEvent(
        event_id=event_id or f"evt_{ts_offset}",
        protocol=protocol,
        direction=direction,
        amount_usd=amount,
        timestamp=BASE_TS + ts_offset,
        wallet_type=wallet_type,
        is_concentrated=is_concentrated,
    )


# ---------------------------------------------------------------------------
# 1. _compute_flow_direction
# ---------------------------------------------------------------------------

class TestFlowDirection(unittest.TestCase):

    def test_strong_inflow_exact_boundary(self):
        # net = 31% of volume → STRONG_INFLOW
        self.assertEqual(_compute_flow_direction(310, 1000), "STRONG_INFLOW")

    def test_strong_inflow_above_boundary(self):
        self.assertEqual(_compute_flow_direction(500, 1000), "STRONG_INFLOW")

    def test_inflow_above_10pct(self):
        # net = 15% → INFLOW
        self.assertEqual(_compute_flow_direction(150, 1000), "INFLOW")

    def test_inflow_exact_10pct_plus_epsilon(self):
        self.assertEqual(_compute_flow_direction(101, 1000), "INFLOW")

    def test_neutral_positive_small(self):
        # net = 5% → NEUTRAL
        self.assertEqual(_compute_flow_direction(50, 1000), "NEUTRAL")

    def test_neutral_zero(self):
        self.assertEqual(_compute_flow_direction(0, 1000), "NEUTRAL")

    def test_neutral_zero_volume(self):
        self.assertEqual(_compute_flow_direction(0, 0), "NEUTRAL")

    def test_outflow_negative_small(self):
        # net = -15% → OUTFLOW
        self.assertEqual(_compute_flow_direction(-150, 1000), "OUTFLOW")

    def test_strong_outflow_negative_large(self):
        # net = -40% → STRONG_OUTFLOW
        self.assertEqual(_compute_flow_direction(-400, 1000), "STRONG_OUTFLOW")

    def test_outflow_exactly_10pct_minus(self):
        # net = -10.1% → OUTFLOW
        self.assertEqual(_compute_flow_direction(-101, 1000), "OUTFLOW")


# ---------------------------------------------------------------------------
# 2. _compute_smart_money_score
# ---------------------------------------------------------------------------

class TestSmartMoneyScore(unittest.TestCase):

    def test_empty_events_returns_zero(self):
        self.assertEqual(_compute_smart_money_score([]), 0.0)

    def test_all_whale(self):
        events = [_event(wallet_type="WHALE") for _ in range(4)]
        self.assertAlmostEqual(_compute_smart_money_score(events), 1.0)

    def test_all_institution(self):
        events = [_event(wallet_type="INSTITUTION") for _ in range(3)]
        self.assertAlmostEqual(_compute_smart_money_score(events), 1.0)

    def test_all_retail_returns_zero(self):
        events = [_event(wallet_type="RETAIL") for _ in range(5)]
        self.assertAlmostEqual(_compute_smart_money_score(events), 0.0)

    def test_mixed_half_half(self):
        events = [_event(wallet_type="WHALE"), _event(wallet_type="RETAIL")]
        self.assertAlmostEqual(_compute_smart_money_score(events), 0.5)

    def test_dao_not_counted_as_smart(self):
        events = [_event(wallet_type="DAO"), _event(wallet_type="WHALE")]
        # 1 of 2 smart → 0.5
        self.assertAlmostEqual(_compute_smart_money_score(events), 0.5)

    def test_whale_and_institution_both_count(self):
        events = [
            _event(wallet_type="WHALE"),
            _event(wallet_type="INSTITUTION"),
            _event(wallet_type="RETAIL"),
        ]
        self.assertAlmostEqual(_compute_smart_money_score(events), 2 / 3)


# ---------------------------------------------------------------------------
# 3. _compute_signal
# ---------------------------------------------------------------------------

class TestComputeSignal(unittest.TestCase):

    def test_bullish_strong_inflow_smart_money(self):
        self.assertEqual(_compute_signal("STRONG_INFLOW", 0.5, False), "BULLISH")

    def test_bullish_inflow_smart_money_above_threshold(self):
        self.assertEqual(_compute_signal("INFLOW", 0.41, False), "BULLISH")

    def test_not_bullish_inflow_low_smart_money(self):
        # smart_money_score == 0.4 is NOT > 0.4, so not BULLISH
        result = _compute_signal("INFLOW", 0.4, False)
        self.assertNotEqual(result, "BULLISH")

    def test_bearish_exodus(self):
        self.assertEqual(_compute_signal("NEUTRAL", 0.8, True), "BEARISH")

    def test_bearish_strong_outflow(self):
        self.assertEqual(_compute_signal("STRONG_OUTFLOW", 0.0, False), "BEARISH")

    def test_bearish_outflow(self):
        self.assertEqual(_compute_signal("OUTFLOW", 0.0, False), "BEARISH")

    def test_neutral_no_signal(self):
        self.assertEqual(_compute_signal("NEUTRAL", 0.3, False), "NEUTRAL")

    def test_neutral_inflow_but_low_smart_money(self):
        self.assertEqual(_compute_signal("INFLOW", 0.2, False), "NEUTRAL")


# ---------------------------------------------------------------------------
# 4. _build_recommendations
# ---------------------------------------------------------------------------

class TestBuildRecommendations(unittest.TestCase):

    def test_accumulation_adds_whale_message(self):
        recs = _build_recommendations(True, False, 0.7, "BULLISH")
        self.assertTrue(any("🐋" in r for r in recs))

    def test_exodus_adds_exodus_message(self):
        recs = _build_recommendations(False, True, 0.0, "BEARISH")
        self.assertTrue(any("🚨" in r for r in recs))

    def test_high_smart_money_adds_reliability_message(self):
        recs = _build_recommendations(False, False, 0.7, "NEUTRAL")
        self.assertTrue(any("📊" in r for r in recs))

    def test_bullish_signal_adds_bullish_message(self):
        recs = _build_recommendations(False, False, 0.3, "BULLISH")
        self.assertTrue(any("✅" in r for r in recs))

    def test_bearish_signal_adds_bearish_message(self):
        recs = _build_recommendations(False, False, 0.0, "BEARISH")
        self.assertTrue(any("⚠️" in r for r in recs))

    def test_neutral_no_accumulation_no_exodus_minimal_recs(self):
        recs = _build_recommendations(False, False, 0.3, "NEUTRAL")
        # smart_money ≤ 0.6, signal NEUTRAL → no emoji recs beyond empty
        self.assertIsInstance(recs, list)

    def test_smart_money_below_threshold_no_reliability_message(self):
        recs = _build_recommendations(False, False, 0.6, "NEUTRAL")
        # 0.6 is NOT > 0.6
        self.assertFalse(any("📊" in r for r in recs))

    def test_multiple_flags_combined(self):
        recs = _build_recommendations(True, True, 0.8, "BEARISH")
        # expects: accumulation + exodus + high_smart + bearish
        self.assertGreaterEqual(len(recs), 4)


# ---------------------------------------------------------------------------
# 5. analyze() — per-protocol analysis
# ---------------------------------------------------------------------------

class TestAnalyze(unittest.TestCase):

    def _make_events(self):
        """Balanced scenario: Aave 2×INFLOW WHALE, 1×OUTFLOW RETAIL."""
        return [
            _event("Aave", "INFLOW",  1_000_000, "WHALE",       ts_offset=0),
            _event("Aave", "INFLOW",  2_000_000, "INSTITUTION", ts_offset=100),
            _event("Aave", "OUTFLOW", 500_000,   "RETAIL",      ts_offset=200),
            _event("Compound", "INFLOW", 500_000, "WHALE",       ts_offset=50),
        ]

    # --- inflow / outflow / net ---

    def test_total_inflow_sum(self):
        fa = analyze("Aave", self._make_events())
        self.assertAlmostEqual(fa.total_inflow_usd, 3_000_000.0)

    def test_total_outflow_sum(self):
        fa = analyze("Aave", self._make_events())
        self.assertAlmostEqual(fa.total_outflow_usd, 500_000.0)

    def test_net_flow_inflow_minus_outflow(self):
        fa = analyze("Aave", self._make_events())
        self.assertAlmostEqual(fa.net_flow_usd, 2_500_000.0)

    # --- flow_direction ---

    def test_flow_direction_strong_inflow(self):
        # net=2.5M, volume=3.5M → net/vol ≈ 71% → STRONG_INFLOW
        fa = analyze("Aave", self._make_events())
        self.assertEqual(fa.flow_direction, "STRONG_INFLOW")

    def test_flow_direction_neutral_balanced(self):
        events = [
            _event("X", "INFLOW",  1_000, "RETAIL", ts_offset=0),
            _event("X", "OUTFLOW", 1_000, "RETAIL", ts_offset=1),
        ]
        fa = analyze("X", events)
        self.assertEqual(fa.flow_direction, "NEUTRAL")

    def test_flow_direction_strong_outflow(self):
        events = [
            _event("X", "INFLOW",  100, "RETAIL", ts_offset=0),
            _event("X", "OUTFLOW", 900, "RETAIL", ts_offset=1),
        ]
        # net = -800, volume = 1000, ratio = -80% → STRONG_OUTFLOW
        fa = analyze("X", events)
        self.assertEqual(fa.flow_direction, "STRONG_OUTFLOW")

    def test_flow_direction_outflow_moderate(self):
        events = [
            _event("X", "INFLOW",  400, "RETAIL", ts_offset=0),
            _event("X", "OUTFLOW", 600, "RETAIL", ts_offset=1),
        ]
        # net = -200, volume = 1000, ratio = -20% → OUTFLOW
        fa = analyze("X", events)
        self.assertEqual(fa.flow_direction, "OUTFLOW")

    # --- smart_money_score ---

    def test_smart_money_score_whale_institution(self):
        fa = analyze("Aave", self._make_events())
        # 2 whale/institution out of 3 Aave events → ~0.667
        self.assertAlmostEqual(fa.smart_money_score, 2 / 3, places=5)

    def test_smart_money_score_all_retail(self):
        events = [_event("X", "INFLOW", 1000, "RETAIL", ts_offset=i) for i in range(4)]
        fa = analyze("X", events)
        self.assertAlmostEqual(fa.smart_money_score, 0.0)

    # --- is_exodus ---

    def test_is_exodus_true_when_net_outflow_gt_20pct(self):
        events = [
            _event("X", "INFLOW",  300, "RETAIL", ts_offset=0),
            _event("X", "OUTFLOW", 700, "RETAIL", ts_offset=1),
        ]
        # net = -400, volume = 1000, -40% → exodus
        fa = analyze("X", events)
        self.assertTrue(fa.is_exodus)

    def test_is_exodus_false_when_balanced(self):
        fa = analyze("Aave", self._make_events())
        self.assertFalse(fa.is_exodus)

    def test_is_exodus_false_no_events(self):
        fa = analyze("Missing", self._make_events())
        self.assertFalse(fa.is_exodus)

    # --- is_accumulation ---

    def test_is_accumulation_true_inflow_and_smart_money(self):
        # net/volume > 20%, smart_money > 0.5
        fa = analyze("Aave", self._make_events())
        # net=2.5M/3.5M ≈ 71%; smart_money≈0.667 → accumulation
        self.assertTrue(fa.is_accumulation)

    def test_is_accumulation_false_low_smart_money(self):
        events = [
            _event("X", "INFLOW",  900, "RETAIL", ts_offset=0),
            _event("X", "OUTFLOW", 100, "RETAIL", ts_offset=1),
        ]
        # net = 800/1000 = 80% but smart_money = 0 → no accumulation
        fa = analyze("X", events)
        self.assertFalse(fa.is_accumulation)

    def test_is_accumulation_false_low_net(self):
        events = [
            _event("X", "INFLOW",  510, "WHALE", ts_offset=0),
            _event("X", "OUTFLOW", 490, "WHALE", ts_offset=1),
        ]
        # net = 20/1000 = 2% → not > 20%
        fa = analyze("X", events)
        self.assertFalse(fa.is_accumulation)

    # --- signal ---

    def test_signal_bullish_strong_inflow_high_smart(self):
        fa = analyze("Aave", self._make_events())
        self.assertEqual(fa.signal, "BULLISH")

    def test_signal_bearish_exodus(self):
        events = [
            _event("X", "INFLOW",  200, "RETAIL", ts_offset=0),
            _event("X", "OUTFLOW", 800, "RETAIL", ts_offset=1),
        ]
        fa = analyze("X", events)
        self.assertEqual(fa.signal, "BEARISH")

    def test_signal_neutral_balanced_retail(self):
        events = [
            _event("X", "INFLOW",  500, "RETAIL", ts_offset=0),
            _event("X", "OUTFLOW", 500, "RETAIL", ts_offset=1),
        ]
        fa = analyze("X", events)
        self.assertEqual(fa.signal, "NEUTRAL")

    # --- largest_single_flow ---

    def test_largest_single_flow(self):
        fa = analyze("Aave", self._make_events())
        self.assertAlmostEqual(fa.largest_single_flow_usd, 2_000_000.0)

    def test_largest_single_flow_zero_no_events(self):
        fa = analyze("NoProtocol", self._make_events())
        self.assertAlmostEqual(fa.largest_single_flow_usd, 0.0)

    # --- event_count ---

    def test_event_count_correct(self):
        fa = analyze("Aave", self._make_events())
        self.assertEqual(fa.event_count, 3)

    def test_event_count_zero_no_match(self):
        fa = analyze("NoProtocol", self._make_events())
        self.assertEqual(fa.event_count, 0)

    # --- protocol filter ---

    def test_analyze_filters_by_protocol(self):
        fa_compound = analyze("Compound", self._make_events())
        self.assertEqual(fa_compound.event_count, 1)
        self.assertAlmostEqual(fa_compound.total_inflow_usd, 500_000.0)

    def test_analyze_different_protocols_independent(self):
        fa_aave = analyze("Aave", self._make_events())
        fa_compound = analyze("Compound", self._make_events())
        self.assertNotEqual(fa_aave.total_inflow_usd, fa_compound.total_inflow_usd)

    # --- window filter ---

    def test_window_filter_excludes_old_events(self):
        # window = 1 hour; latest event at BASE_TS + 3700
        events = [
            _event("X", "INFLOW", 1_000_000, "WHALE", ts_offset=0),       # OLD
            _event("X", "INFLOW", 2_000_000, "WHALE", ts_offset=3700),    # NEW (latest)
        ]
        fa = analyze("X", events, window_hours=1)
        # cutoff = (BASE_TS+3700) - 3600 = BASE_TS+100; event at ts_offset=0 excluded
        self.assertEqual(fa.event_count, 1)
        self.assertAlmostEqual(fa.total_inflow_usd, 2_000_000.0)

    def test_window_filter_includes_events_within_window(self):
        events = [
            _event("X", "INFLOW", 1_000, "WHALE", ts_offset=0),
            _event("X", "INFLOW", 2_000, "WHALE", ts_offset=100),
        ]
        fa = analyze("X", events, window_hours=24)
        self.assertEqual(fa.event_count, 2)

    def test_window_filter_all_old_returns_zeros(self):
        # All events are far in the past; latest event at BASE_TS+0 → only 1hr window
        events = [_event("X", "INFLOW", 1_000_000, "WHALE", ts_offset=0)]
        # window covers only the event itself (latest_ts − 3600 ≤ ts < latest_ts)
        # ts_offset=0 means event IS the latest → cutoff = BASE_TS−3600 → included
        fa = analyze("X", events, window_hours=1)
        self.assertEqual(fa.event_count, 1)

    def test_window_filter_zero_hours_excludes_older_event(self):
        # 0-hour window: cutoff == latest_ts; event older than latest is excluded
        events = [
            _event("X", "INFLOW", 1_000_000, "WHALE", ts_offset=-1),   # 1 sec older than latest
            _event("X", "INFLOW", 2_000_000, "WHALE", ts_offset=0),    # latest
        ]
        fa = analyze("X", events, window_hours=0)
        # cutoff = BASE_TS+0 - 0 = BASE_TS; event at BASE_TS-1 excluded, event at BASE_TS included
        self.assertEqual(fa.event_count, 1)
        self.assertAlmostEqual(fa.total_inflow_usd, 2_000_000.0)

    # --- empty events ---

    def test_empty_events_returns_neutral_zeros(self):
        fa = analyze("Aave", [])
        self.assertEqual(fa.signal, "NEUTRAL")
        self.assertAlmostEqual(fa.total_inflow_usd, 0.0)
        self.assertAlmostEqual(fa.total_outflow_usd, 0.0)
        self.assertAlmostEqual(fa.net_flow_usd, 0.0)
        self.assertEqual(fa.event_count, 0)
        self.assertAlmostEqual(fa.smart_money_score, 0.0)
        self.assertFalse(fa.is_exodus)
        self.assertFalse(fa.is_accumulation)

    def test_empty_events_flow_direction_neutral(self):
        fa = analyze("Aave", [])
        self.assertEqual(fa.flow_direction, "NEUTRAL")

    def test_empty_events_largest_flow_zero(self):
        fa = analyze("Aave", [])
        self.assertAlmostEqual(fa.largest_single_flow_usd, 0.0)

    # --- recommendations ---

    def test_accumulation_recommendation_present(self):
        fa = analyze("Aave", self._make_events())
        self.assertTrue(any("🐋" in r for r in fa.recommendations))

    def test_bullish_recommendation_present(self):
        fa = analyze("Aave", self._make_events())
        self.assertTrue(any("✅" in r for r in fa.recommendations))

    def test_bearish_recommendation_for_exodus(self):
        events = [
            _event("X", "INFLOW",  100, "RETAIL", ts_offset=0),
            _event("X", "OUTFLOW", 900, "RETAIL", ts_offset=1),
        ]
        fa = analyze("X", events)
        self.assertTrue(any("🚨" in r for r in fa.recommendations))

    # --- protocol field ---

    def test_result_protocol_matches_input(self):
        fa = analyze("Morpho", self._make_events())
        self.assertEqual(fa.protocol, "Morpho")

    def test_result_window_hours_matches_input(self):
        fa = analyze("Aave", self._make_events(), window_hours=48)
        self.assertEqual(fa.analysis_window_hours, 48)


# ---------------------------------------------------------------------------
# 6. analyze_all()
# ---------------------------------------------------------------------------

class TestAnalyzeAll(unittest.TestCase):

    def _mixed_events(self):
        return [
            _event("Aave",     "INFLOW",  1_000_000, "WHALE", ts_offset=0),
            _event("Compound", "INFLOW",  500_000,   "INSTITUTION", ts_offset=1),
            _event("Aave",     "OUTFLOW", 200_000,   "RETAIL", ts_offset=2),
        ]

    def test_analyze_all_groups_by_protocol(self):
        results = analyze_all(self._mixed_events())
        protocols = [fa.protocol for fa in results]
        self.assertIn("Aave", protocols)
        self.assertIn("Compound", protocols)

    def test_analyze_all_returns_one_result_per_protocol(self):
        results = analyze_all(self._mixed_events())
        self.assertEqual(len(results), 2)

    def test_analyze_all_correct_counts(self):
        results = analyze_all(self._mixed_events())
        aave = next(fa for fa in results if fa.protocol == "Aave")
        compound = next(fa for fa in results if fa.protocol == "Compound")
        self.assertEqual(aave.event_count, 2)
        self.assertEqual(compound.event_count, 1)

    def test_analyze_all_empty_returns_empty_list(self):
        self.assertEqual(analyze_all([]), [])

    def test_analyze_all_single_protocol(self):
        events = [_event("Yearn", "INFLOW", 1_000, "WHALE", ts_offset=i) for i in range(3)]
        results = analyze_all(events)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].protocol, "Yearn")

    def test_analyze_all_preserves_protocol_order(self):
        # Aave appears first in events list
        results = analyze_all(self._mixed_events())
        self.assertEqual(results[0].protocol, "Aave")


# ---------------------------------------------------------------------------
# 7. save_results / load_history
# ---------------------------------------------------------------------------

class TestPersistence(unittest.TestCase):

    def _simple_analysis(self, protocol="Aave"):
        events = [_event(protocol, "INFLOW", 1_000_000, "WHALE", ts_offset=0)]
        return analyze(protocol, events)

    def test_load_history_returns_empty_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nonexistent.json"
            self.assertEqual(load_history(path), [])

    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "flow_log.json"
            save_results([self._simple_analysis()], data_file=path)
            self.assertTrue(path.exists())

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "flow_log.json"
            save_results([self._simple_analysis()], data_file=path)
            records = load_history(path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["protocol"], "Aave")

    def test_save_appends_to_existing(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "flow_log.json"
            save_results([self._simple_analysis("Aave")], data_file=path)
            save_results([self._simple_analysis("Compound")], data_file=path)
            records = load_history(path)
            self.assertEqual(len(records), 2)

    def test_ring_buffer_max_entries(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "flow_log.json"
            max_e = 5
            for i in range(7):
                save_results([self._simple_analysis(f"P{i}")], data_file=path, max_entries=max_e)
            records = load_history(path)
            self.assertEqual(len(records), max_e)

    def test_ring_buffer_keeps_latest(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "flow_log.json"
            max_e = 3
            for i in range(5):
                save_results([self._simple_analysis(f"P{i}")], data_file=path, max_entries=max_e)
            records = load_history(path)
            protocols = [r["protocol"] for r in records]
            self.assertIn("P4", protocols)
            self.assertNotIn("P0", protocols)

    def test_atomic_write_no_tmp_file_left(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "flow_log.json"
            save_results([self._simple_analysis()], data_file=path)
            tmp = path.with_suffix(".tmp")
            self.assertFalse(tmp.exists())

    def test_load_history_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "flow_log.json"
            path.write_text("not valid json")
            self.assertEqual(load_history(path), [])

    def test_save_multiple_analyses_in_one_call(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "flow_log.json"
            analyses = [self._simple_analysis("A"), self._simple_analysis("B")]
            save_results(analyses, data_file=path)
            records = load_history(path)
            self.assertEqual(len(records), 2)


if __name__ == "__main__":
    unittest.main()
