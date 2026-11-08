#!/usr/bin/env python3
"""СУДЬБА пойманного исключения у глушителя — род, который предмет ДВИГАЕТ.

# LLM_FORBIDDEN

**Что это закрывает.** ADR-950 измерил громкость 82 индексирующих чтений `x[k]`
за границей своей функции и ответил: заглушено звавшим **66**, громко через всё
замыкание **0**, НЕ ИЗМЕРЕНО **16**. Заказ G939 п. 1 назвал род для этих 66
главным делом следующего цикла — и поставил условие, выросшее из цены ADR-943:

> Замер есть, запрет снят; остаётся урок ADR-943: расширение замкнутого перечня
> родов дало предмет 571 → 571, две оси понесли ОДИН бит, и дефект был в ОТЧЁТЕ,
> а не в перечне. Поэтому сперва прогнать ось с родом и без рода, сравнить
> предмет, и только потом править.

Условие исполнено дословно, и порядок здесь не косметический: **крайности
меряются ДО того, как род начинает судить.** Вопрос «покупает ли род хоть один
бит» задаётся КОНСТРУКЦИИ, а не тексту отчёта, и у него два разных ответа,
которые до замера неотличимы:

| ответ | что значит | что делать |
|---|---|---|
| крайности СОВПАЛИ | род не способен сдвинуть предмет НИКОГДА — украшение (случай ADR-943) | не заводить; чинить ОТЧЁТ |
| крайности РАЗОШЛИСЬ | род предмет двигает ПО ПОСТРОЕНИЮ | заводить; а СКОЛЬКО он двигает на этом дереве — ВТОРОЙ, отдельный замер |

Два этих замера смешивать нельзя. «Род ничего не поменял на нашем дереве» и
«род не способен ничего поменять» — разные утверждения, и первое не влечёт
второго: род, двигающий предмет по построению, остаётся верным описанием вреда,
даже если сегодня все его значения оказались одним.

**Сам род.** Глушитель — это `try: <вызов> … except <род>:` у звавшего. Пустота
нашего перечня поднимает `LookupError`, обработчик её ловит, и дальше судьба
пойманного исключения бывает ровно трёх видов плюс третий исход:

| судьба | что делает обработчик | вред |
|---|---|---|
| `reraised` | поднимает исключение ДАЛЬШЕ — безусловно | пустота НЕ потеряна: глушитель на этом участке глушителем не является |
| `renamed` | записывает ПРИЧИНУ под ДРУГИМ именем | пустота не теряется, а ПЕРЕИМЕНОВЫВАЕТСЯ — мисдиагноз |
| `lost` | не оставляет следа вовсе (`pass`, `return <константа>`, подстановка умолчания) | пустота исчезает молча |
| `unmeasured` | обработчик в эти роды не разобран | не выдаётся ни за один из трёх (инв. #17) |

`renamed` — это дословно измеренный ADR-950 случай моста находок: пустой
перечень поднимает `LookupError`, мост глотает и докладывает
`census_skipped: KeyError: 'gate'`, то есть **мисдиагноз, а не потеря**.

**`reraised` ТРЕБУЕТ ДОКАЗАТЕЛЬСТВА и не достаётся умолчанием** — ровно как
`loud` в ADR-950, и по той же причине: это единственная судьба, СНИМАЮЩАЯ чтение
с предмета, а снять его неверно дороже, чем оставить. Поэтому `raise` под `if`
даёт `unmeasured`, а не `reraised`: часть путей из обработчика выходит молча, и
утверждать «пустота не потеряна» нельзя ни в одну сторону.

**Что считается ЗАПИСЬЮ причины — вопрос «выходит ли пойманное исключение за
обработчик», а не «какой формы его тело».** Первая редакция этого прибора
спрашивала форму последнего оператора и объявляла `return` бесследным; контроль
на НАСТОЯЩИХ членах дерева (требование `.claude/rules/acceptance.md` п. 3)
опроверг её сразу же и в ОПАСНУЮ сторону. Господствующая форма в дереве —

    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": f"живой замер не состоялся: {type(exc).__name__}: {exc}"}

то есть пойманное исключение уходит наружу СТРОКОЙ под чужим именем. Это
дословно `renamed`, а первая редакция назвала бы это `lost` — у трёх известных
членов класса из трёх (`reachability_of_the_rest._cross`,
`criterion_sign_price.scorable_days`,
`rule_second_copy_census.open_class_counter_census`). Поэтому мерой записи
служит ДОРОГА ЗНАЧЕНИЯ: имя, связанное `except … as <имя>`, прочитанное где-либо
в теле обработчика, либо вызов, оставляющий след (:data:`RECORDING_METHODS`).

**Ошибка каждой двери идёт в сторону БÓЛЬШЕГО вреда.** `renamed` мягче `lost`
(мисдиагноз лучше потери), поэтому он ТРЕБУЕТ доказательства: нет ни дороги
значения, ни записывающего вызова ⇒ `lost`. Тело, не разобранное ни в одну из
трёх судеб, — `unmeasured`, а не `lost` и не `renamed` (инв. #17).

**Прибор только ЧИТАЕТ.** Ни один глушитель не снимается и не правится:
`except Exception` у моста находок и у бегуна шага 0-офис есть ОБЪЯВЛЕННОЕ
решение (ADR-950), и менять его значило бы менять поведение ОБЯЗАТЕЛЬНЫХ шагов
цикла.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Судьбы пойманного исключения. Перечень ЗАМКНУТ: судьба вне него краснит
#: сторожа, а не проезжает молча (урок ADR-932 о собственном контракте).
FATES: Tuple[str, ...] = ("reraised", "renamed", "lost", "unmeasured")

#: Судьбы, при которых глушитель глушителем ОСТАЁТСЯ. Выводятся из замкнутого
#: :data:`FATES`, а не перечисляются руками: разойдись перечень с выводом, и
#: утверждение «предмет двигает ровно `reraised`» перестало бы быть верным МОЛЧА.
SILENCING_FATES: Tuple[str, ...] = tuple(f for f in FATES if f != "reraised")

#: Методы, которыми обработчик ЗАПИСЫВАЕТ причину. Присутствие любого — это
#: `renamed`: след остался, но под другим именем.
RECORDING_METHODS: frozenset = frozenset({
    "append", "add", "extend", "insert", "update", "setdefault",
    "warning", "warn", "error", "exception", "critical", "info", "debug", "log",
    "write", "writelines", "put", "send", "record", "report", "note",
})

#: Свободные функции, оставляющие след.
RECORDING_CALLS: frozenset = frozenset({"print"})

#: Узлы, НЕ оставляющие следа сами по себе.
TRACELESS = (ast.Pass, ast.Continue, ast.Break)

#: Сколько уровней вложенности обработчика прибор проходит. ВЫБОР, а не свойство
#: дерева; исчерпание предела — ТРЕТИЙ исход, а не судьба.
BODY_DEPTH = 40


def _own_scope(nodes: Sequence[ast.AST]):
    """Узлы тела обработчика БЕЗ вложенных областей связывания.

    Вложенное объявление функции не исполняется поимкой исключения, и считать его
    `raise` поднятием значило бы выдать отложенный код за состоявшееся действие.
    """
    stack: List[ast.AST] = list(nodes)
    seen = 0
    while stack:
        node = stack.pop()
        seen += 1
        if seen > BODY_DEPTH * 100:
            return
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Lambda, ast.ClassDef)):
            # ВНУТРЬ отложенного кода не спускаемся. Проверять РЕБЁНКА вместо
            # самого узла — дефект первой редакции: `def later(): raise …` в
            # теле обработчика объявлялся условным `raise`, то есть отложенный
            # код выдавался за состоявшееся действие (нашёл свой же контроль).
            continue
        for child in ast.iter_child_nodes(node):
            stack.append(child)


def _unconditional_raise(body: Sequence[ast.stmt]) -> Optional[ast.Raise]:
    """``raise``, через который выходит КАЖДЫЙ путь, либо ``None``.

    Условный ``raise`` сюда не попадает намеренно: он доказывает, что ОДИН путь
    громкий, и не опровергает, что другой молчит, — а :data:`FATES` требует от
    ``reraised`` доказательства по ВСЕМ путям.
    """
    for stmt in body:
        if isinstance(stmt, ast.Raise):
            return stmt
        if isinstance(stmt, ast.Try):
            # `raise` внутри `try` обработчика может быть пойман тут же.
            continue
    return None


def _conditional_raise(body: Sequence[ast.stmt]) -> Optional[ast.Raise]:
    """Любой ``raise`` в теле обработчика, включая условный, либо ``None``."""
    for node in _own_scope(body):
        if isinstance(node, ast.Raise):
            return node
    return None


def _recording(body: Sequence[ast.stmt],
               exc_name: Optional[str]) -> Optional[str]:
    """Чем именно обработчик оставляет след, либо ``None``.

    ДВЕ двери, и обе про ДОРОГУ ЗНАЧЕНИЯ, а не про форму оператора:

    1. имя, связанное ``except … as <имя>``, ПРОЧИТАНО в теле — пойманное
       исключение уходит наружу (вернулось строкой, положено в отчёт, собрано
       в сообщение); это господствующая форма дерева, и ровно её потеряла
       первая редакция;
    2. вызов, оставляющий след (:data:`RECORDING_METHODS` /
       :data:`RECORDING_CALLS`) — следа может не быть в значении, но он есть
       в журнале, перечне непрочитанного и прочей записи.

    Ни одна из двух не спрашивает, ЧТО написано в сообщении: «та ли это
    причина» — следующий вопрос, и мерить его нечем, кроме чтения человеком.
    """
    if exc_name is not None:
        for node in _own_scope(body):
            if isinstance(node, ast.Name) and node.id == exc_name \
                    and isinstance(node.ctx, ast.Load):
                return f"пойманное исключение `{exc_name}` уходит наружу"
    for node in _own_scope(body):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in RECORDING_METHODS:
            return f".{func.attr}()"
        if isinstance(func, ast.Name) and func.id in RECORDING_CALLS:
            return f"{func.id}()"
    return None


def _traceless(body: Sequence[ast.stmt]) -> Optional[str]:
    """Чем обработчик кончается БЕЗ следа, либо ``None``."""
    forms: List[str] = []
    for stmt in body:
        if isinstance(stmt, TRACELESS):
            forms.append(type(stmt).__name__.lower())
        elif isinstance(stmt, ast.Return):
            forms.append("return")
        elif isinstance(stmt, ast.Assign):
            forms.append("подстановка умолчания")
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            forms.append("строка-документация")
    return " · ".join(dict.fromkeys(forms)) if forms else None


def fate_of_handler(handler: ast.ExceptHandler) -> Tuple[str, str]:
    """Судьба пойманного исключения: ``(судьба, причина)``. Судьба — член FATES.

    Порядок вопросов НЕ косметический, и он тот же, что у ADR-950: сперва
    спрашивается то, что ТРЕБУЕТ доказательства и снимает чтение с предмета
    (`reraised`), потом то, что вред ОСЛАБЛЯЕТ (`renamed`), и лишь потом худшее
    (`lost`). Обратный порядок присвоил бы `lost` обработчику, который на самом
    деле поднимает исключение дальше, — то есть выдумал бы вред.
    """
    body = handler.body
    if not body:
        return "unmeasured", "тело обработчика пусто в разборе"

    unconditional = _unconditional_raise(body)
    if unconditional is not None:
        return ("reraised",
                f"обработчик безусловно поднимает исключение дальше "
                f"(строка {unconditional.lineno}) — пустота НЕ потеряна")

    conditional = _conditional_raise(body)
    if conditional is not None:
        return ("unmeasured",
                f"`raise` есть (строка {conditional.lineno}), но НЕ на каждом пути "
                "из обработчика — «пустота не потеряна» не доказано ни в одну сторону")

    record = _recording(body, handler.name)
    if record is not None:
        return ("renamed",
                f"обработчик оставляет след ({record}) — причина записана, но под "
                "ДРУГИМ именем: мисдиагноз, а не потеря")

    traceless = _traceless(body)
    if traceless is not None:
        return ("lost",
                f"обработчик не оставляет следа ({traceless}) — пустота исчезает молча")

    return ("unmeasured",
            "тело обработчика не разобрано ни в одну из трёх судеб: "
            + ", ".join(sorted({type(s).__name__ for s in body})))


def fate_tally(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Сводка судеб по строкам замера. Ключи — ровно :data:`FATES`."""
    tally = {fate: 0 for fate in FATES}
    for row in rows:
        fate = row.get("fate")
        if fate is None:
            continue
        if fate not in tally:
            raise ValueError(f"судьба вне замкнутого перечня FATES: {fate!r}")
        tally[fate] += 1
    return tally


def constant_fate(fate: str):
    """Классификатор-КРАЙНОСТЬ: объявляет одну судьбу у каждого обработчика.

    Вход крайности — функция, а не флаг, ровно затем, чтобы прибор не узнал о
    своей крайности ничего: подмена идёт в той же двери, которой пользуется
    настоящий замер (`_swap` из `test_read_kind_axis_is_redundant`).
    """
    if fate not in FATES:
        raise ValueError(f"судьба вне замкнутого перечня FATES: {fate!r}")

    def classify(handler: ast.ExceptHandler) -> Tuple[str, str]:
        return fate, f"КРАЙНОСТЬ: судьба объявлена `{fate}` входом, а не замером"

    return classify
