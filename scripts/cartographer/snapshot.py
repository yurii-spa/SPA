#!/usr/bin/env python3
"""Read-only SPA inventory (Cartographer, Phase 0B).

Only --output is written; nothing in production is touched and no runtime module is
imported. Every probe failure becomes an explicit UNKNOWN, never a silent absence.

PRIVACY CONTRACT (enforced by tests):
  * process argv and environment are never requested (``ps -o comm``, not ``-o args``);
  * plist ``ProgramArguments`` is reduced to one entrypoint path + an argument COUNT —
    no other element is stored, because an argument can carry a token or a prompt;
  * plist ``EnvironmentVariables`` contributes KEY NAMES only, never values;
  * stderr and remote URLs are never serialized; a failed probe reports an error CLASS.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import time
import urllib.request

SNAPSHOT_SCHEMA = 'cartographer.snapshot/0.3'

#: Governance documents a later comparison may want to point at. NOT a second registry:
#: no agent is listed, only documents that already exist in the repository. Each is
#: resolved TWICE and the two answers are kept apart, because they are different facts:
#: presence in the pinned commit's `docs/**` index and presence in the production tree.
REFERENCE_DOCUMENTS = (
    'CLAUDE.md',
    '.claude/rules/deployment.md',
    '.claude/rules/acceptance.md',
    'docs/SYSTEM_MAP.md',
    'docs/STATE.md',
    'docs/decisions/INDEX.md',
    'architecture/manifest.json',
    'data/agent_registry.json',
    'data/code_sync_status.json',
    'scripts/code_sync_from_origin.sh',
)

STAGES = ('DECLARED', 'REGISTERED', 'INSTALLED', 'LOADED', 'RUNNING', 'PRODUCING_OUTPUT', 'HEALTHY')
STATUSES = ('LIVE', 'DEGRADED', 'STALE', 'LEGACY', 'DEAD', 'ORPHANED', 'UNKNOWN', 'DUPLICATED')
BASES = ('declaration', 'observation', 'static_inference')

# Same scope as scripts/code_sync_from_origin.sh; that mutating script is never executed.
CODE_PATHS = ('spa_core', 'scripts', 'tests', 'architecture', 'push_to_github.py',
              'push_to_github_batch.py', 'CLAUDE.md', '.claude/rules')

LABEL_RE = re.compile(r'com\.(?:spa|ollama)\.[A-Za-z0-9_.-]+')
#: Interpreters whose first argv element is not the entrypoint.
INTERPRETERS = ('bash', 'sh', 'zsh', 'python', 'python3', 'node', 'ruby', 'perl', 'env')
#: Safe, static declaration some wrappers carry about the module they will run.
AGENT_MODULE_RE = re.compile(r'^#\s*AGENT_MODULE:\s*([A-Za-z0-9_.]+)\s*$', re.M)
#: ADR identifier at the START of a filename: ADR-129 · ADR-YL-004 · ADR-AI1-004.
ADR_ID_RE = re.compile(r'ADR-(?:[A-Za-z]+[0-9]*-)*[0-9]+')


#: Fixed reason codes for an unresolved entrypoint. The TEXT is constant: interpolating
#: any argv element here leaked option VALUES into `unknown_reason`, and from there into
#: snapshot.json, findings.json, system_map.json and the Markdown. An option can be
#: `--api-key=<secret>`, so nothing from argv is ever formatted into a diagnostic.
ENTRYPOINT_REASONS = {
    'NO_PROGRAM_OR_ARGV': 'plist declares neither Program nor a usable ProgramArguments',
    'ENV_FORM_UNSUPPORTED': '`env` launch form is not parsed: the real executable is hidden '
                            'behind assignments; wrapper NOT executed',
    'INTERPRETER_WITHOUT_TARGET': 'interpreter invoked with no target argument',
    'SHELL_INLINE_COMMAND': 'inline `-c` command form: the command string is not stored (it '
                            'can carry secrets) and the wrapper is NOT executed, so the '
                            'target stays UNKNOWN',
    'SHELL_OPTION_UNSUPPORTED': 'shell invoked with an unsupported option form; the option '
                                'text is deliberately not stored',
    'PYTHON_OPTION_UNSUPPORTED': 'python invoked with an unsupported option form; the option '
                                 'text is deliberately not stored',
    'PYTHON_MODULE_MISSING_NAME': '`python -m` without a module name',
    'INTERPRETER_OPTION_UNSUPPORTED': 'interpreter invoked with an unsupported option form; '
                                      'the option text is deliberately not stored',
    'SCRIPT_MISSING_ON_DISK': 'declared script does not exist on disk; a later argument is '
                              'deliberately NOT substituted for it',
}

# ── probes: failure is a value, not an empty string ──────────────────────────

def _exec(args, cwd=None, timeout=25):
    """Run a read-only command. Returns {'ok', 'out', 'rc', 'error'}.

    ``error`` is an error CLASS ('timeout' / 'oserror' / 'exit_nonzero'), never stderr:
    stderr can carry credentials, remote URLs and prompt text.
    """
    try:
        p = subprocess.run(args, cwd=cwd,
                           env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0'},
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'out': None, 'rc': None, 'error': 'timeout'}
    except OSError:
        return {'ok': False, 'out': None, 'rc': None, 'error': 'oserror'}
    if p.returncode != 0:
        return {'ok': False, 'out': None, 'rc': p.returncode, 'error': 'exit_nonzero'}
    return {'ok': True, 'out': p.stdout, 'rc': 0, 'error': None}


def run(args, cwd=None):
    """Backwards-compatible helper: stdout on success, None on any failure."""
    return _exec(args, cwd)['out']


def git(repo, *args):
    return run(['git', '-c', 'core.fsmonitor=false', *args], repo)


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def meta(path):
    """Filesystem facts. ``lstat`` first so a symlink is NAMED, not silently followed."""
    p = Path(path)
    out = {'path': str(p), 'is_symlink': os.path.islink(p)}
    try:
        s = p.stat()
    except FileNotFoundError:
        out.update(exists=False)
        return out
    except OSError:
        out.update(exists=None, unknown_reason='stat failed')
        return out
    out.update(exists=True, size_bytes=s.st_size, mtime_epoch=s.st_mtime,
               age_seconds=max(0, round(time.time() - s.st_mtime)))
    return out


# ── classification ──────────────────────────────────────────────────────────

def classify(stages, intent=None, last_exit=None, outputs=None, duplicate=False):
    """Component status. Absence of a PID is never DEAD; DEAD needs retirement evidence.

    ``last_exit`` is HISTORICAL — launchctl keeps the previous exit status, so it is
    consulted only after RUNNING has been checked.
    """
    if duplicate:
        return 'DUPLICATED'
    if stages['LOADED'] is True and stages['INSTALLED'] is False:
        return 'ORPHANED'
    if intent in ('retired', 'legacy', 'disabled'):
        return 'DEGRADED' if stages['LOADED'] else 'LEGACY'
    if outputs and any(x.get('fresh') is False for x in outputs):
        return 'STALE'
    if stages['RUNNING'] is True:
        return 'LIVE'
    if last_exit not in (None, 0):
        return 'DEGRADED'
    if stages['LOADED'] is True:
        return 'LIVE'  # Scheduled idle is not dead.
    if stages['INSTALLED'] is True and intent == 'active' and stages['LOADED'] is False:
        return 'DEGRADED'
    return 'UNKNOWN'


# ── git drift: the comparison basis is named, never implied ──────────────────

def resolve_baseline(repo, ref='refs/remotes/origin/main'):
    """Resolve a mutable ref to ONE immutable SHA, once, before any dependent read.

    A remote-tracking ref moves — a background sync or another session can advance it
    between two git calls. The earlier code read the REF name in `ls-tree` and `diff` and
    then read `rev-parse` separately, so a comparison could straddle two different trees
    while claiming to be pinned. Returns None when the ref cannot be resolved: then the
    comparison is UNKNOWN, never a result against an unnamed baseline.
    """
    sha = (git(repo, 'rev-parse', '--verify', f'{ref}^{{commit}}') or '').strip() or None
    return sha if sha and re.fullmatch(r'[0-9a-f]{40}', sha) else None


def drift(repo, ref='refs/remotes/origin/main', baseline_sha=None):
    """Drift against ONE pinned commit. Three populations that differ in meaning.

    ``production_only_*`` is NOT 'retired' and NOT 'unneeded' — it is only 'absent from
    the commit we compared against'. Nothing is deleted or corrected here.

    Every ref-dependent read uses ``baseline_sha``; the ref NAME is kept only as
    provenance. The working tree itself remains non-atomic — a separate, documented limit.
    """
    sha = baseline_sha or resolve_baseline(repo, ref)
    if sha is None:
        return None
    names = git(repo, 'ls-tree', '-r', '--name-only', '-z', sha, '--', *CODE_PATHS)
    diff = git(repo, '-c', 'core.fileMode=false', 'diff', '--no-ext-diff', '--no-textconv',
               '--name-only', '-z', sha, '--', *CODE_PATHS)
    untracked = git(repo, 'ls-files', '--others', '--exclude-standard', '-z', '--', *CODE_PATHS)
    if names is None or diff is None or untracked is None:
        return None
    origin = set(filter(None, names.split('\0')))
    changed = set(filter(None, diff.split('\0')))
    extra = set(filter(None, untracked.split('\0')))
    # lexists, not exists: a dangling symlink is present on disk and must not vanish here.
    return {
        'scope': list(CODE_PATHS),
        'basis': 'pinned_commit',
        'reference': ref,
        'reference_sha': sha,
        'reference_note': 'resolved ONCE to this commit before any dependent read; the ref '
                          'name is provenance only. Cached ref, NOT a live server query',
        'changed_or_missing_on_disk': sorted(changed & origin),
        'production_only_tracked': sorted(p for p in changed - origin
                                          if os.path.lexists(repo / p)),
        'production_only_untracked': sorted(extra - origin),
        'production_only_note': 'absent from the compared ref; not evidence of retirement',
        'ignored_files': 'not inventoried',
        'auto_fix': False,
    }


def worktrees(repo):
    raw = git(repo, 'worktree', 'list', '--porcelain')
    if raw is None:
        return None
    result = []
    for block in raw.strip().split('\n\n'):
        row = {}
        for line in block.splitlines():
            k, _, v = line.partition(' ')
            if k in ('worktree', 'HEAD', 'branch'):
                row[k] = v
            elif k in ('bare', 'detached', 'prunable', 'locked'):
                row[k] = True
        if row:
            p = Path(row['worktree'])
            row['exists'] = p.exists()
            row['observed_head'] = ((git(p, 'rev-parse', 'HEAD') or '').strip() or None) if p.exists() else None
            row['code_drift_vs_cached_ref'] = drift(p) if p.exists() else None
            result.append(row)
    return result


# ── launchd: domains are probed, absence is not assumed ─────────────────────

def parse_domain_print(text):
    """Split `launchctl print <domain>` into the blocks that mean different things.

    ``services = { … }`` lists REGISTERED services — that is what "loaded" means.
    ``disabled services = { … }`` lists enable/disable OVERRIDES — a setting that exists
    whether or not any service is registered. Conflating the two is exactly the defect
    this function was written to remove: a regex over the whole output reported
    `com.spa.httpserver` as loaded because an `=> enabled` override mentions it, while
    `launchctl print gui/<uid>/com.spa.httpserver` answers "could not find service".
    """
    services, overrides = {}, {}
    block = None
    for line in (text or '').splitlines():
        stripped = line.strip()
        if re.match(r'^services\s*=\s*\{$', stripped):
            block = 'services'
            continue
        if re.match(r'^disabled services\s*=\s*\{$', stripped):
            block = 'overrides'
            continue
        if stripped == '}':
            if block in ('services', 'overrides'):
                block = None
            continue
        if block == 'services':
            cols = stripped.split()
            if len(cols) >= 3 and LABEL_RE.fullmatch(cols[-1]):
                services[cols[-1]] = {
                    'pid': int(cols[0]) if cols[0].isdigit() and cols[0] != '0' else None,
                    'status': int(cols[1]) if re.fullmatch(r'-?\d+', cols[1]) else None,
                }
        elif block == 'overrides':
            hit = re.match(r'^"([^"]+)"\s*=>\s*(\w+)$', stripped)
            if hit and LABEL_RE.fullmatch(hit.group(1)):
                overrides[hit.group(1)] = hit.group(2)
    return services, overrides


def launchd_domains(uid=None):
    """Observe each queryable launchd domain separately.

    Absence of a label in the user domain does NOT prove absence system-wide, so each
    domain carries its own ``readable`` flag, its own REGISTERED service set and its own
    enable/disable overrides. LOADED stays UNKNOWN while any domain is unreadable.
    """
    uid = os.getuid() if uid is None else uid
    out = {}
    for name in (f'gui/{uid}', 'system'):
        r = _exec(['launchctl', 'print', name])
        services, overrides = parse_domain_print(r['out']) if r['ok'] else ({}, {})
        out[name] = {
            'readable': r['ok'],
            'error': r['error'],
            'services': sorted(services) if r['ok'] else None,
            'service_detail': services if r['ok'] else None,
            'enable_overrides': overrides if r['ok'] else None,
            'method': '`launchctl print <domain>` parsed by block: registered services and '
                      'enable/disable overrides are kept apart',
        }
    return out


def service_target(domain, label):
    """Targeted proof for one service target: 'present' | 'absent' | 'unknown'.

    ``launchctl print <domain>/<label>`` exits non-zero both for "no such service" and
    for other errors, so the two are separated by CLASSIFYING stderr — the text itself is
    never stored, only the resulting class.
    """
    try:
        p = subprocess.run(['launchctl', 'print', f'{domain}/{label}'],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'
    if p.returncode == 0:
        return 'present'
    if 'could not find service' in (p.stderr or '').lower():
        return 'absent'
    return 'unknown'


def launchctl_list():
    """`launchctl list` — the only probe that yields pid and the HISTORICAL last_exit."""
    r = _exec(['launchctl', 'list'])
    rows = {}
    for line in (r['out'] or '').splitlines():
        cols = line.split()
        if len(cols) == 3 and cols[2].startswith(('com.spa.', 'com.ollama.')):
            rows[cols[2]] = {
                'pid': int(cols[0]) if cols[0].isdigit() else None,
                'last_exit': int(cols[1]) if re.fullmatch(r'-?\d+', cols[1]) else None,
            }
    return rows, r['ok']


# ── entrypoint extraction: one path, an argument count, nothing else ────────

def entrypoint_from_plist(data, working_directory=None):
    """Reduce a plist to a safe entrypoint record by PARSING THE LAUNCH FORM.

    Returns ``executable`` (what launchd runs), ``target_kind`` in {executable, script,
    module, None}, ``target``, ``target_exists``, ``argument_count`` and, when the form is
    not supported, ``unknown_reason``.

    The earlier version scanned argv for the first element that happened to exist on disk.
    That is wrong and was reproduced: ``["/bin/bash", "/nonexistent/agent.sh", "/tmp"]``
    yielded ``/tmp`` as the entrypoint, and ``bash -c <cmd> /tmp`` did too. A missing script
    is now reported as missing and NEVER replaced by a later argument; an unsupported form
    (``-c`` inline command, ``env VAR=...``) stays UNKNOWN. No argv element other than the
    resolved target is ever stored — an argument can carry a token or a prompt.
    """
    rec = {'executable': None, 'target_kind': None, 'target': None, 'target_exists': None,
           'argument_count': None, 'arguments_omitted': True,
           'unknown_code': None, 'unknown_reason': None}

    def unknown(code):
        rec['unknown_code'] = code
        rec['unknown_reason'] = ENTRYPOINT_REASONS[code]
        return rec

    def resolve(value):
        q = Path(value)
        if not q.is_absolute() and working_directory:
            q = Path(working_directory) / q
        return str(q)

    prog = data.get('Program')
    argv = data.get('ProgramArguments')
    if isinstance(argv, list):
        rec['argument_count'] = len(argv)
    if isinstance(prog, str) and prog:
        target = resolve(prog)
        rec.update(executable=target, target_kind='executable', target=target,
                   target_exists=os.path.lexists(target))
        if rec['argument_count'] is None:
            rec['argument_count'] = 0
        return rec
    if not isinstance(argv, list) or not argv or not isinstance(argv[0], str):
        return unknown('NO_PROGRAM_OR_ARGV')

    exe = argv[0]
    rec['executable'] = exe
    name = Path(exe).name
    rest = [a for a in argv[1:] if isinstance(a, str)]

    def script(value, why_missing=True):
        target = resolve(value)
        rec.update(target_kind='script', target=target, target_exists=os.path.lexists(target))
        if why_missing and not rec['target_exists']:
            rec['unknown_code'] = 'SCRIPT_MISSING_ON_DISK'
            rec['unknown_reason'] = ENTRYPOINT_REASONS['SCRIPT_MISSING_ON_DISK']
        return rec

    if name not in INTERPRETERS:
        target = resolve(exe)
        rec.update(target_kind='executable', target=target,
                   target_exists=os.path.lexists(target))
        return rec
    if name == 'env':
        return unknown('ENV_FORM_UNSUPPORTED')
    if not rest:
        return unknown('INTERPRETER_WITHOUT_TARGET')

    first = rest[0]
    if name in ('bash', 'sh', 'zsh'):
        if first == '-c':
            return unknown('SHELL_INLINE_COMMAND')
        if first.startswith('-'):
            return unknown('SHELL_OPTION_UNSUPPORTED')
        return script(first)
    if name in ('python', 'python3'):
        if first == '-m':
            if len(rest) >= 2 and not rest[1].startswith('-'):
                rec.update(target_kind='module', target=rest[1], target_exists=None)
                return rec
            return unknown('PYTHON_MODULE_MISSING_NAME')
        if first.startswith('-'):
            return unknown('PYTHON_OPTION_UNSUPPORTED')
        return script(first)
    if first.startswith('-'):
        return unknown('INTERPRETER_OPTION_UNSUPPORTED')
    return script(first)


def plist_env_keys(data):
    """Environment KEY NAMES only. Values are never read — they can be secrets."""
    env = data.get('EnvironmentVariables')
    return sorted(env.keys()) if isinstance(env, dict) else None


def checkout_of(path):
    """Nearest ancestor that is a git checkout. Observation of path containment."""
    try:
        p = Path(path).resolve()
    except OSError:
        return None
    for candidate in [p, *p.parents]:
        if (candidate / '.git').exists():
            return str(candidate)
    return None


def wrapper_declared_target(path):
    """Static, safe read of a wrapper's own ``# AGENT_MODULE:`` declaration.

    The wrapper is never executed. Absence returns None and the caller records UNKNOWN.
    """
    try:
        if os.path.islink(path):
            return None
        text = Path(path).read_text(encoding='utf-8', errors='replace')[:8000]
    except OSError:
        return None
    hit = AGENT_MODULE_RE.search(text)
    return hit.group(1) if hit else None


# ── documents: an index pinned to one SHA, covering paths AND ADR identifiers ──

def document_index(repo, ref='refs/remotes/origin/main', baseline_sha=None):
    """Index of documents at ONE pinned commit.

    Two lookup keys, because ``governed_by`` carries both kinds: exact repo-relative
    PATHS (``docs/CMO_EDITORIAL_LAYER.md``) and ADR IDENTIFIERS (``ADR-066``). The
    earlier index keyed ADR ids only and looked at ``docs/decisions`` + ``docs/adr``
    alone, so all 12 plain-path references were falsely reported unresolved.

    Returns ``{'sha', 'paths', 'adr', 'available'}``. ``available=False`` means the index
    itself is missing — then "not found" is UNKNOWN (no coverage), not "no document".
    """
    sha = baseline_sha or resolve_baseline(repo, ref)
    if sha is None:
        return {'sha': None, 'paths': None, 'adr': None, 'available': False,
                'reason': 'baseline ref could not be resolved to a commit'}
    # Read BY SHA, not by the ref name: the ref can move between these two calls.
    listing = git(repo, 'ls-tree', '-r', '--name-only', sha, '--', 'docs')
    if listing is None:
        return {'sha': sha, 'paths': None, 'adr': None, 'available': False,
                'reason': 'docs listing unavailable at the pinned commit'}
    paths = [x for x in listing.splitlines() if x]
    adr = {}
    for rel in paths:
        # ANCHORED and non-greedy by construction. `ADR-[A-Za-z0-9-]*\d+` was greedy and
        # swallowed the whole filename: `ADR-129-owner-decisions-2026-08-23-batch4.md`
        # became the key `ADR-129-owner-decisions-2026-08-23-batch4`, so a real reference
        # to `ADR-129` was reported absent although the file exists. Same class as a
        # greedy `\w*` making a word its own label.
        hit = ADR_ID_RE.match(Path(rel).name)
        if hit:
            adr.setdefault(hit.group(0), rel)
    return {'sha': sha, 'paths': sorted(paths), 'adr': adr, 'available': True,
            'scope': 'docs/** at the pinned ref'}


def resolve_document(ref_value, index):
    """Resolve one governed_by reference. Three outcomes, never conflated."""
    if not index.get('available'):
        return {'reference': ref_value, 'outcome': 'index_unavailable', 'path': None,
                'kind': None, 'note': index.get('reason')}
    if '/' in ref_value or ref_value.endswith('.md'):
        hit = ref_value in (index['paths'] or ())
        return {'reference': ref_value, 'kind': 'path',
                'outcome': 'resolved' if hit else 'absent',
                'path': ref_value if hit else None}
    hit = (index['adr'] or {}).get(ref_value)
    return {'reference': ref_value, 'kind': 'adr_id',
            'outcome': 'resolved' if hit else 'absent', 'path': hit}


# ── collection ──────────────────────────────────────────────────────────────

def collect(repo, extra_repos=()):
    start = dt.datetime.now(dt.timezone.utc).isoformat()
    findings = []

    def finding(kind, rule, subject, reason, context=None):
        """Stable id from RULE + entity (+ context), never from the mutable reason text.

        Two different rules on one entity previously collapsed into one id
        (``DRIFT:com.spa.httpserver`` appeared twice). ``rule_code`` is the stable
        discriminator; ``context`` separates repeated rules within one entity.
        """
        fid = f'{rule}:{subject}' + (f':{context}' if context else '')
        findings.append({'id': fid, 'kind': kind, 'rule_code': rule, 'subject': subject,
                         'context': context, 'reason': reason})

    manifest_path = repo / 'architecture/manifest.json'
    registry_path = repo / 'data/agent_registry.json'
    manifest = read_json(manifest_path)
    registry = read_json(registry_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get('agents'), list):
        manifest = None
    if not isinstance(registry, dict) or not isinstance(registry.get('agents'), list):
        registry = None
    declared = {x['label']: x for x in (manifest or {}).get('agents', [])
                if isinstance(x, dict) and 'label' in x}
    registered = {x['label']: x for x in (registry or {}).get('agents', [])
                  if isinstance(x, dict) and 'label' in x}
    for name, value in [('manifest', manifest), ('registry', registry)]:
        if value is None:
            finding('UNKNOWN', 'SOURCE_UNREADABLE', name,
                    'Source unreadable or invalid; absence is not proof of no agents')

    domains = launchd_domains()
    domains_complete = all(d['readable'] for d in domains.values())
    for name, dom in domains.items():
        if not dom['readable']:
            finding('UNKNOWN', 'DOMAIN_UNREADABLE', f'launchd_domain:{name}',
                    f"Domain unreadable ({dom['error']}); absence of a label there is NOT established")
    listed, list_ok = launchctl_list()
    if not list_ok:
        finding('UNKNOWN', 'LAUNCHCTL_LIST_FAILED', 'launchctl_list',
                'launchctl list failed; pid and last_exit unavailable')

    ps_probe = _exec(['ps', '-axo', 'pid=,ppid=,comm='])
    processes = []
    for line in (ps_probe['out'] or '').splitlines():
        cols = line.strip().split(None, 2)
        if len(cols) == 3 and cols[0].isdigit():
            processes.append({'pid': int(cols[0]), 'ppid': int(cols[1]), 'command': cols[2]})
    if not ps_probe['ok']:
        finding('UNKNOWN', 'PS_FAILED', 'processes', f"ps failed ({ps_probe['error']})")
    pids = {x['pid'] for x in processes}

    installed = {}
    install_complete = True
    plist_dirs = [Path.home() / 'Library/LaunchAgents', Path('/Library/LaunchAgents'),
                  Path('/Library/LaunchDaemons')]
    for directory in plist_dirs:
        try:
            for pl_path in sorted(directory.glob('com.spa.*.plist')):
                try:
                    data = plistlib.loads(pl_path.read_bytes())
                    installed.setdefault(data.get('Label', pl_path.stem), []).append((pl_path, data))
                except (OSError, ValueError, plistlib.InvalidFileException):
                    install_complete = False
                    finding('UNKNOWN', 'PLIST_UNREADABLE', str(pl_path), 'Unreadable plist')
        except OSError:
            install_complete = False
            finding('UNKNOWN', 'PLIST_DIR_UNREADABLE', str(directory), 'Cannot enumerate plists')

    declared_plists = {}
    declared_plist_scan_complete = True
    try:
        for pl_path in sorted((repo / 'launchd').glob('com.spa.*.plist')):
            declared_plists[pl_path.stem] = str(pl_path)
    except OSError:
        declared_plist_scan_complete = False
        finding('UNKNOWN', 'DECLARED_PLIST_DIR_UNREADABLE', 'launchd_dir',
                'Cannot enumerate declared plists in repo')

    baseline = resolve_baseline(repo)
    if baseline is None:
        finding('UNKNOWN', 'BASELINE_UNRESOLVED', str(repo),
                'Comparison baseline ref could not be resolved to a commit; drift and\n'
                'document resolution are UNKNOWN rather than measured against an\n'
                'unnamed tree')
    docs = document_index(repo, baseline_sha=baseline)
    if not docs['available']:
        finding('UNKNOWN', 'DOC_INDEX_UNAVAILABLE', 'documents',
                'Document index unavailable at the pinned ref; unresolved references are '
                'a coverage gap, not evidence of a missing document')

    # Enable/disable overrides are SETTINGS, not services. An override for a label with no
    # registered service is a real observation and gets its own rule — it is NOT a
    # contradiction between probes and NOT evidence of being loaded.
    override_only = set()
    for name, dom in domains.items():
        for label, state in (dom['enable_overrides'] or {}).items():
            if label.startswith('com.spa.') and label not in (dom['services'] or ()):
                override_only.add(label)
                finding('UNKNOWN', 'ENABLE_OVERRIDE_WITHOUT_SERVICE', label,
                        f'Domain {name} holds an enable/disable override ({state}) but no '
                        f'registered service; an override is a setting, not a loaded service',
                        context=name)

    candidates = (set(declared) | set(registered) | set(installed)
                  | {k for k in listed if k.startswith('com.spa.')}
                  | {l for d in domains.values() for l in (d['services'] or ()) if l.startswith('com.spa.')}
                  | override_only)

    entities = []
    for label in sorted(candidates):
        d = declared.get(label, {})
        l = listed.get(label, {})
        # LOADED is proven per domain by a TARGETED service-target probe, not by a regex.
        in_domains, probe_unknown = {}, False
        for name, dom in domains.items():
            if not dom['readable']:
                in_domains[name] = None
                probe_unknown = True
                continue
            verdict = service_target(name, label)
            if verdict == 'unknown':
                probe_unknown = True
                in_domains[name] = None
            else:
                in_domains[name] = (verdict == 'present')
        loaded = True if any(v is True for v in in_domains.values()) else (
            None if (probe_unknown or not domains_complete) else False)

        stages = dict.fromkeys(STAGES)
        stages.update(
            DECLARED=label in declared if manifest is not None else None,
            REGISTERED=label in registered if registry is not None else None,
            INSTALLED=label in installed if install_complete else None,
            LOADED=loaded,
            RUNNING=(l.get('pid') in pids) if (ps_probe['ok'] and list_ok and l.get('pid')) else (
                False if (ps_probe['ok'] and list_ok and label in listed) else None),
        )

        outputs = []
        for spec in d.get('produces', []) or []:
            rel = spec.get('artifact', '') if isinstance(spec, dict) else str(spec)
            if not rel:
                continue
            raw = repo / rel
            try:
                resolved = raw.resolve()
            except OSError:
                finding('UNKNOWN', 'DECLARED_OUTPUT_UNRESOLVABLE', label,
                        'Declared output path unresolvable', context=rel)
                continue
            if not resolved.is_relative_to(repo.resolve()):
                finding('UNKNOWN', 'DECLARED_OUTPUT_ESCAPES_REPO', label,
                        'Declared output resolves outside the repository (symlink escape) — omitted',
                        context=rel)
                continue
            m = meta(raw)
            slo = spec.get('slo_hours') if isinstance(spec, dict) else None
            m['relpath'] = rel
            m['slo_hours'] = slo
            m['fresh'] = ((m.get('age_seconds', float('inf')) <= slo * 3600)
                          if isinstance(slo, (int, float)) and m.get('exists') is True else None)
            m['producer_attribution'] = 'UNKNOWN'
            outputs.append(m)

        intent = d.get('intent')
        status = classify(stages, intent, l.get('last_exit'), outputs,
                          len(installed.get(label, [])) > 1)
        paths = []
        for pl_path, pl in installed.get(label, []):
            ep = entrypoint_from_plist(pl, pl.get('WorkingDirectory'))
            target_path = ep['target'] if ep['target_kind'] in ('script', 'executable') else None
            paths.append({
                'plist': str(pl_path),
                'plist_domain_dir': str(pl_path.parent),
                'working_directory': pl.get('WorkingDirectory'),
                'stdout': pl.get('StandardOutPath'),
                'stderr': pl.get('StandardErrorPath'),
                'keep_alive': pl.get('KeepAlive'),
                'start_interval': pl.get('StartInterval'),
                'has_calendar_schedule': 'StartCalendarInterval' in pl,
                'environment_keys': plist_env_keys(pl),
                'entrypoint': ep,
                'entrypoint_checkout': checkout_of(target_path) if target_path and ep['target_exists'] else None,
                'entrypoint_declared_target': (wrapper_declared_target(target_path)
                                               if target_path and ep['target_exists'] else None),
            })
            if ep['target_kind'] is None:
                finding('UNKNOWN', 'ENTRYPOINT_FORM_UNSUPPORTED', label,
                        f"Entrypoint unresolved: {ep['unknown_reason']}",
                        context=Path(pl_path).name)
            elif ep['target_kind'] == 'script' and ep['target_exists'] is False:
                finding('DRIFT', 'ENTRYPOINT_SCRIPT_MISSING', label,
                        'Declared entrypoint script is absent on disk; no later argument was '
                        'substituted for it', context=Path(pl_path).name)
            elif ep['target_kind'] == 'script' and not paths[-1]['entrypoint_declared_target']:
                finding('UNKNOWN', 'WRAPPER_TARGET_UNDECLARED', label,
                        'Wrapper target not statically declared (no AGENT_MODULE); wrapper '
                        'deliberately not executed', context=Path(pl_path).name)

        doc_refs = [resolve_document(g, docs)
                    for g in (d.get('governed_by') or []) if isinstance(g, str)]
        for ref in doc_refs:
            if ref['outcome'] == 'absent':
                finding('DRIFT', 'DOC_REFERENCE_ABSENT', label,
                        f"governed_by references {ref['reference']}, absent from docs/** at "
                        f"pinned {docs['sha'][:12] if docs['sha'] else 'UNKNOWN'}",
                        context=ref['reference'])
            elif ref['outcome'] == 'index_unavailable':
                finding('UNKNOWN', 'DOC_REFERENCE_UNVERIFIABLE', label,
                        f"governed_by references {ref['reference']}; index unavailable so "
                        f"presence is UNKNOWN, not absent", context=ref['reference'])

        entities.append({
            'id': label,
            'status': status,
            'stages': stages,
            'pid': l.get('pid'),
            'last_exit': l.get('last_exit'),
            'last_exit_basis': 'historical: launchctl retains the previous exit status; '
                               'not a current probe',
            'intent': intent,
            'layer': d.get('layer'),
            'role': d.get('role'),
            'schedule': d.get('schedule'),
            'declared_program': d.get('program'),
            'declared_plist_source': d.get('plist_source'),
            'declared_consumes': [c for c in (d.get('consumes') or []) if isinstance(c, str)],
            'declared_governed_by': [g for g in (d.get('governed_by') or []) if isinstance(g, str)],
            'document_references': doc_refs,
            'declared_plist_in_repo': declared_plists.get(label),
            'domains': in_domains,
            'enable_overrides': {n: (d2['enable_overrides'] or {}).get(label)
                                 for n, d2 in domains.items() if d2['readable']},
            'installed_paths': paths,
            'declared_outputs': outputs,
            'evidence': {
                'DECLARED': str(manifest_path),
                'REGISTERED': str(registry_path),
                'INSTALLED': 'plist glob over ' + ', '.join(str(x) for x in plist_dirs),
                'LOADED': 'targeted `launchctl print <domain>/<label>` per domain: '
                          + ', '.join(domains),
                'RUNNING': 'launchctl list PID joined to ps PID (non-atomic)',
            },
            'health_reason': 'No semantic health probe; output mtime does not establish '
                             'producer attribution',
        })
        if status == 'UNKNOWN':
            finding('UNKNOWN', 'STATUS_UNCLASSIFIABLE', label,
                    'No sufficient live-state evidence for classification')
        if status == 'ORPHANED':
            finding('ORPHANED', 'LOADED_WITHOUT_INSTALLED_PLIST', label,
                    'Registered as a service in a launchd domain without an installed plist')
        elif status in ('DEGRADED', 'STALE', 'DUPLICATED'):
            finding('DRIFT', f'STATUS_{status}', label, status)
        if stages['DECLARED'] is False and stages['LOADED']:
            finding('DRIFT', 'LOADED_NOT_IN_MANIFEST', label, 'Loaded but absent from manifest')
        if l.get('pid') and stages['RUNNING'] is False:
            finding('UNKNOWN', 'PID_VANISHED_BETWEEN_PROBES', label,
                    'PID disappeared between launchctl and ps; non-atomic capture')

    finding('UNKNOWN', 'HEALTH_UNMEASURED', 'agent_health',
            'HEALTHY and PRODUCING_OUTPUT unmeasured for all components; artifact metadata only')
    if (repo / 'spa_core/paper_trading/cycle_exit.py').exists():
        finding('UNKNOWN', 'EXIT_SEMANTICS_NOT_APPLIED', 'exit_code_semantics',
                'Production declares a per-label exit-code dictionary '
                '(spa_core/paper_trading/cycle_exit.py); the map does not apply it, so any '
                'DEGRADED inferred from last_exit means "last outcome non-zero", not "broken"')

    repos = []
    for root in [repo, *extra_repos]:
        head = (git(root, 'rev-parse', 'HEAD') or '').strip() or None
        # ONE resolution per repository, reused by every dependent read below.
        cached = baseline if root == repo else resolve_baseline(root)
        remote = git(root, 'ls-remote', 'origin', 'refs/heads/main')
        remote_sha = remote.split()[0] if remote and re.match(r'^[0-9a-f]{40}\s', remote) else None
        measured = drift(root, baseline_sha=cached)
        repos.append({'path': str(root), 'head': head,
                      'cached_origin_main': cached, 'remote_origin_main': remote_sha,
                      'sha_comparison_basis': 'cached remote-tracking ref resolved ONCE to a '
                                              'commit, then reused by every dependent read; '
                                              'compared against a live ls-remote separately',
                      'drift': measured, 'worktrees': worktrees(root)})
        if remote_sha is None:
            finding('UNKNOWN', 'REMOTE_UNAVAILABLE', str(root),
                    'Live remote origin/main unavailable; only the cached ref is known')
        elif remote_sha != cached:
            finding('DRIFT', 'CACHED_VS_REMOTE_DIVERGED', str(root),
                    'Cached origin/main differs from live remote; no fetch performed')
        if measured is None:
            finding('UNKNOWN', 'DRIFT_UNMEASURABLE', str(root), 'Git drift not measurable')
        else:
            for key in ('changed_or_missing_on_disk', 'production_only_tracked',
                        'production_only_untracked'):
                for path in measured[key]:
                    finding('DRIFT', f'DRIFT_{key.upper()}', str(root), key, context=path)

    sync_path = repo / 'data/code_sync_status.json'
    sync = read_json(sync_path)
    sync_safe = ({k: sync.get(k) for k in ('timestamp', 'result', 'origin_main', 'files_changed',
                                           'exec_bits_fixed', 'retired_code', 'retired_instructions')}
                 if isinstance(sync, dict) else None)
    sync_meta = meta(sync_path)
    if sync_safe is None:
        finding('UNKNOWN', 'SYNC_STATUS_UNREADABLE', 'code_sync', 'Missing or invalid status')
    elif (sync_meta.get('age_seconds') or 0) > 3600:
        finding('DRIFT', 'SYNC_STATUS_STALE', 'code_sync',
                'Status file older than one hour; advisory threshold — stale EVIDENCE, not '
                'proven stale code')
    reg_meta = meta(registry_path)
    if (reg_meta.get('age_seconds') or 0) > 26 * 3600:
        finding('DRIFT', 'REGISTRY_STALE', 'agent_registry',
                'Registry older than its own 26h SLO; stale EVIDENCE')

    ollama = {'binary': (run(['which', 'ollama']) or '').strip() or None,
              'launchd': {k: v for k, v in listed.items() if k.startswith('com.ollama.')},
              'api_reachable': False, 'inference_performed': False,
              'routing': 'NOT_INSPECTED_OR_CHANGED'}
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:11434/api/version', timeout=3) as response:
            ollama['api_reachable'] = response.status == 200
    except (OSError, ValueError):
        pass

    # What this run was ABLE to observe. Recorded, not inferred later: a comparison needs
    # it to tell "the finding is gone because it was fixed" from "the probe that saw it
    # did not run". Absence of a value is None (UNKNOWN) and never False.
    coverage = {
        'manifest_readable': manifest is not None,
        'registry_readable': registry is not None,
        'installed_scan_complete': install_complete,
        'declared_plist_scan_complete': declared_plist_scan_complete,
        'launchctl_list_ok': list_ok,
        'ps_ok': ps_probe['ok'],
        'domains_readable': {n: d['readable'] for n, d in domains.items()},
        'domains_complete': domains_complete,
        'document_index_available': docs['available'],
        'sync_status_readable': sync_safe is not None,
        'drift_measurable': {r['path']: r['drift'] is not None for r in repos},
        'baseline_sha': {r['path']: r['cached_origin_main'] for r in repos},
        'note': 'Coverage of THIS run. A later comparison may call a finding resolved only '
                'where the probe that could see it ran again; absence alone is not a fix.',
    }

    reference_documents = []
    for rel in REFERENCE_DOCUMENTS:
        in_index = (rel in (docs['paths'] or ())) if (docs['available'] and
                                                      rel.startswith('docs/')) else None
        reference_documents.append({
            'path': rel,
            # Two different facts, deliberately not merged: the pinned commit's docs/**
            # index covers only docs/, so anything else is None there rather than False.
            'in_pinned_docs_index': in_index,
            'in_production_tree': os.path.lexists(repo / rel),
        })

    dup = sorted({f['id'] for f in findings if [x['id'] for x in findings].count(f['id']) > 1})
    if dup:
        raise ValueError(f'findings ids must be unique; collisions: {dup[:5]}')

    return {
        'schema_version': SNAPSHOT_SCHEMA,
        'started_at': start,
        'finished_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'derived_state': True,
        'read_only_sources': True,
        'atomic_observation': False,
        'privacy': 'No argv, environment VALUES, plist argument content, log contents or '
                   'remote URLs; process executable names, one entrypoint target, argument '
                   'counts and environment key names only',
        'stage_vocabulary': list(STAGES),
        'status_vocabulary': list(STATUSES),
        'evidence_bases': list(BASES),
        'coverage': coverage,
        'reference_documents': reference_documents,
        'launchd_domains': domains,
        'launchctl_list_ok': list_ok,
        'labels_with_override_but_no_service': sorted(override_only),
        'entities': entities,
        'processes': processes,
        'repositories': repos,
        'declared_plists_in_repo': declared_plists,
        'source_metadata': [meta(manifest_path), reg_meta, sync_meta],
        'runtime_paths': [meta(repo / x) for x in
                          ('data', 'logs', 'scripts', 'spa_core', 'launchd', 'architecture')],
        'code_sync': sync_safe,
        'document_index': {'sha': docs['sha'], 'available': docs['available'],
                           'path_count': len(docs['paths'] or ()),
                           'adr_count': len(docs['adr'] or {}),
                           'scope': docs.get('scope') or docs.get('reason')},
        'ollama': ollama,
        'findings': findings,
        'scope': 'Explicit SPA repo plus --repo arguments and their registered worktrees; '
                 'not a whole-disk repository search',
    }


def summary(s, smap=None):
    counts = {k: sum(f['kind'] == k for f in s['findings']) for k in ('UNKNOWN', 'DRIFT', 'ORPHANED')}
    by_status = {}
    for e in s['entities']:
        by_status[e['status']] = by_status.get(e['status'], 0) + 1
    lines = ['# Cartographer System Map — snapshot summary', '',
             f"Observed: {s['finished_at']}  ·  schema `{s['schema_version']}`",
             f"Components: {len(s['entities'])}  ·  processes: {len(s['processes'])}  ·  findings: {counts}",
             f"Component status: {by_status}", '']
    if smap:
        lines += [f"Graph: {len(smap['nodes'])} nodes, {len(smap['edges'])} edges "
                  f"(bases: {smap['edge_basis_counts']})", '']
    lines += ['## Coverage and limits', '',
              '- Read-only, rebuildable, NON-ATOMIC observation: probes are taken in sequence.',
              '- `LIVE` means loaded or running — not HEALTHY. `HEALTHY` and `PRODUCING_OUTPUT` '
              'are unmeasured for every component.',
              '- A fresh artifact does not establish WHO produced it (`producer_attribution: UNKNOWN`).',
              '- `last_exit` is historical: launchctl keeps the previous exit status.',
              '- launchd domains probed separately: ' +
              ', '.join(f"`{n}` readable={d['readable']}" for n, d in s['launchd_domains'].items()),
              '- Process argv, environment values and plist argument content are never collected.', '']
    lines += ['## Repositories', '']
    for r in s['repositories']:
        lines += [f"`{r['path']}`",
                  f"- HEAD `{r['head']}` · cached origin/main `{r['cached_origin_main']}` · "
                  f"live remote `{r['remote_origin_main']}`"]
        if r['drift']:
            for k in ('changed_or_missing_on_disk', 'production_only_tracked', 'production_only_untracked'):
                lines.append(f"- {k}: {len(r['drift'][k])}")
            lines.append('- production-only means "absent from the compared ref", not "retired"')
        else:
            lines.append('- drift: UNKNOWN (not measurable)')
        lines.append('')
    lines += ['## Findings', '',
              f"UNKNOWN {counts['UNKNOWN']} · DRIFT {counts['DRIFT']} · ORPHANED {counts['ORPHANED']}",
              'Full list with stable ids: `findings.json`. Graph: `system_map.json` / `system_map.md`.',
              'No corrections performed; nothing in production was written.', '']
    return '\n'.join(lines) + '\n'


def _forbidden_dirs():
    """launchd directories, resolved. A symlinked path to the same directory is the same
    directory, and the guard must treat it as such."""
    out = []
    for p in (Path.home() / 'Library/LaunchAgents', Path('/Library/LaunchAgents'),
              Path('/Library/LaunchDaemons')):
        try:
            out.append(p.resolve())
        except OSError:
            out.append(p)
    return out


def validate_output(output, roots):
    resolved = Path(output).resolve()
    for root in roots:
        if resolved.is_relative_to(Path(root).resolve()):
            raise ValueError('Output must be outside all observed repositories')
    # BOTH sides are resolved. Resolving only the output made the guard silently
    # ineffective wherever the home directory is itself a symlink: the target resolved
    # to the real path while the forbidden path stayed symbolic, so `is_relative_to`
    # compared two different spellings of the same directory and let the write through.
    # The forbidden location is the REAL directory, which is what the guard must mean.
    if any(resolved.is_relative_to(p) for p in _forbidden_dirs()):
        raise ValueError('Output in launchd directory forbidden')
    return resolved


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--production', type=Path, default=Path.home() / 'Documents/SPA_Claude')
    ap.add_argument('--repo', type=Path, action='append', default=[])
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)
    output = validate_output(args.output, [args.production, *args.repo])
    if output.exists():
        raise SystemExit('Choose a new output directory; snapshots are never overwritten')
    s = collect(args.production.resolve(), args.repo)
    observed = [Path(w['worktree']) for r in s['repositories'] for w in (r['worktrees'] or [])]
    validate_output(output, observed)

    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location('cartographer_system_map', Path(__file__).with_name('system_map.py'))
    sm_mod = module_from_spec(spec)
    spec.loader.exec_module(sm_mod)
    smap = sm_mod.build(s)
    sm_mod.validate(smap)

    output.mkdir(parents=True, mode=0o700)
    files = [('snapshot.json', json.dumps(s, indent=2, ensure_ascii=False)),
             ('system_map.json', json.dumps(smap, indent=2, ensure_ascii=False)),
             ('findings.json', json.dumps(s['findings'], indent=2, ensure_ascii=False)),
             ('summary.md', summary(s, smap)),
             ('system_map.md', sm_mod.mermaid(smap, s))]
    for name, content in files:
        p = output / name
        with p.open('x', encoding='utf-8') as f:
            f.write(content + '\n')
        p.chmod(0o600)
    print(summary(s, smap))
    print(f'Artifacts: {", ".join(n for n, _ in files)}  →  {output}')


if __name__ == '__main__':
    main()
