#!/usr/bin/env python3
"""ТОЧКА ВХОДА КАРКАСА — ОБЪЯВЛЕНИЕ, а не вывод из формы.

# LLM_FORBIDDEN

**Что это закрывает.** ADR-950 измерил границу «вызывающих не спрашивали» и
оставил **16** чтений в третьем исходе. ADR-951 добавил СУДЬБУ пойманного
исключения и те же 16 не тронул. Заказ G940 п. 1 назвал эту дыру крупнейшей
объявленной и назвал лечение ДОСЛОВНО:

> непривязанный однофамилец **8** · звавшего в дереве нет вовсе **6** ·
> опаковый декоратор **2**. Первая группа лечится привязкой по ДОРОГЕ значения,
> а не по имени; вторая и третья — **ОБЪЯВЛЕНИЕМ точек входа каркаса** (маршрут
> FastAPI, расписание launchd), **и это объявление, а не вывод из формы**.

Этот модуль есть вторая и третья группы. Первая (однофамилец) здесь НЕ
закрывается и названа в ADR-952 остатком с измеренной ценой.

**Почему именно ОБЪЯВЛЕНИЕ.** Функция, которую не зовёт ни одна строка дерева,
не «громкая» и не «заглушённая» — про неё неизвестно НИЧЕГО, пока не назван тот,
кто её зовёт, И не названо, что он делает с исключением. Вывести второе из формы
декоратора нельзя: `@router.get` и `@functools.lru_cache` отличаются не формой, а
тем, что делает каркас за ними. Поэтому здесь перечень с НАЗВАННЫМ МЕХАНИЗМОМ у
каждого члена, а каркас вне перечня даёт ``None`` — то есть прежнее
«не измерено» (fail-CLOSED).

**Порядок вердиктов не косметический.** В этом классе ошибаться дороже всего в
сторону ``loud``: «громко» СНИМАЕТ чтение с приоритета, а ``silenced`` оставляет
его на предмете. Поэтому:

* ``silenced`` спрашивается ПЕРВЫМ и бьёт ``loud`` у одного и того же имени;
* ``loud`` объявлен только там, где каркас ДОКЛАДЫВАЕТ исключение (pytest,
  unittest) — и для ``pytest_test`` это вообще не новая претензия, а та же,
  которую прибор ADR-950 уже применял ОДНИМ ПРЫЖКОМ ПОЗЖЕ (см. ниже);
* всё, про что механизм не назван, остаётся ``None``.

**Асимметрия, которую этот модуль снимает по построению.** `_caller_silencer`
объявлял ``pytest_test`` точкой входа (:data:`_caller_silencer.ENTRY_KINDS`) и
считал её ровно тогда, когда тест ЗВАЛ что-то. Если же само измеряемое чтение
лежало В ТЕЛЕ теста, тест переставал быть точкой входа и становился «звавший вне
дерева» — то есть один и тот же `def test_…` был то каркасом, то неизвестностью,
и решал это НОМЕР ПРЫЖКА, а не свойство дерева. Предикат теперь ОДИН
(:func:`is_pytest_test`), и у него два вызывающих — расхождение стало
невозможным, а не исправленным (урок ADR-774 о единственной двери).

**Дорога значения, а не имя.** `@router.get` признаётся маршрутом только если
``router`` привязан НА УРОВНЕ МОДУЛЯ к вызову ``APIRouter``/``FastAPI``,
ввезённого из ``fastapi``/``starlette``. Сцена `router = object()` маршрутом не
является и не становится им от похожести имени — иначе объявление мерило бы
написание, а не каркас.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, FrozenSet, NamedTuple, Optional, Set, Tuple

from spa_core.tests import _silencer_fate as fates

#: Что каркас делает с исключением. Третий исход у объявления ТОЖЕ есть:
#: ``ambiguous`` — каркас НАЗВАН, а судьба у него не одна (инв. #17).
ENTRY_VERDICTS: Tuple[str, ...] = ("loud", "silenced", "ambiguous")


class FrameworkEntry(NamedTuple):
    """Один объявленный каркас: кто зовёт, что делает с исключением и ПОЧЕМУ."""

    kind: str
    verdict: str
    fate: Optional[str]
    why: str


#: Глаголы HTTP (и `websocket`), которыми маршрутизатор ASGI объявляет обработчик.
ASGI_VERBS: FrozenSet[str] = frozenset({
    "get", "post", "put", "patch", "delete", "head", "options", "trace",
    "websocket", "api_route", "route",
})

#: Фабрики объекта-маршрутизатора. Признаётся ТОЛЬКО ввезённая из каркаса.
ASGI_FACTORIES: FrozenSet[str] = frozenset({"APIRouter", "FastAPI", "Starlette"})

#: Пакеты каркаса ASGI.
ASGI_PACKAGES: Tuple[str, ...] = ("fastapi", "starlette")

#: Крюки `unittest.TestCase`, которые зовёт САМ каркас прогона.
UNITTEST_HOOKS: FrozenSet[str] = frozenset({
    "setUp", "tearDown", "setUpClass", "tearDownClass",
    "asyncSetUp", "asyncTearDown", "setUpModule", "tearDownModule",
})

#: Базы, по которым класс признаётся набором `unittest`.
UNITTEST_BASES: FrozenSet[str] = frozenset({"TestCase", "IsolatedAsyncioTestCase"})


#: ОБЪЯВЛЕНИЕ. У каждого члена назван МЕХАНИЗМ — иначе это не объявление, а вкус.
DECLARATION: Dict[str, FrameworkEntry] = {
    "asgi_route": FrameworkEntry(
        kind="asgi_route", verdict="silenced", fate="renamed",
        why=("обработчик маршрута зовёт каркас ASGI: исключение из тела "
             "перехватывает `ServerErrorMiddleware` и отдаёт клиенту "
             "`500 Internal Server Error` — пустота не теряется, а "
             "ПЕРЕИМЕНОВЫВАЕТСЯ в «сервер сломался». Канал лога сервера при "
             "этом остаётся громким, и выбор сделан в сторону ПРЕДМЕТА: в этом "
             "классе `loud` — единственный вердикт, снимающий чтение с "
             "приоритета")),
    "pytest_test": FrameworkEntry(
        kind="pytest_test", verdict="loud", fate=None,
        why=("тестовую функцию зовёт pytest: исключение из её тела становится "
             "ПАДЕНИЕМ теста с напечатанным стеком. Это та же претензия, "
             "которую прибор ADR-950 уже применял к вызову ВНУТРИ теста — "
             "здесь она применена к самому тесту, и предикат у обеих один")),
    "pytest_fixture": FrameworkEntry(
        kind="pytest_fixture", verdict="loud", fate=None,
        why=("фикстуру зовёт pytest: исключение при её подготовке становится "
             "ОШИБКОЙ теста с напечатанным стеком, а не тишиной")),
    "unittest_hook": FrameworkEntry(
        kind="unittest_hook", verdict="loud", fate=None,
        why=("крюк `unittest.TestCase` зовёт каркас прогона: исключение из "
             "него становится ОШИБКОЙ набора с напечатанным стеком")),
}

#: Выведены, а не перечислены: разойдись перечень с объявлением — и утверждение
#: «вот эти каркасы громкие» перестало бы быть верным МОЛЧА (урок ADR-943).
LOUD_ENTRY_KINDS: Tuple[str, ...] = tuple(
    kind for kind, entry in DECLARATION.items() if entry.verdict == "loud")
SILENCED_ENTRY_KINDS: Tuple[str, ...] = tuple(
    kind for kind, entry in DECLARATION.items() if entry.verdict == "silenced")
ENTRY_KINDS: Tuple[str, ...] = tuple(DECLARATION)


def _check_declaration() -> None:
    """Объявление несёт СВОЙ контракт и проверяет его на импорте (ADR-932)."""
    for kind, entry in DECLARATION.items():
        if entry.kind != kind:
            raise ValueError(f"член `{kind}` объявлен под именем `{entry.kind}`")
        if entry.verdict not in ENTRY_VERDICTS:
            raise ValueError(f"`{kind}`: вердикт `{entry.verdict}` вне перечня")
        if entry.verdict == "silenced":
            if entry.fate not in fates.SILENCING_FATES:
                raise ValueError(
                    f"`{kind}`: глушащий каркас обязан назвать судьбу из "
                    f"{fates.SILENCING_FATES}, названа `{entry.fate}`")
        elif entry.fate is not None:
            raise ValueError(f"`{kind}`: судьба названа при вердикте "
                             f"`{entry.verdict}` — её читать некому")
        if len(entry.why) < 40:
            raise ValueError(f"`{kind}`: механизм не назван — это не объявление")


_check_declaration()


# ─────────────────────────── распознаватели ──────────────────────────────────


def _decorator_head(dec: ast.expr) -> ast.expr:
    """Узел имени декоратора: у `@f(...)` это `f`, у `@f` — он сам."""
    return dec.func if isinstance(dec, ast.Call) else dec


def _imported_from(mod: Any, local: str, packages: Tuple[str, ...]) -> bool:
    """Ввезено ли имя ``local`` из одного из ``packages`` (по его объявлению)."""
    imported = getattr(mod, "imported", {}).get(local)
    if imported is None:
        return False
    base = imported[0] or ""
    return base.split(".")[0] in packages


def asgi_router_names(mod: Any) -> Set[str]:
    """Имена уровня модуля, привязанные ДОРОГОЙ ЗНАЧЕНИЯ к маршрутизатору ASGI.

    Привязка мерится не написанием имени, а тем, ОТКУДА в него пришло значение:
    вызов фабрики из :data:`ASGI_FACTORIES`, и сама фабрика ввезена из
    :data:`ASGI_PACKAGES`. `router = object()` маршрутизатором не является.
    """
    tree = getattr(mod, "tree", None)
    if tree is None:
        return set()
    names: Set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            targets = [t for t in stmt.targets if isinstance(t, ast.Name)]
            value = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            targets = [stmt.target]
            value = stmt.value
        else:
            continue
        if not isinstance(value, ast.Call):
            continue
        fn = value.func
        if isinstance(fn, ast.Name):
            callee, head = fn.id, fn.id
        elif isinstance(fn, ast.Attribute):
            callee = fn.attr
            head = fn.value.id if isinstance(fn.value, ast.Name) else ""
        else:
            continue
        if callee not in ASGI_FACTORIES:
            continue
        if not _imported_from(mod, head, ASGI_PACKAGES):
            continue
        names.update(t.id for t in targets)
    return names


def asgi_route_decorator(func: ast.AST, mod: Any) -> Optional[str]:
    """Имя декоратора-маршрута ASGI у объявления, либо ``None``."""
    routers = asgi_router_names(mod)
    if not routers:
        return None
    for dec in getattr(func, "decorator_list", []):
        node = _decorator_head(dec)
        if not isinstance(node, ast.Attribute) or node.attr not in ASGI_VERBS:
            continue
        head = node.value
        if isinstance(head, ast.Name) and head.id in routers:
            return f"{head.id}.{node.attr}"
    return None


def pytest_fixture_decorator(func: ast.AST, mod: Any) -> Optional[str]:
    """Имя декоратора-фикстуры pytest у объявления, либо ``None``."""
    for dec in getattr(func, "decorator_list", []):
        node = _decorator_head(dec)
        if isinstance(node, ast.Name):
            if node.id == "fixture" and _imported_from(mod, node.id, ("pytest",)):
                return "fixture"
        elif isinstance(node, ast.Attribute) and node.attr == "fixture":
            head = node.value
            if isinstance(head, ast.Name) and (
                    head.id == "pytest"
                    or _imported_from(mod, head.id, ("pytest",))):
                return f"{head.id}.fixture"
    return None


def is_pytest_test(name: str, rel: str) -> bool:
    """ЕДИНСТВЕННЫЙ предикат «это тестовая функция, которую зовёт pytest».

    У него ДВА вызывающих в `_caller_silencer`: вызов ВНУТРИ теста и сам тест как
    цель замера. Своей копии ни у одного из них нет — иначе один и тот же
    `def test_…` снова оказался бы то каркасом, то неизвестностью, и решал бы это
    номер прыжка.
    """
    return name.startswith("test_") and ("tests/" in rel or "/test_" in f"/{rel}")


def _unittest_hook(func: ast.AST, mod: Any) -> Optional[str]:
    """Имя крюка `unittest`, если объявление — крюк набора, либо ``None``."""
    name = getattr(func, "name", "")
    if name not in UNITTEST_HOOKS:
        return None
    owner = getattr(mod, "index", {}).get(id(func))
    if not isinstance(owner, ast.ClassDef):
        # `setUpModule`/`tearDownModule` зовёт каркас и на уровне модуля.
        return name if isinstance(owner, ast.Module) and name.endswith("Module") \
            else None
    for base in owner.bases:
        label = (base.id if isinstance(base, ast.Name)
                 else base.attr if isinstance(base, ast.Attribute) else None)
        if label in UNITTEST_BASES:
            return f"{owner.name}.{name}"
    return None


#: Порядок опроса. ``silenced`` стои́т ПЕРВЫМ намеренно: у одного имени может
#: оказаться и маршрут, и форма теста, и ошибиться в сторону ``loud`` дороже.
_PROBES: Tuple[Tuple[str, Any], ...] = (
    ("asgi_route", lambda func, name, rel, mod: asgi_route_decorator(func, mod)),
    ("pytest_fixture", lambda func, name, rel, mod: pytest_fixture_decorator(func, mod)),
    ("unittest_hook", lambda func, name, rel, mod: _unittest_hook(func, mod)),
    ("pytest_test", lambda func, name, rel, mod: (
        name if is_pytest_test(name, rel) else None)),
)


def framework_entry(rel: str, name: str,
                    facts: Dict[str, Any]) -> Optional[Tuple[FrameworkEntry, str]]:
    """Объявленный каркас, зовущий ``rel::name``, и ПРИМЕТА, по которой он узнан.

    ``None`` означает «каркас не объявлен» — то есть прежнее «не измерено», а не
    «каркаса нет». Если имя объявлено в модуле несколько раз, берётся ХУДШИЙ для
    предмета ответ в порядке :data:`_PROBES`: громкость принадлежит ПУТИ, и один
    заглушающий путь отменяет громкость остальных (та же мера, что у ADR-950).
    """
    mod = facts.get(rel)
    tree = getattr(mod, "tree", None) if mod is not None else None
    if tree is None:
        return None
    found: Dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != name:
            continue
        for kind, probe in _PROBES:
            if kind in found:
                continue
            mark = probe(node, name, rel, mod)
            if mark is not None:
                found[kind] = mark
    for kind, _probe in _PROBES:
        if kind in found:
            return DECLARATION[kind], found[kind]
    return None
