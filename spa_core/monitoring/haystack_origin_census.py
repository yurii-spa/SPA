"""Откуда пришло содержимое стога: НАСТОЯЩИЙ сосед или байты, написанные тестом.

Заказ #568 (стоячая карточка CIO `inbox-task-portfolio-cio-dynamic-capital-alloc`)
поставлен дословно так:

> Из тех 91 сайта за границей замера ADR-338 — сколько читают файл, лежащий
> **В РЕПОЗИТОРИИ** (настоящий сосед, просто названный фикстурой или аргументом),
> а сколько читают файл, который тест **САМ** только что написал во временный
> каталог? Первым результатом обязано быть РАЗДЕЛЕНИЕ этих двух, потому что у них
> противоположная цена: у первых обрыв — тот же дефект, что закрыт ADR-338; у
> вторых предмета нет вовсе, тест судит о своих же байтах.
>
> **Ловушка названа заранее.** Соблазн — решить это по ИМЕНИ переменной (``tmp``,
> ``tmpdir``, ``TemporaryDirectory``) и объявить долю. Это признак, а не замер, и
> он ошибается в обе стороны: фикстура умеет копировать НАСТОЯЩИЙ файл
> репозитория во временный каталог (тогда предмет есть), а «честное» имя
> ``repo_src`` умеет указывать на сгенерированный текст. Разделять надо
> ПРОИСХОЖДЕНИЕМ ЗНАЧЕНИЯ: дошло ли содержимое стога до чтения из пути, который
> лежит под корнем дерева. Не удалось проследить ⇒ ТРЕТИЙ исход с названной
> причиной, НЕ «временный». И отдельно: «путь не свернулся» НЕ равно «сосед не в
> репозитории» — сказать это надо ПРЕЖДЕ, чем называть долю.

## Население берётся у ADR-338, а не строится заново

Предмет заказа — РОВНО те сайты, которые прибор #568 отложил с причиной «путь
статикой не свернулся». Построить их своим обходом значило бы ответить на
похожий, но ДРУГОЙ вопрос: любое расхождение обходов сделало бы долю
несопоставимой с опубликованным числом 91. Поэтому население импортируется
дословно у `substring_structure_assertions.forward_sites` и отбирается по той же
строке-причине; расхождение с опубликованным числом — находка, а не допуск
(`population_source_disagrees`).

## «Путь не свернулся» — утверждение о ПРИБОРЕ, а не о соседе

Граница #568 проходит по тому, что УМЕЛ свернуть его сворачиватель: `Path(...)`,
`/`, `.parent`, `.parents[N]`, `Path(__file__)`. Всё остальное — `open()` +
`os.path.join`, `модуль.__file__.replace(".pyc", ".py")`, константа соседнего
модуля, фикстура, параметр — уехало в остаток. Из этого НЕ следует, что читаемого
файла нет в репозитории: следует только, что #568 его не назвал. Разница между
этими двумя утверждениями и есть первый результат замера, и он печатается ПЕРВОЙ
строкой — до любой доли.

## Разделение идёт ПРОИСХОЖДЕНИЕМ ЗНАЧЕНИЯ, и это два независимых вопроса

``написан ли он тестом?``  Есть ли в коде самого теста ЗАПИСЬ по тому же пути,
                           каким идёт чтение. Вопрос структурный: путь чтения и
                           путь записи сводятся к одному символическому терму
                           (с подстановкой параметров при заходе в хелпер), и
                           сравниваются термы, а не тексты.
``лежит ли он под корнем?`` Сворачивается ли путь до конкретного файла,
                           существующего под корнем дерева.

Ни один из двух не спрашивает, как ЗОВУТ переменную. Имя в этом приборе не
участвует нигде — кроме одного места, где оно измеряется КАК ЛОВУШКА (см. ниже).

### Четыре исхода

``repo_neighbour``  чтение идёт из файла, лежащего под корнем дерева, и тест по
                    этому пути ничего не писал. Предмет заказа ЕСТЬ: цена обрыва
                    здесь ровно та, что закрыта ADR-338.
``repo_copy``       тест САМ написал файл, но содержимое записи происходит от
                    ЧТЕНИЯ файла под корнем дерева (`shutil.copy`,
                    `dst.write_text(src.read_text())`). Предмет тоже ЕСТЬ — это
                    буквально первая половина названной в заказе ловушки, и она
                    вынесена отдельным исходом, а не слита с `self_written`.
``self_written``    тест написал файл содержимым, которое не происходит ни от
                    какого чтения под корнем: литерал, f-строка, результат зова
                    проверяемого кода. Предмета заказа нет — утверждение судит о
                    байтах, которые тест сам и произвёл.
``unmeasured``      проследить не удалось, причина названа поимённо. Не
                    складывается ни с одной из трёх долей и НИКОГДА не читается
                    как «временный»: именно эта подмена и есть дефект, против
                    которого написан заказ.

## Ловушка заказа ИЗМЕРЯЕТСЯ, а не оговаривается

Признак-по-имени («в выражении пути встречается `tmp`/`tmpdir`/`TemporaryDirectory`»)
вычисляется ОТДЕЛЬНО и сверяется с замером. Каждое расхождение печатается
поимённо и в обе стороны:

``sign_says_tmp_but_measure_says_repo``   имя кричит «временный», а содержимое
                                          пришло из репозитория;
``sign_says_repo_but_measure_says_self``  в имени нет ни следа временного
                                          каталога, а файл написан самим тестом.

Ноль расхождений — это тоже результат, и он говорит лишь то, что на ЭТОМ
населении признак совпал с замером; правом быть ответом признак от этого не
становится.

## Чего прибор НЕ утверждает

Он не говорит, ОБРЫВАЕТСЯ ли литерал у сайтов, попавших в `repo_neighbour` /
`repo_copy`, — это вопрос ADR-338, у него свой замер возмущением, и смешивать их
значило бы выдать разделение за приговор. Он не говорит и того, верно ли
утверждение по существу.

ADVISORY: прибор только ЧИТАЕТ исходники набора. Ни один тест не правится, не
скипается и не сужается (инв. #16); `POLLED_ADAPTERS`, пины, писатель журнала
решений, `TriggerParams`, пороги RiskPolicy v1.0, потолки концентрации, стоп-кран
и живой трек НЕ тронуты.
"""

from __future__ import annotations

import ast
import os
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.monitoring.substring_structure_assertions import (
    _scope_of,
    forward_sites,
    parent_map,
)

OUTPUT_FILENAME = "haystack_origin_census.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Дословная причина, которой ADR-338 отложил сайт за свою границу. Население
#: этого прибора — РОВНО те сайты; строка сверяется, а не пересказывается.
BOUNDARY_REASON = "ПУТЬ которого статикой не свернулся"

#: Опубликованное ADR-338 число сайтов за границей. Расхождение — находка.
PUBLISHED_BOUNDARY = 91

#: Зовы, возвращающие СОДЕРЖИМОЕ файла.
_READ_ATTRS = ("read_text", "read", "read_bytes")

#: Зовы записи «получатель.метод(содержимое)».
_WRITE_ATTRS = ("write_text", "write_bytes")

#: Признак-ловушка. Участвует ТОЛЬКО в сверке признака с замером и ни в одном
#: вердикте. Держится тестом `test_name_sign_never_decides_a_verdict`.
_TMP_NAME_SIGN = re.compile(
    r"\btmp\w*|\btemp\w*|TemporaryDirectory|mkdtemp|mkstemp", re.IGNORECASE)


# ─────────────────────────── общее ───────────────────────────

def _rel(root: Path, p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(p)


def _parse(path: Path) -> Optional[ast.Module]:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        with warnings.catch_warnings():
            # Битая escape-последовательность в ЧУЖОЙ строке — находка про
            # соседа, а не про прибор; засорять ею вывод замера нельзя.
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(src)
    except (OSError, SyntaxError, ValueError):
        return None


# ────────────── символический терм пути ──────────────
#
# Терм — вложенный кортеж с тегом в нулевой позиции. Сравнение термов
# СТРУКТУРНОЕ: именно оно отвечает на вопрос «чтение и запись идут по одному
# пути?», и текстов оно не сравнивает вовсе.

def t_const(s: str): return ("const", s)
def t_anchor(p: Path): return ("anchor", str(p))
def t_join(a, b): return ("join", a, b)
def t_parent(a): return ("parent", a)
def t_parents(a, n: int): return ("parents", a, n)
def t_opaque(kind: str, tag: str): return ("opaque", kind, tag)
def t_unknown(reason: str): return ("unknown", reason)


def term_unknown_reason(term) -> Optional[str]:
    """Первая названная причина непрослеживаемости внутри терма (или None)."""
    if not isinstance(term, tuple):
        return None
    if term[0] == "unknown":
        return term[1]
    for part in term[1:]:
        got = term_unknown_reason(part)
        if got is not None:
            return got
    return None


def term_has_opaque(term) -> bool:
    if not isinstance(term, tuple):
        return False
    if term[0] == "opaque":
        return True
    return any(term_has_opaque(p) for p in term[1:])


def concretize(term) -> Optional[Path]:
    """Терм → конкретный путь, если в нём нет ни одного непрозрачного якоря."""
    if not isinstance(term, tuple):
        return None
    tag = term[0]
    if tag == "anchor":
        return Path(term[1])
    if tag == "const":
        p = Path(term[1])
        return p if p.is_absolute() else None
    if tag == "join":
        left = concretize(term[1])
        if left is None:
            return None
        right = term[2]
        if isinstance(right, tuple) and right[0] == "const":
            return left / right[1]
        inner = concretize(right)
        return (left / inner) if inner is not None else None
    if tag == "parent":
        inner = concretize(term[1])
        return inner.parent if inner is not None else None
    if tag == "parents":
        inner = concretize(term[1])
        if inner is None:
            return None
        parents = inner.resolve().parents
        return parents[term[2]] if term[2] < len(parents) else None
    return None


# ──────────────────── разрешение выражений ────────────────────

class Frame:
    """Кадр разрешения: функция + подстановка её параметров.

    Подстановка — то, что делает разделение ИНТЕРПРОЦЕДУРНЫМ: хелпер
    ``_card(tmp_path, name)`` пишет в ``p = tmp_path / name`` и возвращает ``p``,
    а тест читает возвращённое. Без подстановки терм чтения и терм записи
    сравнивались бы как термы ДВУХ РАЗНЫХ функций и не совпали бы никогда —
    измеримое «написан тестом» выродилось бы в «не измерено» поголовно.
    """

    def __init__(self, func: Optional[ast.AST], subst: Dict[str, tuple]):
        self.func = func
        self.subst = subst


class Tracer:
    """Разрешение выражений-путей в пределах ОДНОГО файла набора."""

    MAX_DEPTH = 12

    def __init__(self, tree: ast.Module, path: Path, root: Path):
        self.tree = tree
        self.path = path
        self.root = root
        self.parents = parent_map(tree)
        self.module_funcs: Dict[str, ast.AST] = {}
        self.fixtures: Dict[str, ast.AST] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.module_funcs.setdefault(node.name, node)
                if self._is_fixture(node):
                    self.fixtures.setdefault(node.name, node)
        self.module_files = self._import_module_files()
        self._neighbour_consts: Dict[Tuple[str, str], Optional[tuple]] = {}
        #: кадры, пройденные при разрешении последнего выражения — по ним потом
        #: ищется ЗАПИСЬ.
        self.visited: List[Frame] = []
        #: ТЕКСТ цепочки связывания пути. Нужен РОВНО для одного: показать, что
        #: сказал бы признак-по-имени. В вердиктах не участвует — и это
        #: закреплено тестом, а не обещанием.
        self.trace_src: List[str] = []

    # ── импорты и константы соседа ──

    @staticmethod
    def _is_fixture(node: ast.AST) -> bool:
        for dec in getattr(node, "decorator_list", []) or []:
            tgt = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(tgt, ast.Attribute) and tgt.attr == "fixture":
                return True
            if isinstance(tgt, ast.Name) and tgt.id == "fixture":
                return True
        return False

    def _import_module_files(self) -> Dict[str, Path]:
        """Локальное имя → файл модуля. Разрешение АРИФМЕТИКОЙ ПУТИ, не импортом:
        прибор обязан читать чужой набор, ничего в нём не исполняя."""
        out: Dict[str, Path] = {}

        def resolve(dotted: str) -> Optional[Path]:
            parts = dotted.split(".")
            cand = self.root.joinpath(*parts)
            if cand.with_suffix(".py").is_file():
                return cand.with_suffix(".py")
            if (cand / "__init__.py").is_file():
                return cand / "__init__.py"
            # Набор кладёт `scripts/` в `sys.path` и импортирует оттуда ПЛОСКИМ
            # именем (`import check_tracker_drift as drift`). Пакетная арифметика
            # такой импорт не разрешает, и без этой ветки шесть сайтов уходили в
            # «не измерено» по причине, которая есть свойство ПРИБОРА, а не
            # предмета.
            for base in ("scripts", "."):
                flat = self.root / base / (parts[0] + ".py")
                if len(parts) == 1 and flat.is_file():
                    return flat
            return None

        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    got = resolve(alias.name)
                    if got is not None:
                        out[alias.asname or alias.name.split(".")[0]] = got
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for alias in node.names:
                    got = resolve(f"{node.module}.{alias.name}")
                    if got is not None:
                        out[alias.asname or alias.name] = got
        return out

    def _module_file(self, dotted: str) -> Optional[Path]:
        cand = self.root.joinpath(*dotted.split("."))
        if cand.with_suffix(".py").is_file():
            return cand.with_suffix(".py")
        if (cand / "__init__.py").is_file():
            return cand / "__init__.py"
        return None

    def _neighbour_const(self, mod_name: str, attr: str) -> Optional[tuple]:
        """`A.REPO_ROOT` — константа-путь в ИМПОРТИРОВАННОМ модуле набора."""
        key = (mod_name, attr)
        if key in self._neighbour_consts:
            return self._neighbour_consts[key]
        self._neighbour_consts[key] = None
        mod_file = self.module_files.get(mod_name)
        if mod_file is None:
            return None
        tree = _parse(mod_file)
        if tree is None:
            return None
        sub = Tracer(tree, mod_file, self.root)
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == attr:
                    term = sub.resolve(node.value, Frame(None, {}), 0)
                    if term_unknown_reason(term) is None:
                        self._neighbour_consts[key] = term
                        return term
        return None

    # ── связывание имён ──

    def _class_of(self, node: ast.AST) -> Optional[ast.ClassDef]:
        cur: Optional[ast.AST] = node
        while cur is not None:
            if isinstance(cur, ast.ClassDef):
                return cur
            cur = self.parents.get(id(cur))
        return None

    def _assign_for(self, name: str, frame: Frame) -> Optional[ast.AST]:
        """Последнее присваивание имени в кадре (функция, иначе модуль)."""
        best, best_line = None, -1
        scopes: List[Optional[ast.AST]] = [frame.func, self.tree]
        for scope in scopes:
            if scope is None:
                continue
            for node in ast.walk(scope):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and node is not scope and scope is self.tree:
                    continue
                value = tgts = None
                if isinstance(node, ast.Assign):
                    tgts, value = node.targets, node.value
                elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value:
                    tgts, value = [node.target], node.value
                if not tgts:
                    continue
                for tgt in tgts:
                    hit = self._unpack_hit(tgt, name, value)
                    if hit is None:
                        continue
                    if _scope_of(node, self.parents) is not scope and scope is not self.tree:
                        continue
                    line = getattr(node, "lineno", 0)
                    if line > best_line:
                        best, best_line = hit, line
            if best is not None:
                return best
        return None

    @staticmethod
    def _unpack_hit(tgt: ast.AST, name: str, value: Optional[ast.AST]):
        """Выражение, давшее `name` этим присваиванием (с учётом распаковки)."""
        if value is None:
            return None
        if isinstance(tgt, ast.Name) and tgt.id == name:
            return value
        if isinstance(tgt, (ast.Tuple, ast.List)):
            for idx, el in enumerate(tgt.elts):
                if isinstance(el, ast.Name) and el.id == name:
                    return ("__index__", value, idx)
        return None

    def _with_binding(self, name: str, frame: Frame) -> Optional[ast.AST]:
        """`with open(P) as fh:` → выражение `open(P)` для имени `fh`."""
        scope = frame.func if frame.func is not None else self.tree
        for node in ast.walk(scope):
            if not isinstance(node, (ast.With, ast.AsyncWith)):
                continue
            for item in node.items:
                var = item.optional_vars
                if isinstance(var, ast.Name) and var.id == name:
                    return item.context_expr
        return None

    def _self_attr(self, attr: str, frame: Frame) -> Optional[ast.AST]:
        """`self.tmp` — присваивание в классе (`setUp`) ЛИБО атрибут класса.

        Второе не мелочь: `ROOT = os.path.dirname(...)` в теле класса — самая
        частая форма якоря репозитория в наборе, и без неё сайт, читающий
        настоящего соседа, выглядел бы неизмеримым.
        """
        if frame.func is None:
            return None
        klass = self._class_of(frame.func)
        if klass is None:
            return None
        for node in ast.walk(klass):
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Attribute) and tgt.attr == attr \
                        and isinstance(tgt.value, ast.Name) and tgt.value.id == "self":
                    return node.value
        for node in klass.body:
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == attr:
                        return node.value
        return None

    def _self_method(self, name: str, frame: Frame) -> Optional[ast.AST]:
        if frame.func is None:
            return None
        klass = self._class_of(frame.func)
        if klass is None:
            return None
        for node in klass.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == name and node is not frame.func:
                return node
        return None

    # ── собственно разрешение ──

    def resolve(self, node: Optional[ast.AST], frame: Frame, depth: int):
        if node is None:
            return t_unknown("выражения нет")
        if depth > self.MAX_DEPTH:
            return t_unknown("цепочка связывания глубже предела разбора")

        if isinstance(node, tuple) and node and node[0] == "__index__":
            return self._resolve_index(node[1], node[2], frame, depth)

        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                return t_const(node.value)
            return t_unknown(f"константа не строка ({type(node.value).__name__})")

        if isinstance(node, ast.JoinedStr):
            return t_unknown("путь собран f-строкой — части статикой не сведены")

        if isinstance(node, ast.Name):
            return self._resolve_name(node, frame, depth)

        if isinstance(node, ast.Attribute):
            return self._resolve_attribute(node, frame, depth)

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return t_join(self.resolve(node.left, frame, depth + 1),
                          self.resolve(node.right, frame, depth + 1))

        if isinstance(node, ast.Subscript):
            return self._resolve_subscript(node, frame, depth)

        if isinstance(node, ast.Call):
            return self._resolve_call(node, frame, depth)

        return t_unknown(f"форма выражения не разбирается ({type(node).__name__})")

    def _note(self, node) -> None:
        """Запомнить ТЕКСТ звена цепочки — материал для признака-по-имени."""
        if isinstance(node, str):
            self.trace_src.append(node)
            return
        try:
            self.trace_src.append(ast.unparse(node))
        except Exception:  # pragma: no cover — печать признака необязательна
            pass

    def _resolve_name(self, node: ast.Name, frame: Frame, depth: int):
        name = node.id
        self._note(node)
        if name == "__file__":
            return t_anchor(self.path)
        if name in frame.subst:
            return frame.subst[name]
        bound = self._assign_for(name, frame)
        if bound is not None:
            return self.resolve(bound, frame, depth + 1)
        bound = self._with_binding(name, frame)
        if bound is not None:
            return self.resolve(bound, frame, depth + 1)
        if frame.func is not None and name in _param_names(frame.func):
            fixture = self.fixtures.get(name)
            if fixture is not None:
                return self._enter(fixture, {}, depth)
            # Параметр без локального определения (встроенная фикстура
            # набора). Значение приходит извне файла — это НЕПРОЗРАЧНЫЙ
            # якорь, а не «временный каталог»: чем он окажется, решает
            # ЗАПИСЬ, которую прибор ищет отдельно.
            self._note(name)
            return t_opaque("param", f"{_func_name(frame.func)}:{name}")
        return t_unknown(f"имя `{name}` не связано в области видимости")

    def _resolve_attribute(self, node: ast.Attribute, frame: Frame, depth: int):
        if node.attr == "parent":
            return t_parent(self.resolve(node.value, frame, depth + 1))
        if node.attr == "__file__" and isinstance(node.value, ast.Name):
            got = self.module_files.get(node.value.id)
            if got is not None:
                return t_anchor(got)
            return t_unknown(f"модуль `{node.value.id}` не разрешён под корнем")
        if node.attr == "__file__" and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Name) \
                and node.value.func.id == "__import__" and node.value.args:
            arg = node.value.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                got = self._module_file(arg.value)
                if got is not None:
                    return t_anchor(got)
            return t_unknown("`__import__(...)` с неконстантным именем модуля")
        if node.attr in ("name", "stem"):
            inner = self.resolve(node.value, frame, depth + 1)
            concrete = concretize(inner)
            if concrete is not None:
                return t_const(concrete.name if node.attr == "name" else concrete.stem)
            if term_unknown_reason(inner) is None and term_has_opaque(inner):
                # `TemporaryDirectory().name` — якорь НЕПРОЗРАЧНЫЙ, но не
                # безымянный: он один и тот же у чтения и у записи, и сравнение
                # термов по-прежнему отвечает на вопрос «один ли это путь».
                # Считать его `unknown` значило бы потерять весь класс фикстур,
                # строящих каталог зовом, а не параметром.
                return ("attrname", inner, node.attr)
            return t_unknown(f"атрибут `{node.attr}` поверх несвёрнутого пути")
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            bound = self._self_attr(node.attr, frame)
            if bound is not None:
                return self.resolve(bound, frame, depth + 1)
            return t_opaque("self", f"self.{node.attr}")
        if isinstance(node.value, ast.Name):
            got = self._neighbour_const(node.value.id, node.attr)
            if got is not None:
                return got
        return t_unknown(f"атрибут `{node.attr}` статикой не сведён")

    def _resolve_subscript(self, node: ast.Subscript, frame: Frame, depth: int):
        base = node.value
        if isinstance(base, ast.Attribute) and base.attr == "parents":
            idx = node.slice
            if isinstance(idx, ast.Constant) and isinstance(idx.value, int):
                return t_parents(self.resolve(base.value, frame, depth + 1), idx.value)
            return t_unknown("индекс `.parents[...]` не константа")
        idx = node.slice
        if isinstance(idx, ast.Constant) and isinstance(idx.value, str):
            container, cframe = self._resolve_container(base, frame, depth)
            if container is not None and idx.value in container:
                return self.resolve(container[idx.value], cframe, depth + 1)
            if self._names_a_runtime_read(base, frame, depth):
                return t_unknown(
                    f"путь назван СОДЕРЖИМЫМ файла в рантайме (ключ `{idx.value}`) — "
                    f"статикой он не определён ни в одну сторону")
            return t_unknown(f"словарь пути не сведён к литералу (ключ `{idx.value}`)")
        return t_unknown("индексация не по строковому литералу")

    def _names_a_runtime_read(self, node: ast.AST, frame: Frame, depth: int) -> bool:
        """Идёт ли выражение от ЧТЕНИЯ файла в рантайме (`json.loads(p.read_text())`).

        Это не придирка к форме: путь, названный содержимым другого файла,
        статикой не определён ПО ПОСТРОЕНИЮ, и причина обязана сказать именно
        это, а не «словарь не сведён» — иначе третий исход выглядит недоработкой
        прибора там, где он есть свойство предмета.
        """
        cur: Optional[ast.AST] = node
        cframe = frame
        for _ in range(self.MAX_DEPTH):
            if cur is None:
                return False
            for sub in ast.walk(cur):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                        and sub.func.attr in _READ_ATTRS:
                    return True
            nxt, nframe = self._expr_of(cur, cframe, depth)
            if nxt is None or nxt is cur:
                return False
            cur, cframe = nxt, nframe
        return False

    def _resolve_container(self, base: ast.AST, frame: Frame, depth: int):
        """Выражение → ({ключ: выражение}, кадр), если сводится к словарю-литералу.

        Не сводится ⇒ (None, кадр): решает вызывающий, какую причину назвать.
        """
        node: Optional[ast.AST] = base
        cur = frame
        for _ in range(self.MAX_DEPTH):
            if isinstance(node, ast.Dict):
                out: Dict[str, ast.AST] = {}
                for key, val in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        out[key.value] = val
                return out, cur
            nxt, nframe = self._expr_of(node, cur, depth)
            if nxt is None or nxt is node:
                return None, cur
            node, cur = nxt, nframe
        return None, cur

    def _resolve_index(self, value: ast.AST, idx: int, frame: Frame, depth: int):
        """Распаковка `a, b = <выражение>` — взять idx-й элемент.

        Правая часть почти никогда не бывает кортежем-литералом прямо на месте:
        это имя фикстуры (`host, wt = trees`) или зов хелпера. Разворачивать её
        обязан ТОТ ЖЕ механизм кадров, иначе «написан тестом» вырождается в «не
        измерено» на всём населении фикстур.
        """
        unwrapped, uframe = self._expr_of(value, frame, depth)
        if unwrapped is not None and unwrapped is not value:
            return self._resolve_index(unwrapped, idx, uframe, depth + 1)
        if isinstance(value, (ast.Tuple, ast.List)):
            if idx < len(value.elts):
                return self.resolve(value.elts[idx], frame, depth + 1)
            return t_unknown("распаковка короче индекса")
        if isinstance(value, ast.Call):
            func = self._local_func(value, frame)
            if func is not None:
                ret = _return_expr(func)
                if isinstance(ret, (ast.Tuple, ast.List)) and idx < len(ret.elts):
                    sub = self._bind_args(func, value, frame, depth)
                    self.visited.append(Frame(func, sub))
                    return self.resolve(ret.elts[idx], Frame(func, sub), depth + 1)
            return t_unknown("распаковка зова, чей возврат не кортеж-литерал")
        return t_unknown("распаковка выражения, которое не кортеж")

    def _expr_of(self, node: ast.AST, frame: Frame, depth: int):
        """Имя/зов → выражение, ДАВШЕЕ значение, и кадр, в котором его читать.

        Возвращает (выражение, кадр) либо (None, кадр). Кадр меняется при заходе
        в хелпер или фикстуру — вместе с подстановкой параметров; без неё терм
        записи и терм чтения жили бы в разных системах координат.
        """
        if depth > self.MAX_DEPTH:
            return None, frame
        if isinstance(node, ast.Name):
            self._note(node)
            if node.id in frame.subst:
                return None, frame
            bound = self._assign_for(node.id, frame)
            if bound is not None and not isinstance(bound, tuple):
                self._note(bound)
                return bound, frame
            if frame.func is not None and node.id in _param_names(frame.func):
                fixture = self.fixtures.get(node.id)
                if fixture is not None:
                    ret = _return_expr(fixture)
                    if ret is not None:
                        sub = Frame(fixture, {})
                        self.visited.append(sub)
                        return ret, sub
            return None, frame
        if isinstance(node, ast.Call):
            local = self._local_func(node, frame)
            if local is not None:
                ret = _return_expr(local)
                if ret is not None:
                    sub = Frame(local, self._bind_args(local, node, frame, depth))
                    self.visited.append(sub)
                    return ret, sub
            return None, frame
        return None, frame

    def _resolve_call(self, node: ast.Call, frame: Frame, depth: int):
        func = node.func
        if isinstance(func, ast.Name):
            if func.id == "Path" and node.args:
                return self.resolve(node.args[0], frame, depth + 1)
            if func.id == "str" and node.args:
                return self.resolve(node.args[0], frame, depth + 1)
            if func.id == "open" and node.args:
                return self.resolve(node.args[0], frame, depth + 1)
            local = self._local_func(node, frame)
            if local is not None:
                ret = _return_expr(local)
                if ret is None:
                    return t_unknown(f"хелпер `{func.id}` ничего не возвращает")
                sub = self._bind_args(local, node, frame, depth)
                self.visited.append(Frame(local, sub))
                return self.resolve(ret, Frame(local, sub), depth + 1)
            return t_opaque("call", func.id)
        if isinstance(func, ast.Attribute):
            if func.attr in ("resolve", "absolute", "expanduser"):
                return self.resolve(func.value, frame, depth + 1)
            if func.attr == "replace" and len(node.args) == 2:
                base = self.resolve(func.value, frame, depth + 1)
                a, b = node.args
                if isinstance(base, tuple) and base[0] == "anchor" \
                        and isinstance(a, ast.Constant) and isinstance(b, ast.Constant):
                    return t_anchor(Path(str(base[1]).replace(a.value, b.value)))
                return t_unknown("`.replace` поверх несвёрнутого пути")
            if func.attr in ("dirname", "abspath", "realpath") \
                    and isinstance(func.value, ast.Attribute) \
                    and func.value.attr == "path" and node.args:
                inner = self.resolve(node.args[0], frame, depth + 1)
                return t_parent(inner) if func.attr == "dirname" else inner
            if func.attr == "join" and isinstance(func.value, ast.Attribute) \
                    and func.value.attr == "path":
                if not node.args:
                    return t_unknown("`os.path.join` без аргументов")
                term = self.resolve(node.args[0], frame, depth + 1)
                for arg in node.args[1:]:
                    term = t_join(term, self.resolve(arg, frame, depth + 1))
                return term
            if func.attr in ("mkdtemp", "mkstemp", "TemporaryDirectory",
                             "NamedTemporaryFile"):
                return t_opaque("call", func.attr)
            return t_opaque("call", func.attr)
        return t_unknown("зов неразбираемой формы")

    def side_effect_frames(self, frame: Frame) -> List[Frame]:
        """Кадры хелперов, зовомых в теле кадра РАДИ ПОБОЧНОГО ДЕЙСТВИЯ.

        Аргументы подставляются так же, как при заходе по значению: иначе терм
        записи жил бы в системе координат хелпера, а терм чтения — в системе
        координат теста, и совпасть они не могли бы никогда.
        """
        scope = frame.func if frame.func is not None else self.tree
        out: List[Frame] = []
        seen: set = set()
        for node in ast.walk(scope):
            if not isinstance(node, ast.Call):
                continue
            func = self._local_func(node, frame)
            if func is None or id(func) in seen:
                continue
            seen.add(id(func))
            out.append(Frame(func, self._bind_args(func, node, frame, 0)))
        return out

    def _local_func(self, call: ast.Call, frame: Frame) -> Optional[ast.AST]:
        func = call.func
        if isinstance(func, ast.Name):
            got = self.module_funcs.get(func.id)
            if got is not None and got is not frame.func:
                return got
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
                and func.value.id == "self":
            return self._self_method(func.attr, frame)
        return None

    def _bind_args(self, func: ast.AST, call: ast.Call, frame: Frame,
                   depth: int) -> Dict[str, tuple]:
        """Подстановка параметров хелпера: позиционные, именованные, умолчания."""
        names = _param_names(func)
        sub: Dict[str, tuple] = {}
        for name, default in _param_defaults(func).items():
            sub[name] = self.resolve(default, frame, depth + 1)
        for idx, arg in enumerate(call.args):
            if idx < len(names):
                sub[names[idx]] = self.resolve(arg, frame, depth + 1)
        for kw in call.keywords:
            if kw.arg:
                sub[kw.arg] = self.resolve(kw.value, frame, depth + 1)
        return sub

    def _enter(self, func: ast.AST, sub: Dict[str, tuple], depth: int):
        ret = _return_expr(func)
        if ret is None:
            return t_opaque("fixture", _func_name(func))
        self.visited.append(Frame(func, sub))
        return self.resolve(ret, Frame(func, sub), depth + 1)


def _param_names(func: ast.AST) -> List[str]:
    args = getattr(func, "args", None)
    if args is None:
        return []
    out = [a.arg for a in list(args.posonlyargs) + list(args.args)]
    out.extend(a.arg for a in args.kwonlyargs)
    return out


def _param_defaults(func: ast.AST) -> Dict[str, ast.AST]:
    args = getattr(func, "args", None)
    if args is None:
        return {}
    out: Dict[str, ast.AST] = {}
    positional = list(args.posonlyargs) + list(args.args)
    if args.defaults:
        for arg, default in zip(positional[-len(args.defaults):], args.defaults):
            out[arg.arg] = default
    for arg, default in zip(args.kwonlyargs, args.kw_defaults or []):
        if default is not None:
            out[arg.arg] = default
    return out


def _func_name(func: Optional[ast.AST]) -> str:
    return getattr(func, "name", "<модуль>")


def _return_expr(func: ast.AST) -> Optional[ast.AST]:
    """ТЕКСТУАЛЬНО последний `return` САМОЙ функции (не вложенной в неё).

    Два уточнения, каждое измерено на наборе. Первое: `ast.walk` обходит в
    ширину, поэтому «последний встреченный» не есть «последний по тексту» —
    порядок решается номером строки, а не порядком обхода. Второе: вложенная
    функция (фабрика, замыкание внутри фикстуры) имеет СВОЙ возврат, и взять
    его за возврат внешней значило бы приписать значению чужое происхождение.

    Развилка возвратов прибором не моделируется, и это сказано вслух: если
    ветки ведут в разные файлы, вердикт обязан прийти через `unknown`, а не
    через угаданную ветку.
    """
    inner: set = set()
    for node in ast.walk(func):
        if node is func:
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for sub in ast.walk(node):
                inner.add(id(sub))
    best, best_line = None, -1
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and node.value is not None \
                and id(node) not in inner:
            line = getattr(node, "lineno", 0)
            if line > best_line:
                best, best_line = node.value, line
    return best


# ──────────────────── чтение и запись ────────────────────

def read_path_expr(hay: ast.AST, tracer: Tracer, frame: Frame,
                   depth: int = 0) -> Tuple[Optional[ast.AST], Optional[str]]:
    """Выражение ПУТИ, из которого пришло содержимое стога.

    Возвращает (выражение, причина-отказа). Отличие от #568: там цепочка
    обрывалась на первой же незнакомой форме и сайт уходил в остаток; здесь
    разбираются `open()`/`fh.read()` внутри `with`, зов хелпера и распаковка.
    """
    if depth > Tracer.MAX_DEPTH:
        return None, "цепочка стога глубже предела разбора"
    if isinstance(hay, ast.Call):
        func = hay.func
        if isinstance(func, ast.Attribute) and func.attr in _READ_ATTRS:
            recv = func.value
            if isinstance(recv, ast.Name):
                bound = tracer._with_binding(recv.id, frame)
                if bound is not None:
                    return read_path_expr(bound, tracer, frame, depth + 1)
            if isinstance(recv, ast.Call) and isinstance(recv.func, ast.Name) \
                    and recv.func.id == "open" and recv.args:
                return recv.args[0], None
            return recv, None
        if isinstance(func, ast.Attribute) and func.attr == "getsource" and hay.args:
            return ast.Attribute(value=hay.args[0], attr="__file__", ctx=ast.Load()), None
        if isinstance(func, ast.Name) and func.id == "open" and hay.args:
            return hay.args[0], None
        inner, iframe = tracer._expr_of(hay, frame, depth)
        if inner is not None:
            return read_path_expr(inner, tracer, iframe, depth + 1)
        return None, "стог — зов, не являющийся чтением файла"
    if isinstance(hay, ast.Name):
        bound = tracer._assign_for(hay.id, frame)
        if bound is None:
            bound = tracer._with_binding(hay.id, frame)
        if bound is None:
            inner, iframe = tracer._expr_of(hay, frame, depth)
            if inner is not None:
                return read_path_expr(inner, tracer, iframe, depth + 1)
            return None, f"имя стога `{hay.id}` не связано в области видимости"
        if isinstance(bound, tuple):
            return _unpacked_read(bound, tracer, frame, depth)
        return read_path_expr(bound, tracer, frame, depth + 1)
    if isinstance(hay, ast.Subscript):
        idx = hay.slice
        if isinstance(idx, ast.Constant) and isinstance(idx.value, str):
            container, cframe = tracer._resolve_container(hay.value, frame, depth)
            if container is not None and idx.value in container:
                return read_path_expr(container[idx.value], tracer, cframe, depth + 1)
        return None, "стог — элемент контейнера, зов чтения не назван"
    return None, f"стог формы {type(hay).__name__} к зову чтения не сведён"


def _unpacked_read(bound: tuple, tracer: "Tracer", frame: Frame,
                   depth: int) -> Tuple[Optional[ast.AST], Optional[str]]:
    """Стог пришёл распаковкой `a, b = <зов>` — взять idx-й возврат и идти дальше."""
    value, idx = bound[1], bound[2]
    cur, cframe = value, frame
    for _ in range(Tracer.MAX_DEPTH):
        if isinstance(cur, (ast.Tuple, ast.List)):
            if idx < len(cur.elts):
                return read_path_expr(cur.elts[idx], tracer, cframe, depth + 1)
            return None, "распаковка короче индекса"
        nxt, nframe = tracer._expr_of(cur, cframe, depth)
        if nxt is None or nxt is cur:
            return None, "стог пришёл распаковкой — зов чтения не назван"
        cur, cframe = nxt, nframe
    return None, "распаковка глубже предела разбора"


def write_events(tracer: Tracer, frame: Frame) -> List[Tuple[tuple, ast.AST, str]]:
    """Все записи файла в кадре: (терм-цель, выражение-содержимое, вид зова)."""
    scope = frame.func if frame.func is not None else tracer.tree
    out: List[Tuple[tuple, ast.AST, str]] = []
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _WRITE_ATTRS:
            term = tracer.resolve(func.value, frame, 0)
            content = node.args[0] if node.args else None
            out.append((term, content, func.attr))
        elif isinstance(func, ast.Attribute) and func.attr in ("copy", "copy2",
                                                               "copyfile") \
                and len(node.args) >= 2:
            out.append((tracer.resolve(node.args[1], frame, 0), node.args[0],
                        f"shutil.{func.attr}"))
        elif isinstance(func, ast.Name) and func.id == "atomic_save" \
                and len(node.args) >= 2:
            out.append((tracer.resolve(node.args[1], frame, 0), node.args[0],
                        "atomic_save"))
        elif isinstance(func, ast.Attribute) and func.attr == "write" \
                and isinstance(func.value, ast.Name):
            bound = tracer._with_binding(func.value.id, frame)
            if bound is not None and isinstance(bound, ast.Call) \
                    and isinstance(bound.func, ast.Name) and bound.func.id == "open" \
                    and len(bound.args) >= 2:
                mode = bound.args[1]
                if isinstance(mode, ast.Constant) and isinstance(mode.value, str) \
                        and ("w" in mode.value or "a" in mode.value):
                    out.append((tracer.resolve(bound.args[0], frame, 0),
                                node.args[0] if node.args else None, "open(w).write"))
        elif isinstance(func, ast.Attribute) and func.attr == "dump" \
                and len(node.args) >= 2 and isinstance(node.args[1], ast.Name):
            bound = tracer._with_binding(node.args[1].id, frame)
            if bound is not None and isinstance(bound, ast.Call) \
                    and isinstance(bound.func, ast.Name) and bound.func.id == "open" \
                    and bound.args:
                out.append((tracer.resolve(bound.args[0], frame, 0),
                            node.args[0], "json.dump"))
    return out


def content_from_repo(content: Optional[ast.AST], tracer: Tracer, frame: Frame,
                      root: Path) -> Optional[str]:
    """Происходит ли ЗАПИСАННОЕ содержимое от чтения файла под корнем дерева.

    Это вторая половина ловушки заказа, и она измеряется, а не оговаривается:
    фикстура, скопировавшая настоящий файл репозитория во временный каталог,
    обязана попасть в repo-сторону, хотя путь чтения ведёт в tmp.
    """
    if content is None:
        return None
    for node in ast.walk(content):
        path_expr, _ = read_path_expr(node, tracer, frame)
        if path_expr is None:
            continue
        term = tracer.resolve(path_expr, frame, 0)
        concrete = concretize(term)
        if concrete is None:
            continue
        try:
            rel = concrete.resolve().relative_to(root.resolve())
        except (ValueError, OSError):
            continue
        if concrete.is_file():
            return str(rel)
    return None


# ──────────────────────── замер ────────────────────────

def classify_site(site: dict, tracer: Tracer, node: ast.AST, hay: ast.AST,
                  root: Path) -> dict:
    """Один сайт → исход с НАЗВАННЫМ основанием."""
    func = _scope_of(node, tracer.parents)
    if isinstance(func, ast.Module):
        func = None
    frame = Frame(func, {})
    tracer.visited = [frame]
    tracer.trace_src = []

    path_expr, why = read_path_expr(hay, tracer, frame)
    if path_expr is not None:
        tracer._note(path_expr)
    if path_expr is None:
        return {"verdict": "unmeasured", "reason": why or "зов чтения не найден"}

    term = tracer.resolve(path_expr, frame, 0)
    unknown = term_unknown_reason(term)

    # ── вопрос 1: писал ли сам тест по ЭТОМУ пути ──
    # Кадров два рода, и второй не выводится из первого. ПРОЙДЕННЫЕ при
    # разрешении пути — те, через которые значение пришло. Но запись умеет жить
    # в хелпере, зовомом РАДИ ПОБОЧНОГО ДЕЙСТВИЯ (`_write(box.name)`, путь потом
    # собирается в самом тесте): его кадр при разрешении ЧТЕНИЯ не посещается
    # никогда, и без второго рода такой сайт уходил бы в «не измерено» по
    # свойству ПРИБОРА.
    visited = list(tracer.visited) + tracer.side_effect_frames(frame)
    if unknown is None:
        for vframe in visited:
            for target, content, kind in write_events(tracer, vframe):
                if target != term:
                    continue
                origin = content_from_repo(content, tracer, vframe, root)
                if origin is not None:
                    return {"verdict": "repo_copy", "write_kind": kind,
                            "repo_file": origin,
                            "reason": "файл написан тестом, но содержимое записи "
                                      "происходит от чтения файла под корнем дерева"}
                return {"verdict": "self_written", "write_kind": kind,
                        "reason": "по тому же пути в коде теста есть ЗАПИСЬ, а её "
                                  "содержимое не происходит ни от какого чтения "
                                  "под корнем дерева"}

    # ── вопрос 2: лежит ли путь под корнем дерева ──
    concrete = concretize(term)
    if concrete is not None:
        try:
            rel = concrete.resolve().relative_to(root.resolve())
        except (ValueError, OSError):
            return {"verdict": "unmeasured",
                    "reason": f"путь свёрнут, но лежит ВНЕ корня дерева ({concrete})"}
        if concrete.is_file():
            return {"verdict": "repo_neighbour", "repo_file": str(rel),
                    "reason": "путь свёрнут до файла, существующего под корнем "
                              "дерева, и записи по нему в коде теста нет"}
        return {"verdict": "unmeasured",
                "reason": f"путь свёрнут под корень ({rel}), но файла там НЕТ — "
                          f"чем он окажется в прогоне, статикой не сказано"}

    if unknown is not None:
        return {"verdict": "unmeasured", "reason": unknown}
    if term_has_opaque(term):
        return {"verdict": "unmeasured",
                "reason": "путь стоит на непрозрачном якоре (параметр/фикстура/зов), "
                          "и ЗАПИСИ по нему в коде теста не найдено — чем он "
                          "окажется, не сказано ни тем, ни другим"}
    return {"verdict": "unmeasured", "reason": "терм пути не сведён и не опознан"}


def name_sign(path_expr_src: str) -> bool:
    """ЛОВУШКА заказа: что сказал бы признак-по-имени. В вердикте не участвует."""
    return bool(_TMP_NAME_SIGN.search(path_expr_src))


def _site_nodes(root: Path, sites: List[dict]):
    """Сайт → (tracer, узел-зов, выражение-стога). Разбор файла один раз."""
    from spa_core.monitoring.substring_structure_assertions import _membership_pair

    by_file: Dict[str, List[dict]] = {}
    for site in sites:
        by_file.setdefault(site["file"], []).append(site)

    for rel, group in sorted(by_file.items()):
        path = root / rel
        tree = _parse(path)
        if tree is None:
            for site in group:
                yield site, None, None, None
            continue
        tracer = Tracer(tree, path, root)
        wanted = {s["line"] for s in group}
        found: Dict[int, Tuple[ast.AST, ast.AST]] = {}
        for node in ast.walk(tree):
            line = getattr(node, "lineno", None)
            if line not in wanted:
                continue
            pair = _membership_pair(node)
            if pair is None:
                continue
            found[line] = (node, pair[1])
        for site in group:
            got = found.get(site["line"])
            if got is None:
                yield site, tracer, None, None
            else:
                yield site, tracer, got[0], got[1]


def measure(root: Path, *, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    root = Path(root)

    _, every = forward_sites(root)
    boundary = [s for s in every
                if s.get("haystack") == "text" and s.get("excluded")
                and BOUNDARY_REASON in s["excluded"]]

    verdicts: Dict[str, List[dict]] = {
        "repo_neighbour": [], "repo_copy": [], "self_written": [], "unmeasured": []}
    sign_rows: List[dict] = []

    for site, tracer, node, hay in _site_nodes(root, boundary):
        row = {"file": site["file"], "line": site["line"],
               "literal": site.get("literal", "")}
        if tracer is None:
            row.update({"verdict": "unmeasured",
                        "reason": "файл сайта не разобран повторно"})
        elif node is None:
            row.update({"verdict": "unmeasured",
                        "reason": "зов-утверждение не найден повторным разбором"})
        else:
            row.update(classify_site(site, tracer, node, hay, root))
            # Признак-по-имени применяется к ТЕКСТУ ЦЕПОЧКИ связывания — ровно к
            # тому, что увидел бы человек, идущий по коду глазами. Применять его
            # к абсолютному пути было бы подлогом: дерево цикла живёт в
            # `/private/tmp/...`, и тогда «tmp» нашлось бы у КАЖДОГО соседа под
            # корнем — расхождение изготовилось бы из места запуска.
            row["trace_src"] = " ; ".join(tracer.trace_src)
        verdicts[row["verdict"]].append(row)
        sign_rows.append(row)

    # ── ловушка: признак-по-имени против замера ──
    sign_vs_measure = {"sign_says_tmp": 0, "sign_says_repo": 0,
                       "sign_says_tmp_but_measure_says_repo": [],
                       "sign_says_repo_but_measure_says_self": [],
                       "sign_answers_where_measure_refuses": []}
    for row in sign_rows:
        sign = name_sign(row.get("trace_src") or "")
        sign_vs_measure["sign_says_tmp" if sign else "sign_says_repo"] += 1
        if sign and row["verdict"] in ("repo_neighbour", "repo_copy"):
            sign_vs_measure["sign_says_tmp_but_measure_says_repo"].append(
                {"file": row["file"], "line": row["line"], "verdict": row["verdict"]})
        if not sign and row["verdict"] == "self_written":
            sign_vs_measure["sign_says_repo_but_measure_says_self"].append(
                {"file": row["file"], "line": row["line"]})
        if row["verdict"] == "unmeasured":
            # Главное свойство признака: он отвечает ВСЕГДА. Там, где замер
            # отказался, признак всё равно назовёт сторону — и назовёт её
            # уверенно. Это и есть цена подмены замера признаком, и она
            # СЧИТАЕТСЯ, а не оговаривается.
            sign_vs_measure["sign_answers_where_measure_refuses"].append(
                {"file": row["file"], "line": row["line"],
                 "sign": "временный" if sign else "репозиторий"})

    counts = {k: len(v) for k, v in verdicts.items()}
    counts["boundary"] = len(boundary)
    counts["assertion_sites"] = len(every)
    repo_side = counts["repo_neighbour"] + counts["repo_copy"]

    population_disagrees = len(boundary) != PUBLISHED_BOUNDARY

    findings: List[str] = []
    findings.append(
        f"[ПРЕЖДЕ ДОЛИ] «путь статикой не свернулся» НЕ равно «соседа нет в "
        f"репозитории»: из {len(boundary)} сайтов за границей ADR-338 "
        f"{repo_side} читают файл, ЛЕЖАЩИЙ ПОД КОРНЕМ ДЕРЕВА. Граница #568 "
        f"проходила по тому, что умел свернуть ЕГО сворачиватель, а не по тому, "
        f"где лежит файл")
    findings.append(
        f"[РАЗДЕЛЕНИЕ] настоящий сосед в репозитории: {counts['repo_neighbour']} · "
        f"копия репозиторного файла, сделанная тестом: {counts['repo_copy']} · "
        f"файл, написанный САМИМ тестом: {counts['self_written']} · не измерено: "
        f"{counts['unmeasured']}. «Не измерено» не складывается ни с одной долей "
        f"и НИКОГДА не читается как «временный»")
    if repo_side:
        findings.append(
            f"[ЦЕНА] у {repo_side} сайт(ов) предмет заказа ЕСТЬ: обрыв литерала "
            f"здесь — тот же дефект, что закрыт ADR-338. Обрывается ли он у них "
            f"на самом деле, ЭТОТ прибор не утверждает — это отдельный замер "
            f"возмущением, и подменять его разделением нельзя")
    for row in verdicts["repo_neighbour"] + verdicts["repo_copy"]:
        findings.append(
            f"[ПРЕДМЕТ ЕСТЬ] {row['file']}:{row['line']} читает "
            f"{row.get('repo_file')} ({row['verdict']})")
    if counts["self_written"]:
        findings.append(
            f"[ПРЕДМЕТА НЕТ] {counts['self_written']} сайт(ов) судят о байтах, "
            f"которые тест сам и написал: по тому же пути в его коде найдена "
            f"ЗАПИСЬ, а её содержимое не происходит от чтения под корнем")
    if sign_vs_measure["sign_says_tmp_but_measure_says_repo"]:
        findings.append(
            f"[ЛОВУШКА, ЗАМЕР] признак-по-имени ошибся в сторону «временный» на "
            f"{len(sign_vs_measure['sign_says_tmp_but_measure_says_repo'])} "
            f"сайт(ах): имя кричит про tmp, а содержимое пришло из репозитория")
    if sign_vs_measure["sign_says_repo_but_measure_says_self"]:
        findings.append(
            f"[ЛОВУШКА, ЗАМЕР] признак-по-имени ошибся в другую сторону на "
            f"{len(sign_vs_measure['sign_says_repo_but_measure_says_self'])} "
            f"сайт(ах): в имени пути нет ни следа временного каталога, а файл "
            f"написан самим тестом")
    if not (sign_vs_measure["sign_says_tmp_but_measure_says_repo"]
            or sign_vs_measure["sign_says_repo_but_measure_says_self"]):
        findings.append(
            "[ЛОВУШКА, ЗАМЕР] на ТЕХ сайтах, где замер состоялся, признак-по-"
            "имени с ним совпал. Правом быть ответом он от этого не становится, "
            "и совпадение измерено здесь и сегодня — вердикты прибор выводит "
            "без имён вовсе")
    refuses = sign_vs_measure["sign_answers_where_measure_refuses"]
    if refuses:
        tmp_side = sum(1 for r in refuses if r["sign"] == "временный")
        findings.append(
            f"[ЛОВУШКА, ГЛАВНОЕ] признак-по-имени ответил бы на ВСЕХ "
            f"{len(refuses)} сайтах, где замер ОТКАЗАЛСЯ: {tmp_side} назвал бы "
            f"«временный», {len(refuses) - tmp_side} — «репозиторий». Именно "
            f"здесь подмена замера признаком и даёт долю, за которой нет "
            f"ничего: сторона названа, а происхождение значения не прослежено "
            f"ни у одного из них")
    if counts["unmeasured"]:
        reasons: Dict[str, int] = {}
        for row in verdicts["unmeasured"]:
            reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
        for reason, num in sorted(reasons.items(), key=lambda kv: -kv[1]):
            findings.append(f"[НЕ ИЗМЕРЕНО] {num} сайт(ов) — {reason}")
    if population_disagrees:
        findings.append(
            f"[CRITICAL] население за границей = {len(boundary)}, а ADR-338 "
            f"опубликовал {PUBLISHED_BOUNDARY}: доля несопоставима с "
            f"опубликованной, пока расхождение не разобрано")

    if population_disagrees:
        status = STATUS_CRITICAL
    elif counts["unmeasured"]:
        status = STATUS_WARNING
    else:
        status = STATUS_OK

    return {
        "generated_at": now.isoformat(),
        "status": status,
        "overall": status,
        "counts": counts,
        "published_boundary": PUBLISHED_BOUNDARY,
        "population_source_disagrees": population_disagrees,
        "split": {
            "repo_neighbour": verdicts["repo_neighbour"],
            "repo_copy": verdicts["repo_copy"],
            "self_written": [{"file": r["file"], "line": r["line"],
                              "write_kind": r.get("write_kind")}
                             for r in verdicts["self_written"]],
            "unmeasured": [{"file": r["file"], "line": r["line"],
                            "reason": r["reason"]} for r in verdicts["unmeasured"]],
        },
        "name_sign_vs_measure": sign_vs_measure,
        "findings": findings,
        "advisory": (
            "ADVISORY: прибор только ЧИТАЕТ исходники набора. Ни один тест не "
            "правится, не скипается и не сужается (инв. #16); POLLED_ADAPTERS, "
            "пины, писатель журнала решений, TriggerParams, пороги RiskPolicy "
            "v1.0, потолки концентрации, стоп-кран и живой трек НЕ тронуты."),
        "what_it_does_not_prove": (
            "НЕ ДОКЛАДЫВАЕТ: обрывается ли литерал у сайтов repo-стороны — это "
            "замер ADR-338 возмущением, и разделение его не заменяет; верно ли "
            "утверждение по существу; и что происходит с путём в РАНТАЙМЕ — "
            "весь замер статический, монки-патч каталога прибор не видит."),
    }


def format_report(doc: dict) -> List[str]:
    lines = [f"haystack_origin_census: {doc.get('overall')}"]
    lines.extend(doc.get("findings") or [])
    return lines


def run(root: Optional[str] = None, *, now=None, write: bool = True,
        data_dir: Optional[str] = None) -> dict:
    """Форма ступени переписей: `root` — КОРЕНЬ ДЕРЕВА (ADR-326)."""
    from spa_core.utils.atomic import atomic_save

    root = root or str(Path(__file__).resolve().parents[2])
    out_dir = Path(data_dir) if data_dir else Path(root) / "data"
    doc = measure(Path(root), now=now)
    if write:
        out_dir.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(out_dir / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="откуда пришло содержимое стога: сосед под корнем дерева "
                    "или байты, написанные самим тестом (заказ #568)")
    ap.add_argument("--root", default=None, help="КОРЕНЬ ДЕРЕВА")
    ap.add_argument("--data-dir", default=None, help="каталог данных, если не <root>/data")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    root = args.root or str(Path(__file__).resolve().parents[2])
    data_dir = args.data_dir or os.environ.get("SPA_DATA_DIR")
    doc = run(root=root, write=not args.no_write, data_dir=data_dir)
    for line in format_report(doc):
        print(line)
    return 0 if doc["status"] in (STATUS_OK, STATUS_WARNING) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
