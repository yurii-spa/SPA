#!/usr/bin/env python3
"""Вторая запись о деньгах: сходится ли книга с журналом ходов (двойная запись).

Шаг 3 из трёх до повторного вопроса о go-live ([ADR-286](../docs/decisions/ADR-286-owner-decisions-2026-09-09.md) §1),
вторая его половина. Первая — независимое наблюдение — упирается в ключи владельца
(ADR-257) и здесь НЕ решается и не изображается решённой.

**Почему это не то же самое, что сверка ADR-255.** Та сравнивала величину с самой собой:
обе стороны происходили из одного намерения, и расхождение было недостижимо по построению
(ADR-349 снял это утверждение). Здесь стороны РАЗНЫЕ по писателю и по времени: журнал
ходов пишется в момент решения, файл позиций — в конце цикла. Совпасть они обязаны, а
разойтись могут только от дефекта. Это двойная запись, а не наблюдение: источник по-прежнему
наш, и выдавать её за независимость было бы уверенным неверным ответом.

## Что меряется

1. **Непрерывность цепи.** `from_allocation` каждого хода обязан совпасть с
   `to_allocation` предыдущего. Разрыв означает, что состояние книги менялось МИМО
   журнала.
2. **Схождение конца.** `to_allocation` последнего хода обязан совпасть с развёрнутой
   книгой `current_positions.json`.

Разрывы РАЗДЕЛЕНЫ по природе, и это главное в приборе:

| род | признак | что означает |
|---|---|---|
| `renamed_key` | суммы совпали, множества ключей разошлись | переименование/слияние ключа пула (замер 12.09: T034, `fluid_usdc` → `fluid_fusdc`, слияние ADR-331/335) |
| `money_gap` | суммы НЕ совпали | деньги сменили состояние без записи (замер 12.09: T008, $94 999.88 → $80 000.00 — журнал пуст с 20.06 по 23.08) |

Сваливать их в один счёт нельзя: первое — дефект ИМЕНИ и лечится реестром ключей, второе —
дыра в записи о деньгах. Молчаливое прощение первого («суммы же сошлись») ослепило бы прибор
ровно на том классе, ради которого он написан.

## РОСТ состава обязан менять код возврата (ADR-1033, заказ G1021 п. 6)

Два расхождения живой книги ИСТОРИЧЕСКИЕ и закрыты быть не могут: дописать запись задним
числом значит выдумать наблюдение (`docs/37`), переписать журнал ходов значит правку записи
о деньгах, которая агенту не принадлежит (инв. #14). Решение «не закрывать» принято и названо
вслух. Цена этого решения была в другом месте: шесть циклов подряд шаг 1д давал код **1** на
одном и том же составе, и **третья дыра дала бы ТОТ ЖЕ код** — рост был виден только чтением
глазами. Прибор, чей вердикт не меняется от прихода нового дефекта, отвечает на свой вопрос,
а не на нужный.

Поэтому наблюдённый состав сверяется с ОБЪЯВЛЕННЫМ (`scripts/book_second_record_baseline.json`):

| исход | код | что это |
|---|:--:|---|
| сходится, и объявлять нечего | **0** | расхождений нет вовсе И перечень пуст |
| НОВЫХ НЕТ | **1** | наблюдённое РОВНО совпало с объявленным — статус-кво назван |
| состав РАЗОШЁЛСЯ с объявленным | **3** | пришло новое · объявленное исчезло · конец не сошёлся |
| НЕ ИЗМЕРЕНО | **2** | нет каталога/файла, файл не разобран, журнал пуст, **объявление не прочитано** |

**Личность расхождения** — `trade_id` + род + ОБЕ суммы + разошедшиеся ключи. `gap_usd` в
личность НЕ входит намеренно: он выводится из двух сумм, и сверять его отдельно значило бы
сравнивать число с самим собой (знакомый класс, ADR-349). Дыра, выросшая на том же ходу, при
этом остаётся НОВОЙ — суммы в личности именно за этим.

**Расхождение КОНЦА объявлению не подлежит** и перечнем не прощается никогда: оно про
СЕГОДНЯШНЮЮ книгу, а не про историю.

**Отсутствие объявления — НЕ ИЗМЕРЕНО, а не «всё знакомо».** Обратная подстановка («перечня
нет ⇒ считаем всё объявленным») вернула бы прежнюю слепоту тише красного вердикта — тот самый
fail-OPEN, против которого прибор и написан.

## Третий исход

Нет каталога данных, нет файла, файл не разобран, журнал пуст, объявление не прочитано ⇒
**«НЕ ИЗМЕРЕНО»** с названной причиной и кодом 2 (инв. #17). Отсутствие `data/` в рабочем
дереве — штатно и НЕ является находкой: там его нет по построению.

Коды возврата: 0 — сходится · 1 — новых расхождений нет · 2 — НЕ ИЗМЕРЕНО · 3 — состав
разошёлся с объявленным.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Допуск в долларах. Книга ведётся в центах, поэтому копейка — шум округления,
#: а не расхождение; больше центра брать нельзя: T034 разошёлся на НОЛЬ долларов
#: и всё равно обязан быть назван.
TOLERANCE_USD = 0.01


class NotMeasured(RuntimeError):
    """Замер не состоялся. Причина обязана быть названа."""


def data_dir(explicit: str | None = None) -> Path:
    d = Path(explicit or os.environ.get("SPA_DATA_DIR") or (ROOT / "data"))
    if not d.is_dir():
        raise NotMeasured(f"каталога данных нет ({d}) — в рабочем дереве это ШТАТНО "
                          f"и находкой не является")
    return d


def _load(path: Path) -> object:
    if not path.is_file():
        raise NotMeasured(f"{path.name} не найден — сверять нечего")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(f"{path.name} не разобран ({exc})") from exc


def _norm(d: object) -> dict:
    """Аллокация в сравнимом виде: нули выброшены, суммы округлены до цента."""
    out = {}
    for k, v in (d or {}).items() if isinstance(d, dict) else ():
        try:
            val = round(float(v or 0.0), 2)
        except (TypeError, ValueError):
            continue
        if val:
            out[str(k)] = val
    return out


def chain_breaks(trades: list) -> list[dict]:
    """Разрывы цепи ходов, каждый С НАЗВАННЫМ РОДОМ."""
    breaks = []
    for i in range(1, len(trades)):
        prev_to = _norm(trades[i - 1].get("to_allocation"))
        cur_from = _norm(trades[i].get("from_allocation"))
        if prev_to == cur_from:
            continue
        gap = round(sum(cur_from.values()) - sum(prev_to.values()), 2)
        breaks.append({
            "trade_id": trades[i].get("trade_id"),
            "ts": trades[i].get("ts"),
            "kind": "money_gap" if abs(gap) > TOLERANCE_USD else "renamed_key",
            "sum_before": round(sum(prev_to.values()), 2),
            "sum_after": round(sum(cur_from.values()), 2),
            "gap_usd": gap,
            "keys_only_before": sorted(set(prev_to) - set(cur_from)),
            "keys_only_after": sorted(set(cur_from) - set(prev_to)),
        })
    return breaks


def terminal_divergence(trades: list, positions: dict) -> dict | None:
    """Расхождение последнего хода с развёрнутой книгой, либо None."""
    book = positions.get("positions")
    if not isinstance(book, dict):
        raise NotMeasured("в current_positions.json нет объекта `positions` — "
                          "разворот книги не прочитан")
    last_to = _norm(trades[-1].get("to_allocation"))
    book = _norm(book)
    keys = set(last_to) | set(book)
    diff = {k: [last_to.get(k, 0.0), book.get(k, 0.0)] for k in keys
            if abs(last_to.get(k, 0.0) - book.get(k, 0.0)) > TOLERANCE_USD}
    if not diff:
        return None
    return {"last_trade_id": trades[-1].get("trade_id"),
            "sum_journal": round(sum(last_to.values()), 2),
            "sum_book": round(sum(book.values()), 2),
            "per_key": dict(sorted(diff.items()))}


def measure(ddir: str | None = None) -> dict:
    d = data_dir(ddir)
    trades = _load(d / "trades.json")
    if not isinstance(trades, list) or not trades:
        raise NotMeasured("журнал ходов пуст или не список — цепь не строится")
    positions = _load(d / "current_positions.json")
    if not isinstance(positions, dict):
        raise NotMeasured("current_positions.json не объект")
    breaks = chain_breaks(trades)
    terminal = terminal_divergence(trades, positions)
    return {
        # КАКОЕ ДЕРЕВО измерено — часть ответа, а не украшение: канон `data/` в git
        # заморожен (замер 12.09: на origin журнал несёт 7 ходов, живой — 34), поэтому
        # один и тот же прибор из прода и из worktree отвечает РАЗНОЕ, и вердикт без
        # названного каталога был бы вердиктом об окружении.
        "data_dir": str(d),
        "trades": len(trades),
        "chain_breaks": breaks,
        "money_gaps": [b for b in breaks if b["kind"] == "money_gap"],
        "renamed_keys": [b for b in breaks if b["kind"] == "renamed_key"],
        "terminal_divergence": terminal,
        "reconciles": not breaks and terminal is None,
    }


#: Объявление исторических расхождений. Живёт РЯДОМ с прибором и в git — иначе
#: «что мы уже знаем» пришлось бы держать в голове читателя, а голова читателя
#: меняется каждый цикл.
BASELINE = ROOT / "scripts" / "book_second_record_baseline.json"

#: Поля, которые обязана нести КАЖДАЯ объявленная строка. Перечень читается ИЗ
#: САМОГО объявления (ключ ``required_fields``), и этот литерал — лишь запас на
#: случай, когда объявление своего контракта не несёт: объявление, само решающее,
#: чем его мерить, не меряется ничем.
DECLARED_REQUIRED = ("trade_id", "kind", "sum_before", "sum_after", "gap_usd",
                     "keys_only_before", "keys_only_after", "reason")


def _cents(v: object) -> int:
    """Сумма в ЦЕЛЫХ центах. Книга ведётся в центах, а float сравнивать нельзя."""
    try:
        return int(round(float(v or 0.0) * 100))
    except (TypeError, ValueError) as exc:
        raise NotMeasured(f"сумма не разобрана ({v!r}: {exc})") from exc


def identity(b: dict) -> tuple:
    """Личность расхождения: ход + род + ОБЕ суммы + разошедшиеся ключи.

    ``gap_usd`` в личность НЕ входит: он выводится из двух сумм, уже вошедших сюда,
    и сверка его отдельно сравнивала бы число с самим собой. Суммы входят ОБЕ именно
    затем, чтобы выросшая на том же ходу дыра осталась НОВОЙ, а не спряталась за
    знакомым ``trade_id``.
    """
    return (str(b.get("trade_id")), str(b.get("kind")),
            _cents(b.get("sum_before")), _cents(b.get("sum_after")),
            tuple(str(k) for k in (b.get("keys_only_before") or ())),
            tuple(str(k) for k in (b.get("keys_only_after") or ())))


def load_declared(path: "str | Path | None" = None) -> dict:
    """Прочитать объявление. Любая немочь — :class:`NotMeasured` с причиной.

    **Почему fail-CLOSED.** Обратная подстановка («перечня нет ⇒ считаем всё
    объявленным») вернула бы слепоту к росту состава, и вернула бы её ТИШЕ красного
    вердикта. Подстановка в другую сторону («перечня нет ⇒ всё новое») кричала бы о
    находке, которой никто не мерил. Поэтому ни одна из двух: это третий исход.
    """
    p = Path(path) if path else BASELINE
    if not p.is_file():
        raise NotMeasured(f"объявления исторических расхождений нет ({p}) — «новое» от "
                          f"«знакомого» отличить нечем")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(f"объявление не разобрано ({p.name}: {exc})") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("declared"), list):
        raise NotMeasured(f"в объявлении {p.name} нет списка `declared` — перечень не прочитан")
    required = doc.get("required_fields")
    if not (isinstance(required, list) and required and all(isinstance(f, str) for f in required)):
        required = list(DECLARED_REQUIRED)
    rows = {}
    for i, row in enumerate(doc["declared"]):
        if not isinstance(row, dict):
            raise NotMeasured(f"строка #{i} объявления {p.name} не объект")
        missing = [f for f in required if f not in row]
        if missing:
            raise NotMeasured(f"строка #{i} объявления {p.name} (`{row.get('trade_id')}`) не несёт "
                              f"полей {missing} — объявление без своего контракта прощало бы что угодно")
        rows[identity(row)] = row
    return {"source": str(p), "rows": rows}


def classify(verdict: dict, declared: dict) -> dict:
    """Развести «новых нет» и «состав разошёлся». Ничего не чинит и не прощает."""
    seen = {}
    for b in verdict["chain_breaks"]:
        seen[identity(b)] = b
    new = [seen[k] for k in seen if k not in declared["rows"]]
    vanished = [declared["rows"][k] for k in declared["rows"] if k not in seen]
    terminal = verdict.get("terminal_divergence")
    return {
        "declared_source": declared["source"],
        "declared_count": len(declared["rows"]),
        # Порядок печати — порядок журнала ходов, а не порядок обхода множества:
        # PYTHONHASHSEED=0 в CI его фиксирует, но опираться на это нельзя.
        "new_breaks": sorted(new, key=lambda b: str(b.get("trade_id"))),
        "vanished_declared": sorted(vanished, key=lambda b: str(b.get("trade_id"))),
        # Конец объявлению не подлежит: любое его расхождение — рост состава.
        "terminal_is_new": terminal is not None,
        "diverged_from_declaration": bool(new or vanished or terminal is not None),
    }


#: Имя артефакта прогона. Прибор, не оставляющий следа, неотличим от прибора,
#: который не запускался НИ РАЗУ — и это ровно тот класс, ради которого он написан.
ARTIFACT = "book_second_record.json"


def write_artifact(verdict: dict, ddir: "str | Path | None" = None) -> "Path | None":
    """Оставить след прогона. Вернуть путь либо ``None``, если писать некуда.

    **Зачем это есть (ADR-374).** Прибор был проведён в цикл СТРОКОЙ В ПРОМПТЕ и
    ничего не писал. Значит на вопрос «запускался ли он сегодня» ответить было нечем:
    молчание прибора выглядело в точности как его исправная работа. Проверять
    ИСПОЛНЕНИЕ по промпту нельзя — промпт это намерение, а не факт.

    Замер 13.09, честно: из журнала цикла исполнение шага промпта НЕ ВИДНО вовсе —
    туда попадает итоговая сводка агента, а не его шаги. То есть прежде вывода
    «шаги не исполняются» надо было бы завести наблюдение; артефакт и есть это
    наблюдение. Пока его нет, верный ответ — «не измерено», а не «не работает».

    Запись НЕ ломает замер: не смогли записать — прибор всё равно отвечает на свой
    вопрос, и код возврата от этого не меняется. След — не цель, а свидетельство.
    """
    try:
        d = data_dir(str(ddir) if ddir else None)
    except NotMeasured:
        return None
    doc = dict(verdict)
    doc["_note"] = ("След прогона `scripts/book_second_record.py`. Пишется КАЖДЫЙ раз, "
                    "включая отказ: иначе «прибор молчал» и «прибор не запускался» "
                    "неразличимы.")
    doc["ran_at"] = datetime.now(timezone.utc).isoformat()
    try:
        from spa_core.utils.atomic import atomic_save
        # Порядок аргументов — `atomic_save(data, path)`, и он НЕ косметика:
        # перевёрнутый вызов канонической двери ОТКАЗЫВАЕТ fail-CLOSED
        # (`path must be a str/PathLike, got dict`), отказ глотает `except` ниже,
        # и запись МОЛЧА уходила в неатомарный запас — то есть инвариант #5 не
        # исполнялся здесь никогда (найдено циклом #1053, ADR-936).
        atomic_save(doc, str(d / ARTIFACT))
    except Exception:  # noqa: BLE001 — запись следа не имеет права ронять замер
        try:
            (d / ARTIFACT).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
        except OSError:
            return None
    return d / ARTIFACT


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=None, help="каталог данных (умолчание — SPA_DATA_DIR или data/)")
    ap.add_argument("--baseline", default=None,
                    help=f"объявление исторических расхождений (умолчание — {BASELINE})")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    args = ap.parse_args(argv)
    try:
        r = measure(args.data_dir)
    except NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО — {exc}")
        # След пишется и у ОТКАЗА — иначе «не смогли измерить» выглядело бы как
        # «не запускались», а это разные факты (инв. #17).
        write_artifact({"status": "unmeasured", "reason": str(exc), "reconciles": None},
                       args.data_dir)
        return 2
    # Объявление читается ПОСЛЕ замера и ДО вердикта: его немочь — такое же
    # «НЕ ИЗМЕРЕНО», и выдать её за «новых нет» значило бы вернуть прежнюю слепоту.
    try:
        declared = load_declared(args.baseline)
    except NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО — {exc}")
        write_artifact({"status": "unmeasured", "reason": str(exc), "reconciles": None, **r},
                       args.data_dir)
        return 2
    cl = classify(r, declared)
    write_artifact({"status": "measured", **r, **cl}, args.data_dir)
    if args.json:
        print(json.dumps({**r, **cl}, ensure_ascii=False, indent=2))
    # КАКОЕ объявление мерило — часть ответа: умолчание печатается так же, как
    # названный вход (иначе читатель не узнает, с чем сверяли).
    print(f"объявление: {cl['declared_source']} ({cl['declared_count']} строк"
          f"{', УМОЛЧАНИЕ' if not args.baseline else ', НАЗВАНО входом'})")
    if r["reconciles"] and not cl["diverged_from_declaration"]:
        print(f"Вторая запись сходится: {r['trades']} ходов, цепь непрерывна, "
              f"конец совпал с книгой. Каталог: {r['data_dir']}")
        return 0
    print(f"РАСХОЖДЕНИЯ второй записи ({r['trades']} ходов, каталог {r['data_dir']}):")
    for b in r["money_gaps"]:
        print(f"  ДЫРА В ЗАПИСИ  {b['trade_id']} {str(b['ts'])[:19]}: "
              f"${b['sum_before']:,.2f} → ${b['sum_after']:,.2f} "
              f"(${b['gap_usd']:+,.2f}) — деньги сменили состояние без записи")
    for b in r["renamed_keys"]:
        print(f"  ПЕРЕИМЕНОВАНИЕ {b['trade_id']} {str(b['ts'])[:19]}: суммы равны, "
              f"ключи {b['keys_only_before']} → {b['keys_only_after']}")
    if r["terminal_divergence"]:
        t = r["terminal_divergence"]
        print(f"  КОНЕЦ НЕ СОШЁЛСЯ после {t['last_trade_id']}: "
              f"журнал ${t['sum_journal']:,.2f} · книга ${t['sum_book']:,.2f}")
    if not cl["diverged_from_declaration"]:
        print(f"  ✅ НОВЫХ НЕТ: наблюдённое РОВНО совпало с объявленным "
              f"({cl['declared_count']} истори"
              f"{'ческое расхождение' if cl['declared_count'] == 1 else 'ческих расхождения'}) — "
              f"статус-кво назван, а не забыт")
        return 1
    print("  🔎 СОСТАВ РАЗОШЁЛСЯ С ОБЪЯВЛЕННЫМ — это находка ДНЯ, а не статус-кво:")
    for b in cl["new_breaks"]:
        print(f"     • НОВОЕ РАСХОЖДЕНИЕ {b['trade_id']} ({b['kind']}): "
              f"${b['sum_before']:,.2f} → ${b['sum_after']:,.2f} "
              f"(${b['gap_usd']:+,.2f}) — в объявлении его НЕТ; чинить у ПИСАТЕЛЯ журнала "
              f"ходов, дописывать в {Path(cl['declared_source']).name} ЗАПРЕЩЕНО")
    for b in cl["vanished_declared"]:
        print(f"     • ОБЪЯВЛЕННОЕ ИСЧЕЗЛО {b['trade_id']} ({b['kind']}): "
              f"${b['sum_before']:,.2f} → ${b['sum_after']:,.2f} — наблюдения больше нет. "
              f"Либо мерили НЕ ТОТ каталог, либо журнал ходов переписан")
    if cl["terminal_is_new"]:
        print("     • КОНЕЦ НЕ СОШЁЛСЯ — объявлению не подлежит по построению: "
              "это про СЕГОДНЯШНЮЮ книгу, а не про историю")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
