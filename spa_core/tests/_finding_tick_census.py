"""Перепись КРАСНЫХ печатей шага 0-офис и достижимости у каждой третьего исхода.

ЗАЧЕМ (заказ цикла #527, урок #519 в четвёртый раз).
Класс «форму контроля применили к ПОВОДУ, а не ко всему классу» закрывали три
раза подряд, и каждый раз — на том месте, где нашлось: ADR-261 (файла нет на
диске), ADR-262 (второй читатель того же вопроса), ADR-264 (предмет сменился).
Четвёртого случая ждать не стали: этот модуль спрашивает о классе ЦЕЛИКОМ —
перечисляет ВСЕ печати, требующие от читателя действия, и у каждой измеряет,
достижим ли третий исход «производитель ещё не должен был».

ЛОВУШКА НАЗВАНА ЗАКАЗОМ ЗАРАНЕЕ и обойдена здесь буквально: «строка содержит
слово находка» — НЕ население. Находка бывает и верной, а слово «находка» есть
и в комментариях. Население здесь — печати, несущие ЗНАЧОК действия
(`⚠️`/`🔴`/`❌`/`🚨`; подпись самого шага: «Красные строки выше = действовать
(карточки)»), и меряется у них не текст, а ФОРМА: от чего получен значок.

ТРИ ИСХОДА У КАЖДОЙ ПЕЧАТИ, и третий обязателен (иначе «не разобрал» стало бы
неотличимо от «в порядке» — ровно тот дефект, ради которого модуль написан):

* ``GATED`` — значок печати ВЫЧИСЛЯЕТСЯ (подставлен из `{mark}`), то есть у
  строки есть развилка и третий исход достижим;
* ``LITERAL`` — значок вбит в строку литералом: третий исход недостижим ПО
  ПОСТРОЕНИЮ, что бы производитель ни делал;
* ``UNMEASURED`` — разобрать не вышло (не распарсился файл, не нашлась
  объемлющая функция). Громко, с названной причиной.

ПОЧЕМУ ЭТО НЕ ПРЕВРАЩАЕТ ВЕСЬ НАБОР В КРАСНОЕ. `LITERAL` сам по себе НЕ
дефект: у огромной части печатей предмет не имеет производителя с тактом
вовсе (сообщения о собственных отказах шага, о содержимом отчёта, о ветках
git). Дефект — `LITERAL` там, где утверждение печати САМОРАССАСЫВАЮЩЕЕСЯ,
то есть следующий прогон производителя снял бы строку без единой правки кода.
Такое утверждение опознаётся по СТОРОЖУ печати, а не по её тексту: условие
говорит «блока/ключа нет в отчёте». Их и считает `self_clearing_sites`.
"""

from __future__ import annotations

import ast
import os

#: Значки, которыми шаг зовёт читателя действовать.
ACTION_MARKS = ("⚠️", "\U0001f534", "❌", "\U0001f6a8")

GATED = "gated"        #: значок вычисляется — третий исход достижим
LITERAL = "literal"    #: значок вбит литералом — третий исход недостижим
PLAIN = "plain"        #: значка действия нет вовсе — строка к сведению
UNMEASURED = "unmeasured"

#: Кто выдаёт значок. Проводка проверяется ФОРМОЙ вызова, а не именем
#: переменной: имя можно назвать как угодно, а вот получить значок можно только
#: у этих трёх — они и есть единственный дом развилки (`_finding_mark`).
MARK_SOURCES = ("_absent_block", "_drift_words", "_finding_mark")

#: Имя корня отчёта. Ключ, взятый НЕ отсюда, блоком отчёта не является:
#: `comp.get("measured")` — это поле ВНУТРИ блока, и следующий прогон
#: производителя его не «допишет», причина лежит в самом отчёте. Считать
#: такую строку саморассасывающейся значило бы обещать, что она уйдёт сама.
REPORT_ROOT = "data"

#: Сторож ФОРМОЙ говорит «блока нет», а имя блока разобрать не вышло (короткое
#: имя переменной, ключ из цикла). Это ТРЕТИЙ исход переписи, и он обязан быть
#: НАЗВАН: молча выпасть из населения — ровно тот дефект, ради которого модуль
#: написан («не измерено», выданное за «в порядке»).
UNRESOLVED = "<ключ не разобран>"


class Emission:
    """Одна печать со значком действия."""

    def __init__(self, line, func, artifact, kind, absent_key, text, why=""):
        self.line = line
        self.func = func
        self.artifact = artifact
        self.kind = kind
        self.absent_key = absent_key
        self.text = text
        self.why = why

    @property
    def self_clearing(self) -> bool:
        """Строка, которую снял бы следующий прогон производителя."""
        return self.absent_key is not None and self.absent_key != UNRESOLVED

    @property
    def guard_unresolved(self) -> bool:
        """Сторож формой говорит «блока нет», а какого — разобрать не вышло."""
        return self.absent_key == UNRESOLVED

    def __repr__(self):  # pragma: no cover - диагностика
        return (f"<{self.func}:{self.line} {self.kind} "
                f"key={self.absent_key} {self.text[:40]!r}>")


def _text_of(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(p.value for p in node.values
                       if isinstance(p, ast.Constant) and isinstance(p.value, str))
    return None


def _marked(node):
    txt = _text_of(node)
    return txt if txt and any(m in txt for m in ACTION_MARKS) else None


def _mark_is_computed(node, mark_names: set) -> bool:
    """Значок ПОДСТАВЛЕН из развилки, а не вбит литералом.

    Меряется ФОРМОЙ ПРОВОДКИ, а не наличием подстановки: «в строке есть
    `{...}`» зачло бы за развилку любую f-строку набора (замер #528: 255 из
    291). Считается только подстановка имени, ПОЛУЧЕННОГО у выдатчика значка
    (`MARK_SOURCES`) — переименование переменной проводку не подделает, а
    подмена источника сразу перестанет считаться.
    """
    if not isinstance(node, ast.JoinedStr):
        return False
    literal = "".join(p.value for p in node.values
                      if isinstance(p, ast.Constant) and isinstance(p.value, str))
    if any(m in literal for m in ACTION_MARKS):
        return False
    for part in node.values:
        if isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
            if part.value.id in mark_names:
                return True
    return False


def census(path: str) -> list[Emission]:
    """Перепись печатей файла. Разобрать не вышло ⇒ ОДНА запись `UNMEASURED`."""
    try:
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
    except (OSError, SyntaxError, ValueError) as exc:
        return [Emission(0, "<файл>", None, UNMEASURED, None, "",
                         why=f"{os.path.basename(path)} не прочитан/не разобран: {exc}")]

    parent: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    def ancestors(node):
        while node in parent:
            node = parent[node]
            yield node

    def enclosing_func(node):
        for anc in ancestors(node):
            if isinstance(anc, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return anc.name
        return None

    def artifact_branch(node):
        """Ветка `if/elif name == "X"`, в теле которой лежит печать."""
        cur = node
        while cur in parent:
            par = parent[cur]
            if isinstance(par, ast.If) and cur in par.body:
                test = par.test
                if (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                        and test.left.id == "name" and len(test.comparators) == 1):
                    val = _text_of(test.comparators[0])
                    if val:
                        return val
            cur = par
        return None

    # `NAME = data.get("K")` / `NAME = data["K"]` — иначе сторож вида
    # `not isinstance(comp, dict)` не сказал бы, О КАКОМ блоке речь.
    #
    # Словарь ПОФУНКЦИОННЫЙ намеренно: имена `d`, `st`, `lat` живут в модуле
    # десятками, и общий на файл словарь отдавал бы последнее по тексту
    # связывание ЧУЖОЙ функции — то есть уверенно неверное имя блока. Ошибиться
    # именем здесь хуже, чем не разобрать: не разобранное уходит в третий исход
    # и остаётся видимым, а неверное имя молча зачтётся за разбор.
    bindings_by_func: dict = {}
    for fnode in ast.walk(tree):
        if not isinstance(fnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        local: dict[str, str] = {}
        for node in ast.walk(fnode):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                continue
            val = node.value
            key = container = None
            if (isinstance(val, ast.Call) and isinstance(val.func, ast.Attribute)
                    and val.func.attr == "get" and val.args):
                key = _text_of(val.args[0])
                container = getattr(val.func.value, "id", None)
            elif isinstance(val, ast.Subscript):
                key = _text_of(val.slice)
                container = getattr(val.value, "id", None)
            if container != REPORT_ROOT:
                continue
            name = node.targets[0].id
            key = key or UNRESOLVED
            # Имя, связанное ДВАЖДЫ с разными блоками внутри одной функции
            # (`_summarize_json` — 1700 строк, и `d`/`st`/`lat` живут в ней
            # повторно), разобранным НЕ считается: последнее связывание по
            # тексту дало бы уверенно неверное имя блока. Громкое «не
            # разобрано» видно, тихая подмена — нет.
            if name in local and local[name] != key:
                local[name] = UNRESOLVED
            else:
                local[name] = key
        bindings_by_func[fnode.name] = local

    def key_of(node, scope):
        """Имя блока ОТЧЁТА (не поля внутри блока), `UNRESOLVED` либо None."""
        bindings = bindings_by_func.get(scope, {})
        if isinstance(node, ast.Name):
            return bindings.get(node.id)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and node.args
                and getattr(node.func.value, "id", None) == REPORT_ROOT):
            return _text_of(node.args[0]) or UNRESOLVED
        if (isinstance(node, ast.Subscript)
                and getattr(node.value, "id", None) == REPORT_ROOT):
            return _text_of(node.slice) or UNRESOLVED
        return None

    def absence_key(test, sense, scope):
        """Условие «блока нет в отчёте» ⇒ имя блока, иначе None."""
        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            op, right = test.ops[0], test.comparators[0]
            if (isinstance(op, ast.Is) and isinstance(right, ast.Constant)
                    and right.value is None and sense == "then"):
                return key_of(test.left, scope)
            if (isinstance(op, ast.NotIn) and sense == "then"
                    and getattr(right, "id", None) == REPORT_ROOT):
                return _text_of(test.left)
            if (isinstance(op, ast.In) and sense == "else"
                    and getattr(right, "id", None) == REPORT_ROOT):
                return _text_of(test.left)
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and sense == "then":
            inner = test.operand
            if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
                    and inner.func.id == "isinstance" and inner.args):
                return key_of(inner.args[0], scope)
            return key_of(inner, scope)
        if (isinstance(test, ast.Call) and isinstance(test.func, ast.Name)
                and test.func.id == "isinstance" and sense == "else" and test.args):
            return key_of(test.args[0], scope)
        if isinstance(test, ast.BoolOp) and sense == "then":
            # `not isinstance(a, dict) or not isinstance(b, list)` — блок всё
            # равно отсутствует; берём первый названный.
            for value in test.values:
                key = absence_key(value, "then", scope)
                if key:
                    return key
        return None

    def guarding_absence(node, scope):
        cur = node
        while cur in parent:
            par = parent[cur]
            if isinstance(par, ast.If):
                sense = "then" if cur in par.body else ("else" if cur in par.orelse else None)
                if sense:
                    key = absence_key(par.test, sense, scope)
                    if key:
                        return key
            cur = par
        return None

    # Имена, получившие значок у выдатчика: `mark, why = _absent_block(...)`
    # либо `mark = _finding_mark(...)`. Собирается по ФОРМЕ вызова.
    mark_names: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        val = node.value
        if not (isinstance(val, ast.Call) and isinstance(val.func, ast.Name)
                and val.func.id in MARK_SOURCES):
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name):
            mark_names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)) and target.elts:
            first = target.elts[0]
            if isinstance(first, ast.Name):
                mark_names.add(first.id)

    out: list[Emission] = []
    seen: set[int] = set()
    for node in ast.walk(tree):
        txt = _text_of(node)
        if txt is None or node.lineno in seen:
            continue
        # только то, что реально уходит в вывод
        near = list(ancestors(node))[:6]
        emitted = any(
            isinstance(a, ast.Call)
            and ((isinstance(a.func, ast.Attribute) and a.func.attr in ("append", "extend"))
                 or (isinstance(a.func, ast.Name) and a.func.id == "print"))
            for a in near)
        if not emitted:
            continue
        scope = enclosing_func(node)
        absent = guarding_absence(node, scope)
        has_mark = _marked(node) is not None
        computed = _mark_is_computed(node, mark_names)
        # Строка без значка и без сторожа отсутствия к делу не относится.
        if not has_mark and not computed and absent is None:
            continue
        seen.add(node.lineno)
        func = scope
        if func is None:
            out.append(Emission(node.lineno, "<модуль>", None, UNMEASURED, None,
                                " ".join(txt.split())[:90],
                                why="печать вне функции — сторожа не разобрать"))
            continue
        if has_mark:
            kind = LITERAL
        elif computed:
            kind = GATED
        else:
            kind = PLAIN
        out.append(Emission(node.lineno, func, artifact_branch(node), kind,
                            absent, " ".join(txt.split())[:90]))
    out.sort(key=lambda e: e.line)
    return out


def action_sites(path: str) -> list[Emission]:
    """Печати, зовущие читателя действовать (значок вбит либо вычисляется)."""
    return [e for e in census(path) if e.kind in (LITERAL, GATED, UNMEASURED)]


def self_clearing_sites(path: str) -> list[Emission]:
    """Печати, чьё утверждение снял бы следующий прогон производителя.

    Два ВХОДА в население, и второй закрывает дыру, которую первый оставляет
    молча: помимо разобранного сторожа «блока нет» сюда попадает всё, что
    ПРОВЕДЕНО через выдатчик значка (`GATED`). Автор, позвавший `_absent_block`,
    тем самым объявил строку вопросом о блоке — даже если сам сторож стои́т на
    вложенном ключе (`delivery.debt`) и переписью не разбирается. Без этого
    входа проведённая строка выпадала бы из населения ТИХО, а тишина здесь
    неотличима от «в порядке».
    """
    return [e for e in census(path)
            if e.self_clearing or e.guard_unresolved
            or e.kind in (GATED, UNMEASURED)]
