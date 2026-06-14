"""
Tests for MP-855 DeFiCollateralHealthMonitor
Run with: python3 -m unittest spa_core.tests.test_defi_collateral_health_monitor
"""

import json
import math
import os
import tempfile
import unittest

from spa_core.analytics.defi_collateral_health_monitor import (
    analyze,
    append_log,
    run,
    _health_factor,
    _ltv_current,
    _buffer_to_liquidation_usd,
    _liquidation_price_drop_pct,
    _health_status,
    _recommendation,
)


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def make_pos(
    protocol="TestProtocol",
    collateral_usd=10000.0,
    debt_usd=5000.0,
    liquidation_threshold=0.85,
    collateral_factor=0.75,
    collateral_asset="ETH",
    borrow_asset="USDC",
):
    return {
        "protocol": protocol,
        "collateral_usd": collateral_usd,
        "debt_usd": debt_usd,
        "liquidation_threshold": liquidation_threshold,
        "collateral_factor": collateral_factor,
        "collateral_asset": collateral_asset,
        "borrow_asset": borrow_asset,
    }


# ===========================================================================
# Unit tests — internal helper functions
# ===========================================================================

class TestHealthFactor(unittest.TestCase):

    def test_normal_case(self):
        # hf = (10000 * 0.85) / 5000 = 1.7
        self.assertAlmostEqual(_health_factor(10000, 0.85, 5000), 1.7, places=6)

    def test_no_debt_returns_inf(self):
        self.assertEqual(_health_factor(10000, 0.85, 0), float('inf'))

    def test_zero_collateral_zero_debt(self):
        self.assertEqual(_health_factor(0, 0.85, 0), float('inf'))

    def test_zero_collateral_with_debt(self):
        # (0 * 0.85) / 5000 = 0.0
        self.assertAlmostEqual(_health_factor(0, 0.85, 5000), 0.0, places=6)

    def test_liquidatable_health_factor(self):
        # hf <= 1: collateral=5000, debt=6000, liq=0.85 → (5000*0.85)/6000 = 0.7083
        hf = _health_factor(5000, 0.85, 6000)
        self.assertLess(hf, 1.0)

    def test_exactly_at_liquidation(self):
        # hf = 1.0 exactly
        hf = _health_factor(1000, 0.85, 850)
        self.assertAlmostEqual(hf, 1.0, places=6)

    def test_high_threshold(self):
        hf = _health_factor(10000, 0.95, 5000)
        self.assertAlmostEqual(hf, 1.9, places=6)

    def test_negative_debt_treated_as_no_debt(self):
        # debt <= 0 → inf
        self.assertEqual(_health_factor(10000, 0.85, -1), float('inf'))


class TestLtvCurrent(unittest.TestCase):

    def test_normal_ltv(self):
        self.assertAlmostEqual(_ltv_current(5000, 10000), 0.5, places=6)

    def test_zero_collateral_returns_zero(self):
        self.assertEqual(_ltv_current(5000, 0), 0.0)

    def test_zero_debt(self):
        self.assertAlmostEqual(_ltv_current(0, 10000), 0.0, places=6)

    def test_high_ltv(self):
        self.assertAlmostEqual(_ltv_current(9000, 10000), 0.9, places=6)

    def test_above_100pct(self):
        # debt > collateral
        self.assertAlmostEqual(_ltv_current(12000, 10000), 1.2, places=6)


class TestBufferToLiquidation(unittest.TestCase):

    def test_no_debt_is_inf(self):
        self.assertEqual(_buffer_to_liquidation_usd(10000, 0, 0.85), float('inf'))

    def test_positive_buffer(self):
        # collateral=10000, debt=5000, liq=0.85
        # buffer = 10000 - (5000/0.85) = 10000 - 5882.35 = 4117.65
        buf = _buffer_to_liquidation_usd(10000, 5000, 0.85)
        self.assertAlmostEqual(buf, 10000 - 5000 / 0.85, places=2)

    def test_negative_buffer_underwater(self):
        # debt huge → already liquidatable
        buf = _buffer_to_liquidation_usd(5000, 9000, 0.85)
        self.assertLess(buf, 0)

    def test_exactly_zero_buffer(self):
        # collateral = debt/liq_threshold → buffer=0
        liq = 0.85
        debt = 8500
        collateral = debt / liq  # = 10000
        buf = _buffer_to_liquidation_usd(collateral, debt, liq)
        self.assertAlmostEqual(buf, 0.0, places=4)


class TestLiquidationPriceDropPct(unittest.TestCase):

    def test_no_debt_returns_100(self):
        self.assertAlmostEqual(_liquidation_price_drop_pct(10000, 0, 0.85), 100.0, places=6)

    def test_zero_collateral_returns_0(self):
        self.assertAlmostEqual(_liquidation_price_drop_pct(0, 5000, 0.85), 0.0, places=6)

    def test_normal_case(self):
        # 1 - (5000 / (10000*0.85)) * 100 = (1 - 0.5882) * 100 = 41.18%
        pct = _liquidation_price_drop_pct(10000, 5000, 0.85)
        expected = (1 - 5000 / (10000 * 0.85)) * 100
        self.assertAlmostEqual(pct, expected, places=4)

    def test_clamped_at_zero_when_underwater(self):
        # debt > collateral * liq_threshold
        pct = _liquidation_price_drop_pct(5000, 9000, 0.85)
        self.assertEqual(pct, 0.0)

    def test_high_buffer(self):
        pct = _liquidation_price_drop_pct(10000, 1000, 0.85)
        self.assertGreater(pct, 80.0)


class TestHealthStatus(unittest.TestCase):

    def test_safe_no_debt(self):
        self.assertEqual(_health_status(float('inf'), 0), "SAFE")

    def test_safe_above_threshold(self):
        self.assertEqual(_health_status(2.0, 5000, 1.5), "SAFE")

    def test_warning_at_threshold(self):
        self.assertEqual(_health_status(1.5, 5000, 1.5), "WARNING")

    def test_warning_just_below(self):
        self.assertEqual(_health_status(1.49, 5000, 1.5), "WARNING")

    def test_danger(self):
        self.assertEqual(_health_status(1.2, 5000, 1.5), "DANGER")

    def test_critical(self):
        self.assertEqual(_health_status(1.05, 5000, 1.5), "CRITICAL")

    def test_liquidatable(self):
        self.assertEqual(_health_status(0.95, 5000, 1.5), "LIQUIDATABLE")

    def test_exactly_liquidatable(self):
        self.assertEqual(_health_status(1.0, 5000, 1.5), "LIQUIDATABLE")

    def test_exactly_critical_boundary(self):
        self.assertEqual(_health_status(1.1, 5000, 1.5), "CRITICAL")

    def test_exactly_danger_boundary(self):
        self.assertEqual(_health_status(1.25, 5000, 1.5), "DANGER")

    def test_custom_safe_threshold(self):
        # With safe_hf=2.0, hf=1.8 should be WARNING
        self.assertEqual(_health_status(1.8, 5000, 2.0), "WARNING")

    def test_custom_safe_threshold_safe(self):
        self.assertEqual(_health_status(2.1, 5000, 2.0), "SAFE")


class TestRecommendation(unittest.TestCase):

    def test_safe_no_debt(self):
        rec = _recommendation("SAFE", float('inf'), float('inf'), 100.0)
        self.assertIn("No debt", rec)

    def test_safe_with_debt(self):
        rec = _recommendation("SAFE", 2.0, 4000, 41.0)
        self.assertIn("healthy", rec)
        self.assertIn("2.00", rec)
        self.assertIn("4000", rec)

    def test_warning(self):
        rec = _recommendation("WARNING", 1.45, 1000, 20.0)
        self.assertIn("Monitor", rec)
        self.assertIn("1.45", rec)

    def test_danger(self):
        rec = _recommendation("DANGER", 1.2, 500, 15.3)
        self.assertIn("15.3%", rec)
        self.assertIn("liquidation", rec)

    def test_critical(self):
        rec = _recommendation("CRITICAL", 1.05, 200, 5.8)
        self.assertIn("5.8%", rec)
        self.assertIn("immediately", rec)

    def test_liquidatable(self):
        rec = _recommendation("LIQUIDATABLE", 0.9, -500, 0.0)
        self.assertIn("URGENT", rec)
        self.assertIn("500", rec)

    def test_liquidatable_positive_abs(self):
        rec = _recommendation("LIQUIDATABLE", 0.85, -1234, 0.0)
        self.assertIn("1234", rec)


# ===========================================================================
# Integration tests — analyze()
# ===========================================================================

class TestAnalyzeEmpty(unittest.TestCase):

    def test_empty_positions(self):
        result = analyze([])
        self.assertEqual(result["positions"], [])
        ps = result["portfolio_summary"]
        self.assertEqual(ps["total_positions"], 0)
        self.assertEqual(ps["total_collateral_usd"], 0)
        self.assertEqual(ps["total_debt_usd"], 0)
        self.assertIsNone(ps["most_at_risk"])
        self.assertIsNone(ps["average_health_factor"])
        self.assertIn("timestamp", result)

    def test_timestamp_is_float(self):
        result = analyze([])
        self.assertIsInstance(result["timestamp"], float)


class TestAnalyzeSingleSafe(unittest.TestCase):

    def setUp(self):
        self.pos = make_pos(collateral_usd=10000, debt_usd=5000, liquidation_threshold=0.85)
        self.result = analyze([self.pos])

    def test_one_position_returned(self):
        self.assertEqual(len(self.result["positions"]), 1)

    def test_health_factor_correct(self):
        hf = self.result["positions"][0]["health_factor"]
        self.assertAlmostEqual(hf, (10000 * 0.85) / 5000, places=6)

    def test_status_safe(self):
        self.assertEqual(self.result["positions"][0]["health_status"], "SAFE")

    def test_ltv_current(self):
        ltv = self.result["positions"][0]["ltv_current"]
        self.assertAlmostEqual(ltv, 0.5, places=6)

    def test_ltv_max(self):
        self.assertAlmostEqual(self.result["positions"][0]["ltv_max"], 0.75, places=6)

    def test_ltv_liquidation(self):
        self.assertAlmostEqual(self.result["positions"][0]["ltv_liquidation"], 0.85, places=6)

    def test_portfolio_positions_safe_1(self):
        self.assertEqual(self.result["portfolio_summary"]["positions_safe"], 1)

    def test_portfolio_positions_at_risk_0(self):
        self.assertEqual(self.result["portfolio_summary"]["positions_at_risk"], 0)

    def test_most_at_risk_none_when_single_safe(self):
        # There is one position with finite hf — it IS the lowest, so most_at_risk is set
        ps = self.result["portfolio_summary"]
        self.assertEqual(ps["most_at_risk"], "TestProtocol")

    def test_average_health_factor_correct(self):
        avg = self.result["portfolio_summary"]["average_health_factor"]
        expected = (10000 * 0.85) / 5000
        self.assertAlmostEqual(avg, expected, places=6)

    def test_buffer_positive(self):
        buf = self.result["positions"][0]["buffer_to_liquidation_usd"]
        self.assertGreater(buf, 0)

    def test_recommendation_contains_healthy(self):
        rec = self.result["positions"][0]["recommendation"]
        self.assertIn("healthy", rec)


class TestAnalyzeNoDebt(unittest.TestCase):

    def setUp(self):
        self.pos = make_pos(collateral_usd=10000, debt_usd=0)
        self.result = analyze([self.pos])

    def test_health_factor_inf(self):
        hf = self.result["positions"][0]["health_factor"]
        self.assertTrue(math.isinf(hf))

    def test_status_safe(self):
        self.assertEqual(self.result["positions"][0]["health_status"], "SAFE")

    def test_buffer_inf(self):
        buf = self.result["positions"][0]["buffer_to_liquidation_usd"]
        self.assertTrue(math.isinf(buf))

    def test_drop_pct_100(self):
        self.assertAlmostEqual(
            self.result["positions"][0]["liquidation_price_drop_pct"], 100.0, places=6
        )

    def test_recommendation_no_debt(self):
        rec = self.result["positions"][0]["recommendation"]
        self.assertIn("No debt", rec)

    def test_most_at_risk_none(self):
        ps = self.result["portfolio_summary"]
        self.assertIsNone(ps["most_at_risk"])

    def test_average_hf_none(self):
        ps = self.result["portfolio_summary"]
        self.assertIsNone(ps["average_health_factor"])


class TestAnalyzeZeroCollateralWithDebt(unittest.TestCase):

    def setUp(self):
        self.pos = make_pos(collateral_usd=0, debt_usd=5000)
        self.result = analyze([self.pos])
        self.p = self.result["positions"][0]

    def test_ltv_zero(self):
        self.assertAlmostEqual(self.p["ltv_current"], 0.0, places=6)

    def test_health_factor_zero(self):
        self.assertAlmostEqual(self.p["health_factor"], 0.0, places=6)

    def test_status_liquidatable(self):
        self.assertEqual(self.p["health_status"], "LIQUIDATABLE")

    def test_drop_pct_zero(self):
        self.assertAlmostEqual(self.p["liquidation_price_drop_pct"], 0.0, places=6)


class TestAnalyzeLiquidatable(unittest.TestCase):

    def setUp(self):
        # hf = (5000*0.85)/6000 = 0.7083
        self.pos = make_pos(collateral_usd=5000, debt_usd=6000, liquidation_threshold=0.85)
        self.result = analyze([self.pos])
        self.p = self.result["positions"][0]

    def test_status_liquidatable(self):
        self.assertEqual(self.p["health_status"], "LIQUIDATABLE")

    def test_recommendation_urgent(self):
        self.assertIn("URGENT", self.p["recommendation"])

    def test_buffer_negative(self):
        self.assertLess(self.p["buffer_to_liquidation_usd"], 0)

    def test_drop_pct_zero(self):
        self.assertAlmostEqual(self.p["liquidation_price_drop_pct"], 0.0, places=6)

    def test_at_risk_count_1(self):
        self.assertEqual(self.result["portfolio_summary"]["positions_at_risk"], 1)


class TestAnalyzeCritical(unittest.TestCase):

    def setUp(self):
        # hf = (10000*0.85)/8000 = 1.0625 → CRITICAL
        self.pos = make_pos(collateral_usd=10000, debt_usd=8000, liquidation_threshold=0.85)
        self.result = analyze([self.pos])
        self.p = self.result["positions"][0]

    def test_status_critical(self):
        self.assertEqual(self.p["health_status"], "CRITICAL")

    def test_recommendation_mentions_immediately(self):
        self.assertIn("immediately", self.p["recommendation"])


class TestAnalyzeDanger(unittest.TestCase):

    def setUp(self):
        # hf = (10000*0.85)/7000 = 1.2143 → DANGER
        self.pos = make_pos(collateral_usd=10000, debt_usd=7000, liquidation_threshold=0.85)
        self.result = analyze([self.pos])
        self.p = self.result["positions"][0]

    def test_status_danger(self):
        self.assertEqual(self.p["health_status"], "DANGER")

    def test_recommendation_reduce_risk(self):
        self.assertIn("Reduce risk", self.p["recommendation"])


class TestAnalyzeWarning(unittest.TestCase):

    def setUp(self):
        # hf = (10000*0.85)/6000 = 1.4167 → WARNING (below 1.5)
        self.pos = make_pos(collateral_usd=10000, debt_usd=6000, liquidation_threshold=0.85)
        self.result = analyze([self.pos])
        self.p = self.result["positions"][0]

    def test_status_warning(self):
        self.assertEqual(self.p["health_status"], "WARNING")

    def test_recommendation_monitor(self):
        self.assertIn("Monitor", self.p["recommendation"])


class TestAnalyzeMultiplePositions(unittest.TestCase):

    def setUp(self):
        positions = [
            make_pos("Safe", collateral_usd=10000, debt_usd=3000, liquidation_threshold=0.85),
            make_pos("Danger", collateral_usd=10000, debt_usd=7200, liquidation_threshold=0.85),
            make_pos("Liquidatable", collateral_usd=5000, debt_usd=6000, liquidation_threshold=0.85),
        ]
        self.result = analyze(positions)

    def test_three_positions(self):
        self.assertEqual(len(self.result["positions"]), 3)

    def test_positions_safe_count(self):
        statuses = [p["health_status"] for p in self.result["positions"]]
        self.assertEqual(statuses[0], "SAFE")

    def test_positions_at_risk_2(self):
        ps = self.result["portfolio_summary"]
        self.assertEqual(ps["positions_at_risk"], 2)

    def test_most_at_risk_is_liquidatable(self):
        ps = self.result["portfolio_summary"]
        self.assertEqual(ps["most_at_risk"], "Liquidatable")

    def test_average_health_factor_computed(self):
        ps = self.result["portfolio_summary"]
        self.assertIsNotNone(ps["average_health_factor"])
        self.assertIsInstance(ps["average_health_factor"], float)

    def test_total_collateral_sum(self):
        ps = self.result["portfolio_summary"]
        self.assertAlmostEqual(ps["total_collateral_usd"], 25000.0, places=2)

    def test_total_debt_sum(self):
        ps = self.result["portfolio_summary"]
        self.assertAlmostEqual(ps["total_debt_usd"], 16200.0, places=2)


class TestAnalyzeAllNoDebt(unittest.TestCase):

    def setUp(self):
        positions = [
            make_pos("A", debt_usd=0),
            make_pos("B", debt_usd=0),
        ]
        self.result = analyze(positions)

    def test_all_safe(self):
        for p in self.result["positions"]:
            self.assertEqual(p["health_status"], "SAFE")

    def test_most_at_risk_none(self):
        self.assertIsNone(self.result["portfolio_summary"]["most_at_risk"])

    def test_average_hf_none(self):
        self.assertIsNone(self.result["portfolio_summary"]["average_health_factor"])


class TestAnalyzeCustomConfig(unittest.TestCase):

    def test_custom_safe_threshold_changes_status(self):
        # hf = (10000*0.85)/5000 = 1.7 → SAFE at default 1.5, WARNING at 2.0
        pos = make_pos(collateral_usd=10000, debt_usd=5000, liquidation_threshold=0.85)
        result_default = analyze([pos])
        result_custom = analyze([pos], config={"safe_health_factor": 2.0})
        self.assertEqual(result_default["positions"][0]["health_status"], "SAFE")
        self.assertEqual(result_custom["positions"][0]["health_status"], "WARNING")

    def test_config_none_uses_defaults(self):
        pos = make_pos(collateral_usd=10000, debt_usd=5000)
        result = analyze([pos], config=None)
        self.assertIn("health_status", result["positions"][0])

    def test_config_empty_dict_uses_defaults(self):
        pos = make_pos(collateral_usd=10000, debt_usd=5000)
        result = analyze([pos], config={})
        self.assertIn("health_status", result["positions"][0])


class TestAnalyzeFieldTypes(unittest.TestCase):

    def setUp(self):
        self.pos = make_pos()
        self.result = analyze([self.pos])
        self.p = self.result["positions"][0]

    def test_protocol_is_str(self):
        self.assertIsInstance(self.p["protocol"], str)

    def test_health_factor_is_float(self):
        self.assertIsInstance(self.p["health_factor"], float)

    def test_ltv_current_is_float(self):
        self.assertIsInstance(self.p["ltv_current"], float)

    def test_ltv_max_is_float(self):
        self.assertIsInstance(self.p["ltv_max"], float)

    def test_ltv_liquidation_is_float(self):
        self.assertIsInstance(self.p["ltv_liquidation"], float)

    def test_buffer_is_float(self):
        self.assertIsInstance(self.p["buffer_to_liquidation_usd"], float)

    def test_drop_pct_is_float(self):
        self.assertIsInstance(self.p["liquidation_price_drop_pct"], float)

    def test_health_status_is_str(self):
        self.assertIsInstance(self.p["health_status"], str)

    def test_recommendation_is_str(self):
        self.assertIsInstance(self.p["recommendation"], str)

    def test_collateral_asset_is_str(self):
        self.assertIsInstance(self.p["collateral_asset"], str)

    def test_borrow_asset_is_str(self):
        self.assertIsInstance(self.p["borrow_asset"], str)


class TestAnalyzeStatusBoundaries(unittest.TestCase):

    def _status_for_hf(self, hf_target):
        """Create position achieving target health factor."""
        # hf = (C * 0.85) / D → D = (C * 0.85) / hf
        C = 10000.0
        liq = 0.85
        D = (C * liq) / hf_target
        pos = make_pos(collateral_usd=C, debt_usd=D, liquidation_threshold=liq)
        return analyze([pos])["positions"][0]["health_status"]

    def test_hf_just_above_1_is_critical(self):
        self.assertEqual(self._status_for_hf(1.01), "CRITICAL")

    def test_hf_1_25_is_danger(self):
        self.assertEqual(self._status_for_hf(1.25), "DANGER")

    def test_hf_1_26_is_warning(self):
        self.assertEqual(self._status_for_hf(1.26), "WARNING")

    def test_hf_1_5_is_warning(self):
        self.assertEqual(self._status_for_hf(1.5), "WARNING")

    def test_hf_1_51_is_safe(self):
        self.assertEqual(self._status_for_hf(1.51), "SAFE")

    def test_hf_0_5_is_liquidatable(self):
        self.assertEqual(self._status_for_hf(0.5), "LIQUIDATABLE")


class TestAnalyzeProtocolNames(unittest.TestCase):

    def test_protocol_name_preserved(self):
        pos = make_pos(protocol="Aave V3 Ethereum")
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["protocol"], "Aave V3 Ethereum")

    def test_multiple_protocol_names(self):
        pos1 = make_pos(protocol="Aave")
        pos2 = make_pos(protocol="Compound")
        result = analyze([pos1, pos2])
        names = [p["protocol"] for p in result["positions"]]
        self.assertIn("Aave", names)
        self.assertIn("Compound", names)


# ===========================================================================
# Persistence tests — append_log, run
# ===========================================================================

class TestAppendLog(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_log_file(self):
        result = analyze([make_pos()])
        append_log(result, data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, "collateral_health_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_log_is_list(self):
        result = analyze([make_pos()])
        append_log(result, data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, "collateral_health_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        self.assertIsInstance(data, list)

    def test_log_contains_one_entry(self):
        result = analyze([make_pos()])
        append_log(result, data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, "collateral_health_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 1)

    def test_log_ring_buffer_cap_100(self):
        for i in range(105):
            result = analyze([make_pos(protocol=f"P{i}")])
            append_log(result, data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, "collateral_health_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 100)

    def test_log_keeps_latest_entries(self):
        for i in range(105):
            result = analyze([make_pos(protocol=f"P{i}")])
            append_log(result, data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, "collateral_health_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        # Last entry should be from i=104
        last_protocol = data[-1]["positions"][0]["protocol"]
        self.assertEqual(last_protocol, "P104")

    def test_log_appends_multiple(self):
        for _ in range(3):
            result = analyze([make_pos()])
            append_log(result, data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, "collateral_health_log.json")
        with open(log_path) as fh:
            data = json.load(fh)
        self.assertEqual(len(data), 3)


class TestRunFunction(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_run_returns_dict(self):
        positions = [make_pos()]
        result = run(positions, data_dir=self.tmpdir)
        self.assertIsInstance(result, dict)

    def test_run_creates_log(self):
        positions = [make_pos()]
        run(positions, data_dir=self.tmpdir)
        log_path = os.path.join(self.tmpdir, "collateral_health_log.json")
        self.assertTrue(os.path.exists(log_path))

    def test_run_result_has_positions(self):
        positions = [make_pos()]
        result = run(positions, data_dir=self.tmpdir)
        self.assertIn("positions", result)
        self.assertEqual(len(result["positions"]), 1)

    def test_run_with_config(self):
        positions = [make_pos(collateral_usd=10000, debt_usd=5000)]
        result = run(positions, config={"safe_health_factor": 2.0}, data_dir=self.tmpdir)
        self.assertIn("positions", result)


# ===========================================================================
# Edge case tests
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_collateral_zero_debt_zero(self):
        pos = make_pos(collateral_usd=0, debt_usd=0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertTrue(math.isinf(p["health_factor"]))
        self.assertEqual(p["health_status"], "SAFE")
        self.assertAlmostEqual(p["ltv_current"], 0.0, places=6)

    def test_very_small_debt(self):
        pos = make_pos(collateral_usd=10000, debt_usd=0.01)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertGreater(p["health_factor"], 100)
        self.assertEqual(p["health_status"], "SAFE")

    def test_very_large_collateral(self):
        pos = make_pos(collateral_usd=1e12, debt_usd=1000)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertGreater(p["health_factor"], 1e6)
        self.assertEqual(p["health_status"], "SAFE")

    def test_assets_preserved(self):
        pos = make_pos(collateral_asset="WBTC", borrow_asset="DAI")
        result = analyze([pos])
        p = result["positions"][0]
        self.assertEqual(p["collateral_asset"], "WBTC")
        self.assertEqual(p["borrow_asset"], "DAI")

    def test_positions_field_is_list(self):
        result = analyze([make_pos()])
        self.assertIsInstance(result["positions"], list)

    def test_portfolio_summary_keys(self):
        result = analyze([make_pos()])
        ps = result["portfolio_summary"]
        required_keys = [
            "total_positions", "total_collateral_usd", "total_debt_usd",
            "positions_safe", "positions_at_risk", "most_at_risk", "average_health_factor"
        ]
        for key in required_keys:
            self.assertIn(key, ps)

    def test_position_keys_complete(self):
        result = analyze([make_pos()])
        p = result["positions"][0]
        expected_keys = [
            "protocol", "collateral_usd", "debt_usd", "health_factor",
            "ltv_current", "ltv_max", "ltv_liquidation",
            "buffer_to_liquidation_usd", "liquidation_price_drop_pct",
            "health_status", "recommendation", "collateral_asset", "borrow_asset"
        ]
        for key in expected_keys:
            self.assertIn(key, p, f"Missing key: {key}")

    def test_liquidation_threshold_100pct(self):
        pos = make_pos(liquidation_threshold=1.0, debt_usd=10000, collateral_usd=10000)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["health_factor"], 1.0, places=6)
        self.assertEqual(p["health_status"], "LIQUIDATABLE")

    def test_mix_inf_and_finite_hf_average(self):
        positions = [
            make_pos("A", debt_usd=0),           # inf
            make_pos("B", collateral_usd=10000, debt_usd=5000, liquidation_threshold=0.85),  # 1.7
        ]
        result = analyze(positions)
        ps = result["portfolio_summary"]
        # average of finite hfs only → 1.7
        self.assertAlmostEqual(ps["average_health_factor"], 1.7, places=6)

    def test_positions_at_risk_all_safe(self):
        positions = [make_pos(debt_usd=0), make_pos(debt_usd=0)]
        result = analyze(positions)
        self.assertEqual(result["portfolio_summary"]["positions_at_risk"], 0)
        self.assertEqual(result["portfolio_summary"]["positions_safe"], 2)


if __name__ == "__main__":
    unittest.main()
