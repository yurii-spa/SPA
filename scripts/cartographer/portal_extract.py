#!/usr/bin/env python3
"""Layer A + B of the studio portal: read-only extraction into a normalised snapshot.

READ-ONLY. Opens files, never writes production, never imports a production module and
never runs a writer. What it produces is derived state: a `portal_snapshot.json` that the
renderer can rebuild a page from offline, without reading production again.

Three rules govern every field below.

  * **No second registry.** The canonical task, decision and agent records stay exactly
    where they are. This snapshot is a projection with the source path of every record.
  * **Original values survive.** A status is stored verbatim; the display GROUPING is a
    separate field, and its basis is the `category` already declared in
    `.nimbalyst/trackers/*.yaml` — not a grouping invented here. A status outside that
    vocabulary becomes `UNKNOWN_STATUS`, never a guess.
  * **A link needs a basis.** The only links recorded are ones a machine can check: a
    `finding_key` that literally contains a launchd label, an `adr:` field naming a
    document. A label merely MENTIONED in a card body is recorded as a mention with
    `proves_assignment: false`, and `claimed_by` is an executor claim string
    (`cycle-663`, `pid98130`, `interactive-session-…`) — it is NOT an agent label and is
    never presented as one.

Field selection is a WHITELIST. Card bodies are not copied at all: they carry Telegram
text, prompts and log excerpts, and the portal has no need of them — it shows the title
and the path to the record.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re

PORTAL_SCHEMA = 'cartographer.portal_snapshot/0.1'

#: Frontmatter keys kept for a task-like record. Everything else is dropped, including the
#: body: a card can contain arbitrary Telegram text, and the portal does not need it.
TASK_FIELDS = (
    'title', 'status', 'created', 'updated', 'source', 'priority', 'domain', 'owner',
    'claimed_by', 'claimed_at', 'claimed_note', 'acceptance_probe', 'finding_key', 'adr',
    'blocks', 'blocked_by', 'related', 'closed', 'closed_reason', 'closed_by', 'resolved',
    'split_from', 'legacy_id', 'phase', 'tags', 'type', 'stale', 'recheck_after',
)
#: Additionally kept for an owner-decision record: the lifecycle the source really has.
DECISION_FIELDS = (
    'owner_choice', 'owner_answered_at', 'owner_answer_via', 'owner_answered_by',
    'owner_answer_kind', 'owner_decision', 'owner_choice_superseded',
    'owner_choice_superseded_at', 'owner_choice_superseded_via', 'decision', 'answered',
    'approves',
)
LABEL_RE = re.compile(r'com\.(?:spa|ollama)\.[A-Za-z0-9_.-]+')
ADR_RE = re.compile(r'ADR-(?:[A-Za-z]+[0-9]*-)*[0-9]+')

#: Which file-name prefix maps to which tracker definition. The prefix is how the
#: repository itself names the three queues (CLAUDE.md §"Структура репо").
PREFIX_TO_TRACKER = {'inbox': 'inbox', 'agent': 'agent-task',
                     'own': 'owner-decision', 'owner': 'owner-decision'}
DECISION_PREFIXES = ('own', 'owner')


class ExtractionError(Exception):
    """A source could not be read. Never silently turned into "no records"."""


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _iso(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat()


# ── minimal frontmatter reader (stdlib only, no YAML dependency) ─────────────

def parse_frontmatter(text):
    """Read the leading `---` block only. Returns (mapping, error_or_None).

    Deliberately narrow: `key: value`, one level of nesting, and `key:` followed by
    `- item` lines. The BODY is never parsed — prose lines like `try:` or `else:` would
    otherwise be harvested as fields, and 693 cards contain plenty of them.
    """
    if not text.startswith('---'):
        return {}, 'no frontmatter block'
    lines = text.splitlines()
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == '---':
            end = i
            break
    if end is None:
        return {}, 'frontmatter block is not terminated'
    out, current_list, current_key, parent = {}, None, None, None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith('#'):
            continue
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip())
        if stripped.startswith('- '):
            value = _scalar(stripped[2:])
            if current_list is not None:
                current_list.append(value)
            continue
        hit = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$', stripped)
        if not hit:
            continue
        key, value = hit.group(1), hit.group(2)
        if indent and parent:
            # `key:` with nothing after it is provisionally a list; the first indented
            # `sub: value` line proves it is a MAP and converts it. Without this the
            # nested `trackerStatus.type` was dropped on every card, and the conflict
            # between a file-name prefix and the declared tracker type could never fire.
            if not isinstance(out.get(parent), dict):
                out[parent] = {}
            out[parent][key] = _scalar(value)
            current_list = None
            continue
        if value == '':
            current_list, current_key, parent = [], key, key
            out[key] = current_list
        else:
            out[key] = _scalar(value)
            current_list, current_key, parent = None, None, None
    # `key:` with neither a list nor a nested map stays an empty list — keep it visible
    return out, None


def _scalar(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
        return value[1:-1]
    if value in ('true', 'false'):
        return value == 'true'
    return value


def tracker_vocabulary(trackers_dir):
    """The status vocabulary AND its category, as the repository already declares them.

    `category` (unstarted / started / done) is Nimbalyst's own field — the grouping shown
    in the portal is therefore an existing rule, not one invented here.
    """
    vocab, errors = {}, []
    directory = Path(trackers_dir)
    if not directory.is_dir():
        return vocab, [f'{directory}: not a directory']
    for path in sorted(directory.glob('*.yaml')):
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError as exc:
            errors.append(f'{path}: {type(exc).__name__}')
            continue
        kind = None
        hit = re.search(r'^type:\s*(\S+)', text, re.M)
        if hit:
            kind = hit.group(1)
        # Bounded by the NEXT `- name:` at any indentation: a looser bound swallowed the
        # neighbouring `source` and `priority` option blocks and produced a status
        # vocabulary containing `telegram` and `medium`.
        block = re.search(r'-\s*name:\s*status\b(.*?)(?=\n\s*-\s*name:\s|\Z)',
                          text, re.S)
        options = {}
        if block:
            for opt in re.finditer(r'- value:\s*(\S+)\s*\n\s*label:\s*(.*?)\n'
                                   r'(?:\s*category:\s*(\S+))?', block.group(1)):
                options[opt.group(1)] = {'label': opt.group(2).strip(),
                                         'category': opt.group(3)}
        prefix = None
        hit = re.search(r'^idPrefix:\s*(\S+)', text, re.M)
        if hit:
            prefix = hit.group(1)
        if kind:
            vocab[kind] = {'source': str(path), 'statuses': options,
                           'id_prefix': prefix,
                           # Both names address the same tracker: a card may declare
                           # `agent` where the definition calls itself `agent-task`.
                           # Treating the alias as a disagreement produced 58 false
                           # conflicts on real data.
                           'aliases': sorted({x for x in (kind, prefix) if x})}
    return vocab, errors


def canonical_tracker(name, vocab):
    """Resolve a tracker name or its id prefix to the one canonical tracker type."""
    for kind, spec in vocab.items():
        if name == kind or name in (spec.get('aliases') or ()):
            return kind
    return None


# ── tasks and decisions ─────────────────────────────────────────────────────

def _record(path, vocab, root):  # noqa: C901 — one record, many recorded facts
    text = path.read_text(encoding='utf-8', errors='replace')
    fm, error = parse_frontmatter(text)
    prefix = path.name.split('-')[0]
    tracker = PREFIX_TO_TRACKER.get(prefix)
    declared_tracker = None
    if isinstance(fm.get('trackerStatus'), dict):
        declared_tracker = fm['trackerStatus'].get('type')
    declared_canonical = (canonical_tracker(declared_tracker, vocab)
                          if isinstance(declared_tracker, str) else None)

    status = fm.get('status')
    known = (vocab.get(tracker) or {}).get('statuses') or {}
    if not isinstance(status, str) or not status:
        status_group, basis = 'UNKNOWN_STATUS', 'the record declares no status'
    elif status in known:
        category = known[status].get('category')
        status_group = {'unstarted': 'не начато', 'started': 'в работе',
                        'done': 'закрыто'}.get(category, 'UNKNOWN_STATUS')
        basis = (f"category `{category}` declared for `{status}` in "
                 f"{(vocab.get(tracker) or {}).get('source')}")
    else:
        status_group, basis = 'UNKNOWN_STATUS', (
            f'`{status}` is not in the vocabulary of tracker `{tracker}`')

    fields = {k: fm[k] for k in TASK_FIELDS if k in fm}
    if prefix in DECISION_PREFIXES:
        fields.update({k: fm[k] for k in DECISION_FIELDS if k in fm})
    trail = fm.get('status_trail')
    if isinstance(trail, list) and trail:
        fields['status_trail_last'] = [str(x) for x in trail[-3:]]
        fields['status_trail_count'] = len(trail)

    stat = path.stat()
    record = {
        'id': path.stem,
        'object_type': 'owner_decision_record' if prefix in DECISION_PREFIXES else 'task',
        'tracker': tracker or 'UNKNOWN',
        'filename_prefix': prefix,
        'declared_tracker_type': declared_tracker,
        'declared_tracker_canonical': declared_canonical,
        'title': fm.get('title') if isinstance(fm.get('title'), str) else None,
        'status_raw': status if isinstance(status, str) else None,
        'status_group': status_group,
        'status_group_basis': basis,
        'fields': fields,
        'source': {'path': str(path.relative_to(root)), 'absolute': str(path),
                   'format': 'markdown + YAML frontmatter',
                   'file_mtime': _iso(stat.st_mtime), 'size_bytes': stat.st_size},
        'parse_error': error,
        'body_copied': False,
        'body_note': 'тело карточки НЕ копируется: оно содержит произвольный текст из '
                     'Telegram, промпты и выдержки логов; в портале — заголовок и путь '
                     'к записи',
    }
    record['acceptance'] = _acceptance(record)
    return record


#: The acceptance rule names the queue it governs and the ones it does not: it applies to
#: `inbox` cards, and explicitly NOT to owner decisions or agent tasks. Applying its
#: verdict to all three would state a rule that does not exist for two of them.
ACCEPTANCE_APPLIES_TO = ('inbox',)


def _acceptance(record):
    """Whether the work was ACCEPTED — which a recorded `done` does not establish."""
    probe = record['fields'].get('acceptance_probe')
    closed = record['status_group'] == 'закрыто'
    applies = record['tracker'] in ACCEPTANCE_APPLIES_TO
    if not applies:
        verdict = ('правило приёмки на этот тип записи не распространяется '
                   '(.claude/rules/acceptance.md, раздел «Не относится»)')
    elif closed:
        verdict = 'НЕ ПОДТВЕРЖДЕНО: статус закрыт, но результата пробы приёмки нет'
    else:
        verdict = 'не применимо: запись не закрыта'
    return {
        'rule_applies_to_this_tracker': applies,
        'probe_declared': probe if isinstance(probe, str) else None,
        'result_recorded': None,
        'result_source': ('NOT_FOUND — артефакта с результатами проб приёмки карточек в '
                          'наблюдаемом дереве не найдено' if applies else
                          'не применимо'),
        'accepted': None,
        'verdict': verdict,
        'rule': '.claude/rules/acceptance.md — приёмка inbox-карточки меряется машинной '
                'пробой, объявленной ДО работы; записанный `done` сам по себе приёмкой не '
                'является. На own-*/owner-* и agent-* правило не распространяется',
    }


def collect_records(tracker_dir, vocab, root, errors):
    directory = Path(tracker_dir)
    if not directory.is_dir():
        errors.append({'source': str(directory), 'error': 'not a directory',
                       'consequence': 'записи трекера НЕ извлечены — это НЕ значит «задач нет»'})
        return []
    records, seen = [], {}
    for path in sorted(directory.glob('*.md')):
        if path.name == '_BOARD.md':
            continue
        try:
            record = _record(path, vocab, root)
        except OSError as exc:
            errors.append({'source': str(path), 'error': type(exc).__name__,
                           'consequence': 'эта запись пропущена и НЕ учтена в счётчиках'})
            continue
        if record['id'] in seen:
            record['duplicate_of'] = seen[record['id']]
        seen[record['id']] = record['source']['path']
        records.append(record)
    return records


# ── provable links only ─────────────────────────────────────────────────────

def build_links(records, labels_known, adr_index):
    """Only links a machine can verify. Nothing probabilistic, nothing by title."""
    links, mentions = [], []
    for r in records:
        key = r['fields'].get('finding_key')
        if isinstance(key, str):
            for label in LABEL_RE.findall(key):
                links.append({
                    'id': f"link:finding_key:{r['id']}:{label}",
                    'from': {'type': r['object_type'], 'id': r['id']},
                    'to': {'type': 'launchd_label', 'id': label},
                    'relation': 'record_references_label',
                    'basis': 'the `finding_key` field literally contains the label',
                    'evidence': {'artifact': 'portal_snapshot.json',
                                 'pointer': f"records[id={r['id']!r}].fields.finding_key"},
                    'label_known_to_cartographer': label in labels_known,
                    'proves_assignment': False,
                    'proves_assignment_note': 'ссылка доказывает УПОМИНАНИЕ метки в '
                                              'машинном ключе находки, а не то, что агент '
                                              'работает над записью',
                })
        adr = r['fields'].get('adr')
        for value in ([adr] if isinstance(adr, str) else adr if isinstance(adr, list) else []):
            for ident in ADR_RE.findall(str(value)):
                links.append({
                    'id': f"link:adr:{r['id']}:{ident}",
                    'from': {'type': r['object_type'], 'id': r['id']},
                    'to': {'type': 'document', 'id': ident},
                    'relation': 'record_declares_governing_document',
                    'basis': 'the `adr:` field names the identifier',
                    'evidence': {'artifact': 'portal_snapshot.json',
                                 'pointer': f"records[id={r['id']!r}].fields.adr"},
                    'resolved_in_document_index': adr_index.get(ident) is not None,
                    'document_path': adr_index.get(ident),
                    'proves_assignment': False,
                })
        claim = r['fields'].get('claimed_by')
        if isinstance(claim, str) and claim:
            mentions.append({
                'id': f"claim:{r['id']}",
                'record': r['id'],
                'claimed_by_raw': claim,
                'kind': ('launchd_label' if LABEL_RE.fullmatch(claim) else
                         'executor_claim_string'),
                'agent_link': ('linked' if LABEL_RE.fullmatch(claim) else 'UNLINKED'),
                'note': 'значение `claimed_by` — строка исполнителя (цикл, PID, '
                        'интерактивная сессия). Это НЕ метка launchd и не доказывает, '
                        'что над записью работает агент',
            })
    return links, mentions


def body_label_mentions(tracker_dir, root, errors):
    """Labels mentioned in card BODIES. Counted, never treated as a link.

    Only the label strings are extracted — no surrounding text leaves the card.
    """
    directory = Path(tracker_dir)
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob('*.md')):
        if path.name == '_BOARD.md':
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError as exc:
            errors.append({'source': str(path), 'error': type(exc).__name__,
                           'consequence': 'упоминания меток в этой записи не собраны'})
            continue
        labels = sorted(set(LABEL_RE.findall(text)))
        if labels:
            out.append({'record': path.stem, 'labels': labels,
                        'relation': 'mentions_label_in_text',
                        'proves_assignment': False,
                        'note': 'упоминание метки в тексте записи; назначения НЕ доказывает'})
    return out


# ── agents and roles: three separate columns of fact, never merged ───────────

def agents_and_roles(manifest, registry, cartographer_snapshot, errors):
    """Role configuration, registry membership and observed stages, kept apart.

    DECLARED / REGISTERED / INSTALLED / LOADED / RUNNING answer different questions and
    come from different sources. They are reported side by side and never collapsed into
    one "state", because a declaration cannot testify about a process.
    """
    declared = {}
    if isinstance(manifest, dict) and isinstance(manifest.get('agents'), list):
        declared = {a['label']: a for a in manifest['agents']
                    if isinstance(a, dict) and a.get('label')}
    else:
        errors.append({'source': 'architecture/manifest.json',
                       'error': 'unreadable or unexpected shape',
                       'consequence': 'роли НЕ извлечены — это НЕ значит «ролей нет»'})
    registered = {}
    if isinstance(registry, dict) and isinstance(registry.get('agents'), list):
        registered = {a['label']: a for a in registry['agents']
                      if isinstance(a, dict) and a.get('label')}
    else:
        errors.append({'source': 'data/agent_registry.json',
                       'error': 'unreadable or unexpected shape',
                       'consequence': 'членство в реестре НЕ извлечено'})
    observed = {}
    if isinstance(cartographer_snapshot, dict):
        observed = {e['id']: e for e in cartographer_snapshot.get('entities') or []
                    if isinstance(e, dict) and e.get('id')}

    rows = []
    for label in sorted(set(declared) | set(registered) | set(observed)):
        d, g, o = declared.get(label, {}), registered.get(label, {}), observed.get(label, {})
        stages = o.get('stages') or {}
        rows.append({
            'id': label,
            'object_type': 'agent_or_role',
            'role_configuration': {
                'present_in_manifest': label in declared,
                'layer': d.get('layer'), 'role': d.get('role'), 'intent': d.get('intent'),
                'schedule': d.get('schedule'), 'program': d.get('program'),
                'produces_count': len(d.get('produces') or ()),
                'consumes_count': len(d.get('consumes') or ()),
                'governed_by': [x for x in (d.get('governed_by') or []) if isinstance(x, str)],
                'source': 'architecture/manifest.json',
                'proves': 'что объявлено; об исполнении не говорит ничего',
            },
            'registry_membership': {
                'present_in_registry': label in registered,
                'role': g.get('role'), 'schedule': g.get('schedule'),
                'retired': g.get('retired'), 'reboot_safe': g.get('reboot_safe'),
                'source': 'data/agent_registry.json',
                'proves': 'членство в реестре на момент записи файла',
                'note': 'поля `loaded`/`pid` реестра здесь НЕ используются как наблюдение: '
                        'наблюдение берётся из снимка Cartographer',
            },
            'observed': {
                'in_cartographer_snapshot': label in observed,
                'status': o.get('status'),
                'stages': {k: stages.get(k) for k in
                           ('DECLARED', 'REGISTERED', 'INSTALLED', 'LOADED', 'RUNNING',
                            'PRODUCING_OUTPUT', 'HEALTHY')},
                'domains': o.get('domains'),
                'last_exit': o.get('last_exit'),
                'last_exit_basis': o.get('last_exit_basis'),
                'source': 'snapshot.json (Cartographer)',
                'proves': 'то, что наблюдалось в момент снимка, по стадиям отдельно',
            },
            'task_links': [],
            'text_mentions': 0,
        })
    return rows


def _source(path, root, purpose, fmt, writer, scope, canonicality, limits):
    p = Path(path)
    available = p.exists()
    record = {
        'id': str(p.relative_to(root)) if str(p).startswith(str(root)) else str(p),
        'path': str(p), 'purpose': purpose, 'format': fmt,
        'written_by': writer, 'scope': scope,
        'canonicality_rule': canonicality, 'limits': limits,
        'available': available,
    }
    if available:
        stat = p.stat()
        record['observed_at'] = _iso(stat.st_mtime)
        record['size_bytes'] = stat.st_size
        if p.is_file():
            record['sha256'] = _sha256(p)
        else:
            record['entries'] = len(list(p.iterdir()))
    else:
        record['consequence'] = ('раздел, зависящий от этого источника, остаётся '
                                 'НЕИЗВЕСТНЫМ — это не «пусто»')
    return record


def declared_sources(root, cartographer_dir, briefing_dir):
    root = Path(root)
    return [
        _source(root / 'nimbalyst-local/tracker', root,
                'файлы-карточки: задания (inbox), задачи агентов (agent), решения '
                'владельца (own/owner)', 'каталог Markdown + YAML frontmatter',
                'оркестратор и сессии через scripts/orchestrator_queue.py (подтверждено '
                'документацией CLAUDE.md §"Структура репо")',
                'все три очереди студии',
                'источник правды по задачам и решениям — сами карточки; `_BOARD.md` '
                'объявлен производным индексом',
                ['одна запись = один файл; одинаковые заголовки НЕ объединяются',
                 'тело карточки не копируется в портал']),
        _source(root / '.nimbalyst/trackers', root,
                'определения типов трекеров: словарь статусов и их категории',
                'каталог YAML', 'конфигурация Nimbalyst',
                'словари статусов трёх очередей',
                'единственное объявленное место, где статус получает категорию '
                '(unstarted/started/done) — на ней и строится группировка портала',
                ['группировка портала берётся отсюда, а не выдумывается']),
        _source(root / 'architecture/manifest.json', root,
                'объявленная конфигурация ролей агентов', 'JSON',
                'курируется вручную и доезжает в прод через origin (ADR-курация)',
                'намерение: label, layer, role, intent, schedule, produces, consumes',
                'декларация намерения; об исполнении не свидетельствует',
                ['состав может расходиться с реестром — требования равенства нет']),
        _source(root / 'data/agent_registry.json', root,
                'реестр агентов', 'JSON', 'генерируется агентом флота',
                'членство в реестре и его метаданные',
                'AUTHORITY_UNDEFINED относительно манифеста: правила, какой из двух '
                'составов главнее, в репозитории нет',
                ['поля `loaded`/`pid` реестра не используются как наблюдение',
                 'свой SLO 26 ч объявлен правилом REGISTRY_STALE']),
        _source(root / 'KANBAN.json', root,
                'спринтовая доска MP-задач', 'JSON',
                'записывается агентами цикла (поле updated_by)',
                'спринты и колонки MP-задач',
                'AUTHORITY_UNDEFINED относительно карточек трекера: это другая ось '
                '(спринты MP), и правила соподчинения нет',
                ['возраст файла показан как есть; портал не выдаёт его за свежий',
                 'в портале учитывается только как источник, содержимое не смешивается '
                 'с карточками']),
        _source(Path(cartographer_dir), Path(cartographer_dir).parent,
                'наблюдение машины: стадии, процессы, drift, находки',
                'комплект артефактов Cartographer',
                'scripts/cartographer/snapshot.py (read-only)',
                'launchd, процессы, plist, git-расхождение',
                'принятый контракт cartographer.snapshot/0.3',
                ['наблюдение не атомарно', 'HEALTHY и PRODUCING_OUTPUT всегда неизвестны']),
        _source(Path(briefing_dir), Path(briefing_dir).parent,
                'сводка владельца Phase 1: изменения, внимание, кандидаты решений',
                'комплект артефактов Owner Briefing',
                'scripts/cartographer/brief.py (offline)',
                'производное представление сравнения двух наблюдений',
                'принятый контракт cartographer.owner_briefing/0.1',
                ['кандидаты решений — производные наблюдения, а не карточки решений']),
    ]


def _read_json(path, errors, what):
    p = Path(path)
    if not p.is_file():
        errors.append({'source': str(p), 'error': 'missing',
                       'consequence': f'{what}: НЕИЗВЕСТНО (источник отсутствует)'})
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        errors.append({'source': str(p), 'error': type(exc).__name__,
                       'consequence': f'{what}: НЕИЗВЕСТНО (источник не разобран)'})
        return None


def build_portal_snapshot(production, cartographer_dir, briefing_dir):
    """Layer B: one normalised, rebuildable snapshot of what the portal will show."""
    root = Path(production).resolve()
    errors = []
    started = dt.datetime.now(dt.timezone.utc).isoformat()

    vocab, vocab_errors = tracker_vocabulary(root / '.nimbalyst/trackers')
    for message in vocab_errors:
        errors.append({'source': str(root / '.nimbalyst/trackers'), 'error': message,
                       'consequence': 'группировка статусов недоступна — статусы останутся '
                                      'в исходном виде с UNKNOWN_STATUS'})
    records = collect_records(root / 'nimbalyst-local/tracker', vocab, root, errors)
    tasks = [r for r in records if r['object_type'] == 'task']
    decisions = [r for r in records if r['object_type'] == 'owner_decision_record']

    manifest = _read_json(root / 'architecture/manifest.json', errors, 'конфигурация ролей')
    registry = _read_json(root / 'data/agent_registry.json', errors, 'реестр агентов')
    snapshot = _read_json(Path(cartographer_dir) / 'snapshot.json', errors,
                          'наблюдение машины')
    briefing = _read_json(Path(briefing_dir) / 'owner_briefing.json', errors,
                          'сводка владельца')
    doc_index = {}
    if isinstance(snapshot, dict):
        # The pinned ADR index the accepted snapshot already carries, via governed_by
        # resolutions recorded per entity.
        for entity in snapshot.get('entities') or []:
            for ref in entity.get('document_references') or []:
                if ref.get('outcome') == 'resolved' and ref.get('reference'):
                    doc_index[ref['reference']] = ref.get('path')

    agents = agents_and_roles(manifest, registry, snapshot, errors)
    labels_known = {a['id'] for a in agents}
    links, claims = build_links(records, labels_known, doc_index)
    mentions = body_label_mentions(root / 'nimbalyst-local/tracker', root, errors)

    by_label = {a['id']: a for a in agents}
    for link in links:
        if link['to']['type'] == 'launchd_label' and link['to']['id'] in by_label:
            by_label[link['to']['id']]['task_links'].append(
                {'record': link['from']['id'], 'relation': link['relation'],
                 'basis': link['basis'], 'proves_assignment': False})
    mention_count = {}
    for m in mentions:
        for label in m['labels']:
            mention_count[label] = mention_count.get(label, 0) + 1
    for label, count in mention_count.items():
        if label in by_label:
            by_label[label]['text_mentions'] = count

    conflicts = []
    for r in records:
        declared = r['declared_tracker_type']
        expected = r['tracker']
        # Compared after resolving aliases: `agent` and `agent-task` are one tracker.
        if (declared and expected != 'UNKNOWN'
                and r['declared_tracker_canonical'] not in (None, expected)):
            conflicts.append({
                'id': f"conflict:tracker_type:{r['id']}",
                'kind': 'declaration_difference',
                'subject': r['id'],
                'statements': [
                    {'source': 'имя файла', 'says': f'префикс `{r["filename_prefix"]}` → '
                                                    f'трекер `{expected}`'},
                    {'source': 'frontmatter trackerStatus.type',
                     'says': f'`{declared}` → трекер '
                             f'`{r["declared_tracker_canonical"]}`'}],
                'authority': 'AUTHORITY_UNDEFINED',
                'note': 'правила, что главнее — имя файла или объявленный тип, в '
                        'репозитории нет; оба утверждения сохранены',
            })
        if r.get('duplicate_of'):
            conflicts.append({
                'id': f"conflict:duplicate_id:{r['id']}",
                'kind': 'duplicate_identifier', 'subject': r['id'],
                'statements': [{'source': r['source']['path'], 'says': 'запись с этим id'},
                               {'source': r['duplicate_of'], 'says': 'ещё одна с тем же id'}],
                'authority': 'AUTHORITY_UNDEFINED',
                'note': 'записи НЕ объединяются',
            })
    manifest_only = sorted(a['id'] for a in agents
                           if a['role_configuration']['present_in_manifest']
                           and not a['registry_membership']['present_in_registry'])
    registry_only = sorted(a['id'] for a in agents
                           if a['registry_membership']['present_in_registry']
                           and not a['role_configuration']['present_in_manifest'])
    if manifest_only or registry_only:
        conflicts.append({
            'id': 'conflict:manifest_vs_registry_membership',
            'kind': 'declaration_difference', 'subject': 'состав агентов',
            'statements': [
                {'source': 'architecture/manifest.json',
                 'says': f'{len(manifest_only)} метк(и) только здесь'},
                {'source': 'data/agent_registry.json',
                 'says': f'{len(registry_only)} метк(и) только здесь'}],
            'authority': 'AUTHORITY_UNDEFINED',
            'note': 'требования равенства составов нигде не установлено',
            'subjects': manifest_only + registry_only,
        })

    status_counts, group_counts, type_counts = {}, {}, {}
    for r in records:
        status_counts[r['status_raw'] or 'NO_STATUS'] = \
            status_counts.get(r['status_raw'] or 'NO_STATUS', 0) + 1
        group_counts[r['status_group']] = group_counts.get(r['status_group'], 0) + 1
        type_counts[r['tracker']] = type_counts.get(r['tracker'], 0) + 1

    portal = {
        'schema_version': PORTAL_SCHEMA,
        'extraction_started_at': started,
        'extraction_finished_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'volatile_fields': list(VOLATILE_KEYS),
        'derived_state': True,
        'read_only': True,
        'creates_no_registry': 'канонические записи остаются в своих файлах; здесь только '
                               'проекция с путём к каждой записи',
        'production_root': str(root),
        'sources': declared_sources(root, cartographer_dir, briefing_dir),
        'tracker_vocabulary': vocab,
        'tasks': tasks,
        'owner_decision_records': decisions,
        'agents_and_roles': agents,
        'links': links,
        'executor_claims': claims,
        'text_mentions': mentions,
        'conflicts': conflicts,
        'extraction_errors': errors,
        'counts': {
            'tasks': len(tasks),
            'owner_decision_records': len(decisions),
            'agents_and_roles': len(agents),
            'provable_links': len(links),
            'executor_claims': len(claims),
            'records_with_text_mentions': len(mentions),
            'conflicts': len(conflicts),
            'extraction_errors': len(errors),
            'by_tracker': type_counts,
            'by_status_raw': dict(sorted(status_counts.items(), key=lambda kv: -kv[1])),
            'by_status_group': group_counts,
            # Counted only where the acceptance rule actually applies.
            'closed_inbox_without_confirmed_acceptance': sum(
                1 for r in records if r['acceptance']['rule_applies_to_this_tracker']
                and r['status_group'] == 'закрыто'),
            'closed_records_outside_the_acceptance_rule': sum(
                1 for r in records if not r['acceptance']['rule_applies_to_this_tracker']
                and r['status_group'] == 'закрыто'),
        },
        'observation_times': {
            'machine_observed_at': (snapshot or {}).get('finished_at'),
            'briefing_generated_at': (briefing or {}).get('generated_at'),
            'extraction_finished_at': None,
            'note': 'наблюдение машины, сборка сводки и извлечение карточек — три разных '
                    'момента; они не смешиваются',
        },
        'limits': [
            'Портал READ-ONLY: он ничего не создаёт, не закрывает и не исполняет.',
            'Записанный `done` не означает принятую работу: результатов проб приёмки в '
            'наблюдаемом дереве нет, поэтому приёмка у всех закрытых — НЕ ПОДТВЕРЖДЕНА.',
            '`claimed_by` — строка исполнителя (цикл, PID, сессия), а не метка агента.',
            'Упоминание метки в тексте записи назначением не является.',
            'Где правило каноничности не объявлено, стоит AUTHORITY_UNDEFINED.',
        ],
    }
    portal['observation_times']['extraction_finished_at'] = portal['extraction_finished_at']
    return portal


#: Clock fields, named explicitly. `page_generated_at` belongs here too: including it
#: made an offline rebuild of the SAME snapshot produce a different digest.
VOLATILE_KEYS = ('extraction_started_at', 'extraction_finished_at', 'page_generated_at',
                 'volatile_fields', 'semantic_digest', 'observation_times')


def semantic_view(portal):
    return {k: v for k, v in portal.items() if k not in VOLATILE_KEYS}


def semantic_digest(portal):
    blob = json.dumps(semantic_view(portal), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()
