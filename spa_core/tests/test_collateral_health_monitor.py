"""
Tests for MP-797: CollateralHealthMonitor
≥65 unittest tests. Pure stdlib (unittest only).
Run: python3 -m unittest spa_core/tests/test_collateral_health_monitor.py
"""
import json
import os
import sys
import tempfile
import time
import unittest

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.collateral_health_monitor import (
    analyze,
    append_log,
    _analyze_position,
    _resolve_config,
    _atomic_write,
    DEFAULT_DANGER_BUFFER_PCT,
    DEFAULT_WARNING_BUFFER_PCT,
    LOG_MAX,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pos(
    protocol="TestProto",
    collateral=100_000.0,
    debt=60_000.0,
    liq_threshold=0.80,
    token="ETH",
    price_change=0.0,
):
    return {
        "protocol": protocol,
        "collateral_usd": collateral,
        "debt_usd": debt,
        "liquidation_threshold": liq_threshold,
        "collateral_token": token,
        "collateral_price_change_24h": price_change,
    }


# ---------------------------------------------------------------------------
# 1. Config resolution
# ---------------------------------------------------------------------------

class TestResolveConfig(unittest.TestCase):

    def test_defaults_when_none(self):
        cfg = _resolve_config(None)
        self.assertEqual(cfg["warning_buffer_pct"], DEFAULT_WARNING_BUFFER_PCT)
        self.assertEqual(cfg["danger_buffer_pct"], DEFAULT_DANGER_BUFFER_PCT)

    def test_defaults_when_empty(self):
        cfg = _resolve_config({})
        self.assertEqual(cfg["warning_buffer_pct"], DEFAULT_WARNING_BUFFER_PCT)
        self.assertEqual(cfg["danger_buffer_pct"], DEFAULT_DANGER_BUFFER_PCT)

    def test_custom_warning(self):
        cfg = _resolve_config({"warning_buffer_pct": 15.0})
        self.assertEqual(cfg["warning_buffer_pct"], 15.0)

    def test_custom_danger(self):
        cfg = _resolve_config({"danger_buffer_pct": 2.5})
        self.assertEqual(cfg["danger_buffer_pct"], 2.5)

    def test_both_custom(self):
        cfg = _resolve_config({"warning_buffer_pct": 20.0, "danger_buffer_pct": 7.0})
        self.assertEqual(cfg["warning_buffer_pct"], 20.0)
        self.assertEqual(cfg["danger_buffer_pct"], 7.0)

    def test_string_values_converted(self):
        cfg = _resolve_config({"warning_buffer_pct": "12", "danger_buffer_pct": "3"})
        self.assertIsInstance(cfg["warning_buffer_pct"], float)
        self.assertIsInstance(cfg["danger_buffer_pct"], float)


# ---------------------------------------------------------------------------
# 2. Per-position analysis – edge cases
# ---------------------------------------------------------------------------

class TestAnalyzePositionEdgeCases(unittest.TestCase):

    def test_zero_collateral_is_liquidating(self):
        result = _analyze_position(_pos(collateral=0.0, debt=1000.0), 10.0, 5.0)
        self.assertEqual(result["status"], "LIQUIDATING")

    def test_zero_collateral_buffer_zero(self):
        result = _analyze_position(_pos(collateral=0.0, debt=1000.0), 10.0, 5.0)
        self.assertEqual(result["buffer_pct"], 0.0)

    def test_zero_collateral_max_borrow_zero(self):
        result = _analyze_position(_pos(collateral=0.0, debt=1000.0), 10.0, 5.0)
        self.assertEqual(result["max_additional_debt_usd"], 0.0)

    def test_zero_collateral_price_drop_zero(self):
        result = _analyze_position(_pos(collateral=0.0, debt=1000.0), 10.0, 5.0)
        self.assertEqual(result["price_drop_to_liquidation_pct"], 0.0)

    def test_zero_debt_is_safe(self):
        result = _analyze_position(_pos(debt=0.0), 10.0, 5.0)
        self.assertEqual(result["status"], "SAFE")

    def test_zero_debt_buffer_100(self):
        result = _analyze_position(_pos(debt=0.0), 10.0, 5.0)
        self.assertAlmostEqual(result["buffer_pct"], 100.0, places=4)

    def test_zero_debt_price_drop_100(self):
        result = _analyze_position(_pos(debt=0.0), 10.0, 5.0)
        self.assertAlmostEqual(result["price_drop_to_liquidation_pct"], 100.0, places=4)

    def test_zero_debt_max_borrow_correct(self):
        result = _analyze_position(_pos(collateral=100_000.0, debt=0.0, liq_threshold=0.8), 10.0, 5.0)
        self.assertAlmostEqual(result["max_additional_debt_usd"], 80_000.0, places=2)

    def test_protocol_name_preserved(self):
        result = _analyze_position(_pos(protocol="Aave V3"), 10.0, 5.0)
        self.assertEqual(result["protocol"], "Aave V3")

    def test_collateral_token_preserved(self):
        result = _analyze_position(_pos(token="WBTC"), 10.0, 5.0)
        self.assertEqual(result["collateral_token"], "WBTC")

    def test_price_change_preserved(self):
        result = _analyze_position(_pos(price_change=-3.5), 10.0, 5.0)
        self.assertAlmostEqual(result["price_change_24h"], -3.5)


# ---------------------------------------------------------------------------
# 3. LTV and buffer calculations
# ---------------------------------------------------------------------------

class TestLTVAndBuffer(unittest.TestCase):

    def test_ltv_calculation(self):
        # debt 60k / collateral 100k = 0.60
        result = _analyze_position(_pos(collateral=100_000.0, debt=60_000.0), 10.0, 5.0)
        self.assertAlmostEqual(result["current_ltv"], 0.60, places=5)

    def test_liquidation_ltv_matches_threshold(self):
        result = _analyze_position(_pos(liq_threshold=0.75), 10.0, 5.0)
        self.assertEqual(result["liquidation_ltv"], 0.75)

    def test_buffer_pct_formula(self):
        # LTV = 0.60, threshold = 0.80 → buffer = (0.80 - 0.60)/0.80 * 100 = 25%
        result = _analyze_position(_pos(collateral=100_000.0, debt=60_000.0, liq_threshold=0.80), 10.0, 5.0)
        self.assertAlmostEqual(result["buffer_pct"], 25.0, places=3)

    def test_price_drop_formula(self):
        # debt=60k, collateral=100k, threshold=0.80
        # ratio = 60000/(100000*0.80) = 0.75 → drop = 25%
        result = _analyze_position(_pos(collateral=100_000.0, debt=60_000.0, liq_threshold=0.80), 10.0, 5.0)
        self.assertAlmostEqual(result["price_drop_to_liquidation_pct"], 25.0, places=3)

    def test_max_borrow_formula(self):
        # collateral=100k, threshold=0.80, debt=60k → max_borrow = 100k*0.80 - 60k = 20k
        result = _analyze_position(_pos(collateral=100_000.0, debt=60_000.0, liq_threshold=0.80), 10.0, 5.0)
        self.assertAlmostEqual(result["max_additional_debt_usd"], 20_000.0, places=2)

    def test_max_borrow_zero_when_over_threshold(self):
        result = _analyze_position(_pos(collateral=100_000.0, debt=85_000.0, liq_threshold=0.80), 10.0, 5.0)
        self.assertEqual(result["max_additional_debt_usd"], 0.0)

    def test_price_drop_zero_when_at_liquidation(self):
        # debt=80k, collateral=100k, threshold=0.80 → exactly at liquidation
        result = _analyze_position(_pos(collateral=100_000.0, debt=80_000.0, liq_threshold=0.80), 10.0, 5.0)
        self.assertAlmostEqual(result["price_drop_to_liquidation_pct"], 0.0, places=3)


# ---------------------------------------------------------------------------
# 4. Status thresholds
# ---------------------------------------------------------------------------

class TestStatusThresholds(unittest.TestCase):

    def _make_pos(self, current_ltv: float, threshold: float = 0.80) -> dict:
        """Create a position with a specific LTV."""
        debt = current_ltv * 100_000.0
        return _pos(collateral=100_000.0, debt=debt, liq_threshold=threshold)

    def test_safe_status(self):
        # buffer ~25% → SAFE
        result = _analyze_position(self._make_pos(0.60), 10.0, 5.0)
        self.assertEqual(result["status"], "SAFE")

    def test_warning_status_just_below_warning(self):
        # buffer = (0.80 - 0.73)/0.80 * 100 = 8.75% < 10% → WARNING
        result = _analyze_position(self._make_pos(0.73), 10.0, 5.0)
        self.assertEqual(result["status"], "WARNING")

    def test_danger_status(self):
        # buffer = (0.80 - 0.776)/0.80 * 100 = 3% < 5% → DANGER
        result = _analyze_position(self._make_pos(0.776), 10.0, 5.0)
        self.assertEqual(result["status"], "DANGER")

    def test_liquidating_at_threshold(self):
        result = _analyze_position(self._make_pos(0.80), 10.0, 5.0)
        self.assertEqual(result["status"], "LIQUIDATING")

    def test_liquidating_above_threshold(self):
        result = _analyze_position(self._make_pos(0.90), 10.0, 5.0)
        self.assertEqual(result["status"], "LIQUIDATING")

    def test_custom_thresholds_warning(self):
        # With warn=20, danger=10: buffer 8.75% → DANGER
        result = _analyze_position(self._make_pos(0.73), 20.0, 10.0)
        self.assertEqual(result["status"], "DANGER")

    def test_custom_thresholds_safe(self):
        # With warn=5, danger=2: buffer 25% → SAFE
        result = _analyze_position(self._make_pos(0.60), 5.0, 2.0)
        self.assertEqual(result["status"], "SAFE")


# ---------------------------------------------------------------------------
# 5. analyze() – full portfolio
# ---------------------------------------------------------------------------

class TestAnalyzeFull(unittest.TestCase):

    def setUp(self):
        self.safe_pos = _pos("SafeProto", collateral=100_000, debt=50_000, liq_threshold=0.80)
        self.warn_pos = _pos("WarnProto", collateral=100_000, debt=73_000, liq_threshold=0.80)
        self.danger_pos = _pos("DangerProto", collateral=100_000, debt=77_600, liq_threshold=0.80)
        self.liq_pos = _pos("LiqProto", collateral=100_000, debt=85_000, liq_threshold=0.80)

    def test_returns_dict_with_required_keys(self):
        result = analyze([self.safe_pos])
        self.assertIn("positions", result)
        self.assertIn("portfolio_summary", result)
        self.assertIn("alerts", result)
        self.assertIn("timestamp", result)

    def test_position_count_matches_input(self):
        result = analyze([self.safe_pos, self.warn_pos])
        self.assertEqual(len(result["positions"]), 2)

    def test_empty_positions(self):
        result = analyze([])
        self.assertEqual(result["positions"], [])
        self.assertEqual(result["portfolio_summary"]["at_risk_count"], 0)
        self.assertEqual(result["alerts"], [])

    def test_none_positions(self):
        result = analyze(None)
        self.assertEqual(result["positions"], [])

    def test_total_collateral_sum(self):
        result = analyze([self.safe_pos, self.warn_pos])
        self.assertAlmostEqual(
            result["portfolio_summary"]["total_collateral_usd"], 200_000.0, places=1
        )

    def test_total_debt_sum(self):
        result = analyze([self.safe_pos, self.warn_pos])
        self.assertAlmostEqual(
            result["portfolio_summary"]["total_debt_usd"], 123_000.0, places=1
        )

    def test_portfolio_ltv(self):
        result = analyze([self.safe_pos, self.warn_pos])
        expected = 123_000 / 200_000
        self.assertAlmostEqual(result["portfolio_summary"]["portfolio_ltv"], expected, places=5)

    def test_at_risk_count_zero(self):
        result = analyze([self.safe_pos])
        self.assertEqual(result["portfolio_summary"]["at_risk_count"], 0)

    def test_at_risk_count_includes_warning(self):
        result = analyze([self.safe_pos, self.warn_pos])
        self.assertEqual(result["portfolio_summary"]["at_risk_count"], 1)

    def test_at_risk_count_includes_danger(self):
        result = analyze([self.safe_pos, self.warn_pos, self.danger_pos])
        self.assertEqual(result["portfolio_summary"]["at_risk_count"], 2)

    def test_at_risk_count_includes_liquidating(self):
        result = analyze([self.safe_pos, self.liq_pos])
        self.assertEqual(result["portfolio_summary"]["at_risk_count"], 1)

    def test_healthiest_protocol_identified(self):
        result = analyze([self.safe_pos, self.warn_pos, self.danger_pos])
        self.assertEqual(result["portfolio_summary"]["healthiest_protocol"], "SafeProto")

    def test_riskiest_protocol_identified(self):
        result = analyze([self.safe_pos, self.warn_pos, self.danger_pos])
        self.assertEqual(result["portfolio_summary"]["riskiest_protocol"], "DangerProto")

    def test_no_alerts_when_all_safe(self):
        result = analyze([self.safe_pos])
        self.assertEqual(result["alerts"], [])

    def test_warning_alert_generated(self):
        result = analyze([self.warn_pos])
        self.assertTrue(any("WARNING" in a for a in result["alerts"]))

    def test_danger_alert_generated(self):
        result = analyze([self.danger_pos])
        self.assertTrue(any("DANGER" in a for a in result["alerts"]))

    def test_liquidating_alert_generated(self):
        result = analyze([self.liq_pos])
        self.assertTrue(any("LIQUIDATING" in a for a in result["alerts"]))

    def test_liquidating_alert_contains_critical(self):
        result = analyze([self.liq_pos])
        self.assertTrue(any("CRITICAL" in a for a in result["alerts"]))

    def test_alert_count_matches_at_risk(self):
        result = analyze([self.safe_pos, self.warn_pos, self.danger_pos, self.liq_pos])
        self.assertEqual(len(result["alerts"]), 3)

    def test_timestamp_is_recent(self):
        before = time.time()
        result = analyze([self.safe_pos])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_custom_config_applied(self):
        # With very tight thresholds: buffer 37.5% → still SAFE
        result = analyze([self.safe_pos], config={"warning_buffer_pct": 1.0, "danger_buffer_pct": 0.5})
        self.assertEqual(result["positions"][0]["status"], "SAFE")

    def test_single_position_healthiest_and_riskiest_same(self):
        result = analyze([self.safe_pos])
        self.assertEqual(
            result["portfolio_summary"]["healthiest_protocol"],
            result["portfolio_summary"]["riskiest_protocol"],
        )

    def test_zero_collateral_position_in_portfolio(self):
        zero_coll = _pos("ZeroCol", collateral=0.0, debt=1000.0)
        result = analyze([zero_coll])
        self.assertEqual(result["positions"][0]["status"], "LIQUIDATING")

    def test_zero_debt_position_in_portfolio(self):
        zero_debt = _pos("ZeroDebt", debt=0.0)
        result = analyze([zero_debt])
        self.assertEqual(result["positions"][0]["status"], "SAFE")

    def test_position_result_has_all_keys(self):
        result = analyze([self.safe_pos])
        pos = result["positions"][0]
        for key in (
            "protocol", "current_ltv", "liquidation_ltv", "buffer_pct",
            "status", "max_additional_debt_usd", "price_drop_to_liquidation_pct",
        ):
            self.assertIn(key, pos)

    def test_portfolio_summary_has_all_keys(self):
        result = analyze([self.safe_pos])
        ps = result["portfolio_summary"]
        for key in (
            "total_collateral_usd", "total_debt_usd", "portfolio_ltv",
            "at_risk_count", "healthiest_protocol", "riskiest_protocol",
        ):
            self.assertIn(key, ps)

    def test_empty_portfolio_zero_ltv(self):
        result = analyze([])
        self.assertEqual(result["portfolio_summary"]["portfolio_ltv"], 0.0)

    def test_empty_portfolio_empty_healthiest_riskiest(self):
        result = analyze([])
        self.assertEqual(result["portfolio_summary"]["healthiest_protocol"], "")
        self.assertEqual(result["portfolio_summary"]["riskiest_protocol"], "")


# ---------------------------------------------------------------------------
# 6. Alert message content
# ---------------------------------------------------------------------------

class TestAlertMessages(unittest.TestCase):

    def test_warning_alert_contains_protocol_name(self):
        pos = _pos("MyProto", collateral=100_000, debt=73_000, liq_threshold=0.80)
        result = analyze([pos])
        self.assertTrue(any("MyProto" in a for a in result["alerts"]))

    def test_danger_alert_mentions_price_drop(self):
        pos = _pos("DProto", collateral=100_000, debt=77_600, liq_threshold=0.80)
        result = analyze([pos])
        danger_alerts = [a for a in result["alerts"] if "DANGER" in a]
        self.assertTrue(any("triggers liquidation" in a for a in danger_alerts))

    def test_warning_alert_mentions_max_borrow(self):
        pos = _pos("WProto", collateral=100_000, debt=73_000, liq_threshold=0.80)
        result = analyze([pos])
        warn_alerts = [a for a in result["alerts"] if "WARNING" in a]
        self.assertTrue(any("Max additional borrow" in a for a in warn_alerts))

    def test_liquidating_alert_mentions_threshold(self):
        pos = _pos("LProto", collateral=100_000, debt=85_000, liq_threshold=0.80)
        result = analyze([pos])
        liq_alerts = [a for a in result["alerts"] if "LIQUIDATING" in a]
        self.assertTrue(len(liq_alerts) > 0)


# ---------------------------------------------------------------------------
# 7. Ring-buffer log
# ---------------------------------------------------------------------------

class TestAppendLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.log_path = self.tmp.name
        self.tmp.close()
        os.unlink(self.log_path)

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)

    def test_creates_file_on_first_write(self):
        result = analyze([_pos()])
        append_log(result, self.log_path)
        self.assertTrue(os.path.exists(self.log_path))

    def test_file_contains_valid_json(self):
        result = analyze([_pos()])
        append_log(result, self.log_path)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_first_entry_appended(self):
        result = analyze([_pos()])
        append_log(result, self.log_path)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_multiple_appends(self):
        for _ in range(5):
            append_log(analyze([_pos()]), self.log_path)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        for _ in range(LOG_MAX + 10):
            append_log(analyze([_pos()]), self.log_path)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), LOG_MAX)

    def test_ring_buffer_keeps_latest(self):
        for i in range(LOG_MAX + 5):
            r = analyze([_pos()])
            r["_seq"] = i
            append_log(r, self.log_path)
        with open(self.log_path) as fh:
            data = json.load(fh)
        seqs = [e["_seq"] for e in data]
        self.assertEqual(seqs[-1], LOG_MAX + 4)

    def test_corrupted_log_reset(self):
        with open(self.log_path, "w") as fh:
            fh.write("not-json")
        result = analyze([_pos()])
        append_log(result, self.log_path)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_wrong_type_log_reset(self):
        with open(self.log_path, "w") as fh:
            json.dump({"not": "a list"}, fh)
        result = analyze([_pos()])
        append_log(result, self.log_path)
        with open(self.log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)


# ---------------------------------------------------------------------------
# 8. Atomic write
# ---------------------------------------------------------------------------

class TestAtomicWrite(unittest.TestCase):

    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {"hello": "world"})
            self.assertTrue(os.path.exists(path))

    def test_atomic_write_valid_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, [1, 2, 3])
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(data, [1, 2, 3])

    def test_atomic_write_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "dir", "test.json")
            _atomic_write(path, {"x": 1})
            self.assertTrue(os.path.exists(path))

    def test_atomic_write_no_tmp_left(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.json")
            _atomic_write(path, {})
            files = os.listdir(d)
            tmp_files = [f for f in files if f.endswith(".tmp")]
            self.assertEqual(tmp_files, [])


# ---------------------------------------------------------------------------
# 9. Numeric correctness
# ---------------------------------------------------------------------------

class TestNumericCorrectness(unittest.TestCase):

    def test_ltv_50_pct(self):
        result = _analyze_position(_pos(collateral=200_000, debt=100_000, liq_threshold=0.80), 10.0, 5.0)
        self.assertAlmostEqual(result["current_ltv"], 0.5, places=5)

    def test_buffer_at_50_pct_ltv(self):
        # buffer = (0.80-0.50)/0.80*100 = 37.5%
        result = _analyze_position(_pos(collateral=200_000, debt=100_000, liq_threshold=0.80), 10.0, 5.0)
        self.assertAlmostEqual(result["buffer_pct"], 37.5, places=3)

    def test_price_drop_at_50_pct_ltv(self):
        # ratio = 100000/(200000*0.80) = 0.625 → drop = 37.5%
        result = _analyze_position(_pos(collateral=200_000, debt=100_000, liq_threshold=0.80), 10.0, 5.0)
        self.assertAlmostEqual(result["price_drop_to_liquidation_pct"], 37.5, places=3)

    def test_very_high_ltv_small_buffer(self):
        # LTV=0.78, threshold=0.80 → buffer=(0.80-0.78)/0.80*100=2.5% → DANGER
        result = _analyze_position(_pos(collateral=100_000, debt=78_000, liq_threshold=0.80), 10.0, 5.0)
        self.assertEqual(result["status"], "DANGER")
        self.assertAlmostEqual(result["buffer_pct"], 2.5, places=3)

    def test_price_drop_positive_when_healthy(self):
        result = _analyze_position(_pos(collateral=100_000, debt=50_000, liq_threshold=0.80), 10.0, 5.0)
        self.assertGreater(result["price_drop_to_liquidation_pct"], 0.0)

    def test_portfolio_ltv_correct(self):
        pos1 = _pos(collateral=100_000, debt=50_000)
        pos2 = _pos(collateral=100_000, debt=70_000)
        result = analyze([pos1, pos2])
        self.assertAlmostEqual(result["portfolio_summary"]["portfolio_ltv"], 0.60, places=5)


if __name__ == "__main__":
    unittest.main()
