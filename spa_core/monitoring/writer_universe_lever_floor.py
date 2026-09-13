"""ЧТО РЕАЛЬНО поднимает дешёвый рычаг `writer_universe` (заказ #596/G10).

Заказ, оставленный в хвосте [ADR-375] по стоячему приказу владельца «Portfolio CIO»:

> Четыре заказа подряд (G6→G9) мерили СЛЕПОТУ входов и её цену, и ряд сошёлся:
> цена $195 000.00 · рычаг преимущественно наш · знаменатель 16→22 дн. · раскладка
> подтверждена. Заказ G10: **чего стоит рычаг ``writer_universe`` в СТРОКАХ КОДА и
> в риске, а не в долларах и днях.** Он нужен КАЖДОМУ из восьми дней и в обеих
> единицах вышел самым дешёвым; из этого читатель уже дважды сделал вывод «начать
> с него». Но ни один из четырёх приборов не спросил, **существует ли та строка
> отсечения по ``universe`` у писателя как правка** — ADR-290 назвал её возможной,
> а не написанной, и класс объявлен ПОТОЛКОМ ровно потому, что запись молчит о
> существовании живой ставки у ноги вне книг. Вопрос: **сколько ног класса
> ``writer_universe`` имели бы живую ставку, будь строка написана, — измеренное по
> ``POLLED_ADAPTERS`` и истории фидов, а не по потолку?**

## Предмет ровно один

**Доллары класса ``writer_universe``, разделённые по тому, СУЩЕСТВОВАЛ ЛИ у ноги
материал в истории фидов на нужный форвардный день.** Не причина слепоты (предмет
``unevidenced_leg_causes``, заказ #543). Не доля слепого оборота (предмет
``unobserved_turnover_dependence``, заказ #587). Не раскладка по рычагам (предмет
``unobserved_leg_remedy_class``, заказ #590) и не её пересчёт по одному форвардному
дню (``remedy_class_single_forward_day``, заказ #592). Все четыре берутся ССЫЛКОЙ и
здесь не пересчитываются.

## Почему вопрос не тот же, что у соседа #544

``journal_backfill_material`` спрашивает, **есть ли чем закрыть уже написанную
строку журнала ЗАДНИМ ЧИСЛОМ**, и меряет это по всем отсечённым парам. Здесь
вопрос обращён ВПЕРЁД и сужен до одного класса рычага: **не пуст ли потолок**, на
котором стои́т вывод «начинать с дешёвой строки у писателя». Ответы могут
расходиться, и ни один не выводится из другого.

## Три исхода у КАЖДОЙ пары, и они не сливаются (инв. #17)

============================ ==================================================
``material``                 ключ есть в ряду И в ряду есть точка того дня ⇒
                             строке писателя было бы ЧТО записать
``gap``                      ключ в ряду есть, точки того дня нет ⇒ фид молчал
                             ИМЕННО в тот день (конвенция ряда: пропуск остаётся
                             пропуском, накопитель не интерполирует)
``never_live``               ключ есть у СЕГОДНЯШНЕГО производителя ряда
                             (``adapter_status.json``), а в ряду нет НИ ОДНОЙ его
                             точки за всю историю накопителя ⇒ живой ставки не
                             было ни разу, и строка писателя не поднимет доллар
                             НИ ПРИ КАКОМ состоянии нашего кода
``outside_producer``         ключа нет и у производителя ⇒ **НЕ ИЗМЕРЕНО**:
                             отсутствие ключа у него не есть отсутствие фида
``outside_window``           форвардный день вне окна ряда ⇒ **НЕ ИЗМЕРЕНО**:
                             день до начала накопления НЕ читается как «фид молчал»
============================ ==================================================

Ноль пар с материалом и ноль пар вообще — РАЗНЫЕ исходы, и второй не выдаётся за
первый.

## Что материал ДОКАЗЫВАЕТ и чего НЕ доказывает

Направление доказательства здесь **несимметрично**, и в этом вся ценность замера.

* ``material`` — условие НЕОБХОДИМОЕ, но не достаточное: точка ряда доказывает,
  что у производителя в тот день было конечное число, и НЕ доказывает, что оно
  прошло бы пробу ``apy_sources[p] == "live"`` у писателя журнала. Провенанс
  принадлежит значению, а не дороге ([ADR-302], [ADR-303]), и накопитель берёт
  ``live_apy``, а при ОТСУТСТВИИ ключа — ``apy``. Поэтому доллары с материалом
  остаются ВОЗМОЖНЫМИ, а не поднятыми;
* ``never_live`` и ``gap`` — условие необходимое НЕ выполнено, и это доказательство
  в ОТРИЦАТЕЛЬНУЮ сторону: писать было нечего, значит строка отсечения по
  ``universe`` этот доллар не поднимает. Здесь потолок доказанно ПУСТ.

Поэтому прибор докладывает две величины отдельно и ни одну не выводит из другой:
``material_usd`` (возможные) и ``proven_empty_usd`` (доказанно не поднимаемые).

## Правило подъёма дня — ЧУЖОЕ, и взято целиком

День возвращается, если существует форвардный день, на котором материал есть у
**ВСЕХ** ног, блокирующих ИМЕННО в нём. Это правило одного форвардного дня
[ADR-371]/[ADR-375], а не собственное изобретение: считать по объединению
форвардных дней значило бы объявить поднятым день, у которого ни на одном дне
полного набора ставок не собирается.

## ADVISORY

``POLLED_ADAPTERS``, пины, писатель журнала, накопитель ряда, ``hit_rate``,
``MIN_HIT_RATE``, ``TriggerParams``, пороги RiskPolicy v1.0, стоп-кран, живой трек
и ``landing/`` НЕ трогаются. Капитал не сдвинут. Прибор только ЧИТАЕТ и делит уже
измеренные доллары по наличию материала.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from spa_core.monitoring import journal_backfill_material as _jbm
from spa_core.monitoring import unobserved_leg_remedy_class as _g7
from spa_core.utils.observation import observed

log = logging.getLogger(__name__)

OUTPUT_FILENAME = "writer_universe_lever_floor.json"
VERSION = "writer-universe-lever-floor-v1"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

SERIES_FILENAME = "apy_series_daily.json"
PRODUCER_FILENAME = "adapter_status.json"

#: Рычаг, про который спрашивает заказ. Другие классы прибор не трогает вовсе.
SUBJECT_REMEDY = _g7.REMEDY_WRITER_UNIVERSE

# ── исходы пары ───────────────────────────────────────────────────────────
PAIR_MATERIAL = "material"
PAIR_GAP = "gap"
PAIR_NEVER_LIVE = "never_live"
PAIR_OUTSIDE_PRODUCER = "outside_producer"
PAIR_OUTSIDE_WINDOW = "outside_window"
PAIR_ROW_UNREADABLE = "series_row_unreadable"

#: Исходы, при которых материала НЕТ и это ИЗМЕРЕНО (доказательство в минус).
PROVEN_EMPTY = (PAIR_GAP, PAIR_NEVER_LIVE)
#: Исходы, при которых сказать нечего. Нулём они НЕ становятся (инв. #17).
UNMEASURED_OUTCOMES = (PAIR_OUTSIDE_PRODUCER, PAIR_OUTSIDE_WINDOW,
                       PAIR_ROW_UNREADABLE)

_ADVISORY = ("POLLED_ADAPTERS, пины, писатель журнала, накопитель ряда, hit_rate, "
             "MIN_HIT_RATE, TriggerParams, пороги RiskPolicy v1.0, стоп-кран, живой "
             "трек и landing/ НЕ трогаются — прибор только делит уже измеренные "
             "доллары по наличию материала в истории фидов")

#: Границы утверждения — В АРТЕФАКТ, а не только в шапку модуля: читатель отчёта
#: шапку не открывает, а именно он переносит число в решение о починке.
WHAT_IT_DOES_NOT_PROVE = [
    "не обещает, что доллар с материалом будет поднят: точка ряда доказывает "
    "конечное число у производителя, а НЕ провенанс `live` у писателя журнала "
    "(ADR-302) — направление доказательства здесь одностороннее",
    "не объявляет ответ G7 неверным: у соседа свой вопрос — «какой рычаг нужен "
    "ноге», и на него его ответ верен. Здесь меряется, ПУСТ ли потолок одного "
    "из его классов",
    "не пересчитывает ни цену слепоты, ни раскладку по рычагам: доллары и классы "
    "взяты у соседей #587/#590/#592 как есть",
    "не судит о днях, у которых нет ни одной пары класса `writer_universe`: они "
    "не «подняты» и не «не подняты», они вне предмета",
    "не утверждает, что HOLD на отвергнутых днях был неправ, и исход дня не "
    "пересчитывает",
    "не меряет, написана ли строка отсечения по `universe` в коде писателя: "
    "предмет — цена рычага, а не его существование как правки",
    "не различает у `gap` две причины: окно ряда ОБЩЕЕ для всех ключей, поэтому "
    "день, в который протокол ещё не попадал к производителю вовсе, неотличим "
    "здесь от дня, в который производитель его видел и живого числа не получил. "
    "Сегодняшний `adapter_status.json` о СОСТАВЕ прошлых дней не говорит, и "
    "прибор его не домысливает — на замере 13.09 `gap` не встретился ни разу, "
    "поэтому вопрос не повлиял на ответ, но обязан быть назван",
]

# ── исходы, которые НЕ измеряются ────────────────────────────────────────
NO_G7 = ("сосед `unobserved_leg_remedy_class` не дал разложенных дней — класс "
         "`writer_universe` неоткуда взять, и это НЕ «класс пуст»")
NO_SERIES = (f"`{SERIES_FILENAME}` не прочитан или не той формы — истории фидов "
             "нет, а «не прочитан» не читается как «фид молчал»")
NO_PRODUCER = (f"`{PRODUCER_FILENAME}` не прочитан или не той формы — вселенная "
               "производителя ряда неизвестна, и отличить «не было живой ставки» "
               "от «ключа не было у производителя» нечем")
NO_SUBJECT = ("ни одной пары класса `writer_universe` — предмет заказа пуст. Это "
              "ИЗМЕРЕННЫЙ ноль, а не отказ: соседи дали дни, класс в них не встретился")


def _load_series(data_dir: Path) -> Optional[Tuple[Dict[str, Set[str]], str, str]]:
    """Ряд как «ключ → множество дат», плюс границы окна. ``None`` = не измерено.

    Форму ряда разбирает ``journal_backfill_material.series_dates`` — то самое
    ОДНО место, которое уже держит правило «что такое точка ряда». Вторая копия
    правила разошлась бы с первой молча, и одна из двух назвала бы материалом то,
    что второй материалом не является.
    """
    try:
        doc = _jbm._read_json(Path(data_dir) / SERIES_FILENAME)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        log.warning("%s не прочитан: %s", SERIES_FILENAME, exc)
        return None
    series = observed(doc if isinstance(doc, dict) else {}, "series", kind=dict)
    if series is None:
        return None
    dates = _jbm.series_dates(series)
    every: Set[str] = set()
    for got in dates.values():
        every |= got
    if not every:
        return None
    return dates, min(every), max(every)


def _producer_keys(data_dir: Path) -> Optional[Set[str]]:
    """Вселенная производителя ряда — ключи ``adapter_status.json``. ``None`` = не измерено.

    Накопитель ``apy_series_accumulator`` обходит ИМЕННО этот файл, поэтому
    вселенную надо брать у него, а не у ``POLLED_ADAPTERS``: ключ, которого
    производитель не видит, в ряд не попадёт ни при каком состоянии фида, и
    читать его отсутствие как «ставки не было» значило бы судить о ноге по
    чужой двери.
    """
    try:
        doc = _jbm._read_json(Path(data_dir) / PRODUCER_FILENAME)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        log.warning("%s не прочитан: %s", PRODUCER_FILENAME, exc)
        return None
    adapters = observed(doc if isinstance(doc, dict) else {}, "adapters", kind=dict)
    if adapters is None:
        return None
    return {str(k) for k in adapters} or None


def _resolve_key(protocol: str, *, series: Dict[str, Set[str]],
                 twins: Dict[str, List[str]]) -> Tuple[str, Optional[str]]:
    """Под каким именем нога живёт в ряду: своим либо ДОКАЗАННОГО близнеца.

    Близнец берётся только у канонического сторожа второй записи (равные суммы,
    один-к-одному) — тот же источник, что у соседа #590. Догадываться о родстве
    по виду имени запрещено: `pendle` и `pendle_pt_susde` похожи, и родство их
    записью НЕ доказано, а цена ошибки здесь — половина ответа.
    """
    if protocol in series:
        return protocol, None
    for twin in twins.get(protocol, []):
        if twin in series:
            return twin, twin
    return protocol, None


def _pair_outcome(protocol: str, forward_date: str, *, series: Dict[str, Set[str]],
                  producer: Set[str], twins: Dict[str, List[str]],
                  window: Tuple[str, str]) -> dict:
    """Исход ОДНОЙ пары «форвардный день × нога» — с названной опорой."""
    key, via_twin = _resolve_key(protocol, series=series, twins=twins)
    low, high = window
    if not (low <= forward_date <= high):
        return {"outcome": PAIR_OUTSIDE_WINDOW, "key": key, "via_twin": via_twin,
                "why": (f"форвардный день вне окна ряда {low}..{high} — до начала "
                        "накопления; «нет точки» здесь НЕ значит «фид молчал»")}
    if key in series:
        # Ключ в ряду ЕСТЬ, а разобранных дат у него НЕТ НИ ОДНОЙ — это «строку
        # прочитать не удалось», а не «фид молчал каждый день». Канонический
        # разборщик оставляет такой ключ с пустым множеством НАМЕРЕННО, чтобы
        # два состояния не схлопнулись (см. `series_points`); схлопнуть их здесь
        # значило бы объявить потолок доказанно пустым на неразобранной строке —
        # ровно тот дефект, ради которого прибор и написан.
        if not series[key]:
            return {"outcome": PAIR_ROW_UNREADABLE, "key": key, "via_twin": via_twin,
                    "why": (f"ключ `{key}` в ряду есть, но ни одной разобранной "
                            "точки у него нет — строка ряда не прочитана, и это НЕ "
                            "«фид молчал»")}
        if forward_date in series[key]:
            return {"outcome": PAIR_MATERIAL, "key": key, "via_twin": via_twin,
                    "why": (f"в ряду есть точка {forward_date} под ключом `{key}`"
                            + (f" (ДОКАЗАННЫЙ близнец ноги)" if via_twin else "")
                            + " ⇒ строке писателя было бы что записать")}
        return {"outcome": PAIR_GAP, "key": key, "via_twin": via_twin,
                "why": (f"ключ `{key}` в ряду есть, точки {forward_date} нет ⇒ фид "
                        "молчал именно в тот день (накопитель не интерполирует)")}
    if key in producer or protocol in producer:
        return {"outcome": PAIR_NEVER_LIVE, "key": key, "via_twin": via_twin,
                "why": (f"ключ `{protocol}` есть у производителя ряда "
                        f"({PRODUCER_FILENAME}), а в ряду нет НИ ОДНОЙ его точки за "
                        "всю историю накопителя ⇒ живой ставки не было ни разу, и "
                        "строка у писателя этот доллар не поднимет")}
    return {"outcome": PAIR_OUTSIDE_PRODUCER, "key": key, "via_twin": via_twin,
            "why": (f"ключа `{protocol}` нет и у производителя ряда — отсутствие "
                    "ключа у него НЕ есть отсутствие фида")}


def measure(data_dir: Path, *, now: Optional[datetime] = None, **_ignored) -> dict:
    """Разделить доллары класса ``writer_universe`` по наличию материала. Только чтение.

    ``_ignored`` — совместимость с зовущей ступенью переписей, которая передаёт
    общие для всех приборов ключи. Глотать их МОЛЧА безопасно ровно потому, что ни
    один из них не участвует в замере: появись здесь значащий параметр, он обязан
    быть назван явно, а не прийти через эту дверь.
    """
    data_dir = Path(data_dir)
    doc: dict = {
        "version": VERSION,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "subject": ("доллары класса `writer_universe`, разделённые по наличию "
                    "материала в истории фидов (заказ #596/G10 приказа «Portfolio CIO»)"),
        "advisory": _ADVISORY,
        "what_it_does_not_prove": list(WHAT_IT_DOES_NOT_PROVE),
    }

    def unmeasured(why: str) -> dict:
        # `unmeasured_days` ПУСТ, а не отсутствует: отказ ГЛОБАЛЬНЫЙ и назван в
        # `unmeasured_reason`, ни один день по отдельности не отвергался.
        doc.update({"status": STATUS_UNMEASURED, "unmeasured_reason": why,
                    "answer": None, "per_day": [],
                    "population": {"measured_days": 0, "unmeasured_days": [],
                                   "subject_pairs": 0},
                    "findings": [f"[НЕ ИЗМЕРЕНО] {why}"]})
        return doc

    loaded = _load_series(data_dir)
    if loaded is None:
        return unmeasured(NO_SERIES)
    series, win_lo, win_hi = loaded
    doc["series_window"] = {"from": win_lo, "to": win_hi, "keys": len(series)}

    producer = _producer_keys(data_dir)
    if producer is None:
        return unmeasured(NO_PRODUCER)
    doc["producer_keys"] = len(producer)

    base = _g7.measure(data_dir, now=now)
    doc["g7_status"] = base.get("status")
    # «Ключа `per_day` сосед не дал» и «дал пустой список» — РАЗНЫЕ ответы, и
    # подстановка `or []` слила бы их в один. Первое означает, что сосед отказал
    # или сменил форму; второе — что дней слепого оборота в истории нет вовсе.
    base_days = observed(base, "per_day", kind=list)
    if base_days is None:
        return unmeasured(f"{NO_G7}: ключа `per_day` в ответе нет "
                          f"(вердикт соседа: {base.get('status')})")
    if not base_days:
        return unmeasured(f"{NO_G7}: список дней ПУСТ "
                          f"(вердикт соседа: {base.get('status')})")

    # Близнецы: их отсутствие бывает ДВУХ родов, и оба меняют ответ. Сосед мог
    # близнецов не мерить вовсе (сторож второй записи отказал) — тогда нога с
    # переименованием уедет в `never_live` по ЧУЖОМУ отказу, а не по наблюдению;
    # либо измерить и не найти ни одного. Подстановка `or {}` выдала бы первое
    # за второе, поэтому род записывается в артефакт (инв. #17).
    twin_doc = observed(base, "twin_keys", kind=dict)
    twins_measured = bool(twin_doc.get("measured")) if twin_doc is not None else False
    twin_pairs = observed(twin_doc, "pairs", kind=dict) if twin_doc is not None else None
    twins: Dict[str, List[str]] = dict(twin_pairs) if twin_pairs is not None else {}
    doc["twins_measured"] = twins_measured
    doc["twin_pairs_used"] = {k: v for k, v in twins.items() if k not in series}

    per_day: List[dict] = []
    unmeasured_days: List[dict] = []
    subject_pairs = 0
    outcome_counts: Dict[str, int] = {k: 0 for k in
                                      (PAIR_MATERIAL, PAIR_GAP, PAIR_NEVER_LIVE,
                                       PAIR_OUTSIDE_PRODUCER, PAIR_OUTSIDE_WINDOW,
                                       PAIR_ROW_UNREADABLE)}
    material_usd = proven_empty_usd = unmeasured_usd = 0.0

    for day in base_days:
        date = str(day.get("cycle_date"))
        gross = day.get("unpriced_gross_usd")
        # форвардный день → {нога: исход}; ТОЛЬКО пары предметного класса
        by_forward: Dict[str, Dict[str, dict]] = {}
        # Ключа `legs`/`pairs` у соседа может не быть вовсе — это НЕ «ног нет».
        # Пустой список ног читается как «класса в дне не встретилось» и ведёт
        # к пропуску дня вне предмета; отсутствие ключа — отказ формы, и день
        # обязан попасть в НЕИЗМЕРЕННЫЕ, а не исчезнуть молча.
        day_legs = observed(day, "legs", kind=list)
        if day_legs is None:
            unmeasured_days.append({
                "cycle_date": date,
                "reason": "у дня нет ключа `legs` — перечислить ноги нечем"})
            continue
        for leg in day_legs:
            protocol = str(leg.get("protocol"))
            leg_pairs = observed(leg, "pairs", kind=list)
            if leg_pairs is None:
                unmeasured_days.append({
                    "cycle_date": date,
                    "reason": f"у ноги {protocol} нет ключа `pairs` — "
                              "форвардные дни неоткуда взять"})
                by_forward = {}
                break
            for pair in leg_pairs:
                if str(pair.get("remedy")) != SUBJECT_REMEDY:
                    continue
                fdate = str(pair.get("forward_date"))
                out = _pair_outcome(protocol, fdate, series=series, producer=producer,
                                    twins=twins, window=(win_lo, win_hi))
                by_forward.setdefault(fdate, {})[protocol] = out
                outcome_counts[out["outcome"]] += 1
                subject_pairs += 1

        if not by_forward or gross is None:
            # День без пар предмета — ВНЕ предмета, а не «не измерен»: у него свои
            # рычаги, и записывать его в отказ значило бы раздуть знаменатель.
            continue

        # Правило подъёма — чужое (ADR-371/ADR-375): нужен ОДИН форвардный день,
        # на котором материал есть у ВСЕХ ног, блокирующих именно в нём.
        good = sorted(f for f, legs in by_forward.items()
                      if all(o["outcome"] == PAIR_MATERIAL for o in legs.values()))
        blind = sorted({p for legs in by_forward.values() for p, o in legs.items()
                        if o["outcome"] in UNMEASURED_OUTCOMES})
        if good:
            verdict = "material"
            material_usd += float(gross)
        elif blind:
            # Хоть одна пара не измерена ⇒ о ДНЕ сказать нечего: объявить его
            # доказанно пустым значило бы выдать «не измерено» за наблюдение.
            verdict = "unmeasured"
            unmeasured_usd += float(gross)
            unmeasured_days.append({
                "cycle_date": date,
                "reason": (f"ноги {', '.join(blind)} не измерены по ряду — "
                           "доказать пустоту потолка нечем")})
        else:
            verdict = "proven_empty"
            proven_empty_usd += float(gross)

        per_day.append({
            "cycle_date": date,
            "unpriced_gross_usd": gross,
            "verdict": verdict,
            "forward_days_with_full_material": good,
            "forward_days_examined": sorted(by_forward),
            "legs": sorted({p for legs in by_forward.values() for p in legs}),
            "outcomes": {f: {p: o["outcome"] for p, o in sorted(legs.items())}
                         for f, legs in sorted(by_forward.items())},
            "why": sorted({o["why"] for legs in by_forward.values()
                           for o in legs.values()}),
        })

    if not subject_pairs:
        doc.update({"status": STATUS_OK, "answer": None, "per_day": [],
                    "population": {"measured_days": 0, "unmeasured_days": [],
                                   "subject_pairs": 0},
                    "findings": [f"[ОТВЕТ] {NO_SUBJECT}"]})
        doc["counts"] = {"critical": 0, "warn": 0, "info": 1, "unchecked": 0}
        return doc

    total = material_usd + proven_empty_usd + unmeasured_usd
    doc["per_day"] = per_day
    # `measured_days` считается ПО ВЕРДИКТУ, а не вычитанием: в `unmeasured_days`
    # попадают и дни, отвергнутые ПО ФОРМЕ чужого ответа (нет ключа `legs`/`pairs`),
    # а их в `per_day` нет вовсе — вычитание уводило бы счёт измеренных дней вниз,
    # вплоть до отрицательного, то есть врало бы о полноте населения.
    doc["population"] = {
        "subject_pairs": subject_pairs,
        "measured_days": sum(1 for d in per_day if d["verdict"] != "unmeasured"),
        "unmeasured_days": unmeasured_days,
        "days_with_subject": len(per_day),
        "pair_outcomes": outcome_counts,
    }
    doc["answer"] = {
        "measured": True,
        "subject_usd": round(total, 2),
        "material_usd": round(material_usd, 2),
        "material_pct": round(100.0 * material_usd / total, 2) if total else None,
        "proven_empty_usd": round(proven_empty_usd, 2),
        "proven_empty_pct": round(100.0 * proven_empty_usd / total, 2) if total else None,
        "unmeasured_usd": round(unmeasured_usd, 2),
        "pair_outcomes": dict(outcome_counts),
    }
    doc["status"] = _status(doc)
    doc["findings"] = _findings(doc)
    return doc


def _status(doc: dict) -> str:
    """CRITICAL, когда потолок ДОКАЗАННО пуст хоть на доллар.

    Именно этот исход опровергает вывод «начинать с дешёвой строки»: доллар,
    у которого материала не было, не поднимется ни при каком состоянии нашего
    кода, и очередь рычагов для него надо строить заново.

    Числа берутся ПРЯМЫМ ключом, а не `.get(...) or 0`: подстановка нуля сделала
    бы «ключа нет» неотличимым от «измерено и равно нулю» (инв. #17) — ровно у
    того счёта, который решает вердикт. Отсутствие ключа здесь означает, что
    вызывающий собрал ответ не той формы, и упасть громко правильнее, чем
    объявить OK.
    """
    ans = doc["answer"]
    if ans["proven_empty_usd"] > 0:
        return STATUS_CRITICAL
    if ans["unmeasured_usd"] > 0:
        return STATUS_WARNING
    return STATUS_OK


def _findings(doc: dict) -> List[str]:
    # Те же прямые ключи, что и в `_status`, и по той же причине: отчёт, молча
    # подставивший ноль вместо отсутствующего счёта, врал бы читателю в сторону
    # нормы — а именно он переносит число в решение о починке.
    ans = doc["answer"]
    pop = doc["population"]
    out: List[str] = []
    out.append(
        f"[ОТВЕТ] из ${ans['subject_usd']:,.2f} класса `writer_universe` "
        f"материал в истории фидов подпирает ${ans['material_usd']:,.2f} "
        f"({ans['material_pct']} %), доказанно НЕ подпирает "
        f"${ans['proven_empty_usd']:,.2f} ({ans['proven_empty_pct']} %), "
        f"не измерено ${ans['unmeasured_usd']:,.2f}")
    out.append(
        "[СТАТУС ЧИСЛА] материал — условие НЕОБХОДИМОЕ и НЕ достаточное: точка ряда "
        "доказывает конечное число у производителя, а не провенанс `live` у писателя "
        "(ADR-302). Доказательство одностороннее, и сильная сторона — отрицательная: "
        "доллар без материала не поднимается строкой у писателя никогда")
    counts = pop["pair_outcomes"]
    out.append("[ПО ПАРАМ] " + " · ".join(
        f"{k}={counts[k]}" for k in
        (PAIR_MATERIAL, PAIR_GAP, PAIR_NEVER_LIVE, PAIR_OUTSIDE_PRODUCER,
         PAIR_OUTSIDE_WINDOW, PAIR_ROW_UNREADABLE)))
    for day in doc["per_day"]:
        out.append(
            f"[ПО ДНЯМ] {day['cycle_date']}: ${day['unpriced_gross_usd']:,.2f} — "
            f"{day['verdict']}; ноги {', '.join(day['legs'])}; форвардных дней "
            f"{len(day['forward_days_examined'])}, с полным материалом "
            f"{len(day['forward_days_with_full_material'])}")
    for bad in pop["unmeasured_days"]:
        out.append(f"[НЕ ИЗМЕРЕНО] {bad['cycle_date']}: {bad['reason']}")
    if ans["proven_empty_usd"] > 0:
        out.append(
            f"[CRITICAL] потолок класса `writer_universe` ДОКАЗАННО пуст на "
            f"${ans['proven_empty_usd']:,.2f}: вывод «начинать с дешёвой "
            f"строки у писателя» на эти доллары не распространяется — материала, "
            f"который строка записала бы, не существовало ни в один нужный день")
    twins = doc["twin_pairs_used"]
    if twins:
        out.append("[ОПОРА] ключ ноги взят у ДОКАЗАННОГО близнеца (равные суммы, "
                   "один-к-одному у сторожа второй записи): "
                   + ", ".join(f"{k}→{'/'.join(v)}" for k, v in sorted(twins.items())))
    win = doc["series_window"]
    out.append(f"[ОПОРА] окно ряда {win['from']}..{win['to']}, ключей "
               f"{win['keys']}; вселенная производителя {doc['producer_keys']} "
               f"ключ(ей) — «нет ключа у производителя» и «не было живой ставки» "
               f"разведены, а не слиты")
    out.append(f"ADVISORY: {_ADVISORY}")
    return out


def format_report(doc: dict) -> List[str]:
    # Прямой ключ: `findings` ставит КАЖДАЯ ветка `measure`, включая отказ, —
    # поэтому его отсутствие есть чужая ошибка формы, а не пустой отчёт, и
    # подставлять вместо неё пустой список значило бы печатать тишину как
    # чистый прогон (инв. #17).
    return list(doc["findings"])


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, **kwargs) -> dict:
    """Форма, которую ждут ступень переписей `findings_bridge` и шаг 0-офис."""
    from spa_core.utils.atomic import atomic_save

    root = root or str(Path(__file__).resolve().parents[2])
    data_dir = Path(root) / "data"
    doc = measure(data_dir, now=now, **kwargs)
    findings = list(doc["findings"])
    doc["overall"] = doc["status"]
    doc["counts"] = {
        "critical": sum(1 for x in findings if x.startswith("[CRITICAL]")),
        "warn": sum(1 for x in findings if x.startswith("[WARNING]")),
        "info": sum(1 for x in findings if x.startswith("[ОТВЕТ")
                    or x.startswith("[СТАТУС ЧИСЛА]") or x.startswith("[ПО ПАРАМ]")
                    or x.startswith("[ПО ДНЯМ]") or x.startswith("[ОПОРА]")),
        # «не измерено» считается ОТДЕЛЬНО от нулей: растворив его, мы сделали бы
        # молчание прибора неотличимым от чистого прогона.
        "unchecked": (1 if doc["status"] == STATUS_UNMEASURED else 0)
                     + sum(1 for x in findings if x.startswith("[НЕ ИЗМЕРЕНО]")),
    }
    if write:
        atomic_save(doc, str(data_dir / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description=("чего РЕАЛЬНО стоит рычаг `writer_universe`: сколько его "
                     "долларов подпёрто материалом в истории фидов "
                     "(заказ #596/G10 приказа «Portfolio CIO»)"))
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    data_dir = (Path(args.data_dir) if args.data_dir
                else Path(os.environ.get("SPA_DATA_DIR")
                          or (Path(__file__).resolve().parents[2] / "data")))
    doc = measure(data_dir)
    if not args.no_write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(data_dir) / OUTPUT_FILENAME))
    for line in format_report(doc):
        print(line)
    return 0 if doc["status"] in (STATUS_OK, STATUS_WARNING) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
