"""Сколько дней журнала получат ВЕРДИКТ, если закрыть G1 (заказ #541→#542, ADR-299).

Заказ ADR-299 поставлен дословно так:

> Ось C — граница, потому что ``UNCHECKED``-дни не измерены **по построению**: у
> двигаемой ноги нет живой ставки в forward-днях. Вопрос: **сколько из этих 7
> дней станут измеримыми, если закрыть G1** (пины → ``POLLED_ADAPTERS``, 13 из 17
> запинённых ключей сегодня отсутствуют в снимке оркестратора)? Мерить надо не
> «сколько ключей добавится», а **сколько дней журнала получат вердикт** — это
> разные числа, и первое уже не раз выдавали за второе.

Прибор отвечает ровно на этот вопрос и ровно в этих единицах: **дни**, а не
ключи. Ключи он тоже печатает — но как ВХОД возмущения, а не как ответ.

## Почему вопрос про money-path, а не про удобство

``hit_rate`` — не приборная величина, а **критерий взвода**
(``shadow_trigger_eval.MIN_HIT_RATE`` = 0.60, мандат владельца ADR-067). ADR-299
показал, что сегодня он предъявлен как ``PASS`` там, где честный ответ — «не
измерено»: 1.0 посчитан на 15 днях из 35, а порог 0.60 лежит ВНУТРИ интервала
защитимых поправок. Естественное следствие, которое напрашивается само: «закроем
G1 — журнал станет полным, и критерий станет решаемым». Прибор проверяет это
следствие ЗАМЕРОМ, потому что если оно неверно, то работа по G1 не приблизит
взвод ни на день, а очередь будет считать, что приблизит.

## Что значит «закрыть G1» — и почему берётся ПОТОЛОК

Закрытие G1 читается **максимально щедро**: каждый ключ из выданного набора
считается оценённым в КАЖДЫЙ forward-день журнала. Это заведомо больше, чем даст
настоящая проводка (живой фид иногда молчит и у опрашиваемого протокола), и
взято намеренно: **потолок**. Ноль под потолком — это ноль под любым честным
чтением; ноль под полом не значил бы ничего.

Наборов два, и оба ИЗМЕРЕНЫ каноническим производителем ADR-236
(``scripts.measure_pin_placement_effect.pins_invisible_to_the_gate``), а не
выписаны в этот файл руками:

* ``wiring`` — ``not_polled``: класс адаптера есть, оркестратор не спрашивает.
  Это ровно та проводка ``POLLED_ADAPTERS``, которую называет заказ;
* ``max`` — ``not_polled`` ∪ ``no_adapter``: сверх проводки дописаны и те ключи,
  у которых адаптера нет вовсе. Проводкой они не чинятся (ADR-053 запрещает
  константу под маркой ``live``), и в реальный ремонт G1 не входят — но в
  потолок входят, чтобы ответ нельзя было списать на узко взятый набор.

## Ставка не выдумывается: выдаётся ПРАВО БЫТЬ ОЦЕНЁННЫМ, а не число

``_day_gain_usd`` отбраковывает forward-день, когда у двигаемой ноги ставки
**нет** (``None``). Возмущение поэтому подставляет ``_PRICING_SENTINEL_PCT`` =
0.0: нога становится оценимой, а её вклад в ``benefit`` равен РОВНО НУЛЮ.
Выдуманной доходности в числа прибора попасть неоткуда.

Отсюда же граница ответственности, и она названа вслух: прибор отвечает
**«получит ли день вердикт»** и НИКОГДА не печатает, КАКИМ этот вердикт был бы.
Исход ``hit``/``miss`` под сентинелом — артефакт сентинела, а не наблюдение.

**Ловушка заказа названа заранее и соблюдена:** соблазн — посчитать ``hit_rate``
после расширения и предъявить его как «настоящий». Он был бы посчитан на другом
населении, и сравнивать его с 1.0 напрямую нельзя. Прибор такого числа не
считает вовсе (тест это закрепляет).

## Два независимых вывода, и они ОБЯЗАНЫ совпасть

1. **структурный** — день восстанавливается, если найдётся forward-день, у
   которого множество неоценённых двигаемых ног целиком лежит внутри выданного
   набора;
2. **реплей** — настоящий ``_evaluate_verdict`` зовётся на возмущённых копиях
   forward-записей, и смотрится, перестал ли исход быть ``UNCHECKED``.

Расхождение хотя бы на одном дне ⇒ прибор ОТКАЗЫВАЕТ (``UNMEASURED``). Один
вывод — это утверждение о коде, который я сам же и написал; два совпавших —
утверждение о поведении настоящей поверхности решения.

## Обязательные контроли (не сработал ⇒ UNMEASURED, а не «ноль»)

* **ПАРИТЕТ.** При ПУСТОМ наборе реплей обязан воспроизвести исход настоящего
  ``_evaluate_verdict`` **бит в бит по каждому дню журнала**. Не сошлось ⇒
  копирование записей врёт, и все числа ниже недействительны.
* **СПОСОБНОСТЬ.** Возмущение набором ИЗМЕРЕННЫХ блокирующих ног обязано поднять
  хотя бы один день. Без него ноль по G1 был бы вакуумом: неотличимо «G1 не тот
  рычаг» от «прибор не умеет поднимать дни вообще». Набор для контроля
  измеряется из журнала, а не выписывается.

Контроль способности не требуется ровно в одном случае: в населении нет ни
одного дня, восстановимого В ПРИНЦИПЕ (все ``UNCHECKED`` — от отсутствия
forward-дней). Тогда это сказано отдельной строкой, а не спрятано в ноль.

**ADVISORY.** Прибор ничего не чинит: ни ``POLLED_ADAPTERS``, ни пины, ни
``MIN_HIT_RATE``, ни ``TriggerParams``, ни пороги RiskPolicy v1.0, ни потолки
концентрации, ни kill-switch, ни живой трек. Проводка ``POLLED_ADAPTERS`` —
money-path и решение владельца. Живое ``data/`` открывается на запись ровно один
раз — для собственного артефакта.
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

log = logging.getLogger("spa.monitoring.g1_verdict_recoverability")

VERSION = "g1-verdict-recoverability-v1"
OUTPUT_FILENAME = "g1_verdict_recoverability.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Ставка, которой возмущение делает ногу ОЦЕНИМОЙ. Ноль выбран не «для
#: простоты»: при нём вклад ноги в ``benefit`` равен ровно нулю, то есть выдаётся
#: право быть оценённым и НЕ выдаётся доходность. Любое ненулевое число здесь
#: было бы выдуманным наблюдением.
_PRICING_SENTINEL_PCT = 0.0

#: ЕДИНСТВЕННАЯ причина ``UNCHECKED``, которая лечится выдачей ставок. Все
#: прочие (``no_forward_data`` — у дня нет forward-записей вовсе;
#: ``no_target_recorded`` — в записи дня нет цели; ``unknown_verdict:*`` — день
#: оценён, но вердикт не разобран) НЕ лечатся НИ ПРИ КАКОМ наборе, и считать их
#: «не поднятыми G1» значило бы записать в счёт G1 конец окна и дырки записи.
#: Список ведётся ПОЗИТИВНО (что лечится), а не негативно (что не лечится):
#: негативный молча пропустил бы новую причину в восстановимые.
_REASON_RECOVERABLE = "no_evidenced_apy_for_moved_legs"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Наборы возмущения: ИЗМЕРЕНЫ каноническим производителем, не выписаны ──────
def measure_grant_sets(data_dir: Path) -> dict:
    """Два чтения «G1 закрыт», снятые производителем ADR-236.

    Третий исход обязателен: производитель не импортировался или сам ответил
    ``unmeasured`` ⇒ набора НЕТ, и подставлять свой список значило бы ответить на
    вопрос про выдуманный G1. Никакой запасной копии списка здесь не лежит
    намеренно — вторая копия набора разошлась бы с первой молча.
    """
    try:
        from scripts.measure_pin_placement_effect import pins_invisible_to_the_gate
    except Exception as exc:  # noqa: BLE001 — молчание здесь = fail-OPEN
        return {"unmeasured": f"производитель набора G1 не импортирован: "
                              f"{type(exc).__name__}: {exc}"}
    try:
        res = pins_invisible_to_the_gate(Path(data_dir))
    except Exception as exc:  # noqa: BLE001
        return {"unmeasured": f"производитель набора G1 отказал: "
                              f"{type(exc).__name__}: {exc}"}
    if res.get("unmeasured"):
        return {"unmeasured": f"набор G1 не измерен производителем: "
                              f"{res['unmeasured']}"}
    not_polled = sorted(res.get("not_polled") or [])
    no_adapter = sorted(res.get("no_adapter") or [])
    if not not_polled and not no_adapter:
        # Не отказ: G1 закрыт. Пустые наборы — валидный вход, и вопрос
        # вырождается («поднимать нечем, потому что поднимать нечего»).
        pass
    return {
        "unmeasured": None,
        "pinned_total": res.get("checked"),
        "polled_total": res.get("polled"),
        "wiring": not_polled,
        "no_adapter": no_adapter,
        "max": sorted(set(not_polled) | set(no_adapter)),
    }


def _polled_keys(data_dir: Path) -> Tuple[Set[str], Optional[str]]:
    """Ключи, которые снимок оркестратора ФАКТИЧЕСКИ несёт (для атрибуции ног)."""
    try:
        doc = json.loads((Path(data_dir) / "adapter_orchestrator_status.json")
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return set(), f"снимок оркестратора не прочитан: {type(exc).__name__}: {exc}"
    keys = {str(a.get("protocol")) for a in (doc.get("adapters") or [])
            if isinstance(a, dict) and a.get("protocol")}
    if not keys:
        return set(), "в снимке оркестратора нет ни одного протокола"
    return keys, None


# ── Возмущение forward-записей ────────────────────────────────────────────────
def grant_pricing(forward: Sequence[dict], grant: Set[str]) -> List[dict]:
    """Копии forward-записей, где ключам из ``grant`` выдано ПРАВО быть оценёнными.

    Копия глубокая: возмущение не смеет тронуть записи, по которым считается
    базовая линия, — иначе паритет сравнивал бы возмущённое с возмущённым и
    прошёл бы всегда.
    """
    out: List[dict] = []
    for rec in forward:
        c = copy.deepcopy(rec)
        apy = c.get("apy_evidenced_pct")
        if not isinstance(apy, dict):
            apy = {}
        for key in grant:
            if apy.get(key) is None:
                apy[key] = _PRICING_SENTINEL_PCT
        c["apy_evidenced_pct"] = apy
        out.append(c)
    return out


def _structural_recovers(deltas: Dict[str, float], forward: Sequence[dict],
                         horizon: int, grant: Set[str]) -> bool:
    """Вывод №1 — по форме входа, БЕЗ вызова оценщика.

    День восстанавливается, если найдётся forward-день, у которого неоценённые
    двигаемые ноги целиком лежат внутри выданного набора. Достаточно ОДНОГО
    такого дня: ``_evaluate_verdict`` выносит вердикт при ``checked >= 1``.
    """
    for frec in list(forward)[:horizon]:
        apy = frec.get("apy_evidenced_pct") or {}
        missing = {p for p in deltas if apy.get(p) is None}
        if missing <= grant:
            return True
    return False


def _replay_outcome(rec: dict, forward: Sequence[dict], horizon: int,
                    grant: Set[str]) -> dict:
    """Вывод №2 — НАСТОЯЩИЙ ``_evaluate_verdict`` на возмущённых копиях."""
    from spa_core.paper_trading.shadow_trigger_eval import _evaluate_verdict

    return _evaluate_verdict(rec, grant_pricing(forward, grant), horizon)


# ── Замер ─────────────────────────────────────────────────────────────────────
def measure(data_dir: Path, *, now: Optional[datetime] = None,
            book_id: Optional[str] = None,
            horizon_days: Optional[int] = None) -> dict:
    """Ответ заказу #541: сколько ДНЕЙ поднимет закрытие G1."""
    from spa_core.paper_trading.shadow_trigger_eval import (
        DEFAULT_HORIZON_DAYS, _deltas, _evaluate_verdict, load_history,
    )

    now = now or _utcnow()
    horizon = int(horizon_days or DEFAULT_HORIZON_DAYS)
    ddir = Path(data_dir)

    doc: dict = {
        "version": VERSION,
        "generated_at": now.isoformat(),
        "question": ("сколько UNCHECKED-дней журнала получат ВЕРДИКТ, если "
                     "закрыть G1 (пины → POLLED_ADAPTERS); единица ответа — ДНИ"),
        "horizon_days": horizon,
        "status": STATUS_UNMEASURED,
        "findings": [],
        "advisory": ("POLLED_ADAPTERS, пины, MIN_HIT_RATE, TriggerParams, пороги "
                     "RiskPolicy v1.0, потолки концентрации, kill-switch и живой "
                     "трек НЕ тронуты, капитал не сдвинут; проводка "
                     "POLLED_ADAPTERS — money-path и решение владельца"),
        "does_not_report": ("hit_rate после расширения — НЕ считается намеренно "
                            "(ловушка заказа): он был бы посчитан на другом "
                            "населении, и сравнивать его с 1.0 нельзя. Прибор "
                            "отвечает «получит ли день вердикт», а не «каким он "
                            "будет»"),
    }
    f: List[str] = doc["findings"]

    # ── вход 1: журнал решений ────────────────────────────────────────────────
    records, bad = load_history(ddir, book_id)
    doc["journal_rows"] = len(records)
    doc["journal_unparseable"] = bad
    if not records:
        f.append("[НЕ ИЗМЕРЕНО] журнал решений пуст или не прочитан — "
                 "населения вопроса нет")
        return doc

    by_date = {str(r.get("cycle_date")): r for r in records}
    dates = sorted(by_date)

    # ── вход 2: наборы G1 ─────────────────────────────────────────────────────
    grants = measure_grant_sets(ddir)
    if grants.get("unmeasured"):
        doc["grant_sets"] = {"unmeasured": grants["unmeasured"]}
        f.append(f"[НЕ ИЗМЕРЕНО] {grants['unmeasured']} — «G1 не поднял дней» и "
                 f"«набор G1 неизвестен» это РАЗНЫЕ факты")
        return doc
    doc["grant_sets"] = {
        "pinned_total": grants["pinned_total"],
        "polled_total": grants["polled_total"],
        "wiring": grants["wiring"],
        "no_adapter": grants["no_adapter"],
        "max": grants["max"],
        "reading": ("ПОТОЛОК: каждый ключ набора считается оценённым в КАЖДЫЙ "
                    "forward-день — щедрее, чем даст настоящая проводка"),
    }
    grant_wiring = set(grants["wiring"])
    grant_max = set(grants["max"])

    # ── базовая линия: настоящий оценщик, невозмущённые записи ────────────────
    baseline: Dict[str, dict] = {}
    forward_of: Dict[str, List[dict]] = {}
    for i, dt in enumerate(dates):
        fw = [by_date[x] for x in dates[i + 1:i + 1 + horizon]]
        forward_of[dt] = fw
        baseline[dt] = _evaluate_verdict(by_date[dt], fw, horizon)

    population = [dt for dt in dates if baseline[dt]["outcome"] == "UNCHECKED"]
    in_principle = [dt for dt in population
                    if str(baseline[dt].get("unchecked_reason") or "")
                    == _REASON_RECOVERABLE]
    beyond = [dt for dt in population if dt not in set(in_principle)]
    doc["population"] = {
        "days_total": len(dates),
        "unchecked": len(population),
        "unchecked_days": population,
        "recoverable_in_principle": len(in_principle),
        "beyond_any_grant": len(beyond),
        "beyond_any_grant_days": beyond,
        "beyond_reasons": sorted({str(baseline[dt].get("unchecked_reason") or "?")
                                  for dt in beyond}),
        "beyond_reason": ("причина не в отсутствии ставки (нет forward-записей "
                          "вовсе / нет цели в записи / вердикт не разобран) — "
                          "выдача ставок не лечит это НИ ПРИ КАКОМ наборе"),
    }

    # ── контроль ПАРИТЕТА: пустой набор обязан воспроизвести базу бит в бит ───
    parity_mismatch: List[str] = []
    for dt in dates:
        replayed = _replay_outcome(by_date[dt], forward_of[dt], horizon, set())
        if replayed != baseline[dt]:
            parity_mismatch.append(dt)
    doc["parity_control"] = {
        "passed": not parity_mismatch,
        "days_compared": len(dates),
        "mismatch_days": parity_mismatch[:10],
        "what_it_proves": ("возмущение копирует записи ЧЕСТНО: при пустом наборе "
                           "реплей = настоящий _evaluate_verdict бит в бит"),
    }
    if parity_mismatch:
        doc["status"] = STATUS_UNMEASURED
        f.append(f"[НЕ ИЗМЕРЕНО] контроль паритета не прошёл на "
                 f"{len(parity_mismatch)} дн. — копирование записей врёт, "
                 f"числа ниже недействительны")
        return doc

    # ── блокирующие ноги: ИЗМЕРЕНЫ из журнала ────────────────────────────────
    blocking: Dict[str, List[str]] = {}
    for dt in in_principle:
        deltas = _deltas(by_date[dt])
        legs: Set[str] = set()
        for frec in forward_of[dt][:horizon]:
            apy = frec.get("apy_evidenced_pct") or {}
            legs |= {p for p in deltas if apy.get(p) is None}
        for leg in legs:
            blocking.setdefault(leg, []).append(dt)
    grant_capability = set(blocking)

    polled_now, polled_err = _polled_keys(ddir)
    attribution: List[dict] = []
    for leg in sorted(blocking, key=lambda k: (-len(blocking[k]), k)):
        if leg in grant_wiring:
            cls = "g1_not_polled"
        elif leg in set(grants["no_adapter"]):
            cls = "g1_no_adapter"
        elif polled_err:
            cls = "UNMEASURED"
        elif leg in polled_now:
            cls = "polled_but_unevidenced"
        else:
            cls = "unpinned_and_unpolled"
        attribution.append({"protocol": leg, "days_blocked": len(blocking[leg]),
                            "days": sorted(blocking[leg]), "class": cls})
    doc["blocking_legs"] = attribution
    doc["blocking_legs_class_note"] = {
        "g1_not_polled": "класс адаптера есть, оркестратор не спрашивает — ЭТО и есть G1",
        "g1_no_adapter": "пин есть, адаптера нет вовсе — проводкой не чинится (ADR-053)",
        "polled_but_unevidenced": ("оркестратор СПРАШИВАЕТ этот протокол, а ставки в "
                                   "тот день всё равно нет — перебои эвиденса, НЕ G1"),
        "unpinned_and_unpolled": "ни пина, ни опроса — вне обоих наборов",
        "UNMEASURED": "снимок оркестратора не прочитан, класс ноги не назван",
    }
    if polled_err:
        f.append(f"[НЕ ИЗМЕРЕНО] класс блокирующих ног не назван: {polled_err}")

    # ── контроль СПОСОБНОСТИ: измеренные блокеры обязаны поднять хотя бы день ─
    cap_recovered = [dt for dt in in_principle
                     if _structural_recovers(_deltas(by_date[dt]), forward_of[dt],
                                             horizon, grant_capability)]
    capability_required = bool(in_principle)
    doc["capability_control"] = {
        "required": capability_required,
        "passed": (not capability_required) or bool(cap_recovered),
        "grant": sorted(grant_capability),
        "grant_provenance": "ИЗМЕРЕН из журнала: ноги, блокирующие хоть один день",
        "days_recovered": len(cap_recovered),
        "what_it_proves": ("прибор УМЕЕТ поднимать дни; без этого ноль по G1 был бы "
                           "вакуумом — неотличимо «G1 не тот рычаг» от «прибор не "
                           "поднимает никогда»"),
    }
    if capability_required and not cap_recovered:
        doc["status"] = STATUS_UNMEASURED
        f.append("[НЕ ИЗМЕРЕНО] контроль способности не сработал: даже выдача ВСЕХ "
                 "измеренных блокирующих ног не подняла ни одного дня — прибор "
                 "мерит не тот путь, и ноль по G1 ничего не значит")
        return doc

    # ── собственно ответ, двумя выводами ──────────────────────────────────────
    scenarios: Dict[str, dict] = {}
    disagreement: List[str] = []
    for name, grant in (("g1_wiring", grant_wiring), ("g1_max", grant_max)):
        recovered: List[str] = []
        for dt in in_principle:
            deltas = _deltas(by_date[dt])
            struct = _structural_recovers(deltas, forward_of[dt], horizon, grant)
            replay = (_replay_outcome(by_date[dt], forward_of[dt], horizon, grant)
                      ["outcome"] != "UNCHECKED")
            if struct != replay:
                disagreement.append(f"{name}:{dt}")
            elif struct:
                recovered.append(dt)
        scenarios[name] = {
            "grant_keys": sorted(grant),
            "grant_key_count": len(grant),
            "days_recovered": len(recovered),
            "days_recovered_list": recovered,
            "days_still_unchecked": len(population) - len(recovered),
            "scanned_days": in_principle,
        }
    doc["scenarios"] = scenarios
    doc["derivation_cross_check"] = {
        "passed": not disagreement,
        "disagreements": disagreement[:10],
        "what_it_proves": ("структурный вывод и реплей настоящего оценщика согласны; "
                           "один вывод был бы утверждением о моём же коде"),
    }
    if disagreement:
        doc["status"] = STATUS_UNMEASURED
        f.append(f"[НЕ ИЗМЕРЕНО] два вывода разошлись на {len(disagreement)} "
                 f"случаях — ответ недействителен")
        return doc

    # ── вердикт ───────────────────────────────────────────────────────────────
    wiring_days = scenarios["g1_wiring"]["days_recovered"]
    max_days = scenarios["g1_max"]["days_recovered"]
    n_g1_legs = sum(1 for a in attribution if a["class"].startswith("g1_"))
    n_intermittent = sum(1 for a in attribution
                         if a["class"] == "polled_but_unevidenced")

    f.append(
        f"[ОТВЕТ] закрытие G1 поднимает {wiring_days} из {len(population)} "
        f"UNCHECKED-дней (проводка {len(grant_wiring)} ключей); при ПОТОЛКЕ "
        f"(+{len(grants['no_adapter'])} ключа без адаптера) — {max_days}. "
        f"Единица ответа ДНИ: ключей добавляется {len(grant_max)}, дней "
        f"поднимается {max_days} — это и есть те два разных числа, которые заказ "
        f"велел не путать")

    if in_principle:
        f.append(
            f"[КОНТРОЛЬ] способность доказана: выдача {len(grant_capability)} "
            f"ИЗМЕРЕННЫХ блокирующих ног поднимает {len(cap_recovered)} из "
            f"{len(in_principle)} восстановимых в принципе дней — положительный "
            f"результат был достижим, значит ноль выше честный")

    if beyond:
        f.append(
            f"[ЦЕНА] {len(beyond)} из {len(population)} дней не поднимет НИКАКОЙ "
            f"набор: {', '.join(beyond)} — {doc['population']['beyond_reason']}")

    if max_days == 0 and in_principle:
        doc["status"] = STATUS_CRITICAL
        f.append(
            f"[CRITICAL] названный рычаг не поднимает НИ ОДНОГО дня: из "
            f"{len(attribution)} блокирующих ног к G1 относится {n_g1_legs}, а "
            f"{n_intermittent} — протоколы, которые оркестратор УЖЕ спрашивает, "
            f"и ставки в тот день всё равно нет. Значит недоизмеренность "
            f"hit_rate (ADR-299) держится не проводкой POLLED_ADAPTERS, а "
            f"ПЕРЕБОЯМИ ЭВИДЕНСА на ногах книги; закрытие G1 не сделает критерий "
            f"взвода решаемым, и ждать этого от него — ошибка адресации")
    elif max_days < len(in_principle):
        doc["status"] = STATUS_WARNING
        f.append(
            f"[ЦЕНА] G1 поднимает {max_days} из {len(in_principle)} восстановимых "
            f"дней — остальные держат ноги вне обоих наборов; критерий взвода "
            f"после закрытия G1 останется посчитанным на неполном населении")
    else:
        doc["status"] = STATUS_OK
        f.append(
            f"[ОТВЕТ] G1 поднимает ВСЕ {len(in_principle)} восстановимых дней — "
            f"проводка закрывает недоизмеренность населения целиком")

    return doc


# ── Отрисовка для шага 0-офис ─────────────────────────────────────────────────
def format_report(doc: dict) -> List[str]:
    """Порядок строк — порядок вопроса: население → ответ в ДНЯХ → ноги → контроли."""
    out: List[str] = []
    pop = doc.get("population") or {}
    out.append(f"   поднимет ли G1 дни журнала (заказ #541): {doc.get('status')} · "
               f"дней журнала {doc.get('journal_rows')} · "
               f"без вердикта {pop.get('unchecked')} "
               f"(восстановимых в принципе {pop.get('recoverable_in_principle')})")
    par = doc.get("parity_control") or {}
    if par and not par.get("passed"):
        out.append("   [НЕ ИЗМЕРЕНО] контроль паритета не прошёл — "
                   "числам ниже верить нельзя")
    sc = doc.get("scenarios") or {}
    for key, label in (("g1_wiring", "проводка POLLED_ADAPTERS"),
                       ("g1_max", "потолок (+ключи без адаптера)")):
        s = sc.get(key) or {}
        if not s:
            continue
        out.append(f"   {label}: ключей {s.get('grant_key_count')} ⇒ "
                   f"ДНЕЙ поднято {s.get('days_recovered')} "
                   f"(осталось без вердикта {s.get('days_still_unchecked')})")
    for a in (doc.get("blocking_legs") or [])[:8]:
        out.append(f"   · {a.get('protocol')}: блокирует {a.get('days_blocked')} дн. "
                   f"— {a.get('class')}")
    cap = doc.get("capability_control") or {}
    if cap.get("required"):
        out.append("   контроль способности: "
                   + ("сработал" if cap.get("passed") else "НЕ СРАБОТАЛ")
                   + f" ({cap.get('days_recovered')} дн. поднято измеренными блокерами)")
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
                    or x.startswith("[КОНТРОЛЬ]")),
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
        description="сколько дней журнала поднимет закрытие G1 (заказ #541)")
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
