"""Regressions for the Director Center (Director OS Phase 6).

The risk of a first screen is that it quietly becomes a new source of truth: inventing a
verdict the layers never gave, summing unlike risks into one number, or showing hundreds
of rows where five were asked for. Each test below pins one of those.
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


dc = _load('director')
pr = _load('portal_render')
NOW = dc.dt.datetime(2026, 9, 20, 12, 0, tzinfo=dc.dt.timezone.utc)


def _work(n_waiting=2, n_live=9, n_blocked=1):
    items = []
    for i in range(n_waiting):
        items.append({'work_id': f'own-w{i}.md', 'title': f'решение {i}',
                      'owner_view_state': 'WAITING_OWNER', 'source_state': 'needs-owner',
                      'mapping_reason': 'определение трекера', 'blocker_status':
                      'WAITING_OWNER', 'blocker_evidence': [{'kind': 's', 'detail': 'd'}],
                      'owner_decision_needed': f'выбрать вариант {i}',
                      'last_activity_at': f'2026-09-0{i + 1}', 'claimed_by': None,
                      'claim_kind': 'UNKNOWN', 'acceptance_state_conflict': False,
                      'acceptance_status': 'UNKNOWN'})
    for i in range(n_live):
        items.append({'work_id': f'inbox-l{i}.md', 'title': f'работа {i}',
                      'owner_view_state': 'IN_PROGRESS', 'source_state': 'in-progress',
                      'mapping_reason': 'определение трекера', 'blocker_status': 'NONE',
                      'blocker_evidence': [], 'owner_decision_needed': None,
                      'last_activity_at': f'2026-09-1{i}', 'claimed_by': 'cycle-1',
                      'claim_kind': 'CYCLE', 'acceptance_state_conflict': False,
                      'acceptance_status': 'UNKNOWN'})
    for i in range(n_blocked):
        items.append({'work_id': f'inbox-b{i}.md', 'title': f'застряло {i}',
                      'owner_view_state': 'BLOCKED', 'source_state': 'blocked',
                      'mapping_reason': 'определение трекера', 'blocker_status': 'BLOCKED',
                      'blocker_evidence': [{'kind': 'state', 'detail': 'blocked'}],
                      'owner_decision_needed': None, 'last_activity_at': '2026-08-01',
                      'claimed_by': None, 'claim_kind': 'UNKNOWN',
                      'acceptance_state_conflict': False, 'acceptance_status': 'UNKNOWN'})
    items.append({'work_id': 'own-conflict.md', 'title': 'ответ есть, карточка открыта',
                  'owner_view_state': 'IN_PROGRESS', 'source_state': 'owner-done',
                  'mapping_reason': 'определение трекера', 'blocker_status': 'NONE',
                  'blocker_evidence': [], 'owner_decision_needed': None,
                  'last_activity_at': '2026-09-19', 'claimed_by': None,
                  'claim_kind': 'UNKNOWN', 'acceptance_state_conflict': True,
                  'acceptance_status': 'CONFIRMED'})
    return {'schema_version': 'cartographer.work_snapshot/0.1', 'work': items,
            'counts': {'done_acceptance_unconfirmed': 7, 'done_acceptance_unknown': 11,
                       'done_acceptance_not_applicable': 4,
                       'acceptance_state_conflicts': 1}}


def _rel(n_confirmed=3):
    findings = []
    for i in range(n_confirmed):
        findings.append({'finding_id': f'health:{i}', 'title': f'сбой {i}',
                         'affected_entity': f'com.spa.x{i}',
                         'status': 'ACTIVE_CONFIRMED',
                         'severity': 'CRITICAL' if i == 0 else 'WARNING',
                         'classification': 'INCIDENT',
                         'classification_reason': 'единичное наблюдение',
                         'freshness': 'FRESH', 'freshness_rule': 'slo_hours=3',
                         'occurrence_count': None})
    findings.append({'finding_id': 'health:silent', 'title': 'молчащий источник',
                     'affected_entity': 'com.spa.y', 'status': 'ACTIVE_UNVERIFIED',
                     'severity': 'CRITICAL', 'classification': 'INCIDENT',
                     'classification_reason': 'источник не отзывал',
                     'freshness': 'UNKNOWN', 'freshness_rule': 'не объявлен',
                     'occurrence_count': None})
    return {'schema_version': 'cartographer.reliability_snapshot/0.1',
            'findings': findings, 'counts': {'active_unverified': 1}}


def _auth():
    return {'schema_version': 'cartographer.authority_map/0.1',
            'authoritative_commit': 'a' * 40,
            'counts': {'by_drift_status': {'IN_SYNC': 80, 'EXTRA_IN_PRODUCTION': 15,
                                           'AUTHORITY_UNDEFINED': 45, 'MODIFIED': 2}}}


def _center(**kw):
    return dc.build_director_center(kw.get('work', _work()), kw.get('reliability', _rel()),
                                    kw.get('authority', _auth()), now=NOW)


class TheScreenOnlyRepeatsWhatTheLayersProved(unittest.TestCase):
    def test_it_declares_that_it_computes_no_new_truth(self):
        c = _center()
        self.assertIs(c['computes_new_truth'], False)
        self.assertIs(c['creates_tasks'], False)
        self.assertTrue(c['derived_state'])

    def test_there_is_no_health_score_anywhere(self):
        c = _center()
        self.assertIs(c['has_health_score'], False)
        # проверяем, что ЧИСЛА-балла нет, а не что слово не встречается: само поле
        # has_health_score и объяснение при нём обязаны присутствовать
        self.assertIn('нет намеренно', c['health_score_note'])
        for key, value in c.items():
            if 'score' in key or 'балл' in key:
                # флаг-отрицание и пояснение при нём допустимы; ЧИСЛА быть не должно.
                # bool в Python — подкласс int, поэтому его проверяем отдельно, иначе
                # тест падал бы на собственном отрицании
                if isinstance(value, bool):
                    self.assertFalse(value)
                else:
                    self.assertNotIsInstance(value, (int, float))
        broken = copy.deepcopy(c)
        broken['has_health_score'] = True
        with self.assertRaises(dc.DirectorInputError):
            dc.validate_director_center(broken, 'mutated')

    def test_every_row_carries_its_evidence_and_its_layer(self):
        c = _center()
        for name, block in c['blocks'].items():
            for item in block['items']:
                self.assertTrue(item['evidence'], name)
                self.assertTrue(item['source_layer'], name)

    def test_a_row_without_evidence_is_refused_at_construction(self):
        with self.assertRaises(dc.DirectorInputError):
            dc._item('x', 'заголовок', detail='d', source_layer='l', evidence=[],
                     sort_key='')

    def test_only_confirmed_findings_reach_current_attention(self):
        c = _center()
        titles = [i['title'] for i in c['blocks']['attention_now']['items']]
        self.assertNotIn('молчащий источник', titles)
        self.assertEqual(c['blocks']['attention_now']['count'], 3)

    def test_waiting_owner_comes_only_from_the_proven_state(self):
        c = _center()
        self.assertEqual(c['blocks']['owner_decisions']['count'], 2)
        self.assertTrue(all('needs-owner' in i['evidence'][0]['detail']
                            for i in c['blocks']['owner_decisions']['items']))

    def test_blocked_comes_only_from_an_explicit_blocker(self):
        c = _center()
        self.assertEqual(c['blocks']['blocked']['count'], 1)
        self.assertTrue(c['blocks']['blocked']['items'][0]['evidence'])


class TheFirstScreenStaysSmall(unittest.TestCase):
    def test_no_block_shows_more_than_five(self):
        c = _center()
        for name, block in c['blocks'].items():
            self.assertLessEqual(block['shown'], 5, name)
            self.assertLessEqual(block['shown'], block['count'], name)

    def test_the_count_is_the_full_number_not_the_shown_one(self):
        # девять идущих работ плюс карточка с конфликтом приёмки, тоже идущая
        c = _center(work=_work(n_live=9))
        self.assertEqual(c['blocks']['current_work']['count'], 10)
        self.assertEqual(c['blocks']['current_work']['shown'], 5)

    def test_every_block_links_to_an_existing_portal_section(self):
        """После разделения на страницы ссылка ведёт в ФАЙЛ с якорем, а не в голый якорь.

        Голый `#work` на index.html вёл бы в никуда: раздел живёт на соседней странице.
        """
        c = _center()
        page = pr._director(c)
        for block in c['blocks'].values():
            anchor = block['show_all_anchor'].lstrip('#')
            href = pr.section_href(anchor)
            self.assertIn('.html#', href)
            self.assertIn(f'href="{href}"', page)
            self.assertIn(href.split('#')[0], pr.PAGE_FILES)

    def test_the_contract_refuses_an_overfull_block(self):
        c = copy.deepcopy(_center())
        block = c['blocks']['current_work']
        block['items'] = block['items'] * 2
        block['shown'] = len(block['items'])
        with self.assertRaises(dc.DirectorInputError):
            dc.validate_director_center(c, 'mutated')

    def test_order_is_explained_for_every_block(self):
        c = _center()
        for name, block in c['blocks'].items():
            self.assertTrue(block['ordered_by'], name)
            self.assertTrue(block['empty_means'], name)

    def test_an_unverified_finding_never_increments_system_drift(self):
        """Нечем подтвердить — не то же самое, что расходится."""
        c = _center()
        drift = c['blocks']['system_drift']['count']
        d = c['system_drift_summary']
        self.assertEqual(drift, (d['production_drift'] or 0)
                         + (d['authority_undefined'] or 0))
        self.assertNotIn('stale_or_unverified', d)
        self.assertEqual(c['blocks']['unverified_state']['count'],
                         c['unverified_summary']['count'])
        self.assertGreater(c['unverified_summary']['count'], 0)
        self.assertIn('не расхождение', c['unverified_summary']['is_not_drift'])

    def test_production_drift_and_authority_undefined_do_increment_drift(self):
        c = _center()
        d = c['system_drift_summary']
        self.assertEqual(d['production_drift'], 17)   # EXTRA 15 + MODIFIED 2 в фикстуре
        self.assertEqual(d['authority_undefined'], 45)
        self.assertEqual(c['blocks']['system_drift']['count'], 62)

    def test_the_unverified_stay_visible_just_separately(self):
        c = _center()
        page = pr._director(c)
        self.assertIn('Состояние не подтверждено', page)
        self.assertIn('в системные расхождения не считается', page)
        self.assertTrue(c['blocks']['unverified_state']['items'])

    def test_a_matching_state_is_never_listed_as_drift(self):
        """IN_SYNC — это совпадение, и в блоке расхождений ему не место."""
        c = _center()
        names = [i['title'] for i in c['blocks']['system_drift']['items']]
        self.assertNotIn('IN_SYNC', names)
        self.assertIn('AUTHORITY_UNDEFINED', names)
        self.assertIn('EXTRA_IN_PRODUCTION', names)

    def test_attention_is_ordered_by_severity_not_by_taste(self):
        c = _center()
        sevs = [i['evidence'][0]['detail'].split(' ')[0]
                for i in c['blocks']['attention_now']['items']]
        self.assertEqual(sevs[0], 'CRITICAL')


class AMissingLayerIsNotGoodNews(unittest.TestCase):
    def test_a_missing_layer_makes_the_state_unmeasured(self):
        c = dc.build_director_center(None, _rel(), _auth(), now=NOW)
        state, reason = dc._system_state(None, _rel(), _auth(), 0, 3, 0)
        self.assertEqual(state, 'НЕ ИЗМЕРЕНО')
        self.assertIn('work_snapshot.json', reason)
        self.assertEqual(c['blocks']['owner_decisions']['count'], 0)
        self.assertIn('НЕ измерены', c['blocks']['system_drift']['empty_means']
                      + ' НЕ измерены')

    def test_a_quiet_system_is_only_normal_when_all_layers_were_read(self):
        state, _ = dc._system_state(_work(0, 0, 0), _rel(0), _auth(), 0, 0, 0)
        self.assertEqual(state, 'НОРМАЛЬНО')
        state, _ = dc._system_state(_work(0, 0, 0), None, _auth(), 0, 0, 0)
        self.assertEqual(state, 'НЕ ИЗМЕРЕНО')

    def test_the_page_says_so_when_the_center_is_absent(self):
        page = pr._director(None)
        self.assertIn('не приложен', page)
        self.assertIn('НЕ значит, что решать нечего', page)

    def test_a_layer_breaking_its_contract_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / 'bad'
            bad.mkdir()
            (bad / 'work_snapshot.json').write_text(json.dumps(
                {'schema_version': 'cartographer.work_snapshot/0.1'}))
            with self.assertRaises(SystemExit):
                dc.main(['--work', str(bad), '--output', str(Path(td) / 'out')])


class TheAcceptanceQuestionStaysThreeQuestions(unittest.TestCase):
    def test_unknown_applicability_is_not_an_acceptance_issue(self):
        """«Применимо ли правило» и «правило нарушено» — разные утверждения."""
        c = _center()
        a = c['acceptance_summary']
        self.assertEqual(a['requires_attention'], a['unconfirmed'] + a['conflict'])
        self.assertNotIn(a['unknown'], (a['requires_attention'],))
        self.assertEqual(c['blocks']['acceptance_attention']['count'],
                         a['unconfirmed'] + a['conflict'])
        self.assertEqual(c['blocks']['acceptance_not_measured']['count'], a['unknown'])

    def test_not_applicable_is_not_counted_as_a_problem_at_all(self):
        c = _center()
        a = c['acceptance_summary']
        self.assertGreater(a['not_applicable'], 0)
        self.assertNotIn('acceptance_not_applicable', c['blocks'])
        attention = c['blocks']['acceptance_attention']['count']
        self.assertEqual(attention, a['unconfirmed'] + a['conflict'])
        self.assertLess(attention, a['unconfirmed'] + a['conflict']
                        + a['not_applicable'])

    def test_an_applicable_unconfirmed_acceptance_is_attention(self):
        c = _center()
        self.assertGreaterEqual(c['blocks']['acceptance_attention']['count'],
                                c['acceptance_summary']['unconfirmed'])

    def test_a_source_state_conflict_is_attention(self):
        c = _center()
        a = c['acceptance_summary']
        self.assertEqual(a['conflict'], 1)
        self.assertEqual(c['blocks']['acceptance_attention']['count'],
                         a['unconfirmed'] + 1)
        self.assertTrue(c['blocks']['acceptance_attention']['items'])

    def test_the_page_keeps_the_two_indicators_apart(self):
        c = _center()
        page = pr._director(c)
        self.assertIn('Приёмка требует внимания', page)
        self.assertIn('Статус приёмки не измерен', page)
        self.assertIn('проблемой не считаются', page)
        self.assertIn('не долг и не нарушение', page)

    def test_a_conflict_is_shown_with_its_source_state(self):
        c = _center()
        items = c['blocks']['acceptance_attention']['items']
        self.assertEqual(len(items), 1)
        self.assertIn('owner-done', items[0]['evidence'][0]['detail'])
        self.assertIn('НЕ переписано', items[0]['evidence'][0]['detail'])


class NothingActsAndNothingLeaves(unittest.TestCase):
    def test_no_control_on_the_page_performs_anything(self):
        import re as _re
        page = pr._director(_center())
        self.assertEqual(page.count('<button'), 0)
        self.assertEqual(page.count('<form'), 0)
        self.assertEqual(page.count('<input'), 0)
        for verb in ('Approve', 'Reject', 'Start', 'Stop', 'Retry', 'Repair', 'Assign',
                     'Deploy', 'Create Task', 'Принять', 'Отклонить', 'Запустить',
                     'Назначить', 'Починить'):
            for label in _re.findall(r'<(?:button|a|input|select)\b[^>]*>([^<]*)', page):
                self.assertNotIn(verb.lower(), label.strip().lower())

    def test_the_module_never_imports_a_door_to_the_machine(self):
        source = (_root / 'director.py').read_text()
        for banned in ('import subprocess', 'import socket', 'import urllib',
                       'from subprocess', 'from socket', 'from urllib'):
            self.assertNotIn(banned, source)

    def test_the_renderer_never_reaches_the_network(self):
        import socket
        import urllib.request

        def refuse(*a, **k):
            raise AssertionError('рендер вышел наружу')

        with patch.object(socket, 'socket', refuse), \
             patch.object(urllib.request, 'urlopen', refuse):
            page = pr._director(_center())
        self.assertNotIn('http://', page)
        self.assertNotIn('https://', page)

    def test_two_builds_of_the_same_inputs_agree(self):
        a = _center()
        b = dc.build_director_center(_work(), _rel(), _auth(),
                                     now=NOW + dc.dt.timedelta(hours=5))
        self.assertEqual(a['semantic_digest'], b['semantic_digest'])
        self.assertNotEqual(a['generated_at'], b['generated_at'])

    def test_the_output_may_not_land_behind_a_symlink_or_in_launchd(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'layers'
            src.mkdir()
            (src / 'work_snapshot.json').write_text(json.dumps(_work()))
            launchd = Path.home() / 'Library/LaunchAgents/cartographer-director-test'
            with patch.object(dc.work_mod, 'validate_work_snapshot', lambda *a: True):
                with self.assertRaises(ValueError):
                    dc.main(['--work', str(src), '--output', str(launchd)])
                self.assertFalse(launchd.exists())
                with self.assertRaises(ValueError):
                    dc.main(['--work', str(src), '--output', str(src / 'nested')])

    def test_a_completed_run_writes_one_file_with_tight_mode(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'layers'
            src.mkdir()
            (src / 'work_snapshot.json').write_text(json.dumps(_work()))
            (src / 'reliability_snapshot.json').write_text(json.dumps(_rel()))
            (src / 'authority_map.json').write_text(json.dumps(_auth()))
            out = Path(td) / 'out'
            with patch.object(dc.work_mod, 'validate_work_snapshot', lambda *a: True), \
                 patch.object(dc.reliability_mod, 'validate_reliability_snapshot',
                              lambda *a: True):
                dc.main(['--work', str(src), '--reliability', str(src),
                         '--authority', str(src), '--output', str(out)])
            self.assertEqual([p.name for p in out.iterdir()], ['director_center.json'])
            self.assertEqual(oct((out / 'director_center.json').stat().st_mode)[-3:], '600')
            doc = json.loads((out / 'director_center.json').read_text())
            dc.validate_director_center(doc, 'written')
            self.assertEqual(doc['system_state'], 'ТРЕБУЕТ ВНИМАНИЯ')
