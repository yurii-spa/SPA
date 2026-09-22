#!/usr/bin/env python3
"""Director OS v1.3 · Семантическое здоровье служб — ПРОИЗВОДНАЯ модель.

Что этот модуль меняет
======================
v1.2 показывала «LIVE 79» зелёным. Замер: ``LIVE`` в снимке означает «объявлена,
установлена, загружена» — и ничего больше. Живой процесс сейчас есть у **8** сущностей,
и все восемь — демоны. У остальных процесса нет, и для расписанных это НОРМА, а не
поломка: расписанное задание между запусками не работает по построению.

Отсюда главное правило модуля: **у расписанного задания ``RUNNING`` не ``false``, а
``NOT_APPLICABLE``.** Поставить ``false`` значило бы выкрасить 86 сущностей из 103 в
красный за то, что они ведут себя правильно.

Семь стадий и что каждая на самом деле доказывает
=================================================
* ``DECLARED``  — ярлык объявлен манифестом или реестром;
* ``REGISTERED``— он же есть в реестре агентов;
* ``INSTALLED`` — plist лежит в каталоге автозапуска пользователя;
* ``LOADED``    — ярлык присутствует в перечне загруженных;
* ``RUNNING``   — у ярлыка ЕСТЬ номер процесса прямо сейчас. Для расписанных —
  ``NOT_APPLICABLE``; для тех, кого нет в перечне, — ``NOT_MEASURED``;
* ``PRODUCING_OUTPUT`` — объявленный артефакт существует И свеж по объявленному SLO.
  Артефакт без объявленного SLO не даёт ответа: ``NOT_MEASURED``;
* ``HEALTHY`` — требует ОБЪЯВЛЕННОГО контракта здоровья.

Про ``HEALTHY`` отдельно
========================
Контракта здоровья в системе **не существует**. Замер нашёл четыре кандидата, и ни один
им не является: ``passport.quality_metric`` порождается скриптом из тех же
``produces[].slo_hours``, то есть пересказывает свежесть своими словами; сам ``slo_hours``
отвечает на вопрос «свеж ли файл», а не «здоров ли компонент»; монитор здоровья — мнение
по форме расписания; и лишь ``cycle_exit`` объявляет настоящий контракт — для ОДНОГО
ярлыка из 103. Поэтому ``HEALTHY = NOT_MEASURED`` у 102 из 103, и выводить здоровье из
свежего файла запрещено: свежий файл доказывает, что писатель дошёл до записи, а не что
он написал верное.

Про род сущности
================
Поля ``kind``/``type``/``component_type`` нет **нигде** (0 из 103). Поэтому шесть классов
ARB из улик невыводимы, и придумывать их нельзя. Доказуемы четыре, и каждое правило
подписано ``PROVEN`` либо ``HEURISTIC``. Особо: **``AGENT`` недоказуем** — префикс имени
доказывает соглашение об именовании, а не природу сущности.

Read-only. Ничего не запускает, не останавливает и не перезапускает. Только stdlib.
"""
from __future__ import annotations

import os
import plistlib
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import owner_facts as F
except ImportError:
    import owner_facts as F

DOMAIN = 'STUDIO'

STAGES = ('DECLARED', 'REGISTERED', 'INSTALLED', 'LOADED', 'RUNNING',
          'PRODUCING_OUTPUT', 'HEALTHY')

#: Третий исход обязателен у каждой стадии. ``None`` здесь — не «нет», а «не спрашивали».
STAGE_VALUES = (True, False, None)

#: Ответ «вопрос неприменим». Отличается и от ``False``, и от ``None``: расписанное
#: задание, не работающее между запусками, не сломано и не «не измерено» — оно исправно.
NOT_APPLICABLE = 'NOT_APPLICABLE'

KINDS = ('AGENT', 'SERVICE', 'WORKER', 'SCHEDULER', 'MONITOR', 'CONNECTOR', 'UNKNOWN')
KIND_BASIS = ('PROVEN', 'HEURISTIC', 'NOT_DERIVABLE')

SCHEDULE_CLASSES = ('DAEMON', 'SCHEDULED', 'ONDEMAND', 'UNKNOWN')

_LABEL = re.compile(r'^[A-Za-z0-9_.-]+$')


def _now():
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────────────────────
#  Сбор улик (инъектируемый: тест подаёт свои, живой прогон — настоящие)
# ──────────────────────────────────────────────────────────────────────────────

def read_launchctl(runner=None):
    """Перечень загруженных ярлыков. ЧИТАЕТ и ничего не меняет.

    Отказ команды — это ``None`` (не измерено), а не пустой словарь: пустой словарь
    означал бы «ни один ярлык не загружен», то есть ложь о состоянии флота.
    """
    run = runner or (lambda: subprocess.run(['launchctl', 'list'], capture_output=True,
                                            text=True, timeout=30))
    try:
        proc = run()
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(proc, 'returncode', 1) != 0:
        return None
    rows = {}
    for line in (proc.stdout or '').splitlines()[1:]:
        parts = line.split('\t')
        if len(parts) < 3:
            continue
        pid, status, label = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not _LABEL.match(label):
            continue
        rows[label] = {
            'pid': int(pid) if pid.isdigit() else None,
            'has_pid': pid.isdigit(),
            'last_exit': int(status) if status.lstrip('-').isdigit() else None,
        }
    return rows


def read_plist(path):
    """Расписание из plist. Читается ЗНАЧЕНИЕ ``KeepAlive``, а не наличие ключа:
    ``<false/>`` при чтении по ключу превратил бы расписанного в демона."""
    try:
        with open(path, 'rb') as fh:
            doc = plistlib.load(fh)
    except (OSError, ValueError):
        return None
    keep = doc.get('KeepAlive')
    keep_alive = bool(keep) if not isinstance(keep, dict) else True
    has_interval = 'StartInterval' in doc
    has_calendar = 'StartCalendarInterval' in doc
    has_watch = 'WatchPaths' in doc or 'QueueDirectories' in doc
    if has_interval or has_calendar or has_watch:
        cls = 'SCHEDULED'
    elif keep_alive:
        cls = 'DAEMON'
    elif doc.get('RunAtLoad'):
        cls = 'ONDEMAND'
    else:
        cls = 'UNKNOWN'
    return {'schedule_class': cls, 'keep_alive': keep_alive,
            'start_interval': doc.get('StartInterval'),
            'has_calendar': has_calendar, 'has_watchpaths': has_watch,
            'run_at_load': bool(doc.get('RunAtLoad'))}


def collect_plists(directories):
    out = {}
    for d in directories:
        p = Path(d)
        if not p.is_dir():
            continue
        for f in sorted(p.glob('*.plist')):
            label = f.stem
            if label in out:
                continue
            info = read_plist(f)
            if info:
                out[label] = info
    return out


# ──────────────────────────────────────────────────────────────────────────────
#  Объявленные выходы и их свежесть
# ──────────────────────────────────────────────────────────────────────────────

def declared_outputs(manifest):
    """Объявленные артефакты из ОБЕИХ секций манифеста.

    Их две, и они разные: ``agents[].produces[]`` покрывает больше ярлыков, а
    ``artifacts[]`` объявляет SLO у всех своих строк. Объединение честнее любой из них
    по отдельности, а расхождение между ними — само по себе улика и сохраняется.
    """
    by_label = {}
    for agent in (manifest or {}).get('agents') or ():
        label = agent.get('label')
        if not label:
            continue
        for prod in agent.get('produces') or ():
            if not isinstance(prod, dict):
                continue
            art = prod.get('artifact') or prod.get('path')
            if not art:
                continue
            by_label.setdefault(label, []).append({
                'artifact': art,
                'slo_hours': prod.get('slo_hours'),
                'declared_in': 'agents[].produces[]'})
    for art in (manifest or {}).get('artifacts') or ():
        if not isinstance(art, dict):
            continue
        label, path = art.get('producer'), art.get('path')
        if not label or not path:
            continue
        rows = by_label.setdefault(label, [])
        existing = next((r for r in rows if r['artifact'] == path), None)
        if existing is None:
            rows.append({'artifact': path, 'slo_hours': art.get('slo_hours'),
                         'declared_in': 'artifacts[]'})
        elif existing.get('slo_hours') is None and art.get('slo_hours') is not None:
            existing['slo_hours'] = art.get('slo_hours')
            existing['declared_in'] = 'agents[].produces[] + artifacts[]'
        elif (art.get('slo_hours') is not None
              and existing.get('slo_hours') not in (None, art.get('slo_hours'))):
            existing['slo_conflict'] = {'agents_section': existing.get('slo_hours'),
                                        'artifacts_section': art.get('slo_hours')}
    return by_label


def artifact_freshness(root, rows, *, now, stat_fn=None):
    """Существование и возраст объявленных артефактов. Отсутствие файла — MISSING,
    не «старый» и не «ноль»."""
    stat = stat_fn or (lambda p: os.stat(p))
    out = []
    for row in rows:
        rel = str(row['artifact'])
        path = Path(root) / rel
        slo = row.get('slo_hours')
        try:
            st = stat(path)
            age = round((now.timestamp() - st.st_mtime) / 3600.0, 3)
            state = F.freshness_of(age, slo_hours=slo)
            out.append({'artifact': rel, 'exists': True, 'age_hours': age,
                        'slo_hours': slo, 'freshness_state': state,
                        'declared_in': row.get('declared_in'),
                        'slo_conflict': row.get('slo_conflict')})
        except PermissionError:
            # Нет доступа — это НЕ «файла нет». Третий исход, и он назван.
            out.append({'artifact': rel, 'exists': None, 'age_hours': None,
                        'slo_hours': slo, 'freshness_state': 'NOT_MEASURED',
                        'reason': 'нет доступа к файлу — существование не проверено',
                        'declared_in': row.get('declared_in'),
                        'slo_conflict': row.get('slo_conflict')})
        except OSError:
            out.append({'artifact': rel, 'exists': False, 'age_hours': None,
                        'slo_hours': slo, 'freshness_state': 'MISSING',
                        'declared_in': row.get('declared_in'),
                        'slo_conflict': row.get('slo_conflict')})
    return out


# ──────────────────────────────────────────────────────────────────────────────
#  Род сущности — только доказуемое
# ──────────────────────────────────────────────────────────────────────────────

def entity_kind(*, role, schedule_class, declared_kind=None):
    """Род и ОСНОВАНИЕ рода. Основание обязательно: род без основания — это догадка.

    ``AGENT`` здесь не выдаётся никогда. Ни одно поле ни в одном источнике не объявляет
    сущность агентом; префикс имени доказывает соглашение об именовании, а не природу.
    Классификация по имени ошибается в обе стороны, и это измерено.
    """
    if declared_kind and str(declared_kind).upper() in KINDS:
        return str(declared_kind).upper(), 'PROVEN', 'род объявлен источником напрямую'
    if str(role or '').lower() == 'monitoring':
        return 'MONITOR', 'PROVEN', 'manifest объявляет role=monitoring'
    if schedule_class == 'DAEMON':
        return 'SERVICE', 'PROVEN', 'plist объявляет KeepAlive без расписания — резидент'
    if schedule_class == 'SCHEDULED':
        return 'WORKER', 'PROVEN', 'plist объявляет расписание — задание по расписанию'
    if schedule_class == 'ONDEMAND':
        return 'WORKER', 'HEURISTIC', 'RunAtLoad без расписания: форма исполнения разовая'
    return 'UNKNOWN', 'NOT_DERIVABLE', 'ни plist, ни расписание не объявлены'


# ──────────────────────────────────────────────────────────────────────────────
#  Сборка модели
# ──────────────────────────────────────────────────────────────────────────────

def fleet_prefixes(declared_labels):
    """Область флота, ВЫВЕДЕННАЯ из объявленных ярлыков, а не вписанная константой.

    Без неё сюда попадает весь перечень системы: первый прогон дал 658 сущностей,
    из них 550 — служебные ярлыки самой ОС, и «419 не работают» относилось к ним.
    Ровно тот класс, где счётчик честно считает НЕ ТО НАСЕЛЕНИЕ. Область берётся из
    первых двух сегментов объявленных имён: что объявлено манифестом и реестром, то и
    есть флот; что делит с ними пространство имён — кандидат того же флота.
    """
    out = set()
    for label in declared_labels:
        parts = str(label).split('.')
        if len(parts) >= 2:
            out.add('.'.join(parts[:2]) + '.')
    return out


def build_service_health(*, manifest, registry=None, launchctl=None, plists=None,
                         production_root=None, now=None, stat_fn=None,
                         prefixes=None):
    """Производная модель здоровья. НИЧЕГО не меняет и ничего не запускает."""
    now = now or _now()
    plists_given = plists is not None
    plists = plists or {}
    outputs = declared_outputs(manifest)
    registry_labels = {a.get('label') for a in (registry or {}).get('agents') or ()
                       if a.get('label')}
    manifest_agents = {a.get('label'): a for a in (manifest or {}).get('agents') or ()
                       if a.get('label')}
    declared = set(manifest_agents) | registry_labels
    scope = set(prefixes) if prefixes is not None else fleet_prefixes(declared)

    def in_fleet(label):
        return label in declared or any(str(label).startswith(p) for p in scope)

    plists = {k: v for k, v in plists.items() if in_fleet(k)}
    if launchctl is not None:
        launchctl = {k: v for k, v in launchctl.items() if in_fleet(k)}
    labels = sorted(declared | set(plists) | set(launchctl or {}))

    entities, counts = [], {
        'total': 0, 'running_true': 0, 'running_not_applicable': 0,
        'running_not_measured': 0, 'running_false': 0,
        # Отдельный счётчик наблюдения, а не стадии. Расписанное задание, застигнутое
        # в середине прогона, ИМЕЕТ живой процесс — и при этом стадия RUNNING у него
        # по-прежнему неприменима. Независимая сверка нашла ровно это расхождение:
        # два верных ответа на два разных вопроса под одним именем.
        'has_live_process': 0,
        'producing_true': 0, 'producing_false': 0, 'producing_not_measured': 0,
        'health_measured': 0, 'health_not_measured': 0,
        'stale_output': 0, 'missing_output': 0, 'nonzero_last_exit': 0,
        'entities_with_declared_slo': 0,
    }
    by_kind, by_schedule = {}, {}
    problems = []

    for label in labels:
        agent = manifest_agents.get(label) or {}
        plist = plists.get(label)
        live = (launchctl or {}).get(label)
        in_listing = launchctl is not None and label in launchctl
        schedule_class = (plist or {}).get('schedule_class') or 'UNKNOWN'
        role = agent.get('role')
        intent = agent.get('intent')
        kind, basis, basis_note = entity_kind(role=role, schedule_class=schedule_class,
                                              declared_kind=agent.get('kind'))

        # ── RUNNING: три разных ответа, и ни один не подменяет другой.
        if schedule_class in ('SCHEDULED', 'ONDEMAND'):
            running, running_note = NOT_APPLICABLE, (
                'расписанное задание между запусками не работает ПО ПОСТРОЕНИЮ; '
                'отсутствие процесса здесь не поломка')
        elif schedule_class == 'UNKNOWN':
            # Форма исполнения не объявлена ⇒ неизвестно, ОБЯЗАН ли процесс быть.
            # Судить такую сущность по правилу резидента значит выдумать ей расписание.
            running, running_note = None, (
                'форма исполнения не объявлена: неизвестно, должен ли процесс быть '
                'запущен прямо сейчас')
        elif launchctl is None or not in_listing:
            running, running_note = None, 'ярлыка нет в перечне загруженных — не измерено'
        else:
            running = bool(live and live.get('has_pid'))
            running_note = ('у ярлыка есть номер процесса прямо сейчас' if running
                            else 'резидент объявлен, но процесса нет')
            if not running:
                problems.append({'label': label, 'problem': 'DAEMON_NOT_RUNNING',
                                 'detail': running_note})

        # ── PRODUCING_OUTPUT: артефакт существует И свеж по ОБЪЯВЛЕННОМУ сроку.
        rows = outputs.get(label) or []
        fresh_rows = artifact_freshness(production_root or '.', rows, now=now,
                                        stat_fn=stat_fn) if (rows and production_root) else []
        with_slo = [r for r in fresh_rows if r['slo_hours'] is not None]
        if not rows:
            producing, producing_note = None, 'ни один артефакт не объявлен — не измерено'
        elif not with_slo:
            producing, producing_note = None, (
                'артефакт объявлен, но срок годности не объявлен: «свеж ли он» — вопрос '
                'без объявленной нормы')
        else:
            bad = [r for r in with_slo if r['freshness_state'] in ('STALE', 'MISSING')]
            producing = not bad
            producing_note = ('все объявленные артефакты свежи по объявленному сроку'
                              if producing else
                              'есть артефакты просроченные или отсутствующие')
            for r in bad:
                counts['stale_output' if r['freshness_state'] == 'STALE'
                       else 'missing_output'] += 1
                problems.append({'label': label,
                                 'problem': f'OUTPUT_{r["freshness_state"]}',
                                 'detail': r['artifact'], 'age_hours': r['age_hours'],
                                 'slo_hours': r['slo_hours'],
                                 'intent': intent})

        # ── HEALTHY: только по ОБЪЯВЛЕННОМУ контракту. Его нет — значит не измерено.
        contract = agent.get('health_contract')
        if contract:
            healthy, health_note = None, 'контракт объявлен, исполнитель пробы не написан'
            counts['health_measured'] += 0
        else:
            healthy, health_note = None, (
                'контракта здоровья для этой сущности не объявлено; выводить здоровье '
                'из свежего файла запрещено — свежий файл доказывает, что писатель дошёл '
                'до записи, а не что он написал верное')
        counts['health_not_measured'] += 1

        last_exit = (live or {}).get('last_exit')
        if last_exit not in (None, 0):
            counts['nonzero_last_exit'] += 1
            problems.append({'label': label, 'problem': 'NONZERO_LAST_EXIT',
                             'detail': last_exit,
                             'note': 'код выхода ИСТОРИЧЕН: он говорит о прошлом запуске, '
                                     'а не о состоянии сейчас'})

        entities.append({
            'label': label,
            'kind': kind, 'kind_basis': basis, 'kind_basis_note': basis_note,
            'role_declared': role, 'intent': intent,
            'schedule_class': schedule_class,
            'stages': {
                # Три отдельных вопроса, и у каждого свой источник. Если источник не
                # подан, ответ — `None` («не спрашивали»), а не `False` («нет»):
                # реестр, которого нам не дали, не доказывает незарегистрированность.
                'DECLARED': (None if not manifest_agents and not registry_labels
                             else (label in manifest_agents or label in registry_labels)),
                'REGISTERED': (None if registry is None
                               else label in registry_labels),
                'INSTALLED': (None if not plists_given else label in plists),
                'LOADED': (None if launchctl is None else in_listing),
                'RUNNING': running,
                'PRODUCING_OUTPUT': producing,
                'HEALTHY': healthy,
            },
            'stage_notes': {'RUNNING': running_note, 'PRODUCING_OUTPUT': producing_note,
                            'HEALTHY': health_note},
            'declared_outputs': fresh_rows,
            'declared_output_count': len(rows),
            'last_exit': last_exit,
            'has_pid': (live or {}).get('has_pid') if in_listing else None,
        })
        counts['total'] += 1
        if with_slo:
            counts['entities_with_declared_slo'] += 1
        if (live or {}).get('has_pid'):
            counts['has_live_process'] += 1
        if running is True:
            counts['running_true'] += 1
        elif running is False:
            counts['running_false'] += 1
        elif running == NOT_APPLICABLE:
            counts['running_not_applicable'] += 1
        else:
            counts['running_not_measured'] += 1
        if producing is True:
            counts['producing_true'] += 1
        elif producing is False:
            counts['producing_false'] += 1
        else:
            counts['producing_not_measured'] += 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_schedule[schedule_class] = by_schedule.get(schedule_class, 0) + 1

    # Проблемы у ушедших на покой — не проблемы флота. Разделяем, а не прячем.
    retired = [p for p in problems if p.get('intent') == 'retired']
    active = [p for p in problems if p.get('intent') != 'retired']
    return {
        'schema': 'service_health/1',
        'state': 'READ',
        'fleet_prefixes': sorted(scope),
        'population_basis': ('флот = объявленное манифестом и реестром плюс то, что делит с '
                             'ними пространство имён; перечень ОС в население не входит'),
        'measured_at': now.isoformat(),
        'entities': entities,
        'counts': counts,
        'by_kind': by_kind,
        'by_schedule_class': by_schedule,
        'problems': active,
        'problems_retired': retired,
        'health_contract_exists': False,
        'health_contract_note':
            'объявленного контракта здоровья в системе нет ни для одной сущности; '
            'поэтому HEALTHY честно не измерено, а не «в порядке»',
        'kind_note':
            'ни один источник не объявляет род сущности полем; AGENT недоказуем в '
            'принципе — префикс имени доказывает соглашение об именовании',
        'running_note':
            'RUNNING отвечает только за резидентов; у расписанных заданий вопрос '
            'НЕПРИМЕНИМ, и отсутствие процесса у них не поломка',
        'last_exit_note':
            'код последнего выхода историчен: ненулевой код у живого сейчас процесса '
            'говорит о прошлом запуске',
    }
