"""ОСТАЁТСЯ ЛИ расширение записи на критическом пути к взводу (заказ #545, ADR-305).

Заказ поставлен дословно так:

> **Остаётся ли расширение записи вообще на критическом пути к взводу?** ADR-295
> мерил цену на снимке 09.09, а ``data/shadow_trigger_evaluation.json`` объявил
> взвод ``UNREACHABLE_UNTIL_CHANGED`` по ДРУГОЙ причине — недельный бюджет
> оборота отказывает на **22 существенных днях из 22**. Мерить надо ОБА порядка
> снятия стен: сначала бюджет, потом запись — и наоборот.
>
> **Ловушка названа заранее.** Соблазн — ответить «ветка закрыта» из одного
> факта, что бюджет отказывает на 100 % дней. Это ответ на вопрос «что блокирует
> СЕГОДНЯ», а не «что будет блокировать, когда владелец ответит по бюджету».
> Порядок, при котором расширение не добавляет НИЧЕГО НИ В ОДНОМ из двух, и есть
> закрытие ветки; любой другой — нет.

## Две стены РАЗНОРОДНЫ, и в этом весь вопрос

Смоделировать их как два гейта было бы первой ошибкой. Они стоят на разных
этапах и отвечают за разное:

* **стена «бюджет»** — гейтовая. Решает, БЫВАЕТ ЛИ вообще вердикт ``ACT``:
  ``week_turnover_ok`` / ``move_turnover_ok`` в ``rebalance_economics``;
* **стена «запись»** — ценовая. Гейта не трогает вовсе; решает, можно ли уже
  случившийся ``ACT`` ОЦЕНИТЬ: ``_evaluate_verdict`` объявляет день
  ``UNCHECKED``, когда у двигаемой ноги нет живой ставки в forward-записи.

Критерий №3 мандата владельца (ADR-067, ``net_bps_if_followed > 0``) требует
ОБОИХ разом: нужен ``ACT``, и он должен быть оценён. Поэтому «критический путь»
здесь — конъюнкция, а не цепочка, и порядок снятия стен на неё влияет
несимметрично. Прибор считает обе половины порознь и печатает их порознь.

## Что прибор меряет

1. **Освобождение по гейтам.** Сколько существенных дней становятся
   ACT-пригодными, когда объявленный набор гейтов принудительно проходит.
   Считается ПО ДНЮ и СОВМЕСТНО (все остальные гейты того дня обязаны пройти),
   а не по краевым долям: гейты отказывают пачками, и сумма краевых долей на
   вопрос «сколько дней освободится» не отвечает.
2. **Оценимость освобождённых дней.** На каждом освобождённом дне зовётся
   НАСТОЯЩИЙ ``_evaluate_verdict`` — сколько forward-дней горизонта оценено,
   какие ноги остались неоценёнными.
3. **Потолок стены «запись».** Для каждой неоценённой пары «forward-день × нога»
   класс берётся у НАСТОЯЩЕГО ``unevidenced_leg_causes.classify_pair``. Расширение
   писателя (ADR-302 — записывать все живые ставки, а не только ноги книг дня)
   закрывает РОВНО класс ``absent_from_forward_books``. Классы «провенанс не
   живой» и «провенанс живой, значение пустое» оно не закрывает НИКАК: писать
   нечего. Пара старой схемы — ``unattributable``, и это третий исход, а не
   отнесение к более частому классу.

## Правило закрытия ветки — ровно то, которое назвал заказ

Ветка закрыта тогда и только тогда, когда расширение не добавляет НИЧЕГО НИ В
ОДНОМ из двух порядков. Добавило хоть в одном — ветка открыта, и прибор говорит
В КАКОМ ИМЕННО: это разные приказы владельцу.

## Чего прибор НЕ утверждает — граница названа вслух

1. **Он не предсказывает вердикты.** «День стал бы ACT» здесь означает
   арифметику гейтов на ЗАПИСАННОМ предложении того дня: все гейты, кроме
   снятых, прошли. Он НЕ утверждает, что аллокатор предложил бы то же самое при
   других порогах — цель считается заново, и её пересчёт этому прибору не
   принадлежит. Поэтому число освобождённых дней есть **потолок**, а не прогноз.
2. **Он не решает, чем был провенанс в прошлом.** Расширение писателя действует
   только ВПЕРЁД (ADR-305), а класс пары читается из САМОЙ forward-записи, а не
   из сегодняшнего ``adapter_status.json``: провенанс принадлежит ЗНАЧЕНИЮ, а не
   дороге (ловушка ADR-302, соблюдена — файл не читается вовсе).
3. **Знак ``net`` на оценённой части — не приговор дню.** Стоимость заряжается
   ПОЛНОСТЬЮ и однократно, выгода копится только по ОЦЕНЁННЫМ дням, поэтому
   короткий оценённый горизонт смещает знак в минус по построению. Прибор
   печатает рядом границу «тот же дневной темп на всём горизонте» и НАЗЫВАЕТ её
   допущением о постоянстве темпа, а не замером.

**ADVISORY.** Прибор ничего не двигает: пороги ``TriggerParams``,
``MIN_HIT_RATE``, ``ready_to_arm``, ``POLLED_ADAPTERS``, писатель журнала, пороги
RiskPolicy v1.0, потолки концентрации, kill-switch и живой трек не тронуты,
капитал не сдвинут. Снятие стен решает владелец (предмет №1 ADR-285).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

log = logging.getLogger("spa.monitoring.arming_wall_order")

VERSION = "arming-wall-order-v1"
OUTPUT_FILENAME = "arming_wall_order.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Гейтовая стена «бюджет оборота». ДВА гейта, и порознь они ведут себя
#: по-разному — недельный потолок и потолок на один ход. Карточка владельцу
#: спрашивает про НЕДЕЛЬНЫЙ; замер показывает, что он один не освобождает
#: ничего, поэтому оба подмножества считаются и печатаются ОТДЕЛЬНО.
WALL_WEEK = ("week_turnover_ok",)
WALL_BUDGET = ("week_turnover_ok", "move_turnover_ok")

#: Ценовая стена. Гейтом НЕ является — снимается не проходом гейта, а наличием
#: ставки в forward-записи, поэтому в наборы гейтов не входит никогда.
WALL_RECORD = "record_expansion"

BRANCH_CLOSED = "BRANCH_CLOSED"
BRANCH_OPEN = "BRANCH_OPEN"
BRANCH_UNMEASURED = "BRANCH_UNMEASURED"


def material_days(records: Sequence[dict]) -> Tuple[List[dict], List[str]]:
    """Существенные дни + дни, у которых состояние гейтов НЕ ИЗМЕРЕНО.

    Существенный день — тот, где было что решать (``has_legs``). Тривиальные
    HOLD'ы исключены той же меркой, что у ``arming_blockade``: иначе тихий рынок
    надувал бы знаменатель.
    """
    from spa_core.paper_trading.shadow_trigger_eval import gate_state

    out: List[dict] = []
    unmeasured: List[str] = []
    for idx, rec in enumerate(records):
        state, source = gate_state(rec)
        date = str(rec.get("cycle_date") or "")
        if state is None:
            unmeasured.append(date)
            continue
        if not state.get("has_legs", True):
            continue
        out.append({"index": idx, "date": date, "state": state, "source": source})
    return out, unmeasured


def released_days(material: Sequence[dict], lifted: Sequence[str]) -> List[dict]:
    """Дни, где проходят ВСЕ гейты, кроме принудительно снятых.

    Совместно, а не покомпонентно: день освобождается только если ни один
    НЕснятый гейт на нём не отказал.
    """
    from spa_core.paper_trading.shadow_trigger_eval import _ALL_GATES

    lifted_set = set(lifted)
    gates = [g for g in sorted(_ALL_GATES) if g != "has_legs"]
    out: List[dict] = []
    for row in material:
        still = [g for g in gates
                 if g not in lifted_set and not row["state"].get(g, True)]
        if not still:
            out.append(row)
    return out


def pricing_profile(rec: dict, forward: Sequence[dict], horizon: int) -> dict:
    """Оценимость одного дня НАСТОЯЩИМ оценщиком + разбор неоценённых пар.

    Класс каждой неоценённой пары берётся у настоящего ``classify_pair``: своя
    копия правила разошлась бы с писателем молча.
    """
    from spa_core.monitoring.unevidenced_leg_causes import (
        CLASS_ABSENT, CLASS_UNATTRIBUTABLE, classify_pair,
    )
    from spa_core.paper_trading.shadow_trigger_eval import _deltas, _evaluate_verdict

    row = _evaluate_verdict(rec, forward, horizon)
    deltas = _deltas(rec)
    fw = list(forward)[:horizon]

    pairs: List[dict] = []
    for frec in fw:
        apy = frec.get("apy_evidenced_pct") or {}
        for proto in sorted(deltas):
            if apy.get(proto) is not None:
                continue
            pairs.append({
                "forward_date": str(frec.get("cycle_date") or ""),
                "protocol": proto,
                "cause_class": classify_pair(frec, proto),
            })

    # ПОТОЛОК, а не обещание (граница №3 ADR-300). Пара класса «вне книг дня»
    # лежит ВНУТРИ того, что расширение писателя вообще способно затронуть, — но
    # существовала ли у этой ноги в тот день живая ставка, запись не говорит
    # вовсе: у ноги вне книг провенанса в записи нет по построению. Поэтому
    # величина называется потолком и НЕ складывается с «расширение откроет».
    within_ceiling = sum(1 for p in pairs if p["cause_class"] == CLASS_ABSENT)
    # А эти расширение не закроет НИКАК: нога в книгах дня, провенанс не живой
    # либо значение пустое — записывать было нечего.
    beyond = sum(1 for p in pairs
                 if p["cause_class"] not in (CLASS_ABSENT, CLASS_UNATTRIBUTABLE))
    unattributable = sum(1 for p in pairs
                         if p["cause_class"] == CLASS_UNATTRIBUTABLE)
    checked = int(row.get("forward_days_checked") or 0)

    prof = {
        "date": str(rec.get("cycle_date") or ""),
        "recorded_verdict": row.get("verdict"),
        "turnover_usd": row.get("turnover_usd"),
        "forward_days_available": row.get("forward_days_available"),
        "forward_days_checked": checked,
        "forward_days_unchecked": row.get("forward_days_unchecked"),
        "counterfactual": row.get("counterfactual"),
        "scorable": checked > 0,
        "unpriced_protocols": row.get("unpriced_protocols") or [],
        "unpriced_pairs": pairs,
        "unpriced_pairs_total": len(pairs),
        "unpriced_pairs_within_expansion_ceiling": within_ceiling,
        "unpriced_pairs_beyond_expansion": beyond,
        "unpriced_pairs_unattributable": unattributable,
        "expansion_effect": (
            "NOT_BLOCKED" if checked > 0 else
            "UNDETERMINED_WITHIN_CEILING" if within_ceiling else
            "BEYOND_EXPANSION" if beyond else "UNMEASURED"),
        "expansion_effect_note": (
            "«внутри потолка» НЕ означает «расширение откроет»: у ноги вне книг "
            "дня провенанса в записи нет вовсе, поэтому существовала ли тогда "
            "живая ставка — НЕ ОПРЕДЕЛЕНО ничем, что лежит на диске"),
    }

    # Знак `net` и его чувствительность к дыре — ТОЛЬКО там, где он существует.
    #
    # Условие ИЗБЫТОЧНО, и это измерено, а не предположено: батарея мутаций
    # цикла #546 сняла `checked > 0` — набор остался зелёным, потому что
    # `_evaluate_verdict` при `checked == 0` не кладёт `net_usd` вовсе, и вторая
    # половина условия отсекает ту же ветку. Избыточность оставлена намеренно
    # (она перестанет быть избыточной, если оценщик когда-нибудь начнёт класть
    # ноль вместо пропуска), но выдавать её за проверенную поодиночке нельзя:
    # наблюдаемый инвариант — «у неоценимого дня ключей `net_*` нет» — закрыт
    # тестом `test_unpriceable_day_carries_NO_net_at_all` при любом из двух.
    if checked > 0 and row.get("net_usd") is not None:
        benefit = float(row.get("benefit_usd_over_checked_days") or 0.0)
        cost = float(row.get("cost_usd_used") or 0.0)
        per_day = benefit / checked
        prof["net_usd_as_scored"] = row.get("net_usd")
        prof["net_usd_if_full_horizon_at_same_rate"] = round(
            per_day * horizon - cost, 2)
        prof["net_sign_note"] = (
            "стоимость заряжена ПОЛНОСТЬЮ и однократно, выгода накоплена только "
            f"по {checked} оценённым дням из {horizon}; вторая величина — граница "
            "при ДОПУЩЕНИИ постоянного дневного темпа, а не замер")
    return prof


def _order_budget_then_record(material: Sequence[dict], records: Sequence[dict],
                              horizon: int) -> dict:
    """Порядок A: сперва снимается бюджет, потом спрашивается про запись."""
    week_only = released_days(material, WALL_WEEK)
    both = released_days(material, WALL_BUDGET)

    profiles = [pricing_profile(records[r["index"]],
                                records[r["index"] + 1:], horizon)
                for r in both]
    scorable = [p for p in profiles if p["scorable"]]
    blocked = [p for p in profiles if not p["scorable"]]
    partial = [p for p in scorable
               if int(p["forward_days_checked"] or 0) < horizon]
    blocked_within_ceiling = [p for p in blocked
                              if p["unpriced_pairs_within_expansion_ceiling"] > 0]
    blocked_beyond = [p for p in blocked
                      if p["unpriced_pairs_within_expansion_ceiling"] == 0]

    # ДВА РАЗНЫХ утверждения, и слипание их было бы находкой из неизмеренного:
    #   `wall_binds`  — измерено: дыра записи ещё связывает после падения бюджета;
    #   ceiling/beyond — НЕ измерено: закроет ли дыру именно ПРЕДЛОЖЕННОЕ
    #                    расширение писателя.
    adds = bool(blocked) or bool(partial)
    return {
        "order": "budget_then_record",
        "released_by_week_budget_alone": len(week_only),
        "released_by_both_turnover_budgets": len(both),
        "released_dates": [r["date"] for r in both],
        "scorable_days": len(scorable),
        "record_blocked_days": len(blocked),
        "record_blocked_dates": [p["date"] for p in blocked],
        "partially_priced_days": len(partial),
        "record_blocked_days_within_expansion_ceiling": len(blocked_within_ceiling),
        "record_blocked_days_beyond_expansion": len(blocked_beyond),
        "profiles": profiles,
        "record_wall_binds": adds,
        "expansion_adds": adds,
        "note": (
            "снятие НЕДЕЛЬНОГО бюджета в одиночку освобождает "
            f"{len(week_only)} дн.: карточка владельцу спрашивает про него, а "
            "связывает пара с потолком на один ход — снятие только одного из "
            "двух не открывает ничего"
            if len(week_only) < len(both) else
            "недельный потолок и потолок на ход освобождают одно и то же "
            "множество дней"),
    }


def _order_record_then_budget(material: Sequence[dict], records: Sequence[dict],
                              horizon: int) -> dict:
    """Порядок B: сперва закрывается запись (до её ПОТОЛКА), потом бюджет.

    Расширение писателя не трогает ни одного гейта, поэтому множество
    ACT-пригодных дней при неснятом бюджете от него не зависит вовсе. Это и
    есть измеряемое утверждение: считается то же освобождение при пустом наборе
    снятых гейтов.
    """
    released_before = released_days(material, ())
    return {
        "order": "record_then_budget",
        "act_eligible_days_before_budget": len(released_before),
        "expansion_adds": False if not released_before else True,
        "note": (
            "расширение писателя не участвует в вычислении ни одного гейта "
            "(`gates` считает `rebalance_economics`, ставки туда не входят), "
            f"поэтому ACT-пригодных дней остаётся {len(released_before)} при "
            "любом состоянии записи; критерий №3 требует оценённого ACT, а ACT "
            "не появляется — расширение не приближает взвод НИ НА ЧТО"),
    }


def measure(data_dir: Path, *, now: Optional[datetime] = None,
            horizon_days: Optional[int] = None,
            book_id: Optional[str] = None) -> dict:
    """Замер обоих порядков снятия стен. Ничего не пишет — только считает."""
    from spa_core.paper_trading.shadow_trigger_eval import (
        DEFAULT_HORIZON_DAYS, load_history,
    )

    now = now or datetime.now(timezone.utc)
    horizon = int(horizon_days or DEFAULT_HORIZON_DAYS)
    records, bad = load_history(Path(data_dir), book_id)

    doc: dict = {
        "generated_at": now.isoformat(),
        "version": VERSION,
        "horizon_days": horizon,
        "history_lines": len(records),
        "history_unparseable": bad,
        "walls": {
            "budget": {"kind": "gate", "gates": list(WALL_BUDGET),
                       "week_only": list(WALL_WEEK)},
            "record": {"kind": "pricing", "name": WALL_RECORD,
                       "closes_cause_class": "absent_from_forward_books"},
        },
        "findings": [],
    }

    material, unmeasured = material_days(records)
    doc["material_days"] = len(material)
    doc["gate_state_unmeasured_days"] = unmeasured

    if not material:
        doc["status"] = STATUS_UNMEASURED
        doc["branch_verdict"] = BRANCH_UNMEASURED
        doc["findings"].append(
            "[НЕ ИЗМЕРЕНО] существенных дней в истории нет — снимать нечего, и "
            "«расширение не нужно» из пустого населения не выводится")
        return doc
    if unmeasured:
        doc["status"] = STATUS_UNMEASURED
        doc["branch_verdict"] = BRANCH_UNMEASURED
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] {len(unmeasured)} дн. истории не несут ни `gates`, "
            "ни `reasons` — перепись отказов неполна, и порядок снятия стен по "
            "ней не судится")
        return doc

    order_a = _order_budget_then_record(material, records, horizon)
    order_b = _order_record_then_budget(material, records, horizon)
    doc["orders"] = [order_a, order_b]

    # Правило закрытия — ровно то, которое назвал заказ #545.
    adds_in = [o["order"] for o in (order_a, order_b) if o["expansion_adds"]]
    doc["expansion_adds_in_orders"] = adds_in
    doc["branch_verdict"] = BRANCH_CLOSED if not adds_in else BRANCH_OPEN
    doc["branch_rule"] = (
        "ветка закрыта тогда и только тогда, когда расширение не добавляет "
        "НИЧЕГО НИ В ОДНОМ из двух порядков (правило заказа #545)")

    if adds_in:
        doc["status"] = STATUS_CRITICAL
        doc["findings"].append(
            f"[ОТВЕТ] ветка НЕ закрыта: дыра записи ещё СВЯЗЫВАЕТ в порядке "
            f"{', '.join(adds_in)} — но НЕ в обоих. Связывает ДЫРА (замер); "
            "снимет ли её предложенное расширение писателя — вопрос его "
            "потолка, и он отвечается отдельно ниже")
    else:
        doc["status"] = STATUS_OK
        doc["findings"].append(
            "[ОТВЕТ] ветка закрыта: расширение записи не добавляет ни в одном "
            "из двух порядков")

    doc["findings"].append(
        f"[ПО ДНЯМ] бюджет: недельный потолок в одиночку освобождает "
        f"{order_a['released_by_week_budget_alone']} дн. из "
        f"{len(material)} существенных, оба потолка оборота вместе — "
        f"{order_a['released_by_both_turnover_budgets']} дн.")

    if order_a["record_blocked_days"]:
        doc["findings"].append(
            f"[CRITICAL] порядок A: из "
            f"{order_a['released_by_both_turnover_budgets']} освобождённых "
            f"бюджетом дней {order_a['record_blocked_days']} не оценивается "
            f"ВОВСЕ ({', '.join(order_a['record_blocked_dates'])}) — критерий "
            "№3 на них не считается, и снятие бюджета само по себе взвод не "
            "открывает")
    if order_a["partially_priced_days"]:
        doc["findings"].append(
            f"[ЦЕНА] порядок A: ещё {order_a['partially_priced_days']} дн. "
            f"оценены ЧАСТИЧНО — горизонт неполон, и знак `net` на них считан "
            "с полной стоимостью против неполной выгоды")

    # Потолок стены «запись» — ОТДЕЛЬНОЕ утверждение от «стена связывает».
    # Слить их значило бы выдать «расширение откроет» за замер: у ноги вне книг
    # дня провенанса в записи нет, и что там было, не решается ничем на диске.
    pairs_ceiling = sum(p["unpriced_pairs_within_expansion_ceiling"]
                        for p in order_a["profiles"])
    pairs_beyond = sum(p["unpriced_pairs_beyond_expansion"]
                       for p in order_a["profiles"])
    pairs_total = sum(p["unpriced_pairs_total"] for p in order_a["profiles"])
    doc["expansion_ceiling"] = {
        "unpriced_pairs_total": pairs_total,
        "within_ceiling": pairs_ceiling,
        "beyond_expansion": pairs_beyond,
        "blocked_days_beyond_expansion": order_a["record_blocked_days_beyond_expansion"],
    }
    if pairs_beyond > 0:
        doc["findings"].append(
            f"[CRITICAL] потолок стены «запись»: из {pairs_total} неоценённых "
            f"пар «forward-день × нога» расширение писателя НЕ закрывает "
            f"{pairs_beyond} — нога В КНИГАХ дня, а провенанс не живой: "
            "записывать было нечего. Внутри потолка расширения лежат лишь "
            f"{pairs_ceiling}")
    if order_a["record_blocked_days_beyond_expansion"] > 0:
        doc["findings"].append(
            f"[CRITICAL] {order_a['record_blocked_days_beyond_expansion']} "
            "заблокированных записью дней расширение не открывает НИ ПРИ КАКОМ "
            "исходе — все их неоценённые пары вне его потолка")
    if order_a["record_blocked_days_within_expansion_ceiling"] > 0:
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] у "
            f"{order_a['record_blocked_days_within_expansion_ceiling']} "
            "заблокированных записью дней есть пары ВНУТРИ потолка расширения — "
            "но откроет ли их расширение, НЕ ОПРЕДЕЛЕНО: у ноги вне книг дня "
            "провенанса в записи нет вовсе, и была ли тогда живая ставка, не "
            "решается ничем, что лежит на диске. Это третий исход, а не «да»")

    doc["findings"].append(
        "[ОТВЕТ] порядок B: расширение не добавляет ничего — оно не участвует "
        "в вычислении гейтов, а ACT-пригодных дней при неснятом бюджете "
        f"{order_b['act_eligible_days_before_budget']}")

    doc["what_it_does_not_prove"] = [
        "число освобождённых дней есть ПОТОЛОК: гейты пересчитаны на ЗАПИСАННОМ "
        "предложении того дня, а при других порогах аллокатор предложил бы "
        "другую цель — её пересчёт этому прибору не принадлежит",
        "чем был провенанс ставки в конкретный день прошлого, не решается ничем, "
        "что лежит на диске сегодня; `adapter_status.json` прибор не читает вовсе",
        "знак `net` на частично оценённом дне смещён в минус по построению "
        "(полная стоимость против неполной выгоды); граница при постоянном темпе "
        "печатается рядом и является ДОПУЩЕНИЕМ",
    ]
    return doc


def format_report(doc: dict) -> List[str]:
    """Строки для шага 0-офис."""
    out = [
        f"порядок снятия стен к взводу (заказ #545): {doc.get('status')} · "
        f"существенных дней {doc.get('material_days')} · вердикт ветки "
        f"{doc.get('branch_verdict')}"
    ]
    for o in doc.get("orders") or []:
        if o["order"] == "budget_then_record":
            out.append(
                f"   A бюджет→запись: недельный потолок один "
                f"{o['released_by_week_budget_alone']} дн. · оба потолка "
                f"{o['released_by_both_turnover_budgets']} дн. · из них "
                f"оценимо {o['scorable_days']}, заблокировано записью "
                f"{o['record_blocked_days']}")
        else:
            out.append(
                f"   B запись→бюджет: ACT-пригодных дней "
                f"{o['act_eligible_days_before_budget']} — расширение не "
                f"добавляет ничего")
    for line in doc.get("findings") or []:
        out.append(f"   {line}")
    out.append("   ADVISORY: пороги TriggerParams, MIN_HIT_RATE и ready_to_arm "
               "НЕ трогаются — снятие стен решает владелец")
    return out


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
        "warn": sum(1 for x in findings if x.startswith("[ЦЕНА")),
        "info": sum(1 for x in findings if x.startswith("[ОТВЕТ")
                    or x.startswith("[ПО ДНЯМ]")),
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
        description="остаётся ли расширение записи на пути к взводу (заказ #545)")
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
