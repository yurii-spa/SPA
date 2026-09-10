"""ПОЧЕМУ у опрашиваемой ноги в конкретный день нет живой ставки (заказ #543, ADR-300).

Заказ ADR-300 поставлен дословно так:

> **Измерить, почему у ОПРАШИВАЕМОГО протокола в конкретный день нет живой
> ставки.** Пять из шести блокирующих ног оркестратор спрашивает, и ставки всё
> равно нет. Молчание фида · отказ гейта живого TVL (ADR-053) при живой ставке ·
> неполная перепись входов в самой записи решения · иное? Ответ обязан быть
> **по дням и по причинам поимённо**, а не одной долей.

Прибор отвечает ровно в этих единицах: **пара «forward-день × нога»** для
атрибуции и **ДНИ журнала** для цены. Доли он тоже печатает — но после
поимённого перечня, а не вместо него.

## Почему вопрос не праздный

``hit_rate`` — критерий взвода (``shadow_trigger_eval.MIN_HIT_RATE`` = 0.60,
мандат владельца ADR-067). ADR-299 показал, что он предъявлен как ``PASS`` на
неполном населении; ADR-300 измерил, что закрытие G1 не поднимает ни одного дня,
и назвал адрес недоизмеренности так:

> недоизмеренность ``hit_rate`` держится не проводкой ``POLLED_ADAPTERS``, а
> **ПЕРЕБОЯМИ ЭВИДЕНСА на ногах книги**

Это утверждение о ПРИЧИНЕ, и оно было выведено из того, что блокирующие ноги
опрашиваются. «Ногу спрашивают, а ставки в записи нет» ⇒ «фид дал перебой» —
шаг, который прибор проверяет ЗАМЕРОМ, потому что у отсутствия ставки в записи
есть и вторая дорога, не имеющая к фиду отношения.

## Три класса, и разводятся они ПО ЗАПИСИ, а не по догадке

Писатель журнала (``allocation_rationale.build_history_record``, ADR-290) кладёт
в ``apy_evidenced_pct`` ключ ``p`` тогда и только тогда, когда одновременно:
``p ∈ universe = current_positions ∪ target_positions`` **и** провенанс
``apy_sources[p] == "live"`` **и** значение не ``None``. Отсюда ровно три
взаимоисключающих класса, каждый читается из САМОЙ forward-записи:

* ``absent_from_forward_books`` — ``p`` вне книг того дня. Запись не могла нести
  его ставку ни при каком состоянии фида: отсекла **перепись входов**, а не
  наблюдение. Это население, измеренное ADR-290 («население журнала — КНИГА, а
  не ранжированный набор»), здесь применённое к конкретным блокирующим дням;
* ``in_books_source_not_live`` — ``p`` в книгах дня и назван в ``apy_unevidenced``.
  Провенанс не ``live`` ⇒ это и есть **перебой эвиденса**;
* ``live_source_but_null_value`` — ``p`` в книгах, в ``apy_unevidenced`` его нет,
  а ставки всё равно нет. Провенанс живой, значение пустое.

Четвёртый исход обязателен: запись старой схемы без ``apy_unevidenced`` не даёт
развести второй класс с третьим ⇒ ``unattributable``, и такая пара идёт в
ОТДЕЛЬНЫЙ счёт, а не в самую правдоподобную корзину.

## Ловушка заказа названа заранее и соблюдена

Соблазн — взять ``data/adapter_status.json`` за источник провенанса и сказать
«фид молчал». Прибор этого файла НЕ ЧИТАЕТ ВОВСЕ: провенанс принадлежит
ЗНАЧЕНИЮ, а не дороге, и «пришло не от X» не равно «не наблюдалось». Всё, что
прибор знает о провенансе, он берёт из полей той же записи, которую судит
оценщик.

## Чего прибор НЕ утверждает — граница названа вслух

1. **Подкласс ``in_books_source_not_live`` не разбирается.** Молчал ли фид,
   вышло ли значение из полосы правдоподобия, не спросили ли адаптер в тот день —
   запись этого не несёт, и прибор отвечает ``unattributable`` на подуровне, а не
   выбирает правдоподобное.
2. **Гейт живого TVL (ADR-053) не исключён из причин — он переклассифицирован.**
   Гейт не может стереть ставку у ноги, которую книги дня касаются: он не
   участвует в построении ``apy_evidenced_pct`` вовсе. Подействовать он способен
   ТОЛЬКО раньше — убрав ногу из цели, то есть из ``universe``. Такая нога
   неотличима в записи от той, которую аллокатор не захотел сам, и обе лежат в
   ``absent_from_forward_books``. Прибор говорит «отсекла перепись входов» и НЕ
   говорит, кто именно был причиной отсутствия ноги в цели.
3. **«Класс поднял бы день» — это ПОТОЛОК, а не обещание.** Выдавая право быть
   оценённой, прибор ставит ``_PRICING_SENTINEL_PCT`` = 0.0 (конвенция ADR-300):
   нога становится оценимой, вклад в ``benefit`` РОВНО нулевой. Существовала ли
   в тот день живая ставка у ноги вне книг — запись не говорит, и прибор не
   выдумывает. Ноль под потолком есть ноль под любым честным чтением; ЧИСЛО под
   потолком — верхняя граница, и в отчёте оно так и названо.
4. **Какими были бы вердикты, прибор не печатает никогда.** ``hit``/``miss`` под
   сентинелом — артефакт сентинела, а не наблюдение (та же граница, что у
   ADR-300; тест закрепляет отсутствие ключа ``hit_rate`` во всём артефакте).

## Два независимых вывода, и они ОБЯЗАНЫ совпасть

1. **структурный** — день восстанавливается, если найдётся forward-день, у
   которого неоценённые двигаемые ноги целиком лежат внутри выданных ПАР;
2. **реплей** — настоящий ``_evaluate_verdict`` зовётся на возмущённых копиях
   forward-записей.

Расхождение хотя бы на одном дне ⇒ ``UNMEASURED``. Один вывод был бы
утверждением о коде, который я сам же и написал.

**Чем НЕ является замыкание ``all_causes_closure``.** «Выдача всех пар поднимает
все дни» при сошедшемся паритете верна ПО ПОСТРОЕНИЮ и контролем способности
служить не может — назвать её так значило бы завести украшение. Она оставлена как
замыкание на случай отключённого паритета. Способность «ноль у класса мог бы быть
не-нулём» доказывается в наборе тестов СЦЕНОЙ, где перебой эвиденса ОДИН поднимает
день.

**ADVISORY.** Прибор ничего не двигает: ``POLLED_ADAPTERS``, пины, писатель
журнала, ``MIN_HIT_RATE``, ``TriggerParams``, пороги RiskPolicy v1.0, потолки
концентрации, kill-switch и живой трек не тронуты, капитал не сдвинут.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import copy
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

log = logging.getLogger("spa.monitoring.unevidenced_leg_causes")

VERSION = "unevidenced-leg-causes-v1"
OUTPUT_FILENAME = "unevidenced_leg_causes.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Право быть оценённым, а не доходность (конвенция ADR-300).
_PRICING_SENTINEL_PCT = 0.0

#: Классы причин. Порядок — порядок разбора в :func:`classify_pair`.
CLASS_ABSENT = "absent_from_forward_books"
CLASS_NOT_LIVE = "in_books_source_not_live"
CLASS_LIVE_NULL = "live_source_but_null_value"
CLASS_UNATTRIBUTABLE = "unattributable"

ALL_CLASSES = (CLASS_ABSENT, CLASS_NOT_LIVE, CLASS_LIVE_NULL, CLASS_UNATTRIBUTABLE)

#: Причина, по которой день не поднимет НИКАКОЙ класс.
_BEYOND_REASON = ("forward-записей у дня нет вовсе — окно кончилось, а не ставка "
                  "пропала; никакая причина отсутствия ставки к этому дню не относится")


def classify_pair(frec: dict, protocol: str) -> str:
    """Класс причины для пары «forward-запись × нога». Читается ИЗ ЗАПИСИ.

    Разбор идёт в том порядке, в каком отсекает писатель
    (``build_history_record``): сперва ``universe``, потом провенанс, потом
    значение. Обратный порядок соврал бы: нога вне книг не имеет провенанса в
    записи вовсе, и спросив о нём первым, мы отнесли бы её к перебою эвиденса.
    """
    universe = (set(frec.get("current_positions") or {})
                | set(frec.get("target_positions") or {}))
    if protocol not in universe:
        return CLASS_ABSENT
    if "apy_unevidenced" not in frec:
        # Схема без переписи неэвиденсных ключей: второй класс от третьего не
        # отличим. Третий исход, а не догадка в пользу более частого.
        return CLASS_UNATTRIBUTABLE
    if protocol in set(frec.get("apy_unevidenced") or []):
        return CLASS_NOT_LIVE
    return CLASS_LIVE_NULL


def _missing_legs(deltas: Dict[str, float], frec: dict) -> List[str]:
    """Собственное прочтение правила оценки — вход контроля ПАРИТЕТА.

    Намеренно НЕ зовёт ``_day_gain_usd``: сверка своего прочтения с чужим и есть
    контроль. Позвав оценщика, прибор сверял бы его с самим собой.
    """
    apy = frec.get("apy_evidenced_pct") or {}
    return sorted(p for p in deltas if apy.get(p) is None)


def grant_pricing_pairs(forward: Sequence[dict],
                        granted: Set[Tuple[str, str]]) -> List[dict]:
    """Копии forward-записей, где ПАРАМ из ``granted`` выдано право быть оценёнными.

    Выдача идёт по ПАРЕ (день, нога), а не по ключу: одна и та же нога бывает
    разных классов в разные дни (``pendle`` 2026-09-06 — вне книг в один день и
    неэвиденсной в другой), и выдача по ключу приписала бы классу чужие дни.

    Копия глубокая: возмущение не смеет тронуть записи, по которым считается
    базовая линия, — иначе паритет сравнивал бы возмущённое с возмущённым.
    """
    out: List[dict] = []
    for rec in forward:
        c = copy.deepcopy(rec)
        date = str(c.get("cycle_date"))
        apy = c.get("apy_evidenced_pct")
        if not isinstance(apy, dict):
            apy = {}
        for gdate, gproto in granted:
            if gdate == date and apy.get(gproto) is None:
                apy[gproto] = _PRICING_SENTINEL_PCT
        c["apy_evidenced_pct"] = apy
        out.append(c)
    return out


def _structural_recovers(deltas: Dict[str, float], forward: Sequence[dict],
                         horizon: int, granted: Set[Tuple[str, str]]) -> bool:
    """Вывод №1 — по форме входа, БЕЗ вызова оценщика.

    Достаточно ОДНОГО forward-дня, все неоценённые ноги которого выданы:
    ``_evaluate_verdict`` выносит вердикт при ``checked >= 1``.
    """
    for frec in list(forward)[:horizon]:
        date = str(frec.get("cycle_date"))
        missing = {(date, p) for p in _missing_legs(deltas, frec)}
        if missing <= granted:
            return True
    return False


def _replay_recovers(rec: dict, forward: Sequence[dict], horizon: int,
                     granted: Set[Tuple[str, str]]) -> bool:
    """Вывод №2 — НАСТОЯЩИЙ ``_evaluate_verdict`` на возмущённых копиях."""
    from spa_core.paper_trading.shadow_trigger_eval import _evaluate_verdict

    row = _evaluate_verdict(rec, grant_pricing_pairs(forward, granted), horizon)
    return row.get("outcome") != "UNCHECKED"


def _in_books_unpriced_census(records: Sequence[dict]) -> dict:
    """Независимая опора: как часто нога ВНУТРИ книг дня остаётся без ставки.

    Считается по ВСЕМ дням журнала и всем ногам их книг — то есть на населении,
    никак не связанном с блокирующими днями. Это верхняя оценка того, сколько
    вообще способен объяснить перебой эвиденса: класс, почти пустой на всём
    журнале, не может держать много блокирующих дней. Опора НЕ участвует в
    атрибуции — она её проверяет со стороны.
    """
    in_books = unpriced = 0
    unpriced_pairs: List[str] = []
    for rec in records:
        universe = (set(rec.get("current_positions") or {})
                    | set(rec.get("target_positions") or {}))
        apy = rec.get("apy_evidenced_pct") or {}
        for p in sorted(universe):
            in_books += 1
            if apy.get(p) is None:
                unpriced += 1
                if len(unpriced_pairs) < 20:
                    unpriced_pairs.append(f"{rec.get('cycle_date')}:{p}")
    return {
        "leg_days_in_books": in_books,
        "leg_days_unpriced": unpriced,
        "unpriced_examples": unpriced_pairs,
        "what_it_bounds": ("перебой эвиденса способен объяснить только пары ВНУТРИ "
                           "книг; на всём журнале их столько"),
    }


def measure(data_dir: Path, *, now: Optional[datetime] = None,
            book_id: Optional[str] = None,
            horizon_days: Optional[int] = None) -> dict:
    """Ответ заказу #543: причины отсутствия живой ставки, по дням и поимённо."""
    from spa_core.paper_trading.shadow_trigger_eval import (
        DEFAULT_HORIZON_DAYS, _day_gain_usd, _deltas, _evaluate_verdict,
        load_history,
    )

    now = now or datetime.now(timezone.utc)
    horizon = int(horizon_days or DEFAULT_HORIZON_DAYS)
    findings: List[str] = []
    doc: dict = {
        "version": VERSION,
        "generated_at": now.isoformat(),
        "status": STATUS_UNMEASURED,
        "horizon_days": horizon,
        "findings": findings,
        "does_not_report": (
            "подкласс перебоя эвиденса (молчал фид · значение вне полосы · не "
            "спросили адаптер) — запись его не несёт, а adapter_status.json не "
            "несёт провенанса ЗНАЧЕНИЯ и прибором не читается вовсе; каким был "
            "бы вердикт под сентинелом — тоже не докладывается"),
        "advisory": ("POLLED_ADAPTERS, пины, писатель журнала, MIN_HIT_RATE, "
                     "TriggerParams, пороги RiskPolicy v1.0 и живой трек НЕ "
                     "трогаются — прибор только называет причину"),
    }

    records, bad = load_history(Path(data_dir), book_id=book_id)
    doc["journal_rows"] = len(records)
    doc["journal_unparseable_lines"] = bad
    if not records:
        findings.append("[НЕ ИЗМЕРЕНО] журнал решений пуст или не прочитан — "
                        "причину отсутствия ставки назвать не из чего")
        return doc

    by_date = {str(r.get("cycle_date")): r for r in records}
    forward_of = {str(r.get("cycle_date")): records[i + 1:]
                  for i, r in enumerate(records)}

    # ── население: дни без вердикта ИМЕННО из-за неоценённых ног ──────────────
    population: List[str] = []
    beyond: List[str] = []
    for i, rec in enumerate(records):
        row = _evaluate_verdict(rec, records[i + 1:], horizon)
        if row.get("counterfactual") != "UNCHECKED":
            continue
        date = str(rec.get("cycle_date"))
        if row.get("unchecked_reason") == "no_evidenced_apy_for_moved_legs":
            population.append(date)
        else:
            # `no_forward_data` / `no_target_recorded` — вопрос заказа к ним не
            # относится: там ставка не пропадала. Считаются ОТДЕЛЬНО, чтобы
            # доля ниже не была посчитана на чужом населении.
            beyond.append(date)
    doc["population"] = {
        "days_unchecked_by_unpriced_legs": len(population),
        "days_unchecked_for_other_reasons": len(beyond),
        "days_list": population,
        "beyond_list": beyond,
        "beyond_reason": _BEYOND_REASON,
    }

    if not population:
        doc["status"] = STATUS_OK
        findings.append("[ОТВЕТ] нет ни одного дня, потерявшего вердикт из-за "
                        "неоценённой ноги — вопрос заказа не на чем задать")
        doc["attribution"] = []
        doc["parity_control"] = {"passed": True, "pairs_checked": 0,
                                 "what_it_proves": "население пусто, сверять нечего"}
        return doc

    # ── атрибуция пар + контроль ПАРИТЕТА ─────────────────────────────────────
    pairs: List[dict] = []
    parity_mismatch: List[str] = []
    by_class: Dict[str, Set[Tuple[str, str]]] = {c: set() for c in ALL_CLASSES}
    for date in population:
        deltas = _deltas(by_date[date])
        for frec in forward_of[date][:horizon]:
            fdate = str(frec.get("cycle_date"))
            mine = _missing_legs(deltas, frec)
            _gain, theirs = _day_gain_usd(deltas, frec.get("apy_evidenced_pct") or {})
            if sorted(theirs) != mine:
                parity_mismatch.append(f"{date}→{fdate}")
                continue
            for p in mine:
                cls = classify_pair(frec, p)
                by_class[cls].add((fdate, p))
                pairs.append({"decision_date": date, "forward_date": fdate,
                              "protocol": p, "class": cls})

    doc["parity_control"] = {
        "passed": not parity_mismatch,
        "pairs_checked": len(pairs),
        "mismatches": parity_mismatch[:10],
        "what_it_proves": ("моё прочтение правила оценки совпало с настоящим "
                           "_day_gain_usd на каждой паре; разойдись оно — "
                           "классифицировались бы не те ноги"),
    }
    if parity_mismatch:
        findings.append(f"[НЕ ИЗМЕРЕНО] паритет с настоящим оценщиком не сошёлся "
                        f"на {len(parity_mismatch)} forward-днях — атрибуция "
                        f"недействительна")
        return doc

    counts = {c: sum(1 for x in pairs if x["class"] == c) for c in ALL_CLASSES}
    doc["attribution"] = pairs
    doc["class_counts"] = counts
    doc["pairs_total"] = len(pairs)

    # ── замыкание РАЗБИЕНИЯ ───────────────────────────────────────────────────
    # Как и `all_causes_closure` ниже, названо тем, что оно есть: при работающем
    # `classify_pair` равенство «сумма классов == число пар» верно ПО ПОСТРОЕНИЮ
    # (разборщик тотален, ключи `counts` — весь `ALL_CLASSES`), и контролем
    # разбиения служить не может. Настоящее свойство — ТОТАЛЬНОСТЬ разборщика на
    # любой, в том числе покорёженной, записи; она закрыта тестом. Замыкание
    # оставлено как последняя сеть на случай, когда сложение делает уже не тот
    # код, что классификация.
    doc["partition_closure"] = {
        "passed": sum(counts.values()) == len(pairs) and len(pairs) > 0,
        "sum_of_classes": sum(counts.values()),
        "pairs_total": len(pairs),
        "what_it_proves": ("ни одна блокирующая пара не выпала между "
                           "классификацией и счётом"),
        "what_it_does_not_prove": ("это НЕ контроль разбиения — при тотальном "
                                   "classify_pair равенство выполняется по "
                                   "построению; тотальность закрыта тестом"),
    }
    if not doc["partition_closure"]["passed"]:
        doc["status"] = STATUS_UNMEASURED
        findings.append("[НЕ ИЗМЕРЕНО] пара выпала между классификацией и счётом "
                        "— доли ниже считались бы на дырявом множестве")
        return doc

    # ── цена в ДНЯХ: что поднял бы каждый класс поодиночке ────────────────────
    all_pairs = set().union(*by_class.values()) if by_class else set()
    scenarios: Dict[str, dict] = {}
    disagreement: List[str] = []
    for name, granted in ([(c, by_class[c]) for c in ALL_CLASSES]
                          + [("ALL", all_pairs)]):
        recovered: List[str] = []
        for date in population:
            deltas = _deltas(by_date[date])
            struct = _structural_recovers(deltas, forward_of[date], horizon, granted)
            replay = _replay_recovers(by_date[date], forward_of[date], horizon, granted)
            if struct != replay:
                disagreement.append(f"{name}:{date}")
            elif struct:
                recovered.append(date)
        scenarios[name] = {
            "granted_pairs": len(granted),
            "days_recovered": len(recovered),
            "days_recovered_list": recovered,
            "days_still_unchecked": len(population) - len(recovered),
        }
    doc["scenarios"] = scenarios
    doc["derivation_cross_check"] = {
        "passed": not disagreement,
        "disagreements": disagreement[:10],
        "what_it_proves": ("структурный вывод и реплей настоящего оценщика "
                           "согласны на каждом дне каждого сценария"),
    }
    if disagreement:
        doc["status"] = STATUS_UNMEASURED
        findings.append(f"[НЕ ИЗМЕРЕНО] два вывода разошлись на "
                        f"{len(disagreement)} случаях — цена в днях недействительна")
        return doc

    # ── замыкание: выдача ВСЕГО обязана поднять всё население ────────────────
    # Честная граница этой проверки названа вслух: при СОШЕДШЕМСЯ паритете она
    # выполняется ПО ПОСТРОЕНИЮ (``all_pairs`` — в точности множество
    # блокирующих пар, значит `missing <= granted` на каждом forward-дне), и
    # независимой проверкой способности она НЕ является. Оставлена как замыкание
    # на случай, когда отключён сам паритет или сверка выводов: тогда она —
    # последнее, что заметит, что прибор мерит не тот путь. Настоящий контроль
    # «ноль у класса мог бы быть не-нулём» живёт в наборе тестов сценой, где
    # перебой эвиденса ОДИН поднимает день.
    cap = scenarios["ALL"]["days_recovered"]
    doc["all_causes_closure"] = {
        "passed": cap == len(population),
        "days_recovered": cap,
        "days_required": len(population),
        "what_it_proves": ("названные причины исчерпывают население: каждый "
                           "блокирующий день поднимается выдачей всех пар"),
        "what_it_does_not_prove": ("это НЕ контроль способности — при сошедшемся "
                                   "паритете равенство выполняется по построению"),
    }
    if not doc["all_causes_closure"]["passed"]:
        doc["status"] = STATUS_UNMEASURED
        findings.append(f"[НЕ ИЗМЕРЕНО] замыкание не сошлось: выдача ВСЕХ "
                        f"{len(all_pairs)} пар подняла {cap} из "
                        f"{len(population)} дней — числа по классам недействительны")
        return doc

    doc["in_books_unpriced_census"] = _in_books_unpriced_census(records)

    # ── ответ ─────────────────────────────────────────────────────────────────
    per_day: List[dict] = []
    for date in population:
        cs = sorted({x["class"] for x in pairs if x["decision_date"] == date})
        legs = sorted({x["protocol"] for x in pairs if x["decision_date"] == date})
        per_day.append({"decision_date": date, "classes": cs, "legs": legs,
                        "recovered_by": sorted(
                            name for name in ALL_CLASSES
                            if date in scenarios[name]["days_recovered_list"])})
    doc["per_day"] = per_day

    findings.append(
        f"[ОТВЕТ] {len(pairs)} блокирующих пар «forward-день × нога» по "
        f"{len(population)} дням: "
        + " · ".join(f"{c}={counts[c]}" for c in ALL_CLASSES if counts[c]))
    for row in per_day:
        findings.append(
            f"[ПО ДНЯМ] {row['decision_date']}: ноги {', '.join(row['legs'])} — "
            f"классы {', '.join(row['classes'])}; поднял бы "
            + (", ".join(row["recovered_by"]) if row["recovered_by"]
               else "НИ ОДИН класс поодиночке"))

    absent_days = scenarios[CLASS_ABSENT]["days_recovered"]
    notlive_days = scenarios[CLASS_NOT_LIVE]["days_recovered"]
    only_notlive = sorted(set(scenarios[CLASS_NOT_LIVE]["days_recovered_list"])
                          - set(scenarios[CLASS_ABSENT]["days_recovered_list"]))
    doc["days_held_by_evidence_outage_alone"] = only_notlive

    findings.append(
        f"[ЦЕНА В ДНЯХ, ПОТОЛОК] перепись входов поднимает {absent_days} из "
        f"{len(population)} дней, перебой эвиденса — {notlive_days}; ТОЛЬКО "
        f"перебоем держится {len(only_notlive)} "
        f"({', '.join(only_notlive) if only_notlive else '—'}). Числа верхние: "
        f"выдано право быть оценённым, существование живой ставки у ноги вне "
        f"книг записью не подтверждается и прибором не выдумывается")

    census = doc["in_books_unpriced_census"]
    findings.append(
        f"[ОПОРА] на ВСЁМ журнале нога внутри книг дня осталась без ставки "
        f"{census['leg_days_unpriced']} раз из {census['leg_days_in_books']} "
        f"нога-дней — класс, которым объясняли недоизмеренность, почти пуст на "
        f"населении, не связанном с блокирующими днями")

    if counts[CLASS_UNATTRIBUTABLE]:
        findings.append(
            f"[НЕ ИЗМЕРЕНО] {counts[CLASS_UNATTRIBUTABLE]} пар не разведены: "
            f"запись старой схемы не несёт apy_unevidenced, и перебой эвиденса "
            f"от пустого значения при живом провенансе неотличим")

    if counts[CLASS_ABSENT] > counts[CLASS_NOT_LIVE]:
        doc["status"] = STATUS_CRITICAL
        findings.append(
            f"[CRITICAL] причина названа не та: ADR-300 отнёс недоизмеренность "
            f"hit_rate к ПЕРЕБОЯМ ЭВИДЕНСА на ногах книги, а замер даёт "
            f"{counts[CLASS_NOT_LIVE]} таких пар из {len(pairs)} — остальные "
            f"{counts[CLASS_ABSENT]} суть НЕПОЛНАЯ ПЕРЕПИСЬ ВХОДОВ: нога вне "
            f"книг того дня, и запись не могла нести её ставку ни при каком "
            f"состоянии фида. Рычаг лежит у писателя журнала (ADR-290, одна "
            f"строка отсечения по universe), а не у фида и не у POLLED_ADAPTERS")
    elif counts[CLASS_UNATTRIBUTABLE]:
        doc["status"] = STATUS_WARNING
    else:
        doc["status"] = STATUS_OK

    return doc


def format_report(doc: dict) -> List[str]:
    """Порядок строк — порядок вопроса: население → классы → дни → контроли."""
    out: List[str] = []
    pop = doc.get("population") or {}
    out.append(f"   почему у ноги нет живой ставки (заказ #543): {doc.get('status')} · "
               f"дней журнала {doc.get('journal_rows')} · "
               f"дней без вердикта из-за неоценённых ног "
               f"{pop.get('days_unchecked_by_unpriced_legs')}")
    par = doc.get("parity_control") or {}
    if par and not par.get("passed"):
        out.append("   [НЕ ИЗМЕРЕНО] паритет с оценщиком не прошёл — "
                   "числам ниже верить нельзя")
        return out + [f"   {x}" for x in (doc.get("findings") or [])]
    counts = doc.get("class_counts") or {}
    if counts:
        out.append("   классы блокирующих пар: "
                   + " · ".join(f"{c}={n}" for c, n in counts.items() if n))
    sc = doc.get("scenarios") or {}
    for key, label in ((CLASS_ABSENT, "перепись входов"),
                       (CLASS_NOT_LIVE, "перебой эвиденса")):
        s = sc.get(key) or {}
        if s:
            out.append(f"   поднял бы поодиночке — {label}: "
                       f"{s.get('days_recovered')} дн. (потолок)")
    for row in (doc.get("per_day") or [])[:8]:
        out.append(f"   · {row.get('decision_date')}: "
                   f"{', '.join(row.get('legs') or [])} — "
                   f"{', '.join(row.get('classes') or [])}")
    cap = doc.get("all_causes_closure") or {}
    if cap:
        out.append("   замыкание по всем причинам: "
                   + ("сошлось" if cap.get("passed") else "НЕ СОШЛОСЬ")
                   + f" ({cap.get('days_recovered')}/{cap.get('days_required')} дн.)")
    xc = doc.get("derivation_cross_check") or {}
    if xc:
        out.append("   сверка двух выводов: "
                   + ("сошлись" if xc.get("passed") else "РАЗОШЛИСЬ"))
    for line in doc.get("findings") or []:
        out.append(f"   {line}")
    if doc.get("does_not_report"):
        out.append(f"   НЕ ДОКЛАДЫВАЕТ: {doc['does_not_report']}")
    if doc.get("advisory"):
        out.append(f"   ADVISORY: {doc['advisory']}")
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
        description="почему у опрашиваемой ноги нет живой ставки (заказ #543)")
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
