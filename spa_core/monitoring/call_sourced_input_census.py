"""Перепись входов-перечней, собранных ВЫЗОВОМ, а не литералом.

Заказ **G45, п. 1** приказа владельца «Portfolio CIO» — дословный хвост
ADR-420:

    «Перечень, собранный ВЫЗОВОМ, в население не входит вовсе — это дыра,
    названная в `what_it_does_not_prove` и не измеренная ничем. Сколько
    сторожей берут вход не литералом, а вызовом (`_collect()`, `glob`,
    чтением файла)? Для них "пустой вход" достижим БЕЗ всякой правки —
    то есть подкласс `reachable_absent_path` там может оказаться не
    исключением, а правилом. Считать ДО починок.»

## Чем этот вопрос отличается от ADR-420

ADR-420 мерил сторожей, чей вход записан ЛИТЕРАЛОМ (`SCAN_DIRS = (...)`), и
опустошал его ПРАВКОЙ исходника. Здесь вход собирается вызовом
(`ROOT.rglob("*.py")`, `PATH.read_text()`, `json.load(...)`), и опустошить его
правкой не нужно вовсе: каталога нет — перечень пуст. Такие деревья у нас
штатны и предписаны протоколом (свежий `git worktree`, где `data/` в
`.gitignore` и потому отсутствует ПО ПОСТРОЕНИЮ).

Поэтому вопрос сдвигается с «достижима ли пустота» на **«что сторож ДЕЛАЕТ,
когда его вход пуст»**, и ответов ровно четыре — они и есть вердикт строки.

## Четыре двери, и три из них различимы в ИСХОДЕ

| дверь | что стои́т между пустым входом и зелёным тестом | исход |
|---|---|---|
| `refuses_or_skips` | проверка существования → `pytest.skip` / `fail` / `raise` | назван |
| `substitutes` | проверка существования → **подстановка фикстуры**, тест идёт дальше | ЗЕЛЁНЫЙ |
| `no_door` | проверки нет: вызов вернул пустое, тело цикла не исполнилось | ЗЕЛЁНЫЙ |
| `unmeasured` | дверь есть, но её последствие не разбирается | — |

`substitutes` — находка, и находка нового рода. Сторож не слепнет: он **меняет
предмет**. `test_proof_chain_spec_reproducible` (замер 19.09) при живом
артефакте пересчитывает хеш НАСТОЯЩЕГО публичного журнала отказов, а при
отсутствующем — хеш строки, которую сам же только что и написал. Оба исхода
`passed`, и различить их нечем. Инвариант #17 требует, чтобы «не измерено»
было ОТДЕЛЬНЫМ ЗНАЧЕНИЕМ; объявление подстановки в докстроке отдельным
значением не является, поэтому поле `declared_in_docstring` у строки есть, а
вердикт оно не меняет.

`no_door` — тот же класс, что у ADR-420 (`vacuous_pass`), но достижимый БЕЗ
правки. Находкой он становится тогда, когда путь в ЭТОМ дереве отсутствует:
тогда это не риск, а сегодняшнее состояние.

## Что в население НЕ входит — и это замер, а не осторожность

* **Перечень из фикстуры** (`tmp_path.iterdir()`, `mkdtemp()`): это не вход
  сторожа, а его собственные леса — каталог построен тем же тестом парой строк
  выше. Опустошить его значит сломать сцену, а не ослепить сторожа. Счётчик
  `fixture_tree` печатается, чтобы исключение было видимым.
* **Перечень вне дерева репозитория** (`/etc`, `$HOME`) — `outside_repo`.
* **`ast.walk`** — обход разобранного дерева, а не файловой системы.

## Третий исход (инв. #17)

`unresolved` — путь не вычислился (имя из параметра, `self.X` вне `setUp`,
конкатенация не-литералом). Это НЕ «входов больше нет»: доля неразобранного
печатается рядом с ответом, и перепись без неё читать нельзя. Нечитаемый файл
идёт в `unreadable`, а отсутствие каталогов-сторожей — громкий отказ
(`NotMeasured`), а не пустая перепись.

## Перепись ничего не чинит

Требование заказа дословно: «Считать ДО починок». Найденный сторож — предмет
своей карточки, а не прицепа (инв. #16).
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # запуск ПО ПУТИ, а не пакетом
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import rule_second_copy_census as census  # noqa: E402
from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.utils.atomic import atomic_save  # noqa: E402

ARTIFACT = "call_sourced_input_census.json"
PRODUCER = "spa_core/monitoring/call_sourced_input_census.py"

#: Журнал ПОВЕДЕНЧЕСКОГО зонда (`absent_path_probe`, заказ G46 п. 1). Перепись
#: зонд не зовёт — она только ЧИТАЕТ его журнал, ровно как ADR-419/420. Имя
#: живёт ЗДЕСЬ, а зонд его ввозит: одно правило — одна копия (ADR-418).
BEHAVIOUR_LEDGER = "spa_core/monitoring/absent_path_ledger.json"

#: Каталоги сторожей ВВОЗЯТСЯ у переписи ADR-417 — одно правило, одна копия
#: (ADR-418, форма починки `single_copy_by_import`).
GUARD_DIRS = census.GUARD_DIRS

# ── роды источника ────────────────────────────────────────────────────────────
KIND_TREE = "tree_scan"
KIND_READ = "file_read"

#: Методы пути, перечисляющие дерево.
_SCAN_METHODS = frozenset({"rglob", "glob", "iterdir", "scandir"})
#: Функции модуля `os`, перечисляющие дерево.
_OS_SCANS = frozenset({"walk", "listdir", "scandir"})
_GLOB_FUNCS = frozenset({"glob", "iglob"})
#: Методы пути, читающие файл в перечень.
_READ_METHODS = frozenset({"read_text", "read_bytes", "readlines"})
#: Обёртки, не меняющие источник: `sorted(ROOT.rglob(...))` — это тот же обход.
_WRAPPERS = frozenset({"sorted", "list", "set", "tuple", "frozenset",
                       "reversed", "iter"})
#: Хвосты текста: `PATH.read_text().splitlines()` — источник в `read_text`.
_TEXT_TAILS = frozenset({"splitlines", "split", "strip", "rstrip", "lstrip"})

# ── расположение перечня ──────────────────────────────────────────────────────
PLACE_REPO = "repo_tree"
PLACE_FIXTURE = "fixture_tree"
PLACE_OUTSIDE = "outside_repo"
PLACE_UNRESOLVED = "unresolved"

# ── двери ─────────────────────────────────────────────────────────────────────
DOOR_REFUSES = "refuses_or_skips"
DOOR_SUBSTITUTES = "substitutes"
#: Проверка отсутствия ЕСТЬ, и её ответ — ПУСТОЙ перечень. Инвариант #17
#: запрещает ровно эту форму: «не измерено» представлено нулём, а не
#: отдельным значением. От :data:`DOOR_NONE` отличается доказуемой
#: НАМЕРЕННОСТЬЮ — автор отсутствие увидел и выбрал промолчать.
DOOR_EMPTY = "empty_sentinel"
#: Пустой вход КРАСНИТ модуль, но краснотой соседа, а не потребителя: тест
#: вида `n not in _collect()` на пустом перечне объявляет нарушителями ВСЮ
#: базу. Защита есть, и сливать её с отказом нельзя — потребитель перечня
#: остался вырожденным, покраснел другой (то же различение, что у ADR-420).
DOOR_ELSEWHERE = "refuses_elsewhere"
DOOR_NONE = "no_door"
DOOR_UNMEASURED = "unmeasured"
DOORS = (DOOR_REFUSES, DOOR_SUBSTITUTES, DOOR_EMPTY, DOOR_ELSEWHERE,
         DOOR_NONE, DOOR_UNMEASURED)
#: Двери, при которых пустой вход даёт ЗЕЛЁНЫЙ тест и об этом не сказано ничем.
GREEN_DOORS = (DOOR_SUBSTITUTES, DOOR_EMPTY, DOOR_NONE)
#: Двери, от которых ЖДЁТСЯ отказ в прогоне. Правило объявлено здесь, потому
#: что двери — предмет переписи; зонд его ввозит, а не переписывает.
DOORS_EXPECTING_REFUSAL = (DOOR_REFUSES, DOOR_ELSEWHERE)

#: Утверждения unittest, отказывающие на пустоте. `assert`-оператор здесь НЕ
#: годится один: замер 19.09 показал, что контроль на вхолостую в нашем наборе
#: пишется `self.assertTrue(_collect(), "...")`, а не `assert`, и перепись,
#: знавшая только оператор, объявила находкой исправного сторожа.
_NONEMPTY_ASSERTS = frozenset({"assertTrue", "assertGreater",
                               "assertGreaterEqual", "assertNotEqual",
                               "assertIsNotNone"})

PRESENT_YES = "present"
PRESENT_NO = "absent"

#: Вердикт зонда, означающий слепоту: зелен, и прошло столько же тестов.
BEHAVIOUR_VACUOUS = "vacuous_pass"
#: Вердикты зонда, которые вердиктом о слепоте НЕ являются: «не измерено»,
#: «унос сломал сцену» и «собственный тест строки в этом дереве ПРОПУЩЕН».
#: Слить их с отсутствием записи нельзя — причина у каждого своя.
#: Литералы, а не ввоз констант зонда, ПО ПОСТРОЕНИЮ: зонд ввозит эту перепись
#: (`absent_path_probe.census`), и обратный ввоз был бы кругом. Копия названа
#: вслух, как требует ADR-417/418, а не оставлена молчаливой.
BEHAVIOUR_NO_VERDICT = ("unmeasured", "scene_destroyed", "already_skipped")

#: Имена фикстур pytest/unittest, дающих одноразовый каталог.
_FIXTURE_NAMES = frozenset({"tmp_path", "tmpdir", "tmp", "tmp_dir", "td",
                            "tempdir", "tmp_path_factory", "tmpdir_factory"})
#: Вызовы, рождающие одноразовый каталог.
_FIXTURE_CALLS = frozenset({"mkdtemp", "mkstemp", "TemporaryDirectory",
                            "NamedTemporaryFile"})
#: Вызовы-отказы: ими сторож ГОВОРИТ, что не смотрел.
_REFUSAL_CALLS = frozenset({"skip", "skipTest", "fail", "xfail", "exit"})

_FIXTURE = object()   # часовой: «путь одноразовый», не то же, что «не вычислен»


class NotMeasured(RuntimeError):
    """Население не прочитано — третий исход, а не пустая перепись."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 1. Источник перечня
# ══════════════════════════════════════════════════════════════════════════════

def unwrap(node: ast.AST) -> ast.AST:
    """Снять обёртки, не меняющие источник перечня.

    `sorted(...)`, `list(...)` и хвост `.splitlines()` перечень переупаковывают,
    но не порождают: пустой обход останется пустым через любую из них. Не снять
    их значило бы считать `sorted(ROOT.rglob(...))` другим родом, чем
    `ROOT.rglob(...)`, — то есть делить население по способу записи.
    """
    changed = True
    while changed:
        changed = False
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in _WRAPPERS and node.args:
            node, changed = node.args[0], True
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in _TEXT_TAILS \
                and isinstance(node.func.value, ast.Call):
            node, changed = node.func.value, True
    return node


def source_of(call: ast.Call) -> Tuple[Optional[str], Optional[ast.AST]]:
    """Род источника и выражение ПУТИ, из которого перечень берётся.

    Возвращает ``(None, None)``, если вызов перечня из файловой системы не
    строит. `ast.walk` исключён поимённо: он обходит разобранное дерево, а не
    каталог, и попасть в население значило бы считать разбор источника
    источником.
    """
    func = call.func
    if isinstance(func, ast.Attribute):
        owner = func.value
        # `ast.walk` в население не входит БЕЗ отдельной ветки: `walk` нет в
        # `_SCAN_METHODS`, а обходы `os` гейтятся именем владельца. Ветка-
        # исключение здесь стояла и была МЁРТВОЙ — батарея мутаций показала,
        # что её снятие не меняет ни одного вердикта. Снята: сторож,
        # неотличимый от своего отсутствия, есть украшение.
        if isinstance(owner, ast.Name) and owner.id == "os" \
                and func.attr in _OS_SCANS:
            return (KIND_TREE, call.args[0] if call.args else None)
        if isinstance(owner, ast.Name) and owner.id == "glob" \
                and func.attr in _GLOB_FUNCS:
            return (KIND_TREE, call.args[0] if call.args else None)
        if isinstance(owner, ast.Name) and owner.id == "json" \
                and func.attr in {"load", "loads"}:
            return (KIND_READ, call.args[0] if call.args else None)
        if func.attr in _SCAN_METHODS:
            return (KIND_TREE, owner)
        if func.attr in _READ_METHODS:
            return (KIND_READ, owner)
    if isinstance(func, ast.Name) and func.id == "open" and call.args:
        return (KIND_READ, call.args[0])
    return None, None


# ══════════════════════════════════════════════════════════════════════════════
# 2. Вычисление пути — КОНКРЕТНОЕ, а не по виду имени
# ══════════════════════════════════════════════════════════════════════════════

def _assignments(scope: ast.AST) -> Dict[str, ast.AST]:
    """Присваивания области: имена и `self.X`. Первое присваивание выигрывает."""
    out: Dict[str, ast.AST] = {}
    for node in ast.walk(scope):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name):
            out.setdefault(target.id, node.value)
        elif isinstance(target, ast.Attribute) \
                and isinstance(target.value, ast.Name) \
                and target.value.id == "self":
            out.setdefault("self." + target.attr, node.value)
    return out


def resolve(node: Optional[ast.AST], scopes: Sequence[Dict[str, ast.AST]],
            here: Path, *, depth: int = 0,
            seen: Optional[Set[str]] = None) -> object:
    """Вычислить выражение пути до НАСТОЯЩЕГО пути этого дерева.

    Вычисление конкретное: `__file__` есть разбираемый файл, поэтому
    `Path(__file__).resolve().parents[2] / "data"` даёт не «похоже на корень»,
    а сам каталог, у которого можно спросить `.exists()`. Разбор по ВИДУ имени
    (`"ROOT" in name`) ошибается в обе стороны и здесь не используется.

    Три исхода: путь · :data:`_FIXTURE` (одноразовый каталог) · ``None``
    (не вычислен). Сливать два последних нельзя: фикстура ИЗМЕРЕНА и исключена,
    невычисленное — не измерено и остаётся на учёте.
    """
    seen = seen or set()
    if node is None or depth > 14:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return Path(node.value)
    if isinstance(node, ast.Name):
        if node.id == "__file__":
            return here
        if node.id in _FIXTURE_NAMES:
            return _FIXTURE
        if node.id in seen:
            return None
        for scope in scopes:
            if node.id in scope:
                return resolve(scope[node.id], scopes, here,
                               depth=depth + 1, seen=seen | {node.id})
        return None
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            key = "self." + node.attr
            lowered = node.attr.lower()
            if "tmp" in lowered or "temp" in lowered:
                return _FIXTURE
            if key in seen:
                return None
            for scope in scopes:
                if key in scope:
                    return resolve(scope[key], scopes, here,
                                   depth=depth + 1, seen=seen | {key})
            return None
        base = resolve(node.value, scopes, here, depth=depth + 1, seen=seen)
        if base is _FIXTURE:
            return _FIXTURE
        if isinstance(base, Path) and node.attr == "parent":
            return base.parent
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        base = resolve(node.left, scopes, here, depth=depth + 1, seen=seen)
        if base is _FIXTURE:
            return _FIXTURE
        right = node.right
        if isinstance(base, Path) and isinstance(right, ast.Constant) \
                and isinstance(right.value, str):
            return base / right.value
        return None
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
            and node.value.attr == "parents":
        base = resolve(node.value.value, scopes, here, depth=depth + 1, seen=seen)
        index = node.slice
        if base is _FIXTURE:
            return _FIXTURE
        if not isinstance(base, Path) or not isinstance(index, ast.Constant) \
                or not isinstance(index.value, int):
            return None
        try:
            return base.parents[index.value]
        except IndexError:
            return None
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in _FIXTURE_CALLS:
                return _FIXTURE
            if func.id in {"Path", "str"} and node.args:
                return resolve(node.args[0], scopes, here,
                               depth=depth + 1, seen=seen)
        if isinstance(func, ast.Attribute):
            if func.attr in _FIXTURE_CALLS:
                return _FIXTURE
            if func.attr in {"resolve", "absolute", "expanduser"}:
                return resolve(func.value, scopes, here,
                               depth=depth + 1, seen=seen)
            if func.attr == "joinpath" and node.args:
                base = resolve(func.value, scopes, here,
                               depth=depth + 1, seen=seen)
                if base is _FIXTURE:
                    return _FIXTURE
                parts = [a.value for a in node.args
                         if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                if isinstance(base, Path) and len(parts) == len(node.args):
                    return base.joinpath(*parts)
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 3. Дверь: что стои́т между пустым входом и зелёным тестом
# ══════════════════════════════════════════════════════════════════════════════

def probes_existence(test: ast.AST, anchor: str) -> bool:
    """Спрашивает ли условие о СУЩЕСТВОВАНИИ именно этого пути.

    Сверка идёт по разобранному выражению получателя (`ast.unparse`), а не по
    вхождению подстроки в текст условия: `if other.exists() and ROOT` содержит
    имя `ROOT`, но спрашивает не о нём.
    """
    for node in ast.walk(test):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"exists", "is_file", "is_dir"}:
            continue
        try:
            if ast.unparse(node.func.value) == anchor:
                return True
        except Exception:      # noqa: BLE001 — неразбираемое выражение не якорь
            continue
    return False


def _refuses(body: Sequence[ast.stmt]) -> Optional[str]:
    """Отказ в ветке: `pytest.skip` / `skipTest` / `fail` / `raise` / `exit`."""
    for node in body:
        for inner in ast.walk(node):
            if isinstance(inner, ast.Raise):
                return "raise"
            if isinstance(inner, ast.Call):
                name = inner.func.attr if isinstance(inner.func, ast.Attribute) \
                    else getattr(inner.func, "id", None)
                if name in _REFUSAL_CALLS:
                    return name
    return None


SENTINEL_NONE = "none"
SENTINEL_EMPTY = "empty"

#: Конструкторы пустых контейнеров: `set()` есть пустой перечень так же, как
#: `[]`. Разбирать только литералы значило бы делить класс по способу записи —
#: ровно та ошибка, из-за которой три храповика прошли мимо замера 19.09.
_EMPTY_CTORS = frozenset({"set", "list", "dict", "tuple", "frozenset"})


def _empty_value(node: Optional[ast.AST],
                 local: Optional[Dict[str, ast.AST]] = None,
                 depth: int = 0) -> Optional[str]:
    """Род часового у возвращаемого выражения, или ``None``.

    ``return found``, где выше стои́т ``found = []``, есть тот же пустой
    перечень: имя разрешается по присваиваниям ТОЙ ЖЕ функции.
    """
    if node is None or depth > 4:
        return SENTINEL_NONE if node is None else None
    if isinstance(node, ast.Constant) and node.value is None:
        return SENTINEL_NONE
    if isinstance(node, (ast.List, ast.Tuple)) and not node.elts:
        return SENTINEL_EMPTY
    if isinstance(node, ast.Dict) and not node.keys:
        return SENTINEL_EMPTY
    if isinstance(node, ast.Set) and not node.elts:
        return SENTINEL_EMPTY
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in _EMPTY_CTORS and not node.args \
            and not node.keywords:
        return SENTINEL_EMPTY
    if isinstance(node, ast.Name) and local and node.id in local:
        return _empty_value(local[node.id], None, depth + 1)
    return None


def _returns_sentinel(body: Sequence[ast.stmt],
                      local: Optional[Dict[str, ast.AST]] = None) -> Optional[str]:
    """Род часового, возвращаемого веткой: ``none`` · ``empty`` · ``None``."""
    for node in body:
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Return):
                continue
            kind = _empty_value(inner.value, local)
            if kind:
                return kind
    return None


def _assigned_names(body: Sequence[ast.stmt]) -> Set[str]:
    out: Set[str] = set()
    for node in body:
        for inner in ast.walk(node):
            if isinstance(inner, ast.Assign):
                for target in inner.targets:
                    if isinstance(target, ast.Name) and target.id != "_":
                        out.add(target.id)
    return out


def classify_door(scope: ast.AST, anchor: str) -> Tuple[str, str]:
    """``(дверь, улика)`` для перечня с якорем ``anchor`` внутри области ``scope``.

    Порядок правил существен и объявлен: отказ старше подстановки, подстановка
    старше часового. Ветка, которая И отказывает, И подставляет, есть отказ —
    зелёного исхода при пустом входе она не даёт.
    """
    for node in ast.walk(scope):
        if not isinstance(node, ast.If) or not probes_existence(node.test, anchor):
            continue
        refusal = _refuses(node.body) or _refuses(node.orelse)
        if refusal:
            return DOOR_REFUSES, f"{refusal} на строке {node.lineno}"
        common = _assigned_names(node.body) & _assigned_names(node.orelse)
        if node.orelse and common:
            names = ", ".join(sorted(common))
            return DOOR_SUBSTITUTES, f"обе ветки строки {node.lineno} задают {names}"
        local = _assignments(scope)
        sentinel = _returns_sentinel(node.body, local) \
            or _returns_sentinel(node.orelse, local)
        if sentinel:
            return f"returns_sentinel:{sentinel}", f"часовой на строке {node.lineno}"
        return DOOR_UNMEASURED, f"проверка на строке {node.lineno}, последствие не разобрано"
    return DOOR_NONE, ""


def _mentions(node: Optional[ast.AST], helper: str,
              holders: Set[str]) -> bool:
    """Упоминает ли выражение перечень: вызовом помощника или его именем."""
    if node is None:
        return False
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call) and (
                getattr(inner.func, "id", None) == helper
                or getattr(inner.func, "attr", None) == helper):
            return True
        if isinstance(inner, ast.Name) and inner.id in holders:
            return True
    return False


def anti_vacuity(tree: ast.Module, helper: str,
                 holders: Set[str]) -> Tuple[Optional[str], str]:
    """Есть ли в модуле защита от пустого перечня, и КТО её несёт.

    Возвращает ``(дверь | None, улика)``. Порядок опроса объявлен и существен:
    прямой контроль на вхолостую старше соседа-инвертора, потому что первый
    отказывает ИМЕННО по пустоте, а второй краснеет побочно.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in _NONEMPTY_ASSERTS and node.args \
                and _mentions(node.args[0], helper, holders):
            return (DOOR_REFUSES,
                    f"{node.func.attr} по перечню на строке {node.lineno} — "
                    f"контроль на вхолостую")
        if isinstance(node, ast.Assert) and not isinstance(node.test, ast.UnaryOp) \
                and _mentions(node.test, helper, holders):
            return (DOOR_REFUSES,
                    f"assert по перечню на строке {node.lineno} — "
                    f"контроль на вхолостую")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, ast.NotIn) for op in node.ops):
            continue
        if any(_mentions(c, helper, holders) for c in node.comparators):
            return (DOOR_ELSEWHERE,
                    f"сосед на строке {node.lineno} спрашивает «нет в перечне» — "
                    f"на пустом входе он краснеет за всю базу")
    return None, ""


def holders_of(tree: ast.Module, helper: str) -> Set[str]:
    """Имена, которым присваивается результат ``helper()``."""
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Call):
            func = node.value.func
            name = func.attr if isinstance(func, ast.Attribute) \
                else getattr(func, "id", None)
            if name == helper:
                out.add(node.targets[0].id)
    return out


def sentinel_handled(tree: ast.Module, helper: str,
                     sentinel: str) -> Tuple[str, str]:
    """Что делает ЗВАВШИЙ с часовым помощника ``helper``.

    Дверь может стоять на два шага: помощник возвращает часового, а отказ
    печатает звавший. Не пройти этот шаг значило бы записать исправного
    сторожа в находку — ровно та ошибка, ради которой перепись и пишется.

    Род часового решает, ЧТО считать отказом у звавшего: часового ``None``
    ловит проверка на ``is None``, пустой перечень — проверка пустоты
    (``if not rows:`` / ``assert rows``). Спрашивать про пустоту у часового
    ``None`` и наоборот значило бы искать не ту дверь.
    """
    holders = holders_of(tree, helper)
    inline = not holders
    if inline:
        # Результат помощника потребляется ПРЯМО в выражении
        # (`for x in _collect()`), имени у него нет — значит, отказать по имени
        # звавший не мог. Спросить всё равно надо: отказ бывает и по вызову
        # (`assert _collect()`), и не спросив, перепись записала бы исправного
        # сторожа в находку.
        for node in ast.walk(tree):
            refusal_body = None
            if isinstance(node, ast.Assert):
                refusal_body = [node]
            elif isinstance(node, ast.If):
                refusal_body = node.body + node.orelse
            if refusal_body is None:
                continue
            probe = node.test if isinstance(node, (ast.Assert, ast.If)) else None
            mentions = any(
                isinstance(inner, ast.Call)
                and (getattr(inner.func, "id", None) == helper
                     or getattr(inner.func, "attr", None) == helper)
                for inner in ast.walk(probe)) if probe is not None else False
            if not mentions:
                continue
            if isinstance(node, ast.Assert):
                return (DOOR_REFUSES,
                        f"assert по вызову {helper}() на строке {node.lineno}")
            refusal = _refuses(node.body) or _refuses(node.orelse)
            if refusal:
                return (DOOR_REFUSES,
                        f"{refusal} по вызову {helper}() на строке {node.lineno}")
        door, evidence = anti_vacuity(tree, helper, holders)
        if door:
            return door, evidence
        if sentinel == SENTINEL_EMPTY:
            return (DOOR_EMPTY,
                    f"{helper}() отвечает ПУСТЫМ перечнем и потребляется без "
                    f"имени — отказа по пустоте нет ни у одного звавшего")
        return (DOOR_NONE,
                f"часовой {helper}() потребляется без имени, отказа по нему нет")
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            if names & holders:
                refusal = _refuses(node.body) or _refuses(node.orelse)
                if refusal:
                    return (DOOR_REFUSES,
                            f"{refusal} по часовому {helper}() на строке {node.lineno}")
        if sentinel == SENTINEL_EMPTY and isinstance(node, ast.Assert):
            names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            if names & holders:
                return (DOOR_REFUSES,
                        f"assert по пустоте {helper}() на строке {node.lineno}")
    door, evidence = anti_vacuity(tree, helper, holders)
    if door:
        return door, evidence
    if sentinel == SENTINEL_EMPTY:
        return (DOOR_EMPTY,
                f"{helper}() отвечает ПУСТЫМ перечнем, отказа по пустоте нет")
    return DOOR_NONE, f"часовой {helper}() возвращается, отказа по нему нет"


#: Обороты, которыми подстановка объявляется прозой. Объявление вердикт НЕ
#: меняет (инв. #17: докстрока не есть отдельное ЗНАЧЕНИЕ исхода) — оно лишь
#: отличает осознанный приём от недосмотра, и это разные карточки.
_DECLARED_PHRASES = (
    "falls back", "fall back", "fallback", "hermetic", "self-contained",
    "if the live", "if absent", "when absent", "подстанов", "запасн",
)


def declared_fallback(scope: ast.AST) -> str:
    doc = ast.get_docstring(scope) if isinstance(
        scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module,
                ast.ClassDef)) else None
    if not doc:
        return ""
    lowered = doc.lower()
    for phrase in _DECLARED_PHRASES:
        if phrase in lowered:
            return phrase
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# 4. Население
# ══════════════════════════════════════════════════════════════════════════════

def _enumeration_sites(tree: ast.Module) -> List[Tuple[ast.AST, ast.Call]]:
    """Места, где перечень ОБХОДИТСЯ: `for` и включения."""
    out: List[Tuple[ast.AST, ast.Call]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            source = node.iter
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp,
                               ast.DictComp)):
            source = node.generators[0].iter
        else:
            continue
        call = unwrap(source)
        if isinstance(call, ast.Call):
            out.append((node, call))
    return out


def _parents(tree: ast.Module) -> Dict[ast.AST, ast.AST]:
    out: Dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def _enclosing(node: ast.AST, parents: Dict[ast.AST, ast.AST],
               tree: ast.Module) -> Tuple[ast.AST, List[ast.AST]]:
    """``(ближайшая функция-или-модуль, цепочка областей снаружи внутрь)``."""
    chain: List[ast.AST] = []
    cur = node
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            chain.append(cur)
    nearest = chain[0] if chain else tree
    return nearest, chain


def row_key(guard_rel: str, lineno: int, anchor: str) -> str:
    return f"{guard_rel}::{lineno}::{anchor}"


def population(root: Path) -> Tuple[List[dict], Dict[str, int], List[dict]]:
    """``(строки-входы репозитория, счётчик расположений, нечитаемые файлы)``."""
    rows: List[dict] = []
    places = {PLACE_REPO: 0, PLACE_FIXTURE: 0, PLACE_OUTSIDE: 0,
              PLACE_UNRESOLVED: 0}
    unreadable: List[dict] = []
    for path in census._guard_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
            # filename= обязателен: без него предупреждение разбора печатает
            # `<unknown>:74` и по такой строке действовать нельзя (ADR-420).
            tree = ast.parse(source, filename=rel)
        except (OSError, SyntaxError) as exc:
            unreadable.append({"guard": rel,
                               "reason": f"{type(exc).__name__}: {exc}"})
            continue
        parents = _parents(tree)
        module_scope = _assignments_toplevel(tree)
        for node, call in _enumeration_sites(tree):
            kind, base = source_of(call)
            if kind is None:
                continue
            nearest, chain = _enclosing(node, parents, tree)
            scopes = [_assignments(s) for s in chain] + [module_scope]
            value = resolve(base, scopes, path)
            if value is _FIXTURE:
                places[PLACE_FIXTURE] += 1
                continue
            if not isinstance(value, Path):
                places[PLACE_UNRESOLVED] += 1
                continue
            try:
                resolved = value.resolve()
            except OSError:
                places[PLACE_UNRESOLVED] += 1
                continue
            if resolved != root and root not in resolved.parents:
                places[PLACE_OUTSIDE] += 1
                continue
            places[PLACE_REPO] += 1
            try:
                anchor = ast.unparse(base)
            except Exception:      # noqa: BLE001
                anchor = ""
            door, evidence = classify_door(nearest, anchor) if anchor \
                else (DOOR_UNMEASURED, "выражение пути не разбирается обратно")
            if door == DOOR_NONE and isinstance(
                    nearest, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Проверки существования нет — но контроль на вхолостую может
                # стоять и без неё. Не спросив, перепись назвала бы
                # «двери нет» там, где дверь есть и она другого рода.
                guarded, why = anti_vacuity(
                    tree, nearest.name, holders_of(tree, nearest.name))
                if guarded:
                    door, evidence = guarded, why
            if door.startswith("returns_sentinel:"):
                sentinel = door.split(":", 1)[1]
                if isinstance(nearest, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    door, evidence = sentinel_handled(tree, nearest.name, sentinel)
                else:
                    door, evidence = DOOR_UNMEASURED, "часовой вне функции"
            rows.append({
                "key": row_key(rel, node.lineno, anchor),
                "guard": rel,
                "line": node.lineno,
                "scope": getattr(nearest, "name", "<module>"),
                "kind": kind,
                "anchor": anchor,
                "path": resolved.relative_to(root).as_posix() if resolved != root else ".",
                "present_here": PRESENT_YES if resolved.exists() else PRESENT_NO,
                "door": door,
                "door_evidence": evidence,
                "declared_in_docstring": declared_fallback(nearest),
                "guard_sha": _sha256(path),
            })
    return rows, places, unreadable


def _assignments_toplevel(tree: ast.Module) -> Dict[str, ast.AST]:
    out: Dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            out.setdefault(node.targets[0].id, node.value)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 5. Замер
# ══════════════════════════════════════════════════════════════════════════════

def behaviour_of(row: dict, ledger: Dict[str, dict],
                 reason: Optional[str]) -> dict:
    """Вердикт ПРОГОНА для строки — из журнала зонда `absent_path_probe`.

    Журнал устаревает САМ и в безопасную сторону: запись годится, только если
    совпал sha сторожа. Любая правка сторожа отменяет вердикт зонда, и строка
    возвращается к статическому приближению — то есть НА учёт, а не с учёта.
    Расписания зонду поэтому не нужно: протухший журнал не молчит, он
    перестаёт отвечать.

    `scene_destroyed` и `unmeasured` вердиктом о слепоте НЕ являются и здесь
    отделены от отсутствия записи: «опыт поставлен и ничего не сказал» и
    «опыта не было» — два разных состояния (инв. #17).
    """
    entry = ledger.get(str(row.get("key")))
    if entry is None:
        return {"behaviour": None, "behaviour_disagrees": False,
                "behaviour_evidence": reason or "прогона по этой строке нет"}
    if entry.get("guard_sha") != row.get("guard_sha"):
        return {"behaviour": None, "behaviour_disagrees": False,
                "behaviour_evidence": ("запись прогона снята с ДРУГОЙ редакции "
                                       "сторожа — вердикт отменён")}
    verdict = entry.get("verdict")
    if not isinstance(verdict, str) or verdict in BEHAVIOUR_NO_VERDICT:
        return {"behaviour": None, "behaviour_disagrees": False,
                "behaviour_evidence": str(entry.get("evidence") or "")}
    return {"behaviour": verdict,
            # Согласие статики с прогоном считает ЗОНД и кладёт в журнал.
            # Считать его здесь второй раз значило бы завести вторую копию
            # правила «от какой двери ждётся отказ» (ADR-417).
            "behaviour_disagrees": entry.get("static_agrees") is False,
            "behaviour_evidence": str(entry.get("evidence") or "")}


def is_finding(row: dict) -> bool:
    """Строка-находка.

    `substitutes` — находка ВСЕГДА: предмет подменяется молча, и зелёный исход
    ничем не отличает «проверен настоящий артефакт» от «проверена строка,
    которую тест сам же и написал».

    `empty_sentinel` — находка ВСЕГДА: проверка отсутствия ЕСТЬ, и её ответ —
    пустой перечень. Автор отсутствие увидел и выбрал промолчать, а инвариант
    #17 требует, чтобы «не измерено» было ОТДЕЛЬНЫМ значением, а не нулём.
    Присутствие пути сегодня этого не лечит: дверь открыта в любом дереве, где
    каталога нет, — а такие деревья у нас предписаны протоколом.

    `no_door` — находка ТОЛЬКО там, где пути в этом дереве нет: тогда это не
    риск, а сегодняшнее состояние сторожа. При живом пути та же строка
    остаётся `latent` и в находки не идёт — иначе перепись объявляла бы
    находкой всякий обход каталога.
    """
    behaviour = row.get("behaviour")
    if behaviour:
        # Право на вердикт даёт ПРОГОН. Статика остаётся дешёвым приближением,
        # и замер 19.09 показал, чего она стои́т: у входа рода `file_read`
        # отсутствие пути не даёт пустого перечня — оно ПОДНИМАЕТ ИСКЛЮЧЕНИЕ,
        # и сторож, названный статикой слепым, краснеет громко.
        return behaviour == BEHAVIOUR_VACUOUS
    if row.get("door") in (DOOR_SUBSTITUTES, DOOR_EMPTY):
        return True
    return row.get("door") == DOOR_NONE and row.get("present_here") == PRESENT_NO


def measure(root: Path, *, now: Optional[dt.datetime] = None) -> dict:
    root = Path(root).resolve()
    if not root.is_dir():
        # Причина обязана отличаться от «в дереве нет каталогов-сторожей»:
        # это два разных состояния мира, и слить их значило бы сделать
        # «дерева нет» неотличимым от «дерево есть, сторожей в нём нет».
        raise NotMeasured(f"корень дерева не прочитан: {root}")
    try:
        rows, places, unreadable = population(root)
    except census.NotMeasured as exc:
        # Отказ ввезённого читателя населения обязан быть исходом ЭТОГО
        # прибора, а не трассировкой чужого класса.
        raise NotMeasured(str(exc)) from exc
    ledger, ledger_reason = census.load_probe_ledger(root / BEHAVIOUR_LEDGER)
    doors = {d: 0 for d in DOORS}
    for row in rows:
        doors[row["door"]] = doors.get(row["door"], 0) + 1
        row.update(behaviour_of(row, ledger, ledger_reason))
        row["finding"] = is_finding(row)
    findings = [r for r in rows if r["finding"]]
    absent = [r for r in rows if r["present_here"] == PRESENT_NO]
    latent = [r for r in rows
              if r["door"] in GREEN_DOORS and r["present_here"] == PRESENT_YES
              and not r["finding"]]
    guards = sorted({r["guard"] for r in rows})
    behaviour_measured = [r for r in rows if r.get("behaviour")]
    behaviour_disagrees = [r for r in rows if r.get("behaviour_disagrees")]
    resolved_total = places[PLACE_REPO] + places[PLACE_FIXTURE] + places[PLACE_OUTSIDE]
    seen_total = resolved_total + places[PLACE_UNRESOLVED]
    return {
        "generated_at": (now or _utcnow()).isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "status": "CRITICAL" if findings else "MEASURED",
        "question": "что делает сторож, когда его вход-перечень, собранный ВЫЗОВОМ, пуст",
        "order": "G45 п. 1 (хвост ADR-420)",
        "guard_dirs": list(GUARD_DIRS),
        "tree": str(root),
        "rows": rows,
        "guards": len(guards),
        "inputs": len(rows),
        "places": places,
        "sites_seen": seen_total,
        "unresolved_share": (round(places[PLACE_UNRESOLVED] / seen_total, 4)
                             if seen_total else None),
        "doors": doors,
        "findings": len(findings),
        "absent_here": len(absent),
        "latent": len(latent),
        "behaviour_ledger": BEHAVIOUR_LEDGER,
        "behaviour_ledger_reason": ledger_reason or "",
        "behaviour_measured": len(behaviour_measured),
        "behaviour_disagrees": len(behaviour_disagrees),
        "unreadable": unreadable,
        "what_it_does_not_prove": [
            "что перепись полна: доля невычисленных путей (`unresolved`) печатается рядом с ответом и в население НЕ входит — это третий исход, а не ноль",
            "что `refuses_or_skips` означает исправного сторожа — он означает лишь, что сторож СКАЗАЛ, что не смотрел; в таком дереве он не охраняет ничего",
            "что `substitutes` есть ошибка автора: приём может быть осознанным (`declared_in_docstring`), но докстрока не есть отдельное ЗНАЧЕНИЕ исхода, а инв. #17 требует именно значения",
            "что `latent` безопасен — путь есть СЕГОДНЯ и в ЭТОМ дереве; в свежем worktree каталоги из `.gitignore` отсутствуют по построению",
            "что дверь разобрана верно в каждой строке: последствие ветки читается статикой, и ветка, отказывающая окольно (флаг + `assert` после цикла), будет прочтена как `no_door`",
            "что пустой перечень слепит КАЖДОГО потребителя: у одного теста он гасит находки, у соседнего (`n not in _collect()`) наоборот КРАСНИТ — координата переписи есть место сбора перечня, а не исход у потребителя; исход мерит прогон, а не эта статика",
            "что строка БЕЗ записи прогона исправна — запись зонда отменяется любой правкой сторожа (сверка по sha), и строка возвращается на учёт, а не уходит с него",
            "что `fixture_tree` безвреден — он лишь не есть ВХОД сторожа: каталог построен тем же тестом",
        ],
    }


def report(doc: dict, *, max_rows: int = 25) -> List[str]:
    status = str(doc.get("status"))
    if status == "UNMEASURED":
        return [f"НЕ ИЗМЕРЕНО — {doc.get('reason') or 'причина не записана'}"]
    doors = doc.get("doors") or {}
    places = doc.get("places") or {}
    share = doc.get("unresolved_share")
    out = [
        f"перепись входов, собранных ВЫЗОВОМ (заказ G45 п. 1): {status} · "
        f"сторожей {doc.get('guards')} · входов дерева {doc.get('inputs')} · "
        f"НАХОДОК {doc.get('findings')}",
        f"[ДВЕРИ] отказ/скип {doors.get(DOOR_REFUSES)} · ПОДСТАНОВКА "
        f"{doors.get(DOOR_SUBSTITUTES)} · ПУСТОЙ ЧАСОВОЙ {doors.get(DOOR_EMPTY)} "
        f"(отсутствие выдано за ноль, инв. #17) · двери нет "
        f"{doors.get(DOOR_NONE)} · краснеет СОСЕД {doors.get(DOOR_ELSEWHERE)} "
        f"(защита есть, но потребитель перечня вырожден) · НЕ ИЗМЕРЕНО "
        f"{doors.get(DOOR_UNMEASURED)}",
        f"[НАСЕЛЕНИЕ] осмотрено мест {doc.get('sites_seen')}: дерево репозитория "
        f"{places.get(PLACE_REPO)} · фикстура {places.get(PLACE_FIXTURE)} (не вход: "
        f"каталог строит сам тест) · вне репозитория {places.get(PLACE_OUTSIDE)} · "
        f"НЕ ВЫЧИСЛЕН путь {places.get(PLACE_UNRESOLVED)}"
        + (f" = {share:.1%} осмотренного" if isinstance(share, float) else ""),
        f"[СЕГОДНЯ] входов, которых в ЭТОМ дереве НЕТ: {doc.get('absent_here')}; "
        f"зелёных при живом пути (латентных) {doc.get('latent')}",
        f"[ПРОГОНОМ] вердикт зонда есть у {doc.get('behaviour_measured')} строк(и); "
        f"статика РАЗОШЛАСЬ с прогоном у {doc.get('behaviour_disagrees')}"
        + (f" · журнала нет: {doc.get('behaviour_ledger_reason')}"
           if doc.get("behaviour_ledger_reason") else ""),
    ]
    if doc.get("unreadable"):
        out.append(f"[НЕ ИЗМЕРЕНО] файлов сторожей не разобрано: "
                   f"{len(doc.get('unreadable') or [])}")
    shown = [r for r in (doc.get("rows") or []) if r.get("finding")]
    for row in shown[:max_rows]:
        declared = (f" · объявлено прозой: «{row.get('declared_in_docstring')}»"
                    if row.get("declared_in_docstring") else "")
        # Кто вынес вердикт, обязано быть видно в самой строке: «зелен по
        # разбору» и «зелен в прогоне» — разной силы утверждения, и слить их
        # значило бы выдать приближение за замер.
        label = (f"ПРОГОН:{row.get('behaviour')}" if row.get("behaviour")
                 else row.get("door"))
        why = (row.get("behaviour_evidence") if row.get("behaviour")
               else row.get("door_evidence")) or "—"
        out.append(f"[{label}] {row.get('guard')}:{row.get('line')} "
                   f"({row.get('scope')}) · {row.get('kind')} по «{row.get('path')}» "
                   f"({row.get('present_here')}): {why}{declared}")
    if len(shown) > max_rows:
        out.append(f"… ещё {len(shown) - max_rows} находок(и) — полный перечень в артефакте")
    out.append("НЕ ДОКЛАДЫВАЕТ: верность самого правила сторожа · строки БЕЗ "
               "записи зонда — их дверь разобрана статикой и прогоном не "
               "проверена · входы, чей путь не вычислен — они НЕ ноль, а "
               "третий исход")
    return out


def format_report(doc: dict, *, max_rows: int = 5) -> List[str]:
    """Короткая форма для шага 0-офис."""
    return report(doc, max_rows=max_rows)


def run(root: str | Path = _ROOT, *, dest: Optional[Path] = None,
        write: bool = True, now: Optional[dt.datetime] = None) -> dict:
    root = Path(root)
    target = Path(dest) if dest is not None else root / "data" / ARTIFACT
    try:
        doc = measure(root, now=now)
    except NotMeasured as exc:
        doc = {
            "generated_at": (now or _utcnow()).isoformat(),
            "generated_by": PRODUCER,
            "invoked_by": call_provenance(tree_root=root),
            "status": "UNMEASURED",
            "reason": str(exc),
            "rows": [],
        }
    if write:
        atomic_save(doc, str(target))
    return {"measured": doc.get("status") != "UNMEASURED", "doc": doc,
            "artifact": str(target)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись входов-перечней, собранных вызовом (G45 п. 1)")
    ap.add_argument("--root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--max-rows", type=int, default=25)
    args = ap.parse_args(argv)

    outcome = run(Path(args.root), dest=Path(args.out) if args.out else None,
                  write=not args.no_write)
    doc = outcome["doc"]
    for line in report(doc, max_rows=args.max_rows):
        print(line)
    if str(doc.get("status")) == "UNMEASURED":
        return 2
    return 1 if doc.get("findings") or (doc.get("doors") or {}).get(DOOR_UNMEASURED) else 0


if __name__ == "__main__":
    raise SystemExit(main())
