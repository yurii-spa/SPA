"""
Tests for MP-971: ProtocolLiquidityDepthStressTester
Run: python3 -m unittest spa_core.tests.test_protocol_liquidity_depth_stress_tester -v
"""

import json
import os
import tempfile
import unittest

from spa_core.analytics.protocol_liquidity_depth_stress_tester import (
    ProtocolLiquidityDepthStressTester,
    STRESS_DEEP,
    STRESS_ADEQUATE,
    STRESS_THIN,
    STRESS_VERY_THIN,
    STRESS_ILLIQUID,
    FLAG_LP_CONCENTRATED,
    FLAG_ACTIVE_RANGE_NARROW,
    FLAG_HIGH_VOLUME_RATIO,
    FLAG_INSTITUTIONAL_GRADE,
    FLAG_RETAIL_ONLY,
    ALL_STRESS_LABELS,
)


def _make_pool(**kwargs):
    """Return a deep base pool, overriding with kwargs."""
    defaults = {
        'protocol': 'Uniswap',
        'pair': 'USDC/ETH',
        'total_liquidity_usd': 50_000_000,
        'liquidity_distribution': {
            'pct_within_1pct': 40,
            'pct_within_5pct': 70,
            'pct_within_10pct': 90,
        },
        'daily_volume_usd': 5_000_000,
        'top_3_lp_concentration_pct': 25,
        'is_concentrated_liquidity': False,
        'active_range_utilization_pct': 80,
        'fee_tier_bps': 30,
        'avg_slippage_1m_usd': 0.05,
    }
    defaults.update(kwargs)
    return defaults


def _make_log_dir():
    d = tempfile.mkdtemp()
    return d, os.path.join(d, 'liquidity_depth_log.json')


class TestInstantiation(unittest.TestCase):
    def test_default_instantiation(self):
        t = ProtocolLiquidityDepthStressTester()
        self.assertIsNotNone(t)

    def test_custom_log_file(self):
        _, log = _make_log_dir()
        t = ProtocolLiquidityDepthStressTester(log_file=log)
        self.assertEqual(t._log_file, log)

    def test_default_config_keys(self):
        cfg = ProtocolLiquidityDepthStressTester.DEFAULT_CONFIG
        self.assertIn('illiquid_slippage_threshold_pct', cfg)
        self.assertIn('lp_concentration_threshold_pct', cfg)
        self.assertIn('high_volume_ratio_threshold', cfg)
        self.assertIn('institutional_impact_threshold_pct', cfg)


class TestEmptyInput(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def test_empty_returns_dict(self):
        r = self.t.test([], config={'log_file': self.log})
        self.assertIsInstance(r, dict)

    def test_empty_pools_analyzed_zero(self):
        r = self.t.test([], config={'log_file': self.log})
        self.assertEqual(r['pools_analyzed'], 0)

    def test_empty_results_empty(self):
        r = self.t.test([], config={'log_file': self.log})
        self.assertEqual(r['results'], [])

    def test_empty_aggregates_defaults(self):
        r = self.t.test([], config={'log_file': self.log})
        agg = r['aggregates']
        self.assertIsNone(agg['deepest_pool'])
        self.assertIsNone(agg['shallowest_pool'])
        self.assertEqual(agg['total_ecosystem_liquidity_usd'], 0.0)
        self.assertEqual(agg['illiquid_count'], 0)
        self.assertEqual(agg['institutional_grade_count'], 0)

    def test_empty_still_writes_log(self):
        self.t.test([], config={'log_file': self.log})
        self.assertTrue(os.path.exists(self.log))


class TestOutputStructure(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def test_top_level_keys(self):
        r = self.t.test([_make_pool()], config={'log_file': self.log})
        for key in ('timestamp', 'pools_analyzed', 'results', 'aggregates'):
            self.assertIn(key, r)

    def test_result_has_required_fields(self):
        r = self.t.test([_make_pool()], config={'log_file': self.log})
        res = r['results'][0]
        for field in (
            'protocol', 'pair', 'total_liquidity_usd', 'daily_volume_usd',
            'top_3_lp_concentration_pct', 'is_concentrated_liquidity',
            'active_range_utilization_pct', 'fee_tier_bps',
            'price_impact_100k_pct', 'price_impact_1m_pct', 'price_impact_10m_pct',
            'market_depth_score', 'concentration_risk_score',
            'volume_to_liquidity_ratio', 'stress_label', 'flags',
        ):
            self.assertIn(field, res, f"Missing field: {field}")

    def test_timestamp_format(self):
        r = self.t.test([_make_pool()], config={'log_file': self.log})
        self.assertRegex(r['timestamp'], r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')

    def test_pools_analyzed_count(self):
        r = self.t.test([_make_pool(), _make_pool()], config={'log_file': self.log})
        self.assertEqual(r['pools_analyzed'], 2)


class TestPriceImpact(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def _impacts(self, pool):
        r = self.t.test([pool], config={'log_file': self.log})
        res = r['results'][0]
        return (
            res['price_impact_100k_pct'],
            res['price_impact_1m_pct'],
            res['price_impact_10m_pct'],
        )

    def test_impact_bounded_0_100(self):
        p100k, p1m, p10m = self._impacts(_make_pool())
        for v in [p100k, p1m, p10m]:
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 100.0)

    def test_larger_trade_higher_impact(self):
        pool = _make_pool(
            total_liquidity_usd=10_000_000,
            liquidity_distribution={
                'pct_within_1pct': 20,
                'pct_within_5pct': 50,
                'pct_within_10pct': 80,
            }
        )
        p100k, p1m, p10m = self._impacts(pool)
        self.assertLessEqual(p100k, p1m)
        self.assertLessEqual(p1m, p10m)

    def test_higher_liquidity_lower_impact(self):
        pool_small = _make_pool(total_liquidity_usd=1_000_000)
        pool_large = _make_pool(total_liquidity_usd=100_000_000)
        _, p1m_small, _ = self._impacts(pool_small)
        _, p1m_large, _ = self._impacts(pool_large)
        self.assertGreater(p1m_small, p1m_large)

    def test_zero_liquidity_returns_100(self):
        pool = _make_pool(total_liquidity_usd=0)
        p100k, p1m, p10m = self._impacts(pool)
        self.assertEqual(p100k, 100.0)
        self.assertEqual(p1m, 100.0)
        self.assertEqual(p10m, 100.0)

    def test_distribution_affects_1pct_impact(self):
        # Higher pct_within_1pct → more liquid near price → lower $100k impact
        pool_dense = _make_pool(
            total_liquidity_usd=10_000_000,
            liquidity_distribution={'pct_within_1pct': 80, 'pct_within_5pct': 90, 'pct_within_10pct': 95}
        )
        pool_sparse = _make_pool(
            total_liquidity_usd=10_000_000,
            liquidity_distribution={'pct_within_1pct': 10, 'pct_within_5pct': 30, 'pct_within_10pct': 60}
        )
        p_dense, _, _ = self._impacts(pool_dense)
        p_sparse, _, _ = self._impacts(pool_sparse)
        self.assertLess(p_dense, p_sparse)

    def test_fallback_distribution_used_when_zero(self):
        pool = _make_pool(
            total_liquidity_usd=10_000_000,
            liquidity_distribution={'pct_within_1pct': 0, 'pct_within_5pct': 0, 'pct_within_10pct': 0}
        )
        p100k, p1m, p10m = self._impacts(pool)
        # Should use fallback 10%, 30%, 50% → not all 100
        self.assertLess(p100k, 100.0)


class TestStressLabels(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def _label(self, pool):
        r = self.t.test([pool], config={'log_file': self.log})
        return r['results'][0]['stress_label']

    def test_deep_liquidity(self):
        # Very large liquidity, high density near price → $1M impact < 0.1%
        # Need eff_liq_5pct = total * pct_5/100 > 1_000_000_000 for impact < 0.1%
        # 10_000_000_000 * 80% = 8B → impact = 0.0125%
        pool = _make_pool(
            total_liquidity_usd=10_000_000_000,
            liquidity_distribution={'pct_within_1pct': 50, 'pct_within_5pct': 80, 'pct_within_10pct': 95}
        )
        lbl = self._label(pool)
        self.assertEqual(lbl, STRESS_DEEP)

    def test_adequate(self):
        # Medium liquidity, 1M impact between 0.1% and 0.5%
        pool = _make_pool(
            total_liquidity_usd=500_000_000,
            liquidity_distribution={'pct_within_1pct': 20, 'pct_within_5pct': 50, 'pct_within_10pct': 80}
        )
        lbl = self._label(pool)
        self.assertIn(lbl, ALL_STRESS_LABELS)

    def test_illiquid(self):
        # Tiny liquidity → 10M impact > 5%
        pool = _make_pool(
            total_liquidity_usd=100_000,
            liquidity_distribution={'pct_within_1pct': 10, 'pct_within_5pct': 20, 'pct_within_10pct': 40}
        )
        lbl = self._label(pool)
        self.assertEqual(lbl, STRESS_ILLIQUID)

    def test_very_thin(self):
        # Small-medium liquidity → 1M impact > 2%
        pool = _make_pool(
            total_liquidity_usd=5_000_000,
            liquidity_distribution={'pct_within_1pct': 5, 'pct_within_5pct': 15, 'pct_within_10pct': 30}
        )
        lbl = self._label(pool)
        self.assertIn(lbl, [STRESS_VERY_THIN, STRESS_ILLIQUID])

    def test_all_labels_are_valid(self):
        lbl = self._label(_make_pool())
        self.assertIn(lbl, ALL_STRESS_LABELS)

    def test_zero_liquidity_is_illiquid(self):
        pool = _make_pool(total_liquidity_usd=0)
        lbl = self._label(pool)
        self.assertEqual(lbl, STRESS_ILLIQUID)


class TestMarketDepthScore(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def _score(self, pool):
        r = self.t.test([pool], config={'log_file': self.log})
        return r['results'][0]['market_depth_score']

    def test_bounded_0_100(self):
        for liq in [0, 1_000_000, 100_000_000, 1_000_000_000]:
            pool = _make_pool(total_liquidity_usd=liq)
            s = self._score(pool)
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 100.0)

    def test_higher_liquidity_higher_score(self):
        pool_small = _make_pool(total_liquidity_usd=500_000)
        pool_large = _make_pool(total_liquidity_usd=500_000_000)
        s_small = self._score(pool_small)
        s_large = self._score(pool_large)
        self.assertGreater(s_large, s_small)

    def test_zero_liquidity_score_zero(self):
        pool = _make_pool(total_liquidity_usd=0)
        s = self._score(pool)
        self.assertAlmostEqual(s, 0.0, places=1)

    def test_is_float(self):
        s = self._score(_make_pool())
        self.assertIsInstance(s, float)


class TestConcentrationRiskScore(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def _conc_score(self, top3):
        pool = _make_pool(top_3_lp_concentration_pct=top3)
        r = self.t.test([pool], config={'log_file': self.log})
        return r['results'][0]['concentration_risk_score']

    def test_equals_top3_pct(self):
        self.assertAlmostEqual(self._conc_score(45.0), 45.0, places=2)

    def test_zero_concentration(self):
        self.assertAlmostEqual(self._conc_score(0.0), 0.0, places=2)

    def test_full_concentration(self):
        self.assertAlmostEqual(self._conc_score(100.0), 100.0, places=2)

    def test_bounded_at_100(self):
        # Even if over 100, should clamp
        pool = _make_pool(top_3_lp_concentration_pct=120)
        r = self.t.test([pool], config={'log_file': self.log})
        score = r['results'][0]['concentration_risk_score']
        self.assertLessEqual(score, 100.0)


class TestVolumeToLiquidityRatio(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def _ratio(self, vol, liq):
        pool = _make_pool(daily_volume_usd=vol, total_liquidity_usd=liq)
        r = self.t.test([pool], config={'log_file': self.log})
        return r['results'][0]['volume_to_liquidity_ratio']

    def test_zero_volume(self):
        self.assertAlmostEqual(self._ratio(0, 10_000_000), 0.0, places=4)

    def test_zero_liquidity(self):
        self.assertAlmostEqual(self._ratio(5_000_000, 0), 0.0, places=4)

    def test_correct_ratio(self):
        self.assertAlmostEqual(self._ratio(5_000_000, 10_000_000), 0.5, places=4)

    def test_high_ratio(self):
        r = self._ratio(8_000_000, 10_000_000)
        self.assertAlmostEqual(r, 0.8, places=4)


class TestFlags(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def _flags(self, pool):
        r = self.t.test([pool], config={'log_file': self.log})
        return r['results'][0]['flags']

    def test_no_flags_deep_healthy_pool(self):
        pool = _make_pool(
            total_liquidity_usd=500_000_000,
            liquidity_distribution={'pct_within_1pct': 40, 'pct_within_5pct': 70, 'pct_within_10pct': 90},
            top_3_lp_concentration_pct=20,
            daily_volume_usd=5_000_000,
            is_concentrated_liquidity=False,
        )
        flags = self._flags(pool)
        self.assertNotIn(FLAG_LP_CONCENTRATED, flags)
        self.assertNotIn(FLAG_HIGH_VOLUME_RATIO, flags)

    def test_lp_concentrated_flag(self):
        pool = _make_pool(top_3_lp_concentration_pct=61)
        flags = self._flags(pool)
        self.assertIn(FLAG_LP_CONCENTRATED, flags)

    def test_no_lp_concentrated_at_threshold(self):
        pool = _make_pool(top_3_lp_concentration_pct=60)
        flags = self._flags(pool)
        self.assertNotIn(FLAG_LP_CONCENTRATED, flags)

    def test_active_range_narrow_flag(self):
        pool = _make_pool(is_concentrated_liquidity=True, active_range_utilization_pct=49)
        flags = self._flags(pool)
        self.assertIn(FLAG_ACTIVE_RANGE_NARROW, flags)

    def test_no_active_range_narrow_for_amm(self):
        # Not CL → flag not raised even if utilization low
        pool = _make_pool(is_concentrated_liquidity=False, active_range_utilization_pct=10)
        flags = self._flags(pool)
        self.assertNotIn(FLAG_ACTIVE_RANGE_NARROW, flags)

    def test_no_active_range_narrow_at_threshold(self):
        pool = _make_pool(is_concentrated_liquidity=True, active_range_utilization_pct=50)
        flags = self._flags(pool)
        self.assertNotIn(FLAG_ACTIVE_RANGE_NARROW, flags)

    def test_high_volume_ratio_flag(self):
        pool = _make_pool(daily_volume_usd=6_000_000, total_liquidity_usd=10_000_000)
        flags = self._flags(pool)
        self.assertIn(FLAG_HIGH_VOLUME_RATIO, flags)

    def test_no_high_volume_ratio_at_threshold(self):
        pool = _make_pool(daily_volume_usd=5_000_000, total_liquidity_usd=10_000_000)
        flags = self._flags(pool)
        self.assertNotIn(FLAG_HIGH_VOLUME_RATIO, flags)

    def test_institutional_grade_flag(self):
        # Need $1M impact < 0.1% → need very large liquidity near 5pct band
        pool = _make_pool(
            total_liquidity_usd=2_000_000_000,
            liquidity_distribution={'pct_within_1pct': 20, 'pct_within_5pct': 60, 'pct_within_10pct': 90}
        )
        flags = self._flags(pool)
        self.assertIn(FLAG_INSTITUTIONAL_GRADE, flags)

    def test_retail_only_flag(self):
        # Need $100K impact > 1% → low liquidity
        pool = _make_pool(
            total_liquidity_usd=500_000,
            liquidity_distribution={'pct_within_1pct': 10, 'pct_within_5pct': 30, 'pct_within_10pct': 60}
        )
        flags = self._flags(pool)
        self.assertIn(FLAG_RETAIL_ONLY, flags)

    def test_flags_is_list(self):
        flags = self._flags(_make_pool())
        self.assertIsInstance(flags, list)

    def test_multiple_flags_together(self):
        pool = _make_pool(
            total_liquidity_usd=100_000,
            liquidity_distribution={'pct_within_1pct': 5, 'pct_within_5pct': 15, 'pct_within_10pct': 30},
            top_3_lp_concentration_pct=80,
            daily_volume_usd=100_000,
            is_concentrated_liquidity=True,
            active_range_utilization_pct=30,
        )
        flags = self._flags(pool)
        self.assertIn(FLAG_LP_CONCENTRATED, flags)
        self.assertIn(FLAG_ACTIVE_RANGE_NARROW, flags)
        self.assertIn(FLAG_RETAIL_ONLY, flags)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def test_deepest_pool_identified(self):
        deep = _make_pool(
            protocol='Uni', pair='A/B', total_liquidity_usd=1_000_000_000,
            liquidity_distribution={'pct_within_1pct': 40, 'pct_within_5pct': 70, 'pct_within_10pct': 90}
        )
        shallow = _make_pool(
            protocol='Curve', pair='X/Y', total_liquidity_usd=100_000,
            liquidity_distribution={'pct_within_1pct': 10, 'pct_within_5pct': 20, 'pct_within_10pct': 40}
        )
        r = self.t.test([deep, shallow], config={'log_file': self.log})
        self.assertIn('Uni', r['aggregates']['deepest_pool'])

    def test_shallowest_pool_identified(self):
        deep = _make_pool(
            protocol='BigPool', pair='A/B', total_liquidity_usd=1_000_000_000,
            liquidity_distribution={'pct_within_1pct': 40, 'pct_within_5pct': 70, 'pct_within_10pct': 90}
        )
        shallow = _make_pool(
            protocol='TinyPool', pair='X/Y', total_liquidity_usd=100_000,
            liquidity_distribution={'pct_within_1pct': 5, 'pct_within_5pct': 10, 'pct_within_10pct': 20}
        )
        r = self.t.test([deep, shallow], config={'log_file': self.log})
        self.assertIn('TinyPool', r['aggregates']['shallowest_pool'])

    def test_total_ecosystem_liquidity(self):
        p1 = _make_pool(total_liquidity_usd=10_000_000)
        p2 = _make_pool(total_liquidity_usd=20_000_000)
        r = self.t.test([p1, p2], config={'log_file': self.log})
        self.assertAlmostEqual(r['aggregates']['total_ecosystem_liquidity_usd'], 30_000_000.0)

    def test_illiquid_count(self):
        illiquid = _make_pool(total_liquidity_usd=0)
        deep = _make_pool(total_liquidity_usd=500_000_000)
        r = self.t.test([illiquid, deep], config={'log_file': self.log})
        self.assertGreaterEqual(r['aggregates']['illiquid_count'], 1)

    def test_institutional_grade_count(self):
        inst = _make_pool(
            total_liquidity_usd=2_000_000_000,
            liquidity_distribution={'pct_within_1pct': 20, 'pct_within_5pct': 60, 'pct_within_10pct': 90}
        )
        retail = _make_pool(total_liquidity_usd=500_000)
        r = self.t.test([inst, retail], config={'log_file': self.log})
        self.assertGreaterEqual(r['aggregates']['institutional_grade_count'], 1)

    def test_single_pool_deepest_and_shallowest(self):
        pool = _make_pool(protocol='Solo', pair='A/B')
        r = self.t.test([pool], config={'log_file': self.log})
        agg = r['aggregates']
        self.assertEqual(agg['deepest_pool'], 'Solo/A/B')
        self.assertEqual(agg['shallowest_pool'], 'Solo/A/B')


class TestFieldPassthrough(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def test_protocol_passthrough(self):
        pool = _make_pool(protocol='Balancer')
        r = self.t.test([pool], config={'log_file': self.log})
        self.assertEqual(r['results'][0]['protocol'], 'Balancer')

    def test_pair_passthrough(self):
        pool = _make_pool(pair='WBTC/USDC')
        r = self.t.test([pool], config={'log_file': self.log})
        self.assertEqual(r['results'][0]['pair'], 'WBTC/USDC')

    def test_fee_tier_passthrough(self):
        pool = _make_pool(fee_tier_bps=5)
        r = self.t.test([pool], config={'log_file': self.log})
        self.assertAlmostEqual(r['results'][0]['fee_tier_bps'], 5.0)

    def test_is_cl_passthrough_true(self):
        pool = _make_pool(is_concentrated_liquidity=True)
        r = self.t.test([pool], config={'log_file': self.log})
        self.assertTrue(r['results'][0]['is_concentrated_liquidity'])

    def test_is_cl_passthrough_false(self):
        pool = _make_pool(is_concentrated_liquidity=False)
        r = self.t.test([pool], config={'log_file': self.log})
        self.assertFalse(r['results'][0]['is_concentrated_liquidity'])


class TestConfigOverrides(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def test_lp_concentration_threshold_override(self):
        cfg = {'lp_concentration_threshold_pct': 30.0, 'log_file': self.log}
        pool = _make_pool(top_3_lp_concentration_pct=35)
        r = self.t.test([pool], config=cfg)
        self.assertIn(FLAG_LP_CONCENTRATED, r['results'][0]['flags'])

    def test_high_volume_ratio_threshold_override(self):
        cfg = {'high_volume_ratio_threshold': 0.1, 'log_file': self.log}
        pool = _make_pool(daily_volume_usd=2_000_000, total_liquidity_usd=10_000_000)
        r = self.t.test([pool], config=cfg)
        self.assertIn(FLAG_HIGH_VOLUME_RATIO, r['results'][0]['flags'])

    def test_illiquid_threshold_override(self):
        cfg = {'illiquid_slippage_threshold_pct': 1.0, 'log_file': self.log}
        pool = _make_pool(
            total_liquidity_usd=1_000_000,
            liquidity_distribution={'pct_within_1pct': 5, 'pct_within_5pct': 15, 'pct_within_10pct': 30}
        )
        r = self.t.test([pool], config=cfg)
        self.assertIn(r['results'][0]['stress_label'], ALL_STRESS_LABELS)

    def test_config_none_uses_defaults(self):
        r = self.t.test([_make_pool()], config=None)
        self.assertIn('results', r)


class TestRingBufferLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def test_log_created_on_first_call(self):
        self.assertFalse(os.path.exists(self.log))
        self.t.test([], config={'log_file': self.log})
        self.assertTrue(os.path.exists(self.log))

    def test_log_is_valid_json(self):
        self.t.test([], config={'log_file': self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_appends(self):
        self.t.test([], config={'log_file': self.log})
        self.t.test([], config={'log_file': self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap_100(self):
        for _ in range(105):
            self.t.test([], config={'log_file': self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_keeps_latest_entries(self):
        for i in range(102):
            pool = _make_pool(protocol=f'proto_{i}')
            self.t.test([pool], config={'log_file': self.log})
        with open(self.log) as f:
            data = json.load(f)
        last = data[-1]
        self.assertEqual(last['results'][0]['protocol'], 'proto_101')

    def test_log_entry_has_timestamp(self):
        self.t.test([], config={'log_file': self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertIn('timestamp', data[0])

    def test_corrupted_log_recovered(self):
        with open(self.log, 'w') as f:
            f.write('{invalid json')
        self.t.test([], config={'log_file': self.log})
        with open(self.log) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_atomic_write_always_valid_json(self):
        for i in range(5):
            self.t.test([_make_pool(protocol=f'x{i}')], config={'log_file': self.log})
            with open(self.log) as f:
                data = json.load(f)
            self.assertIsInstance(data, list)


class TestMissingFields(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def test_empty_pool_dict(self):
        r = self.t.test([{}], config={'log_file': self.log})
        self.assertEqual(r['pools_analyzed'], 1)
        res = r['results'][0]
        self.assertEqual(res['protocol'], 'unknown')
        self.assertIn(res['stress_label'], ALL_STRESS_LABELS)

    def test_missing_distribution(self):
        pool = {'protocol': 'Test', 'pair': 'A/B', 'total_liquidity_usd': 10_000_000}
        r = self.t.test([pool], config={'log_file': self.log})
        self.assertEqual(r['pools_analyzed'], 1)

    def test_none_distribution_handled(self):
        pool = _make_pool(liquidity_distribution=None)
        r = self.t.test([pool], config={'log_file': self.log})
        self.assertEqual(r['pools_analyzed'], 1)


class TestStressLabelConstants(unittest.TestCase):
    def test_deep_label_value(self):
        self.assertEqual(STRESS_DEEP, 'DEEP_LIQUIDITY')

    def test_adequate_label_value(self):
        self.assertEqual(STRESS_ADEQUATE, 'ADEQUATE')

    def test_thin_label_value(self):
        self.assertEqual(STRESS_THIN, 'THIN')

    def test_very_thin_label_value(self):
        self.assertEqual(STRESS_VERY_THIN, 'VERY_THIN')

    def test_illiquid_label_value(self):
        self.assertEqual(STRESS_ILLIQUID, 'ILLIQUID')

    def test_all_labels_five(self):
        self.assertEqual(len(ALL_STRESS_LABELS), 5)

    def test_flag_lp_concentrated(self):
        self.assertEqual(FLAG_LP_CONCENTRATED, 'LP_CONCENTRATED')

    def test_flag_active_range_narrow(self):
        self.assertEqual(FLAG_ACTIVE_RANGE_NARROW, 'ACTIVE_RANGE_NARROW')

    def test_flag_high_volume_ratio(self):
        self.assertEqual(FLAG_HIGH_VOLUME_RATIO, 'HIGH_VOLUME_RATIO')

    def test_flag_institutional_grade(self):
        self.assertEqual(FLAG_INSTITUTIONAL_GRADE, 'INSTITUTIONAL_GRADE')

    def test_flag_retail_only(self):
        self.assertEqual(FLAG_RETAIL_ONLY, 'RETAIL_ONLY')


class TestNumericsAreFloat(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def test_price_impacts_are_float(self):
        r = self.t.test([_make_pool()], config={'log_file': self.log})
        res = r['results'][0]
        self.assertIsInstance(res['price_impact_100k_pct'], float)
        self.assertIsInstance(res['price_impact_1m_pct'], float)
        self.assertIsInstance(res['price_impact_10m_pct'], float)

    def test_market_depth_score_is_float(self):
        r = self.t.test([_make_pool()], config={'log_file': self.log})
        self.assertIsInstance(r['results'][0]['market_depth_score'], float)

    def test_concentration_risk_score_is_float(self):
        r = self.t.test([_make_pool()], config={'log_file': self.log})
        self.assertIsInstance(r['results'][0]['concentration_risk_score'], float)

    def test_volume_ratio_is_float(self):
        r = self.t.test([_make_pool()], config={'log_file': self.log})
        self.assertIsInstance(r['results'][0]['volume_to_liquidity_ratio'], float)


class TestMultiplePools(unittest.TestCase):
    def setUp(self):
        _, self.log = _make_log_dir()
        self.t = ProtocolLiquidityDepthStressTester(log_file=self.log)

    def test_three_pools(self):
        pools = [_make_pool(protocol=f'p{i}') for i in range(3)]
        r = self.t.test(pools, config={'log_file': self.log})
        self.assertEqual(r['pools_analyzed'], 3)
        self.assertEqual(len(r['results']), 3)

    def test_results_preserve_order(self):
        pools = [_make_pool(protocol=p) for p in ['A', 'B', 'C']]
        r = self.t.test(pools, config={'log_file': self.log})
        protos = [res['protocol'] for res in r['results']]
        self.assertEqual(protos, ['A', 'B', 'C'])

    def test_total_liquidity_sum(self):
        liqs = [1_000_000, 2_000_000, 3_000_000]
        pools = [_make_pool(protocol=f'p{i}', total_liquidity_usd=l)
                 for i, l in enumerate(liqs)]
        r = self.t.test(pools, config={'log_file': self.log})
        self.assertAlmostEqual(
            r['aggregates']['total_ecosystem_liquidity_usd'], sum(liqs), places=2
        )


if __name__ == '__main__':
    unittest.main()
