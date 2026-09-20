"""Regressions for Investments & R&D (Director OS Phase 7).

The risk of an investment screen is the most expensive one in this repository: presenting
paper as real, a forecast as earned, a source's proposal as advice, or a number nobody
measured. Each test below pins one of those. Director OS must stay a reader.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

_root = Path(__file__).parents[2] / 'scripts/cartographer'


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _root / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


inv = _load('investments')
pr = _load('portal_render')
SENTINEL = 'SYNTHETIC_SECRET_SENTINEL_P7'


def _prod(td, **over):
    root = Path(td) / 'prod'
    (root / 'data/strategy_lab').mkdir(parents=True, exist_ok=True)
    docs = {
        'capital_config.json': {
            'capital': {'starting_capital_usd': 100000.0, 'currency': 'USDC',
                        'mode': 'paper', 'is_demo': False},
            'allocation_limits': {'min_cash_buffer_pct': 5.0},
            'risk_parameters': {'max_drawdown_kill_pct': 5.0},
            'created_at': '2026-06-19'},
        'current_positions.json': {
            'generated_at': '2026-09-20T06:00:00+00:00', 'execution_mode':
            'read_only_simulation', 'is_demo': False, 'capital_usd': 100000.0,
            'current_equity_usd': 101340.69, 'net_pnl_usd': 1340.69},
        'equity_curve_daily.json': {'generated_at': '2026-09-20T06:00:00+00:00',
                                    'execution_mode': 'read_only_simulation'},
        'paper_trading_status.json': {'execution_mode': 'read_only_simulation',
                                      'is_demo': False, 'days_running': 100},
        'strategy_configs.json': {'configs': [
            {'id': 'S0', 'valid': True, 'config_hash': 'abc'},
            {'id': 'S1', 'valid': True, 'config_hash': 'def'}]},
        'promotion_report.json': {
            'generated_at': '2026-09-20T06:00:42+00:00', 'is_demo': False,
            'decisions': [{'strategy_id': 'S0', 'action': 'promote',
                           'reason': 'sharpe high', 'metrics': {'sharpe_30d': 8.2},
                           'ts': '2026-09-20T06:00:42+00:00'}]},
        'strategy_lab_promotion.json': {
            'generated_at': '2026-06-25T19:57:47+00:00',
            'pipeline': 'RESEARCH -> BACKTEST -> WALK-FORWARD -> PAPER -> CANARY -> FULL',
            'stage_counts': {'PAPER_CANDIDATE': 1, 'REJECT': 1},
            'sleeves': [{'sleeve': 'alpha', 'stage': 'PAPER_CANDIDATE',
                         'beats_floor': True,
                         'criteria': {'drawdown_within_band': {'pass': True,
                                                               'detail': '<= 15%'}}},
                        {'sleeve': 'beta', 'stage': 'REJECT', 'beats_floor': False,
                         'criteria': {}}]},
        'golive_status.json': {'ready': True, 'passed': 29, 'total': 29, 'blockers': [],
                               'timestamp': '2026-09-20T06:00:00+00:00'},
        'kill_switch_status.json': {'generated_at': '2026-09-20T16:18:00+00:00',
                                    'triggered': False, 'reason': 'all triggers clear'},
        'allocation_rationale.json': {'generated_at': '2026-09-20T06:00:00+00:00',
                                      'mode': 'SHADOW', 'capital_usd': 100000.0},
    }
    docs.update(over)
    for name, body in docs.items():
        (root / 'data' / name).write_text(json.dumps(body, ensure_ascii=False))
    (root / 'data/strategy_lab/portfolio_book.json').write_text(json.dumps(
        {'generated_at': '2026-06-29T16:45:48+00:00', 'is_advisory': True,
         'research_only': True}, ensure_ascii=False))
    return root


def _build(td, **kw):
    return inv.build_investment_snapshot(kw.get('production') or _prod(td))


class PaperIsNeverPresentedAsReal(unittest.TestCase):
    def test_real_capital_is_not_proven_and_says_so(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertIs(s['real_capital_proven'], False)
            self.assertIsNone(s['capital_by_mode']['REAL'])
            self.assertIn('НЕ ДОКАЗАН', s['real_capital_note'])
            self.assertEqual(s['capital_by_mode']['PAPER'], 101340.69)

    def test_is_demo_false_is_never_read_as_real(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td, **{'current_positions.json': {
                'generated_at': '2026-09-20T06:00:00+00:00', 'is_demo': False,
                'current_equity_usd': 5.0}})
            s = _build(td, production=root)
            rec = [x for x in s['sources'] if x['source'] == 'current_positions.json'][0]
            self.assertEqual(rec['mode'], 'UNKNOWN')
            self.assertIn('НЕ режим', rec['mode_evidence']['detail'])
            self.assertIs(s['real_capital_proven'], False)

    def test_modes_are_never_summed(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            values = [v for v in s['capital_by_mode'].values() if v is not None]
            self.assertNotIn(sum(values), [v for k, v in s['capital_by_mode'].items()
                                           if k == 'REAL' and v is not None])
            self.assertEqual(set(s['capital_by_mode']), set(inv.MODES))
            page = pr._investments(s, {'investment_snapshot.json'})
            self.assertIn('Режимы не складываются', page)
            self.assertIn('БУМАГА', page)

    def test_the_contract_refuses_real_capital_without_a_declared_mode(self):
        with tempfile.TemporaryDirectory() as td:
            broken = copy.deepcopy(_build(td))
            broken['capital_by_mode']['REAL'] = 101340.69
            with self.assertRaises(inv.InvestmentInputError):
                inv.validate_investment_snapshot(broken, 'mutated')

    def test_the_contract_refuses_an_object_declared_real_without_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            broken = copy.deepcopy(_build(td))
            broken['objects'][0]['mode'] = 'REAL'
            with self.assertRaises(inv.InvestmentInputError):
                inv.validate_investment_snapshot(broken, 'mutated')

    def test_an_unknown_mode_may_not_carry_capital(self):
        with tempfile.TemporaryDirectory() as td:
            broken = copy.deepcopy(_build(td))
            victim = [o for o in broken['objects'] if o['mode'] == 'UNKNOWN'][0]
            victim['capital_value'] = 100.0
            with self.assertRaises(inv.InvestmentInputError):
                inv.validate_investment_snapshot(broken, 'mutated')


class NothingIsCalculatedThatTheSourceDidNotSay(unittest.TestCase):
    def test_a_missing_metric_stays_empty(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            configs = [o for o in s['objects']
                       if 'strategy_configs.json' in o['sources']
                       and 'promotion_report.json' not in o['sources']]
            self.assertTrue(configs)
            for o in configs:
                self.assertEqual(o['performance_metrics'], [])
                self.assertEqual(o['yield_metrics'], [])
                self.assertIsNone(o['capital_value'])
                self.assertIsNone(o['risk_classification'])

    def test_metrics_are_carried_verbatim_from_the_source(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            promo = [o for o in s['objects'] if o['strategy_id'] == 'S0'][0]
            names = {m['name']: m['value'] for m in promo['performance_metrics']}
            self.assertEqual(names['sharpe_30d'], 8.2)
            self.assertTrue(all(m['source'] == 'promotion_report.json'
                                for m in promo['performance_metrics']))

    def test_risk_limits_are_quoted_not_invented(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertEqual(s['risk_limits']['allocation_limits'],
                             {'min_cash_buffer_pct': 5.0})
            self.assertEqual(s['risk_limits']['source'], 'capital_config.json')

    def test_owner_approval_is_unknown_unless_evidenced(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertTrue(all(o['owner_approval_status'] == 'UNKNOWN'
                                for o in s['objects']))
            self.assertIn('за владельцем', s['golive']['note'])

    def test_go_live_readiness_is_not_an_approval(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertIs(s['golive']['ready'], True)
            self.assertTrue(all(o['owner_approval_status'] != 'APPROVED'
                                for o in s['objects']))
            page = pr._investments(s, {'investment_snapshot.json'})
            self.assertIn('готовность гейтов — НЕ разрешение', page)

    def test_an_unreadable_source_is_not_read_as_no_investments(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            (root / 'data/promotion_report.json').write_text('{ не json')
            s = _build(td, production=root)
            rec = [x for x in s['sources'] if x['source'] == 'promotion_report.json'][0]
            self.assertEqual(rec['status'], 'UNREADABLE')
            self.assertEqual([o for o in s['objects']
                              if 'promotion_report.json' in o['sources']], [])


class ResearchNeverBecomesPromotion(unittest.TestCase):
    def test_the_pipeline_is_taken_from_the_source(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertIn('RESEARCH', s['rnd_pipeline'])
            self.assertIn('CANARY', s['rnd_pipeline'])
            self.assertEqual(s['lifecycle_source'], inv.LIFECYCLE_SOURCE)

    def test_lab_sleeves_are_rnd_and_carry_no_capital(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            sleeves = [o for o in s['objects'] if o['mode'] == 'RND']
            self.assertEqual(len(sleeves), 2)
            for o in sleeves:
                self.assertIsNone(o['capital_value'])
                self.assertIn(o['lifecycle_state'], ('PAPER_CANDIDATE', 'REJECT'))

    def test_a_promotion_decision_is_labelled_a_source_proposal(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            promo = [o for o in s['objects'] if o['strategy_id'] == 'S0'][0]
            self.assertEqual(promo['promotion_status'], 'PROMOTE')
            self.assertTrue(any('ПРЕДЛОЖЕНИЕ ИСТОЧНИКА' in e['detail']
                                for e in promo['evidence']))
            page = pr._investments(s, {'investment_snapshot.json'})
            self.assertIn('НЕ совет Director OS', page)

    def test_rnd_is_never_given_an_owner_approval_by_itself(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            for o in s['objects']:
                if o['mode'] == 'RND':
                    self.assertEqual(o['owner_approval_status'], 'UNKNOWN')
                    self.assertIsNone(o['canary_status'])


class ThePageActsOnNothing(unittest.TestCase):
    def test_no_control_performs_an_investment_action(self):
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            page = pr._investments(_build(td), {'investment_snapshot.json'})
            self.assertEqual(page.count('<button'), 0)
            self.assertEqual(page.count('<form'), 0)
            handlers = set(_re.findall(r'on[a-z]+="([A-Za-z_]+)\(', page))
            self.assertLessEqual(handlers, {'spaFilter', 'spaSort'})
            # <option> намеренно НЕ проверяется словами: это ЗНАЧЕНИЕ фильтра из словаря
            # самого источника (например PROMOTE — его собственное слово), а не кнопка.
            # Нажать option значит отфильтровать, а не продвинуть.
            for verb in ('Approve investment', 'Promote', 'Allocate', 'Rebalance',
                         'Execute', 'Change risk', 'Change rate', 'Инвестировать',
                         'Продвинуть', 'Перебалансировать', 'Исполнить'):
                for label in _re.findall(r'<(?:button|a|input|select)\b[^>]*>([^<]*)',
                                         page):
                    self.assertNotIn(verb.lower(), label.strip().lower())
            options = _re.findall(r'<option value="([^"]*)"', page)
            self.assertTrue(all(o == '' or o in
                                {str(x['mode']) for x in _build(td)['objects']}
                                | {str(x['lifecycle_state'])
                                   for x in _build(td)['objects']}
                                | {str(x.get('promotion_status') or 'нет')
                                   for x in _build(td)['objects']}
                                | {', '.join(sorted(x['sources']))
                                   for x in _build(td)['objects']}
                                | {x['owner_approval_status']
                                   for x in _build(td)['objects']}
                                | {'imode', 'ilife', 'isource'}
                                for o in options))

    def test_the_mode_is_visible_on_every_row(self):
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            page = pr._investments(s, {'investment_snapshot.json'})
            rows = _re.findall(r'<div class="row"[^>]*>', page)
            self.assertTrue(rows)
            for row in rows:
                self.assertIn('data-imode', row)
            self.assertIn('РЕЖИМ НЕ ИЗМЕРЕН', page)

    def test_every_facet_option_exists_in_the_data(self):
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            page = pr._investments(s, {'investment_snapshot.json'})
            block = page[page.index('id="investments-scope"'):]
            block = block[:block.index('data-role="list"')]
            facets = _re.findall(r'<select[^>]*data-role="facet"[^>]*>(.*?)</select>',
                                 block, _re.S)
            self.assertEqual(len(facets), 5)
            options = {o for f in facets
                       for o in _re.findall(r'<option value="([^"]*)"', f)} - {''}
            present = ({o['mode'] for o in s['objects']}
                       | {str(o['lifecycle_state']) for o in s['objects']}
                       | {str(o.get('promotion_status') or 'нет') for o in s['objects']}
                       | {', '.join(sorted(o['sources'])) for o in s['objects']}
                       | {o['owner_approval_status'] for o in s['objects']})
            self.assertLessEqual(options, present)

    def test_an_absent_snapshot_is_not_rendered_as_no_investments(self):
        page = pr._investments(None, set())
        self.assertIn('не приложен', page)
        self.assertIn('НЕ значит, что инвестиций нет', page)

    def test_counts_match_the_objects(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            c = s['counts']
            self.assertEqual(c['objects'], len(s['objects']))
            self.assertEqual(sum(c['by_mode'].values()), len(s['objects']))
            self.assertEqual(c['rnd_objects'],
                             sum(1 for o in s['objects'] if o['mode'] == 'RND'))


class NothingIsWrittenAndNothingLeaves(unittest.TestCase):
    def test_the_run_writes_nothing_into_production(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            before = {str(p.relative_to(root)): p.stat().st_mtime_ns
                      for p in root.rglob('*') if p.is_file()}
            inv.main(['--production', str(root), '--output', str(Path(td) / 'out')])
            after = {str(p.relative_to(root)): p.stat().st_mtime_ns
                     for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before, after)

    def test_the_snapshot_declares_it_writes_no_capital(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertIs(s['writes_capital'], False)
            self.assertIs(s['creates_strategies'], False)
            self.assertIs(s['calculates_recommendations'], False)
            self.assertIs(s['is_not_an_investment_engine'], True)
            broken = copy.deepcopy(s)
            broken['writes_capital'] = True
            with self.assertRaises(inv.InvestmentInputError):
                inv.validate_investment_snapshot(broken, 'mutated')

    def test_a_credential_shape_never_reaches_the_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            leak = f'ghp_{"c" * 36}'
            root = _prod(td, **{'strategy_configs.json': {'configs': [
                {'id': f'S-{leak}', 'valid': True, 'config_hash': 'x'}]}})
            s = _build(td, production=root)
            self.assertNotIn(leak, json.dumps(s, ensure_ascii=False))
            self.assertIn('ВЫРЕЗАНО', json.dumps(s, ensure_ascii=False))

    def test_the_module_never_imports_a_door_to_the_machine(self):
        source = (_root / 'investments.py').read_text()
        for banned in ('import subprocess', 'import socket', 'import urllib',
                       'from subprocess', 'from socket', 'from urllib'):
            self.assertNotIn(banned, source)

    def test_the_renderer_never_reaches_the_network(self):
        import socket
        import urllib.request

        def refuse(*a, **k):
            raise AssertionError('рендер вышел наружу')

        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            with patch.object(socket, 'socket', refuse), \
                 patch.object(urllib.request, 'urlopen', refuse):
                page = pr._investments(s, {'investment_snapshot.json'})
            self.assertNotIn('http://', page)
            self.assertNotIn('https://', page)

    def test_the_output_may_not_land_in_production_or_behind_a_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            with self.assertRaises(ValueError):
                inv.main(['--production', str(root), '--output', str(root / 'data/out')])
            link = Path(td) / 'link'
            os.symlink(root, link)
            with self.assertRaises(ValueError):
                inv.main(['--production', str(root), '--output',
                          str(link / 'data' / 'o')])
            launchd = Path.home() / 'Library/LaunchAgents/cartographer-inv-test'
            with self.assertRaises(ValueError):
                inv.main(['--production', str(root), '--output', str(launchd)])
            self.assertFalse(launchd.exists())

    def test_two_builds_of_the_same_inputs_agree(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            a = inv.build_investment_snapshot(root)
            b = inv.build_investment_snapshot(root)
            self.assertEqual(a['semantic_digest'], b['semantic_digest'])

    def test_a_completed_run_writes_one_file_with_tight_mode(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            out = Path(td) / 'out'
            inv.main(['--production', str(root), '--output', str(out)])
            self.assertEqual([p.name for p in out.iterdir()],
                             ['investment_snapshot.json'])
            self.assertEqual(oct((out / 'investment_snapshot.json').stat().st_mode)[-3:],
                             '600')
            inv.validate_investment_snapshot(
                json.loads((out / 'investment_snapshot.json').read_text()), 'written')


class TheSnapshotIsValidJsonForEveryone(unittest.TestCase):
    """Замер на живых данных: promotion_report.json содержит -Infinity.

    Python сериализует его дословно, и файл перестаёт быть валидным JSON — браузер такой
    снимок не читает, а раздел молча исчезает. Подменить на null нельзя: это стёрло бы
    факт. Значение переезжает текстом рядом с флагом.
    """

    def test_a_non_finite_metric_is_named_not_lost(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td, **{'promotion_report.json': {
                'generated_at': '2026-09-20T06:00:42+00:00',
                'decisions': [{'strategy_id': 'S9', 'action': 'demote',
                               'reason': 'bad', 'metrics': {'calmar_30d': float('-inf'),
                                                            'sharpe_30d': 0.1},
                               'ts': '2026-09-20T06:00:42+00:00'}]}})
            s = _build(td, production=root)
            o = [x for x in s['objects'] if x['strategy_id'] == 'S9'][0]
            by = {m['name']: m['value'] for m in o['performance_metrics']}
            self.assertEqual(by['sharpe_30d'], 0.1)
            self.assertIsInstance(by['calmar_30d'], dict)
            self.assertIs(by['calmar_30d']['non_finite'], True)
            self.assertIn('inf', by['calmar_30d']['as_text'])

    def test_the_written_file_parses_as_strict_json(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td, **{'promotion_report.json': {
                'generated_at': '2026-09-20T06:00:42+00:00',
                'decisions': [{'strategy_id': 'S9', 'action': 'demote', 'reason': 'x',
                               'metrics': {'calmar_30d': float('-inf')},
                               'ts': '2026-09-20T06:00:42+00:00'}]}})
            out = Path(td) / 'out'
            inv.main(['--production', str(root), '--output', str(out)])
            text = (out / 'investment_snapshot.json').read_text()
            self.assertNotIn('-Infinity', text)
            self.assertNotIn('NaN', text)
            # строгий разбор — тот же, что делает браузер
            json.loads(text, parse_constant=lambda c: (_ for _ in ()).throw(
                AssertionError(f'невалидный JSON: {c}')))


class StrategyIdentityIsMeasuredNotAssumed(unittest.TestCase):
    """Складывать записи трёх источников в «число стратегий» можно только доказав id."""

    def test_the_same_stable_id_in_two_sources_is_one_strategy(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            same = [o for o in s['objects'] if o['strategy_id'] == 'S0']
            self.assertEqual(len(same), 1)
            self.assertEqual(sorted(same[0]['sources']),
                             ['promotion_report.json', 'strategy_configs.json'])
            self.assertEqual(s['strategy_identity']['cross_source_exact_id_matches'], 1)

    def test_facts_from_both_sources_are_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            merged = [o for o in s['objects'] if o['strategy_id'] == 'S0'][0]
            self.assertEqual(sorted(merged['facts_by_source']),
                             ['promotion_report.json', 'strategy_configs.json'])
            self.assertEqual(
                merged['facts_by_source']['promotion_report.json']['promotion_status'],
                'PROMOTE')
            self.assertEqual(
                merged['facts_by_source']['strategy_configs.json']['lifecycle_state'],
                'DECLARED_CONFIG')
            self.assertTrue(merged['performance_metrics'],
                            'метрики движка не потеряны при слиянии')

    def test_conflicting_source_facts_stay_visible_without_a_winner(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            merged = [o for o in s['objects'] if o['strategy_id'] == 'S0'][0]
            fields = {c['field'] for c in merged['conflicting_facts']}
            self.assertIn('lifecycle_state', fields)
            for c in merged['conflicting_facts']:
                self.assertIn('победитель НЕ выбирается', c['note'])
                self.assertEqual(sorted(c['by_source']),
                                 ['promotion_report.json', 'strategy_configs.json'])
            self.assertIn('|', merged['lifecycle_state'])
            page = pr._investments(s, {'investment_snapshot.json'})
            self.assertIn('расхождение источников', page)

    def test_a_name_only_match_is_never_merged(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td, **{'strategy_lab_promotion.json': {
                'generated_at': '2026-06-25T19:57:47+00:00',
                'pipeline': 'RESEARCH -> BACKTEST -> PAPER',
                'stage_counts': {'PAPER_CANDIDATE': 1},
                # имя рукава совпадает с идентификатором конфигурации, id — нет
                'sleeves': [{'id': 'lab-1', 'sleeve': 'S0', 'stage': 'PAPER_CANDIDATE',
                             'beats_floor': True, 'criteria': {}}]}})
            s = _build(td, production=root)
            ids = [o['strategy_id'] for o in s['objects']]
            self.assertIn('S0', ids)
            self.assertIn('lab-1', ids)
            lab = [o for o in s['objects'] if o['strategy_id'] == 'lab-1'][0]
            self.assertEqual(lab['id_namespace'], 'sleeve_id')
            self.assertEqual(lab['sources'], ['strategy_lab_promotion.json'])
            self.assertGreaterEqual(s['strategy_identity']['name_only_matches'], 1)

    def test_different_namespaces_are_never_confused(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            spaces = {o['id_namespace'] for o in s['objects']}
            self.assertEqual(spaces, {'strategy_id', 'sleeve_id'})
            self.assertIn('РАЗНЫХ пространствах',
                          s['strategy_identity']['namespace_note'])

    def test_no_silent_authority_winner_between_sources(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertEqual(s['strategy_identity']['authority_between_sources'],
                             'AUTHORITY_UNDEFINED')
            self.assertIn('победителя не выбираем',
                          s['strategy_identity']['authority_note'])

    def test_the_page_says_records_not_unique_strategies(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            page = pr._investments(s, {'investment_snapshot.json'})
            self.assertIn('Записей о стратегиях', page)
            self.assertIn('Тождество стратегий — измерено', page)


class CapitalAndEquityAreNotTheSameWord(unittest.TestCase):
    def test_configured_capital_and_current_equity_are_separate_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            by = {m['metric_type']: m for m in s['capital_metrics']}
            self.assertEqual(by['CONFIGURED_CAPITAL']['value'], 100000.0)
            self.assertEqual(by['CONFIGURED_CAPITAL']['source'], 'capital_config.json')
            self.assertEqual(by['CURRENT_EQUITY']['value'], 101340.69)
            self.assertEqual(by['CURRENT_EQUITY']['source'], 'current_positions.json')
            self.assertNotEqual(by['CONFIGURED_CAPITAL']['source_field'],
                                by['CURRENT_EQUITY']['source_field'])

    def test_every_metric_names_its_mode_and_its_field(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            for m in s['capital_metrics']:
                self.assertEqual(m['mode'], 'PAPER')
                self.assertTrue(m['source_field'])
                self.assertIn(m['metric_type'], inv.METRIC_TYPES)

    def test_a_missing_currency_stays_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            by = {m['metric_type']: m for m in s['capital_metrics']}
            self.assertEqual(by['CONFIGURED_CAPITAL']['currency'], 'USDC')
            self.assertIsNone(by['CURRENT_EQUITY']['currency'])
            self.assertIn('НЕ измерена', by['CURRENT_EQUITY']['currency_basis'])
            self.assertIn('суффикс _usd', by['CURRENT_EQUITY']['currency_basis'])

    def test_position_value_is_not_summed_into_equity(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td, **{'current_positions.json': {
                'generated_at': '2026-09-20T06:00:00+00:00',
                'execution_mode': 'read_only_simulation',
                'current_equity_usd': 100.0, 'deployed_usd': 90.0, 'cash_usd': 10.0}})
            s = _build(td, production=root)
            by = {m['metric_type']: m['value'] for m in s['capital_metrics']}
            self.assertEqual(by['CURRENT_EQUITY'], 100.0)
            self.assertEqual(by['POSITION_VALUE'], 90.0)
            self.assertEqual(by['CASH'], 10.0)
            self.assertNotIn(190.0, by.values())
            self.assertNotIn(200.0, by.values())

    def test_a_paper_metric_never_becomes_real(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertTrue(all(m['mode'] != 'REAL' for m in s['capital_metrics']))
            broken = copy.deepcopy(s)
            broken['capital_metrics'][0]['mode'] = 'REAL'
            with self.assertRaises(inv.InvestmentInputError):
                inv.validate_investment_snapshot(broken, 'mutated')

    def test_the_page_labels_equity_as_equity(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            page = pr._investments(s, {'investment_snapshot.json'})
            self.assertIn('CURRENT_EQUITY', page)
            self.assertIn('CONFIGURED_CAPITAL', page)
            self.assertIn('складывать их нельзя', page)


class TheSourceFilterDoesNotDropMergedRecords(unittest.TestCase):
    """После слияния у записи два источника; фильтр обязан показывать оба.

    Первая редакция ставила в data-isource ПЕРВЫЙ источник, и срез по движку продвижения
    давал 6 записей вместо 16 — объединённые молча выпадали.
    """

    def test_a_merged_row_carries_both_sources_in_its_filter_key(self):
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            page = pr._investments(s, {'investment_snapshot.json'})
            merged = [o for o in s['objects'] if len(o['sources']) > 1][0]
            row = [r for r in _re.findall(r'<div class="row"[^>]*>', page)
                   if f'data-id="{merged["strategy_id"]}"' in r][0]
            key = _re.search(r'data-isource="([^"]*)"', row).group(1)
            for src in merged['sources']:
                self.assertIn(src, key)

    def test_the_facet_offers_the_same_combined_values(self):
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            page = pr._investments(s, {'investment_snapshot.json'})
            block = page[page.index('id="investments-scope"'):]
            block = block[:block.index('data-role="list"')]
            facet = _re.search(r'data-facet="isource"[^>]*>(.*?)</select>', block,
                               _re.S).group(1)
            options = set(_re.findall(r'<option value="([^"]*)"', facet)) - {''}
            keys = {', '.join(sorted(o['sources'])) for o in s['objects']}
            self.assertEqual(options, keys)
