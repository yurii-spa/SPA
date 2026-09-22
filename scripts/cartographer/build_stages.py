#!/usr/bin/env python3
"""Director OS v1.3 · Стадии конвейера разработки — ВЫВЕДЕННЫЕ, а не проставленные.

Что меняется
============
v1.2 получала девять стадий ПАРАМЕТРОМ: пять LIVE, три PARTIAL, одна DOCUMENTED_ONLY.
Это было моё суждение, поданное в отрисовку, и экран не отличал его от замера. Здесь
каждая стадия обязана назвать свой носитель улики и правило, по которому улика читается.

Правило живости: улика ДОЛЖНА БЫТЬ СВЕЖЕЙ
========================================
«Стадия работает» и «стадия когда-то сработала» — разные утверждения. Мост исполнял
задачи, и это доказано; последняя доказанная доставка датируется августом. Поэтому
``LIVE`` требует улики не старше объявленного окна, а всё, что старше, честно
становится ``PARTIAL``: механизм есть, движения сейчас нет.

Отдельно про «Архитектор»
=========================
Существование архитектурных документов и переписок НЕ делает стадию живой. Носитель
улики для неё — работающий компонент со своим артефактом и расписанием. Нет артефакта —
``DOCUMENTED_ONLY``, сколько бы документов ни лежало рядом.

Только stdlib. Ничего не исполняет и не меняет.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from . import owner_facts as F
except ImportError:
    import owner_facts as F

DOMAIN = 'BUILD'

STATUSES = ('LIVE', 'PARTIAL', 'DOCUMENTED_ONLY', 'NOT_FOUND', 'UNKNOWN')
HANDOFF = ('YES', 'NO', 'UNKNOWN')

#: Окно живости. Объявлено здесь и названо вслух: без объявленного окна «живой»
#: означает «когда-нибудь случалось», и тогда стадия не перестаёт быть живой никогда.
LIVE_WINDOW_DAYS = 14

#: Роли, которые ЗАСЧИТЫВАЮТСЯ как разбор архитектуры. Список объявлен здесь, потому
#: что в манифесте такой роли нет ни у одной сущности: пустое пересечение — это замер,
#: а не недосмотр, и он обязан быть виден.
ARCHITECT_ROLES = frozenset({'architecture_review', 'architect', 'design_review'})

STAGES = (
    'OWNER_INPUT', 'INTAKE', 'CLASSIFICATION', 'ARCHITECT_REVIEW', 'APPROVED_WORK',
    'CLAUDE_EXECUTION', 'IMPLEMENTATION_EVIDENCE', 'ARB_REVIEW', 'CANONICAL_DELIVERY',
)

STAGE_TITLES = {
    'OWNER_INPUT': 'Владелец ставит задачу',
    'INTAKE': 'Приём входящего',
    'CLASSIFICATION': 'Разбор по предмету',
    'ARCHITECT_REVIEW': 'Разбор архитектором',
    'APPROVED_WORK': 'Работа с объявленной приёмкой',
    'CLAUDE_EXECUTION': 'Исполнение',
    'IMPLEMENTATION_EVIDENCE': 'Улика исполнения',
    'ARB_REVIEW': 'Ревью',
    'CANONICAL_DELIVERY': 'Каноническая доставка',
}

_FM = re.compile(r'^---\n(.*?)\n---', re.S)
_DATE = re.compile(r'\d{4}-\d{2}-\d{2}')


def _now():
    return datetime.now(timezone.utc)


def read_cards(tracker_dir):
    """Карточки как улики. Разбор намеренно грубый: нам нужны поля, а не содержимое."""
    root = Path(tracker_dir)
    if not root.is_dir():
        return None
    cards = []
    for path in sorted(root.glob('*.md')):
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        m = _FM.match(text)
        if not m:
            continue
        fields, trail = {}, []
        in_trail = False
        for line in m.group(1).splitlines():
            if line.startswith('  - ') and in_trail:
                trail.append(line[4:].strip().strip('"'))
                continue
            if not line.startswith(' ') and ':' in line:
                key, _, val = line.partition(':')
                key = key.strip()
                in_trail = (key == 'status_trail')
                fields[key] = val.strip().strip('"')
        cards.append({'name': path.stem, 'fields': fields, 'trail': trail,
                      'family': path.stem.split('-')[0]})
    return cards


def _latest_date(values):
    best = None
    for v in values:
        for hit in _DATE.findall(str(v or '')):
            try:
                d = datetime.fromisoformat(hit).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if best is None or d > best:
                best = d
    return best


def _verdict(*, carrier_exists, evidence_count, latest, now, doc_only=False,
             partial_reason=None):
    """Один судья на все стадии: наличие носителя, число улик и их свежесть."""
    if not carrier_exists:
        return 'NOT_FOUND', 'носителя улики для этой стадии не существует', None
    if doc_only:
        return 'DOCUMENTED_ONLY', ('объявление есть, работающего компонента с артефактом '
                                   'и расписанием нет'), None
    if evidence_count == 0:
        return 'NOT_FOUND', 'носитель есть, улик в нём нет', None
    if latest is None:
        return 'UNKNOWN', 'улики есть, но их время не объявлено — свежесть не измерена', None
    age_days = round((now - latest).total_seconds() / 86400.0, 2)
    if partial_reason:
        return 'PARTIAL', partial_reason, age_days
    if age_days <= LIVE_WINDOW_DAYS:
        return 'LIVE', f'улика свежее {LIVE_WINDOW_DAYS} дн.', age_days
    return 'PARTIAL', (f'механизм доказан, но последняя улика старше {LIVE_WINDOW_DAYS} дн. '
                       f'({age_days} дн.) — сейчас движения нет'), age_days


#: Документы, ОБЪЯВЛЯЮЩИЕ слой разбора. Их наличие даёт стадии DOCUMENTED_ONLY —
#: и ровно этого достаточно, чтобы отличить «спроектировано» от «работает».
ARCHITECT_DOCS = ('docs/10_agent_architecture.md', 'docs/ADR_004_two_layer_agents.md',
                  'docs/08_ai_investment_os_architecture.md')


def build_pipeline(*, cards, bridge, service_health=None, now=None,
                   architect_labels=('architect', 'cio'), production_root=None):
    """Девять стадий, каждая со своим носителем улики."""
    now = now or _now()
    # `None` от читателя означает «каталог карточек не прочитан», а пустой список —
    # «прочитан и пуст». Слив их в `[]`, четыре стадии получили бы вердикт
    # «носитель есть, улик в нём нет» — приговор вместо честного «не измерено».
    cards_unread = cards is None
    bridge_unread = bridge is None
    cards = cards or []
    bridge = bridge or {}
    out = []

    def add(key, *, carrier, count, latest, doc_only=False, partial_reason=None,
            detail=None, rule=None, unread=False):
        if unread:
            out.append({'stage': key, 'title': STAGE_TITLES[key], 'status': 'UNKNOWN',
                        'evidence_carrier': carrier, 'evidence_count': None,
                        'latest_evidence_age_days': None,
                        'verdict_reason': 'носитель улик не прочитан — не измерено',
                        'acceptance_rule': rule, 'detail': detail or {},
                        'can_hand_off': 'UNKNOWN'})
            return
        status, why, age = _verdict(carrier_exists=carrier is not None, evidence_count=count,
                                    latest=latest, now=now, doc_only=doc_only,
                                    partial_reason=partial_reason)
        out.append({'stage': key, 'title': STAGE_TITLES[key], 'status': status,
                    'evidence_carrier': carrier, 'evidence_count': count,
                    'latest_evidence_age_days': age, 'verdict_reason': why,
                    'acceptance_rule': rule, 'detail': detail or {}})

    # 1. Владелец ставит задачу — канал приёма объявлен САМОЙ карточкой (поле source).
    sourced = [c for c in cards if c['fields'].get('source')]
    channels = {}
    for c in sourced:
        channels[c['fields']['source']] = channels.get(c['fields']['source'], 0) + 1
    add('OWNER_INPUT', unread=cards_unread, carrier='nimbalyst-local/tracker/*.md:source',
        count=len(sourced), latest=_latest_date(c['fields'].get('created') for c in sourced),
        detail={'channels': channels},
        rule='LIVE, если существуют карточки с объявленным каналом происхождения и '
             'свежая дата создания')

    # 2. Приём — есть ли ДВИЖЕНИЕ статуса, а не просто лежащие карточки.
    moved = [c for c in cards if c['trail']]
    add('INTAKE', unread=cards_unread, carrier='nimbalyst-local/tracker/*.md:status_trail',
        count=len(moved), latest=_latest_date(t for c in moved for t in c['trail']),
        detail={'cards_with_trail': len(moved), 'cards_total': len(cards),
                'still_new': sum(1 for c in cards if c['fields'].get('status') == 'new')},
        rule='LIVE, если статусы карточек действительно переводились недавно; лежащая '
             'карточка приёмом не является')

    # 3. Разбор по предмету — объявленный предмет у карточки.
    classified = [c for c in cards if c['fields'].get('domain')]
    share = round(len(classified) / len(cards) * 100.0, 1) if cards else None
    add('CLASSIFICATION', unread=cards_unread, carrier='nimbalyst-local/tracker/*.md:domain',
        count=len(classified), latest=_latest_date(c['fields'].get('created') for c in classified),
        partial_reason=(f'предмет объявлен лишь у {len(classified)} карточек из '
                        f'{len(cards)} ({share} %): классификатор покрывает меньшинство'
                        if classified and share is not None and share < 50 else None),
        detail={'classified': len(classified), 'total': len(cards), 'share_pct': share},
        rule='LIVE, если предмет объявлен у большинства карточек')

    # 4. Архитектор — ТОЛЬКО работающий компонент с артефактом. Документы не считаются.
    # ── Носитель улики для «Архитектора» обязан быть ОБЪЯВЛЕН, а не угадан по имени.
    #    Первая редакция искала подстроку в ярлыке и объявила стадию живой, найдя
    #    `architecture_conformance` — сторожа соответствия, а не разбор предложенного
    #    решения. Классификация по имени ошибается в обе стороны, и здесь она ошиблась
    #    в дорогую: стадия, которая на самом деле и есть разрыв автономии, показалась
    #    работающей. Поэтому совпадение по имени уликой НЕ признаётся, а кандидат,
    #    которого оно нашло, записывается отдельно — как рассмотренный и отклонённый.
    declared_architect, near_miss = [], []
    for ent in (service_health or {}).get('entities') or ():
        role = str(ent.get('role_declared') or '').lower()
        label = str(ent.get('label') or '').lower()
        if role in ARCHITECT_ROLES:
            declared_architect.append({'label': ent['label'], 'role_declared': role,
                                       'producing': (ent.get('stages') or {}).get('PRODUCING_OUTPUT')})
        elif any(a in label for a in architect_labels):
            near_miss.append({'label': ent['label'], 'role_declared': ent.get('role_declared'),
                              'rejected_because': 'совпадение по имени уликой не является'})
    freshest_age = None
    for ent in (service_health or {}).get('entities') or ():
        if ent.get('label') not in {d['label'] for d in declared_architect}:
            continue
        for out_row in ent.get('declared_outputs') or ():
            age = out_row.get('age_hours')
            if age is not None and (freshest_age is None or age < freshest_age):
                freshest_age = age
    architect_latest = (now - timedelta(hours=freshest_age)) if freshest_age is not None else None
    docs_present = [d for d in ARCHITECT_DOCS
                    if production_root and (Path(production_root) / d).is_file()]
    add('ARCHITECT_REVIEW',
        carrier=('architecture/manifest.json:agents[].role ∈ объявленные роли разбора'
                 if declared_architect else
                 ('документы проекта: ' + ', '.join(docs_present) if docs_present else None)),
        count=len(declared_architect), latest=architect_latest,
        doc_only=not declared_architect,
        detail={'declared_components': declared_architect,
                'rejected_name_matches': near_miss,
                'freshest_output_age_hours': freshest_age,
                'documents_declaring_the_layer': docs_present,
                'note': 'ни один источник не объявляет компонент разбора архитектуры '
                        'ролью; наличие архитектурных документов и переписок стадию '
                        'живой НЕ делает'},
        rule='LIVE только при компоненте с ОБЪЯВЛЕННОЙ ролью разбора и свежим '
             'артефактом; совпадение по имени ярлыка уликой не является')

    # 5. Работа с объявленной приёмкой — машинный критерий ДО начала работы.
    probed = [c for c in cards if c['fields'].get('acceptance_probe')]
    in_work = [c for c in cards if c['fields'].get('status') == 'in-progress']
    probed_in_work = [c for c in in_work if c['fields'].get('acceptance_probe')]
    add('APPROVED_WORK', unread=cards_unread, carrier='nimbalyst-local/tracker/*.md:acceptance_probe',
        count=len(probed), latest=_latest_date(c['fields'].get('created') for c in probed),
        partial_reason=(f'в работе {len(in_work)} карточек, объявленная проба есть у '
                        f'{len(probed_in_work)}' if in_work and
                        len(probed_in_work) < len(in_work) else None),
        detail={'with_probe': len(probed), 'in_progress': len(in_work),
                'in_progress_with_probe': len(probed_in_work)},
        rule='LIVE, если у взятых в работу карточек объявлен машинный критерий приёмки')

    # 6–9. Стадии моста. Числа приходят из проекции улик, а не из параметра.
    tasks = bridge.get('tasks') or []

    def bridge_latest(pred):
        best = None
        for t in tasks:
            if not pred(t):
                continue
            ts = t.get('created_at')
            try:
                d = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            except (TypeError, ValueError):
                continue
            if best is None or d > best:
                best = d
        return best

    def done(t, phase):
        return (t.get('turns_by_kind') or {}).get(phase, {}).get('done', 0) > 0

    add('CLAUDE_EXECUTION', unread=bridge_unread, carrier='bridge.db:turns(phase=implement,status=done)',
        count=sum(1 for t in tasks if done(t, 'implement')),
        latest=bridge_latest(lambda t: done(t, 'implement')),
        rule='LIVE, если улика исполнения существует и свежа')

    add('IMPLEMENTATION_EVIDENCE',
        carrier='artifacts/<run_id>/apply/manifest.json',
        count=sum(1 for t in tasks if t.get('apply_manifests')),
        latest=bridge_latest(lambda t: t.get('apply_manifests')),
        detail={'artifacts_table_rows': bridge.get('artifacts_table_rows'),
                'note': 'контракт улик в базе НЕ заполняется: таблица artifacts пуста, '
                        'а доказательство лежит в каталоге прогона'},
        rule='LIVE, если существует манифест применения с отпечатком диффа')

    add('ARB_REVIEW', unread=bridge_unread, carrier='bridge.db:turns(phase=review,status=done)',
        count=sum(1 for t in tasks if done(t, 'review')),
        latest=bridge_latest(lambda t: done(t, 'review')),
        rule='LIVE, если ревью действительно исполнялось')

    delivered = [t for t in tasks if t.get('furthest_proven_stage') == 'CANONICAL_DELIVERY']
    add('CANONICAL_DELIVERY', unread=bridge_unread, carrier='apply/manifest.json:apply_commit + git cat-file',
        count=len(delivered), latest=bridge_latest(
            lambda t: t.get('furthest_proven_stage') == 'CANONICAL_DELIVERY'),
        detail={'verified_commits': bridge.get('commits_verified_count'),
                'not_found_commits': len(bridge.get('commits_not_found') or ()),
                'delivered_with_failing_tests':
                    len(bridge.get('delivered_with_failing_tests') or ())},
        rule='LIVE только если коммит задачи ПОДТВЕРЖДЁН в каноническом репозитории '
             'чтением git; заявленный в манифесте и не найденный коммит не считается')

    # ── Передача дальше. Разрыв — там, где первая стадия перестаёт быть живой.
    for i, stage in enumerate(out):
        nxt = out[i + 1] if i + 1 < len(out) else None
        if nxt is None:
            stage['can_hand_off'] = 'YES' if stage['status'] == 'LIVE' else (
                'UNKNOWN' if stage['status'] == 'UNKNOWN' else 'NO')
            stage['hand_off_to'] = None
            continue
        stage['hand_off_to'] = nxt['stage']
        if stage['status'] == 'LIVE' and nxt['status'] == 'LIVE':
            stage['can_hand_off'] = 'YES'
        elif 'UNKNOWN' in (stage['status'], nxt['status']):
            stage['can_hand_off'] = 'UNKNOWN'
        else:
            stage['can_hand_off'] = 'NO'

    break_at = next((s for s in out if s['can_hand_off'] != 'YES'), None)
    # Причина разрыва — состояние СЛЕДУЮЩЕЙ стадии, а не текущей. Первая редакция
    # печатала «улика свежее 14 дн.» под заголовком «автономия останавливается здесь»:
    # верную фразу о живой стадии в роли объяснения того, почему дальше не идёт.
    blocker = next((s for s in out if break_at and s['stage'] == break_at['hand_off_to']), None)
    return {
        'schema': 'build_stages/1',
        'state': 'READ',
        'measured_at': now.isoformat(),
        'live_window_days': LIVE_WINDOW_DAYS,
        'stages': out,
        'counts': {st: sum(1 for s in out if s['status'] == st) for st in STATUSES},
        'autonomy_breaks_at': (None if break_at is None else {
            'stage': break_at['stage'], 'title': break_at['title'],
            'status': break_at['status'],
            'hand_off_to': break_at['hand_off_to'],
            'can_hand_off': break_at['can_hand_off'],
            'evidence_carrier': break_at['evidence_carrier'],
            'blocked_by_stage': (blocker or {}).get('stage'),
            'blocked_by_status': (blocker or {}).get('status'),
            'reason': ((blocker or {}).get('verdict_reason')
                       if blocker else break_at['verdict_reason']),
            'reason_belongs_to': ((blocker or {}).get('stage')
                                  if blocker else break_at['stage'])}),
        'derivation_note':
            'ни одна стадия не проставлена вручную: у каждой назван носитель улики и '
            'правило её чтения, и вердикт пересчитывается из улик при каждой сборке',
    }
