#!/usr/bin/env python3
"""Studio · Состояние роли в рантайме — ВЫВЕДЕННОЕ, а не проставленное.

Зачем этот модуль появился
==========================
Кокпит утверждал «CIO в рантайме: DOCUMENTED_ONLY». Замер показал, откуда взялось это
утверждение: из **литерала тестовой фикстуры**. Производитель состояние роли не
вычислял вовсе — это был аргумент командной строки, и его никто не подавал.

Владелец поправил: CIO здесь — **Chief Investment Officer**, и он построен. Замер
подтвердил: модуль есть, расписание объявлено значением `StartInterval = 3600`, выход
свежий, и — решающее — его читают **в денежном пути**: `cio_arming.gate_sleeve_book`
вызывается из `hy_cycle` и `lp_cycle` и решает, двигать ли книгу.

То есть экран годами мог утверждать обратное тому, что есть, потому что утверждение не
было ничем измерено. Этот модуль закрывает класс: состояние роли собирается из улик, и
у каждой улики назван адрес.

Шесть состояний, и у каждого своё условие
=========================================
* ``DOCUMENTED_ONLY`` — есть документы, кода нет;
* ``CODE_EXISTS`` — модуль есть, расписания нет;
* ``SCHEDULED`` — расписание объявлено, свежего выхода нет;
* ``RUNTIME_EXISTS`` — выход свежий, но его никто не читает;
* ``ACTIVE`` — выход свежий И у него есть читатель;
* ``NOT_MEASURED`` — улик не собрали.

Различие между ``RUNTIME_EXISTS`` и ``ACTIVE`` существенно и делается намеренно: «свежий
артефакт, который никто не читает» — это работа в никуда, и три месяца в этом проекте
так и писался отчёт одного куратора.

Only stdlib. Ничего не запускает и не меняет.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'role_lifecycle/1'

STATES = ('DOCUMENTED_ONLY', 'CODE_EXISTS', 'SCHEDULED', 'RUNTIME_EXISTS', 'ACTIVE',
          'NOT_MEASURED')

#: Что объявляет роль. Каждое поле — АДРЕС улики, а не мнение о ней.
#: Список объявлен здесь, потому что «найти роль поиском по имени» уже однажды
#: назвало сторожа соответствия Архитектором.
ROLE_EVIDENCE = {
    'CIO': {
        'display': 'Portfolio CIO (Chief Investment Officer)',
        'module': 'spa_core/investment_os/agents/chief_investment.py',
        'label': 'com.spa.io_chief_investment',
        'output': 'data/investment_os/chief_investment.json',
        'output_slo_hours': 2.0,
        'consumer_probe': {
            'paths': ('spa_core/paper_trading', 'spa_core/strategy_lab'),
            'symbols': ('cio_arming', 'chief_investment'),
        },
        'docs': ('docs/08_ai_investment_os_architecture.md',),
    },
    'ARCHITECT': {
        'display': 'Архитектор',
        'module': None,
        'label': None,
        'output': None,
        'output_slo_hours': None,
        'consumer_probe': None,
        'docs': ('docs/10_agent_architecture.md', 'docs/ADR_004_two_layer_agents.md'),
    },
}


def _now():
    return datetime.now(timezone.utc)


def _age_hours(path, *, now):
    try:
        return round((now.timestamp() - os.stat(path).st_mtime) / 3600.0, 3)
    except OSError:
        return None


def _schedule_of(label, *, launchd_dirs):
    """Расписание из plist — по ЗНАЧЕНИЮ ключа, не по его наличию."""
    if not label:
        return None
    for d in launchd_dirs:
        p = Path(d).expanduser() / f'{label}.plist'
        if not p.is_file():
            continue
        try:
            with open(p, 'rb') as fh:
                doc = plistlib.load(fh)
        except (OSError, ValueError):
            continue
        keep = doc.get('KeepAlive')
        return {'plist': p.name,
                'start_interval': doc.get('StartInterval'),
                'has_calendar': 'StartCalendarInterval' in doc,
                'run_at_load': bool(doc.get('RunAtLoad')),
                'keep_alive': bool(keep) if not isinstance(keep, dict) else True,
                'declared': bool(doc.get('StartInterval')
                                 or 'StartCalendarInterval' in doc
                                 or (keep if not isinstance(keep, dict) else True))}
    return None


def _consumers(probe, *, production_root):
    """Кто ЧИТАЕТ выход роли. Ищется по ИМПОРТУ и по вызову, а не по имени файла.

    Документированная ловушка этого репозитория: гейты денежного пути импортируют
    модули, а не читают `data/*.json` по имени. Поиск по имени файла ответил бы
    «читателя нет» там, где он есть.
    """
    if not probe:
        return None
    root = Path(production_root)
    found = []
    pattern = re.compile(r'\b(?:from|import)\s+\S*(' + '|'.join(
        re.escape(s) for s in probe['symbols']) + r')\b|(' + '|'.join(
        re.escape(s) for s in probe['symbols']) + r')\.\w+\s*\(')
    for rel in probe['paths']:
        base = root / rel
        if not base.is_dir():
            continue
        for f in sorted(base.rglob('*.py')):
            try:
                text = f.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    found.append({'file': str(f.relative_to(root)), 'line': i,
                                  'code': line.strip()[:110]})
    return found


def measure_role(name, *, production_root, launchd_dirs=None, now=None):
    """Состояние ОДНОЙ роли из улик. Ни одного литерала вердикта."""
    now = now or _now()
    spec = ROLE_EVIDENCE.get(name)
    if spec is None:
        return {'schema': SCHEMA, 'role': name, 'state': 'NOT_MEASURED',
                'reason': f'улики для роли {name} не объявлены'}
    root = Path(production_root)
    dirs = launchd_dirs or ['~/Library/LaunchAgents', str(root / 'launchd')]

    module_exists = bool(spec['module']) and (root / spec['module']).is_file()
    docs_present = [d for d in spec['docs'] if (root / d).is_file()]
    schedule = _schedule_of(spec['label'], launchd_dirs=dirs)
    output_age = _age_hours(root / spec['output'], now=now) if spec['output'] else None
    slo = spec['output_slo_hours']
    output_fresh = (output_age is not None and slo is not None and output_age <= slo)
    consumers = _consumers(spec['consumer_probe'], production_root=root)

    if output_fresh and consumers:
        state = 'ACTIVE'
        why = (f'выход свежий ({output_age} ч ≤ {slo} ч) И его читают: '
               f'{len(consumers)} мест')
    elif output_fresh:
        state = 'RUNTIME_EXISTS'
        why = ('выход свежий, но читателя не найдено — работа в никуда, и это другое '
               'состояние, чем ACTIVE')
    elif schedule and schedule['declared']:
        state = 'SCHEDULED'
        why = 'расписание объявлено, свежего выхода нет'
    elif module_exists:
        state = 'CODE_EXISTS'
        why = 'модуль есть, расписания не объявлено'
    elif docs_present:
        state = 'DOCUMENTED_ONLY'
        why = f'документы есть ({len(docs_present)}), кода не найдено'
    else:
        state = 'NOT_MEASURED'
        why = 'ни модуля, ни расписания, ни документов не найдено'

    return {
        'schema': SCHEMA,
        'role': name,
        'display_name': spec['display'],
        'state': state,
        'why': why,
        'measured_at': now.isoformat(),
        'evidence': {
            'module': spec['module'], 'module_exists': module_exists,
            'label': spec['label'], 'schedule': schedule,
            'output': spec['output'], 'output_age_hours': output_age,
            'output_slo_hours': slo, 'output_fresh': output_fresh,
            'consumers': consumers, 'consumer_count': (None if consumers is None
                                                       else len(consumers)),
            'documents_present': docs_present,
        },
        'derivation_note': ('состояние выведено из улик, а не проставлено. Прежнее '
                            'утверждение «DOCUMENTED_ONLY» приходило из литерала '
                            'тестовой фикстуры и ничем не измерялось'),
    }


def measure_roles(*, production_root, launchd_dirs=None, now=None):
    now = now or _now()
    rows = {name: measure_role(name, production_root=production_root,
                               launchd_dirs=launchd_dirs, now=now)
            for name in ROLE_EVIDENCE}
    return {'schema': SCHEMA, 'measured_at': now.isoformat(), 'roles': rows,
            'states': {n: r['state'] for n, r in rows.items()}}
