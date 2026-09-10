"""Обратное заполнение переписи журнала решений — ответ владельца «Вариант Б».

Владелец ответил 2026-09-10T06:26Z на карточку
``owner-decision-zapisyvat-li-v-dnevnoe-reshenie-vse-zhiv`` **Вариант Б**:
расширить население записи вперёд И дописать ставки в уже написанные дни.
Рекомендация агента была «Вариант А» (только вперёд) — владелец выбрал иначе,
и его выбор исполняется. Условие, которое сам агент назвал в карточке, при этом
остаётся частью исполнения дословно:

    «эвиденс-класс дописанных значений будет помечен в самой записи (не «live»,
    а отдельной меткой), — иначе проба смешается молча»

## Что прибор делает

Строит ПЛАН обратного заполнения и, отдельной командой, применяет его:

* **план** — какие пары «день × нога» закрываемы точкой ряда
  ``data/apy_series_daily.json``, поимённо, с числом;
* **применение** — те же значения ложатся в строку журнала под ОТДЕЛЬНЫМ ключом
  ``apy_backfilled_pct`` с меткой пробы ``apy_backfill_grade``.

## Чего прибор НЕ делает — и это главное в его устройстве

1. **Не кладёт ни одного числа в ``apy_evidenced_pct``.** Этот словарь означает
   «ставка с живым провенансом значения», и ряд провенанса не несёт вовсе
   (ADR-305: правило накопителя — ``live_apy`` → иначе ``apy`` → фильтр только
   на конечность; 11 адаптеров из 34 сегодня не несут ``live_apy``, двое из них
   в ряду есть). Положить точку ряда туда значило бы ослабить пробу
   контрфакта (ADR-061/063) молча.
2. **Не трогает ``apy_unevidenced``.** Нога, которую писатель в ТОТ день сам
   признал без живого провенанса, такой и остаётся: дописать ей значение
   меньшей пробы значило бы перебить собственное живое суждение писателя
   значением, о котором не свидетельствует ничто. Такие пары уезжают в
   ``refused`` с причиной, а не в план.
3. **Ничего не пересчитывает.** ``hit_rate``, ``shadow_trigger_eval``,
   ``MIN_HIT_RATE``, ``TriggerParams``, пороги RiskPolicy v1.0, kill-switch и
   живой трек не трогаются. Сегодня дописанный ключ НЕ ЧИТАЕТ НИ ОДИН
   потребитель — и это сказано вслух, а не подразумевается: пока правило
   потребления не решено, применение плана не двигает ни одного вердикта.
   Вопрос «считать ли ``hit_rate`` на смешанной пробе» — предмет №1 границы
   ADR-285 (готовность к переходу с бумаги на live) и уезжает карточкой.

## Третий исход

Журнал не прочитан · ряд не прочитан или не той формы · замер материала
(:mod:`spa_core.monitoring.journal_backfill_material`) сам ``UNMEASURED``
⇒ ``UNMEASURED`` с названной причиной. **Ноль закрываемых пар при исправных
входах и «нечем мерить» — РАЗНЫЕ исходы**, и второй не выдаётся за первый.

## Почему история этого журнала переписывается, а не дополняется

У архива входов конвенция обратная («history is never rewritten — a wrong record
is followed by a correcting one»), и путать их нельзя. Накопитель ЭТОГО журнала
идемпотентен по ``cycle_date`` и сам заявляет «latest run of the day wins»
(:func:`spa_core.paper_trading.allocation_rationale.append_rationale_history`):
второй строки за тот же день в нём не бывает по построению, и читатели на это
рассчитывают. Поэтому обратное заполнение правит строку дня — но правит ТОЛЬКО
добавлением ключей, и это закреплено тестом на тождество всех прежних полей.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

VERSION = "1.0"
OUTPUT_FILENAME = "journal_population_backfill.json"

STATUS_OK = "OK"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: метка пробы дописанного значения. НЕ "live" — и это условие владельца,
#: а не украшение: ряд не несёт провенанса значения ни в каком виде.
BACKFILL_GRADE = "series_point_no_provenance"

#: ключи, которые обратное заполнение добавляет в строку журнала
KEY_VALUES = "apy_backfilled_pct"
KEY_GRADE = "apy_backfill_grade"
KEY_SOURCE = "apy_backfill_source"

#: исходы по паре
PLANNED = "planned"
REFUSED_ALREADY_EVIDENCED = "refused_already_evidenced"
REFUSED_WRITER_SAID_UNEVIDENCED = "refused_writer_said_unevidenced"
REFUSED_NO_MATERIAL = "refused_no_material"
REFUSED_DAY_NOT_IN_JOURNAL = "refused_day_not_in_journal"

WHAT_IT_DOES_NOT_PROVE = (
    "какой пробы была точка ряда в конкретный день прошлого. Прибор дописывает "
    "ЗНАЧЕНИЕ и честно метит его пробой `" + BACKFILL_GRADE + "`; утверждения "
    "«эта ставка была живой» он не делает и сделать не может")

ADVISORY = (
    "ADVISORY: дописанный ключ не читает сегодня ни один потребитель. "
    "hit_rate, shadow_trigger_eval, MIN_HIT_RATE, TriggerParams, пороги "
    "RiskPolicy v1.0, kill-switch и живой трек НЕ трогаются — капитал от "
    "обратного заполнения не двигается")


def _read_lines(path: Path) -> Tuple[Optional[List[dict]], Optional[str]]:
    """Строки журнала как объекты — либо причина, по которой их нет.

    Нечитаемая строка НЕ отбрасывается: она остаётся в списке как ``None``,
    чтобы применение плана могло сохранить её байт-в-байт. Накопитель живёт
    под тем же правилом («unreadable ≠ deletable»), и обратное заполнение не
    вправе быть свободнее его.
    """
    if not path.exists():
        return None, f"журнала нет: {path.name}"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"журнал не прочитан: {type(exc).__name__}"
    out: List[dict] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            out.append({"__raw__": line})
            continue
        out.append(obj if isinstance(obj, dict) else {"__raw__": line})
    if not out:
        return None, "журнал пуст — закрывать нечего"
    return out, None


def plan_for_pairs(lines: List[dict], points: Dict[str, Dict[str, float]],
                   pairs: List[dict]) -> dict:
    """План обратного заполнения по уже посчитанному списку отсечённых пар.

    ``pairs`` — ``per_pair`` замера материала (ADR-305). Своей копии правила
    «какая пара отсечена переписью» здесь НЕТ: она живёт в
    :mod:`spa_core.monitoring.unevidenced_leg_causes` и приходит сюда готовой.

    Отказ по паре — всегда ИМЕНОВАННЫЙ исход, а не пропущенная строка.
    """
    by_date: Dict[str, dict] = {}
    for rec in lines:
        d = rec.get("cycle_date")
        if isinstance(d, str):
            by_date[d] = rec

    plan: Dict[str, Dict[str, float]] = {}
    per_pair: List[dict] = []
    seen: set = set()

    for pair in pairs or []:
        proto = str(pair.get("protocol"))
        day = str(pair.get("forward_date"))
        if (day, proto) in seen:
            continue
        seen.add((day, proto))

        rec = by_date.get(day)
        if rec is None:
            outcome, note = REFUSED_DAY_NOT_IN_JOURNAL, "строки за этот день в журнале нет"
        elif proto in (rec.get("apy_evidenced_pct") or {}):
            outcome, note = (REFUSED_ALREADY_EVIDENCED,
                             "ставка с живым провенансом уже в записи — дописывать нечего")
        elif proto in (rec.get("apy_unevidenced") or []):
            outcome, note = (REFUSED_WRITER_SAID_UNEVIDENCED,
                             "писатель в ТОТ день сам признал ногу без живого провенанса; "
                             "значение меньшей пробы не вправе перебить его суждение")
        else:
            value = (points.get(proto) or {}).get(day)
            if value is None:
                outcome, note = REFUSED_NO_MATERIAL, "точки ряда за этот день по этой ноге нет"
            else:
                plan.setdefault(day, {})[proto] = float(value)
                outcome, note = PLANNED, None

        entry = {"forward_date": day, "protocol": proto, "outcome": outcome}
        if note:
            entry["note"] = note
        per_pair.append(entry)

    counts: Dict[str, int] = {}
    for e in per_pair:
        counts[e["outcome"]] = counts.get(e["outcome"], 0) + 1
    return {
        "plan": {d: dict(sorted(v.items())) for d, v in sorted(plan.items())},
        "per_pair": sorted(per_pair, key=lambda e: (e["forward_date"], e["protocol"])),
        "counts": counts,
        "days_touched": sorted(plan),
        "values_planned": sum(len(v) for v in plan.values()),
    }


def corrected_lines(lines: List[dict], plan: Dict[str, Dict[str, float]],
                    *, now: Optional[datetime] = None) -> List[dict]:
    """Строки журнала с дописанными ключами — чистая функция, ничего не пишет.

    Правка СТРОГО аддитивна: ни одно прежнее поле не меняется и не исчезает,
    и это не декларация, а свойство, которое меряет тест на тождество.
    Нечитаемая строка возвращается как есть.
    """
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    out: List[dict] = []
    for rec in lines:
        day = rec.get("cycle_date")
        add = plan.get(day) if isinstance(day, str) else None
        if not add or "__raw__" in rec:
            out.append(rec)
            continue
        fresh = dict(rec)
        merged = dict(fresh.get(KEY_VALUES) or {})
        merged.update({p: float(v) for p, v in add.items()})
        fresh[KEY_VALUES] = dict(sorted(merged.items()))
        fresh[KEY_GRADE] = BACKFILL_GRADE
        fresh[KEY_SOURCE] = {"file": "apy_series_daily.json", "written_at": stamp}
        out.append(fresh)
    return out


def measure(data_dir, *, now: Optional[datetime] = None,
            book_id: Optional[str] = None,
            material: Optional[dict] = None) -> dict:
    """План обратного заполнения по живым входам — или третий исход с причиной.

    ``material`` — уже посчитанный замер ADR-305 (инъекция для тестов и для
    повторного использования внутри одного прогона моста). По умолчанию
    зовётся НАСТОЯЩИЙ :func:`journal_backfill_material.measure`.
    """
    from spa_core.monitoring import journal_backfill_material as mat
    from spa_core.paper_trading.allocation_rationale import history_filename

    root = Path(data_dir)
    doc: dict = {
        "version": VERSION,
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "grade": BACKFILL_GRADE,
        "owner_answer": {
            "card": "owner-decision-zapisyvat-li-v-dnevnoe-reshenie-vse-zhiv",
            "choice": "Б",
            "answered_at": "2026-09-10T06:26:38.834637+00:00",
        },
        "what_it_does_not_prove": WHAT_IT_DOES_NOT_PROVE,
        "advisory": ADVISORY,
        "findings": [],
    }

    if material is None:
        material = mat.measure(root, now=now, book_id=book_id)
    doc["material_status"] = material.get("status")
    if material.get("status") == mat.STATUS_UNMEASURED:
        doc["status"] = STATUS_UNMEASURED
        doc["reason"] = ("замер материала (ADR-305) сам UNMEASURED: "
                         f"{material.get('reason') or 'причина не названа'}")
        doc["findings"].append("[НЕ ИЗМЕРЕНО] " + doc["reason"])
        return doc

    lines, why = _read_lines(root / history_filename(book_id))
    if lines is None:
        doc["status"] = STATUS_UNMEASURED
        doc["reason"] = why
        doc["findings"].append("[НЕ ИЗМЕРЕНО] " + str(why))
        return doc

    try:
        series = json.loads((root / mat.SERIES_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        doc["status"] = STATUS_UNMEASURED
        doc["reason"] = f"ряд не прочитан: {type(exc).__name__}"
        doc["findings"].append("[НЕ ИЗМЕРЕНО] " + doc["reason"])
        return doc
    if not isinstance(series, dict) or not isinstance(series.get("series"), dict):
        doc["status"] = STATUS_UNMEASURED
        doc["reason"] = "ряд не той формы: нет словаря `series`"
        doc["findings"].append("[НЕ ИЗМЕРЕНО] " + doc["reason"])
        return doc

    points = mat.series_points(series["series"])
    built = plan_for_pairs(lines, points, material.get("per_pair") or [])
    doc.update(built)
    doc["journal_lines"] = len(lines)
    doc["status"] = STATUS_OK if built["values_planned"] else STATUS_CRITICAL

    counts = built["counts"]
    doc["findings"].append(
        f"[ПЛАН] обратное заполнение закрывает {built['values_planned']} "
        f"пар(ы) «день × нога» на {len(built['days_touched'])} дн. журнала; "
        f"значения ложатся под ключ `{KEY_VALUES}` с меткой пробы "
        f"`{BACKFILL_GRADE}` и НЕ смешиваются с `apy_evidenced_pct`")
    refused = {k: v for k, v in counts.items() if k != PLANNED}
    if refused:
        doc["findings"].append(
            "[ОТКАЗЫ ИМЕНОВАНЫ] " + " · ".join(
                f"{k}={v}" for k, v in sorted(refused.items())))
    if not built["values_planned"]:
        doc["findings"].append(
            "[CRITICAL] закрываемых пар НЕ ОСТАЛОСЬ — при исправных входах это "
            "ответ, а не отсутствие замера: смотри `counts`, там названа причина "
            "по каждой паре")
    doc["findings"].append(
        "[НЕ ПОТРЕБЛЯЕТСЯ] дописанный ключ не читает сегодня ни один прибор — "
        "применение плана не двигает ни одного вердикта, пока правило "
        "потребления не решено (предмет №1 границы ADR-285)")
    return doc


def apply_plan(data_dir, *, plan: Dict[str, Dict[str, float]],
               book_id: Optional[str] = None,
               now: Optional[datetime] = None) -> dict:
    """Записать план в журнал АТОМАРНО, сняв резерв ДО правки, а не после.

    Возвращает квитанцию: путь резерва, сколько строк тронуто, сколько значений
    дописано. Пустой план — законный вход: тогда не пишется ничего и резерв не
    снимается (правка, которой нет, не нуждается в откате).
    """
    from spa_core.paper_trading.allocation_rationale import history_filename
    from spa_core.utils.atomic import atomic_save_text

    root = Path(data_dir)
    path = root / history_filename(book_id)
    lines, why = _read_lines(path)
    if lines is None:
        return {"applied": False, "reason": why}
    if not plan:
        return {"applied": False, "reason": "план пуст — писать нечего",
                "lines_touched": 0, "values_written": 0}

    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_suffix(path.suffix + f".bak.{stamp}")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    fresh = corrected_lines(lines, plan, now=now)
    payload = "\n".join(
        rec["__raw__"] if "__raw__" in rec
        else json.dumps(rec, sort_keys=True, default=str)
        for rec in fresh
    ) + "\n"
    atomic_save_text(payload, str(path))
    return {
        "applied": True,
        "backup": str(backup),
        "lines_touched": sum(1 for r in fresh if KEY_VALUES in r),
        "values_written": sum(len(v) for v in plan.values()),
    }


def format_report(doc: dict) -> List[str]:
    """Строки для консоли моста находок — без своего второго набора правил."""
    out = [f"обратное заполнение переписи журнала (ответ владельца Б): "
           f"{doc.get('status')}"]
    if doc.get("status") == STATUS_UNMEASURED:
        out.append(f"   НЕ ИЗМЕРЕНО: {doc.get('reason')}")
        return out
    out.append(f"   план: {doc.get('values_planned')} значений на "
               f"{len(doc.get('days_touched') or [])} дн. · метка пробы "
               f"`{doc.get('grade')}`")
    for f in doc.get("findings") or []:
        out.append(f"   {f}")
    out.append("   " + ADVISORY)
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        book_id: Optional[str] = None) -> dict:
    """Померить и положить артефакт рядом с остальными — атомарно."""
    from spa_core.utils.atomic import atomic_save

    base = Path(root) if root else Path(
        os.environ.get("SPA_DATA_DIR")
        or Path(__file__).resolve().parents[2] / "data")
    doc = measure(base, now=now, book_id=book_id)
    atomic_save(doc, str(base / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--book-id", default=None)
    ap.add_argument("--apply", action="store_true",
                    help="записать план в журнал (резерв снимается ДО правки)")
    args = ap.parse_args(argv)

    doc = run(args.data_dir, book_id=args.book_id)
    for line in format_report(doc):
        print(line)
    if args.apply:
        if doc.get("status") == STATUS_UNMEASURED:
            print("ОТКАЗ: план не измерен — применять нечего")
            return 2
        receipt = apply_plan(
            Path(args.data_dir) if args.data_dir else Path(
                os.environ.get("SPA_DATA_DIR")
                or Path(__file__).resolve().parents[2] / "data"),
            plan=doc.get("plan") or {}, book_id=args.book_id)
        print(f"применение: {receipt}")
    return 0 if doc.get("status") != STATUS_UNMEASURED else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
