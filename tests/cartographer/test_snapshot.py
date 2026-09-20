import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('snapshot', Path(__file__).parents[2] / 'scripts/cartographer/snapshot.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

SECRET = 'ghp_SENTINEL_NEVER_IN_OUTPUT_0123456789'


def _dom(services=(), overrides=None, readable=True, error=None):
    """One launchd domain in the shape launchd_domains() now returns."""
    return {'readable': readable, 'error': error,
            'services': sorted(services) if readable else None,
            'service_detail': {s: {'pid': None, 'status': 0} for s in services} if readable else None,
            'enable_overrides': dict(overrides or {}) if readable else None,
            'method': 'test'}


def _probe(domains):
    """Targeted service_target() stub consistent with the given domains."""
    def probe(domain, label):
        d = domains.get(domain)
        if d is None or not d['readable']:
            return 'unknown'
        return 'present' if label in (d['services'] or ()) else 'absent'
    return probe


def _collect(root, domains, listed=None, real_git=False, **extra):
    """collect() with launchd and ps stubbed. ``real_git=True`` keeps the real `run`,
    which git needs — stubbing it makes drift unmeasurable and silently empty."""
    from contextlib import ExitStack
    from unittest.mock import patch as _p
    with ExitStack() as st:
        st.enter_context(_p.object(m, 'launchd_domains', return_value=domains))
        st.enter_context(_p.object(m, 'service_target', side_effect=_probe(domains)))
        st.enter_context(_p.object(m, 'launchctl_list', return_value=(dict(listed or {}), True)))
        st.enter_context(_p.object(m.urllib.request, 'build_opener', side_effect=OSError))
        if not real_git:
            st.enter_context(_p.object(m, 'run', return_value=extra.get('run_out')))
            st.enter_context(_p.object(m, '_exec', return_value={
                'ok': True, 'out': extra.get('ps_out', ''), 'rc': 0, 'error': None}))
        return m.collect(root)



def _repo(root):
    """Minimal production-shaped tree: manifest, registry, sync status."""
    root.mkdir(parents=True, exist_ok=True)
    (root / 'data').mkdir(exist_ok=True)
    (root / 'architecture').mkdir(exist_ok=True)
    (root / 'architecture/manifest.json').write_text('{"agents": []}')
    (root / 'data/agent_registry.json').write_text('{"agents": []}')
    (root / 'data/code_sync_status.json').write_text('{"result":"IN_SYNC"}')
    return root


class Classification(unittest.TestCase):
    def test_scheduled_idle_not_dead(self):
        s = dict.fromkeys(m.STAGES); s.update(LOADED=True, INSTALLED=True, RUNNING=False)
        self.assertEqual(m.classify(s, 'active', 0), 'LIVE')
        self.assertIsNone(s['HEALTHY'])

    def test_orphan_and_stale_and_duplicate(self):
        s = dict.fromkeys(m.STAGES); s.update(LOADED=True, INSTALLED=False, RUNNING=True)
        self.assertEqual(m.classify(s), 'ORPHANED')
        s['INSTALLED'] = True
        self.assertEqual(m.classify(s, outputs=[{'fresh': False}]), 'STALE')
        self.assertEqual(m.classify(s, duplicate=True), 'DUPLICATED')

    def test_missing_probe_never_live(self):
        self.assertEqual(m.classify(dict.fromkeys(m.STAGES)), 'UNKNOWN')

    def test_installed_not_loaded_degrades_only_when_loaded_is_known(self):
        """LOADED=None (a domain was unreadable) must NOT yield DEGRADED — that would be
        a claim about a domain we could not read."""
        unknown = dict.fromkeys(m.STAGES); unknown.update(INSTALLED=True, LOADED=None)
        self.assertEqual(m.classify(unknown, 'active'), 'UNKNOWN')
        known = dict.fromkeys(m.STAGES); known.update(INSTALLED=True, LOADED=False)
        self.assertEqual(m.classify(known, 'active'), 'DEGRADED')

    def test_running_is_checked_before_historical_exit(self):
        """A live always-on server whose PREVIOUS run exited -15 is LIVE, not DEGRADED."""
        s = dict.fromkeys(m.STAGES); s.update(LOADED=True, INSTALLED=True, RUNNING=True)
        self.assertEqual(m.classify(s, 'active', last_exit=-15), 'LIVE')


class Probes(unittest.TestCase):
    def test_exec_reports_error_class_not_stderr(self):
        r = m._exec(['python3', '-c', f'import sys; print("{SECRET}", file=sys.stderr); sys.exit(1)'])
        self.assertFalse(r['ok'])
        self.assertEqual(r['error'], 'exit_nonzero')
        self.assertNotIn(SECRET, json.dumps(r))

    def test_stderr_not_exposed_through_run(self):
        self.assertIsNone(m.run(['python3', '-c', f'import sys; print("{SECRET}", file=sys.stderr); sys.exit(1)']))

    def test_missing_binary_is_oserror_not_silence(self):
        r = m._exec(['/nonexistent/binary/xyz'])
        self.assertFalse(r['ok'])
        self.assertEqual(r['error'], 'oserror')


class Domains(unittest.TestCase):
    """LOADED must rest on a registered SERVICE, not on an enable/disable setting."""

    def test_enable_override_without_service_is_not_loaded(self):
        """The defect this replaces: `com.spa.httpserver` appears in the `disabled
        services` block as `=> enabled` while `launchctl print <domain>/<label>` answers
        "could not find service". A regex over the whole output called that LOADED and
        then ORPHANED."""
        with tempfile.TemporaryDirectory() as td:
            root = _repo(Path(td))
            domains = {'gui/501': _dom(services=[], overrides={'com.spa.ghost': 'enabled'}),
                       'system': _dom(services=[])}
            s = _collect(root, domains)
        ents = {e['id']: e for e in s['entities']}
        self.assertIn('com.spa.ghost', ents)
        self.assertFalse(ents['com.spa.ghost']['stages']['LOADED'])
        self.assertNotEqual(ents['com.spa.ghost']['status'], 'ORPHANED')
        self.assertEqual(s['labels_with_override_but_no_service'], ['com.spa.ghost'])
        rules = {f['rule_code'] for f in s['findings']}
        self.assertIn('ENABLE_OVERRIDE_WITHOUT_SERVICE', rules)
        self.assertNotIn('LOADED_WITHOUT_INSTALLED_PLIST', rules)

    def test_a_genuinely_registered_service_is_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            root = _repo(Path(td))
            domains = {'gui/501': _dom(services=['com.spa.real']), 'system': _dom()}
            s = _collect(root, domains, listed={'com.spa.real': {'pid': None, 'last_exit': 0}})
        ent = {e['id']: e for e in s['entities']}['com.spa.real']
        self.assertTrue(ent['stages']['LOADED'])
        self.assertEqual(ent['domains'], {'gui/501': True, 'system': False})
        self.assertIn('targeted', ent['evidence']['LOADED'])

    def test_unreadable_domain_keeps_loaded_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            root = _repo(Path(td))
            domains = {'gui/501': _dom(services=[]),
                       'system': _dom(readable=False, error='exit_nonzero')}
            s = _collect(root, domains, listed={'com.spa.probe': {'pid': None, 'last_exit': None}})
        ent = {e['id']: e for e in s['entities']}['com.spa.probe']
        self.assertIsNone(ent['stages']['LOADED'])
        self.assertIn('DOMAIN_UNREADABLE', {f['rule_code'] for f in s['findings']})

    def test_absence_in_user_domain_is_not_absence_system_wide(self):
        with tempfile.TemporaryDirectory() as td:
            root = _repo(Path(td))
            domains = {'gui/501': _dom(services=[]), 'system': _dom(services=['com.spa.sys'])}
            s = _collect(root, domains)
        ent = {e['id']: e for e in s['entities']}['com.spa.sys']
        self.assertTrue(ent['stages']['LOADED'])

    def test_domain_print_parser_separates_the_two_blocks(self):
        text = ('\tservices = {\n'
                '\t\t       0      0 \tcom.spa.alpha\n'
                '\t\t       -      1 \tcom.spa.beta\n'
                '\t}\n'
                '\tdisabled services = {\n'
                '\t\t"com.spa.ghost" => enabled\n'
                '\t\t"com.spa.beta" => disabled\n'
                '\t}\n')
        services, overrides = m.parse_domain_print(text)
        self.assertEqual(sorted(services), ['com.spa.alpha', 'com.spa.beta'])
        self.assertNotIn('com.spa.ghost', services)
        self.assertEqual(overrides, {'com.spa.ghost': 'enabled', 'com.spa.beta': 'disabled'})


class EntrypointSemantics(unittest.TestCase):
    """The launch FORM is parsed; a later argument never stands in for a missing script."""

    def test_missing_script_is_not_replaced_by_a_later_argument(self):
        """Reported defect, reproduced: argv ["/bin/bash", "/nonexistent/agent.sh", "/tmp"]
        used to yield /tmp as the entrypoint, because the old code took the first argv
        element that happened to exist."""
        ep = m.entrypoint_from_plist({'ProgramArguments': ['/bin/bash', '/nonexistent/agent.sh', '/tmp']})
        self.assertEqual(ep['target_kind'], 'script')
        self.assertEqual(ep['target'], '/nonexistent/agent.sh')
        self.assertFalse(ep['target_exists'])
        self.assertNotEqual(ep['target'], '/tmp')
        self.assertIn('NOT substituted', ep['unknown_reason'])

    def test_inline_command_form_is_unknown_and_never_stored(self):
        ep = m.entrypoint_from_plist({'ProgramArguments': ['/bin/bash', '-c', f'curl {SECRET}', '/tmp']})
        self.assertIsNone(ep['target_kind'])
        self.assertIsNone(ep['target'])
        self.assertIn('-c', ep['unknown_reason'])
        self.assertNotIn(SECRET, json.dumps(ep))

    def test_env_form_is_unsupported_not_guessed(self):
        ep = m.entrypoint_from_plist({'ProgramArguments': ['/usr/bin/env', 'TOKEN=x', '/bin/sh', '/tmp']})
        self.assertIsNone(ep['target_kind'])
        self.assertIn('env', ep['unknown_reason'])
        self.assertNotIn('/tmp', json.dumps(ep))

    def test_python_module_form_is_a_module_not_a_path(self):
        ep = m.entrypoint_from_plist({'ProgramArguments': ['/usr/bin/python3', '-m', 'spa_core.monitoring.x', '--run']})
        self.assertEqual(ep['target_kind'], 'module')
        self.assertEqual(ep['target'], 'spa_core.monitoring.x')
        self.assertIsNone(ep['target_exists'])

    def test_relative_script_is_resolved_against_working_directory(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / 'agent.sh').write_text('#!/bin/bash\n')
            ep = m.entrypoint_from_plist({'ProgramArguments': ['/bin/bash', 'agent.sh']}, td)
        self.assertEqual(ep['target'], str(Path(td) / 'agent.sh'))
        self.assertTrue(ep['target_exists'])

    def test_direct_executable_form(self):
        ep = m.entrypoint_from_plist({'ProgramArguments': ['/usr/bin/true', '--flag']})
        self.assertEqual(ep['target_kind'], 'executable')
        self.assertEqual(ep['target'], '/usr/bin/true')
        self.assertEqual(ep['argument_count'], 2)

    def test_program_key_form(self):
        ep = m.entrypoint_from_plist({'Program': '/usr/bin/true'})
        self.assertEqual(ep['target_kind'], 'executable')
        self.assertTrue(ep['target_exists'])

    def test_environment_values_never_collected(self):
        keys = m.plist_env_keys({'EnvironmentVariables': {'GITHUB_PAT_SPA': SECRET, 'HOME': '/x'}})
        self.assertEqual(keys, ['GITHUB_PAT_SPA', 'HOME'])
        self.assertNotIn(SECRET, json.dumps(keys))

    def test_installed_plist_with_secret_argv_does_not_leak_into_collect(self):
        with tempfile.TemporaryDirectory() as td:
            root = _repo(Path(td) / 'repo')
            script = root / 'runner.sh'; script.write_text('#!/bin/bash\n')
            plist = {'Label': 'com.spa.secretive',
                     'ProgramArguments': ['/bin/bash', str(script), SECRET],
                     'EnvironmentVariables': {'TOKEN': SECRET}}
            pdir = Path(td) / 'Library/LaunchAgents'; pdir.mkdir(parents=True)
            (pdir / 'com.spa.secretive.plist').write_bytes(plistlib.dumps(plist))
            with patch.object(m.Path, 'home', staticmethod(lambda: Path(td))):
                s = _collect(root, {'gui/501': _dom(services=['com.spa.secretive'])})
        blob = json.dumps(s, ensure_ascii=False)
        self.assertNotIn(SECRET, blob)
        ent = {e['id']: e for e in s['entities']}['com.spa.secretive']
        self.assertEqual(ent['installed_paths'][0]['environment_keys'], ['TOKEN'])
        self.assertEqual(ent['installed_paths'][0]['entrypoint']['target'], str(script))
        self.assertEqual(ent['installed_paths'][0]['entrypoint']['argument_count'], 3)


class DeclaredOutputs(unittest.TestCase):
    def test_symlink_escaping_declared_output_is_omitted_and_named(self):
        with tempfile.TemporaryDirectory() as td:
            outside = Path(td) / 'outside'; outside.mkdir(); (outside / 'secret.json').write_text('{}')
            root = _repo(Path(td) / 'repo'); (root / 'data').mkdir(exist_ok=True)
            (root / 'data/escape.json').symlink_to(outside / 'secret.json')
            (root / 'architecture/manifest.json').write_text(json.dumps(
                {'agents': [{'label': 'com.spa.esc', 'intent': 'active',
                             'produces': [{'artifact': 'data/escape.json', 'slo_hours': 1}]}]}))
            s = _collect(root, {'gui/501': _dom()})
        ent = {e['id']: e for e in s['entities']}['com.spa.esc']
        self.assertEqual(ent['declared_outputs'], [])
        self.assertTrue(any('symlink escape' in f['reason'] for f in s['findings']))

    def test_fresh_artifact_never_claims_a_producer(self):
        with tempfile.TemporaryDirectory() as td:
            root = _repo(Path(td))
            (root / 'data/out.json').write_text('{}')
            (root / 'architecture/manifest.json').write_text(json.dumps(
                {'agents': [{'label': 'com.spa.p', 'intent': 'active',
                             'produces': [{'artifact': 'data/out.json', 'slo_hours': 99}]}]}))
            s = _collect(root, {'gui/501': _dom()})
        out = {e['id']: e for e in s['entities']}['com.spa.p']['declared_outputs'][0]
        self.assertTrue(out['fresh'])
        self.assertEqual(out['producer_attribution'], 'UNKNOWN')
        self.assertIsNone({e['id']: e for e in s['entities']}['com.spa.p']['stages']['PRODUCING_OUTPUT'])


class Drift(unittest.TestCase):
    def test_three_populations_detected_without_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            def g(*a): return subprocess.check_output(['git', *a], cwd=p, stderr=subprocess.DEVNULL)
            g('init'); g('config', 'user.name', 'Test'); g('config', 'user.email', 'test@example.invalid')
            (p / 'scripts').mkdir()
            for n in ['retired.py', 'active.py']: (p / 'scripts' / n).write_text('old\n')
            g('add', '.'); g('commit', '-m', 'base')
            old = g('rev-parse', 'HEAD').decode().strip()
            g('rm', 'scripts/retired.py'); g('commit', '-m', 'retire')
            g('update-ref', 'refs/remotes/origin/main', 'HEAD'); g('checkout', '--detach', old)
            (p / 'scripts/active.py').write_text('changed\n'); (p / 'scripts/local.py').write_text('local\n')
            before = (p / '.git/index').read_bytes()
            r = m.drift(p)
            self.assertEqual(r['production_only_tracked'], ['scripts/retired.py'])
            self.assertEqual(r['production_only_untracked'], ['scripts/local.py'])
            self.assertEqual(r['changed_or_missing_on_disk'], ['scripts/active.py'])
            self.assertEqual(before, (p / '.git/index').read_bytes())
            self.assertTrue((p / 'scripts/retired.py').exists())

    def test_basis_is_named_not_implied(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            def g(*a): return subprocess.check_output(['git', *a], cwd=p, stderr=subprocess.DEVNULL)
            g('init'); g('config', 'user.name', 'T'); g('config', 'user.email', 't@e.invalid')
            (p / 'scripts').mkdir(); (p / 'scripts/a.py').write_text('x\n')
            g('add', '.'); g('commit', '-m', 'b'); g('update-ref', 'refs/remotes/origin/main', 'HEAD')
            r = m.drift(p)
        self.assertEqual(r['basis'], 'pinned_commit')
        self.assertIn('resolved ONCE', r['reference_note'])
        self.assertIn('NOT a live server query', r['reference_note'])
        self.assertRegex(r['reference_sha'], r'^[0-9a-f]{40}$')
        self.assertIn('not evidence of retirement', r['production_only_note'])

    def test_failure_is_unknown_not_empty(self):
        with patch.object(m, 'git', return_value=None):
            self.assertIsNone(m.drift(Path('/missing')))


class OutputGuards(unittest.TestCase):
    def test_output_must_be_outside_repos_and_launchd(self):
        with self.assertRaises(ValueError): m.validate_output(Path('/tmp/prod/out'), [Path('/tmp/prod')])
        with self.assertRaises(ValueError): m.validate_output(Path.home() / 'Library/LaunchAgents/out', [])
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); (base / 'prod').mkdir(); (base / 'alias').symlink_to(base / 'prod')
            with self.assertRaises(ValueError): m.validate_output(base / 'alias/out', [base / 'prod'])


class Contract(unittest.TestCase):
    def test_schema_and_bases_declared(self):
        with tempfile.TemporaryDirectory() as td:
            root = _repo(Path(td))
            s = _collect(root, {'gui/501': _dom()})
        self.assertEqual(s['schema_version'], m.SNAPSHOT_SCHEMA)
        self.assertEqual(s['evidence_bases'], list(m.BASES))
        self.assertFalse(s['atomic_observation'])
        self.assertTrue(s['derived_state'])

    def test_runtime_detail_is_not_copied_verbatim(self):
        with tempfile.TemporaryDirectory() as td:
            root = _repo(Path(td))
            (root / 'data/code_sync_status.json').write_text(
                json.dumps({'result': 'IN_SYNC', 'detail': SECRET, 'api_key': SECRET}))
            s = _collect(root, {'gui/501': _dom()})
        self.assertNotIn(SECRET, json.dumps(s, ensure_ascii=False))

    def test_last_exit_basis_is_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            root = _repo(Path(td))
            s = _collect(root, {'gui/501': _dom(services=['com.spa.z'])},
                             listed={'com.spa.z': {'pid': None, 'last_exit': 1}})
        ent = {e['id']: e for e in s['entities']}['com.spa.z']
        self.assertIn('historical', ent['last_exit_basis'])


if __name__ == '__main__':
    unittest.main()


def _git_repo_with_docs(root, files):
    """Real git repo with docs committed and origin/main pinned to that commit."""
    root.mkdir(parents=True, exist_ok=True)
    def g(*a): return subprocess.check_output(['git', *a], cwd=root, stderr=subprocess.DEVNULL)
    g('init'); g('config', 'user.name', 'T'); g('config', 'user.email', 't@e.invalid')
    for rel in files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('doc\n')
    g('add', '.'); g('commit', '-m', 'docs'); g('update-ref', 'refs/remotes/origin/main', 'HEAD')
    return root


class DocumentResolution(unittest.TestCase):
    """governed_by carries BOTH plain repo-relative paths and ADR identifiers."""

    def test_plain_path_and_adr_id_both_resolve_at_the_pinned_sha(self):
        """Reported defect: the index keyed ADR ids only, over docs/decisions + docs/adr,
        so all plain-path references (12 of 42 in production) were falsely 'unresolved'."""
        with tempfile.TemporaryDirectory() as td:
            root = _git_repo_with_docs(Path(td), [
                'docs/CMO_EDITORIAL_LAYER.md',
                'docs/08_ai_investment_os_architecture.md',
                'docs/decisions/ADR-066-office.md',
            ])
            idx = m.document_index(root)
            self.assertTrue(idx['available'])
            self.assertRegex(idx['sha'], r'^[0-9a-f]{40}$')
            path_ref = m.resolve_document('docs/CMO_EDITORIAL_LAYER.md', idx)
            numbered = m.resolve_document('docs/08_ai_investment_os_architecture.md', idx)
            adr_ref = m.resolve_document('ADR-066', idx)
            missing = m.resolve_document('docs/NOPE_does_not_exist.md', idx)
        self.assertEqual((path_ref['outcome'], path_ref['kind']), ('resolved', 'path'))
        self.assertEqual(numbered['outcome'], 'resolved')
        self.assertEqual((adr_ref['outcome'], adr_ref['kind']), ('resolved', 'adr_id'))
        self.assertEqual(adr_ref['path'], 'docs/decisions/ADR-066-office.md')
        self.assertEqual(missing['outcome'], 'absent')

    def test_absent_document_and_missing_index_are_different_outcomes(self):
        unavailable = {'available': False, 'reason': 'listing unavailable', 'sha': None,
                       'paths': None, 'adr': None}
        r = m.resolve_document('docs/whatever.md', unavailable)
        self.assertEqual(r['outcome'], 'index_unavailable')
        self.assertNotEqual(r['outcome'], 'absent')

    def test_index_failure_is_unknown_not_absent_in_findings(self):
        with tempfile.TemporaryDirectory() as td:
            root = _repo(Path(td))
            (root / 'architecture/manifest.json').write_text(json.dumps(
                {'agents': [{'label': 'com.spa.g', 'intent': 'active',
                             'governed_by': ['docs/X.md']}]}))
            s = _collect(root, {'gui/501': _dom()})  # no git repo → index unavailable
        rules = {f['rule_code'] for f in s['findings']}
        self.assertIn('DOC_REFERENCE_UNVERIFIABLE', rules)
        self.assertNotIn('DOC_REFERENCE_ABSENT', rules)


class FindingIdentity(unittest.TestCase):
    """Two different rules on one entity must never share an id."""

    def test_multiple_rules_on_one_entity_get_distinct_ids(self):
        """Reported defect: findings.json carried `DRIFT:com.spa.httpserver` twice, for
        two different observations."""
        with tempfile.TemporaryDirectory() as td:
            root = _repo(Path(td) / 'repo')  # manifest empty → the label is NOT declared
            (Path(td) / 'Library/LaunchAgents').mkdir(parents=True)  # no plist for it
            with patch.object(m.Path, 'home', staticmethod(lambda: Path(td))):
                s = _collect(root, {'gui/501': _dom(services=['com.spa.multi'])},
                             listed={'com.spa.multi': {'pid': None, 'last_exit': 7}})
        mine = [f for f in s['findings'] if f['subject'] == 'com.spa.multi']
        # This is the httpserver shape: two different rules about one entity, which is
        # exactly what used to collapse into a single `DRIFT:<label>` id.
        self.assertEqual({f['rule_code'] for f in mine},
                         {'LOADED_WITHOUT_INSTALLED_PLIST', 'LOADED_NOT_IN_MANIFEST'})
        self.assertGreater(len(mine), 1, 'scene must produce several rules on one entity')
        self.assertEqual(len(mine), len({f['id'] for f in mine}), 'ids collided')
        for f in mine:
            self.assertTrue(f['rule_code'])
            self.assertTrue(f['id'].startswith(f['rule_code']))

    def test_ids_are_stable_across_repeated_collections(self):
        with tempfile.TemporaryDirectory() as td:
            root = _repo(Path(td))
            domains = {'gui/501': _dom(services=['com.spa.stable'])}
            a = _collect(root, domains, listed={'com.spa.stable': {'pid': None, 'last_exit': 2}})
            b = _collect(root, domains, listed={'com.spa.stable': {'pid': None, 'last_exit': 2}})
        self.assertEqual(sorted(f['id'] for f in a['findings']),
                         sorted(f['id'] for f in b['findings']))

    def test_uniqueness_is_validated_not_assumed(self):
        with tempfile.TemporaryDirectory() as td:
            root = _repo(Path(td))
            original = m.classify
            # Force the same rule to fire twice for one entity by faking a duplicate status.
            with patch.object(m, 'classify', side_effect=lambda *a, **k: 'DEGRADED'):
                s = _collect(root, {'gui/501': _dom(services=['com.spa.one', 'com.spa.two'])})
            m.classify = original
        ids = [f['id'] for f in s['findings']]
        self.assertEqual(len(ids), len(set(ids)))

    def test_drift_paths_get_one_id_each(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            def g(*a): return subprocess.check_output(['git', *a], cwd=p, stderr=subprocess.DEVNULL)
            g('init'); g('config', 'user.name', 'T'); g('config', 'user.email', 't@e.invalid')
            (p / 'scripts').mkdir(); (p / 'data').mkdir(); (p / 'architecture').mkdir()
            (p / 'architecture/manifest.json').write_text('{"agents": []}')
            (p / 'data/agent_registry.json').write_text('{"agents": []}')
            (p / 'data/code_sync_status.json').write_text('{"result":"IN_SYNC"}')
            for n in ('a.py', 'b.py'): (p / 'scripts' / n).write_text('x\n')
            g('add', '.'); g('commit', '-m', 'base'); g('update-ref', 'refs/remotes/origin/main', 'HEAD')
            (p / 'scripts/a.py').write_text('changed\n'); (p / 'scripts/b.py').write_text('changed\n')
            s = _collect(p, {'gui/501': _dom()}, real_git=True)
        drift_ids = [f['id'] for f in s['findings'] if f['rule_code'].startswith('DRIFT_')]
        self.assertGreaterEqual(len(drift_ids), 2)
        self.assertEqual(len(drift_ids), len(set(drift_ids)))


class AdrIdExtraction(unittest.TestCase):
    """The ADR key must be the identifier, not the whole filename."""

    def test_greedy_pattern_regression(self):
        """`ADR-[A-Za-z0-9-]*\\d+` swallowed the filename: ADR-129-owner-…-batch4.md keyed
        as `ADR-129-owner-decisions-2026-08-23-batch4`, so a real ADR-129 reference was
        reported absent while the file existed."""
        cases = {
            'ADR-129-owner-decisions-2026-08-23-batch4.md': 'ADR-129',
            'ADR-YL-004-risk-scoring-v2-is-advisory.md': 'ADR-YL-004',
            'ADR-AI1-004.md': 'ADR-AI1-004',
            'ADR-066-office.md': 'ADR-066',
        }
        for name, expected in cases.items():
            hit = m.ADR_ID_RE.match(name)
            self.assertIsNotNone(hit, name)
            self.assertEqual(hit.group(0), expected, name)
        self.assertIsNone(m.ADR_ID_RE.match('README.md'))

    def test_adr_with_a_date_in_the_filename_still_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            root = _git_repo_with_docs(Path(td), [
                'docs/decisions/ADR-129-owner-decisions-2026-08-23-batch4.md'])
            idx = m.document_index(root)
            got = m.resolve_document('ADR-129', idx)
        self.assertEqual(got['outcome'], 'resolved')
        self.assertEqual(got['path'], 'docs/decisions/ADR-129-owner-decisions-2026-08-23-batch4.md')


class ArgvNeverLeaksIntoDiagnostics(unittest.TestCase):
    """An option VALUE must not reach any output field — reason text included."""

    SENTINEL = 'SYNTHETIC_SECRET_SENTINEL'

    def test_every_unresolved_branch_uses_a_fixed_reason_code(self):
        """Reported defect: `unsupported python option form `--api-key=<secret>`` put the
        argument value straight into `unknown_reason`, and from there into every artifact."""
        S = self.SENTINEL
        branches = [
            (['/usr/bin/python3', f'--api-key={S}'], 'PYTHON_OPTION_UNSUPPORTED'),
            (['/bin/bash', f'--token={S}'], 'SHELL_OPTION_UNSUPPORTED'),
            (['/usr/bin/node', f'--secret={S}'], 'INTERPRETER_OPTION_UNSUPPORTED'),
            (['/bin/bash', '-c', f'curl {S}', '/tmp'], 'SHELL_INLINE_COMMAND'),
            (['/usr/bin/env', f'TOKEN={S}', '/bin/sh'], 'ENV_FORM_UNSUPPORTED'),
            (['/usr/bin/python3', '-m'], 'PYTHON_MODULE_MISSING_NAME'),
            (['/bin/bash'], 'INTERPRETER_WITHOUT_TARGET'),
        ]
        for argv, code in branches:
            ep = m.entrypoint_from_plist({'ProgramArguments': argv})
            self.assertEqual(ep['unknown_code'], code, argv)
            self.assertEqual(ep['unknown_reason'], m.ENTRYPOINT_REASONS[code])
            self.assertNotIn(S, json.dumps(ep, ensure_ascii=False), argv)
        self.assertIsNone(m.entrypoint_from_plist({}).get('target_kind'))
        self.assertEqual(m.entrypoint_from_plist({})['unknown_code'], 'NO_PROGRAM_OR_ARGV')

    def test_reason_texts_are_constant_never_formatted(self):
        """Two different secrets in the same branch must yield the SAME reason text."""
        a = m.entrypoint_from_plist({'ProgramArguments': ['/bin/bash', '--x=AAA']})
        b = m.entrypoint_from_plist({'ProgramArguments': ['/bin/bash', '--y=BBB']})
        self.assertEqual(a['unknown_reason'], b['unknown_reason'])
        self.assertNotIn('AAA', json.dumps(a))
        self.assertNotIn('BBB', json.dumps(b))

    def test_module_and_script_TARGETS_are_stored_by_design(self):
        """The resolved target is the entrypoint identity, not option content: a module
        name and a script path are recorded deliberately. Only OPTION text is withheld."""
        ep = m.entrypoint_from_plist({'ProgramArguments': ['/usr/bin/python3', '-m', 'pkg.mod']})
        self.assertEqual(ep['target'], 'pkg.mod')
        self.assertIsNone(ep['unknown_code'])

    def test_sentinel_absent_from_all_five_artifacts_not_just_one_field(self):
        S = self.SENTINEL
        import importlib.util as iu
        sp = iu.spec_from_file_location('sm', Path(__file__).parents[2] / 'scripts/cartographer/system_map.py')
        sm = iu.module_from_spec(sp); sp.loader.exec_module(sm)
        with tempfile.TemporaryDirectory() as td:
            root = _repo(Path(td) / 'repo')
            plist = {'Label': 'com.spa.leaky',
                     'ProgramArguments': ['/usr/bin/python3', f'--api-key={S}'],
                     'EnvironmentVariables': {'TOKEN': S}}
            pdir = Path(td) / 'Library/LaunchAgents'; pdir.mkdir(parents=True)
            (pdir / 'com.spa.leaky.plist').write_bytes(plistlib.dumps(plist))
            with patch.object(m.Path, 'home', staticmethod(lambda: Path(td))):
                snap = _collect(root, {'gui/501': _dom(services=['com.spa.leaky'])})
        graph = sm.build(snap)
        sm.validate(graph)
        blobs = {
            'snapshot.json': json.dumps(snap, ensure_ascii=False),
            'findings.json': json.dumps(snap['findings'], ensure_ascii=False),
            'system_map.json': json.dumps(graph, ensure_ascii=False),
            'summary.md': m.summary(snap, graph),
            'system_map.md': sm.mermaid(graph, snap),
        }
        for name, blob in blobs.items():
            self.assertNotIn(S, blob, f'sentinel leaked into {name}')


class PinnedBaseline(unittest.TestCase):
    """Every ref-dependent read of one comparison must use ONE resolved commit."""

    def _repo_with_two_commits(self, td):
        p = Path(td)
        def g(*a): return subprocess.check_output(['git', *a], cwd=p, stderr=subprocess.DEVNULL)
        g('init'); g('config', 'user.name', 'T'); g('config', 'user.email', 't@e.invalid')
        (p / 'scripts').mkdir(); (p / 'data').mkdir(); (p / 'architecture').mkdir()
        (p / 'architecture/manifest.json').write_text('{"agents": []}')
        (p / 'data/agent_registry.json').write_text('{"agents": []}')
        (p / 'data/code_sync_status.json').write_text('{"result":"IN_SYNC"}')
        (p / 'scripts/old_only.py').write_text('a\n')
        g('add', '.'); g('commit', '-m', 'A')
        sha_a = g('rev-parse', 'HEAD').decode().strip()
        g('update-ref', 'refs/remotes/origin/main', sha_a)
        g('rm', '-q', 'scripts/old_only.py'); g('commit', '-m', 'B')
        sha_b = g('rev-parse', 'HEAD').decode().strip()
        return p, g, sha_a, sha_b

    def test_reads_go_by_sha_not_by_the_moving_ref_name(self):
        """Structural proof: after resolution, no dependent read mentions the ref NAME."""
        seen = []
        real = m.git

        def spy(repo, *args):
            seen.append(args)
            return real(repo, *args)

        with tempfile.TemporaryDirectory() as td:
            p, g, sha_a, _ = self._repo_with_two_commits(td)
            with patch.object(m, 'git', side_effect=spy):
                m.drift(p)
        dependent = [a for a in seen if a and a[0] in ('ls-tree',) or (a and a[0] == '-c')]
        self.assertTrue(dependent)
        for args in dependent:
            self.assertNotIn('refs/remotes/origin/main', args,
                             'a dependent read still used the mutable ref name')
            self.assertIn(sha_a, args)

    def test_result_relates_to_the_originally_pinned_sha_even_if_the_ref_moves(self):
        with tempfile.TemporaryDirectory() as td:
            p, g, sha_a, sha_b = self._repo_with_two_commits(td)
            pinned = m.resolve_baseline(p)
            self.assertEqual(pinned, sha_a)
            # The ref moves between resolution and the dependent reads — as a background
            # sync really does on this machine.
            g('update-ref', 'refs/remotes/origin/main', sha_b)
            self.assertEqual(m.resolve_baseline(p), sha_b)
            result = m.drift(p, baseline_sha=pinned)
        self.assertEqual(result['reference_sha'], sha_a)
        # Against A the file still exists in the ref, so it is NOT production-only.
        self.assertEqual(result['production_only_tracked'], [])
        self.assertEqual(result['changed_or_missing_on_disk'], ['scripts/old_only.py'])

    def test_against_the_moved_ref_the_same_tree_reads_differently(self):
        """Control: the two baselines genuinely disagree, so the pin is load-bearing."""
        with tempfile.TemporaryDirectory() as td:
            p, g, sha_a, sha_b = self._repo_with_two_commits(td)
            at_a = m.drift(p, baseline_sha=sha_a)
            at_b = m.drift(p, baseline_sha=sha_b)
        self.assertNotEqual(at_a['changed_or_missing_on_disk'], at_b['changed_or_missing_on_disk'])
        self.assertEqual(at_b['changed_or_missing_on_disk'], [])

    def test_unresolvable_baseline_is_unknown_not_a_result(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            subprocess.check_output(['git', 'init'], cwd=p, stderr=subprocess.DEVNULL)
            self.assertIsNone(m.resolve_baseline(p))          # no origin/main at all
            self.assertIsNone(m.drift(p))
            idx = m.document_index(p)
        self.assertFalse(idx['available'])
        self.assertIsNone(idx['sha'])
        self.assertIn('could not be resolved', idx['reason'])

    def test_document_index_reads_by_sha(self):
        seen = []
        real = m.git

        def spy(repo, *args):
            seen.append(args)
            return real(repo, *args)

        with tempfile.TemporaryDirectory() as td:
            root = _git_repo_with_docs(Path(td), ['docs/A.md'])
            sha = m.resolve_baseline(root)
            with patch.object(m, 'git', side_effect=spy):
                idx = m.document_index(root)
        self.assertEqual(idx['sha'], sha)
        listings = [a for a in seen if a and a[0] == 'ls-tree']
        self.assertTrue(listings)
        for args in listings:
            self.assertIn(sha, args)
            self.assertNotIn('refs/remotes/origin/main', args)
