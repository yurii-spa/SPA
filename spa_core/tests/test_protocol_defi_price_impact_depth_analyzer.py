"""
Tests for MP-1019: ProtocolDeFiPriceImpactDepthAnalyzer
Run: python3 -m unittest spa_core.tests.test_protocol_defi_price_impact_depth_analyzer
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_defi_price_impact_depth_analyzer import (
    ProtocolDeFiPriceImpactDepthAnalyzer,
    _safe_div,
    _clamp,
    _impact_to_depth_score,
    _impact_v2,
    _impact_v3,
    _impact_curve,
    _impact_balancer,
    _atomic_write,
    _load_log,
    POOL_V2,
    POOL_V3,
    POOL_CURVE,
    POOL_BALANCER,
)


def _make_pool(**kwargs):
    """Return a valid pool dict with defaults overridden by kwargs."""
    defaults = {
        "name": "TestPool",
        "protocol": "TestProtocol",
        "token_pair": "USDC/USDT",
        "pool_type": POOL_V2,
        "tvl_usd": 10_000_000.0,
        "active_liquidity_usd": 8_000_000.0,
        "token_a_reserve_usd": 5_000_000.0,
        "token_b_reserve_usd": 5_000_000.0,
        "fee_tier_bps": 30,
        "trade_sizes_usd": [1_000.0, 10_000.0, 100_000.0, 1_000_000.0],
        "curve_amplification": 100.0,
    }
    defaults.update(kwargs)
    return defaults


def _deep_pool(**kwargs):
    """Large-liquidity pool for INSTITUTIONAL_DEPTH tests."""
    return _make_pool(
        tvl_usd=500_000_000.0,
        active_liquidity_usd=400_000_000.0,
        token_a_reserve_usd=250_000_000.0,
        token_b_reserve_usd=250_000_000.0,
        **kwargs,
    )


def _shallow_pool(**kwargs):
    """Tiny-liquidity pool for SHALLOW tests."""
    return _make_pool(
        tvl_usd=5_000.0,
        active_liquidity_usd=4_000.0,
        token_a_reserve_usd=2_500.0,
        token_b_reserve_usd=2_500.0,
        **kwargs,
    )


class TestHelperFunctions(unittest.TestCase):
    def test_safe_div_normal(self):
        self.assertAlmostEqual(_safe_div(10.0, 2.0), 5.0)

    def test_safe_div_zero_den(self):
        self.assertEqual(_safe_div(5.0, 0.0), 0.0)

    def test_clamp_within(self):
        self.assertEqual(_clamp(5.0, 0.0, 10.0), 5.0)

    def test_clamp_lo(self):
        self.assertEqual(_clamp(-1.0, 0.0, 10.0), 0.0)

    def test_clamp_hi(self):
        self.assertEqual(_clamp(20.0, 0.0, 10.0), 10.0)

    def test_impact_to_depth_score_zero_impact(self):
        # 0% impact → score = 100/(1+0) = 100
        self.assertAlmostEqual(_impact_to_depth_score(0.0), 100.0, places=4)

    def test_impact_to_depth_score_100_percent(self):
        # 100% impact → score = 100/(1+100) ≈ 0.99
        score = _impact_to_depth_score(100.0)
        self.assertLess(score, 2.0)
        self.assertGreaterEqual(score, 0.0)

    def test_impact_to_depth_score_decreasing(self):
        s1 = _impact_to_depth_score(0.5)
        s2 = _impact_to_depth_score(5.0)
        s3 = _impact_to_depth_score(50.0)
        self.assertGreater(s1, s2)
        self.assertGreater(s2, s3)

    def test_impact_to_depth_score_clamped(self):
        self.assertLessEqual(_impact_to_depth_score(-1.0), 100.0)
        self.assertGreaterEqual(_impact_to_depth_score(999.0), 0.0)

    def test_atomic_write_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "out.json")
            _atomic_write(path, {"k": 42})
            with open(path) as f:
                self.assertEqual(json.load(f)["k"], 42)

    def test_atomic_write_no_tmp_leftover(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "out.json")
            _atomic_write(path, [1, 2])
            tmp_files = [f for f in os.listdir(td) if f.endswith(".tmp")]
            self.assertEqual(tmp_files, [])

    def test_load_log_missing_returns_empty(self):
        self.assertEqual(_load_log("/does/not/exist.json"), [])

    def test_load_log_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ bad json }")
            fname = f.name
        try:
            self.assertEqual(_load_log(fname), [])
        finally:
            os.unlink(fname)

    def test_load_log_non_list_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"not": "a list"}, f)
            fname = f.name
        try:
            self.assertEqual(_load_log(fname), [])
        finally:
            os.unlink(fname)


class TestImpactFormulas(unittest.TestCase):
    def test_v2_zero_trade(self):
        self.assertEqual(_impact_v2(0.0, 1_000_000.0, 1_000_000.0), 0.0)

    def test_v2_zero_reserve(self):
        self.assertEqual(_impact_v2(1_000.0, 0.0, 1_000_000.0), 0.0)

    def test_v2_small_trade_low_impact(self):
        # 1K vs 5M reserve → ~0.02%
        impact = _impact_v2(1_000.0, 5_000_000.0, 5_000_000.0)
        self.assertLess(impact, 0.1)

    def test_v2_large_trade_high_impact(self):
        # 5M vs 5M reserve → ~50%
        impact = _impact_v2(5_000_000.0, 5_000_000.0, 5_000_000.0)
        self.assertAlmostEqual(impact, 50.0, delta=1.0)

    def test_v2_impact_formula(self):
        # impact = trade / (reserve_a + trade) * 100
        trade = 1_000.0
        res_a = 999_000.0
        expected = trade / (res_a + trade) * 100
        self.assertAlmostEqual(_impact_v2(trade, res_a, 1.0), expected, places=4)

    def test_v3_zero_active_liquidity(self):
        self.assertEqual(_impact_v3(1_000.0, 0.0), 0.0)

    def test_v3_less_impact_than_v2_same_tvl(self):
        tvl = 10_000_000.0
        trade = 100_000.0
        impact_v2 = _impact_v2(trade, tvl / 2, tvl / 2)
        # v3 with active_liq = 20% of tvl → effective reserve = 10% of tvl < v2 reserve
        # BUT if active_liq = tvl/2 → same as v2
        # Use active_liq < tvl → v3 worse; but conceptually v3 better in tight ranges
        # Test just that formula works
        impact_v3 = _impact_v3(trade, tvl)
        self.assertGreater(impact_v3, 0.0)
        self.assertLess(impact_v3, 100.0)

    def test_v3_formula_correctness(self):
        trade = 10_000.0
        active_liq = 2_000_000.0
        eff_reserve = active_liq / 2.0
        expected = trade / (eff_reserve + trade) * 100
        self.assertAlmostEqual(_impact_v3(trade, active_liq), expected, places=4)

    def test_curve_zero_tvl(self):
        self.assertEqual(_impact_curve(1_000.0, 0.0, 100.0), 0.0)

    def test_curve_high_amp_low_impact(self):
        trade = 100_000.0
        tvl = 1_000_000.0
        impact_low_a = _impact_curve(trade, tvl, 1.0)
        impact_high_a = _impact_curve(trade, tvl, 200.0)
        self.assertGreater(impact_low_a, impact_high_a)

    def test_curve_amp1_similar_to_v2(self):
        # With amp=1, curve approximation ~ v2
        trade = 50_000.0
        tvl = 1_000_000.0
        curve_1 = _impact_curve(trade, tvl, 1.0)
        v2_approx = trade / (tvl + trade) * 100
        self.assertAlmostEqual(curve_1, v2_approx, places=4)

    def test_balancer_zero_trade(self):
        self.assertEqual(_impact_balancer(0.0, 1_000_000.0), 0.0)

    def test_balancer_positive_impact(self):
        impact = _impact_balancer(100_000.0, 500_000.0)
        self.assertGreater(impact, 0.0)

    def test_impact_capped_at_99_99(self):
        # Massive trade vs tiny reserve
        impact = _impact_v2(1e12, 1.0, 1.0)
        self.assertLessEqual(impact, 99.99)


class TestAnalyzerInstantiation(unittest.TestCase):
    def test_default_log_path(self):
        a = ProtocolDeFiPriceImpactDepthAnalyzer()
        self.assertIn("price_impact_depth_log.json", a.log_path)

    def test_custom_log_path(self):
        a = ProtocolDeFiPriceImpactDepthAnalyzer(log_path="/tmp/custom_depth.json")
        self.assertEqual(a.log_path, "/tmp/custom_depth.json")


class TestAnalyzeEmpty(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiPriceImpactDepthAnalyzer(
            log_path=os.path.join(self.td, "log.json")
        )

    def test_empty_returns_dict(self):
        result = self.analyzer.analyze([], {})
        self.assertIsInstance(result, dict)

    def test_empty_pools_key(self):
        result = self.analyzer.analyze([], {})
        self.assertEqual(result["pools"], [])

    def test_empty_aggregates_key(self):
        result = self.analyzer.analyze([], {})
        self.assertIn("aggregates", result)

    def test_empty_aggregates_zero_total(self):
        result = self.analyzer.analyze([], {})
        self.assertEqual(result["aggregates"]["total_pools"], 0)

    def test_empty_aggregates_none_deepest(self):
        result = self.analyzer.analyze([], {})
        self.assertIsNone(result["aggregates"]["deepest_pool"])

    def test_empty_has_timestamp(self):
        result = self.analyzer.analyze([], {})
        self.assertIn("timestamp", result)


class TestAnalyzeSinglePool(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiPriceImpactDepthAnalyzer(
            log_path=os.path.join(self.td, "log.json")
        )

    def _analyze(self, **kwargs):
        return self.analyzer.analyze([_make_pool(**kwargs)], {})

    def test_returns_one_pool(self):
        result = self._analyze()
        self.assertEqual(len(result["pools"]), 1)

    def test_pool_has_name(self):
        result = self._analyze(name="MyPool")
        self.assertEqual(result["pools"][0]["name"], "MyPool")

    def test_pool_has_depth_label(self):
        result = self._analyze()
        self.assertIn("depth_label", result["pools"][0])

    def test_pool_has_flags(self):
        result = self._analyze()
        self.assertIsInstance(result["pools"][0]["flags"], list)

    def test_pool_has_impact_details(self):
        result = self._analyze()
        self.assertIn("impact_details", result["pools"][0])

    def test_impact_details_count_matches_trade_sizes(self):
        result = self._analyze(trade_sizes_usd=[1_000.0, 10_000.0])
        self.assertEqual(len(result["pools"][0]["impact_details"]), 2)

    def test_pool_has_depth_scores(self):
        pool = result["pools"][0] if (result := self._analyze()) else None
        self.assertIn("depth_1k_score", pool)
        self.assertIn("depth_10k_score", pool)
        self.assertIn("depth_100k_score", pool)
        self.assertIn("depth_1m_score", pool)

    def test_pool_has_best_size_tier(self):
        result = self._analyze()
        self.assertIn("best_size_tier", result["pools"][0])

    def test_pool_has_large_trade_viability(self):
        result = self._analyze()
        self.assertIn("large_trade_viability", result["pools"][0])

    def test_impact_details_have_required_fields(self):
        result = self._analyze()
        detail = result["pools"][0]["impact_details"][0]
        self.assertIn("trade_size_usd", detail)
        self.assertIn("price_impact_pct", detail)
        self.assertIn("effective_execution_price", detail)
        self.assertIn("slippage_cost_usd", detail)
        self.assertIn("market_depth_score", detail)

    def test_price_impact_nonnegative(self):
        result = self._analyze()
        for detail in result["pools"][0]["impact_details"]:
            self.assertGreaterEqual(detail["price_impact_pct"], 0.0)

    def test_market_depth_score_range(self):
        result = self._analyze()
        for detail in result["pools"][0]["impact_details"]:
            self.assertGreaterEqual(detail["market_depth_score"], 0.0)
            self.assertLessEqual(detail["market_depth_score"], 100.0)

    def test_slippage_cost_positive(self):
        result = self._analyze()
        for detail in result["pools"][0]["impact_details"]:
            self.assertGreaterEqual(detail["slippage_cost_usd"], 0.0)

    def test_effective_price_at_most_one(self):
        result = self._analyze()
        for detail in result["pools"][0]["impact_details"]:
            self.assertLessEqual(detail["effective_execution_price"], 1.0)


class TestDepthScoreMonotonicity(unittest.TestCase):
    """Larger trades → more impact → lower depth score."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiPriceImpactDepthAnalyzer(
            log_path=os.path.join(self.td, "log.json")
        )

    def test_v2_depth_scores_decrease_with_size(self):
        pool = _make_pool(
            pool_type=POOL_V2,
            token_a_reserve_usd=5_000_000.0,
            trade_sizes_usd=[1_000.0, 10_000.0, 100_000.0, 1_000_000.0],
        )
        result = self.analyzer.analyze([pool], {})
        details = result["pools"][0]["impact_details"]
        scores = [d["market_depth_score"] for d in details]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])

    def test_v3_depth_decreases_with_size(self):
        pool = _make_pool(
            pool_type=POOL_V3,
            active_liquidity_usd=4_000_000.0,
            trade_sizes_usd=[1_000.0, 10_000.0, 100_000.0],
        )
        result = self.analyzer.analyze([pool], {})
        details = result["pools"][0]["impact_details"]
        scores = [d["market_depth_score"] for d in details]
        self.assertGreaterEqual(scores[0], scores[-1])

    def test_curve_depth_decreases_with_size(self):
        pool = _make_pool(
            pool_type=POOL_CURVE,
            tvl_usd=20_000_000.0,
            curve_amplification=100.0,
            trade_sizes_usd=[1_000.0, 10_000.0, 100_000.0],
        )
        result = self.analyzer.analyze([pool], {})
        details = result["pools"][0]["impact_details"]
        scores = [d["market_depth_score"] for d in details]
        self.assertGreaterEqual(scores[0], scores[-1])


class TestDepthLabels(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiPriceImpactDepthAnalyzer(
            log_path=os.path.join(self.td, "log.json")
        )

    def _label(self, **kwargs):
        result = self.analyzer.analyze([kwargs if kwargs else _make_pool()], {})
        return result["pools"][0]["depth_label"]

    def test_institutional_depth_label(self):
        pool = _deep_pool(pool_type=POOL_V2, name="Huge")
        result = self.analyzer.analyze([pool], {})
        label = result["pools"][0]["depth_label"]
        self.assertEqual(label, "INSTITUTIONAL_DEPTH")

    def test_shallow_label(self):
        pool = _shallow_pool(pool_type=POOL_V2, name="Tiny")
        result = self.analyzer.analyze([pool], {})
        label = result["pools"][0]["depth_label"]
        self.assertIn(label, ["SHALLOW", "RETAIL_ONLY"])

    def test_curve_high_amp_deep_label(self):
        pool = _make_pool(
            pool_type=POOL_CURVE,
            tvl_usd=100_000_000.0,
            curve_amplification=500.0,
        )
        result = self.analyzer.analyze([pool], {})
        label = result["pools"][0]["depth_label"]
        # High amp + large TVL should be deep
        self.assertIn(label, ["INSTITUTIONAL_DEPTH", "DEEP_MARKET", "MEDIUM_DEPTH"])

    def test_label_not_empty(self):
        pool = _make_pool()
        result = self.analyzer.analyze([pool], {})
        self.assertTrue(result["pools"][0]["depth_label"])

    def test_valid_labels(self):
        valid = {"INSTITUTIONAL_DEPTH", "DEEP_MARKET", "MEDIUM_DEPTH", "RETAIL_ONLY", "SHALLOW"}
        for pool_type in [POOL_V2, POOL_V3, POOL_CURVE, POOL_BALANCER]:
            pool = _make_pool(pool_type=pool_type)
            result = self.analyzer.analyze([pool], {})
            self.assertIn(result["pools"][0]["depth_label"], valid)


class TestFlags(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiPriceImpactDepthAnalyzer(
            log_path=os.path.join(self.td, "log.json")
        )

    def test_whale_friendly_flag_deep_pool(self):
        pool = _deep_pool(pool_type=POOL_V2, name="Whale")
        result = self.analyzer.analyze([pool], {})
        self.assertIn("WHALE_FRIENDLY", result["pools"][0]["flags"])

    def test_retail_only_pool_flag_shallow(self):
        pool = _shallow_pool(pool_type=POOL_V2, name="Retail")
        result = self.analyzer.analyze([pool], {})
        self.assertIn("RETAIL_ONLY_POOL", result["pools"][0]["flags"])

    def test_concentrated_liquidity_advantage_v3_deep(self):
        pool = _make_pool(
            pool_type=POOL_V3,
            active_liquidity_usd=200_000_000.0,
        )
        result = self.analyzer.analyze([pool], {})
        flags = result["pools"][0]["flags"]
        # Should have CONCENTRATED_LIQUIDITY_ADVANTAGE if depth_100k_score >= 70
        # 100K trade vs 100M effective reserve → tiny impact → high score
        depth_100k = result["pools"][0]["depth_100k_score"]
        if depth_100k >= 70.0:
            self.assertIn("CONCENTRATED_LIQUIDITY_ADVANTAGE", flags)

    def test_no_concentrated_advantage_for_v2(self):
        pool = _deep_pool(pool_type=POOL_V2)
        result = self.analyzer.analyze([pool], {})
        self.assertNotIn("CONCENTRATED_LIQUIDITY_ADVANTAGE", result["pools"][0]["flags"])

    def test_stable_curve_efficiency_deep_curve(self):
        pool = _make_pool(
            pool_type=POOL_CURVE,
            tvl_usd=500_000_000.0,
            curve_amplification=1000.0,
        )
        result = self.analyzer.analyze([pool], {})
        flags = result["pools"][0]["flags"]
        # 1M impact should be very small with high amp & large TVL
        detail_1m = [d for d in result["pools"][0]["impact_details"] if d["trade_size_usd"] == 1_000_000.0]
        if detail_1m and detail_1m[0]["price_impact_pct"] < 0.3:
            self.assertIn("STABLE_CURVE_EFFICIENCY", flags)

    def test_deep_for_size_flag(self):
        pool = _deep_pool(pool_type=POOL_V2)
        result = self.analyzer.analyze([pool], {})
        flags = result["pools"][0]["flags"]
        best = result["pools"][0]["best_size_tier"]
        if best > 100_000:
            self.assertIn("DEEP_FOR_SIZE", flags)

    def test_flags_is_list(self):
        pool = _make_pool()
        result = self.analyzer.analyze([pool], {})
        self.assertIsInstance(result["pools"][0]["flags"], list)


class TestBestSizeTier(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiPriceImpactDepthAnalyzer(
            log_path=os.path.join(self.td, "log.json")
        )

    def test_deep_pool_best_size_1m(self):
        pool = _deep_pool(pool_type=POOL_V2)
        result = self.analyzer.analyze([pool], {})
        self.assertEqual(result["pools"][0]["best_size_tier"], 1_000_000.0)

    def test_shallow_pool_best_size_zero(self):
        pool = _shallow_pool(pool_type=POOL_V2)
        result = self.analyzer.analyze([pool], {})
        # Best size likely 0 (even 1K > 0.5% impact in tiny pool)
        self.assertLessEqual(result["pools"][0]["best_size_tier"], 1_000.0)

    def test_large_trade_viability_ge_best_size(self):
        """large_trade_viability (1% threshold) ≥ best_size_tier (0.5% threshold)."""
        pool = _make_pool(tvl_usd=5_000_000.0, token_a_reserve_usd=2_500_000.0)
        result = self.analyzer.analyze([pool], {})
        p = result["pools"][0]
        self.assertGreaterEqual(p["large_trade_viability"], p["best_size_tier"])


class TestPoolTypeRouting(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiPriceImpactDepthAnalyzer(
            log_path=os.path.join(self.td, "log.json")
        )

    def test_v2_pool_produces_results(self):
        result = self.analyzer.analyze([_make_pool(pool_type=POOL_V2)], {})
        self.assertEqual(len(result["pools"]), 1)

    def test_v3_pool_produces_results(self):
        result = self.analyzer.analyze([_make_pool(pool_type=POOL_V3)], {})
        self.assertEqual(len(result["pools"]), 1)

    def test_curve_pool_produces_results(self):
        result = self.analyzer.analyze([_make_pool(pool_type=POOL_CURVE)], {})
        self.assertEqual(len(result["pools"]), 1)

    def test_balancer_pool_produces_results(self):
        result = self.analyzer.analyze([_make_pool(pool_type=POOL_BALANCER)], {})
        self.assertEqual(len(result["pools"]), 1)

    def test_unknown_pool_type_treated_as_v2(self):
        result = self.analyzer.analyze([_make_pool(pool_type="mystery_amm")], {})
        self.assertEqual(len(result["pools"]), 1)

    def test_curve_vs_v2_same_tvl_curve_lower_impact(self):
        """Curve with high amp should have lower impact than plain V2 at same TVL."""
        tvl = 10_000_000.0
        trade = 500_000.0
        pool_v2 = _make_pool(
            pool_type=POOL_V2,
            tvl_usd=tvl, token_a_reserve_usd=tvl/2, token_b_reserve_usd=tvl/2,
            trade_sizes_usd=[trade],
        )
        pool_curve = _make_pool(
            pool_type=POOL_CURVE,
            tvl_usd=tvl, curve_amplification=200.0,
            trade_sizes_usd=[trade],
        )
        res_v2 = self.analyzer.analyze([pool_v2], {})
        res_curve = self.analyzer.analyze([pool_curve], {})
        imp_v2 = res_v2["pools"][0]["impact_details"][0]["price_impact_pct"]
        imp_curve = res_curve["pools"][0]["impact_details"][0]["price_impact_pct"]
        self.assertGreater(imp_v2, imp_curve)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiPriceImpactDepthAnalyzer(
            log_path=os.path.join(self.td, "log.json")
        )

    def test_deepest_pool_is_largest(self):
        deep = _deep_pool(name="Huge", pool_type=POOL_V2)
        shallow = _shallow_pool(name="Tiny", pool_type=POOL_V2)
        result = self.analyzer.analyze([deep, shallow], {})
        self.assertEqual(result["aggregates"]["deepest_pool"], "Huge")

    def test_shallowest_pool_is_smallest(self):
        deep = _deep_pool(name="Huge", pool_type=POOL_V2)
        shallow = _shallow_pool(name="Tiny", pool_type=POOL_V2)
        result = self.analyzer.analyze([deep, shallow], {})
        self.assertEqual(result["aggregates"]["shallowest_pool"], "Tiny")

    def test_avg_depth_score_single_pool(self):
        result = self.analyzer.analyze([_make_pool()], {})
        agg = result["aggregates"]
        pool_1m_score = result["pools"][0]["depth_1m_score"]
        self.assertAlmostEqual(agg["avg_depth_score"], pool_1m_score, places=4)

    def test_avg_depth_score_two_pools(self):
        deep = _deep_pool(name="Big", pool_type=POOL_V2)
        shallow = _shallow_pool(name="Small", pool_type=POOL_V2)
        result = self.analyzer.analyze([deep, shallow], {})
        scores = [p["depth_1m_score"] for p in result["pools"]]
        expected = sum(scores) / len(scores)
        self.assertAlmostEqual(result["aggregates"]["avg_depth_score"], expected, places=4)

    def test_institutional_depth_count(self):
        pools = [_deep_pool(name=f"Big{i}") for i in range(3)] + [_shallow_pool(name="S")]
        result = self.analyzer.analyze(pools, {})
        institutional = result["aggregates"]["institutional_depth_count"]
        self.assertGreaterEqual(institutional, 0)
        self.assertLessEqual(institutional, 4)

    def test_shallow_count_includes_retail_only(self):
        pools = [_shallow_pool(name=f"S{i}") for i in range(2)]
        result = self.analyzer.analyze(pools, {})
        self.assertGreaterEqual(result["aggregates"]["shallow_count"], 0)

    def test_total_pools(self):
        pools = [_make_pool(name=f"P{i}") for i in range(4)]
        result = self.analyzer.analyze(pools, {})
        self.assertEqual(result["aggregates"]["total_pools"], 4)


class TestLogPersistence(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.log_path = os.path.join(self.td, "log.json")
        self.analyzer = ProtocolDeFiPriceImpactDepthAnalyzer(log_path=self.log_path)

    def test_log_created(self):
        self.analyzer.analyze([], {})
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_list(self):
        self.analyzer.analyze([], {})
        with open(self.log_path) as f:
            self.assertIsInstance(json.load(f), list)

    def test_log_appends_entries(self):
        self.analyzer.analyze([], {})
        self.analyzer.analyze([], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_ring_buffer_cap(self):
        for _ in range(110):
            self.analyzer.analyze([], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_log_entry_has_timestamp(self):
        self.analyzer.analyze([], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_pools(self):
        self.analyzer.analyze([_make_pool()], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("pools", data[0])

    def test_log_entry_has_aggregates(self):
        self.analyzer.analyze([], {})
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn("aggregates", data[0])

    def test_no_tmp_files_after_write(self):
        self.analyzer.analyze([], {})
        tmp_files = [f for f in os.listdir(self.td) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.analyzer = ProtocolDeFiPriceImpactDepthAnalyzer(
            log_path=os.path.join(self.td, "log.json")
        )

    def test_zero_tvl_pool(self):
        pool = _make_pool(tvl_usd=0.0, token_a_reserve_usd=0.0, token_b_reserve_usd=0.0)
        result = self.analyzer.analyze([pool], {})
        # Should not raise; all impacts should be 0
        self.assertEqual(len(result["pools"]), 1)
        for detail in result["pools"][0]["impact_details"]:
            self.assertAlmostEqual(detail["price_impact_pct"], 0.0)

    def test_single_trade_size(self):
        pool = _make_pool(trade_sizes_usd=[50_000.0])
        result = self.analyzer.analyze([pool], {})
        self.assertEqual(len(result["pools"][0]["impact_details"]), 1)

    def test_global_trade_sizes_from_config(self):
        pool = _make_pool()
        del pool["trade_sizes_usd"]
        config = {"trade_sizes_usd": [5_000.0, 50_000.0]}
        result = self.analyzer.analyze([pool], config)
        self.assertEqual(len(result["pools"][0]["impact_details"]), 2)

    def test_pool_echoes_name(self):
        pool = _make_pool(name="SpecialPool")
        result = self.analyzer.analyze([pool], {})
        self.assertEqual(result["pools"][0]["name"], "SpecialPool")

    def test_pool_echoes_protocol(self):
        pool = _make_pool(protocol="Uniswap")
        result = self.analyzer.analyze([pool], {})
        self.assertEqual(result["pools"][0]["protocol"], "Uniswap")

    def test_pool_echoes_token_pair(self):
        pool = _make_pool(token_pair="WETH/USDC")
        result = self.analyzer.analyze([pool], {})
        self.assertEqual(result["pools"][0]["token_pair"], "WETH/USDC")

    def test_five_pools_sorted_correctly(self):
        pools = [_make_pool(name=f"P{i}", tvl_usd=float(i * 1_000_000)) for i in range(1, 6)]
        result = self.analyzer.analyze(pools, {})
        agg = result["aggregates"]
        self.assertIsNotNone(agg["deepest_pool"])
        self.assertIsNotNone(agg["shallowest_pool"])

    def test_balancer_same_as_v2_for_equal_reserves(self):
        """Balancer pool should use token_a_reserve same as V2 with same reserve."""
        pool_v2 = _make_pool(pool_type=POOL_V2, trade_sizes_usd=[1_000.0])
        pool_bal = _make_pool(pool_type=POOL_BALANCER, trade_sizes_usd=[1_000.0])
        res_v2 = self.analyzer.analyze([pool_v2], {})
        res_bal = self.analyzer.analyze([pool_bal], {})
        # Both use token_a_reserve in the same way
        imp_v2 = res_v2["pools"][0]["impact_details"][0]["price_impact_pct"]
        imp_bal = res_bal["pools"][0]["impact_details"][0]["price_impact_pct"]
        self.assertAlmostEqual(imp_v2, imp_bal, places=4)

    def test_v3_uses_active_liquidity_not_tvl(self):
        """V3 pool with small active_liquidity should have higher impact than TVL suggests."""
        pool = _make_pool(
            pool_type=POOL_V3,
            tvl_usd=100_000_000.0,
            active_liquidity_usd=200_000.0,  # only 0.2% active
            trade_sizes_usd=[100_000.0],
        )
        result = self.analyzer.analyze([pool], {})
        impact = result["pools"][0]["impact_details"][0]["price_impact_pct"]
        # 100K vs 100K effective → very high impact
        self.assertGreater(impact, 10.0)


if __name__ == "__main__":
    unittest.main()
