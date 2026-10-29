#!/usr/bin/env python3
"""Сколько ЕЩЁ читателей не отличают «шага не звали» от «замера нуля» — население класса ADR-851.

Заказ G855 п. 4 (стоячий приказ владельца «Portfolio CIO»,
`inbox-chitatel-schitaet-naselenie-po-vsem-zapi`).

Откуда заказ
------------------------------------------------------------------------------
ADR-851 нашёл и закрыл ОДИН экземпляр класса. У поля, добавленного **АДДИТИВНО
и ВПЕРЁД**, строки, написанные ДО появления поля, его не несут, поэтому у
читателя всегда есть развилка: считать население по ВСЕМ записям или по
записям, НЕСУЩИМ поле. Пока эти два числа совпадают, разницы нет; когда поля
не несёт НИ ОДНА запись, они расходятся максимально — и ответ переворачивается.

На проде 28.10 расходились максимально: 163 записи, из них 163 без поля.
Печать шага 0-офис сказала «урезаний не было ни на одной записи — это ЗАМЕР»,
то есть ровно наоборот. Производитель (`live_trim_census`) при этом был честен
всё время: он считает `records_without_field` ОТДЕЛЬНЫМ числом. Различение
терялось У ЧИТАТЕЛЯ.

Заказ спросил НЕ «есть ли дефект ещё где-то», а **НАСЕЛЕНИЕ**: сколько в
дереве таких пар «производитель × читатель» и сколько из читателей различить
два исхода НЕ МОГУТ.

Что здесь предмет, а что НЕ предмет
------------------------------------------------------------------------------
Предмет — пара **БЛОК × ЧИТАТЕЛЬ**, где блок есть словарь, публикующий ДВА
населения одного и того же набора записей:

* «все» — `records` / `rows` / `population` / `total` …;
* «не несут» — ключ, чьё имя называет ОТСУТСТВИЕ (`records_without_field`,
  `records_without_card`, `produces_without_slo` …).

Блок, публикующий только ОДНО население, в предмет не входит: развилки у его
читателя нет вовсе. Это сказано здесь вслух, потому что соблазн — грепать
`counts`: замер 29.10 дал на нём **259** кандидатов, из которых к классу не
относится почти ни один (`counts` в дереве есть имя любого счётчика). Признак,
отвечающий на свой вопрос, ответом на нужный не является — тот же урок, что у
`subject_population_census` (ADR-327).

Почему «не читает ключ» здесь ДОКАЗАТЕЛЬСТВО, а не признак
------------------------------------------------------------------------------
Обычно статический признак прав не имеет (ADR-326/327). Здесь он доказывает
ОТРИЦАНИЕ, а отрицание доказывается именно так: если читатель НИ РАЗУ не
упоминает ключ «не несут», его вердикт от этого числа зависеть НЕ МОЖЕТ —
значения, которого код не читает, в вердикте нет по построению. Поэтому
`cannot_distinguish` есть вывод, а не подозрение.

Обратное направление признаком НЕ закрывается: «ключ читается» ещё не значит,
что вердикт на нём стои́т (прочитать и выбросить можно). Поэтому читатели,
читающие ОБА населения, уходят не в «чисто», а в отдельное значение
`reads_both` — «различить МОЖЕТ», — и доводится это до вердикта ПОВЕДЕНИЕМ:
две сцены, отличающиеся РОВНО ОДНИМ полем (:func:`drive_exemplar`).

Четыре исхода у пары, и четвёртый — значение (инв. #17)
------------------------------------------------------------------------------
``READS_BOTH``            — читает оба населения ⇒ различить МОЖЕТ;
``CANNOT_DISTINGUISH``    — читает только «все» ⇒ различить НЕ МОЖЕТ (вывод);
``READS_WITHOUT_ONLY``    — читает только «не несут» ⇒ вердикт о населении
                            «все» не выносит вовсе, развилки нет;
``PAIR_UNMEASURED``       — файл не разобран либо читатель не привязан к блоку;
                            НЕ «чисто».

Прибор только ЧИТАЕТ: ни один сторож, ни одна цель, ни один порог не меняется.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: Исходы пары «блок × читатель». Четыре, и четвёртый — ЗНАЧЕНИЕ.
READS_BOTH = "reads_both"
READS_WITHOUT_ONLY = "reads_without_only"
PAIR_UNMEASURED = "unmeasured"

#: Исходы поведенческой пробы эталона. Три, и третий — ЗНАЧЕНИЕ.
DRIVE_DISTINGUISHES = "distinguishes"
DRIVE_CONFLATES = "conflates"
DRIVE_UNMEASURED = "unmeasured"

#: Имена, которыми в дереве зовут население «ВСЕ записи». Список ЗАКРЫТ
#: намеренно: открытая маска втянула бы любой счётчик и вернула бы замер
#: `counts` (259 кандидатов, класс в них утонул).
ALL_POPULATION_RE = re.compile(
    r"^(records|rows|entries|population|total|n_records|considered)$")

#: Имя, НАЗЫВАЮЩЕЕ отсутствие. Маска открытая намеренно — именно она несёт
#: смысл класса, и автор нового блока вправе назвать своё число иначе.
WITHOUT_POPULATION_RE = re.compile(
    r"without|lacking|missing_field|no_field|not_carrying|absent")

#: Деревья, которые меряем. `tests/` исключены: тест, читающий ключ, вердикта
#: о проде не выносит.
ROOTS = ("spa_core", "scripts")

#: Сам прибор из населения ИСКЛЮЧЁН, и это названо, а не умолчано: его сцена
#: (:func:`_blank_census`) по построению публикует оба населения, поэтому
#: прибор, меряющий себя, прибавил бы к классу собственную фикстуру. Замер
#: 29.10: с собой 19 блоков, без себя 18.
SELF_PATH = "spa_core/monitoring/additive_field_reader_census.py"


def _is_test(path: str) -> bool:
    return "/tests/" in path or "/test_" in path


def _string_keys(node: ast.Dict) -> List[str]:
    return [k.value for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)]


def mapping_key_reads(tree: ast.AST):
    """Каждое чтение СТРОКОВОГО ключа из отображения: ``(ключ, строка)``.

    Три формы, и третья — не роскошь: `observed(doc, key)` есть честная форма
    чтения из `spa_core/utils/observation.py` (инв. #17), и читатель, собранный
    на ней, по `.get` найден бы не был.
    """
    for node in ast.walk(tree):
        key = None
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            key = node.args[0].value
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "observed" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)):
            key = node.args[1].value
        elif (isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            key = node.slice.value
        if isinstance(key, str):
            yield key, node.lineno


def _enclosing_functions(tree: ast.AST) -> List[Tuple[int, int, str]]:
    return [(n.lineno, getattr(n, "end_lineno", n.lineno), n.name)
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _function_at(funcs: List[Tuple[int, int, str]], lineno: int) -> str:
    best: Optional[Tuple[int, str]] = None
    for start, end, name in funcs:
        if start <= lineno <= end and (best is None or start > best[0]):
            best = (start, name)
    return best[1] if best else "<module>"


def find_blocks(root: Path) -> Tuple[List[dict], List[dict]]:
    """Блоки, публикующие ДВА населения одного набора записей.

    Возврат ``(блоки, не_разобрано)``. Второй список — третий исход на уровне
    файла: файл, который не разобрался, молча исчезнуть не вправе.
    """
    blocks: List[dict] = []
    unparsed: List[dict] = []
    for path in sorted(root.rglob("*.py")):
        rel = str(path.relative_to(root))
        if rel.split("/")[0] not in ROOTS or _is_test(rel) or rel == SELF_PATH:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            unparsed.append({"file": rel, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        funcs = _enclosing_functions(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = _string_keys(node)
            all_keys = [k for k in keys if ALL_POPULATION_RE.match(k)]
            without_keys = [k for k in keys if WITHOUT_POPULATION_RE.search(k)]
            if all_keys and without_keys:
                blocks.append({
                    "file": rel,
                    "line": node.lineno,
                    "producer": _function_at(funcs, node.lineno),
                    "keys": sorted(set(keys)),
                    "all_keys": sorted(all_keys),
                    "without_keys": sorted(without_keys),
                })
    return blocks, unparsed


def find_readers(root: Path, blocks: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Читатели ЧИСЛА ОТСУТСТВИЯ — привязка идёт по ЕГО имени, и только по нему.

    Имя числа отсутствия (``records_without_field``, ``produces_without_slo``)
    РАЗЛИЧАЮЩЕЕ: его читает тот, кто читает именно этот блок. Поэтому «ключ
    читают / не читают нигде» здесь ЗАМЕР, а не догадка.

    Чего эта привязка НЕ даёт — сказано в :func:`run_census` и в
    ``reader_axis_not_measured``: по ней нельзя найти читателя, который число
    отсутствия НЕ читает. Обе наивные попытки его найти ИЗМЕРЕНЫ и обе
    неверны — см. ADR-856.
    """
    pairs: List[dict] = []
    unparsed: List[dict] = []
    owner: Dict[str, List[dict]] = {}
    for blk in blocks:
        for key in blk["without_keys"]:
            owner.setdefault(key, []).append(blk)
    siblings = {key: {a for blk in owners for a in blk["all_keys"]}
                for key, owners in owner.items()}

    for path in sorted(root.rglob("*.py")):
        rel = str(path.relative_to(root))
        if rel.split("/")[0] not in ROOTS or _is_test(rel) or rel == SELF_PATH:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError) as exc:
            unparsed.append({"file": rel, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        funcs = _enclosing_functions(tree)
        reads = list(mapping_key_reads(tree))
        if not reads:
            continue
        per_fn: Dict[str, set] = {}
        for key, lineno in reads:
            per_fn.setdefault(_function_at(funcs, lineno), set()).add(key)
        for fn, keys in per_fn.items():
            for wkey in sorted(keys & owner.keys()):
                producers = owner[wkey]
                # Производитель читателем себя не является: он это число ПИШЕТ.
                if any(blk["file"] == rel and blk["producer"] == fn
                       for blk in producers):
                    continue
                reads_all = sorted(keys & siblings[wkey])
                pairs.append({
                    "reader_file": rel,
                    "reader": fn,
                    "without_key": wkey,
                    "reads_all": reads_all,
                    "producers": sorted({f"{b['file']}::{b['producer']}"
                                         for b in producers}),
                    "outcome": READS_BOTH if reads_all else READS_WITHOUT_ONLY,
                })
    return pairs, unparsed


def _blank_census(records: int, without: int) -> dict:
    """Перепись живого урезания, собранная РУКАМИ, — ровно две сцены ниже."""
    carrying = records - without
    return {
        "records": records,
        "records_without_field": without,
        "counts": ({"KEPT_AS_IS": carrying} if carrying else {}),
        "last_applied": None,
    }


def drive_exemplar(door=None, *, door_name: Optional[str] = None) -> dict:
    """ПОВЕДЕНЧЕСКИЙ контроль: эталон класса, две сцены, РОВНО одно отличие.

    Статика доказывает только ОТРИЦАНИЕ («ключа не читает ⇒ различить не
    может»). Положительное утверждение — «читает оба и вердикт в самом деле
    РАЗНЫЙ» — статикой не доказуемо, поэтому эталон (`live_trim_outcome`,
    ADR-851) здесь ЗАПУСКАЕТСЯ на двух сценах:

    * ``nobody_carries`` — записи есть, поля не несёт НИ ОДНА ⇒ обязан быть
      третий исход «шага не звали»;
    * ``measured_zero``  — записи есть, поле несут ВСЕ, урезаний ноль ⇒
      обязан быть ЗАМЕР нуля.

    Сцены отличаются РОВНО тем, у скольких записей есть поле. Один и тот же
    ответ на обе ⇒ ``conflates``: ровно дефект, который ADR-851 нашёл в проде.

    ``door`` инъектируется НЕ для удобства: без инъекции у пробы был бы только
    положительный контроль («сегодняшняя дверь различает»), а проверка,
    никогда не видевшая настоящей поломки, есть украшение
    (`.claude/rules/deployment.md`). Тест подаёт сюда читателя В ТОМ ВИДЕ, в
    котором он жил до ADR-851 — ветвящегося по ``records``, — и обязан получить
    ``conflates``. Умолчание — настоящая живая дверь.
    """
    name = door_name
    if door is None:
        try:
            from spa_core.paper_trading.admissible_trim import live_trim_outcome
        except Exception as exc:           # pragma: no cover - импорт эталона
            return {"kind": DRIVE_UNMEASURED,
                    "reason": f"эталон не ввозится: {type(exc).__name__}: {exc}"}
        door = live_trim_outcome
        name = name or ("spa_core.paper_trading.admissible_trim."
                        "live_trim_outcome")
    try:
        nobody = door(_blank_census(163, 163))
        zero = door(_blank_census(163, 0))
    except Exception as exc:
        return {"kind": DRIVE_UNMEASURED,
                "reason": f"эталон не отвечает: {type(exc).__name__}: {exc}"}
    same = nobody[0] == zero[0]
    return {
        "kind": DRIVE_CONFLATES if same else DRIVE_DISTINGUISHES,
        "door": name or getattr(door, "__qualname__", repr(door)),
        "scene_nobody_carries": {"outcome": nobody[0], "reason": nobody[1]},
        "scene_measured_zero": {"outcome": zero[0], "reason": zero[1]},
        "reason": ("род исхода у двух сцен ОДИН — «шага не звали» и «замер "
                   "нуля» неразличимы" if same else
                   "род исхода у двух сцен РАЗНЫЙ — различение живо"),
    }


def run_census(root: Optional[Path] = None) -> dict:
    """Весь замер одним вызовом. Прибор только ЧИТАЕТ."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    blocks, unparsed_blocks = find_blocks(root)
    pairs, unparsed_readers = find_readers(root, blocks)
    unparsed = {r["file"]: r for r in (unparsed_blocks + unparsed_readers)}

    counts = {READS_BOTH: 0, READS_WITHOUT_ONLY: 0, PAIR_UNMEASURED: 0}
    for pair in pairs:
        counts[pair["outcome"]] = counts.get(pair["outcome"], 0) + 1
    counts[PAIR_UNMEASURED] += len(unparsed)

    # Блок, у которого число отсутствия не читает НИ ОДИН найденный читатель, —
    # не «чисто»: третий исход публикуется и до вердикта не доезжает вовсе.
    reached = {key for pair in pairs for key in [pair["without_key"]]}
    unread = [{"file": b["file"], "line": b["line"], "producer": b["producer"],
               "without_keys": b["without_keys"]}
              for b in blocks
              if not (set(b["without_keys"]) & reached)]

    return {
        "measured": True,
        "root": str(root),
        "blocks": blocks,
        "block_count": len(blocks),
        "pairs": pairs,
        "pair_count": len(pairs),
        "counts": counts,
        "blocks_with_no_reader": unread,
        "unparsed": sorted(unparsed.values(), key=lambda r: r["file"]),
        "exemplar": drive_exemplar(),
        # ТРЕТИЙ ИСХОД на уровне ОСИ, а не строки: «на каком из двух населений
        # стои́т вердикт читателя, который число отсутствия НЕ читает» этим
        # прибором НЕ ИЗМЕРЕНО, и ноль здесь не печатается. Обе наивные
        # привязки измерены и обе неверны (ADR-856):
        "reader_axis_not_measured": {
            "question": ("сколько читателей судят о населении «все» и число "
                         "отсутствия НЕ читают"),
            "why": ("привязать читателя к блоку по имени ключа нельзя ни в "
                    "одну сторону, и это ЗАМЕР, а не осторожность"),
            "attempt_by_absence_key": (
                "привязка по ключу отсутствия: исход `cannot_distinguish` "
                "НЕДОСТИЖИМ по построению — читатель, не читающий ключ, в "
                "население не попадает, и прибор печатал бы «не может — 0». "
                "Это ровно тот false-zero, против которого прибор написан"),
            "attempt_by_distinctive_keys": (
                "привязка по узнаваемым ключам блока: 864 пары и 67 «находок» "
                "на замере 29.10, и они ПРОВЕРЯЕМО ложные — `rows`/`population` "
                "читает полдерева, совпадение имени родством не является"),
            "what_would_close_it": (
                "привязка по ДОРОГЕ значения (зов производителя либо чтение "
                "артефакта по пути публикации), а не по имени ключа"),
        },
        "note": (
            "население класса ADR-851 = блоки × читатели. `cannot_distinguish` "
            "есть ВЫВОД (ключа не читает ⇒ в вердикте его нет по построению), "
            "`reads_both` — только «различить МОЖЕТ», и доводит это до вердикта "
            "поведенческая проба эталона. Прибор ЧИТАЕТ и ничего не чинит"),
    }


def summary_line(report: dict) -> str:
    if not report.get("measured"):
        return ("НЕ ИЗМЕРЕНО: перепись читателей аддитивного поля — "
                f"{report.get('unmeasured_reason', 'причина не названа')}")
    c = report["counts"]
    ex = report.get("exemplar") or {}
    return (f"население класса ADR-851: блоков {report['block_count']}, "
            f"читателей числа отсутствия {report['pair_count']} "
            f"(читают ОБА населения {c[READS_BOTH]} · только отсутствие "
            f"{c[READS_WITHOUT_ONLY]} · НЕ ИЗМЕРЕНО {c[PAIR_UNMEASURED]}); "
            f"блоков, чьё число отсутствия НЕ читает никто — "
            f"{len(report['blocks_with_no_reader'])} из {report['block_count']}; "
            f"эталон — {ex.get('kind', 'НЕ ИЗМЕРЕНО')}")


def format_report(report: dict) -> List[str]:
    """Печать для шага 0-офис. Одна строка сводки + названные находки."""
    out = [summary_line(report)]
    if not report.get("measured"):
        return out
    ex = report.get("exemplar") or {}
    if ex.get("kind") == DRIVE_CONFLATES:
        out.append(f"  🔴 ЭТАЛОН КЛАССА СЛОМАН ({ex.get('door')}): "
                   f"{ex.get('reason')}")
    elif ex.get("kind") == DRIVE_UNMEASURED:
        out.append(f"  ⚠️ эталон класса НЕ ИЗМЕРЕН: {ex.get('reason')} — "
                   f"это НЕ «различение живо»")
    else:
        out.append(f"  ✅ эталон различает: «{ex['scene_nobody_carries']['outcome']}» "
                   f"против «{ex['scene_measured_zero']['outcome']}» на сценах, "
                   f"отличающихся РОВНО полем")
    for blk in report["blocks_with_no_reader"]:
        out.append(f"  ⚠️ {blk['file']}:{blk['line']} {blk['producer']}() — "
                   f"число отсутствия {blk['without_keys']} публикуется и НЕ "
                   f"читается никем: третий исход до вердикта не доезжает")
    for pair in report["pairs"]:
        if pair["outcome"] == READS_WITHOUT_ONLY:
            out.append(f"  · {pair['reader_file']}::{pair['reader']}() читает "
                       f"только `{pair['without_key']}` — вердикта о населении "
                       f"«все» не выносит, развилки у него нет")
    axis = report.get("reader_axis_not_measured") or {}
    if axis:
        out.append(f"  ⚠️ НЕ ИЗМЕРЕНО (ось, не строка): {axis['question']} — "
                   f"{axis['why']}; закрыло бы — {axis['what_would_close_it']}")
    if report["unparsed"]:
        out.append(f"  ⚠️ НЕ ИЗМЕРЕНО {len(report['unparsed'])} файл(ов): "
                   f"{report['unparsed'][0]['reason']}")
    out.append("  ADVISORY: прибор только ЧИТАЕТ — ни один сторож не изменён")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="дерево, которое мерим (умолчание — корень репозитория)")
    ap.add_argument("--json", action="store_true", help="печатать отчёт целиком")
    args = ap.parse_args(argv)

    report = run_census(Path(args.root) if args.root else None)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0 if report.get("measured") else 2
    for line in format_report(report):
        print(line)
    if not report.get("measured"):
        return 2
    ex = report.get("exemplar") or {}
    if ex.get("kind") == DRIVE_CONFLATES:
        return 1
    if ex.get("kind") == DRIVE_UNMEASURED:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
