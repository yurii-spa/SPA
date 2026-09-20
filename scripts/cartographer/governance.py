#!/usr/bin/env python3
"""Управление и восстановление (Director OS Phase 8) — чем система управляется и можем ли
мы её восстановить.

READ-ONLY. Новый governance-движок здесь не строится, разрешения не меняются,
восстановление не выполняется. Слой читает существующие решения, правила, границы
разрешений и улики восстановления — и показывает их вместе с тем, чем каждое доказано.

ДВЕ ГРАНИЦЫ, КОТОРЫЕ ЭТОТ СЛОЙ ДЕРЖИТ ЖЁСТКО:

* **наличие резерва — не доказательство восстановления.** Архив на диске говорит только о
  том, что архив есть. Доказательством является ПРОВЕДЁННАЯ проба восстановления с
  результатом;
* **описанный откат — не проверенный откат.** Процедура в документе и запись об её
  исполнении — разные улики, и вторая здесь не выводится из первой.

Общего балла управления нет намеренно: пробел в резервах и пробел в разрешениях — разные
вещи, и сумма их не описывает.
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

SCHEMA = 'cartographer.governance_snapshot/0.1'

CATEGORIES = ('decision', 'rule', 'invariant', 'permission', 'recovery', 'backup',
              'security', 'deployment', 'gap')

AUTHORITY_STATES = ('AUTHORITATIVE', 'AUTHORITY_UNDEFINED', 'NOT_AUTHORITY')

RECOVERY_STATES = ('TESTED', 'DOCUMENTED_UNTESTED', 'MISSING', 'NOT_APPLICABLE',
                   'UNKNOWN')

RECOVERY_DEFINITIONS = {
    'TESTED': 'процедура описана И есть запись о проведённой пробе с результатом — '
              'доказано',
    'DOCUMENTED_UNTESTED': 'документ существует, доказательства исполнения НЕ найдено. '
                           'Это НЕ «неизвестно»: известно ровно то, что пробы нет',
    'MISSING': 'процедуры не найдено',
    'NOT_APPLICABLE': 'к этому предмету восстановление не относится',
    'UNKNOWN': 'состояние действительно не измерено — ни документа, ни отсутствия его '
               'установить не удалось',
}

PERMISSION_ZONES = ('OWNER_GATED', 'AGENT_DECIDES', 'UNKNOWN')

PERMISSION_DEFINITIONS = {
    'OWNER_GATED': 'предмет из трёх, оставленных за владельцем (ADR-285): движение '
                   'реальных денег · публичные числа, нейминг и legal · необратимые '
                   'действия',
    'AGENT_DECIDES': 'вне трёх предметов: агент решает сам и фиксирует записью',
    'UNKNOWN': 'правило не относит предмет ни к одной зоне — не измерено',
}

# Род правила разрешения. «Правило о разрешениях» и «ворота одобрения владельца» — НЕ одно
# и то же: правило «агент решает сам» тоже относится к разрешениям, но одобрения не
# требует, а аварийная граница срабатывает сама.
PERMISSION_CLASSES = ('OWNER_GATED', 'AUTONOMOUS', 'EMERGENCY', 'UNKNOWN')

PERMISSION_CLASS_DEFINITIONS = {
    'OWNER_GATED': 'источник ПРЯМО оставляет предмет за владельцем',
    'AUTONOMOUS': 'источник прямо говорит, что агент решает сам',
    'EMERGENCY': 'аварийная граница: срабатывает по правилу, а не по чьему-то решению',
    'UNKNOWN': 'род правила из улик не следует',
}

APPROVAL_STATES = ('REQUIRED', 'NOT_REQUIRED', 'UNKNOWN')

# ОБЛАСТЬ зонирования объявлена самим правилом: граница ADR-285 говорит о ПРЕДМЕТАХ
# решений и действий («что сюда входит: включение исполнения, платежи… удаление данных,
# публикация вовне»), и отдельно распространена на git/PR. Документ — ADR, правило,
# инвариант, runbook, архив — предметом решения не является, и требовать у него зону
# значило бы выдумать универсальное требование, которого правило не объявляло.
ZONE_SCOPES = ('ZONE_REQUIRED', 'ZONE_NOT_APPLICABLE', 'ZONE_SCOPE_UNKNOWN')

ZONE_SCOPE_DEFINITIONS = {
    'ZONE_REQUIRED': 'запись описывает ДЕЙСТВИЕ или предмет решения — правило требует '
                     'отнести её к зоне',
    'ZONE_NOT_APPLICABLE': 'запись описывает ДОКУМЕНТ или наблюдение; область правила на '
                           'неё не распространяется, и это не пробел',
    'ZONE_SCOPE_UNKNOWN': 'к какой области относится запись, установить не удалось',
}

# Категории, которые описывают действия. Списком, а не догадкой по названию записи.
_ZONE_REQUIRED_CATEGORIES = ('permission', 'deployment')
_ZONE_NOT_APPLICABLE_CATEGORIES = ('decision', 'rule', 'invariant', 'recovery', 'backup',
                                   'security', 'gap')

ZONE_SCOPE_BASIS = (
    'CLAUDE.md, «Граница “решай сам” / “спроси меня” — ПО ПРЕДМЕТУ (ADR-285)»: предметы '
    'перечислены как ДЕЙСТВИЯ («включение исполнения, ключи, платежи… удаление данных, '
    'публикация вовне»), и отдельно сказано «Та же граница действует на git/PR». '
    'Документы — ADR, правила, инварианты, runbook-и, архивы — предметом решения не '
    'являются, поэтому зона к ним не требуется.')


class GovernanceInputError(Exception):
    """Вход не соответствует контракту. Отказ, а не молчаливая догадка."""


SOURCE_CONTRACTS = {
    'docs/decisions/*.md': {
        'governs': 'архитектурные решения (ADR), меняющие инварианты и контуры',
        'basis': 'declared', 'authority_status': 'AUTHORITATIVE',
        'authority_quote': 'CLAUDE.md: «решение → ADR (docs/decisions/)»; '
                           'docs/decisions/INDEX.md: «Каждое решение, меняющее инвариант '
                           '/ risk-логику / контур, оформляется ADR»',
        'owner': '@yurii', 'has_recovery': False,
    },
    'docs/adr/*.md': {
        'governs': 'второй каталог ADR того же репозитория',
        'basis': 'declared', 'authority_status': 'AUTHORITY_UNDEFINED',
        'authority_quote': 'CLAUDE.md сам называет два реестра ADR с коллизиями номеров: '
                           '«Два реестра ADR (docs/adr/, docs/decisions/) с 5 коллизиями '
                           'номеров… “ADR-053” неоднозначен». Правила, чей реестр '
                           'сильнее, нет',
        'owner': 'UNKNOWN', 'has_recovery': False,
    },
    'docs/decisions/INDEX.md': {
        'governs': 'сводный реестр ADR',
        'basis': 'derived', 'authority_status': 'NOT_AUTHORITY',
        'authority_quote': 'индекс: сами решения живут в файлах ADR',
        'owner': 'UNKNOWN', 'has_recovery': False,
    },
    '.claude/rules/*.md': {
        'governs': 'действующие правила по областям (risk, deployment, приёмка, сайт)',
        'basis': 'declared', 'authority_status': 'AUTHORITATIVE',
        'authority_quote': 'CLAUDE.md: «Действующие правила живут только в CLAUDE.md / '
                           '.claude/rules/»',
        'owner': '@yurii', 'has_recovery': False,
    },
    'CLAUDE.md': {
        'governs': 'инварианты и граница «решай сам / спроси меня» (ADR-285)',
        'basis': 'declared', 'authority_status': 'AUTHORITATIVE',
        'authority_quote': 'сам файл: «Инварианты (нарушать нельзя)» и «Граница “решай '
                           'сам” / “спроси меня” — ПО ПРЕДМЕТУ (ADR-285)»',
        'owner': '@yurii', 'has_recovery': False,
    },
    'data/restore_drill_status.json': {
        'governs': 'пробу восстановления из резервной копии',
        'basis': 'observed', 'authority_status': 'NOT_AUTHORITY',
        'authority_quote': 'наблюдение: запись о проведённой пробе',
        'owner': 'UNKNOWN', 'has_recovery': True,
    },
    'data/dr_offsite_status.json': {
        'governs': 'вынос резервной копии за пределы машины',
        'basis': 'observed', 'authority_status': 'NOT_AUTHORITY',
        'authority_quote': 'наблюдение: запись о выносе и сверке',
        'owner': 'UNKNOWN', 'has_recovery': True,
    },
    'data/deployment_acceptance.json': {
        'governs': 'способность флота стартовать после изменения дерева',
        'basis': 'observed', 'authority_status': 'NOT_AUTHORITY',
        'authority_quote': 'наблюдение приёмки развёртывания',
        'owner': 'UNKNOWN', 'has_recovery': False,
    },
    'data/code_sync_status.json': {
        'governs': 'канонический путь доставки origin → прод-дерево',
        'basis': 'observed', 'authority_status': 'NOT_AUTHORITY',
        'authority_quote': 'наблюдение последней синхронизации',
        'owner': 'UNKNOWN', 'has_recovery': False,
    },
    'scripts/code_sync_from_origin.sh': {
        'governs': 'правила канонической доставки: что синхронизируется, что никогда',
        'basis': 'declared', 'authority_status': 'AUTHORITATIVE',
        'authority_quote': 'сам скрипт: «CODE ONLY, whole directories… NEVER data/ (live '
                           'track), docs/, nimbalyst-local/, KANBAN.json» и «A checkout '
                           'does not DELETE»',
        'owner': '@yurii', 'has_recovery': False,
    },
    'data/security_alerts.json': {
        'governs': 'тревоги безопасности',
        'basis': 'observed', 'authority_status': 'NOT_AUTHORITY',
        'authority_quote': 'наблюдение сторожа безопасности',
        'owner': 'UNKNOWN', 'has_recovery': False,
    },
    'data/kill_switch_status.json': {
        'governs': 'состояние стоп-крана',
        'basis': 'observed', 'authority_status': 'NOT_AUTHORITY',
        'authority_quote': 'наблюдение состояния',
        'owner': 'UNKNOWN', 'has_recovery': False,
    },
}

# Документы-процедуры. Наличие документа — улика ОПИСАНИЯ, не исполнения.
RUNBOOKS = ('docs/DISASTER_RECOVERY.md', 'docs/INCIDENT_RESPONSE.md',
            'docs/DEPLOYMENT_RUNBOOK.md', 'docs/RUNBOOK.md',
            'docs/TOKEN_ROTATION_RUNBOOK.md', 'docs/operator_runbook.md',
            'docs/LIVE_LAUNCH_RUNBOOK.md')


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _read_json(path):
    return reliability_mod._read_json(path)


def redact(text):
    return reliability_mod.redact(text)


def _evidence(kind, detail, where=None):
    return {'kind': kind, 'detail': redact(str(detail)[:600]), 'where': where}


def _item(governance_id, category, title, *, status, authority_source, evidence,
          owner='UNKNOWN', decision_ref=None, permission_zone='UNKNOWN',
          permission_class='UNKNOWN', zone_scope=None,
          approval_required='UNKNOWN', recovery_status='UNKNOWN', recovery_evidence=(),
          security_status='UNKNOWN', last_verified_at=None, freshness='UNKNOWN',
          related_work=(), related_findings=()):
    if category not in CATEGORIES:
        raise GovernanceInputError(f'{governance_id}: категория {category!r} вне словаря')
    if not evidence:
        raise GovernanceInputError(f'{governance_id}: запись без улики')
    return {
        'governance_id': governance_id, 'category': category, 'title': redact(title),
        'status': status, 'authority_source': authority_source, 'owner': owner,
        'decision_ref': decision_ref, 'permission_zone': permission_zone,
        'permission_class': permission_class,
        'zone_scope': (zone_scope if zone_scope else
                       ('ZONE_REQUIRED' if category in _ZONE_REQUIRED_CATEGORIES
                        else 'ZONE_NOT_APPLICABLE'
                        if category in _ZONE_NOT_APPLICABLE_CATEGORIES
                        else 'ZONE_SCOPE_UNKNOWN')),
        'approval_required': approval_required, 'recovery_status': recovery_status,
        'recovery_evidence': list(recovery_evidence), 'security_status': security_status,
        'last_verified_at': last_verified_at, 'freshness': freshness,
        'related_work': list(related_work), 'related_findings': list(related_findings),
        'evidence': list(evidence),
    }


def _source_record(name, path, status, *, note='', observed_at=None, now=None):
    c = SOURCE_CONTRACTS.get(name, {})
    return {
        'source': name, 'path': str(path), 'status': status,
        'governs': c.get('governs'), 'basis': c.get('basis'),
        'authority_status': c.get('authority_status', 'AUTHORITY_UNDEFINED'),
        'authority_quote': c.get('authority_quote'),
        'owner': c.get('owner', 'UNKNOWN'),
        'has_recovery_procedure': c.get('has_recovery'),
        'last_updated': observed_at,
        'age_hours': reliability_mod._age_hours(observed_at, now or _now())
        if observed_at else None,
        'freshness': 'UNKNOWN',
        'freshness_rule': 'собственного срока годности источник не объявляет — свежесть '
                          'НЕ измерена',
        'note': note,
    }


def _adr_items(production, sources, now):
    """Решения из обоих реестров. Коллизия номеров НЕ разрешается — она показывается."""
    items, seen = [], {}
    for folder, name in (('docs/decisions', 'docs/decisions/*.md'),
                         ('docs/adr', 'docs/adr/*.md')):
        root = Path(production) / folder
        files = sorted(root.glob('ADR-*.md')) if root.is_dir() else []
        sources.append(_source_record(name, root, 'READ' if files else 'ABSENT',
                                      note=f'{len(files)} решений', now=now))
        for f in files:
            number = re.match(r'(ADR-\d+)', f.name)
            number = number.group(1) if number else f.stem
            title = ''
            try:
                head = f.read_text(encoding='utf-8', errors='replace').splitlines()[:6]
                title = next((l.lstrip('# ').strip() for l in head if l.startswith('#')),
                             f.stem)
            except OSError:
                title = f.stem
            seen.setdefault(number, []).append((name, f, title))
    for number, entries in sorted(seen.items()):
        name, f, title = entries[0]
        ev = [_evidence('adr_file', f'{f.name}', name)]
        status = 'DECLARED'
        if len(entries) > 1:
            status = 'NUMBER_COLLISION'
            ev.append(_evidence(
                'collision',
                'номер занят в ОБОИХ реестрах: '
                + ', '.join(str(x[1].parent.name) + '/' + x[1].name for x in entries)
                + '. Правила, чей реестр сильнее, нет — победителя не выбираем',
                'docs'))
        items.append(_item(
            number, 'decision', title, status=status,
            authority_source=('AUTHORITY_UNDEFINED' if len(entries) > 1
                              else SOURCE_CONTRACTS[name]['authority_status']),
            owner=SOURCE_CONTRACTS[name].get('owner', 'UNKNOWN'),
            decision_ref=number, permission_zone='UNKNOWN',
            approval_required='UNKNOWN', recovery_status='NOT_APPLICABLE',
            evidence=ev))
    return items


def _rule_items(production, sources, now):
    items = []
    root = Path(production) / '.claude/rules'
    files = sorted(root.glob('*.md')) if root.is_dir() else []
    sources.append(_source_record('.claude/rules/*.md', root,
                                  'READ' if files else 'ABSENT',
                                  note=f'{len(files)} правил', now=now))
    for f in files:
        try:
            first = f.read_text(encoding='utf-8', errors='replace').splitlines()[0]
        except OSError:
            first = f.stem
        items.append(_item(
            f'rule:{f.name}', 'rule', first.lstrip('# ').strip() or f.stem,
            status='ACTIVE', authority_source='AUTHORITATIVE', owner='@yurii',
            permission_zone='UNKNOWN', approval_required='UNKNOWN',
            recovery_status='NOT_APPLICABLE',
            evidence=[_evidence('rule_file', f.name, '.claude/rules')]))
    return items


_INVARIANT_RE = re.compile(r'^(\d{1,2})\.\s+\*\*(.+?)\*\*', re.M)


def _invariant_items(production, sources, now):
    """Инварианты и три предмета владельца — цитатами из CLAUDE.md, а не пересказом."""
    p = Path(production) / 'CLAUDE.md'
    if not p.is_file():
        sources.append(_source_record('CLAUDE.md', p, 'ABSENT', now=now))
        return []
    text = p.read_text(encoding='utf-8', errors='replace')
    sources.append(_source_record('CLAUDE.md', p, 'READ',
                                  note=f'{len(text.splitlines())} строк', now=now))
    items = []
    block = text[text.index('## 🔒 Инварианты'):] if '## 🔒 Инварианты' in text else ''
    block = block[:block.index('###')] if '###' in block else block
    for number, title in _INVARIANT_RE.findall(block):
        items.append(_item(
            f'invariant:{number}', 'invariant', title.strip(), status='ACTIVE',
            authority_source='AUTHORITATIVE', owner='@yurii',
            permission_zone='UNKNOWN', approval_required='UNKNOWN',
            recovery_status='NOT_APPLICABLE',
            evidence=[_evidence('claude_md', f'инвариант #{number}: {title}',
                                'CLAUDE.md')]))
    # три предмета владельца — зона OWNER_GATED, объявленная самим файлом
    if 'Граница «решай сам»' in text or 'ADR-285' in text:
        for subject in ('Движение реальных денег',
                        'Публичные числа доходности, нейминг тиров, юридические '
                        'формулировки',
                        'Необратимые действия'):
            items.append(_item(
                f'permission:{subject[:28]}', 'permission', subject, status='ACTIVE',
                authority_source='AUTHORITATIVE', owner='@yurii',
                decision_ref='ADR-285', permission_zone='OWNER_GATED',
                permission_class='OWNER_GATED',
                approval_required='REQUIRED', recovery_status='NOT_APPLICABLE',
                evidence=[_evidence(
                    'boundary',
                    'CLAUDE.md, «Граница “решай сам” / “спроси меня” — ПО ПРЕДМЕТУ '
                    '(ADR-285)»: за владельцем остаются ровно три предмета — источник '
                    'ПРЯМО требует решения владельца',
                    'CLAUDE.md')]))
        items.append(_item(
            'permission:agent_decides', 'permission',
            'Всё вне трёх предметов агент решает сам', status='ACTIVE',
            authority_source='AUTHORITATIVE', owner='@yurii', decision_ref='ADR-285',
            permission_zone='AGENT_DECIDES', permission_class='AUTONOMOUS',
            approval_required='NOT_REQUIRED', recovery_status='NOT_APPLICABLE',
            evidence=[_evidence('boundary',
                                'CLAUDE.md: «Всё остальное агент решает сам и фиксирует '
                                'записью в журнал, а не вопросом» — одобрения владельца '
                                'источник здесь НЕ требует', 'CLAUDE.md')]))
    return items


def _recovery_items(production, sources, now):
    """Восстановление: описание и ИСПОЛНЕНИЕ — разные улики, и вторая не следует из первой.

    Наличие архива доказывает только наличие архива. Доказательством восстановления
    является запись о проведённой пробе с результатом; описанный откат без записи об
    исполнении остаётся DOCUMENTED_NOT_TESTED.
    """
    items = []
    data = Path(production) / 'data'

    drill, state = _read_json(data / 'restore_drill_status.json')
    sources.append(_source_record('data/restore_drill_status.json',
                                  data / 'restore_drill_status.json', state,
                                  observed_at=(drill or {}).get('last_drill_ts')
                                  if isinstance(drill, dict) else None, now=now))
    if isinstance(drill, dict):
        ok = drill.get('all_ok')
        validated = drill.get('files_validated') or []
        items.append(_item(
            'recovery:restore_drill', 'recovery',
            'Восстановление из резервной копии — проба проведена', status='ACTIVE',
            authority_source='NOT_AUTHORITY', owner='UNKNOWN',
            recovery_status=('TESTED' if ok else 'DOCUMENTED_UNTESTED'),
            recovery_evidence=[_evidence(
                'drill',
                f"проба {drill.get('last_drill_ts')}: all_ok={ok}, архив "
                f"{drill.get('archive')}, проверено файлов {len(validated)}",
                'data/restore_drill_status.json')],
            last_verified_at=drill.get('last_drill_ts'),
            evidence=[_evidence('drill_record',
                                'запись о проведённой пробе восстановления — это улика '
                                'ИСПОЛНЕНИЯ, а не только описания',
                                'data/restore_drill_status.json')]))

    off, state = _read_json(data / 'dr_offsite_status.json')
    sources.append(_source_record('data/dr_offsite_status.json',
                                  data / 'dr_offsite_status.json', state,
                                  observed_at=(off or {}).get('last_offsite_ts')
                                  if isinstance(off, dict) else None, now=now))
    if isinstance(off, dict):
        items.append(_item(
            'backup:offsite', 'backup', 'Резервная копия вынесена за пределы машины',
            status='ACTIVE', authority_source='NOT_AUTHORITY',
            recovery_status='UNKNOWN',
            recovery_evidence=[_evidence(
                'offsite',
                f"вынос {off.get('last_offsite_ts')}, сверен={off.get('verified')}, "
                f"хранится копий {off.get('n_offsite_kept')}, реально удалённое "
                f"хранилище={off.get('is_real_remote')}",
                'data/dr_offsite_status.json')],
            last_verified_at=off.get('last_offsite_ts'),
            evidence=[_evidence(
                'backup_is_not_restore',
                'НАЛИЧИЕ и сверка копии доказывают копию, а не восстановление: '
                'доказательство восстановления — отдельная проба',
                'data/dr_offsite_status.json')]))

    backups = data / 'backups'
    n = len(list(backups.iterdir())) if backups.is_dir() else 0
    if n:
        items.append(_item(
            'backup:local_archive', 'backup',
            f'Локальные резервные копии на диске ({n} файлов)', status='ACTIVE',
            authority_source='NOT_AUTHORITY', recovery_status='UNKNOWN',
            evidence=[_evidence(
                'presence',
                f'в data/backups найдено {n} файлов. Это улика НАЛИЧИЯ копий и ничего '
                'больше: успешность восстановления отсюда не следует', 'data/backups')]))

    for rel in RUNBOOKS:
        p = Path(production) / rel
        if not p.is_file():
            continue
        items.append(_item(
            f'recovery:{Path(rel).name}', 'recovery', Path(rel).name, status='DOCUMENTED',
            authority_source='AUTHORITY_UNDEFINED', owner='UNKNOWN',
            recovery_status='DOCUMENTED_UNTESTED',
            recovery_evidence=[_evidence(
                'document',
                'процедура ОПИСАНА в документе, доказательства исполнения НЕ найдено. '
                'Это не «неизвестно»: известно ровно то, что пробы нет', rel)],
            evidence=[_evidence('runbook', rel, 'docs')]))
    return items


def _deployment_items(production, sources, now):
    items = []
    data = Path(production) / 'data'
    acc, state = _read_json(data / 'deployment_acceptance.json')
    sources.append(_source_record('data/deployment_acceptance.json',
                                  data / 'deployment_acceptance.json', state,
                                  observed_at=(acc or {}).get('checked_at')
                                  if isinstance(acc, dict) else None, now=now))
    if isinstance(acc, dict):
        items.append(_item(
            'deployment:acceptance', 'deployment',
            'Приёмка развёртывания: способен ли флот стартовать',
            status=str(acc.get('status')), authority_source='NOT_AUTHORITY',
            recovery_status='NOT_APPLICABLE', last_verified_at=acc.get('checked_at'),
            evidence=[_evidence(
                'acceptance',
                f"status={acc.get('status')}, точек входа {acc.get('entrypoints_total')}, "
                f"сломанных {len(acc.get('entrypoints_broken') or [])}",
                'data/deployment_acceptance.json')]))

    sync, state = _read_json(data / 'code_sync_status.json')
    sources.append(_source_record('data/code_sync_status.json',
                                  data / 'code_sync_status.json', state,
                                  observed_at=(sync or {}).get('timestamp')
                                  if isinstance(sync, dict) else None, now=now))
    script = Path(production) / 'scripts/code_sync_from_origin.sh'
    sources.append(_source_record('scripts/code_sync_from_origin.sh', script,
                                  'READ' if script.is_file() else 'ABSENT', now=now))
    if isinstance(sync, dict):
        items.append(_item(
            'deployment:canonical_path', 'deployment',
            'Канонический путь доставки: origin/main → прод-дерево',
            status=str(sync.get('result')), authority_source='AUTHORITATIVE',
            owner='@yurii', permission_zone='AGENT_DECIDES',
            permission_class='AUTONOMOUS', approval_required='NOT_REQUIRED',
            recovery_status='UNKNOWN',
            last_verified_at=sync.get('timestamp'),
            evidence=[_evidence(
                'rule',
                'scripts/code_sync_from_origin.sh: «CODE ONLY, whole directories… NEVER '
                'data/ (live track), docs/, nimbalyst-local/, KANBAN.json»; ручное '
                'копирование файлов между деревьями запрещено правилом деплоя',
                'scripts/code_sync_from_origin.sh'),
                _evidence('observed',
                          f"последняя синхронизация {sync.get('timestamp')}: "
                          f"{sync.get('result')}, изменено {sync.get('files_changed')}",
                          'data/code_sync_status.json')]))
        retired = sync.get('retired_code') or []
        if retired:
            items.append(_item(
                'deployment:no_delete', 'deployment',
                'Checkout не удаляет: отставленный код остаётся в проде',
                status='CONDITION', authority_source='AUTHORITATIVE',
                recovery_status='NOT_APPLICABLE',
                last_verified_at=sync.get('timestamp'),
                evidence=[_evidence(
                    'rule_and_observation',
                    f'правило доставки прямо говорит «A checkout does not DELETE», и '
                    f'синхронизация называет {len(retired)} таких файлов в retired_code',
                    'scripts/code_sync_from_origin.sh')]))
    return items


def _security_items(production, sources, now):
    items = []
    data = Path(production) / 'data'
    alerts, state = _read_json(data / 'security_alerts.json')
    sources.append(_source_record('data/security_alerts.json',
                                  data / 'security_alerts.json', state, now=now))
    rows = alerts if isinstance(alerts, list) else (alerts or {}).get('alerts') or []
    items.append(_item(
        'security:alerts', 'security', f'Тревоги безопасности ({len(rows)})',
        status='ACTIVE' if rows else 'CLEAR', authority_source='NOT_AUTHORITY',
        security_status=('ALERTS_PRESENT' if rows else 'NO_ALERTS_RECORDED'),
        recovery_status='NOT_APPLICABLE',
        evidence=[_evidence(
            'alerts',
            f'в файле {len(rows)} запис(ей). Отсутствие записей не является '
            'доказательством отсутствия проблем — это отсутствие записей',
            'data/security_alerts.json')]))
    # инвариант о секретах — цитата, а не пересказ
    claude = Path(production) / 'CLAUDE.md'
    if claude.is_file() and 'Никаких секретов в файлах' in claude.read_text(
            encoding='utf-8', errors='replace'):
        items.append(_item(
            'security:no_secrets_in_files', 'security',
            'Никаких секретов в файлах — ключи только из Keychain',
            status='ACTIVE', authority_source='AUTHORITATIVE', owner='@yurii',
            permission_zone='UNKNOWN', permission_class='UNKNOWN',
            approval_required='UNKNOWN',
            security_status='RULE_DECLARED', recovery_status='NOT_APPLICABLE',
            evidence=[_evidence(
                'invariant',
                'CLAUDE.md, инвариант #7: «Никаких секретов в файлах — PAT/токены/ключи '
                'читать из Keychain в рантайме (инцидент 2026-06-10: PAT утёк в 90+ '
                'файлов)»', 'CLAUDE.md')]))
    kill, state = _read_json(data / 'kill_switch_status.json')
    sources.append(_source_record('data/kill_switch_status.json',
                                  data / 'kill_switch_status.json', state,
                                  observed_at=(kill or {}).get('generated_at')
                                  if isinstance(kill, dict) else None, now=now))
    if isinstance(kill, dict):
        items.append(_item(
            'permission:kill_switch', 'permission',
            'Стоп-кран: состояние и кто им управляет', status='ACTIVE',
            authority_source='AUTHORITATIVE', owner='@yurii',
            decision_ref='ADR-034/ADR-048', permission_zone='UNKNOWN',
            permission_class='EMERGENCY', approval_required='UNKNOWN',
            recovery_status='NOT_APPLICABLE',
            last_verified_at=kill.get('generated_at'),
            evidence=[_evidence(
                'state', f"triggered={kill.get('triggered')} ({kill.get('reason')})",
                'data/kill_switch_status.json'),
                _evidence('rule',
                          'CLAUDE.md: two-tier kill-switch SOFT −5% / HARD −10% — '
                          'срабатывает ПО ПРАВИЛУ, а не по чьему-то решению; изменение '
                          'порогов — только новым ADR. Прямого требования одобрения '
                          'владельца источник НЕ содержит, поэтому воротами одобрения '
                          'это правило не объявляем', 'CLAUDE.md')]))
    return items


LIMITS = (
    'Новый governance-движок не строится: слой читает существующие решения, правила и '
    'улики и ничего не меняет.',
    'НАЛИЧИЕ резервной копии не является доказательством восстановления. Доказательство — '
    'запись о проведённой пробе с результатом.',
    'ОПИСАННАЯ процедура отката не является проверенной. Документ и запись об исполнении — '
    'разные улики, и вторая из первой не выводится.',
    'Коллизии номеров ADR не разрешаются: правила, чей реестр сильнее, в репозитории нет, '
    'и победитель не выбирается.',
    'Зона разрешения ставится только там, где её объявляет правило; иначе UNKNOWN.',
    'Значения секретов не копируются никуда: цитируются только правила о них.',
    'Общего балла управления нет намеренно: пробел в резервах и пробел в разрешениях — '
    'разные вещи, и сумма их не описывает.',
)


def build_governance_snapshot(production, now=None):
    now = now or _now()
    production = Path(production)
    sources, items = [], []
    items += _adr_items(production, sources, now)
    items += _rule_items(production, sources, now)
    items += _invariant_items(production, sources, now)
    items += _recovery_items(production, sources, now)
    items += _deployment_items(production, sources, now)
    items += _security_items(production, sources, now)

    index = production / 'docs/decisions/INDEX.md'
    sources.append(_source_record('docs/decisions/INDEX.md', index,
                                  'READ' if index.is_file() else 'ABSENT', now=now))

    # пробелы: они ИЗМЕРЕНЫ, а не перечислены из головы
    gaps = []
    if not any(i['recovery_status'] == 'TESTED' for i in items):
        gaps.append(('recovery_untested',
                     'ни одна процедура восстановления не имеет записи об исполнении'))
    documented_only = [i for i in items
                       if i['recovery_status'] == 'DOCUMENTED_UNTESTED']
    if documented_only:
        gaps.append(('rollback_documented_not_tested',
                     f'процедур описано {len(documented_only)}, записи об исполнении нет '
                     'ни у одной из них'))
    collisions = [i for i in items if i['status'] == 'NUMBER_COLLISION']
    if collisions:
        gaps.append(('adr_number_collision',
                     f'номеров ADR, занятых в обоих реестрах: {len(collisions)}; '
                     'правила, чей реестр сильнее, нет'))
    unknown_owner = [i for i in items if i['owner'] == 'UNKNOWN']
    if unknown_owner:
        gaps.append(('owner_undefined',
                     f'записей без объявленного владельца: {len(unknown_owner)}'))
    # ПРОБЕЛ — только там, где зона ТРЕБУЕТСЯ объявленной областью правила. Запись вне
    # области (документ, наблюдение) пробелом не является: требовать у ADR зону значило бы
    # выдумать универсальное требование, которого правило не объявляло.
    required_missing = [i for i in items if i['zone_scope'] == 'ZONE_REQUIRED'
                        and i['permission_zone'] == 'UNKNOWN']
    if required_missing:
        gaps.append(('permission_zone_required_but_missing',
                     f'записей, которым зона ТРЕБУЕТСЯ правилом, но она не объявлена: '
                     f'{len(required_missing)}'))
    scope_unknown = [i for i in items if i['zone_scope'] == 'ZONE_SCOPE_UNKNOWN']
    if scope_unknown:
        gaps.append(('permission_zone_scope_unknown',
                     f'записей, чью область зонирования установить не удалось: '
                     f'{len(scope_unknown)}'))
    for key, detail in gaps:
        items.append(_item(
            f'gap:{key}', 'gap', detail, status='OPEN',
            authority_source='NOT_AUTHORITY', recovery_status='UNKNOWN',
            evidence=[_evidence('measured', detail, 'governance')]))

    by = lambda key: {k: sum(1 for i in items if i[key] == k)  # noqa: E731
                      for k in sorted({str(i[key]) for i in items})}
    counts = {
        'items': len(items),
        'by_category': by('category'),
        'by_recovery_status': by('recovery_status'),
        'by_permission_zone': by('permission_zone'),
        'by_authority_source': by('authority_source'),
        'decisions': sum(1 for i in items if i['category'] == 'decision'),
        'rules': sum(1 for i in items if i['category'] == 'rule'),
        'invariants': sum(1 for i in items if i['category'] == 'invariant'),
        'permissions': sum(1 for i in items if i['category'] == 'permission'),
        'by_permission_class': {k: sum(1 for i in items
                                       if i['category'] == 'permission'
                                       and i['permission_class'] == k)
                                for k in PERMISSION_CLASSES},
        'by_zone_scope': {k: sum(1 for i in items if i['zone_scope'] == k)
                          for k in ZONE_SCOPES},
        'owner_gated': sum(1 for i in items
                           if i['category'] == 'permission'
                           and i['permission_class'] == 'OWNER_GATED'),
        'autonomous_rules': sum(1 for i in items if i['category'] == 'permission'
                                and i['permission_class'] == 'AUTONOMOUS'),
        'emergency_rules': sum(1 for i in items if i['category'] == 'permission'
                               and i['permission_class'] == 'EMERGENCY'),
        # ворота одобрения — только там, где источник ПРЯМО требует решения владельца
        'approval_required': sum(1 for i in items
                                 if i['approval_required'] == 'REQUIRED'),
        'zone_required': sum(1 for i in items if i['zone_scope'] == 'ZONE_REQUIRED'),
        'zone_defined': sum(1 for i in items if i['zone_scope'] == 'ZONE_REQUIRED'
                            and i['permission_zone'] != 'UNKNOWN'),
        'zone_required_but_missing': sum(1 for i in items
                                         if i['zone_scope'] == 'ZONE_REQUIRED'
                                         and i['permission_zone'] == 'UNKNOWN'),
        'zone_not_applicable': sum(1 for i in items
                                   if i['zone_scope'] == 'ZONE_NOT_APPLICABLE'),
        'zone_scope_unknown': sum(1 for i in items
                                  if i['zone_scope'] == 'ZONE_SCOPE_UNKNOWN'),
        'recovery_tested': sum(1 for i in items if i['recovery_status'] == 'TESTED'),
        'recovery_documented_untested': sum(
            1 for i in items if i['recovery_status'] == 'DOCUMENTED_UNTESTED'),
        'recovery_missing': sum(1 for i in items
                                if i['recovery_status'] == 'MISSING'),
        'recovery_documented_total': sum(
            1 for i in items if i['recovery_status'] in ('TESTED',
                                                         'DOCUMENTED_UNTESTED')),
        'recovery_unknown': sum(1 for i in items
                                if i['recovery_status'] == 'UNKNOWN'),
        'recovery_not_applicable': sum(1 for i in items
                                       if i['recovery_status'] == 'NOT_APPLICABLE'),
        'backups_observed': sum(1 for i in items if i['category'] == 'backup'),
        'restore_proven': sum(1 for i in items
                              if i['category'] == 'recovery'
                              and i['recovery_status'] == 'TESTED'),
        'security_items': sum(1 for i in items if i['category'] == 'security'),
        'gaps': sum(1 for i in items if i['category'] == 'gap'),
        'adr_number_collisions': len(collisions),
        'sources_read': sum(1 for s in sources if s['status'] == 'READ'),
        'sources_unavailable': sum(1 for s in sources if s['status'] != 'READ'),
    }

    items.sort(key=lambda i: (i['category'], i['governance_id']))
    snapshot = {
        'schema_version': SCHEMA,
        'generated_at': now.isoformat(),
        'derived_state': True,
        'is_not_a_source_of_truth':
            'производный снимок управления: пересобирается из решений, правил и журналов '
            'и не является ни реестром решений, ни новым governance-движком',
        'builds_new_governance': False,
        'changes_permissions': False,
        'executes_recovery': False,
        'has_governance_score': False,
        'governance_score_note':
            'общего балла управления нет намеренно: пробел в резервах и пробел в '
            'разрешениях — разные вещи, и сумма их не описывает',
        'production': str(production),
        'category_vocabulary': list(CATEGORIES),
        'recovery_vocabulary': list(RECOVERY_STATES),
        'recovery_definitions': dict(RECOVERY_DEFINITIONS),
        'permission_vocabulary': list(PERMISSION_ZONES),
        'permission_definitions': dict(PERMISSION_DEFINITIONS),
        'permission_class_vocabulary': list(PERMISSION_CLASSES),
        'permission_class_definitions': dict(PERMISSION_CLASS_DEFINITIONS),
        'zone_scope_vocabulary': list(ZONE_SCOPES),
        'zone_scope_definitions': dict(ZONE_SCOPE_DEFINITIONS),
        'zone_scope_basis': ZONE_SCOPE_BASIS,
        'authority_vocabulary': list(AUTHORITY_STATES),
        'sources': sources,
        'counts': counts,
        'items': items,
        'limits': list(LIMITS),
    }
    snapshot['semantic_digest'] = semantic_digest(snapshot)
    return snapshot


def semantic_view(snapshot):
    view = {k: v for k, v in snapshot.items()
            if k not in ('generated_at', 'semantic_digest', 'sources')}
    view['sources'] = [{k: v for k, v in s.items() if k != 'age_hours'}
                       for s in snapshot.get('sources', [])]
    return view


def semantic_digest(snapshot):
    payload = json.dumps(semantic_view(snapshot), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]


def validate_governance_snapshot(snapshot, where):
    def need(cond, message):
        if not cond:
            raise GovernanceInputError(f'{where}: {message}')

    need(isinstance(snapshot, dict), 'снимок не является объектом')
    need(snapshot.get('schema_version') == SCHEMA,
         f"схема {snapshot.get('schema_version')!r}, ожидалась {SCHEMA!r}")
    for key in ('generated_at', 'sources', 'counts', 'items', 'limits',
                'recovery_definitions', 'permission_definitions',
                'permission_class_definitions', 'zone_scope_definitions',
                'zone_scope_basis'):
        need(key in snapshot, f'поле {key} отсутствует')
    for flag in ('builds_new_governance', 'changes_permissions', 'executes_recovery',
                 'has_governance_score'):
        need(snapshot.get(flag) is False, f'{flag} обязан быть False')
    seen = set()
    for i, it in enumerate(snapshot['items']):
        for key in ('governance_id', 'category', 'title', 'status', 'authority_source',
                    'owner', 'decision_ref', 'permission_zone', 'approval_required',
                    'recovery_status', 'recovery_evidence', 'security_status',
                    'last_verified_at', 'freshness', 'related_work', 'related_findings',
                    'evidence'):
            need(key in it, f'items[{i}] без поля {key}')
        need(it['governance_id'] not in seen, f"дубль id {it['governance_id']!r}")
        seen.add(it['governance_id'])
        need(it['category'] in CATEGORIES, f"items[{i}] категория вне словаря")
        need(it['recovery_status'] in RECOVERY_STATES,
             f"items[{i}] восстановление {it['recovery_status']!r} вне словаря")
        need(it['permission_zone'] in PERMISSION_ZONES,
             f"items[{i}] зона {it['permission_zone']!r} вне словаря")
        need(it['permission_class'] in PERMISSION_CLASSES,
             f"items[{i}] род правила {it['permission_class']!r} вне словаря")
        need(it['zone_scope'] in ZONE_SCOPES,
             f"items[{i}] область зонирования {it['zone_scope']!r} вне словаря")
        need(not (it['permission_class'] in ('AUTONOMOUS', 'EMERGENCY')
                  and it['approval_required'] == 'REQUIRED'),
             f'items[{i}] правило рода {it["permission_class"]} объявлено воротами '
             'одобрения владельца — источник этого не требует')
        need(not (it['approval_required'] == 'REQUIRED'
                  and it['permission_class'] != 'OWNER_GATED'),
             f'items[{i}] требует одобрения, не будучи предметом владельца')
        need(it['approval_required'] in APPROVAL_STATES,
             f"items[{i}] одобрение {it['approval_required']!r} вне словаря")
        need(it['authority_source'] in AUTHORITY_STATES,
             f"items[{i}] авторитет {it['authority_source']!r} вне словаря")
        need(bool(it['evidence']), f'items[{i}] без улики')
        need(not (it['recovery_status'] == 'TESTED' and not it['recovery_evidence']),
             f'items[{i}] объявлен проверенным без улики исполнения')
        need(not (it['category'] == 'backup' and it['recovery_status'] == 'TESTED'),
             f'items[{i}]: наличие копии выдано за доказательство восстановления')
    blob = json.dumps(snapshot, ensure_ascii=False)
    for shape in ('ghp_', 'github_pat_', 'AKIA'):
        need(shape not in blob, f'в снимок попала форма секрета ({shape})')
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--production', type=Path, default=Path.home() / 'Documents/SPA_Claude')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)

    final = Path(args.output)
    if final.exists():
        raise SystemExit(f'{final} уже существует; каждый прогон пишет новый каталог')
    try:
        snapshot = build_governance_snapshot(args.production)
        validate_governance_snapshot(snapshot, 'freshly built')
    except GovernanceInputError as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\nСнимок не построен. Это НЕ '
                         '«управление в порядке».')

    diff_mod.validate_output(final, [Path(args.production)])
    staging = final.with_name(final.name + '.incomplete')
    if staging.exists():
        raise SystemExit(f'{staging} остался от прерванного прогона; отодвиньте его')
    staging.mkdir(parents=True, mode=0o700)
    p = staging / 'governance_snapshot.json'
    with p.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(snapshot, indent=2, ensure_ascii=False,
                                allow_nan=False) + '\n')
    p.chmod(0o600)
    os.rename(staging, final)

    c = snapshot['counts']
    print(f"Источников прочитано: {c['sources_read']} · недоступно: "
          f"{c['sources_unavailable']}")
    print(f"Решений {c['decisions']} (коллизий номеров {c['adr_number_collisions']}) · "
          f"правил {c['rules']} · инвариантов {c['invariants']} · разрешений "
          f"{c['permissions']}")
    print(f"Правила разрешений: по роду {c['by_permission_class']} · ВОРОТ одобрения "
          f"владельца: {c['approval_required']}")
    print(f"Зонирование: требуется {c['zone_required']} · объявлено {c['zone_defined']} · "
          f"требуется и НЕ объявлено {c['zone_required_but_missing']} · не относится "
          f"{c['zone_not_applicable']} · область неизвестна {c['zone_scope_unknown']}")
    print(f"Восстановление: ПРОВЕРЕНО {c['recovery_tested']} · описано без пробы "
          f"{c['recovery_documented_untested']} · отсутствует {c['recovery_missing']} · "
          f"не измерено {c['recovery_unknown']} · не относится "
          f"{c['recovery_not_applicable']}")
    print(f"Резервные копии наблюдаются: {c['backups_observed']} · восстановление "
          f"доказано: {c['restore_proven']}")
    print(f"Безопасность: {c['security_items']} · пробелов управления: {c['gaps']}")
    print(f"Снимок → {final / 'governance_snapshot.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
