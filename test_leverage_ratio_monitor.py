"""
Tests for MP-793 LeverageRatioMonitor.
Run: python3 -m pytest spa_core/tests/test_leverage_ratio_monitor.py -v
"""

import json
import math
import os
import tempfile
import time
import unittest

from spa_core.analytics.leverage_ratio_monitor import (
    LeverageRatioMonitor,
    MARGIN_STATUS_SAFE,
    MARGIN_STATUS_WARNING,
    MARGIN_STATUS_DANGER,
    MARGIN_STATUS_LIQUIDATING,
    _classify_margin_status,
    _compute_position_metrics,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_position(
    protocol="TestPool",
    position_value_usd=10_000.0,
    collateral_usd=5_000.0,
    debt_usd=3_000.0,
    maintenance_margin_pct=5.0,
):
    return {
        "protocol": protocol,
        "position_value_usd": position_value_usd,
        "collateral_usd": collateral_usd,
        "debt_usd": debt_usd,
        "maintenance_margin_pct": maintenance_margin_pct,
    }


def _safe_position():
    """margin_ratio=(5000-1000)/10000*100=40, safety=40-5=35 → SAFE."""
    return _make_position(
        position_value_usd=10_000,
        collateral_usd=5_000,
        debt_usd=1_000,
        maintenance_margin_pct=5.0,
    )


def _warning_position():
    """margin_ratio=(1000-900)/10000*100=1, maintenance=None... let me calc:
    position=10000, collateral=1000, debt=900  → margin_ratio=(1000-900)/10000*100=1
    maintenance=0 → safety=1.0 - 0 = 1  but we want warning (5<safety<=10)
    Use: collateral=2000, debt=1200, pos=10000 → margin_ratio=800/10000*100=8 → safety=8-0=8 → WARNING
    """
    return _make_position(
        position_value_usd=10_000,
        collateral_usd=2_000,
        debt_usd=1_200,
        maintenance_margin_pct=0.0,
    )


def _danger_position():
    """safety just above 0, below 5 → DANGER.
    pos=10000, coll=600, debt=400, maint=0
    margin_ratio=(600-400)/10000*100=2, safety=2-0=2 → DANGER
    """
    return _make_position(
        position_value_usd=10_000,
        collateral_usd=600,
        debt_usd=400,
        maintenance_margin_pct=0.0,
    )


def _liquidating_position():
    """safety<=0 → LIQUIDATING.
    pos=10000, coll=500, debt=600, maint=0
    margin_ratio=(500-600)/10000*100=-1, safety=-1 → LIQUIDATING
    """
    return _make_position(
        position_value_usd=10_000,
        collateral_usd=500,
        debt_usd=600,
        maintenance_margin_pct=0.0,
    )


# ---------------------------------------------------------------------------
# Group 1: Initialization
# ---------------------------------------------------------------------------

class TestInit(unittest.TestCase):

    def test_default_log_path(self):
        m = LeverageRatioMonitor()
        self.assertEqual(m.log_path, "data/leverage_ratio_log.json")

    def test_default_max_entries(self):
        m = LeverageRatioMonitor()
        self.assertEqual(m.max_entries, 100)

    def test_custom_log_path(self):
        m = LeverageRatioMonitor(log_path="/tmp/test_lev.json")
        self.assertEqual(m.log_path, "/tmp/test_lev.json")

    def test_custom_max_entries(self):
        m = LeverageRatioMonitor(max_entries=50)
        self.assertEqual(m.max_entries, 50)

    def test_last_result_initially_none(self):
        m = LeverageRatioMonitor()
        self.assertIsNone(m._last_result)


# ---------------------------------------------------------------------------
# Group 2: _classify_margin_status
# ---------------------------------------------------------------------------

class TestClassifyMarginStatus(unittest.TestCase):

    def test_safe_well_above_10(self):
        self.assertEqual(_classify_margin_status(50.0), MARGIN_STATUS_SAFE)

    def test_safe_just_above_10(self):
        self.assertEqual(_classify_margin_status(10.001), MARGIN_STATUS_SAFE)

    def test_warning_exactly_10(self):
        # 10.0 is NOT > 10.0, so falls to WARNING
        self.assertEqual(_classify_margin_status(10.0), MARGIN_STATUS_WARNING)

    def test_warning_between_5_and_10(self):
        self.assertEqual(_classify_margin_status(7.5), MARGIN_STATUS_WARNING)

    def test_warning_just_above_5(self):
        self.assertEqual(_classify_margin_status(5.001), MARGIN_STATUS_WARNING)

    def test_danger_exactly_5(self):
        self.assertEqual(_classify_margin_status(5.0), MARGIN_STATUS_DANGER)

    def test_danger_between_0_and_5(self):
        self.assertEqual(_classify_margin_status(2.5), MARGIN_STATUS_DANGER)

    def test_danger_just_above_0(self):
        self.assertEqual(_classify_margin_status(0.001), MARGIN_STATUS_DANGER)

    def test_liquidating_exactly_0(self):
        self.assertEqual(_classify_margin_status(0.0), MARGIN_STATUS_LIQUIDATING)

    def test_liquidating_negative(self):
        self.assertEqual(_classify_margin_status(-5.0), MARGIN_STATUS_LIQUIDATING)

    def test_liquidating_very_negative(self):
        self.assertEqual(_classify_margin_status(-100.0), MARGIN_STATUS_LIQUIDATING)


# ---------------------------------------------------------------------------
# Group 3: _compute_position_metrics
# ---------------------------------------------------------------------------

class TestComputePositionMetrics(unittest.TestCase):

    def test_leverage_ratio_basic(self):
        pos = _make_position(position_value_usd=20_000, collateral_usd=10_000)
        result = _compute_position_metrics(pos)
        self.assertAlmostEqual(result["leverage_ratio"], 2.0, places=4)

    def test_leverage_ratio_1x(self):
        pos = _make_position(position_value_usd=5_000, collateral_usd=5_000)
        result = _compute_position_metrics(pos)
        self.assertAlmostEqual(result["leverage_ratio"], 1.0, places=4)

    def test_leverage_ratio_3x(self):
        pos = _make_position(position_value_usd=30_000, collateral_usd=10_000)
        result = _compute_position_metrics(pos)
        self.assertAlmostEqual(result["leverage_ratio"], 3.0, places=4)

    def test_leverage_ratio_zero_collateral_nonzero_value(self):
        pos = _make_position(position_value_usd=1_000, collateral_usd=0)
        result = _compute_position_metrics(pos)
        self.assertEqual(result["leverage_ratio"], 9999.0)

    def test_leverage_ratio_zero_collateral_zero_value(self):
        pos = _make_position(position_value_usd=0, collateral_usd=0)
        result = _compute_position_metrics(pos)
        self.assertEqual(result["leverage_ratio"], 0.0)

    def test_leverage_ratio_fractional(self):
        pos = _make_position(position_value_usd=5_000, collateral_usd=10_000)
        result = _compute_position_metrics(pos)
        self.assertAlmostEqual(result["leverage_ratio"], 0.5, places=4)

    def test_margin_ratio_basic(self):
        # (5000 - 3000) / 10000 * 100 = 20
        pos = _make_position(position_value_usd=10_000, collateral_usd=5_000, debt_usd=3_000)
        result = _compute_position_metrics(pos)
        self.assertAlmostEqual(result["margin_ratio"], 20.0, places=4)

    def test_margin_ratio_no_debt(self):
        # (5000 - 0) / 10000 * 100 = 50
        pos = _make_position(position_value_usd=10_000, collateral_usd=5_000, debt_usd=0)
        result = _compute_position_metrics(pos)
        self.assertAlmostEqual(result["margin_ratio"], 50.0, places=4)

    def test_margin_ratio_debt_equals_collateral(self):
        # (5000 - 5000) / 10000 * 100 = 0
        pos = _make_position(position_value_usd=10_000, collateral_usd=5_000, debt_usd=5_000)
        result = _compute_position_metrics(pos)
        self.assertAlmostEqual(result["margin_ratio"], 0.0, places=4)

    def test_margin_ratio_debt_exceeds_collateral(self):
        # (1000 - 2000) / 10000 * 100 = -10
        pos = _make_position(position_value_usd=10_000, collateral_usd=1_000, debt_usd=2_000)
        result = _compute_position_metrics(pos)
        self.assertAlmostEqual(result["margin_ratio"], -10.0, places=4)

    def test_margin_ratio_zero_position_value(self):
        pos = _make_position(position_value_usd=0, collateral_usd=5_000, debt_usd=1_000)
        result = _compute_position_metrics(pos)
        self.assertEqual(result["margin_ratio"], 0.0)

    def test_margin_safety_basic(self):
        # margin_ratio=20, maintenance=5 → safety=15
        pos = _make_position(
            position_value_usd=10_000, collateral_usd=5_000,
            debt_usd=3_000, maintenance_margin_pct=5.0
        )
        result = _compute_position_metrics(pos)
        self.assertAlmostEqual(result["margin_safety_pct"], 15.0, places=4)

    def test_margin_safety_negative(self):
        pos = _liquidating_position()
        result = _compute_position_metrics(pos)
        self.assertLess(result["margin_safety_pct"], 0.0)

    def test_margin_safety_maintenance_zero(self):
        pos = _make_position(
            position_value_usd=10_000, collateral_usd=5_000,
            debt_usd=3_000, maintenance_margin_pct=0.0
        )
        result = _compute_position_metrics(pos)
        # margin_ratio = (5000-3000)/10000*100 = 20, safety=20
        self.assertAlmostEqual(result["margin_safety_pct"], 20.0, places=4)

    def test_liquidation_distance_basic(self):
        # pos=10000, coll=5000, debt=3000, maint=5
        # leverage=2, margin_ratio=20, safety=15
        # liquidation_distance = 15 / 2 = 7.5
        pos = _make_position(
            position_value_usd=10_000, collateral_usd=5_000,
            debt_usd=3_000, maintenance_margin_pct=5.0
        )
        result = _compute_position_metrics(pos)
        self.assertAlmostEqual(result["liquidation_distance_pct"], 7.5, places=4)

    def test_liquidation_distance_zero_leverage(self):
        pos = _make_position(position_value_usd=0, collateral_usd=0, debt_usd=0)
        result = _compute_position_metrics(pos)
        self.assertEqual(result["liquidation_distance_pct"], 0.0)

    def test_protocol_name_preserved(self):
        pos = _make_position(protocol="Aave V3")
        result = _compute_position_metrics(pos)
        self.assertEqual(result["protocol"], "Aave V3")

    def test_large_values(self):
        pos = _make_position(
            position_value_usd=1_000_000_000,
            collateral_usd=500_000_000,
            debt_usd=100_000_000,
            maintenance_margin_pct=5.0,
        )
        result = _compute_position_metrics(pos)
        self.assertAlmostEqual(result["leverage_ratio"], 2.0, places=4)
        self.assertAlmostEqual(result["margin_ratio"], 40.0, places=4)
        self.assertAlmostEqual(result["margin_safety_pct"], 35.0, places=4)

    def test_margin_status_safe(self):
        result = _compute_position_metrics(_safe_position())
        self.assertEqual(result["margin_status"], MARGIN_STATUS_SAFE)

    def test_margin_status_warning(self):
        result = _compute_position_metrics(_warning_position())
        self.assertEqual(result["margin_status"], MARGIN_STATUS_WARNING)

    def test_margin_status_danger(self):
        result = _compute_position_metrics(_danger_position())
        self.assertEqual(result["margin_status"], MARGIN_STATUS_DANGER)

    def test_margin_status_liquidating(self):
        result = _compute_position_metrics(_liquidating_position())
        self.assertEqual(result["margin_status"], MARGIN_STATUS_LIQUIDATING)

    def test_result_keys_complete(self):
        expected_keys = {
            "protocol", "position_value_usd", "collateral_usd", "debt_usd",
            "maintenance_margin_pct", "leverage_ratio", "margin_ratio",
            "margin_safety_pct", "liquidation_distance_pct", "margin_status",
        }
        result = _compute_position_metrics(_safe_position())
        self.assertEqual(set(result.keys()), expected_keys)


# ---------------------------------------------------------------------------
# Group 4: monitor()
# ---------------------------------------------------------------------------

class TestMonitor(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.monitor = LeverageRatioMonitor(log_path=self.tmp.name)

    def tearDown(self):
        for f in [self.tmp.name, self.tmp.name + ".tmp"]:
            try:
                os.unlink(f)
            except OSError:
                pass

    def test_monitor_empty_positions(self):
        result = self.monitor.monitor([])
        self.assertEqual(result["total_positions"], 0)
        self.assertEqual(result["positions_at_risk"], 0)
        self.assertEqual(result["portfolio_max_leverage"], 0.0)
        self.assertEqual(result["portfolio_avg_leverage"], 0.0)

    def test_monitor_single_safe_position(self):
        result = self.monitor.monitor([_safe_position()])
        self.assertEqual(result["total_positions"], 1)
        self.assertEqual(result["positions"][0]["margin_status"], MARGIN_STATUS_SAFE)

    def test_monitor_single_warning_position(self):
        result = self.monitor.monitor([_warning_position()])
        self.assertEqual(result["positions"][0]["margin_status"], MARGIN_STATUS_WARNING)

    def test_monitor_single_danger_position(self):
        result = self.monitor.monitor([_danger_position()])
        self.assertEqual(result["positions"][0]["margin_status"], MARGIN_STATUS_DANGER)

    def test_monitor_single_liquidating_position(self):
        result = self.monitor.monitor([_liquidating_position()])
        self.assertEqual(result["positions"][0]["margin_status"], MARGIN_STATUS_LIQUIDATING)

    def test_monitor_multiple_positions_count(self):
        positions = [_safe_position(), _warning_position(), _danger_position()]
        result = self.monitor.monitor(positions)
        self.assertEqual(result["total_positions"], 3)
        self.assertEqual(len(result["positions"]), 3)

    def test_monitor_positions_at_risk_zero(self):
        result = self.monitor.monitor([_safe_position(), _warning_position()])
        self.assertEqual(result["positions_at_risk"], 0)

    def test_monitor_positions_at_risk_danger(self):
        result = self.monitor.monitor([_safe_position(), _danger_position()])
        self.assertEqual(result["positions_at_risk"], 1)

    def test_monitor_positions_at_risk_liquidating(self):
        result = self.monitor.monitor([_liquidating_position()])
        self.assertEqual(result["positions_at_risk"], 1)

    def test_monitor_positions_at_risk_mixed(self):
        positions = [
            _safe_position(),
            _danger_position(),
            _liquidating_position(),
            _warning_position(),
        ]
        result = self.monitor.monitor(positions)
        self.assertEqual(result["positions_at_risk"], 2)

    def test_monitor_portfolio_max_leverage_single(self):
        # leverage = 10000 / 5000 = 2.0
        result = self.monitor.monitor([_safe_position()])
        self.assertAlmostEqual(result["portfolio_max_leverage"], 2.0, places=4)

    def test_monitor_portfolio_max_leverage_multiple(self):
        p1 = _make_position(position_value_usd=10_000, collateral_usd=5_000)  # 2x
        p2 = _make_position(position_value_usd=10_000, collateral_usd=2_000)  # 5x
        result = self.monitor.monitor([p1, p2])
        self.assertAlmostEqual(result["portfolio_max_leverage"], 5.0, places=4)

    def test_monitor_portfolio_avg_leverage_single(self):
        result = self.monitor.monitor([_safe_position()])
        self.assertAlmostEqual(
            result["portfolio_max_leverage"],
            result["portfolio_avg_leverage"],
            places=4,
        )

    def test_monitor_portfolio_avg_leverage_two_positions(self):
        p1 = _make_position(position_value_usd=10_000, collateral_usd=5_000)   # 2x
        p2 = _make_position(position_value_usd=10_000, collateral_usd=10_000)  # 1x
        result = self.monitor.monitor([p1, p2])
        self.assertAlmostEqual(result["portfolio_avg_leverage"], 1.5, places=4)

    def test_monitor_timestamp_present(self):
        result = self.monitor.monitor([])
        self.assertIn("timestamp", result)
        self.assertAlmostEqual(result["timestamp"], time.time(), delta=5)

    def test_monitor_returns_result_dict(self):
        result = self.monitor.monitor([])
        self.assertIsInstance(result, dict)

    def test_monitor_result_keys(self):
        result = self.monitor.monitor([])
        for key in [
            "timestamp", "positions", "portfolio_max_leverage",
            "portfolio_avg_leverage", "positions_at_risk", "total_positions",
        ]:
            self.assertIn(key, result)

    def test_monitor_updates_last_result(self):
        self.assertIsNone(self.monitor._last_result)
        self.monitor.monitor([_safe_position()])
        self.assertIsNotNone(self.monitor._last_result)

    def test_monitor_all_at_risk(self):
        positions = [_danger_position(), _liquidating_position()]
        result = self.monitor.monitor(positions)
        self.assertEqual(result["positions_at_risk"], 2)

    def test_monitor_no_positions_at_risk_safe_only(self):
        result = self.monitor.monitor([_safe_position(), _safe_position()])
        self.assertEqual(result["positions_at_risk"], 0)


# ---------------------------------------------------------------------------
# Group 5: get_at_risk_positions()
# ---------------------------------------------------------------------------

class TestGetAtRiskPositions(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.monitor = LeverageRatioMonitor(log_path=self.tmp.name)

    def tearDown(self):
        for f in [self.tmp.name, self.tmp.name + ".tmp"]:
            try:
                os.unlink(f)
            except OSError:
                pass

    def test_at_risk_before_monitor_is_empty(self):
        self.assertEqual(self.monitor.get_at_risk_positions(), [])

    def test_at_risk_no_at_risk_positions(self):
        self.monitor.monitor([_safe_position(), _warning_position()])
        self.assertEqual(self.monitor.get_at_risk_positions(), [])

    def test_at_risk_includes_danger(self):
        self.monitor.monitor([_danger_position()])
        at_risk = self.monitor.get_at_risk_positions()
        self.assertEqual(len(at_risk), 1)
        self.assertEqual(at_risk[0]["margin_status"], MARGIN_STATUS_DANGER)

    def test_at_risk_includes_liquidating(self):
        self.monitor.monitor([_liquidating_position()])
        at_risk = self.monitor.get_at_risk_positions()
        self.assertEqual(len(at_risk), 1)
        self.assertEqual(at_risk[0]["margin_status"], MARGIN_STATUS_LIQUIDATING)

    def test_at_risk_excludes_safe(self):
        self.monitor.monitor([_safe_position(), _danger_position()])
        at_risk = self.monitor.get_at_risk_positions()
        statuses = [p["margin_status"] for p in at_risk]
        self.assertNotIn(MARGIN_STATUS_SAFE, statuses)

    def test_at_risk_excludes_warning(self):
        self.monitor.monitor([_warning_position(), _liquidating_position()])
        at_risk = self.monitor.get_at_risk_positions()
        statuses = [p["margin_status"] for p in at_risk]
        self.assertNotIn(MARGIN_STATUS_WARNING, statuses)

    def test_at_risk_mixed(self):
        self.monitor.monitor([
            _safe_position(), _warning_position(),
            _danger_position(), _liquidating_position(),
        ])
        at_risk = self.monitor.get_at_risk_positions()
        self.assertEqual(len(at_risk), 2)

    def test_at_risk_all_liquidating(self):
        self.monitor.monitor([_liquidating_position(), _liquidating_position()])
        at_risk = self.monitor.get_at_risk_positions()
        self.assertEqual(len(at_risk), 2)

    def test_at_risk_protocol_names_preserved(self):
        p = _make_position(protocol="RiskyPool")
        p2 = _liquidating_position()
        p2["protocol"] = "RiskyPool"
        self.monitor.monitor([p2])
        at_risk = self.monitor.get_at_risk_positions()
        self.assertEqual(at_risk[0]["protocol"], "RiskyPool")


# ---------------------------------------------------------------------------
# Group 6: get_portfolio_leverage_summary()
# ---------------------------------------------------------------------------

class TestGetPortfolioLeverageSummary(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.monitor = LeverageRatioMonitor(log_path=self.tmp.name)

    def tearDown(self):
        for f in [self.tmp.name, self.tmp.name + ".tmp"]:
            try:
                os.unlink(f)
            except OSError:
                pass

    def test_summary_before_monitor_returns_zeros(self):
        summary = self.monitor.get_portfolio_leverage_summary()
        self.assertEqual(summary["portfolio_max_leverage"], 0.0)
        self.assertEqual(summary["portfolio_avg_leverage"], 0.0)
        self.assertEqual(summary["positions_at_risk"], 0)
        self.assertEqual(summary["total_positions"], 0)

    def test_summary_empty_positions(self):
        self.monitor.monitor([])
        summary = self.monitor.get_portfolio_leverage_summary()
        self.assertEqual(summary["total_positions"], 0)
        self.assertEqual(summary["positions_at_risk"], 0)

    def test_summary_max_leverage(self):
        p1 = _make_position(position_value_usd=30_000, collateral_usd=10_000)  # 3x
        p2 = _make_position(position_value_usd=10_000, collateral_usd=10_000)  # 1x
        self.monitor.monitor([p1, p2])
        summary = self.monitor.get_portfolio_leverage_summary()
        self.assertAlmostEqual(summary["portfolio_max_leverage"], 3.0, places=4)

    def test_summary_avg_leverage(self):
        p1 = _make_position(position_value_usd=20_000, collateral_usd=10_000)  # 2x
        p2 = _make_position(position_value_usd=40_000, collateral_usd=10_000)  # 4x
        self.monitor.monitor([p1, p2])
        summary = self.monitor.get_portfolio_leverage_summary()
        self.assertAlmostEqual(summary["portfolio_avg_leverage"], 3.0, places=4)

    def test_summary_positions_at_risk(self):
        self.monitor.monitor([_safe_position(), _liquidating_position()])
        summary = self.monitor.get_portfolio_leverage_summary()
        self.assertEqual(summary["positions_at_risk"], 1)

    def test_summary_keys_present(self):
        self.monitor.monitor([])
        summary = self.monitor.get_portfolio_leverage_summary()
        for key in ["portfolio_max_leverage", "portfolio_avg_leverage",
                    "positions_at_risk", "total_positions"]:
            self.assertIn(key, summary)

    def test_summary_at_risk_matches_monitor_result(self):
        positions = [_danger_position(), _liquidating_position(), _safe_position()]
        result = self.monitor.monitor(positions)
        summary = self.monitor.get_portfolio_leverage_summary()
        self.assertEqual(summary["positions_at_risk"], result["positions_at_risk"])


# ---------------------------------------------------------------------------
# Group 7: Ring buffer & persistence
# ---------------------------------------------------------------------------

class TestRingBuffer(unittest.TestCase):

    def _make_monitor(self, max_entries=100):
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        return LeverageRatioMonitor(log_path=tmp.name, max_entries=max_entries), tmp.name

    def _cleanup(self, path):
        for f in [path, path + ".tmp"]:
            try:
                os.unlink(f)
            except OSError:
                pass

    def test_log_file_created_after_monitor(self):
        m, path = self._make_monitor()
        os.unlink(path)  # remove so we verify creation
        try:
            m.monitor([_safe_position()])
            self.assertTrue(os.path.exists(path))
        finally:
            self._cleanup(path)

    def test_log_file_is_list(self):
        m, path = self._make_monitor()
        try:
            m.monitor([])
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)
        finally:
            self._cleanup(path)

    def test_log_grows_on_multiple_monitors(self):
        m, path = self._make_monitor()
        try:
            m.monitor([_safe_position()])
            m.monitor([_warning_position()])
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
        finally:
            self._cleanup(path)

    def test_log_capped_at_max_entries(self):
        m, path = self._make_monitor(max_entries=3)
        try:
            for _ in range(5):
                m.monitor([_safe_position()])
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)
        finally:
            self._cleanup(path)

    def test_log_content_has_positions_key(self):
        m, path = self._make_monitor()
        try:
            m.monitor([_safe_position()])
            with open(path) as f:
                data = json.load(f)
            self.assertIn("positions", data[0])
        finally:
            self._cleanup(path)

    def test_log_content_has_timestamp(self):
        m, path = self._make_monitor()
        try:
            m.monitor([])
            with open(path) as f:
                data = json.load(f)
            self.assertIn("timestamp", data[0])
        finally:
            self._cleanup(path)

    def test_log_keeps_newest_on_cap(self):
        m, path = self._make_monitor(max_entries=2)
        try:
            p1 = _make_position(protocol="First")
            p2 = _make_position(protocol="Second")
            p3 = _make_position(protocol="Third")
            m.monitor([p1])
            m.monitor([p2])
            m.monitor([p3])
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
            protocols = [d["positions"][0]["protocol"] for d in data]
            self.assertIn("Second", protocols)
            self.assertIn("Third", protocols)
        finally:
            self._cleanup(path)

    def test_log_loads_existing_data(self):
        m, path = self._make_monitor(max_entries=10)
        try:
            # pre-populate with 5 entries
            with open(path, "w") as f:
                json.dump([{"existing": True}] * 5, f)
            m.monitor([])
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(len(data), 6)
        finally:
            self._cleanup(path)

    def test_custom_log_path_directory_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "subdir", "lev.json")
            m = LeverageRatioMonitor(log_path=log_path)
            m.monitor([])
            self.assertTrue(os.path.exists(log_path))


# ---------------------------------------------------------------------------
# Group 8: Edge cases & integration
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.monitor = LeverageRatioMonitor(log_path=self.tmp.name)

    def tearDown(self):
        for f in [self.tmp.name, self.tmp.name + ".tmp"]:
            try:
                os.unlink(f)
            except OSError:
                pass

    def test_maintenance_margin_50pct(self):
        # margin_ratio = (5000-1000)/10000*100 = 40, safety = 40-50 = -10 → LIQUIDATING
        pos = _make_position(
            position_value_usd=10_000, collateral_usd=5_000,
            debt_usd=1_000, maintenance_margin_pct=50.0
        )
        self.monitor.monitor([pos])
        at_risk = self.monitor.get_at_risk_positions()
        self.assertEqual(len(at_risk), 1)
        self.assertEqual(at_risk[0]["margin_status"], MARGIN_STATUS_LIQUIDATING)

    def test_multiple_protocols_distinct(self):
        p1 = _make_position(protocol="Aave")
        p2 = _make_position(protocol="Compound")
        result = self.monitor.monitor([p1, p2])
        protocols = [p["protocol"] for p in result["positions"]]
        self.assertIn("Aave", protocols)
        self.assertIn("Compound", protocols)

    def test_at_risk_count_matches_summary_count(self):
        self.monitor.monitor([
            _safe_position(), _danger_position(), _liquidating_position()
        ])
        at_risk = self.monitor.get_at_risk_positions()
        summary = self.monitor.get_portfolio_leverage_summary()
        self.assertEqual(len(at_risk), summary["positions_at_risk"])

    def test_second_monitor_overwrites_last_result(self):
        self.monitor.monitor([_safe_position()])
        self.monitor.monitor([_liquidating_position()])
        at_risk = self.monitor.get_at_risk_positions()
        self.assertEqual(len(at_risk), 1)
        self.assertEqual(at_risk[0]["margin_status"], MARGIN_STATUS_LIQUIDATING)

    def test_default_protocol_name(self):
        pos = {
            "position_value_usd": 10_000,
            "collateral_usd": 5_000,
            "debt_usd": 1_000,
            "maintenance_margin_pct": 5.0,
        }
        result = _compute_position_metrics(pos)
        self.assertEqual(result["protocol"], "unknown")

    def test_very_high_leverage_handled(self):
        pos = _make_position(position_value_usd=10_000, collateral_usd=1)
        result = _compute_position_metrics(pos)
        self.assertGreater(result["leverage_ratio"], 1000)

    def test_monitor_returns_same_count_as_input(self):
        positions = [_safe_position()] * 5
        result = self.monitor.monitor(positions)
        self.assertEqual(result["total_positions"], 5)
        self.assertEqual(len(result["positions"]), 5)


if __name__ == "__main__":
    unittest.main()
