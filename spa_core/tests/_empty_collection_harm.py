#!/usr/bin/env python3
"""spa_core/tests/_empty_collection_harm.py — ПРЕДМЕТ переписи перечней против ДЕФЕКТА.

# LLM_FORBIDDEN

**Чем это НЕ является.** Перепись `spa_core/monitoring/declared_collection_census.py`
(ADR-940…943) отвечает на вопрос «кто заметит, что перечень ОПУСТЕЛ», и её `subject`
есть **ВЕРХНЯЯ ГРАНИЦА вреда**, а не число дефектов: `data_integrity._TS_KEYS` был
предметом и дефектом не оказался — мутант умер на восьми сценах (ADR-942). Разницу
между «предмет» и «дефект» меряет **МУТАЦИЯ**, а не чтение.

Этот модуль закрывает ДВА разных вопроса, и склеивать их нельзя:

======================  ====================================================
дверь                   вопрос, на который она отвечает
======================  ====================================================
``production``          ПРИОРИТИЗАЦИЯ: читается ли перечень циклом, у которого
                        пустота даёт ТИХОЕ «находок нет». Это ПРИЗНАК с
                        измеримой точностью, а НЕ определение предмета —
                        складывать его в `SUBJECT_AXES` переписи запрещено
                        (см. ниже «почему это не пятая ось»)
``baseline``            ОБЪЯВЛЕНИЕ класса ИМЕНАМИ: какие перечни ИЗМЕРЕНЫ
                        мутацией как вредные (мутант ВЫЖИЛ — пустоту не
                        заметил ни один собственный тест модуля). База может
                        ТОЛЬКО УБЫВАТЬ
======================  ====================================================

**Почему `production` — не пятая ось переписи.** Ось, перекладывание внутри которой
предмета не меняет, есть украшение — ровно это ADR-943 измерил на осях `empty`/`other`
(предмет 571 → 571 на обеих крайностях). Сложить `production` в `SUBJECT_AXES` значило
бы сжать предмет 571 → 390 и ОБЪЯВИТЬ безвредными 181 перечень, у которых тело цикла
ничего не накапливает, — а пустота у них проявляется не громко, а просто НЕ
ПРОВЕРЯЕТСЯ (``for row in NAME: validate(row)`` над пустым не валидирует ничего и
молчит). Поэтому признак живёт ОТДЕЛЬНО и честно зовётся признаком: он говорит, с чего
начинать мутацию, а не кто виноват.

**Цена ошибки признака ИЗМЕРЕНА, и первая редакция была НЕВЕРНА.** Признак заказа
G933 п. 2 назывался «тело цикла ДОПИСЫВАЕТ в перечень находок» (``findings.append`` /
``yield`` / ``+= [``). Прибор, построенный дословно по нему, числил ``any(… for … in
NAME)`` родом «ничего не производит» — а **единственный ИЗВЕСТНЫЙ член класса**
(``AGGRAVATING`` в ADR-939) имеет РОВНО эту форму: ``any`` над пустым даёт ``False``,
то есть «находок нет» МОЛЧА. Контроль нашёл это до первой мутации; цена поправки —
``produces`` **291 → 390**, то есть четверть класса прибор не видел и ответил бы
«пусто» о том, чего не смотрел (урок ADR-935).

**Громкая пустота — ОТДЕЛЬНЫЙ исход, а не находка.** ``min``/``max`` над пустым
ПОДНИМАЮТ ``ValueError``: пустота замечена немедленно и шумно, поэтому такое чтение
признак СНИМАЕТ. ``any`` → ``False`` · ``all`` → ``True`` · ``sum`` → ``0`` молчат, и
все три опасны: «нарушений не найдено», «все строки в порядке», «ноль находок».

Три исхода у признака различимы (инв. #17): ``produces`` · ``no_production`` ·
``unmeasured`` (файл не разобран, узел чтения не найден, цикл не поднят). «Не
измерено» нулём не считается и за `no_production` не выдаётся.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Объявление класса ИМЕНАМИ: перечни, у которых мутация «опустошить» ВЫЖИЛА.
BASELINE_PATH = Path(__file__).resolve().parent / "empty_collection_harm_baseline.json"

#: Методы, которыми тело цикла НАКАПЛИВАЕТ находку.
ACCUMULATING_METHODS: Tuple[str, ...] = (
    "append", "appendleft", "add", "extend", "update", "setdefault",
)

#: Свёртки, у которых пустота даёт ТИХИЙ вердикт «находок нет».
SILENT_FOLDS: Tuple[str, ...] = ("any", "all", "sum")

#: Свёртки, у которых пустота ПОДНИМАЕТ исключение — она замечена ГРОМКО.
LOUD_FOLDS: Tuple[str, ...] = ("min", "max")

PRODUCTION_OUTCOMES: Tuple[str, ...] = ("produces", "no_production", "unmeasured")

#: Насколько высоко подниматься от узла имени до цикла, который его перебирает.
CLIMB_DEPTH = 40


class Unmeasured(Exception):
    """Предпосылка замера НЕ ОБЕСПЕЧЕНА. Падать громко, а не судить о пустоте."""


def _parents(tree: ast.Module) -> Dict[int, ast.AST]:
    index: Dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for _field, value in ast.iter_fields(parent):
            for child in (value if isinstance(value, list) else [value]):
                if isinstance(child, ast.AST):
                    index[id(child)] = parent
    return index


def _contains(root: ast.AST, target: ast.AST) -> bool:
    return any(node is target for node in ast.walk(root))


def _enclosing_loop(
    node: ast.AST, parents: Dict[int, ast.AST]
) -> Tuple[Optional[str], Optional[ast.AST]]:
    """Цикл/генератор, чей ИТЕРАТОР содержит узел. Поле `iter` здесь несущее:
    `for x in NAME` и `if NAME` — разные вопросы при одном типе узла."""
    current: Optional[ast.AST] = parents.get(id(node))
    hops = 0
    while current is not None and hops < CLIMB_DEPTH:
        if isinstance(current, (ast.For, ast.AsyncFor)) and _contains(current.iter, node):
            return "for", current
        if isinstance(current, ast.comprehension) and _contains(current.iter, node):
            return "comprehension", current
        current = parents.get(id(current))
        hops += 1
    return None, None


def _body_accumulates(body: Sequence[ast.stmt]) -> Optional[str]:
    """Чем именно тело цикла накапливает находку, либо None."""
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, (ast.Yield, ast.YieldFrom)):
                return "yield"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in ACCUMULATING_METHODS:
                return f".{node.func.attr}()"
            if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
                return "+="
            if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Subscript) for target in node.targets):
                return "NAME[k] ="
    return None


def production_of_one_loop(
    kind: str, loop: ast.AST, parents: Dict[int, ast.AST]
) -> Tuple[str, str]:
    """Признак ОДНОГО цикла: ``(исход, причина)``. Исход — член PRODUCTION_OUTCOMES."""
    if kind == "for":
        assert isinstance(loop, (ast.For, ast.AsyncFor))
        why = _body_accumulates(loop.body)
        return ("produces", why) if why else ("no_production", "тело не накапливает")
    if kind == "comprehension":
        owner = parents.get(id(loop))
        if owner is None:
            return "unmeasured", "у генератора нет владельца в разборе"
        if isinstance(owner, (ast.ListComp, ast.SetComp, ast.DictComp)):
            return "produces", "включение СОБИРАЕТ результат"
        if isinstance(owner, ast.GeneratorExp):
            fold = parents.get(id(owner))
            if isinstance(fold, ast.Call) and isinstance(fold.func, ast.Name):
                name = fold.func.id
                if name in LOUD_FOLDS:
                    return "no_production", f"ГРОМКО: {name}() над пустым поднимает ValueError"
                if name in SILENT_FOLDS:
                    return "produces", f"ТИХАЯ свёртка {name}()"
            return "produces", "генератор отдаёт результат наружу"
        return "unmeasured", f"владелец генератора не разобран: {type(owner).__name__}"
    return "unmeasured", f"род цикла не разобран: {kind}"


def production(
    rows: Sequence[Dict[str, Any]], root: Optional[Path] = None
) -> Dict[str, Any]:
    """Признак для КАЖДОГО предмета переписи. Вход — `census()["rows"]`.

    Решение по объявлению принимается в сторону НАХОДКИ: достаточно ОДНОГО цикла с
    тихой пустотой, чтобы объявление попало в приоритет. Обратное правило («все
    циклы обязаны производить») снимало бы с приоритета перечень, читаемый и так, и
    так, — то есть ошибалось бы в сторону НЕнаходки.
    """
    root = root or REPO_ROOT
    trees: Dict[str, Optional[ast.Module]] = {}
    parents: Dict[str, Any] = {}
    reasons_of_break: Dict[str, str] = {}

    def load(rel: str):
        if rel not in trees:
            try:
                tree = ast.parse((root / rel).read_text(errors="replace"))
            except (OSError, SyntaxError, ValueError) as exc:
                trees[rel], parents[rel] = None, None
                reasons_of_break[rel] = f"{type(exc).__name__}: {exc}"
            else:
                trees[rel], parents[rel] = tree, _parents(tree)
        return trees[rel], parents[rel]

    out: List[Dict[str, Any]] = []
    tally = {outcome: 0 for outcome in PRODUCTION_OUTCOMES}
    for row in rows:
        verdicts: List[str] = []
        why: List[str] = []
        for place in row.get("reads", {}).get("loop", []):
            rel, _, lineno = place.rpartition(":")
            tree, index = load(rel)
            if tree is None:
                verdicts.append("unmeasured")
                why.append(f"{place}: НЕ РАЗОБРАН — {reasons_of_break[rel]}")
                continue
            hits = [
                node for node in ast.walk(tree)
                if getattr(node, "lineno", None) == int(lineno)
                and ((isinstance(node, ast.Name) and node.id == row["name"])
                     or (isinstance(node, ast.Attribute) and node.attr == row["name"]))
            ]
            if not hits:
                verdicts.append("unmeasured")
                why.append(f"{place}: узел чтения не найден")
                continue
            lifted = False
            for hit in hits:
                kind, loop = _enclosing_loop(hit, index)
                if loop is None or kind is None:
                    continue
                outcome, reason = production_of_one_loop(kind, loop, index)
                verdicts.append(outcome)
                why.append(f"{place}:{kind}: {reason}")
                lifted = True
            if not lifted:
                verdicts.append("unmeasured")
                why.append(f"{place}: цикл над именем не поднят")
        if not verdicts:
            verdict = "unmeasured"
            why.append("ни одного чтения рода `loop` — предметом быть не мог")
        elif "produces" in verdicts:
            verdict = "produces"
        elif all(item == "unmeasured" for item in verdicts):
            verdict = "unmeasured"
        else:
            verdict = "no_production"
        tally[verdict] += 1
        out.append({
            "module": row["module"], "name": row["name"], "lineno": row["lineno"],
            "form": row.get("form"), "production": verdict, "why": why,
        })
    return {"tally": tally, "rows": out,
            "unparsable_readers": dict(reasons_of_break)}


def load_baseline(path: Optional[Path] = None) -> Dict[str, Any]:
    """Объявление класса. Отсутствие файла — НЕ «класс пуст», а НЕ ИЗМЕРЕНО."""
    path = path or BASELINE_PATH
    try:
        raw = path.read_text()
    except OSError as exc:
        raise Unmeasured(f"объявление не прочитано: {path} — {exc}") from exc
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Unmeasured(f"объявление не разобрано: {path} — {exc}") from exc
    for field in ("measured_at", "measured_on_commit", "scope", "harmful"):
        if field not in doc:
            raise Unmeasured(f"объявление без поля {field!r}: {path}")
    return doc


def key(module: str, name: str) -> str:
    """Ключ объявления ПАРНЫЙ: одноимённые перечни разных модулей не делят ни
    чтений (ADR-942), ни противоядий — значит не вправе делить и записи класса."""
    return f"{module}::{name}"
