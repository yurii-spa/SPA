"""Раскладка слепого оборота по рычагам под правилом ОДНОГО форвардного дня (заказ #592/G9).

Заказ, оставленный в хвосте ADR-371 по стоячему приказу владельца «Portfolio CIO»:

> G7 приписывает день НАБОРУ рычагов, объединяя классы ног по ВСЕМ их парам;
> замер G8 показал, что день возвращается через ОДИН форвардный день, и на
> 2026-09-06 это меняет адресата: $20 000 числятся за ``key_mismatch`` вместе с
> ``writer_universe``, а на деле поднимаются писателем в одиночку. Вопрос:
> **сколько долларов из $195 000 меняют класс, если рычаг ноги брать не по всем
> её парам, а по тому форвардному дню, которым день РЕАЛЬНО возвращается?**
> Ответ либо подтвердит раскладку 94.87 / 5.13, либо назовёт её смещённой.

## Предмет ровно один

**Те же доллары слепого оборота, разложенные по рычагам под правилом подъёма,
которым день возвращается НА САМОМ ДЕЛЕ.** Не новая цена слепоты (предмет
``unobserved_turnover_dependence``, заказ #587), не дни знаменателя (предмет
``hit_rate_denominator_recovery``, заказ #591: он отвечает в ДНЯХ), не ``hit_rate``
и не суждение о том, был ли HOLD прав.

## Откуда берётся правило, и почему оно не изобретено здесь

Правило подъёма уже написано в дереве и является каноническим:
``unevidenced_leg_causes._structural_recovers`` — «достаточно ОДНОГО forward-дня,
все неоценённые ноги которого выданы», потому что ``_evaluate_verdict`` выносит
вердикт при ``checked >= 1``. Прибор его НЕ переписывает: он зовёт этот самый
предикат и настоящего судью (``_replay_recovers``) как контроль своего ответа.

Отличие от соседа G7 ровно одно и оно арифметическое:

* **G7:** у ноги берётся дешевейший рычаг по ВСЕМ её парам, затем рычаги ног
  ОБЪЕДИНЯЮТСЯ. Это НЕОБХОДИМОЕ условие подъёма — и G8 доказал, что не достаточное:
  нога A чинится через форвардный день D₁, нога B через D₂, и день не возвращается
  ни при каком из них.
* **G9 (здесь):** для КАЖДОГО форвардного дня F берётся набор рычагов ног, блокирующих
  именно в F; ответом дня становится дешевейший из этих наборов. Такой набор
  достаточен по построению — и достаточность ПРОВЕРЯЕТСЯ настоящим судьёй, а не
  предполагается.

## Дешевизна НАБОРА — это порядок, а не измерение, и здесь это сказано вслух

У ноги дешевизна рычага определена в дереве (``_g7.REMEDY_COST_ORDER``: наш код
прежде владельца). У НАБОРА порядка не было, и прибор его не выдумывает молча:
набор сравнивается лексикографически по ``(худший рычаг, размер, вектор рычагов)``,
то есть тем же объявленным порядком, поднятым с рычага на набор.

**Где этот выбор решает ответ — прибор ИЗМЕРЯЕТ, а не оговаривает.** Для каждого дня
считаются наборы, минимальные ПО ВКЛЮЧЕНИЮ. Если такой набор один, ответ дня не
зависит от порядка вовсе. Если их несколько и они несравнимы, вердикт держится на
объявленном порядке — и тогда печатается, во что обошёлся бы противоположный выбор
(``order_sensitivity``). Замер 13.09: несравнимых дней ТРИ, и на них раскладка
«наш код / владелец» ходит с 94.87 / 5.13 до 64.10 / 35.90. Число, молчащее об этом,
выдало бы соглашение за наблюдение.

## Что прибор НЕ делает

Он не пересчитывает цену слепоты, не трогает ``hit_rate``, не объявляет G7 неверным:
у G7 свой вопрос («какой рычаг нужен ноге»), и на него его ответ верен. Смещённым
может оказаться лишь ПЕРЕНОС этого ответа на день — ровно то, что здесь и меряется.

ADVISORY. Только stdlib. Прибор ЧИТАЕТ: ни ``POLLED_ADAPTERS``, ни писателя журнала,
ни ``hit_rate``, ни ``MIN_HIT_RATE``, ни пороги RiskPolicy v1.0, ни стоп-кран, ни
живой трек он не трогает. Живое ``data/`` открывается на запись только ради
собственного артефакта.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

# Соседи зовутся ПО ССЫЛКЕ НА МОДУЛЬ, а не связанными при импорте именами: связанное
# имя есть СНИМОК функции на момент импорта, и подмена канонического правила прошла
# бы мимо нас молча. Так же поступают оба соседа по заказу (ADR-368, ADR-371).
from spa_core.monitoring import unevidenced_leg_causes as _causes
from spa_core.monitoring import unobserved_leg_remedy_class as _g7
from spa_core.monitoring import unobserved_turnover_dependence as _dep
from spa_core.utils.observation import observed

log = logging.getLogger("spa.monitoring.remedy_class_single_forward_day")

OUTPUT_FILENAME = "remedy_class_single_forward_day.json"
VERSION = "remedy-single-forward-day-v1"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

_ADVISORY = ("ADVISORY: `POLLED_ADAPTERS`, писатель журнала, `hit_rate`, "
             "`MIN_HIT_RATE`, пороги RiskPolicy v1.0, стоп-кран и живой трек НЕ "
             "трогаются — прибор только перекладывает уже измеренные доллары по "
             "другому правилу подъёма")

#: Границы утверждения — В АРТЕФАКТ, а не только в шапку модуля: читатель отчёта
#: шапку не открывает, а именно он переносит число в решение о починке.
WHAT_IT_DOES_NOT_PROVE = [
    "не объявляет ответ G7 неверным: у соседа свой вопрос — «какой рычаг нужен "
    "НОГЕ», и на него его ответ верен. Смещённым может быть только ПЕРЕНОС "
    "ответа с ноги на день, и меряется здесь именно он",
    "не обещает, что применённый рычаг поднимет доллар: классы `writer_universe`, "
    "`needs_polling` и `feed_outage` остаются ПОТОЛКОМ (конвенция ADR-300) — "
    "запись молчит о том, существовала ли живая ставка у ноги вне книг",
    "не пересчитывает цену слепоты: доллары взяты у соседа #587 как есть, и "
    "знаменатель $195 000.00 этим прибором не проверяется",
    "не делит доллары дня между рычагами набора: величина дневная, и день "
    "требует ВСЕХ рычагов своего набора сразу",
    "не утверждает, что HOLD на отвергнутых днях был НЕПРАВ, и исход дня не "
    "пересчитывает",
    "не выбирает между несравнимыми наборами САМ: где их несколько, ответ "
    "держится на объявленном порядке цены, и цена этого выбора напечатана "
    "отдельной строкой, а не растворена в итоге",
]

# ──────────────────────────────────────────────────────────────────────────
# исходы, которые НЕ измеряются
# ──────────────────────────────────────────────────────────────────────────
NO_G7 = ("сосед `unobserved_leg_remedy_class` не дал разложенных дней — "
         "сравнивать не с чем, и это НЕ «раскладка совпала»")
NO_CAUSES = ("сосед `unevidenced_leg_causes` не дал пар «форвардный день × нога» — "
             "набор рычагов форвардного дня неоткуда взять")
NO_POLLED = ("`POLLED_ADAPTERS` не прочитан — опрашиваемость ноги неизвестна, а "
             "«не прочитан» не читается как «не опрашивается»")
NO_JOURNAL = ("журнал решений пуст или не прочитан — горизонт дня неизвестен, а "
              "пустой горизонт НЕ читается как «форвардных дней нет»")
DAY_NO_PAIRS = ("у дня нет ни одной блокирующей пары — набор форвардного дня "
                "неоткуда взять, и пустым набором это НЕ читается: пустой набор "
                "объявил бы день поднятым БЕЗ единого рычага")
FREE_FORWARD_DAY = ("форвардный день внутри горизонта не несёт ни одной блокирующей "
                    "пары ⇒ день восстанавливался бы БЕЗ рычагов, но судья его "
                    "отверг: два чтения одного дня спорят")
RECOVERY_DISAGREES = ("выданный набор не вернул день настоящему судье — правило "
                      "подъёма прибора и `_evaluate_verdict` разошлись")
NECESSITY_FAILED = ("набор оказался ИЗБЫТОЧНЫМ: день возвращается и без одной из "
                    "его пар, то есть набор не минимален по построению")


def _set_cost(remedies: FrozenSet[str], order: Sequence[str]) -> tuple:
    """Цена НАБОРА: объявленный порядок рычага, поднятый с рычага на набор.

    Лексикографически ``(худший рычаг, размер, вектор)``. Это ПОРЯДОК, а не замер,
    и там, где он решает ответ, прибор печатает цену выбора (``order_sensitivity``).
    """
    idx = {r: i for i, r in enumerate(order)}
    # Рычаг вне объявленного порядка — не «самый дешёвый по умолчанию»: он худший,
    # иначе неизвестный класс молча выиграл бы у известных.
    ranks = sorted(idx.get(r, len(order)) for r in remedies)
    return (max(ranks) if ranks else len(order), len(ranks), tuple(ranks))


def _minimal_by_inclusion(sets: Set[FrozenSet[str]]) -> List[FrozenSet[str]]:
    """Наборы, у которых нет СТРОГО меньшего собрата.

    Ответ дня не зависит от порядка цены тогда и только тогда, когда такой набор
    ОДИН: единственный минимальный по включению выигрывает у любого монотонного
    порядка. Несколько несравнимых ⇒ вердикт держится на соглашении, и это
    обязано быть сказано, а не подразумеваться.
    """
    return sorted((s for s in sets if not any(o < s for o in sets)),
                  key=lambda s: tuple(sorted(s)))


def _forward_sets(day_pairs: Dict[str, Dict[str, str]]) -> Dict[str, FrozenSet[str]]:
    """Набор рычагов КАЖДОГО форвардного дня: рычаги ног, блокирующих именно в нём."""
    return {f: frozenset(legs.values()) for f, legs in day_pairs.items()}


def measure(data_dir: Path, *, now: Optional[datetime] = None, **_ignored) -> dict:
    """Переложить доллары слепого оборота по правилу одного форвардного дня.

    ``_ignored`` — совместимость с зовущей ступенью переписей, которая передаёт
    общие для всех приборов ключи. Глотать их МОЛЧА безопасно ровно потому, что ни
    один из них не участвует в замере: появись здесь значащий параметр, он обязан
    быть назван явно, а не прийти через эту дверь.
    """
    data_dir = Path(data_dir)
    doc: dict = {
        "version": VERSION,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "subject": ("доллары слепого оборота, разложенные по рычагам под правилом "
                    "ОДНОГО форвардного дня (заказ #592/G9 приказа «Portfolio CIO»)"),
        "advisory": _ADVISORY,
        "what_it_does_not_prove": list(WHAT_IT_DOES_NOT_PROVE),
    }

    def unmeasured(why: str) -> dict:
        # `unmeasured_days` ПУСТ, а не отсутствует: отказ здесь ГЛОБАЛЬНЫЙ и назван
        # в `unmeasured_reason`, ни один день по отдельности не отвергался. Разница
        # существенна — отсутствие перечня означало бы, что о полноте населения
        # сказать нечего, и читается это иначе (инв. #17).
        doc.update({"status": STATUS_UNMEASURED, "unmeasured_reason": why,
                    "answer": None, "per_day": [],
                    "population": {"measured_days": 0, "unmeasured_days": []},
                    "findings": [f"[НЕ ИЗМЕРЕНО] {why}"]})
        return doc

    polled = _g7._polled_keys()
    if polled is None:
        return unmeasured(NO_POLLED)

    base = _g7.measure(data_dir, now=now)
    doc["g7_status"] = base.get("status")
    base_days = observed(base, "per_day", kind=list) or []
    if not base_days:
        return unmeasured(f"{NO_G7} (вердикт соседа: {base.get('status')})")

    causes = _causes.measure(data_dir, now=now)
    doc["causes_status"] = causes.get("status")
    pairs = observed(causes, "attribution", kind=list)
    if pairs is None:
        return unmeasured(f"{NO_CAUSES} (вердикт соседа: {causes.get('status')})")
    horizon = int(causes.get("horizon_days") or 0)
    doc["horizon_days"] = horizon

    history, _bad = _dep._ste.load_history(data_dir)
    if not history:
        return unmeasured(NO_JOURNAL)
    by_date = {str(r.get("cycle_date")): r for r in history}
    order = list(_g7.REMEDY_COST_ORDER)
    forward_of = {str(r.get("cycle_date")): history[i + 1:]
                  for i, r in enumerate(history)}

    twins = (_g7._twin_keys(data_dir).get("pairs") or {})

    # пара «форвардный день × нога» → рычаг, посчитанный КАНОНИЧЕСКИМ правилом соседа
    by_day: Dict[str, Dict[str, Dict[str, str]]] = {}
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        day = str(pair.get("decision_date"))
        fdate = str(pair.get("forward_date"))
        verdict = _g7._pair_remedy(pair, polled=polled, twins=twins,
                                   forward_record=by_date.get(fdate))
        by_day.setdefault(day, {}).setdefault(fdate, {})[str(pair.get("protocol"))] = \
            verdict["remedy"]

    from spa_core.paper_trading.shadow_trigger_eval import _deltas

    per_day: List[dict] = []
    unmeasured_days: List[dict] = []
    for base_day in base_days:
        date = str(base_day.get("cycle_date"))
        gross = base_day.get("unpriced_gross_usd")
        day_pairs = by_day.get(date)
        if not day_pairs or gross is None:
            unmeasured_days.append({"cycle_date": date, "reason": DAY_NO_PAIRS})
            continue

        # КОНТРОЛЬ ПОКРЫТИЯ ГОРИЗОНТА. Форвардный день без блокирующих пар означал бы,
        # что день восстанавливается ДАРОМ, — а судья его отверг. Прочитать такой день
        # как «набор пуст» значило бы объявить весь оборот дня поднятым без рычагов.
        covered = set(day_pairs)
        window = [str(r.get("cycle_date")) for r in forward_of.get(date, [])[:horizon]]
        free = [f for f in window if f not in covered]
        if free:
            unmeasured_days.append({
                "cycle_date": date,
                "reason": f"{FREE_FORWARD_DAY} ({', '.join(free)})"})
            continue

        sets = _forward_sets(day_pairs)
        chosen_f = min(sorted(sets), key=lambda f: _set_cost(sets[f], order))
        chosen = sets[chosen_f]
        minimal = _minimal_by_inclusion(set(sets.values()))

        # КОНТРОЛЬ ДОСТАТОЧНОСТИ — не «по построению», а настоящим судьёй.
        deltas = _deltas(by_date[date])
        forward = forward_of.get(date, [])
        granted = {(chosen_f, leg) for leg in day_pairs[chosen_f]}
        structural = _causes._structural_recovers(deltas, forward, horizon, granted)
        replay = _causes._replay_recovers(by_date[date], forward, horizon, granted)
        if not (structural and replay):
            unmeasured_days.append({
                "cycle_date": date,
                "reason": (f"{RECOVERY_DISAGREES} (структурный={structural}, "
                           f"реплей={replay}, форвардный день {chosen_f})")})
            continue

        # КОНТРОЛЬ НЕОБХОДИМОСТИ. Набор обязан быть минимальным: снятие ЛЮБОЙ его
        # пары обязано ломать подъём. Иначе прибор зачислил бы дню рычаг, без
        # которого тот поднимается, — то есть удорожил бы починку на бумаге.
        redundant = [leg for leg in sorted(day_pairs[chosen_f])
                     if _causes._structural_recovers(
                         deltas, forward, horizon, granted - {(chosen_f, leg)})]
        if redundant:
            unmeasured_days.append({
                "cycle_date": date,
                "reason": f"{NECESSITY_FAILED} ({chosen_f}: {', '.join(redundant)})"})
            continue

        g7_set = frozenset(base_day.get("remedies_required") or ())
        per_day.append({
            "cycle_date": date,
            "unpriced_gross_usd": gross,
            "chosen_forward_date": chosen_f,
            "legs_blocking_there": sorted(day_pairs[chosen_f]),
            "remedies_required": sorted(chosen),
            "g7_remedies_required": sorted(g7_set),
            "changed": sorted(chosen) != sorted(g7_set),
            "lever_owner": ("наш код" if set(chosen) <= _g7.OUR_CODE_REMEDIES
                            else "владелец / фид" if set(chosen) <= _g7.OWNER_REMEDIES
                            else "смешанный — нужны оба"),
            "forward_day_sets": {f: sorted(s) for f, s in sorted(sets.items())},
            "minimal_by_inclusion": [sorted(s) for s in minimal],
            # Ответ дня не зависит от соглашения ровно тогда, когда минимальный
            # набор ОДИН. Печатается у КАЖДОГО дня, а не только у спорных.
            "order_decides": len(minimal) > 1,
            "recovery_control": {"structural": structural, "replay": replay,
                                 "granted_pairs": sorted(f"{d}×{p}" for d, p in granted)},
        })

    doc["per_day"] = per_day
    doc["population"] = {
        "g7_days": len(base_days),
        "measured_days": len(per_day),
        "unmeasured_days": unmeasured_days,
        "attribution_pairs": len(pairs),
        # Тождество истинно ПО ПОСТРОЕНИЮ и само по себе не доказывает ничего; ценно
        # тем, что уронить день МОЛЧА нельзя — падение обязано быть громким.
        "accounting_identity_holds":
            len(per_day) + len(unmeasured_days) == len(base_days),
    }

    if not per_day:
        doc["findings"] = _findings(doc)
        doc.update({"status": STATUS_UNMEASURED, "answer": None,
                    "unmeasured_reason": ("ни один день соседа не переложен — причины "
                                          "названы поимённо в population.unmeasured_days")})
        doc["findings"] = _findings(doc)
        return doc

    total = sum(float(d["unpriced_gross_usd"]) for d in per_day)
    changed = sum(float(d["unpriced_gross_usd"]) for d in per_day if d["changed"])
    our = sum(float(d["unpriced_gross_usd"]) for d in per_day
              if set(d["remedies_required"]) <= _g7.OUR_CODE_REMEDIES)
    owner = total - our
    g7_our = sum(float(d["unpriced_gross_usd"]) for d in per_day
                 if set(d["g7_remedies_required"]) <= _g7.OUR_CODE_REMEDIES)

    by_remedy: Dict[str, float] = {}
    g7_by_remedy: Dict[str, float] = {}
    for day in per_day:
        for remedy in day["remedies_required"]:
            by_remedy[remedy] = by_remedy.get(remedy, 0.0) + float(day["unpriced_gross_usd"])
        for remedy in day["g7_remedies_required"]:
            g7_by_remedy[remedy] = g7_by_remedy.get(remedy, 0.0) + float(day["unpriced_gross_usd"])

    # ЧУВСТВИТЕЛЬНОСТЬ К ОБЪЯВЛЕННОМУ ПОРЯДКУ. Не соперничающая версия ответа, а
    # ЦЕНА соглашения: во что обошлась бы противоположная договорённость там, где
    # минимальные наборы несравнимы. Молчание тут выдало бы соглашение за замер.
    owner_first = [r for r in order if r in _g7.OWNER_REMEDIES] + \
                  [r for r in order if r not in _g7.OWNER_REMEDIES]
    alt_our = 0.0
    for day in per_day:
        sets = {f: frozenset(s) for f, s in day["forward_day_sets"].items()}
        alt = min(sorted(sets), key=lambda f: _set_cost(sets[f], owner_first))
        if set(sets[alt]) <= _g7.OUR_CODE_REMEDIES:
            alt_our += float(day["unpriced_gross_usd"])
    contested = [d["cycle_date"] for d in per_day if d["order_decides"]]

    doc["order_sensitivity"] = {
        "days_where_order_decides": contested,
        "declared_order": order,
        "our_code_pct_declared": round(our / total * 100.0, 2) if total else None,
        "our_code_pct_owner_first": round(alt_our / total * 100.0, 2) if total else None,
        "swing_usd": round(abs(our - alt_our), 2),
        "what_it_proves": (
            "во что обошёлся бы противоположный порядок цены там, где минимальные "
            "по включению наборы несравнимы. Это ЦЕНА СОГЛАШЕНИЯ, а не второй "
            "ответ: порядок «наш код прежде владельца» объявлен в дереве "
            "(`_g7.REMEDY_COST_ORDER`) и здесь не пересматривается"),
    }
    doc["answer"] = {
        "measured": True,
        "blind_turnover_usd": round(total, 2),
        "changed_class_usd": round(changed, 2),
        "changed_class_pct": round(changed / total * 100.0, 2) if total else None,
        "changed_days": [d["cycle_date"] for d in per_day if d["changed"]],
        "our_code_usd": round(our, 2),
        "our_code_pct": round(our / total * 100.0, 2) if total else None,
        "owner_lever_usd": round(owner, 2),
        "owner_lever_pct": round(owner / total * 100.0, 2) if total else None,
        "g7_our_code_pct": round(g7_our / total * 100.0, 2) if total else None,
        "split_confirmed": round(our, 2) == round(g7_our, 2),
        "usd_by_remedy": {k: round(v, 2) for k, v in sorted(by_remedy.items())},
        "g7_usd_by_remedy": {k: round(v, 2) for k, v in sorted(g7_by_remedy.items())},
    }
    doc["status"] = _status(doc)
    doc["findings"] = _findings(doc)
    return doc


def _status(doc: dict) -> str:
    if not (doc.get("population") or {}).get("accounting_identity_holds", True):
        return STATUS_UNMEASURED
    answer = doc.get("answer") or {}
    if not answer.get("measured"):
        return STATUS_UNMEASURED
    if (doc.get("population") or {}).get("unmeasured_days"):
        return STATUS_UNMEASURED
    # Смещение раскладки — находка о ДЕНЬГАХ: читатель G7 переносит её в решение
    # о том, кого просить о починке. Совпадение раскладки при сдвинутых рычагах —
    # тоже находка, но мягче: адресат тот же, цена класса другая.
    if not answer.get("split_confirmed"):
        return STATUS_CRITICAL
    if answer.get("changed_class_usd"):
        return STATUS_WARNING
    return STATUS_OK


def _name_unmeasured_days(pop: dict) -> List[str]:
    """Назвать неизмеренные дни поимённо — либо сказать, что перечня НЕТ.

    ``pop.get(...) or []`` прочитал бы ОТСУТСТВУЮЩИЙ перечень как «таких дней нет»
    и объявил бы население полным, ни разу его не измерив (инв. #17). Пустой
    перечень и отсутствующий — разные утверждения, и второе громче первого.
    """
    rows = observed(pop, "unmeasured_days", kind=list)
    if rows is None:
        return ["[НЕ ИЗМЕРЕНО] отчёт не несёт перечня неизмеренных дней — полно ли "
                "население, на котором посчитана доля, сказать нельзя"]
    return [f"[НЕ ИЗМЕРЕНО] {row['cycle_date']}: {row['reason']}" for row in rows]


def _findings(doc: dict) -> List[str]:
    out: List[str] = []
    pop = doc.get("population") or {}
    answer = doc.get("answer") or {}
    if not answer.get("measured"):
        why = doc.get("unmeasured_reason") or "причина не названа"
        out.append(f"[НЕ ИЗМЕРЕНО] {why}")
        out.extend(_name_unmeasured_days(pop))
        return out

    # Неизмеренные дни называются ДАЖЕ когда ответ есть: при смешанном исходе
    # статус уже UNMEASURED, и молчать о причине значило бы считать «не измерено»,
    # не произнося его (инв. #17). Строка идёт ПЕРВОЙ — читатель обязан увидеть
    # границу населения прежде доли, посчитанной на нём.
    out.extend(_name_unmeasured_days(pop))

    total = answer["blind_turnover_usd"]
    out.append(
        f"[ОТВЕТ] под правилом ОДНОГО форвардного дня класс меняют "
        f"${answer['changed_class_usd']:,.2f} из ${total:,.2f} слепого оборота = "
        f"{answer['changed_class_pct']:.2f} % "
        f"({', '.join(answer['changed_days']) or 'ни одного дня'})")
    verdict = ("ПОДТВЕРЖДЕНА" if answer["split_confirmed"] else "СМЕЩЕНА")
    out.append(
        f"[РАСКЛАДКА] наш код / владелец = {answer['our_code_pct']:.2f} / "
        f"{answer['owner_lever_pct']:.2f} против {answer['g7_our_code_pct']:.2f} / "
        f"{round(100.0 - answer['g7_our_code_pct'], 2):.2f} у G7 ⇒ раскладка {verdict}")
    for remedy in sorted(set(answer["usd_by_remedy"]) | set(answer["g7_usd_by_remedy"])):
        new = answer["usd_by_remedy"].get(remedy, 0.0)
        old = answer["g7_usd_by_remedy"].get(remedy, 0.0)
        mark = "" if new == old else f"  ⇐ сдвиг ${new - old:+,.2f}"
        out.append(f"[ПО РЫЧАГАМ] {remedy}: ${new:,.2f} против ${old:,.2f} у G7{mark}")
    for day in doc.get("per_day") or []:
        if not day["changed"]:
            continue
        out.append(
            f"[ПО ДНЯМ] {day['cycle_date']} ${float(day['unpriced_gross_usd']):,.2f}: "
            f"G7 требовал [{', '.join(day['g7_remedies_required'])}], а днём "
            f"{day['chosen_forward_date']} довольно "
            f"[{', '.join(day['remedies_required'])}] — блокируют там "
            f"{', '.join(day['legs_blocking_there'])}")

    sens = doc.get("order_sensitivity") or {}
    contested = sens.get("days_where_order_decides") or []
    if contested:
        out.append(
            f"[WARNING] на {len(contested)} дн. ({', '.join(contested)}) минимальные "
            f"по включению наборы НЕСРАВНИМЫ ⇒ вердикт держится на объявленном "
            f"порядке цены, а не на данных: при обратном порядке доля нашего кода "
            f"была бы {sens['our_code_pct_owner_first']:.2f} % вместо "
            f"{sens['our_code_pct_declared']:.2f} % (ход ${sens['swing_usd']:,.2f})")
    else:
        # «Измерено и равно нулю» обязано отличаться от «не измерено» (инв. #17).
        out.append("[ОПОРА] ни на одном дне порядок цены не решает: у каждого дня "
                   "минимальный по включению набор ОДИН, и ответ не зависит от "
                   "соглашения о дешевизне набора")
    out.append(
        f"[ОПОРА] достаточность набора проверена НАСТОЯЩИМ судьёй на каждом из "
        f"{pop['measured_days']} дн.: структурный предикат и `_evaluate_verdict` "
        f"согласны, и снятие любой пары набора ломает подъём")
    return out


def format_report(doc: dict) -> List[str]:
    return list(doc.get("findings") or [])


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, **kwargs) -> dict:
    """Форма, которую ждут ступень переписей `findings_bridge` и шаг 0-офис."""
    from spa_core.utils.atomic import atomic_save

    root = root or str(Path(__file__).resolve().parents[2])
    data_dir = Path(root) / "data"
    doc = measure(data_dir, now=now, **kwargs)
    findings = list(doc.get("findings") or [])
    doc["overall"] = doc["status"]
    doc["counts"] = {
        "critical": sum(1 for x in findings if x.startswith("[CRITICAL]")),
        "warn": sum(1 for x in findings if x.startswith("[WARNING]")),
        "info": sum(1 for x in findings if x.startswith("[ОТВЕТ")
                    or x.startswith("[РАСКЛАДКА]") or x.startswith("[ПО ДНЯМ]")
                    or x.startswith("[ПО РЫЧАГАМ]") or x.startswith("[ОПОРА]")),
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
        description=("доллары слепого оборота под правилом ОДНОГО форвардного дня "
                     "(заказ #592/G9 приказа «Portfolio CIO»)"))
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
