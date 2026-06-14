"""
Tests for MP-883: DeFiLeverageSafetyMonitor
Run: python3 -m unittest spa_core.tests.test_defi_leverage_safety_monitor -v
"""
import json
import math
import os
import sys
import tempfile
import time
import unittest

# Ensure project root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.defi_leverage_safety_monitor import (
    analyze,
    log_result,
    _analyze_position,
    _health_factor_label,
    _safety_status,
    _build_flags,
    _recommendation,
    _resolve_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pos(**kwargs) -> dict:
    """Return a default safe position, overriding with kwargs."""
    base = {
        "protocol": "TestProto",
        "collateral_usd": 100_000.0,
        "debt_usd": 40_000.0,
        "liquidation_threshold_pct": 80.0,
        "current_ltv_pct": 40.0,
        "collateral_apy_pct": 5.0,
        "borrow_cost_pct": 2.0,
        "leverage_multiplier": 2.0,
        "position_health_factor": 2.0,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# _resolve_config
# ---------------------------------------------------------------------------

class TestResolveConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = _resolve_config(None)
        self.assertAlmostEqual(cfg["safety_buffer_pct"], 10.0)

    def test_override(self):
        cfg = _resolve_config({"safety_buffer_pct": 15.0})
        self.assertAlmostEqual(cfg["safety_buffer_pct"], 15.0)

    def test_empty_dict(self):
        cfg = _resolve_config({})
        self.assertAlmostEqual(cfg["safety_buffer_pct"], 10.0)

    def test_string_value_coerces(self):
        cfg = _resolve_config({"safety_buffer_pct": "7"})
        self.assertAlmostEqual(cfg["safety_buffer_pct"], 7.0)


# ---------------------------------------------------------------------------
# _health_factor_label
# ---------------------------------------------------------------------------

class TestHealthFactorLabel(unittest.TestCase):
    def test_healthy(self):
        self.assertEqual(_health_factor_label(2.0), "HEALTHY")

    def test_exactly_1_5_is_adequate(self):
        self.assertEqual(_health_factor_label(1.5), "ADEQUATE")

    def test_adequate_range(self):
        self.assertEqual(_health_factor_label(1.3), "ADEQUATE")

    def test_exactly_1_2_is_critical(self):
        self.assertEqual(_health_factor_label(1.2), "CRITICAL")

    def test_critical_range(self):
        self.assertEqual(_health_factor_label(1.1), "CRITICAL")

    def test_exactly_1_0_is_liquidatable(self):
        self.assertEqual(_health_factor_label(1.0), "LIQUIDATABLE")

    def test_below_1_0_liquidatable(self):
        self.assertEqual(_health_factor_label(0.5), "LIQUIDATABLE")

    def test_zero_health_factor(self):
        self.assertEqual(_health_factor_label(0.0), "LIQUIDATABLE")

    def test_negative_health_factor(self):
        self.assertEqual(_health_factor_label(-0.5), "LIQUIDATABLE")

    def test_nan_health_factor(self):
        self.assertEqual(_health_factor_label(float("nan")), "LIQUIDATABLE")


# ---------------------------------------------------------------------------
# _safety_status
# ---------------------------------------------------------------------------

class TestSafetyStatus(unittest.TestCase):
    def test_safe(self):
        self.assertEqual(_safety_status(30.0, 2.0, 10.0), "SAFE")

    def test_warning_boundary(self):
        # 20% distance = exactly 2 * buffer → WARNING
        self.assertEqual(_safety_status(20.0, 1.6, 10.0), "WARNING")

    def test_warning_range(self):
        self.assertEqual(_safety_status(15.0, 1.6, 10.0), "WARNING")

    def test_danger_boundary(self):
        # exactly at buffer → DANGER
        self.assertEqual(_safety_status(10.0, 1.6, 10.0), "DANGER")

    def test_danger_range(self):
        self.assertEqual(_safety_status(5.0, 1.6, 10.0), "DANGER")

    def test_liquidatable_distance_zero(self):
        self.assertEqual(_safety_status(0.0, 1.6, 10.0), "LIQUIDATABLE")

    def test_liquidatable_negative_distance(self):
        self.assertEqual(_safety_status(-5.0, 2.0, 10.0), "LIQUIDATABLE")

    def test_liquidatable_health_factor_1(self):
        self.assertEqual(_safety_status(30.0, 1.0, 10.0), "LIQUIDATABLE")

    def test_liquidatable_health_factor_below_1(self):
        self.assertEqual(_safety_status(30.0, 0.9, 10.0), "LIQUIDATABLE")

    def test_liquidatable_nan_health(self):
        self.assertEqual(_safety_status(30.0, float("nan"), 10.0), "LIQUIDATABLE")


# ---------------------------------------------------------------------------
# _build_flags
# ---------------------------------------------------------------------------

class TestBuildFlags(unittest.TestCase):
    def test_no_flags(self):
        flags = _build_flags(30.0, 5.0, 2.0, 10.0)
        self.assertEqual(flags, [])

    def test_near_liquidation_flag(self):
        flags = _build_flags(5.0, 5.0, 2.0, 10.0)
        self.assertIn("NEAR_LIQUIDATION", flags)

    def test_negative_carry_flag(self):
        flags = _build_flags(30.0, -1.0, 2.0, 10.0)
        self.assertIn("NEGATIVE_CARRY", flags)

    def test_over_leveraged_flag(self):
        flags = _build_flags(30.0, 5.0, 6.0, 10.0)
        self.assertIn("OVER_LEVERAGED", flags)

    def test_all_flags(self):
        flags = _build_flags(5.0, -1.0, 6.0, 10.0)
        self.assertIn("NEAR_LIQUIDATION", flags)
        self.assertIn("NEGATIVE_CARRY", flags)
        self.assertIn("OVER_LEVERAGED", flags)

    def test_over_leveraged_exactly_5_not_flagged(self):
        flags = _build_flags(30.0, 5.0, 5.0, 10.0)
        self.assertNotIn("OVER_LEVERAGED", flags)

    def test_near_liquidation_at_buffer_boundary(self):
        flags = _build_flags(10.0, 5.0, 2.0, 10.0)
        self.assertIn("NEAR_LIQUIDATION", flags)


# ---------------------------------------------------------------------------
# _recommendation
# ---------------------------------------------------------------------------

class TestRecommendation(unittest.TestCase):
    def test_liquidatable(self):
        rec = _recommendation("LIQUIDATABLE", -5.0, 2.0, 0.5)
        self.assertIn("URGENT", rec)
        self.assertIn("liquidation risk", rec)

    def test_danger(self):
        rec = _recommendation("DANGER", 5.0, 3.0, 0.8)
        self.assertIn("High risk", rec)
        self.assertIn("5.0%", rec)

    def test_warning(self):
        rec = _recommendation("WARNING", 15.0, 4.0, 0.9)
        self.assertIn("Caution", rec)
        self.assertIn("15.0%", rec)

    def test_safe_positive_apy(self):
        rec = _recommendation("SAFE", 30.0, 7.0, 1.4)
        self.assertIn("Healthy position", rec)
        self.assertIn("7.0%", rec)
        self.assertIn("1.40x", rec)

    def test_safe_negative_apy(self):
        rec = _recommendation("SAFE", 30.0, -2.0, -0.5)
        self.assertIn("negative carry", rec)
        self.assertIn("-2.0%", rec)


# ---------------------------------------------------------------------------
# _analyze_position
# ---------------------------------------------------------------------------

class TestAnalyzePosition(unittest.TestCase):
    def test_basic_safe_position(self):
        pos = _make_pos()
        result = _analyze_position(pos, 10.0)
        self.assertEqual(result["protocol"], "TestProto")
        self.assertEqual(result["safety_status"], "SAFE")
        self.assertEqual(result["health_factor_label"], "HEALTHY")
        # net_apy = 5*2 - 2*1 = 8
        self.assertAlmostEqual(result["net_apy_pct"], 8.0, places=3)
        # funding_drag = 2*1 = 2
        self.assertAlmostEqual(result["funding_drag_pct"], 2.0, places=3)
        # liquidation_distance = 80 - 40 = 40
        self.assertAlmostEqual(result["liquidation_distance_pct"], 40.0, places=3)
        # efficiency = 8/5 = 1.6
        self.assertAlmostEqual(result["leverage_efficiency"], 1.6, places=3)

    def test_leverage_1_no_drag(self):
        pos = _make_pos(leverage_multiplier=1.0, borrow_cost_pct=5.0)
        result = _analyze_position(pos, 10.0)
        self.assertAlmostEqual(result["funding_drag_pct"], 0.0, places=6)
        self.assertAlmostEqual(result["net_apy_pct"], 5.0, places=6)

    def test_liquidatable_health_factor(self):
        pos = _make_pos(position_health_factor=0.95, current_ltv_pct=78.0)
        result = _analyze_position(pos, 10.0)
        self.assertEqual(result["safety_status"], "LIQUIDATABLE")
        self.assertEqual(result["health_factor_label"], "LIQUIDATABLE")

    def test_danger_status(self):
        pos = _make_pos(current_ltv_pct=74.0, position_health_factor=1.08)
        result = _analyze_position(pos, 10.0)
        # distance = 80 - 74 = 6 <= 10
        self.assertEqual(result["safety_status"], "DANGER")

    def test_warning_status(self):
        pos = _make_pos(current_ltv_pct=65.0, position_health_factor=1.3)
        result = _analyze_position(pos, 10.0)
        # distance = 80 - 65 = 15, within 2*10=20 but > 10 → WARNING
        self.assertEqual(result["safety_status"], "WARNING")

    def test_zero_collateral_apy_efficiency(self):
        pos = _make_pos(collateral_apy_pct=0.0)
        result = _analyze_position(pos, 10.0)
        self.assertAlmostEqual(result["leverage_efficiency"], 0.0, places=6)

    def test_negative_carry_flag(self):
        pos = _make_pos(collateral_apy_pct=1.0, borrow_cost_pct=5.0, leverage_multiplier=2.0)
        result = _analyze_position(pos, 10.0)
        # net_apy = 1*2 - 5*1 = -3
        self.assertIn("NEGATIVE_CARRY", result["flags"])
        self.assertAlmostEqual(result["net_apy_pct"], -3.0, places=3)

    def test_over_leveraged_flag(self):
        pos = _make_pos(leverage_multiplier=6.0)
        result = _analyze_position(pos, 10.0)
        self.assertIn("OVER_LEVERAGED", result["flags"])

    def test_near_liquidation_flag(self):
        pos = _make_pos(current_ltv_pct=75.0, position_health_factor=1.07)
        result = _analyze_position(pos, 10.0)
        # distance = 80 - 75 = 5 <= 10
        self.assertIn("NEAR_LIQUIDATION", result["flags"])

    def test_health_factor_adequate(self):
        pos = _make_pos(position_health_factor=1.3)
        result = _analyze_position(pos, 10.0)
        self.assertEqual(result["health_factor_label"], "ADEQUATE")

    def test_health_factor_critical(self):
        pos = _make_pos(position_health_factor=1.1, current_ltv_pct=76.0)
        result = _analyze_position(pos, 10.0)
        self.assertEqual(result["health_factor_label"], "CRITICAL")

    def test_protocol_name_preserved(self):
        pos = _make_pos(protocol="Morpho-USDC")
        result = _analyze_position(pos, 10.0)
        self.assertEqual(result["protocol"], "Morpho-USDC")

    def test_liquidation_distance_negative(self):
        pos = _make_pos(current_ltv_pct=85.0, position_health_factor=0.94)
        result = _analyze_position(pos, 10.0)
        self.assertLess(result["liquidation_distance_pct"], 0)
        self.assertEqual(result["safety_status"], "LIQUIDATABLE")

    def test_recommendation_in_result(self):
        pos = _make_pos()
        result = _analyze_position(pos, 10.0)
        self.assertIn("recommendation", result)
        self.assertIsInstance(result["recommendation"], str)
        self.assertGreater(len(result["recommendation"]), 0)


# ---------------------------------------------------------------------------
# analyze() — integration
# ---------------------------------------------------------------------------

class TestAnalyze(unittest.TestCase):
    def test_empty_positions(self):
        result = analyze([])
        self.assertEqual(result["positions"], [])
        self.assertEqual(result["at_risk_count"], 0)
        self.assertAlmostEqual(result["average_net_apy_pct"], 0.0)
        self.assertIsNone(result["highest_risk_position"])
        self.assertIn("timestamp", result)

    def test_single_safe_position(self):
        result = analyze([_make_pos()])
        self.assertEqual(len(result["positions"]), 1)
        self.assertEqual(result["at_risk_count"], 0)
        self.assertAlmostEqual(result["average_net_apy_pct"], 8.0, places=2)
        self.assertEqual(result["highest_risk_position"], "TestProto")

    def test_at_risk_count_danger(self):
        pos1 = _make_pos(protocol="A", current_ltv_pct=74.0, position_health_factor=1.08)
        pos2 = _make_pos(protocol="B")
        result = analyze([pos1, pos2])
        self.assertEqual(result["at_risk_count"], 1)

    def test_at_risk_count_liquidatable(self):
        pos = _make_pos(protocol="X", position_health_factor=0.95)
        result = analyze([pos])
        self.assertEqual(result["at_risk_count"], 1)

    def test_at_risk_count_warning_not_counted(self):
        pos = _make_pos(current_ltv_pct=65.0, position_health_factor=1.3)
        result = analyze([pos])
        self.assertEqual(result["at_risk_count"], 0)

    def test_highest_risk_is_min_distance(self):
        pos1 = _make_pos(protocol="A", current_ltv_pct=40.0)  # distance 40
        pos2 = _make_pos(protocol="B", current_ltv_pct=72.0, position_health_factor=1.1)  # distance 8
        result = analyze([pos1, pos2])
        self.assertEqual(result["highest_risk_position"], "B")

    def test_average_net_apy_multiple(self):
        # pos1 net_apy = 5*2 - 2*1 = 8
        pos1 = _make_pos(protocol="A")
        # pos2 net_apy = 3*1 - 4*0 = 3
        pos2 = _make_pos(
            protocol="B",
            collateral_apy_pct=3.0,
            borrow_cost_pct=4.0,
            leverage_multiplier=1.0,
        )
        result = analyze([pos1, pos2])
        self.assertAlmostEqual(result["average_net_apy_pct"], (8.0 + 3.0) / 2, places=2)

    def test_timestamp_recent(self):
        before = time.time()
        result = analyze([])
        after = time.time()
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)

    def test_custom_safety_buffer_changes_status(self):
        # distance = 15, default buffer 10 → WARNING; with buffer=20 → DANGER
        pos = _make_pos(current_ltv_pct=65.0, position_health_factor=1.6)
        result_default = analyze([pos])
        result_larger = analyze([pos], config={"safety_buffer_pct": 20.0})
        self.assertEqual(result_default["positions"][0]["safety_status"], "WARNING")
        self.assertEqual(result_larger["positions"][0]["safety_status"], "DANGER")

    def test_multiple_positions_returned(self):
        positions = [_make_pos(protocol=f"P{i}") for i in range(5)]
        result = analyze(positions)
        self.assertEqual(len(result["positions"]), 5)

    def test_result_keys_present(self):
        result = analyze([_make_pos()])
        for key in ("positions", "at_risk_count", "average_net_apy_pct",
                    "highest_risk_position", "timestamp"):
            self.assertIn(key, result)

    def test_position_keys_present(self):
        result = analyze([_make_pos()])
        pos = result["positions"][0]
        for key in (
            "protocol", "current_ltv_pct", "liquidation_distance_pct",
            "net_apy_pct", "funding_drag_pct", "safety_status",
            "health_factor_label", "leverage_efficiency", "recommendation", "flags",
        ):
            self.assertIn(key, pos, f"Missing key: {key}")

    def test_all_liquidatable_at_risk(self):
        positions = [
            _make_pos(protocol="X", position_health_factor=0.9),
            _make_pos(protocol="Y", position_health_factor=0.8),
        ]
        result = analyze(positions)
        self.assertEqual(result["at_risk_count"], 2)

    def test_zero_config_buffer(self):
        pos = _make_pos(current_ltv_pct=79.0, position_health_factor=1.5)
        result = analyze([pos], config={"safety_buffer_pct": 0.0})
        # distance = 1%, buffer=0 → not DANGER, not WARNING
        self.assertEqual(result["positions"][0]["safety_status"], "SAFE")

    def test_negative_net_apy_average(self):
        pos = _make_pos(
            collateral_apy_pct=1.0,
            borrow_cost_pct=10.0,
            leverage_multiplier=2.0,
        )
        result = analyze([pos])
        # net_apy = 1*2 - 10*1 = -8
        self.assertAlmostEqual(result["average_net_apy_pct"], -8.0, places=2)


# ---------------------------------------------------------------------------
# log_result
# ---------------------------------------------------------------------------

class TestLogResult(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _log_path(self):
        return os.path.join(self.tmpdir, "data", "leverage_safety_log.json")

    def test_creates_log_file(self):
        result = analyze([_make_pos()])
        log_result(result, self.tmpdir)
        self.assertTrue(os.path.exists(self._log_path()))

    def test_log_contains_entry(self):
        result = analyze([_make_pos()])
        log_result(result, self.tmpdir)
        with open(self._log_path()) as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 1)

    def test_log_appends(self):
        for _ in range(3):
            result = analyze([_make_pos()])
            log_result(result, self.tmpdir)
        with open(self._log_path()) as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 3)

    def test_ring_buffer_max_100(self):
        for _ in range(110):
            result = analyze([])
            log_result(result, self.tmpdir)
        with open(self._log_path()) as f:
            entries = json.load(f)
        self.assertLessEqual(len(entries), 100)

    def test_log_is_valid_json(self):
        log_result(analyze([]), self.tmpdir)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_timestamp(self):
        log_result(analyze([_make_pos()]), self.tmpdir)
        with open(self._log_path()) as f:
            entries = json.load(f)
        self.assertIn("timestamp", entries[0])

    def test_corrupted_log_resets(self):
        log_path = self._log_path()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w") as f:
            f.write("NOT JSON {{{")
        result = analyze([])
        log_result(result, self.tmpdir)  # should not raise
        with open(log_path) as f:
            entries = json.load(f)
        self.assertEqual(len(entries), 1)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_leverage_multiplier_zero(self):
        pos = _make_pos(leverage_multiplier=0.0)
        result = analyze([pos])
        p = result["positions"][0]
        # net_apy = 5*0 - 2*(0-1) = 2 (funding drag = 2*(0-1) = -2, so net = 0 + 2 = 2)
        # Actually: net = collateral_apy * lev - borrow * (lev-1) = 5*0 - 2*(0-1) = 0+2 = 2
        self.assertIsNotNone(p)

    def test_very_high_leverage(self):
        pos = _make_pos(leverage_multiplier=100.0)
        result = analyze([pos])
        p = result["positions"][0]
        self.assertIn("OVER_LEVERAGED", p["flags"])

    def test_all_zeros(self):
        pos = {
            "protocol": "Zero",
            "collateral_usd": 0.0,
            "debt_usd": 0.0,
            "liquidation_threshold_pct": 0.0,
            "current_ltv_pct": 0.0,
            "collateral_apy_pct": 0.0,
            "borrow_cost_pct": 0.0,
            "leverage_multiplier": 1.0,
            "position_health_factor": 2.0,
        }
        result = analyze([pos])
        p = result["positions"][0]
        self.assertAlmostEqual(p["net_apy_pct"], 0.0)
        self.assertAlmostEqual(p["funding_drag_pct"], 0.0)
        self.assertAlmostEqual(p["leverage_efficiency"], 0.0)

    def test_string_protocol_coercion(self):
        pos = _make_pos(protocol=123)
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["protocol"], "123")

    def test_missing_optional_fields_defaults(self):
        pos = {"protocol": "Minimal"}
        result = analyze([pos])
        p = result["positions"][0]
        self.assertIn("safety_status", p)

    def test_health_factor_exactly_1_5(self):
        pos = _make_pos(position_health_factor=1.5)
        result = _analyze_position(pos, 10.0)
        self.assertEqual(result["health_factor_label"], "ADEQUATE")

    def test_health_factor_exactly_1_2(self):
        pos = _make_pos(position_health_factor=1.2, current_ltv_pct=70.0)
        result = _analyze_position(pos, 10.0)
        self.assertEqual(result["health_factor_label"], "CRITICAL")

    def test_large_collateral_small_debt(self):
        pos = _make_pos(collateral_usd=1_000_000, debt_usd=1_000)
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["safety_status"], "SAFE")

    def test_danger_and_safe_mixed(self):
        safe = _make_pos(protocol="Safe")
        danger = _make_pos(
            protocol="Danger",
            current_ltv_pct=74.0,
            position_health_factor=1.08,
        )
        result = analyze([safe, danger])
        statuses = {p["protocol"]: p["safety_status"] for p in result["positions"]}
        self.assertEqual(statuses["Safe"], "SAFE")
        self.assertEqual(statuses["Danger"], "DANGER")

    def test_flags_is_list(self):
        result = analyze([_make_pos()])
        self.assertIsInstance(result["positions"][0]["flags"], list)

    def test_leverage_efficiency_positive_apy(self):
        # collateral_apy=5, leverage=3 → net = 5*3 - 2*2 = 15-4 = 11; eff = 11/5 = 2.2
        pos = _make_pos(collateral_apy_pct=5.0, borrow_cost_pct=2.0, leverage_multiplier=3.0)
        result = analyze([pos])
        self.assertAlmostEqual(result["positions"][0]["leverage_efficiency"], 2.2, places=3)

    def test_no_flags_clean_position(self):
        # Far from liquidation, positive carry, low leverage
        pos = _make_pos(
            current_ltv_pct=20.0,
            position_health_factor=3.0,
            leverage_multiplier=1.5,
            collateral_apy_pct=10.0,
            borrow_cost_pct=2.0,
        )
        result = analyze([pos])
        self.assertEqual(result["positions"][0]["flags"], [])

    def test_all_three_flags_simultaneously(self):
        pos = _make_pos(
            current_ltv_pct=73.0,  # distance = 7 <= 10 → NEAR_LIQUIDATION
            position_health_factor=1.09,
            collateral_apy_pct=1.0,
            borrow_cost_pct=5.0,   # net = -3 → NEGATIVE_CARRY
            leverage_multiplier=6.0,  # > 5 → OVER_LEVERAGED
        )
        result = analyze([pos])
        flags = result["positions"][0]["flags"]
        self.assertIn("NEAR_LIQUIDATION", flags)
        self.assertIn("NEGATIVE_CARRY", flags)
        self.assertIn("OVER_LEVERAGED", flags)


if __name__ == "__main__":
    unittest.main()
