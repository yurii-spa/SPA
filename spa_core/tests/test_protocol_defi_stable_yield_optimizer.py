"""
Tests for MP-1021: ProtocolDeFiStableYieldOptimizer
Run with: python3 -m unittest spa_core.tests.test_protocol_defi_stable_yield_optimizer
"""
import json
import os
import sys
import tempfile
import unittest

_SRC = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, _SRC)

from spa_core.analytics.protocol_defi_stable_yield_optimizer import (
    ProtocolDeFiStableYieldOptimizer,
    DEFAULT_CONFIG,
    VALID_LABELS,
    VALID_FLAGS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_opp(**kwargs):
    defaults = {
        'name': 'TestOpp',
        'protocol': 'TestProtocol',
        'stablecoin': 'USDC',
        'yield_type': 'lending',
        'current_apy_pct': 5.0,
        'apy_7d_avg_pct': 4.8,
        'apy_30d_avg_pct': 4.5,
        'apy_volatility_pct': 0.5,
        'smart_contract_risk_score': 20.0,
        'protocol_age_days': 900,
        'tvl_usd': 500_000_000,
        'stablecoin_peg_score': 99.0,
        'max_single_allocation_usd': 100_000,
        'gas_cost_to_enter_usd': 10.0,
        'gas_cost_to_exit_usd': 10.0,
        'lockup_days': 0,
    }
    defaults.update(kwargs)
    return defaults


def _make_optimizer(tmp_dir):
    cfg = {
        'log_path': os.path.join(tmp_dir, 'stable_yield_optimizer_log.json'),
        'log_cap': 100,
    }
    return ProtocolDeFiStableYieldOptimizer(config=cfg)


# ===========================================================================
# 1. Return structure tests
# ===========================================================================

class TestReturnStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = _make_optimizer(self.tmp)

    def test_optimize_returns_dict(self):
        result = self.opt.optimize([_make_opp()])
        self.assertIsInstance(result, dict)

    def test_result_has_opportunities(self):
        result = self.opt.optimize([_make_opp()])
        self.assertIn('opportunities', result)

    def test_result_has_top_opportunity(self):
        result = self.opt.optimize([_make_opp()])
        self.assertIn('top_opportunity', result)

    def test_result_has_avoid_list(self):
        result = self.opt.optimize([_make_opp()])
        self.assertIn('avoid_list', result)

    def test_result_has_total_yield_weighted_apy(self):
        result = self.opt.optimize([_make_opp()])
        self.assertIn('total_yield_weighted_apy', result)

    def test_result_has_top_allocation_count(self):
        result = self.opt.optimize([_make_opp()])
        self.assertIn('top_allocation_count', result)

    def test_result_has_avoid_count(self):
        result = self.opt.optimize([_make_opp()])
        self.assertIn('avoid_count', result)

    def test_result_has_recommended_portfolio(self):
        result = self.opt.optimize([_make_opp()])
        self.assertIn('recommended_portfolio', result)

    def test_result_has_total_analyzed(self):
        result = self.opt.optimize([_make_opp()])
        self.assertIn('total_analyzed', result)

    def test_empty_list_returns_dict(self):
        result = self.opt.optimize([])
        self.assertIsInstance(result, dict)

    def test_empty_total_analyzed_zero(self):
        result = self.opt.optimize([])
        self.assertEqual(result['total_analyzed'], 0)

    def test_empty_top_opportunity_none(self):
        result = self.opt.optimize([])
        self.assertIsNone(result['top_opportunity'])

    def test_none_input_returns_dict(self):
        result = self.opt.optimize(None)
        self.assertIsInstance(result, dict)


# ===========================================================================
# 2. Per-opportunity metric keys
# ===========================================================================

class TestOpportunityMetricKeys(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = _make_optimizer(self.tmp)

    def _first(self, opps=None):
        if opps is None:
            opps = [_make_opp()]
        return self.opt.optimize(opps)['opportunities'][0]

    def test_name_preserved(self):
        o = _make_opp(name='AaveUSDC')
        self.assertEqual(self._first([o])['name'], 'AaveUSDC')

    def test_protocol_preserved(self):
        o = _make_opp(protocol='Aave')
        self.assertEqual(self._first([o])['protocol'], 'Aave')

    def test_stablecoin_preserved(self):
        o = _make_opp(stablecoin='DAI')
        self.assertEqual(self._first([o])['stablecoin'], 'DAI')

    def test_yield_type_preserved(self):
        o = _make_opp(yield_type='lp_fees')
        self.assertEqual(self._first([o])['yield_type'], 'lp_fees')

    def test_has_risk_adjusted_apy(self):
        self.assertIn('risk_adjusted_apy', self._first())

    def test_has_net_apy_after_gas(self):
        self.assertIn('net_apy_after_gas', self._first())

    def test_has_stability_score(self):
        self.assertIn('stability_score', self._first())

    def test_has_yield_per_risk_unit(self):
        self.assertIn('yield_per_risk_unit', self._first())

    def test_has_optimal_allocation_pct(self):
        self.assertIn('optimal_allocation_pct', self._first())

    def test_has_label(self):
        self.assertIn('label', self._first())

    def test_has_flags(self):
        self.assertIn('flags', self._first())

    def test_flags_is_list(self):
        self.assertIsInstance(self._first()['flags'], list)

    def test_no_raw_weight_key_in_output(self):
        # _raw_weight is an internal field — must not appear in final output
        self.assertNotIn('_raw_weight', self._first())


# ===========================================================================
# 3. Metric computation correctness
# ===========================================================================

class TestMetricComputation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = _make_optimizer(self.tmp)

    def test_risk_adjusted_apy_correct(self):
        # apy=10, sc_risk=20, peg=100 → 10 × 0.8 × 1.0 = 8.0
        o = _make_opp(current_apy_pct=10.0, smart_contract_risk_score=20.0, stablecoin_peg_score=100.0)
        r = self.opt.optimize([o])['opportunities'][0]
        self.assertAlmostEqual(r['risk_adjusted_apy'], 8.0, places=5)

    def test_risk_adjusted_apy_zero_for_full_risk(self):
        o = _make_opp(current_apy_pct=10.0, smart_contract_risk_score=100.0)
        r = self.opt.optimize([o])['opportunities'][0]
        self.assertAlmostEqual(r['risk_adjusted_apy'], 0.0, places=5)

    def test_net_apy_less_than_risk_adj_when_gas(self):
        o = _make_opp(gas_cost_to_enter_usd=25.0, gas_cost_to_exit_usd=25.0)
        r = self.opt.optimize([o])['opportunities'][0]
        self.assertLessEqual(r['net_apy_after_gas'], r['risk_adjusted_apy'])

    def test_stability_score_in_range(self):
        r = self.opt.optimize([_make_opp()])['opportunities'][0]
        self.assertGreaterEqual(r['stability_score'], 0.0)
        self.assertLessEqual(r['stability_score'], 100.0)

    def test_old_large_protocol_high_stability(self):
        o = _make_opp(protocol_age_days=1825, tvl_usd=1_000_000_000,
                      apy_volatility_pct=0.0, stablecoin_peg_score=100.0)
        r = self.opt.optimize([o])['opportunities'][0]
        self.assertGreater(r['stability_score'], 80.0)

    def test_young_small_protocol_low_stability(self):
        o = _make_opp(protocol_age_days=10, tvl_usd=100_000,
                      apy_volatility_pct=20.0, stablecoin_peg_score=70.0)
        r = self.opt.optimize([o])['opportunities'][0]
        self.assertLess(r['stability_score'], 50.0)

    def test_yield_per_risk_unit_positive(self):
        r = self.opt.optimize([_make_opp()])['opportunities'][0]
        self.assertGreaterEqual(r['yield_per_risk_unit'], 0.0)

    def test_high_risk_reduces_yield_per_risk(self):
        low = _make_opp(smart_contract_risk_score=10)
        high = _make_opp(smart_contract_risk_score=80)
        r_low = self.opt.optimize([low])['opportunities'][0]
        r_high = self.opt.optimize([high])['opportunities'][0]
        self.assertGreater(r_low['yield_per_risk_unit'], r_high['yield_per_risk_unit'])

    def test_optimal_allocation_sums_100(self):
        opps = [_make_opp(name=f'O{i}') for i in range(5)]
        result = self.opt.optimize(opps)
        total = sum(r['optimal_allocation_pct'] for r in result['opportunities'])
        self.assertAlmostEqual(total, 100.0, places=2)

    def test_single_opportunity_allocation_100(self):
        result = self.opt.optimize([_make_opp()])
        self.assertAlmostEqual(result['opportunities'][0]['optimal_allocation_pct'], 100.0, places=2)

    def test_optimal_allocation_non_negative(self):
        opps = [_make_opp(name=f'O{i}') for i in range(3)]
        result = self.opt.optimize(opps)
        for r in result['opportunities']:
            self.assertGreaterEqual(r['optimal_allocation_pct'], 0.0)

    def test_peg_reduction_reduces_risk_adj_apy(self):
        high_peg = _make_opp(stablecoin_peg_score=100.0)
        low_peg = _make_opp(stablecoin_peg_score=80.0)
        r_high = self.opt.optimize([high_peg])['opportunities'][0]
        r_low = self.opt.optimize([low_peg])['opportunities'][0]
        self.assertGreater(r_high['risk_adjusted_apy'], r_low['risk_adjusted_apy'])


# ===========================================================================
# 4. Label tests
# ===========================================================================

class TestLabels(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = _make_optimizer(self.tmp)

    def _label(self, **kwargs):
        return self.opt.optimize([_make_opp(**kwargs)])['opportunities'][0]['label']

    def test_label_is_valid(self):
        self.assertIn(self._label(), VALID_LABELS)

    def test_avoid_high_sc_risk(self):
        label = self._label(smart_contract_risk_score=85.0)
        self.assertEqual(label, 'AVOID')

    def test_avoid_low_peg(self):
        label = self._label(stablecoin_peg_score=75.0)
        self.assertEqual(label, 'AVOID')

    def test_avoid_exactly_at_threshold(self):
        # sc_risk > 80 → AVOID; sc_risk = 81
        label = self._label(smart_contract_risk_score=81.0)
        self.assertEqual(label, 'AVOID')

    def test_low_priority_mid_sc_risk(self):
        label = self._label(smart_contract_risk_score=65.0, stablecoin_peg_score=92.0)
        self.assertEqual(label, 'LOW_PRIORITY')

    def test_low_priority_borderline_peg(self):
        label = self._label(smart_contract_risk_score=10.0, stablecoin_peg_score=88.0)
        self.assertEqual(label, 'LOW_PRIORITY')

    def test_top_allocation_excellent(self):
        # risk_adj_apy > 8: need current_apy high enough with low risk/good peg
        # apy=12, sc=0, peg=100 → risk_adj=12 > 8; stability needs > 80
        o = _make_opp(
            current_apy_pct=12.0,
            smart_contract_risk_score=0.0,
            stablecoin_peg_score=100.0,
            protocol_age_days=1825,
            tvl_usd=1_000_000_000,
            apy_volatility_pct=0.0,
            gas_cost_to_enter_usd=0.0,
            gas_cost_to_exit_usd=0.0,
        )
        label = self.opt.optimize([o])['opportunities'][0]['label']
        self.assertEqual(label, 'TOP_ALLOCATION')

    def test_high_priority_good_params(self):
        # risk_adj_apy > 5, stability > 60, but sc_risk ≤ 60, peg ≥ 90
        o = _make_opp(
            current_apy_pct=8.0,
            smart_contract_risk_score=30.0,
            stablecoin_peg_score=96.0,
            protocol_age_days=500,
            tvl_usd=200_000_000,
            apy_volatility_pct=1.0,
        )
        label = self.opt.optimize([o])['opportunities'][0]['label']
        self.assertEqual(label, 'HIGH_PRIORITY')

    def test_standard_label_default_opp(self):
        # Default opp: sc=20, peg=99 → not AVOID or LOW_PRIORITY
        # apy=5, sc=20, peg=99 → risk_adj=5*0.8*0.99=3.96 < 5 → STANDARD
        o = _make_opp(current_apy_pct=5.0, smart_contract_risk_score=20.0, stablecoin_peg_score=99.0)
        label = self.opt.optimize([o])['opportunities'][0]['label']
        self.assertEqual(label, 'STANDARD')

    def test_all_valid_labels_in_set(self):
        self.assertEqual(VALID_LABELS, {'TOP_ALLOCATION', 'HIGH_PRIORITY', 'STANDARD', 'LOW_PRIORITY', 'AVOID'})


# ===========================================================================
# 5. Flag tests
# ===========================================================================

class TestFlags(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = _make_optimizer(self.tmp)

    def _flags(self, **kwargs):
        return self.opt.optimize([_make_opp(**kwargs)])['opportunities'][0]['flags']

    def test_high_risk_protocol_flag(self):
        self.assertIn('HIGH_RISK_PROTOCOL', self._flags(smart_contract_risk_score=75.0))

    def test_no_high_risk_protocol_below_threshold(self):
        self.assertNotIn('HIGH_RISK_PROTOCOL', self._flags(smart_contract_risk_score=60.0))

    def test_depeg_risk_flag(self):
        self.assertIn('DEPEG_RISK', self._flags(stablecoin_peg_score=85.0))

    def test_no_depeg_risk_good_peg(self):
        self.assertNotIn('DEPEG_RISK', self._flags(stablecoin_peg_score=99.0))

    def test_gas_inefficient_flag(self):
        # gas=60, max_alloc=5000 < 10000 → GAS_INEFFICIENT
        self.assertIn('GAS_INEFFICIENT', self._flags(
            gas_cost_to_enter_usd=35.0, gas_cost_to_exit_usd=30.0,
            max_single_allocation_usd=5_000,
        ))

    def test_no_gas_inefficient_large_allocation(self):
        # gas=60, max_alloc=50000 >= 10000 → not GAS_INEFFICIENT
        self.assertNotIn('GAS_INEFFICIENT', self._flags(
            gas_cost_to_enter_usd=35.0, gas_cost_to_exit_usd=30.0,
            max_single_allocation_usd=50_000,
        ))

    def test_no_gas_inefficient_low_gas(self):
        self.assertNotIn('GAS_INEFFICIENT', self._flags(
            gas_cost_to_enter_usd=10.0, gas_cost_to_exit_usd=10.0,
            max_single_allocation_usd=5_000,
        ))

    def test_established_protocol_flag(self):
        self.assertIn('ESTABLISHED_PROTOCOL', self._flags(
            protocol_age_days=800, tvl_usd=150_000_000,
        ))

    def test_no_established_protocol_too_young(self):
        self.assertNotIn('ESTABLISHED_PROTOCOL', self._flags(
            protocol_age_days=365, tvl_usd=200_000_000,
        ))

    def test_no_established_protocol_small_tvl(self):
        self.assertNotIn('ESTABLISHED_PROTOCOL', self._flags(
            protocol_age_days=900, tvl_usd=50_000_000,
        ))

    def test_real_yield_stable_flag(self):
        self.assertIn('REAL_YIELD_STABLE', self._flags(yield_type='real_yield'))

    def test_no_real_yield_stable_lending(self):
        self.assertNotIn('REAL_YIELD_STABLE', self._flags(yield_type='lending'))

    def test_instant_exit_flag(self):
        self.assertIn('INSTANT_EXIT', self._flags(lockup_days=0))

    def test_no_instant_exit_with_lockup(self):
        self.assertNotIn('INSTANT_EXIT', self._flags(lockup_days=7))

    def test_all_flags_valid(self):
        flags = self._flags(
            smart_contract_risk_score=75.0,
            stablecoin_peg_score=85.0,
            gas_cost_to_enter_usd=35.0,
            gas_cost_to_exit_usd=30.0,
            max_single_allocation_usd=5_000,
            protocol_age_days=800,
            tvl_usd=150_000_000,
            yield_type='real_yield',
            lockup_days=0,
        )
        for f in flags:
            self.assertIn(f, VALID_FLAGS)


# ===========================================================================
# 6. Aggregation tests
# ===========================================================================

class TestAggregation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = _make_optimizer(self.tmp)

    def test_total_analyzed_count(self):
        result = self.opt.optimize([_make_opp() for _ in range(4)])
        self.assertEqual(result['total_analyzed'], 4)

    def test_top_allocation_count_correct(self):
        excellent = _make_opp(
            current_apy_pct=12.0, smart_contract_risk_score=0.0,
            stablecoin_peg_score=100.0, protocol_age_days=1825,
            tvl_usd=1_000_000_000, apy_volatility_pct=0.0,
            gas_cost_to_enter_usd=0.0, gas_cost_to_exit_usd=0.0,
        )
        standard = _make_opp(current_apy_pct=3.0)
        result = self.opt.optimize([excellent, standard])
        self.assertGreaterEqual(result['top_allocation_count'], 1)

    def test_avoid_count_correct(self):
        avoid1 = _make_opp(smart_contract_risk_score=90.0)
        avoid2 = _make_opp(stablecoin_peg_score=70.0)
        normal = _make_opp()
        result = self.opt.optimize([avoid1, avoid2, normal])
        self.assertEqual(result['avoid_count'], 2)

    def test_avoid_list_contains_avoids(self):
        avoid = _make_opp(smart_contract_risk_score=90.0, name='Risky')
        normal = _make_opp()
        result = self.opt.optimize([avoid, normal])
        avoid_names = [r['name'] for r in result['avoid_list']]
        self.assertIn('Risky', avoid_names)

    def test_recommended_portfolio_sorted(self):
        opps = [_make_opp(name=f'O{i}') for i in range(5)]
        result = self.opt.optimize(opps)
        allocs = [r['optimal_allocation_pct'] for r in result['recommended_portfolio']]
        self.assertEqual(allocs, sorted(allocs, reverse=True))

    def test_total_yield_weighted_apy_non_negative(self):
        result = self.opt.optimize([_make_opp()])
        self.assertGreaterEqual(result['total_yield_weighted_apy'], 0.0)

    def test_top_opportunity_is_highest_allocation(self):
        opps = [_make_opp(name=f'O{i}') for i in range(4)]
        result = self.opt.optimize(opps)
        top = result['top_opportunity']
        max_alloc = max(r['optimal_allocation_pct'] for r in result['opportunities'])
        self.assertAlmostEqual(top['optimal_allocation_pct'], max_alloc, places=4)

    def test_opportunities_list_length(self):
        opps = [_make_opp() for _ in range(6)]
        result = self.opt.optimize(opps)
        self.assertEqual(len(result['opportunities']), 6)


# ===========================================================================
# 7. Ring-buffer log tests
# ===========================================================================

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, 'stable_yield_optimizer_log.json')
        self.opt = ProtocolDeFiStableYieldOptimizer(config={
            'log_path': self.log_path,
            'log_cap': 5,
        })

    def test_log_file_created(self):
        self.opt.optimize([_make_opp()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_valid_json_list(self):
        self.opt.optimize([_make_opp()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_ts(self):
        self.opt.optimize([_make_opp()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('ts', data[0])

    def test_log_entry_has_total_analyzed(self):
        self.opt.optimize([_make_opp()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('total_analyzed', data[0])

    def test_log_entry_has_top_allocation_count(self):
        self.opt.optimize([_make_opp()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('top_allocation_count', data[0])

    def test_log_entry_has_avoid_count(self):
        self.opt.optimize([_make_opp()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('avoid_count', data[0])

    def test_log_entry_has_top_opportunity_name(self):
        self.opt.optimize([_make_opp(name='AaveUSDC')])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('top_opportunity_name', data[0])

    def test_log_ring_buffer_cap(self):
        for _ in range(12):
            self.opt.optimize([_make_opp()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 5)

    def test_log_accumulates(self):
        self.opt.optimize([_make_opp()])
        self.opt.optimize([_make_opp()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_no_tmp_file_left(self):
        self.opt.optimize([_make_opp()])
        self.assertFalse(os.path.exists(self.log_path + '.tmp'))

    def test_total_yield_weighted_apy_in_log(self):
        self.opt.optimize([_make_opp()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('total_yield_weighted_apy', data[0])


# ===========================================================================
# 8. Edge case tests
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = _make_optimizer(self.tmp)

    def test_zero_apy_no_crash(self):
        result = self.opt.optimize([_make_opp(current_apy_pct=0.0)])
        self.assertIn('opportunities', result)

    def test_zero_tvl_no_crash(self):
        result = self.opt.optimize([_make_opp(tvl_usd=0)])
        self.assertIn('opportunities', result)

    def test_zero_gas_no_crash(self):
        result = self.opt.optimize([_make_opp(gas_cost_to_enter_usd=0.0, gas_cost_to_exit_usd=0.0)])
        r = result['opportunities'][0]
        self.assertAlmostEqual(r['net_apy_after_gas'], r['risk_adjusted_apy'], places=5)

    def test_lockup_nonzero_no_instant_exit(self):
        result = self.opt.optimize([_make_opp(lockup_days=30)])
        self.assertNotIn('INSTANT_EXIT', result['opportunities'][0]['flags'])

    def test_all_avoid_gives_zero_top_allocation(self):
        result = self.opt.optimize([
            _make_opp(smart_contract_risk_score=90.0),
            _make_opp(stablecoin_peg_score=70.0),
        ])
        self.assertEqual(result['top_allocation_count'], 0)

    def test_high_apy_volatility_reduces_stability(self):
        low_vol = _make_opp(apy_volatility_pct=0.0)
        high_vol = _make_opp(apy_volatility_pct=20.0)
        r_low = self.opt.optimize([low_vol])['opportunities'][0]
        r_high = self.opt.optimize([high_vol])['opportunities'][0]
        self.assertGreater(r_low['stability_score'], r_high['stability_score'])

    def test_all_zero_weights_give_equal_allocation(self):
        # If all weights are zero (e.g., all params are 0), allocation should split equally
        opps = [
            _make_opp(
                protocol_age_days=0, tvl_usd=0,
                apy_volatility_pct=20.0, stablecoin_peg_score=0.0,
                smart_contract_risk_score=100.0,
                current_apy_pct=0.0,
                gas_cost_to_enter_usd=0.0, gas_cost_to_exit_usd=0.0,
            )
            for _ in range(3)
        ]
        result = self.opt.optimize(opps)
        allocs = [r['optimal_allocation_pct'] for r in result['opportunities']]
        # All equal (within float precision)
        for a in allocs:
            self.assertAlmostEqual(a, allocs[0], places=3)

    def test_ten_opportunities_total_analyzed(self):
        result = self.opt.optimize([_make_opp() for _ in range(10)])
        self.assertEqual(result['total_analyzed'], 10)

    def test_default_constructor_works(self):
        opt = ProtocolDeFiStableYieldOptimizer()
        result = opt.optimize([_make_opp()])
        self.assertIn('opportunities', result)


# ===========================================================================
# 9. Config override tests
# ===========================================================================

class TestConfigOverrides(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_custom_avoid_sc_risk_threshold(self):
        # Lower AVOID threshold: 60 → sc_risk=65 should be AVOID
        opt = ProtocolDeFiStableYieldOptimizer(config={
            'log_path': os.path.join(self.tmp, 'log1.json'),
            'avoid_sc_risk': 60.0,
        })
        o = _make_opp(smart_contract_risk_score=65.0, stablecoin_peg_score=99.0)
        label = opt.optimize([o])['opportunities'][0]['label']
        self.assertEqual(label, 'AVOID')

    def test_custom_top_allocation_apy_threshold(self):
        opt = ProtocolDeFiStableYieldOptimizer(config={
            'log_path': os.path.join(self.tmp, 'log2.json'),
            'top_allocation_risk_adj_apy': 15.0,
        })
        # apy=12, sc=0, peg=100 → risk_adj=12, which is < 15 → not TOP
        o = _make_opp(
            current_apy_pct=12.0, smart_contract_risk_score=0.0,
            stablecoin_peg_score=100.0, protocol_age_days=1825,
            tvl_usd=1_000_000_000, apy_volatility_pct=0.0,
        )
        label = opt.optimize([o])['opportunities'][0]['label']
        self.assertNotEqual(label, 'TOP_ALLOCATION')

    def test_custom_log_cap(self):
        log_path = os.path.join(self.tmp, 'capped.json')
        opt = ProtocolDeFiStableYieldOptimizer(config={'log_path': log_path, 'log_cap': 3})
        for _ in range(9):
            opt.optimize([_make_opp()])
        with open(log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 3)

    def test_custom_established_age(self):
        opt = ProtocolDeFiStableYieldOptimizer(config={
            'log_path': os.path.join(self.tmp, 'log3.json'),
            'established_age_days': 200,
        })
        flags = opt.optimize([_make_opp(protocol_age_days=250, tvl_usd=200_000_000)])['opportunities'][0]['flags']
        self.assertIn('ESTABLISHED_PROTOCOL', flags)


# ===========================================================================
# 10. Constant / DEFAULT_CONFIG tests
# ===========================================================================

class TestConstants(unittest.TestCase):

    def test_default_config_has_log_path(self):
        self.assertIn('log_path', DEFAULT_CONFIG)

    def test_default_config_has_log_cap(self):
        self.assertIn('log_cap', DEFAULT_CONFIG)

    def test_default_log_cap_100(self):
        self.assertEqual(DEFAULT_CONFIG['log_cap'], 100)

    def test_default_avoid_sc_risk(self):
        self.assertEqual(DEFAULT_CONFIG['avoid_sc_risk'], 80.0)

    def test_default_avoid_peg(self):
        self.assertEqual(DEFAULT_CONFIG['avoid_peg'], 80.0)

    def test_valid_labels_count(self):
        self.assertEqual(len(VALID_LABELS), 5)

    def test_valid_flags_count(self):
        self.assertEqual(len(VALID_FLAGS), 6)

    def test_stability_weights_sum_to_one(self):
        w = (DEFAULT_CONFIG['stability_weight_age'] +
             DEFAULT_CONFIG['stability_weight_tvl'] +
             DEFAULT_CONFIG['stability_weight_apy_vol'] +
             DEFAULT_CONFIG['stability_weight_peg'])
        self.assertAlmostEqual(w, 1.0, places=5)

    def test_alloc_weights_sum_to_one(self):
        w = (DEFAULT_CONFIG['alloc_weight_stability'] +
             DEFAULT_CONFIG['alloc_weight_yield_per_risk'] +
             DEFAULT_CONFIG['alloc_weight_tvl'])
        self.assertAlmostEqual(w, 1.0, places=5)

    def test_top_allocation_label_in_valid(self):
        self.assertIn('TOP_ALLOCATION', VALID_LABELS)

    def test_avoid_label_in_valid(self):
        self.assertIn('AVOID', VALID_LABELS)

    def test_high_risk_flag_in_valid(self):
        self.assertIn('HIGH_RISK_PROTOCOL', VALID_FLAGS)

    def test_instant_exit_flag_in_valid(self):
        self.assertIn('INSTANT_EXIT', VALID_FLAGS)


# ===========================================================================
# 11. Multiple opportunities interaction
# ===========================================================================

class TestMultipleOpportunities(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.opt = _make_optimizer(self.tmp)

    def test_avoid_list_only_avoids(self):
        opps = [
            _make_opp(name='Good'),
            _make_opp(name='Bad1', smart_contract_risk_score=90.0),
            _make_opp(name='Bad2', stablecoin_peg_score=70.0),
        ]
        result = self.opt.optimize(opps)
        for r in result['avoid_list']:
            self.assertEqual(r['label'], 'AVOID')

    def test_recommended_portfolio_includes_all(self):
        opps = [_make_opp(name=f'O{i}') for i in range(5)]
        result = self.opt.optimize(opps)
        self.assertEqual(len(result['recommended_portfolio']), 5)

    def test_best_opportunity_gets_highest_allocation(self):
        best = _make_opp(
            name='Best',
            current_apy_pct=12.0, smart_contract_risk_score=0.0,
            stablecoin_peg_score=100.0, protocol_age_days=1825,
            tvl_usd=1_000_000_000, apy_volatility_pct=0.0,
            gas_cost_to_enter_usd=0.0, gas_cost_to_exit_usd=0.0,
        )
        worst = _make_opp(
            name='Worst',
            current_apy_pct=1.0, smart_contract_risk_score=70.0,
            stablecoin_peg_score=88.0, protocol_age_days=30,
            tvl_usd=10_000, apy_volatility_pct=15.0,
        )
        result = self.opt.optimize([best, worst])
        allocs = {r['name']: r['optimal_allocation_pct'] for r in result['opportunities']}
        self.assertGreater(allocs['Best'], allocs['Worst'])

    def test_stablecoin_types_preserved(self):
        opps = [
            _make_opp(name='A', stablecoin='USDC'),
            _make_opp(name='B', stablecoin='DAI'),
            _make_opp(name='C', stablecoin='FRAX'),
        ]
        result = self.opt.optimize(opps)
        coins = {r['stablecoin'] for r in result['opportunities']}
        self.assertEqual(coins, {'USDC', 'DAI', 'FRAX'})

    def test_yield_types_preserved(self):
        opps = [
            _make_opp(yield_type='lending'),
            _make_opp(yield_type='lp_fees'),
            _make_opp(yield_type='real_yield'),
            _make_opp(yield_type='points'),
        ]
        result = self.opt.optimize(opps)
        types = {r['yield_type'] for r in result['opportunities']}
        self.assertEqual(types, {'lending', 'lp_fees', 'real_yield', 'points'})

    def test_total_yield_weighted_apy_matches_manual(self):
        o1 = _make_opp(name='A', current_apy_pct=5.0, smart_contract_risk_score=0.0,
                       stablecoin_peg_score=100.0)
        result = self.opt.optimize([o1])
        r = result['opportunities'][0]
        expected = (r['optimal_allocation_pct'] / 100.0) * r['risk_adjusted_apy']
        self.assertAlmostEqual(result['total_yield_weighted_apy'], expected, places=5)


if __name__ == '__main__':
    unittest.main()
