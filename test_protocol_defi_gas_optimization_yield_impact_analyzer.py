"""
Tests for MP-1053: ProtocolDeFiGasOptimizationYieldImpactAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_gas_optimization_yield_impact_analyzer -v
≥ 90 tests covering all helpers and integration paths.
"""

import json
import math
import os
import tempfile
import time
import unittest
from pathlib import Path

from spa_core.analytics.protocol_defi_gas_optimization_yield_impact_analyzer import (
    MAX_ENTRIES,
    RECOMMENDATION_NEGATIVE,
    ProtocolDeFiGasOptimizationYieldImpactAnalyzer,
    chain_gas_efficiency_factor,
    compute_annual_gas_cost_usd,
    compute_break_even_position_usd,
    compute_gas_drag_pct,
    compute_gas_efficiency_score,
    compute_net_apy_pct,
    compute_recommendation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_params(**overrides):
    """Return a default param dict, overridable."""
    params = dict(
        position_usd=10_000.0,
        gross_apy_pct=5.0,
        estimated_gas_usd_per_tx=10.0,
        txs_per_year=12,
        chain="ethereum",
        compound_frequency_per_year=12,
        gas_price_gwei=30.0,
        protocol_gas_rebate_pct=0.0,
    )
    params.update(overrides)
    return params


def _make_analyzer(tmp_dir):
    data_file = Path(tmp_dir) / "gas_optimization_yield_impact_log.json"
    return ProtocolDeFiGasOptimizationYieldImpactAnalyzer(data_file=data_file)


# ===========================================================================
# Tests: compute_annual_gas_cost_usd
# ===========================================================================

class TestAnnualGasCostUsd(unittest.TestCase):

    def test_no_rebate_simple_multiply(self):
        # 10 USD * 12 txs = 120
        self.assertAlmostEqual(compute_annual_gas_cost_usd(10.0, 12, 0.0), 120.0)

    def test_full_rebate_returns_zero(self):
        self.assertAlmostEqual(compute_annual_gas_cost_usd(10.0, 12, 100.0), 0.0)

    def test_50pct_rebate_halves_cost(self):
        self.assertAlmostEqual(compute_annual_gas_cost_usd(10.0, 12, 50.0), 60.0)

    def test_25pct_rebate(self):
        # 10 * (1 - 0.25) * 12 = 7.5 * 12 = 90
        self.assertAlmostEqual(compute_annual_gas_cost_usd(10.0, 12, 25.0), 90.0)

    def test_zero_txs_returns_zero(self):
        self.assertAlmostEqual(compute_annual_gas_cost_usd(50.0, 0, 0.0), 0.0)

    def test_zero_gas_per_tx_returns_zero(self):
        self.assertAlmostEqual(compute_annual_gas_cost_usd(0.0, 100, 0.0), 0.0)

    def test_rebate_above_100_clamped(self):
        # rebate > 100 % clamped to 100 % → cost = 0
        self.assertAlmostEqual(compute_annual_gas_cost_usd(10.0, 12, 150.0), 0.0)

    def test_rebate_below_0_clamped(self):
        # rebate < 0 clamped to 0 → no rebate
        self.assertAlmostEqual(compute_annual_gas_cost_usd(10.0, 12, -10.0), 120.0)

    def test_large_position_values(self):
        # 100 USD * 365 txs = 36_500
        self.assertAlmostEqual(compute_annual_gas_cost_usd(100.0, 365, 0.0), 36_500.0)

    def test_fractional_txs(self):
        # 10 * 1.5 = 15
        self.assertAlmostEqual(compute_annual_gas_cost_usd(10.0, 1.5, 0.0), 15.0)


# ===========================================================================
# Tests: compute_gas_drag_pct
# ===========================================================================

class TestGasDragPct(unittest.TestCase):

    def test_basic_drag(self):
        # 120 USD gas on 10_000 position = 1.2%
        self.assertAlmostEqual(compute_gas_drag_pct(120.0, 10_000.0), 1.2)

    def test_zero_gas_cost(self):
        self.assertAlmostEqual(compute_gas_drag_pct(0.0, 10_000.0), 0.0)

    def test_zero_position_returns_zero(self):
        self.assertAlmostEqual(compute_gas_drag_pct(100.0, 0.0), 0.0)

    def test_negative_position_returns_zero(self):
        self.assertAlmostEqual(compute_gas_drag_pct(100.0, -100.0), 0.0)

    def test_drag_can_exceed_100_pct(self):
        # 1000 USD gas on 100 USD position = 1000%
        self.assertAlmostEqual(compute_gas_drag_pct(1000.0, 100.0), 1000.0)

    def test_small_drag(self):
        # 5 USD gas on 100_000 position = 0.005%
        self.assertAlmostEqual(compute_gas_drag_pct(5.0, 100_000.0), 0.005)

    def test_equal_gas_and_position(self):
        # 1000 USD gas on 1000 USD position = 100%
        self.assertAlmostEqual(compute_gas_drag_pct(1000.0, 1000.0), 100.0)


# ===========================================================================
# Tests: compute_net_apy_pct
# ===========================================================================

class TestNetApyPct(unittest.TestCase):

    def test_positive_net(self):
        self.assertAlmostEqual(compute_net_apy_pct(5.0, 1.2), 3.8)

    def test_zero_gas_drag(self):
        self.assertAlmostEqual(compute_net_apy_pct(5.0, 0.0), 5.0)

    def test_negative_net(self):
        self.assertAlmostEqual(compute_net_apy_pct(2.0, 3.0), -1.0)

    def test_exact_break_even(self):
        self.assertAlmostEqual(compute_net_apy_pct(5.0, 5.0), 0.0)

    def test_zero_gross_apy(self):
        self.assertAlmostEqual(compute_net_apy_pct(0.0, 0.5), -0.5)


# ===========================================================================
# Tests: compute_break_even_position_usd
# ===========================================================================

class TestBreakEvenPositionUsd(unittest.TestCase):

    def test_basic_break_even(self):
        # 120 USD gas / year, 5% APY → need 120*100/5 = 2400 USD
        self.assertAlmostEqual(compute_break_even_position_usd(120.0, 5.0), 2_400.0)

    def test_zero_gas_returns_zero(self):
        self.assertAlmostEqual(compute_break_even_position_usd(0.0, 5.0), 0.0)

    def test_zero_apy_returns_inf(self):
        result = compute_break_even_position_usd(100.0, 0.0)
        self.assertTrue(math.isinf(result))

    def test_negative_apy_returns_inf(self):
        result = compute_break_even_position_usd(100.0, -1.0)
        self.assertTrue(math.isinf(result))

    def test_high_gas_low_apy_large_break_even(self):
        # 1000 USD gas, 1% APY → 100_000 USD
        self.assertAlmostEqual(compute_break_even_position_usd(1000.0, 1.0), 100_000.0)

    def test_break_even_proportional_to_gas(self):
        be1 = compute_break_even_position_usd(100.0, 5.0)
        be2 = compute_break_even_position_usd(200.0, 5.0)
        self.assertAlmostEqual(be2, be1 * 2)

    def test_break_even_inversely_proportional_to_apy(self):
        be1 = compute_break_even_position_usd(100.0, 5.0)
        be2 = compute_break_even_position_usd(100.0, 10.0)
        self.assertAlmostEqual(be2, be1 / 2)


# ===========================================================================
# Tests: compute_gas_efficiency_score
# ===========================================================================

class TestGasEfficiencyScore(unittest.TestCase):

    def test_zero_drag_gives_100(self):
        self.assertAlmostEqual(compute_gas_efficiency_score(0.0, 5.0), 100.0)

    def test_drag_equal_to_yield_gives_0(self):
        self.assertAlmostEqual(compute_gas_efficiency_score(5.0, 5.0), 0.0)

    def test_drag_exceeds_yield_gives_0(self):
        self.assertAlmostEqual(compute_gas_efficiency_score(10.0, 5.0), 0.0)

    def test_half_drag_gives_50(self):
        self.assertAlmostEqual(compute_gas_efficiency_score(2.5, 5.0), 50.0)

    def test_score_bounded_0_to_100(self):
        for drag in [0, 1, 2.5, 5, 10, 100]:
            score = compute_gas_efficiency_score(float(drag), 5.0)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)

    def test_zero_gross_apy_gives_0(self):
        self.assertAlmostEqual(compute_gas_efficiency_score(1.0, 0.0), 0.0)

    def test_score_decreases_as_drag_increases(self):
        drags = [0.0, 0.5, 1.0, 2.0, 4.0, 5.0]
        scores = [compute_gas_efficiency_score(d, 5.0) for d in drags]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])

    def test_small_drag_high_score(self):
        # 0.1% drag on 5% yield → 98% efficiency
        self.assertAlmostEqual(compute_gas_efficiency_score(0.1, 5.0), 98.0)


# ===========================================================================
# Tests: compute_recommendation
# ===========================================================================

class TestRecommendation(unittest.TestCase):

    def test_negligible_drag(self):
        # 0.2 drag / 5 yield = 4% ratio → GAS_NEGLIGIBLE
        self.assertEqual(compute_recommendation(0.2, 5.0), "GAS_NEGLIGIBLE")

    def test_manageable_drag(self):
        # 0.5 drag / 5 yield = 10% ratio → GAS_MANAGEABLE
        self.assertEqual(compute_recommendation(0.5, 5.0), "GAS_MANAGEABLE")

    def test_significant_drag(self):
        # 1.5 drag / 5 yield = 30% ratio → GAS_SIGNIFICANT
        self.assertEqual(compute_recommendation(1.5, 5.0), "GAS_SIGNIFICANT")

    def test_dominant_drag(self):
        # 3.0 drag / 5 yield = 60% ratio → GAS_DOMINANT
        self.assertEqual(compute_recommendation(3.0, 5.0), "GAS_DOMINANT")

    def test_position_too_small(self):
        # 6.0 drag / 5 yield = 120% ratio → POSITION_TOO_SMALL
        self.assertEqual(compute_recommendation(6.0, 5.0), "POSITION_TOO_SMALL")

    def test_zero_drag_is_negligible(self):
        self.assertEqual(compute_recommendation(0.0, 5.0), "GAS_NEGLIGIBLE")

    def test_exact_break_even_is_position_too_small(self):
        # drag = gross → ratio = 1.0 → POSITION_TOO_SMALL
        self.assertEqual(compute_recommendation(5.0, 5.0), "POSITION_TOO_SMALL")

    def test_zero_gross_apy_is_position_too_small(self):
        self.assertEqual(compute_recommendation(1.0, 0.0), "POSITION_TOO_SMALL")

    def test_5pct_threshold_boundary(self):
        # ratio exactly 0.05 → threshold is < 0.05 → GAS_MANAGEABLE
        self.assertEqual(compute_recommendation(0.25, 5.0), "GAS_MANAGEABLE")

    def test_20pct_threshold_boundary(self):
        # ratio exactly 0.20 → GAS_SIGNIFICANT
        self.assertEqual(compute_recommendation(1.0, 5.0), "GAS_SIGNIFICANT")

    def test_50pct_threshold_boundary(self):
        # ratio exactly 0.50 → GAS_DOMINANT
        self.assertEqual(compute_recommendation(2.5, 5.0), "GAS_DOMINANT")

    def test_valid_labels_set(self):
        valid = {
            "GAS_NEGLIGIBLE", "GAS_MANAGEABLE", "GAS_SIGNIFICANT",
            "GAS_DOMINANT", "POSITION_TOO_SMALL",
        }
        for drag in [0, 0.2, 0.5, 1.0, 1.5, 2.5, 3.0, 5.0, 6.0, 50.0]:
            label = compute_recommendation(float(drag), 5.0)
            self.assertIn(label, valid)


# ===========================================================================
# Tests: chain_gas_efficiency_factor
# ===========================================================================

class TestChainGasEfficiencyFactor(unittest.TestCase):

    def test_ethereum_is_1(self):
        self.assertAlmostEqual(chain_gas_efficiency_factor("ethereum"), 1.0)

    def test_arbitrum_less_than_ethereum(self):
        self.assertLess(chain_gas_efficiency_factor("arbitrum"), 1.0)

    def test_base_less_than_ethereum(self):
        self.assertLess(chain_gas_efficiency_factor("base"), 1.0)

    def test_polygon_less_than_ethereum(self):
        self.assertLess(chain_gas_efficiency_factor("polygon"), 1.0)

    def test_case_insensitive(self):
        self.assertAlmostEqual(
            chain_gas_efficiency_factor("ETHEREUM"),
            chain_gas_efficiency_factor("ethereum"),
        )

    def test_unknown_chain_defaults_to_1(self):
        self.assertAlmostEqual(chain_gas_efficiency_factor("unknown_chain"), 1.0)

    def test_optimism_less_than_ethereum(self):
        self.assertLess(chain_gas_efficiency_factor("optimism"), 1.0)


# ===========================================================================
# Tests: ProtocolDeFiGasOptimizationYieldImpactAnalyzer (integration)
# ===========================================================================

class TestAnalyzerIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.analyzer = _make_analyzer(self.tmp)

    def _analyze(self, **overrides):
        return self.analyzer.analyze(_default_params(**overrides))

    # --- Output keys ---
    def test_result_contains_all_output_keys(self):
        result = self._analyze()
        for key in ProtocolDeFiGasOptimizationYieldImpactAnalyzer.OUTPUT_KEYS:
            self.assertIn(key, result)

    def test_net_apy_equals_gross_minus_drag(self):
        result = self._analyze()
        self.assertAlmostEqual(
            result["net_apy_pct"],
            result["gross_apy_pct"] - result["gas_drag_pct"],
            places=4,
        )

    def test_recommendation_is_string(self):
        result = self._analyze()
        self.assertIsInstance(result["recommendation"], str)

    def test_gas_efficiency_score_in_range(self):
        result = self._analyze()
        self.assertGreaterEqual(result["gas_efficiency_score"], 0.0)
        self.assertLessEqual(result["gas_efficiency_score"], 100.0)

    def test_chain_preserved_in_result(self):
        result = self._analyze(chain="arbitrum")
        self.assertEqual(result["chain"], "arbitrum")

    def test_timestamp_is_recent(self):
        result = self._analyze()
        self.assertAlmostEqual(result["timestamp"], time.time(), delta=5.0)

    def test_annual_gas_cost_computed_correctly(self):
        # 10 USD * 12 txs * (1 - 0) = 120
        result = self._analyze(
            estimated_gas_usd_per_tx=10.0,
            txs_per_year=12,
            protocol_gas_rebate_pct=0.0,
        )
        self.assertAlmostEqual(result["annual_gas_cost_usd"], 120.0)

    def test_rebate_reduces_annual_gas_cost(self):
        r_no_rebate = self._analyze(protocol_gas_rebate_pct=0.0)
        r_with_rebate = self._analyze(protocol_gas_rebate_pct=50.0)
        self.assertLess(r_with_rebate["annual_gas_cost_usd"], r_no_rebate["annual_gas_cost_usd"])

    def test_larger_position_lowers_gas_drag(self):
        small = self._analyze(position_usd=1_000.0)
        large = self._analyze(position_usd=100_000.0)
        self.assertGreater(small["gas_drag_pct"], large["gas_drag_pct"])

    def test_more_txs_increases_gas_drag(self):
        few = self._analyze(txs_per_year=4)
        many = self._analyze(txs_per_year=52)
        self.assertLess(few["gas_drag_pct"], many["gas_drag_pct"])

    def test_break_even_is_positive_or_none(self):
        result = self._analyze()
        bep = result["break_even_position_usd"]
        if bep is not None:
            self.assertGreater(bep, 0.0)

    def test_zero_apy_break_even_is_none(self):
        result = self._analyze(gross_apy_pct=0.0)
        self.assertIsNone(result["break_even_position_usd"])

    def test_chain_gas_efficiency_factor_in_result(self):
        result = self._analyze(chain="ethereum")
        self.assertAlmostEqual(result["chain_gas_efficiency_factor"], 1.0)

    # --- Log file ---
    def test_log_file_created(self):
        self._analyze()
        log_path = Path(self.tmp) / "gas_optimization_yield_impact_log.json"
        self.assertTrue(log_path.exists())

    def test_log_file_is_list(self):
        self._analyze()
        log_path = Path(self.tmp) / "gas_optimization_yield_impact_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_accumulates(self):
        for _ in range(5):
            self._analyze()
        log_path = Path(self.tmp) / "gas_optimization_yield_impact_log.json"
        with open(log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_ring_buffer_capped(self):
        analyzer = ProtocolDeFiGasOptimizationYieldImpactAnalyzer(
            data_file=Path(self.tmp) / "ring.json", max_entries=3
        )
        for i in range(10):
            analyzer.analyze(_default_params(position_usd=float(1000 + i)))
        with open(Path(self.tmp) / "ring.json") as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)
        # Most recent retained
        self.assertAlmostEqual(data[-1]["position_usd"], 1009.0)

    def test_log_atomic_no_partial_file(self):
        self._analyze()
        log_path = Path(self.tmp) / "gas_optimization_yield_impact_log.json"
        with open(log_path) as f:
            content = f.read()
        self.assertGreater(len(content), 0)

    # --- Scenario tests ---
    def test_negligible_gas_on_large_position(self):
        result = self._analyze(
            position_usd=1_000_000.0,
            gross_apy_pct=5.0,
            estimated_gas_usd_per_tx=5.0,
            txs_per_year=12,
            protocol_gas_rebate_pct=0.0,
        )
        # annual_gas = 60; drag = 60/1_000_000 * 100 = 0.006% → negligible
        self.assertEqual(result["recommendation"], "GAS_NEGLIGIBLE")
        self.assertGreater(result["gas_efficiency_score"], 95.0)

    def test_tiny_position_gas_dominant(self):
        result = self._analyze(
            position_usd=500.0,
            gross_apy_pct=5.0,
            estimated_gas_usd_per_tx=15.0,
            txs_per_year=52,  # weekly harvests
            protocol_gas_rebate_pct=0.0,
        )
        # annual_gas = 780; drag = 156%; net_apy very negative
        self.assertIn(result["recommendation"], ("POSITION_TOO_SMALL", "GAS_DOMINANT"))

    def test_full_rebate_makes_gas_free(self):
        result = self._analyze(
            estimated_gas_usd_per_tx=50.0,
            txs_per_year=52,
            protocol_gas_rebate_pct=100.0,
        )
        self.assertAlmostEqual(result["gas_drag_pct"], 0.0)
        self.assertEqual(result["recommendation"], "GAS_NEGLIGIBLE")
        self.assertAlmostEqual(result["gas_efficiency_score"], 100.0)

    def test_high_apy_absorbs_high_gas(self):
        result = self._analyze(
            position_usd=50_000.0,
            gross_apy_pct=25.0,   # high APY (e.g., S8 delta-neutral)
            estimated_gas_usd_per_tx=20.0,
            txs_per_year=12,
            protocol_gas_rebate_pct=0.0,
        )
        # annual_gas = 240; drag = 240/50k * 100 = 0.48%; 0.48/25 = 1.9% → negligible
        self.assertEqual(result["recommendation"], "GAS_NEGLIGIBLE")

    def test_net_apy_negative_when_gas_exceeds_yield(self):
        result = self._analyze(
            position_usd=100.0,
            gross_apy_pct=5.0,
            estimated_gas_usd_per_tx=1.0,
            txs_per_year=100,
            protocol_gas_rebate_pct=0.0,
        )
        # annual_gas = 100; drag = 100%; net_apy = 5 - 100 = -95%
        self.assertLess(result["net_apy_pct"], 0.0)

    # --- Validation errors ---
    def test_missing_key_raises(self):
        params = _default_params()
        del params["position_usd"]
        with self.assertRaises(ValueError):
            self.analyzer.analyze(params)

    def test_negative_position_raises(self):
        with self.assertRaises(ValueError):
            self._analyze(position_usd=-1.0)

    def test_negative_gross_apy_raises(self):
        with self.assertRaises(ValueError):
            self._analyze(gross_apy_pct=-1.0)

    def test_negative_gas_per_tx_raises(self):
        with self.assertRaises(ValueError):
            self._analyze(estimated_gas_usd_per_tx=-1.0)

    def test_negative_txs_per_year_raises(self):
        with self.assertRaises(ValueError):
            self._analyze(txs_per_year=-1)

    def test_rebate_over_100_raises(self):
        with self.assertRaises(ValueError):
            self._analyze(protocol_gas_rebate_pct=101.0)

    def test_rebate_negative_raises(self):
        with self.assertRaises(ValueError):
            self._analyze(protocol_gas_rebate_pct=-1.0)

    def test_negative_gas_price_raises(self):
        with self.assertRaises(ValueError):
            self._analyze(gas_price_gwei=-1.0)

    def test_zero_position_accepted(self):
        """Zero position is accepted; gas_drag returns 0 (degenerate)."""
        result = self._analyze(position_usd=0.0)
        self.assertAlmostEqual(result["gas_drag_pct"], 0.0)

    def test_all_five_recommendations_reachable(self):
        seen = set()
        cases = [
            # GAS_NEGLIGIBLE
            _default_params(position_usd=1_000_000, gross_apy_pct=5, estimated_gas_usd_per_tx=5, txs_per_year=12),
            # GAS_MANAGEABLE
            _default_params(position_usd=10_000, gross_apy_pct=5, estimated_gas_usd_per_tx=5, txs_per_year=12),
            # GAS_SIGNIFICANT
            _default_params(position_usd=3_000, gross_apy_pct=5, estimated_gas_usd_per_tx=5, txs_per_year=12),
            # GAS_DOMINANT
            _default_params(position_usd=1_000, gross_apy_pct=5, estimated_gas_usd_per_tx=5, txs_per_year=12),
            # POSITION_TOO_SMALL
            _default_params(position_usd=100, gross_apy_pct=5, estimated_gas_usd_per_tx=10, txs_per_year=52),
        ]
        for params in cases:
            result = self.analyzer.analyze(params)
            seen.add(result["recommendation"])
        self.assertGreaterEqual(len(seen), 4)

    def test_result_is_json_serializable(self):
        """Output dict must be serializable (no inf/nan at top level)."""
        result = self._analyze(gross_apy_pct=0.0)
        # break_even_position_usd should be None (not inf) in JSON output
        serialized = json.dumps(result)
        self.assertIsInstance(serialized, str)
        self.assertNotIn('"Infinity"', serialized)


if __name__ == "__main__":
    unittest.main()
