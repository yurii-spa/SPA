"""
Tests for MP-1065 ProtocolDeFiFeeRevenueSustainabilityAnalyzer
≥90 unittest tests — pure stdlib, no third-party dependencies.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from spa_core.analytics.protocol_defi_protocol_fee_revenue_sustainability_analyzer import (
    ProtocolDeFiFeeRevenueSustainabilityAnalyzer,
    analyze,
    _atomic_log,
    _profit_margin_pct,
    _runway_months,
    _fee_competitiveness_score,
    _revenue_trend_pct,
    _sustainability_label,
    _LOG_CAP,
    _INFINITE_RUNWAY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


def _base_data(**overrides) -> dict:
    d = {
        "protocol_name":             "TestDeFi",
        "fee_revenue_30d_usd":       1_000_000.0,
        "operational_costs_30d_usd": 400_000.0,
        "token_buyback_30d_usd":     100_000.0,
        "treasury_usd":              10_000_000.0,
        "tvl_usd":                   200_000_000.0,
        "monthly_active_users":      50_000.0,
        "fee_revenue_history":       [700_000, 750_000, 800_000, 850_000, 900_000, 1_000_000],
        "competitor_fee_rate_bps":   30.0,
        "own_fee_rate_bps":          25.0,
    }
    d.update(overrides)
    return d


# ===========================================================================
# 1. _profit_margin_pct
# ===========================================================================

class TestProfitMarginPct(unittest.TestCase):

    def test_all_zeros_returns_zero(self):
        self.assertEqual(_profit_margin_pct(0.0, 0.0, 0.0), 0.0)

    def test_zero_revenue_with_costs_returns_minus_100(self):
        self.assertEqual(_profit_margin_pct(0.0, 100_000.0, 0.0), -100.0)

    def test_zero_revenue_with_buyback_returns_minus_100(self):
        self.assertEqual(_profit_margin_pct(0.0, 0.0, 50_000.0), -100.0)

    def test_zero_revenue_with_both_returns_minus_100(self):
        self.assertEqual(_profit_margin_pct(0.0, 100_000.0, 50_000.0), -100.0)

    def test_100_pct_margin_no_costs(self):
        result = _profit_margin_pct(1_000_000.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 100.0, places=4)

    def test_50_pct_margin(self):
        result = _profit_margin_pct(1_000_000.0, 500_000.0, 0.0)
        self.assertAlmostEqual(result, 50.0, places=4)

    def test_known_case(self):
        # rev=1M, costs=400k, buyback=100k → profit=500k → 50%
        result = _profit_margin_pct(1_000_000.0, 400_000.0, 100_000.0)
        self.assertAlmostEqual(result, 50.0, places=4)

    def test_negative_margin(self):
        # rev=500k, costs=700k → profit=-200k → -40%
        result = _profit_margin_pct(500_000.0, 700_000.0, 0.0)
        self.assertAlmostEqual(result, -40.0, places=4)

    def test_exactly_break_even(self):
        result = _profit_margin_pct(500_000.0, 500_000.0, 0.0)
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_result_rounded_to_4_places(self):
        result = _profit_margin_pct(1_000_000.0, 333_333.0, 0.0)
        # Should be rounded to 4 decimal places
        self.assertAlmostEqual(result, 66.6667, places=2)

    def test_buyback_reduces_margin(self):
        m1 = _profit_margin_pct(1_000_000.0, 400_000.0, 0.0)
        m2 = _profit_margin_pct(1_000_000.0, 400_000.0, 100_000.0)
        self.assertGreater(m1, m2)

    def test_returns_float(self):
        self.assertIsInstance(_profit_margin_pct(500_000.0, 200_000.0, 50_000.0), float)


# ===========================================================================
# 2. _runway_months
# ===========================================================================

class TestRunwayMonths(unittest.TestCase):

    def test_profitable_returns_infinite_sentinel(self):
        # costs < revenue → no burn → infinite runway
        result = _runway_months(10_000_000.0, 1_000_000.0, 500_000.0)
        self.assertEqual(result, _INFINITE_RUNWAY)

    def test_break_even_returns_infinite_sentinel(self):
        result = _runway_months(10_000_000.0, 1_000_000.0, 1_000_000.0)
        self.assertEqual(result, _INFINITE_RUNWAY)

    def test_zero_treasury_with_burn_returns_zero(self):
        result = _runway_months(0.0, 500_000.0, 1_000_000.0)
        self.assertEqual(result, 0.0)

    def test_negative_treasury_with_burn_returns_zero(self):
        result = _runway_months(-100.0, 500_000.0, 1_000_000.0)
        self.assertEqual(result, 0.0)

    def test_known_case(self):
        # burn = 1_000_000 - 500_000 = 500_000/month
        # treasury = 5_000_000 → 10 months
        result = _runway_months(5_000_000.0, 500_000.0, 1_000_000.0)
        self.assertAlmostEqual(result, 10.0, places=2)

    def test_large_treasury_many_months(self):
        result = _runway_months(120_000_000.0, 0.0, 1_000_000.0)
        self.assertAlmostEqual(result, 120.0, places=2)

    def test_result_rounded_to_2_places(self):
        result = _runway_months(1_000_000.0, 0.0, 300_000.0)
        # 1M / 300k = 3.333...  → rounds to 3.33
        self.assertAlmostEqual(result, 3.33, places=2)

    def test_returns_float(self):
        self.assertIsInstance(_runway_months(1_000_000.0, 0.0, 500_000.0), float)

    def test_tiny_burn(self):
        result = _runway_months(1_000.0, 0.0, 1.0)
        self.assertAlmostEqual(result, 1000.0, places=2)

    def test_zero_costs_zero_revenue_no_burn(self):
        result = _runway_months(0.0, 0.0, 0.0)
        self.assertEqual(result, _INFINITE_RUNWAY)


# ===========================================================================
# 3. _fee_competitiveness_score
# ===========================================================================

class TestFeeCompetitivenessScore(unittest.TestCase):

    def test_both_zero_neutral(self):
        self.assertAlmostEqual(_fee_competitiveness_score(0.0, 0.0), 50.0, places=2)

    def test_own_zero_competitor_positive_returns_100(self):
        self.assertAlmostEqual(_fee_competitiveness_score(0.0, 30.0), 100.0, places=2)

    def test_own_positive_competitor_zero_returns_0(self):
        self.assertAlmostEqual(_fee_competitiveness_score(30.0, 0.0), 0.0, places=2)

    def test_equal_fees_returns_50(self):
        self.assertAlmostEqual(_fee_competitiveness_score(30.0, 30.0), 50.0, places=2)

    def test_own_half_competitor(self):
        # ratio = 0.5 → (1-0.5)*50+50 = 75
        self.assertAlmostEqual(_fee_competitiveness_score(15.0, 30.0), 75.0, places=2)

    def test_own_double_competitor_returns_0(self):
        # ratio = 2.0 → (1-2)*50+50 = 0, clamped to 0
        self.assertAlmostEqual(_fee_competitiveness_score(60.0, 30.0), 0.0, places=2)

    def test_own_quarter_competitor(self):
        # ratio = 0.25 → (1-0.25)*50+50 = 87.5
        self.assertAlmostEqual(_fee_competitiveness_score(7.5, 30.0), 87.5, places=2)

    def test_own_triple_competitor_clamped_to_0(self):
        result = _fee_competitiveness_score(90.0, 30.0)
        self.assertAlmostEqual(result, 0.0, places=2)

    def test_result_clamped_above_100(self):
        result = _fee_competitiveness_score(0.0, 1_000_000.0)
        self.assertLessEqual(result, 100.0)

    def test_result_clamped_below_0(self):
        result = _fee_competitiveness_score(1_000_000.0, 1.0)
        self.assertGreaterEqual(result, 0.0)

    def test_returns_float(self):
        self.assertIsInstance(_fee_competitiveness_score(25.0, 30.0), float)

    def test_own_25_competitor_30(self):
        # ratio = 25/30 → (1 - 25/30)*50+50 = 58.333...
        expected = (1.0 - 25.0 / 30.0) * 50.0 + 50.0
        result = _fee_competitiveness_score(25.0, 30.0)
        self.assertAlmostEqual(result, expected, places=2)


# ===========================================================================
# 4. _revenue_trend_pct
# ===========================================================================

class TestRevenueTrendPct(unittest.TestCase):

    def test_empty_list_returns_zero(self):
        self.assertEqual(_revenue_trend_pct([]), 0.0)

    def test_single_entry_returns_zero(self):
        self.assertEqual(_revenue_trend_pct([1_000_000.0]), 0.0)

    def test_zero_previous_month_returns_zero(self):
        self.assertEqual(_revenue_trend_pct([0.0, 500_000.0]), 0.0)

    def test_no_change_returns_zero(self):
        result = _revenue_trend_pct([1_000_000.0, 1_000_000.0])
        self.assertAlmostEqual(result, 0.0, places=4)

    def test_positive_growth(self):
        # 800k → 1M = 25%
        result = _revenue_trend_pct([800_000.0, 1_000_000.0])
        self.assertAlmostEqual(result, 25.0, places=4)

    def test_negative_growth(self):
        # 1M → 750k = -25%
        result = _revenue_trend_pct([1_000_000.0, 750_000.0])
        self.assertAlmostEqual(result, -25.0, places=4)

    def test_uses_last_two_entries(self):
        # Long history: last two are 900k and 1M → 11.11%
        history = [500_000, 600_000, 700_000, 800_000, 900_000, 1_000_000]
        result = _revenue_trend_pct(history)
        self.assertAlmostEqual(result, 11.1111, places=2)

    def test_double_revenue(self):
        result = _revenue_trend_pct([500_000.0, 1_000_000.0])
        self.assertAlmostEqual(result, 100.0, places=4)

    def test_returns_float(self):
        self.assertIsInstance(_revenue_trend_pct([900_000.0, 1_000_000.0]), float)

    def test_result_rounded_to_4_places(self):
        # 2/3 * 100 = 66.6666...
        result = _revenue_trend_pct([300_000.0, 500_000.0])
        self.assertAlmostEqual(result, 66.6667, places=2)


# ===========================================================================
# 5. _sustainability_label
# ===========================================================================

class TestSustainabilityLabel(unittest.TestCase):

    def test_self_sustaining_both_thresholds_met(self):
        label = _sustainability_label(35.0, 24.0)
        self.assertEqual(label, "SELF_SUSTAINING")

    def test_self_sustaining_exactly_at_thresholds(self):
        label = _sustainability_label(30.0, 24.0)
        self.assertEqual(label, "SELF_SUSTAINING")

    def test_not_self_sustaining_low_runway(self):
        # margin fine but runway < 24
        label = _sustainability_label(35.0, 23.9)
        self.assertEqual(label, "HEALTHY")

    def test_not_self_sustaining_low_margin(self):
        # runway fine but margin < 30
        label = _sustainability_label(29.9, 30.0)
        self.assertEqual(label, "HEALTHY")

    def test_healthy_zero_margin(self):
        label = _sustainability_label(0.0, 0.0)
        self.assertEqual(label, "HEALTHY")

    def test_healthy_positive_margin_low_runway(self):
        label = _sustainability_label(5.0, 10.0)
        self.assertEqual(label, "HEALTHY")

    def test_break_even_at_minus_10(self):
        label = _sustainability_label(-10.0, 100.0)
        self.assertEqual(label, "BREAK_EVEN")

    def test_break_even_between_0_and_minus_10(self):
        label = _sustainability_label(-5.0, 100.0)
        self.assertEqual(label, "BREAK_EVEN")

    def test_treasury_dependent_low_margin_good_runway(self):
        label = _sustainability_label(-20.0, 12.0)
        self.assertEqual(label, "TREASURY_DEPENDENT")

    def test_insolvent_trajectory_low_margin_low_runway(self):
        label = _sustainability_label(-20.0, 5.0)
        self.assertEqual(label, "INSOLVENT_TRAJECTORY")

    def test_insolvent_trajectory_zero_runway(self):
        label = _sustainability_label(-50.0, 0.0)
        self.assertEqual(label, "INSOLVENT_TRAJECTORY")

    def test_all_five_labels_reachable(self):
        labels = {
            _sustainability_label(50.0, 30.0),
            _sustainability_label(10.0, 10.0),
            _sustainability_label(-5.0, 10.0),
            _sustainability_label(-20.0, 10.0),
            _sustainability_label(-20.0, 3.0),
        }
        self.assertEqual(len(labels), 5)


# ===========================================================================
# 6. _atomic_log
# ===========================================================================

class TestAtomicLog(unittest.TestCase):

    def test_creates_file_on_first_write(self):
        path = _tmp_log()
        _atomic_log(path, {"k": 1})
        self.assertTrue(os.path.exists(path))
        os.unlink(path)

    def test_initial_entry_is_list_of_one(self):
        path = _tmp_log()
        _atomic_log(path, {"v": 42})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["v"], 42)
        os.unlink(path)

    def test_appends_multiple_entries(self):
        path = _tmp_log()
        _atomic_log(path, {"n": 1})
        _atomic_log(path, {"n": 2})
        _atomic_log(path, {"n": 3})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)
        os.unlink(path)

    def test_ring_buffer_capped_at_log_cap(self):
        path = _tmp_log()
        for i in range(_LOG_CAP + 15):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), _LOG_CAP)
        os.unlink(path)

    def test_ring_buffer_retains_latest(self):
        path = _tmp_log()
        for i in range(_LOG_CAP + 5):
            _atomic_log(path, {"i": i})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["i"], _LOG_CAP + 4)
        self.assertEqual(data[0]["i"], 5)
        os.unlink(path)

    def test_corrupted_json_resets_to_empty(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.write(fd, b"CORRUPTED_DATA!!!")
        os.close(fd)
        _atomic_log(path, {"ok": True})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        os.unlink(path)

    def test_non_list_json_resets(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.write(fd, b'{"not": "a list"}')
        os.close(fd)
        _atomic_log(path, {"reset": True})
        with open(path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        os.unlink(path)

    def test_creates_parent_directories(self):
        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "nested", "dir", "log.json")
        _atomic_log(path, {"deep": True})
        self.assertTrue(os.path.exists(path))
        import shutil
        shutil.rmtree(tmp_dir)


# ===========================================================================
# 7. ProtocolDeFiFeeRevenueSustainabilityAnalyzer.analyze
# ===========================================================================

class TestAnalyzerAnalyze(unittest.TestCase):

    def setUp(self):
        self.log = _tmp_log()
        self.cfg = {"log_path": self.log, "write_log": False}

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def _run(self, **overrides):
        return ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(
            _base_data(**overrides), self.cfg
        )

    def test_returns_dict(self):
        self.assertIsInstance(self._run(), dict)

    def test_protocol_name_preserved(self):
        r = self._run(protocol_name="Uniswap")
        self.assertEqual(r["protocol_name"], "Uniswap")

    def test_profit_margin_in_result(self):
        r = self._run()
        self.assertIn("profit_margin_pct", r)

    def test_profit_margin_correct(self):
        # rev=1M, costs=400k, buyback=100k → 50%
        r = self._run(
            fee_revenue_30d_usd=1_000_000.0,
            operational_costs_30d_usd=400_000.0,
            token_buyback_30d_usd=100_000.0,
        )
        self.assertAlmostEqual(r["profit_margin_pct"], 50.0, places=2)

    def test_runway_in_result(self):
        r = self._run()
        self.assertIn("runway_months", r)

    def test_runway_infinite_when_profitable(self):
        r = self._run(
            fee_revenue_30d_usd=2_000_000.0,
            operational_costs_30d_usd=500_000.0,
        )
        self.assertEqual(r["runway_months"], _INFINITE_RUNWAY)

    def test_fee_competitiveness_score_in_result(self):
        r = self._run()
        self.assertIn("fee_competitiveness_score", r)

    def test_fee_competitiveness_score_range(self):
        r = self._run()
        self.assertGreaterEqual(r["fee_competitiveness_score"], 0.0)
        self.assertLessEqual(r["fee_competitiveness_score"], 100.0)

    def test_revenue_trend_in_result(self):
        r = self._run()
        self.assertIn("revenue_trend_pct", r)

    def test_revenue_trend_correct(self):
        history = [800_000.0, 1_000_000.0]
        r = self._run(fee_revenue_history=history)
        self.assertAlmostEqual(r["revenue_trend_pct"], 25.0, places=2)

    def test_sustainability_label_in_result(self):
        r = self._run()
        self.assertIn("sustainability_label", r)

    def test_sustainability_label_valid(self):
        valid = {"SELF_SUSTAINING", "HEALTHY", "BREAK_EVEN",
                 "TREASURY_DEPENDENT", "INSOLVENT_TRAJECTORY"}
        r = self._run()
        self.assertIn(r["sustainability_label"], valid)

    def test_timestamp_present(self):
        r = self._run()
        self.assertIn("timestamp", r)
        self.assertRegex(r["timestamp"], r"\d{4}-\d{2}-\d{2}T")

    def test_tvl_passed_through(self):
        r = self._run(tvl_usd=500_000_000.0)
        self.assertEqual(r["tvl_usd"], 500_000_000.0)

    def test_mau_passed_through(self):
        r = self._run(monthly_active_users=12_345.0)
        self.assertEqual(r["monthly_active_users"], 12_345.0)

    def test_write_log_true_creates_file(self):
        cfg = {"log_path": self.log, "write_log": True}
        ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(_base_data(), cfg)
        self.assertTrue(os.path.exists(self.log))

    def test_write_log_false_no_file(self):
        ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(_base_data(), self.cfg)
        self.assertFalse(os.path.exists(self.log))

    def test_missing_name_defaults_unknown(self):
        data = {k: v for k, v in _base_data().items() if k != "protocol_name"}
        r = ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(data, self.cfg)
        self.assertEqual(r["protocol_name"], "UNKNOWN")

    def test_self_sustaining_label(self):
        r = self._run(
            fee_revenue_30d_usd=2_000_000.0,
            operational_costs_30d_usd=1_000_000.0,  # 50% margin → self-sustaining
            token_buyback_30d_usd=0.0,
            treasury_usd=100_000_000.0,
        )
        self.assertEqual(r["sustainability_label"], "SELF_SUSTAINING")

    def test_insolvent_trajectory_label(self):
        r = self._run(
            fee_revenue_30d_usd=100_000.0,
            operational_costs_30d_usd=500_000.0,
            token_buyback_30d_usd=0.0,
            treasury_usd=500_000.0,  # 1 month runway
        )
        self.assertEqual(r["sustainability_label"], "INSOLVENT_TRAJECTORY")

    def test_all_expected_keys_present(self):
        expected = {
            "protocol_name", "profit_margin_pct", "runway_months",
            "fee_competitiveness_score", "revenue_trend_pct",
            "sustainability_label", "tvl_usd", "monthly_active_users", "timestamp",
        }
        r = self._run()
        self.assertTrue(expected.issubset(set(r.keys())))

    def test_string_numeric_coercion(self):
        data = _base_data()
        data["fee_revenue_30d_usd"] = "1000000"
        data["operational_costs_30d_usd"] = "400000"
        r = ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(data, self.cfg)
        self.assertIsInstance(r["profit_margin_pct"], float)

    def test_empty_history_trend_zero(self):
        r = self._run(fee_revenue_history=[])
        self.assertEqual(r["revenue_trend_pct"], 0.0)

    def test_no_config_uses_defaults(self):
        r = ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(
            _base_data(), {"write_log": False}
        )
        self.assertIn("sustainability_label", r)

    def test_break_even_label(self):
        r = self._run(
            fee_revenue_30d_usd=1_000_000.0,
            operational_costs_30d_usd=1_050_000.0,
            token_buyback_30d_usd=0.0,
            treasury_usd=50_000_000.0,
        )
        self.assertEqual(r["sustainability_label"], "BREAK_EVEN")

    def test_treasury_dependent_label(self):
        r = self._run(
            fee_revenue_30d_usd=200_000.0,
            operational_costs_30d_usd=800_000.0,  # burn = 600k/month
            token_buyback_30d_usd=0.0,
            treasury_usd=6_000_001.0,   # > 10 months runway
        )
        self.assertEqual(r["sustainability_label"], "TREASURY_DEPENDENT")


# ===========================================================================
# 8. Module-level analyze()
# ===========================================================================

class TestModuleLevelAnalyze(unittest.TestCase):

    def setUp(self):
        self.log = _tmp_log()

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def test_returns_dict(self):
        cfg = {"log_path": self.log, "write_log": False}
        self.assertIsInstance(analyze(_base_data(), cfg), dict)

    def test_same_result_as_class(self):
        cfg = {"log_path": self.log, "write_log": False}
        r1 = analyze(_base_data(), cfg)
        r2 = ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(_base_data(), cfg)
        for k in ("profit_margin_pct", "sustainability_label", "revenue_trend_pct"):
            self.assertEqual(r1[k], r2[k])

    def test_protocol_name_forwarded(self):
        cfg = {"log_path": self.log, "write_log": False}
        r = analyze(_base_data(protocol_name="Curve"), cfg)
        self.assertEqual(r["protocol_name"], "Curve")

    def test_no_exception_with_minimal_data(self):
        cfg = {"write_log": False}
        r = analyze({"protocol_name": "Minimal"}, cfg)
        self.assertIn("sustainability_label", r)


# ===========================================================================
# 9. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.log = _tmp_log()
        self.cfg = {"log_path": self.log, "write_log": False}

    def tearDown(self):
        if os.path.exists(self.log):
            os.unlink(self.log)

    def _run(self, **overrides):
        return ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(
            _base_data(**overrides), self.cfg
        )

    def test_all_zeros(self):
        data = {k: 0 for k in _base_data()}
        data["protocol_name"] = "ZeroProto"
        data["fee_revenue_history"] = []
        r = ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(data, self.cfg)
        self.assertIn("sustainability_label", r)

    def test_very_large_revenue(self):
        r = self._run(fee_revenue_30d_usd=1e15)
        self.assertIn("profit_margin_pct", r)

    def test_single_entry_history(self):
        r = self._run(fee_revenue_history=[1_000_000.0])
        self.assertEqual(r["revenue_trend_pct"], 0.0)

    def test_declining_revenue_trend(self):
        r = self._run(fee_revenue_history=[1_000_000.0, 600_000.0])
        self.assertAlmostEqual(r["revenue_trend_pct"], -40.0, places=2)

    def test_result_no_write_side_effects(self):
        r = self._run()
        self.assertNotIn("trades", r)
        self.assertNotIn("positions", r)

    def test_zero_competitor_bps_own_positive(self):
        r = self._run(competitor_fee_rate_bps=0.0, own_fee_rate_bps=30.0)
        self.assertAlmostEqual(r["fee_competitiveness_score"], 0.0, places=2)

    def test_zero_own_bps_competitor_positive(self):
        r = self._run(own_fee_rate_bps=0.0, competitor_fee_rate_bps=30.0)
        self.assertAlmostEqual(r["fee_competitiveness_score"], 100.0, places=2)

    def test_no_treasury_no_revenue_insolvent(self):
        r = self._run(
            fee_revenue_30d_usd=0.0,
            operational_costs_30d_usd=500_000.0,
            treasury_usd=0.0,
        )
        self.assertEqual(r["sustainability_label"], "INSOLVENT_TRAJECTORY")


# ===========================================================================
# 10. Log integration and ring-buffer
# ===========================================================================

class TestLogIntegration(unittest.TestCase):

    def test_101_calls_stays_at_100(self):
        path = _tmp_log()
        cfg = {"log_path": path, "write_log": True}
        an = ProtocolDeFiFeeRevenueSustainabilityAnalyzer()
        for i in range(101):
            d = _base_data(protocol_name=f"P{i}")
            an.analyze(d, cfg)
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)
        os.unlink(path)

    def test_log_entry_contains_required_keys(self):
        path = _tmp_log()
        cfg = {"log_path": path, "write_log": True}
        ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(_base_data(), cfg)
        with open(path) as f:
            entry = json.load(f)[0]
        for field in ("timestamp", "protocol_name", "profit_margin_pct",
                      "runway_months", "fee_competitiveness_score",
                      "revenue_trend_pct", "sustainability_label"):
            self.assertIn(field, entry)
        os.unlink(path)

    def test_log_entry_protocol_name_correct(self):
        path = _tmp_log()
        cfg = {"log_path": path, "write_log": True}
        ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(
            _base_data(protocol_name="Aave"), cfg
        )
        with open(path) as f:
            entry = json.load(f)[0]
        self.assertEqual(entry["protocol_name"], "Aave")
        os.unlink(path)

    def test_result_profit_margin_is_float(self):
        path = _tmp_log()
        r = ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(
            _base_data(), {"log_path": path, "write_log": False}
        )
        self.assertIsInstance(r["profit_margin_pct"], float)

    def test_result_runway_is_float(self):
        path = _tmp_log()
        r = ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(
            _base_data(), {"log_path": path, "write_log": False}
        )
        self.assertIsInstance(r["runway_months"], float)

    def test_result_label_is_string(self):
        path = _tmp_log()
        r = ProtocolDeFiFeeRevenueSustainabilityAnalyzer().analyze(
            _base_data(), {"log_path": path, "write_log": False}
        )
        self.assertIsInstance(r["sustainability_label"], str)


if __name__ == "__main__":
    unittest.main()
