#!/usr/bin/env python3
"""Director OS · Контракт правды (OwnerFact) — v1.3.

Зачем он существует
===================
Красная команда v1.2 нашла шесть дефектов ОДНОГО класса: у числа на экране не было
паспорта. «Эквити, USDC» — валюту приписал экран, источник её не объявляет. «Просадка» —
два разных вычисления под одним словом. «Доход за 7 дней» — разность накопленных
доходностей вместо отношения эквити. «Вложено» — выведено суммированием, хотя источник
объявляет поле сам. Ни один из этих дефектов не был виден в коде отрисовки: чтобы его
увидеть, надо было держать рядом число и ответ на вопрос «откуда оно».

Контракт делает ответ ОБЯЗАТЕЛЬНЫМ. Значение без паспорта собрать нельзя — ``fact()``
откажет. Поэтому класс дефектов закрывается не бдительностью, а построением.

Чем это НЕ является
===================
Это **не** новый источник правды. Ни один факт здесь не рождается: каждый обязан назвать
файл и поле, откуда взят, либо формулу и факты, из которых выведен. Набор фактов —
производный и пересобираемый; потеря файла фактов не теряет ничего, кроме времени.

Три исхода вместо двух (инвариант #17)
======================================
``value=None`` — законное значение и означает «не измерено». Тогда обязателен
``absent_reason``. «Измерено и равно нулю» — это ``value=0`` с ``freshness_state``
свежести. Различить их обязан уметь каждый потребитель, поэтому ``None`` никогда не
заменяется нулём ни при сборке, ни при отрисовке.

Валюта — отдельный предмет
==========================
``currency`` разрешено заполнить, ТОЛЬКО назвав ``currency_basis`` — файл и поле, где
валюта объявлена. Нет объявления — валюты нет, и на экране её тоже нет. Ровно этот
запрет убирает приписанный «USDC».

Дайджест смысла — по СПИСКУ РАЗРЕШЁННЫХ, а не по списку запрещённых
===================================================================
v1.2 вычитала из дайджеста перечень «волатильных» ключей, который велся руками. Он
протёк трижды: ``as_of``, ``last_seen``, ``detected_at``. Причина не в невнимательности,
а в направлении умолчания: НОВОЕ поле попадало в дайджест по умолчанию. Здесь умолчание
обратное — в дайджест попадают только поля из ``SEMANTIC_FACT_FIELDS``. Поле, добавленное
завтра, на дайджест не влияет, пока его не объявят смысловым явно.

LLM здесь запрещён. Только stdlib.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

SCHEMA = 'owner_fact/1'

#: Наблюдение или вывод. Третьего не дано: значение либо прочитано, либо посчитано.
FACT_KINDS = ('OBSERVED', 'DERIVED')

#: Свежесть. ``TIMELESS`` — для величин, которые не устаревают по построению (порог,
#: решение ADR): называть их «свежими» значило бы обещать наблюдение, которого нет.
FRESHNESS_STATES = ('FRESH', 'AGING', 'STALE', 'NOT_MEASURED', 'TIMELESS')

#: Насколько мы уверены В САМОМ ПРАВИЛЕ, давшем значение (не в точности арифметики).
#: ``PROVEN`` — источник объявляет прямо; ``HEURISTIC`` — выведено по косвенному признаку
#: (например род службы по форме расписания); ``UNVERIFIED`` — не перепроверено.
CONFIDENCE_STATES = ('PROVEN', 'HEURISTIC', 'UNVERIFIED', 'NOT_MEASURED')

#: Результат независимой перепроверки. ``CONFLICT`` НИКОГДА не чинится подменой значения:
#: конфликт показывается владельцу, потому что выбор победителя — это уже суждение.
VERIFICATION_STATES = ('VERIFIED', 'CONFLICT', 'UNVERIFIED', 'NOT_APPLICABLE')

#: Режим капитала. ``UNKNOWN`` — не то же, что ``PAPER``: неизвестный режим нельзя
#: читать как бумажный, иначе настоящие деньги однажды покажутся учебными.
MODES = ('PAPER', 'REAL', 'SHADOW', 'BACKTEST', 'PROPOSED', 'UNKNOWN')

#: Что это значит ДЛЯ ВЛАДЕЛЬЦА. Кокпит не советует сделок: ``ACTION_REQUIRED`` означает
#: «источник объявил, что требуется действие», а не «я считаю, что надо купить».
OWNER_RELEVANCE = ('ACTION_REQUIRED', 'DECISION_REQUIRED', 'INFORMATION_ONLY', 'UNKNOWN')

#: Класс публикации наследуется от web_projection: умолчание — UNKNOWN ⇒ не публикуется.
WEB_VISIBILITY = ('SAFE_FOR_PRIVATE_WEB', 'REDACTED', 'LOCAL_ONLY', 'UNKNOWN')

#: Наблюдение против цели. Разделение обязательно: цель, нарисованная как наблюдение, —
#: это ложь о состоянии портфеля, а не неточность подписи.
OBSERVATION_KINDS = ('CURRENT_OBSERVED', 'TARGET_POLICY', 'SHADOW_PROPOSED',
                     'HISTORICAL', 'CONFIGURED', 'EXPECTED', 'UNKNOWN')

#: ПОЛЯ, ВХОДЯЩИЕ В ДАЙДЖЕСТ СМЫСЛА. Список разрешённых, а не запрещённых.
#: Здесь намеренно НЕТ: observed_at, freshness_age_hours, fact_id (порядковый),
#: derivation (текст формулы), source_field (путь), note. Изменение любого из них
#: не меняет смысла для владельца и не обязано переподставлять комплект.
SEMANTIC_FACT_FIELDS = ('domain', 'metric', 'value', 'unit', 'currency', 'mode',
                        'observation_kind', 'fact_kind', 'freshness_state',
                        'confidence_state', 'verification_state', 'owner_relevance',
                        'absent_reason', 'conflict_count')

_ISO = re.compile(r'^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?')


class FactError(Exception):
    """Отказ собрать факт. Собирается либо полный паспорт, либо ничего."""


def _vocab(name, value, vocabulary):
    if value not in vocabulary:
        raise FactError(f'{name}={value!r} вне словаря {vocabulary}')
    return value


def _parse_ts(value):
    """Отметка времени в UTC либо ``None``. Неразборчивая строка — это НЕ «сейчас»."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        if not _ISO.match(text):
            return None
        try:
            dt = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def age_hours(observed_at, *, now):
    """Возраст наблюдения в часах либо ``None``. ``None`` — не ноль и не свежесть."""
    ts = _parse_ts(observed_at)
    if ts is None or now is None:
        return None
    return round((now - ts).total_seconds() / 3600.0, 3)


def freshness_of(age, *, slo_hours):
    """Свежесть по ОБЪЯВЛЕННОМУ сроку годности.

    Без объявленного SLO ответа нет: ``NOT_MEASURED``. Придумать срок — значит
    назначить норму, а норму назначает архитектура, а не экран.
    """
    if age is None or slo_hours is None:
        return 'NOT_MEASURED'
    if age <= slo_hours:
        return 'FRESH'
    if age <= slo_hours * 3:
        return 'AGING'
    return 'STALE'


def fact(*, domain, metric, value, source, source_field=None, authority=None,
         unit=None, currency=None, currency_basis=None, mode='UNKNOWN',
         observation_kind='CURRENT_OBSERVED', fact_kind='OBSERVED', derivation=None,
         inputs=(), observed_at=None, slo_hours=None, now=None,
         confidence_state='PROVEN', verification_state='NOT_APPLICABLE',
         conflicts=(), owner_relevance='INFORMATION_ONLY',
         web_visibility='UNKNOWN', absent_reason=None, note=None, fact_id=None,
         freshness_state=None):
    """Собрать один факт. Отказывает, если паспорт неполон.

    Отказы здесь — не придирки, а ровно те шесть дефектов v1.2, каждый в своей ветке.
    """
    _vocab('fact_kind', fact_kind, FACT_KINDS)
    _vocab('mode', mode, MODES)
    _vocab('observation_kind', observation_kind, OBSERVATION_KINDS)
    _vocab('confidence_state', confidence_state, CONFIDENCE_STATES)
    _vocab('verification_state', verification_state, VERIFICATION_STATES)
    _vocab('owner_relevance', owner_relevance, OWNER_RELEVANCE)
    _vocab('web_visibility', web_visibility, WEB_VISIBILITY)

    if not domain or not metric:
        raise FactError('у факта обязаны быть domain и metric')
    if not source:
        raise FactError(f'{domain}.{metric}: источник не назван — факта без источника нет')

    # ── Вывод обязан назвать формулу; наблюдение обязано её НЕ называть.
    if fact_kind == 'DERIVED' and not derivation:
        raise FactError(f'{domain}.{metric}: DERIVED без derivation — это и есть '
                        'молчаливый вывод, ради запрета которого контракт написан')
    if fact_kind == 'OBSERVED' and derivation:
        raise FactError(f'{domain}.{metric}: OBSERVED с формулой — значит это вывод, '
                        'а не наблюдение; смените fact_kind')

    # ── Отсутствие обязано назвать причину, иначе «не измерено» неотличимо от нуля.
    if value is None and not absent_reason:
        raise FactError(f'{domain}.{metric}: value=None без absent_reason — '
                        'отсутствие наблюдения обязано быть названо (инвариант #17)')
    if value is not None and absent_reason:
        raise FactError(f'{domain}.{metric}: есть и значение, и причина его отсутствия')

    # ── Валюта: только с указанием, ГДЕ она объявлена. Это запрет на «USDC» от экрана.
    if currency and not currency_basis:
        raise FactError(f'{domain}.{metric}: currency={currency!r} без currency_basis. '
                        'Валюту объявляет источник, а не кокпит')

    conflicts = list(conflicts)
    if conflicts and verification_state != 'CONFLICT':
        raise FactError(f'{domain}.{metric}: конфликты есть, а verification_state={verification_state}')
    if verification_state == 'CONFLICT' and not conflicts:
        raise FactError(f'{domain}.{metric}: CONFLICT без описания расхождения')

    age = age_hours(observed_at, now=now)
    state = freshness_state or freshness_of(age, slo_hours=slo_hours)
    _vocab('freshness_state', state, FRESHNESS_STATES)

    return {
        'schema': SCHEMA,
        'fact_id': fact_id or f'{domain}.{metric}',
        'domain': domain,
        'metric': metric,
        'value': value,
        'unit': unit,
        'currency': currency,
        'currency_basis': currency_basis,
        'mode': mode,
        'observation_kind': observation_kind,
        'source': source,
        'source_field': source_field,
        'authority': authority,
        'observed_at': observed_at,
        'freshness_state': state,
        'freshness_age_hours': age,
        'freshness_slo_hours': slo_hours,
        'fact_kind': fact_kind,
        'derivation': derivation,
        'inputs': list(inputs),
        'confidence_state': confidence_state,
        'verification_state': verification_state,
        'conflicts': conflicts,
        'conflict_count': len(conflicts),
        'owner_relevance': owner_relevance,
        'web_visibility': web_visibility,
        'absent_reason': absent_reason,
        'note': note,
    }


def not_measured(*, domain, metric, source, reason, **kw):
    """Короткая форма честного «не измерено». Существует, чтобы не соблазнять нулём."""
    kw.pop('value', None)
    kw.pop('absent_reason', None)
    kw.setdefault('confidence_state', 'NOT_MEASURED')
    kw.setdefault('freshness_state', 'NOT_MEASURED')
    return fact(domain=domain, metric=metric, value=None, source=source,
                absent_reason=reason, **kw)


def with_conflict(base, *, other_value, other_source, tolerance=0.0):
    """Перепроверка факта независимым значением.

    Согласие → ``VERIFIED``. Расхождение → ``CONFLICT`` **без подмены значения**:
    победитель здесь не выбирается никогда, потому что выбор победителя есть суждение
    о том, какой источник авторитетнее, а это решение архитектуры, а не сборки.
    """
    out = dict(base)
    if base.get('value') is None or other_value is None:
        out['verification_state'] = 'UNVERIFIED'
        return out
    try:
        agree = abs(float(base['value']) - float(other_value)) <= tolerance
    except (TypeError, ValueError):
        agree = base['value'] == other_value
    if agree:
        out['verification_state'] = 'VERIFIED'
        out['conflicts'] = []
        out['conflict_count'] = 0
        return out
    out['verification_state'] = 'CONFLICT'
    out['conflicts'] = [{'other_value': other_value, 'other_source': other_source,
                         'declared_value': base['value'],
                         'note': 'расхождение показано, а не устранено: выбор источника — '
                                 'решение архитектуры'}]
    out['conflict_count'] = 1
    return out


# ──────────────────────────────────────────────────────────────────────────────
#  Дайджест смысла v2 — по объявленному списку разрешённых полей
# ──────────────────────────────────────────────────────────────────────────────

def semantic_projection(facts):
    """Смысловая проекция набора фактов: только поля из ``SEMANTIC_FACT_FIELDS``.

    Порядок нормализуется сортировкой по ``fact_id``: перестановка списка не есть
    изменение смысла, а дайджест обязан отвечать на вопрос о смысле.
    """
    rows = []
    for f in facts:
        row = {k: f.get(k) for k in SEMANTIC_FACT_FIELDS}
        row['fact_id'] = f.get('fact_id')
        rows.append(row)
    return sorted(rows, key=lambda r: (str(r.get('fact_id')), str(r.get('metric'))))


def semantic_digest(facts, *, length=24):
    """Отпечаток смысла. Отметки наблюдения в него не входят ПО ПОСТРОЕНИЮ."""
    blob = json.dumps(semantic_projection(facts), ensure_ascii=False,
                      sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:length]


# ──────────────────────────────────────────────────────────────────────────────
#  Канонический калькулятор доходности — ОДИН на всю систему
# ──────────────────────────────────────────────────────────────────────────────

def _d(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_series(rows, *, date_key='date', equity_key='close_equity'):
    """Ряд ``[(date, equity)]``, отсортированный по дате. Строки без даты или без
    эквити отбрасываются и СЧИТАЮТСЯ: молча потерянная точка — это подделка ряда."""
    points, dropped = [], 0
    for r in rows or ():
        if not isinstance(r, dict):
            dropped += 1
            continue
        raw = r.get(date_key)
        eq = _d(r.get(equity_key))
        ts = _parse_ts(raw) if raw else None
        if ts is None or eq is None:
            dropped += 1
            continue
        points.append((ts.date(), eq, r))
    points.sort(key=lambda p: p[0])
    return points, dropped


def calendar_integrity(points):
    """Пропуски, дубли и нарушения порядка в календаре ряда."""
    if not points:
        return {'state': 'NOT_MEASURED', 'reason': 'ряд пуст'}
    dates = [p[0] for p in points]
    seen, duplicates = set(), []
    for d in dates:
        if d in seen:
            duplicates.append(d.isoformat())
        seen.add(d)
    first, last = dates[0], dates[-1]
    span = (last - first).days + 1
    missing = []
    cursor = first
    while cursor <= last:
        if cursor not in seen:
            missing.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return {
        'state': 'MEASURED',
        'first_date': first.isoformat(),
        'last_date': last.isoformat(),
        'calendar_days_span': span,
        'points': len(points),
        'missing_dates': missing,
        'missing_count': len(missing),
        'duplicate_dates': sorted(set(duplicates)),
        'duplicate_count': len(set(duplicates)),
        'is_continuous': not missing and not duplicates,
    }


def _at_calendar_offset(points, days):
    """Точка ровно за ``days`` календарных дней до последней.

    Возвращает ``(индекс, точность)``: ``EXACT`` — нужная дата есть; ``NEAREST_BEFORE`` —
    нужной даты в ряду нет, взята ближайшая НЕ ПОЗЖЕ неё, и тогда окно фактически другое;
    ``None`` — ряд не покрывает окно вовсе.
    """
    target = points[-1][0] - timedelta(days=days)
    for i in range(len(points) - 1, -1, -1):
        if points[i][0] == target:
            return i, 'EXACT'
    candidates = [i for i in range(len(points)) if points[i][0] <= target]
    if not candidates:
        return None, 'OUT_OF_RANGE'
    return max(candidates), 'NEAREST_BEFORE'


def series_boundaries(points, *, reset_key='series_reset'):
    """Даты, на которых ряд РАЗРЫВАЕТСЯ и склейка не является движением капитала.

    Источник объявляет разрыв сам (``series_reset: true`` плюс пояснение в ``note``).
    Это не догадка слоя: 10.06 в ряду стоит написанное источником предупреждение, что
    ступень эквити между разогревочной и восстановленной сериями — ГРАНИЦА СЕРИЙ, а не
    дневной убыток. Метрика, посчитанная сквозь такую границу, измеряет склейку.
    """
    out = []
    for date, _eq, row in points:
        if isinstance(row, dict) and row.get(reset_key):
            out.append(date)
    return out


def _crosses_boundary(points, start_date, end_date, boundaries):
    return [d.isoformat() for d in boundaries if start_date < d <= end_date]


def window_return(points, days, *, boundaries=()):
    """Доход за календарное окно: ``close[конец] / close[начало] − 1``.

    Это ЕДИНСТВЕННАЯ каноническая формула окна в системе. v1.2 считала разность
    накопленных доходностей: на нынешних сотых долях процента ошибка прячется в
    четвёртом знаке, но она не «мелкая» — она НЕВЕРНА по роду. При удвоении капитала
    дважды разность накопленных даёт 200 п.п. вместо настоящих 300 %.

    Конец окна — закрытие последнего дня, начало — закрытие дня N календарных дней
    назад: между ними ровно N дневных доходностей. Брать ОТКРЫТИЕ начального дня
    означало бы окно N+1 дней под подписью N.
    """
    if len(points) < 2:
        return {'state': 'NOT_MEASURED', 'reason': 'меньше двух точек — окна нет'}
    idx, precision = _at_calendar_offset(points, days)
    if idx is None or idx >= len(points) - 1:
        return {'state': 'NOT_MEASURED',
                'reason': f'ряд не покрывает окно {days} дн.', 'precision': precision}
    start_date, start_eq, _ = points[idx]
    end_date, end_eq, _ = points[-1]
    if not start_eq:
        return {'state': 'NOT_MEASURED', 'reason': 'нулевая база окна'}
    crossed = _crosses_boundary(points, start_date, end_date, boundaries)
    if crossed:
        return {'state': 'NOT_MEASURED',
                'reason': f'окно пересекает разрыв ряда {crossed}: измеряло бы склейку серий, '
                          'а не движение капитала',
                'crosses_series_boundary': crossed}
    actual = (end_date - start_date).days
    return {
        'state': 'MEASURED',
        'value': round((end_eq / start_eq - 1.0) * 100.0, 6),
        'window_requested_days': days,
        'window_actual_days': actual,
        'precision': precision,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'crosses_series_boundary': [],
        'derivation': f'(close[{end_date.isoformat()}] / close[{start_date.isoformat()}] − 1) × 100',
    }


def total_return(points, *, since_index=0, declared_base=None, declared_base_field=None,
                 boundaries=()):
    """Доход за весь период. Основание берётся ОБЪЯВЛЕННОЕ, если источник его объявил.

    Источник объявляет ``summary.start_equity`` (стартовый капитал) и
    ``summary.real_start_equity`` (открытие первого подтверждённого дня). Оба — открытия,
    а не закрытия, и это осмысленно: «за всё время» меряется от денег, которые были ДО
    первой сделки. Вывести своё основание из ``close[0]`` значило бы тихо разойтись с
    источником на 0.011 п.п. — ровно тот молчаливый вывод, который контракт запрещает.
    """
    if len(points) < 2 or since_index >= len(points) - 1:
        return {'state': 'NOT_MEASURED', 'reason': 'ряда для расчёта нет'}
    start_date, close_eq, _ = points[since_index]
    end_date, end_eq, _ = points[-1]
    # `is not None`, а не истинность: объявленное основание 0 — это объявленный ноль,
    # и подменять его закрытием первой точки значило бы тихо сменить базу расчёта.
    base = declared_base if declared_base is not None else close_eq
    basis = declared_base_field or 'close_equity первой точки (источник основания не объявил)'
    if not base:
        return {'state': 'NOT_MEASURED', 'reason': 'нулевая база'}
    crossed = _crosses_boundary(points, start_date, end_date, boundaries)
    return {'state': 'MEASURED',
            'value': round((end_eq / base - 1.0) * 100.0, 6),
            'start_date': start_date.isoformat(), 'end_date': end_date.isoformat(),
            'base_value': base, 'base_field': basis,
            'crosses_series_boundary': crossed,
            'derivation': f'(close[{end_date.isoformat()}] / {basis} − 1) × 100'}


def max_drawdown(points, *, boundaries=()):
    """МАКСИМАЛЬНАЯ просадка: худшее падение от достигнутого пика к последующему дну.

    Это НЕ текущая просадка, и звать их одним словом «просадка» запрещено: v1.2 держала
    на одном экране карточку с одной величиной и график с другой.

    Разрыв ряда обнуляет пик. Без этого «просадка −0.2047 %» есть ступень между
    разогревочной и восстановленной сериями 10.06 — то есть измерение склейки. Именно
    это число v1.2 показывала владельцу как просадку, и именно его я подтвердил в
    красной команде собственным пересчётом: пересчёт повторил арифметику источника и
    вместе с ней повторил её предмет.
    """
    if len(points) < 2:
        return {'state': 'NOT_MEASURED', 'reason': 'меньше двух точек'}
    bset = set(boundaries)
    peak, peak_date = points[0][1], points[0][0]
    worst, worst_peak_date, worst_trough_date = 0.0, None, None
    segments, skipped = 1, 0
    for date, eq, _ in points:
        if date in bset:
            peak, peak_date = eq, date     # новая серия — новый пик
            segments += 1
            continue
        if eq > peak:
            peak, peak_date = eq, date
        if peak > 0:
            dd = (eq / peak - 1.0) * 100.0
            if dd < worst:
                worst, worst_peak_date, worst_trough_date = dd, peak_date, date
        else:
            skipped += 1        # точка с нулевым пиком не считается и НЕ молчит
    return {'state': 'MEASURED', 'value': round(worst, 6),
            'peak_date': worst_peak_date.isoformat() if worst_peak_date else None,
            'trough_date': worst_trough_date.isoformat() if worst_trough_date else None,
            'segments': segments, 'points_skipped_zero_peak': skipped,
            'boundaries_honoured': [d.isoformat() for d in bset],
            'derivation': 'min по ряду от (close / бегущий максимум close − 1) × 100; '
                          'бегущий максимум сбрасывается на объявленном разрыве ряда'}


def current_drawdown(points):
    """ТЕКУЩАЯ просадка: где мы сейчас относительно исторического пика."""
    if not points:
        return {'state': 'NOT_MEASURED', 'reason': 'ряд пуст'}
    peak, peak_date = points[0][1], points[0][0]
    for date, eq, _ in points:
        if eq > peak:
            peak, peak_date = eq, date
    last_date, last_eq, _ = points[-1]
    if not peak:
        return {'state': 'NOT_MEASURED', 'reason': 'нулевой пик'}
    return {'state': 'MEASURED', 'value': round((last_eq / peak - 1.0) * 100.0, 6),
            'peak_date': peak_date.isoformat(), 'as_of_date': last_date.isoformat(),
            'derivation': f'(equity[{last_date.isoformat()}] / пик[{peak_date.isoformat()}] − 1) × 100'}
