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

Хопов НЕСКОЛЬКО (`max_hops`, ADR-1098), и КОНСТРУКТОР класса с 25.11 — такой же
разрешимый получатель, как функция (ADR-1099, заказ G1082 п. 3): величина,
легшая в поле, судится в КАЖДОМ методе, это поле читающем. Прежде `Touch(hit, …)`
не разрешался никак, и мера печатала честное «получатель НЕ РАЗРЕШЁН» — причина
верная, населением за границей не являвшаяся.

Границы, которые остаются НАЗВАННЫМИ и нулём не считаются:

* **Конструктор, которого класс НЕ ОБЪЯВЛЯЛ, не судится** (ADR-1101): форма,
  рождающая конструктор ПОЛЯМИ, перечислена закрытым каталогом
  (:data:`_FIELD_CTOR_DECORATORS`, :data:`_FIELD_CTOR_BASES`), и класс вне
  каталога, у которого есть база, отдаёт третий исход — конструктор у него
  УНАСЛЕДОВАН, а аннотации суть классовые КОНСТАНТЫ. Остаётся названной
  границей класс БЕЗ базы и без объявленной формы: его зов невозможен в Python
  вовсе, и другого чтения исходника нет; население этой границы НЕ ИЗМЕРЕНО.
* **`InitVar` и `ClassVar`** отсеяны, `field(init=False)` тоже; прочие рычаги
  `dataclasses` (`kw_only=True`, `__post_init__`) подпись меры НЕ двигают, и
  население этой границы НЕ ИЗМЕРЕНО.
* **Поток внутри объекта идёт ПО ИМЕНИ ПОЛЯ**, ровно как внутри функции — по
  имени параметра: `self.token` и `other.token` для меры одно имя. Огрубление
  названо и ошибается в сторону НАХОДКИ, а не в сторону «чисто».
* **Объект, положенный в ЧУЖОЙ объект** (`self.writer.save(x)`), — следующий
  класс, и он НЕ ИЗМЕРЕН.
* Разбор чужого исходника — дело вызывающего: он подаёт `resolve`, и `None` от
  него есть `unmeasured`, а не «чисто».
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

#: ФОРМА, рождающая конструктор ПОЛЯМИ класса. Перечень закрытый, и это не
#: «белый список, который разрешает»: форма ВНЕ каталога даёт третий исход, а не
#: догадку (:func:`_ctor_form`). Поэтому забытая форма теряет ОХВАТ меры и
#: никогда не рождает ложное «чисто» — ошибка идёт в сторону `unmeasured`.
#: `inherits_fields` — наследует ли форма поля БАЗЫ (у `@dataclass` и pydantic
#: да, у `NamedTuple` нет); `keyword_only` — принимает ли конструктор величину
#: только по ключу (pydantic и `TypedDict`), и тогда ПОЗИЦИОННЫЙ зов есть не
#: «позиция 0», а код, которого Python не исполнит.

@dataclass(frozen=True)
class _CtorForm:
    """Объявленная форма конструктора: её имя и два её свойства."""

    name: str
    inherits_fields: bool
    keyword_only: bool


#: Декораторы, объявляющие форму. `@dataclass(frozen=True)` — тот же декоратор
#: (живой `Touch` объявлен ровно так), поэтому имя берётся у ЗОВА, а не у узла.
_FIELD_CTOR_DECORATORS: dict = {
    "dataclass": _CtorForm("@dataclass", True, False),
}

#: Базы, объявляющие форму. Имя сверяется по ЛИСТУ точечной цепочки:
#: `typing.NamedTuple` и `NamedTuple` — одна форма.
_FIELD_CTOR_BASES: dict = {
    "NamedTuple": _CtorForm("NamedTuple", False, False),
    "TypedDict": _CtorForm("TypedDict", False, True),
    "BaseModel": _CtorForm("pydantic BaseModel", True, True),
}

#: Аннотации, которые полем конструктора НЕ являются: `ClassVar` — классовая
#: величина, `InitVar` в подписи есть, но полем не становится и до объекта не
#: доходит. Пропустить их значило бы сдвинуть ПОЗИЦИИ и назвать не то поле —
#: ровно тот дефект, против которого написан ADR-1101.
_NON_FIELD_ANNOTATIONS: frozenset[str] = frozenset({"ClassVar", "InitVar"})

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
    classes: dict
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


def _local_classes(tree: ast.AST) -> dict:
    """Классы модуля: имя → объявление. Конструктор — такой же получатель.

    До 25.11 здесь не было ничего, и зов `Touch(hit, …)` не разрешался НИКАК:
    мера печатала «получатель следующего хопа НЕ РАЗРЕШЁН» — честный третий
    исход, но населением за ЭТОЙ границей он не был (ADR-1098 назвал это своим
    пределом, заказ G1082 п. 3 велел измерить).
    """
    out: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            out.setdefault(node.name, node)
    return out


def _methods(cls: ast.ClassDef) -> list:
    """Методы, объявленные в ЭТОМ теле класса. Унаследованных здесь нет."""
    return [node for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _init_of(cls: ast.ClassDef):
    """Явный `__init__` либо `None` — у сгенерированного конструктора тела НЕТ."""
    for method in _methods(cls):
        if method.name == "__init__":
            return method
    return None


def _annotated_fields(cls: ast.ClassDef) -> list:
    """Поля ЭТОГО тела класса, объявленные АННОТАЦИЕЙ, В ПОРЯДКЕ объявления.

    Подписью СГЕНЕРИРОВАННОГО конструктора этот порядок является только у
    объявленной формы и только вместе с полями БАЗ — собирает подпись
    :func:`_generated_signature`, а не этот зов. До ADR-1101 он отвечал на
    вопрос о подписи сам, и на классе с базой это был ответ о другом
    конструкторе: у `class Handler(BaseHTTPRequestHandler)` конструктор
    УНАСЛЕДОВАН, а `backtest_dir: str` — классовая КОНСТАНТА, величины не
    получающая никогда.

    `ClassVar` и `InitVar` отсеяны: полями конструктора они не становятся, а их
    присутствие в перечне СДВИНУЛО БЫ позиции и назвало не то поле.
    """
    out: list = []
    for node in cls.body:
        if not (isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)):
            continue
        if _annotation_head(node.annotation) in _NON_FIELD_ANNOTATIONS:
            continue
        if _declared_out_of_init(node.value):
            continue
        out.append(node.target.id)
    return out


def _annotation_head(node: ast.AST) -> Optional[str]:
    """Голова аннотации: `ClassVar[int]` → `ClassVar`, `typing.ClassVar` → то же."""
    if isinstance(node, ast.Subscript):
        node = node.value
    dotted = _dotted_of(node)
    return dotted.split(".")[-1] if dotted else None


def _declared_out_of_init(value: Optional[ast.AST]) -> bool:
    """`field(init=False)` — объявление, что поля в подписи НЕТ."""
    if not isinstance(value, ast.Call) or _call_name(value) != "field":
        return False
    for kw in value.keywords:
        if kw.arg == "init" and isinstance(kw.value, ast.Constant):
            return kw.value.value is False
    return False


def _ctor_form(cls: ast.ClassDef) -> Optional[_CtorForm]:
    """Форма, рождающая конструктор ПОЛЯМИ, либо `None` — форма НЕ ОБЪЯВЛЕНА.

    Спрашивается ОБЪЯВЛЕНИЕ класса, а не отсутствие `__init__`: «своего
    `__init__` нет» и «конструктор рождён полями» — разные утверждения, и до
    ADR-1101 мера подменяла второе первым. Замер 25.11 по `spa_core/**` вне
    тестов: классов с аннотациями, без своего `__init__` и с базой — **64**, из
    них форму НЕ объявляют **9**, и у всех девяти конструктор унаследован.
    """
    for dec in cls.decorator_list:
        node = dec.func if isinstance(dec, ast.Call) else dec
        dotted = _dotted_of(node)
        if dotted and dotted.split(".")[-1] in _FIELD_CTOR_DECORATORS:
            return _FIELD_CTOR_DECORATORS[dotted.split(".")[-1]]
    for dotted in _base_names(cls):
        leaf = dotted.split(".")[-1]
        if leaf in _FIELD_CTOR_BASES:
            return _FIELD_CTOR_BASES[leaf]
    return None


def _generated_signature(cls: ast.ClassDef, ctx: "_Ctx",
                         form: _CtorForm) -> tuple:
    """Подпись сгенерированного конструктора: поля БАЗ ПЕРВЫМИ, потом свои.

    Порядок не косметика, а сама мера: позиция зова сопоставляется с позицией
    подписи, и перечислить только свои поля значит назвать поле, стоящее на
    ДРУГОМ месте. Поля базы попадают в подпись лишь когда база сама объявила
    форму (`@dataclass` не берёт аннотации обычного родителя) — поэтому у
    каждой базы спрашивается :func:`_ctor_form`, а не наличие аннотаций.

    Обход в ГЛУБИНУ и ПОСЛЕ потомка: `dataclasses` собирает поля по
    `__mro__` НАОБОРОТ, то есть дальняя база идёт первой. Обход в ширину дал бы
    для цепочки `Kid(Mid)`→`Mid(Top)` порядок `Mid, Top` вместо `Top, Mid` —
    и позиция 0 указала бы на чужое поле.

    Возвращается ТРОЙКА: подпись · базы, разрешить которые нечем · признак
    НЕОДНОЗНАЧНОГО порядка. Последний поднимается, когда поля несёт больше
    одной прямой базы: их порядок в подписи решает C3-линеаризация, а не
    объявление, и вычислять её по исходнику мера не умеет. Оба последних —
    вход третьего исхода у :func:`_ctor_param`, а не ответ этого зова.
    """
    if not form.inherits_fields:
        return _annotated_fields(cls), [], False
    unresolved: list = []
    contributors = 0

    def fields_of(node: ast.ClassDef, nctx: "_Ctx", seen: frozenset) -> list:
        step = (nctx.key, node.name)
        if step in seen:                       # цикл в цепочке баз — не повод врать
            return []
        seen = seen | {step}
        out: list = []
        for dotted in _base_names(node):
            base, bctx = _resolve_base(dotted, nctx)
            if base is None or bctx is None:
                if dotted not in unresolved:
                    unresolved.append(dotted)
                continue
            out.extend(fields_of(base, bctx, seen))
            if _ctor_form(base) is not None:
                out.extend(_annotated_fields(base))
        return out

    inherited: list = []
    for field in fields_of(cls, ctx, frozenset()):
        if field not in inherited:
            inherited.append(field)
    for dotted in _base_names(cls):
        base, bctx = _resolve_base(dotted, ctx)
        if base is None or bctx is None:
            continue
        if fields_of(base, bctx, frozenset()) or (
                _ctor_form(base) is not None and _annotated_fields(base)):
            contributors += 1
    own = [f for f in _annotated_fields(cls) if f not in inherited]
    return inherited + own, unresolved, contributors > 1


def _base_names(cls: ast.ClassDef) -> list:
    """Базовые классы, кроме `object`. Непустой список = есть НЕВИДИМЫЕ методы."""
    out: list = []
    for base in cls.bases:
        dotted = _dotted_of(base)
        if dotted and dotted.split(".")[-1] != "object":
            out.append(dotted)
    return out


def _dotted_of(node: ast.AST) -> Optional[str]:
    """`a.b.c` из цепочки Attribute/Name, либо `None` — цепочка не из имён."""
    parts: list = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return ".".join(reversed(parts))


def _fields_fed_by(init: ast.AST, param: str) -> list:
    """Поля `self.X`, в которые явный `__init__` КЛАДЁТ значение параметра.

    Спрашивается ЗАМЫКАНИЕ параметра, а не само имя: `__init__`, положивший
    `self.mods = tuple(modules)`, кладёт ту же величину в другой упаковке.
    """
    local = _closure(init, {param})
    out: list = []
    for node in _own_statements(init):
        targets: list = []
        if isinstance(node, ast.Assign) and _mentions_any(node.value, local):
            targets = list(node.targets)
        elif (isinstance(node, ast.AnnAssign) and node.value is not None
                and _mentions_any(node.value, local)):
            targets = [node.target]
        for target in targets:
            if (isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"):
                out.append(target.attr)
    return out


def _ctor_param(cls: ast.ClassDef, init, call: ast.Call, names: set,
                node: Optional[ast.AST], ctx: "_Ctx") -> tuple:
    """Параметр конструктора, принявший значение, либо названная ПРИЧИНА отказа.

    Конструкторов у класса не два вида, а ТРИ, и до ADR-1101 мера знала два:
    явный `__init__` (подпись в исходнике, первый параметр `self`, позиции зова
    сдвинуты на один) и «сгенерированный» — им объявлялся ЛЮБОЙ класс без
    своего `__init__`. Третий вид — конструктор УНАСЛЕДОВАННЫЙ, и он на живой
    поверхности самый частый: у `class Handler(BaseHTTPRequestHandler)`
    аннотации суть классовые КОНСТАНТЫ, величины не получающие никогда. Мера
    называла первую из них «параметром, принявшим значение», и дальше судила
    методы, её читающие, — то есть ВЫДУМЫВАЛА находку (замер 25.11: девять
    таких классов, у двух из девяти константа участвует в сборке пути).

    Поэтому спрашивается ОБЪЯВЛЕННАЯ ФОРМА (:func:`_ctor_form`), а подпись
    собирается вместе с полями баз (:func:`_generated_signature`). Неизвестная
    подпись — третий исход с названной причиной, а не позиция 0.
    """
    if init is not None:
        args = init.args
        params = [a.arg for a in list(args.posonlyargs) + list(args.args)][1:]
        return _match_param(params, args, call, names, node), None
    form = _ctor_form(cls)
    if form is None:
        bases = _base_names(cls)
        if bases:
            return None, (
                f"конструктор {cls.name!r} НЕ ОБЪЯВЛЕН: ни `__init__`, ни формы, "
                f"рождающей конструктор полями — он УНАСЛЕДОВАН от "
                f"{', '.join(bases)}, а аннотации класса суть КОНСТАНТЫ; какой "
                f"параметр принял величину, НЕ ИЗМЕРЕНО")
        form = _CtorForm("поля без базы", False, False)
    fields, unresolved, ambiguous = _generated_signature(cls, ctx, form)
    if not fields:
        return None, (f"конструктор {cls.name!r} НЕ РАЗРЕШЁН: ни `__init__`, ни "
                      f"объявленных полей — НЕ ИЗМЕРЕНО")
    kind, where = _hit_in_call(call, names, node)
    if kind == "keyword":
        if where in fields or unresolved:
            return where, None
        return None, (f"конструктор {cls.name!r}: параметр, принявший значение, "
                      f"НЕ РАЗРЕШЁН среди объявленных полей "
                      f"({', '.join(fields)}) — НЕ ИЗМЕРЕНО")
    if kind is None:
        return None, (f"конструктор {cls.name!r}: параметр, принявший значение, "
                      f"НЕ РАЗРЕШЁН среди объявленных полей "
                      f"({', '.join(fields)}) — НЕ ИЗМЕРЕНО")
    if form.keyword_only:
        return None, (
            f"конструктор {cls.name!r}: форма {form.name} принимает поля ТОЛЬКО "
            f"по ключу, а величина передана ПОЗИЦИЕЙ {where} — какое поле её "
            f"приняло, НЕ ИЗМЕРЕНО")
    if unresolved:
        return None, (
            f"конструктор {cls.name!r}: подпись НЕИЗВЕСТНА — базы НЕ РАЗРЕШЕНЫ "
            f"({', '.join(unresolved)}), сколько полей они несут, мерой не "
            f"узнать, и какое поле стои́т на позиции {where}, НЕ ИЗМЕРЕНО")
    if ambiguous:
        return None, (
            f"конструктор {cls.name!r}: поля несёт больше одной прямой базы — "
            f"их порядок в подписи решает C3-линеаризация, мерой не вычисляемая, "
            f"и какое поле стои́т на позиции {where}, НЕ ИЗМЕРЕНО")
    if where < len(fields):
        return fields[where], None
    return None, (
        f"конструктор {cls.name!r}: величина передана позицией {where}, а "
        f"подпись несёт {len(fields)} пол(я) ({', '.join(fields)}) — "
        f"НЕ ИЗМЕРЕНО")


def _hit_in_call(call: ast.Call, names: set,
                 node: Optional[ast.AST]) -> tuple:
    """КАК величина попала в зов: `("positional", индекс)` либо `("keyword", имя)`.

    ЕДИНСТВЕННАЯ дверь вопроса, и спрашивает её же :func:`_match_param`. Копий
    быть не должно: разойдись они — одна и та же передача считалась бы
    позиционной на одной дороге и ключевой на другой, то есть вердикт зависел
    бы от того, каким путём мера дошла до зова.
    """
    for index, arg in enumerate(call.args):
        if _hits(arg, names, node):
            return "positional", index
    for kw in call.keywords:
        if kw.arg and _hits(kw.value, names, node):
            return "keyword", kw.arg
    return None, None


def _hits(arg: ast.AST, names: set, node: Optional[ast.AST]) -> bool:
    """Лежит ли в этом аргументе ИСКОМОЕ вхождение — по ТОЖДЕСТВУ либо по именам.

    Тождество нужно литералу, переданному на месте (`Touch(("tier_curator",))`):
    имени у него нет, и поиск по именам ответил бы `False` — ложная невинность,
    закрытая у функций :func:`_param_by_identity`.
    """
    if node is not None:
        return any(sub is node for sub in ast.walk(arg))
    return _mentions_any(arg, names)


def _match_param(params: list, args, call: ast.Call, names: set,
                 node: Optional[ast.AST]) -> Optional[str]:
    """Какой из `params` принял значение. Как именно попало — у :func:`_hit_in_call`."""
    kind, where = _hit_in_call(call, names, node)
    if kind == "positional":
        if where < len(params):
            return params[where]
        if args is not None and args.vararg is not None:
            return args.vararg.arg
        return None
    if kind == "keyword":
        if args is not None or where in params:
            return where
        return None
    return None


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
    ctx = _Ctx("<self>", defs, imported, _local_classes(tree), resolve, {})
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
    return _Ctx(key, _local_defs(tree), _imported_modules(tree),
                _local_classes(tree), resolve, cache)


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
    sub, hop = _module_ctx(call, ctx)
    if sub is None:
        return None, None, hop
    func = sub.defs.get(name)
    if func is None:
        return None, None, "unresolved"
    return func, sub, hop


def _module_ctx(call: ast.Call, ctx: "_Ctx") -> tuple:
    """Контекст МОДУЛЯ, в котором живёт получатель зова, либо `None`.

    Вынесено из :func:`_resolve_callee` не ради краткости: та же половина нужна
    КОНСТРУКТОРУ (:func:`_resolve_class`), и вторая её копия означала бы, что
    функция и класс разрешаются по РАЗНЫМ правилам ввоза — то есть мера пускала
    бы через себя ровно то, из-за чего понадобилась.
    """
    owner = None
    if (isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)):
        owner = call.func.value.id
    return _module_ctx_for(_call_name(call), owner, ctx)


def _module_ctx_for(name: str, owner: Optional[str], ctx: "_Ctx") -> tuple:
    """Та же половина разрешения ввоза, но спрошенная ИМЕНЕМ, а не зовом.

    Третьему потребителю (:func:`_resolve_base` — базовый класс объявлен ИМЕНЕМ,
    зова у него нет) понадобилось ровно то же правило. Своя копия означала бы,
    что база разрешается иначе, чем конструктор и функция, и тогда вердикт
    зависел бы от того, каким путём мера дошла до класса (дефект, закрытый
    ADR-1099 п. 2 внутри одного хопа).
    """
    module = ctx.imported.get(name)
    if module is None and owner:
        module = ctx.imported.get(owner)
    if module is None or ctx.resolve is None:
        return None, "unresolved"
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
        return None, "unresolved"
    return sub, f"import:{module}"


def _resolve_class(call: ast.Call, ctx: "_Ctx") -> tuple:
    """Класс-получатель зова: объявление, КОНТЕКСТ его модуля и где он измерен."""
    name = _call_name(call)
    if name in ctx.classes:
        return ctx.classes[name], ctx, "local"
    sub, hop = _module_ctx(call, ctx)
    if sub is None:
        return None, None, hop
    cls = sub.classes.get(name)
    if cls is None:
        return None, None, "unresolved"
    return cls, sub, hop


def _resolve_base(dotted: str, ctx: "_Ctx") -> tuple:
    """Базовый класс по его имени в коде: объявление и КОНТЕКСТ его модуля.

    Спрашивается ТОЙ ЖЕ половиной разрешения ввоза, что конструктор и функция
    (:func:`_module_ctx_for`). «База НЕ РАЗРЕШЕНА» и «базу судить нечем» —
    разные утверждения, и до 25.11 мера печатала их одной строкой: база,
    лежащая в ТОМ ЖЕ модуле, объявлялась неподсудной наравне с чужой.
    """
    parts = dotted.split(".")
    name = parts[-1]
    if len(parts) == 1 and name in ctx.classes:
        return ctx.classes[name], ctx
    sub, _hop = _module_ctx_for(name, parts[0] if len(parts) > 1 else None, ctx)
    if sub is None:
        return None, None
    cls = sub.classes.get(name)
    if cls is None:
        return None, None
    return cls, sub


def _class_methods(cls: ast.ClassDef, ctx: "_Ctx") -> tuple:
    """Методы класса И его РАЗРЕШИМЫХ баз, плюс имена баз, разрешить которые нечем.

    Унаследованный метод читает поле `self.X` ровно так же, как свой, и
    невидимость его для меры была границей МЕРЫ, а не свойством кода. Замер
    25.11 (цикл #1245) показал, что эта граница схлопывала ТРИ разных состояния
    в один вердикт с одним текстом: настоящего ЧЛЕНА класса (метод базы собирает
    путь к отчёту из поля), честную неразрешимость чужой базы и измеренный ноль.
    Первое из трёх — утечка, о которой мера молчала.

    Обход транзитивный (база базы — тоже база) и защищён от цикла: пара
    «модуль + имя класса» судится один раз.
    """
    out: list = []
    unresolved: list = []
    seen: set = set()
    queue: list = [(cls, ctx)]
    while queue:
        node, nctx = queue.pop(0)
        step = (nctx.key, node.name)
        if step in seen:
            continue
        seen.add(step)
        for method in _methods(node):
            out.append((method, nctx, node.name))
        for dotted in _base_names(node):
            base, bctx = _resolve_base(dotted, nctx)
            if base is None or bctx is None:
                if dotted not in unresolved:
                    unresolved.append(dotted)
                continue
            queue.append((base, bctx))
    return out, unresolved


def _into_object(cls: ast.ClassDef, call: ast.Call, names: set,
                 node: Optional[ast.AST], ctx: "_Ctx", hops_left: int,
                 visited: frozenset, where: str) -> tuple:
    """Что делает с величиной САМ ОБЪЕКТ, а не только его конструктор.

    Граница ADR-1098 стояла здесь: `Touch(hit, …)` разрешался НИКАК, и мера
    печатала «получатель НЕ РАЗРЕШЁН». Причина была честной, но населением за
    границей она не была — а величина, легшая в поле, живёт дальше в КАЖДОМ
    методе, это поле читающем.

    Поток внутри объекта прослеживается ПО ИМЕНИ ПОЛЯ — той же мерой, что поток
    внутри функции прослеживается по имени параметра, и с тем же признанным
    огрублением: `self.token` и `other.token` для неё одно имя. Огрубление
    ошибается в сторону НАХОДКИ, а не в сторону «чисто».

    Судятся методы ЭТОГО класса И его РАЗРЕШИМЫХ баз (:func:`_class_methods`).
    Прежняя редакция перечисляла только свои и отвечала третьим исходом
    «унаследованные методы мерой НЕ СУДЯТСЯ» — один вердикт с одним текстом на
    ТРИ разных состояния, и одним из трёх был настоящий ЧЛЕН класса (метод
    базы, собирающий путь к отчёту из поля). Неразрешимая база остаётся третьим
    исходом и теперь НАЗЫВАЕТСЯ поимённо — она отвечает на свой вопрос, а не за
    базу, лежащую в том же модуле.
    """
    init = _init_of(cls)
    param, refusal = _ctor_param(cls, init, call, names, node, ctx)
    if param is None:
        return UNMEASURED, f"{where}: {refusal}"
    step = (ctx.key, cls.name, param)
    if step in visited:
        return (UNMEASURED,
                f"{where}: ЦИКЛ передач — конструктор {cls.name!r} уже судился "
                f"на этой дороге, НЕ ИЗМЕРЕНО")
    visited = visited | {step}
    results: list = []
    if init is not None:
        results.append(_follow(init, {param}, f"{where}.__init__", ctx,
                               hops_left, visited))
        fields = _fields_fed_by(init, param)
    else:
        # Сгенерированный конструктор: поле зовётся так же, как параметр.
        fields = [param]
    methods, unresolved_bases = _class_methods(cls, ctx)
    read_by: list = []
    for field in sorted(set(fields)):
        for method, mctx, owner in methods:
            if method is init:
                continue
            if not any(_mentions_name(stmt, field)
                       for stmt in _own_statements(method)):
                continue
            read_by.append((field, method, mctx, owner))
    for field, method, mctx, owner in read_by:
        label = (f"{where}.{method.name}" if owner == cls.name
                 else f"{where}.{owner}.{method.name}")
        results.append(_follow(method, {field}, label, mctx,
                               hops_left - 1, visited))
    where_fields = ", ".join(sorted(set(fields)))
    if fields and unresolved_bases:
        results.append((
            UNMEASURED,
            f"{where}: величина легла в поле {where_fields}, а базовые классы "
            f"НЕ РАЗРЕШЕНЫ ({', '.join(unresolved_bases)}) — что делают с полем "
            f"их методы, мерой не судится, НЕ ИЗМЕРЕНО"))
    if fields and not read_by and not unresolved_bases:
        results.append((
            "local_only",
            f"{where}: величина легла в поле {where_fields}, и НИ ОДИН метод "
            f"класса ни его РАЗРЕШИМЫХ баз её не читает — ИЗМЕРЕННЫЙ ноль, "
            f"проверенный обходом"))
    if not results:
        return (UNMEASURED,
                f"{where}: конструктор {cls.name!r} разрешён, но ни одного "
                f"места, куда попало значение, не найдено — НЕ ИЗМЕРЕНО")
    results.sort(key=lambda r: VERDICT_ORDER.index(r[0]))
    return results[0]


def _into_receiver(call: ast.Call, ctx: "_Ctx", names: set,
                   node: Optional[ast.AST], hops_left: int,
                   visited: frozenset, label: str) -> tuple:
    """ЕДИНСТВЕННАЯ дверь «войти в получателя»: функция ЛИБО конструктор класса.

    Дверей было три (:func:`_handover`, :func:`_flow_for_direct_call` и цикл
    :func:`_follow`), и каждая разрешала получателя своей копией кода. Копий
    больше нет намеренно: разойдись они — конструктор стал бы получателем на
    одной дороге и неразрешимым на другой, то есть вердикт зависел бы от того,
    каким путём мера дошла до зова.
    """
    func, sub, hop = _resolve_callee(call, ctx)
    if func is not None and sub is not None:
        param = (_param_by_identity(func, call, node) if node is not None
                 else _param_for(func, call, names))
        if param is None:
            return (UNMEASURED,
                    f"{label}: параметр получателя, принявший значение, "
                    f"НЕ РАЗРЕШЁН — НЕ ИЗМЕРЕНО", hop)
        step = (sub.key, getattr(func, "name", "?"), param)
        if step in visited:
            return (UNMEASURED,
                    f"{label}: ЦИКЛ передач — этот получатель уже судился на "
                    f"этой дороге, НЕ ИЗМЕРЕНО", hop)
        verdict, why = _follow(func, {param}, label, sub, hops_left,
                               visited | {step})
        return verdict, why, hop
    cls, csub, chop = _resolve_class(call, ctx)
    if cls is None or csub is None:
        return (UNMEASURED,
                f"{label}: исходник получателя НЕ РАЗРЕШЁН — НЕ ИЗМЕРЕНО",
                chop)
    verdict, why = _into_object(cls, call, names, node, csub, hops_left,
                                visited, label)
    return verdict, why, chop


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
        who = _call_name(call) or "<?>"
        verdict, why, _hop = _into_receiver(call, ctx, local, None,
                                            hops_left - 1, visited,
                                            f"{where} → {who}")
        results.append((verdict, why))
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
    receiver = _call_name(call) or None
    verdict, why, hop = _into_receiver(call, ctx, set(), node, max_hops - 1,
                                       frozenset(),
                                       f"получатель {receiver!r}")
    return Flow(mention.token, mention.line, None, verdict, why, receiver, hop)


def _handover(mention, binding, call, names, ctx: "_Ctx",
              max_hops: int) -> Flow:
    """Передача значения помощнику: разрешить его и судить ЕГО тело — И ДАЛЬШЕ.

    Неразрешимый помощник — третий исход с названной причиной, а не «не
    утекает»: исходника у него нет, и выдумать его поведение нечем. Тело,
    отдающее значение ТРЕТЬЕМУ, судится по той же дороге до предела
    `max_hops`, а исчерпанный предел тоже есть третий исход (ADR-1098).
    """
    receiver = _call_name(call) or None
    verdict, why, hop = _into_receiver(call, ctx, names, None, max_hops - 1,
                                       frozenset(),
                                       f"получатель {receiver!r}")
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
