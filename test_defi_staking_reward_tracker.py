"""Tests for defi_staking_reward_tracker.py — MP-895. ≥65 tests, stdlib unittest."""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from spa_core.analytics.defi_staking_reward_tracker import analyze, run


def _make_pos(**kwargs):
    """Build a minimal valid position dict with sensible defaults."""
    base = {
        'protocol': 'TestProto',
        'staked_asset': 'ETH',
        'gross_apy_pct': 8.0,
        'lockup_days': 0,
        'slashing_risk_pct': 2.0,
        'slashing_penalty_pct': 5.0,
        'exit_cost_pct': 0.0,
        'reward_compounding': 'DAILY',
        'validator_count': 5,
        'capital_usd': 10000.0,
    }
    base.update(kwargs)
    return base


# ── Empty input ──────────────────────────────────────────────────────────────

class TestEmptyPositions(unittest.TestCase):
    def test_empty_positions_list(self):
        result = analyze([])
        self.assertEqual(result['positions'], [])

    def test_empty_best_is_none(self):
        self.assertIsNone(analyze([])['best_staking_opportunity'])

    def test_empty_average_zero(self):
        self.assertEqual(analyze([])['average_effective_apy_pct'], 0.0)

    def test_empty_total_capital_zero(self):
        self.assertEqual(analyze([])['total_capital_usd'], 0.0)

    def test_empty_has_timestamp(self):
        t0 = time.time()
        self.assertGreaterEqual(analyze([])['timestamp'], t0)

    def test_empty_config_none(self):
        result = analyze([], config=None)
        self.assertEqual(result['positions'], [])


# ── Slashing drag ────────────────────────────────────────────────────────────

class TestSlashingDrag(unittest.TestCase):
    def test_basic_drag(self):
        pos = _make_pos(slashing_risk_pct=10.0, slashing_penalty_pct=10.0,
                        exit_cost_pct=0.0, lockup_days=0, gross_apy_pct=10.0)
        r = analyze([pos])['positions'][0]
        self.assertAlmostEqual(r['slashing_drag_pct'], 1.0, places=5)

    def test_zero_risk_zero_drag(self):
        r = analyze([_make_pos(slashing_risk_pct=0.0, slashing_penalty_pct=50.0)])
        self.assertEqual(r['positions'][0]['slashing_drag_pct'], 0.0)

    def test_zero_penalty_zero_drag(self):
        r = analyze([_make_pos(slashing_risk_pct=5.0, slashing_penalty_pct=0.0)])
        self.assertEqual(r['positions'][0]['slashing_drag_pct'], 0.0)

    def test_both_zero_drag(self):
        r = analyze([_make_pos(slashing_risk_pct=0.0, slashing_penalty_pct=0.0)])
        self.assertEqual(r['positions'][0]['slashing_drag_pct'], 0.0)

    def test_formula_correctness(self):
        pos = _make_pos(slashing_risk_pct=3.5, slashing_penalty_pct=8.0,
                        exit_cost_pct=0.0, lockup_days=0, gross_apy_pct=10.0)
        r = analyze([pos])['positions'][0]
        self.assertAlmostEqual(r['slashing_drag_pct'], (3.5 / 100.0) * 8.0, places=5)

    def test_100_pct_risk_full_penalty(self):
        pos = _make_pos(slashing_risk_pct=100.0, slashing_penalty_pct=50.0,
                        exit_cost_pct=0.0, lockup_days=0)
        r = analyze([pos])['positions'][0]
        self.assertAlmostEqual(r['slashing_drag_pct'], 50.0, places=5)


# ── Exit drag ────────────────────────────────────────────────────────────────

class TestExitDrag(unittest.TestCase):
    def test_liquid_no_exit_drag(self):
        r = analyze([_make_pos(lockup_days=0, exit_cost_pct=2.0)])
        self.assertEqual(r['positions'][0]['exit_drag_annualized_pct'], 0.0)

    def test_lockup_30_days(self):
        pos = _make_pos(lockup_days=30, exit_cost_pct=1.0,
                        slashing_risk_pct=0.0, slashing_penalty_pct=0.0)
        r = analyze([pos])['positions'][0]
        self.assertAlmostEqual(r['exit_drag_annualized_pct'], 1.0 / 30 * 365, places=4)

    def test_lockup_365_days(self):
        pos = _make_pos(lockup_days=365, exit_cost_pct=3.65,
                        slashing_risk_pct=0.0, slashing_penalty_pct=0.0)
        r = analyze([pos])['positions'][0]
        self.assertAlmostEqual(r['exit_drag_annualized_pct'], 3.65, places=4)

    def test_zero_exit_cost_lockup(self):
        r = analyze([_make_pos(lockup_days=60, exit_cost_pct=0.0)])
        self.assertEqual(r['positions'][0]['exit_drag_annualized_pct'], 0.0)

    def test_exit_drag_reduces_effective_apy(self):
        pos = _make_pos(gross_apy_pct=10.0, lockup_days=365, exit_cost_pct=1.0,
                        slashing_risk_pct=0.0, slashing_penalty_pct=0.0,
                        reward_compounding='MANUAL')
        r = analyze([pos])['positions'][0]
        # effective = 10.0 - 0.0 - 1.0 = 9.0
        self.assertAlmostEqual(r['effective_apy_pct'], 9.0, places=4)


# ── Effective APY ────────────────────────────────────────────────────────────

class TestEffectiveAPY(unittest.TestCase):
    def test_no_drag(self):
        pos = _make_pos(gross_apy_pct=10.0, slashing_risk_pct=0.0,
                        slashing_penalty_pct=0.0, exit_cost_pct=0.0, lockup_days=0)
        r = analyze([pos])['positions'][0]
        self.assertAlmostEqual(r['effective_apy_pct'], 10.0, places=5)

    def test_slashing_reduces_effective(self):
        pos = _make_pos(gross_apy_pct=10.0, slashing_risk_pct=10.0,
                        slashing_penalty_pct=10.0, exit_cost_pct=0.0, lockup_days=0)
        r = analyze([pos])['positions'][0]
        self.assertAlmostEqual(r['effective_apy_pct'], 9.0, places=5)

    def test_can_be_negative(self):
        pos = _make_pos(gross_apy_pct=1.0, slashing_risk_pct=50.0,
                        slashing_penalty_pct=10.0, exit_cost_pct=0.0, lockup_days=0)
        r = analyze([pos])['positions'][0]
        self.assertAlmostEqual(r['effective_apy_pct'], -4.0, places=5)

    def test_combined_drags(self):
        pos = _make_pos(gross_apy_pct=12.0, slashing_risk_pct=20.0,
                        slashing_penalty_pct=5.0, exit_cost_pct=0.365,
                        lockup_days=365, reward_compounding='MANUAL')
        r = analyze([pos])['positions'][0]
        slashing_drag = (20.0 / 100) * 5.0  # 1.0
        exit_drag = 0.365 / 365 * 365       # 0.365
        expected = 12.0 - slashing_drag - exit_drag
        self.assertAlmostEqual(r['effective_apy_pct'], expected, places=4)


# ── Lockup label ─────────────────────────────────────────────────────────────

class TestLockupLabel(unittest.TestCase):
    def test_liquid_0(self):
        self.assertEqual(analyze([_make_pos(lockup_days=0)])['positions'][0]['lockup_label'], 'LIQUID')

    def test_short_1(self):
        self.assertEqual(analyze([_make_pos(lockup_days=1)])['positions'][0]['lockup_label'], 'SHORT')

    def test_short_30(self):
        self.assertEqual(analyze([_make_pos(lockup_days=30)])['positions'][0]['lockup_label'], 'SHORT')

    def test_medium_31(self):
        self.assertEqual(analyze([_make_pos(lockup_days=31)])['positions'][0]['lockup_label'], 'MEDIUM')

    def test_medium_90(self):
        self.assertEqual(analyze([_make_pos(lockup_days=90)])['positions'][0]['lockup_label'], 'MEDIUM')

    def test_long_91(self):
        self.assertEqual(analyze([_make_pos(lockup_days=91)])['positions'][0]['lockup_label'], 'LONG')

    def test_long_365(self):
        self.assertEqual(analyze([_make_pos(lockup_days=365)])['positions'][0]['lockup_label'], 'LONG')

    def test_very_long_366(self):
        self.assertEqual(analyze([_make_pos(lockup_days=366)])['positions'][0]['lockup_label'], 'VERY_LONG')

    def test_very_long_1000(self):
        self.assertEqual(analyze([_make_pos(lockup_days=1000)])['positions'][0]['lockup_label'], 'VERY_LONG')


# ── Compounding bonus ─────────────────────────────────────────────────────────

class TestCompoundingBonus(unittest.TestCase):
    def test_daily_30bps(self):
        r = analyze([_make_pos(reward_compounding='DAILY')])
        self.assertEqual(r['positions'][0]['compounding_bonus_bps'], 30)

    def test_weekly_15bps(self):
        r = analyze([_make_pos(reward_compounding='WEEKLY')])
        self.assertEqual(r['positions'][0]['compounding_bonus_bps'], 15)

    def test_monthly_5bps(self):
        r = analyze([_make_pos(reward_compounding='MONTHLY')])
        self.assertEqual(r['positions'][0]['compounding_bonus_bps'], 5)

    def test_manual_0bps(self):
        r = analyze([_make_pos(reward_compounding='MANUAL')])
        self.assertEqual(r['positions'][0]['compounding_bonus_bps'], 0)

    def test_lowercase_daily(self):
        r = analyze([_make_pos(reward_compounding='daily')])
        self.assertEqual(r['positions'][0]['compounding_bonus_bps'], 30)

    def test_adjusted_apy_daily(self):
        pos = _make_pos(gross_apy_pct=10.0, slashing_risk_pct=0.0,
                        slashing_penalty_pct=0.0, exit_cost_pct=0.0,
                        lockup_days=0, reward_compounding='DAILY')
        r = analyze([pos])['positions'][0]
        self.assertAlmostEqual(r['adjusted_apy_pct'], 10.30, places=5)

    def test_adjusted_apy_manual(self):
        pos = _make_pos(gross_apy_pct=10.0, slashing_risk_pct=0.0,
                        slashing_penalty_pct=0.0, exit_cost_pct=0.0,
                        lockup_days=0, reward_compounding='MANUAL')
        r = analyze([pos])['positions'][0]
        self.assertAlmostEqual(r['adjusted_apy_pct'], 10.0, places=5)


# ── Staking grade ─────────────────────────────────────────────────────────────

class TestStakingGrade(unittest.TestCase):
    def _clean_pos(self, gross_apy, compounding='MANUAL'):
        return _make_pos(gross_apy_pct=gross_apy, slashing_risk_pct=0.0,
                         slashing_penalty_pct=0.0, exit_cost_pct=0.0,
                         lockup_days=0, reward_compounding=compounding)

    def test_a_plus_20(self):
        self.assertEqual(analyze([self._clean_pos(20.0)])['positions'][0]['staking_grade'], 'A+')

    def test_a_plus_boundary_15(self):
        self.assertEqual(analyze([self._clean_pos(15.0)])['positions'][0]['staking_grade'], 'A+')

    def test_a_grade_12(self):
        self.assertEqual(analyze([self._clean_pos(12.0)])['positions'][0]['staking_grade'], 'A')

    def test_a_boundary_10(self):
        self.assertEqual(analyze([self._clean_pos(10.0)])['positions'][0]['staking_grade'], 'A')

    def test_b_grade_8(self):
        self.assertEqual(analyze([self._clean_pos(8.0)])['positions'][0]['staking_grade'], 'B')

    def test_b_boundary_7(self):
        self.assertEqual(analyze([self._clean_pos(7.0)])['positions'][0]['staking_grade'], 'B')

    def test_c_grade_5(self):
        self.assertEqual(analyze([self._clean_pos(5.0)])['positions'][0]['staking_grade'], 'C')

    def test_c_boundary_4(self):
        self.assertEqual(analyze([self._clean_pos(4.0)])['positions'][0]['staking_grade'], 'C')

    def test_d_grade_2(self):
        self.assertEqual(analyze([self._clean_pos(2.0)])['positions'][0]['staking_grade'], 'D')

    def test_d_boundary_1(self):
        self.assertEqual(analyze([self._clean_pos(1.0)])['positions'][0]['staking_grade'], 'D')

    def test_f_grade_zero(self):
        self.assertEqual(analyze([self._clean_pos(0.0)])['positions'][0]['staking_grade'], 'F')

    def test_f_grade_negative(self):
        self.assertEqual(analyze([self._clean_pos(-5.0)])['positions'][0]['staking_grade'], 'F')


# ── Flags ─────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def test_negative_premium(self):
        pos = _make_pos(gross_apy_pct=2.0, slashing_risk_pct=0.0,
                        slashing_penalty_pct=0.0, exit_cost_pct=0.0,
                        lockup_days=0, reward_compounding='MANUAL')
        flags = analyze([pos], config={'opportunity_cost_apy_pct': 5.0})['positions'][0]['flags']
        self.assertIn('NEGATIVE_PREMIUM', flags)

    def test_no_negative_premium(self):
        pos = _make_pos(gross_apy_pct=10.0, slashing_risk_pct=0.0,
                        slashing_penalty_pct=0.0, exit_cost_pct=0.0,
                        lockup_days=0, reward_compounding='MANUAL')
        flags = analyze([pos], config={'opportunity_cost_apy_pct': 5.0})['positions'][0]['flags']
        self.assertNotIn('NEGATIVE_PREMIUM', flags)

    def test_high_slashing_risk_6pct(self):
        flags = analyze([_make_pos(slashing_risk_pct=6.0)])['positions'][0]['flags']
        self.assertIn('HIGH_SLASHING_RISK', flags)

    def test_not_high_slashing_at_5pct(self):
        flags = analyze([_make_pos(slashing_risk_pct=5.0)])['positions'][0]['flags']
        self.assertNotIn('HIGH_SLASHING_RISK', flags)

    def test_long_lockup_91_days(self):
        flags = analyze([_make_pos(lockup_days=91)])['positions'][0]['flags']
        self.assertIn('LONG_LOCKUP', flags)

    def test_no_long_lockup_at_90_days(self):
        flags = analyze([_make_pos(lockup_days=90)])['positions'][0]['flags']
        self.assertNotIn('LONG_LOCKUP', flags)

    def test_manual_compounding_flag(self):
        flags = analyze([_make_pos(reward_compounding='MANUAL')])['positions'][0]['flags']
        self.assertIn('MANUAL_COMPOUNDING', flags)

    def test_no_manual_flag_for_daily(self):
        flags = analyze([_make_pos(reward_compounding='DAILY')])['positions'][0]['flags']
        self.assertNotIn('MANUAL_COMPOUNDING', flags)

    def test_all_four_flags_together(self):
        pos = _make_pos(gross_apy_pct=1.0, slashing_risk_pct=10.0,
                        slashing_penalty_pct=0.0, exit_cost_pct=0.0,
                        lockup_days=100, reward_compounding='MANUAL')
        flags = analyze([pos], config={'opportunity_cost_apy_pct': 5.0})['positions'][0]['flags']
        self.assertIn('NEGATIVE_PREMIUM', flags)
        self.assertIn('HIGH_SLASHING_RISK', flags)
        self.assertIn('LONG_LOCKUP', flags)
        self.assertIn('MANUAL_COMPOUNDING', flags)

    def test_flags_is_list(self):
        r = analyze([_make_pos()])
        self.assertIsInstance(r['positions'][0]['flags'], list)

    def test_clean_position_no_flags(self):
        pos = _make_pos(gross_apy_pct=10.0, slashing_risk_pct=0.0,
                        slashing_penalty_pct=0.0, exit_cost_pct=0.0,
                        lockup_days=0, reward_compounding='DAILY')
        flags = analyze([pos], config={'opportunity_cost_apy_pct': 5.0})['positions'][0]['flags']
        self.assertEqual(flags, [])


# ── Net premium ───────────────────────────────────────────────────────────────

class TestNetPremium(unittest.TestCase):
    def test_default_opp_cost_5pct(self):
        pos = _make_pos(gross_apy_pct=8.0, slashing_risk_pct=0.0,
                        slashing_penalty_pct=0.0, exit_cost_pct=0.0,
                        lockup_days=0, reward_compounding='MANUAL')
        r = analyze([pos])['positions'][0]
        self.assertAlmostEqual(r['net_premium_pct'], 3.0, places=5)

    def test_custom_opp_cost(self):
        pos = _make_pos(gross_apy_pct=8.0, slashing_risk_pct=0.0,
                        slashing_penalty_pct=0.0, exit_cost_pct=0.0,
                        lockup_days=0, reward_compounding='MANUAL')
        r = analyze([pos], config={'opportunity_cost_apy_pct': 3.0})['positions'][0]
        self.assertAlmostEqual(r['net_premium_pct'], 5.0, places=5)

    def test_opp_cost_in_output(self):
        r = analyze([_make_pos()], config={'opportunity_cost_apy_pct': 4.5})
        self.assertEqual(r['positions'][0]['opportunity_cost_pct'], 4.5)


# ── Best opportunity ──────────────────────────────────────────────────────────

class TestBestOpportunity(unittest.TestCase):
    def test_single(self):
        pos = _make_pos(protocol='Lido', staked_asset='ETH')
        r = analyze([pos])
        self.assertEqual(r['best_staking_opportunity'], 'Lido:ETH')

    def test_highest_adjusted_apy_wins(self):
        p1 = _make_pos(protocol='A', staked_asset='ETH', gross_apy_pct=5.0,
                       slashing_risk_pct=0.0, slashing_penalty_pct=0.0,
                       exit_cost_pct=0.0, lockup_days=0, reward_compounding='MANUAL')
        p2 = _make_pos(protocol='B', staked_asset='SOL', gross_apy_pct=15.0,
                       slashing_risk_pct=0.0, slashing_penalty_pct=0.0,
                       exit_cost_pct=0.0, lockup_days=0, reward_compounding='MANUAL')
        r = analyze([p1, p2])
        self.assertEqual(r['best_staking_opportunity'], 'B:SOL')

    def test_empty_none(self):
        self.assertIsNone(analyze([])['best_staking_opportunity'])

    def test_format_colon_separated(self):
        pos = _make_pos(protocol='Proto', staked_asset='ASSET')
        result = analyze([pos])['best_staking_opportunity']
        self.assertIn(':', result)


# ── Average effective APY ─────────────────────────────────────────────────────

class TestAverageEffective(unittest.TestCase):
    def test_single(self):
        pos = _make_pos(gross_apy_pct=10.0, slashing_risk_pct=0.0,
                        slashing_penalty_pct=0.0, exit_cost_pct=0.0, lockup_days=0)
        self.assertAlmostEqual(analyze([pos])['average_effective_apy_pct'], 10.0, places=5)

    def test_two_positions_mean(self):
        p1 = _make_pos(gross_apy_pct=10.0, slashing_risk_pct=0.0,
                       slashing_penalty_pct=0.0, exit_cost_pct=0.0, lockup_days=0)
        p2 = _make_pos(gross_apy_pct=6.0, slashing_risk_pct=0.0,
                       slashing_penalty_pct=0.0, exit_cost_pct=0.0, lockup_days=0)
        self.assertAlmostEqual(analyze([p1, p2])['average_effective_apy_pct'], 8.0, places=5)

    def test_empty_zero(self):
        self.assertEqual(analyze([])['average_effective_apy_pct'], 0.0)


# ── Total capital ─────────────────────────────────────────────────────────────

class TestTotalCapital(unittest.TestCase):
    def test_sum_two(self):
        r = analyze([_make_pos(capital_usd=10000), _make_pos(capital_usd=20000)])
        self.assertAlmostEqual(r['total_capital_usd'], 30000.0, places=2)

    def test_empty_zero(self):
        self.assertEqual(analyze([])['total_capital_usd'], 0.0)


# ── Recommendation text ───────────────────────────────────────────────────────

class TestRecommendation(unittest.TestCase):
    def _simple(self, gross_apy, compounding='MANUAL'):
        return _make_pos(gross_apy_pct=gross_apy, slashing_risk_pct=0.0,
                         slashing_penalty_pct=0.0, exit_cost_pct=0.0,
                         lockup_days=0, reward_compounding=compounding)

    def test_a_plus_says_excellent(self):
        rec = analyze([self._simple(20.0)])['positions'][0]['recommendation']
        self.assertIn('Excellent', rec)

    def test_a_says_excellent(self):
        rec = analyze([self._simple(12.0)])['positions'][0]['recommendation']
        self.assertIn('Excellent', rec)

    def test_b_says_good_yield(self):
        rec = analyze([self._simple(8.0)])['positions'][0]['recommendation']
        self.assertIn('Good yield', rec)

    def test_c_says_marginal(self):
        rec = analyze([self._simple(4.5)])['positions'][0]['recommendation']
        self.assertIn('Marginal', rec)

    def test_d_says_poor(self):
        rec = analyze([self._simple(1.5)])['positions'][0]['recommendation']
        self.assertIn('Poor risk-return', rec)

    def test_f_says_poor(self):
        rec = analyze([self._simple(0.0)])['positions'][0]['recommendation']
        self.assertIn('Poor risk-return', rec)

    def test_recommendation_is_string(self):
        rec = analyze([_make_pos()])['positions'][0]['recommendation']
        self.assertIsInstance(rec, str)
        self.assertGreater(len(rec), 0)


# ── run() / persistence ───────────────────────────────────────────────────────

class TestRunPersistence(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_run_creates_log(self):
        run([_make_pos()], data_dir=self.tmpdir)
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, 'staking_reward_log.json')))

    def test_run_log_is_list(self):
        run([_make_pos()], data_dir=self.tmpdir)
        with open(os.path.join(self.tmpdir, 'staking_reward_log.json')) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_run_accumulates(self):
        run([_make_pos()], data_dir=self.tmpdir)
        run([_make_pos()], data_dir=self.tmpdir)
        with open(os.path.join(self.tmpdir, 'staking_reward_log.json')) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        for _ in range(105):
            run([_make_pos()], data_dir=self.tmpdir)
        with open(os.path.join(self.tmpdir, 'staking_reward_log.json')) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_run_returns_result(self):
        result = run([_make_pos()], data_dir=self.tmpdir)
        self.assertIn('positions', result)
        self.assertIn('best_staking_opportunity', result)

    def test_atomic_write_no_tmp_left(self):
        run([_make_pos()], data_dir=self.tmpdir)
        tmp = os.path.join(self.tmpdir, 'staking_reward_log.json.tmp')
        self.assertFalse(os.path.exists(tmp))


# ── Output fields ─────────────────────────────────────────────────────────────

class TestOutputFields(unittest.TestCase):
    def test_top_level_keys(self):
        r = analyze([_make_pos()])
        for k in ('positions', 'best_staking_opportunity', 'average_effective_apy_pct',
                  'total_capital_usd', 'timestamp'):
            self.assertIn(k, r)

    def test_position_keys(self):
        r = analyze([_make_pos()])
        p = r['positions'][0]
        for k in ('protocol', 'staked_asset', 'gross_apy_pct', 'slashing_drag_pct',
                  'exit_drag_annualized_pct', 'effective_apy_pct', 'opportunity_cost_pct',
                  'net_premium_pct', 'lockup_label', 'compounding_bonus_bps',
                  'adjusted_apy_pct', 'staking_grade', 'flags', 'recommendation'):
            self.assertIn(k, p)

    def test_protocol_preserved(self):
        pos = _make_pos(protocol='Cosmos', staked_asset='ATOM')
        r = analyze([pos])['positions'][0]
        self.assertEqual(r['protocol'], 'Cosmos')
        self.assertEqual(r['staked_asset'], 'ATOM')


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    def test_five_positions(self):
        positions = [_make_pos(protocol=f'P{i}', gross_apy_pct=5.0 + i) for i in range(5)]
        r = analyze(positions)
        self.assertEqual(len(r['positions']), 5)

    def test_empty_config_dict_uses_default(self):
        r = analyze([_make_pos()], config={})
        self.assertEqual(r['positions'][0]['opportunity_cost_pct'], 5.0)

    def test_zero_gross_apy(self):
        pos = _make_pos(gross_apy_pct=0.0, slashing_risk_pct=0.0,
                        slashing_penalty_pct=0.0, exit_cost_pct=0.0, lockup_days=0)
        r = analyze([pos])['positions'][0]
        self.assertAlmostEqual(r['effective_apy_pct'], 0.0, places=5)

    def test_very_long_lockup_exit_drag(self):
        pos = _make_pos(lockup_days=500, gross_apy_pct=20.0, slashing_risk_pct=0.0,
                        slashing_penalty_pct=0.0, exit_cost_pct=0.0,
                        reward_compounding='MANUAL')
        r = analyze([pos])['positions'][0]
        self.assertEqual(r['lockup_label'], 'VERY_LONG')
        self.assertAlmostEqual(r['exit_drag_annualized_pct'], 0.0, places=5)

    def test_high_slashing_flag_boundary(self):
        # exactly 5.0 → NOT flagged; 5.01 → flagged
        pos_5 = _make_pos(slashing_risk_pct=5.0)
        pos_6 = _make_pos(slashing_risk_pct=5.01)
        self.assertNotIn('HIGH_SLASHING_RISK', analyze([pos_5])['positions'][0]['flags'])
        self.assertIn('HIGH_SLASHING_RISK', analyze([pos_6])['positions'][0]['flags'])


if __name__ == '__main__':
    unittest.main()
