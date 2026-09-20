#!/usr/bin/env python3
"""Director OS Phase 2 — build the read-only studio portal.

Two documented commands, both writing a NEW directory outside production, outside every
observed worktree and outside the input sets:

  1. extract + build — layer A reads the chosen sources, layers B-D build the page;
  2. --from-portal-snapshot — OFFLINE rebuild of the page from a stored portal snapshot,
     touching neither production nor the network.

An unfinished run is written to ``<output>.incomplete`` and renamed into place only when
every artifact exists. Input sets are never modified and earlier results are never
overwritten.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diff as diff_mod                  # noqa: E402  offline by construction
import portal_extract as extract_mod     # noqa: E402  layer A + B
import portal_render as render_mod        # noqa: E402  layer C + D

PORTAL_MANIFEST_SCHEMA = 'cartographer.portal_run_manifest/0.1'
#: Derived artifacts copied next to the page so evidence is reachable from the UI. All of
#: them are already-sanitised derived state — no log, prompt or environment is copied.
EVIDENCE_FILES = ('owner_briefing.json', 'owner_briefing.md', 'diff.json', 'changes.md',
                  'source_of_truth.json', 'source_of_truth.md')
REACHING_MODULES = ('subprocess', 'socket', 'urllib.request', 'http.client')


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def design_reference(production):
    """Look for design material for THIS portal and report exactly what was found.

    The owner discussed the portal's design in another chat whose content was not handed
    over. Two design specs exist in the repository, but both are marked "read-only / not
    yet built" and both are about the PUBLIC site and its dashboard — neither is an
    approved design for an internal read-only portal. Saying otherwise would dress a
    draft for a different surface as an agreed design.
    """
    root = Path(production)
    candidates = []
    for rel, what in (('docs/SITE_DESIGN_SYSTEM.md', 'дизайн-система публичного сайта'),
                      ('docs/DASHBOARD_UX.md', 'UX-спецификация публичного дашборда'),
                      ('kanban.html', 'локальная статическая страница канбана')):
        p = root / rel
        if not p.is_file():
            continue
        head = p.read_text(encoding='utf-8', errors='replace')[:400]
        approved = 'not yet built' not in head and 'DESIGN SPEC' not in head
        candidates.append({'path': rel, 'what': what,
                           'status_line': next((l.strip() for l in head.splitlines()
                                                if 'Status:' in l), None),
                           'approved_for_this_portal': False,
                           'looks_like_draft': not approved})
    return {
        'state': 'DESIGN_REFERENCE_UNAVAILABLE',
        'note': 'материала, согласованного именно для этого внутреннего портала, в '
                'репозитории не найдено; оформление взято от принятой Phase 1 как '
                'временное и согласованным дизайном не является',
        'searched': ['docs/**.md (упоминания портала/Director OS)', 'docs/ideas',
                     'docs/rules-draft', 'корневые *.html', 'landing/src/pages',
                     'nimbalyst-local/tracker (карточки про портал)'],
        'found_but_not_applicable': candidates,
        'reason_not_applied': 'найденные материалы — черновики («not yet built») и '
                              'относятся к ПУБЛИЧНОМУ сайту и его дашборду, а не к '
                              'внутреннему read-only порталу',
    }


def _stage_facts(extracted_here, portal, briefing_dir):
    probes = []
    for source in portal['sources']:
        probes.append({'source': source['id'], 'read': source['available'],
                       'kind': 'file read' if source['available'] else 'missing'})
    return {
        'extraction': {
            'performed_by_this_run': extracted_here,
            'reads_production_files': extracted_here,
            'writes_production': False,
            'imports_production_modules': False,
            'network_used': False,
            'sources_read': probes if extracted_here else None,
            'note': ('источники прочитаны этим прогоном' if extracted_here else
                     'этот прогон не читал источники: страница пересобрана из '
                     'сохранённого portal snapshot'),
        },
        'machine_observation': {
            'performed_by_this_run': False,
            'note': 'наблюдение машины не выполнялось: взят принятый комплект '
                    'Cartographer/Owner Briefing как вход',
            'observed_at': portal['observation_times']['machine_observed_at'],
        },
        'build': {'network_used': False,
                  'guarantee': 'portal_render.py не импортирует subprocess, socket или '
                               'urllib — проверяется структурным тестом'},
        'offline_evidence': {
            'reaching_modules_imported': sorted(m for m in REACHING_MODULES
                                                if m in sys.modules),
            'note': 'измерено в конце прогона; при пересборке из snapshot список пуст',
        },
    }


def run(args):
    checks = []
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    briefing_dir = Path(args.briefing) if args.briefing else None

    if args.from_portal_snapshot:
        stored = Path(args.from_portal_snapshot)
        path = stored if stored.is_file() else stored / 'portal_snapshot.json'
        if not path.is_file():
            raise diff_mod.IncompatibleInput(f'no portal_snapshot.json at {stored}')
        try:
            portal = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise diff_mod.IncompatibleInput(
                f'portal_snapshot.json at {stored} could not be read '
                f'({type(exc).__name__})') from None
        validate_portal(portal, str(path))
        checks.append({'check': 'portal_snapshot_contract', 'result': 'PASS',
                       'detail': portal['schema_version']})
        extracted_here = False
        source_of_snapshot = str(path)
    else:
        if not briefing_dir:
            raise SystemExit('--briefing <accepted Owner Briefing set> is required when '
                             'extracting; pass --from-portal-snapshot to rebuild offline')
        if not args.cartographer:
            raise SystemExit('--cartographer <accepted Cartographer set> is required')
        portal = extract_mod.build_portal_snapshot(args.production, args.cartographer,
                                                   briefing_dir)
        validate_portal(portal, 'freshly extracted')
        checks.append({'check': 'extraction_completed', 'result': 'PASS',
                       'detail': f"{portal['counts']['tasks']} tasks, "
                                 f"{portal['counts']['owner_decision_records']} decisions, "
                                 f"{portal['counts']['agents_and_roles']} labels"})
        extracted_here = True
        source_of_snapshot = 'extracted in this run'

    brief = None
    brief_path = None
    if briefing_dir:
        brief_path = briefing_dir / 'owner_briefing.json'
        if brief_path.is_file():
            try:
                brief = json.loads(brief_path.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                raise diff_mod.IncompatibleInput(
                    f'owner_briefing.json in {briefing_dir} could not be read '
                    f'({type(exc).__name__})') from None
            if brief.get('schema_version') != 'cartographer.owner_briefing/0.1':
                raise diff_mod.IncompatibleInput(
                    f"owner briefing has schema {brief.get('schema_version')!r}, expected "
                    'cartographer.owner_briefing/0.1')
            checks.append({'check': 'owner_briefing_contract', 'result': 'PASS'})
        else:
            checks.append({'check': 'owner_briefing_contract', 'result': 'ABSENT',
                           'detail': 'раздел «Обзор» будет помечен недоступным'})

    authority = None
    if getattr(args, 'authority', None):
        import authority_map as authority_mod
        given = Path(args.authority)
        path = given if given.is_file() else given / 'authority_map.json'
        if not path.is_file():
            raise diff_mod.IncompatibleInput(f'no authority_map.json at {given}')
        try:
            authority = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise diff_mod.IncompatibleInput(
                f'authority_map.json at {given} could not be read '
                f'({type(exc).__name__})') from None
        try:
            authority_mod.validate_authority_map(authority, str(path))
        except authority_mod.AuthorityInputError as exc:
            raise diff_mod.IncompatibleInput(str(exc)) from None
        checks.append({'check': 'authority_map_contract', 'result': 'PASS',
                       'detail': authority['schema_version']})
        authority_source = path

    reliability = None
    reliability_source = None
    if getattr(args, 'reliability', None):
        import reliability as reliability_mod
        given = Path(args.reliability)
        path = given if given.is_file() else given / 'reliability_snapshot.json'
        if not path.is_file():
            raise diff_mod.IncompatibleInput(f'no reliability_snapshot.json at {given}')
        try:
            reliability = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise diff_mod.IncompatibleInput(
                f'reliability_snapshot.json at {given} could not be read '
                f'({type(exc).__name__})') from None
        try:
            reliability_mod.validate_reliability_snapshot(reliability, str(path))
        except reliability_mod.ReliabilityInputError as exc:
            raise diff_mod.IncompatibleInput(str(exc)) from None
        checks.append({'check': 'reliability_snapshot_contract', 'result': 'PASS',
                       'detail': reliability['schema_version']})
        reliability_source = path

    work = None
    work_source = None
    if getattr(args, 'work', None):
        import work as work_mod
        given = Path(args.work)
        path = given if given.is_file() else given / 'work_snapshot.json'
        if not path.is_file():
            raise diff_mod.IncompatibleInput(f'no work_snapshot.json at {given}')
        try:
            work = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise diff_mod.IncompatibleInput(
                f'work_snapshot.json at {given} could not be read '
                f'({type(exc).__name__})') from None
        try:
            work_mod.validate_work_snapshot(work, str(path))
        except work_mod.WorkInputError as exc:
            raise diff_mod.IncompatibleInput(str(exc)) from None
        checks.append({'check': 'work_snapshot_contract', 'result': 'PASS',
                       'detail': work['schema_version']})
        work_source = path

    director = None
    director_source = None
    if getattr(args, 'director', None):
        import director as director_mod
        given = Path(args.director)
        path = given if given.is_file() else given / 'director_center.json'
        if not path.is_file():
            raise diff_mod.IncompatibleInput(f'no director_center.json at {given}')
        try:
            director = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise diff_mod.IncompatibleInput(
                f'director_center.json at {given} could not be read '
                f'({type(exc).__name__})') from None
        try:
            director_mod.validate_director_center(director, str(path))
        except director_mod.DirectorInputError as exc:
            raise diff_mod.IncompatibleInput(str(exc)) from None
        checks.append({'check': 'director_center_contract', 'result': 'PASS',
                       'detail': director['schema_version']})
        director_source = path

    design = design_reference(args.production)
    portal['page_generated_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    portal['design_reference'] = design
    portal['semantic_digest'] = extract_mod.semantic_digest(portal)

    # ── output location: outside production, observed trees and the input sets ──
    final = Path(args.output)
    if final.exists():
        raise SystemExit(f'{final} already exists; every run writes a new directory')
    protected = [Path(args.production)]
    if args.cartographer:
        protected.append(Path(args.cartographer))
    if briefing_dir:
        protected.append(briefing_dir)
    if args.from_portal_snapshot:
        protected.append(Path(args.from_portal_snapshot))
    if getattr(args, 'reliability', None):
        protected.append(Path(args.reliability))
    if getattr(args, 'work', None):
        protected.append(Path(args.work))
    if getattr(args, 'director', None):
        protected.append(Path(args.director))
    snapshot_json = None
    if args.cartographer:
        candidate = Path(args.cartographer) / 'snapshot.json'
        if candidate.is_file():
            try:
                snapshot_json = json.loads(candidate.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                snapshot_json = None
    observed = diff_mod.observed_roots(snapshot_json) if snapshot_json else []
    diff_mod.validate_output(final, [*protected, *observed])
    checks.append({'check': 'output_outside_production_observed_trees_and_inputs',
                   'result': 'PASS',
                   'detail': f'{len(protected) + len(observed)} protected root(s), '
                             'symlinks resolved'})

    staging = final.with_name(final.name + '.incomplete')
    if staging.exists():
        raise SystemExit(f'{staging} exists from an earlier interrupted run; move it aside')
    staging.mkdir(parents=True, mode=0o700)

    # Which evidence files will really sit next to the page decides which links the page
    # is allowed to emit: an unconditional link to a file the input set lacks is dead.
    available = [name for name in EVIDENCE_FILES
                 if briefing_dir and (briefing_dir / name).is_file()]
    if authority is not None:
        available.append('authority_map.json')
    if reliability is not None:
        available.append('reliability_snapshot.json')
    if work is not None:
        available.append('work_snapshot.json')
    if director is not None:
        available.append('director_center.json')
    if args.cartographer and (Path(args.cartographer) / 'system_map.md').is_file():
        available.append('system_map.md')
    files = [('portal_snapshot.json', json.dumps(portal, indent=2, ensure_ascii=False)),
             ('index.html', render_mod.html(portal, brief, design, available,
                                             authority=authority,
                                             reliability=reliability, work=work,
                                             director=director)),
             ('owner_summary.md', render_mod.owner_summary(portal, brief, design))]
    for name, content in files:
        p = staging / name
        with p.open('x', encoding='utf-8') as handle:
            handle.write(content + '\n')
        p.chmod(0o600)

    copied = []
    for name in available:
        if name == 'director_center.json':
            shutil.copyfile(director_source, staging / name)
            (staging / name).chmod(0o600)
            copied.append(name)
            continue
        if name == 'work_snapshot.json':
            shutil.copyfile(work_source, staging / name)
            (staging / name).chmod(0o600)
            copied.append(name)
            continue
        if name == 'reliability_snapshot.json':
            shutil.copyfile(reliability_source, staging / name)
            (staging / name).chmod(0o600)
            copied.append(name)
            continue
        if name == 'authority_map.json':
            shutil.copyfile(authority_source, staging / name)
            (staging / name).chmod(0o600)
            copied.append(name)
            continue
        origin = (Path(args.cartographer) if name == 'system_map.md' else briefing_dir)
        shutil.copyfile(origin / name, staging / name)
        (staging / name).chmod(0o600)
        copied.append(name)
    checks.append({'check': 'evidence_copied_next_to_the_page', 'result': 'PASS',
                   'detail': ', '.join(copied) or 'none'})

    produced = [n for n, _ in files] + copied
    manifest = {
        'schema_version': PORTAL_MANIFEST_SCHEMA,
        'run_started_at': started,
        'page_generated_at': portal['page_generated_at'],
        'volatile_fields': ['run_started_at', 'page_generated_at'],
        'mode': 'offline_rebuild' if args.from_portal_snapshot else 'extract_and_build',
        'command': ' '.join(str(x) for x in sys.argv),
        'inputs': {
            'portal_snapshot_from': source_of_snapshot,
            'production_root': str(Path(args.production).resolve()),
            'cartographer_set': str(args.cartographer) if args.cartographer else None,
            'owner_briefing_set': str(briefing_dir) if briefing_dir else None,
            'owner_briefing_sha256': (_sha256(brief_path) if brief_path
                                      and brief_path.is_file() else None),
            'sources': [{'id': s['id'], 'available': s['available'],
                         'sha256': s.get('sha256'), 'observed_at': s.get('observed_at'),
                         'scope': s['scope']} for s in portal['sources']],
        },
        'versions': {
            'portal_snapshot_schema': portal['schema_version'],
            'portal_page_contract': render_mod.RENDER_CONTRACT,
            'owner_briefing_schema': (brief or {}).get('schema_version'),
            'run_manifest_schema': PORTAL_MANIFEST_SCHEMA,
        },
        'times': {
            'machine_observed_at': portal['observation_times']['machine_observed_at'],
            'briefing_generated_at': portal['observation_times']['briefing_generated_at'],
            'extraction_finished_at': portal['observation_times']['extraction_finished_at'],
            'page_generated_at': portal['page_generated_at'],
            'note': 'четыре разных момента; страница не выдаёт время сборки за время '
                    'наблюдения',
        },
        'design_reference': design,
        'authority_map': ({'schema': authority['schema_version'],
                           'authoritative_commit': authority['authoritative_commit'],
                           'counts': authority['counts'],
                           'digest': authority.get('semantic_digest')}
                          if authority else None),
        'reliability_snapshot': ({'schema': reliability['schema_version'],
                                  'counts': reliability['counts'],
                                  'creates_tasks': reliability['creates_tasks'],
                                  'performs_repair': reliability['performs_repair'],
                                  'digest': reliability.get('semantic_digest')}
                                 if reliability else None),
        'work_snapshot': ({'schema': work['schema_version'],
                           'counts': work['counts'],
                           'creates_tasks': work['creates_tasks'],
                           'modifies_tracker': work['modifies_tracker'],
                           'assigns_work': work['assigns_work'],
                           'digest': work.get('semantic_digest')}
                          if work else None),
        'director_center': ({'schema': director['schema_version'],
                             'system_state': director['system_state'],
                             'has_health_score': director['has_health_score'],
                             'computes_new_truth': director['computes_new_truth'],
                             'digest': director.get('semantic_digest')}
                            if director else None),
        'checks': checks,
        'digests': {'portal_snapshot': portal['semantic_digest']},
        'counts': portal['counts'],
        'outputs': [{'file': n, 'sha256': _sha256(staging / n)} for n in produced],
        'writers_invoked': 'NONE',
        'canonical_records_written': 'NONE',
        'stages': _stage_facts(extracted_here, portal, briefing_dir),
    }
    p = staging / 'run_manifest.json'
    with p.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    p.chmod(0o600)

    expected = set(produced) | {'run_manifest.json'}
    missing = expected - {x.name for x in staging.iterdir()}
    if missing:
        raise SystemExit(f'run incomplete, not published: missing {sorted(missing)}')
    os.rename(staging, final)
    return final, portal, manifest


#: Every portal snapshot must carry these, with these types. A truncated file is not an
#: empty studio.
REQUIRED_PORTAL_KEYS = {
    'schema_version': str, 'sources': list, 'tasks': list, 'owner_decision_records': list,
    'agents_and_roles': list, 'links': list, 'conflicts': list, 'extraction_errors': list,
    'counts': dict, 'observation_times': dict, 'limits': list, 'tracker_vocabulary': dict,
    'executor_claims': list, 'text_mentions': list,
}


def validate_portal(portal, where):
    if not isinstance(portal, dict):
        raise diff_mod.IncompatibleInput(f'{where}: portal snapshot is not an object')
    if portal.get('schema_version') != extract_mod.PORTAL_SCHEMA:
        raise diff_mod.IncompatibleInput(
            f"{where}: unsupported portal schema {portal.get('schema_version')!r}, "
            f'expected {extract_mod.PORTAL_SCHEMA}')
    for key, kind in REQUIRED_PORTAL_KEYS.items():
        value = portal.get(key)
        if value is None or not isinstance(value, kind):
            raise diff_mod.IncompatibleInput(
                f'{where}: required field `{key}` is missing or not {kind.__name__}')
    seen = set()
    for group in ('tasks', 'owner_decision_records', 'agents_and_roles'):
        for i, item in enumerate(portal[group]):
            if not isinstance(item, dict) or not item.get('id'):
                raise diff_mod.IncompatibleInput(f'{where}: {group}[{i}] has no id')
            key = (group, item['id'])
            if key in seen:
                raise diff_mod.IncompatibleInput(
                    f'{where}: duplicate id {item["id"]!r} in {group}')
            seen.add(key)
    for i, link in enumerate(portal['links']):
        if not link.get('basis'):
            raise diff_mod.IncompatibleInput(f'{where}: links[{i}] has no basis')
        if link.get('proves_assignment') is not False:
            raise diff_mod.IncompatibleInput(
                f'{where}: links[{i}] claims to prove an assignment; this phase records '
                'no such claim')
    counted = portal['counts'].get('tasks')
    if counted is not None and counted != len(portal['tasks']):
        raise diff_mod.IncompatibleInput(
            f'{where}: counts.tasks={counted} disagrees with {len(portal["tasks"])} '
            'task records')
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--production', type=Path, default=Path.home() / 'Documents/SPA_Claude')
    ap.add_argument('--cartographer', type=Path,
                    help='accepted Cartographer artifact set (machine observation)')
    ap.add_argument('--briefing', type=Path,
                    help='accepted Owner Briefing set (Phase 1)')
    ap.add_argument('--authority', type=Path,
                    help='комплект Authority Map (Phase 3): каталог или authority_map.json')
    ap.add_argument('--reliability', type=Path,
                    help='снимок надёжности (Phase 4): каталог или '
                         'reliability_snapshot.json')
    ap.add_argument('--work', type=Path,
                    help='снимок работы (Phase 5): каталог или work_snapshot.json')
    ap.add_argument('--director', type=Path,
                    help='центр директора (Phase 6): каталог или director_center.json')
    ap.add_argument('--from-portal-snapshot', type=Path,
                    help='OFFLINE rebuild: a stored portal_snapshot.json or its directory')
    ap.add_argument('--output', type=Path, required=True, help='new directory for the run')
    args = ap.parse_args(argv)
    try:
        final, portal, manifest = run(args)
    except diff_mod.IncompatibleInput as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\n'
                         'No portal was produced. This is NOT "the studio is empty".')
    c = portal['counts']
    print(f"Режим: {manifest['mode']}")
    print(f"Задач: {c['tasks']} · решений: {c['owner_decision_records']} · "
          f"агентов/ролей: {c['agents_and_roles']} · доказуемых связей: "
          f"{c['provable_links']} · расхождений: {c['conflicts']} · "
          f"ошибок извлечения: {c['extraction_errors']}")
    print(f"Дизайн-референс: {portal['design_reference']['state']}")
    print(f'Артефакты → {final}')
    print(f'  открыть: {final / "index.html"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
