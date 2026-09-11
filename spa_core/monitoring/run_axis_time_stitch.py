"""Сшиваются ли оси прогонов двух носителей ПО ВРЕМЕНИ (заказ #556).

Заказ цикла #556 (ADR-319) поставлен дословно так:

> **Сшиваются ли оси прогонов двух носителей ПО ВРЕМЕНИ — и какова цена ошибки
> такого правила?** Замер выше закрыл сшивку по тождеству (общих
> идентификаторов 0). Но носители пишутся одним и тем же дневным заходом, и
> отметки стены у них соседние: 10.09 носитель ставок пишет
> ``07:59:45.131172``, а ``cycle_start`` трейла — ``07:59:42.865818``, то есть
> 2.3 с. Если правило близости состоятельно, ось прогонов трейла можно одолжить
> носителю ставок, и тогда вопрос о втором входе возвращается к ПОКРЫТИЮ —
> величине восполнимой, а не к цензуре.

И назвал ловушку заранее:

> Одна убедительная пара не есть правило: у подтверждающего инструмента обязана
> быть СВОЯ цена ошибки. Первым результатом обязано быть **население**, на
> котором правило проверяемо, и **доля неоднозначных сопоставлений**. Ноль
> однозначных пар ⇒ третий исход. И отдельно: сшивка, даже состоявшись, не
> снимает ни цензуры, ни разрешения — она снимает только вопрос об оси, и
> сказать это надо прежде, чем называть долю.

Пять слоёв отвечают на пять РАЗНЫХ вопросов. Смешать их значило бы убедительно
ответить не на тот — ровно то, на чём споткнулся сам заказ (слой 1).

## Слой 1 — КАКОЕ ПОЛЕ ЕСТЬ ОСЬ. Первый результат, потому что на нём стои́т всё

Заказ назвал ось ЧИСЛОМ (``07:59:45.131172``), а не именем поля, — и число
принадлежит НЕ тому полю, которое описывают слова «носитель ставок пишет».
Запись носителя ставок несёт ДВЕ отметки времени:

* ``observed_at`` — когда запись ЗАПИСАНА (это и есть «носитель пишет»);
* ``snapshot``    — отметка снимка, на котором значение НАБЛЮДЕНО.

На живом носителе они разъехались на 0.9–5.9 часа, и процитированные заказом
2.3 с принадлежат ``snapshot``. Разница не косметическая: правило близости
состоятельно на одной оси и не даёт НИ ОДНОЙ пары на другой. Поэтому слой
меряет ОБА кандидата и печатается первым.

**Урок класса:** ось, названная числом, не названа вовсе. Проверяемо имя поля,
а совпадение отметок — его следствие.

## Слой 2 — ЧЕГО СШИВКА НЕ СНИМАЕТ. Печатается ДО доли, как требует заказ

Сшивка отвечает на вопрос об ОСИ и ни на один другой. Она не снимает цензуры
(ADR-319: ставка трейла рождается только на ветке отказа гейта), не снимает
разрешения (сетка печати 0.1 пп против решающей маржи 0.0001 пп) и — добавлено
этим замером — **не снимает нехватки НАБЛЮДЕНИЙ**: одолженная ось делает прогон
опознаваемым, но не создаёт второго наблюдения там, где носитель сделал одно.

Порядок печати — часть утверждения, а не оформление: доля, названная прежде
оговорки, читается как ответ на вопрос о втором входе, которым она не является.

## Слой 3 — НАСЕЛЕНИЕ и ДОЛЯ НЕОДНОЗНАЧНЫХ. То, что заказ потребовал первым

Сопоставление считается:

* ``unmatched``   — в окне нет ни одного чужого прогона (правило ОТКАЗЫВАЕТ);
* ``unambiguous`` — ровно один;
* ``ambiguous``   — ДВА и более, то есть правило не знает, который из них.

Меряется в ОБЕ стороны, потому что носители разного размера и односторонний
замер ответил бы на половину вопроса. Обратная сторона по построению даёт массу
``unmatched`` — это ПОКРЫТИЕ, а не ошибка правила, и так и сказано.

Ноль однозначных пар ⇒ третий исход, а не «правило не сработало».

## Слой 4 — СВОЯ ЦЕНА ОШИБКИ. Полоса окна и её запас

У правила близости один параметр — окно. Цена ошибки считается не на глаз, а
двумя числами, снятыми с населения:

* ``widest_true_gap``     — самое далёкое ВЕРНОЕ расстояние; окно уже него теряет прогоны;
* ``narrowest_wrong_gap`` — самое близкое расстояние до ВТОРОГО прогона; окно шире него плодит неоднозначность.

Полоса ``[widest_true, narrowest_wrong)`` и её отношение — и есть запас правила.

**И отдельно — главное ограничение, которое нельзя умолчать:** полоса выведена
ИЗ ТЕХ ЖЕ наблюдений, которые правило потом судит. Вне выборки правило не
проверялось ни разу, поэтому запас есть свойство снимка, а не гарантия. Прибор
говорит это числом (``out_of_sample_runs``), а не словами.

## Слой 5 — ЧТО СШИВКА ПЕРЕНОСИТ НА ЗНАМЕНАТЕЛЬ

Вопрос заказа был не «сшиваются ли оси» сам по себе, а «вернётся ли вопрос о
втором входе к покрытию». Слой меряет это у КАНОНИЧЕСКОГО производителя
знаменателя (``shadow_trigger_eval``), а не по списку дней, выписанному здесь
руками. Производитель не ответил ⇒ ``None``, то есть «не измерено»: пустое
множество читалось бы как «знаменатель пуст», и прибор объявил бы полное
покрытие нуля.

## ADVISORY

Прибор ничего не чинит и не предлагает чинить молча. Писатель трейла, писатель
носителя ставок, писатель журнала решений и его правило замены строки дня,
``POLLED_ADAPTERS``, пины, частота опроса, ``MIN_HIT_RATE``, ``TriggerParams``,
пороги RiskPolicy v1.0, потолки концентрации, стоп-кран и живой трек не
трогаются; капитал не двигается.

## Почему прибор НЕ внесён в перепись потребителей журнала решений

``decision_journal_coverage.READERS`` — население потребителей КЛЮЧА ставки в
журнале решений. Этот прибор ключа не касается: из журнала он не читает вовсе,
знаменатель берёт у канонического производителя. Внеси его в ``READERS`` — и
``probe_readers`` выдал бы ``insensitive``, ИСТИННЫЙ ПО ПОСТРОЕНИЮ (класс
ADR-317). Решение закреплено тестом в обе стороны.
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

VERSION = "run_axis_time_stitch/v1"

OUTPUT_FILENAME = "run_axis_time_stitch.json"
RATE_CARRIER_FILENAME = "apy_composition_log.jsonl"
TRAIL_FILENAME = "audit_trail.jsonl"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Событие трейла, несущее ось прогонов. ADR-319 измерил: 443 таких записи на
#: 28 днях, до 28 прогонов на день — ось в ветке лучшая.
TRAIL_RUN_EVENT = "cycle_start"

#: ДВА кандидата в ось на стороне носителя ставок, ОБЪЯВЛЕННЫЕ по именам полей.
#: Заказ назвал ось числом и промахнулся мимо поля (слой 1), поэтому здесь имена
#: перечислены явно и оба меряются — выбор делает замер, а не эта строка.
AXIS_WRITE_TIME = "observed_at"
AXIS_SNAPSHOT = "snapshot"
AXIS_CANDIDATES = (AXIS_SNAPSHOT, AXIS_WRITE_TIME)

#: Развёртка окон для слоя 3. Крайние значения намеренно абсурдны с обеих
#: сторон: доля неоднозначных обязана быть видна КАК ФУНКЦИЯ окна, иначе
#: единственное удобное окно выдаётся за свойство носителей.
WINDOW_SWEEP_S = (1, 2, 5, 10, 15, 20, 30, 60, 300, 3600, 21600)

MATCH_UNMATCHED = "unmatched"
MATCH_UNAMBIGUOUS = "unambiguous"
MATCH_AMBIGUOUS = "ambiguous"


# ─────────────────────────── чтение носителей ───────────────────────────
def _parse_ts(value: object) -> Optional[datetime]:
    """Отметка времени ⇒ aware ``datetime``. Любой отказ ⇒ ``None``."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except Exception:  # noqa: BLE001
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def read_rate_carrier_runs(data_dir: Path) -> Tuple[List[dict], str]:
    """Прогоны носителя ставок — по ОБОИМ кандидатам в ось сразу.

    Прогон опознаётся парой отметок, а не одной: слой 1 обязан сравнить оси
    между собой, а для этого обе нужны у одной и той же записи.
    """
    seen: Dict[Tuple[str, str], int] = {}
    broken = 0
    path = Path(data_dir) / RATE_CARRIER_FILENAME
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:  # noqa: BLE001
                    broken += 1
                    continue
                if not isinstance(row, dict):
                    broken += 1
                    continue
                key = (str(row.get(AXIS_WRITE_TIME) or ""),
                       str(row.get(AXIS_SNAPSHOT) or ""))
                if not key[0] and not key[1]:
                    broken += 1
                    continue
                seen[key] = seen.get(key, 0) + 1
    except Exception as exc:  # noqa: BLE001 — причина уезжает в отчёт словами
        return [], f"{type(exc).__name__}: {exc}"
    if broken and not seen:
        return [], f"строк носителя ставок не разобрано: {broken}"
    runs = [{AXIS_WRITE_TIME: w, AXIS_SNAPSHOT: s, "records": n}
            for (w, s), n in sorted(seen.items())]
    return runs, ""


def read_trail_runs(data_dir: Path) -> Tuple[List[datetime], str]:
    """Ось прогонов трейла — отметки событий ``cycle_start``."""
    out: List[datetime] = []
    broken = 0
    path = Path(data_dir) / TRAIL_FILENAME
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:  # noqa: BLE001
                    broken += 1
                    continue
                if not isinstance(row, dict):
                    broken += 1
                    continue
                if row.get("event_type") != TRAIL_RUN_EVENT:
                    continue
                ts = _parse_ts(row.get("timestamp"))
                if ts is None:
                    broken += 1
                    continue
                out.append(ts)
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"
    if broken and not out:
        return [], f"строк трейла не разобрано: {broken}"
    return sorted(out), ""


def scored_days(data_dir: Path) -> Optional[set]:
    """Дни знаменателя ``hit_rate`` — у КАНОНИЧЕСКОГО производителя.

    Список не выписывается сюда руками: знаменатель определяет
    ``shadow_trigger_eval``. Не ответил ⇒ ``None``, то есть «не измерено», а не
    пустое множество: пустое читалось бы как «знаменатель пуст», и прибор
    объявил бы полное покрытие нуля.
    """
    try:
        from spa_core.paper_trading import shadow_trigger_eval as ste
        report = ste.evaluate_window(Path(data_dir), write=False)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        log.warning("знаменатель hit_rate не измерен: %s", exc)
        return None
    rows = report.get("per_verdict")
    if not isinstance(rows, list):
        return None
    return {str(r.get("cycle_date")) for r in rows
            if not r.get("trivial") and r.get("outcome") in ("hit", "miss")}


# ───────────────── слой 1: какое поле есть ось ─────────────────
def _axis_separation(runs: List[dict], trail: List[datetime]) -> dict:
    """Оба кандидата в ось, сравнённые ОДНОЙ мерой — расстоянием до трейла.

    Мера одна намеренно: два кандидата, сравнённые разными мерами, неразличимы
    по существу. Здесь у каждого считается одно и то же — медиана и максимум
    расстояния до ближайшего прогона трейла.
    """
    out: Dict[str, dict] = {}
    for axis in AXIS_CANDIDATES:
        gaps: List[float] = []
        unparsed = 0
        for run in runs:
            ts = _parse_ts(run.get(axis))
            if ts is None:
                unparsed += 1
                continue
            if not trail:
                continue
            gaps.append(min(abs((c - ts).total_seconds()) for c in trail))
        gaps.sort()
        out[axis] = {
            "runs_with_field": len(runs) - unparsed,
            "unparsed": unparsed,
            "nearest_gap_s_min": round(gaps[0], 3) if gaps else None,
            "nearest_gap_s_median": (round(gaps[len(gaps) // 2], 3)
                                     if gaps else None),
            "nearest_gap_s_max": round(gaps[-1], 3) if gaps else None,
        }
    # Расхождение САМИХ осей внутри одной записи: именно оно делает выбор поля
    # решающим, и именно его заказ не увидел.
    spreads = []
    for run in runs:
        a = _parse_ts(run.get(AXIS_SNAPSHOT))
        b = _parse_ts(run.get(AXIS_WRITE_TIME))
        if a is not None and b is not None:
            spreads.append(abs((b - a).total_seconds()))
    spreads.sort()
    out["axes_disagree_within_one_record_s"] = {
        "min": round(spreads[0], 3) if spreads else None,
        "max": round(spreads[-1], 3) if spreads else None,
        "runs": len(spreads),
    }
    # Какая ось ближе к трейлу — выбирается ЗАМЕРОМ (меньший максимум), а не
    # порядком объявления.
    ranked = [(out[a]["nearest_gap_s_max"], a) for a in AXIS_CANDIDATES
              if out[a]["nearest_gap_s_max"] is not None]
    out["axis_chosen_by_measurement"] = min(ranked)[1] if ranked else None
    out["measured"] = bool(ranked)
    return out


# ───────────────── слой 3: население и неоднозначность ─────────────────
def _classify(anchor: datetime, others: List[datetime], window_s: float) -> str:
    near = [c for c in others
            if abs((c - anchor).total_seconds()) <= window_s]
    if not near:
        return MATCH_UNMATCHED
    return MATCH_UNAMBIGUOUS if len(near) == 1 else MATCH_AMBIGUOUS


def _tally(anchors: List[datetime], others: List[datetime],
           window_s: float) -> dict:
    counts = {MATCH_UNMATCHED: 0, MATCH_UNAMBIGUOUS: 0, MATCH_AMBIGUOUS: 0}
    for a in anchors:
        counts[_classify(a, others, window_s)] += 1
    paired = counts[MATCH_UNAMBIGUOUS] + counts[MATCH_AMBIGUOUS]
    return {
        "window_s": window_s,
        **counts,
        "paired": paired,
        # Доля НЕ считается от нуля: знаменателя нет ⇒ None, а не 0.0. Ноль
        # читался бы как «неоднозначных нет», то есть как успех правила.
        "ambiguous_share": (round(counts[MATCH_AMBIGUOUS] / paired, 4)
                            if paired else None),
    }


# ───────────────── слой 4: своя цена ошибки ─────────────────
def _error_rate(anchors: List[datetime], others: List[datetime]) -> dict:
    """Полоса окна: где правило ещё не теряет и уже не путает."""
    widest_true: Optional[float] = None
    narrowest_wrong: Optional[float] = None
    signed: List[float] = []
    for a in anchors:
        gaps = sorted(abs((c - a).total_seconds()) for c in others)
        if not gaps:
            continue
        widest_true = gaps[0] if widest_true is None else max(widest_true,
                                                             gaps[0])
        if len(gaps) > 1:
            narrowest_wrong = (gaps[1] if narrowest_wrong is None
                               else min(narrowest_wrong, gaps[1]))
        near = min(others, key=lambda c: abs((c - a).total_seconds()))
        signed.append((a - near).total_seconds())
    band_open = widest_true is not None
    margin = (round(narrowest_wrong / widest_true, 3)
              if band_open and narrowest_wrong and widest_true else None)
    return {
        "measured": band_open,
        "widest_true_gap_s": round(widest_true, 3) if band_open else None,
        # Окно берётся ОТСЮДА, а не из округлённого поля выше: округление вниз
        # сделало бы окно уже самого далёкого верного расстояния, и правило
        # потеряло бы тот самый прогон, из которого окно выведено. Это не
        # косметика — первый прогон прибора так и дал 10 однозначных из 11.
        "_widest_true_gap_s_exact": widest_true if band_open else None,
        "narrowest_wrong_gap_s": (round(narrowest_wrong, 3)
                                  if narrowest_wrong is not None else None),
        "margin_ratio": margin,
        # Знак расстояния: снимок ПОСЛЕ старта прогона — следствие причинности,
        # и односторонним окном её можно было бы использовать. Меряется, а не
        # предполагается.
        "all_after_run_start": bool(signed) and all(d > 0 for d in signed),
        "signed_gap_s_min": round(min(signed), 3) if signed else None,
        "signed_gap_s_max": round(max(signed), 3) if signed else None,
        # ГЛАВНОЕ ограничение: полоса выведена из тех же наблюдений, которые
        # правило судит. Вне выборки правило не проверялось ни разу.
        "out_of_sample_runs": 0,
        "in_sample_runs": len(anchors),
    }


# ───────────────── слой 5: что переносится на знаменатель ─────────────────
def _transfer(runs: List[dict], denominator: Optional[set]) -> dict:
    per_day: Dict[str, int] = {}
    for run in runs:
        ts = _parse_ts(run.get(AXIS_SNAPSHOT))
        if ts is None:
            continue
        per_day[ts.date().isoformat()] = per_day.get(
            ts.date().isoformat(), 0) + 1
    multi = {d for d, n in per_day.items() if n >= 2}
    if denominator is None:
        return {
            "measured": False,
            "reason": ("знаменатель hit_rate не получен у канонического "
                       "производителя shadow_trigger_eval; ноль здесь читался "
                       "бы как «знаменатель пуст»"),
            "carrier_days": len(per_day),
            "carrier_days_with_two_or_more_runs": len(multi),
        }
    touched = set(per_day) & denominator
    adjudicable = multi & denominator
    return {
        "measured": True,
        "denominator_days": len(denominator),
        "carrier_days": len(per_day),
        "carrier_days_with_two_or_more_runs": sorted(multi),
        "denominator_days_touched": sorted(touched),
        # Ровно то, что сшивка покупает знаменателю: дни, где носитель И в
        # знаменателе, И имеет два наблюдения. Одно наблюдение не сравнимо ни с
        # чем, как бы хорошо ни была подписана его ось.
        "denominator_days_adjudicable_after_stitch": sorted(adjudicable),
        "denominator_days_still_unadjudicable": len(denominator) - len(
            adjudicable),
    }


# ───────────────────────────── замер ─────────────────────────────
def measure(data_dir: Path, *, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    data_dir = Path(data_dir)
    doc: dict = {
        "version": VERSION,
        "generated_at": now.isoformat(),
        "question": ("сшиваются ли оси прогонов носителя ставок и трейла ПО "
                     "ВРЕМЕНИ, и какова своя цена ошибки такого правила "
                     "(заказ #556)"),
        "findings": [],
        "advisory": ("ADVISORY: прибор ничего не чинит; писатели носителей, "
                     "частота опроса, POLLED_ADAPTERS, MIN_HIT_RATE, "
                     "TriggerParams, пороги RiskPolicy v1.0, стоп-кран и "
                     "живой трек не трогаются"),
    }

    runs, err_runs = read_rate_carrier_runs(data_dir)
    trail, err_trail = read_trail_runs(data_dir)
    if err_runs or err_trail or not runs or not trail:
        doc["status"] = STATUS_UNMEASURED
        doc["reason"] = (err_runs or err_trail
                         or ("носитель ставок пуст" if not runs
                             else "ось прогонов трейла пуста"))
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] сшивка осей не считается: {doc['reason']}")
        doc["rate_carrier_runs"] = len(runs)
        doc["trail_runs"] = len(trail)
        return doc

    doc["rate_carrier_runs"] = len(runs)
    doc["trail_runs"] = len(trail)

    # ── слой 1 ──
    axes = _axis_separation(runs, trail)
    doc["axis_candidates"] = axes
    chosen = axes.get("axis_chosen_by_measurement")
    if chosen is None:
        doc["status"] = STATUS_UNMEASURED
        doc["reason"] = "ни одно из объявленных полей-осей не разобрано"
        doc["findings"].append(f"[НЕ ИЗМЕРЕНО] {doc['reason']}")
        return doc
    other = next(a for a in AXIS_CANDIDATES if a != chosen)
    doc["findings"].append(
        f"[ОСЬ] осью выбрано поле `{chosen}` ЗАМЕРОМ: максимум расстояния до "
        f"прогона трейла {axes[chosen]['nearest_gap_s_max']} с против "
        f"{axes[other]['nearest_gap_s_max']} с у `{other}`; внутри ОДНОЙ "
        f"записи оси расходятся на "
        f"{axes['axes_disagree_within_one_record_s']['min']}–"
        f"{axes['axes_disagree_within_one_record_s']['max']} с — поэтому ось, "
        f"названная числом, не названа вовсе")

    # ── слой 2: печатается ДО доли, как требует заказ ──
    doc["what_the_stitch_cannot_remove"] = [
        "цензуру: ставка трейла рождается только на ветке отказа гейта "
        "(ADR-319), и частотой это не чинится",
        "разрешение: сетка печати грубее решающей маржи (ADR-319)",
        "нехватку НАБЛЮДЕНИЙ: одолженная ось делает прогон опознаваемым, но "
        "не создаёт второго наблюдения там, где носитель сделал одно",
    ]
    doc["findings"].append(
        "[ОГОВОРКА ДО ДОЛИ] сшивка отвечает на вопрос об ОСИ и ни на один "
        "другой: она не снимает ни цензуры, ни разрешения, ни нехватки "
        "наблюдений")

    anchors = [ts for ts in (_parse_ts(r.get(chosen)) for r in runs)
               if ts is not None]

    # ── слой 4 считается до слоя 3, потому что окно слоя 3 берётся из полосы ──
    err = _error_rate(anchors, trail)
    doc["error_rate"] = err

    # ── слой 3 ──
    sweep = [_tally(anchors, trail, w) for w in WINDOW_SWEEP_S]
    doc["window_sweep"] = sweep
    doc["reverse_direction"] = None
    derived = err.get("_widest_true_gap_s_exact")
    if derived is not None:
        # Окно — НЕ константа из этого файла: оно выведено из населения
        # (самое далёкое верное расстояние), и провенанс назван рядом.
        doc["derived_window_s"] = round(derived, 3)
        doc["derived_window_provenance"] = (
            "widest_true_gap_s — самое далёкое ВЕРНОЕ расстояние на населении; "
            "окно уже него теряет прогоны")
        fwd = _tally(anchors, trail, derived)
        doc["forward_direction"] = fwd
        doc["reverse_direction"] = _tally(trail, anchors, derived)

        if fwd[MATCH_UNAMBIGUOUS] == 0:
            doc["status"] = STATUS_UNMEASURED
            doc["findings"].append(
                "[НЕ ИЗМЕРЕНО] однозначных пар НОЛЬ на выведенном окне — "
                "правило близости не проверяемо на этом населении, и это "
                "третий исход, а не «сшивка невозможна»")
            return doc

        doc["findings"].append(
            f"[НАСЕЛЕНИЕ] прямая сторона на окне {round(derived, 3)} с: "
            f"{fwd[MATCH_UNAMBIGUOUS]} однозначных из {len(anchors)} прогонов "
            f"носителя, неоднозначных {fwd[MATCH_AMBIGUOUS]}, доля "
            f"{fwd['ambiguous_share']}")
        rev = doc["reverse_direction"]
        doc["findings"].append(
            f"[ОБРАТНАЯ СТОРОНА] из {len(trail)} прогонов трейла пару имеют "
            f"{rev[MATCH_UNAMBIGUOUS]} — это ПОКРЫТИЕ носителя ставок, а не "
            f"ошибка правила: {rev[MATCH_UNMATCHED]} прогонов трейла не имеют "
            f"рядом ни одной записи ставок")
        doc["findings"].append(
            f"[ЦЕНА ОШИБКИ] полоса окна "
            f"[{err['widest_true_gap_s']}, {err['narrowest_wrong_gap_s']}) с, "
            f"запас {err['margin_ratio']}x; вне выборки правило проверялось "
            f"{err['out_of_sample_runs']} раз при "
            f"{err['in_sample_runs']} в выборке — запас есть свойство снимка, "
            f"а не гарантия")

    # ── слой 5 ──
    transfer = _transfer(runs, scored_days(data_dir))
    doc["transfer_to_denominator"] = transfer
    if not transfer.get("measured"):
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] перенос на знаменатель: {transfer['reason']}")
        doc["status"] = STATUS_UNMEASURED
        return doc

    gained = transfer["denominator_days_adjudicable_after_stitch"]
    if gained:
        doc["findings"].append(
            f"[ОТВЕТ] сшивка переносит на знаменатель {len(gained)} дней: "
            f"{gained}")
        doc["status"] = STATUS_WARNING
    else:
        doc["findings"].append(
            f"[ОТВЕТ] сшивка состоялась и переносит на знаменатель НОЛЬ дней: "
            f"носитель касается {len(transfer['denominator_days_touched'])} "
            f"дней знаменателя из {transfer['denominator_days']} и на каждом "
            f"держит ОДНО наблюдение, а дни с двумя и более наблюдениями "
            f"({len(transfer['carrier_days_with_two_or_more_runs'])}) в "
            f"знаменатель не входят ни одним. Ось одолжена, сравнивать "
            f"по-прежнему нечего")
        doc["status"] = STATUS_WARNING

    doc["does_not_report"] = (
        "прибор НЕ утверждает, что правило близости верно вне этого снимка: "
        "полоса окна выведена из тех же 11 наблюдений, которые она судит")
    return doc


# ─────────────────────────── отчёт ───────────────────────────
def format_report(doc: dict) -> List[str]:
    out = [f"СШИВКА ОСЕЙ ПО ВРЕМЕНИ (заказ #556): {doc.get('status')}"]
    if doc.get("reason"):
        out.append(f"   причина: {doc['reason']}")
    axes = doc.get("axis_candidates") or {}
    if axes.get("measured"):
        out.append(f"   ось выбрана замером: `{axes['axis_chosen_by_measurement']}`")
    # Оговорка печатается ДО доли — порядок строк есть часть утверждения.
    for line in doc.get("what_the_stitch_cannot_remove") or []:
        out.append(f"   НЕ СНИМАЕТ: {line}")
    fwd = doc.get("forward_direction") or {}
    if fwd:
        out.append(
            f"   прямая сторона (окно {round(fwd['window_s'], 3)} с): однозначных "
            f"{fwd['unambiguous']}, неоднозначных {fwd['ambiguous']}, доля "
            f"{fwd['ambiguous_share']}")
    err = observed(doc, "error_rate", kind=dict) or {}
    if err.get("measured"):
        out.append(
            f"   цена ошибки: полоса [{err['widest_true_gap_s']}, "
            f"{err['narrowest_wrong_gap_s']}) с, запас {err['margin_ratio']}x, "
            f"вне выборки {err['out_of_sample_runs']} прогонов")
    tr = doc.get("transfer_to_denominator") or {}
    if tr.get("measured"):
        out.append(
            f"   перенос на знаменатель: "
            f"{len(tr['denominator_days_adjudicable_after_stitch'])} дней из "
            f"{tr['denominator_days']}")
    for line in doc.get("findings") or []:
        out.append(f"   {line}")
    if doc.get("does_not_report"):
        out.append(f"   НЕ ДОКЛАДЫВАЕТ: {doc['does_not_report']}")
    if doc.get("advisory"):
        out.append(f"   {doc['advisory']}")
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
        "warn": sum(1 for x in findings
                    if x.startswith("[ОСЬ]")
                    or x.startswith("[ОГОВОРКА ДО ДОЛИ]")
                    or x.startswith("[ЦЕНА ОШИБКИ]")
                    or x.startswith("[ОБРАТНАЯ СТОРОНА]")
                    or x.startswith("[НАСЕЛЕНИЕ]")),
        "info": sum(1 for x in findings if x.startswith("[ОТВЕТ]")),
        # «не измерено» считается ОТДЕЛЬНО от нулей: растворив его, мы сделали
        # бы молчание прибора неотличимым от чистого прогона.
        "unchecked": (1 if doc["status"] == STATUS_UNMEASURED else 0)
                     + sum(1 for x in findings
                           if x.startswith("[НЕ ИЗМЕРЕНО]")),
    }
    if write:
        atomic_save(doc, str(data_dir / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="сшиваются ли оси прогонов двух носителей по времени "
                    "(заказ #556)")
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
