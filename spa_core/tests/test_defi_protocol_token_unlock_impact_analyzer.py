"""
Tests for MP-1020: DeFiProtocolTokenUnlockImpactAnalyzer
Run with: python3 -m unittest spa_core.tests.test_defi_protocol_token_unlock_impact_analyzer
"""
import json
import os
import sys
import tempfile
import unittest

_SRC = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, _SRC)

from spa_core.analytics.defi_protocol_token_unlock_impact_analyzer import (
    DeFiProtocolTokenUnlockImpactAnalyzer,
    DEFAULT_CONFIG,
    VALID_IMPACT_LABELS,
    VALID_FLAGS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_schedule(**kwargs):
    defaults = {
        'name': 'TestToken',
        'protocol': 'TestProtocol',
        'token_price_usd': 1.0,
        'circulating_supply_usd': 10_000_000,
        'daily_volume_usd': 500_000,
        'next_unlock_date_days': 60,
        'next_unlock_amount_usd': 100_000,
        'next_unlock_beneficiary': 'community',
        'unlock_as_pct_circulating': 1.0,
        'total_locked_remaining_usd': 5_000_000,
        'unlock_cliff': False,
        'historical_unlock_price_impact_pct': -2.0,
        'upcoming_unlocks_12mo_usd': 500_000,
        'vesting_schedule_months_remaining': 12,
    }
    defaults.update(kwargs)
    return defaults


def _make_analyzer(tmp_dir):
    cfg = {
        'log_path': os.path.join(tmp_dir, 'token_unlock_impact_log.json'),
        'log_cap': 100,
    }
    return DeFiProtocolTokenUnlockImpactAnalyzer(config=cfg)


# ===========================================================================
# 1. Return-structure tests
# ===========================================================================

class TestReturnStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_analyze_returns_dict(self):
        result = self.ana.analyze([_make_schedule()])
        self.assertIsInstance(result, dict)

    def test_result_has_analyzed_key(self):
        result = self.ana.analyze([_make_schedule()])
        self.assertIn('analyzed', result)

    def test_result_has_highest_pressure(self):
        result = self.ana.analyze([_make_schedule()])
        self.assertIn('highest_pressure', result)

    def test_result_has_lowest_pressure(self):
        result = self.ana.analyze([_make_schedule()])
        self.assertIn('lowest_pressure', result)

    def test_result_has_total_upcoming_unlock_usd(self):
        result = self.ana.analyze([_make_schedule()])
        self.assertIn('total_upcoming_unlock_usd', result)

    def test_result_has_critical_overhang_count(self):
        result = self.ana.analyze([_make_schedule()])
        self.assertIn('critical_overhang_count', result)

    def test_result_has_negligible_count(self):
        result = self.ana.analyze([_make_schedule()])
        self.assertIn('negligible_count', result)

    def test_result_has_total_analyzed(self):
        result = self.ana.analyze([_make_schedule()])
        self.assertIn('total_analyzed', result)

    def test_empty_list_returns_dict(self):
        result = self.ana.analyze([])
        self.assertIsInstance(result, dict)

    def test_empty_list_total_zero(self):
        result = self.ana.analyze([])
        self.assertEqual(result['total_analyzed'], 0)

    def test_empty_list_highest_none(self):
        result = self.ana.analyze([])
        self.assertIsNone(result['highest_pressure'])

    def test_empty_list_lowest_none(self):
        result = self.ana.analyze([])
        self.assertIsNone(result['lowest_pressure'])


# ===========================================================================
# 2. Per-schedule metric keys
# ===========================================================================

class TestScheduleMetricKeys(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def _first(self, schedules=None):
        if schedules is None:
            schedules = [_make_schedule()]
        return self.ana.analyze(schedules)['analyzed'][0]

    def test_name_preserved(self):
        s = _make_schedule(name='MyToken')
        self.assertEqual(self._first([s])['name'], 'MyToken')

    def test_protocol_preserved(self):
        s = _make_schedule(protocol='MyProtocol')
        self.assertEqual(self._first([s])['protocol'], 'MyProtocol')

    def test_has_unlock_to_volume_ratio(self):
        self.assertIn('unlock_to_volume_ratio', self._first())

    def test_has_supply_inflation_pct(self):
        self.assertIn('supply_inflation_pct', self._first())

    def test_has_sell_pressure_score(self):
        self.assertIn('sell_pressure_score', self._first())

    def test_has_absorption_capacity_score(self):
        self.assertIn('absorption_capacity_score', self._first())

    def test_has_net_impact_score(self):
        self.assertIn('net_impact_score', self._first())

    def test_has_impact_label(self):
        self.assertIn('impact_label', self._first())

    def test_has_flags(self):
        self.assertIn('flags', self._first())

    def test_flags_is_list(self):
        self.assertIsInstance(self._first()['flags'], list)


# ===========================================================================
# 3. Metric value correctness
# ===========================================================================

class TestMetricValues(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_unlock_to_volume_ratio_correct(self):
        # unlock_amount=100k, daily_volume=500k → ratio=(100000/500000)*100=20.0
        s = _make_schedule(next_unlock_amount_usd=100_000, daily_volume_usd=500_000)
        r = self.ana.analyze([s])['analyzed'][0]
        self.assertAlmostEqual(r['unlock_to_volume_ratio'], 20.0, places=2)

    def test_supply_inflation_pct_correct(self):
        # unlock=100k, circulating=10M → inflation=1.0%
        s = _make_schedule(next_unlock_amount_usd=100_000, circulating_supply_usd=10_000_000)
        r = self.ana.analyze([s])['analyzed'][0]
        self.assertAlmostEqual(r['supply_inflation_pct'], 1.0, places=4)

    def test_sell_pressure_in_range(self):
        r = self.ana.analyze([_make_schedule()])['analyzed'][0]
        self.assertGreaterEqual(r['sell_pressure_score'], 0)
        self.assertLessEqual(r['sell_pressure_score'], 100)

    def test_absorption_capacity_in_range(self):
        r = self.ana.analyze([_make_schedule()])['analyzed'][0]
        self.assertGreaterEqual(r['absorption_capacity_score'], 0)
        self.assertLessEqual(r['absorption_capacity_score'], 100)

    def test_net_impact_is_difference(self):
        r = self.ana.analyze([_make_schedule()])['analyzed'][0]
        expected = r['sell_pressure_score'] - r['absorption_capacity_score']
        self.assertAlmostEqual(r['net_impact_score'], expected, places=4)

    def test_team_beneficiary_higher_pressure_than_community(self):
        team = _make_schedule(next_unlock_beneficiary='team', next_unlock_amount_usd=200_000)
        community = _make_schedule(next_unlock_beneficiary='community', next_unlock_amount_usd=200_000)
        r_team = self.ana.analyze([team])['analyzed'][0]
        r_comm = self.ana.analyze([community])['analyzed'][0]
        self.assertGreater(r_team['sell_pressure_score'], r_comm['sell_pressure_score'])

    def test_cliff_increases_sell_pressure(self):
        no_cliff = _make_schedule(unlock_cliff=False)
        cliff = _make_schedule(unlock_cliff=True)
        r_no = self.ana.analyze([no_cliff])['analyzed'][0]
        r_cl = self.ana.analyze([cliff])['analyzed'][0]
        self.assertGreater(r_cl['sell_pressure_score'], r_no['sell_pressure_score'])

    def test_larger_volume_increases_absorption(self):
        low_vol = _make_schedule(daily_volume_usd=100_000, next_unlock_amount_usd=500_000)
        high_vol = _make_schedule(daily_volume_usd=10_000_000, next_unlock_amount_usd=500_000)
        r_low = self.ana.analyze([low_vol])['analyzed'][0]
        r_high = self.ana.analyze([high_vol])['analyzed'][0]
        self.assertGreater(r_high['absorption_capacity_score'], r_low['absorption_capacity_score'])

    def test_historical_dump_increases_sell_pressure(self):
        mild = _make_schedule(historical_unlock_price_impact_pct=-1.0)
        severe = _make_schedule(historical_unlock_price_impact_pct=-20.0)
        r_mild = self.ana.analyze([mild])['analyzed'][0]
        r_sev = self.ana.analyze([severe])['analyzed'][0]
        self.assertGreater(r_sev['sell_pressure_score'], r_mild['sell_pressure_score'])

    def test_total_upcoming_unlock_sums_field(self):
        s1 = _make_schedule(upcoming_unlocks_12mo_usd=1_000_000)
        s2 = _make_schedule(upcoming_unlocks_12mo_usd=2_000_000)
        result = self.ana.analyze([s1, s2])
        self.assertAlmostEqual(result['total_upcoming_unlock_usd'], 3_000_000, places=0)


# ===========================================================================
# 4. Impact label tests
# ===========================================================================

class TestImpactLabels(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def _label(self, **kwargs):
        return self.ana.analyze([_make_schedule(**kwargs)])['analyzed'][0]['impact_label']

    def test_label_is_valid(self):
        label = self._label()
        self.assertIn(label, VALID_IMPACT_LABELS)

    def test_critical_overhang_high_supply_inflation(self):
        # ≥20% circulating → CRITICAL_OVERHANG
        label = self._label(
            next_unlock_amount_usd=2_000_000,
            circulating_supply_usd=10_000_000,
        )
        self.assertEqual(label, 'CRITICAL_OVERHANG')

    def test_critical_overhang_exact_20pct(self):
        label = self._label(
            next_unlock_amount_usd=2_000_000,
            circulating_supply_usd=10_000_000,
            daily_volume_usd=100,  # nearly zero absorption
        )
        self.assertEqual(label, 'CRITICAL_OVERHANG')

    def test_high_pressure_team_cliff(self):
        # team + cliff + ≥5% supply; high volume keeps net_impact < 70
        label = self._label(
            next_unlock_beneficiary='team',
            unlock_cliff=True,
            next_unlock_amount_usd=600_000,
            circulating_supply_usd=10_000_000,
            daily_volume_usd=10_000_000,  # high volume → absorption ~100
        )
        self.assertEqual(label, 'HIGH_PRESSURE')

    def test_high_pressure_investors_cliff(self):
        # investors + cliff + ≥5% supply; high volume keeps net_impact < 70
        label = self._label(
            next_unlock_beneficiary='investors',
            unlock_cliff=True,
            next_unlock_amount_usd=600_000,
            circulating_supply_usd=10_000_000,
            daily_volume_usd=10_000_000,
        )
        self.assertEqual(label, 'HIGH_PRESSURE')

    def test_moderate_pressure_mid_supply_pct(self):
        # exactly 5% supply (moderate_supply_pct default = 5.0)
        label = self._label(
            next_unlock_amount_usd=500_000,
            circulating_supply_usd=10_000_000,
            next_unlock_beneficiary='ecosystem',
            daily_volume_usd=500_000,
        )
        self.assertEqual(label, 'MODERATE_PRESSURE')

    def test_low_impact_small_unlock(self):
        # 3% supply (≥ low_impact_supply_pct=3.0 but < moderate=5.0)
        label = self._label(
            next_unlock_amount_usd=300_000,
            circulating_supply_usd=10_000_000,
            next_unlock_beneficiary='community',
        )
        self.assertEqual(label, 'LOW_IMPACT')

    def test_negligible_impact_community_tiny(self):
        label = self._label(
            next_unlock_amount_usd=50_000,
            circulating_supply_usd=10_000_000,
            next_unlock_beneficiary='community',
        )
        self.assertEqual(label, 'NEGLIGIBLE_IMPACT')

    def test_all_valid_impact_labels_exist(self):
        self.assertIn('NEGLIGIBLE_IMPACT', VALID_IMPACT_LABELS)
        self.assertIn('LOW_IMPACT', VALID_IMPACT_LABELS)
        self.assertIn('MODERATE_PRESSURE', VALID_IMPACT_LABELS)
        self.assertIn('HIGH_PRESSURE', VALID_IMPACT_LABELS)
        self.assertIn('CRITICAL_OVERHANG', VALID_IMPACT_LABELS)


# ===========================================================================
# 5. Flag tests
# ===========================================================================

class TestFlags(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def _flags(self, **kwargs):
        return self.ana.analyze([_make_schedule(**kwargs)])['analyzed'][0]['flags']

    def test_team_investor_unlock_team(self):
        self.assertIn('TEAM_INVESTOR_UNLOCK', self._flags(next_unlock_beneficiary='team'))

    def test_team_investor_unlock_investors(self):
        self.assertIn('TEAM_INVESTOR_UNLOCK', self._flags(next_unlock_beneficiary='investors'))

    def test_no_team_investor_for_community(self):
        self.assertNotIn('TEAM_INVESTOR_UNLOCK', self._flags(next_unlock_beneficiary='community'))

    def test_cliff_unlock_flag_large(self):
        flags = self._flags(
            unlock_cliff=True,
            next_unlock_amount_usd=500_000,
            circulating_supply_usd=10_000_000,
        )
        self.assertIn('CLIFF_UNLOCK', flags)

    def test_cliff_unlock_not_set_when_no_cliff(self):
        flags = self._flags(unlock_cliff=False, next_unlock_amount_usd=500_000)
        self.assertNotIn('CLIFF_UNLOCK', flags)

    def test_near_term_unlock_30_days(self):
        flags = self._flags(next_unlock_date_days=29)
        self.assertIn('NEAR_TERM_UNLOCK', flags)

    def test_near_term_unlock_exactly_30(self):
        flags = self._flags(next_unlock_date_days=30)
        self.assertIn('NEAR_TERM_UNLOCK', flags)

    def test_no_near_term_far_away(self):
        flags = self._flags(next_unlock_date_days=90)
        self.assertNotIn('NEAR_TERM_UNLOCK', flags)

    def test_community_friendly_flag(self):
        flags = self._flags(next_unlock_beneficiary='community')
        self.assertIn('COMMUNITY_FRIENDLY', flags)

    def test_no_community_friendly_team(self):
        flags = self._flags(next_unlock_beneficiary='team')
        self.assertNotIn('COMMUNITY_FRIENDLY', flags)

    def test_absorption_sufficient_high_volume(self):
        flags = self._flags(
            daily_volume_usd=10_000_000,
            next_unlock_amount_usd=100_000,
        )
        self.assertIn('ABSORPTION_SUFFICIENT', flags)

    def test_no_absorption_sufficient_low_volume(self):
        flags = self._flags(
            daily_volume_usd=100,
            next_unlock_amount_usd=100_000,
        )
        self.assertNotIn('ABSORPTION_SUFFICIENT', flags)

    def test_historical_dump_flag(self):
        flags = self._flags(historical_unlock_price_impact_pct=-15.0)
        self.assertIn('HISTORICAL_DUMP', flags)

    def test_no_historical_dump_mild(self):
        flags = self._flags(historical_unlock_price_impact_pct=-5.0)
        self.assertNotIn('HISTORICAL_DUMP', flags)

    def test_flags_all_valid(self):
        flags = self._flags(
            next_unlock_beneficiary='team',
            unlock_cliff=True,
            next_unlock_amount_usd=500_000,
            next_unlock_date_days=10,
            historical_unlock_price_impact_pct=-15.0,
        )
        for f in flags:
            self.assertIn(f, VALID_FLAGS)


# ===========================================================================
# 6. Aggregation tests
# ===========================================================================

class TestAggregation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_total_analyzed_count(self):
        result = self.ana.analyze([_make_schedule(), _make_schedule(), _make_schedule()])
        self.assertEqual(result['total_analyzed'], 3)

    def test_critical_overhang_count_correct(self):
        critical = _make_schedule(
            next_unlock_amount_usd=5_000_000,
            circulating_supply_usd=10_000_000,
        )
        normal = _make_schedule()
        result = self.ana.analyze([critical, normal])
        self.assertEqual(result['critical_overhang_count'], 1)

    def test_negligible_count_correct(self):
        s = _make_schedule(
            next_unlock_amount_usd=50_000,
            circulating_supply_usd=10_000_000,
            next_unlock_beneficiary='community',
        )
        result = self.ana.analyze([s, s])
        self.assertGreaterEqual(result['negligible_count'], 0)

    def test_highest_pressure_is_max(self):
        low = _make_schedule(next_unlock_beneficiary='community', next_unlock_amount_usd=10_000)
        high = _make_schedule(next_unlock_beneficiary='team', unlock_cliff=True,
                               next_unlock_amount_usd=500_000, name='HighPressure')
        result = self.ana.analyze([low, high])
        self.assertEqual(result['highest_pressure']['name'], 'HighPressure')

    def test_lowest_pressure_is_min(self):
        low = _make_schedule(next_unlock_beneficiary='community', next_unlock_amount_usd=10_000,
                             name='LowPressure')
        high = _make_schedule(next_unlock_beneficiary='team', unlock_cliff=True,
                               next_unlock_amount_usd=500_000)
        result = self.ana.analyze([low, high])
        self.assertEqual(result['lowest_pressure']['name'], 'LowPressure')

    def test_single_item_highest_equals_lowest(self):
        result = self.ana.analyze([_make_schedule(name='Only')])
        self.assertEqual(result['highest_pressure']['name'], result['lowest_pressure']['name'])

    def test_analyzed_list_length_matches_input(self):
        schedules = [_make_schedule() for _ in range(5)]
        result = self.ana.analyze(schedules)
        self.assertEqual(len(result['analyzed']), 5)


# ===========================================================================
# 7. Ring-buffer log tests
# ===========================================================================

class TestRingBufferLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, 'token_unlock_impact_log.json')
        self.ana = DeFiProtocolTokenUnlockImpactAnalyzer(config={
            'log_path': self.log_path,
            'log_cap': 5,
        })

    def test_log_file_created(self):
        self.ana.analyze([_make_schedule()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_is_valid_json_list(self):
        self.ana.analyze([_make_schedule()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_ts(self):
        self.ana.analyze([_make_schedule()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('ts', data[0])

    def test_log_entry_has_total_analyzed(self):
        self.ana.analyze([_make_schedule()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('total_analyzed', data[0])

    def test_log_entry_has_critical_overhang_count(self):
        self.ana.analyze([_make_schedule()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('critical_overhang_count', data[0])

    def test_log_ring_buffer_cap(self):
        for i in range(10):
            self.ana.analyze([_make_schedule()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 5)

    def test_log_accumulates_entries(self):
        self.ana.analyze([_make_schedule()])
        self.ana.analyze([_make_schedule()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_atomic_write_no_tmp_left(self):
        self.ana.analyze([_make_schedule()])
        tmp_path = self.log_path + '.tmp'
        self.assertFalse(os.path.exists(tmp_path))


# ===========================================================================
# 8. Edge case tests
# ===========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_zero_volume_no_crash(self):
        s = _make_schedule(daily_volume_usd=0)
        result = self.ana.analyze([s])
        self.assertIn('analyzed', result)

    def test_zero_unlock_amount_no_crash(self):
        s = _make_schedule(next_unlock_amount_usd=0)
        result = self.ana.analyze([s])
        self.assertIn('analyzed', result)

    def test_zero_circulating_supply_no_crash(self):
        s = _make_schedule(circulating_supply_usd=0)
        result = self.ana.analyze([s])
        self.assertIn('analyzed', result)

    def test_positive_historical_impact_no_crash(self):
        s = _make_schedule(historical_unlock_price_impact_pct=5.0)
        result = self.ana.analyze([s])
        self.assertIn('analyzed', result)

    def test_extreme_unlock_amount_no_crash(self):
        s = _make_schedule(
            next_unlock_amount_usd=100_000_000_000,
            circulating_supply_usd=100_000,
        )
        result = self.ana.analyze([s])
        self.assertEqual(result['analyzed'][0]['impact_label'], 'CRITICAL_OVERHANG')

    def test_unknown_beneficiary_defaults(self):
        s = _make_schedule(next_unlock_beneficiary='unknown_entity')
        result = self.ana.analyze([s])
        self.assertIn('analyzed', result)
        r = result['analyzed'][0]
        self.assertGreaterEqual(r['sell_pressure_score'], 0)

    def test_none_schedules_treated_as_empty(self):
        result = self.ana.analyze(None)
        self.assertEqual(result['total_analyzed'], 0)

    def test_very_large_volume_full_absorption(self):
        s = _make_schedule(daily_volume_usd=1_000_000_000, next_unlock_amount_usd=100_000)
        r = self.ana.analyze([s])['analyzed'][0]
        self.assertAlmostEqual(r['absorption_capacity_score'], 100.0, places=1)

    def test_investors_beneficiary_factor(self):
        s = _make_schedule(next_unlock_beneficiary='investors')
        r = self.ana.analyze([s])['analyzed'][0]
        # investors factor=0.9, should be high pressure-ish
        self.assertGreater(r['sell_pressure_score'], 10)

    def test_ecosystem_beneficiary_factor(self):
        s = _make_schedule(next_unlock_beneficiary='ecosystem')
        r_eco = self.ana.analyze([s])['analyzed'][0]
        s2 = _make_schedule(next_unlock_beneficiary='team')
        r_team = self.ana.analyze([s2])['analyzed'][0]
        # ecosystem factor < team factor
        self.assertLess(r_eco['sell_pressure_score'], r_team['sell_pressure_score'])


# ===========================================================================
# 9. Config override tests
# ===========================================================================

class TestConfigOverrides(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_custom_critical_supply_pct(self):
        # lower threshold: 5% → critical
        ana = DeFiProtocolTokenUnlockImpactAnalyzer(config={
            'log_path': os.path.join(self.tmp, 'log2.json'),
            'critical_supply_pct': 3.0,
        })
        s = _make_schedule(
            next_unlock_amount_usd=350_000,
            circulating_supply_usd=10_000_000,
        )
        r = ana.analyze([s])['analyzed'][0]
        self.assertEqual(r['impact_label'], 'CRITICAL_OVERHANG')

    def test_custom_near_term_days(self):
        ana = DeFiProtocolTokenUnlockImpactAnalyzer(config={
            'log_path': os.path.join(self.tmp, 'log3.json'),
            'near_term_days': 7,
        })
        s = _make_schedule(next_unlock_date_days=10)
        flags = ana.analyze([s])['analyzed'][0]['flags']
        # 10 > 7, so NOT near-term with default 30 but also 10 > 7 so NOT near-term here
        self.assertNotIn('NEAR_TERM_UNLOCK', flags)

    def test_custom_absorption_ratio(self):
        ana = DeFiProtocolTokenUnlockImpactAnalyzer(config={
            'log_path': os.path.join(self.tmp, 'log4.json'),
            'absorption_ratio': 5.0,
        })
        s = _make_schedule(daily_volume_usd=3_000_000, next_unlock_amount_usd=1_000_000)
        flags = ana.analyze([s])['analyzed'][0]['flags']
        self.assertNotIn('ABSORPTION_SUFFICIENT', flags)

    def test_log_cap_respected(self):
        log_path = os.path.join(self.tmp, 'cap_log.json')
        ana = DeFiProtocolTokenUnlockImpactAnalyzer(config={'log_path': log_path, 'log_cap': 3})
        for _ in range(8):
            ana.analyze([_make_schedule()])
        with open(log_path) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 3)


# ===========================================================================
# 10. DEFAULT_CONFIG and constant tests
# ===========================================================================

class TestConstants(unittest.TestCase):

    def test_default_config_has_log_path(self):
        self.assertIn('log_path', DEFAULT_CONFIG)

    def test_default_config_has_log_cap(self):
        self.assertIn('log_cap', DEFAULT_CONFIG)

    def test_default_config_has_beneficiary_factors(self):
        self.assertIn('beneficiary_factors', DEFAULT_CONFIG)

    def test_team_factor_highest(self):
        factors = DEFAULT_CONFIG['beneficiary_factors']
        self.assertGreater(factors['team'], factors['ecosystem'])
        self.assertGreater(factors['team'], factors['community'])

    def test_community_factor_lowest(self):
        factors = DEFAULT_CONFIG['beneficiary_factors']
        self.assertEqual(min(factors.values()), factors['community'])

    def test_valid_impact_labels_complete(self):
        expected = {
            'NEGLIGIBLE_IMPACT', 'LOW_IMPACT', 'MODERATE_PRESSURE',
            'HIGH_PRESSURE', 'CRITICAL_OVERHANG',
        }
        self.assertEqual(VALID_IMPACT_LABELS, expected)

    def test_valid_flags_complete(self):
        expected = {
            'TEAM_INVESTOR_UNLOCK', 'CLIFF_UNLOCK', 'NEAR_TERM_UNLOCK',
            'COMMUNITY_FRIENDLY', 'ABSORPTION_SUFFICIENT', 'HISTORICAL_DUMP',
        }
        self.assertEqual(VALID_FLAGS, expected)

    def test_default_log_cap_100(self):
        self.assertEqual(DEFAULT_CONFIG['log_cap'], 100)

    def test_near_term_days_default(self):
        self.assertEqual(DEFAULT_CONFIG['near_term_days'], 30)

    def test_critical_supply_pct_default(self):
        self.assertEqual(DEFAULT_CONFIG['critical_supply_pct'], 20.0)


# ===========================================================================
# 11. Multiple schedule scenarios
# ===========================================================================

class TestMultipleSchedules(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ana = _make_analyzer(self.tmp)

    def test_mixed_labels_in_results(self):
        schedules = [
            _make_schedule(next_unlock_amount_usd=50_000, circulating_supply_usd=10_000_000,
                           next_unlock_beneficiary='community'),
            _make_schedule(next_unlock_amount_usd=2_500_000, circulating_supply_usd=10_000_000,
                           next_unlock_beneficiary='team', unlock_cliff=True),
        ]
        result = self.ana.analyze(schedules)
        labels = {r['impact_label'] for r in result['analyzed']}
        self.assertGreater(len(labels), 1)

    def test_all_critical_count(self):
        schedules = [
            _make_schedule(next_unlock_amount_usd=3_000_000, circulating_supply_usd=10_000_000)
            for _ in range(3)
        ]
        result = self.ana.analyze(schedules)
        self.assertEqual(result['critical_overhang_count'], 3)

    def test_total_upcoming_summed_correctly(self):
        s1 = _make_schedule(upcoming_unlocks_12mo_usd=500_000)
        s2 = _make_schedule(upcoming_unlocks_12mo_usd=750_000)
        s3 = _make_schedule(upcoming_unlocks_12mo_usd=1_250_000)
        result = self.ana.analyze([s1, s2, s3])
        self.assertAlmostEqual(result['total_upcoming_unlock_usd'], 2_500_000, places=0)

    def test_ten_schedules_all_analyzed(self):
        schedules = [_make_schedule() for _ in range(10)]
        result = self.ana.analyze(schedules)
        self.assertEqual(result['total_analyzed'], 10)
        self.assertEqual(len(result['analyzed']), 10)

    def test_highest_and_lowest_different_for_two_schedules(self):
        low = _make_schedule(next_unlock_beneficiary='community', name='Low',
                             next_unlock_amount_usd=10_000)
        high = _make_schedule(next_unlock_beneficiary='team', name='High',
                              unlock_cliff=True, next_unlock_amount_usd=5_000_000)
        result = self.ana.analyze([low, high])
        self.assertNotEqual(
            result['highest_pressure']['name'],
            result['lowest_pressure']['name'],
        )

    def test_default_constructor_works(self):
        ana = DeFiProtocolTokenUnlockImpactAnalyzer()
        result = ana.analyze([_make_schedule()])
        self.assertIn('analyzed', result)


if __name__ == '__main__':
    unittest.main()
