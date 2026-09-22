#!/usr/bin/env python3
"""Director OS v1.3 · Очередь решений владельца — ПРОИЗВОДНАЯ проекция.

Вопрос, на который она отвечает
===============================
«Что сегодня ждёт именно моего решения?»

Чем она НЕ является
===================
Это не ещё один движок процессов и не новое хранилище. Ничего не создаётся, ничего не
переводится из статуса в статус. Существующие очереди читаются и складываются в один
ответ — при условии, что складывать их вообще можно.

Про склейку
===========
Записи объединяются ТОЛЬКО по доказанному совпадению идентификатора. Замер показал, что
доказывать нечего: ни один идентификатор задачи моста не встречается в карточках, ни
один слаг карточки — в базе моста. Похожие заголовки совпадением не считаются никогда,
поэтому «всего решений» здесь — сумма по источникам, а не по склеенным сущностям, и это
сказано вслух.

Про границу трёх предметов (ADR-285)
====================================
За владельцем остаются ровно три предмета: движение настоящих денег; публичные числа,
нейминг и юридические формулировки; необратимые действия. Ждущий элемент, не попадающий
ни в один из трёх, — **дефект очереди**, а не ожидание ответа: разбирать его обязан
агент. Проекция считает такие элементы отдельно, потому что очередь, которая копит
чужую работу, выглядит как занятость владельца.

Про срочность
=============
Ни один источник не объявляет срочность. Поэтому её здесь нет — ни поля, ни цвета, ни
порядка «по важности». Порядок — по возрасту, и это единственное, что измерено.
Только stdlib.
"""
from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import owner_facts as F
    from . import bridge_evidence as BE
except ImportError:
    import owner_facts as F
    import bridge_evidence as BE

DOMAIN = 'STUDIO'

#: Три предмета границы. Четвёртого нет; всё остальное решает агент.
SUBJECTS = {
    '1': 'движение настоящих денег',
    '2': 'публичные числа доходности, нейминг тиров, юридические формулировки',
    '3': 'необратимые действия',
    'NONE': 'ни один из трёх предметов — это дефект очереди, а не решение владельца',
}

_FM = re.compile(r'^---\n(.*?)\n---', re.S)
_DATE = re.compile(r'(\d{4}-\d{2}-\d{2})')

#: Слова-приметы предмета. Это ЭВРИСТИКА, и каждый элемент несёт признак того,
#: что предмет присвоен эвристикой, а не объявлен источником.
SUBJECT_HINTS = (
    ('1', ('custody', 'кастоди', 'live_trading', 'live trading', 'go-live', 'go_live',
           'real capital', 'реальны', 'настоящие деньги', 'ключи', 'keys', 'signer',
           'multisig', 'gnosis safe', 'платёж', 'payment', 'вывод средств')),
    ('2', ('legal', 'юридич', 'counsel', 'disclosure', 'no-guarantee', 'нейминг',
           'naming', 'доходност', 'публичн', 'disclaimer', 'tier', 'тир')),
    ('3', ('публикац', 'удал', 'канал', 'channel', 'необратим', 'аудит', 'audit',
           'внешн', 'external')),
)


def _now():
    return datetime.now(timezone.utc)


def _age_days(value, *, now):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return round((now - datetime.fromtimestamp(float(value), tz=timezone.utc))
                         .total_seconds() / 86400.0, 2)
        except (OSError, ValueError, OverflowError):
            return None
    hit = _DATE.search(str(value))
    if not hit:
        return None
    try:
        d = datetime.fromisoformat(hit.group(1)).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return round((now - d).total_seconds() / 86400.0, 2)


#: КЛАСС ЭЛЕМЕНТА ОЧЕРЕДИ. Четыре исхода, и три из них — не работа владельца.
#: Замер: из восьми ждущих элементов два не принадлежат ни одному из трёх предметов
#: границы, а один живёт в снимке 93-дневной давности. Показывать всё это одним списком
#: «ждёт вашего решения» значит занимать владельца чужой работой и просроченными
#: вопросами.
CLASS_OWNER = 'OWNER_DECISION_REQUIRED'
CLASS_SYSTEM = 'SYSTEM_SHOULD_RESOLVE'
CLASS_STALE = 'STALE'
CLASS_UNKNOWN = 'UNKNOWN'
ITEM_CLASSES = (CLASS_OWNER, CLASS_SYSTEM, CLASS_STALE, CLASS_UNKNOWN)

#: Порог устаревания. Объявлен здесь и назван вслух: без объявленного срока «просрочено»
#: было бы мнением. Элемент старше порога НЕ снимается и НЕ закрывается — он лишь
#: перестаёт стоять первым, потому что его предпосылку надо перемерить, а не отвечать
#: на него как на свежий вопрос.
STALE_AFTER_DAYS = 60.0


def classify_item(item, *, stale_after_days=STALE_AFTER_DAYS):
    """Класс элемента и ОСНОВАНИЕ класса.

    Порядок проверок намеренный. Принадлежность предмету решается раньше возраста:
    вопрос про настоящие деньги не перестаёт быть вопросом владельца от того, что он
    давно ждёт, — но его предпосылку надо перемерить, и это говорится отдельно.
    """
    subject = item.get('subject')
    age = item.get('age_days')
    if subject == 'NONE':
        return CLASS_SYSTEM, ('ни один из трёх предметов границы: это работа агента, '
                              'а не решение владельца')
    if subject not in ('1', '2', '3'):
        return CLASS_UNKNOWN, 'предмет определить не удалось'
    if age is not None and age > stale_after_days:
        return CLASS_STALE, (f'предмет владельца, но элемент ждёт {int(round(age))} дн. '
                             f'при пороге {int(stale_after_days)}: предпосылку надо '
                             f'перемерить прежде, чем отвечать')
    return CLASS_OWNER, 'предмет границы, наблюдение не просрочено'


def _subject_of(text):
    """Предмет по приметам. Возвращает и предмет, и ОСНОВАНИЕ его присвоения."""
    low = str(text or '').lower()
    for subject, words in SUBJECT_HINTS:
        for w in words:
            if w in low:
                return subject, 'HEURISTIC', f'в тексте встречается «{w}»'
    return 'NONE', 'HEURISTIC', 'ни одна примета трёх предметов не найдена'


# ── Источники ────────────────────────────────────────────────────────────────

def from_bridge_gates(db_path, *, now):
    """Гейты моста. ``open`` — ждёт; всё прочее — решено."""
    work = tempfile.mkdtemp(prefix='owner-gates-')
    copy = BE.snapshot_database(db_path, work)
    if copy is None:
        return {'source': 'bridge.db:gates', 'state': 'NOT_MEASURED',
                'reason': 'база моста не найдена'}
    conn = sqlite3.connect(f'file:{copy}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        if 'gates' not in names:
            return {'source': 'bridge.db:gates', 'state': 'NOT_MEASURED',
                    'reason': 'таблицы gates нет'}
        rows = [dict(r) for r in conn.execute('SELECT * FROM gates')]
    finally:
        conn.close()
    vocab = sorted({str(r.get('status') or 'UNKNOWN') for r in rows})
    waiting = [r for r in rows if str(r.get('status') or '') == 'open']
    items = []
    for r in waiting:
        subject, basis, why = _subject_of(r.get('reason'))
        items.append({
            'source': 'bridge.db:gates', 'ref': str(r.get('gate_id')),
            'title_ru': str(r.get('reason') or 'причина не объявлена'),
            'age_days': _age_days(r.get('created_at'), now=now),
            'severity': r.get('effective_risk'),
            'severity_declared': r.get('effective_risk') is not None,
            'subject': subject, 'subject_basis': basis, 'subject_why': why,
        })
    return {'source': 'bridge.db:gates', 'state': 'READ',
            'waiting_field': 'status', 'vocabulary': vocab,
            'total_rows': len(rows), 'waiting_count': len(waiting),
            'declares_severity': True, 'severity_field': 'effective_risk',
            'items': items}


def from_tracker(tracker_dir, *, now, families=('own', 'owner'),
                 waiting_statuses=('needs-owner',)):
    """Карточки владельца. Статусы берутся ИЗ карточек, а не из головы."""
    root = Path(tracker_dir)
    if not root.is_dir():
        return {'source': 'tracker', 'state': 'NOT_MEASURED',
                'reason': 'каталога карточек нет'}
    rows, vocab = [], set()
    for path in sorted(root.glob('*.md')):
        family = path.stem.split('-')[0]
        if family not in families:
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        m = _FM.match(text)
        if not m:
            continue
        fields = {}
        for line in m.group(1).splitlines():
            if not line.startswith(' ') and ':' in line:
                k, _, v = line.partition(':')
                fields[k.strip()] = v.strip().strip('"')
        vocab.add(fields.get('status') or 'UNKNOWN')
        rows.append((path.stem, fields))
    waiting = [(n, f) for n, f in rows if f.get('status') in waiting_statuses]
    items = []
    for name, f in waiting:
        subject, basis, why = _subject_of(f.get('title') or name)
        items.append({
            'source': f'tracker:{"/".join(families)}-*', 'ref': name,
            'title_ru': f.get('title') or name,
            'age_days': _age_days(f.get('created'), now=now),
            'severity': f.get('priority'),
            'severity_declared': bool(f.get('priority')),
            'subject': subject, 'subject_basis': basis, 'subject_why': why,
        })
    return {'source': f'tracker:{"/".join(families)}-*', 'state': 'READ',
            'waiting_field': 'status', 'vocabulary': sorted(vocab),
            'total_rows': len(rows), 'waiting_count': len(waiting),
            'declares_severity': any(f.get('priority') for _, f in waiting),
            'severity_field': 'priority', 'items': items}


def from_json_flag(path, *, now, source_name, waiting_field, is_waiting, describe,
                   list_key=None, ref_key=None, age_key=None, severity_key=None,
                   subject=None, subject_basis_note=None):
    """Общий читатель файла-флага. Правило ожидания подаётся вызовом, не угадывается.

    ``subject`` подаётся, когда предмет следует из САМОЙ ПРИРОДЫ источника, а не из слов
    в заголовке: файл-гейт перехода на живую торговлю относится к движению настоящих
    денег независимо от того, какими словами описана строка. Такое основание сильнее
    приметы и помечается отдельно — ``DECLARED_BY_SOURCE_NATURE``.
    """
    p = Path(path)
    if not p.is_file():
        return {'source': source_name, 'state': 'NOT_MEASURED',
                'reason': f'файла нет: {p.name}'}
    try:
        doc = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return {'source': source_name, 'state': 'NOT_MEASURED',
                'reason': f'файл не прочитан: {exc.__class__.__name__}'}
    records = doc.get(list_key) if list_key else [doc]
    if not isinstance(records, list):
        records = [records]
    items, vocab, waiting = [], set(), 0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        vocab.add(str(rec.get(waiting_field, 'UNKNOWN')))
        if not is_waiting(rec):
            continue
        waiting += 1
        title = describe(rec)
        if subject:
            subj, basis, why = subject, 'DECLARED_BY_SOURCE_NATURE', (
                subject_basis_note or 'предмет следует из природы источника')
        else:
            subj, basis, why = _subject_of(title)
        items.append({
            'source': source_name,
            'ref': str(rec.get(ref_key) if ref_key else p.name),
            'title_ru': title,
            'age_days': _age_days(rec.get(age_key) if age_key else None, now=now),
            'age_declared': bool(age_key and rec.get(age_key)),
            'severity': rec.get(severity_key) if severity_key else None,
            'severity_declared': bool(severity_key and rec.get(severity_key)),
            'subject': subj, 'subject_basis': basis, 'subject_why': why,
        })
    return {'source': source_name, 'state': 'READ', 'waiting_field': waiting_field,
            'vocabulary': sorted(vocab), 'total_rows': len(records),
            'waiting_count': waiting,
            'declares_severity': any(i['severity'] is not None for i in items),
            'items': items}


def _walk_records(node):
    """Все словари документа, на любой глубине. Ждущая запись не обязана лежать
    в том списке, где её ожидает автор читателя."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_records(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_records(value)


def from_kanban(path, *, now, waiting_value='blocked_user_action'):
    p = Path(path)
    if not p.is_file():
        return {'source': 'KANBAN.json', 'state': 'NOT_MEASURED', 'reason': 'файла нет'}
    try:
        doc = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'source': 'KANBAN.json', 'state': 'NOT_MEASURED',
                'reason': 'файл не прочитан'}
    records = [r for r in _walk_records(doc) if 'status' in r]
    vocab = sorted({str(r.get('status')) for r in records})
    items = []
    for r in records:
        if str(r.get('status') or '').lower() != waiting_value:
            continue
        title = ' · '.join(str(x) for x in (r.get('id'), r.get('title')) if x) or 'без названия'
        subject, basis, why = _subject_of(title)
        items.append({'source': 'KANBAN.json', 'ref': str(r.get('id') or p.name),
                      'title_ru': title,
                      'age_days': _age_days(r.get('created_at') or r.get('created'), now=now),
                      'severity': r.get('priority'),
                      'severity_declared': bool(r.get('priority')),
                      'subject': subject, 'subject_basis': basis, 'subject_why': why})
    return {'source': 'KANBAN.json', 'state': 'READ', 'waiting_field': 'status',
            'vocabulary': vocab, 'total_rows': len(records),
            'waiting_count': len(items),
            'declares_severity': any(i['severity'] for i in items),
            'items': items}


def build_owner_decisions(*, production_root, bridge_db=None, now=None):
    """Одна производная очередь. Ничего не создаёт и ничего не двигает."""
    now = now or _now()
    root = Path(production_root)
    sources = []

    if bridge_db:
        sources.append(from_bridge_gates(bridge_db, now=now))
    sources.append(from_tracker(root / 'nimbalyst-local' / 'tracker', now=now,
                                families=('own', 'owner'),
                                waiting_statuses=('needs-owner',)))
    # `agent-*` в очередь владельца НЕ входит: правило приёмки прямо говорит, что на эту
    # семью оно не распространяется. Меряем отдельно и называем расхождением словаря.
    agent_blocked = from_tracker(root / 'nimbalyst-local' / 'tracker', now=now,
                                 families=('agent',), waiting_statuses=('blocked',))
    agent_blocked['source'] = 'tracker:agent-* (НЕ очередь владельца)'
    agent_blocked['excluded_from_owner_queue'] = True
    agent_blocked['exclusion_basis'] = (
        'словарь трекера подписывает статус blocked как «ждёт владельца», а правило '
        'приёмки прямо исключает семью agent-* из очереди владельца: расхождение словаря '
        'и правила порождает мнимое ожидание')

    # Список зовётся `gates`, а не `blockers`: первая редакция читала несуществующий
    # ключ и честно печатала «ждёт 0» — ноль, означавший «не туда посмотрели».
    sources.append(from_json_flag(
        root / 'data' / 'owner_blockers.json', now=now,
        source_name='data/owner_blockers.json', waiting_field='status',
        is_waiting=lambda r: str(r.get('status')) == 'open',
        # Идентификатор входит в разбираемый текст намеренно: у этого источника он и
        # есть объявление предмета (`custody`, `audit`, `legal`), а описание — проза.
        describe=lambda r: ' · '.join(x for x in (r.get('id'), r.get('what')) if x)
                           or 'препятствие без названия',
        list_key='gates', ref_key='id', severity_key='severity'))
    sources.append(from_json_flag(
        root / 'data' / 'gate_status.json', now=now,
        source_name='data/gate_status.json', waiting_field='owner_acceptance',
        is_waiting=lambda r: str(r.get('owner_acceptance')).upper() == 'PENDING',
        describe=lambda r: 'приёмка владельцем гейта готовности не получена',
        age_key='generated_at', subject='1',
        subject_basis_note='гейт готовности существует ради перехода на настоящие деньги'))
    sources.append(from_json_flag(
        root / 'data' / 'live_trading_gate.json', now=now,
        source_name='data/live_trading_gate.json', waiting_field='owner_acceptance',
        is_waiting=lambda r: r.get('owner_acceptance') is False,
        describe=lambda r: 'приёмка владельцем перехода на живую торговлю не получена',
        age_key='generated_at', subject='1',
        subject_basis_note='файл целиком посвящён переходу на настоящие деньги'))

    # KANBAN — исторический реестр задач. Читается ради полноты ответа: ждущий в нём
    # элемент ждёт независимо от того, что сам файл давно не обновлялся.
    # Обход ВСЕГО документа, а не одного списка: ждущая запись лежит под
    # `columns.backlog`, и чтение только `tasks` честно печатало «ждёт 0» — ноль,
    # означавший «смотрели не туда». Население счётчика важнее самого счётчика.
    sources.append(from_kanban(root / 'KANBAN.json', now=now))

    items = [i for s in sources for i in s.get('items') or ()]
    items.sort(key=lambda i: (i.get('age_days') is None, -(i.get('age_days') or 0)))
    by_subject, by_class = {}, {c: 0 for c in ITEM_CLASSES}
    for i in items:
        by_subject[i['subject']] = by_subject.get(i['subject'], 0) + 1
        cls, basis = classify_item(i)
        i['item_class'] = cls
        i['item_class_basis'] = basis
        by_class[cls] += 1
    ages = [i['age_days'] for i in items if i.get('age_days') is not None]
    return {
        'schema': 'owner_decisions/1',
        'state': 'READ',
        'measured_at': now.isoformat(),
        'sources': sources,
        'excluded_sources': [agent_blocked],
        'items': items,
        'waiting_total': len(items),
        'waiting_total_basis': ('сумма по источникам: склеивать нечего, доказанных '
                                'совпадений идентификатора между источниками нет'),
        'by_subject': by_subject,
        'by_class': by_class,
        'class_vocabulary': {
            CLASS_OWNER: 'ждёт решения владельца',
            CLASS_SYSTEM: 'это должна разобрать система, а не владелец',
            CLASS_STALE: 'предмет владельца, но предпосылку надо перемерить',
            CLASS_UNKNOWN: 'предмет не определён',
        },
        'owner_decisions_required': [i for i in items if i['item_class'] == CLASS_OWNER],
        'owner_decisions_required_count': by_class[CLASS_OWNER],
        'stale_after_days': STALE_AFTER_DAYS,
        'class_note': ('канонические записи НЕ меняются: классификация живёт только в '
                       'производной проекции. Элемент, отнесённый к работе системы, '
                       'остаётся открытым там, где он объявлен'),
        'subject_vocabulary': dict(SUBJECTS),
        'queue_defects': by_subject.get('NONE', 0),
        'queue_defect_note': ('элемент, не попадающий ни в один из трёх предметов, — '
                              'работа агента, а не решение владельца'),
        'subject_basis_note': ('предмет присвоен приметами в тексте и помечен HEURISTIC: '
                               'ни один источник не объявляет предмет полем'),
        'oldest_age_days': max(ages) if ages else None,
        'items_without_declared_age': sum(1 for i in items if i.get('age_days') is None),
        'severity_note': ('срочность не объявляет ни один источник, поэтому её здесь нет '
                          'ни полем, ни цветом, ни порядком; порядок — по возрасту'),
        'identity_note': ('склейка выполняется только по доказанному совпадению '
                          'идентификатора; совпадение заголовков совпадением не является'),
    }
