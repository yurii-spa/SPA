"""Двигался ли ВТОРОЙ вход тени — ставки — внутри дня (заказ #554, ADR-316).

Заказ цикла #554 поставлен дословно так:

> **Второй вход тени — ставки — двигался ли внутри дня так же, и на скольких днях
> знаменателя?** Этот цикл измерил ОДИН вход (``current_positions``), потому что
> его несёт сам журнал. Ставки журнал тоже несёт (``apy_evidenced_pct``), но по
> одной строке на день — то есть ровно та же слепота, и носителя ставок ПО
> ПРОГОНАМ у журнала нет.

И назвал ловушку заранее: ``data/apy_series_daily.json`` — ряд ПО ДНЯМ, а не по
прогонам; подставить его точку как «ставку прогона» значило бы повторить ту самую
подмену, которую ADR-316 запретил. Кандидат в носители назван один —
``apy_composition_log.jsonl``: он пишет строку с полем ``snapshot``, то есть
двусторонен по прогонам. Отсюда порядок исполнения, заданный самим заказом:

> **Первым результатом обязано быть то, что этот носитель РЕАЛЬНО покрывает:
> сколько пар «день знаменателя × нога» он способен рассудить, а не доля от того,
> что хотелось бы. Не поддаётся ⇒ третий исход.**

Прибор устроен ровно по этому порядку. Его четыре слоя отвечают на четыре РАЗНЫХ
вопроса, и смешать их — значит верно ответить не на тот вопрос.

## Слой 1 — ПОКРЫТИЕ. Первый результат, и он про носитель, а не про ставки

Вопрос слоя: **на скольких парах «день знаменателя × нога» носитель вообще
способен вынести суждение о движении внутри дня.** Рассудить пару носитель может
тогда и только тогда, когда у дня в нём ДВА и более различных ``snapshot`` И нога
получила значение не менее чем в двух из них: одно наблюдение не сравнивается ни
с чем, а «значение одно» и «значений два и они равны» — разные ответы.

Нога дня — протокол из ``current_positions ∪ target_positions`` строки журнала:
это ровно то население, для которого писатель кладёт ставку (правило ADR-290).
Знаменатель — ``scored``-дни у КАНОНИЧЕСКОГО производителя
(``shadow_trigger_eval``), а не выписанный сюда список.

Нерассуженная пара получает НАЗВАННУЮ причину, и причин четыре, потому что они
означают разное: дня нет в носителе вовсе · у дня единственный снимок · нога в
носителе не встречается · нога встречается ровно в одном снимке дня. Свалить их
в «не покрыто» значило бы потерять единственное, что здесь можно чинить.

## Слой 2 — ДВИЖЕНИЕ. Измеримо, но на НЕСВЯЗАННОМ населении, и это сказано вслух

Дни, у которых носитель ИМЕЕТ два и более снимка, могут в знаменатель не входить.
Тогда движение ставок внутри дня измеряется — но **о знаменателе не говорит
ничего**, и прибор не переносит долю с одного населения на другое. Слой печатается
ПОСЛЕ слоя 1 намеренно: читатель, увидевший первой строкой «ставки двигались на N
днях», прочтёт это как замер знаменателя.

## Слой 3 — РОД ВЕЛИЧИН. Контроль, пересчитываемый КАЖДЫЙ прогон

Даже полное покрытие не дало бы права подставлять значение носителя в рассуждение
о входе тени, пока не показано, что это ОДНА И ТА ЖЕ величина. Контроль:
у последнего снимка дня сверяется значение носителя со ставкой того же протокола
в ``apy_evidenced_pct`` строки журнала того же дня. Совпало ⇒ род один. Разошлось
⇒ второй, независимый от покрытия, запрет на подстановку.

Контроль пересчитывается каждый прогон, а не цитируется из ADR: сойдись предметы
однажды — прибор обязан это увидеть; разойдись — тоже.

**Ноль сравнимых пар НЕ есть «контроль пройден».** Это третий исход.

## Слой 4 — ЛОВУШКА ЗАКАЗА, доказанная ЗАМЕРОМ, а не памятью

``apy_series_daily.json`` прибор не подставляет и доказывает замером, что
подставлять нельзя: считается МАКСИМАЛЬНОЕ число точек на пару (адаптер, день).
Единица означает, что разрешения по прогонам у ряда нет ПО ПОСТРОЕНИЮ — одна
точка не может свидетельствовать о двух прогонах. Число берётся с диска каждый
прогон: изменись ряд, прибор скажет новое, а не старое.

## ADVISORY

Прибор ничего не чинит и не предлагает чинить молча. Ни писатель журнала решений
и его правило замены строки дня, ни писатель носителя
(``apy_composition.append_history``), ни ``POLLED_ADAPTERS``, ни пины, ни
``MIN_HIT_RATE``, ни ``TriggerParams``, ни пороги RiskPolicy v1.0, ни потолки
концентрации, ни стоп-кран, ни живой трек не трогаются; капитал не двигается.
Живое ``data/`` открывается на запись ровно один раз — для собственного артефакта.
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

VERSION = "intraday_rate_input_movement/v1"

OUTPUT_FILENAME = "intraday_rate_input_movement.json"
HISTORY_FILENAME = "allocation_rationale_history.jsonl"
CARRIER_FILENAME = "apy_composition_log.jsonl"
SERIES_FILENAME = "apy_series_daily.json"

#: Ключ журнала, чью величину сверяет слой 3. Назван константой не для красоты:
#: храповик населения потребителей (`ReaderPopulationRatchet`) ищет ровно это
#: слово в тексте модуля, и прибор обязан числиться потребителем — он им и есть.
JOURNAL_RATE_KEY = "apy_evidenced_pct"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Разряд сравнения ставок. Носитель и журнал пишут проценты с четырьмя знаками;
#: сравнивать float'ы без сетки значило бы объявлять движением последний бит.
_PP = 4

#: Классы нерассуженной пары. Их четыре, и растворять их друг в друге нельзя:
#: чинится у них РАЗНОЕ (день не покрыт — писателем носителя; нога не покрыта —
#: составом опрашиваемых; единственный снимок — частотой опроса).
WHY_DAY_ABSENT = "day_absent_from_carrier"
WHY_ONE_SNAPSHOT = "single_snapshot_on_day"
WHY_LEG_ABSENT = "leg_absent_from_carrier"
WHY_LEG_ONCE = "leg_in_one_snapshot_only"

ADJUDICABLE = "adjudicable"


# ─────────────────────────── чтение носителей ───────────────────────────
def read_journal(data_dir: Path) -> Tuple[List[dict], str]:
    """Строки журнала решений. Битая строка не рушит замер — она называется."""
    rows: List[dict] = []
    broken = 0
    path = Path(data_dir) / HISTORY_FILENAME
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
                if isinstance(row, dict) and row.get("cycle_date"):
                    rows.append(row)
    except Exception as exc:  # noqa: BLE001 — причина уезжает в отчёт словами
        return [], f"{type(exc).__name__}: {exc}"
    if broken and not rows:
        return [], f"строк журнала не разобрано: {broken}"
    return rows, ""


def read_carrier(data_dir: Path) -> Tuple[Dict[str, Dict[str, Dict[str, float]]], str]:
    """Носитель ставок ПО ПРОГОНАМ → ``{день: {снимок: {адаптер: ставка}}}``.

    Берутся только строки ``kind == "hint_winner"`` со ставкой: строка
    ``unchecked`` говорит, что у ключа наблюдения НЕ БЫЛО, и считать её
    наблюдением значило бы изготовить покрытие из отказа.
    """
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    path = Path(data_dir) / CARRIER_FILENAME
    broken = 0
    seen_any = False
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
                seen_any = True
                snap = row.get("snapshot")
                adapter = row.get("adapter")
                if not isinstance(snap, str) or not isinstance(adapter, str):
                    continue
                if row.get("kind") != "hint_winner":
                    continue
                apy = row.get("apy")
                if not isinstance(apy, (int, float)):
                    continue
                out.setdefault(snap[:10], {}).setdefault(snap, {})[adapter] = \
                    round(float(apy), _PP)
    except Exception as exc:  # noqa: BLE001
        return {}, f"{type(exc).__name__}: {exc}"
    if broken and not seen_any:
        return {}, f"строк носителя не разобрано: {broken}"
    return out, ""


def scored_days(data_dir: Path) -> Optional[set]:
    """Дни знаменателя ``hit_rate`` — у КАНОНИЧЕСКОГО производителя.

    Список не выписывается сюда руками: знаменатель определяет
    ``shadow_trigger_eval``, и спрашивать надо его. Не ответил ⇒ ``None``, то
    есть «не измерено», а не пустое множество: пустое читалось бы как
    «знаменатель пуст», и прибор объявил бы полное покрытие нуля.
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


def legs_of_day(row: dict) -> List[str]:
    """Ноги дня — ``current_positions ∪ target_positions``.

    Ровно то население, для которого писатель журнала кладёт ставку (ADR-290).
    Брать вместо него список ``legs`` (только ходы) значило бы спрашивать о
    движении ставки лишь там, где ход и так предложен.
    """
    cur = row.get("current_positions")
    tgt = row.get("target_positions")
    names = set()
    for book in (cur, tgt):
        if isinstance(book, dict):
            names.update(str(k) for k in book)
    return sorted(names)


# ───────────────────────────── слой 1: покрытие ─────────────────────────────
def _classify_pair(day: str, leg: str,
                   carrier: Dict[str, Dict[str, Dict[str, float]]]) -> dict:
    """Способен ли носитель рассудить эту пару — и если нет, ПОЧЕМУ именно."""
    snaps = carrier.get(day)
    if not snaps:
        return {"cycle_date": day, "leg": leg, "verdict": WHY_DAY_ABSENT,
                "snapshots_on_day": 0, "observations": 0}
    if len(snaps) < 2:
        with_leg = sum(1 for v in snaps.values() if leg in v)
        return {"cycle_date": day, "leg": leg, "verdict": WHY_ONE_SNAPSHOT,
                "snapshots_on_day": len(snaps), "observations": with_leg}
    values = [v[leg] for _, v in sorted(snaps.items()) if leg in v]
    if not values:
        return {"cycle_date": day, "leg": leg, "verdict": WHY_LEG_ABSENT,
                "snapshots_on_day": len(snaps), "observations": 0}
    if len(values) < 2:
        return {"cycle_date": day, "leg": leg, "verdict": WHY_LEG_ONCE,
                "snapshots_on_day": len(snaps), "observations": 1}
    return {"cycle_date": day, "leg": leg, "verdict": ADJUDICABLE,
            "snapshots_on_day": len(snaps), "observations": len(values),
            "moved": max(values) != min(values),
            "spread_pp": round(max(values) - min(values), _PP)}


def _coverage(days_in_denominator: List[dict],
              carrier: Dict[str, Dict[str, Dict[str, float]]]) -> dict:
    """Слой 1 целиком: пары знаменателя, поимённо и по классам."""
    pairs: List[dict] = []
    for row in days_in_denominator:
        day = str(row["cycle_date"])
        for leg in legs_of_day(row):
            pairs.append(_classify_pair(day, leg, carrier))
    by_verdict: Dict[str, int] = {}
    for p in pairs:
        by_verdict[p["verdict"]] = by_verdict.get(p["verdict"], 0) + 1
    adjudicable = [p for p in pairs if p["verdict"] == ADJUDICABLE]
    return {
        "measured": True,
        "denominator_days": len(days_in_denominator),
        "pairs_total": len(pairs),
        "pairs_adjudicable": len(adjudicable),
        "pairs_moved": sum(1 for p in adjudicable if p["moved"]),
        "by_verdict": dict(sorted(by_verdict.items())),
        "days_touched_by_carrier": sorted(
            {str(r["cycle_date"]) for r in days_in_denominator
             if str(r["cycle_date"]) in carrier}),
    }


# ─────────────────── слой 2: движение вне знаменателя ───────────────────
def _movement_outside(carrier: Dict[str, Dict[str, Dict[str, float]]],
                      denominator: set) -> dict:
    """Движение ставок внутри дня там, где носитель ЕГО ВИДИТ.

    Население тут ДРУГОЕ — дни носителя, не дни знаменателя, — и прибор об этом
    говорит вслух в самом поле: перенос доли с одного населения на другое и есть
    та подстановка, против которой написан заказ.
    """
    days = []
    moved = unmoved = 0
    widest = 0.0
    widest_at = None
    for day in sorted(carrier):
        snaps = carrier[day]
        if len(snaps) < 2:
            continue
        per_adapter = {}
        for _, values in sorted(snaps.items()):
            for adapter, apy in values.items():
                per_adapter.setdefault(adapter, []).append(apy)
        day_moved = day_unmoved = 0
        for adapter, values in sorted(per_adapter.items()):
            if len(values) < 2:
                continue
            spread = round(max(values) - min(values), _PP)
            if spread:
                day_moved += 1
                if spread > widest:
                    widest, widest_at = spread, f"{day}/{adapter}"
            else:
                day_unmoved += 1
        moved += day_moved
        unmoved += day_unmoved
        days.append({"cycle_date": day, "snapshots": len(snaps),
                     "in_denominator": day in denominator,
                     "adapters_moved": day_moved,
                     "adapters_unmoved": day_unmoved})
    return {
        "population": ("дни НОСИТЕЛЯ с двумя и более снимками — это НЕ дни "
                       "знаменателя hit_rate; доля отсюда на знаменатель не "
                       "переносится"),
        "days_measured": len(days),
        "days_also_in_denominator": sum(1 for d in days if d["in_denominator"]),
        "adapter_days_moved": moved,
        "adapter_days_unmoved": unmoved,
        "widest_spread_pp": round(widest, _PP) if days else None,
        "widest_spread_at": widest_at,
        "days": days,
    }


# ──────────────────────── слой 3: род величин ────────────────────────
def _kind_control(carrier: Dict[str, Dict[str, Dict[str, float]]],
                  journal: List[dict]) -> dict:
    """Одна ли это величина — ставка носителя и ставка журнала.

    Сверяется ПОСЛЕДНИЙ снимок дня: именно он ближе всего к строке, которую
    писатель оставил за день. Ноль сравнимых пар ⇒ третий исход, а не «род
    совпал»: контроль, истинный по построению, — украшение.
    """
    by_day = {str(r["cycle_date"]): r for r in journal}
    matched: List[dict] = []
    diverged: List[dict] = []
    for day in sorted(carrier):
        snaps = carrier[day]
        if not snaps:
            continue
        last = snaps[sorted(snaps)[-1]]
        rates = (by_day.get(day) or {}).get(JOURNAL_RATE_KEY)
        if not isinstance(rates, dict):
            continue
        for adapter, carried in sorted(last.items()):
            if adapter not in rates:
                continue
            journaled = rates[adapter]
            if not isinstance(journaled, (int, float)):
                continue
            entry = {"cycle_date": day, "adapter": adapter,
                     "carrier_pp": carried,
                     "journal_pp": round(float(journaled), _PP)}
            if entry["carrier_pp"] == entry["journal_pp"]:
                matched.append(entry)
            else:
                diverged.append(entry)
    compared = len(matched) + len(diverged)
    if not compared:
        return {"measured": False,
                "reason": ("сравнимых пар (день × адаптер) у носителя и журнала "
                           "нет — род величин НЕ ИЗМЕРЕН; ноль сравнений не есть "
                           "совпадение"),
                "pairs_compared": 0, "matched": 0, "diverged": 0,
                "same_subject": None, "diverged_pairs": []}
    return {"measured": True,
            "pairs_compared": compared,
            "matched": len(matched),
            "diverged": len(diverged),
            "same_subject": not diverged,
            "diverged_pairs": diverged}


# ──────────────────────── слой 4: ловушка заказа ────────────────────────
def _substitution_trap(data_dir: Path) -> dict:
    """Разрешение ряда ``apy_series_daily.json`` — ЗАМЕРОМ, а не по памяти.

    Вопрос ровно один: сколько точек ряд несёт на пару (адаптер, день). Единица
    означает, что о двух прогонах одного дня он свидетельствовать не может ни
    при каком желании, и подстановка запрещена по построению, а не по традиции.
    """
    path = Path(data_dir) / SERIES_FILENAME
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": f"ряд не прочитан ({type(exc).__name__}: {exc})",
                "max_points_per_adapter_day": None,
                "substitution_admissible": None}
    series = doc.get("series")
    if not isinstance(series, dict) or not series:
        return {"measured": False,
                "reason": "в ряде нет поля `series` — разрешение не измерено",
                "max_points_per_adapter_day": None,
                "substitution_admissible": None}
    worst = 0
    points = 0
    for rows in series.values():
        if not isinstance(rows, list):
            continue
        per_day: Dict[str, int] = {}
        for point in rows:
            if isinstance(point, (list, tuple)) and point:
                day = str(point[0])[:10]
                per_day[day] = per_day.get(day, 0) + 1
                points += 1
        if per_day:
            worst = max(worst, max(per_day.values()))
    return {"measured": True,
            "adapters": len(series),
            "points": points,
            "max_points_per_adapter_day": worst,
            # Ряд годится в носители прогонов ТОЛЬКО если хоть у одной пары
            # точек больше одной. Иначе подстановка изготовила бы прогон.
            "substitution_admissible": worst > 1,
            "reason": ("ряд несёт максимум "
                       f"{worst} точк(у/и) на пару (адаптер, день): разрешения "
                       "по прогонам нет — подставлять его точку как ставку "
                       "прогона ЗАПРЕЩЕНО (ловушка заказа #554)")}


# ───────────────────────────── сборка ─────────────────────────────
def measure(data_dir: Path, *, now: Optional[datetime] = None) -> dict:
    """Полный замер. Детерминирован при тех же файлах на диске.

    ``now`` — только отметка отчёта: прибор не судит о свежести и не берёт
    времени у стены ни в одном вердикте.
    """
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)
    doc: dict = {
        "schema": VERSION,
        "generated_at": now.isoformat(),
        "order": "заказ #554 (ADR-316): двигался ли ВТОРОЙ вход тени — ставки",
        "carrier_file": CARRIER_FILENAME,
        "findings": [],
        "third_outcomes": [],
    }

    journal, jerr = read_journal(data_dir)
    doc["journal_rows"] = len(journal)
    if not journal:
        doc["status"] = STATUS_UNMEASURED
        doc["third_outcomes"].append(
            f"журнал решений не прочитан ({jerr or 'ни одной записи'}) — "
            "ни знаменатель, ни ноги дня строить не из чего")
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] журнал решений не прочитан: {jerr or 'пуст'}")
        doc["population"] = {"scoreable": 0}
        doc["coverage"] = {"measured": False, "reason": "журнал не прочитан"}
        doc["movement_outside_denominator"] = {}
        doc["kind_control"] = {"measured": False, "reason": "журнал не прочитан"}
        doc["substitution_trap"] = _substitution_trap(data_dir)
        doc["does_not_report"] = _DOES_NOT_REPORT
        doc["advisory"] = _ADVISORY
        return doc

    carrier, cerr = read_carrier(data_dir)
    denominator = scored_days(data_dir)

    doc["carrier"] = {
        "measured": not cerr,
        "reason": cerr or "",
        "days": sorted(carrier),
        "snapshots_per_day": {d: len(s) for d, s in sorted(carrier.items())},
        "snapshots_total": sum(len(s) for s in carrier.values()),
    }
    doc["substitution_trap"] = _substitution_trap(data_dir)
    doc["kind_control"] = _kind_control(carrier, journal)

    if denominator is None:
        doc["status"] = STATUS_UNMEASURED
        doc["coverage"] = {
            "measured": False,
            "reason": ("знаменатель hit_rate не получен от "
                       "shadow_trigger_eval.evaluate_window — пустое множество "
                       "здесь читалось бы как «знаменатель пуст»"),
        }
        doc["population"] = {"scoreable": 0}
        doc["movement_outside_denominator"] = _movement_outside(carrier, set())
        doc["third_outcomes"].append(
            "знаменатель hit_rate не измерен — покрытие пар не считается")
        doc["findings"].append(
            "[НЕ ИЗМЕРЕНО] знаменатель hit_rate не получен у канонического "
            "производителя — слой покрытия не строится")
        doc["does_not_report"] = _DOES_NOT_REPORT
        doc["advisory"] = _ADVISORY
        return doc

    in_denominator = [r for r in journal
                      if str(r.get("cycle_date")) in denominator]
    coverage = _coverage(in_denominator, carrier)
    doc["coverage"] = coverage
    doc["movement_outside_denominator"] = _movement_outside(carrier, denominator)
    # Счётчик покрытия для переписи потребителей журнала
    # (`decision_journal_coverage.probe_readers` берёт его ИМЕНЕМ поля).
    # Это пары, которые прибор СУМЕЛ КЛАССИФИЦИРОВАТЬ, а не рассудить: шире
    # журнал — шире знаменатель — больше пар, и рост здесь означает ровно то,
    # что означает у соседей.
    doc["population"] = {"scoreable": coverage["pairs_total"]}
    doc["status"] = _status(coverage, cerr)
    doc["third_outcomes"].extend(_third_outcomes(doc, coverage, cerr))
    doc["findings"].extend(_findings(doc, coverage))
    doc["does_not_report"] = _DOES_NOT_REPORT
    doc["advisory"] = _ADVISORY
    return doc


_DOES_NOT_REPORT = (
    "каким был бы вердикт тени при другой ставке того же дня. Прибор меряет "
    "ДВИЖЕНИЕ ВХОДА и покрытие носителя; расхождение входа не есть расхождение "
    "вердикта, и переводить одно в другое он не станет ни при каком покрытии")

_ADVISORY = (
    "ADVISORY: писатель журнала решений и его правило замены строки дня, "
    "писатель носителя apy_composition.append_history, POLLED_ADAPTERS, пины, "
    "MIN_HIT_RATE, TriggerParams, пороги RiskPolicy v1.0, потолки концентрации, "
    "стоп-кран и живой трек не тронуты; капитал не двигается")


def _status(coverage: dict, cerr: str) -> str:
    """Вердикт прибора. «Нечем измерить» и «измерено, всё тихо» — РАЗНОЕ."""
    if cerr:
        return STATUS_UNMEASURED
    if not coverage.get("pairs_total"):
        # Знаменатель пуст или у его дней нет ног — мерить нечего, и это не «OK».
        return STATUS_UNMEASURED
    if not coverage.get("pairs_adjudicable"):
        # Критерий взвода предъявлен на знаменателе, о втором входе которого
        # носитель не способен сказать НИЧЕГО. Это утверждение об ЭВИДЕНСЕ.
        return STATUS_CRITICAL
    if coverage["pairs_adjudicable"] < coverage["pairs_total"]:
        return STATUS_WARNING
    return STATUS_OK


def _third_outcomes(doc: dict, coverage: dict, cerr: str) -> List[str]:
    out: List[str] = []
    if cerr:
        out.append(f"носитель ставок по прогонам не прочитан ({cerr}) — "
                   "движение второго входа не измерено ничем")
    unresolved = coverage["pairs_total"] - coverage["pairs_adjudicable"]
    if unresolved:
        out.append(
            f"движение ставки НЕ ИЗМЕРЕНО на {unresolved} пар(ах) из "
            f"{coverage['pairs_total']}: носитель этих пар рассудить не может. "
            "Это не «ставка не двигалась» — это отсутствие наблюдения")
    trap = doc.get("substitution_trap") or {}
    if trap.get("measured") and not trap.get("substitution_admissible"):
        out.append(trap.get("reason", ""))
    kind = doc.get("kind_control") or {}
    if not kind.get("measured"):
        out.append(kind.get("reason", "род величин не измерен"))
    return [x for x in out if x]


def _findings(doc: dict, coverage: dict) -> List[str]:
    out: List[str] = []
    out.append(
        f"[ОТВЕТ] знаменатель hit_rate — {coverage['denominator_days']} дн., "
        f"пар «день × нога» {coverage['pairs_total']}; носитель "
        f"{CARRIER_FILENAME} способен рассудить "
        f"{coverage['pairs_adjudicable']} из них "
        f"(движение наблюдено на {coverage['pairs_moved']})")
    if not coverage["pairs_adjudicable"] and coverage["pairs_total"]:
        by = coverage["by_verdict"]
        out.append(
            f"[CRITICAL] о ВТОРОМ входе тени носитель не свидетельствует НИ НА "
            f"ОДНОЙ паре знаменателя ({coverage['pairs_total']} пар): "
            + ", ".join(f"{k}={v}" for k, v in by.items())
            + ". Критерий взвода hit_rate предъявлен на днях, где движение "
            "ставки внутри дня не наблюдал никто. Это утверждение об ЭВИДЕНСЕ "
            "критерия, а НЕ о том, что вердикты тех дней были неверны")
    mv = doc.get("movement_outside_denominator") or {}
    if mv.get("days_measured"):
        out.append(
            f"[ОПОРА] на НЕСВЯЗАННОМ населении — {mv['days_measured']} дн. "
            f"носителя с двумя и более снимками (из них в знаменателе "
            f"{mv['days_also_in_denominator']}) — ставка внутри дня двигалась на "
            f"{mv['adapter_days_moved']} парах (адаптер × день) против "
            f"{mv['adapter_days_unmoved']} неподвижных; самый широкий размах "
            f"{mv['widest_spread_pp']} пп ({mv['widest_spread_at']}). "
            "На знаменатель эта доля НЕ переносится")
    kind = doc.get("kind_control") or {}
    if kind.get("measured"):
        verdict = ("род ОДИН" if kind["same_subject"]
                   else f"род РАСХОДИТСЯ на {kind['diverged']} пар(ах)")
        out.append(
            f"[ПО ДНЯМ] контроль рода величин: сверено {kind['pairs_compared']} "
            f"пар (день × адаптер), совпало {kind['matched']} — {verdict}")
        for pair in kind.get("diverged_pairs") or []:
            out.append(
                f"[ПО ДНЯМ] расхождение рода {pair['cycle_date']}/"
                f"{pair['adapter']}: носитель {pair['carrier_pp']} пп против "
                f"{pair['journal_pp']} пп в журнале — на этой паре носитель не "
                "свидетельствует даже о ставке ВЫЖИВШЕГО прогона")
    for line in doc.get("third_outcomes") or []:
        out.append(f"[НЕ ИЗМЕРЕНО] {line}")
    return out


# ────────────────────────────── проводка ──────────────────────────────────
def format_report(doc: dict) -> List[str]:
    """Порядок строк — порядок заказа: ПОКРЫТИЕ первым, движение вторым.

    Заказ #554 требует этого дословно: «первым результатом обязано быть то, что
    носитель РЕАЛЬНО покрывает». Читатель, увидевший первой строкой «ставки
    двигались на N днях», прочтёт её как замер знаменателя — а население там
    другое, и прибор говорит об этом раньше, чем называет долю.
    """
    out: List[str] = []
    coverage = observed(doc, "coverage", kind=dict) or {}
    out.append(
        f"   двигался ли ВТОРОЙ вход тени — ставки (заказ #554): "
        f"{doc.get('status')} · дней журнала {doc.get('journal_rows')} · "
        f"знаменатель {coverage.get('denominator_days')} дн. · пар «день × нога» "
        f"{coverage.get('pairs_total')} · носитель рассуживает "
        f"{coverage.get('pairs_adjudicable')}")
    if not coverage.get("measured"):
        out.append(f"   покрытие НЕ ИЗМЕРЕНО: {coverage.get('reason')}")
    mv = doc.get("movement_outside_denominator") or {}
    if mv.get("days_measured"):
        out.append(
            f"   движение ставки внутри дня (население НЕ знаменателя): "
            f"{mv['adapter_days_moved']} подвижных пар против "
            f"{mv['adapter_days_unmoved']} на {mv['days_measured']} дн. "
            f"носителя, размах до {mv['widest_spread_pp']} пп")
    kind = doc.get("kind_control") or {}
    if kind.get("measured"):
        out.append(
            f"   род величин (носитель против журнала): совпало "
            f"{kind['matched']} из {kind['pairs_compared']} — "
            f"{'ОДИН предмет' if kind['same_subject'] else 'РАСХОДИТСЯ'}")
    else:
        out.append(f"   род величин НЕ ИЗМЕРЕН: {kind.get('reason')}")
    trap = doc.get("substitution_trap") or {}
    if trap.get("measured"):
        out.append(
            f"   ловушка заказа (apy_series_daily): точек на (адаптер, день) "
            f"максимум {trap['max_points_per_adapter_day']} — подстановка "
            f"{'ДОПУСТИМА' if trap['substitution_admissible'] else 'ЗАПРЕЩЕНА'}")
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
                    if x.startswith("[ПО ДНЯМ]") or x.startswith("[ОПОРА]")),
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
        description="двигался ли второй вход тени — ставки — внутри дня "
                    "(заказ #554)")
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
