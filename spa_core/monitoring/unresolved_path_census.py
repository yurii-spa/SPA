"""Сколько невычисленных путей разрешимо УЖЕСТОЧЕНИЕМ вычислителя.

Заказ **G46, п. 2** приказа владельца «Portfolio CIO» — дословный хвост
ADR-421:

    «195 невычисленных путей — 43 % осмотренного. Считать, сколько из них
    разрешимы ужесточением вычислителя (параметр функции, `self.X` вне
    `setUp`), а сколько неразрешимы по существу. Пока доля не измерена,
    ответ переписи — нижняя граница, и это сказано вслух.»

## Ужесточение — это ОБЛАСТЬ ИМЁН, а не второй вычислитель

Соблазн был написать `resolve_tight()` рядом с `call_sourced_input_census.
resolve()`. Это ровно тот дефект, который меряет ADR-417: одно правило в двух
копиях, и расходиться они начнут молча. Поэтому вычислитель здесь ОДИН —
ввезённый, — а ужесточение подаётся ему ДОПОЛНИТЕЛЬНОЙ ОБЛАСТЬЮ ИМЁН,
подставляемой перед остальными. Каждое расширение отвечает на вопрос «чем
ещё может быть связано это имя», и ни одно не трогает разбор выражений.

## Пять расширений, и порядок их объявлен

| расширение | чем связывает имя |
|---|---|
| `self_attr_from_base_class` | `self.X` присвоен в БАЗОВОМ классе того же файла |
| `parameter_default` | имя — параметр объемлющей функции с вычислимым умолчанием |
| `local_helper_return` | имя получено вызовом функции ЭТОГО файла — берётся её `return` |
| `loop_variable_over_literals` | имя — переменная `for` по литеральному перечню |
| `call_site_argument` | имя — параметр локальной функции, и ВСЕ её вызовы передают одно выражение |

Порядок нужен не красоты ради: расширения применяются НАКОПИТЕЛЬНО, и
«сработавшим» зовётся то, с добавлением которого путь вычислился. Без
объявленного порядка это число было бы впечатлением.

**Украшение отсекается замером, а не обещанием.** У каждого расширения
считается ПРЕДЕЛЬНЫЙ вклад: сколько строк теряется, если убрать одно его при
всех остальных. Расширение с нулевым предельным вкладом неотличимо от своего
отсутствия и подлежит снятию (`positive-control-can-be-an-ornament`).

## Третий исход (инв. #17)

Невычисленный остаток не ноль и не «прочее»: у каждой строки названа ПРИЧИНА
(`caller_supplied`, `external_call`, `subscript_of_non_literal`,
`name_unbound`, `expression_form`). Нечитаемый файл — `unreadable`, отсутствие
каталогов-сторожей — громкий отказ, а не пустая перепись.

## Чего перепись НЕ делает

Она не чинит вычислитель. Требование заказа — СЧИТАТЬ, и число «нижняя
граница поднимется на N» есть ответ; переносить расширения в сам вычислитель
значило бы менять население переписи той же правкой, которой его меряешь.
"""

from __future__ import annotations

import argparse
import ast
import copy
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # запуск ПО ПУТИ, а не пакетом
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import call_sourced_input_census as census  # noqa: E402
from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "unresolved_path_census.json"
PRODUCER = "spa_core/monitoring/unresolved_path_census.py"

NotMeasured = census.NotMeasured

# ── расширения вычислителя, в ОБЪЯВЛЕННОМ порядке накопления ──────────────────
EXT_BASE_ATTR = "self_attr_from_base_class"
EXT_PARAM_DEFAULT = "parameter_default"
EXT_HELPER_RETURN = "local_helper_return"
EXT_LOOP_LITERAL = "loop_variable_over_literals"
EXT_CALLSITE_ARG = "call_site_argument"
EXTENSIONS = (EXT_BASE_ATTR, EXT_PARAM_DEFAULT, EXT_HELPER_RETURN,
              EXT_LOOP_LITERAL, EXT_CALLSITE_ARG)

# ── причины остатка ───────────────────────────────────────────────────────────
WHY_CALLER = "caller_supplied"
WHY_EXTERNAL = "external_call"
WHY_SUBSCRIPT = "subscript_of_non_literal"
WHY_IMPORTED = "name_imported"
WHY_LOOP_VAR = "loop_variable_not_literal"
WHY_UNBOUND = "name_unbound"
WHY_FORM = "expression_form"
WHY_CYCLE = "binding_cycle"
WHY_MANY_LOOPS = "several_loop_variables"
REASONS = (WHY_CALLER, WHY_EXTERNAL, WHY_SUBSCRIPT, WHY_IMPORTED, WHY_LOOP_VAR,
           WHY_UNBOUND, WHY_FORM, WHY_CYCLE, WHY_MANY_LOOPS)

#: Сколько значений литерального перечня разворачивать. Перечень длиннее —
#: строка считается вычисленной, но пути берутся первые N: цель замера —
#: «вычислим ли путь», а не полный список.
MAX_LOOP_VALUES = 12


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Расширения: чем ЕЩЁ может быть связано имя
# ══════════════════════════════════════════════════════════════════════════════

def _class_bases(tree: ast.Module) -> Dict[str, List[str]]:
    """Имена базовых классов у каждого класса файла (только имена, не пути)."""
    out: Dict[str, List[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            out[node.name] = [b.id for b in node.bases if isinstance(b, ast.Name)]
    return out


def _classes(tree: ast.Module) -> Dict[str, ast.ClassDef]:
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}


def base_class_attrs(tree: ast.Module,
                     owner: Optional[ast.ClassDef]) -> Dict[str, ast.AST]:
    """`self.X`, присвоенные в БАЗОВЫХ классах того же файла.

    Замер 19.09, ради которого расширение и написано: `self.data_dir` у
    шестнадцати строк объявлен не в своём классе, а в общем предке
    (`class _TmpBase(unittest.TestCase)` с `setUp`). Вычислитель переписи
    смотрит цепочку ОБЛАСТЕЙ (метод → класс → модуль), а наследование областью
    не является: базовый класс лежит в файле РЯДОМ, а не снаружи.

    Обход идёт вверх по именам и защищён от цикла: файл с `class A(B)` и
    `class B(A)` синтаксически возможен, и вечный цикл здесь был бы отказом
    прибора, а не находкой.
    """
    if owner is None:
        return {}
    bases, classes = _class_bases(tree), _classes(tree)
    out: Dict[str, ast.AST] = {}
    seen: Set[str] = {owner.name}
    queue = list(bases.get(owner.name, []))
    while queue:
        name = queue.pop(0)
        if name in seen or name not in classes:
            continue
        seen.add(name)
        for key, value in census._assignments(classes[name]).items():
            if key.startswith("self."):
                out.setdefault(key, value)
        queue.extend(bases.get(name, []))
    return out


def parameter_defaults(chain: Sequence[ast.AST]) -> Dict[str, ast.AST]:
    """Параметры объемлющих функций, у которых есть УМОЛЧАНИЕ.

    Параметр без умолчания сюда не попадает намеренно: его значение решает
    зовущий, и подставить вместо него что-либо значило бы выдумать путь.
    """
    out: Dict[str, ast.AST] = {}
    for scope in chain:
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = scope.args
        positional = list(args.posonlyargs) + list(args.args)
        for arg, default in zip(positional[len(positional) - len(args.defaults):],
                                args.defaults):
            out.setdefault(arg.arg, default)
        for arg, default in zip(args.kwonlyargs, args.kw_defaults):
            if default is not None:
                out.setdefault(arg.arg, default)
    return out


def _functions(tree: ast.Module) -> Dict[str, ast.AST]:
    out: Dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, node)
    return out


def _sole_return(func: ast.AST) -> Optional[ast.AST]:
    """Единственное возвращаемое выражение функции; ``None`` — их не одно.

    Две разные ветки `return` — это два разных пути, и выбрать из них один
    значило бы решить за код. Такая функция остаётся неразрешённой.
    """
    returns = [n.value for n in ast.walk(func)
               if isinstance(n, ast.Return) and n.value is not None]
    return returns[0] if len(returns) == 1 else None


def helper_returns(tree: ast.Module,
                   scopes: Sequence[Dict[str, ast.AST]]) -> Dict[str, ast.AST]:
    """Имена, связанные вызовом функции ЭТОГО файла → её `return`.

    `data = self.full_day(...)` вычислителю переписи выглядит вызовом и
    обрывает счёт. Но тело функции лежит в том же файле, и его единственный
    `return` есть выражение того же рода, что и всякое другое.
    """
    funcs = _functions(tree)
    out: Dict[str, ast.AST] = {}
    for scope in scopes:
        for name, value in scope.items():
            call = census.unwrap(value)
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            key = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name) and func.value.id == "self"
                else None)
            if key is None or key not in funcs:
                continue
            body = _sole_return(funcs[key])
            if body is not None:
                out.setdefault(name, body)
    return out


def _literal_values(node: ast.AST,
                    scopes: Sequence[Dict[str, ast.AST]]) -> Optional[List[ast.AST]]:
    """Элементы литерального перечня (возможно, спрятанного за именем)."""
    target = census.unwrap(node)
    if isinstance(target, ast.Name):
        for scope in scopes:
            if target.id in scope:
                return _literal_values(scope[target.id], scopes)
        return None
    if isinstance(target, (ast.Tuple, ast.List, ast.Set)):
        items = [e for e in target.elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        return items if len(items) == len(target.elts) and items else None
    return None


def loop_literals(node: ast.AST, parents: Dict[ast.AST, ast.AST],
                  scopes: Sequence[Dict[str, ast.AST]]) -> Dict[str, List[ast.AST]]:
    """Переменные объемлющих `for`, бегущих по ЛИТЕРАЛЬНОМУ перечню.

    Это и есть форма `for d in SCAN_DIRS: base = ROOT / d`, которой держится
    `tests/test_no_utcnow.py`: путь не «невычислим», он просто не один.
    """
    out: Dict[str, List[ast.AST]] = {}
    cur: Optional[ast.AST] = node
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, ast.For) and isinstance(cur.target, ast.Name):
            values = _literal_values(cur.iter, scopes)
            if values:
                out.setdefault(cur.target.id, values[:MAX_LOOP_VALUES])
        elif isinstance(cur, (ast.ListComp, ast.SetComp, ast.GeneratorExp,
                              ast.DictComp)):
            for gen in cur.generators:
                if isinstance(gen.target, ast.Name):
                    values = _literal_values(gen.iter, scopes)
                    if values:
                        out.setdefault(gen.target.id, values[:MAX_LOOP_VALUES])
    return out


def _params_without_default(chain: Sequence[ast.AST]) -> Dict[str, ast.AST]:
    """Параметры объемлющих функций БЕЗ умолчания → сама функция."""
    out: Dict[str, ast.AST] = {}
    for scope in chain:
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = scope.args
        named = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
        with_default = set(parameter_defaults([scope]))
        for arg in named:
            if arg.arg not in with_default and arg.arg != "self":
                out.setdefault(arg.arg, scope)
    return out


def call_site_arguments(tree: ast.Module,
                        chain: Sequence[ast.AST]) -> Dict[str, ast.AST]:
    """Параметр локальной функции, которому ВСЕ вызовы дают одно выражение.

    Правило намеренно строгое: если хоть один вызов передаёт другое выражение,
    имя не связывается вовсе. «Обычно передают то же» путём не является —
    это было бы угадыванием в пользу ответа, а не вычислением.
    """
    out: Dict[str, ast.AST] = {}
    for name, func in _params_without_default(chain).items():
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = func.args
        order = [a.arg for a in list(args.posonlyargs) + list(args.args)]
        if name not in order:
            continue
        index = order.index(name)
        passed: List[str] = []
        nodes: List[ast.AST] = []
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            target = call.func
            called = target.id if isinstance(target, ast.Name) else (
                target.attr if isinstance(target, ast.Attribute) else None)
            if called != func.name:
                continue
            bound: Optional[ast.AST] = None
            if len(call.args) > index:
                bound = call.args[index]
            else:
                for kw in call.keywords:
                    if kw.arg == name:
                        bound = kw.value
            if bound is None:
                passed.append("<нет>")
                continue
            try:
                passed.append(ast.unparse(bound))
            except Exception:      # noqa: BLE001
                passed.append("<не разобрано>")
            nodes.append(bound)
        if nodes and len(set(passed)) == 1 and "<нет>" not in passed:
            out.setdefault(name, nodes[0])
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 2. Вычисление с накопленными расширениями
# ══════════════════════════════════════════════════════════════════════════════

class Site:
    """Место обхода, чей путь вычислитель переписи не взял."""

    __slots__ = ("guard", "line", "kind", "anchor", "scope", "base", "here",
                 "scopes", "extras", "loops", "imports", "loop_targets")

    def __init__(self, *, guard: str, line: int, kind: str, anchor: str,
                 scope: str, base: ast.AST, here: Path,
                 scopes: List[Dict[str, ast.AST]],
                 extras: Dict[str, Dict[str, ast.AST]],
                 loops: Dict[str, List[ast.AST]],
                 imports: Set[str], loop_targets: Set[str]):
        self.guard, self.line, self.kind = guard, line, kind
        self.anchor, self.scope, self.base, self.here = anchor, scope, base, here
        self.scopes, self.extras, self.loops = scopes, extras, loops
        self.imports, self.loop_targets = imports, loop_targets


class _Substitute(ast.NodeTransformer):
    """Подстановка значения вместо имени — в КОПИИ дерева.

    Переменная цикла не связывается областью: `for d in SCAN_DIRS` и потом
    `ROOT / d`. Положить `d` в область недостаточно — вычислитель требует на
    правой стороне `/` именно ЛИТЕРАЛ и через область туда не заглядывает.
    Поэтому значение подставляется в выражение, а вычислитель остаётся ОДИН
    и нетронутым: ему просто подают другое выражение.

    Замер 19.09 ровно этим и опроверг первую редакцию расширения: поданное
    областью, оно имело предельный вклад НОЛЬ — то есть было неотличимо от
    своего отсутствия.
    """

    def __init__(self, name: str, value: ast.AST):
        self.name, self.value = name, value

    def visit_Name(self, node: ast.Name) -> ast.AST:      # noqa: N802
        if isinstance(node.ctx, ast.Load) and node.id == self.name:
            return ast.copy_location(copy.deepcopy(self.value), node)
        return node


def _resolve_with(site: Site, enabled: Sequence[str]) -> Optional[List[object]]:
    """Вычислить путь(и) с включёнными расширениями; ``None`` — не вышло.

    Возвращается СПИСОК: переменная цикла по литеральному перечню даёт
    столько путей, сколько в перечне элементов, и сводить их к одному значило
    бы потерять половину входа.
    """
    extra: Dict[str, ast.AST] = {}
    for name in enabled:
        if name == EXT_LOOP_LITERAL:
            continue
        extra.update(site.extras.get(name, {}))
    loop_names = site.loops if EXT_LOOP_LITERAL in enabled else {}
    if len(loop_names) > 1:
        return None
    scopes = [extra] + list(site.scopes)
    if not loop_names:
        value = census.resolve(site.base, scopes, site.here)
        if value is census._FIXTURE:
            return [census._FIXTURE]
        return [value] if isinstance(value, Path) else None

    name, values = next(iter(loop_names.items()))
    out: List[object] = []
    for item in values:
        swap = _Substitute(name, item)
        node = swap.visit(copy.deepcopy(site.base))
        swapped = [{k: swap.visit(copy.deepcopy(v)) for k, v in scope.items()}
                   for scope in scopes]
        value = census.resolve(node, swapped, site.here)
        if value is census._FIXTURE:
            out.append(census._FIXTURE)
            continue
        if not isinstance(value, Path):
            return None
        out.append(value)
    return out or None


def _place(values: List[object], root: Path) -> Tuple[str, List[str]]:
    """Куда легли вычисленные пути и как они называются относительно корня."""
    if any(v is census._FIXTURE for v in values):
        return census.PLACE_FIXTURE, []
    names: List[str] = []
    inside = True
    for value in values:
        try:
            resolved = Path(value).resolve()
        except OSError:
            return census.PLACE_UNRESOLVED, []
        if resolved != root and root not in resolved.parents:
            inside = False
            names.append(str(resolved))
            continue
        names.append(resolved.relative_to(root).as_posix() if resolved != root else ".")
    return (census.PLACE_REPO if inside else census.PLACE_OUTSIDE), names


def imported_names(tree: ast.Module) -> Set[str]:
    """Имена, ВВЕЗЁННЫЕ в файл. Их значение живёт в другом модуле, не здесь."""
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                out.add(alias.asname or alias.name.split(".")[0])
    return out


def loop_target_names(tree: ast.Module) -> Set[str]:
    """Имена, связываемые ЦИКЛОМ где-либо в файле (не важно, по чему он бежит)."""
    out: Set[str] = set()
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.For):
            targets = [node.target]
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp,
                               ast.DictComp)):
            targets = [g.target for g in node.generators]
        for target in targets:
            if isinstance(target, ast.Name):
                out.add(target.id)
    return out


def referenced(node: ast.AST, namespaces: Optional[Set[str]] = None) -> List[ast.AST]:
    """Имена-ЗНАЧЕНИЯ выражения — то, чем МОЖЕТ БЫТЬ путь.

    Вызываемое имя значением не является: в `Path(data)` путь несёт `data`, а
    не `Path`. Не отделив одно от другого, разбор остатка обвинял бы в
    невычислимости конструктор — замер 19.09 дал ровно такую строку
    («имена не связаны: Path») и тем показал, что вопрос задан не о том.

    ``namespaces`` — ВВЕЗЁННЫЕ имена. В `pathlib.Path(d)` путь несёт `d`, а
    `pathlib` есть пространство имён вызываемого; без этого отсева виновным
    назначался модуль, и вторая редакция замера дала двадцать одну такую
    строку. Различие проходит именно по ввозу: в `base.rglob(...)` та же
    форма записи, но `base` — значение, и обвинять его верно.
    """
    namespaces = namespaces or set()
    callee: Set[int] = set()
    selfattrs: List[ast.AST] = []
    for item in ast.walk(node):
        if isinstance(item, ast.Call):
            func = item.func
            if isinstance(func, ast.Name):
                callee.add(id(func))
            elif isinstance(func, ast.Attribute):
                root = func.value
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id in namespaces:
                    callee.add(id(root))
        if isinstance(item, ast.Attribute) and isinstance(item.value, ast.Name) \
                and item.value.id == "self":
            selfattrs.append(item)
            callee.add(id(item.value))
    plain = [item for item in ast.walk(node)
             if isinstance(item, ast.Name) and id(item) not in callee
             and item.id != "self"]
    return selfattrs + plain


def _key_of(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return "self." + node.attr
    return getattr(node, "id", "?")


def why_unresolved(site: Site) -> Tuple[str, str]:
    """Причина остатка и её основание — по ЦЕПОЧКЕ СВЯЗЫВАНИЯ, а не по виду.

    Вопрос «чем это выражение не взялось» нельзя ответить, глядя на само
    выражение: `bee_dir` невычислим не потому, что он имя, а потому, что его
    ЗНАЧЕНИЕ упирается во что-то ещё. Поэтому разбор идёт вниз по связыванию:
    имя → его значение → имена того значения, — пока не дойдёт до листа,
    которого не берёт сам вычислитель. Второго вычислителя здесь нет: у
    ввезённого спрашивается ровно один вопрос — «берёшь ли ты это имя».
    """
    if len(site.loops) > 1:
        return WHY_MANY_LOOPS, (f"переменных цикла {len(site.loops)}: сведение "
                                f"к одной было бы выбором за код")
    scopes = [site.extras.get(name, {}) for name in EXTENSIONS] + list(site.scopes)
    node: ast.AST = site.base
    seen: Set[str] = set()
    for _ in range(24):
        if isinstance(node, ast.Subscript):
            return WHY_SUBSCRIPT, (f"путь берётся из отображения по ключу: "
                                   f"`{_unparse(node)}`")
        call = census.unwrap(node)
        if isinstance(call, ast.Call):
            func = call.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else "?")
            if name not in {"Path", "str", "resolve", "absolute", "expanduser",
                            "joinpath"}:
                return WHY_EXTERNAL, (f"путь получен вызовом `{name}`, чьё тело "
                                      f"вычислителю недоступно")
        failing = [item for item in referenced(node, site.imports)
                   if census.resolve(item, scopes, site.here) is None]
        if not failing:
            return WHY_FORM, (f"все имена берутся, а форма выражения — нет: "
                              f"`{_unparse(node)}`")
        leaf = failing[0]
        key = _key_of(leaf)
        binding = next((scope[key] for scope in scopes if key in scope), None)
        # Связывание ВИДА `root = Path(root)` замыкается на себя, и «цикл» тут
        # не причина, а форма записи: значение всё равно приходит извне.
        # Поэтому повтор имени разбирается ТАК ЖЕ, как его отсутствие, и
        # `binding_cycle` остаётся только для того, чему имени не нашлось.
        if binding is None or key in seen:
            if key in site.extras.get("_params_no_default", {}):
                return WHY_CALLER, (f"`{key}` — параметр без умолчания: значение "
                                    f"решает зовущий, а не выражение")
            if key in site.imports:
                return WHY_IMPORTED, (f"`{key}` ввезено из другого модуля — "
                                      f"значение живёт там, а не в этом файле")
            if key in site.loop_targets:
                return WHY_LOOP_VAR, (f"`{key}` связывается циклом, бегущим не "
                                      f"по литеральному перечню")
            if binding is None:
                return WHY_UNBOUND, f"`{key}` не связано ни одной областью файла"
            return WHY_CYCLE, f"связывание `{key}` замкнуто само на себя"
        seen.add(key)
        node = binding
    return WHY_CYCLE, "цепочка связывания глубже 24 шагов — разбор прекращён"


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:      # noqa: BLE001
        return "<не разобрано>"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Население
# ══════════════════════════════════════════════════════════════════════════════

def collect(root: Path) -> Tuple[List[Site], Dict[str, int], List[dict]]:
    """Места обхода, чей путь ПЕРЕПИСЬ не вычислила, — и только они."""
    sites: List[Site] = []
    seen = {"sites_total": 0, "resolved_by_census": 0}
    unreadable: List[dict] = []
    for path in census.census._guard_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (OSError, SyntaxError) as exc:
            unreadable.append({"guard": rel, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        parents = census._parents(tree)
        module_scope = census._assignments_toplevel(tree)
        imports, targets = imported_names(tree), loop_target_names(tree)
        for node, call in census._enumeration_sites(tree):
            kind, base = census.source_of(call)
            if kind is None:
                continue
            seen["sites_total"] += 1
            nearest, chain = census._enclosing(node, parents, tree)
            scopes = [census._assignments(s) for s in chain] + [module_scope]
            value = census.resolve(base, scopes, path)
            if value is census._FIXTURE or isinstance(value, Path):
                seen["resolved_by_census"] += 1
                continue
            owner = next((c for c in chain if isinstance(c, ast.ClassDef)), None)
            extras = {
                EXT_BASE_ATTR: base_class_attrs(tree, owner),
                EXT_PARAM_DEFAULT: parameter_defaults(chain),
                EXT_HELPER_RETURN: helper_returns(tree, scopes),
                EXT_CALLSITE_ARG: call_site_arguments(tree, chain),
                "_params_no_default": _params_without_default(chain),
            }
            try:
                anchor = ast.unparse(base)
            except Exception:      # noqa: BLE001
                anchor = ""
            sites.append(Site(
                guard=rel, line=node.lineno, kind=kind, anchor=anchor,
                scope=getattr(nearest, "name", "<module>"), base=base, here=path,
                scopes=scopes, extras=extras,
                loops=loop_literals(node, parents, scopes),
                imports=imports, loop_targets=targets))
    return sites, seen, unreadable


# ══════════════════════════════════════════════════════════════════════════════
# 4. Замер
# ══════════════════════════════════════════════════════════════════════════════

def measure(root: Path, *, now: Optional[dt.datetime] = None) -> dict:
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotMeasured(f"корень дерева не прочитан: {root}")
    try:
        sites, seen, unreadable = collect(root)
    except census.census.NotMeasured as exc:
        raise NotMeasured(str(exc)) from exc

    rows: List[dict] = []
    by_extension = {e: 0 for e in EXTENSIONS}
    by_reason = {r: 0 for r in REASONS}
    by_place = {census.PLACE_REPO: 0, census.PLACE_FIXTURE: 0,
                census.PLACE_OUTSIDE: 0, census.PLACE_UNRESOLVED: 0}
    for site in sites:
        row = {"guard": site.guard, "line": site.line, "kind": site.kind,
               "scope": site.scope, "anchor": site.anchor,
               "resolved_by": None, "place": None, "paths": [],
               "reason": None, "evidence": ""}
        for cut in range(1, len(EXTENSIONS) + 1):
            values = _resolve_with(site, EXTENSIONS[:cut])
            if values is None:
                continue
            place, names = _place(values, root)
            row["resolved_by"] = EXTENSIONS[cut - 1]
            row["place"] = place
            row["paths"] = names[:MAX_LOOP_VALUES]
            by_extension[EXTENSIONS[cut - 1]] += 1
            by_place[place] += 1
            break
        if row["resolved_by"] is None:
            reason, evidence = why_unresolved(site)
            row["reason"], row["evidence"] = reason, evidence
            by_reason[reason] = by_reason.get(reason, 0) + 1
        rows.append(row)

    # Предельный вклад: сколько строк ТЕРЯЕТСЯ без одного расширения при всех
    # остальных. Ноль — расширение неотличимо от своего отсутствия.
    full = sum(1 for s in sites if _resolve_with(s, EXTENSIONS) is not None)
    marginal: Dict[str, int] = {}
    for name in EXTENSIONS:
        without = [e for e in EXTENSIONS if e != name]
        marginal[name] = full - sum(
            1 for s in sites if _resolve_with(s, without) is not None)

    resolved = [r for r in rows if r["resolved_by"]]
    new_population = [r for r in resolved if r["place"] == census.PLACE_REPO]
    return {
        "generated_at": (now or _utcnow()).isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "status": "MEASURED",
        "question": "сколько невычисленных путей разрешимо ужесточением вычислителя, а сколько неразрешимо по существу",
        "order": "G46 п. 2 (хвост ADR-421)",
        "tree": str(root),
        "sites_seen": seen["sites_total"],
        "resolved_by_census": seen["resolved_by_census"],
        "unresolved": len(sites),
        "resolved_by_tightening": len(resolved),
        "still_unresolved": len(sites) - len(resolved),
        "by_extension": by_extension,
        "by_place": by_place,
        "by_reason": by_reason,
        "marginal_contribution": marginal,
        "ornament_extensions": sorted(n for n, v in marginal.items() if v == 0),
        "new_repo_population": len(new_population),
        "extensions_order": list(EXTENSIONS),
        "rows": rows,
        "unreadable": unreadable,
        "what_it_does_not_prove": [
            "что вычислитель переписи ПОЧИНЕН: расширения живут здесь и в него не перенесены — заказ требовал СЧИТАТЬ, и правка меняла бы население тем же движением, каким его меряешь",
            "что `caller_supplied` неразрешим вообще: он неразрешим ВЫЧИСЛИТЕЛЕМ ВЫРАЖЕНИЯ; межпроцедурный разбор всех зовущих — другой прибор и другая цена",
            "что вычисленный путь есть ВХОД сторожа: часть их ляжет в фикстуру, и доля фикстуры печатается рядом",
            "что новая доля переписи равна `new_repo_population`: строка становится населением только вместе с разбором её ДВЕРИ, а дверь здесь не разбирается",
            "что перечень значений переменной цикла полон: берутся первые "
            f"{MAX_LOOP_VALUES}, и это названо",
            "что расширение верно в каждой строке: `local_helper_return` берёт ЕДИНСТВЕННЫЙ `return`, а функция с ветвлением остаётся неразрешённой — это отказ, а не вычисление",
        ],
    }


def report(doc: dict, *, max_rows: int = 20) -> List[str]:
    status = str(doc.get("status"))
    if status == "UNMEASURED":
        return [f"НЕ ИЗМЕРЕНО — {observed(doc, 'reason', kind=str) or 'причина не записана'}"]
    ext = observed(doc, "by_extension", kind=dict) or {}
    reasons = observed(doc, "by_reason", kind=dict) or {}
    place = observed(doc, "by_place", kind=dict) or {}
    total = doc.get("unresolved") or 0
    got = doc.get("resolved_by_tightening") or 0
    share = (got / total) if total else None
    out = [
        f"разрешимость невычисленных путей (заказ G46 п. 2): {status} · "
        f"невычисленных {total} · РАЗРЕШИМО УЖЕСТОЧЕНИЕМ {got}"
        + (f" = {share:.1%}" if share is not None else "")
        + f" · остаток {doc.get('still_unresolved')}",
        "[ЧЕМ РАЗРЕШЕНО] " + " · ".join(f"{k} {ext.get(k, 0)}" for k in EXTENSIONS),
        "[КУДА ЛЕГЛИ] дерево репозитория "
        f"{place.get(census.PLACE_REPO, 0)} · фикстура "
        f"{place.get(census.PLACE_FIXTURE, 0)} (не вход сторожа) · вне репозитория "
        f"{place.get(census.PLACE_OUTSIDE, 0)}",
        "[ОСТАТОК ПО ПРИЧИНАМ] " + " · ".join(
            f"{k} {reasons.get(k, 0)}" for k in REASONS if reasons.get(k)),
        f"[НИЖНЯЯ ГРАНИЦА] население переписи поднимается на "
        f"{doc.get('new_repo_population')} вход(ов) — это и есть цена молчания "
        f"о невычисленных путях",
        "[ПРЕДЕЛЬНЫЙ ВКЛАД] " + " · ".join(
            f"{k} {(observed(doc, 'marginal_contribution', kind=dict) or {}).get(k, 0)}"
            for k in EXTENSIONS),
    ]
    if doc.get("ornament_extensions"):
        out.append(f"[УКРАШЕНИЕ] расширения с нулевым предельным вкладом: "
                   f"{', '.join(doc['ornament_extensions'])} — неотличимы от своего отсутствия")
    shown = [r for r in (doc.get("rows") or [])
             if r.get("place") == census.PLACE_REPO]
    for row in shown[:max_rows]:
        out.append(f"[{row.get('resolved_by')}] {row.get('guard')}:{row.get('line')} "
                   f"({row.get('scope')}) · «{row.get('anchor')}» → "
                   f"{', '.join(row.get('paths') or []) or '—'}")
    if len(shown) > max_rows:
        out.append(f"… ещё {len(shown) - max_rows} строк(и) — полный перечень в артефакте")
    out.append("НЕ ДОКЛАДЫВАЕТ: дверь у новых входов (её разбирает перепись G45) · "
               "верность самих сторожей · межпроцедурный разбор зовущих — "
               "`caller_supplied` остаётся третьим исходом, а не нулём")
    return out


def format_report(doc: dict, *, max_rows: int = 4) -> List[str]:
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
        description="разрешимость невычисленных путей ужесточением вычислителя (G46 п. 2)")
    ap.add_argument("--root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--max-rows", type=int, default=20)
    args = ap.parse_args(argv)

    outcome = run(Path(args.root), dest=Path(args.out) if args.out else None,
                  write=not args.no_write)
    doc = outcome["doc"]
    for line in report(doc, max_rows=args.max_rows):
        print(line)
    if str(doc.get("status")) == "UNMEASURED":
        return 2
    return 1 if doc.get("new_repo_population") or doc.get("ornament_extensions") else 0


if __name__ == "__main__":
    raise SystemExit(main())
