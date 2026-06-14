"""
Tests for MP-959: ProtocolSmartContractComplexityScorer
Run with: python3 -m unittest spa_core.tests.test_protocol_smart_contract_complexity_scorer
"""
import json
import os
import sys
import tempfile
import unittest

_SRC = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, _SRC)

from spa_core.analytics.protocol_smart_contract_complexity_scorer import (
    ProtocolSmartContractComplexityScorer,
    DEFAULT_CONFIG,
    VALID_RISK_LABELS,
    VALID_FLAGS,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_contract(**kwargs):
    """Build a minimal valid contract dict."""
    defaults = {
        'name': 'TestContract',
        'protocol': 'TestProtocol',
        'lines_of_code': 500,
        'function_count': 20,
        'external_call_count': 5,
        'inheritance_depth': 2,
        'proxy_pattern': 'none',
        'upgrade_mechanism': 'none',
        'oracle_dependencies': 1,
        'cross_contract_calls': 3,
        'assembly_blocks_count': 1,
        'audit_count': 2,
        'bug_bounty_usd': 50_000,
        'days_live': 400,
        'critical_bugs_found': 0,
    }
    defaults.update(kwargs)
    return defaults


def _make_scorer(tmp_dir):
    cfg = {
        'log_path': os.path.join(tmp_dir, 'contract_complexity_log.json'),
        'log_cap': 100,
    }
    return ProtocolSmartContractComplexityScorer(config=cfg)


# ---------------------------------------------------------------------------
# 1. Basic functionality
# ---------------------------------------------------------------------------

class TestScoreBasic(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _make_scorer(self.tmp)

    def test_score_returns_dict(self):
        result = self.scorer.score([_make_contract()])
        self.assertIsInstance(result, dict)

    def test_score_empty_contracts_returns_dict(self):
        result = self.scorer.score([])
        self.assertIsInstance(result, dict)

    def test_score_empty_contracts_zero_total(self):
        result = self.scorer.score([])
        self.assertEqual(result['aggregates']['total_contracts'], 0)

    def test_score_single_contract_total_one(self):
        result = self.scorer.score([_make_contract()])
        self.assertEqual(result['aggregates']['total_contracts'], 1)

    def test_score_multiple_contracts_correct_count(self):
        contracts = [_make_contract(name=f'C{i}') for i in range(5)]
        result = self.scorer.score(contracts)
        self.assertEqual(result['aggregates']['total_contracts'], 5)

    def test_score_config_override(self):
        self.scorer.score([_make_contract()], config={'log_cap': 50})
        self.assertEqual(self.scorer.config['log_cap'], 50)

    def test_score_contracts_list_length(self):
        contracts = [_make_contract(name=f'C{i}') for i in range(4)]
        result = self.scorer.score(contracts)
        self.assertEqual(len(result['contracts']), 4)

    def test_init_default_config(self):
        s = ProtocolSmartContractComplexityScorer()
        self.assertEqual(s.config['log_cap'], 100)

    def test_init_custom_config(self):
        s = ProtocolSmartContractComplexityScorer(config={'log_cap': 25})
        self.assertEqual(s.config['log_cap'], 25)


# ---------------------------------------------------------------------------
# 2. Complexity score
# ---------------------------------------------------------------------------

class TestComplexityScore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _make_scorer(self.tmp)

    def _complexity(self, **kwargs):
        result = self.scorer.score([_make_contract(**kwargs)])
        return result['contracts'][0]['complexity_score']

    def test_complexity_zero_all(self):
        score = self._complexity(
            lines_of_code=0, function_count=0, external_call_count=0,
            inheritance_depth=0, assembly_blocks_count=0,
        )
        self.assertEqual(score, 0.0)

    def test_complexity_max_loc_only(self):
        # loc=10000 contributes 0.20×100 = 20
        score = self._complexity(
            lines_of_code=10_000, function_count=0, external_call_count=0,
            inheritance_depth=0, assembly_blocks_count=0,
        )
        self.assertAlmostEqual(score, 20.0, places=2)

    def test_complexity_max_funcs_only(self):
        # func=200 contributes 0.30×100 = 30
        score = self._complexity(
            lines_of_code=0, function_count=200, external_call_count=0,
            inheritance_depth=0, assembly_blocks_count=0,
        )
        self.assertAlmostEqual(score, 30.0, places=2)

    def test_complexity_max_ext_calls_only(self):
        # ext_calls=50 contributes 0.20×100 = 20
        score = self._complexity(
            lines_of_code=0, function_count=0, external_call_count=50,
            inheritance_depth=0, assembly_blocks_count=0,
        )
        self.assertAlmostEqual(score, 20.0, places=2)

    def test_complexity_max_inheritance_only(self):
        # inherit=10 contributes 0.15×100 = 15
        score = self._complexity(
            lines_of_code=0, function_count=0, external_call_count=0,
            inheritance_depth=10, assembly_blocks_count=0,
        )
        self.assertAlmostEqual(score, 15.0, places=2)

    def test_complexity_max_assembly_only(self):
        # assembly=20 contributes 0.15×100 = 15
        score = self._complexity(
            lines_of_code=0, function_count=0, external_call_count=0,
            inheritance_depth=0, assembly_blocks_count=20,
        )
        self.assertAlmostEqual(score, 15.0, places=2)

    def test_complexity_all_max_is_100(self):
        score = self._complexity(
            lines_of_code=10_000, function_count=200, external_call_count=50,
            inheritance_depth=10, assembly_blocks_count=20,
        )
        self.assertAlmostEqual(score, 100.0, places=2)

    def test_complexity_score_range_0_100(self):
        score = self._complexity()
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_complexity_score_in_result(self):
        result = self.scorer.score([_make_contract()])
        self.assertIn('complexity_score', result['contracts'][0])

    def test_complexity_score_increases_with_loc(self):
        s1 = self._complexity(lines_of_code=1000)
        s2 = self._complexity(lines_of_code=5000)
        self.assertGreater(s2, s1)

    def test_complexity_score_exceeding_max_capped(self):
        score = self._complexity(
            lines_of_code=100_000,  # 10× max
            function_count=2000,
            external_call_count=500,
            inheritance_depth=100,
            assembly_blocks_count=200,
        )
        self.assertLessEqual(score, 100.0)

    def test_complexity_score_is_float(self):
        result = self.scorer.score([_make_contract()])
        self.assertIsInstance(result['contracts'][0]['complexity_score'], float)


# ---------------------------------------------------------------------------
# 3. Upgrade risk score
# ---------------------------------------------------------------------------

class TestUpgradeRiskScore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _make_scorer(self.tmp)

    def _upgrade_risk(self, **kwargs):
        result = self.scorer.score([_make_contract(**kwargs)])
        return result['contracts'][0]['upgrade_risk_score']

    def test_upgrade_risk_no_proxy(self):
        score = self._upgrade_risk(proxy_pattern='none', upgrade_mechanism='none')
        self.assertEqual(score, 0.0)

    def test_upgrade_risk_transparent_proxy_no_mechanism(self):
        # proxy=transparent(30)×0.60 + none(0)×0.40 = 18; +20 penalty = 38
        score = self._upgrade_risk(proxy_pattern='transparent', upgrade_mechanism='none')
        self.assertAlmostEqual(score, 38.0, places=2)

    def test_upgrade_risk_uups_no_mechanism(self):
        # uups(40)×0.60 + none(0)×0.40 = 24; +20 penalty = 44
        score = self._upgrade_risk(proxy_pattern='uups', upgrade_mechanism='none')
        self.assertAlmostEqual(score, 44.0, places=2)

    def test_upgrade_risk_beacon_no_mechanism(self):
        # beacon(50)×0.60 + none(0)×0.40 = 30; +20 = 50
        score = self._upgrade_risk(proxy_pattern='beacon', upgrade_mechanism='none')
        self.assertAlmostEqual(score, 50.0, places=2)

    def test_upgrade_risk_diamond_no_mechanism(self):
        # diamond(80)×0.60 + none(0)×0.40 = 48; +20 = 68
        score = self._upgrade_risk(proxy_pattern='diamond', upgrade_mechanism='none')
        self.assertAlmostEqual(score, 68.0, places=2)

    def test_upgrade_risk_with_timelock(self):
        # transparent(30)×0.60 + timelock(20)×0.40 = 18 + 8 = 26
        score = self._upgrade_risk(proxy_pattern='transparent', upgrade_mechanism='timelock')
        self.assertAlmostEqual(score, 26.0, places=2)

    def test_upgrade_risk_with_multisig(self):
        # transparent(30)×0.60 + multisig(40)×0.40 = 18 + 16 = 34
        score = self._upgrade_risk(proxy_pattern='transparent', upgrade_mechanism='multisig')
        self.assertAlmostEqual(score, 34.0, places=2)

    def test_upgrade_risk_score_range_0_100(self):
        score = self._upgrade_risk()
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_upgrade_risk_in_result(self):
        result = self.scorer.score([_make_contract()])
        self.assertIn('upgrade_risk_score', result['contracts'][0])

    def test_upgrade_risk_no_penalty_when_no_proxy(self):
        # penalty only applies when proxy_pattern != 'none'
        no_proxy = self._upgrade_risk(proxy_pattern='none', upgrade_mechanism='none')
        self.assertEqual(no_proxy, 0.0)

    def test_upgrade_risk_dao_mechanism(self):
        # transparent(30)×0.60 + dao(30)×0.40 = 18 + 12 = 30
        score = self._upgrade_risk(proxy_pattern='transparent', upgrade_mechanism='dao')
        self.assertAlmostEqual(score, 30.0, places=2)


# ---------------------------------------------------------------------------
# 4. Audit coverage score
# ---------------------------------------------------------------------------

class TestAuditCoverageScore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _make_scorer(self.tmp)

    def _audit_coverage(self, **kwargs):
        result = self.scorer.score([_make_contract(**kwargs)])
        return result['contracts'][0]['audit_coverage_score']

    def test_audit_coverage_zero_audits_no_bounty(self):
        score = self._audit_coverage(audit_count=0, bug_bounty_usd=0)
        self.assertEqual(score, 0.0)

    def test_audit_coverage_one_audit(self):
        score = self._audit_coverage(audit_count=1, bug_bounty_usd=0)
        self.assertAlmostEqual(score, 25.0, places=2)

    def test_audit_coverage_two_audits(self):
        score = self._audit_coverage(audit_count=2, bug_bounty_usd=0)
        self.assertAlmostEqual(score, 50.0, places=2)

    def test_audit_coverage_four_audits_capped(self):
        score = self._audit_coverage(audit_count=4, bug_bounty_usd=0)
        self.assertAlmostEqual(score, 100.0, places=2)

    def test_audit_coverage_many_audits_still_capped(self):
        score = self._audit_coverage(audit_count=10, bug_bounty_usd=0)
        self.assertLessEqual(score, 100.0)

    def test_audit_coverage_bug_bounty_bonus(self):
        # $100k → 10 points bonus
        score_no_bounty = self._audit_coverage(audit_count=0, bug_bounty_usd=0)
        score_bounty = self._audit_coverage(audit_count=0, bug_bounty_usd=100_000)
        self.assertGreater(score_bounty, score_no_bounty)

    def test_audit_coverage_range_0_100(self):
        score = self._audit_coverage()
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_audit_coverage_in_result(self):
        result = self.scorer.score([_make_contract()])
        self.assertIn('audit_coverage_score', result['contracts'][0])

    def test_audit_coverage_is_float(self):
        result = self.scorer.score([_make_contract()])
        self.assertIsInstance(result['contracts'][0]['audit_coverage_score'], float)


# ---------------------------------------------------------------------------
# 5. Net risk score
# ---------------------------------------------------------------------------

class TestNetRiskScore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _make_scorer(self.tmp)

    def _net_risk(self, **kwargs):
        result = self.scorer.score([_make_contract(**kwargs)])
        return result['contracts'][0]['net_risk_score']

    def test_net_risk_in_result(self):
        result = self.scorer.score([_make_contract()])
        self.assertIn('net_risk_score', result['contracts'][0])

    def test_net_risk_range_0_100(self):
        score = self._net_risk()
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_net_risk_minimum_zero(self):
        # High audits can reduce net risk to zero but not below
        score = self._net_risk(
            lines_of_code=0, function_count=0, external_call_count=0,
            inheritance_depth=0, assembly_blocks_count=0,
            proxy_pattern='none', upgrade_mechanism='none',
            audit_count=4, bug_bounty_usd=200_000,
        )
        self.assertGreaterEqual(score, 0.0)

    def test_net_risk_high_complexity_no_audits(self):
        score = self._net_risk(
            lines_of_code=10_000, function_count=200, external_call_count=50,
            inheritance_depth=10, assembly_blocks_count=20,
            audit_count=0, bug_bounty_usd=0,
        )
        self.assertGreater(score, 50.0)

    def test_net_risk_high_audits_reduce(self):
        low_audit = self._net_risk(audit_count=0, bug_bounty_usd=0)
        high_audit = self._net_risk(audit_count=4, bug_bounty_usd=200_000)
        self.assertGreater(low_audit, high_audit)

    def test_net_risk_formula_check(self):
        result = self.scorer.score([_make_contract()])
        c = result['contracts'][0]
        raw = c['complexity_score'] + c['upgrade_risk_score'] - c['audit_coverage_score']
        expected = round(min(100.0, max(0.0, raw)), 4)
        self.assertAlmostEqual(c['net_risk_score'], expected, places=2)

    def test_net_risk_is_float(self):
        result = self.scorer.score([_make_contract()])
        self.assertIsInstance(result['contracts'][0]['net_risk_score'], float)

    def test_net_risk_simple_contract(self):
        score = self._net_risk(
            lines_of_code=100, function_count=5, external_call_count=0,
            inheritance_depth=1, assembly_blocks_count=0,
            proxy_pattern='none', upgrade_mechanism='none',
            audit_count=3, bug_bounty_usd=100_000,
        )
        self.assertLess(score, 40.0)


# ---------------------------------------------------------------------------
# 6. Risk labels
# ---------------------------------------------------------------------------

class TestRiskLabels(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _make_scorer(self.tmp)

    def test_label_in_result(self):
        result = self.scorer.score([_make_contract()])
        self.assertIn('risk_label', result['contracts'][0])

    def test_label_in_valid_set(self):
        result = self.scorer.score([_make_contract()])
        self.assertIn(result['contracts'][0]['risk_label'], VALID_RISK_LABELS)

    def test_label_simple_low_risk(self):
        result = self.scorer.score([_make_contract(
            lines_of_code=50, function_count=5, external_call_count=0,
            inheritance_depth=0, assembly_blocks_count=0,
            proxy_pattern='none', upgrade_mechanism='none',
            audit_count=4, bug_bounty_usd=200_000,
        )])
        self.assertEqual(result['contracts'][0]['risk_label'], 'SIMPLE')

    def test_label_critical_complexity_high_all(self):
        result = self.scorer.score([_make_contract(
            lines_of_code=10_000, function_count=200, external_call_count=50,
            inheritance_depth=10, assembly_blocks_count=20,
            proxy_pattern='diamond', upgrade_mechanism='none',
            audit_count=0, bug_bounty_usd=0,
        )])
        self.assertEqual(result['contracts'][0]['risk_label'], 'CRITICAL_COMPLEXITY')

    def test_label_is_string(self):
        result = self.scorer.score([_make_contract()])
        self.assertIsInstance(result['contracts'][0]['risk_label'], str)


# ---------------------------------------------------------------------------
# 7. Flags
# ---------------------------------------------------------------------------

class TestFlags(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _make_scorer(self.tmp)

    def _flags(self, **kwargs):
        return self.scorer.score([_make_contract(**kwargs)])['contracts'][0]['flags']

    def test_flag_proxy_risk_transparent_no_timelock(self):
        flags = self._flags(proxy_pattern='transparent', upgrade_mechanism='none')
        self.assertIn('PROXY_RISK', flags)

    def test_flag_proxy_risk_uups_multisig(self):
        flags = self._flags(proxy_pattern='uups', upgrade_mechanism='multisig')
        self.assertIn('PROXY_RISK', flags)

    def test_flag_no_proxy_risk_no_proxy(self):
        flags = self._flags(proxy_pattern='none', upgrade_mechanism='none')
        self.assertNotIn('PROXY_RISK', flags)

    def test_flag_no_proxy_risk_with_timelock(self):
        flags = self._flags(proxy_pattern='transparent', upgrade_mechanism='timelock')
        self.assertNotIn('PROXY_RISK', flags)

    def test_flag_no_proxy_risk_with_dao(self):
        flags = self._flags(proxy_pattern='uups', upgrade_mechanism='dao')
        self.assertNotIn('PROXY_RISK', flags)

    def test_flag_assembly_heavy_triggered(self):
        flags = self._flags(assembly_blocks_count=15)
        self.assertIn('ASSEMBLY_HEAVY', flags)

    def test_flag_assembly_heavy_not_triggered(self):
        flags = self._flags(assembly_blocks_count=5)
        self.assertNotIn('ASSEMBLY_HEAVY', flags)

    def test_flag_assembly_heavy_boundary(self):
        # threshold is > 10; exactly 10 should NOT trigger
        flags = self._flags(assembly_blocks_count=10)
        self.assertNotIn('ASSEMBLY_HEAVY', flags)

    def test_flag_oracle_dependent_triggered(self):
        flags = self._flags(oracle_dependencies=5)
        self.assertIn('ORACLE_DEPENDENT', flags)

    def test_flag_oracle_dependent_not_triggered(self):
        flags = self._flags(oracle_dependencies=1)
        self.assertNotIn('ORACLE_DEPENDENT', flags)

    def test_flag_oracle_dependent_boundary(self):
        # threshold is > 2; exactly 2 should NOT trigger
        flags = self._flags(oracle_dependencies=2)
        self.assertNotIn('ORACLE_DEPENDENT', flags)

    def test_flag_battle_tested_triggered(self):
        flags = self._flags(days_live=400, critical_bugs_found=0)
        self.assertIn('BATTLE_TESTED', flags)

    def test_flag_battle_tested_not_triggered_new(self):
        flags = self._flags(days_live=100, critical_bugs_found=0)
        self.assertNotIn('BATTLE_TESTED', flags)

    def test_flag_battle_tested_not_triggered_has_bugs(self):
        flags = self._flags(days_live=500, critical_bugs_found=1)
        self.assertNotIn('BATTLE_TESTED', flags)

    def test_flag_under_audited_triggered(self):
        flags = self._flags(
            lines_of_code=8000, function_count=150, external_call_count=30,
            inheritance_depth=5, assembly_blocks_count=5,
            audit_count=1,
        )
        # complexity score should be > 60
        self.assertIn('UNDER_AUDITED', flags)

    def test_flag_under_audited_not_triggered_many_audits(self):
        flags = self._flags(
            lines_of_code=8000, function_count=150,
            audit_count=3,
        )
        self.assertNotIn('UNDER_AUDITED', flags)

    def test_flag_bug_bounty_active_triggered(self):
        flags = self._flags(bug_bounty_usd=50_000)
        self.assertIn('BUG_BOUNTY_ACTIVE', flags)

    def test_flag_bug_bounty_active_not_triggered(self):
        flags = self._flags(bug_bounty_usd=0)
        self.assertNotIn('BUG_BOUNTY_ACTIVE', flags)

    def test_flags_list_type(self):
        result = self.scorer.score([_make_contract()])
        self.assertIsInstance(result['contracts'][0]['flags'], list)

    def test_flags_subset_of_valid(self):
        flags = self._flags(
            assembly_blocks_count=15, oracle_dependencies=5,
            days_live=400, critical_bugs_found=0,
            bug_bounty_usd=10_000,
        )
        self.assertTrue(set(flags).issubset(VALID_FLAGS))

    def test_multiple_flags_possible(self):
        flags = self._flags(
            assembly_blocks_count=15,
            oracle_dependencies=5,
            bug_bounty_usd=10_000,
            days_live=400,
            critical_bugs_found=0,
        )
        # At least ASSEMBLY_HEAVY + ORACLE_DEPENDENT + BUG_BOUNTY_ACTIVE + BATTLE_TESTED
        self.assertGreaterEqual(len(flags), 3)

    def test_no_flags_for_minimal_contract(self):
        flags = self._flags(
            lines_of_code=10, function_count=2, external_call_count=0,
            inheritance_depth=0, proxy_pattern='none', upgrade_mechanism='none',
            oracle_dependencies=0, assembly_blocks_count=0,
            audit_count=4, bug_bounty_usd=0,
            days_live=10, critical_bugs_found=0,
        )
        # Should have no PROXY_RISK, ASSEMBLY_HEAVY, ORACLE_DEPENDENT, UNDER_AUDITED
        self.assertNotIn('PROXY_RISK', flags)
        self.assertNotIn('ASSEMBLY_HEAVY', flags)
        self.assertNotIn('ORACLE_DEPENDENT', flags)


# ---------------------------------------------------------------------------
# 8. Aggregates
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _make_scorer(self.tmp)

    def _two_contracts(self):
        simple = _make_contract(
            name='SIMPLE_C',
            lines_of_code=50, function_count=5, external_call_count=0,
            inheritance_depth=0, assembly_blocks_count=0,
            proxy_pattern='none', upgrade_mechanism='none',
            audit_count=4, bug_bounty_usd=200_000,
        )
        complex_ = _make_contract(
            name='COMPLEX_C',
            lines_of_code=9000, function_count=180, external_call_count=45,
            inheritance_depth=9, assembly_blocks_count=19,
            proxy_pattern='diamond', upgrade_mechanism='none',
            audit_count=0, bug_bounty_usd=0,
        )
        return [simple, complex_]

    def test_aggregate_most_complex(self):
        result = self.scorer.score(self._two_contracts())
        self.assertEqual(result['aggregates']['most_complex'], 'COMPLEX_C')

    def test_aggregate_safest(self):
        result = self.scorer.score(self._two_contracts())
        self.assertEqual(result['aggregates']['safest'], 'SIMPLE_C')

    def test_aggregate_average_complexity_score(self):
        result = self.scorer.score(self._two_contracts())
        contracts = result['contracts']
        expected = (contracts[0]['complexity_score'] + contracts[1]['complexity_score']) / 2
        self.assertAlmostEqual(result['aggregates']['average_complexity_score'], expected, places=2)

    def test_aggregate_critical_complexity_count(self):
        result = self.scorer.score(self._two_contracts())
        count = result['aggregates']['critical_complexity_count']
        labeled = sum(1 for c in result['contracts'] if c['risk_label'] == 'CRITICAL_COMPLEXITY')
        self.assertEqual(count, labeled)

    def test_aggregate_under_audited_count(self):
        result = self.scorer.score(self._two_contracts())
        count = result['aggregates']['under_audited_count']
        labeled = sum(1 for c in result['contracts'] if 'UNDER_AUDITED' in c['flags'])
        self.assertEqual(count, labeled)

    def test_aggregate_total_contracts(self):
        contracts = [_make_contract(name=f'C{i}') for i in range(6)]
        result = self.scorer.score(contracts)
        self.assertEqual(result['aggregates']['total_contracts'], 6)

    def test_aggregate_empty_nones(self):
        result = self.scorer.score([])
        self.assertIsNone(result['aggregates']['most_complex'])
        self.assertIsNone(result['aggregates']['safest'])

    def test_aggregate_most_complex_score_in_result(self):
        result = self.scorer.score(self._two_contracts())
        self.assertIn('most_complex_score', result['aggregates'])

    def test_aggregate_safest_score_in_result(self):
        result = self.scorer.score(self._two_contracts())
        self.assertIn('safest_score', result['aggregates'])


# ---------------------------------------------------------------------------
# 9. Result structure
# ---------------------------------------------------------------------------

class TestResultStructure(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _make_scorer(self.tmp)

    def test_result_has_contracts_key(self):
        result = self.scorer.score([_make_contract()])
        self.assertIn('contracts', result)

    def test_result_has_aggregates_key(self):
        result = self.scorer.score([_make_contract()])
        self.assertIn('aggregates', result)

    def test_result_has_timestamp(self):
        result = self.scorer.score([_make_contract()])
        self.assertIn('timestamp', result)
        self.assertIsInstance(result['timestamp'], str)

    def test_result_status_ok(self):
        result = self.scorer.score([_make_contract()])
        self.assertEqual(result['status'], 'ok')

    def test_contract_result_has_complexity_score(self):
        c = self.scorer.score([_make_contract()])['contracts'][0]
        self.assertIn('complexity_score', c)

    def test_contract_result_has_upgrade_risk_score(self):
        c = self.scorer.score([_make_contract()])['contracts'][0]
        self.assertIn('upgrade_risk_score', c)

    def test_contract_result_has_audit_coverage_score(self):
        c = self.scorer.score([_make_contract()])['contracts'][0]
        self.assertIn('audit_coverage_score', c)

    def test_contract_result_has_net_risk_score(self):
        c = self.scorer.score([_make_contract()])['contracts'][0]
        self.assertIn('net_risk_score', c)

    def test_contract_result_has_risk_label(self):
        c = self.scorer.score([_make_contract()])['contracts'][0]
        self.assertIn('risk_label', c)

    def test_contract_result_has_flags(self):
        c = self.scorer.score([_make_contract()])['contracts'][0]
        self.assertIn('flags', c)

    def test_contract_name_preserved(self):
        c = self.scorer.score([_make_contract(name='MYCONTRACT')])['contracts'][0]
        self.assertEqual(c['name'], 'MYCONTRACT')

    def test_contract_protocol_preserved(self):
        c = self.scorer.score([_make_contract(protocol='MYPROTOCOL')])['contracts'][0]
        self.assertEqual(c['protocol'], 'MYPROTOCOL')


# ---------------------------------------------------------------------------
# 10. Log file (ring-buffer, atomic write)
# ---------------------------------------------------------------------------

class TestLogFile(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp, 'cclog.json')
        self.scorer = ProtocolSmartContractComplexityScorer(config={
            'log_path': self.log_path,
            'log_cap': 100,
        })

    def test_log_file_created_after_score(self):
        self.scorer.score([_make_contract()])
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_file_is_valid_json(self):
        self.scorer.score([_make_contract()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_entry_has_timestamp(self):
        self.scorer.score([_make_contract()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('timestamp', data[0])

    def test_log_entry_has_total_contracts(self):
        self.scorer.score([_make_contract()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('total_contracts', data[0])

    def test_log_entry_has_average_complexity_score(self):
        self.scorer.score([_make_contract()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('average_complexity_score', data[0])

    def test_log_entry_has_critical_complexity_count(self):
        self.scorer.score([_make_contract()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('critical_complexity_count', data[0])

    def test_log_entry_has_under_audited_count(self):
        self.scorer.score([_make_contract()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertIn('under_audited_count', data[0])

    def test_log_multiple_runs_append(self):
        for _ in range(4):
            self.scorer.score([_make_contract()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 4)

    def test_log_ring_buffer_cap(self):
        scorer = ProtocolSmartContractComplexityScorer(config={
            'log_path': self.log_path,
            'log_cap': 3,
        })
        for _ in range(7):
            scorer.score([_make_contract()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 3)

    def test_log_no_tmp_file_remains(self):
        self.scorer.score([_make_contract()])
        self.assertFalse(os.path.exists(self.log_path + '.tmp'))

    def test_log_invalid_existing_json_reset(self):
        with open(self.log_path, 'w') as f:
            f.write('{"broken"}')
        self.scorer.score([_make_contract()])
        with open(self.log_path) as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

    def test_log_subdirectory_created(self):
        nested = os.path.join(self.tmp, 'a', 'b', 'clog.json')
        scorer = ProtocolSmartContractComplexityScorer(config={
            'log_path': nested,
            'log_cap': 10,
        })
        scorer.score([_make_contract()])
        self.assertTrue(os.path.exists(nested))

    def test_log_empty_score_still_writes(self):
        self.scorer.score([])
        self.assertTrue(os.path.exists(self.log_path))


# ---------------------------------------------------------------------------
# 11. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scorer = _make_scorer(self.tmp)

    def test_zero_loc_no_error(self):
        result = self.scorer.score([_make_contract(lines_of_code=0)])
        self.assertIsNotNone(result)

    def test_very_high_loc_capped(self):
        result = self.scorer.score([_make_contract(lines_of_code=1_000_000)])
        score = result['contracts'][0]['complexity_score']
        self.assertLessEqual(score, 100.0)

    def test_unknown_proxy_pattern_uses_default(self):
        result = self.scorer.score([_make_contract(proxy_pattern='unknown_type')])
        self.assertIsNotNone(result['contracts'][0]['upgrade_risk_score'])

    def test_all_max_values_no_error(self):
        result = self.scorer.score([_make_contract(
            lines_of_code=100_000,
            function_count=10_000,
            external_call_count=5_000,
            inheritance_depth=500,
            assembly_blocks_count=1_000,
        )])
        self.assertIsNotNone(result)

    def test_no_critical_bugs_and_old_contract_battle_tested(self):
        result = self.scorer.score([_make_contract(
            days_live=730, critical_bugs_found=0,
        )])
        flags = result['contracts'][0]['flags']
        self.assertIn('BATTLE_TESTED', flags)

    def test_missing_fields_handled(self):
        result = self.scorer.score([{'name': 'Minimal'}])
        self.assertIn('complexity_score', result['contracts'][0])

    def test_zero_audit_zero_bounty_no_coverage(self):
        result = self.scorer.score([_make_contract(audit_count=0, bug_bounty_usd=0)])
        self.assertEqual(result['contracts'][0]['audit_coverage_score'], 0.0)

    def test_very_large_bug_bounty_capped(self):
        result = self.scorer.score([_make_contract(audit_count=0, bug_bounty_usd=1_000_000_000)])
        score = result['contracts'][0]['audit_coverage_score']
        self.assertLessEqual(score, 100.0)


if __name__ == '__main__':
    unittest.main()
