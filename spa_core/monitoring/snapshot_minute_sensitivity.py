"""Решает ли МИНУТА снимка — и где теряется наблюдённое значение (заказ #549).

Заказ цикла #549 (ADR-311) поставил вопрос ровно так: **где именно теряется
НАБЛЮДЁННОЕ значение между оркестратором и записью решения — и решает ли вердикт
МИНУТА снимка?** 08.09 наблюдение ``pendle`` было в 07:03Z и в 13:06Z, а запись
17:27Z его не несёт. Гипотеза, которую надо ПРОВЕРИТЬ, а не принять: наблюдение
мигает ВНУТРИ дня, и запись фотографирует один момент.

**Ловушка названа заказом заранее.** ``adapter_feed_divergence_log.jsonl``
оставляет строку ТОЛЬКО при расхождении, поэтому «сколько прогонов дня наблюдали
ставку» он по построению ЗАНИЖАЕТ: согласие следа не оставляет. Считать по нему
частоту мигания — верный ответ не на тот вопрос, и прибор этот файл не читает
вовсе. Носитель прошлого здесь другой и двусторонний:
``data/apy_composition_log.jsonl`` несёт ``observed_at`` (когда шёл прогон),
``snapshot`` (какой снимок оркестратора он видел) и ``apy`` — то есть пишет
строку на КАЖДОЕ наблюдение, а не только на разошедшееся.

## Две поверхности, и у них разные ответы

1. **Мигает ли значение внутри дня.** Пары «день × адаптер», у которых носитель
   знает ДВА и более РАЗНЫХ снимка, сверяются между собой. Меньше двух снимков ⇒
   ``unmeasured_single_snapshot``, а НЕ «неподвижно»: один замер не есть
   наблюдение неподвижности, и выдать его за неё значило бы подставить ответ
   вместо замера.

2. **Решает ли миганиe ВЕРДИКТ, а не только число.** Размах внутри дня сам по
   себе ничего не решает — решает он в сравнении с МАРЖОЙ, на которой стои́т
   цель. Маржа берётся готовой из ``data/target_stability.json``
   (``protocols[].margin_pp``) — второе определение маржи здесь не заводится.
   Маржи нет ⇒ ``unmeasured_no_margin``, и claim про вердикт НЕ выдаётся.

   ⚠️ Границу надо назвать вслух: ``target_stability`` меряет ход ставки
   ОТ ДНЯ К ДНЮ (одна точка на день из журнала решений), а этот прибор — размах
   ВНУТРИ одного дня. Числа разные по смыслу и не заменяют друг друга; маржа
   берётся оттуда только как порог, а не как замер хода.

## Где теряется значение: класс на каждую пару, и отказ там, где нечем мерить

Пары «день × нога» из ``apy_unevidenced`` записи решения разбираются по тому,
что о них может сказать ДАТИРОВАННЫЙ носитель:

* ``observed_but_absent_from_record`` — наблюдение с конечной ставкой у этой
  ноги в этот день ЕСТЬ, и снимок, который оно видело, НЕ НОВЕЕ записи. Только
  тогда это настоящая дыра транскрипции: запись МОГЛА это значение видеть;
* ``unmeasured_carrier_newer_than_record`` — наблюдение есть, но его снимок
  НОВЕЕ записи. Запись не могла видеть будущее, и назвать такую пару дырой
  значило бы изготовить находку из неизмеренного. Замер 10.09 ровно таков:
  ``fluid_usdc`` в снимке 07:59:45 живой, а запись дня сделана в 07:59:42 — на
  три секунды РАНЬШЕ. Пара не измерена, а не «потеряна»;
* ``unmeasured_no_dated_carrier`` — ни одной строки о паре. Носитель узок
  (5 повторяющихся адаптеров), и его молчание НЕ есть молчание фида;
* ``feed_error_at_source`` — датированный носитель показывает, что значения не
  было и у самого оркестратора (``status`` не ``ok``/``partial`` либо ставка не
  конечна) И этот носитель СОПОСТАВИМ с записью по времени. Тогда терять между
  оркестратором и записью было нечего: потеря лежит ВЫШЕ оркестратора.

Снимок ``adapter_orchestrator_status.json`` перезаписывается каждым прогоном,
поэтому он свидетельствует о записи ТОЛЬКО когда его ``generated_at`` не новее
``generated_at`` записи. Это не осторожность, а единственное, что он вправе
утверждать.

**ADVISORY.** Прибор ничего не чинит и не предлагает чинить молча: ни
``POLLED_ADAPTERS``, ни пины, ни писатель журнала решений, ни ``TriggerParams``,
ни пороги RiskPolicy v1.0, ни стоп-кран, ни живой трек не трогаются, капитал не
двигается. Живое ``data/`` открывается на запись ровно один раз — для
собственного артефакта.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.utils.observation import observed

log = logging.getLogger("spa.monitoring.snapshot_minute_sensitivity")

VERSION = "snapshot-minute-sensitivity-v1"
OUTPUT_FILENAME = "snapshot_minute_sensitivity.json"
SCHEMA = "snapshot-minute-sensitivity/1.0"

HISTORY_FILENAME = "allocation_rationale_history.jsonl"
COMPOSITION_FILENAME = "apy_composition_log.jsonl"
SNAPSHOT_FILENAME = "adapter_orchestrator_status.json"
STABILITY_FILENAME = "target_stability.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Классы потери. Порядок — порядок разбора, он же порядок печати.
CLASS_GATE = "dropped_by_funding_gate"
CLASS_HOLE = "observed_but_absent_from_record"
CLASS_FEED_ERROR = "feed_error_at_source"
CLASS_NEWER = "unmeasured_carrier_newer_than_record"
CLASS_NO_CARRIER = "unmeasured_no_dated_carrier"

LOSS_CLASSES = (CLASS_GATE, CLASS_HOLE, CLASS_FEED_ERROR, CLASS_NEWER,
                CLASS_NO_CARRIER)

#: Вердикты поверхности «мигает ли значение внутри дня».
MOVE_MOVED = "moved"
MOVE_STILL = "still"
MOVE_UNMEASURED = "unmeasured_single_snapshot"

#: Вердикты поверхности «решает ли мигание вердикт».
DECIDES = "minute_decides_target"
MARGIN_HOLDS = "margin_holds"
NO_MARGIN = "unmeasured_no_margin"


def _is_finite(x) -> bool:
    """Конечное число и НЕ bool (``True`` — это 1, и она бы прошла как ставка)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    return x == x and x not in (float("inf"), float("-inf"))


def _parse_ts(value: object) -> Optional[datetime]:
    """ISO-отметка → aware ``datetime``. Не разобралось ⇒ ``None``, не «сейчас»."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _read_jsonl(path: Path) -> Tuple[List[dict], Optional[str]]:
    """Строки файла или причина, по которой их нет. Битая строка не роняет файл."""
    if not path.exists():
        return [], f"нет файла {path.name}"
    rows: List[dict] = []
    bad = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(rec, dict):
                    rows.append(rec)
    except OSError as exc:  # pragma: no cover — доступ к файлу
        return [], f"{path.name} нечитаем: {exc}"
    if not rows:
        return [], f"{path.name} пуст (битых строк {bad})"
    return rows, None


def _read_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    if not path.exists():
        return None, f"нет файла {path.name}"
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, f"{path.name} нечитаем: {exc}"
    return (doc, None) if isinstance(doc, dict) else (None, f"{path.name}: не объект")


# --------------------------------------------------------------------------
# поверхность 1 — мигает ли значение внутри дня
# --------------------------------------------------------------------------

def observation_index(rows: Sequence[dict]) -> Dict[Tuple[str, str], Dict[str, float]]:
    """(день, адаптер) → {снимок: ставка}.

    Ключ снимка — ОТМЕТКА СНИМКА, а не отметка прогона: два прогона, увидевшие
    один снимок, суть одно наблюдение, и считать их двумя значило бы объявить
    миганием повторное чтение одного и того же файла.
    """
    index: Dict[Tuple[str, str], Dict[str, float]] = {}
    for rec in rows:
        adapter = rec.get("adapter")
        apy = rec.get("apy")
        observed = _parse_ts(rec.get("observed_at"))
        if not isinstance(adapter, str) or not adapter or observed is None:
            continue
        if not _is_finite(apy):
            continue
        snap = rec.get("snapshot")
        if not isinstance(snap, str) or not snap.strip():
            continue
        key = (observed.date().isoformat(), adapter)
        index.setdefault(key, {})[snap] = float(apy)
    return index


def within_day_movement(index: Dict[Tuple[str, str], Dict[str, float]]) -> List[dict]:
    """Размах ставки внутри дня по парам «день × адаптер». Отсортировано."""
    out: List[dict] = []
    for (day, adapter), snaps in sorted(index.items()):
        values = [snaps[s] for s in sorted(snaps)]
        if len(snaps) < 2:
            verdict, spread = MOVE_UNMEASURED, None
        else:
            spread = round(max(values) - min(values), 4)
            verdict = MOVE_STILL if spread == 0.0 else MOVE_MOVED
        out.append({
            "day": day,
            "adapter": adapter,
            "snapshots": len(snaps),
            "first_snapshot": sorted(snaps)[0],
            "last_snapshot": sorted(snaps)[-1],
            "apy_min_pp": round(min(values), 4) if values else None,
            "apy_max_pp": round(max(values), 4) if values else None,
            "spread_pp": spread,
            "verdict": verdict,
        })
    return out


# --------------------------------------------------------------------------
# поверхность 2 — решает ли мигание ВЕРДИКТ
# --------------------------------------------------------------------------

def margin_index(stability: Optional[dict]) -> Dict[str, float]:
    """протокол → маржа в пп из ``target_stability.json``. Нет числа ⇒ нет ключа."""
    if not isinstance(stability, dict):
        return {}
    out: Dict[str, float] = {}
    for row in stability.get("protocols") or []:
        if not isinstance(row, dict):
            continue
        name = row.get("protocol")
        margin = row.get("margin_pp")
        if isinstance(name, str) and name and _is_finite(margin):
            out[name] = float(margin)
    return out


def verdict_sensitivity(movement: Sequence[dict],
                        margins: Dict[str, float]) -> List[dict]:
    """Сверяет размах ВНУТРИ дня с маржой, на которой стои́т цель.

    Считается только по парам, которые ИЗМЕРЕНЫ и ДВИНУЛИСЬ: у неподвижной пары
    сравнивать нечего, у неизмеренной — нечем.
    """
    out: List[dict] = []
    for row in movement:
        if row["verdict"] != MOVE_MOVED:
            continue
        margin = margins.get(row["adapter"])
        if margin is None:
            verdict = NO_MARGIN
        elif row["spread_pp"] > margin:
            verdict = DECIDES
        else:
            verdict = MARGIN_HOLDS
        out.append({
            "day": row["day"],
            "adapter": row["adapter"],
            "spread_pp": row["spread_pp"],
            "margin_pp": margin,
            "verdict": verdict,
        })
    return out


# --------------------------------------------------------------------------
# где теряется значение
# --------------------------------------------------------------------------

def _record_stamp(rec: dict) -> Optional[datetime]:
    """Отметка записи решения. ``run_ts`` бывает ``null`` — тогда ``generated_at``."""
    return _parse_ts(rec.get("run_ts")) or _parse_ts(rec.get("generated_at"))


def snapshot_testimony(snapshot: Optional[dict],
                       record_stamp: Optional[datetime]
                       ) -> Tuple[Dict[str, dict], bool, str]:
    """Что вправе сказать перезаписываемый снимок о ДАННОЙ записи.

    Возвращает ``(протокол → строка снимка, сопоставим ли, причина)``.

    Строки отдаются ВСЕГДА, когда снимок разобран, а право свидетельствовать —
    отдельным флагом. Разделение существенно: «носителя о паре нет вовсе» и
    «носитель есть, но он новее записи» — РАЗНЫЕ третьи исхода, и склеив их мы
    сообщили бы, что о ноге не знает никто, тогда как на самом деле знает, но
    не о том моменте. Снимок свидетельствует ТОЛЬКО когда его ``generated_at``
    не новее отметки записи: запись не могла видеть будущее.
    """
    if not isinstance(snapshot, dict):
        return {}, False, "снимка нет"
    rows: Dict[str, dict] = {}
    for a in snapshot.get("adapters") or []:
        if isinstance(a, dict) and isinstance(a.get("protocol"), str):
            rows[a["protocol"]] = a
    snap_ts = _parse_ts(snapshot.get("generated_at"))
    if snap_ts is None:
        return rows, False, "у снимка нет разбираемой отметки"
    if record_stamp is None:
        return rows, False, "у записи нет разбираемой отметки"
    if snap_ts > record_stamp:
        return rows, False, (f"снимок {snap_ts.isoformat()} НОВЕЕ записи "
                             f"{record_stamp.isoformat()}")
    return rows, True, "сопоставим"


def classify_losses(history: Sequence[dict],
                    index: Dict[Tuple[str, str], Dict[str, float]],
                    snapshot: Optional[dict]) -> List[dict]:
    """Класс на каждую пару «день × нога без живой ставки»."""
    out: List[dict] = []
    for rec in history:
        day = rec.get("cycle_date")
        if not isinstance(day, str) or not day:
            continue
        stamp = _record_stamp(rec)
        testimony, comparable, why = snapshot_testimony(snapshot, stamp)
        for leg in observed(rec, "apy_unevidenced", kind=(list, tuple)) or []:
            if not isinstance(leg, str) or not leg:
                continue
            snaps = index.get((day, leg)) or {}
            klass, detail = CLASS_NO_CARRIER, None
            record_as_of = (observed(rec, "apy_as_of", kind=dict) or {}).get(leg)
            if isinstance(record_as_of, str) and record_as_of.strip():
                # Носитель, у которого вопроса о сопоставимости НЕТ ПО
                # ПОСТРОЕНИЮ: момент наблюдения лежит в ТОЙ ЖЕ записи (ADR-312).
                # Момент наблюдения есть, а живого провенанса у ноги нет ⇒ между
                # оркестратором и записью значение НЕ терялось: ногу снял гейт
                # финансирования (`_fundable` в аллокаторе), и он же стёр
                # провенанс наблюдения. Поле аддитивно и действует ВПЕРЁД — на
                # 36 написанных строках его нет, и они честно попадают в третий
                # исход ниже, а не в этот класс.
                klass = CLASS_GATE
                detail = (f"запись несёт момент наблюдения {record_as_of}, но не "
                          f"несёт живого провенанса — нога снята гейтом "
                          f"финансирования, а не потеряна по дороге")
            elif snaps:
                # Наблюдение годится в свидетели только если снимок, который оно
                # видело, НЕ НОВЕЕ записи.
                usable = sorted(s for s in snaps
                                if stamp is not None
                                and _parse_ts(s) is not None
                                and _parse_ts(s) <= stamp)  # type: ignore[operator]
                if usable:
                    klass = CLASS_HOLE
                    detail = f"наблюдение {usable[-1]} несло {snaps[usable[-1]]} пп"
                else:
                    klass = CLASS_NEWER
                    detail = (f"все {len(snaps)} наблюдений дня новее записи "
                              f"{stamp.isoformat() if stamp else '—'}")
            elif leg in testimony:
                row = testimony[leg]
                if not comparable:
                    # Носитель ЕСТЬ и ногу называет, но о ЭТОЙ записи говорить
                    # не вправе. Это не «о ноге не знает никто».
                    klass = CLASS_NEWER
                    detail = f"снимок называет ногу, но {why}"
                elif (row.get("status") not in ("ok", "partial")
                        or not _is_finite(row.get("apy_pct"))):
                    klass = CLASS_FEED_ERROR
                    detail = (f"снимок сопоставим и несёт status="
                              f"{row.get('status')!r}, apy={row.get('apy_pct')!r}")
                else:
                    klass = CLASS_HOLE
                    detail = (f"снимок сопоставим и несёт живую ставку "
                              f"{row.get('apy_pct')} пп")
            else:
                detail = f"датированного носителя о паре нет ({why})"
            out.append({"day": day, "leg": leg, "class": klass, "detail": detail})
    return out


# --------------------------------------------------------------------------
# замер
# --------------------------------------------------------------------------

def measure(data_dir, *, now: Optional[datetime] = None) -> dict:
    """Полный замер. Часы — ВХОД (``now``), а не окружение."""
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)

    history, hist_why = _read_jsonl(data_dir / HISTORY_FILENAME)
    comp, comp_why = _read_jsonl(data_dir / COMPOSITION_FILENAME)
    snapshot, _snap_why = _read_json(data_dir / SNAPSHOT_FILENAME)
    stability, _stab_why = _read_json(data_dir / STABILITY_FILENAME)

    doc: dict = {
        "schema": SCHEMA,
        "version": VERSION,
        "generated_at": now.isoformat(),
        "status": STATUS_UNMEASURED,
        "findings": [],
        "advisory": ("POLLED_ADAPTERS, пины, писатель журнала решений, "
                     "TriggerParams, пороги RiskPolicy v1.0, стоп-кран и живой "
                     "трек НЕ трогаются — прибор только называет место потери"),
        "does_not_report": (
            "подкласс ошибки фида (молчал источник · значение вне полосы · не "
            "спросили адаптер) — снимок его не несёт; и каким был бы вердикт, "
            "если бы запись фотографировала ДРУГОЙ снимок дня: контрфакт "
            "требует прогона аллокатора на снимке прошлого, а снимки прошлого "
            "перезаписаны"),
    }

    # Третий исход — ОТДЕЛЬНО у каждого носителя: без журнала мерить нечего
    # вовсе, без переписи наблюдений нельзя говорить о мигании. Молчание одного
    # из них не есть «ничего не происходит».
    if hist_why:
        doc["unmeasured_reason"] = f"журнал решений: {hist_why}"
        doc["findings"].append(f"[НЕ ИЗМЕРЕНО] {doc['unmeasured_reason']}")
        return doc
    if comp_why:
        doc["unmeasured_reason"] = f"перепись наблюдений: {comp_why}"
        doc["findings"].append(
            f"[НЕ ИЗМЕРЕНО] {doc['unmeasured_reason']} — без неё «мигает ли "
            f"ставка внутри дня» не измеряется, а НЕ отвечается «не мигает»")
        doc["journal_rows"] = len(history)
        return doc

    index = observation_index(comp)
    movement = within_day_movement(index)
    margins = margin_index(stability)
    sensitivity = verdict_sensitivity(movement, margins)
    losses = classify_losses(history, index, snapshot)

    moved = [m for m in movement if m["verdict"] == MOVE_MOVED]
    still = [m for m in movement if m["verdict"] == MOVE_STILL]
    unmeas = [m for m in movement if m["verdict"] == MOVE_UNMEASURED]
    decides = [s for s in sensitivity if s["verdict"] == DECIDES]
    holds = [s for s in sensitivity if s["verdict"] == MARGIN_HOLDS]
    no_margin = [s for s in sensitivity if s["verdict"] == NO_MARGIN]

    class_counts = {c: sum(1 for l in losses if l["class"] == c) for c in LOSS_CLASSES}

    doc.update({
        "journal_rows": len(history),
        "observation_rows": len(comp),
        "population": {
            "pairs_total": len(movement),
            "pairs_with_two_or_more_snapshots": len(moved) + len(still),
            "pairs_single_snapshot": len(unmeas),
            "loss_pairs": len(losses),
        },
        "movement": movement,
        "sensitivity": sensitivity,
        "losses": losses,
        "class_counts": class_counts,
        "margin_source": (STABILITY_FILENAME if margins else None),
    })

    findings: List[str] = doc["findings"]
    measured = len(moved) + len(still)
    if measured:
        findings.append(
            f"[ОТВЕТ] значение МИГАЕТ внутри дня: из {measured} пар "
            f"«день × адаптер» с двумя и более снимками двинулись {len(moved)}, "
            f"остались неподвижны {len(still)}. Гипотеза заказа #549 "
            f"ПОДТВЕРЖДЕНА замером на том населении, которое носитель покрывает")
    else:
        findings.append(
            "[НЕ ИЗМЕРЕНО] ни одной пары с двумя и более снимками — мигание не "
            "измерено, и это НЕ «ставка неподвижна»")
    if unmeas:
        findings.append(
            f"[НЕ ИЗМЕРЕНО] {len(unmeas)} пар видели ровно один снимок: один "
            f"замер не есть наблюдение неподвижности")

    if decides:
        worst = max(decides, key=lambda s: s["spread_pp"] - (s["margin_pp"] or 0.0))
        findings.append(
            f"[CRITICAL] МИНУТА РЕШАЕТ ЦЕЛЬ, а не только число: на {len(decides)} "
            f"парах размах ставки ВНУТРИ дня превышает маржу, на которой стои́т "
            f"цель. Худшая — {worst['adapter']} {worst['day']}: размах "
            f"{worst['spread_pp']} пп при марже {worst['margin_pp']} пп. Запись "
            f"фотографирует ОДИН снимок дня, и какой именно — решает минута "
            f"прогона, а не рынок")
    if holds:
        findings.append(
            f"[ИНФО] на {len(holds)} парах размах внутри дня меньше маржи — там "
            f"минута цель не переставляет")
    if no_margin:
        findings.append(
            f"[НЕ ИЗМЕРЕНО] {len(no_margin)} двинувшихся пар не с чем сравнить: "
            f"маржи для их адаптера в {STABILITY_FILENAME} нет, и вердикт про "
            f"них не выдаётся")

    if class_counts[CLASS_GATE]:
        findings.append(
            f"[ОТВЕТ] на {class_counts[CLASS_GATE]} парах значение НЕ терялось "
            f"по дороге: запись несёт момент наблюдения, а живого провенанса у "
            f"ноги нет — её снял ГЕЙТ ФИНАНСИРОВАНИЯ, и он же стёр провенанс "
            f"наблюдения")
    if class_counts[CLASS_HOLE]:
        findings.append(
            f"[CRITICAL] дыра транскрипции ДОКАЗАНА на {class_counts[CLASS_HOLE]} "
            f"парах: значение было у сопоставимого по времени носителя, а запись "
            f"его не несёт — потеря лежит МЕЖДУ наблюдением и записью")
    if class_counts[CLASS_FEED_ERROR]:
        findings.append(
            f"[ОТВЕТ] на {class_counts[CLASS_FEED_ERROR]} парах терять было "
            f"нечего: у самого оркестратора значения не было — потеря выше "
            f"оркестратора, а не между ним и записью")
    if class_counts[CLASS_NEWER]:
        findings.append(
            f"[НЕ ИЗМЕРЕНО] {class_counts[CLASS_NEWER]} пар: единственный "
            f"носитель НОВЕЕ записи. Запись не могла видеть будущее, и назвать "
            f"такую пару дырой значило бы изготовить находку из неизмеренного")
    if class_counts[CLASS_NO_CARRIER]:
        findings.append(
            f"[НЕ ИЗМЕРЕНО] {class_counts[CLASS_NO_CARRIER]} пар: датированного "
            f"носителя о них нет вовсе. Перепись наблюдений узка, и её молчание "
            f"НЕ есть молчание фида")

    if decides or class_counts[CLASS_HOLE]:
        doc["status"] = STATUS_CRITICAL
    elif moved or losses:
        doc["status"] = STATUS_WARNING
    else:
        doc["status"] = STATUS_OK
    return doc


def format_report(doc: dict) -> List[str]:
    """Порядок строк — порядок вопроса: население → мигание → вердикт → классы."""
    out: List[str] = []
    pop = doc.get("population") or {}
    out.append(
        f"   решает ли МИНУТА снимка (заказ #549): {doc.get('status')} · "
        f"дней журнала {doc.get('journal_rows')} · пар день×адаптер "
        f"{pop.get('pairs_total')} · из них с ≥2 снимками "
        f"{pop.get('pairs_with_two_or_more_snapshots')} · пар потери "
        f"{pop.get('loss_pairs')}")
    counts = doc.get("class_counts")
    if counts:
        named = " · ".join(f"{c}={n}" for c, n in counts.items() if n)
        if named:
            out.append(f"   классы потери: {named}")
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
        "warn": sum(1 for x in findings if x.startswith("[ИНФО]")),
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
        description="решает ли МИНУТА снимка и где теряется наблюдённое "
                    "значение (заказ #549)")
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
