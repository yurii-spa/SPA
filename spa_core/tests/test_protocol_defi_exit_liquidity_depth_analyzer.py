"""
Tests for MP-1121: ProtocolDeFiExitLiquidityDepthAnalyzer

Run: python3 -m unittest spa_core.tests.test_protocol_defi_exit_liquidity_depth_analyzer

Covers:
  - compute_position_to_tvl_pct
  - compute_position_to_daily_volume_pct
  - compute_estimated_slippage_pct (sqrt heuristic, cap at 20%)
  - compute_estimated_exit_cost_usd
  - compute_recommended_exit_chunks
  - compute_exit_time_hours
  - get_urgency_factor (all 4 urgency levels + unknown)
  - get_liquidity_label (all 5 labels, boundaries)
  - ProtocolDeFiExitLiquidityDepthAnalyzer.analyze() (comprehensive)
  - save_result() (atomic write, ring-buffer, corruption recovery)
  - Import hygiene (no external deps)
  - Edge cases

Python 3.9 compatible. unittest only (NOT pytest). No network. All I/O in tempdir.
"""

from __future__ import annotations

import ast
import json
import math
import os
import tempfile
import time
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------
from spa_core.analytics.protocol_defi_exit_liquidity_depth_analyzer import (
    ProtocolDeFiExitLiquidityDepthAnalyzer,
    RING_BUFFER_CAP,
    LABEL_DEEP_LIQUIDITY,
    LABEL_GOOD_LIQUIDITY,
    LABEL_ADEQUATE_LIQUIDITY,
    LABEL_THIN_LIQUIDITY,
    LABEL_EXIT_TRAP,
    THRESHOLD_DEEP,
    THRESHOLD_GOOD,
    THRESHOLD_ADEQUATE,
    THRESHOLD_THIN,
    MAX_SLIPPAGE_PCT,
    URGENCY_FACTORS,
    DEFAULT_URGENCY_FACTOR,
    VALID_PROTOCOL_TYPES,
    compute_position_to_tvl_pct,
    compute_position_to_daily_volume_pct,
    compute_estimated_slippage_pct,
    compute_estimated_exit_cost_usd,
    compute_recommended_exit_chunks,
    compute_exit_time_hours,
    get_urgency_factor,
    get_liquidity_label,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = (
    _REPO_ROOT / "spa_core" / "analytics"
    / "protocol_defi_exit_liquidity_depth_analyzer.py"
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_analyzer(tmp_dir: str) -> ProtocolDeFiExitLiquidityDepthAnalyzer:
    log_file = os.path.join(tmp_dir, "exit_liquidity_depth_log.json")
    return ProtocolDeFiExitLiquidityDepthAnalyzer(data_file=log_file)


def _basic_analyze(analyzer: ProtocolDeFiExitLiquidityDepthAnalyzer, **overrides) -> dict:
    """Return an analyze result with sensible defaults, allowing key overrides."""
    defaults = dict(
        position_size_usd=10_000.0,
        pool_tvl_usd=1_000_000.0,
        daily_volume_usd=500_000.0,
        exit_urgency="within_day",
        protocol_type="amm",
        withdrawal_queue_hours=0.0,
        protocol_name="TestPool",
    )
    defaults.update(overrides)
    return analyzer.analyze(**defaults)


# ===========================================================================
# 1. compute_position_to_tvl_pct
# ===========================================================================

class TestComputePositionToTvlPct(unittest.TestCase):

    def test_zero_tvl_returns_zero(self):
        self.assertEqual(compute_position_to_tvl_pct(10_000, 0), 0.0)

    def test_negative_tvl_returns_zero(self):
        self.assertEqual(compute_position_to_tvl_pct(10_000, -1), 0.0)

    def test_zero_position(self):
        self.assertEqual(compute_position_to_tvl_pct(0, 1_000_000), 0.0)

    def test_one_percent(self):
        result = compute_position_to_tvl_pct(10_000, 1_000_000)
        self.assertAlmostEqual(result, 1.0, places=6)

    def test_five_percent(self):
        result = compute_position_to_tvl_pct(50_000, 1_000_000)
        self.assertAlmostEqual(result, 5.0, places=6)

    def test_ten_percent(self):
        result = compute_position_to_tvl_pct(100_000, 1_000_000)
        self.assertAlmostEqual(result, 10.0, places=6)

    def test_over_100_percent(self):
        result = compute_position_to_tvl_pct(2_000_000, 1_000_000)
        self.assertAlmostEqual(result, 200.0, places=6)

    def test_small_values(self):
        result = compute_position_to_tvl_pct(0.5, 1000.0)
        self.assertAlmostEqual(result, 0.05, places=6)


# ===========================================================================
# 2. compute_position_to_daily_volume_pct
# ===========================================================================

class TestComputePositionToDailyVolumePct(unittest.TestCase):

    def test_zero_volume_returns_zero(self):
        self.assertEqual(compute_position_to_daily_volume_pct(10_000, 0), 0.0)

    def test_negative_volume_returns_zero(self):
        self.assertEqual(compute_position_to_daily_volume_pct(10_000, -1), 0.0)

    def test_zero_position(self):
        self.assertEqual(compute_position_to_daily_volume_pct(0, 500_000), 0.0)

    def test_two_percent(self):
        result = compute_position_to_daily_volume_pct(10_000, 500_000)
        self.assertAlmostEqual(result, 2.0, places=6)

    def test_fifty_percent(self):
        result = compute_position_to_daily_volume_pct(250_000, 500_000)
        self.assertAlmostEqual(result, 50.0, places=6)

    def test_one_hundred_percent(self):
        result = compute_position_to_daily_volume_pct(500_000, 500_000)
        self.assertAlmostEqual(result, 100.0, places=6)

    def test_over_100_percent(self):
        result = compute_position_to_daily_volume_pct(1_000_000, 500_000)
        self.assertAlmostEqual(result, 200.0, places=6)

    def test_large_values(self):
        result = compute_position_to_daily_volume_pct(1e9, 1e10)
        self.assertAlmostEqual(result, 10.0, places=6)


# ===========================================================================
# 3. compute_estimated_slippage_pct
# ===========================================================================

class TestComputeEstimatedSlippagePct(unittest.TestCase):

    def test_zero_tvl_returns_zero(self):
        self.assertEqual(compute_estimated_slippage_pct(10_000, 0), 0.0)

    def test_zero_position_returns_zero(self):
        self.assertEqual(compute_estimated_slippage_pct(0, 1_000_000), 0.0)

    def test_both_zero_returns_zero(self):
        self.assertEqual(compute_estimated_slippage_pct(0, 0), 0.0)

    def test_one_pct_of_tvl_gives_one_pct_slippage(self):
        # position = 1% of tvl → sqrt(0.01) * 10 = 0.1 * 10 = 1.0
        result = compute_estimated_slippage_pct(10_000, 1_000_000)
        self.assertAlmostEqual(result, 1.0, places=6)

    def test_four_pct_of_tvl_gives_two_pct_slippage(self):
        # sqrt(0.04) * 10 = 0.2 * 10 = 2.0
        result = compute_estimated_slippage_pct(40_000, 1_000_000)
        self.assertAlmostEqual(result, 2.0, places=6)

    def test_25_pct_of_tvl_gives_five_pct_slippage(self):
        # sqrt(0.25) * 10 = 0.5 * 10 = 5.0
        result = compute_estimated_slippage_pct(250_000, 1_000_000)
        self.assertAlmostEqual(result, 5.0, places=6)

    def test_100_pct_of_tvl_gives_ten_pct_slippage(self):
        # sqrt(1.0) * 10 = 10.0
        result = compute_estimated_slippage_pct(1_000_000, 1_000_000)
        self.assertAlmostEqual(result, 10.0, places=6)

    def test_400_pct_of_tvl_capped_at_20(self):
        # sqrt(4.0) * 10 = 20.0 — exactly at cap
        result = compute_estimated_slippage_pct(4_000_000, 1_000_000)
        self.assertAlmostEqual(result, 20.0, places=6)

    def test_over_400_pct_capped_at_20(self):
        # sqrt(10) * 10 > 20 → capped
        result = compute_estimated_slippage_pct(10_000_000, 1_000_000)
        self.assertAlmostEqual(result, 20.0, places=6)

    def test_small_position_tiny_slippage(self):
        # position = 0.01% of tvl → sqrt(0.0001) * 10 = 0.01 * 10 = 0.1
        result = compute_estimated_slippage_pct(100, 1_000_000)
        self.assertAlmostEqual(result, 0.1, places=6)

    def test_result_always_nonnegative(self):
        for pos, tvl in [(0, 1e6), (1, 1e6), (1e6, 1e6), (4e6, 1e6), (1e7, 1e6)]:
            self.assertGreaterEqual(compute_estimated_slippage_pct(pos, tvl), 0.0)

    def test_cap_constant_is_20(self):
        self.assertEqual(MAX_SLIPPAGE_PCT, 20.0)


# ===========================================================================
# 4. compute_estimated_exit_cost_usd
# ===========================================================================

class TestComputeEstimatedExitCostUsd(unittest.TestCase):

    def test_zero_slippage(self):
        self.assertEqual(compute_estimated_exit_cost_usd(100_000, 0.0), 0.0)

    def test_zero_position(self):
        self.assertEqual(compute_estimated_exit_cost_usd(0, 5.0), 0.0)

    def test_one_pct_slippage(self):
        result = compute_estimated_exit_cost_usd(100_000, 1.0)
        self.assertAlmostEqual(result, 1_000.0, places=4)

    def test_five_pct_slippage(self):
        result = compute_estimated_exit_cost_usd(100_000, 5.0)
        self.assertAlmostEqual(result, 5_000.0, places=4)

    def test_twenty_pct_slippage(self):
        result = compute_estimated_exit_cost_usd(100_000, 20.0)
        self.assertAlmostEqual(result, 20_000.0, places=4)

    def test_proportional_to_position(self):
        r1 = compute_estimated_exit_cost_usd(100_000, 2.0)
        r2 = compute_estimated_exit_cost_usd(200_000, 2.0)
        self.assertAlmostEqual(r2, 2 * r1, places=6)

    def test_proportional_to_slippage(self):
        r1 = compute_estimated_exit_cost_usd(50_000, 1.0)
        r2 = compute_estimated_exit_cost_usd(50_000, 4.0)
        self.assertAlmostEqual(r2, 4 * r1, places=6)

    def test_large_values(self):
        result = compute_estimated_exit_cost_usd(1e9, 10.0)
        self.assertAlmostEqual(result, 1e8, places=0)


# ===========================================================================
# 5. compute_recommended_exit_chunks
# ===========================================================================

class TestComputeRecommendedExitChunks(unittest.TestCase):

    def test_zero_pct_returns_one(self):
        self.assertEqual(compute_recommended_exit_chunks(0.0), 1)

    def test_one_pct_returns_one(self):
        self.assertEqual(compute_recommended_exit_chunks(1.0), 1)

    def test_exactly_two_pct_returns_one(self):
        # > 2% threshold, so 2.0 stays at 1
        self.assertEqual(compute_recommended_exit_chunks(2.0), 1)

    def test_just_above_two_pct_returns_two(self):
        # 2.01% → ceil(2.01/2) = ceil(1.005) = 2
        self.assertEqual(compute_recommended_exit_chunks(2.01), 2)

    def test_four_pct_returns_two(self):
        # ceil(4/2) = 2
        self.assertEqual(compute_recommended_exit_chunks(4.0), 2)

    def test_five_pct_returns_three(self):
        # ceil(5/2) = ceil(2.5) = 3
        self.assertEqual(compute_recommended_exit_chunks(5.0), 3)

    def test_ten_pct_returns_five(self):
        # ceil(10/2) = 5
        self.assertEqual(compute_recommended_exit_chunks(10.0), 5)

    def test_fifteen_pct_returns_eight(self):
        # ceil(15/2) = ceil(7.5) = 8
        self.assertEqual(compute_recommended_exit_chunks(15.0), 8)

    def test_twenty_pct_returns_ten(self):
        # ceil(20/2) = 10
        self.assertEqual(compute_recommended_exit_chunks(20.0), 10)

    def test_negative_pct_returns_one(self):
        self.assertEqual(compute_recommended_exit_chunks(-5.0), 1)

    def test_minimum_is_always_one(self):
        for pct in [-10, 0, 0.5, 1.0, 2.0, 2.01, 10, 50]:
            self.assertGreaterEqual(compute_recommended_exit_chunks(pct), 1)

    def test_returns_int(self):
        for pct in [0, 1, 3, 5, 10, 15]:
            self.assertIsInstance(compute_recommended_exit_chunks(pct), int)


# ===========================================================================
# 6. compute_exit_time_hours
# ===========================================================================

class TestComputeExitTimeHours(unittest.TestCase):

    def test_immediate_single_chunk_no_queue(self):
        # 0 + 1 * 0.0 = 0.0
        result = compute_exit_time_hours(0.0, 1, 0.0)
        self.assertAlmostEqual(result, 0.0, places=6)

    def test_within_hour_single_chunk_no_queue(self):
        result = compute_exit_time_hours(0.0, 1, 0.1)
        self.assertAlmostEqual(result, 0.1, places=6)

    def test_within_day_single_chunk_no_queue(self):
        result = compute_exit_time_hours(0.0, 1, 1.0)
        self.assertAlmostEqual(result, 1.0, places=6)

    def test_within_week_single_chunk_no_queue(self):
        result = compute_exit_time_hours(0.0, 1, 24.0)
        self.assertAlmostEqual(result, 24.0, places=6)

    def test_queue_plus_chunks_factor(self):
        result = compute_exit_time_hours(4.0, 3, 2.0)
        # 4 + 3*2 = 10
        self.assertAlmostEqual(result, 10.0, places=6)

    def test_multiple_chunks(self):
        result = compute_exit_time_hours(0.0, 5, 1.0)
        self.assertAlmostEqual(result, 5.0, places=6)

    def test_negative_queue_clamped_to_zero(self):
        result = compute_exit_time_hours(-10.0, 1, 1.0)
        self.assertAlmostEqual(result, 1.0, places=6)

    def test_zero_factor_with_queue(self):
        result = compute_exit_time_hours(6.0, 3, 0.0)
        self.assertAlmostEqual(result, 6.0, places=6)

    def test_large_values(self):
        result = compute_exit_time_hours(100.0, 50, 24.0)
        # 100 + 50*24 = 1300
        self.assertAlmostEqual(result, 1300.0, places=4)

    def test_result_is_nonnegative(self):
        for q, c, f in [(-5, 1, 0), (0, 1, 0), (0, 0, 5), (-100, 10, 0)]:
            self.assertGreaterEqual(compute_exit_time_hours(q, c, f), 0.0)


# ===========================================================================
# 7. get_urgency_factor
# ===========================================================================

class TestGetUrgencyFactor(unittest.TestCase):

    def test_immediate(self):
        self.assertAlmostEqual(get_urgency_factor("immediate"), 0.0, places=6)

    def test_within_hour(self):
        self.assertAlmostEqual(get_urgency_factor("within_hour"), 0.1, places=6)

    def test_within_day(self):
        self.assertAlmostEqual(get_urgency_factor("within_day"), 1.0, places=6)

    def test_within_week(self):
        self.assertAlmostEqual(get_urgency_factor("within_week"), 24.0, places=6)

    def test_unknown_string_returns_default(self):
        result = get_urgency_factor("next_month")
        self.assertEqual(result, DEFAULT_URGENCY_FACTOR)

    def test_empty_string_returns_default(self):
        result = get_urgency_factor("")
        self.assertEqual(result, DEFAULT_URGENCY_FACTOR)

    def test_urgency_factors_dict_has_four_keys(self):
        self.assertEqual(len(URGENCY_FACTORS), 4)

    def test_factors_ordered_ascending(self):
        f = [URGENCY_FACTORS[k] for k in
             ["immediate", "within_hour", "within_day", "within_week"]]
        for i in range(len(f) - 1):
            self.assertLessEqual(f[i], f[i + 1])


# ===========================================================================
# 8. get_liquidity_label
# ===========================================================================

class TestGetLiquidityLabel(unittest.TestCase):

    def test_zero_pct_deep(self):
        self.assertEqual(get_liquidity_label(0.0), LABEL_DEEP_LIQUIDITY)

    def test_below_threshold_deep(self):
        self.assertEqual(get_liquidity_label(0.4), LABEL_DEEP_LIQUIDITY)

    def test_just_below_0_5_deep(self):
        self.assertEqual(get_liquidity_label(0.499), LABEL_DEEP_LIQUIDITY)

    def test_at_0_5_good(self):
        self.assertEqual(get_liquidity_label(0.5), LABEL_GOOD_LIQUIDITY)

    def test_mid_good(self):
        self.assertEqual(get_liquidity_label(1.0), LABEL_GOOD_LIQUIDITY)

    def test_just_below_2_good(self):
        self.assertEqual(get_liquidity_label(1.999), LABEL_GOOD_LIQUIDITY)

    def test_at_2_adequate(self):
        self.assertEqual(get_liquidity_label(2.0), LABEL_ADEQUATE_LIQUIDITY)

    def test_mid_adequate(self):
        self.assertEqual(get_liquidity_label(3.5), LABEL_ADEQUATE_LIQUIDITY)

    def test_just_below_5_adequate(self):
        self.assertEqual(get_liquidity_label(4.999), LABEL_ADEQUATE_LIQUIDITY)

    def test_at_5_thin(self):
        self.assertEqual(get_liquidity_label(5.0), LABEL_THIN_LIQUIDITY)

    def test_mid_thin(self):
        self.assertEqual(get_liquidity_label(10.0), LABEL_THIN_LIQUIDITY)

    def test_just_below_15_thin(self):
        self.assertEqual(get_liquidity_label(14.999), LABEL_THIN_LIQUIDITY)

    def test_at_15_exit_trap(self):
        self.assertEqual(get_liquidity_label(15.0), LABEL_EXIT_TRAP)

    def test_above_15_exit_trap(self):
        self.assertEqual(get_liquidity_label(50.0), LABEL_EXIT_TRAP)

    def test_all_five_labels_returned(self):
        labels = {
            get_liquidity_label(0.0),
            get_liquidity_label(1.0),
            get_liquidity_label(3.0),
            get_liquidity_label(10.0),
            get_liquidity_label(20.0),
        }
        self.assertEqual(
            labels,
            {
                LABEL_DEEP_LIQUIDITY,
                LABEL_GOOD_LIQUIDITY,
                LABEL_ADEQUATE_LIQUIDITY,
                LABEL_THIN_LIQUIDITY,
                LABEL_EXIT_TRAP,
            },
        )

    def test_negative_pct_returns_deep(self):
        # negative position_to_tvl is unusual but should not crash
        self.assertEqual(get_liquidity_label(-1.0), LABEL_DEEP_LIQUIDITY)


# ===========================================================================
# 9. ProtocolDeFiExitLiquidityDepthAnalyzer.analyze()
# ===========================================================================

class TestProtocolDeFiExitLiquidityDepthAnalyzerAnalyze(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = _make_analyzer(self.tmp)

    # --- Return type and keys ---

    def test_returns_dict(self):
        result = _basic_analyze(self.analyzer)
        self.assertIsInstance(result, dict)

    def test_all_required_keys_present(self):
        result = _basic_analyze(self.analyzer)
        expected_keys = {
            "protocol_name", "protocol_type", "exit_urgency",
            "position_size_usd", "pool_tvl_usd", "daily_volume_usd",
            "withdrawal_queue_hours", "position_to_tvl_pct",
            "position_to_daily_volume_pct", "estimated_slippage_pct",
            "estimated_exit_cost_usd", "recommended_exit_chunks",
            "exit_time_hours", "liquidity_label", "run_ts",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_protocol_name_stored(self):
        result = _basic_analyze(self.analyzer, protocol_name="UniV3")
        self.assertEqual(result["protocol_name"], "UniV3")

    def test_protocol_type_stored(self):
        result = _basic_analyze(self.analyzer, protocol_type="lending")
        self.assertEqual(result["protocol_type"], "lending")

    def test_exit_urgency_stored(self):
        result = _basic_analyze(self.analyzer, exit_urgency="within_week")
        self.assertEqual(result["exit_urgency"], "within_week")

    def test_withdrawal_queue_stored(self):
        result = _basic_analyze(self.analyzer, withdrawal_queue_hours=48.0)
        self.assertAlmostEqual(result["withdrawal_queue_hours"], 48.0, places=6)

    def test_run_ts_is_float(self):
        t_before = time.time()
        result = _basic_analyze(self.analyzer)
        t_after = time.time()
        self.assertGreaterEqual(result["run_ts"], t_before)
        self.assertLessEqual(result["run_ts"], t_after)

    def test_liquidity_label_is_str(self):
        result = _basic_analyze(self.analyzer)
        self.assertIsInstance(result["liquidity_label"], str)

    def test_recommended_exit_chunks_is_int(self):
        result = _basic_analyze(self.analyzer)
        self.assertIsInstance(result["recommended_exit_chunks"], int)

    # --- Label scenarios ---

    def test_deep_liquidity_scenario(self):
        # 0.1% of TVL → DEEP
        result = self.analyzer.analyze(
            position_size_usd=1_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=500_000,
            exit_urgency="within_day",
            protocol_type="amm",
            withdrawal_queue_hours=0.0,
            protocol_name="UniV3",
        )
        self.assertEqual(result["liquidity_label"], LABEL_DEEP_LIQUIDITY)

    def test_good_liquidity_scenario(self):
        # 1% of TVL → GOOD
        result = self.analyzer.analyze(
            position_size_usd=10_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=500_000,
            exit_urgency="within_day",
            protocol_type="amm",
            withdrawal_queue_hours=0.0,
        )
        self.assertEqual(result["liquidity_label"], LABEL_GOOD_LIQUIDITY)

    def test_adequate_liquidity_scenario(self):
        # 3% of TVL → ADEQUATE
        result = self.analyzer.analyze(
            position_size_usd=30_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=500_000,
            exit_urgency="within_day",
            protocol_type="lending",
            withdrawal_queue_hours=0.0,
        )
        self.assertEqual(result["liquidity_label"], LABEL_ADEQUATE_LIQUIDITY)

    def test_thin_liquidity_scenario(self):
        # 10% of TVL → THIN
        result = self.analyzer.analyze(
            position_size_usd=100_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=500_000,
            exit_urgency="within_week",
            protocol_type="vault",
            withdrawal_queue_hours=0.0,
        )
        self.assertEqual(result["liquidity_label"], LABEL_THIN_LIQUIDITY)

    def test_exit_trap_scenario(self):
        # 20% of TVL → EXIT_TRAP
        result = self.analyzer.analyze(
            position_size_usd=200_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=100_000,
            exit_urgency="within_week",
            protocol_type="staking",
            withdrawal_queue_hours=72.0,
        )
        self.assertEqual(result["liquidity_label"], LABEL_EXIT_TRAP)

    # --- Slippage formula verification ---

    def test_slippage_sqrt_formula_verified(self):
        # 1% of TVL → sqrt(0.01)*10 = 1.0%
        result = self.analyzer.analyze(
            position_size_usd=10_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=500_000,
            exit_urgency="immediate",
            protocol_type="amm",
            withdrawal_queue_hours=0.0,
        )
        self.assertAlmostEqual(result["estimated_slippage_pct"], 1.0, places=4)

    def test_slippage_capped_at_20(self):
        # Very large position → slippage capped at 20%
        result = self.analyzer.analyze(
            position_size_usd=100_000_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=500_000,
            exit_urgency="within_week",
            protocol_type="amm",
            withdrawal_queue_hours=0.0,
        )
        self.assertAlmostEqual(result["estimated_slippage_pct"], 20.0, places=4)

    # --- Exit cost ---

    def test_estimated_exit_cost_correct(self):
        result = _basic_analyze(self.analyzer,
                                position_size_usd=100_000,
                                pool_tvl_usd=10_000_000)  # 1% → slippage 1%
        expected_cost = 100_000 * 1.0 / 100
        self.assertAlmostEqual(result["estimated_exit_cost_usd"], expected_cost, places=2)

    # --- Chunks ---

    def test_recommended_chunks_one_for_deep(self):
        result = _basic_analyze(self.analyzer,
                                position_size_usd=1_000,
                                pool_tvl_usd=1_000_000)  # 0.1% → 1 chunk
        self.assertEqual(result["recommended_exit_chunks"], 1)

    def test_recommended_chunks_multiple_for_large(self):
        result = _basic_analyze(self.analyzer,
                                position_size_usd=100_000,
                                pool_tvl_usd=1_000_000)  # 10% → ceil(10/2)=5 chunks
        self.assertEqual(result["recommended_exit_chunks"], 5)

    # --- Exit time / urgency ---

    def test_immediate_urgency_with_queue_equals_queue(self):
        # immediate → factor=0, so exit_time = queue + chunks*0 = queue
        result = self.analyzer.analyze(
            position_size_usd=1_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=500_000,
            exit_urgency="immediate",
            protocol_type="lending",
            withdrawal_queue_hours=8.0,
        )
        self.assertAlmostEqual(result["exit_time_hours"], 8.0, places=4)

    def test_within_hour_urgency_single_chunk(self):
        result = self.analyzer.analyze(
            position_size_usd=1_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=500_000,
            exit_urgency="within_hour",
            protocol_type="amm",
            withdrawal_queue_hours=0.0,
        )
        # 0 + 1*0.1 = 0.1
        self.assertAlmostEqual(result["exit_time_hours"], 0.1, places=4)

    def test_within_day_urgency_single_chunk(self):
        result = _basic_analyze(self.analyzer,
                                position_size_usd=1_000,
                                pool_tvl_usd=1_000_000,
                                exit_urgency="within_day",
                                withdrawal_queue_hours=0.0)
        # 1 chunk, factor=1 → 0 + 1*1 = 1.0
        self.assertAlmostEqual(result["exit_time_hours"], 1.0, places=4)

    def test_within_week_urgency_single_chunk(self):
        result = _basic_analyze(self.analyzer,
                                position_size_usd=1_000,
                                pool_tvl_usd=1_000_000,
                                exit_urgency="within_week",
                                withdrawal_queue_hours=0.0)
        self.assertAlmostEqual(result["exit_time_hours"], 24.0, places=4)

    def test_exit_time_with_queue_and_chunks(self):
        # 10% TVL → 5 chunks, within_day → factor=1, queue=24
        result = self.analyzer.analyze(
            position_size_usd=100_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=500_000,
            exit_urgency="within_day",
            protocol_type="vault",
            withdrawal_queue_hours=24.0,
        )
        self.assertAlmostEqual(result["exit_time_hours"], 24.0 + 5 * 1.0, places=4)

    # --- Protocol types ---

    def test_amm_protocol_type_stored(self):
        r = _basic_analyze(self.analyzer, protocol_type="amm")
        self.assertEqual(r["protocol_type"], "amm")

    def test_lending_protocol_type_stored(self):
        r = _basic_analyze(self.analyzer, protocol_type="lending")
        self.assertEqual(r["protocol_type"], "lending")

    def test_vault_protocol_type_stored(self):
        r = _basic_analyze(self.analyzer, protocol_type="vault")
        self.assertEqual(r["protocol_type"], "vault")

    def test_staking_protocol_type_stored(self):
        r = _basic_analyze(self.analyzer, protocol_type="staking")
        self.assertEqual(r["protocol_type"], "staking")

    # --- Numeric output rounding ---

    def test_rounded_outputs_to_6_places(self):
        result = _basic_analyze(self.analyzer)
        for key in [
            "position_to_tvl_pct", "position_to_daily_volume_pct",
            "estimated_slippage_pct", "estimated_exit_cost_usd", "exit_time_hours",
        ]:
            val = result[key]
            self.assertAlmostEqual(val, round(val, 6), places=9)

    # --- Float coercion ---

    def test_float_coercion_from_int_inputs(self):
        result = self.analyzer.analyze(
            position_size_usd=10_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=500_000,
            exit_urgency="within_day",
            protocol_type="amm",
            withdrawal_queue_hours=0,
        )
        self.assertIsInstance(result["position_size_usd"], float)
        self.assertIsInstance(result["pool_tvl_usd"], float)

    def test_default_protocol_name(self):
        result = self.analyzer.analyze(
            10_000, 1_000_000, 500_000, "within_day", "amm", 0.0
        )
        self.assertEqual(result["protocol_name"], "unknown")

    # --- Zero tvl / volume edge cases ---

    def test_zero_tvl_all_tvl_outputs_zero(self):
        result = self.analyzer.analyze(
            10_000, 0, 500_000, "within_day", "amm", 0.0
        )
        self.assertAlmostEqual(result["position_to_tvl_pct"], 0.0, places=6)
        self.assertAlmostEqual(result["estimated_slippage_pct"], 0.0, places=6)

    def test_zero_volume_vol_pct_zero(self):
        result = self.analyzer.analyze(
            10_000, 1_000_000, 0, "within_day", "amm", 0.0
        )
        self.assertAlmostEqual(result["position_to_daily_volume_pct"], 0.0, places=6)


# ===========================================================================
# 10. save_result()
# ===========================================================================

class TestSaveResult(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_file = os.path.join(self.tmp, "exit_liq.json")
        self.analyzer = ProtocolDeFiExitLiquidityDepthAnalyzer(data_file=self.log_file)

    def _result(self, tag: str = "p") -> dict:
        return _basic_analyze(self.analyzer, protocol_name=tag)

    def test_creates_file_if_not_exist(self):
        self.assertFalse(os.path.exists(self.log_file))
        self.analyzer.save_result(self._result("a"))
        self.assertTrue(os.path.exists(self.log_file))

    def test_saved_data_is_list(self):
        self.analyzer.save_result(self._result("b"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_appends_to_existing(self):
        self.analyzer.save_result(self._result("c1"))
        self.analyzer.save_result(self._result("c2"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap_enforced(self):
        for i in range(RING_BUFFER_CAP + 10):
            self.analyzer.save_result(self._result(f"r{i}"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), RING_BUFFER_CAP)

    def test_ring_buffer_keeps_latest(self):
        for i in range(RING_BUFFER_CAP + 5):
            self.analyzer.save_result(self._result(f"p{i}"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(data[-1]["protocol_name"], f"p{RING_BUFFER_CAP + 4}")

    def test_atomic_write_produces_valid_json(self):
        self.analyzer.save_result(self._result("atomic"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_corrupted_file_recovered(self):
        with open(self.log_file, "w") as f:
            f.write("{broken json")
        self.analyzer.save_result(self._result("recover"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_non_list_json_recovered(self):
        with open(self.log_file, "w") as f:
            json.dump({"key": "val"}, f)
        self.analyzer.save_result(self._result("nonlist"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_empty_list_file_appended(self):
        with open(self.log_file, "w") as f:
            json.dump([], f)
        self.analyzer.save_result(self._result("empty"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_data_dir_created_if_missing(self):
        deep_dir = os.path.join(self.tmp, "nested", "deep")
        log_file = os.path.join(deep_dir, "test.json")
        analyzer = ProtocolDeFiExitLiquidityDepthAnalyzer(data_file=log_file)
        analyzer.save_result(self._result("deep"))
        self.assertTrue(os.path.exists(log_file))

    def test_multiple_sequential_saves(self):
        for i in range(7):
            self.analyzer.save_result(self._result(f"seq{i}"))
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(len(data), 7)

    def test_saved_result_preserves_protocol_name(self):
        r = _basic_analyze(self.analyzer, protocol_name="Curve3Pool")
        self.analyzer.save_result(r)
        with open(self.log_file) as f:
            data = json.load(f)
        self.assertEqual(data[0]["protocol_name"], "Curve3Pool")


# ===========================================================================
# 11. Import hygiene — no external dependencies
# ===========================================================================

class TestImportHygiene(unittest.TestCase):

    def test_module_file_exists(self):
        self.assertTrue(_MODULE_PATH.exists(), f"Module not found: {_MODULE_PATH}")

    def test_no_external_imports(self):
        stdlib_modules = {
            "json", "math", "os", "tempfile", "time",
            "typing", "__future__", "abc", "collections",
            "functools", "itertools", "re", "sys",
            # Internal project modules are allowed (not external pip packages)
            "spa_core",
        }
        source = _MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                else:
                    names = [node.module.split(".")[0]] if node.module else []
                for name in names:
                    self.assertIn(
                        name, stdlib_modules,
                        f"External import detected: {name}"
                    )

    def test_class_instantiable_with_custom_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = ProtocolDeFiExitLiquidityDepthAnalyzer(
                data_file=os.path.join(tmp, "tmp.json")
            )
            self.assertIsInstance(a, ProtocolDeFiExitLiquidityDepthAnalyzer)

    def test_constants_exported(self):
        from spa_core.analytics import protocol_defi_exit_liquidity_depth_analyzer as m
        self.assertEqual(m.RING_BUFFER_CAP, 100)
        self.assertEqual(m.MAX_SLIPPAGE_PCT, 20.0)
        self.assertIn("immediate", m.URGENCY_FACTORS)


# ===========================================================================
# 12. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = _make_analyzer(self.tmp)

    def test_very_large_position_in_tiny_pool_exit_trap(self):
        result = self.analyzer.analyze(
            position_size_usd=1_000_000,
            pool_tvl_usd=100_000,
            daily_volume_usd=50_000,
            exit_urgency="within_week",
            protocol_type="vault",
            withdrawal_queue_hours=0.0,
        )
        self.assertEqual(result["liquidity_label"], LABEL_EXIT_TRAP)
        self.assertAlmostEqual(result["estimated_slippage_pct"], 20.0, places=4)

    def test_tiny_position_huge_pool_deep_liquidity(self):
        result = self.analyzer.analyze(
            position_size_usd=100,
            pool_tvl_usd=1_000_000_000,
            daily_volume_usd=500_000_000,
            exit_urgency="immediate",
            protocol_type="amm",
            withdrawal_queue_hours=0.0,
        )
        self.assertEqual(result["liquidity_label"], LABEL_DEEP_LIQUIDITY)

    def test_zero_volume_returns_valid_result(self):
        result = self.analyzer.analyze(
            position_size_usd=10_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=0,
            exit_urgency="within_day",
            protocol_type="staking",
            withdrawal_queue_hours=0.0,
        )
        self.assertAlmostEqual(result["position_to_daily_volume_pct"], 0.0, places=6)

    def test_very_long_queue_dominates_exit_time(self):
        # Single chunk, immediate urgency, 1000h queue
        result = self.analyzer.analyze(
            position_size_usd=1_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=500_000,
            exit_urgency="immediate",
            protocol_type="staking",
            withdrawal_queue_hours=1000.0,
        )
        self.assertAlmostEqual(result["exit_time_hours"], 1000.0, places=4)

    def test_unknown_urgency_uses_default_factor(self):
        result1 = self.analyzer.analyze(
            position_size_usd=1_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=500_000,
            exit_urgency="unknown_urgency",
            protocol_type="amm",
            withdrawal_queue_hours=0.0,
        )
        # 1 chunk * DEFAULT_URGENCY_FACTOR(1.0) = 1.0
        self.assertAlmostEqual(result1["exit_time_hours"], DEFAULT_URGENCY_FACTOR, places=4)

    def test_chunks_minimum_one(self):
        result = self.analyzer.analyze(
            position_size_usd=0.01,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=500_000,
            exit_urgency="within_day",
            protocol_type="amm",
            withdrawal_queue_hours=0.0,
        )
        self.assertGreaterEqual(result["recommended_exit_chunks"], 1)

    def test_negative_queue_clamped_in_analyze(self):
        result = self.analyzer.analyze(
            position_size_usd=1_000,
            pool_tvl_usd=1_000_000,
            daily_volume_usd=500_000,
            exit_urgency="within_day",
            protocol_type="amm",
            withdrawal_queue_hours=-10.0,
        )
        # queue clamped → 0, so exit_time = 0 + 1*1.0 = 1.0
        self.assertAlmostEqual(result["exit_time_hours"], 1.0, places=4)

    def test_analyze_is_deterministic(self):
        r1 = _basic_analyze(self.analyzer)
        r2 = _basic_analyze(self.analyzer)
        self.assertEqual(r1["position_to_tvl_pct"], r2["position_to_tvl_pct"])
        self.assertEqual(r1["estimated_slippage_pct"], r2["estimated_slippage_pct"])
        self.assertEqual(r1["liquidity_label"], r2["liquidity_label"])
        self.assertEqual(r1["recommended_exit_chunks"], r2["recommended_exit_chunks"])


if __name__ == "__main__":
    unittest.main()
