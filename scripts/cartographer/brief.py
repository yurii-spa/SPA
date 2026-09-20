#!/usr/bin/env python3
"""Director OS Phase 1 — one command from stored observations to an owner briefing.

Three modes, all writing into a NEW directory outside production and outside every
observed worktree. Input sets are never modified.

  1. offline      — briefing from two EXPLICITLY named stored sets;
  2. one-shot     — new read-only capture, compared against an EXPLICITLY named baseline;
  3. first run    — no baseline at all: current state only, no invented comparison.

The baseline is never chosen silently. Convenience auto-selection exists but must be
asked for (``--baseline-latest-in``), and the choice, the candidates and the reason are
written into the run manifest.

An unfinished run must not look like a published briefing: everything is written into
``<output>.incomplete`` and renamed into place only when every artifact exists.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diff as diff_mod                      # noqa: E402  offline by construction
import owner_briefing as briefing_mod        # noqa: E402
import render as render_mod                  # noqa: E402
import source_of_truth as sot_mod            # noqa: E402

RUN_MANIFEST_SCHEMA = 'cartographer.run_manifest/0.1'


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _set_hashes(directory):
    out = {}
    for name in ('snapshot.json', 'system_map.json', 'findings.json'):
        p = Path(directory) / name
        if p.is_file():
            out[name] = _sha256(p)
    return out


#: A stored comparison must carry all of these. A truncated file is not a quiet result.
REQUIRED_DIFF_KEYS = ('schema_version', 'inputs', 'counts', 'changes', 'findings',
                      'change_classes', 'materiality_vocabulary', 'compatibility',
                      'limitations', 'component_counts', 'semantic_digest',
                      'owner_decision_candidates')


def _load_stored_diff(path, old_set, new_set, checks):
    """Reuse a stored comparison only if it IS the comparison of these two sets.

    Matching the schema and the input hashes is not enough: a file with the right
    `schema_version`, the right `inputs.files_sha256`, `counts.material = 999` and an
    empty `changes` list was accepted — reproduced. A recorded `semantic_digest` proves
    nothing either, since it is part of the same file.

    The comparison is deterministic and offline, so the honest check is to RECOMPUTE it
    from the two sets and require the semantic result to match. Anything else is refused
    before a briefing is published.
    """
    p = Path(path) / 'diff.json'
    if not p.is_file():
        raise diff_mod.IncompatibleInput(f'no diff.json in {path}')
    try:
        stored = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise diff_mod.IncompatibleInput(
            f'diff.json in {path} could not be read ({type(exc).__name__})') from None
    if not isinstance(stored, dict):
        raise diff_mod.IncompatibleInput(f'diff.json in {path} is not an object')
    if stored.get('schema_version') != diff_mod.DIFF_SCHEMA:
        raise diff_mod.IncompatibleInput(
            f"stored diff has schema {stored.get('schema_version')!r}, expected "
            f'{diff_mod.DIFF_SCHEMA}')
    missing = [k for k in REQUIRED_DIFF_KEYS if k not in stored]
    if missing:
        raise diff_mod.IncompatibleInput(
            f'stored diff in {path} is incomplete: missing {", ".join(sorted(missing))}')
    if not isinstance(stored['changes'], list) or not isinstance(stored['counts'], dict):
        raise diff_mod.IncompatibleInput(
            f'stored diff in {path}: `changes` must be a list and `counts` an object')

    for side, loaded in (('old', old_set), ('new', new_set)):
        want = loaded['files_sha256'].get('snapshot.json')
        got = (stored.get('inputs') or {}).get(side, {}).get('files_sha256', {}) \
            .get('snapshot.json')
        if got != want:
            raise diff_mod.IncompatibleInput(
                f'the stored comparison was not made from the {side} set given here '
                '(snapshot.json hash differs); snapshot and diff must come from one run')

    # Its own digest must at least describe its own content.
    if diff_mod.semantic_digest(stored) != stored['semantic_digest']:
        raise diff_mod.IncompatibleInput(
            f'stored diff in {path}: its semantic_digest does not match its own content')

    recomputed = diff_mod.compare(old_set, new_set)
    stored_view, fresh_view = (diff_mod.semantic_view(stored),
                              diff_mod.semantic_view(recomputed))
    if stored_view != fresh_view:
        differing = sorted(k for k in set(stored_view) | set(fresh_view)
                           if stored_view.get(k) != fresh_view.get(k))
        raise diff_mod.IncompatibleInput(
            f'stored diff in {path} does not match a fresh comparison of these two sets; '
            f'first differing field(s): {", ".join(differing[:4])}. The comparison is '
            'deterministic, so a difference means the stored file is not the result of '
            'these inputs')
    checks.append({'check': 'stored_diff_recomputed_and_identical', 'result': 'PASS',
                   'detail': 'schema, required fields, input hashes, own digest and the '
                             'full semantic result all agree'})
    return stored


def _pick_latest(directory, exclude=()):
    """Explicitly requested convenience: newest set by directory name."""
    candidates = sorted(d.name for d in Path(directory).iterdir()
                        if d.is_dir() and (d / 'snapshot.json').is_file()
                        and d.name not in exclude)
    if not candidates:
        raise SystemExit(f'no artifact set with a snapshot.json found in {directory}')
    return str(Path(directory) / candidates[-1]), candidates


def _capture(production, output_root, checks, protected=()):
    """Layer A: the existing read-only Cartographer. The only step that observes.

    The output location is guarded TWICE, and the second guard is the load-bearing one:
    which trees are observed is only known after ``collect()`` returns them, so checking
    the target against production alone let a capture write into an observed worktree —
    reproduced. Both guards run before the first write, and ``validate_output`` resolves
    symlinks on both sides, so an alias into an observed tree is caught as well.
    """
    import snapshot as snapshot_mod
    import system_map as map_mod
    target = Path(output_root) / f'capture-{dt.datetime.now().strftime("%Y%m%d-%H%M%S")}'
    snapshot_mod.validate_output(target, [production, *protected])
    s = snapshot_mod.collect(Path(production).resolve(), ())
    observed = diff_mod.observed_roots(s)
    snapshot_mod.validate_output(target, [production, *protected, *observed])
    checks.append({'check': 'capture_output_outside_every_observed_tree', 'result': 'PASS',
                   'detail': f'{len(observed)} observed tree(s) checked after collect, '
                             'symlinks resolved, before the first write'})
    smap = map_mod.build(s)
    map_mod.validate(smap)
    target.mkdir(parents=True, mode=0o700)
    for name, content in (
            ('snapshot.json', json.dumps(s, indent=2, ensure_ascii=False)),
            ('system_map.json', json.dumps(smap, indent=2, ensure_ascii=False)),
            ('findings.json', json.dumps(s['findings'], indent=2, ensure_ascii=False)),
            ('summary.md', snapshot_mod.summary(s, smap)),
            ('system_map.md', map_mod.mermaid(smap, s))):
        p = target / name
        with p.open('x', encoding='utf-8') as handle:
            handle.write(content + '\n')
        p.chmod(0o600)
    checks.append({'check': 'capture_written', 'result': 'PASS', 'detail': str(target)})
    return str(target)


#: Modules that could reach the machine or the network. In an offline run none of them is
#: even imported, and that is recorded as checkable evidence rather than asserted.
REACHING_MODULES = ('subprocess', 'socket', 'urllib.request', 'http.client')


def _stage_facts(new_snapshot, captured_here):
    """What each STAGE actually did. Never a blanket `network_used: false`.

    The capture stage reaches beyond this machine on purpose: it asks git for the live
    remote ref of main and probes the loopback Ollama endpoint. Writing `false` for the
    whole run — as this manifest used to — was untrue for every --capture run. Only
    WHETHER a probe answered is recorded: no remote URL, no credential, no raw response.
    """
    probes = [{'probe': 'git ls-remote origin (live ref of main)',
               'repository': r.get('path'),
               'reaches_beyond_this_machine': True,
               'outcome': 'answered' if r.get('remote_origin_main') else 'no answer recorded'}
              for r in (new_snapshot.get('repositories') or [])]
    ollama = new_snapshot.get('ollama') or {}
    probes.append({'probe': 'HTTP GET on the loopback Ollama version endpoint',
                   'repository': None, 'reaches_beyond_this_machine': False,
                   'outcome': ('answered' if ollama.get('api_reachable')
                               else 'no answer recorded')})
    offline_guarantee = ('this stage imports no subprocess, socket or urllib — enforced by '
                         'a structural test over diff.py, source_of_truth.py, '
                         'owner_briefing.py and render.py, and by a behavioural test that '
                         'runs the whole path with those doors patched to raise')
    return {
        'capture': {
            'performed_by_this_run': captured_here,
            'observes_live_sources': True,
            'probes_recorded_by': ('this run' if captured_here else
                                   'the stored capture, not this run'),
            'network_probes': probes,
            'privacy': 'only whether a probe answered is stored; no remote URL, no '
                       'credential, no raw response, no stderr',
        },
        'interpretation': {'network_used': False, 'guarantee': offline_guarantee},
        'presentation': {'network_used': False, 'guarantee': offline_guarantee},
        'offline_evidence': {
            'reaching_modules_imported': sorted(
                m for m in REACHING_MODULES if m in sys.modules),
            'note': 'measured at the end of the run. In an offline run this list is empty; '
                    'with --capture it is not, because layer A must observe',
        },
    }


def run(args):
    checks = []
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    baseline_selection = {'mode': 'none', 'chosen': None, 'considered': None,
                          'reason': 'первый запуск: baseline не выбирался'}

    new_dir = str(args.new) if args.new else None
    if args.capture:
        # The explicitly named baseline is an INPUT: a capture must not be written inside it.
        protected = [args.old] if args.old else []
        new_dir = _capture(args.production, args.capture_into or args.output.parent,
                           checks, protected=protected)

    if new_dir is None:
        raise SystemExit('need --new <set> or --capture')

    old_dir = str(args.old) if args.old else None
    if args.baseline_latest_in:
        if args.first_run:
            raise SystemExit('--first-run and --baseline-latest-in are mutually exclusive')
        old_dir, considered = _pick_latest(args.baseline_latest_in,
                                           exclude={Path(new_dir).name})
        baseline_selection = {
            'mode': 'auto-latest-by-name', 'chosen': old_dir, 'considered': considered,
            'reason': 'автоматический выбор был ЯВНО запрошен флагом --baseline-latest-in; '
                      'порядок — по имени каталога, а не по содержимому'}
    elif old_dir:
        baseline_selection = {'mode': 'explicit', 'chosen': old_dir, 'considered': None,
                              'reason': 'baseline назван пользователем явно'}
    elif not args.first_run:
        raise SystemExit('a baseline is required: pass --old <set>, --baseline-latest-in '
                         '<dir> (explicit opt-in), or --first-run for no comparison at all')

    # ── load and check inputs ────────────────────────────────────────────────
    new_set = diff_mod.load_set(new_dir)
    checks.append({'check': 'new_snapshot_contract', 'result': 'PASS',
                   'detail': new_set['schema_version']})
    the_diff = None
    old_set = None
    if old_dir:
        old_set = diff_mod.load_set(old_dir)
        checks.append({'check': 'old_snapshot_contract', 'result': 'PASS',
                       'detail': old_set['schema_version']})
        if args.diff:
            the_diff = _load_stored_diff(args.diff, old_set, new_set, checks)
        else:
            the_diff = diff_mod.compare(old_set, new_set)
            checks.append({'check': 'comparison_computed_from_these_two_sets',
                           'result': 'PASS'})

    sot = sot_mod.build(new_set['snapshot'], source_dir=new_set['dir'])
    sot_mod.validate(sot)
    checks.append({'check': 'source_of_truth_validated', 'result': 'PASS'})

    provenance = {
        'capture': {'directory': new_dir, 'observed_at': new_set['finished_at'],
                    'schema': new_set['schema_version'],
                    'files_sha256': new_set['files_sha256']},
        'baseline': ({'directory': old_dir, 'observed_at': old_set['finished_at'],
                      'schema': old_set['schema_version'],
                      'files_sha256': old_set['files_sha256']} if old_set else None),
        'comparison_generated_at': (the_diff or {}).get('generated_at'),
        'comparison_digest': (the_diff or {}).get('semantic_digest'),
        'baseline_selection': baseline_selection,
        'time_note': 'время наблюдения, время сравнения и время сборки страницы — три '
                     'разных момента и здесь не смешиваются',
    }
    brief = briefing_mod.build(new_set['snapshot'], sot, diff=the_diff,
                               provenance=provenance)

    # ── write: nothing is published until everything exists ─────────────────
    final = Path(args.output)
    if final.exists():
        raise SystemExit(f'{final} already exists; every run writes a new directory')
    # Outside every observed tree AND outside the input sets themselves: a report must
    # never be written inside the artifacts it was derived from.
    roots = diff_mod.observed_roots(new_set['snapshot'],
                                    *( [old_set['snapshot']] if old_set else [] ))
    roots = roots + [new_dir] + ([old_dir] if old_dir else [])
    diff_mod.validate_output(final, roots)
    checks.append({'check': 'output_outside_observed_trees_and_input_sets', 'result': 'PASS',
                   'detail': f'{len(roots)} protected root(s), symlinks resolved'})
    staging = final.with_name(final.name + '.incomplete')
    if staging.exists():
        raise SystemExit(f'{staging} exists from an earlier interrupted run; move it aside')
    staging.mkdir(parents=True, mode=0o700)

    files = [('owner_briefing.json', json.dumps(brief, indent=2, ensure_ascii=False)),
             ('owner_briefing.md', render_mod.markdown(brief)),
             ('index.html', render_mod.html(brief)),
             ('source_of_truth.json', json.dumps(sot, indent=2, ensure_ascii=False)),
             ('source_of_truth.md', sot_mod.markdown(sot))]
    if the_diff:
        files += [('diff.json', json.dumps(the_diff, indent=2, ensure_ascii=False)),
                  ('changes.md', diff_mod.changes_markdown(the_diff))]
    for name, content in files:
        p = staging / name
        with p.open('x', encoding='utf-8') as handle:
            handle.write(content + '\n')
        p.chmod(0o600)

    manifest = {
        'schema_version': RUN_MANIFEST_SCHEMA,
        'run_started_at': started,
        'page_generated_at': brief['generated_at'],
        'volatile_fields': ['run_started_at', 'page_generated_at'],
        'mode': brief['mode'],
        'command': ' '.join(sys.argv[:1] + [str(x) for x in sys.argv[1:]]),
        'inputs': provenance,
        'versions': {
            'snapshot_schema': new_set['schema_version'],
            'diff_schema': (the_diff or {}).get('schema_version'),
            'source_of_truth_schema': sot['schema_version'],
            'owner_briefing_schema': brief['schema_version'],
            'run_manifest_schema': RUN_MANIFEST_SCHEMA,
        },
        'checks': checks,
        'digests': {'owner_briefing': brief['semantic_digest'],
                    'comparison': (the_diff or {}).get('semantic_digest')},
        'outputs': [{'file': name, 'sha256': _sha256(staging / name)}
                    for name, _ in files],
        'writers_invoked': 'NONE',
        'production_written': False,
        'production_read_by_this_run': bool(args.capture),
        'stages': _stage_facts(new_set['snapshot'], bool(args.capture)),
    }
    p = staging / 'run_manifest.json'
    with p.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    p.chmod(0o600)

    expected = {name for name, _ in files} | {'run_manifest.json'}
    missing = expected - {x.name for x in staging.iterdir()}
    if missing:
        raise SystemExit(f'run incomplete, not published: missing {sorted(missing)}')
    os.rename(staging, final)
    return final, brief, manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--new', type=Path, help='stored artifact set to brief on')
    ap.add_argument('--old', type=Path, help='baseline artifact set (explicit)')
    ap.add_argument('--diff', type=Path,
                    help='reuse an existing comparison directory (verified by hash)')
    ap.add_argument('--capture', action='store_true',
                    help='take a NEW read-only capture first (one-shot)')
    ap.add_argument('--capture-into', type=Path,
                    help='where the new capture is stored (default: next to --output)')
    ap.add_argument('--production', type=Path, default=Path.home() / 'Documents/SPA_Claude')
    ap.add_argument('--first-run', action='store_true',
                    help='no baseline at all: current state only, no invented comparison')
    ap.add_argument('--baseline-latest-in', type=Path,
                    help='EXPLICIT opt-in: pick the newest set in this directory as the '
                         'baseline; the choice is recorded in the run manifest')
    ap.add_argument('--output', type=Path, required=True, help='new directory for the run')
    args = ap.parse_args(argv)

    try:
        final, brief, manifest = run(args)
    except diff_mod.IncompatibleInput as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\n'
                         'No briefing was produced. This is NOT "nothing changed".')
    print(f"Режим: {brief['mode']} · наблюдение {brief['freshness_and_coverage']['observed_at']}")
    print(f"Подтверждённых изменений: {brief['counts']['confirmed_changes']} · "
          f"внимание: {brief['counts']['attention_items']} · "
          f"кандидатов решений: {brief['counts']['owner_candidates']} · "
          f"неизвестного: {brief['counts']['unknown_findings']}")
    print(f'Артефакты → {final}')
    print(f'  открыть: {final / "index.html"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
