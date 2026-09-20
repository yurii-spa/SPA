"""Regressions for the offline snapshot comparison (Phase 0C).

Every test here is a positive control for one way a diff can lie: by calling a lost
observation a stop, an unreadable source a removal, a missing line a fix, a moved
baseline a repair, or ordinary ageing an incident.
"""
import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import random
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

_root = Path(__file__).parents[2] / 'scripts/cartographer'


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _root / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


d = _load('diff')
sot = _load('source_of_truth')

SENTINEL = 'SYNTHETIC_SECRET_SENTINEL_0C'
REPO = '/repo'


def _snap(**over):
    """A snapshot in the shape collect() produces, schema 0.3. No probes, no filesystem."""
    base = {
        'schema_version': 'cartographer.snapshot/0.3',
        'started_at': '2026-09-19T10:00:00+00:00',
        'finished_at': '2026-09-19T10:00:09+00:00',
        'derived_state': True,
        'scope': 'test scope',
        'launchd_domains': {'gui/501': {'readable': True, 'error': None,
                                        'services': ['com.spa.alpha'],
                                        'enable_overrides': {}, 'method': 'test'}},
        'launchctl_list_ok': True,
        'labels_with_override_but_no_service': [],
        'coverage': {
            'manifest_readable': True, 'registry_readable': True,
            'installed_scan_complete': True, 'declared_plist_scan_complete': True,
            'launchctl_list_ok': True, 'ps_ok': True,
            'domains_readable': {'gui/501': True}, 'domains_complete': True,
            'document_index_available': True, 'sync_status_readable': True,
            'drift_measurable': {REPO: True}, 'baseline_sha': {REPO: 'a' * 40},
            'note': 'test',
        },
        'reference_documents': [
            {'path': 'CLAUDE.md', 'in_pinned_docs_index': None, 'in_production_tree': True},
            {'path': '.claude/rules/deployment.md', 'in_pinned_docs_index': None,
             'in_production_tree': True},
        ],
        'entities': [{
            'id': 'com.spa.alpha', 'status': 'LIVE', 'intent': 'active',
            'layer': 'product', 'role': 'monitor', 'schedule': None,
            'pid': 42, 'last_exit': 0, 'last_exit_basis': 'historical',
            'stages': {'DECLARED': True, 'REGISTERED': True, 'INSTALLED': True,
                       'LOADED': True, 'RUNNING': True,
                       'PRODUCING_OUTPUT': None, 'HEALTHY': None},
            'domains': {'gui/501': True},
            'enable_overrides': {'gui/501': None},
            'declared_program': None, 'declared_plist_source': None,
            'declared_consumes': ['data/in.json'],
            'declared_governed_by': ['ADR-066'],
            'document_references': [{'reference': 'ADR-066', 'kind': 'adr_id',
                                     'outcome': 'resolved', 'path': 'docs/decisions/ADR-066.md'}],
            'declared_plist_in_repo': '/repo/launchd/com.spa.alpha.plist',
            'installed_paths': [{
                'plist': '/home/Library/LaunchAgents/com.spa.alpha.plist',
                'plist_domain_dir': '/home/Library/LaunchAgents',
                'working_directory': REPO, 'stdout': '/tmp/a.log', 'stderr': '/tmp/a.err',
                'keep_alive': None, 'start_interval': None,
                'has_calendar_schedule': False, 'environment_keys': ['SPA_ENV'],
                'entrypoint': {'executable': '/bin/bash', 'target_kind': 'script',
                               'target': '/repo/scripts/alpha.sh', 'target_exists': True,
                               'argument_count': 2, 'arguments_omitted': True,
                               'unknown_code': None, 'unknown_reason': None},
                'entrypoint_checkout': REPO,
                'entrypoint_declared_target': 'spa_core.monitoring.alpha',
            }],
            'declared_outputs': [{'relpath': 'data/out.json', 'exists': True, 'fresh': True,
                                  'slo_hours': 3, 'age_seconds': 60, 'mtime_epoch': 1.0,
                                  'size_bytes': 10, 'is_symlink': False,
                                  'producer_attribution': 'UNKNOWN'}],
            'evidence': {'LOADED': 'targeted launchctl print', 'RUNNING': 'list+ps'},
        }],
        'processes': [{'pid': 42, 'ppid': 1, 'command': 'bash'}],
        'repositories': [{
            'path': REPO, 'head': 'h' * 40,
            'cached_origin_main': 'a' * 40, 'remote_origin_main': 'a' * 40,
            'drift': {'scope': ['scripts'], 'basis': 'pinned_commit',
                      'reference': 'refs/remotes/origin/main', 'reference_sha': 'a' * 40,
                      'changed_or_missing_on_disk': ['scripts/changed.py'],
                      'production_only_tracked': ['scripts/tracked_only.py'],
                      'production_only_untracked': ['scripts/untracked_only.py']},
            'worktrees': [],
        }],
        'code_sync': {'timestamp': '2026-09-19T09:00:00+00:00', 'result': 'IN_SYNC'},
        'document_index': {'sha': 'a' * 40, 'available': True, 'path_count': 5, 'adr_count': 2},
        'ollama': {'binary': None, 'launchd': {}, 'api_reachable': False,
                   'inference_performed': False, 'routing': 'NOT_INSPECTED_OR_CHANGED'},
        'findings': [
            {'id': 'WRAPPER_TARGET_UNDECLARED:com.spa.alpha:com.spa.alpha.plist', 'kind': 'UNKNOWN',
             'rule_code': 'WRAPPER_TARGET_UNDECLARED', 'subject': 'com.spa.alpha',
             'context': 'com.spa.alpha.plist',
             'reason': 'wrapper target not declared'},
            {'id': f'DRIFT_CHANGED_OR_MISSING_ON_DISK:{REPO}:scripts/changed.py',
             'kind': 'DRIFT', 'rule_code': 'DRIFT_CHANGED_OR_MISSING_ON_DISK',
             'subject': REPO, 'context': 'scripts/changed.py', 'reason': 'changed'},
        ],
    }
    base.update(over)
    return base


def _write(directory, snapshot, system_map=True):
    p = Path(directory)
    p.mkdir(parents=True, exist_ok=True)
    (p / 'snapshot.json').write_text(json.dumps(snapshot), encoding='utf-8')
    (p / 'findings.json').write_text(json.dumps(snapshot.get('findings') or []), encoding='utf-8')
    if system_map:
        (p / 'system_map.json').write_text(json.dumps(
            {'schema_version': 'cartographer.system_map/0.1', 'nodes': [], 'edges': []}),
            encoding='utf-8')
    return p


def _diff(old_snapshot, new_snapshot, **kw):
    with tempfile.TemporaryDirectory() as td:
        a = _write(Path(td) / 'old', old_snapshot, **kw)
        b = _write(Path(td) / 'new', new_snapshot, **kw)
        return d.compare(d.load_set(a), d.load_set(b))


def _types(diff, materiality=None):
    return {c['type'] for c in diff['changes']
            if materiality is None or c['materiality'] == materiality}


def _pick(diff, ctype, detail=None):
    return [c for c in diff['changes']
            if c['type'] == ctype and (detail is None or c['detail'] == detail)]


class NoFalseChange(unittest.TestCase):
    def test_one_snapshot_against_itself_has_no_material_change(self):
        diff = _diff(_snap(), _snap())
        self.assertEqual(_types(diff, 'material'), set(), diff['changes'])
        self.assertEqual(diff['findings']['resolved'], [])
        self.assertEqual(diff['findings']['not_rechecked'], [])
        self.assertEqual(len(diff['findings']['persisting']), 2)

    def test_array_order_and_technical_timestamps_create_no_changes(self):
        """Shuffled lists and a later clock are not events. The comparison keys by
        identity and reads no timestamp, so both runs must look identical."""
        new = _snap(started_at='2026-09-19T12:00:00+00:00',
                    finished_at='2026-09-19T12:00:31+00:00')
        ent = new['entities'][0]
        ent['declared_outputs'][0].update(age_seconds=2000, mtime_epoch=99.0, size_bytes=77)
        ent['declared_consumes'] = list(reversed(ent['declared_consumes']))
        ent['installed_paths'] = list(ent['installed_paths'])
        new['findings'] = list(reversed(new['findings']))
        new['processes'] = [{'pid': 7, 'ppid': 1, 'command': 'bash'},
                            {'pid': 42, 'ppid': 1, 'command': 'bash'}]
        rng = random.Random(7)
        for repo in new['repositories']:
            for key in d.DRIFT_CATEGORIES:
                rng.shuffle(repo['drift'][key])
        diff = _diff(_snap(), new)
        self.assertEqual(diff['changes'], [], diff['changes'])

    def test_a_scheduled_job_between_runs_is_not_an_incident(self):
        old = _snap()
        old['entities'][0]['schedule'] = 'interval:3600s'
        old['entities'][0]['installed_paths'][0]['start_interval'] = 3600
        new = copy.deepcopy(old)
        new['entities'][0]['stages']['RUNNING'] = False
        new['entities'][0]['pid'] = None
        diff = _diff(old, new)
        running = _pick(diff, 'STAGE_CHANGED', 'RUNNING')
        self.assertEqual(len(running), 1)
        self.assertEqual(running[0]['materiality'], 'expected_schedule')
        self.assertNotIn('STAGE_CHANGED', _types(diff, 'material'))

    def test_a_new_pid_alone_is_informational_not_a_restart_claim(self):
        new = _snap()
        new['entities'][0]['pid'] = 4242
        new['processes'] = [{'pid': 4242, 'ppid': 1, 'command': 'bash'}]
        diff = _diff(_snap(), new)
        pid = _pick(diff, 'PID_CHANGED')
        self.assertEqual(len(pid), 1)
        self.assertEqual(pid[0]['materiality'], 'informational')
        self.assertIn('does NOT by itself prove a restart', pid[0]['note'])
        self.assertEqual(_types(diff, 'material'), set())


class KnowledgeLossIsNotAStop(unittest.TestCase):
    def test_service_really_unloaded_under_a_successful_reprobe_is_material(self):
        new = _snap()
        new['entities'][0]['stages']['LOADED'] = False
        new['entities'][0]['status'] = 'DEGRADED'
        diff = _diff(_snap(), new)
        loaded = _pick(diff, 'STAGE_CHANGED', 'LOADED')
        self.assertEqual(len(loaded), 1)
        self.assertEqual((loaded[0]['old'], loaded[0]['new']), (True, False))
        self.assertEqual(loaded[0]['materiality'], 'material')
        status = _pick(diff, 'STATUS_CHANGED')
        self.assertEqual(status[0]['evidence']['stages_changed'], ['LOADED'])

    def test_true_to_null_is_a_loss_of_knowledge_not_a_stop(self):
        new = _snap()
        new['entities'][0]['stages']['LOADED'] = None
        new['entities'][0]['status'] = 'UNKNOWN'
        new['coverage']['domains_complete'] = False
        new['coverage']['domains_readable'] = {'gui/501': False}
        diff = _diff(_snap(), new)
        self.assertEqual(_pick(diff, 'STAGE_CHANGED', 'LOADED'), [])
        lost = _pick(diff, 'STAGE_OBSERVATION_LOST', 'LOADED')
        self.assertEqual(len(lost), 1)
        self.assertEqual(lost[0]['materiality'], 'observation_quality')
        self.assertIn('NOT evidence that the stage stopped', lost[0]['note'])
        status = _pick(diff, 'STATUS_CHANGED_BY_OBSERVATION_QUALITY')
        self.assertEqual(len(status), 1)
        self.assertEqual(_pick(diff, 'STATUS_CHANGED'), [])

    def test_absent_entity_under_a_failed_source_is_not_a_removal(self):
        new = _snap(entities=[])
        new['coverage'].update(domains_complete=False, domains_readable={'gui/501': False},
                               manifest_readable=False, registry_readable=False,
                               installed_scan_complete=False, launchctl_list_ok=False,
                               ps_ok=False)
        diff = _diff(_snap(), new)
        self.assertEqual(_pick(diff, 'COMPONENT_DISAPPEARED'), [])
        unverifiable = _pick(diff, 'COMPONENT_ABSENT_UNVERIFIABLE')
        self.assertEqual(len(unverifiable), 1)
        self.assertIn('NOT a removal', unverifiable[0]['note'])
        self.assertTrue(unverifiable[0]['evidence']['unavailable_in_new'])

    def test_absent_entity_with_every_source_readable_is_a_removal(self):
        diff = _diff(_snap(), _snap(entities=[]))
        gone = _pick(diff, 'COMPONENT_DISAPPEARED')
        self.assertEqual(len(gone), 1)
        self.assertEqual(gone[0]['materiality'], 'material')
        self.assertTrue(gone[0]['evidence']['rechecked_in_new'])

    def test_a_field_absent_on_one_side_is_a_schema_gap_never_false(self):
        """The accepted 0.2 sets have no `unknown_code`; reading its absence as a value
        would invent a change on 81 plists at once."""
        old = _snap()
        del old['entities'][0]['installed_paths'][0]['entrypoint']['unknown_code']
        diff = _diff(old, _snap())
        gap = _pick(diff, 'SCHEMA_FIELD_ABSENT', 'entrypoint.unknown_code')
        self.assertEqual(len(gap), 1)
        self.assertEqual(gap[0]['materiality'], 'observation_quality')
        self.assertEqual((gap[0]['old'], gap[0]['new']), (None, 'present'))
        self.assertEqual(_pick(diff, 'ENTRYPOINT_CHANGED', 'entrypoint.unknown_code'), [])


class FindingsNeedEvidence(unittest.TestCase):
    def test_absence_alone_is_not_resolution(self):
        new = _snap(findings=[f for f in _snap()['findings']
                              if f['rule_code'] != 'WRAPPER_TARGET_UNDECLARED'])
        new['coverage']['installed_scan_complete'] = False
        diff = _diff(_snap(), new)
        self.assertEqual(diff['findings']['resolved'], [])
        not_rechecked = [f['id'] for f in diff['findings']['not_rechecked']]
        self.assertIn('WRAPPER_TARGET_UNDECLARED:com.spa.alpha:com.spa.alpha.plist', not_rechecked)
        self.assertIn('installed_scan_complete', diff['findings']['not_rechecked'][0]['why'])

    def test_absence_plus_a_successful_reprobe_is_resolution(self):
        new = _snap(findings=[f for f in _snap()['findings']
                              if f['rule_code'] != 'WRAPPER_TARGET_UNDECLARED'])
        diff = _diff(_snap(), new)
        resolved = [f['id'] for f in diff['findings']['resolved']]
        self.assertEqual(resolved, ['WRAPPER_TARGET_UNDECLARED:com.spa.alpha:com.spa.alpha.plist'])
        self.assertEqual(diff['findings']['resolved'][0]['recheck_basis'], 'recorded')
        self.assertEqual(diff['findings']['not_rechecked'], [])

    def test_a_rule_outside_the_recheck_table_is_never_resolved(self):
        old = _snap()
        old['findings'] = old['findings'] + [
            {'id': 'FUTURE_RULE:x', 'kind': 'UNKNOWN', 'rule_code': 'FUTURE_RULE',
             'subject': 'x', 'context': None, 'reason': 'invented later'}]
        diff = _diff(old, _snap())
        why = {f['id']: f['why'] for f in diff['findings']['not_rechecked']}
        self.assertIn('FUTURE_RULE:x', why)
        self.assertIn('not in the re-check table', why['FUTURE_RULE:x'])

    def test_a_finding_without_a_rule_code_is_refused_at_the_input(self):
        """Stronger than the earlier guarantee, which only declined to RESOLVE such a
        finding: a finding with no rule_code carries no identifiable probe, so the whole
        set is now refused before any comparison. The pre-round-2 artifact sets are
        exactly the ones this excludes, and they are also the ones with duplicate ids."""
        old = _snap()
        old['findings'] = [{'id': 'DRIFT:legacy', 'kind': 'DRIFT', 'subject': 'x',
                            'reason': 'old shape without rule_code'}]
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(d.IncompatibleInput) as ctx:
                d.load_set(_write(Path(td) / 'o', old))
        self.assertIn('rule_code', str(ctx.exception))


class BaselineAndDrift(unittest.TestCase):
    def _moved_baseline(self):
        new = _snap()
        repo = new['repositories'][0]
        repo['cached_origin_main'] = 'b' * 40
        repo['remote_origin_main'] = 'b' * 40
        repo['drift']['reference_sha'] = 'b' * 40
        repo['drift']['changed_or_missing_on_disk'] = []
        new['coverage']['baseline_sha'] = {REPO: 'b' * 40}
        new['findings'] = [f for f in new['findings']
                           if f['rule_code'] != 'DRIFT_CHANGED_OR_MISSING_ON_DISK']
        return new

    def test_a_moved_baseline_is_named_and_its_drift_is_not_comparable(self):
        diff = _diff(_snap(), self._moved_baseline())
        moved = _pick(diff, 'BASELINE_CHANGED')
        self.assertEqual(len(moved), 1)
        self.assertEqual((moved[0]['old'], moved[0]['new']), ('a' * 40, 'b' * 40))
        self.assertIn('NOT evidence that production was', moved[0]['note'])
        removed = _pick(diff, 'DRIFT_PATH_REMOVED')
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0]['materiality'], 'not_comparable')
        self.assertIn('not a production fix', removed[0]['note'])

    def test_a_drift_finding_under_a_moved_baseline_is_not_resolved(self):
        diff = _diff(_snap(), self._moved_baseline())
        self.assertEqual(diff['findings']['resolved'], [])
        why = {f['id']: f['why'] for f in diff['findings']['not_rechecked']}
        self.assertIn(f'DRIFT_CHANGED_OR_MISSING_ON_DISK:{REPO}:scripts/changed.py', why)
        self.assertIn('DIFFERENT baseline', str(why))

    def test_the_same_baseline_makes_a_disappearing_path_a_real_change(self):
        new = _snap()
        new['repositories'][0]['drift']['changed_or_missing_on_disk'] = []
        new['findings'] = [f for f in new['findings']
                           if f['rule_code'] != 'DRIFT_CHANGED_OR_MISSING_ON_DISK']
        diff = _diff(_snap(), new)
        removed = _pick(diff, 'DRIFT_PATH_REMOVED')
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0]['materiality'], 'material')
        self.assertIn('SAME pinned commit', removed[0]['note'])
        self.assertEqual(len(diff['findings']['resolved']), 1)

    def test_the_three_categories_stay_distinct_and_untracked_is_not_retired(self):
        new = _snap()
        drift = new['repositories'][0]['drift']
        drift['changed_or_missing_on_disk'] = []
        drift['production_only_untracked'] = ['scripts/untracked_only.py', 'scripts/new_local.py']
        new['findings'] = [f for f in new['findings']
                           if f['rule_code'] != 'DRIFT_CHANGED_OR_MISSING_ON_DISK']
        diff = _diff(_snap(), new)
        cats = {c['evidence']['category'] for c in diff['changes']
                if c['subject_kind'] == 'drift'}
        self.assertEqual(cats, {'changed_or_missing_on_disk', 'production_only_untracked'})
        added = _pick(diff, 'DRIFT_PATH_ADDED')
        self.assertEqual([c['detail'] for c in added], ['scripts/new_local.py'])
        self.assertIn('untracked never means retired',
                      added[0]['evidence']['category_meaning'])
        # the untouched category produced no change at all
        self.assertNotIn('production_only_tracked', cats)

    def test_drift_becoming_unmeasurable_is_a_coverage_change_not_a_fix(self):
        new = _snap()
        new['repositories'][0]['drift'] = None
        new['coverage']['drift_measurable'] = {REPO: False}
        new['findings'] = [f for f in new['findings']
                           if not f['rule_code'].startswith('DRIFT_')]
        diff = _diff(_snap(), new)
        self.assertEqual(len(_pick(diff, 'DRIFT_MEASURABILITY_CHANGED')), 1)
        self.assertEqual(_pick(diff, 'DRIFT_PATH_REMOVED'), [])
        # the drift finding vanished with the measurement itself — that is not a fix
        why = {f['id']: f['why'] for f in diff['findings']['not_rechecked']}
        self.assertIn(f'DRIFT_CHANGED_OR_MISSING_ON_DISK:{REPO}:scripts/changed.py', why)
        self.assertIn('not measurable', str(why))
        self.assertEqual([f['id'] for f in diff['findings']['resolved']], [])


class ArtifactFreshness(unittest.TestCase):
    def test_ageing_without_crossing_the_slo_is_not_a_change(self):
        new = _snap()
        new['entities'][0]['declared_outputs'][0].update(age_seconds=7000, mtime_epoch=5.0)
        diff = _diff(_snap(), new)
        self.assertEqual(diff['changes'], [])

    def test_crossing_the_declared_slo_is_material(self):
        new = _snap()
        new['entities'][0]['declared_outputs'][0].update(fresh=False, age_seconds=99999)
        new['entities'][0]['status'] = 'STALE'
        diff = _diff(_snap(), new)
        crossed = _pick(diff, 'ARTIFACT_SLO_CROSSED')
        self.assertEqual(len(crossed), 1)
        self.assertEqual(crossed[0]['materiality'], 'material')
        self.assertEqual(crossed[0]['evidence']['slo_hours'], 3)

    def test_freshness_becoming_unknown_is_not_stale(self):
        new = _snap()
        new['entities'][0]['declared_outputs'][0].update(fresh=None, slo_hours=None)
        diff = _diff(_snap(), new)
        self.assertEqual(_pick(diff, 'ARTIFACT_SLO_CROSSED'), [])
        unknown = _pick(diff, 'ARTIFACT_FRESHNESS_UNKNOWN')
        self.assertEqual(unknown[0]['materiality'], 'observation_quality')
        self.assertIn('UNKNOWN is not stale', unknown[0]['note'])


class DeclarationVersusObservation(unittest.TestCase):
    def test_a_declaration_change_is_not_an_observed_state_change(self):
        new = _snap()
        new['entities'][0]['declared_consumes'] = ['data/in.json', 'data/extra.json']
        diff = _diff(_snap(), new)
        decl = _pick(diff, 'DECLARATION_CHANGED', 'declared_consumes')
        self.assertEqual(len(decl), 1)
        self.assertEqual(decl[0]['class'], 'declaration')
        self.assertIn('says nothing about what is running', decl[0]['note'])
        self.assertEqual({c['class'] for c in diff['changes']}, {'declaration'})


class InputIntegrity(unittest.TestCase):
    def test_unsupported_schema_is_an_error_not_a_clean_report(self):
        with tempfile.TemporaryDirectory() as td:
            p = _write(Path(td) / 'x', _snap(schema_version='cartographer.snapshot/9.9'))
            with self.assertRaises(d.IncompatibleInput) as ctx:
                d.load_set(p)
        self.assertIn('unsupported snapshot schema', str(ctx.exception))

    def test_corrupt_json_is_an_error_not_a_clean_report(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'x'
            p.mkdir()
            (p / 'snapshot.json').write_text('{ this is not json')
            with self.assertRaises(d.IncompatibleInput):
                d.load_set(p)

    def test_missing_directory_and_missing_snapshot_are_errors(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(d.IncompatibleInput):
                d.load_set(Path(td) / 'nope')
            empty = Path(td) / 'empty'
            empty.mkdir()
            with self.assertRaises(d.IncompatibleInput):
                d.load_set(empty)

    def test_a_snapshot_without_entities_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            broken = _snap()
            del broken['entities']
            p = _write(Path(td) / 'x', broken)
            with self.assertRaises(d.IncompatibleInput):
                d.load_set(p)

    def test_main_refuses_loudly_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            good = _write(Path(td) / 'good', _snap())
            bad = _write(Path(td) / 'bad', _snap(schema_version='nope/1'))
            out = Path(td) / 'out'
            with self.assertRaises(SystemExit) as ctx:
                d.main(['--old', str(good), '--new', str(bad), '--output', str(out)])
        self.assertIn('INCOMPATIBLE INPUT', str(ctx.exception))
        self.assertIn('NOT "no changes"', str(ctx.exception))
        self.assertFalse(out.exists())

    def test_an_incomplete_set_is_reported_as_a_limitation_not_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            a = _write(Path(td) / 'old', _snap(), system_map=False)
            b = _write(Path(td) / 'new', _snap())
            diff = d.compare(d.load_set(a), d.load_set(b))
        self.assertFalse(diff['inputs']['old']['files_present']['system_map.json'])
        self.assertTrue(any('graph is not compared' in x for x in diff['limitations']))

    def test_input_files_are_identified_by_hash_and_schema(self):
        with tempfile.TemporaryDirectory() as td:
            a = _write(Path(td) / 'old', _snap())
            b = _write(Path(td) / 'new', _snap())
            diff = d.compare(d.load_set(a), d.load_set(b))
        for side in ('old', 'new'):
            rec = diff['inputs'][side]
            self.assertRegex(rec['files_sha256']['snapshot.json'], r'^[0-9a-f]{64}$')
            self.assertEqual(rec['schema_version'], 'cartographer.snapshot/0.3')


class SchemaCompatibility(unittest.TestCase):
    def _v02(self):
        old = _snap(schema_version='cartographer.snapshot/0.2')
        del old['coverage']
        del old['reference_documents']
        return old

    def test_an_accepted_02_snapshot_is_supported_with_named_limits(self):
        diff = _diff(self._v02(), _snap())
        self.assertTrue(any('coverage is INFERRED' in x for x in diff['compatibility']))
        self.assertTrue(any('schema differs' in x for x in diff['compatibility']))
        self.assertEqual(diff['inputs']['old']['coverage_basis'], 'inferred_from_findings')

    def test_inferred_coverage_is_marked_on_anything_it_resolves(self):
        old = self._v02()
        new = self._v02()
        new['findings'] = [f for f in new['findings']
                           if f['rule_code'] != 'WRAPPER_TARGET_UNDECLARED']
        diff = _diff(old, new)
        self.assertEqual(diff['findings']['resolved'][0]['recheck_basis'],
                         'inferred_from_findings')

    def test_a_02_snapshot_whose_findings_are_missing_is_refused(self):
        """Also stronger than before: a set whose findings array is absent cannot say
        anything about what was re-checked, so it is refused rather than compared."""
        new = self._v02()
        new['findings'] = None
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(d.IncompatibleInput) as ctx:
                d.load_set(_write(Path(td) / 'n', new))
        self.assertIn('findings', str(ctx.exception))


class Reproducibility(unittest.TestCase):
    def test_ids_and_semantics_are_stable_across_rebuilds(self):
        new = _snap()
        new['entities'][0]['stages']['LOADED'] = False
        # The SAME inputs, compared twice: input paths are provenance and belong to the
        # semantics, so re-running over two different temp dirs would not be that test.
        with tempfile.TemporaryDirectory() as td:
            x = _write(Path(td) / 'old', _snap())
            y = _write(Path(td) / 'new', new)
            a = d.compare(d.load_set(x), d.load_set(y))
            b = d.compare(d.load_set(x), d.load_set(y))
        self.assertEqual(d.semantic_view(a), d.semantic_view(b))
        self.assertEqual(a['semantic_digest'], b['semantic_digest'])
        self.assertEqual([c['id'] for c in a['changes']], [c['id'] for c in b['changes']])
        self.assertNotEqual(a['generated_at'], '')
        self.assertEqual(a['volatile_fields'], ['generated_at'])

    def test_change_ids_are_unique_and_validated(self):
        new = _snap()
        new['entities'][0]['stages'].update(LOADED=False, RUNNING=False)
        diff = _diff(_snap(), new)
        ids = [c['id'] for c in diff['changes']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(c['id'].startswith(c['type']) for c in diff['changes']))

    def test_every_change_carries_a_class_and_a_materiality_from_the_vocabulary(self):
        new = _snap()
        new['entities'][0]['stages']['LOADED'] = None
        new['entities'][0]['declared_consumes'] = []
        diff = _diff(_snap(), new)
        self.assertTrue(diff['changes'])
        for c in diff['changes']:
            self.assertIn(c['class'], d.CHANGE_CLASSES)
            self.assertIn(c['materiality'], d.MATERIALITY)


class OfflineAndQuiet(unittest.TestCase):
    """The comparison must not be able to consult the live machine even by accident."""

    def test_the_module_imports_no_process_socket_or_network_library(self):
        forbidden = {'subprocess', 'socket', 'urllib', 'http', 'requests', 'plistlib'}
        for name in ('diff', 'source_of_truth'):
            tree = ast.parse((_root / f'{name}.py').read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split('.')[0], forbidden, name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(node.module.split('.')[0], forbidden, name)

    def test_comparison_runs_with_every_door_to_the_machine_shut(self):
        """Behavioural control: not "no import" but "no call". Every door raises."""
        def boom(*a, **k):
            raise AssertionError('the offline comparison reached a live source')

        new = _snap()
        new['entities'][0]['stages']['LOADED'] = False
        with tempfile.TemporaryDirectory() as td:
            a = _write(Path(td) / 'old', _snap())
            b = _write(Path(td) / 'new', new)
            with patch.object(subprocess, 'run', boom), \
                 patch.object(subprocess, 'Popen', boom), \
                 patch.object(socket, 'socket', boom), \
                 patch.object(socket, 'create_connection', boom):
                old_set, new_set = d.load_set(a), d.load_set(b)
                diff = d.compare(old_set, new_set)
                report = d.changes_markdown(diff)
                smap = sot.build(new_set['snapshot'], source_dir=new_set['dir'])
                sot.validate(smap)
                text = sot.markdown(smap)
        self.assertIn('STAGE_CHANGED', {c['type'] for c in diff['changes']})
        self.assertIn('Cartographer', report)
        self.assertIn('источник', text)

    def test_output_must_be_outside_every_observed_tree(self):
        roots = d.observed_roots(_snap())
        self.assertIn(REPO, roots)
        with self.assertRaises(ValueError):
            d.validate_output(Path(REPO) / 'report', roots)
        with self.assertRaises(ValueError):
            d.validate_output(Path.home() / 'Library/LaunchAgents/report', [])

    def test_observed_roots_include_worktrees_of_both_snapshots(self):
        s = _snap()
        s['repositories'][0]['worktrees'] = [{'worktree': '/wt/one'}]
        self.assertEqual(d.observed_roots(s), [REPO, '/wt/one'])


class NothingLeaksIntoTheReport(unittest.TestCase):
    def test_sentinel_absent_from_all_four_artifacts(self):
        """Comparison reads a WHITELIST of fields. Anything else in the snapshot —
        a raw error, a command line, an unexpected key — must not reach the report."""
        old = _snap()
        new = _snap()
        for s in (old, new):
            s['entities'][0]['undeclared_extra'] = SENTINEL
            s['entities'][0]['installed_paths'][0]['raw_argv'] = [SENTINEL]
            s['code_sync']['detail'] = SENTINEL
            s['processes'] = [{'pid': 1, 'ppid': 0, 'command': SENTINEL}]
            s['raw_stderr'] = SENTINEL
        new['entities'][0]['stages']['LOADED'] = False
        new['entities'][0]['status'] = 'DEGRADED'
        with tempfile.TemporaryDirectory() as td:
            a = _write(Path(td) / 'old', old)
            b = _write(Path(td) / 'new', new)
            old_set, new_set = d.load_set(a), d.load_set(b)
            diff = d.compare(old_set, new_set)
            blobs = {
                'diff.json': json.dumps(diff, ensure_ascii=False),
                'changes.md': d.changes_markdown(diff),
            }
            smap = sot.build(new_set['snapshot'], source_dir=new_set['dir'])
            blobs['source_of_truth.json'] = json.dumps(smap, ensure_ascii=False)
            blobs['source_of_truth.md'] = sot.markdown(smap)
        self.assertTrue(diff['changes'], 'the scene must actually produce a report')
        for name, blob in blobs.items():
            self.assertNotIn(SENTINEL, blob, f'sentinel leaked into {name}')


class OwnerDecisions(unittest.TestCase):
    def test_owner_items_quote_an_existing_rule_and_never_invent_severity(self):
        diff = _diff(_snap(), _snap())
        items = {i['condition']: i for i in diff['owner_decision_candidates']}
        self.assertIn('drift_present', items)
        item = items['drift_present']
        self.assertIn('deployment.md', item['existing_rule'])
        self.assertEqual(item['severity'], 'POLICY_UNDEFINED')
        self.assertIn('NONE', item['action_taken'])

    def test_no_owner_item_without_a_matching_condition(self):
        clean = _snap(findings=[])
        clean['repositories'][0]['drift'].update(changed_or_missing_on_disk=[],
                                                 production_only_tracked=[],
                                                 production_only_untracked=[])
        diff = _diff(clean, clean)
        self.assertEqual(diff['owner_decision_candidates'], [])
        self.assertIn('Ни одно существующее правило', d.changes_markdown(diff))


class Report(unittest.TestCase):
    def test_repeated_identical_findings_are_grouped_not_listed_one_by_one(self):
        old = _snap()
        old['findings'] = old['findings'] + [
            {'id': f'WRAPPER_TARGET_UNDECLARED:com.spa.w{i}:p.plist', 'kind': 'UNKNOWN',
             'rule_code': 'WRAPPER_TARGET_UNDECLARED', 'subject': f'com.spa.w{i}',
             'context': 'p.plist', 'reason': 'dynamic target'} for i in range(77)]
        new = copy.deepcopy(old)
        diff = _diff(old, new)
        text = d.changes_markdown(diff)
        # 78 findings of one rule become one heading plus at most three examples.
        self.assertLessEqual(text.count('WRAPPER_TARGET_UNDECLARED:'), 4)
        self.assertIn('78 — держится с прошлого снимка', text)
        self.assertEqual(len(diff['findings']['persisting']), 79)
        self.assertLess(len(text.splitlines()), 80, 'the report must group, not enumerate')

    def test_no_change_is_reported_as_a_valid_result_not_an_empty_page(self):
        text = d.changes_markdown(_diff(_snap(), _snap()))
        self.assertIn('Существенных изменений нет', text)
        self.assertIn('корректный результат', text)

    def test_the_report_names_what_is_deliberately_not_compared(self):
        text = d.changes_markdown(_diff(_snap(), _snap()))
        self.assertIn('Не сравнивается намеренно', text)
        self.assertIn('ageing is not an SLO crossing', text)


if __name__ == '__main__':
    unittest.main()


class OwnerItemsAreReadFromStagesNotLabels(unittest.TestCase):
    """Measured on the live Mac: all three DEGRADED components were LOADED=True and
    degraded only by a historical non-zero last_exit. Filing those under "installed but
    not loaded" misnames them, and no written rule makes "last outcome non-zero" the
    owner's decision."""

    def _clean_drift(self, s):
        s['repositories'][0]['drift'].update(changed_or_missing_on_disk=[],
                                             production_only_tracked=[],
                                             production_only_untracked=[])
        s['findings'] = [f for f in s['findings'] if not f['rule_code'].startswith('DRIFT_')]
        return s

    def test_degraded_by_exit_code_while_loaded_is_not_an_owner_item(self):
        s = self._clean_drift(_snap())
        s['entities'][0].update(status='DEGRADED', last_exit=1)
        s['entities'][0]['stages'].update(LOADED=True, RUNNING=False)
        s['findings'] = s['findings'] + [
            {'id': 'STATUS_DEGRADED:com.spa.alpha', 'kind': 'DRIFT',
             'rule_code': 'STATUS_DEGRADED', 'subject': 'com.spa.alpha',
             'context': None, 'reason': 'DEGRADED'}]
        diff = _diff(s, s)
        self.assertEqual(diff['owner_decision_candidates'], [])

    def test_installed_and_active_but_not_loaded_is_an_owner_item(self):
        s = self._clean_drift(_snap())
        s['entities'][0].update(status='DEGRADED')
        s['entities'][0]['stages'].update(LOADED=False, RUNNING=False)
        diff = _diff(s, s)
        items = {i['condition']: i for i in diff['owner_decision_candidates']}
        self.assertEqual(list(items), ['installed_but_not_loaded'])
        self.assertEqual(items['installed_but_not_loaded']['examples'], ['com.spa.alpha'])
        self.assertIn('инв. 12', items['installed_but_not_loaded']['existing_rule'])

    def test_a_loaded_unknown_stage_is_not_treated_as_not_loaded(self):
        s = self._clean_drift(_snap())
        s['entities'][0]['stages']['LOADED'] = None
        s['entities'][0]['status'] = 'UNKNOWN'
        diff = _diff(s, s)
        self.assertEqual(diff['owner_decision_candidates'], [])


def _stale(**over):
    """Old snapshot where com.spa.alpha is STALE because its output missed its SLO."""
    s = _snap(**over)
    s['entities'][0]['status'] = 'STALE'
    s['entities'][0]['declared_outputs'][0].update(fresh=False, age_seconds=99999)
    s['findings'] = s['findings'] + [
        {'id': 'STATUS_STALE:com.spa.alpha', 'kind': 'DRIFT', 'rule_code': 'STATUS_STALE',
         'subject': 'com.spa.alpha', 'context': None, 'reason': 'STALE'}]
    return s


def _without(snapshot, rule):
    snapshot['findings'] = [f for f in snapshot['findings'] if f['rule_code'] != rule]
    return snapshot


def _verdicts(diff):
    out = {}
    for bucket in ('resolved', 'not_rechecked', 'applicability_changed'):
        for f in diff['findings'][bucket]:
            out[f['id']] = bucket
    return out


class ResolutionNeedsEvidenceAboutThisSubject(unittest.TestCase):
    """Reproduced defect: blinding one component's artifact metadata removed STATUS_STALE
    from the array while `manifest_readable` stayed true, and the comparison called the
    finding RESOLVED — a claim about a file nobody managed to stat."""

    def test_unobservable_artifact_does_not_resolve_a_stale_finding(self):
        old = _stale()
        new = _without(_snap(), 'STATUS_STALE')
        for o in new['entities'][0]['declared_outputs']:
            o.update(exists=None, fresh=None)      # metadata UNAVAILABLE
        self.assertTrue(new['coverage']['manifest_readable'])
        diff = _diff(old, new)
        self.assertEqual(diff['findings']['resolved'], [])
        why = {f['id']: f['why'] for f in diff['findings']['not_rechecked']}
        self.assertIn('STATUS_STALE:com.spa.alpha', why)
        self.assertIn('artifact metadata was not obtained', why['STATUS_STALE:com.spa.alpha'])

    def test_a_genuinely_fresh_artifact_still_resolves_it(self):
        """The fix must not become a blanket ban on RESOLVED."""
        old = _stale()
        new = _without(_snap(), 'STATUS_STALE')
        diff = _diff(old, new)
        self.assertEqual([f['id'] for f in diff['findings']['resolved']],
                         ['STATUS_STALE:com.spa.alpha'])
        evidence = _pick(diff, 'FINDING_RESOLVED')[0]['evidence']
        self.assertIn('stale_outputs_recovered', evidence['requirements_met'])
        self.assertIn('stale_outputs_recovered',
                      diff['findings']['resolved'][0]['requirements'])

    def test_removing_the_declaration_is_applicability_not_a_fix(self):
        old = _stale()
        new = _without(_snap(), 'STATUS_STALE')
        new['entities'][0]['declared_outputs'] = []
        diff = _diff(old, new)
        self.assertEqual(diff['findings']['resolved'], [])
        self.assertEqual(_verdicts(diff)['STATUS_STALE:com.spa.alpha'], 'applicability_changed')
        change = _pick(diff, 'FINDING_APPLICABILITY_CHANGED')[0]
        self.assertEqual(change['materiality'], 'not_comparable')
        self.assertIn('NOT the condition being fixed', change['note'])

    def test_a_readable_domain_does_not_stand_in_for_a_probed_label(self):
        """domains_complete says the domain answered; it says nothing about whether the
        targeted probe for THIS label answered."""
        old = _snap()
        old['entities'][0].update(status='DEGRADED')
        old['entities'][0]['stages'].update(LOADED=False, RUNNING=False)
        old['findings'] = old['findings'] + [
            {'id': 'STATUS_DEGRADED:com.spa.alpha', 'kind': 'DRIFT',
             'rule_code': 'STATUS_DEGRADED', 'subject': 'com.spa.alpha',
             'context': None, 'reason': 'DEGRADED'}]
        new = _snap()
        new['entities'][0]['domains'] = {'gui/501': None}   # label probe did not answer
        self.assertTrue(new['coverage']['domains_complete'])
        diff = _diff(old, new)
        self.assertEqual(diff['findings']['resolved'], [])
        why = {f['id']: f['why'] for f in diff['findings']['not_rechecked']}
        self.assertIn('a readable domain is not a probed label',
                      why['STATUS_DEGRADED:com.spa.alpha'])

    def test_an_unobserved_stage_does_not_resolve_a_status_finding(self):
        old = _snap()
        old['entities'][0]['status'] = 'UNKNOWN'
        old['findings'] = old['findings'] + [
            {'id': 'STATUS_UNCLASSIFIABLE:com.spa.alpha', 'kind': 'UNKNOWN',
             'rule_code': 'STATUS_UNCLASSIFIABLE', 'subject': 'com.spa.alpha',
             'context': None, 'reason': 'no evidence'}]
        new = _snap()
        new['entities'][0]['stages']['RUNNING'] = None
        diff = _diff(old, new)
        self.assertEqual(diff['findings']['resolved'], [])
        self.assertIn('RUNNING', {f['id']: f['why'] for f in
                                  diff['findings']['not_rechecked']}['STATUS_UNCLASSIFIABLE:com.spa.alpha'])

    def test_a_component_leaving_the_scope_does_not_resolve_its_findings(self):
        diff = _diff(_snap(), _snap(entities=[], findings=[]))
        self.assertEqual(diff['findings']['resolved'], [],
                         'the drift path is still listed, so nothing was fixed either')
        verdicts = _verdicts(diff)
        self.assertEqual(verdicts['WRAPPER_TARGET_UNDECLARED:com.spa.alpha:com.spa.alpha.plist'],
                         'applicability_changed')

    def test_a_component_absent_while_a_source_failed_is_not_rechecked(self):
        new = _snap(entities=[], findings=[])
        new['coverage'].update(installed_scan_complete=False)
        diff = _diff(_snap(), new)
        verdicts = _verdicts(diff)
        self.assertEqual(verdicts['WRAPPER_TARGET_UNDECLARED:com.spa.alpha:com.spa.alpha.plist'],
                         'not_rechecked')

    def test_an_uninstalled_plist_is_applicability_not_a_fix(self):
        new = _without(_snap(), 'WRAPPER_TARGET_UNDECLARED')
        new['entities'][0]['installed_paths'] = []
        diff = _diff(_snap(), new)
        self.assertEqual(diff['findings']['resolved'], [])
        self.assertEqual(_verdicts(diff)['WRAPPER_TARGET_UNDECLARED:com.spa.alpha:com.spa.alpha.plist'],
                         'applicability_changed')

    def test_a_withdrawn_governed_by_reference_is_applicability_not_a_fix(self):
        old = _snap()
        old['entities'][0]['document_references'][0]['outcome'] = 'absent'
        old['findings'] = old['findings'] + [
            {'id': 'DOC_REFERENCE_ABSENT:com.spa.alpha:ADR-066', 'kind': 'DRIFT',
             'rule_code': 'DOC_REFERENCE_ABSENT', 'subject': 'com.spa.alpha',
             'context': 'ADR-066', 'reason': 'absent'}]
        new = _snap()
        new['entities'][0]['declared_governed_by'] = []
        diff = _diff(old, new)
        self.assertEqual(_verdicts(diff)['DOC_REFERENCE_ABSENT:com.spa.alpha:ADR-066'],
                         'applicability_changed')


class RepositoryScopedResolution(unittest.TestCase):
    def _with(self, rule, **over):
        s = _snap(**over)
        s['findings'] = s['findings'] + [
            {'id': f'{rule}:{REPO}', 'kind': 'UNKNOWN', 'rule_code': rule,
             'subject': REPO, 'context': None, 'reason': rule}]
        return s

    def test_remote_unavailable_is_not_resolved_without_a_successful_remote_probe(self):
        """`always` proved nothing about THIS repository having been probed again."""
        old = self._with('REMOTE_UNAVAILABLE')
        new = _snap()
        new['repositories'][0]['remote_origin_main'] = None
        diff = _diff(old, new)
        self.assertEqual(diff['findings']['resolved'], [])
        self.assertIn('live remote was not reached',
                      {f['id']: f['why'] for f in diff['findings']['not_rechecked']}[f'REMOTE_UNAVAILABLE:{REPO}'])

    def test_remote_unavailable_resolves_once_the_remote_answers(self):
        diff = _diff(self._with('REMOTE_UNAVAILABLE'), _snap())
        self.assertEqual([f['id'] for f in diff['findings']['resolved']],
                         [f'REMOTE_UNAVAILABLE:{REPO}'])

    def test_cached_vs_remote_needs_both_sides_known_again(self):
        old = self._with('CACHED_VS_REMOTE_DIVERGED')
        new = _snap()
        new['repositories'][0]['remote_origin_main'] = None
        diff = _diff(old, new)
        self.assertEqual(diff['findings']['resolved'], [])

    def test_a_repository_leaving_the_observed_set_resolves_nothing(self):
        old = self._with('DRIFT_UNMEASURABLE')
        new = _snap(repositories=[], findings=[])
        new['coverage'].update(drift_measurable={}, baseline_sha={})
        diff = _diff(old, new)
        # the entity-scoped finding is legitimately resolvable; the REPOSITORY-scoped
        # ones are not, because that repository was not looked at in the new run
        self.assertEqual([f['id'] for f in diff['findings']['resolved']],
                         ['WRAPPER_TARGET_UNDECLARED:com.spa.alpha:com.spa.alpha.plist'])
        whys = {f['id']: f['why'] for f in diff['findings']['not_rechecked']}
        self.assertIn('outside the observed scope', whys[f'DRIFT_UNMEASURABLE:{REPO}'])
        self.assertIn('outside the observed scope',
                      whys[f'DRIFT_CHANGED_OR_MISSING_ON_DISK:{REPO}:scripts/changed.py'])

    def test_a_narrowed_declared_scope_blocks_every_resolution(self):
        new = _without(_snap(scope='a narrower scope'), 'WRAPPER_TARGET_UNDECLARED')
        diff = _diff(_snap(), new)
        self.assertEqual(diff['findings']['resolved'], [])
        self.assertIn('observation scope of the two runs differs',
                      diff['findings']['not_rechecked'][0]['why'])

    def test_a_domain_finding_needs_that_domain_readable_again(self):
        old = _snap()
        old['findings'] = old['findings'] + [
            {'id': 'DOMAIN_UNREADABLE:launchd_domain:gui/501', 'kind': 'UNKNOWN',
             'rule_code': 'DOMAIN_UNREADABLE', 'subject': 'launchd_domain:gui/501',
             'context': None, 'reason': 'unreadable'}]
        blind = _snap()
        blind['launchd_domains']['gui/501']['readable'] = False
        blind['coverage'].update(domains_complete=False, domains_readable={'gui/501': False})
        self.assertEqual(_diff(old, blind)['findings']['resolved'], [])
        self.assertEqual([f['id'] for f in _diff(old, _snap())['findings']['resolved']],
                         ['DOMAIN_UNREADABLE:launchd_domain:gui/501'])

    def test_an_override_finding_needs_the_domain_read_again(self):
        old = _snap(labels_with_override_but_no_service=['com.spa.ghost'])
        old['findings'] = old['findings'] + [
            {'id': 'ENABLE_OVERRIDE_WITHOUT_SERVICE:com.spa.ghost:gui/501',
             'kind': 'UNKNOWN', 'rule_code': 'ENABLE_OVERRIDE_WITHOUT_SERVICE',
             'subject': 'com.spa.ghost', 'context': 'gui/501', 'reason': 'override'}]
        blind = _snap()
        blind['launchd_domains']['gui/501']['readable'] = False
        blind['coverage'].update(domains_complete=False, domains_readable={'gui/501': False})
        self.assertEqual(_diff(old, blind)['findings']['resolved'], [])
        # the domain is readable again and no longer holds the override
        self.assertEqual([f['id'] for f in _diff(old, _snap())['findings']['resolved']],
                         ['ENABLE_OVERRIDE_WITHOUT_SERVICE:com.spa.ghost:gui/501'])

    def test_a_still_present_override_is_not_resolved(self):
        old = _snap(labels_with_override_but_no_service=['com.spa.ghost'])
        old['findings'] = old['findings'] + [
            {'id': 'ENABLE_OVERRIDE_WITHOUT_SERVICE:com.spa.ghost:gui/501',
             'kind': 'UNKNOWN', 'rule_code': 'ENABLE_OVERRIDE_WITHOUT_SERVICE',
             'subject': 'com.spa.ghost', 'context': 'gui/501', 'reason': 'override'}]
        new = _snap()
        new['launchd_domains']['gui/501']['enable_overrides'] = {'com.spa.ghost': 'enabled'}
        diff = _diff(old, new)
        self.assertEqual(diff['findings']['resolved'], [])
        self.assertIn('still recorded in that domain',
                      diff['findings']['not_rechecked'][0]['why'])


class InputContractIsStrict(unittest.TestCase):
    """Reproduced defect: `{"schema_version": "…/0.3", "entities": []}` was accepted and
    compared, producing a normal report with material changes out of a truncated file."""

    def _reject(self, snapshot, fragment):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'x'
            p.mkdir()
            (p / 'snapshot.json').write_text(json.dumps(snapshot))
            with self.assertRaises(d.IncompatibleInput) as ctx:
                d.load_set(p)
        self.assertIn(fragment, str(ctx.exception))

    def test_the_reported_truncated_snapshot_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'x'
            p.mkdir()
            (p / 'snapshot.json').write_text(
                '{"schema_version":"cartographer.snapshot/0.3","entities":[]}')
            with self.assertRaises(d.IncompatibleInput) as ctx:
                d.load_set(p)
        self.assertIn('required field', str(ctx.exception))

    def test_a_03_snapshot_without_coverage_is_refused_not_inferred(self):
        s = _snap()
        del s['coverage']
        self._reject(s, 'coverage')

    def test_a_03_coverage_missing_one_key_is_refused(self):
        s = _snap()
        del s['coverage']['ps_ok']
        self._reject(s, 'must RECORD')

    def test_wrong_types_are_refused(self):
        s = _snap()
        s['entities'] = {}
        self._reject(s, 'must be list')
        s = _snap()
        s['coverage']['ps_ok'] = 'yes'
        self._reject(s, 'coverage.ps_ok')
        s = _snap()
        s['entities'][0]['stages']['LOADED'] = 'maybe'
        self._reject(s, 'stages.LOADED')

    def test_duplicate_entity_and_finding_ids_are_refused(self):
        s = _snap()
        s['entities'] = s['entities'] + [dict(s['entities'][0])]
        self._reject(s, 'duplicate entity id')
        s = _snap()
        s['findings'] = s['findings'] + [dict(s['findings'][0])]
        self._reject(s, 'duplicate finding id')

    def test_an_unknown_status_or_missing_stage_is_refused(self):
        s = _snap()
        s['entities'][0]['status'] = 'FINE'
        self._reject(s, 'unknown status')
        s = _snap()
        del s['entities'][0]['stages']['HEALTHY']
        self._reject(s, 'stages lacks')

    def test_a_malformed_repository_is_refused(self):
        s = _snap()
        del s['repositories'][0]['drift']
        self._reject(s, 'drift')
        s = _snap()
        del s['repositories'][0]['drift']['production_only_tracked']
        self._reject(s, 'production_only_tracked')

    def test_a_02_snapshot_carrying_a_coverage_block_is_refused(self):
        s = _snap(schema_version='cartographer.snapshot/0.2')
        del s['reference_documents']
        self._reject(s, 'must not carry a coverage block')

    def test_a_legitimately_empty_run_with_full_coverage_is_accepted(self):
        """An empty result and a truncated file must not look alike."""
        empty = _snap(entities=[], findings=[], repositories=[], processes=[])
        empty['coverage'].update(drift_measurable={}, baseline_sha={})
        empty['labels_with_override_but_no_service'] = []
        with tempfile.TemporaryDirectory() as td:
            a = _write(Path(td) / 'o', empty)
            b = _write(Path(td) / 'n', empty)
            diff = d.compare(d.load_set(a), d.load_set(b))
        self.assertEqual(diff['changes'], [])
        self.assertEqual(diff['component_counts'], {'old': 0, 'new': 0})

    def test_the_contract_accepts_an_accepted_shape_and_refuses_the_defective_one(self):
        """The contract must accept the artifact shape this phase was accepted on and
        refuse exactly the shape that carried the duplicate-id defect.

        Previously this scanned ~/studio-os-snapshots and therefore had a verdict that
        depended on one machine's local files: on any other checkout it failed for a
        reason unrelated to the behaviour under test. The two SHAPES are what matters,
        so the test now owns them.
        """
        accepted = _snap(schema_version='cartographer.snapshot/0.2')
        del accepted['coverage']
        del accepted['reference_documents']

        pre_round_two = copy.deepcopy(accepted)
        for finding in pre_round_two['findings']:
            finding.pop('rule_code', None)
        pre_round_two['findings'] = [dict(pre_round_two['findings'][0]),
                                     dict(pre_round_two['findings'][0])]

        with tempfile.TemporaryDirectory() as td:
            good = _write(Path(td) / 'accepted-shape', accepted)
            bad = _write(Path(td) / 'pre-round-2-shape', pre_round_two)
            loaded = d.load_set(good)
            self.assertEqual(loaded['schema_version'], 'cartographer.snapshot/0.2')
            self.assertEqual(loaded['coverage']['basis'], 'inferred_from_findings')
            with self.assertRaises(d.IncompatibleInput) as ctx:
                d.load_set(bad)
        message = str(ctx.exception)
        self.assertTrue('rule_code' in message or 'duplicate finding id' in message,
                        message)

    def test_a_named_sample_directory_is_checked_when_one_is_given(self):
        """Opt-in live check: if a caller names a directory of stored sets, every set in
        it must still load. Absent the variable the test does not invent a location."""
        sample = os.environ.get('CARTOGRAPHER_SAMPLE_SETS')
        if not sample:
            self.skipTest('CARTOGRAPHER_SAMPLE_SETS не задан — живой набор не выдумывается')
        checked = 0
        for path in sorted(Path(sample).iterdir()):
            if not (path / 'snapshot.json').is_file():
                continue
            d.load_set(path)
            checked += 1
        self.assertGreater(checked, 0, f'в {sample} нет ни одного набора со snapshot.json')


def _two_outputs(first_fresh, second_fresh, **first_over):
    """Component declaring two outputs, so partial recovery can be expressed."""
    s = _snap()
    ent = s['entities'][0]
    base = dict(ent['declared_outputs'][0])
    first = {**base, 'relpath': 'data/first.json', 'fresh': first_fresh,
             'exists': True, 'slo_hours': 3, **first_over}
    second = {**base, 'relpath': 'data/second.json', 'fresh': second_fresh,
              'exists': True, 'slo_hours': 3}
    ent['declared_outputs'] = [first, second]
    return s


def _was_stale(**over):
    """Old snapshot: data/first.json is past its SLO, data/second.json is fine."""
    s = _two_outputs(False, True, **over)
    s['entities'][0]['status'] = 'STALE'
    s['findings'] = s['findings'] + [
        {'id': 'STATUS_STALE:com.spa.alpha', 'kind': 'DRIFT', 'rule_code': 'STATUS_STALE',
         'subject': 'com.spa.alpha', 'context': None, 'reason': 'STALE'}]
    return s


def _stale_verdict(old, new):
    diff = _diff(old, new)
    for bucket in ('resolved', 'not_rechecked', 'applicability_changed'):
        for f in diff['findings'][bucket]:
            if f['id'] == 'STATUS_STALE:com.spa.alpha':
                return bucket, f.get('why') or '', diff
    return None, '', diff


class StaleResolutionIsPerOutput(unittest.TestCase):
    """ARB round 3, reproduced on the accepted live snapshot: three different events made
    STATUS_STALE disappear and all three were announced as RESOLVED — the overdue file
    vanishing, the output being withdrawn from the declaration, and its SLO being removed.
    None of them is evidence that the overdue artifact recovered.

    The rule's cause is now reconstructed from the OLD snapshot — the specific outputs
    that were `fresh: false` — and each is matched by its stable relpath."""

    def test_the_overdue_file_disappearing_is_not_a_recovery(self):
        new = _without(_two_outputs(None, True, exists=False), 'STATUS_STALE')
        verdict, why, _ = _stale_verdict(_was_stale(), new)
        self.assertEqual(verdict, 'not_rechecked')
        self.assertIn('data/first.json', why)
        self.assertIn('now ABSENT', why)
        self.assertIn('not a recovery', why)

    def test_withdrawing_the_overdue_output_is_applicability_not_a_recovery(self):
        new = _without(_snap(), 'STATUS_STALE')
        new['entities'][0]['declared_outputs'] = [
            o for o in _two_outputs(True, True)['entities'][0]['declared_outputs']
            if o['relpath'] != 'data/first.json']
        verdict, why, _ = _stale_verdict(_was_stale(), new)
        self.assertEqual(verdict, 'applicability_changed')
        self.assertIn('no longer declared as an output', why)

    def test_removing_the_slo_of_the_overdue_output_is_not_a_recovery(self):
        new = _without(_two_outputs(None, True, slo_hours=None), 'STATUS_STALE')
        verdict, why, _ = _stale_verdict(_was_stale(), new)
        self.assertEqual(verdict, 'applicability_changed')
        self.assertIn('no longer carries the same SLO', why)
        self.assertIn('not comparable', why)

    def test_changing_the_slo_of_the_overdue_output_is_not_a_recovery(self):
        new = _without(_two_outputs(True, True, slo_hours=999), 'STATUS_STALE')
        verdict, why, _ = _stale_verdict(_was_stale(), new)
        self.assertEqual(verdict, 'applicability_changed')
        self.assertIn('3 → 999', why)

    def test_positive_control_a_real_recovery_still_resolves(self):
        new = _without(_two_outputs(True, True), 'STATUS_STALE')
        verdict, _, diff = _stale_verdict(_was_stale(), new)
        self.assertEqual(verdict, 'resolved')
        self.assertIn('stale_outputs_recovered',
                      diff['findings']['resolved'][0]['requirements'])

    def test_two_overdue_outputs_with_only_one_recovered_are_not_resolved(self):
        old = _was_stale()
        old['entities'][0]['declared_outputs'][1]['fresh'] = False   # both were overdue
        new = _without(_two_outputs(True, False), 'STATUS_STALE')
        verdict, why, _ = _stale_verdict(old, new)
        self.assertEqual(verdict, 'not_rechecked')
        self.assertIn('data/second.json', why)

    def test_partial_evidence_never_resolves_the_aggregate_finding(self):
        """One overdue output recovered, the other's metadata was not obtained."""
        old = _was_stale()
        old['entities'][0]['declared_outputs'][1]['fresh'] = False
        new = _without(_two_outputs(True, None), 'STATUS_STALE')
        new['entities'][0]['declared_outputs'][1]['exists'] = None
        verdict, why, _ = _stale_verdict(old, new)
        self.assertEqual(verdict, 'not_rechecked')
        self.assertIn('metadata was not obtained', why)

    def test_missing_evidence_outranks_lost_applicability(self):
        """One overdue output withdrawn, another still unobserved: not knowing is weaker
        than knowing the rule moved, so the verdict must be NOT_RECHECKED."""
        old = _was_stale()
        old['entities'][0]['declared_outputs'][1]['fresh'] = False
        new = _without(_two_outputs(True, None), 'STATUS_STALE')
        new['entities'][0]['declared_outputs'] = [new['entities'][0]['declared_outputs'][1]]
        new['entities'][0]['declared_outputs'][0]['exists'] = None
        verdict, why, _ = _stale_verdict(old, new)
        self.assertEqual(verdict, 'not_rechecked')

    def test_an_unobserved_neighbour_blocks_resolution(self):
        """The overdue output recovered, but a neighbour that declares an SLO was not
        observed: the ABSENCE of a stale condition is then not established."""
        new = _without(_two_outputs(True, None), 'STATUS_STALE')
        new['entities'][0]['declared_outputs'][1]['exists'] = None
        verdict, why, _ = _stale_verdict(_was_stale(), new)
        self.assertEqual(verdict, 'not_rechecked')
        self.assertIn('staleness is undetermined', why)
        self.assertIn('data/second.json', why)

    def test_a_neighbour_that_became_stale_blocks_resolution(self):
        new = _without(_two_outputs(True, False), 'STATUS_STALE')
        verdict, why, _ = _stale_verdict(_was_stale(), new)
        self.assertEqual(verdict, 'not_rechecked')
        self.assertIn('stale condition persists', why)

    def test_an_old_snapshot_that_does_not_name_the_overdue_output_is_not_rechecked(self):
        """If the original cause cannot be reconstructed from stored data, the verdict is
        UNKNOWN rather than a guess."""
        old = _was_stale()
        for o in old['entities'][0]['declared_outputs']:
            o['fresh'] = None            # which output was overdue is no longer recorded
        new = _without(_two_outputs(True, True), 'STATUS_STALE')
        verdict, why, _ = _stale_verdict(old, new)
        self.assertEqual(verdict, 'not_rechecked')
        self.assertIn('does not record WHICH declared output', why)

    def test_a_component_absent_from_the_old_snapshot_is_not_rechecked(self):
        old = _was_stale()
        new = _without(_two_outputs(True, True), 'STATUS_STALE')
        old_without_entity = copy.deepcopy(old)
        old_without_entity['entities'] = []
        verdict, why, _ = _stale_verdict(old_without_entity, new)
        self.assertIn(verdict, ('not_rechecked', None))


class GoingBlindIsNotAStateChange(unittest.TestCase):
    """Found by scenario 4 of the Director OS package: one launchd domain stopping to
    answer turned every per-label verdict null, and the comparison reported 101 MATERIAL
    changes. Going blind is loss of observation, not a change of state."""

    def _blinded(self):
        new = _snap()
        new['launchd_domains']['gui/501']['readable'] = False
        new['coverage'].update(domains_complete=False, domains_readable={'gui/501': False})
        new['entities'][0]['domains'] = {'gui/501': None}
        new['entities'][0]['stages']['LOADED'] = None
        new['entities'][0]['status'] = 'UNKNOWN'
        return new

    def test_a_verdict_turning_null_is_observation_quality_not_material(self):
        diff = _diff(_snap(), self._blinded())
        self.assertEqual(_types(diff, 'material'), set(), diff['changes'])
        lost = _pick(diff, 'DOMAIN_VERDICT_OBSERVATION_LOST', 'domains.gui/501')
        self.assertEqual(len(lost), 1)
        self.assertEqual(lost[0]['materiality'], 'observation_quality')
        self.assertIn('знание потеряно', lost[0]['note'])
        self.assertEqual(_pick(diff, 'OBSERVED_FIELD_CHANGED', 'domains'), [])

    def test_a_domain_dropping_out_of_the_map_is_also_a_loss(self):
        new = _snap()
        new['entities'][0]['domains'] = {}
        diff = _diff(_snap(), new)
        self.assertEqual(_types(diff, 'material'), set())
        self.assertEqual(len(_pick(diff, 'DOMAIN_VERDICT_OBSERVATION_LOST')), 1)

    def test_a_verdict_flipping_between_known_values_is_still_material(self):
        new = _snap()
        new['entities'][0]['domains'] = {'gui/501': False}
        new['entities'][0]['stages']['LOADED'] = False
        new['entities'][0]['status'] = 'DEGRADED'
        diff = _diff(_snap(), new)
        flipped = _pick(diff, 'DOMAIN_VERDICT_CHANGED', 'domains.gui/501')
        self.assertEqual(len(flipped), 1)
        self.assertEqual(flipped[0]['materiality'], 'material')
        self.assertEqual((flipped[0]['old'], flipped[0]['new']), (True, False))


class TheLaunchdGuardResolvesBothSides(unittest.TestCase):
    """Reproduced: resolving only the output made the guard useless wherever the home
    directory is a symlink — the write into the launchd directory was ALLOWED. The
    forbidden location is the real directory, so both sides must be resolved."""

    def _scene(self, td):
        real = Path(td) / 'realhome'
        (real / 'Library/LaunchAgents').mkdir(parents=True)
        link = Path(td) / 'homelink'
        link.symlink_to(real)
        return real, link

    def test_a_symlinked_home_cannot_smuggle_an_output_into_launchd(self):
        with tempfile.TemporaryDirectory() as td:
            real, link = self._scene(td)
            with patch.object(Path, 'home', staticmethod(lambda: link)):
                with self.assertRaises(ValueError):
                    d.validate_output(link / 'Library/LaunchAgents' / 'out', [])
                with self.assertRaises(ValueError):
                    d.validate_output(real / 'Library/LaunchAgents' / 'out', [])

    def test_a_path_outside_launchd_is_still_allowed_under_a_symlinked_home(self):
        with tempfile.TemporaryDirectory() as td:
            real, link = self._scene(td)
            (real / 'reports').mkdir()
            with patch.object(Path, 'home', staticmethod(lambda: link)):
                resolved = d.validate_output(link / 'reports' / 'out', [])
        self.assertTrue(str(resolved).endswith('reports/out'))

    def test_the_snapshot_guard_behaves_the_same(self):
        snapshot_mod = _load('snapshot')
        with tempfile.TemporaryDirectory() as td:
            real, link = self._scene(td)
            with patch.object(Path, 'home', staticmethod(lambda: link)):
                with self.assertRaises(ValueError):
                    snapshot_mod.validate_output(link / 'Library/LaunchAgents' / 'o', [])
