"""Regressions for the Development / Work view (Director OS Phase 5).

The risk of a work screen is that it invents a workflow, an executor or an acceptance:
calling a cycle number an agent, calling a closed card accepted, calling a quiet card
blocked, or replacing the tracker's own vocabulary with a prettier one. Each test below
pins one of those.

The production tree here is built by the test. A verdict that depends on one host's cards
answers a question nobody asked.
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


wk = _load('work')
pr = _load('portal_render')

SENTINEL = 'SYNTHETIC_SECRET_SENTINEL_P5'
NOW = wk.dt.datetime(2026, 9, 20, 12, 0, tzinfo=wk.dt.timezone.utc)

_TRACKER_YAML = """type: {kind}
idPrefix: {prefix}
fields:
  - name: title
    type: string
  - name: status
    type: select
    options:
{options}
"""


def _options(pairs):
    out = []
    for value, label, category in pairs:
        out.append(f'      - value: {value}\n        label: {label}\n'
                   f'        category: {category}')
    return '\n'.join(out)


def _card(path, fields, body='## тело\nтекст\n'):
    head = '\n'.join(f'{k}: {v}' for k, v in fields.items())
    path.write_text(f'---\n{head}\n---\n{body}', encoding='utf-8')


def _prod(td, cards=None, kanban=None, sessions=None, baseline=None):
    root = Path(td) / 'prod'
    (root / '.nimbalyst/trackers').mkdir(parents=True, exist_ok=True)
    (root / 'nimbalyst-local/tracker').mkdir(parents=True, exist_ok=True)
    (root / 'data').mkdir(parents=True, exist_ok=True)
    (root / 'scripts').mkdir(parents=True, exist_ok=True)

    (root / '.nimbalyst/trackers/inbox.yaml').write_text(_TRACKER_YAML.format(
        kind='inbox', prefix='inbox', options=_options([
            ('new', 'New', 'unstarted'), ('backlog', 'Backlog', 'unstarted'),
            ('in-progress', 'In Progress', 'started'), ('blocked', 'Blocked', 'started'),
            ('done', 'Done', 'done'), ('ingested', 'Ingested', 'done')])))
    (root / '.nimbalyst/trackers/owner-decision.yaml').write_text(_TRACKER_YAML.format(
        kind='owner-decision', prefix='own', options=_options([
            ('needs-owner', 'Needs Owner', 'unstarted'),
            ('owner-accepted', 'Owner Accepted', 'started'),
            ('owner-done', 'Owner Done', 'started'),
            ('ingested', 'Ingested', 'done'), ('done', 'Done', 'done')])))
    (root / '.nimbalyst/trackers/agent-task.yaml').write_text(_TRACKER_YAML.format(
        kind='agent-task', prefix='agent', options=_options([
            ('backlog', 'Backlog', 'unstarted'),
            ('in-progress', 'In Progress', 'started'),
            ('done', 'Done', 'done')])))

    t = root / 'nimbalyst-local/tracker'
    default = {
        'inbox-running.md': {'title': 'идёт работа', 'status': 'in-progress',
                             'created': '2026-09-01', 'claimed_by': 'cycle-663',
                             'claimed_at': '2026-09-01T10:00:00Z'},
        'inbox-blocked.md': {'title': 'застряло', 'status': 'blocked',
                             'created': '2026-08-01'},
        'inbox-closed-no-probe.md': {'title': 'закрыто без пробы', 'status': 'done',
                                     'created': '2026-08-02', 'resolved': '2026-08-20'},
        'inbox-closed-with-probe.md': {'title': 'закрыто с объявленной пробой',
                                       'status': 'done', 'created': '2026-08-03',
                                       'acceptance_probe': 'tier_promotion_loop_closed'},
        'inbox-session-claim.md': {'title': 'занято сессией', 'status': 'in-progress',
                                   'created': '2026-09-02',
                                   'claimed_by': 'interactive-session-2026-08-27'},
        'inbox-pid-claim.md': {'title': 'занято номером процесса', 'status': 'in-progress',
                               'created': '2026-09-03', 'claimed_by': 'pid94637'},
        'inbox-agent-claim.md': {'title': 'занято настоящим агентом',
                                 'status': 'in-progress', 'created': '2026-09-04',
                                 'claimed_by': 'com.spa.known_agent'},
        'inbox-ghost-agent.md': {'title': 'ярлык, которого нет', 'status': 'in-progress',
                                 'created': '2026-09-05',
                                 'claimed_by': 'com.spa.never_observed'},
        'inbox-strange-state.md': {'title': 'состояние вне словаря', 'status': 'выдумано',
                                   'created': '2026-09-06'},
        'own-waiting.md': {'title': 'ждёт владельца', 'status': 'needs-owner',
                           'created': '2026-08-10', 'blocks': 'go-live'},
        'own-answered.md': {'title': 'владелец ответил', 'status': 'ingested',
                            'created': '2026-08-11', 'owner_choice': 'B',
                            'owner_answered_at': '2026-08-12T09:00:00Z',
                            'owner_answer_via': 'telegram'},
        'own-closed-silent.md': {'title': 'закрыто без ответа', 'status': 'ingested',
                                 'created': '2026-08-13'},
        'agent-task-done.md': {'title': 'задача агента закрыта', 'status': 'done',
                               'created': '2026-08-14'},
        'inbox-with-finding.md': {'title': 'работа по находке', 'status': 'in-progress',
                                  'created': '2026-09-07',
                                  'finding_key': 'B7:manifest_parity:com.spa.hy_cycle'},
    }
    for name, fields in (cards if cards is not None else default).items():
        body = ('## Что от тебя нужно\nвыбрать вариант B или C\n'
                if fields.get('status') == 'needs-owner' else '## тело\nтекст\n')
        _card(t / name, fields, body)
    (t / '_BOARD.md').write_text('# индекс\nпроизводный\n')

    (root / 'KANBAN.json').write_text(json.dumps(kanban if kanban is not None else {
        'last_updated': '2026-06-22T08:25:00+00:00',
        'columns': {'features': [{'id': 'MP-404', 'title': 'фича', 'status': None}],
                    'backlog': [{'id': 'MP-900', 'title': 'в бэклоге', 'status': 'backlog'}]},
        'done': [{'id': 'MP-404', 'title': 'фича', 'status': 'done',
                  'completed': '2026-06-01', 'files': ['spa_core/x.py']},
                 {'id': 'MP-500', 'title': 'сделано', 'status': 'done',
                  'completed': '2026-06-02', 'tags': ['ADR-055']}]}, ensure_ascii=False))

    rows = sessions if sessions is not None else [
        {'ts': '2026-09-10T10:00:00Z', 'session': 'cycle-663',
         'summary': 'работа', 'files': ['spa_core/a.py', 'scripts/b.py'],
         'card': 'nimbalyst-local/tracker/inbox-running.md', 'card_state': 'in-progress'}]
    (root / 'data/session_changes.jsonl').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n')

    (root / 'scripts/inbox_acceptance_baseline.json').write_text(json.dumps(
        baseline if baseline is not None else {
            '_comment': 'карточки без критерия', '_measured': '2026-09-13',
            '_rule': '.claude/rules/acceptance.md',
            'files': ['inbox-closed-no-probe.md']}, ensure_ascii=False))
    return root


def _snapshot(td, labels=('com.spa.known_agent',)):
    p = Path(td) / 'cart'
    p.mkdir(exist_ok=True)
    (p / 'snapshot.json').write_text(json.dumps({
        'schema_version': 'cartographer.snapshot/0.3',
        'entities': [{'label': lbl} for lbl in labels]}, ensure_ascii=False))
    return p


def _reliability(td, links=None):
    rel = _load('reliability')
    root = Path(td) / 'relprod'
    (root / 'data').mkdir(parents=True, exist_ok=True)
    snap = rel.build_reliability_snapshot(root, None, None, now=NOW)
    snap['findings'] = links if links is not None else [{
        'finding_id': 'bridge:B7:manifest_parity:com.spa.hy_cycle',
        'finding_type': 'loop_finding', 'affected_entity': 'com.spa.hy_cycle',
        'title': 'повтор', 'status': 'ACTIVE_UNVERIFIED', 'severity': 'WARNING',
        'first_seen': None, 'last_seen': None, 'source': 'findings_bridge_state.json',
        'source_status': 'READ', 'evidence': [], 'category': 'loop',
        'occurrence_count': None, 'occurrence_basis': None,
        'classification': 'CONDITION', 'classification_reason': 'проверено',
        'observed_at': None, 'as_of': None, 'source_age_hours': None,
        'sources': ['findings_bridge_state.json'], 'corroborated_by': [],
        'merged_ids': [], 'freshness': 'UNKNOWN', 'freshness_rule': 'не объявлен',
        'authoritative_source': None,
        'linked_tasks': [
            {'task': 'nimbalyst-local/tracker/inbox-with-finding.md',
             'relation': 'EXPLICIT_LINK', 'basis': 'источник назвал карточку',
             'source': 'findings_bridge_state.json'},
            {'task': 'nimbalyst-local/tracker/inbox-running.md',
             'relation': 'MENTION_MATCH', 'basis': 'совпадение по упоминанию',
             'source': 'nimbalyst-local/tracker'}]}]
    snap['counts']['findings'] = len(snap['findings'])
    p = Path(td) / 'relset'
    p.mkdir(exist_ok=True)
    (p / 'reliability_snapshot.json').write_text(json.dumps(snap, ensure_ascii=False))
    return p


def _build(td, **kw):
    root = kw['production'] if 'production' in kw else _prod(td)
    rel = kw['reliability'] if 'reliability' in kw else _reliability(td)
    cart = kw['cartographer'] if 'cartographer' in kw else _snapshot(td)
    return wk.build_work_snapshot(root, rel, cart, now=NOW)


def _by(snapshot, work_id):
    return [w for w in snapshot['work'] if w['work_id'] == work_id][0]


class AClaimIsNotAnExecutor(unittest.TestCase):
    def test_a_cycle_number_never_becomes_an_agent(self):
        with tempfile.TemporaryDirectory() as td:
            w = _by(_build(td), 'inbox-running.md')
            self.assertEqual(w['claim_kind'], 'CYCLE')
            self.assertIn('НЕ агент', w['claim_reason'])

    def test_a_session_id_never_becomes_an_agent(self):
        with tempfile.TemporaryDirectory() as td:
            w = _by(_build(td), 'inbox-session-claim.md')
            self.assertEqual(w['claim_kind'], 'SESSION')

    def test_a_pid_never_becomes_an_agent(self):
        with tempfile.TemporaryDirectory() as td:
            w = _by(_build(td), 'inbox-pid-claim.md')
            self.assertEqual(w['claim_kind'], 'PID')
            self.assertIn('переиспользует', w['claim_reason'])

    def test_an_observed_label_is_the_only_thing_called_an_agent(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            real = _by(s, 'inbox-agent-claim.md')
            self.assertEqual(real['claim_kind'], 'AGENT_LABEL')
            self.assertIn('подтвержд', real['claim_reason'])
            ghost = _by(s, 'inbox-ghost-agent.md')
            self.assertEqual(ghost['claim_kind'], 'UNVERIFIED_LABEL')
            self.assertIn('агентом не называем', ghost['claim_reason'])

    def test_without_the_machine_observation_no_claim_is_an_agent(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td, cartographer=None)
            self.assertEqual(_by(s, 'inbox-agent-claim.md')['claim_kind'],
                             'UNVERIFIED_LABEL')
            self.assertEqual(s['counts']['claim_is_a_verified_agent'], 0)

    def test_the_contract_refuses_an_agent_without_confirming_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            broken = copy.deepcopy(_build(td))
            victim = _by(broken, 'inbox-session-claim.md')
            victim['claim_kind'] = 'AGENT_LABEL'
            victim['claim_reason'] = 'потому что похоже'
            with self.assertRaises(wk.WorkInputError):
                wk.validate_work_snapshot(broken, 'mutated')


class CompletionIsNotAcceptance(unittest.TestCase):
    def test_a_closed_card_without_evidence_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            w = _by(_build(td), 'inbox-closed-no-probe.md')
            self.assertEqual(w['source_state'], 'done')
            self.assertEqual(w['acceptance_status'], 'NOT_CONFIRMED')
            self.assertEqual(w['owner_view_state'], 'DONE_ACCEPTANCE_UNCONFIRMED')
            self.assertEqual(w['acceptance_applicability'], 'APPLICABLE')
            self.assertIsNone(w['accepted_at'])

    def test_a_declared_probe_is_not_a_passed_probe(self):
        with tempfile.TemporaryDirectory() as td:
            w = _by(_build(td), 'inbox-closed-with-probe.md')
            self.assertEqual(w['acceptance_status'], 'NOT_CONFIRMED')
            self.assertTrue(any('ВЕРДИКТ' in e['detail']
                                for e in w['acceptance_evidence']))

    def test_an_owner_answer_is_the_acceptance_of_a_decision(self):
        with tempfile.TemporaryDirectory() as td:
            w = _by(_build(td), 'own-answered.md')
            self.assertEqual(w['acceptance_status'], 'CONFIRMED')
            self.assertEqual(w['owner_view_state'], 'ACCEPTED')
            self.assertEqual(w['accepted_at'], '2026-08-12T09:00:00Z')

    def test_a_closed_decision_without_an_answer_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            w = _by(_build(td), 'own-closed-silent.md')
            self.assertEqual(w['acceptance_status'], 'NOT_CONFIRMED')
            self.assertEqual(w['owner_view_state'], 'DONE_ACCEPTANCE_UNCONFIRMED')

    def test_the_rule_that_excludes_agent_cards_is_quoted_not_guessed(self):
        with tempfile.TemporaryDirectory() as td:
            w = _by(_build(td), 'agent-task-done.md')
            self.assertEqual(w['acceptance_status'], 'NOT_APPLICABLE')
            self.assertEqual(w['acceptance_applicability'], 'NOT_APPLICABLE')
            self.assertEqual(w['owner_view_state'], 'DONE_ACCEPTANCE_NOT_APPLICABLE')
            self.assertTrue(any('acceptance.md' in (e.get('where') or '')
                                for e in w['acceptance_evidence']))

    def test_the_contract_refuses_accepted_without_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            broken = copy.deepcopy(_build(td))
            victim = _by(broken, 'inbox-closed-no-probe.md')
            victim['owner_view_state'] = 'ACCEPTED'
            with self.assertRaises(wk.WorkInputError):
                wk.validate_work_snapshot(broken, 'mutated')

    def test_the_page_never_prints_accepted_for_an_unconfirmed_card(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            page = pr._work_view(s, {'work_snapshot.json'})
            self.assertIn('Завершено, приёмка НЕ подтверждена', page)
            self.assertIn('Завершено, статус приёмки не измерен', page)
            self.assertIn('Завершено, отдельная приёмка не требуется', page)


class TheTrackersOwnVocabularyIsKept(unittest.TestCase):
    def test_the_lifecycle_comes_from_the_definitions_not_from_us(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertIn('in-progress', s['lifecycle_vocabulary'])
            self.assertIn('needs-owner', s['lifecycle_vocabulary'])
            self.assertTrue(s['lifecycle_vocabulary_source'])
            self.assertTrue(all('.nimbalyst/trackers' in p
                                for p in s['lifecycle_vocabulary_source']))

    def test_the_source_state_is_kept_beside_the_owner_group(self):
        with tempfile.TemporaryDirectory() as td:
            for work_id, source_state, view in (
                    ('inbox-running.md', 'in-progress', 'IN_PROGRESS'),
                    ('inbox-blocked.md', 'blocked', 'BLOCKED'),
                    ('own-waiting.md', 'needs-owner', 'WAITING_OWNER')):
                w = _by(_build(td), work_id)
                self.assertEqual(w['source_state'], source_state)
                self.assertEqual(w['lifecycle_state'], source_state)
                self.assertEqual(w['owner_view_state'], view)

    def test_every_mapping_names_its_reason(self):
        with tempfile.TemporaryDirectory() as td:
            for w in _build(td)['work']:
                self.assertTrue(w['mapping_reason'])

    def test_a_state_outside_the_vocabulary_stays_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            w = _by(_build(td), 'inbox-strange-state.md')
            self.assertEqual(w['owner_view_state'], 'UNKNOWN')
            self.assertEqual(w['source_state'], 'выдумано')
            self.assertIn('победителя не выбираем', w['mapping_reason'])

    def test_a_registry_that_names_two_states_for_one_id_is_not_resolved(self):
        with tempfile.TemporaryDirectory() as td:
            w = _by(_build(td), 'kanban:MP-404')
            self.assertEqual(w['owner_view_state'], 'UNKNOWN')
            self.assertIn('победителя не выбираем', w['mapping_reason'])
            self.assertTrue(any(e['kind'] == 'duplicate_id'
                                for e in w['lifecycle_evidence']))


class BlockersAndOwnerDecisionsNeedEvidence(unittest.TestCase):
    def test_a_blocker_is_only_what_the_state_says(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertEqual(_by(s, 'inbox-blocked.md')['blocker_status'], 'BLOCKED')
            quiet = _by(s, 'inbox-closed-no-probe.md')
            self.assertEqual(quiet['blocker_status'], 'NONE')
            self.assertEqual(quiet['blocker_evidence'], [])

    def test_a_long_quiet_card_is_not_called_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td, cards={'inbox-old.md': {
                'title': 'давно не трогали', 'status': 'in-progress',
                'created': '2026-01-01'}})
            s = _build(td, production=root)
            w = _by(s, 'inbox-old.md')
            self.assertEqual(w['blocker_status'], 'NONE')
            self.assertEqual(w['owner_view_state'], 'IN_PROGRESS')

    def test_waiting_owner_comes_from_the_state_not_from_the_text(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td, cards={
                'own-waiting.md': {'title': 'ждёт', 'status': 'needs-owner',
                                   'created': '2026-08-10'},
                'inbox-says-waiting.md': {'title': 'в тексте написано «жду владельца»',
                                          'status': 'in-progress', 'created': '2026-08-10'}})
            s = _build(td, production=root)
            self.assertEqual(_by(s, 'own-waiting.md')['owner_view_state'], 'WAITING_OWNER')
            self.assertEqual(_by(s, 'inbox-says-waiting.md')['owner_view_state'],
                             'IN_PROGRESS')
            self.assertEqual(s['counts']['waiting_owner'], 1)

    def test_the_owner_question_is_quoted_from_the_card(self):
        with tempfile.TemporaryDirectory() as td:
            w = _by(_build(td), 'own-waiting.md')
            self.assertIn('выбрать вариант B или C', w['owner_decision_needed'])

    def test_the_contract_refuses_a_blocker_without_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            broken = copy.deepcopy(_build(td))
            victim = _by(broken, 'inbox-running.md')
            victim['blocker_status'] = 'BLOCKED'
            victim['blocker_evidence'] = []
            with self.assertRaises(wk.WorkInputError):
                wk.validate_work_snapshot(broken, 'mutated')


class AFindingIsNotATask(unittest.TestCase):
    def test_a_declared_link_is_shown_as_a_link(self):
        with tempfile.TemporaryDirectory() as td:
            w = _by(_build(td), 'inbox-with-finding.md')
            kinds = {r['relation'] for r in w['related_findings']}
            self.assertIn('EXPLICIT_LINK', kinds)

    def test_a_mention_is_not_promoted_to_a_link(self):
        with tempfile.TemporaryDirectory() as td:
            w = _by(_build(td), 'inbox-running.md')
            self.assertEqual({r['relation'] for r in w['related_findings']},
                             {'MENTION_MATCH'})
            page = pr._work_view(_build(td), {'work_snapshot.json'})
            self.assertIn('Возможная связь (совпадение по упоминанию)', page)

    def test_a_finding_never_becomes_a_work_item(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertTrue(all(w['source'] in ('nimbalyst-local/tracker/*.md',
                                                'KANBAN.json')
                                for w in s['work']))
            self.assertIs(s['creates_tasks'], False)


class NothingIsWrittenAndNothingIsInvented(unittest.TestCase):
    def test_no_card_is_created_or_modified(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            t = root / 'nimbalyst-local/tracker'
            before = {p.name: p.read_bytes() for p in t.iterdir()}
            _build(td, production=root)
            after = {p.name: p.read_bytes() for p in t.iterdir()}
            self.assertEqual(before, after)

    def test_kanban_is_not_written(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            before = (root / 'KANBAN.json').read_bytes()
            _build(td, production=root)
            self.assertEqual((root / 'KANBAN.json').read_bytes(), before)

    def test_a_credential_shape_never_reaches_the_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            leak = f'ghp_{"b" * 36}'
            root = _prod(td, cards={'inbox-leak.md': {
                'title': f'токен {leak} в заголовке', 'status': 'in-progress',
                'created': '2026-09-01'}})
            s = _build(td, production=root)
            blob = json.dumps(s, ensure_ascii=False)
            self.assertNotIn(leak, blob)
            self.assertIn('ВЫРЕЗАНО', blob)

    def test_the_module_never_imports_a_door_to_the_machine(self):
        source = (_root / 'work.py').read_text()
        for banned in ('import subprocess', 'import socket', 'import urllib',
                       'from subprocess', 'from socket', 'from urllib'):
            self.assertNotIn(banned, source)

    def test_the_renderer_never_reaches_the_network(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)

            def refuse(*a, **k):
                raise AssertionError('рендер вышел наружу')

            import socket
            import urllib.request
            with patch.object(socket, 'socket', refuse), \
                 patch.object(urllib.request, 'urlopen', refuse):
                page = pr._work_view(s, {'work_snapshot.json'})
            self.assertNotIn('http://', page)
            self.assertNotIn('https://', page)

    def test_the_output_may_not_land_in_production_or_behind_a_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            with self.assertRaises(ValueError):
                wk.main(['--production', str(root), '--output',
                         str(root / 'data' / 'work')])
            link = Path(td) / 'link'
            os.symlink(root, link)
            with self.assertRaises(ValueError):
                wk.main(['--production', str(root), '--output', str(link / 'data' / 'o')])
            launchd = Path.home() / 'Library/LaunchAgents/cartographer-work-test'
            with self.assertRaises(ValueError):
                wk.main(['--production', str(root), '--output', str(launchd)])
            self.assertFalse(launchd.exists())

    def test_a_completed_run_writes_one_file_with_tight_mode(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            out = Path(td) / 'out'
            wk.main(['--production', str(root), '--output', str(out)])
            self.assertEqual([p.name for p in out.iterdir()], ['work_snapshot.json'])
            self.assertEqual(oct((out / 'work_snapshot.json').stat().st_mode)[-3:], '600')
            wk.validate_work_snapshot(
                json.loads((out / 'work_snapshot.json').read_text()), 'written')


class TheSnapshotIsDerivedAndReproducible(unittest.TestCase):
    def test_two_builds_of_the_same_inputs_agree(self):
        with tempfile.TemporaryDirectory() as td:
            root, rel, cart = _prod(td), _reliability(td), _snapshot(td)
            a = wk.build_work_snapshot(root, rel, cart, now=NOW)
            b = wk.build_work_snapshot(root, rel, cart,
                                       now=NOW + wk.dt.timedelta(hours=3))
            self.assertEqual(a['semantic_digest'], b['semantic_digest'])
            self.assertNotEqual(a['generated_at'], b['generated_at'])

    def test_counts_match_the_work_they_summarise(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            c, w = s['counts'], s['work']
            self.assertEqual(c['source_records'], len(w))
            self.assertIsNone(c['proven_unique_work_count'])
            self.assertEqual(sum(c['by_owner_view_state'].values()), len(w))
            self.assertEqual(sum(c['by_acceptance_status'].values()), len(w))
            self.assertEqual(sum(c['by_claim_kind'].values()), len(w))
            self.assertEqual(c['waiting_owner'],
                             sum(1 for x in w if x['owner_view_state'] == 'WAITING_OWNER'))
            self.assertEqual(c['reliability_explicit'] + c['reliability_mention_only']
                             + c['reliability_none'], len(w))

    def test_an_unreadable_source_is_not_read_as_no_work(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td)
            (root / 'KANBAN.json').write_text('{ это не json')
            s = _build(td, production=root)
            rec = [x for x in s['sources'] if x['source'] == 'KANBAN.json'][0]
            self.assertEqual(rec['status'], 'UNREADABLE')
            self.assertEqual([x for x in s['work'] if x['source'] == 'KANBAN.json'], [])
            self.assertGreaterEqual(s['counts']['sources_unavailable'], 1)

    def test_an_empty_tree_produces_no_invented_work(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'empty'
            root.mkdir()
            s = wk.build_work_snapshot(root, None, None, now=NOW)
            self.assertEqual(s['work'], [])
            self.assertEqual(s['counts']['source_records'], 0)


class ThePageOffersNoWayToActAndItsFiltersMatchItsData(unittest.TestCase):
    def _page(self, td):
        return pr._work_view(_build(td), {'work_snapshot.json'})

    def test_no_control_on_the_page_performs_anything(self):
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            page = self._page(td)
            self.assertEqual(page.count('<button'), 0)
            self.assertEqual(page.count('<form'), 0)
            handlers = set(_re.findall(r'on[a-z]+="([A-Za-z_]+)\(', page))
            self.assertLessEqual(handlers, {'spaFilter', 'spaSort'})
            labels = _re.findall(r'<(?:button|a|input|select|option)\b[^>]*>([^<]*)', page)
            for verb in ('Start', 'Stop', 'Assign', 'Reassign', 'Approve', 'Reject',
                         'Retry', 'Pause', 'Resume', 'Create task', 'Resolve', 'Deploy',
                         'Назначить', 'Запустить', 'Остановить', 'Принять', 'Отклонить',
                         'Завести задачу'):
                for label in labels:
                    self.assertNotIn(verb.lower(), label.strip().lower())

    def test_every_facet_option_exists_in_the_data(self):
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            page = pr._work_view(s, {'work_snapshot.json'})
            block = page[page.index('id="work-scope"'):]
            block = block[:block.index('data-role="list"')]
            facets = _re.findall(r'<select[^>]*data-role="facet"[^>]*>(.*?)</select>',
                                 block, _re.S)
            self.assertEqual(len(facets), 9)
            options = {o for f in facets
                       for o in _re.findall(r'<option value="([^"]*)"', f)} - {''}
            present = ({w['owner_view_state'] for w in s['work']}
                       | {str(w['source_state']) for w in s['work']}
                       | {w['work_type'] for w in s['work']}
                       | {w.get('owner_role') or 'не измерено' for w in s['work']}
                       | {w['acceptance_status'] for w in s['work']}
                       | {w['acceptance_applicability'] for w in s['work']}
                       | {w['blocker_status'] for w in s['work']}
                       | {'да', 'нет', 'объявленная', 'упоминание'})
            self.assertLessEqual(options, present)

    def test_every_row_carries_the_attributes_the_filters_read(self):
        import re as _re
        with tempfile.TemporaryDirectory() as td:
            page = self._page(td)
            rows = _re.findall(r'<div class="row"[^>]*>', page)
            self.assertTrue(rows)
            for row in rows:
                for attr in ('data-wview', 'data-wsource', 'data-wtype', 'data-wowner',
                             'data-waccept', 'data-wapplic', 'data-wblock',
                             'data-wdecision',
                             'data-wfinding', 'data-hay', 'data-id'):
                    self.assertIn(attr, row)

    def test_an_absent_snapshot_is_not_rendered_as_no_work(self):
        page = pr._work_view(None, set())
        self.assertIn('не приложен', page)
        self.assertIn('НЕ значит, что работы нет', page)

    def test_unmeasured_values_are_printed_as_such(self):
        with tempfile.TemporaryDirectory() as td:
            page = self._page(td)
            self.assertIn('не измерено', page)
            self.assertIn('блокером здесь не считается', page)


class IdentityIsMeasuredNotAssumed(unittest.TestCase):
    """Складывать записи двух реестров в одно число можно только доказав уникальность."""

    def test_one_id_in_two_columns_is_one_record_not_two(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            same = [w for w in s['work'] if w['work_id'] == 'kanban:MP-404']
            self.assertEqual(len(same), 1)
            self.assertEqual(s['identity']['kanban']['identifiers_in_several_columns'],
                             ['MP-404'])
            self.assertGreater(s['identity']['kanban']['source_record_count'],
                               s['identity']['kanban']['unique_identifier_count'])

    def test_the_unique_total_across_registries_is_not_claimed(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertIsNone(s['identity']['proven_unique_work_count'])
            self.assertIn('НЕ ИЗМЕРЕНО', s['identity']['proven_unique_reason'])
            page = pr._work_view(s, {'work_snapshot.json'})
            self.assertIn('Уникальное число работ НЕ ИЗМЕРЕНО', page)

    def test_a_title_match_is_never_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td, cards={'inbox-same-title.md': {
                'title': 'фича', 'status': 'in-progress', 'created': '2026-09-01'}})
            s = _build(td, production=root)
            # тот же заголовок есть у MP-404 в фикстуре KANBAN
            self.assertEqual(len([w for w in s['work']
                                  if w['work_id'] == 'inbox-same-title.md']), 1)
            self.assertEqual(len([w for w in s['work']
                                  if w['work_id'] == 'kanban:MP-404']), 1)
            self.assertEqual(s['identity']['cross_source']['title_only_matches'], 0)
            self.assertIn('тождеством',
                          s['identity']['cross_source']['title_only_basis'])

    def test_an_explicit_reference_is_a_reference_not_a_merge(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td, cards={'inbox-refs.md': {
                'title': 'про MP-404 и MP-500', 'status': 'in-progress',
                'created': '2026-09-01'}})
            s = _build(td, production=root)
            w = _by(s, 'inbox-refs.md')
            self.assertEqual({r['id'] for r in w['cross_source_refs']},
                             {'MP-404', 'MP-500'})
            self.assertTrue(all(r['relation'] == 'EXPLICIT_REFERENCE'
                                for r in w['cross_source_refs']))
            # обе задачи KANBAN остались самостоятельными записями
            self.assertTrue([x for x in s['work'] if x['work_id'] == 'kanban:MP-404'])
            self.assertTrue([x for x in s['work'] if x['work_id'] == 'kanban:MP-500'])
            self.assertEqual(s['identity']['unresolved_identity_records'], 1)

    def test_authority_between_registries_has_no_silent_winner(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            self.assertEqual(
                s['identity']['cross_source']['authority_between_registries'],
                'AUTHORITY_UNDEFINED')
            self.assertIn('победителя не выбираем',
                          s['identity']['cross_source']['authority_note'])

    def test_the_contract_refuses_an_invented_unique_total(self):
        with tempfile.TemporaryDirectory() as td:
            broken = copy.deepcopy(_build(td))
            broken['identity']['proven_unique_reason'] = ''
            with self.assertRaises(wk.WorkInputError):
                wk.validate_work_snapshot(broken, 'mutated')


class AuthorityIsQuotedNotAsserted(unittest.TestCase):
    def test_the_tracker_authority_quotes_a_real_rule(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            rec = [r for r in s['sources']
                   if r['source'] == 'nimbalyst-local/tracker/*.md'][0]
            self.assertEqual(rec['authority_status'], 'AUTHORITATIVE')
            self.assertIn('Источник правды', rec['authority_quote'])

    def test_kanban_is_not_called_authoritative_without_a_rule(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            rec = [r for r in s['sources'] if r['source'] == 'KANBAN.json'][0]
            self.assertEqual(rec['authority_status'], 'AUTHORITY_UNDEFINED')
            self.assertIn('НЕТ', rec['authority_quote'])

    def test_a_derived_index_never_claims_authority(self):
        with tempfile.TemporaryDirectory() as td:
            s = _build(td)
            for name in ('nimbalyst-local/tracker/_BOARD.md',
                         'reliability_snapshot.json'):
                rec = [r for r in s['sources'] if r['source'] == name][0]
                self.assertEqual(rec['authority_status'], 'NOT_AUTHORITY')

    def test_the_contract_refuses_authority_without_a_quote(self):
        with tempfile.TemporaryDirectory() as td:
            broken = copy.deepcopy(_build(td))
            rec = [r for r in broken['sources'] if r['source'] == 'KANBAN.json'][0]
            rec['authority_status'] = 'AUTHORITATIVE'
            rec['authority_quote'] = ''
            with self.assertRaises(wk.WorkInputError):
                wk.validate_work_snapshot(broken, 'mutated')


class ApplicabilityIsNotAVerdict(unittest.TestCase):
    def test_a_registry_no_rule_covers_gets_unknown_not_unconfirmed(self):
        with tempfile.TemporaryDirectory() as td:
            w = _by(_build(td), 'kanban:MP-500')
            self.assertEqual(w['acceptance_applicability'], 'UNKNOWN')
            self.assertEqual(w['acceptance_status'], 'UNKNOWN')
            self.assertEqual(w['owner_view_state'], 'DONE_ACCEPTANCE_UNKNOWN')
            self.assertIn('НЕ измерена', w['acceptance_evidence'][0]['detail'])

    def test_three_kinds_of_completion_are_counted_apart(self):
        with tempfile.TemporaryDirectory() as td:
            c = _build(td)['counts']
            self.assertEqual(
                c['completed_total'],
                c['accepted'] + c['done_acceptance_unconfirmed']
                + c['done_acceptance_unknown'] + c['done_acceptance_not_applicable'])
            self.assertGreater(c['done_acceptance_unknown'], 0)
            self.assertGreater(c['done_acceptance_not_applicable'], 0)

    def test_the_contract_refuses_blaming_a_rule_that_does_not_look_here(self):
        with tempfile.TemporaryDirectory() as td:
            broken = copy.deepcopy(_build(td))
            victim = _by(broken, 'kanban:MP-500')
            victim['owner_view_state'] = 'DONE_ACCEPTANCE_UNCONFIRMED'
            with self.assertRaises(wk.WorkInputError):
                wk.validate_work_snapshot(broken, 'mutated')

    def test_a_confirmed_acceptance_on_an_open_card_is_shown_as_a_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            root = _prod(td, cards={'own-answered-open.md': {
                'title': 'ответ есть, карточка открыта', 'status': 'owner-done',
                'created': '2026-08-11', 'owner_choice': 'B',
                'owner_answered_at': '2026-08-12T09:00:00Z'}})
            s = _build(td, production=root)
            w = _by(s, 'own-answered-open.md')
            self.assertTrue(w['acceptance_state_conflict'])
            self.assertEqual(w['acceptance_status'], 'CONFIRMED')
            self.assertEqual(w['source_state'], 'owner-done',
                             'исходное состояние НЕ переписано')
            self.assertEqual(w['owner_view_state'], 'IN_PROGRESS')
            self.assertEqual(s['counts']['acceptance_state_conflicts'], 1)
            page = pr._work_view(s, {'work_snapshot.json'})
            self.assertIn('Приёмка подтверждена, а состояние не закрыто', page)
