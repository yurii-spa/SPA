#!/usr/bin/env python3
"""SPA · Контракт здоровья компонента. Проверяет НАЗНАЧЕНИЕ, а не существование.

Постановка, которую изменил замер
=================================
``HEALTHY`` не измерено у 103 сущностей из 103 — но **не потому, что мерить нечем**.
Обёртка агента печатает на каждом прогоне строку с меткой времени и кодом возврата
(``EXIT agent=<имя> code=<RC>``), и такие журналы есть у 63 сущностей из 103. Признак
последнего успеха НАБЛЮДАЕМ у всех десяти самых критичных и у всех двадцати шести из
названных семейств. Объявлен он ровно у ОДНОЙ.

То есть дыра не в приборах, а в объявлении: измерение существует и не названо.

Флагманский случай — почему «процесс жив» ничего не значит
==========================================================
Телеграм-бот прямо сейчас: ``launchctl`` даёт код 0, номер процесса на месте, маячок
возможностей свеж (0.0 ч). Все существующие сторожа говорят «здоров».

А журнал бота оборван 18.09 строкой ``getUpdates failed (streak=5) — backoff 32s``, и
файл смещения обновлений не двигался **82 часа**. Канал кнопок владельца мёртв трое
суток, и ни один прибор этого не сказал.

Маячок мерит «обёртка крутится». Файл смещения мерит «бот делает своё дело». Контракт
обязан спрашивать второе.

Четыре смысла отсутствующего выхода
===================================
Самая тонкая часть контракта. Отсутствие объявленного артефакта означает РАЗНОЕ:

* ``FAILURE`` — должен был написать и не написал;
* ``HEALTHY_WHEN_ABSENT`` — отсутствие и ЕСТЬ здоровье. Реактор угроз объявляет выходом
  файл включённого стоп-крана: пока его нет, всё в порядке, а объявленный срок годности
  выполним только в аварии;
* ``ZERO_EVENTS`` — писать было нечего. Приёмник событий при нуле событий молчит
  законно;
* ``NOT_MEASURED`` — неизвестно.

Прежняя проверка знала только первый смысл и потому ошибалась в обе стороны.

Наблюдение есть, доверия нет
============================
``blind_values`` — состояния, при которых артефакт свеж, а вердикт по нему брать нельзя.
Замер: файл красных флагов свеж и код возврата нулевой, а внутри ``fallback_used: true``,
и читатель этих флагов исполняет свою ветку только при ``fallback_used == false`` — то
есть не исполняет её вовсе. Свежий файл, который никто не читает, здоровьем не является.

Only stdlib. Ничего не запускает, не перезапускает и не меняет.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'health_contract/1'

#: Вердикт здоровья. Четыре исхода, и два последних НЕ являются провалом.
HEALTHY = 'HEALTHY'
UNHEALTHY = 'UNHEALTHY'
#: Работает, но ХУЖЕ объявленного ожидания. Не провал и не здоровье: артефакт уже
#: старше порога предупреждения и ещё не старше предела. Без этого состояния приходится
#: выбирать между «всё хорошо» и «сломано» там, где верно ни то, ни другое.
DEGRADED = 'DEGRADED'
BLIND = 'BLIND'
NOT_MEASURED = 'NOT_MEASURED'
#: Вопрос НЕПРИМЕНИМ. Расписанное задание между запусками не работает по построению,
#: и спрашивать у него о резидентности — спрашивать не то.
NOT_APPLICABLE = 'NOT_APPLICABLE'
VERDICTS = (HEALTHY, UNHEALTHY, DEGRADED, BLIND, NOT_MEASURED, NOT_APPLICABLE)

#: Что означает отсутствие объявленного выхода.
ABSENCE_MEANS = ('FAILURE', 'HEALTHY_WHEN_ABSENT', 'ZERO_EVENTS', 'NOT_MEASURED')

#: Критичность. Контракты пишутся сверху вниз, а не всем сразу.
TIERS = ('C1', 'C2', 'C3', 'C4', 'C5')

#: Словарь кодов дневного цикла — единственный настоящий контракт исходов в системе.
#: Код 3 — ШТАТНЫЙ отказ политики: успех по смыслу, ненулевой по форме.
CYCLE_EXIT_VOCABULARY = {
    0: ('OK', 'отработал'),
    1: ('FAILURE', 'авария'),
    2: ('LOCK_REFUSED', 'отказ замка'),
    3: ('POLICY_REFUSED_BY_DESIGN', 'штатный отказ политики'),
    4: ('NO_LIVE_DATA', 'нет живых данных'),
    5: ('SAFETY_CHECK_DID_NOT_RUN', 'проверка безопасности не отработала'),
    6: ('PROTECTION_FIRED', 'сработала защита'),
}

_EXIT_LINE = re.compile(
    r'^\[(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\]\s+EXIT\s+agent=(?P<agent>\S+)\s+'
    r'code=(?P<code>-?\d+)\s*$')


class ContractError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


def _age_hours(path, *, now):
    try:
        return round((now.timestamp() - os.stat(path).st_mtime) / 3600.0, 3)
    except OSError:
        return None


# ── Последний успех: из строки обёртки, потому что у неё есть ВРЕМЯ ───────────

def read_last_exit(log_path, *, agent=None, tail_bytes=200_000):
    """Последний зафиксированный выход агента: код И время.

    ``launchctl list`` даёт код без времени, поэтому по нему нельзя сказать, когда
    компонент работал в последний раз. Строка обёртки даёт оба.
    """
    p = Path(log_path)
    if not p.is_file():
        return {'state': NOT_MEASURED, 'reason': 'журнала обёртки нет'}
    try:
        with open(p, 'rb') as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - tail_bytes))
            text = fh.read().decode('utf-8', errors='replace')
    except OSError as exc:
        return {'state': NOT_MEASURED, 'reason': exc.__class__.__name__}
    last = None
    for line in text.splitlines():
        m = _EXIT_LINE.match(line.strip())
        if m and (agent is None or m.group('agent') == agent):
            last = m
    if last is None:
        return {'state': NOT_MEASURED,
                'reason': 'строки выхода в журнале нет — прогонов с этой обёрткой '
                          'не зафиксировано'}
    return {'state': 'MEASURED', 'exit_code': int(last.group('code')),
            'at': last.group('ts'), 'agent': last.group('agent')}


def classify_exit(code, contract):
    """Код возврата по ОБЪЯВЛЕННОМУ словарю компонента.

    Ненулевой код не всегда провал: у дневного цикла код 3 — штатный отказ политики,
    и звать его поломкой значило бы требовать от системы торговать, когда она обязана
    отказаться.
    """
    if code is None:
        return NOT_MEASURED, 'код возврата не наблюдался'
    ok = contract.get('success', {}).get('ok_values') or [0]
    by_design = contract.get('success', {}).get('by_design_values') or []
    if code in ok:
        return HEALTHY, f'код {code} объявлен успешным'
    if code in by_design:
        name = CYCLE_EXIT_VOCABULARY.get(code, ('', 'штатный отказ'))[1]
        return HEALTHY, f'код {code} объявлен штатным ({name}), это не поломка'
    return UNHEALTHY, f'код {code} не объявлен ни успешным, ни штатным'


def verify_cadence(path, *, expected_seconds, samples=3, sleeper=None,
                   stat_fn=None, tolerance=0.5):
    """Измерить ТАКТ признака назначения, а не поверить в него.

    Зачем это существует. Выбирая признак назначения, я дважды взял файл, чьё время
    изменения означает нечто СОСЕДНЕЕ с нужным:

    * у телеграм-бота — файл смещения обновлений. Он пишется только при ВХОДЯЩЕМ
      сообщении, то есть мерит активность ВЛАДЕЛЬЦА. 83 часа значили, что владелец
      трое суток ничего не нажимал, а не что бот сломан;
    * у координатора моста — ``runtime_coordinator.json``. Он содержит ``started_at``
      и пишется один раз при старте, то есть мерит ВРЕМЯ ЗАПУСКА. 88 часов значили,
      что резидент не перезапускался, — ровно то, чего от него и хотят.

    Оба раза файл выглядел правдоподобно, и оба раза исправный компонент получил
    ``UNHEALTHY``. Правдоподобие уликой не является. Признак назначения обязан ТИКАТЬ
    с объявленным тактом, и это проверяется замером, а не выбором имени.
    """
    sleep = sleeper or (lambda s: __import__('time').sleep(s))
    stat = stat_fn or (lambda p: os.stat(p).st_mtime)
    seen = []
    total = max(2, samples)
    for i in range(total):
        try:
            seen.append(stat(path))
        except OSError:
            return {'state': NOT_MEASURED, 'reason': 'файла нет — такт не измерить'}
        if i < total - 1:
            sleep(expected_seconds * (1 + tolerance))
    moved = len({round(x, 3) for x in seen}) > 1
    gaps = [round(b - a, 2) for a, b in zip(seen, seen[1:]) if b > a]
    return {
        'state': 'MEASURED',
        'ticks': moved,
        'samples': len(seen),
        'observed_gaps_seconds': gaps,
        'expected_seconds': expected_seconds,
        'verdict': 'TICKS_AS_DECLARED' if moved else 'DOES_NOT_TICK',
        'note': ('признак, не двигающийся за объявленный такт, мерит НЕ то, что нужно: '
                 'он может быть отметкой запуска или следом чужой активности'),
    }



# ── Оценка одного контракта ───────────────────────────────────────────────────

def evaluate(contract, *, production_root, now=None, log_root='/tmp'):
    """Вердикт здоровья ОДНОГО компонента по его объявленному контракту."""
    now = now or _now()
    label = contract.get('label')
    if not label:
        raise ContractError('контракт без label')
    absence = contract.get('output_absence_means', 'NOT_MEASURED')
    if absence not in ABSENCE_MEANS:
        raise ContractError(f'output_absence_means={absence!r} вне словаря {ABSENCE_MEANS}')
    # Контракт, объявивший отсутствие выхода провалом и НЕ назвавший признак назначения,
    # проверяет только существование процесса — ровно то, ради запрета чего модель и
    # написана. Первая редакция набора содержала такой контракт (координатор моста), и
    # он честно дал HEALTHY резиденту, чей артефакт не двигался четверо суток.
    if absence == 'FAILURE' and not (contract.get('purpose_signal') or {}).get('path'):
        raise ContractError(
            f'{contract.get("label")}: отсутствие выхода объявлено провалом, но признак '
            f'назначения не назван — такой контракт проверяет только существование')
    root = Path(production_root)
    checks, verdicts = [], []

    # 1. НАЗНАЧЕНИЕ идёт ПЕРВЫМ: его возраст нужен, чтобы судить о свежести кода выхода.
    purpose = contract.get('purpose_signal') or {}
    purpose_age = None
    if purpose.get('path'):
        # Артефакт может лежать ВНЕ прод-дерева (координатор моста — другой репозиторий).
        # Корень тогда объявляется явно; угадывать его запрещено.
        base = Path(purpose['root']).expanduser() if purpose.get('root') else root
        target = base / purpose['path']
        purpose_age = _age_hours(target, now=now)
        limit = purpose.get('max_age_hours')
        if purpose_age is None:
            meaning = {'FAILURE': UNHEALTHY, 'HEALTHY_WHEN_ABSENT': HEALTHY,
                       'ZERO_EVENTS': HEALTHY, 'NOT_MEASURED': NOT_MEASURED}[absence]
            checks.append({'check': 'purpose_signal', 'verdict': meaning,
                           'why': f'артефакта нет; объявлено, что отсутствие означает '
                                  f'{absence}',
                           'path': purpose['path']})
            verdicts.append(meaning)
        elif limit is None:
            checks.append({'check': 'purpose_signal', 'verdict': NOT_MEASURED,
                           'why': 'предельный возраст признака назначения не объявлен',
                           'age_hours': purpose_age})
            verdicts.append(NOT_MEASURED)
        else:
            limit = float(limit)
            # Порог предупреждения объявляется компонентом; по умолчанию — доля предела.
            warn_at = purpose.get('warn_age_hours')
            warn_at = float(warn_at) if warn_at is not None else limit * 0.75
            if purpose_age > limit:
                v = UNHEALTHY
                why = (f'признак назначения НЕ двигался {purpose_age} ч при пределе '
                       f'{limit} ч — компонент существует, но своего дела не делает')
            elif purpose_age > warn_at:
                v = DEGRADED
                why = (f'признак назначения свеж ({purpose_age} ч ≤ {limit} ч), но уже '
                       f'старше порога предупреждения {warn_at} ч')
            else:
                v = HEALTHY
                why = f'признак назначения свеж ({purpose_age} ч ≤ {warn_at} ч)'
            checks.append({'check': 'purpose_signal', 'verdict': v, 'why': why,
                           'path': purpose['path'], 'age_hours': purpose_age,
                           'warn_age_hours': warn_at, 'max_age_hours': limit})
            verdicts.append(v)

    # 2. Последний успех — с временем. И с проверкой, не УСТАРЕЛ ли он сам.
    success = contract.get('success') or {}
    log_name = success.get('log') or f'spa_{label.split(".")[-1]}.log'
    exit_info = read_last_exit(Path(log_root) / log_name,
                               agent=success.get('agent_name'))
    if exit_info['state'] == 'MEASURED':
        exit_age = None
        try:
            ts = datetime.strptime(exit_info['at'], '%Y-%m-%dT%H:%M:%SZ').replace(
                tzinfo=timezone.utc)
            exit_age = round((now - ts).total_seconds() / 3600.0, 3)
        except ValueError:
            pass
        # Код выхода ИСТОРИЧЕН. Если после него компонент успешно дописал свой артефакт,
        # этот код описывает ПЕРЕЖИТЫЙ прогон и решать им сегодняшний вердикт нельзя.
        # Замер на живой системе: сборка кокпита вернула 2 в 21:46, затем дважды успешно
        # отработала в 06:36 — и первая редакция объявила её нездоровой по старому коду.
        superseded = (exit_age is not None and purpose_age is not None
                      and purpose_age < exit_age)
        if superseded:
            checks.append({
                'check': 'last_exit', 'verdict': NOT_MEASURED,
                'why': f'код {exit_info["exit_code"]} записан {exit_age} ч назад, а '
                       f'признак назначения свежее ({purpose_age} ч): этот код описывает '
                       f'пережитый прогон и сегодняшний вердикт не решает',
                'exit_code': exit_info['exit_code'], 'at': exit_info['at'],
                'age_hours': exit_age, 'superseded_by_purpose_signal': True})
            verdicts.append(NOT_MEASURED)
        else:
            v, why = classify_exit(exit_info['exit_code'], contract)
            checks.append({'check': 'last_exit', 'verdict': v, 'why': why,
                           'exit_code': exit_info['exit_code'], 'at': exit_info['at'],
                           'age_hours': exit_age})
            verdicts.append(v)
    else:
        checks.append({'check': 'last_exit', 'verdict': NOT_MEASURED,
                       'why': exit_info['reason']})
        verdicts.append(NOT_MEASURED)

    # 2b. Резидентность — ТОЛЬКО для тех, кто обязан быть резидентом.
    liveness = contract.get('liveness') or {}
    if liveness.get('expected'):
        expected = str(liveness['expected']).upper()
        has_pid = liveness.get('has_pid')
        if expected == 'SCHEDULED':
            checks.append({'check': 'liveness', 'verdict': NOT_APPLICABLE,
                           'why': 'расписанное задание между запусками не работает ПО '
                                  'ПОСТРОЕНИЮ; спрашивать у него о резидентности — '
                                  'спрашивать не то'})
            verdicts.append(NOT_APPLICABLE)
        elif has_pid is None:
            checks.append({'check': 'liveness', 'verdict': NOT_MEASURED,
                           'why': 'наличие процесса не подано — не измерено'})
            verdicts.append(NOT_MEASURED)
        else:
            checks.append({'check': 'liveness',
                           'verdict': HEALTHY if has_pid else UNHEALTHY,
                           'why': ('резидент держит процесс' if has_pid else
                                   'резидент объявлен, процесса нет')})
            verdicts.append(HEALTHY if has_pid else UNHEALTHY)

    # 3. Слепые состояния: наблюдение есть, доверия нет.
    blind = contract.get('blind_values') or []
    for rule in blind:
        path, field = rule.get('path'), rule.get('field')
        if not path or not field:
            continue
        target = root / path
        try:
            doc = json.loads(target.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            checks.append({'check': f'blind:{field}', 'verdict': NOT_MEASURED,
                           'why': 'файл слепого состояния не прочитан'})
            verdicts.append(NOT_MEASURED)
            continue
        node = doc
        for part in str(field).split('.'):
            node = node.get(part) if isinstance(node, dict) else None
        if node == rule.get('blind_when'):
            checks.append({
                'check': f'blind:{field}', 'verdict': BLIND,
                'why': rule.get('why') or (f'{field}={node!r}: наблюдение есть, '
                                           f'доверять ему нельзя')})
            verdicts.append(BLIND)
        else:
            checks.append({'check': f'blind:{field}', 'verdict': HEALTHY,
                           'why': f'{field}={node!r} — не слепое состояние'})
            verdicts.append(HEALTHY)

    # Свод: худшее побеждает, но BLIND и NOT_MEASURED не превращаются в провал.
    # Порядок свода объявлен: провал сильнее всего, затем слепота, затем деградация.
    # NOT_APPLICABLE НЕ влияет на свод — это ответ «вопрос не тот», а не оценка.
    weighing = [v for v in verdicts if v != NOT_APPLICABLE]
    if UNHEALTHY in weighing:
        final = UNHEALTHY
    elif BLIND in weighing:
        final = BLIND
    elif DEGRADED in weighing:
        final = DEGRADED
    elif not weighing:
        final = NOT_APPLICABLE
    elif NOT_MEASURED in weighing and HEALTHY not in weighing:
        final = NOT_MEASURED
    else:
        final = HEALTHY        # часть измерена и здорова, часть не спрашивали
    return {
        'schema': SCHEMA,
        'label': label,
        'tier': contract.get('tier'),
        'verdict': final,
        'checks': checks,
        'output_absence_means': absence,
        'owner': contract.get('owner'),
        'measured_at': now.isoformat(),
        'existence_is_not_success': True,
        'note': ('вердикт складывается из последнего выхода, признака НАЗНАЧЕНИЯ и '
                 'слепых состояний; существование процесса успехом не считается'),
    }


def build_health(contracts, *, production_root, now=None, log_root='/tmp'):
    """Свод по объявленным контрактам. Необъявленные сущности сюда не попадают —
    и это честно: контракт, которого нет, вердикта не даёт."""
    now = now or _now()
    rows = [evaluate(c, production_root=production_root, now=now, log_root=log_root)
            for c in contracts or ()]
    counts = {v: sum(1 for r in rows if r['verdict'] == v) for v in VERDICTS}
    return {
        'degraded': [r['label'] for r in rows if r['verdict'] == DEGRADED],
        'schema': 'health_summary/1',
        'measured_at': now.isoformat(),
        'declared_contracts': len(rows),
        'entities': rows,
        'counts': counts,
        'unhealthy': [r['label'] for r in rows if r['verdict'] == UNHEALTHY],
        'blind': [r['label'] for r in rows if r['verdict'] == BLIND],
        'no_synthetic_score': True,
        'score_note': ('единого числа здоровья здесь нет намеренно: шесть состояний '
                       'отвечают на разные вопросы, и свернуть их в одну оценку значило '
                       'бы потерять ровно то различие, ради которого они введены'),
        'coverage_note': ('измеряется ТОЛЬКО то, для чего объявлен контракт; остальные '
                          'сущности остаются НЕ ИЗМЕРЕННЫМИ, и это не то же, что '
                          'здоровыми'),
    }
