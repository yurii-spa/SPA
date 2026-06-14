"""
Tests for MP-815 SmartMoneyFlowDetector
≥65 test cases — unittest only (no third-party deps).
"""

import json
import os
import tempfile
import time
import unittest

from spa_core.analytics.smart_money_flow_detector import (
    analyze,
    init_log,
    _clamp,
    _compute_flow_signal,
    _compute_whale_signal,
    _build_interpretation,
    _load_log,
    _save_log,
)

_NOW = time.time()


def _event(action="deposit", amount=100_000.0, wallet_type="retail", offset_secs=0):
    return {
        "timestamp": _NOW - offset_secs,
        "wallet_type": wallet_type,
        "action": action,
        "amount_usd": amount,
    }


def _whale_deposit(amount=1_000_000.0, offset_secs=3600):
    return _event("deposit", amount, "whale", offset_secs)


def _whale_withdrawal(amount=1_000_000.0, offset_secs=3600):
    return _event("withdrawal", amount, "whale", offset_secs)


class TestClamp(unittest.TestCase):
    def test_clamp_within(self):
        self.assertEqual(_clamp(50.0, -100.0, 100.0), 50.0)

    def test_clamp_max(self):
        self.assertEqual(_clamp(200.0, -100.0, 100.0), 100.0)

    def test_clamp_min(self):
        self.assertEqual(_clamp(-200.0, -100.0, 100.0), -100.0)

    def test_clamp_exact_boundary(self):
        self.assertEqual(_clamp(-100.0, -100.0, 100.0), -100.0)
        self.assertEqual(_clamp(100.0, -100.0, 100.0), 100.0)

    def test_clamp_zero(self):
        self.assertEqual(_clamp(0.0, -100.0, 100.0), 0.0)


class TestComputeFlowSignal(unittest.TestCase):
    def test_no_events_neutral(self):
        self.assertEqual(_compute_flow_signal(0, 0, 0), "NEUTRAL")

    def test_strong_inflow(self):
        # net_pct = 800/1000 * 100 = 80 > 50
        self.assertEqual(_compute_flow_signal(800, 900, 100), "STRONG_INFLOW")

    def test_inflow(self):
        # net=200, total=1200, pct≈16.7
        self.assertEqual(_compute_flow_signal(200, 700, 500), "INFLOW")

    def test_neutral_positive_edge(self):
        # net=100, total=1000, pct=10 → boundary: >10 is INFLOW, so 10 is NEUTRAL
        self.assertEqual(_compute_flow_signal(100, 550, 450), "NEUTRAL")

    def test_neutral_zero(self):
        self.assertEqual(_compute_flow_signal(0, 500, 500), "NEUTRAL")

    def test_neutral_negative_edge(self):
        # net=-100, total=1000, pct=-10 → ≥-10 = NEUTRAL
        self.assertEqual(_compute_flow_signal(-100, 450, 550), "NEUTRAL")

    def test_outflow(self):
        # net=-200, total=1200, pct≈-16.7
        self.assertEqual(_compute_flow_signal(-200, 500, 700), "OUTFLOW")

    def test_strong_outflow(self):
        # net=-800, total=1000, pct=-80
        self.assertEqual(_compute_flow_signal(-800, 100, 900), "STRONG_OUTFLOW")

    def test_all_inflow_strong(self):
        self.assertEqual(_compute_flow_signal(1000, 1000, 0), "STRONG_INFLOW")

    def test_all_outflow_strong(self):
        self.assertEqual(_compute_flow_signal(-1000, 0, 1000), "STRONG_OUTFLOW")


class TestComputeWhaleSignal(unittest.TestCase):
    def test_accumulating(self):
        self.assertEqual(_compute_whale_signal(500_000), "ACCUMULATING")

    def test_distributing(self):
        self.assertEqual(_compute_whale_signal(-500_000), "DISTRIBUTING")

    def test_neutral_zero(self):
        self.assertEqual(_compute_whale_signal(0), "NEUTRAL")

    def test_small_positive(self):
        self.assertEqual(_compute_whale_signal(0.01), "ACCUMULATING")

    def test_small_negative(self):
        self.assertEqual(_compute_whale_signal(-0.01), "DISTRIBUTING")


class TestBuildInterpretation(unittest.TestCase):
    def test_strong_inflow_accumulating(self):
        txt = _build_interpretation("STRONG_INFLOW", "ACCUMULATING", 1_200_000, 1_000_000)
        self.assertIn("bullish", txt)
        self.assertIn("inflow", txt)

    def test_strong_outflow_distributing(self):
        txt = _build_interpretation("STRONG_OUTFLOW", "DISTRIBUTING", -2_000_000, -1_500_000)
        self.assertIn("monitor", txt.lower())

    def test_inflow_neutral_whale(self):
        txt = _build_interpretation("INFLOW", "NEUTRAL", 500_000, 0)
        self.assertIn("inflow", txt.lower())

    def test_outflow_neutral_whale(self):
        txt = _build_interpretation("OUTFLOW", "NEUTRAL", -500_000, 0)
        self.assertIn("outflow", txt.lower())

    def test_neutral_accumulating(self):
        txt = _build_interpretation("NEUTRAL", "ACCUMULATING", 0, 100_000)
        self.assertIn("whale accumulation", txt.lower())

    def test_neutral_distributing(self):
        txt = _build_interpretation("NEUTRAL", "DISTRIBUTING", 0, -100_000)
        self.assertIn("whale distribution", txt.lower())

    def test_neutral_neutral(self):
        txt = _build_interpretation("NEUTRAL", "NEUTRAL", 0, 0)
        self.assertIn("neutral", txt.lower())

    def test_large_amount_m_format(self):
        txt = _build_interpretation("STRONG_INFLOW", "ACCUMULATING", 2_500_000, 2_000_000)
        self.assertIn("M", txt)

    def test_small_amount_k_format(self):
        txt = _build_interpretation("INFLOW", "NEUTRAL", 300_000, 0)
        self.assertIn("K", txt)


class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "smart_money_flow_log.json")

    def test_empty_events_returns_zeros(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        r24 = r["recent_24h"]
        self.assertEqual(r24["gross_inflow_usd"], 0.0)
        self.assertEqual(r24["gross_outflow_usd"], 0.0)
        self.assertEqual(r24["net_flow_usd"], 0.0)
        self.assertEqual(r24["whale_inflow_usd"], 0.0)
        self.assertEqual(r24["whale_outflow_usd"], 0.0)
        self.assertEqual(r24["whale_net_flow_usd"], 0.0)
        self.assertEqual(r24["deposit_count"], 0)
        self.assertEqual(r24["withdrawal_count"], 0)
        self.assertEqual(r24["largest_single_event_usd"], 0.0)

    def test_empty_signals_neutral(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertEqual(r["flow_signal"], "NEUTRAL")
        self.assertEqual(r["whale_signal"], "NEUTRAL")
        self.assertEqual(r["smart_money_score"], 0)

    def test_empty_no_risk_events(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertEqual(r["risk_events"], [])

    def test_protocol_name_preserved(self):
        r = analyze("morpho_steakhouse", [], log_path=self.log, persist=False)
        self.assertEqual(r["protocol"], "morpho_steakhouse")

    def test_timestamp_present(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertIn("timestamp", r)
        self.assertIsInstance(r["timestamp"], float)


class TestAnalyzeWhaleDeposit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "smart_money_flow_log.json")

    def test_single_whale_deposit_inflow(self):
        events = [_whale_deposit(2_000_000, 3600)]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertEqual(r["flow_signal"], "STRONG_INFLOW")

    def test_single_whale_deposit_accumulating(self):
        events = [_whale_deposit(2_000_000, 3600)]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertEqual(r["whale_signal"], "ACCUMULATING")

    def test_single_whale_deposit_positive_score(self):
        events = [_whale_deposit(2_000_000, 3600)]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertGreater(r["smart_money_score"], 0)

    def test_whale_inflow_counted(self):
        events = [_whale_deposit(2_000_000, 3600)]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["whale_inflow_usd"], 2_000_000)

    def test_institution_counted_as_whale(self):
        ev = _event("deposit", 1_000_000, "institution", 3600)
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["whale_inflow_usd"], 1_000_000)

    def test_deposit_count(self):
        events = [_whale_deposit(1_000_000, 100), _whale_deposit(500_000, 200)]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["deposit_count"], 2)


class TestAnalyzeWhaleWithdrawal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "smart_money_flow_log.json")

    def test_single_whale_withdrawal_outflow(self):
        events = [_whale_withdrawal(2_000_000, 3600)]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertEqual(r["flow_signal"], "STRONG_OUTFLOW")

    def test_single_whale_withdrawal_distributing(self):
        events = [_whale_withdrawal(2_000_000, 3600)]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertEqual(r["whale_signal"], "DISTRIBUTING")

    def test_whale_withdrawal_risk_event(self):
        events = [_whale_withdrawal(2_500_000, 3600)]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertTrue(any("Large whale withdrawal" in e for e in r["risk_events"]))

    def test_whale_withdrawal_risk_event_amount_format(self):
        events = [_whale_withdrawal(2_500_000, 3600)]
        r = analyze("aave", events, log_path=self.log, persist=False)
        risk = r["risk_events"][0]
        self.assertIn("$2.5M", risk)

    def test_retail_withdrawal_no_risk_event(self):
        events = [_event("withdrawal", 10_000, "retail", 3600)]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertEqual(r["risk_events"], [])

    def test_withdrawal_count(self):
        events = [_whale_withdrawal(1_000_000, 100), _whale_withdrawal(800_000, 200)]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["withdrawal_count"], 2)

    def test_negative_score_on_whale_withdrawal(self):
        events = [_whale_withdrawal(2_000_000, 3600)]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertLess(r["smart_money_score"], 0)


class TestAnalyzeMixedEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "smart_money_flow_log.json")

    def test_equal_inflow_outflow_neutral(self):
        events = [
            _whale_deposit(1_000_000, 3600),
            _whale_withdrawal(1_000_000, 1800),
        ]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertEqual(r["flow_signal"], "NEUTRAL")

    def test_net_flow_calculation(self):
        events = [
            _whale_deposit(3_000_000, 3600),
            _whale_withdrawal(1_000_000, 1800),
        ]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertAlmostEqual(r["recent_24h"]["net_flow_usd"], 2_000_000)

    def test_largest_single_event(self):
        events = [
            _whale_deposit(3_000_000, 3600),
            _whale_withdrawal(1_000_000, 1800),
            _event("deposit", 500_000, "retail", 100),
        ]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["largest_single_event_usd"], 3_000_000)

    def test_gross_inflow_outflow_separate(self):
        events = [
            _whale_deposit(2_000_000, 3600),
            _whale_withdrawal(800_000, 1800),
        ]
        r = analyze("aave", events, log_path=self.log, persist=False)
        r24 = r["recent_24h"]
        self.assertAlmostEqual(r24["gross_inflow_usd"], 2_000_000)
        self.assertAlmostEqual(r24["gross_outflow_usd"], 800_000)


class TestLookbackFiltering(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "smart_money_flow_log.json")

    def test_old_event_excluded_from_recent(self):
        # 30 hours ago — outside 24h default lookback
        old_ev = _whale_deposit(5_000_000, offset_secs=30 * 3600)
        r = analyze("aave", [old_ev], log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["deposit_count"], 0)

    def test_recent_event_included(self):
        ev = _whale_deposit(1_000_000, offset_secs=3600)  # 1 hour ago
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["deposit_count"], 1)

    def test_custom_lookback_hours(self):
        # 30h ago, but lookback = 48h → should be included
        ev = _whale_deposit(1_000_000, offset_secs=30 * 3600)
        cfg = {"lookback_hours": 48.0}
        r = analyze("aave", [ev], config=cfg, log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["deposit_count"], 1)

    def test_signal_window_includes_7day_events(self):
        # 5 days ago — inside 7d window but outside 24h
        # whale_net_flow (24h numerator) = 0, but window vol (denominator) = 2M
        # So score = 0 / (2M + 1) * 100 = 0
        ev = _whale_deposit(2_000_000, offset_secs=5 * 24 * 3600)
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        # No 24h whale flow → score = 0 (denominator is non-zero but numerator is 0)
        self.assertEqual(r["smart_money_score"], 0)

    def test_8day_old_event_excluded_from_context(self):
        ev = _whale_deposit(2_000_000, offset_secs=8 * 24 * 3600)
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        # 8 days old, outside 7d window → score ≈ 0
        self.assertEqual(r["smart_money_score"], 0)


class TestRiskEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "smart_money_flow_log.json")

    def test_no_risk_event_below_threshold(self):
        ev = _event("withdrawal", 400_000, "whale", 3600)
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        large_risk = [e for e in r["risk_events"] if "Large whale withdrawal" in e]
        self.assertEqual(large_risk, [])

    def test_elevated_whale_exits_risk_event(self):
        # Whale outflow > 10% of 7d volume
        # 7d vol = whale withdrawal amount; 10% = same
        # Put a large whale withdrawal (within 24h) + context
        ev_recent = _whale_withdrawal(2_000_000, offset_secs=3600)
        # No other events: 7d_vol = 2_000_000; whale_outflow=2_000_000 > 10%*2_000_000
        r = analyze("aave", [ev_recent], log_path=self.log, persist=False)
        # whale_outflow (2M) > 10% of window_vol (2M) = 200K → True
        self.assertTrue(any("Elevated whale exits" in e for e in r["risk_events"]))

    def test_multiple_whale_withdrawals_multiple_risk_events(self):
        events = [
            _whale_withdrawal(1_000_000, 3600),
            _whale_withdrawal(800_000, 1800),
        ]
        r = analyze("aave", events, log_path=self.log, persist=False)
        large_risks = [e for e in r["risk_events"] if "Large whale withdrawal" in e]
        self.assertEqual(len(large_risks), 2)

    def test_risk_event_amount_formatting_1m(self):
        ev = _whale_withdrawal(1_000_000, 3600)
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        large_risks = [e for e in r["risk_events"] if "Large whale withdrawal" in e]
        self.assertTrue(any("$1.0M" in e for e in large_risks))


class TestSmartMoneyScore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "smart_money_flow_log.json")

    def test_score_clamped_max(self):
        # Massive whale inflow with tiny context → score → 100
        ev = _whale_deposit(1_000_000_000, 3600)
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        self.assertLessEqual(r["smart_money_score"], 100)

    def test_score_clamped_min(self):
        ev = _whale_withdrawal(1_000_000_000, 3600)
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        self.assertGreaterEqual(r["smart_money_score"], -100)

    def test_score_is_int(self):
        ev = _whale_deposit(1_000_000, 3600)
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        self.assertIsInstance(r["smart_money_score"], int)

    def test_score_zero_on_no_events(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertEqual(r["smart_money_score"], 0)


class TestPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "smart_money_flow_log.json")

    def test_persist_true_creates_log(self):
        analyze("aave", [], log_path=self.log, persist=True)
        self.assertTrue(os.path.exists(self.log))

    def test_persist_false_no_file_created(self):
        analyze("aave", [], log_path=self.log, persist=False)
        self.assertFalse(os.path.exists(self.log))

    def test_persist_appends_entries(self):
        analyze("aave", [], log_path=self.log, persist=True)
        analyze("compound", [], log_path=self.log, persist=True)
        entries = _load_log(self.log)
        self.assertEqual(len(entries), 2)

    def test_ring_buffer_cap(self):
        for i in range(110):
            analyze(f"proto_{i}", [], log_path=self.log, persist=True)
        entries = _load_log(self.log)
        self.assertLessEqual(len(entries), 100)

    def test_log_is_valid_json(self):
        analyze("aave", [], log_path=self.log, persist=True)
        with open(self.log, "r") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_init_log_creates_empty_list(self):
        path = os.path.join(self.tmp, "new_log.json")
        init_log(path)
        self.assertTrue(os.path.exists(path))
        data = _load_log(path)
        self.assertEqual(data, [])

    def test_load_log_missing_file(self):
        path = os.path.join(self.tmp, "nonexistent.json")
        data = _load_log(path)
        self.assertEqual(data, [])

    def test_load_log_corrupted_returns_empty(self):
        path = os.path.join(self.tmp, "bad.json")
        with open(path, "w") as fh:
            fh.write("not valid json{{{")
        data = _load_log(path)
        self.assertEqual(data, [])

    def test_save_load_roundtrip(self):
        path = os.path.join(self.tmp, "rt.json")
        entries = [{"key": "val", "n": 42}]
        _save_log(path, entries)
        loaded = _load_log(path)
        self.assertEqual(loaded, entries)


class TestAnalysisWindowField(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "smart_money_flow_log.json")

    def test_default_analysis_window(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertEqual(r["analysis_window_hours"], 24.0)

    def test_custom_analysis_window(self):
        r = analyze("aave", [], config={"lookback_hours": 48.0}, log_path=self.log, persist=False)
        self.assertEqual(r["analysis_window_hours"], 48.0)


class TestRetailEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "smart_money_flow_log.json")

    def test_retail_not_counted_as_whale_by_type(self):
        ev = _event("deposit", 100_000, "retail", 3600)
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["whale_inflow_usd"], 0.0)

    def test_retail_over_threshold_counted_as_whale(self):
        # Amount >= threshold (500K) → treated as whale even if type=retail
        ev = _event("deposit", 600_000, "retail", 3600)
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["whale_inflow_usd"], 600_000)

    def test_retail_deposit_counted_in_gross_inflow(self):
        ev = _event("deposit", 100_000, "retail", 3600)
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["gross_inflow_usd"], 100_000)


class TestReturnSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "smart_money_flow_log.json")

    def test_all_top_level_keys_present(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        required_keys = {
            "protocol", "analysis_window_hours", "recent_24h",
            "flow_signal", "whale_signal", "smart_money_score",
            "risk_events", "interpretation", "timestamp",
        }
        self.assertTrue(required_keys.issubset(r.keys()))

    def test_recent_24h_all_keys_present(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        r24 = r["recent_24h"]
        required = {
            "gross_inflow_usd", "gross_outflow_usd", "net_flow_usd",
            "whale_inflow_usd", "whale_outflow_usd", "whale_net_flow_usd",
            "deposit_count", "withdrawal_count", "largest_single_event_usd",
        }
        self.assertTrue(required.issubset(r24.keys()))

    def test_flow_signal_valid_enum(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        valid = {"STRONG_INFLOW", "INFLOW", "NEUTRAL", "OUTFLOW", "STRONG_OUTFLOW"}
        self.assertIn(r["flow_signal"], valid)

    def test_whale_signal_valid_enum(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        valid = {"ACCUMULATING", "NEUTRAL", "DISTRIBUTING"}
        self.assertIn(r["whale_signal"], valid)

    def test_risk_events_is_list(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertIsInstance(r["risk_events"], list)

    def test_interpretation_is_string(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertIsInstance(r["interpretation"], str)

    def test_score_in_range(self):
        r = analyze("aave", [_whale_deposit(1_000_000, 3600)], log_path=self.log, persist=False)
        self.assertGreaterEqual(r["smart_money_score"], -100)
        self.assertLessEqual(r["smart_money_score"], 100)


class TestConfigDefaults(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "smart_money_flow_log.json")

    def test_custom_whale_threshold(self):
        # With low threshold (100K), a 150K retail becomes whale
        ev = _event("deposit", 150_000, "retail", 3600)
        r = analyze("aave", [ev], config={"whale_threshold_usd": 100_000}, log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["whale_inflow_usd"], 150_000)

    def test_high_threshold_retail_not_whale(self):
        ev = _event("deposit", 300_000, "retail", 3600)
        r = analyze("aave", [ev], config={"whale_threshold_usd": 1_000_000}, log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["whale_inflow_usd"], 0.0)

    def test_none_config_uses_defaults(self):
        r = analyze("aave", [], config=None, log_path=self.log, persist=False)
        self.assertEqual(r["analysis_window_hours"], 24.0)


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "smart_money_flow_log.json")

    def test_zero_amount_event(self):
        ev = _event("deposit", 0.0, "whale", 3600)
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["gross_inflow_usd"], 0.0)

    def test_unknown_action_ignored(self):
        ev = {"timestamp": _NOW - 100, "wallet_type": "whale", "action": "transfer", "amount_usd": 1_000_000}
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["deposit_count"], 0)
        self.assertEqual(r["recent_24h"]["withdrawal_count"], 0)

    def test_missing_amount_defaults_zero(self):
        ev = {"timestamp": _NOW - 100, "wallet_type": "whale", "action": "deposit"}
        r = analyze("aave", [ev], log_path=self.log, persist=False)
        self.assertEqual(r["recent_24h"]["gross_inflow_usd"], 0.0)

    def test_many_events_performance(self):
        events = [_whale_deposit(1_000_000, i * 10) for i in range(200)]
        r = analyze("aave", events, log_path=self.log, persist=False)
        self.assertIsInstance(r, dict)

    def test_empty_string_protocol(self):
        r = analyze("", [], log_path=self.log, persist=False)
        self.assertEqual(r["protocol"], "")

    def test_interpretation_non_empty(self):
        r = analyze("aave", [], log_path=self.log, persist=False)
        self.assertTrue(len(r["interpretation"]) > 0)


if __name__ == "__main__":
    unittest.main()
