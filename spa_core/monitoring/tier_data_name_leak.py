"""Доходит ли ИМЯ-ДАННЫЕ до диска ОКОЛЬНО — через чужого помощника.

Сосед по предмету — `spa_core/monitoring/tier_report_consumption.py` (ADR-1096):
тот решает РОЛЬ вхождения по НЕПОСРЕДСТВЕННОМУ родителю узла и потому честно
говорит о себе, чего не видит. Дословно из его решения:

> Роль выводится по НЕПОСРЕДСТВЕННОМУ родителю узла — имя, положенное в
> контейнер и утёкшее к файловой системе через общего помощника, видит только
> замыкание по второй половине пути, а не поток значения; **население класса
> «имя-данные, дошедшее до диска окольно» НЕ ИЗМЕРЕНО** и нулём это не
> считается.

Этот модуль и есть мерка того населения (заказ G1080 п. 2). Замыкание ADR-1096
(`assembled_path`) ищет ОБЕ половины пути в ОДНОМ модуле; класс, который оно
пропускает, — это модуль, отдающий голое имя НАРУЖУ, где путь собирает кто-то
другой. Поэтому мера спрашивает не «что лежит рядом в файле», а **кому передана
привязка** и что с параметром делает получатель.

## Почему мера УЖЕ класса «дошло до файловой системы»

Вопрос сторожа — «добирается ли модуль до ОТЧЁТА куратора», а не «трогает ли он
диск вообще». Помощник, который из переданного имени собирает
`data/cadence_census.json`, до отчёта куратора не добирается, и назвать его
потребителем значило бы завести меру ШИРЕ класса — ровно тот дефект, которым
прежняя подстрока красила верное состояние (ADR-1096). Поэтому исходов пять, и
классом является РОВНО один (`reaches_report`); `reaches_fs` печатается рядом как
НАЗВАННЫЙ контекст, а не как находка.

## Пять исходов, и три из них — не находка

| вердикт | что измерено | класс? |
|---|---|---|
| `reaches_report` | получатель в одном хопе собирает либо называет путь к отчёту | **ДА** |
| `reaches_fs` | получатель открывает путь, выведенный из параметра, но НЕ отчёт | нет, контекст |
| `selects_path` | значение сличается с путями, но ни одна дверь ФС в одном хопе не достигнута | нет, БЛИЖНИЙ промах |
| `local_only` | привязку не получает ни один зов — утечь через помощника нечему | нет |
| `unmeasured` | привязка либо получатель НЕ РАЗРЕШЕНЫ (инв. #17) | НЕ ИЗМЕРЕНО |

`local_only` — утверждение, а не умолчание: «ни один зов не получает привязку»
проверяется обходом, и пустое пересечение есть ИЗМЕРЕННЫЙ НОЛЬ.

## Чего мера НЕ закрывает

Хоп ОДИН: получатель, передающий значение ДАЛЬШЕ третьему, числится по тому, что
делает сам, и население за этой границей НЕ ИЗМЕРЕНО — нулём это не считается
(та же граница, о которую спотыкается сторож притязания `injected-clock`,
`.claude/rules/deployment.md` § девятая дверь). Поток значения внутри получателя
прослеживается ПО ИМЕНИ ПАРАМЕТРА, а не по SSA: переименование через промежуточную
переменную внутри помощника мера видит, переупаковку в чужой объект — нет.
Разбор чужого исходника — дело вызывающего: он подаёт `resolve`, и `None` от него
есть `unmeasured`, а не «чисто».
"""
from __future__ import annotations

import ast
import builtins as _builtins
from dataclasses import dataclass
from typing import Callable, Optional

from spa_core.monitoring.tier_report_consumption import (
    MODULE_TOKEN,
    REPORT_SUFFIX,
    REPORT_TOKEN,
    TierReportConsumptionUnmeasured,
    mentions,
)

#: Двери файловой системы: зов с таким именем ЧИТАЕТ или ПИШЕТ файл.
#: Перечень намеренно короткий и закрытый — «любой зов с путём в аргументе»
#: снова сделал бы меру шире класса.
FS_DOORS: frozenset[str] = frozenset({
    "open", "read_text", "write_text", "read_bytes", "write_bytes",
    "load", "dump", "atomic_save", "replace", "iterdir", "glob",
})

#: Зовы, которыми значение СЛИЧАЮТ с путём, а не открывают путь.
PATH_SHAPES: frozenset[str] = frozenset({"Path", "PurePath", "basename", "name"})

#: Методы, которыми значение КЛАДУТ В КОНТЕЙНЕР. Это не получатель, а новый дом
#: той же величины: поток продолжается под именем контейнера. Считать их
#: получателями значило бы ответить «НЕ ИЗМЕРЕНО» про `rows.append(...)` —
#: встроенный метод исходника не имеет, и разрешать его нечему (замер 25.11).
ADMISSION_METHODS: frozenset[str] = frozenset({
    "append", "add", "extend", "update", "insert", "setdefault",
})

#: Зовы, которые значение ФОРМИРУЮТ, а не потребляют: получив привязку, они
#: отдают её же в новой упаковке. Считать их получателями значило бы объявить
#: `frozenset(NAMES)` утечкой — перечень закрыт намеренно (замер 25.11:
#: `_untiered_census` отдаёт перепись именно `frozenset`, и первая редакция этой
#: меры ответила про него `НЕ ИЗМЕРЕНО`, то есть спрятала продолжение потока).
SHAPING_CALLS: frozenset[str] = frozenset({
    "frozenset", "set", "list", "tuple", "dict", "sorted", "reversed", "len",
    "iter", "enumerate", "zip", "items", "keys", "values", "get", "copy",
})

#: Роли СБОРКИ строки — те же, что у ADR-1096: только они делают из имени путь.
_ASSEMBLY_ROLES = (ast.BinOp, ast.JoinedStr)

#: Встроенные имена — ЗАМЕР интерпретатора, а не список из головы. Встроенный зов
#: исходника не имеет, разрешать его нечем, и среди них файл открывает РОВНО
#: `open` (он и остаётся дверью, см. :data:`FS_DOORS`). Перечень, набранный
#: руками, пришлось бы дописывать при каждом новом `sum`/`min`/`any` — ровно та
#: форма «белый список имён», от которой уходил ADR-1096.
_BUILTIN_LEAVES: frozenset[str] = frozenset(dir(_builtins)) - FS_DOORS

#: Зовы-ЛИСТЬЯ: разрешать их исходник нечем и не нужно. Дверь файловой системы
#: судится на месте (:func:`_verdict_in_scope`), формирующий зов и приём в
#: контейнер продолжают поток, путевой зов сличает. Объявить их получателями
#: значило бы ответить «НЕ ИЗМЕРЕНО» про `open(...)` — то есть спрятать САМУ
#: утечку за третьим исходом (дефект первой редакции, замер 25.11).
LEAF_CALLS: frozenset[str] = (SHAPING_CALLS | ADMISSION_METHODS | FS_DOORS
                              | PATH_SHAPES | _BUILTIN_LEAVES)

#: Вердикт, составляющий КЛАСС. Остальные — контекст либо третий исход.
CLASS_VERDICT = "reaches_report"

#: Вердикт третьего исхода (инв. #17).
UNMEASURED = "unmeasured"

#: Сколько ПЕРЕДАЧ значения мера проходит, прежде чем ответить третьим исходом.
#: Число есть ЗАМЕР живой поверхности (ADR-1098, цикл #1243), а не вкус: ответ о
#: всех трёх модулях поверхности УСТАНАВЛИВАЕТСЯ на глубине 2 и не меняется ни на
#: 3, ни на 4 (сводка дословно одна: `local_only` 1 · `selects_path` 1 ·
#: `unmeasured` 1), поэтому взят запас ОДИН хоп над точкой установления.
#: Глубина 1 даёт ТОТ ЖЕ вердикт при ДРУГОЙ причине — «бюджет хопов исчерпан»
#: вместо названного неразрешимого получателя, — и это и есть честная форма
#: ответа ADR-1097, который на той же глубине печатал `local_only`, то есть
#: ИЗМЕРЕННЫЙ ноль, не заглянув в следующего получателя.
DEFAULT_MAX_HOPS: int = 3


@dataclass
class _Ctx:
    """Модуль, в котором живёт судимая область: его разбор, ввозы и разрешитель.

    Без него второй хоп судился бы ввозами ПЕРВОГО модуля: помощник чужого
    модуля, зовущий своего соседа, читался бы как неразрешимый, и настоящий
    вердикт спрятался бы за третьим исходом — тот же дефект, что первая
    редакция меры допустила на `open(...)` (ADR-1097, дефект 3).
    """

    key: str
    defs: dict
    imported: dict
    resolve: Optional[Callable[[str], Optional[str]]] = None
    cache: Optional[dict] = None


class TierDataNameLeakUnmeasured(Exception):
    """Исходник не разобран ⇒ поток НЕ ИЗМЕРЕН (это не «чисто»)."""


@dataclass(frozen=True)
class Flow:
    """Одно имя-данные и судьба его привязки: КОМУ отдано и что тот сделал."""

    token: str
    line: int
    binding: Optional[str]
    verdict: str
    why: str
    receiver: Optional[str] = None
    hop: Optional[str] = None

    @property
    def is_member(self) -> bool:
        """Член класса — РОВНО один вердикт. Вторых правил рядом нет."""
        return self.verdict == CLASS_VERDICT

    def __str__(self) -> str:                   # pragma: no cover - проза отчёта
        who = f" → {self.receiver}" if self.receiver else ""
        return f"{self.token!r} (строка {self.line}, {self.verdict}{who}): {self.why}"


def _parse(text: str) -> ast.AST:
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        raise TierDataNameLeakUnmeasured(
            f"исходник не разобран ({exc}) — поток НЕ ИЗМЕРЕН") from exc


def _parents(tree: ast.AST) -> dict:
    table: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            table[id(child)] = node
    return table


def _constant_at(tree: ast.AST, line: int, token: str) -> Optional[ast.Constant]:
    """Узел-строка с именем на названной строке. Привязку ищут от него."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.lineno == line and token in node.value):
            return node
    return None


def _binding_of(node: ast.AST, parents: dict) -> tuple[Optional[str], Optional[ast.AST]]:
    """Имя, под которым лежит контейнер с вхождением, и узел-владелец.

    Поднимаемся от вхождения к ближайшему присваиванию. Контейнер, стоя́щий
    АРГУМЕНТОМ зова прямо на месте, привязки не имеет — получатель у него
    непосредственный, и это ДРУГОЙ ответ, а не «привязка не найдена».
    """
    cur: Optional[ast.AST] = node
    while cur is not None:
        parent = parents.get(id(cur))
        if isinstance(parent, ast.Assign) and len(parent.targets) == 1:
            target = parent.targets[0]
            if isinstance(target, ast.Name):
                return target.id, parent
        if isinstance(parent, ast.AnnAssign) and isinstance(parent.target, ast.Name):
            return parent.target.id, parent
        if isinstance(parent, ast.Call):
            return None, parent
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                               ast.Module)):
            return None, None
        cur = parent
    return None, None


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _mentions_name(node: ast.AST, name: str) -> bool:
    """Имя встречается в поддереве. Один хоп меряется ИМЕНЕМ, а это сказано вслух."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id == name:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == name:
            return True
        if isinstance(sub, ast.arg) and sub.arg == name:
            return True
    return False


def _own_statements(scope: ast.AST) -> list:
    """Узлы ЭТОЙ области, без тел вложенных функций и классов.

    Область обязательна: модульное замыкание, спустившееся в тела функций,
    подбирает местные имена (`s`, `row`, `mod`) и объявляет получателем КАЖДЫЙ
    зов, который их трогает. Замер 25.11: такое замыкание назвало получателем
    `_INTERVAL_RE.match` в `cadence_census` и `str.endswith` в `tier_touch` —
    оба НЕРАЗРЕШИМЫ, и оба СПРЯТАЛИ настоящий ответ за третьим исходом.
    """
    out: list = []
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        out.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return out


def _closure(scope: ast.AST, start) -> set:
    """Имена, под которыми ЗНАЧЕНИЕ живёт в ЭТОЙ области, — до неподвижной точки.

    Приём взят у сторожа притязания `injected-clock` (`spa_core/tests/_injected_clock.py`,
    ADR-477), и по той же причине: значение путешествует под НОВЫМИ именами — через
    распаковку `.items()`, через цикл, через умолчание параметра, — и спрашивать о
    старом имени значит спрашивать не о том. Замер 25.11: первая редакция этой меры
    спрашивала ОДНО имя и ответила `local_only` про ДВА модуля, у которых привязка
    отдаётся наружу (`EVENT_ARTIFACT_FRAGMENTS` → параметром `fragments`,
    `TIER_CANON_MODULES` → умолчанием параметра `modules`). Ошибка шла в ОПАСНУЮ
    сторону: «не утекает» вместо «утекает — вот куда».

    Формирующий зов (:data:`SHAPING_CALLS`) потока НЕ прерывает: результат входит в
    замыкание, потому что это та же величина в другой упаковке.
    """
    names = {start} if isinstance(start, str) else set(start)
    body = _own_statements(scope)
    changed = True
    while changed:
        changed = False
        for node in body:
            fresh: set = set()
            if isinstance(node, ast.Assign) and _mentions_any(node.value, names):
                for target in node.targets:
                    fresh |= _target_names(target)
            elif (isinstance(node, ast.AnnAssign) and node.value is not None
                    and _mentions_any(node.value, names)):
                fresh |= _target_names(node.target)
            elif (isinstance(node, (ast.For, ast.AsyncFor))
                    and _mentions_any(node.iter, names)):
                fresh |= _target_names(node.target)
            elif (isinstance(node, ast.comprehension)
                    and _mentions_any(node.iter, names)):
                fresh |= _target_names(node.target)
            elif (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ADMISSION_METHODS
                    and isinstance(node.func.value, ast.Name)
                    and any(_mentions_any(a, names) for a in node.args)):
                fresh.add(node.func.value.id)
            if fresh - names:
                names |= fresh
                changed = True
    return names


def _mentions_any(node: ast.AST, names: set) -> bool:
    return any(_mentions_name(node, n) for n in names)


def _target_names(target: ast.AST) -> set:
    """Имена цели присваивания либо распаковки — включая кортежные."""
    return {sub.id for sub in ast.walk(target) if isinstance(sub, ast.Name)}


def _is_method_of_value(call: ast.Call, names: set) -> bool:
    """Зов есть МЕТОД самого значения, а не помощник, его получивший.

    `mod.endswith(…)` — метод строки, лежащей в замыкании; помощником он не
    является, и разрешать его нечему (встроенный метод исходника не имеет).
    Решает БАЗА зова, а не его имя: `replace` стои́т и среди дверей файловой
    системы (`os.replace`), и среди методов строки, и различить их можно только
    тем, на чём зов сделан.
    """
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    base = func.value
    return isinstance(base, ast.Name) and base.id in names


def _is_stdlib_method(call: ast.Call, imported: dict, defs: dict) -> bool:
    """Зов есть МЕТОД величины времени исполнения, а не чужой помощник.

    `dotted.endswith("." + mod)` получает значение аргументом, но читать у него
    нечего: это метод строки, и исходника у него нет. Объявить его получателем
    значит ответить «НЕ ИЗМЕРЕНО» и спрятать настоящий вердикт области за
    третьим исходом (замер 25.11 — именно так мера соврала про `tier_touch`).

    Дверь файловой системы методом-листом НЕ считается: `p.write_text(value)`
    обязана остаться видимой, иначе вычет снял бы с учёта саму утечку.

    **Граница названа:** метод объекта, чей класс не разрешается (`self.writer
    .save(x)`), числится листом, и население за этой границей НЕ ИЗМЕРЕНО —
    нулём это не считается.
    """
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in FS_DOORS:
        return False
    base = func.value
    if isinstance(base, ast.Name):
        return base.id not in imported and base.id not in defs
    # Метод, сделанный на ЛИТЕРАЛЕ либо на выражении-литерале
    # (`"…".format(x)`, `", ".join(x)`), — метод строки по построению: базы с
    # именем у него нет вовсе, и первая редакция этого вычета, спрашивавшая
    # только `ast.Name`, объявляла такой зов неразрешимым получателем.
    return isinstance(base, (ast.Constant, ast.JoinedStr, ast.Tuple, ast.List,
                             ast.Set, ast.Dict))


def _receivers(scope: ast.AST, names: set, imported: dict, defs: dict) -> list:
    """Зовы ЭТОЙ области, которым отдано значение, и функции, принявшие его УМОЛЧАНИЕМ.

    Возвращает пары «зов, или функция, принявшая значение УМОЛЧАНИЕМ параметра».
    Умолчание — такое же вхождение значения в чужое тело, как и аргумент, и
    пропустить его значило бы объявить `tier_touch` непротекающим (замер 25.11).
    """
    out: list = []
    for node in _own_statements(scope):
        if isinstance(node, ast.Call):
            if (_call_name(node) in LEAF_CALLS
                    or _is_method_of_value(node, names)
                    or _is_stdlib_method(node, imported, defs)):
                continue
            for arg in list(node.args) + [k.value for k in node.keywords]:
                if _mentions_any(arg, names):
                    out.append(node)
                    break
    return out


def _default_crossings(tree: ast.AST, names: set) -> list:
    """Функции, чей ПАРАМЕТР получает значение умолчанием: `(функция, параметр)`."""
    out: list = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args
        positional = list(args.posonlyargs) + list(args.args)
        pairs = list(zip(positional[len(positional) - len(args.defaults):],
                         args.defaults))
        pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults)
                  if d is not None]
        for arg, default in pairs:
            if default is not None and _mentions_any(default, names):
                out.append((node, arg.arg))
    return out


def _local_defs(tree: ast.AST) -> dict:
    out: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, node)
    return out


def _param_by_identity(func: ast.AST, call: ast.Call,
                       node: ast.AST) -> Optional[str]:
    """Параметр, принявший ЛИТЕРАЛ, переданный на месте.

    Имени у литерала нет, поэтому `_param_for` (он ищет по ИМЕНАМ замыкания)
    отвечает `None`, и вердикт выходил `local_only` — ложная невинность. Здесь
    аргумент находится по ТОЖДЕСТВУ узла: ровно тот, в чьём поддереве лежит
    вхождение.
    """
    args = getattr(func, "args", None)
    if args is None:
        return None
    params = [a.arg for a in list(args.posonlyargs) + list(args.args)]
    for index, arg in enumerate(call.args):
        if any(sub is node for sub in ast.walk(arg)):
            if index < len(params):
                return params[index]
            if args.vararg is not None:
                return args.vararg.arg
            return None
    for kw in call.keywords:
        if kw.arg and any(sub is node for sub in ast.walk(kw.value)):
            return kw.arg
    return None


def _param_for(func: ast.AST, call: ast.Call, names: set) -> Optional[str]:
    """Какой ПАРАМЕТР получателя принял значение — по ЛЮБОМУ имени замыкания.

    Имена РАЗНЫЕ и путать их нельзя: `names` — замыкание ЗНАЧЕНИЯ у вызывающего,
    `params` — параметры ПОЛУЧАТЕЛЯ. Первая редакция назвала оба `names`, местное
    затёрло параметр, и `_param_for` отвечал `None` на КАЖДОМ зове: вердикт
    выходил `НЕ ИЗМЕРЕНО` даже там, где утечка была написана в три строки.
    """
    args = getattr(func, "args", None)
    if args is None:
        return None
    params = [a.arg for a in list(args.posonlyargs) + list(args.args)]
    for index, arg in enumerate(call.args):
        if _mentions_any(arg, names):
            if index < len(params):
                return params[index]
            if args.vararg is not None:
                return args.vararg.arg
            return None
    for kw in call.keywords:
        if kw.arg and _mentions_any(kw.value, names):
            return kw.arg
    return None


def _report_assembled_from(scope: ast.AST, names: set) -> Optional[ast.AST]:
    """Сборка пути к отчёту, в которой участвует САМО значение.

    Именно это отличает «помощник собрал путь из переданного имени» от
    «в помощнике где-то рядом лежит имя отчёта»: второе ADR-1096 уже видит
    замыканием, и повторять его здесь значило бы мерить не свой предмет.
    """
    for node in ast.walk(scope):
        if not isinstance(node, _ASSEMBLY_ROLES):
            continue
        has_suffix = any(isinstance(s, ast.Constant) and isinstance(s.value, str)
                         and (REPORT_SUFFIX in s.value or REPORT_TOKEN in s.value)
                         for s in ast.walk(node))
        if has_suffix and _mentions_any(node, names):
            return node
    return None


def _door_naming_the_report(scope: ast.AST) -> Optional[ast.Call]:
    """Дверь файловой системы, чей аргумент НАЗЫВАЕТ отчёт целиком."""
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node) not in (FS_DOORS | PATH_SHAPES):
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                if (isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                        and REPORT_TOKEN in sub.value):
                    return node
    return None


def _door_fed_by(scope: ast.AST, names: set) -> Optional[ast.Call]:
    """Дверь файловой системы, чей аргумент выведен из значения."""
    for node in ast.walk(scope):
        if isinstance(node, ast.Call) and _call_name(node) in FS_DOORS:
            if any(_mentions_any(a, names) for a in node.args):
                return node
    return None


def _compare_with_path(scope: ast.AST, names: set) -> Optional[ast.Compare]:
    """Сличение значения с путём: выбор файла есть, открытия файла нет."""
    for node in ast.walk(scope):
        if not (isinstance(node, ast.Compare) and _mentions_any(node, names)):
            continue
        for other in [node.left] + list(node.comparators):
            if _path_shaped(other):
                return node
    return None


def _verdict_in_scope(scope: ast.AST, names: set, where: str,
                      ) -> tuple[str, str]:
    """Что ЭТА область делает со значением. Порядок проверок значим.

    Сперва отчёт (предмет класса), потом любой другой файл (контекст, НЕ класс),
    потом сличение (ближний промах) и только затем «ничего». Переставить —
    значит либо объявить членом чужой путь, либо спрятать отчёт за ним.
    """
    local = _closure(scope, names)
    node = _report_assembled_from(scope, local)
    if node is not None:
        return (CLASS_VERDICT,
                f"{where}: путь к отчёту куратора СОБРАН из значения "
                f"(строка {node.lineno})")
    call = _door_naming_the_report(scope)
    if call is not None:
        return (CLASS_VERDICT,
                f"{where}: дверь {_call_name(call)!r} открывает отчёт куратора "
                f"по имени (строка {call.lineno}), а значение пришло сюда")
    call = _door_fed_by(scope, local)
    if call is not None:
        return ("reaches_fs",
                f"{where}: дверь {_call_name(call)!r} открывает путь, выведенный "
                f"из значения (строка {call.lineno}) — но это НЕ отчёт куратора: "
                f"класс УЖЕ файловой системы")
    cmp_node = _compare_with_path(scope, local)
    if cmp_node is not None:
        return ("selects_path",
                f"{where}: значение СЛИЧАЕТСЯ с путём (строка {cmp_node.lineno}), "
                f"но ни одна дверь файловой системы в одном хопе не достигнута — "
                f"БЛИЖНИЙ промах класса")
    return ("local_only",
            f"{where}: ни путь к отчёту не собран, ни файл из значения не открыт")


def _path_shaped(node: ast.AST) -> bool:
    """Выражение похоже на ПУТЬ: зов `Path`/`basename` либо имя `path`/`artifact`."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and _call_name(sub) in PATH_SHAPES:
            return True
        if isinstance(sub, ast.Name) and sub.id in ("path", "paths", "artifact",
                                                    "artifacts", "filename", "rel"):
            return True
    return False


def _scopes(tree: ast.AST) -> list:
    """Модуль и КАЖДОЕ его функциональное тело — по отдельности.

    Значение, лежащее в модульной привязке, отдаётся наружу чаще всего ИЗ ТЕЛА
    функции (`_artifacts_for_event(manifest, fragments)` стои́т внутри
    `event_artifact_names`), поэтому спрашивать только модульный уровень значило
    бы ответить `local_only` про настоящую передачу.
    """
    out: list = [tree]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(node)
    return out


def data_name_flows(
    text: str,
    *,
    resolve: Optional[Callable[[str], Optional[str]]] = None,
    token: str = MODULE_TOKEN,
    max_hops: int = DEFAULT_MAX_HOPS,
) -> tuple[Flow, ...]:
    """Судьба КАЖДОГО имени-данные в исходнике. Третий исход поднимается сам.

    `resolve(name)` отдаёт исходник чужого модуля по имени ввоза. Он
    отсутствует либо вернул `None` ⇒ вердикт `unmeasured` с названной причиной:
    подставить `local_only` значило бы выдать непрочитанное за «не утекает».

    `max_hops` — сколько ПЕРЕДАЧ значения мера проходит. Это ВХОД, а не
    константа внутри: `max_hops=1` воспроизводит глубину ADR-1097 и показывает,
    что та печатала `local_only` там, где значение отдано дальше (ADR-1098).
    Предел ≤ 0 — не «мерить нечего», а отказ: мера, которой не дали ни одного
    хопа, ответила бы о первом получателе, не заглянув в него.
    """
    if max_hops < 1:
        raise TierDataNameLeakUnmeasured(
            f"бюджет хопов {max_hops} меньше одного — мерить нечем; это НЕ "
            f"«утечек нет» (инв. #17)")
    try:
        found = mentions(text)
    except TierReportConsumptionUnmeasured as exc:
        raise TierDataNameLeakUnmeasured(str(exc)) from exc
    data = [m for m in found if m.kind == "data"]
    if not data:
        return ()
    tree = _parse(text)
    parents = _parents(tree)
    defs = _local_defs(tree)
    imported = _imported_modules(tree)
    ctx = _Ctx("<self>", defs, imported, resolve, {})
    out: list = []
    for mention in data:
        node = _constant_at(tree, mention.line, token)
        if node is None:
            out.append(Flow(mention.token, mention.line, None, UNMEASURED,
                            "вхождение не найдено повторным разбором — "
                            "НЕ ИЗМЕРЕНО"))
            continue
        binding, owner = _binding_of(node, parents)
        if binding is None and isinstance(owner, ast.Call):
            out.append(_flow_for_direct_call(mention, owner, node, ctx,
                                             max_hops))
            continue
        if binding is None:
            out.append(Flow(mention.token, mention.line, None, UNMEASURED,
                            "привязка контейнера НЕ РАЗРЕШЕНА (ни присваивание, "
                            "ни аргумент зова) — НЕ ИЗМЕРЕНО"))
            continue
        module_names = _closure(tree, binding)
        verdicts: list = []
        for scope in _scopes(tree):
            local = _closure(scope, module_names)
            if not any(_mentions_any(n, local) for n in _own_statements(scope)):
                continue
            where = "свой модуль" if scope is tree else (
                f"своя функция {getattr(scope, 'name', '?')!r}")
            verdict, why = _verdict_in_scope(scope, local, where)
            verdicts.append(Flow(mention.token, mention.line, binding, verdict,
                                 why, getattr(scope, "name", None), "self"))
            for call in _receivers(scope, local, imported, defs):
                verdicts.append(_handover(mention, binding, call, local, ctx,
                                          max_hops))
        for func, param in _default_crossings(tree, module_names):
            verdict, why = _follow(
                func, {param}, f"умолчанием в {getattr(func, 'name', '?')!r}",
                ctx, max_hops - 1,
                frozenset({(ctx.key, getattr(func, "name", "?"), param)}))
            verdicts.append(Flow(mention.token, mention.line, binding, verdict,
                                 why, getattr(func, "name", None),
                                 "local:default"))
        if not verdicts:
            out.append(Flow(mention.token, mention.line, binding, "local_only",
                            f"замыкание привязки {binding!r} "
                            f"({sorted(module_names)}) не встречается ни в одной "
                            f"области модуля — утечь нечему (ИЗМЕРЕННЫЙ ноль, "
                            f"не молчание)"))
            continue
        out.append(_worst_of(verdicts))
    return tuple(out)


def _imported_modules(tree: ast.AST) -> dict:
    """Имя в коде → модуль, из которого оно ввезено. Один хоп начинается здесь."""
    out: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                out[alias.asname or alias.name] = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split(".")[0]] = alias.name
    return out


def _ctx_for_source(key: str, source: str,
                    resolve: Optional[Callable[[str], Optional[str]]],
                    cache: dict) -> "_Ctx":
    """Контекст чужого модуля: его разбор, его ввозы, тот же разрешитель."""
    tree = _parse(source)
    return _Ctx(key, _local_defs(tree), _imported_modules(tree), resolve, cache)


def _resolve_callee(call: ast.Call, ctx: "_Ctx",
                    ) -> tuple[Optional[ast.AST], Optional["_Ctx"], str]:
    """Получатель зова: тело функции, КОНТЕКСТ его модуля и ГДЕ он измерен.

    Контекст возвращается вместе с телом не для удобства: следующий хоп обязан
    спрашивать ввозы ТОГО модуля, в котором лежит получатель. Разбор чужого
    модуля кэшируется по имени — иначе глубина перечитывала бы один и тот же
    исходник на каждой ветке дороги.
    """
    name = _call_name(call)
    if name in ctx.defs:
        return ctx.defs[name], ctx, "local"
    module = ctx.imported.get(name)
    if module is None and isinstance(call.func, ast.Attribute):
        base = call.func.value
        if isinstance(base, ast.Name):
            module = ctx.imported.get(base.id)
    if module is None or ctx.resolve is None:
        return None, None, "unresolved"
    cache = ctx.cache if ctx.cache is not None else {}
    if module in cache:
        sub = cache[module]
    else:
        source = ctx.resolve(module)
        sub = None
        if source:
            try:
                sub = _ctx_for_source(f"import:{module}", source,
                                      ctx.resolve, cache)
            except TierDataNameLeakUnmeasured:
                sub = None
        cache[module] = sub
    if sub is None:
        return None, None, "unresolved"
    func = sub.defs.get(name)
    if func is None:
        return None, None, "unresolved"
    return func, sub, f"import:{module}"


def _follow(scope: ast.AST, names: set, where: str, ctx: "_Ctx",
            hops_left: int, visited: frozenset) -> tuple[str, str]:
    """Что область делает со значением — И КУДА отдаёт его ДАЛЬШЕ.

    ADR-1097 судил тело получателя ОДНИМ вопросом «собрана ли здесь дорога к
    отчёту», и когда ответом было «нет», печатал `local_only` — то есть
    ИЗМЕРЕННЫЙ ноль. Замер 25.11 (ADR-1098) показал цену: `tier_touch
    .tier_touches` отдаёт свой параметр `modules` ТРЕТЬЕМУ помощнику
    `_module_matches`, и прежняя мера объявила «не утекает», в этого помощника
    не заглянув. Ответ совпал с правдой СЛУЧАЙНО.

    Поэтому `local_only` теперь означает РОВНО «ни дороги, ни двери, и значение
    НИКОМУ не отдано», и это проверено обходом. Отдано дальше, а бюджет хопов
    исчерпан либо получатель неразрешим ⇒ третий исход с названной причиной
    (инв. #17), а не тишина.
    """
    verdict, why = _verdict_in_scope(scope, names, where)
    if verdict != "local_only":
        return verdict, why
    local = _closure(scope, names)
    onward = _receivers(scope, local, ctx.imported, ctx.defs)
    if not onward:
        return verdict, (f"{why}; и значение НИКОМУ не отдано дальше — "
                         f"ИЗМЕРЕННЫЙ ноль, проверенный обходом")
    told = ", ".join(sorted({_call_name(c) or "<?>" for c in onward}))
    if hops_left <= 0:
        return (UNMEASURED,
                f"{where}: значение отдано ДАЛЬШЕ ({told}) — бюджет хопов "
                f"исчерпан, НЕ ИЗМЕРЕНО (прежняя редакция печатала здесь "
                f"`local_only`, ничего не измерив)")
    results: list = []
    for call in onward:
        func, sub, _hop = _resolve_callee(call, ctx)
        who = _call_name(call) or "<?>"
        if func is None or sub is None:
            results.append((UNMEASURED,
                            f"{where} → {who}: получатель следующего хопа НЕ "
                            f"РАЗРЕШЁН — НЕ ИЗМЕРЕНО"))
            continue
        param = _param_for(func, call, local)
        if param is None:
            results.append((UNMEASURED,
                            f"{where} → {who}: параметр получателя, принявший "
                            f"значение, НЕ РАЗРЕШЁН — НЕ ИЗМЕРЕНО"))
            continue
        step = (sub.key, getattr(func, "name", "?"), param)
        if step in visited:
            results.append((UNMEASURED,
                            f"{where} → {who}: ЦИКЛ передач — этот получатель "
                            f"уже судился на этой дороге, НЕ ИЗМЕРЕНО"))
            continue
        results.append(_follow(func, {param}, f"{where} → {who}", sub,
                               hops_left - 1, visited | {step}))
    results.sort(key=lambda r: VERDICT_ORDER.index(r[0]))
    return results[0]


def _flow_for_direct_call(mention, call, node, ctx: "_Ctx",
                          max_hops: int) -> Flow:
    """Контейнер стои́т АРГУМЕНТОМ зова прямо на месте — получатель один.

    Привязки у такого вхождения нет: литерал передан на месте
    (`eat(("tier_curator",))`), и спрашивать замыкание не о чем. Судится тело
    получателя по ПАРАМЕТРУ, принявшему литерал.

    Эта ветка не имела НИ ОДНОЙ сцены до 25.11 и звала снятую функцию
    `_verdict_inside` — то есть падала бы `NameError` на первом же таком модуле.
    Нашёл её `pyflakes`, а не тест: дыра покрытия названа и закрыта сценой
    `ADirectCallArgument`.
    """
    func, sub, hop = _resolve_callee(call, ctx)
    receiver = _call_name(call) or None
    if func is None or sub is None:
        return Flow(mention.token, mention.line, None, UNMEASURED,
                    f"получатель {receiver!r} НЕ РАЗРЕШЁН (первый хоп) — "
                    f"НЕ ИЗМЕРЕНО", receiver, hop)
    param = _param_by_identity(func, call, node) or "<аргумент>"
    verdict, why = _follow(func, {param}, f"получатель {receiver!r}", sub,
                           max_hops - 1,
                           frozenset({(sub.key, getattr(func, "name", "?"),
                                       param)}))
    return Flow(mention.token, mention.line, None, verdict, why, receiver, hop)


def _handover(mention, binding, call, names, ctx: "_Ctx",
              max_hops: int) -> Flow:
    """Передача значения помощнику: разрешить его и судить ЕГО тело — И ДАЛЬШЕ.

    Неразрешимый помощник — третий исход с названной причиной, а не «не
    утекает»: исходника у него нет, и выдумать его поведение нечем. Тело,
    отдающее значение ТРЕТЬЕМУ, судится по той же дороге до предела
    `max_hops`, а исчерпанный предел тоже есть третий исход (ADR-1098).
    """
    func, sub, hop = _resolve_callee(call, ctx)
    receiver = _call_name(call) or None
    if func is None or sub is None:
        return Flow(mention.token, mention.line, binding, UNMEASURED,
                    f"получатель {receiver!r} НЕ РАЗРЕШЁН (первый хоп) — "
                    f"НЕ ИЗМЕРЕНО", receiver, hop)
    param = _param_for(func, call, names)
    if param is None:
        return Flow(mention.token, mention.line, binding, UNMEASURED,
                    f"параметр получателя {receiver!r}, принявший значение, "
                    f"НЕ РАЗРЕШЁН — НЕ ИЗМЕРЕНО", receiver, hop)
    verdict, why = _follow(func, {param}, f"получатель {receiver!r}", sub,
                           max_hops - 1,
                           frozenset({(sub.key, getattr(func, "name", "?"),
                                       param)}))
    return Flow(mention.token, mention.line, binding, verdict, why, receiver,
                hop)


#: Порядок строгости: класс ВЫШЕ контекста, контекст выше ближнего промаха, а
#: `unmeasured` НЕ гасит найденную утечку — но и не прячется за `local_only`.
VERDICT_ORDER: tuple = (CLASS_VERDICT, "reaches_fs", UNMEASURED,
                        "selects_path", "local_only")


def _worst_of(verdicts: list) -> Flow:
    """Худший исход, и СВОДКА всех — чтобы измеренное не прятал неизмеренное.

    При РАВНОМ вердикте вперёд ставится наблюдение, прошедшее ПО ДОРОГЕ
    (передача помощнику), а не наблюдение своей области. Причина не косметика:
    `local_only` значит «и значение НИКОМУ не отдано», и это утверждение имеет
    право делать только тот, кто дорогу прошёл. Своя область о передаче не
    знает — её ответ был бы верным про себя и немым про класс (ADR-1098).
    """
    ordered = sorted(verdicts, key=lambda f: (VERDICT_ORDER.index(f.verdict),
                                              0 if f.hop != "self" else 1))
    tally: dict = {}
    for flow in ordered:
        tally[flow.verdict] = tally.get(flow.verdict, 0) + 1
    worst = ordered[0]
    summary = ", ".join(f"{k}×{v}" for k, v in sorted(tally.items()))
    return Flow(worst.token, worst.line, worst.binding, worst.verdict,
                f"{worst.why} [наблюдений {len(ordered)}: {summary}]",
                worst.receiver, worst.hop)


def members(flows) -> tuple[Flow, ...]:
    """Члены КЛАССА. Остальные вердикты членами не являются по построению."""
    return tuple(f for f in flows if f.is_member)


def unmeasured(flows) -> tuple[Flow, ...]:
    """Третий исход поимённо: «не измерено» никогда не выдаётся за «не утекает»."""
    return tuple(f for f in flows if f.verdict == UNMEASURED)


def describe(where: str, flows) -> str:
    """Строка вердикта: ЧТО измерено и чем это не является."""
    if not flows:
        return f"{where}: имён-данных нет — вопрос не задан"
    found = members(flows)
    if found:
        return f"{where}: ЧЛЕН КЛАССА — " + ", ".join(str(f) for f in found)
    return (f"{where}: членов класса нет ({len(flows)} имён-данных, "
            f"НЕ ИЗМЕРЕНО {len(unmeasured(flows))})")
