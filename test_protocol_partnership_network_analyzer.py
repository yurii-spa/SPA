"""Tests for protocol_partnership_network_analyzer.py — MP-896. ≥65 tests, stdlib unittest."""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from spa_core.analytics.protocol_partnership_network_analyzer import analyze, run


def _net(*protocols):
    return {'protocols': list(protocols)}


def _proto(name, tvl=1_000_000, integrations=None):
    return {'name': name, 'tvl_usd': tvl, 'integrations': integrations or []}


# ── Empty / minimal input ─────────────────────────────────────────────────────

class TestEmptyNetwork(unittest.TestCase):
    def test_empty_protocols(self):
        r = analyze({'protocols': []})
        self.assertEqual(r['protocols'], [])

    def test_empty_most_connected_none(self):
        self.assertIsNone(analyze({'protocols': []})['most_connected'])

    def test_empty_highest_tvl_none(self):
        self.assertIsNone(analyze({'protocols': []})['highest_tvl_influence'])

    def test_empty_density_zero(self):
        self.assertEqual(analyze({'protocols': []})['network_density'], 0.0)

    def test_empty_avg_composability_zero(self):
        self.assertEqual(analyze({'protocols': []})['average_composability_score'], 0.0)

    def test_empty_isolated_count_zero(self):
        self.assertEqual(analyze({'protocols': []})['isolated_count'], 0)

    def test_empty_has_timestamp(self):
        t0 = time.time()
        self.assertGreaterEqual(analyze({'protocols': []})['timestamp'], t0)

    def test_missing_protocols_key(self):
        r = analyze({})
        self.assertEqual(r['protocols'], [])

    def test_none_network_treated_as_empty(self):
        r = analyze(None)
        self.assertEqual(r['protocols'], [])


# ── Single protocol ───────────────────────────────────────────────────────────

class TestSingleProtocol(unittest.TestCase):
    def test_single_degree_zero(self):
        r = analyze(_net(_proto('Aave')))
        p = r['protocols'][0]
        self.assertEqual(p['total_degree'], 0)
        self.assertEqual(p['outbound_integrations'], 0)
        self.assertEqual(p['inbound_integrations'], 0)

    def test_single_density_zero(self):
        self.assertEqual(analyze(_net(_proto('Aave')))['network_density'], 0.0)

    def test_single_most_connected(self):
        self.assertEqual(analyze(_net(_proto('Aave')))['most_connected'], 'Aave')

    def test_single_isolated_count_one(self):
        self.assertEqual(analyze(_net(_proto('Aave')))['isolated_count'], 1)

    def test_single_composability_zero(self):
        self.assertEqual(analyze(_net(_proto('Aave')))['protocols'][0]['composability_score'], 0)

    def test_single_resilience_none(self):
        self.assertEqual(analyze(_net(_proto('Aave')))['protocols'][0]['network_resilience'], 'NONE')

    def test_single_dep_risk_low(self):
        self.assertEqual(analyze(_net(_proto('Aave')))['protocols'][0]['dependency_risk'], 'LOW')

    def test_single_centrality_isolated(self):
        self.assertEqual(analyze(_net(_proto('Aave')))['protocols'][0]['centrality_label'], 'ISOLATED')


# ── Outbound / inbound counts ─────────────────────────────────────────────────

class TestDegrees(unittest.TestCase):
    def test_outbound_counted(self):
        r = analyze(_net(_proto('A', integrations=['B', 'C']), _proto('B'), _proto('C')))
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['outbound_integrations'], 2)

    def test_inbound_counted(self):
        r = analyze(_net(_proto('A', integrations=['B']), _proto('B', integrations=['A'])))
        b = next(x for x in r['protocols'] if x['name'] == 'B')
        self.assertEqual(b['inbound_integrations'], 1)

    def test_total_degree_outbound_plus_inbound(self):
        r = analyze(_net(_proto('A', integrations=['B']), _proto('B', integrations=['A'])))
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['total_degree'], a['outbound_integrations'] + a['inbound_integrations'])

    def test_hub_degree(self):
        protos = [_proto('A', integrations=['B', 'C', 'D', 'E', 'F'])]
        for name in ['B', 'C', 'D', 'E', 'F']:
            protos.append(_proto(name, integrations=['A']))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['outbound_integrations'], 5)
        self.assertEqual(a['inbound_integrations'], 5)
        self.assertEqual(a['total_degree'], 10)

    def test_unregistered_target_skipped_for_inbound(self):
        # A → Unknown; Unknown not in protocols list → should not crash
        r = analyze(_net(_proto('A', integrations=['Unknown'])))
        a = r['protocols'][0]
        self.assertEqual(a['outbound_integrations'], 1)  # outbound still counted

    def test_self_loop_counts_outbound_and_inbound(self):
        r = analyze(_net(_proto('A', integrations=['A'])))
        a = r['protocols'][0]
        self.assertEqual(a['outbound_integrations'], 1)
        self.assertEqual(a['inbound_integrations'], 1)
        self.assertEqual(a['total_degree'], 2)


# ── Centrality label ──────────────────────────────────────────────────────────

class TestCentralityLabel(unittest.TestCase):
    def test_isolated_degree_0(self):
        r = analyze(_net(_proto('A')))
        self.assertEqual(r['protocols'][0]['centrality_label'], 'ISOLATED')

    def test_isolated_degree_1(self):
        r = analyze(_net(_proto('A', integrations=['B']), _proto('B')))
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['centrality_label'], 'ISOLATED')  # outbound=1, inbound=0 → total=1

    def test_participant_degree_2(self):
        r = analyze(_net(_proto('A', integrations=['B', 'C']), _proto('B'), _proto('C')))
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['centrality_label'], 'PARTICIPANT')

    def test_connector_degree_5(self):
        protos = [_proto('A', integrations=['B', 'C', 'D', 'E', 'F'])]
        for n in ['B', 'C', 'D', 'E', 'F']:
            protos.append(_proto(n))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['centrality_label'], 'CONNECTOR')

    def test_hub_degree_10(self):
        protos = [_proto('A', integrations=['B', 'C', 'D', 'E', 'F'])]
        for n in ['B', 'C', 'D', 'E', 'F']:
            protos.append(_proto(n, integrations=['A']))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['centrality_label'], 'HUB')

    def test_boundary_degree_9_is_connector(self):
        # outbound=9, inbound=0 → total=9 → CONNECTOR
        protos = [_proto('A', integrations=[f'X{i}' for i in range(9)])]
        for i in range(9):
            protos.append(_proto(f'X{i}'))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['centrality_label'], 'CONNECTOR')

    def test_boundary_degree_4_is_participant(self):
        # outbound=4, inbound=0 → total=4 → PARTICIPANT
        protos = [_proto('A', integrations=['B', 'C', 'D', 'E'])]
        for n in ['B', 'C', 'D', 'E']:
            protos.append(_proto(n))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['centrality_label'], 'PARTICIPANT')


# ── Dependency risk ───────────────────────────────────────────────────────────

class TestDependencyRisk(unittest.TestCase):
    def test_low_inbound_0(self):
        self.assertEqual(analyze(_net(_proto('A')))['protocols'][0]['dependency_risk'], 'LOW')

    def test_low_inbound_2(self):
        protos = [_proto('A'), _proto('B', integrations=['A']), _proto('C', integrations=['A'])]
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['dependency_risk'], 'LOW')

    def test_moderate_inbound_3(self):
        protos = [_proto('A')]
        for n in ['B', 'C', 'D']:
            protos.append(_proto(n, integrations=['A']))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['inbound_integrations'], 3)
        self.assertEqual(a['dependency_risk'], 'MODERATE')

    def test_high_inbound_5(self):
        protos = [_proto('A')]
        for n in ['B', 'C', 'D', 'E', 'F']:
            protos.append(_proto(n, integrations=['A']))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['dependency_risk'], 'HIGH')

    def test_critical_inbound_8(self):
        protos = [_proto('A')]
        for i in range(8):
            protos.append(_proto(f'X{i}', integrations=['A']))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['dependency_risk'], 'CRITICAL')

    def test_boundary_inbound_7_high(self):
        protos = [_proto('A')]
        for i in range(7):
            protos.append(_proto(f'X{i}', integrations=['A']))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['dependency_risk'], 'HIGH')


# ── Composability score ───────────────────────────────────────────────────────

class TestComposabilityScore(unittest.TestCase):
    def test_zero_degree_zero_score(self):
        self.assertEqual(analyze(_net(_proto('A')))['protocols'][0]['composability_score'], 0)

    def test_degree_5_score_50(self):
        protos = [_proto('A', integrations=['B', 'C', 'D', 'E', 'F'])]
        for n in ['B', 'C', 'D', 'E', 'F']:
            protos.append(_proto(n))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['composability_score'], 50)

    def test_degree_10_score_100(self):
        protos = [_proto('A', integrations=['B', 'C', 'D', 'E', 'F'])]
        for n in ['B', 'C', 'D', 'E', 'F']:
            protos.append(_proto(n, integrations=['A']))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['composability_score'], 100)

    def test_capped_at_100(self):
        protos = [_proto('A', integrations=[f'X{i}' for i in range(7)])]
        for i in range(7):
            protos.append(_proto(f'X{i}', integrations=['A']))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        # total_degree = 7+7=14, 14*10=140 → capped at 100
        self.assertEqual(a['composability_score'], 100)

    def test_formula_degree_3(self):
        protos = [_proto('A', integrations=['B', 'C', 'D'])]
        for n in ['B', 'C', 'D']:
            protos.append(_proto(n))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['composability_score'], 30)


# ── Network resilience ────────────────────────────────────────────────────────

class TestNetworkResilience(unittest.TestCase):
    def test_none_outbound_0(self):
        self.assertEqual(analyze(_net(_proto('A')))['protocols'][0]['network_resilience'], 'NONE')

    def test_single_path_outbound_1(self):
        r = analyze(_net(_proto('A', integrations=['B']), _proto('B')))
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['network_resilience'], 'SINGLE_PATH')

    def test_some_redundancy_outbound_2(self):
        r = analyze(_net(_proto('A', integrations=['B', 'C']), _proto('B'), _proto('C')))
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['network_resilience'], 'SOME_REDUNDANCY')

    def test_redundant_outbound_3(self):
        r = analyze(_net(_proto('A', integrations=['B', 'C', 'D']),
                         _proto('B'), _proto('C'), _proto('D')))
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['network_resilience'], 'REDUNDANT')

    def test_redundant_outbound_5(self):
        protos = [_proto('A', integrations=['B', 'C', 'D', 'E', 'F'])]
        for n in ['B', 'C', 'D', 'E', 'F']:
            protos.append(_proto(n))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['network_resilience'], 'REDUNDANT')


# ── TVL influence ─────────────────────────────────────────────────────────────

class TestTVLInfluence(unittest.TestCase):
    def test_influence_sum(self):
        p_a = _proto('A', tvl=1_000_000, integrations=['C'])
        p_b = _proto('B', tvl=2_000_000, integrations=['C'])
        p_c = _proto('C', tvl=5_000_000, integrations=[])
        r = analyze(_net(p_a, p_b, p_c))
        c = next(x for x in r['protocols'] if x['name'] == 'C')
        self.assertAlmostEqual(c['tvl_influence_score'], 3_000_000.0, places=0)

    def test_no_integrators_zero_influence(self):
        r = analyze(_net(_proto('A', tvl=1_000_000)))
        self.assertEqual(r['protocols'][0]['tvl_influence_score'], 0.0)

    def test_highest_tvl_influence_field(self):
        p_a = _proto('A', tvl=10_000_000, integrations=['C'])
        p_b = _proto('B', tvl=500_000, integrations=['C'])
        p_c = _proto('C', tvl=1_000_000)
        r = analyze(_net(p_a, p_b, p_c))
        self.assertEqual(r['highest_tvl_influence'], 'C')

    def test_single_protocol_tvl_influence_zero(self):
        r = analyze(_net(_proto('Solo', tvl=999_999_999)))
        self.assertEqual(r['protocols'][0]['tvl_influence_score'], 0.0)


# ── Network density ───────────────────────────────────────────────────────────

class TestNetworkDensity(unittest.TestCase):
    def test_empty_density_zero(self):
        self.assertEqual(analyze({'protocols': []})['network_density'], 0.0)

    def test_single_density_zero(self):
        self.assertEqual(analyze(_net(_proto('A')))['network_density'], 0.0)

    def test_two_no_edges_density_zero(self):
        self.assertEqual(analyze(_net(_proto('A'), _proto('B')))['network_density'], 0.0)

    def test_two_one_edge_density_half(self):
        r = analyze(_net(_proto('A', integrations=['B']), _proto('B')))
        # n=2, edges=1, max=2 → density=0.5
        self.assertAlmostEqual(r['network_density'], 0.5, places=5)

    def test_three_fully_connected_density_one(self):
        p_a = _proto('A', integrations=['B', 'C'])
        p_b = _proto('B', integrations=['A', 'C'])
        p_c = _proto('C', integrations=['A', 'B'])
        r = analyze(_net(p_a, p_b, p_c))
        # n=3, edges=6, max=3*2=6 → density=1.0
        self.assertAlmostEqual(r['network_density'], 1.0, places=5)

    def test_three_two_edges(self):
        p_a = _proto('A', integrations=['B'])
        p_b = _proto('B', integrations=['C'])
        p_c = _proto('C')
        r = analyze(_net(p_a, p_b, p_c))
        # n=3, edges=2, max=6 → density=2/6
        self.assertAlmostEqual(r['network_density'], 2 / 6, places=5)


# ── Most connected ────────────────────────────────────────────────────────────

class TestMostConnected(unittest.TestCase):
    def test_single(self):
        self.assertEqual(analyze(_net(_proto('A')))['most_connected'], 'A')

    def test_clear_winner(self):
        r = analyze(_net(_proto('A', integrations=['B', 'C', 'D']),
                         _proto('B'), _proto('C'), _proto('D')))
        self.assertEqual(r['most_connected'], 'A')

    def test_empty_none(self):
        self.assertIsNone(analyze({'protocols': []})['most_connected'])


# ── Isolated count ────────────────────────────────────────────────────────────

class TestIsolatedCount(unittest.TestCase):
    def test_all_isolated(self):
        r = analyze(_net(_proto('A'), _proto('B'), _proto('C')))
        self.assertEqual(r['isolated_count'], 3)

    def test_none_isolated(self):
        r = analyze(_net(_proto('A', integrations=['B']), _proto('B', integrations=['A'])))
        # both have degree=2 → PARTICIPANT
        self.assertEqual(r['isolated_count'], 0)

    def test_partial_isolated(self):
        r = analyze(_net(_proto('A', integrations=['B']), _proto('B', integrations=['A']),
                         _proto('C')))
        self.assertEqual(r['isolated_count'], 1)


# ── Average composability ─────────────────────────────────────────────────────

class TestAverageComposability(unittest.TestCase):
    def test_empty_zero(self):
        self.assertEqual(analyze({'protocols': []})['average_composability_score'], 0.0)

    def test_single_zero(self):
        self.assertEqual(analyze(_net(_proto('A')))['average_composability_score'], 0.0)

    def test_two_same(self):
        r = analyze(_net(_proto('A', integrations=['B']), _proto('B', integrations=['A'])))
        # both degree=2, score=20; avg=20
        self.assertAlmostEqual(r['average_composability_score'], 20.0, places=5)


# ── run() / persistence ───────────────────────────────────────────────────────

class TestRunPersistence(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_run_creates_log(self):
        run({'protocols': []}, data_dir=self.tmpdir)
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, 'partnership_network_log.json')))

    def test_run_log_is_list(self):
        run({'protocols': []}, data_dir=self.tmpdir)
        with open(os.path.join(self.tmpdir, 'partnership_network_log.json')) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_run_accumulates(self):
        run({'protocols': []}, data_dir=self.tmpdir)
        run({'protocols': []}, data_dir=self.tmpdir)
        with open(os.path.join(self.tmpdir, 'partnership_network_log.json')) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_ring_buffer_cap(self):
        for _ in range(105):
            run({'protocols': []}, data_dir=self.tmpdir)
        with open(os.path.join(self.tmpdir, 'partnership_network_log.json')) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_run_returns_result(self):
        result = run({'protocols': []}, data_dir=self.tmpdir)
        self.assertIn('protocols', result)
        self.assertIn('network_density', result)

    def test_atomic_no_tmp_left(self):
        run({'protocols': []}, data_dir=self.tmpdir)
        self.assertFalse(os.path.exists(
            os.path.join(self.tmpdir, 'partnership_network_log.json.tmp')))


# ── Output fields ─────────────────────────────────────────────────────────────

class TestOutputFields(unittest.TestCase):
    def test_top_level_keys(self):
        r = analyze({'protocols': []})
        for k in ('protocols', 'most_connected', 'highest_tvl_influence',
                  'network_density', 'average_composability_score', 'isolated_count', 'timestamp'):
            self.assertIn(k, r)

    def test_protocol_result_keys(self):
        r = analyze(_net(_proto('A')))
        p = r['protocols'][0]
        for k in ('name', 'outbound_integrations', 'inbound_integrations', 'total_degree',
                  'composability_score', 'centrality_label', 'dependency_risk',
                  'tvl_influence_score', 'network_resilience'):
            self.assertIn(k, p)

    def test_names_preserved(self):
        r = analyze(_net(_proto('UniswapV3'), _proto('AaveV3')))
        names = [p['name'] for p in r['protocols']]
        self.assertIn('UniswapV3', names)
        self.assertIn('AaveV3', names)

    def test_order_preserved(self):
        r = analyze(_net(_proto('Z'), _proto('Y'), _proto('X')))
        self.assertEqual([p['name'] for p in r['protocols']], ['Z', 'Y', 'X'])

    def test_timestamp_float(self):
        r = analyze({'protocols': []})
        self.assertIsInstance(r['timestamp'], float)


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    def test_20_protocol_ring_no_crash(self):
        protos = [_proto(f'P{i}', integrations=[f'P{(i + 1) % 20}']) for i in range(20)]
        r = analyze({'protocols': protos})
        self.assertEqual(len(r['protocols']), 20)

    def test_zero_tvl_no_influence(self):
        p_a = _proto('A', tvl=0, integrations=['B'])
        p_b = _proto('B', tvl=1_000_000)
        r = analyze(_net(p_a, p_b))
        b = next(x for x in r['protocols'] if x['name'] == 'B')
        self.assertEqual(b['tvl_influence_score'], 0.0)

    def test_all_outbound_no_inbound(self):
        # Star topology: A→B, A→C, A→D; B, C, D have no outbound
        r = analyze(_net(_proto('A', integrations=['B', 'C', 'D']),
                         _proto('B'), _proto('C'), _proto('D')))
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['inbound_integrations'], 0)
        self.assertEqual(a['outbound_integrations'], 3)

    def test_inbound_only_hub(self):
        # B, C, D all point to A but A has no outbound
        protos = [_proto('A')]
        for n in ['B', 'C', 'D', 'E', 'F']:
            protos.append(_proto(n, integrations=['A']))
        r = analyze({'protocols': protos})
        a = next(x for x in r['protocols'] if x['name'] == 'A')
        self.assertEqual(a['outbound_integrations'], 0)
        self.assertEqual(a['inbound_integrations'], 5)
        self.assertEqual(a['dependency_risk'], 'HIGH')


if __name__ == '__main__':
    unittest.main()
