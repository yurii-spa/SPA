"""Кто спрашивает «та ли это книга» у прибора, судящего по журналу ходов.

Заказ владельца **G97 п. 2** (хвост `ADR-510`, 29.09) дословно:

> «Вопрос „та ли это книга“ задан ОДНОЙ пробой, а нужен он многим. Проба `Risk`
> спрашивает `current_positions.json`, потому что перепись судит последнее
> исполненное состояние. Ровно тем же материалом пользуются `Economics`,
> `Persistence` и (судя по имени) `Anti-churn`. Замерить: сколько приборов,
> читающих `trades.json`, выносят вердикт О НАСТОЯЩЕМ, и у скольких из них
> тождество судимого состояния со стоящей книгой не спрашивает никто. Общий
> ответ („один вопрос — одно место“) принимать ТОЛЬКО после замера населения:
> до него вынос кода в общую функцию есть обобщение одного случая.»

Вред, ради которого прибор написан
---------------------------------------------------------------------------
Прибор, восстановивший состояние книги из журнала ходов, выносит вердикт о том,
как дела СЕЙЧАС. Журнал пополняется только тогда, когда ход БЫЛ, поэтому три
разных мира дают у него один и тот же вид:

* система действительно успокоилась — вердикт верен;
* замороженный канон `data/` в git (ходов 7 против 34 живых) — вердикт о чужом
  дереве;
* книга двигалась МИМО записи — ход без записи не породит находки ни у какого
  прибора, сверяющего состояния по записям.

Различает их ОДИН вопрос, и он не о возрасте журнала: сходится ли состав
состояния, на котором журнал кончается, с книгой, которая стои́т сегодня
(`current_positions.json` переписывается КАЖДЫМ дневным циклом). Тишина там, где
вопрос не задан, читается как зелёное — это `ложная зелёная`, тише красной строки
и потому опаснее её.

Почему это перепись, а не правка
---------------------------------------------------------------------------
Заказ прямо запрещает обратный порядок: «общий ответ принимать ТОЛЬКО после
замера населения: до него вынос кода в общую функцию есть обобщение одного
случая». К моменту замера общая функция (`card_acceptance._standing_book_liveness`,
цикл #729) уже вынесена и обслуживает три пробы; число, которого не хватало, —
сколько приборов остаётся СНАРУЖИ неё. Прибор отвечает на это и не правит ничего
(`applied=False`).

Как мерится: ТРИ оси, и ни одна не заменяет другую
---------------------------------------------------------------------------
**Ось дороги — «читает ли он журнал ВООБЩЕ».** Токен в файле читателем не делает
(урок ADR-550): имя `trades.json` стои́т и в перечне носителей у
`decision_journal_coverage`, который журнал не открывает ни строкой. Дорога
меряется ПОТОКОМ ЗНАЧЕНИЯ до неподвижной точки, и у неё несколько форм — каждая
найдена замером, а не придумана:

1. **язык** — литерал → имя, связанное выражением, которое его поминает →
   элемент цикла по такому имени → получатель чтения (`open`, `.read_text`,
   `.read_bytes`, `.open`);
2. **ЗАГРУЗЧИК** — функция, читающая с диска значение СВОЕГО аргумента. Их
   четыре подвида, и каждый был пропущен первой редакцией:
   свой (`_load(d / "trades.json")` у `scripts/book_second_record.py`),
   **метод своего класса** (`self._read_json(self.data_dir / …)` у
   `pre_launch_validation`), **ввезённый у соседа**
   (`from …capital_shadow.intent import _read_json` у `readiness`, `read_state`
   у API) и **цепочка** — загрузчик, который сам диск не трогает, а передаёт
   аргумент дальше (`book_digest_and_asof` → `_read_json` у `reconcile`);
   поэтому реестр загрузчиков считается ДО НЕПОДВИЖНОЙ ТОЧКИ. Ввезённое имя
   сверяется с ИСХОДНЫМ у модуля-владельца, а не с локальным псевдонимом, и имя,
   загрузчиком не являющееся, дорогой не делает;
3. **умолчание параметра** — `trades_filename: str = TRADES_FILENAME` у
   `act_day_recovery.marked_moves`. Без этой формы прибор, весь предмет
   которого — восстановление ACT-дня ПО ЖУРНАЛУ, выпадал из населения молча.

Четвёртая дорога — через ПОМОЩНИКА ЧУЖОГО модуля (предел глубины
:data:`HELPER_DEPTH` — ВЫБОР, а не свойство дерева). Ввоз любого имени из
модуля-читателя дорогой НЕ является: ввезённое имя обязано само читать журнал.
У ввоза при этом ДВЕ орфографии, и обе населены: `from m import read_journal`
зовётся голым именем, `import m as x` — атрибутом `x.read_journal`. Правило,
знавшее только первую, теряло вторую молча; нашёл это не разбор дерева, а
собственный контроль переписи.

**Третий исход дороги назван ОТДЕЛЬНО.** Значение журнала, ушедшее в вызов на
модуле, добытом В РАНТАЙМЕ (`mod._load(d / "trades.json")` у
`unobserved_leg_remedy_class`), даёт ``road_unmeasured``: прочитан он там или
нет — по дереву НЕ ВИДНО. Сложить такой файл с «имя стои́т, а чтения нет»
значило бы выдать НЕЗНАНИЕ за ИЗМЕРЕННОЕ ОТСУТСТВИЕ и спрятать читателя;
пустое население этот исход тоже не гасит.

**Ось времени — «о настоящем ли вердикт».** Род вердикта берётся у ПРЕДМЕТА, а не
у окрестности: вердикт о настоящем опирается на ХВОСТ журнала, вердикт об истории
— на все записи. Опора на хвост читается двумя формами, и обе механические:
``tail_selected`` — явный выбор последней записи (``[-1]``, ``[-1:]``, ``.pop()``,
``max(..., key=…)``, ``sorted(…)[-1]``); ``loop_carried`` — обход записей, у
которого имя, присвоенное В ТЕЛЕ, читается ПОСЛЕ цикла (накопленное итоговое
состояние — ровно та форма, которой `book_oscillation_census` восстанавливает
книгу). Ни того, ни другого ⇒ ``whole_history``.

**Ось вопроса — «спрашивает ли КТО-НИБУДЬ».** Три исхода: ``asks_self`` — прибор
сам читает стоящую книгу; ``asks_probe`` — за него спрашивает проба §49, которая
его грузит; ``asks_nobody``. Отвечающий «никто» и есть ответ заказа.

**Имя стоящей книги НЕ перепечатано.** Оно читается из
`card_acceptance.STANDING_BOOK_FILE` разбором исходника — второе место для имени
разошлось бы молча (ADR-220). Константы в дереве нет — или приёмку не удалось разобрать — ⇒
:class:`Unmeasured`, а не умолчание.

**Помощники тождества тоже ИЗМЕРЕНЫ, а не перечислены.** Функция
`card_acceptance` считается помощником тождества, если ЕЁ тело читает стоящую
книгу; список имён в этом файле был бы претензией, которая ветшает молча.

Семь ложных членов, и каждый ИЗМЕРЕН, а не предположен
---------------------------------------------------------------------------
Первая редакция правила ошибалась в ОБЕ стороны, и ни одна ошибка не нашлась
рассуждением: шесть из семи вскрыл РУЧНОЙ ПОИМЁННЫЙ ОБХОД файлов, которые
перепись объявила «поминающими имя». Население от этого выросло с 21 до 26, а
ответ заказа — с 4 до 5. Методический вывод: собственному «не читает» без
поимённой сверки верить нельзя — это та же претензия без доказательства, против
которой написан весь ряд.

* **поток по дереву целиком** (без областей видимости) объявил помощниками
  тождества 21 функцию `card_acceptance` вместо ОДНОЙ настоящей
  (`_standing_book_liveness`): `path` одной функции засчитывался другой. Ошибка
  в сторону «за прибор уже спрашивают» — то есть в сторону ЗАНИЖЕНИЯ ответа;
* **любое имя, ввезённое из читателя**, дало 42 читателя вместо 19 и выдуманную
  находку: `python_reader_clock_doors` числился судящим о книге по журналу,
  которого он не касается. Ошибка в сторону ВЫДУМАННОЙ находки, и она хуже
  молчания — настоящую от неё не отличить;
* **забытое умолчание параметра** роняло `act_day_recovery` в «поминает имя».
  Ошибка в сторону МОЛЧАНИЯ о настоящем приборе;
* **одна орфография ввоза из двух** теряла дорогу `import m as x` →
  `x.read_journal(...)`. Сегодня эта форма в дереве не населена, поэтому ответ
  от правки не изменился — и это важно: промах был бы МОЛЧАЛИВЫМ, пока кто-то не
  напишет вторую орфографию. Нашёл его контроль переписи, а не замер дерева;
* **загрузчиком считался только СВОЙ** — трое настоящих читателей журнала
  (`capital_shadow/readiness`, `api/routers/misc`, `pre_launch_validation`)
  числились поминающими имя. Ошибка в сторону МОЛЧАНИЯ, и самая крупная: один
  из троих берёт ХВОСТ журнала, то есть судит о настоящем;
* **цепочка загрузчиков мерилась одним шагом** — `reconcile` выпадал, потому что
  его `book_digest_and_asof` диск не трогает, а зовёт `_read_json`;
* **метод своего класса загрузчиком не считался** — `self._read_json(…)`.

Поэтому поток считается ПО ОБЛАСТЯМ (модуль без тел функций — и каждая функция
отдельно), засеваясь именами уровня модуля и умолчаниями своих параметров.
Непрослеженный поток падает в третий исход, а не выдаётся ни за «читает», ни за
«не читает».

Четыре исхода различимы (инв. #17)
---------------------------------------------------------------------------
У каждой оси свой третий исход, и ни один не выдаётся за ноль: исходник не
прочитан или не разобран ⇒ файл попадает в ``unparsed`` с причиной, а код
возврата у `main` ненулевой. Пустое население ⇒ «НЕ ИЗМЕРЕНО», а не «чисто»
(урок `pyflakes`, #465).

ADVISORY: прибор только ЧИТАЕТ. Денег, публичных чисел и необратимого не касается.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys

#: Журнал ходов — предмет заказа дословно.
JOURNAL_NAME = "trades.json"

#: Где объявлено имя стоящей книги. Перепись читает имя ОТТУДА, а не держит копию.
STANDING_BOOK_SOURCE = "spa_core/monitoring/card_acceptance.py"
STANDING_BOOK_CONST = "STANDING_BOOK_FILE"

#: Каталоги разбора. Тесты исключены намеренно: предмет — приборы, а не их контроли.
SEARCH_DIRS = ("spa_core", "scripts")

#: Предел дороги через помощника. ВЫБОР переписи, а не свойство дерева.
HELPER_DEPTH = 2

#: Получатели чтения. Имя считается прочитанным, когда доезжает сюда.
READ_ATTRS = frozenset({"read_text", "read_bytes", "open", "read"})

#: Ось дороги.
ROAD_DIRECT = "reader_direct"
ROAD_HELPER = "reader_through_helper"
ROAD_NAMES_ONLY = "names_only"
ROAD_UNMEASURED = "road_unmeasured"
ROADS = (ROAD_DIRECT, ROAD_HELPER, ROAD_NAMES_ONLY, ROAD_UNMEASURED)

#: Ось времени.
TENSE_TAIL = "tail_selected"
TENSE_LOOP = "loop_carried"
TENSE_HISTORY = "whole_history"
TENSE_UNMEASURED = "tense_unmeasured"
TENSES = (TENSE_TAIL, TENSE_LOOP, TENSE_HISTORY, TENSE_UNMEASURED)

#: Ось вопроса.
ASKS_SELF = "asks_self"
ASKS_PROBE = "asks_probe"
ASKS_NOBODY = "asks_nobody"
ASKS = (ASKS_SELF, ASKS_PROBE, ASKS_NOBODY)

#: Вердикт о настоящем — это опора на хвост журнала любой из двух форм.
PRESENT_TENSES = (TENSE_TAIL, TENSE_LOOP)


class Unmeasured(RuntimeError):
    """Ответить нечем. Не ноль и не «чисто» — причина называется вслух."""


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]


# ── поток значения ──────────────────────────────────────────────────────────

def _bound_names(target: ast.AST) -> list[str]:
    """Имена, связываемые целью присваивания (включая распаковку кортежа)."""
    out: list[str] = []
    for node in ast.walk(target):
        if isinstance(node, ast.Name):
            out.append(node.id)
    return out


def _mentions(expr: ast.AST, literals: frozenset[str], names: set[str],
              nodes: set[int]) -> bool:
    """Поминает ли выражение семя: литерал, уже заражённое имя или узел-источник."""
    for node in ast.walk(expr):
        if id(node) in nodes:
            return True
        if isinstance(node, ast.Constant) and node.value in literals:
            return True
        if isinstance(node, ast.Name) and node.id in names:
            return True
    return False


def _walk_outside_functions(tree: ast.AST):
    """Обход дерева БЕЗ тел функций: так собирается область видимости модуля."""
    stack = [tree]
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            stack.append(child)


def _module_level_tainted(tree: ast.AST, literals: frozenset[str]) -> set[str]:
    """Имена уровня модуля, происходящие от семени (`JOURNAL_NAME = "trades.json"`)."""
    names: set[str] = set()
    changed = True
    carriers = [(t, v) for node in _walk_outside_functions(tree)
                for t, v in _carriers_of(node)]
    while changed:
        changed = False
        for targets, value in carriers:
            if not _mentions(value, literals, names, set()):
                continue
            for target in targets:
                for name in _bound_names(target):
                    if name not in names:
                        names.add(name)
                        changed = True
    return names


def _scopes(tree: ast.AST) -> list[tuple[str, ast.AST]]:
    """Области видимости модуля: сам модуль (без тел функций) и каждая функция.

    Поток имён считается В ОБЛАСТИ, а не по дереву целиком. Слияние областей
    давало бы `path.read_text()` одной функции в заслугу другой: замер первой
    редакции объявил помощниками тождества 21 функцию `card_acceptance` вместо
    трёх настоящих — ошибка В СТОРОНУ «за прибор уже спрашивают», то есть в
    сторону ЗАНИЖЕНИЯ ответа заказа. Именно её и нельзя допускать.
    """
    out: list[tuple[str, ast.AST]] = [("<module>", _ModuleScope(tree))]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, node))
    return out


class _ModuleScope(ast.AST):
    """Область видимости модуля: его узлы без тел функций."""

    _fields = ()

    def __init__(self, tree: ast.AST) -> None:
        super().__init__()
        self._nodes = list(_walk_outside_functions(tree))


def _scope_nodes(scope: ast.AST) -> list[ast.AST]:
    if isinstance(scope, _ModuleScope):
        return scope._nodes
    return list(ast.walk(scope))


def _carriers_of(node: ast.AST) -> list[tuple[list[ast.AST], ast.AST]]:
    """Переход значения от выражения к имени у ОДНОГО узла."""
    if isinstance(node, ast.Assign):
        return [(list(node.targets), node.value)]
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
        return [([node.target], node.value)]
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return [([node.target], node.iter)]
    if isinstance(node, ast.comprehension):
        return [([node.target], node.iter)]
    if isinstance(node, ast.withitem) and node.optional_vars is not None:
        return [([node.optional_vars], node.context_expr)]
    return []


def _scope_tainted(scope: ast.AST, literals: frozenset[str],
                   seeded: set[str], seed_nodes: set[int] | None = None) -> set[str]:
    """Заражённые имена ОДНОЙ области, засеянной именами уровня модуля."""
    nodes = seed_nodes or set()
    names = set(seeded)
    carriers = [c for node in _scope_nodes(scope) for c in _carriers_of(node)]
    changed = True
    while changed:
        changed = False
        for targets, value in carriers:
            if not _mentions(value, literals, names, nodes):
                continue
            for target in targets:
                for name in _bound_names(target):
                    if name not in names:
                        names.add(name)
                        changed = True
    return names


def _tainted_params(fn: ast.AST, literals: frozenset[str],
                    seeded: set[str]) -> set[str]:
    """Параметры, чьё УМОЛЧАНИЕ происходит от семени.

    Третья форма дороги, и она населена: `act_day_recovery.marked_moves` берёт
    `trades_filename: str = TRADES_FILENAME` и читает `_read_json(data_dir /
    trades_filename)`. Правило без умолчаний объявило бы прибор, весь предмет
    которого — восстановление дня ПО ЖУРНАЛУ, «просто поминающим имя».
    """
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return set()
    args = fn.args
    positional = list(args.posonlyargs) + list(args.args)
    out: set[str] = set()
    for arg, default in zip(positional[len(positional) - len(args.defaults):],
                            args.defaults):
        if default is not None and _mentions(default, literals, seeded, set()):
            out.add(arg.arg)
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if default is not None and _mentions(default, literals, seeded, set()):
            out.add(arg.arg)
    return out


def _param_readers(tree: ast.AST) -> frozenset[str]:
    """Функции модуля, читающие с диска значение СВОЕГО аргумента.

    Шаг в такого помощника НЕСУЩИЙ, а не для полноты (урок ADR-550). Замер
    показал цену его отсутствия на `scripts/book_second_record.py`: там стои́т
    `_load(d / "trades.json")`, и правило, знающее только `open`/`.read_text`,
    объявило бы настоящего читателя журнала «просто поминающим имя» — ошибка В
    СТОРОНУ МОЛЧАНИЯ, то есть ровно та, которой перепись не имеет права делать.
    """
    empty: frozenset[str] = frozenset()
    functions: list[tuple[str, ast.AST, set[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args
        params = {a.arg for a in (list(args.posonlyargs) + list(args.args) +
                                  list(args.kwonlyargs))}
        if args.vararg:
            params.add(args.vararg.arg)
        #: `self` параметром-носителем не является: это получатель, а не путь.
        params.discard("self")
        params.discard("cls")
        if params:
            functions.append((node.name, node, params))

    #: Цепочка загрузчиков считается ДО НЕПОДВИЖНОЙ ТОЧКИ: `book_digest_and_asof`
    #: не читает диск сам, он передаёт свой аргумент в `_read_json`. Правило
    #: глубиной в один шаг объявило бы `capital_shadow/reconcile` «поминающим
    #: имя» — и снова ошиблось бы МОЛЧАНИЕМ о настоящем читателе.
    out: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, node, params in functions:
            if name in out:
                continue
            names = _scope_tainted(node, empty, params)
            if _scope_read_sites(node, empty, names, frozenset(out)):
                out.add(name)
                changed = True
    return frozenset(out)


def _direct_read_sites(scope: ast.AST, literals: frozenset[str],
                       names: set[str]) -> list[ast.Call]:
    """Чтение самим языком: `open(...)`, `.read_text()`, `.read_bytes()`, `.open()`."""
    out: list[ast.Call] = []
    for node in _scope_nodes(scope):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in READ_ATTRS:
            if _mentions(func.value, literals, names, set()):
                out.append(node)
        elif isinstance(func, ast.Name) and func.id == "open":
            if any(_mentions(a, literals, names, set()) for a in node.args):
                out.append(node)
    return out


def _scope_read_sites(scope: ast.AST, literals: frozenset[str], names: set[str],
                      param_readers: frozenset[str] = frozenset()) -> list[ast.Call]:
    """Чтение самим языком ЛИБО через помощника того же модуля."""
    out = _direct_read_sites(scope, literals, names)
    if not param_readers:
        return out
    for node in _scope_nodes(scope):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            callee = func.id
        elif (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
              and func.value.id in ("self", "cls")):
            #: `self._read_json(self.data_dir / "trades.json")` — метод того же
            #: класса есть тот же помощник; правило без него роняло
            #: `pre_launch_validation` в «поминает имя».
            callee = func.attr
        else:
            continue
        if callee not in param_readers:
            continue
        payload = list(node.args) + [kw.value for kw in node.keywords]
        if any(_mentions(a, literals, names, set()) for a in payload):
            out.append(node)
    return out


def _runtime_module_names(tree: ast.AST) -> set[str]:
    """Имена, связанные с модулем, добытым В РАНТАЙМЕ (`importlib`, `spec_*`)."""
    out: set[str] = set()
    for targets, value in [c for node in ast.walk(tree)
                           for c in _carriers_of(node)]:
        for call in ast.walk(value):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr in ("import_module", "module_from_spec",
                                           "spec_from_file_location")):
                for target in targets:
                    out.update(_bound_names(target))
    return out


def _unresolved_read_doors(tree: ast.AST, filename: str,
                           param_readers: frozenset[str]) -> list[str]:
    """Двери, за которые перепись заглянуть НЕ МОЖЕТ: `mod._load(d / <журнал>)`.

    Значение журнала уходит в вызов на модуле, добытом в рантайме, — прочитан он
    там или нет, по дереву не видно. Это ТРЕТИЙ ИСХОД, и смешивать его с «имя
    стои́т, а чтения нет» нельзя: первое есть незнание, второе — измеренное
    отсутствие (инв. #17).
    """
    literals = frozenset({filename})
    runtime = _runtime_module_names(tree)
    if not runtime:
        return []
    seeded = _module_level_tainted(tree, literals)
    doors: list[str] = []
    for _name, scope in _scopes(tree):
        names = _scope_tainted(scope, literals,
                               seeded | _tainted_params(scope, literals, seeded))
        for node in _scope_nodes(scope):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in runtime):
                continue
            payload = list(node.args) + [kw.value for kw in node.keywords]
            if any(_mentions(a, literals, names, set()) for a in payload):
                doors.append(f"{node.func.value.id}.{node.func.attr}")
    return sorted(set(doors))


def _reads_file(tree: ast.AST, filename: str,
                param_readers: frozenset[str] | None = None) -> list[ast.Call]:
    """Читает ли модуль файл с таким именем. Поток ПО ОБЛАСТЯМ, а не токен."""
    literals = frozenset({filename})
    helpers = _param_readers(tree) if param_readers is None else param_readers
    seeded = _module_level_tainted(tree, literals)
    out: list[ast.Call] = []
    for _scope_name, scope in _scopes(tree):
        names = _scope_tainted(scope, literals,
                               seeded | _tainted_params(scope, literals, seeded))
        out.extend(_scope_read_sites(scope, literals, names, helpers))
    return out


def _function_reads_file(fn: ast.AST, literals: frozenset[str], seeded: set[str],
                         param_readers: frozenset[str]) -> bool:
    """Читает ли ТЕЛО функции файл, чьё имя засеяно уровнем модуля."""
    names = _scope_tainted(fn, literals,
                           seeded | _tainted_params(fn, literals, seeded))
    return bool(_scope_read_sites(fn, literals, names, param_readers))


# ── ось времени ─────────────────────────────────────────────────────────────

def _loop_carried(scope: ast.AST, names: set[str], nodes: set[int]) -> bool:
    """Обход записей, чьё имя из тела читается ПОСЛЕ цикла (итоговое состояние)."""
    scope_nodes = _scope_nodes(scope)
    for loop in scope_nodes:
        if not isinstance(loop, (ast.For, ast.AsyncFor)):
            continue
        if not _mentions(loop.iter, frozenset(), names, nodes):
            continue
        assigned: set[str] = set()
        for stmt in loop.body:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Assign):
                    assigned.update(_bound_names(node.targets[0]))
                elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                    assigned.update(_bound_names(node.target))
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    # `moves.append(...)` — накопитель, объявленный до цикла.
                    if node.func.attr in ("append", "extend", "update", "add"):
                        assigned.update(_bound_names(node.func.value))
        if not assigned:
            continue
        start = getattr(loop, "lineno", 0)
        end = getattr(loop, "end_lineno", None) or start
        for node in scope_nodes:
            if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                    and node.id in assigned and getattr(node, "lineno", 0) > end):
                return True
    return False


def _tail_selected(scope: ast.AST, names: set[str], nodes: set[int]) -> bool:
    """Явный выбор последней записи у значения, пришедшего из журнала."""
    empty: frozenset[str] = frozenset()
    for node in _scope_nodes(scope):
        if isinstance(node, ast.Subscript):
            if not _mentions(node.value, empty, names, nodes):
                continue
            sl = node.slice
            if _is_minus_one(sl):
                return True
            if isinstance(sl, ast.Slice) and sl.lower is not None and _is_minus_one(sl.lower):
                return True
        elif isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id in ("max", "min")
                    and any(_mentions(a, empty, names, nodes) for a in node.args)):
                return True
            if (isinstance(func, ast.Attribute) and func.attr == "pop"
                    and _mentions(func.value, empty, names, nodes)):
                return True
    return False


def _is_minus_one(node: ast.AST) -> bool:
    return (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant) and node.operand.value == 1)


def _tense(tree: ast.AST, seeds: list[ast.Call]) -> str:
    """Опирается ли вердикт на хвост журнала. Третий исход — поток не прослежен.

    Считается ПО ОБЛАСТЯМ: семя (узел чтения) живёт в одной из них, и значение
    журнала не переходит в другую иначе как возвратом, которого эта мера не
    прослеживает, — поэтому непрослеженный поток честно падает в третий исход,
    а не выдаётся за «вердикт обо всей истории».
    """
    if not seeds:
        return TENSE_UNMEASURED
    nodes = {id(call) for call in seeds}
    empty: frozenset[str] = frozenset()
    traced = False
    loop = False
    for _scope_name, scope in _scopes(tree):
        names = _scope_tainted(scope, empty, set(), nodes)
        if not names:
            continue
        traced = True
        if _tail_selected(scope, names, nodes):
            return TENSE_TAIL
        if _loop_carried(scope, names, nodes):
            loop = True
    if loop:
        return TENSE_LOOP
    return TENSE_HISTORY if traced else TENSE_UNMEASURED


# ── разбор дерева ───────────────────────────────────────────────────────────

def _py_files(root: pathlib.Path) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for folder in SEARCH_DIRS:
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/tests/" in rel or rel.endswith("conftest.py"):
                continue
            out.append(path)
    return out


def _dotted(rel: str) -> str:
    stem = rel[:-len(".py")]
    if stem.endswith("/__init__"):
        stem = stem[:-len("/__init__")]
    return stem.replace("/", ".")


def _import_bindings(tree: ast.AST) -> list[tuple[str, str, str | None]]:
    """`(локальное имя, модуль, исходное имя)`. Исходное нужно, чтобы спросить у
    модуля-владельца, читает ли ИМЕННО эта функция свой аргумент: `from m import
    _read_json as load` обязан сверяться с `_read_json`, а не с `load`."""
    out: list[tuple[str, str, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                out.append((alias.asname or alias.name, node.module, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.append((alias.asname or alias.name.split(".")[0],
                            alias.name, None))
    return out


def _imported_names(tree: ast.AST) -> dict[str, str]:
    """Локальное имя → модуль, откуда оно ввезено (`from a.b import C as D`)."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                out[alias.asname or alias.name] = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split(".")[0]] = alias.name
    return out


def _called_names(tree: ast.AST) -> set[str]:
    """Имена, которые модуль ЗОВЁТ (ввоз без вызова читателем не делает)."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            out.add(func.id)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            out.add(func.value.id)
            out.add(f"{func.value.id}.{func.attr}")
    return out


# ── проба §49, спрашивающая за прибор ───────────────────────────────────────

def _same_module_calls(fn: ast.AST, defined: set[str]) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in defined:
                out.add(node.func.id)
    return out


def _reachable(start: str, edges: dict[str, set[str]], depth: int) -> set[str]:
    seen = {start}
    frontier = {start}
    for _ in range(depth):
        nxt: set[str] = set()
        for name in frontier:
            nxt |= edges.get(name, set()) - seen
        if not nxt:
            break
        seen |= nxt
        frontier = nxt
    return seen


def _acceptance_tree(source: pathlib.Path) -> ast.AST:
    """Разбор приёмки. Не прочитана или не разобрана ⇒ ТРЕТИЙ ИСХОД, не падение.

    Это тот же инв. #17, что и у населения: «приёмку разобрать не вышло» обязано
    быть отличимо и от «вопрос задают все», и от случайного обвала с трассировкой.
    """
    try:
        return ast.parse(source.read_text(encoding="utf-8"))
    except BaseException as exc:  # noqa: BLE001 — молчание здесь = fail-OPEN
        raise Unmeasured(
            f"приёмка {source} не разобрана ({type(exc).__name__}: {exc}) — ни имя "
            f"стоящей книги, ни пробы §49 не прочитаны, и «кто спрашивает» НЕ "
            f"ИЗМЕРЕНО (это не «никто» и не «все»)") from exc


def _probe_askers(source: pathlib.Path, standing_book: str,
                  depth: int = HELPER_DEPTH) -> tuple[set[str], list[str]]:
    """Модули (точечные имена), за которые тождество спрашивает проба §49.

    Возврат: `(модули, имена помощников тождества)`. Помощники ИЗМЕРЕНЫ — ими
    считаются функции `card_acceptance`, чьё тело читает стоящую книгу.
    """
    tree = _acceptance_tree(source)
    functions = {n.name: n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    defined = set(functions)
    edges = {name: _same_module_calls(fn, defined) for name, fn in functions.items()}

    #: Поток имени стоящей книги считается по МОДУЛЮ, а чтение ищется в теле
    #: функции. Семя (`STANDING_BOOK_FILE`) объявлено на уровне модуля, и замер
    #: только по поддереву функции дал бы НОЛЬ помощников при трёх настоящих —
    #: ложный ноль ровно того рода, против которого написан инв. #17.
    book_literals = frozenset({standing_book})
    book_names = _module_level_tainted(tree, book_literals)
    book_helpers = _param_readers(tree)
    identity = {name for name, fn in functions.items()
                if _function_reads_file(fn, book_literals, book_names, book_helpers)}

    consts: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        consts[target.id] = node.value.value

    #: Загрузчик прибора — функция, зовущая `import_module(<КОНСТАНТА>)`.
    loaders: dict[str, str] = {}
    for name, fn in functions.items():
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("import_module", "reload")):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Name) and arg.id in consts:
                    loaders[name] = consts[arg.id]
                elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    loaders[name] = arg.value

    asked: set[str] = set()
    for name in functions:
        reach = _reachable(name, edges, depth)
        if not (reach & identity):
            continue
        for fn_name in reach:
            if fn_name in loaders:
                asked.add(loaders[fn_name])
    return asked, sorted(identity)


def _standing_book_name(source: pathlib.Path) -> str:
    """Имя стоящей книги — у её объявления, не копией здесь."""
    tree = _acceptance_tree(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == STANDING_BOOK_CONST:
                    if isinstance(node.value.value, str):
                        return node.value.value
    raise Unmeasured(
        f"в {source} нет объявления {STANDING_BOOK_CONST} — имя стоящей книги НЕ "
        f"ПРОЧИТАНО, и держать его второй копией здесь было бы тем самым «одним "
        f"правилом в двух местах», которое расходится молча")


# ── замер ───────────────────────────────────────────────────────────────────

def measure(repo_root: str | pathlib.Path | None = None, *,
            journal: str = JOURNAL_NAME, depth: int = HELPER_DEPTH) -> dict:
    """Перепись «кто спрашивает, та ли это книга». Только читает."""
    root = pathlib.Path(repo_root) if repo_root else _repo_root()
    acceptance = root / STANDING_BOOK_SOURCE
    if not acceptance.exists():
        raise Unmeasured(
            f"{acceptance} в этом дереве нет — ни имя стоящей книги, ни пробы §49 "
            f"не прочитаны; население вопроса НЕ ИЗМЕРЕНО (это не ноль)")
    standing_book = _standing_book_name(acceptance)
    probe_asked, identity_helpers = _probe_askers(acceptance, standing_book, depth)

    files = _py_files(root)
    if not files:
        raise Unmeasured(
            f"в {root} не найдено ни одного разбираемого файла каталогов "
            f"{', '.join(SEARCH_DIRS)} — население НЕ ИЗМЕРЕНО")

    unparsed: list[dict] = []
    parsed: dict[str, dict] = {}
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except BaseException as exc:  # noqa: BLE001 — молчание здесь = fail-OPEN
            unparsed.append({"file": rel, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        parsed[rel] = {"tree": tree, "dotted": _dotted(rel)}

    #: Реестр ЗАГРУЗЧИКОВ: функция, читающая с диска значение своего аргумента.
    #: Собирается по ВСЕМУ дереву, потому что загрузчик сплошь и рядом живёт в
    #: соседнем модуле (`from spa_core.capital_shadow.intent import _read_json`,
    #: `read_state` у API). Правило, знавшее только своих, роняло в «поминает
    #: имя» трёх настоящих читателей журнала разом.
    own_loaders = {rel: _param_readers(info["tree"]) for rel, info in parsed.items()}
    by_dotted = {info["dotted"]: rel for rel, info in parsed.items()}

    def _accepted(rel: str) -> frozenset[str]:
        """Имена, зов которых считается чтением В ЭТОМ модуле.

        Свои загрузчики плюс ввезённые — и ввезённое имя сверяется с ИСХОДНЫМ
        у модуля-владельца, а не с локальным псевдонимом. Имя чужого модуля,
        который загрузчиком не является, сюда не попадает: иначе перепись
        выдумывала бы читателей (цена такой ошибки измерена на дороге помощника).
        """
        accepted = set(own_loaders[rel])
        for local, module, origin in _import_bindings(parsed[rel]["tree"]):
            owner = by_dotted.get(module)
            if owner is None or origin is None:
                continue
            if origin in own_loaders[owner]:
                accepted.add(local)
        return frozenset(accepted)

    #: Прямые читатели журнала — и отдельно те, у кого имя есть, а чтения нет.
    direct: dict[str, list[ast.Call]] = {}
    names_only: list[str] = []
    unresolved: list[dict] = []
    accepted_by_rel: dict[str, frozenset[str]] = {}
    for rel, info in parsed.items():
        tree = info["tree"]
        mentions = any(isinstance(n, ast.Constant) and n.value == journal
                       for n in ast.walk(tree))
        if not mentions:
            continue
        accepted_by_rel[rel] = _accepted(rel)
        sites = _reads_file(tree, journal, accepted_by_rel[rel])
        if sites:
            direct[rel] = sites
            continue
        doors = _unresolved_read_doors(tree, journal, accepted_by_rel[rel])
        if doors:
            unresolved.append({"file": rel, "doors": doors})
        else:
            names_only.append(rel)

    #: Что именно у читателя отдаёт журнал наружу: ИМЕНА функций, чьё тело до
    #: него доезжает. Ввоз любого имени из модуля-читателя дорогой НЕ является —
    #: первая редакция считала так и объявила `python_reader_clock_doors`
    #: судящим о книге по журналу, которого он не касается: 42 читателя вместо
    #: 17 и выдуманные находки. Ошибка в сторону ВЫДУМАННОЙ находки хуже
    #: молчания, потому что её нечем отличить от настоящей.
    exports: dict[str, frozenset[str]] = {}
    for rel in direct:
        tree = parsed[rel]["tree"]
        literals = frozenset({journal})
        helpers = accepted_by_rel[rel]
        seeded = _module_level_tainted(tree, literals)
        names = {fn.name for fn in ast.walk(tree)
                 if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and _function_reads_file(fn, literals, seeded, helpers)}
        exports[parsed[rel]["dotted"]] = frozenset(names)

    helper: dict[str, dict] = {}
    frontier = {d: names for d, names in exports.items() if names}
    for hop in range(1, depth + 1):
        found: dict[str, dict] = {}
        for rel, info in parsed.items():
            if rel in direct or rel in helper:
                continue
            imports = _imported_names(info["tree"])
            called = _called_names(info["tree"])
            for local, module in imports.items():
                if module not in frontier:
                    continue
                #: Зовётся именно ЧИТАЮЩЕЕ имя, и у ввоза две формы. `from m
                #: import read_journal` зовётся голым именем; `import m as x` —
                #: атрибутом `x.read_journal`. Правило, знающее только первую,
                #: теряло вторую молча (найдено своим же контролем).
                through = None
                for export in sorted(frontier[module]):
                    if local == export and local in called:
                        through = local
                        break
                    if f"{local}.{export}" in called:
                        through = f"{local}.{export}"
                        break
                if through is None:
                    continue
                seeds = [n for n in ast.walk(info["tree"])
                         if isinstance(n, ast.Call) and _call_names_to(n, through)]
                found[rel] = {"via": module, "depth": hop, "seeds": seeds,
                              "through": through}
                break
        if not found:
            break
        helper.update(found)
        frontier = {parsed[rel]["dotted"]: frozenset(
            fn.name for fn in ast.walk(parsed[rel]["tree"])
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(isinstance(n, ast.Call)
                    and _call_names_to(n, found[rel]["through"])
                    for n in ast.walk(fn)))
            for rel in found}
        frontier = {d: names for d, names in frontier.items() if names}

    rows: list[dict] = []
    for rel in sorted(set(direct) | set(helper)):
        info = parsed[rel]
        road = ROAD_DIRECT if rel in direct else ROAD_HELPER
        seeds = direct.get(rel) or helper[rel]["seeds"]
        tense = _tense(info["tree"], seeds)
        dotted = info["dotted"]
        if _reads_file(info["tree"], standing_book, _accepted(rel)):
            asks = ASKS_SELF
        elif dotted in probe_asked:
            asks = ASKS_PROBE
        else:
            asks = ASKS_NOBODY
        rows.append({
            "file": rel, "module": dotted, "road": road, "tense": tense,
            "asks": asks,
            "via": helper[rel]["via"] if rel in helper else None,
            "through": helper[rel]["through"] if rel in helper else None,
            "depth": helper[rel]["depth"] if rel in helper else 0,
        })

    road_counts = {name: 0 for name in ROADS}
    road_counts[ROAD_NAMES_ONLY] = len(names_only)
    road_counts[ROAD_UNMEASURED] = len(unresolved)
    tense_counts = {name: 0 for name in TENSES}
    asks_counts = {name: 0 for name in ASKS}
    for row in rows:
        road_counts[row["road"]] += 1
        tense_counts[row["tense"]] += 1
        asks_counts[row["asks"]] += 1

    present = [r for r in rows if r["tense"] in PRESENT_TENSES]
    findings = [r for r in present if r["asks"] == ASKS_NOBODY]

    return {
        "measured": True,
        "journal": journal,
        "standing_book": standing_book,
        "standing_book_source": STANDING_BOOK_SOURCE,
        "identity_helpers": identity_helpers,
        "probe_asked_modules": sorted(probe_asked),
        "depth": depth,
        "files_parsed": len(parsed),
        "population": len(rows),
        "road_counts": road_counts,
        "tense_counts": tense_counts,
        "asks_counts": asks_counts,
        "present_population": len(present),
        "rows": rows,
        "findings": findings,
        "names_only": sorted(names_only),
        "unresolved_doors": sorted(unresolved, key=lambda r: r["file"]),
        "unparsed": unparsed,
        "not_reported": [
            "ЧИТАЕТ ли прибор журнал на самом деле (дорога есть достижимость, "
            "а не исполнение)",
            "соседние журналы того же рода (`Economics` судит по "
            "`allocation_rationale_history*.jsonl`, и в это население не входит)",
            "ПРАВ ли прибор, который вопрос задаёт",
            "имя файла, вычисленное в рантайме",
        ],
        "applied": False,
    }


def _call_names_to(call: ast.Call, local: str) -> bool:
    """Зовёт ли вызов именно это имя — голое либо через точку."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id == local
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}" == local or func.value.id == local
    return False


def verdict(doc: dict) -> str:
    if doc.get("findings"):
        return "present_verdicts_without_the_question"
    return "every_present_verdict_is_asked"


def format_report(doc: dict) -> str:
    """Отчёт для шага 0-офис. Каждый ноль объявлен (инв. #17)."""
    if not doc.get("population"):
        # Ноль исходов на пустом населении не есть «чисто» (урок `pyflakes`, #465).
        plain = ("НЕ ИЗМЕРЕНО: кто спрашивает «та ли это книга» — ни одного читателя "
                 f"журнала {doc.get('journal')!r} не найдено; это НЕ «все спрашивают»")
        #: Пустое население НЕ ГАСИТ неразобранную дверь: иначе единственный
        #: третий исход исчез бы под словом «не найдено» — та же подмена
        #: незнания измеренным отсутствием, только этажом выше.
        doors = doc.get("unresolved_doors") or []
        if doors:
            plain += ("; при этом ДВЕРЬ НЕ РАЗОБРАНА у "
                      f"{len(doors)} файл(ов): "
                      + " · ".join(f"{r['file']} [{', '.join(r['doors'])}]"
                                   for r in doors[:4]))
        return plain
    roads, tenses, asks = doc["road_counts"], doc["tense_counts"], doc["asks_counts"]
    lines = [
        f"кто спрашивает «та ли это книга» (заказ G97 п. 2): читателей журнала "
        f"{doc['journal']} — {doc['population']}, из них о НАСТОЯЩЕМ судят "
        f"{doc['present_population']}; предел дороги через помощника {doc['depth']} "
        f"(ВЫБОР, не свойство дерева)",
        "  дорога: " + " · ".join(f"{k} {roads[k]}" for k in ROADS),
        "  время: " + " · ".join(f"{k} {tenses[k]}" for k in TENSES),
        "  вопрос: " + " · ".join(f"{k} {asks[k]}" for k in ASKS),
    ]
    lines.append(
        f"  ОТВЕТ заказа: у {len(doc['findings'])} из {doc['present_population']} "
        f"приборов, судящих о настоящем, тождество судимого состояния со стоящей "
        f"книгой ({doc['standing_book']}) не спрашивает НИКТО")
    for row in doc["findings"][:12]:
        via = f" ← {row['via']}" if row["via"] else ""
        lines.append(f"  [{ASKS_NOBODY}] {row['file']} ({row['tense']}, "
                     f"{row['road']}{via})")
    if len(doc["findings"]) > 12:
        lines.append(f"  … ещё {len(doc['findings']) - 12} находок(и) того же вида "
                     "(полный перечень — `--json`)")
    lines.append(
        f"  помощники тождества ИЗМЕРЕНЫ у {doc['standing_book_source']} "
        f"({len(doc['identity_helpers'])}): "
        f"{', '.join(doc['identity_helpers']) or '—'}; за приборы спрашивают пробы "
        f"§49 для {len(doc['probe_asked_modules'])} модул(я/ей)")
    if doc["names_only"]:
        lines.append(
            f"  цена правила: имя журнала стои́т, а чтения нет — {len(doc['names_only'])} "
            f"файл(ов) ({', '.join(doc['names_only'][:4])}"
            f"{'…' if len(doc['names_only']) > 4 else ''}); токен читателем не делает")
    if doc["unresolved_doors"]:
        lines.append(
            f"  ⚠️ ДВЕРЬ НЕ РАЗОБРАНА у {len(doc['unresolved_doors'])} файл(ов) "
            "(значение журнала уходит в вызов на модуле, добытом в рантайме — "
            "прочитан он там или нет, по дереву НЕ ВИДНО; это не «не читает»): "
            + " · ".join(f"{r['file']} [{', '.join(r['doors'])}]"
                         for r in doc["unresolved_doors"][:4]))
    if doc["unparsed"]:
        lines.append(f"  ⚠️ НЕ РАЗОБРАНО {len(doc['unparsed'])} файл(ов): " +
                     " · ".join(f"{u['file']} ({u['reason']})"
                                for u in doc["unparsed"][:3]))
    lines.append("  НЕ ДОКЛАДЫВАЕТ: " + " · ".join(doc["not_reported"]))
    lines.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--repo-root", default=None, help="дерево, о котором мерить")
    ap.add_argument("--journal", default=JOURNAL_NAME, help="журнал ходов")
    ap.add_argument("--depth", type=int, default=HELPER_DEPTH,
                    help="предел дороги через помощника")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    args = ap.parse_args(argv)

    try:
        doc = measure(args.repo_root, journal=args.journal, depth=args.depth)
    except Unmeasured as exc:
        if args.json:
            print(json.dumps({"measured": False, "reason": str(exc)},
                             ensure_ascii=False, indent=2))
        else:
            print(f"НЕ ИЗМЕРЕНО: {exc}")
        return 2

    print(json.dumps(doc, ensure_ascii=False, indent=2, default=str)
          if args.json else format_report(doc))
    if doc["unparsed"] or doc["unresolved_doors"]:
        return 2
    return 1 if doc["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
