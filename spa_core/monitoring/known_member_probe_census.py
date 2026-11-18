#!/usr/bin/env python3
"""spa_core/monitoring/known_member_probe_census.py — ПЕРЕПИСЬ ПРИБОРОВ БЕЗ ПРОБЫ «ИЗВЕСТНЫЙ ЧЛЕН».

# LLM_FORBIDDEN

Вопрос, на который отвечает прибор
----------------------------------
«У скольких приборов дерева, печатающих вердикт о НАСЕЛЕНИИ класса, в батарее
НЕТ пробы, которая спрашивает прибор о ЖИВОМ дереве и предъявляет ему
ИЗВЕСТНОГО ЧЛЕНА?»

Откуда взят вопрос
------------------
Заказ **G1029 п. 2** приказа владельца «Portfolio CIO» (хвост ADR-1040),
дословно:

    «Правило для следующего замера любого класса: прежде чем печатать
     население, предъявить ИЗВЕСТНОГО члена. Замер, не нашедший известного
     члена, мерой класса не является. Сколько ещё приборов дерева не имеют
     такой пробы — НЕ ИЗМЕРЕНО и нулём не считается.»

Класс найден не рассуждением, а трижды случившейся аварией ОДНОГО цикла
(#1179, ADR-1040): способ, названный заказом, НЕ НАХОДИЛ известного члена по
трём разным причинам (одно место объявления из двух · форма засева · его
глубина), и КАЖДЫЙ раз ответ выглядел как число. До того тем же кончились
#1046/#1047 (ADR-932: `✅ ПУСТ` при 19 зелёных тестах и 11/11 убитых мутациях)
и #1048 (прибор ДВАЖДЫ сказал «✅ ПУСТ» на непустом классе).

Почему проба обязана спрашивать ЖИВОЕ дерево
--------------------------------------------
Сцена в одноразовом каталоге проверяет ТУ ФОРМУ, которую автор держал в
голове, — и потому не способна опровергнуть саму форму. Ровно это и ломалось:
во всех трёх авариях синтетические сцены были ЗЕЛЕНЫ, а живой известный член
не находился. Поэтому предметом пробы объявлено сочетание, а не любая из
половин:

    ЖИВОЕ дерево  ∧  ИЗВЕСТНЫЙ член, названный НЕ из ответа прибора.

Это дословно форма пробы, которую заказ хвалит
(`test_the_surface_finds_every_known_member_of_the_class`, ADR-1040) и форма
проб у `_tracker_content_door` (#1015) и у `timeout_door_census` (ADR-620).

Три исхода, перечень ЗАКРЫТ, сумма равна населению (инв. #17)
-------------------------------------------------------------
``has_probe``   проба найдена — прибор НЕ член класса.
``no_probe``    проба не найдена — ПРЕДМЕТ КЛАССА. Род назван:
                ``battery_absent`` (батареи нет вовсе — худший род, и он
                отделён, потому что «нет пробы» и «нет батареи» чинятся
                разным) · ``battery_without_probe``.
``unmeasured``  прибор или батарея не прочитаны / не разобраны. Это НЕ «пробы
                нет»: о таком приборе не известно ничего.

Ошибка ответа идёт в сторону БОЛЬШЕГО населения, и это выбрано нарочно
---------------------------------------------------------------------
Форма пробы ЗАКРЫТА перечнями (ниже), поэтому настоящая проба в неузнанной
форме попадёт в ``no_probe``:

    население класса  ≤  `counts[no_probe]`

Мера, ошибающаяся в другую сторону, умеет объявить работу законченной — а это
дороже лишнего кандидата (тот же выбор и та же причина, что у
`_population_verdict_surface`).

ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ — ИЗВЕСТНЫЕ ЧЛЕНЫ ПО ОБЕ СТОРОНЫ
--------------------------------------------------------
Прибор, печатающий население класса без предъявления известного члена, был бы
ровно тем дефектом, который он мерит. Поэтому перед печатью населения
``calibrate()`` предъявляет ОБЕ стороны (`KNOWN_WITH_PROBE`,
`KNOWN_WITHOUT_PROBE`, каждая вычитана руками и несёт адрес пробы либо
причину её отсутствия), и форма, потерявшая известного члена, ОПРОВЕРГНУТА:
перепись тогда ОТКАЗЫВАЕТ (код 2, поимённо), а не печатает число.

Первая редакция формы этого прибора так и была опровергнута — и дважды:
``scripts/forbidden_reach_census.py`` терялся, потому что сцену строит
ПОМОЩНИК (засев не ходил в помощника), а ``timeout_door_census`` — потому что
его проба предъявляет члена через ``assertTrue(any(... endswith ...))``, а не
через ``assertIn``. Обе находки сохранены здесь как причины, по которым форма
именно такая.

Чего прибор НЕ доказывает
-------------------------
* ``has_probe`` не означает «проба верна»: он означает «проба предъявляет
  живому дереву названного члена». Верность самой пробы — следующий вопрос,
  и здесь он не измерен вовсе.
* Поверхность наследована у `_population_verdict_surface` целиком, вместе с
  её формой. Прибор, печатающий население в форме, которой та поверхность не
  знает, в население НЕ входит — замер: `observation_channel_env_census`
  (ADR-1040) объявляет исходы ТУПЛАМИ (`DECLARED_STATUSES`), а не парой
  строковых констант, и поверхностью НЕ НАЙДЕН. Поэтому он стоит в
  калибровке: детектор о нём отвечает, поверхность — нет.
* Засев идёт по ОДНОМУ файлу батареи и его помощникам. Помощник в СОСЕДНЕМ
  модуле не прослеживается — ось есть ПОВЕРХНОСТЬ (та же граница, о которую
  спотыкается сторож претензии `injected-clock`, ADR-897).

ADVISORY: прибор только ЧИТАЕТ дерево. Ни одного байта не правит, ни одного
подпроцесса не поднимает сам (поверхность берётся входом либо отдельным
зовом), о свежести не судит — значит ни одной двери к календарю и к номерам
процессов у него нет по построению.
"""
from __future__ import annotations

import ast
import copy
import json
import os
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Iterable, Optional

# ───────────────────────────── объявленные исходы ────────────────────────────

HAS_PROBE = "has_probe"
NO_PROBE = "no_probe"
UNMEASURED = "unmeasured"
OUTCOMES: tuple[str, ...] = (HAS_PROBE, NO_PROBE, UNMEASURED)

BATTERY_ABSENT = "battery_absent"
BATTERY_WITHOUT_PROBE = "battery_without_probe"
NO_PROBE_RODS: tuple[str, ...] = (BATTERY_ABSENT, BATTERY_WITHOUT_PROBE)

SUBJECT_UNPARSED = "subject_unparsed"
BATTERY_UNPARSED = "battery_unparsed"
UNMEASURED_RODS: tuple[str, ...] = (SUBJECT_UNPARSED, BATTERY_UNPARSED)

#: Дверь, которой батарея достаёт прибор. Две, и они НЕ равносильны.
DOOR_IMPORT = "import"   #: привязка импорта — сильная дверь
DOOR_PATH = "path"       #: путь прибора строкой (CLI-прибор) — слабее
DOORS: tuple[str, ...] = (DOOR_IMPORT, DOOR_PATH)

#: Форма ИМЕНИ известного члена. Перечень ЗАКРЫТ, и каждая форма названа:
#: лишняя форма пустила бы ярлык состояния (`"measured"`, `"ci"`) за имя
#: члена, а это ровно та подмена, против которой прибор написан.
ITEM_PATH = "path"               #: 'spa_core/monitoring/watcher.py', '_probe.py'
ITEM_UPPER = "upper"             #: 'SPA_PYTEST_STREAM'
ITEM_DECLARED = "declared_loop"  #: переменная цикла по ОБЪЯВЛЕННОМУ перечню
#: Ось известных членов названа САМИМ прибором, и батарея утверждает о ней на
#: живом дереве (`assertEqual([], census.declared_outside_form)`). Сильнейшая
#: форма — перечень берётся у источника, а не копией, — и ровно поэтому в ней
#: НЕТ литерала-имени: без этой формы терялся известный член
#: `_population_verdict_surface` (замер этого цикла).
ITEM_DECLARED_SLOT = "declared_slot"
ITEM_FORMS: tuple[str, ...] = (ITEM_PATH, ITEM_UPPER, ITEM_DECLARED,
                               ITEM_DECLARED_SLOT)

_PATH_ITEM = re.compile(
    r"^[\w./\-]+\.(py|json|jsonl|md|yml|yaml|sh|astro|js|ts|txt|plist)$")
_UPPER_ITEM = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_DECLARED_SOURCE = re.compile(r"(KNOWN|DECLARED|EXPECTED|SCENES|MEMBERS)")
#: Имя ключа/атрибута, которым ПРИБОР называет ось известных членов.
_DECLARED_SLOT = re.compile(r"(known|declared|expected|member)", re.IGNORECASE)

#: Каталоги батарей. Объявлены, а не найдены обходом: набор, который гейтит CI,
#: назван в `CLAUDE.md` одной строкой, и расхождение с ним краснит сторожа.
BATTERY_DIRS: tuple[str, ...] = (
    "spa_core/tests", "scripts/tests", "tests", "studio_shell", "research/cards",
)

#: Имена, по которым видно, что корень НЕ живой. Сцена в одноразовом каталоге
#: проверяет форму автора и потому формой пробы не является (см. докстроку).
_DISPOSABLE = re.compile(
    r"(TemporaryDirectory|mkdtemp|mkstemp|tempfile|NamedTemporaryFile)")

_ASSERT_METHODS = frozenset({
    "assertIn", "assertEqual", "assertTrue", "assertGreater", "assertGreaterEqual",
    "assertCountEqual", "assertSetEqual", "assertLess", "assertNotIn",
})

#: Методы-ПОДГОТОВКИ, чей вызов харнесс гарантирует ДО каждого теста того же
#: класса (`unittest` — `setUp`/`setUpClass`/`asyncSetUp`, `pytest` —
#: `setup_method`/`setup_class`). Перечень ЗАКРЫТ: имя вне него харнессом не
#: гарантировано, и считать его подготовкой значило бы объявить пробой зов,
#: который может не состояться вовсе.
#:
#: ОДНО ИМЯ — ОДИН ОБЪЕКТ (урок цикла #274). Этот же перечень читает
#: `spa_core/monitoring/probe_candidate_root_census.py`, и расхождение двух
#: копий означало бы, что два прибора одного семейства считают подготовкой
#: РАЗНОЕ — то есть отвечают на разные вопросы под одним словом.
FIXTURE_METHODS: frozenset[str] = frozenset({
    "setUp", "setUpClass", "asyncSetUp", "setup_method", "setup_class",
})


class Refused(Exception):
    """Предпосылка переписи не обеспечена — отказ с названной причиной."""


# ───────────────────────────── элементарные формы ────────────────────────────


def item_form(node: ast.AST, declared_vars: frozenset[str]) -> Optional[str]:
    """Форма ИМЕНИ известного члена у выражения `node`, либо None.

    Перечень форм ЗАКРЫТ (`ITEM_FORMS`). Прозаический литерал («НЕ ИЗМЕРЕНО»,
    «measured») именем члена не является и формы не имеет — иначе проба о
    СТАТУСЕ считалась бы пробой о ЧЛЕНЕ.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if _PATH_ITEM.match(sub.value) or "/" in sub.value:
                return ITEM_PATH
            if _UPPER_ITEM.match(sub.value):
                return ITEM_UPPER
        if isinstance(sub, ast.Name) and sub.id in declared_vars:
            return ITEM_DECLARED
    return None


def _names(node: ast.AST) -> set[str]:
    """Имена, на которые ссылается выражение (включая `self.<имя>`)."""
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) \
                and sub.value.id == "self":
            out.add("self." + sub.attr)
    return out


def subject_keys(rel: str) -> frozenset[str]:
    """Имена, под которыми батарея способна ввезти прибор `rel`.

    Две формы, и вторая обязательна: `scripts/*.py` батареи ввозят ГОЛЫМ
    именем после `sys.path.insert(0, …/scripts)`, и дверь, знавшая только
    точечную форму, теряла `scripts/forbidden_reach_census.py` — известного
    члена с живой батареей (замер этого цикла).
    """
    keys = {rel[:-3].replace("/", ".")}
    parts = rel[:-3].split("/")
    if parts[0] == "scripts" and len(parts) == 2:
        keys.add(parts[1])
    return frozenset(keys)


def scope_nodes(node: ast.AST) -> list[ast.AST]:
    """Узлы ОДНОЙ области видимости: в тела вложенных функций и классов не ходим.

    Разделение обязательно и измерено: имя `root` в одном тесте происходит от
    `__file__`, а в соседнем — от `TemporaryDirectory()`. Пока оба множества
    считались по ВСЕМУ файлу, одноразовое имя отравляло живое, и форма теряла
    известного члена (`_population_verdict_surface`, замер этого цикла). Это
    та же ошибка, что «контейнер привязкой НЕ является» у сторожа
    `injected-clock`, только по области видимости, а не по форме выражения.
    """
    out: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(node))
    while stack:
        cur = stack.pop()
        out.append(cur)
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(cur))
    return out


def live_root_names(tree: ast.AST, inherited: frozenset[str] = frozenset(),
                    disposable: frozenset[str] = frozenset()) -> frozenset[str]:
    """Имена, чьё значение происходит от ЖИВОГО корня дерева.

    Якорь — `__file__`: единственное выражение, которое называет дерево, в
    котором прогон идёт. Засев идёт ДО НЕПОДВИЖНОЙ ТОЧКИ (урок ADR-1040:
    привязка через одно имя терялась), а привязка, пришедшая из одноразового
    каталога, НЕ живая и отсекается явно.
    """
    live: set[str] = set(inherited)
    nodes = scope_nodes(tree)
    changed = True
    while changed:
        changed = False
        for node in nodes:
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                targets, value = [node.target], node.value
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                targets, value = [node.optional_vars], node.context_expr
            else:
                continue
            src = ast.unparse(value)
            if _DISPOSABLE.search(src) or (_names(value) & disposable):
                continue
            seeded = "__file__" in src or bool(_names(value) & live)
            if not seeded:
                continue
            for tgt in targets:
                for name in _names(tgt):
                    if name not in live:
                        live.add(name)
                        changed = True
    return frozenset(live)


def disposable_names(tree: ast.AST, inherited: frozenset[str] = frozenset(),
                     makers: frozenset[str] = frozenset()) -> frozenset[str]:
    """Имена, чьё значение происходит от ОДНОРАЗОВОГО каталога.

    Вопрос обязателен и отдельный: без него правило «умолчание прибора живое»
    объявляло живым зов `census.measure(root)` по tempfile-каталогу — то есть
    теряло известного члена со стороны «пробы НЕТ» (замер этого цикла,
    `scripts/forbidden_reach_census.py`). Засев до неподвижной точки той же
    формы, что у живого корня.
    """
    disposable: set[str] = set(inherited)
    nodes = scope_nodes(tree)
    changed = True
    while changed:
        changed = False
        for node in nodes:
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                targets, value = [node.target], node.value
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                targets, value = [node.optional_vars], node.context_expr
            else:
                continue
            src = ast.unparse(value)
            via_maker = any(isinstance(call, ast.Call) and _calls_name(call, makers)
                            for call in ast.walk(value))
            if not (_DISPOSABLE.search(src) or (_names(value) & disposable) or via_maker):
                continue
            for tgt in targets:
                for name in _names(tgt):
                    if name not in disposable:
                        disposable.add(name)
                        changed = True
    return frozenset(disposable)


def helpers_making_disposable(tree: ast.AST) -> frozenset[str]:
    """Помощники файла, из которых выходит ОДНОРАЗОВЫЙ каталог.

    Без этого вопроса одноразовость терялась на ОДНОМ хопе: `tmp = _tree({…})`
    не содержит ни слова `tempfile`, и зов прибора по такому `tmp` объявлялся
    живым — то есть форма объявляла пробу там, где её вычитали отсутствующей
    (`haystack_origin_census`, замер этого цикла). Засев до неподвижной точки:
    помощник помощника тоже дверь.
    """
    reach: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("test_") or node.name in reach:
                continue
            src = ast.unparse(node)
            if _DISPOSABLE.search(src) or any(
                    isinstance(call, ast.Call) and _calls_name(call, reach)
                    for call in ast.walk(node)):
                reach.add(node.name)
                reach.add("self." + node.name)
                changed = True
    return frozenset(reach)


def declared_loop_vars(fn: ast.AST) -> frozenset[str]:
    """Переменные цикла, бегущего по ОБЪЯВЛЕННОМУ перечню известных членов."""
    out: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.For) and _DECLARED_SOURCE.search(ast.unparse(node.iter)):
            out |= _names(node.target)
    return frozenset(out)


# ───────────────────────────── дверь к прибору ────────────────────────────────


def battery_bindings(tree: ast.AST, keys: frozenset[str]) -> tuple[set[str], set[str]]:
    """Имена, через которые батарея зовёт прибор: модульные и поимённые."""
    mods: set[str] = set()
    funcs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in keys:
                    mods.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if base in keys:
                for alias in node.names:
                    funcs.add(alias.asname or alias.name)
            for alias in node.names:
                if f"{base}.{alias.name}" in keys:
                    mods.add(alias.asname or alias.name)
    return mods, funcs


def _dotted(func: ast.AST) -> str:
    chain: list[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        chain.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        chain.append(node.id)
    return ".".join(reversed(chain))


def is_instrument_call(call: ast.Call, mods: set[str], funcs: set[str],
                       path_strs: frozenset[str]) -> bool:
    """Зовёт ли `call` прибор — любой из двух дверей."""
    func = call.func
    if isinstance(func, ast.Attribute):
        dotted = _dotted(func)
        head = dotted.split(".")[0]
        if dotted in mods or head in mods or ".".join(dotted.split(".")[:-1]) in mods:
            return True
    if isinstance(func, ast.Name) and func.id in funcs:
        return True
    for arg in list(call.args) + [kw.value for kw in call.keywords]:
        for sub in ast.walk(arg):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                    and sub.value in path_strs:
                return True
    return False


def subject_live_default_funcs(subject_source: str) -> frozenset[str]:
    """Функции прибора, чей корень ПО УМОЛЧАНИЮ есть живое дерево.

    Без этого вопроса форма теряла известного члена: `_telegram_doors` зовут
    `doors.scan_repo()` БЕЗ аргументов, а живой корень берётся умолчанием
    самого прибора (`root = root or REPO_ROOT`, где `REPO_ROOT` происходит от
    `__file__`). Утверждать за прибор, что умолчание живое, нельзя — поэтому
    умолчание ЧИТАЕТСЯ у него, а не предполагается.
    """
    try:
        tree = ast.parse(subject_source)
    except (SyntaxError, UnicodeDecodeError):
        return frozenset()
    live = live_root_names(tree)
    if not live:
        return frozenset()
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body_names: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                body_names.add(sub.id)
        if body_names & live:
            out.add(node.name)
    return frozenset(out)


def is_live_call(call: ast.Call, live: frozenset[str],
                 live_default_funcs: frozenset[str] = frozenset(),
                 disposable: frozenset[str] = frozenset()) -> bool:
    """Назван ли прибору ЖИВОЙ корень — аргументом либо его же умолчанием.

    Зов без живого аргумента живым считается ТОЛЬКО тогда, когда умолчание
    прочитано у самого прибора (`live_default_funcs`). Пустой перечень
    умолчаний ⇒ такой зов живым НЕ считается: подставить за прибор ответ
    значило бы выдать предположение за замер.
    """
    args = list(call.args) + [kw.value for kw in call.keywords]
    for arg in args:
        if _names(arg) & disposable or _DISPOSABLE.search(ast.unparse(arg)):
            return False
    for arg in args:
        if _names(arg) & live:
            return True
        if "__file__" in ast.unparse(arg):
            return True
    if not live_default_funcs:
        return False
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else (
        func.id if isinstance(func, ast.Name) else None)
    return bool(name) and name in live_default_funcs


def _helpers_reaching_instrument(tree: ast.AST, mods: set[str], funcs: set[str],
                                 path_strs: frozenset[str],
                                 live: frozenset[str],
                                 live_defaults: frozenset[str] = frozenset(),
                                 disposable: frozenset[str] = frozenset(),
                                 makers: frozenset[str] = frozenset()
                                 ) -> frozenset[str]:
    """Помощники файла, через которых идёт ЖИВОЙ зов прибора.

    Без этого шага терялся известный член: сцену и зов строит помощник
    (`_scene(...)`, `self._probe(...)`), а тест видит только его имя. Засев
    идёт до неподвижной точки — помощник помощника тоже дверь.
    """
    reach: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("test_") or node.name in reach:
                continue
            own_disposable = disposable_names(node, disposable, makers)
            own_live = live_root_names(node, live, own_disposable)
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                direct = is_instrument_call(call, mods, funcs, path_strs) \
                    and is_live_call(call, own_live, live_defaults, own_disposable)
                via = _calls_name(call, reach)
                if direct or via:
                    reach.add(node.name)
                    reach.add("self." + node.name)
                    changed = True
                    break
    return frozenset(reach)


class _ClsAsSelf(ast.NodeTransformer):
    """`cls.<имя>` → `self.<имя>`: две формы одной привязки.

    `setUpClass` ставит атрибут на `cls`, а тест читает его через `self` —
    харнесс отдаёт ему ОДНО И ТО ЖЕ значение. Пока две формы считались разными
    именами, засев подготовки не доходил до тела теста ни одним именем.
    """

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == "cls":
            node.value = ast.Name(id="self", ctx=node.value.ctx)
        return node


def _fixture_as_self(fn: ast.AST) -> ast.AST:
    """КОПИЯ подготовки в форме `self.…`.

    Копия, а не правка узла на месте: то же дерево разбирают ещё и другие оси
    (живой корень, одноразовость, помощники), и правка на месте изменила бы их
    ответ — ровно та ловушка «контейнер привязкой НЕ является» (#477), только с
    другой стороны.
    """
    return _ClsAsSelf().visit(copy.deepcopy(fn))


def _attr_forms(names: Iterable[str]) -> frozenset[str]:
    """Имена тела класса — ВМЕСТЕ с их атрибутной формой.

    Привязка, стоящая в теле класса (`box = tempfile.mkdtemp()`), доступна
    методу ТОЛЬКО через атрибут (`cls.box` / `self.box`), а это ДРУГОЕ имя.
    Пока две формы считались разными, одноразовость и живость, объявленные в
    теле класса, до разбора подготовки НЕ ДОХОДИЛИ: зов
    `tc.scan_repo(cls.box)` по tempfile-каталогу объявлялся живым через
    умолчание прибора. Нашла это РАЗЛИЧАЮЩАЯ сцена собственной батареи ДО
    доставки (`…disposable_bound_in_the_class_body…`), а не рассуждение.
    """
    bare = {name for name in names if "." not in name}
    return frozenset(set(names) | {"self." + name for name in bare})


def _class_fixture_seeds(tree: ast.AST, mods: set[str], funcs: set[str],
                         path_strs: frozenset[str], mod_live: frozenset[str],
                         mod_disposable: frozenset[str], makers: frozenset[str],
                         helpers: frozenset[str],
                         live_defaults: frozenset[str] = frozenset(),
                         ) -> dict[ast.AST, frozenset[str]]:
    """Для каждого теста — АТРИБУТЫ, помеченные живым ответом в подготовке.

    Вопрос, который закрывает этот засев (G1044 п. 1, ADR-1057): «зовёт ли
    батарея прибор на ЖИВОМ дереве» — свойство БАТАРЕИ, а не отдельного тела
    `test_*`. Харнесс гарантирует, что `setUpClass` отработал до КАЖДОГО теста
    класса, поэтому живой зов в ней есть такой же живой зов; ограничение
    префиксом `test_` было артефактом засева, и из-за него форма требовала от
    каждого теста СВОЕГО зова — то есть сама производила род обморока по стенным
    часам (цена замерена ADR-1056: ×3 против ×1, 541.4 с против 181.2 с).

    Вывозятся ТОЛЬКО имена вида `self.<имя>`: локальная переменная подготовки
    телу теста не видна, и считать её привязкой значило бы объявить пробой то,
    чего тест прочитать не может.

    ГРАНИЦА, названная вслух: подготовка МОДУЛЯ (`setUpModule`) и помощник
    класса, читающий атрибут подготовки, этим засевом не прослеживаются — ось
    есть ПОВЕРХНОСТЬ, и ошибка её идёт в сторону БОЛЬШЕГО населения (та же
    граница, что у засева помощников).
    """
    seeds: dict[ast.AST, frozenset[str]] = {}
    for cls_node in ast.walk(tree):
        if not isinstance(cls_node, ast.ClassDef):
            continue
        tests = [item for item in cls_node.body
                 if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and item.name.startswith("test_")]
        if not tests:
            continue
        cls_disposable = disposable_names(cls_node, mod_disposable, makers)
        cls_live = live_root_names(cls_node, mod_live, cls_disposable)
        seed: set[str] = set()
        for item in cls_node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name not in FIXTURE_METHODS:
                continue
            fixture = _fixture_as_self(item)
            fx_disposable = disposable_names(
                fixture, _attr_forms(cls_disposable), makers)
            fx_live = live_root_names(
                fixture, _attr_forms(cls_live), fx_disposable)
            tainted = _tainted_by_live_answer(
                fixture, mods, funcs, path_strs, fx_live, helpers,
                live_defaults, fx_disposable)
            seed |= {name for name in tainted if name.startswith("self.")}
        if not seed:
            continue
        frozen = frozenset(seed)
        for item in tests:
            seeds[item] = frozen
    return seeds


def _calls_name(call: ast.Call, names: Iterable[str]) -> bool:
    func = call.func
    names = set(names)
    if isinstance(func, ast.Name) and func.id in names:
        return True
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
            and func.value.id == "self" and ("self." + func.attr) in names:
        return True
    return False


# ───────────────────────────── проба в одной батарее ─────────────────────────


@dataclass(frozen=True)
class Probe:
    """Найденная проба: адрес, форма имени члена и дверь."""

    battery: str
    test: str
    item_form: str
    item: str
    assertion: str


def _test_scopes(tree: ast.AST, mod_live: frozenset[str],
                 mod_disposable: frozenset[str],
                 makers: frozenset[str] = frozenset()):
    """Тест-функции дерева вместе с ОБЪЕМЛЮЩИМИ привязками корня.

    Уровни три — модуль, тело класса, сама функция, — и объемлющий уровень
    наследуется, а не пересчитывается по всему файлу: имя `root` соседнего
    теста к этому тесту отношения не имеет.
    """
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            cls_disposable = disposable_names(node, mod_disposable, makers)
            cls_live = live_root_names(node, mod_live, cls_disposable)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and item.name.startswith("test_"):
                    out.append((item, cls_live, cls_disposable))
    for item in getattr(tree, "body", []):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and item.name.startswith("test_"):
            out.append((item, mod_live, mod_disposable))
    return out


def probes_in_battery(source: str, battery_rel: str, subject_rel: str,
                      subject_source: str = "") -> list[Probe]:
    """Пробы «ЖИВОЕ дерево + ИЗВЕСТНЫЙ член» в ОДНОЙ батарее.

    Поднимается SyntaxError/UnicodeDecodeError наружу — молча вернуть пустой
    список значило бы выдать НЕ ИЗМЕРЕНО за «пробы нет» (инв. #17).
    """
    tree = ast.parse(source)
    keys = subject_keys(subject_rel)
    mods, funcs = battery_bindings(tree, keys)
    path_strs = frozenset({subject_rel, pathlib.PurePath(subject_rel).name})
    makers = helpers_making_disposable(tree)
    mod_disposable = disposable_names(tree, makers=makers)
    mod_live = live_root_names(tree, disposable=mod_disposable)
    live_defaults = subject_live_default_funcs(subject_source)
    helpers = _helpers_reaching_instrument(tree, mods, funcs, path_strs, mod_live,
                                           live_defaults, mod_disposable, makers)
    seeds = _class_fixture_seeds(tree, mods, funcs, path_strs, mod_live,
                                 mod_disposable, makers, helpers, live_defaults)

    found: list[Probe] = []
    for fn, outer_live, outer_disposable in _test_scopes(tree, mod_live,
                                                         mod_disposable, makers):
        disposable = disposable_names(fn, outer_disposable, makers)
        live = live_root_names(fn, outer_live, disposable)
        tainted = _tainted_by_live_answer(fn, mods, funcs, path_strs, live, helpers,
                                          live_defaults, disposable,
                                          seed=seeds.get(fn, frozenset()))
        if not tainted:
            continue
        declared_vars = declared_loop_vars(fn)
        for node in ast.walk(fn):
            claim = _assertion_parts(node)
            if claim is None:
                continue
            if not (_names(claim) & tainted):
                continue
            form = _item_form_outside_answer(claim, tainted, declared_vars)
            if form is None:
                continue
            found.append(Probe(
                battery=battery_rel, test=fn.name, item_form=form,
                item=_first_item_text(claim, tainted, declared_vars),
                assertion=ast.unparse(node)[:160]))
            break
    return found


def _tainted_by_live_answer(fn: ast.AST, mods: set[str], funcs: set[str],
                            path_strs: frozenset[str], live: frozenset[str],
                            helpers: frozenset[str],
                            live_defaults: frozenset[str] = frozenset(),
                            disposable: frozenset[str] = frozenset(),
                            seed: frozenset[str] = frozenset()
                            ) -> frozenset[str]:
    """Имена теста, чьё значение происходит от ЖИВОГО ответа прибора.

    Засев до неподвижной точки: ответ переливают через словарь, срез, помощника
    и распаковку, и мера «имя стои́т прямо в зове» теряла известных членов.

    `seed` — имена, УЖЕ помеченные живым ответом ВНЕ тела теста: атрибуты,
    поставленные классовой подготовкой (`_class_fixture_seeds`). Без них зов,
    стоящий в `setUpClass`, пробой не считался, хотя харнесс гарантирует его
    до каждого теста класса (ADR-1057).
    """
    tainted: set[str] = set(seed)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                targets, value = [node.target], node.value
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                targets, value = [node.optional_vars], node.context_expr
            elif isinstance(node, (ast.For, ast.comprehension)):
                targets, value = [node.target], node.iter
            else:
                continue
            seeded = False
            for call in ast.walk(value):
                if not isinstance(call, ast.Call):
                    continue
                if is_instrument_call(call, mods, funcs, path_strs) \
                        and is_live_call(call, live, live_defaults, disposable):
                    seeded = True
                    break
                if _calls_name(call, helpers):
                    seeded = True
                    break
            if not seeded and (_names(value) & tainted):
                seeded = True
            if not seeded:
                continue
            for tgt in targets:
                for name in _names(tgt):
                    if name not in tainted:
                        tainted.add(name)
                        changed = True
    return frozenset(tainted)


def _assertion_parts(node: ast.AST) -> Optional[ast.AST]:
    """Выражение утверждения, если `node` — утверждение. Иначе None."""
    if isinstance(node, ast.Assert):
        return node.test
    if isinstance(node, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else None)
        if name in _ASSERT_METHODS and node.args:
            return ast.Tuple(elts=list(node.args), ctx=ast.Load())
    return None


def _item_form_outside_answer(claim: ast.AST, tainted: frozenset[str],
                              declared_vars: frozenset[str]) -> Optional[str]:
    """Форма имени члена, НЕ происходящего от ответа прибора.

    Условие «не из ответа» несущее: сверять ответ прибора с его же ответом —
    известный класс дефекта (ADR-913), и такая проба известного члена НЕ
    предъявляет.
    """
    for sub in ast.walk(claim):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if _PATH_ITEM.match(sub.value) or "/" in sub.value:
                return ITEM_PATH
            if _UPPER_ITEM.match(sub.value):
                return ITEM_UPPER
    for sub in ast.walk(claim):
        if isinstance(sub, ast.Name) and sub.id in declared_vars \
                and sub.id not in tainted:
            return ITEM_DECLARED
    for sub in ast.walk(claim):
        name = None
        if isinstance(sub, ast.Attribute):
            name = sub.attr
        elif isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant) \
                and isinstance(sub.slice.value, str):
            name = sub.slice.value
        if name and _DECLARED_SLOT.search(name) and (_names(sub) & tainted):
            return ITEM_DECLARED_SLOT
    return None


def _first_item_text(claim: ast.AST, tainted: frozenset[str],
                     declared_vars: frozenset[str]) -> str:
    for sub in ast.walk(claim):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and (
                _PATH_ITEM.match(sub.value) or "/" in sub.value
                or _UPPER_ITEM.match(sub.value)):
            return sub.value
    for sub in ast.walk(claim):
        if isinstance(sub, ast.Name) and sub.id in declared_vars:
            return sub.id
    for sub in ast.walk(claim):
        if isinstance(sub, ast.Attribute) and _DECLARED_SLOT.search(sub.attr) \
                and (_names(sub) & tainted):
            return sub.attr
        if isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant) \
                and isinstance(sub.slice.value, str) \
                and _DECLARED_SLOT.search(sub.slice.value) and (_names(sub) & tainted):
            return sub.slice.value
    return ""


# ───────────────────────────── батареи прибора ───────────────────────────────


def battery_files(repo_root: pathlib.Path) -> list[str]:
    """Файлы батарей ОБЪЯВЛЕННЫХ каталогов. Пустой список — отказ."""
    out: list[str] = []
    for rel in BATTERY_DIRS:
        base = repo_root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("test_*.py")):
            out.append(str(path.relative_to(repo_root)))
    if not out:
        raise Refused(
            f"батарей не найдено ни в одном объявленном каталоге под {repo_root}: "
            f"{', '.join(BATTERY_DIRS)} — «пробы нет» о таком дереве утверждать нечем")
    return out


def batteries_of(repo_root: pathlib.Path, subjects: Iterable[str],
                 battery_rels: Optional[Iterable[str]] = None
                 ) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """Для каждого прибора — его батареи и ДВЕРЬ каждой.

    Возвращает также перечень НЕ РАЗОБРАННЫХ батарей с причиной: батарея,
    которую не прочитали, не есть батарея, которой нет.
    """
    subjects = list(subjects)
    rels = list(battery_rels) if battery_rels is not None else battery_files(repo_root)
    keymap: dict[str, set[str]] = {}
    for rel in subjects:
        for key in subject_keys(rel):
            keymap.setdefault(key, set()).add(rel)
    basenames = {rel: pathlib.PurePath(rel).name for rel in subjects}

    found: dict[str, dict[str, str]] = {rel: {} for rel in subjects}
    unparsed: dict[str, str] = {}
    for battery in rels:
        path = repo_root / battery
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            unparsed[battery] = f"{type(exc).__name__}: {exc}"
            continue
        literals = {node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for rel in keymap.get(alias.name, ()):
                        found[rel][battery] = DOOR_IMPORT
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                for rel in keymap.get(base, ()):
                    found[rel][battery] = DOOR_IMPORT
                for alias in node.names:
                    for rel in keymap.get(f"{base}.{alias.name}", ()):
                        found[rel][battery] = DOOR_IMPORT
        for rel in subjects:
            if battery in found[rel]:
                continue
            if rel in literals or basenames[rel] in literals:
                found[rel][battery] = DOOR_PATH
    return found, unparsed


# ───────────────────────────── перепись ──────────────────────────────────────


@dataclass(frozen=True)
class Row:
    rel: str
    outcome: str
    rod: Optional[str] = None
    probes: tuple[Probe, ...] = ()
    batteries: tuple[str, ...] = ()
    doors: tuple[str, ...] = ()
    reason: Optional[str] = None


@dataclass
class Census:
    population: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    rods: dict[str, int] = field(default_factory=dict)
    rows: list[Row] = field(default_factory=list)
    unparsed_batteries: dict[str, str] = field(default_factory=dict)
    surface_source: str = ""
    item_forms: dict[str, int] = field(default_factory=dict)


def measure(repo_root, subjects: Iterable[str],
            surface_source: str = "вход") -> Census:
    """Перепись класса по НАЗВАННОМУ перечню приборов.

    `subjects` — вход, а не умолчание: перечень приборов есть поверхность
    соседнего прибора, и выдумывать её здесь значило бы завести ВТОРОЕ
    объявление того же класса.
    """
    root = pathlib.Path(repo_root)
    subjects = sorted(set(subjects))
    if not subjects:
        raise Refused(
            "перечень приборов ПУСТ: о населении класса «прибор без пробы» нечем "
            "ответить, а ноль здесь был бы свойством входа, а не дерева")
    batteries, unparsed = batteries_of(root, subjects)
    census = Census(population=len(subjects), surface_source=surface_source,
                    unparsed_batteries=dict(unparsed))
    for rel in subjects:
        own = batteries.get(rel, {})
        if not (root / rel).exists():
            census.rows.append(Row(rel=rel, outcome=UNMEASURED, rod=SUBJECT_UNPARSED,
                                   reason=f"прибора нет в дереве {root}"))
            continue
        if not own:
            if unparsed:
                # «батареи нет» утверждать нельзя, пока часть батарей не
                # прочитана: дверь импорта у неразобранного файла невидима.
                census.rows.append(Row(
                    rel=rel, outcome=UNMEASURED, rod=BATTERY_UNPARSED,
                    reason="батарея не найдена, но не разобрано "
                           f"{len(unparsed)} файл(ов) батарей: "
                           + "; ".join(f"{b}: {w}" for b, w in
                                       sorted(unparsed.items())[:3])))
                continue
            census.rows.append(Row(rel=rel, outcome=NO_PROBE, rod=BATTERY_ABSENT,
                                   reason="ни одна батарея не ввозит прибор и не "
                                          "называет его путь"))
            continue
        try:
            subject_source = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            census.rows.append(Row(rel=rel, outcome=UNMEASURED, rod=SUBJECT_UNPARSED,
                                   reason=f"{type(exc).__name__}: {exc}"))
            continue
        probes: list[Probe] = []
        bad: list[str] = []
        for battery, _door in sorted(own.items()):
            try:
                source = (root / battery).read_text(encoding="utf-8")
                probes += probes_in_battery(source, battery, rel, subject_source)
            except (OSError, SyntaxError, UnicodeDecodeError) as exc:
                bad.append(f"{battery}: {type(exc).__name__}: {exc}")
        if probes:
            census.rows.append(Row(rel=rel, outcome=HAS_PROBE,
                                   probes=tuple(probes),
                                   batteries=tuple(sorted(own)),
                                   doors=tuple(sorted(set(own.values())))))
        elif bad:
            census.rows.append(Row(rel=rel, outcome=UNMEASURED, rod=BATTERY_UNPARSED,
                                   batteries=tuple(sorted(own)),
                                   reason="; ".join(bad)))
        elif unparsed:
            census.rows.append(Row(
                rel=rel, outcome=UNMEASURED, rod=BATTERY_UNPARSED,
                batteries=tuple(sorted(own)),
                reason="пробы в прочитанных батареях нет, но не разобрано "
                       f"{len(unparsed)} файл(ов): "
                       + "; ".join(f"{b}: {w}" for b, w in
                                   sorted(unparsed.items())[:3])))
        else:
            census.rows.append(Row(rel=rel, outcome=NO_PROBE,
                                   rod=BATTERY_WITHOUT_PROBE,
                                   batteries=tuple(sorted(own)),
                                   doors=tuple(sorted(set(own.values()))),
                                   reason="батарея есть, живого зова с названным "
                                          "членом в ней нет"))
    census.counts = {outcome: sum(1 for r in census.rows if r.outcome == outcome)
                     for outcome in OUTCOMES}
    census.rods = {rod: sum(1 for r in census.rows if r.rod == rod)
                   for rod in NO_PROBE_RODS + UNMEASURED_RODS}
    census.item_forms = {form: sum(1 for r in census.rows for p in r.probes
                                   if p.item_form == form) for form in ITEM_FORMS}
    if sum(census.counts.values()) != census.population:
        raise Refused(
            f"сумма исходов {sum(census.counts.values())} не равна населению "
            f"{census.population} — перечень исходов не замкнут (инв. #17)")
    return census


# ───────────────────────────── поверхность (вход) ─────────────────────────────

#: Перепись поверхности класса «прибор, объявляющий вердикт о населении»
#: (ADR-935). Берётся у источника ЗОВОМ, а не копией перечня: копии нечем
#: состариться вместе с источником, и перепись хвалила бы охват, которого
#: больше нет.
SURFACE_TOOL = "spa_core/tests/_population_verdict_surface.py"


def surface_subjects(repo_root, timeout_s: float = 600.0) -> tuple[list[str], str]:
    """Приборы НАЗВАННОГО дерева: его собственная перепись поверхности.

    Зов подпроцессом, а не импорт: ввоз чужого модуля взял бы код из
    `sys.path`, то есть ответил бы о СВОЁМ дереве под видом ответа о названном
    (урок ADR-796). Тест-модули из поверхности ИСКЛЮЧЕНЫ и это сказано вслух:
    у теста батареи не бывает по устройству — он ею и является.
    """
    root = pathlib.Path(repo_root)
    tool = root / SURFACE_TOOL
    if not tool.exists():
        raise Refused(
            f"поверхность НЕ ПРОЧИТАНА: {SURFACE_TOOL} нет в дереве {root} — "
            "перечень приборов выдумывать здесь запрещено")
    try:
        proc = subprocess.run(
            [sys.executable, str(tool), "--repo-root", str(root), "--json"],
            capture_output=True, text=True, timeout=timeout_s,
            env={**os.environ})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refused(f"поверхность НЕ ПРОЧИТАНА: {type(exc).__name__}: {exc}") from exc
    if proc.returncode not in (0, 1):
        raise Refused(
            f"поверхность НЕ ПРОЧИТАНА: {SURFACE_TOOL} вышел кодом "
            f"{proc.returncode}: {(proc.stderr or '').strip()[:300]}")
    try:
        doc = json.loads(proc.stdout)
    except (ValueError, TypeError) as exc:
        raise Refused(
            f"поверхность НЕ ПРОЧИТАНА: ответ {SURFACE_TOOL} не разобран "
            f"({type(exc).__name__})") from exc
    everyone = set(doc.get("candidates") or ()) | set(doc.get("declared") or ())
    if not everyone:
        raise Refused(
            "поверхность ПУСТА: перепись приборов не назвала ни одного — "
            "«приборов без пробы 0» было бы свойством входа, а не дерева")
    subjects = [rel for rel in sorted(everyone)
                if not pathlib.PurePath(rel).name.startswith("test_")]
    return subjects, SURFACE_TOOL


# ───────────────────────────── калибровка формы ──────────────────────────────

#: ИЗВЕСТНЫЕ члены по обе стороны. Каждый вычитан РУКАМИ, и адрес назван:
#: форма, потерявшая известного члена, мерой класса не является (G1029 п. 2).
#:
#: Сторона «проба ЕСТЬ» — три адреса, и третий намеренно ВНЕ поверхности:
#: `observation_channel_env_census` объявляет исходы туплами, поэтому
#: `_population_verdict_surface` его не находит, а детектор обязан находить.
KNOWN_WITH_PROBE: dict[str, str] = {
    "spa_core/tests/_tracker_content_door.py":
        "spa_core/tests/test_tracker_content_door_census.py::"
        "test_both_known_members_are_on_the_surface_with_their_door — "
        "`d.measure_surface(_REPO)` + assertIn по KNOWN_MEMBERS",
    "spa_core/monitoring/timeout_door_census.py":
        "spa_core/tests/test_timeout_door_census.py::"
        "test_the_instrument_does_not_become_its_own_finding — живое дерево "
        "`Path(tdc.__file__).resolve().parents[2]` + названный сосед "
        "`_artifact_stamp_clock_probe.py`",
    "spa_core/monitoring/census_consumer_census.py":
        "spa_core/tests/test_census_consumer_census.py::"
        "test_the_bridge_is_among_the_by_name_consumers — `live_measure()` "
        "по живому дереву + assertIn('spa_core/monitoring/findings_bridge.py')",
    "spa_core/tests/_telegram_doors.py":
        "spa_core/tests/test_telegram_doors_single_guard.py::"
        "test_every_known_door_is_still_visible — `doors.scan_repo()` БЕЗ "
        "аргументов (живой корень умолчанием прибора) + assertIn по KNOWN_DOORS",
    "spa_core/tests/_population_verdict_surface.py":
        "spa_core/tests/test_population_verdict_surface.py::"
        "test_every_declared_instrument_of_the_live_tree_is_in_form — "
        "`pvs.measure(живой корень)` + assertEqual([], census."
        "declared_outside_form): ось известных членов названа ПРИБОРОМ",
    "spa_core/monitoring/observation_channel_env_census.py":
        "spa_core/tests/test_observation_channel_env_census.py::"
        "test_the_surface_finds_every_known_member_of_the_class — "
        "`oc.census(_REPO_ROOT)` + assertIn по KNOWN (ADR-1040)",
}

#: Сторона «пробы НЕТ» — вычитана руками по той же мерке: в батарее ни одного
#: зова прибора о ЖИВОМ дереве, все сцены одноразовые.
KNOWN_WITHOUT_PROBE: dict[str, str] = {
    "scripts/forbidden_reach_census.py":
        "scripts/tests/test_forbidden_reach_census.py — все 14 зовов "
        "`census.measure(root)` идут по tempfile-каталогу; живого корня "
        "(_REPO) батарея касается только для sys.path",
    "spa_core/monitoring/haystack_origin_census.py":
        "spa_core/tests/test_haystack_origin_census.py — все зовы "
        "`H.measure(Path(tmp.name))` идут по tempfile-каталогу; живой "
        "`REPO_ROOT` служит только адресом фикстурного исходника",
}


def calibrate(repo_root, rows_by_rel: dict[str, Row]) -> dict[str, list[str]]:
    """Предъявить ИЗВЕСТНЫХ членов по обе стороны — ДО печати населения.

    Возвращает перечень расхождений. Непустой перечень означает, что форма
    ОПРОВЕРГНУТА: звать её мерой класса нельзя.
    """
    lost: list[str] = []
    for rel, address in sorted(KNOWN_WITH_PROBE.items()):
        row = rows_by_rel.get(rel)
        if row is None:
            lost.append(f"{rel}: известный НЕ-член вне переписи (проба: {address})")
        elif row.outcome != HAS_PROBE:
            lost.append(f"{rel}: форма не нашла ИЗВЕСТНОЙ пробы ({address}) — "
                        f"исход {row.outcome}/{row.rod}")
    for rel, why in sorted(KNOWN_WITHOUT_PROBE.items()):
        row = rows_by_rel.get(rel)
        if row is None:
            lost.append(f"{rel}: известный член вне переписи ({why})")
        elif row.outcome != NO_PROBE:
            lost.append(f"{rel}: форма объявила пробу там, где её вычитали "
                        f"отсутствующей ({why}) — исход {row.outcome}")
    return {"lost": lost}


def calibrated_measure(repo_root, subjects: Optional[Iterable[str]] = None) -> Census:
    """Перепись, которая ОТКАЗЫВАЕТ, пока известные члены не предъявлены.

    Это и есть исполнение правила G1029 п. 2 на самом себе: прибор, печатающий
    население класса без предъявления известного члена, был бы ровно тем
    дефектом, который он мерит.
    """
    root = pathlib.Path(repo_root)
    if subjects is None:
        subjects, source = surface_subjects(root)
    else:
        subjects, source = list(subjects), "вход"
    extra = [rel for rel in list(KNOWN_WITH_PROBE) + list(KNOWN_WITHOUT_PROBE)
             if rel not in subjects and (root / rel).exists()]
    census = measure(root, list(subjects) + extra, surface_source=source)
    by_rel = {row.rel: row for row in census.rows}
    verdict = calibrate(root, by_rel)
    if verdict["lost"]:
        raise Refused(
            "ФОРМА ОПРОВЕРГНУТА известными членами — население НЕ ПЕЧАТАЕТСЯ:\n  "
            + "\n  ".join(verdict["lost"]))
    # приборы, добавленные ТОЛЬКО ради калибровки, из населения вычитаются:
    # иначе число отвечало бы о поверхности плюс мой список, а не о поверхности.
    if extra:
        census.rows = [row for row in census.rows if row.rel not in set(extra)]
        census.population = len(census.rows)
        census.counts = {o: sum(1 for r in census.rows if r.outcome == o)
                         for o in OUTCOMES}
        census.rods = {rod: sum(1 for r in census.rows if r.rod == rod)
                       for rod in NO_PROBE_RODS + UNMEASURED_RODS}
        census.item_forms = {f: sum(1 for r in census.rows for p in r.probes
                                    if p.item_form == f) for f in ITEM_FORMS}
    return census


# ───────────────────────────── отчёт ─────────────────────────────────────────


def as_json(census: Census) -> dict:
    return {
        "schema": "spa-known-member-probe-census/1",
        "population": census.population,
        "counts": dict(census.counts),
        "rods": dict(census.rods),
        "item_forms": dict(census.item_forms),
        "surface_source": census.surface_source,
        "unparsed_batteries": dict(census.unparsed_batteries),
        "rows": [
            {
                "rel": row.rel, "outcome": row.outcome, "rod": row.rod,
                "batteries": list(row.batteries), "doors": list(row.doors),
                "reason": row.reason,
                "probes": [
                    {"battery": p.battery, "test": p.test,
                     "item_form": p.item_form, "item": p.item,
                     "assertion": p.assertion}
                    for p in row.probes
                ],
            }
            for row in census.rows
        ],
    }


def format_report(census: Census, limit: int = 20) -> str:
    """Человеческая строка. Ноль НИКОГДА не печатается как «чисто»."""
    lines = [
        f"приборов без пробы «ЖИВОЕ дерево + ИЗВЕСТНЫЙ член»: "
        f"{census.counts.get(NO_PROBE, 0)} из {census.population} "
        f"(поверхность: {census.surface_source})",
        f"  исходы: проба есть {census.counts.get(HAS_PROBE, 0)} · "
        f"пробы нет {census.counts.get(NO_PROBE, 0)} "
        f"(батареи нет вовсе {census.rods.get(BATTERY_ABSENT, 0)} · "
        f"батарея без пробы {census.rods.get(BATTERY_WITHOUT_PROBE, 0)}) · "
        f"НЕ ИЗМЕРЕНО {census.counts.get(UNMEASURED, 0)}",
        f"  формы имени члена у найденных проб: "
        + " · ".join(f"{form} {census.item_forms.get(form, 0)}" for form in ITEM_FORMS),
        "  ⚠️ ответ есть ВЕРХНЯЯ граница класса: форма пробы закрыта перечнями, "
        "и настоящая проба в неузнанной форме попадает в «пробы нет»",
    ]
    if census.unparsed_batteries:
        lines.append(f"  НЕ ИЗМЕРЕНО (батарей не разобрано): "
                     f"{len(census.unparsed_batteries)}")
        for battery, why in sorted(census.unparsed_batteries.items())[:5]:
            lines.append(f"     {battery} — {why}")
    members = [row for row in census.rows if row.outcome == NO_PROBE]
    for row in members[:limit]:
        lines.append(f"  [{row.rod}] {row.rel} — {row.reason}")
    if len(members) > limit:
        lines.append(f"  … и ещё {len(members) - limit} поимённо в `rows`")
    lines.append("  ADVISORY: прибор только ЧИТАЕТ дерево и ничего не чинит")
    return "\n".join(lines)
