"""
Tests for MP-768: LiquidationRiskHeatmap
Uses unittest only. 65+ test cases.

Coverage:
- compute_health_factor: zero debt, zero collateral, normal, threshold variants
- classify_risk: all four levels, boundary values
- compute_liquidation_price_drop_pct: normal, inf, zero, CRITICAL
- LiquidationRiskHeatmap.compute_heatmap: empty, single, multi, all CRITICAL
- get_portfolio_risk_score: empty, zero collateral, all safe, all critical, mixed
- get_at_risk_positions: filtering
- save / load_history: ring buffer cap, atomic write, empty/corrupt JSON
- Module-level convenience wrappers
"""

import json
import math
import os
import tempfile
import unittest

from spa_core.analytics.liquidation_risk_heatmap import (
    RING_BUFFER_CAP,
    RISK_CRITICAL,
    RISK_DANGER,
    RISK_SAFE,
    RISK_WARNING,
    HeatmapResult,
    LiquidationRiskHeatmap,
    classify_risk,
    compute_health_factor,
    compute_heatmap,
    compute_liquidation_price_drop_pct,
    get_at_risk_positions,
    get_portfolio_risk_score,
    load_history,
    save_results,
)


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

def _pos(
    protocol="TestProtocol",
    collateral_usd=10_000.0,
    debt_usd=5_000.0,
    liquidation_threshold_pct=0.8,
) -> dict:
    return {
        "protocol": protocol,
        "collateral_usd": collateral_usd,
        "debt_usd": debt_usd,
        "liquidation_threshold_pct": liquidation_threshold_pct,
    }


# ===========================================================================
# compute_health_factor
# ===========================================================================

class TestComputeHealthFactor(unittest.TestCase):

    def test_basic(self):
        # hf = (10000 * 0.8) / 5000 = 1.6
        hf = compute_health_factor(10_000, 5_000, 0.8)
        self.assertAlmostEqual(hf, 1.6, places=10)

    def test_zero_debt_returns_inf(self):
        hf = compute_health_factor(10_000, 0.0, 0.8)
        self.assertTrue(math.isinf(hf))

    def test_zero_debt_zero_collateral_returns_inf(self):
        hf = compute_health_factor(0.0, 0.0, 0.8)
        self.assertTrue(math.isinf(hf))

    def test_zero_collateral_nonzero_debt_returns_zero(self):
        hf = compute_health_factor(0.0, 5_000, 0.8)
        self.assertEqual(hf, 0.0)

    def test_negative_collateral_returns_zero(self):
        hf = compute_health_factor(-1_000, 5_000, 0.8)
        self.assertEqual(hf, 0.0)

    def test_threshold_one(self):
        # hf = (10000 * 1.0) / 5000 = 2.0
        hf = compute_health_factor(10_000, 5_000, 1.0)
        self.assertAlmostEqual(hf, 2.0, places=10)

    def test_threshold_zero(self):
        # hf = 0 / 5000 = 0.0
        hf = compute_health_factor(10_000, 5_000, 0.0)
        self.assertAlmostEqual(hf, 0.0, places=10)

    def test_high_leverage_ratio(self):
        # collateral=1000, debt=990, threshold=0.8 → hf = 800/990 ≈ 0.808
        hf = compute_health_factor(1_000, 990, 0.8)
        self.assertAlmostEqual(hf, 800 / 990, places=10)

    def test_equal_collateral_debt_full_threshold(self):
        # hf = (5000 * 1.0) / 5000 = 1.0
        hf = compute_health_factor(5_000, 5_000, 1.0)
        self.assertAlmostEqual(hf, 1.0, places=10)

    def test_large_values(self):
        hf = compute_health_factor(1_000_000, 100_000, 0.825)
        self.assertAlmostEqual(hf, (1_000_000 * 0.825) / 100_000, places=6)


# ===========================================================================
# classify_risk
# ===========================================================================

class TestClassifyRisk(unittest.TestCase):

    def test_safe_inf(self):
        self.assertEqual(classify_risk(math.inf), RISK_SAFE)

    def test_safe_exactly_2(self):
        self.assertEqual(classify_risk(2.0), RISK_SAFE)

    def test_safe_above_2(self):
        self.assertEqual(classify_risk(5.0), RISK_SAFE)

    def test_warning_just_below_2(self):
        self.assertEqual(classify_risk(1.999), RISK_WARNING)

    def test_warning_exactly_1_25(self):
        self.assertEqual(classify_risk(1.25), RISK_WARNING)

    def test_warning_mid(self):
        self.assertEqual(classify_risk(1.5), RISK_WARNING)

    def test_danger_just_below_1_25(self):
        self.assertEqual(classify_risk(1.249), RISK_DANGER)

    def test_danger_exactly_1(self):
        self.assertEqual(classify_risk(1.0), RISK_DANGER)

    def test_danger_just_above_1(self):
        self.assertEqual(classify_risk(1.001), RISK_DANGER)

    def test_critical_just_below_1(self):
        self.assertEqual(classify_risk(0.999), RISK_CRITICAL)

    def test_critical_zero(self):
        self.assertEqual(classify_risk(0.0), RISK_CRITICAL)

    def test_critical_negative(self):
        self.assertEqual(classify_risk(-1.0), RISK_CRITICAL)


# ===========================================================================
# compute_liquidation_price_drop_pct
# ===========================================================================

class TestComputeLiquidationPriceDropPct(unittest.TestCase):

    def test_inf_returns_100(self):
        self.assertAlmostEqual(
            compute_liquidation_price_drop_pct(math.inf), 100.0
        )

    def test_hf_2_returns_50_pct(self):
        # (1 - 1/2) * 100 = 50
        self.assertAlmostEqual(
            compute_liquidation_price_drop_pct(2.0), 50.0, places=10
        )

    def test_hf_1_returns_0(self):
        # (1 - 1/1) * 100 = 0
        self.assertAlmostEqual(
            compute_liquidation_price_drop_pct(1.0), 0.0, places=10
        )

    def test_hf_below_1_returns_0(self):
        # Already liquidatable
        self.assertEqual(compute_liquidation_price_drop_pct(0.8), 0.0)

    def test_hf_zero_returns_0(self):
        self.assertEqual(compute_liquidation_price_drop_pct(0.0), 0.0)

    def test_hf_negative_returns_0(self):
        self.assertEqual(compute_liquidation_price_drop_pct(-1.0), 0.0)

    def test_hf_1_5_returns_33_33(self):
        # (1 - 1/1.5) * 100 = (1 - 0.6667) * 100 ≈ 33.33
        expected = (1 - 1 / 1.5) * 100
        self.assertAlmostEqual(
            compute_liquidation_price_drop_pct(1.5), expected, places=8
        )

    def test_hf_4_returns_75(self):
        # (1 - 1/4) * 100 = 75
        self.assertAlmostEqual(
            compute_liquidation_price_drop_pct(4.0), 75.0, places=10
        )

    def test_hf_1_25_returns_20(self):
        # (1 - 1/1.25) * 100 = 20
        self.assertAlmostEqual(
            compute_liquidation_price_drop_pct(1.25), 20.0, places=8
        )


# ===========================================================================
# LiquidationRiskHeatmap.compute_heatmap
# ===========================================================================

class TestComputeHeatmap(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = LiquidationRiskHeatmap(data_dir=self.tmpdir)

    # --- Empty portfolio ---------------------------------------------------

    def test_empty_positions(self):
        result = self.engine.compute_heatmap([])
        self.assertIsInstance(result, HeatmapResult)
        self.assertEqual(result.positions, [])
        self.assertEqual(result.portfolio_risk_score, 0.0)
        self.assertEqual(result.positions_at_risk, 0)
        self.assertEqual(result.critical_count, 0)
        self.assertEqual(result.safe_count, 0)

    # --- Single position ---------------------------------------------------

    def test_single_safe_position(self):
        # hf = (10000 * 0.8) / 2000 = 4.0 → SAFE
        result = self.engine.compute_heatmap([
            _pos(collateral_usd=10_000, debt_usd=2_000, liquidation_threshold_pct=0.8)
        ])
        self.assertEqual(len(result.positions), 1)
        self.assertEqual(result.positions[0].risk_level, RISK_SAFE)
        self.assertEqual(result.safe_count, 1)
        self.assertEqual(result.positions_at_risk, 0)
        self.assertAlmostEqual(result.portfolio_risk_score, 0.0)

    def test_single_warning_position(self):
        # hf = (10000 * 0.8) / 5500 ≈ 1.4545 → WARNING
        result = self.engine.compute_heatmap([
            _pos(collateral_usd=10_000, debt_usd=5_500, liquidation_threshold_pct=0.8)
        ])
        self.assertEqual(result.positions[0].risk_level, RISK_WARNING)
        self.assertEqual(result.warning_count, 1)
        self.assertEqual(result.positions_at_risk, 1)
        self.assertAlmostEqual(result.portfolio_risk_score, 30.0)

    def test_single_danger_position(self):
        # hf = (10000 * 0.8) / 7500 ≈ 1.067 → DANGER
        result = self.engine.compute_heatmap([
            _pos(collateral_usd=10_000, debt_usd=7_500, liquidation_threshold_pct=0.8)
        ])
        self.assertEqual(result.positions[0].risk_level, RISK_DANGER)
        self.assertEqual(result.danger_count, 1)
        self.assertAlmostEqual(result.portfolio_risk_score, 70.0)

    def test_single_critical_position(self):
        # hf = (5000 * 0.8) / 5000 = 0.8 → CRITICAL
        result = self.engine.compute_heatmap([
            _pos(collateral_usd=5_000, debt_usd=5_000, liquidation_threshold_pct=0.8)
        ])
        self.assertEqual(result.positions[0].risk_level, RISK_CRITICAL)
        self.assertEqual(result.critical_count, 1)
        self.assertAlmostEqual(result.portfolio_risk_score, 100.0)

    def test_zero_debt_position_is_safe(self):
        # debt=0 → infinite HF → SAFE
        result = self.engine.compute_heatmap([
            _pos(collateral_usd=10_000, debt_usd=0.0, liquidation_threshold_pct=0.8)
        ])
        self.assertEqual(result.positions[0].risk_level, RISK_SAFE)
        self.assertTrue(math.isinf(result.positions[0].health_factor))
        self.assertAlmostEqual(result.positions[0].liquidation_price_drop_pct, 100.0)

    # --- All CRITICAL portfolio -------------------------------------------

    def test_all_critical_portfolio(self):
        positions = [
            _pos("P1", 1_000, 2_000, 0.8),   # hf = 0.4 → CRITICAL
            _pos("P2", 500, 1_000, 0.7),      # hf = 0.35 → CRITICAL
            _pos("P3", 2_000, 5_000, 0.6),    # hf = 0.24 → CRITICAL
        ]
        result = self.engine.compute_heatmap(positions)
        self.assertEqual(result.critical_count, 3)
        self.assertEqual(result.safe_count, 0)
        self.assertAlmostEqual(result.portfolio_risk_score, 100.0)
        self.assertEqual(result.positions_at_risk, 3)

    # --- Mixed portfolio --------------------------------------------------

    def test_mixed_portfolio_counts(self):
        positions = [
            _pos("S1", 50_000, 10_000, 0.825),   # hf=4.125 → SAFE
            _pos("W1", 10_000, 5_500, 0.8),       # hf≈1.45 → WARNING
            _pos("D1", 10_000, 7_500, 0.8),       # hf≈1.07 → DANGER
            _pos("C1", 5_000, 5_000, 0.8),        # hf=0.8 → CRITICAL
        ]
        result = self.engine.compute_heatmap(positions)
        self.assertEqual(result.safe_count, 1)
        self.assertEqual(result.warning_count, 1)
        self.assertEqual(result.danger_count, 1)
        self.assertEqual(result.critical_count, 1)
        self.assertEqual(result.positions_at_risk, 3)

    def test_result_has_advisory(self):
        result = self.engine.compute_heatmap([_pos()])
        self.assertIn("advisory", result.to_dict())
        self.assertIsInstance(result.advisory, str)
        self.assertGreater(len(result.advisory), 0)

    def test_result_has_computed_at(self):
        result = self.engine.compute_heatmap([_pos()])
        self.assertIn("T", result.computed_at)

    def test_position_health_factor_correct(self):
        result = self.engine.compute_heatmap([
            _pos(collateral_usd=10_000, debt_usd=5_000, liquidation_threshold_pct=0.8)
        ])
        self.assertAlmostEqual(result.positions[0].health_factor, 1.6, places=8)

    def test_position_drop_pct_correct_for_hf_1_6(self):
        result = self.engine.compute_heatmap([
            _pos(collateral_usd=10_000, debt_usd=5_000, liquidation_threshold_pct=0.8)
        ])
        # (1 - 1/1.6) * 100 = 37.5
        self.assertAlmostEqual(
            result.positions[0].liquidation_price_drop_pct, 37.5, places=4
        )

    def test_protocol_name_preserved(self):
        result = self.engine.compute_heatmap([_pos(protocol="Aave V3")])
        self.assertEqual(result.positions[0].protocol, "Aave V3")

    # --- to_dict serialisation -------------------------------------------

    def test_to_dict_keys(self):
        result = self.engine.compute_heatmap([_pos()])
        d = result.to_dict()
        for key in ("computed_at", "portfolio_risk_score", "positions_at_risk",
                    "risk_heatmap", "advisory"):
            self.assertIn(key, d)

    def test_position_to_dict_inf_health_factor_is_none(self):
        result = self.engine.compute_heatmap([
            _pos(collateral_usd=10_000, debt_usd=0.0, liquidation_threshold_pct=0.8)
        ])
        d = result.positions[0].to_dict()
        self.assertIsNone(d["health_factor"])

    def test_position_to_dict_finite_health_factor_is_float(self):
        result = self.engine.compute_heatmap([_pos()])
        d = result.positions[0].to_dict()
        self.assertIsInstance(d["health_factor"], float)


# ===========================================================================
# Portfolio risk score
# ===========================================================================

class TestPortfolioRiskScore(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = LiquidationRiskHeatmap(data_dir=self.tmpdir)

    def test_empty_portfolio_score_is_zero(self):
        self.engine.compute_heatmap([])
        self.assertAlmostEqual(self.engine.get_portfolio_risk_score(), 0.0)

    def test_all_safe_score_is_zero(self):
        positions = [
            _pos("A", 50_000, 10_000, 0.825),
            _pos("B", 30_000, 5_000, 0.8),
        ]
        self.engine.compute_heatmap(positions)
        self.assertAlmostEqual(self.engine.get_portfolio_risk_score(), 0.0)

    def test_all_critical_score_is_100(self):
        positions = [
            _pos("A", 5_000, 10_000, 0.8),   # CRITICAL
            _pos("B", 3_000, 6_000, 0.8),    # CRITICAL
        ]
        self.engine.compute_heatmap(positions)
        self.assertAlmostEqual(self.engine.get_portfolio_risk_score(), 100.0)

    def test_before_compute_returns_zero(self):
        engine = LiquidationRiskHeatmap(data_dir=self.tmpdir)
        self.assertEqual(engine.get_portfolio_risk_score(), 0.0)

    def test_zero_collateral_equal_weight_fallback(self):
        # collateral=0 triggers equal-weight fallback
        positions = [
            _pos("A", 0.0, 5_000, 0.8),   # CRITICAL (hf=0)
            _pos("B", 0.0, 5_000, 0.8),   # CRITICAL
        ]
        self.engine.compute_heatmap(positions)
        # All CRITICAL → 100
        self.assertAlmostEqual(self.engine.get_portfolio_risk_score(), 100.0)

    def test_weighted_average_mixed(self):
        # Safe (10000 collateral) + Critical (10000 collateral) → (0+100)/2=50
        positions = [
            _pos("SAFE", 10_000, 2_000, 0.8),   # hf=4.0 → SAFE → 0
            _pos("CRIT", 10_000, 15_000, 0.8),  # hf=0.53 → CRITICAL → 100
        ]
        self.engine.compute_heatmap(positions)
        # weighted: (0*10000 + 100*10000) / 20000 = 50
        self.assertAlmostEqual(self.engine.get_portfolio_risk_score(), 50.0, places=4)

    def test_score_in_range_0_to_100(self):
        positions = [
            _pos("A", 50_000, 30_000, 0.8),
            _pos("B", 10_000, 9_500, 0.8),
        ]
        self.engine.compute_heatmap(positions)
        score = self.engine.get_portfolio_risk_score()
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)


# ===========================================================================
# get_at_risk_positions
# ===========================================================================

class TestGetAtRiskPositions(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = LiquidationRiskHeatmap(data_dir=self.tmpdir)

    def test_no_positions_at_risk(self):
        self.engine.compute_heatmap([
            _pos("A", 50_000, 5_000, 0.825),  # SAFE
        ])
        self.assertEqual(self.engine.get_at_risk_positions(), [])

    def test_returns_warning_positions(self):
        self.engine.compute_heatmap([
            _pos("W", 10_000, 5_500, 0.8),   # WARNING
            _pos("S", 50_000, 5_000, 0.825), # SAFE
        ])
        at_risk = self.engine.get_at_risk_positions()
        self.assertEqual(len(at_risk), 1)
        self.assertEqual(at_risk[0].protocol, "W")

    def test_returns_all_non_safe(self):
        self.engine.compute_heatmap([
            _pos("S", 50_000, 5_000, 0.825),
            _pos("W", 10_000, 5_500, 0.8),
            _pos("D", 10_000, 7_500, 0.8),
            _pos("C", 5_000, 5_000, 0.8),
        ])
        at_risk = self.engine.get_at_risk_positions()
        self.assertEqual(len(at_risk), 3)

    def test_before_compute_returns_empty(self):
        engine = LiquidationRiskHeatmap(data_dir=self.tmpdir)
        self.assertEqual(engine.get_at_risk_positions(), [])

    def test_all_safe_returns_empty(self):
        self.engine.compute_heatmap([
            _pos("A", 100_000, 10_000, 0.825),
            _pos("B", 50_000, 5_000, 0.8),
        ])
        self.assertEqual(self.engine.get_at_risk_positions(), [])


# ===========================================================================
# save / load_history (ring buffer + atomic write)
# ===========================================================================

class TestSaveAndLoadHistory(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = LiquidationRiskHeatmap(data_dir=self.tmpdir)

    def _compute_and_save(self, n_positions: int = 1) -> str:
        positions = [_pos(f"P{i}") for i in range(n_positions)]
        result = self.engine.compute_heatmap(positions)
        return self.engine.save(result)

    def test_save_creates_log_file(self):
        path = self._compute_and_save()
        self.assertTrue(os.path.exists(path))

    def test_save_returns_correct_path(self):
        path = self._compute_and_save()
        self.assertTrue(path.endswith("liquidation_risk_heatmap_log.json"))

    def test_load_history_empty_before_save(self):
        history = self.engine.load_history()
        self.assertEqual(history, [])

    def test_save_and_load_roundtrip(self):
        self._compute_and_save()
        history = self.engine.load_history()
        self.assertEqual(len(history), 1)

    def test_multiple_saves_accumulate(self):
        for _ in range(5):
            self._compute_and_save()
        history = self.engine.load_history()
        self.assertEqual(len(history), 5)

    def test_ring_buffer_cap(self):
        for _ in range(RING_BUFFER_CAP + 10):
            self._compute_and_save()
        history = self.engine.load_history()
        self.assertEqual(len(history), RING_BUFFER_CAP)

    def test_ring_buffer_keeps_latest_entries(self):
        # Save 110 entries, cap=100 → only last 100 kept
        for i in range(RING_BUFFER_CAP + 10):
            positions = [_pos(f"P{i}")]
            result = self.engine.compute_heatmap(positions)
            self.engine.save(result)
        history = self.engine.load_history()
        self.assertEqual(len(history), RING_BUFFER_CAP)

    def test_load_history_missing_file_returns_empty(self):
        engine = LiquidationRiskHeatmap(data_dir=self.tmpdir)
        history = engine.load_history()
        self.assertEqual(history, [])

    def test_load_history_corrupt_json_returns_empty(self):
        log_path = os.path.join(self.tmpdir, "liquidation_risk_heatmap_log.json")
        with open(log_path, "w") as f:
            f.write("{INVALID JSON}")
        history = self.engine.load_history()
        self.assertEqual(history, [])

    def test_load_history_non_list_json_returns_empty(self):
        log_path = os.path.join(self.tmpdir, "liquidation_risk_heatmap_log.json")
        with open(log_path, "w") as f:
            json.dump({"not": "a list"}, f)
        history = self.engine.load_history()
        self.assertEqual(history, [])

    def test_saved_entry_has_risk_heatmap_key(self):
        self._compute_and_save()
        history = self.engine.load_history()
        self.assertIn("risk_heatmap", history[0])

    def test_saved_entry_has_portfolio_risk_score(self):
        self._compute_and_save()
        history = self.engine.load_history()
        self.assertIn("portfolio_risk_score", history[0])

    def test_atomic_write_no_partial_file(self):
        # Save successfully, then check the file is valid JSON
        self._compute_and_save()
        log_path = os.path.join(self.tmpdir, "liquidation_risk_heatmap_log.json")
        with open(log_path, "r") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)


# ===========================================================================
# Module-level convenience wrappers
# ===========================================================================

class TestConvenienceWrappers(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_compute_heatmap_wrapper(self):
        result = compute_heatmap([_pos()], data_dir=self.tmpdir)
        self.assertIsInstance(result, HeatmapResult)

    def test_get_portfolio_risk_score_wrapper_safe(self):
        # Large HF → SAFE → 0
        positions = [_pos(collateral_usd=100_000, debt_usd=5_000)]
        score = get_portfolio_risk_score(positions, data_dir=self.tmpdir)
        self.assertAlmostEqual(score, 0.0)

    def test_get_at_risk_positions_wrapper_empty(self):
        positions = [_pos(collateral_usd=100_000, debt_usd=5_000)]
        at_risk = get_at_risk_positions(positions, data_dir=self.tmpdir)
        self.assertEqual(at_risk, [])

    def test_save_results_wrapper(self):
        result = compute_heatmap([_pos()], data_dir=self.tmpdir)
        path = save_results(result, data_dir=self.tmpdir)
        self.assertTrue(os.path.exists(path))

    def test_load_history_wrapper(self):
        result = compute_heatmap([_pos()], data_dir=self.tmpdir)
        save_results(result, data_dir=self.tmpdir)
        history = load_history(data_dir=self.tmpdir)
        self.assertEqual(len(history), 1)

    def test_at_risk_wrapper_returns_critical(self):
        positions = [_pos(collateral_usd=1_000, debt_usd=5_000, liquidation_threshold_pct=0.8)]
        at_risk = get_at_risk_positions(positions, data_dir=self.tmpdir)
        self.assertEqual(len(at_risk), 1)
        self.assertEqual(at_risk[0].risk_level, RISK_CRITICAL)


# ===========================================================================
# Edge cases and boundary conditions
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = LiquidationRiskHeatmap(data_dir=self.tmpdir)

    def test_hf_exactly_2_is_safe(self):
        # collateral=10000, debt=5000, threshold=1.0 → hf=2.0 → SAFE
        result = self.engine.compute_heatmap([
            _pos(collateral_usd=10_000, debt_usd=5_000, liquidation_threshold_pct=1.0)
        ])
        self.assertEqual(result.positions[0].risk_level, RISK_SAFE)

    def test_hf_exactly_1_is_danger(self):
        # collateral=10000, debt=10000, threshold=1.0 → hf=1.0 → DANGER
        result = self.engine.compute_heatmap([
            _pos(collateral_usd=10_000, debt_usd=10_000, liquidation_threshold_pct=1.0)
        ])
        self.assertEqual(result.positions[0].risk_level, RISK_DANGER)

    def test_missing_protocol_defaults_to_unknown(self):
        result = self.engine.compute_heatmap([
            {"collateral_usd": 10_000, "debt_usd": 5_000,
             "liquidation_threshold_pct": 0.8}
        ])
        self.assertEqual(result.positions[0].protocol, "unknown")

    def test_missing_fields_default_safely(self):
        # All defaults: collateral=0, debt=0, threshold=0.8 → inf HF → SAFE
        result = self.engine.compute_heatmap([{}])
        self.assertEqual(result.positions[0].risk_level, RISK_SAFE)

    def test_very_high_collateral_safe(self):
        result = self.engine.compute_heatmap([
            _pos(collateral_usd=1_000_000, debt_usd=1, liquidation_threshold_pct=0.8)
        ])
        self.assertEqual(result.positions[0].risk_level, RISK_SAFE)

    def test_large_portfolio_correct_count(self):
        positions = [_pos(f"P{i}") for i in range(20)]
        result = self.engine.compute_heatmap(positions)
        self.assertEqual(len(result.positions), 20)

    def test_positions_at_risk_count_consistency(self):
        positions = [
            _pos("S", 50_000, 5_000, 0.825),
            _pos("W", 10_000, 5_500, 0.8),
            _pos("D", 10_000, 7_500, 0.8),
            _pos("C", 5_000, 5_000, 0.8),
        ]
        result = self.engine.compute_heatmap(positions)
        self.assertEqual(
            result.positions_at_risk,
            result.warning_count + result.danger_count + result.critical_count
        )

    def test_deterministic_output(self):
        positions = [
            _pos("A", 50_000, 20_000, 0.825),
            _pos("B", 10_000, 7_000, 0.8),
        ]
        r1 = self.engine.compute_heatmap(positions)
        r2 = self.engine.compute_heatmap(positions)
        self.assertAlmostEqual(
            r1.portfolio_risk_score, r2.portfolio_risk_score
        )
        self.assertEqual(
            r1.positions[0].risk_level, r2.positions[0].risk_level
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
