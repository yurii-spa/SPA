#!/usr/bin/env python3
"""Studio · Контракт вывода Архитектора. СНАЧАЛА контракт, потом исполнитель.

Почему не «сделать ИИ по имени Архитектор»
==========================================
Стадия «разбор архитектором» сегодня ``DOCUMENTED_ONLY``: слой описан документами, ролей
разбора не объявляет ни одна из 103 сущностей. Соблазн — посадить на эту стадию языковую
модель и объявить её живой. Замер уже показал, чем это кончается: совпадение по имени
объявило стадию живой, найдя сторожа соответствия. Живой её делает **проверяемый выход**,
а не наличие исполнителя.

Поэтому здесь нет исполнителя. Здесь есть контракт и **проверка** контракта: что
Архитектор обязан выдать, и как машина убеждается, что он не выдумал состояние системы.

Главная опасность — выдуманное состояние
========================================
Архитектурный разбор опасен не тем, что предложит плохое решение, а тем, что опишет
несуществующее НАСТОЯЩЕЕ: «модуль X уже делает Y», «тесты зелёные», «агент работает».
На таком основании любое решение верно и бесполезно.

Противоядие одно: **каждое утверждение о текущем состоянии обязано назвать улику,
которую можно проверить машинно** — путь к существующему файлу, поле существующего
артефакта, команду с воспроизводимым выводом. Утверждение без проверяемой улики не
делает документ плохим — оно делает его НЕПРИНЯТЫМ.

Границы Архитектора
===================
* читает: канонические источники, производные проекции, документы, историю git;
* пишет: **только свой документ предложения**. Ни кода, ни конфигурации, ни карточек,
  ни статусов;
* не решает: ничего из трёх предметов владельца (настоящие деньги; публичные числа,
  нейминг и юридические формулировки; необратимые действия);
* не исполняет: ни одной задачи. Выход Архитектора — вход для исполнителя, а не команда.

Чем Архитектор отличается от ARB
================================
Архитектор **предлагает** и обязан показать альтернативы. ARB **принимает или отвергает**
и обязан показать, по какому правилу. Их нельзя совмещать в одном проходе: тот, кто
предложил, не может быть тем, кто беспристрастно принял. Поэтому у ARB свой контракт
входа — предложение Архитектора — и свой словарь вердиктов.

Только stdlib. LLM здесь не вызывается: это контракт и его проверка.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'architect_output/1'

#: Обязательные разделы вывода. Отсутствие любого — отказ, а не замечание.
REQUIRED_SECTIONS = (
    'problem',                  # что именно не работает, без предложений
    'current_state_evidence',   # утверждения о НАСТОЯЩЕМ, каждое с проверяемой уликой
    'architecture',             # как устроено предлагаемое
    'alternatives',             # не менее двух, с причиной отклонения каждой
    'selected_recommendation',  # одна, названная
    'risks',                    # чем опасно предлагаемое
    'acceptance_criteria',      # как машина узнает, что построено
    'implementation_tasks',     # что именно делать
    'permission_zone',          # что исполнителю разрешено трогать
    'owner_decisions_required', # список или пустой список с обоснованием пустоты
    'implementation_package',   # вход для исполнителя
)

#: Что Архитектор НЕ ВПРАВЕ решать сам. Совпадает с тремя предметами границы.
OWNER_SUBJECTS = {
    '1': 'движение настоящих денег',
    '2': 'публичные числа доходности, нейминг тиров, юридические формулировки',
    '3': 'необратимые действия',
}

#: Виды улики текущего состояния, которые можно проверить машинно.
EVIDENCE_KINDS = ('FILE', 'FIELD', 'COMMAND', 'MEASUREMENT', 'ABSENCE')

#: Вердикты ARB. Это ДРУГОЙ словарь: предлагающий и принимающий не совпадают.
ARB_VERDICTS = ('ACCEPTED', 'REJECTED', 'NEEDS_EVIDENCE', 'OWNER_GATED')

#: Слова, выдающие утверждение о состоянии без улики. Не запрет на слово, а требование
#: приложить к нему улику: «уже работает» без пути к артефакту и есть выдуманное
#: состояние.
_STATE_CLAIM_MARKERS = (
    'уже работает', 'уже реализован', 'уже сделано', 'тесты зелёные', 'агент работает',
    'полностью покрыт', 'всё готово', 'работает корректно', 'is already', 'works fine',
)


class ContractError(Exception):
    """Отказ принять вывод Архитектора. Содержит названные причины."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__('вывод не принят: ' + '; '.join(self.reasons))


def _now():
    return datetime.now(timezone.utc)


def evidence_item(kind, *, claim, locator, value=None):
    """Одно проверяемое утверждение о настоящем.

    ``ABSENCE`` — полноправный вид улики: «такого файла нет» и «такого поля никто не
    объявляет» суть измерения, а не отговорки. Именно они чаще всего и оказываются
    главным содержанием разбора.
    """
    if kind not in EVIDENCE_KINDS:
        raise ValueError(f'вид улики {kind!r} вне словаря {EVIDENCE_KINDS}')
    if not claim or not locator:
        raise ValueError('улика обязана назвать и утверждение, и где его проверять')
    return {'kind': kind, 'claim': claim, 'locator': locator, 'value': value}


def verify_evidence(item, *, production_root, projection=None):
    """Машинная проверка ОДНОЙ улики. Возвращает вердикт, а не мнение."""
    kind, locator = item.get('kind'), str(item.get('locator') or '')
    root = Path(production_root)
    if kind == 'FILE':
        return ({'state': 'VERIFIED', 'note': 'файл существует'}
                if (root / locator).exists() else
                {'state': 'REFUTED', 'note': 'файла не существует'})
    if kind == 'ABSENCE':
        return ({'state': 'VERIFIED', 'note': 'названного действительно нет'}
                if not (root / locator).exists() else
                {'state': 'REFUTED', 'note': 'названное отсутствующим существует'})
    if kind == 'FIELD':
        path, _, field = locator.partition(':')
        target = root / path
        if not target.exists():
            return {'state': 'REFUTED', 'note': 'файла с полем не существует'}
        try:
            doc = json.loads(target.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {'state': 'NOT_MEASURED', 'note': 'файл не разобран'}
        node = doc
        for part in [p for p in field.split('.') if p]:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return {'state': 'REFUTED', 'note': f'поля {field} нет'}
        if item.get('value') is not None and node != item['value']:
            return {'state': 'REFUTED',
                    'note': f'поле есть, но значение {node!r}, а заявлено {item["value"]!r}'}
        return {'state': 'VERIFIED', 'note': 'поле есть и значение совпадает',
                'observed': node}
    if kind == 'MEASUREMENT':
        if projection is None:
            return {'state': 'NOT_MEASURED', 'note': 'проекция для сверки не подана'}
        facts = {f.get('metric'): f.get('value')
                 for f in (projection.get('facts') or ())}
        if locator not in facts:
            return {'state': 'REFUTED', 'note': f'кокпит не публикует величину {locator}'}
        if item.get('value') is not None and facts[locator] != item['value']:
            return {'state': 'REFUTED',
                    'note': f'кокпит даёт {facts[locator]!r}, заявлено {item["value"]!r}'}
        return {'state': 'VERIFIED', 'note': 'величина совпадает с проекцией',
                'observed': facts[locator]}
    if kind == 'COMMAND':
        # Команды здесь НЕ исполняются намеренно: проверка вывода Архитектора не имеет
        # права ничего запускать. Такая улика остаётся неподтверждённой до отдельного
        # прогона, и это честнее, чем поверить ей на слово.
        return {'state': 'NOT_MEASURED',
                'note': 'улика-команда не исполняется проверкой; требует отдельного прогона'}
    return {'state': 'NOT_MEASURED', 'note': 'вид улики не проверяется'}


def validate_output(doc, *, production_root, projection=None):
    """Проверка вывода Архитектора по контракту. Отказывает, а не чинит."""
    reasons, warnings = [], []
    if not isinstance(doc, dict):
        raise ContractError(['вывод обязан быть объектом'])

    for section in REQUIRED_SECTIONS:
        if section not in doc:
            reasons.append(f'нет обязательного раздела «{section}»')
        elif doc[section] in (None, '', [], {}) and section != 'owner_decisions_required':
            reasons.append(f'раздел «{section}» пуст')

    alts = doc.get('alternatives') or []
    if isinstance(alts, list) and len(alts) < 2:
        reasons.append('альтернатив меньше двух: «единственный возможный путь» — это '
                       'не разбор, а решение, принятое до разбора')
    for a in alts if isinstance(alts, list) else ():
        if isinstance(a, dict) and not a.get('rejected_because'):
            reasons.append(f'альтернатива {a.get("name") or a!r} отклонена без причины')

    # Владельческие предметы: пустой список ДОПУСТИМ, но обязан быть обоснован.
    owner = doc.get('owner_decisions_required')
    if owner is None:
        reasons.append('не сказано, требуются ли решения владельца')
    elif owner == [] and not doc.get('owner_decisions_none_basis'):
        reasons.append('список решений владельца пуст без обоснования: молчание тут '
                       'неотличимо от недосмотра')
    for d in owner if isinstance(owner, list) else ():
        subj = (d or {}).get('subject') if isinstance(d, dict) else None
        if subj not in OWNER_SUBJECTS:
            reasons.append(f'решение владельца без предмета границы: {d!r}')

    # Зона разрешений обязана быть ОГРАНИЧЕНА. «Всё» зоной не является.
    zone = doc.get('permission_zone') or {}
    if isinstance(zone, dict):
        paths = zone.get('may_write') or []
        if not paths:
            reasons.append('зона разрешений не называет ни одного пути записи')
        for p in paths:
            if str(p).strip() in ('.', '/', '*', '**'):
                reasons.append(f'зона разрешений «{p}» не является ограничением')
    else:
        reasons.append('зона разрешений обязана быть объектом с may_write')

    # ── Главная проверка: утверждения о настоящем против улик.
    evidence = doc.get('current_state_evidence') or []
    verified = []
    if not isinstance(evidence, list) or not evidence:
        reasons.append('раздел улик текущего состояния пуст: тогда разбор опирается '
                       'на пересказ, а не на замер')
    else:
        for item in evidence:
            if not isinstance(item, dict):
                reasons.append(f'улика не является объектом: {item!r}')
                continue
            result = verify_evidence(item, production_root=production_root,
                                     projection=projection)
            verified.append({**item, 'verification': result})
            if result['state'] == 'REFUTED':
                reasons.append(f'улика ОПРОВЕРГНУТА: «{item.get("claim")}» — '
                               f'{result["note"]}')

    # Утверждения о состоянии в прозе, не приложенные к улике.
    prose = ' '.join(str(doc.get(k) or '') for k in
                     ('problem', 'architecture', 'selected_recommendation')).lower()
    for marker in _STATE_CLAIM_MARKERS:
        if marker in prose:
            warnings.append(f'в прозе есть утверждение о состоянии «{marker}»: оно '
                            f'обязано быть вынесено в улику с проверяемым адресом')

    acceptance = doc.get('acceptance_criteria') or []
    for c in acceptance if isinstance(acceptance, list) else ():
        text = str((c or {}).get('check') if isinstance(c, dict) else c)
        if any(w in text.lower() for w in ('будет реализовано', 'планируется', 'должно работать')):
            reasons.append(f'критерий приёмки не проверяем: «{text[:60]}»')

    if reasons:
        raise ContractError(reasons)
    return {
        'schema': SCHEMA,
        'state': 'ACCEPTED_BY_CONTRACT',
        'validated_at': _now().isoformat(),
        'evidence_verified': verified,
        'evidence_counts': {
            state: sum(1 for v in verified if v['verification']['state'] == state)
            for state in ('VERIFIED', 'REFUTED', 'NOT_MEASURED')},
        'warnings': warnings,
        'contract_note': ('принят КОНТРАКТОМ, а не ARB: контракт отвечает на вопрос '
                          '«разбор оформлен и его улики не опровергнуты», а не на вопрос '
                          '«решение верное». Второй вопрос — предмет ARB'),
    }


def arb_input(validated, *, proposal):
    """Что ARB получает на вход. Разделение ролей — часть контракта, а не вежливость."""
    return {
        'schema': 'arb_input/1',
        'proposal': proposal,
        'contract_validation': validated,
        'verdict_vocabulary': list(ARB_VERDICTS),
        'separation_note': ('предложивший не может быть принимающим: Архитектор обязан '
                            'показать альтернативы, ARB обязан назвать правило, по '
                            'которому принял или отверг'),
    }
