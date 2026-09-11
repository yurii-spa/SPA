"""Перепись ЧТЕНИЙ шага 0-офис: что ветка отчёта берёт у артефакта и что из
этого объявлено в `_READ_SCHEMA` (заказ CIO #563).

## Вопрос

`scripts/consume_office_reports.py` печатает владельцу и оркестратору выжимку
каждого офисного артефакта. Строка «⚠️ СХЕМА РАЗОШЛАСЬ» — единственная тревога
о том, что производитель перестал писать поле, и срабатывает она **ровно по
списку путей в `_READ_SCHEMA`**. Значит у любого чтения ровно два состояния:
объявлено (за него тревожат) и не объявлено (пропади поле завтра — ветка
напечатает `None`, и не покраснеет ничто).

Заказ #563 спрашивает НАСЕЛЕНИЕ второго состояния.

## Ловушка заказа, названная им заранее

«Поле есть в артефакте» и «поле объявлено в схеме» — разные множества. Мерить
надо ОБЪЯВЛЕННОЕ ОТНОСИТЕЛЬНО ЧИТАЕМОГО, а не наоборот: населением класса
является то, что ветка БЕРЁТ, но схема не стережёт. Живой артефакт в этом
замере не участвует вовсе — вопрос о КОДЕ, и ответ на него не должен зависеть
от того, что сегодня лежит в `data/`.

## Три исхода, а не два

У чтения бывает и третий исход: **ветка отдаёт под-словарь чужой функции**
(`summary_line(ch)`), и что именно та прочтёт — перепись ЭТОГО файла не знает
ни при каком разборе. Такое чтение не засчитывается ни в «объявлено», ни в
«не объявлено»: оно `handed_off` с названной причиной. Молчаливое сворачивание
третьего исхода во второй изготовило бы находку, а в первый — усыпило бы.

## Границы замера, названные вслух

* **Элементы списков не отслеживаются.** `for a in data.get("analysts")` —
  чтение `analysts` записывается, поля `a` — нет: `_READ_SCHEMA` объявляет пути
  вложенных СЛОВАРЕЙ (`history.by_key`), а не полей элементов, и считать их
  населением значило бы мерить схему по правилу, которого у неё нет.
* **Мера статическая.** Выражение, которое не разбирается до пути
  (`data.get(var)`), уходит в `unresolvable`, а не признаётся отсутствующим.
* Ветка `else` (generic) предметом не является: она печатает одно слово по
  общему правилу и никакого артефакт-специфичного поля не читает.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

#: Вызовы, которые получают под-словарь и НЕ спускаются в его поля: передача
#: сюда не есть чтение неизвестных полей, и объявлять её нечем.
_NON_DESCENDING = frozenset({
    "len", "str", "int", "float", "bool", "sorted", "list", "set", "dict",
    "any", "all", "isinstance", "repr", "max", "min", "sum", "enumerate",
    "zip", "reversed", "tuple", "abs", "round", "type", "print",
    # свои читатели того же файла: они берут путь вторым аргументом, и этот
    # путь уже записан разбором как обычное чтение.
    "_num", "_has_path", "_absent_block",
})

#: Методы, чей вызов на связанном пути не уводит чтение в чужой модуль.
_METHODS = frozenset({
    "get", "append", "extend", "items", "keys", "values", "join", "format",
    "startswith", "strip", "split", "replace", "lower", "upper", "setdefault",
    "pop", "sort", "update", "rstrip", "lstrip", "title", "endswith", "count",
    "index", "encode", "decode", "isoformat", "copy", "total_seconds",
    "astimezone", "strftime", "add", "discard", "remove", "insert",
})

_OFFICE_REL = "scripts/consume_office_reports.py"


def office_script_path(root: Path | str | None = None) -> Path:
    """Путь к разбираемому файлу. Корень — дерево, в котором лежит этот тест."""
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    return base / _OFFICE_REL


def load_office_module(path: Path):
    """Загрузить модуль отчёта, чтобы взять `_READ_SCHEMA` из КОДА, а не копией.

    Копия схемы в тесте была бы вторым местом правды: разойдясь с модулем, она
    отвечала бы на вопрос о себе.
    """
    spec = importlib.util.spec_from_file_location("_office_under_census", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"не загрузить модуль отчёта из {path} — перепись "
                          "отвечать не о чем")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _artifact_names(test: ast.expr) -> list[str] | None:
    """Имена артефактов, которые выбирает условие ветки, либо None."""
    if not (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
            and test.left.id == "name" and len(test.ops) == 1):
        return None
    op, right = test.ops[0], test.comparators[0]
    if isinstance(op, ast.Eq) and isinstance(right, ast.Constant) \
            and isinstance(right.value, str):
        return [right.value]
    if isinstance(op, ast.In) and isinstance(right, (ast.Tuple, ast.List, ast.Set)):
        values = [e.value for e in right.elts
                  if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if len(values) == len(right.elts):
            return values
    return None


def branches(tree: ast.Module) -> list[tuple[list[str], list[ast.stmt], int]]:
    """Цепочка `if/elif name == "<артефакт>"` внутри `_summarize_json`."""
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_summarize_json"), None)
    if fn is None:
        raise LookupError("в разбираемом файле нет функции `_summarize_json` — "
                          "перепись отвечать не о чем")
    found: list[tuple[list[str], list[ast.stmt], int]] = []

    def walk(stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.If):
                names = _artifact_names(stmt.test)
                if names is not None:
                    found.append((names, stmt.body, stmt.test.lineno))
                    if stmt.orelse:
                        walk(stmt.orelse)
                    return

    walk(fn.body)
    return found


class _BranchReads:
    """Пути, которые ОДНА ветка берёт у своего артефакта.

    Привязка ищется последовательно по телу ветки: `c = data.get("counts")`
    связывает имя `c` с путём `counts`, и всякое `c.get("total")` дальше
    читается как `counts.total`. Имя, которому присвоили неразбираемое
    выражение, привязку ТЕРЯЕТ — иначе разбор продолжал бы судить о пути,
    которого у значения уже нет.
    """

    def __init__(self) -> None:
        self.binds: dict[str, str] = {"data": ""}
        self.reads: dict[str, int] = {}
        self.handed_off: dict[tuple[str, str], int] = {}
        self.unresolvable: dict[str, int] = {}

    # ── разрешение выражения в путь ────────────────────────────────────────
    def path_of(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return self.binds.get(node.id)
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            # `data.get("k") or {}` — путь задаёт ЛЕВОЕ плечо, правое умолчание
            return self.path_of(node.values[0])
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            base = self.path_of(node.value)
            return None if base is None else _join(base, node.slice.value)
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr == "get" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                base = self.path_of(func.value)
                return None if base is None else _join(base, node.args[0].value)
            if (isinstance(func, ast.Name) and func.id in ("_num", "_has_path")
                    and len(node.args) == 2 and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)):
                base = self.path_of(node.args[0])
                return None if base is None else _join(base, node.args[1].value)
        return None

    # ── сбор чтений ────────────────────────────────────────────────────────
    def visit_expr(self, node: ast.expr) -> None:
        path = self.path_of(node)
        if path:
            self.reads.setdefault(path, node.lineno)
        if isinstance(node, ast.Call):
            self._note_handoff(node)
            self._note_dynamic_key(node)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self.visit_expr(child)

    def _callee_name(self, node: ast.Call) -> str:
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return "?"

    def _note_handoff(self, node: ast.Call) -> None:
        """Под-словарь ушёл в чужую функцию — что она прочтёт, отсюда не видно."""
        callee = self._callee_name(node)
        if callee in _NON_DESCENDING or callee in _METHODS:
            return
        for arg in node.args:
            path = self.path_of(arg)
            if path:
                self.handed_off.setdefault((callee, path), node.lineno)

    def _note_dynamic_key(self, node: ast.Call) -> None:
        """`x.get(<не литерал>)` — ключ вычисляется, путь статике не даётся."""
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr == "get" and node.args
                and not (isinstance(node.args[0], ast.Constant)
                         and isinstance(node.args[0].value, str))):
            base = self.path_of(func.value)
            if base is not None:
                self.unresolvable.setdefault(
                    f"{base or 'data'}.<ключ вычисляется>", node.lineno)

    def run(self, stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                    and isinstance(stmt.targets[0], ast.Name):
                self.visit_expr(stmt.value)
                target = stmt.targets[0].id
                path = self.path_of(stmt.value)
                if path is None:
                    self.binds.pop(target, None)
                else:
                    self.binds[target] = path
            elif isinstance(stmt, ast.For):
                self.visit_expr(stmt.iter)
                if isinstance(stmt.target, ast.Name):
                    # элемент списка: его поля предметом схемы не являются
                    self.binds.pop(stmt.target.id, None)
                self.run(stmt.body)
                self.run(stmt.orelse)
            elif isinstance(stmt, (ast.If, ast.While)):
                self.visit_expr(stmt.test)
                self.run(stmt.body)
                self.run(stmt.orelse)
            elif isinstance(stmt, ast.Try):
                self.run(stmt.body)
                for handler in stmt.handlers:
                    self.run(handler.body)
                self.run(stmt.orelse)
                self.run(stmt.finalbody)
            elif isinstance(stmt, ast.With):
                for item in stmt.items:
                    self.visit_expr(item.context_expr)
                self.run(stmt.body)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.run(stmt.body)
            else:
                for child in ast.iter_child_nodes(stmt):
                    if isinstance(child, ast.expr):
                        self.visit_expr(child)


def _covered(path: str, declared: frozenset[str]) -> bool:
    """Стережёт ли объявленное это чтение.

    Путь покрыт, если объявлен сам ИЛИ является началом объявленного:
    проверка `counts.total` требует существования `counts`, поэтому
    промежуточное чтение контейнера тревогой уже обеспечено.
    """
    if path in declared:
        return True
    prefix = path + "."
    return any(d.startswith(prefix) for d in declared)


def census(*, root: Path | str | None = None) -> dict:
    """Перепись живого файла отчёта: схема берётся из КОДА, а не копией."""
    path = office_script_path(root)
    module = load_office_module(path)
    return census_source(path.read_text(encoding="utf-8"), module._READ_SCHEMA)


def census_source(source: str, read_schema: dict) -> dict:
    """Перепись по ИСХОДНИКУ и схеме. Возвращает классы и третий исход раздельно.

    Отдельной функцией намеренно: положительный контроль обязан уметь показать
    перепись КРАСНОЙ и ЗЕЛЁНОЙ, не трогая живой файл отчёта. Проверка, никогда
    не видевшая настоящей поломки, — украшение.

    * `no_entry` — у ветки НЕТ записи в `_READ_SCHEMA` вовсе: не стережётся ни
      одно её чтение, включая верхние блоки.
    * `undeclared_top` — верхний ключ читается, но не объявлен: пропади блок
      целиком — ветка промолчит.
    * `undeclared_nested` — то же на глубине (поле внутри объявленного блока).
    * `handed_off` / `unresolvable` — «не измерено» с названной причиной.
    """
    schema = {name: frozenset(fields) for name, fields in read_schema.items()}
    tree = ast.parse(source)

    no_entry: dict[str, list[str]] = {}
    undeclared_top: dict[str, list[str]] = {}
    undeclared_nested: dict[str, list[str]] = {}
    handed_off: list[dict] = []
    unresolvable: list[dict] = []
    branch_count = 0

    for names, body, _lineno in branches(tree):
        reads = _BranchReads()
        reads.run(body)
        branch_count += 1
        for (callee, where), line in sorted(reads.handed_off.items()):
            handed_off.append({"artifact": names[0], "callee": callee,
                               "path": where, "line": line})
        for where, line in sorted(reads.unresolvable.items()):
            unresolvable.append({"artifact": names[0], "path": where, "line": line})
        for name in names:
            if name not in schema:
                no_entry[name] = sorted(p for p in reads.reads if "." not in p)
                continue
            declared = schema[name]
            missing = [p for p in reads.reads if not _covered(p, declared)]
            top = sorted(p for p in missing if "." not in p)
            nested = sorted(p for p in missing if "." in p)
            if top:
                undeclared_top[name] = top
            if nested:
                undeclared_nested[name] = nested

    return {
        "branches": branch_count,
        "schema_entries": len(schema),
        "no_entry": no_entry,
        "undeclared_top": undeclared_top,
        "undeclared_nested": undeclared_nested,
        "handed_off": handed_off,
        "unresolvable": unresolvable,
        "population_no_entry": len(no_entry),
        "population_top": sum(len(v) for v in undeclared_top.values()),
        "population_nested": sum(len(v) for v in undeclared_nested.values()),
    }
