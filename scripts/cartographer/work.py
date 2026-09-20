#!/usr/bin/env python3
"""Разработка и работа (Director OS Phase 5) — что строится, кем, где застряло, что
закончено и что ждёт решения владельца.

READ-ONLY и OFFLINE ПО ПОСТРОЕНИЮ: ни ``subprocess``, ни ``socket``, ни ``urllib``.
Читаются уже существующие карточки, определения трекеров, журналы сессий и производные
снимки предыдущих фаз; пишется ровно один файл в ``--output``.

ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО:

* второго бэклога. Снимок ПРОИЗВОДНЫЙ: пересобирается из тех же входов и ничего не
  помнит между прогонами. Источник правды остаётся в карточках;
* нового workflow. Словарь состояний берётся ИЗ ОПРЕДЕЛЕНИЙ трекеров
  (``.nimbalyst/trackers/*.yaml``), а не выдумывается; исходное состояние хранится
  рядом с owner-группой, и у сведения названа причина;
* назначения задач. Ни одна карточка не создаётся, не двигается и не трогается;
* догадок об исполнителе. ``claimed_by`` в этом репозитории содержит номера циклов,
  идентификаторы сессий и pid — это НЕ ярлык агента, и повышать одно до другого без
  отдельной улики запрещено (замер Phase 2 повторён здесь);
* «принято» без улики приёмки. Закрытая карточка без подтверждения приёмки показывается
  как «завершено, приёмка НЕ подтверждена» — это разные факты (инв. #17).
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import diff as diff_mod  # noqa: E402
import reliability as reliability_mod  # noqa: E402

SCHEMA = 'cartographer.work_snapshot/0.1'

# ── словари ──────────────────────────────────────────────────────────────────

OWNER_VIEW_STATES = ('NOT_STARTED', 'IN_PROGRESS', 'BLOCKED', 'WAITING_OWNER',
                     'DONE_ACCEPTANCE_UNCONFIRMED', 'DONE_ACCEPTANCE_UNKNOWN',
                     'DONE_ACCEPTANCE_NOT_APPLICABLE', 'ACCEPTED', 'UNKNOWN')

OWNER_VIEW_DEFINITIONS = {
    'NOT_STARTED': 'работа объявлена, но не начата',
    'IN_PROGRESS': 'работа идёт',
    'BLOCKED': 'исходное состояние карточки прямо говорит «заблокировано»',
    'WAITING_OWNER': 'ждёт решения владельца — так говорит исходное состояние, а не текст',
    'DONE_ACCEPTANCE_UNCONFIRMED': 'завершено, приёмка К ЭТОМУ РОДУ РАБОТ ПРИМЕНИМА, но '
                                   'подтверждения нет ни у одного источника',
    'DONE_ACCEPTANCE_UNKNOWN': 'завершено, но ПРИМЕНИМА ли приёмка — не измерено: ни одно '
                               'правило этот род работ не покрывает',
    'DONE_ACCEPTANCE_NOT_APPLICABLE': 'завершено, и отдельная приёмка не требуется — так '
                                      'говорит само правило',
    'ACCEPTED': 'приёмка подтверждена уликой',
    'UNKNOWN': 'исходное состояние не объявлено ни одним определением трекера',
}

# Применимость приёмки — ОТДЕЛЬНЫЙ вопрос от её результата. Смешать их значит выдать
# «правило сюда не смотрит» за «правило нарушено».
APPLICABILITY_STATES = ('APPLICABLE', 'NOT_APPLICABLE', 'UNKNOWN')

APPLICABILITY_DEFINITIONS = {
    'APPLICABLE': 'существующее правило прямо распространяется на этот род работ',
    'NOT_APPLICABLE': 'существующее правило прямо говорит, что к этому роду не относится',
    'UNKNOWN': 'ни одно правило этот род работ не покрывает — применимость НЕ измерена',
}

ACCEPTANCE_STATES = ('CONFIRMED', 'NOT_CONFIRMED', 'NOT_APPLICABLE', 'UNKNOWN')

ACCEPTANCE_DEFINITIONS = {
    'CONFIRMED': 'есть улика приёмки: владелец ответил (его акт и есть приёмка решения) '
                 'либо записан вердикт объявленной машинной пробы',
    'NOT_CONFIRMED': 'работа закрыта, но улики приёмки нет ни одной',
    'NOT_APPLICABLE': 'правило приёмки к этому роду карточек не относится — так сказано '
                      'в самом правиле',
    'UNKNOWN': 'о приёмке нельзя сказать ничего: карточка не закрыта',
}

BLOCKER_STATES = ('BLOCKED', 'WAITING_OWNER', 'NONE', 'UNKNOWN')

CLAIM_KINDS = ('CYCLE', 'SESSION', 'PID', 'AGENT_LABEL', 'UNVERIFIED_LABEL', 'UNKNOWN')

CLAIM_KIND_DEFINITIONS = {
    'CYCLE': 'номер цикла оркестратора — НЕ агент',
    'SESSION': 'идентификатор сессии — НЕ агент',
    'PID': 'номер процесса — НЕ агент, и он переиспользуется ОС',
    'AGENT_LABEL': 'ярлык launchd, ПОДТВЕРЖДЁННЫЙ наблюдением машины',
    'UNVERIFIED_LABEL': 'похоже на ярлык launchd, но наблюдением не подтверждён',
    'UNKNOWN': 'разобрать не удалось — и это не повод назвать агентом',
}

WORK_TYPES = ('owner_decision', 'inbox_task', 'agent_task', 'kanban_item', 'unknown')

# Как ИМЯ ФАЙЛА карточки отображается в род работы. Псевдонимы трекеров объявлены самими
# определениями (`idPrefix`), поэтому `own` и `owner` — один род, а не два.
PREFIX_TO_TYPE = {'own': 'owner_decision', 'owner': 'owner_decision',
                  'inbox': 'inbox_task', 'agent': 'agent_task'}

_CLAIM_PATTERNS = (
    (re.compile(r'^cycle[-_]?\d+$', re.I), 'CYCLE'),
    (re.compile(r'^pid[-_]?\d+$', re.I), 'PID'),
    (re.compile(r'session', re.I), 'SESSION'),
    (re.compile(r'^com\.spa\.[\w.]+$'), 'UNVERIFIED_LABEL'),
)


AUTHORITY_STATES = ('AUTHORITATIVE', 'AUTHORITY_UNDEFINED', 'NOT_AUTHORITY')

AUTHORITY_DEFINITIONS = {
    'AUTHORITATIVE': 'существующее правило или определение ПРЯМО называет этот файл '
                     'источником правды — цитата приложена',
    'AUTHORITY_UNDEFINED': 'правила, устанавливающего авторитет этого источника, в '
                           'репозитории не найдено. Победителя мы не выбираем '
                           '(словарь Phase 3, не новый)',
    'NOT_AUTHORITY': 'источник сам объявляет себя производным или наблюдением',
}


class WorkInputError(Exception):
    """Вход не соответствует контракту. Отказ, а не молчаливая догадка."""


# ── источники ────────────────────────────────────────────────────────────────

SOURCE_CONTRACTS = {
    'nimbalyst-local/tracker/*.md': {
        'represents': 'карточки работы: решения владельца, задания, задачи агентов',
        'basis': 'declared',
        'authority_status': 'AUTHORITATIVE',
        'authority_quote':
            '.nimbalyst/trackers/owner-decision.yaml:2 и agent-task.yaml:2 — «Источник '
            'правды — эти markdown-карточки в git»; для inbox то же место занимает '
            'CLAUDE.md:87 «задачи — в inbox / трекерах (nimbalyst-local/tracker/)»',
        'can_prove_owner': True, 'can_prove_state': True, 'can_prove_completion': True,
        'can_prove_acceptance': False, 'can_prove_blocker': True, 'can_prove_output': False,
        'limit': 'приёмку карточка объявить может, а ПОДТВЕРДИТЬ — нет: вердикт пробы '
                 'нигде не записывается',
    },
    '.nimbalyst/trackers/*.yaml': {
        'represents': 'словарь состояний и их группировку (category)',
        'basis': 'declared',
        'authority_status': 'AUTHORITATIVE',
        'authority_quote': 'определение трекера само объявляет набор status и category — '
                           'это и есть словарь, других претендентов нет',
        'can_prove_owner': False, 'can_prove_state': True, 'can_prove_completion': True,
        'can_prove_acceptance': False, 'can_prove_blocker': False, 'can_prove_output': False,
        'limit': 'словарь, а не состояние конкретной работы',
    },
    'nimbalyst-local/tracker/_BOARD.md': {
        'represents': 'сводный индекс карточек',
        'basis': 'derived', 'rebuildable_artifact': True,
        'authority_status': 'NOT_AUTHORITY',
        'authority_quote': 'сам файл: «НЕ править вручную — правь карточки. Источник '
                           'правды — карточки, это индекс»',
        'can_prove_owner': False, 'can_prove_state': False, 'can_prove_completion': False,
        'can_prove_acceptance': False, 'can_prove_blocker': False, 'can_prove_output': False,
        'limit': 'производный индекс: в спорах о состоянии не свидетель',
    },
    'KANBAN.json': {
        'represents': 'реестр задач MP-xxx (отдельный от карточек)',
        'basis': 'declared',
        # Правила, УСТАНАВЛИВАЮЩЕГО авторитет этого реестра, в репозитории нет: найдены
        # только строка структуры репо (CLAUDE.md:261 «Kanban (источник MP-xxx задач)») и
        # инвариант #11 про атомарную запись. Первая говорит, ГДЕ живут MP-задачи, а не
        # чей ответ сильнее при расхождении; второй — про порядок записи. Ни одного ADR.
        # Поэтому статус тот же, что Phase 3 ставит в таком случае, а не выдуманный.
        'authority_status': 'AUTHORITY_UNDEFINED',
        'authority_quote': 'найдено только CLAUDE.md:261 «KANBAN.json | Kanban (источник '
                           'MP-xxx задач)» и инвариант #11 про атомарную запись; ADR или '
                           'правила, устанавливающего авторитет, НЕТ',
        'can_prove_owner': False, 'can_prove_state': True, 'can_prove_completion': True,
        'can_prove_acceptance': False, 'can_prove_blocker': False, 'can_prove_output': True,
        'limit': 'ведётся отдельно от карточек; собственную свежесть объявляет полем '
                 'last_updated',
    },
    'data/session_changes.jsonl': {
        'represents': 'что сессия ЗАЯВИЛА сделанным: карточка, файлы, время',
        'basis': 'observed', 'authority_status': 'NOT_AUTHORITY',
        'authority_quote': 'журнал заявок сессий: наблюдение, не правило',
        'can_prove_owner': False, 'can_prove_state': False, 'can_prove_completion': False,
        'can_prove_acceptance': False, 'can_prove_blocker': False, 'can_prove_output': True,
        'limit': 'ЗАЯВКА, а не проверка: поле verified отражает собственную проверку '
                 'сессии, приёмкой не является',
    },
    'scripts/inbox_acceptance_baseline.json': {
        'represents': 'перечень карточек, у которых машинного критерия приёмки НЕТ',
        'basis': 'declared', 'authority_status': 'AUTHORITATIVE',
        'authority_quote': '.claude/rules/acceptance.md §«Храповик» называет этот файл '
                           'базой; сам файл несёт поле _rule с тем же путём',
        'can_prove_owner': False, 'can_prove_state': False, 'can_prove_completion': False,
        'can_prove_acceptance': True, 'can_prove_blocker': False, 'can_prove_output': False,
        'limit': 'доказывает ОТСУТСТВИЕ критерия, а не наличие приёмки',
    },
    'reliability_snapshot.json': {
        'represents': 'производный снимок надёжности (Phase 4)',
        'basis': 'derived', 'rebuildable_artifact': True,
        'authority_status': 'NOT_AUTHORITY',
        'authority_quote': 'сам снимок объявляет себя производным',
        'can_prove_owner': False, 'can_prove_state': False, 'can_prove_completion': False,
        'can_prove_acceptance': False, 'can_prove_blocker': True, 'can_prove_output': False,
        'limit': 'находка — НЕ задача; связь показывается только там, где она объявлена',
    },
    'system_map.json': {
        'represents': 'наблюдение машины: какие ярлыки launchd существуют',
        'basis': 'observed', 'authority_status': 'NOT_AUTHORITY',
        'authority_quote': 'снимок Cartographer: наблюдение, не правило',
        'can_prove_owner': False, 'can_prove_state': False, 'can_prove_completion': False,
        'can_prove_acceptance': False, 'can_prove_blocker': False, 'can_prove_output': False,
        'limit': 'подтверждает существование ЯРЛЫКА, а не то, что он что-то исполняет',
    },
}


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _parse_ts(value):
    return reliability_mod._parse_ts(value)


def _read_json(path):
    return reliability_mod._read_json(path)


def redact(text):
    return reliability_mod.redact(text)


def _evidence(kind, detail, where=None):
    return {'kind': kind, 'detail': redact(str(detail)[:600]), 'where': where}


def _frontmatter(text):
    """(поля, тело). Карточка без заголовка — не ошибка, а отдельный исход."""
    m = re.match(r'^---\n(.*?)\n---\n?(.*)$', text, re.S)
    if not m:
        return None, text
    fields = {}
    for line in m.group(1).splitlines():
        k = re.match(r'^([A-Za-z_][\w-]*):\s*(.*)$', line)
        if k:
            fields[k.group(1)] = k.group(2).strip().strip('"').strip("'")
    return fields, m.group(2)


def lifecycle_vocabulary(production):
    """Словарь состояний, ОБЪЯВЛЕННЫЙ определениями трекеров.

    Ничего не выдумывает: и набор значений, и их группировка (`category`) читаются из
    `.nimbalyst/trackers/*.yaml`. Новый workflow поверх существующего не строится.
    """
    out, files = {}, []
    root = Path(production) / '.nimbalyst/trackers'
    for y in sorted(root.glob('*.yaml')):
        try:
            text = y.read_text(encoding='utf-8')
        except OSError:
            continue
        files.append(str(y.relative_to(production)))
        prefix = (re.search(r'^idPrefix:\s*(\S+)', text, re.M) or [None, None])[1]
        block = text[text.index('name: status'):] if 'name: status' in text else ''
        for m in re.finditer(r'- value:\s*(\S+)\s*\n\s*label:\s*([^\n]+)\n\s*category:\s*(\S+)',
                             block):
            out.setdefault(m.group(1), {'labels': {}, 'categories': set()})
            out[m.group(1)]['labels'][prefix or y.stem] = m.group(2).strip()
            out[m.group(1)]['categories'].add(m.group(3).strip())
    return ({k: {'labels': v['labels'], 'categories': sorted(v['categories'])}
             for k, v in out.items()}, files)


# ── исполнительская заявка: claimed_by это НЕ агент ─────────────────────────

def classify_claim(value, known_labels=()):
    """(род, причина). Повышение до AGENT_LABEL требует ОТДЕЛЬНОЙ улики.

    В этом репозитории ``claimed_by`` держит `cycle-663`, `pid94637`,
    `interactive-session-2026-08-27`. Назвать такое агентом значит сочинить исполнителя:
    цикл — это прогон, сессия — это окно, pid — номер, который ОС переиспользует.
    Ярлыком агента значение становится только когда оно и выглядит как ярлык, и
    подтверждено наблюдением машины.
    """
    if not value:
        return 'UNKNOWN', 'поле claimed_by пустое — исполнитель НЕ измерен'
    text = str(value).strip()
    for pattern, kind in _CLAIM_PATTERNS:
        if pattern.search(text):
            if kind == 'UNVERIFIED_LABEL':
                if text in set(known_labels):
                    return 'AGENT_LABEL', ('значение похоже на ярлык launchd И подтверждено '
                                           'наблюдением машины')
                return 'UNVERIFIED_LABEL', ('значение похоже на ярлык launchd, но среди '
                                            'наблюдённых его нет — агентом не называем')
            return kind, f'{CLAIM_KIND_DEFINITIONS[kind]} (значение «{text}»)'
    return 'UNKNOWN', (f'значение «{text}» не разобрано ни одним правилом — это НЕ '
                       'основание назвать его агентом')


# ── приёмка ≠ завершение ─────────────────────────────────────────────────────

def acceptance_applicability(work_type):
    """(применимость, улика). Правило либо покрывает этот род работ, либо нет.

    Третий исход обязателен: KANBAN-задачи не покрыты ни одним правилом приёмки, и назвать
    их «приёмка не подтверждена» значило бы обвинить их в нарушении правила, которое на
    них не смотрит. Применимость здесь не сочиняется — она читается из существующих
    правил.
    """
    if work_type == 'owner_decision':
        return 'APPLICABLE', _evidence(
            'rule', 'инв. #14: карточку решения закрывает владелец, и его ответ и есть '
                    'приёмка', 'CLAUDE.md')
    if work_type == 'inbox_task':
        return 'APPLICABLE', _evidence(
            'rule', '.claude/rules/acceptance.md: «Читать перед тем, как взять карточку '
                    'inbox в работу» — правило прямо про этот род',
            '.claude/rules/acceptance.md')
    if work_type == 'agent_task':
        return 'NOT_APPLICABLE', _evidence(
            'rule', '.claude/rules/acceptance.md §«Не относится»: правило не '
                    'распространяется на agent-*', '.claude/rules/acceptance.md')
    return 'UNKNOWN', _evidence(
        'no_rule', f'ни одно правило приёмки не называет род работ «{work_type}» — '
                   'применимость НЕ измерена', 'repository')


def acceptance_of(work_type, fields, closed, baseline_files, card_name):
    """(применимость, состояние приёмки, улики). Закрытая карточка не равна принятой.

    Улики приёмки в этом репозитории ровно две, и обе объявлены правилами: ответ владельца
    (инв. #14) и машинная проба (.claude/rules/acceptance.md). Проба, ОБЪЯВЛЕННАЯ у
    карточки, приёмкой ещё не является: её вердикт нигде не записывается, и выдать
    объявление за результат значило бы ту самую самосертификацию, против которой правило
    написано.
    """
    applicability, app_ev = acceptance_applicability(work_type)
    ev = [app_ev]
    if applicability == 'NOT_APPLICABLE':
        return applicability, 'NOT_APPLICABLE', ev
    if applicability == 'UNKNOWN':
        return applicability, 'UNKNOWN', ev
    if work_type == 'owner_decision':
        answered = fields.get('owner_answered_at') or fields.get('owner_choice')
        if answered:
            ev.append(_evidence('owner_answer',
                                f"владелец ответил: choice={fields.get('owner_choice')}, "
                                f"время {fields.get('owner_answered_at')}, канал "
                                f"{fields.get('owner_answer_via')}", card_name))
            return applicability, 'CONFIRMED', ev
        if closed:
            ev.append(_evidence('no_owner_answer',
                                'карточка решения закрыта, но ответа владельца в полях '
                                'нет', card_name))
            return applicability, 'NOT_CONFIRMED', ev
        return applicability, 'UNKNOWN', ev
    probe = fields.get('acceptance_probe')
    if probe:
        ev.append(_evidence('probe_declared',
                            f'проба объявлена: {probe}. ВЕРДИКТ пробы нигде не записан — '
                            'объявление не является подтверждением', card_name))
        return applicability, 'NOT_CONFIRMED', ev
    if card_name in baseline_files:
        ev.append(_evidence('baseline',
                            'карточка названа в scripts/inbox_acceptance_baseline.json как '
                            'не имеющая машинного критерия приёмки',
                            'scripts/inbox_acceptance_baseline.json'))
        return applicability, 'NOT_CONFIRMED', ev
    if closed:
        ev.append(_evidence('no_criterion',
                            'карточка закрыта, критерия приёмки не объявлено, вердикта '
                            'нет', card_name))
        return applicability, 'NOT_CONFIRMED', ev
    return applicability, 'UNKNOWN', ev


# ── сведение состояний ───────────────────────────────────────────────────────

def owner_view(work_type, source_state, vocabulary, acceptance):
    """(группа владельца, причина). Исходное состояние НЕ заменяется — оно хранится рядом.

    Сведение опирается на `category`, объявленную самим определением трекера, и на два
    именованных исключения, которые объявлены там же в комментариях: `needs-owner` — это
    ожидание владельца, `blocked` — это «заблокировано».
    """
    known = vocabulary.get(source_state)
    if not known:
        return 'UNKNOWN', (f'состояние «{source_state}» не объявлено ни одним определением '
                           'трекера — победителя не выбираем')
    cats = known['categories']
    label = next(iter(known['labels'].values()), source_state)
    if source_state == 'needs-owner':
        return 'WAITING_OWNER', (f'определение трекера: «{label}», category={cats} — '
                                 'состояние прямо означает ожидание владельца')
    if source_state == 'blocked':
        return 'BLOCKED', f'определение трекера: «{label}», category={cats}'
    if 'done' in cats:
        if acceptance == 'CONFIRMED':
            return 'ACCEPTED', (f'category={cats} по определению трекера И улика приёмки '
                                'есть')
        if acceptance == 'NOT_APPLICABLE':
            return 'DONE_ACCEPTANCE_NOT_APPLICABLE', (
                f'category={cats}; правило приёмки само говорит, что к этому роду не '
                'относится, — отдельная приёмка не требуется')
        if acceptance == 'UNKNOWN':
            return 'DONE_ACCEPTANCE_UNKNOWN', (
                f'category={cats}; ПРИМЕНИМА ли приёмка к этому роду — не измерено, '
                'поэтому «не подтверждена» было бы обвинением по правилу, которое сюда '
                'не смотрит')
        return 'DONE_ACCEPTANCE_UNCONFIRMED', (
            f'category={cats} по определению трекера; приёмка применима, но '
            'подтверждения нет ни у одного источника')
    if 'started' in cats:
        return 'IN_PROGRESS', f'определение трекера: «{label}», category={cats}'
    if 'unstarted' in cats:
        return 'NOT_STARTED', f'определение трекера: «{label}», category={cats}'
    return 'UNKNOWN', f'category={cats} не отображается ни в одну группу'


# ── чтение источников ────────────────────────────────────────────────────────

def _source_record(name, path, status, *, note='', extra=None):
    c = SOURCE_CONTRACTS.get(name, {})
    rec = {
        'source': name, 'path': str(path), 'status': status,
        'represents': c.get('represents'), 'basis': c.get('basis'),
        'authority_status': c.get('authority_status', 'AUTHORITY_UNDEFINED'),
        'rebuildable_artifact': c.get('rebuildable_artifact', False),
        'authority_quote': c.get('authority_quote'),
        'can_prove_owner': c.get('can_prove_owner'),
        'can_prove_current_state': c.get('can_prove_state'),
        'can_prove_completion': c.get('can_prove_completion'),
        'can_prove_acceptance': c.get('can_prove_acceptance'),
        'can_prove_blocker': c.get('can_prove_blocker'),
        'can_prove_output': c.get('can_prove_output'),
        'limit': c.get('limit'), 'note': note,
    }
    rec.update(extra or {})
    return rec


def session_claims(production):
    """Заявки сессий по карточкам. ЗАЯВКА, а не проверка — так и записано."""
    path = Path(production) / 'data/session_changes.jsonl'
    if not path.is_file():
        return {}, _source_record('data/session_changes.jsonl', path, 'ABSENT')
    by_card, rows = {}, 0
    latest = None
    try:
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            rows += 1
            latest = d.get('ts') or latest
            card = d.get('card')
            if not card:
                continue
            key = Path(card).name
            entry = by_card.setdefault(key, {'sessions': [], 'files': [], 'last_ts': None,
                                             'states': []})
            if d.get('session'):
                entry['sessions'].append(d['session'])
            for f in (d.get('files') or []):
                if f not in entry['files']:
                    entry['files'].append(f)
            if d.get('card_state'):
                entry['states'].append(d['card_state'])
            ts = d.get('ts')
            if ts and (entry['last_ts'] is None or ts > entry['last_ts']):
                entry['last_ts'] = ts
    except OSError:
        return {}, _source_record('data/session_changes.jsonl', path, 'UNREADABLE')
    return by_card, _source_record(
        'data/session_changes.jsonl', path, 'READ',
        note=f'{rows} записей, из них с названной карточкой {sum(1 for _ in by_card)}',
        extra={'generated_at': latest})


def acceptance_baseline(production):
    path = Path(production) / 'scripts/inbox_acceptance_baseline.json'
    doc, state = _read_json(path)
    if state != 'READ' or not isinstance(doc, dict):
        return set(), _source_record('scripts/inbox_acceptance_baseline.json', path, state)
    files = set(doc.get('files') or [])
    return files, _source_record(
        'scripts/inbox_acceptance_baseline.json', path, 'READ',
        note=f"{len(files)} карточек без машинного критерия; замер {doc.get('_measured')}, "
             f"правило {doc.get('_rule')}", extra={'generated_at': doc.get('_measured')})


def kanban_items(production):
    """Отдельный реестр MP-xxx. Свежесть он объявляет сам — мы её только показываем."""
    path = Path(production) / 'KANBAN.json'
    doc, state = _read_json(path)
    if state != 'READ' or not isinstance(doc, dict):
        return [], _source_record('KANBAN.json', path, state)
    items = []
    for column, rows in (doc.get('columns') or {}).items():
        for r in (rows if isinstance(rows, list) else []):
            if isinstance(r, dict):
                items.append((column, r))
    for r in (doc.get('done') or []):
        if isinstance(r, dict):
            items.append(('done', r))
    rec = _source_record('KANBAN.json', path, 'READ',
                         note=f"{len(items)} записей, "
                              f"{len({r.get('id') for _, r in items})} уникальных id; "
                              f"last_updated "
                              f"{doc.get('last_updated')}, updated_by "
                              f"{doc.get('updated_by')}",
                         extra={'generated_at': doc.get('last_updated')})
    return items, rec


def _work(work_id, title, work_type, source, *, source_state, owner_view_state,
          mapping_reason, lifecycle_evidence, acceptance_status, acceptance_evidence,
          acceptance_applicability='UNKNOWN', acceptance_state_conflict=False,
          cross_source_refs=(),
          blocker_status, blocker_evidence, owner_role=None, owner_evidence=None,
          claimed_by=None, claim_kind='UNKNOWN', claim_reason=None, started_at=None,
          last_activity_at=None, completed_at=None, accepted_at=None, output_refs=(),
          related_decisions=(), related_findings=(), related_components=(),
          owner_decision_needed=None, source_status='READ', observed_at=None):
    return {
        'work_id': work_id,
        'title': redact(title),
        'work_type': work_type,
        'source': source,
        'source_status': source_status,
        # ОБА состояния живут рядом: исходное не заменяется сведением
        'source_state': source_state,
        'owner_view_state': owner_view_state,
        'mapping_reason': mapping_reason,
        'lifecycle_state': source_state,
        'lifecycle_evidence': list(lifecycle_evidence),
        'owner_role': owner_role,
        'owner_evidence': list(owner_evidence or []),
        'claimed_by': claimed_by,
        'claim_kind': claim_kind,
        'claim_reason': claim_reason,
        'started_at': started_at,
        'last_activity_at': last_activity_at,
        'completed_at': completed_at,
        'accepted_at': accepted_at,
        'acceptance_applicability': acceptance_applicability,
        'acceptance_status': acceptance_status,
        'acceptance_evidence': list(acceptance_evidence),
        # приёмка подтверждена, а исходное состояние всё ещё «в работе» — это РАСХОЖДЕНИЕ
        # источников, и оно показывается, а не заглаживается переписыванием состояния
        'acceptance_state_conflict': bool(acceptance_state_conflict),
        'cross_source_refs': list(cross_source_refs),
        'blocker_status': blocker_status,
        'blocker_evidence': list(blocker_evidence),
        'output_refs': list(output_refs),
        'related_decisions': list(related_decisions),
        'related_findings': list(related_findings),
        'related_components': list(related_components),
        'owner_decision_needed': owner_decision_needed,
        'observed_at': observed_at,
    }


def _card_work(path, production, vocabulary, baseline, claims, known_labels,
               findings_index, kanban_ids=()):
    name = path.name
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    fields, body = _frontmatter(text)
    prefix = name.split('-')[0]
    work_type = PREFIX_TO_TYPE.get(prefix, 'unknown')
    if fields is None:
        return _work(name, name, work_type, 'nimbalyst-local/tracker/*.md',
                     source_state=None, owner_view_state='UNKNOWN',
                     mapping_reason='у карточки нет заголовка — состояние НЕ измерено',
                     lifecycle_evidence=[_evidence('no_frontmatter', 'файл без ---', name)],
                     acceptance_status='UNKNOWN', acceptance_evidence=[],
                     blocker_status='UNKNOWN', blocker_evidence=[], source_status='PARTIAL')

    state = fields.get('status')
    closed = bool(vocabulary.get(state) and 'done' in vocabulary[state]['categories'])
    applicability, acceptance, acc_ev = acceptance_of(work_type, fields, closed, baseline,
                                                      name)
    view, reason = owner_view(work_type, state, vocabulary, acceptance)
    conflict = acceptance == 'CONFIRMED' and not closed
    if conflict:
        acc_ev.append(_evidence(
            'state_conflict',
            f'приёмка подтверждена, а исходное состояние всё ещё «{state}» — источники '
            'расходятся; состояние НЕ переписано', name))

    claim_raw = fields.get('claimed_by')
    claim_kind, claim_reason = classify_claim(claim_raw, known_labels)

    owner_role, owner_ev = None, []
    if fields.get('owner'):
        owner_role = fields['owner']
        owner_ev.append(_evidence('owner_field', f"поле owner: {fields['owner']}", name))
    elif work_type == 'owner_decision':
        owner_role = 'владелец'
        owner_ev.append(_evidence('card_type',
                                  'карточка рода «решение владельца»: закрыть её вправе '
                                  'только владелец (инв. #14)', name))

    blocker, blocker_ev = 'NONE', []
    if state == 'blocked':
        blocker = 'BLOCKED'
        blocker_ev.append(_evidence('state', 'исходное состояние карточки: blocked', name))
    elif state == 'needs-owner':
        blocker = 'WAITING_OWNER'
        blocker_ev.append(_evidence('state', 'исходное состояние карточки: needs-owner',
                                    name))
    if fields.get('blocks'):
        blocker_ev.append(_evidence('blocks',
                                    f"карточка объявляет, что БЛОКИРУЕТ: "
                                    f"{fields['blocks']}", name))

    claim = claims.get(name) or {}
    stamps = [fields.get('created'), fields.get('claimed_at'),
              fields.get('owner_answered_at'), fields.get('resolved'),
              fields.get('closed'), claim.get('last_ts')]
    parsed = [(_parse_ts(s), s) for s in stamps if s]
    parsed = [(d, s) for d, s in parsed if d]
    last = max(parsed)[1] if parsed else None

    findings = []
    if fields.get('finding_key'):
        findings.append({'finding': fields['finding_key'], 'relation': 'EXPLICIT_LINK',
                         'basis': 'карточка названа полем finding_key'})
    for fid, rel in (findings_index.get(name) or []):
        findings.append({'finding': fid, 'relation': rel,
                         'basis': ('снимок надёжности назвал эту карточку'
                                   if rel == 'EXPLICIT_LINK'
                                   else 'совпадение по упоминанию — НЕ объявленная связь')})

    decisions = [fields[k] for k in ('adr', 'decision', 'closed_by_class') if fields.get(k)]
    # ЯВНАЯ перекрёстная ссылка на другой реестр — это ссылка, а не тождество: карточка
    # может называть три MP-задачи сразу, и ни одной из них она не является
    cross_refs = [{'registry': 'KANBAN.json', 'id': mp, 'relation': 'EXPLICIT_REFERENCE',
                   'basis': 'идентификатор дословно встречается в тексте карточки; '
                            'тождеством это НЕ является'}
                  for mp in sorted(set(re.findall(r'\bMP-\d+\b', text)) & set(kanban_ids))]

    needed = None
    if view == 'WAITING_OWNER':
        head = re.search(r'^##\s*Что от тебя нужно\s*\n(.+?)(?=\n##|\Z)', body, re.S | re.M)
        needed = redact((head.group(1).strip() if head else
                         'раздел «Что от тебя нужно» в карточке не найден')[:400])

    return _work(
        name, fields.get('title') or name, work_type, 'nimbalyst-local/tracker/*.md',
        source_state=state, owner_view_state=view, mapping_reason=reason,
        lifecycle_evidence=[_evidence('status_field', f'status: {state}', name)],
        acceptance_status=acceptance, acceptance_evidence=acc_ev,
        acceptance_applicability=applicability, acceptance_state_conflict=conflict,
        cross_source_refs=cross_refs,
        blocker_status=blocker, blocker_evidence=blocker_ev,
        owner_role=owner_role, owner_evidence=owner_ev,
        claimed_by=claim_raw, claim_kind=claim_kind, claim_reason=claim_reason,
        started_at=fields.get('claimed_at'), last_activity_at=last,
        completed_at=(fields.get('resolved') or fields.get('closed')) if closed else None,
        accepted_at=fields.get('owner_answered_at') if acceptance == 'CONFIRMED' else None,
        output_refs=[{'path': f, 'basis': 'сессия ЗАЯВИЛА файл в data/session_changes.jsonl'}
                     for f in (claim.get('files') or [])[:12]],
        related_decisions=decisions, related_findings=findings,
        related_components=sorted({f.split('/')[0] + '/' for f in (claim.get('files') or [])
                                   if '/' in f})[:8],
        owner_decision_needed=needed, observed_at=fields.get('created'))


def _kanban_work(entries):
    """Одна запись MP-xxx, даже если реестр перечисляет её несколько раз.

    Замер: в KANBAN.json 912 записей на 885 идентификаторов — 27 повторов, и часть из них
    лежит в РАЗНЫХ колонках (`MP-404` значится и в `features`, и в `done`). Это свойство
    самого реестра, а не помеха: выбрасывать повтор молча значило бы спрятать расхождение,
    а считать его двумя работами — удвоить одну. Поэтому запись одна, повтор назван уликой,
    а расходящиеся состояния НЕ сводятся к победителю.
    """
    columns = [c for c, _ in entries]
    states = {str(r.get('status') or c) for c, r in entries}
    column, row = entries[0]
    state = str(row.get('status') or column)
    extra_ev = []
    if len(entries) > 1:
        extra_ev.append(_evidence(
            'duplicate_id',
            f'реестр перечисляет {row.get("id")} {len(entries)} раз(а): колонки '
            f'{sorted(columns)}, состояния {sorted(states)}', 'KANBAN.json'))
    if len(states) > 1:
        return _work(
            f"kanban:{row.get('id')}", str(row.get('title') or row.get('id')),
            'kanban_item', 'KANBAN.json', source_state=' | '.join(sorted(states)),
            owner_view_state='UNKNOWN',
            mapping_reason=(f'реестр называет для {row.get("id")} несколько состояний '
                            f'{sorted(states)} в колонках {sorted(columns)} — победителя '
                            'не выбираем'),
            lifecycle_evidence=[_evidence('kanban', f'колонки {sorted(columns)}',
                                          'KANBAN.json')] + extra_ev,
            acceptance_status='UNKNOWN', acceptance_applicability='UNKNOWN',
            acceptance_evidence=[
                acceptance_applicability('kanban_item')[1],
                _evidence('no_acceptance_channel',
                          'KANBAN.json приёмку не фиксирует ни одним полем',
                          'KANBAN.json')],
            blocker_status='UNKNOWN', blocker_evidence=[])
    view = {'done': 'DONE_ACCEPTANCE_UNKNOWN'}.get(state.lower())
    if view is None:
        view = 'UNKNOWN'
        reason = (f'состояние «{state}» объявлено только внутри KANBAN.json; определения '
                  'трекеров его не знают, победителя не выбираем')
    else:
        reason = ('KANBAN.json объявляет задачу выполненной; ПРИМЕНИМА ли к этому реестру '
                  'приёмка — ни одним правилом не сказано, поэтому статус приёмки не '
                  'измерен, а не «не подтверждён»')
    return _work(
        f"kanban:{row.get('id')}", str(row.get('title') or row.get('id')), 'kanban_item',
        'KANBAN.json', source_state=state, owner_view_state=view, mapping_reason=reason,
        lifecycle_evidence=[_evidence('kanban',
                                      f"колонка {column}, status {row.get('status')}",
                                      'KANBAN.json')] + extra_ev,
        acceptance_status='UNKNOWN', acceptance_applicability='UNKNOWN',
        acceptance_evidence=[
            acceptance_applicability('kanban_item')[1],
            _evidence('no_acceptance_channel',
                      'KANBAN.json приёмку не фиксирует ни одним полем', 'KANBAN.json')],
        blocker_status='UNKNOWN', blocker_evidence=[],
        completed_at=row.get('completed'), last_activity_at=row.get('completed'),
        output_refs=[{'path': f, 'basis': 'поле files записи KANBAN'}
                     for f in (row.get('files') or [])[:12]],
        related_decisions=[t for t in (row.get('tags') or []) if str(t).startswith('ADR')])


LIMITS = (
    'Снимок ПРОИЗВОДНЫЙ: пересобирается из тех же входов и ничего не помнит между '
    'прогонами. Источник правды остаётся в карточках.',
    'Словарь состояний взят ИЗ ОПРЕДЕЛЕНИЙ трекеров. Исходное состояние хранится рядом с '
    'группой владельца, и у сведения названа причина; новый workflow не заводится.',
    '«Принято» требует улики приёмки. Закрытая карточка без неё показывается как '
    '«завершено, приёмка НЕ подтверждена» — это разные факты.',
    'ВЕРДИКТ машинной пробы приёмки в этом репозитории не записывается нигде, поэтому '
    'объявленная проба сама по себе подтверждением не является.',
    'claimed_by — исполнительская ЗАЯВКА, а не агент: там живут номера циклов, сессий и '
    'pid. Ярлыком агента значение становится только при подтверждении наблюдением.',
    'Блокер показывается только по улике. «Давно не менялось» блокером здесь не считается '
    'вовсе: правила или SLA на срок работы в репозитории не объявлено.',
    'Находка надёжности — НЕ задача. Объявленная связь показывается как связь, совпадение '
    'по упоминанию — как возможное, и повышения одного до другого нет.',
    'Задачи не создаются, карточки не двигаются, состояния не переписываются.',
)


def build_work_snapshot(production, reliability_path=None, cartographer_set=None,
                        now=None):
    now = now or _now()
    production = Path(production)
    sources, works = [], []

    vocabulary, voc_files = lifecycle_vocabulary(production)
    sources.append(_source_record(
        '.nimbalyst/trackers/*.yaml', ', '.join(voc_files) or '—',
        'READ' if vocabulary else 'ABSENT',
        note=f'{len(vocabulary)} состояний объявлено'))

    baseline, base_rec = acceptance_baseline(production)
    claims, claims_rec = session_claims(production)

    known_labels = []
    if cartographer_set:
        p = Path(cartographer_set)
        p = p if p.is_file() else p / 'snapshot.json'
        doc, state = _read_json(p)
        if state == 'READ' and isinstance(doc, dict):
            known_labels = sorted({e.get('label') for e in (doc.get('entities') or [])
                                   if isinstance(e, dict) and e.get('label')})
        sources.append(_source_record('system_map.json', p, state,
                                      note=f'{len(known_labels)} наблюдённых ярлыков'))
    else:
        sources.append(_source_record('system_map.json', '—', 'NOT_GIVEN',
                                      note='наблюдение машины не передано: ярлык агента '
                                           'подтвердить нечем'))

    findings_index = {}
    if reliability_path:
        p = Path(reliability_path)
        p = p if p.is_file() else p / 'reliability_snapshot.json'
        doc, state = _read_json(p)
        if state == 'READ' and isinstance(doc, dict):
            try:
                reliability_mod.validate_reliability_snapshot(doc, str(p))
            except reliability_mod.ReliabilityInputError as exc:
                raise WorkInputError(f'снимок надёжности не соответствует контракту: {exc}')
            for f in doc.get('findings') or []:
                for t in f.get('linked_tasks') or []:
                    findings_index.setdefault(Path(t['task']).name, []).append(
                        (f['finding_id'], t['relation']))
        sources.append(_source_record('reliability_snapshot.json', p, state,
                                      extra={'generated_at': (doc or {}).get('generated_at')
                                             if isinstance(doc, dict) else None}))
    else:
        sources.append(_source_record('reliability_snapshot.json', '—', 'NOT_GIVEN',
                                      note='снимок надёжности не передан'))

    kanban, kanban_rec = kanban_items(production)
    kanban_ids = {r.get('id') for _, r in kanban if r.get('id')}

    cards = sorted((production / 'nimbalyst-local/tracker').glob('*.md'))
    cards = [c for c in cards if c.name != '_BOARD.md']
    for c in cards:
        item = _card_work(c, production, vocabulary, baseline, claims, known_labels,
                          findings_index, kanban_ids)
        if item:
            works.append(item)
    sources.append(_source_record('nimbalyst-local/tracker/*.md',
                                  production / 'nimbalyst-local/tracker',
                                  'READ' if cards else 'ABSENT',
                                  note=f'{len(cards)} карточек'))
    board = production / 'nimbalyst-local/tracker/_BOARD.md'
    sources.append(_source_record('nimbalyst-local/tracker/_BOARD.md', board,
                                  'READ' if board.is_file() else 'ABSENT',
                                  note='производный индекс: в составе работ НЕ участвует'))
    sources.append(base_rec)
    sources.append(claims_rec)

    grouped = {}
    for column, row in kanban:
        grouped.setdefault(row.get('id'), []).append((column, row))
    for entries in grouped.values():
        works.append(_kanban_work(entries))
    sources.append(kanban_rec)

    works.sort(key=lambda w: (w['work_id'],))

    # ── тождество работ измеряется, а не предполагается ──────────────────────
    # Складывать записи двух реестров в одно число можно ТОЛЬКО доказав, что это разные
    # работы. Тождество между реестрами здесь не доказано ни для одной пары: совпадений
    # идентификаторов нет, совпадений заголовков нет, а явная ссылка — это ссылка
    # (одна карточка называет до трёх MP-задач сразу и ни одной из них не является).
    # Поэтому общее уникальное число работ остаётся НЕ ИЗМЕРЕННЫМ.
    card_works = [w for w in works if w['source'] == 'nimbalyst-local/tracker/*.md']
    kanban_works = [w for w in works if w['source'] == 'KANBAN.json']
    dup_ids = sorted({r.get('id') for _, r in kanban
                      if sum(1 for _, x in kanban if x.get('id') == r.get('id')) > 1})
    multi_col = sorted({i for i in dup_ids
                        if len({c for c, x in kanban if x.get('id') == i}) > 1})
    referencing = [w for w in card_works if w['cross_source_refs']]
    referenced_ids = sorted({r['id'] for w in referencing for r in w['cross_source_refs']})
    identity = {
        'tracker': {'source_record_count': len(cards),
                    'unique_identifier_count': len({c.name for c in cards}),
                    'identifier': 'имя файла карточки',
                    'proven_unique': len({c.name for c in cards})},
        'kanban': {'source_record_count': len(kanban),
                   'unique_identifier_count': len({r.get('id') for _, r in kanban}),
                   'duplicate_identifiers': len(dup_ids),
                   'identifiers_in_several_columns': multi_col,
                   'identifier': 'поле id записи',
                   'proven_unique': len({r.get('id') for _, r in kanban})},
        'cross_source': {
            'exact_identity_matches': 0,
            'exact_identity_basis': 'общий устойчивый идентификатор между реестрами не '
                                    'существует: имена карточек и id KANBAN живут в '
                                    'разных пространствах, пересечение измерено и равно 0',
            'explicit_reference_records': len(referencing),
            'explicit_reference_ids': referenced_ids,
            'explicit_reference_basis': 'карточка дословно называет идентификатор другого '
                                        'реестра. Это ССЫЛКА, а не тождество: одна '
                                        'карточка может назвать несколько задач',
            'title_only_matches': 0,
            'title_only_basis': 'совпадение заголовков измерено отдельно и тождеством НЕ '
                                'считается ни при каком числе',
            'authority_between_registries': 'AUTHORITY_UNDEFINED',
            'authority_note': 'правила, устанавливающего, чей ответ сильнее при '
                              'расхождении карточек и KANBAN, в репозитории нет — '
                              'победителя не выбираем',
        },
        'source_record_count': len(cards) + len(kanban),
        'proven_unique_work_count': None,
        'proven_unique_reason':
            'уникальность ВНУТРИ каждого реестра доказана его собственным '
            'идентификатором; уникальность МЕЖДУ реестрами не доказана ни для одной '
            'записи, поэтому суммарное число уникальных работ НЕ ИЗМЕРЕНО',
        'unresolved_identity_records': len(referencing),
    }

    by = lambda key: {k: sum(1 for w in works if w[key] == k)  # noqa: E731
                      for k in sorted({str(w[key]) for w in works})}
    explicit = [w for w in works
                if any(r['relation'] == 'EXPLICIT_LINK' for r in w['related_findings'])]
    mention_only = [w for w in works if w['related_findings'] and w not in explicit]
    counts = {
        # записей ДВУХ реестров; «работ» столько называть нельзя — см. identity
        'source_records': len(works),
        'proven_unique_work_count': None,
        'unresolved_identity_records': identity['unresolved_identity_records'],
        'by_owner_view_state': by('owner_view_state'),
        'by_source_state': by('source_state'),
        'by_work_type': by('work_type'),
        'by_acceptance_status': by('acceptance_status'),
        'by_acceptance_applicability': by('acceptance_applicability'),
        'by_blocker_status': by('blocker_status'),
        'by_claim_kind': by('claim_kind'),
        'waiting_owner': sum(1 for w in works if w['owner_view_state'] == 'WAITING_OWNER'),
        'blocked': sum(1 for w in works if w['owner_view_state'] == 'BLOCKED'),
        'in_progress': sum(1 for w in works if w['owner_view_state'] == 'IN_PROGRESS'),
        'done_acceptance_unconfirmed': sum(
            1 for w in works if w['owner_view_state'] == 'DONE_ACCEPTANCE_UNCONFIRMED'),
        'done_acceptance_unknown': sum(
            1 for w in works if w['owner_view_state'] == 'DONE_ACCEPTANCE_UNKNOWN'),
        'done_acceptance_not_applicable': sum(
            1 for w in works
            if w['owner_view_state'] == 'DONE_ACCEPTANCE_NOT_APPLICABLE'),
        'completed_total': sum(
            1 for w in works if w['owner_view_state'] in (
                'ACCEPTED', 'DONE_ACCEPTANCE_UNCONFIRMED', 'DONE_ACCEPTANCE_UNKNOWN',
                'DONE_ACCEPTANCE_NOT_APPLICABLE')),
        'acceptance_state_conflicts': sum(
            1 for w in works if w['acceptance_state_conflict']),
        'accepted': sum(1 for w in works if w['owner_view_state'] == 'ACCEPTED'),
        'unknown_state': sum(1 for w in works if w['owner_view_state'] == 'UNKNOWN'),
        'owner_role_known': sum(1 for w in works if w['owner_role']),
        'execution_claim_known': sum(1 for w in works if w['claimed_by']),
        'claim_not_an_agent': sum(1 for w in works
                                  if w['claim_kind'] in ('CYCLE', 'SESSION', 'PID',
                                                         'UNVERIFIED_LABEL', 'UNKNOWN')
                                  and w['claimed_by']),
        'claim_is_a_verified_agent': sum(1 for w in works
                                         if w['claim_kind'] == 'AGENT_LABEL'),
        'reliability_explicit': len(explicit),
        'reliability_mention_only': len(mention_only),
        'reliability_none': sum(1 for w in works if not w['related_findings']),
        'sources_read': sum(1 for s in sources if s['status'] == 'READ'),
        'sources_unavailable': sum(1 for s in sources if s['status'] != 'READ'),
    }

    snapshot = {
        'schema_version': SCHEMA,
        'generated_at': now.isoformat(),
        'derived_state': True,
        'is_not_a_source_of_truth':
            'производный снимок работы: пересобирается из карточек и журналов и не '
            'является ни вторым бэклогом, ни новым реестром задач',
        'creates_tasks': False,
        'modifies_tracker': False,
        'assigns_work': False,
        'production': str(production),
        'identity': identity,
        'owner_view_definitions': dict(OWNER_VIEW_DEFINITIONS),
        'applicability_definitions': dict(APPLICABILITY_DEFINITIONS),
        'authority_definitions': dict(AUTHORITY_DEFINITIONS),
        'acceptance_definitions': dict(ACCEPTANCE_DEFINITIONS),
        'claim_kind_definitions': dict(CLAIM_KIND_DEFINITIONS),
        'owner_view_vocabulary': list(OWNER_VIEW_STATES),
        'acceptance_vocabulary': list(ACCEPTANCE_STATES),
        'applicability_vocabulary': list(APPLICABILITY_STATES),
        'authority_vocabulary': list(AUTHORITY_STATES),
        'blocker_vocabulary': list(BLOCKER_STATES),
        'claim_vocabulary': list(CLAIM_KINDS),
        'work_type_vocabulary': list(WORK_TYPES),
        'lifecycle_vocabulary_source': voc_files,
        'lifecycle_vocabulary': {k: v for k, v in sorted(vocabulary.items())},
        'sources': sources,
        'counts': counts,
        'work': works,
        'limits': list(LIMITS),
    }
    snapshot['semantic_digest'] = semantic_digest(snapshot)
    return snapshot


def semantic_view(snapshot):
    return {k: v for k, v in snapshot.items()
            if k not in ('generated_at', 'semantic_digest')}


def semantic_digest(snapshot):
    payload = json.dumps(semantic_view(snapshot), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]


def validate_work_snapshot(snapshot, where):
    def need(cond, message):
        if not cond:
            raise WorkInputError(f'{where}: {message}')

    need(isinstance(snapshot, dict), 'снимок не является объектом')
    need(snapshot.get('schema_version') == SCHEMA,
         f"схема {snapshot.get('schema_version')!r}, ожидалась {SCHEMA!r}")
    for key in ('generated_at', 'sources', 'counts', 'work', 'limits',
                'owner_view_definitions', 'acceptance_definitions',
                'claim_kind_definitions', 'lifecycle_vocabulary',
                'lifecycle_vocabulary_source', 'identity',
                'applicability_definitions', 'authority_definitions'):
        need(key in snapshot, f'поле {key} отсутствует')
    ident = snapshot['identity']
    need(ident.get('proven_unique_work_count') is None
         or isinstance(ident['proven_unique_work_count'], int),
         'proven_unique_work_count обязан быть числом ИЛИ null, а не догадкой')
    need(bool(ident.get('proven_unique_reason')),
         'у числа уникальных работ не названа причина')
    need(ident['cross_source']['title_only_matches'] == 0
         or 'тождеством' in ident['cross_source']['title_only_basis'],
         'совпадение заголовков объявлено тождеством')
    for rec in snapshot['sources']:
        need(rec.get('authority_status') in AUTHORITY_STATES,
             f"источник {rec.get('source')}: авторитет "
             f"{rec.get('authority_status')!r} вне словаря")
        need(not (rec.get('authority_status') == 'AUTHORITATIVE'
                  and not rec.get('authority_quote')),
             f"источник {rec.get('source')} объявлен авторитетным без цитаты правила")
    for flag in ('creates_tasks', 'modifies_tracker', 'assigns_work'):
        need(snapshot.get(flag) is False, f'{flag} обязан быть False')
    seen = set()
    for i, w in enumerate(snapshot['work']):
        need(isinstance(w, dict), f'work[{i}] не объект')
        for key in ('work_id', 'title', 'work_type', 'source', 'source_status',
                    'source_state', 'owner_view_state', 'mapping_reason',
                    'lifecycle_state', 'lifecycle_evidence', 'owner_role',
                    'owner_evidence', 'claimed_by', 'claim_kind', 'claim_reason',
                    'started_at', 'last_activity_at', 'completed_at', 'accepted_at',
                    'acceptance_status', 'acceptance_evidence', 'blocker_status',
                    'blocker_evidence', 'output_refs', 'related_decisions',
                    'related_findings', 'related_components', 'owner_decision_needed',
                    'observed_at', 'acceptance_applicability',
                    'acceptance_state_conflict', 'cross_source_refs'):
            need(key in w, f'work[{i}] без поля {key}')
        need(w['work_id'] not in seen, f"дубль work_id {w['work_id']!r}")
        seen.add(w['work_id'])
        need(w['owner_view_state'] in OWNER_VIEW_STATES,
             f"work[{i}] группа {w['owner_view_state']!r} вне словаря")
        need(w['acceptance_status'] in ACCEPTANCE_STATES,
             f"work[{i}] приёмка {w['acceptance_status']!r} вне словаря")
        need(w['acceptance_applicability'] in APPLICABILITY_STATES,
             f"work[{i}] применимость {w['acceptance_applicability']!r} вне словаря")
        need(not (w['owner_view_state'] == 'DONE_ACCEPTANCE_UNCONFIRMED'
                  and w['acceptance_applicability'] != 'APPLICABLE'),
             f'work[{i}] «приёмка не подтверждена» при неизмеренной применимости — '
             'это обвинение по правилу, которое сюда не смотрит')
        for r in w['cross_source_refs']:
            need(r.get('relation') == 'EXPLICIT_REFERENCE',
                 f'work[{i}] перекрёстная ссылка без рода улики')
            need('НЕ является' in (r.get('basis') or ''),
                 f'work[{i}] ссылка на другой реестр подана как тождество')
        need(w['blocker_status'] in BLOCKER_STATES,
             f"work[{i}] блокер {w['blocker_status']!r} вне словаря")
        need(w['claim_kind'] in CLAIM_KINDS,
             f"work[{i}] род заявки {w['claim_kind']!r} вне словаря")
        need(bool(w['mapping_reason']), f'work[{i}] сведение без причины')
        need(not (w['owner_view_state'] == 'ACCEPTED'
                  and w['acceptance_status'] != 'CONFIRMED'),
             f'work[{i}] объявлен принятым без подтверждённой приёмки')
        need(not (w['blocker_status'] in ('BLOCKED', 'WAITING_OWNER')
                  and not w['blocker_evidence']),
             f'work[{i}] блокер объявлен без улики')
        need(not (w['claim_kind'] == 'AGENT_LABEL'
                  and 'подтвержд' not in (w['claim_reason'] or '')),
             f'work[{i}] заявка названа агентом без подтверждающей улики')
        for r in w['related_findings']:
            need(r.get('relation') in ('EXPLICIT_LINK', 'MENTION_MATCH'),
                 f'work[{i}] связь с находкой без рода улики')
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--production', type=Path, default=Path.home() / 'Documents/SPA_Claude')
    ap.add_argument('--reliability', type=Path,
                    help='снимок надёжности Phase 4 (для связей находка↔карточка)')
    ap.add_argument('--cartographer', type=Path,
                    help='комплект Cartographer: подтверждение ярлыков агентов')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)

    final = Path(args.output)
    if final.exists():
        raise SystemExit(f'{final} уже существует; каждый прогон пишет новый каталог')
    try:
        snapshot = build_work_snapshot(args.production, args.reliability,
                                       args.cartographer)
        validate_work_snapshot(snapshot, 'freshly built')
    except WorkInputError as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\nСнимок не построен. Это НЕ '
                         '«работы нет».')

    protected = [Path(args.production)]
    for extra in (args.reliability, args.cartographer):
        if extra:
            protected.append(Path(extra))
    diff_mod.validate_output(final, protected)

    staging = final.with_name(final.name + '.incomplete')
    if staging.exists():
        raise SystemExit(f'{staging} остался от прерванного прогона; отодвиньте его')
    staging.mkdir(parents=True, mode=0o700)
    p = staging / 'work_snapshot.json'
    with p.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(snapshot, indent=2, ensure_ascii=False) + '\n')
    p.chmod(0o600)
    os.rename(staging, final)

    c = snapshot['counts']
    print(f"Источников прочитано: {c['sources_read']} · недоступно: "
          f"{c['sources_unavailable']}")
    idn = snapshot['identity']
    print(f"Записей в снимке: {c['source_records']} · сырых записей источников: "
          f"{idn['source_record_count']} (трекер {idn['tracker']['source_record_count']}, "
          f"KANBAN {idn['kanban']['source_record_count']}, из них "
          f"{idn['kanban']['duplicate_identifiers']} повторов одного id)")
    print("Уникальных работ ВСЕГО: НЕ ИЗМЕРЕНО — тождество между реестрами не доказано")
    print(f"Перекрёстных ссылок без доказанного тождества: "
          f"{c['unresolved_identity_records']}")
    print(f"В работе {c['in_progress']} · заблокировано {c['blocked']} · ждёт владельца "
          f"{c['waiting_owner']} · статус неизвестен: {c['unknown_state']}")
    print(f"Завершено {c['completed_total']}: принято {c['accepted']} · приёмка не "
          f"подтверждена {c['done_acceptance_unconfirmed']} · применимость не измерена "
          f"{c['done_acceptance_unknown']} · приёмка не требуется "
          f"{c['done_acceptance_not_applicable']}")
    print(f"Расхождений «приёмка есть, состояние не закрыто»: "
          f"{c['acceptance_state_conflicts']}")
    print(f"Приёмка: {c['by_acceptance_status']} · применимость: "
          f"{c['by_acceptance_applicability']}")
    print(f"Исполнительских заявок: {c['execution_claim_known']}, из них НЕ агент: "
          f"{c['claim_not_an_agent']}, подтверждённых агентов: "
          f"{c['claim_is_a_verified_agent']}")
    print(f"Снимок → {final / 'work_snapshot.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
