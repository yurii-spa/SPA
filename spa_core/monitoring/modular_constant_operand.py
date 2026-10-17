#!/usr/bin/env python3
"""Модульная числовая постоянная как ОПЕРАНД — третья односторонность оси, замером.

Заказ **G115 п. 2** приказа владельца «Portfolio CIO» (поставлен ADR-541).
Дословно: «Модульная числовая постоянная — третья односторонность оси. Замерить
население класса: сколько мест вида ``КОНСТАНТА - значение`` ось сегодня не
видит, и есть ли среди них хоть одно поле-кандидат. Если населения нет —
записать это и закрыть, а не расширять ось на всякий случай.»

Что именно ось не видит
------------------------------------------------------------------------------
Ось ``arithmetic_derived`` (:mod:`spa_core.monitoring.identity_field_kind`)
называет родом не оператор, а ОПЕРАНД: числом выражение делает операнд,
числовой ПО ПОСТРОЕНИЮ — числовой литерал либо счёт/сумма/округление
(``_numeric_operand``). Модульная постоянная ``BEACON_MAX_AGE_S = 21600``
числовая по построению ровно так же — но она ИМЯ, а не литерал, и в
``scope.derived`` не попадает: туда входят имена, связанные с ПОСЧИТАННЫМ
значением, а ``= 21600`` ничего не считает. Поэтому ``BEACON_MAX_AGE_S - age``
ось молчит, а ``21600 - age`` называет находкой — одно и то же вычисление под
двумя написаниями.

Односторонность в сторону «чисто», как и две названные до неё (замыкание над
объемлющей функцией — задел G113 п. 3; порядок привязок — ADR-503).

Как мерено: ПОДСТАНОВКА ОПЕРАНДА, а не вторая копия правила
------------------------------------------------------------------------------
Второй разбор «что здесь арифметика» расходился бы с осью молча (урок #820:
второй поиск предмета, уже раскрытого соседом, РАСХОДИТСЯ). Поэтому правило
оси не копируется и не подменяется: прибор прогоняет НАСТОЯЩУЮ ось ДВАЖДЫ по
одному модулю —

1. как есть (ответ «что ось видит сегодня»);
2. по дереву, где каждое ЧТЕНИЕ модульной числовой постоянной заменено её
   литералом (ответ «что ось увидела бы, будь постоянная литералом»).

**Разница ответов и ЕСТЬ население класса.** Подстановка не выдумывает правило,
а исполняет само определение «числовой по построению»: если имя связано только
с числовым литералом, то его чтение и этот литерал — одно и то же значение.
Метод тот же, которым мерены классы #453 (pid) и #700 (git-окружение):
прогнать дважды, подменив одну дверь, и считать предметом класса то, у чего
сменился вердикт.

Что прибор НЕ доказывает
------------------------------------------------------------------------------
* **Годность рода в личность.** Правило «род ⇒ годность» отвергнуто замером
  (ADR-539/503), и этот прибор его не возвращает: он печатает НАСЕЛЕНИЕ, а не
  вердикт о поле. Ось не расширена ни на одно имя — заказ требовал замера.
* **Затенённое имя не подставляется ВОВСЕ.** Если имя постоянной где-нибудь в
  модуле затенено параметром, циклом или ``with``, подстановка его пропускает
  целиком — во всех областях, включая модульную. Односторонность названа:
  промах в сторону «чисто» (ЗАНИЖАЕТ население), и выбор сделан по той же
  причине, что у самой оси, — население не есть гейт, поэтому цена промаха
  есть недостающая строка отчёта, а не отвергнутое имя.

  **Цена этой односторонности ИЗМЕРЕНА (заказ G697 п. 1), а не оговорена.**
  До ADR-702 здесь стояло «население ЗАНИЖЕНО» без числа — то есть «33»
  могло быть как точным ответом, так и нижней границей, далёкой от правды, и
  различить это было нечем. Мера та же, что у самого прибора: прогнать его
  ДВАЖДЫ, подменив ровно одну дверь (``drop_shadowed``), и считать ценой то,
  у чего сменился вердикт (:func:`module_shadow_cost`, :func:`census`
  раздел ``shadow_cost``). Число печатается РЯДОМ с населением — там, где
  читатель видит «33», а не в одной справке.
* **Постоянная вне модульной области не считается постоянной.**
  ``def f(): LIMIT = 5`` — привязка функции, а не модуля; заказ назвал класс
  МОДУЛЬНЫМ, и расширять его здесь значило бы мерить не тот класс.
* **Имя, пере-связанное в модуле хоть раз с не-числом, постоянной не является.**
  ``X = 300`` … ``X = load()`` — по построению уже не число.
* **Имя, объявленное ``global``, постоянной не является ВОВСЕ** — и это вторая
  односторонность, заказом G697 п. 1 НЕ названная, с ОБРАТНЫМ направлением
  ошибки. ``_shadowed`` оси ловит параметры, циклы, ``with``, ``except``,
  импорт и включения, но НЕ присваивание: ``global X`` с ``X = time.time()``
  внутри функции имя не ЗАТЕНЯЕТ, а пере-связывает ТУ ЖЕ модульную привязку,
  и подстановка такого имени его литералом неверна не в одной области, а
  ВЕЗДЕ. Промах здесь в сторону НАХОДКИ (ложное обвинение), то есть опаснее
  названного, и признак у него механический: объявление ``global`` само и
  означает «модульная привязка ЗАПИСЫВАЕМА» (:func:`globals_declared`).
  Население на 2026-10-12 — **2** имени (``pendle_adapter._LLAMA_FAILED_AT``,
  ``allocator._live_apy_cache_ts``, оба ``= 0.0`` с ``global`` и присваиванием
  в функции), площадок сменило вердикт **0**. Ноль исправление НЕ отменяет:
  форма жива, и правило ADR-700 п. 3 на этот случай названо прямо.
* **Транзитивный случай назван ОТДЕЛЬНЫМ числом.** ``HALF = LIMIT / 2`` на
  модульном уровне делает ``HALF`` посчитанным, и поле, читающее ``HALF``,
  ось тоже не видит. Это тот же класс (значение происходит от постоянной), но
  в САМОМ выражении поля постоянной нет — поэтому ``direct`` и ``transitive``
  печатаются раздельно и не складываются в одно число.

  **ДЛИНА такой цепочки измерена (заказ G697 п. 3)**, а не оговорена:
  :func:`module_chain` ставит пределом раундов оси ``k = 0, 1, 2 …`` и
  спрашивает, при каком ``k`` ответ об этой площадке ПОЯВЛЯЕТСЯ. Один раунд
  петли оси добавляет ровно один шаг по имени, поэтому ``k`` и есть длина
  кратчайшей цепочки. ``steps == 0`` — шаг НЕ ПО ИМЕНИ (через обёртку), и
  различать это обязательно: обёртки ось ищет своей отдельной петлёй.

Два ПРЕДЕЛА самой оси — и их цена (заказ G697 п. 3)
------------------------------------------------------------------------------
Обход оси кончается на ``depth > DEPTH_LIMIT``, а петля привязок — на
``DERIVE_ROUNDS`` раундах. Оба предела возвращают ``None``, то есть говорят
«арифметики нет» там, где верный ответ — «НЕ ИЗМЕРЕНО» (инв. #17), и население
класса под таким молчанием есть нижняя граница НЕИЗВЕСТНОЙ глубины. Цена обоих
мерится :func:`axis_limit_cost` подстановкой в САМИ двери (отрицательный
стартовый ``depth`` даёт запас; бо́льший ``rounds`` — больше шагов), и печатается
РЯДОМ с населением (:func:`limit_report`). Утверждения двух дверей РАЗНОЙ СИЛЫ,
и это сказано вслух: про глубину говорит структура дерева (самое глубокое
выражение-значение против предела), про раунды — только измеренные цепочки.

Три исхода различимы на каждом уровне (инв. #17)
------------------------------------------------------------------------------
======================= ============================================
уровень                 третий исход
======================= ============================================
свод                    каталога нет в дереве ⇒ причина поимённо
свод                    ни один файл не разобран ⇒ ``UNMEASURED``
модуль                  файл не разобран ⇒ причина, не «постоянных нет»
модуль                  состав площадок разошёлся между двумя
                        прогонами ⇒ ``UNMEASURED`` с причиной, а не
                        молчаливое спаривание не тех мест
население кандидатов    перечень кандидатов не дан ⇒ ``None``, а не
                        «ни одного кандидата не задето»
длина цепочки           ось не отвечает о площадке и при полном пределе
                        ⇒ ``steps=None`` с причиной, а не ноль шагов
цена пределов           запаса по глубине не хватает ⇒ отказ с
                        названной причиной, а не «спрятано 0»
======================= ============================================

ADVISORY: прибор только ЧИТАЕТ исходники. ``_IDENTITY_FIELDS``, координаты,
RiskPolicy v1.0, стоп-кран и живой трек он не трогает.
"""

from __future__ import annotations

import argparse
import ast
import copy
import dataclasses
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # pragma: no cover - путь для прямого запуска
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import identity_field_kind as field_kind  # noqa: E402

SCHEMA = "modular_constant_operand.v1"

PRODUCER = "spa_core/monitoring/modular_constant_operand.py"


# --- память ОДНОГО прогона переписи по ОДНОМУ файлу ---------------------------
#
# Замер 2026-10-17 (CI #6, группа G01): `census()` по живому дереву шёл 90 с на
# этом Маке, и треть времени уходила на ПОВТОР уже сделанной работы над тем же
# файлом. Для каждого модуля с постоянными четыре ступени (`module_sites`,
# `module_shadow_cost`, `module_chain`, `axis_limit_cost`) заново разбирали
# ОДИН И ТОТ ЖЕ исходник, заново искали постоянные и затенение, заново
# копировали дерево подстановкой и заново прогоняли ось по ТОЙ ЖЕ копии с теми
# же пределами: `_axis_answers_converged` звалась 4621 раз на 2480 файлов.
#
# Все пять запоминаемых функций — чистые функции своих входов (ни одна не
# пишет в узлы дерева: проверено поиском присваиваний атрибутов в обоих
# модулях), поэтому ответ из памяти тождествен пересчёту ПО ПОСТРОЕНИЮ. Память
# живёт РОВНО один прогон `census()` (тот же порядок, что у
# `rule_second_copy_census._neighbour_query_memo`) и только для текущего
# файла: подмена двери оси МЕЖДУ прогонами (так устроены контроли соседних
# тестов) видна сразу, а вне `census()` функции работают как прежде, без
# памяти вовсе. Ключ — ТОЖДЕСТВО объекта дерева, и запись держит сам объект,
# поэтому `id()` не может быть переиспользован, пока запись жива.
#
# Выдача из памяти — КОПИЯ изменяемого контейнера (`module_sites` вычитает из
# словаря постоянных затенённые имена), а деревья отдаются как есть: их не
# пишет никто. Доказательство тождества — сверка полного ответа `census()` с
# памятью и без неё (`test_modular_constant_operand_run_memo.py`).
_RUN_MEMO: List[dict] = []


def _file_memo(source: Optional[str] = None) -> Optional[dict]:
    """Память текущего файла внутри прогона, либо ``None`` вне прогона.

    ``source`` переключает память на новый файл (прежний забывается — это
    граница потребления памяти, а не условие верности: ключи держат свои
    объекты и без неё).
    """
    if not _RUN_MEMO:
        return None
    run = _RUN_MEMO[-1]
    if source is not None and run.get("source") != source:
        run.clear()
        run["source"] = source
        run["entries"] = {}
        field_kind.node_memo.reset()     # узлы прежнего файла забываются там же
    return run.setdefault("entries", {})


def _remembered(fn):
    """Запоминает чистую функцию дерева на время текущего файла прогона."""
    import functools
    import inspect

    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(tree, *args, **kwargs):
        memo = _file_memo()
        if memo is None:
            return fn(tree, *args, **kwargs)
        # Умолчания подставляются в ключ: `f(t)` и `f(t, rounds=None)` — один
        # и тот же вопрос, и спрашивать его дважды значило бы платить дважды.
        bound = signature.bind(tree, *args, **kwargs)
        bound.apply_defaults()
        frozen = tuple(
            (name, tuple(sorted(value.items())) if isinstance(value, dict)
             else value)
            for name, value in bound.arguments.items() if name != "tree")
        key = (fn.__name__, id(tree), frozen)
        got = memo.get(key)
        if got is None:
            got = (tree, args, fn(tree, *args, **kwargs))
            memo[key] = got
        return _copy_out(got[2])

    return wrapper


def _copy_out(value):
    """Изменяемый контейнер отдаётся копией; деревья и кортежи — как есть."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, set):
        return set(value)
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return tuple(_copy_out(v) if isinstance(v, (dict, set, list)) else v
                     for v in value)
    return value


def _fresh_copy(tree: ast.Module) -> ast.Module:
    """Независимая копия дерева: ``copy.deepcopy`` либо НОВЫЙ разбор исходника.

    Внутри прогона, когда дерево — ровно то, что разобрала память текущего
    файла, копия получается повторным ``ast.parse`` того же исходника: разбор
    детерминирован и даёт те же узлы с теми же отметками положения, что и
    глубокая копия нетронутого дерева, а стоит на порядок дешевле (замер:
    24 мс копии против 0,5 мс разбора на файл). Вне прогона — прежний путь.
    """
    if _RUN_MEMO:
        run = _RUN_MEMO[-1]
        got = run.get("entries", {}).get("__parse__")
        if got is not None and got[0] == "tree" and got[1] is tree:
            return ast.parse(run["source"])
    return copy.deepcopy(tree)


def _with_run_memo(fn):
    """Ставит память одного прогона вокруг :func:`census`, не трогая тело.

    Возврат безусловен: память снимается и после исключения, иначе следующий
    прогон (или прямой зов ступени из теста) получил бы ответ о ЧУЖОМ файле.
    """
    import functools

    @functools.wraps(fn)
    def run_with_memo(*args, **kwargs):
        _RUN_MEMO.append({})
        try:
            # Память обходов оси (тела областей, перечень областей) живёт под
            # той же границей: один прогон, один файл.
            with field_kind.node_memo():
                return fn(*args, **kwargs)
        finally:
            _RUN_MEMO.pop()

    return run_with_memo


def _parse(source: str) -> ast.Module:
    """``ast.parse`` с памятью текущего файла прогона; отказ разбора — тоже."""
    memo = _file_memo(source)
    if memo is None:
        return ast.parse(source)
    got = memo.get("__parse__")
    if got is None:
        try:
            got = ("tree", ast.parse(source))
        except (SyntaxError, ValueError) as exc:
            got = ("error", exc)
        memo["__parse__"] = got
    if got[0] == "error":
        raise got[1]
    return got[1]

#: Населения у класса нет вовсе — ось расширять не на чем.
EMPTY = "EMPTY"

#: Население есть, но ни одно место не пишет поле-кандидат: заказ велел
#: «записать это и закрыть», а не расширять ось на всякий случай.
POPULATED_NO_CANDIDATE = "POPULATED_NO_CANDIDATE"

#: Население есть И хотя бы одно место пишет поле, о котором перепись спрашивает.
POPULATED_CANDIDATE_TOUCHED = "POPULATED_CANDIDATE_TOUCHED"

#: Не измерено. Никогда не выдаётся за «чисто» (инв. #17).
UNMEASURED = "UNMEASURED"

#: Каталоги дерева — ТЕ ЖЕ, что у оси. Своего списка здесь быть не может:
#: население класса обязано совпадать с населением, которое судит ось.
DEFAULT_ROOTS = field_kind.DEFAULT_ROOTS


@dataclasses.dataclass(frozen=True)
class Site:
    """Место, которое ось не видит сегодня и увидела бы при литерале."""

    module: str
    line: int
    field: str
    how: str
    consts: Tuple[str, ...]

    @property
    def transitive(self) -> bool:
        """В САМОМ выражении поля постоянной нет — значение пришло через имя."""
        return not self.consts

    def __str__(self) -> str:
        where = ",".join(self.consts) if self.consts else "через имя"
        return f"{self.module}:{self.line} {self.field} ← {self.how} [{where}]"


def _numeric_literal(node: Optional[ast.AST]) -> Optional[str]:
    """Литерал-число — или ``None``.

    ``bool`` исключён ТИПОМ, а не вычитанием из списка: ``True`` есть ``int``
    по наследству, и ``isinstance`` пропустил бы флаг в арифметику. Правило
    дословно то же, что у ``identity_field_kind._numeric_operand``, и это не
    дублирование: здесь оно отвечает на другой вопрос — «постоянная ли это
    привязка», а не «числовой ли это операнд».
    """
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return repr(node.value)
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd))
            and isinstance(node.operand, ast.Constant)
            and type(node.operand.value) in (int, float)):
        sign = "-" if isinstance(node.op, ast.USub) else ""
        return f"{sign}{node.operand.value!r}"
    return None


def _module_bindings(tree: ast.Module) -> Dict[str, List[Optional[ast.AST]]]:
    """Все привязки МОДУЛЬНОЙ области: имя → список привязанных выражений.

    ``None`` в списке означает привязку, выражения у которой нет или она не
    присваивание (``for``, ``with``, ``+=``, ``import``): такое имя постоянной
    быть не может, и отличить его от «связано числом» обязано ЗНАЧЕНИЕ, а не
    отсутствие строки.
    """
    out: Dict[str, List[Optional[ast.AST]]] = {}

    def add(names: Iterable[str], value: Optional[ast.AST]) -> None:
        for name in names:
            out.setdefault(name, []).append(value)

    for node in field_kind._own_body(tree):
        if isinstance(node, ast.Assign):
            names: Set[str] = set()
            for target in node.targets:
                names |= field_kind._targets(target)
            add(names, node.value)
        elif isinstance(node, ast.AnnAssign):
            add(field_kind._targets(node.target), node.value)
        elif isinstance(node, ast.AugAssign):
            add(field_kind._targets(node.target), None)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            add(field_kind._targets(node.target), None)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    add(field_kind._targets(item.optional_vars), None)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            add({node.name}, None)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            add({(a.asname or a.name).split(".")[0] for a in node.names}, None)
    return out


def globals_declared(tree: ast.Module) -> Set[str]:
    """Имена, объявленные ``global`` ХОТЬ ГДЕ в модуле: привязка ЗАПИСЫВАЕМА.

    Вторая односторонность прибора, заказом G697 п. 1 НЕ названная, и
    направление ошибки у неё ОБРАТНОЕ названному — в сторону находки.

    ``_shadowed`` оси перечисляет привязки НЕ присваиванием: параметры, циклы,
    ``with``, ``except``, импорт, включения. Присваивания там нет намеренно —
    для оси важна видимость имени в чужой области. Но ``global X`` с
    ``X = time.time()`` внутри функции имя не ЗАТЕНЯЕТ: он пере-связывает ТУ
    ЖЕ модульную привязку. Поэтому такое имя проходит и ``module_constants``
    (единственная модульная привязка — числовой литерал), и
    ``shadowed_anywhere`` (затенения нет), а подстановка его литералом неверна
    не в одной области, а ВЕЗДЕ, включая саму модульную.

    Признак механический и ложных срабатываний не имеет по построению:
    объявление ``global`` само и есть утверждение «эту модульную привязку
    пишут». Поэтому проверка живёт ЗДЕСЬ, а не рядом с
    :func:`shadowed_anywhere`: затенение — свойство ДРУГИХ областей, а
    записываемость — свойство ЭТОЙ привязки, и смешать их значило бы потерять
    разницу направлений промаха.
    """
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            out.update(node.names)
    return out


@_remembered
def module_constants(tree: ast.Module) -> Dict[str, str]:
    """Имя → литерал: модульные имена, связанные ТОЛЬКО числовыми литералами.

    «Только» — обязательное слово. Имя, пере-связанное хоть раз чем-то иным,
    числом по построению не является, и считать его таким значило бы мерить
    догадку. Затенение проверяется ОТДЕЛЬНО (:func:`shadowed_anywhere`): оно
    свойство других областей, а не этой привязки.

    Объявленное ``global`` имя отбрасывается ЗДЕСЬ (:func:`globals_declared`):
    записываемость модульной привязки есть свойство САМОЙ привязки, и
    постоянной такое имя не является ни в одной области.
    """
    writable = globals_declared(tree)
    out: Dict[str, str] = {}
    for name, values in _module_bindings(tree).items():
        if name in writable:
            continue
        literals = [_numeric_literal(v) for v in values]
        if literals and all(lit is not None for lit in literals):
            out[name] = str(literals[0])
    return out


@_remembered
def shadowed_anywhere(tree: ast.Module) -> Set[str]:
    """Имена, затенённые НЕ присваиванием хоть в одной области модуля.

    Такое имя подстановка пропускает целиком — не потому, что это точно не
    постоянная, а потому, что РАЗЛИЧИТЬ области здесь нельзя без второй копии
    правила видимости оси. Односторонность названа в модульной справке:
    население ЗАНИЖАЕТСЯ.
    """
    out: Set[str] = set()
    for scope_node in field_kind._scopes(tree):
        if scope_node is tree:
            continue
        out |= field_kind._shadowed(scope_node)
    return out


class _Substitute(ast.NodeTransformer):
    """Чтение постоянной → её литерал. Ничего, кроме чтений, не меняется."""

    def __init__(self, consts: Dict[str, str]) -> None:
        self.consts = consts
        self.done = 0

    def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802
        if not isinstance(node.ctx, ast.Load) or node.id not in self.consts:
            return node
        try:
            value = ast.literal_eval(self.consts[node.id])
        except (ValueError, SyntaxError):  # pragma: no cover - литерал наш
            return node
        self.done += 1
        return ast.copy_location(ast.Constant(value=value), node)


@_remembered
def substituted(tree: ast.Module, consts: Dict[str, str]
                ) -> Tuple[ast.Module, int]:
    """Копия дерева, где чтения постоянных стали литералами. Вторым — сколько.

    Отметки положения КОПИРУЮТСЯ у исходного узла (``copy_location``): номера
    строк в отчёте обязаны указывать на НАСТОЯЩИЙ файл, а не на разобранную
    копию (урок: «регион по номерам строк пуст на разобранной базе»).
    """
    clone = _fresh_copy(tree)
    sub = _Substitute(consts)
    clone = sub.visit(clone)
    ast.fix_missing_locations(clone)
    return clone, sub.done


def _axis_answers(tree: ast.Module, *, rounds: Optional[int] = None,
                  depth: int = 0) -> List[Tuple[str, int, str]]:
    """``(поле, строка, что ось сказала)`` для каждой площадки — НАСТОЯЩЕЙ осью.

    Прогон повторяет ровно то, что делает ``identity_field_kind.module_kinds``
    на своей третьей оси, и зовёт ЕГО функции: таблицу областей, обёртки,
    сильное и слабое прочтения. Правило здесь не живёт ни одной строкой —
    иначе прибор и ось разошлись бы молча. Верность повторения проверяется
    контролем (``test_the_today_answer_equals_the_axis_itself``).

    ``rounds`` и ``depth`` — ДВА предела самой оси, объявленные входами
    (заказ **G697 п. 3**). Умолчания дают ответ оси байт в байт, а подстановка
    в них и есть мера: при ``rounds=k`` видно, за сколько ШАГОВ ответ
    появляется, а при отрицательном ``depth`` — не прячет ли предел глубины
    площадку под словом «арифметики нет». Второго разбора ни одного правила
    здесь нет, подставляется сама дверь (тот же приём, что у ``drop_shadowed``
    в ADR-702).
    """
    return _axis_answers_converged(tree, rounds=rounds, depth=depth)[0]


@_remembered
def _axis_answers_converged(tree: ast.Module, *, rounds: Optional[int] = None,
                            depth: int = 0
                            ) -> Tuple[List[Tuple[str, int, str]], bool]:
    """Ответы оси И сходимость её петли — ОДНИМ проходом таблицы областей.

    Два вопроса сразу не ради краткости: таблица областей и есть вся цена
    прохода, и спрашивать её дважды (раз за ответами, раз за сходимостью)
    значило бы заплатить втрое за один и тот же разбор. Ответ площадок —
    первым значением, сходимость — вторым; смешать их нельзя, это разные
    утверждения (``False`` вторым означает «предел раундов исчерпан», а не
    «площадок нет»).
    """
    scopes, converged = field_kind.scope_table_steps(
        tree, field_kind.arith_derivation, field_kind.arith_wrappers(tree),
        rounds=rounds)
    out: List[Tuple[str, int, str]] = []
    for name, value, line, scope_node in field_kind.field_assignments(tree):
        scope = scopes.get(id(scope_node), scopes[id(tree)])
        how = field_kind.arith_derivation(value, scope, depth)
        if not how:
            how = field_kind.arith_formatted(value, scope, depth) or ""
        out.append((name, line, how))
    return out, converged


def _consts_in(value: ast.AST, consts: Dict[str, str]) -> Tuple[str, ...]:
    """Постоянные, прочитанные В САМОМ выражении площадки (без спуска в чужое)."""
    found: Set[str] = set()
    for node in ast.walk(value):
        if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                and node.id in consts):
            found.add(node.id)
    return tuple(sorted(found))


def module_sites(source: str, *, drop_shadowed: bool = True
                 ) -> Tuple[Optional[List[Site]], Dict[str, str], str]:
    """Площадки класса в ОДНОМ модуле. Вторым — постоянные, третьим — причина.

    ``(None, {}, причина)`` — третий исход: файл не разобран либо два прогона
    дали РАЗНЫЙ состав площадок. Второе означает, что подстановка задела
    структуру, а не только операнд; спарить тогда «что было» и «что стало»
    нельзя, и молчаливое спаривание не тех мест было бы хуже отказа.

    ``drop_shadowed=False`` — ЕДИНСТВЕННАЯ дверь, которую подменяет мера цены
    односторонности (:func:`module_shadow_cost`, заказ G697 п. 1). Это не
    режим работы и не ослабление: с закрытым выбросом ответ есть ВЕРХНЯЯ
    граница класса (подстановка в затенённой области заведомо неверна),
    тогда как ответ по умолчанию — НИЖНЯЯ. Цена односторонности и есть
    расстояние между ними, и мерить его обязана подстановка в САМ прибор, а
    не второй разбор правила видимости (урок #820: второй поиск предмета,
    уже раскрытого соседом, РАСХОДИТСЯ).
    """
    try:
        tree = _parse(source)
    except (SyntaxError, ValueError) as exc:
        return None, {}, f"не разобрано: {type(exc).__name__}"
    consts = module_constants(tree)
    if drop_shadowed:
        for name in shadowed_anywhere(tree):
            consts.pop(name, None)
    if not consts:
        return [], {}, ""
    clone, _ = substituted(tree, consts)
    before = _axis_answers(tree)
    after = _axis_answers(clone)
    if len(before) != len(after) or [(n, l) for n, l, _ in before] != [
            (n, l) for n, l, _ in after]:
        return None, consts, ("состав площадок разошёлся между прогонами: "
                              f"{len(before)} против {len(after)}")
    by_line: Dict[Tuple[str, int], ast.AST] = {}
    for name, value, line, _scope in field_kind.field_assignments(tree):
        by_line.setdefault((name, line), value)
    sites: List[Site] = []
    for (name, line, was), (_n, _l, now) in zip(before, after):
        if was or not now:
            continue
        value = by_line.get((name, line))
        sites.append(Site(module="", line=line, field=name, how=now,
                          consts=_consts_in(value, consts) if value is not None
                          else ()))
    return sites, consts, ""


@dataclasses.dataclass(frozen=True)
class ShadowCost:
    """Цена односторонности В ОДНОМ модуле — заказ G697 п. 1.

    Две величины РАЗВЕДЕНЫ, и это не украшение: выброшенная постоянная и
    потерянная площадка — разные ответы, и ноль у второй не отменяет
    ненулевой первой (урок ADR-700 п. 3). Заказ спросил ровно их обе:
    «сколько постоянных выброшено затенением и у скольких модулей от этого
    исчезает хотя бы одна площадка».
    """

    module: str
    #: Постоянные, которые выброс затенения убрал из операнда.
    dropped: Tuple[str, ...]
    #: Площадки, которые от этого выброса НЕ попали в население («поле:строка»).
    lost: Tuple[str, ...]
    #: Третий исход: разобрать или спарить не вышло. Никогда не «цены нет».
    reason: str


def module_shadow_cost(source: str) -> ShadowCost:
    """Цена выброса затенённых имён в ОДНОМ модуле — подстановкой в сам прибор.

    Второй прогон делается ТОЛЬКО там, где дверь выброса сработала. Это не
    приближение и не экономия на замере: при пустом ``dropped`` оба прогона
    получают БАЙТ В БАЙТ один и тот же ``consts`` (единственная разница ветки
    — что из него вычесть), поэтому их ответы тождественны ПО ПОСТРОЕНИЮ.
    Тождество закреплено контролем (сцена, где дверь не сработала, обязана
    давать равные ответы обоими способами) — иначе сокращение держалось бы на
    рассуждении, а не на тесте.
    """
    try:
        tree = _parse(source)
    except (SyntaxError, ValueError) as exc:
        return ShadowCost("", (), (), f"не разобрано: {type(exc).__name__}")
    dropped = tuple(sorted(set(module_constants(tree)) & shadowed_anywhere(tree)))
    if not dropped:
        return ShadowCost("", (), (), "")
    tight, _c, why_tight = module_sites(source)
    loose, _c2, why_loose = module_sites(source, drop_shadowed=False)
    if tight is None or loose is None:
        return ShadowCost("", dropped, (),
                          why_tight or why_loose
                          or "спарить прогоны не вышло")
    seen = {(s.field, s.line) for s in tight}
    lost = tuple(f"{s.field}:{s.line}" for s in loose
                 if (s.field, s.line) not in seen)
    return ShadowCost("", dropped, lost, "")


@dataclasses.dataclass(frozen=True)
class ChainRow:
    """Сколько ШАГОВ лежит между постоянной и полем — заказ G697 п. 3.

    ``steps`` — РАУНДЫ распространения, за которые ось начинает отвечать об
    этой площадке, и мерены они подстановкой в саму дверь оси (``rounds=k``),
    а не вторым разбором цепочки. Один раунд петли добавляет ровно один шаг по
    имени: снимок привязок берётся ПЕРЕД обходом тела, поэтому порядок строк
    в модуле на счёт не влияет.

    ``steps == 0`` — не «шагов нет», а шаг НЕ ПО ИМЕНИ: ответ пришёл через
    обёртку (``_effective_apy()``), чьи привязки ось ищет своей петлёй
    (``_wrappers``, предел ``len(funcs) + 1`` — исчерпать его нельзя по
    построению, функций в модуле меньше). Различать эти два случая обязательно:
    иначе «через имя» и «через обёртку» слились бы в одно число, а цепочку
    удлиняет только первое.

    ``steps is None`` — третий исход с НАЗВАННОЙ причиной. Никогда не ноль.
    """

    module: str
    line: int
    field: str
    how: str
    steps: Optional[int]
    reason: str

    def __str__(self) -> str:
        where = "НЕ ИЗМЕРЕНО" if self.steps is None else f"шагов {self.steps}"
        tail = f" ({self.reason})" if self.reason else ""
        return f"{self.module}:{self.line} {self.field} ← {self.how} [{where}]{tail}"


def module_chain(source: str, sites: Sequence[Site]) -> Tuple[List[ChainRow], str]:
    """Длина цепочки для КАЖДОЙ транзитивной площадки модуля. Вторым — причина.

    Площадки приходят ВХОДОМ, а не считаются заново: их уже посчитал
    :func:`module_sites`, и второй счёт того же предмета расходился бы молча
    (урок #820). Прибор добавляет к ним ровно одно — расстояние.

    Мера: предел раундов оси ставится ``k = 0, 1, 2 …`` и спрашивается, при
    каком ``k`` ответ об этой площадке ПОЯВЛЯЕТСЯ. Это и есть длина кратчайшей
    цепочки от постоянной (ставшей литералом) до поля. Больше
    :data:`field_kind.DERIVE_ROUNDS` шагов ось не делает вовсе, поэтому
    «ответа нет и при полном пределе» есть третий исход, а не длина.
    """
    try:
        tree = _parse(source)
    except (SyntaxError, ValueError) as exc:
        return [], f"не разобрано: {type(exc).__name__}"
    wanted = [s for s in sites if s.transitive]
    if not wanted:
        return [], ""
    consts = module_constants(tree)
    for name in shadowed_anywhere(tree):
        consts.pop(name, None)
    if not consts:
        return [], "постоянных нет — транзитивной площадки быть не может"
    clone, _done = substituted(tree, consts)
    steps: Dict[Tuple[str, int], int] = {}
    for k in range(field_kind.DERIVE_ROUNDS + 1):
        answers = {(n, l): how for n, l, how in _axis_answers(clone, rounds=k)}
        for site in wanted:
            key = (site.field, site.line)
            if key not in steps and answers.get(key):
                steps[key] = k
        if len(steps) == len(wanted):
            break
    rows = [ChainRow(module="", line=s.line, field=s.field, how=s.how,
                     steps=steps.get((s.field, s.line)),
                     reason="" if (s.field, s.line) in steps else
                     (f"ответ не появился и при полном пределе "
                      f"{field_kind.DERIVE_ROUNDS} раунд(ов)"))
            for s in wanted]
    return rows, ""


#: Запас, с которым прибор спрашивает у оси «а если бы предела глубины не
#: было». Отрицательная НАЧАЛЬНАЯ глубина — это и есть подстановка в саму
#: дверь: условие оси ``depth > DEPTH_LIMIT`` при старте с ``-N`` пропускает
#: ``DEPTH_LIMIT + N`` уровней вместо ``DEPTH_LIMIT``. Множитель взят с запасом
#: к самому глубокому выражению дерева, а не «на всякий случай»: глубина
#: выражения МЕРИТСЯ рядом (:func:`deepest_value`), и запас обязан её
#: перекрывать.
_DEPTH_HEADROOM = -8 * field_kind.DEPTH_LIMIT


@dataclasses.dataclass(frozen=True)
class LimitCost:
    """Цена ДВУХ пределов самой оси — заказ G697 п. 3.

    Предел, в который обход упёрся, возвращает ``None``, то есть говорит
    «арифметики нет» там, где верный ответ — «НЕ ИЗМЕРЕНО» (инв. #17). Пока
    цены нет, оба предела молчат одинаково, и население класса есть нижняя
    граница неизвестной глубины — ровно та болезнь, которую ADR-702 вылечил у
    двери затенения.

    Две двери РАЗВЕДЕНЫ, как разведены там выброшенная постоянная и потерянная
    площадка: глубина спуска в ОДНОМ выражении и длина цепочки МЕЖДУ именами —
    разные вопросы, и ноль у одной не говорит ничего о другой.
    """

    module: str
    #: Самое глубокое выражение-значение модуля (ВЕРХНЯЯ оценка глубины обхода).
    deepest_value: int
    #: Где оно: ``строка``. Называется, чтобы запас можно было перепроверить.
    deepest_line: int
    #: Дверь глубины сработала: выражение глубже предела оси ЕСТЬ.
    depth_door: bool
    #: Площадки, которые видно ТОЛЬКО с запасом по глубине («поле:строка»).
    depth_hidden: Tuple[str, ...]
    #: Дверь раундов сработала: петля хоть одной области НЕ сошлась за предел.
    rounds_door: bool
    #: Площадки, которые видно ТОЛЬКО при бо́льшем пределе раундов.
    rounds_hidden: Tuple[str, ...]
    #: Третий исход. Никогда не «цены нет».
    reason: str


def deepest_value(tree: ast.Module) -> Tuple[int, int]:
    """Самое глубокое выражение-ЗНАЧЕНИЕ модуля: ``(глубина, строка)``.

    Это ВЕРХНЯЯ оценка глубины, на которую может спуститься обход оси: счётчик
    ``depth`` растёт ровно на один уровень вложенности узла, а в контейнеры и
    в условие развилки ось не ходит вовсе. Поэтому запас «предел минус эта
    глубина» больше нуля ДОКАЗЫВАЕТ, что предел глубины сегодня связать
    ничего не может, — и доказывает структурой дерева, а не выборкой.

    Спрашиваются ровно те выражения, о которых ось судит: значения привязок
    (операнд петли распространения) и значения названных полей.
    """

    def depth_of(node: ast.AST) -> int:
        best = 1
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.expr, ast.comprehension)):
                best = max(best, 1 + depth_of(child))
        return best

    best, line = 0, 0
    for node in ast.walk(tree):
        if (isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
                and getattr(node, "value", None) is not None):
            got = depth_of(node.value)
            if got > best:
                best, line = got, getattr(node, "lineno", 0)
    for _name, value, line_no, _scope in field_kind.field_assignments(tree):
        got = depth_of(value)
        if got > best:
            best, line = got, line_no
    return best, line


def _round_ceiling(tree: ast.Module) -> int:
    """Предел раундов, исчерпать который НЕЛЬЗЯ: привязок в модуле плюс один.

    Каждый раунд петли добавляет хотя бы одно имя, иначе петля кончается
    неподвижной точкой. Значит раундов не может потребоваться больше, чем в
    модуле привязок. Тот же приём, которым ``_wrappers`` берёт
    ``len(funcs) + 1``: это не «побольше на всякий случай», а потолок по
    построению.
    """
    return 1 + sum(1 for node in ast.walk(tree)
                   if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)))


def axis_limit_cost(source: str) -> LimitCost:
    """Цена двух пределов оси В ОДНОМ модуле — подстановкой в сами двери.

    Второй прогон делается ТОЛЬКО там, где соответствующая дверь СРАБОТАЛА, и
    это не экономия на замере, а доказанное тождество — то же правило, по
    которому ADR-702 сократил второй прогон цены затенения:

    * выражений глубже предела в модуле нет ⇒ счётчик ``depth`` не может
      дойти до предела ни на одной площадке, и ответы с запасом и без
      совпадают ПО ПОСТРОЕНИЮ;
    * петля сошлась неподвижной точкой ⇒ бо́льший предел раундов добавить
      нечему, и ответы совпадают ПО ПОСТРОЕНИЮ.

    Оба тождества закреплены контролем, а не рассуждением.
    """
    try:
        tree = _parse(source)
    except (SyntaxError, ValueError) as exc:
        return LimitCost("", 0, 0, False, (), False, (),
                         f"не разобрано: {type(exc).__name__}")
    depth, line = deepest_value(tree)
    consts = module_constants(tree)
    for name in shadowed_anywhere(tree):
        consts.pop(name, None)
    operand = tree
    if consts:
        operand, _done = substituted(tree, consts)
    rows, converged = _axis_answers_converged(operand)
    base = {(n, l): how for n, l, how in rows}
    depth_door = depth > field_kind.DEPTH_LIMIT
    rounds_door = not converged
    depth_hidden: List[str] = []
    rounds_hidden: List[str] = []
    if depth_door and depth > field_kind.DEPTH_LIMIT - _DEPTH_HEADROOM:
        # Запас КОНЕЧЕН, и выдать его нехватку за «спрятанных площадок столько»
        # значило бы повторить ровно тот дефект, который прибор и мерит:
        # недостающий запас молчит так же, как достигнутый предел (инв. #17).
        return LimitCost("", depth, line, depth_door, (), rounds_door, (),
                         f"запаса по глубине не хватает: выражение {depth} при "
                         f"запасе {field_kind.DEPTH_LIMIT - _DEPTH_HEADROOM}")
    for door, kind, bucket in ((depth_door, "depth", depth_hidden),
                               (rounds_door, "rounds", rounds_hidden)):
        if not door:
            continue
        loose = (_axis_answers(operand, depth=_DEPTH_HEADROOM) if kind == "depth"
                 else _axis_answers(operand, rounds=_round_ceiling(operand)))
        if len(loose) != len(base):
            return LimitCost("", depth, line, depth_door, (), rounds_door, (),
                             "состав площадок разошёлся между прогонами: "
                             f"{len(base)} против {len(loose)}")
        for name, line_no, how in loose:
            if how and not base.get((name, line_no)):
                bucket.append(f"{name}:{line_no}")
    return LimitCost("", depth, line, depth_door, tuple(depth_hidden),
                     rounds_door, tuple(rounds_hidden), "")


@_with_run_memo
def census(tree_root: Path,
           roots: Sequence[str] = DEFAULT_ROOTS) -> dict:
    """Население класса по всему дереву. Тесты исключены — как у оси."""
    sites: List[Site] = []
    unmeasured: Dict[str, str] = {}
    costs: List[ShadowCost] = []
    cost_unmeasured: Dict[str, str] = {}
    chain: List[ChainRow] = []
    chain_unmeasured: Dict[str, str] = {}
    limits: List[LimitCost] = []
    limit_unmeasured: Dict[str, str] = {}
    limits_outside = 0
    modules_with_consts = 0
    constants_seen = 0
    files_parsed = 0
    for root in roots:
        base = Path(tree_root) / root
        if not base.is_dir():
            unmeasured[root] = "каталога нет в дереве"
            continue
        for path in sorted(base.rglob("*.py")):
            rel = str(path.relative_to(tree_root))
            if "/tests/" in f"/{rel}" or path.name.startswith("test_"):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError as exc:
                unmeasured[rel] = f"не прочитано: {type(exc).__name__}"
                continue
            found, consts, why = module_sites(source)
            if found is None:
                unmeasured[rel] = why
                continue
            files_parsed += 1
            if consts:
                modules_with_consts += 1
                constants_seen += len(consts)
            sites.extend(dataclasses.replace(s, module=rel) for s in found)
            # Заказ G697 п. 1 — цена СВОЕЙ односторонности, замером. Считается
            # в том же проходе: отдельный проход по дереву был бы вторым
            # прочтением тех же файлов, а разойтись им не дало бы ничто.
            cost = module_shadow_cost(source)
            if cost.reason:
                cost_unmeasured[rel] = cost.reason
            elif cost.dropped:
                costs.append(dataclasses.replace(cost, module=rel))
            # Заказ G697 п. 3 — ДЛИНА цепочки у транзитивных площадок. Счёт
            # идёт только там, где такая площадка есть: у модуля без неё
            # измерять нечего, и прогон ради ноля был бы платой за тишину.
            if any(s.transitive for s in found):
                rows, why_chain = module_chain(source, found)
                if why_chain:
                    chain_unmeasured[rel] = why_chain
                else:
                    chain.extend(dataclasses.replace(r, module=rel)
                                 for r in rows)
            # Заказ G697 п. 3 — цена ДВУХ пределов самой оси. Дверь
            # спрашивается у модуля с постоянными и НЕ спрашивается у модуля
            # без них, и это ВЫБОР с причиной, а не свойство дерева: класс
            # живёт только там, где постоянная есть, а прогон стои́т таблицу
            # областей (цена названа числом в ADR). Исключённые модули
            # посчитаны отдельной строкой — «не спрашивали» и «спросили и
            # ноль» обязаны быть различимы (инв. #17).
            if consts:
                limit = axis_limit_cost(source)
                if limit.reason:
                    limit_unmeasured[rel] = limit.reason
                else:
                    limits.append(dataclasses.replace(limit, module=rel))
            else:
                limits_outside += 1
    doc = {
        "schema": SCHEMA,
        "files_parsed": files_parsed,
        "files_unmeasured": unmeasured,
        "modules_with_constants": modules_with_consts,
        "constants_seen": constants_seen,
        "sites": [dataclasses.asdict(s) for s in sites],
        "population": len(sites),
        "direct": sum(1 for s in sites if not s.transitive),
        "transitive": sum(1 for s in sites if s.transitive),
        # Заказ G697 п. 1. Две величины РАЗВЕДЕНЫ: выброшенная постоянная
        # (операнд) и потерянная площадка (ответ). Ноль у второй не отменяет
        # ненулевой первой, и слить их в одно число значило бы потерять ровно
        # тот вопрос, который заказ задал двумя половинами.
        "shadow_cost": {
            "dropped_constants": sum(len(c.dropped) for c in costs),
            "dropped_modules": len(costs),
            "lost_sites": sum(len(c.lost) for c in costs),
            "lost_modules": sum(1 for c in costs if c.lost),
            "dropped_named": [f"{c.module}:{n}"
                              for c in costs for n in c.dropped],
            "lost_named": [f"{c.module}:{n}" for c in costs for n in c.lost],
            "unmeasured": cost_unmeasured,
        },
        # Заказ G697 п. 3. Шаги печатаются РАСКЛАДОМ, а не средним: заказ
        # спросил «сколько шагов в КАЖДОМ случае», и среднее на этот вопрос
        # не отвечает. `without_name_hop` отделён нарочно — шаг через обёртку
        # цепочку по именам не удлиняет (см. :class:`ChainRow`).
        "chain": {
            "rows": [dataclasses.asdict(r) for r in chain],
            "steps_histogram": _histogram(chain),
            "max_steps": max([r.steps for r in chain if r.steps is not None],
                             default=None),
            "without_name_hop": sum(1 for r in chain if r.steps == 0),
            "steps_unmeasured": sum(1 for r in chain if r.steps is None),
            "unmeasured": chain_unmeasured,
        },
        # Заказ G697 п. 3. Два предела оси и запас до каждого. Двери РАЗВЕДЕНЫ:
        # глубина спуска в одном выражении и длина цепочки между именами —
        # разные вопросы, и ноль у одной ничего не говорит о другой.
        "axis_limits": _limit_summary(limits, limit_unmeasured, chain,
                                      outside=limits_outside),
    }
    if not files_parsed:
        doc["status"] = UNMEASURED
        doc["reason"] = ("ни один файл дерева не разобран — ноль мест читался "
                         "бы как ответ")
    return doc


def _histogram(rows: Sequence[ChainRow]) -> Dict[str, int]:
    """Расклад шагов: ``«шагов» → сколько площадок``. Третий исход — отдельно."""
    out: Dict[str, int] = {}
    for row in rows:
        if row.steps is None:
            continue
        out[str(row.steps)] = out.get(str(row.steps), 0) + 1
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def _limit_summary(limits: Sequence[LimitCost], unmeasured: Dict[str, str],
                   chain: Sequence[ChainRow], *, outside: int) -> dict:
    """Свод цены двух пределов оси. Запас — число, а не слово «хватает».

    Запас по ГЛУБИНЕ есть ``предел − самое глубокое выражение дерева``: пока
    он положителен, предел глубины не может связать НИ ОДНОЙ площадки, и это
    свойство структуры дерева, а не выборки. Запас по РАУНДАМ есть
    ``предел − самая длинная измеренная цепочка``: он говорит лишь о том, что
    измерено сегодня, и обязан читаться слабее первого.
    """
    deepest = max((c.deepest_value for c in limits), default=0)
    at = next((f"{c.module}:{c.deepest_line}" for c in limits
               if c.deepest_value == deepest), "")
    longest = max([r.steps for r in chain if r.steps is not None], default=None)
    return {
        "depth_limit": field_kind.DEPTH_LIMIT,
        "deepest_value_expression": deepest or None,
        "deepest_named": at,
        "depth_margin": (None if not deepest
                         else field_kind.DEPTH_LIMIT - deepest),
        "depth_doors_fired": sum(1 for c in limits if c.depth_door),
        "depth_hidden_sites": sum(len(c.depth_hidden) for c in limits),
        "depth_hidden_named": [f"{c.module}:{s}" for c in limits
                               for s in c.depth_hidden],
        "rounds_limit": field_kind.DERIVE_ROUNDS,
        "longest_chain": longest,
        "rounds_margin": (None if longest is None
                          else field_kind.DERIVE_ROUNDS - longest),
        "rounds_doors_fired": sum(1 for c in limits if c.rounds_door),
        "rounds_hidden_sites": sum(len(c.rounds_hidden) for c in limits),
        "rounds_hidden_named": [f"{c.module}:{s}" for c in limits
                                for s in c.rounds_hidden],
        "modules_measured": len(limits),
        # «Не спрашивали» — своё число, а не ноль в графе «сработало»: модуль
        # без постоянных операнда класса не несёт, и дверь у него не задавалась.
        "modules_outside_the_operand": outside,
        "unmeasured": unmeasured,
    }


def tally(candidate_fields: Optional[Dict[str, int]],
          identity_fields: Optional[Sequence[str]],
          tree_root: Optional[Path]) -> dict:
    """Свод: население класса и ЗАДЕТО ли им хоть одно поле-кандидат.

    ``tree_root=None`` ⇒ ``UNMEASURED`` с причиной: население есть утверждение
    о КОДЕ, и выдумать его нельзя. ``candidate_fields=None`` ⇒ пересечение
    остаётся ``None``, а не нулём: «перечня не дали» и «ни одного не задето» —
    разные ответы (инв. #17).
    """
    if tree_root is None:
        return {
            "schema": SCHEMA,
            "status": UNMEASURED,
            "reason": "дерева не дали — население класса есть утверждение о КОДЕ",
            "population": None,
            "candidate_hits": None,
            "identity_hits": None,
            "what_it_does_not_prove": _not_proven(),
        }
    doc = census(Path(tree_root))
    if doc.get("status") == UNMEASURED:
        doc.update({"candidate_hits": None, "identity_hits": None,
                    "what_it_does_not_prove": _not_proven(doc)})
        return doc
    sites = [Site(**s) for s in doc["sites"]]
    cand = set(candidate_fields or {}) if candidate_fields is not None else None
    ident = set(identity_fields or ()) if identity_fields is not None else None
    cand_rows = (None if cand is None
                 else [str(s) for s in sites if s.field in cand])
    ident_rows = (None if ident is None
                  else [str(s) for s in sites if s.field in ident])
    doc["candidate_hits"] = None if cand_rows is None else len(cand_rows)
    doc["candidate_sites"] = cand_rows
    doc["identity_hits"] = None if ident_rows is None else len(ident_rows)
    doc["identity_sites"] = ident_rows
    doc["candidate_denominator"] = None if cand is None else len(cand)
    if not sites:
        doc["status"] = EMPTY
        doc["reason"] = ("мест вида «постоянная ⊕ значение», которых ось не "
                         "видит, в дереве нет — расширять ось не на чем")
    elif cand_rows or ident_rows:
        doc["status"] = POPULATED_CANDIDATE_TOUCHED
        doc["reason"] = (
            f"население класса {len(sites)}; из них пишут поле-кандидат "
            f"{len(cand_rows or [])}, поле из _IDENTITY_FIELDS "
            f"{len(ident_rows or [])}")
    else:
        doc["status"] = POPULATED_NO_CANDIDATE
        doc["reason"] = (
            f"население класса {len(sites)}, но ни одно место не пишет поле, "
            "о котором перепись спрашивает — заказ велел записать и закрыть")
    doc["what_it_does_not_prove"] = _not_proven(doc)
    return doc


def _cost_clause(doc: Optional[dict]) -> str:
    """Оговорка про занижение — ЧИСЛОМ, когда число есть (заказ G697 п. 1).

    До ADR-702 здесь стояла проза «население ЗАНИЖЕНО», и она была верна в
    обе стороны сразу: «33» могло быть и точным ответом, и нижней границей,
    далёкой от правды. Теперь направление промаха названо ВМЕСТЕ с его
    величиной, а когда цену измерить не вышло — это третий исход, а не
    возврат к прозе (инв. #17).
    """
    cost = (doc or {}).get("shadow_cost")
    head = ("затенённое хоть в одной области имя не подставляется ВОВСЕ — "
            "промах в сторону «чисто», население ЗАНИЖЕНО")
    if not isinstance(cost, dict):
        return (f"{head}; ВЕЛИЧИНА промаха НЕ ИЗМЕРЕНА (раздела "
                "`shadow_cost` у документа нет — отчёт старого образца)")
    if cost.get("unmeasured"):
        return (f"{head}; величина промаха измерена ЧАСТИЧНО: "
                f"{len(cost['unmeasured'])} модул(ей) в третьем исходе")
    return (f"{head} — но ВЕЛИЧИНА промаха ИЗМЕРЕНА и она "
            f"{cost.get('dropped_constants')} постоянн(ых) в "
            f"{cost.get('dropped_modules')} модул(ях), от которых теряется "
            f"{cost.get('lost_sites')} площад(ок) в {cost.get('lost_modules')} "
            "модул(ях): население есть нижняя граница, и расстояние до верхней "
            "названо числом, а не оговоркой")


def _not_proven(doc: Optional[dict] = None) -> List[str]:
    """Чего прибор НЕ доказывает. Цена односторонности — числом, не прозой."""
    return [
        "население НЕ есть правило: ось не расширена ни на одно имя, и «род ⇒ "
        "годность» остаётся отвергнутым замером (ADR-539/503)",
        _cost_clause(doc),
        "имя, объявленное `global`, постоянной не считается ВОВСЕ: `global X` "
        "не ЗАТЕНЯЕТ имя, а пере-связывает ТУ ЖЕ модульную привязку, и промах "
        "здесь был бы в сторону НАХОДКИ (ложное обвинение) — вторая "
        "односторонность, заказом G697 п. 1 не названная",
        "постоянная функции постоянной здесь не считается: заказ назвал класс "
        "МОДУЛЬНЫМ",
        _chain_clause(doc),
        _limit_clause(doc),
        "«поле-кандидат задето» говорит о МЕСТЕ в коде, а не о годности поля в "
        "личность — годность меряет перепись, и правила от этого числа у неё нет",
    ]


def _chain_clause(doc: Optional[dict] = None) -> str:
    """Что говорит РАСКЛАД шагов — и чего он не говорит (заказ G697 п. 3)."""
    chain = (doc or {}).get("chain")
    if not isinstance(chain, dict):
        return ("длина цепочки «постоянная → поле» НЕ ИЗМЕРЕНА (раздела "
                "`chain` у документа нет — отчёт старого образца)")
    return (f"расклад шагов говорит о КРАТЧАЙШЕЙ цепочке, которой хватает оси: "
            f"самая длинная измеренная — {chain.get('max_steps')} шаг(ов), и "
            "это не «других путей к полю нет», а «столько раундов ось делает, "
            "прежде чем ответить»")


def _limit_clause(doc: Optional[dict] = None) -> str:
    """Цена двух пределов оси — числами и с НАЗВАННОЙ разницей силы."""
    lim = (doc or {}).get("axis_limits")
    if not isinstance(lim, dict):
        return ("цена пределов самой оси НЕ ИЗМЕРЕНА (раздела `axis_limits` у "
                "документа нет — отчёт старого образца)")
    if lim.get("unmeasured"):
        return ("цена пределов оси измерена ЧАСТИЧНО: "
                f"{len(lim['unmeasured'])} модул(ей) в третьем исходе")
    return (
        f"предел ГЛУБИНЫ ({lim.get('depth_limit')}) связать сегодня ничего не "
        f"может по СТРУКТУРЕ дерева — самое глубокое выражение-значение "
        f"{lim.get('deepest_value_expression')} ({lim.get('deepest_named')}), "
        f"запас {lim.get('depth_margin')}; предел РАУНДОВ "
        f"({lim.get('rounds_limit')}) не упёрся ни в одной области "
        f"({lim.get('rounds_doors_fired')} дверей сработало), и это утверждение "
        "СЛАБЕЕ первого: оно про измеренные цепочки, а не про структуру")


def cost_report(doc: dict, *, max_rows: int = 6) -> List[str]:
    """Строки ЦЕНЫ односторонности. Третий исход — вслух, не «цены нет»."""
    cost = doc.get("shadow_cost")
    if not isinstance(cost, dict):
        return ["  ЦЕНА односторонности: НЕ ИЗМЕРЕНА — раздела `shadow_cost` "
                "у документа нет вовсе (отчёт СТАРОГО ОБРАЗЦА, а не «цены "
                "нет»)"]
    out = [
        f"  ЦЕНА односторонности ИЗМЕРЕНА: затенением выброшено "
        f"{cost.get('dropped_constants')} постоянн(ых) из "
        f"{doc.get('constants_seen')} в {cost.get('dropped_modules')} "
        f"модул(ях) · площадок от этого теряется {cost.get('lost_sites')} "
        f"в {cost.get('lost_modules')} модул(ях) ⇒ население "
        f"{doc.get('population')} есть НИЖНЯЯ граница, и расстояние до "
        "верхней названо"]
    for name in (cost.get("dropped_named") or [])[:max_rows]:
        out.append(f"    выброшено · {name}")
    extra = len(cost.get("dropped_named") or []) - max_rows
    if extra > 0:
        out.append(f"    … ещё {extra} выброшенн(ых)")
    for name in (cost.get("lost_named") or [])[:max_rows]:
        out.append(f"    потеряна площадка · {name}")
    for rel, why in (cost.get("unmeasured") or {}).items():
        out.append(f"    [ЦЕНА НЕ ИЗМЕРЕНА] {rel}: {why}")
    return out


def chain_report(doc: dict, *, max_rows: int = 6) -> List[str]:
    """Строки РАСКЛАДА шагов. Третий исход — вслух, не «шагов нет»."""
    chain = doc.get("chain")
    if not isinstance(chain, dict):
        return ["  ШАГИ до поля: НЕ ИЗМЕРЕНЫ — раздела `chain` у документа нет "
                "вовсе (отчёт СТАРОГО ОБРАЗЦА, а не «цепочек нет»)"]
    hist = chain.get("steps_histogram") or {}
    rows = chain.get("rows") or []
    if not rows:
        return ["  ШАГИ до поля: транзитивных площадок нет — мерить нечего "
                "(измерено и равно нулю, а не «не измерено»)"]
    spread = " · ".join(f"{k} шаг(ов) у {v}" for k, v in hist.items())
    out = [f"  ШАГИ до поля ИЗМЕРЕНЫ у {len(rows)} транзитивн(ых): {spread}"
           f" · самая длинная {chain.get('max_steps')} · без шага ПО ИМЕНИ "
           f"(через обёртку) {chain.get('without_name_hop')} · НЕ ИЗМЕРЕНО "
           f"{chain.get('steps_unmeasured')}"]
    for row in rows[:max_rows]:
        out.append(f"    шаги · {ChainRow(**row)}")
    extra = len(rows) - max_rows
    if extra > 0:
        out.append(f"    … ещё {extra} цепочк(и)")
    for rel, why in (chain.get("unmeasured") or {}).items():
        out.append(f"    [ШАГИ НЕ ИЗМЕРЕНЫ] {rel}: {why}")
    return out


def limit_report(doc: dict, *, max_rows: int = 6) -> List[str]:
    """Строки цены ДВУХ пределов оси. Запас — число, а не слово «хватает»."""
    lim = doc.get("axis_limits")
    if not isinstance(lim, dict):
        return ["  ПРЕДЕЛЫ оси: цена НЕ ИЗМЕРЕНА — раздела `axis_limits` у "
                "документа нет вовсе (отчёт СТАРОГО ОБРАЗЦА, а не «пределы не "
                "жмут»)"]
    out = [
        f"  ПРЕДЕЛ ГЛУБИНЫ {lim.get('depth_limit')}: самое глубокое "
        f"выражение-значение {lim.get('deepest_value_expression')} "
        f"({lim.get('deepest_named')}) ⇒ запас {lim.get('depth_margin')} · "
        f"дверей сработало {lim.get('depth_doors_fired')} · площадок спрятано "
        f"{lim.get('depth_hidden_sites')}",
        f"  ПРЕДЕЛ РАУНДОВ {lim.get('rounds_limit')}: самая длинная измеренная "
        f"цепочка {lim.get('longest_chain')} ⇒ запас {lim.get('rounds_margin')} "
        f"· дверей сработало {lim.get('rounds_doors_fired')} · площадок "
        f"спрятано {lim.get('rounds_hidden_sites')} · модулей измерено "
        f"{lim.get('modules_measured')}"]
    for name in (lim.get("depth_hidden_named") or [])[:max_rows]:
        out.append(f"    спрятано ГЛУБИНОЙ · {name}")
    for name in (lim.get("rounds_hidden_named") or [])[:max_rows]:
        out.append(f"    спрятано РАУНДАМИ · {name}")
    for rel, why in (lim.get("unmeasured") or {}).items():
        out.append(f"    [ПРЕДЕЛЫ НЕ ИЗМЕРЕНЫ] {rel}: {why}")
    return out


def report(doc: dict, *, max_rows: int = 8) -> List[str]:
    """Строки отчёта. Знаменатель рядом с числителем, третий исход — вслух."""
    status = doc.get("status")
    if status == UNMEASURED:
        return [f"НЕ ИЗМЕРЕНО: {doc.get('reason')}"]
    out = [str(doc.get("reason"))]
    out.append(
        f"  население {doc.get('population')} "
        f"(в самом выражении {doc.get('direct')} · через имя "
        f"{doc.get('transitive')}) · модулей с постоянными "
        f"{doc.get('modules_with_constants')} · постоянных "
        f"{doc.get('constants_seen')} · файлов разобрано "
        f"{doc.get('files_parsed')}")
    # Заказ G697 п. 1: цена односторонности печатается ТАМ, ГДЕ ПЕЧАТАЕТСЯ
    # НАСЕЛЕНИЕ — строкой ниже самого числа. Оговорка в модульной справке
    # читателя отчёта не достаёт, а именно он решает, точный перед ним ответ
    # или нижняя граница.
    out.extend(cost_report(doc))
    # Заказ G697 п. 3: шаги и ПРЕДЕЛЫ печатаются там же, где население — иначе
    # читатель отчёта не узнает, что «33» могло быть ограничено не кодом, а
    # пределом обхода, и прочтёт молчание предела как «арифметики нет».
    out.extend(chain_report(doc))
    out.extend(limit_report(doc))
    hits = doc.get("candidate_hits")
    denom = doc.get("candidate_denominator")
    out.append("  полей-кандидатов задето: "
               + ("НЕ ИЗМЕРЕНО (перечня не дали)" if hits is None
                  else f"{hits} из {denom}"))
    ident = doc.get("identity_hits")
    out.append("  полей _IDENTITY_FIELDS задето: "
               + ("НЕ ИЗМЕРЕНО (перечня не дали)" if ident is None
                  else str(ident)))
    for row in (doc.get("sites") or [])[:max_rows]:
        out.append(f"    · {Site(**row)}")
    extra = len(doc.get("sites") or []) - max_rows
    if extra > 0:
        out.append(f"    … ещё {extra} мест(а)")
    for why in doc.get("files_unmeasured") or {}:
        out.append(f"  [НЕ ИЗМЕРЕНО] {why}: "
                   f"{(doc.get('files_unmeasured') or {})[why]}")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    """``0`` — населения нет · ``1`` — есть · ``2`` — НЕ ИЗМЕРЕНО."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tree-root", default=str(_ROOT), help="корень дерева")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-rows", type=int, default=8)
    args = ap.parse_args(argv)
    from spa_core.monitoring import list_identity_census as census_mod
    identity = list(census_mod.probe.IDENTITY_FIELDS)
    doc = tally(None, identity, Path(args.tree_root))
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in report(doc, max_rows=args.max_rows):
            print(f"[ПОСТОЯННАЯ-ОПЕРАНД] {line}")
    if doc.get("status") == UNMEASURED:
        return 2
    return 1 if doc.get("population") else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
