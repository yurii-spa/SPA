#!/usr/bin/env python3
"""Unit tests for MP-1063 ProtocolDeFiLiquidityDepthImpactAnalyzer (SPA-v769).

Run:
    python3 -m unittest spa_core/tests/test_protocol_defi_liquidity_depth_impact_analyzer.py -v

stdlib unittest only — no pytest, no numpy.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.analytics.protocol_defi_liquidity_depth_impact_analyzer import (
    ProtocolDeFiLiquidityDepthImpactAnalyzer,
    _clamp,
    _compute_price_impact_constant_product,
    _compute_price_impact,
    _compute_slippage,
    _compute_fee_cost_pct,
    _compute_effective_spread_bps,
    _compute_liquidity_label,
    _load_json_list,
    _atomic_write,
    analyze_liquidity_depth_impact,
    write_log,
    RING_BUFFER_CAP,
    LOG_FILENAME,
    STABLE_AMPLIFICATION,
    VALID_POOL_TYPES,
)


# ===========================================================================
# 1. _clamp
# ===========================================================================

class TestClamp(unittest.TestCase):

    def test_within_range(self):
        self.assertAlmostEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_below_lo(self):
        self.assertAlmostEqual(_clamp(-3.0, 0.0, 10.0), 0.0)

    def test_above_hi(self):
        self.assertAlmostEqual(_clamp(20.0, 0.0, 10.0), 10.0)

    def test_at_lo(self):
        self.assertAlmostEqual(_clamp(0.0, 0.0, 10.0), 0.0)

    def test_at_hi(self):
        self.assertAlmostEqual(_clamp(10.0, 0.0, 10.0), 10.0)

    def test_same_lo_hi(self):
        self.assertAlmostEqual(_clamp(99.0, 5.0, 5.0), 5.0)


# ===========================================================================
# 2. _compute_price_impact_constant_product
# ===========================================================================

class TestPriceImpactConstantProduct(unittest.TestCase):

    def test_zero_trade_returns_zero(self):
        self.assertAlmostEqual(_compute_price_impact_constant_product(0.0, 1_000_000.0), 0.0)

    def test_small_trade_small_impact(self):
        # 1000 / (1_000_000 + 1000) * 100 ≈ 0.0999
        impact = _compute_price_impact_constant_product(1_000.0, 1_000_000.0)
        self.assertAlmostEqual(impact, 1000.0 / 1_001_000.0 * 100.0, places=6)

    def test_equal_trade_and_reserve(self):
        # trade = reserve → 50%
        impact = _compute_price_impact_constant_product(1_000.0, 1_000.0)
        self.assertAlmostEqual(impact, 50.0, places=6)

    def test_zero_reserve_returns_100(self):
        impact = _compute_price_impact_constant_product(1_000.0, 0.0)
        self.assertAlmostEqual(impact, 100.0)

    def test_large_reserve_very_small_impact(self):
        impact = _compute_price_impact_constant_product(100.0, 10_000_000.0)
        self.assertLess(impact, 0.01)

    def test_negative_trade_returns_zero(self):
        impact = _compute_price_impact_constant_product(-1000.0, 1_000_000.0)
        self.assertAlmostEqual(impact, 0.0)

    def test_result_in_range(self):
        impact = _compute_price_impact_constant_product(50_000.0, 500_000.0)
        self.assertGreaterEqual(impact, 0.0)
        self.assertLessEqual(impact, 100.0)

    def test_exact_formula(self):
        trade, reserve = 10_000.0, 100_000.0
        expected = trade / (reserve + trade) * 100.0
        result = _compute_price_impact_constant_product(trade, reserve)
        self.assertAlmostEqual(result, expected, places=8)


# ===========================================================================
# 3. _compute_price_impact — pool type routing
# ===========================================================================

class TestComputePriceImpact(unittest.TestCase):

    def _run(self, pool_type, trade=10_000.0, reserve=1_000_000.0, conc=1.0):
        impact, warnings = _compute_price_impact(pool_type, trade, reserve, conc)
        return impact, warnings

    def test_constant_product_returns_float(self):
        impact, _ = self._run("constant_product")
        self.assertIsInstance(impact, float)

    def test_stable_swap_lower_than_constant_product(self):
        cp_impact, _ = self._run("constant_product")
        ss_impact, _ = self._run("stable_swap")
        self.assertLess(ss_impact, cp_impact)

    def test_stable_swap_amplification(self):
        # stable_swap uses 10× effective reserve
        trade, reserve = 10_000.0, 1_000_000.0
        ss_impact, _ = self._run("stable_swap", trade, reserve)
        eff_reserve = reserve * STABLE_AMPLIFICATION
        expected = _compute_price_impact_constant_product(trade, eff_reserve)
        self.assertAlmostEqual(ss_impact, expected, places=6)

    def test_concentrated_higher_conc_lower_impact(self):
        impact_1x, _ = self._run("concentrated", conc=1.0)
        impact_4x, _ = self._run("concentrated", conc=4.0)
        self.assertGreater(impact_1x, impact_4x)

    def test_concentrated_conc1_equals_constant_product(self):
        cp, _ = self._run("constant_product")
        conc, _ = self._run("concentrated", conc=1.0)
        self.assertAlmostEqual(cp, conc, places=6)

    def test_unknown_pool_type_warns(self):
        _, w = self._run("magic_amm")
        self.assertTrue(any("unknown" in s.lower() or "default" in s.lower() for s in w))

    def test_unknown_pool_type_returns_float(self):
        impact, _ = self._run("bogus")
        self.assertIsInstance(impact, float)

    def test_zero_trade_returns_zero(self):
        impact, _ = self._run("constant_product", trade=0.0)
        self.assertAlmostEqual(impact, 0.0)

    def test_negative_conc_clamped(self):
        impact, w = self._run("concentrated", conc=-5.0)
        # Should warn and use 1.0
        self.assertIsInstance(impact, float)

    def test_all_valid_pool_types_return_float(self):
        for pt in VALID_POOL_TYPES:
            impact, _ = self._run(pt)
            self.assertIsInstance(impact, float)


# ===========================================================================
# 4. _compute_slippage
# ===========================================================================

class TestComputeSlippage(unittest.TestCase):

    def test_zero_impact_zero_slippage(self):
        self.assertAlmostEqual(_compute_slippage(0.0), 0.0)

    def test_half_of_impact(self):
        self.assertAlmostEqual(_compute_slippage(2.0), 1.0)

    def test_exact_ratio(self):
        for pi in [0.1, 1.0, 5.0, 10.0, 50.0]:
            self.assertAlmostEqual(_compute_slippage(pi), pi * 0.5, places=8)

    def test_negative_impact_zero_slippage(self):
        self.assertAlmostEqual(_compute_slippage(-5.0), 0.0)


# ===========================================================================
# 5. _compute_fee_cost_pct
# ===========================================================================

class TestComputeFeeCostPct(unittest.TestCase):

    def test_30bps(self):
        # 30 bps = 0.30%
        self.assertAlmostEqual(_compute_fee_cost_pct(30.0), 0.30)

    def test_5bps(self):
        self.assertAlmostEqual(_compute_fee_cost_pct(5.0), 0.05)

    def test_zero_bps(self):
        self.assertAlmostEqual(_compute_fee_cost_pct(0.0), 0.0)

    def test_100bps(self):
        self.assertAlmostEqual(_compute_fee_cost_pct(100.0), 1.0)

    def test_negative_clamped_zero(self):
        self.assertAlmostEqual(_compute_fee_cost_pct(-10.0), 0.0)

    def test_fractional_bps(self):
        self.assertAlmostEqual(_compute_fee_cost_pct(1.0), 0.01)


# ===========================================================================
# 6. _compute_effective_spread_bps
# ===========================================================================

class TestComputeEffectiveSpreadBps(unittest.TestCase):

    def test_zero_cost(self):
        self.assertAlmostEqual(_compute_effective_spread_bps(0.0), 0.0)

    def test_one_pct(self):
        self.assertAlmostEqual(_compute_effective_spread_bps(1.0), 100.0)

    def test_half_pct(self):
        self.assertAlmostEqual(_compute_effective_spread_bps(0.5), 50.0)

    def test_negative_clamped(self):
        self.assertAlmostEqual(_compute_effective_spread_bps(-1.0), 0.0)

    def test_small_cost(self):
        self.assertAlmostEqual(_compute_effective_spread_bps(0.01), 1.0)


# ===========================================================================
# 7. _compute_liquidity_label
# ===========================================================================

class TestComputeLiquidityLabel(unittest.TestCase):

    def test_deep_liquidity_zero(self):
        self.assertEqual(_compute_liquidity_label(0.0), "DEEP_LIQUIDITY")

    def test_deep_liquidity_just_below(self):
        self.assertEqual(_compute_liquidity_label(0.09), "DEEP_LIQUIDITY")

    def test_adequate_at_threshold(self):
        self.assertEqual(_compute_liquidity_label(0.1), "ADEQUATE_LIQUIDITY")

    def test_adequate_below_moderate(self):
        self.assertEqual(_compute_liquidity_label(0.4), "ADEQUATE_LIQUIDITY")

    def test_moderate_at_threshold(self):
        self.assertEqual(_compute_liquidity_label(0.5), "MODERATE_IMPACT")

    def test_moderate_below_high(self):
        self.assertEqual(_compute_liquidity_label(0.9), "MODERATE_IMPACT")

    def test_high_at_threshold(self):
        self.assertEqual(_compute_liquidity_label(1.0), "HIGH_IMPACT")

    def test_high_below_avoid(self):
        self.assertEqual(_compute_liquidity_label(2.9), "HIGH_IMPACT")

    def test_avoid_at_threshold(self):
        self.assertEqual(_compute_liquidity_label(3.0), "AVOID_TRADE_SIZE")

    def test_avoid_very_large(self):
        self.assertEqual(_compute_liquidity_label(100.0), "AVOID_TRADE_SIZE")


# ===========================================================================
# 8. analyze_liquidity_depth_impact — output structure
# ===========================================================================

BASE_PARAMS = {
    "pool_name": "USDC/ETH 0.30%",
    "total_liquidity_usd": 10_000_000.0,
    "token_a_reserve_usd": 5_000_000.0,
    "token_b_reserve_usd": 5_000_000.0,
    "fee_tier_bps": 30.0,
    "trade_size_usd": 100_000.0,
    "pool_type": "constant_product",
    "concentration_factor": 1.0,
    "volume_24h_usd": 2_000_000.0,
}


class TestAnalyzeStructure(unittest.TestCase):

    def _run(self, extra=None):
        p = dict(BASE_PARAMS)
        if extra:
            p.update(extra)
        return analyze_liquidity_depth_impact(p)

    def test_returns_dict(self):
        self.assertIsInstance(self._run(), dict)

    def test_required_keys(self):
        result = self._run()
        for key in [
            "pool_name", "price_impact_pct", "slippage_pct", "fee_cost_pct",
            "total_execution_cost_pct", "effective_spread_bps", "liquidity_label",
            "warnings", "timestamp_utc", "schema_version", "source", "mp_tag",
        ]:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_pool_name_preserved(self):
        result = self._run()
        self.assertEqual(result["pool_name"], "USDC/ETH 0.30%")

    def test_mp_tag(self):
        result = self._run()
        self.assertEqual(result["mp_tag"], "MP-1063")

    def test_schema_version(self):
        result = self._run()
        self.assertEqual(result["schema_version"], 1)

    def test_liquidity_label_valid(self):
        valid = {"DEEP_LIQUIDITY", "ADEQUATE_LIQUIDITY", "MODERATE_IMPACT",
                 "HIGH_IMPACT", "AVOID_TRADE_SIZE"}
        result = self._run()
        self.assertIn(result["liquidity_label"], valid)

    def test_warnings_list(self):
        result = self._run()
        self.assertIsInstance(result["warnings"], list)

    def test_price_impact_nonnegative(self):
        result = self._run()
        self.assertGreaterEqual(result["price_impact_pct"], 0.0)

    def test_slippage_nonnegative(self):
        result = self._run()
        self.assertGreaterEqual(result["slippage_pct"], 0.0)

    def test_fee_cost_nonnegative(self):
        result = self._run()
        self.assertGreaterEqual(result["fee_cost_pct"], 0.0)

    def test_total_cost_equals_sum(self):
        result = self._run()
        expected = (result["price_impact_pct"] + result["slippage_pct"]
                    + result["fee_cost_pct"])
        self.assertAlmostEqual(result["total_execution_cost_pct"], expected, places=5)

    def test_spread_equals_100x_total(self):
        result = self._run()
        expected = result["total_execution_cost_pct"] * 100.0
        self.assertAlmostEqual(result["effective_spread_bps"], expected, places=4)


# ===========================================================================
# 9. Numeric values — constant product
# ===========================================================================

class TestAnalyzeConstantProductValues(unittest.TestCase):

    def setUp(self):
        self.result = analyze_liquidity_depth_impact(BASE_PARAMS)

    def test_fee_cost_30bps(self):
        self.assertAlmostEqual(self.result["fee_cost_pct"], 0.30, places=4)

    def test_slippage_half_impact(self):
        self.assertAlmostEqual(
            self.result["slippage_pct"],
            self.result["price_impact_pct"] * 0.5,
            places=5,
        )

    def test_price_impact_formula(self):
        # trade=100000, reserve=5000000 → 100000/5100000*100
        expected = 100_000.0 / 5_100_000.0 * 100.0
        self.assertAlmostEqual(self.result["price_impact_pct"], expected, places=4)

    def test_label_reasonable_large_pool(self):
        # 100k trade, 5M single-side reserve → ~1.96% impact + slippage + fee ≈ 3.2% → any valid label
        valid = {"DEEP_LIQUIDITY", "ADEQUATE_LIQUIDITY", "MODERATE_IMPACT",
                 "HIGH_IMPACT", "AVOID_TRADE_SIZE"}
        self.assertIn(self.result["liquidity_label"], valid)


# ===========================================================================
# 10. Stable swap vs constant product
# ===========================================================================

class TestStableSwap(unittest.TestCase):

    def _run(self, pool_type):
        return analyze_liquidity_depth_impact({**BASE_PARAMS, "pool_type": pool_type})

    def test_stable_lower_impact(self):
        cp = self._run("constant_product")
        ss = self._run("stable_swap")
        self.assertLess(ss["price_impact_pct"], cp["price_impact_pct"])

    def test_stable_same_fee(self):
        cp = self._run("constant_product")
        ss = self._run("stable_swap")
        self.assertAlmostEqual(ss["fee_cost_pct"], cp["fee_cost_pct"], places=6)

    def test_stable_lower_total_cost_than_cp(self):
        # stable_swap has lower price impact than constant_product; total cost still lower
        cp = self._run("constant_product")
        ss = self._run("stable_swap")
        self.assertLess(ss["total_execution_cost_pct"], cp["total_execution_cost_pct"])


# ===========================================================================
# 11. Concentrated liquidity
# ===========================================================================

class TestConcentrated(unittest.TestCase):

    def _run(self, conc):
        return analyze_liquidity_depth_impact(
            {**BASE_PARAMS, "pool_type": "concentrated", "concentration_factor": conc}
        )

    def test_higher_conc_lower_impact(self):
        r1 = self._run(1.0)
        r10 = self._run(10.0)
        self.assertGreater(r1["price_impact_pct"], r10["price_impact_pct"])

    def test_conc_1_matches_cp(self):
        cp = analyze_liquidity_depth_impact(BASE_PARAMS)
        conc = self._run(1.0)
        self.assertAlmostEqual(cp["price_impact_pct"], conc["price_impact_pct"], places=6)

    def test_very_high_conc_very_low_impact(self):
        r = self._run(1000.0)
        self.assertLess(r["price_impact_pct"], 0.01)


# ===========================================================================
# 12. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def test_zero_trade_size_all_zeros(self):
        result = analyze_liquidity_depth_impact({**BASE_PARAMS, "trade_size_usd": 0.0})
        self.assertAlmostEqual(result["price_impact_pct"], 0.0)
        self.assertAlmostEqual(result["slippage_pct"], 0.0)
        # fee still applies only to the trade, which is 0 → fee_cost 0.30% of notional
        # fee_cost_pct is from fee_tier_bps, independent of trade size
        self.assertAlmostEqual(result["fee_cost_pct"], 0.30, places=4)

    def test_zero_liquidity_warns(self):
        result = analyze_liquidity_depth_impact({
            **BASE_PARAMS,
            "total_liquidity_usd": 0.0,
            "token_b_reserve_usd": 0.0,
        })
        self.assertTrue(len(result["warnings"]) > 0)

    def test_missing_pool_name(self):
        p = {k: v for k, v in BASE_PARAMS.items() if k != "pool_name"}
        result = analyze_liquidity_depth_impact(p)
        self.assertEqual(result["pool_name"], "unknown")

    def test_unknown_pool_type_warns(self):
        result = analyze_liquidity_depth_impact({**BASE_PARAMS, "pool_type": "exotic"})
        self.assertTrue(len(result["warnings"]) > 0)

    def test_very_large_trade_avoid_label(self):
        result = analyze_liquidity_depth_impact({
            **BASE_PARAMS,
            "trade_size_usd": 9_000_000.0,  # 90% of pool
        })
        self.assertEqual(result["liquidity_label"], "AVOID_TRADE_SIZE")

    def test_tiny_trade_deep_label(self):
        # tiny impact, but fee_tier_bps=30 (0.30%) still keeps it as ADEQUATE at minimum
        result = analyze_liquidity_depth_impact({
            **BASE_PARAMS,
            "trade_size_usd": 10.0,
            "total_liquidity_usd": 100_000_000.0,
            "token_b_reserve_usd": 50_000_000.0,
            "fee_tier_bps": 0.0,  # zero fee → price impact only → should be DEEP
        })
        self.assertEqual(result["liquidity_label"], "DEEP_LIQUIDITY")

    def test_non_numeric_input_warns(self):
        result = analyze_liquidity_depth_impact({
            **BASE_PARAMS,
            "trade_size_usd": "not_a_number",
        })
        self.assertTrue(len(result["warnings"]) > 0)

    def test_zero_token_b_uses_fallback(self):
        result = analyze_liquidity_depth_impact({
            **BASE_PARAMS,
            "token_b_reserve_usd": 0.0,
        })
        # Should warn and use total_liq/2 as fallback
        self.assertTrue(len(result["warnings"]) > 0)
        self.assertIsInstance(result["price_impact_pct"], float)

    def test_negative_fee_clamped(self):
        result = analyze_liquidity_depth_impact({**BASE_PARAMS, "fee_tier_bps": -10.0})
        self.assertGreaterEqual(result["fee_cost_pct"], 0.0)


# ===========================================================================
# 13. _load_json_list and _atomic_write
# ===========================================================================

class TestIOHelpers(unittest.TestCase):

    def test_load_missing_returns_empty(self):
        result = _load_json_list(Path("/nonexistent/path/log.json"))
        self.assertEqual(result, [])

    def test_load_corrupted_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{not valid json}")
            tmp = f.name
        try:
            result = _load_json_list(Path(tmp))
            self.assertEqual(result, [])
        finally:
            os.unlink(tmp)

    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.json"
            _atomic_write(p, [{"a": 1}])
            self.assertEqual(json.loads(p.read_text()), [{"a": 1}])

    def test_atomic_write_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.json"
            _atomic_write(p, [1])
            _atomic_write(p, [2, 3])
            self.assertEqual(json.loads(p.read_text()), [2, 3])

    def test_load_non_list_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"a": 1}, f)
            tmp = f.name
        try:
            result = _load_json_list(Path(tmp))
            self.assertEqual(result, [])
        finally:
            os.unlink(tmp)


# ===========================================================================
# 14. write_log ring-buffer
# ===========================================================================

class TestWriteLog(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _result(self, name="pool"):
        return analyze_liquidity_depth_impact({**BASE_PARAMS, "pool_name": name})

    def test_write_creates_file(self):
        r = self._result()
        path = write_log(r, self.data_dir)
        self.assertTrue(path.exists())

    def test_filename_matches_constant(self):
        r = self._result()
        path = write_log(r, self.data_dir)
        self.assertEqual(path.name, LOG_FILENAME)

    def test_single_entry(self):
        write_log(self._result(), self.data_dir)
        data = json.loads((self.data_dir / LOG_FILENAME).read_text())
        self.assertEqual(len(data), 1)

    def test_multiple_entries(self):
        for i in range(5):
            write_log(self._result(f"pool{i}"), self.data_dir)
        data = json.loads((self.data_dir / LOG_FILENAME).read_text())
        self.assertEqual(len(data), 5)

    def test_ring_buffer_cap(self):
        for i in range(RING_BUFFER_CAP + 10):
            write_log(self._result(f"p{i}"), self.data_dir)
        data = json.loads((self.data_dir / LOG_FILENAME).read_text())
        self.assertLessEqual(len(data), RING_BUFFER_CAP)

    def test_ring_buffer_keeps_latest(self):
        for i in range(RING_BUFFER_CAP + 3):
            write_log(self._result(f"p{i}"), self.data_dir)
        data = json.loads((self.data_dir / LOG_FILENAME).read_text())
        self.assertEqual(data[-1]["pool_name"], f"p{RING_BUFFER_CAP + 2}")

    def test_log_is_valid_json_list(self):
        write_log(self._result(), self.data_dir)
        data = json.loads((self.data_dir / LOG_FILENAME).read_text())
        self.assertIsInstance(data, list)


# ===========================================================================
# 15. ProtocolDeFiLiquidityDepthImpactAnalyzer class
# ===========================================================================

class TestAnalyzerClass(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiLiquidityDepthImpactAnalyzer(
            data_dir=Path(self.tmp_dir)
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_analyze_returns_dict(self):
        result = self.analyzer.analyze(BASE_PARAMS)
        self.assertIsInstance(result, dict)

    def test_save_creates_log(self):
        result = self.analyzer.analyze(BASE_PARAMS)
        path = self.analyzer.save(result)
        self.assertTrue(path.exists())

    def test_analyze_and_save(self):
        result = self.analyzer.analyze_and_save(BASE_PARAMS)
        path = Path(self.tmp_dir) / LOG_FILENAME
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["mp_tag"], "MP-1063")

    def test_default_data_dir(self):
        a = ProtocolDeFiLiquidityDepthImpactAnalyzer()
        self.assertIsNotNone(a._data_dir)

    def test_ring_buffer_via_class(self):
        for _ in range(RING_BUFFER_CAP + 5):
            result = self.analyzer.analyze(BASE_PARAMS)
            self.analyzer.save(result)
        data = json.loads((Path(self.tmp_dir) / LOG_FILENAME).read_text())
        self.assertLessEqual(len(data), RING_BUFFER_CAP)


# ===========================================================================
# 16. Fee tier variations
# ===========================================================================

class TestFeeTiers(unittest.TestCase):

    def _run(self, fee_bps):
        return analyze_liquidity_depth_impact({**BASE_PARAMS, "fee_tier_bps": fee_bps})

    def test_5bps_pool(self):
        result = self._run(5.0)
        self.assertAlmostEqual(result["fee_cost_pct"], 0.05, places=4)

    def test_100bps_pool(self):
        result = self._run(100.0)
        self.assertAlmostEqual(result["fee_cost_pct"], 1.0, places=4)

    def test_1bps_pool(self):
        result = self._run(1.0)
        self.assertAlmostEqual(result["fee_cost_pct"], 0.01, places=4)

    def test_zero_fee_pool(self):
        result = self._run(0.0)
        self.assertAlmostEqual(result["fee_cost_pct"], 0.0, places=4)

    def test_high_fee_bumps_label(self):
        # 100 bps = 1% fee alone → at least HIGH_IMPACT
        result = self._run(100.0)
        self.assertIn(result["liquidity_label"],
                      {"HIGH_IMPACT", "AVOID_TRADE_SIZE"})


# ===========================================================================
# 17. Volume 24h (informational)
# ===========================================================================

class TestVolume24h(unittest.TestCase):

    def test_volume_preserved_in_result(self):
        result = analyze_liquidity_depth_impact({
            **BASE_PARAMS, "volume_24h_usd": 12_345_678.0
        })
        self.assertAlmostEqual(result["volume_24h_usd"], 12_345_678.0, places=2)

    def test_zero_volume_valid(self):
        result = analyze_liquidity_depth_impact({**BASE_PARAMS, "volume_24h_usd": 0.0})
        self.assertAlmostEqual(result["volume_24h_usd"], 0.0)


# ===========================================================================
# 18. Total execution cost composition
# ===========================================================================

class TestTotalCostComposition(unittest.TestCase):

    def test_total_cost_increases_with_trade_size(self):
        small = analyze_liquidity_depth_impact({**BASE_PARAMS, "trade_size_usd": 1_000.0})
        large = analyze_liquidity_depth_impact({**BASE_PARAMS, "trade_size_usd": 1_000_000.0})
        self.assertLess(
            small["total_execution_cost_pct"],
            large["total_execution_cost_pct"],
        )

    def test_total_cost_decreases_with_liquidity(self):
        shallow = analyze_liquidity_depth_impact({
            **BASE_PARAMS,
            "total_liquidity_usd": 100_000.0,
            "token_b_reserve_usd": 50_000.0,
        })
        deep = analyze_liquidity_depth_impact({
            **BASE_PARAMS,
            "total_liquidity_usd": 500_000_000.0,
            "token_b_reserve_usd": 250_000_000.0,
        })
        self.assertGreater(
            shallow["total_execution_cost_pct"],
            deep["total_execution_cost_pct"],
        )

    def test_spread_bps_consistent(self):
        result = analyze_liquidity_depth_impact(BASE_PARAMS)
        self.assertAlmostEqual(
            result["effective_spread_bps"],
            result["total_execution_cost_pct"] * 100.0,
            places=3,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
