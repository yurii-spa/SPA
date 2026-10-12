"""Объявленный путь `_READ_SCHEMA`, которого фикстура соседа НЕ НЕСЁТ.

# LLM_FORBIDDEN

Заказ **G697 п. 2** приказа владельца «Portfolio CIO» — дословный хвост
ADR-697:

    «Класс "объявленный ключ без ЗНАЧЕНИЯ в фикстуре соседа" повторился
    ЧЕТВЁРТЫЙ раз — мерить население, а не чинить по одному. #832, #834, #837
    и этот цикл платили одним и тем же: раздел объявляется читаемым у шага
    0-офис, сосед его не получает, и чужая сцена краснеет не о своём предмете.
    Четыре случая — это уже не совпадение, а форма. Замерить: сколько путей
    `_READ_SCHEMA` сегодня НЕ несут значения ни в одной фикстуре, которая
    строит документ того же производителя. Есть население ⇒ храповик (база
    только вниз); нет ⇒ записать и закрыть.»

## Что именно мерится — и почему НЕ «все словари в файле»

Вред случается у ОДНОЙ двери: тест отдаёт свой документ читателю офиса
(`consume_office_reports._summarize_json(<имя артефакта>, doc, …)`), а тот
первым делом считает `_schema_drift` — пути `_READ_SCHEMA`, которых в
документе нет. Поэтому населением класса является не «словарь, похожий на
отчёт», а **площадка вызова этой двери**: пара «тест × артефакт», у которой
документ до двери доезжает, а объявленного пути в нём нет.

Первая, отброшенная редакция мерки искала словари-литералы по пересечению
ключей с объявленными и ошибалась грубо: у `pre_trade_recheck_census.json`
«документом» оказался словарь циферблатов соседнего зонда, совпавший одним
ключом `tolerance_s`, и все 21 путь артефакта объявлялись ненесомыми. Мера по
ДВЕРИ такой ошибки не допускает по построению: документ берётся тот, который
дверь и получает.

## Поток значения, а не подстрока

Документ почти никогда не стои́т в аргументе литералом: его собирает помощник
(`self._doc()`), а внутри — имя (`counts = {...}`), и у помощника бывает
несколько `return`. Поэтому аргумент РАЗРЕШАЕТСЯ по потоку значения: словарь →
имя (объединение всех его присваиваний) → вызов помощника того же файла
(объединение всех его `return`) → `dict(...)` / `{**base, …}`. Глубина
ограничена; предел — свой третий исход, а не «полей нет».

Объединение здесь не небрежность: `counts.update(over)` и ветки `if` дают
несколько присваиваний одному имени, и фикстура считается несущей путь, если
его несёт хотя бы одна ветка. Обратная мерка (пересечение) объявила бы
находкой намеренный отрицательный контроль («документ БЕЗ раздела»).

## Три исхода, и третий называется вслух

| исход | что наблюдалось | что печатается |
|---|---|---|
| площадка | имя артефакта и документ разрешены | объявленные пути, которых нет |
| НЕ ИЗМЕРЕНО | имя артефакта не разрешается (переменная, которой нет в файле) | причина `artifact_name_unresolved` |
| НЕ ИЗМЕРЕНО | документ не разрешается до словаря | причина `doc_unresolved:<почему>` |
| НЕ ИЗМЕРЕНО | файл не разобран | причина `file_unparsed:<ошибка>` |
| вне предмета | имя разрешено, но в `_READ_SCHEMA` его нет | `name_not_declared` — стеречь нечего |

«НЕ ИЗМЕРЕНО» никогда не сворачивается в «путей не хватает 0»: это ровно та
подмена, против которой инвариант #17.

## Намеренно минимальная фикстура — освобождение С ПРИЧИНОЙ

Часть площадок кормит дверь куцым документом ПО ПРЕДМЕТУ: ветка возраста,
generic-ветка, сцена «раздела нет ⇒ отчёт старого образца». Дописать им поля
значило бы сломать их предмет. Для них есть пометка в исходнике —
``# SCHEMA-GAP-OK: <причина>`` на строке вызова или в теле её функции, — и
освобождение ВИДНО и СЧИТАЕТСЯ. Пометка без причины освобождением НЕ является
(тот же порядок, что у `FROZEN-DATE-OK`): она попадает в население и
называется отдельной строкой.

## Чего мера НЕ говорит

* **Не говорит, что площадка КРАСНЕЕТ сегодня.** `_schema_drift` различает
  «производитель поле не пишет» и «отчёт старого образца», и вторая форма
  печатается без находки. Население здесь — ЛАТЕНТНОЕ: оно обращается в
  красный тест только у сцен, пришпиливающих вывод целиком (так и покраснели
  #832/#834/#837/#841).
* **Не мерит артефакты без площадки.** Производитель, чей документ в тестах
  собирается прогоном самого производителя, в население не входит: фикстуры у
  него нет, и объявлять ей нечего.
* **Не судит о правдивости схемы.** Обратный вопрос — «ветка читает поле, а
  схема молчит» — мерит СОСЕД `_office_read_sites.py` (заказ #563), и у него
  ДРУГОЕ население: он идёт от чтений ветки, эта мера — от объявленных путей к
  фикстурам. Два ответа не заменяют друг друга и не сравниваются.
"""

from __future__ import annotations

import ast
import importlib
import os
import re
from dataclasses import dataclass, field

#: Дверь: читатель офиса, у которого и считается `_schema_drift`.
DOOR = "_summarize_json"

#: Заглушка листа. `_has_path` спрашивает «ЕСТЬ ли поле», не «истинно ли оно»,
#: поэтому значение листа мере безразлично — важно лишь, что ключ есть.
LEAF = "<leaf>"

#: Предел глубины разрешения потока. Упёрлись — третий исход, а не «нет поля».
MAX_DEPTH = 12

#: Освобождение намеренно куцей фикстуры. Причина ОБЯЗАТЕЛЬНА.
_EXEMPT_RE = re.compile(r"#\s*SCHEMA-GAP-OK\s*:\s*(?P<why>\S.*?)\s*$")
_EXEMPT_BARE_RE = re.compile(r"#\s*SCHEMA-GAP-OK\s*:?\s*$")

#: Причины, по которым документ до словаря-литерала не доводится ПО ПРИРОДЕ
#: выражения, а не из-за слабости разбора: его собрал ВЫЗОВ.
#:
#: `receiver_not_self` и `self_outside_class` добавлены заказом G699 п. 2 и
#: суть та же природа: тело зовомого в этом файле не опознаётся, значит
#: словаря-фикстуры у площадки нет. Причины НАЗВАНЫ врозь нарочно — так цена
#: отказа от одалживания считается в `census.built_by_call`, а не растворяется
#: в общем «вызов не разрешён».
_BUILT_BY_CALL = frozenset({"call_unresolved", "helper_returns_no_dict",
                            "receiver_not_self", "self_outside_class"})

#: Каталоги тестов — предмет замера. Передаются ВХОДОМ, здесь только умолчание.
DEFAULT_TEST_DIRS = ("spa_core/tests", "tests", "scripts/tests")


@dataclass(frozen=True)
class Site:
    """Площадка: один вызов двери с разрешённым именем и документом."""

    file: str
    line: int
    artifact: str
    missing: tuple[str, ...]
    declared: int
    exempt_reason: str | None = None

    @property
    def key(self) -> str:
        return f"{self.file}::{self.artifact}"


@dataclass
class Census:
    files_scanned: int = 0
    sites: list[Site] = field(default_factory=list)
    out_of_subject: list[tuple[str, int, str]] = field(default_factory=list)
    built_by_call: list[tuple[str, str]] = field(default_factory=list)
    unmeasured: list[tuple[str, str]] = field(default_factory=list)
    marker_without_reason: list[tuple[str, int]] = field(default_factory=list)

    @property
    def population(self) -> list[Site]:
        """Площадки класса: путь объявлен, фикстура его не несёт, не освобождены."""
        return [s for s in self.sites if s.missing and not s.exempt_reason]

    @property
    def exempt(self) -> list[Site]:
        return [s for s in self.sites if s.missing and s.exempt_reason]

    @property
    def pairs(self) -> int:
        """Пар «площадка × объявленный путь» без значения."""
        return sum(len(s.missing) for s in self.population)

    def by_key(self) -> dict[str, int]:
        """Ключ «файл::артефакт» → сколько РАЗНЫХ путей не несёт ни одна его
        площадка.

        Объединение, а не сумма: один и тот же артефакт кормится из файла по
        нескольку раз (у `loop_health.json` — семь площадок с одним и тем же
        куцым документом), и сумма меняла бы число от переноса строки, а не от
        предмета.
        """
        out: dict[str, set[str]] = {}
        for s in self.population:
            out.setdefault(s.key, set()).update(s.missing)
        return {k: len(v) for k, v in sorted(out.items())}

    def missing_by_key(self) -> dict[str, tuple[str, ...]]:
        out: dict[str, set[str]] = {}
        for s in self.population:
            out.setdefault(s.key, set()).update(s.missing)
        return {k: tuple(sorted(v)) for k, v in sorted(out.items())}


def _merge(dst: dict, src: dict) -> None:
    """Объединение ветвей — ГЛУБОКОЕ: «несёт хотя бы одна ветка».

    Плоский `dict.update` отвечал на другой вопрос: ветка с `counts: {}`
    СТИРАЛА богатый `counts` соседней ветки, и ответ зависел от ПОРЯДКА
    присваиваний, а не от предмета (замер ADR-699: у
    `test_list_identity_census_wiring.py::_text` так исчезали все 17 путей
    `counts.*`, которые полная фикстура несёт). Вопрос меры — «есть ли поле
    хоть у одной ветки», и глубокое слияние есть ровно он.

    Лист против словаря: словарь богаче и остаётся — он несёт пути глубже.
    """
    for key, value in src.items():
        have = dst.get(key)
        if isinstance(have, dict) and isinstance(value, dict):
            _merge(have, value)
        elif isinstance(have, dict):
            continue
        else:
            dst[key] = value


def _assigns_of(scope: ast.AST) -> dict[str, list[ast.AST]]:
    """Присваивания СВОЕЙ области: тело `scope` без вложенных функций и классов.

    Граница области и есть предмет: обход, спускающийся во вложенные тела,
    выдаёт за видимое то, что из `scope` голым именем не видно.
    """
    out: dict[str, list[ast.AST]] = {}

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Assign):
                for tgt in child.targets:
                    if isinstance(tgt, ast.Name):
                        out.setdefault(tgt.id, []).append(child.value)
            elif (isinstance(child, ast.AnnAssign)
                  and isinstance(child.target, ast.Name)
                  and child.value is not None):
                out.setdefault(child.target.id, []).append(child.value)
            walk(child)

    walk(scope)
    return out


def _enclosing_funcs(tree: ast.Module) -> dict[int, ast.AST]:
    """Строка → ближайшая объемлющая функция (самая внутренняя из объемлющих)."""
    owner: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            line = getattr(inner, "lineno", None)
            if line is None:
                continue
            prev = owner.get(line)
            if prev is None or node.lineno > prev.lineno:
                owner[line] = node
    return owner


def _enclosing_classes(tree: ast.Module) -> dict[int, ast.ClassDef]:
    """Строка → ближайший объемлющий КЛАСС (самый внутренний из объемлющих).

    Нужен затем же, зачем `_enclosing_funcs` понадобился присваиваниям: имя
    метода принадлежит КЛАССУ, и разрешать его по файлу значит одалживать
    (заказ G699 п. 2).
    """
    owner: dict[int, ast.ClassDef] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for inner in ast.walk(node):
            line = getattr(inner, "lineno", None)
            if line is None:
                continue
            prev = owner.get(line)
            if prev is None or node.lineno > prev.lineno:
                owner[line] = node
    return owner


def _parents(tree: ast.Module) -> dict[int, ast.AST]:
    """Узел → его НЕПОСРЕДСТВЕННЫЙ родитель.

    Метод отличается от вложенной функции именно родителем, а не объемлющим
    классом: `def _h()` внутри метода класса `C` объемлется `C`, но методом
    `C` НЕ является и голым именем из соседнего метода не виден.
    """
    out: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[id(child)] = node
    return out


class _ModuleFlow:
    """Разрешение выражения в скелет словаря — по потоку значения внутри файла."""

    def __init__(self, tree: ast.Module, aliases: dict[str, str]):
        self.aliases = aliases
        # Определения разводятся по ВЛАДЕЛЬЦУ, а не по имени (заказ G699 п. 2):
        # метод живёт у пары «класс × имя», свободная функция — у имени.
        parents = _parents(tree)
        self._classes = _enclosing_classes(tree)
        self._class_by_name: dict[str, ast.ClassDef] = {}
        self._methods: dict[tuple[int, str], list[ast.AST]] = {}
        self._free_funcs: dict[str, list[ast.AST]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self._class_by_name.setdefault(node.name, node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owner = parents.get(id(node))
                if isinstance(owner, ast.ClassDef):
                    self._methods.setdefault((id(owner), node.name), []).append(node)
                else:
                    self._free_funcs.setdefault(node.name, []).append(node)
        self._module_assigns = _assigns_of(tree)
        self._func_assigns: dict[int, dict[str, list[ast.AST]]] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._func_assigns[id(node)] = _assigns_of(node)
        self.assigns: dict[str, list[ast.AST]] = dict(self._module_assigns)
        self._scope_func: ast.AST | None = None
        self._owners = _enclosing_funcs(tree)
        #: КОНКРЕТНОЕ определение → его вызовы вместе с областью зова.
        #: Нужен, чтобы ПАРАМЕТР разрешался у ВЫЗЫВАЮЩЕГО (заказ G698 п. 2).
        #:
        #: Ключ — определение, а НЕ имя: прежняя редакция спрашивала
        #: `self.calls.get(func.name)`, и это было ТО ЖЕ объединение по имени,
        #: что у `self.funcs`, только у второй двери (заказ G699 п. 2 назвал
        #: одну из двух; вторая найдена этим ходом). У `setUp`, определённого
        #: в файле семь раз, параметр помощника разрешался аргументами ВСЕХ
        #: семи вызовов — ровно одалживание, против которого введена область.
        self.calls: dict[int, list[tuple[ast.Call, ast.AST | None]]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            defs, _why = self.target_defs(node)
            for fdef in defs or ():
                self.calls.setdefault(id(fdef), []).append(
                    (node, self._owners.get(node.lineno)))

    def _lookup_method(self, cls: ast.ClassDef, name: str,
                       seen: tuple[int, ...] = ()) -> list[ast.AST] | None:
        """Метод по паре «класс × имя», затем по базам, объявленным В ФАЙЛЕ.

        Строгое «только свой класс» потеряло бы наследование: сцена-потомок
        зовёт `self._doc()`, определённый у базы, и объявить его ненайденным
        значило бы купить исправление потерей зрения. База вне файла
        (`unittest.TestCase`) честно не находится — документ собрал вызов.
        """
        if id(cls) in seen:
            return None
        defs = self._methods.get((id(cls), name))
        if defs:
            return defs
        for base in cls.bases:
            bname = base.id if isinstance(base, ast.Name) else (
                base.attr if isinstance(base, ast.Attribute) else None)
            parent = self._class_by_name.get(bname) if bname else None
            if parent is None:
                continue
            found = self._lookup_method(parent, name, seen + (id(cls),))
            if found:
                return found
        return None

    def target_defs(self, node: ast.Call) -> tuple[list[ast.AST] | None, str | None]:
        """Определения, которые ДЕЙСТВИТЕЛЬНО зовёт этот вызов.

        Одно правило на обе двери (разрешение зовомого и разрешение
        вызывающего), и второй его копии нет: две копии разошлись бы молча.

        | форма вызова | чем разрешается |
        |---|---|
        | `f(...)` | свободные функции файла — метод голым именем не виден |
        | `self.f(...)` / `cls.f(...)` | пара «класс площадки × имя» + базы в файле |
        | `C.f(...)`, `C` — класс ФАЙЛА | пара «этот класс × имя» |
        | `mod.f(...)`, `mod` — импорт | тело вне файла ⇒ `call_unresolved` |
        | `other.f(...)` | получатель неизвестен ⇒ `receiver_not_self` |

        Последние две строки РАЗВЕДЕНЫ нарочно, и это не косметика: модуль —
        это «тела здесь нет по природе» (так `json.loads(raw)` и
        `producer.run()` отвечали с ADR-698), а неизвестный объект — «тело,
        может быть, и здесь, но КОТОРОЕ из одноимённых, статике не дано».
        Свернуть их в одну причину значило бы потерять различие между
        отсутствием предмета и отказом одалживать. Одалживать же
        неизвестному получателю любой одноимённый метод файла — ровно тот
        вред, который мерит заказ G699 п. 2, поэтому исход НАЗВАН, чтобы
        цена считалась в `census.built_by_call`, а не растворилась.
        """
        func = node.func
        if isinstance(func, ast.Name):
            return self._free_funcs.get(func.id), None
        if not isinstance(func, ast.Attribute):
            return None, "call_unresolved"
        receiver = func.value
        if not isinstance(receiver, ast.Name):
            return None, "receiver_not_self"
        if receiver.id in ("self", "cls"):
            cls = self._classes.get(node.lineno)
            if cls is None:
                return None, "self_outside_class"
            return self._lookup_method(cls, func.attr), None
        own = self._class_by_name.get(receiver.id)
        if own is not None:
            return self._lookup_method(own, func.attr), None
        if receiver.id in self.aliases:
            return None, "call_unresolved"
        return None, "receiver_not_self"

    def scope_to(self, func: ast.AST | None) -> None:
        """Связать имена так, как их связывает PYTHON — не весь файл.

        Прежняя редакция собирала `assigns` обходом ВСЕГО модуля, и имя `doc`
        объединяло присваивания из ВСЕХ функций файла. У той формы два вреда,
        и оба измерены (ADR-699): чужой словарь объявлялся документом площадки,
        которая его не видит (ЛОЖНАЯ находка — три площадки `_health.json`
        числились «не несёт 7 из 7», тогда как их настоящая фикстура
        `HEALTH_REAL` несёт все семь), и наоборот — богатый сосед ОДАЛЖИВАЛ
        куцей площадке свои ключи, пряча настоящий пробел.

        Область берётся по правилам языка: своя функция плюс уровень модуля.
        Тело класса СЮДА НЕ ВХОДИТ — имя, присвоенное в теле класса, из метода
        голым именем не видно (`NameError`), и считать его видимым значило бы
        вернуть то же одалживание под другим именем.
        """
        self.assigns = dict(self._module_assigns)
        self._scope_func = func
        own = self._func_assigns.get(id(func)) if func is not None else None
        if own:
            for name, values in own.items():
                self.assigns[name] = values

    def _params(self, func: ast.AST) -> list[str]:
        a = func.args
        return [arg.arg for arg in (*a.posonlyargs, *a.args)]

    def _from_callers(self, param: str, depth: int, seen: tuple[str, ...]
                      ) -> tuple[dict | None, str | None]:
        """Значение ПАРАМЕТРА решает ВЫЗЫВАЮЩИЙ — спросить у него (G698 п. 2).

        Документ редко стои́т у двери литералом: сцена зовёт помощника
        (`self._render(self._doc())`), и внутри помощника имя — параметр,
        не присваивание. Областное связывание такое имя честно объявляет
        несвязанным, и остановиться здесь значило бы назвать «НЕ ИЗМЕРЕНО»
        ровно то, что статике ДАЁТСЯ: у помощника вызовов одна-две, и
        аргумент в них стои́т явно.

        Разрешение идёт в области ВЫЗЫВАЮЩЕГО, а не помощника: аргумент
        написан там, и связать его именами помощника значило бы повторить
        одалживание, против которого введена область.
        """
        func = self._scope_func
        if func is None or not isinstance(func, (ast.FunctionDef,
                                                 ast.AsyncFunctionDef)):
            return None, "name_unbound"
        params = self._params(func)
        if param not in params:
            return None, "name_unbound"
        index = params.index(param)
        # Вызовы ЭТОГО определения, а не всех одноимённых (заказ G699 п. 2).
        sites = self.calls.get(id(func)) or []
        if not sites:
            return None, "param_no_call_site"
        merged: dict = {}
        why: str | None = None
        got = False
        saved_assigns, saved_func = self.assigns, self._scope_func
        try:
            for call, caller in sites:
                bound = self._argument(call, index, params)
                if bound is None:
                    why = why or "param_not_bound_at_call"
                    continue
                self.scope_to(caller)
                sub, sub_why = self.skeleton(
                    bound, depth + 1, seen + ((id(func), param),))
                if sub is not None:
                    _merge(merged, sub)
                    got = True
                elif why is None:
                    why = sub_why
        finally:
            self.assigns, self._scope_func = saved_assigns, saved_func
        if got:
            return merged, why
        return None, why or "param_unresolved"

    @staticmethod
    def _argument(call: ast.Call, index: int, params: list[str]) -> ast.AST | None:
        """Аргумент, вставший на место параметра №`index`.

        `self` при вызове методом не передаётся позиционно, поэтому смещение
        читается из ФОРМЫ вызова, а не угадывается: `X.f(a)` связывает `a` со
        вторым параметром, `f(a)` — с первым.
        """
        offset = 1 if (isinstance(call.func, ast.Attribute)
                       and params and params[0] in ("self", "cls")) else 0
        position = index - offset
        if 0 <= position < len(call.args):
            arg = call.args[position]
            return None if isinstance(arg, ast.Starred) else arg
        for kw in call.keywords:
            if kw.arg == params[index]:
                return kw.value
        return None

    # --- имя артефакта ---------------------------------------------------
    def text(self, node: ast.AST, depth: int = 0) -> str | None:
        """Строка аргумента-пути: литерал, имя, f-строка, `mod.ATTR`, `a / b`."""
        if depth > MAX_DEPTH:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            for value in self.assigns.get(node.id, []):
                got = self.text(value, depth + 1)
                if got:
                    return got
            return None
        if isinstance(node, ast.Attribute):
            return self._module_attr(node, depth)
        if isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    parts.append(part.value)
                elif isinstance(part, ast.FormattedValue):
                    got = self.text(part.value, depth + 1)
                    if got is None:
                        return None
                    parts.append(got)
                else:
                    return None
            return "".join(parts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            # `data / mod.ARTIFACT` — имя файла несёт ПРАВЫЙ операнд.
            return self.text(node.right, depth + 1)
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else None)
            if name == "str" and len(node.args) == 1:
                return self.text(node.args[0], depth + 1)
            return None
        return None

    def _module_attr(self, node: ast.Attribute, depth: int) -> str | None:
        """`mod.ARTIFACT` — спросить у НАСТОЯЩЕГО модуля, а не угадывать.

        Догадка по каталогу уже рождала выдуманные находки (урок #774):
        значение постоянной берётся из того модуля, которым имя связано в ЭТОМ
        файле, и ни из какого другого.
        """
        base = node.value
        if not isinstance(base, ast.Name):
            return None
        dotted = self.aliases.get(base.id)
        if not dotted:
            return None
        try:
            mod = importlib.import_module(dotted)
        except Exception:
            return None
        value = getattr(mod, node.attr, None)
        return value if isinstance(value, str) else None

    # --- документ --------------------------------------------------------
    def skeleton(self, node: ast.AST, depth: int = 0,
                 seen: tuple[str, ...] = ()) -> tuple[dict | None, str | None]:
        if depth > MAX_DEPTH:
            return None, "depth_limit"
        if isinstance(node, ast.Dict):
            return self._dict_skeleton(node, depth, seen)
        if isinstance(node, ast.Name):
            return self._name_skeleton(node, depth, seen)
        if isinstance(node, ast.Call):
            return self._call_skeleton(node, depth, seen)
        if isinstance(node, ast.Subscript):
            # `D.run(...)["doc"]` — документ достаётся из РЕЗУЛЬТАТА вызова.
            # Разрешать надо подчинённый узел, а причину — пробрасывать
            # как есть: иначе исход «собран вызовом» прочитался бы как
            # слабость разбора.
            inner, why = self.skeleton(node.value, depth + 1, seen)
            key = node.slice
            if (inner is not None and isinstance(key, ast.Constant)
                    and isinstance(key.value, str)):
                sub = inner.get(key.value)
                return (sub, why) if isinstance(sub, dict) else (None, why or "subscript_leaf")
            return None, why or "subscript_unresolved"
        if isinstance(node, ast.DictComp):
            # `{k: v for k, v in БАЗА.items() if k != "x"}` — отрицательный
            # контроль «документ БЕЗ поля». Предметом мерки является ФИКСТУРА,
            # а не её намеренное усечение, поэтому разрешается БАЗА включения
            # (то же правило объединения, что у нескольких присваиваний имени).
            return self._comprehension_skeleton(node, depth, seen)
        return None, "expr_unresolved"

    def _dict_skeleton(self, node: ast.Dict, depth: int,
                       seen: tuple[str, ...]) -> tuple[dict, str | None]:
        out: dict = {}
        why: str | None = None
        for key, value in zip(node.keys, node.values):
            if key is None:                               # {**base, …}
                sub, sub_why = self.skeleton(value, depth + 1, seen)
                if sub:
                    _merge(out, sub)
                elif why is None:
                    why = sub_why or "star_unresolved"
                continue
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                why = why or "non_literal_key"
                continue
            sub, _ = self.skeleton(value, depth + 1, seen)
            if sub is None:
                sub = self._first_in_sequence(value, depth + 1, seen)
            out[key.value] = sub if sub is not None else LEAF
        return out, why

    def _first_in_sequence(self, node: ast.AST, depth: int,
                           seen: tuple[str, ...]) -> dict | None:
        """Список записей: `_has_path` в элементы не спускается, но вложенный
        словарь-образец бывает единственным носителем формы раздела."""
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for element in node.elts:
                sub, _ = self.skeleton(element, depth, seen)
                if sub is not None:
                    return sub
        return None

    def _name_skeleton(self, node: ast.Name, depth: int,
                       seen: tuple) -> tuple[dict | None, str | None]:
        # Петля ищется по ПАРЕ «область × имя», а не по одному имени: после
        # перехода к вызывающему (G698 п. 2) у его локального `doc` то же
        # написание, что у параметра помощника, и проверка по одному имени
        # объявляла бы петлёй ОБЫЧНУЮ передачу аргумента (замер: 9 площадок
        # из 33 неизмеренных вместо 5).
        mark = (id(self._scope_func), node.id)
        if mark in seen:
            return None, "cycle"
        values = self.assigns.get(node.id)
        if not values:
            return self._from_callers(node.id, depth, seen)
        merged: dict = {}
        why: str | None = None
        got = False
        for value in values:
            sub, sub_why = self.skeleton(value, depth + 1, seen + (mark,))
            if sub is not None:
                _merge(merged, sub)
                got = True
            elif why is None:
                why = sub_why
        return (merged, why) if got else (None, why or "name_unresolved")

    def _comprehension_skeleton(self, node: ast.DictComp, depth: int,
                                seen: tuple[str, ...]
                                ) -> tuple[dict | None, str | None]:
        for comp in node.generators:
            source = comp.iter
            if (isinstance(source, ast.Call)
                    and isinstance(source.func, ast.Attribute)
                    and source.func.attr in ("items", "copy")):
                source = source.func.value
            sub, why = self.skeleton(source, depth + 1, seen)
            if sub is not None:
                return sub, why
        return None, "comprehension_unresolved"

    @staticmethod
    def _json_round_trip(node: ast.Call) -> ast.AST | None:
        """`json.loads(json.dumps(X))` → `X`, иначе `None`."""
        def dotted(call: ast.Call, attr: str) -> bool:
            func = call.func
            return (isinstance(func, ast.Attribute) and func.attr == attr
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "json")

        if not (dotted(node, "loads") and len(node.args) == 1):
            return None
        arg = node.args[0]
        if isinstance(arg, ast.Call) and dotted(arg, "dumps") and arg.args:
            return arg.args[0]
        return None

    def _call_skeleton(self, node: ast.Call, depth: int,
                       seen: tuple[str, ...]) -> tuple[dict | None, str | None]:
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None)
        if name in ("deepcopy", "copy") and node.args:
            # Копия фикстуры ЕСТЬ та же фикстура: мутации после копии — это
            # отрицательные контроли, а не другой документ.
            return self.skeleton(node.args[0], depth + 1, seen)
        inner = self._json_round_trip(node)
        if inner is not None:
            # `json.loads(json.dumps(X))` — тот же идиом глубокой копии, что и
            # `deepcopy`, только написанный stdlib-ом (инв. #4). Не узнав его,
            # мера объявляла документ «собранным вызовом» и площадку теряла.
            return self.skeleton(inner, depth + 1, seen)
        if (name == "copy" and not node.args
                and isinstance(func, ast.Attribute)):
            return self.skeleton(func.value, depth + 1, seen)
        if name == "dict":
            out: dict = {}
            why: str | None = None
            for arg in node.args:
                sub, sub_why = self.skeleton(arg, depth + 1, seen)
                if sub:
                    _merge(out, sub)
                elif why is None:
                    why = sub_why or "star_unresolved"
            for kw in node.keywords:
                if kw.arg is None:
                    sub, sub_why = self.skeleton(kw.value, depth + 1, seen)
                    if sub:
                        _merge(out, sub)
                    elif why is None:
                        why = sub_why or "star_unresolved"
                else:
                    sub, _ = self.skeleton(kw.value, depth + 1, seen)
                    out[kw.arg] = sub if sub is not None else LEAF
            return out, why
        if name and name not in seen:
            # Разрешение по ВЛАДЕЛЬЦУ, а не по имени (заказ G699 п. 2): три
            # `_doc` в трёх классах `test_list_day_axis.py` зовутся каждый
            # своей сценой, а объединение по имени сливало их возвраты, и
            # богатый сосед ОПРАВДЫВАЛ куцую площадку.
            defs, why_target = self.target_defs(node)
            if not defs:
                return None, why_target or "call_unresolved"
            merged: dict = {}
            why = None
            got = False
            saved_assigns, saved_func = self.assigns, self._scope_func
            try:
                for fdef in defs:
                    # Выражение `return` принадлежит ПОМОЩНИКУ, и связывать
                    # его имена областью ЗОВУЩЕГО значило бы то же
                    # одалживание, против которого введена область:
                    # `_health_with_house_view` строит документ в своём
                    # локальном `doc`, которого у сцены нет вовсе.
                    self.scope_to(fdef)
                    for ret in ast.walk(fdef):
                        if isinstance(ret, ast.Return) and ret.value is not None:
                            sub, sub_why = self.skeleton(ret.value, depth + 1,
                                                         seen + (name,))
                            if sub is not None:
                                _merge(merged, sub)
                                got = True
                            elif why is None:
                                why = sub_why
            finally:
                self.assigns, self._scope_func = saved_assigns, saved_func
            if got:
                return merged, why
            return None, why or "helper_returns_no_dict"
        return None, "call_unresolved"


def _aliases(tree: ast.Module) -> dict[str, str]:
    """Имя в файле → точечное имя модуля (`import a.b as m`, `import_module`).

    Форма импорта теряется в плоском наборе имён (урок про `import a.b` против
    `from a.b import C`), поэтому собираются ровно те формы, что дают МОДУЛЬ:
    по ним и только по ним спрашивается значение постоянной.
    """
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                out[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            fname = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None)
            if fname != "import_module" or not node.value.args:
                continue
            arg = node.value.args[0]
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    out[tgt.id] = arg.value
    return out


def _exemption(lines: list[str], call_line: int,
               enclosing: tuple[int, int] | None) -> tuple[str | None, bool]:
    """Пометка освобождения: причина, и была ли пометка БЕЗ причины.

    Ищется на строке вызова и в теле её функции — там, где её и напишет автор
    куцей фикстуры. Пометка в докстринге невидима (урок #829): форма обязана
    быть `#`-комментарием, и регулярное выражение требует именно решётки.
    """
    span = [call_line]
    if enclosing:
        span = list(range(enclosing[0], enclosing[1] + 1))
    bare = False
    for number in span:
        if not (1 <= number <= len(lines)):
            continue
        text = lines[number - 1]
        hit = _EXEMPT_RE.search(text)
        if hit:
            return hit.group("why"), False
        if _EXEMPT_BARE_RE.search(text):
            bare = True
    return None, bare


def _enclosing_spans(tree: ast.Module) -> list[tuple[int, int]]:
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spans.append((node.lineno, getattr(node, "end_lineno", node.lineno)))
    return spans


def _span_of(spans: list[tuple[int, int]], line: int) -> tuple[int, int] | None:
    best = None
    for start, end in spans:
        if start <= line <= end and (best is None or start > best[0]):
            best = (start, end)
    return best


def measure(*, schema: dict, has_path, root: str,
            test_dirs: tuple[str, ...] = DEFAULT_TEST_DIRS) -> Census:
    """Перепись класса.

    `schema` и `has_path` приезжают ВХОДОМ — это правило шага 0-офис, и второй
    его копии здесь нет: пересчёт «что значит ЕСТЬ поле» был бы вторым
    правилом, расходящимся с первым молча.
    """
    census = Census()
    files: list[str] = []
    for directory in test_dirs:
        base = os.path.join(root, directory)
        for walk_root, _dirs, names in os.walk(base):
            files += [os.path.join(walk_root, n) for n in names if n.endswith(".py")]

    for path in sorted(files):
        rel = os.path.relpath(path, root)
        try:
            source = open(path, encoding="utf-8").read()
        except OSError as exc:
            census.unmeasured.append((rel, f"file_unreadable:{exc!r}"))
            continue
        if DOOR + "(" not in source:
            continue
        census.files_scanned += 1
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            census.unmeasured.append((rel, f"file_unparsed:{exc!r}"))
            continue
        lines = source.splitlines()
        flow = _ModuleFlow(tree, _aliases(tree))
        spans = _enclosing_spans(tree)
        owners = _enclosing_funcs(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else None)
            if name != DOOR or len(node.args) < 2:
                continue
            where = f"{rel}:{node.lineno}"
            # Имена связываются ОБЛАСТЬЮ площадки, а не файлом (ADR-699).
            flow.scope_to(owners.get(node.lineno))
            raw = flow.text(node.args[0])
            if raw is None:
                census.unmeasured.append((where, "artifact_name_unresolved"))
                continue
            artifact = os.path.basename(raw)
            if artifact not in schema:
                census.out_of_subject.append((rel, node.lineno, artifact))
                continue
            doc, why = flow.skeleton(node.args[1])
            if doc is None:
                if why in _BUILT_BY_CALL:
                    # Документ собран ВЫЗОВОМ (прогон производителя, чтение
                    # файла, помощник вне файла) — это НЕ словарь-фикстура, и
                    # класс «объявленный ключ без значения в фикстуре» к нему
                    # не относится по построению. Исход назван отдельно, а не
                    # свёрнут ни в население, ни в «НЕ ИЗМЕРЕНО»: то, что у
                    # мерки нет предмета, и то, что она не справилась, —
                    # разные ответы.
                    census.built_by_call.append((where, str(why)))
                else:
                    census.unmeasured.append((where, f"doc_unresolved:{why}"))
                continue
            missing = tuple(p for p in schema[artifact] if not has_path(doc, p))
            reason, bare = _exemption(lines, node.lineno,
                                      _span_of(spans, node.lineno))
            if bare and reason is None and missing:
                census.marker_without_reason.append((rel, node.lineno))
            census.sites.append(Site(file=rel, line=node.lineno,
                                     artifact=artifact, missing=missing,
                                     declared=len(schema[artifact]),
                                     exempt_reason=reason))
    return census


def compare(census: Census, baseline: dict) -> list[str]:
    """Сверка с базой: что ВЫРОСЛО и что появилось НОВЫМ.

    Вынесено из храповика в прибор нарочно: сама сверка и есть то поведение,
    которому нужен положительный контроль (авария #832/#834/#837/#841 —
    объявленный раздел и необновлённая фикстура), а тест, читающий живую базу,
    воспроизвести аварию не может, не правя живую базу.

    База может только УМЕНЬШАТЬСЯ, поэтому убывание ключа и его исчезновение
    молчат: это починка, а не регресс.
    """
    measured = census.by_key()
    detail = census.missing_by_key()
    report: list[str] = []
    for key, now in sorted(measured.items()):
        was = baseline.get(key)
        if was is None:
            report.append(f"  НОВЫЙ {key}: {now}\n"
                          f"        не несёт: {detail[key]}")
        elif now > was:
            report.append(f"  ВЫРОС {key}: {was} \u2192 {now}\n"
                          f"        не несёт: {detail[key]}")
    return report
