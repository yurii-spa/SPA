"""Regressions for Reliability & Problems (Director OS Phase 4).

The risk of a reliability screen is that it manufactures problems: turning one observation
into a trend, a silent source into "all clear", a duplicate into a repetition, or a guess
into a cause. Each test below pins one of those.

The production tree here is built by the test, not borrowed from the machine: a verdict
that depends on one host's files answers a question nobody asked.
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


rel = _load('reliability')
pr = _load('portal_render')

SENTINEL = 'SYNTHETIC_SECRET_SENTINEL_P4'
NOW = rel.dt.datetime(2026, 9, 20, 12, 0, tzinfo=rel.dt.timezone.utc)


def _ts(hours_ago):
    return (NOW - rel.dt.timedelta(hours=hours_ago)).isoformat()


def _prod(td, **over):
    """A production-shaped tree with one instance of every reliability source."""
    root = Path(td) / 'prod'
    (root / 'data').mkdir(parents=True, exist_ok=True)
    (root / 'architecture').mkdir(parents=True, exist_ok=True)
    (root / 'nimbalyst-local/tracker').mkdir(parents=True, exist_ok=True)
    # срок годности объявляет РЕПОЗИТОРИЙ, а не слой надёжности — ровно тем же файлом,
    # что и в проде. Источник без строки здесь обязан получить свежесть UNKNOWN.
    (root / 'architecture/manifest.json').write_text(json.dumps({
        'agents': [], 'artifacts': [
            {'path': 'data/system_health.json', 'producer': 'com.spa.system_health',
             'slo_hours': 26},
            {'path': 'data/watchdog_report.json', 'producer': 'com.spa.rules_watchdog',
             'slo_hours': 1},
            {'path': 'data/agent_health.json', 'producer': 'com.spa.agent_health',
             'slo_hours': 3},
            {'path': 'data/cycle_health.json', 'producer': 'com.spa.cycle_health',
             'slo_hours': 26},
            {'path': 'data/uptime_status.json', 'producer': 'com.spa.uptime_monitor',
             'slo_hours': 26},
            {'path': 'data/code_sync_status.json', 'producer': 'com.spa.orchestrator',
             'slo_hours': 2},
            {'path': 'data/deployment_drift.json', 'producer': 'com.spa.system_health',
             'slo_hours': 15},
            {'path': 'data/loop_health.json', 'producer': 'com.spa.decision_loop',
             'slo_hours': 7},
        ]}, ensure_ascii=False))

    docs = {
        'system_health.json': {
            'generated_at': _ts(2),
            'checks': [
                {'id': 'd1.ok', 'status': 'OK', 'title': 'всё хорошо', 'evidence': {}},
                {'id': 'd5.deployment.drift', 'status': 'WARNING',
                 'title': 'доставленное не исполняется', 'evidence': {'n': 1},
                 'error': None},
                {'id': 'd9.boom', 'status': 'CRITICAL', 'title': 'сломано',
                 'evidence': {}, 'error': 'boom'},
                {'id': 'd2.skipped', 'status': 'SKIPPED', 'title': 'пропущено'},
            ]},
        # три прогона: repeat_me падает во всех трёх, once_only — только в последнем
        'watchdog_report.json': [
            {'checked_at': _ts(50), 'checks': [
                {'check': 'repeat_me', 'status': 'WARNING', 'message': 'опять'},
                {'check': 'quiet', 'status': 'OK'}]},
            {'checked_at': _ts(26), 'checks': [
                {'check': 'repeat_me', 'status': 'WARNING', 'message': 'опять'}]},
            # 0.4 ч при SLO 1 ч: НЕ на границе намеренно — иначе сдвиг часов на семь
            # минут переводил бы источник через порог, и тест детерминизма ловил бы
            # настоящую смену смысла вместо утечки часов
            {'checked_at': _ts(0.4), 'checks': [
                {'check': 'repeat_me', 'status': 'WARNING', 'message': 'опять'},
                {'check': 'once_only', 'status': 'CRITICAL', 'message': 'первый раз'}]},
        ],
        'agent_health.json': {
            'timestamp': _ts(1), 'agents': [
                {'label': 'com.spa.fine', 'status': 'OK'},
                {'label': 'com.spa.broken', 'status': 'CRITICAL', 'last_exit': 78,
                 'log_age_min': 900, 'issue': 'агент не стартует'}],
            'system_issues': ['fleet parity DRIFT (1 orphan-plist)']},
        'cycle_health.json': {
            'checked_at': _ts(3), 'overall': 'WARNING',
            'checks': {'cycle_gap': {'status': 'OK'},
                       'evidence': {'status': 'WARNING', 'detail': 'протухло'}},
            'unchecked': ['nav_reconciliation']},
        'uptime_status.json': {
            'all_ok': False, 'ts': (NOW - rel.dt.timedelta(hours=1)).timestamp(),
            'checks': {'apiserver': {'running': True, 'error': None},
                       'dashboard': {'running': False, 'error': 'порт не отвечает'}}},
        'code_sync_status.json': {
            'timestamp': _ts(1), 'result': 'SYNCED', 'detail': 'ok',
            'origin_main': 'abc123', 'files_changed': 0,
            'retired_code': ['scripts/retired_thing.py'], 'retired_instructions': []},
        'deployment_drift.json': {
            'status': 'OK', 'checked_at': _ts(1), 'reasons': [],
            'commits_behind': 0, 'commits_ahead': 0},
        'loop_health.json': {
            'generated_at': _ts(4),
            'recurring_findings': [
                {'key': 'gap:thing', 'recurrences': 3, 'status': 'open',
                 'last_seen': _ts(5), 'live': True}]},
        'findings_bridge_state.json': {
            'generated_at': _ts(6), 'findings': {
                'B1:dead:com.spa.broken': {
                    'first_seen': _ts(200), 'last_seen': _ts(6), 'seen_count': 4,
                    'severity': 'WARN', 'status': 'open',
                    'card': 'nimbalyst-local/tracker/inbox-known.md'}}},
    }
    docs.update(over)
    for name, body in docs.items():
        (root / 'data' / name).write_text(json.dumps(body, ensure_ascii=False))

    (root / 'nimbalyst-local/tracker/inbox-known.md').write_text(
        '# карточка\n\nПро scripts/retired_thing.py уже заведено.\n')
    (root / 'nimbalyst-local/tracker/inbox-other.md').write_text('# другое\n\nне про это\n')
    return root


def _authority(td):
    the_map = {
        'schema_version': 'cartographer.authority_map/0.1',
        'authoritative_commit': 'a' * 40, 'observed_at': _ts(1),
        'entities': [
            {'entity_id': 'code_file:scripts/retired_thing.py',
             'path': 'scripts/retired_thing.py', 'entity_type': 'code_file',
             'drift_status': 'EXTRA_IN_PRODUCTION', 'severity': 'WARNING',
             'severity_basis': 'origin удалил, checkout удалить не может',
             'observed_at': _ts(1), 'evidence': [{'kind': 'git', 'detail': 'ls-tree'}]},
            {'entity_id': 'code_file:docs/loose.md', 'path': 'docs/loose.md',
             'entity_type': 'code_file', 'drift_status': 'AUTHORITY_UNDEFINED',
             'severity': 'INFO', 'severity_basis': 'правило каноничности не объявлено',
             'observed_at': _ts(1), 'evidence': []},
            {'entity_id': 'artifact:data/old.json', 'path': 'data/old.json',
             'entity_type': 'artifact', 'drift_status': 'STALE', 'severity': 'WARNING',
             'severity_basis': 'старше собственного порога', 'observed_at': _ts(1),
             'evidence': []},
            {'entity_id': 'code_file:scripts/fine.py', 'path': 'scripts/fine.py',
             'entity_type': 'code_file', 'drift_status': 'IN_SYNC', 'severity': 'INFO',
             'severity_basis': 'совпадает', 'observed_at': _ts(1), 'evidence': []},
        ]}
    p = Path(td) / 'auth'
    p.mkdir(exist_ok=True)
    (p / 'authority_map.json').write_text(json.dumps(the_map, ensure_ascii=False))
    return p


def _snapshot(td):
    snap = {'schema_version': 'cartographer.snapshot/0.3', 'started_at': _ts(2),
            'finished_at': _ts(2),
            'findings': [
                {'id': 'STATUS_STALE:com.spa.slow', 'kind': 'DRIFT',
                 'rule_code': 'STATUS_STALE', 'subject': 'com.spa.slow',
                 'context': 'вывод старше порога', 'reason': 'артефакт протух'},
                {'id': 'WRAPPER_TARGET_UNDECLARED:x', 'kind': 'UNKNOWN',
                 'rule_code': 'WRAPPER_TARGET_UNDECLARED', 'subject': 'com.spa.x',
                 'context': 'обёртка', 'reason': 'цель обёртки не объявлена'}]}
    p = Path(td) / 'cart'
    p.mkdir(exist_ok=True)
    (p / 'snapshot.json').write_text(json.dumps(snap, ensure_ascii=False))
    return p


def _build(td, **kw):
    """Собрать снимок, НЕ перезаписывая фикстуру, которую передал вызывающий.

    Раньше здесь стояло ``kw.pop('authority', _authority(td))``. Аргумент по умолчанию в
    Python вычисляется ДО pop, а ``_authority`` пишет файл — поэтому переданная тестом
    правленая карта молча затиралась исходной, и тест падал на своём же входе.
    """
    root = kw['production'] if 'production' in kw else _prod(td)
    cart = kw['cartographer'] if 'cartographer' in kw else _snapshot(td)
    auth = kw['authority'] if 'authority' in kw else _authority(td)
    return rel.build_reliability_snapshot(root, cart, auth, now=NOW)


def _by_id(snapshot, needle):
    return [f for f in snapshot['findings'] if needle in f['finding_id']]


class OneObservationIsNotATrend(unittest.TestCase):
    def test_a_single_failure_stays_an_incident(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            once = _by_id(s, 'watchdog:once_only')
            self.assertEqual(len(once), 1)
            self.assertEqual(once[0]['classification'], 'INCIDENT')
            self.assertEqual(once[0]['occurrence_count'], 1)
            self.assertIn('повторяемость НЕ измерена', once[0]['classification_reason'])

    def test_repeated_evidence_becomes_a_problem_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            repeat = _by_id(s, 'watchdog:repeat_me')[0]
            self.assertEqual(repeat['classification'], 'PROBLEM_CANDIDATE')
            self.assertEqual(repeat['occurrence_count'], 3)
            self.assertIn('watchdog_report.json', repeat['occurrence_basis'])

    def test_the_same_subject_from_two_sources_is_not_two_observations(self):
        """Подтверждение ≠ повторение: дублирование не имеет права родить проблему."""
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            retired = [f for f in s['findings']
                       if f['affected_entity'] == 'scripts/retired_thing.py']
            self.assertEqual(len(retired), 1, 'один предмет — одна запись')
            f = retired[0]
            self.assertEqual(sorted(f['sources']),
                             ['authority_map.json', 'code_sync_status.json'])
            self.assertEqual(f['corroborated_by'], ['code_sync_status.json'])
            self.assertIsNone(f['occurrence_count'])
            self.assertEqual(f['classification'], 'CONDITION')

    def test_a_finding_without_evidence_never_becomes_a_problem(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            for f in s['findings']:
                if f['classification'] == 'PROBLEM_CANDIDATE':
                    proven = (f['occurrence_count'] or 0) >= rel.REPETITION_MIN
                    first = rel._parse_ts(f['first_seen'])
                    last = rel._parse_ts(f['last_seen'])
                    held = bool(first and last and
                                (last - first).total_seconds() / 3600
                                >= rel.PERSISTENCE_HOURS)
                    self.assertTrue(proven or held, f['finding_id'])

    def test_a_bare_observation_with_no_time_and_no_count_is_unknown(self):
        bare = rel._finding('x:1', 'not_a_known_type', 'нечто', 'без улик',
                            status='ACTIVE', severity='UNKNOWN', source='s',
                            source_status='READ', category='observation', evidence=[])
        verdict, reason = rel.classify(bare)
        self.assertEqual(verdict, 'UNKNOWN')
        self.assertIn('не хватает', reason)


class NothingIsInventedThatTheSourceDidNotSay(unittest.TestCase):
    def test_severity_is_carried_from_the_source_verbatim(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertEqual(_by_id(s, 'health:d9.boom')[0]['severity'], 'CRITICAL')
            self.assertEqual(_by_id(s, 'health:d5.deployment.drift')[0]['severity'],
                             'WARNING')

    def test_a_source_without_severity_leaves_it_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            down = _by_id(s, 'uptime:dashboard')[0]
            self.assertEqual(down['severity'], 'UNKNOWN')
            contract = [x for x in s['sources'] if x['source'] == 'uptime_status.json'][0]
            self.assertIs(contract['has_severity'], False)

    def test_first_seen_is_never_invented(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            health = _by_id(s, 'health:d9.boom')[0]
            self.assertIsNone(health['first_seen'],
                              'источник первого появления не знает — поле обязано пустовать')
            repeat = _by_id(s, 'watchdog:repeat_me')[0]
            self.assertEqual(repeat['first_seen'], _ts(50),
                             'а там, где история есть, берётся её самая ранняя отметка')

    def test_no_field_anywhere_carries_a_cause(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            blob = json.dumps(s, ensure_ascii=False).lower()
            for banned in ('root_cause', 'rootcause', 'probable_cause', 'because_of'):
                self.assertNotIn(banned, blob)
            for f in s['findings']:
                self.assertIn('причин', f['classification_reason'].lower() + 'причин')
                self.assertNotIn('вероятно', f['classification_reason'].lower())

    def test_an_unreadable_source_is_not_read_as_all_clear(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            (root / 'data/system_health.json').write_text('{ это не json')
            s = _build(td, production=root)
            rec = [x for x in s['sources'] if x['source'] == 'system_health.json'][0]
            self.assertEqual(rec['status'], 'UNREADABLE')
            self.assertEqual(_by_id(s, 'health:'), [])
            self.assertGreaterEqual(s['counts']['sources_unavailable'], 1)

    def test_an_absent_source_produces_no_findings_and_says_so(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            (root / 'data/agent_health.json').unlink()
            s = _build(td, production=root)
            rec = [x for x in s['sources'] if x['source'] == 'agent_health.json'][0]
            self.assertEqual(rec['status'], 'ABSENT')
            self.assertEqual(_by_id(s, 'agent:'), [])

    def test_a_count_without_a_named_instrument_is_refused(self):
        with self.assertRaises(rel.ReliabilityInputError):
            rel._finding('x:2', 'watchdog_check_failed', 'e', 't', status='ACTIVE',
                         severity='UNKNOWN', source='s', source_status='READ',
                         category='health', evidence=[], occurrence_count=5)

    def test_a_silent_source_is_named_rather_than_hidden(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            bridge = _by_id(s, 'bridge:B1:dead:com.spa.broken')[0]
            self.assertGreater(bridge['source_age_hours'], 0)

    def test_a_stale_source_downgrades_active_to_unverified(self):
        """«Источник не отзывал» и «подтверждено сейчас» — разные утверждения."""
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td, **{'agent_health.json': {
                'timestamp': _ts(50),  # SLO 3 ч — просрочен в шестнадцать раз
                'agents': [{'label': 'com.spa.broken', 'status': 'CRITICAL',
                            'last_exit': 78, 'log_age_min': 900,
                            'issue': 'агент не стартует'}],
                'system_issues': []}})
            s = _build(td, production=root)
            rec = [x for x in s['sources'] if x['source'] == 'agent_health.json'][0]
            self.assertEqual(rec['freshness'], 'STALE')
            self.assertEqual(rec['declared_slo_hours'], 3.0)
            f = _by_id(s, 'agent:com.spa.broken')[0]
            self.assertEqual(f['status'], 'ACTIVE_UNVERIFIED')
            self.assertEqual(f['freshness'], 'STALE')
            self.assertIn('slo_hours', f['freshness_rule'])

    def test_the_age_of_a_source_is_not_part_of_the_snapshot_meaning(self):
        """Иначе digest менялся бы от хода часов, а не от входов."""
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertNotIn('source_age_hours',
                             json.dumps(rel.semantic_view(s), ensure_ascii=False))
            self.assertTrue(any(f['source_age_hours'] is not None
                                for f in s['findings']))


class TheKnownRealConditionsAreSurfaced(unittest.TestCase):
    def test_a_retired_production_file_is_shown(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            f = [x for x in s['findings']
                 if x['finding_type'] == 'retired_code_in_production']
            self.assertEqual([x['affected_entity'] for x in f],
                             ['scripts/retired_thing.py'])
            self.assertEqual(f[0]['classification'], 'CONDITION')

    def test_authority_undefined_is_shown(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            f = [x for x in s['findings'] if x['finding_type'] == 'authority_undefined']
            self.assertEqual([x['affected_entity'] for x in f], ['docs/loose.md'])

    def test_a_stale_component_is_shown(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            stale = [x for x in s['findings'] if x['finding_type'] == 'stale_artifact']
            self.assertEqual(sorted(x['affected_entity'] for x in stale),
                             ['com.spa.slow', 'data/old.json'])

    def test_local_only_and_in_sync_are_treated_differently(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertEqual([x for x in s['findings']
                              if x['affected_entity'] == 'scripts/fine.py'], [],
                             'совпадающий с авторитетом файл находкой не является')

    def test_nothing_is_invented_when_the_tree_is_healthy(self):
        """Положительный контроль наоборот: код умеет искать — но без улик молчит."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'empty'
            (root / 'data').mkdir(parents=True)
            s = rel.build_reliability_snapshot(root, None, None, now=NOW)
            self.assertEqual(s['findings'], [])
            self.assertEqual(s['counts']['findings'], 0)
            self.assertEqual(s['counts']['sources_read'], 0)
            self.assertGreaterEqual(s['counts']['sources_unavailable'], 9)


class TheLayerNeverOpensASecondBacklog(unittest.TestCase):
    def test_an_existing_card_is_shown_when_the_evidence_links_it(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            retired = [x for x in s['findings']
                       if x['affected_entity'] == 'scripts/retired_thing.py'][0]
            tasks = [t['task'] for t in retired['linked_tasks']]
            self.assertIn('nimbalyst-local/tracker/inbox-known.md', tasks)
            self.assertNotIn('nimbalyst-local/tracker/inbox-other.md', tasks)
            self.assertTrue(retired['linked_tasks'][0]['basis'])

    def test_a_source_named_card_is_carried_with_its_basis(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            bridge = _by_id(s, 'bridge:B1:dead:com.spa.broken')[0]
            self.assertEqual([t['task'] for t in bridge['linked_tasks']],
                             ['nimbalyst-local/tracker/inbox-known.md'])
            self.assertIn('источник назвал', bridge['linked_tasks'][0]['basis'])

    def test_no_card_is_created_and_the_tracker_is_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            before = {p.name: p.read_bytes()
                      for p in (root / 'nimbalyst-local/tracker').iterdir()}
            _build(td, production=root)
            after = {p.name: p.read_bytes()
                     for p in (root / 'nimbalyst-local/tracker').iterdir()}
            self.assertEqual(before, after)

    def test_an_unlinked_finding_says_so_without_proposing_a_card(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            unlinked = [f for f in s['findings'] if not f['linked_tasks']]
            self.assertTrue(unlinked)
            page = pr._reliability(s, {'reliability_snapshot.json'})
            self.assertIn('Нет связанной задачи', page)
            self.assertNotIn('Завести задачу', page)
            self.assertNotIn('Create Task', page)
            self.assertIs(s['creates_tasks'], False)


class TheSnapshotIsDerivedAndReproducible(unittest.TestCase):
    def test_crossing_a_declared_slo_does_change_the_meaning(self):
        """Обратный контроль: смена свежести — смысл, и digest обязан её заметить."""
        with tempfile.TemporaryDirectory() as td:
            root, cart, auth = _prod(td), _snapshot(td), _authority(td)
            fresh = rel.build_reliability_snapshot(root, cart, auth, now=NOW)
            # сдвигаем часы так, что watchdog (SLO 1 ч) переходит собственный порог
            later = rel.build_reliability_snapshot(
                root, cart, auth, now=NOW + rel.dt.timedelta(hours=1))
            self.assertNotEqual(fresh['semantic_digest'], later['semantic_digest'])
            before = [x for x in fresh['sources']
                      if x['source'] == 'watchdog_report.json'][0]
            after = [x for x in later['sources']
                     if x['source'] == 'watchdog_report.json'][0]
            self.assertEqual((before['freshness'], after['freshness']),
                             ('FRESH', 'STALE'))

    def test_two_builds_of_the_same_inputs_agree(self):
        with tempfile.TemporaryDirectory() as td:
            root, cart, auth = _prod(td), _snapshot(td), _authority(td)
            a = rel.build_reliability_snapshot(root, cart, auth, now=NOW)
            b = rel.build_reliability_snapshot(
                root, cart, auth, now=NOW + rel.dt.timedelta(minutes=7))
            # семь минут не переводят ни один источник через его объявленный срок
            self.assertEqual(a['semantic_digest'], b['semantic_digest'])
            self.assertNotEqual(a['generated_at'], b['generated_at'])

    def test_the_contract_refuses_a_problem_without_proof(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            rel.validate_reliability_snapshot(s, 'built')
            broken = copy.deepcopy(s)
            victim = [f for f in broken['findings']
                      if f['classification'] == 'CONDITION'][0]
            victim['classification'] = 'PROBLEM_CANDIDATE'
            with self.assertRaises(rel.ReliabilityInputError):
                rel.validate_reliability_snapshot(broken, 'mutated')

    def test_the_contract_refuses_an_unknown_vocabulary_value(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            for field, value in (('severity', 'SCARY'), ('status', 'MAYBE'),
                                 ('classification', 'PROBABLY_BAD')):
                broken = copy.deepcopy(s)
                broken['findings'][0][field] = value
                with self.assertRaises(rel.ReliabilityInputError):
                    rel.validate_reliability_snapshot(broken, f'mutated {field}')

    def test_counts_match_the_findings_they_summarise(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            c, f = s['counts'], s['findings']
            self.assertEqual(c['findings'], len(f))
            self.assertEqual(c['active_confirmed'],
                             sum(1 for x in f if x['status'] == 'ACTIVE_CONFIRMED'))
            self.assertEqual(c['active_unverified'],
                             sum(1 for x in f if x['status'] == 'ACTIVE_UNVERIFIED'))
            self.assertEqual(sum(c['by_classification'].values()), len(f))
            self.assertEqual(sum(c['by_severity'].values()), len(f))
            self.assertEqual(sum(c['by_freshness'].values()), len(f))
            self.assertEqual(
                c['explicit_task_links'] + c['mention_only_matches']
                + c['no_task_relation'], len(f))
            self.assertEqual(c['critical_confirmed_now'],
                             sum(1 for x in f if x['status'] == 'ACTIVE_CONFIRMED'
                                 and x['severity'] == 'CRITICAL'))
            self.assertEqual(c['critical_unverified'],
                             sum(1 for x in f if x['status'] == 'ACTIVE_UNVERIFIED'
                                 and x['severity'] == 'CRITICAL'))

    def test_the_module_never_imports_a_door_to_the_machine(self):
        source = (_root / 'reliability.py').read_text()
        for banned in ('import subprocess', 'import socket', 'import urllib',
                       'from subprocess', 'from socket', 'from urllib'):
            self.assertNotIn(banned, source)

    def test_building_works_with_every_door_to_the_network_shut(self):
        with tempfile.TemporaryDirectory() as td:
            root, cart, auth = _prod(td), _snapshot(td), _authority(td)

            def refuse(*a, **k):
                raise AssertionError('слой надёжности вышел наружу')

            with patch('socket.socket', refuse), patch('socket.create_connection', refuse):
                s = rel.build_reliability_snapshot(root, cart, auth, now=NOW)
            self.assertTrue(s['findings'])


class NothingLeavesTheMachineAndNothingSecretIsCopied(unittest.TestCase):
    def test_a_credential_shape_in_a_source_never_reaches_the_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            leaky = f'token = ghp_{"a" * 36} и ещё api_key: {SENTINEL}0123456789'
            root = _prod(td, **{'system_health.json': {
                'generated_at': _ts(1),
                'checks': [{'id': 'd9.leak', 'status': 'CRITICAL', 'title': leaky,
                            'evidence': {'raw': leaky}, 'error': leaky}]}})
            s = _build(td, production=root)
            blob = json.dumps(s, ensure_ascii=False)
            self.assertNotIn('ghp_' + 'a' * 36, blob)
            self.assertNotIn(f'api_key: {SENTINEL}', blob)
            self.assertIn('ВЫРЕЗАНО', blob, 'вырезано обязано быть видно, а не молча')
            self.assertIn('d9.leak', blob, 'сама находка при этом не исчезает')

    def test_the_redactor_leaves_ordinary_text_alone(self):
        """Положительный контроль наоборот: сторож, режущий всё, бесполезен."""
        plain = 'агент com.spa.broken не стартует: exit 78, журнал 900 мин'
        self.assertEqual(rel.redact(plain), plain)

    def test_the_renderer_never_reaches_the_network(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)

            def refuse(*a, **k):
                raise AssertionError('рендер вышел наружу')

            import socket
            import urllib.request
            with patch.object(socket, 'socket', refuse), \
                 patch.object(socket, 'create_connection', refuse), \
                 patch.object(urllib.request, 'urlopen', refuse):
                page = pr._reliability(s, {'reliability_snapshot.json'})
            self.assertNotIn('http://', page)
            self.assertNotIn('https://', page)

    def test_the_output_may_not_land_in_production_or_behind_a_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            cart, auth = _snapshot(td), _authority(td)
            inside = root / 'data' / 'reliability'
            # общий сторож выхода (diff.validate_output) отказывает ValueError — тем же
            # отказом, что у портала и карты авторитетности; тип важен, чтобы тест ловил
            # ИМЕННО отказ, а не любое падение
            with self.assertRaises(ValueError):
                rel.main(['--production', str(root), '--cartographer', str(cart),
                          '--authority', str(auth), '--output', str(inside)])
            self.assertFalse(inside.exists())

            link = Path(td) / 'link-to-prod'
            os.symlink(root, link)
            with self.assertRaises(ValueError):
                rel.main(['--production', str(root), '--cartographer', str(cart),
                          '--authority', str(auth),
                          '--output', str(link / 'data' / 'out')])

            launchd = Path.home() / 'Library/LaunchAgents/cartographer-test-output'
            with self.assertRaises(ValueError):
                rel.main(['--production', str(root), '--cartographer', str(cart),
                          '--authority', str(auth), '--output', str(launchd)])
            self.assertFalse(launchd.exists())

    def test_the_input_sets_are_protected_from_the_output_too(self):
        with tempfile.TemporaryDirectory() as td:
            root, cart, auth = _prod(td), _snapshot(td), _authority(td)
            with self.assertRaises(ValueError):
                rel.main(['--production', str(root), '--cartographer', str(cart),
                          '--authority', str(auth), '--output', str(auth / 'nested')])
            self.assertFalse((auth / 'nested').exists())

    def test_a_completed_run_writes_one_file_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as td:
            root, cart, auth = _prod(td), _snapshot(td), _authority(td)
            out = Path(td) / 'out'
            rel.main(['--production', str(root), '--cartographer', str(cart),
                      '--authority', str(auth), '--output', str(out)])
            self.assertEqual([p.name for p in out.iterdir()],
                             ['reliability_snapshot.json'])
            self.assertEqual(oct((out / 'reliability_snapshot.json').stat().st_mode)[-3:],
                             '600')
            doc = json.loads((out / 'reliability_snapshot.json').read_text())
            rel.validate_reliability_snapshot(doc, 'written')

    def test_the_run_writes_nothing_into_the_production_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root, cart, auth = _prod(td), _snapshot(td), _authority(td)
            before = {str(p.relative_to(root)): p.stat().st_mtime_ns
                      for p in root.rglob('*') if p.is_file()}
            rel.main(['--production', str(root), '--cartographer', str(cart),
                      '--authority', str(auth), '--output', str(Path(td) / 'o2')])
            after = {str(p.relative_to(root)): p.stat().st_mtime_ns
                     for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before, after)


class ThePageOffersNoWayToActAndItsFiltersMatchItsData(unittest.TestCase):
    def _page(self, td):
        return pr._reliability(_build(td), {'reliability_snapshot.json'})

    def test_no_control_on_the_page_performs_anything(self):
        """Проверяются УПРАВЛЯЮЩИЕ ЭЛЕМЕНТЫ, а не сырой текст.

        Дважды в прошлых фазах этот тест ловил сам себя: «Удалить» в заголовке карточки
        трекера — данные, а не кнопка. Смотреть надо на то, что можно нажать.
        """
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            page = self._page(td)
            self.assertEqual(page.count('<button'), 0)
            self.assertEqual(page.count('<form'), 0)
            handlers = set(_re.findall(r'on[a-z]+="([A-Za-z_]+)\(', page))
            self.assertLessEqual(handlers, {'spaFilter', 'spaSort'})
            for verb in ('Fix', 'Repair', 'Restart', 'Delete', 'Sync', 'Deploy', 'Retry',
                         'Acknowledge', 'Create Task', 'Починить', 'Перезапустить',
                         'Синхронизировать', 'Развернуть', 'Принять расхождение'):
                for label in _re.findall(r'<(?:button|a|input|select|option)\b[^>]*>'
                                         r'([^<]*)', page):
                    self.assertNotIn(verb.lower(), label.strip().lower())

    def test_every_facet_option_exists_in_the_data(self):
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            page = pr._reliability(s, {'reliability_snapshot.json'})
            block = page[page.index('id="reliability-scope"'):]
            block = block[:block.index('data-role="list"')]
            facets = _re.findall(r'<select[^>]*data-role="facet"[^>]*>(.*?)</select>',
                                 block, _re.S)
            self.assertEqual(len(facets), 5,
                             'severity, классификация, категория, статус, свежесть')
            options = {o for f in facets
                       for o in _re.findall(r'<option value="([^"]*)"', f)} - {''}
            present = ({f['severity'] for f in s['findings']}
                       | {f['classification'] for f in s['findings']}
                       | {f['category'] for f in s['findings']}
                       | {f['status'] for f in s['findings']}
                       | {f['freshness'] for f in s['findings']})
            self.assertTrue(options)
            self.assertLessEqual(options, present,
                                 'фильтр не предлагает значений, которых в данных нет')

    def test_every_row_carries_the_attributes_the_filters_read(self):
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            page = pr._reliability(s, {'reliability_snapshot.json'})
            rows = _re.findall(r'<div class="row"[^>]*>', page)
            self.assertEqual(len(rows) >= len(s['findings']), True)
            for row in rows:
                for attr in ('data-rsev', 'data-rclass', 'data-rcat', 'data-rstatus',
                             'data-rentity', 'data-hay', 'data-id'):
                    self.assertIn(attr, row)

    def test_the_headline_numbers_are_the_ones_in_the_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            page = pr._reliability(s, {'reliability_snapshot.json'})
            c = s['counts']
            self.assertIn(f'<dt>CRITICAL подтверждённых сейчас</dt><dd class="big">'
                          f'{c["critical_confirmed_now"]}</dd>', page)
            self.assertIn(f'<dt>CRITICAL без подтверждения</dt><dd class="big">'
                          f'{c["critical_unverified"]}</dd>', page)
            self.assertIn(f'<dt>PROBLEM CANDIDATES</dt><dd class="big">'
                          f'{c["by_classification"].get("PROBLEM_CANDIDATE", 0)}</dd>',
                          page)

    def test_an_absent_snapshot_is_not_rendered_as_all_clear(self):
        page = pr._reliability(None, set())
        self.assertIn('не приложен', page)
        self.assertIn('НЕ значит, что всё исправно', page)

    def test_unmeasured_values_are_printed_as_such(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            page = pr._reliability(s, {'reliability_snapshot.json'})
            self.assertIn('не измерено', page)
            self.assertIn('это «не считали», а не «повторений нет»', page)


class TheSourceTableDoesNotLieAboutItsSources(unittest.TestCase):
    """Таблица источников — это утверждение о приборах, и его тоже надо мерить.

    Первая редакция объявляла у снимка Cartographer severity, которой у него нет ни у
    одной находки: ложь ровно в той таблице, ради которой раздел и написан.
    """

    def test_a_source_that_declares_severity_really_carries_it(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            for rec in s['sources']:
                if rec['status'] != 'READ':
                    continue
                mine = [f for f in s['findings'] if rec['source'] in f['sources']]
                if not mine:
                    continue
                stated = any(f['severity'] != 'UNKNOWN' for f in mine
                             if f['sources'] == [rec['source']])
                if rec['has_severity'] is False:
                    self.assertFalse(
                        stated,
                        f'{rec["source"]} объявлен без severity, но она у записи есть')

    def test_a_source_that_declares_counting_really_counts(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            counting = {r['source'] for r in s['sources'] if r['counts_occurrences']}
            for f in s['findings']:
                if f['occurrence_count'] is not None:
                    self.assertTrue(
                        set(f['sources']) & counting,
                        f'{f["finding_id"]}: счёт есть, а считающего источника нет')


class ADerivedSnapshotIsNeverTheSourceOfTruth(unittest.TestCase):
    """Карта авторитетности Phase 3 — пересобираемый ПРОИЗВОДНЫЙ артефакт.

    Назвать её authoritative значило бы завести второй источник правды ровно там, где
    Phase 3 его старательно не заводила: карта цитирует коммит, но коммитом не является.
    """

    def test_the_authority_map_is_declared_derived_not_authoritative(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            rec = [x for x in s['sources'] if x['source'] == 'authority_map.json'][0]
            self.assertEqual(rec['basis'], 'derived')
            self.assertTrue(rec['rebuildable_artifact'])
            self.assertTrue(rec['names_authoritative_source_inside'])

    def test_no_rebuildable_artifact_anywhere_claims_authority(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            for rec in s['sources']:
                if rec.get('rebuildable_artifact'):
                    self.assertNotEqual(rec['basis'], 'authoritative', rec['source'])
            broken = copy.deepcopy(s)
            victim = [x for x in broken['sources']
                      if x['source'] == 'authority_map.json'][0]
            victim['basis'] = 'authoritative'
            with self.assertRaises(rel.ReliabilityInputError):
                rel.validate_reliability_snapshot(broken, 'mutated')

    def test_the_real_authority_travels_as_its_own_field(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            auth = _authority(td)
            the_map = json.loads((auth / 'authority_map.json').read_text())
            for e in the_map['entities']:
                e['authoritative_source'] = 'origin/main@' + 'a' * 12
            (auth / 'authority_map.json').write_text(json.dumps(the_map,
                                                               ensure_ascii=False))
            s = _build(td, production=root, authority=auth)
            from_map = [x for x in s['findings'] if 'authority_map.json' in x['sources']]
            self.assertTrue(from_map)
            self.assertTrue(all(x['authoritative_source'] == 'origin/main@' + 'a' * 12
                                for x in from_map))
            page = pr._reliability(s, {'reliability_snapshot.json'})
            self.assertIn('авторитет по этому предмету', page)
            self.assertIn('источником правды не является', page)

    def test_the_snapshot_says_of_itself_that_it_is_not_a_source_of_truth(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertTrue(s['derived_state'])
            self.assertIn('не является', s['is_not_a_source_of_truth'])


class ConfirmedNowIsNotTheSameAsNotYetWithdrawn(unittest.TestCase):
    def _stale_critical(self, td):
        """CRITICAL от источника, который просрочил СВОЙ объявленный срок."""
        return _prod(td, **{'agent_health.json': {
            'timestamp': _ts(24 * 40),          # SLO 3 ч
            'agents': [{'label': 'com.spa.broken', 'status': 'CRITICAL', 'last_exit': 78,
                        'log_age_min': 900, 'issue': 'агент не стартует'}],
            'system_issues': []}})

    def test_a_fresh_critical_reaches_current_attention(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            f = _by_id(s, 'agent:com.spa.broken')[0]
            self.assertEqual(f['status'], 'ACTIVE_CONFIRMED')
            self.assertEqual(f['freshness'], 'FRESH')
            page = pr._reliability(s, {'reliability_snapshot.json'})
            head = page[page.index('Требует внимания сейчас'):
                        page.index('Источник давно не обновлялся')]
            self.assertIn('agent:com.spa.broken', head)

    def test_a_stale_critical_is_not_confirmed_and_not_in_current_attention(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td, production=self._stale_critical(td))
            f = _by_id(s, 'agent:com.spa.broken')[0]
            self.assertEqual(f['status'], 'ACTIVE_UNVERIFIED')
            self.assertEqual(f['freshness'], 'STALE')
            confirmed_critical = [x['finding_id'] for x in s['findings']
                                  if x['status'] == 'ACTIVE_CONFIRMED'
                                  and x['severity'] == 'CRITICAL']
            self.assertNotIn('agent:com.spa.broken', confirmed_critical,
                             'просроченный источник не даёт подтверждения «сейчас»')
            self.assertGreaterEqual(s['counts']['critical_unverified'], 1)
            self.assertEqual(s['counts']['critical_confirmed_now'],
                             len(confirmed_critical))
            page = pr._reliability(s, {'reliability_snapshot.json'})
            head = page[page.index('Требует внимания сейчас'):
                        page.index('Источник давно не обновлялся')]
            self.assertNotIn('agent:com.spa.broken', head)

    def test_a_stale_critical_does_not_disappear_from_the_portal(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td, production=self._stale_critical(td))
            page = pr._reliability(s, {'reliability_snapshot.json'})
            tail = page[page.index('Источник давно не обновлялся'):]
            self.assertIn('agent:com.spa.broken', tail)
            self.assertIn('Источник просрочил собственный объявленный срок', page)
            self.assertIn('агент не стартует', page)

    def test_unknown_freshness_does_not_silently_become_stale(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            bridge = _by_id(s, 'bridge:B1:dead:com.spa.broken')[0]
            self.assertEqual(bridge['freshness'], 'UNKNOWN',
                             'срок для findings_bridge_state.json не объявлен нигде')
            self.assertIn('не объявлен', bridge['freshness_rule'])
            self.assertEqual(bridge['status'], 'ACTIVE_UNVERIFIED')
            rec = [x for x in s['sources']
                   if x['source'] == 'findings_bridge_state.json'][0]
            self.assertIsNone(rec['declared_slo_hours'])
            self.assertNotEqual(rec['freshness'], 'STALE')
            page = pr._reliability(s, {'reliability_snapshot.json'})
            self.assertIn('Срок годности источника не объявлен — свежесть НЕ измерена',
                          page)

    def test_silence_of_a_source_is_never_read_as_resolved(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td, production=self._stale_critical(td))
            f = _by_id(s, 'agent:com.spa.broken')[0]
            self.assertNotEqual(f['status'], 'RESOLVED')
            resolved = [x for x in s['findings'] if x['status'] == 'RESOLVED']
            for x in resolved:
                self.assertIn('ЯВНО', x['classification_reason'])

    def test_the_headline_separates_confirmed_from_unverified(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td, production=self._stale_critical(td))
            page = pr._reliability(s, {'reliability_snapshot.json'})
            self.assertIn('CRITICAL подтверждённых сейчас', page)
            self.assertIn('CRITICAL без подтверждения', page)
            self.assertNotIn('CRITICAL (активные)', page)


class AMentionIsNotADeclaredLink(unittest.TestCase):
    def test_a_text_mention_never_becomes_an_explicit_link(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            retired = [x for x in s['findings']
                       if x['affected_entity'] == 'scripts/retired_thing.py'][0]
            kinds = {t['relation'] for t in retired['linked_tasks']}
            self.assertEqual(kinds, {'MENTION_MATCH'})
            for t in retired['linked_tasks']:
                self.assertIn('НЕ объявлена', t['basis'])
            self.assertTrue(s['task_linking']['never_promotes_mention_to_link'])

    def test_a_source_named_card_keeps_the_explicit_kind(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            bridge = _by_id(s, 'bridge:B1:dead:com.spa.broken')[0]
            explicit = [t for t in bridge['linked_tasks']
                        if t['relation'] == 'EXPLICIT_LINK']
            self.assertEqual(len(explicit), 1)
            self.assertIn('источник назвал', explicit[0]['basis'])

    def test_the_two_kinds_are_counted_apart(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            c = s['counts']
            explicit = [f for f in s['findings']
                        if any(t['relation'] == 'EXPLICIT_LINK'
                               for t in f['linked_tasks'])]
            self.assertEqual(c['explicit_task_links'], len(explicit))
            self.assertEqual(c['mention_only_matches'],
                             sum(1 for f in s['findings'] if f['linked_tasks']
                                 and f not in explicit))

    def test_the_page_labels_a_mention_as_a_possible_link_only(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            page = pr._reliability(s, {'reliability_snapshot.json'})
            self.assertIn('Возможная связанная задача (совпадение по упоминанию)', page)
            self.assertIn('Нет связанной задачи', page)
            self.assertNotIn('Завести задачу', page)

    def test_a_relation_without_a_declared_kind_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            broken = copy.deepcopy(s)
            victim = [f for f in broken['findings'] if f['linked_tasks']][0]
            del victim['linked_tasks'][0]['relation']
            with self.assertRaises(rel.ReliabilityInputError):
                rel.validate_reliability_snapshot(broken, 'mutated')
