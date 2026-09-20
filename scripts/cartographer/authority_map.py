#!/usr/bin/env python3
"""Authority Map (Director OS Phase 3): where truth lives, and where reality differs.

READ-ONLY. Reads git and the filesystem, writes nothing outside ``--output``, invokes no
writer, deletes nothing. Every status carries the evidence that produced it; a status is
never assigned without one.

The authority model is NOT invented here. It is read out of what the repository already
declares:

  * ``scripts/code_sync_from_origin.sh`` states its own scope and — crucially — that a
    checkout **cannot delete**: "a file origin deleted stays here", and the rest "is named
    in `retired_code` and left alone". So production carrying code that origin no longer
    has is the DESIGNED outcome of the canonical path, not a malfunction.
  * ADR-214 makes ``CLAUDE.md`` and ``.claude/rules/`` part of delivery, so their
    authority is origin too.
  * The same script names what is NEVER synced: ``data/`` (the live track), ``docs/``,
    ``nimbalyst-local/``, ``KANBAN.json`` and ``.claude/`` as a whole. For those,
    production is where the content is written, and origin has no authority at all.

Where no rule establishes who wins, the answer is ``AUTHORITY_UNDEFINED`` — not a guess.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

AUTHORITY_SCHEMA = 'cartographer.authority_map/0.1'

#: Every status a comparison may produce. A status outside this set is a bug.
DRIFT_STATUSES = (
    'IN_SYNC', 'MODIFIED', 'MISSING_IN_PRODUCTION', 'EXTRA_IN_PRODUCTION',
    'MISSING_IN_ORIGIN', 'DECLARED_NOT_OBSERVED', 'OBSERVED_NOT_DECLARED', 'STALE',
    'AUTHORITY_UNDEFINED', 'GENERATED', 'IGNORED', 'UNKNOWN',
)
SEVERITIES = ('INFO', 'WARNING', 'CRITICAL')

#: What DISCRIMINATES each status from its neighbours. The three that read most alike —
#: EXTRA_IN_PRODUCTION, MISSING_IN_ORIGIN and OBSERVED_NOT_DECLARED — are disjoint by
#: construction, but not by NAME: "missing in origin" is literally true of the first two
#: alike. The discriminator, not the name, decides, and it is stated here so a reader
#: cannot confuse them. (A more precise name for MISSING_IN_ORIGIN would be
#: LOCAL_ONLY_UNTRACKED; the taxonomy is not renamed here because the prescribed
#: vocabulary is what the reviewer enumerated — the recommendation is reported instead.)
DRIFT_STATUS_DEFINITIONS = {
    'IN_SYNC': 'содержимое на диске совпадает с авторитетным коммитом',
    'MODIFIED': 'путь ЕСТЬ в авторитетном коммите, содержимое на диске другое',
    'MISSING_IN_PRODUCTION': 'путь ЕСТЬ в авторитетном коммите, на диске его нет',
    'EXTRA_IN_PRODUCTION': 'путь ОТСЛЕЖИВАЕТСЯ git в проде и отсутствует в авторитетном '
                           'коммите: origin его удалил, а checkout удалить не может',
    'MISSING_IN_ORIGIN': 'путь на диске НЕ отслеживается git и отсутствует в авторитетном '
                         'коммите: он никогда не доезжал каноническим путём. Дискриминатор '
                         'против EXTRA_IN_PRODUCTION — именно отслеживаемость',
    'DECLARED_NOT_OBSERVED': 'сущность объявлена (манифест или repo/launchd), но не '
                             'наблюдается; речь о СУЩНОСТЯХ, не о файлах области '
                             'синхронизации',
    'OBSERVED_NOT_DECLARED': 'сущность наблюдается, но не объявлена; тоже о сущностях — '
                             'метках launchd и установленных plist, а не о файлах кода',
    'STALE': 'артефакт вышел за ОБЪЯВЛЕННЫЙ в манифесте slo_hours',
    'AUTHORITY_UNDEFINED': 'правило каноничности для этого типа нигде не объявлено',
    'GENERATED': 'файл производится в проде; сравнение с origin не применимо',
    'IGNORED': 'путь объявлен вне канонической доставки самим синхронизатором',
    'UNKNOWN': 'наблюдения не хватает для суждения',
}
#: Which entity types each status may apply to. Two statuses that can never meet on one
#: entity type cannot be confused in the data, whatever their names suggest.
DRIFT_STATUS_SCOPE = {
    'EXTRA_IN_PRODUCTION': ('code_file', 'instruction_file'),
    'MISSING_IN_ORIGIN': ('code_file', 'instruction_file'),
    'OBSERVED_NOT_DECLARED': ('launchd_agent', 'installed_plist'),
}

#: The scope the canonical sync actually carries, quoted from the script's own rules.
SYNC_SCOPE = ('spa_core', 'scripts', 'tests', 'architecture',
              'push_to_github.py', 'push_to_github_batch.py',
              'CLAUDE.md', '.claude/rules')
#: Named by the same script as NEVER synced.
NEVER_SYNCED = ('data', 'docs', 'nimbalyst-local', 'KANBAN.json')

#: The declared authority model, per kind of entity. `established_by` is the citation that
#: makes it a rule rather than an opinion; where it is None the status is
#: AUTHORITY_UNDEFINED and the map says so instead of choosing.
AUTHORITY_MODEL = {
    'code_file': {
        'declared_source': 'рабочее дерево сессии (worktree) → push_to_github.py',
        'authoritative_source': 'origin/main (коммит)',
        'observed_source': 'рабочее дерево прода ~/Documents/SPA_Claude',
        'derived_source': 'data/code_sync_status.json + снимок Cartographer (drift)',
        'authority_status': 'DECLARED',
        'established_by': 'scripts/code_sync_from_origin.sh — «CODE ONLY, whole '
                          'directories … This script makes "delivered to origin" == '
                          '"running in prod"»; ADR-214',
        'limit': 'checkout НЕ УДАЛЯЕТ: файл, удалённый на origin, остаётся в проде и '
                 'называется в retired_code',
    },
    'instruction_file': {
        'declared_source': 'рабочее дерево сессии → push_to_github.py',
        'authoritative_source': 'origin/main (коммит)',
        'observed_source': 'прод-дерево',
        'derived_source': 'data/code_sync_status.json (retired_instructions)',
        'authority_status': 'DECLARED',
        'established_by': 'ADR-214 «Инструкции — часть доставки»; синхронизатор возит '
                          'CLAUDE.md и .claude/rules/',
        'limit': 'то же ограничение: удаление на origin в прод не доезжает',
    },
    'excluded_path': {
        'declared_source': 'нет: путь вне канонической доставки',
        'authoritative_source': 'прод-дерево (там и пишется)',
        'observed_source': 'прод-дерево',
        'derived_source': None,
        'authority_status': 'DECLARED',
        'established_by': 'scripts/code_sync_from_origin.sh — «NEVER data/ (live track), '
                          'docs/, nimbalyst-local/, KANBAN.json»',
        'limit': 'origin для этих путей авторитетом не является вовсе',
    },
    'generated_state': {
        'declared_source': 'агент-производитель в проде',
        'authoritative_source': 'прод-дерево (файл переписывается на месте)',
        'observed_source': 'прод-дерево',
        'derived_source': None,
        'authority_status': 'DECLARED',
        'established_by': 'поле source/updated_by внутри самого файла',
        'limit': 'сравнение с origin бессмысленно: origin-копия заморожена',
    },
    'launchd_agent': {
        'declared_source': 'architecture/manifest.json',
        'authoritative_source': None,
        'observed_source': 'launchctl print <domain>/<label> + launchctl list (снимок)',
        'derived_source': 'data/agent_registry.json (генерируется агентом флота)',
        'authority_status': 'AUTHORITY_UNDEFINED',
        'established_by': None,
        'limit': 'правила, какой состав главнее — манифест или реестр, в репозитории нет',
    },
    'installed_plist': {
        'declared_source': '<repo>/launchd/*.plist',
        'authoritative_source': None,
        'observed_source': '~/Library/LaunchAgents и системные каталоги',
        'derived_source': None,
        'authority_status': 'AUTHORITY_UNDEFINED',
        'established_by': None,
        'limit': 'launchd/ НЕ входит в область синхронизации, а установку выполняет '
                 'отдельное действие владельца (CLAUDE.md инв. 12) — кто главнее, '
                 'нигде не объявлено',
    },
    'declared_artifact': {
        'declared_source': 'architecture/manifest.json (produces + slo_hours)',
        'authoritative_source': 'architecture/manifest.json для ОБЪЯВЛЕНИЯ; для '
                                'содержимого — производящий агент',
        'observed_source': 'метаданные файла в прод-дереве',
        'derived_source': 'снимок Cartographer (fresh/exists)',
        'authority_status': 'DECLARED',
        'established_by': 'манифест объявляет артефакт и его SLO',
        'limit': 'кто записал файл — неизвестно (producer_attribution: UNKNOWN)',
    },
}

#: Severity is factual and cites the rule that makes the state matter. No business grade.
SEVERITY_RULES = {
    'IN_SYNC': ('INFO', 'состояние совпадает с авторитетным источником'),
    'GENERATED': ('INFO', 'файл производится в проде; сравнение с origin не применимо'),
    'IGNORED': ('INFO', 'путь объявлен вне канонической доставки самим синхронизатором'),
    'AUTHORITY_UNDEFINED': ('INFO', 'правило каноничности не объявлено; это не дефект '
                                    'состояния, а пробел в правилах'),
    'UNKNOWN': ('INFO', 'наблюдения не хватает для суждения'),
    'MODIFIED': ('WARNING', 'первый вопрос правила доставки — «это тот код, который мы '
                            'приняли?» — отвечает НЕТ (.claude/rules/deployment.md)'),
    'EXTRA_IN_PRODUCTION': ('WARNING', 'прод несёт код, которого нет в авторитетном '
                                       'коммите; checkout его не удалит по построению'),
    'MISSING_IN_ORIGIN': ('WARNING', 'файл не доезжал каноническим путём и не защищён '
                                     'историей origin'),
    'MISSING_IN_PRODUCTION': ('WARNING', 'принятый код не дошёл до прода'),
    'DECLARED_NOT_OBSERVED': ('WARNING', 'объявлено, но не наблюдается'),
    'OBSERVED_NOT_DECLARED': ('WARNING', 'наблюдается, но не объявлено'),
    'STALE': ('WARNING', 'артефакт вышел за ОБЪЯВЛЕННЫЙ в манифесте SLO'),
}

#: The read-only delivery chain. Direction and evidence per transition; not a workflow
#: engine — nothing here executes or schedules anything.
DELIVERY_CHAIN = (
    {'step': 1, 'from': 'рабочее дерево сессии (worktree)', 'to': 'origin/main',
     'mechanism': 'push_to_github.py (GitHub Contents API)',
     'direction': 'session → origin', 'authority_role': 'записывает АВТОРИТЕТ для кода',
     'evidence': 'CLAUDE.md §Команды: «Push (ABSOLUTE пути, PAT из Keychain)»; сам '
                 'push_to_github.py сверяет свою копию инструмента и отказывает '
                 'fail-CLOSED при расхождении',
     'observed_state_field': 'origin_head'},
    {'step': 2, 'from': 'origin/main', 'to': 'прод-дерево',
     'mechanism': 'scripts/code_sync_from_origin.sh (git checkout origin/main -- paths)',
     'direction': 'origin → production',
     'authority_role': 'приводит прод к авторитету в ОБЪЯВЛЕННОЙ области',
     'evidence': 'скрипт: «only `checkout origin/main -- <paths>`», «Never git reset», '
                 '«A checkout does not DELETE»',
     'observed_state_field': 'code_sync'},
    {'step': 3, 'from': 'прод-дерево', 'to': 'launchd / runtime',
     'mechanism': 'launchd исполняет entrypoint по пути из установленного plist',
     'direction': 'production → runtime',
     'authority_role': 'прод-дерево — то, что реально исполняется',
     'evidence': 'снимок Cartographer: стадии INSTALLED/LOADED/RUNNING и entrypoint '
                 'каждого установленного plist',
     'observed_state_field': 'launchd'},
    {'step': 4, 'from': 'любой просыпающийся агент', 'to': 'шаг 2',
     'mechanism': 'scripts/agent_template.sh вызывает синхронизатор (троттлинг)',
     'direction': 'runtime → origin→production',
     'authority_role': 'носитель шага 2; отдельной метки launchd у синхронизации нет',
     'evidence': 'agent_template.sh: вызов code_sync_from_origin.sh с троттлингом',
     'observed_state_field': 'code_sync.timestamp'},
)


class AuthorityInputError(Exception):
    """Unreadable or inconsistent input. Never degraded into "no drift"."""


def _run(args, cwd, timeout=60):
    """Read-only command. Returns stdout or None; the error CLASS only, never stderr."""
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0',
                                'GIT_TERMINAL_PROMPT': '0'})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def _git(repo, *args):
    return _run(['git', '-c', 'core.fsmonitor=false', *args], repo)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _evidence(kind, detail, command=None):
    rec = {'kind': kind, 'detail': detail}
    if command:
        rec['command'] = command
    return rec


def resolve_origin(production, ref='refs/remotes/origin/main'):
    """Pin the authoritative commit ONCE, exactly as Phase 0C taught."""
    sha = (_git(production, 'rev-parse', '--verify', f'{ref}^{{commit}}') or '').strip()
    return sha if re.fullmatch(r'[0-9a-f]{40}', sha or '') else None


# ── code and instructions: production against the pinned authoritative commit ──

def compare_scope(production, origin_sha):
    """Compare the sync scope between the authoritative commit and the production tree.

    Three git reads, not thousands: ``diff --name-status`` against the pinned commit gives
    every difference in one pass, ``ls-files --others`` gives what git never tracked, and
    ``ls-tree`` gives the denominator. Nothing is written — no index refresh is requested
    and ``core.fileMode`` stays as configured.
    """
    scope = [p for p in SYNC_SCOPE]
    diff = _git(production, '-c', 'core.fileMode=false', 'diff', '--no-ext-diff',
                '--no-textconv', '--name-status', '-z', origin_sha, '--', *scope)
    others = _git(production, 'ls-files', '--others', '--exclude-standard', '-z',
                  '--', *scope)
    listing = _git(production, 'ls-tree', '-r', '--name-only', '-z', origin_sha,
                   '--', *scope)
    if diff is None or others is None or listing is None:
        raise AuthorityInputError(
            'сравнение области синхронизации не выполнено (git-чтение не удалось); '
            'это НЕ значит «расхождений нет»')
    in_origin = [x for x in listing.split('\0') if x]
    untracked = [x for x in others.split('\0') if x]
    changed = {}
    tokens = [x for x in diff.split('\0') if x]
    i = 0
    while i < len(tokens) - 1:
        status, path = tokens[i], tokens[i + 1]
        changed[path] = status[0]
        i += 2
    return {'in_origin': in_origin, 'untracked': untracked, 'changed': changed,
            'scope': scope}


def _code_entity(path, status, production, origin_sha, kind):
    model = AUTHORITY_MODEL[kind]
    severity, why = SEVERITY_RULES[status]
    disk = Path(production) / path
    evidence = [_evidence('git', f'сравнение с закреплённым коммитом {origin_sha[:12]}',
                          f'git diff --name-status {origin_sha[:12]} -- {path}')]
    if status in ('EXTRA_IN_PRODUCTION', 'MISSING_IN_ORIGIN'):
        evidence.append(_evidence('git', f'путь отсутствует в дереве коммита',
                                  f'git cat-file -e {origin_sha[:12]}:{path}'))
    observed = {'present': os.path.lexists(disk)}
    if observed['present'] and disk.is_file():
        stat = disk.stat()
        observed['sha256'] = _sha256(disk)
        observed['mtime'] = dt.datetime.fromtimestamp(stat.st_mtime,
                                                      dt.timezone.utc).isoformat()
        observed['size_bytes'] = stat.st_size
    return {
        'entity_id': f'{kind}:{path}',
        'entity_type': kind,
        'path': path,
        'declared_source': model['declared_source'],
        'authoritative_source': model['authoritative_source'],
        'observed_source': model['observed_source'],
        'derived_source': model['derived_source'],
        'authority_status': model['authority_status'],
        'authority_established_by': model['established_by'],
        'authority_limit': model['limit'],
        'observed': observed,
        'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'drift_status': status,
        'severity': severity,
        'severity_basis': why,
        'origin_present': status not in ('EXTRA_IN_PRODUCTION', 'MISSING_IN_ORIGIN'),
        'production_present': status != 'MISSING_IN_PRODUCTION',
        'evidence': evidence,
    }


def code_entities(production, origin_sha, comparison, sync_report):
    """One entity per path that is NOT in sync, plus one aggregate for the in-sync rest.

    Listing ~4500 unchanged files individually would drown the owner in noise and say
    nothing; the aggregate carries the count and the command that produced it.
    """
    out = []
    instruction_paths = ('CLAUDE.md', '.claude/rules')
    def kind_of(path):
        return ('instruction_file'
                if path == 'CLAUDE.md' or path.startswith('.claude/rules')
                else 'code_file')

    for path, letter in sorted(comparison['changed'].items()):
        status = {'M': 'MODIFIED', 'D': 'MISSING_IN_PRODUCTION',
                  'A': 'EXTRA_IN_PRODUCTION'}.get(letter, 'UNKNOWN')
        out.append(_code_entity(path, status, production, origin_sha, kind_of(path)))
    for path in sorted(comparison['untracked']):
        out.append(_code_entity(path, 'MISSING_IN_ORIGIN', production, origin_sha,
                                kind_of(path)))

    differing = set(comparison['changed']) | set(comparison['untracked'])
    in_sync = [p for p in comparison['in_origin'] if p not in differing]
    model = AUTHORITY_MODEL['code_file']
    out.append({
        'entity_id': 'code_file:__in_sync_aggregate__',
        'entity_type': 'code_file_aggregate',
        'path': ', '.join(comparison['scope']),
        'declared_source': model['declared_source'],
        'authoritative_source': model['authoritative_source'],
        'observed_source': model['observed_source'],
        'derived_source': model['derived_source'],
        'authority_status': model['authority_status'],
        'authority_established_by': model['established_by'],
        'authority_limit': model['limit'],
        'observed': {'files_in_sync': len(in_sync),
                     'files_in_authoritative_commit': len(comparison['in_origin'])},
        'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'drift_status': 'IN_SYNC',
        'severity': 'INFO',
        'severity_basis': SEVERITY_RULES['IN_SYNC'][1],
        'origin_present': True, 'production_present': True,
        'aggregate_note': 'один объект на ВСЕ совпавшие файлы: перечислять их поимённо '
                          'значило бы утопить содержательные расхождения в шуме',
        'evidence': [_evidence('git', f'{len(in_sync)} путей области совпали с коммитом '
                                      f'{origin_sha[:12]}',
                               f'git ls-tree -r --name-only {origin_sha[:12]} минус '
                               'git diff --name-status')],
    })
    # The sync's own report is the derived witness for exactly this class.
    if isinstance(sync_report, dict):
        retired = sync_report.get('retired_code') or []
        out.append({
            'entity_id': 'derived:code_sync_status',
            'entity_type': 'sync_report',
            'path': 'data/code_sync_status.json',
            'declared_source': 'scripts/code_sync_from_origin.sh',
            'authoritative_source': 'прод-дерево (отчёт пишется там)',
            'observed_source': 'data/code_sync_status.json',
            'derived_source': None,
            'authority_status': 'DECLARED',
            'authority_established_by': 'поле source внутри файла',
            'authority_limit': 'result=IN_SYNC относится только к тому, что checkout МОЖЕТ '
                               'сойти; удалённое на origin он не удаляет и называет '
                               'отдельно в retired_code',
            'observed': {'result': sync_report.get('result'),
                         'detail': sync_report.get('detail'),
                         'files_changed': sync_report.get('files_changed'),
                         'origin_main': sync_report.get('origin_main'),
                         'retired_code_count': len(retired),
                         'retired_instructions_count':
                             len(sync_report.get('retired_instructions') or [])},
            'observed_at': sync_report.get('timestamp'),
            'drift_status': 'GENERATED',
            'severity': 'INFO',
            'severity_basis': SEVERITY_RULES['GENERATED'][1],
            'origin_present': False, 'production_present': True,
            'evidence': [_evidence('file', 'отчёт последнего запуска синхронизации с его '
                                           'собственным временем')],
        })
    return out


# ── entities whose authority is NOT established anywhere ─────────────────────

def _undefined(kind, entity_id, path, observed, statements, status='AUTHORITY_UNDEFINED'):
    model = AUTHORITY_MODEL[kind]
    severity, why = SEVERITY_RULES[status]
    return {
        'entity_id': entity_id, 'entity_type': kind, 'path': path,
        'declared_source': model['declared_source'],
        'authoritative_source': model['authoritative_source'],
        'observed_source': model['observed_source'],
        'derived_source': model['derived_source'],
        'authority_status': model['authority_status'],
        'authority_established_by': model['established_by'],
        'authority_limit': model['limit'],
        'observed': observed,
        'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'drift_status': status, 'severity': severity, 'severity_basis': why,
        'origin_present': None, 'production_present': True,
        'statements': statements,
        'evidence': [_evidence('snapshot', 'стадии и адресные пробы из принятого снимка '
                                           'Cartographer')],
    }


def launchd_entities(snapshot, manifest, registry):
    """Declared vs observed, and the membership question nobody has settled."""
    declared = {a['label'] for a in (manifest or {}).get('agents') or []
                if isinstance(a, dict) and a.get('label')}
    registered = {a['label'] for a in (registry or {}).get('agents') or []
                  if isinstance(a, dict) and a.get('label')}
    observed = {e['id']: e for e in (snapshot or {}).get('entities') or []
                if isinstance(e, dict) and e.get('id')}
    out = []
    for label in sorted(declared | registered | set(observed)):
        entity = observed.get(label, {})
        stages = entity.get('stages') or {}
        loaded, running = stages.get('LOADED'), stages.get('RUNNING')
        in_manifest, in_registry = label in declared, label in registered
        if in_manifest and loaded is False:
            status = 'DECLARED_NOT_OBSERVED'
        elif not in_manifest and loaded is True:
            status = 'OBSERVED_NOT_DECLARED'
        elif loaded is None:
            status = 'UNKNOWN'
        elif in_manifest != in_registry:
            status = 'AUTHORITY_UNDEFINED'
        elif loaded is True:
            status = 'IN_SYNC'
        else:
            status = 'UNKNOWN'
        statements = [
            {'source': 'architecture/manifest.json',
             'says': f'объявлен: {in_manifest}' + (f", intent={entity.get('intent')}"
                                                   if entity.get('intent') else '')},
            {'source': 'data/agent_registry.json', 'says': f'в реестре: {in_registry}'},
            {'source': 'launchctl print <domain>/<label>',
             'says': f'LOADED={loaded}, RUNNING={running}'},
        ]
        out.append(_undefined('launchd_agent', f'launchd_agent:{label}', label,
                              {'in_manifest': in_manifest, 'in_registry': in_registry,
                               'stages': {k: stages.get(k) for k in
                                          ('DECLARED', 'REGISTERED', 'INSTALLED',
                                           'LOADED', 'RUNNING')},
                               'status_in_snapshot': entity.get('status')},
                              statements, status))
    return out


def plist_entities(snapshot, production):
    """The repo's plist declarations against what is actually installed."""
    declared = (snapshot or {}).get('declared_plists_in_repo') or {}
    out = []
    for entity in (snapshot or {}).get('entities') or []:
        installed = entity.get('installed_paths') or []
        label = entity.get('id')
        repo_copy = declared.get(label) or entity.get('declared_plist_in_repo')
        if not installed and repo_copy:
            status = 'DECLARED_NOT_OBSERVED'
        elif installed and not repo_copy:
            status = 'OBSERVED_NOT_DECLARED'
        elif installed and repo_copy:
            status = 'AUTHORITY_UNDEFINED'
        else:
            continue
        out.append(_undefined(
            'installed_plist', f'installed_plist:{label}', label,
            {'declared_in_repo': repo_copy,
             'installed_paths': [p.get('plist') for p in installed],
             'entrypoints': [(p.get('entrypoint') or {}).get('target') for p in installed]},
            [{'source': '<repo>/launchd/', 'says': f'объявлен: {bool(repo_copy)}'},
             {'source': '~/Library/LaunchAgents и системные каталоги',
              'says': f'установлено копий: {len(installed)}'}],
            status))
    return out


def excluded_entities(production):
    """Paths the sync itself declares it never carries. Not drift — a declared boundary."""
    out = []
    for rel in NEVER_SYNCED:
        p = Path(production) / rel
        model = AUTHORITY_MODEL['excluded_path']
        severity, why = SEVERITY_RULES['IGNORED']
        out.append({
            'entity_id': f'excluded_path:{rel}', 'entity_type': 'excluded_path',
            'path': rel,
            'declared_source': model['declared_source'],
            'authoritative_source': model['authoritative_source'],
            'observed_source': model['observed_source'],
            'derived_source': model['derived_source'],
            'authority_status': model['authority_status'],
            'authority_established_by': model['established_by'],
            'authority_limit': model['limit'],
            'observed': {'present': p.exists(),
                         'entries': len(list(p.iterdir())) if p.is_dir() else None},
            'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'drift_status': 'IGNORED', 'severity': severity, 'severity_basis': why,
            'origin_present': None, 'production_present': p.exists(),
            'evidence': [_evidence('rule', 'синхронизатор объявляет этот путь вне области: '
                                           '«NEVER data/ (live track), docs/, '
                                           'nimbalyst-local/, KANBAN.json»')],
        })
    return out


def generated_entities(production):
    """Files a production agent rewrites in place. Comparing them to origin is meaningless."""
    out = []
    for rel, producer in (('data/agent_registry.json', 'агент флота'),
                          ('data/code_sync_status.json', 'code_sync_from_origin.sh'),
                          ('KANBAN.json', 'агенты цикла (поле updated_by)')):
        p = Path(production) / rel
        if not p.exists():
            continue
        model = AUTHORITY_MODEL['generated_state']
        severity, why = SEVERITY_RULES['GENERATED']
        stat = p.stat()
        out.append({
            'entity_id': f'generated_state:{rel}', 'entity_type': 'generated_state',
            'path': rel,
            'declared_source': producer,
            'authoritative_source': model['authoritative_source'],
            'observed_source': model['observed_source'],
            'derived_source': None,
            'authority_status': model['authority_status'],
            'authority_established_by': model['established_by'],
            'authority_limit': model['limit'],
            'observed': {'mtime': dt.datetime.fromtimestamp(
                stat.st_mtime, dt.timezone.utc).isoformat(), 'size_bytes': stat.st_size},
            'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'drift_status': 'GENERATED', 'severity': severity, 'severity_basis': why,
            'origin_present': None, 'production_present': True,
            'evidence': [_evidence('file', f'файл переписывается в проде: {producer}')],
        })
    return out


def artifact_entities(snapshot):
    """Declared artifacts against their DECLARED SLO. Stale evidence, not a verdict."""
    out = []
    for entity in (snapshot or {}).get('entities') or []:
        for output in entity.get('declared_outputs') or []:
            rel = output.get('relpath')
            if not rel:
                continue
            if output.get('exists') is None:
                status = 'UNKNOWN'
            elif output.get('fresh') is False:
                status = 'STALE'
            elif output.get('exists') is False:
                status = 'DECLARED_NOT_OBSERVED'
            else:
                continue
            model = AUTHORITY_MODEL['declared_artifact']
            severity, why = SEVERITY_RULES[status]
            out.append({
                'entity_id': f'declared_artifact:{entity["id"]}:{rel}',
                'entity_type': 'declared_artifact', 'path': rel,
                'declared_source': model['declared_source'],
                'authoritative_source': model['authoritative_source'],
                'observed_source': model['observed_source'],
                'derived_source': model['derived_source'],
                'authority_status': model['authority_status'],
                'authority_established_by': model['established_by'],
                'authority_limit': model['limit'],
                'observed': {'declared_by': entity['id'], 'exists': output.get('exists'),
                             'fresh': output.get('fresh'),
                             'slo_hours': output.get('slo_hours'),
                             'age_seconds': output.get('age_seconds'),
                             'producer_attribution': 'UNKNOWN'},
                'observed_at': (snapshot or {}).get('finished_at'),
                'drift_status': status, 'severity': severity, 'severity_basis': why,
                'origin_present': None, 'production_present': bool(output.get('exists')),
                'evidence': [_evidence('snapshot', 'метаданные файла и объявленный '
                                                   'slo_hours из манифеста')],
            })
    return out


# ── assembly ────────────────────────────────────────────────────────────────

def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def build_authority_map(production, cartographer_set):
    """The whole map. Read-only; every status carries its evidence."""
    production = Path(production).resolve()
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    origin_sha = resolve_origin(production)
    if origin_sha is None:
        raise AuthorityInputError(
            'авторитетный коммит origin/main не разрешён; карта не строится — это НЕ '
            '«расхождений нет»')
    snapshot = _read_json(Path(cartographer_set) / 'snapshot.json')
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('entities'), list):
        raise AuthorityInputError(
            f'снимок Cartographer в {cartographer_set} не прочитан или не той формы')
    manifest = _read_json(production / 'architecture/manifest.json')
    registry = _read_json(production / 'data/agent_registry.json')
    sync = _read_json(production / 'data/code_sync_status.json')

    comparison = compare_scope(production, origin_sha)
    entities = (code_entities(production, origin_sha, comparison, sync)
                + launchd_entities(snapshot, manifest, registry)
                + plist_entities(snapshot, production)
                + excluded_entities(production)
                + generated_entities(production)
                + artifact_entities(snapshot))

    ids = [e['entity_id'] for e in entities]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise AuthorityInputError(f'entity_id должны быть уникальны; коллизии: {dup[:5]}')
    for e in entities:
        if e['drift_status'] not in DRIFT_STATUSES:
            raise AuthorityInputError(f'{e["entity_id"]}: неизвестный drift_status '
                                      f'{e["drift_status"]}')
        if e['severity'] not in SEVERITIES:
            raise AuthorityInputError(f'{e["entity_id"]}: неизвестная severity')
        if not e.get('evidence'):
            raise AuthorityInputError(f'{e["entity_id"]}: статус без evidence')

    by_status, by_severity, by_type, by_authority = {}, {}, {}, {}
    for e in entities:
        by_status[e['drift_status']] = by_status.get(e['drift_status'], 0) + 1
        by_severity[e['severity']] = by_severity.get(e['severity'], 0) + 1
        by_type[e['entity_type']] = by_type.get(e['entity_type'], 0) + 1
        by_authority[e['authority_status']] = by_authority.get(e['authority_status'], 0) + 1

    chain = []
    for step in DELIVERY_CHAIN:
        observed = None
        if step['observed_state_field'] == 'origin_head':
            observed = {'origin_main': origin_sha}
        elif step['observed_state_field'] == 'code_sync':
            observed = {'result': (sync or {}).get('result'),
                        'origin_main_seen': (sync or {}).get('origin_main'),
                        'files_changed': (sync or {}).get('files_changed'),
                        'retired_code': len((sync or {}).get('retired_code') or [])}
        elif step['observed_state_field'] == 'code_sync.timestamp':
            observed = {'last_run': (sync or {}).get('timestamp')}
        elif step['observed_state_field'] == 'launchd':
            loaded = sum(1 for e in snapshot['entities']
                         if (e.get('stages') or {}).get('LOADED') is True)
            observed = {'labels_observed': len(snapshot['entities']),
                        'loaded': loaded,
                        'snapshot_taken_at': snapshot.get('finished_at')}
        chain.append({**step, 'observed_state': observed})

    the_map = {
        'schema_version': AUTHORITY_SCHEMA,
        'built_started_at': started,
        'built_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'volatile_fields': ['built_started_at', 'built_at', 'observed_at',
                            'semantic_digest'],
        'derived_state': True,
        'read_only': True,
        'auto_fix_performed': False,
        'creates_no_second_ssot': 'карта ничего не объявляет источником правды сама: она '
                                  'цитирует правило, которое это уже сделало, а где '
                                  'правила нет — ставит AUTHORITY_UNDEFINED',
        'production_root': str(production),
        'authoritative_commit': origin_sha,
        'authoritative_commit_basis': 'remote-tracking ref разрешён в коммит ОДИН раз '
                                      'до всех зависимых чтений (контракт Phase 0C)',
        'sync_scope': list(SYNC_SCOPE),
        'never_synced': list(NEVER_SYNCED),
        'authority_model': AUTHORITY_MODEL,
        'drift_statuses': list(DRIFT_STATUSES),
        'drift_status_definitions': dict(DRIFT_STATUS_DEFINITIONS),
        'drift_status_scope': {k: list(v) for k, v in DRIFT_STATUS_SCOPE.items()},
        'taxonomy_note': 'EXTRA_IN_PRODUCTION и MISSING_IN_ORIGIN различает ОТСЛЕЖИВАЕМОСТЬ '
                         'пути в git, а не название; OBSERVED_NOT_DECLARED относится к '
                         'сущностям, а не к файлам, и с ними пересечься не может',
        'severity_rules': {k: {'severity': v[0], 'basis': v[1]}
                           for k, v in SEVERITY_RULES.items()},
        'delivery_chain': chain,
        'entities': entities,
        'counts': {'entities': len(entities), 'by_drift_status': by_status,
                   'by_severity': by_severity, 'by_entity_type': by_type,
                   'by_authority_status': by_authority,
                   'files_in_authoritative_commit': len(comparison['in_origin'])},
        'observation_times': {
            'authoritative_commit_read_at': started,
            'machine_observed_at': snapshot.get('finished_at'),
            'sync_report_written_at': (sync or {}).get('timestamp'),
            'map_built_at': None,
            'note': 'четыре разных момента; карта их не смешивает',
        },
        'limits': [
            'Карта только ЧИТАЕТ: ничего не удаляет, не синхронизирует и не исправляет.',
            'EXTRA_IN_PRODUCTION — спроектированный исход канонического пути: checkout '
            'не удаляет то, что удалено на origin, и сам синхронизатор называет такие '
            'файлы в retired_code.',
            'Сравнение содержимого идёт против ОДНОГО закреплённого коммита; сдвиг '
            'коммита между прогонами делает списки несопоставимыми.',
            'Где правило каноничности не объявлено — AUTHORITY_UNDEFINED, и карта не '
            'выбирает победителя.',
            'Severity фактическая: каждая ссылается на писаное правило или наблюдаемое '
            'следствие, бизнес-оценки нет.',
        ],
    }
    the_map['observation_times']['map_built_at'] = the_map['built_at']
    the_map['semantic_digest'] = semantic_digest(the_map)
    return the_map


VOLATILE_KEYS = ('built_started_at', 'built_at', 'volatile_fields', 'semantic_digest',
                 'observation_times')


def semantic_view(the_map):
    """The map minus its clock fields — including the per-entity observation stamps."""
    kept = {k: v for k, v in the_map.items() if k not in VOLATILE_KEYS}
    kept['entities'] = [{k: v for k, v in e.items() if k != 'observed_at'}
                        for e in kept.get('entities', [])]
    return kept


def semantic_digest(the_map):
    blob = json.dumps(semantic_view(the_map), sort_keys=True, ensure_ascii=False,
                      default=str)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def validate_authority_map(the_map, where):
    required = {'schema_version': str, 'authoritative_commit': str, 'entities': list,
                'counts': dict, 'authority_model': dict, 'delivery_chain': list,
                'drift_statuses': list, 'severity_rules': dict, 'limits': list,
                'sync_scope': list, 'never_synced': list, 'observation_times': dict,
                'drift_status_definitions': dict, 'drift_status_scope': dict}
    if not isinstance(the_map, dict):
        raise AuthorityInputError(f'{where}: карта не объект')
    if the_map.get('schema_version') != AUTHORITY_SCHEMA:
        raise AuthorityInputError(
            f'{where}: неподдерживаемая схема {the_map.get("schema_version")!r}, '
            f'ожидается {AUTHORITY_SCHEMA}')
    for key, kind in required.items():
        if not isinstance(the_map.get(key), kind):
            raise AuthorityInputError(f'{where}: поле `{key}` отсутствует или не '
                                      f'{kind.__name__}')
    if not re.fullmatch(r'[0-9a-f]{40}', the_map['authoritative_commit']):
        raise AuthorityInputError(f'{where}: authoritative_commit не 40-hex')
    seen = set()
    for i, e in enumerate(the_map['entities']):
        for key in ('entity_id', 'entity_type', 'drift_status', 'severity', 'evidence'):
            if not e.get(key):
                raise AuthorityInputError(f'{where}: entities[{i}] без `{key}`')
        if e['drift_status'] not in DRIFT_STATUSES:
            raise AuthorityInputError(f'{where}: entities[{i}] неизвестный drift_status')
        if e['severity'] not in SEVERITIES:
            raise AuthorityInputError(f'{where}: entities[{i}] неизвестная severity')
        scope = DRIFT_STATUS_SCOPE.get(e['drift_status'])
        if scope and e['entity_type'] not in scope:
            raise AuthorityInputError(
                f'{where}: entities[{i}] — статус {e["drift_status"]} не применим к типу '
                f'{e["entity_type"]}')
        if e['entity_id'] in seen:
            raise AuthorityInputError(f'{where}: дубль entity_id {e["entity_id"]!r}')
        seen.add(e['entity_id'])
    counted = the_map['counts'].get('entities')
    if counted != len(the_map['entities']):
        raise AuthorityInputError(
            f'{where}: counts.entities={counted} расходится с {len(the_map["entities"])}')
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--production', type=Path, default=Path.home() / 'Documents/SPA_Claude')
    ap.add_argument('--cartographer', type=Path, required=True,
                    help='принятый комплект Cartographer (наблюдение машины)')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)
    final = Path(args.output)
    if final.exists():
        raise SystemExit(f'{final} уже существует; каждый прогон пишет новый каталог')
    try:
        the_map = build_authority_map(args.production, args.cartographer)
        validate_authority_map(the_map, 'freshly built')
    except AuthorityInputError as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\nКарта не построена. Это НЕ '
                         '«расхождений нет».')
    staging = final.with_name(final.name + '.incomplete')
    staging.mkdir(parents=True, mode=0o700)
    p = staging / 'authority_map.json'
    with p.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(the_map, indent=2, ensure_ascii=False) + '\n')
    p.chmod(0o600)
    os.rename(staging, final)
    c = the_map['counts']
    print(f"Авторитетный коммит: {the_map['authoritative_commit'][:12]}")
    print(f"Объектов: {c['entities']} · по статусу: {c['by_drift_status']}")
    print(f"По severity: {c['by_severity']}")
    print(f"Карта → {final / 'authority_map.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
