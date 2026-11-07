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


# ---------------------------------------------------------------------------
# ОСЬ НАПРАВЛЕНИЯ ВРЕДА (ADR-945, цикл #1064, заказ G934 п. 4)
# ---------------------------------------------------------------------------
# **Зачем отдельная ось.** `survived` стенда выше означает РОВНО «пустоту не заметил
# ни один собственный тест модуля» — и НЕ означает «молча усиливает». Разбор десяти
# выживших (ADR-944) показал это сразу: `cio_explainability._BOOKS` читается как
# `for key, book_id in _BOOKS:` с накоплением в теле — пустота даёт МЕНЬШЕ находок
# (тишина, предмет ADR-939), а `presence_as_observation_census._SKIP_PARTS` читается
# как `if any(part in marker for part in _SKIP_PARTS): continue` — пустота даёт
# БОЛЬШЕ находок (шум). Оба состояния — дефекты (никто не заметил), но лечатся они
# разным, и объявить их ОДНИМ родом значило бы завести ось, несущую два бита под
# одним именем — дословно дефект, измеренный ADR-943 на осях `empty`/`other`.
#
# **И РАЗЛИЧАЮТСЯ они не только лечением, но и ОБНАРУЖИМОСТЬЮ.** Шум виден: поток
# находок, выросший на порядок, замечает читатель отчёта. Тишина не видна никому —
# «находок нет» выглядит дословно как хороший день. Поэтому `fewer` ОПАСНЕЕ `more`
# при равной мере вреда, и приоритет починки идёт по роду, а не по номеру строки.
#
# **Почему это НЕ пятая ось переписи и НЕ вторая ось признака.** Та же причина, что
# у `production` (ADR-944): ось, перекладывание внутри которой предмета не меняет,
# есть украшение. Направление не сужает и не расширяет ни предмет, ни признак — оно
# РАЗДЕЛЯЕТ уже отобранное на два рода с разными лекарствами.

#: Истинность ТИХОЙ свёртки над ПУСТЫМ перечнем: `any` → False, `all` → True,
#: `sum` → 0 (ложно). Громкие свёртки (`min`/`max`) сюда НЕ входят по построению —
#: над пустым они поднимают `ValueError`, пустота замечена, и предмета нет.
TRUTH_OVER_EMPTY: Dict[str, bool] = {"any": False, "all": True, "sum": False}

#: Утверждения, которыми ветка ИСКЛЮЧАЕТ рассматриваемый элемент из рассмотрения.
#: `Return` считается отсечкой ТОЛЬКО с пустым или константным значением: `return
#: build_finding()` исключением не является, он находку ОТДАЁТ.
CUTOFF_NODES: Tuple[type, ...] = (ast.Continue, ast.Break)

DIRECTION_OUTCOMES: Tuple[str, ...] = ("fewer", "more", "both", "unmeasured")

#: Что ветка делает с рассматриваемым элементом.
BRANCH_EFFECTS: Tuple[str, ...] = ("cutoff", "accumulates", "none")


def _is_cutoff_stmt(node: ast.stmt) -> bool:
    if isinstance(node, CUTOFF_NODES):
        return True
    return (isinstance(node, ast.Return)
            and (node.value is None or isinstance(node.value, ast.Constant)))


def branch_effect(stmts: Sequence[ast.stmt]) -> str:
    """Что ветка ДЕЛАЕТ с рассматриваемым элементом — член BRANCH_EFFECTS.

    **Отсечка имеет ПРИОРИТЕТ над накоплением, и это ВЫБОР, а не недосмотр.**
    Ветка `dirnames[:] = []` + `continue` (дословно `_SKIP_PARTS`) содержит и
    подрезку, и выход: элемент до пути находок не доходит ни при каком содержимом
    ветки, поэтому род её — отсечка. Считать такую ветку «и то и другое» значило бы
    отдать `unmeasured` там, где направление определено однозначно.
    """
    if any(_is_cutoff_stmt(stmt) for stmt in stmts):
        return "cutoff"
    return "accumulates" if _body_accumulates(stmts) else "none"


def _condition_owner(
    node: ast.AST, parents: Dict[int, ast.AST]
) -> Tuple[Optional[ast.AST], str, int]:
    """Поднимается от узла-операнда к УТВЕРЖДЕНИЮ, чьим условием он является.

    Возвращает ``(владелец, род, число отрицаний)`` либо ``(None, причина, 0)``.

    **Через `and`/`or` подъём идёт НАМЕРЕННО, и это не вольность.** Подстановка
    константы вместо ОДНОГО операнда монотонной формулы двигает «срабатывает ли
    ветка» РОВНО в одну сторону: ``A or X`` при ``A=False`` срабатывает не чаще
    исходного, при ``A=True`` — всегда; ``A and X`` при ``A=True`` срабатывает не
    реже, при ``A=False`` — никогда. Поэтому знание эффективной истинности нашего
    операнда достаточно, а значения соседних операндов не нужны. Любая НЕмонотонная
    обёртка (`==`, арифметика, вызов) подъём ОБРЫВАЕТ третьим исходом.
    """
    current = node
    negations = 0
    for _hop in range(CLIMB_DEPTH):
        parent = parents.get(id(current))
        if parent is None:
            return None, "у условия нет владельца в разборе", 0
        if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
            negations += 1
        elif isinstance(parent, ast.BoolOp):
            pass  # монотонно — см. docstring
        elif isinstance(parent, ast.If) and parent.test is current:
            return parent, "if", negations
        elif isinstance(parent, ast.comprehension) and any(
                test is current for test in parent.ifs):
            return parent, "filter", negations
        else:
            return None, f"свёртка условием не является: {type(parent).__name__}", 0
        current = parent
    return None, "подъём к условию длиннее предела", 0


def _direction_from_condition(
    prefix: str, owner: ast.AST, kind: str, fires_more: bool
) -> Tuple[str, str]:
    """Направление по УТВЕРЖДЕНИЮ, чьим условием оказалось чтение.

    Вход — ЭФФЕКТИВНАЯ истинность нашего операнда над ПУСТЫМ перечнем
    (``fires_more``), владелец условия и род владельца (``if`` либо ``filter``).

    **Почему дверь ОДНА на две формы.** Так читают перечень тихая свёртка
    (``any``/``all``/``sum``, ADR-945) и ПРОВЕРКА ПРИНАДЛЕЖНОСТИ
    (``in``/``not in``, ADR-947). Форма операнда у них разная, а дальше вопрос
    дословно один: срабатывает ветка ЧАЩЕ или РЕЖЕ и что она делает с
    рассматриваемым элементом. Своя копия этой логики у второй двери означала бы,
    что две двери расходятся МОЛЧА — ровно тот дефект, который ADR-942 измерил на
    слиянии чтений по имени.
    """
    if kind == "filter":
        # Предикат ВКЛЮЧЕНИЯ: срабатывает чаще ⇒ собирается больше.
        return (("more" if fires_more else "fewer"),
                f"{prefix} в фильтре включения, "
                f"над пустым предикат {'истинен' if fires_more else 'ложен'}")
    assert isinstance(owner, ast.If)
    arms: List[Tuple[str, str, bool]] = [("тело", branch_effect(owner.body), fires_more)]
    if owner.orelse:
        arms.append(("иначе", branch_effect(owner.orelse), not fires_more))
    verdicts: List[str] = []
    why: List[str] = []
    for label, effect, arm_fires_more in arms:
        if effect == "none":
            continue
        if effect == "cutoff":
            verdict = "fewer" if arm_fires_more else "more"
        else:
            verdict = "more" if arm_fires_more else "fewer"
        verdicts.append(verdict)
        why.append(f"{label}: {effect}, срабатывает "
                   f"{'ЧАЩЕ' if arm_fires_more else 'РЕЖЕ'} ⇒ {verdict}")
    if not verdicts:
        return "unmeasured", (f"{prefix}: ни одна ветка не исключает элемент "
                              f"и не накапливает находку")
    joined = f"{prefix}: " + " · ".join(why)
    if len(set(verdicts)) > 1:
        # ДВЕ ветки двигают счёт находок в ПРОТИВОПОЛОЖНЫЕ стороны: накопители в них
        # РАЗНЫЕ, и починка обязана смотреть на обе. Свести к одному роду значило бы
        # потерять ровно то, ради чего ось заведена.
        return "both", joined
    return verdicts[0], joined


def _direction_of_silent_fold(
    fold_name: str, fold_call: ast.AST, parents: Dict[int, ast.AST]
) -> Tuple[str, str]:
    """Направление для чтения под ТИХОЙ свёрткой: ``(исход, причина)``."""
    owner, kind, negations = _condition_owner(fold_call, parents)
    if owner is None:
        return "unmeasured", f"{fold_name}(): {kind}"
    # Эффективная истинность НАШЕГО операнда над пустым перечнем.
    fires_more = TRUTH_OVER_EMPTY[fold_name] != bool(negations % 2)
    return _direction_from_condition(f"{fold_name}()", owner, kind, fires_more)


# ---------------------------------------------------------------------------
# ПРОВЕРКА ПРИНАДЛЕЖНОСТИ — чтение рода `other` (ADR-947, цикл #1066, G936 п. 2)
# ---------------------------------------------------------------------------
# **Что это закрывает.** ADR-946 измерил, что остаток `unmeasured` держится НЕ
# пробелом разбора, а ГРАНИЦЕЙ оси: из 135 отказов 111 — «ни одного читающего
# цикла в области», потому что производное имя не ПЕРЕБИРАЮТ вовсе, а проверяют
# на принадлежность (`item in x`), передают аргументом или спрашивают длину. Ось
# направления спрашивала только чтения рода `loop` (`_loop_reads_of`), и это было
# сказано вслух как объявленная граница. Эта дверь переносит границу на ОДИН род
# чтения — проверку принадлежности, — и ни на какой другой.
#
# **Известный член класса назван ДО замера** (порядок заказа G936 п. 2):
# `if item in SKIP: continue` над ПУСТЫМ `SKIP` не отсекает НИ ОДНОГО элемента ⇒
# находок БОЛЬШЕ (`more`). Это дословно форма `_SKIP_PARTS` из ADR-945, но без
# свёртки `any`, и до этой двери прибор отвечал о ней `unmeasured` — замерено на
# сцене ДО первой правки.
#
# **Громкого исхода у формы НЕТ.** Пустая правая часть `in` не поднимает ничего
# (в отличие от `min`/`max` над пустым) — ровно поэтому форма и опасна: пустота
# молча меняет вердикт КАЖДОЙ проверки.

#: Истинность проверки принадлежности над ПУСТЫМ перечнем — при ЛЮБОМ левом
#: операнде: `x in EMPTY` ложно, `x not in EMPTY` истинно. Перечень ЗАМКНУТ:
#: оператор вне него принадлежностью не является и даёт третий исход.
MEMBERSHIP_TRUTH_OVER_EMPTY: Dict[str, bool] = {"In": False, "NotIn": True}

#: Как форма читается в причине. Текст — часть ответа: «`x in NAME`» объясняет
#: читателю отчёта, ЧТО именно прибор разобрал, а имя класса узла — нет.
MEMBERSHIP_TEXT: Dict[str, str] = {"In": "x in NAME", "NotIn": "x not in NAME"}


def membership_operand(
    node: ast.AST, parents: Dict[int, ast.AST]
) -> Tuple[Optional[ast.Compare], Optional[str], str]:
    """Является ли чтение ПРАВЫМ операндом одиночной проверки принадлежности.

    Возвращает ``(сравнение, имя оператора, "")`` либо ``(None, None, причина)``.

    **Каждый отказ назван и каждый — в сторону `unmeasured`.** Цепочка сравнений
    (`a in X in Y`) двигает истинность операнда неоднозначно. Имя СЛЕВА
    (`NAME in other`) спрашивает, не является ли сам перечень ЭЛЕМЕНТОМ чужого
    набора, — другой вопрос, и его пустота не решает. Оператор не из
    ``in``/``not in`` к принадлежности не относится вовсе. Прозрачные обёртки
    (`item in tuple(NAME)`) эта дверь НЕ проходит: подъём через них есть
    отдельный вопрос с НЕ ИЗМЕРЕННЫМ населением (заказ G936 п. 3), и пройти его
    молча значило бы ответить о том, чего не смотрели (урок ADR-940).
    """
    parent = parents.get(id(node))
    if not isinstance(parent, ast.Compare):
        where = type(parent).__name__ if parent is not None else "владельца нет"
        return None, None, f"чтение не операнд сравнения ({where})"
    if len(parent.ops) != 1:
        return None, None, "цепочка сравнений — истинность операнда не однозначна"
    if parent.comparators[0] is not node:
        return None, None, "имя СЛЕВА: вопрос не о принадлежности ему"
    op = type(parent.ops[0]).__name__
    if op not in MEMBERSHIP_TRUTH_OVER_EMPTY:
        return None, None, f"оператор `{op}` принадлежностью не является"
    return parent, op, ""


def direction_of_one_membership_read(
    hit: ast.AST, parents: Dict[int, ast.AST]
) -> Tuple[str, str]:
    """Направление вреда для ОДНОГО чтения-проверки принадлежности.

    Исход — член DIRECTION_OUTCOMES. Форма, которую дверь не разобрала, остаётся
    `unmeasured` с НАЗВАННОЙ причиной: ни тишины, ни шума она не оправдывает
    (инв. #17).
    """
    compare, op, why_not = membership_operand(hit, parents)
    if compare is None or op is None:
        return "unmeasured", f"принадлежность: {why_not}"
    owner, kind, negations = _condition_owner(compare, parents)
    if owner is None:
        return "unmeasured", f"`{MEMBERSHIP_TEXT[op]}`: {kind}"
    fires_more = MEMBERSHIP_TRUTH_OVER_EMPTY[op] != bool(negations % 2)
    return _direction_from_condition(
        f"`{MEMBERSHIP_TEXT[op]}`", owner, kind, fires_more)


def direction_of_one_read(
    hit: ast.AST, parents: Dict[int, ast.AST], seeds_left: int = -1
) -> Tuple[str, str]:
    """Направление вреда для ОДНОГО чтения рода `loop`: ``(исход, причина)``.

    Исход — член DIRECTION_OUTCOMES. «Не измерено» нулём не считается и ни за один
    род не выдаётся: форма, которую прибор не разобрал, не оправдывает ни тишины,
    ни шума (инв. #17).

    ``seeds_left`` — остаток бюджета ЗАСЕВА производного имени (ADR-946). ``-1``
    означает «бюджет не назван» и берёт ``SEED_HOPS``; ноль — прослеживание
    ОБОРВАНО, и это третий исход, а не род.
    """
    if seeds_left < 0:
        seeds_left = SEED_HOPS
    kind, loop = _enclosing_loop(hit, parents)
    if loop is None or kind is None:
        # Цикла над именем нет — но «не перебирают» ещё не значит «форма не
        # разобрана». Чтение рода `other` может быть ПРОВЕРКОЙ ПРИНАДЛЕЖНОСТИ, и
        # направление у неё выводится ровно так же, как у тихой свёртки
        # (ADR-947). Порядок здесь НЕСУЩИЙ: сперва перебор, и только при его
        # отсутствии — принадлежность; иначе дверь переписала бы уже измеренные
        # роды, а требование заказа — ошибаться в сторону `unmeasured`.
        outcome, reason = direction_of_one_membership_read(hit, parents)
        if outcome != "unmeasured":
            return outcome, reason
        return "unmeasured", f"цикл над именем не поднят; {reason}"
    if kind == "for":
        why = _body_accumulates(loop.body)  # type: ignore[union-attr]
        if why:
            return "fewer", f"`for … in NAME` с накоплением в теле ({why}): " \
                            f"над пустым витков НОЛЬ ⇒ накоплено НИЧЕГО"
        return "unmeasured", ("`for … in NAME` без накопления в теле — чего станет "
                              "меньше или больше, из формы не следует")
    if kind != "comprehension":
        return "unmeasured", f"род цикла не разобран: {kind}"
    owner = parents.get(id(loop))
    if owner is None:
        return "unmeasured", "у генератора нет владельца в разборе"
    if isinstance(owner, (ast.ListComp, ast.SetComp, ast.DictComp)):
        host = parents.get(id(owner))
        if isinstance(host, (ast.Yield, ast.YieldFrom)) or (
                isinstance(host, ast.Return) and host.value is owner):
            return "fewer", "включение СОБИРАЕТ и сразу ОТДАЁТСЯ наружу ⇒ собрано меньше"
        if isinstance(host, ast.Call) and isinstance(host.func, ast.Attribute) \
                and host.func.attr in ACCUMULATING_METHODS:
            return "fewer", (f"включение СОБИРАЕТ и сразу накапливается "
                             f"(.{host.func.attr}()) ⇒ накоплено меньше")
        # Собранное уходит дальше: меньше собранных элементов означает МЕНЬШЕ находок,
        # если это находки, и БОЛЬШЕ, если это множество-исключение. Направление решает
        # СЛЕДУЮЩИЙ шаг, и выдумывать его здесь значило бы вернуть «два бита под одним
        # именем» — ровно то, против чего ось заведена. Поэтому вопрос ПЕРЕАДРЕСУЕТСЯ
        # читателям производного имени (ADR-946), а не угадывается здесь.
        derived = bound_name(host)
        if derived is None:
            return "unmeasured", ("результат включения уходит дальше "
                                  f"({type(host).__name__ if host else 'владельца нет'}) "
                                  "и ИМЕНИ ему не дано — направление решает следующий шаг")
        if seeds_left <= 0:
            return "unmeasured", (f"цепочка производных имён длиннее бюджета "
                                  f"({SEED_HOPS}) — прослеживание ОБОРВАНО на `{derived}`")
        return _direction_through_name(derived, host, parents, seeds_left - 1)
    if isinstance(owner, ast.GeneratorExp):
        fold = parents.get(id(owner))
        if isinstance(fold, ast.Call) and isinstance(fold.func, ast.Name):
            name = fold.func.id
            if name in LOUD_FOLDS:
                return "unmeasured", (f"ГРОМКО: {name}() над пустым поднимает "
                                      f"ValueError — предмета нет")
            if name in TRUTH_OVER_EMPTY:
                return _direction_of_silent_fold(name, fold, parents)
            return "unmeasured", f"свёртка `{name}()` не объявлена ни тихой, ни громкой"
        return "unmeasured", "генератор отдаёт результат наружу без свёртки"
    return "unmeasured", f"владелец генератора не разобран: {type(owner).__name__}"


def direction(
    rows: Sequence[Dict[str, Any]], root: Optional[Path] = None
) -> Dict[str, Any]:
    """Направление вреда для КАЖДОЙ строки входа. Вход — строки `production()`
    (или `census()["rows"]`): ось имеет смысл только там, где перечень ПЕРЕБИРАЮТ.

    Решение по объявлению: роды, собранные по его чтениям, СКЛАДЫВАЮТСЯ, и
    расхождение даёт `both`, а не произвольную из двух сторон. `unmeasured` у
    ОТДЕЛЬНОГО чтения род объявления не запирает — но объявление, у которого
    измеренных чтений НЕТ ни одного, остаётся `unmeasured` целиком.
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
    tally = {outcome: 0 for outcome in DIRECTION_OUTCOMES}
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
            for hit in hits:
                outcome, reason = direction_of_one_read(hit, index)
                verdicts.append(outcome)
                why.append(f"{place}: {reason}")
        measured = {v for v in verdicts if v != "unmeasured"}
        if not measured:
            verdict = "unmeasured"
            if not verdicts:
                why.append("ни одного чтения рода `loop` — ось к объявлению не относится")
        elif measured == {"fewer"}:
            verdict = "fewer"
        elif measured == {"more"}:
            verdict = "more"
        else:
            verdict = "both"
        tally[verdict] += 1
        out.append({
            "module": row["module"], "name": row["name"], "lineno": row["lineno"],
            "form": row.get("form"), "direction": verdict, "why": why,
        })
    return {"tally": tally, "rows": out,
            "unparsable_readers": dict(reasons_of_break)}


# ---------------------------------------------------------------------------
# ЗАСЕВ ПРОИЗВОДНОГО ИМЕНИ (ADR-946, цикл #1065, заказ G935 п. 2)
# ---------------------------------------------------------------------------
# **Что это закрывает.** Ось направления (ADR-945) отдавала `unmeasured` **178** из
# 387 кандидатов, и крупнейшая причина была ОДНА: `результат включения уходит дальше`
# — 142 чтения, из них у **91** «дальше» есть ИМЯ (`x = [… for … in NAME]`), у 13
# имя объявлено с типом (`AnnAssign`). Пустота исходного перечня в этой форме
# ДОКАЗЫВАЕТ пустоту `x`: витков ноль ⇒ собрано ничего. Значит направление вреда
# лежит не здесь, а у ЧИТАТЕЛЕЙ `x`, и спрашивать его надо у них.
#
# **Почему это не выдумывание рода.** Прибор не угадывает, находки `x` или
# множество-исключение: он задаёт ТОТ ЖЕ вопрос `direction_of_one_read` следующему
# шагу и складывает ответы тем же правилом (расхождение ⇒ `both`). Новый род не
# заводится ни один; меняется только число `unmeasured`.
#
# **Ошибаться обязано в сторону `unmeasured`** (требование заказа). Поэтому засев
# ОТКАЗЫВАЕТ, едва пустота `x` перестаёт следовать из пустоты перечня: второе
# связывание имени в области, мутация на месте (`+=`, `.append()`), параметр
# функции, `global`/`nonlocal`, `except … as`, импорт под тем же именем, тело класса
# (имя класса методам не видно) — любое из этого обрывает прослеживание с НАЗВАННОЙ
# причиной. Цепочка производных имён ограничена бюджетом, и его исчерпание —
# третий исход, а не род (дословно образец ADR-932: засев до неподвижной точки,
# исчерпание = код 2).

#: Сколько раз прослеживание перепрыгивает на ПРОИЗВОДНОЕ имя. Исчерпание — третий
#: исход, а не род.
SEED_HOPS = 5

#: Области, внутри которых имя ищется целиком. `ClassDef` сюда НЕ входит намеренно:
#: связывание в теле класса методам этого класса не видно, и считать такое чтение
#: тем же именем значило бы приписать роду чужое направление.
SCOPE_NODES: Tuple[type, ...] = (
    ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
)


def _enclosing_scope(
    node: ast.AST, parents: Dict[int, ast.AST]
) -> Tuple[Optional[ast.AST], str]:
    """Область, в которой живёт связывание: ``(узел, причина-если-нет)``."""
    current: Optional[ast.AST] = parents.get(id(node))
    for _hop in range(CLIMB_DEPTH):
        if current is None:
            return None, "область связывания не найдена в разборе"
        if isinstance(current, ast.ClassDef):
            return None, "связывание в ТЕЛЕ КЛАССА — методам это имя не видно"
        if isinstance(current, SCOPE_NODES):
            return current, ""
        current = parents.get(id(current))
    return None, "подъём к области длиннее предела"


def bound_name(host: Optional[ast.AST]) -> Optional[str]:
    """Имя, которому ОДНОЗНАЧНО присвоен результат включения, либо ``None``.

    Распаковка (`a, b = …`), присвоение в элемент (`d[k] = …`) и присвоение в
    атрибут (`self.x = …`) именем НЕ считаются: у первой пустота не доказана без
    разбора формы, у двух других имя живёт в чужом объекте, и его читателей эта
    область не исчерпывает.
    """
    if isinstance(host, ast.Assign):
        if len(host.targets) == 1 and isinstance(host.targets[0], ast.Name):
            return host.targets[0].id
        return None
    if isinstance(host, ast.AnnAssign) and isinstance(host.target, ast.Name):
        return host.target.id
    if isinstance(host, ast.NamedExpr) and isinstance(host.target, ast.Name):
        return host.target.id
    return None


def rebinding_of(scope: ast.AST, name: str) -> Optional[str]:
    """Причина, по которой пустота перечня НЕ доказывает пустоту ``name``, либо
    ``None``. Любое второе связывание и любая мутация на месте — причина."""
    stores = 0
    for node in ast.walk(scope):
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == name:
            return f"`{name}` дополняется на месте (+=) — пустота не доказана"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ACCUMULATING_METHODS \
                and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == name:
            return (f"`{name}` мутируется на месте (.{node.func.attr}()) — "
                    f"пустота не доказана")
        if isinstance(node, ast.Name) and node.id == name \
                and isinstance(node.ctx, (ast.Store, ast.Del)):
            stores += 1
        elif isinstance(node, ast.arg) and node.arg == name:
            return f"`{name}` — параметр функции, пустота из перечня не следует"
        elif isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names:
            return f"`{name}` объявлен {type(node).__name__.lower()} — связывание вне области"
        elif isinstance(node, ast.ExceptHandler) and node.name == name:
            return f"`{name}` связывается `except … as` — пустота не доказана"
        elif isinstance(node, ast.alias) \
                and (node.asname or node.name.split(".")[0]) == name:
            return f"`{name}` связывается импортом — пустота не доказана"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and node.name == name:
            return f"`{name}` связывается определением {type(node).__name__} — пустота не доказана"
    if stores != 1:
        return (f"`{name}` связывается в области {stores} раз(а), а не один — "
                f"пустота не доказана")
    return None


def _direction_reads_of(
    scope: ast.AST, name: str, binder: ast.AST, parents: Dict[int, ast.AST]
) -> List[ast.AST]:
    """Чтения имени, О КОТОРЫХ ось направления вправе спросить, в области
    связывания и не принадлежащие самому связыванию.

    Фильтр по роду здесь НЕСУЩИЙ и остаётся им: `len(x)` рядом с `for … in x` —
    не вопрос о направлении, и складывать такие чтения в ответ значило бы кормить
    вердикт «не измерено» формой, которая к оси не относится вовсе.

    **Родов теперь ДВА, и второй добавлен ЗАМЕРОМ, а не на всякий случай**
    (ADR-947, заказ G936 п. 2): перебор (`for … in x`, включение) и ПРОВЕРКА
    ПРИНАДЛЕЖНОСТИ (`item in x`). Крупнейшая причина отказа ADR-946 была ровно
    «ни одного читающего ЦИКЛА в области» — 111 из 135, — то есть ось отказывала
    не потому, что форма неясна, а потому что спрашивала не о той форме.
    """
    out: List[ast.AST] = []
    for node in ast.walk(scope):
        if not (isinstance(node, ast.Name) and node.id == name
                and isinstance(node.ctx, ast.Load)):
            continue
        if _contains(binder, node):
            continue
        _kind, loop = _enclosing_loop(node, parents)
        if loop is not None:
            out.append(node)
            continue
        compare, op, _why = membership_operand(node, parents)
        if compare is not None and op is not None:
            out.append(node)
    return out


def _direction_through_name(
    name: str, binder: ast.AST, parents: Dict[int, ast.AST], seeds_left: int
) -> Tuple[str, str]:
    """Направление вреда, спрошенное у ЧИТАТЕЛЕЙ производного имени."""
    scope, why_no_scope = _enclosing_scope(binder, parents)
    if scope is None:
        return "unmeasured", f"засев `{name}` ОТКАЗАН: {why_no_scope}"
    blocked = rebinding_of(scope, name)
    if blocked is not None:
        return "unmeasured", f"засев `{name}` ОТКАЗАН: {blocked}"
    verdicts: List[str] = []
    why: List[str] = []
    for hit in _direction_reads_of(scope, name, binder, parents):
        outcome, reason = direction_of_one_read(hit, parents, seeds_left)
        verdicts.append(outcome)
        why.append(f"[{name}] {reason}")
    measured = {item for item in verdicts if item != "unmeasured"}
    if not measured:
        # Формулировка РАСШИРЯЕТСЯ, а не заменяется: прежняя дословная причина
        # («ни одного читающего цикла в области») остаётся подстрокой, поэтому
        # пробы ADR-945/946, которые её проверяют, НЕ ТРОНУТЫ ни одной строкой
        # (инв. #16). Дописано РОВНО то, о чём ось стала спрашивать.
        tail = (" · ".join(why) if why
                else "ни одного читающего цикла в области "
                     "и ни одной проверки принадлежности")
        return "unmeasured", f"засев `{name}`: рода не дало ни одно чтение — {tail}"
    joined = f"засев `{name}`: " + " · ".join(why)
    return ("both" if len(measured) > 1 else measured.pop()), joined
