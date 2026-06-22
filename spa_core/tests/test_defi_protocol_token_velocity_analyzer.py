"""
Tests for MP-958: DeFiProtocolTokenVelocityAnalyzer
Run with: python3 -m unittest spa_core.tests.test_defi_protocol_token_velocity_analyzer
"""
import json
import os
import sys
import tempfile
import unittest

# Ensure project root is importable
_SRC = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, _SRC)

from spa_core.analytics.defi_protocol_token_velocity_analyzer import (
    DeFiProtocolTokenVelocityAnalyzer,
    VALID_VELOCITY_LABELS,
    VALID_FLAGS,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_token(**kwargs):
    """Build a minimal valid token dict."""
    defaults = {
        'name': 'TestToken',
        'protocol': 'TestProtocol',
        'circulating_supply': 1_000_000,
        'trading_volume_30d_usd': 500_000,
        'market_cap_usd': 10_000_000,
        'unique_wallets_30d': 5_000,
        'on_chain_tx_count_30d': 100_000,
        'staked_pct': 0.0,
        'vesting_locked_pct': 0.0,
        'avg_hold_duration_days': 30,
        'utility_uses': ['governance'],
    }
    defaults.update(kwargs)
    return defaults


def _make_analyzer(tmp_dir):
    cfg = {'log_path': os.path.join(tmp_dir, 'token_velocity_log.json'), 'log_cap': 100}
    return DeFiProtocolTokenVelocityAnalyzer(config=cfg)


# ---------------------------------------------------------------------------
# 1. Basic functionality
# ---------------------------------------------------------------------------

class TestAnalyzeBasic(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_analyze_returns_dict(self):
        result = self.ana.analyze([_make_token()])
        self.assertIsInstance(result, dict)

    def test_analyze_empty_tokens_returns_dict(self):
        result = self.ana.analyze([])
        self.assertIsInstance(result, dict)

    def test_analyze_empty_tokens_zero_total(self):
        result = self.ana.analyze([])
        self.assertEqual(result['aggregates']['total_tokens'], 0)

    def test_analyze_single_token_total_one(self):
        result = self.ana.analyze([_make_token()])
        self.assertEqual(result['aggregates']['total_tokens'], 1)

    def test_analyze_multiple_tokens_correct_count(self):
        tokens = [_make_token(name=f'T{i}') for i in range(5)]
        result = self.ana.analyze(tokens)
        self.assertEqual(result['aggregates']['total_tokens'], 5)

    def test_analyze_config_override(self):
        result = self.ana.analyze([_make_token()], config={'log_cap': 50})
        self.assertEqual(self.ana.config['log_cap'], 50)

    def test_analyze_tokens_list_length(self):
        tokens = [_make_token(name=f'T{i}') for i in range(3)]
        result = self.ana.analyze(tokens)
        self.assertEqual(len(result['tokens']), 3)

    def test_init_default_config(self):
        ana = DeFiProtocolTokenVelocityAnalyzer()
        self.assertEqual(ana.config['log_cap'], 100)

    def test_init_custom_config(self):
        ana = DeFiProtocolTokenVelocityAnalyzer(config={'log_cap': 50})
        self.assertEqual(ana.config['log_cap'], 50)


# ---------------------------------------------------------------------------
# 2. Velocity ratio calculations
# ---------------------------------------------------------------------------

class TestVelocityCalculations(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_velocity_ratio_basic(self):
        token = _make_token(trading_volume_30d_usd=1_000_000, market_cap_usd=10_000_000)
        result = self.ana.analyze([token])
        t = result['tokens'][0]
        self.assertAlmostEqual(t['velocity_ratio'], 0.1, places=5)

    def test_velocity_ratio_zero_market_cap(self):
        token = _make_token(market_cap_usd=0)
        result = self.ana.analyze([token])
        t = result['tokens'][0]
        self.assertEqual(t['velocity_ratio'], 0.0)

    def test_velocity_ratio_in_result(self):
        result = self.ana.analyze([_make_token()])
        self.assertIn('velocity_ratio', result['tokens'][0])

    def test_annualized_velocity_in_result(self):
        result = self.ana.analyze([_make_token()])
        self.assertIn('annualized_velocity', result['tokens'][0])

    def test_annualized_velocity_multiplied_by_factor(self):
        # factor = 365/30 ≈ 12.1667
        token = _make_token(trading_volume_30d_usd=1_000_000, market_cap_usd=10_000_000)
        result = self.ana.analyze([token])
        t = result['tokens'][0]
        expected = (1_000_000 / 10_000_000) * (365 / 30)
        self.assertAlmostEqual(t['annualized_velocity'], expected, places=4)

    def test_annualized_velocity_zero_volume(self):
        token = _make_token(trading_volume_30d_usd=0)
        result = self.ana.analyze([token])
        self.assertEqual(result['tokens'][0]['annualized_velocity'], 0.0)

    def test_annualized_velocity_positive_for_nonzero(self):
        token = _make_token(trading_volume_30d_usd=100_000, market_cap_usd=1_000_000)
        result = self.ana.analyze([token])
        self.assertGreater(result['tokens'][0]['annualized_velocity'], 0)

    def test_velocity_ratio_proportional_to_volume(self):
        t1 = _make_token(name='T1', trading_volume_30d_usd=100_000, market_cap_usd=1_000_000)
        t2 = _make_token(name='T2', trading_volume_30d_usd=200_000, market_cap_usd=1_000_000)
        r1 = self.ana.analyze([t1])['tokens'][0]
        self.ana2 = _make_analyzer(tempfile.mkdtemp())
        r2 = self.ana2.analyze([t2])['tokens'][0]
        self.assertAlmostEqual(r2['velocity_ratio'], 2 * r1['velocity_ratio'], places=5)

    def test_annualized_velocity_store_of_value_range(self):
        # very low volume relative to market cap → STORE_OF_VALUE
        token = _make_token(trading_volume_30d_usd=1_000, market_cap_usd=10_000_000)
        result = self.ana.analyze([token])
        t = result['tokens'][0]
        # annualized ~ 0.1/30 * 365 ≈ 0.00122 < 0.5
        self.assertLess(t['annualized_velocity'], 0.5)

    def test_annualized_velocity_hyperactive_range(self):
        token = _make_token(trading_volume_30d_usd=60_000_000, market_cap_usd=1_000_000)
        result = self.ana.analyze([token])
        t = result['tokens'][0]
        self.assertGreater(t['annualized_velocity'], 50)


# ---------------------------------------------------------------------------
# 3. Effective circulating supply & market cap
# ---------------------------------------------------------------------------

class TestEffectiveCirculating(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_effective_circulating_no_lock(self):
        token = _make_token(circulating_supply=1_000_000, staked_pct=0, vesting_locked_pct=0)
        result = self.ana.analyze([token])
        self.assertAlmostEqual(result['tokens'][0]['effective_circulating'], 1_000_000, places=0)

    def test_effective_circulating_staked(self):
        token = _make_token(circulating_supply=1_000_000, staked_pct=50, vesting_locked_pct=0)
        result = self.ana.analyze([token])
        self.assertAlmostEqual(result['tokens'][0]['effective_circulating'], 500_000, places=0)

    def test_effective_circulating_vesting(self):
        token = _make_token(circulating_supply=1_000_000, staked_pct=0, vesting_locked_pct=30)
        result = self.ana.analyze([token])
        self.assertAlmostEqual(result['tokens'][0]['effective_circulating'], 700_000, places=0)

    def test_effective_circulating_both(self):
        token = _make_token(circulating_supply=1_000_000, staked_pct=30, vesting_locked_pct=20)
        result = self.ana.analyze([token])
        self.assertAlmostEqual(result['tokens'][0]['effective_circulating'], 500_000, places=0)

    def test_effective_circulating_capped_not_negative(self):
        token = _make_token(circulating_supply=1_000_000, staked_pct=70, vesting_locked_pct=70)
        result = self.ana.analyze([token])
        self.assertGreaterEqual(result['tokens'][0]['effective_circulating'], 0)

    def test_effective_circulating_in_result(self):
        result = self.ana.analyze([_make_token()])
        self.assertIn('effective_circulating', result['tokens'][0])

    def test_effective_market_cap_in_result(self):
        result = self.ana.analyze([_make_token()])
        self.assertIn('effective_market_cap', result['tokens'][0])

    def test_effective_market_cap_reduced_by_staking(self):
        token = _make_token(market_cap_usd=10_000_000, staked_pct=50, vesting_locked_pct=0)
        result = self.ana.analyze([token])
        self.assertAlmostEqual(result['tokens'][0]['effective_market_cap'], 5_000_000, places=0)


# ---------------------------------------------------------------------------
# 4. Adjusted velocity
# ---------------------------------------------------------------------------

class TestAdjustedVelocity(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_adjusted_velocity_in_result(self):
        result = self.ana.analyze([_make_token()])
        self.assertIn('adjusted_velocity', result['tokens'][0])

    def test_adjusted_velocity_higher_when_staked(self):
        # Same volume but half effective market cap → double adjusted velocity
        t_no_stake = _make_token(name='A', staked_pct=0)
        t_staked = _make_token(name='B', staked_pct=50)
        ana2 = _make_analyzer(tempfile.mkdtemp())
        av_no = self.ana.analyze([t_no_stake])['tokens'][0]['adjusted_velocity']
        av_st = ana2.analyze([t_staked])['tokens'][0]['adjusted_velocity']
        self.assertGreater(av_st, av_no)

    def test_adjusted_velocity_same_when_no_lock(self):
        # When staked_pct=0 and vesting=0, adjusted should equal annualized
        token = _make_token(staked_pct=0, vesting_locked_pct=0)
        result = self.ana.analyze([token])
        t = result['tokens'][0]
        self.assertAlmostEqual(t['adjusted_velocity'], t['annualized_velocity'], places=4)

    def test_adjusted_velocity_non_negative(self):
        result = self.ana.analyze([_make_token()])
        self.assertGreaterEqual(result['tokens'][0]['adjusted_velocity'], 0)

    def test_adjusted_velocity_fallback_zero_effective_cap(self):
        # If effective_market_cap == 0 → fallback to annualized_velocity
        token = _make_token(market_cap_usd=0)
        result = self.ana.analyze([token])
        t = result['tokens'][0]
        self.assertEqual(t['adjusted_velocity'], t['annualized_velocity'])


# ---------------------------------------------------------------------------
# 5. Utility score
# ---------------------------------------------------------------------------

class TestUtilityScore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def _score(self, utility_uses):
        result = self.ana.analyze([_make_token(utility_uses=utility_uses)])
        return result['tokens'][0]['utility_score']

    def test_utility_score_empty(self):
        self.assertEqual(self._score([]), 0)

    def test_utility_score_one_use(self):
        self.assertEqual(self._score(['governance']), 20)

    def test_utility_score_two_uses(self):
        self.assertEqual(self._score(['governance', 'fee_payment']), 40)

    def test_utility_score_three_uses(self):
        self.assertEqual(self._score(['governance', 'fee_payment', 'collateral']), 60)

    def test_utility_score_four_uses(self):
        self.assertEqual(self._score(['governance', 'fee_payment', 'collateral', 'staking']), 80)

    def test_utility_score_five_uses(self):
        self.assertEqual(self._score(['governance', 'fee_payment', 'collateral', 'staking', 'gas']), 100)

    def test_utility_score_capped_at_100(self):
        # 6 uses would be 120 → capped at 100
        uses = ['governance', 'fee_payment', 'collateral', 'staking', 'gas', 'extra']
        self.assertEqual(self._score(uses), 100)

    def test_utility_score_in_result(self):
        result = self.ana.analyze([_make_token()])
        self.assertIn('utility_score', result['tokens'][0])

    def test_utility_score_is_integer_type(self):
        result = self.ana.analyze([_make_token(utility_uses=['governance'])])
        self.assertIsInstance(result['tokens'][0]['utility_score'], int)


# ---------------------------------------------------------------------------
# 6. Speculation index
# ---------------------------------------------------------------------------

class TestSpeculationIndex(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_speculation_index_in_result(self):
        result = self.ana.analyze([_make_token()])
        self.assertIn('speculation_index', result['tokens'][0])

    def test_speculation_index_range(self):
        result = self.ana.analyze([_make_token()])
        si = result['tokens'][0]['speculation_index']
        self.assertGreaterEqual(si, 0.0)
        self.assertLessEqual(si, 100.0)

    def test_speculation_index_high_for_high_velocity_low_utility(self):
        token = _make_token(
            trading_volume_30d_usd=100_000_000,  # very high velocity
            market_cap_usd=1_000_000,
            utility_uses=[],  # zero utility
        )
        result = self.ana.analyze([token])
        self.assertGreater(result['tokens'][0]['speculation_index'], 60)

    def test_speculation_index_lower_for_high_utility(self):
        token_low = _make_token(utility_uses=[])
        token_high = _make_token(
            name='HighUtil',
            utility_uses=['governance', 'fee_payment', 'collateral', 'staking', 'gas'],
            trading_volume_30d_usd=100_000,  # low velocity
            market_cap_usd=10_000_000,
        )
        r_low = self.ana.analyze([token_low])['tokens'][0]['speculation_index']
        ana2 = _make_analyzer(tempfile.mkdtemp())
        r_high = ana2.analyze([token_high])['tokens'][0]['speculation_index']
        self.assertGreater(r_low, r_high)

    def test_speculation_index_is_float(self):
        result = self.ana.analyze([_make_token()])
        self.assertIsInstance(result['tokens'][0]['speculation_index'], float)


# ---------------------------------------------------------------------------
# 7. Velocity labels
# ---------------------------------------------------------------------------

class TestVelocityLabels(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def _label_for_ratio(self, vol, mcap):
        token = _make_token(trading_volume_30d_usd=vol, market_cap_usd=mcap)
        result = self.ana.analyze([token])
        return result['tokens'][0]['velocity_label']

    def test_label_store_of_value(self):
        # annualized < 0.5: vol/mcap * 12.16 < 0.5 → vol/mcap < ~0.041
        label = self._label_for_ratio(1_000, 10_000_000)
        self.assertEqual(label, 'STORE_OF_VALUE')

    def test_label_low_velocity(self):
        # 0.5 <= annualized < 2.0
        # annualized = (vol/mcap) × (365/30); target annualized = 1.0
        # vol/mcap = 1.0 × 30/365 ≈ 0.08219 → vol = 821_900 for mcap=10M
        label = self._label_for_ratio(821_900, 10_000_000)
        self.assertEqual(label, 'LOW_VELOCITY')

    def test_label_moderate(self):
        # 2.0 <= annualized < 10.0 → vol/mcap = 5/12.16 ≈ 0.411
        label = self._label_for_ratio(4_110_000, 10_000_000)
        self.assertEqual(label, 'MODERATE')

    def test_label_high_velocity(self):
        # 10 <= annualized < 50 → vol/mcap = 20/12.16 ≈ 1.644
        label = self._label_for_ratio(16_440_000, 10_000_000)
        self.assertEqual(label, 'HIGH_VELOCITY')

    def test_label_hyperactive(self):
        # annualized >= 50 → vol/mcap = 60/12.16 ≈ 4.934
        label = self._label_for_ratio(49_340_000, 10_000_000)
        self.assertEqual(label, 'HYPERACTIVE')

    def test_label_in_valid_set(self):
        result = self.ana.analyze([_make_token()])
        label = result['tokens'][0]['velocity_label']
        self.assertIn(label, VALID_VELOCITY_LABELS)

    def test_label_in_result(self):
        result = self.ana.analyze([_make_token()])
        self.assertIn('velocity_label', result['tokens'][0])


# ---------------------------------------------------------------------------
# 8. Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def _flags(self, **kwargs):
        result = self.ana.analyze([_make_token(**kwargs)])
        return result['tokens'][0]['flags']

    def test_flag_pure_speculation_triggered(self):
        # velocity > 10 (annualized) AND utility_score < 40
        flags = self._flags(
            trading_volume_30d_usd=10_000_000,  # velocity >> 10
            market_cap_usd=100_000,
            utility_uses=[],
        )
        self.assertIn('PURE_SPECULATION', flags)

    def test_flag_pure_speculation_not_triggered_low_velocity(self):
        flags = self._flags(
            trading_volume_30d_usd=100,
            market_cap_usd=10_000_000,
            utility_uses=[],
        )
        self.assertNotIn('PURE_SPECULATION', flags)

    def test_flag_pure_speculation_not_triggered_high_utility(self):
        flags = self._flags(
            trading_volume_30d_usd=10_000_000,
            market_cap_usd=100_000,
            utility_uses=['governance', 'fee_payment', 'collateral'],
        )
        self.assertNotIn('PURE_SPECULATION', flags)

    def test_flag_utility_driven_triggered(self):
        # utility_score > 60 AND annualized < 5
        flags = self._flags(
            trading_volume_30d_usd=10_000,
            market_cap_usd=10_000_000,
            utility_uses=['governance', 'fee_payment', 'collateral', 'staking'],
        )
        self.assertIn('UTILITY_DRIVEN', flags)

    def test_flag_utility_driven_not_triggered_high_velocity(self):
        flags = self._flags(
            trading_volume_30d_usd=5_000_000,
            market_cap_usd=1_000_000,
            utility_uses=['governance', 'fee_payment', 'collateral', 'staking'],
        )
        self.assertNotIn('UTILITY_DRIVEN', flags)

    def test_flag_utility_driven_not_triggered_low_utility(self):
        flags = self._flags(
            trading_volume_30d_usd=10_000,
            market_cap_usd=10_000_000,
            utility_uses=['governance'],
        )
        self.assertNotIn('UTILITY_DRIVEN', flags)

    def test_flag_high_staking_lock_triggered(self):
        flags = self._flags(staked_pct=60)
        self.assertIn('HIGH_STAKING_LOCK', flags)

    def test_flag_high_staking_lock_not_triggered(self):
        flags = self._flags(staked_pct=40)
        self.assertNotIn('HIGH_STAKING_LOCK', flags)

    def test_flag_high_staking_lock_boundary(self):
        # exactly 50% → threshold is > 50, so 50% should NOT trigger
        flags = self._flags(staked_pct=50)
        self.assertNotIn('HIGH_STAKING_LOCK', flags)

    def test_flag_vesting_overhang_triggered(self):
        flags = self._flags(vesting_locked_pct=35)
        self.assertIn('VESTING_OVERHANG', flags)

    def test_flag_vesting_overhang_not_triggered(self):
        flags = self._flags(vesting_locked_pct=20)
        self.assertNotIn('VESTING_OVERHANG', flags)

    def test_flag_broad_adoption_triggered(self):
        flags = self._flags(unique_wallets_30d=15_000)
        self.assertIn('BROAD_ADOPTION', flags)

    def test_flag_broad_adoption_not_triggered(self):
        flags = self._flags(unique_wallets_30d=5_000)
        self.assertNotIn('BROAD_ADOPTION', flags)

    def test_flags_list_type(self):
        result = self.ana.analyze([_make_token()])
        self.assertIsInstance(result['tokens'][0]['flags'], list)

    def test_flags_subset_of_valid(self):
        result = self.ana.analyze([_make_token(staked_pct=60, unique_wallets_30d=20_000)])
        flags = result['tokens'][0]['flags']
        self.assertTrue(set(flags).issubset(VALID_FLAGS))

    def test_multiple_flags_possible(self):
        flags = self._flags(
            staked_pct=60,
            vesting_locked_pct=35,
            unique_wallets_30d=20_000,
        )
        # At least HIGH_STAKING_LOCK + VESTING_OVERHANG + BROAD_ADOPTION
        self.assertGreaterEqual(len(flags), 3)


# ---------------------------------------------------------------------------
# 9. Aggregates
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def _two_tokens(self):
        t1 = _make_token(name='SLOW', trading_volume_30d_usd=10_000, market_cap_usd=10_000_000)
        t2 = _make_token(name='FAST', trading_volume_30d_usd=9_000_000, market_cap_usd=1_000_000)
        return [t1, t2]

    def test_aggregate_highest_velocity(self):
        result = self.ana.analyze(self._two_tokens())
        self.assertEqual(result['aggregates']['highest_velocity'], 'FAST')

    def test_aggregate_lowest_velocity(self):
        result = self.ana.analyze(self._two_tokens())
        self.assertEqual(result['aggregates']['lowest_velocity'], 'SLOW')

    def test_aggregate_average_velocity(self):
        result = self.ana.analyze(self._two_tokens())
        tokens = result['tokens']
        expected = (tokens[0]['annualized_velocity'] + tokens[1]['annualized_velocity']) / 2
        self.assertAlmostEqual(result['aggregates']['average_velocity'], expected, places=4)

    def test_aggregate_speculation_count(self):
        tokens = [
            _make_token(name='S', trading_volume_30d_usd=10_000_000, market_cap_usd=100_000, utility_uses=[]),
            _make_token(name='N'),
        ]
        result = self.ana.analyze(tokens)
        self.assertGreaterEqual(result['aggregates']['speculation_count'], 1)

    def test_aggregate_total_tokens_matches(self):
        tokens = [_make_token(name=f'T{i}') for i in range(4)]
        result = self.ana.analyze(tokens)
        self.assertEqual(result['aggregates']['total_tokens'], 4)

    def test_aggregate_most_speculative_in_result(self):
        result = self.ana.analyze(self._two_tokens())
        self.assertIn('most_speculative', result['aggregates'])

    def test_aggregate_most_utility_driven_in_result(self):
        result = self.ana.analyze(self._two_tokens())
        self.assertIn('most_utility_driven', result['aggregates'])

    def test_aggregate_empty_nones(self):
        result = self.ana.analyze([])
        self.assertIsNone(result['aggregates']['highest_velocity'])
        self.assertIsNone(result['aggregates']['lowest_velocity'])


# ---------------------------------------------------------------------------
# 10. Result structure
# ---------------------------------------------------------------------------

class TestResultStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_result_has_tokens_key(self):
        result = self.ana.analyze([_make_token()])
        self.assertIn('tokens', result)

    def test_result_has_aggregates_key(self):
        result = self.ana.analyze([_make_token()])
        self.assertIn('aggregates', result)

    def test_result_has_timestamp(self):
        result = self.ana.analyze([_make_token()])
        self.assertIn('timestamp', result)
        self.assertIsInstance(result['timestamp'], str)

    def test_result_status_ok(self):
        result = self.ana.analyze([_make_token()])
        self.assertEqual(result['status'], 'ok')

    def test_token_result_has_velocity_ratio(self):
        t = self.ana.analyze([_make_token()])['tokens'][0]
        self.assertIn('velocity_ratio', t)

    def test_token_result_has_annualized_velocity(self):
        t = self.ana.analyze([_make_token()])['tokens'][0]
        self.assertIn('annualized_velocity', t)

    def test_token_result_has_effective_circulating(self):
        t = self.ana.analyze([_make_token()])['tokens'][0]
        self.assertIn('effective_circulating', t)

    def test_token_result_has_effective_market_cap(self):
        t = self.ana.analyze([_make_token()])['tokens'][0]
        self.assertIn('effective_market_cap', t)

    def test_token_result_has_adjusted_velocity(self):
        t = self.ana.analyze([_make_token()])['tokens'][0]
        self.assertIn('adjusted_velocity', t)

    def test_token_result_has_utility_score(self):
        t = self.ana.analyze([_make_token()])['tokens'][0]
        self.assertIn('utility_score', t)

    def test_token_result_has_speculation_index(self):
        t = self.ana.analyze([_make_token()])['tokens'][0]
        self.assertIn('speculation_index', t)

    def test_token_result_has_velocity_label(self):
        t = self.ana.analyze([_make_token()])['tokens'][0]
        self.assertIn('velocity_label', t)

    def test_token_result_has_flags(self):
        t = self.ana.analyze([_make_token()])['tokens'][0]
        self.assertIn('flags', t)


# ---------------------------------------------------------------------------
# 11. Log file (ring-buffer, atomic write)
# ---------------------------------------------------------------------------

class TestLogFile(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, 'tvlog.json')
        self.ana = DeFiProtocolTokenVelocityAnalyzer(config={
            'log_path': self.log_path,
            'log_cap': 100,
        })

    def test_log_file_created_after_analyze(self):
        self.ana.analyze([_make_token()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_file_is_valid_json(self):
        self.ana.analyze([_make_token()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_timestamp(self):
        self.ana.analyze([_make_token()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('timestamp', data[0])

    def test_log_entry_has_total_tokens(self):
        self.ana.analyze([_make_token()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('total_tokens', data[0])

    def test_log_entry_has_average_velocity(self):
        self.ana.analyze([_make_token()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('average_velocity', data[0])

    def test_log_entry_has_speculation_count(self):
        self.ana.analyze([_make_token()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('speculation_count', data[0])

    def test_log_multiple_runs_append(self):
        self.ana.analyze([_make_token()])
        self.ana.analyze([_make_token()])
        self.ana.analyze([_make_token()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_ring_buffer_cap(self):
        # Set cap=5, run 8 times → only 5 entries
        ana = DeFiProtocolTokenVelocityAnalyzer(config={
            'log_path': self.log_path,
            'log_cap': 5,
        })
        for _ in range(8):
            ana.analyze([_make_token()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 5)

    def test_log_no_tmp_file_remains(self):
        self.ana.analyze([_make_token()])
        self.assertFalse(os.path.exists(self.log_path + '.tmp'))

    def test_log_invalid_existing_json_reset(self):
        with open(self.log_path, 'w') as f:
            f.write('NOT_JSON!')
        self.ana.analyze([_make_token()])  # should not raise
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_subdirectory_created(self):
        nested = os.path.join(self.tmp, 'sub', 'dir', 'log.json')
        ana = DeFiProtocolTokenVelocityAnalyzer(config={'log_path': nested, 'log_cap': 10})
        ana.analyze([_make_token()])
        self.assertTrue(os.path.exists(nested))

    def test_log_empty_analyze_still_writes(self):
        self.ana.analyze([])
        self.assertTrue(os.path.exists(self.log_path))


# ---------------------------------------------------------------------------
# 12. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_zero_market_cap_no_error(self):
        result = self.ana.analyze([_make_token(market_cap_usd=0)])
        self.assertIsNotNone(result)

    def test_zero_supply_no_error(self):
        result = self.ana.analyze([_make_token(circulating_supply=0)])
        self.assertIsNotNone(result)

    def test_all_locked_supply_no_negative_effective(self):
        token = _make_token(staked_pct=60, vesting_locked_pct=60)
        result = self.ana.analyze([token])
        self.assertGreaterEqual(result['tokens'][0]['effective_circulating'], 0)

    def test_very_large_numbers_no_error(self):
        token = _make_token(
            circulating_supply=1e15,
            trading_volume_30d_usd=1e12,
            market_cap_usd=1e14,
        )
        result = self.ana.analyze([token])
        self.assertIsNotNone(result)

    def test_none_utility_uses_handled(self):
        token = _make_token(utility_uses=None)
        result = self.ana.analyze([token])
        self.assertEqual(result['tokens'][0]['utility_score'], 0)

    def test_missing_fields_handled(self):
        result = self.ana.analyze([{'name': 'Minimal'}])
        self.assertIn('annualized_velocity', result['tokens'][0])

    def test_name_preserved(self):
        result = self.ana.analyze([_make_token(name='MYTOKEN')])
        self.assertEqual(result['tokens'][0]['name'], 'MYTOKEN')

    def test_protocol_preserved(self):
        result = self.ana.analyze([_make_token(protocol='MYPROTOCOL')])
        self.assertEqual(result['tokens'][0]['protocol'], 'MYPROTOCOL')


if __name__ == '__main__':
    unittest.main()
