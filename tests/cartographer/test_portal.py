"""Behaviour and refusal tests for the studio portal (Director OS Phase 2).

The risk of a portal is that it looks authoritative. Each test below is one way it could
claim more than the sources say: an unreadable tracker reading as "no tasks", a recorded
`done` reading as accepted work, a text mention reading as an assignment, a derived
candidate reading as a real owner decision, arbitrary card text executing in the page.
"""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

_root = Path(__file__).parents[2] / 'scripts/cartographer'


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _root / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ex = _load('portal_extract')
pr = _load('portal_render')
d = _load('diff')
SENTINEL = 'SYNTHETIC_SECRET_SENTINEL_P2'

TRACKER_YAML = """type: {kind}
displayName: X
idPrefix: {prefix}
fields:
  - name: title
    type: string
  - name: status
    type: select
    default: {default}
    options:
{options}
  - name: priority
    type: select
    default: medium
    options:
      - value: high
        label: High
"""


def _tracker_yaml(kind, default, options, prefix=None):
    body = ''.join(f'      - value: {v}\n        label: {v}\n        category: {c}\n'
                   for v, c in options)
    return TRACKER_YAML.format(kind=kind, default=default, options=body,
                               prefix=prefix or kind)


def _card(front, body='## тело\nтекст записи\n'):
    lines = ['---']
    for k, v in front.items():
        if isinstance(v, list):
            lines.append(f'{k}:')
            lines.extend(f'  - "{x}"' for x in v)
        elif isinstance(v, dict):
            lines.append(f'{k}:')
            lines.extend(f'  {a}: {b}' for a, b in v.items())
        else:
            lines.append(f'{k}: {v}')
    lines.append('---')
    return '\n'.join(lines) + '\n\n' + body


def _production(td, cards=None, manifest=True, registry=True, trackers=True):
    """A production-shaped tree with the real file layout and formats."""
    root = Path(td) / 'prod'
    (root / 'nimbalyst-local/tracker').mkdir(parents=True)
    (root / 'architecture').mkdir(parents=True)
    (root / 'data').mkdir(parents=True)
    if trackers:
        (root / '.nimbalyst/trackers').mkdir(parents=True)
        (root / '.nimbalyst/trackers/inbox.yaml').write_text(_tracker_yaml(
            'inbox', 'new', [('new', 'unstarted'), ('in-progress', 'started'),
                             ('done', 'done'), ('ingested', 'done')]))
        (root / '.nimbalyst/trackers/agent-task.yaml').write_text(_tracker_yaml(
            'agent-task', 'backlog', [('backlog', 'unstarted'),
                                      ('in-progress', 'started'), ('done', 'done')],
            prefix='agent'))
        (root / '.nimbalyst/trackers/owner-decision.yaml').write_text(_tracker_yaml(
            'owner-decision', 'needs-owner',
            [('needs-owner', 'unstarted'), ('owner-accepted', 'started'),
             ('ingested', 'done')], prefix='own'))
    for name, text in (cards or {}).items():
        (root / 'nimbalyst-local/tracker' / name).write_text(text, encoding='utf-8')
    if manifest:
        (root / 'architecture/manifest.json').write_text(json.dumps({'agents': [
            {'label': 'com.spa.alpha', 'role': 'monitoring', 'layer': 'product',
             'intent': 'active', 'schedule': 'interval:3600s', 'produces': [],
             'consumes': [], 'governed_by': ['ADR-066']}]}))
    if registry:
        (root / 'data/agent_registry.json').write_text(json.dumps({'agents': [
            {'label': 'com.spa.alpha', 'role': 'monitoring', 'retired': False},
            {'label': 'com.spa.only_in_registry', 'role': 'ops', 'retired': False}]}))
    (root / 'KANBAN.json').write_text(json.dumps({'last_updated': '2026-06-22'}))
    return root


def _sets(td, snapshot=None, briefing=None):
    carto = Path(td) / 'carto'
    carto.mkdir()
    snap = snapshot if snapshot is not None else {
        'schema_version': 'cartographer.snapshot/0.3',
        'finished_at': '2026-09-19T10:00:00+00:00',
        'entities': [{'id': 'com.spa.alpha', 'status': 'LIVE',
                      'stages': {'DECLARED': True, 'REGISTERED': True, 'INSTALLED': True,
                                 'LOADED': True, 'RUNNING': True,
                                 'PRODUCING_OUTPUT': None, 'HEALTHY': None},
                      'domains': {'gui/501': True}, 'last_exit': 0,
                      'last_exit_basis': 'historical',
                      'document_references': [{'reference': 'ADR-066',
                                               'outcome': 'resolved',
                                               'path': 'docs/decisions/ADR-066.md'}]}],
        'repositories': [], 'findings': []}
    (carto / 'snapshot.json').write_text(json.dumps(snap))
    (carto / 'system_map.md').write_text('# map\n')
    brief_dir = Path(td) / 'brief'
    brief_dir.mkdir()
    if briefing is not False:
        (brief_dir / 'owner_briefing.json').write_text(json.dumps(briefing or {
            'schema_version': 'cartographer.owner_briefing/0.1',
            'generated_at': '2026-09-19T11:00:00+00:00',
            'mode': 'comparison',
            'freshness_and_coverage': {
                'observed_at': '2026-09-19T10:00:00+00:00',
                'age_at_generation_human': '60 мин',
                'freshness_policy': 'POLICY_UNDEFINED',
                'stale_summary_is_not_a_broken_system': 'устаревшая сводка ≠ поломка',
                'capture_window': {'started_at': 'a', 'finished_at': 'b',
                                   'duration_seconds': 1},
                'sources': [], 'git_baselines': [], 'not_measured': [],
                'freshness_note': 'нет порога', 'compared_sets': None},
            'material_changes': {'confirmed': [], 'observation_quality': [],
                                 'applicability': [], 'informational': []},
            'attention': [], 'owner_decision_candidates': [
                {'id': 'owner:drift_present', 'observed_fact': '17 наблюдений',
                 'why_a_decision_may_be_needed': 'меняет прод-дерево',
                 'existing_rule': 'deployment.md п.6',
                 'what_must_still_be_found_out': 'разобрать список',
                 'possible_next_safe_step': 'разбор человеком',
                 'severity': 'POLICY_UNDEFINED', 'deadline': 'POLICY_UNDEFINED',
                 'obligation': 'НЕ ОБЯЗАТЕЛЬНО', 'action_taken': 'НИЧЕГО',
                 'examples': []}],
            'unknowns': [], 'claim_limits': ['предел'],
            'counts': {'confirmed_changes': 0, 'attention_items': 0,
                       'owner_candidates': 1, 'unknown_findings': 0, 'unknown_groups': 0},
            'overall_health_note': 'нет оценки', 'semantic_digest': 'x' * 64}))
    return carto, brief_dir


def _extract(td, **kw):
    root = _production(td, **kw)
    carto, brief = _sets(td)
    return ex.build_portal_snapshot(root, carto, brief), root, carto, brief


class SourceAdaptersOnRealFormats(unittest.TestCase):
    def test_frontmatter_is_read_and_the_body_is_not(self):
        card = _card({'trackerStatus': {'type': 'inbox'}, 'title': 'Задача A',
                      'status': 'done', 'created': '2026-08-01'},
                     body='## тело\ntry: это проза, а не поле\nelse: и это\n')
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'inbox-a.md': card})
        task = portal['tasks'][0]
        self.assertEqual(task['title'], 'Задача A')
        self.assertEqual(task['status_raw'], 'done')
        self.assertNotIn('try', task['fields'])
        self.assertNotIn('else', task['fields'])
        self.assertFalse(task['body_copied'])
        blob = json.dumps(portal, ensure_ascii=False)
        self.assertNotIn('это проза', blob)

    def test_the_status_group_comes_from_the_tracker_definition(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'inbox-a.md': _card({'title': 'A', 'status': 'done'}),
                'inbox-b.md': _card({'title': 'B', 'status': 'in-progress'}),
                'agent-c.md': _card({'title': 'C', 'status': 'backlog'})})
        groups = {t['id']: t['status_group'] for t in portal['tasks']}
        self.assertEqual(groups, {'inbox-a': 'закрыто', 'inbox-b': 'в работе',
                                  'agent-c': 'не начато'})
        basis = [t['status_group_basis'] for t in portal['tasks']]
        self.assertTrue(all('category' in b and '.yaml' in b for b in basis), basis)

    def test_the_original_status_is_never_replaced_by_the_group(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'inbox-a.md': _card({'title': 'A', 'status': 'ingested'})})
        task = portal['tasks'][0]
        self.assertEqual(task['status_raw'], 'ingested')
        self.assertEqual(task['status_group'], 'закрыто')
        page = pr.html(portal, None, {'state': 'X', 'note': 'y'})
        self.assertIn('ingested', page)

    def test_owner_decision_records_keep_their_lifecycle_fields(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'own-x.md': _card({
                'title': 'Решение', 'status': 'ingested', 'owner_choice': 'C',
                'owner_answered_at': '2026-08-02T10:00:00Z',
                'owner_answer_via': 'telegram'})})
        rec = portal['owner_decision_records'][0]
        self.assertEqual(rec['object_type'], 'owner_decision_record')
        self.assertEqual(rec['fields']['owner_choice'], 'C')
        self.assertEqual(rec['fields']['owner_answer_via'], 'telegram')
        self.assertEqual(portal['tasks'], [])


class AnUnavailableSourceIsNotAnEmptyStudio(unittest.TestCase):
    def test_a_missing_tracker_directory_does_not_read_as_no_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            root = _production(td)
            (root / 'nimbalyst-local/tracker').rmdir()
            carto, brief = _sets(td)
            portal = ex.build_portal_snapshot(root, carto, brief)
        self.assertEqual(portal['tasks'], [])
        errors = portal['extraction_errors']
        self.assertTrue(any('tracker' in e['source'] for e in errors))
        self.assertTrue(any('НЕ значит «задач нет»' in e['consequence'] for e in errors))
        page = pr.html(portal, None, {'state': 'X', 'note': 'y'})
        self.assertIn('недоступный источник — это не «задач нет»', page)

    def test_a_missing_manifest_is_named_not_silently_empty(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, manifest=False)
        self.assertTrue(any('manifest.json' in e['source']
                            for e in portal['extraction_errors']))
        self.assertTrue(any('НЕ значит «ролей нет»' in e['consequence']
                            for e in portal['extraction_errors']))

    def test_a_missing_tracker_vocabulary_leaves_statuses_unknown_not_guessed(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, trackers=False, cards={
                'inbox-a.md': _card({'title': 'A', 'status': 'done'})})
        task = portal['tasks'][0]
        self.assertEqual(task['status_raw'], 'done')
        self.assertEqual(task['status_group'], 'UNKNOWN_STATUS')


class UnknownAndMissingAreVisible(unittest.TestCase):
    def test_a_status_outside_the_vocabulary_is_unknown_status(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'inbox-a.md': _card({'title': 'A', 'status': 'соврешенно-новый'})})
        task = portal['tasks'][0]
        self.assertEqual(task['status_group'], 'UNKNOWN_STATUS')
        self.assertIn('not in the vocabulary', task['status_group_basis'])

    def test_a_record_without_a_status_is_unknown_not_open(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'inbox-a.md': _card({'title': 'A'})})
        self.assertEqual(portal['tasks'][0]['status_group'], 'UNKNOWN_STATUS')
        self.assertIsNone(portal['tasks'][0]['status_raw'])

    def test_a_missing_field_is_absent_not_false(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'inbox-a.md': _card({'title': 'A', 'status': 'new'})})
        fields = portal['tasks'][0]['fields']
        for key in ('priority', 'owner', 'claimed_by', 'acceptance_probe'):
            self.assertNotIn(key, fields)
            self.assertIsNot(fields.get(key), False)

    def test_an_unterminated_frontmatter_is_reported_not_guessed(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'inbox-broken.md': '---\ntitle: X\nstatus: new\n\nтело без закрытия\n'})
        task = portal['tasks'][0]
        self.assertIn('not terminated', task['parse_error'])
        self.assertEqual(task['status_group'], 'UNKNOWN_STATUS')


class LinksNeedEvidence(unittest.TestCase):
    def test_a_finding_key_naming_a_label_is_a_provable_link(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'inbox-a.md': _card({
                'title': 'A', 'status': 'new',
                'finding_key': '"B7:manifest_parity:com.spa.alpha"'})})
        links = portal['links']
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]['to'], {'type': 'launchd_label', 'id': 'com.spa.alpha'})
        self.assertIn('literally contains', links[0]['basis'])
        self.assertFalse(links[0]['proves_assignment'])

    def test_claimed_by_is_an_executor_string_not_an_agent(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'inbox-a.md': _card({
                'title': 'A', 'status': 'in-progress', 'claimed_by': 'cycle-663'})})
        claim = portal['executor_claims'][0]
        self.assertEqual(claim['kind'], 'executor_claim_string')
        self.assertEqual(claim['agent_link'], 'UNLINKED')
        self.assertEqual(portal['links'], [])
        self.assertIn('НЕ метка launchd', claim['note'])

    def test_a_label_mentioned_in_the_body_is_not_a_link(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'inbox-a.md': _card(
                {'title': 'A', 'status': 'new'},
                body='агент com.spa.alpha что-то делал\n')})
        self.assertEqual(portal['links'], [])
        mention = portal['text_mentions'][0]
        self.assertEqual(mention['labels'], ['com.spa.alpha'])
        self.assertFalse(mention['proves_assignment'])
        agent = [a for a in portal['agents_and_roles'] if a['id'] == 'com.spa.alpha'][0]
        self.assertEqual(agent['task_links'], [])
        self.assertEqual(agent['text_mentions'], 1)

    def test_an_agent_without_a_provable_link_is_shown_unlinked(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td)
            page = pr.html(portal, None, {'state': 'X', 'note': 'y'})
        self.assertIn('UNLINKED', page)
        self.assertIn('доказуемой связи с записями нет', page)

    def test_the_page_never_claims_an_agent_is_working_on_a_task(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'inbox-a.md': _card({
                'title': 'A', 'status': 'in-progress', 'claimed_by': 'pid98130'})})
            page = pr.html(portal, None, {'state': 'X', 'note': 'y'})
        self.assertNotIn('работает над задачей', page.replace(
            'Портал не утверждает «агент сейчас работает над задачей»', ''))
        self.assertIn('строка\nисполнителя', page.replace('  ', ' ').replace(' ', '\n'))


class DoneIsNotAccepted(unittest.TestCase):
    def test_a_recorded_done_without_acceptance_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'inbox-a.md': _card({'title': 'A', 'status': 'done'})})
        acc = portal['tasks'][0]['acceptance']
        self.assertIsNone(acc['accepted'])
        self.assertIsNone(acc['result_recorded'])
        self.assertIn('НЕ ПОДТВЕРЖДЕНО', acc['verdict'])
        self.assertEqual(portal['counts']['closed_inbox_without_confirmed_acceptance'], 1)

    def test_a_declared_probe_without_a_result_is_still_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'inbox-a.md': _card({
                'title': 'A', 'status': 'done', 'acceptance_probe': 'some_probe'})})
        acc = portal['tasks'][0]['acceptance']
        self.assertEqual(acc['probe_declared'], 'some_probe')
        self.assertIsNone(acc['accepted'])
        self.assertIn('NOT_FOUND', acc['result_source'])

    def test_the_page_says_so_next_to_the_count(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'inbox-a.md': _card({'title': 'A', 'status': 'done'})})
            page = pr.html(portal, None, {'state': 'X', 'note': 'y'})
        self.assertIn('это не принятая', page)
        self.assertIn('приёмка НЕ ПОДТВЕРЖДЕНА', page)


class RealDecisionsAreSeparateFromCandidates(unittest.TestCase):
    def test_records_and_candidates_never_share_a_list(self):
        with tempfile.TemporaryDirectory() as td:
            root = _production(td, cards={'own-x.md': _card({
                'title': 'Настоящее решение', 'status': 'needs-owner'})})
            carto, brief_dir = _sets(td)
            portal = ex.build_portal_snapshot(root, carto, brief_dir)
            brief = json.loads((brief_dir / 'owner_briefing.json').read_text())
            page = pr.html(portal, brief, {'state': 'X', 'note': 'y'})
        self.assertEqual(len(portal['owner_decision_records']), 1)
        ids = {r['id'] for r in portal['owner_decision_records']}
        self.assertNotIn('owner:drift_present', ids)
        self.assertIn('Записанные решения (1)', page)
        self.assertIn('Производные кандидаты Director OS (1)', page)
        self.assertIn('не карточка решения', page)

    def test_a_candidate_never_gets_a_lifecycle_it_does_not_have(self):
        with tempfile.TemporaryDirectory() as td:
            root = _production(td)
            carto, brief_dir = _sets(td)
            portal = ex.build_portal_snapshot(root, carto, brief_dir)
            brief = json.loads((brief_dir / 'owner_briefing.json').read_text())
            page = pr.html(portal, brief, {'state': 'X', 'note': 'y'})
        self.assertIn('POLICY_UNDEFINED', page)
        self.assertNotIn('owner_choice', page.split('Производные кандидаты')[1])

    def test_a_decision_without_a_recorded_outcome_says_so(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'own-x.md': _card({
                'title': 'Без исхода', 'status': 'needs-owner'})})
            page = pr.html(portal, None, {'state': 'X', 'note': 'y'})
        self.assertIn('в источнике не записан', page)


class ConflictsAndDuplicates(unittest.TestCase):
    def test_a_filename_prefix_disagreeing_with_the_declared_type_is_a_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'inbox-a.md': _card({
                'trackerStatus': {'type': 'owner-decision'}, 'title': 'A',
                'status': 'new'})})
        conflict = [c for c in portal['conflicts']
                    if c['id'].startswith('conflict:tracker_type')][0]
        self.assertEqual(conflict['authority'], 'AUTHORITY_UNDEFINED')
        self.assertEqual(len(conflict['statements']), 2)

    def test_manifest_and_registry_membership_difference_is_authority_undefined(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td)
        conflict = [c for c in portal['conflicts']
                    if c['id'] == 'conflict:manifest_vs_registry_membership'][0]
        self.assertEqual(conflict['authority'], 'AUTHORITY_UNDEFINED')
        self.assertIn('com.spa.only_in_registry', conflict['subjects'])
        self.assertIn('равенства составов', conflict['note'])

    def test_records_are_not_merged_by_a_similar_title(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'inbox-a.md': _card({'title': 'Одинаковый заголовок', 'status': 'new'}),
                'inbox-b.md': _card({'title': 'Одинаковый заголовок', 'status': 'done'})})
        self.assertEqual(len(portal['tasks']), 2)
        self.assertEqual({t['id'] for t in portal['tasks']}, {'inbox-a', 'inbox-b'})

    def test_a_duplicate_id_in_a_snapshot_is_refused_by_the_contract(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td)
            portal['tasks'] = [{'id': 'x'}, {'id': 'x'}]
            portal['counts']['tasks'] = 2
            with self.assertRaises(portal_cli.diff_mod.IncompatibleInput) as ctx:
                portal_cli.validate_portal(portal, 'test')
        self.assertIn('duplicate id', str(ctx.exception))

    def test_an_alias_of_the_same_tracker_is_not_a_conflict(self):
        """Measured on real data: 58 cards declare `agent` where the definition calls
        itself `agent-task`. Two names for one tracker, not a disagreement."""
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'agent-a.md': _card({
                'trackerStatus': {'type': 'agent'}, 'title': 'A', 'status': 'backlog'})})
        self.assertEqual([c for c in portal['conflicts']
                          if c['id'].startswith('conflict:tracker_type')], [])
        self.assertEqual(portal['tasks'][0]['declared_tracker_canonical'], 'agent-task')

    def test_a_declared_type_pointing_at_another_tracker_is_still_a_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'agent-a.md': _card({
                'trackerStatus': {'type': 'inbox'}, 'title': 'A', 'status': 'backlog'})})
        conflict = [c for c in portal['conflicts']
                    if c['id'].startswith('conflict:tracker_type')][0]
        self.assertIn('inbox', conflict['statements'][1]['says'])
        self.assertEqual(conflict['authority'], 'AUTHORITY_UNDEFINED')


class NothingDangerousReachesThePage(unittest.TestCase):
    HOSTILE = ('<img src=x onerror="alert(1)"><script>alert(2)</script>'
               '[ссылка](javascript:alert(3)) &"\'')

    def test_hostile_card_text_is_escaped_not_executed(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'inbox-evil.md': _card({
                'title': f'Задача {self.HOSTILE}', 'status': 'new',
                'domain': self.HOSTILE, 'claimed_by': self.HOSTILE})})
            page = pr.html(portal, None, {'state': 'X', 'note': self.HOSTILE})
        self.assertNotIn('<img src=x', page)
        self.assertNotIn('<script>alert(2)', page)
        self.assertNotIn('onerror="alert(1)"', page)
        self.assertIn('&lt;img', page)
        self.assertIn('&amp;', page)
        # the only script on the page is our own filter helper
        self.assertEqual(page.count('<script'), 1)
        self.assertIn('function spaFilter', page)

    def test_a_javascript_url_never_becomes_a_live_link(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'inbox-evil.md': _card({
                'title': 'javascript:alert(1)', 'status': 'new',
                'source': 'javascript:alert(2)'})})
            page = pr.html(portal, None, {'state': 'X', 'note': 'y'})
        self.assertNotIn('href="javascript:', page)
        self.assertNotIn("href='javascript:", page)
        # always produced by the run, therefore always linkable
        for href in ('portal_snapshot.json', 'run_manifest.json'):
            self.assertIn(f'href="{href}"', page)
        # not part of this set: named as absent instead of linked into nothing
        self.assertNotIn('href="diff.json"', page)
        self.assertIn('не приложен к этому комплекту', page)
        with_evidence = pr.html(portal, None, {'state': 'X', 'note': 'y'},
                                ['diff.json', 'owner_briefing.md'])
        self.assertIn('href="diff.json"', with_evidence)
        self.assertIn('href="owner_briefing.md"', with_evidence)

    def test_no_sentinel_reaches_any_output(self):
        with tempfile.TemporaryDirectory() as td:
            portal, root, carto, brief = _extract(td, cards={'inbox-a.md': _card(
                {'title': 'Задача', 'status': 'new'},
                body=f'секрет в теле: {SENTINEL}\n')})
            page = pr.html(portal, None, {'state': 'X', 'note': 'y'})
            summary = pr.owner_summary(portal, None, {'state': 'X', 'note': 'y'})
        for name, text in (('portal_snapshot.json',
                            json.dumps(portal, ensure_ascii=False)),
                           ('index.html', page), ('owner_summary.md', summary)):
            self.assertNotIn(SENTINEL, text, name)

    def test_the_page_offers_no_control_that_could_act(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td)
            page = pr.html(portal, None, {'state': 'X', 'note': 'y'})
        lowered = page.lower()
        self.assertNotIn('<button', lowered)
        self.assertNotIn('<form', lowered)
        self.assertNotIn('onclick', lowered)
        self.assertNotIn('fetch(', lowered)
        self.assertNotIn('xmlhttprequest', lowered)
        for verb in pr.FORBIDDEN_ACTIONS:
            self.assertNotIn(f'>{verb}', lowered, verb)

    def test_the_page_loads_nothing_from_the_network(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td)
            page = pr.html(portal, None, {'state': 'X', 'note': 'y'})
        for forbidden in ('http://', 'https://', 'cdn.', 'fonts.google', '//unpkg'):
            self.assertNotIn(forbidden, page.lower(), forbidden)
        self.assertIn('name="viewport"', page)
        self.assertIn('<!DOCTYPE html>', page)


class FiltersAndCountsAgreeWithTheData(unittest.TestCase):
    def _page(self, td, cards):
        portal, *_ = _extract(td, cards=cards)
        return portal, pr.html(portal, None, {'state': 'X', 'note': 'y'})

    def test_every_row_carries_the_attributes_the_filters_read(self):
        cards = {f'inbox-{i}.md': _card({'title': f'Задача {i}', 'status': 'new'})
                 for i in range(5)}
        cards['agent-x.md'] = _card({'title': 'Агентская', 'status': 'done'})
        with tempfile.TemporaryDirectory() as td:
            portal, page = self._page(td, cards)
        for task in portal['tasks']:
            self.assertIn(f'data-id="{task["id"]}"', page)
            self.assertIn(f'data-tracker="{task["tracker"]}"', page)
            self.assertIn(f'data-group="{task["status_group"]}"', page)
            self.assertIn(task['id'].lower(), page)

    def test_facet_options_are_exactly_the_values_present(self):
        with tempfile.TemporaryDirectory() as td:
            portal, page = self._page(td, {
                'inbox-a.md': _card({'title': 'A', 'status': 'new'}),
                'inbox-b.md': _card({'title': 'B', 'status': 'done'}),
                'agent-c.md': _card({'title': 'C', 'status': 'backlog'})})
        section = page.split('id="tasks-scope"')[1].split('data-role="list"')[0]
        for value in {t['status_raw'] for t in portal['tasks']}:
            self.assertIn(f'<option value="{value}">', section)
        self.assertIn('<option value="inbox">', section)
        self.assertIn('<option value="agent-task">', section)
        self.assertNotIn('<option value="owner-decision">', section)

    def test_the_headline_count_equals_the_number_of_rows(self):
        cards = {f'inbox-{i}.md': _card({'title': f'T{i}', 'status': 'new'})
                 for i in range(7)}
        with tempfile.TemporaryDirectory() as td:
            portal, page = self._page(td, cards)
        self.assertEqual(portal['counts']['tasks'], 7)
        self.assertIn('Записей: <strong>7</strong>', page)
        tasks_section = page.split('id="tasks-scope"')[1].split('<h2 id="agents"')[0]
        self.assertEqual(tasks_section.count('class="row"'), 7)

    def test_an_empty_task_list_shows_an_empty_state_not_a_blank_area(self):
        with tempfile.TemporaryDirectory() as td:
            portal, page = self._page(td, {})
        self.assertEqual(portal['counts']['tasks'], 0)
        self.assertIn('class="empty"', page)
        self.assertIn('это не «задач нет»', page)

    def test_decisions_and_tasks_are_counted_separately(self):
        with tempfile.TemporaryDirectory() as td:
            portal, page = self._page(td, {
                'inbox-a.md': _card({'title': 'A', 'status': 'new'}),
                'own-b.md': _card({'title': 'B', 'status': 'needs-owner'}),
                'owner-c.md': _card({'title': 'C', 'status': 'ingested'})})
        self.assertEqual(portal['counts']['tasks'], 1)
        self.assertEqual(portal['counts']['owner_decision_records'], 2)
        self.assertIn('Записанные решения (2)', page)


class BuildIsOfflineAndReproducible(unittest.TestCase):
    def test_the_render_module_imports_no_process_socket_or_network_library(self):
        forbidden = {'subprocess', 'socket', 'urllib', 'http', 'requests'}
        for name in ('portal_render',):
            tree = ast.parse((_root / f'{name}.py').read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split('.')[0], forbidden, name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(node.module.split('.')[0], forbidden, name)

    def test_an_offline_rebuild_reaches_no_live_source(self):
        portal_cli = _load('portal')

        def boom(*a, **k):
            raise AssertionError('the offline rebuild reached a live source')

        with tempfile.TemporaryDirectory() as td:
            portal, root, carto, brief = _extract(td)
            stored = Path(td) / 'stored'
            stored.mkdir()
            portal['page_generated_at'] = '2026-01-01T00:00:00+00:00'
            (stored / 'portal_snapshot.json').write_text(
                json.dumps(portal), encoding='utf-8')
            with patch.object(subprocess, 'run', boom), \
                 patch.object(subprocess, 'Popen', boom), \
                 patch.object(socket, 'socket', boom), \
                 patch.object(socket, 'create_connection', boom):
                final, rebuilt, manifest = portal_cli.run(types.SimpleNamespace(
                    production=root, cartographer=None, briefing=None,
                    from_portal_snapshot=stored, output=Path(td) / 'out'))
            self.assertTrue((final / 'index.html').is_file())
        self.assertEqual(manifest['mode'], 'offline_rebuild')
        self.assertFalse(manifest['stages']['extraction']['performed_by_this_run'])
        self.assertFalse(manifest['stages']['extraction']['reads_production_files'])
        self.assertFalse(manifest['stages']['build']['network_used'])

    def test_the_same_snapshot_gives_the_same_semantic_digest_and_page(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'inbox-a.md': _card({'title': 'A', 'status': 'new'})})
            first = ex.semantic_digest(portal)
            second = ex.semantic_digest(copy.deepcopy(portal))
            page_a = pr.html(portal, None, {'state': 'X', 'note': 'y'})
            page_b = pr.html(copy.deepcopy(portal), None, {'state': 'X', 'note': 'y'})
        self.assertEqual(first, second)
        self.assertEqual(page_a, page_b)

    def test_the_digest_ignores_the_page_build_time(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td)
            portal['page_generated_at'] = '2026-01-01T00:00:00+00:00'
            first = ex.semantic_digest(portal)
            portal['page_generated_at'] = '2027-12-31T23:59:59+00:00'
            self.assertEqual(first, ex.semantic_digest(portal))

    def test_every_object_carries_an_id_a_type_and_a_source(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'inbox-a.md': _card({'title': 'A', 'status': 'new'}),
                'own-b.md': _card({'title': 'B', 'status': 'needs-owner'})})
        for record in portal['tasks'] + portal['owner_decision_records']:
            self.assertTrue(record['id'])
            self.assertIn(record['object_type'], ('task', 'owner_decision_record'))
            self.assertTrue(record['source']['path'])
            self.assertTrue(record['source']['file_mtime'])
        for agent in portal['agents_and_roles']:
            self.assertTrue(agent['id'])
            self.assertEqual(agent['object_type'], 'agent_or_role')
            for block in ('role_configuration', 'registry_membership', 'observed'):
                self.assertIn('source', agent[block])

    def test_every_evidence_link_on_the_page_exists_next_to_it(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            portal, root, carto, brief = _extract(td)
            final, _, _ = portal_cli.run(types.SimpleNamespace(
                production=root, cartographer=carto, briefing=brief,
                from_portal_snapshot=None, output=Path(td) / 'out'))
            page = (final / 'index.html').read_text(encoding='utf-8')
            import re as _re
            hrefs = sorted(set(_re.findall(r'href="([^"#]+)"', page)))
            missing = [h for h in hrefs if not (final / h).exists()]
        self.assertTrue(hrefs)
        self.assertEqual(missing, [], f'ссылки без файла: {missing}')


class RunContractAndRefusals(unittest.TestCase):
    def _args(self, **over):
        base = dict(production=Path('/nonexistent'), cartographer=None, briefing=None,
                    from_portal_snapshot=None, output=None)
        base.update(over)
        return types.SimpleNamespace(**base)

    def test_a_full_run_publishes_the_documented_set(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            portal, root, carto, brief = _extract(td)
            final, built, manifest = portal_cli.run(self._args(
                production=root, cartographer=carto, briefing=brief,
                output=Path(td) / 'out'))
            produced = {p.name for p in final.iterdir()}
        for required in ('index.html', 'portal_snapshot.json', 'owner_summary.md',
                         'run_manifest.json'):
            self.assertIn(required, produced)
        self.assertEqual(manifest['writers_invoked'], 'NONE')
        self.assertEqual(manifest['canonical_records_written'], 'NONE')
        self.assertTrue(all(len(o['sha256']) == 64 for o in manifest['outputs']))
        self.assertEqual(manifest['design_reference']['state'],
                         'DESIGN_REFERENCE_UNAVAILABLE')

    def test_capture_extraction_and_page_times_stay_distinct(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            portal, root, carto, brief = _extract(td)
            _, _, manifest = portal_cli.run(self._args(
                production=root, cartographer=carto, briefing=brief,
                output=Path(td) / 'out'))
        times = manifest['times']
        self.assertEqual(times['machine_observed_at'], '2026-09-19T10:00:00+00:00')
        self.assertNotEqual(times['page_generated_at'], times['machine_observed_at'])
        self.assertNotEqual(times['extraction_finished_at'], times['machine_observed_at'])

    def test_a_truncated_portal_snapshot_is_refused(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            stored = Path(td) / 'stored'
            stored.mkdir()
            (stored / 'portal_snapshot.json').write_text(
                '{"schema_version":"cartographer.portal_snapshot/0.1","tasks":[]}')
            out = Path(td) / 'out'
            with self.assertRaises(portal_cli.diff_mod.IncompatibleInput) as ctx:
                portal_cli.run(self._args(from_portal_snapshot=stored, output=out))
            self.assertIn('required field', str(ctx.exception))
            self.assertFalse(out.exists())
            self.assertFalse(out.with_name(out.name + '.incomplete').exists())

    def test_an_unsupported_schema_is_refused(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td)
            portal['schema_version'] = 'cartographer.portal_snapshot/9.9'
            stored = Path(td) / 'stored'
            stored.mkdir()
            (stored / 'portal_snapshot.json').write_text(json.dumps(portal))
            with self.assertRaises(portal_cli.diff_mod.IncompatibleInput) as ctx:
                portal_cli.run(self._args(from_portal_snapshot=stored,
                                          output=Path(td) / 'out'))
        self.assertIn('unsupported portal schema', str(ctx.exception))

    def test_a_count_disagreeing_with_the_records_is_refused(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'inbox-a.md': _card({'title': 'A', 'status': 'new'})})
            portal['counts']['tasks'] = 99
            with self.assertRaises(portal_cli.diff_mod.IncompatibleInput) as ctx:
                portal_cli.validate_portal(portal, 'test')
        self.assertIn('disagrees', str(ctx.exception))

    def test_a_link_claiming_to_prove_an_assignment_is_refused(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={'inbox-a.md': _card({
                'title': 'A', 'status': 'new',
                'finding_key': '"B7:x:com.spa.alpha"'})})
            portal['links'][0]['proves_assignment'] = True
            with self.assertRaises(portal_cli.diff_mod.IncompatibleInput) as ctx:
                portal_cli.validate_portal(portal, 'test')
        self.assertIn('no such claim', str(ctx.exception))

    def test_a_broken_owner_briefing_refuses_rather_than_dropping_the_overview(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            portal, root, carto, brief = _extract(td)
            (brief / 'owner_briefing.json').write_text('{ not json')
            out = Path(td) / 'out'
            with self.assertRaises(portal_cli.diff_mod.IncompatibleInput):
                portal_cli.run(self._args(production=root, cartographer=carto,
                                          briefing=brief, output=out))
            self.assertFalse(out.exists())

    def test_an_existing_output_directory_is_never_overwritten(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            portal, root, carto, brief = _extract(td)
            out = Path(td) / 'out'
            out.mkdir()
            (out / 'precious.txt').write_text('earlier result')
            with self.assertRaises(SystemExit):
                portal_cli.run(self._args(production=root, cartographer=carto,
                                          briefing=brief, output=out))
            self.assertEqual((out / 'precious.txt').read_text(), 'earlier result')

    def test_the_output_may_not_land_inside_production_or_an_input_set(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            portal, root, carto, brief = _extract(td)
            for forbidden in (root / 'inside', carto / 'inside', brief / 'inside'):
                with self.assertRaises(ValueError, msg=str(forbidden)):
                    portal_cli.run(self._args(production=root, cartographer=carto,
                                              briefing=brief, output=forbidden))

    def test_a_symlink_into_production_is_caught(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            portal, root, carto, brief = _extract(td)
            alias = Path(td) / 'alias'
            alias.symlink_to(root)
            with self.assertRaises(ValueError):
                portal_cli.run(self._args(production=root, cartographer=carto,
                                          briefing=brief, output=alias / 'inside'))

    def test_main_refuses_loudly_and_writes_nothing(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            stored = Path(td) / 'stored'
            stored.mkdir()
            (stored / 'portal_snapshot.json').write_text('{ not json')
            out = Path(td) / 'out'
            with self.assertRaises(SystemExit) as ctx:
                portal_cli.main(['--from-portal-snapshot', str(stored),
                                 '--output', str(out)])
        self.assertIn('INCOMPATIBLE INPUT', str(ctx.exception))
        self.assertIn('NOT "the studio is empty"', str(ctx.exception))
        self.assertFalse(out.exists())


class DesignReferenceIsReportedHonestly(unittest.TestCase):
    def test_absence_is_named_and_the_temporary_styling_is_not_called_agreed(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            root = _production(td)
            ref = portal_cli.design_reference(root)
        self.assertEqual(ref['state'], 'DESIGN_REFERENCE_UNAVAILABLE')
        self.assertIn('согласованным дизайном не является', ref['note'])
        self.assertEqual(ref['found_but_not_applicable'], [])

    def test_a_draft_spec_for_another_surface_is_found_but_not_applied(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            root = _production(td)
            (root / 'docs').mkdir()
            (root / 'docs/DASHBOARD_UX.md').write_text(
                '# X\n> **Status:** DESIGN SPEC (read-only / not yet built).\n')
            ref = portal_cli.design_reference(root)
        self.assertEqual(ref['state'], 'DESIGN_REFERENCE_UNAVAILABLE')
        found = ref['found_but_not_applicable'][0]
        self.assertFalse(found['approved_for_this_portal'])
        self.assertTrue(found['looks_like_draft'])
        self.assertIn('ПУБЛИЧНОМУ сайту', ref['reason_not_applied'])


class TheAcceptanceRuleIsAppliedOnlyWhereItGoverns(unittest.TestCase):
    """Found by manual verification against the source: the acceptance rule names the
    queue it governs and the ones it does not — inbox yes, own-*/owner-* and agent-* no.
    Applying its verdict to all three stated a rule that does not exist for two."""

    def test_an_inbox_card_gets_the_acceptance_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'inbox-a.md': _card({'title': 'A', 'status': 'done'})})
        acc = portal['tasks'][0]['acceptance']
        self.assertTrue(acc['rule_applies_to_this_tracker'])
        self.assertIn('НЕ ПОДТВЕРЖДЕНО', acc['verdict'])

    def test_an_agent_task_and_a_decision_are_outside_the_rule(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'agent-a.md': _card({'title': 'A', 'status': 'done'}),
                'own-b.md': _card({'title': 'B', 'status': 'ingested'})})
        for record in portal['tasks'] + portal['owner_decision_records']:
            acc = record['acceptance']
            self.assertFalse(acc['rule_applies_to_this_tracker'], record['id'])
            self.assertIn('не распространяется', acc['verdict'])
            self.assertIsNone(acc['accepted'])

    def test_the_counts_separate_the_two_populations(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'inbox-a.md': _card({'title': 'A', 'status': 'done'}),
                'agent-b.md': _card({'title': 'B', 'status': 'done'}),
                'own-c.md': _card({'title': 'C', 'status': 'ingested'})})
        c = portal['counts']
        self.assertEqual(c['closed_inbox_without_confirmed_acceptance'], 1)
        self.assertEqual(c['closed_records_outside_the_acceptance_rule'], 2)

    def test_the_page_says_the_rule_covers_only_inbox(self):
        with tempfile.TemporaryDirectory() as td:
            portal, *_ = _extract(td, cards={
                'inbox-a.md': _card({'title': 'A', 'status': 'done'}),
                'agent-b.md': _card({'title': 'B', 'status': 'done'})})
            page = pr.html(portal, None, {'state': 'X', 'note': 'y'})
        self.assertIn('только к очереди inbox', page)
        self.assertIn('правило приёмки не применяется', page)


class LongIdentifiersDoNotBreakTheNarrowLayout(unittest.TestCase):
    """Found in a real 390px viewport: a 40-character git SHA rendered inside <strong>
    did not wrap and pushed the document 29px wider than the screen."""

    def test_card_values_and_headlines_may_break_anywhere(self):
        css = pr._CSS
        self.assertIn('.card strong', css)
        self.assertIn('overflow-wrap:anywhere', css)
        block = css.split('.big{')[1].split('}')[0]
        self.assertIn('overflow-wrap:anywhere', block)

    def test_a_long_identifier_is_rendered_inside_a_breakable_element(self):
        sha = '0' * 40
        with tempfile.TemporaryDirectory() as td:
            root = _production(td)
            carto, brief_dir = _sets(td)
            brief = json.loads((brief_dir / 'owner_briefing.json').read_text())
            brief['material_changes']['confirmed'] = [{
                'id': 'BASELINE_CHANGED:repository:/repo', 'headline': 'Сменился коммит',
                'subject': '/repo', 'detail': None, 'old': sha, 'new': 'f' * 40,
                'class': 'comparison_basis', 'materiality': 'material', 'note': None,
                'evidence': {'artifact': 'diff.json', 'pointer': 'changes[0]'}}]
            portal = ex.build_portal_snapshot(root, carto, brief_dir)
            page = pr.html(portal, brief, {'state': 'X', 'note': 'y'})
        self.assertIn('f' * 40, page)
        # the long value sits inside the card, whose children may break anywhere
        self.assertIn('<div class="card">', page)
        self.assertIn('.card strong,.card div{overflow-wrap:anywhere}', page)


class TheReliabilitySectionTravelsWithItsEvidence(unittest.TestCase):
    """Phase 4 живёт в портале на тех же правах, что и карта авторитетности."""

    def _snapshot(self, td, **over):
        rel = _load('reliability')
        root = Path(td) / 'relprod'
        (root / 'data').mkdir(parents=True, exist_ok=True)
        (root / 'data/agent_health.json').write_text(json.dumps({
            'timestamp': '2026-09-20T10:00:00+00:00',
            'agents': [{'label': 'com.spa.broken', 'status': 'CRITICAL', 'last_exit': 78,
                        'log_age_min': 10, 'issue': 'агент не стартует'}],
            'system_issues': []}))
        snap = rel.build_reliability_snapshot(root, None, None)
        snap.update(over)
        out = Path(td) / 'relset'
        out.mkdir(exist_ok=True)
        (out / 'reliability_snapshot.json').write_text(
            json.dumps(snap, ensure_ascii=False), encoding='utf-8')
        return out, snap

    def _args(self, td, relset, **over):
        portal, root, carto, brief = _extract(td)
        base = dict(production=root, cartographer=carto, briefing=brief,
                    from_portal_snapshot=None, reliability=relset,
                    output=Path(td) / 'out')
        base.update(over)
        return types.SimpleNamespace(**base)

    def test_the_snapshot_is_copied_next_to_the_page_and_linked(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            relset, snap = self._snapshot(td)
            final, _, manifest = portal_cli.run(self._args(td, relset))
            produced = {p.name for p in final.iterdir()}
            page = (final / 'reliability.html').read_text(encoding='utf-8')
            self.assertIn('reliability_snapshot.json', produced)
            self.assertIn('href="reliability_snapshot.json"', page)
            self.assertIn('id="reliability"', page)
            self.assertEqual(manifest['reliability_snapshot']['digest'],
                             snap['semantic_digest'])
            self.assertIs(manifest['reliability_snapshot']['creates_tasks'], False)
            self.assertIs(manifest['reliability_snapshot']['performs_repair'], False)
            self.assertIn({'check': 'reliability_snapshot_contract', 'result': 'PASS',
                           'detail': snap['schema_version']}, manifest['checks'])

    def test_a_page_without_the_snapshot_says_so_instead_of_all_clear(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            final, _, manifest = portal_cli.run(self._args(td, None, reliability=None))
            page = (final / 'reliability.html').read_text(encoding='utf-8')
            self.assertIn('id="reliability"', page)
            self.assertIn('НЕ значит, что всё исправно', page)
            self.assertNotIn('href="reliability_snapshot.json"', page)
            self.assertIsNone(manifest['reliability_snapshot'])

    def test_a_snapshot_that_breaks_its_contract_is_refused(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            relset, snap = self._snapshot(td)
            broken = json.loads((relset / 'reliability_snapshot.json').read_text())
            broken['findings'][0]['classification'] = 'PROBABLY_BAD'
            (relset / 'reliability_snapshot.json').write_text(json.dumps(broken))
            with self.assertRaises(portal_cli.diff_mod.IncompatibleInput):
                portal_cli.run(self._args(td, relset))

    def test_an_offline_rebuild_with_the_evidence_reproduces_the_section(self):
        portal_cli = _load('portal')

        def boom(*a, **k):
            raise AssertionError('the offline rebuild reached a live source')

        with tempfile.TemporaryDirectory() as td:
            relset, _ = self._snapshot(td)
            final, built, _ = portal_cli.run(self._args(td, relset))
            first = (final / 'reliability.html').read_text(encoding='utf-8')
            stored = Path(td) / 'stored'
            stored.mkdir()
            (stored / 'portal_snapshot.json').write_text(
                json.dumps(built), encoding='utf-8')
            with patch.object(subprocess, 'run', boom), \
                 patch.object(socket, 'socket', boom), \
                 patch.object(socket, 'create_connection', boom):
                again, _, manifest = portal_cli.run(types.SimpleNamespace(
                    production=Path('/nonexistent'), cartographer=None, briefing=None,
                    from_portal_snapshot=stored, reliability=final,
                    output=Path(td) / 'out2'))
            second = (again / 'reliability.html').read_text(encoding='utf-8')
        cut = lambda t: t[t.index('id="reliability"'):]  # noqa: E731
        self.assertEqual(cut(first), cut(second),
                         'раздел обязан воспроизводиться побайтово из тех же улик')
        self.assertEqual(manifest['mode'], 'offline_rebuild')


class TheWorkSectionTravelsWithItsEvidence(unittest.TestCase):
    """Phase 5 живёт в портале на тех же правах, что надёжность и карта авторитетности."""

    def _snapshot(self, td):
        wk = _load('work')
        root = Path(td) / 'wkprod'
        (root / '.nimbalyst/trackers').mkdir(parents=True, exist_ok=True)
        (root / 'nimbalyst-local/tracker').mkdir(parents=True, exist_ok=True)
        (root / '.nimbalyst/trackers/inbox.yaml').write_text(
            'type: inbox\nidPrefix: inbox\nfields:\n  - name: status\n'
            '    type: select\n    options:\n'
            '      - value: in-progress\n        label: In Progress\n'
            '        category: started\n')
        (root / 'nimbalyst-local/tracker/inbox-a.md').write_text(
            '---\ntitle: работа\nstatus: in-progress\ncreated: 2026-09-01\n---\n## тело\n')
        snap = wk.build_work_snapshot(root, None, None)
        out = Path(td) / 'wkset'
        out.mkdir(exist_ok=True)
        (out / 'work_snapshot.json').write_text(json.dumps(snap, ensure_ascii=False),
                                                encoding='utf-8')
        return out, snap

    def _args(self, td, wkset, **over):
        portal, root, carto, brief = _extract(td)
        base = dict(production=root, cartographer=carto, briefing=brief,
                    from_portal_snapshot=None, work=wkset, output=Path(td) / 'out')
        base.update(over)
        return types.SimpleNamespace(**base)

    def test_the_snapshot_is_copied_next_to_the_page_and_linked(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            wkset, snap = self._snapshot(td)
            final, _, manifest = portal_cli.run(self._args(td, wkset))
            page = (final / 'work.html').read_text(encoding='utf-8')
            self.assertIn('work_snapshot.json', {p.name for p in final.iterdir()})
            self.assertIn('href="work_snapshot.json"', page)
            self.assertIn('id="work"', page)
            self.assertEqual(manifest['work_snapshot']['digest'], snap['semantic_digest'])
            self.assertIs(manifest['work_snapshot']['creates_tasks'], False)
            self.assertIs(manifest['work_snapshot']['modifies_tracker'], False)
            self.assertIs(manifest['work_snapshot']['assigns_work'], False)

    def test_a_page_without_the_snapshot_says_so_instead_of_no_work(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            final, _, manifest = portal_cli.run(self._args(td, None, work=None))
            page = (final / 'work.html').read_text(encoding='utf-8')
            self.assertIn('id="work"', page)
            self.assertIn('НЕ значит, что работы нет', page)
            self.assertIsNone(manifest['work_snapshot'])

    def test_a_snapshot_that_breaks_its_contract_is_refused(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            wkset, _ = self._snapshot(td)
            broken = json.loads((wkset / 'work_snapshot.json').read_text())
            broken['work'][0]['owner_view_state'] = 'ПОЧТИ_ГОТОВО'
            (wkset / 'work_snapshot.json').write_text(json.dumps(broken))
            with self.assertRaises(portal_cli.diff_mod.IncompatibleInput):
                portal_cli.run(self._args(td, wkset))

    def test_an_offline_rebuild_reproduces_the_section(self):
        portal_cli = _load('portal')

        def boom(*a, **k):
            raise AssertionError('the offline rebuild reached a live source')

        with tempfile.TemporaryDirectory() as td:
            wkset, _ = self._snapshot(td)
            final, built, _ = portal_cli.run(self._args(td, wkset))
            first = (final / 'work.html').read_text(encoding='utf-8')
            stored = Path(td) / 'stored'
            stored.mkdir()
            (stored / 'portal_snapshot.json').write_text(json.dumps(built),
                                                         encoding='utf-8')
            with patch.object(subprocess, 'run', boom), \
                 patch.object(socket, 'socket', boom):
                again, _, manifest = portal_cli.run(types.SimpleNamespace(
                    production=Path('/nonexistent'), cartographer=None, briefing=None,
                    from_portal_snapshot=stored, work=final, output=Path(td) / 'out2'))
            second = (again / 'work.html').read_text(encoding='utf-8')
        cut = lambda t: t[t.index('id="work"'):]  # noqa: E731
        self.assertEqual(cut(first), cut(second))
        self.assertEqual(manifest['mode'], 'offline_rebuild')


class TheRunPublishesEveryStaticPage(unittest.TestCase):
    def test_all_six_pages_are_written_and_linked(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            portal, root, carto, brief = _extract(td)
            final, _, manifest = portal_cli.run(types.SimpleNamespace(
                production=root, cartographer=carto, briefing=brief,
                from_portal_snapshot=None, output=Path(td) / 'out'))
            produced = {p.name for p in final.iterdir()}
            render = _load('portal_render')
            for name in render.PAGE_FILES:
                self.assertIn(name, produced, name)
            index = (final / 'index.html').read_text(encoding='utf-8')
            for name in render.PAGE_FILES:
                self.assertIn(f'href="{name}"', index, name)
            self.assertIn({'file': 'index.html'},
                          [{'file': o['file']} for o in manifest['outputs']])

    def test_the_index_is_much_smaller_than_the_detail_pages(self):
        portal_cli = _load('portal')
        with tempfile.TemporaryDirectory() as td:
            portal, root, carto, brief = _extract(td)
            final, _, _ = portal_cli.run(types.SimpleNamespace(
                production=root, cartographer=carto, briefing=brief,
                from_portal_snapshot=None, output=Path(td) / 'out'))
            sizes = {p.name: p.stat().st_size for p in final.iterdir()
                     if p.suffix == '.html'}
            self.assertLessEqual(sizes['index.html'], max(sizes.values()))

    def test_every_page_has_the_same_navigation(self):
        portal_cli = _load('portal')
        render = _load('portal_render')
        with tempfile.TemporaryDirectory() as td:
            portal, root, carto, brief = _extract(td)
            final, _, _ = portal_cli.run(types.SimpleNamespace(
                production=root, cartographer=carto, briefing=brief,
                from_portal_snapshot=None, output=Path(td) / 'out'))
            for name in render.PAGE_FILES:
                html = (final / name).read_text(encoding='utf-8')
                for other in render.PAGE_FILES:
                    self.assertIn(f'href="{other}"', html, f'{name} → {other}')
