"""Что теряет ``hit_rate`` от правила «одна строка в день» (заказ #552, ADR-314).

Заказ цикла #552 поставлен дословно так:

> **Что именно теряет ``hit_rate``, считая по одной строке в день вместо всех
> решений дня?** Верхняя граница потери НАСЕЛЕНИЯ известна (206 прогонов вне
> журнала на 17 днях), но ``hit_rate`` считается по ВЕРДИКТАМ: сколько дней из
> 36 имели внутри себя прогоны с РАЗНЫМИ вердиктами, и совпал ли выживший
> вердикт с большинством своего дня.

И назвал ловушку заранее: вердиктов стёртых прогонов в журнале нет ПО
ПОСТРОЕНИЮ, а восстанавливать их по ``risk_verdict`` из ``audit_trail`` нельзя
без доказательства, что это тот же предмет. Отсюда порядок исполнения, заданный
самим заказом: **что поддаётся замеру на ПРОШЛОМ, обязано быть первым
результатом; не поддаётся ⇒ третий исход, а не подстановка соседней величины.**

Прибор устроен ровно по этому порядку, и его три слоя отвечают на три РАЗНЫХ
вопроса. Смешать их — значит верно ответить не на тот вопрос.

## Слой 1 — ЭКСПОЗИЦИЯ. Измеримо целиком, и это первый результат

``hit_rate`` — не приборная величина, а **критерий взвода**
(``shadow_trigger_eval.MIN_HIT_RATE`` = 0.60, мандат владельца ADR-067). Его
знаменатель — ``scored``-дни: не ``trivial`` и с исходом ``hit``/``miss``.
Первый вопрос поэтому не «каким был стёртый вердикт», а **на скольких прогонах
стои́т каждый день знаменателя** — и это измеряется без единого допущения:
день журнала сопоставляется с прогонами того же дня из ``audit_trail``
(``cycle_start``, опознание по ``correlation_id``, как в ADR-314).

Исходов ровно три, и третий не растворяется в первых двух: день с ОДНИМ
прогоном (терять нечего), день с НЕСКОЛЬКИМИ (выжила одна строка из N) и день,
которого в носителе прогонов НЕТ ВОВСЕ — там население **не измерено**, и это
не то же самое, что «прогон был один». Носитель покрывает 19 дней журнала из
36; выдать молчание носителя за единицу значило бы изготовить чистый знаменатель
из неизмеренного.

## Слой 2 — ДВИЖЕНИЕ ВХОДА. Измеримо ВНУТРИ предмета, с контролем на реконструкцию

Вердикт тени детерминирован своими входами, и один из них — ``current_positions``
— журнал несёт САМ, в собственной строке. Значит вопрос «могли ли прогоны дня
разойтись» имеет измеримую нижнюю границу, не выходящую за предмет: **сколько
РАЗНЫХ значений ``current_positions`` видели прогоны дня.**

Книга восстанавливается по ``trade_executed`` (``from_allocation`` первой сделки
— затравка, дальше ``to_allocation`` каждой), и каждому прогону присваивается
состояние на момент его ``cycle_start``.

**Реконструкция не принимается на веру — у неё обязательный контроль ТОЖДЕСТВОМ
ЗНАЧЕНИЯ.** Состояние, присвоенное ВЫЖИВШЕМУ прогону дня, обязано совпасть с
``current_positions`` строки журнала этого дня — с полем, которое написал сам
писатель. Не совпало хоть на одном сравнимом дне ⇒ слой 2 целиком
``UNMEASURED`` с названной причиной. Отрицательный результат («входы не
двигались») без этого контроля не стоил бы ничего: он неотличим от сломанной
реконструкции.

Отсюда же граница ответственности, и она названа вслух: расхождение входа
**НЕ ЕСТЬ** расхождение вердикта. Прибор НИКОГДА не печатает, каким был бы
вердикт стёртого прогона.

## Слой 3 — ГЛАВНЫЙ ОТКАЗ. Третий исход, и он не подменяется соседней величиной

Каким был вердикт стёртого прогона — **НЕ ИЗМЕРЕНО и измерено быть не может**:
единственным носителем вердикта прогона была строка журнала, которую замена
уничтожила. Потеря неизмерима ПОТОМУ, что она произошла.

Соблазн, названный заказом, — взять ``risk_verdict``/``allocation_proposal`` из
``audit_trail``: они пишутся НА КАЖДЫЙ прогон и выглядят готовой заменой.
Прибор их не подставляет и **доказывает замером**, что подставлять нельзя: у
ВЫЖИВШЕГО прогона каждого дня сверяются ``allocation_proposal.target_usd`` (цель
живого аллокатора) и ``target_positions`` (цель теневого триггера ADR-060).
Это один и тот же прогон и один и тот же день — если бы величины были одним
предметом, они совпали бы здесь. Расходятся ⇒ род величин РАЗНЫЙ, и запись
живого пути не свидетельствует о вердикте тени. Совпадение имён — не совпадение
величин.

Доказательство пересчитывается КАЖДЫЙ прогон, а не цитируется из ADR: если
однажды предметы сойдутся, прибор обязан это увидеть, а не помнить старый ответ.

## ADVISORY

Прибор ничего не чинит и не предлагает чинить молча. Ни писатель журнала и его
правило замены строки дня (``allocation_rationale.append_rationale_history``),
ни ``POLLED_ADAPTERS``, ни пины, ни ``MIN_HIT_RATE``, ни ``TriggerParams``, ни
пороги RiskPolicy v1.0, ни потолки концентрации, ни стоп-кран, ни живой трек не
трогаются, капитал не двигается. Живое ``data/`` открывается на запись ровно
один раз — для собственного артефакта.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.utils.observation import observed, observed_number

log = logging.getLogger(__name__)

OUTPUT_FILENAME = "day_replacement_verdict_loss.json"
HISTORY_FILENAME = "allocation_rationale_history.jsonl"
AUDIT_FILENAME = "audit_trail.jsonl"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Разряд округления книги. Сделки и журнал пишут центы; сравнивать float'ы
#: без сетки значило бы объявлять расхождением последний бит представления.
_CENTS = 2

#: Класс дня по населению прогонов. Третий — не ноль и не единица.
POP_SINGLE = "single_run"
POP_MULTI = "multi_run"
POP_UNMEASURED = "population_unmeasured"


# ─────────────────────────── чтение носителей ───────────────────────────


def _read_jsonl(path: Path) -> Tuple[List[dict], int]:
    """Возвращает (строки, число нечитаемых). Отсутствие файла — не ноль строк."""
    if not path.exists():
        return [], -1
    rows: List[dict] = []
    bad = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except (ValueError, TypeError):
                bad += 1
    return rows, bad


def _norm_book(book) -> Optional[Dict[str, float]]:
    """Книга на сетке центов, без нулевых ног.

    Нулевая нога и отсутствующая нога — одно и то же состояние капитала, и
    считать их разными значило бы объявить движением смену формы записи.
    """
    if not isinstance(book, dict):
        return None
    out: Dict[str, float] = {}
    for key, value in book.items():
        try:
            amount = round(float(value), _CENTS)
        except (TypeError, ValueError):
            return None
        if amount != 0.0:
            out[str(key)] = amount
    return out


def _key(book: Optional[Dict[str, float]]) -> Optional[str]:
    return None if book is None else json.dumps(book, sort_keys=True)


# ─────────────────────────── слой 1: экспозиция ───────────────────────────


def _runs_by_day(audit_rows: List[dict]) -> Dict[str, List[dict]]:
    """Прогоны, опознанные по ``cycle_start``, разложенные по дню цикла.

    Опознание идёт ``correlation_id``-ом, а датировка — полем ``cycle_date``
    самого события, а не первыми десятью символами отметки: прогон, начатый
    после полуночи UTC, принадлежит своему циклу, а не своей минуте.
    """
    by_day: Dict[str, List[dict]] = {}
    for row in audit_rows:
        if row.get("event_type") != "cycle_start":
            continue
        day = (row.get("data") or {}).get("cycle_date")
        cid = row.get("correlation_id")
        ts = row.get("timestamp")
        if not day or not cid or not ts:
            continue
        by_day.setdefault(str(day), []).append(
            {"correlation_id": cid, "timestamp": str(ts)})
    for runs in by_day.values():
        runs.sort(key=lambda r: r["timestamp"])
    return by_day


# ─────────────────────────── слой 2: движение входа ───────────────────────


def _book_timeline(audit_rows: List[dict]) -> List[Tuple[str, Dict[str, float]]]:
    """Хронология книги: (отметка, состояние ПОСЛЕ этой отметки).

    Затравка — ``from_allocation`` ПЕРВОЙ сделки: состояние до неё. Дальше
    каждая сделка кладёт своё ``to_allocation``. Сделки, у которых книга не
    разбирается, пропускаются — и это видно по числу пропущенных, а не молча.
    """
    trades = sorted(
        [r for r in audit_rows
         if r.get("event_type") == "trade_executed" and r.get("timestamp")],
        key=lambda r: str(r["timestamp"]))
    timeline: List[Tuple[str, Dict[str, float]]] = []
    for i, trade in enumerate(trades):
        data = trade.get("data") or {}
        ts = str(trade["timestamp"])
        if i == 0:
            seed = _norm_book(data.get("from_allocation"))
            if seed is not None:
                timeline.append(("", seed))
        after = _norm_book(data.get("to_allocation"))
        if after is not None:
            timeline.append((ts, after))
    return timeline


def _state_at(timeline: List[Tuple[str, Dict[str, float]]],
              ts: str) -> Optional[Dict[str, float]]:
    """Состояние книги на момент ``ts``: последняя запись с отметкой <= ts."""
    if not timeline:
        return None
    state = None
    for stamp, book in timeline:
        if stamp <= ts:
            state = book
        else:
            break
    return state


# ─────────────────────────── слой 3: род величин ──────────────────────────


def _subject_distinctness(audit_rows: List[dict],
                          journal_by_day: Dict[str, dict],
                          runs_by_day: Dict[str, List[dict]]) -> dict:
    """Один ли предмет `target_usd` живого пути и `target_positions` тени.

    Сверяются величины ОДНОГО прогона (выжившего) и ОДНОГО дня. Совпали бы —
    подстановка была бы законна; расходятся — род величин разный.
    """
    proposals = {}
    for row in audit_rows:
        if row.get("event_type") == "allocation_proposal":
            cid = row.get("correlation_id")
            if cid is not None:
                proposals.setdefault(cid, row)

    same = 0
    different = 0
    no_pair = 0
    examples: List[dict] = []
    for day in sorted(runs_by_day):
        record = journal_by_day.get(day)
        if record is None:
            continue
        survivor = runs_by_day[day][-1]["correlation_id"]
        proposal = proposals.get(survivor)
        if proposal is None:
            no_pair += 1
            continue
        live = _norm_book((proposal.get("data") or {}).get("target_usd"))
        shadow = _norm_book(record.get("target_positions"))
        if live is None or shadow is None:
            no_pair += 1
            continue
        if live == shadow:
            same += 1
        else:
            different += 1
            if len(examples) < 3:
                examples.append({
                    "cycle_date": day,
                    "only_in_live_target_usd": sorted(set(live) - set(shadow)),
                    "only_in_shadow_target_positions": sorted(set(shadow) - set(live)),
                    "shared_keys_disagreeing": sum(
                        1 for k in set(live) & set(shadow) if live[k] != shadow[k]),
                })
    compared = same + different
    return {
        "days_compared": compared,
        "same_subject_days": same,
        "different_subject_days": different,
        "days_without_pair": no_pair,
        "examples": examples,
        # Подстановка законна ТОЛЬКО если предметы сошлись везде, где сравнимы.
        # Ноль сравнимых дней — не «сошлись», а «нечем мерить».
        "substitution_admissible": (compared > 0 and different == 0),
    }


# ─────────────────────────────── замер ────────────────────────────────────


def measure(data_dir: Path, *, now: Optional[datetime] = None) -> dict:
    """Полный замер. Читает только диск; ничего не пишет."""
    data_dir = Path(data_dir)
    generated_at = (now or datetime.now(timezone.utc)).isoformat()

    journal_rows, journal_bad = _read_jsonl(data_dir / HISTORY_FILENAME)
    audit_rows, audit_bad = _read_jsonl(data_dir / AUDIT_FILENAME)

    def refuse(reason: str) -> dict:
        return {
            "generated_at": generated_at,
            "version": "v1",
            "status": STATUS_UNMEASURED,
            "unmeasured_reason": reason,
            "journal_rows": len(journal_rows),
            "exposure": None,
            "input_movement": None,
            "reconstruction_control": None,
            "subject_distinctness": None,
            "days": [],
            "findings": [f"[НЕ ИЗМЕРЕНО] {reason}"],
            "third_outcomes": [reason],
            "does_not_report": _DOES_NOT_REPORT,
            "advisory": _ADVISORY,
        }

    if journal_bad == -1:
        return refuse(f"журнал решений не прочитан: {HISTORY_FILENAME} отсутствует")
    if not journal_rows:
        return refuse(f"журнал решений пуст: {HISTORY_FILENAME}")
    if audit_bad == -1:
        return refuse(f"носитель прогонов не прочитан: {AUDIT_FILENAME} отсутствует")

    journal_by_day: Dict[str, dict] = {}
    for record in journal_rows:
        day = record.get("cycle_date")
        if day:
            journal_by_day[str(day)] = record
    if not journal_by_day:
        return refuse("ни одна строка журнала не несёт `cycle_date`")

    runs_by_day = _runs_by_day(audit_rows)
    if not runs_by_day:
        return refuse(
            f"в {AUDIT_FILENAME} нет ни одного события `cycle_start` — "
            "население прогонов измерить нечем")

    # ── слой 1: экспозиция знаменателя ──
    scored_days = _scored_days(data_dir)

    timeline = _book_timeline(audit_rows)
    days: List[dict] = []
    control_matched = 0
    control_mismatched = 0
    control_no_pair = 0

    for day in sorted(journal_by_day):
        record = journal_by_day[day]
        runs = runs_by_day.get(day)
        entry: dict = {
            "cycle_date": day,
            "in_hit_rate_denominator": (day in scored_days) if scored_days is not None
                                       else None,
            "journal_verdict": record.get("verdict"),
        }
        if not runs:
            entry.update({
                "population_class": POP_UNMEASURED,
                "runs": None,
                "erased_runs": None,
                "distinct_positions": None,
                "survivor_state_is_majority": None,
                "runs_disagreeing_with_survivor": None,
                "reason": "дня нет в носителе прогонов — население не измерено",
            })
            days.append(entry)
            continue

        entry["runs"] = len(runs)
        entry["erased_runs"] = len(runs) - 1
        entry["population_class"] = POP_MULTI if len(runs) > 1 else POP_SINGLE

        states = [_state_at(timeline, r["timestamp"]) for r in runs]
        survivor_state = states[-1]
        journal_state = _norm_book(record.get("current_positions"))

        # Контроль реконструкции ТОЖДЕСТВОМ ЗНАЧЕНИЯ: присвоенное выжившему
        # прогону обязано совпасть с тем, что написал сам писатель.
        if survivor_state is None or journal_state is None:
            control_no_pair += 1
            entry["reconstruction"] = "no_pair"
        elif survivor_state == journal_state:
            control_matched += 1
            entry["reconstruction"] = "matched"
        else:
            control_mismatched += 1
            entry["reconstruction"] = "mismatched"

        keys = [_key(s) for s in states]
        known = [k for k in keys if k is not None]
        entry["distinct_positions"] = len(set(known)) if known else None
        if known and keys[-1] is not None:
            survivor_key = keys[-1]
            agreeing = sum(1 for k in known if k == survivor_key)
            entry["runs_disagreeing_with_survivor"] = len(known) - agreeing
            entry["survivor_state_is_majority"] = agreeing * 2 > len(known)
        else:
            entry["runs_disagreeing_with_survivor"] = None
            entry["survivor_state_is_majority"] = None
        days.append(entry)

    exposure = _exposure(days, scored_days)
    reconstruction_control = {
        "days_checked": control_matched + control_mismatched,
        "matched": control_matched,
        "mismatched": control_mismatched,
        "days_without_pair": control_no_pair,
        # Контроль ПРОЙДЕН только при полном совпадении на сравнимых днях.
        # Ноль сравнимых дней — не «пройден», а «нечем мерить».
        "passed": (control_matched > 0 and control_mismatched == 0),
        "note": ("состояние, присвоенное выжившему прогону, сверено с "
                 "`current_positions` строки журнала — полем самого писателя"),
    }

    if not reconstruction_control["passed"]:
        reason = (
            "реконструкция книги не подтверждена тождеством значения: сравнимых "
            f"дней {reconstruction_control['days_checked']}, совпало "
            f"{control_matched}, разошлось {control_mismatched} — движение входа "
            "не измеряется, а не объявляется нулём")
        doc = refuse(reason)
        doc["exposure"] = exposure
        doc["days"] = days
        doc["reconstruction_control"] = reconstruction_control
        doc["subject_distinctness"] = _subject_distinctness(
            audit_rows, journal_by_day, runs_by_day)
        doc["findings"] = _findings(doc, exposure, None, days)
        return doc

    input_movement = _input_movement(days)
    subject = _subject_distinctness(audit_rows, journal_by_day, runs_by_day)

    doc = {
        "generated_at": generated_at,
        "version": "v1",
        "journal_rows": len(journal_rows),
        "journal_days": len(journal_by_day),
        "exposure": exposure,
        "input_movement": input_movement,
        "reconstruction_control": reconstruction_control,
        "subject_distinctness": subject,
        "days": days,
        "does_not_report": _DOES_NOT_REPORT,
        "advisory": _ADVISORY,
    }
    doc["third_outcomes"] = _third_outcomes(exposure, subject)
    doc["status"] = _status(exposure, input_movement)
    doc["findings"] = _findings(doc, exposure, input_movement, days)
    return doc


def _scored_days(data_dir: Path) -> Optional[set]:
    """Дни, входящие в знаменатель ``hit_rate`` — у КАНОНИЧЕСКОГО производителя.

    Список не выписывается сюда руками: знаменатель определяет
    ``shadow_trigger_eval``, и спрашивать надо его. Не ответил ⇒ ``None``, то
    есть «не измерено», а не пустое множество: пустое читалось бы как
    «знаменатель пуст».
    """
    try:
        from spa_core.paper_trading import shadow_trigger_eval as ste
        report = ste.evaluate_window(data_dir, write=False)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        log.warning("знаменатель hit_rate не измерен: %s", exc)
        return None
    rows = report.get("per_verdict")
    if not isinstance(rows, list):
        return None
    return {str(r.get("cycle_date")) for r in rows
            if not r.get("trivial") and r.get("outcome") in ("hit", "miss")}


def _exposure(days: List[dict], scored_days: Optional[set]) -> dict:
    """На скольких прогонах стои́т каждый день знаменателя ``hit_rate``."""
    if scored_days is None:
        return {
            "measured": False,
            "reason": ("знаменатель hit_rate не получен от "
                       "shadow_trigger_eval.evaluate_window"),
            "scored_days": None,
        }
    in_denom = [d for d in days if d["cycle_date"] in scored_days]
    counts = {POP_SINGLE: 0, POP_MULTI: 0, POP_UNMEASURED: 0}
    erased = 0
    for entry in in_denom:
        counts[entry["population_class"]] = counts.get(
            entry["population_class"], 0) + 1
        if entry.get("erased_runs"):
            erased += int(entry["erased_runs"])
    return {
        "measured": True,
        "scored_days": len(in_denom),
        "on_single_run_days": counts[POP_SINGLE],
        "on_multi_run_days": counts[POP_MULTI],
        "population_unmeasured_days": counts[POP_UNMEASURED],
        "erased_runs_under_denominator": erased,
        "days_multi_run": sorted(d["cycle_date"] for d in in_denom
                                 if d["population_class"] == POP_MULTI),
        "days_population_unmeasured": sorted(d["cycle_date"] for d in in_denom
                                             if d["population_class"] == POP_UNMEASURED),
    }


def _input_movement(days: List[dict]) -> dict:
    """Сколько РАЗНЫХ значений входа `current_positions` видели прогоны дня."""
    measured = [d for d in days if d.get("distinct_positions") is not None]
    moved = [d for d in measured if d["distinct_positions"] > 1]
    survivor_minority = [d for d in moved
                         if d.get("survivor_state_is_majority") is False]
    return {
        "days_measured": len(measured),
        "days_input_moved": len(moved),
        "days_survivor_state_not_majority": len(survivor_minority),
        "max_distinct_positions": (max(d["distinct_positions"] for d in measured)
                                   if measured else None),
        "runs_disagreeing_with_survivor": sum(
            int(d.get("runs_disagreeing_with_survivor") or 0) for d in measured),
        "days_moved": sorted(d["cycle_date"] for d in moved),
        "days_survivor_minority": sorted(d["cycle_date"] for d in survivor_minority),
    }


def _third_outcomes(exposure: dict, subject: dict) -> List[str]:
    """Отказы, названные поимённо. Первый — главный и безусловный."""
    out = [
        "вердикты стёртых прогонов НЕ ИЗМЕРЕНЫ и измерены быть не могут: "
        "единственным носителем вердикта прогона была строка журнала, которую "
        "замена уничтожила",
    ]
    if exposure.get("measured") and exposure.get("population_unmeasured_days"):
        out.append(
            f"население прогонов НЕ ИЗМЕРЕНО на "
            f"{exposure['population_unmeasured_days']} дн. знаменателя — этих "
            "дней нет в носителе прогонов, и молчание носителя не есть «прогон "
            "был один»")
    if not exposure.get("measured"):
        out.append("знаменатель hit_rate не измерен — экспозиция не считается")
    if not subject.get("substitution_admissible"):
        out.append(
            "подстановка записи живого пути вместо вердикта тени НЕДОПУСТИМА: "
            f"на {subject.get('different_subject_days')} дн. из "
            f"{subject.get('days_compared')} сравнимых `target_usd` и "
            "`target_positions` у ОДНОГО прогона расходятся — род величин разный")
    return out


def _status(exposure: dict, input_movement: Optional[dict]) -> str:
    if not exposure.get("measured"):
        return STATUS_UNMEASURED
    # CRITICAL — когда критерий взвода стои́т на днях, чей выживший прогон не
    # единственный ИЛИ чьё население не измерено вовсе. Это утверждение об
    # ЭВИДЕНСЕ критерия, а не о том, что HOLD был неправ.
    exposed = (exposure.get("on_multi_run_days", 0)
               + exposure.get("population_unmeasured_days", 0))
    if exposed and exposure.get("scored_days"):
        return STATUS_CRITICAL
    if input_movement and input_movement.get("days_input_moved"):
        return STATUS_WARNING
    return STATUS_OK


_DOES_NOT_REPORT = (
    "каким был вердикт стёртого прогона (носитель уничтожен заменой) · "
    "изменился бы ли hit_rate, если бы в журнал попала другая строка дня "
    "(это требует того же несуществующего вердикта) · подкласс движения входа "
    "(ставка, книга или анти-чёрн) — прибор меряет ОДИН вход `current_positions`, "
    "тот, что журнал несёт сам, и молчание об остальных не выдаёт за их покой"
)

_ADVISORY = (
    "писатель журнала и его правило замены строки дня, POLLED_ADAPTERS, пины, "
    "MIN_HIT_RATE, TriggerParams, пороги RiskPolicy v1.0, потолки концентрации, "
    "стоп-кран и живой трек НЕ трогаются — прибор только называет размер потери"
)


def _findings(doc: dict, exposure: dict, input_movement: Optional[dict],
              days: List[dict]) -> List[str]:
    out: List[str] = []
    if exposure.get("measured"):
        out.append(
            f"[ОТВЕТ] знаменатель hit_rate — {exposure['scored_days']} дн.; "
            f"на дне с ЕДИНСТВЕННЫМ прогоном стои́т "
            f"{exposure['on_single_run_days']}, на дне с несколькими — "
            f"{exposure['on_multi_run_days']}, население НЕ ИЗМЕРЕНО у "
            f"{exposure['population_unmeasured_days']}")
        if exposure.get("erased_runs_under_denominator"):
            out.append(
                f"[ОТВЕТ] под самим знаменателем стёрто "
                f"{exposure['erased_runs_under_denominator']} прогон(ов): дни "
                + ", ".join(exposure["days_multi_run"]))
    if input_movement:
        out.append(
            f"[ОТВЕТ] вход `current_positions` двигался внутри дня на "
            f"{input_movement['days_input_moved']} дн. из "
            f"{input_movement['days_measured']} измеренных (максимум "
            f"{input_movement['max_distinct_positions']} разных значений за день); "
            f"состояние выжившего прогона НЕ было большинством своего дня на "
            f"{input_movement['days_survivor_state_not_majority']} дн.")
        for entry in days:
            if (entry.get("distinct_positions") or 0) > 1 and entry.get(
                    "in_hit_rate_denominator"):
                out.append(
                    f"[ПО ДНЯМ] {entry['cycle_date']}: прогонов {entry['runs']}, "
                    f"разных значений входа {entry['distinct_positions']}, "
                    f"с выжившим расходится {entry['runs_disagreeing_with_survivor']} "
                    f"— день ВХОДИТ в знаменатель hit_rate")
    for reason in doc.get("third_outcomes") or []:
        out.append(f"[НЕ ИЗМЕРЕНО] {reason}")
    if doc.get("status") == STATUS_CRITICAL:
        out.append(
            f"[CRITICAL] критерий взвода hit_rate предъявлен на знаменателе, где "
            f"{exposure['on_multi_run_days'] + exposure['population_unmeasured_days']} "
            f"дн. из {exposure['scored_days']} не стои́т на измеренном единственном "
            "решении дня: правило «побеждает последний прогон дня» оставило от дня "
            "одну строку, а вердикты остальных не существуют ни в одном носителе. "
            "Это утверждение об ЭВИДЕНСЕ критерия, а НЕ о том, что HOLD был неправ")
    return out


# ────────────────────────────── проводка ──────────────────────────────────


def format_report(doc: dict) -> List[str]:
    """Порядок строк — порядок вопроса: экспозиция → движение входа → отказы.

    Экспозиция идёт ПЕРВОЙ намеренно: читатель, увидевший первой строкой
    «вход двигался на N днях», прочтёт это как замер всего журнала, — а носитель
    прогонов покрывает часть дней, и его молчание об остальных прибор называет
    третьим исходом, а не покоем.
    """
    out: List[str] = []
    exposure = observed(doc, "exposure", kind=dict) or {}
    movement = doc.get("input_movement") or {}
    out.append(
        f"   что теряет hit_rate от «одной строки в день» (заказ #552): "
        f"{doc.get('status')} · дней журнала {doc.get('journal_rows')} · "
        f"знаменатель {exposure.get('scored_days')} дн. · из них на дне с "
        f"единственным прогоном {exposure.get('on_single_run_days')}")
    if movement:
        out.append(
            f"   движение входа `current_positions` внутри дня: "
            f"{movement.get('days_input_moved')} дн. из "
            f"{movement.get('days_measured')} · выживший не большинство: "
            f"{movement.get('days_survivor_state_not_majority')} дн.")
    control = doc.get("reconstruction_control") or {}
    if control:
        out.append(
            f"   контроль реконструкции тождеством значения: совпало "
            f"{control.get('matched')} из {control.get('days_checked')} "
            f"({'ПРОЙДЕН' if control.get('passed') else 'НЕ ПРОЙДЕН'})")
    subject = doc.get("subject_distinctness") or {}
    if subject:
        out.append(
            f"   род величин (можно ли подставить запись живого пути): "
            f"расходятся на {subject.get('different_subject_days')} дн. из "
            f"{subject.get('days_compared')} — подстановка "
            f"{'ДОПУСТИМА' if subject.get('substitution_admissible') else 'ЗАПРЕЩЕНА'}")
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
        "warn": sum(1 for x in findings if x.startswith("[ПО ДНЯМ]")),
        "info": sum(1 for x in findings if x.startswith("[ОТВЕТ]")),
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
        description="что теряет hit_rate от правила «одна строка в день» "
                    "(заказ #552)")
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
