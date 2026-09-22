#!/usr/bin/env python3
"""SPA · Долговечность канонической истории — измерение и НЕИЗМЕНЯЕМЫЙ журнал закрытых дней.

Что уже есть, и почему это важно не переделывать
================================================
Замер показал, что резервная инфраструктура существует и работает: дневной архив
объявляет кривую эквити обязательной (отсутствие файла роняет сборку архива, а не даёт
частичный), у архива есть манифест с sha256, учения восстановления идут четыре раза в
сутки в изолированной песочнице, и один путь действительно уходит с устройства через
облачную папку. Кривая капитала переживёт потерю машины — все 122 точки, включая 77,
которых нет ни в одном коммите.

Поэтому здесь НЕ строится ещё один механизм резервирования. Здесь закрываются три
конкретные дыры, которых существующие приборы не видят.

Дыра 1 — прошлое ИЗМЕНЯЕМО, и никто не сравнивает
==================================================
Писатель ряда перезаписывает файл целиком. Замер по истории git: **семь коммитов, 90
перезаписей уже закрытых дат**; в одном из них эквити одиннадцати закрытых дней сдвинулось
примерно на −216 USD, а просадка 20.06 прошла путь ``0.0 → −0.094466 → 0.0``. Ни один
сторож не сравнивает сегодняшний ряд с вчерашним, а с 05.07 нет и копии в git, с которой
можно было бы сравнить.

Журнал закрытых дней ниже — приложение, а не источник правды: он пересобирается из ряда.
Но он **только дописывается**, и попытка изменить уже записанный день становится находкой,
а не тихой правкой.

Дыра 2 — кольцевой буфер тикает
===============================
Ряд обрезается до **365 последних точек** (``daily = daily[-MAX_EQUITY_POINTS:]``).
Точки старше начнут исчезать сами собой; канон в git остановился на 04.07, дневные архивы
чистятся по своему сроку. Ни один прибор не считает, сколько дней осталось.

Дыра 3 — сторож отвечает «ok» об отсутствующем архиве
=====================================================
Замер: дневного архива за **17.09 не существует** (в каталоге архивов есть 16.09 и 18.09),
а отчёт здоровья объявляет этот день ``{'state': 'ok'}``. Отсутствие наблюдения выдано
за успех — ровно запрещённый инвариантом #17 случай.

Read-only по отношению к прод-дереву: журнал пишется ТОЛЬКО в объявленный каталог
вне репозитория. Только stdlib.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tarfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCHEMA = 'history_durability/1'
LEDGER_SCHEMA = 'closed_day_ledger/1'

#: Сколько точек держит ряд. Значение ЧИТАЕТСЯ из источника, а не дублируется здесь:
#: вписанная копия разошлась бы с правдой молча.
RING_CAP_DECL = ('spa_core/paper_trading/_cycle_io.py', 'MAX_EQUITY_POINTS')

#: За сколько дней до обрезания начинать говорить вслух.
HORIZON_WARN_DAYS = 90

#: Состояния долговечности одного хранилища.
DURABILITY = ('SURVIVES_MACHINE_LOSS', 'LOCAL_ONLY', 'LOST', 'NOT_MEASURED')

_DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_ARCHIVE_DAY = re.compile(r'(\d{4})(\d{2})(\d{2})T\d{6}Z')

#: Поля точки, входящие в её отпечаток. Список РАЗРЕШЁННЫХ: поле, добавленное завтра,
#: не объявит задним числом, что все прошлые дни переписаны.
POINT_DIGEST_FIELDS = ('date', 'open_equity', 'close_equity', 'daily_return_pct',
                       'cumulative_return_pct', 'drawdown_pct', 'evidenced', 'source')


def _now():
    return datetime.now(timezone.utc)


def read_ring_cap(production_root):
    """Ёмкость кольцевого буфера ИЗ ИСТОЧНИКА. Не найдено — честное «не измерено»."""
    path = Path(production_root) / RING_CAP_DECL[0]
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return None, f'файл {RING_CAP_DECL[0]} не прочитан'
    m = re.search(rf'^{RING_CAP_DECL[1]}\s*=\s*(\d+)', text, re.M)
    if not m:
        return None, f'{RING_CAP_DECL[1]} не объявлен в {RING_CAP_DECL[0]}'
    return int(m.group(1)), f'{RING_CAP_DECL[0]}:{RING_CAP_DECL[1]}'


def point_digest(row):
    """Отпечаток одной точки по объявленному списку полей."""
    view = {k: row.get(k) for k in POINT_DIGEST_FIELDS}
    blob = json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:32]


# ── Журнал закрытых дней: только дописывается ─────────────────────────────────

def _closed_rows(daily, *, today):
    """Закрытые дни: всё, кроме текущего. Сегодняшняя точка ещё дописывается циклом,
    и объявлять её неизменяемой значило бы ловить собственный дневной цикл."""
    out = []
    for row in daily or ():
        d = str(row.get('date') or '')[:10]
        if not _DAY.match(d) or d >= today.isoformat():
            continue
        out.append((d, row))
    out.sort(key=lambda p: p[0])
    return out


def load_ledger(path):
    p = Path(path)
    if not p.is_file():
        return {'schema': LEDGER_SCHEMA, 'days': {}, 'first_written_at': None}
    try:
        doc = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None                     # НЕ пустой журнал: нечитаемый ≠ отсутствующий
    if doc.get('schema') != LEDGER_SCHEMA:
        return None
    return doc


def update_ledger(daily, *, ledger_path, today=None, now=None, write=True):
    """Дописать закрытые дни. ИЗМЕНЕНИЕ уже записанного дня — находка, не правка.

    Журнал не источник правды: он пересобирается из ряда, и его потеря не теряет ничего,
    кроме способности заметить переписывание. Но именно эту способность он и даёт.
    """
    now = now or _now()
    today = today or now.date()
    existing = load_ledger(ledger_path)
    if existing is None:
        return {'state': 'NOT_MEASURED',
                'reason': 'журнал существует и не читается — сравнивать нельзя, '
                          'и создавать новый поверх запрещено: это стёрло бы улику'}
    days = dict(existing.get('days') or {})
    appended, rewritten, unchanged = [], [], 0
    for d, row in _closed_rows(daily, today=today):
        digest = point_digest(row)
        prior = days.get(d)
        if prior is None:
            days[d] = {'digest': digest, 'first_seen_at': now.isoformat(),
                       'close_equity': row.get('close_equity'),
                       'evidenced': bool(row.get('evidenced'))}
            appended.append(d)
        elif prior.get('digest') != digest:
            rewritten.append({
                'date': d,
                'digest_before': prior.get('digest'),
                'digest_now': digest,
                'close_equity_before': prior.get('close_equity'),
                'close_equity_now': row.get('close_equity'),
                'first_seen_at': prior.get('first_seen_at'),
                'note': 'закрытый день изменился после записи в журнал'})
        else:
            unchanged += 1
    out = {
        'schema': LEDGER_SCHEMA,
        'days': days,
        'first_written_at': existing.get('first_written_at') or now.isoformat(),
        'last_written_at': now.isoformat(),
        'day_count': len(days),
    }
    out['ledger_digest'] = hashlib.sha256(json.dumps(
        {d: v['digest'] for d, v in sorted(days.items())},
        sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()[:32]
    if write:
        target = Path(ledger_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + '.tmp')
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)          # одна операция: журнал либо старый, либо новый
    return {
        'state': 'MEASURED',
        'ledger': out,
        'appended': appended,
        'appended_count': len(appended),
        'rewritten': rewritten,
        'rewritten_count': len(rewritten),
        'unchanged_count': unchanged,
        'verdict': 'IMMUTABLE' if not rewritten else 'PAST_REWRITTEN',
        'immutability_note': ('журнал только дописывается; изменение уже записанного дня '
                              'становится находкой, а не тихой правкой'),
    }


# ── Горизонт кольцевого буфера ────────────────────────────────────────────────

def ring_buffer_horizon(daily, *, production_root, now=None):
    """Через сколько дней ряд начнёт терять историю сам собой."""
    now = now or _now()
    cap, basis = read_ring_cap(production_root)
    points = [r for r in daily or () if _DAY.match(str(r.get('date') or '')[:10])]
    if cap is None:
        return {'state': 'NOT_MEASURED', 'reason': basis, 'points': len(points)}
    remaining = cap - len(points)
    dates = sorted(str(r['date'])[:10] for r in points)
    return {
        'state': 'MEASURED',
        'cap': cap,
        'cap_basis': basis,
        'points': len(points),
        'days_until_truncation': remaining,
        'first_point_at_risk': dates[0] if dates else None,
        'estimated_truncation_date': (
            (now.date() + timedelta(days=max(remaining, 0))).isoformat()
            if remaining >= 0 else 'уже обрезается'),
        'warning': remaining <= HORIZON_WARN_DAYS,
        'note': ('ряд обрезается до последних точек по ёмкости, объявленной источником. '
                 'Точки старше исчезнут БЕЗ ошибки и без записи в журнал — поэтому '
                 'горизонт считается прибором, а не предполагается'),
    }


# ── Честная сверка заявлений о резервировании ─────────────────────────────────

def archive_days(backup_dir):
    """Какие дни ДЕЙСТВИТЕЛЬНО имеют архив. Каталога нет — «не измерено», не пустота."""
    p = Path(backup_dir)
    if not p.is_dir():
        return None
    days = set()
    for f in p.glob('*.tar.gz'):
        m = _ARCHIVE_DAY.search(f.name)
        if m:
            days.add('-'.join(m.groups()))
    return days


def verify_backup_claims(*, claims, backup_dir):
    """Сверка заявлений сторожа с наличием архива — ТОЛЬКО в окне хранения.

    Замер: дневного архива за 17.09 не существует (в каталоге есть 16.09 и 18.09), а
    отчёт здоровья объявляет этот день ``ok``. Отсутствие наблюдения выдано за успех.

    Первая редакция этой проверки насчитала таких дней СЕМНАДЦАТЬ — и шестнадцать из них
    были её собственной ошибкой. Архивы чистятся по сроку хранения, поэтому отсутствие
    архива за август ничего не говорит о том, делался ли он тогда: судить о дне вне окна
    нельзя. Прибор, не знающий границ своего окна, находит дефекты там, где их нет, —
    и это тот же род ошибки, против которого он написан. Дни старше самого старого
    сохранившегося архива получают третий исход.
    """
    actual = archive_days(backup_dir)
    if actual is None:
        return {'state': 'NOT_MEASURED',
                'reason': 'каталог архивов не найден — сверять нечего, и это НЕ значит '
                          'что архивов нет'}
    if not actual:
        return {'state': 'NOT_MEASURED',
                'reason': 'в каталоге нет ни одного архива: окна хранения не определить'}
    window_start = min(actual)
    rows, lying, outside = [], [], []
    for day, claim in sorted((claims or {}).items()):
        declared = (claim or {}).get('state') if isinstance(claim, dict) else claim
        if day < window_start:
            rows.append({'day': day, 'declared': declared, 'archive_present': None,
                         'verdict': 'OUTSIDE_RETENTION_WINDOW',
                         'note': 'день старше самого старого сохранившегося архива: '
                                 'отсутствие архива сегодня не говорит о прошлом'})
            outside.append(day)
            continue
        present = day in actual
        verdict = ('AGREES' if (declared == 'ok') == present
                   else ('CLAIMS_OK_BUT_ABSENT' if declared == 'ok'
                         else 'CLAIMS_BAD_BUT_PRESENT'))
        rows.append({'day': day, 'declared': declared, 'archive_present': present,
                     'verdict': verdict})
        if verdict == 'CLAIMS_OK_BUT_ABSENT':
            lying.append(day)
    return {
        'state': 'MEASURED',
        'retention_window_start': window_start,
        'archives_present': len(actual),
        'days_checked': len(rows),
        'days_judgeable': len(rows) - len(outside),
        'days_outside_window': outside,
        'rows': rows,
        'days_claimed_ok_without_archive': lying,
        'false_ok_count': len(lying),
        'verdict': 'HONEST' if not lying else 'GUARD_REPORTS_OK_FOR_MISSING_ARCHIVE',
        'note': ('«ok» об отсутствующем архиве ВНУТРИ окна хранения — не неточность, '
                 'а отсутствие наблюдения, выданное за успех. Вне окна судить нельзя'),
    }


def archive_contains(archive_path, member_suffix):
    """Есть ли файл в архиве. Проверяется чтением архива, а не именем скрипта."""
    p = Path(archive_path)
    if not p.is_file():
        return {'state': 'NOT_MEASURED', 'reason': 'архив не найден'}
    try:
        with tarfile.open(p, 'r:gz') as tar:
            for name in tar.getnames():
                if name.endswith(member_suffix):
                    return {'state': 'PRESENT', 'member': name,
                            'members_total': len(tar.getnames())}
            return {'state': 'ABSENT', 'members_total': len(tar.getnames())}
    except (OSError, tarfile.TarError) as exc:
        return {'state': 'NOT_MEASURED', 'reason': exc.__class__.__name__}


def build_durability(*, production_root, ledger_path, backup_dir=None,
                     equity_relpath='data/equity_curve_daily.json',
                     health_relpath='data/system_health.json',
                     now=None, write_ledger=True):
    """Сводка долговечности истории. Ничего в прод-дереве не меняет."""
    now = now or _now()
    root = Path(production_root)
    try:
        equity = json.loads((root / equity_relpath).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'schema': SCHEMA, 'state': 'NOT_MEASURED',
                'reason': f'{equity_relpath} не прочитан', 'measured_at': now.isoformat()}
    daily = equity.get('daily') or []
    ledger = update_ledger(daily, ledger_path=ledger_path, now=now, write=write_ledger)
    horizon = ring_buffer_horizon(daily, production_root=root, now=now)
    claims = {}
    try:
        health = json.loads((root / health_relpath).read_text(encoding='utf-8'))
        claims = health.get('offsite_backup_days') or {}
    except (OSError, ValueError):
        claims = {}
    backup = verify_backup_claims(claims=claims,
                                  backup_dir=backup_dir or (root / 'data' / 'backups'))
    return {
        'schema': SCHEMA,
        'state': 'READ',
        'measured_at': now.isoformat(),
        'series_points': len(daily),
        'ledger': ledger,
        'ring_buffer': horizon,
        'backup_claims': backup,
        'summary_note': ('кривая капитала резервируется и восстанавливается — это '
                         'измерено. Закрываются три другие дыры: изменяемость прошлого, '
                         'тикающий кольцевой буфер и сторож, отвечающий «ok» об '
                         'отсутствующем архиве'),
    }
