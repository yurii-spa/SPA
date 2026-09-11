#!/usr/bin/env python3
"""Сколько ЕЩЁ приборов судят о дне на ГРАНИЦЕ своего окна — и у скольких окно названо.

Заказ #562 (ADR-322), карточка CIO `inbox-task-portfolio-cio-dynamic-capital-alloc`.

Откуда заказ
------------------------------------------------------------------------------
ADR-322 нашёл на `orchestrator_runs.json` дефект формы: хранилище есть кольцевой
буфер, он ПОЛОН, вытеснение идёт с головы — поэтому число записей на САМОМ РАННЕМ
(граничном) дне есть **нижняя граница, а не счёт**. Прибор печатал его как счёт.

Заказ спросил не «есть ли этот дефект ещё где-то», а два числа:
**НАСЕЛЕНИЕ** таких хранилищ и **у скольких из них окно вообще названо**.
Ноль ⇒ третий исход «класс одиночный». Ловушка названа заказом заранее:
грепать по ФОРМЕ правила, а не по имени константы ``max_runs``.

Почему меряем АРТЕФАКТ, а не исходник (замер #563)
------------------------------------------------------------------------------
Первый заход мерил писателей статически: найти срез-идиому ``x = x[-CAP:]`` и
привязать её к файлу, в который хранилище сохраняется. Идиома ловится надёжно
(782 места, и эталонное — ``adapter_orchestrator.py:413`` — среди них). А вот
ПРИВЯЗКА к артефакту разваливается: путь там параметр функции (``runs_path``),
и статический разбор до имени файла не доходит. Замер #563: тот заход дал 111
артефактов, среди которых эталонного `orchestrator_runs.json` **НЕ БЫЛО**, зато
были приписанные по соседству в тексте. Положительный контроль упал — значит
число 111 отвечало не на тот вопрос, и повторять его было нельзя.

Наполнение — свойство ХРАНИЛИЩА, а не исходника, и на диске оно видно прямо:
документ либо объявляет свой потолок полем, либо нет. Поэтому мерим здесь
артефакты, и эталон воспроизводится на них дословно (см. положительный контроль
в тестах: `orchestrator_runs.json`, `max_runs=30`, `n=30`, граница 2026-09-02).

Три исхода, и третий НЕ сворачивается во второй
------------------------------------------------------------------------------
``saturation(doc, key)`` отвечает ``True`` / ``False`` / ``None``:

* ``True``  — записей не меньше объявленного потолка ⇒ голова срезана,
              граничный день ЧАСТИЧЕН, его число есть нижняя граница;
* ``False`` — потолок объявлен и не достигнут ⇒ вытеснения не было,
              граничный день измерен ПОЛНОСТЬЮ;
* ``None``  — **окно не названо**: документ не объявляет потолка. Это не
              «вытеснения не было» — это «сказать нечего». Свернуть ``None`` в
              ``False`` значило бы сделать утверждение, которого никто не делал,
              и ровно так выглядит fail-OPEN: хранилище без объявленного окна
              молча получило бы вид измеренного.

Ровно эта развилка и есть ответ на вторую половину заказа: хранилище с
``None`` — это и есть «окно не названо».

Что прибор НЕ утверждает
------------------------------------------------------------------------------
Он не утверждает, что хранилище с названным и НЕ полным окном безопасно завтра:
наполнение меняется каждым прогоном писателя, и сегодняшний ``False`` есть
замер на сегодня. Он не утверждает и что хранилище без окна дефектно — только
что про него **нечем ответить из артефакта**.

stdlib, детерминированно, read-only по умолчанию. **LLM запрещён** (инвариант #3
— это monitoring-путь).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ── формы, по которым узнаём отметку времени и потолок ───────────────────────
#
# Обе формы привязаны к тому, что РЕАЛЬНО лежит в `data/`, а не к воображению
# автора: отметка — ISO-дата в начале строки, потолок — целое поле, чьё имя
# говорит о вместимости. Имя `max_runs` здесь ЧАСТНЫЙ случай, а не образец:
# заказ прямо запретил грепать по нему.
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]")

#: Поля-кандидаты на отметку времени — сначала по имени, потом любое ISO-поле.
_TS_KEYS = ("ts", "timestamp", "time", "at", "date", "created_at",
            "generated_at", "run_at", "when", "observed_at", "sent_at")

#: Имя поля, объявляющего вместимость. ФОРМА правила: «про потолок», а не
#: конкретная константа. `max_runs`, `max_entries`, `ring_buffer_max`,
#: `log_cap`, `history_limit` — всё это одна форма.
_CAP_NAME_RE = re.compile(
    r"^(max|cap|limit|ring|window|keep|retain)[a-z0-9_]*$"
    r"|^[a-z0-9_]*(max|cap|limit|size|entries_kept)$"
)

#: Поля, которые ПОХОЖИ на потолок именем, но им не являются: это замеры,
#: пороги предметной области и настройки, не имеющие отношения к вместимости.
#: Список закрытый и обоснован поимённо — «на глаз похоже» причиной не является.
_CAP_NAME_DENY = frozenset({
    "max_drawdown", "max_drawdown_pct", "max_dd", "drawdown_max",
    "max_apy", "min_apy", "apy_max", "tvl_max", "max_tvl",
    "max_per_day", "max_cards_per_day", "position_size_max",
    "max_slippage", "max_gas", "max_age_s", "max_skew_s",
})

#: Классы хранилища.
WINDOW_NOT_NAMED = "window_not_named"
WINDOW_NAMED_UNSATURATED = "window_named_unsaturated"
WINDOW_NAMED_SATURATED = "window_named_saturated"

#: Причина третьего исхода — печатается всегда рядом с классом.
WINDOW_NOT_NAMED_REASON = (
    "окно не названо: документ не объявляет своей вместимости — наполнение "
    "неизмеримо из артефакта, и это НЕ «вытеснения не было»"
)


def day_of(record: object) -> Optional[str]:
    """День записи (``YYYY-MM-DD``) или ``None``, если отметки нет.

    ``None`` здесь — полноценный исход: запись без отметки не приписывается ни
    одному дню (в том числе не «сегодняшнему»), иначе прибор сам изготовил бы
    наблюдение, которого не было.
    """
    if not isinstance(record, dict):
        return None
    for key in _TS_KEYS:
        value = record.get(key)
        if isinstance(value, str) and _TS_RE.match(value):
            return value[:10]
    for value in record.values():
        if isinstance(value, str) and _TS_RE.match(value):
            return value[:10]
    return None


def declared_cap(doc: object) -> Optional[Tuple[str, int]]:
    """Объявленная документом вместимость ``(имя поля, значение)`` или ``None``.

    Ищется ФОРМА («поле про вместимость»), а не конкретное имя: `max_runs`
    эталона и `ring_buffer_max` соседа — одно правило. Поля из `_CAP_NAME_DENY`
    отвергаются поимённо: `max_drawdown` именем похоже на потолок, а говорит про
    предметную область, и принять его значило бы объявить окно там, где его нет.
    """
    if not isinstance(doc, dict):
        return None
    for name, value in doc.items():
        if not isinstance(name, str) or name in _CAP_NAME_DENY:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if value <= 1:
            continue
        if _CAP_NAME_RE.match(name):
            return (name, value)
    return None


def saturation(doc: object, records: object) -> Optional[bool]:
    """Полон ли буфер: ``True`` / ``False`` / ``None``.

    ``None`` — третий исход, «окно не названо». Он НЕ сворачивается в ``False``:
    ``False`` означает «потолок объявлен и не достигнут», то есть утверждение о
    том, что вытеснения точно не было. Про безымянное окно такого утверждения
    никто не делал.
    """
    cap = declared_cap(doc)
    if cap is None:
        return None
    if not isinstance(records, list):
        return None
    return len(records) >= cap[1]


def census_store(artifact: str, key: Optional[str], doc: object,
                 records: List[Any]) -> Dict[str, Any]:
    """Разбор ОДНОГО хранилища: класс, граница окна, пометка нижней границы."""
    days = [day_of(r) for r in records]
    dated = [d for d in days if d]
    undated = len(days) - len(dated)
    full = saturation(doc, records)
    cap = declared_cap(doc)
    boundary_day = min(dated) if dated else None
    boundary_count = sum(1 for d in dated if d == boundary_day) if boundary_day else 0

    if full is None:
        klass, reason = WINDOW_NOT_NAMED, WINDOW_NOT_NAMED_REASON
    elif full:
        klass = WINDOW_NAMED_SATURATED
        reason = (f"буфер ПОЛОН ({len(records)} ≥ {cap[1]} по полю `{cap[0]}`) — "
                  f"голова срезана, граничный день {boundary_day} ЧАСТИЧЕН")
    else:
        klass = WINDOW_NAMED_UNSATURATED
        reason = (f"потолок `{cap[0]}`={cap[1]} объявлен и не достигнут "
                  f"({len(records)}) — вытеснения не было")

    # Нижняя граница ставится ТОЛЬКО при доказанном наполнении. При `None`
    # ставить её было бы догадкой, при `False` — ложью.
    is_floor = bool(full)
    return {
        "artifact": artifact,
        "key": key,
        "records": len(records),
        "undated_records": undated,
        "declared_cap_field": cap[0] if cap else None,
        "declared_cap": cap[1] if cap else None,
        "window_named": cap is not None,
        "saturated": full,
        "class": klass,
        "reason": reason,
        "boundary_day": boundary_day,
        "boundary_day_records": boundary_count,
        "boundary_day_records_is_floor": is_floor,
        "days_span": len(set(dated)),
    }


def _record_lists(doc: object) -> Iterable[Tuple[Optional[str], List[Any]]]:
    """Списки записей документа: сам документ (если это список) и списки полей."""
    if isinstance(doc, list):
        yield (None, doc)
    elif isinstance(doc, dict):
        for key, value in doc.items():
            if isinstance(value, list) and value:
                yield (key, value)


#: Список считается ЖУРНАЛОМ, если у большинства записей есть отметка времени.
#: Порог назван здесь, а не спрятан в условии: список, где отметок меньшинство,
#: — не журнал, и судить его границу значило бы мерить не то население.
MIN_DATED_SHARE = 0.6
MIN_DATED_RECORDS = 3


def _is_journal(records: List[Any]) -> bool:
    dated = sum(1 for r in records if day_of(r))
    if dated < MIN_DATED_RECORDS:
        return False
    return dated >= MIN_DATED_SHARE * len(records)


def run_census(data_dir: Path) -> Dict[str, Any]:
    """Перепись всех журналов каталога данных.

    Каталога нет / ни один файл не прочитан ⇒ **третий исход целиком**:
    ``measured=False`` с названной причиной. «Не измерено» никогда не выдаётся
    за «чисто» — это общий порядок проекта, и у переписи он такой же, как у
    её предмета.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        return {"measured": False,
                "reason": f"каталог данных не найден: {data_dir}",
                "stores": [], "counts": {}}

    stores: List[Dict[str, Any]] = []
    unreadable: List[Dict[str, str]] = []
    for path in sorted(data_dir.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            unreadable.append({"artifact": path.name, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        for key, records in _record_lists(doc):
            if not _is_journal(records):
                continue
            stores.append(census_store(path.name, key, doc, records))

    if not stores and unreadable:
        return {"measured": False,
                "reason": (f"ни один журнал не прочитан ({len(unreadable)} файлов "
                           f"нечитаемы) — перепись не измерена"),
                "stores": [], "unreadable": unreadable, "counts": {}}

    named = [s for s in stores if s["window_named"]]
    saturated = [s for s in stores if s["saturated"] is True]
    counts = {
        "journals": len(stores),
        "window_named": len(named),
        "window_not_named": len(stores) - len(named),
        "saturated_boundary_is_floor": len(saturated),
        "unreadable": len(unreadable),
    }
    return {
        "measured": True,
        "data_dir": str(data_dir),
        "stores": stores,
        "unreadable": unreadable,
        "counts": counts,
        "saturated": saturated,
    }


def consumers(artifact: str, roots: Iterable[Path]) -> Dict[str, Any]:
    """Кто читает артефакт: модули, называющие его имя.

    Привязка ТЕКСТОВАЯ и названа таковой: имя файла в исходнике — свидетельство
    о том, что модуль про этот артефакт знает, а не о том, что он судит его дни.
    Отделять «читает» от «судит» обязан человек, читающий список; выдавать это
    число за население дефекта нельзя. Корень нечитаем ⇒ ``measured=False``.
    """
    found: List[str] = []
    scanned = 0
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            return {"measured": False,
                    "reason": f"корень исходников не найден: {root}", "modules": []}
        for path in root.rglob("*.py"):
            name = os.path.basename(str(path))
            if "/tests/" in str(path) or name.startswith("test_"):
                continue
            scanned += 1
            try:
                if artifact in path.read_text(encoding="utf-8", errors="replace"):
                    found.append(str(path))
            except OSError:
                continue
    if scanned == 0:
        return {"measured": False,
                "reason": "ни одного исходника не прочитано — потребители не измерены",
                "modules": []}
    return {"measured": True, "modules": sorted(found), "scanned": scanned}


def summary_line(report: Dict[str, Any]) -> str:
    """Одна строка для шага 0-офис. «Не измерено» печатается как таковое."""
    if not report.get("measured"):
        return f"перепись окон: НЕ ИЗМЕРЕНО — {report.get('reason')}"
    c = report["counts"]
    return (f"перепись окон: журналов {c['journals']} · окно названо "
            f"{c['window_named']} · НЕ названо {c['window_not_named']} · "
            f"полны сейчас (граничный день = нижняя граница) "
            f"{c['saturated_boundary_is_floor']}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=None,
                    help="каталог данных (по умолчанию — data/ рядом с репозиторием)")
    ap.add_argument("--json", action="store_true", help="печатать отчёт целиком")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else (
        Path(__file__).resolve().parents[2] / "data")
    report = run_census(data_dir)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0 if report.get("measured") else 3

    print(summary_line(report))
    if not report.get("measured"):
        return 3
    for store in report["saturated"]:
        print(f"  🔴 {store['artifact']}[{store['key']}] — {store['reason']}; "
              f"на границе {store['boundary_day_records']} записей "
              f"(НИЖНЯЯ ГРАНИЦА, не счёт)")
    not_named = report["counts"]["window_not_named"]
    if not_named:
        print(f"  ⚠️ у {not_named} журналов окно не названо — про их наполнение "
              f"артефакт не отвечает вовсе (третий исход, НЕ «чисто»)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
